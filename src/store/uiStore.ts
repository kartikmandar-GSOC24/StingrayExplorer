/**
 * UI state store for global application state
 */

import { create } from 'zustand';

export interface ProcessResources {
  memoryMb: number;
  cpuPercent: number;
}

export interface AppResources {
  // Individual process resources
  backend: ProcessResources | null;
  electronMain: ProcessResources | null;
  electronRenderer: ProcessResources | null;
  // Combined totals (what the app is actually using)
  totalMemoryMb: number;
  totalCpuPercent: number;
  // System reference info
  systemMemoryTotalMb: number;
  systemMemoryAvailableMb: number;
  // Calculated app percentage of system
  appMemoryPercent: number;
}

// Legacy interface for backwards compatibility
export interface SystemResources {
  cpuPercent: number;
  memoryUsedGb: number;
  memoryTotalGb: number;
  memoryPercent: number;
}

interface UIState {
  // Panel visibility
  logPanelOpen: boolean;
  rightToolbarCollapsed: boolean;

  // Processing state
  isProcessing: boolean;
  processingMessage: string;
  processingProgress: number | null; // null = indeterminate

  // System resources (legacy)
  systemResources: SystemResources | null;
  // App-specific resources (new)
  appResources: AppResources | null;

  // Notifications
  notifications: Notification[];
  unreadNotificationCount: number;

  // Search
  searchOpen: boolean;
  searchQuery: string;

  // Actions
  toggleLogPanel: () => void;
  setLogPanelOpen: (open: boolean) => void;
  toggleRightToolbar: () => void;

  setProcessing: (isProcessing: boolean, message?: string, progress?: number | null) => void;

  setSystemResources: (resources: SystemResources | null) => void;
  setAppResources: (resources: AppResources | null) => void;

  addNotification: (notification: Omit<Notification, 'id' | 'timestamp' | 'read'>) => void;
  markNotificationRead: (id: string) => void;
  clearNotifications: () => void;

  setSearchOpen: (open: boolean) => void;
  setSearchQuery: (query: string) => void;
}

export interface Notification {
  id: string;
  timestamp: Date;
  type: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  read: boolean;
}

export const useUIStore = create<UIState>((set) => ({
  // Initial state
  logPanelOpen: false,
  rightToolbarCollapsed: false,
  isProcessing: false,
  processingMessage: '',
  processingProgress: null,
  systemResources: null,
  appResources: null,
  notifications: [],
  unreadNotificationCount: 0,
  searchOpen: false,
  searchQuery: '',

  // Actions
  toggleLogPanel: () => set((state) => ({ logPanelOpen: !state.logPanelOpen })),
  setLogPanelOpen: (open) => set({ logPanelOpen: open }),
  toggleRightToolbar: () => set((state) => ({ rightToolbarCollapsed: !state.rightToolbarCollapsed })),

  setProcessing: (isProcessing, message = '', progress = null) =>
    set({ isProcessing, processingMessage: message, processingProgress: progress }),

  setSystemResources: (resources) => set({ systemResources: resources }),
  setAppResources: (resources) => set({ appResources: resources }),

  addNotification: (notification) => set((state) => {
    const newNotification: Notification = {
      ...notification,
      id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date(),
      read: false,
    };
    return {
      notifications: [newNotification, ...state.notifications].slice(0, 50), // Keep last 50
      unreadNotificationCount: state.unreadNotificationCount + 1,
    };
  }),

  markNotificationRead: (id) => set((state) => {
    const notifications = state.notifications.map((n) =>
      n.id === id ? { ...n, read: true } : n
    );
    const unreadCount = notifications.filter((n) => !n.read).length;
    return { notifications, unreadNotificationCount: unreadCount };
  }),

  clearNotifications: () => set({ notifications: [], unreadNotificationCount: 0 }),

  setSearchOpen: (open) => set({ searchOpen: open }),
  setSearchQuery: (query) => set({ searchQuery: query }),
}));
