# Stingray Explorer

Stingray Explorer is a desktop application for X-ray timing analysis. It combines
an Electron and React interface with a loopback FastAPI service backed by
[Stingray](https://docs.stingray.science/), Astropy, and NumPy.

> [!IMPORTANT]
> The original Panel, public Docker, and Hugging Face Spaces runtime has been
> retired. It accepted browser-controlled local paths, arbitrary download URLs,
> and unsafe serialization formats that do not belong at a public web boundary.
> The files still under `modules/`, root `services/`, and `utils/` are migration
> reference code; they are not a supported application entrypoint.

## Current application

The supported runtime is the Electron desktop app:

- React, TypeScript, Material UI, and Plotly provide the renderer.
- Electron owns native file dialogs and launches the Python service.
- FastAPI exposes the local scientific API on an ephemeral loopback port.
- Native selections are represented by short-lived grants instead of accepting
  paths typed by renderer code.
- Stingray performs event-list, light-curve, spectral, timing, correlation,
  variable-energy, and dead-time analyses.

The desktop UI includes data ingestion, HEASARC archive browsing, quick-look
analysis pages, job progress, logs, and utility workflows for General I/O, GTIs,
mission I/O, statistics, and miscellaneous Stingray helpers.

## Development setup

Install [Pixi](https://pixi.sh/) and a Node version supported by the locked
frontend toolchain, then run:

```bash
pixi install
npm install
npm run dev
```

Electron starts and authenticates the Python service automatically. Running the
FastAPI service as an unrelated external process is intentionally unsupported;
it cannot share Electron's per-launch credentials or native file grants.

Useful commands:

```bash
# Backend tests in the development environment
pixi run -e dev pytest python-backend/tests

# Frontend tests, type checking, linting, and production build
npm test -- --run
npm run typecheck
npm run lint
npm run build
```

Additional scripts and packaging targets are listed in `package.json` and
`pixi.toml`.

## Repository layout

```text
electron/          Electron main process, preload bridge, and backend lifecycle
python-backend/    Authenticated FastAPI routes, services, models, and tests
src/               React renderer, API clients, state, pages, and component tests
files/             Small sample data used for development
resources/         Desktop application icons and packaging resources
docs/              Implementation plans and engineering notes
```

The historical Panel implementation remains in the legacy root Python folders
while migration work is completed. It has no executable `explorer.py`, Docker
image, or deployment workflow.

## Data and exports

Use the desktop application's native open and save dialogs for local files.
General I/O is the maintained export path; the duplicate raw-path `/api/export/*`
API has been retired. User-visible outputs are expected to use explicit formats,
refuse unintended overwrite, and pass format-specific verification before
publication.

Large scientific files are intentionally not tracked. The small examples under
`files/data/` are suitable for local development; use your own mission data for
full-scale analysis.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

Stingray Explorer builds on the work of the Stingray, Astropy, HoloViz, and
broader X-ray astronomy communities.
