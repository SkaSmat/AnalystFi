-- =============================================================
--  PLANIFICATION DES PRIX — pg_cron + pg_net
--  À lancer APRÈS avoir déployé l'Edge Function refresh-prices.
--
--  Remplace <PROJECT_REF> par ta référence Supabase (ex: abcd1234)
--  et <ANON_KEY> par ta clé anon (Project Settings → API).
-- =============================================================

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Rafraîchit les prix chaque jour ouvré à 19h05 UTC (~21h05 Paris l'été).
-- Après la clôture d'Euronext, avant que tu regardes le soir.
select cron.schedule(
  'refresh-prices-daily',
  '5 19 * * 1-5',
  $$
  select net.http_post(
    url     := 'https://<PROJECT_REF>.supabase.co/functions/v1/refresh-prices',
    headers := jsonb_build_object(
      'Content-Type',  'application/json',
      'Authorization', 'Bearer <ANON_KEY>'
    ),
    body    := '{}'::jsonb
  );
  $$
);

-- Pour voir / supprimer le job :
--   select * from cron.job;
--   select cron.unschedule('refresh-prices-daily');

-- Déclenchement manuel immédiat (test) :
--   select net.http_post(
--     url := 'https://<PROJECT_REF>.supabase.co/functions/v1/refresh-prices',
--     headers := jsonb_build_object('Content-Type','application/json',
--                                   'Authorization','Bearer <ANON_KEY>'),
--     body := '{}'::jsonb);
