# Closed-Loop Social Care Referral Network API — Product Requirements Document

## 1. Introduction

Community health depends on a fragile handshake: a clinic identifies a patient whose real barrier to health is housing, food, or transportation, and hands that patient off to a community-based organization that may or may not have capacity, may or may not report back, and is rarely paid for the work. This document specifies the Closed-Loop Social Care Referral Network API, a coordination platform in the style of Unite Us that makes that handshake accountable end to end. The platform onboards community organizations, clinical senders, and funders into a single network; routes referrals only when consent, data-sharing agreements, eligibility, and capacity all line up; and forces every referral to a confirmed outcome — delivered, not reached, or declined by the client — so that no case silently evaporates.

Two economic facts shape the design. First, funders (health plans and public agencies) pay for delivered social services through rate cards, claims adjudication, and batched disbursements, so the API carries a full billing pipeline with segregation of duties, monthly caps, and clawbacks settled against a network-level escrow. Second, consent is revocable at any moment, and revocation must propagate: open referrals are cancelled, in-flight claims are voided, and the network's escrow absorbs the financial shock. Reporting to funders closes the loop with period metrics — including a deliberately dual reading of "closure" — under k-anonymity suppression so that no demographic cell exposes a handful of clients.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply to every endpoint and every entity in the network.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. A request missing either header, or carrying a malformed value — including an `X-User-Role` value outside the four recognized roles — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose recognized role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The platform recognizes exactly four roles, spelled as follows: `NetworkCoordinator`, `CaseWorker`, `OrgAdmin`, and `FunderAdmin`.

Role identity is resolved in two distinct ways:

- When `X-User-Role` is `NetworkCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any organization's `id`.
- When `X-User-Role` is `CaseWorker`, `OrgAdmin`, or `FunderAdmin`, `X-User-ID` is entity-backed by `Organization`: it is either the bare `id` of the acting organization (the organization acting as itself) or the compound form `<org_id>#<staff_label>` identifying an individual staff member of that organization. Org-ownership checks — for example, a receiver-only action requiring the caller's organization to equal the referral's `receiver_org_id` — compare the org-id prefix of `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN_ORG` (HTTP 403). Segregation-of-duties checks, by contrast, compare the full `X-User-ID` string, suffix included, so two staff members of the same funder must use distinct staff labels to act as different adjudicators.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and the Aging Sweep

The platform runs on a server-held logical clock, not wall-clock time. At startup the clock reads exactly `2026-09-01T00:00:00Z`; before any clock-setting call it continues to read this default and never falls back to wall-clock time. A `NetworkCoordinator` may advance the logical clock to a supplied `to_iso8601` instant; the response reports the resulting `current_utc`. Every aging, escalation, expiry, and reporting rule in this document is evaluated against this clock.

Advancing the clock triggers the referral aging sweep as a side effect: any referral still in `ROUTED` whose whole-day age since it was routed — the number of complete 24-hour days between the routed timestamp and the clock, rounded down — is strictly greater than the network's `referral_expiry_days` transitions to `EXPIRED`, releasing its capacity reservation and decrementing the client's open-referral count. The same sweep can be run on demand by a coordinator through a dedicated aging-sweep capability, which returns the `expired_count` and the list of `expired_referral_ids`. The strictness of the comparison matters: a referral exactly `referral_expiry_days` days old is not yet expired.

### 2.5. Common Resource Properties

Most resources — networks, taxonomy categories, organizations, service offerings, clients, agreements, consents, referrals, rate cards, claims, disbursements, and funder reports — carry a standard set of system-managed fields:

- `id` (string): a unique server-minted identifier, formatted as a standard hyphenated UUID (e.g. `3f6b2a1c-...`) with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): starts at its initial value on creation and increments by 1 on every mutation of the resource; it backs optimistic concurrency control.

Two resource families are deliberately leaner. `ReferralNote` and `OutcomeRecord` carry only `id` and `created_at`; both `updated_at` and `version` are absent on them, and no OCC field applies to any operation that creates them.

### 2.6. Nested Resource Retrieval and Validation Order

Endpoints whose paths nest one resource under another — for example an offering under an organization, or a consent under a client — validate path identifiers strictly left to right. The first identifier that does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and no later segment is examined. This ordering guarantee extends into the full validation pipeline: authentication and role checks come first, then org-ownership checks, then existence, then request well-formedness — a request with a missing required field, an invalid enum value, an unknown field, or a foreign-key target that does not exist is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — then optimistic-concurrency checks, then state validity, where a resource not in a valid from-state for the requested transition is rejected with `ERR_INVALID_STATE` (HTTP 409), and only then business rules in their declared priority order. A request that fails an earlier category never surfaces a later category's error — a stale-version conflict, for instance, is reported before a state-machine violation, and a state-machine violation before any consent, agreement, eligibility, or capacity failure.

### 2.7. Monetary Values and Integer-Cents Precision

All monetary quantities — balances, rates, claim amounts, escrow, caps — are represented as integer counts of cents. Unit rates are integer cents per unit, so claim amounts are computed with integer multiplication and require no fractional rounding; no claim amount is ever rounded. The single exception to integer precision is the pair of rate percentages on funder reports, which are reported to exactly 1 decimal place using round-half-up. Balances that accrue, such as an organization's `payable_balance_cents`, never go negative; any shortfall is absorbed by the escrow mechanism described in §3.8 rather than by allowing a negative balance.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and only those three. Each requires a non-optional version field in the request body carrying the caller's last observed `version` of the target resource; a request omitting that field (or sending a non-integer) is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a value that does not match the resource's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The check runs after existence checks and before business rules. Endpoints not listed here do not accept a version field.

