# Crayon Works API — Product Requirements Document

## 1. Introduction

Crayon Works is the operating platform for a crayon manufacturer whose business spans far more than molding wax. Pigments arrive from suppliers under strict child-product safety classifications and must clear quarantine and certification before a single batch reaches the molding floor. Color scientists draft formulas, safety officers approve them only after laboratory testing, and every licensed or co-branded product line passes through a two-party negotiation between the brand side and the external licensor before it may be produced. Because the product is intended for children, the platform carries recall readiness as a first-class concern: the retroactive rejection of a previously certified pigment batch must cascade through production runs, warehouse lots, retail commitments, and licensed lines in a single, auditable motion.

Two commercial rhythms shape the catalog. Colors are introduced and retired through public consumer voting campaigns whose ballots are weighted by voter segment, and an archived color library preserves the brand's heritage once a retired shade ages out of the active line. Demand concentrates heavily in the back-to-school season, so retail allocations are managed as a forward-looking waterfall that prices requests against both physical inventory and projected in-season production, with optimistic concurrency protecting the shared pool. Alongside the factory, a destination experience attraction sells timed sessions — including school-group buyouts — with dynamic ticket pricing, strict capacity accounting, and an ordered waitlist.

This document is the complete and sole functional specification for the API. It defines the resource model, the state machines that govern every lifecycle, the calculations behind voting, pricing, packing accuracy, allocation, royalties, and recall severity, the validation pipeline every request traverses, and the endpoint and error catalogues. All resources are mounted under the `/crayon-works` prefix, with the single exception of the logical-clock capability described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly to every endpoint: authentication and roles, the response envelope, pagination, the logical clock, common resource properties, numeric precision, optimistic concurrency, the validation pipeline, and segregation of duties.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. A request missing either header, or presenting a role value the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the same error is raised when a licensor-side action is attempted by an `X-User-ID` that does not equal the licensed line's `licensor_user_id`.

The system recognizes eleven roles, spelled exactly as follows:

- `PlatformAdmin` — factory operations administrator: catalog, specs, sessions, production runs, epoch and clock.
- `SourcingManager` — pigment sourcing desk: registers pigment batches.
- `QualityAssurance` — quality assurance officer: registers batches and decides certification; may never certify a batch it registered.
- `Formulator` — color scientist: creates formulas and submits them for approval.
- `SafetyOfficer` — product safety authority: approves, rejects, or requests revision on formulas; may never decide a formula it submitted.
- `LabTechnician` — wet-lab technician: records safety test outcomes.
- `BrandManager` — brand partnerships manager: owns licensed lines on the brand side; may never brand-approve a line it submitted.
- `Licensor` — external licensor approver; its `X-User-ID` must equal the line's `licensor_user_id`.
- `AllocationPlanner` — retail allocation planner for the seasonal back-to-school window.
- `BoxOffice` — attraction box office: sells tickets, checks in visitors, processes refunds and cancellations.
- `Consumer` — the public voter; may only cast ballots.

**Identity semantics.** For every one of the eleven roles — `PlatformAdmin`, `SourcingManager`, `QualityAssurance`, `Formulator`, `SafetyOfficer`, `LabTechnician`, `BrandManager`, `Licensor`, `AllocationPlanner`, `BoxOffice`, and `Consumer` — `X-User-ID` is an opaque operator identifier that is not tied to the `id` of any persisted entity. The server records it for accountability where a workflow demands it — as `created_by_user_id` on a pigment batch, `certified_by_user_id` on a certified batch, `submitted_by_user_id` on a formula or a licensed line, `approved_by_user_id` on an approved formula, and `recorded_by_user_id` on a safety test — and it compares those recorded values against `X-User-ID` only where the segregation-of-duties rules of §2.9 say so. The single exception in shape, though not in opacity: the `Licensor` role's `X-User-ID` must exactly equal the `licensor_user_id` value stored on the licensed line being acted upon; that field is itself an opaque identifier supplied at line creation, not the `id` of any entity.

Read access is broad: every `GET` endpoint is open to all roles except `Consumer`, with two narrower exceptions — a single retail allocation and a spec's allocation list are visible only to `PlatformAdmin` and `AllocationPlanner`, and a session's ticket list is visible only to `PlatformAdmin` and `BoxOffice`. Write access is narrow and role-exclusive; §4 lists the authorized roles for every endpoint, and §3 narrates which role drives each workflow. Even the public ballot intake requires both headers, presented with the `Consumer` role.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Both appear on list endpoints that declare them, such as the production-run list, which also accepts `limit` and `offset` alongside its domain filters.

