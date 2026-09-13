"""Top-level review orchestration — reads like a narrative of the review process.

Each step delegates to a well-named sub-module. The file answers *what*
happens; the sub-modules answer *how*.
"""

import logging
import sys

from opentelemetry import trace

import review_bot
from review_bot.backend.container_manager import ContainerManager
from review_bot.config import ensure_setup
from review_bot.graph import build_dependency_graph
from review_bot.orchestration import create_agents, build_review_prompt, run_agent_pipeline
from review_bot.orchestration.formatter import format_and_post_review
from review_bot.rag import create_vector_index

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)


async def review(spec: str, backend: str, post: bool = False) -> None:
    ensure_setup(logger)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("review_process") as span:
        span.set_attribute("review.spec", spec)
        span.set_attribute("review.backend", str(backend))
        span.set_attribute("review.post", post)

        mr_request = None
        container_mgr = None
        chroma_client = None
        try:
            # 1. Load MR data
            mr_request = review_bot.backend_factory(backend)(logger, spec)
            logger.info(f"Load the Merge Request {spec}")
            mr_request.load()

            if not mr_request.is_open() or mr_request.is_draft():
                logger.info("Merge Request skipped (either closed or draft).")
                return

            # 2. Setup sandbox
            container_mgr = ContainerManager(logger)
            if mr_request.repo_dir:
                container_mgr.setup(mr_request.repo_dir)

            # 3. Build knowledge indices
            chroma_client, vector_index = create_vector_index(mr_request.repo_dir)
            dep_graph = _build_dependency_graph(mr_request.repo_dir)

            # 4. Assemble prompt and run agents
            secure_base_prompt = build_review_prompt(mr_request)
            agents = create_agents()
            review_result = await run_agent_pipeline(
                agents, secure_base_prompt, mr_request, container_mgr, vector_index, dep_graph,
            )

            # 5. Format and post results
            format_and_post_review(logger, mr_request, review_result, post)
        except Exception as e:
            logger.error(f"CRITICAL: Flow failed: {e}", exc_info=True)
            if post and mr_request is not None:
                try:
                    # Only the exception type is posted: messages can embed
                    # paths, hostnames, or config fragments; the full error
                    # stays in the logs.
                    mr_request.post_review(
                        "## AI Review Error\n\nThe AI reviewer failed to complete "
                        f"this review (`{type(e).__name__}`). "
                        "Check the bot logs for the full traceback."
                    )
                except Exception:
                    logger.exception(
                        "Failed to post the error comment to the merge request"
                    )
        finally:
            if chroma_client is not None:
                chroma_client.close()
            if container_mgr is not None:
                container_mgr.cleanup()
            if mr_request is not None:
                mr_request.cleanup()


def _build_dependency_graph(repo_dir: str | None):
    """Build the dependency graph if a repo dir is available."""
    with trace.get_tracer(__name__).start_as_current_span("dependency_graph_build"):
        try:
            if repo_dir:
                dep_graph = build_dependency_graph(repo_dir)
                mod_count = len(dep_graph.modules)
                imp_count = sum(len(m.imports) for m in dep_graph.modules.values())
                logger.info(f"Built dependency graph: {mod_count} modules, {imp_count} imports.")
                return dep_graph
        except Exception as e:
            logger.warning(f"Failed to build dependency graph: {e}.")
    return None