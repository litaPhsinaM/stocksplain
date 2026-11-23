-- A second daily run, the afternoon edition: at 4:30 pm New York time (after the close, once the price job has the
-- closing prices) the daily job runs again to pick up new episodes and refresh the top stories. The quiz, audio and
-- email are written once a day and are not redone (run.py / daily.yml). Same function as 020, plus the 4 pm hour.
-- pg_cron runs on UTC: 9/10 UTC is 5 am New York in summer/winter, 20/21 UTC is 4 pm; the hour check keeps one of each.
create or replace function public.dispatch_daily_job() returns void
language plpgsql security definer set search_path = public, vault, net as $$
declare tok text;
begin
  if extract(hour from now() at time zone 'America/New_York') not in (5, 16) then return; end if;
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token';
  if tok is null then return; end if;
  perform net.http_post(
    url := 'https://api.github.com/repos/litaPhsinaM/stocksplain/actions/workflows/daily.yml/dispatches',
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'stocksplain-timer'),
    body := '{"ref":"main"}'::jsonb);
end $$;
revoke execute on function public.dispatch_daily_job() from public, anon, authenticated;

select cron.schedule('daily-digest', '30 9,10,20,21 * * 1-5', 'select public.dispatch_daily_job()');
