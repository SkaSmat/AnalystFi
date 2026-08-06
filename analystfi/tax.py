"""Fiscalité LATENTE — l'impôt que tu paierais si tu liquidais aujourd'hui.

Calcul par POCHE (= groupe fiscal), pas ligne par ligne :
  - le taux (%) est celui réglé sur la poche par l'utilisateur ;
  - il s'applique à la plus-value NETTE de la poche (les lignes en perte
    réduisent le gain des autres). C'est ce qui rend le crypto-global juste :
    un portefeuille crypto globalement en perte → impôt nul.

Estimations, à revalider avant toute cession.
"""
from __future__ import annotations

import sqlite3

from . import db

# Repli si aucune poche n'a de taux réglé (taux par type d'enveloppe).
FALLBACK_RATE = {
    "pea": 0.172, "pea_pme": 0.172, "cto": 0.30,
    "crypto_wallet": 0.30, "crypto_exchange": 0.30, "epargne_salariale": 0.172,
    "per": 0.30, "assurance_vie": 0.247, "livret_a": 0.0, "ldds": 0.0, "lep": 0.0,
    "cel_pel": 0.172, "compte_courant": 0.0, "scpi": 0.30, "autre": 0.30,
}


def latent_tax(conn: sqlite3.Connection) -> dict:
    rows = db.rows(
        conn,
        "select p.account_id, p.account_name, p.account_type, p.asset_name, "
        "       p.market_value, p.unrealized_pnl, a.tax_rate_pct "
        "from v_positions p join accounts a on a.id = p.account_id "
        "order by p.market_value desc",
    )
    groups: dict[int, dict] = {}
    positions = []
    brut = 0.0
    for r in rows:
        rate = (r["tax_rate_pct"] / 100.0) if r["tax_rate_pct"] is not None \
            else FALLBACK_RATE.get(r["account_type"], 0.30)
        value = r["market_value"] or 0
        gain = r["unrealized_pnl"] or 0
        g = groups.setdefault(r["account_id"], {"poche": r["account_name"], "rate": rate,
                                                "brut": 0.0, "gain": 0.0})
        g["brut"] += value
        g["gain"] += gain
        brut += value
        positions.append({
            "asset_name": r["asset_name"], "poche": r["account_name"],
            "brut": round(value, 2), "gain_latent": round(gain, 2),
        })

    group_list, tax_total = [], 0.0
    for g in groups.values():
        impot = round(g["rate"] * max(g["gain"], 0), 2)   # sur la PV NETTE de la poche
        tax_total += impot
        group_list.append({
            "poche": g["poche"], "brut": round(g["brut"], 2),
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
