-- Crew chat (Photon): which crew members are on which incident, and the Photon chat each one texts from.
-- Private to the server: row level security is on and there is no anon policy.
-- Additive: nothing existing changes. Run this in the Supabase SQL editor.
create table if not exists crew_threads (
  id bigserial primary key,
  incident_id uuid references incidents(id),
  handle text not null,                -- the crew member's phone (+15551234567) or email
  name text,
  assigned_phone_number text,          -- the Photon line they must text once
  photon_space_id text,                -- set when they first text the line; needed to message them later
  photon_user_id text,                 -- the line's user id in that chat (Photon's senderId)
  pending jsonb,                       -- a change waiting for the crew's YES
  created_at timestamptz default now(),
  unique (incident_id, handle)
);

alter table crew_threads enable row level security;

-- plan_steps.kind gets a new value, 'crew' (what the crew texted and what we texted back). kind is plain text,
-- so no change is needed here; the web app shows unknown kinds as a normal step.
