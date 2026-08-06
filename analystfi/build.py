"""Ingestion : un tableau de lignes (par catégorie d'actif) → base en mémoire.

Stateless : rien n'est stocké. On reconstruit la base à chaque analyse, ce qui
permet d'ajouter/retirer autant de lignes qu'on veut sans jamais rien bloquer.

Une ligne = un dict :
  categorie : 'Actions' | 'ETF' | 'Crypto' | 'Liquidités' | 'Obligations'
              | 'Immobilier' | 'Crédit (passif)' | 'Autre'
  libelle   : texte libre ('Eiffage', 'Bitcoin'…)
  enveloppe : 'PEA' | 'CTO' | 'PEE/PER' | 'Assurance-vie' | 'Livret'
              | 'Wallet crypto' | 'Immo' | 'Autre'
  montant   : € (valeur actuelle ; pour un crédit = capital restant dû)
  devise    : 'EUR' | 'USD' | …
  symbole   : optionnel — ticker Yahoo ('FGR.PA') ou id CoinGecko ('bitcoin'),
              pour l'historique de risque
  employeur : bool
  taux      : optionnel — % (pour un crédit)
"""
from __future__ import annotations

import sqlite3

from . import db

# catégorie -> (bucket asset_class, is_cash, source de prix par défaut)
CLASS_MAP = {
    "Actions":     ("actions", 0, "yahoo"),
    "ETF":         ("actions", 0, "yahoo"),
    "Crypto":      ("crypto", 0, "coingecko"),
    "Liquidités":  ("liquidités", 1, "manual"),
    "Obligations": ("obligations", 0, "yahoo"),
    "Autre":       ("autre", 0, "manual"),
}

ENV_MAP = {
    "PEA": "pea", "PEA-PME": "pea_pme", "CTO": "cto", "PEE/PER": "epargne_salariale",
    "PER": "per", "Assurance-vie": "assurance_vie", "Livret": "livret_a",
    "Wallet crypto": "crypto_wallet", "Immo": "autre", "Autre": "autre",
}

# Transparisation des instruments connus : region + sector (+ currency si sous-jacent
# différent de la devise de cotation). Clé = ticker/id/nom en majuscules.
KNOWN_EXPOSURES = {
    "FGR.PA":   {"region": {"France": 100}, "sector": {"construction": 65, "concessions": 35}},
    "EIFFAGE":  {"region": {"France": 100}, "sector": {"construction": 65, "concessions": 35}},
    "EN.PA":    {"region": {"France": 100}, "sector": {"construction": 45, "telecom": 35, "media": 20}},
    "BOUYGUES": {"region": {"France": 100}, "sector": {"construction": 45, "telecom": 35, "media": 20}},
    "PE500.PA": {"region": {"US": 100}, "currency": {"USD": 100},
                 "sector": {"tech": 32, "finance": 13, "santé": 11, "conso": 16,
                            "communication": 9, "industrie": 8, "énergie": 4, "autres": 7}},
}


def _known(row: dict) -> dict:
    for key in (row.get("symbole"), row.get("libelle")):
        if key and key.strip().upper() in KNOWN_EXPOSURES:
            return KNOWN_EXPOSURES[key.strip().upper()]
    return {}


