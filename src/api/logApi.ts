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
  private abortController: AbortController | null = null;
  private connected: boolean = false;
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
    if (this.abortController || this.isConnecting) {
      console.log('[LogStreamClient] Already connected or connecting');
      return;
    }

    this.isConnecting = true;
    const controller = new AbortController();
    this.abortController = controller;

    try {
      console.log('[LogStreamClient] Connecting to authenticated log stream');
      let opened = false;
      for await (const data of apiClient.stream<StreamLogEntry>(
        '/api/logs/stream',
        controller.signal
      )) {
        if (!opened) {
          opened = true;
          this.connected = true;
          this.reconnectAttempts = 0;
          this.isConnecting = false;
          useLogStore.getState().addLog({
            level: 'info',
            source: 'frontend',
            message: 'Connected to Python log stream',
          });
        }
        if (data.type === 'log' && data.level && data.message) {
          useLogStore.getState().addLog({
            level: data.level,
            source: data.source || 'python',
            message: data.message,
          });
        }
      }
      if (!controller.signal.aborted) {
        console.warn('[LogStreamClient] Stream ended, will attempt reconnect');
        this.handleDisconnect();
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      console.error('[LogStreamClient] Failed to connect:', error);
      this.isConnecting = false;
      this.handleDisconnect();
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

    this.abortController?.abort();
    this.abortController = null;
    this.connected = false;

    this.reconnectAttempts = 0;
    this.isConnecting = false;
  }

  /**
   * Check if currently connected to the log stream.
   */
  isConnected(): boolean {
    return this.connected;
  }

  /**
   * Handle disconnection and schedule reconnect.
   */
  private handleDisconnect(): void {
    this.abortController?.abort();
    this.abortController = null;
    this.connected = false;

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
