# QuickLook Remaining Pages Implementation Plan (2026-07-29)

**Goal:** Replace the nine remaining QuickLook placeholder pages — AutoCorrelation, CrossCorrelation, CovarianceSpectrum, AvgCovarianceSpectrum, RmsEnergySpectrum, LagEnergySpectrum, ExcessVarianceSpectrum, VariableEnergySpectrum, DeadTimeCorrections — with working analysis UIs. Unlike the 2026-06-10 plan, **no backend endpoints exist for any of these**: each needs a service method + FastAPI route + frontend API module + page.

**Grounding:** All stingray behavior cited below was verified by introspecting the installed stingray 2.2.10 in `.pixi/envs/default` (not the AI_DOCS guides, several of which contain verified inaccuracies). Routes and sidebar nav entries for all 9 pages already exist; page stubs are 15-line `PageTemplate status="coming-soon"` components.

---

## Verified stingray facts the implementation MUST honor

### Correlation (`stingray.crosscorrelation`)
- `CrossCorrelation(lc1=None, lc2=None, cross=None, mode='same', norm='none')`; `AutoCorrelation(lc=None, mode='same')` — AutoCorrelation does **not** forward `norm` (always `'none'`). For a normalized ACF use `CrossCorrelation(lc, lc, norm='variance')`.
- Inputs must be `Lightcurve` (EventList NOT accepted). Attributes: `.corr`, `.time_lags` (seconds), `.time_shift` (argmax lag), `.dt`, `.n`, `.mode`, `.norm`.
- **Sign convention (verified with Gaussian-pulse alignment): `time_shift > 0` ⟺ lc1 (first arg) lags lc2; `time_shift < 0` ⟺ lc1 leads.**
- **stingray performs NO time-grid alignment**: it correlates `counts` arrays by position, ignoring `.time` entirely. The service MUST bin both event lists onto an identical grid over their common time range (shared bin edges) before constructing light curves.
- `norm='variance'` can silently produce **all-NaN `.corr`** (negative noise-subtracted variance for flat/low-count curves) with a bogus `time_shift`; the service must detect NaN and null out `time_shift` + attach a warning.
- `mode='full'|'valid'` are only reliable on the two-Lightcurve path; with equal-length inputs `'valid'` degenerates to one point. Expose `same` (default) and `full` only.

### Var-energy spectra (`stingray.varenergyspectrum`)
- `RmsSpectrum` (= alias `RmsEnergySpectrum`), `LagSpectrum` (= `LagEnergySpectrum`), `CovarianceSpectrum`, `ComplexCovarianceSpectrum`, `ExcessVarianceSpectrum`, `CountSpectrum`. All take `EventList` with `.energy` (or `.pi` with `use_pi=True`).
- `energy_spec` = tuple `(emin, emax, n_bins, 'lin'|'log')`; `freq_interval=[fmin,fmax)`; outputs `.energy`, `.spectrum`, `.spectrum_error` (float64, NaN for skipped bins).
- **`segment_size=None` CRASHES `RmsSpectrum` and `CovarianceSpectrum`** (TypeError). Always require an explicit numeric segment_size. `LagSpectrum` tolerates None (m=1) but require it anyway.
- **`ref_band` is silently inert for `RmsSpectrum`** (single-EventList case) — do not expose it on the RMS page. It IS used by `LagSpectrum`/`CovarianceSpectrum`.
- **`ExcessVarianceSpectrum` is broken in 2.2.10**: `_spectrum_function()` returns `(spec, spec_err)` but `__init__` discards it → `.spectrum` always all-NaN. Workaround (verified): call `spec, spec_err = xvs._spectrum_function()` manually and use the returned arrays. `ExcessVarianceSpectrum` positional order is `(events, freq_interval, energy_spec, ...)` — different from every sibling; pass all kwargs by keyword. It ignores `segment_size` entirely.
- Covariance with pure Poisson noise is legitimately all-NaN (no excess variance in ref band → sqrt of negative). Tests need **correlated variability** (shared sinusoidally-modulated rate across energies); low-count bins emit `UserWarning ... Skipping.` and stay NaN — capture and surface these warnings.
- `min_phot_per_segment` is only a constructor arg on Covariance/ComplexCovariance (default 10); Rms/Lag do not accept it.
- **Legacy module `stingray.covariancespectrum`** (`Covariancespectrum`, `AveragedCovariancespectrum`) exists in 2.2.10, distinct API (takes raw `[time, energy]` event data, `band_interest`/`ref_band_interest`, `std`). Not yet introspected — the covariance implementer must introspect it before writing tests.

