import type { ReactNode } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  Typography,
} from '@mui/material';
import CalculateOutlinedIcon from '@mui/icons-material/CalculateOutlined';
import {
  NumericResultTable,
  ProvenancePanel,
  type ResultCell,
  UtilityWarnings,
} from '@/components/utilities/UtilityResult';

interface WorkbenchTabPanelProps {
  active: number;
  index: number;
  children: ReactNode;
}

export function WorkbenchTabPanel({ active, index, children }: WorkbenchTabPanelProps) {
  return (
    <Box
      role="tabpanel"
      hidden={active !== index}
      id={`statistics-panel-${index}`}
      aria-labelledby={`statistics-tab-${index}`}
      sx={{ pt: 3 }}
    >
      {children}
    </Box>
  );
}

interface ResultFrameProps {
  title: string;
  running: boolean;
  error: string | null;
  requestWarnings?: string[];
  result: { warnings: string[]; provenance: Record<string, unknown> } | null;
  rows: Array<Record<string, ResultCell>>;
  chips?: ReactNode;
  emptyText: string;
}

export function ResultFrame({
  title,
  running,
  error,
  requestWarnings = [],
  result,
  rows,
  chips,
  emptyText,
}: ResultFrameProps) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Stack spacing={2} aria-live="polite">
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
              {title}
            </Typography>
            {chips}
            {running && <Chip size="small" color="primary" label="Calculating…" />}
          </Box>
          {error && (
            <Alert severity="error">
              {error}
              {result ? ' The previous successful result remains available below.' : ''}
            </Alert>
          )}
          <UtilityWarnings warnings={requestWarnings} />
          {result ? (
            <>
              <UtilityWarnings warnings={result.warnings} />
              <NumericResultTable
                title="Copyable result"
                columns={[
                  { key: 'quantity', label: 'Quantity' },
                  { key: 'value', label: 'Value' },
                  { key: 'unit', label: 'Unit / meaning' },
                ]}
                rows={rows}
                pageSize={10}
              />
              <ProvenancePanel provenance={result.provenance} />
            </>
          ) : (
            <Box sx={{ py: { xs: 5, md: 10 }, textAlign: 'center' }}>
              {running ? (
                <CircularProgress size={30} sx={{ mb: 2 }} />
              ) : (
                <CalculateOutlinedIcon sx={{ fontSize: 42, color: 'text.disabled', mb: 1 }} />
              )}
              <Typography color="text.secondary">
                {running ? 'Running the calculation…' : emptyText}
              </Typography>
            </Box>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

interface SubmitButtonProps {
  running: boolean;
  disabled: boolean;
  label: string;
}

export function SubmitButton({ running, disabled, label }: SubmitButtonProps) {
  return (
    <Button
      type="submit"
      variant="contained"
      disabled={disabled}
      startIcon={
        running ? <CircularProgress size={16} color="inherit" /> : <CalculateOutlinedIcon />
      }
    >
      {running ? 'Calculating…' : label}
    </Button>
  );
}
