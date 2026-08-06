"""Moteur d'analyse DÉTERMINISTE.

Produit un dict de métriques + alertes. C'est la seule source de chiffres :
un futur LLM ne fera qu'interpréter ce dict, jamais recalculer (sinon
hallucinations sur ton propre patrimoine).

V1 : patrimoine net, allocation transparisée, concentration (top-5, HHI,
mono-position, titre employeur), poids des frais projeté.
"""
from __future__ import annotations

import sqlite3

from . import db

# Seuils de gestion (normes institutionnelles usuelles)
SEUIL_LIGNE_INFO = 5.0     # au-delà : concentration à surveiller
SEUIL_LIGNE_WARN = 10.0    # au-delà : risque idiosyncratique non rémunéré
HORIZON_FRAIS_ANS = 15


def _pct(part: float, total: float) -> float:
    return round(100 * part / total, 2) if total else 0.0


def compute_metrics(conn: sqlite3.Connection) -> dict:
    positions = db.rows(
        conn,
        "select account_name, account_type, asset_name, isin, is_employer, ter_pct, "
        "quantity, pru, last_price, price_date, market_value, unrealized_pnl "
        "from v_positions order by market_value desc",
    )
    nw = db.one(conn, "select * from v_net_worth") or {
        "financial_assets": 0, "real_estate": 0, "liabilities": 0, "net_worth": 0,
    }
    alloc_rows = db.rows(conn, "select dimension, bucket, value from v_allocation")

    fin_total = sum((p["market_value"] or 0) for p in positions)

    # --- Concentration ---
    ranked = [p for p in positions if (p["market_value"] or 0) > 0]
    for p in ranked:
        p["weight_pct"] = _pct(p["market_value"], fin_total)
    top5 = ranked[:5]
    top5_weight = round(sum(p["weight_pct"] for p in top5), 2)
    # HHI sur fractions (0..1) : 1 = tout dans une ligne, ~0 = très diversifié
    hhi = round(sum((p["market_value"] / fin_total) ** 2 for p in ranked), 4) if fin_total else 0.0
    effective_positions = round(1 / hhi, 1) if hhi else 0.0

    employer_value = sum((p["market_value"] or 0) for p in ranked if p["is_employer"])
    employer_weight = _pct(employer_value, fin_total)

    # --- Allocation transparisée (poids % par dimension) ---
    allocation: dict[str, list] = {}
    dim_totals: dict[str, float] = {}
    for r in alloc_rows:
        dim_totals[r["dimension"]] = dim_totals.get(r["dimension"], 0) + (r["value"] or 0)
    for r in alloc_rows:
        allocation.setdefault(r["dimension"], []).append({
            "bucket": r["bucket"],
            "value": r["value"],
            "weight_pct": _pct(r["value"], dim_totals[r["dimension"]]),
        })
    for dim in allocation:
        allocation[dim].sort(key=lambda x: x["weight_pct"], reverse=True)

    # --- Frais ---
    annual_fee_eur = round(sum((p["market_value"] or 0) * (p["ter_pct"] or 0) / 100 for p in ranked), 2)
    mgmt = db.rows(conn, "select management_fee_pct from accounts where is_active = 1")
    # coût composé approximatif des frais sur l'horizon (drag sur le capital financier)
    fee_rate = annual_fee_eur / fin_total if fin_total else 0.0
    fee_drag_15y = round(fin_total * (1 - (1 - fee_rate) ** HORIZON_FRAIS_ANS), 2) if fin_total else 0.0

    # --- Alertes (hiérarchisées : le LLM les priorisera / commentera) ---
    alerts = []
    if employer_weight >= SEUIL_LIGNE_WARN:
        alerts.append({
            "level": "high",
            "code": "titre_employeur",
            "message": (
                f"Titre employeur = {employer_weight}% des actifs financiers "
                f"({employer_value:,.0f} €). Aggravant : ton capital humain est corrélé "
                f"à 100% à ce titre — un choc sur l'employeur frappe salaire ET patrimoine."
            ).replace(",", " "),
        })
    for p in ranked:
        if not p["is_employer"] and p["weight_pct"] >= SEUIL_LIGNE_WARN:
            alerts.append({
                "level": "medium",
                "code": "mono_position",
                "message": f"{p['asset_name']} = {p['weight_pct']}% des actifs financiers (seuil {SEUIL_LIGNE_WARN}%).",
            })
    if top5_weight >= 80 and len(ranked) > 5:
        alerts.append({
            "level": "medium",
            "code": "top5",
            "message": f"Top-5 = {top5_weight}% des actifs financiers : diversification faible.",
        })
    stale = [p for p in ranked if p["market_value"] and not p["last_price"]]
    if stale:
        alerts.append({
            "level": "info",
            "code": "prix_manquant",
            "message": f"{len(stale)} position(s) sans cours : lance un rafraîchissement des prix.",
        })

    return {
        "net_worth": {
            "financial_assets": round(nw["financial_assets"], 2),
            "real_estate": round(nw["real_estate"], 2),
            "liabilities": round(nw["liabilities"], 2),
            "net_worth": round(nw["net_worth"], 2),
        },
        "positions": ranked,
        "concentration": {
            "hhi": hhi,
            "effective_positions": effective_positions,
            "top5_weight_pct": top5_weight,
            "employer_value": round(employer_value, 2),
            "employer_weight_pct": employer_weight,
            "n_positions": len(ranked),
        },
        "allocation": allocation,
        "fees": {
            "annual_fee_eur": annual_fee_eur,
            "weighted_ter_pct": round(100 * fee_rate, 3),
            f"drag_{HORIZON_FRAIS_ANS}y_eur": fee_drag_15y,
            "accounts_with_mgmt_fee": sum(1 for m in mgmt if (m["management_fee_pct"] or 0) > 0),
        },
        "alerts": sorted(alerts, key=lambda a: {"high": 0, "medium": 1, "info": 2}[a["level"]]),
    }


