"""Format-independent secure publication primitives.

Scientific serializers should only receive the streams exposed by this module.
Path authorization, private staging, descriptor identity checks, exclusive
publication, and best-effort identity-aware cleanup stay platform-specific.
"""

from __future__ import annotations

import io
import os
import secrets
import stat
from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import BinaryIO, TextIO

from .utility_helpers import (
    GrantedWriteDestination,
    open_verified_write_grant,
    verify_file_grant,
)

PublicationStream = BinaryIO | TextIO
FileIdentity = tuple[int, int]


class SecurePublication(ABC):
    """Platform-neutral lifecycle for publishing one verified artifact."""

    @property
    @abstractmethod
    def path(self) -> Path:
        """Return the authorized user-visible destination path."""

    @property
    @abstractmethod
    def filename(self) -> str:
        """Return the destination's final, single-component filename."""

    @abstractmethod
    def revalidate(self, changed_message: str) -> None:
        """Revalidate the destination grant and pinned parent identity."""

    @abstractmethod
    def assert_destination_available(self) -> None:
        """Reject any existing entry at the authorized destination."""

    @abstractmethod
    def reserve_staging(self, extension: str) -> None:
        """Reserve a private, same-directory staging artifact exclusively."""

    @abstractmethod
    def open_writer(
        self, mode: str, *, encoding: str | None
    ) -> AbstractContextManager[PublicationStream]:
        """Open the exclusively reserved artifact and flush it on success."""

    @abstractmethod
    def open_reader(
        self, mode: str, *, encoding: str | None
    ) -> AbstractContextManager[PublicationStream]:
        """Reopen the owned staging artifact for scientific verification."""

    @abstractmethod
    def verified_size(self) -> int:
        """Return the nonzero byte size after a final ownership check."""

    @abstractmethod
    def publish(self) -> list[str]:
        """Publish without replacement and return nonfatal cleanup warnings."""

    @abstractmethod
    def close(self) -> None:
        """Close handles and remove only staging entries still believed owned."""


def _identity(file_stat: os.stat_result) -> FileIdentity:
    return (file_stat.st_dev, file_stat.st_ino)


def _unlink_owned_entry(
    directory_descriptor: int,
    name: str,
    identity: FileIdentity,
) -> None:
    """Best-effort removal after a no-follow identity check.

    Portable POSIX does not provide an atomic compare-identity-and-unlink
    operation. The random, mode-0700 staging directory and pinned directory
    descriptor are the primary boundary; this check avoids knowingly unlinking
    a replacement but cannot eliminate a same-user swap between stat and unlink.
    """
    try:
        current = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if stat.S_ISREG(current.st_mode) and _identity(current) == identity:
        os.unlink(name, dir_fd=directory_descriptor)


def _rmdir_owned_entry(
    parent_descriptor: int,
    name: str,
    identity: FileIdentity,
) -> bool:
    """Best-effort removal after a no-follow identity check.

    As with ``_unlink_owned_entry``, portable POSIX cannot combine the identity
    comparison and removal into one operation.  A mismatch is retained, but a
    same-user replacement in the small stat-to-rmdir interval cannot be ruled
    out.  The unguessable, mode-0700 staging directory is the primary boundary.
    """
    try:
        current = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return True
    if not stat.S_ISDIR(current.st_mode):
        return False
    if _identity(current) != identity:
        return False
    os.rmdir(name, dir_fd=parent_descriptor)
    return True


@contextmanager
def _descriptor_stream(
    descriptor: int,
    mode: str,
    *,
    encoding: str | None,
) -> Generator[PublicationStream, None, None]:
    """Expose a descriptor without transferring its ownership to the stream.

    ``closefd=False`` makes this helper the sole descriptor owner even when
    stream construction or teardown fails.  That keeps error paths predictable
    and also mirrors the explicit handle ownership required by the Windows
    adapter.
    """
    if mode not in {"r", "rb", "w", "wb"}:
        raise ValueError(f"Unsupported secure publication stream mode: {mode}")

    raw_stream: io.FileIO | None = None
    stream: PublicationStream | None = None
    try:
        raw_stream = io.FileIO(
            descriptor,
            mode.replace("b", ""),
            closefd=False,
        )
        if "b" in mode:
            stream = raw_stream
        else:
            stream = io.TextIOWrapper(raw_stream, encoding=encoding or "utf-8")
        yield stream
    finally:
        try:
            if stream is not None:
                stream.close()
            elif raw_stream is not None:
                raw_stream.close()
        finally:
            os.close(descriptor)


