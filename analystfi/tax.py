"""Fiscalité LATENTE — l'impôt que tu paierais si tu liquidais aujourd'hui.

L'impôt porte sur la PLUS-VALUE (valeur − coût), pas sur le montant total, et il
se calcule par GROUPE FISCAL, pas ligne par ligne :
  - Crypto (art. 150 VH bis) : plus-value GLOBALE sur tout le portefeuille crypto.
    Une ligne en moins-value réduit donc le gain d'une autre. Si le portefeuille
    crypto est globalement en perte → impôt nul.
  - Titres (PEA, PEE, CTO…) : gains et pertes se compensent au sein de l'enveloppe.

Tout est estimation (règles connues 2026), à revalider avant toute cession.
"""
from __future__ import annotations

import sqlite3

from . import db

# Taux d'imposition sur la plus-value latente, par type d'enveloppe.
RATE_BY_ACCOUNT_TYPE = {
    "pea": 0.172, "pea_pme": 0.172,          # > 5 ans : prélèvements sociaux 17,2 % (IR exonéré)
    "cto": 0.30,                             # PFU 30 % (12,8 IR + 17,2 PS)
    "crypto_wallet": 0.30, "crypto_exchange": 0.30,  # PFU 30 % (art. 150 VH bis, GLOBAL)
    "epargne_salariale": 0.172,              # PEE : IR exonéré, PS 17,2 % sur le gain
    "per": 0.30,                             # approximation — le PER taxe le capital à la sortie (à affiner)
    "assurance_vie": 0.247,                  # > 8 ans approx (PS 17,2 % + IR 7,5 %, hors abattement)
    "livret_a": 0.0, "ldds": 0.0, "lep": 0.0, "cel_pel": 0.172,
    "compte_courant": 0.0, "scpi": 0.30, "autre": 0.30,
}

LABEL = {
    "pea": "PEA >5 ans (PS 17,2 %)", "pea_pme": "PEA-PME (PS 17,2 %)",
    "cto": "CTO (PFU 30 %)", "crypto": "Crypto (PFU 30 %, global)",
    "epargne_salariale": "PEE (PS 17,2 %)", "per": "PER (~30 %, approx.)",
    "assurance_vie": "AV >8 ans (~24,7 %)", "livret_a": "Livret (exonéré)",
    "ldds": "Livret (exonéré)", "lep": "Livret (exonéré)", "cel_pel": "CEL/PEL (PS 17,2 %)",
    "compte_courant": "Liquidités (exonéré)", "scpi": "SCPI (PFU 30 %)",
    "autre": "Autre (PFU 30 %)",
}


def _group_key(account_type: str) -> str:
    # tout le crypto est un seul groupe fiscal (calcul global)
    if account_type in ("crypto_wallet", "crypto_exchange"):
        return "crypto"
    return account_type


def latent_tax(conn: sqlite3.Connection) -> dict:
    rows = db.rows(
        conn,
        "select account_type, account_name, asset_name, market_value, unrealized_pnl, is_cash "
        "from v_positions order by market_value desc",
    )
    groups: dict[str, dict] = {}
    positions = []
    brut = 0.0
    for r in rows:
        key = _group_key(r["account_type"])
        rate = RATE_BY_ACCOUNT_TYPE.get(r["account_type"], 0.30)
        value = r["market_value"] or 0
        gain = r["unrealized_pnl"] or 0
        g = groups.setdefault(key, {"regime": LABEL.get(key, "—"), "rate": rate,
                                    "brut": 0.0, "gain": 0.0})
        g["brut"] += value
        g["gain"] += gain
        brut += value
        positions.append({
            "asset_name": r["asset_name"], "envelope": r["account_name"],
            "regime": LABEL.get(key, "—"), "brut": round(value, 2), "gain_latent": round(gain, 2),
        })

    group_list, tax_total = [], 0.0
    for g in groups.values():
        impot = round(g["rate"] * max(g["gain"], 0), 2)   # impôt sur la PV NETTE du groupe
        tax_total += impot
        group_list.append({
            "regime": g["regime"], "brut": round(g["brut"], 2),
            "gain_net": round(g["gain"], 2), "taux_pct": round(g["rate"] * 100, 1),
            "impot_latent": impot, "net": round(g["brut"] - impot, 2),
        })
    group_list.sort(key=lambda x: -x["brut"])

    return {
        "brut": round(brut, 2),
        "impot_latent": round(tax_total, 2),
        "net": round(brut - tax_total, 2),
        "taux_moyen_pct": round(100 * tax_total / brut, 2) if brut else 0.0,
        "groups": group_list,
        "positions": positions,
    }
