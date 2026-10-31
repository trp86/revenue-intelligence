-- Reconciliation results (spec 01 section 6). Rebuilt in full on every run: a run replaces
-- the previous results, it never appends to them. Only counts, sums and dates are stored,
-- never a row.
--
-- status: pass or fail for R1 to R3, info for R4 (informational).
-- expected / actual / difference: difference = actual - expected, in the unit of the check
--   (rows, or an amount). tolerance: the allowed absolute difference, 0 for row counts.
create or replace table recon_results (
    check_id varchar,
    subject varchar,
    description varchar,
    status varchar,
    expected decimal(38, 4),
    actual decimal(38, 4),
    difference decimal(38, 4),
    tolerance double,
    detail varchar,
    checked_at timestamp
);