- Reassigning a referral requires `expected_referral_version` matching the referral's current `version`. This captures the case where another writer has just re-routed the referral — which legitimately overwrites its `receiver_org_id` under the decline-reassign policy — so the current writer's view is stale.
- Approving a payment claim requires `expected_claim_version` matching the claim's current `version`. This captures the case where another writer has just mutated the claim — for example, a void that escrowed the reserve — so the approving writer's view is stale.
- Suspending an organization requires `expected_org_version` matching the organization's current `version`. This captures the case where another writer has just changed org state, so the suspending writer's view is stale.

### 2.9. Network-Level Configuration

A `CareNetwork` is created by a `NetworkCoordinator` with a `name`, a `coordinator_org_name` naming the backbone coordinating organization, and four tunable policy knobs, each with a default applied when omitted: `max_reassignment_count` (default 3) caps how many times a referral may be re-routed after declines or withdrawn accepts before it must be cancelled; `auto_accept_window_hours` (default 72) is the number of hours a routed referral may sit unanswered before a coordinator may escalate it; `unresolved_aging_days` (default 30) is the age threshold beyond which a non-terminal referral counts as aging in funder reports; and `referral_expiry_days` (default 60) is the number of days a referral may sit routed with no accept before the aging sweep expires it. Each knob, like the escrow seed, must be a non-negative integer; a negative or non-integer value is rejected with `ERR_INVALID_REQUEST`. The expiry window is deliberately decoupled from the aging threshold so that aging-but-not-yet-expired referrals remain observable in reports. The network also holds `network_escrow_cents`, a clearing account seeded at creation (default 0) and used to settle clawbacks when a receiver's balance is insufficient, and `network_escrow_reserved_cents`, a computed total of the escrow reserved for voided claims awaiting clawback settlement. The escrow-hold invariant requires that `network_escrow_reserved_cents` always equals the sum of `clawback_reserve_cents` over all claims currently in `VOIDED` status. All computed fields on the network initialize to 0 at creation.

## 3. Business Logic & Workflows

### 3.1. Taxonomy: The Service Vocabulary

Every service in the network is classified under a `ServiceTaxonomyCategory` created by a `NetworkCoordinator` with a short `code` — unique across the network, such as FOOD, HOUSING, or TRANSPORT, with a duplicate `code` rejected as `ERR_INVALID_REQUEST` — and a display `name`. A category is born `ACTIVE`. When a category is retired by a coordinator it moves from `ACTIVE` to `RETIRED`, a terminal state; retirement is blocked with `ERR_CATEGORY_IN_USE` while any `ACTIVE` service offering still references the category's `code`. Once a category is `RETIRED`, any attempt to create a new offering or a new referral naming that code is rejected with `ERR_CATEGORY_RETIRED`. The taxonomy listing accepts an optional `status` filter.

### 3.2. Organization Onboarding and the Network Roster

A `NetworkCoordinator` registers each participant organization with a legal `name`, an `org_type` of `CBO`, `CLINIC`, or `FUNDER`, and a tax identifier `ein` that is unique across the network, with a duplicate `ein` rejected as `ERR_INVALID_REQUEST`. Organizations of type `FUNDER` may further declare a `funder_type` of `HEALTH_PLAN` or `PUBLIC_AGENCY`; for non-funders this field holds `NONE`. The field is accepted as declared for any `org_type` — a `CBO` that submits `HEALTH_PLAN` keeps that value — and defaults to `NONE` when omitted. Registration leaves the organization in `PENDING_REVIEW` with a zeroed `payable_balance_cents`.

Activation moves an organization from `PENDING_REVIEW` to `ACTIVE` and increments its `version`; only `ACTIVE` organizations may participate in routing, agreements, and billing. The organization list supports filtering by `org_type` and `status`.

Suspension is the coordinator's enforcement lever and carries the heaviest cascade in the system. Suspending an organization — which requires the OCC field described in §2.8 and a `suspension_reason` — is allowed only from `ACTIVE`, and only while the organization has no claim in `SUBMITTED` or `UNDER_REVIEW`; otherwise the request is rejected with `ERR_OPEN_CLAIMS_BLOCK_TRANSITION`. On suspension, the reason is captured, every one of the organization's `ACTIVE` service offerings is forced to `PAUSED` (already-`PAUSED` offerings are left as-is), and then the cascade walks outward: first, every `ROUTED` referral currently aimed at this organization as receiver is force-declined by the system with the reason `ORG_SUSPENDED` — the referral moves `ROUTED` → `DECLINED` and its consent is left untouched; second, each affected referral's case reservation is released, decrementing the routed offering's `capacity_consumed` by 1, and the system re-route attempt increments each referral's `reassignment_count` by 1; third, if any affected referral's `reassignment_count` would now exceed the network's `max_reassignment_count`, that referral auto-cancels (`DECLINED` → `CANCELLED`) and its client's `open_referral_count` is decremented. Reactivating a suspended organization moves it `SUSPENDED` → `ACTIVE`, clears the `suspension_reason`, and deliberately leaves its offerings `PAUSED` — resuming them is a separate manual act.

Termination is the final exit, reachable from `ACTIVE` or `SUSPENDED`, and gated twice: any non-terminal referral naming the organization as sender or receiver blocks it with `ERR_OPEN_REFERRALS_BLOCK_TERMINATION`, and a nonzero `payable_balance_cents` blocks it with `ERR_UNSETTLED_BALANCE`. When termination succeeds, every `ACTIVE` data-sharing agreement naming the organization is cascaded to `TERMINATED` (with the consent-revocation consequences described in §3.4), and all of the organization's `ACTIVE` offerings are locked to `PAUSED` terminally (already-`PAUSED` offerings simply remain `PAUSED`).

