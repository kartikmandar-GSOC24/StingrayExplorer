import panel as pn
from utils.strings import HOME_HEADING_STRING, WELCOME_MESSAGE_STRING, FOOTER_STRING
from modules.Home.Home import home_header, home_main_area
from utils.dashboardClasses import OutputBox, WarningBox, BokehPlotsContainer, HelpBox, Footer
from utils.sidebar import create_sidebar
from bokeh.plotting import figure  # Importing figure from Bokeh

# Initialize panel extension
pn.extension()

# Create a boolean status indicator
busy_indicator = pn.indicators.BooleanStatus(
    value=True, color="warning", width=30, height=30
)

# Create the header
header = home_header

# Create the main area
main_area = home_main_area

# Create the output box and warning box
output_box = OutputBox(output_content="This is the output content")
warning_box = WarningBox(warning_content="This is the warning content")





# Create a welcome message
welcome_message = pn.pane.HTML(
    WELCOME_MESSAGE_STRING,
    stylesheets=["../assets/stylesheets/explorer.css"],
)

# Create Bokeh plots
p1 = figure(title="Scatter Plot")
p1.scatter([1, 2, 3], [4, 5, 6])

p2 = figure(title="Line Plot")
p2.line([1, 2, 3], [4, 5, 6])

p3 = figure(title="Bar Plot")
p3.vbar(x=[1, 2, 3], top=[4, 5, 6], width=0.5)

# Create Bokeh plots container
bokeh_plots_container = BokehPlotsContainer(
    flexbox_contents=[p1, p2, p3],
    titles=["Scatter Plot", "Line Plot", "Bar Plot"],
    sizes=[(200, 200), (200, 200), (300, 300)]
)

# Create HelpBox
help_content = """
## Help Section
This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.
This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.
This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.

vThis section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.

vThis section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.vThis section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.
arkdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.vThis section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.
arkdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.vThis section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.
arkdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.vThis section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.
arkdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.This section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.vThis section provides help and documentation for using the dashboard. You can include any markdown content here to assist users.
"""
help_box = HelpBox(help_content=help_content, title="Help Section")


# Define icon buttons
icon_buttons = [
    pn.widgets.Button(name="Icon 1", button_type="default"),
    pn.widgets.Button(name="Icon 2", button_type="default"),
    pn.widgets.Button(name="Icon 3", button_type="default"),
    pn.widgets.Button(name="Icon 4", button_type="default"),
    pn.widgets.Button(name="Icon 5", button_type="default")
]

footer_content = "© 2024 Stingray. All rights reserved."
additional_links = [
    "[Privacy Policy](https://example.com)",
    "[Terms of Service](https://example.com)",
    "[Contact Us](https://example.com)",
    "[Support](https://example.com)",
    "[About Us](https://example.com)"
]

footer = Footer(
    main_content=footer_content,
    additional_links=additional_links,
    icons=icon_buttons
)

sidebar = create_sidebar(main_area, header, footer, output_box, warning_box, help_box)


# Create a FastGridTemplate layout
layout = pn.template.FastGridTemplate(
    # Basic Panel layout components
    main=[],
    header="Next-Generation Spectral Timing Made Easy",
    sidebar=[sidebar],
    modal=True,
    # Parameters for the FastGridTemplate
    site="",  # Not shown as already doing in title
    site_url="StingrayExplorer",
    logo="./assets/images/stingray_explorer.png",
    title="Stingray Explorer",
    favicon="./assets/images/stingray_explorer.png",
    # sidebar_footer="Sidebar Footer",
    # config= (TemplateConfig): Contains configuration options similar to pn.config but applied to the current Template only. (Currently only css_files is supported) But css_files are now deprecated.
    busy_indicator=busy_indicator,
    # For configuring the grid
    cols={"lg": 12, "md": 12, "sm": 12, "xs": 4, "xxs": 2},
    breakpoints={"lg": 1200, "md": 996, "sm": 768, "xs": 480, "xxs": 0},
    row_height=10,
    dimensions={"minW": 0, "maxW": float("inf"), "minH": 0, "maxH": float("inf")},
    prevent_collision=False,
    save_layout=True,
    # Styling parameter
    theme="default",
    theme_toggle=True,
    # background_color="#FFFFFF", # The toggle button choses it according to the theme
    neutral_color="#D3D3D3",
    accent_base_color="#c4e1c5",
    header_background="#000000",
    header_color="#c4e1c5",
    header_neutral_color="#D3D3D3",
    header_accent_base_color="#c4e1c5",
    corner_radius=7,
    # font="",
    # font_url="",
    shadow=True,
    main_layout="card",
    # Layout parameters
    collapsed_sidebar=False,
    sidebar_width=250,
    main_max_width="100%",
    # Meta data
    meta_description="Stingray Explorer Dashboard",
    meta_keywords="Stingray, Explorer, Dashboard, Astronomy, Stingray Explorer, X-ray Astronomy, X-ray Data Analysis",
    meta_author="Kartik Mandar",
    meta_refresh="",
    meta_viewport="width=device-width, initial-scale=1",
    base_url="/",
    base_target="_self",
)

layout.main[0:8, 0:12] = header
layout.main[8:45, 0:8] = main_area
layout.main[8:25, 8:12] = output_box
layout.main[25:45, 8:12] = warning_box
layout.main[45:85, 0:12] = bokeh_plots_container
layout.main[85:120, 0:12] = help_box
layout.main[120:150, 0:12] = footer

# Serve the layout
layout.servable()
