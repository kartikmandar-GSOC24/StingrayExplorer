"""Shared Utility safety helpers and state semantics."""

import hashlib
import hmac
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from services.state_manager import StateManager
from services.utility_helpers import (
    FILE_GRANT_MAX_FUTURE_SECONDS,
    FILE_GRANT_SECRET_ENV,
    FILE_GRANT_TTL_SECONDS,
    FILE_GRANT_VERSION,
    issue_file_grant,
    json_safe,
    open_verified_read_grant,
    open_verified_write_grant,
    validate_derived_name,
    validate_finite_array,
    verify_file_grant,
)
from stingray import EventList

from services import utility_helpers


def _grant(secret: str, path, access: str, expires: int | None = None) -> str:
    expires = int(time.time()) + 60 if expires is None else expires
    resolved = path.resolve()
    identity_path = resolved if access == "read" else resolved.parent
    selected_stat = identity_path.stat()
    prefix = (
        f"{FILE_GRANT_VERSION}.{expires}.{selected_stat.st_dev}.{selected_stat.st_ino}"
    )
    payload = (
        f"{FILE_GRANT_VERSION}\0{access}\0{expires}\0{resolved}\0"
        f"{selected_stat.st_dev}\0{selected_stat.st_ino}"
    ).encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"{prefix}.{digest}"


def test_file_grant_is_bound_to_exact_path_and_access(tmp_path, monkeypatch):
    secret = "test-only-file-grant-secret-32-bytes"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")
    adjacent = tmp_path / "adjacent.fits"
    adjacent.write_bytes(b"other")
    token = _grant(secret, selected, "read")

    assert (
        verify_file_grant(str(selected), token, access="read", must_exist=True)
        == selected.resolve()
    )
    with pytest.raises(PermissionError, match="does not match"):
        verify_file_grant(str(adjacent), token, access="read", must_exist=True)
    with pytest.raises(PermissionError, match="does not match"):
        verify_file_grant(str(selected), token, access="write", must_exist=False)


def test_file_grant_rejects_expired_or_missing_secret(tmp_path, monkeypatch):
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")
    secret = "test-only-file-grant-secret-32-bytes"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    expired = _grant(secret, selected, "read", int(time.time()) - 1)
    with pytest.raises(PermissionError, match="expired"):
        verify_file_grant(str(selected), expired, access="read", must_exist=True)
    monkeypatch.delenv(FILE_GRANT_SECRET_ENV)
    with pytest.raises(PermissionError, match="not launched by Electron"):
        verify_file_grant(str(selected), expired, access="read", must_exist=True)


def test_python_issuer_creates_canonical_v2_grants_with_fixed_ttl(
    tmp_path, monkeypatch
):
    secret = "test-only-file-grant-secret-32-bytes"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    monkeypatch.setattr(utility_helpers.time, "time", lambda: 1_900_000_000)
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")

    issued = issue_file_grant(str(selected), access="read")

    assert issued.path == selected.resolve()
    assert issued.expires_at == 1_900_000_000 + FILE_GRANT_TTL_SECONDS
    assert issued.grant.startswith(f"{FILE_GRANT_VERSION}.{issued.expires_at}.")
    assert (
        verify_file_grant(
            str(issued.path), issued.grant, access="read", must_exist=True
        )
        == issued.path
    )


def test_file_grant_rejects_malformed_future_and_weak_secret(tmp_path, monkeypatch):
    secret = "test-only-file-grant-secret-32-bytes"
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)

    malformed_grants = (
        "v1.1.2.3." + "0" * 64,
        "v2." + "9" * 10_000 + ".2.3." + "0" * 64,
        "v2." + "9" * 21 + ".2.3." + "0" * 64,
        "v2.123.\u0661.3." + "0" * 64,
    )
    for malformed in malformed_grants:
        with pytest.raises(PermissionError, match="malformed"):
            verify_file_grant(str(selected), malformed, access="read", must_exist=True)

    future = _grant(
        secret,
        selected,
        "read",
        int(time.time()) + FILE_GRANT_MAX_FUTURE_SECONDS + 1,
    )
    with pytest.raises(PermissionError, match="expiry is invalid"):
        verify_file_grant(str(selected), future, access="read", must_exist=True)

    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, "too-short")
    with pytest.raises(PermissionError, match="strong per-launch secret"):
        verify_file_grant(str(selected), future, access="read", must_exist=True)


