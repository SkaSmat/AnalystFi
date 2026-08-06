-- =============================================================
--  AnalystFi — schéma LOCAL (SQLite, mono-utilisateur)
--  Même modèle en journal de transactions, sans la couche
--  hébergement (pas de RLS, pas de user_id : tu es seul user).
--
--  Init : python -m analystfi.cli init
--  (ou : sqlite3 patrimoine.db < db/schema.sql)
-- =============================================================

pragma foreign_keys = on;

-- -------------------------------------------------------------
-- 1. ACCOUNTS — les enveloppes
--    opened_at est CRITIQUE : horloge fiscale PEA (5 ans) / AV (8 ans)
-- -------------------------------------------------------------
create table if not exists accounts (
  id                 integer primary key,
  name               text not null,
  type               text not null check (type in (
                       'pea','pea_pme','cto','assurance_vie','per',
                       'livret_a','ldds','lep','cel_pel',
                       'crypto_wallet','crypto_exchange',
                       'compte_courant','epargne_salariale','scpi','autre')),
  provider           text,                       -- Boursorama, Linxea, Binance...
  opened_at          text not null,              -- 'YYYY-MM-DD'
  base_currency      text not null default 'EUR',
  management_fee_pct real not null default 0,    -- frais de gestion annuels (AV, PER)
  is_active          integer not null default 1,
  notes              text,
  created_at         text not null default (datetime('now'))
);

-- -------------------------------------------------------------
-- 2. ASSETS — les instruments
-- -------------------------------------------------------------
create table if not exists assets (
  id           integer primary key,
  name         text not null,
  isin         text,
  ticker       text,
  currency     text not null default 'EUR',
  price_source text not null default 'manual' check (price_source in (
                 'yahoo','stooq','coingecko','twelvedata','manual')),
  price_symbol text,                         -- 'CW8.PA' (Yahoo), 'bitcoin' (CoinGecko)
  ter_pct      real not null default 0,      -- frais courants annuels ETF/fonds
  is_cash      integer not null default 0,
  is_employer  integer not null default 0,   -- titre employeur (concentration + capital humain corrélé)
  -- 1 = valorisé par un total saisi à la main (snapshot). Le refresh spot ne le
  -- touche pas, mais l'historique de risque peut être chargé via price_symbol.
  manual_value integer not null default 0,
  notes        text,
  created_at   text not null default (datetime('now')),
  unique (isin),
  check (price_source = 'manual' or price_symbol is not null)
);

-- -------------------------------------------------------------
-- 3. ASSET_EXPOSURES — la transparisation (look-through)
--    Un ETF World n'est PAS une ligne : il s'éclate en buckets.
--    Somme des weight_pct = 100 pour chaque (asset, dimension).
-- -------------------------------------------------------------
create table if not exists asset_exposures (
  id         integer primary key,
  asset_id   integer not null references assets(id) on delete cascade,
  dimension  text not null check (dimension in ('asset_class','region','sector','currency','factor')),
  bucket     text not null,                 -- 'actions','US','tech','USD','value'...
  weight_pct real not null check (weight_pct >= 0 and weight_pct <= 100),
  unique (asset_id, dimension, bucket)
);

-- -------------------------------------------------------------
-- 4. TRANSACTIONS — le journal. Source de vérité unique.
--    On ne stocke JAMAIS un solde : on le recalcule toujours.
--    signed_quantity / cash_flow : colonnes générées = convention
--    de signe figée par la base, jamais par le code applicatif.
-- -------------------------------------------------------------
create table if not exists transactions (
  id          integer primary key,
  account_id  integer not null references accounts(id) on delete cascade,
  asset_id    integer references assets(id) on delete restrict,  -- null = mouvement d'espèces
  trade_date  text not null,                -- 'YYYY-MM-DD'
  type        text not null check (type in (
                'buy','sell','deposit','withdrawal',
                'dividend','interest','coupon','fee','tax',
                'transfer_in','transfer_out')),
  quantity    real not null default 0 check (quantity >= 0),
  unit_price  real not null default 0 check (unit_price >= 0),
  fees        real not null default 0,
  currency    text not null default 'EUR',

  signed_quantity real generated always as (
    case when type in ('sell','transfer_out') then -quantity else quantity end
  ) stored,

  -- Négatif = argent sorti de ma poche. Format attendu par un XIRR.
  cash_flow real generated always as (
    case
      when type in ('buy','deposit','transfer_in','fee','tax')
        then -(quantity * unit_price + fees)
      when type in ('sell','withdrawal','transfer_out')
        then  (quantity * unit_price - fees)
      when type in ('dividend','interest','coupon')
        then  (quantity * unit_price - fees)
    end
  ) stored,

  notes      text,
  created_at text not null default (datetime('now')),

  check (type in ('deposit','withdrawal','fee','tax') or asset_id is not null)
);

