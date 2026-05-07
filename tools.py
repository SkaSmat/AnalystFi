"""Tools exposés à l'agent Claude. Semaine 1 : lecture seule du patrimoine."""
from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"


def lire_patrimoine() -> str:
    df = pd.read_csv(DATA_DIR / "patrimoine.csv")
    total_actif = df.loc[df["montant_eur"] > 0, "montant_eur"].sum()
    total_passif = -df.loc[df["montant_eur"] < 0, "montant_eur"].sum()
    net = total_actif - total_passif
    resume = (
        f"Patrimoine brut : {total_actif:,.0f} € | "
        f"Passif : {total_passif:,.0f} € | "
        f"Patrimoine net : {net:,.0f} €\n\n"
    )
    return resume + df.to_markdown(index=False)


def lire_objectifs() -> str:
    return (DATA_DIR / "objectifs.md").read_text(encoding="utf-8")


def lire_profil_fiscal() -> str:
    return (DATA_DIR / "profil_fiscal.md").read_text(encoding="utf-8")


TOOLS = [
    {
        "name": "lire_patrimoine",
        "description": "Renvoie le patrimoine complet de l'utilisateur (positions, montants, dates, supports) au format tableau, plus un résumé brut/passif/net.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "lire_objectifs",
        "description": "Renvoie les objectifs patrimoniaux, l'horizon, la tolérance au risque et les décisions historiques.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "lire_profil_fiscal",
        "description": "Renvoie le profil fiscal : foyer, parts, TMI, plafonds PER, situation IFI.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

DISPATCH = {
    "lire_patrimoine": lambda **_: lire_patrimoine(),
    "lire_objectifs": lambda **_: lire_objectifs(),
    "lire_profil_fiscal": lambda **_: lire_profil_fiscal(),
}
