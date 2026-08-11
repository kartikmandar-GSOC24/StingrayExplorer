"""Focused, network-free tests for the remote-source security boundary."""

from __future__ import annotations

import ipaddress
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest
import services.remote_source as remote_source_module
from services.remote_source import (
    GENERAL_HTTPS_POLICY,
    HEASARC_ARCHIVE_POLICY,
    RemoteSourceCancelled,
    RemoteSourceClient,
    RemoteSourceError,
    RemoteSourceHTTPError,
    RemoteSourcePeerError,
    RemoteSourcePolicyError,
    RemoteSourceRedirectError,
    RemoteSourceResolutionError,
    RemoteSourceSizeError,
    RemoteSourceTimeout,
    RemoteTimeouts,
    redact_remote_url,
)

PUBLIC_IP = "93.184.216.34"
SECOND_PUBLIC_IP = "1.1.1.1"


class StaticResolver:
    def __init__(self, addresses: Sequence[str] = (PUBLIC_IP,)) -> None:
        self.addresses = addresses
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        self.calls.append((host, port))
        return self.addresses


class HostResolver:
    def __init__(self, addresses: dict[str, Sequence[str]]) -> None:
        self.addresses = addresses
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        self.calls.append((host, port))
        return self.addresses[host]


class PeerStream:
    def __init__(self, address: str | None, port: int = 443) -> None:
        self.address = address
        self.port = port

    def get_extra_info(self, info: str):
        if info == "server_addr" and self.address is not None:
            return (self.address, self.port)
        return None


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: Sequence[bytes], on_chunk=None) -> None:
        self.chunks = chunks
        self.on_chunk = on_chunk

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index, chunk in enumerate(self.chunks):
            if self.on_chunk is not None:
                self.on_chunk(index)
            yield chunk


class FailingReadStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        raise httpx.ReadTimeout(
            "read secret",
            request=httpx.Request(
                "GET", "https://example.com/data?secret=must-not-leak"
            ),
        )
        yield b""  # pragma: no cover - keeps this an async generator


def response(
    status: int = 200,
    *,
    body: bytes | httpx.AsyncByteStream = b"ok",
    headers: dict[str, str] | None = None,
    peer: str | None = PUBLIC_IP,
    peer_port: int = 443,
) -> httpx.Response:
    extensions = {}
    if peer is not None:
        extensions["network_stream"] = PeerStream(peer, peer_port)
    if isinstance(body, bytes):
        body = ChunkStream((body,))
    return httpx.Response(status, stream=body, headers=headers, extensions=extensions)


def client_for(
    handler,
    *,
    resolver=None,
    policy=GENERAL_HTTPS_POLICY,
    **kwargs,
) -> RemoteSourceClient:
    return RemoteSourceClient(
        policy,
        resolver=resolver or StaticResolver(),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/file.fits",
        "ftp://example.com/file.fits",
        "https://user:secret@example.com/file.fits",
        "https://example.com/file.fits#section",
        "https://example.com/file.fits#",
        "https://example.com:444/file.fits",
        "https://example.com:0443/file.fits",
        "https://example.com:/file.fits",
        "https://example.com\\@evil.test/file.fits",
        "https://example.com/%0d%0aX-Test:yes",
        " https://example.com/file.fits",
        "https://example.com/%zz",
        "https://example.com./file.fits",
    ],
)
@pytest.mark.asyncio
async def test_invalid_urls_are_rejected_before_transport(url: str) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return response()

    source = client_for(handler)
    with pytest.raises(RemoteSourcePolicyError):
        await source.fetch_bytes(url, max_bytes=100)
    assert called is False


@pytest.mark.asyncio
async def test_remote_url_length_is_bounded_before_resolution_or_transport() -> None:
    resolver = StaticResolver()
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return response()

    source = client_for(handler, resolver=resolver)
    with pytest.raises(RemoteSourcePolicyError, match="canonical string"):
        await source.fetch_bytes(f"https://example.com/{'a' * 4_096}", max_bytes=100)

    assert resolver.calls == []
    assert called is False