### 3.3. Service Offerings: Eligibility and Declared Capacity

An organization publishes what it can do through a `ServiceOffering`, declared under the organization by an `OrgAdmin` (or a coordinator on its behalf) and only while the owning organization is `ACTIVE`. The offering names its `category_code` — which must reference an `ACTIVE` taxonomy category, with an unknown code rejected as `ERR_INVALID_REQUEST` and a retired one as `ERR_CATEGORY_RETIRED` — plus a human-readable `description` and a declared caseload `capacity_total` of at least 1. The owning provider is recorded on the offering as its `organization_id`, set by the system from the parent organization at creation. Eligibility criteria ride on the offering: `min_client_age` (default 0; must be a non-negative integer) and `max_client_age` (default 150) bound acceptable client ages; `eligible_zip_codes` restricts geography, with an empty array meaning all zips are accepted; `eligible_genders` lists acceptable gender values (default `["ANY"]`), with the value `ANY` meaning all genders; and `income_cap_annual_cents` imposes an income ceiling, with `null` meaning no income test. Two counters track load: `capacity_consumed` counts this offering's referrals currently holding a reservation, and `capacity_available` is `capacity_total` minus `capacity_consumed` and never goes negative. The case-reservation invariant is exact: at all times, an offering's `capacity_consumed` equals the number of referrals routed to that offering whose status is `ROUTED`, `ACCEPTED`, or `IN_SERVICE`, and every transition that creates or destroys a reservation updates `capacity_consumed` by exactly 1 in the same request.

An offering is born `ACTIVE` with `capacity_consumed` at 0. Pausing flips it to `PAUSED` — an action available to the organization's own `OrgAdmin`, to a coordinator, or to the system cascade during suspension — and a paused offering is not routable, though its consumed capacity is unchanged. Resuming returns it to `ACTIVE` and requires the owning organization to be `ACTIVE`, failing with `ERR_ORG_NOT_ACTIVE` otherwise. The offering listing accepts an optional `status` filter.

### 3.4. Agreements and Consent: The Legal Substrate

Two independent gates must both be open before a referral can flow between two organizations. The first is the `DataSharingAgreement`, created by a `NetworkCoordinator` between a `party_a_org_id` and a `party_b_org_id` — which must differ — with an `effective_at` instant. Direction does not restrict sharing: when an agreement is `ACTIVE`, information may flow both ways between the parties. An agreement starts `PENDING`; a coordinator approves it to `ACTIVE` only once `effective_at` is at or before the server clock (otherwise `ERR_AGREEMENT_NOT_YET_EFFECTIVE`) and only while both party organizations are `ACTIVE` (otherwise `ERR_ORG_NOT_ACTIVE`). Expiring an agreement moves it `ACTIVE` → `EXPIRED`, after which new referrals between the parties are blocked with `ERR_AGREEMENT_INACTIVE` while existing non-terminal referrals are unaffected. Agreements may be listed globally with `party_a_org_id`, `party_b_org_id`, and `status` filters, or per organization.

Terminating an agreement — by a coordinator's explicit act or by the cascade from an organization's termination — moves it `ACTIVE` → `TERMINATED` and fires the consent cascade: every consent whose (`sender_org_id`, `receiver_org_id`) pair matches either party direction of the agreement moves `ACTIVE` → `REVOKED` with its `revoked_at` set to the clock, and each such revocation then fires the full revocation consequences described below.

The second gate is the `Consent`, recorded under a client by a `CaseWorker` (or coordinator) and naming the `sender_org_id` and `receiver_org_id` it authorizes plus a `scope` of `FULL` or `MINIMUM_NECESSARY`. Under `MINIMUM_NECESSARY`, client contact fields are hidden from receiver-side reads. A consent is born `ACTIVE`. Revocation — by the client's `CaseWorker`, by a coordinator, or by the agreement cascade — stamps `revoked_at` and propagates in three hops. First, every referral riding on this consent that is in `DRAFT`, `ROUTED`, `DECLINED`, or `ESCALATED` is cancelled with the reason `CONSENT_REVOKED`. Second, for each such cancelled referral that was in `ROUTED`, the receiving offering's `capacity_consumed` is decremented by 1, releasing the reservation. Third, each cancelled referral decrements its client's `open_referral_count`, and every payment claim in `SUBMITTED` or `UNDER_REVIEW` whose referral rode on this consent is voided — regardless of whether that referral itself was cancelled — with the clawback reserve funded from the network escrow: the reserve equals the claim's `approved_amount_cents` when set, otherwise its `provisional_amount_cents`; `network_escrow_cents` is debited by the reserve and `network_escrow_reserved_cents` credited by the same amount. The entire revocation is rejected atomically with `ERR_ESCROW_EXHAUSTED` if the escrow cannot cover the total reserve — no partial revocation is committed. The escrow requirement applies only when the total reserve is nonzero: when no claims need voiding, revocation requires no escrow and proceeds even if the network or its escrow is absent. Referrals already `IN_SERVICE` or `OUTCOME_RECORDED` are not cancelled, since service is already underway; instead they become non-billable evidence, and any new claim submitted against them is rejected with `ERR_CONSENT_REVOKED`.

### 3.5. Clients and the Referral Lifecycle

A `CaseWorker` registers a `Client` with a `full_name`, a `date_of_birth` (an ISO `YYYY-MM-DD` date used for age evaluation at referral time), a residential `zip_code`, and a `gender` of `FEMALE`, `MALE`, `NONBINARY`, or `UNDISCLOSED`. Optional demographics — `annual_income_cents` (with `null` meaning undisclosed), `race` (one of `AMERICAN_INDIAN`, `ASIAN`, `BLACK`, `PACIFIC_ISLANDER`, `WHITE`, `MULTIRACIAL`, `UNDISCLOSED`), `ethnicity` (`HISPANIC`, `NON_HISPANIC`, `UNDISCLOSED`), preferred `language` (default `en`), and `veteran_status` (default false) — feed funder reporting. The client's `open_referral_count` starts at 0 and tracks how many of the client's referrals are not yet in a terminal state.

