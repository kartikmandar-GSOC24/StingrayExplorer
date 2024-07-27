import panel as pn
from stingray.events import EventList
from stingray import Lightcurve
import warnings
import os
import stat
import numpy as np
from bokeh.models import Tooltip
from utils.globals import loaded_event_data
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
import param
from utils.strings import LOADING_DATA_HELP_BOX_STRING

# Path to the topmost directory for loaded data
loaded_data_path = os.path.join(os.getcwd(), "files", "loaded-data")

# Create the loaded-data directory if it doesn't exist
os.makedirs(loaded_data_path, exist_ok=True)


# Create a warning handler
def create_warning_handler():
    """
    Create an instance of WarningHandler and redirect warnings to this custom handler.

    Returns:
        warning_handler (WarningHandler): An instance of WarningHandler to handle warnings.
    """
    warning_handler = WarningHandler()
    warnings.showwarning = warning_handler.warn
    return warning_handler


""" Header Section """


def create_loadingdata_header(
    header_container,
    main_area_container,
    output_box_container,
    warning_box_container,
    plots_container,
    help_box_container,
    footer_container,
):
    """
    Create the header for the data loading section.

    Returns:
        MainHeader: An instance of MainHeader with the specified heading.
    """
    home_heading_input = pn.widgets.TextInput(
        name="Heading", value="Data Ingestion and creation"
    )
    return MainHeader(heading=home_heading_input)


""" Output Box Section """


def create_loadingdata_output_box(content):
    """
    Create an output box to display messages.

    Args:
        content (str): The content to be displayed in the output box.

    Returns:
        OutputBox: An instance of OutputBox with the specified content.
    """
    return OutputBox(output_content=content)


""" Warning Box Section """


def create_loadingdata_warning_box(content):
    """
    Create a warning box to display warnings.

    Args:
        content (str): The content to be displayed in the warning box.

    Returns:
        WarningBox: An instance of WarningBox with the specified content.
    """
    return WarningBox(warning_content=content)


def load_event_data(
    event,
    file_selector,
    filename_input,
    format_input,
    format_checkbox,
    output_box_container,
    warning_box_container,
    warning_handler,
):
    """
    Load event data from selected files.

    Args:
        event: The event object triggering the function.
        file_selector (FileSelector): The file selector widget.
        filename_input (TextInput): The input widget for filenames.
        format_input (TextInput): The input widget for formats.
        format_checkbox (Checkbox): The checkbox for default format.
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.
    """
    if not file_selector.value:
        output_box_container[:] = [
            create_loadingdata_output_box(
                "No file selected. Please select a file to upload."
            )
        ]
        return

    file_paths = file_selector.value
    filenames = (
        [name.strip() for name in filename_input.value.split(",")]
        if filename_input.value
        else []
    )
    formats = (
        [fmt.strip() for fmt in format_input.value.split(",")]
        if format_input.value
        else []
    )

    if format_checkbox.value:
        formats = ["ogip" for _ in range(len(file_paths))]

    if len(filenames) < len(file_paths):
        filenames.extend(
            [
                os.path.basename(path).split(".")[0]
                for path in file_paths[len(filenames) :]
            ]
        )
    if len(formats) < len(file_paths):
        output_box_container[:] = [
            create_loadingdata_output_box(
                "Please specify formats for all files or check the default format option."
            )
        ]
        return

    try:
        loaded_files = []
        for file_path, file_name, file_format in zip(file_paths, filenames, formats):
            if any(file_name == event[0] for event in loaded_event_data):
                output_box_container[:] = [
                    create_loadingdata_output_box(
                        f"A file with the name '{file_name}' already exists in memory. Please provide a different name."
                    )
                ]
                return

            event_list = EventList.read(file_path, file_format)
            loaded_event_data.append((file_name, event_list))
            loaded_files.append(
                f"File '{file_path}' loaded successfully as '{file_name}' with format '{file_format}'."
            )
        output_box_container[:] = [
            create_loadingdata_output_box("\n".join(loaded_files))
        ]
        if warning_handler.warnings:
            warning_box_container[:] = [
                create_loadingdata_warning_box("\n".join(warning_handler.warnings))
            ]
        else:
            warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]
    except Exception as e:
        output_box_container[:] = [
            create_loadingdata_output_box(f"An error occurred: {e}")
        ]

    # Clear the warnings after displaying them
    warning_handler.warnings.clear()


