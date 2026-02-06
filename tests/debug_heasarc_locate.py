#!/usr/bin/env python
"""
Debug script to test Heasarc.locate_data() API.
Run: python tests/debug_heasarc_locate.py
"""

from astroquery.heasarc import Heasarc
from astropy.coordinates import SkyCoord
from astropy import units as u

def test_locate_data(mission: str, catalog: str, source: str = "Crab"):
    """Test locate_data with correct API."""
    print(f"\n{'='*60}")
    print(f"Testing locate_data for {mission}")
    print("=" * 60)

    try:
        # Step 1: Get coordinates
        coords = SkyCoord.from_name(source)
        print(f"Source: {source} -> RA={coords.ra.deg:.4f}, Dec={coords.dec.deg:.4f}")

        # Step 2: Query to get observation rows
        table = Heasarc.query_region(
            coords,
            catalog=catalog,
            radius=0.5 * u.deg,
        )

        if table is None or len(table) == 0:
            print("No observations found")
            return

        print(f"Found {len(table)} observations")

        # Step 3: Test locate_data with FIRST row only
        first_row = table[:1]  # Get first row as a table
        print(f"\nCalling Heasarc.locate_data(table[:1])...")

        try:
            links = Heasarc.locate_data(first_row)

            if links is None or len(links) == 0:
                print("  No links returned")
            else:
                print(f"  Links table columns: {links.colnames}")
                for row in links:
                    print(f"  - access_url: {row.get('access_url', 'N/A')}")
                    print(f"  - sciserver: {row.get('sciserver', 'N/A')}")
                    print(f"  - aws: {row.get('aws', 'N/A')}")

        except Exception as e:
            print(f"  locate_data ERROR: {e}")

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    test_locate_data("NICER", "nicermastr", "Crab")
    test_locate_data("NuSTAR", "numaster", "Crab")
    test_locate_data("XMM-Newton", "xmmmaster", "Cyg X-1")
    test_locate_data("RXTE", "xtemaster", "Crab")
    test_locate_data("Chandra", "chanmaster", "Crab")
