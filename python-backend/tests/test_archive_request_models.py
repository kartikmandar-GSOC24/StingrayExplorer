"""Strict bounded model tests for archive search requests."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError
from routes.archive_routes import (
    ArchiveMission,
    SearchByCoordinatesRequest,
    SearchByNameRequest,
    SearchByObsidRequest,
    _iso_dates_to_mjd_range,
)
from services.archive_service import SUPPORTED_CATALOGS


def test_strict_mission_literal_matches_supported_catalogs():
    assert set(get_args(ArchiveMission)) == set(SUPPORTED_CATALOGS)


def test_valid_archive_search_requests_keep_supported_behavior():
    by_name = SearchByNameRequest.model_validate(
        {
            "source_name": "Cyg X-1",
            "mission": "NICER",
            "radius": 0.5,
            "max_results": 100,
            "min_exposure": 0.0,
            "start_date": "2024-02-29",
            "end_date": "2024-03-01",
        }
    )
    by_coordinates = SearchByCoordinatesRequest.model_validate(
        {
            "ra": 0.0,
            "dec": -90.0,
            "mission": "NuSTAR",
            "radius": 180.0,
            "max_results": 1_000,
            "min_exposure": 1_000_000_000.0,
        }
    )
    by_obsid = SearchByObsidRequest.model_validate(
        {"obsid": "4010080142-A", "mission": "XMM-Newton"}
    )

    assert by_name.source_name == "Cyg X-1"
    assert by_coordinates.ra == 0.0
    assert by_coordinates.dec == -90.0
    assert by_obsid.obsid == "4010080142-A"
    assert _iso_dates_to_mjd_range("2024-02-29", "2024-03-01") is not None


@pytest.mark.parametrize(
    "model,payload",
    [
        (
            SearchByNameRequest,
            {"source_name": "Crab", "mission": "NICER", "extra": True},
        ),
        (SearchByNameRequest, {"source_name": " ", "mission": "NICER"}),
        (
            SearchByNameRequest,
            {"source_name": "Crab\nsecret", "mission": "NICER"},
        ),
        (
            SearchByNameRequest,
            {"source_name": "x" * 257, "mission": "NICER"},
        ),
        (SearchByNameRequest, {"source_name": "Crab", "mission": "Unknown"}),
        (
            SearchByNameRequest,
            {"source_name": "Crab", "mission": "NICER", "radius": 0.0},
        ),
        (
            SearchByNameRequest,
            {"source_name": "Crab", "mission": "NICER", "radius": float("inf")},
        ),
        (
            SearchByNameRequest,
            {"source_name": "Crab", "mission": "NICER", "max_results": 0},
        ),
        (
            SearchByNameRequest,
            {"source_name": "Crab", "mission": "NICER", "max_results": 1_001},
        ),
        (
            SearchByNameRequest,
            {"source_name": "Crab", "mission": "NICER", "max_results": "100"},
        ),
        (
            SearchByNameRequest,
            {"source_name": "Crab", "mission": "NICER", "min_exposure": -1.0},
        ),
        (
            SearchByNameRequest,
            {
                "source_name": "Crab",
                "mission": "NICER",
                "start_date": "2024-02-30",
            },
        ),
        (
            SearchByNameRequest,
            {
                "source_name": "Crab",
                "mission": "NICER",
                "end_date": "2024-1-01",
            },
        ),
        (
            SearchByNameRequest,
            {
                "source_name": "Crab",
                "mission": "NICER",
                "start_date": "2024-03-01",
                "end_date": "2024-02-29",
            },
        ),
        (
            SearchByCoordinatesRequest,
            {"ra": -0.1, "dec": 0.0, "mission": "NICER"},
        ),
        (
            SearchByCoordinatesRequest,
            {"ra": 0.0, "dec": 90.1, "mission": "NICER"},
        ),
        (
            SearchByCoordinatesRequest,
            {"ra": float("nan"), "dec": 0.0, "mission": "NICER"},
        ),
        (
            SearchByCoordinatesRequest,
            {"ra": 0.0, "dec": 0.0, "mission": "NICER", "radius": "0.5"},
        ),
        (SearchByObsidRequest, {"obsid": "../escape", "mission": "NICER"}),
        (SearchByObsidRequest, {"obsid": "x" * 129, "mission": "NICER"}),
        (
            SearchByObsidRequest,
            {"obsid": "4010080142", "mission": "NICER", "extra": True},
        ),
    ],
)
def test_archive_search_models_reject_unbounded_or_coercive_values(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "start_date,end_date",
    [
        ("not-a-date", None),
        (None, "2024-02-30"),
    ],
)
def test_date_conversion_fails_instead_of_silently_widening_range(
    start_date,
    end_date,
):
    with pytest.raises(ValueError):
        _iso_dates_to_mjd_range(start_date, end_date)
