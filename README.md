# AnalystFi — Mon CGP personnel

Assistant patrimonial personnel basé sur Claude. MVP mono-utilisateur.

## Semaine 1 — Socle

- `data/patrimoine.csv` : tes positions (à remplir)
- `data/objectifs.md` : tes objectifs patrimoniaux (à remplir)
- `data/profil_fiscal.md` : foyer fiscal, TMI, parts (à remplir)
- `app.py` : chat Streamlit branché sur Claude
- `tools.py` : tools exposés à l'agent

## Setup local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

## Déploiement Streamlit Cloud

1. https://share.streamlit.io → Sign in with GitHub
2. New app → repo `skasmat/analystfi` → branche `claude/asset-manager-design-jrRUh` → main file `app.py`
3. Advanced settings → Secrets :
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
4. Deploy.

## Roadmap

- S1 : socle conversationnel + lecture patrimoine (ici)
- S2 : OpenFisca en tool use (calculs fiscaux exacts)
- S3 : RAG BOFiP + Légifrance daté
- S4 : mémoire long terme SQLite