def save_loaded_files(
    event,
    filename_input,
    format_input,
    format_checkbox,
    output_box_container,
    warning_box_container,
    warning_handler,
):
    """
    Save loaded event data to specified file formats.

    Args:
        event: The event object triggering the function.
        filename_input (TextInput): The input widget for filenames.
        format_input (TextInput): The input widget for formats.
        format_checkbox (Checkbox): The checkbox for default format.
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.
    """
    if not loaded_event_data:
        output_box_container[:] = [
            create_loadingdata_output_box("No files loaded to save.")
        ]
        return

    filenames = (
        [name.strip() for name in filename_input.value.split(",")]
        if filename_input.value
        else [event[0] for event in loaded_event_data]
    )
    formats = (
        [fmt.strip() for fmt in format_input.value.split(",")]
        if format_input.value
        else []
    )

    if format_checkbox.value:
        formats = ["hdf5" for _ in range(len(loaded_event_data))]

    if len(filenames) < len(loaded_event_data):
        output_box_container[:] = [
            create_loadingdata_output_box("Please specify names for all loaded files.")
        ]
        return
    if len(filenames) != len(loaded_event_data):
        output_box_container[:] = [
            create_loadingdata_output_box(
                "Please ensure that the number of names matches the number of loaded files."
            )
        ]
        return
    if len(formats) < len(loaded_event_data):
        output_box_container[:] = [
            create_loadingdata_output_box(
                "Please specify formats for all loaded files or check the default format option."
            )
        ]
        return

    saved_files = []
    try:
        for (loaded_name, event_list), file_name, file_format in zip(
            loaded_event_data, filenames, formats
        ):
            if os.path.exists(
                os.path.join(loaded_data_path, f"{file_name}.{file_format}")
            ):
                output_box_container[:] = [
                    create_loadingdata_output_box(
                        f"A file with the name '{file_name}' already exists. Please provide a different name."
                    )
                ]
                return

            save_path = os.path.join(loaded_data_path, f"{file_name}.{file_format}")
            if file_format == "hdf5":
                event_list.to_astropy_table().write(
                    save_path, format=file_format, path="data"
                )
            else:
                event_list.write(save_path, file_format)

            saved_files.append(
                f"File '{file_name}' saved successfully to '{save_path}'."
            )

        output_box_container[:] = [
            create_loadingdata_output_box("\n".join(saved_files))
        ]
        if warning_handler.warnings:
            warning_box_container[:] = [
                create_loadingdata_warning_box("\n".join(warning_handler.warnings))
            ]
        else:
            warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]
    except Exception as e:
        warning_box_container[:] = [
            create_loadingdata_warning_box(f"An error occurred while saving files: {e}")
        ]

    # Clear the warnings after displaying them
    warning_handler.warnings.clear()


def delete_selected_files(
    event,
    file_selector,
    output_box_container,
    warning_box_container,
    warning_handler,
):
    """
    Delete selected files from the file system.

    Args:
        event: The event object triggering the function.
        file_selector (FileSelector): The file selector widget.
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.
    """
    if not file_selector.value:
        output_box_container[:] = [
            create_loadingdata_output_box(
                "No file selected. Please select a file to delete."
            )
        ]
        return

    file_paths = file_selector.value
    deleted_files = []
    for file_path in file_paths:
        if file_path.endswith(".py"):
            deleted_files.append(
                f"Cannot delete file '{file_path}': Deleting .py files is not allowed."
            )
            continue

        try:
            # Change the file permissions to ensure it can be deleted
            os.chmod(file_path, stat.S_IWUSR | stat.S_IREAD | stat.S_IWRITE)
            os.remove(file_path)
            deleted_files.append(f"File '{file_path}' deleted successfully.")
        except Exception as e:
            deleted_files.append(f"An error occurred while deleting '{file_path}': {e}")
    output_box_container[:] = [create_loadingdata_output_box("\n".join(deleted_files))]
    if warning_handler.warnings:
        warning_box_container[:] = [
            create_loadingdata_warning_box("\n".join(warning_handler.warnings))
        ]
    else:
        warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]

    warning_handler.warnings.clear()


