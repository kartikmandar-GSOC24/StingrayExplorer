import panel as pn
import param
from typing import List, Tuple


class MainHeader(pn.viewable.Viewer):
    """
    MainHeader class represents the header section of the dashboard.
    It includes a heading, subheading, and a series of buttons with configurable actions.
    """

    # Parameters for the header and subheading text
    heading: str = param.String(
        default="Default Heading", doc="The heading text", allow_refs=True
    )
    subheading: str = param.String(
        default="Default Subheading", doc="The subheading text", allow_refs=True
    )

    # Parameters for the names of up to 12 buttons
    button_1_name: str = param.String(
        default="Button 1", doc="Name for Button 1", allow_refs=True
    )
    button_2_name: str = param.String(
        default="Button 2", doc="Name for Button 2", allow_refs=True
    )
    button_3_name: str = param.String(
        default="Button 3", doc="Name for Button 3", allow_refs=True
    )
    button_4_name: str = param.String(
        default="Button 4", doc="Name for Button 4", allow_refs=True
    )
    button_5_name: str = param.String(
        default="Button 5", doc="Name for Button 5", allow_refs=True
    )
    button_6_name: str = param.String(
        default="Button 6", doc="Name for Button 6", allow_refs=True
    )
    button_7_name: str = param.String(
        default="Button 7", doc="Name for Button 7", allow_refs=True
    )
    button_8_name: str = param.String(
        default="Button 8", doc="Name for Button 8", allow_refs=True
    )
    button_9_name: str = param.String(
        default="Button 9", doc="Name for Button 9", allow_refs=True
    )
    button_10_name: str = param.String(
        default="Button 10", doc="Name for Button 10", allow_refs=True
    )
    button_11_name: str = param.String(
        default="Button 11", doc="Name for Button 11", allow_refs=True
    )
    button_12_name: str = param.String(
        default="Button 12", doc="Name for Button 12", allow_refs=True
    )

    # Parameters for the actions associated with each button
    button_1_action = param.Parameter(doc="Action for Button 1")
    button_2_action = param.Parameter(doc="Action for Button 2")
    button_3_action = param.Parameter(doc="Action for Button 3")
    button_4_action = param.Parameter(doc="Action for Button 4")
    button_5_action = param.Parameter(doc="Action for Button 5")
    button_6_action = param.Parameter(doc="Action for Button 6")
    button_7_action = param.Parameter(doc="Action for Button 7")
    button_8_action = param.Parameter(doc="Action for Button 8")
    button_9_action = param.Parameter(doc="Action for Button 9")
    button_10_action = param.Parameter(doc="Action for Button 10")
    button_11_action = param.Parameter(doc="Action for Button 11")
    button_12_action = param.Parameter(doc="Action for Button 12")

    def __init__(self, **params):
        """
        Initializes the MainHeader class with the provided parameters.
        """
        super().__init__(**params)

    def __panel__(self):
        """
        Returns the Panel layout for the header, including the heading, subheading, and buttons.
        """
        # Create HTML panes for heading and subheading
        heading_pane = pn.pane.HTML(
            pn.bind(lambda heading: f"<h1>{heading}</h1>", self.param.heading)
        )

        subheading_pane = pn.pane.HTML(
            pn.bind(lambda subheading: f"<h4>{subheading}</h4>", self.param.subheading)
        )

        # Create buttons based on the provided names and actions
        buttons = []
        if self.button_1_name and self.button_1_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_1_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_1_action,
                )
            )
        if self.button_2_name and self.button_2_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_2_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_2_action,
                )
            )
        if self.button_3_name and self.button_3_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_3_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_3_action,
                )
            )
        if self.button_4_name and self.button_4_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_4_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_4_action,
                )
            )
        if self.button_5_name and self.button_5_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_5_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_5_action,
                )
            )
        if self.button_6_name and self.button_6_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_6_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_6_action,
                )
            )
        if self.button_7_name and self.button_7_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_7_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_7_action,
                )
            )
        if self.button_8_name and self.button_8_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_8_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_8_action,
                )
            )
        if self.button_9_name and self.button_9_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_9_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_9_action,
                )
            )
        if self.button_10_name and self.button_10_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_10_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_10_action,
                )
            )
        if self.button_11_name and self.button_11_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_11_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_11_action,
                )
            )
        if self.button_12_name and self.button_12_action:
            buttons.append(
                pn.widgets.Button(
                    name=self.button_12_name,
                    button_type="primary",
                    width=70,
                    height=30,
                    margin=(5, 5),
                    on_click=self.button_12_action,
                )
            )

        # Create the layout for the header
        layout_items = [heading_pane]
        if self.subheading and self.subheading != "Default Subheading":
            layout_items.append(subheading_pane)

        # Create the layout for the header
        layout = pn.Row(
            pn.Column(*layout_items),
            pn.FlexBox(
                *buttons,
                align_items="center",
                justify_content="end",
                flex_wrap="wrap",
            ),
        )

        return layout


