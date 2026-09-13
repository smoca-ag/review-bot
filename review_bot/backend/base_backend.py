import logging


class BaseBackend:
    """Abstract backend providing MR/repo metadata across GitLab and local Git.

    Responsibilities: MR data, diff retrieval, repo directory lifecycle.
    Container management lives in ``ContainerManager``.
    Review posting lives in ``GitlabReviewPoster`` (GitLab only).
    """

    def __init__(self, logger: logging.Logger, url: str) -> None:
        self.url = url
        self.repo_dir: str | None = None
        self.logger: logging.Logger = logger

    def load(self) -> None:
        """Fetch MR details, diffs, discussions, and clone the repository."""
        raise NotImplementedError

    def is_open(self) -> bool:
        """Returns True if the merge request is open and eligible for review."""
        return True

    def is_draft(self) -> bool:
        """Returns True if the merge request is a draft/WIP."""
        return False

    def diff(self) -> str:
        raise NotImplementedError

    def description(self) -> str | None:
        return None

    def title(self) -> str | None:
        return None

    def cleanup(self) -> None:
        """Clean up repository resources (subclasses override for temp dirs)."""
        pass

    def post_review(self, text: str) -> None:
        """Post a top-level review comment (GitLab only; no-op for other backends)."""
        pass

    def post_line_review(self, text: str, new_path: str, new_position: int) -> None:
        """Post an inline comment (GitLab only; no-op for other backends)."""
        pass
