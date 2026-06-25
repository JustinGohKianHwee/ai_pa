export interface StatementImportSummary {
  id: string;
  source_label: string | null;
  row_count: number;
  matched_count: number;
  imported_count: number;
  created_at: string;
}

export interface StatementImportsResponse {
  items: StatementImportSummary[];
  total: number;
}

export interface StatementImportResult {
  import_id: string;
  row_count: number;
  matched_count: number;
  imported_count: number;
}
