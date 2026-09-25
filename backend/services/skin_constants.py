"""Shared skin/avatar constants. Imported by match_engine, auth_service, and any future skin-related code."""

# All valid avatar skins available for players to choose from.
ALL_SKINS = ["arthur", "dexter", "eloise", "jenny", "kiera", "sadie"]

# Deterministic bot-to-skin mapping for consistent visual identity per bot name.
SKIN_BY_BOT = {
    "NOX": "arthur",
    "ECHO": "dexter",
    "VEIL": "eloise",
    "RAVEN": "jenny",
    "ASH": "kiera",
    "DUSK": "sadie",
}
