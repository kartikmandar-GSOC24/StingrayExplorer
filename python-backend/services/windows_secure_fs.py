"""Windows NTFS primitives for native grants and secure publication.

This module is importable on every platform, but its handle-owning APIs are
available only on Windows.  Windows paths are walked one component at a time
from a retained drive-root handle.  Every prefix is opened without
``FILE_SHARE_DELETE`` and every reparse point is rejected, so later pathname
replacement cannot redirect an authorized operation.

The supported Windows boundary is deliberately narrow: absolute local paths
on fixed NTFS volumes.  UNC/device paths, alternate data streams, reparse
points, and Win32 ambiguous names are rejected rather than approximated.
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import re
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ctypes import wintypes

WINDOWS_FILE_GRANT_VERSION = "v3"

_DRIVE_RE = re.compile(r"^[A-Za-z]:$")
_RESERVED_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
    "COM¹",
    "COM²",
    "COM³",
    "LPT¹",
    "LPT²",
    "LPT³",
}
_INVALID_COMPONENT_CHARS = frozenset('<>:"|?*')

# Access masks and Win32/NT constants.
DELETE = 0x00010000
SYNCHRONIZE = 0x00100000
FILE_READ_DATA = 0x0001
FILE_LIST_DIRECTORY = 0x0001
FILE_ADD_FILE = 0x0002
FILE_ADD_SUBDIRECTORY = 0x0004
FILE_TRAVERSE = 0x0020
FILE_READ_ATTRIBUTES = 0x0080
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000

FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3

FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_HIDDEN = 0x00000002
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_NOT_CONTENT_INDEXED = 0x00002000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

FILE_DIRECTORY_FILE = 0x00000001
FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
FILE_NON_DIRECTORY_FILE = 0x00000040
FILE_OPEN_REPARSE_POINT = 0x00200000
FILE_OPEN = 0x00000001
FILE_CREATE = 0x00000002
OBJ_CASE_INSENSITIVE = 0x00000040

FILE_RENAME_INFO_CLASS = 3
FILE_DISPOSITION_INFO_CLASS = 4
FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
FILE_ID_INFO_CLASS = 18

DRIVE_FIXED = 3
DUPLICATE_SAME_ACCESS = 0x00000002
SDDL_REVISION_1 = 1

ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ALREADY_EXISTS = 183
ERROR_FILE_EXISTS = 80


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", wintypes.LPVOID),
        ("SecurityQualityOfService", wintypes.LPVOID),
    ]


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [
        ("Status", wintypes.LPVOID),
        ("Information", ctypes.c_size_t),
    ]


class _FILE_ID_128(ctypes.Structure):
    _fields_ = [("Identifier", wintypes.BYTE * 16)]


class _FILE_ID_INFO(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_ulonglong),
        ("FileId", _FILE_ID_128),
    ]


class _FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
    _fields_ = [
        ("FileAttributes", wintypes.DWORD),
        ("ReparseTag", wintypes.DWORD),
    ]


class _FILE_DISPOSITION_INFO(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOLEAN)]


class _FILE_RENAME_INFO(ctypes.Structure):
    _fields_ = [
        ("ReplaceIfExists", wintypes.BOOLEAN),
        ("RootDirectory", wintypes.HANDLE),
        ("FileNameLength", wintypes.DWORD),
        ("FileName", wintypes.WCHAR * 1),
    ]


@dataclass(frozen=True)
class WindowsFileIdentity:
    """Stable NTFS identity returned by ``FileIdInfo``."""

    volume_serial: int
    file_id: bytes

    @property
    def volume_hex(self) -> str:
        return f"{self.volume_serial:016x}"

    @property
    def file_id_hex(self) -> str:
        return self.file_id.hex()


def _validate_windows_component(component: str) -> None:
    if not component:
        raise ValueError("Windows paths cannot contain empty components")
    if component in {".", ".."}:
        raise ValueError("Windows paths cannot contain dot components")
    if "\\" in component or "/" in component:
        raise ValueError("A Windows native operation requires one path component")
    if component.endswith((" ", ".")):
        raise ValueError("Windows path components cannot end in a space or period")
    if len(component) > 255:
        raise ValueError("A Windows path component exceeds the NTFS limit")
    if any(ord(character) < 32 for character in component):
        raise ValueError("Windows paths cannot contain control characters")
    if any(character in _INVALID_COMPONENT_CHARS for character in component):
        if ":" in component:
            raise ValueError("Windows alternate data streams are not supported")
        raise ValueError("The Windows path contains a reserved character")
    # Win32 recognizes device names even before an extension and ignores
    # spaces immediately before that extension (for example ``COM1 .txt``).
    stem = component.split(".", 1)[0].rstrip(" ").upper()
    if stem in _RESERVED_STEMS:
        raise ValueError("The Windows path contains a reserved device name")


def validate_windows_path_text(file_path: str) -> None:
    """Reject Windows path forms with ambiguous or unsupported semantics."""
    if not isinstance(file_path, str) or not file_path or "\x00" in file_path:
        raise ValueError("A non-empty native Windows path is required")
    if any(ord(character) < 32 for character in file_path):
        raise ValueError("Windows paths cannot contain control characters")

    normalized_separators = file_path.replace("/", "\\")
    lowered = normalized_separators.casefold()
    if lowered.startswith(("\\\\", "\\?\\", "\\.\\", "\\??\\")):
        raise ValueError("UNC and Windows device paths are not supported")

    drive, tail = ntpath.splitdrive(normalized_separators)
    if not _DRIVE_RE.fullmatch(drive) or not tail.startswith("\\"):
        raise ValueError("An absolute local Windows drive path is required")

    components = [] if tail == "\\" else tail.split("\\")[1:]
    for component in components:
        _validate_windows_component(component)


def canonicalize_windows_path(file_path: str) -> Path:
    """Return one canonical absolute Windows path without following links."""
    validate_windows_path_text(file_path)
    normalized = ntpath.normpath(file_path.replace("/", "\\"))
    drive, tail = ntpath.splitdrive(normalized)
    canonical = f"{drive.upper()}{tail}"
    validate_windows_path_text(canonical)
    return Path(canonical)


def _handle_value(handle: Any) -> int:
    if isinstance(handle, int):
        return handle
    value = getattr(handle, "value", None)
    if value is None:
        raise OSError("Windows returned an invalid native handle")
    return int(value)


class WindowsNativeApi:
    """Small, explicitly typed wrapper around the required Windows APIs."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows native filesystem APIs are unavailable")

        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        self.kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.kernel32.CreateFileW.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetDriveTypeW.restype = wintypes.UINT
        self.kernel32.GetVolumeInformationByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        self.kernel32.GetVolumeInformationByHandleW.restype = wintypes.BOOL
        self.kernel32.GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self.kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
        self.kernel32.SetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self.kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
        self.kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self.kernel32.FlushFileBuffers.restype = wintypes.BOOL
        self.kernel32.GetFileSizeEx.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_longlong),
        ]
        self.kernel32.GetFileSizeEx.restype = wintypes.BOOL
        self.kernel32.GetCurrentProcess.argtypes = []
        self.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel32.DuplicateHandle.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel32.DuplicateHandle.restype = wintypes.BOOL
        self.kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self.kernel32.LocalFree.restype = wintypes.HLOCAL

        self.ntdll.NtCreateFile.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            ctypes.POINTER(_OBJECT_ATTRIBUTES),
            ctypes.POINTER(_IO_STATUS_BLOCK),
            ctypes.POINTER(ctypes.c_longlong),
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
        ]
        self.ntdll.NtCreateFile.restype = ctypes.c_long
        self.ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
        self.ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG

        self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.ULONG),
        ]
        self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            wintypes.BOOL
        )

    def _raise_last_error(self, message: str) -> None:
        error = ctypes.get_last_error()
        raise OSError(error, f"{message}: {ctypes.FormatError(error)}")

    def close(self, handle: int) -> None:
        if handle >= 0 and not self.kernel32.CloseHandle(wintypes.HANDLE(handle)):
            self._raise_last_error("Could not close a Windows filesystem handle")

    def open_root(self, root: str, *, writable_directory: bool = False) -> int:
        if self.kernel32.GetDriveTypeW(root) != DRIVE_FIXED:
            raise PermissionError(
                "Secure native files require a fixed local Windows volume"
            )
        desired_access = (
            FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES | SYNCHRONIZE
        )
        if writable_directory:
            desired_access |= FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY
        handle = self.kernel32.CreateFileW(
            root,
            desired_access,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        handle_value = _handle_value(handle)
        if handle_value == ctypes.c_void_p(-1).value:
            self._raise_last_error("Could not open the selected Windows volume")
        try:
            filesystem = ctypes.create_unicode_buffer(32)
            serial = wintypes.DWORD()
            maximum_component = wintypes.DWORD()
            flags = wintypes.DWORD()
            if not self.kernel32.GetVolumeInformationByHandleW(
                wintypes.HANDLE(handle_value),
                None,
                0,
                ctypes.byref(serial),
                ctypes.byref(maximum_component),
                ctypes.byref(flags),
                filesystem,
                len(filesystem),
            ):
                self._raise_last_error("Could not inspect the selected Windows volume")
            if filesystem.value.upper() != "NTFS":
                raise PermissionError(
                    "Secure native files currently require a local NTFS volume"
                )
            self.assert_not_reparse(handle_value)
        except BaseException:
            self.close(handle_value)
            raise
        return handle_value

    def open_relative(
        self,
        root_handle: int,
        name: str,
        *,
        desired_access: int,
        disposition: int,
        directory: bool | None,
        attributes: int = 0,
        security_descriptor: Any | None = None,
        share_delete: bool = False,
    ) -> int:
        _validate_windows_component(name)
        name_buffer = ctypes.create_unicode_buffer(name)
        name_bytes = len(name.encode("utf-16-le"))
        unicode_name = _UNICODE_STRING(
            Length=name_bytes,
            MaximumLength=name_bytes + ctypes.sizeof(wintypes.WCHAR),
            Buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        object_attributes = _OBJECT_ATTRIBUTES(
            Length=ctypes.sizeof(_OBJECT_ATTRIBUTES),
            RootDirectory=wintypes.HANDLE(root_handle),
            ObjectName=ctypes.pointer(unicode_name),
            Attributes=OBJ_CASE_INSENSITIVE,
            SecurityDescriptor=security_descriptor,
            SecurityQualityOfService=None,
        )
        io_status = _IO_STATUS_BLOCK()
        options = FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT
        if directory is True:
            options |= FILE_DIRECTORY_FILE
        elif directory is False:
            options |= FILE_NON_DIRECTORY_FILE
        output = wintypes.HANDLE()
        status = self.ntdll.NtCreateFile(
            ctypes.byref(output),
            desired_access,
            ctypes.byref(object_attributes),
            ctypes.byref(io_status),
            None,
            attributes,
            FILE_SHARE_READ
            | FILE_SHARE_WRITE
            | (FILE_SHARE_DELETE if share_delete else 0),
            disposition,
            options,
            None,
            0,
        )
        if status < 0:
            error = int(self.ntdll.RtlNtStatusToDosError(status))
            raise OSError(error, ctypes.FormatError(error))
        return _handle_value(output)

    def attributes(self, handle: int) -> int:
        info = _FILE_ATTRIBUTE_TAG_INFO()
        if not self.kernel32.GetFileInformationByHandleEx(
            wintypes.HANDLE(handle),
            FILE_ATTRIBUTE_TAG_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            self._raise_last_error("Could not inspect a Windows filesystem entry")
        return int(info.FileAttributes)

    def assert_not_reparse(self, handle: int) -> None:
        if self.attributes(handle) & FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError(
                "Windows reparse points, junctions, and symbolic links are not supported"
            )

    def identity(self, handle: int) -> WindowsFileIdentity:
        info = _FILE_ID_INFO()
        if not self.kernel32.GetFileInformationByHandleEx(
            wintypes.HANDLE(handle),
            FILE_ID_INFO_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            self._raise_last_error("Could not read the stable Windows file identity")
        return WindowsFileIdentity(
            volume_serial=int(info.VolumeSerialNumber),
            file_id=bytes(info.FileId.Identifier),
        )

    @contextmanager
    def private_security_descriptor(self) -> Generator[wintypes.LPVOID, None, None]:
        """Yield a protected inheritable DACL for atomic stage creation."""
        # SYSTEM, Administrators, and the object's owner retain full control.
        # OI/CI makes the same protected boundary inherit to child artifacts.
        security_descriptor = wintypes.LPVOID()
        if not self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)",
            SDDL_REVISION_1,
            ctypes.byref(security_descriptor),
            None,
        ):
            self._raise_last_error("Could not create a private staging ACL")
        try:
            yield security_descriptor
        finally:
            self.kernel32.LocalFree(security_descriptor)

    def set_disposition(self, handle: int) -> None:
        disposition = _FILE_DISPOSITION_INFO(DeleteFile=True)
        if not self.kernel32.SetFileInformationByHandle(
            wintypes.HANDLE(handle),
            FILE_DISPOSITION_INFO_CLASS,
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        ):
            self._raise_last_error("Could not remove an owned Windows staging entry")

    def flush(self, handle: int) -> None:
        if not self.kernel32.FlushFileBuffers(wintypes.HANDLE(handle)):
            self._raise_last_error("Could not flush the Windows staging artifact")

    def size(self, handle: int) -> int:
        value = ctypes.c_longlong()
        if not self.kernel32.GetFileSizeEx(
            wintypes.HANDLE(handle), ctypes.byref(value)
        ):
            self._raise_last_error("Could not inspect the Windows staging artifact")
        return int(value.value)

    def rename_no_replace(
        self,
        handle: int,
        parent_handle: int,
        filename: str,
    ) -> None:
        encoded_name = filename.encode("utf-16-le")
        buffer_size = (
            ctypes.sizeof(_FILE_RENAME_INFO)
            + len(encoded_name)
            + ctypes.sizeof(wintypes.WCHAR)
        )
        buffer = ctypes.create_string_buffer(buffer_size)
        rename_info = ctypes.cast(buffer, ctypes.POINTER(_FILE_RENAME_INFO)).contents
        rename_info.ReplaceIfExists = False
        rename_info.RootDirectory = wintypes.HANDLE(parent_handle)
        rename_info.FileNameLength = len(encoded_name)
        ctypes.memmove(
            ctypes.addressof(buffer) + _FILE_RENAME_INFO.FileName.offset,
            encoded_name,
            len(encoded_name),
        )
        if not self.kernel32.SetFileInformationByHandle(
            wintypes.HANDLE(handle),
            FILE_RENAME_INFO_CLASS,
            buffer,
            buffer_size,
        ):
            error = ctypes.get_last_error()
            if error in {ERROR_ALREADY_EXISTS, ERROR_FILE_EXISTS}:
                raise FileExistsError(error, "The export destination already exists")
            raise OSError(
                error,
                f"Could not publish the Windows artifact: {ctypes.FormatError(error)}",
            )

    def duplicate_to_fd(self, handle: int, *, writable: bool) -> int:
        import msvcrt

        process = self.kernel32.GetCurrentProcess()
        duplicate = wintypes.HANDLE()
        if not self.kernel32.DuplicateHandle(
            process,
            wintypes.HANDLE(handle),
            process,
            ctypes.byref(duplicate),
            0,
            False,
            DUPLICATE_SAME_ACCESS,
        ):
            self._raise_last_error("Could not duplicate a Windows staging handle")
        duplicate_value = _handle_value(duplicate)
        flags = os.O_BINARY | (os.O_RDWR if writable else os.O_RDONLY)
        try:
            descriptor = msvcrt.open_osfhandle(duplicate_value, flags)
        except BaseException:
            self.close(duplicate_value)
            raise
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor


class PinnedWindowsPath:
    """A reparse-free path whose complete prefix handle chain stays retained."""

    def __init__(
        self,
        path: Path,
        api: WindowsNativeApi,
        handles: list[int],
        identity: WindowsFileIdentity,
        *,
        directory: bool,
    ) -> None:
        self.path = path
        self.api = api
        self._handles = handles
        self.identity = identity
        self.directory = directory

    @property
    def handle(self) -> int:
        if not self._handles:
            raise RuntimeError("The pinned Windows path is already closed")
        return self._handles[-1]

    def close(self) -> None:
        while self._handles:
            handle = self._handles.pop()
            try:
                self.api.close(handle)
            except OSError:
                pass


@contextmanager
def pin_windows_path(
    path: Path,
    *,
    directory: bool,
    writable_directory: bool = False,
) -> Generator[PinnedWindowsPath, None, None]:
    """Open and retain every component of an existing local NTFS path."""
    canonical = canonicalize_windows_path(str(path))
    drive, tail = ntpath.splitdrive(str(canonical))
    root = f"{drive}\\"
    components = [] if tail == "\\" else tail.split("\\")[1:]
    api = WindowsNativeApi()
    handles: list[int] = []
    try:
        root_handle = api.open_root(
            root,
            writable_directory=writable_directory and not components,
        )
        handles.append(root_handle)
        api.assert_not_reparse(root_handle)
        current = root_handle
        for index, component in enumerate(components):
            is_final = index == len(components) - 1
            component_is_directory = directory or not is_final
            access = FILE_READ_ATTRIBUTES | SYNCHRONIZE
            if component_is_directory:
                access |= FILE_LIST_DIRECTORY | FILE_TRAVERSE
                if is_final and writable_directory:
                    access |= FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY
            else:
                access |= FILE_READ_DATA
            opened = api.open_relative(
                current,
                component,
                desired_access=access,
                disposition=FILE_OPEN,
                directory=component_is_directory,
            )
            handles.append(opened)
            api.assert_not_reparse(opened)
            current = opened
        attributes = api.attributes(current)
        if directory != bool(attributes & FILE_ATTRIBUTE_DIRECTORY):
            raise PermissionError("The selected Windows path type changed")
        pinned = PinnedWindowsPath(
            canonical,
            api,
            handles,
            api.identity(current),
            directory=directory,
        )
        handles = []
        try:
            yield pinned
        finally:
            pinned.close()
    finally:
        while handles:
            try:
                api.close(handles.pop())
            except OSError:
                pass


class WindowsPublicationReservation:
    """Handle-owned private NTFS staging and no-replacement publication."""

    def __init__(self, parent: PinnedWindowsPath, filename: str) -> None:
        self.parent = parent
        self.api = parent.api
        self.filename = filename
        self.stage_handle = -1
        self.stage_name: str | None = None
        self.artifact_handle = -1
        self.artifact_name: str | None = None
        self.artifact_identity: WindowsFileIdentity | None = None
        self.published = False

    def assert_destination_available(self) -> None:
        try:
            existing = self.api.open_relative(
                self.parent.handle,
                self.filename,
                desired_access=FILE_READ_ATTRIBUTES | SYNCHRONIZE,
                disposition=FILE_OPEN,
                directory=None,
            )
        except OSError as exc:
            if exc.errno in {ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND}:
                return
            raise
        try:
            raise FileExistsError(f"Destination already exists: {self.filename}")
        finally:
            self.api.close(existing)

    def reserve(self, extension: str) -> None:
        if self.stage_handle >= 0:
            raise RuntimeError("A Windows staging artifact is already reserved")
        try:
            with self.api.private_security_descriptor() as private_descriptor:
                for _ in range(10):
                    candidate = f".stingray-export-{secrets.token_hex(16)}"
                    try:
                        stage_handle = self.api.open_relative(
                            self.parent.handle,
                            candidate,
                            desired_access=FILE_LIST_DIRECTORY
                            | FILE_ADD_FILE
                            | FILE_ADD_SUBDIRECTORY
                            | FILE_TRAVERSE
                            | FILE_READ_ATTRIBUTES
                            | DELETE
                            | SYNCHRONIZE,
                            disposition=FILE_CREATE,
                            directory=True,
                            attributes=FILE_ATTRIBUTE_HIDDEN
                            | FILE_ATTRIBUTE_NOT_CONTENT_INDEXED,
                            security_descriptor=private_descriptor,
                        )
                    except OSError as exc:
                        if exc.errno in {ERROR_ALREADY_EXISTS, ERROR_FILE_EXISTS}:
                            continue
                        raise
                    self.stage_handle = stage_handle
                    self.stage_name = candidate
                    break
                else:
                    raise FileExistsError(
                        "Could not reserve a private Windows staging area"
                    )

                self.api.assert_not_reparse(self.stage_handle)
                self.artifact_name = f"artifact{extension}"
                self.artifact_handle = self.api.open_relative(
                    self.stage_handle,
                    self.artifact_name,
                    desired_access=GENERIC_READ
                    | GENERIC_WRITE
                    | FILE_READ_ATTRIBUTES
                    | DELETE
                    | SYNCHRONIZE,
                    disposition=FILE_CREATE,
                    directory=False,
                    attributes=FILE_ATTRIBUTE_NOT_CONTENT_INDEXED,
                    security_descriptor=private_descriptor,
                )
            self.api.assert_not_reparse(self.artifact_handle)
            self.artifact_identity = self.api.identity(self.artifact_handle)
        except BaseException:
            self.close()
            raise

    def duplicate_fd(self, *, writable: bool) -> int:
        if self.artifact_handle < 0 or self.artifact_identity is None:
            raise RuntimeError("No Windows staging artifact is reserved")
        if self.api.identity(self.artifact_handle) != self.artifact_identity:
            raise PermissionError("The Windows staging artifact identity changed")
        return self.api.duplicate_to_fd(self.artifact_handle, writable=writable)

    def flush(self) -> None:
        if self.artifact_handle < 0:
            raise RuntimeError("No Windows staging artifact is reserved")
        self.api.flush(self.artifact_handle)

    def verified_size(self) -> int:
        if self.artifact_handle < 0 or self.artifact_identity is None:
            raise RuntimeError("No Windows staging artifact is reserved")
        if self.api.identity(self.artifact_handle) != self.artifact_identity:
            raise PermissionError("The Windows staging artifact identity changed")
        return self.api.size(self.artifact_handle)

    def publish(self) -> list[str]:
        if self.artifact_handle < 0 or self.artifact_identity is None:
            raise RuntimeError("No Windows staging artifact is reserved")
        self.api.rename_no_replace(
            self.artifact_handle,
            self.parent.handle,
            self.filename,
        )
        # The namespace transition has occurred. Never delete this handle in a
        # later failure path: it now denotes the user's published artifact.
        self.published = True
        final_handle = -1
        try:
            final_handle = self.api.open_relative(
                self.parent.handle,
                self.filename,
                desired_access=FILE_READ_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
                disposition=FILE_OPEN,
                directory=False,
                share_delete=True,
            )
            self.api.assert_not_reparse(final_handle)
            if self.api.identity(final_handle) != self.artifact_identity:
                raise PermissionError(
                    "The Windows export destination changed during publication"
                )
        finally:
            if final_handle >= 0:
                self.api.close(final_handle)

        warnings: list[str] = []
        try:
            self._close_artifact(delete=False)
            self._close_stage(delete=True)
        except OSError as cleanup_error:
            warnings.append(
                "Export succeeded, but its private Windows staging directory "
                f"could not be removed ({cleanup_error})."
            )
        return warnings

    def _close_artifact(self, *, delete: bool) -> None:
        if self.artifact_handle < 0:
            return
        handle = self.artifact_handle
        self.artifact_handle = -1
        try:
            if delete:
                self.api.set_disposition(handle)
        finally:
            self.api.close(handle)

    def _close_stage(self, *, delete: bool) -> None:
        if self.stage_handle < 0:
            return
        handle = self.stage_handle
        self.stage_handle = -1
        try:
            if delete:
                self.api.set_disposition(handle)
        finally:
            self.api.close(handle)

    def close(self) -> None:
        try:
            self._close_artifact(delete=not self.published)
        except OSError:
            pass
        try:
            self._close_stage(delete=True)
        except OSError:
            pass
