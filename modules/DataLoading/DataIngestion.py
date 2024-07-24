# component_factories.py

import panel as pn
from stingray.events import EventList
from stingray import Lightcurve
import warnings
import os
import stat
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
)
import param


# Path to the topmost directory for loaded-data
loaded_data_path = os.path.join(os.getcwd(), "files", "loaded-data")

# Create the loaded-data directory if it doesn't exist
os.makedirs(loaded_data_path, exist_ok=True)

# Custom warning handler
class WarningHandler:
    def __init__(self):
        self.warnings = []

    def warn(
        self, message, category=None, filename=None, lineno=None, file=None, line=None
    ):
        warning_message = f"Message: {message}\nCategory: {category.__name__ if category else 'N/A'}\nFile: {filename if filename else 'N/A'}\nLine: {lineno if lineno else 'N/A'}\n"
        self.warnings.append(warning_message)


def create_warning_handler():
    # Create an instance of the warning handler
    warning_handler = WarningHandler()

    # Redirect warnings to the custom handler
    warnings.showwarning = warning_handler.warn

    return warning_handler


def create_loadingdata_header():
    home_heading_input = pn.widgets.TextInput(
        name="Heading", value="Data Ingestion and creation"
    )
    return MainHeader(heading=home_heading_input)


def create_loadingdata_output_box(content):
    return OutputBox(output_content=content)


def create_loadingdata_warning_box(content):
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
    if not file_selector.value:
        output_box_container[:] = [create_loadingdata_output_box("No file selected. Please select a file to upload.")]
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
        output_box_container[:] = [create_loadingdata_output_box("Please specify formats for all files or check the default format option.")]
        return

    try:
        loaded_files = []
        for file_path, file_name, file_format in zip(file_paths, filenames, formats):
            if any(file_name == event[0] for event in loaded_event_data):
                output_box_container[:] = [create_loadingdata_output_box(f"A file with the name '{file_name}' already exists in memory. Please provide a different name.")]
                return

            event_list = EventList.read(file_path, file_format)
            loaded_event_data.append((file_name, event_list))
            loaded_files.append(
                f"File '{file_path}' loaded successfully as '{file_name}' with format '{file_format}'."
            )
        output_box_container[:] = [create_loadingdata_output_box("\n".join(loaded_files))]
        if warning_handler.warnings:
            warning_box_container[:] = [create_loadingdata_warning_box("\n".join(warning_handler.warnings))]
        else:
            warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]
    except Exception as e:
        output_box_container[:] = [create_loadingdata_output_box(f"An error occurred: {e}")]

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
    if not loaded_event_data:
        output_box_container[:] = [create_loadingdata_output_box("No files loaded to save.")]
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
        output_box_container[:] = [create_loadingdata_output_box("Please specify names for all loaded files.")]
        return
    if len(filenames) != len(loaded_event_data):
        output_box_container[:] = [create_loadingdata_output_box("Please ensure that the number of names matches the number of loaded files.")]
        return
    if len(formats) < len(loaded_event_data):
        output_box_container[:] = [create_loadingdata_output_box("Please specify formats for all loaded files or check the default format option.")]
        return

    saved_files = []
    try:
        for (loaded_name, event_list), file_name, file_format in zip(
            loaded_event_data, filenames, formats
        ):
            if os.path.exists(
                os.path.join(loaded_data_path, f"{file_name}.{file_format}")
            ):
                output_box_container[:] = [create_loadingdata_output_box(f"A file with the name '{file_name}' already exists. Please provide a different name.")]
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

        output_box_container[:] = [create_loadingdata_output_box("\n".join(saved_files))]
        if warning_handler.warnings:
            warning_box_container[:] = [create_loadingdata_warning_box("\n".join(warning_handler.warnings))]
        else:
            warning_box_container[:] = [create_loadingtab_warning_box("No warnings.")]
    except Exception as e:
        warning_box_container[:] = [create_loadingdata_warning_box(f"An error occurred while saving files: {e}")]

    # Clear the warnings after displaying them
    warning_handler.warnings.clear()


def delete_selected_files(
    event,
    file_selector,
    output_box_container,
    warning_box_container,
    warning_handler,
):
    if not file_selector.value:
        output_box_container[:] = [create_loadingdata_output_box("No file selected. Please select a file to delete.")]
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
        warning_box_container[:] = [create_loadingdata_warning_box("\n".join(warning_handler.warnings))]
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
    if not loaded_event_data:
        output_box_container[:] = [create_loadingdata_output_box("No files loaded to preview.")]
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
        output_box_container[:] = [create_loadingdata_output_box("\n\n".join(preview_data))]
    else:
        output_box_container[:] = [create_loadingdata_output_box("No valid files loaded for preview.")]

    if warning_handler.warnings:
        warning_box_container[:] = [create_loadingdata_warning_box("\n".join(warning_handler.warnings))]
    else:
        warning_box_container[:] = [create_loadingdata_warning_box("No warnings.")]

    warning_handler.warnings.clear()


def create_loading_tab(output_box_container, warning_box_container, warning_handler):
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
        output_box_container[:] = [create_loadingdata_output_box("")]
        warning_box_container[:] = [create_loadingdata_warning_box("")]
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
        output_box_container[:] = [create_loadingdata_output_box("")]
        warning_box_container[:] = [create_loadingdata_warning_box("")]
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
        warning_box_container[:] = [create_loadingdata_warning_box("")]
        output_box_container[:] = [create_loadingdata_output_box("")]
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
        output_box_container[:] = [create_loadingdata_output_box("")]
        warning_box_container[:] = [create_loadingdata_warning_box("")]
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        preview_loaded_files(
            event, output_box_container, warning_box_container, warning_handler
        )

    load_button.on_click(on_load_click)
    save_button.on_click(on_save_click)
    delete_button.on_click(on_delete_click)
    preview_button.on_click(on_preview_click)

    first_column = pn.Column(
        pn.pane.Markdown("# Load Files"),
        file_selector,
        pn.Row(filename_input, tooltip_file),
        pn.Row(format_input, tooltip_format),
        format_checkbox,
        pn.Row(load_button, save_button, delete_button, preview_button),
        width_policy="min",
    )

    tab_content = pn.Column(
        first_column,
        width_policy="min",
    )

    return tab_content


def create_loadingdata_main_area(output_box, warning_box):
    warning_handler = create_warning_handler()
    tabs_content = {
        "Loading": create_loading_tab(
            output_box_container=output_box,
            warning_box_container=warning_box,
            warning_handler=warning_handler,
        )
    }
    return MainArea(tabs_content=tabs_content)