def build(rows: list[dict]) -> sqlite3.Connection:
    conn = db.memory()
    cur = conn.cursor()
    acc_cache: dict[str, int] = {}

    for r in rows:
        try:
            montant = float(r.get("montant") or 0)
        except (TypeError, ValueError):
            montant = 0
        if montant == 0 or not (r.get("libelle") or "").strip():
            continue
        cat = (r.get("categorie") or "Autre").strip()

        if cat == "Crédit (passif)":
            cur.execute(
                "insert into liabilities(name,initial_principal,outstanding,outstanding_date,"
                "rate_pct,monthly_payment,start_date,end_date) "
                "values(?,?,?,date('now'),?,0,date('now'),date('now'))",
                (r["libelle"], montant, montant, float(r.get("taux") or 0)),
            )
            continue

        if cat == "Immobilier":
            cur.execute(
                "insert into properties(name,regime,purchase_price,purchase_date,"
                "current_value,valuation_date) values(?,?,?,date('now'),?,date('now'))",
                (r["libelle"], "residence_principale", montant, montant),
            )
            continue

        # position financière
        env = (r.get("enveloppe") or "Autre").strip()
        if env not in acc_cache:
            cur.execute("insert into accounts(name,type,opened_at) values(?,?,date('now'))",
                        (env, ENV_MAP.get(env, "autre")))
            acc_cache[env] = cur.lastrowid
        acc_id = acc_cache[env]

        bucket, is_cash, default_src = CLASS_MAP.get(cat, ("autre", 0, "manual"))
        devise = (r.get("devise") or "EUR").strip().upper()
        symbole = (r.get("symbole") or "").strip() or None
        src = default_src if symbole else "manual"

        cur.execute(
            "insert into assets(name,currency,price_source,price_symbol,is_cash,is_employer,manual_value) "
            "values(?,?,?,?,?,?,1)",
            (r["libelle"], devise, src, symbole, is_cash, int(bool(r.get("employeur")))),
        )
        ast_id = cur.lastrowid

        # expositions : asset_class + devise + (region/sector connus)
        known = _known(r)
        cur.execute("insert into asset_exposures(asset_id,dimension,bucket,weight_pct) "
                    "values(?,'asset_class',?,100)", (ast_id, bucket))
        cur_exp = known.get("currency") or ({"USD": 100} if bucket == "crypto" else {devise: 100})
        for b, w in cur_exp.items():
            cur.execute("insert into asset_exposures(asset_id,dimension,bucket,weight_pct) "
                        "values(?,'currency',?,?)", (ast_id, b, w))
        for dim in ("region", "sector"):
            for b, w in known.get(dim, {}).items():
                cur.execute("insert into asset_exposures(asset_id,dimension,bucket,weight_pct) "
                            "values(?,?,?,?)", (ast_id, dim, b, w))

        # snapshot : base de coût = coût si fourni (sinon = valeur -> gain nul),
        # cours du jour = valeur actuelle. Gain latent = valeur - coût.
        try:
            cost = float(r.get("cost") or 0)
        except (TypeError, ValueError):
            cost = 0
        cost = cost if cost > 0 else montant
        cur.execute("insert into transactions(account_id,asset_id,trade_date,type,quantity,unit_price) "
                    "values(?,?,date('now'),'buy',1,?)", (acc_id, ast_id, cost))
        cur.execute("insert into prices(asset_id,price_date,close,currency) "
                    "values(?,date('now'),?,?)", (ast_id, montant, devise))

    conn.commit()
    return conn


def default_rows() -> list[dict]:
    """Lignes de départ (éditables/extensibles) pour amorcer le tableau."""
    return [
        {"categorie": "Actions", "libelle": "Eiffage", "enveloppe": "PEE/PER", "montant": 36236,
         "cost": 0, "devise": "EUR", "symbole": "FGR.PA", "employeur": True},
        {"categorie": "Actions", "libelle": "Bouygues", "enveloppe": "PEE/PER", "montant": 28600,
         "cost": 0, "devise": "EUR", "symbole": "EN.PA", "employeur": True},
        {"categorie": "ETF", "libelle": "Amundi PEA S&P 500 (PE500)", "enveloppe": "PEA", "montant": 12667,
         "cost": 0, "devise": "EUR", "symbole": "PE500.PA", "employeur": False},
        {"categorie": "Crypto", "libelle": "Bitcoin", "enveloppe": "Wallet crypto", "montant": 13853,
         "cost": 16588, "devise": "USD", "symbole": "bitcoin", "employeur": False},
        {"categorie": "Crypto", "libelle": "Ethereum", "enveloppe": "Wallet crypto", "montant": 3201,
         "cost": 1225, "devise": "USD", "symbole": "ethereum", "employeur": False},
        {"categorie": "Crypto", "libelle": "Solana", "enveloppe": "Wallet crypto", "montant": 14442,
         "cost": 6170, "devise": "USD", "symbole": "solana", "employeur": False},
        {"categorie": "Crypto", "libelle": "Celestia (TIA)", "enveloppe": "Wallet crypto", "montant": 2228,
         "cost": 11208, "devise": "USD", "symbole": "celestia", "employeur": False},
        {"categorie": "Crypto", "libelle": "NEAR", "enveloppe": "Wallet crypto", "montant": 885,
         "cost": 991, "devise": "USD", "symbole": "near", "employeur": False},
        {"categorie": "Crypto", "libelle": "Ouinex", "enveloppe": "Wallet crypto", "montant": 1304,
         "cost": 1304, "devise": "USD", "symbole": "", "employeur": False},
        {"categorie": "Liquidités", "libelle": "Livret A", "enveloppe": "Livret", "montant": 28767.47,
         "cost": 0, "devise": "EUR", "symbole": "", "employeur": False},
        {"categorie": "Immobilier", "libelle": "Résidence principale", "enveloppe": "Immo", "montant": 350000,
         "cost": 0, "devise": "EUR", "symbole": "", "employeur": False},
        {"categorie": "Crédit (passif)", "libelle": "Crédit RP", "enveloppe": "Immo", "montant": 283144.18,
         "cost": 0, "devise": "EUR", "symbole": "", "employeur": False, "taux": 3.30},
    ]
