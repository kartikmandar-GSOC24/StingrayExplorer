# QuickLook Core Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the eleven QuickLook placeholder pages (EventList, LightCurve, PowerSpectrum, AvgPowerSpectrum, CrossSpectrum, AvgCrossSpectrum, DynamicalPowerSpectrum, Bispectrum, Coherence, TimeLags, PowerColors) with working analysis UIs wired to the existing FastAPI endpoints, fixing the four backend correctness bugs that block them.

**Architecture:** Each page is a self-contained React component: a parameters card (left) driving one POST to the backend, and a Plotly result card (right). Shared machinery is built once — a theme-aware `PlotlyChart`, an `EventListSelector` fed by a TanStack Query hook, and a `useAnalysisRunner` hook that owns the request lifecycle and notifications. Analysis results live in backend memory (StateManager); pages display the create-response payload directly. Backend fixes land first (TDD with pytest) because three endpoints currently return unserializable or scientifically wrong data.

**Tech Stack:** React 18 + TypeScript + MUI v5 + TanStack Query v5 + Zustand + react-plotly.js (lazy-loaded), FastAPI + Stingray 2.2.10, vitest + @testing-library/react (frontend), pytest via pixi `dev` env (backend).

**Testing strategy (read before executing):** Backend fixes and all shared frontend logic (hooks, helpers, selector, chart wrapper) are TDD'd. The EventList and LightCurve pages get component tests establishing the display-page and runner-page patterns. The remaining nine pages are declarative wiring of already-tested pieces; their gates are `npm run typecheck`, `npm run lint`, and a manual verification step each — jsdom tests for Plotly-heavy pages would test mocks, not behavior.

**Git note (user preference):** Commits use conventional format, **no Claude co-authorship**. The user requires confirmation before git commands — at execution start, ask the user for blanket approval of the commit steps in this plan, or pause at each commit step.

---

## Context for an engineer with zero prior knowledge

Repo root: `/Volumes/Mac Projects/StingrayExplorer`, branch `electron-migration`.

- Run the app: `npm run dev` (Electron spawns the Python backend itself from `.pixi/envs/default/bin/python`). First cold start can take ~60 s.
- The renderer talks to FastAPI at `http://127.0.0.1:<port>` via `apiClient` ([src/api/client.ts](../../../src/api/client.ts)). Every response has shape `ApiResponse<T> = { success, data, message, error }`. **A failed analysis still returns HTTP 200 with `success: false`** — always branch on `res.success`.
- Frontend API modules already exist and match the backend: `src/api/dataApi.ts`, `lightcurveApi.ts`, `spectrumApi.ts`, `timingApi.ts`.
- Notifications: `useUIStore.getState().addNotification({ type, title, message })` where `type: 'info' | 'success' | 'warning' | 'error'` (`src/store/uiStore.ts:81`).
- Pages live at `src/pages/QuickLook/<Name>/index.tsx`, currently rendering `PageTemplate` with `status="coming-soon"`. `PageTemplate` (`src/components/common/PageTemplate.tsx`) accepts `status="ready"` and `children`.
- Routes: `src/App.tsx:648-665` (hash router). Sidebar nav: `src/components/layout/Sidebar.tsx:79-98` (submenu items) and `:157-181` (category groupings). **There is no route/page/nav entry yet for Time Lags or Power Colors — Tasks 20-21 add them.**
- Path alias `@/` → `src/` (configured in `electron.vite.config.ts`; vitest config in Task 1 must mirror it).
- Backend services return plain dicts via `BaseService.create_result(success, data, message, error)`. Services are constructed per-request: `LightcurveService(state_manager=request.app.state.state_manager, performance_monitor=...)` — the second arg is optional.
- Python style: 4-space indent. TS style: 2-space indent.

**Known backend bugs this plan fixes (verified by reading code):**
1. `spectrum_service.py:203,286` — `cs.power.tolist()` on a **complex** array (Stingray cross spectra) → not JSON-serializable; both cross-spectrum endpoints fail.
2. `timing_service.py:305` — coherence computed as `np.abs(cs.unnorm_power)**2` (just |cross power|², values ≫ 1). Must use Stingray's `cs.coherence()`.
3. `timing_service.py:217` — time lags hand-rolled as `np.angle(unnorm_power)/(2πf)`, no uncertainties. Must use `cs.time_lag()`.
4. `lightcurve_routes.py` / `spectrum_routes.py` / `timing_routes.py` — `async def` handlers call synchronous services directly, **blocking the event loop** during computation (freezes SSE job/log streams). `data_routes.py` already shows the fix pattern: `await asyncio.to_thread(...)`.
5. Light curves return full `time`/`counts` arrays — a NICER file at dt=1 ms is tens of millions of bins → renderer death. Add server-side stride decimation for plotting.

---

## File structure

**Created:**
- `vitest.config.ts`, `src/test/setup.ts`, `src/test/testUtils.tsx`
- `python-backend/tests/__init__.py`, `conftest.py`, `test_spectrum_service.py`, `test_timing_service.py`, `test_lightcurve_service.py`, `test_route_concurrency.py`
- `src/components/plots/PlotlyChart.tsx` (+ test)
- `src/components/analysis/EventListSelector.tsx` (+ test)
- `src/hooks/useEventLists.ts` (+ test), `src/hooks/useAnalysisRunner.ts` (+ test)
- `src/utils/numbers.ts`, `src/utils/powerColors.ts` (+ tests)
- `src/pages/QuickLook/TimeLags/index.tsx`, `src/pages/QuickLook/PowerColors/index.tsx`
- Page tests: `src/pages/QuickLook/EventList/index.test.tsx`, `src/pages/QuickLook/LightCurve/index.test.tsx`

**Modified:**
- `python-backend/services/spectrum_service.py`, `timing_service.py`, `lightcurve_service.py`
- `python-backend/routes/lightcurve_routes.py`, `spectrum_routes.py`, `timing_routes.py`
- `src/api/lightcurveApi.ts`, `spectrumApi.ts`, `timingApi.ts`
- `src/pages/QuickLook/{EventList,LightCurve,PowerSpectrum,AvgPowerSpectrum,CrossSpectrum,AvgCrossSpectrum,DynamicalPowerSpectrum,Bispectrum,Coherence}/index.tsx`
- `src/App.tsx` (2 imports + 2 routes), `src/components/layout/Sidebar.tsx` (2 nav items + 2 category entries)
- `package.json` (test devDeps)

---

### Task 1: Frontend test infrastructure

**Files:**
- Create: `vitest.config.ts`, `src/test/setup.ts`, `src/test/testUtils.tsx`, `src/utils/numbers.ts`, `src/utils/numbers.test.ts`
- Modify: `package.json` (devDependencies via npm)

- [x] **Step 1: Install test dependencies**

Run: `npm install --save-dev jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event`
Expected: exits 0, package.json devDependencies updated.

- [x] **Step 2: Create vitest config and setup**

`vitest.config.ts`:
```ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
```

`src/test/setup.ts`:
```ts
import '@testing-library/jest-dom/vitest';

// MUI useMediaQuery requires matchMedia, absent in jsdom
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
```

`src/test/testUtils.tsx`:
```tsx
import React from 'react';
import { render, RenderResult } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

export function renderWithProviders(ui: React.ReactElement): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}
```

- [x] **Step 3: Write a first real test (number parsing helpers used by every page)**

`src/utils/numbers.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { parseNumber, parsePositiveNumber } from './numbers';

describe('parsePositiveNumber', () => {
  it('parses valid positive numbers', () => {
    expect(parsePositiveNumber('0.0625')).toBe(0.0625);
    expect(parsePositiveNumber('32')).toBe(32);
  });

  it('rejects zero, negatives, and junk', () => {
    expect(parsePositiveNumber('0')).toBeNull();
    expect(parsePositiveNumber('-1')).toBeNull();
    expect(parsePositiveNumber('abc')).toBeNull();
    expect(parsePositiveNumber('')).toBeNull();
  });
});

describe('parseNumber', () => {
  it('parses any finite number', () => {
    expect(parseNumber('-2.5')).toBe(-2.5);
    expect(parseNumber('0')).toBe(0);
  });

  it('rejects non-numeric input', () => {
    expect(parseNumber('1e999')).toBeNull();
    expect(parseNumber('x')).toBeNull();
    expect(parseNumber('')).toBeNull();
  });
});
```

- [x] **Step 4: Run to verify it fails**

Run: `npm test -- --run`
Expected: FAIL — `Cannot find module './numbers'` (or equivalent resolve error).

- [x] **Step 5: Implement the helpers**

`src/utils/numbers.ts`:
```ts
/** Parse a text-field value into a finite positive number, or null if invalid. */
export function parsePositiveNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Parse a text-field value into any finite number, or null if invalid. */
export function parseNumber(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
```

- [x] **Step 6: Run to verify it passes**

Run: `npm test -- --run`
Expected: PASS (4 tests).

- [x] **Step 7: Commit**

```bash
git add vitest.config.ts src/test/ src/utils/numbers.ts src/utils/numbers.test.ts package.json package-lock.json
git commit -m "chore: add vitest + testing-library infrastructure"
```

---

### Task 2: Python test infrastructure

**Files:**
- Create: `python-backend/tests/__init__.py`, `python-backend/tests/conftest.py`, `python-backend/tests/test_smoke.py`

- [x] **Step 1: Ensure the pixi dev environment exists**

Run: `pixi install -e dev`
Expected: exits 0 (installs pytest, pytest-asyncio into `.pixi/envs/dev`). May take a few minutes the first time.

- [x] **Step 2: Create the test package and fixtures**

`python-backend/tests/__init__.py`: empty file.

`python-backend/tests/conftest.py`:
```python
"""Shared fixtures for backend service tests.

python-backend is not an installable package (hyphenated dir name), so tests
add it to sys.path and import the same way main.py does (cwd=python-backend).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from stingray import EventList

from services.state_manager import StateManager


def make_event_list(seed: int, n_events: int = 20000, length: float = 64.0) -> EventList:
    """Deterministic synthetic event list spanning [0, length] seconds."""
    rng = np.random.default_rng(seed)
    times = np.sort(rng.uniform(0.0, length, n_events))
    energy = rng.uniform(0.5, 10.0, n_events)
    return EventList(time=times, energy=energy, gti=[[0.0, length]])


@pytest.fixture()
def state_manager() -> StateManager:
    return StateManager()


@pytest.fixture()
def loaded_state(state_manager: StateManager) -> StateManager:
    state_manager.add_event_data("ev1", make_event_list(1))
    state_manager.add_event_data("ev2", make_event_list(2))
    return state_manager
```

`python-backend/tests/test_smoke.py`:
```python
def test_services_import_and_state_works(loaded_state):
    assert loaded_state.has_event_data("ev1")
    assert loaded_state.has_event_data("ev2")
    assert len(loaded_state.get_event_data("ev1").time) == 20000
```

- [x] **Step 3: Run the smoke test**

Run: `pixi run -e dev pytest python-backend/tests -v`
Expected: PASS (1 test). If `add_event_data` has a different name, check `python-backend/services/state_manager.py:48` — it is `add_event_data(name, event_list)`.

- [x] **Step 4: Commit**

```bash
git add python-backend/tests/
git commit -m "chore: add pytest scaffolding for python backend"
```

---

### Task 3: Fix cross-spectrum complex power serialization (backend)

**Files:**
- Create: `python-backend/tests/test_spectrum_service.py`
- Modify: `python-backend/services/spectrum_service.py`

- [x] **Step 1: Write the failing tests**

`python-backend/tests/test_spectrum_service.py`:
```python
import json

from services.spectrum_service import SpectrumService


def test_cross_spectrum_is_strict_json_serializable(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_cross_spectrum("ev1", "ev2", dt=0.0625)
    assert result["success"], result
    json.dumps(result, allow_nan=False)  # complex or NaN values raise here
    data = result["data"]
    assert all(isinstance(p, float) for p in data["power"][:10])
    assert data["power_phase"] is not None
    assert len(data["power_phase"]) == len(data["power"])


def test_averaged_cross_spectrum_is_strict_json_serializable(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_averaged_cross_spectrum(
        "ev1", "ev2", dt=0.0625, segment_size=8.0
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    assert result["data"]["power_phase"] is not None


def test_power_spectrum_has_null_phase(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_power_spectrum("ev1", dt=0.0625)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    assert result["data"]["power_phase"] is None


def test_rebin_of_stored_cross_spectrum_serializes(loaded_state):
    svc = SpectrumService(loaded_state)
    created = svc.create_cross_spectrum("ev1", "ev2", dt=0.0625, output_name="cs1")
    assert created["success"], created
    rebinned = svc.rebin_spectrum("cs1", rebin_factor=0.1, log=True)
    assert rebinned["success"], rebinned
    json.dumps(rebinned, allow_nan=False)
```

- [x] **Step 2: Run to verify they fail**

Run: `pixi run -e dev pytest python-backend/tests/test_spectrum_service.py -v`
Expected: FAIL — `TypeError: Object of type complex is not JSON serializable` (cross-spectrum tests) and `KeyError: 'power_phase'` (power-spectrum test).

- [x] **Step 3: Implement the fix**

In `python-backend/services/spectrum_service.py`, add after the imports (below line 18):

```python
def _power_to_lists(power) -> tuple:
    """Split a (possibly complex) power array into JSON-safe magnitude and phase lists.

    Returns (power_list, phase_list_or_None). Non-finite values become None so
    strict JSON (and JS JSON.parse) never sees NaN/Infinity.
    """
    arr = np.asarray(power)
    if np.iscomplexobj(arr):
        mag = np.abs(arr)
        phase = np.angle(arr)
        return _finite_list(mag), _finite_list(phase)
    return _finite_list(arr.astype(float)), None


def _finite_list(arr) -> list:
    """Convert a float array to a list, replacing non-finite values with None."""
    values = np.asarray(arr, dtype=float)
    return [float(v) if np.isfinite(v) else None for v in values]
```

Replace the four response dict constructions:

1. `create_power_spectrum` (lines 64-72) — replace with:
```python
            power_list, phase_list = _power_to_lists(ps.power)
            ps_data = {
                "name": output_name,
                "freq": ps.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": norm,
                "n_freq": len(ps.freq),
                "df": float(ps.df),
                "freq_range": [float(ps.freq[0]), float(ps.freq[-1])],
            }
```

2. `create_averaged_power_spectrum` (lines 122-131) — replace with:
```python
            power_list, phase_list = _power_to_lists(ps.power)
            ps_data = {
                "name": output_name,
                "freq": ps.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": norm,
                "n_freq": len(ps.freq),
                "df": float(ps.df),
                "segment_size": segment_size,
                "n_segments": int(ps.m) if hasattr(ps, "m") else None,
            }
```

