# Ticket price APIs for Swiss public transport (full fare / Halbtax / Sparbillette)

**Date:** 2026-09-27 · **Sources:** official docs + live endpoint calls (curl, from this machine)
**Question:** Is there an API — official or reverse-engineered — returning **official
point-to-point ticket prices** (2nd/1st class, full fare and Halbtax) and ideally
**per-connection Sparbillette (supersaver) offers** for a specific train?

## Verdicts

| Question | Verdict | Source |
|---|---|---|
| Official open-data price API for CH? | **Yes — OJPFare** on opentransportdata.swiss (free key). Prices from **NOVA** (the national fare system), full + **Halbtax** (`EntitlementProduct: HTA`), **Spartickets included when they exist**. Currently integration (test) system, prices "nicht verbindlich" | [cookbook OJP Fare](https://opentransportdata.swiss/cookbook/ojp-fare/), live-probed 401/403 |
| transport.opendata.ch (community wrapper) | **No prices.** `/v1/connections` has timetable + occupancy (`capacity1st/2nd`) only; zero price/fare fields in live response and docs | live call 2026-09-27, [docs](https://transport.opendata.ch/docs.html) |
| transport.search.ch API | **No prices.** Endpoints: completion, route, stationboard, one-to-many; zero price/tarif mentions; needs key (404 without); 1000 route queries/day | [API help](https://search.ch/timetable/api/help) |
| developer.sbb.ch (official) | Exists (APIM portal, Azure-AD registration). Public doc = **Journey-Service** (B2C planner: places/trips/occupancy) — **no fare/price endpoints** | [journey-service repo](https://github.com/SchweizerischeBundesbahnen/journey-service-b2c) |
| Official SBB *sales* API | **B2P API** (`b2p.api.sbb.ch`): `/api/v2/prices?tripIds=…` returns price + **`superSaver: true/false` per trip**. Partner contract + OAuth (401 live-probed). Documented by SBB partner `schlpbch/bookingAPI` (INT host) | live probe; [bookingAPI](https://github.com/schlpbch/bookingAPI) |
| sbb.ch web shop backend | **Undocumented GraphQL `https://graphql.www.sbb.ch/` — works unauthenticated, live-verified**: `trips` → `tripPrices` (full/Halbtax, 1st/2nd) and `tripOffers` (**"Supersaver Ticket" / "Supersaver Ticket Flex" per specific train**, full and Halbtax variants) | live calls below (extracted from sbb.ch JS bundle) |
| SBB Mobile app API | Reverse-engineered timetable `https://active.vnext.app.sbb.ch/api/timetable/v2/trips` **live-verified (HTTP 200)** — timetable only, **no prices** (`ticketingInfo.isAvailable` only) | [sbb-api-rs](https://github.com/denysvitali/sbb-api-rs) + live call |
| Other operators (BLS, SOB, TPF, ZVV), Fairtiq, Omio | **No public price APIs** found (site checks). Their fares run through **NOVA**, i.e. covered by OJPFare — the OJP cookbook even cites a **BLS** product code (Bern–Zweisimmen) | bls.ch/sob.ch/tpf.ch/zvv.ch, fairtiq.com |

---

## 1. Official open data: OJPFare (opentransportdata.swiss) — *the* official source

**What:** SIRI/OJP XML endpoint proxying the **NOVA Preisauskunft** (the system that
actually prices all Swiss PT). Datasets: `ojpfare` (service), `osdm-offline`
(precomputed fares for *international* exchange only), GA/HTA lists.

- **Request:** `POST https://api.opentransportdata.swiss/ojpfare/` — OJP 1.0/2.0
  `OJPFareRequest` XML; header `Authorization: Bearer <API key>` (free registration
  at api-manager.opentransportdata.swiss; could not be completed from this machine →
  not live-verified beyond the auth gate: GET → `403 {"error":"Requested endpoint is
  forbidden"}`, POST without auth → `401 {"error":"Authorization field missing"}`).
- **Trip in, prices out:** you supply a `TripResult` (from an `OJPTripRequest`, which
  the same service accepts), plus params:
  `<ojp:TravelClass>second</ojp:TravelClass>`,
  `<ojp:Traveller>…<ojp:EntitlementProduct>HTA</ojp:EntitlementProduct></ojp:Traveller>`
  — cookbook: *«Ist dieses gesetzt, so werden Halbtax-Preise angegeben, ansonsten der
  volle Preis»*. 1st/2nd both returned.
- **Response (cookbook example, verified format):**
  ```xml
  <ojp:TripFareResult>
    <ojp:FareProduct>
      <ojp:FareProductId>10972</ojp:FareProductId>
      <ojp:Price>2.80</ojp:Price> <ojp:NetPrice>2.58</ojp:NetPrice>
      <ojp:Currency>CHF</ojp:Currency> <ojp:VatRate>7.7</ojp:VatRate>
      <ojp:TravelClass>second</ojp:TravelClass>
    </ojp:FareProduct>
    <!-- ... 4.80 / first ... -->
  </ojp:TripFareResult>
  ```
- **Sparbillette: yes, per connection** — *«Die Preisauskunft bezieht auch
  Spartickets mit ein, wenn sie existieren. Normalpreis-Tickets haben den Code 125»*
  (e.g. BLS Bern–Zweisimmen product code 84004). Requests must be for the **future**
  → prices are **date+time+train specific**.
- **Known issues (cookbook):** sometimes answers with a discounted day pass under
  code 2361 (filter it); no prices for foreign stops outside tariff unions.
- **Rate limits (official):** free tier **50 req/min, 20'000/day per key** (OJPFare,
  OJP, TFS); paid tiers up to CHF 1'000/month ([limits](https://opentransportdata.swiss/en/limits-and-costs/)).
- **License:** open-data terms (FEDRO / platform rules) — cleanest legal basis.
- **Status caveat:** *«ein erstes Testsystem … Daten stammen aus der Integration und
  nicht von der Produktion … Die Preisauskunft ist nicht verbindlich»* — prices may
  deviate from the shop.

## 2. sbb.ch web-shop GraphQL (undocumented) — best data, live-verified, ToS risk

Extracted from the sbb.ch Next.js bundle (runtime config: `apolloUrl:
"https://graphql.www.sbb.ch/"`). Works **without login** if sent like the browser
sends it; plain curl gets CloudFront **403** — you need a browser UA, `Origin`/`Referer`
and the `apollographql-client-*` headers. Verified 2026-09-27 with Bern→Basel SBB,
2026-10-01:

**a) Trips** (`query Trips($input: TripInput!…)`), `input` =
`{"places":[{"type":"NAME","value":"Bern"},{"type":"NAME","value":"Basel SBB"}],
"time":{"date":"2026-10-01","time":"10:00","type":"DEPARTURE"}}` → 3 trips, e.g.
`10:04→11:00`, with opaque `trip.id` used below.

**b) `tripPrices`** — min price per class, **full vs Halbtax** via
`passengers:[{reductions:["NONE"|"HALF_FARE"]}]`:

| trip (dep) | reduction | 2nd | 1st | matches offer below |
|---|---|---|---|---|
| 10:04 | NONE | 27.20 | 46.80 | **Supersaver Ticket** |
| 10:04 | HALF_FARE | 15.40 | 24.60 | Supersaver (HTA) |
| 10:33 | NONE | 42.00 | 72.00 | Point-to-point (no supersaver) |
| 10:33 | HALF_FARE | 21.00 | 36.00 | Point-to-point (HTA) |

(Note: the `afterSaleFlexibility` labels returned do not map cleanly to
supersaver/normal — trust `tripOffers` for product identity.)

**c) `tripOffers`** (`tripOffersInput:{tripContext:"<trip.id>", passengers:[{…
reductions:[{code:"NONE"|"HTA123"|GA…}]}]}`) — the real buy-flow offers, **per train**.
Trimmed live response (10:04 train, reduction NONE):

```
Point-to-point Ticket   4200 CHF  (2nd, PERSON_16+)     7200 CHF (1st)
City-Ticket             5110 CHF  (2nd)                 8110 CHF (1st)
Supersaver Ticket       2720 CHF  (2nd)  ← Sparbillett  4680 CHF (1st)
Supersaver Ticket Flex  3180 CHF  (2nd)                 5440 CHF (1st)
```

With `HTA123` the 10:33 train additionally returned `Supersaver Ticket 25.20 CHF
(1st)` and `Supersaver Ticket Flex 28.60 CHF` — i.e. **supersaver inventory is
per-connection, date+time dependent, and separate for full/Halbtax**, exactly as on
sbb.ch. Also observed: `Saver Day Pass` (Spartageskarte), `City-Ticket` variants,
round-trip bundles (`direction: ROUND`), validity windows.

Other useful operations in the same schema: `places` (station search, verified),
`lowPriceTrips` / `routeMinPrices` (low-price calendar — exists but returned
`routePriceAvailableForRoute:false` in unauthenticated probes),
`HtaStatusSummaries`, `AddNationalTripOfferToCart` (booking needs SwissPass session).

**Assessment:** exact production prices incl. Sparbillette, no auth, JSON — but
**undocumented internal API** of the sbb.ch shop (CloudFront-WAFed; no published rate
limits; schema introspection disabled; will break silently on SBB redesigns). Fine
for personal calibration scripts; **not** a stable/legally-safe production source.

## 3. SBB official B2B / mobile APIs

- **developer.sbb.ch** (3scale APIM, Azure-AD SSO registration): publicly documented
  API is the **Journey-Service** B2C (`/v3/trips`, places, formations, occupancy) —
  a *planner*; no price/fare/ticket endpoint in its open docs. The underlying sales
  system (NOVA) appears only as an internal dependency.
- **B2P API** (partner sales, `https://b2p.api.sbb.ch`): live probe
  `GET /api/v2/prices?tripIds=…` → `401 "Access not allowed: Authorization header is
  missing or invalid"`. Shape per `schlpbch/bookingAPI` (which SBB built for a hack
  event, INT host `b2p-int.api.sbb.ch`): `GET /api/trips`, `GET /api/trip-offers`,
  `GET /api/v2/prices` → `[{tripId, qualityOfService, superSaver: true|false, price:
  620 /*CHF 6.20, cents*/}]`. Requires an SBB **partner contract** (headers
  `Authorization`, `X-Conversation-Id`, `X-Contract-Id`) — not accessible to
  individuals. This is the API behind travel-agency/Omio-style sales.
- **SBB Mobile (vnext), reverse-engineered** — verified live:
  ```
  GET https://active.vnext.app.sbb.ch/api/timetable/v2/trips
      ?departureName=Bern&arrivalName=Basel SBB&searchDate=2026-10-01&searchTime=10:00&searchDateTimeType=DEPARTURE
  headers: User-Agent: SBBmobile/12.49.5.166.master Android/14 …; USE-CASE: TIMETABLE;
           X-APP-TOKEN: <random UUID>;
           X-API-DATE: <YYYY-MM-DD>;
           X-API-AUTHORIZATION: base64(HMAC-SHA1(key, path+date))
  # key published in github.com/denysvitali/sbb-api-rs (extracted from the Android app)
  ```
  → HTTP 200 JSON (`x-rate-limit-remaining: 765` header). TLS cert is still signed by
  SBB's own CA (`*.sbbmobile.ch`, in that repo) — curl needs `--cacert` or `-k`.
  **Timetable only — no prices** (the fare flow lives elsewhere). Legal status:
  undocumented app API, spoofed app identity — same ToS risk class as §2.
- Old endpoints (`api.sbb.ch:8080`, `xmlfahrplan.sbb.ch/bin/extxml.exe`,
  `app.sbbmobile.ch/tripoffer`) are **dead** (NXDOMAIN / superseded).

## 4. Community / wrapper APIs (verified: no prices)

- **transport.opendata.ch** `/v1/connections?from=Bern&to=Basel SBB` → 200, full
  field dump contains only timetable + `capacity1st/capacity2nd` (occupancy
  prognosis) — **no price fields at all** (docs & live response checked).
- **transport.search.ch** (`search.ch/fahrplan/api/…`): completion/route/stationboard
  only; help page has **zero** price/tarif/ticket mentions; requires free key
  (email registration); limits *«1000 Routensuchen und 10080 Abfahrtstabellen»*/day;
  *«Beachten Sie, dass das API jederzeit ändern kann»*. No fare data.

## 5. Other operators / aggregators

- **BLS, SOB, TPF, ZVV:** no developer/price APIs on their sites (spot-checked).
  Regional fares are in NOVA/DFA → queryable via **OJPFare** (cookbook's own example
  is a BLS product). ZVV municipal tariffs appear there only if part of the through
  tariff.
- **Fairtiq / Omio:** no public APIs (checked). Omio-type OTAs consume B2P-style
  partner integrations.

## Recommendation

| Need | Best source | Alternative / fallback |
|---|---|---|
| (a) Point-to-point full & Halbtax price (1st/2nd), reproducible & legal | **OJPFare** (opentransportdata.swiss, free key; NOVA full + HTA via `EntitlementProduct`) | sbb.ch GraphQL `tripPrices` (exact shop prices, undocumented) |
| (b) Per-connection Sparbillette (supersaver), full & Halbtax | **sbb.ch GraphQL `tripOffers`** (live per-trip "Supersaver Ticket (Flex)", HTA variants) | OJPFare (includes Spartickets per trip, but INT system, non-binding); B2P `superSaver` flag (partner contract only) |
| Timetable to feed fare queries | OJP 1.0/2.0 on opentransportdata.swiss (same key) | transport.opendata.ch / search.ch / vnext (no prices but fine for trips) |

## Modeling implications

1. **Auto-fill `trips.yaml` prices:** a small script can query the sbb.ch GraphQL
   (`Trips` → `tripPrices` with `HALF_FARE`) per relation in trips.yaml and write the
   observed 2nd-class Halbtax price into `price:` (and full fare for
   `price_calibration.yaml` anchors) — replaces the km-based estimator with exact
   NOVA tariffs. Round-trip flag maps to `direction: ROUND` bundles (≈2× one-way).
2. **Sparticket modeling:** `tripOffers` gives per-departure supersaver prices when
   they exist; sampling a relation over several days yields an empirical
   *availability* and *discount ratio* (e.g. Bern→Basel 10:04: 27.20 vs 42.00 = 65%).
   That could add an optional `sparticket_factor:` per trip — but note PLUS credit
   only covers Sparwelt tickets for the *booked* train, and spontaneous travellers
   can't count on inventory; safest use is as a sensitivity bound, not the mean.
3. **Price semantics for the model:** with Halbtax, point-to-point is exactly 50% of
   full fare on national direct traffic (observed 42.00→21.00), so
   `full = 2 × halftax` remains a valid calibration invariant; supersaver prices do
   **not** obey it (27.20 full vs 15.40 HTA ≈ 57%).
4. **Operational notes:** fares only for future dates; OJPFare needs the free API key
   (email registration, 50 req/min free tier) and returns test-system prices; the
   sbb.ch GraphQL is exact but undocumented — cache results in `price_calibration.yaml`
   rather than hammering it; B2P is out of reach without a partner contract.

## Validation: trips.yaml (SBB app) vs sbb.ch GraphQL — live

**Date:** 2026-09-27 · queries re-extracted from the sbb.ch bundle the same way as §2
(Next.js chunk `6656-*.js`, string table `"<query>":a.XXX`), then run live for the 4
hand-priced relations in `trips.yaml`. Search date **2026-10-01** (whole day, ~05:00–23:00,
paged), one adult passenger **with Halbtax** (`reductions:[{code:"HTA123"}]`), 2nd class,
one-way (OUTWARD bundles only). Prices are `bundle.totalPrice` in centimes; product =
`includedOffers[].title` + `productIdentifier`.

### Comparison table

| # | relation (trips.yaml) | trips.yaml HTA 2nd | GraphQL product & price (HTA 2nd) | match? | cheapest Sparbillett that day |
|---|---|---|---|---|---|
| 1 | Olten, Südwest → Basel, Dreispitz | 11.40 | **Point-to-point Ticket 11.40** on the 23 fastest deps; slower routings 11.00 (×19) / 10.70 (×31) | **exact** (routing-dependent) | Supersaver Ticket **8.20** (dep 13:06); supersavers on 33/73 deps (8.20–10.00) |
| 2 | Olten, Südwest → Zürich HB | 16.00 | **Point-to-point Ticket 16.00** on 48/49 deps (one 16.90) | **exact** | Supersaver Ticket **11.80** (dep 05:45); on 38/49 deps (11.80–13.00) |
| 3 | Olten, Südwest → Luino, Stazione FS (I) | 48.20 | **Point-to-point Ticket 48.20** on 24/34 deps; 41.50 (×7) on the faster IC→Bellinzona→S20→S30 routing; 53.70 (×1) | **exact** (dominant routing) | Supersaver Ticket **31.20** (dep 05:20); on 16/34 deps; `Saver Day Pass` also offered |
| 4 | Luino, Stazione FS (I) → Lugano, Stazione FFS | 3.90 | **Arcobaleno Individual Ticket 3.90** (NOVA-1638) on 21/24 deps — *not* the national Point-to-point product | **exact** (different product) | none — Arcobaleno tariff has no Spartickets |

### Request recipe that worked (minimal)

Same headers as §2 (browser UA, `Origin`/`Referer: https://www.sbb.ch`, `apollographql-client-name/-version/-time/-origin`);
the client-name value appears unvalidated (`web-shop` accepted; the real value is a build-time
env `NEXT_PUBLIC_APP_NAME` not exposed in the HTML). Two queries suffice:

1. **`Trips($input: TripInput!, $pagingCursor, $language)`** (+ `TripFields` fragment, verbatim
   from the bundle) with
   `input = {places:[{type:"NAME",value:"Olten, Südwest"},{type:"NAME",value:"Luino"}],
   time:{date:"2026-10-01",time:"05:00",type:"DEPARTURE"}}`, `language:"EN"`; page via
   `paginationCursor.next` (5 trips/page). Foreign and bus/tram stop names resolve as `NAME` places.
2. **`TripOffers($processId, $language, $tripOffersInput)`** per trip — gotchas found by diffing
   against the bundle's caller:
   - `tripOffersInput` must include **`bikes:0, dogs:0`** — omitting them (or sending only
     `reductions:[{code:"HTA123"}]` without the full passenger object) returns **200 with zero
     bundles**, no error;
   - passenger = the client's default: `{id:"default-passenger", firstname:"Max",
     lastname:"Mustermann", dateOfBirth:<25y ago>, reductions:[{code:"HTA123"}]}` — this is what
     the anonymous timetable shop sends; `processId` = any client-generated UUID;
   - header `apollographql-client-business-context: b2c`;
   - read prices from `bundles[].totalPrice` (centimes) filtered `direction ∈ {null,"OUTWARD"}`
     and `travelClass:"SECOND"`; `includedOffers[].priceDetails.amount` is sometimes `null`
     (was null for all Arcobaleno offers).
- `TripPrices` (batched) works for small `tripIds` lists but a 73-ID batch tripped CloudFront
  (**403**) — keep batches small or skip it; `tripOffers` is the authoritative buy-flow source anyway.

### Observations

- **Non-rail stops (relations 1–2) price fine**: `Olten, Südwest` (bus stop) → `Basel, Dreispitz`
  (tram/bus stop) returns a normal through **Point-to-point Ticket** (NOVA-125) plus optional
  **City-Ticket** add-ons (NOVA-4092, 15.70–21.00 HTA 2nd for Basel zones). Short local tariff is
  included in the through fare; the exact amount depends on the routing (relation 1 had three
  variants: 11.40/11.00/10.70 — the app-priced 11.40 corresponds to the fastest connections).
- **International (relations 3–4): prices come back at all times**, in both directions — Luino as
  destination *and* as origin. This **contrasts with the OJPFare cookbook limitation** ("no prices
  for foreign stops outside tariff unions", §1): the sbb.ch shop sells via TCV/Arcobaleno
  international tariffs, so the GraphQL returns them. Caveat: for Luino→Lugano the Swiss national
  Point-to-point product is generally **not** offered — the sellable product is the **Arcobaleno
  Individual Ticket** (3.90 HTA 2nd / 6.70 1st). One late-evening EC departure instead offered the
  national Point-to-point (11.90), an *Arcobaleno Transfrontaliera* Individual Ticket (11.30,
  NOVA-63155) and City-Ticket — international product choice is per-connection, not just per-relation.
- **Product codes line up with the OJP cookbook**: Point-to-point = `NOVA-125` (cookbook: normal
  price tickets are code 125), Supersaver Ticket = `NOVA-84004` — the very BLS Sparticket code the
  cookbook cites (Bern–Zweisimmen); Supersaver Flex = `NOVA-84022`. So GraphQL offers and OJPFare
  fare products share the NOVA product space.
- **Per-train Sparbillette confirmed on 3 of 4 relations** (none exist on the Arcobaleno tariff);
  supersavers appeared on 33/73, 38/49 and 16/34 departures respectively, always alongside the
  full-flex Point-to-point product. Two edge cases: one Olten→Luino departure (17:36, arr 23:15)
  returned no offers at all, and one (21:27, overnight arrival) offered *only* supersavers.
- Halbtax = exactly 50 % of full fare on every product seen here (re-measured with a no-reduction
  passenger: r1 22.80→11.40, r2 32.00→16.00, r3 96.40→48.20, r4 Arcobaleno 7.80→3.90), consistent
  with §2/Modeling point 3; supersavers again violate it (r3 05:20: 31.20 HTA vs 55.20 full ≈ 56 %).

### Verdict

The sbb.ch GraphQL **reproduces all four SBB-app prices exactly** — including the international
Luino relations and the non-rail bus/tram-stop relations — with two caveats: (a) where multiple
routings exist the point-to-point price is routing-dependent (the app value matched one variant,
usually the dominant/fastest one, and a *cheaper* variant sometimes exists), and (b) for the purely
cross-border local relation the matching product is the Arcobaleno ticket, not the national
Point-to-point product — a naive "look for Point-to-point Ticket" scraper would miss it. For
auto-filling `trips.yaml`, match on `productIdentifier`/title **per relation**, and prefer the
price of the routing class the traveller actually uses.
