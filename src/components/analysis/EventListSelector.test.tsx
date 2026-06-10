import React, { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/testUtils';

const listEventLists = vi.fn();
vi.mock('@/api/dataApi', () => ({
  dataApi: { listEventLists: (...args: unknown[]) => listEventLists(...args) },
}));

import EventListSelector from './EventListSelector';

const Harness: React.FC = () => {
  const [value, setValue] = useState('');
  return <EventListSelector label="Event list" value={value} onChange={setValue} />;
};

describe('EventListSelector', () => {
  beforeEach(() => listEventLists.mockReset());

  it('lists loaded event lists and selects one', async () => {
    listEventLists.mockResolvedValue({
      success: true,
      data: [
        { name: 'obs1', n_events: 1000, time_range: [0, 10] },
        { name: 'obs2', n_events: 2000, time_range: [0, 20] },
      ],
      message: '',
      error: null,
    });
    renderWithProviders(<Harness />);
    const select = await screen.findByLabelText('Event list');
    await userEvent.click(select);
    await userEvent.click(await screen.findByText(/obs2/));
    await waitFor(() => expect(screen.getByLabelText('Event list')).toHaveTextContent('obs2'));
  });

  it('shows an empty-state prompt linking to data ingestion', async () => {
    listEventLists.mockResolvedValue({ success: true, data: [], message: '', error: null });
    renderWithProviders(<Harness />);
    expect(await screen.findByText(/No event lists loaded/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Load data/ })).toHaveAttribute(
      'href',
      '/data-ingestion'
    );
  });
});
