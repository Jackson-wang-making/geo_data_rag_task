-- Convert raw input into the standard layer. The unique constraint and
-- ON CONFLICT clause make this statement safe to execute repeatedly.

WITH base AS (
    SELECT DISTINCT
        product_id,
        title,
        sales_count,
        "timestamp",
        user_id,
        lower(trim(category)) AS category,
        lower(trim(source)) AS source
    FROM raw.sales_data
),
normalized AS (
    SELECT
        product_id,
        title,
        sales_count,
        "timestamp" AT TIME ZONE 'Asia/Shanghai' AS occurred_at,
        user_id,
        category,
        source,
        std.normalize_title(title) AS title_norm
    FROM base
)
INSERT INTO std.sales_clean (
    product_id,
    title,
    sales_count,
    "timestamp",
    user_id,
    category,
    source,
    title_norm,
    business_date,
    is_maxi_dress
)
SELECT
    product_id,
    title,
    sales_count,
    occurred_at,
    user_id,
    category,
    source,
    title_norm,
    (occurred_at AT TIME ZONE 'Asia/Shanghai')::date AS business_date,
    std.is_explicit_maxi_dress(title, category) AS is_maxi_dress
FROM normalized
WHERE sales_count >= 0
  AND product_id IS NOT NULL
  AND title IS NOT NULL
  AND trim(title) <> ''
  AND title_norm <> ''
  AND occurred_at IS NOT NULL
  AND category IS NOT NULL
  AND category <> ''
  AND source IN ('website', 'app', 'marketplace')
ON CONFLICT ON CONSTRAINT uq_sales_clean_source DO NOTHING;