def format_report(m: dict) -> str:
    """Rapport texte lisible (le même dict alimentera plus tard le LLM)."""
    def eur(x): return f"{x:,.0f} €".replace(",", " ")

    nw = m["net_worth"]
    c = m["concentration"]
    lines = [
        "═══ PATRIMOINE NET ═══",
        f"  Actifs financiers : {eur(nw['financial_assets'])}",
        f"  Immobilier        : {eur(nw['real_estate'])}",
        f"  Passif            : − {eur(nw['liabilities'])}",
        f"  ─────────────────────",
        f"  NET               : {eur(nw['net_worth'])}",
        "",
        "═══ CONCENTRATION (actifs financiers) ═══",
        f"  Nb de lignes      : {c['n_positions']}  (équivalent diversifié ≈ {c['effective_positions']})",
        f"  HHI               : {c['hhi']}",
        f"  Top-5             : {c['top5_weight_pct']} %",
        f"  Titre employeur   : {c['employer_weight_pct']} %  ({eur(c['employer_value'])})",
    ]
    if m["allocation"]:
        lines += ["", "═══ ALLOCATION ═══"]
        for dim, buckets in m["allocation"].items():
            top = ", ".join(f"{b['bucket']} {b['weight_pct']}%" for b in buckets[:4])
            lines.append(f"  {dim:12s}: {top}")
    f = m["fees"]
    lines += [
        "",
        "═══ FRAIS ═══",
        f"  TER moyen pondéré : {f['weighted_ter_pct']} %/an  ({eur(f['annual_fee_eur'])}/an)",
        f"  Coût composé {HORIZON_FRAIS_ANS} ans : {eur(f[f'drag_{HORIZON_FRAIS_ANS}y_eur'])}",
    ]
    if m["alerts"]:
        lines += ["", "═══ ALERTES ═══"]
        icon = {"high": "🔴", "medium": "🟠", "info": "🔵"}
        for a in m["alerts"]:
            lines.append(f"  {icon[a['level']]} {a['message']}")
    return "\n".join(lines)
