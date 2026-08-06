"""Couche conseil — le LLM INTERPRÈTE, il ne calcule jamais.

Reçoit le JSON produit par les moteurs déterministes (engine + risk +
projections) et rend : hiérarchisation des alertes, contre-argument, idées
d'investissement cadrées. Aucun chiffre n'est inventé : ils viennent tous du JSON.

Nécessite une clé Anthropic (ANTHROPIC_API_KEY). Sans clé, l'app reste
pleinement fonctionnelle sur toute la partie déterministe.
"""
from __future__ import annotations

import json
import os

DEFAULT_MODEL = os.getenv("ANALYSTFI_MODEL", "claude-sonnet-5")

SYSTEM = """Tu es le gestionnaire de patrimoine personnel de l'utilisateur, seul \
destinataire et seul décideur. Tu reçois un JSON de métriques calculées par un \
moteur déterministe (patrimoine net, allocation, concentration, risque/MCTR, \
stress tests, projection Monte Carlo).

Règles absolues :
- Tu ne calcules JAMAIS et tu n'inventes AUCUN chiffre. Tous les nombres que tu \
cites viennent du JSON. Si une donnée manque, dis-le, ne l'estime pas.
- Tu interprètes, tu hiérarchises, tu formules le contre-argument. C'est ce qu'un \
tableur ne fait pas.
- Structure : (1) les 3 risques prioritaires, dans l'ordre ; (2) pour chacun, \
l'action concrète et le contre-argument ; (3) idées d'investissement cadrées, \
cohérentes avec les enveloppes disponibles et la fiscalité française (PEA >5 ans, \
PEE, PFU crypto 30 %) ; (4) une phrase de prudence.
- Direct, opérationnel, chiffré à partir du JSON. Pas de disclaimer juridique long.
- Rappelle une fois que ce n'est pas un conseil réglementé, brièvement.
- Réponds en français."""


def advise(payload: dict, api_key: str | None = None, model: str | None = None) -> str:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return ("_(Couche conseil désactivée : renseigne une clé Anthropic pour "
                "obtenir la lecture priorisée et les idées d'invest. Toute l'analyse "
                "chiffrée ci-dessus reste valable sans clé.)_")
    from anthropic import Anthropic

    client = Anthropic(api_key=key)
    resp = client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=1500,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": "Voici mes métriques patrimoniales. Donne-moi ta lecture.\n\n"
                       + json.dumps(payload, ensure_ascii=False, indent=2),
        }],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
