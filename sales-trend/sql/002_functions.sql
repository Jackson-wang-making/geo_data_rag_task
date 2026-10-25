-- Shared normalization/classification functions and partition/refresh helpers.

CREATE OR REPLACE FUNCTION std.normalize_text(input text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT trim(
        regexp_replace(
            regexp_replace(
                lower(replace(coalesce(input, ''), '''', '')),
                '[^a-z0-9]+', ' ', 'g'
            ),
            '\s+', ' ', 'g'
        )
    );
$$;

CREATE OR REPLACE FUNCTION std.normalize_title(input text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT array_to_string(
        ARRAY(
            SELECT token
            FROM regexp_split_to_table(std.normalize_text(input), '\s+') AS token
            WHERE token <> ''
            ORDER BY token
        ),
        ' '
    );
$$;

CREATE OR REPLACE FUNCTION std.is_explicit_maxi_dress(
    p_title text,
    p_category text
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT lower(trim(coalesce(p_category, ''))) = 'dress'
       AND std.normalize_text(p_title) ~ '(^| )maxi( |$)'
       AND std.normalize_text(p_title) ~ '(^| )dress( |$)';
$$;

CREATE OR REPLACE FUNCTION app.ensure_monthly_partition(p_month date)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_start date := date_trunc('month', p_month)::date;
    v_end   date := (date_trunc('month', p_month) + interval '1 month')::date;
    v_name  text := format('maxi_dress_daily_%s', to_char(v_start, 'YYYY_MM'));
BEGIN
    IF p_month IS NULL THEN
        RAISE EXCEPTION 'partition month must not be null';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(v_name, 0));

    IF to_regclass(format('app.%I', v_name)) IS NULL THEN
        EXECUTE format(
            'CREATE TABLE app.%I PARTITION OF app.maxi_dress_daily '
            'FOR VALUES FROM (%L) TO (%L)',
            v_name,
            v_start,
            v_end
        );
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION app.refresh_maxi_dress_daily(
    p_start_date date,
    p_end_date date
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_month date;
    v_rows  bigint;
BEGIN
    IF p_start_date IS NULL OR p_end_date IS NULL THEN
        RAISE EXCEPTION 'refresh date range must not be null';
    END IF;
    IF p_start_date > p_end_date THEN
        RAISE EXCEPTION 'refresh start date % is after end date %',
            p_start_date, p_end_date;
    END IF;

    -- Serialize refreshes; DELETE + INSERT must be atomic for overlapping ranges.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('app.maxi_dress_daily.refresh', 0)
    );

    v_month := date_trunc('month', p_start_date)::date;
    WHILE v_month <= p_end_date LOOP
        PERFORM app.ensure_monthly_partition(v_month);
        v_month := (v_month + interval '1 month')::date;
    END LOOP;

    DELETE FROM app.maxi_dress_daily
    WHERE stat_date BETWEEN p_start_date AND p_end_date;

    INSERT INTO app.maxi_dress_daily (
        stat_date,
        source,
        product_id,
        title,
        sales_count
    )
    SELECT
        business_date AS stat_date,
        source,
        product_id,
        title_norm AS title,
        sum(sales_count)::bigint AS sales_count
    FROM std.sales_clean
    WHERE is_maxi_dress = true
      AND business_date BETWEEN p_start_date AND p_end_date
    GROUP BY business_date, source, product_id, title_norm
    ON CONFLICT (stat_date, source, product_id, title)
    DO UPDATE SET sales_count = EXCLUDED.sales_count;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;