#!/usr/bin/env python
"""
Debug script to verify HEASARC directory URL patterns.
Run: python tests/debug_heasarc_urls.py
"""

import httpx
import asyncio

# Test URLs based on current code patterns
TEST_URLS = {
    "NICER": [
        # Needs obs_time for YYYY_MM folder
        "https://heasarc.gsfc.nasa.gov/FTP/nicer/data/obs/",
    ],
    "NuSTAR": [
        # Pattern: /nustar/data/obs/YY/Z/OBSID/
        # For obsid 10610025001: YY=06, Z=1 (from locate_data test)
        "https://heasarc.gsfc.nasa.gov/FTP/nustar/data/obs/06/1/10610025001/",
        # For obsid 30001011002: YY=00, Z=0
        "https://heasarc.gsfc.nasa.gov/FTP/nustar/data/obs/00/0/30001011002/",
    ],
    "XMM-Newton": [
        # Pattern: /xmm/data/rev0/OBSID/
        "https://heasarc.gsfc.nasa.gov/FTP/xmm/data/rev0/0112310101/",
    ],
    "RXTE": [
        # Pattern: /rxte/data/archive/AOCYCLE/PCODE/OBSID/
        "https://heasarc.gsfc.nasa.gov/FTP/rxte/data/archive/AO1/P10257/10257-01-03-00/",
    ],
    "Chandra": [
        # Pattern: /chandra/data/byobsid/X/OBSID/ where X = last digit
        "https://heasarc.gsfc.nasa.gov/FTP/chandra/data/byobsid/8/758/",
    ],
}

async def check_url(url: str) -> tuple[str, bool, str]:
    """Check if URL is accessible."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.head(url)
            return (url, response.status_code < 400, f"HTTP {response.status_code}")
    except Exception as e:
        return (url, False, str(e))

async def main():
    """Test all URLs."""
    print("Testing HEASARC Directory URL Patterns")
    print("=" * 80)

    for mission, urls in TEST_URLS.items():
        print(f"\n{mission}:")
        for url in urls:
            _, success, status = await check_url(url)
            emoji = "✅" if success else "❌"
            print(f"  {emoji} {status}: {url}")

if __name__ == "__main__":
    asyncio.run(main())
