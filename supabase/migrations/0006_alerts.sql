-- Safety alerts from the wearable: a medic fall, bad air. The web app shows a banner while `active` is true.
-- Additive: a new table, nothing existing changes. Run this in the Supabase SQL editor.
create table if not exists alerts (
  id bigserial primary key,
  incident_id uuid references incidents(id),
  device_id text,
  kind text not null,          -- fall | air
  active boolean not null default true,
  detail jsonb,                -- air: {"v": raw reading}
  created_at timestamptz default now(),
  cleared_at timestamptz
);

alter table alerts enable row level security;
create policy "anon read" on alerts for select to anon using (true);
alter publication supabase_realtime add table alerts;
