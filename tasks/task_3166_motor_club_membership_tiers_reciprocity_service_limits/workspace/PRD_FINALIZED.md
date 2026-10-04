# Motor Club Reciprocity API — Product Requirements Document

## 1. Introduction

Regional motor clubs have always operated under a federation bargain: a member stranded far from home receives the same roadside rescue a local would, and the clubs settle the cost between themselves afterward. This document specifies the API that operationalizes that bargain — a Motor Club Membership, Reciprocity and Service Limits platform covering enrollment, household coverage, roadside dispatch, inter-club settlement, and the ancillary agencies (travel, insurance, identity protection) that clubs sell alongside membership.

The system is quota-driven at its core. Each membership tier carries an annual call cap, an included tow-mileage allowance, and a lockout reimbursement ceiling, and every completed service call draws against those allowances under precise, auditable rules. Because members may be served by a club other than their own, the platform must also reconcile money between clubs: foreign benefit-eligible calls generate settlement lines that are swept into period closes, assessed a federation fee, and disputed through reversal — all under segregation-of-duties controls that keep the clerk who closes a period from being the officer who assesses it.

Two cross-cutting mechanisms deserve mention up front. First, all time in the system is logical: a test-driving clock endpoint sets "now", and advancing it fires the sweeps that move memberships into grace and lapse and expire stale service calls. Second, anti-adverse-selection is a first-class concern — a member who upgrades mid-term waits a tier-defined number of days before the richer benefits apply to pre-existing needs, and the platform pins benefit tiers at call-creation time so the waiting period cannot be gamed.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly seven roles, spelled as follows: `ClubAdmin`, `MemberServicesRep`, `Dispatcher`, `ProviderOps`, `SettlementClerk`, `FederationFinance`, and `Agent`.

- A `ClubAdmin` is the federation and club configuration operator: clubs, tiers, providers, products, and the logical clock.
- A `MemberServicesRep` owns the membership lifecycle: enrollment, upgrade and downgrade, renewal, lapse, reinstatement, cancellation, and household management.
- A `Dispatcher` performs service-call intake and dispatch.
- A `ProviderOps` operator drives a dispatch through accept, arrive, complete, and fail on behalf of the assigned provider.
- A `SettlementClerk` opens and closes inter-club settlement periods; by design, a clerk may never assess a period they closed.
- A `FederationFinance` officer assesses closed periods and reverses pending settlement lines.
- An `Agent` sells ancillary products and may refund only sales they personally made.

All seven roles share one identity convention: `X-User-ID` is an opaque operator identifier not tied to the `id` of any persisted entity. The server may record it — for example, as `sold_by_agent_id` on an `AncillarySale` or as `closed_by` on a `SettlementPeriod` — and segregation-of-duties checks compare those recorded identifiers against the caller's `X-User-ID`, but no ownership check ever compares `X-User-ID` against an entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; resources that share the same `created_at` — common under the logical clock, which stamps every event of a single logical instant identically — are ordered by creation (insertion) order, earliest first. The server-minted `id` never participates in list ordering.

The `meta` object of a list response carries exactly the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and System Sweeps

The platform runs on a logical clock, never on wall-clock time. At server startup the clock reads exactly `2026-09-01T00:00:00Z`; before any clock-setting call, every timestamp the system produces or compares is derived from that default, and the clock never silently falls back to the host's wall clock.

An administrative capability advances the clock: a `ClubAdmin` or `MemberServicesRep` supplies a `to_iso8601` instant, and the endpoint responds with the new `current_utc`. Advancing the clock is not a passive act — it fires two system sweeps in the same request:

1. **Membership sweep.** Any `ACTIVE` membership whose `term_end_date` now lies in the past transitions to `GRACE` (a thirty-day grace window opens). Any membership already in `GRACE` whose grace deadline — `term_end_date` plus thirty days — now lies in the past transitions to `LAPSED`, with `lapse_at` stamped at the new logical now.
2. **Service-call sweep.** Any `ServiceCall` still sitting in `REQUESTED` more than twenty-four hours after its `created_at` transitions to `EXPIRED`. An expired call consumed no benefit and generates no settlement line.

### 2.5. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): an optimistic-concurrency guard that increments by one on every mutation of the resource.

The audit entity `MembershipEvent` is the exception: it is immutable after creation and therefore carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

Every timestamp the server generates — `created_at`, `updated_at`, `enrolled_at`, `term_start_date`, `term_end_date`, `lapse_at`, `tier_upgrade_effective_at`, `assigned_at`, `promised_arrive_by`, `arrived_at`, `completed_at`, `closed_at`, a `MembershipEvent`'s `effective_at`, the clock endpoint's `current_utc`, and the envelope's `api_request_timestamp` — is serialized as an ISO 8601 UTC timestamp with exactly three fractional digits (for example `2026-09-01T00:00:00.000Z`). Fields that echo a client-supplied value, such as `date_of_birth` or a settlement period's `period_start_date`/`period_end_date`, are returned as supplied.

### 2.6. Monetary Precision, Mileage and Rounding

All monetary amounts are integers of cents; no decimal money exists anywhere in the API. Wherever a calculation produces a fractional cent — prorations, commissions, federation assessment fees — the value is rounded half-up to the nearest whole cent. The federation's per-line assessment explicitly pins a nested rounding order: each line's fee is rounded half-up first, and only then are the rounded per-line fees and nets summed; summing gross amounts first and rounding once at the end is forbidden.

Tow mileage is always expressed in whole miles. Promised arrival windows are computed in whole minutes with round-half-up applied to the product of club default and provider multiplier. Day arithmetic for terms, waiting periods, and windows uses exact day counts against the logical clock.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control; no other endpoint takes a version field.

