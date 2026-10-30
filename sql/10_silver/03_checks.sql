-- Silver checks that must hold for the stage to commit (spec 01 S10). A failed check raises
-- an error, which rolls back the whole stage: silver is never left half-built.

-- S10: silver keeps every bronze row. count(silver_sales) = count(bronze).
with silver as (
    select count(*) as n from silver_sales
),

bronze as (
    select count(*) as n from read_parquet($bronze_file)
)

select
    case
        when silver.n <> bronze.n
            then error(
                'silver row count ' || silver.n::varchar
                || ' does not match bronze row count ' || bronze.n::varchar
            )
    end as row_count_check
from silver
cross join bronze;
