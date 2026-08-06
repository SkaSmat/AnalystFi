-- =============================================================
--  SEED DE VÉRIFICATION (SQLite) — à lancer après le schéma.
--  Prouve que v_positions calcule la bonne quantité + PRU.
--
--    python -m analystfi.cli seed
--    (ou : sqlite3 patrimoine.db < db/seed_example.sql)
--
--  PEA ouvert en 2020, ETF MSCI World, 2 achats :
--    10 @ 100,00 € + 2 € de frais   puis   10 @ 120,00 € + 2 € de frais
--    → quantité = 20
--    → PRU = (1002 + 1202) / 20 = 2204 / 20 = 110,20 €
--    → market_value @ 130 € = 2600,00 €
--    → unrealized_pnl = 2600 − 20*110,20 = 396,00 €
-- =============================================================

insert into accounts (name, type, provider, opened_at)
values ('PEA (seed test)', 'pea', 'Bourse Direct', '2020-01-01');

insert into assets (name, isin, ticker, currency, price_source, price_symbol, ter_pct)
values ('Amundi MSCI World (seed test)', 'LU1681043599', 'CW8', 'EUR', 'yahoo', 'CW8.PA', 0.38);

insert into asset_exposures (asset_id, dimension, bucket, weight_pct)
select a.id, d.dimension, d.bucket, d.weight_pct
from assets a
join (
  select 'asset_class' as dimension, 'actions' as bucket, 100 as weight_pct union all
  select 'region','US',70     union all
  select 'region','Europe',15 union all
  select 'region','Japon',6   union all
  select 'region','Autres',9  union all
  select 'sector','tech',25   union all
  select 'sector','finance',15 union all
  select 'sector','autres',60 union all
  select 'currency','USD',70  union all
  select 'currency','EUR',15  union all
  select 'currency','JPY',6   union all
  select 'currency','autres',9
) d on 1=1
where a.isin = 'LU1681043599';

insert into transactions (account_id, asset_id, trade_date, type, quantity, unit_price, fees)
select acc.id, ast.id, '2024-01-15', 'buy', 10, 100.00, 2.00
from accounts acc, assets ast
where acc.name = 'PEA (seed test)' and ast.isin = 'LU1681043599';

insert into transactions (account_id, asset_id, trade_date, type, quantity, unit_price, fees)
select acc.id, ast.id, '2024-06-15', 'buy', 10, 120.00, 2.00
from accounts acc, assets ast
where acc.name = 'PEA (seed test)' and ast.isin = 'LU1681043599';

insert into prices (asset_id, price_date, close, currency)
select id, date('now'), 130.00, 'EUR' from assets where isin = 'LU1681043599'
on conflict (asset_id, price_date) do update set close = excluded.close;