A referral begins when a `CaseWorker` creates it against a client with a `sender_org_id`, a candidate `receiver_org_id`, a target `service_offering_id`, the authorizing `consent_id`, the `category_code` snapshot, and an `urgency` of `STANDARD` (the default) or `URGENT`. Creation lands the referral in `DRAFT` — consent and category are validated eagerly, but no capacity is reserved yet. Eager validation at creation checks only that the named consent exists and is `ACTIVE` (otherwise `ERR_CONSENT_REQUIRED`) and that the named category exists and is not retired; the requirement that the consent match the sender-receiver pair is enforced by the routing gate below, not at creation.

Routing is the gate-keeper transition, `DRAFT` → `ROUTED`, performed by the `CaseWorker`, and its preconditions are evaluated in the platform's global validation order after authentication, ownership, existence, well-formedness, and state checks. Within the business-rule stage the checks fire in this order: first consent — an `ACTIVE` consent must match the sender-receiver pair, failing with `ERR_CONSENT_REQUIRED`; then agreement — an `ACTIVE` agreement must cover the sender-receiver pair in either direction, failing with `ERR_AGREEMENT_INACTIVE`; then offering and category — the named offering must belong to the receiver, match the referral's `category_code`, and itself be `ACTIVE`, failing with `ERR_OFFERING_MISMATCH`, and the category must exist and not be retired, failing with `ERR_CATEGORY_RETIRED`. Then eligibility: the client's age in whole years at referral creation — the complete years between `date_of_birth` and the referral creation date, computed against a year length of 365.25 days and rounded down — must be at least `min_client_age` and at most `max_client_age` (both bounds inclusive); the client's zip must be a member of `eligible_zip_codes` unless that list is empty; the client's gender must appear in `eligible_genders` unless that list contains `ANY`; and when `income_cap_annual_cents` is set, the client must have disclosed an income strictly below the cap — income exactly equal to the cap fails, and an undisclosed income fails a capped offering. Any eligibility failure is `ERR_ELIGIBILITY_FAILED`. Then the offering must have at least 1 unit of `capacity_available`, failing with `ERR_CAPACITY_EXHAUSTED`. Finally the receiver must be of `org_type` `CBO`, failing with `ERR_RECEIVER_NOT_CBO`, and both the sender organization and the receiver organization must be `ACTIVE`, failing with `ERR_ORG_NOT_ACTIVE`. A successful route reserves the case: the offering's `capacity_consumed` increments by 1 and the client's `open_referral_count` increments by 1.

The receiving organization's `OrgAdmin` then answers. Accepting moves `ROUTED` → `ACCEPTED` and requires the caller's organization to be the current `receiver_org_id` (else `ERR_FORBIDDEN_ORG`) and at least 1 unit of `capacity_available` on the current offering (else `ERR_CAPACITY_EXHAUSTED`); the service window opens. Declining moves `ROUTED` → `DECLINED` with the same ownership rule, takes a free-text `reason`, releases the reservation (`capacity_consumed` decrements by 1), and increments `reassignment_count`; if that count now exceeds the network's `max_reassignment_count`, the referral auto-cancels to `CANCELLED` and the client's `open_referral_count` decrements — so with the default cap of 3, a fourth decline is rejected into cancellation.

A declined referral can be re-routed by a `CaseWorker` or `NetworkCoordinator` to a `new_receiver_org_id` and `new_service_offering_id`, which overwrites the referral's `receiver_org_id` and `service_offering_id` and reserves capacity on the new offering. An optional `new_consent_id` may name a specific consent of the client to ride on; when supplied, that consent must exist, be `ACTIVE`, belong to the referral's client, and match the (sender, new receiver) pair — and the referral's recorded `consent_id` is rewritten to it — while a nonexistent `new_consent_id` is rejected with `ERR_INVALID_REQUEST`. The new receiver must differ from the one that just declined — otherwise `ERR_REASSIGNMENT_LOOP` — and the re-route re-runs the full routing gate against the new target: consent, agreement with the sender, offering ownership and category match, eligibility, capacity, receiver type, and org status. When no `new_consent_id` is given, the re-run consent check does not rely on the recorded `consent_id` alone: it searches the client's `ACTIVE` consents existentially for one whose (`sender_org_id`, `receiver_org_id`) matches the (sender, new receiver) pair, failing with `ERR_CONSENT_REQUIRED` when none matches. A decline-reassign does not itself increment `reassignment_count` — the increment was already charged by the decline that freed the slot — nor `reopen_count`. Because reassignment is OCC-guarded (§2.8), the request must carry `expected_referral_version`.

Coordinator oversight watches referrals that sit. Escalation — `ROUTED` → `ESCALATED`, a `NetworkCoordinator` act — requires the referral to be genuinely aging: the whole hours elapsed since it was routed must strictly exceed the network's `auto_accept_window_hours`, with that window halved for `URGENT` referrals (integer division, fractions discarded); a referral exactly at the window is not aging and the request fails with `ERR_NOT_AGING`. Escalation changes only oversight state — the receiver is unchanged and the coordinator's queue gains the referral. The coordinator may then reassign an escalated referral under the same rules as a decline-reassign, including the loop check and the OCC field; an escalation-reassign additionally increments `reopen_count` as well as `reassignment_count` (which continues to count against the reassignment cap), and it swaps reservations — the old offering's `capacity_consumed` decrements by 1 while the new offering's increments by 1.

