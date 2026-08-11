import { apiClient, type ApiResponse } from './client';

export interface MissionSourceField {
  value: string | null;
  raw_value: string | null;
  source: string | null;
  source_type: 'event_list_attribute' | 'fits_header' | 'override' | 'missing';
  inferred: boolean;
  override: boolean;
  database_supported?: boolean;
}

export interface MissionMapping {
  event_hdu: unknown;
  gti_hdu: unknown;
  time_column: unknown;
  energy_or_channel_column: unknown;
  detector_column: unknown;
  instrument_keyword: unknown;
  mode_keyword: unknown;
}

export interface PreciseCalibration {
  method: string;
  location: string;
}

export interface RoughConversionCapability {
  status: 'supported' | 'conditional' | 'unsupported';
  approximate: boolean;
  dependencies: string[];
  message?: string;
  epoch_mjd_domain?: {
    minimum_exclusive: number;
    maximum_inclusive: number;
  } | null;
}

export interface SpecializedInterpretationCapability {
  supported: boolean;
  scope: string | null;
}

export interface MissionCapabilityRow {
  mission: string;
  mapping: MissionMapping;
  instruments: unknown;
  modes: unknown;
  rough_pi_to_energy: RoughConversionCapability;
  specialized_interpretation: SpecializedInterpretationCapability;
}

export interface MissionCapabilitiesData {
  missions: MissionCapabilityRow[];
  mission_count: number;
  raw_database_entry_count: number;
  database_source: string;
  support_note: string;
  precise_calibration: PreciseCalibration;
  provenance: Record<string, unknown>;
  warnings: string[];
}

export interface MissionInfoData {
  mission: string;
  requested_mission: string;
  mission_name_inferred: boolean;
  instrument: string | null;
  mode: string | null;
  mapping: MissionMapping;
  available_instruments: unknown;
  available_modes: unknown;
  capabilities: {
    rough_pi_to_energy: RoughConversionCapability;
    specialized_interpretation: SpecializedInterpretationCapability;
  };
  precise_calibration: PreciseCalibration;
  provenance: Record<string, unknown>;
  warnings: string[];
}

export interface MissionIdentificationData {
  source: Record<string, unknown>;
  mission: MissionSourceField;
  instrument: MissionSourceField;
  mode: MissionSourceField;
  mapping: MissionMapping | null;
  timing_metadata?: Record<string, MissionTimingMetadataEntry> & {
    mjdref?: MissionMjdReferenceEntry;
  };
  hdus?: Array<{
    index: number;
    name: string;
    type: string;
    rows: number | null;
  }>;
  provenance: Record<string, unknown>;
  warnings: string[];
}

export interface MissionTimingMetadataEntry {
  value: unknown;
  source: string | null;
}

export interface MissionMjdReferenceEntry extends MissionTimingMetadataEntry {
  value: number | null;
  decimal: string;
  components: {
    integer: { value: string; source: string | null };
    fraction: { value: string; source: string | null };
  } | null;
}

export interface ConversionDependency {
  required: boolean;
  used?: boolean;
  value?: string | number | null;
  requested_value?: string | number | null;
  source?: string | null;
}

export interface ApproximateConversionData {
  label: string;
  conversion_type: 'rough_approximate';
  approximate: true;
  energy_unit: 'keV';
  mission: MissionSourceField;
  instrument: MissionSourceField;
  mode: MissionSourceField;
  dependencies: Record<string, ConversionDependency>;
  count: number;
  rows: Array<{
    index: number;
    pi: number;
    energy_kev: number | null;
    detector_id?: number;
  }>;
  preview_count: number;
  preview_truncated: boolean;
  saved_event_list: string | null;
  precise_calibration: PreciseCalibration;
  provenance: Record<string, unknown>;
  warnings: string[];
}

export interface MissionInterpretationData {
  label: string;
  mission: MissionSourceField;
  instrument: MissionSourceField;
  mode: MissionSourceField;
  supported_scope: string;
  read_only: true;
  source_modified: false;
  hdu: string;
  event_count: number;
  changed_count: number;
  original_pha_range: [number, number] | null;
  interpreted_pha_range: [number, number] | null;
  rows: Array<{
    index: number;
    original_pha: number;
    interpreted_pha: number;
    changed: boolean;
  }>;
  preview_count: number;
  preview_truncated: boolean;
  provenance: Record<string, unknown>;
  warnings: string[];
}

interface MissionOverrideParams {
  mission_override?: string;
  instrument_override?: string;
  mode_override?: string;
}

export type IdentifyMissionParams = MissionOverrideParams & (
  | { event_list_name: string; file_path?: never; file_grant?: never }
  | { event_list_name?: never; file_path: string; file_grant: string }
);

interface ConvertPiCommonParams extends MissionOverrideParams {
  epoch_mjd?: number;
  detector_ids?: number[];
}

export type ConvertPiParams = ConvertPiCommonParams & (
  | { pi_values: number[]; event_list_name?: never; save_as?: never }
  | { pi_values?: never; event_list_name: string; save_as?: string }
);

export interface InterpretMissionParams {
  file_path: string;
  file_grant: string;
  mission_override?: string;
  instrument_override?: string;
  mode_override?: string;
}

type EnvelopeWithWarnings<T> = ApiResponse<T> & { warnings?: string[] };

/**
 * Utility services return warnings beside the standard envelope. Fold those
 * warnings into data so useAnalysisRunner can preserve and render them with
 * the last successful result.
 */
async function includeWarnings<T extends object>(
  request: Promise<EnvelopeWithWarnings<T>>
): Promise<ApiResponse<T & { warnings: string[] }>> {
  const response = await request;
  if (response.data === null) return response as ApiResponse<T & { warnings: string[] }>;
  const existing = 'warnings' in response.data && Array.isArray(response.data.warnings)
    ? response.data.warnings as string[]
    : [];
  return {
    ...response,
    data: {
      ...response.data,
      warnings: existing.length > 0 ? existing : response.warnings ?? [],
    },
  };
}

export const missionIoApi = {
  async getCapabilities(): Promise<ApiResponse<MissionCapabilitiesData>> {
    return includeWarnings(
      apiClient.get<MissionCapabilitiesData>('/api/utilities/mission-io/capabilities')
    );
  },

  async getMissionInfo(params: {
    mission: string;
    instrument?: string;
    mode?: string;
  }): Promise<ApiResponse<MissionInfoData>> {
    return includeWarnings(
      apiClient.post<MissionInfoData>('/api/utilities/mission-io/info', params)
    );
  },

  async identify(params: IdentifyMissionParams): Promise<ApiResponse<MissionIdentificationData>> {
    return includeWarnings(
      apiClient.post<MissionIdentificationData>('/api/utilities/mission-io/identify', params)
    );
  },

  async convertPi(params: ConvertPiParams): Promise<ApiResponse<ApproximateConversionData>> {
    return includeWarnings(
      apiClient.post<ApproximateConversionData>('/api/utilities/mission-io/convert-pi', params)
    );
  },

  async interpret(params: InterpretMissionParams): Promise<ApiResponse<MissionInterpretationData>> {
    return includeWarnings(
      apiClient.post<MissionInterpretationData>('/api/utilities/mission-io/interpret', params)
    );
  },
};

export default missionIoApi;
