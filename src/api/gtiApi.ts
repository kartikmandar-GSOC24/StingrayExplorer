/** Typed API boundary for the Utilities GTI workbench. */

import { apiClient } from './client';
import type { ApiResponse } from './client';

export type GtiTimeReference = 'absolute_mission_time' | 'relative_seconds';
export type GtiSetOperation = 'intersection' | 'union' | 'append';

export interface GtiIntervalRow {
  index: number;
  start: number;
  stop: number;
  length_s: number | null;
}

export interface GtiIntervalPlot {
  starts: number[];
  stops: number[];
  interval_indices: number[];
  stride: number;
  source_points: number;
}

export interface GtiIntervalPayload {
  intervals: GtiIntervalRow[];
  interval_count: number;
  lengths_s: Array<number | null>;
  separations_s: Array<number | null>;
  total_exposure_s: number | null;
  overall_time_span_s: number | null;
  duty_cycle: number | null;
  plot: GtiIntervalPlot;
}

interface GtiResultBase {
  warnings: string[];
  provenance: Record<string, unknown>;
}

interface TimedGtiResult extends GtiResultBase {
  time_unit: 's';
  time_reference: GtiTimeReference;
}

export interface GtiInspectionData extends GtiIntervalPayload, TimedGtiResult {
  event_list_name: string;
  event_count: number;
  gti_status: 'available' | 'missing' | 'empty';
  gti_origin: 'effective_event_list_gti';
  mjdref: number | null;
}

export interface GtiValidationData extends GtiIntervalPayload, TimedGtiResult {
  valid: true;
}

export interface GtiSetOperationData extends GtiIntervalPayload, TimedGtiResult {
  operation: GtiSetOperation;
  merge_strategy: string;
}

export interface GtiBadTimeData extends GtiIntervalPayload, TimedGtiResult {
  observation_start: number;
  observation_stop: number;
  good_exposure_s: number | null;
  bad_exposure_s: number | null;
}

export interface GtiMaskPreviewData extends GtiResultBase {
  event_list_name: string;
  source_event_count: number;
  retained_event_count: number;
  rejected_event_count: number;
  retained_exposure_s: number | null;
  time_unit: 's';
  time_reference: 'absolute_mission_time';
  applied_gtis: GtiIntervalPayload;
  mask_preview: {
    time: number[];
    retained: boolean[];
    shown: number;
    total: number;
    truncated: boolean;
  };
  plot: {
    time: number[];
    retained: Array<boolean | number>;
    stride: number;
    source_points: number;
  };
}

export interface GtiMaskSaveData extends TimedGtiResult {
  source_event_list_name: string;
  destination_name: string;
  source_event_count: number;
  retained_event_count: number;
  rejected_event_count: number;
  retained_exposure_s: number | null;
  applied_gtis: GtiIntervalPayload;
}

export interface GtiFixedSegmentsData extends GtiIntervalPayload, TimedGtiResult {
  segment_size_s: number;
  source_exposure_s: number | null;
  segmented_exposure_s: number | null;
  unused_exposure_s: number | null;
}

export interface GtiExposureChunk extends GtiIntervalPayload {
  chunk_index: number;
}

export interface GtiExposureSegmentsData extends TimedGtiResult {
  exposure_per_chunk_s: number;
  new_interval_if_gti_sep_s: number | null;
  source_exposure_s: number | null;
  output_exposure_s: number | null;
  chunk_count: number;
  interval_count: number;
  chunks: GtiExposureChunk[];
  plot: {
    starts: number[];
    stops: number[];
    chunk_indices: number[];
    stride: number;
    source_points: number;
  };
}

export const gtiApi = {
  inspect(params: { event_list_name: string }): Promise<ApiResponse<GtiInspectionData>> {
    return apiClient.post('/api/utilities/gti/inspect', params);
  },

  validate(params: {
    gtis: [number, number][];
    time_reference: GtiTimeReference;
  }): Promise<ApiResponse<GtiValidationData>> {
    return apiClient.post('/api/utilities/gti/validate', params);
  },

  setOperation(params: {
    left_gtis: [number, number][];
    right_gtis: [number, number][];
    operation: GtiSetOperation;
    time_reference: GtiTimeReference;
  }): Promise<ApiResponse<GtiSetOperationData>> {
    return apiClient.post('/api/utilities/gti/set-operation', params);
  },

  badTimeIntervals(params: {
    gtis: [number, number][];
    start_time: number;
    stop_time: number;
    time_reference: GtiTimeReference;
  }): Promise<ApiResponse<GtiBadTimeData>> {
    return apiClient.post('/api/utilities/gti/bad-time-intervals', params);
  },

  previewMask(params: {
    event_list_name: string;
    gtis: [number, number][];
  }): Promise<ApiResponse<GtiMaskPreviewData>> {
    return apiClient.post('/api/utilities/gti/mask/preview', params);
  },

  saveMask(params: {
    event_list_name: string;
    gtis: [number, number][];
    destination_name: string;
  }): Promise<ApiResponse<GtiMaskSaveData>> {
    return apiClient.post('/api/utilities/gti/mask/save', params);
  },

  fixedSegments(params: {
    gtis: [number, number][];
    segment_size: number;
    time_reference: GtiTimeReference;
  }): Promise<ApiResponse<GtiFixedSegmentsData>> {
    return apiClient.post('/api/utilities/gti/segment/fixed', params);
  },

  exposureSegments(params: {
    gtis: [number, number][];
    exposure_per_chunk: number;
    new_interval_if_gti_sep?: number;
    time_reference: GtiTimeReference;
  }): Promise<ApiResponse<GtiExposureSegmentsData>> {
    const payload = {
      gtis: params.gtis,
      exposure_per_chunk: params.exposure_per_chunk,
      time_reference: params.time_reference,
      ...(params.new_interval_if_gti_sep === undefined
        ? {}
        : { new_interval_if_gti_sep: params.new_interval_if_gti_sep }),
    };
    return apiClient.post('/api/utilities/gti/segment/exposure', payload);
  },
};

export default gtiApi;
