## This section contains the textual strings used in the HomeContent.py

HOME_HEADER_STRING = """
<h1>Welcome to the Stingray Explorer Dashboard</h1>
"""

WELCOME_MESSAGE_STRING = """
<div>
    <p>This dashboard is designed to provide a comprehensive toolset for X-ray astronomy data analysis. Here are the main features:</p>
    <ul>
        <li><b>Quicklook with Stingray:</b><ul><li> Don't want to dabble around too much and generate plots fast and easy, this is the way.</li></ul></li>
        <li><b>Working with Event Data:</b> 
            <ul>
                <li>Setup and creating EventList from photon arrival times</li>
                <li>Roundtrip to Astropy-compatible formats</li>
                <li>Loading and writing EventList objects</li>
                <li>Simulating EventList from Lightcurve</li>
                <li>Joining EventLists</li>
            </ul>
        </li>
        <li><b>Working with Lightcurves:</b> 
            <ul>
                <li>Creating light curves from time stamps, counts, or photon arrival times</li>
                <li>Operations including addition, subtraction, indexing, and plotting</li>
                <li>Handling Good Time Intervals (GTIs) and analyzing light curve segments</li>
            </ul>
        </li>
        <li><b>Fourier Analysis:</b> 
            <ul>
                <li>Generating Powerspectra, AveragedPowerspectra, and Cross Spectra</li>
                <li>Normalizing and re-binning power spectra</li>
                <li>Creating Dynamical Power Spectra</li>
            </ul>
        </li>
        <li><b>Cross and Autocorrelations:</b> 
            <ul>
                <li>Generating CrossCorrelation and AutoCorrelation plots</li>
            </ul>
        </li>
        <li><b>Bispectra:</b> 
            <ul>
                <li>Understanding and plotting Bispectrum</li>
            </ul>
        </li>
        <li><b>Bayesian Excess Variance:</b> 
            <ul>
                <li>Theoretical background and practical examples</li>
            </ul>
        </li>
        <li><b>Multi-taper Periodogram:</b> 
            <ul>
                <li>Creating and analyzing Multitaper objects</li>
            </ul>
        </li>
        <li><b>Lomb Scargle Spectra:</b> 
            <ul>
                <li>Generating Lomb Scargle Powerspectrum and Crossspectrum</li>
            </ul>
        </li>
    </ul>
    <p>Please use the sidebar to navigate to the different analysis tools. Each tool comes with interactive widgets to customize your analysis and generate plots on the fly.</p>
    <p>We hope you find this dashboard useful for your research!</p>
</div>
"""

FOOTER_STRING = """
    <div>
        <p>Stingray Explorer Dashboard</p>
        <p>&copy; 2021 Kartik Mandar</p>
    </div>
    """


# Tabs in Main Area of Home Page

STINGRAY_TAB_STRING = """
<h2> Stingray: Next-Generation Spectral Timing </h2>

![Stingray-logo](../assets/images/stingray_logo_minimised.png)

Stingray is a Python library designed to perform time series analysis and related tasks on astronomical light curves. It supports a range of commonly-used Fourier analysis techniques, as well as extensions for analyzing pulsar data, simulating data sets, and statistical modeling. Stingray is designed to be easy to extend and easy to incorporate into data analysis workflows and pipelines.

<h3> Features </h3>

<h4> Current Capabilities </h4>

1. **Data handling and simulation**
    - Loading event lists from FITS files (and generally good handling of OGIP-compliant missions, like RXTE/PCA, NuSTAR/FPM, XMM-Newton/EPIC, NICER/XTI)
    - Constructing light curves and time series from event data
    - Various operations on time series (e.g. addition, subtraction, joining, and truncation)
    - Simulating a light curve with a given power spectrum
    - Simulating a light curve from another light curve and a 1-d (time) or 2-d (time-energy) impulse response
    - Simulating an event list from a given light curve _and_ with a given energy spectrum
    - Good Time Interval operations
    - Filling gaps in light curves with statistically sound fake data

2. **Fourier methods**
    - Power spectra and cross spectra in Leahy, rms normalization, absolute rms, and no normalization
    - Averaged power spectra and cross spectra
    - Dynamical power spectra and cross spectra
    - Maximum likelihood fitting of periodograms/parametric models
    - (Averaged) cross spectra
    - Coherence, time lags
    - Variability-Energy spectra, like covariance spectra and lags (needs testing)
    - Covariance spectra (needs testing)
    - Bispectra (needs testing)
    - (Bayesian) quasi-periodic oscillation searches
    - Lomb-Scargle periodograms and cross spectra
    - Power Colors

3. **Other time series methods**
    - Pulsar searches with Epoch Folding, Z-test
    - Gaussian Processes for QPO studies
    - Cross-correlation functions

<h4> Future Plans </h4>

Other future additions we are currently implementing are:
- Bicoherence
- Phase-resolved spectroscopy of quasi-periodic oscillations
- Fourier-frequency-resolved spectroscopy
- Full HEASARC-compatible mission support
- Pulsar searches with Z-test
- Binary pulsar searches

<h4> Platform-specific Issues </h4>

Windows uses an internal 32-bit representation for int. This might create numerical errors when using large integer numbers (e.g., when calculating the sum of a light curve, if the lc.counts array is an integer). On Windows, we automatically convert the counts array to float. The small numerical errors should be a relatively small issue compared to the above.

<br></br>
"""

