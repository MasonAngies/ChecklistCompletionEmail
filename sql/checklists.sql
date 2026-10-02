-- ─────────────────────────────────────────────────────────────────────────────
-- Checklist completion — what each store had actually done, as of the morning
--
-- The point of these tables is that KINTONE MUTATES. A store can open last
-- Tuesday's closing checklist today and tick the boxes, and from then on Kintone
-- says Tuesday was complete. Re-querying a past date therefore cannot tell you
-- what the DMs were shown that morning. These tables are the record that can.
--
-- Ownership: this repo (ChecklistCompletionEmail) owns `checklist_*` and NOTHING
-- else. It reads nothing else either — `stores` belongs to the punch report, and
-- store_number here is a SOFT key to it on purpose: no foreign key, because a
-- store that is in the Kintone directory but not yet in `stores` must never be
-- able to fail the morning write.
--
-- Grain, and why re-runs UPDATE rather than append (the opposite of
-- dc_picksheet_run): a pick sheet re-send is a new event worth keeping, but a
-- checklist re-run is the same question asked again. One row per
-- (business_date, store, checklist) keeps "did 11104 close on the 29th"
-- answerable with a single row rather than a newest-row-wins query. The run
-- table below holds the per-run history.
--
-- Applied by scripts/init_db.py:
--   ./.venv/bin/python scripts/init_db.py
-- ─────────────────────────────────────────────────────────────────────────────


-- One row per execution, including backfills and dry runs. This is the audit
-- trail: which mornings actually ran, what they found, and who was told.
CREATE TABLE IF NOT EXISTS checklist_run (
    id              BIGSERIAL PRIMARY KEY,
    business_date   DATE NOT NULL,              -- the day being graded
    ran_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL,              -- sent | built | send_failed
    dry_run         BOOLEAN NOT NULL DEFAULT FALSE,
    backfill        BOOLEAN NOT NULL DEFAULT FALSE,
    store_count     INTEGER NOT NULL DEFAULT 0,
    completed       INTEGER NOT NULL DEFAULT 0, -- gradeable checklists done
    gradeable       INTEGER NOT NULL DEFAULT 0, -- out of this many
    stores_perfect  INTEGER NOT NULL DEFAULT 0,
    unmatched       INTEGER NOT NULL DEFAULT 0, -- submissions with no store
    recipients      TEXT,                       -- comma-separated, as sent
    cc              TEXT,
    problems        TEXT                        -- Kintone apps that could not be read
);

CREATE INDEX IF NOT EXISTS idx_checklist_run_date
    ON checklist_run (business_date DESC, ran_at DESC);

ALTER TABLE checklist_run ENABLE ROW LEVEL SECURITY;


-- One row per store per checklist per day — the table to query.
--
-- `completed` is NULLABLE and that is load-bearing: NULL means the Kintone app
-- was unreadable on the run that wrote the row, which is NOT the same as the
-- store missing it. Anything counting misses must say `completed IS FALSE`,
-- never `NOT completed`. The upsert never lets a NULL overwrite a real answer.
--
-- district/dm are a SNAPSHOT of the Kintone Store Directory at run time, not a
-- live join: districts get re-cut, and last quarter's numbers should keep
-- reporting under the DM who actually owned the store that day.
CREATE TABLE IF NOT EXISTS checklist_completion (
    id                  BIGSERIAL PRIMARY KEY,
    business_date       DATE NOT NULL,
    store_number        TEXT NOT NULL,          -- soft key to stores.store_number
    checklist           TEXT NOT NULL,          -- opening|qfs_am|qfs_pm|rush_am|rush_pm|closing
    completed           BOOLEAN,                -- NULL = source app unreadable, see above
    submissions         INTEGER NOT NULL DEFAULT 0,  -- matching records found
    first_submitted_at  TIMESTAMPTZ,            -- earliest matching submission, UTC
    store_name          TEXT,
    district            TEXT,
    district_manager    TEXT,
    run_id              BIGINT REFERENCES checklist_run (id) ON DELETE SET NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT checklist_completion_grain UNIQUE (business_date, store_number, checklist)
);

CREATE INDEX IF NOT EXISTS idx_checklist_completion_date
    ON checklist_completion (business_date DESC, store_number);
CREATE INDEX IF NOT EXISTS idx_checklist_completion_store
    ON checklist_completion (store_number, business_date DESC);
CREATE INDEX IF NOT EXISTS idx_checklist_completion_district
    ON checklist_completion (district, business_date DESC);
-- The "who missed what" query, which is the whole point of the table.
CREATE INDEX IF NOT EXISTS idx_checklist_completion_missed
    ON checklist_completion (business_date DESC, checklist)
    WHERE completed IS FALSE;

ALTER TABLE checklist_completion ENABLE ROW LEVEL SECURITY;


-- One row per store per Mon-Sun week for the Weekly Cleaning checklist.
--
-- Separate from checklist_completion because the grain genuinely differs — a
-- week, and a percentage rather than a yes/no — and forcing it into the daily
-- table would mean either a fake date or a column that is null for every other
-- row. photos_total is stored per row because it is read off the Kintone form at
-- run time: when a cleaning task is added, 32/47 and 32/50 must stay tellable
-- apart rather than silently becoming different percentages of "the form".
CREATE TABLE IF NOT EXISTS checklist_cleaning_week (
    id                  BIGSERIAL PRIMARY KEY,
    week_start          DATE NOT NULL,          -- Monday
    week_end            DATE NOT NULL,          -- Sunday
    store_number        TEXT NOT NULL,          -- soft key to stores.store_number
    photos_filled       INTEGER NOT NULL DEFAULT 0,
    photos_total        INTEGER NOT NULL,       -- fields on the form that week
    pct                 NUMERIC(5,4) NOT NULL,  -- 0.0000-1.0000
    passed              BOOLEAN NOT NULL,       -- pct >= the 0.75 threshold
    submitted           BOOLEAN NOT NULL,       -- FALSE = no record at all that week
    store_name          TEXT,
    district            TEXT,
    district_manager    TEXT,
    run_id              BIGINT REFERENCES checklist_run (id) ON DELETE SET NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT checklist_cleaning_week_grain UNIQUE (week_start, store_number)
);

CREATE INDEX IF NOT EXISTS idx_checklist_cleaning_week
    ON checklist_cleaning_week (week_start DESC, store_number);
CREATE INDEX IF NOT EXISTS idx_checklist_cleaning_store
    ON checklist_cleaning_week (store_number, week_start DESC);

ALTER TABLE checklist_cleaning_week ENABLE ROW LEVEL SECURITY;