3. `create_cross_spectrum` (lines 200-207) — replace with:
```python
            power_list, phase_list = _power_to_lists(cs.power)
            cs_data = {
                "name": output_name,
                "freq": cs.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": norm,
                "n_freq": len(cs.freq),
                "df": float(cs.df),
            }
```

4. `create_averaged_cross_spectrum` (lines 281-289) — replace with:
```python
            power_list, phase_list = _power_to_lists(cs.power)
            cs_data = {
                "name": output_name,
                "freq": cs.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": norm,
                "n_freq": len(cs.freq),
                "df": float(cs.df),
                "segment_size": segment_size,
            }
```

5. `rebin_spectrum` (lines 409-414) — replace with:
```python
            power_list, phase_list = _power_to_lists(rebinned.power)
            data = {
                "name": output_name,
                "freq": rebinned.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "n_freq": len(rebinned.freq),
            }
```

- [x] **Step 4: Run to verify they pass**

Run: `pixi run -e dev pytest python-backend/tests/test_spectrum_service.py -v`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add python-backend/services/spectrum_service.py python-backend/tests/test_spectrum_service.py
git commit -m "fix: serialize complex cross-spectrum power as magnitude and phase"
```

---

### Task 4: Fix coherence and time lags (backend)

**Files:**
- Create: `python-backend/tests/test_timing_service.py`
- Modify: `python-backend/services/timing_service.py`

- [x] **Step 1: Write the failing tests**

`python-backend/tests/test_timing_service.py`:
```python
import json

import numpy as np

from services.timing_service import TimingService


