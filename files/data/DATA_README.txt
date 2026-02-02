================================================================================
                    StingrayExplorer Sample Data Files
================================================================================

This folder contains sample X-ray astronomy event lists and light curves for
testing and demonstration purposes with StingrayExplorer.

================================================================================
                              EVENT LIST FILES
================================================================================

ni1200120106_0mpu7_cl_bary.evt.gz (2.4 GB compressed)
------------------------------------------------------------------------------
  Source:       MAXI J1820+070 (accreting stellar-mass black hole)
  Mission:      NASA NICER (Neutron star Interior Composition Explorer)
  ObsID:        1200120106
  Observation:  2018 outburst - famous for strong quasi-periodic oscillations
  Processing:   Barycentered using JPL DE 430 ephemeris
  Authors:      Matteo Bachetti, Daniela Huppenkothen
  Download:     https://zenodo.org/record/6785435
  Usage:        Official Stingray tutorial dataset
  Load with:    EventList.read("ni1200120106_0mpu7_cl_bary.evt.gz", fmt="hea")

monol_testA.evt (28 KB)
------------------------------------------------------------------------------
  Source:       Simulated/test data
  Mission:      Generic test event list
  Description:  Basic event list for unit testing and quick demos
  Load with:    EventList.read("monol_testA.evt", fmt="hea")

monol_testA_calib.evt (25 KB)
------------------------------------------------------------------------------
  Source:       Simulated/test data
  Mission:      Generic test event list
  Description:  Calibrated version of monol_testA with energy information
  Load with:    EventList.read("monol_testA_calib.evt", fmt="hea")

monol_testA_calib_unsrt.evt (25 KB)
------------------------------------------------------------------------------
  Source:       Simulated/test data
  Mission:      Generic test event list
  Description:  Unsorted calibrated event list (for testing sorting functions)
  Load with:    EventList.read("monol_testA_calib_unsrt.evt", fmt="hea")

nomission.evt (28 KB)
------------------------------------------------------------------------------
  Source:       Simulated/test data
  Mission:      None (generic format)
  Description:  Event list without mission-specific metadata
  Usage:        Testing generic event list handling
  Load with:    EventList.read("nomission.evt", fmt="hea")

xte_test.evt.gz (11 KB compressed)
------------------------------------------------------------------------------
  Source:       Test data based on RXTE format
  Mission:      RXTE (Rossi X-ray Timing Explorer)
  Description:  Small RXTE-format event list for testing
  Usage:        Testing RXTE data loading and processing
  Load with:    EventList.read("xte_test.evt.gz", fmt="hea")

xte_gx_test.evt.gz (34 KB compressed)
------------------------------------------------------------------------------
  Source:       Test data based on RXTE format
  Mission:      RXTE (Rossi X-ray Timing Explorer)
  Description:  RXTE event list, likely from a GX source observation
  Usage:        Testing RXTE data with slightly more events
  Load with:    EventList.read("xte_gx_test.evt.gz", fmt="hea")

================================================================================
                             LIGHT CURVE FILES
================================================================================

lcurveA.fits (37 KB)
------------------------------------------------------------------------------
  Type:         Pre-computed light curve
  Format:       FITS (OGIP standard)
  Description:  Sample light curve for testing light curve operations
  Load with:    Lightcurve.read("lcurveA.fits", fmt="ogip")

lcurve_new.fits (54 KB)
------------------------------------------------------------------------------
  Type:         Pre-computed light curve
  Format:       FITS (OGIP standard)
  Description:  Another sample light curve with different parameters
  Load with:    Lightcurve.read("lcurve_new.fits", fmt="ogip")

LightCurve_bexvar.fits (416 KB)
------------------------------------------------------------------------------
  Type:         Pre-computed light curve
  Format:       FITS
  Description:  Light curve for testing excess variance (bexvar) calculations
  Usage:        Testing variability and excess variance spectrum analysis
  Load with:    Lightcurve.read("LightCurve_bexvar.fits", fmt="ogip")

================================================================================
                           LOADING DATA IN PYTHON
================================================================================

Using Stingray directly:

    from stingray import EventList, Lightcurve

    # Load event list
    evt = EventList.read("files/data/monol_testA.evt", fmt="hea")
    print(f"Events: {len(evt.time)}, Time range: {evt.time.min()}-{evt.time.max()}")

    # Load light curve
    lc = Lightcurve.read("files/data/lcurveA.fits", fmt="ogip")
    print(f"Bins: {len(lc.time)}, Count rate: {lc.countrate.mean():.2f} cts/s")

Using StingrayExplorer UI:

    1. Go to "Data Ingestion" page
    2. Click "Browse Files" and select the file
    3. Choose format: "OGIP/FITS (recommended)" for .evt/.fits files
    4. Enter a name for the dataset
    5. Click "Load Event List"

================================================================================
                              DATA SOURCES
================================================================================

HEASARC (NASA):     https://heasarc.gsfc.nasa.gov
NICER Archive:      https://heasarc.gsfc.nasa.gov/docs/nicer/
Stingray Docs:      https://docs.stingray.science/
Zenodo Dataset:     https://zenodo.org/record/6785435

================================================================================
                              FILE FORMATS
================================================================================

.evt / .evt.gz    - Event list files (photon arrival times + metadata)
.fits             - FITS format (Flexible Image Transport System)
.gz               - Gzip compressed files (auto-detected by Stingray)

Format parameter for EventList.read():
  - "hea" or "ogip" : HEASARC/OGIP standard FITS event files
  - "hdf5"          : HDF5 format
  - "ascii.ecsv"    : ASCII Enhanced CSV

================================================================================
Last updated: February 2025
================================================================================
