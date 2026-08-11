"""Real-Windows coverage for FILE_ID_INFO grants and NTFS publication."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

import services.utility_helpers as utility_helpers
from services.secure_publication import open_secure_publication
from services.utility_helpers import (
    FILE_GRANT_MAX_FUTURE_SECONDS,
    FILE_GRANT_SECRET_ENV,
    FILE_GRANT_TTL_SECONDS,
    FileGrantEligibilityError,
    issue_file_grant,
    open_verified_read_grant,
    verify_file_grant,
)
from services.windows_secure_fs import (
    FILE_RENAME_INFORMATION_CLASS,
    WINDOWS_FILE_GRANT_VERSION,
    WindowsFileIdentity,
    WindowsNativeApi,
    _build_file_rename_information,
    _FILE_RENAME_INFORMATION,
    _FILE_RENAME_OPERATION,
    canonicalize_windows_path,
    pin_windows_path,
    validate_windows_path_text,
)

TEST_SECRET = "windows-secure-publication-test-secret-32-bytes"
WINDOWS_REQUIRED_ENV = "STINGRAY_REQUIRE_WINDOWS_SECURE_EXPORT"

requires_windows = pytest.mark.skipif(
    os.name != "nt",
    reason="Real Windows NTFS handles are required",
)


@pytest.fixture(autouse=True)
def file_grant_secret(monkeypatch):
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, TEST_SECRET)


def _write_grant(path: Path) -> str:
    return issue_file_grant(str(path), access="write").grant


def test_windows_ci_capability_gate_cannot_pass_via_skips(tmp_path):
    """The dedicated workflow sets the gate, making Windows capability required."""
    if os.environ.get(WINDOWS_REQUIRED_ENV) != "1":
        return
    assert os.name == "nt"
    assert WindowsNativeApi().kernel32 is not None
    issued = issue_file_grant(str(tmp_path / "capability.bin"), access="write")
    assert issued.grant.startswith(f"{WINDOWS_FILE_GRANT_VERSION}.")


def test_windows_path_canonicalizes_drive_case_and_separators():
    canonical = canonicalize_windows_path("c:/Science/Events.fits")
    assert str(canonical) == r"C:\Science\Events.fits"
    assert str(canonicalize_windows_path("d:/artifact.bin")) == r"D:\artifact.bin"
    assert str(canonicalize_windows_path("e:/")) == "E:\\"


def test_windows_native_rename_buffer_matches_file_rename_information_abi():
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(_FILE_RENAME_OPERATION) == 4
    assert _FILE_RENAME_INFORMATION.RootDirectory.offset == (
        8 if pointer_size == 8 else 4
    )
    assert _FILE_RENAME_INFORMATION.FileNameLength.offset == (
        16 if pointer_size == 8 else 8
    )
    assert _FILE_RENAME_INFORMATION.FileName.offset == (20 if pointer_size == 8 else 12)
    assert ctypes.sizeof(_FILE_RENAME_INFORMATION) == (24 if pointer_size == 8 else 16)

    parent_handle = 0x01020304 if pointer_size == 4 else 0x0102030405060708
    filename = "artifact.bin"
    encoded_name = filename.encode("utf-16-le")
    buffer, buffer_size = _build_file_rename_information(parent_handle, filename)
    raw = bytes(buffer)

    assert FILE_RENAME_INFORMATION_CLASS == 10
    assert buffer_size == ctypes.sizeof(_FILE_RENAME_INFORMATION) + len(encoded_name)
    assert raw[:4] == b"\0" * 4
    root_offset = _FILE_RENAME_INFORMATION.RootDirectory.offset
    assert int.from_bytes(raw[root_offset : root_offset + pointer_size], "little") == (
        parent_handle
    )
    length_offset = _FILE_RENAME_INFORMATION.FileNameLength.offset
    assert int.from_bytes(raw[length_offset : length_offset + 4], "little") == len(
        encoded_name
    )
    name_offset = _FILE_RENAME_INFORMATION.FileName.offset
    assert raw[name_offset : name_offset + len(encoded_name)] == encoded_name


def test_windows_native_rename_uses_nt_class_10_and_relative_parent_handle():
    captured: dict[str, object] = {}

    class FakeNtdll:
        def NtSetInformationFile(
            self,
            handle,
            io_status,
            buffer,
            buffer_size,
            information_class,
        ):
            captured["handle"] = handle.value
            captured["io_status"] = io_status
            captured["buffer"] = bytes(buffer)
            captured["buffer_size"] = buffer_size
            captured["information_class"] = information_class
            return 0

        def RtlNtStatusToDosError(self, status):
            raise AssertionError(
                f"Successful NT status was unexpectedly mapped: {status}"
            )

    api = object.__new__(WindowsNativeApi)
    api.ntdll = FakeNtdll()
    parent_handle = 0x1234
    filename = "artifact.bin"
    api.rename_no_replace(0x5678, parent_handle, filename)

    assert captured["handle"] == 0x5678
    assert captured["information_class"] == FILE_RENAME_INFORMATION_CLASS
    assert captured["buffer_size"] == len(captured["buffer"])
    raw = captured["buffer"]
    assert isinstance(raw, bytes)
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    root_offset = _FILE_RENAME_INFORMATION.RootDirectory.offset
    assert int.from_bytes(raw[root_offset : root_offset + pointer_size], "little") == (
        parent_handle
    )


@pytest.mark.parametrize(
    "unsafe_path, expected",
    [
        (r"\\server\share\events.fits", "UNC"),
        (r"\\?\C:\science\events.fits", "UNC"),
        (r"C:\science\events.fits:stream", "alternate data streams"),
        (r"C:\science\CON.fits", "reserved device"),
        (r"C:\science\COM1 .fits", "reserved device"),
        (r"C:\science\event.fits. ", "space or period"),
        (r"C:\science\..\event.fits", "dot components"),
    ],
)
def test_windows_path_policy_rejects_ambiguous_names(unsafe_path, expected):
    with pytest.raises(ValueError, match=expected):
        validate_windows_path_text(unsafe_path)


@requires_windows
def test_windows_drive_root_is_really_pinned(tmp_path):
    drive_root = Path(tmp_path.anchor)
    with pin_windows_path(drive_root, directory=True) as pinned:
        assert pinned.path == drive_root
        assert pinned.directory is True
        assert len(pinned.identity.file_id) == 16


@requires_windows
def test_windows_v3_grant_pins_read_identity_and_closes_handles(tmp_path):
    selected = tmp_path / "events.fits"
    selected.write_bytes(b"selected scientific bytes")
    replacement = tmp_path / "replacement.fits"
    replacement.write_bytes(b"replacement")

    issued = issue_file_grant(str(selected), access="read")
    parts = issued.grant.split(".")
    assert parts[0] == WINDOWS_FILE_GRANT_VERSION
    assert len(parts[2]) == 16
    assert len(parts[3]) == 32
    assert (
        verify_file_grant(
            str(selected),
            issued.grant,
            access="read",
            must_exist=True,
        )
        == selected
    )
    adjacent = tmp_path / "adjacent.fits"
    adjacent.write_bytes(b"adjacent")
    with pytest.raises(PermissionError, match="does not match"):
        verify_file_grant(str(adjacent), issued.grant, access="read", must_exist=True)
    with pytest.raises(PermissionError, match="does not match"):
        verify_file_grant(str(selected), issued.grant, access="write", must_exist=False)

    with open_verified_read_grant(str(selected), issued.grant) as granted:
        with pytest.raises(OSError):
            os.replace(replacement, selected)
        assert granted.stream.read() == b"selected scientific bytes"
        assert granted.size_bytes == len(b"selected scientific bytes")

    # All retained prefix/file handles are gone after the grant context.
    os.replace(replacement, selected)
    assert selected.read_bytes() == b"replacement"


@requires_windows
def test_windows_v3_grants_reject_stale_file_and_parent_identities(tmp_path):
    selected = tmp_path / "events.fits"
    selected.write_bytes(b"original")
    stale_read_grant = issue_file_grant(str(selected), access="read").grant
    replacement = tmp_path / "replacement.fits"
    replacement.write_bytes(b"replacement")
    os.replace(replacement, selected)
    with pytest.raises(PermissionError, match="identity changed"):
        verify_file_grant(
            str(selected), stale_read_grant, access="read", must_exist=True
        )

    parent = tmp_path / "selected-parent"
    parent.mkdir()
    destination = parent / "artifact.bin"
    stale_write_grant = issue_file_grant(str(destination), access="write").grant
    moved_parent = tmp_path / "original-parent"
    parent.rename(moved_parent)
    parent.mkdir()
    with pytest.raises(PermissionError, match="directory identity changed"):
        with open_secure_publication(str(destination), stale_write_grant):
            pytest.fail("A stale Windows parent identity must never be yielded")


@requires_windows
def test_windows_v3_grant_rejects_malformed_and_future_tokens(tmp_path, monkeypatch):
    selected = tmp_path / "events.fits"
    selected.write_bytes(b"events")
    issued = issue_file_grant(str(selected), access="read")
    malformed = [
        issued.grant.replace("v3.", "v2.", 1),
        "v3.123.bad.00000000000000000000000000000000." + "0" * 64,
        "v3.123.0000000000000000." + "f" * 31 + "." + "0" * 64,
    ]
    for token in malformed:
        with pytest.raises(PermissionError):
            verify_file_grant(str(selected), token, access="read", must_exist=True)

    now = int(time.time())
    monkeypatch.setattr("services.utility_helpers.time.time", lambda: now)
    future = issue_file_grant(str(selected), access="read")
    monkeypatch.setattr(
        "services.utility_helpers.time.time",
        lambda: now - FILE_GRANT_MAX_FUTURE_SECONDS,
    )
    with pytest.raises(PermissionError, match="expiry is invalid"):
        verify_file_grant(str(selected), future.grant, access="read", must_exist=True)


@requires_windows
def test_windows_publication_is_seekable_verified_and_handle_clean(
    tmp_path, monkeypatch
):
    parent = tmp_path / "selected-parent"
    parent.mkdir()
    destination = parent / "artifact.hdf5"
    moved_parent = tmp_path / "moved-parent"

    with open_secure_publication(
        str(destination),
        _write_grant(destination),
    ) as publication:
        future_time = int(time.time()) + FILE_GRANT_TTL_SECONDS + 30
        reservation = publication._reservation
        real_private_descriptor = reservation.api.private_security_descriptor
        real_flush = reservation.api.flush
        private_descriptors: list[object] = []
        flushed_handles: list[int] = []

        @contextmanager
        def tracked_private_descriptor():
            with real_private_descriptor() as descriptor:
                private_descriptors.append(descriptor)
                yield descriptor

        def tracked_flush(handle):
            flushed_handles.append(handle)
            real_flush(handle)

        monkeypatch.setattr(
            reservation.api,
            "private_security_descriptor",
            tracked_private_descriptor,
        )
        monkeypatch.setattr(reservation.api, "flush", tracked_flush)
        publication.assert_destination_available()
        publication.reserve_staging(".hdf5")
        with pytest.raises(OSError):
            parent.rename(moved_parent)
        with publication.open_writer("w+b", encoding=None) as stream:
            assert stream.seekable() and stream.readable() and stream.writable()
            stream.write(b"verified HDF5-compatible bytes")
            stream.seek(0)
            assert stream.read() == b"verified HDF5-compatible bytes"
            with pytest.raises(RuntimeError, match="writer is already active"):
                with publication.open_writer("w+b", encoding=None):
                    pass
        monkeypatch.setattr(utility_helpers.time, "time", lambda: future_time)
        with publication.open_reader("rb", encoding=None) as stream:
            assert stream.read() == b"verified HDF5-compatible bytes"
            with pytest.raises(RuntimeError, match="reader is already active"):
                with publication.open_reader("rb", encoding=None):
                    pass
        assert publication.verified_size() == len(b"verified HDF5-compatible bytes")
        assert publication.publish() == []

    assert len(private_descriptors) == 1
    assert len(flushed_handles) == 1
    assert destination.read_bytes() == b"verified HDF5-compatible bytes"
    assert list(parent.glob(".stingray-export-*")) == []
    parent.rename(moved_parent)
    moved_parent.rename(parent)


@requires_windows
def test_windows_publication_rejects_grant_expired_before_admission(
    tmp_path, monkeypatch
):
    destination = tmp_path / "expired.bin"
    admission_time = int(time.time())
    monkeypatch.setattr(
        utility_helpers.time,
        "time",
        lambda: admission_time - FILE_GRANT_TTL_SECONDS - 1,
    )
    expired_grant = _write_grant(destination)
    monkeypatch.setattr(utility_helpers.time, "time", lambda: admission_time)

    with pytest.raises(PermissionError, match="expired"):
        with open_secure_publication(str(destination), expired_grant):
            pytest.fail("An expired Windows grant must not be admitted")


@requires_windows
def test_windows_publication_roundtrips_real_hdf5_file_object_driver(tmp_path):
    import h5py

    destination = tmp_path / "real-science.hdf5"
    expected = [1.25, 2.5, 5.0]

    with open_secure_publication(
        str(destination),
        _write_grant(destination),
    ) as publication:
        publication.reserve_staging(".hdf5")
        with publication.open_writer("w+b", encoding=None) as stream:
            with h5py.File(stream, "w") as handle:
                handle.create_dataset("events/time", data=expected)
                handle.attrs["schema"] = "stingray-explorer.hdf5.v1"
        with publication.open_reader("rb", encoding=None) as stream:
            with h5py.File(stream, "r") as handle:
                assert handle["events/time"][:].tolist() == expected
                assert handle.attrs["schema"] == "stingray-explorer.hdf5.v1"
        publication.verified_size()
        publication.publish()

    with h5py.File(destination, "r") as handle:
        assert handle["events/time"][:].tolist() == expected


@requires_windows
def test_windows_publication_enforces_verified_lifecycle_and_nonempty_output(
    tmp_path,
):
    empty_destination = tmp_path / "empty.bin"
    with open_secure_publication(
        str(empty_destination),
        _write_grant(empty_destination),
    ) as publication:
        with pytest.raises(RuntimeError, match="has not completed verification"):
            publication.publish()
        publication.reserve_staging(".bin")
        with pytest.raises(RuntimeError, match="has not completed"):
            with publication.open_reader("rb", encoding=None):
                pass
        with publication.open_writer("wb", encoding=None):
            pass
        with publication.open_reader("rb", encoding=None) as stream:
            assert stream.read() == b""
        with pytest.raises(ValueError, match="empty"):
            publication.verified_size()

    assert not empty_destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []

    destination = tmp_path / "verified.bin"
    with open_secure_publication(
        str(destination),
        _write_grant(destination),
    ) as publication:
        publication.reserve_staging(".bin")
        with publication.open_writer("wb", encoding=None) as stream:
            stream.write(b"verified")
        with publication.open_reader("rb", encoding=None) as stream:
            assert stream.read() == b"verified"
        publication.verified_size()
        publication.publish()
        with pytest.raises(RuntimeError, match="already published"):
            publication.publish()


@requires_windows
def test_windows_publication_refuses_late_target_race_without_replacement(tmp_path):
    destination = tmp_path / "artifact.bin"
    sentinel = b"user-owned target"

    with pytest.raises(FileExistsError, match="already exists"):
        with open_secure_publication(
            str(destination),
            _write_grant(destination),
        ) as publication:
            publication.assert_destination_available()
            publication.reserve_staging(".bin")
            with publication.open_writer("wb", encoding=None) as stream:
                stream.write(b"new bytes")
            with publication.open_reader("rb", encoding=None) as stream:
                assert stream.read() == b"new bytes"
            publication.verified_size()
            destination.write_bytes(sentinel)
            publication.publish()

    assert destination.read_bytes() == sentinel
    assert list(tmp_path.glob(".stingray-export-*")) == []


@requires_windows
def test_windows_publication_cleans_owned_handles_after_writer_failure(tmp_path):
    parent = tmp_path / "selected-parent"
    parent.mkdir()
    destination = parent / "artifact.bin"

    with pytest.raises(OSError, match="synthetic writer failure"):
        with open_secure_publication(
            str(destination),
            _write_grant(destination),
        ) as publication:
            publication.reserve_staging(".bin")
            with publication.open_writer("wb", encoding=None) as stream:
                stream.write(b"partial")
                raise OSError("synthetic writer failure")

    assert not destination.exists()
    assert list(parent.glob(".stingray-export-*")) == []
    moved_parent = tmp_path / "moved-parent"
    parent.rename(moved_parent)


@requires_windows
@pytest.mark.parametrize("invalid_phase", ["writer", "reader"])
def test_windows_invalid_stream_mode_closes_every_owned_handle(tmp_path, invalid_phase):
    parent = tmp_path / f"{invalid_phase}-parent"
    parent.mkdir()
    destination = parent / "artifact.bin"

    with pytest.raises(ValueError, match="Unsupported secure publication stream"):
        with open_secure_publication(
            str(destination),
            _write_grant(destination),
        ) as publication:
            publication.reserve_staging(".bin")
            if invalid_phase == "reader":
                with publication.open_writer("wb", encoding=None) as stream:
                    stream.write(b"private bytes")
                with publication.open_reader("invalid", encoding=None):
                    pass
            else:
                with publication.open_writer("invalid", encoding=None):
                    pass

    assert not destination.exists()
    assert list(parent.glob(".stingray-export-*")) == []
    parent.rename(tmp_path / f"moved-{invalid_phase}-parent")


@requires_windows
def test_windows_publication_checks_final_reopen_identity(tmp_path, monkeypatch):
    destination = tmp_path / "artifact.bin"

    with pytest.raises(PermissionError, match="changed during publication"):
        with open_secure_publication(
            str(destination),
            _write_grant(destination),
        ) as publication:
            publication.reserve_staging(".bin")
            with publication.open_writer("wb", encoding=None) as stream:
                stream.write(b"published bytes")
            with publication.open_reader("rb", encoding=None) as stream:
                assert stream.read() == b"published bytes"
            publication.verified_size()

            reservation = publication._reservation
            real_identity = reservation.api.identity

            def mismatched_final_identity(handle):
                identity = real_identity(handle)
                if handle != reservation.artifact_handle:
                    return WindowsFileIdentity(
                        volume_serial=identity.volume_serial,
                        file_id=b"\xff" * 16,
                    )
                return identity

            monkeypatch.setattr(reservation.api, "identity", mismatched_final_identity)
            publication.publish()

    # Rename already occurred before the final reopen check. Failures never
    # trigger a destructive retry against the published destination.
    assert destination.read_bytes() == b"published bytes"
    assert list(tmp_path.glob(".stingray-export-*")) == []


@requires_windows
def test_windows_grants_reject_junction_prefixes(tmp_path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    junction = tmp_path / "junction-parent"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(real_parent)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with pytest.raises(FileGrantEligibilityError, match="reparse points"):
        issue_file_grant(str(junction / "artifact.bin"), access="write")
