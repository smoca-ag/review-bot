import os

from review_bot.config import EXCLUDE_DIRS, EXCLUDE_DOT_DIRS, INDEX_EXTENSIONS
from review_bot.text_utils import chunk_text


def build_vector_index(repo_dir: str, collection) -> int:
    count = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDE_DIRS
            and not (EXCLUDE_DOT_DIRS and d.startswith("."))
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
                ids = [c[0] for c in chunks]
                documents = [c[1] for c in chunks]
                metadatas = [
                    {"file": rel_path, "lines": start_line}
                    for _, _, start_line in chunks
                ]
                collection.add(ids=ids, documents=documents, metadatas=metadatas)
                count += len(chunks)
    return count
