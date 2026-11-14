-- Beeline initial schema. Paste into the Supabase SQL editor (or run as a migration).

create extension if not exists vector;

-- ===== Shared tables: Person 1 reads these live. This section is the contract. =====

create table incidents (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(),
  note text,
  parsed jsonb,
  building_id text,
  status text   -- planning | routing | en_route | arrived
);

create table plan_steps (
  id bigserial primary key,
  incident_id uuid references incidents(id),
  seq int,
  kind text,    -- plan | subagent | tool_call | tool_result | replan | final
  title text,
  detail jsonb,
  created_at timestamptz default now()
);

create table routes (
  id bigserial primary key,
  incident_id uuid references incidents(id),
  version int,
  entrance_node text,
  steps jsonb,  -- see contracts/route.schema.json
  total_seconds int,
  briefing text,
  created_at timestamptz default now()
);

create table positions (
  id bigserial primary key,
  incident_id uuid references incidents(id),
  route_version int,
  step_index int,
  progress_m real,
  floor int,
  off_route bool,
  created_at timestamptz default now()
);

create table cues (
  id bigserial primary key,
  incident_id uuid references incidents(id),
  route_version int,
  cue text,     -- LEFT | RIGHT | STRAIGHT | UTURN | FLOOR_UP | FLOOR_DOWN | ARRIVE | OFF_ROUTE
  dist_m real,
  text text,
  created_at timestamptz default now()
);

-- ===== Person 2's private tables: Person 1 never reads these. =====

create table buildings (
  id text primary key,
  name text,
  address text,
  record jsonb,
  aerial jsonb,
  updated_at timestamptz default now()
);

create table graphs (
  building_id text primary key references buildings(id),
  graph jsonb,
  source text,
  checked_by_hand bool default false,
  updated_at timestamptz default now()
);

create table notes (
  id bigserial primary key,
  building_id text references buildings(id),
  text text,
  embedding vector(768),  -- check against the Gemini embedding model actually used
  created_at timestamptz default now()
);

create table closures (
  id bigserial primary key,
  incident_id uuid references incidents(id),
  node_or_edge text,
  reason text,
  created_at timestamptz default now()
);

-- ===== Security =====
-- Tables made in the SQL editor have row level security OFF, which would let the
-- public anon key read AND write everything. Turn it on everywhere. The server's
-- service-role key bypasses it automatically.

alter table incidents  enable row level security;
alter table plan_steps enable row level security;
alter table routes     enable row level security;
alter table positions  enable row level security;
alter table cues       enable row level security;
alter table buildings  enable row level security;
alter table graphs     enable row level security;
alter table notes      enable row level security;
alter table closures   enable row level security;

-- The web app (anon key) may only READ the five shared tables. No policy on the
-- private tables means anon cannot touch them.
create policy "anon read" on incidents  for select to anon using (true);
create policy "anon read" on plan_steps for select to anon using (true);
create policy "anon read" on routes     for select to anon using (true);
create policy "anon read" on positions  for select to anon using (true);
create policy "anon read" on cues       for select to anon using (true);

-- ===== Realtime on the five shared tables =====

alter publication supabase_realtime add table incidents, plan_steps, routes, positions, cues;
