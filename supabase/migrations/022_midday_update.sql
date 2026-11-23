-- A second daily run, the midday update: at 12:30 pm New York time (most of the day's news has broken, and the market
-- has reacted since the open) the daily job runs again to pick up new episodes and refresh the top stories. The quiz, audio and
-- email are written once a day and are not redone (run.py / daily.yml). Same function as 020, plus the 12 pm hour.
-- pg_cron runs on UTC: 9/10 UTC is 5 am New York in summer/winter, 16/17 UTC is 12 pm; the hour check keeps one of each.
create or replace function public.dispatch_daily_job() returns void
language plpgsql security definer set search_path = public, vault, net as $$
declare tok text;
begin
  if extract(hour from now() at time zone 'America/New_York') not in (5, 12) then return; end if;
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token';
  if tok is null then return; end if;
  perform net.http_post(
    url := 'https://api.github.com/repos/litaPhsinaM/stocksplain/actions/workflows/daily.yml/dispatches',
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'stocksplain-timer'),
    body := '{"ref":"main"}'::jsonb);
end $$;
revoke execute on function public.dispatch_daily_job() from public, anon, authenticated;

select cron.schedule('daily-digest', '30 9,10,16,17 * * 1-5', 'select public.dispatch_daily_job()');
