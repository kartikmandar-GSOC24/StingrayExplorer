"""Regression tests for the listener-owned backend startup protocol."""

import socket

import pytest
import uvicorn

from main import bind_backend_socket, parse_requested_port, run_backend


@pytest.mark.parametrize("value", ["0", "65536", "+1", "01", " 8765", "８７６５"])
def test_explicit_port_validation_is_canonical(value: str):
    with pytest.raises(ValueError):
        parse_requested_port(value)


@pytest.mark.parametrize(
    ("value", "expected"), [("1", 1), ("8765", 8765), ("65535", 65535)]
)
def test_explicit_port_validation_accepts_only_valid_ports(value: str, expected: int):
    assert parse_requested_port(value) == expected


def test_run_backend_announces_an_owned_listening_socket(
    monkeypatch, capsys, unused_tcp_port
):
    observed: dict[str, object] = {}

    def fake_run(server, *, sockets=None):
        assert sockets is not None and len(sockets) == 1
        listener = sockets[0]
        observed["listener"] = listener
        observed["port"] = listener.getsockname()[1]
        try:
            assert listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1
        except OSError:
            # macOS does not expose SO_ACCEPTCONN for AF_INET sockets; the
            # competing-bind check below still proves the listener is owned.
            pass
        with pytest.raises(OSError):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as competing:
                competing.bind(("127.0.0.1", listener.getsockname()[1]))
        assert server.config.port == listener.getsockname()[1]
        assert server.config.workers == 1

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    run_backend(str(unused_tcp_port))

    output = capsys.readouterr().out
    assert output == f"BACKEND_PORT:{observed['port']}\n"
    assert observed["port"] == unused_tcp_port
    assert observed["listener"].fileno() == -1


def test_bind_backend_socket_closes_failed_candidates(monkeypatch, unused_tcp_port):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", unused_tcp_port))
    blocker.listen()
    try:
        with pytest.raises(RuntimeError):
            bind_backend_socket(requested_port=str(unused_tcp_port))
    finally:
        blocker.close()
