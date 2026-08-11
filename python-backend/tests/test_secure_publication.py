"""Contract tests for format-independent secure publication."""

from __future__ import annotations

import os

import pytest

import services.secure_publication as publication_module
from services.secure_publication import open_secure_publication
from services.utility_helpers import (
    FILE_GRANT_SECRET_ENV,
    SECURE_DIR_FD_OPERATIONS_SUPPORTED,
    issue_file_grant,
)

TEST_SECRET = "secure-publication-test-secret-at-least-32-bytes"

requires_posix_publication = pytest.mark.skipif(
    os.name != "posix" or not SECURE_DIR_FD_OPERATIONS_SUPPORTED,
    reason="POSIX descriptor-relative publication primitives are required",
)


@pytest.fixture(autouse=True)
def file_grant_secret(monkeypatch):
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, TEST_SECRET)


def _write_grant(path) -> str:
    return issue_file_grant(str(path), access="write").grant


@requires_posix_publication
def test_posix_publication_contract_writes_reopens_and_publishes(tmp_path, monkeypatch):
    destination = tmp_path / "artifact.bin"
    real_fsync = os.fsync
    flushed_descriptors: list[int] = []

    def tracked_fsync(descriptor: int) -> None:
        flushed_descriptors.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(publication_module.os, "fsync", tracked_fsync)

    with open_secure_publication(
        str(destination),
        _write_grant(destination),
    ) as publication:
        assert publication.path == destination.resolve()
        assert publication.filename == destination.name
        publication.revalidate("destination changed")
        publication.assert_destination_available()
        publication.reserve_staging(".bin")
        with publication.open_writer("wb", encoding=None) as stream:
            stream.write(b"scientifically verified bytes")
        assert len(flushed_descriptors) == 1
        with publication.open_reader("rb", encoding=None) as stream:
            assert stream.read() == b"scientifically verified bytes"
        assert publication.verified_size() == len(b"scientifically verified bytes")
        assert publication.publish() == []

    assert destination.read_bytes() == b"scientifically verified bytes"
    assert list(tmp_path.glob(".stingray-export-*")) == []


@requires_posix_publication
def test_posix_publication_refuses_a_late_existing_target(tmp_path):
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


@requires_posix_publication
def test_posix_publication_cleans_owned_staging_after_writer_failure(tmp_path):
    destination = tmp_path / "artifact.bin"

    with pytest.raises(OSError, match="synthetic writer failure"):
        with open_secure_publication(
            str(destination),
            _write_grant(destination),
        ) as publication:
            publication.assert_destination_available()
            publication.reserve_staging(".bin")
            with publication.open_writer("wb", encoding=None) as stream:
                stream.write(b"partial private bytes")
                raise OSError("synthetic writer failure")

    assert not destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []


@requires_posix_publication
def test_posix_publication_enforces_verified_lifecycle(tmp_path):
    destination = tmp_path / "artifact.bin"

    with open_secure_publication(
        str(destination),
        _write_grant(destination),
    ) as publication:
        with pytest.raises(RuntimeError, match="has not completed verification"):
            publication.publish()

        publication.reserve_staging(".bin")
        with pytest.raises(RuntimeError, match="has not completed"):
            with publication.open_reader("rb", encoding=None):
                pass
        with pytest.raises(RuntimeError, match="has not completed verification"):
            publication.publish()

        with publication.open_writer("wb", encoding=None) as stream:
            stream.write(b"verified bytes")
        with publication.open_reader("rb", encoding=None) as stream:
            assert stream.read() == b"verified bytes"
        with pytest.raises(RuntimeError, match="reader already completed"):
            with publication.open_reader("rb", encoding=None):
                pass
        publication.verified_size()
        publication.publish()
        with pytest.raises(RuntimeError, match="already published"):
            publication.publish()

    assert destination.read_bytes() == b"verified bytes"


@requires_posix_publication
def test_posix_writer_stream_construction_closes_descriptor_once(tmp_path, monkeypatch):
    destination = tmp_path / "artifact.bin"

    with open_secure_publication(
        str(destination),
        _write_grant(destination),
    ) as publication:
        publication.reserve_staging(".bin")
        writer_descriptor = publication._writer_descriptor
        real_close = publication_module.os.close
        closed: list[int] = []

        def tracked_close(descriptor: int) -> None:
            closed.append(descriptor)
            real_close(descriptor)

        def fail_file_io(*_args, **_kwargs):
            raise OSError("synthetic stream construction failure")

        monkeypatch.setattr(publication_module.os, "close", tracked_close)
        monkeypatch.setattr(publication_module.io, "FileIO", fail_file_io)

        with pytest.raises(OSError, match="synthetic stream construction failure"):
            with publication.open_writer("wb", encoding=None):
                pass

        assert closed.count(writer_descriptor) == 1

    assert not destination.exists()


def test_secure_publication_fails_closed_without_a_platform_adapter(
    tmp_path, monkeypatch
):
    destination = tmp_path / "artifact.bin"
    monkeypatch.setattr(publication_module, "_platform_name", lambda: "nt")

    with pytest.raises(NotImplementedError, match="not supported"):
        with open_secure_publication(str(destination), "unused"):
            pytest.fail("An unsupported platform must not yield a publication")
