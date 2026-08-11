import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BackendStatusProvider, useBackendContext } from './BackendContext';
import type { BackendStatusSource } from '@/types/backendStatus';

const StatusConsumer: React.FC = () => {
  const { isReady } = useBackendContext();
  return <span>{isReady ? 'Backend Ready' : 'Starting...'}</span>;
};

describe('BackendStatusProvider', () => {
  it('reconciles its consumer to Backend Ready', async () => {
    const source: BackendStatusSource = {
      getBackendStatus: async () => ({
        revision: 6,
        phase: 'ready',
        port: 50017,
        error: null,
      }),
      onBackendStatus: () => () => undefined,
    };

    render(
      <BackendStatusProvider source={source}>
        <StatusConsumer />
      </BackendStatusProvider>
    );

    expect(await screen.findByText('Backend Ready')).toBeInTheDocument();
  });
});
