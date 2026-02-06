"""
Archive service for HEASARC catalog queries and data downloads.

Provides functionality to search NASA's HEASARC archive for X-ray observations
and download data with progress tracking.
"""

import asyncio
import os
import re
import tempfile
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx
from astropy import units as u
from astropy.coordinates import SkyCoord
from stingray import EventList

from .base_service import BaseService


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
        obsid_cols = ["obsid", "obs_id", "observation_id", "seq_num", "sequence_number",
                      "OBSID", "OBS_ID", "OBSERVATION_ID", "SEQ_NUM", "SEQUENCE_NUMBER"]
        name_cols = ["name", "target_name", "object", "src_name", "NAME", "TARGET_NAME", "OBJECT", "SRC_NAME"]
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
                "xrt_exposure", "XRT_EXPOSURE",
                "bat_exposure", "BAT_EXPOSURE",
                "uvot_exposure", "UVOT_EXPOSURE",
                "exposure", "duration", "ontime", "livetime",
                "EXPOSURE", "DURATION", "ONTIME", "LIVETIME",
            ]
        elif catalog_name == "IXPE":
            # IXPE has per-detector-unit exposures: exposure_1, exposure_2, exposure_3
            # The main "exposure" column also exists
            exposure_cols = [
                "exposure", "exposure_1", "exposure_2", "exposure_3",
                "ontime_1", "ontime_2", "ontime_3",
                "EXPOSURE", "EXPOSURE_1", "EXPOSURE_2", "EXPOSURE_3",
            ]
        else:
            exposure_cols = [
                "exposure", "exposure_a", "duration",
                "ontime", "livetime", "good_time", "xrt_exposure",
                "EXPOSURE", "EXPOSURE_A", "DURATION",
                "ONTIME", "LIVETIME", "GOOD_TIME", "XRT_EXPOSURE",
            ]
        time_cols = ["time", "start_time", "date_obs", "tstart", "TIME", "START_TIME", "DATE_OBS", "TSTART"]

        # Get table column names once
        table_cols = set(table.colnames)

        def get_column_value(row: Any, col_names: List[str], default: Any = None) -> Any:
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
                    "exposure": _to_python_float(get_column_value(row, exposure_cols, 0)),
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
                    obs["exposure_du1"] = _to_python_float(get_column_value(row, ixpe_du1_cols))
                    obs["exposure_du2"] = _to_python_float(get_column_value(row, ixpe_du2_cols))
                    obs["exposure_du3"] = _to_python_float(get_column_value(row, ixpe_du3_cols))

                # NICER: Include processing status and number of FPMs
                if catalog_name == "NICER":
                    obs["processing_status"] = str(
                        get_column_value(row, nicer_status_cols, "")
                    )
                    obs["num_fpm"] = _to_python_int(
                        get_column_value(row, nicer_fpm_cols)
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
            for col in ["exposure", "exposure_a", "duration", "ontime",
                        "xrt_exposure", "bat_exposure"]:
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
                        (table[time_col] >= mjd_start)
                        & (table[time_col] <= mjd_end)
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
            # Import here to avoid startup delay
            from astroquery.heasarc import Heasarc

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
                table = Heasarc.query_region(
                    coords,
                    catalog=catalog_name,
                    radius=radius * u.deg,
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
            # Import here to avoid startup delay
            from astroquery.heasarc import Heasarc

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
                table = Heasarc.query_region(
                    coords,
                    catalog=catalog_name,
                    radius=radius * u.deg,
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
            from astroquery.heasarc import Heasarc

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
                tap_result = Heasarc.query_tap(adql, maxrec=10)
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

        # Base HEASARC FTP/HTTPS URL
        base_url = "https://heasarc.gsfc.nasa.gov/FTP"

        if mission == "NICER":
            # NICER data path: /nicer/data/obs/YYYY_MM/OBSID/
            # We can't know the exact date folder without more info
            # But we can construct a search URL
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dnicermastr&obsid={obsid}"

        elif mission == "NuSTAR":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dnumaster&obsid={obsid}"

        elif mission == "XMM-Newton":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dxmmmaster&obsid={obsid}"

        elif mission == "Chandra":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dchanmaster&obsid={obsid}"

        elif mission == "Swift":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dswiftmastr&obsid={obsid}"

        elif mission == "RXTE":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dxtemaster&obsid={obsid}"

        elif mission == "IXPE":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dixmaster&obsid={obsid}"

        elif mission == "Suzaku":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dsuzamaster&obsid={obsid}"

        elif mission == "ASCA":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dascamaster&obsid={obsid}"

        elif mission == "XRISM":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dxrismmastr&obsid={obsid}"

        elif mission == "Hitomi":
            urls["browse"] = f"https://heasarc.gsfc.nasa.gov/cgi-bin/W3Browse/w3browse.pl?tablehead=name%3Dhitomaster&obsid={obsid}"

        return urls

    async def _list_directory_files(self, directory_url: str) -> List[str]:
        """
        Parse HEASARC HTTPS directory listing to get file names.

        HEASARC serves directory listings as HTML pages. This method fetches
        the HTML and extracts file names from anchor tags.

        Args:
            directory_url: URL of the directory to list

        Returns:
            List of file names (not full URLs)

        Raises:
            httpx.HTTPStatusError: If the HTTP request fails
        """
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(directory_url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        files = []

        for link in soup.find_all("a"):
            href = link.get("href", "")
            # Skip navigation links (parent dir, sorting, etc.)
            if not href or href.startswith("?") or href.startswith("/"):
                continue
            # Skip subdirectories (end with /)
            if href.endswith("/"):
                continue
            # Clean up URL-encoded characters
            files.append(href)

        return files

    async def _list_directory_with_metadata(
        self, directory_url: str
    ) -> List[Dict[str, Any]]:
        """
        Parse HEASARC HTTPS directory listing to get files with metadata.

        Returns both files and subdirectories with size information when available.

        Args:
            directory_url: URL of the directory to list

        Returns:
            List of dicts with keys: name, is_directory, size_bytes (may be None)
        """
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(directory_url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        entries = []

        # HEASARC directory listings typically use <pre> format with size info
        # or standard <a> tags. Try to extract size from the text content.
        pre_content = soup.find("pre")

        if pre_content:
            # Parse Apache-style directory listing in <pre> tag
            # Format: "Name                    Last modified      Size"
            text = pre_content.get_text()
            for link in pre_content.find_all("a"):
                href = link.get("href", "")
                if not href or href.startswith("?") or href.startswith("/"):
                    continue
                if href == "../":
                    continue

                is_directory = href.endswith("/")
                name = href.rstrip("/")

                # Try to extract size from the line containing this link
                size_bytes = None
                link_text = link.get_text()
                # Find the line containing this link and extract size
                for line in text.split("\n"):
                    if link_text in line:
                        # Look for size pattern (e.g., "125M", "45K", "1.2G", "12345")
                        parts = line.split()
                        for part in parts:
                            size_bytes = self._parse_size(part)
                            if size_bytes is not None:
                                break
                        break

                entries.append({
                    "name": name,
                    "is_directory": is_directory,
                    "size_bytes": size_bytes,
                })
        else:
            # Fallback: just get names from anchor tags
            for link in soup.find_all("a"):
                href = link.get("href", "")
                if not href or href.startswith("?") or href.startswith("/"):
                    continue
                if href == "../":
                    continue

                is_directory = href.endswith("/")
                name = href.rstrip("/")

                entries.append({
                    "name": name,
                    "is_directory": is_directory,
                    "size_bytes": None,
                })

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

        # Try numeric first
        try:
            return int(size_str)
        except ValueError:
            pass

        # Try with suffix
        suffixes = {
            "K": 1024,
            "M": 1024 * 1024,
            "G": 1024 * 1024 * 1024,
            "T": 1024 * 1024 * 1024 * 1024,
        }

        for suffix, multiplier in suffixes.items():
            if size_str.upper().endswith(suffix):
                try:
                    num = float(size_str[:-1])
                    return int(num * multiplier)
                except ValueError:
                    pass

        return None

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
        for ext in ('.gz', '.bz2', '.z', '.zip'):
            if filename_lower.endswith(ext):
                filename_lower = filename_lower[:-len(ext)]
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
            # Validate mission
            if mission not in SUPPORTED_CATALOGS:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Unsupported mission: {mission}",
                    error=f"Supported missions: {list(SUPPORTED_CATALOGS.keys())}",
                )

            # Get base directory URL
            base_url = self._get_observation_directory_url(mission, obsid, obs_time, obs_data)

            if not base_url:
                # Try locate_data as fallback
                base_url = await self._locate_observation_directory(mission, obsid, obs_data)

            if not base_url:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Could not locate observation directory for {mission} {obsid}",
                    error="Directory URL construction failed. The observation time may be needed.",
                )

            # Recursively list files
            files = await self._list_files_recursive(
                base_url, mission, recursive, max_depth, 0
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

        except httpx.HTTPStatusError as e:
            return self.create_result(
                success=False,
                data=None,
                message=f"HTTP error listing directory: {e.response.status_code}",
                error=str(e),
            )
        except Exception as e:
            return self.handle_error(
                e,
                "Listing observation files",
                mission=mission,
                obsid=obsid,
            )

    async def _list_files_recursive(
        self,
        directory_url: str,
        mission: str,
        recursive: bool,
        max_depth: int,
        current_depth: int,
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
        entries = await self._list_directory_with_metadata(directory_url)
        result = []

        for entry in entries:
            name = entry["name"]
            is_directory = entry["is_directory"]
            size_bytes = entry["size_bytes"]

            full_url = directory_url.rstrip("/") + "/" + name

            if is_directory:
                children = []
                if recursive and current_depth < max_depth:
                    try:
                        children = await self._list_files_recursive(
                            full_url + "/",
                            mission,
                            recursive,
                            max_depth,
                            current_depth + 1,
                        )
                    except Exception as e:
                        # Log but don't fail if a subdirectory can't be listed
                        print(f"Could not list subdirectory {full_url}: {e}")

                result.append({
                    "path": name,
                    "name": name,
                    "is_directory": True,
                    "file_type": "directory",
                    "size_bytes": None,
                    "size_display": "",
                    "full_url": full_url + "/",
                    "children": children,
                })
            else:
                # For files, try to get size via HEAD request if not available
                if size_bytes is None:
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            head_resp = await client.head(full_url, follow_redirects=True)
                            size_bytes = int(head_resp.headers.get("content-length", 0)) or None
                    except Exception:
                        pass

                file_type = self._classify_file_type(name, mission)
                result.append({
                    "path": name,
                    "name": name,
                    "is_directory": False,
                    "file_type": file_type,
                    "size_bytes": size_bytes,
                    "size_display": self._format_size(size_bytes),
                    "full_url": full_url,
                })

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
            # NuSTAR: /nustar/data/obs/YY/Z/OBSID/
            # YY = obsid[1:3], Z = obsid[3]
            # Example: 10610025001 -> /nustar/data/obs/06/1/10610025001/
            if len(obsid) >= 4:
                return f"{base_url}/nustar/data/obs/{obsid[1:3]}/{obsid[3]}/{obsid}/"
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
        save_path: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Download a file from URL and save to local disk with progress streaming.

        This method bypasses CORS restrictions by downloading on the backend.
        Progress is streamed via SSE events.

        Args:
            url: URL to download from (e.g., HEASARC HTTPS URL)
            save_path: Local path to save the file

        Yields:
            Dict with event type and data:
            - {"type": "progress", "percent": 45, "bytes_downloaded": ..., "total_bytes": ...}
            - {"type": "complete", "file_path": "...", "size_bytes": ...}
            - {"type": "error", "error": "..."}
        """
        try:
            # Ensure the parent directory exists
            save_dir = os.path.dirname(save_path)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()

                    # Get total size from headers if available
                    total_bytes = int(response.headers.get("content-length", 0))
                    bytes_downloaded = 0

                    # Open file for writing
                    with open(save_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                            bytes_downloaded += len(chunk)

                            # Calculate progress
                            if total_bytes > 0:
                                percent = (bytes_downloaded / total_bytes) * 100
                            else:
                                percent = 0

                            yield {
                                "type": "progress",
                                "bytes_downloaded": bytes_downloaded,
                                "total_bytes": total_bytes,
                                "percent": round(percent, 1),
                            }

                            # Small yield to allow other async operations
                            await asyncio.sleep(0)

            # Get actual file size after writing
            actual_size = os.path.getsize(save_path)

            yield {
                "type": "complete",
                "file_path": save_path,
                "size_bytes": actual_size,
            }

        except httpx.HTTPStatusError as e:
            yield {
                "type": "error",
                "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
            }
        except httpx.RequestError as e:
            yield {
                "type": "error",
                "error": f"Request failed: {str(e)}",
            }
        except OSError as e:
            yield {
                "type": "error",
                "error": f"File system error: {str(e)}",
            }
        except Exception as e:
            yield {
                "type": "error",
                "error": f"Download failed: {str(e)}",
            }

    async def _locate_observation_directory(
        self,
        mission: str,
        obsid: str,
        obs_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Locate the observation directory URL using Heasarc.locate_data().

        This uses astroquery's Heasarc class to find the actual data location,
        which handles the complex directory structures of different missions.

        The correct API usage is:
        1. Query to get observation row(s) from the catalog
        2. Call locate_data(table) with the query result table

        Args:
            mission: Mission key
            obsid: Observation ID
            obs_data: Additional observation data (e.g., ra/dec for coordinate queries)

        Returns:
            Directory URL or None if not found
        """
        try:
            from astroquery.heasarc import Heasarc

            catalog_name = SUPPORTED_CATALOGS[mission]["catalog"]
            obs_data = obs_data or {}

            # Step 1: Query to get observation row
            # We need the actual table row for locate_data
            # Best approach: query by coordinates if available, then filter by obsid
            table = None

            # Try coordinate-based query if we have ra/dec
            ra = obs_data.get("ra")
            dec = obs_data.get("dec")
            if ra is not None and dec is not None:
                try:
                    coords = SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg)
                    table = Heasarc.query_region(
                        coords,
                        catalog=catalog_name,
                        radius=0.5 * u.deg,
                    )
                    print(f"Coordinate query for {mission} returned {len(table) if table else 0} results")
                except Exception as coord_err:
                    print(f"Coordinate query failed: {coord_err}")

            # Fallback: use ADQL via query_tap to find the observation by obsid
            if table is None or len(table) == 0:
                try:
                    safe_obsid = obsid.strip().replace("'", "''")
                    adql = f"SELECT * FROM {catalog_name} WHERE obsid = '{safe_obsid}'"
                    tap_result = Heasarc.query_tap(adql, maxrec=1)
                    tap_table = tap_result.to_table()
                    if tap_table is not None and len(tap_table) > 0:
                        # TAP results lack __row column, so locate_data won't work.
                        # Instead, extract time and construct URL directly.
                        time_cols = ["time", "start_time", "date_obs", "tstart"]
                        obs_time_val = None
                        for tc in time_cols:
                            if tc in tap_table.colnames:
                                obs_time_val = str(tap_table[0][tc])
                                break
                        if obs_time_val:
                            url = self._get_observation_directory_url(
                                mission, obsid, obs_time_val, obs_data
                            )
                            if url:
                                return url
                except Exception as adql_err:
                    print(f"ADQL obsid query failed: {adql_err}")
                    return None

            if table is None or len(table) == 0:
                print(f"No observations found in {catalog_name}")
                return None

            # Step 2: Filter to the specific obsid
            obsid_cols = ["obsid", "obs_id", "observation_id", "OBSID", "OBS_ID"]
            obsid_column = None
            for col in obsid_cols:
                if col in table.colnames:
                    obsid_column = col
                    break

            if obsid_column is None:
                print(f"Could not find obsid column in {catalog_name}")
                return None

            # Filter to the specific obsid
            mask = [str(row[obsid_column]).strip() == str(obsid).strip() for row in table]
            if not any(mask):
                print(f"Obsid {obsid} not found in query results")
                return None

            filtered_table = table[mask][:1]

            # Step 3: Call locate_data with the filtered table row
            try:
                result = Heasarc.locate_data(filtered_table)
            except Exception as locate_err:
                print(f"locate_data API call failed: {locate_err}")
                return None

            if result is None or len(result) == 0:
                return None

            # Step 4: Extract the access_url from the result
            # locate_data returns a table with columns: ID, access_url, sciserver, aws, etc.
            if "access_url" in result.colnames:
                for row in result:
                    url = str(row["access_url"]).strip()
                    if url and "heasarc.gsfc.nasa.gov" in url:
                        # Clean up double slashes in path (common in HEASARC URLs)
                        url = re.sub(r"([^:])//+", r"\1/", url)
                        if not url.endswith("/"):
                            url += "/"
                        return url

            # Fallback: look in any column for HEASARC URLs
            for row in result:
                for col in result.colnames:
                    val = str(row[col])
                    if "heasarc.gsfc.nasa.gov" in val and "/FTP/" in val:
                        url = val.strip()
                        url = re.sub(r"([^:])//+", r"\1/", url)
                        if not url.endswith("/"):
                            url += "/"
                        return url

            return None

        except Exception as e:
            # Log but don't fail - we'll try alternative methods
            print(f"locate_data failed for {mission}/{obsid}: {e}")
            return None
