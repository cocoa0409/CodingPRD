# Game Package Blackout API — Product Requirements Document

## 1. Introduction

A national sports league sells the out-of-market television rights to its regular-season game inventory to a distribution partner, who operates a streaming package that lets fans watch any game not carried by their local broadcasters. This product lives and dies on a deceptively simple promise — "every game, except the ones your market already shows" — and behind that promise sits a thicket of operational machinery: the rights grant itself with its exclusivity term and its effective window, the season's week-by-week cadence, the national broadcast selections that quietly remove games from the package each week, the territorial blackout math that maps a billing address and a device location to a market and a market to an in-market game, the commercial-establishment licensing program that prices a sports bar's access by certified occupancy while hunting down residential accounts streaming in taprooms, and the customer-service apparatus that adjudicates blackout complaints into refunds.

This document specifies the API surface of that system. It covers how league operations staff schedule games and curate weekly slates from the first `PRE_SALE` announcement through the final phase advance to `POST`; how subscribers purchase in-season with proration, how students receive a discounted tier against a time-boxed verification, and how the package's multiview and companion features are gated per plan; and how the platform enforces optimistic concurrency on the shared resources — weekly slates and season phase — that multiple operators edit in the run-up to kickoff. Because distribution agreements fail in expensive ways when any two of territory, slate posture, and entitlement disagree, the system's overarching design goal is that every piece of availability information a subscriber sees is derived, at request time, from a single chain of season posture, slate snapshot, national selections, and market resolution — never cached into a state that can drift.

A note on time: the system runs on a logical clock that administrators can advance explicitly. At server startup the clock reads exactly `2026-09-01T00:00:00Z`, and it never consults wall-clock time — every temporal rule in this document (offer windows, complaint grace periods, student verification expiry, rights-grant expiry) is evaluated against that logical clock. The clock is moved by a `PlatformAdmin`-only operation that takes a `current_utc` instant and returns it, and every such set re-evaluates the time-based auto-transitions described in §3.1 and §3.9.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request is authenticated by two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which they act. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The single exception is account registration, which is reachable by an unauthenticated caller acting as `Anonymous`. Once authenticated, if the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The roles are:

- `Anonymous` — the unauthenticated caller. Permitted only to register a new account. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is not compared against any resource's `id`.
- `PlatformAdmin` — the distribution partner's platform operator. Owns rights-grant creation and termination, offer creation and withdrawal, account closure, subscription entitlement suspension and restoration, the logical clock, and payment simulation. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `LeagueOps` — league operations. Owns season phase advancement and all weekly-slate curation: national-selection moves, finalize, reopen, and lock. Shares season, market, game, and week-slate creation with `PlatformAdmin`. When `X-User-Role` is `LeagueOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Subscriber` — a residential account holder. Purchases offers, cancels their own subscription, runs territory checks, files complaints, and starts multiview sessions. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's account foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403).
- `VenueManager` — a commercial establishment operator. Applies for venue licenses, purchases and cancels subscriptions for the venue, runs territory checks, and starts multiview sessions. When `X-User-Role` is `VenueManager`, `X-User-ID` is the `id` of the acting `Account`, and ownership is enforced exactly as for `Subscriber`.
- `SupportAgent` — customer service. Resolves, escalates, and de-escalates complaints, and grants and rescinds per-game entitlement overrides. When `X-User-Role` is `SupportAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `created_by` on each override the agent grants, and that recorded value — not any entity relationship — governs who may later rescind the override.
- `ComplianceAuditor` — enforcement. Certifies, recertifies, suspends, reinstates, and revokes venue licenses; flags and clears commercial misuse on accounts; revokes student verifications. When `X-User-Role` is `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Ownership checks deserve one extra sentence because they guard whole families of endpoints. Any subscriber-scoped operation — cancelling a subscription, filing a complaint, running a territory check — requires that the acting `Subscriber` or `VenueManager` own the parent account of the resource being touched; otherwise the request fails with `ERR_NOT_OWNER`. Separately, only the `SupportAgent` whose `X-User-ID` was recorded as `created_by` on an override may rescind that override — an inverse segregation-of-duties rule.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100. `offset` defaults to 0 and may not be negative. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object, where `total_count` is the full count of matching resources before pagination and `has_more` indicates whether additional rows exist beyond the returned window. Unless a list endpoint specifies otherwise, results are sorted by `created_at` in ascending order.

### 2.4. Common Resource Properties and the Mutation Ledger

Most resources share a standard quartet of system-maintained fields. `id` is a server-minted UUID with no type prefix — it identifies the resource and nothing else. `created_at` is the ISO 8601 UTC timestamp (three fractional digits) at which the resource was created, and `updated_at` is the timestamp of its most recent mutation. `version` is an integer that increments by exactly one on every mutation of the resource; clients read it and echo it back in optimistic-concurrency checks where §2.7 requires it.

Two resources deliberately break this pattern, and the exception matters. `Payment` rows and `TerritoryCheck` rows are append-only evidence: each carries only `id` and `created_at`. Neither `updated_at` nor `version` exists on them, because neither is ever mutated — a payment ledger entry or a territory-check verdict, once written, is permanent.

Whenever any mutating operation touches a resource, that resource's `updated_at` refreshes to the current logical-clock instant and, where the field exists, `version` advances by one. Cascades described in §3 — a season's phase advance sweeping its subscriptions, a national-selection move sweeping entitlements — refresh each touched resource individually.

### 2.5. Markets, ZIP Prefixes, and Territory Resolution

Territory determination rests on the `Market` entity. Each market has a unique, case-sensitive `code` (for example `NYC` or `DAL`), a human-readable `name`, a non-empty array `zip_prefixes` of three-digit ZIP prefix strings, and an array `home_team_codes` naming the teams whose games count as in-market there (this list may be empty). One prefix may appear in at most one market across the entire system: creating or updating a market so that any of its prefixes is already claimed by another market is rejected with `ERR_MARKET_PREFIX_OVERLAP` (HTTP 409), which guarantees the lookup below is never ambiguous.