class PosixSecurePublication(SecurePublication):
    """Descriptor-relative POSIX publication with exclusive hard-link publish."""

    def __init__(
        self,
        destination: GrantedWriteDestination,
        destination_path: str,
        destination_grant: str,
    ) -> None:
        self._path = destination.path
        self._parent_descriptor = destination.parent_descriptor
        self._filename = destination.filename
        self._destination_path = destination_path
        self._destination_grant = destination_grant

        self._staging_descriptor = -1
        self._staging_name: str | None = None
        self._staging_identity: FileIdentity | None = None
        self._artifact_name: str | None = None
        self._artifact_identity: FileIdentity | None = None
        self._writer_descriptor = -1
        self._writer_completed = False
        self._reader_completed = False
        self._size_verified = False
        self._published = False
        self._failed = False
        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def filename(self) -> str:
        return self._filename

    def revalidate(self, changed_message: str) -> None:
        verified_path = verify_file_grant(
            self._destination_path,
            self._destination_grant,
            access="write",
            must_exist=False,
        )
        if verified_path != self._path:
            raise PermissionError(changed_message)

    def assert_destination_available(self) -> None:
        try:
            os.stat(
                self._filename,
                dir_fd=self._parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        raise FileExistsError(f"Destination already exists: {self._path}")

    def reserve_staging(self, extension: str) -> None:
        if self._closed:
            raise RuntimeError("The secure publication is already closed")
        if self._failed:
            raise RuntimeError("The secure publication has already failed")
        if self._published:
            raise RuntimeError("The secure publication is already published")
        if self._staging_name is not None:
            raise RuntimeError("A private staging artifact is already reserved")

        for _ in range(10):
            candidate_name = f".stingray-export-{secrets.token_hex(16)}"
            try:
                os.mkdir(
                    candidate_name,
                    0o700,
                    dir_fd=self._parent_descriptor,
                )
            except FileExistsError:
                continue
            self._staging_name = candidate_name
            break
        else:
            raise FileExistsError("Could not reserve a private export staging area")

        directory_flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            directory_flags |= os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        self._staging_descriptor = os.open(
            self._staging_name,
            directory_flags,
            dir_fd=self._parent_descriptor,
        )
        staging_stat = os.fstat(self._staging_descriptor)
        if not stat.S_ISDIR(staging_stat.st_mode):
            raise PermissionError("The private export staging area was replaced")
        self._staging_identity = _identity(staging_stat)

        self._artifact_name = f"artifact{extension}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(
            self._artifact_name,
            flags,
            0o600,
            dir_fd=self._staging_descriptor,
        )
        try:
            reserved_stat = os.fstat(descriptor)
        except Exception:
            os.close(descriptor)
            raise
        self._artifact_identity = _identity(reserved_stat)
        self._writer_descriptor = descriptor

    def _require_artifact(self) -> tuple[str, FileIdentity]:
        if self._artifact_name is None or self._artifact_identity is None:
            raise RuntimeError("No private staging artifact is reserved")
        return self._artifact_name, self._artifact_identity

    @contextmanager
    def open_writer(
        self, mode: str, *, encoding: str | None
    ) -> Generator[PublicationStream, None, None]:
        self._require_artifact()
        if self._closed:
            raise RuntimeError("The secure publication is already closed")
        if self._failed:
            raise RuntimeError("The secure publication has already failed")
        if self._writer_completed:
            raise RuntimeError("The private staging writer already completed")
        if self._writer_descriptor < 0:
            raise RuntimeError("The private staging writer is unavailable")
        descriptor = self._writer_descriptor
        self._writer_descriptor = -1
        try:
            with _descriptor_stream(descriptor, mode, encoding=encoding) as stream:
                yield stream
                stream.flush()
                os.fsync(descriptor)
        except BaseException:
            self._failed = True
            raise
        self._writer_completed = True

    def _assert_staged_identity(self, changed_message: str) -> os.stat_result:
        artifact_name, artifact_identity = self._require_artifact()
        current = os.stat(
            artifact_name,
            dir_fd=self._staging_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(current.st_mode) or _identity(current) != artifact_identity:
            raise PermissionError(changed_message)
        return current

    @contextmanager
    def open_reader(
        self, mode: str, *, encoding: str | None
    ) -> Generator[PublicationStream, None, None]:
        if self._closed:
            raise RuntimeError("The secure publication is already closed")
        if self._failed:
            raise RuntimeError("The secure publication has already failed")
        if not self._writer_completed:
            raise RuntimeError("The private staging writer has not completed")
        if self._reader_completed:
            raise RuntimeError("The private staging reader already completed")
        self.revalidate("Written artifact path changed during verification")
        artifact_name, artifact_identity = self._require_artifact()
        self._assert_staged_identity(
            "Export destination was replaced before verification"
        )

        read_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            read_flags |= os.O_NOFOLLOW
        read_descriptor = os.open(
            artifact_name,
            read_flags,
            dir_fd=self._staging_descriptor,
        )
        try:
            read_stat = os.fstat(read_descriptor)
        except Exception:
            os.close(read_descriptor)
            raise
        if _identity(read_stat) != artifact_identity:
            os.close(read_descriptor)
            raise PermissionError("Export destination was replaced before verification")
        try:
            with _descriptor_stream(
                read_descriptor,
                mode,
                encoding=encoding,
            ) as stream:
                yield stream
        except BaseException:
            self._failed = True
            raise
        self._reader_completed = True

    def verified_size(self) -> int:
        if self._closed:
            raise RuntimeError("The secure publication is already closed")
        if self._failed:
            raise RuntimeError("The secure publication has already failed")
        if not self._reader_completed:
            raise RuntimeError("Scientific reopen verification has not completed")
        if self._published:
            raise RuntimeError("The secure publication is already published")
        final_stat = self._assert_staged_identity(
            "Export destination was replaced during verification"
        )
        byte_size = final_stat.st_size
        if byte_size < 1:
            raise ValueError("Written artifact is empty")
        self._size_verified = True
        return byte_size

    def publish(self) -> list[str]:
        if self._closed:
            raise RuntimeError("The secure publication is already closed")
        if self._failed:
            raise RuntimeError("The secure publication has already failed")
        if self._published:
            raise RuntimeError("The secure publication is already published")
        if not self._size_verified:
            raise RuntimeError("The staged artifact has not completed verification")
        self.revalidate("The selected destination path changed")
        artifact_name, artifact_identity = self._require_artifact()
        try:
            os.link(
                artifact_name,
                self._filename,
                src_dir_fd=self._staging_descriptor,
                dst_dir_fd=self._parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise FileExistsError(f"Destination already exists: {self._path}") from exc
        published_stat = os.stat(
            self._filename,
            dir_fd=self._parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(published_stat.st_mode)
            or _identity(published_stat) != artifact_identity
        ):
            raise PermissionError(
                "Export destination changed during atomic publication"
            )

        warnings: list[str] = []
        try:
            _unlink_owned_entry(
                self._staging_descriptor,
                artifact_name,
                artifact_identity,
            )
            os.close(self._staging_descriptor)
            self._staging_descriptor = -1
            if (
                self._staging_name is None
                or self._staging_identity is None
                or not _rmdir_owned_entry(
                    self._parent_descriptor,
                    self._staging_name,
                    self._staging_identity,
                )
            ):
                raise OSError("private staging directory identity changed")
        except OSError as cleanup_error:
            warnings.append(
                "Export succeeded, but its private staging artifact could not be "
                f"removed safely ({cleanup_error})."
            )

        # Successful publication never retries a failed name-based cleanup.
        # A retry after an identity mismatch could target an unrelated entry.
        self._artifact_name = None
        self._artifact_identity = None
        self._staging_name = None
        self._staging_identity = None
        self._published = True
        return warnings

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._writer_descriptor >= 0:
            try:
                os.close(self._writer_descriptor)
            except OSError:
                pass
            self._writer_descriptor = -1
        if (
            self._staging_descriptor >= 0
            and self._artifact_name is not None
            and self._artifact_identity is not None
        ):
            try:
                _unlink_owned_entry(
                    self._staging_descriptor,
                    self._artifact_name,
                    self._artifact_identity,
                )
            except OSError:
                pass
        if self._staging_descriptor >= 0:
            try:
                os.close(self._staging_descriptor)
            except OSError:
                pass
            self._staging_descriptor = -1
        if self._staging_name is not None and self._staging_identity is not None:
            try:
                _rmdir_owned_entry(
                    self._parent_descriptor,
                    self._staging_name,
                    self._staging_identity,
                )
            except OSError:
                # Never broaden cleanup or delete an unexpected entry.
                pass


def _platform_name() -> str:
    return os.name


@contextmanager
def open_secure_publication(
    destination_path: str,
    destination_grant: str,
) -> Generator[SecurePublication, None, None]:
    """Open the secure publication implementation for the current platform."""
    if _platform_name() != "posix":
        raise NotImplementedError(
            "Secure export publication is not supported on this platform"
        )

    with open_verified_write_grant(
        destination_path,
        destination_grant,
    ) as destination:
        publication = PosixSecurePublication(
            destination,
            destination_path,
            destination_grant,
        )
        try:
            yield publication
        finally:
            publication.close()
