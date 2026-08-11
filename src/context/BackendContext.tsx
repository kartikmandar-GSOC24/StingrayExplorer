import React, { createContext, useContext } from 'react';
import { useBackendStatus, type BackendState } from '@/hooks/useBackendStatus';
import type { BackendStatusSource } from '@/types/backendStatus';

export const BackendContext = createContext<BackendState>({
  port: null,
  isReady: false,
  error: null,
});

export const useBackendContext = (): BackendState => useContext(BackendContext);

interface BackendStatusProviderProps {
  children: React.ReactNode;
  source?: BackendStatusSource;
}

export const BackendStatusProvider: React.FC<BackendStatusProviderProps> = ({
  children,
  source,
}) => {
  const backendState = useBackendStatus(source);
  return <BackendContext.Provider value={backendState}>{children}</BackendContext.Provider>;
};
