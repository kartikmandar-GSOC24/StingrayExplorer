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
)
import param

""" Header Section """
home_heading_input = pn.widgets.TextInput(
    name="Heading", value="Data Ingestion and creation"
)
# home_subheading_input = pn.widgets.TextInput(name="Subheading", value="Stingray GUI using HoloViz")

loadingdata_header = MainHeader(heading=home_heading_input)


""" Main Area Section """

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


# Create an instance of the warning handler
warning_handler = WarningHandler()

# Redirect warnings to the custom handler
warnings.showwarning = warning_handler.warn

# Create instances of OutputBox and WarningBox
loadingdata_output_box = OutputBox()
loadingdata_warning_box = WarningBox()

def load_event_data(
    event,
    file_selector,
    filename_input,
    format_input,
    format_checkbox,
    loadingdata_output_box,
    loadingdata_warning_box,
):
    if not file_selector.value:
        loadingdata_output_box.output_content = "No file selected. Please select a file to upload."
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
        loadingdata_output_box.output_content = (
            "Please specify formats for all files or check the default format option."
        )
        return

    try:
        loaded_files = []
        for file_path, file_name, file_format in zip(file_paths, filenames, formats):
            if any(file_name == event[0] for event in loaded_event_data):
                loadingdata_output_box.output_content = f"A file with the name '{file_name}' already exists in memory. Please provide a different name."
                return

            event_list = EventList.read(file_path, file_format)
            loaded_event_data.append((file_name, event_list))
            loaded_files.append(
                f"File '{file_path}' loaded successfully as '{file_name}' with format '{file_format}'."
            )

        loadingdata_output_box.output_content = "\n".join(loaded_files)
        if warning_handler.warnings:
            loadingdata_warning_box.warning_content = "\n".join(warning_handler.warnings)
        else:
            loadingdata_warning_box.warning_content = "No warnings."
    except Exception as e:
        loadingdata_output_box.output_content = f"An error occurred: {e}"

    # Clear the warnings after displaying them
    warning_handler.warnings.clear()


def save_loaded_files(
    event, filename_input, format_input, format_checkbox, loadingdata_output_box, loadingdata_warning_box
):
    if not loaded_event_data:
        loadingdata_output_box.output_content = "No files loaded to save."
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
        loadingdata_output_box.output_content = "Please specify names for all loaded files."
        return
    if len(filenames) != len(loaded_event_data):
        loadingdata_output_box.output_content = (
            "Please ensure that the number of names matches the number of loaded files."
        )
        return
    if len(formats) < len(loaded_event_data):
        loadingdata_output_box.output_content = "Please specify formats for all loaded files or check the default format option."
        return

    saved_files = []
    try:
        for (loaded_name, event_list), file_name, file_format in zip(
            loaded_event_data, filenames, formats
        ):
            if os.path.exists(
                os.path.join(loaded_data_path, f"{file_name}.{file_format}")
            ):
                loadingdata_output_box.output_content = f"A file with the name '{file_name}' already exists. Please provide a different name."
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

        loadingdata_output_box.output_content = "\n".join(saved_files)
        if warning_handler.warnings:
            loadingdata_warning_box.warning_content = "\n".join(warning_handler.warnings)
        else:
            loadingdata_warning_box.warning_content = "No warnings."
    except Exception as e:
        loadingdata_output_box.output_content = f"An error occurred while saving files: {e}"

    # Clear the warnings after displaying them
    warning_handler.warnings.clear()


def delete_selected_files(event, file_selector, loadingdata_output_box, loadingdata_warning_box):
    if not file_selector.value:
        loadingdata_output_box.output_content = "No file selected. Please select a file to delete."
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

    loadingdata_output_box.output_content = "\n".join(deleted_files)
    if warning_handler.warnings:
        loadingdata_warning_box.warning_content = "\n".join(warning_handler.warnings)
    else:
        loadingdata_warning_box.warning_content = "No warnings."

    warning_handler.warnings.clear()


def preview_loaded_files(event, loadingdata_output_box, loadingdata_warning_box, time_limit=10):
    if not loaded_event_data:
        loadingdata_output_box.output_content = "No files loaded to preview."
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
        loadingdata_output_box.output_content = "\n\n".join(preview_data)
    else:
        loadingdata_output_box.output_content = "No valid files loaded for preview."

    if warning_handler.warnings:
        loadingdata_warning_box.warning_content = "\n".join(warning_handler.warnings)
    else:
        loadingdata_warning_box.warning_content = "No warnings."

    warning_handler.warnings.clear()


def create_loading_tab():
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
        loadingdata_output_box.output_content = ""
        loadingdata_warning_box.warning_content = ""
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        load_event_data(
            event,
            file_selector,
            filename_input,
            format_input,
            format_checkbox,
            loadingdata_output_box,
            loadingdata_warning_box,
        )

    def on_save_click(event):
        # Clear previous outputs and warnings
        loadingdata_output_box.output_content = ""
        loadingdata_warning_box.warning_content = ""
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        save_loaded_files(
            event, filename_input, format_input, format_checkbox, loadingdata_output_box, loadingdata_warning_box
        )

    def on_delete_click(event):
        # Clear previous outputs and warnings
        loadingdata_output_box.output_content = ""
        loadingdata_warning_box.warning_content = ""
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        delete_selected_files(event, file_selector, loadingdata_output_box, loadingdata_warning_box)

    def on_preview_click(event):
        # Clear previous outputs and warnings
        loadingdata_output_box.output_content = ""
        loadingdata_warning_box.warning_content = ""
        warning_handler.warnings.clear()
        warnings.resetwarnings()

        preview_loaded_files(event, loadingdata_output_box, loadingdata_warning_box)

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


tabs_content = {
    "Loading": create_loading_tab()
}

loadingdata_main_area = MainArea(tabs_content=tabs_content)

layout = pn.Column(loadingdata_header, loadingdata_main_area)