create index if not exists transactions_date_idx on transactions (trade_date desc);
create index if not exists transactions_account_asset_idx on transactions (account_id, asset_id);

-- -------------------------------------------------------------
-- 5. PRICES / FX — alimenté à la demande (bouton "rafraîchir")
-- -------------------------------------------------------------
create table if not exists prices (
  asset_id   integer not null references assets(id) on delete cascade,
  price_date text not null,
  close      real not null,
  currency   text not null default 'EUR',
  primary key (asset_id, price_date)
);

create table if not exists fx_rates (
  base      text not null,
  quote     text not null,
  rate_date text not null,
  rate      real not null,
  primary key (base, quote, rate_date)
);

-- Historique de prix par UNITÉ (part/coin), pour le moteur de risque.
-- Séparé de `prices` : ici on stocke le cours réel, pas la valeur snapshot.
create table if not exists price_history (
  asset_id   integer not null references assets(id) on delete cascade,
  price_date text not null,
  close      real not null,
  primary key (asset_id, price_date)
);

-- -------------------------------------------------------------
-- 6. PROPERTIES — immobilier
-- -------------------------------------------------------------
create table if not exists properties (
  id               integer primary key,
  name             text not null,
  address          text,
  regime           text not null check (regime in (
                     'lmnp_reel','lmnp_micro','nu_reel','nu_micro','sci_is','residence_principale')),
  purchase_price   real not null,
  acquisition_fees real not null default 0,   -- notaire, agence, travaux
  purchase_date    text not null,
  current_value    real not null,
  valuation_date   text not null,
  monthly_rent     real not null default 0,
  monthly_charges  real not null default 0,   -- copro, taxe foncière/12, PNO, gestion
  created_at       text not null default (datetime('now'))
);

-- -------------------------------------------------------------
-- 7. LIABILITIES — le passif. Sans lui, le patrimoine net est faux.
-- -------------------------------------------------------------
create table if not exists liabilities (
  id                integer primary key,
  property_id       integer references properties(id) on delete set null,
  name              text not null,
  initial_principal real not null,
  outstanding       real not null,            -- capital restant dû
  outstanding_date  text not null,
  rate_pct          real not null,
  insurance_pct     real not null default 0,
  monthly_payment   real not null,
  start_date        text not null,
  end_date          text not null,
  created_at        text not null default (datetime('now'))
);

-- =============================================================
--  VUES DE CALCUL
-- =============================================================

-- Positions courantes : quantité détenue + PRU (coût moyen pondéré)
drop view if exists v_positions;
create view v_positions as
with movements as (
  select
    account_id, asset_id,
    sum(signed_quantity) as quantity,
    sum(case when type in ('buy','transfer_in') then quantity*unit_price+fees else 0 end) as total_cost,
    sum(case when type in ('buy','transfer_in') then quantity else 0 end) as total_bought
  from transactions
  where asset_id is not null
  group by account_id, asset_id
),
last_price as (
  select asset_id, close, price_date from (
    select asset_id, close, price_date,
           row_number() over (partition by asset_id order by price_date desc) as rn
    from prices
  ) where rn = 1
)
select
  m.account_id,
  a.name  as account_name,
  a.type  as account_type,
  m.asset_id,
  ast.name as asset_name,
  ast.isin,
  ast.currency,
  ast.is_employer,
  ast.is_cash,
  ast.ter_pct,
  m.quantity,
  case when m.total_bought > 0 then m.total_cost/m.total_bought end as pru,
  lp.close      as last_price,
  lp.price_date as price_date,
  round(m.quantity * lp.close, 2) as market_value,
  round(m.quantity * lp.close - m.quantity * (m.total_cost/nullif(m.total_bought,0)), 2) as unrealized_pnl
from movements m
join accounts a  on a.id  = m.account_id
join assets   ast on ast.id = m.asset_id
left join last_price lp on lp.asset_id = m.asset_id
where m.quantity > 0.00000001;

-- Allocation transparisée (valeur par bucket ; les poids % sont calculés par le moteur)
drop view if exists v_allocation;
create view v_allocation as
select
  e.dimension,
  e.bucket,
  round(sum(p.market_value * e.weight_pct / 100), 2) as value
from v_positions p
join asset_exposures e on e.asset_id = p.asset_id
where p.market_value is not null
group by e.dimension, e.bucket;

-- Patrimoine net consolidé (une seule ligne)
drop view if exists v_net_worth;
create view v_net_worth as
select
  coalesce((select sum(market_value)  from v_positions), 0) as financial_assets,
  coalesce((select sum(current_value) from properties),  0) as real_estate,
  coalesce((select sum(outstanding)   from liabilities), 0) as liabilities,
    coalesce((select sum(market_value)  from v_positions), 0)
  + coalesce((select sum(current_value) from properties),  0)
  - coalesce((select sum(outstanding)   from liabilities), 0) as net_worth;
