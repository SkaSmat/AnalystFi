# AnalystFi — analyseur patrimonial

Outil personnel qui agit comme un gestionnaire de patrimoine : tu **poses tes
chiffres** (ceux que tu tiens dans ton Excel), il te rend **la lecture complète** —
patrimoine net, allocation, concentration, **risque** (volatilité, MCTR, stress
tests), **projection FIRE** (Monte Carlo) et **idées d'investissement**.

> Ce n'est pas un conseil en gestion de patrimoine réglementé. C'est un système
> qui rend visibles les risques que l'intuition sous-estime.

## Principe : analyseur, pas coffre-fort

**Rien n'est stocké.** Ton Excel reste ta source de vérité. Tu ouvres l'outil, tu
poses/actualises tes lignes dans un tableau (tu ajoutes autant de lignes que tu
veux), tu cliques **Analyser** — les chiffres vivent le temps de la session puis
s'effacent. Résultat : aucune base de données, aucun hébergement à réveiller,
coût 0 €, données privées.

```
Tableau éditable (par catégorie d'actif)
  → base SQLite EN MÉMOIRE (analystfi/build.py)  — reconstruite à chaque analyse
     → moteur déterministe (engine.py) : net, allocation, concentration, frais
     → moteur de risque (risk.py) : vol, MCTR, corrélations, stress tests
     → projections (projections.py) : Monte Carlo FIRE, risque de séquence
        → couche conseil (advise.py) : le LLM INTERPRÈTE, ne calcule jamais
```

## Lancer en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Déployer (URL perso, gratuit, zéro install)

1. Fork/dépôt sur ton GitHub (déjà le cas).
2. [share.streamlit.io](https://share.streamlit.io) → *New app* → choisis ce dépôt,
   branche, `app.py`.
3. (Optionnel) *Settings → Secrets* : `ANTHROPIC_API_KEY = "sk-ant-..."` pour activer
   la couche conseil. Tout le reste (net, risque, projection) marche sans clé.
4. Tu obtiens une URL. Tu l'ouvres quand tu veux, tu poses tes chiffres, tu analyses.

L'app dort après inactivité et se réveille en quelques secondes à la visite — pas
de base à dé-pauser puisqu'il n'y en a pas.

## Ce que l'outil calcule

- **Patrimoine net** (avec ou sans résidence principale ; crédit déduit).
- **Allocation transparisée** : classe d'actif, région, secteur, devise (un ETF
  S&P 500 est éclaté en US / tech… ; les titres connus sont reconnus automatiquement).
- **Concentration** : poids par ligne, top-5, HHI, alerte **titre employeur**
  (avec le facteur aggravant capital humain), poche crypto.
- **Risque** : volatilité annualisée, max drawdown, **MCTR** (contribution au
  risque par poche — révèle qu'une poche crypto à 24 % du capital peut porter 80 %+
  du risque), corrélations (dont titres employeur), **stress tests** 2008 / mars
  2020 / 2022.
- **Projection FIRE** : Monte Carlo (p10 / p50 / p90), probabilité de tenir X ans
  à Y €/an, **risque de séquence** intégré.
- **Conseil** : hiérarchisation des risques, contre-argument, idées d'invest cadrées
  (si une clé Anthropic est fournie).

## Outillage CLI (optionnel, pour usage avancé / base persistante)

`python -m analystfi.cli init | seed | check | load <f.sql> | history | report | risk`

## Roadmap

- [x] Socle transactionnel + moteur (net, allocation, concentration, frais).
- [x] Moteur de risque (vol, MCTR, corrélations, stress tests).
- [x] Analyseur stateless (tableau flexible) + projection FIRE Monte Carlo + couche conseil LLM.
- [ ] Couche fiscale détaillée (ordre de retrait optimal PEA/PEE/AV/PER, PFU crypto).
- [ ] Bandes de rééquilibrage (règle 5/25), VaR/CVaR.
