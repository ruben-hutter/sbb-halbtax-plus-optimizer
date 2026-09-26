# SBB Halbtax PLUS: re-buying and switching packages — terms check

**Date:** 2026-09-27 · **Sources:** sbb.ch (official FAQ, fetched live)
**Companion script:** `docs/research/ga-vs-plus-horizon.py` (strategy
comparison this check legalizes)
**Question:** Is re-buying a PLUS package after (partially) using its credit
legal, and may the *next* package be a **different type** (e.g. PLUS 1000
exhausted → buy PLUS 3000)? This gates the "mixed sequences" strategy in the
GA-comparison exploration (companion script referenced in PRs/tests later).

## Verdicts

| Question | Verdict | Source |
|---|---|---|
| Re-buy the same package? | **Allowed** (explicit) | FAQ «Wie kann ich mein Halbtax PLUS-Guthaben wieder aufladen?» |
| Switch to a **different** package type at re-buy? | **Allowed** (explicit "Ja") | FAQ «Ich möchte auf ein anderes Halbtax PLUS-Paket wechseln. Geht das?» |
| Re-buy timing | Allowed **from the start of the bonus phase** (deposit exhausted), not only after full credit use | FAQ, same answers |
| Do old and new package overlap? | Yes — old bonus stays usable until it runs out or expires; the new credit then activates **automatically** | FAQ «Der Bonus des bisherigen Pakets bleibt bis zum Ende der Paket-Gültigkeit verfügbar. …» |

## Key quotes (sbb.ch FAQ, Halbtax PLUS)

Source: <https://www.sbb.ch/de/hilfe-und-kontakt/produkte-services/abos/ga-und-halbtax/halbtax-plus.html>

- «Ich möchte auf ein anderes Halbtax PLUS-Paket wechseln. Geht das?
  **Ja, das ist möglich.** Sobald sich Ihr Guthaben in der Bonus-Phase
  befindet, haben Sie 3 Möglichkeiten, Ihr Halbtax PLUS-Guthaben wieder
  aufzuladen und damit **ein weiteres Halbtax PLUS-Paket zu erwerben**.»
- «Das neue Paket erhält automatisch als ersten Gültigkeitstag (EGT)
  **«heute +1 Tag»** (nicht frei wählbar). … Das neue Paket ist ab diesem
  Zeitpunkt erneut für **maximal 1 Jahr** gültig.»
- «Der Bonus des bisherigen Pakets **bleibt bis zum Ende der Paket-Gültigkeit
  verfügbar**. Sobald der Bonus aufgebraucht oder abgelaufen ist, nutzen Sie
  **automatisch** das neu einbezahlte Guthaben.»
- Contract: «Der Vertrag ist unbefristet gültig» / «…damit Sie Ihr Guthaben zu
  jedem beliebigen späteren Zeitpunkt erneut aufladen können» → no gap between
  packages; each credit is a 1-year term.
- Refunds: unused deposit refunded ~15 days after the last validity day
  («Es erfolgt keine Verrechnung mit der neuen Abonnementsgültigkeit»).

## Modeling implications

1. **Sequential block stacking is the correct abstraction** and is *optimal
   play*: a new package can be bought as soon as the old one is in its bonus
   phase, but since the new package's 1-year clock starts at purchase
   (heute+1) and its credit only activates after the old bonus is used up,
   buying earlier than bonus-exhaustion only wastes validity — never helps.
   So: buy the next package exactly when the current bonus is exhausted →
   the `bonus_topup` sawtooth / mixed-sequence block model.
2. **Mixed sequences (switching types) are legal** — the exploration script's
   `bestmix` strategy is real, not hypothetical.
3. Order of consumption is fixed (deposit → bonus → next package's deposit);
   no choosing which pot to draw from.
4. Unused deposit is refunded after the term even mid-chain; no offsetting
   against the next package.

## Other rules worth remembering

- Personal: tickets only for the holder («Es ist nicht erlaubt, Fahrausweise
  für andere Reisende zu erwerben»).
- Eligible spend: personal single tickets and day cards of national direct
  traffic and tariff associations incl. **Sparwelt**, 1st/2nd class; **not**
  cumulative with other discount models; **no (Spar-)Klassenwechsel**.
- No suspension/«hinterlegen» of validity; contract terminable with 1 month
  to month-end (remaining deposit refunded, bonus forfeited); 10-day
  withdrawal right if credit unused.
- Halbtax subscription is separate and still needed (cost-effectively).

## Gaps

- The formal «AGB Halbtax PLUS» PDF is only shown during checkout
  (SwissPass login) and is not publicly indexed (not in search engines, no
  Wayback snapshot found); the quotes above come from the official FAQ, which
  is sufficient for the switching/re-buy question. If the AGB surface extra
  limits (e.g. max packages per year), revisit before shipping the mix
  feature.
- sbb.ch blocks plain curl (403); a browser User-Agent header works.
