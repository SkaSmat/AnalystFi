"""Tools exposés à l'agent Claude. S2 : lecture + écriture via Supabase."""
import os
from datetime import datetime
from supabase import create_client, Client


def _client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def _fmt_eur(n: float) -> str:
    return f"{n:,.0f} €".replace(",", " ")


# ---------- Patrimoine (positions) ----------

def lire_patrimoine() -> str:
    sb = _client()
    rows = sb.table("positions").select("*").order("categorie").execute().data
    if not rows:
        return "Aucune position enregistrée. Demande à l'utilisateur ses comptes/contrats et utilise `ajouter_position` pour les saisir."
    actif = sum(float(r["montant_eur"]) for r in rows if float(r["montant_eur"]) > 0)
    passif = -sum(float(r["montant_eur"]) for r in rows if float(r["montant_eur"]) < 0)
    net = actif - passif
    head = (
        f"Patrimoine brut : {_fmt_eur(actif)} | "
        f"Passif : {_fmt_eur(passif)} | "
        f"Patrimoine net : {_fmt_eur(net)}\n\n"
    )
    cols = ["id", "categorie", "enveloppe", "etablissement", "libelle", "montant_eur", "date_ouverture", "support", "frais_annuels_pct", "notes"]
    table = "| " + " | ".join(cols) + " |\n"
    table += "|" + "|".join(["---"] * len(cols)) + "|\n"
    for r in rows:
        table += "| " + " | ".join(str(r.get(c, "") or "") for c in cols) + " |\n"
    return head + table


def ajouter_position(
    categorie: str,
    enveloppe: str,
    libelle: str,
    montant_eur: float,
    etablissement: str = "",
    date_ouverture: str = "",
    support: str = "",
    frais_annuels_pct: float = 0,
    notes: str = "",
) -> str:
    sb = _client()
    payload = {
        "categorie": categorie,
        "enveloppe": enveloppe,
        "libelle": libelle,
        "montant_eur": montant_eur,
        "etablissement": etablissement or None,
        "date_ouverture": date_ouverture or None,
        "support": support or None,
        "frais_annuels_pct": frais_annuels_pct,
        "notes": notes or None,
    }
    res = sb.table("positions").insert(payload).execute().data
    return f"Position ajoutée (id={res[0]['id']}) : {libelle} {_fmt_eur(montant_eur)}."


def modifier_position(id: str, **champs) -> str:
    if not champs:
        return "Aucun champ à modifier."
    sb = _client()
    champs["updated_at"] = datetime.utcnow().isoformat()
    res = sb.table("positions").update(champs).eq("id", id).execute().data
    if not res:
        return f"Aucune position trouvée avec id={id}."
    return f"Position {id} mise à jour : {list(champs.keys())}."


def supprimer_position(id: str) -> str:
    sb = _client()
    res = sb.table("positions").delete().eq("id", id).execute().data
    if not res:
        return f"Aucune position trouvée avec id={id}."
    return f"Position {id} supprimée."


# ---------- Objectifs ----------

def lire_objectifs() -> str:
    sb = _client()
    row = sb.table("objectifs").select("contenu_md, updated_at").eq("id", 1).execute().data
    contenu = (row[0]["contenu_md"] if row else "").strip()
    if not contenu:
        return "Aucun objectif enregistré. Lance le mode interview : pose des questions à l'utilisateur (âge, situation, horizon, priorités, tolérance risque, contraintes), puis appelle `ecrire_objectifs` avec un markdown structuré."
    return contenu


