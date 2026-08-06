"""CLI locale. Usage :

    python -m analystfi.cli init       # crée patrimoine.db
    python -m analystfi.cli seed       # charge l'exemple de vérification
    python -m analystfi.cli check      # vérifie que v_positions sort les bons chiffres
    python -m analystfi.cli refresh    # rafraîchit les prix (réseau)
    python -m analystfi.cli report     # affiche le rapport d'analyse
"""
from __future__ import annotations

import sys

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


def cmd_refresh() -> None:
    from . import prices
    conn = db.connect()
    res = prices.refresh_prices(conn)
    conn.close()
    print(f"{res['prices_ok']}/{res['total']} prix mis à jour, {res['fx']} taux de change.")
    for r in res["results"]:
        if not r["ok"]:
            print(f"  ⚠️  {r['asset']} : {r['error']}")


def cmd_report() -> None:
    conn = db.connect()
    m = engine.compute_metrics(conn)
    conn.close()
    print(engine.format_report(m))


COMMANDS = {
    "init": cmd_init, "seed": cmd_seed, "check": cmd_check,
    "refresh": cmd_refresh, "report": cmd_report,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
