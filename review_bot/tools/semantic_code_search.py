from review_bot.models import ReviewDeps
from pydantic_ai import RunContext


def semantic_code_search(ctx: RunContext[ReviewDeps], query: str, top_k: int = 5) -> str:
    """
    Searches the codebase semantically to find code that is conceptually related to a natural language query.

    Use this tool to find conceptually related code chunks when you don't know the exact keyword or file path.

    Args:
        query: The semantic search query describing what you're looking for.
        top_k: The number of top matching code chunks to return.
    """
    collection = ctx.deps.vector_index
    if collection is None:
        return "Vector search is not available (index not built)."
    try:
        results = collection.query(query_texts=[query], n_results=top_k)
        docs = results["documents"][0]
        if not docs:
            return "No relevant code chunks found."
        output_parts = []
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            similarity = 1.0 - dist
            output_parts.append(
                f"File: {meta['file']} (Line ~{meta['lines']}, Similarity: {similarity:.2f})\n```\n{doc}\n```"
            )
        return "\n---\n".join(output_parts)
    except Exception as e:
        return f"Error searching vector index: {str(e)}"