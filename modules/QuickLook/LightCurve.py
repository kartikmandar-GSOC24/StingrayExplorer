import panel as pn

from utils.DashboardClasses import (
    MainHeader,
    MainArea,
    OutputBox,
    WarningBox,
    PlotsContainer,
    HelpBox,
    Footer,
)




def create_quicklook_lightcurve_header():
    home_heading_input = pn.widgets.TextInput(
        name="Heading", value="QuickLook Light Curve"
    )
    home_subheading_input = pn.widgets.TextInput(
        name="Subheading", value=""
    )

    return MainHeader(heading=home_heading_input, subheading=home_subheading_input)