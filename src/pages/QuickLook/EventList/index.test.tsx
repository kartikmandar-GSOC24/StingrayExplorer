import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';

const listEventLists = vi.fn();
const getEventListInfo = vi.fn();
const getEventListFullPreview = vi.fn();
const deleteEventList = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: {
    listEventLists: (...a: unknown[]) => listEventLists(...a),
    getEventListInfo: (...a: unknown[]) => getEventListInfo(...a),
    getEventListFullPreview: (...a: unknown[]) => getEventListFullPreview(...a),
    deleteEventList: (...a: unknown[]) => deleteEventList(...a),
  },
}));
vi.mock('@/components/plots/PlotlyChart', () => ({
  default: () => <div data-testid="chart" />,
}));

import EventListPage from './index';

describe('EventListPage', () => {
  beforeEach(() => {
    listEventLists.mockReset();
    getEventListInfo.mockReset();
    deleteEventList.mockReset();
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 5000, time_range: [0, 100] }],
      message: '',
      error: null,
    });
    getEventListInfo.mockResolvedValue({
      success: true,
      data: {
        name: 'obs1',
        n_events: 5000,
        time_range: [0, 100],
        duration: 100,
        mjdref: 56000,
        gti_count: 2,
        gti_list: [
          [0, 40],
          [60, 100],
        ],
        mean_count_rate: 50,
      },
      message: '',
      error: null,
    });
  });

  it('lists event lists and shows details when one is selected', async () => {
    renderWithProviders(<EventListPage />);
    await userEvent.click(await screen.findByText(/obs1/));
    expect(await screen.findByText('Duration (s)')).toBeInTheDocument();
    expect(getEventListInfo).toHaveBeenCalledWith('obs1');
    // GTI table rows
    expect(await screen.findByText('Good Time Intervals')).toBeInTheDocument();
  });

  it('deletes an event list via the confirmation dialog', async () => {
    deleteEventList.mockResolvedValue({
      success: true,
      data: { name: 'obs1' },
      message: '',
      error: null,
    });
    renderWithProviders(<EventListPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete obs1' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(deleteEventList).toHaveBeenCalledWith('obs1');
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });
});