def test_coherence_of_identical_signals_is_one(loaded_state):
    svc = TimingService(loaded_state)
    # An event list crossed with itself has coherence == 1 at all frequencies.
    result = svc.calculate_coherence("ev1", "ev1", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    coh = np.asarray(result["data"]["coherence"], dtype=float)
    assert np.all(coh <= 1.0 + 1e-6)
    assert np.median(coh) > 0.9


def test_coherence_includes_uncertainty(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_coherence("ev1", "ev2", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    data = result["data"]
    assert "coherence_err" in data
    if data["coherence_err"] is not None:
        assert len(data["coherence_err"]) == len(data["coherence"])


def test_time_lags_include_errors_and_serialize(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_time_lags("ev1", "ev2", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert "time_lags_err" in data
    assert len(data["freq"]) == len(data["time_lags"])
    if data["time_lags_err"] is not None:
        assert len(data["time_lags_err"]) == len(data["time_lags"])


def test_time_lags_freq_range_filters_all_arrays(loaded_state):
    svc = TimingService(loaded_state)
    full = svc.calculate_time_lags("ev1", "ev2", dt=0.0625, segment_size=8.0)
    sub = svc.calculate_time_lags(
        "ev1", "ev2", dt=0.0625, segment_size=8.0, freq_range=(0.5, 2.0)
    )
    assert sub["success"], sub
    freqs = np.asarray(sub["data"]["freq"], dtype=float)
    assert freqs.min() >= 0.5
    assert freqs.max() <= 2.0
    assert len(sub["data"]["freq"]) < len(full["data"]["freq"])
    assert len(sub["data"]["time_lags"]) == len(sub["data"]["freq"])
```

- [x] **Step 2: Run to verify they fail**

Run: `pixi run -e dev pytest python-backend/tests/test_timing_service.py -v`
Expected: FAIL — coherence values ≫ 1 (first test), `KeyError`/missing `coherence_err` and `time_lags_err`.

- [x] **Step 3: Implement the fix**

In `python-backend/services/timing_service.py`:

Add after the imports (below line 12):
```python
def _finite_list(arr) -> list:
    """Convert a float array to a list, replacing non-finite values with None."""
    values = np.asarray(arr, dtype=float)
    return [float(v) if np.isfinite(v) else None for v in values]
```

In `calculate_time_lags`, replace lines 215-230 (from `# Calculate time lags` through the `result_data = {...}` block) with:
```python
            # Stingray's time_lag() returns (lag, lag_err) for averaged spectra.
            lag_result = cs.time_lag()
            if isinstance(lag_result, tuple):
                time_lags, time_lags_err = lag_result
            else:
                time_lags, time_lags_err = lag_result, None

            freq = np.asarray(cs.freq, dtype=float)
            time_lags = np.real(np.asarray(time_lags))
            if time_lags_err is not None:
                time_lags_err = np.real(np.asarray(time_lags_err))

            if freq_range:
                mask = (freq >= freq_range[0]) & (freq <= freq_range[1])
                freq = freq[mask]
                time_lags = time_lags[mask]
                if time_lags_err is not None:
                    time_lags_err = time_lags_err[mask]

            result_data = {
                "name": output_name,
                "freq": freq.tolist(),
                "time_lags": _finite_list(time_lags),
                "time_lags_err": _finite_list(time_lags_err) if time_lags_err is not None else None,
                "freq_range": freq_range,
            }
```

In `calculate_coherence`, replace lines 304-311 (from `# Calculate coherence` through the `result_data = {...}` block) with:
```python
            # Stingray's coherence() returns (coherence, uncertainty) for
            # averaged cross spectra (Vaughan & Nowak 1997).
            coh_result = cs.coherence()
            if isinstance(coh_result, tuple):
                coherence_vals, coherence_err = coh_result
            else:
                coherence_vals, coherence_err = coh_result, None

            coherence_vals = np.real(np.asarray(coherence_vals))
            result_data = {
                "name": output_name,
                "freq": cs.freq.tolist(),
                "coherence": _finite_list(coherence_vals),
                "coherence_err": _finite_list(np.real(np.asarray(coherence_err)))
                if coherence_err is not None
                else None,
                "segment_size": segment_size,
                "n_segments": int(cs.m) if hasattr(cs, "m") else None,
            }
```

- [x] **Step 4: Run to verify they pass**

Run: `pixi run -e dev pytest python-backend/tests/test_timing_service.py -v`
Expected: PASS (4 tests). Also run the full suite: `pixi run -e dev pytest python-backend/tests -v` — all green.

- [x] **Step 5: Commit**

```bash
git add python-backend/services/timing_service.py python-backend/tests/test_timing_service.py
git commit -m "fix: use stingray coherence() and time_lag() with uncertainties"
```

---

### Task 5: Light-curve plot decimation (backend)

**Files:**
- Create: `python-backend/tests/test_lightcurve_service.py`
- Modify: `python-backend/services/lightcurve_service.py`, `python-backend/routes/lightcurve_routes.py`

- [x] **Step 1: Write the failing tests**

`python-backend/tests/test_lightcurve_service.py`:
```python
import json

from services.lightcurve_service import LightcurveService


def test_decimation_caps_returned_points(loaded_state):
    svc = LightcurveService(loaded_state)
    # 64 s span at dt=0.001 -> 64000 bins; cap at 5000 plot points.
    result = svc.create_lightcurve_from_event_list(
        "ev1", dt=0.001, output_name="lc_fine", max_points=5000
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["n_bins"] == 64000          # true resolution is reported
    assert len(data["time"]) <= 5000        # transferred arrays are capped
    assert data["plot_stride"] == 13        # ceil(64000 / 5000)
    assert len(data["time"]) == len(data["counts"])


def test_no_decimation_below_cap(loaded_state):
    svc = LightcurveService(loaded_state)
    result = svc.create_lightcurve_from_event_list("ev1", dt=1.0, output_name="lc_coarse")
    assert result["success"], result
    data = result["data"]
    assert data["plot_stride"] == 1
    assert len(data["time"]) == data["n_bins"]


def test_get_lightcurve_data_decimates(loaded_state):
    svc = LightcurveService(loaded_state)
    svc.create_lightcurve_from_event_list("ev1", dt=0.001, output_name="lc_fine2")
    result = svc.get_lightcurve_data("lc_fine2", max_points=1000)
    assert result["success"], result
    assert len(result["data"]["time"]) <= 1000
    assert result["data"]["plot_stride"] == 64
```

- [x] **Step 2: Run to verify they fail**

Run: `pixi run -e dev pytest python-backend/tests/test_lightcurve_service.py -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'max_points'`.

- [x] **Step 3: Implement decimation in the service**

In `python-backend/services/lightcurve_service.py`:

Add after the imports (below line 12):
```python
# Cap on points transferred for plotting. The full-resolution Lightcurve stays
# in StateManager; only the JSON payload is strided.
DEFAULT_MAX_PLOT_POINTS = 200_000


def _decimate_for_plot(time, counts, max_points):
    """Stride-decimate arrays for display. Returns (time, counts, stride)."""
    n = len(time)
    if not max_points or n <= max_points:
        return time, counts, 1
    stride = int(np.ceil(n / max_points))
    return time[::stride], counts[::stride], stride
```

Change `create_lightcurve_from_event_list` signature (line 22-28) to:
```python
    def create_lightcurve_from_event_list(
        self,
        event_list_name: str,
        dt: float,
        output_name: str,
        gti: Optional[List[List[float]]] = None,
        max_points: Optional[int] = DEFAULT_MAX_PLOT_POINTS,
    ) -> Dict[str, Any]:
```
and replace its `lc_data = {...}` block (lines 64-72) with:
```python
            plot_time, plot_counts, stride = _decimate_for_plot(lc.time, lc.counts, max_points)
            lc_data = {
                "name": output_name,
                "time": plot_time.tolist(),
                "counts": plot_counts.tolist(),
                "dt": float(lc.dt),
                "n_bins": len(lc.time),
                "plot_stride": stride,
                "time_range": [float(lc.time.min()), float(lc.time.max())],
                "count_rate_mean": float(np.mean(lc.counts / lc.dt)),
            }
```

Change `rebin_lightcurve` signature (lines 130-135) to add `max_points: Optional[int] = DEFAULT_MAX_PLOT_POINTS,` after `output_name: str,` and replace its `lc_data = {...}` block (lines 162-168) with:
```python
            plot_time, plot_counts, stride = _decimate_for_plot(
                rebinned_lc.time, rebinned_lc.counts, max_points
            )
            lc_data = {
                "name": output_name,
                "time": plot_time.tolist(),
                "counts": plot_counts.tolist(),
                "dt": float(rebinned_lc.dt),
                "n_bins": len(rebinned_lc.time),
                "plot_stride": stride,
            }
```

Change `get_lightcurve_data` signature (line 181) to:
```python
    def get_lightcurve_data(
        self, name: str, max_points: Optional[int] = DEFAULT_MAX_PLOT_POINTS
    ) -> Dict[str, Any]:
```
and replace its `lc_data = {...}` block (lines 202-215) with:
```python
            plot_time, plot_counts, stride = _decimate_for_plot(lc.time, lc.counts, max_points)
            lc_data = {
                "name": name,
                "time": plot_time.tolist(),
                "counts": plot_counts.tolist(),
                "dt": float(lc.dt),
                "n_bins": len(lc.time),
                "plot_stride": stride,
                "time_range": [float(lc.time.min()), float(lc.time.max())],
                "count_stats": {
                    "mean": float(np.mean(lc.counts)),
                    "std": float(np.std(lc.counts)),
                    "min": float(np.min(lc.counts)),
                    "max": float(np.max(lc.counts)),
                },
            }
```

- [x] **Step 4: Plumb max_points through the routes**

In `python-backend/routes/lightcurve_routes.py`:

`CreateLightcurveFromEventListRequest` (lines 24-28) — add field:
```python
class CreateLightcurveFromEventListRequest(BaseModel):
    event_list_name: str
    dt: float
    output_name: str
    gti: Optional[List[List[float]]] = None
    max_points: Optional[int] = 200000
```

`RebinLightcurveRequest` (lines 38-41) — add field:
```python
class RebinLightcurveRequest(BaseModel):
    name: str
    rebin_factor: float
    output_name: str
    max_points: Optional[int] = 200000
```

Pass them through in the handlers: in `create_lightcurve_from_event_list` add `max_points=request.max_points,` to the service call; in `rebin_lightcurve` add `max_points=request.max_points,`; change `get_lightcurve_data` (lines 86-92) to:
```python
@router.get("/{name}")
async def get_lightcurve_data(
    name: str,
    max_points: int = 200000,
    service: LightcurveService = Depends(get_lightcurve_service),
):
    """Get lightcurve data for plotting."""
    return service.get_lightcurve_data(name, max_points=max_points)
```

- [x] **Step 5: Run to verify they pass**

Run: `pixi run -e dev pytest python-backend/tests -v`
Expected: PASS (all tests, including previous tasks').

- [x] **Step 6: Commit**

```bash
git add python-backend/services/lightcurve_service.py python-backend/routes/lightcurve_routes.py python-backend/tests/test_lightcurve_service.py
git commit -m "feat: add server-side plot decimation for large lightcurves"
```

---

### Task 6: Unblock the event loop in analysis routes

**Files:**
- Create: `python-backend/tests/test_route_concurrency.py`
- Modify: `python-backend/routes/lightcurve_routes.py`, `python-backend/routes/spectrum_routes.py`, `python-backend/routes/timing_routes.py`

- [x] **Step 1: Write the failing test**

`python-backend/tests/test_route_concurrency.py`:
```python
"""Verify analysis routes run blocking work off the event loop.

A handler that calls the synchronous service directly blocks the loop, so a
concurrent "/" request cannot complete until the slow call finishes. With
asyncio.to_thread, the probe returns immediately.
"""

import asyncio
import time

import httpx
import pytest

from services.state_manager import StateManager
from utils.performance_monitor import PerformanceMonitor


@pytest.mark.asyncio
async def test_lightcurve_create_does_not_block_event_loop(monkeypatch):
    import services.lightcurve_service as lcs_mod
    from main import create_app

    def slow_create(self, **kwargs):
        time.sleep(0.6)
        return {"success": True, "data": None, "message": "ok", "error": None}

    monkeypatch.setattr(
        lcs_mod.LightcurveService, "create_lightcurve_from_event_list", slow_create
    )

    app = create_app()
    # ASGITransport does not run the lifespan; provide state manually.
    app.state.state_manager = StateManager()
    app.state.performance_monitor = PerformanceMonitor()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        slow_task = asyncio.create_task(
            client.post(
                "/api/lightcurve/from-event-list",
                json={"event_list_name": "x", "dt": 0.1, "output_name": "y"},
            )
        )
        await asyncio.sleep(0.05)  # let the slow handler start

        t0 = time.monotonic()
        probe = await client.get("/")
        elapsed = time.monotonic() - t0

        slow_response = await slow_task
        assert probe.status_code == 200
        assert slow_response.status_code == 200
        # Without to_thread the probe waits ~0.55s for the loop to free up.
        assert elapsed < 0.4, f"event loop was blocked for {elapsed:.2f}s"
```

- [x] **Step 2: Run to verify it fails**

Run: `pixi run -e dev pytest python-backend/tests/test_route_concurrency.py -v`
Expected: FAIL — `event loop was blocked for ~0.55s`. (If it fails with an import error on `create_app`, check `python-backend/main.py:86` for the factory name.)

- [x] **Step 3: Wrap service calls in asyncio.to_thread**

Pattern (matches `data_routes.py`): add `import asyncio` to the imports of each file, and change every handler that calls a service method doing computation from `return service.method(...)` to `return await asyncio.to_thread(service.method, ...)` with the same keyword arguments.

`python-backend/routes/lightcurve_routes.py` — wrap all 6 handlers. Example for the first:
```python
import asyncio
```
```python
@router.post("/from-event-list")
async def create_lightcurve_from_event_list(
    request: CreateLightcurveFromEventListRequest,
    service: LightcurveService = Depends(get_lightcurve_service),
):
    """Create a Lightcurve from an EventList."""
    return await asyncio.to_thread(
        service.create_lightcurve_from_event_list,
        event_list_name=request.event_list_name,
        dt=request.dt,
        output_name=request.output_name,
        gti=request.gti,
        max_points=request.max_points,
    )
```
Apply the same transformation to `create_lightcurve_from_arrays`, `rebin_lightcurve`, `get_lightcurve_data` (`await asyncio.to_thread(service.get_lightcurve_data, name, max_points=max_points)`), `list_lightcurves`, and `delete_lightcurve`.

`python-backend/routes/spectrum_routes.py` — same for all 8 handlers (`create_power_spectrum`, `create_averaged_power_spectrum`, `create_cross_spectrum`, `create_averaged_cross_spectrum`, `create_dynamical_power_spectrum`, `rebin_spectrum`, `list_spectra`, `delete_spectrum`), preserving each handler's existing keyword arguments.

`python-backend/routes/timing_routes.py` — same for all 4 handlers (`create_bispectrum`, `calculate_power_colors`, `calculate_time_lags`, `calculate_coherence`).

- [x] **Step 4: Run to verify it passes**

Run: `pixi run -e dev pytest python-backend/tests -v`
Expected: PASS (all backend tests).

- [x] **Step 5: Commit**

```bash
git add python-backend/routes/lightcurve_routes.py python-backend/routes/spectrum_routes.py python-backend/routes/timing_routes.py python-backend/tests/test_route_concurrency.py
git commit -m "fix: run analysis routes in worker threads to keep event loop responsive"
```

---

### Task 7: Frontend API type updates

**Files:**
- Modify: `src/api/lightcurveApi.ts`, `src/api/spectrumApi.ts`, `src/api/timingApi.ts`

- [x] **Step 1: Update the types and params**

`src/api/spectrumApi.ts` — in `PowerSpectrumData` (lines 8-18), add after `power: number[];`:
```ts
  power_phase?: Array<number | null> | null;
```

`src/api/timingApi.ts` — replace `TimeLagsData` and `CoherenceData` (lines 27-38) with:
```ts
export interface TimeLagsData {
  name: string | null;
  freq: number[];
  time_lags: Array<number | null>;
  time_lags_err?: Array<number | null> | null;
  freq_range: [number, number] | null;
}

export interface CoherenceData {
  name: string | null;
  freq: number[];
  coherence: Array<number | null>;
  coherence_err?: Array<number | null> | null;
  segment_size?: number;
  n_segments?: number | null;
}
```

`src/api/lightcurveApi.ts`:
- In `LightcurveData` (lines 8-22), add after `n_bins: number;`:
```ts
  plot_stride?: number;
```
- In `createFromEventList`, add `max_points?: number;` to the params type and `max_points: params.max_points,` to the POST body.
- In `rebin`, add `max_points?: number;` to the params type and `max_points: params.max_points,` to the POST body.
- Replace `getLightcurveData` with:
```ts
  /**
   * Get lightcurve data for plotting
   */
  async getLightcurveData(
    name: string,
    maxPoints?: number
  ): Promise<ApiResponse<LightcurveData>> {
    const query = maxPoints ? `?max_points=${maxPoints}` : '';
    return apiClient.get(`/api/lightcurve/${name}${query}`);
  },
```

- [x] **Step 2: Verify**

Run: `npm run typecheck && npm run lint`
Expected: both exit 0.

- [x] **Step 3: Commit**

```bash
git add src/api/lightcurveApi.ts src/api/spectrumApi.ts src/api/timingApi.ts
git commit -m "feat: extend api types for phase, uncertainties, and plot decimation"
```

---

### Task 8: PlotlyChart shared component

**Files:**
- Create: `src/components/plots/PlotlyChart.tsx`, `src/components/plots/PlotlyChart.test.tsx`

- [x] **Step 1: Write the failing test**

`src/components/plots/PlotlyChart.test.tsx`:
```tsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('react-plotly.js', () => ({
  default: ({ data, layout }: { data: unknown[]; layout: Record<string, unknown> }) => (
    <div
      data-testid="plotly-mock"
      data-traces={data.length}
      data-xtype={(layout.xaxis as { type?: string })?.type ?? 'linear'}
    />
  ),
}));

import PlotlyChart from './PlotlyChart';

describe('PlotlyChart', () => {
  it('renders traces and merges page layout over theme defaults', async () => {
    render(
      <PlotlyChart
        data={[{ x: [1, 2], y: [3, 4], type: 'scatter' }]}
        layout={{ xaxis: { type: 'log' } }}
      />
    );
    await waitFor(() => expect(screen.getByTestId('plotly-mock')).toBeInTheDocument());
    expect(screen.getByTestId('plotly-mock').dataset.traces).toBe('1');
    expect(screen.getByTestId('plotly-mock').dataset.xtype).toBe('log');
  });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `npm test -- --run src/components/plots`
Expected: FAIL — cannot resolve `./PlotlyChart`.

- [x] **Step 3: Implement**

`src/components/plots/PlotlyChart.tsx`:
```tsx
import React, { Suspense } from 'react';
import { Box, CircularProgress, useTheme } from '@mui/material';
import type { Config, Data, Layout } from 'plotly.js';

// plotly.js is ~3 MB; load it only when a page actually renders a chart.
const Plot = React.lazy(() => import('react-plotly.js'));

export interface PlotlyChartProps {
  data: Data[];
  layout?: Partial<Layout>;
  height?: number | string;
}

const PlotlyChart: React.FC<PlotlyChartProps> = ({ data, layout = {}, height = 440 }) => {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';
  const gridColor = isDark ? 'rgba(148, 163, 184, 0.12)' : 'rgba(100, 116, 139, 0.2)';

  const mergedLayout: Partial<Layout> = {
    autosize: true,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family: '"IBM Plex Sans", sans-serif',
      size: 12,
      color: theme.palette.text.primary,
    },
    margin: { l: 64, r: 24, t: 24, b: 52 },
    showlegend: false,
    ...layout,
    xaxis: { gridcolor: gridColor, zeroline: false, ...layout.xaxis },
    yaxis: { gridcolor: gridColor, zeroline: false, ...layout.yaxis },
  };

  const config: Partial<Config> = {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
  };

  return (
    <Suspense
      fallback={
        <Box sx={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <CircularProgress size={28} />
        </Box>
      }
    >
      <Plot
        data={data}
        layout={mergedLayout}
        config={config}
        useResizeHandler
        style={{ width: '100%', height }}
      />
    </Suspense>
  );
};

export default PlotlyChart;
```

- [x] **Step 4: Run to verify it passes**

Run: `npm test -- --run src/components/plots && npm run typecheck`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/components/plots/
git commit -m "feat: add theme-aware lazy-loaded PlotlyChart component"
```

---

### Task 9: useEventLists hook + EventListSelector

**Files:**
- Create: `src/hooks/useEventLists.ts`, `src/hooks/useEventLists.test.tsx`, `src/components/analysis/EventListSelector.tsx`, `src/components/analysis/EventListSelector.test.tsx`

- [x] **Step 1: Write the failing hook test**

`src/hooks/useEventLists.test.tsx`:
```tsx
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...args: unknown[]) => listEventLists(...args) },
}));

import { useEventLists } from './useEventLists';

const wrapper = ({ children }: { children: React.ReactNode }): React.ReactElement => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

describe('useEventLists', () => {
  beforeEach(() => listEventLists.mockReset());

  it('returns event list summaries on success', async () => {
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'ev1', n_events: 10, time_range: [0, 1] }],
      message: '',
      error: null,
    });
    const { result } = renderHook(() => useEventLists(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].name).toBe('ev1');
  });

  it('surfaces a success:false response as a query error', async () => {
    listEventLists.mockResolvedValue({ success: false, data: null, message: 'boom', error: 'boom' });
    const { result } = renderHook(() => useEventLists(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toBe('boom');
  });
});
```

- [x] **Step 2: Run to verify it fails, then implement the hook**

Run: `npm test -- --run src/hooks/useEventLists` → FAIL (module not found).

`src/hooks/useEventLists.ts`:
```ts
import { useQuery } from '@tanstack/react-query';
import { dataApi, EventListSummary } from '@/api/dataApi';

export const EVENT_LISTS_QUERY_KEY = ['eventLists'] as const;

/**
 * Loaded event lists from the backend. The ApiClient re-resolves the backend
 * port on every request, so this works without gating on backend readiness;
 * failures surface as query errors with a retry affordance in the UI.
 */
export function useEventLists() {
  return useQuery({
    queryKey: EVENT_LISTS_QUERY_KEY,
    queryFn: async (): Promise<EventListSummary[]> => {
      const res = await dataApi.listEventLists();
      if (!res.success) {
        throw new Error(res.error || res.message || 'Failed to list event lists');
      }
      return res.data ?? [];
    },
    staleTime: 5_000,
  });
}
```

Run: `npm test -- --run src/hooks/useEventLists` → PASS.

- [x] **Step 3: Write the failing selector test**

`src/components/analysis/EventListSelector.test.tsx`:
```tsx
import React, { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...args: unknown[]) => listEventLists(...args) },
}));

import EventListSelector from './EventListSelector';

const Harness: React.FC = () => {
  const [value, setValue] = useState('');
  return <EventListSelector label="Event list" value={value} onChange={setValue} />;
};

describe('EventListSelector', () => {
  beforeEach(() => listEventLists.mockReset());

  it('lists loaded event lists and selects one', async () => {
    listEventLists.mockResolvedValue({
      success: true,
      data: [
        { name: 'obs1', n_events: 1000, time_range: [0, 10] },
        { name: 'obs2', n_events: 2000, time_range: [0, 20] },
      ],
      message: '',
      error: null,
    });
    renderWithProviders(<Harness />);
    const select = await screen.findByLabelText('Event list');
    await userEvent.click(select);
    await userEvent.click(await screen.findByText(/obs2/));
    await waitFor(() => expect(screen.getByLabelText('Event list')).toHaveTextContent('obs2'));
  });

  it('shows an empty-state prompt linking to data ingestion', async () => {
    listEventLists.mockResolvedValue({ success: true, data: [], message: '', error: null });
    renderWithProviders(<Harness />);
    expect(await screen.findByText(/No event lists loaded/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Load data/ })).toHaveAttribute(
      'href',
      '/data-ingestion'
    );
  });
});
```

- [x] **Step 4: Run to verify it fails, then implement the selector**

Run: `npm test -- --run src/components/analysis` → FAIL.

`src/components/analysis/EventListSelector.tsx`:
```tsx
import React from 'react';
import {
  Alert,
  Box,
  CircularProgress,
  FormControl,
  IconButton,
  InputLabel,
  Link,
  MenuItem,
  Select,
  Tooltip,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { Link as RouterLink } from 'react-router-dom';
import { useEventLists } from '@/hooks/useEventLists';

interface EventListSelectorProps {
  label: string;
  value: string;
  onChange: (name: string) => void;
}

/** Dropdown of event lists currently loaded in the backend. */
const EventListSelector: React.FC<EventListSelectorProps> = ({ label, value, onChange }) => {
  const { data, isLoading, isError, error, refetch, isFetching } = useEventLists();

  const refreshButton = (
    <Tooltip title="Refresh list">
      <span>
        <IconButton size="small" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
        </IconButton>
      </span>
    </Tooltip>
  );

  if (isError) {
    return (
      <Alert severity="error" action={refreshButton}>
        Failed to load event lists: {error instanceof Error ? error.message : 'unknown error'}
      </Alert>
    );
  }

  if (!isLoading && (data?.length ?? 0) === 0) {
    return (
      <Alert severity="info" action={refreshButton}>
        No event lists loaded.{' '}
        <Link component={RouterLink} to="/data-ingestion">
          Load data
        </Link>{' '}
        first.
      </Alert>
    );
  }

  const labelId = `event-list-selector-${label.replace(/\s+/g, '-').toLowerCase()}`;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <FormControl fullWidth size="small" disabled={isLoading}>
        <InputLabel id={labelId}>{label}</InputLabel>
        <Select
          labelId={labelId}
          value={value}
          label={label}
          onChange={(e) => onChange(e.target.value)}
        >
          {(data ?? []).map((ev) => (
            <MenuItem key={ev.name} value={ev.name}>
              {ev.name} ({ev.n_events.toLocaleString()} events)
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      {refreshButton}
    </Box>
  );
};

export default EventListSelector;
```

Run: `npm test -- --run src/components/analysis src/hooks` → PASS.

- [x] **Step 5: Commit**

```bash
git add src/hooks/useEventLists.ts src/hooks/useEventLists.test.tsx src/components/analysis/
git commit -m "feat: add event list query hook and selector component"
```

---

### Task 10: useAnalysisRunner hook

**Files:**
- Create: `src/hooks/useAnalysisRunner.ts`, `src/hooks/useAnalysisRunner.test.tsx`

- [x] **Step 1: Write the failing test**

`src/hooks/useAnalysisRunner.test.tsx`:
```tsx
import { beforeEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useAnalysisRunner } from './useAnalysisRunner';
import { useUIStore } from '@/store/uiStore';

describe('useAnalysisRunner', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
  });

  it('stores the result and pushes a success notification', async () => {
    const { result } = renderHook(() => useAnalysisRunner<{ v: number }>('Test Op'));
    await act(async () => {
      await result.current.run(async () => ({
        success: true,
        data: { v: 42 },
        message: 'computed',
        error: null,
      }));
    });
    expect(result.current.result?.v).toBe(42);
    expect(result.current.running).toBe(false);
    expect(result.current.error).toBeNull();
    const notes = useUIStore.getState().notifications;
    expect(notes[0].type).toBe('success');
    expect(notes[0].title).toBe('Test Op');
  });

  it('captures success:false as an error and keeps the previous result', async () => {
    const { result } = renderHook(() => useAnalysisRunner<{ v: number }>('Test Op'));
    await act(async () => {
      await result.current.run(async () => ({
        success: true,
        data: { v: 1 },
        message: '',
        error: null,
      }));
    });
    await act(async () => {
      await result.current.run(async () => ({
        success: false,
        data: null,
        message: 'bad dt',
        error: 'bad dt',
      }));
    });
    expect(result.current.error).toBe('bad dt');
    expect(result.current.result?.v).toBe(1);
    expect(useUIStore.getState().notifications[0].type).toBe('error');
  });

  it('captures thrown errors (network failures)', async () => {
    const { result } = renderHook(() => useAnalysisRunner('Test Op'));
    await act(async () => {
      await result.current.run(async () => {
        throw new Error('connection refused');
      });
    });
    expect(result.current.error).toBe('connection refused');
  });
});
```

- [x] **Step 2: Run to verify it fails, then implement**

Run: `npm test -- --run src/hooks/useAnalysisRunner` → FAIL.

`src/hooks/useAnalysisRunner.ts`:
```ts
import { useCallback, useState } from 'react';
import { ApiResponse } from '@/api/client';
import { useUIStore } from '@/store/uiStore';

interface AnalysisRunnerState<T> {
  result: T | null;
  running: boolean;
  error: string | null;
}

/**
 * Owns the lifecycle of a single analysis request: running flag, last
 * successful result, last error, and success/error notifications.
 * On failure the previous result is kept so the plot doesn't vanish.
 */
export function useAnalysisRunner<T>(label: string) {
  const addNotification = useUIStore((s) => s.addNotification);
  const [state, setState] = useState<AnalysisRunnerState<T>>({
    result: null,
    running: false,
    error: null,
  });

  const run = useCallback(
    async (call: () => Promise<ApiResponse<T>>): Promise<void> => {
      setState((s) => ({ ...s, running: true, error: null }));
      try {
        const res = await call();
        if (res.success && res.data !== null) {
          setState({ result: res.data, running: false, error: null });
          addNotification({ type: 'success', title: label, message: res.message || 'Done' });
        } else {
          const msg = res.error || res.message || 'Operation failed';
          setState((s) => ({ ...s, running: false, error: msg }));
          addNotification({ type: 'error', title: label, message: msg });
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setState((s) => ({ ...s, running: false, error: msg }));
        addNotification({ type: 'error', title: label, message: msg });
      }
    },
    [label, addNotification]
  );

  const reset = useCallback((): void => {
    setState({ result: null, running: false, error: null });
  }, []);

  return { ...state, run, reset };
}
```

Run: `npm test -- --run src/hooks/useAnalysisRunner` → PASS.

- [x] **Step 3: Commit**

```bash
git add src/hooks/useAnalysisRunner.ts src/hooks/useAnalysisRunner.test.tsx
git commit -m "feat: add useAnalysisRunner request-lifecycle hook"
```

---

### Task 11: EventList page

**Files:**
- Modify: `src/pages/QuickLook/EventList/index.tsx`
- Create: `src/pages/QuickLook/EventList/index.test.tsx`

- [x] **Step 1: Write the failing test**

`src/pages/QuickLook/EventList/index.test.tsx`:
```tsx
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';

const listEventLists = vi.fn();
const getEventListInfo = vi.fn();
const getEventListFullPreview = vi.fn();
const deleteEventList = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: {
    listEventLists: (...a: unknown[]) => listEventLists(...a),
    getEventListInfo: (...a: unknown[]) => getEventListInfo(...a),
    getEventListFullPreview: (...a: unknown[]) => getEventListFullPreview(...a),
    deleteEventList: (...a: unknown[]) => deleteEventList(...a),
  },
}));
vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import EventListPage from './index';

describe('EventListPage', () => {
  beforeEach(() => {
    listEventLists.mockReset();
    getEventListInfo.mockReset();
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    getEventListInfo.mockResolvedValue({
      success: true,
      data: {
        name: 'obs1',
        n_events: 5000,
        time_range: [0, 100],
        duration: 100,
        mjdref: 56000,
        gti_count: 2,
        gti_list: [
          [0, 40],
          [60, 100],
        ],
        mean_count_rate: 50,
      },
      message: '',
      error: null,
    });
  });

  it('lists event lists and shows details when one is selected', async () => {
    renderWithProviders(<EventListPage />);
    await userEvent.click(await screen.findByText(/obs1/));
    expect(await screen.findByText('Duration (s)')).toBeInTheDocument();
    expect(getEventListInfo).toHaveBeenCalledWith('obs1');
    // GTI table rows
    expect(await screen.findByText('Good Time Intervals')).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `npm test -- --run src/pages/QuickLook/EventList`
Expected: FAIL — page still renders the coming-soon placeholder, `obs1` never appears.

- [x] **Step 3: Implement the page**

Replace `src/pages/QuickLook/EventList/index.tsx` entirely with:
```tsx
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import DeleteIcon from '@mui/icons-material/Delete';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import { EVENT_LISTS_QUERY_KEY, useEventLists } from '@/hooks/useEventLists';
import { dataApi, EventListFullPreview, EventListInfo } from '@/api/dataApi';
import { useUIStore } from '@/store/uiStore';

const mono = { fontFamily: '"JetBrains Mono", monospace' };

const formatNum = (v: number | null | undefined, digits = 3): string =>
  v === null || v === undefined
    ? '—'
    : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });

const InfoRow: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, py: 0.5 }}>
    <Typography variant="body2" color="text.secondary">
      {label}
    </Typography>
    <Typography variant="body2" sx={mono}>
      {value}
    </Typography>
  </Box>
);

const EventListPage: React.FC = () => {
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const addNotification = useUIStore((s) => s.addNotification);
  const queryClient = useQueryClient();
  const { data: eventLists, isLoading, isError, error, refetch, isFetching } = useEventLists();

  const infoQuery = useQuery({
    queryKey: ['eventListInfo', selected],
    enabled: selected !== null,
    queryFn: async (): Promise<EventListInfo> => {
      const res = await dataApi.getEventListInfo(selected as string);
      if (!res.success || !res.data) throw new Error(res.error || res.message);
      return res.data;
    },
  });

  const previewQuery = useQuery({
    queryKey: ['eventListPreview', selected],
    enabled: selected !== null && tab === 1,
    queryFn: async (): Promise<EventListFullPreview> => {
      const res = await dataApi.getEventListFullPreview(selected as string);
      if (!res.success || !res.data) throw new Error(res.error || res.message);
      return res.data;
    },
  });

  const handleDelete = async (): Promise<void> => {
    if (!deleteTarget) return;
    const res = await dataApi.deleteEventList(deleteTarget);
    if (res.success) {
      addNotification({ type: 'success', title: 'Event List', message: `Deleted '${deleteTarget}'` });
      if (selected === deleteTarget) setSelected(null);
      await queryClient.invalidateQueries({ queryKey: EVENT_LISTS_QUERY_KEY });
    } else {
      addNotification({
        type: 'error',
        title: 'Event List',
        message: res.error || res.message || 'Delete failed',
      });
    }
    setDeleteTarget(null);
  };

  const info = infoQuery.data;
  const preview = previewQuery.data;

  return (
    <PageTemplate
      title="Event List"
      description="Inspect event lists loaded in the backend: metadata, GTIs, and arrival-time/energy distributions"
      category="Time Domain"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Typography variant="subtitle2">Loaded event lists</Typography>
                <Tooltip title="Refresh">
                  <span>
                    <IconButton size="small" onClick={() => refetch()} disabled={isFetching}>
                      {isFetching ? <CircularProgress size={16} /> : <RefreshIcon fontSize="small" />}
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
              {isError && (
                <Alert severity="error" sx={{ mt: 1 }}>
                  {error instanceof Error ? error.message : 'Failed to load'}
                </Alert>
              )}
              {isLoading && <CircularProgress size={20} sx={{ mt: 2 }} />}
              {!isLoading && (eventLists?.length ?? 0) === 0 && (
                <Alert severity="info" sx={{ mt: 1 }}>
                  Nothing loaded yet — use Data Ingestion first.
                </Alert>
              )}
              <List dense>
                {(eventLists ?? []).map((ev) => (
                  <ListItemButton
                    key={ev.name}
                    selected={ev.name === selected}
                    onClick={() => setSelected(ev.name)}
                  >
                    <ListItemText
                      primary={ev.name}
                      secondary={`${ev.n_events.toLocaleString()} events`}
                      primaryTypographyProps={{ sx: mono }}
                    />
                    <IconButton
                      edge="end"
                      size="small"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleteTarget(ev.name);
                      }}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </ListItemButton>
                ))}
              </List>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              {!selected && (
                <Box sx={{ py: 8, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Select an event list to inspect it.
                  </Typography>
                </Box>
              )}
              {selected && (
                <>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Typography variant="h6" sx={mono}>
                      {selected}
                    </Typography>
                    {info?.mission && <Chip size="small" label={info.mission} />}
                    {info?.instrument && <Chip size="small" label={info.instrument} variant="outlined" />}
                  </Box>
                  <Tabs value={tab} onChange={(_e, v: number) => setTab(v)} sx={{ mb: 2 }}>
                    <Tab label="Overview" />
                    <Tab label="Distributions" />
                  </Tabs>

                  {infoQuery.isError && (
                    <Alert severity="error">
                      {infoQuery.error instanceof Error ? infoQuery.error.message : 'Failed to load info'}
                    </Alert>
                  )}
                  {tab === 0 && infoQuery.isLoading && <CircularProgress size={24} />}

                  {tab === 0 && info && (
                    <Grid container spacing={3}>
                      <Grid item xs={12} sm={6}>
                        <InfoRow label="Events" value={formatNum(info.n_events, 0)} />
                        <InfoRow label="Duration (s)" value={formatNum(info.duration)} />
                        <InfoRow
                          label="Time range"
                          value={`${formatNum(info.time_range?.[0])} – ${formatNum(info.time_range?.[1])}`}
                        />
                        <InfoRow label="MJDREF" value={formatNum(info.mjdref, 6)} />
                        <InfoRow label="Mean rate (cts/s)" value={formatNum(info.mean_count_rate)} />
                        <InfoRow
                          label="Energy range (keV)"
                          value={
                            info.energy_range
                              ? `${formatNum(info.energy_range[0])} – ${formatNum(info.energy_range[1])}`
                              : '—'
                          }
                        />
                        <InfoRow label="GTI count" value={formatNum(info.gti_count, 0)} />
                        <InfoRow label="Total GTI time (s)" value={formatNum(info.total_gti_time)} />
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        {(info.validation_issues ?? [])
                          .filter((v) => v.severity === 'error' || v.severity === 'warning')
                          .map((v, i) => (
                            <Alert key={i} severity={v.severity === 'error' ? 'error' : 'warning'} sx={{ mb: 1 }}>
                              {v.message}
                            </Alert>
                          ))}
                        {info.notes && (
                          <Alert severity="info" icon={false}>
                            {info.notes}
                          </Alert>
                        )}
                      </Grid>
                      {(info.gti_list?.length ?? 0) > 0 && (
                        <Grid item xs={12}>
                          <Divider sx={{ mb: 1 }} />
                          <Typography variant="subtitle2" gutterBottom>
                            Good Time Intervals
                          </Typography>
                          <TableContainer sx={{ maxHeight: 260 }}>
                            <Table size="small" stickyHeader>
                              <TableHead>
                                <TableRow>
                                  <TableCell>#</TableCell>
                                  <TableCell>Start</TableCell>
                                  <TableCell>Stop</TableCell>
                                  <TableCell>Duration (s)</TableCell>
                                  <TableCell>Rate (cts/s)</TableCell>
                                </TableRow>
                              </TableHead>
                              <TableBody>
                                {(info.gti_list ?? []).map((g, i) => {
                                  const rate = info.per_gti_rates?.[i];
                                  return (
                                    <TableRow key={i}>
                                      <TableCell>{i + 1}</TableCell>
                                      <TableCell sx={mono}>{formatNum(g[0])}</TableCell>
                                      <TableCell sx={mono}>{formatNum(g[1])}</TableCell>
                                      <TableCell sx={mono}>{formatNum(g[1] - g[0])}</TableCell>
                                      <TableCell sx={mono}>{formatNum(rate?.rate)}</TableCell>
                                    </TableRow>
                                  );
                                })}
                              </TableBody>
                            </Table>
                          </TableContainer>
                        </Grid>
                      )}
                    </Grid>
                  )}

                  {tab === 1 && previewQuery.isLoading && <CircularProgress size={24} />}
                  {tab === 1 && previewQuery.isError && (
                    <Alert severity="error">
                      {previewQuery.error instanceof Error
                        ? previewQuery.error.message
                        : 'Failed to load preview'}
                    </Alert>
                  )}
                  {tab === 1 && preview && (
                    <Stack spacing={3}>
                      <Box>
                        <Typography variant="subtitle2" gutterBottom>
                          Arrival time distribution (preview sample)
                        </Typography>
                        <PlotlyChart
                          data={[
                            {
                              x: preview.times_preview,
                              type: 'histogram',
                              nbinsx: 200,
                              marker: { color: '#00d4aa' },
                            },
                          ]}
                          layout={{
                            xaxis: { title: { text: 'Time (s)' } },
                            yaxis: { title: { text: 'Events / bin' } },
                          }}
                          height={300}
                        />
                      </Box>
                      {preview.has_energy && preview.energy_preview && (
                        <Box>
                          <Typography variant="subtitle2" gutterBottom>
                            Energy distribution (preview sample)
                          </Typography>
                          <PlotlyChart
                            data={[
                              {
                                x: preview.energy_preview,
                                type: 'histogram',
                                nbinsx: 150,
                                marker: { color: '#3b82f6' },
                              },
                            ]}
                            layout={{
                              xaxis: { title: { text: 'Energy (keV)' } },
                              yaxis: { title: { text: 'Events / bin' } },
                            }}
                            height={300}
                          />
                        </Box>
                      )}
                    </Stack>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Dialog open={deleteTarget !== null} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete event list?</DialogTitle>
        <DialogContent>
          <Typography>
            Remove '{deleteTarget}' from backend memory? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={() => void handleDelete()}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </PageTemplate>
  );
};

export default EventListPage;
```

- [x] **Step 4: Run to verify it passes**

Run: `npm test -- --run src/pages/QuickLook/EventList && npm run typecheck && npm run lint`
Expected: PASS, no type or lint errors.

- [x] **Step 5: Manual verification**

Run `npm run dev`, load a sample file from `files/data/` via Data Ingestion, open QuickLook → Event List. Confirm: list shows the file, Overview shows real numbers and GTI table, Distributions tab renders two histograms, Delete removes it.

- [x] **Step 6: Commit**

```bash
git add src/pages/QuickLook/EventList/
git commit -m "feat: implement EventList QuickLook page"
```

---

### Task 12: Light Curve page

**Files:**
- Modify: `src/pages/QuickLook/LightCurve/index.tsx`
- Create: `src/pages/QuickLook/LightCurve/index.test.tsx`

- [x] **Step 1: Write the failing test**

`src/pages/QuickLook/LightCurve/index.test.tsx`:
```tsx
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...a: unknown[]) => listEventLists(...a) },
}));