Cancellation is available to a `CaseWorker` (or the system) from any of `DRAFT`, `ROUTED`, `ACCEPTED`, `DECLINED`, or `ESCALATED`, carrying a `reason`. Cancelling from `ROUTED`, `ACCEPTED`, or `ESCALATED` releases the held reservation; from any state it decrements the client's `open_referral_count`. A referral that outlives its welcome in `ROUTED` — whole days since routing strictly greater than `referral_expiry_days` — is moved to `EXPIRED` by the aging sweep, with the same reservation release and count decrement. `CANCELLED`, `EXPIRED`, and `OUTCOME_RECORDED` are the referral's terminal states.

The referral list endpoint supports filters on `client_id`, `sender_org_id`, `receiver_org_id`, `service_offering_id`, `consent_id`, `status`, and an `aging_only` flag — treated as true when its value is one of `true`, `1`, or `yes` case-insensitively, restricting results to non-terminal referrals whose `aging_days` strictly exceeds the network's `unresolved_aging_days` — alongside the standard pagination parameters; referrals currently holding a reservation on a given offering (statuses `ROUTED`, `ACCEPTED`, or `IN_SERVICE`) and referrals belonging to a given client are also listable through their parent resources.

### 3.6. Notes, Service Delivery, and Outcome Confirmation

While a referral is in flight, participants annotate it. A `ReferralNote` carries a `body` of free text and a `visibility` of `NETWORK` (the default), `SENDER_ONLY`, or `RECEIVER_ONLY`; the author's organization is captured from the caller identity into `author_org_id` — for a `NetworkCoordinator`, whose identity is not entity-backed, the full `X-User-ID` is recorded instead. Notes are listed per referral, and the set of notes authored by an organization is separately listable.

Once accepted, the receiver's `OrgAdmin` marks service started, moving `ACCEPTED` → `IN_SERVICE` and stamping `service_started_at` with the server clock — the billable window opens. Delivery concludes with outcome confirmation, moving `IN_SERVICE` → `OUTCOME_RECORDED`, where the receiver reports an `outcome_code` of `DELIVERED`, `PARTIALLY_DELIVERED`, `NOT_REACHED`, or `CLIENT_DECLINED` together with the `delivered_units`. Units must agree with the outcome: at least 1 unit for `DELIVERED` or `PARTIALLY_DELIVERED`, exactly 0 for `NOT_REACHED` or `CLIENT_DECLINED`, with any mismatch rejected as `ERR_OUTCOME_UNITS_MISMATCH`. Confirmation creates the referral's single `OutcomeRecord` — exactly one per referral; a second is a duplicate — capturing the `outcome_code`, `delivered_units`, the reporting organization as `reported_by_org_id`, and the server timestamp as `reported_at`. The record's `billable` flag is true precisely when the outcome is `DELIVERED` or `PARTIALLY_DELIVERED` with at least 1 delivered unit. The case closes: the offering's `capacity_consumed` decrements by 1, the client's `open_referral_count` decrements by 1, and the referral's `aging_days` — whole days from creation to the earlier of the terminal transition and the clock, 0 while the referral sat in `DRAFT` — freezes at its terminal value. The confirmation response returns the updated referral object; the created `OutcomeRecord` is retrievable through its referral (an array of zero or one) or listed per reporting organization.

### 3.7. Claims: Rate Cards, Adjudication, and Segregation of Duties

Payment begins with the funder's price list. A `FunderAdmin` (or coordinator) publishes a `ServiceRateCard` under a funder organization — which must be an `ACTIVE` `FUNDER`, with either condition failing as `ERR_ORG_NOT_ACTIVE` — naming the `category_code` it prices, a base `rate_cents_per_unit` of at least 1, a tier boundary `min_units` (default 1, and always at least 1), an optional `tier2_rate_cents_per_unit` (with `null` meaning a flat rate), and an optional `monthly_cap_cents` (with `null` meaning uncapped). A rate card is born `ACTIVE`.

The provider organization then bills. An `OrgAdmin` submits a `PaymentClaim` naming the `referral_id`, the `funder_org_id` to bill, and the `claimed_units`. Submission gates hard, checked in this order: the referral's consent must still be `ACTIVE`, else `ERR_CONSENT_REVOKED`; the funder must hold an `ACTIVE` agreement with the provider (the referral's receiver at submission), else `ERR_AGREEMENT_INACTIVE`; `claimed_units` must equal the referral outcome's `delivered_units`, else `ERR_OUTCOME_UNITS_MISMATCH`; exactly one claim may exist per referral, else `ERR_DUPLICATE_CLAIM`; and the referral must be `OUTCOME_RECORDED` with a billable outcome, else `ERR_REFERRAL_NOT_BILLABLE`. Submission also requires an `ACTIVE` rate card from the named funder for the referral's category; its absence is rejected with `ERR_INVALID_REQUEST`. At submission the claim lands in `SUBMITTED` with a `provisional_amount_cents` quote: the per-unit rate is selected from that rate card — the flat `rate_cents_per_unit` when no tier-2 rate is set or when `claimed_units` is strictly below `min_units`, otherwise the `tier2_rate_cents_per_unit`, with the tier-2 rate applying exactly at `min_units` — and the provisional amount is simply `claimed_units` times that per-unit rate, with no monthly cap applied. The provisional figure is deliberately optimistic: it can exceed the final approved amount.

