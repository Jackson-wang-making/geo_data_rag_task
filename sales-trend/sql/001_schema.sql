-- PostgreSQL 16 schema for the raw -> standard -> application data flow.
-- This file is safe to execute repeatedly after the initial deployment.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS std;
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS raw.sales_data (
    product_id  bigint,
    title       text,
    sales_count integer,
    "timestamp" timestamp,
    user_id     text,
    category    text,
    source      text
);

-- The raw table intentionally has no surrogate key or unique constraint. Exact
-- duplicate rows are part of the source and are de-duplicated in std.
CREATE TABLE IF NOT EXISTS std.sales_clean (
    product_id     bigint      NOT NULL,
    title          text        NOT NULL,
    sales_count    integer     NOT NULL CHECK (sales_count >= 0),
    "timestamp"    timestamptz NOT NULL,
    user_id        text,
    category       text        NOT NULL,
    source         text        NOT NULL,
    title_norm     text        NOT NULL CHECK (title_norm <> ''),
    business_date  date        NOT NULL,
    is_maxi_dress  boolean     NOT NULL DEFAULT false,

    CONSTRAINT uq_sales_clean_source UNIQUE NULLS NOT DISTINCT (
        product_id, title, sales_count, "timestamp",
        user_id, category, source
    )
);

CREATE INDEX IF NOT EXISTS ix_sales_clean_date_source
    ON std.sales_clean (business_date, source);

CREATE INDEX IF NOT EXISTS ix_sales_clean_maxi
    ON std.sales_clean (business_date, source, product_id)
    WHERE is_maxi_dress;

CREATE TABLE IF NOT EXISTS app.maxi_dress_daily (
    stat_date   date   NOT NULL,
    source      text   NOT NULL,
    product_id  bigint NOT NULL,
    title       text   NOT NULL,
    sales_count bigint NOT NULL CHECK (sales_count >= 0),
    PRIMARY KEY (stat_date, source, product_id, title)
) PARTITION BY RANGE (stat_date);