const createFromEventList = vi.fn();
const listLightcurves = vi.fn();
const getLightcurveData = vi.fn();
const rebin = vi.fn();
const deleteLightcurve = vi.fn();
vi.mock('@/api/lightcurveApi', () => ({
  lightcurveApi: {
    createFromEventList: (...a: unknown[]) => createFromEventList(...a),
    listLightcurves: (...a: unknown[]) => listLightcurves(...a),
    getLightcurveData: (...a: unknown[]) => getLightcurveData(...a),
    rebin: (...a: unknown[]) => rebin(...a),
    deleteLightcurve: (...a: unknown[]) => deleteLightcurve(...a),
  },
}));
vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import LightCurvePage from './index';

describe('LightCurvePage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    listLightcurves.mockResolvedValue({ success: true, data: [], message: '', error: null });
    createFromEventList.mockResolvedValue({
      success: true,
      data: {
        name: 'obs1_lc',
        time: [0.5, 1.5, 2.5],
        counts: [10, 12, 9],
        dt: 1,
        n_bins: 3,
        plot_stride: 1,
        count_rate_mean: 10.3,
      },
      message: 'created',
      error: null,
    });
  });

  it('creates a light curve with parsed parameters and plots it', async () => {
    renderWithProviders(<LightCurvePage />);
    await userEvent.click(await screen.findByLabelText('Event list'));
    await userEvent.click(await screen.findByText(/obs1/));
    const dtField = screen.getByLabelText(/Time bin/);
    await userEvent.clear(dtField);
    await userEvent.type(dtField, '1.0');
    await userEvent.click(screen.getByRole('button', { name: /Generate/ }));
    await waitFor(() =>
      expect(createFromEventList).toHaveBeenCalledWith(
        expect.objectContaining({ event_list_name: 'obs1', dt: 1, output_name: 'obs1_lc' })
      )
    );
    expect(await screen.findByTestId('chart')).toBeInTheDocument();
  });

  it('disables Generate until inputs are valid', async () => {
    renderWithProviders(<LightCurvePage />);
    const button = await screen.findByRole('button', { name: /Generate/ });
    expect(button).toBeDisabled();
  });
});
```

- [x] **Step 2: Run to verify it fails**

Run: `npm test -- --run src/pages/QuickLook/LightCurve`
Expected: FAIL (placeholder page).

- [x] **Step 3: Implement the page**

Replace `src/pages/QuickLook/LightCurve/index.tsx` entirely with:
```tsx
import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import DeleteIcon from '@mui/icons-material/Delete';
import VisibilityIcon from '@mui/icons-material/Visibility';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { lightcurveApi, LightcurveData, LightcurveSummary } from '@/api/lightcurveApi';
import { parsePositiveNumber } from '@/utils/numbers';
import { useUIStore } from '@/store/uiStore';

