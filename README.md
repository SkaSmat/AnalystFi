# AnalystFi — système d'aide à la décision patrimoniale

Outil personnel mono-utilisateur qui agit comme un gestionnaire de patrimoine :
il consolide le patrimoine, analyse l'allocation et le risque selon les normes
utilisées par les fonds/gérants, et servira plus tard à simuler (FIRE, fiscalité)
et à conseiller.

> Ce n'est pas un conseil en gestion de patrimoine réglementé. C'est un système
> qui rend visibles les risques que l'intuition sous-estime, et de quoi challenger
> un CGP.

## Principe d'architecture

1. **Modèle en journal de transactions, jamais en photo de soldes.** C'est la
   seule façon de calculer un jour un TRI, un PRU, une plus-value latente.
2. **Le moteur est déterministe** (calculs de risque en TypeScript). **Le LLM ne
   calcule jamais : il interprète** le JSON de métriques + alertes produit par le
   moteur. Sinon → hallucinations sur ton propre patrimoine.
3. **Coût ≈ 0 €** : Supabase free tier + sources de prix gratuites.

```
Sources de prix (Yahoo / CoinGecko / Stooq / BCE)
   → Edge Function refresh-prices  (pg_cron, quotidien)
      → Postgres : transactions + prices  (source de vérité)
         → vues v_positions / v_allocation / v_net_worth
            → moteur de risque déterministe (JSON de métriques + alertes)
               → couche LLM (commentaire, priorisation, contre-argument)
```

## Schéma de données (`db/`)

| Table | Rôle |
|---|---|
| `accounts` | l'enveloppe (PEA, CTO, AV, PER…). `opened_at` pilote l'horloge fiscale 5 ans PEA / 8 ans AV. |
| `assets` | l'instrument (ISIN, ticker, devise, source de prix). |
| `asset_exposures` | transparisation (look-through) : un ETF World s'éclate en US 70 %, tech 25 %… |
| `transactions` | le journal. `signed_quantity` et `cash_flow` sont des colonnes générées (convention de signe figée par Postgres). |
| `prices` / `fx_rates` | historique alimenté par le cron. |
| `properties` / `liabilities` | immobilier + passif. Sans le passif, le patrimoine net est faux. |

Vues : `v_positions` (quantité + PRU + PnL latent), `v_allocation` (allocation
transparisée), `v_net_worth` (net consolidé, crédit déduit). RLS activé sur toutes
les tables (`auth.uid()`).

## Mise en place (ordre à respecter)

1. **Projet Supabase** (free tier, région Frankfurt).
2. **SQL Editor → `db/schema.sql` → Run.** Doit passer d'un bloc (idempotent).
3. **Auth → Email** activée, puis crée ton compte. Le RLS a besoin d'un `auth.uid()` réel.
4. **Vérifie le socle** : SQL Editor → `db/seed_example.sql` → Run.
   Attendu : `quantity=20`, `pru=110.20`, `market_value=2600.00`, `unrealized_pnl=396.00`.
   Si le PRU est faux sur 2 transactions, il sera faux sur 200. Nettoie le seed ensuite (bas du fichier).
5. **Prix automatiques** :
   - `supabase functions deploy refresh-prices --no-verify-jwt`
   - ajoute le secret `SUPABASE_SERVICE_ROLE_KEY` (Project Settings → Edge Functions → Secrets)
   - SQL Editor → `db/cron.sql` (remplace `<PROJECT_REF>` et `<ANON_KEY>`) → Run.

## Roadmap

- [x] **V1 — socle** : schéma transactionnel, seed de vérification, cron de prix (Yahoo/CoinGecko/Stooq + FX BCE).
- [ ] **V1 (suite)** : saisie des transactions, patrimoine net consolidé, allocation transparisée, concentration + HHI.
- [ ] **V2 — risque** : matrice de corrélation, MCTR (contribution marginale au risque), stress tests historiques (2008, mars 2020, 2022), bandes de rééquilibrage (règle 5/25).
- [ ] **V3 — simulation & conseil** : Monte Carlo (risque de séquence, taux de retrait), couche fiscale (PFU/PEA/AV/PER/LMNP), ordre de retrait optimal, puis couche LLM.
