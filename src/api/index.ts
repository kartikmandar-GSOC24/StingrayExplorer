/**
 * API module exports
 */

export { apiClient, type ApiResponse } from './client';
export { dataApi, type EventListSummary, type EventListInfo, type FileSizeInfo } from './dataApi';
export { lightcurveApi, type LightcurveData, type LightcurveSummary } from './lightcurveApi';
export {
  spectrumApi,
  type PowerSpectrumData,
  type DynamicalPowerSpectrumData,
  type SpectrumSummary,
} from './spectrumApi';
export {
  timingApi,
  type BispectrumData,
  type PowerColorsData,
  type TimeLagsData,
  type CoherenceData,
} from './timingApi';
export { correlationApi, type CorrelationData } from './correlationApi';
export {
  varenergyApi,
  type RmsSpectrumData,
  type LagSpectrumData,
  type ExcessVarianceData,
  type VarEnergyBand,
  type VariableEnergySpectrumData,
  type CovarianceSpectrumData,
} from './varenergyApi';
export { deadtimeApi, type PdsCorrectionData, type FadCorrectionData } from './deadtimeApi';
export { statisticsApi } from './statisticsApi';
export { gtiApi } from './gtiApi';
export {
  ioApi,
  type ExportableObjectType,
  type UtilityExportFormat,
  type ExportResult as UtilityIoExportResult,
} from './ioApi';
export { missionIoApi } from './missionIoApi';
export { miscApi } from './miscApi';