Adjudication is a two-person affair. A `FunderAdmin` of the billed funder — the caller's organization must equal the claim's `funder_org_id`, else `ERR_FORBIDDEN_ORG` — moves the claim `SUBMITTED` → `UNDER_REVIEW`, and the system records that caller's full `X-User-ID` into `reviewed_by_user_id`. Approval — `UNDER_REVIEW` → `APPROVED`, OCC-guarded by `expected_claim_version` and subject to the same caller-organization rule — first requires the referral's consent to still be `ACTIVE` at that moment, failing with `ERR_CONSENT_REVOKED`, and then must come from a `FunderAdmin` of the same funder whose full `X-User-ID` differs from `reviewed_by_user_id`; sameness is rejected with `ERR_SEGREGATION_OF_DUTIES`. The approved amount is the final variant of the quote, computed in a fixed order: first the gross is `claimed_units` times the tier-selected per-unit rate; then the funder's paid-to-date for the current calendar month is summed from the `approved_amount_cents` of this funder's other claims approved in that same month (by approval timestamp), explicitly excluding this claim, with claims approved that month but later voided contributing only their net `approved_amount_cents` minus `clawback_reserve_cents`; then the remaining cap is `monthly_cap_cents` minus that paid-to-date (treated as unbounded when the card is uncapped); and finally `approved_amount_cents` is the gross clamped to the remaining cap, floored at zero. A claim never contributes to its own cap residue, and the final amount may be strictly less than the provisional quote. Approval credits the provider's `payable_balance_cents` by the approved amount. Denial — `UNDER_REVIEW` → `DENIED`, with a stored `reason` — carries the same segregation-of-duties rule as approval.

### 3.8. Voids, Escrow, and Disbursements

A claim may be voided by a `FunderAdmin` or coordinator with a `reason`. Voiding from `SUBMITTED` or `UNDER_REVIEW` moves the claim to `VOIDED`, sets `clawback_reserve_cents` to the `provisional_amount_cents`, and funds that reserve from the network escrow: `network_escrow_cents` is debited and `network_escrow_reserved_cents` credited, upholding the escrow-hold invariant. Voiding an `APPROVED` claim is the clawback path and is blocked once the claim has been paid out, with `ERR_CLAIM_ALREADY_PAID`. The clawback first debits the provider's `payable_balance_cents` by the `approved_amount_cents` (never below zero); the shortfall — the approved amount minus what the balance could absorb — becomes the `clawback_reserve_cents`, drawn from `network_escrow_cents` and added to `network_escrow_reserved_cents`. Because the clawbacked claim retains its `approved_at` timestamp in `VOIDED` status, future cap computations recover the clawed-back share of its amount automatically (see §3.7). If the escrow cannot cover the shortfall, the entire void is rejected atomically with `ERR_ESCROW_EXHAUSTED` — no partial clawback ever commits. Claims may be listed with `referral_id`, `funder_org_id`, `provider_org_id`, and `status` filters.

Actual money movement is batched. A `FunderAdmin` schedules a `Disbursement` naming the `provider_org_id` to pay, the authorizing `funder_org_id`, and an explicit `claim_ids` list; the batch starts `SCHEDULED` with `total_amount_cents` 0. Running the batch — restricted to a `FunderAdmin` of the disbursement's own `funder_org_id` (else `ERR_FORBIDDEN_ORG`) and only while the batch is `SCHEDULED` — is all-or-nothing: every listed claim must be `APPROVED` and belong to the named provider, else `ERR_CLAIM_NOT_PAYABLE`, and the provider organization must be `ACTIVE`, else `ERR_ORG_NOT_ACTIVE`. A successful run computes `total_amount_cents` as the sum of the included claims' `approved_amount_cents` at run time, moves each claim `APPROVED` → `PAID`, settles each claim against the provider's `payable_balance_cents`, and moves the batch itself to `PAID`. A run invoked with `simulate_failure` set true instead moves the batch to `FAILED`, captures the `failure_reason` (defaulting to `"Simulated failure"` when omitted), and touches nothing else — no claim changes state and the provider balance is unchanged, so no partial payout is ever observable. Disbursements may be listed with `provider_org_id`, `funder_org_id`, and `status` filters.

### 3.9. Funder Reporting: Dual Closure Rates and k-Anonymity

Funders close the loop with the `FunderReport`. A `FunderAdmin` (or coordinator) generates one under the funder organization for a `period_start` and `period_end` — both inclusive ISO dates, with `period_end` at or after `period_start` — and the computed metrics are evaluated at creation, while the report sits in `DRAFT`. A report still in `DRAFT` re-computes its metrics on every read (get or list), so it tracks the network until sealed. The report's population is the referrals created within the period whose `receiver_org_id` shares an `ACTIVE` agreement with this funder at evaluation time: `total_referrals` counts them all; `delivered_count` counts those whose outcome record — whenever it was recorded — shows `DELIVERED` or `PARTIALLY_DELIVERED`; `not_reached_count` counts those whose outcome record shows `NOT_REACHED` or `CLIENT_DECLINED`; `unresolved_count` counts period referrals not in `CANCELLED`, `EXPIRED`, or `OUTCOME_RECORDED` at evaluation time; and `aging_count` counts those unresolved referrals whose `aging_days` strictly exceeds the network's `unresolved_aging_days` — a referral exactly at the threshold is not aging. `total_reimbursed_cents` sums the `approved_amount_cents` of claims approved within the period (by approval timestamp), net of any clawbacks: a claim approved in the period but later voided contributes its `approved_amount_cents` minus its `clawback_reserve_cents`.

Two headline rates deliberately diverge. `closure_rate_percent` is the deliverable-facing metric: `delivered_count` divided by `total_referrals`, times 100. `resolution_rate_percent` is the closed-loop-facing metric: the sum of `delivered_count` and `not_reached_count` divided by `total_referrals`, times 100 — every confirmed outcome counts, delivered or not. Both are 0.0 when `total_referrals` is zero, both are reported to 1 decimal place with round-half-up, and the two always differ by exactly `not_reached_count` over `total_referrals` times 100: a not-reached outcome raises the resolution rate while leaving the closure rate's numerator untouched. The pair is consistent by construction with the unresolved counts — a report in which every referral is unresolved shows a closure rate of 0.0 and `unresolved_count` equal to `total_referrals`.

