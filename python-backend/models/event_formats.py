"""Authoritative format policy for legacy EventList ingestion and saving."""

from typing import Any, Final, Literal, cast, get_args


# Keep this allowlist intentionally narrow. Stingray also exposes a pickle
# reader, plus a broad Astropy registry, but neither is an acceptable API
# surface for renderer-controlled input. ``hea`` is a historical spelling
# accepted only at the boundary and immediately normalized to ``ogip``.
InputEventFormat = Literal[
    "ogip",
    "hea",
    "fits",
    "hdf5",
    "ascii.ecsv",
]
OutputEventFormat = Literal["hdf5", "ascii.ecsv"]

INPUT_EVENT_FORMATS: Final[frozenset[str]] = frozenset(
    cast(tuple[str, ...], get_args(InputEventFormat))
)
CANONICAL_INPUT_EVENT_FORMATS: Final[frozenset[str]] = frozenset(
    INPUT_EVENT_FORMATS - {"hea"}
)
OUTPUT_EVENT_FORMATS: Final[frozenset[str]] = frozenset(
    cast(tuple[str, ...], get_args(OutputEventFormat))
)


def require_input_event_format(fmt: Any) -> InputEventFormat:
    """Return an exact supported input format or fail before any I/O."""
    if not isinstance(fmt, str) or fmt not in INPUT_EVENT_FORMATS:
        supported = ", ".join(sorted(INPUT_EVENT_FORMATS))
        raise ValueError(
            f"Unsupported input EventList format {fmt!r}. "
            f"Supported formats: {supported}"
        )
    if fmt == "hea":
        return "ogip"
    return cast(InputEventFormat, fmt)


def require_output_event_format(fmt: Any) -> OutputEventFormat:
    """Return an exact supported output format or fail before any I/O."""
    if not isinstance(fmt, str) or fmt not in OUTPUT_EVENT_FORMATS:
        supported = ", ".join(sorted(OUTPUT_EVENT_FORMATS))
        raise ValueError(
            f"Unsupported output EventList format {fmt!r}. "
            f"Supported formats: {supported}"
        )
    return cast(OutputEventFormat, fmt)


def require_batch_input_formats(
    files: list[dict[str, Any]], shared_fmt: Any
) -> tuple[list[dict[str, Any]], InputEventFormat]:
    """Validate every supplied batch format before scheduling or path access."""
    validated_shared = require_input_event_format(shared_fmt)
    validated_files: list[dict[str, Any]] = []
    for index, file_config in enumerate(files):
        validated_config = dict(file_config)
        if "fmt" in validated_config:
            try:
                validated_config["fmt"] = require_input_event_format(
                    validated_config["fmt"]
                )
            except ValueError as exc:
                raise ValueError(f"files[{index}].fmt: {exc}") from exc
        validated_files.append(validated_config)
    return validated_files, validated_shared
