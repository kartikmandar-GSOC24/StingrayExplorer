"""Tests for Mission-Specific I/O service and route contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from pydantic import ValidationError
from stingray import EventList
from stingray.mission_support import (
    get_rough_conversion_function,
    mission_specific_event_interpretation,
    read_mission_info,
)

import routes.mission_io_routes as mission_routes
import services.mission_io_service as mission_module
from routes.mission_io_routes import MissionIdentifyRequest, RoughPiConversionRequest
from services.mission_io_service import MissionIOService
from services.utility_helpers import FILE_GRANT_SECRET_ENV


def _grant(secret: str, path: Path, access: str = "read") -> str:
    expires = int(time.time()) + 60
    resolved = path.resolve()
    identity_path = resolved if access == "read" else resolved.parent
    selected_stat = identity_path.stat()
    identity = f"\0{selected_stat.st_dev}\0{selected_stat.st_ino}"
    prefix = f"{expires}.{selected_stat.st_dev}.{selected_stat.st_ino}"
    payload = f"{access}\0{expires}\0{resolved}{identity}".encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"{prefix}.{digest}"


def _write_identification_fits(
    path: Path,
    *,
    mission: str = "NICER",
    instrument: str = "XTI",
    mode: str = "PHOTON",
) -> None:
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = mission
    primary.header["INSTRUME"] = instrument
    primary.header["DATAMODE"] = mode
    primary.header["MJDREFI"] = 56658
    primary.header["MJDREFF"] = 0.000777592592592593
    events = fits.BinTableHDU.from_columns(
        [fits.Column(name="TIME", format="D", array=np.array([0.0, 1.0]))],
        name="EVENTS",
    )
    fits.HDUList([primary, events]).writeto(path)


def _write_xte_science_fits(path: Path) -> None:
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "XTE"
    primary.header["INSTRUME"] = "PCA"
    primary.header["DATAMODE"] = "E_125US_64M_0_1S"
    events = fits.BinTableHDU.from_columns(
        [
            fits.Column(
                name="PHA",
                format="B",
                array=np.array([0, 1, 2], dtype=np.uint8),
            )
        ],
        name="XTE_SE",
    )
    events.header["TELESCOP"] = "XTE"
    events.header["INSTRUME"] = "PCA"
    events.header["DATAMODE"] = "E_125US_64M_0_1S"
    events.header["TEVTB2"] = "(M[1]{1},C[0~4,5~6,7]{2})"
    fits.HDUList([primary, events]).writeto(path)


@pytest.fixture()
def service(state_manager) -> MissionIOService:
    return MissionIOService(state_manager)


def test_runtime_capability_list_uses_database_and_separates_support(service):
    result = service.list_capabilities()

    assert result["success"] is True
    raw_database = read_mission_info()
    assert result["data"]["raw_database_entry_count"] == len(raw_database)
    assert result["data"]["mission_count"] == len(
        {name.casefold() for name in raw_database}
    )
    rows = {row["mission"].casefold(): row for row in result["data"]["missions"]}
    assert rows["nicer"]["rough_pi_to_energy"]["status"] == "supported"
    assert rows["swift"]["rough_pi_to_energy"]["status"] == "unsupported"
    assert rows["xte"]["rough_pi_to_energy"]["status"] == "conditional"
    assert rows["xte"]["rough_pi_to_energy"]["epoch_mjd_domain"] == {
        "minimum_exclusive": 50_081.0,
        "maximum_inclusive": 55_931.0,
    }
    assert rows["xte"]["mapping"]["detector_column"] == "PCUID"
    assert rows["xte"]["modes"]["PCA"] == read_mission_info("XTE")["PCA"]["modes"]
    assert rows["xte"]["modes"]["HEXTE"] == read_mission_info("XTE")["HEXTE"]["modes"]
    assert set(rows["astrosat"]["modes"]["SXT"]) == {"BM", "CM", "FW", "PC", "PW"}
    assert rows["xte"]["specialized_interpretation"]["supported"] is True
    assert (
        sum(
            row["specialized_interpretation"]["supported"]
            for row in result["data"]["missions"]
        )
        == 1
    )
    assert "do not imply" in result["data"]["support_note"]
    assert result["data"]["provenance"]["operation"] == ("mission_io.list_capabilities")
    assert result["data"]["provenance"]["read_only"] is True
    json.dumps(result, allow_nan=False)


def test_selected_mission_mapping_honors_instrument_and_mode(service):
    result = service.get_mission_info("XTE", instrument="PCA", mode="E_125US_64M_0_1S")

    assert result["success"] is True
    assert result["data"]["mapping"]["event_hdu"] == "XTE_SE"
    assert result["data"]["mapping"]["energy_or_channel_column"] == "PHA"
    assert result["data"]["mapping"]["detector_column"] == "PCUID"
    assert result["data"]["available_modes"] == read_mission_info("XTE")["PCA"]["modes"]
    assert result["data"]["capabilities"]["rough_pi_to_energy"] == {
        "status": "conditional",
        "approximate": True,
        "dependencies": ["instrument=PCA", "epoch_mjd", "detector_id"],
        "epoch_mjd_domain": {
            "minimum_exclusive": 50_081.0,
            "maximum_inclusive": 55_931.0,
        },
    }
    assert result["data"]["provenance"]["operation"] == ("mission_io.get_mission_info")
    assert result["data"]["provenance"]["parameters"] == {
        "requested_mission": "XTE",
        "resolved_mission": "XTE",
        "instrument": "PCA",
        "mode": "E_125US_64M_0_1S",
    }
    json.dumps(result, allow_nan=False)

    unsupported_instrument = service.get_mission_info("XTE", instrument="HEXTE")
    assert unsupported_instrument["success"] is True
    assert (
        unsupported_instrument["data"]["capabilities"]["specialized_interpretation"][
            "supported"
        ]
        is False
    )
    assert unsupported_instrument["data"]["capabilities"]["rough_pi_to_energy"] == {
        "status": "unsupported",
        "approximate": False,
        "dependencies": [],
        "epoch_mjd_domain": None,
    }
    assert any(
        "limited to PCA" in warning for warning in unsupported_instrument["warnings"]
    )


@pytest.mark.parametrize(
    ("instrument", "mode", "message"),
    [
        ("NOT_AN_INSTRUMENT", None, "not defined for XTE"),
        ("PCA", "NOT_A_MODE", "not defined for XTE/PCA"),
        (None, "NOT_A_MODE", "requires an instrument selection for XTE"),
    ],
)
def test_selected_mission_mapping_rejects_unknown_runtime_choices(
    service, instrument, mode, message
):
    result = service.get_mission_info("XTE", instrument=instrument, mode=mode)

    assert result["success"] is False
    assert result["error"] is None
    assert message in result["message"]


def test_selected_mission_mapping_accepts_nested_runtime_mode(service):
    result = service.get_mission_info("ASTROSAT", instrument="SXT", mode="BM")

    assert result["success"] is True
    assert result["data"]["instrument"] == "SXT"
    assert result["data"]["mode"] == "BM"
    assert set(result["data"]["available_modes"]) == {"BM", "CM", "FW", "PC", "PW"}


def test_identify_loaded_event_list_reports_each_source(service, state_manager):
    event_list = EventList(
        time=[1.0, 2.0],
        pi=[10, 20],
        mission="nicer",
        instr="XTI",
        mjdref=56658.0,
    )
    event_list.mode = "PHOTON"
    state_manager.add_event_data("events", event_list)

    result = service.identify_source(event_list_name="events")

    assert result["success"] is True
    assert result["data"]["mission"] == {
        "value": "NICER",
        "raw_value": "nicer",
        "source": "EventList.mission",
        "source_type": "event_list_attribute",
        "inferred": False,
        "override": False,
        "database_supported": True,
    }
    assert result["data"]["instrument"]["source"] == "EventList.instr"
    assert result["data"]["mode"]["source"] == "EventList.mode"
    assert result["data"]["mapping"]["energy_or_channel_column"] == "PI"
    assert result["data"]["timing_metadata"]["mjdref"]["source"] == "EventList.mjdref"
    assert result["data"]["provenance"]["operation"] == "mission_io.identify_source"
    assert result["data"]["provenance"]["input_source"]["name"] == "events"
    json.dumps(result, allow_nan=False)


def test_identification_does_not_apply_generic_mapping_to_unknown_runtime_mode(
    service, state_manager
):
    source = EventList(
        time=[1.0, 2.0],
        pi=[10, 20],
        mission="XTE",
        instr="PCA",
    )
    source.mode = "NOT_A_MODE"
    state_manager.add_event_data("unknown-xte-mode", source)

    identified = service.identify_source(event_list_name="unknown-xte-mode")

    assert identified["success"] is True
    assert identified["data"]["mapping"] is None
    assert "not defined for XTE/PCA" in identified["data"]["mapping_validation_error"]
    assert any("no generic fallback" in item for item in identified["warnings"])

    converted = service.convert_pi_to_energy(
        event_list_name="unknown-xte-mode",
        epoch_mjd=55_930.0,
        detector_ids=[0],
    )
    assert converted["success"] is False
    assert "not defined for XTE/PCA" in converted["message"]


def test_missing_metadata_is_explicit_and_missing_only_overrides_are_labelled(
    service, state_manager
):
    state_manager.add_event_data("unknown", EventList(time=[1.0, 2.0], pi=[1, 2]))

    missing = service.identify_source(event_list_name="unknown")
    assert missing["success"] is True
    assert missing["data"]["mission"]["source_type"] == "missing"
    assert any("Mission metadata is missing" in item for item in missing["warnings"])
    assert missing["data"]["warnings"] == missing["warnings"]

    overridden = service.identify_source(
        event_list_name="unknown",
        mission_override="nicer",
        instrument_override="XTI",
        mode_override="PHOTON",
    )
    assert overridden["success"] is True
    for key in ("mission", "instrument", "mode"):
        assert overridden["data"][key]["source_type"] == "override"
        assert overridden["data"][key]["override"] is True
    assert overridden["data"]["mission"]["value"] == "NICER"

    state_manager.add_event_data(
        "known", EventList(time=[1.0], pi=[1], mission="NICER", instr="XTI")
    )
    conflict = service.identify_source(event_list_name="known", mission_override="XMM")
    assert conflict["success"] is False
    assert "only when" in conflict["message"]
    assert conflict["error"] is None


def test_unknown_mission_is_distinct_from_missing_or_operation_unsupported(
    service, state_manager
):
    info = service.get_mission_info("NOT-A-REAL-MISSION")
    assert info["success"] is False
    assert "not present" in info["message"]

    state_manager.add_event_data(
        "unknown-mission",
        EventList(
            time=np.array([0.0]),
            pi=np.array([1]),
            mission="NOT-A-REAL-MISSION",
            instr="UNKNOWN-INSTRUMENT",
        ),
    )
    identified = service.identify_source(event_list_name="unknown-mission")

    assert identified["success"] is True
    assert identified["data"]["mission"]["database_supported"] is False
    assert identified["data"]["mapping"] is None
    assert any("not present" in warning for warning in identified["warnings"])
    json.dumps(identified, allow_nan=False)


@pytest.mark.parametrize(
    ("mission", "pi_values"),
    [
        ("NUSTAR", [0, 10, 100]),
        ("XMM", [0, 10, 100]),
        ("NICER", [0, 10, 100]),
        ("IXPE", [0, 10, 100]),
        ("AXAF", [1, 10, 100]),
    ],
)
def test_simple_rough_conversions_match_public_stingray(service, mission, pi_values):
    result = service.convert_pi_to_energy(
        pi_values=pi_values,
        mission_override=mission,
    )

    assert result["success"] is True
    expected = get_rough_conversion_function(mission)(np.asarray(pi_values))
    actual = np.array([row["energy_kev"] for row in result["data"]["rows"]])
    np.testing.assert_allclose(actual, expected)
    assert result["data"]["approximate"] is True
    assert result["data"]["conversion_type"] == "rough_approximate"
    assert result["data"]["precise_calibration"]["location"] == "General I/O"
    assert "APPROXIMATE" in result["data"]["label"]
    assert "RMF" in result["warnings"][0]
    assert result["data"]["warnings"] == result["warnings"]


def test_xte_conversion_matches_public_function_and_requires_dependencies(service):
    pi_values = np.array([10, 11, 20])
    detectors = np.array([0, 3, 4])
    result = service.convert_pi_to_energy(
        pi_values=pi_values.tolist(),
        mission_override="XTE",
        instrument_override="PCA",
        epoch_mjd=55930.0,
        detector_ids=detectors.tolist(),
    )

    expected = get_rough_conversion_function("XTE", "PCA", 55930.0)(
        pi_values, detector_id=detectors
    )
    assert result["success"] is True
    np.testing.assert_allclose(
        [row["energy_kev"] for row in result["data"]["rows"]], expected
    )
    assert result["data"]["dependencies"]["epoch_mjd"]["source"] == "request.epoch_mjd"
    assert (
        result["data"]["dependencies"]["detector_id"]["source"]
        == "request.detector_ids"
    )

    missing_epoch = service.convert_pi_to_energy(
        pi_values=[10],
        mission_override="XTE",
        instrument_override="PCA",
        detector_ids=[0],
    )
    assert missing_epoch["success"] is False
    assert "epoch" in missing_epoch["message"].lower()

    missing_detector = service.convert_pi_to_energy(
        pi_values=[10],
        mission_override="XTE",
        instrument_override="PCA",
        epoch_mjd=55930,
    )
    assert missing_detector["success"] is False
    assert "detector" in missing_detector["message"].lower()


@pytest.mark.parametrize(
    ("epoch_mjd", "success"),
    [
        (50_081.0, False),
        (50_081.000001, True),
        (55_931.0, True),
        (55_931.000001, False),
    ],
)
def test_xte_conversion_enforces_installed_calibration_epoch_domain(
    service, epoch_mjd, success
):
    result = service.convert_pi_to_energy(
        pi_values=[10],
        mission_override="XTE",
        instrument_override="PCA",
        epoch_mjd=epoch_mjd,
        detector_ids=[0],
    )

    assert result["success"] is success
    if not success:
        assert "50081 < MJD <= 55931" in result["message"]
        assert result["error"] is None


def test_xte_non_pca_and_database_only_mission_are_actionably_unsupported(service):
    hexte = service.convert_pi_to_energy(
        pi_values=[10],
        mission_override="XTE",
        instrument_override="HEXTE",
        epoch_mjd=55930,
        detector_ids=[0],
    )
    assert hexte["success"] is False
    assert "PCA only" in hexte["message"]

    swift = service.convert_pi_to_energy(pi_values=[10], mission_override="SWIFT")
    assert swift["success"] is False
    assert "No public rough" in swift["message"]


def test_conversion_validates_channels_and_caps_before_work(service, monkeypatch):
    assert (
        service.convert_pi_to_energy(
            pi_values=[1, float("nan")], mission_override="NICER"
        )["success"]
        is False
    )
    fractional = service.convert_pi_to_energy(pi_values=[1.5], mission_override="NICER")
    assert fractional["success"] is False
    assert "integer channel" in fractional["message"]
    negative = service.convert_pi_to_energy(pi_values=[-1], mission_override="NICER")
    assert negative["success"] is False
    assert "non-negative" in negative["message"]

    monkeypatch.setattr(mission_module, "MAX_ARRAY_INPUT", 2)
    capped = service.convert_pi_to_energy(pi_values=[1, 2, 3], mission_override="NICER")
    assert capped["success"] is False
    assert "cap is 2" in capped["message"]


def test_non_finite_upstream_energies_become_null_with_warning(service, monkeypatch):
    monkeypatch.setattr(
        mission_module,
        "get_rough_conversion_function",
        lambda *args, **kwargs: lambda values: np.array([np.nan, np.inf, 3.5]),
    )

    result = service.convert_pi_to_energy(pi_values=[1, 2, 3], mission_override="NICER")

    assert result["success"] is True
    assert [row["energy_kev"] for row in result["data"]["rows"]] == [
        None,
        None,
        3.5,
    ]
    assert any(
        "represent" in warning and "null" in warning for warning in result["warnings"]
    )
    json.dumps(result, allow_nan=False)


def test_axaf_rejects_channel_zero_and_negative_approximate_energy(service):
    result = service.convert_pi_to_energy(pi_values=[0, 1], mission_override="AXAF")

    assert result["success"] is False
    assert result["error"] is None
    assert "must be at least 1" in result["message"]
    assert "non-negative" in result["message"]


def test_epoch_is_explicitly_unused_for_epoch_independent_conversion(service):
    result = service.convert_pi_to_energy(
        pi_values=[1, 2], mission_override="NICER", epoch_mjd=55_555.0
    )

    assert result["success"] is True
    dependency = result["data"]["dependencies"]["epoch_mjd"]
    assert dependency["used"] is False
    assert dependency["value"] is None
    assert dependency["requested_value"] == 55_555.0
    assert any("not used" in warning for warning in result["warnings"])
    assert result["data"]["provenance"]["parameters"]["epoch_mjd"] is None
    assert result["data"]["provenance"]["parameters"]["requested_epoch_mjd"] == 55_555.0


def test_loaded_event_snapshot_caps_and_channel_alignment(
    service, state_manager, monkeypatch
):
    oversized = EventList(
        time=np.array([0.0, 1.0, 2.0]),
        pi=np.array([1, 2, 3]),
        mission="NICER",
        instr="XTI",
    )
    state_manager.add_event_data("oversized", oversized)
    monkeypatch.setattr(mission_module, "MAX_ARRAY_INPUT", 2)

    capped = service.convert_pi_to_energy(event_list_name="oversized")

    assert capped["success"] is False
    assert "operation cap is 2" in capped["message"]

    monkeypatch.setattr(mission_module, "MAX_ARRAY_INPUT", 100_000)
    misaligned = EventList(
        time=np.array([0.0, 1.0]),
        pi=np.array([1, 2]),
        mission="NICER",
        instr="XTI",
    )
    misaligned.pi = np.array([1])
    state_manager.add_event_data("misaligned", misaligned)

    rejected = service.convert_pi_to_energy(
        event_list_name="misaligned", save_as="must-not-exist"
    )

    assert rejected["success"] is False
    assert "2 time value(s) but 1 PI/channel value(s)" in rejected["message"]
    assert state_manager.get_event_data("must-not-exist") is None


def test_identification_snapshot_is_bounded(service, state_manager, monkeypatch):
    state_manager.add_event_data(
        "large-identification",
        EventList(
            time=np.array([0.0, 1.0, 2.0]),
            pi=np.array([1, 2, 3]),
            mission="NICER",
        ),
    )
    monkeypatch.setattr(mission_module, "MAX_EXPORT_ROWS", 2)

    result = service.identify_source(event_list_name="large-identification")

    assert result["success"] is False
    assert "operation cap is 2" in result["message"]


def test_derived_event_is_atomic_immutable_and_carries_serializable_provenance(
    service, state_manager
):
    source = EventList(
        time=np.array([0.0, 1.0, 2.0]),
        pi=np.array([0, 100, 200]),
        gti=[[0.0, 2.0]],
        mission="NICER",
        instr="XTI",
        notes="original note",
    )
    state_manager.add_event_data("source", source)
    source_time = source.time.copy()
    source_pi = source.pi.copy()

    result = service.convert_pi_to_energy(event_list_name="source", save_as="derived")

    assert result["success"] is True
    assert result["data"]["saved_event_list"] == "derived"
    np.testing.assert_array_equal(source.time, source_time)
    np.testing.assert_array_equal(source.pi, source_pi)
    assert source.energy is None
    assert source.notes == "original note"

    derived = state_manager.get_event_data("derived")
    np.testing.assert_array_equal(derived.pi, source_pi)
    np.testing.assert_allclose(derived.energy, [0.0, 1.0, 2.0])
    assert not np.shares_memory(derived.pi, source.pi)
    assert derived.mission_io_conversion_type == "rough_approximate"
    attached = json.loads(derived.mission_io_provenance_json)
    assert attached["input_source"] == {"type": "loaded_event_list", "name": "source"}
    assert attached["conversion_type"] == "rough_approximate"
    assert "APPROXIMATE" in derived.notes
    json.dumps(result, allow_nan=False)

    duplicate = service.convert_pi_to_energy(
        event_list_name="source", save_as="derived"
    )
    assert duplicate["success"] is False
    assert "already exists" in duplicate["message"]
    assert state_manager.get_event_data("derived") is derived


def test_loaded_xte_derives_epoch_and_preserves_detector_ids(service, state_manager):
    source = EventList(
        time=np.array([442_845_936.0, 442_845_937.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        mjdref=49353.000696574074,
        detector_id=np.array([0, 3]),
    )
    state_manager.add_event_data("xte", source)

    result = service.convert_pi_to_energy(event_list_name="xte")

    assert result["success"] is True
    derived_epoch = 49353.000696574074 + 442_845_936.0 / 86400.0
    expected = get_rough_conversion_function("XTE", "PCA", derived_epoch)(
        source.pi, detector_id=source.detector_id
    )
    np.testing.assert_allclose(
        [row["energy_kev"] for row in result["data"]["rows"]], expected
    )
    assert "EventList.mjdref" in result["data"]["dependencies"]["epoch_mjd"]["source"]


def test_xte_requested_detector_ids_are_saved_and_reproducibly_provenanced(
    service, state_manager
):
    source = EventList(
        time=np.array([0.0, 1.0]),
        pi=np.array([10, 20]),
        mission="XTE",
        instr="PCA",
    )
    state_manager.add_event_data("xte-no-detectors", source)

    result = service.convert_pi_to_energy(
        event_list_name="xte-no-detectors",
        epoch_mjd=55_930.0,
        detector_ids=[0, 3],
        save_as="xte-with-detectors",
    )

    assert result["success"] is True
    derived = state_manager.get_event_data("xte-with-detectors")
    np.testing.assert_array_equal(derived.detector_id, [0, 3])
    assert source.detector_id is None
    parameters = json.loads(derived.mission_io_provenance_json)["parameters"]
    detector_provenance = parameters["detector_ids"]
    assert detector_provenance["source"] == "request.detector_ids"
    assert detector_provenance["count"] == 2
    assert detector_provenance["values"] == [0, 3]
    assert detector_provenance["preview_truncated"] is False
    expected_digest = hashlib.sha256(
        np.asarray([0, 3], dtype="<i8").tobytes(order="C")
    ).hexdigest()
    assert detector_provenance["sha256_int64_le"] == expected_digest


def test_loaded_xte_epoch_honors_header_timeunit_days(service, state_manager):
    source = EventList(
        time=np.array([0.0, 1.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        detector_id=np.array([0, 1]),
    )
    header = fits.Header()
    header["MJDREFI"] = 50_081
    header["MJDREFF"] = 0.0
    header["TSTART"] = 1.0
    header["TIMEUNIT"] = "d"
    source.header = header
    state_manager.add_event_data("xte-days", source)

    result = service.convert_pi_to_energy(event_list_name="xte-days")

    assert result["success"] is True
    assert result["data"]["dependencies"]["epoch_mjd"]["value"] == pytest.approx(
        50_082.0
    )
    expected = get_rough_conversion_function("XTE", "PCA", 50_082.0)(
        source.pi, detector_id=source.detector_id
    )
    np.testing.assert_allclose(
        [row["energy_kev"] for row in result["data"]["rows"]], expected
    )


def test_loaded_xte_epoch_and_timing_support_split_precision_cards(
    service, state_manager
):
    source = EventList(
        time=np.array([1.0, 2.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        detector_id=np.array([0, 1]),
    )
    header = fits.Header()
    header["MJDREFI"] = 50_000
    header["MJDREFF"] = 0.0
    header["TSTARTI"] = 81.0
    header["TSTARTF"] = 0.25
    header["TSTOPI"] = 82.0
    header["TSTOPF"] = 0.25
    header["TIMEZERI"] = 0.0
    header["TIMEZERF"] = 0.25
    header["TIMEUNIT"] = "d"
    source.header = header
    state_manager.add_event_data("xte-split-timing", source)

    result = service.convert_pi_to_energy(event_list_name="xte-split-timing")

    assert result["success"] is True
    assert result["data"]["dependencies"]["epoch_mjd"]["value"] == pytest.approx(
        50_081.5
    )
    expected = get_rough_conversion_function("XTE", "PCA", 50_081.5)(
        source.pi, detector_id=source.detector_id
    )
    np.testing.assert_allclose(
        [row["energy_kev"] for row in result["data"]["rows"]], expected
    )

    identified = service.identify_source(event_list_name="xte-split-timing")
    timing = identified["data"]["timing_metadata"]
    assert timing["tstart"]["value"] == pytest.approx(81.25)
    assert timing["tstart"]["decimal"] == "81.25"
    assert timing["tstop"]["value"] == pytest.approx(82.25)
    assert timing["timezero"]["value"] == pytest.approx(0.25)


def test_loaded_xte_epoch_prefers_event_time_reference_over_conflicting_mjd_obs(
    service, state_manager
):
    source = EventList(
        time=np.array([0.0, 1.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        detector_id=np.array([0, 1]),
    )
    header = fits.Header()
    header["MJD-OBS"] = 50_163.7
    header["MJDREFI"] = 50_000
    header["MJDREFF"] = 0.0
    header["TSTART"] = 163.8
    header["TIMEUNIT"] = "d"
    source.header = header
    state_manager.add_event_data("xte-conflicting-epoch", source)

    result = service.convert_pi_to_energy(event_list_name="xte-conflicting-epoch")

    assert result["success"] is True
    dependency = result["data"]["dependencies"]["epoch_mjd"]
    assert dependency["value"] == pytest.approx(50_163.8)
    assert any(
        "MJD-OBS" in warning and "conflicts" in warning
        for warning in result["warnings"]
    )
    expected = get_rough_conversion_function("XTE", "PCA", 50_163.8)(
        source.pi, detector_id=source.detector_id
    )
    np.testing.assert_allclose(
        [row["energy_kev"] for row in result["data"]["rows"]], expected
    )


def test_loaded_xte_epoch_prefers_explicit_event_start_over_first_event(
    service, state_manager
):
    source = EventList(
        time=np.array([172_800.0, 172_801.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        detector_id=np.array([0, 1]),
        mjdref=51_258.0,
    )
    source.t_start = 86_400.0
    state_manager.add_event_data("xte-explicit-start", source)

    result = service.convert_pi_to_energy(event_list_name="xte-explicit-start")

    assert result["success"] is True
    dependency = result["data"]["dependencies"]["epoch_mjd"]
    assert dependency["value"] == pytest.approx(51_259.0)
    assert "EventList.t_start" in dependency["source"]
    expected = get_rough_conversion_function("XTE", "PCA", 51_259.0)(
        source.pi, detector_id=source.detector_id
    )
    np.testing.assert_allclose(
        [row["energy_kev"] for row in result["data"]["rows"]], expected
    )


@pytest.mark.parametrize(
    ("timing_cards", "expected_epoch"),
    [
        ({"TSTART": 86_400.0, "TIMEZERO": 86_400.0}, 50_082.0),
        (
            {
                "TSTART": 86_400.0,
                "TIMEZERO": 0.0,
                "TIMEDEL": 86_400.0,
                "TIMEPIXR": 0.0,
            },
            50_081.5,
        ),
    ],
)
def test_loaded_xte_epoch_matches_stingray_timezero_and_timepixr_adjustment(
    service, state_manager, timing_cards, expected_epoch
):
    source = EventList(
        time=np.array([172_800.0, 172_801.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        detector_id=np.array([0, 1]),
    )
    header = fits.Header()
    header["MJDREFI"] = 50_080
    header["MJDREFF"] = 0.0
    header["TIMEUNIT"] = "s"
    for key, value in timing_cards.items():
        header[key] = value
    source.header = header
    state_manager.add_event_data(f"xte-adjusted-{expected_epoch}", source)

    result = service.convert_pi_to_energy(
        event_list_name=f"xte-adjusted-{expected_epoch}"
    )

    assert result["success"] is True
    assert result["data"]["dependencies"]["epoch_mjd"]["value"] == pytest.approx(
        expected_epoch
    )
    expected = get_rough_conversion_function("XTE", "PCA", expected_epoch)(
        source.pi, detector_id=source.detector_id
    )
    np.testing.assert_allclose(
        [row["energy_kev"] for row in result["data"]["rows"]], expected
    )


@pytest.mark.parametrize(
    "invalid_timing",
    [
        {"TIMEDEL": -2.0, "TIMEPIXR": 0.5},
        {"TIMEDEL": 2.0, "TIMEPIXR": 2.0},
        {"TIMEPIXR": 0.0},
    ],
)
def test_loaded_xte_invalid_bin_timing_requires_explicit_epoch(
    service, state_manager, invalid_timing
):
    source = EventList(
        time=np.array([0.0, 1.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        detector_id=np.array([0, 1]),
    )
    header = fits.Header()
    header["MJDREFI"] = 50_081
    header["MJDREFF"] = 0.0
    header["TSTART"] = 1.0
    header["TIMEUNIT"] = "d"
    for key, value in invalid_timing.items():
        header[key] = value
    source.header = header
    name = f"xte-invalid-{len(state_manager.list_event_names())}"
    state_manager.add_event_data(name, source)

    result = service.convert_pi_to_energy(event_list_name=name)

    assert result["success"] is False
    assert "requires the observation epoch" in result["message"]
    assert result["error"] is None
    if invalid_timing.get("TIMEDEL", 0) < 0:
        assert any("TIMEDEL" in warning for warning in result["warnings"])
    if invalid_timing.get("TIMEPIXR", 0.5) > 1:
        assert any("TIMEPIXR" in warning for warning in result["warnings"])


def test_identification_omits_nonfinite_timing_cards_with_warnings(
    service, state_manager
):
    source = EventList(time=[1.0, 2.0], pi=[1, 2], mission="NICER", instr="XTI")
    header = fits.Header()
    header["MJD-OBS"] = "NaN"
    header["TSTART"] = "Infinity"
    header["TSTOP"] = True
    header["TIMEZERO"] = "NaN"
    header["TIMEDEL"] = 1.0
    header["TIMEPIXR"] = 0.5
    source.header = header
    state_manager.add_event_data("nonfinite-timing", source)

    result = service.identify_source(event_list_name="nonfinite-timing")

    assert result["success"] is True
    timing = result["data"]["timing_metadata"]
    assert "mjd_observation" not in timing
    assert "tstart" not in timing
    assert "tstop" not in timing
    assert "timezero" not in timing
    assert timing["timedel"]["value"] == 1.0
    assert timing["timepixr"]["value"] == 0.5
    assert any("MJD-OBS" in warning for warning in result["warnings"])
    assert any("TSTART" in warning for warning in result["warnings"])
    assert any("TSTOP" in warning for warning in result["warnings"])
    assert any("TIMEZERO" in warning for warning in result["warnings"])
    json.dumps(result, allow_nan=False)


def test_loaded_xte_rejects_malformed_mjdreff_for_epoch_derivation(
    service, state_manager
):
    source = EventList(
        time=np.array([0.0, 1.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        detector_id=np.array([0, 1]),
    )
    header = fits.Header()
    header["MJDREFI"] = 50_000
    header["MJDREFF"] = "not-a-number"
    header["TSTART"] = 0.0
    header["TIMEUNIT"] = "s"
    source.header = header
    state_manager.add_event_data("xte-bad-mjdreff", source)

    result = service.convert_pi_to_energy(event_list_name="xte-bad-mjdreff")

    assert result["success"] is False
    assert "requires the observation epoch" in result["message"]
    assert any("not substituted with zero" in warning for warning in result["warnings"])


def test_loaded_xte_rejects_incomplete_split_mjdref(service, state_manager):
    source = EventList(
        time=np.array([0.0, 1.0]),
        pi=np.array([10, 11]),
        mission="XTE",
        instr="PCA",
        detector_id=np.array([0, 1]),
    )
    header = fits.Header()
    header["MJDREFI"] = 50_163
    header["TSTART"] = 0.0
    header["TIMEUNIT"] = "d"
    source.header = header
    state_manager.add_event_data("xte-incomplete-mjdref", source)

    result = service.convert_pi_to_energy(event_list_name="xte-incomplete-mjdref")

    assert result["success"] is False
    assert "requires the observation epoch" in result["message"]
    assert any("both MJDREFI and MJDREFF" in item for item in result["warnings"])


def test_identification_omits_overflowed_split_mjdref(service, state_manager):
    source = EventList(
        time=np.array([0.0, 1.0]),
        pi=np.array([1, 2]),
        mission="NICER",
        instr="XTI",
    )
    header = fits.Header()
    header["MJDREFI"] = 1e308
    header["MJDREFF"] = 1e308
    source.header = header
    state_manager.add_event_data("overflow-mjdref", source)

    result = service.identify_source(event_list_name="overflow-mjdref")

    assert result["success"] is True
    assert "mjdref" not in result["data"]["timing_metadata"]
    assert any(
        "not representable as a finite value" in item for item in result["warnings"]
    )
    json.dumps(result, allow_nan=False)


def test_fits_identification_requires_exact_read_grant(service, tmp_path, monkeypatch):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "selected.fits"
    adjacent = tmp_path / "adjacent.fits"
    _write_identification_fits(selected)
    _write_identification_fits(adjacent, mission="XMM", instrument="EPN")
    grant = _grant(secret, selected)

    result = service.identify_source(file_path=str(selected), file_grant=grant)
    assert result["success"] is True
    assert result["data"]["mission"]["value"] == "NICER"
    assert result["data"]["mission"]["source_type"] == "fits_header"
    assert result["data"]["source"]["path"] == str(selected.resolve())
    assert result["data"]["timing_metadata"]["mjdref"]["value"] == pytest.approx(
        56658.00077759259
    )
    mjdref = result["data"]["timing_metadata"]["mjdref"]
    assert mjdref["decimal"] == "56658.000777592592592593"
    assert mjdref["components"]["integer"]["value"] == "56658"
    assert mjdref["components"]["fraction"]["value"] == "0.000777592592592593"

    substituted = service.identify_source(file_path=str(adjacent), file_grant=grant)
    assert substituted["success"] is False
    assert "does not match" in substituted["message"]

    no_grant = service.identify_source(file_path=str(selected))
    assert no_grant["success"] is False
    assert "grant" in no_grant["message"]


def test_fits_identification_preserves_raw_mjdref_card_precision(
    service, tmp_path, monkeypatch
):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "exact-mjdref.fits"
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "NICER"
    primary.header["INSTRUME"] = "XTI"
    primary.header.append(
        fits.Card.fromstring("MJDREF  = 58000.123456789012345".ljust(80))
    )
    events = fits.BinTableHDU.from_columns(
        [fits.Column(name="TIME", format="D", array=np.array([0.0, 1.0]))],
        name="EVENTS",
    )
    fits.HDUList([primary, events]).writeto(selected)

    result = service.identify_source(
        file_path=str(selected), file_grant=_grant(secret, selected)
    )

    assert result["success"] is True
    mjdref = result["data"]["timing_metadata"]["mjdref"]
    assert mjdref["decimal"] == "58000.123456789012345"
    assert mjdref["value"] == pytest.approx(58_000.12345678901)


def test_malformed_fits_returns_clean_identification_and_interpretation_failures(
    service, tmp_path, monkeypatch
):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "malformed.fits"
    selected.write_bytes(b"this is not a FITS file")
    grant = _grant(secret, selected)

    identified = service.identify_source(file_path=str(selected), file_grant=grant)
    interpreted = service.interpret_selected_fits(
        file_path=str(selected), file_grant=grant
    )

    assert identified["success"] is False
    assert interpreted["success"] is False
    assert "Could not inspect" in identified["message"]
    assert "Could not inspect" in interpreted["message"]
    assert identified["error"] is None
    assert interpreted["error"] is None
    json.dumps(identified, allow_nan=False)
    json.dumps(interpreted, allow_nan=False)


def test_malformed_mjdreff_is_not_substituted_with_zero(service, tmp_path, monkeypatch):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "malformed-mjdreff.fits"
    _write_identification_fits(selected)
    with fits.open(selected, mode="update") as hdulist:
        hdulist[0].header["MJDREFF"] = "not-a-number"
        hdulist.flush()

    result = service.identify_source(
        file_path=str(selected), file_grant=_grant(secret, selected)
    )

    assert result["success"] is True
    assert "mjdref" not in result["data"]["timing_metadata"]
    assert any(
        "MJDREFF" in warning and "not substituted with zero" in warning
        for warning in result["warnings"]
    )


def test_mission_fits_hdu_count_is_capped_before_header_iteration(
    service, tmp_path, monkeypatch
):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "too-many-hdus.fits"
    hdus = [fits.PrimaryHDU()]
    hdus.extend(fits.ImageHDU() for _ in range(mission_module.MAX_FITS_HDUS))
    fits.HDUList(hdus).writeto(selected)
    grant = _grant(secret, selected)

    identified = service.identify_source(file_path=str(selected), file_grant=grant)
    interpreted = service.interpret_selected_fits(
        file_path=str(selected), file_grant=grant
    )

    assert identified["success"] is False
    assert interpreted["success"] is False
    assert "513 HDUs" in identified["message"]
    assert "cap is 512" in identified["message"]
    assert "513 HDUs" in interpreted["message"]
    assert "cap is 512" in interpreted["message"]


def test_mission_header_precedes_telescope_header(service, tmp_path, monkeypatch):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "precedence.fits"
    _write_identification_fits(selected, mission="NICER", instrument="XTI")
    with fits.open(selected, mode="update") as hdulist:
        hdulist[0].header["MISSION"] = "XMM"
        hdulist.flush()

    result = service.identify_source(
        file_path=str(selected), file_grant=_grant(secret, selected)
    )

    assert result["success"] is True
    assert result["data"]["mission"]["value"] == "XMM"
    assert result["data"]["mission"]["source"].endswith(".MISSION")


def test_xte_interpretation_matches_public_api_and_does_not_change_file(
    service, tmp_path, monkeypatch
):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "xte-science.fits"
    _write_xte_science_fits(selected)
    grant = _grant(secret, selected)

    with fits.open(selected) as hdulist:
        direct_hdu = hdulist["XTE_SE"].copy()
    expected_hdu = mission_specific_event_interpretation("XTE")(direct_hdu)
    expected = np.asarray(expected_hdu.data["PHA"]).copy()

    result = service.interpret_selected_fits(file_path=str(selected), file_grant=grant)

    assert result["success"] is True
    actual = np.array([row["interpreted_pha"] for row in result["data"]["rows"]])
    np.testing.assert_array_equal(actual, expected)
    assert result["data"]["read_only"] is True
    assert result["data"]["source_modified"] is False
    assert result["data"]["changed_count"] == 3
    assert "does not calibrate" in result["warnings"][-1]
    with fits.open(selected) as unchanged:
        np.testing.assert_array_equal(unchanged["XTE_SE"].data["PHA"], [0, 1, 2])
    json.dumps(result, allow_nan=False)


def test_xte_interpretation_rejects_missing_hdu_pha_and_oversized_table(
    service, tmp_path, monkeypatch
):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)

    missing_hdu = tmp_path / "xte-missing-hdu.fits"
    _write_identification_fits(missing_hdu, mission="XTE", instrument="PCA")
    no_hdu = service.interpret_selected_fits(
        file_path=str(missing_hdu),
        file_grant=_grant(secret, missing_hdu),
    )
    assert no_hdu["success"] is False
    assert "no XTE_SE extension" in no_hdu["message"]

    missing_pha = tmp_path / "xte-missing-pha.fits"
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "XTE"
    primary.header["INSTRUME"] = "PCA"
    events = fits.BinTableHDU.from_columns(
        [fits.Column(name="TIME", format="D", array=np.array([0.0, 1.0]))],
        name="XTE_SE",
    )
    fits.HDUList([primary, events]).writeto(missing_pha)
    no_pha = service.interpret_selected_fits(
        file_path=str(missing_pha),
        file_grant=_grant(secret, missing_pha),
    )
    assert no_pha["success"] is False
    assert "no PHA column" in no_pha["message"]

    oversized = tmp_path / "xte-oversized.fits"
    _write_xte_science_fits(oversized)
    monkeypatch.setattr(mission_module, "MAX_ARRAY_INPUT", 2)
    too_many_rows = service.interpret_selected_fits(
        file_path=str(oversized),
        file_grant=_grant(secret, oversized),
    )
    assert too_many_rows["success"] is False
    assert "contains 3 rows" in too_many_rows["message"]
    assert "cap is 2" in too_many_rows["message"]


def test_specialized_interpretation_is_xte_only(service, tmp_path, monkeypatch):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / "nicer.fits"
    _write_identification_fits(selected)

    result = service.interpret_selected_fits(
        file_path=str(selected), file_grant=_grant(secret, selected)
    )

    assert result["success"] is False
    assert "Only XTE" in result["message"]


@pytest.mark.parametrize("instrument", [None, "HEXTE"])
def test_xte_specialized_interpretation_requires_pca(
    service, tmp_path, monkeypatch, instrument
):
    secret = "mission-io-test-secret"
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, secret)
    selected = tmp_path / f"xte-{instrument or 'missing'}.fits"
    _write_xte_science_fits(selected)
    with fits.open(selected, mode="update") as hdulist:
        for hdu in hdulist:
            if instrument is None:
                if "INSTRUME" in hdu.header:
                    del hdu.header["INSTRUME"]
            else:
                hdu.header["INSTRUME"] = instrument
        hdulist.flush()

    result = service.interpret_selected_fits(
        file_path=str(selected), file_grant=_grant(secret, selected)
    )

    assert result["success"] is False
    assert "only PCA science-event FITS is supported" in result["message"]


def test_request_models_enforce_exact_sources_and_file_grants():
    with pytest.raises(ValidationError, match="exactly one"):
        MissionIdentifyRequest()
    with pytest.raises(ValidationError, match="file_grant"):
        MissionIdentifyRequest(file_path="/selected/file.fits")
    with pytest.raises(ValidationError, match="exactly one"):
        RoughPiConversionRequest(pi_values=[1], event_list_name="events")
    with pytest.raises(ValidationError, match="save_as"):
        RoughPiConversionRequest(pi_values=[1], save_as="derived")
    with pytest.raises(ValidationError, match="finite number"):
        RoughPiConversionRequest(pi_values=[float("nan")], mission_override="NICER")
    with pytest.raises(ValidationError, match="finite number"):
        RoughPiConversionRequest(
            pi_values=[1], mission_override="XTE", epoch_mjd=float("inf")
        )


def test_request_models_accept_existing_source_names_from_ingestion():
    long_source_name = "loaded-" + "x" * 300

    identification = MissionIdentifyRequest(event_list_name=long_source_name)
    conversion = RoughPiConversionRequest(
        event_list_name=long_source_name,
        mission_override="NICER",
    )

    assert identification.event_list_name == long_source_name
    assert conversion.event_list_name == long_source_name


@pytest.mark.asyncio
async def test_conversion_route_offloads_blocking_service_call(monkeypatch):
    calls = []

    class StubService:
        def convert_pi_to_energy(self, **kwargs):
            calls.append(kwargs)
            return {"success": True}

    async def fake_to_thread(function, *args, **kwargs):
        calls.append("offloaded")
        return function(*args, **kwargs)

    monkeypatch.setattr(mission_routes.asyncio, "to_thread", fake_to_thread)
    request = RoughPiConversionRequest(pi_values=[1, 2], mission_override="NICER")

    result = await mission_routes.convert_pi_to_energy(request, StubService())

    assert result == {"success": True}
    assert calls[0] == "offloaded"
    assert calls[1]["pi_values"] == [1.0, 2.0]
    assert calls[1]["mission_override"] == "NICER"
