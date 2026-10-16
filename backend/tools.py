"""
Tool registry and safe implementations for Sovereign Workbench.
Every tool has: name, description, parameters schema, risk level ('low' or 'high'), and function.
Includes safe AST calculator, path-guarded file reader, SELECT-only SQLite reader, and RAG document search.
"""

import ast
import operator
from pathlib import Path
import re
import sqlite3
from typing import Dict, Any, Callable, Optional, List
from pydantic import BaseModel

from backend.config import settings
from backend.rag import vector_store


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    risk_level: str  # "low" or "high"


# ==============================================================================
# 1. Safe Calculator (AST evaluation only, zero eval())
# ==============================================================================

# Allowed operators mapping
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_ast_node(node):
    """Recursively evaluate an AST node strictly restricted to math operations."""
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body)
    elif isinstance(node, ast.Constant):  # Python 3.8+ numbers
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")
    elif isinstance(node, ast.Num):  # Fallback for older python ast
        return node.n
    elif isinstance(node, ast.BinOp):
        left = _eval_ast_node(node.left)
        right = _eval_ast_node(node.right)
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
        # Guard against zero division
        if op_type in (ast.Div, ast.Mod) and right == 0:
            raise ValueError("Division by zero is undefined")
        # Guard against excessive powers (e.g. 9999**9999) to protect 8GB RAM
        if op_type == ast.Pow and (abs(right) > 1000 or abs(left) > 1000000):
            raise ValueError("Exponentiation values too large (preventing memory exhaustion)")
        return SAFE_OPERATORS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_ast_node(node.operand)
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return SAFE_OPERATORS[op_type](operand)
    else:
        raise ValueError(f"Dangerous or unsupported expression element: {type(node).__name__}")


def calculator(expression: str) -> str:
    """
    Safely evaluate a mathematical expression using AST parsing.
    Allows only numbers, +, -, *, /, **, %, and parentheses.
    Rejects any code execution, function calls, or malicious patterns.
    """
    cleaned = expression.strip()
    if not cleaned:
        return "Error: Empty expression provided."
    try:
        parsed = ast.parse(cleaned, mode="eval")
        result = _eval_ast_node(parsed)
        return str(result)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as e:
        return f"Calculation Error: {str(e)}"
    except Exception as e:
        return f"Calculation Error: Invalid expression ({str(e)})"


# ==============================================================================
# 2. Sandboxed File Reader (Restricted strictly to ./data/uploads)
# ==============================================================================

def read_file(filename: str) -> str:
    """
    Read file contents strictly from ./data/uploads.
    Rejects any path traversal attempts (e.g. '..', absolute paths).
    """
    upload_root = Path(settings.UPLOAD_DIR).resolve()

    # Reject obvious traversal indicators before resolution
    if ".." in filename or ":" in filename or Path(filename).is_absolute() or filename.startswith(("/", "\\")):
        return "Security Error: Path traversal attempt detected. Access denied."

    target_path = (upload_root / filename).resolve()

    # Verify that the resolved target is inside upload_root
    try:
        target_path.relative_to(upload_root)
    except ValueError:
        return "Security Error: Access outside the uploads directory is forbidden."

    if not target_path.exists():
        return f"Error: File '{filename}' not found in uploads directory."
    if not target_path.is_file():
        return f"Error: Target '{filename}' is not a regular file."

    try:
        content = target_path.read_text(encoding="utf-8", errors="replace")
        # Cap returned content to 3000 chars to respect memory budget
        if len(content) > 3000:
            return content[:3000] + f"\n... [Truncated: Total length {len(content)} characters]"
        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


# ==============================================================================
# 3. Read SQL (SELECT-only on data/demo.db)
# ==============================================================================

