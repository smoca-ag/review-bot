"""RAG index — walks the repo, chunks source files, loads into an ephemeral ChromaDB."""

import logging
import os

import chromadb
from opentelemetry import trace

from review_bot.config import EXCLUDE_DIRS, EXCLUDE_DOT_DIRS, INDEX_EXTENSIONS
from review_bot.utils.text import chunk_text

logger = logging.getLogger(__name__)


def create_vector_index(repo_dir: str | None) -> tuple:
    """Create an ephemeral ChromaDB vector index for the given repository.

    Returns a ``(chroma_client, collection)`` tuple, or ``(None, None)`` on
    failure or when *repo_dir* is ``None``.
    """
    chroma_client = None
    vector_index = None
    with trace.get_tracer(__name__).start_as_current_span("rag_setup") as rag_span:
        if repo_dir:
            rag_span.set_attribute("rag.repo_dir", repo_dir)
        try:
            chroma_client = chromadb.EphemeralClient()
            collection = chroma_client.create_collection("codebase")
            if repo_dir:
                indexed_count = build_vector_index(repo_dir, collection)
                if indexed_count > 0:
                    vector_index = collection
                    logger.info(f"Built vector index with {indexed_count} chunks.")
                    rag_span.set_attribute("rag.indexed_chunks", indexed_count)
        except Exception as e:
            logger.warning(f"Failed to build vector index: {e}.")
            rag_span.set_attribute("rag.error", str(e))
    return chroma_client, vector_index


def build_vector_index(repo_dir: str, collection) -> int:
    _BATCH = 1000

    count = 0
    batch_ids: list[str] = []
    batch_docs: list[str] = []
    batch_meta: list[dict[str, str | int]] = []

    def _flush() -> None:
        if batch_ids:
            collection.add(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)
            batch_ids.clear()
            batch_docs.clear()
            batch_meta.clear()

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDE_DIRS and not (EXCLUDE_DOT_DIRS and d.startswith("."))
        ]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in INDEX_EXTENSIONS:
                continue
            file_path = os.path.join(root, f)
            rel_path = os.path.relpath(file_path, repo_dir)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except (IOError, OSError):
                continue
            if text.count("\n") > 1000 or len(text) > 500_000:
                continue
            chunks = chunk_text(text, rel_path)
            if chunks:
                batch_ids.extend(c[0] for c in chunks)
                batch_docs.extend(c[1] for c in chunks)
                batch_meta.extend(
                    {"file": rel_path, "lines": start_line}
                    for _, _, start_line in chunks
                )
                count += len(chunks)
                if count >= _BATCH:
                    _flush()
                    count = 0
    _flush()
    return count
