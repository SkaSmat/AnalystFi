"""CLI locale. Usage :

    python -m analystfi.cli init            # crée patrimoine.db
    python -m analystfi.cli seed            # charge l'exemple de vérification
    python -m analystfi.cli check           # vérifie que v_positions sort les bons chiffres
    python -m analystfi.cli load <fichier>  # exécute un script .sql (ex: ton import)
    python -m analystfi.cli refresh         # rafraîchit les prix spot (réseau)
    python -m analystfi.cli history         # charge ~2 ans d'historique (réseau, pour le risque)
    python -m analystfi.cli report          # affiche le rapport d'analyse
    python -m analystfi.cli risk            # affiche l'analyse de risque (vol, MCTR, stress)
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import db, engine


def cmd_init() -> None:
    db.init_db()
    print(f"OK — base créée : {db.DB_PATH}")


def cmd_seed() -> None:
    db.load_seed()
    print("OK — seed chargé.")


def cmd_check() -> None:
    conn = db.connect()
    p = db.one(conn, "select quantity, pru, market_value, unrealized_pnl "
                     "from v_positions where asset_name like '%seed test%'")
    conn.close()
    if not p:
        sys.exit("Aucune position seed. Lance d'abord : init puis seed.")
    exp = {"quantity": 20.0, "pru": 110.20, "market_value": 2600.0, "unrealized_pnl": 396.0}
    ok = all(abs((p[k] or 0) - v) < 0.01 for k, v in exp.items())
    print(f"attendu : {exp}")
    print(f"obtenu  : {{'quantity': {p['quantity']}, 'pru': {p['pru']}, "
          f"'market_value': {p['market_value']}, 'unrealized_pnl': {p['unrealized_pnl']}}}")
    print("✅ v_positions OK" if ok else "❌ écart détecté")
    sys.exit(0 if ok else 1)


def cmd_load() -> None:
    if len(sys.argv) < 3:
        sys.exit("Usage : python -m analystfi.cli load <fichier.sql>")
    path = Path(sys.argv[2])
    if not path.exists():
        sys.exit(f"Fichier introuvable : {path}")
    conn = db.connect()
    try:
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    print(f"OK — {path.name} exécuté.")


def cmd_refresh() -> None:
    from . import prices
    conn = db.connect()
    res = prices.refresh_prices(conn)
    conn.close()
    print(f"{res['prices_ok']}/{res['total']} prix mis à jour, {res['fx']} taux de change.")
    for r in res["results"]:
        if not r["ok"]:
            print(f"  ⚠️  {r['asset']} : {r['error']}")


def cmd_history() -> None:
    from . import prices
    conn = db.connect()
    res = prices.refresh_history(conn)
    conn.close()
    print(f"{res['loaded']}/{res['total']} historiques chargés.")
    for r in res["results"]:
        tag = f"{r['points']} pts" if r["ok"] else f"⚠️  {r['error']}"
        print(f"  {r['asset']} : {tag}")


def cmd_report() -> None:
    conn = db.connect()
    m = engine.compute_metrics(conn)
    conn.close()
    print(engine.format_report(m))


def cmd_risk() -> None:
    from . import risk
    conn = db.connect()
    r = risk.compute_risk(conn)
    conn.close()
    print(risk.format_risk(r))


COMMANDS = {
    "init": cmd_init, "seed": cmd_seed, "check": cmd_check, "load": cmd_load,
    "refresh": cmd_refresh, "history": cmd_history, "report": cmd_report, "risk": cmd_risk,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