Unless a subsection of §3 states a more specific ordering, every list endpoint returns resources sorted by `created_at` in ascending order; several collections add a per-collection monotonic sequence as the tie-breaker (for example, runs order by creation time and then `run_seq`, safety tests by creation time and then `test_seq`, and a session's waitlist by creation time and then `waitlist_seq`).

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and the Operations Epoch

The platform does not consult wall-clock time for any business rule. All temporal behavior — voting windows, season windows, production lead times, session start and end, license terms, allocation expiry, recall cooling, and color archival — is evaluated against a single **logical clock** maintained by the server.

The logical clock's startup default is exactly `2026-09-01T00:00:00Z`. Before any clock-setting call has been made, the logical clock reads that instant, and it never falls back to wall-clock time on its own. A `PlatformAdmin` may move the clock to a supplied `to_iso8601` instant through the test-driving clock capability; the response reports the new value as `current_utc`. This capability is the one endpoint that lives outside the `/crayon-works` mount, at `/_clock/set_current_utc`.

Time-driven transitions do not fire continuously. They are processed in batches by the **operations epoch checkpoint**, an admin-triggered capability that advances the system epoch and applies every due transition in a fixed, pinned order (campaign openings, campaign tallies, session closings, allocation expirations, recall progressions, color archivals). Throughout §3, the phrase "at the epoch" or "the run-epoch" refers exclusively to a transition fired by this checkpoint; §3.8 defines the checkpoint's processing order and its response tallies.

### 2.5. Common Resource Properties

All thirteen resources of the platform — colors, pigment batches, formulas, vote campaigns, safety tests, assortment specs, production runs, inventory lots, retail allocations, licensed lines, attraction sessions, tickets, and recall cases — share one set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` (integer): starts at 1 when the resource is created and increments by exactly 1 on every mutation.

Every mutation counts, including system-driven ones: an epoch transition, a cascade that flips a spec to `DEPRECATED`, a recomputed aggregate such as `boxes_reserved`, and a `licensed_use_count` increment on a formula all refresh `updated_at` and advance `version` on the affected resource. No resource in this system is exempt from the common-fields convention.

### 2.6. Numbers, Money and Rounding

Monetary values are carried as integer cents on fields whose names end in `_cents` — `wholesale_price_cents`, `base_price_cents`, `price_cents`, `packing_penalty_cents`, and `projected_royalty_cents` — and every rounding applied to money is **round half up**. Three pinning rules remove all ambiguity about where rounding happens. In the packing-penalty calculation, each spec-entry line penalty is rounded half up to integer cents first, and the line results are then summed; summing the raw line amounts and rounding once is explicitly not the rule, because the two orders diverge (two lines each under-packed by 2 units yield 18.75 × 2 = 37.5 cents per line, which rounds to 38 per line and sums to 76, whereas rounding the raw sum of 75.0 would yield 75). In ticket pricing, round half up is applied exactly once, to the unit price, and the rounded unit price is then multiplied by the number of units. In the royalty projection, no intermediate value is rounded; round half up is applied only at the final multiplication of the royalty rate against the base.

The vote-tally ratio is computed in exact decimal arithmetic and is never rounded; the pass/fail boundary comparison uses the exact ratio. Box counts, visitor units, variance units, and severity thresholds are integers throughout; the allocation waterfall and the inventory reconciliation perform no rounding at all.

### 2.7. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and both reject a stale client view with `ERR_STALE_VERSION` (HTTP 412).

First, the allocation-creation endpoint `POST /crayon-works/retail-allocations`: creating a retail allocation requires the request to carry `expected_assortment_spec_version`, holding the `version` of the target assortment spec the client last observed. If the spec's current `version` has advanced past that value, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). The provisional waterfall share is computed from the spec's pool, so a client holding a stale view of the pool must re-read the spec before its request can be priced honestly. On success the allocation raises the spec's `boxes_reserved` and therefore increments the spec's `version`, so the next stale writer is rejected in turn.

Second, the licensed-line transition endpoint `POST /crayon-works/licensed-lines/{id}/transition`: every transition call on a line must carry `expected_formula_version`, holding the `version` of the line's formula the client last observed. If the formula's current `version` has advanced — for example because another line's brand approval incremented `licensed_use_count` — the transition is rejected with `ERR_STALE_VERSION` (HTTP 412), so that approval pins are never taken against a stale view of the formula. A successful brand approval increments the formula's `version`, so the next stale writer fails.

Endpoints not named in this subsection do not take a version field; no other request body carries an `expected_..._version` input.

### 2.8. Validation Pipeline and Error Precedence

Every request traverses a single validation pipeline of eleven ordered stages. The stages are evaluated in the order below, the first failure wins, and a request that would fail several checks surfaces the earliest one's error.

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the eleven declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Applies to all endpoints.
2. **Authorization.** The presented role is allowed on this endpoint per §4's role column; otherwise `ERR_UNAUTHORIZED` (HTTP 403). Applies to all endpoints.
3. **Request body shape.** Required fields are present, types and enum memberships are valid, and conditional-field rules are honored — `group_size` and `school_name` exactly when a ticket's `kind` is `GROUP`, `partner_name` exactly when a spec's `kind` is `CLASSROOM`. Undeclared extra fields are ignored: never echoed, never stored. Violations yield `ERR_INVALID_REQUEST` (HTTP 400). Applies to all endpoints.
4. **Existence.** Path identifiers must exist first; then body foreign keys are checked in the endpoint's declared input order, left to right. The first missing reference yields `ERR_NOT_FOUND` (HTTP 404). Applies to all endpoints with resource identifiers.
5. **Optimistic concurrency.** `expected_assortment_spec_version` must match the current spec `version`, and `expected_formula_version` must match the current formula `version`; otherwise `ERR_STALE_VERSION` (HTTP 412). Applies to the two OCC endpoints of §2.7.
6. **State gates.** The target resource must be in a state that permits the requested transition: formula state (`ERR_INVALID_FORMULA_STATE`), batch terminality (`ERR_BATCH_TERMINAL`), run stage (`ERR_RUN_STAGE_INVALID`, `ERR_RUN_ON_HOLD`), ticket state (`ERR_TICKET_STATE`), allocation state (`ERR_ALLOCATION_STATE`), licensed-line state (`ERR_LICENSE_STATE`), color posture for campaign creation (`ERR_COLOR_NOT_ACTIVE`), and campaign openness for ballots (`ERR_CAMPAIGN_NOT_OPEN`). All are HTTP 409.
7. **Business safety.** Segregation of duties (`ERR_SOD_VIOLATION`, HTTP 403), recall gating on a batch carrying an open or contained recall (`ERR_RECALL_ACTIVE`, HTTP 409), and the certification-mark rule for non-`STANDARD` hazard batches (`ERR_CERTIFICATION_MARK_REQUIRED`, HTTP 409). This stage guards certification decisions, formula transitions, line transitions, and production-run creation.
8. **Temporal rules.** Date ordering and windows: `closes_on` strictly after `opens_on`, `session_date` not in the past, run end strictly after run start, and license `term_end` strictly after `term_start` (`ERR_DATE_ORDER`, HTTP 422); the sixty-day production lead time (`ERR_PLANNED_START_TOO_SOON`, HTTP 422); the season window on `requested_ship_date` (`ERR_SEASON_WINDOW`, HTTP 422); and containment of a licensed run's planned dates in the line's term (`ERR_LICENSE_TERM_WINDOW`, HTTP 422).
9. **Capacity and structural constraints.** Session capacity (`ERR_SESSION_FULL`, HTTP 409), group size bounds (`ERR_GROUP_TOO_LARGE`, HTTP 422), per-color campaign window overlap on closed intervals (`ERR_CAMPAIGN_WINDOW_CONFLICT`, HTTP 409), venue session overlap including the turnover buffer (`ERR_SESSION_WINDOW_CONFLICT`, HTTP 409), assortment-spec structural validity including the box-size set and classroom core-color coverage (`ERR_SPEC_INVALID`, HTTP 409), and ballot payload validity (`ERR_VOTE_INVALID`, HTTP 422).
10. **Linked-entity state**, checked in this fixed intra-category order: an approved formula covers every spec entry color (`ERR_FORMULA_NOT_APPROVABLE`), the pigment batch is certified (`ERR_BATCH_NOT_CERTIFIED`), the spec is `ACTIVE` (`ERR_SPEC_DEPRECATED` — a retired entry color deprecates the spec, so `DEPRECATED` is the single gate for retired colors), a licensed spec is backed by an approved licensed line (`ERR_LICENSE_REQUIRED`), the session is still `SCHEDULED` (`ERR_SESSION_CLOSED`), and a reinstatement pin is fresh (`ERR_STALE_PIN`). All are HTTP 409.
11. **Fiscal sufficiency.** A commit that computes a zero final allocation is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409). Applies to the allocation-decision endpoint.

### 2.9. Segregation of Duties

Three decisions in the platform may never be taken by the same operator who originated the work; each violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403), evaluated at the business-safety stage of the pipeline. A `QualityAssurance` officer deciding a pigment batch's certification must not be the `X-User-ID` recorded as the batch's `created_by_user_id`. A `SafetyOfficer` approving, rejecting, or requesting revision on a formula must not be the `X-User-ID` recorded as that formula's `submitted_by_user_id`. A `BrandManager` brand-approving a licensed line must not be the `X-User-ID` recorded as that line's `submitted_by_user_id`. Because identities are opaque, the comparison is always a plain equality check of the two identifier strings.

### 2.10. The Back-to-School Season and the Production Lead Time

Two calendar constants shape supply planning. The **season window** — bounded by the `SEASON_START` and `SEASON_END` constants — runs from `2027-06-01T00:00:00Z` through `2027-08-31T23:59:59Z`, inclusive at both ends: every retail allocation's `requested_ship_date` must fall inside this closed interval or creation is rejected with `ERR_SEASON_WINDOW` (HTTP 422), and a production run's output counts toward the forward-looking allocation pool only when its `planned_end_date` falls on or before the season end and not before the current logical time.

Crayon production carries a long lead time: a run's `planned_start_date` must be no earlier than sixty days after the current logical clock value, or creation is rejected with `ERR_PLANNED_START_TOO_SOON` (HTTP 422). Planners therefore book seasonal capacity well before the window opens, and the allocation waterfall of §3.5 exists precisely to price retailer demand against supply that has not been molded yet.

## 3. Business Logic & Workflows

This section narrates each business workflow end to end. State names appear as their exact enumeration strings, error identifiers appear where their trigger conditions live, and the HTTP contract for every capability named here is collected in §4.

### 3.1. Color Catalog and Consumer Voting

The catalog begins when a `PlatformAdmin` registers a **color** with a display `name`, an RGB `hex_code` such as `#02A4D3`, and an optional `is_core_curriculum` flag that defaults to false. A new color starts in `PROPOSED` with `version` 1. Its `status` walks the enumeration `PROPOSED`, `IN_VOTE`, `ACTIVE`, `RETIRE_VOTE`, `RETIRED`, `ARCHIVED`, of which `ARCHIVED` is the only terminal state. The core-curriculum flag matters downstream: a `CLASSROOM` assortment spec must include every `ACTIVE` core-curriculum color (§3.4). Two system timestamps stay null until voting resolves them — `introduced_on`, set to the closing instant of the passing introduction campaign, and `retired_on`, set to the closing instant of the passing retirement campaign — and `archive_after_date`, which is derived as `retired_on` plus thirty days and drives archival.

A color never changes posture without a public vote. A `PlatformAdmin` opens a **vote campaign** for a color by supplying a `kind` of `INTRODUCTION` or `RETIREMENT`, an `opens_on` instant, and a `closes_on` instant. An introduction campaign requires the color to be `PROPOSED`; a retirement campaign requires it to be `ACTIVE`; any other posture is rejected with `ERR_COLOR_NOT_ACTIVE` (HTTP 409). The `closes_on` instant must be strictly after `opens_on`, else `ERR_DATE_ORDER` (HTTP 422). Campaign windows are closed intervals — both bounds belong to the window — and a new window must not intersect any existing campaign window of the same color; an overlap is rejected with `ERR_CAMPAIGN_WINDOW_CONFLICT` (HTTP 409). When the campaign is accepted, it is created in `SCHEDULED` and the color flips into its voting posture: `PROPOSED` to `IN_VOTE` for an introduction, or `ACTIVE` to `RETIRE_VOTE` for a retirement. A color's campaigns can be listed with optional `kind` and `status` filters, ordered by creation time ascending with creation sequence as the tie-breaker, and its formulas can be listed with an optional `status` filter.

A campaign carries the system's running ballot tallies: `votes_yes_weighted` and `votes_total_weighted`, both starting at 0, and `turnout_count`, the raw ballot count, also starting at 0. Its `outcome` — `PASSED` or `FAILED` — and its `tallied_at` instant remain null until the campaign is `TALLYED`. The campaign machine is epoch-driven: a `SCHEDULED` campaign becomes `OPEN` at the epoch when the logical clock has reached `opens_on` but has not yet reached `closes_on`; an `OPEN` campaign is tallied at the epoch when the clock has reached or passed `closes_on`. If the clock is moved so that the entire window is jumped — the campaign is still `SCHEDULED` when `closes_on` has already passed — the campaign is tallied anyway, over zero ballots, and fails on quorum as described below.

While a campaign is `OPEN`, a `Consumer` casts ballots by naming the `campaign_id`, a `voter_segment` of `KIDS`, `PARENTS`, `EDUCATORS`, or `COLLECTORS`, a `choice` of `YES` or `NO`, and an optional `count` that imports that many identical ballots and defaults to 1. A ballot cast on a campaign that is `SCHEDULED` or `TALLYED` is rejected with `ERR_CAMPAIGN_NOT_OPEN` (HTTP 409); an unknown segment, an unknown choice, or a `count` below 1 is rejected with `ERR_VOTE_INVALID` (HTTP 422). Each accepted ballot adds its segment weight to `votes_total_weighted`; `YES` ballots additionally add the same weight to `votes_yes_weighted`; and `turnout_count` grows by the raw `count`. The response confirms `accepted`, echoes the `campaign_id`, and reports the `weight_applied`.

The tally itself — the `vote_tally` rule — is weighted scoring, computed in exact decimal arithmetic at the epoch. Weights depend on the campaign kind. For `INTRODUCTION`: `KIDS` weigh 1.0, `PARENTS` 1.5, `EDUCATORS` 2.0, and `COLLECTORS` 1.2. For `RETIREMENT`: `KIDS` weigh 1.0, `PARENTS` 1.0, `EDUCATORS` 1.5, and `COLLECTORS` 2.5. The yes-ratio is `votes_yes_weighted` divided by `votes_total_weighted`; when no ballots were cast at all the ratio is defined as 0. The campaign `PASSED` exactly when two conditions both hold — `turnout_count` reaches the minimum turnout `MIN_TURNOUT` of 10 ballots, and the exact ratio is at least the kind's threshold: `INTRO_THRESHOLD`, 0.55, for `INTRODUCTION`, and `RETIRE_THRESHOLD`, 0.60, for `RETIREMENT`. The threshold comparison is inclusive, so a ratio landing exactly on the threshold passes. Because the weight tables and thresholds differ, an identical set of ballots can pass an introduction yet fail a retirement.

The outcome is applied to the subject color immediately at the tally. A passed introduction moves the color from `IN_VOTE` to `ACTIVE` and stamps `introduced_on` with the campaign's `closes_on`; a failed introduction returns the color to `PROPOSED`, and a later campaign may retry the introduction — the revision loop is intentional. A passed retirement moves the color from `RETIRE_VOTE` to `RETIRED`, stamps `retired_on` with the campaign's `closes_on`, and derives `archive_after_date` as `closes_on` plus thirty days; a failed retirement returns the color to `ACTIVE`. Retirement also cascades at that moment: every assortment spec whose entries contain the retired color becomes `DEPRECATED`, and every `PLANNED` production run of a newly deprecated spec is `CANCELLED`. Finally, when the logical clock reaches or passes `archive_after_date`, the epoch moves the color from `RETIRED` to `ARCHIVED`, closing the lifecycle.

### 3.2. Pigment Sourcing, Certification, and Recall Readiness

Raw color enters the platform as a **pigment batch**, registered by a `SourcingManager` or a `QualityAssurance` officer with a `pigment_name` such as Phthalo Blue, the `supplier_name`, a `hazard_class` of `STANDARD`, `SENSITIVE`, or `RESTRICTED` reflecting the child-product safety classification, a `received_quantity_kg` that must be greater than 0, and the `certification_mark` sought for the lot — `ACMI_AP`, `ACMI_CL`, or `NONE`. A new batch starts in `QUARANTINE`, and the registrar's `X-User-ID` is recorded as `created_by_user_id`, which becomes the segregation-of-duties anchor.

Certification is decided by a `QualityAssurance` officer — never the batch's own registrar, per §2.9 — through a `decision` of `CERTIFY` or `REJECT` with an optional `reason`. A decision attempted on a `REJECTED` batch is refused with `ERR_BATCH_TERMINAL` (HTTP 409), because `REJECTED` is terminal. A `CERTIFY` decision on a `QUARANTINE` batch moves it to `CERTIFIED` and records the decider as `certified_by_user_id`; when the batch's `hazard_class` is `SENSITIVE` or `RESTRICTED`, certification additionally requires the `certification_mark` to be `ACMI_AP`, else the decision is rejected with `ERR_CERTIFICATION_MARK_REQUIRED` (HTTP 409). A `REJECT` decision on a `QUARANTINE` batch moves it to `REJECTED` and stores the payload `reason` as `rejection_reason`.

A `REJECT` decision on an already `CERTIFIED` batch is the platform's recall trigger: the batch is retro-rejected to `REJECTED`, and if any production run references the batch, a **recall case** is created in `OPEN` naming the batch as its `pigment_batch_id`, and the recall cascade fires in the same motion. The cascade walks every run consuming the batch. A `PLANNED` run becomes `CANCELLED`. Runs in `MOLDING`, `LABELING`, `PACKING`, or `ON_HOLD` become `QUARANTINED`. A `COMPLETED` run becomes `QUARANTINED` as well — completion is not a safe harbor — and its inventory lots become `QUARANTINED` with their `boxes_committed` frozen inside the quarantined lot; quarantined lots are excluded from their spec's `boxes_available`, which is recomputed. With supply withdrawn, the cascade then shorts commitments: `COMMITTED` allocations of the affected specs become `SHORTED`, newest first — `created_at` descending with `request_seq` descending as the tie-breaker — until the remaining committed demand fits within the `AVAILABLE` lots again; a shorted allocation no longer claims its committed boxes, which stay frozen in the quarantined lots, and `boxes_reserved` is recomputed. One hop further, any `APPROVED` licensed line is `SUSPENDED` when the recall quarantines a run whose spec contains the color of the line's formula (§3.6). A batch's recall cases can be listed with an optional `status` filter.

The recall case records two computed measures of blast radius. `affected_run_count` counts the runs quarantined or cancelled by the cascade. `affected_units` sums crayon units in scope: each affected `COMPLETED` run contributes its `boxes_produced` multiplied by the spec's `box_size`, while every other affected run contributes its `planned_boxes` multiplied by the spec's `box_size`. From these the case's `severity` is classified by the `recall_severity_classification` rule. The base class follows `affected_units`: fewer than the `CLASS_II_FLOOR` of 1000 units is `CLASS_III`; from 1000 units up to but not including the `CLASS_I_FLOOR` of 10000 is `CLASS_II` — the boundary value 1000 belongs to class II; 10000 units or more is `CLASS_I`. The batch's hazard class can then bump the severity: `RESTRICTED` raises it one class (`CLASS_III` to `CLASS_II`, `CLASS_II` to `CLASS_I`, while `CLASS_I` stays `CLASS_I`); `SENSITIVE` raises only `CLASS_III` to `CLASS_II`; `STANDARD` never bumps. Severity sets the cooling window: `CLASS_III` cools for the `COOLING_III_DAYS` window of 7 days, `CLASS_II` for the `COOLING_II_DAYS` window of 14 days, and `CLASS_I` for the `COOLING_I_DAYS` window of 30 days, and `cooling_until` is the case's `created_at` plus its severity's cooling days.

The case then progresses at the epoch. An `OPEN` case moves to `CONTAINED` once the epoch has verified the cascade has been applied to all affected runs, lots, allocations, and licensed lines. A `CONTAINED` case moves to `CLOSED` once the logical clock is at or after `cooling_until`; closure makes the `SUSPENDED` licensed lines whose suspension traces to this case eligible for reinstatement. While any case against a batch is `OPEN` or `CONTAINED`, that batch gates production: a new run referencing it is rejected with `ERR_RECALL_ACTIVE` (HTTP 409), and per §2.8 this recall gate fires at the business-safety stage, ahead of the linked-entity checks.

### 3.3. Formula Development and Safety Testing

A **formula** is the recipe that produces a color. A `Formulator` or `SafetyOfficer` creates one by naming the `color_id` of the color it produces, an `intended_use` of `CRAYON`, `MARKER`, or `COLORED_PENCIL`, and a `pigment_recipe` — an opaque list of recipe lines, each naming a pigment and its parts — which must be a non-empty array. A new formula starts in `DRAFT` with `licensed_use_count` at 0. Its `status` enumeration is `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, `REJECTED`, `SUPERSEDED`, with `REJECTED` and `SUPERSEDED` terminal.

Submission is the action `SUBMIT`, open to `Formulator` and `SafetyOfficer` alike. From `DRAFT`, or from `REVISION_REQUESTED` on a resubmission, the formula moves to `SUBMITTED`; the submitter's `X-User-ID` is recorded as `submitted_by_user_id`, and a new **safety test** is created in `SCHEDULED` for the formula, because safety certification is mandatory before approval. Resubmission always spawns a fresh test; older test results remain on their own rows as history. The revision loop is intentional: a formula may cycle from `DRAFT` to `SUBMITTED` to `REVISION_REQUESTED` and back to `SUBMITTED` repeatedly.

Each safety test is bound to its formula by `formula_id`, assigned at creation by the submit cascade. It carries the `test_standard` applied — `ASTM_D4236` by default, or `EN71_3` — and a per-formula monotonic `test_seq` beginning at 1, so a formula's tests read in `created_at` ascending, `test_seq` ascending order, which is also the listing order when a formula's tests are listed with the optional `status` filter. Its `status` is `SCHEDULED`, `PASSED`, or `FAILED`; `result_notes` and `recorded_by_user_id` stay null until a result is recorded. A `LabTechnician` records the lab outcome with an `outcome` of `PASS` or `FAIL` and optional `result_notes`: a `PASS` moves the test from `SCHEDULED` to `PASSED`, a `FAIL` moves it to `FAILED`, and either way `result_notes` captures the payload notes and `recorded_by_user_id` captures the technician's `X-User-ID`. A failed test blocks formula approval until a later test for the same formula has passed.

Approval is a `SafetyOfficer` decision and obeys segregation of duties: the decider's `X-User-ID` must differ from the formula's `submitted_by_user_id`, else `ERR_SOD_VIOLATION` (HTTP 403). An `APPROVE` on a `SUBMITTED` formula additionally requires that the formula's latest safety test — the last test in the creation-time and `test_seq` ordering — is `PASSED`; otherwise the decision is rejected with `ERR_FORMULA_NOT_APPROVABLE` (HTTP 409). On approval the formula becomes `APPROVED`, `approved_by_user_id` records the approver, and two cascades fire: every other `APPROVED` formula for the same color becomes `SUPERSEDED`, and every `APPROVED` licensed line whose `formula_id` is one of those newly superseded formulas becomes `SUSPENDED` (§3.6). A `REJECT` decision moves a `SUBMITTED` formula to `REJECTED`; a `REQUEST_REVISION` decision moves it to `REVISION_REQUESTED`; both also obey the segregation rule, and both accept an optional `reason`. Any transition attempted from a state that does not permit it is rejected with `ERR_INVALID_FORMULA_STATE` (HTTP 409).

### 3.4. Assortment Specs and the Production Pipeline

An **assortment spec** describes a box configuration. A `PlatformAdmin` creates one with a `name` such as a 64-count back-to-school box, a `kind` of `RETAIL`, `CLASSROOM`, or `LICENSED`, an `entries` packing plan of color-and-count lines, and a `wholesale_price_cents` of at least 1 cent. The conditional field `partner_name` — the education-program partner — is required exactly when `kind` is `CLASSROOM` and must be omitted for `RETAIL` and `LICENSED`, or creation fails with `ERR_INVALID_REQUEST` (HTTP 400).

The packing plan is validated structurally, with violations rejected as `ERR_SPEC_INVALID` (HTTP 409): `entries` must be non-empty; each line's count must be at least 1; at most one entry per color is allowed; every referenced color must exist and be `ACTIVE`; and a `CLASSROOM` spec must include every `ACTIVE` core-curriculum color. From the entries the system computes `box_size` as the sum of the entry counts, and the sum must be one of 8, 16, 24, or 64 — any other total is likewise `ERR_SPEC_INVALID`. A new spec is `ACTIVE` with `boxes_available` and `boxes_reserved` both 0. Its `status` thereafter is derived: the moment any entry color becomes `RETIRED` or `ARCHIVED`, the spec becomes `DEPRECATED`, recomputed on every color status change — this is the cascade the retirement of §3.1 sets in motion, and deprecation is the single gate through which retired colors block new production.

The spec's two inventory aggregates are always reconciled under the `spec_boxes_reconciliation` rule, never cached loosely. `boxes_available` is the sum of `boxes_on_hand` over the inventory lots of runs created with this spec whose lot status is `AVAILABLE` or `DEPLETED`; quarantined lots are excluded. `boxes_reserved` is the sum of `allocated_boxes_provisional` over the spec's `REQUESTED` allocations plus the sum of `allocated_boxes_final` over its `COMMITTED` allocations. Both are recomputed on run completion, on lot quarantine, on every allocation commit, fulfil, release, or expire, and on read, so the stored value always equals the lot-level sum with no drift.

Against an `ACTIVE` spec, a `PlatformAdmin` plans a **production run**, naming the `assortment_spec_id`, the `pigment_batch_id` the molding stage will consume, a `planned_boxes` of at least 1, a `planned_start_date` honoring the sixty-day lead time of §2.10, and a `planned_end_date` strictly after the start date, else `ERR_DATE_ORDER`. Creation then walks the linked-entity gates in the fixed order of §2.8 stage 10: every entry color of the spec must be covered by an `APPROVED` formula, else `ERR_FORMULA_NOT_APPROVABLE`; the pigment batch must be `CERTIFIED`, else `ERR_BATCH_NOT_CERTIFIED` — unless the batch carries an `OPEN` or `CONTAINED` recall, which the earlier business-safety stage has already rejected as `ERR_RECALL_ACTIVE`; the spec must be `ACTIVE`, else `ERR_SPEC_DEPRECATED`; and a `LICENSED` spec must be backed by an `APPROVED` licensed line covering one of the spec's colors, else `ERR_LICENSE_REQUIRED` — with the run's planned dates fully contained in that line's term, a temporal-stage check rejected as `ERR_LICENSE_TERM_WINDOW`. A run is born in `PLANNED` and receives a global monotonic `run_seq`; the run list orders by creation time ascending and then `run_seq`, and accepts optional `assortment_spec_id`, `pigment_batch_id`, and `stage` filters.

The run's `stage` walks `PLANNED`, `MOLDING`, `LABELING`, `PACKING`, `COMPLETED` through successive advances, with `ON_HOLD` as a lateral parking state and `CANCELLED` and `QUARANTINED` as the terminal exits. A plain advance moves one step forward. The advance out of `PACKING` is the packing-accuracy gate and requires the operator to supply `packed_counts` — the actual per-color packed units — covering exactly the spec's entry colors, no more and no fewer, else `ERR_INVALID_REQUEST`. The `packing_penalty` evaluation proceeds entry by entry in the entries-array order: for each entry, the expected units are the entry's count multiplied by `planned_boxes`, and the line variance is the absolute difference between packed and expected. Summing the line variances yields `packing_variance_units`. Each line's penalty is the `UNDER_UNIT_PENALTY_CENTS` rate of 18.75 cents per variance unit, multiplied by the `OVER_FACTOR` of 1.5 on lines packed above expectation, rounded half up to integer cents per line and only then summed into `packing_penalty_cents`, exactly per the rounding pin of §2.6. If the total variance exceeds the `TOLERANCE_UNITS` tolerance of 5 units, the run does not complete: it is placed `ON_HOLD` with `stage_before_hold` recorded as `PACKING` and `hold_reason` recorded as `QUALITY`, the computed penalty is still recorded against the run, and no inventory lot is created. Otherwise the run completes: `boxes_produced` is the minimum over the spec entries of the whole-boxes floor of that entry's packed units divided by the entry's count; `waste_units` is the total packed units minus `boxes_produced` multiplied by `box_size`, and the `run_production_mass_balance` invariant holds exactly — total packed units equal `boxes_produced` boxes times `box_size` plus `waste_units`. Completion creates an **inventory lot** bound to its producing run by `production_run_id`, in `AVAILABLE`, whose `boxes_received` and `boxes_on_hand` both equal `boxes_produced`, whose `boxes_committed` and `boxes_shipped` start at 0, and which receives the next per-spec monotonic `lot_seq` beginning at 1; the spec's `boxes_available` is recomputed in the same motion.

Operators manage the run's lateral moves with three further actions. `HOLD` parks a run in `MOLDING`, `LABELING`, or `PACKING` into `ON_HOLD`, recording the vacated stage in `stage_before_hold` and setting `hold_reason` to `QUALITY`. `RESUME` returns an `ON_HOLD` run to exactly the stage recorded in `stage_before_hold` and clears both `stage_before_hold` and `hold_reason` to null. `CANCEL` terminates a run from `PLANNED`, `MOLDING`, `LABELING`, `PACKING`, or `ON_HOLD` into `CANCELLED`, and because a cancelled run leaves the projected supply set, the provisional allocation waterfall of §3.5 is re-run for the spec. Attempting to advance a run that is `ON_HOLD` is rejected with `ERR_RUN_ON_HOLD` (HTTP 409) — the run must be resumed first; any other action disallowed from the current stage is rejected with `ERR_RUN_STAGE_INVALID` (HTTP 409). Note the asymmetry of the endgame: `COMPLETED` is not terminal, because recall quarantine (§3.2) remains its only exit, while `CANCELLED` and `QUARANTINED` are final.

Inventory lots live a quiet lifecycle of their own. When a deduction drives `boxes_on_hand` to 0, the lot flips automatically from `AVAILABLE` to `DEPLETED`; when a release returns boxes so that on-hand rises above 0, a `DEPLETED` lot flips back to `AVAILABLE`. Both directions of the availability cycle are system-driven by allocation activity. A recall quarantines `AVAILABLE` and `DEPLETED` lots alike into `QUARANTINED`, which is terminal, freezing the lot's fields as they stand. A run's lots can be listed with an optional `status` filter. Throughout, first-in-first-out ordering — `created_at` ascending with `lot_seq` ascending as the tie-breaker — governs every deduction from and return to a spec's lots.

### 3.5. Seasonal Retail Allocation and the Waterfall

Retail demand for the back-to-school season is booked as **retail allocations**. An `AllocationPlanner` creates one by naming the `assortment_spec_id`, the `retailer_name`, a `priority_tier` of `PLATINUM`, `GOLD`, or `STANDARD`, a `requested_boxes` of at least 1, a `requested_ship_date` inside the season window of §2.10 — a date outside it is rejected with `ERR_SEASON_WINDOW` (HTTP 422) — and, per §2.7, an `expected_assortment_spec_version` matching the spec's current `version`, else `ERR_STALE_VERSION` (HTTP 412). The allocation is born in `REQUESTED` with a per-spec monotonic `request_seq` beginning at 1, its forward-looking share is computed immediately into `allocated_boxes_provisional`, and because the new reservation raises the spec's `boxes_reserved`, the spec's `version` increments by 1 in the same request. Its `allocated_boxes_final` stays null until a commit fixes it. A spec's allocations can be listed with optional `status` and `priority_tier` filters.

The provisional share comes from the **allocation waterfall**, the `retail_allocation_waterfall` rule. All `REQUESTED` allocations of a spec are ranked by tier — `PLATINUM` first, then `GOLD`, then `STANDARD` — with earlier `created_at` breaking ties inside a tier and `request_seq` ascending breaking any remaining tie. The pool is the spec's physical `boxes_available` plus its projected boxes, where the projection sums `planned_boxes` over the spec's runs whose stage is `PLANNED`, `MOLDING`, `LABELING`, `PACKING`, or `ON_HOLD` and whose `planned_end_date` falls on or before the season end and not before the current logical time. The walk then serves each allocation in rank order a provisional share equal to the smaller of its `requested_boxes` and the remaining pool, subtracting each share as it is granted. Whatever a walk cannot serve stays unallocated: the waterfall never over-commits and the pool never goes negative. The provisional walk is re-run for all `REQUESTED` allocations of a spec whenever an allocation is created, released, or expired, and on every pool change — a run completing, a run being cancelled, or a lot being quarantined.

Three decisions resolve an allocation, each taken by an `AllocationPlanner` through the allocation's `action` input. `COMMIT` moves `REQUESTED` to `COMMITTED` and computes the final share against physical stock only — projections are excluded — as the smaller of `requested_boxes` and the spec's `boxes_available`; a final share of 0 is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409). The computed amount is frozen into `allocated_boxes_final`, and the physical deduction walks the spec's `AVAILABLE` and `DEPLETED` lots in first-in-first-out order — `created_at` ascending, then `lot_seq` ascending — moving boxes from `boxes_on_hand` into `boxes_committed` until the final amount is covered, flipping any lot that reaches 0 on-hand to `DEPLETED`. `FULFILL` moves `COMMITTED` to `FULFILLED`, walking the spec's lots in `created_at` ascending order to move `allocated_boxes_final` boxes from `boxes_committed` to `boxes_shipped`. `RELEASE` is the compensating action and works from either live state: from `REQUESTED` it simply drops the provisional reservation; from `COMMITTED` it returns `allocated_boxes_final` to the lots in first-in-first-out order, each lot regaining up to its own `boxes_committed` — the smaller of the remaining return and that lot's committed count — from committed back to on-hand, and any `DEPLETED` lot whose on-hand rises above 0 becomes `AVAILABLE` again; the lot-level mass balance must hold exactly afterwards. Every one of these decisions recomputes the spec's `boxes_available` and `boxes_reserved` in the same request and re-runs the provisional waterfall for the spec's remaining `REQUESTED` allocations. A decision attempted from a state that does not allow it is rejected with `ERR_ALLOCATION_STATE` (HTTP 409); `FULFILLED`, `RELEASED`, `EXPIRED`, and `SHORTED` are the terminal states.

Two system transitions complete the machine. At the epoch, a `REQUESTED` allocation whose `requested_ship_date` is strictly before the logical clock becomes `EXPIRED`; its provisional reservation drops and the waterfall is re-run. And per §3.2, the recall cascade moves `COMMITTED` allocations to `SHORTED`, newest first, when quarantined lots push committed demand above the remaining `AVAILABLE` supply.

### 3.6. Licensed and Co-Branded Lines

A **licensed line** is a co-branded product line — a movie tie-in box, for instance — governed by a two-party approval workflow. A `BrandManager` creates one with a `name`, the `licensor_user_id` the licensor-side approver will present, the `formula_id` of the line's signature color formula, a `term_start` and `term_end` bracketing the license term inclusively — `term_end` must be strictly after `term_start`, else `ERR_DATE_ORDER` — a `royalty_rate` greater than 0 and at most 0.5, and a `royalty_base` of `GROSS` or `NET` selecting the royalty variant. The line starts in `DRAFT`. Its `status` enumeration is `DRAFT`, `LICENSOR_REVIEW`, `BRAND_REVIEW`, `APPROVED`, `REJECTED`, `SUSPENDED`, with `REJECTED` terminal. Every transition call on a line carries `expected_formula_version` and is subject to the optimistic-concurrency rule of §2.7: a mismatch with the formula's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) before anything else about the transition is considered. A formula's lines can be listed with an optional `status` filter.

`SUBMIT`, by a `BrandManager`, moves the line from `DRAFT` to `LICENSOR_REVIEW` and records the submitter's `X-User-ID` as `submitted_by_user_id`. In `LICENSOR_REVIEW` the ball is with the licensor: the acting `Licensor`'s `X-User-ID` must equal the line's `licensor_user_id`, else `ERR_UNAUTHORIZED` (HTTP 403). `LICENSOR_APPROVE` advances the line to `BRAND_REVIEW`; `LICENSOR_REQUEST_REVISION` sends it back to `DRAFT` in the licensor-side revision loop; `LICENSOR_REJECT` terminates it as `REJECTED`.

In `BRAND_REVIEW` the brand side decides. `BRAND_APPROVE` obeys segregation of duties — the approver must not be the recorded `submitted_by_user_id`, else `ERR_SOD_VIOLATION` — and on success two things happen in one motion: the formula's `licensed_use_count` increments by 1, which itself increments the formula's `version` by 1, and the line's `pinned_formula_version` is set to the formula's resulting `version`, pinning the approval to exactly the formula state the parties reviewed. The line becomes `APPROVED`. `BRAND_REQUEST_REVISION` returns the line to `LICENSOR_REVIEW` — the two review states form a negotiation cycle — and `BRAND_REJECT` terminates it as `REJECTED`.

An `APPROVED` line is `SUSPENDED` by the system, never by an operator, in either of two situations already narrated: the pinned formula was `SUPERSEDED` by a newer approval for the same color (§3.3), or a recall quarantined a run whose spec contains the formula's color (§3.2). Reinstatement is a `BrandManager` action: `REINSTATE` moves `SUSPENDED` back to `APPROVED` only when no `OPEN` or `CONTAINED` recall case touches the line's formula color, the line's formula is currently `APPROVED`, and `pinned_formula_version` still equals the formula's current `version`; a stale pin or a non-approved formula is rejected with `ERR_STALE_PIN` (HTTP 409). Any other action attempted from a state that does not permit it is rejected with `ERR_LICENSE_STATE` (HTTP 409).

The line's `projected_royalty_cents` is a computed projection — the `licensed_royalty` rule — recomputed on every read of the line and again after any allocation or production-run mutation touching the line's formula color. Let the line's color be the color of its pinned formula, and consider every assortment spec whose entries contain that color. The evaluation order is pinned, because the steps are interdependent — gross is established first and is lifetime-committed, not currently-committed, and penalties are never subtracted before gross exists. First, gross is the sum, over every allocation of those specs whose status is `COMMITTED`, `FULFILLED`, `RELEASED`, or `SHORTED`, of the allocation's `allocated_boxes_final` multiplied by its spec's `wholesale_price_cents`. Second, returns are the same product summed over only the `RELEASED` and `SHORTED` allocations in that set. Third, penalties are the sum of `packing_penalty_cents` over every production run of those specs. Fourth, the base depends on the variant: under `GROSS` the base is gross itself, returns and penalties ignored; under `NET` the base is gross minus returns minus penalties, floored at 0 — the two variants diverge whenever returns or penalties are nonzero. Fifth and finally, `projected_royalty_cents` is the `royalty_rate` multiplied by the base, rounded half up to integer cents at this final step only.

### 3.7. The Factory Experience: Sessions, Tickets, and the Waitlist

The factory-adjacent attraction sells timed **sessions**. A `PlatformAdmin` schedules one with a `venue_name` such as Hall A, a `session_date` that must not be before the current logical date — a past date is rejected with `ERR_DATE_ORDER` (HTTP 422) — a `start_minute` expressed as minutes after midnight local, from 0 to 1339 inclusive, a `duration_minutes` of at least 30, a `capacity_units` of at least 1 where one unit is one visitor, a `base_price_cents` of at least 0, and an optional `is_charter` flag, defaulting to false, that marks a school buyout and selects the charter pricing variant below. A new session is `SCHEDULED` with `booked_units` at 0; `CLOSED` is its only other state and is terminal.

Sessions in the same venue on the same date share the venue's timeline. Each session occupies a half-open interval that begins at its `start_minute` and runs until thirty minutes after its scheduled end — the extra half hour is a turnover buffer — and a new session's occupied interval must not intersect the occupied interval of any existing `SCHEDULED` session on that venue and date. Because the intervals are half-open, a gap of exactly 30 minutes between one session's start and the previous session's end is allowed: the buffer, not a minute more, separates them. An intersection is rejected with `ERR_SESSION_WINDOW_CONFLICT` (HTTP 409).

A `BoxOffice` agent books a **ticket** against a session by naming the `session_id` and a `kind` of `INDIVIDUAL` or `GROUP`, the latter being the school-group booking path. For a `GROUP` booking, `group_size` and `school_name` are both required; for `INDIVIDUAL` both must be omitted — conditional-field violations are `ERR_INVALID_REQUEST`. A `group_size` must be at least 10 and at most 100; above 100 the booking is rejected with `ERR_GROUP_TOO_LARGE` (HTTP 422). The session must still be `SCHEDULED`, else `ERR_SESSION_CLOSED` (HTTP 409). The ticket's `units` are derived: 1 for an `INDIVIDUAL`, the `group_size` for a `GROUP`.

Whether a booking is confirmed immediately depends on kind and capacity. An `INDIVIDUAL` ticket is created `CONFIRMED` when the session has room — that is, when adding its one unit to `booked_units` would not exceed `capacity_units`, with equality still fitting — and is otherwise rejected outright with `ERR_SESSION_FULL` (HTTP 409); individuals never waitlist. A `GROUP` booking is created `CONFIRMED` when the whole group fits, and is otherwise created directly in `WAITLISTED`: no partial seating, and no capacity consumed while waiting. Each new ticket receives the next per-session monotonic `waitlist_seq` beginning at 1, and a session's tickets can be listed with optional `status` and `kind` filters.

Price is computed per the `ticket_dynamic_price` rule at confirmation — at creation for an individual or a fitting group, and at promotion for a waitlisted group — and then fixed on the ticket as `price_cents`. The dynamic price multiplies the session's `base_price_cents` by three factors. The capacity factor reads the booked ratio, `booked_units` divided by `capacity_units`, measured before this booking: below the low-tier ceiling `LOW_TIER_CEIL` of 0.5 the factor is the low multiplier `LOW_MULT`, 0.9; from 0.5 up to but not including the high-tier floor `HIGH_TIER_FLOOR` of 0.8 the factor is 1.0; at 0.8 or above the factor is the high multiplier `HIGH_MULT`, 1.25. The group factor is `GROUP50_MULT`, 0.75, for a `GROUP` booking of at least 50 units; `GROUP20_MULT`, 0.85, for a `GROUP` booking of at least 20 units; and 1.0 otherwise. The day factor is `WEEKEND_MULT`, 1.15, when `session_date` falls on a Saturday or Sunday, and 1.0 otherwise. The unit price is the base multiplied by all three factors, rounded half up to integer cents exactly once, and `price_cents` is that rounded unit price multiplied by the ticket's `units`. On a charter session — `is_charter` true — the formula flattens to the school buyout rate: the capacity factor is fixed at 1.0 and the group factor for a `GROUP` booking is a flat `CHARTER_GROUP_MULT` of 0.80, while the day factor still applies.

Under the `session_booked_units` rule, the session's `booked_units` is always the sum of `units` over its tickets in `CONFIRMED` or `CHECKED_IN` status — immediate consistency, maintained on every confirmation, promotion, refund, cancellation, and no-show, so a refund followed by a same-size booking leaves the count unchanged.

Three decisions, all taken by `BoxOffice` through the ticket's `action` input, resolve a ticket. `CHECK_IN` requires the ticket `CONFIRMED`, the session still `SCHEDULED` — else `ERR_SESSION_CLOSED` — and the logical clock inside the session's live window, from its start through its end on the session date; outside that window the attempt is `ERR_TICKET_STATE` (HTTP 409). A successful check-in stamps `checked_in_at` with the logical clock and moves the ticket to `CHECKED_IN`. `REFUND` requires a `CONFIRMED` ticket and a logical clock earlier than the session start — the refund window closes when the session begins, and a late attempt is `ERR_TICKET_STATE`. A refund moves the ticket to `REFUNDED`, subtracts its `units` from the session's `booked_units`, and then runs the **waitlist promotion cascade**: the session's `WAITLISTED` tickets are walked in `created_at` ascending, `waitlist_seq` ascending order, and the head of the line is promoted while its `units` fit the freed capacity. The blocking is strict head-of-line — a head whose group does not fit stops the walk entirely, and no later waitlisted ticket is ever skipped ahead of it. Each promoted ticket becomes `CONFIRMED`, adds its `units` to `booked_units`, and computes its `price_cents` at the current booked ratio as described above. `CANCEL` moves a `WAITLISTED` ticket to `CANCELLED`. Any decision attempted from a ticket state that does not permit it is `ERR_TICKET_STATE`; the terminal ticket states are `CHECKED_IN`, `REFUNDED`, `CANCELLED`, and `NO_SHOW`.

Finally, the epoch closes sessions whose end has come. When the logical clock is at or past the session's end — its `session_date` at `start_minute` plus `duration_minutes` — the session moves from `SCHEDULED` to `CLOSED`, each of its still-`CONFIRMED` tickets becomes `NO_SHOW`, each `WAITLISTED` ticket becomes `CANCELLED`, and `booked_units` recomputes to 0.

### 3.8. The Operations Epoch

The run-epoch checkpoint of §2.4 is the platform's batch heart-beat, callable only by `PlatformAdmin`. Each call advances the system epoch and processes six phases in this exact, pinned order — the order is part of the contract, because later phases observe the results of earlier ones within the same epoch:

1. **Campaign openings.** Every `SCHEDULED` vote campaign whose window now contains the logical clock — `opens_on` reached, `closes_on` not yet reached — becomes `OPEN`, processed in `created_at` ascending order.
2. **Campaign tallies.** Every campaign whose `closes_on` is at or before the logical clock is tallied, oldest `closes_on` first — including campaigns that never opened, which are tallied over zero ballots and therefore fail on quorum per §3.1. Each tally computes the weighted outcome and applies it to the subject color, and a passing retirement fires the retirement cascade — spec deprecations and `PLANNED`-run cancellations — inside this phase.
3. **Session closings.** Every session whose end is at or before the clock is closed, marking its tickets `NO_SHOW` or `CANCELLED` as §3.7 describes.
4. **Allocation expirations.** Every `REQUESTED` allocation whose `requested_ship_date` is strictly before the clock becomes `EXPIRED`, dropping its provisional reservation and re-running the waterfall.
5. **Recall progressions.** `OPEN` recall cases move to `CONTAINED` once the epoch verifies the cascade has been applied to all affected runs, lots, allocations, and licensed lines, and `CONTAINED` cases whose `cooling_until` is at or before the clock move to `CLOSED`.
6. **Color archivals.** Every `RETIRED` color whose `archive_after_date` is at or before the clock becomes `ARCHIVED`.

The checkpoint's response reports the epoch as `epoch_index` together with per-phase tallies: `campaigns_opened`, `campaigns_tallied`, `sessions_closed`, `allocations_expired`, `recalls_contained`, `recalls_closed`, and `colors_archived`, each an integer count of the transitions that fired in that phase during this epoch.

## 4. Endpoint Definitions

All endpoints share the envelope of §2.2 and the pipeline of §2.8. Successful resource creation returns HTTP 201 with the new resource in `data`; reads, transitions, decisions, result recordings, ballots, the clock set, and the epoch checkpoint return HTTP 200. Every request must present the `X-User-ID` and `X-User-Role` headers of §2.1, and the role column below is evaluated at the authorization stage. Request payloads, derived fields, and side effects are specified per workflow in §3; this table is the routing and authorization summary only. "All operational roles" means every role of §2.1 except `Consumer`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /crayon-works/colors | Create a color; it starts `PROPOSED`. | PlatformAdmin |
| GET | /crayon-works/colors/{id} | Get a color by id. | All operational roles |
| POST | /crayon-works/colors/{id}/vote-campaigns | Open a voting campaign for the color; flips `PROPOSED` to `IN_VOTE` for an introduction or `ACTIVE` to `RETIRE_VOTE` for a retirement. Campaign windows are closed intervals and must not overlap an existing campaign of the same color. | PlatformAdmin |
| GET | /crayon-works/colors/{id}/vote-campaigns | List the color's vote campaigns, ordered by creation time then creation sequence; optional `kind` and `status` filters. | All operational roles |
| GET | /crayon-works/colors/{id}/formulas | List the color's formulas; optional `status` filter. | All operational roles |
| POST | /crayon-works/pigment-batches | Register a received pigment batch; it starts `QUARANTINE` and records the registrar for segregation of duties. | SourcingManager, QualityAssurance |
| GET | /crayon-works/pigment-batches/{id} | Get a pigment batch by id. | All operational roles |
| POST | /crayon-works/pigment-batches/{id}/certification-decision | Certify or reject a batch; rejecting a `CERTIFIED` batch retro-rejects it and opens the recall cascade. The decider must not be the batch's registrar. | QualityAssurance |
| GET | /crayon-works/pigment-batches/{id}/recall-cases | List the batch's recall cases; optional `status` filter. | All operational roles |
| POST | /crayon-works/assortment-specs | Create an assortment packing spec; `box_size` is computed from the entries and must be one of 8, 16, 24, or 64; `CLASSROOM` specs require `partner_name` and every `ACTIVE` core-curriculum color. | PlatformAdmin |
| GET | /crayon-works/assortment-specs/{id} | Get an assortment spec by id; `boxes_available`, `boxes_reserved`, and `status` are recomputed. | All operational roles |
| GET | /crayon-works/assortment-specs/{id}/retail-allocations | List the spec's retail allocations; optional `status` and `priority_tier` filters. | PlatformAdmin, AllocationPlanner |
| POST | /crayon-works/formulas | Create a formula; it starts `DRAFT`. | Formulator, SafetyOfficer |
| GET | /crayon-works/formulas/{id} | Get a formula by id. | All operational roles |
| POST | /crayon-works/formulas/{id}/transition | Drive the formula lifecycle: submit, approve, reject, or request revision, per §3.3. | Formulator, SafetyOfficer |
| GET | /crayon-works/formulas/{id}/safety-tests | List the formula's safety tests, ordered by creation time then `test_seq`; optional `status` filter. | All operational roles |
| GET | /crayon-works/formulas/{id}/licensed-lines | List the formula's licensed lines; optional `status` filter. | All operational roles |
| POST | /crayon-works/production-runs | Plan a production run against an `ACTIVE` spec with an approved formula per entry color, a certified recall-free batch, the licensed-line backing for `LICENSED` specs, and the sixty-day lead time. | PlatformAdmin |
| GET | /crayon-works/production-runs/{id} | Get a production run by id. | All operational roles |
| GET | /crayon-works/production-runs | List production runs, ordered by creation time then `run_seq`; optional `assortment_spec_id`, `pigment_batch_id`, and `stage` filters plus pagination. | All operational roles |
| POST | /crayon-works/production-runs/{id}/transition | Drive the run lifecycle: advance, hold, resume, or cancel, per §3.4; the packing advance takes `packed_counts` and evaluates the packing-accuracy gate. | PlatformAdmin |
| GET | /crayon-works/production-runs/{id}/inventory-lots | List the run's inventory lots; optional `status` filter. | All operational roles |
| POST | /crayon-works/retail-allocations | Request a seasonal retail allocation; computes the provisional waterfall share immediately; carries `expected_assortment_spec_version` per §2.7. | AllocationPlanner |
| GET | /crayon-works/retail-allocations/{id} | Get a retail allocation by id. | PlatformAdmin, AllocationPlanner |
| POST | /crayon-works/retail-allocations/{id}/decision | Commit, fulfill, or release the allocation, per §3.5. | AllocationPlanner |
| POST | /crayon-works/licensed-lines | Create a licensed or co-branded product line; it starts `DRAFT`. | BrandManager |
| GET | /crayon-works/licensed-lines/{id} | Get a licensed line by id; `projected_royalty_cents` is recomputed on read. | All operational roles |
| POST | /crayon-works/licensed-lines/{id}/transition | Drive the two-party approval workflow — submit, licensor and brand decisions, reinstate — per §3.6; every call carries `expected_formula_version` per §2.7. | BrandManager, Licensor |
| POST | /crayon-works/attraction-sessions | Schedule an experience-attraction session; same-venue same-date sessions occupy buffered half-open intervals that must not intersect. | PlatformAdmin |
| GET | /crayon-works/attraction-sessions/{id} | Get an attraction session by id. | All operational roles |
| GET | /crayon-works/attraction-sessions/{id}/tickets | List the session's tickets; optional `status` and `kind` filters. | PlatformAdmin, BoxOffice |
| POST | /crayon-works/tickets | Book an individual or school-group ticket; priced per the dynamic-pricing rule at confirmation, with non-fitting groups waitlisted. | BoxOffice |
| POST | /crayon-works/tickets/{id}/decision | Check in, refund, or cancel the ticket, per §3.7; refund frees capacity and triggers the waitlist promotion cascade. | BoxOffice |
| POST | /crayon-works/safety-tests/{id}/record-result | Record the lab outcome of a scheduled safety test as `PASSED` or `FAILED`. | LabTechnician |
| POST | /crayon-works/votes | Cast consumer ballots into an `OPEN` campaign; `count` imports multiple identical ballots and defaults to 1. | Consumer |
| POST | /_clock/set_current_utc | Set the logical clock to a supplied instant; the startup default is exactly `2026-09-01T00:00:00Z`. This endpoint lives outside the `/crayon-works` mount. | PlatformAdmin |
| POST | /crayon-works/ops/run-epoch | Advance the system epoch and process campaign openings, tallies, session closings, allocation expirations, recall progressions, and color archivals in the pinned order of §3.8. | PlatformAdmin |

## 5. Error Code Catalogue

Every error response uses the error envelope of §2.2. The trigger condition for each error is defined in the narrative of §2 and §3 where its guarded workflow lives; this catalogue is the identifier-to-status summary only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_SOD_VIOLATION | 403 |
| ERR_COLOR_NOT_ACTIVE | 409 |
| ERR_CAMPAIGN_NOT_OPEN | 409 |
| ERR_CAMPAIGN_WINDOW_CONFLICT | 409 |
| ERR_FORMULA_NOT_APPROVABLE | 409 |
| ERR_INVALID_FORMULA_STATE | 409 |
| ERR_BATCH_NOT_CERTIFIED | 409 |
| ERR_BATCH_TERMINAL | 409 |
| ERR_CERTIFICATION_MARK_REQUIRED | 409 |
| ERR_SPEC_DEPRECATED | 409 |
| ERR_SPEC_INVALID | 409 |
| ERR_RUN_STAGE_INVALID | 409 |
| ERR_RUN_ON_HOLD | 409 |
| ERR_SESSION_FULL | 409 |
| ERR_SESSION_CLOSED | 409 |
| ERR_SESSION_WINDOW_CONFLICT | 409 |
| ERR_TICKET_STATE | 409 |
| ERR_GROUP_TOO_LARGE | 422 |
| ERR_ALLOCATION_STATE | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_LICENSE_STATE | 409 |
| ERR_LICENSE_REQUIRED | 409 |
| ERR_STALE_PIN | 409 |
| ERR_LICENSE_TERM_WINDOW | 422 |
| ERR_RECALL_ACTIVE | 409 |
| ERR_VOTE_INVALID | 422 |
| ERR_DATE_ORDER | 422 |
| ERR_SEASON_WINDOW | 422 |
| ERR_PLANNED_START_TOO_SOON | 422 |
