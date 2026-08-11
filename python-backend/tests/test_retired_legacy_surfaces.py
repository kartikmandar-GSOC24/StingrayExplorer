"""Structural regressions for intentionally retired unsafe legacy runtimes."""

from pathlib import Path

from main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSION_SECRET = "retired-surface-test-session-secret" * 2


def test_duplicate_raw_path_export_api_is_absent_from_the_application():
    app = create_app(session_secret=SESSION_SECRET)
    route_paths = {route.path for route in app.routes}

    assert not {path for path in route_paths if path.startswith("/api/export")}
    assert "/api/utilities/io/export" in route_paths


def test_duplicate_export_implementations_and_renderer_client_are_removed():
    retired_files = (
        "python-backend/routes/export_routes.py",
        "python-backend/services/export_service.py",
        "src/api/exportApi.ts",
    )

    assert all(
        not (PROJECT_ROOT / relative_path).exists() for relative_path in retired_files
    )

    renderer_api_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PROJECT_ROOT / "src/api").glob("*.ts"))
    )
    assert "/api/export" not in renderer_api_source


def test_legacy_panel_server_has_no_executable_or_deployment_entrypoint():
    assert not (PROJECT_ROOT / "explorer.py").exists()
    assert not (PROJECT_ROOT / "Dockerfile").exists()

    operational_sources = [
        PROJECT_ROOT / "package.json",
        PROJECT_ROOT / "pixi.toml",
        *(PROJECT_ROOT / ".github/workflows").glob("*.yml"),
        *(PROJECT_ROOT / ".github/workflows").glob("*.yaml"),
        *(PROJECT_ROOT / "scripts").glob("*"),
    ]
    launch_configuration = "\n".join(
        path.read_text(encoding="utf-8")
        for path in operational_sources
        if path.is_file()
    ).lower()

    assert "panel serve" not in launch_configuration
    assert "allow-websocket-origin" not in launch_configuration
    assert "huggingface.co/spaces" not in launch_configuration
