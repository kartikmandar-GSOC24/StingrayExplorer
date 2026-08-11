import { create } from 'zustand';

/**
 * Log entry type
 */
export interface LogEntry {
  id: string;
  timestamp: Date;
  level: 'info' | 'warn' | 'error' | 'debug';
  source: 'python' | 'electron' | 'frontend';
  message: string;
}

/**
 * Log store state interface
 */
interface LogStoreState {
  logs: LogEntry[];
  maxLogs: number;
  isOpen: boolean;
  filter: {
    levels: Set<LogEntry['level']>;
    sources: Set<LogEntry['source']>;
    search: string;
  };
}

/**
 * Log store actions interface
 */
interface LogStoreActions {
  addLog: (log: Omit<LogEntry, 'id' | 'timestamp'>) => void;
  clearLogs: () => void;
  togglePanel: () => void;
  setOpen: (isOpen: boolean) => void;
  setFilter: (filter: Partial<LogStoreState['filter']>) => void;
  toggleLevelFilter: (level: LogEntry['level']) => void;
  toggleSourceFilter: (source: LogEntry['source']) => void;
  setSearchFilter: (search: string) => void;
}

type LogStore = LogStoreState & LogStoreActions;

/**
 * Generate unique ID for log entries
 */
const generateId = (): string => {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

/**
 * Zustand store for application logs
 */
export const useLogStore = create<LogStore>((set) => ({
  logs: [],
  maxLogs: 1000,
  isOpen: false,
  filter: {
    levels: new Set(['info', 'warn', 'error', 'debug']),
    sources: new Set(['python', 'electron', 'frontend']),
    search: '',
  },

  addLog: (log): void => {
    set((state) => {
      const newLog: LogEntry = {
        ...log,
        id: generateId(),
        timestamp: new Date(),
      };

      // Keep only the last maxLogs entries
      const logs = [...state.logs, newLog];
      if (logs.length > state.maxLogs) {
        logs.shift();
      }

      return { logs };
    });
  },

  clearLogs: (): void => {
    set({ logs: [] });
  },

  togglePanel: (): void => {
    set((state) => ({ isOpen: !state.isOpen }));
  },

  setOpen: (isOpen): void => {
    set({ isOpen });
  },

  setFilter: (filter): void => {
    set((state) => ({
      filter: { ...state.filter, ...filter },
    }));
  },

  toggleLevelFilter: (level): void => {
    set((state) => {
      const levels = new Set(state.filter.levels);
      if (levels.has(level)) {
        levels.delete(level);
      } else {
        levels.add(level);
      }
      return { filter: { ...state.filter, levels } };
    });
  },

  toggleSourceFilter: (source): void => {
    set((state) => {
      const sources = new Set(state.filter.sources);
      if (sources.has(source)) {
        sources.delete(source);
      } else {
        sources.add(source);
      }
      return { filter: { ...state.filter, sources } };
    });
  },

  setSearchFilter: (search): void => {
    set((state) => ({
      filter: { ...state.filter, search },
    }));
  },
}));

/**
 * Selector for filtered logs
 */
export const selectFilteredLogs = (state: LogStore): LogEntry[] => {
  return state.logs.filter((log) => {
    // Filter by level
    if (!state.filter.levels.has(log.level)) {
      return false;
    }

    // Filter by source
    if (!state.filter.sources.has(log.source)) {
      return false;
    }

    // Filter by search text
    if (state.filter.search) {
      const searchLower = state.filter.search.toLowerCase();
      return log.message.toLowerCase().includes(searchLower);
    }

    return true;
  });
};

/**
 * Helper function to add logs from outside React components
 */
export const addLog = (log: Omit<LogEntry, 'id' | 'timestamp'>): void => {
  useLogStore.getState().addLog(log);
};