const LIGHTCURVES_QUERY_KEY = ['lightcurves'] as const;

const LightCurvePage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('1.0');
  const [outputName, setOutputName] = useState('');
  const [existingSelection, setExistingSelection] = useState('');
  const [rebinFactor, setRebinFactor] = useState('2');
  const addNotification = useUIStore((s) => s.addNotification);
  const queryClient = useQueryClient();
  const { result, running, error, run } = useAnalysisRunner<LightcurveData>('Light Curve');

  const existingQuery = useQuery({
    queryKey: LIGHTCURVES_QUERY_KEY,
    queryFn: async (): Promise<LightcurveSummary[]> => {
      const res = await lightcurveApi.listLightcurves();
      if (!res.success) throw new Error(res.error || res.message);
      return res.data ?? [];
    },
  });

  // Any successful create/rebin changes the stored set — refresh the list.
  useEffect(() => {
    if (result) void queryClient.invalidateQueries({ queryKey: LIGHTCURVES_QUERY_KEY });
  }, [result, queryClient]);

  const dtNum = parsePositiveNumber(dt);
  const canRun = eventList !== '' && dtNum !== null && !running;
  const rebinNum = parsePositiveNumber(rebinFactor);

  const handleGenerate = (): void => {
    if (!dtNum || !eventList) return;
    const name = outputName.trim() || `${eventList}_lc`;
    void run(() =>
      lightcurveApi.createFromEventList({ event_list_name: eventList, dt: dtNum, output_name: name })
    );
  };

  const handleView = (): void => {
    if (!existingSelection) return;
    void run(() => lightcurveApi.getLightcurveData(existingSelection));
  };

  const handleRebin = (): void => {
    if (!result?.name || !rebinNum) return;
    void run(() =>
      lightcurveApi.rebin({
        name: result.name,
        rebin_factor: rebinNum,
        output_name: `${result.name}_r${rebinNum}`,
      })
    );
  };

  const handleDelete = async (name: string): Promise<void> => {
    const res = await lightcurveApi.deleteLightcurve(name);
    if (res.success) {
      addNotification({ type: 'success', title: 'Light Curve', message: `Deleted '${name}'` });
      await queryClient.invalidateQueries({ queryKey: LIGHTCURVES_QUERY_KEY });
    } else {
      addNotification({
        type: 'error',
        title: 'Light Curve',
        message: res.error || res.message || 'Delete failed',
      });
    }
  };

  const plotData: Data[] = result
    ? [
        {
          x: result.time,
          y: result.counts,
          type: 'scattergl',
          mode: 'lines',
          line: { color: '#00d4aa', width: 1 },
        },
      ]
    : [];

  return (
    <PageTemplate
      title="Light Curve"
      description="Bin event arrival times into a light curve, rebin it, and inspect stored light curves"
      category="Time Domain"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Generate from event list</Typography>
                <EventListSelector label="Event list" value={eventList} onChange={setEventList} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <TextField
                  label="Store as"
                  size="small"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                  placeholder={eventList ? `${eventList}_lc` : 'name'}
                />
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleGenerate}
                >
                  Generate
                </Button>
              </Stack>

              {result?.name && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Stack spacing={2}>
                    <Typography variant="subtitle2">Rebin '{result.name}'</Typography>
                    <TextField
                      label="Rebin factor (× dt)"
                      size="small"
                      value={rebinFactor}
                      onChange={(e) => setRebinFactor(e.target.value)}
                      error={rebinFactor !== '' && rebinNum === null}
                      helperText={
                        rebinFactor !== '' && rebinNum === null ? 'Must be a positive number' : ' '
                      }
                    />
                    <Button variant="outlined" disabled={!rebinNum || running} onClick={handleRebin}>
                      Rebin
                    </Button>
                  </Stack>
                </>
              )}

              <Divider sx={{ my: 2 }} />
              <Stack spacing={2}>
                <Typography variant="subtitle2">Stored light curves</Typography>
                <FormControl size="small" fullWidth>
                  <InputLabel id="existing-lc-label">Light curve</InputLabel>
                  <Select
                    labelId="existing-lc-label"
                    label="Light curve"
                    value={existingSelection}
                    onChange={(e) => setExistingSelection(e.target.value)}
                  >
                    {(existingQuery.data ?? []).map((lc) => (
                      <MenuItem key={lc.name} value={lc.name}>
                        {lc.name} ({lc.n_bins.toLocaleString()} bins)
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<VisibilityIcon />}
                    disabled={!existingSelection || running}
                    onClick={handleView}
                  >
                    View
                  </Button>
                  <Tooltip title="Delete selected">
                    <span>
                      <IconButton
                        size="small"
                        color="error"
                        disabled={!existingSelection}
                        onClick={() => {
                          void handleDelete(existingSelection);
                          setExistingSelection('');
                        }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                  {result?.name ? `Light curve: ${result.name}` : 'Result'}
                </Typography>
                {result && <Chip size="small" label={`${result.n_bins.toLocaleString()} bins`} />}
                {result && <Chip size="small" label={`dt = ${result.dt} s`} variant="outlined" />}
                {result?.count_rate_mean !== undefined && (
                  <Chip
                    size="small"
                    label={`mean ${result.count_rate_mean.toFixed(2)} cts/s`}
                    variant="outlined"
                  />
                )}
              </Box>
              {result?.plot_stride !== undefined && result.plot_stride > 1 && (
                <Alert severity="info" sx={{ mb: 1 }}>
                  Showing every {result.plot_stride}th bin for display performance (full resolution
                  is stored in the backend).
                </Alert>
              )}
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={plotData}
                  layout={{
                    xaxis: { title: { text: 'Time (s)' } },
                    yaxis: { title: { text: `Counts / ${result.dt} s bin` } },
                  }}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Generate a light curve or view a stored one.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default LightCurvePage;
```

- [x] **Step 4: Run to verify it passes**

Run: `npm test -- --run src/pages/QuickLook/LightCurve && npm run typecheck && npm run lint`
Expected: PASS.

- [x] **Step 5: Manual verification**

In the running app: generate a light curve from a loaded event list (dt=1), confirm plot + chips; rebin ×2, confirm new plot and that the stored list now contains both; view and delete stored curves.

- [x] **Step 6: Commit**

```bash
git add src/pages/QuickLook/LightCurve/
git commit -m "feat: implement Light Curve page with rebin and stored-curve viewer"
```

---

### Task 13: Power Spectrum page

**Files:**
- Modify: `src/pages/QuickLook/PowerSpectrum/index.tsx`

The pattern for all single-input spectrum pages. `lastStoredName` tracks the most recent result that was stored under a name, so Rebin always re-derives from the stored original (rebin responses themselves have `name: null` and are display-only).

- [x] **Step 1: Implement the page**

Replace `src/pages/QuickLook/PowerSpectrum/index.tsx` entirely with:
```tsx
import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { spectrumApi, PowerSpectrumData } from '@/api/spectrumApi';
import { parsePositiveNumber } from '@/utils/numbers';

const NORM_OPTIONS = ['leahy', 'frac', 'abs', 'none'];

const PowerSpectrumPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('0.0625');
  const [norm, setNorm] = useState('leahy');
  const [outputName, setOutputName] = useState('');
  const [logX, setLogX] = useState(true);
  const [logY, setLogY] = useState(true);
  const [rebinFactor, setRebinFactor] = useState('0.02');
  const [logRebin, setLogRebin] = useState(true);
  const [lastStoredName, setLastStoredName] = useState<string | null>(null);
  const { result, running, error, run } = useAnalysisRunner<PowerSpectrumData>('Power Spectrum');

  useEffect(() => {
    if (result?.name) setLastStoredName(result.name);
  }, [result]);

  const dtNum = parsePositiveNumber(dt);
  const rebinNum = parsePositiveNumber(rebinFactor);
  const canRun = eventList !== '' && dtNum !== null && !running;

  const handleRun = (): void => {
    if (!dtNum) return;
    void run(() =>
      spectrumApi.createPowerSpectrum({
        event_list_name: eventList,
        dt: dtNum,
        norm,
        output_name: outputName.trim() || undefined,
      })
    );
  };

  const handleRebin = (): void => {
    if (!lastStoredName || !rebinNum) return;
    void run(() =>
      spectrumApi.rebinSpectrum({ name: lastStoredName, rebin_factor: rebinNum, log: logRebin })
    );
  };

  const plotData: Data[] = result
    ? [
        {
          x: result.freq,
          y: result.power,
          type: 'scattergl',
          mode: 'lines',
          line: { color: '#00d4aa', width: 1 },
        },
      ]
    : [];

  return (
    <PageTemplate
      title="Power Spectrum"
      description="Compute a single (non-averaged) power spectrum from an event list"
      category="Frequency Domain"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Parameters</Typography>
                <EventListSelector label="Event list" value={eventList} onChange={setEventList} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <FormControl size="small">
                  <InputLabel id="ps-norm-label">Normalization</InputLabel>
                  <Select
                    labelId="ps-norm-label"
                    label="Normalization"
                    value={norm}
                    onChange={(e) => setNorm(e.target.value)}
                  >
                    {NORM_OPTIONS.map((n) => (
                      <MenuItem key={n} value={n}>
                        {n}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Store as (optional)"
                  size="small"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                  placeholder={eventList ? `${eventList}_ps` : ''}
                  helperText="Required to enable rebinning"
                />
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleRun}
                >
                  Compute
                </Button>
              </Stack>

              {lastStoredName && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Stack spacing={2}>
                    <Typography variant="subtitle2">Rebin '{lastStoredName}'</Typography>
                    <TextField
                      label={logRebin ? 'Log rebin fraction f' : 'Linear rebin factor'}
                      size="small"
                      value={rebinFactor}
                      onChange={(e) => setRebinFactor(e.target.value)}
                      error={rebinFactor !== '' && rebinNum === null}
                      helperText={logRebin ? 'Each bin grows by (1 + f)' : ' '}
                    />
                    <FormControlLabel
                      control={<Switch checked={logRebin} onChange={(e) => setLogRebin(e.target.checked)} />}
                      label="Logarithmic"
                    />
                    <Button variant="outlined" disabled={!rebinNum || running} onClick={handleRebin}>
                      Rebin
                    </Button>
                  </Stack>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                  Result
                </Typography>
                {result?.norm && <Chip size="small" label={`norm: ${result.norm}`} />}
                {result && <Chip size="small" label={`${result.n_freq.toLocaleString()} freqs`} variant="outlined" />}
                {result?.df !== undefined && (
                  <Chip size="small" label={`df = ${result.df.toPrecision(3)} Hz`} variant="outlined" />
                )}
                <FormControlLabel
                  control={<Switch size="small" checked={logX} onChange={(e) => setLogX(e.target.checked)} />}
                  label="log f"
                />
                <FormControlLabel
                  control={<Switch size="small" checked={logY} onChange={(e) => setLogY(e.target.checked)} />}
                  label="log P"
                />
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={plotData}
                  layout={{
                    xaxis: { title: { text: 'Frequency (Hz)' }, type: logX ? 'log' : 'linear' },
                    yaxis: { title: { text: 'Power' }, type: logY ? 'log' : 'linear' },
                  }}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose an event list and compute a power spectrum.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default PowerSpectrumPage;
```

- [x] **Step 2: Verify**

Run: `npm run typecheck && npm run lint && npm test -- --run`
Expected: all pass (existing tests unaffected).

- [x] **Step 3: Manual verification**

In the app: compute leahy PS at dt=0.0625 on a loaded event list — expect mean power ≈ 2 at high frequency for Poisson data. Store + rebin (log, f=0.02) and confirm the curve smooths.

- [x] **Step 4: Commit**

```bash
git add src/pages/QuickLook/PowerSpectrum/
git commit -m "feat: implement Power Spectrum page"
```

---

### Task 14: Averaged Power Spectrum page

**Files:**
- Modify: `src/pages/QuickLook/AvgPowerSpectrum/index.tsx`

- [x] **Step 1: Implement the page**

Replace `src/pages/QuickLook/AvgPowerSpectrum/index.tsx` entirely. It is the PowerSpectrum page (Task 13) with five deltas — apply them to a fresh copy of that component source:

1. Component name and export: `AvgPowerSpectrumPage`.
2. Add state below `dt`: `const [segmentSize, setSegmentSize] = useState('16');` and parse it: `const segNum = parsePositiveNumber(segmentSize);` and extend `canRun`: `const canRun = eventList !== '' && dtNum !== null && segNum !== null && !running;`
3. `handleRun` calls the averaged endpoint:
```tsx
  const handleRun = (): void => {
    if (!dtNum || !segNum) return;
    void run(() =>
      spectrumApi.createAveragedPowerSpectrum({
        event_list_name: eventList,
        dt: dtNum,
        segment_size: segNum,
        norm,
        output_name: outputName.trim() || undefined,
      })
    );
  };
```
4. Add a segment-size field after the dt TextField:
```tsx
                <TextField
                  label="Segment size (s)"
                  size="small"
                  value={segmentSize}
                  onChange={(e) => setSegmentSize(e.target.value)}
                  error={segmentSize !== '' && segNum === null}
                  helperText={segmentSize !== '' && segNum === null ? 'Must be a positive number' : ' '}
                />
```
5. Add a segments chip in the result header (after the `n_freq` chip):
```tsx
                {result?.n_segments != null && (
                  <Chip size="small" label={`${result.n_segments} segments`} variant="outlined" />
                )}
```
Also update `PageTemplate` props: `title="Averaged Power Spectrum"`, `description="Welch-style averaged power spectrum over fixed-length segments"`, label `'Averaged Power Spectrum'` in `useAnalysisRunner`, and placeholder `_aps` instead of `_ps`.

- [x] **Step 2: Verify**

Run: `npm run typecheck && npm run lint`
Expected: clean.

- [x] **Step 3: Manual verification**

Compute with dt=0.0625, segment=16 s: scatter should be visibly smaller than the single PS; segments chip shows a sensible count (~duration/16).

- [x] **Step 4: Commit**

```bash
git add src/pages/QuickLook/AvgPowerSpectrum/
git commit -m "feat: implement Averaged Power Spectrum page"
```

---

### Task 15: Cross Spectrum page

**Files:**
- Modify: `src/pages/QuickLook/CrossSpectrum/index.tsx`

- [x] **Step 1: Implement the page**

Replace `src/pages/QuickLook/CrossSpectrum/index.tsx` entirely with:
```tsx
import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { spectrumApi, PowerSpectrumData } from '@/api/spectrumApi';
import { parsePositiveNumber } from '@/utils/numbers';

const NORM_OPTIONS = ['leahy', 'frac', 'abs', 'none'];

const CrossSpectrumPage: React.FC = () => {
  const [eventList1, setEventList1] = useState('');
  const [eventList2, setEventList2] = useState('');
  const [dt, setDt] = useState('0.0625');
  const [norm, setNorm] = useState('leahy');
  const [outputName, setOutputName] = useState('');
  const [logX, setLogX] = useState(true);
  const [logY, setLogY] = useState(true);
  const [rebinFactor, setRebinFactor] = useState('0.02');
  const [logRebin, setLogRebin] = useState(true);
  const [lastStoredName, setLastStoredName] = useState<string | null>(null);
  const { result, running, error, run } = useAnalysisRunner<PowerSpectrumData>('Cross Spectrum');

  useEffect(() => {
    if (result?.name) setLastStoredName(result.name);
  }, [result]);

  const dtNum = parsePositiveNumber(dt);
  const rebinNum = parsePositiveNumber(rebinFactor);
  const canRun = eventList1 !== '' && eventList2 !== '' && dtNum !== null && !running;

  const handleRun = (): void => {
    if (!dtNum) return;
    void run(() =>
      spectrumApi.createCrossSpectrum({
        event_list_1_name: eventList1,
        event_list_2_name: eventList2,
        dt: dtNum,
        norm,
        output_name: outputName.trim() || undefined,
      })
    );
  };

  const handleRebin = (): void => {
    if (!lastStoredName || !rebinNum) return;
    void run(() =>
      spectrumApi.rebinSpectrum({ name: lastStoredName, rebin_factor: rebinNum, log: logRebin })
    );
  };

  const magnitudeTrace: Data[] = result
    ? [
        {
          x: result.freq,
          y: result.power,
          type: 'scattergl',
          mode: 'lines',
          line: { color: '#00d4aa', width: 1 },
        },
      ]
    : [];

  const phaseTrace: Data[] =
    result && result.power_phase
      ? [
          {
            x: result.freq,
            y: result.power_phase,
            type: 'scattergl',
            mode: 'markers',
            marker: { color: '#3b82f6', size: 3 },
          },
        ]
      : [];

  return (
    <PageTemplate
      title="Cross Spectrum"
      description="Cross spectrum between two event lists: magnitude and phase"
      category="Frequency Domain"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Parameters</Typography>
                <EventListSelector label="Event list 1" value={eventList1} onChange={setEventList1} />
                <EventListSelector label="Event list 2" value={eventList2} onChange={setEventList2} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <FormControl size="small">
                  <InputLabel id="cs-norm-label">Normalization</InputLabel>
                  <Select
                    labelId="cs-norm-label"
                    label="Normalization"
                    value={norm}
                    onChange={(e) => setNorm(e.target.value)}
                  >
                    {NORM_OPTIONS.map((n) => (
                      <MenuItem key={n} value={n}>
                        {n}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Store as (optional)"
                  size="small"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                  helperText="Required to enable rebinning"
                />
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleRun}
                >
                  Compute
                </Button>
              </Stack>

              {lastStoredName && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Stack spacing={2}>
                    <Typography variant="subtitle2">Rebin '{lastStoredName}'</Typography>
                    <TextField
                      label={logRebin ? 'Log rebin fraction f' : 'Linear rebin factor'}
                      size="small"
                      value={rebinFactor}
                      onChange={(e) => setRebinFactor(e.target.value)}
                    />
                    <FormControlLabel
                      control={<Switch checked={logRebin} onChange={(e) => setLogRebin(e.target.checked)} />}
                      label="Logarithmic"
                    />
                    <Button variant="outlined" disabled={!rebinNum || running} onClick={handleRebin}>
                      Rebin
                    </Button>
                  </Stack>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                  Result
                </Typography>
                {result?.norm && <Chip size="small" label={`norm: ${result.norm}`} />}
                {result && <Chip size="small" label={`${result.n_freq.toLocaleString()} freqs`} variant="outlined" />}
                <FormControlLabel
                  control={<Switch size="small" checked={logX} onChange={(e) => setLogX(e.target.checked)} />}
                  label="log f"
                />
                <FormControlLabel
                  control={<Switch size="small" checked={logY} onChange={(e) => setLogY(e.target.checked)} />}
                  label="log |C|"
                />
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <Stack spacing={2}>
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Cross-power magnitude
                    </Typography>
                    <PlotlyChart
                      data={magnitudeTrace}
                      layout={{
                        xaxis: { title: { text: 'Frequency (Hz)' }, type: logX ? 'log' : 'linear' },
                        yaxis: { title: { text: '|C(f)|' }, type: logY ? 'log' : 'linear' },
                      }}
                      height={320}
                    />
                  </Box>
                  {phaseTrace.length > 0 && (
                    <Box>
                      <Typography variant="caption" color="text.secondary">
                        Cross-spectrum phase
                      </Typography>
                      <PlotlyChart
                        data={phaseTrace}
                        layout={{
                          xaxis: { title: { text: 'Frequency (Hz)' }, type: logX ? 'log' : 'linear' },
                          yaxis: { title: { text: 'Phase (rad)' }, range: [-3.5, 3.5] },
                        }}
                        height={240}
                      />
                    </Box>
                  )}
                </Stack>
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose two event lists and compute their cross spectrum.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default CrossSpectrumPage;
```

- [x] **Step 2: Verify**

Run: `npm run typecheck && npm run lint`
Expected: clean.

- [x] **Step 3: Manual verification**

Load the same file twice under two names (or two different files), compute: magnitude plot renders, phase panel renders with values in [-π, π]. This exercises the Task 3 backend fix end-to-end.

- [x] **Step 4: Commit**

```bash
git add src/pages/QuickLook/CrossSpectrum/
git commit -m "feat: implement Cross Spectrum page with magnitude and phase"
```

---

### Task 16: Averaged Cross Spectrum page

**Files:**
- Modify: `src/pages/QuickLook/AvgCrossSpectrum/index.tsx`

- [x] **Step 1: Implement the page**

Replace `src/pages/QuickLook/AvgCrossSpectrum/index.tsx` entirely. It is the CrossSpectrum page (Task 15) with five deltas — apply them to a fresh copy of that component source:

1. Component name and export: `AvgCrossSpectrumPage`; runner label `'Averaged Cross Spectrum'`.
2. Add state below `dt`: `const [segmentSize, setSegmentSize] = useState('16');` plus `const segNum = parsePositiveNumber(segmentSize);` and extend `canRun` with `&& segNum !== null`.
3. `handleRun` calls:
```tsx
      spectrumApi.createAveragedCrossSpectrum({
        event_list_1_name: eventList1,
        event_list_2_name: eventList2,
        dt: dtNum,
        segment_size: segNum,
        norm,
        output_name: outputName.trim() || undefined,
      })
```
(guard becomes `if (!dtNum || !segNum) return;`)
4. Add the same segment-size TextField as Task 14 delta 4, after the dt field.
5. `PageTemplate` props: `title="Averaged Cross Spectrum"`, `description="Segment-averaged cross spectrum between two event lists"`; add a `segment_size` chip in the result header:
```tsx
                {result?.segment_size !== undefined && (
                  <Chip size="small" label={`segment ${result.segment_size} s`} variant="outlined" />
                )}
```

- [x] **Step 2: Verify**

Run: `npm run typecheck && npm run lint`
Expected: clean.

- [x] **Step 3: Manual verification**

Compute with segment=16 s on two loaded lists; phase scatter should be visibly less noisy than the single cross spectrum.

- [x] **Step 4: Commit**

```bash
git add src/pages/QuickLook/AvgCrossSpectrum/
git commit -m "feat: implement Averaged Cross Spectrum page"
```

---

### Task 17: Dynamical Power Spectrum page

**Files:**
- Modify: `src/pages/QuickLook/DynamicalPowerSpectrum/index.tsx`

- [x] **Step 1: Implement the page**

Replace `src/pages/QuickLook/DynamicalPowerSpectrum/index.tsx` entirely with:
```tsx
import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { spectrumApi, DynamicalPowerSpectrumData } from '@/api/spectrumApi';
import { parsePositiveNumber } from '@/utils/numbers';

const NORM_OPTIONS = ['leahy', 'frac', 'abs', 'none'];

const DynamicalPowerSpectrumPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('0.0625');
  const [segmentSize, setSegmentSize] = useState('8');
  const [norm, setNorm] = useState('leahy');
  const [outputName, setOutputName] = useState('');
  const [logZ, setLogZ] = useState(true);
  const { result, running, error, run } = useAnalysisRunner<DynamicalPowerSpectrumData>(
    'Dynamical Power Spectrum'
  );

  const dtNum = parsePositiveNumber(dt);
  const segNum = parsePositiveNumber(segmentSize);
  const canRun = eventList !== '' && dtNum !== null && segNum !== null && !running;

  const handleRun = (): void => {
    if (!dtNum || !segNum) return;
    void run(() =>
      spectrumApi.createDynamicalPowerSpectrum({
        event_list_name: eventList,
        dt: dtNum,
        segment_size: segNum,
        norm,
        output_name: outputName.trim() || undefined,
      })
    );
  };

  // dyn_ps rows correspond to frequencies (n_freq x n_times) — matches
  // Plotly's convention that z[i] pairs with y[i].
  const zValues: Array<Array<number | null>> | undefined = result
    ? logZ
      ? result.dyn_ps.map((row) => row.map((v) => (v > 0 ? Math.log10(v) : null)))
      : result.dyn_ps
    : undefined;

  const heatmap: Data[] =
    result && zValues
      ? [
          {
            z: zValues,
            x: result.time,
            y: result.freq,
            type: 'heatmap',
            colorscale: 'Viridis',
            colorbar: { title: { text: logZ ? 'log10 P' : 'Power' } },
          } as Data,
        ]
      : [];

  return (
    <PageTemplate
      title="Dynamical Power Spectrum"
      description="Time-resolved power spectrum: power as a function of time and frequency"
      category="Frequency Domain"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Parameters</Typography>
                <EventListSelector label="Event list" value={eventList} onChange={setEventList} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <TextField
                  label="Segment size (s)"
                  size="small"
                  value={segmentSize}
                  onChange={(e) => setSegmentSize(e.target.value)}
                  error={segmentSize !== '' && segNum === null}
                  helperText={segmentSize !== '' && segNum === null ? 'Must be a positive number' : ' '}
                />
                <FormControl size="small">
                  <InputLabel id="dps-norm-label">Normalization</InputLabel>
                  <Select
                    labelId="dps-norm-label"
                    label="Normalization"
                    value={norm}
                    onChange={(e) => setNorm(e.target.value)}
                  >
                    {NORM_OPTIONS.map((n) => (
                      <MenuItem key={n} value={n}>
                        {n}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Store as (optional)"
                  size="small"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                />
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleRun}
                >
                  Compute
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                  Result
                </Typography>
                {result && (
                  <Chip
                    size="small"
                    label={`${result.shape[0]} freqs × ${result.shape[1]} segments`}
                    variant="outlined"
                  />
                )}
                <FormControlLabel
                  control={<Switch size="small" checked={logZ} onChange={(e) => setLogZ(e.target.checked)} />}
                  label="log color"
                />
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={heatmap}
                  layout={{
                    xaxis: { title: { text: 'Time (s)' } },
                    yaxis: { title: { text: 'Frequency (Hz)' } },
                  }}
                  height={500}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Compute a dynamical power spectrum to see the time-frequency map.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default DynamicalPowerSpectrumPage;
```

- [x] **Step 2: Verify**

Run: `npm run typecheck && npm run lint`
Expected: clean.

- [x] **Step 3: Manual verification**

Compute with dt=0.0625, segment=8 s. Heatmap renders with time on x, frequency on y; toggling "log color" rescales.

- [x] **Step 4: Commit**

```bash
git add src/pages/QuickLook/DynamicalPowerSpectrum/
git commit -m "feat: implement Dynamical Power Spectrum page"
```

---

### Task 18: Bispectrum page

**Files:**
- Modify: `src/pages/QuickLook/Bispectrum/index.tsx`

- [x] **Step 1: Implement the page**

Replace `src/pages/QuickLook/Bispectrum/index.tsx` entirely with:
```tsx
import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { timingApi, BispectrumData } from '@/api/timingApi';
import { parsePositiveNumber } from '@/utils/numbers';

const SCALE_OPTIONS = ['biased', 'unbiased'];
const WINDOW_OPTIONS = ['uniform', 'parzen', 'hamming', 'hanning', 'triangular', 'welch', 'blackmann', 'flat-top'];

const BispectrumPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('0.1');
  const [maxlag, setMaxlag] = useState('25');
  const [scale, setScale] = useState('unbiased');
  const [windowFn, setWindowFn] = useState('uniform');
  const [outputName, setOutputName] = useState('');
  const [tab, setTab] = useState(0);
  const [logZ, setLogZ] = useState(true);
  const { result, running, error, run } = useAnalysisRunner<BispectrumData>('Bispectrum');

  const dtNum = parsePositiveNumber(dt);
  const maxlagNum = parsePositiveNumber(maxlag);
  const canRun = eventList !== '' && dtNum !== null && maxlagNum !== null && !running;

  const handleRun = (): void => {
    if (!dtNum || !maxlagNum) return;
    void run(() =>
      timingApi.createBispectrum({
        event_list_name: eventList,
        dt: dtNum,
        maxlag: Math.round(maxlagNum),
        scale,
        window: windowFn,
        output_name: outputName.trim() || undefined,
      })
    );
  };

  const buildHeatmap = (): Data[] => {
    if (!result) return [];
    if (tab === 0) {
      const z = logZ
        ? result.bispec_mag.map((row) => row.map((v) => (v > 0 ? Math.log10(v) : null)))
        : result.bispec_mag;
      return [
        {
          z,
          x: result.freq,
          y: result.freq,
          type: 'heatmap',
          colorscale: 'Viridis',
          colorbar: { title: { text: logZ ? 'log10 |B|' : '|B|' } },
        } as Data,
      ];
    }
    return [
      {
        z: result.bispec_phase,
        x: result.freq,
        y: result.freq,
        type: 'heatmap',
        colorscale: 'RdBu',
        zmid: 0,
        colorbar: { title: { text: 'Phase (rad)' } },
      } as Data,
    ];
  };

  return (
    <PageTemplate
      title="Bispectrum"
      description="Third-order spectrum revealing nonlinear interactions and phase coupling"
      category="Advanced Analysis"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Parameters</Typography>
                <EventListSelector label="Event list" value={eventList} onChange={setEventList} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <TextField
                  label="Max lag (bins)"
                  size="small"
                  value={maxlag}
                  onChange={(e) => setMaxlag(e.target.value)}
                  error={maxlag !== '' && maxlagNum === null}
                  helperText="Bispectrum size is (2·maxlag+1)²; keep ≤ 100"
                />
                <FormControl size="small">
                  <InputLabel id="bs-scale-label">Scale</InputLabel>
                  <Select
                    labelId="bs-scale-label"
                    label="Scale"
                    value={scale}
                    onChange={(e) => setScale(e.target.value)}
                  >
                    {SCALE_OPTIONS.map((s) => (
                      <MenuItem key={s} value={s}>
                        {s}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small">
                  <InputLabel id="bs-window-label">Window</InputLabel>
                  <Select
                    labelId="bs-window-label"
                    label="Window"
                    value={windowFn}
                    onChange={(e) => setWindowFn(e.target.value)}
                  >
                    {WINDOW_OPTIONS.map((w) => (
                      <MenuItem key={w} value={w}>
                        {w}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Store as (optional)"
                  size="small"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                />
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleRun}
                >
                  Compute
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Tabs value={tab} onChange={(_e, v: number) => setTab(v)} sx={{ flexGrow: 1 }}>
                  <Tab label="Magnitude" />
                  <Tab label="Phase" />
                </Tabs>
                {result && <Chip size="small" label={`maxlag ${result.maxlag}`} variant="outlined" />}
                {result && <Chip size="small" label={result.window} variant="outlined" />}
                {tab === 0 && (
                  <FormControlLabel
                    control={<Switch size="small" checked={logZ} onChange={(e) => setLogZ(e.target.checked)} />}
                    label="log color"
                  />
                )}
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={buildHeatmap()}
                  layout={{
                    xaxis: { title: { text: 'Frequency f1 (Hz)' } },
                    yaxis: { title: { text: 'Frequency f2 (Hz)' } },
                  }}
                  height={520}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Compute a bispectrum to see magnitude and phase maps.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default BispectrumPage;
```

- [x] **Step 2: Verify**

Run: `npm run typecheck && npm run lint`
Expected: clean.

- [x] **Step 3: Manual verification**

Compute with dt=0.1, maxlag=25: Magnitude tab shows a (51×51) heatmap, Phase tab a diverging map. Computation may take a while — confirm the log panel stays live (Task 6 fix).

- [x] **Step 4: Commit**

```bash
git add src/pages/QuickLook/Bispectrum/
git commit -m "feat: implement Bispectrum page with magnitude/phase heatmaps"
```

---

### Task 19: Coherence page

**Files:**
- Modify: `src/pages/QuickLook/Coherence/index.tsx`

- [x] **Step 1: Implement the page**

Replace `src/pages/QuickLook/Coherence/index.tsx` entirely with:
```tsx
import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  FormControlLabel,
  Grid,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { timingApi, CoherenceData } from '@/api/timingApi';
import { parsePositiveNumber } from '@/utils/numbers';

const CoherencePage: React.FC = () => {
  const [eventList1, setEventList1] = useState('');
  const [eventList2, setEventList2] = useState('');
  const [dt, setDt] = useState('0.0625');
  const [segmentSize, setSegmentSize] = useState('16');
  const [logX, setLogX] = useState(true);
  const { result, running, error, run } = useAnalysisRunner<CoherenceData>('Coherence');

  const dtNum = parsePositiveNumber(dt);
  const segNum = parsePositiveNumber(segmentSize);
  const canRun = eventList1 !== '' && eventList2 !== '' && dtNum !== null && segNum !== null && !running;

  const handleRun = (): void => {
    if (!dtNum || !segNum) return;
    void run(() =>
      timingApi.calculateCoherence({
        event_list_1_name: eventList1,
        event_list_2_name: eventList2,
        dt: dtNum,
        segment_size: segNum,
      })
    );
  };

  const traces: Data[] = result
    ? [
        {
          x: result.freq,
          y: result.coherence,
          type: 'scattergl',
          mode: 'lines+markers',
          marker: { size: 4, color: '#00d4aa' },
          line: { color: '#00d4aa', width: 1 },
          error_y: result.coherence_err
            ? { type: 'data', array: result.coherence_err, visible: true, color: 'rgba(0, 212, 170, 0.35)' }
            : undefined,
        } as Data,
      ]
    : [];

  return (
    <PageTemplate
      title="Coherence"
      description="Frequency-resolved linear correlation between two event lists (Vaughan & Nowak 1997)"
      category="Frequency Domain"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Parameters</Typography>
                <EventListSelector label="Event list 1" value={eventList1} onChange={setEventList1} />
                <EventListSelector label="Event list 2" value={eventList2} onChange={setEventList2} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText={dt !== '' && dtNum === null ? 'Must be a positive number' : ' '}
                />
                <TextField
                  label="Segment size (s)"
                  size="small"
                  value={segmentSize}
                  onChange={(e) => setSegmentSize(e.target.value)}
                  error={segmentSize !== '' && segNum === null}
                  helperText={segmentSize !== '' && segNum === null ? 'Must be a positive number' : ' '}
                />
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleRun}
                >
                  Compute
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
                  Result
                </Typography>
                {result?.n_segments != null && (
                  <Chip size="small" label={`${result.n_segments} segments`} variant="outlined" />
                )}
                <FormControlLabel
                  control={<Switch size="small" checked={logX} onChange={(e) => setLogX(e.target.checked)} />}
                  label="log f"
                />
              </Box>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <PlotlyChart
                  data={traces}
                  layout={{
                    xaxis: { title: { text: 'Frequency (Hz)' }, type: logX ? 'log' : 'linear' },
                    yaxis: { title: { text: 'Coherence γ²' }, range: [0, 1.2] },
                    shapes: [
                      {
                        type: 'line',
                        xref: 'paper',
                        x0: 0,
                        x1: 1,
                        yref: 'y',
                        y0: 1,
                        y1: 1,
                        line: { color: 'rgba(148, 163, 184, 0.5)', width: 1, dash: 'dash' },
                      },
                    ],
                  }}
                />
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Choose two event lists and compute their coherence.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default CoherencePage;
```

- [x] **Step 2: Verify**

Run: `npm run typecheck && npm run lint`
Expected: clean.

- [x] **Step 3: Manual verification**

Compute coherence of an event list with itself (load the same file under two names): values cluster at 1.0 (this directly validates the Task 4 fix). With two unrelated lists, values are low.

- [x] **Step 4: Commit**

```bash
git add src/pages/QuickLook/Coherence/
git commit -m "feat: implement Coherence page with uncertainties"
```

---

### Task 20: Time Lags page (new route + nav)

**Files:**
- Create: `src/pages/QuickLook/TimeLags/index.tsx`
- Modify: `src/App.tsx`, `src/components/layout/Sidebar.tsx`

- [x] **Step 1: Implement the page**

Create `src/pages/QuickLook/TimeLags/index.tsx`. It is the Coherence page (Task 19) with these deltas applied to a fresh copy of that component source:

1. Component name/export `TimeLagsPage`; runner type `TimeLagsData`; label `'Time Lags'`; import `{ timingApi, TimeLagsData }` and additionally `{ parseNumber }` from `@/utils/numbers`.
2. Add optional frequency-range state after `segmentSize`:
```tsx
  const [freqMin, setFreqMin] = useState('');
  const [freqMax, setFreqMax] = useState('');
```
and parse: `const fMin = parseNumber(freqMin); const fMax = parseNumber(freqMax);`
3. `handleRun` becomes:
```tsx
  const handleRun = (): void => {
    if (!dtNum || !segNum) return;
    const freq_range: [number, number] | undefined =
      fMin !== null && fMax !== null && fMax > fMin ? [fMin, fMax] : undefined;
    void run(() =>
      timingApi.calculateTimeLags({
        event_list_1_name: eventList1,
        event_list_2_name: eventList2,
        dt: dtNum,
        segment_size: segNum,
        freq_range,
      })
    );
  };
```
4. Add two small fields after the segment-size TextField:
```tsx
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    label="f min (Hz)"
                    size="small"
                    value={freqMin}
                    onChange={(e) => setFreqMin(e.target.value)}
                  />
                  <TextField
                    label="f max (Hz)"
                    size="small"
                    value={freqMax}
                    onChange={(e) => setFreqMax(e.target.value)}
                  />
                </Box>
```
5. Replace the `traces` constant with:
```tsx
  const traces: Data[] = result
    ? [
        {
          x: result.freq,
          y: result.time_lags,
          type: 'scattergl',
          mode: 'lines+markers',
          marker: { size: 4, color: '#00d4aa' },
          line: { color: '#00d4aa', width: 1 },
          error_y: result.time_lags_err
            ? { type: 'data', array: result.time_lags_err, visible: true, color: 'rgba(0, 212, 170, 0.35)' }
            : undefined,
        } as Data,
      ]
    : [];
```
and in the chart layout use `yaxis: { title: { text: 'Time lag (s)' } }` (no fixed range), with the dashed reference shape at `y0: 0, y1: 0` (zero lag) instead of 1.
6. `PageTemplate` props: `title="Time Lags"`, `description="Frequency-dependent time lags between two energy bands (positive = band 1 lags band 2)"`, `category="Frequency Domain"`.
7. Result header chip: `TimeLagsData` has no `n_segments` — replace that chip with one showing `result.freq_range` when set:
```tsx
                {result?.freq_range && (
                  <Chip
                    size="small"
                    label={`${result.freq_range[0]}–${result.freq_range[1]} Hz`}
                    variant="outlined"
                  />
                )}
```

- [x] **Step 2: Register route and navigation**

`src/App.tsx`:
- After the `CoherencePage` import (line 33) add:
```tsx
import TimeLagsPage from '@/pages/QuickLook/TimeLags';
```
- After the coherence route (`{ path: 'quicklook/coherence', element: <CoherencePage /> },`) add:
```tsx
      { path: 'quicklook/time-lags', element: <TimeLagsPage /> },
```

`src/components/layout/Sidebar.tsx`:
- In `submenuItems` after the Coherence entry (line 87) add:
```tsx
        { text: 'Time Lags', path: '/quicklook/time-lags' },
```
- In `quicklookCategories`, append `'Time Lags'` to the `'Frequency Domain'` array (after `'Coherence'`).

- [x] **Step 3: Verify**

Run: `npm run typecheck && npm run lint && npm test -- --run`
Expected: clean.

- [x] **Step 4: Manual verification**

Sidebar → QuickLook → Frequency Domain shows "Time Lags"; page computes and plots lags with error bars and a zero reference line; the f-range fields restrict the plotted band.

- [x] **Step 5: Commit**

```bash
git add src/pages/QuickLook/TimeLags/ src/App.tsx src/components/layout/Sidebar.tsx
git commit -m "feat: add Time Lags page with route and navigation"
```

---

### Task 21: Power Colors page (new route + nav)

**Files:**
- Create: `src/utils/powerColors.ts`, `src/utils/powerColors.test.ts`, `src/pages/QuickLook/PowerColors/index.tsx`
- Modify: `src/App.tsx`, `src/components/layout/Sidebar.tsx`

- [x] **Step 1: Write the failing helper test**

`src/utils/powerColors.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { computePowerColorRatios } from './powerColors';

describe('computePowerColorRatios', () => {
  const powerColors = {
    A: [1, 2],
    B: [10, 20],
    C: [100, 200],
    D: [5, 10],
  };

  it('computes PC1 = C/A and PC2 = B/D per segment', () => {
    const result = computePowerColorRatios(powerColors, ['A', 'B', 'C', 'D']);
    expect(result).not.toBeNull();
    expect(result?.pc1).toEqual([100, 100]);
    expect(result?.pc2).toEqual([2, 2]);
  });

  it('returns null when a band is missing or count is not 4', () => {
    expect(computePowerColorRatios(powerColors, ['A', 'B', 'C'])).toBeNull();
    expect(computePowerColorRatios({ A: [1] }, ['A', 'B', 'C', 'D'])).toBeNull();
  });

  it('skips segments with non-positive denominators', () => {
    const result = computePowerColorRatios(
      { A: [0, 1], B: [1, 1], C: [1, 1], D: [1, 1] },
      ['A', 'B', 'C', 'D']
    );
    expect(result?.pc1).toEqual([1]);
    expect(result?.pc2).toEqual([1]);
  });
});
```

- [x] **Step 2: Run to verify it fails, then implement the helper**

Run: `npm test -- --run src/utils/powerColors` → FAIL.

`src/utils/powerColors.ts`:
```ts
/**
 * Power-color ratios following the Heil et al. (2015) convention: with four
 * frequency bands A < B < C < D (ascending f_min),
 *   PC1 = P(C) / P(A)  and  PC2 = P(B) / P(D)
 * computed per dynamical-spectrum segment.
 */
export interface PowerColorRatios {
  pc1: number[];
  pc2: number[];
}

export function computePowerColorRatios(
  powerColors: Record<string, number[]>,
  bandOrder: string[]
): PowerColorRatios | null {
  if (bandOrder.length !== 4) return null;
  const [a, b, c, d] = bandOrder.map((key) => powerColors[key]);
  if (!a || !b || !c || !d) return null;

  const n = Math.min(a.length, b.length, c.length, d.length);
  const pc1: number[] = [];
  const pc2: number[] = [];
  for (let i = 0; i < n; i++) {
    if (a[i] > 0 && d[i] > 0 && c[i] > 0 && b[i] > 0) {
      pc1.push(c[i] / a[i]);
      pc2.push(b[i] / d[i]);
    }
  }
  return { pc1, pc2 };
}
```

Run: `npm test -- --run src/utils/powerColors` → PASS.

- [x] **Step 3: Implement the page**

Create `src/pages/QuickLook/PowerColors/index.tsx`:
```tsx
import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Grid,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { Data } from 'plotly.js';
import PageTemplate from '@/components/common/PageTemplate';
import PlotlyChart from '@/components/plots/PlotlyChart';
import EventListSelector from '@/components/analysis/EventListSelector';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import { timingApi, PowerColorsData } from '@/api/timingApi';
import { parsePositiveNumber } from '@/utils/numbers';
import { computePowerColorRatios } from '@/utils/powerColors';

interface BandInput {
  label: string;
  fmin: string;
  fmax: string;
}

// Heil et al. (2015) bands; require dt <= 1/(2*16) s for the top band.
const DEFAULT_BANDS: BandInput[] = [
  { label: 'A', fmin: '0.0039', fmax: '0.031' },
  { label: 'B', fmin: '0.031', fmax: '0.25' },
  { label: 'C', fmin: '0.25', fmax: '2.0' },
  { label: 'D', fmin: '2.0', fmax: '16.0' },
];

const BAND_COLORS = ['#00d4aa', '#3b82f6', '#f59e0b', '#ef4444'];

const PowerColorsPage: React.FC = () => {
  const [eventList, setEventList] = useState('');
  const [dt, setDt] = useState('0.03125');
  const [segmentSize, setSegmentSize] = useState('64');
  const [bands, setBands] = useState<BandInput[]>(DEFAULT_BANDS);
  const { result, running, error, run } = useAnalysisRunner<PowerColorsData>('Power Colors');

  const dtNum = parsePositiveNumber(dt);
  const segNum = parsePositiveNumber(segmentSize);

  const parsedBands = bands.map((b) => ({
    label: b.label,
    fmin: parsePositiveNumber(b.fmin),
    fmax: parsePositiveNumber(b.fmax),
  }));
  const bandsValid = parsedBands.every(
    (b) => b.fmin !== null && b.fmax !== null && b.fmax > b.fmin
  );
  const canRun = eventList !== '' && dtNum !== null && segNum !== null && bandsValid && !running;

  const updateBand = (index: number, field: 'fmin' | 'fmax', value: string): void => {
    setBands((prev) => prev.map((b, i) => (i === index ? { ...b, [field]: value } : b)));
  };

  const handleRun = (): void => {
    if (!dtNum || !segNum || !bandsValid) return;
    const freq_ranges: Record<string, [number, number]> = {};
    for (const b of parsedBands) {
      freq_ranges[b.label] = [b.fmin as number, b.fmax as number];
    }
    void run(() =>
      timingApi.calculatePowerColors({
        event_list_name: eventList,
        dt: dtNum,
        segment_size: segNum,
        freq_ranges,
      })
    );
  };

  const bandTraces: Data[] = result
    ? Object.entries(result.power_colors).map(([label, values], i) => ({
        x: result.time,
        y: values,
        type: 'scattergl',
        mode: 'lines+markers',
        marker: { size: 4 },
        line: { width: 1, color: BAND_COLORS[i % BAND_COLORS.length] },
        name: label,
      }))
    : [];

  const ratios = result
    ? computePowerColorRatios(result.power_colors, bands.map((b) => b.label))
    : null;

  const scatterTrace: Data[] = ratios
    ? [
        {
          x: ratios.pc1,
          y: ratios.pc2,
          type: 'scattergl',
          mode: 'markers',
          marker: { size: 6, color: '#00d4aa' },
        },
      ]
    : [];

  return (
    <PageTemplate
      title="Power Colors"
      description="Integrated band powers per segment and the PC1–PC2 power-color diagram"
      category="Advanced Analysis"
      status="ready"
    >
      <Grid container spacing={3}>
        <Grid item xs={12} md={4} lg={3}>
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="subtitle2">Parameters</Typography>
                <EventListSelector label="Event list" value={eventList} onChange={setEventList} />
                <TextField
                  label="Time bin dt (s)"
                  size="small"
                  value={dt}
                  onChange={(e) => setDt(e.target.value)}
                  error={dt !== '' && dtNum === null}
                  helperText="Nyquist must cover the highest band"
                />
                <TextField
                  label="Segment size (s)"
                  size="small"
                  value={segmentSize}
                  onChange={(e) => setSegmentSize(e.target.value)}
                  error={segmentSize !== '' && segNum === null}
                  helperText="Must exceed 1/f_min of the lowest band"
                />
                <Typography variant="subtitle2">Frequency bands (Hz)</Typography>
                {bands.map((b, i) => (
                  <Box key={b.label} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                    <Typography sx={{ width: 20, fontFamily: '"JetBrains Mono", monospace' }}>
                      {b.label}
                    </Typography>
                    <TextField
                      size="small"
                      value={b.fmin}
                      onChange={(e) => updateBand(i, 'fmin', e.target.value)}
                    />
                    <TextField
                      size="small"
                      value={b.fmax}
                      onChange={(e) => updateBand(i, 'fmax', e.target.value)}
                    />
                  </Box>
                ))}
                {!bandsValid && (
                  <Alert severity="warning">Each band needs 0 &lt; f min &lt; f max.</Alert>
                )}
                <Button
                  variant="contained"
                  startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
                  disabled={!canRun}
                  onClick={handleRun}
                >
                  Compute
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8} lg={9}>
          <Card variant="outlined">
            <CardContent>
              {error && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {error}
                </Alert>
              )}
              {result ? (
                <Stack spacing={3}>
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      Band power vs time
                    </Typography>
                    <PlotlyChart
                      data={bandTraces}
                      layout={{
                        showlegend: true,
                        xaxis: { title: { text: 'Time (s)' } },
                        yaxis: { title: { text: 'Mean power (leahy)' }, type: 'log' },
                      }}
                      height={320}
                    />
                  </Box>
                  {ratios && ratios.pc1.length > 0 && (
                    <Box>
                      <Typography variant="subtitle2" gutterBottom>
                        Power-color diagram (PC1 = C/A, PC2 = B/D)
                      </Typography>
                      <PlotlyChart
                        data={scatterTrace}
                        layout={{
                          xaxis: { title: { text: 'PC1' }, type: 'log' },
                          yaxis: { title: { text: 'PC2' }, type: 'log' },
                        }}
                        height={380}
                      />
                    </Box>
                  )}
                </Stack>
              ) : (
                <Box sx={{ py: 10, textAlign: 'center' }}>
                  <Typography color="text.secondary">
                    Compute band powers to populate the power-color diagram.
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageTemplate>
  );
};

export default PowerColorsPage;
```

- [x] **Step 4: Register route and navigation**

`src/App.tsx`:
- After the `TimeLagsPage` import add:
```tsx
import PowerColorsPage from '@/pages/QuickLook/PowerColors';
```
- After the bispectrum route (`{ path: 'quicklook/bispectrum', element: <BispectrumPage /> },`) add:
```tsx
      { path: 'quicklook/power-colors', element: <PowerColorsPage /> },
```

`src/components/layout/Sidebar.tsx`:
- In `submenuItems` after the Bispectrum entry add:
```tsx
        { text: 'Power Colors', path: '/quicklook/power-colors' },
```
- In `quicklookCategories`, append `'Power Colors'` to the `'Advanced Analysis'` array (after `'Bispectrum'`).

- [x] **Step 5: Verify**

Run: `npm test -- --run && npm run typecheck && npm run lint`
Expected: all pass.

- [x] **Step 6: Manual verification**

Compute with the defaults on a loaded list (needs ≥ 64 s of data and dt=0.03125): four band traces render; PC diagram shows one point per segment.

- [x] **Step 7: Commit**

```bash
git add src/utils/powerColors.ts src/utils/powerColors.test.ts src/pages/QuickLook/PowerColors/ src/App.tsx src/components/layout/Sidebar.tsx
git commit -m "feat: add Power Colors page with band powers and PC diagram"
```

---

### Task 22: Full-suite verification and end-to-end pass

- [x] **Step 1: Run every automated gate**

```bash
npm test -- --run
npm run typecheck
npm run lint
pixi run -e dev pytest python-backend/tests -v
```
Expected: all green. Fix anything that isn't before proceeding.

- [x] **Step 2: End-to-end manual checklist**

Start `npm run dev`. Load one sample event file from `files/data/` twice under two names (`evA`, `evB`). Then walk every page:

| Page | Action | Expect |
|---|---|---|
| Event List | select evA, both tabs | info + GTI table + 2 histograms |
| Light Curve | generate dt=1, rebin ×2 | plot, chips, stored list grows |
| Power Spectrum | dt=0.0625, leahy, store, rebin log | Poisson level ≈ 2 at high f |
| Avg Power Spectrum | segment=16 | smoother spectrum, segments chip |
| Cross Spectrum | evA × evB | magnitude + phase panels |
| Avg Cross Spectrum | segment=16 | less scatter |
| Dynamical PS | dt=0.0625, segment=8 | heatmap, log-color toggle |
| Bispectrum | dt=0.1, maxlag=25 | magnitude + phase tabs; UI stays responsive |
| Coherence | evA × evA | γ² ≈ 1 flat line at the reference |
| Time Lags | evA × evB, then f-range 0.5–2 | error bars, zero line, filtered range |
| Power Colors | defaults | 4 band traces + PC scatter |

Also confirm: notifications fire on each success/failure; the log panel keeps streaming during a Bispectrum run; no `coming soon` banner remains on any of the eleven pages.

- [x] **Step 3: Check off this plan**

Mark all checkboxes in this document, note any deviations at the bottom, and commit the plan updates:
```bash
git add docs/superpowers/plans/2026-06-10-quicklook-core-pages.md
git commit -m "docs: record quicklook core implementation plan completion"
```

---

## Execution notes (2026-06-11)

- **Rebin factor semantics fixed on both paths**: lightcurve rebin uses `f=` (fractional factor) not the positional `dt` arg; spectrum `rebin()` similarly uses `f=rebin_factor` to avoid passing df-in-Hz.
- **Power-colors axis bug fixed**: `dps.dyn_ps` has shape `(n_freq, n_time)` — mask and mean were applied along the wrong axis in earlier draft; corrected to `dps.dyn_ps[mask, :].mean(axis=0)`.
- **longdouble serialization**: `dps.time`, `lc.time`, and similar stingray arrays use numpy `longdouble`; serialization now coerces via `.astype(float).tolist()` or `float(v)` casts to avoid JSON failures on macOS/Linux where `longdouble` is not JSON-safe.
- **dyn_ps NaN sanitization**: `_finite_list` applied row-by-row on `dps.dyn_ps` to replace any NaN/Inf cells with `null` before JSON serialization.
- **Segment-size + overlap + empty-list guards added**: `_overlap_error` in both `spectrum_service.py` and `timing_service.py` now checks empty event lists first, then disjoint ranges, then optionally rejects if overlap duration < `segment_size`; the optional `segment_size` parameter is passed at all three averaged call sites (`create_averaged_cross_spectrum`, `calculate_time_lags`, `calculate_coherence`), NOT at plain `create_cross_spectrum`.
- **ESLint config created**: project had no `.eslintrc` / `eslint.config.js`; created `eslint.config.js` with `@typescript-eslint` and `react-hooks` rules to make `npm run lint` operational.
- **6 pre-existing typecheck errors cleared**: stray `any` types, missing return-type annotations, and an unused import in route handler stubs were fixed before the first typecheck gate.
- **maxlag capped at 500 + cum3 dropped from payload**: bispectrum `cum3` field is large and unused by the UI; dropped from the JSON response. `maxlag` is validated ≤ 500 server-side to prevent OOM on large lags.
- **Lag sign convention pinned**: positive lag = second list leads first list (stingray convention); documented in the Time Lags page UI and pinned by `test_time_lag_sign_convention_for_shifted_signal`.
- **Time Lags + Power Colors pages added with routes/nav**: Tasks 20–21 added `src/pages/QuickLook/TimeLags/index.tsx` and `PowerColors/index.tsx`, wired routes in `src/App.tsx`, and added sidebar entries in `src/components/layout/Sidebar.tsx`.
- **Decimation with longdouble coercion on lightcurve payloads**: stride-decimation helper also coerces `lc.time` (longdouble on some platforms) to `float64` before `tolist()`.
- **Band-mean (not integrated) power-colors convention documented**: power colors use `dps.dyn_ps[mask, :].mean(axis=0)` (mean over frequencies in band per segment) following the Heil et al. 2015 convention; "integrated" wording removed from UI descriptions to avoid confusion with flux integrals.

## E2E execution notes (2026-07-29)

Task 22 Step 2 manual checklist executed against `npm run dev` (agent-driven via CDP: `--remoteDebuggingPort` + playwright-core `connectOverCDP`). All 11 page rows passed: Event List (both tabs, GTI table, 2 histograms), Light Curve (dt=1, rebin ×2 → 512 bins, stored list grows), Power Spectrum (Leahy Poisson level ≈ 2 at high f, log rebin 8,199 → 258 freqs), Avg Power Spectrum (64-segments chip, smoother), Cross Spectrum (magnitude + phase; phase ≡ 0 for identical files), Avg Cross Spectrum (less scatter), Dynamical PS (heatmap + log-color toggle), Bispectrum (magnitude/phase tabs, console kept streaming during run), Coherence (γ² ≡ 1 for evA × evA), Time Lags (error bars, zero line, f-range 0.5–2 Hz filter verified in plot data), Power Colors (4 band traces + PC scatter). Success and failure notifications both fire; no coming-soon banner on any of the eleven pages. Deviations: event files were loaded via `POST /api/data/load` (the Browse button opens a native macOS dialog, which is not automatable; the rest of the flow used the real UI). Three Electron-shell issues were found outside the plan's scope during startup — hard 180 s backend-ready timeout leaves the app stuck on "Error" even after the backend becomes healthy; `PythonManager.stop()`'s 5 s force-kill timer is never cancelled and SIGKILLs the replacement backend on restart; `python:restart` IPC never re-sends `python:ready`/`python:error` to the renderer — tracked separately.
