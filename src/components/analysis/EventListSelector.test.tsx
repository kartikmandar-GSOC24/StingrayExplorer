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

const DualHarness: React.FC = () => {
  const [value1, setValue1] = useState('');
  const [value2, setValue2] = useState('');
  return (
    <>
      <EventListSelector label="Event list 1" value={value1} onChange={setValue1} />
      <EventListSelector label="Event list 2" value={value2} onChange={setValue2} />
    </>
  );
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

  it('shares one query across two instances and selections stay independent', async () => {
    listEventLists.mockResolvedValue({
      success: true,
      data: [
        { name: 'obs1', n_events: 1000, time_range: [0, 10] },
        { name: 'obs2', n_events: 2000, time_range: [0, 20] },
      ],
      message: '',
      error: null,
    });
    renderWithProviders(<DualHarness />);
    await screen.findByLabelText('Event list 1');
    const select2 = await screen.findByLabelText('Event list 2');
    expect(listEventLists).toHaveBeenCalledTimes(1);
    await userEvent.click(select2);
    await userEvent.click(await screen.findByText(/obs1/));
    await waitFor(() => expect(screen.getByLabelText('Event list 2')).toHaveTextContent('obs1'));
    expect(screen.getByLabelText('Event list 1')).not.toHaveTextContent('obs1');
  });

  it('refreshes from empty to populated via the refresh button', async () => {
    listEventLists.mockResolvedValueOnce({ success: true, data: [], message: '', error: null });
    renderWithProviders(<Harness />);
    expect(await screen.findByText(/No event lists loaded/)).toBeInTheDocument();
    listEventLists.mockResolvedValue({
      success: true,
      data: [{ name: 'obs1', n_events: 1000, time_range: [0, 10] }],
      message: '',
      error: null,
    });
    await userEvent.click(screen.getByRole('button', { name: 'Refresh event lists' }));
    const select = await screen.findByLabelText('Event list');
    await userEvent.click(select);
    expect(await screen.findByText(/obs1/)).toBeInTheDocument();
  });

  it('shows an error alert with a refresh affordance when listing fails', async () => {
    listEventLists.mockResolvedValue({ success: false, data: null, message: 'boom', error: 'boom' });
    renderWithProviders(<Harness />);
    expect(await screen.findByText(/Failed to load event lists/)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh event lists' })).toBeInTheDocument();
  });

  it('disables EventLists that lack a required scientific data capability', async () => {
    listEventLists.mockResolvedValue({
      success: true,
      data: [
        { name: 'with-pi', n_events: 10, time_range: [0, 1], has_pi: true },
        { name: 'without-pi', n_events: 10, time_range: [0, 1], has_pi: false },
      ],
      message: '',
      error: null,
    });
    renderWithProviders(
      <EventListSelector
        label="PI EventList"
        value=""
        onChange={() => undefined}
        requiredCapability="pi"
      />
    );

    await userEvent.click(await screen.findByLabelText('PI EventList'));
    expect(screen.getByRole('option', { name: /without-pi.*no PI\/channel data/ })).toHaveAttribute(
      'aria-disabled',
      'true'
    );
    expect(screen.getByRole('option', { name: /with-pi/ })).not.toHaveAttribute(
      'aria-disabled',
      'true'
    );
  });
});
