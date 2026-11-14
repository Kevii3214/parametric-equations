-- Wearable devices (the Raspberry Pi bridge): which incident each device belongs to, and the falls and
-- air-quality warnings it reports. Private to the server: row level security is on and there is no anon policy.
-- Additive: nothing existing changes. Run this in the Supabase SQL editor.
create table if not exists devices (
  device_id text primary key,
  incident_id uuid references incidents(id),
  linked_at timestamptz default now()
);

create table if not exists device_events (
  id bigserial primary key,
  device_id text,
  incident_id uuid references incidents(id),
  kind text,   -- fall | air
  data jsonb,
  created_at timestamptz default now()
);

alter table devices       enable row level security;
alter table device_events enable row level security;