- **Membership upgrade** requires the request to carry `expected_membership_version`, the `version` of the membership as the client last observed it. If another writer has advanced the membership's `version` since that read — for example a prior upgrade, a renewal, or any tier-affecting mutation — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the writer from basing proration and waiting-period arithmetic on a membership it has not observed.
- **Membership downgrade** is guarded identically: `expected_membership_version` must match the membership's current `version`, or the request fails with `ERR_STALE_VERSION` (HTTP 412), because the proration credit basis — term dates and current tier — may have shifted under the writer.
- **Service-call dispatch** requires `expected_service_call_version` matching the call's current `version`. A prior dispatch attempt or any benefit-affecting mutation may already have consumed the call's dispatchable state, so a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not accept or consult any version field.

### 2.8. Validation Order and Nested Resource Resolution

Every request passes through a fixed validation pipeline, evaluated in this order:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the seven declared roles (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the role is permitted for the endpoint (`ERR_UNAUTHORIZED`).
3. **Existence** — path identifiers resolve to existing entities, validated strictly left-to-right along the URL. A nested request fails on the first path identifier that does not resolve, with `ERR_NOT_FOUND`.
4. **Payload shape** — required fields are present, enum members are valid, and numeric ranges are respected (a provider's `sla_multiplier` between 0.5 and 3.0 inclusive, shift minutes between 0 and 1439 inclusive, miles at least 0, dues at least 0, and so on), else `ERR_INVALID_REQUEST`.
5. **Referential integrity** — foreign-key targets exist and are consistent: a household member belongs to the membership in the payload, a provider's servicing club actually owns the provider, a product id exists. Violations surface as `ERR_NOT_FOUND`.
6. **State preconditions** — the target resource is in a state that permits the operation: dispatch only from `REQUESTED`, completion only from `ARRIVED`, close only from `OPEN`, assess only from `CLOSED`, reinstate only from `LAPSED`, renew only from `GRACE` or `REINSTATED`. Violations return `ERR_INVALID_STATE`.
7. **Domain business rules** — waiting-period protection, segregation of duties, serviceability, coverage, territory resolution, temporal windows, open-call blocks, cancel boundaries, tier-move validity, household capacity, truck-stock sufficiency, product gating, and line-reversal state, each carrying its own error id as described in §3.
8. **Optimistic concurrency** — the guarded writes of §2.7 check their expected version last, returning `ERR_STALE_VERSION`.

Because path validation is left-to-right, a request for a settlement line under a nonexistent settlement period reports the missing period, never the line.

### 2.9. Federation Territory Governance

Every dispatch location resolves to exactly one servicing club. Each `Club` declares a `territory_state_codes` list — the two-letter state codes its territory covers — and a breakdown's state is mapped through those lists to the unique `ACTIVE` club that will service the call. A state covered by no club, or covered only by a `SUSPENDED` club, yields `ERR_TERRITORY_NOT_FOUND`.

A club's `status` gates real business. A `SUSPENDED` club cannot own new memberships (enrollment naming it as home club is rejected with `ERR_CLUB_SUSPENDED`), its providers are ineligible for dispatch candidate pools, and a suspended provider can only be reactivated while its servicing club is `ACTIVE` (otherwise `ERR_CLUB_SUSPENDED`). Clubs return to service by the same configuration path that suspended them.

## 3. Business Logic & Workflows

### 3.1. Clubs, Tiers and the Shape of Benefits

A `ClubAdmin` registers a federation `Club` with a unique `club_code`, a display `name`, its `territory_state_codes`, a `default_arrival_target_minutes` (at least 1), and an optional `billing_policy` of `SCHEDULE` or `ACTUAL` that defaults to `SCHEDULE`. The billing policy selects which inter-club line-amount variant the club bills when it services foreign members (§3.8). Clubs begin life `ACTIVE`; setting a club `SUSPENDED` triggers the governance of §2.9.

Benefit economics live on `MembershipTier` rows, each with a unique `code` of `CLASSIC`, `PLUS`, or `PREMIER` and a unique `rank` (1, 2, and 3 respectively by convention — a higher rank is an upgrade). A tier fixes the `annual_dues_cents` for the primary member, the per-call `included_tow_miles` covered before overage billing, the `annual_call_cap` on benefit-eligible service calls per membership term, the `lockout_benefit_cents` reimbursement ceiling for `LOCKOUT` calls, whether `battery_service_included` is true (so `BATTERY` calls consume no per-call battery surcharge), the `household_member_price_cents` charged annually per household member, the `overage_rate_cents_per_mile` applied to tow miles beyond the included allowance, and the `upgrade_waiting_days` an upgrade into this tier must wait before new-tier benefits apply to pre-existing needs. Updating a tier's economics applies prospectively only: the `benefit_tier_code` pinned on service calls already created is unaffected.

### 3.2. Enrollment and Household Coverage

A `MemberServicesRep` enrolls a primary member by naming the `home_club_id`, the `primary_member_name`, the `primary_member_email` (unique across all memberships), and the desired `tier_code`. Enrollment is rejected with `ERR_CLUB_SUSPENDED` when the named home club is not `ACTIVE`. On success the membership is born `ACTIVE`, `enrolled_at` and `term_start_date` are stamped at the logical now, and `term_end_date` is set exactly 365 days later — the term is a rolling 365-day benefit term, never a calendar year. The membership begins with `calls_used_current_term` at 0, `account_credit_cents` at 0, `reinstatement_count` at 0, `lapse_at` and `tier_upgrade_effective_at` null, and an `ENROLLMENT` entry is appended to its `MembershipEvent` audit trail. Every `MembershipEvent` row records the `membership_id` it concerns, an `event_type` drawn from `ENROLLMENT`, `UPGRADE`, `DOWNGRADE`, `RENEWAL`, `LAPSE`, `REINSTATEMENT`, `CANCELLATION`, and `WAITING_PERIOD_SATISFIED`, the `from_tier` and `to_tier` bracketing the change (the former null for an `ENROLLMENT`, the latter null whenever the event does not change tiers), the `effective_at` logical timestamp, and a free-text `note`. For enrollment, `from_tier` is null and `to_tier` names the enrolled tier, with `effective_at` at the logical now.

Coverage extends to the household through `HouseholdMember` rows carrying a `full_name`, a `relationship` of `SPOUSE`, `CHILD`, `PARENT`, or `OTHER`, a `date_of_birth`, and an `is_primary` flag that defaults to false when omitted. The primary member herself is added as a household row with `is_primary` set true — at most one such row per membership — so that she can request service through the same coverage path as everyone else; the annual dues debit described below is waived for that primary row, since her dues already cover her. Every other household addition debits the membership's `account_credit_cents` by the tier's `household_member_price_cents` as a full-year charge at add time. Two limits guard the household: no more than four `ACTIVE` household members per membership, and a `CHILD` relationship requires the member to be younger than 21 at add time — violations are rejected with `ERR_HOUSEHOLD_LIMIT`. Profile fields (`full_name`, `relationship`, `date_of_birth`) can be corrected later by a member services update.

Removing a household member mid-term is allowed only while that member has no non-terminal service call (one in `REQUESTED`, `DISPATCHED`, `EN_ROUTE`, or `ON_SCENE`) as the requesting member — otherwise the removal is rejected with `ERR_OPEN_SERVICE_CALLS`. A mid-term removal posts a prorated credit to the membership's `account_credit_cents`: the tier's `household_member_price_cents` is multiplied by the number of days remaining in the term (365 minus the whole days elapsed since `term_start_date`), divided by 365, and rounded half-up to a whole cent. The row transitions from `ACTIVE` to `REMOVED`.

### 3.3. The Membership Lifecycle: Renewal, Lapse, Reinstatement, Cancellation

A membership's `status` walks the states `ACTIVE`, `GRACE`, `LAPSED`, `REINSTATED`, and `CANCELLED`, with `CANCELLED` terminal.

**Grace and lapse by the clock.** When the logical clock advances past `term_end_date` on an `ACTIVE` membership whose renewal is unpaid, the membership slides into `GRACE` and a `MembershipEvent` of type `LAPSE` is appended with a `note` recording that the thirty-day grace opened. Should the clock advance past `term_end_date` plus thirty days while still in `GRACE`, the membership becomes `LAPSED`, `lapse_at` is stamped, and a second `LAPSE` event records the hard lapse. An administrative lapse is also available: a `MemberServicesRep` may lapse an `ACTIVE` membership directly for non-payment, without grace, provided the membership holds no non-terminal service call (else `ERR_OPEN_SERVICE_CALLS`); the event note distinguishes this administrative path.

**Renewal.** From `GRACE`, renewal by a `MemberServicesRep` is accepted while the logical now is no later than the grace deadline — `term_end_date` plus thirty days — and it rolls the term forward: the new `term_start_date` is the old `term_end_date`, the new `term_end_date` falls exactly 365 days after that, `calls_used_current_term` resets to 0, and a `RENEWAL` event is appended. A membership in `REINSTATED` may also renew, and here renewing early is expressly allowed — the logical now need not have passed `term_end_date` — but the new term still starts at the old `term_end_date` rather than at the moment of renewal, the call counter resets, and the status becomes `ACTIVE`. Renewal from any other state is rejected with `ERR_INVALID_STATE`.

**Reinstatement.** A `LAPSED` membership can be brought back within ninety days of `lapse_at`; past that window the attempt fails with `ERR_REINSTATEMENT_WINDOW_EXPIRED`. The request must confirm payment of full new-term dues by setting `dues_paid` true. Reinstatement starts a fresh term at the logical now (new `term_start_date`, `term_end_date` 365 days later), resets `calls_used_current_term` to 0, increments `reinstatement_count` by one, nulls `lapse_at` again, lands the membership in `REINSTATED`, and appends a `REINSTATEMENT` event.

**Cancellation.** Cancellation is available from `ACTIVE`, `GRACE`, and `REINSTATED`, and is blocked whenever the membership holds any non-terminal service call (`ERR_OPEN_SERVICE_CALLS`). The cascade is total: every `ACTIVE` household row transitions to `REMOVED` — a cascade removal, unlike the direct mid-term removal of §3.2, posts no prorated credit to `account_credit_cents` — and every `ACTIVE` `AncillarySale` on the membership transitions to `REFUNDED` with the commission reversal and full refund credit of §3.9 applied to each. A `CANCELLATION` event closes the audit trail. Every one of these lifecycle mutations — enroll excepted, which mints the resource — refreshes the membership's `updated_at` and increments its `version` by one.

### 3.4. Mid-Term Tier Changes and the Waiting Period

Upgrades and downgrades are requested by a `MemberServicesRep` naming a `target_tier_code`. The target tier must exist, must differ from the membership's current tier, and must move in the direction the action implies — an upgrade requires a strictly higher `rank`, a downgrade a strictly lower one; violations return `ERR_TIER_MOVE_INVALID`. Both actions are OCC-guarded per §2.7. An immediate re-upgrade within the same term after a downgrade is permitted, but it re-applies the new tier's waiting period in full.

**Proration.** A tier change never resets term dates — this ordering is pinned precisely to break the apparent circularity in which the charge depends on the new tier, the credit on remaining days, and remaining days on the term. The number of elapsed days is the whole days between `term_start_date` and the logical now; the remaining days are 365 minus that count. The prorated value of the new tier is its `annual_dues_cents` times the remaining days, divided by 365, rounded half-up; the prorated value of the old tier is computed the same way from its own dues, with each factor rounded individually before any subtraction. An upgrade charges the difference — new-tier proration minus old-tier proration, never negative given the rank ordering — as a debit to `account_credit_cents`; a downgrade credits the mirror-image difference. An `UPGRADE` or `DOWNGRADE` event (with `from_tier` and `to_tier` populated) is appended, and the membership's `version` increments.

**The waiting period.** An upgrade stamps `tier_upgrade_effective_at` as the logical now plus the new tier's `upgrade_waiting_days` days. While the logical now remains earlier than that timestamp, the membership is said to be inside an upgrade waiting period, and any new service call created during it is flagged with `is_pre_existing_need` true at creation. A pre-existing need is served at the pre-upgrade tier's benefits: the call's `benefit_tier_code` pins the old tier, and the old tier's cap and included mileage govern it. Once the clock passes `tier_upgrade_effective_at`, a `WAITING_PERIOD_SATISFIED` event is appended and subsequent calls resolve benefits at the current tier. Any request that attempts to force a post-upgrade `benefit_tier_code` onto a pre-existing need is rejected with `ERR_WAITING_PERIOD_ACTIVE`. Downgrades carry no waiting period — but a later re-upgrade restarts one.

### 3.5. Roadside Service Intake and Benefit Resolution

A `Dispatcher` or `MemberServicesRep` opens a `ServiceCall` by supplying the `membership_id`, the `requesting_member_id` of the covered person asking for help, a `service_type` of `TOW`, `BATTERY`, `LOCKOUT`, `TIRE`, `FUEL`, or `WINCH`, the `breakdown_location_state` where the vehicle sits disabled, and — for `TOW` calls — the `requested_tow_miles`, which is required for `TOW` and ignored for every other type.

Creation resolves three things before the call is born `REQUESTED`. First, the servicing club: `breakdown_location_state` must fall in exactly one `ACTIVE` club's `territory_state_codes`, else `ERR_TERRITORY_NOT_FOUND`, and the resolved club is stored on the call as `servicing_club_id`. Second, serviceability and coverage: the membership's `status` must be `ACTIVE`, `REINSTATED`, or `GRACE` — calls on `LAPSED` or `CANCELLED` memberships are rejected with `ERR_MEMBERSHIP_NOT_SERVICEABLE` — and the requesting member must be an `ACTIVE` household row belonging to that membership, else `ERR_MEMBER_NOT_COVERED`. Third, the benefit basis: the waiting-period rule of §3.4 sets `is_pre_existing_need`, and `benefit_tier_code` is pinned — the membership's current tier, or the pre-upgrade tier when the need is pre-existing. This pin is permanent for the life of the call; later tier edits and later tier moves never rewrite it.

When several of these guards could fire on the same request, the evaluation order is pinned so the reported error is deterministic: the waiting-period guard runs first — an attempt to directly dictate a post-upgrade `benefit_tier_code` on a pre-existing need surfaces as `ERR_WAITING_PERIOD_ACTIVE` rather than being masked by any later check — then membership serviceability (`ERR_MEMBERSHIP_NOT_SERVICEABLE`), then household coverage (`ERR_MEMBER_NOT_COVERED`), and territory resolution (`ERR_TERRITORY_NOT_FOUND`) last.

**The benefit cap.** Each tier's `annual_call_cap` bounds benefit-eligible calls per membership per rolling term, and the counter `calls_used_current_term` is shared across the primary and every household member — it is a household-level cap. The boundary is strict: a call is benefit-eligible when `calls_used_current_term` is strictly less than the cap, so the cap-th call (when the counter sits at cap minus one) is still eligible and the next one is not. A call whose cap is already exhausted is still dispatched — but as member-pay, with `benefit_eligible` false. Calls created while the membership is in `GRACE` are always member-pay: `benefit_eligible` is forced false regardless of the counter. And when the need is pre-existing, the cap consulted is the pre-upgrade tier's cap, not the new tier's. A fresh call carries `cancel_reason` `NONE`; the other values it can take are `MEMBER_REQUEST` (a member-initiated cancel), `NO_PROVIDER` (the empty-pool auto-cancel of §3.6), and `DUPLICATE`.

### 3.6. Dispatch: Provider Selection, the SLA Clock, and the Roadside Workflow

**Provider registration and standing.** A `ClubAdmin` registers each `ServiceProvider` under a servicing club, declaring its display `name`, its `provider_kind` — `OWNED` fleets belong to the club, `CONTRACTED` providers are third-party — the `capabilities` list of service types it can perform, its `home_base_state_code`, its `sla_multiplier` stretch factor, the `shift_start_minute` and `shift_end_minute` bounding its daily availability window, and its `max_concurrent_dispatches` aggregate capacity. Providers are born `ACTIVE`. A club administrator may suspend a provider only while it holds no non-terminal dispatch — attempting suspension with work still in flight is rejected with `ERR_PROVIDER_BUSY` — and a suspended provider is excluded from all future dispatch candidate pools. Reactivation is permitted only while the provider's servicing club is `ACTIVE`, else `ERR_CLUB_SUSPENDED` per §2.9.

**Candidate selection.** Dispatching a `REQUESTED` call is the `Dispatcher`'s exclusive act, guarded by `expected_service_call_version` per §2.7. The server runs provider selection over every `ServiceProvider` row, admitting a candidate only when all of the following hold: the provider is `ACTIVE`; its `servicing_club_id` equals the call's `servicing_club_id`; the call's `service_type` appears in the provider's `capabilities`; the provider's `home_base_state_code` lies inside the servicing club's territory list; the provider's availability window is open — the minute-of-day of the logical now falls within the half-open interval from `shift_start_minute` to `shift_end_minute`, and when the two are equal the provider works around the clock and is always eligible; the provider's current load — its count of non-terminal dispatches, those in `ASSIGNED`, `ACCEPTED`, `EN_ROUTE`, or `ARRIVED` — is strictly below its `max_concurrent_dispatches`; and, on a redispatch immediately following a failed attempt, the provider whose dispatch just failed is excluded from this retry's pool only.

Among the survivors, ranking is total and deterministic: club-`OWNED` fleets are preferred over `CONTRACTED` third parties; then the provider with the smaller current non-terminal dispatch count wins; then the earlier `created_at` breaks remaining ties. The provider `id` never participates in ranking.

**Empty pool.** When no candidate survives, no `Dispatch` row is created at all; the call transitions straight from `REQUESTED` to `CANCELLED` with `cancel_reason` set to `NO_PROVIDER`, and — as compensation — benefit eligibility is not consumed.

**Assignment.** A successful selection creates a `Dispatch` in `ASSIGNED` whose `sequence_number` is one plus the count of prior dispatches for the call, whose `assigned_at` is the logical now, and whose `dispatched_tow_miles` copies the call's `requested_tow_miles` for a `TOW` call. The promised arrival instant `promised_arrive_by` is `assigned_at` plus the effective arrival target: the servicing club's `default_arrival_target_minutes` multiplied by the chosen provider's `sla_multiplier`, rounded half-up to whole minutes. The dispatch also records a `provisional_mileage_charge_cents` — a forward-looking overage estimate computed on the requested-miles basis per the provisional variant of §3.7 — which is preview only and is never posted to the member's account. Dispatching transitions the call from `REQUESTED` to `DISPATCHED` and increments the call's `version` by one.

**On the road.** A `ProviderOps` operator then walks the dispatch forward, and the parent call's `status` mirrors the roadside reality: acceptance moves the dispatch from `ASSIGNED` to `ACCEPTED`; the same accept action with `en_route` set true moves an `ACCEPTED` dispatch to `EN_ROUTE` (the provider is rolling) and advances the call from `DISPATCHED` to `EN_ROUTE` with it. Arrival moves the dispatch from `EN_ROUTE` to `ARRIVED` — the call moving from `EN_ROUTE` to `ON_SCENE` alongside — stamps `arrived_at` at the logical now, and computes `sla_met` as true exactly when `arrived_at` is no later than `promised_arrive_by` — the boundary is inclusive, so arriving at the promised instant counts as meeting the SLA.

**Failure and the redispatch loop.** Failing a dispatch from `ASSIGNED`, `ACCEPTED`, or `EN_ROUTE` records a `failure_reason` of `PROVIDER_DECLINED`, `NO_PARTS`, or `MEMBER_NO_SHOW` (the default is `NONE`), moves the dispatch to terminal `FAILED`, and loops the parent call from `DISPATCHED` back to `REQUESTED`. The next dispatch attempt receives the next `sequence_number` and re-runs selection with the failed provider excluded from that retry's candidate pool.

**Member cancellation.** A member-requested cancel is always available while the call is still `REQUESTED`. Once `DISPATCHED`, cancellation is permitted only while the linked non-terminal dispatch is `ASSIGNED` or `ACCEPTED` — past that, with the provider rolling or on scene, the member owes a service attempt and the cancel is rejected with `ERR_DISPATCH_BEYOND_CANCEL`. A successful cancel sets the call's `cancel_reason` to `MEMBER_REQUEST` and cascades the linked dispatch to `CANCELLED`, freeing one slot of the provider's concurrency capacity. And per §2.4, a call abandoned in `REQUESTED` for more than twenty-four hours expires on the next clock advance, consuming no benefit and creating no settlement line.

### 3.7. Completion: Charges, Parts, and the Birth of a Settlement Line

Completion is the richest moment in the roadside lifecycle: a single `ProviderOps` act mutates dispatch, call, truck stock, membership account, and potentially the inter-club ledger atomically. The dispatch must be `ARRIVED`. The operator reports the `actual_tow_miles` — required to be at least 1 for a `TOW` call, else `ERR_INVALID_REQUEST` — and optionally the `parts_used`, an array of `part_sku` and quantity pairs consumed from the truck under the battery and mobile service programs.

**Truck stock.** Every `part_sku` named must exist in the completing provider's `TruckPartStock` — the stock line whose `provider_id` is the completing provider — with `quantity_on_hand` at least the requested quantity, or the completion is rejected with `ERR_INSUFFICIENT_TRUCK_STOCK` and the dispatch stays `ARRIVED` — the provider must retry with corrected parts or fail the dispatch. On success the stock decrements per `parts_used` (an empty list decrements nothing, silently). Stock lines are per-provider: `part_sku` is unique within a provider, and each line declares a `part_kind` of `BATTERY`, `TIRE`, `FUEL_CAN`, or `LOCKSMITH_KIT`, alongside a `reorder_level` for restock reporting. Club administrators and provider operators create or restock lines, and a restock adds its `add_quantity` to `quantity_on_hand`.

**Parts charge.** `parts_charge_cents` is the sum over `parts_used` of each part's price-book price times its quantity. The federation parts price book fixes `BAT-G24` at 14500 cents, `BAT-G35` at 16900 cents, `TIRE-SPO` at 9900 cents, `FUEL-CAN` at 1200 cents, and `LOCK-KIT` at 0 cents.

**Mileage charge.** The final variant of the tow-overage calculation runs on the dispatch's `actual_tow_miles` against the call's pinned `benefit_tier_code` — never the membership's current tier. Every tier extends a courtesy bonus of 3 miles, subtracted first: the effective miles are the actual miles minus 3, floored at zero. For a benefit-eligible call, the overage miles are the effective miles beyond the tier's `included_tow_miles`, floored at zero, and the `mileage_charge_cents` is the overage miles times the tier's `overage_rate_cents_per_mile` — zero when the benefit covers every mile or the call is not a tow. For a member-pay call (`benefit_eligible` false), there is no included-mile deduction at all: the member is billed the full effective miles times the overage rate. All factors are integers, so no rounding arises. The provisional variant computed at dispatch differs only in its input — requested rather than actual miles — and in its disposition: preview, never posted.

**Total member charge.** When the call is benefit-eligible, `total_member_charge_cents` is the mileage charge plus the parts charge. `LOCKOUT` calls carry a special case: the member pays the locksmith invoice minus the tier's `lockout_benefit_cents`, floored at zero — and since the price book models the locksmith invoice as zero when no `LOCK-KIT` part is used, the benefit-path charge for a lockout is the parts charge alone. When the call is member-pay — which includes every call made during `GRACE` — the total is the full price-book amount: member-pay mileage (no included-mile deduction) plus the parts charge. The total posts as a debit: the membership's `account_credit_cents` decreases by `total_member_charge_cents`, where a negative balance signals an amount owed to the club.

**Cap consumption and completion bookkeeping.** Completing a benefit-eligible call increments the membership's `calls_used_current_term` by one — cap consumption happens at completion, never at dispatch, so a failed or cancelled attempt costs the member nothing against the cap. The dispatch lands in `COMPLETED` with `completed_at` stamped, and the parent call moves from `ON_SCENE` to `COMPLETED` in the same atomic step.

**Inter-club billing trigger.** When the membership's `home_club_id` differs from the call's `servicing_club_id` — a foreign call — completion also writes a `SettlementLine`, whose `status` begins at `PENDING` unless excluded. If the call was benefit-eligible, the line is born with `excluded` false and a `gross_amount_cents` computed per §3.8. If the call was member-pay, the line is instead born with `excluded` true and `exclusion_reason` `MEMBER_PAY`, because member-pay calls are never reimbursed through the federation. Lines for calls cancelled or expired before completion carry `exclusion_reason` `CALL_NOT_COMPLETED`; in every excluded case the fee fields `assessed_fee_cents` and `assessed_net_cents` remain at their initial zero, and excluded lines are never swept. Each line records both clubs: `home_club_id` as the debtor and `servicing_club_id` as the creditor, plus the `service_call_id` it reimburses; its `settlement_period_id` stays null until a period close sweeps it.

### 3.8. Inter-Club Settlement: Periods, Sweeps, Assessment, and Disputes

**The gross amount.** The amount a home club owes a servicing club for a foreign benefit-eligible call depends on the servicing club's `billing_policy`. Under the default `SCHEDULE` basis, the gross is a flat federation schedule indexed by the call's pinned `benefit_tier_code` and `service_type`, independent of actual miles and parts:

| benefit_tier_code | TOW | BATTERY | LOCKOUT | TIRE | FUEL | WINCH |
| --- | --- | --- | --- | --- | --- | --- |
| `CLASSIC` | 8900 | 6200 | 5500 | 4800 | 4100 | 12400 |
| `PLUS` | 12900 | 6800 | 5500 | 4800 | 4100 | 13900 |
| `PREMIER` | 21500 | 7400 | 5500 | 4800 | 4100 | 16800 |

Under the `ACTUAL` basis, the gross mirrors the provider's cost: a hook fee of 5500 cents, plus 240 cents per actual effective tow mile (the `actual_tow_miles` minus the 3-mile courtesy bonus, floored at zero — zero for non-tow calls), plus the completion's `parts_charge_cents`. Identical call data therefore bills differently under the two variants; the variant is chosen by the servicing club, never by the home club.

**Period lifecycle.** A `SettlementClerk` opens a `SettlementPeriod` for a servicing club, naming the `period_start_date` (inclusive, at 00:00:00Z) and the `period_end_date` (exclusive); the period is born `OPEN`. Closing is allowed only once the logical now has reached `period_end_date` — an early close is rejected with `ERR_PERIOD_NOT_CLOSABLE`. The close performs the sweep with a pinned evaluation order: first filter settlement lines by the period's `servicing_club_id`; then keep only lines with `excluded` false; then keep only `PENDING` lines; then keep only lines whose service call's `completed_at` falls within the half-open window from `period_start_date` up to but not including `period_end_date`; then sort the survivors by `completed_at` ascending, breaking ties by the service call's `created_at` ascending; then assign them to the period in exactly that order, stamping each line's `settlement_period_id` and moving it from `PENDING` to `SWEPT`. The period records `total_foreign_call_count` as the swept count and `total_gross_cents` as the sum of swept `gross_amount_cents`, stamps `closed_at`, and records the closing clerk's `X-User-ID` in `closed_by` — the value the segregation-of-duties check will consult at assess time.

**Assessment.** A `FederationFinance` officer assesses a `CLOSED` period; assessing an `OPEN` period is rejected with `ERR_INVALID_STATE`. Segregation of duties is hard: the assessing officer's `X-User-ID` must differ from the `closed_by` recorded at close, else `ERR_SOD_CONFLICT`. Assessment walks the swept lines in sweep order and, for each, computes `assessed_fee_cents` as the line's `gross_amount_cents` times the federation assessment rate of 4.5 percent, rounded half-up per line first, and `assessed_net_cents` as the gross minus that fee; the period totals are the sums of the already-rounded per-line fees and nets. Each swept line moves from `SWEPT` to terminal `ASSESSED`, and the period itself becomes `ASSESSED`, terminal.

**Disputes.** A home club disputing a line before it is swept asks a `FederationFinance` officer to reverse it. Reversal is legal only while the line is `PENDING`; a `SWEPT` or `ASSESSED` line cannot be reversed and the attempt returns `ERR_LINE_ALREADY_SWEPT`. A reversed line lands in terminal `REVERSED` and is permanently excluded from all future sweeps.

### 3.9. Ancillary Agencies: Products, Sales, Commissions, and Refunds

Clubs also operate three ancillary agencies, modeled as `AncillaryProduct` rows with a `product_type` of `TRAVEL_AGENCY`, `INSURANCE_AGENCY`, or `IDENTITY_PROTECTION`. Each product has a `name` unique within its `product_type`, an annual `price_cents`, a `min_tier_code` naming the minimum membership tier rank required to buy it, and an agent `commission_bps` in basis points of the price, between 0 and 5000 inclusive. A `ClubAdmin` maintains the catalog; retiring a product sets its `status` to `RETIRED`, and existing sales keep their price snapshot regardless of later product edits.

An `Agent` sells a product by naming the `membership_id` and `product_id`; the seller's own `X-User-ID` is recorded as `sold_by_agent_id` for audit. Purchase gating is threefold and any failure returns `ERR_PRODUCT_TIER_GATE`: the membership must be `ACTIVE` or `REINSTATED`, the membership's tier `rank` must be at least the product's `min_tier_code` rank, and the product must be `ACTIVE`. The sale snapshots the product's `price_cents` at sale time, computes the agent's `commission_cents` as the price times `commission_bps` divided by ten thousand and rounded half-up, debits the membership's `account_credit_cents` by the full price, and increments the membership's `version`.

Refunds are narrow by design, and the two guards on them are evaluated in a fixed order: segregation of duties first, then the refund window. An `Agent` may refund only a sale they personally made: the refunding agent's `X-User-ID` must equal the sale's `sold_by_agent_id`, unless the caller is a `MemberServicesRep`; an agent reaching for another agent's sale is stopped with `ERR_SOD_CONFLICT` before any temporal question is considered. Only then does the window apply: a sale may be refunded only within thirty days of its creation, with the window inclusive at exactly thirty days — later attempts return `ERR_REFUND_WINDOW_EXPIRED`. A successful refund moves the sale from `ACTIVE` to terminal `REFUNDED`, credits the membership's `account_credit_cents` by the full `price_cents`, posts a reversal of the `commission_cents` to the agent ledger for reporting, and increments the membership's `version`. The compensating invariant is exact: a sale followed by its refund leaves `account_credit_cents` unchanged, and the membership's `version` returns to its pre-sale value plus two — one bump per event.

## 4. Endpoint Definitions

Operations that create a new resource by posting to a collection — clubs, tiers, memberships, household members, providers, part-stock lines, service calls, settlement periods, ancillary products, ancillary sales — return `201 Created`. All other operations, including action-style posts that drive a state transition or workflow (upgrade, renew, dispatch, accept, close, refund, and the like), updates, and removals, return `200 OK` — this holds even for the dispatch action, which mints a dispatch record yet answers `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/motor-club/_clock/set_current_utc` | Advance the logical clock; fires grace/lapse and call-expiry sweeps | ClubAdmin, MemberServicesRep |
| POST | `/motor-club/clubs` | Create a federation club | ClubAdmin |
| GET | `/motor-club/clubs` | List clubs | ClubAdmin, Dispatcher, MemberServicesRep, SettlementClerk, FederationFinance |
| GET | `/motor-club/clubs/{clubId}` | Get one club | ClubAdmin, Dispatcher, MemberServicesRep, SettlementClerk, FederationFinance |
| PUT | `/motor-club/clubs/{clubId}` | Update club configuration or status | ClubAdmin |
| POST | `/motor-club/tiers` | Create a membership tier | ClubAdmin |
| GET | `/motor-club/tiers` | List tiers | ClubAdmin, MemberServicesRep, Dispatcher, Agent |
| GET | `/motor-club/tiers/{tierId}` | Get one tier | ClubAdmin, MemberServicesRep, Dispatcher, Agent |
| PUT | `/motor-club/tiers/{tierId}` | Update tier economics (prospective only) | ClubAdmin |
| POST | `/motor-club/memberships` | Enroll a primary member | MemberServicesRep |
| GET | `/motor-club/memberships` | List memberships (filterable by status, home club) | MemberServicesRep, Dispatcher, SettlementClerk, FederationFinance |
| GET | `/motor-club/memberships/{membershipId}` | Get one membership | MemberServicesRep, Dispatcher, SettlementClerk, FederationFinance |
| POST | `/motor-club/memberships/{membershipId}/upgrade` | Upgrade tier mid-term (OCC-guarded, prorated charge) | MemberServicesRep |
| POST | `/motor-club/memberships/{membershipId}/downgrade` | Downgrade tier mid-term (OCC-guarded, prorated credit) | MemberServicesRep |
| POST | `/motor-club/memberships/{membershipId}/renew` | Renew from GRACE or REINSTATED; rolls term forward | MemberServicesRep |
| POST | `/motor-club/memberships/{membershipId}/lapse` | Administrative lapse for non-payment | MemberServicesRep |
| POST | `/motor-club/memberships/{membershipId}/reinstate` | Reinstate a LAPSED membership within 90 days | MemberServicesRep |
| POST | `/motor-club/memberships/{membershipId}/cancel` | Cancel membership; cascades household and ancillary refunds | MemberServicesRep |
| GET | `/motor-club/memberships/{id}/membershipEvents` | Audit events of a membership | MemberServicesRep, FederationFinance |
| GET | `/motor-club/memberships/{id}/householdMembers` | Household members of a membership | MemberServicesRep, Dispatcher |
| GET | `/motor-club/memberships/{membershipId}/service-calls` | Service calls of a membership | MemberServicesRep, Dispatcher, SettlementClerk |
| GET | `/motor-club/memberships/{membershipId}/ancillary-sales` | Ancillary sales of a membership | MemberServicesRep, Agent |
| GET | `/motor-club/membership-events` | List membership audit events (filterable) | MemberServicesRep, FederationFinance |
| GET | `/motor-club/truck-part-stock` | List truck part stock lines (filterable) | ClubAdmin, ProviderOps |
| GET | `/motor-club/dispatches` | List dispatches (filterable) | Dispatcher, ProviderOps, SettlementClerk |
| GET | `/motor-club/ancillary-sales` | List ancillary sales (filterable) | Agent, MemberServicesRep |
| POST | `/motor-club/memberships/{membershipId}/household-members` | Add a household member | MemberServicesRep |
| GET | `/motor-club/household-members/{memberId}` | Get one household member | MemberServicesRep, Dispatcher |
| PUT | `/motor-club/household-members/{memberId}` | Update household member profile fields | MemberServicesRep |
| DELETE | `/motor-club/household-members/{memberId}` | Remove a household member mid-term (prorated credit) | MemberServicesRep |
| POST | `/motor-club/providers` | Register a service provider under a servicing club | ClubAdmin |
| GET | `/motor-club/providers` | List providers (filterable) | ClubAdmin, Dispatcher, ProviderOps |
| GET | `/motor-club/providers/{providerId}` | Get one provider | ClubAdmin, Dispatcher, ProviderOps |
| PUT | `/motor-club/providers/{providerId}` | Update provider configuration or status | ClubAdmin |
| GET | `/motor-club/providers/{id}/truckPartStocks` | Truck part stock of a provider | ClubAdmin, ProviderOps |
| POST | `/motor-club/providers/{providerId}/part-stock` | Create or restock a truck part line | ClubAdmin, ProviderOps |
| POST | `/motor-club/part-stock/{stockId}/restock` | Add quantity to an existing truck stock line | ClubAdmin, ProviderOps |
| POST | `/motor-club/service-calls` | Open a service call; resolves territory and benefit basis | Dispatcher, MemberServicesRep |
| GET | `/motor-club/service-calls` | List service calls (filterable) | Dispatcher, MemberServicesRep, SettlementClerk, ProviderOps |
| GET | `/motor-club/service-calls/{callId}` | Get one service call | Dispatcher, MemberServicesRep, SettlementClerk, ProviderOps |
| POST | `/motor-club/service-calls/{callId}/dispatch` | Dispatch the call (OCC-guarded; empty pool auto-cancels) | Dispatcher |
| POST | `/motor-club/service-calls/{callId}/cancel` | Cancel the call (member request) | Dispatcher, MemberServicesRep |
| GET | `/motor-club/service-calls/{callId}/dispatches` | Dispatches of a call | Dispatcher, ProviderOps, SettlementClerk |
| GET | `/motor-club/dispatches/{dispatchId}` | Get one dispatch | Dispatcher, ProviderOps, SettlementClerk |
| POST | `/motor-club/dispatches/{dispatchId}/accept` | Provider accepts, or marks rolling with `en_route` true | ProviderOps |
| POST | `/motor-club/dispatches/{dispatchId}/arrive` | Provider arrives on scene; SLA computed | ProviderOps |
| POST | `/motor-club/dispatches/{dispatchId}/complete` | Complete with actual miles and parts; posts charges | ProviderOps |
| POST | `/motor-club/dispatches/{dispatchId}/fail` | Fail the dispatch; call loops back for redispatch | ProviderOps |
| POST | `/motor-club/settlement-periods` | Open a settlement period for a servicing club | SettlementClerk |
| GET | `/motor-club/settlement-periods` | List settlement periods | SettlementClerk, FederationFinance |
| GET | `/motor-club/settlement-periods/{periodId}` | Get one settlement period | SettlementClerk, FederationFinance |
| POST | `/motor-club/settlement-periods/{periodId}/close` | Close the period; sweeps eligible PENDING lines | SettlementClerk |
| POST | `/motor-club/settlement-periods/{periodId}/assess` | Assess federation fee on swept lines (SoD enforced) | FederationFinance |
| GET | `/motor-club/settlement-periods/{id}/settlementLines` | Settlement lines swept into a period | SettlementClerk, FederationFinance |
| GET | `/motor-club/settlement-lines` | List settlement lines (filterable) | SettlementClerk, FederationFinance |
| GET | `/motor-club/settlement-lines/{lineId}` | Get one settlement line | SettlementClerk, FederationFinance |
| POST | `/motor-club/settlement-lines/{lineId}/reverse` | Reverse a PENDING line (home-club dispute) | FederationFinance |
| POST | `/motor-club/ancillary-products` | Create an ancillary product | ClubAdmin |
| GET | `/motor-club/ancillary-products` | List ancillary products | ClubAdmin, Agent, MemberServicesRep |
| GET | `/motor-club/ancillary-products/{productId}` | Get one ancillary product | ClubAdmin, Agent, MemberServicesRep |
| PUT | `/motor-club/ancillary-products/{productId}` | Update product (existing sales keep price snapshot) | ClubAdmin |
| POST | `/motor-club/ancillary-sales` | Sell an ancillary product to a membership | Agent |
| GET | `/motor-club/ancillary-sales/{saleId}` | Get one ancillary sale | Agent, MemberServicesRep |
| POST | `/motor-club/ancillary-sales/{saleId}/refund` | Refund a sale within 30 days | Agent, MemberServicesRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_WAITING_PERIOD_ACTIVE` | 422 |
| `ERR_SOD_CONFLICT` | 422 |
| `ERR_MEMBERSHIP_NOT_SERVICEABLE` | 422 |
| `ERR_MEMBER_NOT_COVERED` | 422 |
| `ERR_TERRITORY_NOT_FOUND` | 422 |
| `ERR_REINSTATEMENT_WINDOW_EXPIRED` | 422 |
| `ERR_REFUND_WINDOW_EXPIRED` | 422 |
| `ERR_PERIOD_NOT_CLOSABLE` | 422 |
| `ERR_OPEN_SERVICE_CALLS` | 422 |
| `ERR_DISPATCH_BEYOND_CANCEL` | 422 |
| `ERR_TIER_MOVE_INVALID` | 422 |
| `ERR_HOUSEHOLD_LIMIT` | 422 |
| `ERR_INSUFFICIENT_TRUCK_STOCK` | 422 |
| `ERR_PRODUCT_TIER_GATE` | 422 |
| `ERR_LINE_ALREADY_SWEPT` | 422 |
| `ERR_CLUB_SUSPENDED` | 422 |
| `ERR_PROVIDER_BUSY` | 422 |
