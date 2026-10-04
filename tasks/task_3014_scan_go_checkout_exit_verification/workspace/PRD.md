# Scan-Go Checkout API — Product Requirements Document

## 1. Introduction

Self-checkout through a member's own phone has become a competitive necessity for warehouse-club retail, but it collapses three traditionally separate control points — price integrity, age-restricted merchandise compliance, and exit loss prevention — into a single unattended flow. This document specifies the Scan-Go Checkout API: the backend that lets a club member scan items into an in-app cart as they shop (including weighted produce), pay in-app against their membership-linked tender with instant savings applied, and leave the building through either a receipt-code door check or a computer-vision arch, with mismatches escalating into loss-prevention case work.

The system must behave correctly under degraded connectivity. A club whose network drops cannot leave members stranded mid-shop: sessions pause, restricted-item interception — which requires a live associate channel — is suspended rather than silently approved, and clubs may opt into provisional offline payment. When connectivity returns, sessions resume but any intercepts that expired during the outage stay expired. Club managers tune the whole posture per club: opening hours, early-shopping windows for PLUS-tier members, exit-verification mode, loss-prevention thresholds, and time-to-live values for receipt codes and pending intercepts.

Alongside the in-club scanning flow, the same platform stages curbside pickup orders into capacity-limited staging slots, and tracks member-level economics: lifetime charged amounts, a two-tier membership model, and a 2% cash-rewards accrual for PLUS members that moves through a provisional (pending) stage at pay time and a final (posted) stage at settlement, with voids clawing back what was never earned. A test-driving logical clock governs every time-dependent rule in the system, so window boundaries, TTLs, and age checks are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the headers are well-formed but the role is not permitted to call the endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly as follows:

- `Member` — a club member shopping via Scan-and-Go.
- `Associate` — club floor staff handling restricted-item interception, the exit door/arch, and curbside staging.
- `LossPreventionOfficer` — owns loss-prevention case work, payment voids, and member reinstatement.
- `ClubManager` — owns club configuration, connectivity posture, instant savings offers, and the operational closeout.
- `PlatformAdmin` — owns club creation, catalog maintenance, member registration, rewards settlement, and the logical clock.

Role identity is resolved as follows. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record; ownership checks on any resource that references a `Member` — scan sessions and curbside orders in particular — compare the resource's member foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` (HTTP 403). When `X-User-Role` is `Associate`, `LossPreventionOfficer`, `ClubManager`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where workflows require attribution — as `associate_id` on a resolved `RestrictedIntercept`, as `flagging_associate_id` on an `ExitVerification` or `LossPreventionCase`, as `staged_by_associate_id` on a staged `CurbsideOrder` — but never compares it to any entity's `id` for ownership purposes. All roles may call every read (GET) endpoint.

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

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Time-Dependent Rules

