"""Verified optional HDF5 export coverage for General I/O."""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import time
import warnings
from collections import UserDict
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from astropy import units as u
from astropy.table import Column, MaskedColumn, Table
from astropy.utils.masked import Masked
from pydantic import ValidationError
from routes.io_utility_routes import ExportObjectRequest
from services import io_utility_service as io_module
from services.io_utility_service import (
    HDF5_MANIFEST_PATH,
    HDF5_SCHEMA,
    HDF5_TABLE_PATH,
    HDF5_UNAVAILABLE_REASON,
    HDF5_VERIFICATION_CHECKS,
    IOUtilityService,
)
from services.state_manager import StateManager
from services.utility_helpers import FILE_GRANT_VERSION
from stingray import EventList, Lightcurve

TEST_SECRET = "hdf5-export-test-file-grant-secret"
CORE_FORMATS = ["csv", "ecsv", "json", "fits"]


@pytest.fixture(autouse=True)
def file_grant_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STINGRAY_FILE_GRANT_SECRET", TEST_SECRET)


def make_write_grant(path: Path, *, expires_delta: int = 300) -> str:
    resolved = path.parent.resolve(strict=True) / path.name
    expires = int(time.time()) + expires_delta
    parent_stat = resolved.parent.stat()
    prefix = f"{FILE_GRANT_VERSION}.{expires}.{parent_stat.st_dev}.{parent_stat.st_ino}"
    digest = hmac.new(
        TEST_SECRET.encode(),
        (
            f"{FILE_GRANT_VERSION}\0write\0{expires}\0{resolved}\0"
            f"{parent_stat.st_dev}\0{parent_stat.st_ino}"
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{prefix}.{digest}"


def installed_h5py() -> Any:
    module, reason = io_module._optional_hdf5_runtime()
    if module is None:
        pytest.skip(reason)
    return module


def read_export(path: Path, object_type: str, object_name: str) -> Table:
    h5py_module = installed_h5py()
    with path.open("rb") as stream:
        table, _manifest = io_module._read_hdf5_table(
            stream,
            h5py_module,
            object_type=object_type,
            object_name=object_name,
        )
    return table


def assert_private_failure(path: Path, result: dict[str, Any]) -> None:
    assert result["success"] is False, result
    assert not path.exists()
    assert list(path.parent.glob(".stingray-export-*")) == []


@pytest.fixture
def representative_state() -> StateManager:
    state = StateManager()
    events = EventList(
        time=np.asarray([1.0, 2.0, 3.0], dtype=np.float64),
        pi=np.asarray([10, 11, 12], dtype=np.int16),
        energy=np.asarray([0.5, 0.75, 1.0], dtype=np.float32),
        gti=np.empty((0, 2), dtype=np.float32),
        mjdref=58_000.125,
        dt=0.125,
    )
    events.detector_id = np.asarray([0, 1, 2], dtype=np.uint8)
    events.mission = "NICER"
    events.instr = "XTI"
    events.header = "TELESCOP=NICER;INSTRUME=XTI"
    events.rmf_conversion_provenance = {
        "operation": "rmf_event_list_pi_to_energy",
        "calibrated": True,
    }
    events.mission_io_conversion_type = "rough_approximate"
    events.mission_io_provenance_json = '{"operation":"mission_io.rough_pi_to_energy"}'
    state.add_event_data("events complete", events)

    curve = Lightcurve(
        time=np.asarray([1.0, 2.0, 3.0]),
        counts=np.asarray([10.0, 12.0, 11.0]),
        dt=1.0,
        gti=np.asarray([[0.5, 3.5]]),
        bg_counts=np.asarray([1.0, 1.5, 1.25]),
        bg_ratio=np.asarray([2.0, 2.0, 2.0]),
        frac_exp=np.asarray([1.0, 0.8, 0.9]),
        mjdref=58_000.125,
    )
    # These are valid lazy scientific arrays in Stingray 2.2.10.
    _ = curve.bin_lo, curve.bin_hi
    curve.mission = "NICER"
    curve.header = "TELESCOP=NICER"
    curve.custom_flux = np.asarray([4.0, 5.0, 6.0]) * (u.erg / u.s)
    curve.custom_quality = np.ma.array(
        [8.0, 9.0, 10.0],
        mask=[True, False, False],
        fill_value=-19.0,
    )
    curve.custom_masked_quantity = Masked(
        np.asarray([3.0, 4.0, 5.0]) * u.s,
        mask=[True, False, False],
    )
    curve.lightcurve_provenance = {"operation": "background_corrected"}
    state.add_lightcurve_data("curve complete", curve)

    analysis = Table()
    analysis["nullable"] = MaskedColumn(
        np.asarray([1.25, np.nan], dtype=">f8"),
        mask=[True, False],
        fill_value=-7.25,
        unit=u.s,
        description="A masked lag and an unmasked NaN",
        meta={"role": "lag"},
    )
    analysis["nullable"].format = ".3f"
    analysis["label"] = Column(["low", "high"])
    analysis["channel"] = Column(np.asarray([1, 2], dtype=">u2"))
    analysis.meta = {
        "metadata": {
            "method": "cross-spectrum",
            "non_column_fields": ["band"],
        },
        "band": (0.5, 2.0),
        "provenance": {
            "operation": "timing_time_lags",
            "source": ["a", "b"],
        },
    }
    state.add_analysis_result("analysis complete", analysis)
    return state


def test_hdf5_capability_and_request_contract(
    representative_state: StateManager,
) -> None:
    h5py_module = installed_h5py()
    service = IOUtilityService(representative_state)

    result = service.list_exportable_objects()

    assert result["success"], result
    data = result["data"]
    assert data["format_allowlist"] == [*CORE_FORMATS, "hdf5"]
    assert "hdf5" not in data["excluded_formats"]
    for object_type, formats in data["capability_matrix"].items():
        capability = formats["hdf5"]
        assert capability == {
            "supported": True,
            "notes": (
                "Versioned Stingray Explorer HDF5 table with a complete semantic "
                "reopen comparison before publication."
            ),
            "reason": None,
            "extensions": [".hdf5"],
            "dependency": {
                "name": "h5py",
                "available": True,
                "version": h5py_module.__version__,
            },
        }, object_type
    assert all(
        item["formats"] == [*CORE_FORMATS, "hdf5"] and item["format_reasons"] == {}
        for item in data["objects"]
    )
    request = ExportObjectRequest(
        object_type="event_list",
        object_name="events complete",
        format="hdf5",
        destination_path="/selected/events.hdf5",
        destination_grant="grant",
    )
    assert request.format == "hdf5"
    with pytest.raises(ValidationError):
        ExportObjectRequest(
            object_type="event_list",
            object_name="events complete",
            format="h5",
            destination_path="/selected/events.h5",
            destination_grant="grant",
        )


@pytest.mark.parametrize(
    ("object_class", "relative_path", "object_type", "required_metadata"),
    [
        (
            EventList,
            "monol_testA.evt",
            "event_list",
            {"header", "mjdref", "mission", "instr", "t_start", "t_stop"},
        ),
        (
            Lightcurve,
            "lcurveA.fits",
            "lightcurve",
            {
                "header",
                "mjdref",
                "high_precision",
                "input_counts",
                "low_memory",
                "tstart",
                "tseg",
            },
        ),
    ],
)
def test_repository_representative_scientific_file_round_trip(
    object_class: Any,
    relative_path: str,
    object_type: str,
    required_metadata: set[str],
) -> None:
    h5py_module = installed_h5py()
    source_path = Path(__file__).parents[2] / "files" / "data" / relative_path
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        source = object_class.read(str(source_path), fmt="hea")
    table = io_module._table_for_object(
        source,
        object_type,
        preserve_timing_precision=True,
    )
    try:
        table, manifest = io_module._prepare_hdf5_table(table)
    except ValueError as exception:
        if np.dtype(np.longdouble).itemsize > 8:
            assert "width is unsupported" in str(exception)
            return
        raise
    stream = io.BytesIO()

    io_module._write_hdf5_table(
        stream,
        h5py_module,
        table,
        manifest,
        object_type=object_type,
        object_name="representative",
    )
    stream.seek(0)
    reopened, reopened_manifest = io_module._read_hdf5_table(
        stream,
        h5py_module,
        object_type=object_type,
        object_name="representative",
    )

    assert required_metadata <= set(reopened.meta)
    assert reopened_manifest == manifest
    assert io_module._verify_hdf5_table(table, reopened) == HDF5_VERIFICATION_CHECKS


def test_hdf5_event_list_round_trip_preserves_all_fields_and_provenance(
    representative_state: StateManager, tmp_path: Path
) -> None:
    installed_h5py()
    service = IOUtilityService(representative_state)
    path = tmp_path / "events.hdf5"

    result = service.export_object(
        "event_list",
        "events complete",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert result["success"], result
    assert result["data"]["verification"] == {
        "schema": HDF5_SCHEMA,
        "table_path": HDF5_TABLE_PATH,
        "semantic_round_trip": True,
        "checks": HDF5_VERIFICATION_CHECKS,
        "h5py_version": installed_h5py().__version__,
    }
    assert result["data"]["bytes"] == path.stat().st_size > 0
    with installed_h5py().File(path, "r") as handle:
        assert HDF5_TABLE_PATH in handle
        assert HDF5_MANIFEST_PATH in handle
    table = read_export(path, "event_list", "events complete")
    expected = io_module._table_for_object(
        representative_state.copy_event_data("events complete"),
        "event_list",
        preserve_timing_precision=True,
    )
    expected, _ = io_module._prepare_hdf5_table(expected)
    assert table.colnames == expected.colnames
    assert set(table.colnames) >= {"time", "pi", "energy", "detector_id"}
    assert table["pi"].dtype == np.dtype("int16")
    assert table["energy"].dtype == np.dtype("float32")
    assert table["detector_id"].dtype == np.dtype("uint8")
    assert table.meta["gti_status"] == "present"
    assert table.meta["gti"].shape == (0, 2)
    assert table.meta["mjdref"] == pytest.approx(58_000.125)
    assert table.meta["mission"] == "NICER"
    assert table.meta["instr"] == "XTI"
    assert table.meta["header"] == "TELESCOP=NICER;INSTRUME=XTI"
    assert (
        table.meta["rmf_conversion_provenance"]["operation"]
        == "rmf_event_list_pi_to_energy"
    )
    assert table.meta["mission_io_conversion_type"] == "rough_approximate"
    assert "mission_io.rough_pi_to_energy" in table.meta["mission_io_provenance_json"]


def test_hdf5_distinguishes_missing_gti_from_explicit_empty(
    representative_state: StateManager, tmp_path: Path
) -> None:
    installed_h5py()
    no_gti = EventList(time=[1.0, 2.0], pi=[1, 2])
    assert no_gti._gti is None
    representative_state.add_event_data("events missing gti", no_gti)
    service = IOUtilityService(representative_state)
    missing_path = tmp_path / "missing.hdf5"
    empty_path = tmp_path / "empty.hdf5"

    missing_result = service.export_object(
        "event_list",
        "events missing gti",
        "hdf5",
        str(missing_path),
        make_write_grant(missing_path),
    )
    empty_result = service.export_object(
        "event_list",
        "events complete",
        "hdf5",
        str(empty_path),
        make_write_grant(empty_path),
    )

    assert missing_result["success"], missing_result
    assert empty_result["success"], empty_result
    assert any("no explicit GTI" in warning for warning in missing_result["warnings"])
    missing = read_export(missing_path, "event_list", "events missing gti")
    empty = read_export(empty_path, "event_list", "events complete")
    assert missing.meta["gti_status"] == "missing"
    assert "gti" not in missing.meta
    assert empty.meta["gti_status"] == "present"
    assert empty.meta["gti"].shape == (0, 2)
    assert (
        empty.meta["gti"].dtype
        == representative_state.get_event_data("events complete")._gti.dtype
    )
    assert representative_state.get_event_data("events missing gti")._gti is None


def test_hdf5_lightcurve_round_trip_keeps_scientific_arrays(
    representative_state: StateManager, tmp_path: Path
) -> None:
    installed_h5py()
    service = IOUtilityService(representative_state)
    path = tmp_path / "curve.hdf5"

    result = service.export_object(
        "lightcurve",
        "curve complete",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert result["success"], result
    table = read_export(path, "lightcurve", "curve complete")
    for name in (
        "time",
        "counts",
        "bg_counts",
        "bg_ratio",
        "frac_exp",
        "bin_lo",
        "bin_hi",
        "custom_flux",
        "custom_quality",
        "custom_masked_quantity",
    ):
        assert name in table.colnames
    np.testing.assert_allclose(table["bg_counts"], [1.0, 1.5, 1.25])
    np.testing.assert_allclose(table["bg_ratio"], [2.0, 2.0, 2.0])
    np.testing.assert_allclose(table["frac_exp"], [1.0, 0.8, 0.9])
    np.testing.assert_allclose(table["custom_flux"], [4.0, 5.0, 6.0])
    assert table["custom_flux"].unit == u.erg / u.s
    assert table["custom_quality"].mask.tolist() == [True, False, False]
    assert table["custom_quality"].fill_value == pytest.approx(-19.0)
    assert table["custom_masked_quantity"].mask.tolist() == [True, False, False]
    assert table["custom_masked_quantity"].unit == u.s
    assert table["time"].unit == u.s
    assert table["counts"].unit == u.ct
    assert table["bg_counts"].unit == u.ct
    assert table["bin_lo"].unit == u.s
    assert table["bin_hi"].unit == u.s
    assert table.meta["gti_status"] == "present"
    np.testing.assert_allclose(table.meta["gti"], [[0.5, 3.5]])
    assert table.meta["mission"] == "NICER"
    assert table.meta["header"] == "TELESCOP=NICER"
    assert table.meta["dt"] == pytest.approx(1.0)
    assert table.meta["dt_unit"] == "s"
    assert table.meta["high_precision"] is False
    assert table.meta["input_counts"] is True
    assert table.meta["low_memory"] is False
    assert table.meta["notes"] == ""
    assert table.meta["tstart"] == pytest.approx(0.5)
    assert table.meta["tseg"] == pytest.approx(3.0)
    assert table.meta["lightcurve_provenance"] == {"operation": "background_corrected"}


def test_hdf5_lightcurve_preserves_per_bin_widths(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        curve = Lightcurve(
            time=np.asarray([0.5, 2.0, 4.5]),
            counts=np.asarray([1.0, 2.0, 3.0]),
            dt=np.asarray([1.0, 2.0, 3.0]),
        )
    state.add_lightcurve_data("variable bins", curve)
    service = IOUtilityService(state)
    path = tmp_path / "variable-bins.hdf5"

    result = service.export_object(
        "lightcurve",
        "variable bins",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert result["success"], result
    table = read_export(path, "lightcurve", "variable bins")
    np.testing.assert_allclose(table["dt"], [1.0, 2.0, 3.0])
    assert table["dt"].unit == u.s


def test_hdf5_analysis_round_trip_preserves_masks_nan_units_order_and_fill(
    representative_state: StateManager, tmp_path: Path
) -> None:
    h5py_module = installed_h5py()
    service = IOUtilityService(representative_state)
    path = tmp_path / "analysis.hdf5"

    result = service.export_object(
        "analysis_result",
        "analysis complete",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert result["success"], result
    with h5py_module.File(path, "r") as handle:
        manifest_dataset = handle[HDF5_MANIFEST_PATH]
        assert manifest_dataset.shape == ()
        assert manifest_dataset.dtype.kind == "S"
        assert not manifest_dataset.dtype.hasobject
    table = read_export(path, "analysis_result", "analysis complete")
    assert table.colnames == ["nullable", "label", "channel"]
    assert table["nullable"].dtype == np.dtype("float64")
    assert table["channel"].dtype == np.dtype("uint16")
    assert table["label"].dtype.kind == "U"
    assert table["nullable"].mask.tolist() == [True, False]
    assert np.isnan(table["nullable"].data.data[1])
    assert table["nullable"].fill_value == pytest.approx(-7.25)
    assert table["nullable"].unit == u.s
    assert table["nullable"].description == "A masked lag and an unmasked NaN"
    assert table["nullable"].format == ".3f"
    assert table["nullable"].meta == {"role": "lag"}
    assert table.meta["metadata"]["method"] == "cross-spectrum"
    assert table.meta["band"] == (0.5, 2.0)
    assert table.meta["provenance"]["operation"] == "timing_time_lags"


def test_nullable_python_none_becomes_mask_but_nan_remains_unmasked(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    state.add_analysis_result(
        "nullable",
        {
            "value": [None, float("nan"), 1.0],
            "metadata": {"units": {"value": "s"}},
        },
    )
    service = IOUtilityService(state)
    path = tmp_path / "nullable.hdf5"

    result = service.export_object(
        "analysis_result",
        "nullable",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert result["success"], result
    table = read_export(path, "analysis_result", "nullable")
    assert isinstance(table["value"], MaskedColumn)
    assert table["value"].mask.tolist() == [True, False, False]
    assert np.isnan(table["value"].data.data[1])
    assert table["value"].unit == u.s


def test_analysis_scalar_quantity_remains_unit_bearing_metadata(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    state.add_analysis_result(
        "scalar quantity",
        {
            "value": [1.0, 2.0],
            "exposure": np.asarray(3.5) * u.s,
        },
    )
    service = IOUtilityService(state)
    path = tmp_path / "scalar-quantity.hdf5"

    result = service.export_object(
        "analysis_result",
        "scalar quantity",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert result["success"], result
    table = read_export(path, "analysis_result", "scalar quantity")
    assert table.meta["exposure"] == 3.5 * u.s


@pytest.mark.parametrize(
    "quantity",
    [
        u.Quantity(np.uint64(2**64 - 1), u.ct, dtype=np.uint64),
        u.Quantity(np.asarray([1, 2], dtype=np.int16), u.ct, dtype=np.int16),
    ],
)
def test_integer_quantity_metadata_is_honestly_unsupported(
    quantity: u.Quantity,
) -> None:
    installed_h5py()
    state = StateManager()
    table = Table({"value": [1.0, 2.0]})
    table.meta["quantity"] = quantity
    state.add_analysis_result("integer quantity", table)

    listed = IOUtilityService(state).list_exportable_objects()

    assert listed["success"], listed
    entry = listed["data"]["objects"][0]
    assert entry["formats"] == CORE_FORMATS
    assert "integer or boolean Quantity" in entry["format_reasons"]["hdf5"]


def test_quantity_subclass_metadata_is_honestly_unsupported() -> None:
    installed_h5py()
    state = StateManager()
    table = Table({"value": [1.0]})
    # Angle carries additional type semantics beyond a base Quantity.
    from astropy.coordinates import Angle

    table.meta["angle"] = Angle(45.0, u.deg)
    state.add_analysis_result("quantity subclass", table)

    listed = IOUtilityService(state).list_exportable_objects()

    entry = listed["data"]["objects"][0]
    assert entry["formats"] == CORE_FORMATS
    assert "Quantity subclass 'Angle'" in entry["format_reasons"]["hdf5"]


@pytest.mark.parametrize(
    ("values", "mask"),
    [
        (np.asarray([1.0, 2.0]), np.asarray([False, False])),
        (np.asarray([], dtype=np.float64), np.asarray([], dtype=bool)),
    ],
)
def test_all_false_and_empty_masked_columns_round_trip(
    tmp_path: Path,
    values: np.ndarray,
    mask: np.ndarray,
) -> None:
    installed_h5py()
    state = StateManager()
    table = Table()
    table["value"] = MaskedColumn(
        values,
        mask=mask,
        fill_value=-19.5,
        unit=u.s,
    )
    state.add_analysis_result("all false mask", table)
    service = IOUtilityService(state)
    path = tmp_path / f"all-false-{len(values)}.hdf5"

    listed = service.list_exportable_objects()
    result = service.export_object(
        "analysis_result",
        "all false mask",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert "hdf5" in listed["data"]["objects"][0]["formats"]
    assert result["success"], result
    reopened = read_export(path, "analysis_result", "all false mask")
    assert isinstance(reopened["value"], MaskedColumn)
    assert reopened["value"].mask.tolist() == mask.tolist()
    assert reopened["value"].fill_value == pytest.approx(-19.5)
    assert reopened["value"].unit == u.s


@pytest.mark.filterwarnings("ignore:overflow encountered in cast:RuntimeWarning")
@pytest.mark.parametrize("byteorder", ["<", ">"])
@pytest.mark.parametrize(
    ("dtype_code", "fill_value"),
    [
        ("i1", -7),
        ("i2", -257),
        ("i4", -65_537),
        ("i8", -(2**40)),
        ("u1", 7),
        ("u2", 257),
        ("u4", 65_537),
        ("u8", 2**40),
        ("f2", np.nan),
        ("f4", np.inf),
        ("f8", -np.inf),
    ],
)
def test_hdf5_numeric_dtype_endian_and_fill_matrix(
    byteorder: str,
    dtype_code: str,
    fill_value: Any,
) -> None:
    h5py_module = installed_h5py()
    dtype = np.dtype(dtype_code).newbyteorder(byteorder)
    if dtype.kind == "i":
        info = np.iinfo(dtype)
        values = np.asarray([info.min, 0, info.max], dtype=dtype)
        mask = [False, True, False]
    elif dtype.kind == "u":
        info = np.iinfo(dtype)
        values = np.asarray([0, 1, info.max], dtype=dtype)
        mask = [False, True, False]
    else:
        values = np.asarray([np.nan, np.inf, -np.inf, -0.0], dtype=dtype)
        mask = [False, False, False, True]
    source = Table()
    with warnings.catch_warnings():
        # Astropy briefly probes its large default floating fill before
        # applying our explicit float16 fill, which can emit an irrelevant
        # cast-overflow warning.
        warnings.simplefilter("ignore", RuntimeWarning)
        source["value"] = MaskedColumn(
            values,
            mask=mask,
            fill_value=fill_value,
        )
    canonical, manifest = io_module._prepare_hdf5_table(source)
    stream = io.BytesIO()

    io_module._write_hdf5_table(
        stream,
        h5py_module,
        canonical,
        manifest,
        object_type="analysis_result",
        object_name="dtype matrix",
    )
    stream.seek(0)
    reopened, _ = io_module._read_hdf5_table(
        stream,
        h5py_module,
        object_type="analysis_result",
        object_name="dtype matrix",
    )

    assert reopened["value"].dtype.kind == dtype.kind
    assert reopened["value"].dtype.itemsize == dtype.itemsize
    assert io_module._verify_hdf5_table(canonical, reopened) == HDF5_VERIFICATION_CHECKS


@pytest.mark.parametrize(
    ("values", "fill_value"),
    [
        (np.asarray([False, True, False], dtype=bool), True),
        (np.asarray(["", "a", "z"], dtype="U1"), "?"),
        (np.asarray(["", "soft", "hard"], dtype="U8"), "missing"),
    ],
)
def test_hdf5_bool_and_unicode_width_fill_matrix(
    values: np.ndarray,
    fill_value: Any,
) -> None:
    h5py_module = installed_h5py()
    source = Table()
    source["value"] = MaskedColumn(
        values,
        mask=[False, True, False],
        fill_value=fill_value,
    )
    canonical, manifest = io_module._prepare_hdf5_table(source)
    stream = io.BytesIO()

    io_module._write_hdf5_table(
        stream,
        h5py_module,
        canonical,
        manifest,
        object_type="analysis_result",
        object_name="dtype matrix",
    )
    stream.seek(0)
    reopened, _ = io_module._read_hdf5_table(
        stream,
        h5py_module,
        object_type="analysis_result",
        object_name="dtype matrix",
    )

    assert reopened["value"].dtype == values.dtype
    assert io_module._verify_hdf5_table(canonical, reopened) == HDF5_VERIFICATION_CHECKS


def test_longdouble_timing_is_preserved_or_honestly_unsupported(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    events = EventList(time=[1.0, 2.0], pi=[1, 2])
    events.mjdref = np.longdouble("55197.00076601852")
    events._gti = np.asarray(
        [[np.longdouble("0.123456789012345"), np.longdouble("2.5")]],
        dtype=np.longdouble,
    )
    state.add_event_data("high precision timing", events)
    service = IOUtilityService(state)
    path = tmp_path / "high-precision.hdf5"

    listed = service.list_exportable_objects()

    assert listed["success"], listed
    entry = listed["data"]["objects"][0]
    if np.dtype(np.longdouble).itemsize > 8:
        assert entry["formats"] == CORE_FORMATS
        assert "width is unsupported" in entry["format_reasons"]["hdf5"]
        result = service.export_object(
            "event_list",
            "high precision timing",
            "hdf5",
            str(path),
            make_write_grant(path),
        )
        assert_private_failure(path, result)
        return

    assert "hdf5" in entry["formats"]
    result = service.export_object(
        "event_list",
        "high precision timing",
        "hdf5",
        str(path),
        make_write_grant(path),
    )
    assert result["success"], result
    table = read_export(path, "event_list", "high precision timing")
    assert table.meta["mjdref"] == events.mjdref
    assert table.meta["gti"].dtype.itemsize == np.dtype(np.longdouble).itemsize
    np.testing.assert_array_equal(table.meta["gti"], events._gti)


def test_table_backed_nullable_and_premasked_objects_keep_mask_and_fill(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    source = Table()
    source["nullable"] = Column(
        np.asarray([None, float("nan"), 1.0], dtype=object),
        unit=u.s,
    )
    source["hidden"] = MaskedColumn(
        np.asarray(["not-a-number", 2.5, 3.5], dtype=object),
        mask=[True, False, False],
        fill_value=-12.5,
        unit=u.keV,
        description="masked storage is not scientific data",
        meta={"role": "energy"},
    )
    source["already_masked"] = MaskedColumn(
        [4.0, 5.0, 6.0],
        mask=[False, True, False],
        fill_value=-44.0,
    )
    state.add_analysis_result("table nullable", source)
    service = IOUtilityService(state)
    path = tmp_path / "table-nullable.hdf5"

    result = service.export_object(
        "analysis_result",
        "table nullable",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert result["success"], result
    table = read_export(path, "analysis_result", "table nullable")
    assert table["nullable"].mask.tolist() == [True, False, False]
    assert np.isnan(table["nullable"].data.data[1])
    assert table["hidden"].mask.tolist() == [True, False, False]
    assert table["hidden"].fill_value == pytest.approx(-12.5)
    assert table["hidden"].unit == u.keV
    assert table["hidden"].description == "masked storage is not scientific data"
    assert table["hidden"].meta == {"role": "energy"}
    assert table["already_masked"].mask.tolist() == [False, True, False]
    assert table["already_masked"].fill_value == pytest.approx(-44.0)


def test_masked_payload_storage_is_not_compared_as_scientific_data() -> None:
    expected = Table()
    expected["value"] = MaskedColumn([1.0, 2.0], mask=[True, False], fill_value=-9.0)
    actual = expected.copy(copy_data=True)
    actual["value"].data.data[0] = 999.0

    checks = io_module._verify_hdf5_table(expected, actual)

    assert checks == HDF5_VERIFICATION_CHECKS


def test_noncoercible_source_fill_is_hdf5_specific_incompatibility(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    source = Table()
    source["value"] = MaskedColumn(
        np.asarray(["hidden", 2.5], dtype=object),
        mask=[True, False],
        fill_value="missing",
    )
    state.add_analysis_result("noncoercible fill", source)
    service = IOUtilityService(state)

    listed = service.list_exportable_objects()

    assert listed["success"], listed
    entry = listed["data"]["objects"][0]
    assert entry["exportable"] is True
    assert entry["formats"] == CORE_FORMATS
    assert "cannot preserve" in entry["format_reasons"]["hdf5"]
    path = tmp_path / "noncoercible-fill.hdf5"
    result = service.export_object(
        "analysis_result",
        "noncoercible fill",
        "hdf5",
        str(path),
        make_write_grant(path),
    )
    assert_private_failure(path, result)
    assert "custom fill value" in result["message"]


def test_callable_column_format_is_not_advertised_for_hdf5() -> None:
    installed_h5py()
    state = StateManager()
    source = Table({"value": [1.0, 2.0]})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        source["value"].format = lambda value: f"{value:.2f}"
    state.add_analysis_result("callable format", source)

    listed = IOUtilityService(state).list_exportable_objects()

    assert listed["success"], listed
    entry = listed["data"]["objects"][0]
    assert entry["formats"] == CORE_FORMATS
    assert "callable or non-text format" in entry["format_reasons"]["hdf5"]


def test_numpy_scalar_metadata_is_canonicalized_without_rounding(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    source = Table({"value": [1.0, 2.0]})
    source.meta["threshold"] = np.float32(1.1)
    source["value"].meta["floor"] = np.float32(0.1)
    state.add_analysis_result("numpy scalars", source)
    service = IOUtilityService(state)
    path = tmp_path / "numpy-scalars.hdf5"

    result = service.export_object(
        "analysis_result",
        "numpy scalars",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert result["success"], result
    reopened = read_export(path, "analysis_result", "numpy scalars")
    assert reopened.meta["threshold"] == float(np.float32(1.1))
    assert reopened["value"].meta["floor"] == float(np.float32(0.1))


def test_unstable_hdf5_metadata_and_names_keep_core_formats() -> None:
    installed_h5py()
    state = StateManager()

    class ArraySubclass(np.ndarray):
        pass

    mapping = Table({"value": [1.0]})
    mapping.meta["mapping"] = UserDict({"threshold": 1})
    state.add_analysis_result("mapping subclass", mapping)

    masked = Table({"value": [1.0]})
    masked.meta["quality"] = Masked(
        np.asarray([1.0, 2.0]) * u.s,
        mask=[True, False],
    )
    state.add_analysis_result("masked metadata", masked)

    array_subclass = Table({"value": [1.0]})
    array_subclass.meta["matrix"] = np.asarray([[1.0]]).view(ArraySubclass)
    state.add_analysis_result("ndarray subclass", array_subclass)

    custom_unit = Table({"value": [1.0]})
    custom_unit["value"].unit = u.def_unit("hdf5_unregistered_custom_unit")
    state.add_analysis_result("custom unit", custom_unit)

    control_name = Table({"a\0b": [1.0]})
    state.add_analysis_result("control name", control_name)

    listed = IOUtilityService(state).list_exportable_objects()

    assert listed["success"], listed
    entries = {entry["name"]: entry for entry in listed["data"]["objects"]}
    expected_reasons = {
        "mapping subclass": "mapping subclass 'UserDict'",
        "masked metadata": "masked metadata",
        "ndarray subclass": "ndarray subclass 'ArraySubclass'",
        "custom unit": "external custom-unit definition",
        "control name": "control characters in column name",
    }
    for name, reason in expected_reasons.items():
        assert entries[name]["formats"] == CORE_FORMATS
        assert reason in entries[name]["format_reasons"]["hdf5"]


def test_non_text_analysis_keys_are_rejected_before_collision_and_publication(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    state.add_analysis_result(
        "colliding keys",
        {1: [1.0, 2.0], "1": [3.0, 4.0]},
    )
    service = IOUtilityService(state)
    path = tmp_path / "colliding-keys.hdf5"

    listed = service.list_exportable_objects()
    result = service.export_object(
        "analysis_result",
        "colliding keys",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    entry = listed["data"]["objects"][0]
    assert entry["exportable"] is False
    assert entry["formats"] == []
    assert "field names must be text" in entry["reason"]
    assert_private_failure(path, result)
    assert "field names must be text" in result["message"]


def test_nul_object_name_is_hdf5_specific_and_never_publishes(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    name = "analysis\0hidden"
    state.add_analysis_result(name, Table({"value": [1.0]}))
    service = IOUtilityService(state)
    path = tmp_path / "nul-object-name.hdf5"

    listed = service.list_exportable_objects()
    result = service.export_object(
        "analysis_result",
        name,
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    entry = listed["data"]["objects"][0]
    assert entry["exportable"] is True
    assert entry["formats"] == CORE_FORMATS
    assert "NUL characters in object names" in entry["format_reasons"]["hdf5"]
    assert_private_failure(path, result)
    assert "NUL characters in object names" in result["message"]


def test_non_utf8_object_name_is_hdf5_specific_and_never_publishes(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    name = "analysis\ud800"
    state.add_analysis_result(name, Table({"value": [1.0]}))
    service = IOUtilityService(state)
    path = tmp_path / "non-utf8-object-name.hdf5"

    listed = service.list_exportable_objects()
    result = service.export_object(
        "analysis_result",
        name,
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    entry = listed["data"]["objects"][0]
    assert entry["formats"] == CORE_FORMATS
    assert "valid UTF-8 text" in entry["format_reasons"]["hdf5"]
    assert_private_failure(path, result)
    assert "valid UTF-8 text" in result["message"]


def test_reserved_astropy_metadata_key_is_hdf5_specific_and_never_publishes(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    table = Table({"value": [1.0]})
    table.meta["__serialized_columns__"] = "collision"
    state.add_analysis_result("reserved metadata", table)
    service = IOUtilityService(state)
    path = tmp_path / "reserved-metadata.hdf5"

    listed = service.list_exportable_objects()
    result = service.export_object(
        "analysis_result",
        "reserved metadata",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    entry = listed["data"]["objects"][0]
    assert entry["exportable"] is True
    assert entry["formats"] == CORE_FORMATS
    assert "reserved top-level metadata key" in entry["format_reasons"]["hdf5"]
    assert_private_failure(path, result)
    assert "reserved top-level metadata key" in result["message"]


def test_missing_h5py_is_honest_and_does_not_disable_other_formats(
    representative_state: StateManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import_module = io_module.importlib.import_module

    def import_without_h5py(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "h5py":
            raise ModuleNotFoundError("synthetic missing optional h5py")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(io_module.importlib, "import_module", import_without_h5py)
    service = IOUtilityService(representative_state)

    listed = service.list_exportable_objects()

    assert listed["success"], listed
    data = listed["data"]
    assert data["format_allowlist"] == CORE_FORMATS
    assert data["excluded_formats"]["hdf5"] == HDF5_UNAVAILABLE_REASON
    for matrix in data["capability_matrix"].values():
        assert matrix["hdf5"] == {
            "supported": False,
            "notes": "Optional HDF5 runtime dependency is unavailable.",
            "reason": HDF5_UNAVAILABLE_REASON,
            "extensions": [".hdf5"],
            "dependency": {
                "name": "h5py",
                "available": False,
                "version": None,
            },
        }
    assert all(
        item["formats"] == CORE_FORMATS
        and item["format_reasons"] == {"hdf5": HDF5_UNAVAILABLE_REASON}
        for item in data["objects"]
    )

    path = tmp_path / "unavailable.hdf5"
    result = service.export_object(
        "event_list",
        "events complete",
        "hdf5",
        str(path),
        make_write_grant(path),
    )
    assert_private_failure(path, result)
    assert HDF5_UNAVAILABLE_REASON in result["message"]

    json_path = tmp_path / "still-available.json"
    json_result = service.export_object(
        "event_list",
        "events complete",
        "json",
        str(json_path),
        make_write_grant(json_path),
    )
    assert json_result["success"], json_result
    assert json_path.exists()


def test_object_specific_hdf5_incompatibility_keeps_core_formats(
    tmp_path: Path,
) -> None:
    installed_h5py()
    state = StateManager()
    table = Table({"value": np.asarray([1.0, 2.0])})
    # The pre-existing core formats can serialize or deliberately stringify a
    # set.  The versioned HDF5 schema rejects it because its exact semantic
    # type is outside the explicitly verified metadata subset.
    table.meta["selection"] = {"soft", "hard"}
    state.add_analysis_result(
        "set metadata",
        table,
    )
    service = IOUtilityService(state)

    listed = service.list_exportable_objects()

    assert listed["success"], listed
    entry = listed["data"]["objects"][0]
    assert entry["exportable"] is True
    assert entry["formats"] == CORE_FORMATS
    assert "type set" in entry["format_reasons"]["hdf5"]
    path = tmp_path / "set-metadata.hdf5"
    exported = service.export_object(
        "analysis_result",
        "set metadata",
        "hdf5",
        str(path),
        make_write_grant(path),
    )
    assert_private_failure(path, exported)
    assert "type set" in exported["message"]


def test_hdf5_requires_exact_extension_and_refuses_existing_destination(
    representative_state: StateManager, tmp_path: Path
) -> None:
    installed_h5py()
    service = IOUtilityService(representative_state)
    wrong_extension = tmp_path / "events.h5"

    wrong = service.export_object(
        "event_list",
        "events complete",
        "hdf5",
        str(wrong_extension),
        make_write_grant(wrong_extension),
    )

    assert_private_failure(wrong_extension, wrong)
    assert "exact '.hdf5'" in wrong["message"]

    existing = tmp_path / "existing.hdf5"
    existing.write_bytes(b"sentinel")
    existing_result = service.export_object(
        "event_list",
        "events complete",
        "hdf5",
        str(existing),
        make_write_grant(existing),
    )
    assert existing_result["success"] is False
    assert existing.read_bytes() == b"sentinel"


def test_hdf5_caps_run_before_copy_and_table_construction(
    representative_state: StateManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_h5py()
    monkeypatch.setattr(io_module, "MAX_EXPORT_ROWS", 1)
    table_built = False

    def forbidden_table(*_args: Any, **_kwargs: Any) -> Table:
        nonlocal table_built
        table_built = True
        raise AssertionError("table construction ran before the row cap")

    monkeypatch.setattr(io_module, "_table_for_object", forbidden_table)
    service = IOUtilityService(representative_state)
    path = tmp_path / "too-large.hdf5"

    result = service.export_object(
        "event_list",
        "events complete",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert_private_failure(path, result)
    assert table_built is False
    assert "operation cap is 1" in result["message"]


def test_hdf5_column_metadata_cap_runs_before_copy_and_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_h5py()
    state = StateManager()
    table = Table({"value": [1.0]})
    table["value"].meta["blob"] = "x" * 1_000_000
    state.add_analysis_result("oversized column metadata", table)
    monkeypatch.setattr(io_module, "MAX_EXPORT_ESTIMATED_BYTES", 128)

    def forbidden_copy(*_args: Any, **_kwargs: Any) -> Table:
        raise AssertionError("column metadata cap must run before table copy")

    monkeypatch.setattr(table, "copy", forbidden_copy)
    service = IOUtilityService(state)
    path = tmp_path / "oversized-column-metadata.hdf5"

    listed = service.list_exportable_objects()
    result = service.export_object(
        "analysis_result",
        "oversized column metadata",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    entry = listed["data"]["objects"][0]
    assert entry["exportable"] is False
    assert "operation size cap" in entry["reason"]
    assert_private_failure(path, result)
    assert "operation size cap" in result["message"]


@pytest.mark.parametrize(
    "corruption",
    [
        "corrupt_superblock",
        "truncated",
        "schema_mismatch",
        "missing_table",
        "softlink_table",
        "enum_field",
        "padded_compound_layout",
        "opposite_endian_member",
    ],
)
def test_corrupt_or_incomplete_hdf5_never_publishes(
    representative_state: StateManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    h5py_module = installed_h5py()
    original_write = io_module._write_hdf5_table

    def corrupt_after_write(stream: Any, *args: Any, **kwargs: Any) -> None:
        original_write(stream, *args, **kwargs)
        if corruption == "corrupt_superblock":
            stream.seek(0)
            stream.write(b"NOTHDF5!")
        elif corruption == "truncated":
            stream.seek(0, os.SEEK_END)
            stream.truncate(max(1, stream.tell() // 2))
        else:
            stream.seek(0)
            with h5py_module.File(stream, "r+") as handle:
                if corruption == "schema_mismatch":
                    handle[io_module.HDF5_GROUP_PATH].attrs["schema"] = "wrong.v1"
                elif corruption == "missing_table":
                    del handle[HDF5_TABLE_PATH]
                elif corruption == "softlink_table":
                    alternate_path = f"{io_module.HDF5_GROUP_PATH}/alternate_table"
                    handle.copy(HDF5_TABLE_PATH, alternate_path)
                    del handle[HDF5_TABLE_PATH]
                    handle[HDF5_TABLE_PATH] = h5py_module.SoftLink(f"/{alternate_path}")
                else:
                    original = handle[HDF5_TABLE_PATH][()]
                    old_dtype = original.dtype
                    if corruption == "enum_field":
                        enum_dtype = h5py_module.enum_dtype(
                            {"one": 1, "two": 2},
                            basetype=np.dtype("u2"),
                        )
                        replacement_dtype = np.dtype(
                            [
                                (
                                    name,
                                    enum_dtype
                                    if name == "channel"
                                    else old_dtype.fields[name][0],
                                )
                                for name in old_dtype.names
                            ]
                        )
                    elif corruption == "padded_compound_layout":
                        formats = [
                            old_dtype.fields[name][0] for name in old_dtype.names
                        ]
                        offsets: list[int] = []
                        cursor = 8
                        for field_dtype in formats:
                            offsets.append(cursor)
                            cursor += field_dtype.itemsize + 3
                        replacement_dtype = np.dtype(
                            {
                                "names": list(old_dtype.names),
                                "formats": formats,
                                "offsets": offsets,
                                "itemsize": cursor + 8,
                            }
                        )
                    else:
                        opposite = ">" if np.little_endian else "<"
                        replacement_dtype = np.dtype(
                            [
                                (
                                    name,
                                    (
                                        old_dtype.fields[name][0].newbyteorder(opposite)
                                        if old_dtype.fields[name][0].kind
                                        in {"i", "u", "f"}
                                        else old_dtype.fields[name][0]
                                    ),
                                )
                                for name in old_dtype.names
                            ]
                        )
                    replacement = np.empty(original.shape, dtype=replacement_dtype)
                    for name in old_dtype.names:
                        replacement[name] = original[name]
                    del handle[HDF5_TABLE_PATH]
                    handle.create_dataset(HDF5_TABLE_PATH, data=replacement)
                handle.flush()

    monkeypatch.setattr(io_module, "_write_hdf5_table", corrupt_after_write)
    service = IOUtilityService(representative_state)
    path = tmp_path / f"{corruption}.hdf5"

    result = service.export_object(
        "analysis_result",
        "analysis complete",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert_private_failure(path, result)


def test_reduced_hdf5_integer_precision_never_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h5py_module = installed_h5py()
    state = StateManager()
    state.add_analysis_result(
        "signed integer precision",
        Table({"value": np.asarray([1, 2], dtype=np.int16)}),
    )
    original_write = io_module._write_hdf5_table

    def reduce_precision_after_write(stream: Any, *args: Any, **kwargs: Any) -> None:
        original_write(stream, *args, **kwargs)
        stream.seek(0)
        with h5py_module.File(stream, "r+") as handle:
            original = handle[HDF5_TABLE_PATH][()]
            old_dtype = original.dtype
            del handle[HDF5_TABLE_PATH]
            dataspace = h5py_module.h5s.create_simple(original.shape)
            compound_type = h5py_module.h5t.create(
                h5py_module.h5t.COMPOUND,
                old_dtype.itemsize,
            )
            member_types: list[Any] = []
            dataset_id = None
            try:
                for name in old_dtype.names:
                    member_type = h5py_module.h5t.py_create(
                        old_dtype.fields[name][0],
                        logical=True,
                    )
                    if name == "value":
                        member_type.set_precision(8)
                    compound_type.insert(
                        name.encode("utf-8"),
                        old_dtype.fields[name][1],
                        member_type,
                    )
                    member_types.append(member_type)
                dataset_id = h5py_module.h5d.create(
                    handle[io_module.HDF5_GROUP_PATH].id,
                    b"table",
                    compound_type,
                    dataspace,
                )
                dataset_id.write(
                    h5py_module.h5s.ALL,
                    h5py_module.h5s.ALL,
                    original,
                )
            finally:
                if dataset_id is not None:
                    dataset_id.close()
                for member_type in member_types:
                    member_type.close()
                compound_type.close()
                dataspace.close()
            handle.flush()

    monkeypatch.setattr(io_module, "_write_hdf5_table", reduce_precision_after_write)
    service = IOUtilityService(state)
    path = tmp_path / "reduced-integer-precision.hdf5"

    result = service.export_object(
        "analysis_result",
        "signed integer precision",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert_private_failure(path, result)
    assert "noncanonical compound layout or member type" in result["message"]


@pytest.mark.parametrize(
    "corruption",
    ["oversized_manifest", "oversized_table_shape", "oversized_astropy_metadata"],
)
def test_oversized_hdf5_storage_is_rejected_before_publication(
    representative_state: StateManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    h5py_module = installed_h5py()
    original_write = io_module._write_hdf5_table

    def corrupt_after_write(stream: Any, *args: Any, **kwargs: Any) -> None:
        original_write(stream, *args, **kwargs)
        stream.seek(0)
        with h5py_module.File(stream, "r+") as handle:
            if corruption == "oversized_manifest":
                del handle[HDF5_MANIFEST_PATH]
                handle.create_dataset(
                    HDF5_MANIFEST_PATH,
                    shape=(),
                    dtype=f"S{io_module.HDF5_MANIFEST_MAX_BYTES + 1}",
                    data=np.bytes_(b"[]"),
                )
            elif corruption == "oversized_table_shape":
                table_dtype = handle[HDF5_TABLE_PATH].dtype
                del handle[HDF5_TABLE_PATH]
                handle.create_dataset(
                    HDF5_TABLE_PATH,
                    shape=(io_module.MAX_EXPORT_ROWS + 1,),
                    dtype=table_dtype,
                    chunks=(1,),
                )
            else:
                del handle[io_module.HDF5_ASTROPY_METADATA_PATH]
                handle.create_dataset(
                    io_module.HDF5_ASTROPY_METADATA_PATH,
                    shape=(io_module.MAX_EXPORT_ESTIMATED_BYTES + 1,),
                    dtype="S1",
                    chunks=(1_024,),
                )
            handle.flush()

    monkeypatch.setattr(io_module, "_write_hdf5_table", corrupt_after_write)
    service = IOUtilityService(representative_state)
    path = tmp_path / f"{corruption}.hdf5"

    result = service.export_object(
        "analysis_result",
        "analysis complete",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert_private_failure(path, result)


@pytest.mark.parametrize(
    "mismatch",
    [
        "row_count",
        "column_order",
        "dtype",
        "mask",
        "value",
        "unit",
        "column_metadata",
        "fill_value",
        "table_metadata",
        "gti",
        "provenance",
    ],
)
def test_each_semantic_reopen_mismatch_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    installed_h5py()
    state = StateManager()
    table = Table()
    table["value"] = MaskedColumn(
        [1.0, np.nan],
        mask=[True, False],
        fill_value=-9.5,
        unit=u.s,
        meta={"role": "lag"},
    )
    table["index"] = Column(np.asarray([1, 2], dtype=np.int16))
    table.meta = {
        "method": "cross-spectrum",
        "gti": np.asarray([[0.0, 2.0]]),
        "gti_status": "present",
        "provenance": {"operation": "timing"},
    }
    state.add_analysis_result("semantic", table)
    original_read = io_module._read_hdf5_table

    def mismatched_read(*args: Any, **kwargs: Any) -> tuple[Table, Any]:
        reopened, manifest = original_read(*args, **kwargs)
        if mismatch == "row_count":
            reopened = reopened[:-1]
        elif mismatch == "column_order":
            reopened = reopened[list(reversed(reopened.colnames))]
        elif mismatch == "dtype":
            replacement = MaskedColumn(
                np.asarray(reopened["value"].data.data, dtype=np.float32),
                mask=reopened["value"].mask,
                fill_value=reopened["value"].fill_value,
                unit=reopened["value"].unit,
                meta=reopened["value"].meta,
            )
            reopened.replace_column("value", replacement)
        elif mismatch == "mask":
            reopened["value"].mask[0] = False
        elif mismatch == "value":
            reopened["value"].data.data[1] = 99.0
        elif mismatch == "unit":
            reopened["value"].unit = u.ms
        elif mismatch == "column_metadata":
            reopened["value"].meta["role"] = "changed"
        elif mismatch == "fill_value":
            reopened["value"].fill_value = -1.0
        elif mismatch == "table_metadata":
            reopened.meta["method"] = "changed"
        elif mismatch == "gti":
            reopened.meta["gti"][0, 1] = 99.0
        elif mismatch == "provenance":
            reopened.meta["provenance"]["operation"] = "changed"
        return reopened, manifest

    monkeypatch.setattr(io_module, "_read_hdf5_table", mismatched_read)
    service = IOUtilityService(state)
    path = tmp_path / f"mismatch-{mismatch}.hdf5"

    result = service.export_object(
        "analysis_result",
        "semantic",
        "hdf5",
        str(path),
        make_write_grant(path),
    )

    assert_private_failure(path, result)
