"""
RAG (Retrieval-Augmented Generation) pipeline for Sovereign Workbench.
Handles text extraction from PDF, DOCX, and TXT files, chunking,
embedding via host Ollama (nomic-embed-text), and storage in embedded ChromaDB.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import re
import pypdf
import docx
import chromadb

# Strictly disable telemetry in embedded Chroma
try:
    import chromadb.telemetry.product.posthog as _chroma_ph
    _chroma_ph.Posthog.capture = lambda *args, **kwargs: None
except Exception:
    pass

from backend.config import settings
from backend.llm import ollama_client


class DocumentParser:
    """Extracts raw text from supported file types."""

    @staticmethod
    def extract_text(file_path: Path) -> str:
        ext = file_path.suffix.lower()
        if ext == ".txt":
            try:
                return file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return file_path.read_text(encoding="latin-1", errors="ignore")
        elif ext == ".pdf":
            text = []
            reader = pypdf.PdfReader(str(file_path))
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text.append(extracted)
            return "\n\n".join(text)
        elif ext == ".docx":
            doc = docx.Document(str(file_path))
            text = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(text)
        else:
            raise ValueError(f"Unsupported file format '{ext}'. Allowed: .txt, .pdf, .docx")


class TextChunker:
    """Chunks text into windows respecting sentence, line, and word boundaries."""

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> List[str]:
        size = chunk_size or settings.RAG_CHUNK_SIZE
        overlap = chunk_overlap or settings.RAG_CHUNK_OVERLAP

        if overlap >= size:
            overlap = max(0, size // 2)

        cleaned_text = text.strip()
        if not cleaned_text:
            return []

        chunks = []
        start = 0
        text_len = len(cleaned_text)

        while start < text_len:
            if start + size >= text_len:
                end = text_len
            else:
                limit = start + size
                min_break = start + max(1, size // 3)
                sub = cleaned_text[start:limit]

                # 1. Prefer paragraph break (\n\n)
                p_idx = sub.rfind('\n\n')
                if p_idx != -1 and (start + p_idx) >= min_break:
                    end = start + p_idx + 2
                else:
                    # 2. Prefer line break (\n)
                    l_idx = sub.rfind('\n')
                    if l_idx != -1 and (start + l_idx) >= min_break:
                        end = start + l_idx + 1
                    else:
                        # 3. Prefer sentence boundary (. , ? , ! )
                        sent_matches = list(re.finditer(r'[\.\?!]\s+', sub))
                        valid_sent = [m for m in sent_matches if (start + m.end()) >= min_break]
                        if valid_sent:
                            end = start + valid_sent[-1].end()
                        else:
                            # 4. Semicolon or colon
                            semi_matches = list(re.finditer(r'[;:]\s+', sub))
                            valid_semi = [m for m in semi_matches if (start + m.end()) >= min_break]
                            if valid_semi:
                                end = start + valid_semi[-1].end()
                            else:
                                # 5. Any whitespace backwards from limit (never split mid-word)
                                w_matches = list(re.finditer(r'\s+', sub))
                                if w_matches:
                                    end = start + w_matches[-1].start()
                                else:
                                    # 6. No whitespace within limit: search forward to complete word
                                    fwd = re.search(r'\s+', cleaned_text[limit:])
                                    if fwd:
                                        end = limit + fwd.start()
                                    else:
                                        end = text_len

            chunk = cleaned_text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            if end >= text_len:
                break

            # Calculate next chunk start with overlap, never starting mid-word
            target_start = end - overlap
            if target_start <= start:
                start = end
            else:
                # Advance to start of next word if target_start falls mid-word
                pos = target_start
                while pos < end and not cleaned_text[pos].isspace():
                    pos += 1
                while pos < end and cleaned_text[pos].isspace():
                    pos += 1
                if pos < end and pos > start:
                    start = pos
                else:
                    start = end

        return chunks


class VectorStore:
    """Embedded ChromaDB client persisted in ./data/chroma."""

    def __init__(self, persist_dir: Optional[str] = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        self.collection_name = "sovereign_documents"

    @property
    def collection(self):
        """Always retrieve the active collection from Chroma to avoid stale references."""
        return self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Sovereign Document Chunks for RAG"},
        )

    def add_document(
        self,
        document_id: int,
        filename: str,
        chunks: List[str],
        embedding_fn=None,
    ) -> int:
        """
        Embeds chunks using Ollama nomic-embed-text and adds to Chroma.
        Returns the number of added chunks.
        """
        if not chunks:
            return 0

        embed_func = embedding_fn or ollama_client.embed

        ids = [f"doc_{document_id}_chunk_{idx}" for idx in range(len(chunks))]
        metadatas = [
            {
                "document_id": document_id,
                "filename": filename,
                "chunk_index": idx,
            }
            for idx in range(len(chunks))
        ]

        # Attempt batch embedding; fall back to per-chunk if embedding_fn does not support batches
        try:
            raw_embeddings = embed_func(chunks)
            if raw_embeddings and isinstance(raw_embeddings[0], list):
                embeddings = raw_embeddings
            else:
                embeddings = [raw_embeddings] if len(chunks) == 1 else [embed_func(c) for c in chunks]
        except Exception:
            embeddings = [embed_func(c) for c in chunks]

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )
        return len(chunks)

    def query(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        embedding_fn=None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve top-k relevant document chunks for a query.
        Returns chunk content, filename, chunk index, and distance.
        """
        k = top_k or settings.RAG_TOP_K
        embed_func = embedding_fn or ollama_client.embed

        # If collection is empty, return empty list
        if self.collection.count() == 0:
            return []

        query_vector = embed_func(query_text)
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=min(k, self.collection.count()),
        )

        formatted_results = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if "metadatas" in results else [{}] * len(docs)
            distances = results["distances"][0] if "distances" in results else [0.0] * len(docs)

            for doc, meta, dist in zip(docs, metas, distances):
                formatted_results.append({
                    "content": doc,
                    "filename": meta.get("filename", "unknown"),
                    "chunk_index": meta.get("chunk_index", 0),
                    "document_id": meta.get("document_id"),
                    "distance": dist,
                })

        return formatted_results

    def delete_document(self, document_id: int, filename: Optional[str] = None) -> int:
        """
        Delete all vector embeddings associated with a document ID from Chroma.
        Falls back to filename matching if needed.
        """
        deleted_count = 0
        try:
            # Query existing IDs for this document
            existing = self.collection.get(where={"document_id": document_id})
            if existing and existing.get("ids"):
                self.collection.delete(ids=existing["ids"])
                deleted_count = len(existing["ids"])
            elif filename:
                existing_fn = self.collection.get(where={"filename": filename})
                if existing_fn and existing_fn.get("ids"):
                    self.collection.delete(ids=existing_fn["ids"])
                    deleted_count = len(existing_fn["ids"])
        except Exception:
            # Fallback to direct where deletion
            try:
                self.collection.delete(where={"document_id": document_id})
            except Exception:
                pass
        return deleted_count


# Global singleton instance
vector_store = VectorStore()