def preview_loaded_files(
    event,
    output_box_container,
    warning_box_container,
    warning_handler,
    time_limit=10,
):
    """
    Preview the loaded event data files.

    Args:
        event: The event object triggering the function.
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.
        time_limit (int): The number of time entries to preview.
    """
    if not loaded_event_data:
        output_box_container[:] = [
            create_loadingdata_output_box("No files loaded to preview.")
        ]
        return

    preview_data = []
    for file_name, event_list in loaded_event_data:
        try:
            time_data = f"Times (first {time_limit}): {event_list.time[:time_limit]}"
            mjdref = f"MJDREF: {event_list.mjdref}"
            gti = f"GTI: {event_list.gti}"
            preview_data.append(f"File: {file_name}\n{time_data}\n{mjdref}\n{gti}\n")
        except Exception as e:
            warning_handler.warn(str(e), category=RuntimeWarning)

    if preview_data:
        output_box_container[:] = [
            create_loadingdata_output_box("\n\n".join(preview_data))
        ]
    else:
        output_box_container[:] = [
            create_loadingdata_output_box("No valid files loaded for preview.")
        ]

    if warning_handler.warnings:
        warning_box_container[:] = [
            create_loadingdata_warning_box("\n".join(warning_handler.warnings))
        ]
    else:
        warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]

    warning_handler.warnings.clear()


def clear_loaded_files(event, output_box_container, warning_box_container):
    """
    Clear all loaded event data files from memory.

    Args:
        event: The event object triggering the function.
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
    """
    global loaded_event_data
    if not loaded_event_data:
        output_box_container[:] = [
            create_loadingdata_output_box("No files loaded to clear.")
        ]
    else:
        loaded_event_data.clear()
        output_box_container[:] = [
            create_loadingdata_output_box("Loaded files have been cleared.")
        ]
    warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]


def create_event_list(
    event,
    times_input,
    energy_input,
    pi_input,
    gti_input,
    mjdref_input,
    name_input,
    output_box_container,
    warning_box_container,
    warning_handler,
):
    """
    Create an event list from user input.

    Args:
        event: The event object triggering the function.
        times_input (TextInput): The input widget for photon arrival times.
        energy_input (TextInput): The input widget for energy values (optional).
        pi_input (TextInput): The input widget for PI values (optional).
        gti_input (TextInput): The input widget for GTIs (optional).
        mjdref_input (TextInput): The input widget for MJDREF value.
        name_input (TextInput): The input widget for the event list name.
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.
    """
    # Clear previous warnings
    warning_handler.warnings.clear()
    warnings.resetwarnings()

    try:
        if not times_input.value or not mjdref_input.value:
            output_box_container[:] = [
                create_loadingdata_output_box(
                    "Please enter Photon Arrival Times and MJDREF."
                )
            ]
            return

        times = [float(t) for t in times_input.value.split(",")]
        mjdref = float(mjdref_input.value)
        energy = (
            [float(e) for e in energy_input.value.split(",")]
            if energy_input.value
            else None
        )
        pi = [int(p) for p in pi_input.value.split(",")] if pi_input.value else None
        gti = (
            [
                [float(g) for g in interval.split()]
                for interval in gti_input.value.split(";")
            ]
            if gti_input.value
            else None
        )

        if name_input.value:
            name = name_input.value
            if any(name == event[0] for event in loaded_event_data):
                output_box_container[:] = [
                    create_loadingdata_output_box(
                        f"A file with the name '{name}' already exists in memory. Please provide a different name."
                    )
                ]
                return
        else:
            name = f"event_list_{len(loaded_event_data)}"

        event_list = EventList(times, energy=energy, pi=pi, gti=gti, mjdref=mjdref)

        loaded_event_data.append((name, event_list))

        output_box_container[:] = [
            create_loadingdata_output_box(
                f"Event List created successfully!\nSaved as: {name}\nTimes: {event_list.time}\nMJDREF: {event_list.mjdref}\nGTI: {event_list.gti}\nEnergy: {event_list.energy if energy else 'Not provided'}\nPI: {event_list.pi if pi else 'Not provided'}"
            )
        ]
    except ValueError as ve:
        warning_handler.warn(str(ve), category=ValueError)
    except Exception as e:
        warning_handler.warn(str(e), category=RuntimeError)

    if warning_handler.warnings:
        warning_box_container[:] = [
            create_loadingdata_warning_box("\n".join(warning_handler.warnings))
        ]
    else:
        warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]

    warning_handler.warnings.clear()


