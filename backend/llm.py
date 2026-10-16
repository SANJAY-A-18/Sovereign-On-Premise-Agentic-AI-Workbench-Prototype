"""
Ollama LLM client for Sovereign On-Premise Agentic AI Workbench.
Connects strictly to host Ollama (http://localhost:11434).
Guarantees zero cloud egress, enforces a 120s timeout, and caps num_ctx to 4096.
"""

from typing import List, Dict, Any, Optional, Union
import httpx
from backend.config import settings


class OllamaError(Exception):
    """Custom exception for Ollama errors."""
    pass


class OllamaConnectionError(OllamaError):
    """Raised when the Ollama host service is unreachable."""
    pass


class OllamaClient:
    """Client for native Ollama API on localhost."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        default_model: Optional[str] = None,
        embed_model: Optional[str] = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS
        self.default_model = default_model or settings.OLLAMA_MODEL
        self.embed_model = embed_model or settings.OLLAMA_EMBED_MODEL

    def is_reachable(self) -> bool:
        """Check if localhost Ollama service responds to health check."""
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """Fetch list of models available locally in Ollama."""
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    # Also include short names (without :latest)
                    short_names = [m.split(":")[0] for m in models if ":" in m]
                    return list(set(models + short_names))
                return []
        except Exception as e:
            raise OllamaConnectionError(
                f"Ollama is unreachable at {self.base_url}. Please ensure Ollama is running. Error: {str(e)}"
            )

    def check_health(self) -> Dict[str, Any]:
        """
        Check reachability and presence of configured chat and embedding models.
        Returns dictionary with health status and installed models.
        """
        try:
            models = self.list_models()
            chat_model_present = any(
                self.default_model in m or m in self.default_model for m in models
            )
            embed_model_present = any(
                self.embed_model in m or m in self.embed_model for m in models
            )
            return {
                "reachable": True,
                "base_url": self.base_url,
                "configured_chat_model": self.default_model,
                "chat_model_present": chat_model_present,
                "configured_embed_model": self.embed_model,
                "embed_model_present": embed_model_present,
                "available_models": models,
            }
        except OllamaConnectionError as e:
            return {
                "reachable": False,
                "base_url": self.base_url,
                "configured_chat_model": self.default_model,
                "chat_model_present": False,
                "configured_embed_model": self.embed_model,
                "embed_model_present": False,
                "error": str(e),
                "available_models": [],
            }

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.2,
        num_ctx: Optional[int] = None,
        format: Optional[str] = None,
    ) -> str:
        """
        Send a chat completion request to Ollama with non-streaming response.
        Enforces num_ctx <= 4096 and timeout.
        """
        target_model = model or self.default_model
        ctx_limit = min(num_ctx or settings.OLLAMA_NUM_CTX, 4096)

        payload = {
            "model": target_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": ctx_limit,
            },
        }
        if format:
            payload["format"] = format

        try:
            with httpx.Client(timeout=float(self.timeout)) as client:
                response = client.post(f"{self.base_url}/api/chat", json=payload)
                if response.status_code != 200:
                    raise OllamaError(
                        f"Ollama chat error (HTTP {response.status_code}): {response.text}"
                    )
                data = response.json()
                message = data.get("message", {})
                return message.get("content", "").strip()
        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Ollama is unreachable at {self.base_url}. Please ensure Ollama is running natively on the host machine. (Details: {e})"
            )
        except httpx.TimeoutException:
            raise OllamaError(
                f"Ollama call timed out after {self.timeout} seconds. The 8 GB machine may be under heavy load."
            )
        except Exception as e:
            if isinstance(e, OllamaError):
                raise
            raise OllamaError(f"Unexpected error communicating with Ollama: {str(e)}")

    def embed(
        self,
        text_or_texts: Union[str, List[str]],
        model: Optional[str] = None,
    ) -> Union[List[float], List[List[float]]]:
        """
        Generate embedding vector(s) using Ollama /api/embed endpoint.
        Consistently calls /api/embed with {"model": model, "input": [...]}.
        Supports single strings or batched lists of strings.
        Returns List[float] for a single string or List[List[float]] for a list.
        Raises OllamaError on invalid or failed responses.
        """
        target_model = model or self.embed_model
        is_single = isinstance(text_or_texts, str)
        inputs = [text_or_texts] if is_single else list(text_or_texts)

        if not inputs:
            return [] if not is_single else []

        payload = {
            "model": target_model,
            "input": inputs,
        }

        try:
            with httpx.Client(timeout=float(self.timeout)) as client:
                res = client.post(f"{self.base_url}/api/embed", json=payload)
                if res.status_code != 200:
                    raise OllamaError(
                        f"Ollama /api/embed returned HTTP {res.status_code}: {res.text}"
                    )
                data = res.json()
                embeddings = data.get("embeddings")
                if embeddings is None or not isinstance(embeddings, list):
                    raise OllamaError(
                        f"Invalid response from Ollama /api/embed: 'embeddings' field missing or not a list. Response: {res.text[:200]}"
                    )
                if len(embeddings) != len(inputs):
                    raise OllamaError(
                        f"Embedding count mismatch from Ollama /api/embed: expected {len(inputs)}, got {len(embeddings)}."
                    )
                return embeddings[0] if is_single else embeddings
        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Ollama is unreachable at {self.base_url} for embeddings. Please ensure Ollama is running natively. (Details: {e})"
            )
        except httpx.TimeoutException:
            raise OllamaError(f"Ollama embedding call timed out after {self.timeout}s.")
        except Exception as e:
            if isinstance(e, OllamaError):
                raise
            raise OllamaError(f"Error calling Ollama /api/embed: {str(e)}")


# Global singleton instance
ollama_client = OllamaClient()
