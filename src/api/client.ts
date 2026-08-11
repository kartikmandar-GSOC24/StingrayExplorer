/**
 * API client for communicating with the Python backend
 */

export interface ApiResponse<T = unknown> {
  success: boolean;
  data: T | null;
  message: string;
  error: string | null;
  /** Non-fatal scientific advisories, including warnings returned with failures. */
  warnings?: string[];
}

class ApiClient {
  private baseUrl: string = 'http://127.0.0.1:8765';
  private port: number = 8765;

  async setPort(port: number): Promise<void> {
    this.port = port;
    this.baseUrl = `http://127.0.0.1:${port}`;
  }

  async getPort(): Promise<number> {
    // Try to get port from Electron IPC
    if (window.electronAPI?.getBackendPort) {
      try {
        const port = await window.electronAPI.getBackendPort();
        if (port && port !== this.port) {
          console.log(`[ApiClient] Port updated: ${this.port} -> ${port}`);
          await this.setPort(port);
        }
      } catch (error) {
        console.warn('[ApiClient] Failed to get backend port from Electron:', error);
      }
    }
    return this.port;
  }

  async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    // Always sync port before request
    await this.getPort();
    const url = `${this.baseUrl}${endpoint}`;

    console.log(`[ApiClient] ${options.method || 'GET'} ${url}`);

    const defaultHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    const config: RequestInit = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        console.error(`[ApiClient] HTTP ${response.status}:`, errorData);
        const validationMessage = Array.isArray(errorData.detail)
          ? errorData.detail
              .map((issue: { loc?: Array<string | number>; msg?: string }) => {
                const field = issue.loc?.slice(1).join('.') || 'request';
                return `${field}: ${issue.msg || 'invalid value'}`;
              })
              .join('; ')
          : typeof errorData.detail === 'string'
            ? errorData.detail
            : null;
        return {
          success: false,
          data: null,
          message: errorData.message || validationMessage || `HTTP error: ${response.status}`,
          error: errorData.error || validationMessage || response.statusText,
          warnings: Array.isArray(errorData.warnings)
            ? errorData.warnings.filter(
                (warning: unknown): warning is string => typeof warning === 'string'
              )
            : undefined,
        };
      }

      const data = await response.json();
      console.log(`[ApiClient] Response:`, data.success ? 'success' : 'failed');
      return data;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      console.error(`[ApiClient] Fetch error:`, error);
      return {
        success: false,
        data: null,
        message: `Request failed: ${errorMessage}`,
        error: errorMessage,
      };
    }
  }

  async get<T>(endpoint: string): Promise<ApiResponse<T>> {
    return this.request<T>(endpoint, { method: 'GET' });
  }

  async post<T>(endpoint: string, data?: unknown): Promise<ApiResponse<T>> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  async delete<T>(endpoint: string): Promise<ApiResponse<T>> {
    return this.request<T>(endpoint, { method: 'DELETE' });
  }

  async healthCheck(): Promise<boolean> {
    try {
      const response = await this.get<{ status: string }>('/health');
      return response.success && response.data?.status === 'healthy';
    } catch {
      return false;
    }
  }
}

// Export singleton instance
export const apiClient = new ApiClient();

export default apiClient;