def read_sql(query: str) -> str:
    """
    Execute a single read-only SELECT query against demo.db (e.g. students table).
    Rejects any non-SELECT statements, mutations, or multiple queries.
    """
    cleaned = query.strip()
    if not cleaned:
        return "Error: Empty SQL query provided."

    # Strip single trailing semicolon if present
    normalized = cleaned.rstrip(";").strip()

    # Reject multiple statements
    if ";" in normalized:
        return "Security Error: Multiple SQL statements are not permitted."

    # Reject SQL comments to prevent evasion tricks
    if "--" in normalized or "/*" in normalized or "*/" in normalized:
        return "Security Error: SQL comments are not permitted."

    # Validate that the statement begins strictly with SELECT
    tokens = normalized.split()
    if not tokens or tokens[0].upper() != "SELECT":
        return "Security Error: Only single SELECT queries are permitted on the demo database."

    # Disallow dangerous SQL keywords anywhere in the query
    disallowed_keywords = {
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
        "REPLACE", "EXEC", "EXECUTE", "PRAGMA", "ATTACH", "DETACH", "VACUUM",
        "SQLITE_MASTER", "SQLITE_SCHEMA", "SQLITE_TEMP_MASTER", "INTO"
    }
    upper_query_words = set(re.sub(r"[^A-Z0-9_]", "", w.upper()) for w in tokens)
    forbidden = upper_query_words.intersection(disallowed_keywords)
    if forbidden:
        return f"Security Error: Disallowed keyword(s) detected: {', '.join(sorted(forbidden))}"

    if settings.DEMO_DATABASE_URL.startswith("sqlite:///"):
        demo_db_path = Path(settings.DEMO_DATABASE_URL.replace("sqlite:///", "")).resolve()
    else:
        demo_db_path = (Path(settings.DATA_DIR) / "demo.db").resolve()
    if not demo_db_path.exists():
        return f"Error: Demo database ({demo_db_path.name}) has not been initialized."

    try:
        conn = sqlite3.connect(f"file:{demo_db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute(normalized)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(50)  # Cap at 50 rows for memory safety
        conn.close()

        if not rows:
            return f"Query returned 0 rows for columns: {columns}"

        # Format as a clean text table
        header = " | ".join(columns)
        separator = "-" * len(header)
        formatted_rows = [" | ".join(str(val) for val in row) for row in rows]
        return f"{header}\n{separator}\n" + "\n".join(formatted_rows)
    except Exception as e:
        return f"SQL Error: {str(e)}"


# ==============================================================================
# 4. Search Documents (RAG retrieval)
# ==============================================================================

def search_documents(query: str) -> str:
    """
    Retrieve top-k chunks from the Chroma vector store based on query similarity.
    Returns chunk text along with filename and chunk index for citations.
    """
    results = vector_store.query(query, top_k=settings.RAG_TOP_K)
    if not results:
        return "No relevant document chunks found in the knowledge base."

    output = []
    for r in results:
        citation = f"[Source: {r['filename']} | Chunk #{r['chunk_index']}]"
        output.append(f"{citation}\n{r['content']}")

    return "\n\n---\n\n".join(output)


# ==============================================================================
# 5. Future Sandboxed Python Tool (Placeholder)
# ==============================================================================

def execute_python_sandbox(code: str) -> str:
    """
    PLACEHOLDER: Future sandboxed Python execution tool.
    Currently stubbed out as per prototype specifications.
    """
    raise NotImplementedError(
        "Python sandbox tool is reserved for future implementation with isolated containerization."
    )


# ==============================================================================
# Tool Registry
# ==============================================================================

class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        risk_level: str,
        func: Callable[..., Any],
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.risk_level = risk_level  # "low" or "high"
        self.func = func

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            risk_level=self.risk_level,
        )


class ToolRegistry:
    """Central registry of available tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._register_default_tools()

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_all(self) -> List[Tool]:
        return list(self._tools.values())

    def list_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "risk_level": t.risk_level,
            }
            for t in self._tools.values()
        ]

    def _register_default_tools(self):
        # 1. search_documents
        self.register(
            Tool(
                name="search_documents",
                description="Search uploaded documents using semantic similarity (RAG). Returns top relevant text chunks with citations.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query or question to find in documents",
                        }
                    },
                    "required": ["query"],
                },
                risk_level="low",
                func=search_documents,
            )
        )

        # 2. calculator
        self.register(
            Tool(
                name="calculator",
                description="Safe arithmetic calculator. Solves mathematical expressions using numbers, +, -, *, /, **, %, and parentheses. Never use code or imports.",
                parameters={
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "Mathematical expression string, e.g. '(12 * 8) + 4'",
                        }
                    },
                    "required": ["expression"],
                },
                risk_level="low",
                func=calculator,
            )
        )

        # 3. read_file
        self.register(
            Tool(
                name="read_file",
                description="Read the contents of an uploaded file from the data/uploads directory. Path traversal is strictly forbidden.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "The simple filename of the uploaded file to read (e.g. 'notes.txt')",
                        }
                    },
                    "required": ["filename"],
                },
                risk_level="low",
                func=read_file,
            )
        )

        # 4. read_sql
        self.register(
            Tool(
                name="read_sql",
                description="Run a single read-only SELECT query against the demo database containing the 'students' table with columns: id, name, department, marks, gpa, graduation_year. (High risk - requires human approval).",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "A single read-only SELECT SQL query, e.g. 'SELECT name, marks FROM students WHERE marks > 80'",
                        }
                    },
                    "required": ["query"],
                },
                risk_level="high",
                func=read_sql,
            )
        )


tool_registry = ToolRegistry()
