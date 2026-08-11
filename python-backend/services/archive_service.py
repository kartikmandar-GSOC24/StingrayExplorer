"""
Archive service for HEASARC catalog queries and data downloads.

Provides functionality to search NASA's HEASARC archive for X-ray observations
and download data with progress tracking.
"""

import asyncio
import hashlib
import inspect
import math
import os
import queue
import re
import threading
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote_to_bytes, urlsplit

import requests
from astropy import units as u
from astropy.coordinates import SkyCoord

from .base_service import BaseService
from .remote_source import (
    HEASARC_ARCHIVE_POLICY,
    RemoteSourceCancelled,
    RemoteSourceClient,
    RemoteSourceError,
    RemoteSourceHTTPError,
    RemoteSourcePolicyError,
    RemoteSourceTimeout,
    RemoteTimeouts,
)
from .secure_publication import SecurePublication, open_secure_publication

MAX_ARCHIVE_DOWNLOAD_BYTES = 20 * 1024**3
MAX_CONCURRENT_ARCHIVE_DOWNLOADS = 2
MAX_AGGREGATE_ARCHIVE_DOWNLOAD_BYTES = (
    MAX_CONCURRENT_ARCHIVE_DOWNLOADS * MAX_ARCHIVE_DOWNLOAD_BYTES
)
ARCHIVE_DOWNLOAD_CHUNK_BYTES = 256 * 1024
ARCHIVE_DOWNLOAD_TIMEOUTS = RemoteTimeouts(
    connect=10.0,
    read=60.0,
    write=10.0,
    pool=5.0,
    total=3600.0,
)
ARCHIVE_STAGING_WARNING = (
    "Download completed, but private staging cleanup could not be confirmed."
)
ARCHIVE_VERIFICATION_CANCEL_POLL_SECONDS = 0.05
ARCHIVE_WRITER_QUEUE_CHUNKS = 2
MAX_ARCHIVE_DIRECTORY_HTML_BYTES = 2 * 1024**2
MAX_ARCHIVE_DIRECTORY_ENTRIES = 1_000
MAX_ARCHIVE_CRAWL_ENTRIES = 5_000
MAX_ARCHIVE_CRAWL_DIRECTORIES = 64
MAX_ARCHIVE_CRAWL_DEPTH = 3
MAX_ARCHIVE_ENTRY_NAME_CHARS = 255
MAX_ARCHIVE_ENTRY_HREF_CHARS = 1_024
ARCHIVE_CRAWL_TOTAL_SECONDS = 120.0
ARCHIVE_CRAWL_HOP_SECONDS = 30.0
MAX_ARCHIVE_SEARCH_REMOTE_ROWS = 5_000
MAX_ARCHIVE_OBSID_REMOTE_ROWS = 10
ARCHIVE_SEARCH_CONNECT_TIMEOUT_SECONDS = 10.0
ARCHIVE_SEARCH_READ_TIMEOUT_SECONDS = 30.0
ARCHIVE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
ARCHIVE_PROPOSAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
CancellationCheck = Callable[[], bool | None | Awaitable[bool | None]]


class ArchiveSearchSession(requests.Session):
    """Apply finite connect/read timeouts to astroquery's TAP requests."""

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (
                ARCHIVE_SEARCH_CONNECT_TIMEOUT_SECONDS,
                ARCHIVE_SEARCH_READ_TIMEOUT_SECONDS,
            )
        return super().request(method, url, **kwargs)


@contextmanager
def _open_heasarc_client() -> Generator[Any, None, None]:
    """Create one isolated HEASARC client with a bounded HTTP session."""
    from astroquery.heasarc.core import HeasarcClass

    client = HeasarcClass()
    session = ArchiveSearchSession()
    client._set_session(session)
    try:
        yield client
    finally:
        session.close()


class ArchiveDownloadBusyError(RuntimeError):
    """The exact destination is already owned by an active download."""


class ArchiveDownloadCapacityError(RuntimeError):
    """The process-wide bounded archive-download capacity is occupied."""


class ArchiveArtifactWriter:
    """Own the staging writer and its flush/fsync lifecycle off the event loop."""

    _SENTINEL = object()

    def __init__(self, publication: SecurePublication) -> None:
        self._publication = publication
        self._queue: queue.Queue[bytes | object] = queue.Queue(
            maxsize=ARCHIVE_WRITER_QUEUE_CHUNKS
        )
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._exception: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="archive-artifact-writer",
            daemon=False,
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            with self._publication.open_writer("wb", encoding=None) as writer:
                while True:
                    if self._cancel.is_set():
                        raise RemoteSourceCancelled("Archive write was cancelled")
                    try:
                        item = self._queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if item is self._SENTINEL:
                        break
                    writer.write(item)
                    if self._cancel.is_set():
                        raise RemoteSourceCancelled("Archive write was cancelled")
        except BaseException as error:
            self._exception = error
        finally:
            self._done.set()

    def _raise_worker_failure(self) -> None:
        error = self._exception
        if error is None:
            return
        if isinstance(error, Exception):
            raise error
        raise RuntimeError("The archive writer terminated unexpectedly")

    async def _put(
        self,
        item: bytes | object,
        cancellation_check: CancellationCheck | None,
    ) -> None:
        while True:
            if self._done.is_set():
                self._thread.join()
                self._raise_worker_failure()
                raise RuntimeError("The archive writer stopped unexpectedly")
            await ArchiveService._raise_if_download_cancelled(cancellation_check)
            try:
                self._queue.put_nowait(item)
                return
            except queue.Full:
                await asyncio.sleep(0.01)

    async def write(
        self,
        chunk: bytes,
        cancellation_check: CancellationCheck | None,
    ) -> None:
        await self._put(chunk, cancellation_check)

    async def finish(
        self,
        cancellation_check: CancellationCheck | None,
    ) -> None:
        await self._put(self._SENTINEL, cancellation_check)
        while not self._done.is_set():
            await ArchiveService._raise_if_download_cancelled(cancellation_check)
            await asyncio.sleep(0.01)
        self._thread.join()
        self._raise_worker_failure()

    async def abort_and_join(self) -> None:
        """Signal cancellation and defer teardown until writer ownership ends."""
        self._cancel.set()
        while not self._done.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                continue
        self._thread.join()


class ArchiveDownloadCoordinator:
    """Fail-fast process-wide claims for bounded archive download resources."""

    def __init__(self, maximum_active: int) -> None:
        self._maximum_active = maximum_active
        self._lock = threading.Lock()
        self._active_destinations: set[bytes] = set()

    @contextmanager
    def claim(self, destination_key: bytes) -> Generator[None, None, None]:
        with self._lock:
            if destination_key in self._active_destinations:
                raise ArchiveDownloadBusyError
            if len(self._active_destinations) >= self._maximum_active:
                raise ArchiveDownloadCapacityError
            self._active_destinations.add(destination_key)
        try:
            yield
        finally:
            with self._lock:
                self._active_destinations.discard(destination_key)


ARCHIVE_DOWNLOAD_COORDINATOR = ArchiveDownloadCoordinator(
    MAX_CONCURRENT_ARCHIVE_DOWNLOADS
)


@dataclass
class ArchiveCrawlBudget:
    """Shared total-time, directory, and entry budget for one crawl."""

    deadline: float
    directories: int = 0
    entries: int = 0

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RemoteSourceTimeout("The archive directory crawl timed out")
        return remaining

    def begin_directory(self) -> None:
        self.remaining()
        self.directories += 1
        if self.directories > MAX_ARCHIVE_CRAWL_DIRECTORIES:
            raise RemoteSourceError("The archive directory crawl is too large")

    def add_entries(self, count: int) -> None:
        self.remaining()
        if count > MAX_ARCHIVE_DIRECTORY_ENTRIES:
            raise RemoteSourceError("An archive directory contains too many entries")
        self.entries += count
        if self.entries > MAX_ARCHIVE_CRAWL_ENTRIES:
            raise RemoteSourceError(
                "The archive directory crawl contains too many entries"
            )


