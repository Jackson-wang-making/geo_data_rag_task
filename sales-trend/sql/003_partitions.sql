-- Initial sample-data partitions. Future affected months are created by
-- app.refresh_maxi_dress_daily() via app.ensure_monthly_partition().

SELECT app.ensure_monthly_partition('2024-01-01'::date);
SELECT app.ensure_monthly_partition('2024-02-01'::date);
SELECT app.ensure_monthly_partition('2024-03-01'::date);