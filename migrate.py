"""Migration one-shot : CSV → Supabase.

Usage local :
    pip install -r requirements.txt
    export SUPABASE_URL=...
    export SUPABASE_KEY=...
    python migrate.py

Lit data/patrimoine.csv et insère dans la table positions.
À lancer une seule fois après avoir créé le schéma.
"""
import os
import sys
from pathlib import Path
import pandas as pd
from supabase import create_client


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not (url and key):
        sys.exit("Définis SUPABASE_URL et SUPABASE_KEY dans l'environnement.")

    sb = create_client(url, key)
    csv_path = Path(__file__).parent / "data" / "patrimoine.csv"
    df = pd.read_csv(csv_path).fillna("")

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "categorie": r["categorie"],
            "enveloppe": r["enveloppe"],
            "etablissement": r["etablissement"] or None,
            "libelle": r["libelle"] or r["enveloppe"],
            "montant_eur": float(r["montant_eur"]),
            "date_ouverture": r["date_ouverture"] or None,
            "support": r["support"] or None,
            "frais_annuels_pct": float(r["frais_annuels_pct"] or 0),
            "notes": r["notes"] or None,
        })

    existing = sb.table("positions").select("id", count="exact").execute()
    if existing.count and existing.count > 0:
        print(f"⚠️  {existing.count} position(s) déjà en base. Migration annulée pour éviter les doublons.")
        print("   Vide la table d'abord (delete from positions;) ou ignore ce script.")
        sys.exit(1)

    sb.table("positions").insert(rows).execute()
    print(f"✅ {len(rows)} positions importées.")


if __name__ == "__main__":
    main()