def ecrire_objectifs(contenu_md: str) -> str:
    sb = _client()
    sb.table("objectifs").update({
        "contenu_md": contenu_md,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", 1).execute()
    return "Objectifs enregistrés."


# ---------- Profil fiscal ----------

def lire_profil_fiscal() -> str:
    sb = _client()
    row = sb.table("profil_fiscal").select("contenu_md").eq("id", 1).execute().data
    contenu = (row[0]["contenu_md"] if row else "").strip()
    if not contenu:
        return "Aucun profil fiscal enregistré. Lance le mode interview : foyer, parts, revenu net imposable, TMI, IFI, plafond PER, dispositifs en cours. Puis appelle `ecrire_profil_fiscal`."
    return contenu


def ecrire_profil_fiscal(contenu_md: str) -> str:
    sb = _client()
    sb.table("profil_fiscal").update({
        "contenu_md": contenu_md,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", 1).execute()
    return "Profil fiscal enregistré."


# ---------- Mémo (mémoire long terme) ----------

def ajouter_memo(type: str, contenu: str) -> str:
    sb = _client()
    sb.table("memo").insert({"type": type, "contenu": contenu}).execute()
    return f"Mémo {type} enregistré."


def lire_memos(limite: int = 50) -> str:
    sb = _client()
    rows = sb.table("memo").select("*").order("created_at", desc=True).limit(limite).execute().data
    if not rows:
        return "Aucun mémo."
    return "\n".join(f"[{r['created_at'][:10]}] ({r['type']}) {r['contenu']}" for r in rows)


# ---------- Schemas pour Claude ----------

TOOLS = [
    {"name": "lire_patrimoine", "description": "Renvoie toutes les positions du patrimoine (tableau + résumé brut/passif/net).", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "ajouter_position", "description": "Ajoute une nouvelle position. Pour une dette (crédit), montant_eur doit être négatif.", "input_schema": {"type": "object", "properties": {
        "categorie": {"type": "string", "description": "liquidites | epargne_lt | marches | immobilier | credits | autre"},
        "enveloppe": {"type": "string", "description": "livret_a, ldds, compte_courant, assurance_vie, per, pea, pee, cto, scpi, residence_principale, locatif, pret_immo, crypto, ..."},
        "libelle": {"type": "string"},
        "montant_eur": {"type": "number"},
        "etablissement": {"type": "string"},
        "date_ouverture": {"type": "string", "description": "AAAA-MM-JJ"},
        "support": {"type": "string"},
        "frais_annuels_pct": {"type": "number"},
        "notes": {"type": "string"}
    }, "required": ["categorie", "enveloppe", "libelle", "montant_eur"]}},
    {"name": "modifier_position", "description": "Modifie une position existante (par id).", "input_schema": {"type": "object", "properties": {
        "id": {"type": "string"},
        "categorie": {"type": "string"},
        "enveloppe": {"type": "string"},
        "libelle": {"type": "string"},
        "montant_eur": {"type": "number"},
        "etablissement": {"type": "string"},
        "date_ouverture": {"type": "string"},
        "support": {"type": "string"},
        "frais_annuels_pct": {"type": "number"},
        "notes": {"type": "string"}
    }, "required": ["id"]}},
    {"name": "supprimer_position", "description": "Supprime une position. Demande confirmation à l'utilisateur avant.", "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "lire_objectifs", "description": "Lit les objectifs patrimoniaux (markdown).", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "ecrire_objectifs", "description": "Écrit/remplace le bloc objectifs (markdown structuré). À utiliser après avoir interviewé l'utilisateur.", "input_schema": {"type": "object", "properties": {"contenu_md": {"type": "string"}}, "required": ["contenu_md"]}},
    {"name": "lire_profil_fiscal", "description": "Lit le profil fiscal (markdown).", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "ecrire_profil_fiscal", "description": "Écrit/remplace le profil fiscal (markdown structuré).", "input_schema": {"type": "object", "properties": {"contenu_md": {"type": "string"}}, "required": ["contenu_md"]}},
    {"name": "ajouter_memo", "description": "Note une décision, alerte ou raisonnement à retenir pour les sessions futures (mémoire long terme).", "input_schema": {"type": "object", "properties": {"type": {"type": "string", "description": "decision | alerte | raisonnement | preference"}, "contenu": {"type": "string"}}, "required": ["type", "contenu"]}},
    {"name": "lire_memos", "description": "Renvoie les derniers mémos pour reprendre le contexte d'une session.", "input_schema": {"type": "object", "properties": {"limite": {"type": "integer"}}, "required": []}},
]

DISPATCH = {
    "lire_patrimoine": lambda **_: lire_patrimoine(),
    "ajouter_position": lambda **kw: ajouter_position(**kw),
    "modifier_position": lambda **kw: modifier_position(**kw),
    "supprimer_position": lambda **kw: supprimer_position(**kw),
    "lire_objectifs": lambda **_: lire_objectifs(),
    "ecrire_objectifs": lambda **kw: ecrire_objectifs(**kw),
    "lire_profil_fiscal": lambda **_: lire_profil_fiscal(),
    "ecrire_profil_fiscal": lambda **kw: ecrire_profil_fiscal(**kw),
    "ajouter_memo": lambda **kw: ajouter_memo(**kw),
    "lire_memos": lambda **kw: lire_memos(**kw),
}
