# Values-Led Creamery API — Product Requirements Document

## 1. Introduction

This document specifies the Values-Led Creamery API, the system of record for an ice-cream business whose brand promise is that its social mission is not marketing copy but an auditable operating discipline. The company buys dairy, cocoa, sugar, vanilla, nuts, fruit, and chunk inclusions under written sourcing commitments; it pays dairy farms a premium above the commodity price for verified environmental and animal-welfare practices; it substantiates every sourcing claim printed on a pint against third-party certifications; and it lets fans petition retired flavors back into production. What makes the business unusual is its governance: an independent board holds sole authority over social-mission decisions — activism campaign approval and veto, revival adoption, and the policing of mission claims — while the parent company retains operational control over flavor retirement, campaign scheduling and launch, premium disbursement, and the platform's logical clock.

The API exists to make that division of authority executable. Every public claim must trace back to certifications in a verified state. Every farm premium must follow one published formula with a provisional and a final variant. An auditor who performs a supplier audit may not be the person who verifies it, and a board member who proposes a campaign may not cast its board decision. Fans may open and sign revival requests, but only the board may adopt one. Franchise scoop shops — including a partner-shop model for verified nonprofit operators — order product against credit limits and plant capacity that the system enforces at confirmation and allocation time.

All resources are mounted under the `/creamery` prefix. Time-dependent behavior (certification expiry, commitment lapse, production-slot completion, and the revival window) is governed by a server-held logical clock, never by wall-clock time, so that every temporal rule in this document is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contract and the cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role the platform does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Ownership violations — acting on a resource that belongs to someone else — are rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

The platform declares eleven roles, spelled exactly as follows:

- `SourcingManager` — owns suppliers, sourcing commitments, certifications, and audit scheduling.
- `SustainabilityAuditor` — performs supplier audits; may never verify an audit they performed.
- `AuditVerifier` — verifies audits and certifications and revokes certifications; independent of both the `SourcingManager` and the performing auditor.
- `DairyProgramManager` — runs the dairy farm program: enrollments, assessments, and premium-payment calculation, approval, and voiding.
- `FlavorManager` — owns flavor lifecycle promotion, claim substantiation and publication, and revival return-to-line.
- `PlantScheduler` — schedules plant production and allocates supply orders to plant-day capacity.
- `IndependentBoardMember` — the independent board; sole authority over social-mission decisions: campaign approval and veto, revival adoption and decline, and claim challenges.
- `ParentOpsController` — the parent company's operational control: flavor retirement, campaign operations scheduling and launch, premium disbursement, and the logical clock.
- `FranchiseAdmin` — administers the scoop shop program: applications, site approval, openings, suspensions, and order confirmation.
- `ShopOperator` — the operator of one scoop shop.
- `Fan` — an ice-cream fan who opens and signs flavor revival requests.

**Identity semantics.** When `X-User-Role` is `ShopOperator`, `X-User-ID` is the `id` of the acting `ScoopShop`; ownership checks on any resource that references a `ScoopShop` compare the resource's foreign-key field (or the path's scoop-shop identifier) to `X-User-ID`. When `X-User-Role` is any of `SourcingManager`, `SustainabilityAuditor`, `AuditVerifier`, `DairyProgramManager`, `FlavorManager`, `PlantScheduler`, `IndependentBoardMember`, `ParentOpsController`, `FranchiseAdmin`, or `Fan`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `auditor_user_id` on an `Audit` when a `SustainabilityAuditor` starts the audit, or as `proposer_user_id` and `decided_by_user_id` on a `Campaign` — but it does not compare such an identifier to any entity's `id` except where a segregation-of-duties or audit-ownership rule explicitly says so (see §2.9).

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

List endpoints paginate through two query parameters. The `limit` parameter caps how many items one response returns; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100 — out-of-range values are clamped, not rejected: a `limit` below 1 is treated as 1, a `limit` above 100 as 100, and a negative `offset` as 0, while a non-integer `limit` or `offset` is a malformed value rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `offset` parameter says how many items to skip and defaults to 0. Unless an endpoint states otherwise, every list is sorted by `created_at` in ascending order — oldest first.

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Several list endpoints additionally accept a `status` query parameter that filters to one lifecycle state, and the production-slot list accepts `flavor_id`, `plant_code`, and `production_date` filters in addition to `status`. A filter value that matches no lifecycle state (or no resource) of the endpoint is not an error; it simply yields an empty page.

### 2.4. Common Resource Properties

Every resource in the platform — Supplier, SourcingCommitment, Certification, Audit, FarmProgramEnrollment, PremiumPayment, Flavor, RevivalRequest, ProductionSlot, Campaign, ScoopShop, and ShopSupplyOrder — carries the same four system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by one on every mutation; it is the basis of optimistic concurrency control (§2.7).

A mutation is any change to a resource's own fields, including transitions of its lifecycle state, recomputation of a computed field, and cascaded writes described in §3. When §3 says an operation "bumps the supplier's version" or increments a version, that means `version` increases by exactly 1 and `updated_at` refreshes, even though the client touched a different resource.

Requests with a missing required field or a malformed value are rejected with `ERR_INVALID_REQUEST` (HTTP 400). A field declared as an enum that receives a value outside its declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400); an enum field whose value is not a string at all is instead malformed and fails with `ERR_INVALID_REQUEST`.

### 2.5. The Logical Clock

The platform keeps a single server-side logical clock. Before any client touches it, the clock reads exactly `2026-09-01T00:00:00Z`; the server never consults wall-clock time for business rules. A `ParentOpsController` may advance the clock through an admin-only capability that takes a target instant `to_iso8601` and reports the resulting `current_utc`. The clock is monotonic: a request to set it to an instant earlier than the current logical time is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422).

Advancing the clock is not a bookkeeping no-op; it triggers three time-driven evaluations, which are also applied lazily at the start of every request — reads and writes alike observe their effects:

1. **Certification expiry.** A certification in `PENDING` or `VERIFIED` whose `valid_until` is strictly earlier than the current logical time transitions to `EXPIRED`. Every flavor claim in `PUBLISHED` status that cites that certification is retracted to `RETRACTED` — a depth-2 cascade from clock advance to certification expiry to claim retraction.
2. **Commitment lapse.** A sourcing commitment in `ACTIVE` whose `effective_to` is strictly earlier than the current logical time transitions to `LAPSED`. At exactly `effective_to` the commitment is still `ACTIVE`; the window end is exclusive.
3. **Production-slot completion.** A production slot in `CONFIRMED` whose `production_date` is strictly before the current logical date transitions to `COMPLETED`.

The revival window described in §3.6 and the slot-date rule in §3.4 also read the logical clock, never wall-clock time.

### 2.6. Nested Resource Retrieval and Validation Precedence

