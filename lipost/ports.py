"""Publisher port: the only interface the CLI commands depend on.

Adapters (Publora today, an official LinkedIn API client later) implement
`Publisher`; commands never import an adapter's HTTP details.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class PublisherError(Exception):
    """A runtime/API failure reported by a publisher adapter (exit code 1)."""


@dataclass(frozen=True)
class Connection:
    platform_id: str
    display_name: str


@dataclass(frozen=True)
class RemoteDraft:
    draft_id: str
    status: str
    text: str
    media_count: int
    platforms: list = field(default_factory=list)


class Publisher(ABC):
    @abstractmethod
    def list_connections(self) -> list:
        """Return connected LinkedIn accounts as `Connection` objects."""

    @abstractmethod
    def create_draft(self, text: str, platform_id: str) -> str:
        """Create an unpublished draft and return its id."""

    @abstractmethod
    def upload_image(self, draft_id: str, path: str, content_type: str) -> None:
        """Attach the image file at `path` to the draft."""

    @abstractmethod
    def get_draft(self, draft_id: str) -> RemoteDraft:
        """Read the draft back from the remote service."""

    @abstractmethod
    def publish_draft(self, draft_id: str) -> dict:
        """Publish the draft now and return the service response."""

    @abstractmethod
    def delete_draft(self, draft_id: str) -> None:
        """Delete the draft remotely."""
