"""review_bot package – AI code review for Git and GitLab."""

from enum import Enum

from review_bot.backend.base_backend import BaseBackend
from review_bot.backend.git import Git  # noqa: F401
from review_bot.backend.gitlab import Gitlab  # noqa: F401
from review_bot.review_bot import review  # noqa: F401

__all__ = [
    "BackendType",
    "backend_factory",
    "review",
]


class BackendType(Enum):
    """Supported backend identifiers."""

    GIT = "git"
    GITLAB = "gitlab"


def backend_factory(backend: str | BackendType | None = None) -> type[BaseBackend]:
    """Return the backend class for the given identifier.

    Args:
        backend: Backend name ("git" / "gitlab") or a ``BackendType`` member.
                 Defaults to GitLab when *None*.

    Returns:
        A subclass of ``BaseBackend``.

    Raises:
        ValueError: If *backend* is not recognised.
    """
    if isinstance(backend, BackendType):
        backend = backend.value

    mapping: dict[str | None, type[BaseBackend]] = {
        None: Gitlab,
        BackendType.GIT.value: Git,
        BackendType.GITLAB.value: Gitlab,
    }

    cls = mapping.get(backend)
    if cls is None:
        raise ValueError(f"Unknown backend: {backend!r}")
    return cls
