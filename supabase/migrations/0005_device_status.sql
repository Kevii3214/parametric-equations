-- What the wearable last told us: when it was last heard from, its firmware, which sensors it reported.
-- Additive: nothing existing changes. Run this in the Supabase SQL editor. The server works without it
-- (it only logs a warning when it cannot update these columns).
alter table devices add column if not exists last_seen_at timestamptz;
alter table devices add column if not exists fw text;
alter table devices add column if not exists sensors jsonb;