@pytest.mark.asyncio
async def test_canonical_explicit_https_port_is_allowed_and_redacted() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response(headers={"Content-Length": "2"})

    source = client_for(handler)
    body, info = await source.fetch_bytes(
        "https://example.com:443/file.fits?token=super-secret", max_bytes=2
    )

    assert body == b"ok"
    assert info.display_url == "https://example.com:443/file.fits"
    assert "super-secret" not in repr(info)
    assert seen[0].url.host == PUBLIC_IP
    assert seen[0].headers["host"] == "example.com"
    assert seen[0].headers["accept-encoding"] == "identity"
    assert seen[0].extensions["sni_hostname"] == "example.com"
    assert seen[0].extensions["timeout"] == {
        "connect": 10.0,
        "read": 30.0,
        "write": 10.0,
        "pool": 5.0,
    }


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "::",
        "2001:db8::1",
        "::ffff:127.0.0.1",
    ],
)
@pytest.mark.asyncio
async def test_dns_rejects_every_non_public_address_class(address: str) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return response()

    source = client_for(handler, resolver=StaticResolver((address,)))
    with pytest.raises(RemoteSourceResolutionError, match="non-public"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)
    assert called is False


@pytest.mark.asyncio
async def test_dns_rejects_mixed_public_and_private_results() -> None:
    source = client_for(
        lambda request: response(),
        resolver=StaticResolver((PUBLIC_IP, "127.0.0.1")),
    )
    with pytest.raises(RemoteSourceResolutionError, match="non-public"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_empty_and_invalid_dns_results_fail_closed() -> None:
    empty = client_for(lambda request: response(), resolver=StaticResolver(()))
    with pytest.raises(RemoteSourceResolutionError, match="no addresses"):
        await empty.fetch_bytes("https://example.com/data", max_bytes=100)

    invalid = client_for(
        lambda request: response(), resolver=StaticResolver(("not-an-ip",))
    )
    with pytest.raises(RemoteSourceResolutionError, match="invalid address"):
        await invalid.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_public_ip_literal_is_validated_without_dns_lookup() -> None:
    resolver = StaticResolver(("127.0.0.1",))
    source = client_for(lambda request: response(), resolver=resolver)
    body, _ = await source.fetch_bytes(f"https://{PUBLIC_IP}/data", max_bytes=100)
    assert body == b"ok"
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_private_ip_literal_is_rejected() -> None:
    source = client_for(lambda request: response())
    with pytest.raises(RemoteSourceResolutionError, match="non-public"):
        await source.fetch_bytes("https://127.0.0.1/data", max_bytes=100)


@pytest.mark.asyncio
async def test_actual_peer_must_be_public_and_match_validated_dns() -> None:
    private_peer = client_for(
        lambda request: response(peer="127.0.0.1"),
        resolver=StaticResolver((PUBLIC_IP,)),
    )
    with pytest.raises(RemoteSourcePeerError, match="non-public"):
        await private_peer.fetch_bytes("https://example.com/data", max_bytes=100)

    changed_peer = client_for(
        lambda request: response(peer=SECOND_PUBLIC_IP),
        resolver=StaticResolver((PUBLIC_IP,)),
    )
    with pytest.raises(RemoteSourcePeerError, match="did not match"):
        await changed_peer.fetch_bytes("https://example.com/data", max_bytes=100)

    wrong_port = client_for(
        lambda request: response(peer=PUBLIC_IP, peer_port=8443),
        resolver=StaticResolver((PUBLIC_IP,)),
    )
    with pytest.raises(RemoteSourcePeerError, match="unexpected port"):
        await wrong_port.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_dns_rebinding_cannot_change_numeric_connection_target() -> None:
    attempted_peers: list[str] = []

    def rebinding_transport(request: httpx.Request) -> httpx.Response:
        # Model a second DNS lookup that has been poisoned after validation.
        # A hostname request would be sent to loopback; a numeric request cannot
        # be rebound and is sent to the already approved address.
        peer = "127.0.0.1" if request.url.host == "example.com" else request.url.host
        attempted_peers.append(peer)
        return response(peer=peer)

    source = client_for(
        rebinding_transport,
        resolver=StaticResolver((PUBLIC_IP,)),
    )
    body, _ = await source.fetch_bytes("https://example.com/data", max_bytes=100)

    assert body == b"ok"
    assert attempted_peers == [PUBLIC_IP]


@pytest.mark.asyncio
async def test_approved_addresses_are_tried_by_numeric_ip_without_new_dns() -> None:
    attempted_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempted_urls.append(request.url.host)
        if request.url.host == SECOND_PUBLIC_IP:
            raise httpx.ConnectError("unavailable", request=request)
        return response(peer=PUBLIC_IP)

    source = client_for(
        handler,
        resolver=StaticResolver((PUBLIC_IP, SECOND_PUBLIC_IP)),
    )
    body, _ = await source.fetch_bytes("https://example.com/data", max_bytes=100)

    assert body == b"ok"
    assert attempted_urls == [SECOND_PUBLIC_IP, PUBLIC_IP]


@pytest.mark.asyncio
async def test_missing_peer_extension_fails_closed() -> None:
    source = client_for(lambda request: response(peer=None))
    with pytest.raises(RemoteSourcePeerError, match="identity was unavailable"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_peer_extension_without_server_address_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result = response(peer=None)
        result.extensions["network_stream"] = PeerStream(None)
        return result

    source = client_for(handler)
    with pytest.raises(RemoteSourcePeerError, match="identity was unavailable"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/FTP/file.fits",
        "https://heasarc.gsfc.nasa.gov/ftp/file.fits",
        "https://heasarc.gsfc.nasa.gov/FTP",
        "https://heasarc.gsfc.nasa.gov/FTP/../cgi-bin/query",
        "https://heasarc.gsfc.nasa.gov/FTP/%2e%2e/cgi-bin/query",
        "https://heasarc.gsfc.nasa.gov/FTP%2ffile.fits",
        "https://heasarc.gsfc.nasa.gov.evil.test/FTP/file.fits",
        "https://heasarc.gsfc.nasa.gov./FTP/file.fits",
    ],
)
@pytest.mark.asyncio
async def test_archive_policy_has_exact_host_port_and_path_boundary(url: str) -> None:
    source = client_for(lambda request: response(), policy=HEASARC_ARCHIVE_POLICY)
    with pytest.raises(RemoteSourcePolicyError):
        await source.fetch_bytes(url, max_bytes=100)


@pytest.mark.asyncio
async def test_archive_policy_accepts_implicit_or_explicit_default_port() -> None:
    resolver = StaticResolver()
    source = client_for(
        lambda request: response(),
        resolver=resolver,
        policy=HEASARC_ARCHIVE_POLICY,
    )
    for url in (
        "https://heasarc.gsfc.nasa.gov/FTP/file.fits",
        "https://heasarc.gsfc.nasa.gov:443/FTP/file.fits",
    ):
        body, _ = await source.fetch_bytes(url, max_bytes=100)
        assert body == b"ok"
    assert resolver.calls == [
        ("heasarc.gsfc.nasa.gov", 443),
        ("heasarc.gsfc.nasa.gov", 443),
    ]


@pytest.mark.asyncio
async def test_archive_redirect_cannot_escape_exact_boundary() -> None:
    source = client_for(
        lambda request: response(
            302,
            headers={"Location": "https://heasarc.gsfc.nasa.gov/cgi-bin/private"},
        ),
        policy=HEASARC_ARCHIVE_POLICY,
    )
    with pytest.raises(RemoteSourcePolicyError, match="path boundary"):
        await source.fetch_bytes(
            "https://heasarc.gsfc.nasa.gov/FTP/start", max_bytes=100
        )


@pytest.mark.asyncio
async def test_every_redirect_is_re_resolved_and_peer_validated() -> None:
    resolver = HostResolver(
        {"first.example": (PUBLIC_IP,), "second.example": (SECOND_PUBLIC_IP,)}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "first.example":
            return response(
                302,
                headers={"Location": "https://second.example/final?credential=hidden"},
                peer=PUBLIC_IP,
            )
        return response(body=b"final", peer=SECOND_PUBLIC_IP)

    source = client_for(handler, resolver=resolver)
    body, info = await source.fetch_bytes(
        "https://first.example/start?secret=one", max_bytes=100
    )

    assert body == b"final"
    assert info.redirect_count == 1
    assert info.display_url == "https://second.example/final"
    assert resolver.calls == [("first.example", 443), ("second.example", 443)]


@pytest.mark.asyncio
async def test_redirect_to_private_dns_target_is_rejected_before_second_request() -> (
    None
):
    resolver = HostResolver(
        {"first.example": (PUBLIC_IP,), "internal.example": ("127.0.0.1",)}
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.headers["host"])
        return response(
            302,
            headers={"Location": "https://internal.example/admin"},
            peer=PUBLIC_IP,
        )

    source = client_for(handler, resolver=resolver)
    with pytest.raises(RemoteSourceResolutionError, match="non-public"):
        await source.fetch_bytes("https://first.example/start", max_bytes=100)
    assert requests == ["first.example"]


@pytest.mark.asyncio
async def test_redirect_cannot_downgrade_to_http() -> None:
    source = client_for(
        lambda request: response(
            302, headers={"Location": "http://example.com/plaintext"}
        )
    )
    with pytest.raises(RemoteSourcePolicyError, match="HTTPS"):
        await source.fetch_bytes("https://example.com/start", max_bytes=100)


@pytest.mark.asyncio
async def test_redirect_limit_and_missing_location_are_bounded() -> None:
    source = client_for(
        lambda request: response(302, headers={"Location": "/again"}),
        max_redirects=2,
    )
    with pytest.raises(RemoteSourceRedirectError, match="limit"):
        await source.fetch_bytes("https://example.com/start", max_bytes=100)

    missing = client_for(lambda request: response(302))
    with pytest.raises(RemoteSourceRedirectError, match="missing Location"):
        await missing.fetch_bytes("https://example.com/start", max_bytes=100)


@pytest.mark.asyncio
async def test_content_length_is_checked_before_body_iteration() -> None:
    iterated = False

    def mark_iteration(index: int) -> None:
        nonlocal iterated
        iterated = True

    source = client_for(
        lambda request: response(
            body=ChunkStream((b"never",), mark_iteration),
            headers={"Content-Length": "101"},
        )
    )
    with pytest.raises(RemoteSourceSizeError, match="100-byte"):
        await source.fetch_bytes("https://example.com/large", max_bytes=100)
    assert iterated is False


@pytest.mark.parametrize(
    "content_length",
    ["-1", "not-a-number", "1, 2"],
)
@pytest.mark.asyncio
async def test_invalid_or_conflicting_content_lengths_are_rejected(
    content_length: str,
) -> None:
    source = client_for(
        lambda request: response(headers={"Content-Length": content_length})
    )
    with pytest.raises(RemoteSourceSizeError, match="Content-Length"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_huge_numeric_content_length_fails_as_size_error() -> None:
    source = client_for(
        lambda request: response(headers={"Content-Length": "9" * 5000})
    )
    with pytest.raises(RemoteSourceSizeError, match="100-byte"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_incremental_cap_applies_without_content_length() -> None:
    source = client_for(
        lambda request: response(body=ChunkStream((b"1234", b"5678"))),
        chunk_size=4,
    )
    with pytest.raises(RemoteSourceSizeError, match="7-byte"):
        await source.fetch_bytes("https://example.com/data", max_bytes=7)


@pytest.mark.asyncio
async def test_non_identity_content_encoding_is_rejected() -> None:
    source = client_for(lambda request: response(headers={"Content-Encoding": "gzip"}))
    with pytest.raises(RemoteSourceError, match="identity encoding"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_stream_yields_raw_chunks_and_safe_metadata() -> None:
    source = client_for(
        lambda request: response(
            body=ChunkStream((b"one", b"two")),
            headers={"Content-Length": "6", "Content-Type": "application/fits"},
        ),
        chunk_size=3,
    )
    async with source.stream(
        "https://example.com/data?api_key=never-display", max_bytes=6
    ) as stream:
        chunks = [chunk async for chunk in stream.aiter_bytes()]
        assert stream.bytes_read == 6
        assert stream.info.content_length == 6
        assert stream.info.content_type == "application/fits"
        with pytest.raises(RuntimeError, match="only be consumed once"):
            await anext(stream.aiter_bytes())
    assert chunks == [b"one", b"two"]
    assert "api_key" not in repr(stream.info)


@pytest.mark.asyncio
async def test_cancellation_is_checked_for_each_chunk() -> None:
    checks = 0

    def cancellation_check() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    source = client_for(
        lambda request: response(body=ChunkStream((b"first", b"second"))),
        chunk_size=5,
    )
    yielded: list[bytes] = []
    with pytest.raises(RemoteSourceCancelled):
        async with source.stream(
            "https://example.com/data",
            max_bytes=100,
            cancellation_check=cancellation_check,
        ) as stream:
            async for chunk in stream.aiter_bytes():
                yielded.append(chunk)
    assert yielded == [b"first"]


@pytest.mark.asyncio
async def test_async_cancellation_hook_is_supported() -> None:
    async def cancelled() -> bool:
        return True

    source = client_for(lambda request: response())
    with pytest.raises(RemoteSourceCancelled):
        await source.fetch_bytes(
            "https://example.com/data", max_bytes=100, cancellation_check=cancelled
        )


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_monotonic_total_deadline_covers_dns() -> None:
    clock = MutableClock()

    async def resolver(host: str, port: int) -> Sequence[str]:
        clock.value = 2.0
        return (PUBLIC_IP,)

    source = client_for(
        lambda request: response(),
        resolver=resolver,
        clock=clock,
        timeouts=RemoteTimeouts(total=1.0),
    )
    with pytest.raises(RemoteSourceTimeout, match="deadline"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_monotonic_total_deadline_covers_body_iteration() -> None:
    clock = MutableClock()

    def advance_clock(index: int) -> None:
        clock.value = 2.0

    source = client_for(
        lambda request: response(
            body=ChunkStream((b"too-late",), on_chunk=advance_clock)
        ),
        clock=clock,
        timeouts=RemoteTimeouts(total=1.0),
    )
    with pytest.raises(RemoteSourceTimeout, match="deadline"):
        await source.fetch_bytes("https://example.com/data", max_bytes=100)


@pytest.mark.asyncio
async def test_httpx_phase_timeout_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("secret=must-not-leak", request=request)

    source = client_for(handler)
    with pytest.raises(RemoteSourceTimeout) as exc_info:
        await source.fetch_bytes(
            "https://example.com/data?secret=must-not-leak", max_bytes=100
        )
    assert "must-not-leak" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_httpx_read_timeout_is_sanitized() -> None:
    source = client_for(lambda request: response(body=FailingReadStream()))
    with pytest.raises(RemoteSourceTimeout) as exc_info:
        await source.fetch_bytes(
            "https://example.com/data?secret=must-not-leak", max_bytes=100
        )
    assert "must-not-leak" not in str(exc_info.value)
    assert "read secret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_dns_failure_is_sanitized_and_query_is_redacted() -> None:
    async def resolver(host: str, port: int) -> Sequence[str]:
        raise OSError("resolver secret")

    source = client_for(lambda request: response(), resolver=resolver)
    with pytest.raises(RemoteSourceResolutionError) as exc_info:
        await source.fetch_bytes(
            "https://example.com/data?credential=never-show", max_bytes=100
        )
    assert "credential" not in str(exc_info.value)
    assert "never-show" not in str(exc_info.value)
    assert "resolver secret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_http_status_error_and_metadata_never_expose_query() -> None:
    source = client_for(lambda request: response(404))
    with pytest.raises(RemoteSourceHTTPError) as exc_info:
        await source.fetch_bytes(
            "https://example.com/missing?token=top-secret", max_bytes=100
        )
    assert exc_info.value.status_code == 404
    assert "top-secret" not in str(exc_info.value)
    assert "token" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_bounded_text_helper_decodes_listing() -> None:
    source = client_for(
        lambda request: response(
            body=b"<a href='file.fits'>file</a>",
            headers={"Content-Length": "28"},
        )
    )
    text, info = await source.fetch_text("https://example.com/listing", max_bytes=64)
    assert text == "<a href='file.fits'>file</a>"
    assert info.content_length == 28


@pytest.mark.asyncio
async def test_bounded_text_helper_rejects_invalid_encoding() -> None:
    source = client_for(lambda request: response(body=b"\xff"))
    with pytest.raises(RemoteSourceError, match="not valid utf-8"):
        await source.fetch_text("https://example.com/listing", max_bytes=1)


def test_redaction_never_includes_userinfo_query_or_fragment() -> None:
    display = redact_remote_url(
        "https://name:password@example.com:443/path?api_key=secret#fragment"
    )
    assert display == "https://example.com:443/path"
    assert "name" not in display
    assert "password" not in display
    assert "api_key" not in display
    assert "secret" not in display
    assert "fragment" not in display


@pytest.mark.asyncio
async def test_unicode_url_is_canonicalized_without_treating_utf8_as_controls() -> None:
    resolver = StaticResolver()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response()

    source = client_for(handler, resolver=resolver)
    body, info = await source.fetch_bytes(
        "https://b\N{LATIN SMALL LETTER U WITH DIAERESIS}cher.example/\N{LATIN SMALL LETTER U WITH DIAERESIS}ber",
        max_bytes=100,
    )
    assert body == b"ok"
    assert resolver.calls == [("xn--bcher-kva.example", 443)]
    assert seen[0].url.host == PUBLIC_IP
    assert seen[0].headers["host"] == "xn--bcher-kva.example"
    assert seen[0].extensions["sni_hostname"] == "xn--bcher-kva.example"
    assert info.display_url.endswith("/\N{LATIN SMALL LETTER U WITH DIAERESIS}ber")


@pytest.mark.asyncio
async def test_client_disables_environment_proxies_and_automatic_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.AsyncClient
    constructor_options: list[dict[str, object]] = []

    class RecordingClient(real_client):
        def __init__(self, *args, **kwargs) -> None:
            constructor_options.append(dict(kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(remote_source_module.httpx, "AsyncClient", RecordingClient)
    source = client_for(lambda request: response())
    body, _ = await source.fetch_bytes("https://example.com/data", max_bytes=100)
    assert body == b"ok"
    assert constructor_options[0]["trust_env"] is False
    assert constructor_options[0]["follow_redirects"] is False
    assert constructor_options[0]["limits"].max_keepalive_connections == 0


def test_timeout_and_client_bounds_validate_configuration() -> None:
    with pytest.raises(ValueError, match="total timeout"):
        RemoteTimeouts(total=0)
    with pytest.raises(ValueError, match="total timeout"):
        RemoteTimeouts(total=float("inf"))
    with pytest.raises(ValueError, match="read timeout"):
        RemoteTimeouts(read=float("nan"))
    with pytest.raises(ValueError, match="connect timeout"):
        RemoteTimeouts(connect=True)
    with pytest.raises(ValueError, match="max_redirects"):
        RemoteSourceClient(max_redirects=-1)
    with pytest.raises(ValueError, match="max_redirects"):
        RemoteSourceClient(max_redirects=True)
    with pytest.raises(ValueError, match="max_redirects"):
        RemoteSourceClient(max_redirects=11)
    with pytest.raises(ValueError, match="chunk_size"):
        RemoteSourceClient(chunk_size=0)
    with pytest.raises(ValueError, match="chunk_size"):
        RemoteSourceClient(chunk_size=True)
    with pytest.raises(ValueError, match="chunk_size"):
        RemoteSourceClient(chunk_size=1024 * 1024 + 1)


def test_public_address_fixture_is_really_global() -> None:
    assert ipaddress.ip_address(PUBLIC_IP).is_global