### Dead time (`stingray.deadtime`)
- `r_det(td, r_i)`, `r_in(td, r_0)` — trivial rate conversions (implement client-side).
- `<AveragedPowerspectrum>.deadtime_correct(dead_time, rate, background_rate=0, limit_k=200, n_approx=None, paralyzable=False)` → corrected copy. **Assumes Leahy norm without checking** (correction is `2/model`); `paralyzable=True` raises `NotImplementedError`; `(rate+background_rate)*dead_time >= 1` raises ValueError — pre-validate with a readable message. `rate` is the DETECTED rate (`n_events / total GTI exposure`).
- `stingray.deadtime.fad.FAD(data1, data2, segment_size, dt=None, norm='frac', ...)` → astropy Table with columns `freq, pds1, pds2, cs, ptot, *_unnorm, fad`. Needs two independent simultaneous EventLists (different detectors). Verified working, fast (0.16 s for 300 s of data). Recommend ≥30 segments — warn (don't block) below that.
- First call to numba-JIT'd deadtime functions pays ~1 s compile cost per process — acceptable, no warmup needed.
- `check_A`/`check_B` have matplotlib global-state side effects — do NOT call them in the backend.

---

## Design decisions

1. **Three new backend service/route pairs** (keeps files disjoint for parallel work):
   - `services/correlation_service.py` + `routes/correlation_routes.py` → `/api/correlation/*`
   - `services/varenergy_service.py` + `routes/varenergy_routes.py` → `/api/varenergy/*`
   - `services/deadtime_service.py` + `routes/deadtime_routes.py` → `/api/deadtime/*`
2. **Shared helpers hoisted**: new `services/analysis_helpers.py` with `finite_list`, `segment_size_error`, `overlap_error` (same code as the copies in timing/spectrum services). New services import from it; the two existing services are left untouched (separate cleanup, not this plan).
3. **Warnings surfaced**: every service method runs its stingray call inside `warnings.catch_warnings(record=True)` and returns `"warnings": [str, ...]` (deduplicated) in `data`, so the UI can show low-count/NaN advisories.
4. **Covariance page pairing** mirrors PowerSpectrum/AvgPowerSpectrum using the LEGACY module: CovarianceSpectrum page → `stingray.Covariancespectrum` (whole-lightcurve), AvgCovarianceSpectrum page → `stingray.AveragedCovariancespectrum` (segmented). If introspection shows the legacy classes are broken/unusable in 2.2.10, fall back to `varenergyspectrum.CovarianceSpectrum` for BOTH (unsegmented page uses one segment spanning the GTI) and record the deviation at the bottom of this doc.
5. **VariableEnergySpectrum page = variability-vs-energy overview**: one endpoint computing `CountSpectrum` + `RmsSpectrum` + `LagSpectrum` with shared parameters; the page renders three stacked panels. (The abstract `VarEnergySpectrum` base has no direct product; this is the useful composite.)
6. **DeadTimeCorrections page = three panels**: (a) rate calculator, pure client-side TS (`r_det`/`r_in` formulas + `rate*td ≥ 1` guard); (b) model-based PDS correction endpoint; (c) FAD two-detector endpoint.
7. **ExcessVariance workaround** encapsulated in the service with a comment naming the upstream bug; test pins finite output on modulated data.
8. **Response envelope**: bare `create_result` dicts (timing/spectrum precedent), soft-fail `success:false` for domain errors, `asyncio.to_thread` in every route.
9. **Frontend**: three new API modules (`correlationApi.ts`, `varenergyApi.ts`, `deadtimeApi.ts`), interfaces defined below; each page follows the TimeLags runner-page skeleton, `scattergl` traces, chips, warning `Alert` when `warnings` non-empty. Every page gets a vitest test following the LightCurve/EventList mock pattern (api module mocked, PlotlyChart stubbed, assert request fields + disabled-until-valid).

## Endpoint contracts

All request fields snake_case; all array outputs pass through `finite_list` (NaN→null). Every `data` payload includes `"warnings": string[]`.

### POST /api/correlation/auto-correlation
Req `{ event_list_name, dt, mode='same', norm='none' }` (norm: `none|variance`; variance path uses `CrossCorrelation(lc, lc, ...)`).
Data `{ time_lags[], corr[], time_shift|null, dt, n, mode, norm, warnings }` — `time_shift` nulled when corr contains NaN.

### POST /api/correlation/cross-correlation
Req `{ event_list_1_name, event_list_2_name, dt, mode='same', norm='none' }`.
Service: `overlap_error` check → crop both to common `[max(start), min(stop)]` → bin with SHARED edges → `CrossCorrelation(lc1, lc2)`.
Data: same shape as auto. Test pins sign convention: ev2 = ev1 shifted +0.5 s ⇒ lc2 lags lc1 ⇒ `time_shift == -0.5 ± dt`.

### POST /api/varenergy/rms-spectrum
Req `{ event_list_name, bin_time, segment_size, freq_min, freq_max, energy_min, energy_max, n_bands, log_bands=false, norm='frac' }`.
Data `{ energy[], spectrum[], spectrum_error[], freq_range:[f,f], norm, n_segments_hint?, warnings }`. No ref_band (inert in stingray).

### POST /api/varenergy/lag-spectrum
Req: rms fields minus `norm`, plus optional `ref_min`, `ref_max` (both-or-neither; None → full band).
Data: same shape; spectrum in seconds. UI draws a zero line.

### POST /api/varenergy/excess-variance
Req `{ event_list_name, bin_time, energy_min, energy_max, n_bands, log_bands=false, normalization='fvar' }` (+ freq_min/freq_max if introspection shows they matter; implementer verifies).
Service constructs `ExcessVarianceSpectrum` then applies the `_spectrum_function()` workaround.
Data `{ energy[], spectrum[], spectrum_error[], normalization, warnings }`.

### POST /api/varenergy/variable-energy-spectrum
Req: shared `{ event_list_name, bin_time, segment_size, freq_min, freq_max, energy_min, energy_max, n_bands, log_bands, ref_min?, ref_max? }`.
Data `{ energy[], counts:{spectrum[],error[]}, rms:{spectrum[],error[]}, lag:{spectrum[],error[]}, warnings }`.

### POST /api/varenergy/covariance-spectrum and /avg-covariance-spectrum
Contracts finalized by the implementer after introspecting the legacy module; must include `{ energy[], spectrum[], spectrum_error[], warnings }` plus whatever band/segment params the API needs, following the field-naming conventions above. Document the final contract in this file's execution notes.

### POST /api/deadtime/pds-correction
Req `{ event_list_name, dt, segment_size, dead_time, background_rate=0, limit_k=200 }`.
Service: `(rate+background_rate)*dead_time >= 1` → readable soft-fail; norm hard-locked to leahy.
Data `{ freq[], power_uncorrected[], power_corrected[], rate, n_segments, warnings }`.

### POST /api/deadtime/fad-correction
Req `{ event_list_1_name, event_list_2_name, dt, segment_size, norm='frac', smoothing_length? }`.
Service: overlap check; `< 30` segments → warning (still computes).
Data `{ freq[], pds1[], pds2[], ptot[], cs[], n_segments, warnings }`.

## Frontend API module interfaces

`correlationApi.ts`: `CorrelationData { time_lags: number[]; corr: (number|null)[]; time_shift: number|null; dt: number; n: number; mode: string; norm: string; warnings: string[] }`; methods `autoCorrelation(params)`, `crossCorrelation(params)` mirroring the request fields 1:1.

`varenergyApi.ts`: `VarEnergyData { energy: number[]; spectrum: (number|null)[]; spectrum_error: (number|null)[]; warnings: string[]; [k: string]: unknown }`; `VariableEnergyData { energy: number[]; counts: Band; rms: Band; lag: Band; warnings: string[] }` with `Band { spectrum: (number|null)[]; error: (number|null)[] }`; methods `rmsSpectrum`, `lagSpectrum`, `excessVariance`, `variableEnergySpectrum`, `covarianceSpectrum`, `avgCovarianceSpectrum`.

`deadtimeApi.ts`: `PdsCorrectionData { freq: number[]; power_uncorrected: (number|null)[]; power_corrected: (number|null)[]; rate: number; n_segments: number; warnings: string[] }`; `FadData { freq: number[]; pds1: (number|null)[]; pds2: (number|null)[]; ptot: (number|null)[]; cs: (number|null)[]; n_segments: number; warnings: string[] }`; methods `pdsCorrection`, `fadCorrection`.

## Page specs (all: params card left md=4/lg=3, result card right, `useAnalysisRunner`, warning Alert when `result.warnings.length > 0`, vitest test per page)

1. **AutoCorrelation** — selector, dt, mode (same/full), norm (none/variance); plot corr vs time_lags with zero-lag reference line; chips: n, dt, mode.
2. **CrossCorrelation** — two selectors, dt, mode, norm; plot + dashed vertical line at `time_shift` (when non-null) + chip `time shift: X s`; caption: "Positive shift ⇒ first list lags the second."
3. **RmsEnergySpectrum** — selector, bin_time (default 0.01), segment_size (default 8), f-range (0.1–1), energy range (0.5–10, 5 bands, lin/log toggle), norm (frac/abs); error-bar scatter energy vs rms.
4. **LagEnergySpectrum** — as RMS plus optional ref-band pair; zero line; y-axis seconds.
5. **ExcessVarianceSpectrum** — selector, bin_time, energy bands, normalization (fvar/none per introspection); error bars.
6. **VariableEnergySpectrum** — shared params; three stacked PlotlyCharts (counts / fractional rms / lag vs energy).
7. **CovarianceSpectrum / AvgCovarianceSpectrum** — per final backend contract; error-bar scatter vs energy; Avg adds segment_size + n_segments chip.
8. **DeadTimeCorrections** — panel (a) client-side calculator (incident⇄detected radio, dead_time; outputs both rates + loss fraction, error state when `rate*td ≥ 1`); panel (b) model correction: selector + dt + segment_size + dead_time + background_rate + limit_k, overlay uncorrected/corrected traces (log-log) + note "norm fixed to Leahy"; panel (c) FAD: two selectors + dt + segment_size + norm, multi-trace (pds1, pds2, ptot) + cs; warning chip when n_segments < 30.

## Execution phases

- **Phase 0 (orchestrator, inline):** this doc; `services/analysis_helpers.py`; empty skeleton service/route files; `main.py` router registration; commit.
- **Phase 1 (workflow, 3 parallel TDD agents):** correlation / varenergy / deadtime — each introspects what it needs, writes failing pytest cases in its own `tests/test_<domain>_service.py`, implements service + routes, runs `pixi run -e dev pytest` to green. Files per agent are disjoint.
- **Phase 2 (workflow):** one agent writes the three API modules to the interfaces above; then 9 parallel page agents (one per page dir) write `index.tsx` + `index.test.tsx`; gates `npm run typecheck && npm run lint && npm test -- --run`.
- **Phase 3 (verification workflow + orchestrator):** full-suite gates; adversarial science review of the three services against this doc's verified-facts section; live E2E of all 9 pages via CDP with a dense synthetic event file (modulated correlated variability so covariance/rms produce finite results); fix findings; update this doc's execution notes; commit.

## Execution notes (2026-07-29)

All phases executed same-day; every gate green at completion (backend pytest **145 passed**, vitest **72 passed**, typecheck clean, eslint 0 errors). Live E2E of all nine pages performed via CDP against `npm run dev` with dense synthetic data (120k-event 0.5 Hz-modulated list + 0.5 s-shifted copy + two independent dead-time-filtered streams, loaded as HDF5 via `/api/data/load`).

**Key deviations/decisions (full details in service docstrings and tests):**
- Legacy `stingray.covariancespectrum` module rejected after introspection proved it histograms the energy column as arrival times and its "averaged" variant always computes exactly one segment; both covariance endpoints use `varenergyspectrum.CovarianceSpectrum` (unsegmented page = one segment spanning the longest GTI, with GTI-usage accounting fields).
- `ExcessVarianceSpectrum` 2.2.10 discard-bug worked around via a subclass whose `_spectrum_function` stores its results (single compute); excess variance additionally masks inter-GTI gap bins (`create_gti_mask`), which the upstream class does not — gaps otherwise fabricate variability.
- `stingray.deadtime.fad.FAD` mutates its inputs' GTIs; the service passes detached EventList copies. `fad_delta` can be NaN (identical inputs) — serialized as null + warning.
- Cross/auto correlation bin on a shared relative-time grid built with `np.histogram` (stingray ignores absolute time and `to_lc` snaps dt); 500k-bin cap; unsorted-time-safe bounds (`np.min`/`np.max`); verified sign convention pinned: positive `time_shift` ⇒ first list lags second.
- `collect_warnings` is context-aware on Python 3.14 (`PYTHON_CONTEXT_AWARE_WARNINGS=1` set at spawn; `-X` flag in `python:dev`) with a serializing RLock fallback — `warnings.catch_warnings` is otherwise process-global and concurrent captures cross-contaminate and can permanently orphan the global warning hook.
- Post-implementation adversarial review (5 reviewers + per-finding verification) confirmed 22 findings (1 critical, 10 major, 11 minor); all fixed and pinned with discriminating tests (each verified to fail against the pre-fix code where practical). One rejected finding (hardcoded trace colors) left as-is.
- Live E2E numeric cross-checks: recovered `time_shift = -0.5000 s` for the +0.5 s-shifted list; Leahy dead-time correction restored mean power ≈ 2 with the calculator's predicted detected rate (171.43 c/s) matching the measured data rate (171.41 c/s); FAD Δ = 0.007 (compliant) at 37 segments; counts/band = 24k = 120k/5.
- Plotly quirk (verified live): shapes on log axes use RAW data coordinates in the bundled plotly version, not log10 — the Leahy reference line is passed untransformed.
