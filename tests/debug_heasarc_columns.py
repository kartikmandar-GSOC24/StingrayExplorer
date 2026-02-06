#!/usr/bin/env python
"""
Debug script to discover actual HEASARC column names for each mission.
Run: python tests/debug_heasarc_columns.py
"""

from astroquery.heasarc import Heasarc
from astropy.coordinates import SkyCoord
from astropy import units as u

MISSIONS = {
    "NICER": "nicermastr",
    "NuSTAR": "numaster",
    "XMM-Newton": "xmmmaster",
    "Chandra": "chanmaster",
    "Swift": "swiftmastr",
    "RXTE": "xtemaster",
}

def discover_columns(source_name: str = "Crab"):
    """Query each mission and print column names."""
    coords = SkyCoord.from_name(source_name)
    print(f"Testing with source: {source_name}")
    print(f"Resolved coordinates: RA={coords.ra.deg:.4f}, Dec={coords.dec.deg:.4f}")
    print("=" * 80)

    for mission, catalog in MISSIONS.items():
        print(f"\n{'='*40}")
        print(f"MISSION: {mission} (catalog: {catalog})")
        print("=" * 40)

        try:
            table = Heasarc.query_region(
                coords,
                catalog=catalog,
                radius=0.5 * u.deg,
            )

            if table is None or len(table) == 0:
                print("  No results found")
                continue

            print(f"  Results: {len(table)} rows")
            print(f"  Columns: {table.colnames}")
            print()

            # Show first row values
            if len(table) > 0:
                print("  First row values:")
                row = table[0]
                for col in table.colnames:
                    val = row[col]
                    print(f"    {col}: {val}")

        except Exception as e:
            print(f"  ERROR: {e}")

if __name__ == "__main__":
    discover_columns("Crab")
    print("\n\n")
    discover_columns("Cyg X-1")
