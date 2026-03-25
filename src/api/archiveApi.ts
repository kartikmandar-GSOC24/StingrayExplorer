/**
 * API functions for HEASARC archive operations
 */

import { apiClient, ApiResponse } from './client';

// Types

/** Supported HEASARC catalog information */
export interface HeasarcCatalog {
  id: string;
  catalog: string;
  display_name: string;
  description: string;
}

/** HEASARC observation result */
export interface HeasarcObservation {
  obsid: string;
  name: string;
  ra: number | null;
  dec: number | null;
  exposure: number | null;
  time: string;
  catalog: string;
  // Mission-specific fields
  prnb?: string;  // RXTE proposal number
  // Swift instrument-specific exposures
  xrt_exposure?: number | null;
  bat_exposure?: number | null;
  uvot_exposure?: number | null;
  // IXPE per-detector-unit exposures
  exposure_du1?: number | null;
  exposure_du2?: number | null;
  exposure_du3?: number | null;
  // NuSTAR-specific fields
  exposure_b?: number | null;     // FPMB exposure (seconds)
  observation_mode?: string;       // "SCIENCE" or "SLEW"
  issue_flag?: number | null;      // 0=OK, 1=known issues
  // NICER-specific fields
  processing_status?: string;
  num_fpm?: number | null;
  // XMM-Newton-specific fields (per-instrument data only via ObsID/ADQL search)
  pn_time?: number | null;      // EPIC-PN exposure (seconds)
  pn_mode?: string;             // EPIC-PN observation mode
  mos1_time?: number | null;    // EPIC-MOS1 exposure (seconds)
  mos1_mode?: string;           // EPIC-MOS1 observation mode
  mos2_time?: number | null;    // EPIC-MOS2 exposure (seconds)
  mos2_mode?: string;           // EPIC-MOS2 observation mode
  xmm_status?: string;          // "archived" or "scheduled"
  data_in_heasarc?: string;     // "Y" or "N"
  // Chandra-specific fields
  detector?: string;            // "ACIS-I", "ACIS-S", "HRC-I", "HRC-S"
  grating?: string;             // "NONE", "HETG", "LETG"
  chandra_status?: string;      // "archived", "observed", "scheduled", etc.
}

/** Search result from HEASARC */
export interface SearchResult {
  observations: HeasarcObservation[];
  count: number;
  mission: string;
  radius?: number;
  // For name search
  source_name?: string;
  resolved_ra?: number;
  resolved_dec?: number;
  // For coordinate search
  ra?: number;
  dec?: number;
  // For obsid search
  obsid?: string;
}

/** Download URLs for an observation */
export interface ObservationUrls {
  urls: Record<string, string>;
  mission: string;
  obsid: string;
}

// File Browser types
export type FileType = 'event' | 'calibration' | 'auxiliary' | 'log' | 'directory' | 'other';

export interface FileEntry {
  path: string;
  name: string;
  is_directory: boolean;
  file_type: FileType;
  size_bytes: number | null;
  size_display: string;
  full_url: string;
  children?: FileEntry[];
}

export interface ListFilesResponse {
  base_url: string;
  files: FileEntry[];
  mission: string;
  obsid: string;
  total_files: number;
}

// Download to disk SSE event types
export interface DownloadToDiskProgressEvent {
  type: 'progress';
  bytes_downloaded: number;
  total_bytes: number;
  percent: number;
}

export interface DownloadToDiskCompleteEvent {
  type: 'complete';
  file_path: string;
  size_bytes: number;
}

export interface DownloadToDiskErrorEvent {
  type: 'error';
  error: string;
}

export type DownloadToDiskEvent =
  | DownloadToDiskProgressEvent
  | DownloadToDiskCompleteEvent
  | DownloadToDiskErrorEvent;

