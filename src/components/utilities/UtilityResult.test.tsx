import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NumericResultTable } from './UtilityResult';

describe('NumericResultTable', () => {
  const originalElectronApi = window.electronAPI;

  afterEach(() => {
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: originalElectronApi,
    });
  });

  it('renders and copies round-trippable numeric values without artificial truncation', async () => {
    const copyToClipboard = vi.fn();
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { copyToClipboard },
    });
    render(
      <NumericResultTable
        title="Precision check"
        columns={[{ key: 'value', label: 'Value', unit: 'keV' }]}
        rows={[
          { value: 0.12345678901234568 },
          { value: 1e-10 },
          { value: -0 },
        ]}
      />
    );

    expect(screen.getByText('0.12345678901234568')).toBeInTheDocument();
    expect(screen.getByText('1e-10')).toBeInTheDocument();
    expect(screen.getByText('-0')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(copyToClipboard).toHaveBeenCalledWith(
      'Value (keV)\n0.12345678901234568\n1e-10\n-0'
    );
  });
});
