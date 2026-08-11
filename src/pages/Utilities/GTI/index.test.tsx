import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';
import { useUIStore } from '@/store/uiStore';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...args: unknown[]) => listEventLists(...args) },
}));

const inspect = vi.fn();
const validate = vi.fn();
const setOperation = vi.fn();
const badTimeIntervals = vi.fn();
const previewMask = vi.fn();
const saveMask = vi.fn();
const fixedSegments = vi.fn();
const exposureSegments = vi.fn();
vi.mock('@/api/gtiApi', () => ({
  gtiApi: {
    inspect: (...args: unknown[]) => inspect(...args),
    validate: (...args: unknown[]) => validate(...args),
    setOperation: (...args: unknown[]) => setOperation(...args),
    badTimeIntervals: (...args: unknown[]) => badTimeIntervals(...args),
    previewMask: (...args: unknown[]) => previewMask(...args),
    saveMask: (...args: unknown[]) => saveMask(...args),
    fixedSegments: (...args: unknown[]) => fixedSegments(...args),
    exposureSegments: (...args: unknown[]) => exposureSegments(...args),
  },
}));

vi.mock('@/components/plots/PlotlyChart', () => ({
  default: ({ data }: { data: unknown }) => <div data-testid="chart">{JSON.stringify(data)}</div>,
}));

import GTIPage from './index';
import { intervalTrace } from './GtiCommon';

type TestInterval = { index: number; start: number; stop: number; length_s: number };

function intervalPayload(
  intervals: TestInterval[] = [
    { index: 1, start: 0, stop: 10, length_s: 10 },
    { index: 2, start: 12, stop: 20, length_s: 8 },
  ],
  plotIntervals: TestInterval[] = intervals
) {
  const total = intervals.reduce((sum, row) => sum + row.length_s, 0);
  const span = intervals.length > 0 ? intervals[intervals.length - 1].stop - intervals[0].start : 0;
  return {
    intervals,
    interval_count: intervals.length,
    lengths_s: intervals.map((row) => row.length_s),
    separations_s: intervals.slice(1).map((row, index) => row.start - intervals[index].stop),
    total_exposure_s: total,
    overall_time_span_s: span,
    duty_cycle: span > 0 ? total / span : null,
    plot: {
      starts: plotIntervals.map((row) => row.start),
      stops: plotIntervals.map((row) => row.stop),
      interval_indices: plotIntervals.map((row) => row.index),
      stride: plotIntervals.length === intervals.length ? 1 : 2,
      source_points: intervals.length,
    },
  };
}

function response<T>(data: T, message = 'done') {
  return { success: true, data, message, error: null };
}

it('uses sanitized durations for plots instead of overflowing endpoint subtraction', () => {
  const payload = {
    intervals: [{ index: 1, start: -1e308, stop: 1e308, length_s: null }],
    interval_count: 1,
    lengths_s: [null],
    separations_s: [],
    total_exposure_s: null,
    overall_time_span_s: null,
    duty_cycle: null,
    plot: {
      starts: [-1e308],
      stops: [1e308],
      interval_indices: [1],
      stride: 1,
      source_points: 1,
    },
  };

  const trace = intervalTrace(payload, 'Extreme GTI')[0] as { x: unknown[] };

  expect(trace.x).toEqual([null]);
  expect(JSON.stringify(trace)).not.toContain('Infinity');
});

const provenance = { operation: 'test' };