HOLOVIZ_TAB_STRING = """
<h2> High-level tools to simplify visualization in Python </h2>

![HoloViz-logo](../assets/images/holoviz_logo_minimised.png)

**HoloViz provides:**

- High-level tools that make it easier to apply Python plotting libraries to your data.
- A comprehensive tutorial showing how to use the available tools together to do a wide range of different tasks.
- Sample datasets to work with.

<h3> HoloViz-maintained libraries </h3>

HoloViz provides a set of Python packages that make visualization easier, more accurate, and more powerful:

- **Panel**: For making apps and dashboards for your plots from any supported plotting library.
- **hvPlot**: To quickly generate interactive plots from your data.
- **HoloViews**: To help you make all of your data instantly visualizable.
- **GeoViews**: To extend HoloViews for geographic data.
- **Datashader**: For rendering even the largest datasets.
- **Lumen**: To build data-driven dashboards from a simple YAML specification.
- **Param**: To create declarative user-configurable objects.
- **Colorcet**: For perceptually uniform colormaps.

<h3> Building on the SciPy/PyData/PyViz ecosystem </h3>

HoloViz tools build on the many excellent visualization tools available in the scientific Python ecosystem, allowing you to access their power conveniently and efficiently. The core tools make use of:
- **Bokeh**: For interactive plotting.
- **Matplotlib**: For publication-quality output.
- **Plotly**: For interactive 3D visualizations.

**Panel** lets you combine any of these visualizations with output from nearly any other Python plotting library, including specific support for:
- seaborn
- altair
- vega
- plotnine
- graphviz
- ggplot2
- Plus anything that can generate HTML, PNG, or SVG.

HoloViz tools and examples generally work with any Python standard data types (lists, dictionaries, etc.), plus:
- Pandas or Dask DataFrames
- NumPy, Xarray, or Dask arrays
- Including remote data from the Intake data catalog library.

They also use Dask and Numba to speed up computations along with algorithms and functions from SciPy, and support both GPUs and CPUs to make use of all your available hardware.

HoloViz tools are designed for general-purpose use but also support some domain-specific datatypes like:
- Graphs from NetworkX
- Geographic data from GeoPandas, Cartopy, and Iris.

HoloViz tools provide extensive support for Jupyter notebooks, as well as for standalone Python-backed web servers and exporting visualizations or apps as images or static HTML files.
<br/>
"""

DASHBOARD_TAB_STRING = """
<h2> Stingray Explorer </h2>

![Stingray-Explorer-logo](../assets/images/stingray_explorer_minimised.png)

This dashboard is designed to provide a comprehensive toolset for X-ray astronomy data analysis. For now the dashboard provided quicklook features like generating an EventList, loading an EvenList, and generating a lightcurve from the EventList. 

<br/>
"""

OUTPUT_BOX_STRING = """
This is the output container. It will display the output of the analysis tools.
It may contain what EventLists are made, what lightcurves are generated, what power spectra are calculated, etc. It can also be used to preview the loaded EventList. 
"""


WARNING_BOX_STRING = """
This is the warning container. It will display any warnings or errors that occur during the analysis process.
"""

HELP_BOX_STRING = """
This is the helpbox container. It will display any help or documentation for the analysis tools.
It will also have links to the documentation and tutorials for the tools.
And have a brief description of the physics behind the analysis. 
"""
