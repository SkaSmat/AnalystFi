"""AnalystFi — analyseur patrimonial stateless.

    pip install -r requirements.txt
    streamlit run app.py

Saisie organisée en POCHES (Actions, Crypto, PEE…), chacune avec son taux
d'impôt et sa liste de lignes. Tu cliques « Analyser » → lecture complète
(net, allocation, concentration, risque, fiscalité brut/net, projection FIRE,
idées d'invest). Rien n'est stocké : ton Excel reste la source de vérité.
"""
from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

from analystfi import advise, build, engine, projections, prices, risk, tax

st.set_page_config(page_title="AnalystFi", page_icon="💼", layout="wide")
st.title("💼 AnalystFi")
st.caption("Pose tes chiffres par poche → lecture complète. Rien n'est enregistré.")

POCHE_CLASSES = ["Actions", "ETF", "Crypto", "Obligations", "Liquidités", "Autre"]
POCHE_ENV = ["PEA", "PEA-PME", "CTO", "PEE/PER", "PER", "Assurance-vie", "Livret", "Wallet crypto", "Autre"]
LINE_COLS = ["libelle", "montant", "cost", "devise", "symbole", "employeur"]
COL_CONFIG = {
    "libelle": st.column_config.TextColumn("Libellé", required=True),
    "montant": st.column_config.NumberColumn("Montant (€)", format="%.2f"),
    "cost": st.column_config.NumberColumn("Coût (€)", format="%.2f",
                                          help="Prix de revient — sert à l'impôt latent. Vide = gain nul."),
    "devise": st.column_config.SelectboxColumn("Devise", options=["EUR", "USD", "GBP", "CHF"]),
    "symbole": st.column_config.TextColumn("Symbole (prix)",
                                           help="Ticker Yahoo (FGR.PA) ou id CoinGecko (bitcoin) — pour le risque."),
    "employeur": st.column_config.CheckboxColumn("Employeur ?"),
}

# --- état initial ---
if "pockets" not in st.session_state:
    ps = build.default_pockets()
    for p in ps:
        p["id"] = uuid.uuid4().hex[:8]
    st.session_state.pockets = ps
    st.session_state.immo = build.default_immo()

# ---------- Saisie par poche ----------
st.subheader("1. Tes poches")
current_pockets = []
for p in st.session_state.pockets:
    with st.container(border=True):
        h1, h2, h3 = st.columns([5, 2, 1])
        h1.markdown(f"**{p['nom']}**  ·  _{p['classe']} / {p['enveloppe']}_")
        taux = h2.number_input("Impôt latent %", value=float(p.get("taux") or 0), step=0.1,
                               key=f"t_{p['id']}")
        if h3.button("🗑", key=f"del_{p['id']}", help="Supprimer la poche"):
            st.session_state.pockets = [x for x in st.session_state.pockets if x["id"] != p["id"]]
            st.rerun()
        df = pd.DataFrame(p["lignes"] or [{c: ("" if c != "employeur" else False) for c in LINE_COLS}],
                          columns=LINE_COLS)
        edited = st.data_editor(df, num_rows="dynamic", use_container_width=True,
                                hide_index=True, column_config=COL_CONFIG, key=f"e_{p['id']}")
        current_pockets.append({**p, "taux": taux, "lignes": edited.to_dict("records")})

with st.expander("➕ Ajouter une poche"):
    a1, a2, a3, a4 = st.columns(4)
    new_nom = a1.text_input("Nom", key="np_nom")
    new_cls = a2.selectbox("Classe", POCHE_CLASSES, key="np_cls")
    new_env = a3.selectbox("Enveloppe", POCHE_ENV, key="np_env")
    new_tx = a4.number_input("Impôt %", value=30.0, step=0.1, key="np_tx")
    if st.button("Ajouter") and new_nom.strip():
        st.session_state.pockets.append({
            "id": uuid.uuid4().hex[:8], "nom": new_nom.strip(), "classe": new_cls,
            "enveloppe": new_env, "taux": new_tx,
            "lignes": [{c: ("" if c != "employeur" else False) for c in LINE_COLS}],
        })
        st.rerun()

# ---------- Immobilier & passif ----------
with st.container(border=True):
    st.markdown("**🏠 Immobilier & passif**")
    im = st.session_state.immo
    i1, i2, i3 = st.columns(3)
    rp_val = i1.number_input("Résidence principale — valeur (€)", value=float(im["rp_valeur"]), step=1000.0)
    crd = i2.number_input("Crédit — capital restant dû (€)", value=float(im["credit_crd"]), step=1000.0)
    taux_credit = i3.number_input("Crédit — taux %", value=float(im["credit_taux"]), step=0.05)