Every time-dependent rule in the system — offer validity windows, receipt-code expiry, intercept expiry, curbside window expiry, early-shopping gating, and age verification — is evaluated against a single server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` advances it through an admin-only test-driving capability that sets the logical clock to a supplied `to_iso8601` instant; the clock never falls back to wall-clock time on its own. Timestamps such as `paid_at` on a scan session record the logical-clock instant of the event they describe.

### 2.5. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, set at creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that increments by one on every mutation of the resource and underpins the optimistic concurrency control rules in §2.7. All ten entities — `Club`, `Member`, `CatalogItem`, `InstantSavingsOffer`, `ScanSession`, `ScanLine`, `RestrictedIntercept`, `ExitVerification`, `LossPreventionCase`, and `CurbsideOrder` — carry the full common-field set, including system-initiated mutations such as connectivity cascades and closeout sweeps, which update `updated_at` and increment `version` on each entity they touch.

### 2.6. Monetary Values and Rounding

All monetary amounts are integer cents. Where a calculation produces a fractional result — the weighted-item gross computation in §3.2 — the result is rounded to a whole number of cents using round-half-up, and the rounding is applied per line before line values are summed into cart totals. Cash-rewards accrual uses an integer floor rather than rounding (see §3.8). No monetary value is ever represented with decimal places in the API.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two. First, updating a club's configuration requires the request to carry `expected_club_version`, a non-optional field holding the version of the `Club` the caller last observed; if it no longer matches the club's current `version` — because another `ClubManager` has saved a newer configuration in the meantime — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). Second, rescheduling a curbside order requires the request to carry `expected_curbside_order_version`, likewise non-optional, matched against the `CurbsideOrder`'s current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.8. Nested Resource Retrieval and Validation Order

When an endpoint path contains multiple resource identifiers, the system validates their existence left to right — the club before the catalog item beneath it, the session before the line beneath it — and rejects with the not-found error for the first missing identifier. Each resource family has its own scoped code: `ERR_CLUB_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_SCAN_SESSION_NOT_FOUND`, `ERR_SCAN_LINE_NOT_FOUND`, `ERR_INTERCEPT_NOT_FOUND`, `ERR_EXIT_VERIFICATION_NOT_FOUND`, `ERR_LP_CASE_NOT_FOUND`, and `ERR_CURBSIDE_ORDER_NOT_FOUND`, all HTTP 404. Beyond raw existence, cross-parent references are also rejected as not found: a scan line addressed under the wrong session, an intercept addressed under the wrong club, or a catalog item offered to a session at a different club all yield the corresponding scoped 404 rather than a generic conflict.

Across a single request, validation proceeds in a fixed priority order so that overlapping failures surface deterministically. Authentication and role checks come first (missing or invalid headers, then role authorization, then member-ownership checks), followed by resource existence and the optimistic-concurrency check, then target-state validity, then business-safety gates (restricted-item and intercept rules), then temporal gates (windows and shopping-hours), then aggregate and referential constraints (capacities, conflicts, one-active-session), and finally fiscal gates (cart non-empty, tender OK). Malformed-request checks — missing required fields, type mismatches, pricing-mode-inconsistent payloads — are evaluated first of all when the request cannot even be parsed, but among business failures they rank last. As a concrete example: payment on a session that both has a pending intercept and an empty cart fails with the intercept error, because safety outranks fiscal checks; and a club update with a stale version fails with `ERR_STALE_VERSION` before any business rule about the new configuration values is evaluated.

### 2.9. Connectivity Posture and Club Enablement

Each club carries a `connectivity_posture` of `ONLINE`, `DEGRADED`, or `OFFLINE_FALLBACK`, initially `ONLINE` and changeable only through the connectivity-setting operation by a `ClubManager`, whose request carries the desired `posture`. Posture gates behavior throughout the system: instant savings evaluate only while `ONLINE`; new scan sessions cannot be created while `OFFLINE_FALLBACK`; and moving a club to `OFFLINE_FALLBACK` pauses every active session at that club and expires their pending intercepts (§3.5). Separately, the `scan_go_enabled` flag on a club — defaulting to enabled — is a static kill switch: while it is off, no new scan sessions may be started at that club regardless of posture. A club may also opt into `allow_offline_payment` (default off), which permits paused sessions to complete payment against provisional totals during an outage (§3.4).

### 2.10. Verification Modes and Loss-Prevention Thresholds

A club declares which exit-verification methods it operates through `exit_verification_mode`: `RECEIPT_CODE`, `CV_ARCH`, or `BOTH`. Requesting a method the club has not enabled is rejected with `ERR_VERIFICATION_METHOD_NOT_ENABLED`. Two club-tunable thresholds drive loss prevention: `lp_unscanned_threshold` (default 2) is the minimum count of apparently-unscanned physical items that flips a computer-vision exit check to a mismatch and opens a case, and `lp_suspend_strikes` (default 3) is the number of accumulated strikes at which a member is automatically suspended. Two TTL values, also club-tunable, govern expiry: `receipt_code_ttl_minutes` (default 30) bounds how long a receipt code remains valid after payment, and `intercept_ttl_minutes` (default 10) bounds how long a pending restricted-item intercept may await an associate before it expires at closeout. A final club setting, `staging_slot_capacity` (default 2), bounds how many curbside orders may concurrently occupy one staging slot label across overlapping windows.

## 3. Business Logic & Workflows

### 3.1. Clubs, Catalog, and Offers: Setting the Stage

A `PlatformAdmin` onboards a club by supplying its `name`, its `open_minute` (the minute-of-day, from 0 to 1439, at which normal shopping opens to all members), and its `early_shopping_start_minute` (the minute-of-day at which the PLUS-tier early window begins, which must be strictly earlier than `open_minute`), together with the club's `exit_verification_mode` and any desired overrides for the defaults described in §2.9 and §2.10 — `scan_go_enabled`, `allow_offline_payment`, `lp_unscanned_threshold`, `lp_suspend_strikes`, `staging_slot_capacity`, `receipt_code_ttl_minutes`, and `intercept_ttl_minutes`. A `ClubManager` later adjusts the same configuration through the OCC-guarded update described in §2.7, which increments the club's `version` by one on every successful save.

Within a club, a `PlatformAdmin` maintains the catalog. Each item carries a `sku` unique within its club, a display `item_name`, and a `pricing_mode` of `UNIT` or `WEIGHTED`. A `UNIT` item must be priced through `unit_price_cents`, the price per piece; a `WEIGHTED` item must be priced through `price_per_pound_cents`, the price per pound — each field is required exactly when the item has the matching pricing mode, and a payload inconsistent with the item's pricing mode is rejected with `ERR_INVALID_REQUEST`. Items also carry a `restricted_class` of `NONE`, `ALCOHOL`, `TOBACCO`, or `PHARMACY` (defaulting to `NONE`) and an `early_hours_eligible` flag (defaulting to true) marking whether the item may be scanned during the early-shopping window. Items are born `ACTIVE`; a `PlatformAdmin` may reprice an item or flip its `status` to `DELISTED` at any time, and a `DELISTED` item can no longer be newly scanned — a scan attempt against it is rejected as `ERR_CATALOG_ITEM_NOT_FOUND`. Catalog maintenance is a deliberate source of divergence between what a member saw while shopping and what they are charged at payment (§3.4). For recall audits, the platform can list every scan line that references a given catalog item.

Members themselves are onboarded by a `PlatformAdmin`: registration records the member's `tier` (`CLUB` or `PLUS`), their four-digit `birth_year` used later for age verification, the `home_club_id` of their home club, and an optional `tender_status` that defaults to `OK`. A new member is `ACTIVE` with zeroed reward balances, zero lifetime charges, and zero strikes.

Instant savings are authored per club by a `ClubManager`. An `InstantSavingsOffer` names the `catalog_item_id` it discounts, a `discount_cents` amount interpreted per unit for a `UNIT` item and per commenced pound for a `WEIGHTED` item, a validity window from `valid_from_iso` to `valid_to_iso` that is closed at both ends — the offer applies at exactly its start instant and at exactly its end instant — a `tier_eligibility` of `ALL` or `PLUS_ONLY` (defaulting to `ALL`), and a `per_member_limit` capping how many discounted units one member may redeem across all of that member's sessions. The window must be internally sane: a `valid_to_iso` earlier than `valid_from_iso` is rejected with `ERR_OFFER_WINDOW_INVALID`. Windows for the same club and item may never overlap, and because they are closed intervals, touching endpoints count as overlap: an existing window ending at a given instant blocks a new window beginning at that same instant, and any such conflict is rejected with `ERR_OFFER_WINDOW_CONFLICT`.

### 3.2. Scanning: Lines, Prices, and Instant Savings

A member begins shopping by creating a scan session against a `club_id`; the creating member's identity is taken from `X-User-ID` and recorded as the session's `member_id`. Session creation is refused with `ERR_CLUB_SCAN_GO_DISABLED` when the club's `scan_go_enabled` flag is off, with `ERR_CLUB_OFFLINE` while the club's posture is `OFFLINE_FALLBACK`, with `ERR_MEMBER_INACTIVE` when the member is `SUSPENDED`, and with `ERR_SESSION_ALREADY_ACTIVE` when the member already has a non-terminal session at that same club — only one active session per member per club is permitted. The early-shopping gate also applies at creation (§3.3). A new session starts `OPEN` with a `provisional_total_cents` of zero.

Each scan into a session names a `catalog_item_id` and, depending on the item's pricing mode, either a `quantity` (required for a `UNIT` item, and it must be at least 1, else `ERR_INVALID_QUANTITY`) or a `weight_grams` scale reading (required for a `WEIGHTED` item, and it must be strictly greater than 0, else `ERR_INVALID_WEIGHT`). The scanned item must belong to the club the session is shopping at and must be `ACTIVE`; otherwise the scan is rejected with `ERR_CATALOG_ITEM_NOT_FOUND`. Scanning is permitted while the session is `OPEN`, `REVIEW_HOLD`, or `OFFLINE_PAUSED`; in any other state the attempt is rejected with `ERR_SESSION_NOT_OPEN`.

An ordinary line is born in the `SCANNED` state; its lifecycle runs `SCANNED`, possibly through `INTERCEPTED` and `CLEARED` for restricted merchandise, to the terminal `REMOVED` state.

Every scan line is a snapshot. At scan time the server records the item's `pricing_mode_snapshot`, its `unit_price_cents_snapshot` (for a `UNIT` item; null otherwise), its `price_per_pound_cents_snapshot` (for a `WEIGHTED` item; null otherwise), and its `restricted_class_snapshot`, so that the provisional cart always reflects what the member saw at scan time even if the catalog changes mid-shop. Lines are numbered by a `scan_seq` that starts at 1 and increases monotonically within the session.

The line's gross is computed per line and rounded per line. For a `UNIT` line, `line_gross_cents` is the quantity multiplied by the unit price. For a `WEIGHTED` line, `line_gross_cents` is the weight in grams multiplied by the per-pound price, divided by 454 (the number of grams in a pound), rounded half-up to a whole cent. Rounding strictly precedes summation: two 150-gram bags of a 250-cents-per-pound item contribute 83 cents each and total 166 cents, never 165.

Instant savings then evaluate against the line. If the club's connectivity posture is anything other than `ONLINE` at evaluation time, no offer applies and `line_savings_cents` is zero. Otherwise the system finds the offer for the session's club and the scanned item whose closed validity window contains the current logical-clock instant; if none exists, or the offer is `PLUS_ONLY` and the member's `tier` is `CLUB`, no savings apply. When an offer does apply, the discounted units on the line — recorded as `offer_units_applied` — are the line's units (its quantity for a `UNIT` item, or its commenced pounds for a `WEIGHTED` item) capped by the member's remaining allowance under the offer's `per_member_limit`, where the allowance already consumed is the sum of `offer_units_applied` across all of that member's lines carrying this offer on sessions that have not been voided and lines that have not been removed; the applied units never drop below zero. Commenced pounds are counted by rounding up: 454 grams is one commenced pound, and anything beyond that — 455 grams, 500 grams — is two. The line's `line_savings_cents` is the applied units multiplied by the offer's `discount_cents`, and the applied offer is remembered on the line as `offer_id_applied` (null when no offer applied). The line's `line_total_cents` is its gross minus its savings, floored at zero so a line can never go negative.

The session's `provisional_total_cents` is the sum of `line_total_cents` over all non-`REMOVED` lines, recomputed on every line addition, removal, or intercept resolution, always from scan-time snapshots and scan-time offer evaluation. Alongside it, the session's `scanned_item_count` tracks physical items: the sum of `quantity` over non-`REMOVED` `UNIT` lines plus the count of non-`REMOVED` `WEIGHTED` lines — a bag of produce is exactly one physical item no matter its weight. This count is later compared against what the exit arch observes.

A member may remove any line of their own while the session is `OPEN`, `REVIEW_HOLD`, or `OFFLINE_PAUSED`, moving the line to `REMOVED` (its terminal state); the session's provisional total and item count are recomputed, and any offer allowance the line had consumed is released back to the member's remaining redemption balance.

### 3.3. Shopping Hours and the Early Window

Whether a member may shop at a given moment depends on the logical clock's minute-of-day in UTC — the clock's hour multiplied by 60 plus its minute — compared against the club's two configured boundaries. At or after `open_minute`, any member may shop normally. Before `early_shopping_start_minute`, no member may start a session at all, and the attempt is rejected with `ERR_EARLY_HOURS_NOT_ELIGIBLE` regardless of tier. In between — the early-shopping window, open at exactly `early_shopping_start_minute` and closed the moment `open_minute` arrives — session creation is reserved for members whose `tier` is `PLUS`; a `CLUB` member attempting to start a session inside the window is likewise rejected with `ERR_EARLY_HOURS_NOT_ELIGIBLE`.

Restricted merchandise is never sold during the early window: scanning an item whose `restricted_class` is `ALCOHOL`, `TOBACCO`, or `PHARMACY` while the clock sits in the early window is rejected outright with `ERR_RESTRICTED_BLOCKED_EARLY_HOURS`. An item whose `early_hours_eligible` flag is false may not be scanned during the early window either.

### 3.4. Restricted-Item Interception and Payment

Restricted merchandise — anything whose scan-time `restricted_class_snapshot` is `ALCOHOL`, `TOBACCO`, or `PHARMACY` — cannot simply be scanned like groceries. While the club is `ONLINE` and outside the early-shopping window, scanning a restricted item does not reject the scan; instead the line is born `INTERCEPTED`, a `RestrictedIntercept` is created `PENDING` for that line (one intercept per line, addressed back to it via `scan_line_id`, and denormalized with the session's `club_id` so associates can queue by club), and the session itself moves from `OPEN` to `REVIEW_HOLD`. While the club is `OFFLINE_FALLBACK` there is no associate channel at all, so scanning a restricted item is rejected with `ERR_RESTRICTED_BLOCKED_OFFLINE`; during the early window it is rejected as described in §3.3.

An `Associate` resolves a pending intercept by submitting a `decision` of `APPROVE` or `DENY`. Resolving an intercept that is no longer `PENDING` is rejected with `ERR_INTERCEPT_NOT_PENDING`. Approval carries compliance gates that depend on the class. For `ALCOHOL` and `TOBACCO`, the associate must attest `birth_year_verified` as true, and the member's age — the current clock year minus the member's `birth_year` — must be at least 21; failing either condition rejects the approval with `ERR_AGE_VERIFICATION_FAILED`. For `PHARMACY`, the associate must supply a non-empty `pharmacist_note`, or the resolution is rejected with `ERR_INVALID_REQUEST`. Denial has no preconditions. On approval, the intercept becomes `APPROVED`, the line moves `INTERCEPTED → CLEARED`, the resolving associate's identity is recorded as the intercept's `associate_id`, and the line's savings and total are finalized. On denial, the intercept becomes `DENIED`, the line moves `INTERCEPTED → REMOVED`, and the session's provisional totals are recomputed with the line excluded. In both cases, once no `PENDING` intercepts remain for the session, the session reopens from `REVIEW_HOLD` to `OPEN`. A pending intercept can also die without an associate: the closeout sweep expires any intercept that has sat `PENDING` longer than the club's `intercept_ttl_minutes` (measured from its creation), and expiry cascades exactly like a denial — intercept `EXPIRED`, line `REMOVED`, totals recomputed, session reopened if clear.

Payment is the member's in-app checkout of their own session, and it re-prices everything. Paying requires the member to be `ACTIVE` (else `ERR_MEMBER_INACTIVE`), no `PENDING` intercept on the session (else `ERR_INTERCEPT_PENDING` — which is also why paying from `REVIEW_HOLD` is unreachable in practice until its intercepts resolve), at least one non-`REMOVED` line (else `ERR_EMPTY_CART`), and a `tender_status` of `OK` on the member's membership-linked tender — a tender in the `DECLINED` state blocks payment with `ERR_TENDER_DECLINED` (HTTP 402). When payment succeeds, the session moves to `PAID`: the server computes `final_total_cents` by re-pricing every non-`REMOVED` line against the current catalog prices and offers evaluated at the pay-time clock (not the scan-time snapshots), mints the session's `receipt_code`, stamps `paid_at` with the logical clock, adds `final_total_cents` to the member's `lifetime_charged_cents`, and — for `PLUS` members — accrues pending cash rewards (§3.8). The session also records `qualifying_cents` at pay time: the portion of `final_total_cents` attributable to unrestricted merchandise, computed as the final total minus the `line_total_cents` of every non-`REMOVED` line whose `restricted_class_snapshot` is not `NONE`. Because the provisional and final totals are computed at different instants against potentially different prices and offer windows, they can diverge for identical cart contents.

There is one deliberate exception to re-pricing: a session in `OFFLINE_PAUSED` may be paid only when the club has `allow_offline_payment` enabled (otherwise the attempt is rejected with `ERR_SESSION_NOT_OPEN`), and in that case `final_total_cents` is taken as the `provisional_total_cents` with no re-pricing at all — pending intercepts cannot exist on such a session because the outage already expired them, while the empty-cart and tender checks still apply. All other ledger side effects of payment are identical to the online path.

After payment, a member may walk to the exit and begin exit verification (§3.6), or abandon nothing further — but an unpaid session in `OPEN`, `REVIEW_HOLD`, or `OFFLINE_PAUSED` may instead be abandoned by its member, which moves the session to its terminal `ABANDONED` state, removes every non-`REMOVED` line, and expires any `PENDING` intercepts. (From `OFFLINE_PAUSED` there can be no pending intercepts left to expire.) Separately, a `LossPreventionOfficer` may void a session in `PAID`, `EXIT_PENDING`, or `FLAGGED` — voiding from any other state is rejected with `ERR_SESSION_NOT_VOIDABLE`. A void moves the session to `VOIDED`, sets `refunded_cents` equal to `final_total_cents` as a full compensating refund, subtracts `final_total_cents` from the member's `lifetime_charged_cents`, claws the session's `rewards_contribution_cents` back out of the member's `cash_rewards_pending_cents` (never letting it drop below zero), invalidates the receipt code, and expires any `PENDING` exit verifications.

### 3.5. Connectivity Failover

Connectivity posture changes are system-driven cascades, not passive flags. When a `ClubManager` sets a club's posture to `OFFLINE_FALLBACK`, every session at that club in `OPEN` or `REVIEW_HOLD` moves to `OFFLINE_PAUSED`; for sessions that were in `REVIEW_HOLD`, all of their `PENDING` intercepts are expired, each expired intercept's line is removed, and provisional totals are recomputed. When the posture is set back to `ONLINE` or `DEGRADED`, every `OFFLINE_PAUSED` session at the club returns to `OPEN` — sessions always resume to `OPEN`, never back to `REVIEW_HOLD`, because the intercepts that expired during the outage stay `EXPIRED` and their lines stay `REMOVED`. Note that `DEGRADED` connectivity still blocks instant-savings evaluation (§3.2) but permits sessions to be created and paid with full re-pricing; only `OFFLINE_FALLBACK` pauses sessions, blocks new sessions with `ERR_CLUB_OFFLINE`, blocks restricted scans with `ERR_RESTRICTED_BLOCKED_OFFLINE`, and gates payment behind `allow_offline_payment`.

### 3.6. Exit Verification and Mismatch Handling

Once a session is `PAID` — attempting exit verification earlier is rejected with `ERR_SESSION_NOT_PAID` — the member begins exit verification, optionally naming a `method` of `RECEIPT_CODE` or `CV_ARCH`; when the method is omitted it is taken from the club's `exit_verification_mode`. A method the club has not enabled is rejected with `ERR_VERIFICATION_METHOD_NOT_ENABLED`. This creates an `ExitVerification` in `PENDING`, snapshots the session's `scanned_item_count` into the verification's `expected_item_count`, records the session's `club_id` on the verification, and moves the session `PAID → EXIT_PENDING`.

A verification's lifecycle runs from `PENDING` to one of the terminal states `VERIFIED`, `CONFIRMED`, or `EXPIRED`, with the non-terminal `MISMATCH` state in between; reaching `VERIFIED` is what releases the session to `EXITED`.

From there the door flow depends on the method. For a receipt-code verification, a door `Associate` scans the code the member presents: the submitted `receipt_code` is compared against the session's minted code, and a match moves the verification `PENDING → VERIFIED` and the session `EXIT_PENDING → EXITED`. For a computer-vision verification, the arch gateway submits an `observed_item_count`, which the server records on the verification as its `cv_observed_item_count` (null until the report arrives); the unscanned count is the observed count minus the verification's `expected_item_count`, and if that difference is below the club's `lp_unscanned_threshold` — including when the arch observes no more than was scanned — the verification moves `PENDING → VERIFIED` and the session to `EXITED`. Both flows require the verification to still be `PENDING` (else `ERR_VERIFICATION_NOT_PENDING`) and require the method to match the verification's own method — a receipt-code check against a `CV_ARCH` verification, or vice versa, is rejected with `ERR_VERIFICATION_METHOD_NOT_ENABLED`.

A mismatch is the boundary case, inclusive: an unscanned count greater than or equal to `lp_unscanned_threshold` flips the verification to `MISMATCH`, and a receipt-code check with the wrong code does the same. Either way, the associate whose action produced the mismatch is recorded as the verification's `flagging_associate_id`, the session moves `EXIT_PENDING → FLAGGED`, and a `LossPreventionCase` opens in `OPEN` (§3.7).

An associate handles a `MISMATCH` verification — acting on a verification in any other state is rejected with `ERR_VERIFICATION_NOT_MISMATCHED` — with one of three `action` values. `RESCAN` abandons the current verification (it stays `MISMATCH`, superseded), creates a fresh `PENDING` verification, and returns the session `FLAGGED → EXIT_PENDING` for another pass. `CLEAR` moves the verification `MISMATCH → VERIFIED` and the session `FLAGGED → EXITED`, but only once every loss-prevention case for the session has been resolved; an unresolved case blocks the clear and the attempt is rejected with `ERR_LP_CASE_NOT_OPEN`. `CONFIRM` moves the verification to its terminal `CONFIRMED` state and leaves the session `FLAGGED`, awaiting case resolution or a payment void.

Receipt codes do not live forever. The closeout sweep flags any session still sitting `EXIT_PENDING` whose `paid_at` lies more than the club's `receipt_code_ttl_minutes` in the past: its `PENDING` verifications move to `EXPIRED`, the session moves to `FLAGGED`, and a receipt-expiry loss-prevention case opens (§3.7). Verifications also expire when their session is voided (§3.4).

### 3.7. Loss-Prevention Cases and Segregation of Duties

Every mismatch and every receipt-code expiry opens a `LossPreventionCase` in `OPEN`, recording the offending `session_id`, the offending `member_id`, the `club_id` where it was detected, and a `source` of `CV_MISMATCH` or `RECEIPT_EXPIRY`. For a computer-vision mismatch the case records the `unscanned_count` — the observed count minus the expected count — and the `flagging_associate_id` of the associate whose report opened it; a receipt-code mismatch likewise records the verifying associate, with an `unscanned_count` of zero. A receipt-expiry case records no flagging associate and an `unscanned_count` of zero. The case's `tier` is `SEVERE` when the unscanned count is at least twice the club's `lp_unscanned_threshold`, and `REVIEW` otherwise — receipt-expiry cases are therefore always `REVIEW`.

Opening a case strikes the member: `unscanned_strikes` increases by one, and the moment a member's strikes reach the club's `lp_suspend_strikes` — the boundary is inclusive — the member's `status` flips from `ACTIVE` to `SUSPENDED`, after which they can no longer create scan sessions or pay.

Case work belongs to the `LossPreventionOfficer`. A case in `OPEN` may be acknowledged (`OPEN → ACKNOWLEDGED`) or escalated directly (`OPEN → ESCALATED`), and an `ACKNOWLEDGED` case may likewise be escalated (`ACKNOWLEDGED → ESCALATED`). Resolution — from `OPEN`, `ACKNOWLEDGED`, or `ESCALATED` — records an `outcome` of `DISMISSED` or `CONFIRMED` and moves the case to its terminal `RESOLVED` state; any of these operations against a `RESOLVED` case is rejected with `ERR_LP_CASE_NOT_OPEN`. A dismissal gives the member their strike back: `unscanned_strikes` decreases by one, never below zero. Segregation of duties is enforced at resolution: the resolving officer's `X-User-ID` must differ from the case's `flagging_associate_id`, and a violation is rejected with `ERR_SO_DUTY_VIOLATION` (HTTP 403) — the associate who flagged a mismatch can never close their own case. A suspended member is restored by a `LossPreventionOfficer` through reinstatement, which returns the member to `ACTIVE` and zeroes their `unscanned_strikes`.

### 3.8. Cash Rewards: Pending Accrual and Settlement

Cash rewards are a `PLUS`-tier benefit accruing at 2% of qualifying spend, tracked in two stages so that voids never become redeemable value. At pay time, a `PLUS` member's session contributes the integer floor of `qualifying_cents` multiplied by 2 and divided by 100; this contribution is added to the member's `cash_rewards_pending_cents` and recorded on the session as `rewards_contribution_cents`. `CLUB`-tier members accrue nothing — both stages are always zero for them.

Settlement, run by a `PlatformAdmin`, folds pending value into the member's `cash_rewards_posted_cents`. It walks every session of the member whose `rewards_settled` flag is still false and whose status is `PAID`, `EXIT_PENDING`, `FLAGGED`, or `EXITED`, adds the integer floor of each such session's `qualifying_cents` multiplied by 2 and divided by 100 into the posted balance, and marks each of those sessions' `rewards_settled` true. Sessions in `VOIDED` contribute nothing at settle time — their pending contribution was already clawed back by the void (§3.4) — which is exactly how the pending and posted figures diverge for identical payment data when a session is voided between pay and settle.

### 3.9. Curbside Pickup: Staging Slots and Pickup Windows

Curbside pickup runs alongside in-club scanning but on its own lifecycle. A member places an order at a club with an `item_count` of at least 1; the order is born `PLACED` with the creating member's identity recorded from `X-User-ID`. An `Associate` then stages the order by assigning a `staging_slot_label` and a pickup window from `window_start_iso` to `window_end_iso`, moving the order `PLACED → STAGING`. The window is half-open: it includes its start instant and excludes its end instant, so back-to-back windows — one ending at 11:00 and another beginning at 11:00 — do not overlap. A window whose end is not strictly after its start is rejected with `ERR_SLOT_WINDOW_INVALID`.

Staging slots are capacity-gated. The occupancy of a slot label over a candidate window is the number of orders at the same club, in `STAGING` or `STAGED`, sharing that label, whose windows overlap the candidate — overlap meaning each existing window starts strictly before the candidate ends and the candidate starts strictly before the existing window ends. Staging is rejected with `ERR_SLOT_CAPACITY_EXCEEDED` when that occupancy already equals the club's `staging_slot_capacity`. Once physically loaded, the order is marked staged (`STAGING → STAGED`) and the acting associate's identity is recorded as `staged_by_associate_id`.

The member picks up a `STAGED` order — pickup from any other state is rejected with `ERR_CURBSIDE_NOT_CANCELLABLE`'s sibling `ERR_CURBSIDE_NOT_STAGED` — which moves the order to its terminal `PICKED_UP` state and releases the slot occupancy. The member may cancel their own order from `PLACED`, `STAGING`, or `STAGED`; cancelling a staged or staging order likewise releases the slot, while cancelling a terminal order (`PICKED_UP`, `CANCELLED`, or `EXPIRED`) is rejected with `ERR_CURBSIDE_NOT_CANCELLABLE`. A member may also reschedule their own order from `STAGING` or `STAGED`, replacing the `staging_slot_label`, `window_start_iso`, and `window_end_iso` wholesale; the new window must satisfy the same validity and capacity rules, except that the order's own current occupancy does not count against it, and a `STAGED` order is demoted back to `STAGING` by the move. Rescheduling is the OCC-guarded operation of §2.7: the request must carry `expected_curbside_order_version`, a stale value is rejected with `ERR_STALE_VERSION`, and a successful reschedule increments the order's `version` by one. All of pickup, cancel, and reschedule are member-scoped actions: the caller's `X-User-ID` must equal the order's `member_id`, or the attempt is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`.

