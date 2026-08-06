"""Moteur de risque (V2) — DÉTERMINISTE.

Passe du poids vers la contribution au risque. Métriques :
  - volatilité annualisée du portefeuille
  - matrice de corrélation (Eiffage↔Bouygues, crypto interne…)
  - MCTR / contribution au risque par ligne et par poche
    (révèle qu'une poche crypto à 24 % du capital peut porter 50 %+ du risque)
  - max drawdown de l'allocation actuelle sur la fenêtre historique
  - stress tests de scénarios réels (2008 / mars 2020 / 2022)

Nécessite un historique de prix (prices) : lancer d'abord
`python -m analystfi.cli history`. Sans historique, renvoie available=False.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from . import db

FREQ = "W-FRI"      # returns hebdomadaires : robuste au décalage calendaire actions/crypto
ANN = 52
MIN_POINTS = 20     # nb minimal de returns pour retenir un actif

# Scénarios de stress : chocs par classe d'actif (règles de place usuelles).
STRESS = {
    "2008 (crise financière)": {"actions": -0.55, "crypto": -0.80, "liquidités": 0.0},
    "Mars 2020 (Covid)":       {"actions": -0.34, "crypto": -0.50, "liquidités": 0.0},
    "2022 (choc de taux)":     {"actions": -0.18, "crypto": -0.65, "liquidités": 0.0},
}


def _returns(conn: sqlite3.Connection) -> pd.DataFrame:
    rows = db.rows(
        conn,
        "select a.name, h.price_date, h.close from price_history h "
        "join assets a on a.id = h.asset_id order by h.price_date",
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["price_date"] = pd.to_datetime(df["price_date"])
    wide = df.pivot_table(index="price_date", columns="name", values="close")
    wide = wide.resample(FREQ).last().ffill()
    rets = wide.pct_change()
    good = [c for c in rets.columns if rets[c].notna().sum() >= MIN_POINTS]
    return rets[good].dropna()


def _weights(conn: sqlite3.Connection) -> tuple[dict, float, set]:
    pos = db.rows(conn, "select asset_name, market_value, is_cash from v_positions")
    total = sum((p["market_value"] or 0) for p in pos)
    w = {}
    cash = set()
    for p in pos:
        w[p["asset_name"]] = w.get(p["asset_name"], 0) + (p["market_value"] or 0)
        if p["is_cash"]:
            cash.add(p["asset_name"])
    return w, total, cash


def _asset_class(conn: sqlite3.Connection) -> dict:
    rows = db.rows(
        conn,
        "select a.name, e.bucket, e.weight_pct from assets a "
        "join asset_exposures e on e.asset_id = a.id where e.dimension = 'asset_class'",
    )
    best: dict = {}
    for r in rows:
        if r["name"] not in best or r["weight_pct"] > best[r["name"]][1]:
            best[r["name"]] = (r["bucket"], r["weight_pct"])
    return {k: v[0] for k, v in best.items()}


def compute_risk(conn: sqlite3.Connection) -> dict:
    rets = _returns(conn)
    weights, total, cash = _weights(conn)
    if total <= 0:
        return {"available": False, "reason": "aucune position."}
    if rets.empty:
        return {"available": False, "reason": "pas d'historique de prix — lance `history`."}

    klass = _asset_class(conn)

    # Univers de risque : actifs avec historique (risqués) + cash (vol 0).
    risky = list(rets.columns)
    universe = risky + [c for c in cash if c in weights and c not in risky]
    covered_value = sum(weights.get(n, 0) for n in universe)
    uncovered = [n for n in weights if n not in universe and weights[n] > 0]

    # matrice de returns : cash en colonnes nulles
    R = rets.copy()
    for c in universe:
        if c not in R.columns:
            R[c] = 0.0
    R = R[universe]

    w = np.array([weights.get(n, 0) for n in universe], dtype=float)
    w = w / w.sum()  # renormalisé sur l'univers couvert

    cov = R.cov().values * ANN
    port_var = float(w @ cov @ w)
    sigma = float(np.sqrt(max(port_var, 0)))

    # MCTR / contribution au risque
    contrib = {}
    if sigma > 0:
        marginal = cov @ w / sigma
        ccr = w * marginal            # somme = sigma
        for i, n in enumerate(universe):
            contrib[n] = {
                "weight_pct": round(100 * w[i], 2),
                "risk_contribution_pct": round(100 * ccr[i] / sigma, 2),
            }

    # agrégation par classe d'actif : poids vs part du risque
    by_class: dict = {}
    for n in universe:
        cl = klass.get(n, "autre") if n not in cash else "liquidités"
        d = by_class.setdefault(cl, {"weight_pct": 0.0, "risk_contribution_pct": 0.0})
        d["weight_pct"] += contrib.get(n, {}).get("weight_pct", 0)
        d["risk_contribution_pct"] += contrib.get(n, {}).get("risk_contribution_pct", 0)
    for d in by_class.values():
        d["weight_pct"] = round(d["weight_pct"], 2)
        d["risk_contribution_pct"] = round(d["risk_contribution_pct"], 2)

    # volatilités individuelles + corrélations remarquables
    vol_i = {c: round(float(rets[c].std() * np.sqrt(ANN)) * 100, 1) for c in risky}
    corr = rets.corr()
    pairs = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append((cols[i], cols[j], round(float(corr.iloc[i, j]), 2)))
    pairs.sort(key=lambda x: abs(x[2]), reverse=True)

    # corrélation entre titres employeur (concentration sectorielle chiffrée)
    emp_names = [r["name"] for r in db.rows(conn, "select name from assets where is_employer = 1")]
    emp = [n for n in emp_names if n in corr.columns]
    employer_corr = []
    for i in range(len(emp)):
        for j in range(i + 1, len(emp)):
            employer_corr.append((emp[i], emp[j], round(float(corr.loc[emp[i], emp[j]]), 2)))

    # max drawdown de l'allocation actuelle sur la fenêtre
    port_ret = (R * w).sum(axis=1)
    cum = (1 + port_ret).cumprod()
    drawdown = float((cum / cum.cummax() - 1).min()) if len(cum) else 0.0

    # stress tests par classe d'actif
    stress = {}
    positions = db.rows(conn, "select asset_name, market_value, is_cash from v_positions")
    for scen, shocks in STRESS.items():
        loss = 0.0
        for p in positions:
            cl = "liquidités" if p["is_cash"] else klass.get(p["asset_name"], "actions")
            loss += (p["market_value"] or 0) * shocks.get(cl, shocks.get("actions", 0))
        stress[scen] = {
            "impact_eur": round(loss, 0),
            "impact_pct": round(100 * loss / total, 1),
            "after_eur": round(total + loss, 0),
        }

    return {
        "available": True,
        "window": {"from": str(rets.index.min().date()), "to": str(rets.index.max().date()),
                   "points": int(len(rets))},
        "coverage_pct": round(100 * covered_value / total, 1),
        "uncovered": uncovered,
        "portfolio_vol_pct": round(sigma * 100, 1),
        "max_drawdown_pct": round(drawdown * 100, 1),
        "asset_vol_pct": dict(sorted(vol_i.items(), key=lambda x: -x[1])),
        "risk_by_class": dict(sorted(by_class.items(), key=lambda x: -x[1]["risk_contribution_pct"])),
        "risk_by_asset": dict(sorted(contrib.items(), key=lambda x: -x[1]["risk_contribution_pct"])),
        "top_correlations": pairs[:8],
        "employer_correlation": employer_corr,
        "stress_tests": stress,
    }


def format_risk(r: dict) -> str:
    if not r.get("available"):
        return f"Risque indisponible : {r.get('reason')}"
    lines = [
        "═══ RISQUE ═══",
        f"  Fenêtre : {r['window']['from']} → {r['window']['to']} "
        f"({r['window']['points']} points hebdo, couverture {r['coverage_pct']}%)",
        f"  Volatilité annualisée : {r['portfolio_vol_pct']} %",
        f"  Max drawdown (alloc. actuelle) : {r['max_drawdown_pct']} %",
        "",
        "  Poids vs contribution au RISQUE (par poche) :",
    ]
    for cl, d in r["risk_by_class"].items():
        lines.append(f"    {cl:12s}: poids {d['weight_pct']:5.1f} %  →  risque {d['risk_contribution_pct']:5.1f} %")
    if r.get("employer_correlation"):
        lines += ["", "  Corrélation titres employeur :"]
        for a, b, c in r["employer_correlation"]:
            lines.append(f"    {a} ↔ {b} : {c}")
    lines += ["", "  Corrélations notables :"]
    for a, b, c in r["top_correlations"][:5]:
        lines.append(f"    {a} ↔ {b} : {c}")
    lines += ["", "  Stress tests (sur actifs financiers) :"]
    for scen, d in r["stress_tests"].items():
        lines.append(f"    {scen:26s}: {d['impact_pct']:6.1f} %  ({d['impact_eur']:+,.0f} €)".replace(",", " "))
    if r["uncovered"]:
        lines.append("")
        lines.append(f"  ⚠️ Hors couverture (pas d'historique) : {', '.join(r['uncovered'])}")
    return "\n".join(lines)