The `demographic_breakdown` reports counts over the clients of period referrals, keyed by the pipe-delimited tuple `gender|race|ethnicity|veteran_status|language` (veteran status rendered lowercase as `true`/`false`), under k-anonymity with a threshold of 5: any cell whose raw count is at least 5 is reported as-is; cells below 5 contribute their counts to a single synthetic `SUPPRESSED` bucket; and that bucket is itself reported only when its total reaches at least 5. When the suppressed total is between 1 and 4, the bucket is omitted entirely — the breakdown then deliberately does not sum to `total_referrals`, and that visible gap is the signal that suppression occurred.

Sealing is the point of no return: a `FunderAdmin` of the report's own funder organization (else `ERR_FORBIDDEN_ORG`) moves the report `DRAFT` → `SEALED`, freezing `baseline_snapshot_cents` — the total `approved_amount_cents` across all claims known at seal time, network-wide — and arming the sealed-report invariant, under which a sealed report's metrics never change afterwards, with later-approved claims reconciling only against the snapshot delta. Reports are listed per funder with an optional `status` filter.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state-transition actions, return `200 OK`. The complete endpoint inventory is:

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/care-network/_clock/set_current_utc` | Set the server logical clock; triggers the aging sweep | NetworkCoordinator |
| POST | `/care-network/networks` | Create a CareNetwork | NetworkCoordinator |
| GET | `/care-network/networks/{id}` | Get a CareNetwork | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| POST | `/care-network/taxonomy` | Create a ServiceTaxonomyCategory | NetworkCoordinator |
| GET | `/care-network/taxonomy` | List taxonomy categories | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| GET | `/care-network/taxonomy/{id}` | Get a category | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| POST | `/care-network/taxonomy/{id}/retire` | Retire a category | NetworkCoordinator |
| POST | `/care-network/organizations` | Register an organization (CBO onboarding entry point) | NetworkCoordinator |
| GET | `/care-network/organizations` | List organizations | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| GET | `/care-network/organizations/{id}` | Get an organization | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| POST | `/care-network/organizations/{id}/activate` | Activate an organization (PENDING_REVIEW or SUSPENDED → ACTIVE) | NetworkCoordinator |
| POST | `/care-network/organizations/{id}/suspend` | Suspend an organization; cascades to offerings and routed referrals (OCC-guarded) | NetworkCoordinator |
| POST | `/care-network/organizations/{id}/terminate` | Terminate an organization | NetworkCoordinator |
| POST | `/care-network/organizations/{id}/offerings` | Declare a service offering with eligibility and capacity | OrgAdmin, NetworkCoordinator |
| GET | `/care-network/organizations/{id}/offerings` | List an organization's offerings | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| GET | `/care-network/offerings/{id}` | Get an offering | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| POST | `/care-network/offerings/{id}/pause` | Pause an offering | OrgAdmin, NetworkCoordinator |
| POST | `/care-network/offerings/{id}/resume` | Resume an offering | OrgAdmin, NetworkCoordinator |
| POST | `/care-network/clients` | Register a client | CaseWorker, NetworkCoordinator |
| GET | `/care-network/clients/{id}` | Get a client | NetworkCoordinator, CaseWorker |
| POST | `/care-network/agreements` | Create a DataSharingAgreement between two organizations | NetworkCoordinator |
| GET | `/care-network/agreements` | List agreements | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| GET | `/care-network/organizations/{id}/agreements` | List agreements naming this organization as either party | NetworkCoordinator, FunderAdmin, OrgAdmin, CaseWorker |
| POST | `/care-network/agreements/{id}/approve` | Approve an agreement (effective_at must have arrived) | NetworkCoordinator |
| POST | `/care-network/agreements/{id}/expire` | Expire an agreement | NetworkCoordinator |
| POST | `/care-network/agreements/{id}/terminate` | Terminate an agreement; cascades consent revocation | NetworkCoordinator |
| POST | `/care-network/clients/{id}/consents` | Record client consent for a sender/receiver organization pair | CaseWorker, NetworkCoordinator |
| GET | `/care-network/consents` | List consents filtered by counterparty organization | NetworkCoordinator, CaseWorker, OrgAdmin |
| GET | `/care-network/clients/{id}/consents` | List a client's consents | NetworkCoordinator, CaseWorker |
| GET | `/care-network/consents/{id}` | Get a consent | NetworkCoordinator, CaseWorker, OrgAdmin |
| POST | `/care-network/consents/{id}/revoke` | Revoke consent; propagates referral cancellation and claim void cascade | CaseWorker, NetworkCoordinator |
| POST | `/care-network/referrals` | Create a referral in DRAFT (consent and category validated eagerly) | CaseWorker |
| GET | `/care-network/referrals` | List referrals (coordinator oversight of unresolved/aging) | NetworkCoordinator, CaseWorker, OrgAdmin, FunderAdmin |
| GET | `/care-network/offerings/{id}/referrals` | List referrals currently holding a reservation on an offering (ROUTED, ACCEPTED, or IN_SERVICE) | NetworkCoordinator, CaseWorker, OrgAdmin |
| GET | `/care-network/referrals/{id}` | Get a referral | NetworkCoordinator, CaseWorker, OrgAdmin, FunderAdmin |
| POST | `/care-network/referrals/{id}/route` | Route a DRAFT referral (eligibility and capacity gate) | CaseWorker |
| POST | `/care-network/referrals/{id}/accept` | Receiver accepts | OrgAdmin |
| POST | `/care-network/referrals/{id}/decline` | Receiver declines; reservation released; overflow auto-cancel | OrgAdmin |
| POST | `/care-network/referrals/{id}/reassign` | Re-route a DECLINED or ESCALATED referral to a new receiver (OCC-guarded) | CaseWorker, NetworkCoordinator |
| POST | `/care-network/referrals/{id}/escalate` | Coordinator escalates an aging ROUTED referral | NetworkCoordinator |
| POST | `/care-network/referrals/{id}/start-service` | Receiver marks service started | OrgAdmin |
| POST | `/care-network/referrals/{id}/confirm-outcome` | Receiver confirms closed-loop outcome | OrgAdmin |
| POST | `/care-network/referrals/{id}/cancel` | Cancel a non-terminal referral | CaseWorker, NetworkCoordinator |
| GET | `/care-network/clients/{id}/referrals` | List a client's referrals | NetworkCoordinator, CaseWorker |
| POST | `/care-network/referrals/{id}/notes` | Add a referral note | CaseWorker, OrgAdmin, NetworkCoordinator |
| GET | `/care-network/referrals/{id}/notes` | List notes on a referral | NetworkCoordinator, CaseWorker, OrgAdmin |
| GET | `/care-network/organizations/{id}/notes` | List referral notes authored by an organization | NetworkCoordinator, CaseWorker, OrgAdmin |
| GET | `/care-network/referrals/{id}/outcome` | Get the OutcomeRecord of a referral (array of 0 or 1) | NetworkCoordinator, CaseWorker, OrgAdmin, FunderAdmin |
| GET | `/care-network/organizations/{id}/outcomes` | List outcome records reported by an organization | NetworkCoordinator, FunderAdmin, OrgAdmin |
| POST | `/care-network/organizations/{id}/rate-cards` | Funder publishes a rate card for a category | FunderAdmin, NetworkCoordinator |
| GET | `/care-network/organizations/{id}/rate-cards` | List a funder's rate cards | NetworkCoordinator, FunderAdmin, OrgAdmin |
| GET | `/care-network/rate-cards/{id}` | Get a rate card | NetworkCoordinator, FunderAdmin, OrgAdmin |
| POST | `/care-network/claims` | Submit a payment claim for an OUTCOME_RECORDED referral | OrgAdmin |
| GET | `/care-network/claims` | List claims | NetworkCoordinator, FunderAdmin, OrgAdmin |
| GET | `/care-network/claims/{id}` | Get a claim | NetworkCoordinator, FunderAdmin, OrgAdmin |
| POST | `/care-network/claims/{id}/review` | Move claim to UNDER_REVIEW | FunderAdmin |
| POST | `/care-network/claims/{id}/approve` | Approve a claim; computes the final amount with the cap waterfall (OCC-guarded) | FunderAdmin |
| POST | `/care-network/claims/{id}/deny` | Deny a claim | FunderAdmin |
| POST | `/care-network/claims/{id}/void` | Void a claim; clawback path for APPROVED claims | FunderAdmin, NetworkCoordinator |
| POST | `/care-network/disbursements` | Schedule a payout batch to a provider organization | FunderAdmin |
| GET | `/care-network/disbursements` | List disbursements | NetworkCoordinator, FunderAdmin, OrgAdmin |
| GET | `/care-network/disbursements/{id}` | Get a disbursement | NetworkCoordinator, FunderAdmin, OrgAdmin |
| POST | `/care-network/disbursements/{id}/run` | Execute a payout batch (saga: all-or-nothing) | FunderAdmin |
| POST | `/care-network/organizations/{id}/reports` | Generate a FunderReport (DRAFT) for a period | FunderAdmin, NetworkCoordinator |
| GET | `/care-network/reports/{id}` | Get a report | NetworkCoordinator, FunderAdmin |
| GET | `/care-network/organizations/{id}/reports` | List a funder's reports | NetworkCoordinator, FunderAdmin |
| POST | `/care-network/reports/{id}/seal` | Seal a report; freezes metrics | FunderAdmin |
| POST | `/care-network/referrals/aging-sweep` | Run the aging sweep now: expire idle ROUTED referrals past the expiry window | NetworkCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narrative of §2 and §3; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_ORG` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONSENT_REQUIRED` | 422 |
| `ERR_CONSENT_REVOKED` | 422 |
| `ERR_AGREEMENT_INACTIVE` | 422 |
| `ERR_AGREEMENT_NOT_YET_EFFECTIVE` | 409 |
| `ERR_OFFERING_MISMATCH` | 422 |
| `ERR_CATEGORY_RETIRED` | 422 |
| `ERR_CATEGORY_IN_USE` | 409 |
| `ERR_ELIGIBILITY_FAILED` | 422 |
| `ERR_CAPACITY_EXHAUSTED` | 409 |
| `ERR_NOT_AGING` | 409 |
| `ERR_REASSIGNMENT_LOOP` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_OUTCOME_UNITS_MISMATCH` | 422 |
| `ERR_ESCROW_EXHAUSTED` | 402 |
| `ERR_UNSETTLED_BALANCE` | 409 |
| `ERR_OPEN_CLAIMS_BLOCK_TRANSITION` | 409 |
| `ERR_OPEN_REFERRALS_BLOCK_TERMINATION` | 409 |
| `ERR_RECEIVER_NOT_CBO` | 422 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_REFERRAL_NOT_BILLABLE` | 422 |
| `ERR_CLAIM_NOT_PAYABLE` | 409 |
| `ERR_CLAIM_ALREADY_PAID` | 409 |
| `ERR_ORG_NOT_ACTIVE` | 409 |
