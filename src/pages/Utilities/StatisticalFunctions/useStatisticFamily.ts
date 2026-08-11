import { useState, type FormEvent } from 'react';
import type { StatisticDetectionResult, StatisticEvaluationResult } from '@/api/statisticsApi';
import { statisticsApi } from '@/api/statisticsApi';
import { useAnalysisRunner } from '@/hooks/useAnalysisRunner';
import type { FamilyConfig } from './familyConfigs';
import { count, finiteNumber, probability } from './validation';

export type FamilyOperation = 'evaluate' | 'detection';

export function useStatisticFamily(config: FamilyConfig) {
  const [operation, setOperation] = useState<FamilyOperation>('evaluate');
  const [rawStatistic, setRawStatistic] = useState(config.statisticDefault);
  const [rawFalseAlarm, setRawFalseAlarm] = useState('0.01');
  const [rawTrials, setRawTrials] = useState('1');
  const [rawSummed, setRawSummed] = useState('1');
  const [rawRebin, setRawRebin] = useState('1');
  const [rawHarmonics, setRawHarmonics] = useState('2');
  const [rawPhaseBins, setRawPhaseBins] = useState(config.key === 'pdm' ? '10' : '16');
  const [rawSamples, setRawSamples] = useState('100');
  const evaluation = useAnalysisRunner<StatisticEvaluationResult>(`${config.title} Evaluation`);
  const detection = useAnalysisRunner<StatisticDetectionResult>(
    `${config.title} Detection Level`
  );

  const parsedStatistic = finiteNumber(rawStatistic, config.statisticLabel);
  const statisticError =
    parsedStatistic.error ??
    (parsedStatistic.value !== null && parsedStatistic.value < 0
      ? `${config.statisticLabel} must be at least 0`
      : config.key === 'pdm' && parsedStatistic.value !== null && parsedStatistic.value > 1
        ? 'PDM statistic must be at most 1'
        : null);
  const validStatistic = statisticError === null ? parsedStatistic.value : null;
  const falseAlarm = probability(rawFalseAlarm, 'Overall false-alarm probability');
  const trials = count(rawTrials, 'Independent trials');
  const summed = count(
    rawSummed,
    config.key === 'z2' ? 'Averaged periodograms' : 'Averaged spectra'
  );
  const rebin = count(rawRebin, 'Rebin factor');
  const harmonics = count(rawHarmonics, 'Harmonics');
  const phaseBins = count(rawPhaseBins, 'Phase bins', config.minimumPhaseBins ?? 1);
  const samples = count(rawSamples, 'Time-series samples', 3);
  const sampleRelationError =
    config.hasSamples &&
    samples.value !== null &&
    phaseBins.value !== null &&
    samples.value <= phaseBins.value
      ? 'Time-series samples must be greater than phase bins'
      : null;

  const commonValid =
    trials.value !== null &&
    (!config.hasSummedSpectra || summed.value !== null) &&
    (!config.hasRebin || rebin.value !== null) &&
    (!config.hasHarmonics || harmonics.value !== null) &&
    (!config.hasPhaseBins || phaseBins.value !== null) &&
    (!config.hasSamples || (samples.value !== null && sampleRelationError === null));
  const activeRunner = operation === 'evaluate' ? evaluation : detection;
  const canSubmit =
    commonValid &&
    (operation === 'evaluate' ? validStatistic !== null : falseAlarm.value !== null) &&
    !activeRunner.running;

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    if (!canSubmit || trials.value === null) return;

    if (operation === 'evaluate' && validStatistic !== null) {
      switch (config.key) {
        case 'pds':
          if (summed.value === null || rebin.value === null) return;
          void evaluation.run(() =>
            statisticsApi.evaluatePds({
              power: validStatistic,
              n_trials: trials.value as number,
              n_summed_spectra: summed.value as number,
              n_rebin: rebin.value as number,
            })
          );
          return;
        case 'z2':
          if (harmonics.value === null || summed.value === null) return;
          void evaluation.run(() =>
            statisticsApi.evaluateZ2({
              z2: validStatistic,
              harmonics: harmonics.value as number,
              n_trials: trials.value as number,
              n_summed_spectra: summed.value as number,
            })
          );
          return;
        case 'fold':
          if (phaseBins.value === null) return;
          void evaluation.run(() =>
            statisticsApi.evaluateFold({
              statistic: validStatistic,
              n_phase_bins: phaseBins.value as number,
              n_trials: trials.value as number,
            })
          );
          return;
        case 'pdm':
          if (samples.value === null || phaseBins.value === null) return;
          void evaluation.run(() =>
            statisticsApi.evaluatePdm({
              statistic: validStatistic,
              n_samples: samples.value as number,
              n_phase_bins: phaseBins.value as number,
              n_trials: trials.value as number,
            })
          );
          return;
      }
    }

    if (operation === 'detection' && falseAlarm.value !== null) {
      switch (config.key) {
        case 'pds':
          if (summed.value === null || rebin.value === null) return;
          void detection.run(() =>
            statisticsApi.detectPds({
              false_alarm_probability: falseAlarm.value as number,
              n_trials: trials.value as number,
              n_summed_spectra: summed.value as number,
              n_rebin: rebin.value as number,
            })
          );
          return;
        case 'z2':
          if (harmonics.value === null || summed.value === null) return;
          void detection.run(() =>
            statisticsApi.detectZ2({
              false_alarm_probability: falseAlarm.value as number,
              harmonics: harmonics.value as number,
              n_trials: trials.value as number,
              n_summed_spectra: summed.value as number,
            })
          );
          return;
        case 'fold':
          if (phaseBins.value === null) return;
          void detection.run(() =>
            statisticsApi.detectFold({
              false_alarm_probability: falseAlarm.value as number,
              n_phase_bins: phaseBins.value as number,
              n_trials: trials.value as number,
            })
          );
          return;
        case 'pdm':
          if (samples.value === null || phaseBins.value === null) return;
          void detection.run(() =>
            statisticsApi.detectPdm({
              false_alarm_probability: falseAlarm.value as number,
              n_samples: samples.value as number,
              n_phase_bins: phaseBins.value as number,
              n_trials: trials.value as number,
            })
          );
          return;
      }
    }
  };

  const evaluationRows = evaluation.result
    ? [
        {
          quantity: 'Observed statistic',
          value: evaluation.result.observed_statistic,
          unit: evaluation.result.units.observed_statistic ?? config.resultUnit,
        },
        {
          quantity: 'Overall false-alarm probability',
          value: evaluation.result.probability,
          unit: evaluation.result.units.probability ?? 'post-trial, dimensionless',
        },
        {
          quantity: 'ln(overall false-alarm probability)',
          value: evaluation.result.log_probability,
          unit: evaluation.result.units.log_probability ?? 'natural logarithm',
        },
      ]
    : [];
  const detectionRows = detection.result
    ? [
        {
          quantity: 'Desired overall false-alarm probability',
          value: detection.result.false_alarm_probability,
          unit:
            detection.result.units.false_alarm_probability ?? 'post-trial, dimensionless',
        },
        {
          quantity: 'Detection level',
          value: detection.result.detection_level,
          unit: detection.result.units.detection_level ?? config.resultUnit,
        },
        {
          quantity: 'Detection decision rule',
          value: detection.result.decision_rule,
          unit: detection.result.tail === 'lower' ? 'lower tail' : 'upper tail',
        },
      ]
    : [];

  return {
    operation,
    setOperation,
    rawStatistic,
    setRawStatistic,
    rawFalseAlarm,
    setRawFalseAlarm,
    rawTrials,
    setRawTrials,
    rawSummed,
    setRawSummed,
    rawRebin,
    setRawRebin,
    rawHarmonics,
    setRawHarmonics,
    rawPhaseBins,
    setRawPhaseBins,
    rawSamples,
    setRawSamples,
    statisticError,
    falseAlarm,
    trials,
    summed,
    rebin,
    harmonics,
    phaseBins,
    samples,
    sampleRelationError,
    activeRunner,
    canSubmit,
    submit,
    activeResult: operation === 'evaluate' ? evaluation.result : detection.result,
    activeRows: operation === 'evaluate' ? evaluationRows : detectionRows,
  };
}

export type StatisticFamilyModel = ReturnType<typeof useStatisticFamily>;