immo = {"rp_nom": "Résidence principale", "rp_valeur": rp_val,
        "credit_nom": "Crédit RP", "credit_crd": crd, "credit_taux": taux_credit}

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
    api_key = st.text_input("Clé Anthropic", type="password", help="Non stockée.")

if not st.button("📊 Analyser", type="primary", use_container_width=True):
    st.info("Ajuste tes poches puis clique **Analyser**.")
    st.stop()

conn = build.build_pockets(current_pockets, immo)
m = engine.compute_metrics(conn)
t = tax.latent_tax(conn)

# ---------- Patrimoine net ----------
st.subheader("2. Patrimoine net")
nw = m["net_worth"]
immo_net = nw["real_estate"] - nw["liabilities"]
total = nw["net_worth"] if include_rp else nw["financial_assets"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Financier", f"{nw['financial_assets']:,.0f} €".replace(",", " "))
c2.metric("Immo net", f"{immo_net:,.0f} €".replace(",", " "))
c3.metric("Passif", f"− {nw['liabilities']:,.0f} €".replace(",", " "))
c4.metric("NET" + ("" if include_rp else " (hors RP)"), f"{total:,.0f} €".replace(",", " "))

# ---------- Fiscalité latente ----------
st.subheader("Fiscalité latente — brut vs net")
fc1, fc2, fc3 = st.columns(3)
fc1.metric("Brut (financier)", f"{t['brut']:,.0f} €".replace(",", " "))
fc2.metric("Impôt latent", f"− {t['impot_latent']:,.0f} €".replace(",", " "),
           help=f"Taux moyen {t['taux_moyen_pct']} % sur les plus-values latentes.")
fc3.metric("Net après impôt", f"{t['net']:,.0f} €".replace(",", " "))
gdf = pd.DataFrame(t["groups"])
if not gdf.empty:
    gdf = gdf[["poche", "brut", "gain_net", "taux_pct", "impot_latent", "net"]]
    gdf.columns = ["Poche", "Brut €", "PV nette €", "Taux %", "Impôt €", "Net €"]
    st.dataframe(gdf, use_container_width=True, hide_index=True)
st.caption("Impôt par poche, sur la plus-value NETTE de la poche (une ligne en perte réduit le gain "
           "d'une autre — c'est ce qui rend le crypto-global juste). ⚠️ Estimations, à revalider.")

# ---------- Alertes ----------
if m["alerts"]:
    st.subheader("Alertes")
    for a in m["alerts"]:
        {"high": st.error, "medium": st.warning, "info": st.info}[a["level"]](a["message"])

# ---------- Allocation & concentration ----------
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
st.caption(f"Hypothèses : rendement réel {pa['mu_pct']} %/an, vol {pa['sigma_pct']} % (déduits de ton allocation).")
pc1, pc2, pc3 = st.columns(3)
pc1.metric(f"Dans {years_accum} ans — p10", f"{proj['terminal']['p10']:,.0f} €".replace(",", " "))
pc2.metric("médian (p50)", f"{proj['terminal']['p50']:,.0f} €".replace(",", " "))
pc3.metric("favorable (p90)", f"{proj['terminal']['p90']:,.0f} €".replace(",", " "))
if proj["fire"]:
    st.metric(f"Probabilité de tenir {years_retire} ans à {annual_spend:,.0f} €/an".replace(",", " "),
              f"{proj['fire']['success_rate_pct']:.0f} %",
              help="Intègre le risque de séquence.")
st.line_chart(pd.DataFrame({"p10": proj["p10_path"], "médian": proj["median_path"], "p90": proj["p90_path"]}))

# ---------- Conseil ----------
st.subheader("6. Lecture & idées d'invest")
payload = {"net_worth": m["net_worth"], "concentration": m["concentration"],
           "allocation": m["allocation"], "alerts": m["alerts"], "fees": m["fees"],
           "fiscalite_latente": {"brut": t["brut"], "impot_latent": t["impot_latent"],
                                 "net": t["net"], "par_poche": t["groups"]},
           "risk": {k: rk[k] for k in ("portfolio_vol_pct", "risk_by_class", "stress_tests")
                    if k in rk} if rk.get("available") else None,
           "projection": {"terminal": proj["terminal"], "fire": proj["fire"]}}
with st.spinner("Lecture en cours…"):
    st.markdown(advise.advise(payload, api_key=api_key or None))

conn.close()
