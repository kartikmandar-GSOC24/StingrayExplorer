import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import GrantedFileField, { GrantedFileSelection } from './GrantedFileField';

describe('GrantedFileField', () => {
  const originalElectronApi = window.electronAPI;

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: originalElectronApi,
    });
  });

  it('returns a native-dialog selection and never exposes a typed path', async () => {
    const selected = { path: '/data/response.rmf', grant: 'token' };
    const openGrantedFile = vi.fn().mockResolvedValue([selected]);
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { openGrantedFile },
    });
    const onChange = vi.fn();
    render(<GrantedFileField label="RMF file" value={null} onChange={onChange} />);
    expect(screen.getByLabelText('RMF file')).toHaveAttribute('readonly');
    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(onChange).toHaveBeenCalledWith(selected);
  });

  it('preserves the current explicit selection when the dialog is cancelled', async () => {
    const current: GrantedFileSelection = { path: '/data/current.fits', grant: 'old' };
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { openGrantedFile: vi.fn().mockResolvedValue(null) },
    });
    const onChange = vi.fn();
    render(<GrantedFileField label="FITS file" value={current} onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText('FITS file')).toHaveValue('/data/current.fits');
  });

  it('shows native dialog failures without replacing the current selection', async () => {
    const current: GrantedFileSelection = { path: '/data/current.fits', grant: 'old' };
    Object.defineProperty(window, 'electronAPI', {
      configurable: true,
      value: { openGrantedFile: vi.fn().mockRejectedValue(new Error('dialog process failed')) },
    });
    const onChange = vi.fn();
    render(<GrantedFileField label="FITS file" value={current} onChange={onChange} />);

    await userEvent.click(screen.getByRole('button', { name: 'Choose' }));

    expect(await screen.findByText(/dialog process failed/)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText('FITS file')).toHaveValue('/data/current.fits');
  });
});
