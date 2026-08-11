import React from 'react';
import {
  Alert,
  Box,
  Button,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Typography,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';

export interface ResultColumn {
  key: string;
  label: string;
  unit?: string;
}

export type ResultCell = number | string | boolean | null | undefined;

function formatCell(value: ResultCell): string {
  if (value == null) return 'null';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return 'null';
    // Number#toString returns the shortest decimal representation that
    // round-trips to the exact IEEE-754 value. Fixed significant-digit or
    // exponential formatting would silently discard meaningful precision in
    // both the rendered table and copied TSV output.
    return Object.is(value, -0) ? '-0' : value.toString();
  }
  return String(value);
}

function formatColumnHeader(column: ResultColumn): string {
  return `${column.label}${column.unit ? ` (${column.unit})` : ''}`;
}

export const UtilityWarnings: React.FC<{ warnings?: string[] }> = ({ warnings = [] }) =>
  warnings.length > 0 ? (
    <Alert severity="warning">
      <Stack spacing={0.5}>
        {warnings.map((warning, index) => (
          <Typography key={`${warning}-${index}`} variant="body2">
            {warning}
          </Typography>
        ))}
      </Stack>
    </Alert>
  ) : null;

export const ProvenancePanel: React.FC<{ provenance?: Record<string, unknown> }> = ({ provenance }) =>
  provenance ? (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Typography variant="overline" color="text.secondary">
        Provenance
      </Typography>
      <Box
        component="pre"
        sx={{ m: 0, mt: 0.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: '0.72rem' }}
      >
        {JSON.stringify(provenance, null, 2)}
      </Box>
    </Paper>
  ) : null;

interface NumericResultTableProps {
  title?: string;
  columns: ResultColumn[];
  rows: Array<Record<string, ResultCell>>;
  pageSize?: number;
}

/** Paginated exact-value table shared by all Utility workbenches. */
export const NumericResultTable: React.FC<NumericResultTableProps> = ({
  title,
  columns,
  rows,
  pageSize = 25,
}) => {
  const [page, setPage] = React.useState(0);
  const [rowsPerPage, setRowsPerPage] = React.useState(pageSize);
  React.useEffect(() => setPage(0), [rows]);
  const visible = rows.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);
  const copy = (): void => {
    const header = columns.map(formatColumnHeader).join('\t');
    const body = rows
      .map((row) => columns.map((column) => formatCell(row[column.key])).join('\t'))
      .join('\n');
    const text = `${header}\n${body}`;
    if (window.electronAPI?.copyToClipboard) window.electronAPI.copyToClipboard(text);
    else void navigator.clipboard?.writeText(text);
  };

  return (
    <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
      <Box sx={{ px: 2, py: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="subtitle2">{title ?? 'Exact results'}</Typography>
        <Button size="small" startIcon={<ContentCopyIcon />} onClick={copy} disabled={rows.length === 0}>
          Copy
        </Button>
      </Box>
      <TableContainer sx={{ maxHeight: 420 }}>
        <Table size="small" stickyHeader aria-label={title ?? 'Exact results'}>
          <TableHead>
            <TableRow>
              {columns.map((column) => (
                <TableCell key={column.key}>
                  {formatColumnHeader(column)}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {visible.map((row, rowIndex) => (
              <TableRow key={page * rowsPerPage + rowIndex}>
                {columns.map((column) => (
                  <TableCell key={column.key} sx={{ fontFamily: '"IBM Plex Mono", monospace' }}>
                    {formatCell(row[column.key])}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <TablePagination
        component="div"
        count={rows.length}
        page={Math.min(page, Math.max(0, Math.ceil(rows.length / rowsPerPage) - 1))}
        onPageChange={(_event, next) => setPage(next)}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={(event) => {
          setRowsPerPage(Number(event.target.value));
          setPage(0);
        }}
        rowsPerPageOptions={[10, 25, 50, 100]}
      />
    </Paper>
  );
};
