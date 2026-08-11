"""General I/O Utilities service and route tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import os
import time
import warnings
from pathlib import Path

import httpx
import numpy as np
import pytest
from astropy import units as u
from astropy.io import fits
from astropy.table import MaskedColumn, Table
from astropy.utils.exceptions import AstropyUserWarning
from fastapi import FastAPI
from pydantic import ValidationError
from routes import io_utility_routes
from routes.io_utility_routes import (
    ConvertEventListRequest,
    ConvertPiRequest,
    ExportObjectRequest,
    GrantedInputRequest,
)
from services.io_utility_service import IOUtilityService
from services.state_manager import StateManager
from services.utility_helpers import FILE_GRANT_VERSION
from stingray import EventList, Lightcurve
from stingray.io import pi_to_energy

from services.timing_service import TimingService

TEST_SECRET = "io-utility-test-file-grant-secret"


@pytest.fixture(autouse=True)
def file_grant_secret(monkeypatch):
    monkeypatch.setenv("STINGRAY_FILE_GRANT_SECRET", TEST_SECRET)


def make_grant(
    path: Path,
    access: str,
    *,
    expires_delta: int = 300,
    signed_path: Path | None = None,
) -> str:
    """Issue the same exact-path HMAC token as Electron main."""
    target = signed_path or path
    if target.exists():
        resolved = target.resolve(strict=True)
    else:
        resolved = target.parent.resolve(strict=True) / target.name
    expires = int(time.time()) + expires_delta
    identity_path = resolved if access == "read" else resolved.parent
    selected_stat = identity_path.stat()
    prefix = (
        f"{FILE_GRANT_VERSION}.{expires}.{selected_stat.st_dev}.{selected_stat.st_ino}"
    )
    digest = hmac.new(
        TEST_SECRET.encode(),
        (
            f"{FILE_GRANT_VERSION}\0{access}\0{expires}\0{resolved}\0"
            f"{selected_stat.st_dev}\0{selected_stat.st_ino}"
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{prefix}.{digest}"


def write_rmf(
    path: Path,
    *,
    channels: tuple[int, ...] = (0, 1, 2),
    e_min: tuple[float, ...] = (0.1, 0.2, 0.4),
    e_max: tuple[float, ...] = (0.2, 0.4, 0.8),
    units: tuple[str | None, str | None] = ("keV", "keV"),
    include_ebounds: bool = True,
    energy_format: str = "E",
    channel_format: str = "J",
    channel_bzero: int | None = None,
) -> None:
    primary = fits.PrimaryHDU()
    primary.header["MJDREFI"] = 59_000
    primary.header["MJDREFF"] = 0.123456789012345
    hdus: list[fits.hdu.base.ExtensionHDU | fits.PrimaryHDU] = [primary]
    if include_ebounds:
        channel_array = np.asarray(
            channels, dtype=np.uint64 if channel_bzero is not None else None
        )
        columns = [
            fits.Column(
                name="CHANNEL",
                format=channel_format,
                bzero=channel_bzero,
                array=channel_array,
            ),
            fits.Column(
                name="E_MIN",
                format=energy_format,
                unit=units[0],
                array=np.asarray(e_min),
            ),
            fits.Column(
                name="E_MAX",
                format=energy_format,
                unit=units[1],
                array=np.asarray(e_max),
            ),
        ]
        hdus.append(fits.BinTableHDU.from_columns(columns, name="EBOUNDS"))
    fits.HDUList(hdus).writeto(path, checksum=True)


def write_event_fits(path: Path) -> None:
    primary = fits.PrimaryHDU()
    events = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="TIME", format="D", unit="s", array=[1.0, 2.0]),
            fits.Column(name="PI", format="J", array=[0, 1]),
        ],
        name="EVENTS",
    )
    events.header["MJDREFI"] = 58_000
    events.header["MJDREFF"] = "0.123456789012345678"
    events.header["TIMESYS"] = "TT"
    events.header["TIMEUNIT"] = "s"
    events.header["TSTART"] = 1.0
    events.header["TSTOP"] = 2.0
    fits.HDUList([primary, events]).writeto(path, checksum=True)


@pytest.fixture()
def rmf_path(tmp_path: Path) -> Path:
    path = tmp_path / "calibration.rmf"
    write_rmf(path)
    return path


@pytest.fixture()
def io_state() -> StateManager:
    state = StateManager()
    event_list = EventList(
        time=np.array([1.0, 2.0, 3.0]),
        pi=np.array([0, 1, 2]),
        energy=np.array([9.0, 9.0, 9.0]),
        gti=np.array([[0.5, 3.5]]),
        mjdref=58_000.125,
    )
    state.add_event_data("events", event_list)
    state.add_lightcurve_data(
        "curve",
        Lightcurve(
            time=np.array([1.0, 2.0, 3.0]),
            counts=np.array([5.0, 7.0, 6.0]),
            dt=1.0,
            mjdref=58_000.125,
        ),
    )
    state.add_analysis_result(
        "result",
        {"frequency": [1.0, 2.0], "power": [3.0, 4.0], "norm": "leahy"},
    )
    return state


@pytest.fixture()
def service(io_state: StateManager) -> IOUtilityService:
    return IOUtilityService(io_state)


def test_inspect_fits_reports_lazy_hdu_structure_and_exact_mjdref(
    service: IOUtilityService, tmp_path: Path
):
    path = tmp_path / "events.fits"
    write_event_fits(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))

    assert result["success"], result
    data = result["data"]
    assert data["supported"] is True
    assert data["detected_type"] == "fits"
    assert data["size_bytes"] == path.stat().st_size
    assert len(data["hdus"]) == 2
    events = data["hdus"][1]
    assert events["type"] == "binary_table"
    assert events["row_count"] == 2
    assert [column["name"] for column in events["columns"]] == ["TIME", "PI"]
    assert "header-only inspection" in data["warnings"][0]
    timing = events["timing"]
    assert timing["status"] == "available"
    assert timing["mjdref"]["decimal"] == "58000.123456789012345678"
    assert timing["mjdref"]["source_keywords"] == {
        "MJDREFI": "58000",
        "MJDREFF": "0.123456789012345678",
    }
    assert timing["keywords"]["TIMESYS"] == "TT"
    json.dumps(result, allow_nan=False)


def test_inspect_fits_uses_original_numeric_mjd_card_digits(service, tmp_path):
    path = tmp_path / "numeric-mjd.fits"
    primary = fits.PrimaryHDU()
    primary.header["MJDREFI"] = 58_000
    primary.header.append(fits.Card.fromstring("MJDREFF = 0.123456789012345678"))
    primary.writeto(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))

    assert result["success"], result
    mjdref = result["data"]["hdus"][0]["timing"]["mjdref"]
    assert mjdref["decimal"] == "58000.123456789012345678"
    assert mjdref["source_keywords"]["MJDREFF"] == "0.123456789012345678"


def test_inspect_fits_nulls_and_warns_on_nonfinite_timing_cards(service, tmp_path):
    path = tmp_path / "nonfinite-timing.fits"
    primary = fits.PrimaryHDU()
    primary.header["MJDREF"] = "NaN"
    primary.header["TSTART"] = "Infinity"
    primary.writeto(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))

    assert result["success"], result
    timing = result["data"]["hdus"][0]["timing"]
    assert timing["status"] == "invalid"
    assert timing["mjdref"] is None
    assert timing["keywords"]["MJDREF"] is None
    assert timing["keywords"]["TSTART"] is None
    assert any("non-finite" in warning for warning in result["warnings"])
    json.dumps(result, allow_nan=False)


def test_inspect_unsupported_and_malformed_files_are_clean(service, tmp_path):
    text_path = tmp_path / "notes.txt"
    text_path.write_text("not scientific data", encoding="utf-8")
    unsupported = service.inspect_file(str(text_path), make_grant(text_path, "read"))
    assert unsupported["success"]
    assert unsupported["data"]["supported"] is False
    assert "Data Ingestion" in unsupported["data"]["warnings"][0]

    malformed_path = tmp_path / "broken.fits"
    malformed_path.write_bytes(b"SIMPLE  = definitely-not-a-valid-FITS")
    malformed = service.inspect_file(
        str(malformed_path), make_grant(malformed_path, "read")
    )
    assert malformed["success"] is False
    assert "Inspecting selected file" in malformed["message"]


def test_inspect_fits_reports_conflicting_time_references(service, tmp_path):
    path = tmp_path / "ambiguous.fits"
    primary = fits.PrimaryHDU()
    primary.header["MJDREF"] = 58_000.0
    events = fits.BinTableHDU.from_columns(
        [fits.Column(name="TIME", format="D", array=[1.0])], name="EVENTS"
    )
    events.header["MJDREF"] = 59_000.0
    fits.HDUList([primary, events]).writeto(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))
    assert result["success"], result
    assert any("ambiguous" in warning for warning in result["data"]["warnings"])


def test_inspect_fits_rejects_incomplete_split_mjdref(service, tmp_path):
    path = tmp_path / "incomplete-mjdref.fits"
    primary = fits.PrimaryHDU()
    primary.header["MJDREFI"] = 58_000
    primary.writeto(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))

    assert result["success"], result
    timing = result["data"]["hdus"][0]["timing"]
    assert timing["status"] == "invalid"
    assert timing["mjdref"] is None
    assert "invalid" in timing["note"]
    assert any("invalid or non-finite" in warning for warning in result["warnings"])


def test_inspect_fits_warns_on_conflicting_direct_and_split_mjdref(service, tmp_path):
    path = tmp_path / "conflicting-cards.fits"
    primary = fits.PrimaryHDU()
    primary.header["MJDREF"] = 58_000.0
    primary.header["MJDREFI"] = 59_000
    primary.header["MJDREFF"] = 0.125
    primary.writeto(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))

    assert result["success"], result
    timing = result["data"]["hdus"][0]["timing"]
    assert timing["status"] == "available"
    assert timing["mjdref"]["decimal"] == "58000.0"
    assert any("conflicting MJDREF" in warning for warning in result["warnings"])


def test_equivalent_mjdref_decimal_spellings_are_not_cross_hdu_ambiguous(
    service, tmp_path
):
    path = tmp_path / "equivalent-mjdrefs.fits"
    primary = fits.PrimaryHDU()
    primary.header["MJDREF"] = "58000.1000"
    events = fits.BinTableHDU.from_columns(
        [fits.Column(name="TIME", format="D", array=[1.0])], name="EVENTS"
    )
    events.header["MJDREF"] = "58000.1"
    fits.HDUList([primary, events]).writeto(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))

    assert result["success"], result
    assert not any("ambiguous" in warning for warning in result["warnings"])


def test_inspect_fits_combines_split_high_precision_timing_keywords(service, tmp_path):
    path = tmp_path / "split-timing.fits"
    primary = fits.PrimaryHDU()
    primary.header["TSTARTI"] = 12_345
    primary.header.append(fits.Card.fromstring("TSTARTF = 0.123456789012345678"))
    primary.header["TSTOPI"] = 12_346
    primary.header["TSTOPF"] = 0.25
    primary.header["TIMEZERI"] = 2
    primary.header["TIMEZERF"] = 0.5
    primary.writeto(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))

    assert result["success"], result
    timing = result["data"]["hdus"][0]["timing"]
    assert timing["keywords"]["TSTART"] == pytest.approx(12_345.123456789011)
    assert timing["keywords"]["TSTOP"] == pytest.approx(12_346.25)
    assert timing["keywords"]["TIMEZERO"] == pytest.approx(2.5)
    assert timing["high_precision_keywords"]["TSTART"]["decimal"] == (
        "12345.123456789012345678"
    )
    assert timing["high_precision_keywords"]["TSTART"]["source_keywords"] == {
        "TSTARTI": "12345",
        "TSTARTF": "0.123456789012345678",
    }
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "cards,invalid_keyword",
    [
        ({"TIMEDEL": -1.0, "TIMEPIXR": 0.5}, "TIMEDEL"),
        ({"TIMEDEL": 1.0, "TIMEPIXR": 2.0}, "TIMEPIXR"),
        ({"TSTARTI": 10}, "TSTART"),
    ],
)
def test_inspect_fits_nulls_invalid_timing_domains_and_incomplete_splits(
    service, tmp_path, cards, invalid_keyword
):
    path = tmp_path / f"invalid-{invalid_keyword.lower()}.fits"
    primary = fits.PrimaryHDU()
    for keyword, value in cards.items():
        primary.header[keyword] = value
    primary.writeto(path)

    result = service.inspect_file(str(path), make_grant(path, "read"))

    assert result["success"], result
    timing = result["data"]["hdus"][0]["timing"]
    assert timing["status"] == "invalid"
    assert timing["keywords"][invalid_keyword] is None
    assert any(invalid_keyword in warning for warning in result["warnings"])
    json.dumps(result, allow_nan=False)


def test_inspect_file_size_cap_is_checked_before_fits_open(
    service, tmp_path, monkeypatch
):
    import services.io_utility_service as module

    path = tmp_path / "large.fits"
    path.write_bytes(b"SIMPLE  = " + b"x" * 32)
    monkeypatch.setattr(module, "MAX_FITS_INSPECT_BYTES", 8)
    result = service.inspect_file(str(path), make_grant(path, "read"))
    assert result["success"] is False
    assert "supported cap" in result["message"]


@pytest.mark.parametrize("case", ["malformed", "forged", "expired", "wrong_access"])
def test_input_file_grants_are_enforced(service, rmf_path, tmp_path, case):
    if case == "malformed":
        token = "not-a-file-grant"
    elif case == "forged":
        other = tmp_path / "other.rmf"
        write_rmf(other)
        token = make_grant(rmf_path, "read", signed_path=other)
    elif case == "expired":
        token = make_grant(rmf_path, "read", expires_delta=-5)
    else:
        token = make_grant(rmf_path, "write")

    result = service.inspect_rmf(str(rmf_path), token)
    assert result["success"] is False
    assert "grant" in result["message"].lower() or "path" in result["message"].lower()


def test_rmf_path_swap_after_grant_open_cannot_redirect_public_reads(
    service, rmf_path, tmp_path, monkeypatch
):
    import services.io_utility_service as module

    replacement = tmp_path / "replacement.rmf"
    write_rmf(
        replacement,
        channels=(10, 11, 12),
        e_min=(1.0, 2.0, 3.0),
        e_max=(2.0, 3.0, 4.0),
    )
    grant = make_grant(rmf_path, "read")
    real_load = module._load_valid_rmf

    def swap_then_load(stream, *, require_energy_unit):
        os.replace(replacement, rmf_path)
        return real_load(stream, require_energy_unit=require_energy_unit)

    monkeypatch.setattr(module, "_load_valid_rmf", swap_then_load)
    result = service.inspect_rmf(str(rmf_path), grant)

    assert result["success"], result
    assert result["data"]["channel_min"] == 0
    assert result["data"]["channel_max"] == 2
    with fits.open(rmf_path) as hdul:
        np.testing.assert_array_equal(hdul["EBOUNDS"].data["CHANNEL"], [10, 11, 12])


def test_inspect_rmf_returns_validated_bounds(service, rmf_path):
    result = service.inspect_rmf(str(rmf_path), make_grant(rmf_path, "read"))
    assert result["success"], result
    data = result["data"]
    assert data["channel_count"] == 3
    assert (data["channel_min"], data["channel_max"]) == (0, 2)
    assert data["energy_unit"] == "keV"
    assert data["conversion_supported"] is True
    assert data["preview_rows"][2]["energy_midpoint"] == pytest.approx(0.6)


def test_convert_pasted_pi_matches_public_stingray_call(service, rmf_path):
    values = [2, 0, 1, 2]
    result = service.convert_pi_values(
        values, str(rmf_path), make_grant(rmf_path, "read")
    )
    assert result["success"], result
    expected = pi_to_energy(np.asarray(values), str(rmf_path))
    actual = np.asarray([row["energy"] for row in result["data"]["rows"]])
    np.testing.assert_allclose(actual, expected)
    assert result["data"]["energy_unit"] == "keV"
    assert result["data"]["provenance"]["calibrated"] is True


def test_convert_pi_rejects_missing_channel_before_upstream_zero_mapping(
    service, rmf_path
):
    result = service.convert_pi_values(
        [0, 99], str(rmf_path), make_grant(rmf_path, "read")
    )
    assert result["success"] is False
    assert "exact RMF EBOUNDS" in result["message"]
    assert "99" in result["message"]


def test_exports_preserve_known_units_except_explicitly_lossy_csv(service, tmp_path):
    ecsv_path = tmp_path / "events.ecsv"
    ecsv_result = service.export_object(
        "event_list",
        "events",
        "ecsv",
        str(ecsv_path),
        make_grant(ecsv_path, "write"),
    )
    assert ecsv_result["success"], ecsv_result
    ecsv_table = Table.read(ecsv_path, format="ascii.ecsv")
    assert str(ecsv_table["time"].unit) == "s"
    assert str(ecsv_table["energy"].unit) == "keV"
    assert ecsv_table.meta["gti_time_unit"] == "s"

    json_path = tmp_path / "events.json"
    json_result = service.export_object(
        "event_list",
        "events",
        "json",
        str(json_path),
        make_grant(json_path, "write"),
    )
    assert json_result["success"], json_result
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["column_units"]["time"] == "s"
    assert payload["column_units"]["energy"] == "keV"
    assert payload["column_units"]["pi"] is None
    assert payload["metadata"]["gti_time_unit"] == "s"

    fits_path = tmp_path / "events.fits"
    fits_result = service.export_object(
        "event_list",
        "events",
        "fits",
        str(fits_path),
        make_grant(fits_path, "write"),
    )
    assert fits_result["success"], fits_result
    with fits.open(fits_path, checksum=True) as hdul:
        assert hdul["EVENTS"].columns["time"].unit == "s"
        assert hdul["EVENTS"].columns["energy"].unit == "keV"
        assert hdul["EVENTS"].header["TIMEUNIT"] == "s"
        assert hdul["GTI"].columns["START"].unit == "s"
        assert hdul["GTI"].columns["STOP"].unit == "s"
        assert hdul["GTI"].header["TIMEUNIT"] == "s"
        assert hdul["GTI"].header["MJDREF"] == pytest.approx(58_000.125)
        assert hdul["GTI"].header["MJDREFI"] == 58_000
        assert hdul["GTI"].header["MJDREFF"] == pytest.approx(0.125)

    lightcurve_path = tmp_path / "curve.ecsv"
    lightcurve_result = service.export_object(
        "lightcurve",
        "curve",
        "ecsv",
        str(lightcurve_path),
        make_grant(lightcurve_path, "write"),
    )
    assert lightcurve_result["success"], lightcurve_result
    lightcurve_table = Table.read(lightcurve_path, format="ascii.ecsv")
    assert str(lightcurve_table["time"].unit) == "s"
    assert str(lightcurve_table["counts"].unit) == "ct"
    assert lightcurve_table.meta["gti_time_unit"] == "s"

    csv_path = tmp_path / "events.csv"
    csv_result = service.export_object(
        "event_list",
        "events",
        "csv",
        str(csv_path),
        make_grant(csv_path, "write"),
    )
    assert csv_result["success"], csv_result
    assert any("column units" in warning for warning in csv_result["warnings"])


@pytest.mark.parametrize("export_format", ["json", "ecsv", "fits"])
def test_lightcurve_background_and_exposure_arrays_are_not_dropped(
    service, io_state, tmp_path, export_format
):
    curve = Lightcurve(
        time=np.array([1.0, 2.0, 3.0]),
        counts=np.array([10.0, 12.0, 11.0]),
        dt=1.0,
        bg_counts=np.array([1.0, 1.5, 1.25]),
        bg_ratio=np.array([2.0, 2.0, 2.0]),
        frac_exp=np.array([1.0, 0.8, 0.9]),
    )
    # Installed Stingray only serializes these valid time-boundary arrays after
    # the lazy properties have been materialized.
    _ = curve.bin_lo, curve.bin_hi
    io_state.add_lightcurve_data("background curve", curve)
    path = tmp_path / f"background-curve.{export_format}"

    result = service.export_object(
        "lightcurve",
        "background curve",
        export_format,
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    if export_format == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        columns = payload["columns"]
        assert columns["bg_counts"] == pytest.approx([1.0, 1.5, 1.25])
        assert columns["bg_ratio"] == pytest.approx([2.0, 2.0, 2.0])
        assert columns["frac_exp"] == pytest.approx([1.0, 0.8, 0.9])
        assert payload["column_units"]["bg_counts"] == "ct"
        assert payload["column_units"]["bg_ratio"] == ""
        assert payload["column_units"]["frac_exp"] == ""
        assert payload["column_units"]["bin_lo"] == "s"
        assert payload["column_units"]["bin_hi"] == "s"
    elif export_format == "ecsv":
        table = Table.read(path, format="ascii.ecsv")
        np.testing.assert_allclose(table["bg_counts"], [1.0, 1.5, 1.25])
        np.testing.assert_allclose(table["bg_ratio"], [2.0, 2.0, 2.0])
        np.testing.assert_allclose(table["frac_exp"], [1.0, 0.8, 0.9])
        assert str(table["bg_counts"].unit) == "ct"
        assert str(table["bin_lo"].unit) == "s"
        assert str(table["bin_hi"].unit) == "s"
    else:
        with fits.open(path, checksum=True) as hdul:
            np.testing.assert_allclose(hdul["DATA"].data["bg_counts"], [1.0, 1.5, 1.25])
            np.testing.assert_allclose(hdul["DATA"].data["bg_ratio"], [2.0, 2.0, 2.0])
            np.testing.assert_allclose(hdul["DATA"].data["frac_exp"], [1.0, 0.8, 0.9])
            assert u.Unit(hdul["DATA"].columns["bg_counts"].unit) == u.ct
            assert hdul["DATA"].columns["bin_lo"].unit == "s"
            assert hdul["DATA"].columns["bin_hi"].unit == "s"


def test_variable_lightcurve_bin_widths_are_fits_columns_in_seconds(
    service, io_state, tmp_path
):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        curve = Lightcurve(
            time=np.array([0.5, 2.0, 4.5]),
            counts=np.array([1.0, 2.0, 3.0]),
            dt=np.array([1.0, 2.0, 3.0]),
        )
    io_state.add_lightcurve_data("variable bins", curve)
    path = tmp_path / "variable-bins.fits"

    result = service.export_object(
        "lightcurve",
        "variable bins",
        "fits",
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    with fits.open(path, checksum=True) as hdul:
        np.testing.assert_allclose(hdul["DATA"].data["dt"], [1.0, 2.0, 3.0])
        assert hdul["DATA"].columns["dt"].unit == "s"


def test_empty_gti_is_written_and_verified_as_zero_row_extension(
    service, io_state, tmp_path
):
    empty_gti_events = EventList(time=np.array([1.0, 2.0]), pi=np.array([0, 1]))
    empty_gti_events.gti = np.empty((0, 2), dtype=float)
    io_state.add_event_data("empty gti", empty_gti_events)
    path = tmp_path / "empty-gti.fits"

    result = service.export_object(
        "event_list",
        "empty gti",
        "fits",
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    with fits.open(path, checksum=True) as hdul:
        assert "GTI" in hdul
        assert len(hdul["GTI"].data) == 0
        assert hdul["GTI"].header["TIMEUNIT"] == "s"


def test_complex_analysis_columns_are_rejected_before_any_file_is_created(
    service, io_state, tmp_path
):
    io_state.add_analysis_result(
        "complex result",
        {"frequency": [1.0, 2.0], "amplitude": [1.0 + 2.0j, 3.0 + 4.0j]},
    )
    listed = service.list_exportable_objects()
    complex_entry = next(
        item for item in listed["data"]["objects"] if item["name"] == "complex result"
    )
    assert complex_entry["exportable"] is False
    assert "complex" in complex_entry["reason"]

    path = tmp_path / "complex.json"
    result = service.export_object(
        "analysis_result",
        "complex result",
        "json",
        str(path),
        make_grant(path, "write"),
    )
    assert result["success"] is False
    assert "separate real and imaginary columns" in result["message"]
    assert not path.exists()


def test_nested_analysis_result_is_not_partially_advertised_or_exported(
    service, io_state, tmp_path
):
    io_state.add_analysis_result(
        "power colors",
        {
            "time": [1.0, 2.0],
            "power_colors": {"band_a": [3.0, 4.0]},
            "freq_ranges": [[0.1, 0.2], [0.2, 0.4]],
        },
    )

    listed = service.list_exportable_objects()
    entry = next(
        item for item in listed["data"]["objects"] if item["name"] == "power colors"
    )
    assert entry["exportable"] is False
    assert "losslessly represented" in entry["reason"]
    assert entry["formats"] == []

    path = tmp_path / "power-colors.json"
    result = service.export_object(
        "analysis_result",
        "power colors",
        "json",
        str(path),
        make_grant(path, "write"),
    )
    assert result["success"] is False
    assert "losslessly represented" in result["message"]
    assert not path.exists()


@pytest.mark.parametrize(
    "values",
    [
        np.asarray(["2020-01-01"], dtype="datetime64[D]"),
        np.asarray([1], dtype="timedelta64[D]"),
    ],
)
def test_datetime_analysis_columns_are_not_advertised_as_universally_exportable(
    service, io_state, tmp_path, values
):
    name = f"unsupported-{values.dtype.kind}"
    io_state.add_analysis_result(name, Table({"value": values}))

    listed = service.list_exportable_objects()
    entry = next(item for item in listed["data"]["objects"] if item["name"] == name)
    assert entry["exportable"] is False
    assert "not losslessly supported" in entry["reason"]

    path = tmp_path / f"{name}.json"
    result = service.export_object(
        "analysis_result",
        name,
        "json",
        str(path),
        make_grant(path, "write"),
    )
    assert result["success"] is False
    assert "not losslessly supported" in result["message"]
    assert not path.exists()


@pytest.mark.parametrize(
    "values,error_text",
    [
        (
            np.asarray([(1, 2.0)], dtype=[("index", "i4"), ("value", "f8")]),
            "not losslessly supported",
        ),
        (np.asarray([b"abc"], dtype="S3"), "not losslessly supported"),
        (np.asarray(["é"], dtype="U1"), "non-ASCII Unicode"),
    ],
)
def test_structured_and_non_ascii_columns_are_not_advertised_for_all_formats(
    service, io_state, tmp_path, values, error_text
):
    name = f"unsupported-{values.dtype.kind}"
    io_state.add_analysis_result(name, Table({"value": values}))

    listed = service.list_exportable_objects()
    entry = next(item for item in listed["data"]["objects"] if item["name"] == name)
    assert entry["exportable"] is False
    assert error_text in entry["reason"]
    assert entry["formats"] == []

    path = tmp_path / f"{name}.json"
    result = service.export_object(
        "analysis_result",
        name,
        "json",
        str(path),
        make_grant(path, "write"),
    )
    assert result["success"] is False
    assert error_text in result["message"]
    assert not path.exists()


def test_masked_analysis_json_preserves_missing_values_as_null(
    service, io_state, tmp_path
):
    table = Table([MaskedColumn([1.0, 2.0], mask=[False, True])], names=["statistic"])
    io_state.add_analysis_result("masked result", table)
    path = tmp_path / "masked-result.json"

    result = service.export_object(
        "analysis_result",
        "masked result",
        "json",
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["columns"]["statistic"] == [1.0, None]
    assert any("1 masked value" in warning for warning in result["warnings"])


def test_json_export_uses_null_and_warning_for_nonfinite_analysis_values(
    service, io_state, tmp_path
):
    sample_count = 10_000
    io_state.add_analysis_result(
        "nonfinite result",
        {
            "frequency": np.arange(sample_count, dtype=float),
            "statistic": np.full(sample_count, np.nan),
        },
    )
    path = tmp_path / "nonfinite.json"

    result = service.export_object(
        "analysis_result",
        "nonfinite result",
        "json",
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["columns"]["statistic"]) == sample_count
    assert set(payload["columns"]["statistic"]) == {None}
    assert payload["column_units"]["frequency"] is None
    assert payload["column_units"]["statistic"] is None
    nonfinite_warnings = [
        warning for warning in result["warnings"] if "non-finite" in warning
    ]
    assert len(nonfinite_warnings) == 1
    assert "10,000" in nonfinite_warnings[0]
    json.dumps(result, allow_nan=False)
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("export_format", ["json", "ecsv", "fits"])
def test_nullable_numeric_analysis_columns_remain_exportable(
    service, io_state, tmp_path, export_format
):
    io_state.add_analysis_result(
        "nullable lags",
        {
            "freq": [1.0, 2.0],
            "time_lags": [None, 0.25],
            "time_lags_err": [None, None],
            "metadata": {
                "units": {
                    "freq": "Hz",
                    "time_lags": "s",
                    "time_lags_err": "s",
                }
            },
        },
    )
    listed = service.list_exportable_objects()
    entry = next(
        item for item in listed["data"]["objects"] if item["name"] == "nullable lags"
    )
    assert entry["exportable"] is True, entry
    path = tmp_path / f"nullable-lags.{export_format}"

    result = service.export_object(
        "analysis_result",
        "nullable lags",
        export_format,
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    if export_format == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["columns"]["time_lags"] == [None, 0.25]
        assert payload["columns"]["time_lags_err"] == [None, None]
        assert payload["column_units"]["time_lags"] == "s"
        json.dumps(payload, allow_nan=False)
    elif export_format == "ecsv":
        table = Table.read(path, format="ascii.ecsv")
        assert np.isnan(table["time_lags"][0])
        assert table["time_lags"][1] == pytest.approx(0.25)
        assert str(table["time_lags"].unit) == "s"
    else:
        with fits.open(path, checksum=True) as hdul:
            assert np.isnan(hdul["DATA"].data["time_lags"][0])
            assert hdul["DATA"].data["time_lags"][1] == pytest.approx(0.25)
            assert hdul["DATA"].columns["time_lags"].unit == "s"


def test_saved_band_lags_export_nullable_values_and_parameter_metadata(
    service, io_state, tmp_path
):
    times = np.arange(0.0, 64.0, 0.0625)
    io_state.add_event_data("constant a", EventList(time=times, gti=[[0.0, 64.0]]))
    io_state.add_event_data("constant b", EventList(time=times, gti=[[0.0, 64.0]]))
    timing_result = TimingService(io_state).calculate_time_lags(
        "constant a",
        "constant b",
        dt=0.0625,
        segment_size=8.0,
        freq_range=(0.5, 2.0),
        output_name="band lags",
    )
    assert timing_result["success"], timing_result
    assert timing_result["data"]["metadata"]["non_column_fields"] == ["freq_range"]
    assert any(value is None for value in timing_result["data"]["time_lags_err"])

    listed = service.list_exportable_objects()
    entry = next(
        item for item in listed["data"]["objects"] if item["name"] == "band lags"
    )
    assert entry["exportable"] is True, entry
    path = tmp_path / "band-lags.json"
    exported = service.export_object(
        "analysis_result",
        "band lags",
        "json",
        str(path),
        make_grant(path, "write"),
    )

    assert exported["success"], exported
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "freq_range" not in payload["columns"]
    assert payload["metadata"]["freq_range"] == [0.5, 2.0]
    assert payload["metadata"]["provenance"]["operation"] == "timing_time_lags"
    assert payload["column_units"]["freq"] == "Hz"
    assert payload["column_units"]["time_lags_err"] == "s"
    json.dumps(payload, allow_nan=False)


def test_saved_nullable_coherence_result_is_exportable(service, io_state, tmp_path):
    times = np.arange(0.0, 64.0, 0.0625)
    io_state.add_event_data("constant c", EventList(time=times, gti=[[0.0, 64.0]]))
    io_state.add_event_data("constant d", EventList(time=times, gti=[[0.0, 64.0]]))
    timing_result = TimingService(io_state).calculate_coherence(
        "constant c",
        "constant d",
        dt=0.0625,
        segment_size=8.0,
        output_name="nullable coherence",
    )
    assert timing_result["success"], timing_result
    assert all(value is None for value in timing_result["data"]["coherence"])

    listed = service.list_exportable_objects()
    entry = next(
        item
        for item in listed["data"]["objects"]
        if item["name"] == "nullable coherence"
    )
    assert entry["exportable"] is True, entry
    path = tmp_path / "nullable-coherence.json"
    exported = service.export_object(
        "analysis_result",
        "nullable coherence",
        "json",
        str(path),
        make_grant(path, "write"),
    )

    assert exported["success"], exported
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload["columns"]["coherence"]) == {None}
    assert set(payload["columns"]["coherence_err"]) == {None}
    assert payload["column_units"]["freq"] == "Hz"
    assert payload["metadata"]["provenance"]["operation"] == "timing_coherence"
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("export_format", ["json", "ecsv", "fits"])
def test_explicitly_missing_event_gti_is_not_synthesized_during_export(
    service, io_state, tmp_path, export_format
):
    no_gti = EventList(time=np.array([1.0, 2.0, 3.0]), pi=np.array([0, 1, 2]))
    assert no_gti._gti is None
    io_state.add_event_data("no explicit gti", no_gti)
    path = tmp_path / f"no-gti.{export_format}"

    result = service.export_object(
        "event_list",
        "no explicit gti",
        export_format,
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    assert any("no explicit GTI" in warning for warning in result["warnings"])
    assert io_state.get_event_data("no explicit gti")._gti is None
    if export_format == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "gti" not in payload["metadata"]
        assert payload["metadata"]["gti_status"] == "missing"
    elif export_format == "ecsv":
        table = Table.read(path, format="ascii.ecsv")
        assert "gti" not in table.meta
        assert table.meta["gti_status"] == "missing"
    else:
        with fits.open(path, checksum=True) as hdul:
            assert "GTI" not in hdul


@pytest.mark.parametrize(
    "values,error_text",
    [
        ([0.5], "integer channel"),
        ([-1], "non-negative"),
        ([float("nan")], "finite"),
        ([float("inf")], "finite"),
        ([], "at least 1"),
    ],
)
def test_convert_pi_rejects_invalid_arrays(service, rmf_path, values, error_text):
    result = service.convert_pi_values(
        values, str(rmf_path), make_grant(rmf_path, "read")
    )
    assert result["success"] is False
    assert error_text in result["message"]


def test_convert_pi_enforces_output_cap(service, rmf_path, monkeypatch):
    import services.io_utility_service as module

    monkeypatch.setattr(module, "MAX_ARRAY_INPUT", 2)
    result = service.convert_pi_values(
        [0, 1, 2], str(rmf_path), make_grant(rmf_path, "read")
    )
    assert result["success"] is False
    assert "cap is 2" in result["message"]


def test_convert_pi_bounds_generator_consumption_at_cap_plus_one(
    service, rmf_path, monkeypatch
):
    import services.io_utility_service as module

    consumed: list[int] = []

    def values():
        for value in range(10):
            consumed.append(value)
            yield value

    monkeypatch.setattr(module, "MAX_ARRAY_INPUT", 2)
    result = service.convert_pi_values(
        values(), str(rmf_path), make_grant(rmf_path, "read")
    )

    assert result["success"] is False
    assert "at least 3 values; the cap is 2" in result["message"]
    assert consumed == [0, 1, 2]


@pytest.mark.parametrize(
    "builder,error_text",
    [
        (lambda path: write_rmf(path, include_ebounds=False), "exactly one EBOUNDS"),
        (
            lambda path: write_rmf(path, channels=(0, 0, 2)),
            "duplicate value 0",
        ),
        (
            lambda path: write_rmf(path, e_min=(0.3, 0.2, 0.4)),
            "E_MIN < E_MAX",
        ),
    ],
)
def test_malformed_rmf_is_rejected(service, tmp_path, builder, error_text):
    path = tmp_path / "bad.rmf"
    builder(path)
    result = service.inspect_rmf(str(path), make_grant(path, "read"))
    assert result["success"] is False
    assert error_text in result["message"]


def test_missing_rmf_units_are_inspectable_but_conversion_is_disabled(
    service, tmp_path
):
    path = tmp_path / "unitless.rmf"
    write_rmf(path, units=(None, None))
    token = make_grant(path, "read")
    inspected = service.inspect_rmf(str(path), token)
    assert inspected["success"]
    assert inspected["data"]["conversion_supported"] is False
    assert inspected["data"]["energy_unit"] is None
    converted = service.convert_pi_values([0], str(path), token)
    assert converted["success"] is False
    assert "units are missing" in converted["message"]


def test_energy_equivalent_rmf_units_are_normalized_to_kev(service, tmp_path):
    path = tmp_path / "electron-volts.rmf"
    write_rmf(
        path,
        e_min=(100.0, 200.0, 400.0),
        e_max=(200.0, 400.0, 800.0),
        units=("eV", "eV"),
    )
    token = make_grant(path, "read")

    inspected = service.inspect_rmf(str(path), token)
    assert inspected["success"], inspected
    assert inspected["data"]["energy_unit"] == "keV"
    assert inspected["data"]["energy_min"] == pytest.approx(0.1)
    assert inspected["data"]["preview_rows"][0]["energy_midpoint"] == pytest.approx(
        0.15
    )

    converted = service.convert_pi_values([0, 2], str(path), token)
    assert converted["success"], converted
    assert converted["data"]["energy_unit"] == "keV"
    assert [row["energy"] for row in converted["data"]["rows"]] == pytest.approx(
        [0.15, 0.6]
    )


def test_mixed_energy_equivalent_bounds_are_independently_normalized(service, tmp_path):
    path = tmp_path / "mixed-energy-units.rmf"
    write_rmf(
        path,
        e_min=(100.0, 200.0, 400.0),
        e_max=(0.2, 0.4, 0.8),
        units=("eV", "keV"),
    )
    token = make_grant(path, "read")

    result = service.convert_pi_values([0, 2], str(path), token)

    assert result["success"], result
    assert [row["energy"] for row in result["data"]["rows"]] == pytest.approx(
        [0.15, 0.6]
    )
    assert any("independently normalized" in warning for warning in result["warnings"])


def test_non_energy_rmf_units_are_rejected(service, tmp_path):
    path = tmp_path / "time-bounds.rmf"
    write_rmf(path, units=("s", "s"))

    result = service.inspect_rmf(str(path), make_grant(path, "read"))

    assert result["success"] is False
    assert "not energy-equivalent" in result["message"]


def test_non_energy_unit_is_rejected_even_if_other_bound_unit_is_missing(
    service, tmp_path
):
    path = tmp_path / "partially-unitless-time-bounds.rmf"
    write_rmf(path, units=("s", None))

    result = service.inspect_rmf(str(path), make_grant(path, "read"))

    assert result["success"] is False
    assert "not energy-equivalent" in result["message"]


@pytest.mark.parametrize(
    "e_min,e_max,label",
    [
        ((float("nan"),), (1.0,), "E_MIN"),
        ((0.0,), (float("inf"),), "E_MAX"),
    ],
)
def test_nonfinite_rmf_bounds_are_rejected(service, tmp_path, e_min, e_max, label):
    path = tmp_path / f"nonfinite-{label}.rmf"
    write_rmf(
        path,
        channels=(0,),
        e_min=e_min,
        e_max=e_max,
        energy_format="D",
    )

    result = service.inspect_rmf(str(path), make_grant(path, "read"))

    assert result["success"] is False
    assert f"RMF {label}[0] must be finite" in result["message"]


def test_negative_rmf_photon_energy_bounds_are_rejected(service, tmp_path):
    path = tmp_path / "negative-energy.rmf"
    write_rmf(
        path,
        channels=(0,),
        e_min=(-2.0,),
        e_max=(-1.0,),
        energy_format="D",
    )

    result = service.convert_pi_values([0], str(path), make_grant(path, "read"))

    assert result["success"] is False
    assert "non-negative photon energies" in result["message"]


def test_rmf_and_pi_channels_enforce_exact_json_integer_boundaries(
    service, rmf_path, tmp_path
):
    maximum_exact = 2**53 - 1
    safe_path = tmp_path / "maximum-exact-channel.rmf"
    write_rmf(
        safe_path,
        channels=(maximum_exact,),
        e_min=(1.0,),
        e_max=(2.0,),
        channel_format="K",
        energy_format="D",
    )
    safe = service.convert_pi_values(
        [maximum_exact], str(safe_path), make_grant(safe_path, "read")
    )
    assert safe["success"], safe
    assert safe["data"]["rows"][0]["pi"] == maximum_exact

    too_large_path = tmp_path / "inexact-json-channel.rmf"
    write_rmf(
        too_large_path,
        channels=(2**53,),
        e_min=(1.0,),
        e_max=(2.0,),
        channel_format="K",
        energy_format="D",
    )
    too_large_rmf = service.inspect_rmf(
        str(too_large_path), make_grant(too_large_path, "read")
    )
    assert too_large_rmf["success"] is False
    assert "exact JSON/JavaScript integer cap" in too_large_rmf["message"]

    with warnings.catch_warnings(record=True) as caught:
        too_large_pi = service.convert_pi_values(
            [2**53], str(rmf_path), make_grant(rmf_path, "read")
        )
    assert too_large_pi["success"] is False
    assert "exact JSON/JavaScript integer cap" in too_large_pi["message"]
    assert caught == []


def test_uint64_channel_cannot_alias_int64_max_without_warning(service, tmp_path):
    path = tmp_path / "uint64-channel.rmf"
    write_rmf(
        path,
        channels=(2**63,),
        e_min=(1.0,),
        e_max=(2.0,),
        channel_format="K",
        channel_bzero=2**63,
        energy_format="D",
    )

    with warnings.catch_warnings(record=True) as caught:
        inspected = service.inspect_rmf(str(path), make_grant(path, "read"))
    assert inspected["success"] is False
    assert "exact JSON/JavaScript integer cap" in inspected["message"]
    assert caught == []

    # The old float64 path rounded both values to 2**63 and could falsely
    # report an exact match before an unsafe int64 cast.
    with warnings.catch_warnings(record=True) as caught:
        converted = service.convert_pi_values(
            [2**63 - 1], str(path), make_grant(path, "read")
        )
    assert converted["success"] is False
    assert "exact JSON/JavaScript integer cap" in converted["message"]
    assert caught == []


def test_rmf_unique_pi_work_cap_precedes_public_stingray_call(
    service, rmf_path, monkeypatch
):
    import services.io_utility_service as module

    monkeypatch.setattr(module, "MAX_RMF_PI_WORK", 5)

    def forbidden_call(*args, **kwargs):
        raise AssertionError("pi_to_energy must not run after the work cap fails")

    monkeypatch.setattr(module, "pi_to_energy", forbidden_call)
    result = service.convert_pi_values(
        [0, 0, 1], str(rmf_path), make_grant(rmf_path, "read")
    )

    assert result["success"] is False
    assert "3 RMF channels x 2 unique PI values" in result["message"]
    assert "work cap is 5" in result["message"]


def test_huge_finite_rmf_bounds_have_strict_json_safe_midpoints(service, tmp_path):
    path = tmp_path / "huge-bounds.rmf"
    write_rmf(
        path,
        channels=(0,),
        e_min=(1.0e308,),
        e_max=(1.5e308,),
        units=("keV", "keV"),
        energy_format="D",
    )
    token = make_grant(path, "read")

    inspected = service.inspect_rmf(str(path), token)
    assert inspected["success"], inspected
    assert inspected["data"]["preview_rows"][0]["energy_midpoint"] == pytest.approx(
        1.25e308
    )
    json.dumps(inspected, allow_nan=False)

    converted = service.convert_pi_values([0], str(path), token)
    assert converted["success"], converted
    assert converted["data"]["rows"][0]["energy"] == pytest.approx(1.25e308)
    assert any("overflow-safe" in warning for warning in converted["warnings"])
    json.dumps(converted, allow_nan=False)


def test_rmf_with_invalid_checksum_is_rejected(service, tmp_path):
    path = tmp_path / "corrupt.rmf"
    write_rmf(path)
    with path.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        original = stream.read(1)
        stream.seek(-1, os.SEEK_END)
        stream.write(bytes([original[0] ^ 1]))

    result = service.inspect_rmf(str(path), make_grant(path, "read"))
    assert result["success"] is False
    assert "checksum or DATASUM" in result["message"]


def test_event_list_conversion_preview_and_save_are_immutable(
    service, io_state, rmf_path
):
    original = io_state.get_event_data("events")
    before = {
        "time": original.time.copy(),
        "pi": original.pi.copy(),
        "energy": original.energy.copy(),
        "gti": original.gti.copy(),
    }
    token = make_grant(rmf_path, "read")

    preview = service.convert_event_list("events", str(rmf_path), token)
    assert preview["success"], preview
    json.dumps(preview, allow_nan=False)
    assert preview["data"]["saved"] is False
    assert io_state.list_event_names() == ["events"]

    saved = service.convert_event_list(
        "events", str(rmf_path), token, save_as="events calibrated"
    )
    assert saved["success"], saved
    json.dumps(saved, allow_nan=False)
    derived = io_state.get_event_data("events calibrated")
    np.testing.assert_array_equal(derived.pi, before["pi"])
    assert derived.pi.dtype == before["pi"].dtype
    np.testing.assert_allclose(
        derived.energy, pi_to_energy(before["pi"], str(rmf_path))
    )
    assert derived.rmf_conversion_provenance["calibrated"] is True
    assert derived.rmf_conversion_provenance["parameters"]["rmf_path"] == str(
        rmf_path.resolve()
    )

    np.testing.assert_array_equal(original.time, before["time"])
    np.testing.assert_array_equal(original.pi, before["pi"])
    np.testing.assert_array_equal(original.energy, before["energy"])
    np.testing.assert_array_equal(original.gti, before["gti"])
    assert not hasattr(original, "rmf_conversion_provenance")


@pytest.mark.parametrize("export_format", ["json", "ecsv", "fits"])
def test_rmf_conversion_provenance_survives_safe_exports(
    service, io_state, rmf_path, tmp_path, export_format
):
    converted = service.convert_event_list(
        "events",
        str(rmf_path),
        make_grant(rmf_path, "read"),
        save_as="calibrated provenance",
    )
    assert converted["success"], converted
    path = tmp_path / f"calibrated-provenance.{export_format}"

    exported = service.export_object(
        "event_list",
        "calibrated provenance",
        export_format,
        str(path),
        make_grant(path, "write"),
    )

    assert exported["success"], exported
    if export_format == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        provenance = payload["metadata"]["rmf_conversion_provenance"]
    elif export_format == "ecsv":
        provenance = Table.read(path, format="ascii.ecsv").meta[
            "rmf_conversion_provenance"
        ]
    else:
        with fits.open(path, checksum=True) as hdul:
            encoded = hdul["METADATA"].data["JSON"][0]
            if isinstance(encoded, bytes):
                encoded = encoded.decode("ascii")
            provenance = json.loads(encoded)["rmf_conversion_provenance"]
    assert provenance["operation"] == "rmf_event_list_pi_to_energy"
    assert provenance["calibrated"] is True


def test_event_list_duplicate_derived_name_never_replaces_existing(
    service, io_state, rmf_path
):
    sentinel = io_state.get_event_data("events")
    result = service.convert_event_list(
        "events",
        str(rmf_path),
        make_grant(rmf_path, "read"),
        save_as="events",
    )
    assert result["success"] is False
    assert "already exists" in result["message"]
    assert io_state.get_event_data("events") is sentinel


def test_event_list_save_as_name_is_validated(service, io_state, rmf_path):
    result = service.convert_event_list(
        "events",
        str(rmf_path),
        make_grant(rmf_path, "read"),
        save_as="../not-a-name",
    )
    assert result["success"] is False
    assert "Destination name" in result["message"]
    assert io_state.list_event_names() == ["events"]


def test_event_list_without_pi_is_rejected(service, io_state, rmf_path):
    io_state.add_event_data("no-pi", EventList(time=[1.0, 2.0]))
    result = service.convert_event_list(
        "no-pi", str(rmf_path), make_grant(rmf_path, "read")
    )
    assert result["success"] is False
    assert "no PI channel" in result["message"]


def test_list_exportable_objects_has_honest_capability_matrix(service):
    result = service.list_exportable_objects()
    assert result["success"], result
    data = result["data"]
    assert data["format_allowlist"] == ["csv", "ecsv", "json", "fits"]
    assert set(data["capability_matrix"]) == {
        "event_list",
        "lightcurve",
        "analysis_result",
    }
    assert all(
        item["exportable"] and item["formats"] == data["format_allowlist"]
        for item in data["objects"]
    )
    assert "pickle" in data["excluded_formats"]
    assert "hdf5" in data["excluded_formats"]


@pytest.mark.parametrize("export_format", ["csv", "ecsv", "json", "fits"])
def test_event_list_export_is_exclusive_and_reopen_verified(
    service, tmp_path, export_format
):
    path = tmp_path / f"events.{export_format}"
    result = service.export_object(
        "event_list",
        "events",
        export_format,
        str(path),
        make_grant(path, "write"),
    )
    assert result["success"], result
    assert (
        result["data"]
        | {
            "path": str(path.resolve()),
            "format": export_format,
            "row_count": 3,
            "object_type": "event_list",
            "object_name": "events",
            "verified": True,
        }
        == result["data"]
    )
    assert result["data"]["bytes"] == path.stat().st_size > 0

    if export_format == "csv":
        assert len(Table.read(path, format="ascii.csv")) == 3
        assert result["data"]["warnings"]
    elif export_format == "ecsv":
        assert len(Table.read(path, format="ascii.ecsv")) == 3
    elif export_format == "fits":
        with fits.open(path, checksum=True) as hdul:
            assert hdul[1].name == "EVENTS"
            assert len(hdul[1].data) == 3
            np.testing.assert_allclose(hdul["GTI"].data["START"], [0.5])
            np.testing.assert_allclose(hdul["GTI"].data["STOP"], [3.5])
            assert hdul[1].header["HDUCLAS1"] == "GENERIC"
        # The installed generic Stingray reader can recover event columns only
        # when fmt='fits' is explicit.  GTI is preserved in our separate FITS
        # extension but is not consumed by that generic reader.
        with pytest.warns(AstropyUserWarning, match="multiple tables"):
            generic = EventList.read(str(path), fmt="fits", hdu=1)
        np.testing.assert_allclose(generic.time, [1.0, 2.0, 3.0])
        np.testing.assert_array_equal(generic.pi, [0, 1, 2])
        np.testing.assert_allclose(generic.energy, [9.0, 9.0, 9.0])
        assert generic.mjdref == pytest.approx(58_000.125)
        assert 'fmt="ogip"' not in inspect.getsource(service.export_object).lower()
    else:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        assert parsed["schema"] == "stingray-explorer.tabular.v1"
        assert parsed["row_count"] == 3
        assert set(parsed["column_units"]) == set(parsed["columns"])
        json.dumps(parsed, allow_nan=False)


@pytest.mark.parametrize(
    "object_type,object_name,export_format",
    [
        ("lightcurve", "curve", "ecsv"),
        ("analysis_result", "result", "json"),
    ],
)
def test_other_tabular_objects_export(
    service, tmp_path, object_type, object_name, export_format
):
    path = tmp_path / f"output.{export_format}"
    result = service.export_object(
        object_type,
        object_name,
        export_format,
        str(path),
        make_grant(path, "write"),
    )
    assert result["success"], result
    assert result["data"]["verified"] is True


@pytest.mark.parametrize("export_format", ["json", "ecsv", "fits"])
def test_analysis_units_metadata_and_provenance_are_preserved(
    service, io_state, tmp_path, export_format
):
    io_state.add_analysis_result(
        "timing lags",
        {
            "freq": [1.0, 2.0],
            "time_lags": [0.1, 0.2],
            "metadata": {
                "units": {"freq": "Hz", "time_lags": "s"},
                "method": "cross-spectrum",
            },
            "provenance": {"operation": "time_lag", "source": ["a", "b"]},
        },
    )
    path = tmp_path / f"timing-lags.{export_format}"

    result = service.export_object(
        "analysis_result",
        "timing lags",
        export_format,
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    if export_format == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["column_units"] == {"freq": "Hz", "time_lags": "s"}
        assert payload["metadata"]["metadata"]["method"] == "cross-spectrum"
        assert payload["metadata"]["provenance"]["operation"] == "time_lag"
    elif export_format == "ecsv":
        table = Table.read(path, format="ascii.ecsv")
        assert str(table["freq"].unit) == "Hz"
        assert str(table["time_lags"].unit) == "s"
        assert table.meta["metadata"]["method"] == "cross-spectrum"
        assert table.meta["provenance"]["operation"] == "time_lag"
    else:
        with fits.open(path, checksum=True) as hdul:
            assert hdul["DATA"].columns["freq"].unit == "Hz"
            assert hdul["DATA"].columns["time_lags"].unit == "s"
            encoded = hdul["METADATA"].data["JSON"][0]
            if isinstance(encoded, bytes):
                encoded = encoded.decode("ascii")
            metadata = json.loads(encoded)
            assert metadata["metadata"]["method"] == "cross-spectrum"
            assert metadata["provenance"]["operation"] == "time_lag"


def test_analysis_quantity_columns_keep_their_units(service, io_state, tmp_path):
    io_state.add_analysis_result(
        "quantity lags",
        {
            "frequency": np.asarray([1.0, 2.0]) * u.Hz,
            "lag": np.asarray([0.1, 0.2]) * u.s,
        },
    )
    path = tmp_path / "quantity-lags.json"

    result = service.export_object(
        "analysis_result",
        "quantity lags",
        "json",
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"], result
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["column_units"] == {"frequency": "Hz", "lag": "s"}


def test_analysis_catalog_checks_row_cap_before_table_copy(
    service, io_state, monkeypatch
):
    import services.io_utility_service as module

    monkeypatch.setattr(module, "MAX_EXPORT_ROWS", 2)
    oversized = Table({"frequency": [1.0, 2.0, 3.0]})
    io_state.add_analysis_result("oversized table", oversized)

    def forbidden_copy(*args, **kwargs):
        raise AssertionError("catalog must not copy an over-cap table")

    monkeypatch.setattr(oversized, "copy", forbidden_copy)
    result = service.list_exportable_objects()

    assert result["success"], result
    entry = next(
        item for item in result["data"]["objects"] if item["name"] == "oversized table"
    )
    assert entry["exportable"] is False
    assert "export cap is 2" in entry["reason"]


@pytest.mark.parametrize(
    "table,constant,value,error_text",
    [
        (
            Table({"a": [1.0], "b": [2.0], "c": [3.0]}),
            "MAX_EXPORT_COLUMNS",
            2,
            "column cap is 2",
        ),
        (
            Table({"a": [1.0, 2.0], "b": [3.0, 4.0]}),
            "MAX_EXPORT_CELLS",
            3,
            "cell cap is 3",
        ),
        (
            Table({"label": ["x" * 200]}),
            "MAX_EXPORT_ESTIMATED_BYTES",
            100,
            "estimated-size cap",
        ),
    ],
)
def test_analysis_catalog_checks_shape_and_size_caps_before_table_copy(
    service, io_state, monkeypatch, table, constant, value, error_text
):
    import services.io_utility_service as module

    monkeypatch.setattr(module, constant, value)
    name = f"capped-{constant}"
    io_state.add_analysis_result(name, table)

    def forbidden_copy(*args, **kwargs):
        raise AssertionError("catalog must reject before copying the table")

    monkeypatch.setattr(table, "copy", forbidden_copy)
    result = service.list_exportable_objects()

    assert result["success"], result
    entry = next(item for item in result["data"]["objects"] if item["name"] == name)
    assert entry["exportable"] is False
    assert error_text in entry["reason"]


def test_analysis_size_cap_counts_shared_metadata_each_time(
    service, io_state, monkeypatch
):
    import services.io_utility_service as module

    shared = np.zeros(8, dtype=np.float64)
    io_state.add_analysis_result(
        "shared metadata",
        {"value": [1.0], "metadata": {"first": shared, "second": shared}},
    )
    monkeypatch.setattr(module, "MAX_EXPORT_ESTIMATED_BYTES", 100)

    listed = service.list_exportable_objects()

    entry = next(
        item for item in listed["data"]["objects"] if item["name"] == "shared metadata"
    )
    assert entry["exportable"] is False
    assert "estimated-size cap" in entry["reason"]


def test_analysis_catalog_rejects_cyclic_metadata(service, io_state):
    metadata = {}
    metadata["self"] = metadata
    io_state.add_analysis_result(
        "cyclic metadata", {"value": [1.0], "metadata": metadata}
    )

    listed = service.list_exportable_objects()

    entry = next(
        item for item in listed["data"]["objects"] if item["name"] == "cyclic metadata"
    )
    assert entry["exportable"] is False
    assert "cycle" in entry["reason"]


def test_nested_analysis_metadata_size_cap_precedes_deepcopy(
    service, io_state, tmp_path, monkeypatch
):
    import services.io_utility_service as io_module
    import services.state_manager as state_module

    io_state.add_analysis_result(
        "large metadata",
        {"value": [1.0], "metadata": {"blob": np.zeros(64, dtype=np.float64)}},
    )
    monkeypatch.setattr(io_module, "MAX_EXPORT_ESTIMATED_BYTES", 100)

    def forbidden_deepcopy(*args, **kwargs):
        raise AssertionError("metadata size preflight must run before deepcopy")

    monkeypatch.setattr(state_module.copy, "deepcopy", forbidden_deepcopy)
    path = tmp_path / "large-metadata.json"
    result = service.export_object(
        "analysis_result",
        "large metadata",
        "json",
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"] is False
    assert "operation size cap" in result["message"]
    assert not path.exists()


def test_analysis_row_cap_runs_before_sequence_array_conversion_or_deepcopy(
    service, io_state, tmp_path, monkeypatch
):
    import services.io_utility_service as io_module
    import services.state_manager as state_module

    oversized = [1.0, 2.0, 3.0]
    io_state.add_analysis_result("oversized sequence", {"value": oversized})
    monkeypatch.setattr(io_module, "MAX_EXPORT_ROWS", 2)
    real_asarray = state_module.np.asarray

    def guarded_asarray(value, *args, **kwargs):
        if value is oversized:
            raise AssertionError(
                "row preflight must not materialize the Python sequence"
            )
        return real_asarray(value, *args, **kwargs)

    def forbidden_deepcopy(*args, **kwargs):
        raise AssertionError("row preflight must run before deepcopy")

    monkeypatch.setattr(state_module.np, "asarray", guarded_asarray)
    monkeypatch.setattr(state_module.copy, "deepcopy", forbidden_deepcopy)
    path = tmp_path / "oversized-sequence.json"

    result = service.export_object(
        "analysis_result",
        "oversized sequence",
        "json",
        str(path),
        make_grant(path, "write"),
    )

    assert result["success"] is False
    assert "operation cap is 2" in result["message"]
    assert not path.exists()


@pytest.mark.parametrize("object_type", ["event_list", "lightcurve"])
def test_loaded_object_cell_cap_precedes_deepcopy_and_catalog_table_build(
    service, io_state, tmp_path, monkeypatch, object_type
):
    import services.io_utility_service as io_module
    import services.state_manager as state_module

    if object_type == "event_list":
        obj = EventList(time=np.asarray([1.0]))
        io_state.add_event_data("wide events", obj)
    else:
        obj = Lightcurve(time=np.asarray([1.0]), counts=np.asarray([2.0]), dt=1.0)
        io_state.add_lightcurve_data("wide curve", obj)
    for index in range(8):
        setattr(obj, f"extra_{index}", np.asarray([float(index)]))
    monkeypatch.setattr(io_module, "MAX_EXPORT_CELLS", 5)

    listed = service.list_exportable_objects()
    name = "wide events" if object_type == "event_list" else "wide curve"
    entry = next(item for item in listed["data"]["objects"] if item["name"] == name)
    assert entry["exportable"] is False
    assert "cell cap is 5" in entry["reason"]

    def forbidden_deepcopy(*args, **kwargs):
        raise AssertionError("cell preflight must run before deepcopy")

    monkeypatch.setattr(state_module.copy, "deepcopy", forbidden_deepcopy)
    path = tmp_path / f"{object_type}.json"
    exported = service.export_object(
        object_type,
        name,
        "json",
        str(path),
        make_grant(path, "write"),
    )
    assert exported["success"] is False
    assert "operation cell cap is 5" in exported["message"]
    assert not path.exists()


def test_loaded_object_column_cap_precedes_deepcopy(
    service, io_state, tmp_path, monkeypatch
):
    import services.io_utility_service as io_module
    import services.state_manager as state_module

    events = EventList(time=np.asarray([1.0]))
    for index in range(4):
        setattr(events, f"custom_{index}", np.asarray([float(index)]))
    io_state.add_event_data("many columns", events)
    monkeypatch.setattr(io_module, "MAX_EXPORT_COLUMNS", 2)

    listed = service.list_exportable_objects()
    entry = next(
        item for item in listed["data"]["objects"] if item["name"] == "many columns"
    )
    assert entry["exportable"] is False
    assert "column cap is 2" in entry["reason"]

    def forbidden_deepcopy(*args, **kwargs):
        raise AssertionError("column preflight must run before deepcopy")

    monkeypatch.setattr(state_module.copy, "deepcopy", forbidden_deepcopy)
    path = tmp_path / "many-columns.json"
    exported = service.export_object(
        "event_list",
        "many columns",
        "json",
        str(path),
        make_grant(path, "write"),
    )
    assert exported["success"] is False
    assert "operation column cap is 2" in exported["message"]
    assert not path.exists()


def test_loaded_time_row_cap_precedes_array_materialization(
    service, io_state, monkeypatch
):
    import services.io_utility_service as module

    oversized_time = [1.0, 2.0, 3.0]
    events = EventList(time=np.asarray([1.0]))
    events._time = oversized_time
    io_state.add_event_data("list-backed time", events)
    monkeypatch.setattr(module, "MAX_EXPORT_ROWS", 2)
    real_asarray = module.np.asarray

    def guarded_asarray(value, *args, **kwargs):
        if value is oversized_time:
            raise AssertionError("row preflight must precede time-array conversion")
        return real_asarray(value, *args, **kwargs)

    monkeypatch.setattr(module.np, "asarray", guarded_asarray)

    listed = service.list_exportable_objects()

    entry = next(
        item for item in listed["data"]["objects"] if item["name"] == "list-backed time"
    )
    assert entry["exportable"] is False
    assert "operation cap is 2" in entry["reason"]


def test_export_refuses_existing_destination_without_changing_it(service, tmp_path):
    path = tmp_path / "existing.json"
    sentinel = b"user-owned sentinel"
    path.write_bytes(sentinel)
    result = service.export_object(
        "event_list",
        "events",
        "json",
        str(path),
        make_grant(path, "write"),
    )
    assert result["success"] is False
    assert "already exists" in result["message"]
    assert path.read_bytes() == sentinel


def test_export_requires_exact_extension_and_exact_write_grant(service, tmp_path):
    wrong_extension = tmp_path / "events.txt"
    extension_result = service.export_object(
        "event_list",
        "events",
        "json",
        str(wrong_extension),
        make_grant(wrong_extension, "write"),
    )
    assert extension_result["success"] is False
    assert "exact '.json'" in extension_result["message"]
    assert not wrong_extension.exists()

    path = tmp_path / "events.json"
    other = tmp_path / "other.json"
    grant = make_grant(path, "write", signed_path=other)
    grant_result = service.export_object(
        "event_list", "events", "json", str(path), grant
    )
    assert grant_result["success"] is False
    assert not path.exists()

    unsupported = tmp_path / "events.pickle"
    unsupported_result = service.export_object(
        "event_list",
        "events",
        "pickle",
        str(unsupported),
        make_grant(unsupported, "write"),
    )
    assert unsupported_result["success"] is False
    assert "format must be one of" in unsupported_result["message"]
    assert not unsupported.exists()


def test_export_row_cap_and_failure_cleanup(service, tmp_path, monkeypatch):
    import services.io_utility_service as module

    monkeypatch.setattr(module, "MAX_EXPORT_ROWS", 2)
    capped = tmp_path / "capped.csv"
    result = service.export_object(
        "event_list",
        "events",
        "csv",
        str(capped),
        make_grant(capped, "write"),
    )
    assert result["success"] is False
    assert "operation cap is 2" in result["message"]
    assert not capped.exists()

    monkeypatch.setattr(module, "MAX_EXPORT_ROWS", 10)
    failed = tmp_path / "failed.csv"

    def fail_write(*args, **kwargs):
        raise OSError("synthetic writer failure")

    monkeypatch.setattr(Table, "write", fail_write)
    failed_result = service.export_object(
        "event_list",
        "events",
        "csv",
        str(failed),
        make_grant(failed, "write"),
    )
    assert failed_result["success"] is False
    assert "synthetic writer failure" in failed_result["message"]
    assert not failed.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []


def test_export_detects_destination_replacement_and_does_not_delete_replacement(
    service, tmp_path, monkeypatch
):
    destination = tmp_path / "events.json"
    attacker_file = tmp_path / "replacement.json"
    replacement_bytes = b'{"user":"replacement"}'
    attacker_file.write_bytes(replacement_bytes)

    real_link = os.link

    def replace_before_publish(source, target, **kwargs):
        os.replace(attacker_file, destination)
        return real_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", replace_before_publish)
    result = service.export_object(
        "event_list",
        "events",
        "json",
        str(destination),
        make_grant(destination, "write"),
    )
    assert result["success"] is False
    assert "already exists" in result["message"]
    # Atomic publication refuses the replacement, and cleanup touches only the
    # private staging artifact rather than this user-visible destination.
    assert destination.read_bytes() == replacement_bytes
    assert list(tmp_path.glob(".stingray-export-*")) == []


def test_export_parent_swap_cannot_redirect_staging_or_cleanup(
    service, tmp_path, monkeypatch
):
    import services.io_utility_service as module

    selected_parent = tmp_path / "selected-parent"
    selected_parent.mkdir()
    moved_parent = tmp_path / "moved-parent"
    destination = selected_parent / "events.json"
    grant = make_grant(destination, "write")
    real_mkdir = os.mkdir
    swapped = False

    def swap_before_staging(name, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and str(name).startswith(".stingray-export-"):
            swapped = True
            os.rename(selected_parent, moved_parent)
            real_mkdir(selected_parent, 0o755)
            (selected_parent / "sentinel").write_bytes(b"replacement directory")
        return real_mkdir(name, mode, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "mkdir", swap_before_staging)
    result = service.export_object(
        "event_list",
        "events",
        "json",
        str(destination),
        grant,
    )

    assert result["success"] is False
    assert (selected_parent / "sentinel").read_bytes() == b"replacement directory"
    assert not destination.exists()
    assert not (moved_parent / destination.name).exists()
    assert list(moved_parent.glob(".stingray-export-*")) == []


def test_export_cleanup_uses_pinned_directories_after_parent_swap(
    service, tmp_path, monkeypatch
):
    import services.io_utility_service as module

    selected_parent = tmp_path / "selected-parent"
    selected_parent.mkdir()
    moved_parent = tmp_path / "moved-parent"
    destination = selected_parent / "events.json"
    grant = make_grant(destination, "write")
    replacement_bytes = b"replacement staging artifact"
    real_mkdir = os.mkdir
    real_unlink = os.unlink
    replacement_artifact: Path | None = None

    def swap_before_cleanup(name, *, dir_fd=None):
        nonlocal replacement_artifact
        if replacement_artifact is None and str(name).startswith("artifact"):
            os.rename(selected_parent, moved_parent)
            real_mkdir(selected_parent, 0o755)
            staging_name = next(moved_parent.glob(".stingray-export-*")).name
            replacement_staging = selected_parent / staging_name
            real_mkdir(replacement_staging, 0o700)
            replacement_artifact = replacement_staging / str(name)
            replacement_artifact.write_bytes(replacement_bytes)
        return real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "unlink", swap_before_cleanup)
    result = service.export_object(
        "event_list",
        "events",
        "json",
        str(destination),
        grant,
    )

    assert result["success"], result
    assert replacement_artifact is not None
    assert replacement_artifact.read_bytes() == replacement_bytes
    assert (moved_parent / destination.name).is_file()
    assert not destination.exists()
    assert list(moved_parent.glob(".stingray-export-*")) == []


def test_export_cleanup_retains_replacement_staging_directory(
    service, tmp_path, monkeypatch
):
    import services.io_utility_service as module

    destination = tmp_path / "events.json"
    real_open = os.open
    real_close = os.close
    real_mkdir = os.mkdir
    real_rename = os.rename
    parent_descriptor: int | None = None
    staging_descriptor: int | None = None
    staging_name: str | None = None
    replacement_created = False

    def tracked_open(name, flags, *args, **kwargs):
        nonlocal parent_descriptor, staging_descriptor, staging_name
        descriptor = real_open(name, flags, *args, **kwargs)
        if Path(name) == tmp_path.resolve():
            parent_descriptor = descriptor
        elif str(name).startswith(".stingray-export-"):
            staging_descriptor = descriptor
            staging_name = str(name)
        return descriptor

    def swap_before_staging_close(descriptor):
        nonlocal replacement_created
        if descriptor == staging_descriptor and not replacement_created:
            assert parent_descriptor is not None
            assert staging_name is not None
            real_rename(
                staging_name,
                f"{staging_name}.original",
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            real_mkdir(staging_name, 0o700, dir_fd=parent_descriptor)
            replacement_created = True
        return real_close(descriptor)

    monkeypatch.setattr(module.os, "open", tracked_open)
    monkeypatch.setattr(module.os, "close", swap_before_staging_close)
    result = service.export_object(
        "event_list",
        "events",
        "json",
        str(destination),
        make_grant(destination, "write"),
    )

    assert result["success"], result
    assert replacement_created
    assert staging_name is not None
    assert (tmp_path / staging_name).is_dir()
    assert (tmp_path / f"{staging_name}.original").is_dir()
    assert any("identity changed" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    ("failure_kind", "failure_role"),
    [
        ("fstat", "write"),
        ("fdopen", "write"),
        ("fstat", "read"),
        ("fdopen", "read"),
    ],
)
def test_export_closes_raw_descriptors_on_setup_failure(
    service, tmp_path, monkeypatch, failure_kind, failure_role
):
    import services.io_utility_service as module

    destination = tmp_path / "events.json"
    real_open = os.open
    real_fstat = os.fstat
    real_fdopen = os.fdopen
    captured: dict[str, int] = {}

    def tracked_open(name, flags, *args, **kwargs):
        descriptor = real_open(name, flags, *args, **kwargs)
        if str(name).startswith("artifact"):
            role = "write" if flags & os.O_WRONLY else "read"
            captured[role] = descriptor
        return descriptor

    def injected_fstat(descriptor):
        if failure_kind == "fstat" and descriptor == captured.get(failure_role):
            raise OSError(f"synthetic {failure_role} fstat failure")
        return real_fstat(descriptor)

    def injected_fdopen(descriptor, *args, **kwargs):
        if failure_kind == "fdopen" and descriptor == captured.get(failure_role):
            raise OSError(f"synthetic {failure_role} fdopen failure")
        return real_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", tracked_open)
    monkeypatch.setattr(module.os, "fstat", injected_fstat)
    monkeypatch.setattr(module.os, "fdopen", injected_fdopen)
    result = service.export_object(
        "event_list",
        "events",
        "json",
        str(destination),
        make_grant(destination, "write"),
    )

    assert result["success"] is False
    assert f"synthetic {failure_role} {failure_kind} failure" in result["message"]
    assert not destination.exists()
    assert failure_role in captured
    for descriptor in set(captured.values()):
        with pytest.raises(OSError):
            real_fstat(descriptor)
    staging_entries = list(tmp_path.glob(".stingray-export-*"))
    if (failure_kind, failure_role) == ("fstat", "write"):
        # The artifact identity could not be authenticated, so fail closed and
        # retain the private entry rather than risk deleting a replacement.
        assert len(staging_entries) == 1
    else:
        assert staging_entries == []


def test_success_payloads_are_strict_json_serializable(service, rmf_path):
    results = [
        service.inspect_rmf(str(rmf_path), make_grant(rmf_path, "read")),
        service.convert_pi_values([0, 1], str(rmf_path), make_grant(rmf_path, "read")),
        service.list_exportable_objects(),
    ]
    for result in results:
        assert result["success"], result
        json.dumps(result, allow_nan=False)


def test_request_models_forbid_extras_and_nonfinite_values():
    with pytest.raises(ValidationError):
        GrantedInputRequest(file_path="/x", file_grant="token", surprise=True)
    with pytest.raises(ValidationError):
        ConvertPiRequest(rmf_path="/x", rmf_grant="token", pi_values=[float("nan")])


def test_request_models_accept_existing_source_names_from_ingestion():
    long_source_name = "loaded-" + "x" * 300

    conversion = ConvertEventListRequest(
        rmf_path="/selected.rmf",
        rmf_grant="token",
        event_list_name=long_source_name,
    )
    export = ExportObjectRequest(
        object_type="event_list",
        object_name=long_source_name,
        format="json",
        destination_path="/selected.json",
        destination_grant="token",
    )

    assert conversion.event_list_name == long_source_name
    assert export.object_name == long_source_name


def test_all_routes_are_registered_and_offload_to_threads():
    paths = {route.path for route in io_utility_routes.router.routes}
    assert paths == {
        "/inspect-file",
        "/inspect-rmf",
        "/convert-pi",
        "/convert-event-list",
        "/exportable-objects",
        "/export",
    }
    for route in io_utility_routes.router.routes:
        assert "asyncio.to_thread" in inspect.getsource(route.endpoint), route.path


@pytest.mark.asyncio
async def test_io_route_remains_responsive_while_service_runs(monkeypatch):
    def slow_list(self):
        time.sleep(0.6)
        return {"success": True, "data": {}, "message": "ok", "error": None}

    monkeypatch.setattr(IOUtilityService, "list_exportable_objects", slow_list)
    app = FastAPI()
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None
    app.include_router(io_utility_routes.router, prefix="/api/utilities/io")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        slow_task = asyncio.create_task(
            client.get("/api/utilities/io/exportable-objects")
        )
        started = time.monotonic()
        await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        elapsed = time.monotonic() - started
        response = await slow_task
    assert response.status_code == 200
    assert elapsed < 0.4, f"event loop was blocked for {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_convert_pi_route_end_to_end(rmf_path):
    app = FastAPI()
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None
    app.include_router(io_utility_routes.router, prefix="/api/utilities/io")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/utilities/io/convert-pi",
            json={
                "pi_values": [0, 2],
                "rmf_path": str(rmf_path),
                "rmf_grant": make_grant(rmf_path, "read"),
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"], body
    assert [row["pi"] for row in body["data"]["rows"]] == [0, 2]