async function selectEventList(label: string, option: RegExp): Promise<void> {
  const panel = screen.getByRole('tabpanel');
  await userEvent.click(await within(panel).findByLabelText(label));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

async function chooseSelect(label: string, option: RegExp): Promise<void> {
  const panel = screen.getByRole('tabpanel');
  await userEvent.click(within(panel).getByLabelText(label));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

async function fill(label: string, value: string): Promise<void> {
  const field = within(screen.getByRole('tabpanel')).getByLabelText(label);
  await userEvent.clear(field);
  await userEvent.type(field, value);
}

describe('GTIPage', () => {
  beforeEach(() => {
    useUIStore.setState({ notifications: [], unreadNotificationCount: 0 });
    for (const mock of [
      listEventLists,
      inspect,
      validate,
      setOperation,
      badTimeIntervals,
      previewMask,
      saveMask,
      fixedSegments,
      exposureSegments,
    ]) {
      mock.mockReset();
    }
    listEventLists.mockResolvedValue(
      response([
        { name: 'obs1', n_events: 4, time_range: [0, 20] },
        { name: 'existing', n_events: 2, time_range: [1, 2] },
      ])
    );
    const common = intervalPayload();
    inspect.mockResolvedValue(
      response({
        ...common,
        event_list_name: 'obs1',
        event_count: 4,
        gti_status: 'available',
        gti_origin: 'effective_event_list_gti',
        time_unit: 's',
        time_reference: 'absolute_mission_time',
        mjdref: 59000,
        warnings: [],
        provenance,
      })
    );
    validate.mockResolvedValue(
      response({
        ...common,
        valid: true,
        time_unit: 's',
        time_reference: 'relative_seconds',
        warnings: [],
        provenance,
      })
    );
    setOperation.mockResolvedValue(
      response({
        ...common,
        operation: 'union',
        merge_strategy: 'union with touching intervals coalesced',
        time_unit: 's',
        time_reference: 'relative_seconds',
        warnings: ['Touching boundaries were coalesced.'],
        provenance,
      })
    );
    badTimeIntervals.mockResolvedValue(
      response({
        ...intervalPayload([{ index: 1, start: 10, stop: 12, length_s: 2 }]),
        observation_start: 0,
        observation_stop: 20,
        good_exposure_s: 18,
        bad_exposure_s: 2,
        time_unit: 's',
        time_reference: 'relative_seconds',
        warnings: [],
        provenance,
      })
    );
    previewMask.mockResolvedValue(
      response({
        event_list_name: 'obs1',
        source_event_count: 4,
        retained_event_count: 3,
        rejected_event_count: 1,
        retained_exposure_s: 10,
        time_unit: 's',
        time_reference: 'absolute_mission_time',
        applied_gtis: intervalPayload([{ index: 1, start: 0, stop: 10, length_s: 10 }]),
        mask_preview: {
          time: [1, 2, 3, 4],
          retained: [true, false, true, true],
          shown: 4,
          total: 4,
          truncated: false,
        },
        plot: { time: [1, 4], retained: [1, 1], stride: 2, source_points: 4 },
        warnings: ['Requested intervals were clipped to effective GTIs.'],
        provenance,
      })
    );
    saveMask.mockResolvedValue(
      response({
        source_event_list_name: 'obs1',
        destination_name: 'derived',
        time_unit: 's',
        time_reference: 'absolute_mission_time',
        source_event_count: 4,
        retained_event_count: 3,
        rejected_event_count: 1,
        retained_exposure_s: 10,
        applied_gtis: intervalPayload([{ index: 1, start: 0, stop: 10, length_s: 10 }]),
        warnings: [],
        provenance,
      })
    );
    fixedSegments.mockResolvedValue(
      response({
        ...intervalPayload([
          { index: 1, start: 0, stop: 5, length_s: 5 },
          { index: 2, start: 5, stop: 10, length_s: 5 },
        ]),
        segment_size_s: 5,
        source_exposure_s: 25,
        segmented_exposure_s: 20,
        unused_exposure_s: 5,
        time_unit: 's',
        time_reference: 'relative_seconds',
        warnings: ['5 s of remainder was omitted.'],
        provenance,
      })
    );
    exposureSegments.mockResolvedValue(
      response({
        exposure_per_chunk_s: 8,
        new_interval_if_gti_sep_s: 2,
        source_exposure_s: 25,
        output_exposure_s: 25,
        chunk_count: 2,
        interval_count: 2,
        chunks: [
          {
            chunk_index: 1,
            ...intervalPayload([{ index: 1, start: 0, stop: 10, length_s: 10 }]),
          },
          {
            chunk_index: 2,
            ...intervalPayload([{ index: 1, start: 20, stop: 35, length_s: 15 }]),
          },
        ],
        plot: {
          starts: [0, 20],
          stops: [10, 35],
          chunk_indices: [1, 2],
          stride: 1,
          source_points: 2,
        },
        time_unit: 's',
        time_reference: 'relative_seconds',
        warnings: ['Exposure splitting is approximate.'],
        provenance,
      })
    );
  });

  it('is ready, explains effective GTIs, and handles an empty EventList registry', async () => {
    listEventLists.mockResolvedValue(response([]));
    renderWithProviders(<GTIPage />);

    expect(screen.getByRole('heading', { name: 'GTI Functionality' })).toBeInTheDocument();
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
    expect(screen.getByText(/does not infer good time from the first and last event/i)).toBeInTheDocument();
    expect((await screen.findAllByText(/No event lists loaded/)).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Inspect effective GTIs' })).toBeDisabled();
    expect(inspect).not.toHaveBeenCalled();
  });

  it('rejects malformed, overlapping, and non-positive manual rows before submission', async () => {
    renderWithProviders(<GTIPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'Edit & validate' }));

    await fill('Manual GTIs', '0, 10\n9, 12');
    expect(screen.getByText(/row 2: overlaps row 1/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Validate rows' })).toBeDisabled();

    await fill('Manual GTIs', '4, 4');
    expect(screen.getByText(/stop must be greater than start/)).toBeInTheDocument();
    expect(validate).not.toHaveBeenCalled();
  });

  it('sends exact validation, set-operation, and BTI payloads with time-reference metadata', async () => {
    renderWithProviders(<GTIPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'Edit & validate' }));
    await fill('Manual GTIs', '0, 10\n12, 20');
    await chooseSelect('Time reference', /Relative seconds/);
    await userEvent.click(screen.getByRole('button', { name: 'Validate rows' }));

    await waitFor(() =>
      expect(validate).toHaveBeenCalledWith({
        gtis: [
          [0, 10],
          [12, 20],
        ],
        time_reference: 'relative_seconds',
      })
    );
    expect(await screen.findByText(/All rows are finite/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Set operations & BTIs' }));
    await fill('Left / good GTIs', '0, 10\n12, 20');
    await fill('Right GTIs', '5, 8\n20, 25');
    await chooseSelect('Set operation', /Union/);
    await chooseSelect('Time reference', /Relative seconds/);
    await userEvent.click(screen.getByRole('button', { name: 'Compute set result' }));

    await waitFor(() =>
      expect(setOperation).toHaveBeenCalledWith({
        left_gtis: [
          [0, 10],
          [12, 20],
        ],
        right_gtis: [
          [5, 8],
          [20, 25],
        ],
        operation: 'union',
        time_reference: 'relative_seconds',
      })
    );
    expect(await screen.findByText('Touching boundaries were coalesced.')).toBeInTheDocument();

    await fill('Observation start (s)', '0');
    await fill('Observation stop (s)', '20');
    await userEvent.click(screen.getByRole('button', { name: 'Generate BTIs' }));
    await waitFor(() =>
      expect(badTimeIntervals).toHaveBeenCalledWith({
        gtis: [
          [0, 10],
          [12, 20],
        ],
        start_time: 0,
        stop_time: 20,
        time_reference: 'relative_seconds',
      })
    );
  }, 10_000);

  it('keeps exact inspection rows and the previous result after a later error', async () => {
    const exactRows = [
      { index: 1, start: 0, stop: 10, length_s: 10 },
      { index: 2, start: 12, stop: 20, length_s: 8 },
    ];
    inspect
      .mockResolvedValueOnce(
        response({
          ...intervalPayload(exactRows, [exactRows[0]]),
          event_list_name: 'obs1',
          event_count: 4,
          gti_status: 'available',
          gti_origin: 'effective_event_list_gti',
          time_unit: 's',
          time_reference: 'absolute_mission_time',
          mjdref: 59000,
          warnings: ['Inspection warning'],
          provenance,
        })
      )
      .mockResolvedValueOnce({
        success: false,
        data: null,
        message: 'could not inspect',
        error: 'backend exploded',
      });
    renderWithProviders(<GTIPage />);
    await selectEventList('Event list to inspect', /obs1/);
    const button = screen.getByRole('button', { name: 'Inspect effective GTIs' });
    await userEvent.click(button);

    await waitFor(() => expect(inspect).toHaveBeenCalledWith({ event_list_name: 'obs1' }));

    const table = await screen.findByRole('table', { name: 'Effective GTIs — exact intervals' });
    expect(within(table).getByText('12')).toBeInTheDocument();
    expect(screen.getByText('Inspection warning')).toBeInTheDocument();
    expect(screen.getByTestId('chart')).toHaveTextContent('"base":[0]');
    expect(screen.getByTestId('chart')).not.toHaveTextContent('"base":[0,12]');

    await userEvent.click(button);
    expect(await screen.findByText('backend exploded')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Effective GTIs — exact intervals' })).toBeInTheDocument();
    expect(screen.getByText('Inspection warning')).toBeInTheDocument();
  });

  it('preserves inspected and validated row handoffs across the extracted workflows', async () => {
    renderWithProviders(<GTIPage />);
    await selectEventList('Event list to inspect', /obs1/);
    await userEvent.click(screen.getByRole('button', { name: 'Inspect effective GTIs' }));
    await screen.findByRole('table', { name: 'Effective GTIs — exact intervals' });

    await userEvent.click(screen.getByRole('tab', { name: 'Edit & validate' }));
    await userEvent.click(
      screen.getByRole('button', { name: 'Use inspected effective GTIs from obs1' })
    );
    expect(within(screen.getByRole('tabpanel')).getByLabelText('Manual GTIs')).toHaveValue(
      '0, 10\n12, 20'
    );
    await chooseSelect('Time reference', /Relative seconds/);
    await userEvent.click(screen.getByRole('button', { name: 'Validate rows' }));
    await screen.findByText(/All rows are finite/);
    await userEvent.click(
      screen.getByRole('button', { name: 'Use validated rows in compatible tools' })
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Set operations & BTIs' }));
    expect(within(screen.getByRole('tabpanel')).getByLabelText('Left / good GTIs')).toHaveValue(
      '0, 10\n12, 20'
    );
    expect(within(screen.getByRole('tabpanel')).getByLabelText('Time reference')).toHaveTextContent(
      'Relative seconds'
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Segmentation' }));
    expect(within(screen.getByRole('tabpanel')).getByLabelText('GTIs to segment')).toHaveValue(
      '0, 10\n12, 20'
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Mask & save' }));
    expect(within(screen.getByRole('tabpanel')).getByLabelText('Requested mask GTIs')).toHaveValue('');
    expect(screen.getByText(/Relative rows are copied to set operations and segmentation/)).not.toBeVisible();
  });

  it('never applies inspected GTIs to a different EventList source', async () => {
    renderWithProviders(<GTIPage />);
    await selectEventList('Event list to inspect', /obs1/);
    await userEvent.click(screen.getByRole('button', { name: 'Inspect effective GTIs' }));
    await screen.findByRole('table', { name: 'Effective GTIs — exact intervals' });

    await userEvent.click(screen.getByRole('tab', { name: 'Mask & save' }));
    await selectEventList('Source event list', /existing/);

    const reuseButton = screen.getByRole('button', {
      name: 'Use inspected effective GTIs from obs1',
    });
    expect(reuseButton).toBeDisabled();
    expect(screen.getByText(/belong to obs1, not existing/)).toBeInTheDocument();
    expect(within(screen.getByRole('tabpanel')).getByLabelText('Requested mask GTIs')).toHaveValue(
      ''
    );
  });

  it('previews exact masks, blocks known duplicate names, surfaces a race error, then saves uniquely', async () => {
    renderWithProviders(<GTIPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'Mask & save' }));
    await selectEventList('Source event list', /obs1/);
    await fill('Requested mask GTIs', '0, 10');
    await userEvent.click(screen.getByRole('button', { name: 'Preview mask' }));

    await waitFor(() =>
      expect(previewMask).toHaveBeenCalledWith({ event_list_name: 'obs1', gtis: [[0, 10]] })
    );
    const maskTable = await screen.findByRole('table', { name: 'Exact mask preview' });
    expect(within(maskTable).getByText('false')).toBeInTheDocument();
    expect(screen.getByText('Requested intervals were clipped to effective GTIs.')).toBeInTheDocument();
    expect(screen.getAllByTestId('chart')[0]).toHaveTextContent('"x":[1,4]');

    await fill('Save as EventList name', 'existing');
    expect(screen.getByText('An EventList with this name already exists')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save as new EventList' })).toBeDisabled();

    saveMask.mockResolvedValueOnce({
      success: false,
      data: null,
      message: "EventList 'race-name' already exists; choose a unique name",
      error: null,
    });
    await fill('Save as EventList name', 'race-name');
    await userEvent.click(screen.getByRole('button', { name: 'Save as new EventList' }));
    expect(await screen.findByText(/race-name.*already exists/)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Exact mask preview' })).toBeInTheDocument();

    await fill('Save as EventList name', 'derived');
    await userEvent.click(screen.getByRole('button', { name: 'Save as new EventList' }));
    await waitFor(() =>
      expect(saveMask).toHaveBeenLastCalledWith({
        event_list_name: 'obs1',
        gtis: [[0, 10]],
        destination_name: 'derived',
      })
    );
    expect(await screen.findByText(/Saved 3 events as/)).toBeInTheDocument();
    expect(screen.getByText('Time basis: absolute mission time (s).')).toBeInTheDocument();
    await waitFor(() => expect(listEventLists.mock.calls.length).toBeGreaterThan(1));
  }, 10_000);

  it('invalidates a stale mask preview when the rows change', async () => {
    renderWithProviders(<GTIPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'Mask & save' }));
    await selectEventList('Source event list', /obs1/);
    await fill('Requested mask GTIs', '0, 10');
    await userEvent.click(screen.getByRole('button', { name: 'Preview mask' }));
    await screen.findByRole('table', { name: 'Exact mask preview' });
    await fill('Save as EventList name', 'derived');
    expect(screen.getByRole('button', { name: 'Save as new EventList' })).toBeEnabled();

    await fill('Requested mask GTIs', '0, 8');
    expect(screen.getByText(/Preview again before saving/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save as new EventList' })).toBeDisabled();
    expect(saveMask).not.toHaveBeenCalled();
  });

  it('validates segment size and sends exact fixed/exposure payloads with tables and plots', async () => {
    renderWithProviders(<GTIPage />);
    await userEvent.click(screen.getByRole('tab', { name: 'Segmentation' }));
    await fill('GTIs to segment', '0, 10\n20, 35');
    await chooseSelect('Time reference', /Relative seconds/);

    await fill('Segment size (s)', '100');
    expect(screen.getByText('Segment size exceeds every GTI length')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate fixed segments' })).toBeDisabled();
    await fill('Segment size (s)', '5');
    await userEvent.click(screen.getByRole('button', { name: 'Generate fixed segments' }));
    await waitFor(() =>
      expect(fixedSegments).toHaveBeenCalledWith({
        gtis: [
          [0, 10],
          [20, 35],
        ],
        segment_size: 5,
        time_reference: 'relative_seconds',
      })
    );
    expect(await screen.findByText('5 s of remainder was omitted.')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Fixed segments — exact intervals' })).toBeInTheDocument();

    await fill('Exposure per chunk (s)', '8');
    await fill('Start new chunk when GTI gap exceeds (s)', '2');
    await userEvent.click(screen.getByRole('button', { name: 'Split by exposure' }));
    await waitFor(() =>
      expect(exposureSegments).toHaveBeenCalledWith({
        gtis: [
          [0, 10],
          [20, 35],
        ],
        exposure_per_chunk: 8,
        new_interval_if_gti_sep: 2,
        time_reference: 'relative_seconds',
      })
    );
    expect(await screen.findByText('Exposure splitting is approximate.')).toBeInTheDocument();
    expect(
      screen.getByRole('table', { name: 'Exposure chunks — exact intervals' })
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('chart').length).toBeGreaterThanOrEqual(2);
  });
});

describe('gtiApi route boundary', () => {
  it('uses the explicit utility endpoints and forwards only typed request fields', async () => {
    const [{ gtiApi: actualGtiApi }, { apiClient }] = await Promise.all([
      vi.importActual<typeof import('@/api/gtiApi')>('@/api/gtiApi'),
      import('@/api/client'),
    ]);
    const post = vi.spyOn(apiClient, 'post').mockImplementation(async () => ({
      success: true,
      data: null,
      message: '',
      error: null,
    }));
    const rows: [number, number][] = [[0, 10]];

    await actualGtiApi.inspect({ event_list_name: 'obs1' });
    await actualGtiApi.validate({ gtis: rows, time_reference: 'relative_seconds' });
    await actualGtiApi.setOperation({
      left_gtis: rows,
      right_gtis: [[20, 30]],
      operation: 'append',
      time_reference: 'relative_seconds',
    });
    await actualGtiApi.badTimeIntervals({
      gtis: rows,
      start_time: 0,
      stop_time: 20,
      time_reference: 'relative_seconds',
    });
    await actualGtiApi.previewMask({ event_list_name: 'obs1', gtis: rows });
    await actualGtiApi.saveMask({
      event_list_name: 'obs1',
      gtis: rows,
      destination_name: 'derived',
    });
    await actualGtiApi.fixedSegments({
      gtis: rows,
      segment_size: 5,
      time_reference: 'relative_seconds',
    });
    await actualGtiApi.exposureSegments({
      gtis: rows,
      exposure_per_chunk: 8,
      new_interval_if_gti_sep: 2,
      time_reference: 'relative_seconds',
    });

    expect(post.mock.calls).toEqual([
      ['/api/utilities/gti/inspect', { event_list_name: 'obs1' }],
      ['/api/utilities/gti/validate', { gtis: rows, time_reference: 'relative_seconds' }],
      [
        '/api/utilities/gti/set-operation',
        {
          left_gtis: rows,
          right_gtis: [[20, 30]],
          operation: 'append',
          time_reference: 'relative_seconds',
        },
      ],
      [
        '/api/utilities/gti/bad-time-intervals',
        {
          gtis: rows,
          start_time: 0,
          stop_time: 20,
          time_reference: 'relative_seconds',
        },
      ],
      ['/api/utilities/gti/mask/preview', { event_list_name: 'obs1', gtis: rows }],
      [
        '/api/utilities/gti/mask/save',
        { event_list_name: 'obs1', gtis: rows, destination_name: 'derived' },
      ],
      [
        '/api/utilities/gti/segment/fixed',
        { gtis: rows, segment_size: 5, time_reference: 'relative_seconds' },
      ],
      [
        '/api/utilities/gti/segment/exposure',
        {
          gtis: rows,
          exposure_per_chunk: 8,
          time_reference: 'relative_seconds',
          new_interval_if_gti_sep: 2,
        },
      ],
    ]);
    post.mockRestore();
  });
});
