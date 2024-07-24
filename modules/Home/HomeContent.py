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
from utils.strings import (
    HOME_HEADER_STRING,
    HOME_WELCOME_MESSAGE_STRING,
    HOME_FOOTER_STRING,
    HOME_STINGRAY_TAB_STRING,
    HOME_HOLOVIZ_TAB_STRING,
    HOME_DASHBOARD_TAB_STRING,
    HOME_OUTPUT_BOX_STRING,
    HOME_WARNING_BOX_STRING,
    HOME_HELP_BOX_STRING,
)

""" Header Section """
def create_home_header():
    home_heading_input = pn.widgets.TextInput(
        name="Heading", value="Welcome to Stingray Explorer"
    )
    home_subheading_input = pn.widgets.TextInput(
        name="Subheading", value="Stingray GUI using HoloViz"
    )

    return MainHeader(heading=home_heading_input, subheading=home_subheading_input)

""" Main Area Section """
def create_home_main_area():
    tab1_content = pn.pane.Markdown(HOME_STINGRAY_TAB_STRING)
    tab2_content = pn.pane.Markdown(HOME_HOLOVIZ_TAB_STRING)
    tab3_content = pn.pane.Markdown(HOME_DASHBOARD_TAB_STRING)

    tabs_content = {
        "What's Stingray?": tab1_content,
        "What's HoloViz?": tab2_content,
        "Dashboard": tab3_content,
    }

    return MainArea(tabs_content=tabs_content)

""" Output Box Section """
def create_home_output_box():
    return OutputBox(output_content=HOME_OUTPUT_BOX_STRING)

""" Warning Box Section """
def create_home_warning_box():
    return WarningBox(warning_content=HOME_WARNING_BOX_STRING)

""" Plots Area Section """
def create_home_plots_area():
    p1 = pn.pane.Markdown(" Plot 1")
    p2 = pn.pane.Markdown(" Plot 2")
    p3 = pn.pane.Markdown(" Plot 3")
    p4 = pn.pane.Markdown("Plot 4")
    p5 = pn.pane.Markdown("Plot 5")

    return PlotsContainer(
        flexbox_contents=[p1, p2, p3, p4, p5],
        titles=["Heading 1", "Heading 2", "Heading 3", "Heading 4", "Heading 5"],
        sizes=[(300, 300), (300, 300), (300, 300), (300, 300), (300, 300)],
    )

""" Help Area Section """
def create_home_help_area():
    help_content = HOME_HELP_BOX_STRING
    return HelpBox(help_content=help_content, title="Help Section")

""" Footer Section """
def create_home_footer():
    icon_buttons = [
        pn.widgets.Button(name="Icon 1", button_type="default"),
        pn.widgets.Button(name="Icon 2", button_type="default"),
        pn.widgets.Button(name="Icon 3", button_type="default"),
        pn.widgets.Button(name="Icon 4", button_type="default"),
        pn.widgets.Button(name="Icon 5", button_type="default"),
    ]
    footer_content = "© 2024 Stingray. All rights reserved."
    additional_links = [
        "[Privacy Policy](https://example.com)",
        "[Terms of Service](https://example.com)",
        "[Contact Us](https://example.com)",
        "[Support](https://example.com)",
        "[About Us](https://example.com)",
    ]
    return Footer(
        main_content=footer_content,
        additional_links=additional_links,
        icons=icon_buttons,
    )
