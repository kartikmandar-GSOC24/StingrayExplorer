"""Security boundary for fetching caller-supplied remote resources.

The application must not hand arbitrary URLs directly to ``httpx``.  This
module keeps URL validation, DNS/peer checks, redirect handling, deadlines,
and response-size limits in one reusable place.  It deliberately exposes only
redacted URLs in metadata and exceptions.
"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import math
import re
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, unquote_to_bytes, urljoin, urlsplit

import httpx

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_CHUNK_SIZE = 64 * 1024
_MAX_CHUNK_SIZE = 1024 * 1024
_MAX_REDIRECTS = 10
_MAX_REMOTE_URL_CHARS = 4_096
_MAX_DISPLAY_PATH_CHARS = 512

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[Sequence[str | IPAddress]]]
Clock = Callable[[], float]
CancellationCheck = Callable[[], bool | None | Awaitable[bool | None]]


class RemoteSourceError(Exception):
    """Base class for remote-source failures safe to show to a user."""


class RemoteSourcePolicyError(RemoteSourceError):
    """The supplied URL does not satisfy the selected remote-source policy."""


class RemoteSourceResolutionError(RemoteSourceError):
    """DNS resolution failed or produced an unsafe address."""


class RemoteSourcePeerError(RemoteSourceError):
    """The connected peer does not match the addresses validated before I/O."""


class RemoteSourceRedirectError(RemoteSourceError):
    """A redirect was missing, invalid, or exceeded the configured bound."""


class RemoteSourceHTTPError(RemoteSourceError):
    """The remote server returned a non-success status."""

    def __init__(self, status_code: int, display_url: str) -> None:
        self.status_code = status_code
        self.display_url = display_url
        super().__init__(f"Remote server returned HTTP {status_code} for {display_url}")


class RemoteSourceSizeError(RemoteSourceError):
    """A response exceeded its caller-selected byte limit."""


class RemoteSourceTimeout(RemoteSourceError):
    """A phase or total remote-source deadline expired."""


class RemoteSourceCancelled(RemoteSourceError):
    """The caller requested cancellation while consuming a response."""


@dataclass(frozen=True)
class RemoteSourcePolicy:
    """Restrictions applied to an initial URL and every redirect target."""

    name: str
    required_host: str | None = None
    required_path_prefix: str | None = None


GENERAL_HTTPS_POLICY = RemoteSourcePolicy(name="general HTTPS")
HEASARC_ARCHIVE_POLICY = RemoteSourcePolicy(
    name="HEASARC archive",
    required_host="heasarc.gsfc.nasa.gov",
    required_path_prefix="/FTP/",
)


@dataclass(frozen=True)
class RemoteTimeouts:
    """Per-phase httpx limits plus a monotonic end-to-end deadline."""

    connect: float = 10.0
    read: float = 30.0
    write: float = 10.0
    pool: float = 5.0
    total: float = 300.0

    def __post_init__(self) -> None:
        for field_name in ("connect", "read", "write", "pool", "total"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{field_name} timeout must be positive")

    def as_httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect,
            read=self.read,
            write=self.write,
            pool=self.pool,
        )


@dataclass(frozen=True)
class ValidatedRemoteURL:
    """Canonical request URL and the public addresses approved for this hop."""

    url: httpx.URL
    display_url: str
    host: str
    port: int
    addresses: frozenset[IPAddress]


@dataclass(frozen=True)
class RemoteResponseInfo:
    """Non-sensitive metadata for a successfully opened response."""

    display_url: str
    status_code: int
    content_length: int | None
    content_type: str | None
    redirect_count: int


def _has_control_characters(value: str) -> bool:
    return any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value)


def _validate_percent_encoding(value: str) -> None:
    index = 0
    while True:
        index = value.find("%", index)
        if index < 0:
            return
        if (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX_DIGITS
            or value[index + 2] not in _HEX_DIGITS
        ):
            raise RemoteSourcePolicyError(
                "Remote URL contains invalid percent encoding"
            )
        index += 3


def _validate_decoded_octets(value: str) -> None:
    try:
        decoded = unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RemoteSourcePolicyError("Remote URL is not valid UTF-8") from error
    if _has_control_characters(decoded):
        raise RemoteSourcePolicyError("Remote URL contains control characters")
    if "\\" in decoded:
        raise RemoteSourcePolicyError("Remote URL backslashes are not allowed")


def _authority_port(netloc: str) -> str | None:
    """Extract an explicit port without accepting ambiguous authority syntax."""
    if netloc.startswith("["):
        close = netloc.find("]")
        if close < 0:
            raise RemoteSourcePolicyError("Remote URL has an invalid IPv6 authority")
        suffix = netloc[close + 1 :]
        if not suffix:
            return None
        if not suffix.startswith(":"):
            raise RemoteSourcePolicyError("Remote URL has an invalid authority")
        return suffix[1:]

    if netloc.count(":") > 1:
        raise RemoteSourcePolicyError("IPv6 remote hosts must use brackets")
    if ":" not in netloc:
        return None
    return netloc.rsplit(":", 1)[1]


def _canonical_host(host: str) -> str:
    if not host or "%" in host or host.endswith("."):
        raise RemoteSourcePolicyError("Remote URL has a non-canonical host")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise RemoteSourcePolicyError("Remote URL host is invalid") from error

        if len(ascii_host) > 253 or any(
            not _HOST_LABEL.fullmatch(label) for label in ascii_host.split(".")
        ):
            raise RemoteSourcePolicyError("Remote URL host is invalid")
        return ascii_host

    return address.compressed.lower()


def _redacted_display_url(parts: Any, host: str, explicit_port: str | None) -> str:
    display_host = f"[{host}]" if ":" in host else host
    port = ":443" if explicit_port == "443" else ""
    path = parts.path or "/"
    if len(path) > _MAX_DISPLAY_PATH_CHARS:
        path = f"{path[:_MAX_DISPLAY_PATH_CHARS]}..."
    return f"https://{display_host}{port}{path}"


def redact_remote_url(value: str) -> str:
    """Return a best-effort URL display that omits userinfo, query, and fragment."""
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if not host:
            return "<remote URL>"
        canonical_host = _canonical_host(host)
        explicit_port = _authority_port(parts.netloc.rsplit("@", 1)[-1])
        if explicit_port and explicit_port != "443":
            explicit_port = None
        return _redacted_display_url(parts, canonical_host, explicit_port)
    except (RemoteSourceError, UnicodeError, ValueError):
        return "<remote URL>"


def _parse_url(
    value: str, policy: RemoteSourcePolicy
) -> tuple[httpx.URL, str, str, int]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_REMOTE_URL_CHARS
        or value != value.strip()
    ):
        raise RemoteSourcePolicyError("Remote URL must be a non-empty canonical string")
    if _has_control_characters(value):
        raise RemoteSourcePolicyError("Remote URL contains control characters")
    _validate_percent_encoding(value)
    _validate_decoded_octets(value)
    if "#" in value:
        raise RemoteSourcePolicyError("Remote URL fragments are not allowed")

    try:
        parts = urlsplit(value)
    except ValueError as error:
        raise RemoteSourcePolicyError("Remote URL is invalid") from error

    if parts.scheme.lower() != "https":
        raise RemoteSourcePolicyError("Remote URL must use HTTPS")
    if not parts.netloc:
        raise RemoteSourcePolicyError("Remote URL must include a host")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise RemoteSourcePolicyError("Remote URL credentials are not allowed")

    explicit_port = _authority_port(parts.netloc)
    if explicit_port is not None:
        if (
            not explicit_port
            or not explicit_port.isascii()
            or not explicit_port.isdigit()
        ):
            raise RemoteSourcePolicyError("Remote URL port is invalid")
        if explicit_port != str(int(explicit_port)) or explicit_port != "443":
            raise RemoteSourcePolicyError(
                "Remote URL must use canonical HTTPS port 443"
            )

    host = _canonical_host(parts.hostname or "")
    if policy.required_host is not None and host != policy.required_host:
        raise RemoteSourcePolicyError(
            f"Remote URL is outside the {policy.name} host boundary"
        )

    try:
        decoded_path = unquote_to_bytes(parts.path).decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise RemoteSourcePolicyError("Remote URL path is not valid UTF-8") from error
    if policy.required_path_prefix is not None:
        if not parts.path.startswith(
            policy.required_path_prefix
        ) or not decoded_path.startswith(policy.required_path_prefix):
            raise RemoteSourcePolicyError(
                f"Remote URL is outside the {policy.name} path boundary"
            )
        path_segments = decoded_path.split("/")
        if any(segment in {".", ".."} for segment in path_segments):
            raise RemoteSourcePolicyError("Remote URL path traversal is not allowed")

    try:
        request_url = httpx.URL(value)
    except (TypeError, ValueError) as error:
        raise RemoteSourcePolicyError("Remote URL is invalid") from error
    if (
        request_url.scheme != "https"
        or request_url.raw_host.decode("ascii") != host
        or request_url.port not in {None, 443}
    ):
        raise RemoteSourcePolicyError("Remote URL has an ambiguous authority")

    return request_url, _redacted_display_url(parts, host, explicit_port), host, 443


def _normalise_address(value: str | IPAddress) -> IPAddress:
    try:
        address = (
            value
            if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address))
            else ipaddress.ip_address(value)
        )
    except (TypeError, ValueError) as error:
        raise RemoteSourceResolutionError("DNS returned an invalid address") from error

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _address_is_unsafe(address: IPAddress) -> bool:
    return (
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


async def default_resolver(host: str, port: int) -> Sequence[str]:
    """Resolve a host without blocking the event loop."""
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(
        host,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    return tuple(record[4][0] for record in records)


async def _run_cancellation_check(check: CancellationCheck | None) -> None:
    if check is None:
        return
    result = check()
    if inspect.isawaitable(result):
        result = await result
    if result:
        raise RemoteSourceCancelled("Remote transfer was cancelled")


def _content_length(
    response: httpx.Response, max_bytes: int, display_url: str
) -> int | None:
    values = [
        token.strip()
        for value in response.headers.get_list("content-length")
        for token in value.split(",")
    ]
    if not values:
        return None
    if any(not re.fullmatch(r"[0-9]+", value) for value in values):
        raise RemoteSourceSizeError(
            f"Remote response has an invalid Content-Length for {display_url}"
        )
    if any(len(value) > 20 for value in values):
        raise RemoteSourceSizeError(
            f"Remote response exceeds the {max_bytes}-byte limit for {display_url}"
        )
    lengths = {int(value) for value in values}
    if len(lengths) != 1:
        raise RemoteSourceSizeError(
            f"Remote response has conflicting Content-Length values for {display_url}"
        )
    length = lengths.pop()
    if length > max_bytes:
        raise RemoteSourceSizeError(
            f"Remote response exceeds the {max_bytes}-byte limit for {display_url}"
        )
    return length


class RemoteByteStream:
    """One-shot, raw response body stream with deadline and byte accounting."""

    def __init__(
        self,
        response: httpx.Response,
        info: RemoteResponseInfo,
        *,
        max_bytes: int,
        chunk_size: int,
        read_timeout: float,
        deadline: float,
        clock: Clock,
        cancellation_check: CancellationCheck | None,
    ) -> None:
        self.info = info
        self.bytes_read = 0
        self._response = response
        self._max_bytes = max_bytes
        self._chunk_size = chunk_size
        self._read_timeout = read_timeout
        self._deadline = deadline
        self._clock = clock
        self._cancellation_check = cancellation_check
        self._started = False

    def _remaining(self) -> float:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise RemoteSourceTimeout(
                f"Remote transfer deadline expired for {self.info.display_url}"
            )
        return remaining

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        """Yield raw wire bytes exactly once, never content-decoded bytes."""
        if self._started:
            raise RuntimeError("Remote response body can only be consumed once")
        self._started = True

        iterator = self._response.aiter_raw(chunk_size=self._chunk_size).__aiter__()
        while True:
            await _run_cancellation_check(self._cancellation_check)
            timeout = min(self._read_timeout, self._remaining())
            try:
                chunk = await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError:
                raise RemoteSourceTimeout(
                    f"Remote read timed out for {self.info.display_url}"
                ) from None
            except httpx.TimeoutException:
                raise RemoteSourceTimeout(
                    f"Remote read timed out for {self.info.display_url}"
                ) from None
            except httpx.RequestError:
                raise RemoteSourceError(
                    f"Remote read failed for {self.info.display_url}"
                ) from None

            self._remaining()
            await _run_cancellation_check(self._cancellation_check)
            if not chunk:
                continue
            self.bytes_read += len(chunk)
            if self.bytes_read > self._max_bytes:
                raise RemoteSourceSizeError(
                    f"Remote response exceeds the {self._max_bytes}-byte limit for "
                    f"{self.info.display_url}"
                )
            yield chunk


class RemoteSourceClient:
    """Fetch remote content under a fixed URL policy."""

    def __init__(
        self,
        policy: RemoteSourcePolicy = GENERAL_HTTPS_POLICY,
        *,
        resolver: Resolver = default_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        timeouts: RemoteTimeouts | None = None,
        max_redirects: int = 5,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        clock: Clock = time.monotonic,
    ) -> None:
        if (
            not isinstance(max_redirects, int)
            or isinstance(max_redirects, bool)
            or max_redirects < 0
            or max_redirects > _MAX_REDIRECTS
        ):
            raise ValueError(f"max_redirects must be between 0 and {_MAX_REDIRECTS}")
        if (
            not isinstance(chunk_size, int)
            or isinstance(chunk_size, bool)
            or chunk_size <= 0
            or chunk_size > _MAX_CHUNK_SIZE
        ):
            raise ValueError(
                f"chunk_size must be between 1 and {_MAX_CHUNK_SIZE} bytes"
            )
        self.policy = policy
        self._resolver = resolver
        self._transport = transport
        self._timeouts = timeouts or RemoteTimeouts()
        self._max_redirects = max_redirects
        self._chunk_size = chunk_size
        self._clock = clock

    def _remaining(self, deadline: float, display_url: str) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise RemoteSourceTimeout(
                f"Remote transfer deadline expired for {display_url}"
            )
        return remaining

    async def _validate_url(self, value: str, deadline: float) -> ValidatedRemoteURL:
        request_url, display_url, host, port = _parse_url(value, self.policy)
        self._remaining(deadline, display_url)

        try:
            literal_address = _normalise_address(host)
        except RemoteSourceResolutionError:
            literal_address = None

        if literal_address is not None:
            raw_addresses: Sequence[str | IPAddress] = (literal_address,)
        else:
            try:
                raw_addresses = await asyncio.wait_for(
                    self._resolver(host, port),
                    timeout=self._remaining(deadline, display_url),
                )
            except asyncio.TimeoutError:
                raise RemoteSourceTimeout(
                    f"DNS resolution timed out for {display_url}"
                ) from None
            except (OSError, socket.gaierror):
                raise RemoteSourceResolutionError(
                    f"DNS resolution failed for {display_url}"
                ) from None

        self._remaining(deadline, display_url)
        addresses = frozenset(_normalise_address(value) for value in raw_addresses)
        if not addresses:
            raise RemoteSourceResolutionError(
                f"DNS returned no addresses for {display_url}"
            )
        if any(_address_is_unsafe(address) for address in addresses):
            raise RemoteSourceResolutionError(
                f"DNS returned a non-public address for {display_url}"
            )

        return ValidatedRemoteURL(
            url=request_url,
            display_url=display_url,
            host=host,
            port=port,
            addresses=addresses,
        )

    @staticmethod
    def _validate_peer(
        response: httpx.Response,
        validated: ValidatedRemoteURL,
        pinned_address: IPAddress,
    ) -> None:
        network_stream = response.extensions.get("network_stream")
        if network_stream is None or not hasattr(network_stream, "get_extra_info"):
            raise RemoteSourcePeerError(
                f"Connected peer identity was unavailable for {validated.display_url}"
            )

        try:
            server_address = network_stream.get_extra_info("server_addr")
        except Exception:  # noqa: BLE001 - untrusted transport metadata must fail closed
            raise RemoteSourcePeerError(
                f"Could not validate the connected peer for {validated.display_url}"
            ) from None
        if not isinstance(server_address, tuple) or len(server_address) < 2:
            raise RemoteSourcePeerError(
                f"Connected peer identity was unavailable for {validated.display_url}"
            )
        if server_address[1] != validated.port:
            raise RemoteSourcePeerError(
                f"Connected peer used an unexpected port for {validated.display_url}"
            )
        peer_value = server_address[0]
        if "%" in str(peer_value):
            raise RemoteSourcePeerError(
                f"Connected peer was invalid for {validated.display_url}"
            )
        try:
            peer = _normalise_address(str(peer_value))
        except RemoteSourceResolutionError as error:
            raise RemoteSourcePeerError(
                f"Connected peer was invalid for {validated.display_url}"
            ) from error
        if _address_is_unsafe(peer):
            raise RemoteSourcePeerError(
                f"Connected peer was non-public for {validated.display_url}"
            )
        if peer != pinned_address:
            raise RemoteSourcePeerError(
                f"Connected peer did not match the pinned address for "
                f"{validated.display_url}"
            )

    @staticmethod
    def _address_order(address: IPAddress) -> tuple[int, bytes]:
        return address.version, address.packed

    @staticmethod
    def _host_header(host: str) -> str:
        return f"[{host}]" if ":" in host else host

    async def _send(
        self,
        client: httpx.AsyncClient,
        validated: ValidatedRemoteURL,
        deadline: float,
    ) -> httpx.Response:
        last_failure_was_timeout = False
        for pinned_address in sorted(validated.addresses, key=self._address_order):
            # A numeric transport URL prevents a second DNS lookup.  Host remains
            # the validated authority and sni_hostname makes httpcore perform TLS
            # certificate verification against that original authority.
            pinned_url = validated.url.copy_with(host=str(pinned_address))
            client.cookies.clear()
            request = client.build_request(
                "GET",
                pinned_url,
                headers={
                    "Accept-Encoding": "identity",
                    "Host": self._host_header(validated.host),
                    "User-Agent": "StingrayExplorer/remote-source",
                },
                extensions={"sni_hostname": validated.host},
            )
            try:
                response = await asyncio.wait_for(
                    client.send(request, stream=True),
                    timeout=self._remaining(deadline, validated.display_url),
                )
            except httpx.ConnectTimeout:
                last_failure_was_timeout = True
                continue
            except httpx.ConnectError:
                last_failure_was_timeout = False
                continue
            except (asyncio.TimeoutError, httpx.TimeoutException):
                raise RemoteSourceTimeout(
                    f"Remote request timed out for {validated.display_url}"
                ) from None
            except httpx.RequestError:
                raise RemoteSourceError(
                    f"Remote request failed for {validated.display_url}"
                ) from None

            try:
                self._remaining(deadline, validated.display_url)
                self._validate_peer(response, validated, pinned_address)
            except Exception:
                await response.aclose()
                raise
            return response

        if last_failure_was_timeout:
            raise RemoteSourceTimeout(
                f"Remote request timed out for {validated.display_url}"
            ) from None
        raise RemoteSourceError(
            f"Remote request failed for {validated.display_url}"
        ) from None

    async def _open_response(
        self,
        client: httpx.AsyncClient,
        value: str,
        deadline: float,
    ) -> tuple[httpx.Response, ValidatedRemoteURL, int]:
        current = value
        redirect_count = 0

        while True:
            validated = await self._validate_url(current, deadline)
            response = await self._send(client, validated, deadline)
            if response.status_code not in _REDIRECT_STATUSES:
                return response, validated, redirect_count

            location = response.headers.get("location")
            await response.aclose()
            if location is None:
                raise RemoteSourceRedirectError(
                    f"Remote redirect was missing Location for {validated.display_url}"
                )
            redirect_count += 1
            if redirect_count > self._max_redirects:
                raise RemoteSourceRedirectError(
                    f"Remote redirect limit exceeded for {validated.display_url}"
                )
            if _has_control_characters(location):
                raise RemoteSourceRedirectError("Remote redirect Location was invalid")
            current = urljoin(str(validated.url), location)

    @asynccontextmanager
    async def stream(
        self,
        url: str,
        *,
        max_bytes: int,
        cancellation_check: CancellationCheck | None = None,
    ) -> AsyncIterator[RemoteByteStream]:
        """Open a validated response and expose a capped raw-byte stream."""
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes <= 0
        ):
            raise ValueError("max_bytes must be a positive integer")

        deadline = self._clock() + self._timeouts.total
        await _run_cancellation_check(cancellation_check)
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeouts.as_httpx_timeout(),
            follow_redirects=False,
            limits=httpx.Limits(max_keepalive_connections=0),
            trust_env=False,
        ) as client:
            response, validated, redirect_count = await self._open_response(
                client, url, deadline
            )
            try:
                if not 200 <= response.status_code < 300:
                    raise RemoteSourceHTTPError(
                        response.status_code, validated.display_url
                    )
                encodings = {
                    value.strip().lower()
                    for header in response.headers.get_list("content-encoding")
                    for value in header.split(",")
                    if value.strip()
                }
                if encodings and encodings != {"identity"}:
                    raise RemoteSourceError(
                        f"Remote server ignored identity encoding for {validated.display_url}"
                    )
                content_length = _content_length(
                    response, max_bytes, validated.display_url
                )
                info = RemoteResponseInfo(
                    display_url=validated.display_url,
                    status_code=response.status_code,
                    content_length=content_length,
                    content_type=response.headers.get("content-type"),
                    redirect_count=redirect_count,
                )
                yield RemoteByteStream(
                    response,
                    info,
                    max_bytes=max_bytes,
                    chunk_size=self._chunk_size,
                    read_timeout=self._timeouts.read,
                    deadline=deadline,
                    clock=self._clock,
                    cancellation_check=cancellation_check,
                )
            finally:
                await response.aclose()

    async def fetch_bytes(
        self,
        url: str,
        *,
        max_bytes: int,
        cancellation_check: CancellationCheck | None = None,
    ) -> tuple[bytes, RemoteResponseInfo]:
        """Read a complete response while retaining all stream-level bounds."""
        async with self.stream(
            url,
            max_bytes=max_bytes,
            cancellation_check=cancellation_check,
        ) as remote_stream:
            chunks = [chunk async for chunk in remote_stream.aiter_bytes()]
            return b"".join(chunks), remote_stream.info

    async def fetch_text(
        self,
        url: str,
        *,
        max_bytes: int,
        encoding: str = "utf-8",
        cancellation_check: CancellationCheck | None = None,
    ) -> tuple[str, RemoteResponseInfo]:
        """Fetch a bounded text response suitable for directory listings."""
        body, info = await self.fetch_bytes(
            url,
            max_bytes=max_bytes,
            cancellation_check=cancellation_check,
        )
        try:
            return body.decode(encoding), info
        except (LookupError, UnicodeDecodeError) as error:
            raise RemoteSourceError(
                f"Remote text response was not valid {encoding} for {info.display_url}"
            ) from error