class MainArea(pn.viewable.Viewer):
    """
    MainArea class represents the main content area of the dashboard, containing multiple tabs.
    """

    # Parameter for the content of the tabs, as a dictionary with tab names as keys and content as values
    tabs_content: dict = param.Dict(
        default={},
        doc="Dictionary with tab names as keys and content as values",
        allow_refs=True,
    )

    def __init__(self, **params):
        """
        Initializes the MainArea class with the provided parameters.
        """
        super().__init__(**params)

    def __panel__(self):
        """
        Returns the Panel layout for the main area, which includes tabs with their respective content.
        """
        tabs = pn.Tabs(dynamic=True)
        for tab_name, content in self.tabs_content.items():
            tabs.append((tab_name, content))

        flexbox_layout = pn.FlexBox(
            tabs,
            sizing_mode="stretch_both",
            align_items="stretch",
            justify_content="space-between",
        )
        return flexbox_layout


class OutputBox(pn.viewable.Viewer):
    """
    OutputBox class represents a box to display output content.
    """

    # Parameter for the content to display in the output box
    output_content: str = param.String(
        default="", doc="Content to display in the output box", allow_refs=True
    )

    def __init__(self, **params):
        """
        Initializes the OutputBox class with the provided parameters.
        """
        super().__init__(**params)

    def __panel__(self):
        """
        Returns the Panel layout for the output box, including a heading and the content.
        """
        heading = pn.pane.Markdown("<h2> Output </h2>")
        output_box = pn.widgets.TextAreaInput(
            name="",
            value=self.output_content,
            disabled=True,
            min_height=220,
            sizing_mode="stretch_both",
        )
        return pn.Column(heading, output_box, sizing_mode="stretch_both")


class WarningBox(pn.viewable.Viewer):
    """
    WarningBox class represents a box to display warning content.
    """

    # Parameter for the content to display in the warning box
    warning_content: str = param.String(
        default="", doc="Content to display in the warning box", allow_refs=True
    )

    def __init__(self, **params):
        """
        Initializes the WarningBox class with the provided parameters.
        """
        super().__init__(**params)

    def __panel__(self):
        """
        Returns the Panel layout for the warning box, including a heading and the content.
        """
        heading = pn.pane.Markdown("<h2> Warning</h2>")
        warning_box = pn.widgets.TextAreaInput(
            name="",
            value=self.warning_content,
            disabled=True,
            min_height=220,
            sizing_mode="stretch_both",
        )
        return pn.Column(heading, warning_box, sizing_mode="stretch_both")


class PlotsContainer(pn.viewable.Viewer):
    """
    PlotsContainer class represents a container for displaying multiple  plots.
    """

    # Parameters for the contents, titles, and sizes of the FlexBox containers
    flexbox_contents: List[pn.viewable.Viewer] = param.List(
        default=[], doc="Contents for FlexBox containers", allow_refs=True
    )
    titles: List[str] = param.List(
        default=[], doc="Titles for FlexBox containers", allow_refs=True
    )
    sizes: List[Tuple[int, int]] = param.List(
        default=[],
        doc="Sizes for FlexBox containers as (height, width)",
        allow_refs=True,
    )

    def __init__(self, **params):
        """
        Initializes thePlotsContainer class with the provided parameters.
        """
        super().__init__(**params)

    def __panel__(self):
        """
        Returns the Panel layout for the B plots container, including the plots with their respective titles and sizes.
        """
        flexbox_container = pn.FlexBox(
            align_items="center", justify_content="flex-start", flex_wrap="wrap"
        )

        for idx, content in enumerate(self.flexbox_contents):
            if idx < len(self.titles):
                title = self.titles[idx]
            else:
                title = f"FlexBox {idx+1}"

            heading = pn.pane.Markdown(f"<h2> {title} </h2>", align="center")
            flexbox = pn.Column(
                heading,
                content,
            )

            if idx < len(self.sizes):
                height, width = self.sizes[idx]
                flexbox.height = height
                flexbox.width = width
            else:
                flexbox.height = 300
                flexbox.width = 300

            flexbox_container.append(flexbox)

        return flexbox_container


