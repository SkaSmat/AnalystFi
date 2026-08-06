# AnalystFi — système d'aide à la décision patrimoniale (local-first)

Outil **personnel, mono-utilisateur, 100 % local**. Il consolide ton patrimoine,
analyse l'allocation et le risque selon les normes utilisées par les fonds/gérants,
et servira plus tard à simuler (FIRE, fiscalité) et à conseiller.

> Ce n'est pas un conseil en gestion de patrimoine réglementé. C'est un système
> qui rend visibles les risques que l'intuition sous-estime, et de quoi challenger
> un CGP.

## Pourquoi local-first

Pas de serveur, pas de compte hébergé, **rien à réveiller**, coût **0 €**.
Tes données vivent dans un seul fichier SQLite (`patrimoine.db`) à côté du code.
Sauvegarde = copie du fichier (Dropbox/iCloud) ou commit dans un repo **privé**.
Les prix sont récupérés **à la demande** (un bouton), depuis des sources gratuites
et sans clé (Yahoo / Stooq / CoinGecko + taux BCE via Frankfurter).

## Principe d'architecture

1. **Journal de transactions, jamais photo de soldes** — seule base permettant de
   calculer un jour PRU, TRI, plus-value latente.
2. **Le moteur est déterministe** (Python). **Le LLM ne calculera jamais : il
   interprètera** le dict de métriques + alertes. Sinon → hallucinations sur ton
   propre patrimoine.

```
Sources de prix (à la demande)
  → SQLite : transactions + prices  (source de vérité)
     → vues v_positions / v_allocation / v_net_worth
        → moteur déterministe (analystfi/engine.py) : métriques + alertes
           → [V3] couche LLM : commentaire, priorisation, contre-argument
```

## Démarrage

```bash
pip install -r requirements.txt

python -m analystfi.cli init     # crée patrimoine.db
python -m analystfi.cli seed     # charge un exemple (PEA + ETF World + 2 achats)
python -m analystfi.cli check    # vérifie : quantity=20, pru=110.20, pnl=396.00
python -m analystfi.cli report   # rapport texte

streamlit run app.py             # interface locale
```

Dans l'app : bouton **« Rafraîchir les prix »** pour récupérer les cours.

## Modèle de données (`db/schema.sql`)

| Table | Rôle |
|---|---|
| `accounts` | l'enveloppe. `opened_at` = horloge fiscale 5 ans PEA / 8 ans AV. |
| `assets` | l'instrument (ISIN, ticker, source de prix, `is_employer`). |
| `asset_exposures` | transparisation look-through (ETF World → US 70 %, tech 25 %…). |
| `transactions` | le journal. `signed_quantity` / `cash_flow` = colonnes **générées** (convention de signe figée par la base). |
| `prices` / `fx_rates` | alimenté à la demande. |
| `properties` / `liabilities` | immobilier + passif (sans lui, le net est faux). |

Vues : `v_positions` (quantité + PRU + PnL latent), `v_allocation`, `v_net_worth`.

## Ce que le moteur calcule déjà (V1)

- Patrimoine **net** consolidé (crédit déduit).
- **Allocation transparisée** (classe d'actif, région, secteur, devise).
- **Concentration** : poids par ligne, top-5, **HHI** + nombre effectif de lignes.
- **Alerte titre employeur** (avec le facteur aggravant : capital humain corrélé à 100 %).
- **Frais** : TER moyen pondéré + coût composé sur 15 ans.

## Roadmap

- [x] **V1 — socle** : modèle transactionnel SQLite, prix à la demande, moteur (net worth, allocation, concentration/HHI, alerte employeur, frais), app locale.
- [ ] **V2 — risque** : volatilité, max drawdown, corrélation, **MCTR** (contribution marginale au risque), **stress tests** historiques (2008 / mars 2020 / 2022), bandes de rééquilibrage 5/25.
- [ ] **V3 — simulation & conseil** : Monte Carlo (risque de séquence, taux de retrait 3,25–3,5 %, Guyton-Klinger), couche fiscale (PFU/PEA/AV/PER/LMNP), ordre de retrait optimal, puis couche LLM.