Resolving a ZIP code to a market is a pure lookup: take the first three characters of the ZIP, find the market whose `zip_prefixes` contains that prefix, and return that market's `code`. If no market claims the prefix, the resolution yields null. Every ZIP the system ingests — a billing ZIP at registration or update, a device ZIP at check time, a venue ZIP — must be five numeric digits, and malformed input fails with `ERR_INVALID_REQUEST` (HTTP 400).

This lookup fires in three places. At account registration, and again whenever the account's `billing_zip` is changed through an account update, the system resolves and stores `billing_market_code` (null if unmapped). At territory-check time, the system resolves the reported `device_zip` into `device_market_code` (again null if unmapped) and then selects the effective market per the dual-variant rule in §3.6. Separately, each `Game` records `home_market_code` — the market in which that game is in-market, always the home team's market — and a game whose `home_market_code` does not reference an existing market `code` cannot be scheduled at all (`ERR_SEASON_STRUCTURE`, HTTP 422).

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts are integer cents — `base_price_cents`, `price_charged_cents`, `paid_amount_cents`, `refund_amount_cents`, `annual_fee_cents`, and the `amount_cents` on each `Payment` row. Intermediate arithmetic that produces a fractional cent is rounded half-up to a whole cent at each explicitly labelled computation step, not once at the end; §3.5 shows why the step ordering matters for the student tier. Ratios that feed pricing (the proration factors of §3.5) are computed in exact rational arithmetic and only the final cents amount is rounded.

### 2.7. Optimistic Concurrency Control

