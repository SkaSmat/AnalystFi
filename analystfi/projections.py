"""Projections FIRE — Monte Carlo. DÉTERMINISTE (hors aléa simulé, graine fixée).

Deux choses que le rendement fixe à 7 % ne capte pas :
  - la distribution (probabilité de succès, pas un montant unique)
  - le RISQUE DE SÉQUENCE : ce sont les 1res années après l'arrêt d'activité
    qui décident, pas le rendement moyen.

Hypothèses de rendement/vol RÉELS par classe d'actif : ce sont des conventions,
affichées et modifiables dans l'app, pas des vérités.
"""
from __future__ import annotations

import sqlite3

import numpy as np

from . import db

# (rendement réel annuel, volatilité) — conventions, à challenger.
CLASS_ASSUMPTIONS = {
    "actions":     (0.065, 0.16),
    "crypto":      (0.15, 0.70),
    "obligations": (0.025, 0.05),
    "liquidités":  (0.005, 0.01),
    "immobilier":  (0.02, 0.08),
    "autre":       (0.03, 0.10),
}
CROSS_CORR = 0.2   # corrélation inter-classes retenue pour agréger la vol


def portfolio_mu_sigma(conn: sqlite3.Connection, assumptions: dict | None = None) -> tuple[float, float, dict]:
    a = assumptions or CLASS_ASSUMPTIONS
    rows = db.rows(conn, "select bucket, value from v_allocation where dimension = 'asset_class'")
    total = sum(r["value"] for r in rows) or 1.0
    weights = {r["bucket"]: r["value"] / total for r in rows}

    mu = sum(w * a.get(cl, a["autre"])[0] for cl, w in weights.items())
    # sigma agrégée avec corrélation inter-classes CROSS_CORR
    var = 0.0
    items = list(weights.items())
    for i, (ci, wi) in enumerate(items):
        si = a.get(ci, a["autre"])[1]
        for j, (cj, wj) in enumerate(items):
            sj = a.get(cj, a["autre"])[1]
            rho = 1.0 if i == j else CROSS_CORR
            var += wi * wj * rho * si * sj
    return mu, float(np.sqrt(max(var, 0))), weights


def simulate(conn: sqlite3.Connection, params: dict) -> dict:
    """params :
        start            : capital financier de départ (€)
        monthly          : versement mensuel pendant l'accumulation (€)
        years_accum      : horizon d'accumulation (ans)
        years_retire     : durée de la retraite à financer (ans)
        annual_spend     : dépense annuelle en retraite (€, réel)
        n                : nb de trajectoires
        assumptions      : override CLASS_ASSUMPTIONS
    """
    mu, sigma, weights = portfolio_mu_sigma(conn, params.get("assumptions"))
    start = float(params.get("start", 0))
    monthly = float(params.get("monthly", 0))
    ya = int(params.get("years_accum", 15))
    yr = int(params.get("years_retire", 30))
    spend = float(params.get("annual_spend", 0))
    n = int(params.get("n", 5000))

    rng = np.random.default_rng(42)
    contrib = monthly * 12

    # --- accumulation ---
    wealth = np.full(n, start, dtype=float)
    paths = np.zeros((n, ya + 1))
    paths[:, 0] = wealth
    for y in range(ya):
        r = rng.normal(mu, sigma, n)
        wealth = wealth * (1 + r) + contrib
        wealth = np.maximum(wealth, 0)
        paths[:, y + 1] = wealth
    terminal = wealth.copy()

    # --- décumulation (risque de séquence : rendements tirés année par année) ---
    survive = np.zeros(n, dtype=bool)
    if spend > 0 and yr > 0:
        w = terminal.copy()
        alive = np.ones(n, dtype=bool)
        for _ in range(yr):
            r = rng.normal(mu, sigma, n)
            w = np.where(alive, w * (1 + r) - spend, w)
            alive = alive & (w > 0)
        survive = alive
    success_rate = float(survive.mean() * 100) if spend > 0 else None

    pct = lambda arr, p: float(np.percentile(arr, p))
    return {
        "assumptions": {"mu_pct": round(mu * 100, 2), "sigma_pct": round(sigma * 100, 1),
                        "class_weights": {k: round(v * 100, 1) for k, v in weights.items()}},
        "horizon_accum": ya,
        "terminal": {"p10": round(pct(terminal, 10)), "p50": round(pct(terminal, 50)),
                     "p90": round(pct(terminal, 90))},
        "median_path": [round(float(np.percentile(paths[:, y], 50))) for y in range(ya + 1)],
        "p10_path": [round(float(np.percentile(paths[:, y], 10))) for y in range(ya + 1)],
        "p90_path": [round(float(np.percentile(paths[:, y], 90))) for y in range(ya + 1)],
        "fire": {"years_retire": yr, "annual_spend": spend, "success_rate_pct": success_rate}
        if spend > 0 else None,
    }


def format_projection(p: dict) -> str:
    a = p["assumptions"]
    def eur(x): return f"{x:,.0f} €".replace(",", " ")
    lines = [
        "═══ PROJECTION (Monte Carlo) ═══",
        f"  Hypothèses portefeuille : rendement réel {a['mu_pct']} %/an, vol {a['sigma_pct']} %",
        f"  Dans {p['horizon_accum']} ans, capital financier :",
        f"    pessimiste (p10) : {eur(p['terminal']['p10'])}",
        f"    médian     (p50) : {eur(p['terminal']['p50'])}",
        f"    favorable  (p90) : {eur(p['terminal']['p90'])}",
    ]
    if p["fire"]:
        f = p["fire"]
        lines += [
            "",
            f"  FIRE — tenir {f['years_retire']} ans à {eur(f['annual_spend'])}/an :",
            f"    probabilité de succès : {f['success_rate_pct']:.0f} %  "
            f"(intègre le risque de séquence)",
        ]
    return "\n".join(lines)
