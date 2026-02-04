/**
 * Log streaming API client using Server-Sent Events (SSE).
 *
 * Connects to the backend log stream and pushes log entries to the logStore.
 */

import { useLogStore } from '@/store/logStore';
import { apiClient } from './client';

/**
 * Log entry received from the backend SSE stream.
 */
interface StreamLogEntry {
  type: 'log' | 'heartbeat';
  timestamp: string;
  level?: 'info' | 'warn' | 'error' | 'debug';
  source?: 'python';
  logger?: string;
  message?: string;
}

/**
 * SSE client for real-time log streaming from the backend.
 *
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Heartbeat handling to detect stale connections
 * - Integration with Zustand logStore
 */
class LogStreamClient {
  private eventSource: EventSource | null = null;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private isConnecting: boolean = false;

  /**
   * Connect to the log stream SSE endpoint.
   *
   * Will automatically reconnect on connection loss with exponential backoff.
   */
  async connect(): Promise<void> {
    // Avoid duplicate connections
    if (this.eventSource || this.isConnecting) {
      console.log('[LogStreamClient] Already connected or connecting');
      return;
    }

    this.isConnecting = true;

    try {
      // Get current port from API client
      const port = await apiClient.getPort();
      const url = `http://127.0.0.1:${port}/api/logs/stream`;

      console.log('[LogStreamClient] Connecting to:', url);

      this.eventSource = new EventSource(url);

      this.eventSource.onopen = (): void => {
        console.log('[LogStreamClient] Connected to log stream');
        this.reconnectAttempts = 0;
        this.isConnecting = false;

        // Add a log entry to indicate connection
        useLogStore.getState().addLog({
          level: 'info',
          source: 'frontend',
          message: 'Connected to Python log stream',
        });
      };

      this.eventSource.onmessage = (event: MessageEvent<string>): void => {
        try {
          const data: StreamLogEntry = JSON.parse(event.data);

          // Skip heartbeat events
          if (data.type === 'heartbeat') {
            return;
          }

          // Add log entry to store
          if (data.type === 'log' && data.level && data.message) {
            useLogStore.getState().addLog({
              level: data.level,
              source: data.source || 'python',
              message: data.message,
            });
          }
        } catch (error) {
          console.error('[LogStreamClient] Failed to parse log event:', error);
        }
      };

      this.eventSource.onerror = (): void => {
        console.warn('[LogStreamClient] Connection error, will attempt reconnect');
        this.isConnecting = false;
        this.handleDisconnect();
      };
    } catch (error) {
      console.error('[LogStreamClient] Failed to connect:', error);
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from the log stream.
   */
  disconnect(): void {
    console.log('[LogStreamClient] Disconnecting');

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    this.reconnectAttempts = 0;
    this.isConnecting = false;
  }

  /**
   * Check if currently connected to the log stream.
   */
  isConnected(): boolean {
    return this.eventSource !== null && this.eventSource.readyState === EventSource.OPEN;
  }

  /**
   * Handle disconnection and schedule reconnect.
   */
  private handleDisconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    this.scheduleReconnect();
  }

  /**
   * Schedule a reconnection attempt with exponential backoff.
   */
  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[LogStreamClient] Max reconnect attempts reached, giving up');
      useLogStore.getState().addLog({
        level: 'error',
        source: 'frontend',
        message: 'Log stream connection failed after maximum retries',
      });
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s (capped at 32s)
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 32000);
    this.reconnectAttempts++;

    console.log(
      `[LogStreamClient] Scheduling reconnect attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts} in ${delay}ms`
    );

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}

// Export singleton instance
export const logStreamClient = new LogStreamClient();

/**
 * Log API namespace for direct function access.
 */
export const logApi = {
  /**
   * Connect to the log stream.
   */
  connect: (): Promise<void> => logStreamClient.connect(),

  /**
   * Disconnect from the log stream.
   */
  disconnect: (): void => logStreamClient.disconnect(),

  /**
   * Check if connected to the log stream.
   */
  isConnected: (): boolean => logStreamClient.isConnected(),
};

export default logApi;
