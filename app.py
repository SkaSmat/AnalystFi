"""AnalystFi — analyseur patrimonial stateless.

    pip install -r requirements.txt
    streamlit run app.py

Tu poses tes chiffres (tableau éditable, tu ajoutes autant de lignes que tu veux),
tu cliques « Analyser » → lecture complète : net, allocation, concentration,
risque, projection FIRE, idées d'invest. Rien n'est stocké : tout vit le temps
de la session. Ton Excel reste ta source de vérité.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analystfi import advise, build, engine, projections, prices, risk

st.set_page_config(page_title="AnalystFi", page_icon="💼", layout="wide")
st.title("💼 AnalystFi")
st.caption("Pose tes chiffres → lecture complète. Rien n'est enregistré : ton Excel reste la source de vérité.")

CATEGORIES = ["Actions", "ETF", "Crypto", "Obligations", "Liquidités",
              "Immobilier", "Crédit (passif)", "Autre"]
ENVELOPPES = ["PEA", "PEA-PME", "CTO", "PEE/PER", "PER", "Assurance-vie",
              "Livret", "Wallet crypto", "Immo", "Autre"]

# ---------- Saisie ----------
st.subheader("1. Tes lignes")
st.caption("Édite les montants, ajoute/supprime des lignes (bouton + en bas). "
           "« Symbole » = ticker Yahoo (FGR.PA) ou id CoinGecko (bitcoin) — sert au calcul de risque.")

if "rows" not in st.session_state:
    st.session_state.rows = pd.DataFrame(build.default_rows())

edited = st.data_editor(
    st.session_state.rows,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "categorie": st.column_config.SelectboxColumn("Catégorie", options=CATEGORIES, required=True),
        "libelle": st.column_config.TextColumn("Libellé", required=True),
        "enveloppe": st.column_config.SelectboxColumn("Enveloppe", options=ENVELOPPES),
        "montant": st.column_config.NumberColumn("Montant (€)", format="%.2f"),
        "devise": st.column_config.SelectboxColumn("Devise", options=["EUR", "USD", "GBP", "CHF"]),
        "symbole": st.column_config.TextColumn("Symbole (prix)"),
        "employeur": st.column_config.CheckboxColumn("Employeur ?"),
        "taux": st.column_config.NumberColumn("Taux % (crédit)", format="%.2f"),
    },
)

# ---------- Paramètres ----------
with st.sidebar:
    st.header("Paramètres")
    include_rp = st.toggle("Inclure la résidence principale", value=True)
    st.divider()
    st.caption("**Projection FIRE**")
    monthly = st.number_input("Versement mensuel (€)", value=1500, step=100)
    years_accum = st.slider("Horizon d'accumulation (ans)", 1, 40, 15)
    annual_spend = st.number_input("Dépense annuelle en retraite (€)", value=35000, step=1000)
    years_retire = st.slider("Durée de retraite à financer (ans)", 10, 50, 35)
    st.divider()
    with_risk = st.toggle("Analyse de risque (récupère l'historique en ligne)", value=True)
    st.caption("**Conseil (optionnel)**")
    api_key = st.text_input("Clé Anthropic", type="password",
                            help="Pour la lecture priorisée + idées d'invest. Non stockée.")

go = st.button("📊 Analyser", type="primary", use_container_width=True)

if not go:
    st.info("Ajuste tes lignes puis clique **Analyser**.")
    st.stop()

rows = edited.to_dict("records")
conn = build.build(rows)
m = engine.compute_metrics(conn)

# ---------- Patrimoine net ----------
st.subheader("2. Patrimoine net")
nw = m["net_worth"]
immo_net = nw["real_estate"] - nw["liabilities"]
total = nw["net_worth"] if include_rp else nw["financial_assets"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Financier", f"{nw['financial_assets']:,.0f} €".replace(",", " "))
c2.metric("Immo net", f"{immo_net:,.0f} €".replace(",", " "),
          help=f"Bien {nw['real_estate']:,.0f} − crédit {nw['liabilities']:,.0f}".replace(",", " "))
c3.metric("Passif", f"− {nw['liabilities']:,.0f} €".replace(",", " "))
c4.metric("NET" + ("" if include_rp else " (hors RP)"), f"{total:,.0f} €".replace(",", " "))

# ---------- Alertes ----------
if m["alerts"]:
    st.subheader("Alertes")
    for a in m["alerts"]:
        {"high": st.error, "medium": st.warning, "info": st.info}[a["level"]](a["message"])

# ---------- Concentration & Allocation ----------
st.subheader("3. Allocation & concentration")
col1, col2 = st.columns([2, 1])
with col1:
    for dim, buckets in m["allocation"].items():
        st.caption(dim)
        adf = pd.DataFrame(buckets)[["bucket", "weight_pct"]]
        adf.columns = ["Bucket", "%"]
        st.dataframe(adf, use_container_width=True, hide_index=True)
with col2:
    c = m["concentration"]
    st.metric("Titre employeur", f"{c['employer_weight_pct']} %")
    st.metric("Top-5", f"{c['top5_weight_pct']} %")
    st.metric("Lignes (équiv. diversifié)", f"{c['n_positions']} ({c['effective_positions']})")

# ---------- Risque ----------
st.subheader("4. Risque")
rk = {"available": False, "reason": "désactivé"}
if with_risk:
    with st.spinner("Récupération de l'historique et calcul du risque…"):
        try:
            prices.refresh_history(conn)
            rk = risk.compute_risk(conn)
        except Exception as e:  # noqa: BLE001
            rk = {"available": False, "reason": str(e)}
if rk.get("available"):
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Volatilité annualisée", f"{rk['portfolio_vol_pct']} %")
    rc2.metric("Max drawdown (alloc.)", f"{rk['max_drawdown_pct']} %")
    rc3.metric("Couverture", f"{rk['coverage_pct']} %")
    st.caption("Poids vs contribution au **risque**")
    st.dataframe(pd.DataFrame([
        {"Poche": k, "Poids %": v["weight_pct"], "Risque %": v["risk_contribution_pct"]}
        for k, v in rk["risk_by_class"].items()
    ]), use_container_width=True, hide_index=True)
    for a, b, cc in rk.get("employer_correlation", []):
        st.caption(f"Corrélation {a} ↔ {b} : **{cc}**")
    st.caption("Stress tests (sur actifs financiers)")
    st.dataframe(pd.DataFrame([
        {"Scénario": k, "Impact %": v["impact_pct"], "Impact €": v["impact_eur"], "Après €": v["after_eur"]}
        for k, v in rk["stress_tests"].items()
    ]), use_container_width=True, hide_index=True)
else:
    st.info(f"Risque indisponible : {rk.get('reason')}")

# ---------- Projection ----------
st.subheader("5. Projection FIRE (Monte Carlo)")
proj = projections.simulate(conn, {
    "start": nw["financial_assets"], "monthly": monthly, "years_accum": years_accum,
    "years_retire": years_retire, "annual_spend": annual_spend, "n": 5000,
})
pa = proj["assumptions"]
st.caption(f"Hypothèses : rendement réel {pa['mu_pct']} %/an, vol {pa['sigma_pct']} % "
           f"(déduits de ton allocation).")
pc1, pc2, pc3 = st.columns(3)
pc1.metric("Dans " + str(years_accum) + " ans — pessimiste (p10)", f"{proj['terminal']['p10']:,.0f} €".replace(",", " "))
pc2.metric("médian (p50)", f"{proj['terminal']['p50']:,.0f} €".replace(",", " "))
pc3.metric("favorable (p90)", f"{proj['terminal']['p90']:,.0f} €".replace(",", " "))
if proj["fire"]:
    sr = proj["fire"]["success_rate_pct"]
    st.metric(f"Probabilité de tenir {years_retire} ans à {annual_spend:,.0f} €/an".replace(",", " "),
              f"{sr:.0f} %", help="Intègre le risque de séquence (rendements tirés année par année).")
chart = pd.DataFrame({"p10": proj["p10_path"], "médian": proj["median_path"], "p90": proj["p90_path"]})
st.line_chart(chart)

# ---------- Conseil ----------
st.subheader("6. Lecture & idées d'invest")
payload = {"net_worth": m["net_worth"], "concentration": m["concentration"],
           "allocation": m["allocation"], "alerts": m["alerts"], "fees": m["fees"],
           "risk": {k: rk[k] for k in ("portfolio_vol_pct", "risk_by_class", "stress_tests")
                    if k in rk} if rk.get("available") else None,
           "projection": {"terminal": proj["terminal"], "fire": proj["fire"]}}
with st.spinner("Lecture en cours…"):
    st.markdown(advise.advise(payload, api_key=api_key or None))

conn.close()