def simulate_event_list(
    event,
    time_slider,
    count_slider,
    dt_input,
    name_input,
    method_selector,
    output_box_container,
    warning_box_container,
    warning_handler,
):
    """
    Simulate an event list based on user-defined parameters.

    Args:
        event: The event object triggering the function.
        time_slider (IntSlider): The slider for the number of time bins.
        count_slider (IntSlider): The slider for the maximum counts per bin.
        dt_input (FloatSlider): The slider for delta time (dt).
        name_input (TextInput): The input widget for the simulated event list name.
        method_selector (Select): The selector for the simulation method.
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.
    """
    # Clear previous warnings
    warning_handler.warnings.clear()
    warnings.resetwarnings()

    try:
        if not name_input.value:
            output_box_container[:] = [
                create_loadingdata_output_box(
                    "Please provide a name for the simulated event list."
                )
            ]
            return

        if any(name_input.value == event[0] for event in loaded_event_data):
            output_box_container[:] = [
                create_loadingdata_output_box(
                    f"A file with the name '{name_input.value}' already exists in memory. Please provide a different name."
                )
            ]
            return

        times = np.arange(time_slider.value)
        counts = np.floor(np.random.rand(time_slider.value) * count_slider.value)
        dt = dt_input.value
        lc = Lightcurve(times, counts, dt=dt, skip_checks=True)

        if method_selector.value == "Standard Method":
            event_list = EventList.from_lc(lc)
        else:
            event_list = EventList()
            event_list.simulate_times(lc)

        name = name_input.value
        loaded_event_data.append((name, event_list))

        output_box_container[:] = [
            create_loadingdata_output_box(
                f"Event List simulated successfully!\nSaved as: {name}\nTimes: {event_list.time}\nCounts: {counts}"
            )
        ]

    except Exception as e:
        warning_handler.warn(str(e), category=RuntimeError)

    if warning_handler.warnings:
        warning_box_container[:] = [
            create_loadingdata_warning_box("\n".join(warning_handler.warnings))
        ]
    else:
        warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]

    warning_handler.warnings.clear()


