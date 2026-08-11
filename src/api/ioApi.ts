import { apiClient, ApiResponse } from './client';

const IO_PREFIX = '/api/utilities/io';

export interface UtilityMetadata {
  warnings: string[];
  provenance: Record<string, unknown>;
}

export interface GrantedPathRequest {
  file_path: string;
  file_grant: string;
}

export interface FitsColumnSummary {
  name: string;
  format: string;
  unit: string | null;
}

export interface FitsHighPrecisionValue {
  decimal: string;
  stingray_value: string;
  source_keywords: Record<string, string>;
}

export type FitsMjdReference = FitsHighPrecisionValue;

export interface FitsTimingSummary {
  mjdref: FitsMjdReference | null;
  status: 'available' | 'missing' | 'invalid';
  note: string;
  keywords: Record<string, string | number | boolean | null>;
  high_precision_keywords: Record<string, FitsHighPrecisionValue>;
}

export interface FitsHduSummary {
  index: number;
  name: string;
  type: string;
  row_count: number | null;
  dimensions: number[];
  columns: FitsColumnSummary[];
  timing: FitsTimingSummary;
}

export interface FileInspectionResult extends UtilityMetadata {
  path: string;
  filename: string;
  extension: string | null;
  size_bytes: number;
  supported: boolean;
  detected_type: 'fits' | 'rmf' | 'unknown';
  hdus: FitsHduSummary[];
}

export interface RmfChannelBound {
  channel: number;
  energy_min: number;
  energy_max: number;
  energy_midpoint: number;
}

export interface RmfInspectionResult extends UtilityMetadata {
  path: string;
  filename: string;
  size_bytes: number;
  channel_count: number;
  channel_min: number;
  channel_max: number;
  energy_min: number;
  energy_max: number;
  energy_unit: string | null;
  conversion_supported: boolean;
  contiguous_channels: boolean;
  preview_rows: RmfChannelBound[];
  preview_truncated: boolean;
}

export interface PiEnergyRow {
  index: number;
  pi: number;
  energy: number;
}

export interface IoPlotPreview {
  arrays: [number[], number[]];
  stride: number;
  source_points: number;
}

export interface PiConversionResult extends UtilityMetadata {
  rows: PiEnergyRow[];
  count: number;
  energy_unit: string;
  plot: IoPlotPreview;
}

export interface EventListConversionResult extends UtilityMetadata {
  source_name: string;
  saved: boolean;
  saved_name: string | null;
  event_count: number;
  energy_unit: string;
  preview_rows: PiEnergyRow[];
  preview_truncated: boolean;
  plot: IoPlotPreview;
  pi_preserved: boolean;
}

export type ExportableObjectType = 'event_list' | 'lightcurve' | 'analysis_result';
export type UtilityExportFormat = 'fits' | 'csv' | 'ecsv' | 'json';

export interface ExportableObject {
  object_type: ExportableObjectType;
  name: string;
  row_count: number | null;
  exportable: boolean;
  formats: UtilityExportFormat[];
  reason: string | null;
}

export interface FormatCapability {
  supported: boolean;
  notes: string;
}

export interface ExportableObjectsResult {
  objects: ExportableObject[];
  capability_matrix: Record<
    ExportableObjectType,
    Record<UtilityExportFormat, FormatCapability>
  >;
  format_allowlist: UtilityExportFormat[];
  excluded_formats: Record<string, string>;
  row_cap: number;
  provenance: Record<string, unknown>;
}

export interface ExportResult extends UtilityMetadata {
  path: string;
  bytes: number;
  format: UtilityExportFormat;
  row_count: number;
  object_type: ExportableObjectType;
  object_name: string;
  verified: boolean;
}

export const ioApi = {
  inspectFile(params: GrantedPathRequest): Promise<ApiResponse<FileInspectionResult>> {
    return apiClient.post(`${IO_PREFIX}/inspect-file`, params);
  },

  inspectRmf(params: {
    rmf_path: string;
    rmf_grant: string;
  }): Promise<ApiResponse<RmfInspectionResult>> {
    return apiClient.post(`${IO_PREFIX}/inspect-rmf`, params);
  },

  convertPi(params: {
    pi_values: number[];
    rmf_path: string;
    rmf_grant: string;
  }): Promise<ApiResponse<PiConversionResult>> {
    return apiClient.post(`${IO_PREFIX}/convert-pi`, params);
  },

  convertEventList(params: {
    event_list_name: string;
    rmf_path: string;
    rmf_grant: string;
    save_as?: string | null;
  }): Promise<ApiResponse<EventListConversionResult>> {
    return apiClient.post(`${IO_PREFIX}/convert-event-list`, params);
  },

  listExportableObjects(): Promise<ApiResponse<ExportableObjectsResult>> {
    return apiClient.get(`${IO_PREFIX}/exportable-objects`);
  },

  exportObject(params: {
    object_type: ExportableObjectType;
    object_name: string;
    format: UtilityExportFormat;
    destination_path: string;
    destination_grant: string;
  }): Promise<ApiResponse<ExportResult>> {
    return apiClient.post(`${IO_PREFIX}/export`, params);
  },
};

export default ioApi;
