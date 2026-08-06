-- =============================================================
--  SEED DE VÉRIFICATION — à lancer APRÈS schema.sql
--  et APRÈS avoir créé ton compte (auth email).
--
--  Objectif : prouver que v_positions calcule la bonne quantité
--  et le bon PRU sur 2 transactions. Si c'est faux sur 2, c'est
--  faux sur 200.
--
--  Exemple : PEA ouvert en 2020, ETF MSCI World, 2 achats.
--    Achat 1 : 10 parts @ 100,00 € + 2 € de frais
--    Achat 2 : 10 parts @ 120,00 € + 2 € de frais
--    → quantité attendue = 20
--    → PRU attendu = (10*100+2 + 10*120+2) / 20 = 2204 / 20 = 110,20 €
--    → market_value @ 130 € = 2600,00 €
--    → unrealized_pnl = 2600 - 20*110,20 = 396,00 €
-- =============================================================

do $$
declare
  uid   uuid;
  acc   uuid;
  ast   uuid;
begin
  -- ton compte (le premier / unique utilisateur auth)
  select id into uid from auth.users order by created_at limit 1;
  if uid is null then
    raise exception 'Aucun utilisateur auth. Crée ton compte (auth email) avant de lancer ce seed.';
  end if;

  -- enveloppe : PEA ouvert en 2020 (antériorité 5 ans OK)
  insert into accounts (user_id, name, type, provider, opened_at)
  values (uid, 'PEA (seed test)', 'pea', 'Bourse Direct', '2020-01-01')
  returning id into acc;

  -- instrument : ETF MSCI World, prix auto via Yahoo
  insert into assets (user_id, name, isin, ticker, currency, price_source, price_symbol, ter_pct)
  values (uid, 'Amundi MSCI World (seed test)', 'LU1681043599', 'CW8', 'EUR', 'yahoo', 'CW8.PA', 0.38)
  returning id into ast;

  -- transparisation minimale (pour tester v_allocation)
  insert into asset_exposures (asset_id, dimension, bucket, weight_pct) values
    (ast, 'asset_class', 'actions', 100),
    (ast, 'region', 'US', 70),
    (ast, 'region', 'Europe', 15),
    (ast, 'region', 'Japon', 6),
    (ast, 'region', 'Autres', 9),
    (ast, 'sector', 'tech', 25),
    (ast, 'sector', 'finance', 15),
    (ast, 'sector', 'autres', 60),
    (ast, 'currency', 'USD', 70),
    (ast, 'currency', 'EUR', 15),
    (ast, 'currency', 'JPY', 6),
    (ast, 'currency', 'autres', 9);

  -- 2 achats
  insert into transactions (user_id, account_id, asset_id, trade_date, type, quantity, unit_price, fees) values
    (uid, acc, ast, '2024-01-15', 'buy', 10, 100.00, 2.00),
    (uid, acc, ast, '2024-06-15', 'buy', 10, 120.00, 2.00);

  -- un prix récent (le cron le fera automatiquement ensuite)
  insert into prices (asset_id, price_date, close, currency)
  values (ast, current_date, 130.00, 'EUR')
  on conflict (asset_id, price_date) do update set close = excluded.close;

  raise notice 'Seed OK. Lance maintenant : select * from v_positions;';
end $$;

-- Attendu : quantity = 20 | pru = 110.20 | market_value = 2600.00 | unrealized_pnl = 396.00
select account_name, asset_name, quantity, pru, last_price, market_value, unrealized_pnl
from v_positions;

-- Attendu : région US ~70 %, tech ~25 %, USD ~70 %
-- select dimension, bucket, value, weight_pct from v_allocation order by dimension, weight_pct desc;

-- Nettoyage du seed (dé-commente pour repartir propre) :
-- delete from accounts where name = 'PEA (seed test)';
-- delete from assets   where name = 'Amundi MSCI World (seed test)';
