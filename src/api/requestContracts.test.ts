import { describe, expect, it } from 'vitest';
import type { GaussianRequest } from './statisticsApi';
import type { ConvertPiParams, IdentifyMissionParams } from './missionIoApi';
import type { EnergyRangesParams } from './miscApi';

describe('utility request type contracts', () => {
  it('encode exact-one source and input invariants', () => {
    const validRequests = [
      { probability: 0.1, sidedness: 'one-sided' } satisfies GaussianRequest,
      { log_probability: -10, sidedness: 'two-sided' } satisfies GaussianRequest,
      { event_list_name: 'events' } satisfies IdentifyMissionParams,
      { file_path: '/science/events.fits', file_grant: 'grant' } satisfies IdentifyMissionParams,
      { pi_values: [1, 2], mission_override: 'nicer' } satisfies ConvertPiParams,
      { event_list_name: 'events', save_as: 'derived' } satisfies ConvertPiParams,
      { n_ranges: 2, energies: [1, 2], energy_unit: 'keV' } satisfies EnergyRangesParams,
      { n_ranges: 2, event_list_name: 'events', energy_unit: 'keV' } satisfies EnergyRangesParams,
    ];

    // @ts-expect-error Gaussian requests require exactly one probability representation.
    const missingGaussianInput: GaussianRequest = { sidedness: 'one-sided' };
    // @ts-expect-error Gaussian requests cannot include both probability representations.
    const duplicateGaussianInput: GaussianRequest = {
      probability: 0.1,
      log_probability: -2,
      sidedness: 'one-sided',
    };
    // @ts-expect-error Mission identification accepts exactly one source.
    const duplicateIdentifySource: IdentifyMissionParams = {
      event_list_name: 'events',
      file_path: '/science/events.fits',
      file_grant: 'grant',
    };
    // @ts-expect-error Pasted PI conversion cannot save a derived EventList.
    const pastedSave: ConvertPiParams = { pi_values: [1], save_as: 'derived' };
    // @ts-expect-error Energy ranges accept exactly one energy source.
    const duplicateEnergySource: EnergyRangesParams = {
      n_ranges: 2,
      energies: [1, 2],
      event_list_name: 'events',
      energy_unit: 'keV',
    };

    expect(validRequests).toHaveLength(8);
    void [
      missingGaussianInput,
      duplicateGaussianInput,
      duplicateIdentifySource,
      pastedSave,
      duplicateEnergySource,
    ];
  });
});
