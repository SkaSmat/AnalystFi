"""AnalystFi — app locale (Streamlit).

    pip install -r requirements.txt
    streamlit run app.py

Tout est local : la base SQLite `patrimoine.db` vit à côté de ce fichier.
Les prix sont récupérés à la demande (bouton dans la barre latérale).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analystfi import db, engine, prices

st.set_page_config(page_title="AnalystFi", page_icon="💼", layout="wide")

# Init base au premier lancement
if not db.DB_PATH.exists():
    db.init_db()

conn = db.connect()

st.title("💼 AnalystFi")
st.caption("Système d'aide à la décision patrimoniale — local, tes données restent chez toi.")

# --- Barre latérale : actions ---
with st.sidebar:
    st.header("Actions")
    if st.button("🔄 Rafraîchir les prix", use_container_width=True):
        with st.spinner("Récupération des cours…"):
            res = prices.refresh_prices(conn)
        st.success(f"{res['prices_ok']}/{res['total']} prix, {res['fx']} taux FX.")
        for r in res["results"]:
            if not r["ok"]:
                st.warning(f"{r['asset']} : {r['error']}")
    st.divider()
    npos = db.one(conn, "select count(*) n from transactions")["n"]
    if npos == 0:
        if st.button("Charger l'exemple de démo", use_container_width=True):
            db.load_seed()
            st.rerun()
    st.caption(f"{npos} transaction(s) en base.")

m = engine.compute_metrics(conn)

# --- Alertes en tête (le plus important d'abord) ---
if m["alerts"]:
    st.subheader("Alertes")
    for a in m["alerts"]:
        {"high": st.error, "medium": st.warning, "info": st.info}[a["level"]](a["message"])

# --- Patrimoine net ---
nw = m["net_worth"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Actifs financiers", f"{nw['financial_assets']:,.0f} €".replace(",", " "))
c2.metric("Immobilier", f"{nw['real_estate']:,.0f} €".replace(",", " "))
c3.metric("Passif", f"− {nw['liabilities']:,.0f} €".replace(",", " "))
c4.metric("Patrimoine NET", f"{nw['net_worth']:,.0f} €".replace(",", " "))

st.divider()

# --- Positions ---
left, right = st.columns([3, 2])
with left:
    st.subheader("Positions")
    if m["positions"]:
        df = pd.DataFrame(m["positions"])[
            ["asset_name", "account_name", "quantity", "pru", "last_price",
             "market_value", "unrealized_pnl", "weight_pct"]
        ]
        df.columns = ["Actif", "Enveloppe", "Qté", "PRU", "Cours",
                      "Valeur", "+/- latent", "Poids %"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune position. Saisis tes comptes/actifs/transactions, ou charge l'exemple de démo.")

with right:
    st.subheader("Concentration")
    c = m["concentration"]
    st.metric("Titre employeur", f"{c['employer_weight_pct']} %")
    st.metric("Top-5", f"{c['top5_weight_pct']} %")
    st.metric("Lignes (équiv. diversifié)",
              f"{c['n_positions']} ({c['effective_positions']})")

# --- Allocation ---
if m["allocation"]:
    st.divider()
    st.subheader("Allocation transparisée")
    cols = st.columns(len(m["allocation"]))
    for col, (dim, buckets) in zip(cols, m["allocation"].items()):
        with col:
            st.caption(dim)
            adf = pd.DataFrame(buckets)[["bucket", "weight_pct"]]
            adf.columns = ["Bucket", "%"]
            st.dataframe(adf, use_container_width=True, hide_index=True)

# --- Frais ---
st.divider()
f = m["fees"]
st.subheader("Frais")
fc1, fc2 = st.columns(2)
fc1.metric("TER moyen pondéré", f"{f['weighted_ter_pct']} %/an",
           help="Frais courants des supports, pondérés par leur valeur.")
fc2.metric("Coût composé 15 ans", f"{f['drag_15y_eur']:,.0f} €".replace(",", " "),
           help="Ce que les frais te coûtent, capitalisés, sur 15 ans.")

conn.close()
