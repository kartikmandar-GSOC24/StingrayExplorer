import panel as pn
import holoviews as hv
from utils.globals import loaded_event_data
import numpy as np
import pandas as pd
import hvplot.pandas
from utils.DashboardClasses import (
    MainHeader,
    MainArea,
    OutputBox,
    WarningBox,
    PlotsContainer,
    HelpBox,
    Footer,
    WarningHandler,
)


# Create a warning handler
def create_warning_handler():
    # Create an instance of the warning handler
    warning_handler = WarningHandler()

    # Redirect warnings to the custom handler
    warnings.showwarning = warning_handler.warn

    return warning_handler


""" Header Section """


def create_quicklook_lightcurve_header():
    home_heading_input = pn.widgets.TextInput(
        name="Heading", value="QuickLook Light Curve"
    )
    home_subheading_input = pn.widgets.TextInput(name="Subheading", value="")

    return MainHeader(heading=home_heading_input, subheading=home_subheading_input)


""" Output Box Section """


def create_loadingdata_output_box(content):
    return OutputBox(output_content=content)


""" Warning Box Section """


def create_loadingdata_warning_box(content):
    return WarningBox(warning_content=content)


""" Main Area Section """

def create_lightcurve_tab(output_box_container, warning_box_container, warning_handler):
    event_list_dropdown = pn.widgets.Select(
        name="Select Event List",
        options={name: i for i, (name, event) in enumerate(loaded_event_data)},
    )

    dt_slider = pn.widgets.FloatSlider(
        name="Select dt",
        start=0.1,
        end=100,
        step=0.1,
        value=1,
    )


def create_quicklook_lightcurve_main_area(output_box, warning_box):
    warning_handler = create_warning_handler()
    tabs_content = {
        "Light Curve": create_lightcurve_tab(output_box, warning_box, warning_handler),
    }