def create_loading_tab(output_box_container, warning_box_container, warning_handler):
    """
    Create the tab for loading event data files.

    Args:
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.

    Returns:
        tab_content (Column): A Panel Column containing the widgets and layout for the loading tab.
    """
    file_selector = pn.widgets.FileSelector(
        os.getcwd(), only_files=True, name="Select File", show_hidden=True
    )
    filename_input = pn.widgets.TextInput(
        name="Enter File Names",
        placeholder="Enter file names, comma-separated",
        width=400,
    )
    format_input = pn.widgets.TextInput(
        name="Enter Formats",
        placeholder="Enter formats (e.g., ogip, pickle, hdf5), comma-separated",
        width=400,
    )
    format_checkbox = pn.widgets.Checkbox(
        name="Use default format (ogip for loading, hdf5 for saving)", value=False
    )
    load_button = pn.widgets.Button(name="Load Event Data", button_type="primary")
    save_button = pn.widgets.Button(name="Save Loaded Data", button_type="success")
    delete_button = pn.widgets.Button(
        name="Delete Selected Files", button_type="danger"
    )
    preview_button = pn.widgets.Button(
        name="Preview Loaded Files", button_type="default"
    )
    clear_button = pn.widgets.Button(name="Clear Loaded Files", button_type="warning")

    tooltip_format = pn.widgets.TooltipIcon(
        value=Tooltip(
            content="""For HEASoft-supported missions, use 'ogip'. Using 'fits' directly might cause issues with Astropy tables. default = ogip (for reading), hdf5 (for saving)""",
            position="bottom",
        )
    )

    tooltip_file = pn.widgets.TooltipIcon(
        value=Tooltip(
            content="""Ensure the file contains at least a 'time' column.""",
            position="bottom",
        )
    )

    def on_load_click(event):
        # Clear previous outputs and warnings
        output_box_container[:] = [create_loadingdata_output_box("N.A.")]
        warning_box_container[:] = [create_loadingdata_warning_box("N.A.")]
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        load_event_data(
            event,
            file_selector,
            filename_input,
            format_input,
            format_checkbox,
            output_box_container,
            warning_box_container,
            warning_handler,
        )

    def on_save_click(event):
        # Clear previous outputs and warnings
        output_box_container[:] = [create_loadingdata_output_box("N.A.")]
        warning_box_container[:] = [create_loadingdata_warning_box("N.A.")]
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        save_loaded_files(
            event,
            filename_input,
            format_input,
            format_checkbox,
            output_box_container,
            warning_box_container,
            warning_handler,
        )

    def on_delete_click(event):
        # Clear previous outputs and warnings
        warning_box_container[:] = [create_loadingdata_warning_box("N.A.")]
        output_box_container[:] = [create_loadingdata_output_box("N.A.")]
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        delete_selected_files(
            event,
            file_selector,
            warning_box_container,
            output_box_container,
            warning_handler,
        )

    def on_preview_click(event):
        # Clear previous outputs and warnings
        output_box_container[:] = [create_loadingdata_output_box("N.A.")]
        warning_box_container[:] = [create_loadingdata_warning_box("N.A.")]
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        preview_loaded_files(
            event, output_box_container, warning_box_container, warning_handler
        )

    def on_clear_click(event):
        # Clear the loaded files list
        output_box_container[:] = [create_loadingdata_output_box("N.A.")]
        warning_box_container[:] = [create_loadingdata_warning_box("N.A.")]
        warning_handler.warnings.clear()
        warnings.resetwarnings()
        clear_loaded_files(event, output_box_container, warning_box_container)

    load_button.on_click(on_load_click)
    save_button.on_click(on_save_click)
    delete_button.on_click(on_delete_click)
    preview_button.on_click(on_preview_click)
    clear_button.on_click(on_clear_click)

    first_column = pn.Column(
        pn.pane.Markdown("# Load Files"),
        file_selector,
        pn.Row(filename_input, tooltip_file),
        pn.Row(format_input, tooltip_format),
        format_checkbox,
        pn.Row(load_button, save_button, delete_button, preview_button, clear_button),
        pn.pane.Markdown("<br/>"),
        width_policy="min",
    )

    tab_content = pn.Column(
        first_column,
        width_policy="min",
    )

    return tab_content


def create_event_list_tab(output_box_container, warning_box_container, warning_handler):
    """
    Create the tab for creating an event list.

    Args:
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.

    Returns:
        tab_content (Column): A Panel Column containing the widgets and layout for the event list creation tab.
    """
    times_input = pn.widgets.TextInput(
        name="Photon Arrival Times", placeholder="e.g., 0.5, 1.1, 2.2, 3.7"
    )
    mjdref_input = pn.widgets.TextInput(name="MJDREF", placeholder="e.g., 58000.")
    energy_input = pn.widgets.TextInput(
        name="Energy (optional)", placeholder="e.g., 0., 3., 4., 20."
    )
    pi_input = pn.widgets.TextInput(
        name="PI (optional)", placeholder="e.g., 100, 200, 300, 400"
    )
    gti_input = pn.widgets.TextInput(
        name="GTIs (optional)", placeholder="e.g., 0 4; 5 10"
    )
    name_input = pn.widgets.TextInput(
        name="Event List Name", placeholder="e.g., my_event_list"
    )
    create_button = pn.widgets.Button(name="Create Event List", button_type="primary")

    def on_create_button_click(event):
        # Clear previous output and warnings
        output_box_container.clear()
        warning_box_container.clear()
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        create_event_list(
            event,
            times_input,
            energy_input,
            pi_input,
            gti_input,
            mjdref_input,
            name_input,
            output_box_container,
            warning_box_container,
            warning_handler,
        )

    create_button.on_click(on_create_button_click)

    tab_content = pn.Column(
        pn.pane.Markdown("# Create Event List"),
        times_input,
        mjdref_input,
        energy_input,
        pi_input,
        gti_input,
        name_input,
        create_button,
    )
    return tab_content


