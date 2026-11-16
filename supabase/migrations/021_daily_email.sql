-- Daily morning email: who wants it, and a private token for one-tap unsubscribe. Safe to re-run.
-- Signing up uses the normal email sign-in link, so every address is confirmed by its owner (double opt-in).

create table if not exists public.email_prefs (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  daily      boolean not null default true,
  token      uuid not null unique default gen_random_uuid(),   -- goes in every email's unsubscribe link
  updated_at timestamptz not null default now(),
  last_sent  date                                               -- the sender skips anyone already emailed today
);
alter table public.email_prefs enable row level security;

-- Signed-in people can see their own setting; changes go through the function below.
drop policy if exists "own email prefs: read" on public.email_prefs;
create policy "own email prefs: read" on public.email_prefs for select to authenticated using ((select auth.uid()) = user_id);

create or replace function public.set_daily_email(p_on boolean) returns boolean
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then return false; end if;
  insert into public.email_prefs (user_id, daily) values (auth.uid(), p_on)
  on conflict (user_id) do update set daily = excluded.daily, updated_at = now();
  return p_on;
end $$;
grant execute on function public.set_daily_email(boolean) to authenticated;

-- The unsubscribe link works without signing in: the token alone identifies the row, and it can only switch emails off.
create or replace function public.unsubscribe_daily_email(p_token uuid) returns boolean
language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update public.email_prefs set daily = false, updated_at = now() where token = p_token;
  get diagnostics n = row_count;
  return n > 0;
end $$;
revoke all on function public.unsubscribe_daily_email(uuid) from public;
grant execute on function public.unsubscribe_daily_email(uuid) to anon, authenticated;
