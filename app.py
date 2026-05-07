"""AnalystFi — chat Streamlit pour ton CGP personnel."""
import os
from dotenv import load_dotenv
import streamlit as st
from anthropic import Anthropic

from tools import TOOLS, DISPATCH

load_dotenv()

MODEL = "claude-opus-4-7"

SYSTEM = """Tu es AnalystFi, le gestionnaire de patrimoine personnel de l'utilisateur.

Règles non négociables :
1. Avant toute analyse, appelle systématiquement les tools `lire_patrimoine`, `lire_objectifs` et `lire_profil_fiscal` pour charger le contexte. Ne réponds jamais "de mémoire" sur les chiffres de l'utilisateur.
2. Sur les questions fiscales, indique clairement quand une règle dépend de l'année en cours et signale si tu n'es pas certain de la version à jour. Ne donne jamais de chiffre fiscal calculé "à la main" — pour le moment (S1), explique la méthode et dis qu'un calcul exact sera disponible en S2 via OpenFisca.
3. Sois direct et opérationnel : l'utilisateur est seul destinataire, il décide. Tu peux recommander, prioriser, trancher.
4. Quand tu fais une recommandation, structure : Constat → Options → Reco → Pourquoi → Risques.
5. Les chiffres affichés viennent toujours d'un tool, jamais de ton imagination.
"""


def check_password() -> bool:
    expected = os.getenv("APP_PASSWORD") or st.secrets.get("APP_PASSWORD", "")
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
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
            continue
        text = "".join(b.text for b in resp.content if b.type == "text")
        messages.append({"role": "assistant", "content": text})
        return text


st.set_page_config(page_title="AnalystFi", page_icon="💼", layout="wide")
st.title("💼 AnalystFi — ton CGP personnel")

if not check_password():
    st.stop()

if not (os.getenv("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY", "")):
    st.error("Définis ANTHROPIC_API_KEY dans les secrets Streamlit ou un .env.")
    st.stop()

if os.getenv("ANTHROPIC_API_KEY") is None:
    os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]

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
        "- Fais le point sur mon allocation globale\n"
        "- Quels déséquilibres dans mon patrimoine ?\n"
        "- Mes liquidités sont-elles bien dimensionnées ?\n"
        "- Que ferais-tu de 10 000 € supplémentaires ?\n"
        "- Quelles optimisations pour la fin d'année ?"
    )
    if st.button("Réinitialiser la conversation"):
        st.session_state.messages = []
        st.rerun()
