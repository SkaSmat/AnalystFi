"""AnalystFi — chat Streamlit pour ton CGP personnel. S2 : Supabase + interview mode."""
import os
from dotenv import load_dotenv
import streamlit as st
from anthropic import Anthropic

from tools import TOOLS, DISPATCH

load_dotenv()

MODEL = "claude-opus-4-7"

SYSTEM = """Tu es AnalystFi, le gestionnaire de patrimoine personnel de l'utilisateur.

Ton rôle : l'aider à comprendre, optimiser et faire évoluer son patrimoine. L'utilisateur est seul destinataire et seul décideur — tu peux donc être direct, prescriptif, trancher.

Tu disposes d'une mémoire persistante (Supabase) avec :
- positions : le patrimoine détaillé (lire / ajouter / modifier / supprimer)
- objectifs : objectifs et tolérance au risque (lire / écrire)
- profil_fiscal : foyer, TMI, plafonds (lire / écrire)
- memo : décisions et raisonnements passés

# Protocole de démarrage de chaque conversation
1. Lis `lire_objectifs`, `lire_profil_fiscal`, `lire_patrimoine` (en parallèle si possible) **avant** de répondre.
2. Lis aussi `lire_memos` pour reprendre le contexte des sessions précédentes.
3. Si les objectifs ou le profil fiscal sont vides ou incomplets, **bascule en mode interview** : pose des questions ciblées, propose un brouillon structuré, fais valider, puis appelle `ecrire_objectifs` / `ecrire_profil_fiscal`.

# Mode interview (quand un fichier est vide)
- Pose 2-3 questions à la fois maximum, jamais un questionnaire entier.
- Propose des défaults raisonnables ("à ton âge / TMI / situation, on voit souvent X").
- Sois pédagogique : explique pourquoi telle info compte (ex : la TMI détermine si le PER est intéressant).
- Quand tu as assez d'éléments, **résume le profil proposé** et demande "je l'enregistre ?". Si oui, appelle l'outil d'écriture.

# Mise à jour du patrimoine
- Si l'utilisateur mentionne une nouvelle position ("j'ai aussi 5k sur tel livret"), propose `ajouter_position` après confirmation.
- Si un montant a changé, propose `modifier_position`.
- Pour une dette : `montant_eur` négatif. Mets le taux d'intérêt dans `notes`, pas dans `frais_annuels_pct`.

# Mémoire long terme
- Après une décision importante ("je vais verser 5k sur mon PER avant le 31/12"), appelle `ajouter_memo(type='decision', contenu='...')`.
- Après un raisonnement non trivial (arbitrage, choix d'enveloppe), appelle `ajouter_memo(type='raisonnement', ...)`.

# Règles fiscales
- Sur les calculs fiscaux exacts (IR, PFU, IFI), précise que c'est une estimation tant qu'OpenFisca n'est pas branché (S3). Reste qualitatif sur les chiffres précis ; quantitatif quand c'est trivial (ex : économie PER ≈ versement × TMI).
- Date toujours tes raisonnements : "selon les règles connues début 2026...".

# Style
- Direct, opérationnel, sans gras inutile.
- Pour une reco : Constat → Options → Reco → Pourquoi → Risques.
- Cite toujours d'où viennent les chiffres (tools, jamais d'invention).
"""


def get_secret(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val:
        return val
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def check_password() -> bool:
    expected = get_secret("APP_PASSWORD")
    if not expected:
        return True
    if st.session_state.get("auth_ok"):
        return True
    pwd = st.text_input("Mot de passe", type="password")
    if pwd and pwd == expected:
        st.session_state.auth_ok = True
        st.rerun()
    elif pwd:
        st.error("Mot de passe incorrect.")
    return False


def setup_env() -> list:
    missing = []
    for key in ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
        val = get_secret(key)
        if not val:
            missing.append(key)
        else:
            os.environ[key] = val
    return missing


def run_agent(messages: list) -> str:
    client = Anthropic()
    while True:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        if resp.stop_reason == "tool_use":
            assistant_blocks = [b.model_dump() for b in resp.content]
            messages.append({"role": "assistant", "content": assistant_blocks})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    try:
                        result = DISPATCH[block.name](**(block.input or {}))
                    except Exception as e:
                        result = f"Erreur tool {block.name} : {e}"
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})
            messages.append({"role": "user", "content": tool_results})
            continue
        text = "".join(b.text for b in resp.content if b.type == "text")
        messages.append({"role": "assistant", "content": text})
        return text


st.set_page_config(page_title="AnalystFi", page_icon="💼", layout="wide")
st.title("💼 AnalystFi — ton CGP personnel")

if not check_password():
    st.stop()

missing = setup_env()
if missing:
    st.error(
        "Secrets manquants : " + ", ".join(missing) + "\n\n"
        "Va dans Streamlit Cloud → Settings → Secrets et ajoute :\n\n"
        "```toml\n"
        "ANTHROPIC_API_KEY = \"sk-ant-...\"\n"
        "SUPABASE_URL = \"https://xxxx.supabase.co\"\n"
        "SUPABASE_KEY = \"eyJ...\"\n"
        "```"
    )
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    if isinstance(msg["content"], str):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

prompt = st.chat_input("Pose ta question patrimoniale…")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Analyse en cours…"):
            answer = run_agent(st.session_state.messages)
        st.markdown(answer)

with st.sidebar:
    st.header("Suggestions")
    st.markdown(
        "- Aide-moi à définir mes objectifs\n"
        "- Aide-moi à remplir mon profil fiscal\n"
        "- Fais le point sur mon allocation\n"
        "- Quels déséquilibres dans mon patrimoine ?\n"
        "- Que ferais-tu de 10 000 € supplémentaires ?\n"
        "- Quelles optimisations pour la fin d'année ?"
    )
    if st.button("Réinitialiser la conversation"):
        st.session_state.messages = []
        st.rerun()