def create_simulate_event_list_tab(
    output_box_container, warning_box_container, warning_handler
):
    """
    Create the tab for simulating event lists.

    Args:
        output_box_container (OutputBox): The container for output messages.
        warning_box_container (WarningBox): The container for warning messages.
        warning_handler (WarningHandler): The handler for warnings.

    Returns:
        tab_content (Column): A Panel Column containing the widgets and layout for the event list simulation tab.
    """
    simulation_title = pn.pane.Markdown("# Simulating Event Lists")
    time_slider = pn.widgets.IntSlider(
        name="Number of Time Bins", start=1, end=10000, value=10
    )
    count_slider = pn.widgets.IntSlider(
        name="Max Counts per Bin", start=1, end=10000, value=5
    )
    dt_input = pn.widgets.FloatSlider(
        name="Delta Time (dt)", start=0.0001, end=10000.0, step=0.001, value=1.0
    )
    method_selector = pn.widgets.Select(
        name="Method", options=["Standard Method", "Inverse CDF Method"]
    )
    sim_name_input = pn.widgets.TextInput(
        name="Simulated Event List Name", placeholder="e.g., my_sim_event_list"
    )
    simulate_button = pn.widgets.Button(
        name="Simulate Event List", button_type="primary"
    )

    def on_simulate_button_click(event):
        # Clear previous output and warnings
        output_box_container[:] = [create_loadingdata_output_box("N.A.")]
        warning_box_container[:] = [create_loadingdata_warning_box("N.A.")]
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        # Simulate the event list
        simulate_event_list(
            event,
            time_slider,
            count_slider,
            dt_input,
            sim_name_input,
            method_selector,
            output_box_container,
            warning_box_container,
            warning_handler,
        )

    simulate_button.on_click(on_simulate_button_click)

    tab_content = pn.Column(
        simulation_title,
        time_slider,
        count_slider,
        dt_input,
        method_selector,
        sim_name_input,
        simulate_button,
    )
    return tab_content


def create_loadingdata_main_area(
    header_container,
    main_area_container,
    output_box_container,
    warning_box_container,
    plots_container,
    help_box_container,
    footer_container,
):
    """
    Create the main area for the data loading tab, including all sub-tabs.

    Args:
        output_box (OutputBox): The container for output messages.
        warning_box (WarningBox): The container for warning messages.

    Returns:
        MainArea: An instance of MainArea with all the necessary tabs for data loading.
    """
    warning_handler = create_warning_handler()
    tabs_content = {
        "Load Event List": create_loading_tab(
            output_box_container=output_box_container,
            warning_box_container=warning_box_container,
            warning_handler=warning_handler,
        ),
        "Create Event List": create_event_list_tab(
            output_box_container=output_box_container,
            warning_box_container=warning_box_container,
            warning_handler=warning_handler,
        ),
        "Simulate Event List": create_simulate_event_list_tab(
            output_box_container=output_box_container,
            warning_box_container=warning_box_container,
            warning_handler=warning_handler,
        ),
    }
    return MainArea(tabs_content=tabs_content)


def create_loadingdata_help_area():
    """
    Create the help area for the data loading tab.

    Returns:
        HelpBox: An instance of HelpBox with the help content.
    """
    help_content = LOADING_DATA_HELP_BOX_STRING
    return HelpBox(help_content=help_content, title="Help Section")
