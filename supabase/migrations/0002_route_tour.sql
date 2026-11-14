-- Fly-through tour for each route: which scan sweeps the 3D viewer flies to, which way it faces, and when.
-- Additive: existing rows and readers are unaffected. Run this in the Supabase SQL editor.
-- The server saves routes without a tour (and logs a warning) until this column exists, so running it is safe at any time.
alter table routes add column if not exists tour jsonb;