def test_read_grant_pins_identity_and_open_descriptor(tmp_path, monkeypatch):
    secret = "test-only-file-grant-secret-32-bytes"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"original")
    token = _grant(secret, selected, "read")

    replacement = tmp_path / "replacement.fits"
    replacement.write_bytes(b"replacement")
    os.replace(replacement, selected)
    with pytest.raises(PermissionError, match="identity changed"):
        verify_file_grant(str(selected), token, access="read", must_exist=True)

    selected.write_bytes(b"second original")
    token = _grant(secret, selected, "read")
    replacement.write_bytes(b"second replacement")
    with open_verified_read_grant(str(selected), token) as granted:
        os.replace(replacement, selected)
        assert granted.stream.read() == b"second original"
        assert granted.size_bytes == len(b"second original")


def test_read_grant_rejects_swap_between_path_check_and_descriptor_open(
    tmp_path, monkeypatch
):
    secret = "test-only-file-grant-secret-32-bytes"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"original")
    token = _grant(secret, selected, "read")
    replacement = tmp_path / "replacement.fits"
    replacement.write_bytes(b"replacement")
    real_open = os.open
    swapped = False

    def swap_before_open(file_path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(file_path) == selected.resolve():
            swapped = True
            os.replace(replacement, selected)
        return real_open(file_path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_open)
    with (
        pytest.raises(PermissionError, match="identity changed"),
        open_verified_read_grant(str(selected), token),
    ):
        pass


def test_write_grant_is_bound_to_selected_parent_directory(tmp_path, monkeypatch):
    secret = "test-only-file-grant-secret-32-bytes"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected_parent = tmp_path / "selected-parent"
    selected_parent.mkdir()
    destination = selected_parent / "export.json"
    token = _grant(secret, destination, "write")

    original_parent = tmp_path / "original-parent"
    selected_parent.rename(original_parent)
    selected_parent.mkdir()

    with pytest.raises(PermissionError, match="directory identity changed"):
        verify_file_grant(str(destination), token, access="write", must_exist=False)


def test_write_grant_rejects_swap_between_path_check_and_parent_open(
    tmp_path, monkeypatch
):
    secret = "test-only-file-grant-secret-32-bytes"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected_parent = tmp_path / "selected-parent"
    selected_parent.mkdir()
    selected_parent_path = selected_parent.resolve()
    destination = selected_parent / "export.json"
    token = _grant(secret, destination, "write")
    moved_parent = tmp_path / "moved-parent"
    real_open = os.open
    real_fstat = os.fstat
    opened_descriptor: int | None = None

    def swap_before_open(file_path, flags, *args, **kwargs):
        nonlocal opened_descriptor
        if Path(file_path) == selected_parent_path:
            selected_parent.rename(moved_parent)
            selected_parent.mkdir()
        opened_descriptor = real_open(file_path, flags, *args, **kwargs)
        return opened_descriptor

    monkeypatch.setattr(os, "open", swap_before_open)
    with (
        pytest.raises(PermissionError, match="directory identity changed"),
        open_verified_write_grant(str(destination), token),
    ):
        pass

    assert opened_descriptor is not None
    with pytest.raises(OSError):
        real_fstat(opened_descriptor)


def test_state_snapshot_is_detached_and_add_if_absent_is_atomic():
    state = StateManager()
    source = EventList(
        time=np.array([1.0, 2.0, 3.0]),
        energy=np.array([2.0, 3.0, 4.0]),
        gti=[[0.5, 3.5]],
    )
    state.add_event_data("source", source)
    snapshot = state.copy_event_data("source")
    snapshot.time[0] = 99.0
    snapshot.gti[0, 0] = -1.0
    assert source.time[0] == 1.0
    assert source.gti[0, 0] == 0.5
    assert not np.shares_memory(source.time, snapshot.time)

    def add(index: int) -> bool:
        return state.add_event_data_if_absent(
            "derived", EventList(time=[float(index), float(index + 1)])
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(add, range(32)))
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 31


def test_state_row_cap_rejects_sized_sequence_before_iteration():
    class GuardedList(list):
        def __iter__(self):
            raise AssertionError("oversized state must not be iterated")

    state = StateManager()
    state.add_analysis_result("oversized", {"value": GuardedList([1, 2, 3])})

    with pytest.raises(ValueError, match="has 3 rows; the operation cap is 2"):
        state.copy_analysis_result(
            "oversized", max_rows=2, max_cells=100, max_bytes=10_000
        )


def test_state_byte_cap_rejects_string_without_full_utf8_encoding():
    class GuardedString(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("oversized state must not be encoded in full")

    state = StateManager()
    state.add_analysis_result(
        "oversized metadata", {"metadata": {"header": GuardedString("x" * 1_000)}}
    )

    with pytest.raises(ValueError, match="operation size cap"):
        state.copy_analysis_result(
            "oversized metadata", max_rows=10, max_cells=100, max_bytes=64
        )


def test_common_validation_and_json_sanitizing():
    assert validate_derived_name("derived-events") is None
    assert validate_derived_name(" ../unsafe") is not None
    array, error = validate_finite_array([1, 2, 3], label="values")
    assert error is None and np.array_equal(array, [1, 2, 3])
    assert "values[1]" in validate_finite_array([1, np.nan], label="values")[1]
    assert "booleans" in validate_finite_array([1, True], label="values")[1]
    assert "complex" in validate_finite_array([1, 2 + 1j], label="values")[1]
    assert "text values" in validate_finite_array([1, "2"], label="values")[1]
    assert "text" in validate_finite_array("12", label="values")[1]
    assert "mapping" in validate_finite_array({1: 2}, label="values")[1]
    assert "booleans" in validate_finite_array(True, label="values")[1]

    warnings: list[str] = []
    payload = json_safe(
        {
            "finite": np.float64(1.0),
            "scalar_array": np.asarray(2.0),
            "bad": [np.inf, np.nan],
            "complex": 1 + 2j,
            "bad_decimal": Decimal("Infinity"),
        },
        warnings,
    )
    assert payload == {
        "finite": 1.0,
        "scalar_array": 2.0,
        "bad": [None, None],
        "complex": None,
        "bad_decimal": None,
    }
    assert warnings
    json.dumps(payload, allow_nan=False)


def test_finite_array_caps_generators_before_unbounded_materialization():
    consumed: list[int] = []

    def oversized_values():
        for value in range(100):
            consumed.append(value)
            yield value

    array, error = validate_finite_array(oversized_values(), label="values", max_size=2)

    assert array is None
    assert error == "values contains at least 3 values; the cap is 2"
    assert consumed == [0, 1, 2]

    valid, valid_error = validate_finite_array(
        (value for value in [1.0, 2.0]), label="values", max_size=2
    )
    assert valid_error is None
    np.testing.assert_array_equal(valid, [1.0, 2.0])


def test_finite_array_uses_sized_preflight_before_iteration():
    class OversizedValues:
        def __len__(self):
            return 4

        def __iter__(self):
            raise AssertionError("oversized sized input must not be iterated")

    array, error = validate_finite_array(OversizedValues(), label="values", max_size=3)

    assert array is None
    assert error == "values contains 4 values; the cap is 3"


def test_json_sanitizing_aggregates_large_nonfinite_array_warnings():
    warnings: list[str] = []
    payload = json_safe(np.full(10_000, np.nan), warnings, "large_array")

    assert payload == [None] * 10_000
    assert warnings == [
        (
            "large_array contains 10,000 non-finite values represented as null; "
            "first at large_array[0]"
        )
    ]
    json.dumps(payload, allow_nan=False)
