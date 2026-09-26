"""SBB package data (source: sbb.ch/de/angebote/halbtax-plus).

Each PLUS package: you deposit `deposit`, receive `bonus` for free, and can
spend `deposit + bonus` in total over the one-year term.
"""

# Halbtax subscription fee, paid on top of any PLUS deposit (sbb.ch).
HALBTAX_COST = 185.0

# GA (Generalabonnement) 2nd class, adult (source: sbb.ch). Flat cost that
# covers (almost) all public transport in Switzerland - replaces the Halbtax
# subscription entirely.
GA_OPTIONS: list[dict] = [
    {"name": "GA annual", "cost": 3998.0},
    {"name": "GA monthly", "cost": 350.0 * 12},
]

PACKAGES: dict[str, list[dict]] = {
    "adult": [
        {"name": "PLUS 1000", "deposit": 800, "bonus": 200},
        {"name": "PLUS 2000", "deposit": 1500, "bonus": 500},
        {"name": "PLUS 3000", "deposit": 2100, "bonus": 900},
    ],
    # Under 25: much better bonus rates (600 -> 1000 etc.)
    "youth": [
        {"name": "Youth 1000", "deposit": 600, "bonus": 400},
        {"name": "Youth 2000", "deposit": 1125, "bonus": 875},
        {"name": "Youth 3000", "deposit": 1575, "bonus": 1425},
    ],
}