# Supported HEASARC catalogs for X-ray missions
SUPPORTED_CATALOGS = {
    "NICER": {
        "catalog": "nicermastr",
        "display_name": "NICER",
        "description": "Neutron star Interior Composition Explorer",
    },
    "NuSTAR": {
        "catalog": "numaster",
        "display_name": "NuSTAR",
        "description": "Nuclear Spectroscopic Telescope Array",
    },
    "XMM-Newton": {
        "catalog": "xmmmaster",
        "display_name": "XMM-Newton",
        "description": "X-ray Multi-Mirror Mission",
    },
    "Chandra": {
        "catalog": "chanmaster",
        "display_name": "Chandra",
        "description": "Chandra X-ray Observatory",
    },
    "Swift": {
        "catalog": "swiftmastr",
        "display_name": "Swift",
        "description": "Neil Gehrels Swift Observatory",
    },
    "RXTE": {
        "catalog": "xtemaster",
        "display_name": "RXTE",
        "description": "Rossi X-ray Timing Explorer",
    },
    "IXPE": {
        "catalog": "ixmaster",
        "display_name": "IXPE",
        "description": "Imaging X-ray Polarimetry Explorer",
    },
    "Suzaku": {
        "catalog": "suzamaster",
        "display_name": "Suzaku",
        "description": "Suzaku X-ray Satellite",
    },
    "ASCA": {
        "catalog": "ascamaster",
        "display_name": "ASCA",
        "description": "Advanced Satellite for Cosmology and Astrophysics",
    },
    "XRISM": {
        "catalog": "xrismmastr",
        "display_name": "XRISM",
        "description": "X-Ray Imaging and Spectroscopy Mission",
    },
    "Hitomi": {
        "catalog": "hitomaster",
        "display_name": "Hitomi",
        "description": "Hitomi (ASTRO-H) X-ray Satellite",
    },
}


def _to_python_float(val: Any) -> Optional[float]:
    """Convert numpy numeric types to Python float for JSON serialization."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _to_python_int(val: Any) -> Optional[int]:
    """Convert numpy numeric types to Python int for JSON serialization."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


