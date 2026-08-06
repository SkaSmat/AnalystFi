"""Récupération des prix À LA DEMANDE (pas de cron, pas de serveur).

Sources gratuites et sans clé :
  - Yahoo Finance (actions / ETF)
  - Stooq (fallback CSV)
  - CoinGecko (crypto)
  - Frankfurter / BCE (taux de change)

Appelé quand tu ouvres l'outil et cliques "rafraîchir". Écrit dans
`prices` et `fx_rates`. Robuste par actif : une source qui tombe
n'empêche pas les autres.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import requests

TIMEOUT = 12
UA = {"User-Agent": "Mozilla/5.0"}


def _today() -> str:
    return date.today().isoformat()


def fetch_yahoo(symbol: str) -> tuple[float, str]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    meta = r.json()["chart"]["result"][0]["meta"]
    px = meta.get("regularMarketPrice")
    if px is None:
        raise ValueError("yahoo: pas de prix")
    return float(px), meta.get("currency", "EUR")


def fetch_stooq(symbol: str) -> tuple[float, str]:
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    line = r.text.strip().splitlines()[-1]
    cols = line.split(",")
    close = float(cols[6])
    if close <= 0:
        raise ValueError(f"stooq: close invalide ({cols[6]})")
    return close, "EUR"


def fetch_coingecko(coin_id: str) -> tuple[float, str]:
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=eur"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    close = r.json()[coin_id]["eur"]
    return float(close), "EUR"


_FETCHERS = {"yahoo": fetch_yahoo, "stooq": fetch_stooq, "coingecko": fetch_coingecko}


def refresh_fx(conn: sqlite3.Connection, currencies: list[str]) -> int:
    foreign = sorted({c.upper() for c in currencies if c and c.upper() != "EUR"})
    if not foreign:
        return 0
    url = f"https://api.frankfurter.app/latest?from=EUR&to={','.join(foreign)}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    rate_date = data.get("date", _today())
    n = 0
    for quote, rate in (data.get("rates") or {}).items():
        conn.execute(
            "insert into fx_rates(base,quote,rate_date,rate) values('EUR',?,?,?) "
            "on conflict(base,quote,rate_date) do update set rate=excluded.rate",
            (quote, rate_date, float(rate)),
        )
        n += 1
    conn.commit()
    return n


def fetch_yahoo_history(symbol: str, rng: str = "2y") -> list[tuple[str, float]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={rng}"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(ts, closes):
        if c is not None:
            out.append((date.fromtimestamp(t).isoformat(), float(c)))
    return out


def fetch_coingecko_history(coin_id: str, days: int = 730) -> list[tuple[str, float]]:
    url = (f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
           f"?vs_currency=eur&days={days}&interval=daily")
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for ms, price in r.json().get("prices", []):
        out.append((date.fromtimestamp(ms / 1000).isoformat(), float(price)))
    return out


def refresh_history(conn: sqlite3.Connection) -> dict:
    """Charge ~2 ans d'historique quotidien pour le calcul de risque."""
    assets = conn.execute(
        "select id, price_source, price_symbol, name from assets "
        "where price_source in ('yahoo','coingecko') and price_symbol is not null"
    ).fetchall()
    results = []
    for a in assets:
        try:
            if a["price_source"] == "yahoo":
                series = fetch_yahoo_history(a["price_symbol"])
            else:
                series = fetch_coingecko_history(a["price_symbol"])
            conn.executemany(
                "insert into price_history(asset_id,price_date,close) values(?,?,?) "
                "on conflict(asset_id,price_date) do update set close=excluded.close",
                [(a["id"], d, c) for d, c in series],
            )
            results.append({"asset": a["name"], "ok": True, "points": len(series)})
        except Exception as e:  # noqa: BLE001
            results.append({"asset": a["name"], "ok": False, "error": str(e)})
    conn.commit()
    return {"loaded": sum(1 for r in results if r["ok"]), "total": len(results), "results": results}


def refresh_prices(conn: sqlite3.Connection) -> dict:
    """Rafraîchit tous les actifs à source automatique. Renvoie un résumé."""
    assets = conn.execute(
        "select id, currency, price_source, price_symbol, name "
        "from assets where price_source != 'manual' and manual_value = 0"
    ).fetchall()

    results, currencies = [], []
    today = _today()
    for a in assets:
        if not a["price_symbol"]:
            results.append({"asset": a["name"], "ok": False, "error": "price_symbol manquant"})
            continue
        try:
            close, currency = _FETCHERS[a["price_source"]](a["price_symbol"])
            currencies.append(currency)
            conn.execute(
                "insert into prices(asset_id,price_date,close,currency) values(?,?,?,?) "
                "on conflict(asset_id,price_date) do update set close=excluded.close, currency=excluded.currency",
                (a["id"], today, close, currency),
            )
            results.append({"asset": a["name"], "ok": True, "close": close, "currency": currency})
        except Exception as e:  # noqa: BLE001 — une source qui tombe ne bloque pas les autres
            results.append({"asset": a["name"], "ok": False, "error": str(e)})
    conn.commit()

    fx = 0
    try:
        fx = refresh_fx(conn, currencies)
    except Exception:  # noqa: BLE001
        fx = -1

    ok = sum(1 for r in results if r["ok"])
    return {"date": today, "prices_ok": ok, "total": len(results), "fx": fx, "results": results}
