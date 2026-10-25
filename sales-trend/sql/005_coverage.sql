-- Precomputed raw-source coverage so GET /v1/sales/trends never scans
-- raw.sales_data on the hot path. Idempotent; the ETL refreshes it.

CREATE TABLE IF NOT EXISTS app.coverage_meta (
    scope      text PRIMARY KEY,
    min_date   date,
    max_date   date,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION app.refresh_coverage()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO app.coverage_meta (scope, min_date, max_date, updated_at)
    SELECT
        'raw_source',
        MIN(("timestamp" AT TIME ZONE 'Asia/Shanghai')::date),
        MAX(("timestamp" AT TIME ZONE 'Asia/Shanghai')::date),
        now()
    FROM raw.sales_data
    ON CONFLICT (scope) DO UPDATE SET
        min_date   = EXCLUDED.min_date,
        max_date   = EXCLUDED.max_date,
        updated_at = EXCLUDED.updated_at;
END;
$$;