Finally, staged orders are not held indefinitely: the closeout sweep expires any `STAGED` order whose `window_end_iso` lies more than 60 minutes in the past, moving it to `EXPIRED` and releasing its slot.

### 3.10. The Closeout Sweep

A `ClubManager` runs a periodic operational closeout for a club, which performs three expiry passes in one call against the logical clock. First, every `PENDING` restricted intercept at the club older than the club's `intercept_ttl_minutes` expires, cascading as a denial: line removed, provisional totals recomputed, and the session reopened to `OPEN` if no pending intercepts remain (§3.4). Second, every session still `EXIT_PENDING` whose receipt code has outlived `receipt_code_ttl_minutes` is flagged: its pending verifications expire, the session moves to `FLAGGED`, a `RECEIPT_EXPIRY` loss-prevention case opens, and the strike-and-suspension cascade of §3.7 applies (§3.6). Third, every `STAGED` curbside order more than 60 minutes past its window end expires and releases its slot (§3.9).

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Readers should refer to §3 for the full request and response semantics of each operation — the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clubs` | Create a club | PlatformAdmin |
| GET | `/clubs/{id}` | Get a club | Any |
| PATCH | `/clubs/{id}` | Update club configuration (OCC-guarded) | ClubManager |
| POST | `/clubs/{id}/connectivity` | Set club connectivity posture | ClubManager |
| POST | `/clubs/{id}/run-closeout` | Run the operational closeout sweep | ClubManager |
| POST | `/clubs/{id}/catalog-items` | Create a catalog item | PlatformAdmin |
| GET | `/catalog-items/{id}` | Get a catalog item | Any |
| PATCH | `/catalog-items/{id}` | Reprice or delist a catalog item | PlatformAdmin |
| GET | `/clubs/{id}/catalog-items` | List a club's catalog items | Any |
| GET | `/catalog-items/{id}/scan-lines` | Recall audit: scan lines referencing an item | Any |
| POST | `/clubs/{id}/instant-savings-offers` | Create an instant savings offer | ClubManager |
| GET | `/instant-savings-offers/{id}` | Get an offer | Any |
| GET | `/instant-savings-offers` | List offers with optional filters | Any |
| POST | `/members` | Register a member | PlatformAdmin |
| GET | `/members/{id}` | Get a member | Any |
| GET | `/members` | List members with optional filters | Any |
| GET | `/members/{id}/scan-sessions` | List a member's scan sessions | Any |
| POST | `/members/{id}/reinstate` | Reinstate a suspended member | LossPreventionOfficer |
| POST | `/members/{id}/rewards/settle` | Post pending rewards to posted | PlatformAdmin |
| POST | `/scan-sessions` | Start a scan-and-go session | Member |
| GET | `/scan-sessions/{id}` | Get a scan session | Any |
| GET | `/scan-sessions` | List scan sessions with optional filters | Any |
| POST | `/scan-sessions/{id}/lines` | Scan an item into the session | Member |
| GET | `/scan-sessions/{id}/lines` | List lines of a session | Any |
| GET | `/scan-lines/{id}` | Get a scan line | Any |
| POST | `/scan-lines/{id}/remove` | Remove a line from an unpaid session | Member |
| POST | `/scan-sessions/{id}/pay` | Pay the cart total in-app | Member |
| POST | `/scan-sessions/{id}/void-payment` | Void a paid session with full refund | LossPreventionOfficer |
| POST | `/scan-sessions/{id}/exit-scan` | Begin exit verification | Member |
| POST | `/scan-sessions/{id}/abandon` | Abandon an unpaid session | Member |
| GET | `/scan-sessions/{id}/intercepts` | List intercepts of a session | Any |
| GET | `/intercepts/{id}` | Get an intercept | Any |
| GET | `/intercepts` | List intercepts with optional filters | Any |
| POST | `/intercepts/{id}/resolve` | Approve or deny a restricted intercept | Associate |
| GET | `/scan-sessions/{id}/exit-verifications` | List exit verifications of a session | Any |
| GET | `/exit-verifications/{id}` | Get an exit verification | Any |
| GET | `/exit-verifications` | List exit verifications with optional filters | Any |
| POST | `/exit-verifications/{id}/verify-receipt` | Door associate scans the receipt code | Associate |
| POST | `/exit-verifications/{id}/cv-report` | CV arch reports observed item count | Associate |
| POST | `/exit-verifications/{id}/resolve-mismatch` | Resolve a MISMATCH verification | Associate |
| GET | `/loss-prevention-cases/{id}` | Get a loss-prevention case | Any |
| GET | `/loss-prevention-cases` | List loss-prevention cases with optional filters | Any |
| POST | `/loss-prevention-cases/{id}/acknowledge` | Acknowledge an LP case | LossPreventionOfficer |
| POST | `/loss-prevention-cases/{id}/escalate` | Escalate an LP case | LossPreventionOfficer |
| POST | `/loss-prevention-cases/{id}/resolve` | Resolve an LP case (segregation of duties) | LossPreventionOfficer |
| POST | `/clubs/{id}/curbside-orders` | Place a curbside pickup order | Member |
| GET | `/curbside-orders/{id}` | Get a curbside order | Any |
| GET | `/curbside-orders` | List curbside orders with optional filters | Any |
| GET | `/clubs/{id}/curbside-orders` | List a club's curbside orders | Any |
| POST | `/curbside-orders/{id}/stage` | Stage a placed order into a slot and window | Associate |
| POST | `/curbside-orders/{id}/mark-staged` | Mark a staging order as physically staged | Associate |
| POST | `/curbside-orders/{id}/pickup` | Member picks up a staged order | Member |
| POST | `/curbside-orders/{id}/cancel` | Cancel a non-terminal curbside order | Member |
| POST | `/curbside-orders/{id}/reschedule` | Reschedule slot/window (OCC-guarded) | Member |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CLUB_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_CATALOG_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_SCAN_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_SCAN_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_INTERCEPT_NOT_FOUND` | 404 Not Found |
| `ERR_EXIT_VERIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_LP_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CURBSIDE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CLUB_SCAN_GO_DISABLED` | 409 Conflict |
| `ERR_CLUB_OFFLINE` | 409 Conflict |
| `ERR_MEMBER_INACTIVE` | 409 Conflict |
| `ERR_SESSION_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_SESSION_NOT_OPEN` | 409 Conflict |
| `ERR_EARLY_HOURS_NOT_ELIGIBLE` | 403 Forbidden |
| `ERR_RESTRICTED_BLOCKED_OFFLINE` | 409 Conflict |
| `ERR_RESTRICTED_BLOCKED_EARLY_HOURS` | 409 Conflict |
| `ERR_AGE_VERIFICATION_FAILED` | 403 Forbidden |
| `ERR_INTERCEPT_PENDING` | 409 Conflict |
| `ERR_INTERCEPT_NOT_PENDING` | 409 Conflict |
| `ERR_INVALID_QUANTITY` | 400 Bad Request |
| `ERR_INVALID_WEIGHT` | 400 Bad Request |
| `ERR_EMPTY_CART` | 409 Conflict |
| `ERR_TENDER_DECLINED` | 402 Payment Required |
| `ERR_SESSION_NOT_PAID` | 409 Conflict |
| `ERR_SESSION_NOT_VOIDABLE` | 409 Conflict |
| `ERR_VERIFICATION_METHOD_NOT_ENABLED` | 409 Conflict |
| `ERR_VERIFICATION_NOT_PENDING` | 409 Conflict |
| `ERR_VERIFICATION_NOT_MISMATCHED` | 409 Conflict |
| `ERR_LP_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_SO_DUTY_VIOLATION` | 403 Forbidden |
| `ERR_SLOT_WINDOW_INVALID` | 400 Bad Request |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CURBSIDE_NOT_STAGED` | 409 Conflict |
| `ERR_CURBSIDE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_OFFER_WINDOW_INVALID` | 400 Bad Request |
| `ERR_OFFER_WINDOW_CONFLICT` | 409 Conflict |
