"""Per-book coordination with a local implementation and optional ZooKeeper."""

from contextlib import contextmanager
from threading import Lock
from typing import Iterator, Protocol


class BookCoordinator(Protocol):
    @contextmanager
    def lock(self, book_id: str) -> Iterator[None]:
        ...

    def ready(self) -> None:
        ...

    def close(self) -> None:
        ...


class InMemoryCoordinator:
    def __init__(self):
        self._locks: dict[str, Lock] = {}
        self._guard = Lock()

    @contextmanager
    def lock(self, book_id: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(book_id, Lock())
        with lock:
            yield

    def ready(self) -> None:
        return None

    def close(self) -> None:
        return None


def configured_coordinator() -> BookCoordinator:
    hosts = __import__("os").environ.get("ZOOKEEPER_HOSTS")
    if not hosts:
        return InMemoryCoordinator()
    try:
        from kazoo.client import KazooClient
    except ImportError as error:
        raise RuntimeError("ZOOKEEPER_HOSTS requires the kazoo dependency") from error

    class ZooKeeperCoordinator:
        def __init__(self):
            self.client = KazooClient(hosts=hosts)
            self.client.start()

        @contextmanager
        def lock(self, book_id: str) -> Iterator[None]:
            from kazoo.recipe.lock import Lock as ZooLock

            lock = ZooLock(self.client, f"/library/books/{book_id}")
            with lock:
                yield

        def ready(self) -> None:
            from kazoo.protocol.states import KazooState

            if self.client.state != KazooState.CONNECTED:
                raise RuntimeError("ZooKeeper is not connected")

        def close(self) -> None:
            self.client.stop()
            self.client.close()

    return ZooKeeperCoordinator()
