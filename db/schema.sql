-- =============================================================
--  PATRIMOINE — Schéma Supabase / PostgreSQL
--  V1 : socle transactionnel + transparisation + passif
--
--  Ordre d'exécution (voir README) :
--    1. Ce fichier (schema.sql) dans le SQL Editor Supabase.
--    2. Activer l'auth email et créer ton compte (RLS a besoin d'un auth.uid() réel).
--    3. db/seed_example.sql pour vérifier que v_positions renvoie le bon PRU.
-- =============================================================

create extension if not exists pgcrypto;

-- -------------------------------------------------------------
-- 0. ENUMS
-- -------------------------------------------------------------

do $$ begin
  create type account_type as enum (
    'pea', 'pea_pme', 'cto', 'assurance_vie', 'per',
    'livret_a', 'ldds', 'lep', 'cel_pel',
    'crypto_wallet', 'crypto_exchange',
    'compte_courant', 'epargne_salariale', 'scpi', 'autre'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type transaction_type as enum (
    'buy', 'sell',
    'deposit', 'withdrawal',      -- versement / retrait d'espèces sur l'enveloppe
    'dividend', 'interest', 'coupon',
    'fee', 'tax',
    'transfer_in', 'transfer_out' -- apport/sortie de titres (ex: transfert PEA)
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type exposure_dimension as enum (
    'asset_class', 'region', 'sector', 'currency', 'factor'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type price_source as enum (
    'yahoo', 'stooq', 'coingecko', 'twelvedata', 'manual'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type tax_regime as enum (
    'lmnp_reel', 'lmnp_micro', 'nu_reel', 'nu_micro', 'sci_is', 'residence_principale'
  );
exception when duplicate_object then null; end $$;


-- -------------------------------------------------------------
-- 1. ACCOUNTS — les enveloppes
--    opened_at est CRITIQUE : horloge fiscale PEA (5 ans) / AV (8 ans)
-- -------------------------------------------------------------

create table if not exists accounts (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references auth.users(id) on delete cascade,
  name              text not null,
  type              account_type not null,
  provider          text,                    -- Boursorama, Linxea, Binance...
  opened_at         date not null,
  base_currency     char(3) not null default 'EUR',
  management_fee_pct numeric(6,4) default 0, -- frais de gestion annuels (AV, PER)
  is_active         boolean not null default true,
  notes             text,
  created_at        timestamptz not null default now()
);

create index if not exists accounts_user_active_idx on accounts (user_id, is_active);


-- -------------------------------------------------------------
-- 2. ASSETS — les instruments
-- -------------------------------------------------------------

create table if not exists assets (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  name          text not null,
  isin          char(12),
  ticker        text,
  currency      char(3) not null default 'EUR',

  -- alimentation automatique du prix
  price_source  price_source not null default 'manual',
  price_symbol  text,          -- ex: 'CW8.PA' pour Yahoo, 'bitcoin' pour CoinGecko

  ter_pct       numeric(6,4) default 0,  -- frais courants annuels de l'ETF/fonds
  is_cash       boolean not null default false,
  notes         text,
  created_at    timestamptz not null default now(),

  unique (user_id, isin),
  -- si la source n'est pas manuelle, un symbole est obligatoire
  constraint symbol_required check (price_source = 'manual' or price_symbol is not null)
);

create index if not exists assets_user_idx on assets (user_id);


-- -------------------------------------------------------------
-- 3. ASSET_EXPOSURES — la transparisation (look-through)
--    Un ETF World n'est PAS une ligne : il s'éclate en buckets.
--    Somme des weight_pct = 100 pour chaque (asset, dimension).
-- -------------------------------------------------------------

create table if not exists asset_exposures (
  id          uuid primary key default gen_random_uuid(),
  asset_id    uuid not null references assets(id) on delete cascade,
  dimension   exposure_dimension not null,
  bucket      text not null,              -- 'actions', 'US', 'tech', 'USD', 'value'...
  weight_pct  numeric(7,4) not null check (weight_pct >= 0 and weight_pct <= 100),

  unique (asset_id, dimension, bucket)
);

create index if not exists asset_exposures_asset_dim_idx on asset_exposures (asset_id, dimension);


-- -------------------------------------------------------------
-- 4. TRANSACTIONS — le journal. Source de vérité unique.
--    On ne stocke JAMAIS un solde : on le recalcule toujours.
-- -------------------------------------------------------------

create table if not exists transactions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  account_id   uuid not null references accounts(id) on delete cascade,
  asset_id     uuid references assets(id) on delete restrict, -- null si mouvement d'espèces
  trade_date   date not null,
  type         transaction_type not null,

  quantity     numeric(24,8) not null default 0 check (quantity >= 0),
  unit_price   numeric(20,8) not null default 0 check (unit_price >= 0),
  fees         numeric(14,2) not null default 0,
  currency     char(3) not null default 'EUR',

  -- quantité signée : +achat / -vente. Sert au calcul de position.
  signed_quantity numeric(24,8) generated always as (
    case when type in ('sell','transfer_out') then -quantity else quantity end
  ) stored,

  -- flux de trésorerie signé, du point de vue du patrimoine investi.
  -- Négatif = argent sorti de ma poche. Sert au calcul du TRI (XIRR).
  cash_flow numeric(16,2) generated always as (
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
  created_at timestamptz not null default now(),

  -- un mouvement de titre exige un actif
  constraint asset_required check (
    type in ('deposit','withdrawal','fee','tax') or asset_id is not null
  )
);

create index if not exists transactions_user_date_idx on transactions (user_id, trade_date desc);
create index if not exists transactions_account_asset_idx on transactions (account_id, asset_id);


-- -------------------------------------------------------------
-- 5. PRICES — historique alimenté par le cron
-- -------------------------------------------------------------

create table if not exists prices (
  asset_id   uuid not null references assets(id) on delete cascade,
  price_date date not null,
  close      numeric(20,8) not null,
  currency   char(3) not null default 'EUR',
  primary key (asset_id, price_date)
);

create index if not exists prices_asset_date_idx on prices (asset_id, price_date desc);


-- taux de change (exposition devise + conversion)
create table if not exists fx_rates (
  base       char(3) not null,
  quote      char(3) not null,
  rate_date  date not null,
  rate       numeric(20,8) not null,
  primary key (base, quote, rate_date)
);


-- -------------------------------------------------------------
-- 6. PROPERTIES — immobilier
-- -------------------------------------------------------------

create table if not exists properties (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references auth.users(id) on delete cascade,
  name              text not null,
  address           text,
  regime            tax_regime not null,

  purchase_price    numeric(14,2) not null,
  acquisition_fees  numeric(14,2) not null default 0,  -- notaire, agence, travaux
  purchase_date     date not null,

  current_value     numeric(14,2) not null,
  valuation_date    date not null,

  monthly_rent      numeric(12,2) not null default 0,
  monthly_charges   numeric(12,2) not null default 0,  -- copro, taxe foncière/12, PNO, gestion
  created_at        timestamptz not null default now()
);

create index if not exists properties_user_idx on properties (user_id);


-- -------------------------------------------------------------
-- 7. LIABILITIES — le passif. Sans lui, le patrimoine net est faux.
-- -------------------------------------------------------------

create table if not exists liabilities (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references auth.users(id) on delete cascade,
  property_id        uuid references properties(id) on delete set null,
  name               text not null,

  initial_principal  numeric(14,2) not null,
  outstanding        numeric(14,2) not null,   -- capital restant dû
  outstanding_date   date not null,
  rate_pct           numeric(6,4) not null,
  insurance_pct      numeric(6,4) not null default 0,
  monthly_payment    numeric(12,2) not null,
  start_date         date not null,
  end_date           date not null,
  created_at         timestamptz not null default now()
);

create index if not exists liabilities_user_idx on liabilities (user_id);


-- =============================================================
--  VUES DE CALCUL
-- =============================================================

-- Positions courantes : quantité détenue + PRU (coût moyen pondéré)
create or replace view v_positions as
with movements as (
  select
    t.user_id,
    t.account_id,
    t.asset_id,
    sum(t.signed_quantity) as quantity,
    sum(case when t.type in ('buy','transfer_in')
             then t.quantity * t.unit_price + t.fees else 0 end) as total_cost,
    sum(case when t.type in ('buy','transfer_in')
             then t.quantity else 0 end) as total_bought
  from transactions t
  where t.asset_id is not null
  group by 1,2,3
),
last_price as (
  select distinct on (asset_id) asset_id, close, price_date
  from prices
  order by asset_id, price_date desc
)
select
  m.user_id,
  m.account_id,
  a.name        as account_name,
  a.type        as account_type,
  m.asset_id,
  ast.name      as asset_name,
  ast.isin,
  ast.currency,
  m.quantity,
  case when m.total_bought > 0
       then m.total_cost / m.total_bought end            as pru,
  lp.close                                               as last_price,
  lp.price_date                                          as price_date,
  round(m.quantity * lp.close, 2)                        as market_value,
  round(m.quantity * lp.close - m.quantity * (m.total_cost / nullif(m.total_bought,0)), 2)
                                                         as unrealized_pnl
from movements m
join accounts a  on a.id  = m.account_id
join assets  ast on ast.id = m.asset_id
left join last_price lp on lp.asset_id = m.asset_id
where m.quantity > 0.00000001;


-- Allocation transparisée : éclate chaque position selon ses expositions
create or replace view v_allocation as
select
  p.user_id,
  e.dimension,
  e.bucket,
  round(sum(p.market_value * e.weight_pct / 100), 2) as value,
  round(
    100 * sum(p.market_value * e.weight_pct / 100)
        / nullif(sum(sum(p.market_value * e.weight_pct / 100)) over (partition by p.user_id, e.dimension), 0)
  , 2) as weight_pct
from v_positions p
join asset_exposures e on e.asset_id = p.asset_id
group by p.user_id, e.dimension, e.bucket;


-- Patrimoine net consolidé
create or replace view v_net_worth as
select
  u.user_id,
  coalesce(fin.value, 0)    as financial_assets,
  coalesce(re.value, 0)     as real_estate,
  coalesce(deb.value, 0)    as liabilities,
  coalesce(fin.value,0) + coalesce(re.value,0) - coalesce(deb.value,0) as net_worth
from (select distinct user_id from accounts) u
left join (select user_id, sum(market_value) value
           from v_positions group by 1) fin on fin.user_id = u.user_id
left join (select user_id, sum(current_value) value
           from properties group by 1) re  on re.user_id  = u.user_id
left join (select user_id, sum(outstanding) value
           from liabilities group by 1) deb on deb.user_id = u.user_id;


-- =============================================================
--  ROW LEVEL SECURITY
-- =============================================================

alter table accounts        enable row level security;
alter table assets          enable row level security;
alter table asset_exposures enable row level security;
alter table transactions    enable row level security;
alter table prices          enable row level security;
alter table properties      enable row level security;
alter table liabilities     enable row level security;

-- Tables possédées directement par l'utilisateur
drop policy if exists own_accounts on accounts;
create policy own_accounts     on accounts     for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists own_assets on assets;
create policy own_assets       on assets       for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists own_transactions on transactions;
create policy own_transactions on transactions for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists own_properties on properties;
create policy own_properties   on properties   for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists own_liabilities on liabilities;
create policy own_liabilities  on liabilities  for all
  using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Tables filles : on remonte à l'asset
drop policy if exists own_exposures on asset_exposures;
create policy own_exposures on asset_exposures for all
  using (exists (select 1 from assets a where a.id = asset_id and a.user_id = auth.uid()))
  with check (exists (select 1 from assets a where a.id = asset_id and a.user_id = auth.uid()));

drop policy if exists own_prices on prices;
create policy own_prices on prices for all
  using (exists (select 1 from assets a where a.id = asset_id and a.user_id = auth.uid()))
  with check (exists (select 1 from assets a where a.id = asset_id and a.user_id = auth.uid()));

-- Les vues héritent du RLS des tables sous-jacentes (Postgres 15+ / security_invoker)
alter view v_positions  set (security_invoker = on);
alter view v_allocation set (security_invoker = on);
alter view v_net_worth  set (security_invoker = on);