Many resources live beneath a parent: commitments, certifications, and audits beneath a supplier; premium payments beneath an enrollment; revival requests beneath a flavor; supply orders beneath a scoop shop. For any request whose path contains more than one identifier, the server validates existence strictly left to right — the supplier before its commitment collection, the shop before its order, the flavor before its revival requests — and rejects the request with the not-found error of the first missing resource it encounters. The not-found vocabulary is per resource type: `ERR_SUPPLIER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_FLAVOR_NOT_FOUND`, `ERR_REVIVAL_REQUEST_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, and `ERR_ORDER_NOT_FOUND`, each with HTTP 404. The same 404 discipline applies to references carried inside a request body: a supply-order line naming a flavor that does not exist fails with `ERR_FLAVOR_NOT_FOUND`, and a claim substantiation citing a certification that does not exist fails with `ERR_CERTIFICATION_NOT_FOUND`.

When a request could fail several checks at once, the server evaluates them in one fixed precedence ladder, and the earliest failing rung determines the error returned:

1. **Authentication** — headers present and role declared (`ERR_UNAUTHENTICATED`).
2. **Authorization** — role allowed on this endpoint (`ERR_UNAUTHORIZED`).
3. **Ownership** — a `ShopOperator` may only touch their own shop and its orders, and an audit may only be completed by the auditor who started it (`ERR_FORBIDDEN_OWNERSHIP`).
4. **Segregation of duties** — audit verification by the performing auditor fails with `ERR_SOD_AUDITOR_VERIFY`; a board decision cast by the campaign's proposer fails with `ERR_SOD_CAMPAIGN_PROPOSER`.
5. **Path existence** — left-to-right 404s as above.
6. **Body-reference existence** — 404s for identifiers inside the payload.
7. **Optimistic concurrency** — a stale `expected_supplier_version` or `expected_flavor_version` fails with `ERR_STALE_VERSION` (HTTP 412) before any state or business rule is consulted.
8. **State-machine legality** — the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409) or the named state-guard variant (`ERR_SUPPLIER_NOT_APPROVED`, `ERR_SHOP_NOT_OPERATING`, `ERR_FLAVOR_NOT_RETIRED`, `ERR_PAYMENT_NOT_FINAL`, `ERR_RETAIL_NOTICES_PENDING`, `ERR_FLAVOR_NOT_SCHEDULABLE`, `ERR_FLAVOR_NOT_PUBLISHABLE`).
9. **Business rules** — the domain-specific checks of §3, each endpoint applying its own ordered list as stated in its subsection (for example, claim publication checks coverage before certification status before scope, and order confirmation checks flavor availability before the credit limit).

Payload well-formedness — the missing-field, malformed-value, and enum-domain checks of §2.4 — is not a separate rung of this ladder; on every endpoint that takes a request body it is evaluated after path existence (rung 5) and before body-reference existence (rung 6).

### 2.7. Optimistic Concurrency Control

Two write operations mutate a parent resource indirectly — superseding one of its commitments, or replacing its claim state — so a client acting on a stale view of the parent could silently overwrite something it never saw. These two operations, and only these two, carry an optimistic-concurrency field:

- `POST /creamery/suppliers/{id}/commitments` requires `expected_supplier_version`, carrying the client's last observed `version` of the parent Supplier. Creating a commitment legitimately supersedes the prior `ACTIVE` commitment for the same ingredient category, so a stale view of the supplier would supersede a commitment the client never saw. If the value does not match the supplier's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- `POST /creamery/flavors/{id}/substantiate-claim` requires `expected_flavor_version`, carrying the client's last observed `version` of the Flavor. A new substantiation supersedes the flavor's current claim state, so a stale view would silently replace a claim the client never saw. A mismatch with the flavor's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field; optimistic concurrency applies nowhere else.

### 2.8. Numeric Precision, Rounding, and Money

All money in the platform is integer cents: `pint_price_cents`, `commodity_price_cents_per_liter`, `gross_amount_cents`, `total_cents`, `credit_limit_cents`, `franchise_fee_cents`, and `total_approved_cents` are whole numbers of cents, never fractional currency units.

Rounding behavior is pinned per calculation and is observable:

- Composite and blended scores (`composite_score`, `blended_score`) are integers produced with the round-half-up method.
- Claim coverage percentages (`claim_coverage_declared_pct`, `claim_coverage_verified_pct`) carry exactly two decimal places, rounded half-up.
- Premium amounts (`gross_amount_cents`) are integer cents rounded half-up from the exact arithmetic.
- Supply-order line amounts are rounded to integer cents, half-up, per line, and only then summed; rounding per line before summation is a pinned order that can differ from summing first and rounding once.
- Slot `capacity_units` are integers produced by rounding up (ceiling) after all multiplications, never before.

Threshold boundaries are inclusive wherever a rule is phrased as "at least": a blended score of exactly 60 earns the first premium tier, an audit composite of exactly 70 passes the score bar, verified coverage exactly equal to a claim threshold publishes, and exactly 500 signatures qualifies a revival request.

### 2.9. Mission Governance: Board Authority, the Parent Split, and Segregation of Duties

The governance model divides authority between the independent board and the parent company, and the API enforces that division rather than merely recording it. The `IndependentBoardMember` role alone holds social-mission authority: proposing and deciding activism campaigns, vetoing them even after the parent has scheduled or launched them, adopting or declining fan revival requests, and challenging flavor claims. The `ParentOpsController` role alone holds operational control: retiring flavors, scheduling campaign operations, dispatching retail-partner notices, launching campaigns, paying approved farm premiums, and advancing the logical clock. Neither role can perform the other's exclusive operations, and a role not listed for an operation is rejected with `ERR_UNAUTHORIZED`.

Two segregation-of-duties rules cut across individual competence:

- **Audit verification.** The `AuditVerifier` who verifies a completed audit must not be the auditor who performed it. If the verifier's `X-User-ID` equals the audit's `auditor_user_id`, the verification is rejected with `ERR_SOD_AUDITOR_VERIFY` (HTTP 403).
- **Campaign decision.** The board member who casts a campaign's board decision must not be the member who proposed it. If the decider's `X-User-ID` equals the campaign's `proposer_user_id`, the decision is rejected with `ERR_SOD_CAMPAIGN_PROPOSER` (HTTP 403).

### 2.10. Plant Capacity Pools and Reservation Semantics

Production capacity is tracked in two distinct pools, one per scheduling concern, and both are enforced against fixed per-plant constants:

- **The plant-shift capacity-unit pool** governs production slots. Each plant — `VT_WATERBURY`, `VT_ST_ALBANS`, or `NL_HELLENDOORN` — has a per-shift budget of capacity units: 1000 units at `VT_WATERBURY`, 800 at `VT_ST_ALBANS`, and 600 at `NL_HELLENDOORN`. Every planned or confirmed slot consumes units from the discrete bucket keyed by plant, production date, and shift; chunk-heavy and swirl-heavy formulations consume more units per pint (§3.4). When a slot is cancelled — directly or through the flavor-retirement cascade — its reserved `capacity_units` are released back into the bucket as a compensating reversal.
- **The plant-day pint pool** governs supply-order allocation. Each plant can supply at most 12000 pints per production date at `VT_WATERBURY`, 9000 at `VT_ST_ALBANS`, and 7000 at `NL_HELLENDOORN`. Allocating an order reserves its `total_pints` against the bucket keyed by plant and production date; cancelling an `ALLOCATED` order — including via the flavor-retirement cascade — releases those pints back.

Reservations are only ever taken and released by the transitions named in §3.4 and §3.8; there is no separate reservation API, and a released reservation is fully available to later requests.

## 3. Business Logic & Workflows

### 3.1. Supplier Onboarding, Sourcing Commitments, and Certifications

A `SourcingManager` registers a new supplier with its legal `name`, the ISO 3166-1 alpha-2 `country_code` of operation, and the primary `ingredient_category` it supplies — one of `DAIRY`, `COCOA`, `SUGAR`, `VANILLA`, `NUTS`, `FRUIT`, or `CHUNK_INCLUSION`. The supplier's `status` lands in `PROSPECT`, and its `social_criteria_score` stays null until the first verified audit writes it (§3.2); there is no manual path to approval. Everything hung beneath a supplier — its commitments, its certifications, and its audits — records the parent as `supplier_id`, taken from the create path rather than from the request body.

From `APPROVED`, a `SourcingManager` may suspend the supplier, moving it to `SUSPENDED`; manual suspension preserves the supplier's commitments and certifications untouched and bumps the supplier's `version`. A suspension is reversible two ways: a later passing audit reinstates the supplier automatically (§3.2), or the `SourcingManager` reinstates it manually from `SUSPENDED` to `APPROVED` — but manual reinstatement does not resurrect commitments that lapsed in the meantime. Termination is available from `PROSPECT`, `APPROVED`, or `SUSPENDED` and moves the supplier to the terminal `TERMINATED` state, bumping `version` each time; a terminated supplier's certifications can no longer be verified.

**Commitments.** Against an `APPROVED` supplier, the `SourcingManager` records a sourcing commitment naming the `ingredient_category` it covers, whether `fair_trade_required` contractually demands fair-trade certification, the `min_social_score` (a 0–100 minimum supplier social score the commitment demands), the `premium_over_commodity_pct` (a non-negative number) pledged for compliant volume, and the commitment window from `effective_from` (inclusive) to `effective_to` (exclusive for lapse evaluation). The window must be non-degenerate — `effective_to` strictly later than `effective_from` — or the create fails with `ERR_COMMITMENT_WINDOW_INVALID` (HTTP 422). Creating a commitment against a supplier that is not `APPROVED` fails with `ERR_SUPPLIER_NOT_APPROVED` (HTTP 409). The create also carries the OCC field `expected_supplier_version` described in §2.7, and the checks run in this order: supplier existence, then the stale-version check, then the approved-state check, then window validity.

A new commitment lands `ACTIVE` and supersedes whatever commitment was `ACTIVE` for the same supplier and category: the prior commitment moves to `SUPERSEDED`, so exactly one `ACTIVE` commitment exists per supplier-and-category pair, and the supplier's `version` bumps as part of the write. Commitments leave `ACTIVE` only two ways — superseded by a successor, or lapsed, either when the logical clock passes `effective_to` (§2.5) or through the audit-fail cascade (§3.2). `SUPERSEDED` and `LAPSED` are terminal.

**Certifications.** The `SourcingManager` registers a supplier's certificate with its `scheme` — `FAIR_TRADE`, `ORGANIC`, `NON_GMO`, `B_CORP`, or `RAINFOREST_ALLIANCE` — the external `certificate_number`, the `ingredient_scope` it covers (any of the seven ingredient categories, plus `PACKAGING` or `WHOLE_COMPANY`), a validity window from `issued_at` (inclusive) to `valid_until` (exclusive), and the supplier-declared `declared_coverage_pct` share (0–100) of scoped volume the certificate covers. Two window rules guard creation, evaluated in this order: first, the half-open window must not overlap another certification in `PENDING` or `VERIFIED` for the same supplier, scheme, and scope — overlap is rejected with `ERR_CERT_WINDOW_OVERLAP` (HTTP 409), while pure adjacency, where one certificate's `valid_until` equals the next one's `issued_at`, is allowed because the window end is exclusive; second, `valid_until` must be strictly later than `issued_at`, or the create fails with `ERR_CERT_WINDOW_INVALID` (HTTP 422).

A certification lands `PENDING` with `verified_coverage_pct` null. An `AuditVerifier` verifies a `PENDING` certification — provided the supplier is not `TERMINATED`, failing with `ERR_INVALID_STATE` (HTTP 409) otherwise — which records the verifier-confirmed `verified_coverage_pct` from the verification input and moves it to `VERIFIED`. An `AuditVerifier` may instead revoke a `PENDING` or `VERIFIED` certification, moving it to the terminal `REVOKED`; every flavor claim in `SUBSTANTIATED` or `PUBLISHED` that cites the revoked certification is challenged to `CHALLENGED` (§3.5). Clock-driven expiry (§2.5) moves `PENDING` or `VERIFIED` certifications to the terminal `EXPIRED` and retracts citing `PUBLISHED` claims.

### 3.2. The Supplier Social Audit: Scheduling, Fieldwork, and Verification

Audits are how a `PROSPECT` supplier earns approval and how an `APPROVED` supplier keeps it. A `SourcingManager` schedules an audit by naming `scheduled_for`, the planned audit date; the audit lands `SCHEDULED` with `auditor_user_id`, `labor_score`, `environment_score`, `community_score`, `findings_count`, `composite_score`, and `outcome` all null.

A `SustainabilityAuditor` starts a `SCHEDULED` audit — possible only while the supplier is not `TERMINATED`, failing with `ERR_INVALID_STATE` (HTTP 409) otherwise — which stamps `auditor_user_id` from the caller's `X-User-ID` and moves the audit to `IN_PROGRESS`. Completion belongs to that same auditor and no one else: completing requires the caller's `X-User-ID` to equal the audit's `auditor_user_id`, failing with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403) otherwise. At completion the auditor records three dimension scores — `labor_score`, `environment_score`, and `community_score`, each 0–100 — and the `findings_count` of non-conformance findings. The system then computes the audit's `composite_score` as the weighted sum of labor at 40 percent, environment at 30 percent, and community at 30 percent, rounded half-up to an integer, and derives the `outcome`: `PASS` when the composite is at least 70 and the findings count is at most 2 — both boundaries inclusive — and `FAIL` otherwise. The audit moves to `COMPLETED`.

Verification is the gate that makes an audit consequential, and it belongs to an `AuditVerifier` who is not the performing auditor (the segregation-of-duties rule of §2.9, failing with `ERR_SOD_AUDITOR_VERIFY`). Verification moves the audit from `COMPLETED` to its terminal `VERIFIED` state and always writes the audit's `composite_score` onto the supplier as `social_criteria_score`. What happens next depends on the outcome:

- On a `PASS`, a `PROSPECT` or `SUSPENDED` supplier transitions to `APPROVED` — this is both the only path to initial approval and the automatic reinstatement of a suspended supplier — and the supplier's `version` bumps.
- On a `FAIL`, a `PROSPECT` or `APPROVED` supplier cascades to `SUSPENDED` in a depth-3 cascade: every certification of the supplier in `PENDING` or `VERIFIED` is revoked to `REVOKED`; every flavor claim in `SUBSTANTIATED` or `PUBLISHED` citing any of those certifications is challenged to `CHALLENGED`; every `ACTIVE` sourcing commitment of the supplier lapses to `LAPSED`; and the supplier's `version` bumps. The cascade is the same one a manual certification revocation triggers for claims, applied supplier-wide.

Verification is defined whatever lifecycle state the supplier is in at that moment — there is no supplier-state guard on verifying a completed audit, so even a `TERMINATED` supplier's audit can be verified. The `composite_score` write is unconditional. A `PASS` moves only a `PROSPECT` or `SUSPENDED` supplier: an `APPROVED` supplier stays `APPROVED` and a `TERMINATED` supplier stays `TERMINATED`. A `FAIL` runs the depth-3 cascade even for a `SUSPENDED` or `TERMINATED` supplier, but only a `PROSPECT`, `APPROVED`, or `SUSPENDED` supplier's status moves — a `TERMINATED` supplier's status is left unchanged.

### 3.3. The Dairy Farm Program and Premium Payments

The dairy program pays farms above the commodity price for verified practice. A `DairyProgramManager` enrolls a farm with its `farm_name`, `region`, `herd_size`, the `season_year` of the program season, and `baseline_volume_liters` — the farm's annual baseline in liters, above which volume earns a marginal excess bonus. The enrollment lands `ENROLLED`, with `env_practice_score`, `welfare_practice_score`, and `blended_score` null and `total_approved_cents` at 0.

Assessment converts an enrollment into a paying participant. The `DairyProgramManager` records an `env_practice_score` and a `welfare_practice_score`, each 0–100, and the system computes `blended_score` as the round-half-up integer of the equal-weighted average — half environmental, half welfare. Assessment moves the enrollment from `ENROLLED` to `ASSESSED`; re-assessment from `ASSESSED` is allowed, re-sets both practice scores and the blended score, and deliberately does not recompute payments that already exist. `ASSESSED` is the last word of the enrollment lifecycle — the machine has no terminal state.

**Creating a payment.** Against an `ASSESSED` enrollment (any other state is rejected with `ERR_INVALID_STATE`, HTTP 409), the `DairyProgramManager` opens a premium payment naming the `period` — one of `Q1`, `Q2`, `Q3`, `Q4` — the farm's `declared_volume_liters` for the period, and the `commodity_price_cents_per_liter` baseline. The payment's `enrollment_id` is taken from the path, not the payload. The payment lands `CALCULATED` in the `PROVISIONAL` `calc_variant`, with `metered_volume_liters` null, `non_conformance_count` at 0, and `premium_pct` and `gross_amount_cents` computed immediately.

**The premium formula** has two variants that share one shape. The tier percentage comes from the enrollment's `blended_score`: below 60 the tier is 0 percent; at least 60 but below 75 it is 5 percent; at least 75 but below 90 it is 8 percent; at least 90 it is 12 percent — every lower bound inclusive. The effective premium percentage is the tier minus a deduction of 2 percentage points per non-conformance, floored at zero so deductions can never turn the premium negative; `premium_pct` records that effective percentage. When the tier is 0 percent the farm is below the program bar: no premium and no excess bonus, so `gross_amount_cents` is 0 regardless of volume. Otherwise the volume splits at the baseline: the base volume is the smaller of the period volume and `baseline_volume_liters`, and the excess volume is whatever the period volume exceeds the baseline by (zero when it does not). The gross is the round-half-up integer-cent value of the base volume times the commodity price times the effective percentage, plus the excess volume times the commodity price times the effective percentage plus one percentage point — the marginal excess bonus.

The variants differ only in which volume and deductions feed the formula. `PROVISIONAL`, computed at creation, uses `declared_volume_liters` and zero non-conformance deductions. `FINAL` is produced by finalization: the `DairyProgramManager` supplies `metered_volume_liters` and `non_conformance_count`, the payment's `calc_variant` flips from `PROVISIONAL` to `FINAL` — a self-loop that keeps the payment in `CALCULATED` — and `premium_pct` and `gross_amount_cents` recompute with the metered volume and the actual deductions. The recomputation reads the enrollment's `blended_score` and `baseline_volume_liters` as they stand at finalization time, not as they were when the payment was created. Finalize is defined only for a `PROVISIONAL` payment.

**Settlement.** Approval moves a payment from `CALCULATED` to `APPROVED`, but only once its `calc_variant` is `FINAL`; approving a still-`PROVISIONAL` payment fails with `ERR_PAYMENT_NOT_FINAL` (HTTP 409). Approval adds the payment's `gross_amount_cents` to the enrollment's `total_approved_cents` — the running sum of gross amounts over payments in `APPROVED` or `PAID` — and bumps the enrollment's `version` through the cascade. Disbursement is parent-company business: a `ParentOpsController` pays an `APPROVED` payment, moving it to the terminal `PAID`. A `DairyProgramManager` may void a payment in `CALCULATED` or `APPROVED`, moving it to the terminal `VOIDED`; voiding a `CALCULATED` payment has no financial effect, while voiding an `APPROVED` one subtracts its `gross_amount_cents` back out of `total_approved_cents` as a compensating reversal. A payment that has reached `PAID` can no longer be voided.

### 3.4. Flavor Lifecycle and Plant Production Scheduling

A `FlavorManager` creates a flavor with its `name`, `base_type` (`DAIRY` or `NON_DAIRY`), the formulation loads `chunk_load_pct` and `swirl_load_pct` (each 0–100), and the `pint_price_cents` unit price. The flavor's `status` lands in `DEVELOPMENT`; its claim side starts clean — `claim_type` `NONE`, `claim_status` `UNCLAIMED`, an empty `claim_certification_ids` list, null coverage percentages, and `retired_at` null.

Promotion walks the lifecycle one step at a time, each step naming a `target_state`: `DEVELOPMENT` to `TEST_BATCH`, `TEST_BATCH` to `LIMITED_RUN` (the limited-batch introduction), and `LIMITED_RUN` to `CORE_LINE`. Every promotion bumps the flavor's `version`; no other promotion pairs exist. The `target_state` field is an enum over exactly those three targets — `TEST_BATCH`, `LIMITED_RUN`, and `CORE_LINE`: any other value fails with `ERR_INVALID_ENUM` (HTTP 400), and a declared target that is not the next step from the flavor's current state fails with `ERR_INVALID_STATE` (HTTP 409).

Retirement is operational control, reserved to the `ParentOpsController`, and is available from `LIMITED_RUN`, `CORE_LINE`, or `REVIVED`. Retiring a flavor stamps `retired_at` from the logical clock — the revival window of §3.6 measures from this instant — and then cascades: every supply order in `PLACED`, `CONFIRMED`, or `ALLOCATED` whose `lines` contain the flavor is cancelled to `CANCELLED`, with an `ALLOCATED` order's reserved pints released from its plant-day pool; every production slot of the flavor in `PLANNED` or `CONFIRMED` is cancelled to `CANCELLED`, releasing its reserved `capacity_units`; a claim in `PUBLISHED` is retracted to `RETRACTED`; and the flavor's `version` bumps. A retired flavor is not dead — §3.6 lets fans bring it back — and a `REVIVED` flavor returns to `CORE_LINE` when the `FlavorManager` returns it to the line, closing the cycle `CORE_LINE` to `RETIRED` to `REVIVED` to `CORE_LINE`; that return also bumps `version`.

**Production slots.** A `PlantScheduler` schedules a run by naming the `plant_code` (`VT_WATERBURY`, `VT_ST_ALBANS`, or `NL_HELLENDOORN`), the `flavor_id` being scheduled, the `production_date` as an ISO `yyyy-mm-dd` date, the `shift` (`DAY` or `NIGHT`), and the `planned_pints` count, a positive integer. The date may not be before the current logical date, failing with `ERR_SLOT_DATE_PAST` (HTTP 422). Creation applies the date check first and the capacity check second. The slot lands `PLANNED` with its `capacity_units` computed at creation: the planned pints are divided by 100, the result is multiplied by a chunk factor of 1.5 when the flavor's `chunk_load_pct` is at least 20 (1.0 otherwise) and by a swirl factor of 1.25 when the flavor's `swirl_load_pct` is at least 15 (1.0 otherwise) — the factors multiply, so a formulation heavy in both consumes 1.875 units per hundred pints — and the product is rounded up to a whole number of units.

Both slot creation and confirmation enforce the plant-shift pool of §2.10: the sum of `capacity_units` over slots in `PLANNED` or `CONFIRMED` in the same plant-date-shift bucket, plus the new slot's units, must stay within the plant's budget, failing with `ERR_PLANT_CAPACITY_EXCEEDED` (HTTP 422). Confirming a slot additionally requires the flavor's lifecycle to be schedulable — `TEST_BATCH`, `LIMITED_RUN`, or `CORE_LINE` — failing with `ERR_FLAVOR_NOT_SCHEDULABLE` (HTTP 409); confirmation re-runs the same capacity check before moving the slot from `PLANNED` to `CONFIRMED`. A `PlantScheduler` may cancel a slot in `PLANNED` or `CONFIRMED`, releasing its reserved units; the retirement cascade does the same. A `CONFIRMED` slot completes automatically once the logical clock's date passes its `production_date` (§2.5). `COMPLETED` and `CANCELLED` are terminal.

### 3.5. Sourcing Claims: Substantiation, Publication, and Challenge

Every flavor carries a claim dimension — `claim_status` — that runs in parallel to its lifecycle `status` and moves independently of it: `UNCLAIMED`, `SUBSTANTIATED`, `PUBLISHED`, `CHALLENGED`, and `RETRACTED`. A claim asserts one `claim_type` — `FAIR_TRADE_SOURCING`, `ORGANIC_INGREDIENTS`, `NON_GMO`, or `CLIMATE_POSITIVE` (with `NONE` meaning no claim) — and must be able to prove itself against certifications.

A `FlavorManager` substantiates a claim by naming the `claim_type` and the `certification_ids` it cites, together with the OCC field `expected_flavor_version` of §2.7. Any declared `claim_type` value is accepted at substantiation, including `NONE`, and `certification_ids` must be a non-empty array of identifiers. Substantiation is defined from `UNCLAIMED`, from `CHALLENGED`, and from `RETRACTED`, and in each case it supersedes whatever claim state the flavor currently holds. Every cited certification identifier must exist, failing with `ERR_CERTIFICATION_NOT_FOUND` (HTTP 404); the staleness check on `expected_flavor_version` runs before any state evaluation, failing with `ERR_STALE_VERSION` (HTTP 412). On success the write sets `claim_type` and `claim_certification_ids`, computes both coverage bases, moves `claim_status` to `SUBSTANTIATED`, and bumps the flavor's `version`:

- `claim_coverage_declared_pct` is the supplier-reported basis — the mean of `declared_coverage_pct` over all cited certifications regardless of their status — rounded half-up to two decimal places. It is informational only.
- `claim_coverage_verified_pct` is the verification basis — the mean of `verified_coverage_pct` over the cited certifications whose status is `VERIFIED`, and 0 when none of the cited certifications is verified — rounded half-up to two decimal places. This is the only basis the publish gate accepts.

Publication turns a `SUBSTANTIATED` claim into a public one and applies four gates, evaluated in this order. First, the flavor's lifecycle `status` must be `LIMITED_RUN` or `CORE_LINE`, failing with `ERR_FLAVOR_NOT_PUBLISHABLE` (HTTP 409). Second, `claim_coverage_verified_pct` must meet the threshold for the claim's type — 95 for `FAIR_TRADE_SOURCING`, 100 for `ORGANIC_INGREDIENTS`, 90 for `NON_GMO`, and 100 for `CLIMATE_POSITIVE` — with the boundary inclusive, so coverage exactly equal to the threshold passes; falling short fails with `ERR_CLAIM_COVERAGE_INSUFFICIENT` (HTTP 422). No threshold is defined for a `NONE` claim type, so publishing a `NONE` claim always fails this gate. Third, every cited certification must be in `VERIFIED` status, failing with `ERR_CERT_NOT_VERIFIED` (HTTP 422). Fourth, the cited certifications must satisfy the base-type scope rule: for a `DAIRY` flavor, at least one cited certification must carry an `ingredient_scope` of `DAIRY` or `WHOLE_COMPANY`; for a `NON_DAIRY` flavor, at least one cited certification must carry a scope other than `DAIRY` — and `WHOLE_COMPANY` qualifies here as well. A scope failure is rejected with `ERR_CERT_SCOPE_MISMATCH` (HTTP 422). Passing all four moves `claim_status` to `PUBLISHED` and bumps the flavor's `version`.

The board polices mission claims: an `IndependentBoardMember` may challenge a claim in `SUBSTANTIATED` or `PUBLISHED`, moving it to `CHALLENGED` and bumping the flavor's `version`. Challenges also arrive by cascade — revoking a cited certification (manually or through the audit-fail cascade of §3.2) challenges every citing claim in `SUBSTANTIATED` or `PUBLISHED`. Retraction is the system's own move, never a direct action: a claim in `PUBLISHED` retracts to `RETRACTED` when the flavor retires (§3.4) or when a cited certification expires under the logical clock (§2.5). From `CHALLENGED` or `RETRACTED`, the only way back is a fresh substantiation, which supersedes the old claim entirely.

### 3.6. Fan-Driven Flavor Revival

Retirement is not necessarily the end of a flavor. A `Fan` opens a revival request against a flavor with their `fan_email` and a campaign `title`, but only inside the revival window, with the two gates checked in order: first the flavor's `status` must be `RETIRED`, failing with `ERR_FLAVOR_NOT_RETIRED` (HTTP 409), and then the current logical time must be no later than `retired_at` plus 730 days — two full years — failing with `ERR_REVIVAL_WINDOW_EXPIRED` (HTTP 422). The request lands `OPEN` with `signature_count` at 0, an empty `signer_emails` list, and `qualified_at` null.

Signing is how a request earns consideration. A `Fan` signs an `OPEN` request with their `fan_email` and an optional `count` of signatures being contributed — `count` defaults to 1 when omitted and must be a positive integer when present; the request enforces one signature per email per request, and a repeat signature from the same `fan_email` is rejected with `ERR_DUPLICATE_SIGNATURE` (HTTP 409). Each accepted signature adds its `count` to `signature_count`. The moment the running total reaches at least 500 — the threshold is inclusive, so exactly 500 qualifies while 499 does not — the system moves the request from `OPEN` to `QUALIFIED` and stamps `qualified_at` from the logical clock.

Adoption is a social-mission decision reserved to the independent board. An `IndependentBoardMember` adopts a `QUALIFIED` request, moving it to the terminal `ADOPTED` and transitioning the flavor itself from `RETIRED` to `REVIVED`, bumping the flavor's `version`. If the flavor is no longer `RETIRED` when the adoption lands — for example because another qualified request for the same flavor was adopted first — the adoption still stands: the request moves to `ADOPTED` and the flavor is left unchanged. The board may instead decline a request in `OPEN` or `QUALIFIED`, moving it to the terminal `DECLINED` with no effect on the flavor. From `REVIVED`, the `FlavorManager` can return the flavor to `CORE_LINE` (§3.4), or the parent can retire it again — which restarts the revival clock from the new `retired_at`.

### 3.7. Activism Campaigns under Dual Governance

Campaigns are where the board-parent split of §2.9 becomes a workflow. An `IndependentBoardMember` proposes a campaign with a `title`, an `issue_area` — `CLIMATE`, `RACIAL_JUSTICE`, `FAIR_TRADE`, `DEMOCRACY`, or `LGBTQ_RIGHTS` — and the expected `retail_partner_impact` of `NONE`, `LOW`, or `HIGH`. The server records the proposer's `X-User-ID` as `proposer_user_id`, lands the campaign's `approval_status` in `BOARD_REVIEW`, and sets the parallel `retail_notice_status` dimension: `NOT_REQUIRED` when the impact is `NONE`, `PENDING` otherwise.

The board decision belongs to a different board member than the proposer — the segregation-of-duties rule of §2.9, failing with `ERR_SOD_CAMPAIGN_PROPOSER` (HTTP 403). The decision carries an `approve` flag: approving moves the campaign from `BOARD_REVIEW` to `BOARD_APPROVED`, rejecting moves it to the terminal `BOARD_REJECTED`, and either way the decider's `X-User-ID` is recorded as `decided_by_user_id`.

From `BOARD_APPROVED`, operational control passes to the parent. A `ParentOpsController` schedules operations, moving the campaign to `OPS_SCHEDULED`; dispatches retail-partner notices — defined for a campaign in `BOARD_APPROVED` or `OPS_SCHEDULED` — moving `retail_notice_status` from `PENDING` to `DISPATCHED`; and launches an `OPS_SCHEDULED` campaign, moving it to `LAUNCHED`. Launch is gated on partner communication: launching while `retail_notice_status` is still `PENDING` fails with `ERR_RETAIL_NOTICES_PENDING` (HTTP 409), so a campaign whose impact is `NONE` (notices `NOT_REQUIRED`) launches freely, while any `LOW` or `HIGH` impact campaign must have its notices dispatched first.

The board's authority does not end at approval. An `IndependentBoardMember` may veto a campaign in `BOARD_APPROVED`, `OPS_SCHEDULED`, or `LAUNCHED`, withdrawing it to the terminal `WITHDRAWN` — the independent board's veto overrides the parent company's operational scheduling even after launch. `BOARD_REJECTED` and `WITHDRAWN` are the terminal states; nothing leaves them.

### 3.8. Scoop Shops and Product Supply

The scoop-shop program sells the product through two operator models. A `FranchiseAdmin` registers a shop application with its `name`, `operator_type` — `FRANCHISEE` or `NONPROFIT_PARTNER` — an optional `nonprofit_verified` flag defaulting to false, the `city` and `country_code`, and a `credit_limit_cents` capping the shop's confirmed-but-unpaid order exposure. The franchise fee is computed by the server into `franchise_fee_cents`: 3,500,000 cents for a `FRANCHISEE`, and 0 for a `NONPROFIT_PARTNER`, whose partner-shop fee is waived. The application lands in `SITE_REVIEW`.

Site adjudication belongs to the `FranchiseAdmin`: approving moves the shop from `SITE_REVIEW` to `SITE_APPROVED`; rejecting moves it straight to the terminal `CLOSED`. Opening a `SITE_APPROVED` shop moves it to `OPERATING`, but the partner model must be proven first — opening requires either a `FRANCHISEE` operator type or a verified nonprofit flag, failing with `ERR_NONPROFIT_VERIFICATION_REQUIRED` (HTTP 422) for an unverified `NONPROFIT_PARTNER`. An operating shop cycles between `OPERATING` and `SUSPENDED` under the `FranchiseAdmin`'s suspend and reopen actions.

**Supply orders.** A `ShopOperator` places an order for their own shop — the caller's `X-User-ID` must equal the scoop-shop identifier in the path, failing with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403) — naming the `production_date` the product is produced for and the `lines`, a non-empty array of entries each pairing a `flavor_id` with a `quantity_pints` given as a positive integer. Every referenced flavor must exist, failing with `ERR_FLAVOR_NOT_FOUND` (HTTP 404). The server prices the order once, at creation: for each line it multiplies the flavor's current `pint_price_cents` by the line's `quantity_pints` and, for a `NONPROFIT_PARTNER` shop only, applies the 15 percent partner discount (franchisees receive no discount), rounding each line's amount to integer cents half-up; the order's `total_cents` is the sum of those rounded line amounts — per-line rounding pinned before summation — and `total_pints` is the sum of the line quantities. The order lands `PLACED`.

Confirmation is the `FranchiseAdmin`'s credit-and-availability gate and applies three checks in order. First, the shop must be `OPERATING`, failing with `ERR_SHOP_NOT_OPERATING` (HTTP 409). Second, every line's flavor must be orderable — in `LIMITED_RUN` or `CORE_LINE` — failing with `ERR_ORDER_FLAVOR_UNAVAILABLE` (HTTP 422). Third, the order's `total_cents` must fit within the shop's `credit_limit_cents`, with equality allowed, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422). Passing moves the order from `PLACED` to `CONFIRMED`.

Allocation is plant logistics. A `PlantScheduler` allocates a `CONFIRMED` order by naming a `plant_code`; the server checks the plant-day pint pool of §2.10 — the pints already reserved for that plant and `production_date` plus the order's `total_pints` must stay within the plant's daily budget, failing with `ERR_ORDER_CAPACITY_EXCEEDED` (HTTP 422) — then stamps `allocated_plant_code`, reserves the pints, and moves the order to `ALLOCATED`. Delivery closes the loop: the shop's own `ShopOperator` marks an `ALLOCATED` order delivered, moving it to the terminal `DELIVERED` — again an ownership-checked action against the order's `scoop_shop_id`.

Cancellation belongs to the shop's own `ShopOperator` and is defined from `PLACED`, `CONFIRMED`, and `ALLOCATED`; cancelling an `ALLOCATED` order releases its `total_pints` from the plant-day pool as a compensating reversal. The retirement cascade of §3.4 cancels open orders containing the retired flavor on the same terms, releasing allocated pints. `DELIVERED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource — registering a supplier, commitment, certification, audit, enrollment, premium payment, flavor, revival request, production slot, campaign, scoop shop, or supply order — return `201 Created`. Operations that modify an existing resource in place — every state transition, verification, decision, and the clock advance — return `200 OK`. Request payloads, response fields, preconditions, and side effects are specified in §2 and §3; this table is only the HTTP contract and the role authorization matrix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/creamery/_clock/set_current_utc` | Advance the logical clock; evaluates certification expiry, commitment lapse, and slot completion | ParentOpsController |
| POST | `/creamery/suppliers` | Register a supplier (lands `PROSPECT`) | SourcingManager |
| GET | `/creamery/suppliers/{id}` | Read one supplier | SourcingManager, SustainabilityAuditor, AuditVerifier, DairyProgramManager, FlavorManager, IndependentBoardMember, ParentOpsController, FranchiseAdmin |
| POST | `/creamery/suppliers/{id}/suspend` | Manually suspend an `APPROVED` supplier, preserving commitments and certifications | SourcingManager |
| POST | `/creamery/suppliers/{id}/reinstate` | Reinstate a `SUSPENDED` supplier to `APPROVED`; lapsed commitments stay lapsed | SourcingManager |
| POST | `/creamery/suppliers/{id}/terminate` | Terminate a supplier (terminal) | SourcingManager |
| POST | `/creamery/suppliers/{id}/commitments` | Create a sourcing commitment; supersedes the prior `ACTIVE` commitment for the same category; requires `expected_supplier_version` | SourcingManager |
| GET | `/creamery/suppliers/{id}/commitments` | List a supplier's commitments; optional `status` filter | SourcingManager, ParentOpsController |
| POST | `/creamery/suppliers/{id}/certifications` | Register a certification (lands `PENDING`); half-open window overlap rejected | SourcingManager |
| GET | `/creamery/suppliers/{id}/certifications` | List a supplier's certifications; optional `status` filter | SourcingManager, AuditVerifier, FlavorManager |
| POST | `/creamery/certifications/{id}/verify` | Verify a `PENDING` certification; sets `verified_coverage_pct` | AuditVerifier |
| POST | `/creamery/certifications/{id}/revoke` | Revoke a certification; citing claims are challenged | AuditVerifier |
| POST | `/creamery/suppliers/{id}/audits` | Schedule an audit of a supplier | SourcingManager |
| GET | `/creamery/suppliers/{id}/audits` | List a supplier's audits | SourcingManager, SustainabilityAuditor, AuditVerifier |
| POST | `/creamery/audits/{id}/start` | Start a `SCHEDULED` audit; records `auditor_user_id` | SustainabilityAuditor |
| POST | `/creamery/audits/{id}/complete` | Complete an `IN_PROGRESS` audit with dimension scores; only the starting auditor may complete; computes composite and outcome | SustainabilityAuditor |
| POST | `/creamery/audits/{id}/verify` | Verify a `COMPLETED` audit (verifier must differ from auditor); `PASS` approves the supplier, `FAIL` triggers the audit-fail cascade | AuditVerifier |
| POST | `/creamery/enrollments` | Enroll a dairy farm in the farm program (lands `ENROLLED`) | DairyProgramManager |
| GET | `/creamery/enrollments/{id}` | Read one enrollment | DairyProgramManager, ParentOpsController |
| POST | `/creamery/enrollments/{id}/assess` | Record practice scores and compute `blended_score`; allowed from `ENROLLED` and `ASSESSED` | DairyProgramManager |
| POST | `/creamery/enrollments/{id}/premium-payments` | Create a premium payment (`CALCULATED`, `PROVISIONAL` variant); enrollment must be `ASSESSED` | DairyProgramManager |
| GET | `/creamery/enrollments/{id}/premium-payments` | List an enrollment's premium payments | DairyProgramManager, ParentOpsController |
| GET | `/creamery/premium-payments/{id}` | Read one premium payment | DairyProgramManager, ParentOpsController |
| POST | `/creamery/premium-payments/{id}/finalize` | Finalize a `PROVISIONAL` payment with metered volume and non-conformance count; recomputes the `FINAL` variant | DairyProgramManager |
| POST | `/creamery/premium-payments/{id}/approve` | Approve a `FINAL` payment; adds the gross amount to the enrollment's approved total | DairyProgramManager |
| POST | `/creamery/premium-payments/{id}/pay` | Pay an `APPROVED` payment (parent-company operational control) | ParentOpsController |
| POST | `/creamery/premium-payments/{id}/void` | Void a `CALCULATED` or `APPROVED` payment; voiding an approved payment reverses the enrollment total | DairyProgramManager |
| POST | `/creamery/flavors` | Create a flavor (`DEVELOPMENT`, claim `UNCLAIMED`) | FlavorManager |
| GET | `/creamery/flavors/{id}` | Read one flavor | FlavorManager, PlantScheduler, ParentOpsController, IndependentBoardMember, FranchiseAdmin, ShopOperator, Fan, SourcingManager |
| POST | `/creamery/flavors/{id}/promote` | Advance the lifecycle with `target_state`: `DEVELOPMENT` → `TEST_BATCH` → `LIMITED_RUN` → `CORE_LINE` | FlavorManager |
| POST | `/creamery/flavors/{id}/retire` | Retire a flavor from `LIMITED_RUN`, `CORE_LINE`, or `REVIVED`; cascades to orders, slots, and claims | ParentOpsController |
| POST | `/creamery/flavors/{id}/return-to-line` | Return a `REVIVED` flavor to `CORE_LINE` | FlavorManager |
| POST | `/creamery/flavors/{id}/substantiate-claim` | Substantiate a claim against cited certifications; supersedes the current claim state; requires `expected_flavor_version` | FlavorManager |
| POST | `/creamery/flavors/{id}/publish-claim` | Publish a `SUBSTANTIATED` claim; gated by flavor status, verified coverage threshold, certification status, and scope | FlavorManager |
| POST | `/creamery/flavors/{id}/challenge-claim` | The independent board challenges a `SUBSTANTIATED` or `PUBLISHED` claim | IndependentBoardMember |
| POST | `/creamery/flavors/{id}/revival-requests` | Open a fan revival request for a `RETIRED` flavor within the revival window | Fan |
| GET | `/creamery/flavors/{id}/revival-requests` | List a flavor's revival requests; optional `status` filter | Fan, FlavorManager, IndependentBoardMember |
| POST | `/creamery/revival-requests/{id}/sign` | Sign an `OPEN` revival request (one signature per email); reaching 500 auto-qualifies | Fan |
| POST | `/creamery/revival-requests/{id}/adopt` | The board adopts a `QUALIFIED` request; the flavor goes `RETIRED` → `REVIVED` | IndependentBoardMember |
| POST | `/creamery/revival-requests/{id}/decline` | The board declines an `OPEN` or `QUALIFIED` request | IndependentBoardMember |
| POST | `/creamery/production-slots` | Schedule a production run; chunk- and swirl-heavy formulations consume extra capacity units; plant-shift pool checked | PlantScheduler |
| GET | `/creamery/production-slots` | List production slots; optional `flavor_id`, `plant_code`, `production_date`, `status` filters | PlantScheduler, FlavorManager |
| GET | `/creamery/production-slots/{id}` | Read one production slot | PlantScheduler, FlavorManager |
| POST | `/creamery/production-slots/{id}/confirm` | Confirm a `PLANNED` slot; flavor must be schedulable; capacity re-checked | PlantScheduler |
| POST | `/creamery/production-slots/{id}/cancel` | Cancel a `PLANNED` or `CONFIRMED` slot; releases its capacity units | PlantScheduler |
| POST | `/creamery/campaigns` | Propose an activism campaign (lands in `BOARD_REVIEW`); `proposer_user_id` recorded from the caller | IndependentBoardMember |
| GET | `/creamery/campaigns/{id}` | Read one campaign | IndependentBoardMember, ParentOpsController, FlavorManager |
| POST | `/creamery/campaigns/{id}/board-decision` | Board approve or reject; the decider must differ from the proposer | IndependentBoardMember |
| POST | `/creamery/campaigns/{id}/schedule-ops` | The parent company schedules operations for a `BOARD_APPROVED` campaign | ParentOpsController |
| POST | `/creamery/campaigns/{id}/dispatch-retail-notices` | Dispatch retail-partner notices (`PENDING` → `DISPATCHED`) once board-approved | ParentOpsController |
| POST | `/creamery/campaigns/{id}/launch` | Launch an `OPS_SCHEDULED` campaign; requires notices dispatched when impact is not `NONE` | ParentOpsController |
| POST | `/creamery/campaigns/{id}/veto` | An independent-board veto withdraws a campaign from `BOARD_APPROVED`, `OPS_SCHEDULED`, or `LAUNCHED` | IndependentBoardMember |
| POST | `/creamery/scoop-shops` | Register a franchise or partner scoop-shop application (`SITE_REVIEW`); computes `franchise_fee_cents` | FranchiseAdmin |
| GET | `/creamery/scoop-shops/{id}` | Read one scoop shop | FranchiseAdmin, ShopOperator, ParentOpsController |
| POST | `/creamery/scoop-shops/{id}/approve-site` | Approve the site (`SITE_REVIEW` → `SITE_APPROVED`) | FranchiseAdmin |
| POST | `/creamery/scoop-shops/{id}/reject-site` | Reject the site (`SITE_REVIEW` → `CLOSED`) | FranchiseAdmin |
| POST | `/creamery/scoop-shops/{id}/open` | Open a `SITE_APPROVED` shop; partner shops require verified nonprofit status | FranchiseAdmin |
| POST | `/creamery/scoop-shops/{id}/suspend` | Suspend an `OPERATING` shop | FranchiseAdmin |
| POST | `/creamery/scoop-shops/{id}/reopen` | Reopen a `SUSPENDED` shop | FranchiseAdmin |
| POST | `/creamery/scoop-shops/{id}/supply-orders` | Place a supply order for the caller's own shop (lands `PLACED`); totals computed at creation | ShopOperator |
| GET | `/creamery/scoop-shops/{id}/supply-orders` | List a shop's supply orders; optional `status` filter | FranchiseAdmin, ShopOperator |
| GET | `/creamery/supply-orders/{id}` | Read one supply order | FranchiseAdmin, ShopOperator, PlantScheduler |
| POST | `/creamery/supply-orders/{id}/confirm` | Confirm a `PLACED` order; requires the shop `OPERATING`, all flavors orderable, and the total within the credit limit | FranchiseAdmin |
| POST | `/creamery/supply-orders/{id}/allocate` | Allocate a `CONFIRMED` order to a plant-day pint pool | PlantScheduler |
| POST | `/creamery/supply-orders/{id}/deliver` | Mark an `ALLOCATED` order delivered (own shop) | ShopOperator |
| POST | `/creamery/supply-orders/{id}/cancel` | Cancel a `PLACED`, `CONFIRMED`, or `ALLOCATED` order (own shop); releases reserved capacity | ShopOperator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_SOD_AUDITOR_VERIFY` | 403 Forbidden |
| `ERR_SOD_CAMPAIGN_PROPOSER` | 403 Forbidden |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_FLAVOR_NOT_FOUND` | 404 Not Found |
| `ERR_REVIVAL_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_SHOP_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SUPPLIER_NOT_APPROVED` | 409 Conflict |
| `ERR_CERT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CERT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_COMMITMENT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_PLANT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ORDER_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SLOT_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SIGNATURE` | 409 Conflict |
| `ERR_REVIVAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_FLAVOR_NOT_RETIRED` | 409 Conflict |
| `ERR_FLAVOR_NOT_SCHEDULABLE` | 409 Conflict |
| `ERR_FLAVOR_NOT_PUBLISHABLE` | 409 Conflict |
| `ERR_PAYMENT_NOT_FINAL` | 409 Conflict |
| `ERR_CLAIM_COVERAGE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CERT_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_CERT_SCOPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ORDER_FLAVOR_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_SHOP_NOT_OPERATING` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RETAIL_NOTICES_PENDING` | 409 Conflict |
| `ERR_NONPROFIT_VERIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