// API functions
export const archiveApi = {
  /**
   * Get list of supported HEASARC catalogs
   */
  async getCatalogs(): Promise<ApiResponse<{ catalogs: HeasarcCatalog[] }>> {
    return apiClient.get('/api/archive/catalogs');
  },

  /**
   * Search HEASARC by source name
   */
  async searchByName(params: {
    source_name: string;
    mission: string;
    radius?: number;
    max_results?: number;
    min_exposure?: number;
    start_date?: string;  // ISO "YYYY-MM-DD"
    end_date?: string;    // ISO "YYYY-MM-DD"
  }): Promise<ApiResponse<SearchResult>> {
    return apiClient.post('/api/archive/search/name', {
      source_name: params.source_name,
      mission: params.mission,
      radius: params.radius ?? 0.5,
      max_results: params.max_results ?? 100,
      min_exposure: params.min_exposure,
      start_date: params.start_date,
      end_date: params.end_date,
    });
  },

  /**
   * Search HEASARC by coordinates
   */
  async searchByCoordinates(params: {
    ra: number;
    dec: number;
    mission: string;
    radius?: number;
    max_results?: number;
    min_exposure?: number;
    start_date?: string;  // ISO "YYYY-MM-DD"
    end_date?: string;    // ISO "YYYY-MM-DD"
  }): Promise<ApiResponse<SearchResult>> {
    return apiClient.post('/api/archive/search/coordinates', {
      ra: params.ra,
      dec: params.dec,
      mission: params.mission,
      radius: params.radius ?? 0.5,
      max_results: params.max_results ?? 100,
      min_exposure: params.min_exposure,
      start_date: params.start_date,
      end_date: params.end_date,
    });
  },

  /**
   * Search HEASARC by Observation ID
   */
  async searchByObsid(params: {
    obsid: string;
    mission: string;
  }): Promise<ApiResponse<SearchResult>> {
    return apiClient.post('/api/archive/search/obsid', {
      obsid: params.obsid,
      mission: params.mission,
    });
  },

  /**
   * Get download URLs for an observation
   */
  async getObservationUrls(
    mission: string,
    obsid: string
  ): Promise<ApiResponse<ObservationUrls>> {
    return apiClient.get(`/api/archive/observation/${mission}/${obsid}`);
  },

  /**
   * List all files in an observation directory
   *
   * Returns a tree structure of files with metadata including sizes,
   * file type classification, and download URLs.
   *
   * @param params.obs_data - Additional observation data for directory lookup:
   *   - ra/dec: Coordinates for locate_data query (helps find directory)
   *   - prnb: RXTE proposal number (required for RXTE)
   */
  async listObservationFiles(params: {
    mission: string;
    obsid: string;
    obs_time?: string;
    obs_data?: {
      ra?: number | null;
      dec?: number | null;
      prnb?: string;
    };
    recursive?: boolean;
    max_depth?: number;
  }): Promise<ApiResponse<ListFilesResponse>> {
    return apiClient.post('/api/archive/list-files', {
      mission: params.mission,
      obsid: params.obsid,
      obs_time: params.obs_time,
      obs_data: params.obs_data,
      recursive: params.recursive ?? true,
      max_depth: params.max_depth ?? 3,
    });
  },

  /**
   * Download a file from URL to local disk with SSE progress streaming.
   *
   * This function routes the download through the backend to bypass CORS
   * restrictions. Progress is streamed as SSE events.
   *
   * @param params.url - URL to download from (e.g., HEASARC HTTPS URL)
   * @param params.save_path - Local path to save the file
   * @yields DownloadToDiskEvent - Progress, complete, or error events
   */
  async *downloadToDiskSSE(params: {
    url: string;
    save_path: string;
  }): AsyncGenerator<DownloadToDiskEvent, void, unknown> {
    const port = await apiClient.getPort();
    const endpointUrl = `http://localhost:${port}/api/archive/download-to-disk`;

    const response = await fetch(endpointUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: params.url,
        save_path: params.save_path,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body available for streaming');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE format: "data: {...}\n\n"
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6);
            try {
              const event = JSON.parse(jsonStr) as DownloadToDiskEvent;
              yield event;
            } catch (parseError) {
              console.error('Failed to parse SSE event:', parseError, jsonStr);
            }
          }
        }
      }

      // Process remaining buffer
      if (buffer.trim() && buffer.startsWith('data: ')) {
        const jsonStr = buffer.slice(6).trim();
        if (jsonStr) {
          try {
            const event = JSON.parse(jsonStr) as DownloadToDiskEvent;
            yield event;
          } catch (parseError) {
            console.error('Failed to parse final SSE event:', parseError, jsonStr);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};

export default archiveApi;