Three write operations operate on shared operational state that multiple `LeagueOps` operators (or, for season phase, one operator's own stale screen) can edit, and all three require the client to echo the version it last observed:

- Moving a national selection on a weekly slate — adding or removing a game — requires `expected_slate_version` in the request body, matching the target `WeekSlate`'s current `version`.
- Finalizing a weekly slate likewise requires `expected_slate_version` matching the slate's current `version`.
- Advancing a season's phase requires `expected_season_version` matching the target `Season`'s current `version`.

If the supplied value does not match the parent entity's current `version` — because another writer has advanced the slate or the season since the client last read it — the request is rejected with `ERR_STALE_SLATE_VERSION` (HTTP 412) for the two slate operations, or `ERR_STALE_SEASON_VERSION` (HTTP 412) for the phase advance. The client must re-read the resource and re-issue with the fresh version. No other endpoint takes an expected-version field; writes not named above process without an OCC check.

### 2.8. Nested Path Validation and Validation Ordering

Endpoints that address resources through hierarchical paths validate path identifiers left to right — grant before season before week-slate or offer; account before subscription, venue license, complaint case, student verification, or override. The first identifier that does not resolve to an existing resource fails the whole request with `ERR_NOT_FOUND` (HTTP 404).

When several validations apply to one request, the server evaluates them in a fixed priority order, so a caller always sees the same first failure rather than an arbitrary one:

1. Authentication — `X-User-ID` and `X-User-Role` present, role value declared (`ERR_UNAUTHENTICATED`).
2. Authorization — the role is permitted for this operation (`ERR_FORBIDDEN_ROLE`).
3. Existence — path identifiers resolve, left to right (`ERR_NOT_FOUND`).
4. Source-state legality — the target resource is in a valid source state for the requested transition; a transition attempted against a terminal state instead yields `ERR_ALREADY_TERMINAL` (both HTTP 409; non-terminal wrong-state calls yield `ERR_INVALID_STATE`).
5. Season-phase gate on purchases (`ERR_SEASON_CLOSED`).
6. Optimistic-concurrency checks (`ERR_STALE_SLATE_VERSION`, `ERR_STALE_SEASON_VERSION`).
7. Offer availability window (`ERR_OFFER_NOT_AVAILABLE`).
8. Student-tier verification gate (`ERR_STUDENT_NOT_VERIFIED`).
9. Account-kind gate (`ERR_ACCOUNT_KIND_MISMATCH`).
10. Game week consistency (`ERR_GAME_WEEK_MISMATCH`).
11. National-selection membership conflicts (`ERR_NATIONAL_SELECTION_CONFLICT`).
12. Slate lock (`ERR_SLATE_LOCKED`).
13. Uniqueness (`ERR_DUPLICATE_RESOURCE`, `ERR_MARKET_PREFIX_OVERLAP`).
14. Season structural bounds (`ERR_SEASON_STRUCTURE`).
15. Venue occupancy cap (`ERR_OCCUPANCY_CAP_EXCEEDED`).
16. Complaint grace window (`ERR_COMPLAINT_WINDOW_EXPIRED`).
17. Complaint category gate (`ERR_COMPLAINT_NOT_REFUNDABLE`).
18. Refund floor (`ERR_REFUND_NOT_AVAILABLE`).
19. Multiview concurrency cap (`ERR_MULTIVIEW_CAP_REACHED`).
20. Multiview feature entitlement (`ERR_FEATURE_NOT_ENTITLED`).
21. Ownership (`ERR_NOT_OWNER`).
22. Payload shape — required fields present, enum members valid, ZIPs five numeric digits, datetimes ISO 8601 UTC (`ERR_INVALID_REQUEST`).

Two orderings are worth memorizing because they invert naive expectations: the slate-lock check and the selection-membership check both sit *after* the OCC check, so a stale-version rejection (`412`) is reported before a locked-slate rejection (`409`); and on complaint resolution the grace-window check (16) is evaluated before the category gate (17), which is evaluated before the refund-floor check (18).

## 3. Business Logic & Workflows

### 3.1. The Rights Grant: Root of the Distribution Tree

Everything in the system descends from a **RightsGrant**: the league's contractual grant of out-of-market distribution rights to the partner. A `PlatformAdmin` creates one with the partner's legal `distributor_name`, a `scope` (in this version of the platform always `OUT_OF_MARKET`), an `exclusivity` term of either `EXCLUSIVE` or `NON_EXCLUSIVE`, an `effective_from` and `effective_until` pair bounding the grant's validity, and `max_commercial_occupancy_cap` — an absolute ceiling on the venue occupancy that can be certified anywhere under this grant, which must be greater than zero. The grant's `effective_until` must be strictly after `effective_from`. A new grant is born with `status` `ACTIVE`, and `EXPIRED` and `TERMINATED` are its only terminal states.

A grant leaves `ACTIVE` by one of two routes. A `PlatformAdmin` may terminate it outright, moving status from `ACTIVE` to `TERMINATED`. Alternatively, on every set of the logical clock the system re-evaluates time-based transitions, and once the logical clock reaches or passes `effective_until` the grant auto-transitions from `ACTIVE` to `EXPIRED`. Both routes trigger the same depth-four cascade, and every leg of it matters. Each season under the grant is pushed to phase `POST` if it is not already there. Every subscription whose season belongs to the grant and whose `status` is `ACTIVE` is transitioned to `CANCELLED`, its `cancelled_at` stamped with the logical-clock instant and its `entitlement_state` forced to `REVOKED`. Every game entitlement hanging under those subscriptions moves to `WITHDRAWN` with `withdrawn_reason` `ENTITLEMENT_REVOKED`. And every venue license held by accounts of this distributor is `REVOKED`. Termination and expiry are equally fatal downstream; they differ only in the grant's own recorded `status`.

### 3.2. Seasons: Structure, Phase, and the Rhythm of the Year

Under a grant, a `LeagueOps` operator (or a `PlatformAdmin`) creates a **Season** by supplying the parent `rights_grant_id`, a `label` such as "2026-Regular" (unique within its parent grant; a collision is `ERR_DUPLICATE_RESOURCE`, HTTP 409), the `regular_season_weeks` count (at least 1 and at most 22), a `season_start_date` understood as the first day of Week 1 at midnight UTC, and a `season_end_date` that must fall after `season_start_date`. Two optional policy knobs ride along: `grace_days`, the complaint/refund eligibility window in days after purchase, defaulting to 7 and bounded between 0 and 30 inclusive; and `student_discount_pct`, the whole-percent discount applied to the student tier's base price, defaulting to 50 and bounded between 0 and 90.

A season is created with its `phase` set to `PRE_SALE`. Its `phase` machine is a simple line — `PRE_SALE` → `REGULAR` → `POST` — driven by phase advancement, a `LeagueOps`-only operation guarded by OCC as described in §2.7. The first advance, `PRE_SALE` → `REGULAR`, additionally requires that at least one week slate already exists for the season; a season cannot go "regular" with no weekly structure at all. The second advance, `REGULAR` → `POST`, carries a heavy cascade: every subscription of the season whose `status` is `ACTIVE` transitions to `EXPIRED` (its `entitlement_state` left unchanged unless it was already `REVOKED`), and every game entitlement under those subscriptions that is `GRANTED` becomes `WITHDRAWN` with `withdrawn_reason` `ENTITLEMENT_REVOKED`. Each successful advance increments the season's `version` by one. `POST` is terminal for sales: a purchase attempted against a season in `POST` is rejected with `ERR_SEASON_CLOSED` (HTTP 409), while purchases remain legal in both `PRE_SALE` and `REGULAR`. Note the deliberate distinction between a subscription ending `EXPIRED` (season ran out from under it) and `CANCELLED` (someone actively cancelled) — the refund math in §3.7 reads that distinction.

### 3.3. Markets and the Game Schedule

Markets, as covered in §2.5, are the territory substrate. Beyond prefix non-overlap, the `code` itself is unique across all markets and case-sensitive — reusing an existing `code` on creation is `ERR_DUPLICATE_RESOURCE`.

Games are scheduled into a season week by `LeagueOps` or a `PlatformAdmin`, providing `season_id`, a 1-based `week_index`, `away_team_code` and `home_team_code` (which must differ from each other), a `kickoff_at` instant, and the `home_market_code`. The structural rules guarding this creation all surface as `ERR_SEASON_STRUCTURE` (HTTP 422): `week_index` must lie between 1 and the season's `regular_season_weeks` inclusive; away and home team codes must differ; `home_market_code` must reference an existing market `code`; and `kickoff_at` must fall inside the owning week's window — the seven-day span of that week counted from `season_start_date`, week 1 occupying the first seven days, week 2 the next seven, and so on. When a game is created and a week slate already exists for that (season, week) pair, the slate's `package_game_count` is recomputed to absorb the new game.

### 3.4. The Weekly Slate and National Broadcast Selections

Each week of a season gets at most one **WeekSlate** — creating a second slate for the same (season, `week_index`) pair is `ERR_SEASON_STRUCTURE`. A slate is created with just `season_id` and `week_index` and is born with `slate_status` `PRELIMINARY`, with `national_game_ids` empty, `finalized_game_ids` empty, and `package_game_count` computed immediately: the count of games in the package for the week, always the total number of games scheduled in that week minus the games currently carried as national selections.

National broadcast selections are the league's weekly editorial act. A `LeagueOps` operator moves a game into or out of the national picture with a payload naming the `game_id` and an `action` (add or remove), accompanied by `expected_slate_version` per §2.7. The target game must exist, belong to the slate's season, and have a `week_index` equal to the slate's own — otherwise `ERR_GAME_WEEK_MISMATCH` (HTTP 422). Adding a game already present in `national_game_ids`, or removing one that is not present, is `ERR_NATIONAL_SELECTION_CONFLICT` (HTTP 409) — the national list never holds duplicates. Added games take their place in `national_game_ids` ordered by the game's `created_at`. Every move recomputes `package_game_count` and increments the slate's `version`.

A move is a self-transition on the slate and works in both `PRELIMINARY` and `FINALIZED` posture. In `PRELIMINARY` the provisional package view shifts directly. In `FINALIZED` the same move additionally recomputes the `finalized_game_ids` snapshot so the official view still excludes the newly national games. Either way, the move sweeps game entitlements across the season: for every subscription of the season whose `status` is `ACTIVE`, entitlements for the moved game transition from `GRANTED` to `WITHDRAWN` with `withdrawn_reason` `NATIONAL_SELECTION` when a game is added to the national list, and from `WITHDRAWN` back to `GRANTED` — `withdrawn_reason` cleared to null — when a game is removed and its existing withdrawal reason was `NATIONAL_SELECTION`. A withdrawal originally stamped `SUBSCRIPTION_CANCELLED` or `ENTITLEMENT_REVOKED` is untouched by a removal.

Finalization freezes the picture subscribers see. Finalizing a slate (OCC-guarded, §2.7) moves it `PRELIMINARY` → `FINALIZED`: the system computes `finalized_game_ids` as the package-eligible games at that instant — all games of the week minus the national selections, with per-subscriber blackout irrelevant at the slate level — stamps `finalized_at` with the logical clock, and increments `version`. Corrections remain possible: reopening moves `FINALIZED` → `PRELIMINARY`, clears `finalized_game_ids` back to empty, recomputes `package_game_count` back to the live count, and increments `version`. The slate may then be re-finalized; this correction loop can cycle indefinitely. Locking is the point of no return: once the logical clock has reached or passed the kickoff of the week's earliest game, locking moves `FINALIZED` → `LOCKED`, freezing `national_game_ids` and the finalized snapshot immutably. `LOCKED` is terminal — selection moves and reopen attempts against a locked slate are rejected with `ERR_SLATE_LOCKED` (HTTP 409), and a lock attempt before the week's first kickoff, or against a slate not in `FINALIZED`, is `ERR_INVALID_STATE`.

### 3.5. Accounts, Offers, and the Price of a Season

Anyone may register an **Account** without authentication, supplying an `email` (unique across all accounts, compared case-insensitively — a collision is `ERR_DUPLICATE_RESOURCE`), a `full_name`, an `account_kind` of `RESIDENTIAL` or `COMMERCIAL`, and a five-digit `billing_zip`. Registration resolves `billing_market_code` from the billing ZIP per §2.5 and leaves the account `ACTIVE` with `commercial_flag_reason` null. Later, a `PlatformAdmin` or `SupportAgent` may update `full_name` and/or `billing_zip`; a ZIP change re-resolves `billing_market_code`. Every account field downstream — subscriptions, verifications, licenses, complaints, checks, overrides — hangs off this `id` through its `account_id` foreign key.

The **Offer** is what is actually for sale. A `PlatformAdmin` creates one for a season with a `plan_tier` of `BASE`, `PREMIUM`, or `STUDENT`; a `base_price_cents` list price greater than zero; two feature flags, `includes_multiview` and `includes_companion`; and a purchase window [`valid_from`, `valid_until`) — the offer is purchasable at or after `valid_from` and strictly before `valid_until`, which must be after `valid_from`. An offer is born `ACTIVE` and may be withdrawn, moving to `WITHDRAWN`; withdrawal rejects new purchases but leaves existing subscriptions' snapshots untouched. A purchase against a withdrawn offer, or against the logical clock outside the window, fails with `ERR_OFFER_NOT_AVAILABLE` (HTTP 409).

A purchase creates a **Subscription** from just `account_id` and `offer_id` — but the gates in front of that small payload are the densest in the system, evaluated in the §2.8 order. The season must not be `POST` (`ERR_SEASON_CLOSED`). The offer must be `ACTIVE` and in-window (`ERR_OFFER_NOT_AVAILABLE`). A `STUDENT` offer additionally requires the account to hold a `StudentVerification` whose `status` is `VERIFIED` and whose `valid_through` is strictly in the future of the logical clock — otherwise `ERR_STUDENT_NOT_VERIFIED` (HTTP 422). And the account-kind gate (`ERR_ACCOUNT_KIND_MISMATCH`, HTTP 422) runs in both directions: a `COMMERCIAL` account may not purchase any retail offer (`BASE`, `PREMIUM`, or `STUDENT`), and a `RESIDENTIAL` account may not hold a venue license (§3.8).

The charged price is computed in three pinned steps, and the order is load-bearing. Step 1 applies the tier: for a `STUDENT` offer, take `base_price_cents`, multiply by the difference between 100 and the season's `student_discount_pct`, divide by 100, and round half-up to a whole cent — call this the tier base; for `BASE` and `PREMIUM` the tier base is simply `base_price_cents`. Step 2 applies in-season proration to the tier base: multiply by the count of weeks the buyer receives — the season's `regular_season_weeks` minus the purchase week index plus one, since a buyer in week *p* receives weeks *p* through the final week inclusive — then divide by `regular_season_weeks` and round half-up to a whole cent. Step 3 records the result as `price_charged_cents`. The purchase week index — stored as `purchase_week_index` — is the 1-based season week containing the logical-clock purchase instant, clamped so that a purchase before week 1 counts as week 1 and a purchase beyond the final week counts as the final week. Note the asymmetry the whole pricing model rests on: the student discount applies to the full-season base *before* proration (step 1 before step 2), and reversing the order changes the result whenever the discount percent produces a fractional cent. Because the charge-direction factor counts the purchase week itself as delivered value, a buyer in week 1 of a 22-week season pays the full tier base, and a buyer in the final week pays exactly one week's worth.

A new subscription is `PENDING_PAYMENT` with `entitlement_state` already `ENABLED`, `plan_tier` and `season_id` snapshotted from the offer, and the computed `price_charged_cents` and `purchase_week_index` frozen on the row. Payment itself is out of scope for this API; the platform instead exposes a payment simulation for test-driving, taking `subscription_id` and an `outcome`. When the simulated outcome is success, the subscription moves `PENDING_PAYMENT` → `ACTIVE`: `paid_amount_cents` increases by `price_charged_cents`, a `Payment` row of `kind` `CHARGE` is appended, and the entitlement fan-out fires — a `GameEntitlement` row in `status` `GRANTED` is created for every package-eligible game of every week slate in the season, skipping games that are national-selected at creation time, each row carrying its `game_id`, the denormalized `week_index`, and the owning `subscription_id`. When the simulated outcome is failure, the subscription moves `PENDING_PAYMENT` → `CANCELLED`: `entitlement_state` becomes `REVOKED`, `cancelled_at` is stamped, and — notably — no `Payment` row is appended at all.

The subscription carries two parallel state dimensions that evolve independently. The lifecycle `status` runs `PENDING_PAYMENT` → `ACTIVE` → (`CANCELLED` | `EXPIRED`); the access posture `entitlement_state` runs among `ENABLED`, `SUSPENDED`, and `REVOKED`. A subscriber (or venue manager) who owns the account may cancel an `ACTIVE` subscription: `cancelled_at` is stamped, `entitlement_state` becomes `REVOKED`, and every entitlement still `GRANTED` under the subscription becomes `WITHDRAWN` with `withdrawn_reason` `SUBSCRIPTION_CANCELLED`. Cancel is immediate and silent on money — any refund flows through the complaint process of §3.7, never through cancel itself. Meanwhile a `PlatformAdmin` may suspend the entitlement dimension alone, `ENABLED` → `SUSPENDED`, leaving lifecycle `status` untouched: while suspended, territory checks for the subscription return `NO_ENTITLEMENT`, but the entitlement rows themselves are unchanged. Restoring returns `SUSPENDED` → `ENABLED` and, deliberately, does not re-create any entitlement that was previously `WITHDRAWN`.

### 3.6. Territory Checks and the Availability Verdict

The **TerritoryCheck** is the system's evidence record for a single question: may this account watch this game through this subscription from this device location right now? A subscriber, venue manager, or support agent runs a check with `account_id`, `subscription_id`, `game_id`, and the five-digit `device_zip` reported by the device; the acting user must own the account (`ERR_NOT_OWNER`). The system resolves `device_market_code` from the device ZIP, selects the effective market, computes the `verdict`, stamps `checked_at` with the logical clock, and appends the row — immutable thereafter, per §2.4.

The effective market is chosen by a dual-variant rule keyed on account posture. For an account in `ACTIVE` status, the device-preferred variant applies: the effective market is `device_market_code` when the device ZIP mapped to a market, falling back to `billing_market_code` only when the device ZIP is unmapped. For an account in `SUSPENDED` status — one flagged for commercial misuse — the billing-authoritative variant applies: `billing_market_code` wins always, even when the device ZIP maps cleanly to a different market. A flagged account, in other words, loses the benefit of device-location deference. The chosen market is recorded as `effective_market_code` on the check row.

The verdict then walks a fixed chain. First, if the subscription's `entitlement_state` is anything other than `ENABLED`, the verdict is `NO_ENTITLEMENT`. Otherwise, if the game's week slate is `FINALIZED` or `LOCKED` and the game is not in the slate's `finalized_game_ids`, the verdict is `NOT_IN_PACKAGE`; equivalently, if the slate is still `PRELIMINARY` and the game appears in its live `national_game_ids`, the verdict is likewise `NOT_IN_PACKAGE`. Otherwise, if the game's `home_market_code` equals the effective market, the verdict is `BLACKED_OUT` — the subscriber's local broadcaster carries this game, and the package must not. Anything reaching the end of the chain is `AVAILABLE`. One override sits above the entire chain: an `EntitlementOverride` in `status` `ACTIVE` for that (account, game) pair forces the verdict `AVAILABLE` as the final step, regardless of what the chain concluded. When lists of games are produced anywhere in the system, they are ordered by `kickoff_at`, ties broken by the game's `created_at`.

### 3.7. Complaints, Blackout Disputes, and the Refund Waterfall

When a subscriber believes the package failed them, they file a **ComplaintCase** — payload `account_id`, `subscription_id`, `game_id`, a `category` of `BLACKOUT_DISPUTE`, `BILLING`, or `QUALITY`, and free-text `detail`. The complainant must own the account (`ERR_NOT_OWNER`). A complaint is born `OPEN` with `refund_amount_cents` zero and `resolution_note` null.

A `SupportAgent` then drives the case. Resolution takes a `decision` and a `note`. A deny decision moves `OPEN` → `DENIED` for any category, recording the `note` as `resolution_note` while `refund_amount_cents` stays zero. An approve decision is far more guarded, and the guards run in the §2.8 order. Only a `BLACKOUT_DISPUTE` may be approved — approving a `BILLING` or `QUALITY` complaint is `ERR_COMPLAINT_NOT_REFUNDABLE` (HTTP 422). The complaint must have been filed within the season's `grace_days` of the subscription's purchase, measured against the logical clock at second granularity with an inclusive boundary: filing exactly `grace_days` after purchase is still eligible, one second beyond is not, and an out-of-window approval is `ERR_COMPLAINT_WINDOW_EXPIRED` (HTTP 422). And the computed refund must clear a floor — greater than zero and not exceeding the subscription's `paid_amount_cents` — else `ERR_REFUND_NOT_AVAILABLE` (HTTP 422).

The refund amount itself is a waterfall. The weekly value basis divides the subscription's `price_charged_cents` by the number of weeks the subscriber received — `regular_season_weeks` minus `purchase_week_index` plus one, the remaining-weeks anchor — rounded half-up to a whole cent. If the subscription's `status` is `CANCELLED`, the refund is zero by rule (a cancelled subscription is never refund-eligible via complaint), which then fails the floor above. Otherwise the refund is the smaller of that weekly value and the subscription's current `paid_amount_cents`. Two properties of this design are intentional: the elapsed portion of the season — the weeks before the purchase week, measured by the elapsed-weeks factor of purchase-week-minus-one over total weeks — is never refundable, and exactly one weekly-value unit is refundable per complaint. On approval, the case moves `OPEN` → `APPROVED_REFUND`, with `refund_amount_cents` set, `resolution_note` recorded, a `Payment` row of `kind` `REFUND` carrying the refund as a positive `amount_cents` appended to the subscription, and the subscription's `paid_amount_cents` reduced by the same amount. (A `REFUND` payment row always carries a `reason`; `CHARGE` rows may omit it.)

Escalation is the holding pattern: a support agent may move `OPEN` → `ESCALATED`, and only from `ESCALATED` may the case be de-escalated back to `OPEN`. The loop may cycle; `APPROVED_REFUND` and `DENIED` are terminal.

### 3.8. Commercial Establishments: Venue Licensing and Enforcement

A `VenueManager` applies for a **VenueLicense** with `account_id`, `venue_name`, the venue's five-digit `venue_zip`, and `fire_code_occupancy` — the certified maximum occupancy of the establishment. The account must be `COMMERCIAL`; a residential account applying is `ERR_ACCOUNT_KIND_MISMATCH`. The occupancy must be greater than zero and may not exceed the `max_commercial_occupancy_cap` of the grant that parents the account's activity — a violation either way is `ERR_OCCUPANCY_CAP_EXCEEDED` (HTTP 422), checked again at certify and recertify. A new license is `PENDING`.

Certification is a `ComplianceAuditor`'s act and snapshots the economics. Certifying a `PENDING` license derives its `occupancy_tier` from the certified occupancy on fixed boundaries: occupancy from 1 through 100 inclusive is tier `T1`, from 101 through 500 inclusive is `T2`, and 501 or more is `T3` — so an occupancy of exactly 100 is `T1`, exactly 101 is `T2`, exactly 500 is `T2`, and exactly 501 is `T3`. The `annual_fee_cents` is derived together with the tier: `T1` carries an annual fee of 500000 cents (five thousand dollars), `T2` carries 2000000 cents (twenty thousand dollars), and `T3` carries 6000000 cents (sixty thousand dollars). Recertifying a `CERTIFIED` license with a new `fire_code_occupancy` re-derives both tier and fee, and the fee may cross tier boundaries in either direction — a self-transition on `CERTIFIED`. A license in `PENDING` or `CERTIFIED` may be suspended (`SUSPENDED`), and a suspended license may be reinstated — reinstatement always lands on `CERTIFIED` even when the suspension began from `PENDING`, certifying on the way back and recomputing the fee from the current occupancy. Revocation from `PENDING`, `CERTIFIED`, or `SUSPENDED` is `REVOKED` and terminal; the rights-grant cascade of §3.1 also lands licenses here.

Enforcement runs against the account, too. When a `ComplianceAuditor` concludes a residential account is serving a commercial audience, flagging commercial misuse moves the account `ACTIVE` → `SUSPENDED`, recording the request's `reason` as `commercial_flag_reason`, and immediately suspends access without touching billing: every `ACTIVE` subscription of the account has its `entitlement_state` pushed to `SUSPENDED` while its lifecycle `status` is left unchanged. Clearing the flag moves `SUSPENDED` → `ACTIVE`, nulls `commercial_flag_reason`, and restores every `ACTIVE` subscription whose `entitlement_state` is `SUSPENDED` back to `ENABLED` — but does not resurrect any `WITHDRAWN` entitlement. Either state may be closed by a `PlatformAdmin`, moving the account to `CLOSED` (terminal): every `ACTIVE` subscription is `CANCELLED` with `entitlement_state` `REVOKED`, and its `GRANTED` entitlements become `WITHDRAWN` with reason `SUBSCRIPTION_CANCELLED`.

### 3.9. Student Verification

A `ComplianceAuditor` or `PlatformAdmin` creates a **StudentVerification** for an account with `institution_name`, a `verification_method` of `SHEERID` or `DOCUMENT_REVIEW`, and a `valid_through` horizon that must be strictly after the verification timestamp. The record is born `VERIFIED`. On every logical-clock set, once the clock reaches or passes `valid_through`, the record auto-transitions `VERIFIED` → `EXPIRED`; thereafter any `STUDENT`-tier purchase for the account is rejected with `ERR_STUDENT_NOT_VERIFIED`, while subscriptions already purchased are unaffected. A `ComplianceAuditor` may also revoke a verification outright, `VERIFIED` → `REVOKED`, terminal.

### 3.10. Entitlement Overrides: The Goodwill Valve

For situations the rules cannot anticipate — a multi-hour outage, a regulatory carve-out, a gesture of goodwill — a `SupportAgent` grants an **EntitlementOverride** naming `account_id`, `game_id`, and a `reason_code` of `GOODWILL`, `SERVICE_OUTAGE`, or `REGULATORY`. The override is born `ACTIVE`, and the granting agent's `X-User-ID` is recorded as `created_by`. Its effect is singular and total: while `ACTIVE`, it forces the territory-check verdict `AVAILABLE` for that (account, game) pair, overriding any other link in the §3.6 chain. Rescinding moves `ACTIVE` → `RESCINDED` (terminal) and is permitted only to the agent recorded as `created_by` — any other agent, even another `SupportAgent`, is `ERR_NOT_OWNER`.

### 3.11. Multiview Sessions and the Features Read

Two companion capabilities ride on the subscription. The first is a computed read, the subscription's features, which aggregates three things fresh on every call: `multiview` — true exactly when the subscription's offer snapshot has `includes_multiview` and the `entitlement_state` is `ENABLED`; `companion` — the same for `includes_companion`; and `package_games_available_this_week` — the count of the subscription's entitlement rows in `status` `GRANTED` whose `week_index` equals the season week containing the current logical-clock instant, minus those rows whose game's `home_market_code` equals the account's `billing_market_code`.

The second is the multiview session itself. Starting one requires the full eligibility chain of §2.8 in order: the subscription must be `ACTIVE` with `entitlement_state` `ENABLED` and an offer snapshot carrying multiview — failing that is `ERR_FEATURE_NOT_ENTITLED` (HTTP 403) — and the account must hold fewer than two active multiview sessions, the hard cap. An account already holding two active sessions is rejected with `ERR_MULTIVIEW_CAP_REACHED` (HTTP 409); holding exactly one, the start succeeds. The cap is enforced against the account's active sessions ordered by `created_at` ascending, and the oldest session is never auto-evicted — the new request is rejected instead. A successful start returns the new `multiview_session_id` and the account's resulting `active_count`; ending a session frees the slot and likewise reports the resulting `active_count`.

## 4. Endpoint Definitions

Operations that create a new resource — a rights grant, season, market, game, week slate, offer, account, student verification, venue license, subscription, territory check, complaint case, entitlement override, or multiview session — return `201 Created`. Operations that modify or transition an existing resource, and all reads, return `200 OK`. Request and response bodies for each operation are specified by the narratives of §2 and §3; the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/_payments/simulate` | Simulate the payment outcome for a pending subscription's initial charge | PlatformAdmin |
| POST | `/rights-grants` | Create a league rights grant | PlatformAdmin |
| GET | `/rights-grants` | List rights grants | PlatformAdmin, LeagueOps, ComplianceAuditor |
| GET | `/rights-grants/{id}` | Get a rights grant | PlatformAdmin, LeagueOps, ComplianceAuditor |
| POST | `/rights-grants/{id}/terminate` | Terminate a grant (cascades to seasons, subscriptions, entitlements, venue licenses) | PlatformAdmin |
| POST | `/seasons` | Create a season under a rights grant | LeagueOps, PlatformAdmin |
| GET | `/seasons` | List seasons | PlatformAdmin, LeagueOps, ComplianceAuditor, SupportAgent |
| GET | `/seasons/{id}` | Get a season | PlatformAdmin, LeagueOps, ComplianceAuditor, SupportAgent |
| POST | `/seasons/{id}/advance-phase` | Advance season phase (OCC on season version) | LeagueOps |
| POST | `/markets` | Create a broadcast market | LeagueOps, PlatformAdmin |
| GET | `/markets` | List markets | PlatformAdmin, LeagueOps, ComplianceAuditor, SupportAgent |
| GET | `/markets/{id}` | Get a market | PlatformAdmin, LeagueOps, ComplianceAuditor, SupportAgent |
| POST | `/games` | Schedule a game into a season week | LeagueOps, PlatformAdmin |
| GET | `/games` | List games | PlatformAdmin, LeagueOps, ComplianceAuditor, SupportAgent, Subscriber, VenueManager |
| GET | `/games/{id}` | Get a game | PlatformAdmin, LeagueOps, ComplianceAuditor, SupportAgent, Subscriber, VenueManager |
| POST | `/week-slates` | Create the weekly slate for a (season, week) pair | LeagueOps, PlatformAdmin |
| GET | `/week-slates` | List week slates | PlatformAdmin, LeagueOps, ComplianceAuditor, SupportAgent |
| GET | `/week-slates/{id}` | Get a week slate | PlatformAdmin, LeagueOps, ComplianceAuditor, SupportAgent |
| POST | `/week-slates/{id}/selections` | Add or remove a national broadcast selection (OCC on slate version) | LeagueOps |
| POST | `/week-slates/{id}/finalize` | Finalize the slate, snapshotting package-eligible games (OCC on slate version) | LeagueOps |
| POST | `/week-slates/{id}/reopen` | Reopen a finalized slate for corrections | LeagueOps |
| POST | `/week-slates/{id}/lock` | Lock the slate at or after the week's first kickoff | LeagueOps |
| POST | `/offers` | Create a purchasable offer for a season | PlatformAdmin |
| GET | `/offers` | List offers | PlatformAdmin, LeagueOps, SupportAgent, Subscriber |
| GET | `/offers/{id}` | Get an offer | PlatformAdmin, LeagueOps, SupportAgent, Subscriber |
| POST | `/offers/{id}/withdraw` | Withdraw an offer (existing subscriptions keep their snapshots) | PlatformAdmin |
| POST | `/accounts/register` | Register an account; resolves billing market from the billing ZIP | Anonymous |
| GET | `/accounts` | List accounts | PlatformAdmin, ComplianceAuditor, SupportAgent |
| GET | `/accounts/{id}` | Get an account | PlatformAdmin, ComplianceAuditor, SupportAgent |
| PUT | `/accounts/{id}` | Update account fields; a billing-ZIP change re-resolves the billing market | PlatformAdmin, SupportAgent |
| POST | `/accounts/{id}/flag-commercial-misuse` | Flag a residential account for commercial misuse | ComplianceAuditor |
| POST | `/accounts/{id}/clear-commercial-flag` | Clear the misuse flag and restore suspended entitlements | ComplianceAuditor |
| POST | `/accounts/{id}/close` | Close an account, cancelling its active subscriptions | PlatformAdmin |
| POST | `/student-verifications` | Create a student verification for an account | ComplianceAuditor, PlatformAdmin |
| GET | `/student-verifications` | List student verifications | ComplianceAuditor, PlatformAdmin, SupportAgent |
| GET | `/student-verifications/{id}` | Get a student verification | ComplianceAuditor, PlatformAdmin, SupportAgent |
| POST | `/student-verifications/{id}/revoke` | Revoke a verification | ComplianceAuditor |
| POST | `/venue-licenses` | Apply for a commercial venue license | VenueManager |
| GET | `/venue-licenses` | List venue licenses | ComplianceAuditor, PlatformAdmin, SupportAgent, VenueManager |
| GET | `/venue-licenses/{id}` | Get a venue license | ComplianceAuditor, PlatformAdmin, SupportAgent, VenueManager |
| POST | `/venue-licenses/{id}/certify` | Certify a pending license, deriving tier and fee | ComplianceAuditor |
| POST | `/venue-licenses/{id}/recertify` | Update certified occupancy, re-deriving tier and fee | ComplianceAuditor |
| POST | `/venue-licenses/{id}/suspend` | Suspend a license | ComplianceAuditor |
| POST | `/venue-licenses/{id}/reinstate` | Reinstate a suspended license, recomputing the fee | ComplianceAuditor |
| POST | `/venue-licenses/{id}/revoke` | Revoke a license (terminal) | ComplianceAuditor |
| POST | `/subscriptions` | Purchase an offer, creating a pending-payment subscription | Subscriber, VenueManager |
| GET | `/subscriptions` | List subscriptions | PlatformAdmin, SupportAgent, ComplianceAuditor |
| GET | `/subscriptions/{id}` | Get a subscription | PlatformAdmin, SupportAgent, ComplianceAuditor, Subscriber, VenueManager |
| POST | `/subscriptions/{id}/cancel` | Cancel an active subscription (owner only) | Subscriber, VenueManager |
| POST | `/subscriptions/{id}/suspend-entitlement` | Suspend the entitlement dimension | PlatformAdmin |
| POST | `/subscriptions/{id}/restore-entitlement` | Restore a suspended entitlement dimension | PlatformAdmin |
| GET | `/subscriptions/{id}/features` | Computed read of multiview/companion flags and this week's available package games | PlatformAdmin, SupportAgent, Subscriber, VenueManager |
| GET | `/subscriptions/{id}/payments` | List the payment ledger rows of a subscription | PlatformAdmin, SupportAgent, ComplianceAuditor |
| POST | `/territory-checks` | Run a device-location territory check, appending an immutable evidence row | Subscriber, VenueManager, SupportAgent |
| GET | `/territory-checks` | List territory checks | PlatformAdmin, SupportAgent, ComplianceAuditor |
| GET | `/territory-checks/{id}` | Get a territory check | PlatformAdmin, SupportAgent, ComplianceAuditor |
| GET | `/game-entitlements` | List game entitlements | PlatformAdmin, SupportAgent, ComplianceAuditor |
| GET | `/game-entitlements/{id}` | Get a game entitlement | PlatformAdmin, SupportAgent, ComplianceAuditor |
| POST | `/complaint-cases` | File a complaint | Subscriber, VenueManager |
| GET | `/complaint-cases` | List complaint cases | PlatformAdmin, SupportAgent, ComplianceAuditor |
| GET | `/complaint-cases/{id}` | Get a complaint case | PlatformAdmin, SupportAgent, ComplianceAuditor, Subscriber |
| POST | `/complaint-cases/{id}/resolve` | Resolve an open complaint (approve or deny) | SupportAgent |
| POST | `/complaint-cases/{id}/escalate` | Escalate an open complaint | SupportAgent |
| POST | `/complaint-cases/{id}/deescalate` | Return an escalated complaint to open | SupportAgent |
| POST | `/entitlement-overrides` | Grant a per-game entitlement override | SupportAgent |
| GET | `/entitlement-overrides` | List entitlement overrides | PlatformAdmin, SupportAgent, ComplianceAuditor |
| GET | `/entitlement-overrides/{id}` | Get an entitlement override | PlatformAdmin, SupportAgent, ComplianceAuditor |
| POST | `/entitlement-overrides/{id}/rescind` | Rescind an override (granting agent only) | SupportAgent |
| POST | `/multiview-sessions` | Start a multiview session (per-account active cap applies) | Subscriber, VenueManager |
| POST | `/multiview-sessions/{id}/end` | End a multiview session, freeing a slot | Subscriber, VenueManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_SLATE_VERSION` | 412 |
| `ERR_STALE_SEASON_VERSION` | 412 |
| `ERR_SEASON_CLOSED` | 409 |
| `ERR_OFFER_NOT_AVAILABLE` | 409 |
| `ERR_STUDENT_NOT_VERIFIED` | 422 |
| `ERR_ACCOUNT_KIND_MISMATCH` | 422 |
| `ERR_GAME_WEEK_MISMATCH` | 422 |
| `ERR_NATIONAL_SELECTION_CONFLICT` | 409 |
| `ERR_SLATE_LOCKED` | 409 |
| `ERR_MARKET_PREFIX_OVERLAP` | 409 |
| `ERR_SEASON_STRUCTURE` | 422 |
| `ERR_OCCUPANCY_CAP_EXCEEDED` | 422 |
| `ERR_COMPLAINT_WINDOW_EXPIRED` | 422 |
| `ERR_COMPLAINT_NOT_REFUNDABLE` | 422 |
| `ERR_REFUND_NOT_AVAILABLE` | 422 |
| `ERR_MULTIVIEW_CAP_REACHED` | 409 |
| `ERR_FEATURE_NOT_ENTITLED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