class ArchiveService(BaseService):
    """
    Service for HEASARC archive operations.

    Handles catalog queries and data downloads without any UI dependencies.
    """

    def get_supported_catalogs(self) -> Dict[str, Any]:
        """
        Get list of supported HEASARC catalogs.

        Returns:
            Result dictionary with catalog information
        """
        catalogs = [
            {
                "id": key,
                "catalog": info["catalog"],
                "display_name": info["display_name"],
                "description": info["description"],
            }
            for key, info in SUPPORTED_CATALOGS.items()
        ]

        return self.create_result(
            success=True,
            data={"catalogs": catalogs},
            message=f"Found {len(catalogs)} supported catalogs",
        )

    def _resolve_source_name(self, source_name: str) -> Optional[SkyCoord]:
        """
        Resolve a source name to coordinates using SIMBAD/NED.

        Args:
            source_name: Astronomical source name (e.g., "Crab", "Cyg X-1")

        Returns:
            SkyCoord object or None if resolution fails
        """
        try:
            return SkyCoord.from_name(source_name)
        except Exception:
            return None

    def _table_to_observations(
        self, table: Any, catalog_name: str
    ) -> List[Dict[str, Any]]:
        """
        Convert astropy Table from HEASARC query to list of observation dicts.

        Args:
            table: Astropy Table from Heasarc.query_region()
            catalog_name: Name of the HEASARC catalog

        Returns:
            List of observation dictionaries
        """
        observations = []

        if table is None or len(table) == 0:
            return observations

        # Column mapping varies by catalog - try common column names
        # HEASARC returns lowercase column names from astroquery
        obsid_cols = [
            "obsid",
            "obs_id",
            "observation_id",
            "seq_num",
            "sequence_number",
            "OBSID",
            "OBS_ID",
            "OBSERVATION_ID",
            "SEQ_NUM",
            "SEQUENCE_NUMBER",
        ]
        name_cols = [
            "name",
            "target_name",
            "object",
            "src_name",
            "NAME",
            "TARGET_NAME",
            "OBJECT",
            "SRC_NAME",
        ]
        ra_cols = ["ra", "ra_obj", "ra_pnt", "RA", "RA_OBJ", "RA_PNT"]
        dec_cols = ["dec", "dec_obj", "dec_pnt", "DEC", "DEC_OBJ", "DEC_PNT"]
        # Mission-specific exposure columns:
        # - NICER, Chandra, RXTE: "exposure"
        # - NuSTAR: "exposure_a" (FPMA), also has exposure_b (FPMB)
        # - XMM-Newton: "duration"
        # - Swift: "xrt_exposure", "uvot_exposure", "bat_exposure"
        #   Swift catalog has NO generic "exposure" column, so we must
        #   prioritize instrument-specific columns for Swift.
        if catalog_name == "Swift":
            # For Swift, prefer xrt_exposure first (X-ray timing), then
            # fall back to bat_exposure (BAT-only triggers have 0 XRT exposure)
            exposure_cols = [
                "xrt_exposure",
                "XRT_EXPOSURE",
                "bat_exposure",
                "BAT_EXPOSURE",
                "uvot_exposure",
                "UVOT_EXPOSURE",
                "exposure",
                "duration",
                "ontime",
                "livetime",
                "EXPOSURE",
                "DURATION",
                "ONTIME",
                "LIVETIME",
            ]
        elif catalog_name == "IXPE":
            # IXPE has per-detector-unit exposures: exposure_1, exposure_2, exposure_3
            # The main "exposure" column also exists
            exposure_cols = [
                "exposure",
                "exposure_1",
                "exposure_2",
                "exposure_3",
                "ontime_1",
                "ontime_2",
                "ontime_3",
                "EXPOSURE",
                "EXPOSURE_1",
                "EXPOSURE_2",
                "EXPOSURE_3",
            ]
        else:
            exposure_cols = [
                "exposure",
                "exposure_a",
                "duration",
                "ontime",
                "livetime",
                "good_time",
                "xrt_exposure",
                "EXPOSURE",
                "EXPOSURE_A",
                "DURATION",
                "ONTIME",
                "LIVETIME",
                "GOOD_TIME",
                "XRT_EXPOSURE",
            ]
        time_cols = [
            "time",
            "start_time",
            "date_obs",
            "tstart",
            "TIME",
            "START_TIME",
            "DATE_OBS",
            "TSTART",
        ]

        # Get table column names once
        table_cols = set(table.colnames)

        def get_column_value(
            row: Any, col_names: List[str], default: Any = None
        ) -> Any:
            """Get value from first matching column."""
            for col in col_names:
                if col in table_cols:
                    val = row[col]
                    # Handle masked arrays
                    if hasattr(val, "mask") and val.mask:
                        continue
                    return val
            return default

        # RXTE-specific columns
        prnb_cols = ["prnb", "PRNB"]

        # NICER-specific columns
        nicer_status_cols = ["processing_status", "PROCESSING_STATUS"]
        nicer_fpm_cols = ["num_fpm", "NUM_FPM"]

        for row in table:
            try:
                obs = {
                    "obsid": str(get_column_value(row, obsid_cols, "")),
                    "name": str(get_column_value(row, name_cols, "Unknown")),
                    "ra": _to_python_float(get_column_value(row, ra_cols)),
                    "dec": _to_python_float(get_column_value(row, dec_cols)),
                    "exposure": _to_python_float(
                        get_column_value(row, exposure_cols, 0)
                    ),
                    "time": str(get_column_value(row, time_cols, "")),
                    "catalog": catalog_name,
                }

                # Add mission-specific fields
                # Swift: Include per-instrument exposures and pick the best
                # non-zero exposure for the main "exposure" field
                if catalog_name == "Swift":
                    swift_xrt_cols = ["xrt_exposure", "XRT_EXPOSURE"]
                    swift_bat_cols = ["bat_exposure", "BAT_EXPOSURE"]
                    swift_uvot_cols = ["uvot_exposure", "UVOT_EXPOSURE"]
                    xrt_exp = _to_python_float(get_column_value(row, swift_xrt_cols))
                    bat_exp = _to_python_float(get_column_value(row, swift_bat_cols))
                    uvot_exp = _to_python_float(get_column_value(row, swift_uvot_cols))
                    obs["xrt_exposure"] = xrt_exp
                    obs["bat_exposure"] = bat_exp
                    obs["uvot_exposure"] = uvot_exp
                    # Use the best non-zero instrument exposure as the main
                    # exposure value (prefer XRT > BAT > UVOT)
                    if not obs["exposure"] or obs["exposure"] == 0:
                        for inst_exp in [xrt_exp, bat_exp, uvot_exp]:
                            if inst_exp and inst_exp > 0:
                                obs["exposure"] = inst_exp
                                break

                # IXPE: Include per-detector-unit exposures
                if catalog_name == "IXPE":
                    ixpe_du1_cols = ["exposure_1", "EXPOSURE_1"]
                    ixpe_du2_cols = ["exposure_2", "EXPOSURE_2"]
                    ixpe_du3_cols = ["exposure_3", "EXPOSURE_3"]
                    obs["exposure_du1"] = _to_python_float(
                        get_column_value(row, ixpe_du1_cols)
                    )
                    obs["exposure_du2"] = _to_python_float(
                        get_column_value(row, ixpe_du2_cols)
                    )
                    obs["exposure_du3"] = _to_python_float(
                        get_column_value(row, ixpe_du3_cols)
                    )

                # NICER: Include processing status and number of FPMs
                if catalog_name == "NICER":
                    obs["processing_status"] = str(
                        get_column_value(row, nicer_status_cols, "")
                    )
                    obs["num_fpm"] = _to_python_int(
                        get_column_value(row, nicer_fpm_cols)
                    )

                # NuSTAR: Include FPMB exposure, observation mode, issue flag
                if catalog_name == "NuSTAR":
                    exp_b_cols = ["exposure_b", "EXPOSURE_B"]
                    obs_mode_cols = ["observation_mode", "OBSERVATION_MODE"]
                    issue_cols = ["issue_flag", "ISSUE_FLAG"]
                    obs["exposure_b"] = _to_python_float(
                        get_column_value(row, exp_b_cols)
                    )
                    obs["observation_mode"] = str(
                        get_column_value(row, obs_mode_cols, "")
                    )
                    obs["issue_flag"] = _to_python_int(
                        get_column_value(row, issue_cols)
                    )

                # XMM-Newton: Include per-instrument exposures, modes, and status
                # query_region() returns: status, data_in_heasarc (always available)
                # ADQL/TAP returns: pn_time, pn_mode, mos1_time, mos1_mode,
                #   mos2_time, mos2_mode (only via ObsID search)
                if catalog_name == "XMM-Newton":
                    pn_time_cols = ["pn_time", "PN_TIME"]
                    pn_mode_cols = ["pn_mode", "PN_MODE"]
                    mos1_time_cols = ["mos1_time", "MOS1_TIME"]
                    mos1_mode_cols = ["mos1_mode", "MOS1_MODE"]
                    mos2_time_cols = ["mos2_time", "MOS2_TIME"]
                    mos2_mode_cols = ["mos2_mode", "MOS2_MODE"]
                    status_cols = ["status", "STATUS"]
                    data_avail_cols = ["data_in_heasarc", "DATA_IN_HEASARC"]
                    obs["pn_time"] = _to_python_float(
                        get_column_value(row, pn_time_cols)
                    )
                    obs["pn_mode"] = str(get_column_value(row, pn_mode_cols, ""))
                    obs["mos1_time"] = _to_python_float(
                        get_column_value(row, mos1_time_cols)
                    )
                    obs["mos1_mode"] = str(get_column_value(row, mos1_mode_cols, ""))
                    obs["mos2_time"] = _to_python_float(
                        get_column_value(row, mos2_time_cols)
                    )
                    obs["mos2_mode"] = str(get_column_value(row, mos2_mode_cols, ""))
                    obs["xmm_status"] = str(get_column_value(row, status_cols, ""))
                    obs["data_in_heasarc"] = str(
                        get_column_value(row, data_avail_cols, "")
                    )

                # Chandra: Include detector, grating, status
                if catalog_name == "Chandra":
                    detector_cols = ["detector", "DETECTOR"]
                    grating_cols = ["grating", "GRATING"]
                    chandra_status_cols = ["status", "STATUS"]
                    obs["detector"] = str(get_column_value(row, detector_cols, ""))
                    obs["grating"] = str(get_column_value(row, grating_cols, ""))
                    obs["chandra_status"] = str(
                        get_column_value(row, chandra_status_cols, "")
                    )

                # RXTE: Include proposal number for directory lookup
                prnb = get_column_value(row, prnb_cols)
                if prnb is not None:
                    obs["prnb"] = str(prnb)

                # Only include observations with valid obsid
                if obs["obsid"]:
                    observations.append(obs)
            except Exception:
                # Skip malformed rows
                continue

        return observations

    def _apply_table_filters(
        self,
        table: Any,
        min_exposure: Optional[float] = None,
        time_range: Optional[Tuple[float, float]] = None,
    ) -> Any:
        """
        Apply post-query filters to an astropy Table.

        Args:
            table: Astropy Table from HEASARC query
            min_exposure: Minimum exposure time in seconds
            time_range: Tuple of (mjd_start, mjd_end) for date filtering

        Returns:
            Filtered astropy Table
        """
        if table is None or len(table) == 0:
            return table

        if min_exposure is not None:
            exposure_col = None
            for col in [
                "exposure",
                "exposure_a",
                "duration",
                "ontime",
                "xrt_exposure",
                "bat_exposure",
            ]:
                if col in table.colnames:
                    exposure_col = col
                    break
            if exposure_col is not None:
                try:
                    table = table[table[exposure_col] >= min_exposure]
                except Exception:
                    pass

        if time_range is not None:
            time_col = None
            for col in ["time", "start_time", "date_obs", "tstart"]:
                if col in table.colnames:
                    time_col = col
                    break
            if time_col is not None:
                try:
                    mjd_start, mjd_end = time_range
                    table = table[
                        (table[time_col] >= mjd_start) & (table[time_col] <= mjd_end)
                    ]
                except Exception:
                    pass

        return table

    def search_by_name(
        self,
        source_name: str,
        mission: str,
        radius: float = 0.5,
        max_results: int = 100,
        min_exposure: Optional[float] = None,
        time_range: Optional[Tuple[float, float]] = None,
    ) -> Dict[str, Any]:
        """
        Search HEASARC for observations by source name.

        Uses SIMBAD/NED to resolve the source name to coordinates,
        then queries the appropriate HEASARC catalog.

        Args:
            source_name: Astronomical source name (e.g., "Crab", "Cyg X-1")
            mission: Mission key (e.g., "NICER", "NuSTAR")
            radius: Search radius in degrees
            max_results: Maximum number of results to return
            min_exposure: Minimum exposure time in seconds (post-query filter)
            time_range: Tuple of (mjd_start, mjd_end) for date filtering

        Returns:
            Result dictionary with observations
        """
        try:
            # Validate mission
            if mission not in SUPPORTED_CATALOGS:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Unsupported mission: {mission}",
                    error=f"Supported missions: {list(SUPPORTED_CATALOGS.keys())}",
                )

            catalog_info = SUPPORTED_CATALOGS[mission]
            catalog_name = catalog_info["catalog"]

            # Resolve source name to coordinates
            coords = self._resolve_source_name(source_name)
            if coords is None:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Could not resolve source name: '{source_name}'",
                    error="Name resolution failed via SIMBAD/NED",
                )

            # Query HEASARC
            try:
                with _open_heasarc_client() as heasarc:
                    table = heasarc.query_region(
                        coords,
                        catalog=catalog_name,
                        radius=radius * u.deg,
                        columns="*",
                        maxrec=MAX_ARCHIVE_SEARCH_REMOTE_ROWS,
                    )
            except Exception as e:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"HEASARC query failed: {str(e)}",
                    error=str(e),
                )

            # Apply post-query filters
            table = self._apply_table_filters(table, min_exposure, time_range)

            # Convert to observations
            observations = self._table_to_observations(table, mission)

            # Limit results
            if len(observations) > max_results:
                observations = observations[:max_results]

            return self.create_result(
                success=True,
                data={
                    "observations": observations,
                    "count": len(observations),
                    "source_name": source_name,
                    "resolved_ra": _to_python_float(coords.ra.deg),
                    "resolved_dec": _to_python_float(coords.dec.deg),
                    "mission": mission,
                    "radius": radius,
                },
                message=f"Found {len(observations)} observations for '{source_name}' in {mission}",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Searching HEASARC by name",
                source_name=source_name,
                mission=mission,
            )

    def search_by_coordinates(
        self,
        ra: float,
        dec: float,
        mission: str,
        radius: float = 0.5,
        max_results: int = 100,
        min_exposure: Optional[float] = None,
        time_range: Optional[Tuple[float, float]] = None,
    ) -> Dict[str, Any]:
        """
        Search HEASARC for observations by coordinates.

        Args:
            ra: Right Ascension in degrees
            dec: Declination in degrees
            mission: Mission key (e.g., "NICER", "NuSTAR")
            radius: Search radius in degrees
            max_results: Maximum number of results to return
            min_exposure: Minimum exposure time in seconds (post-query filter)
            time_range: Tuple of (mjd_start, mjd_end) for date filtering

        Returns:
            Result dictionary with observations
        """
        try:
            # Validate mission
            if mission not in SUPPORTED_CATALOGS:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Unsupported mission: {mission}",
                    error=f"Supported missions: {list(SUPPORTED_CATALOGS.keys())}",
                )

            catalog_info = SUPPORTED_CATALOGS[mission]
            catalog_name = catalog_info["catalog"]

            # Create coordinates
            coords = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)

            # Query HEASARC
            try:
                with _open_heasarc_client() as heasarc:
                    table = heasarc.query_region(
                        coords,
                        catalog=catalog_name,
                        radius=radius * u.deg,
                        columns="*",
                        maxrec=MAX_ARCHIVE_SEARCH_REMOTE_ROWS,
                    )
            except Exception as e:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"HEASARC query failed: {str(e)}",
                    error=str(e),
                )

            # Apply post-query filters
            table = self._apply_table_filters(table, min_exposure, time_range)

            # Convert to observations
            observations = self._table_to_observations(table, mission)

            # Limit results
            if len(observations) > max_results:
                observations = observations[:max_results]

            return self.create_result(
                success=True,
                data={
                    "observations": observations,
                    "count": len(observations),
                    "ra": ra,
                    "dec": dec,
                    "mission": mission,
                    "radius": radius,
                },
                message=f"Found {len(observations)} observations at RA={ra:.4f}, Dec={dec:.4f} in {mission}",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Searching HEASARC by coordinates",
                ra=ra,
                dec=dec,
                mission=mission,
            )

    def search_by_obsid(
        self,
        obsid: str,
        mission: str,
    ) -> Dict[str, Any]:
        """
        Search HEASARC for an observation by its ObsID using ADQL TAP query.

        This does not require coordinates — it directly queries the catalog
        by observation ID.

        Args:
            obsid: Observation ID to search for
            mission: Mission key (e.g., "NICER", "NuSTAR")

        Returns:
            Result dictionary with observations
        """
        try:
            # Validate mission
            if mission not in SUPPORTED_CATALOGS:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Unsupported mission: {mission}",
                    error=f"Supported missions: {list(SUPPORTED_CATALOGS.keys())}",
                )

            if not obsid or not obsid.strip():
                return self.create_result(
                    success=False,
                    data=None,
                    message="Please enter an Observation ID",
                    error="Empty obsid",
                )

            catalog_info = SUPPORTED_CATALOGS[mission]
            catalog_name = catalog_info["catalog"]

            # Sanitize obsid for ADQL
            safe_obsid = obsid.strip().replace("'", "''")
            adql = f"SELECT * FROM {catalog_name} WHERE obsid = '{safe_obsid}'"

            try:
                with _open_heasarc_client() as heasarc:
                    tap_result = heasarc.query_tap(
                        adql,
                        maxrec=MAX_ARCHIVE_OBSID_REMOTE_ROWS,
                    )
                    table = tap_result.to_table()
            except Exception as e:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"HEASARC ObsID query failed: {str(e)}",
                    error=str(e),
                )

            if table is None or len(table) == 0:
                return self.create_result(
                    success=True,
                    data={
                        "observations": [],
                        "count": 0,
                        "obsid": obsid,
                        "mission": mission,
                    },
                    message=f"No observations found for ObsID '{obsid}' in {mission}",
                )

            # Convert to observations
            observations = self._table_to_observations(table, mission)

            return self.create_result(
                success=True,
                data={
                    "observations": observations,
                    "count": len(observations),
                    "obsid": obsid,
                    "mission": mission,
                },
                message=f"Found {len(observations)} observation(s) for ObsID '{obsid}' in {mission}",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Searching HEASARC by ObsID",
                obsid=obsid,
                mission=mission,
            )

    def get_observation_download_urls(
        self,
        mission: str,
        obsid: str,
    ) -> Dict[str, Any]:
        """
        Get download URLs for an observation.

        Constructs browse URLs based on known HEASARC patterns.

        Args:
            mission: Mission key (e.g., "NICER", "NuSTAR")
            obsid: Observation ID

        Returns:
            Result dictionary with download URLs
        """
        try:
            # Validate mission
            if mission not in SUPPORTED_CATALOGS:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Unsupported mission: {mission}",
                    error=f"Supported missions: {list(SUPPORTED_CATALOGS.keys())}",
                )

            # Construct URLs based on known HEASARC patterns
            urls = self._construct_download_urls(mission, obsid)

            return self.create_result(
                success=True,
                data={
                    "urls": urls,
                    "mission": mission,
                    "obsid": obsid,
                },
                message=f"Found download URLs for {mission} observation {obsid}",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Getting download URLs",
                mission=mission,
                obsid=obsid,
            )

    def _construct_download_urls(self, mission: str, obsid: str) -> Dict[str, str]:
        """
        Construct download URLs based on mission-specific patterns.

        HEASARC has standard URL patterns for each mission's data archive.

        Args:
            mission: Mission key
            obsid: Observation ID

        Returns:
            Dict with url types as keys and URLs as values
        """
        urls = {}

        if mission == "NICER":
            # NICER data path: /nicer/data/obs/YYYY_MM/OBSID/
            # We can't know the exact date folder without more info
            # But we can construct a search URL
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dnicermastr&obsid={obsid}"
            )

        elif mission == "NuSTAR":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dnumaster&obsid={obsid}"
            )

        elif mission == "XMM-Newton":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dxmmmaster&obsid={obsid}"
            )

        elif mission == "Chandra":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dchanmaster&obsid={obsid}"
            )

        elif mission == "Swift":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dswiftmastr&obsid={obsid}"
            )

        elif mission == "RXTE":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dxtemaster&obsid={obsid}"
            )

        elif mission == "IXPE":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dixmaster&obsid={obsid}"
            )

        elif mission == "Suzaku":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dsuzamaster&obsid={obsid}"
            )

        elif mission == "ASCA":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dascamaster&obsid={obsid}"
            )

        elif mission == "XRISM":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dxrismmastr&obsid={obsid}"
            )

        elif mission == "Hitomi":
            urls["browse"] = (
                f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dhitomaster&obsid={obsid}"
            )

        return urls

    async def _list_directory_with_metadata(
        self,
        directory_url: str,
        budget: ArchiveCrawlBudget,
        cancellation_check: CancellationCheck | None,
    ) -> List[Dict[str, Any]]:
        """Fetch and parse one bounded HEASARC directory listing."""
        budget.begin_directory()
        hop_seconds = min(ARCHIVE_CRAWL_HOP_SECONDS, budget.remaining())
        client = RemoteSourceClient(
            HEASARC_ARCHIVE_POLICY,
            timeouts=RemoteTimeouts(
                connect=min(10.0, hop_seconds),
                read=min(10.0, hop_seconds),
                write=min(10.0, hop_seconds),
                pool=min(5.0, hop_seconds),
                total=hop_seconds,
            ),
            max_redirects=3,
            chunk_size=64 * 1024,
        )
        body, info = await client.fetch_bytes(
            directory_url,
            max_bytes=MAX_ARCHIVE_DIRECTORY_HTML_BYTES,
            cancellation_check=cancellation_check,
        )
        if info.status_code != 200:
            raise RemoteSourceError(
                "The archive server did not return a complete directory listing"
            )
        if info.content_type is not None:
            media_type = info.content_type.split(";", 1)[0].strip().lower()
            if media_type not in {
                "text/html",
                "text/plain",
                "application/xhtml+xml",
            }:
                raise RemoteSourceError(
                    "The archive server returned an unexpected directory format"
                )
        try:
            html = body.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise RemoteSourceError(
                "The archive directory listing is not valid UTF-8"
            ) from error

        await self._raise_if_download_cancelled(cancellation_check)
        entries = await asyncio.to_thread(self._parse_archive_directory_html, html)
        await self._raise_if_download_cancelled(cancellation_check)
        budget.add_entries(len(entries))
        return entries

    @staticmethod
    def _decode_archive_entry_href(href: Any) -> tuple[str, bool] | None:
        """Accept one canonical relative UTF-8 path segment from listing HTML."""
        if not isinstance(href, str) or not href:
            return None
        if len(href) > MAX_ARCHIVE_ENTRY_HREF_CHARS:
            raise RemoteSourceError("An archive directory entry is too long")
        if href.startswith("?") or href.startswith("#") or href in {".", "./", "../"}:
            return None

        try:
            parts = urlsplit(href)
        except ValueError as error:
            raise RemoteSourceError("An archive directory entry is invalid") from error
        if parts.scheme or parts.netloc:
            raise RemoteSourceError("An archive directory entry is not relative")
        if parts.query or parts.fragment:
            raise RemoteSourceError("An archive directory entry has metadata")
        if parts.path.startswith("/"):
            # Apache listings can contain root navigation or icon links. They are
            # not children of the observation and must never become crawl hops.
            return None

        is_directory = parts.path.endswith("/")
        encoded_name = parts.path[:-1] if is_directory else parts.path
        if not encoded_name:
            return None
        percent_index = 0
        while True:
            percent_index = encoded_name.find("%", percent_index)
            if percent_index < 0:
                break
            if percent_index + 2 >= len(encoded_name) or not all(
                character in "0123456789abcdefABCDEF"
                for character in encoded_name[percent_index + 1 : percent_index + 3]
            ):
                raise RemoteSourceError(
                    "An archive directory entry has invalid percent encoding"
                )
            percent_index += 3
        try:
            name = unquote_to_bytes(encoded_name).decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise RemoteSourceError(
                "An archive directory entry is not valid UTF-8"
            ) from error
        if (
            not name
            or name != name.strip()
            or len(name) > MAX_ARCHIVE_ENTRY_NAME_CHARS
            or name in {".", ".."}
            or "%" in name
            or "/" in name
            or "\\" in name
            or any(
                ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F
                for character in name
            )
        ):
            raise RemoteSourceError("An archive directory entry is unsafe")
        return name, is_directory

    def _parse_archive_directory_html(self, html: str) -> List[Dict[str, Any]]:
        """Parse a byte-bounded listing without accepting arbitrary URL targets."""
        from bs4 import BeautifulSoup, NavigableString

        soup = BeautifulSoup(html, "lxml")
        links = soup.find_all("a", limit=MAX_ARCHIVE_DIRECTORY_ENTRIES + 1)
        if len(links) > MAX_ARCHIVE_DIRECTORY_ENTRIES:
            raise RemoteSourceError("An archive directory contains too many entries")

        entries: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for link in links:
            decoded = self._decode_archive_entry_href(link.get("href"))
            if decoded is None:
                continue
            name, is_directory = decoded
            if name in seen:
                continue
            seen.add(name)

            size_bytes = None
            sibling = link.next_sibling
            if not is_directory and isinstance(sibling, NavigableString):
                line_tail = str(sibling).splitlines()[0][:256]
                parts = line_tail.split()
                if parts:
                    size_bytes = self._parse_size(parts[-1])
            entries.append(
                {
                    "name": name,
                    "is_directory": is_directory,
                    "size_bytes": size_bytes,
                }
            )
        return entries

    def _parse_size(self, size_str: str) -> Optional[int]:
        """
        Parse size string like '125M', '45K', '1.2G', '12345' to bytes.

        Args:
            size_str: Size string to parse

        Returns:
            Size in bytes or None if not a valid size
        """
        size_str = size_str.strip()
        if not size_str:
            return None

        suffixes = {
            "K": 1024,
            "M": 1024 * 1024,
            "G": 1024 * 1024 * 1024,
            "T": 1024 * 1024 * 1024 * 1024,
        }
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGT]?)", size_str.upper())
        if match is None:
            return None
        try:
            value = float(match.group(1)) * suffixes.get(match.group(2), 1)
        except (OverflowError, ValueError):
            return None
        if not math.isfinite(value) or value < 0 or value > (2**63 - 1):
            return None
        return int(value)

    def _classify_file_type(self, filename: str, mission: str) -> str:
        """
        Classify a file into a type category based on its name.

        Args:
            filename: File name to classify
            mission: Mission name for mission-specific patterns

        Returns:
            File type: 'event', 'calibration', 'auxiliary', 'log', 'other'
        """
        filename_lower = filename.lower()

        # Strip compression suffixes for pattern matching
        for ext in (".gz", ".bz2", ".z", ".zip"):
            if filename_lower.endswith(ext):
                filename_lower = filename_lower[: -len(ext)]
                break

        # Event file patterns
        event_patterns = [
            "_cl.evt",
            "_ufa.evt",
            "evt.fits",
            "_evt2.fits",
            "evli",  # XMM event list
        ]
        if any(p in filename_lower for p in event_patterns):
            return "event"

        # Calibration patterns
        cal_patterns = [
            "_cal",
            "response",
            ".rmf",
            ".arf",
            "caldb",
            "matrix",
        ]
        if any(p in filename_lower for p in cal_patterns):
            return "calibration"

        # Auxiliary patterns
        aux_patterns = [
            ".att",
            ".orb",
            "mkf",
            ".gti",
            "_uf.evt",  # Unfiltered (not cleaned)
            "attitude",
            "orbit",
            "housekeeping",
            "hk",
            "_asol",  # Chandra aspect solution
            "_dtf",  # Chandra dead time factor (HRC)
            "_bpix",  # Chandra bad pixel list
            "_fov",  # Chandra field of view
        ]
        if any(p in filename_lower for p in aux_patterns):
            return "auxiliary"

        # Log patterns
        log_patterns = [".log", "readme", "index.html"]
        if any(p in filename_lower for p in log_patterns):
            return "log"

        return "other"

    def _format_size(self, size_bytes: Optional[int]) -> str:
        """Format size in bytes to human-readable string."""
        if size_bytes is None:
            return "Unknown"

        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    async def list_observation_files(
        self,
        mission: str,
        obsid: str,
        obs_time: Optional[str] = None,
        obs_data: Optional[Dict[str, Any]] = None,
        recursive: bool = True,
        max_depth: int = 3,
        cancellation_check: CancellationCheck | None = None,
    ) -> Dict[str, Any]:
        """
        List all files in an observation directory.

        Uses _get_observation_directory_url() to get the base URL, then
        recursively parses HTML directory listings to build a file tree.

        Args:
            mission: Mission key (e.g., "NICER", "NuSTAR")
            obsid: Observation ID
            obs_time: Observation time (MJD or ISO string) for directory lookup
            obs_data: Additional observation data (e.g., prnb for RXTE, ra/dec for coordinate queries)
            recursive: Whether to recursively list subdirectories
            max_depth: Maximum recursion depth

        Returns:
            Result dictionary with file tree structure
        """
        try:
            clean_obs_data = self._validate_archive_crawl_request(
                mission,
                obsid,
                obs_time,
                obs_data,
                recursive,
                max_depth,
            )
            base_url = self._get_observation_directory_url(
                mission,
                obsid,
                obs_time,
                clean_obs_data,
            )
            if base_url is None:
                return self.create_result(
                    success=False,
                    data=None,
                    message="The observation directory cannot be derived safely",
                    error="Required bounded observation metadata is unavailable",
                )

            budget = ArchiveCrawlBudget(
                deadline=time.monotonic() + ARCHIVE_CRAWL_TOTAL_SECONDS
            )
            files = await self._list_files_recursive(
                base_url,
                mission,
                recursive,
                max_depth,
                0,
                budget,
                cancellation_check,
            )

            return self.create_result(
                success=True,
                data={
                    "base_url": base_url,
                    "files": files,
                    "mission": mission,
                    "obsid": obsid,
                    "total_files": self._count_files(files),
                },
                message=f"Found {self._count_files(files)} files in {mission} observation {obsid}",
            )
        except RemoteSourceCancelled:
            return self.create_result(
                success=False,
                data=None,
                message="Archive directory listing cancelled",
                error="The request was cancelled before the listing completed",
            )
        except RemoteSourceTimeout:
            return self.create_result(
                success=False,
                data=None,
                message="The archive directory listing timed out",
                error="The bounded archive crawl deadline expired",
            )
        except (RemoteSourceError, TypeError, ValueError):
            return self.create_result(
                success=False,
                data=None,
                message="The archive directory listing failed validation",
                error="The archive crawl was rejected safely",
            )

    @staticmethod
    def _validate_archive_crawl_request(
        mission: Any,
        obsid: Any,
        obs_time: Any,
        obs_data: Any,
        recursive: Any,
        max_depth: Any,
    ) -> Dict[str, Any]:
        """Defend the service boundary even when called without the API model."""
        if mission not in SUPPORTED_CATALOGS:
            raise ValueError("Unsupported archive mission")
        if not isinstance(obsid, str) or ARCHIVE_IDENTIFIER.fullmatch(obsid) is None:
            raise ValueError("Invalid archive observation identifier")
        if obs_time is not None and (
            not isinstance(obs_time, str)
            or not obs_time
            or len(obs_time) > 64
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in obs_time
            )
        ):
            raise ValueError("Invalid archive observation time")
        if not isinstance(recursive, bool):
            raise TypeError("Archive recursion must be a boolean")
        if (
            not isinstance(max_depth, int)
            or isinstance(max_depth, bool)
            or not 0 <= max_depth <= MAX_ARCHIVE_CRAWL_DEPTH
        ):
            raise ValueError("Archive recursion depth is out of range")
        if obs_data is None:
            return {}
        if not isinstance(obs_data, dict) or not set(obs_data) <= {"ra", "dec", "prnb"}:
            raise ValueError("Invalid archive observation metadata")

        clean_data: Dict[str, Any] = {}
        for key, lower, upper in (("ra", 0.0, 360.0), ("dec", -90.0, 90.0)):
            value = obs_data.get(key)
            if value is None:
                continue
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or not lower <= float(value) <= upper
            ):
                raise ValueError("Invalid archive observation coordinates")
            clean_data[key] = float(value)
        proposal = obs_data.get("prnb")
        if proposal is not None:
            if (
                not isinstance(proposal, str)
                or ARCHIVE_PROPOSAL.fullmatch(proposal) is None
            ):
                raise ValueError("Invalid archive proposal identifier")
            if not proposal.isdigit() or len(proposal) > 6:
                raise ValueError("Invalid archive proposal identifier")
            clean_data["prnb"] = proposal
        return clean_data

    async def _list_files_recursive(
        self,
        directory_url: str,
        mission: str,
        recursive: bool,
        max_depth: int,
        current_depth: int,
        budget: ArchiveCrawlBudget,
        cancellation_check: CancellationCheck | None,
    ) -> List[Dict[str, Any]]:
        """
        Recursively list files in a directory.

        Args:
            directory_url: URL of the directory to list
            mission: Mission name for file classification
            recursive: Whether to recurse into subdirectories
            max_depth: Maximum recursion depth
            current_depth: Current recursion depth

        Returns:
            List of file/directory entries
        """
        if current_depth > max_depth or current_depth > MAX_ARCHIVE_CRAWL_DEPTH:
            raise RemoteSourceError("The archive crawl exceeded its recursion depth")
        await self._raise_if_download_cancelled(cancellation_check)
        budget.remaining()
        entries = await self._list_directory_with_metadata(
            directory_url,
            budget,
            cancellation_check,
        )
        result = []

        for entry in entries:
            await self._raise_if_download_cancelled(cancellation_check)
            budget.remaining()
            name = entry["name"]
            is_directory = entry["is_directory"]
            size_bytes = entry["size_bytes"]

            encoded_name = quote(name, safe="-._~")
            full_url = directory_url.rstrip("/") + "/" + encoded_name

            if is_directory:
                children = []
                if recursive and current_depth < max_depth:
                    children = await self._list_files_recursive(
                        full_url + "/",
                        mission,
                        recursive,
                        max_depth,
                        current_depth + 1,
                        budget,
                        cancellation_check,
                    )

                result.append(
                    {
                        "path": name,
                        "name": name,
                        "is_directory": True,
                        "file_type": "directory",
                        "size_bytes": None,
                        "size_display": "",
                        "full_url": full_url + "/",
                        "children": children,
                    }
                )
            else:
                file_type = self._classify_file_type(name, mission)
                result.append(
                    {
                        "path": name,
                        "name": name,
                        "is_directory": False,
                        "file_type": file_type,
                        "size_bytes": size_bytes,
                        "size_display": self._format_size(size_bytes),
                        "full_url": full_url,
                    }
                )

        return result

    def _count_files(self, entries: List[Dict[str, Any]]) -> int:
        """Count total number of files (not directories) in a tree."""
        count = 0
        for entry in entries:
            if entry["is_directory"]:
                count += self._count_files(entry.get("children", []))
            else:
                count += 1
        return count

    def _get_observation_directory_url(
        self,
        mission: str,
        obsid: str,
        obs_time: Optional[str] = None,
        obs_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Construct the likely directory URL for an observation.

        HEASARC organizes data in mission-specific directory structures.
        This method constructs the most likely directory URL based on
        known patterns.

        Args:
            mission: Mission key
            obsid: Observation ID
            obs_time: Observation time (MJD float as string, or ISO date string)
                     Required for NICER and Swift to determine the date-based subdirectory
            obs_data: Additional observation data (e.g., prnb for RXTE)

        Returns:
            Directory URL or None if pattern unknown
        """
        from astropy.time import Time

        base_url = "https://heasarc.gsfc.nasa.gov/FTP"
        obs_data = obs_data or {}

        # Helper to parse obs_time to YYYY_MM format
        def get_year_month(time_str: Optional[str]) -> Optional[str]:
            if not time_str:
                return None
            try:
                # Try parsing as MJD first (numeric string)
                try:
                    mjd = float(time_str)
                    t = Time(mjd, format="mjd")
                except ValueError:
                    # Try as ISO format
                    t = Time(time_str, format="isot")
                return t.datetime.strftime("%Y_%m")
            except Exception:
                return None

        if mission == "NICER":
            # NICER: /nicer/data/obs/YYYY_MM/OBSID/
            year_month = get_year_month(obs_time)
            if year_month:
                return f"{base_url}/nicer/data/obs/{year_month}/{obsid}/"
            return None

        elif mission == "NuSTAR":
            # NuSTAR ObsID format: CPPttxxxvvv (11 digits)
            #   C = source category (1 digit): 1=calibration, 3=ToO, 6=AGN, 8=galactic
            #   PP = proposal/cycle (2 digits): 00=primary, 01+=extended missions
            # HEASARC archive path: /nustar/data/obs/PP/C/OBSID/
            #   PP = obsid[1:3] (proposal cycle)
            #   C  = obsid[0]  (source category)
            # Example: 60002023006 -> /nustar/data/obs/00/6/60002023006/
            if len(obsid) >= 4:
                return f"{base_url}/nustar/data/obs/{obsid[1:3]}/{obsid[0]}/{obsid}/"
            return None

        elif mission == "Chandra":
            # Chandra: /chandra/data/byobsid/X/OBSID/
            # X = LAST digit of obsid
            # Example: 758 -> /chandra/data/byobsid/8/758/
            if obsid and obsid[-1].isdigit():
                return f"{base_url}/chandra/data/byobsid/{obsid[-1]}/{obsid}/"
            return None

        elif mission == "Swift":
            # Swift: /swift/data/obs/YYYY_MM/OBSID/
            year_month = get_year_month(obs_time)
            if year_month:
                return f"{base_url}/swift/data/obs/{year_month}/{obsid}/"
            return None

        elif mission == "XMM-Newton":
            # XMM: /xmm/data/rev0/OBSID/
            return f"{base_url}/xmm/data/rev0/{obsid}/"

        elif mission == "RXTE":
            # RXTE: /xte/data/archive/AO{cycle}/P{prnb}/{obsid}/
            # prnb is the proposal number from the observation data
            # The AO cycle can be estimated from the observation date or prnb
            prnb = obs_data.get("prnb")
            if prnb:
                # Estimate AO cycle from prnb
                # RXTE had AO cycles 1-16 (1996-2012)
                # prnb format is typically 5 digits, early proposals are lower numbers
                try:
                    prnb_num = int(prnb)
                    # Rough mapping based on proposal number ranges
                    # This is an approximation - locate_data is more reliable
                    if prnb_num < 10000:
                        ao_cycle = "AO1"
                    elif prnb_num < 20000:
                        ao_cycle = "AO2"
                    elif prnb_num < 30000:
                        ao_cycle = "AO3"
                    elif prnb_num < 40000:
                        ao_cycle = "AO4"
                    elif prnb_num < 50000:
                        ao_cycle = "AO5"
                    elif prnb_num < 60000:
                        ao_cycle = "AO6"
                    elif prnb_num < 70000:
                        ao_cycle = "AO7"
                    elif prnb_num < 80000:
                        ao_cycle = "AO8"
                    elif prnb_num < 90000:
                        ao_cycle = "AO9"
                    elif prnb_num < 93000:
                        ao_cycle = "AO10"
                    elif prnb_num < 94000:
                        ao_cycle = "AO11"
                    elif prnb_num < 95000:
                        ao_cycle = "AO12"
                    elif prnb_num < 96000:
                        ao_cycle = "AO13"
                    elif prnb_num < 97000:
                        ao_cycle = "AO14"
                    elif prnb_num < 98000:
                        ao_cycle = "AO15"
                    else:
                        ao_cycle = "AO16"
                    # Note: RXTE archive uses /xte/ not /rxte/ in the path
                    return f"{base_url}/xte/data/archive/{ao_cycle}/P{prnb}/{obsid}/"
                except (ValueError, TypeError):
                    pass
            # Cannot construct URL without prnb - fallback to locate_data
            return None

        elif mission == "IXPE":
            # IXPE: /ixpe/data/obs/NN/OBSID/
            # NN = first 2 digits of obsid (e.g., 02001099 -> /obs/02/02001099/)
            if len(obsid) >= 2:
                return f"{base_url}/ixpe/data/obs/{obsid[:2]}/{obsid}/"
            return None

        elif mission == "Suzaku":
            # Suzaku: /suzaku/data/obs/N/OBSID/
            # N = first digit of obsid
            if obsid and obsid[0].isdigit():
                return f"{base_url}/suzaku/data/obs/{obsid[0]}/{obsid}/"
            return None

        elif mission == "ASCA":
            # ASCA: /asca/data/rev2/OBSID/
            # Flat structure, direct obsid directory
            return f"{base_url}/asca/data/rev2/{obsid}/"

        elif mission == "XRISM":
            # XRISM: /xrism/data/obs/N/OBSID/
            # N = first digit of obsid
            if obsid and obsid[0].isdigit():
                return f"{base_url}/xrism/data/obs/{obsid[0]}/{obsid}/"
            return None

        elif mission == "Hitomi":
            # Hitomi: /hitomi/data/obs/N/OBSID/
            # N = first digit of obsid
            if obsid and obsid[0].isdigit():
                return f"{base_url}/hitomi/data/obs/{obsid[0]}/{obsid}/"
            return None

        return None

    async def download_file_to_disk(
        self,
        url: str,
        destination_path: str,
        destination_grant: str,
        cancellation_check: CancellationCheck | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Download one approved HEASARC object to one granted destination.

        Bytes remain private until the complete response has been size-checked,
        hashed, reopened, and hashed again.  The secure-publication adapter is
        solely responsible for exclusive publication and owned cleanup.
        """
        try:
            completion_event: dict[str, Any] | None = None
            with ExitStack() as context_stack:
                publication = context_stack.enter_context(
                    open_secure_publication(
                        destination_path,
                        destination_grant,
                    )
                )
                publication.revalidate("The selected destination path changed")
                self._validate_download_filename(publication.filename)
                destination_key = hashlib.sha256(
                    os.fsencode(os.path.normcase(str(publication.path)))
                ).digest()
                context_stack.enter_context(
                    ARCHIVE_DOWNLOAD_COORDINATOR.claim(destination_key)
                )
                publication.assert_destination_available()
                publication.reserve_staging(".download")

                client = RemoteSourceClient(
                    HEASARC_ARCHIVE_POLICY,
                    timeouts=ARCHIVE_DOWNLOAD_TIMEOUTS,
                    max_redirects=5,
                    chunk_size=ARCHIVE_DOWNLOAD_CHUNK_BYTES,
                )
                content_digest = hashlib.sha256()
                bytes_downloaded = 0
                content_length: int | None = None

                artifact_writer = ArchiveArtifactWriter(publication)
                artifact_writer.start()
                try:
                    async with client.stream(
                        url,
                        max_bytes=MAX_ARCHIVE_DOWNLOAD_BYTES,
                        cancellation_check=cancellation_check,
                    ) as remote_stream:
                        if remote_stream.info.status_code != 200:
                            raise RemoteSourceError(
                                "The archive server did not return a complete object"
                            )
                        content_length = remote_stream.info.content_length
                        async for chunk in remote_stream.aiter_bytes():
                            await artifact_writer.write(
                                chunk,
                                cancellation_check,
                            )
                            content_digest.update(chunk)
                            bytes_downloaded += len(chunk)
                            total_bytes = content_length or 0
                            percent = (
                                min(100.0, bytes_downloaded / total_bytes * 100.0)
                                if total_bytes
                                else 0.0
                            )
                            yield {
                                "type": "progress",
                                "bytes_downloaded": bytes_downloaded,
                                "total_bytes": total_bytes,
                                "percent": round(percent, 1),
                            }
                    await artifact_writer.finish(cancellation_check)
                except BaseException:
                    await artifact_writer.abort_and_join()
                    raise

                await self._raise_if_download_cancelled(cancellation_check)
                if content_length is not None and bytes_downloaded != content_length:
                    raise RemoteSourceError(
                        "The remote response did not match its declared size"
                    )
                if bytes_downloaded < 1:
                    raise RemoteSourceError("The remote response was empty")

                expected_digest = content_digest.digest()
                await self._run_download_verification(
                    publication,
                    bytes_downloaded,
                    expected_digest,
                    cancellation_check,
                )
                await self._raise_if_download_cancelled(cancellation_check)
                # Publication is a short, descriptor-relative metadata operation.
                # Keep it in this task so cancellation cannot detach it and expose
                # a final file after the request has already unwound.
                warnings = publication.publish()

                completion_event = {
                    "type": "complete",
                    "file_name": publication.filename,
                    "size_bytes": bytes_downloaded,
                    "sha256": content_digest.hexdigest(),
                    "warnings": ([ARCHIVE_STAGING_WARNING] if warnings else []),
                }

            # Release the global claim and every pinned publication handle before
            # signaling terminal success to a potentially stalled SSE consumer.
            if completion_event is None:
                raise RuntimeError("Download completion was not constructed")
            yield completion_event

        except asyncio.CancelledError:
            # StreamingResponse cancellation closes the generator; ExitStack
            # removes only the adapter-owned private artifact before propagation.
            raise
        except RemoteSourceCancelled:
            yield {"type": "error", "error": "Download cancelled"}
        except ArchiveDownloadBusyError:
            yield {
                "type": "error",
                "error": "A download is already using the selected destination",
            }
        except ArchiveDownloadCapacityError:
            yield {
                "type": "error",
                "error": "Too many archive downloads are already active",
            }
        except RemoteSourcePolicyError:
            yield {
                "type": "error",
                "error": "The selected URL is not an approved HEASARC archive download",
            }
        except RemoteSourceHTTPError as error:
            yield {
                "type": "error",
                "error": f"The HEASARC server returned HTTP {error.status_code}",
            }
        except RemoteSourceTimeout:
            yield {"type": "error", "error": "The HEASARC download timed out"}
        except RemoteSourceError:
            yield {"type": "error", "error": "The HEASARC download failed validation"}
        except PermissionError:
            yield {
                "type": "error",
                "error": (
                    "The save authorization is invalid or expired; choose the "
                    "destination again"
                ),
            }
        except FileExistsError:
            yield {
                "type": "error",
                "error": "A file already exists at the selected destination",
            }
        except (OSError, ValueError, RuntimeError):
            yield {
                "type": "error",
                "error": "The download could not be published safely",
            }

    @staticmethod
    async def _raise_if_download_cancelled(
        cancellation_check: CancellationCheck | None,
    ) -> None:
        if cancellation_check is None:
            return
        cancelled = cancellation_check()
        if inspect.isawaitable(cancelled):
            cancelled = await cancelled
        if cancelled:
            raise RemoteSourceCancelled("Remote transfer was cancelled")

    @staticmethod
    def _validate_download_filename(filename: str) -> None:
        if (
            filename in {"", ".", ".."}
            or len(filename) > 512
            or "/" in filename
            or "\\" in filename
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in filename
            )
        ):
            raise ValueError("The selected destination filename is invalid")

    @staticmethod
    async def _run_download_verification(
        publication: SecurePublication,
        expected_size: int,
        expected_digest: bytes,
        cancellation_check: CancellationCheck | None,
    ) -> None:
        """Poll cancellation and join the descriptor-owning verifier on exit."""
        cancellation_event = threading.Event()
        task = asyncio.create_task(
            asyncio.to_thread(
                ArchiveService._verify_download_artifact,
                publication,
                expected_size,
                expected_digest,
                cancellation_event,
            )
        )
        try:
            while True:
                completed, _pending = await asyncio.wait(
                    {task},
                    timeout=ARCHIVE_VERIFICATION_CANCEL_POLL_SECONDS,
                )
                if completed:
                    task.result()
                    return
                await ArchiveService._raise_if_download_cancelled(cancellation_check)
        except BaseException:
            cancellation_event.set()
            while not task.done():
                try:
                    await asyncio.wait({task})
                except asyncio.CancelledError:
                    continue
            try:
                task.result()
            except Exception:
                pass
            raise

    @staticmethod
    def _verify_download_artifact(
        publication: SecurePublication,
        expected_size: int,
        expected_digest: bytes,
        cancellation_event: threading.Event,
    ) -> None:
        digest = hashlib.sha256()
        reopened_size = 0
        with publication.open_reader("rb", encoding=None) as reader:
            while True:
                if cancellation_event.is_set():
                    raise RemoteSourceCancelled("Download verification was cancelled")
                chunk = reader.read(ARCHIVE_DOWNLOAD_CHUNK_BYTES)
                if cancellation_event.is_set():
                    raise RemoteSourceCancelled("Download verification was cancelled")
                if not chunk:
                    break
                reopened_size += len(chunk)
                digest.update(chunk)
        if reopened_size != expected_size or digest.digest() != expected_digest:
            raise ValueError("The staged download changed during verification")
        if publication.verified_size() != expected_size:
            raise ValueError("The staged download size changed during verification")
