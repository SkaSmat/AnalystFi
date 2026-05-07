# AnalystFi — Mon CGP personnel

Assistant patrimonial personnel basé sur Claude + Supabase. MVP mono-utilisateur.

## Architecture (S2)

- **Streamlit Cloud** : interface chat
- **Claude (Anthropic)** : agent + tool use
- **Supabase Postgres** : mémoire persistante (patrimoine, objectifs, profil fiscal, mémo)

## Setup Supabase (une fois)

1. Créer un projet sur https://supabase.com (region Frankfurt)
2. SQL Editor → coller `db/schema.sql` → Run
3. Project Settings → API : récupérer `URL` et `service_role key`

## Setup Streamlit Cloud

Settings → Secrets :
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
APP_PASSWORD = "un-mot-de-passe-fort"
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_KEY = "eyJ..."  # service_role
```

## Migration des données CSV existantes (optionnel, une fois)

```bash
export SUPABASE_URL=...
export SUPABASE_KEY=...
python migrate.py
```

## Tools disposés par l'agent

- `lire_patrimoine`, `ajouter_position`, `modifier_position`, `supprimer_position`
- `lire_objectifs`, `ecrire_objectifs`
- `lire_profil_fiscal`, `ecrire_profil_fiscal`
- `ajouter_memo`, `lire_memos`

## Roadmap

- [x] S1 : socle Streamlit + tools lecture (CSV)
- [x] S2 : Supabase + tools écriture + mode interview
- [ ] S3 : OpenFisca branché pour calculs fiscaux exacts
- [ ] S4 : RAG BOFiP + Légifrance daté
