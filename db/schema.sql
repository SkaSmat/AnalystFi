-- AnalystFi — schéma Supabase
-- À exécuter une fois dans Supabase Studio → SQL Editor.

create extension if not exists pgcrypto;

-- Positions du patrimoine
create table if not exists positions (
  id uuid primary key default gen_random_uuid(),
  categorie text not null,
  enveloppe text not null,
  etablissement text,
  libelle text not null,
  montant_eur numeric not null,
  date_ouverture date,
  support text,
  frais_annuels_pct numeric default 0,
  notes text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Objectifs (singleton, contenu markdown maintenu par l'agent)
create table if not exists objectifs (
  id int primary key default 1,
  contenu_md text not null default '',
  updated_at timestamptz default now(),
  constraint objectifs_singleton check (id = 1)
);
insert into objectifs (id, contenu_md) values (1, '') on conflict (id) do nothing;

-- Profil fiscal (singleton)
create table if not exists profil_fiscal (
  id int primary key default 1,
  contenu_md text not null default '',
  updated_at timestamptz default now(),
  constraint profil_singleton check (id = 1)
);
insert into profil_fiscal (id, contenu_md) values (1, '') on conflict (id) do nothing;

-- Mémo : décisions, alertes, raisonnements à retenir entre sessions
create table if not exists memo (
  id uuid primary key default gen_random_uuid(),
  type text not null,
  contenu text not null,
  created_at timestamptz default now()
);
