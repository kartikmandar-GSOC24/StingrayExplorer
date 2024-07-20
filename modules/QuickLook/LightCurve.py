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


# Header section
heading_input = pn.widgets.TextInput(name="Heading", value="QuickLook Light Curve")
lightcurve_header = MainHeader(heading=heading_input)


# Main Area section
tab1_content = pn.pane.Markdown("alkjd")
tab2_content = pn.pane.Markdown("aldl")
tab3_content = pn.pane.Markdown("ald")

tabs_content = {
    "adfas?": tab1_content,
    "adafs": tab2_content,
    "adfas": tab3_content,
}

lightcurve_main_area = MainArea(tabs_content=tabs_content)
