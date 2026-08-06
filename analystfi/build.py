"""Ingestion : des POCHES (chacune = un groupe fiscal) → base en mémoire.

Une poche = un bloc homogène (Actions/PEE, ETF/PEA, Crypto, Liquidités…) avec :
  - un taux d'impôt latent (%) réglé par l'utilisateur, appliqué à la plus-value
    NETTE de la poche (les lignes se compensent : c'est ce qui rend le calcul
    crypto-global correct) ;
  - une liste de lignes (les titres/coins détenus).

Stateless : rien n'est stocké, on reconstruit la base à chaque analyse.
"""
from __future__ import annotations

import sqlite3

from . import db

# classe de poche -> (bucket asset_class, is_cash, source de prix par défaut)
CLASS_MAP = {
    "Actions":     ("actions", 0, "yahoo"),
    "ETF":         ("actions", 0, "yahoo"),
    "Crypto":      ("crypto", 0, "coingecko"),
    "Obligations": ("obligations", 0, "yahoo"),
    "Liquidités":  ("liquidités", 1, "manual"),
    "Autre":       ("autre", 0, "manual"),
}

ENV_MAP = {
    "PEA": "pea", "PEA-PME": "pea_pme", "CTO": "cto", "PEE/PER": "epargne_salariale",
    "PER": "per", "Assurance-vie": "assurance_vie", "Livret": "livret_a",
    "Wallet crypto": "crypto_wallet", "Immo": "autre", "Autre": "autre",
}

# Transparisation des instruments connus (region + sector, + currency si le
# sous-jacent diffère de la devise de cotation). Clé = ticker/id/nom en majuscules.
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
        if key and str(key).strip().upper() in KNOWN_EXPOSURES:
            return KNOWN_EXPOSURES[str(key).strip().upper()]
    return {}


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _add_position(cur, acc_id: int, bucket: str, is_cash: int, default_src: str, r: dict) -> None:
    montant = _num(r.get("montant"))
    if montant == 0 or not str(r.get("libelle") or "").strip():
        return
    devise = (str(r.get("devise") or "EUR")).strip().upper()
    symbole = (str(r.get("symbole") or "")).strip() or None
    src = default_src if symbole else "manual"

    cur.execute(
        "insert into assets(name,currency,price_source,price_symbol,is_cash,is_employer,manual_value) "
        "values(?,?,?,?,?,?,1)",
        (r["libelle"], devise, src, symbole, is_cash, int(bool(r.get("employeur")))),
    )
    ast_id = cur.lastrowid

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

    cost = _num(r.get("cost"))
    cost = cost if cost > 0 else montant   # coût fourni -> gain ; sinon gain nul
    cur.execute("insert into transactions(account_id,asset_id,trade_date,type,quantity,unit_price) "
                "values(?,?,date('now'),'buy',1,?)", (acc_id, ast_id, cost))
    cur.execute("insert into prices(asset_id,price_date,close,currency) "
                "values(?,date('now'),?,?)", (ast_id, montant, devise))


def build_pockets(pockets: list[dict], immo: dict | None = None) -> sqlite3.Connection:
    conn = db.memory()
    cur = conn.cursor()
    for p in pockets:
        classe = p.get("classe", "Autre")
        bucket, is_cash, default_src = CLASS_MAP.get(classe, ("autre", 0, "manual"))
        cur.execute(
            "insert into accounts(name,type,opened_at,tax_rate_pct) values(?,?,date('now'),?)",
            (p.get("nom") or classe, ENV_MAP.get(p.get("enveloppe"), "autre"), p.get("taux")),
        )
        acc_id = cur.lastrowid
        for r in p.get("lignes", []):
            _add_position(cur, acc_id, bucket, is_cash, default_src, r)

    if immo:
        if _num(immo.get("rp_valeur")) > 0:
            cur.execute(
                "insert into properties(name,regime,purchase_price,purchase_date,"
                "current_value,valuation_date) values(?,?,?,date('now'),?,date('now'))",
                (immo.get("rp_nom") or "Résidence principale", "residence_principale",
                 _num(immo["rp_valeur"]), _num(immo["rp_valeur"])),
            )
        if _num(immo.get("credit_crd")) > 0:
            cur.execute(
                "insert into liabilities(name,initial_principal,outstanding,outstanding_date,"
                "rate_pct,monthly_payment,start_date,end_date) "
                "values(?,?,?,date('now'),?,0,date('now'),date('now'))",
                (immo.get("credit_nom") or "Crédit", _num(immo["credit_crd"]),
                 _num(immo["credit_crd"]), _num(immo.get("credit_taux"))),
            )
    conn.commit()
    return conn


def default_pockets() -> list[dict]:
    return [
        {"nom": "Actions employeur (PEE)", "classe": "Actions", "enveloppe": "PEE/PER", "taux": 17.2,
         "lignes": [
             {"libelle": "Eiffage", "montant": 36236, "cost": 0, "devise": "EUR", "symbole": "FGR.PA", "employeur": True},
             {"libelle": "Bouygues", "montant": 28600, "cost": 0, "devise": "EUR", "symbole": "EN.PA", "employeur": True},
         ]},
        {"nom": "ETF (PEA)", "classe": "ETF", "enveloppe": "PEA", "taux": 17.2,
         "lignes": [
             {"libelle": "Amundi PEA S&P 500 (PE500)", "montant": 12667, "cost": 0, "devise": "EUR", "symbole": "PE500.PA", "employeur": False},
         ]},
        {"nom": "Crypto", "classe": "Crypto", "enveloppe": "Wallet crypto", "taux": 30.0,
         "lignes": [
             {"libelle": "Bitcoin", "montant": 13853, "cost": 16588, "devise": "USD", "symbole": "bitcoin", "employeur": False},
             {"libelle": "Ethereum", "montant": 3201, "cost": 1225, "devise": "USD", "symbole": "ethereum", "employeur": False},
             {"libelle": "Solana", "montant": 14442, "cost": 6170, "devise": "USD", "symbole": "solana", "employeur": False},
             {"libelle": "Celestia (TIA)", "montant": 2228, "cost": 11208, "devise": "USD", "symbole": "celestia", "employeur": False},
             {"libelle": "NEAR", "montant": 885, "cost": 991, "devise": "USD", "symbole": "near", "employeur": False},
             {"libelle": "Ouinex", "montant": 1304, "cost": 1304, "devise": "USD", "symbole": "", "employeur": False},
         ]},
        {"nom": "Liquidités", "classe": "Liquidités", "enveloppe": "Livret", "taux": 0.0,
         "lignes": [
             {"libelle": "Livret A", "montant": 28767.47, "cost": 0, "devise": "EUR", "symbole": "", "employeur": False},
         ]},
    ]


def default_immo() -> dict:
    return {"rp_nom": "Résidence principale", "rp_valeur": 350000.0,
            "credit_nom": "Crédit RP", "credit_crd": 283144.18, "credit_taux": 3.30}