class HelpBox(pn.viewable.Viewer):
    """
    HelpBox class represents a box to display help or documentation content.
    """

    # Parameters for the title and content of the help box
    title: str = param.String(
        default="Help", doc="Title for the help box", allow_refs=True
    )
    help_content: str = param.String(
        default="", doc="Markdown content for the help box", allow_refs=True
    )

    def __init__(self, **params):
        """
        Initializes the HelpBox class with the provided parameters.
        """
        super().__init__(**params)

    def __panel__(self):
        """
        Returns the Panel layout for the help box, including a heading and Markdown content.
        """
        heading = pn.pane.Markdown(f"<h2> {self.title}</h2>")
        help_markdown = pn.pane.Markdown(self.help_content, sizing_mode="stretch_both")
        return pn.Column(heading, help_markdown, sizing_mode="stretch_both")


class Footer(pn.viewable.Viewer):
    """
    Footer class represents the footer section of the dashboard.
    It includes the main content, additional links, and icon buttons.
    """

    # Parameters for the main content, additional links, and icons in the footer
    main_content: str = param.String(
        default="", doc="Main content to display in the footer", allow_refs=True
    )
    additional_links: List[str] = param.List(
        default=[], doc="List of additional links as markdown strings", allow_refs=True
    )
    icons: List[pn.viewable.Viewer] = param.List(
        default=[], doc="List of icon buttons", allow_refs=True
    )

    def __init__(self, **params):
        """
        Initializes the Footer class with the provided parameters.
        """
        super().__init__(**params)

    def __panel__(self):
        """
        Returns the Panel layout for the footer, including logo, name, links, icons, and contact information.
        """
        logo = pn.pane.PNG(
            "../assets/images/stingray_explorer.png",
            width=100,
            height=100,
            align="center",
        )
        name = pn.pane.Markdown("Stingray Explorer", align="center")

        logo_name_pane = pn.FlexBox(
            logo,
            name,
            flex_direction="column",
            justify_content="center",
            align_items="center",
        )

        links = [pn.pane.Markdown(link) for link in self.additional_links]

        links_pane = pn.FlexBox(
            *links,
            flex_direction="column",
            justify_content="center",
            align_items="center",
        )

        icons_pane = pn.FlexBox(
            *self.icons,
            flex_direction="column",
            justify_content="center",
            align_items="center",
        )

        contact_us_pane = pn.FlexBox(
            pn.pane.Markdown("Email: kartik4321mandar@gmail.com"),
            pn.pane.Markdown("Slack: @kartikmandar"),
            flex_direction="row",
            justify_content="center",
            align_items="center",
        )

        copyright_pane = pn.pane.Markdown(
            """
            &copy; 2024, Stingray. All rights reserved.
            """,
        )

        pane1 = pn.FlexBox(
            logo_name_pane,
            links_pane,
            icons_pane,
            flex_direction="row",
            justify_content="space-between",
            align_items="center",
        )

        pane2 = pn.FlexBox(
            contact_us_pane,
            flex_direction="column",
            justify_content="center",
            align_items="center",
        )

        pane3 = pn.FlexBox(
            copyright_pane,
            flex_direction="row",
            justify_content="center",
            align_items="center",
        )

        footer = pn.FlexBox(
            pane1,
            pane2,
            pane3,
            flex_direction="row",
            justify_content="center",
            align_items="center",
        )

        return footer
