# Television Series Development API — Product Requirements Document

## 1. Introduction

A broadcast network's development department runs on a paper trail that nobody trusts. Pitches arrive from agencies by email, coverage lives in a shared drive, the chain-of-title search sits with an outside lawyer, step-deal option dates are tracked on a whiteboard, and the only person who knows how much of the season's development money is actually spoken for is the one business-affairs executive who keeps a private spreadsheet. By the time a pilot is testing and the studio wants an answer on episode count and license fee, three departments are arguing from three different sets of numbers. This document specifies the service that replaces that spreadsheet.

The system tracks a project from the moment an agency submits a pitch against a **slate** — a platform-and-season container that carries both a development budget in dollars and an inventory of orderable episodes — through coverage, rights clearance, writer attachment on a step deal, pilot order with casting and location contingencies, audience testing, series-order negotiation with the studio, and finally a three-committee greenlight. Every commitment made along that path is charged against its slate the instant it is made and released the instant it is unwound, so that the slate's remaining capacity is always a fact rather than an estimate. Projects that die are written off explicitly, and the studio may buy them back through a turnaround with interest and a handling fee, which is the only way development dollars ever return to a slate.

Two product constraints shape almost every rule below. First, the department is deliberately organised around a separation of duties: creative, business affairs, finance, research and the studio counterparty each hold a distinct set of powers, and the final greenlight requires three different people from three different functions to sign. Second, every date-sensitive rule — option expiries, holding-deal terms, holdback windows, shoot windows, turnaround windows — is evaluated against a server-side **logical clock** rather than wall-clock time, so that a season's worth of development can be exercised deterministically in a test harness.

## 2. Global Specifications & System-Wide Principles

### 2.1. Identity, Roles and the Separation of Duties

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the function that principal is acting in. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined. If the supplied role is not one of the seven roles below, or is a valid role that is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The seven roles are:

- `PlatformAdmin` — network operations administrator. Registers agencies and opens slates, and is the only role permitted to drive the logical clock. Holds read access across every entity except the feasibility computation.
- `AgencyRep` — an agent submitting pitches and registering clients on behalf of exactly one agency. Pitch submission is exclusive to this role.
- `DevelopmentExec` — the creative executive. Covers pitches, advances them into development, reviews delivered script material, orders pilots, wraps pilot shoots, abandons projects, and casts the `CREATIVE` committee vote.
- `BusinessAffairs` — the deal-making arm. Files rights checks, writes holding deals and terminates them, executes step deals, exercises and cuts off options, opens series-order negotiations and counters from the network side, files greenlight requests, offers and exercises turnaround, and casts the `BUSINESS` committee vote.
- `FinanceController` — the finance officer. Reads slate economics and the feasibility computation, and casts the `FINANCE` committee vote.
- `ResearchAnalyst` — the audience-research analyst. Fields test screenings on wrapped pilots and certifies them.
- `StudioPartner` — the studio counterparty on a series order. Counters network offers and accepts standing network offers, and may read the negotiations of a project.

`AgencyRep` is the one role whose `X-User-ID` is entity-backed. When `X-User-Role` is `AgencyRep`, `X-User-ID` is the `id` of the acting `Agency`, and ownership checks compare the `agency_id` on the resource being touched to `X-User-ID`: the `agency_id` in a pitch submission payload, or the `agency_id` of the writer or pitch named in the path. A mismatch is rejected with `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403). This scope check guards six operations: submitting a pitch, reading one pitch, listing pitches, registering a writer, reading one writer, and listing writers.

For the other six roles — `PlatformAdmin`, `DevelopmentExec`, `BusinessAffairs`, `FinanceController`, `ResearchAnalyst` and `StudioPartner` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any row's `id`. The server does record it where a rule demands it: a greenlight committee vote stores the acting `X-User-ID` in `creative_decided_by_user_id`, `business_decided_by_user_id` or `finance_decided_by_user_id` according to the committee named, and those stored identifiers are what the separation-of-duties rule compares. One opaque identifier may record at most one committee decision on any single greenlight request; an attempt to record a second is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Two authorisation rules are finer-grained than the endpoint's role list. A greenlight decision naming the `CREATIVE` committee is only accepted from `DevelopmentExec`, `BUSINESS` only from `BusinessAffairs`, and `FINANCE` only from `FinanceController`; a mismatch is an `ERR_UNAUTHORIZED` rejection. And on a pilot contingency clearance, the `WAIVED` resolution is reserved to `BusinessAffairs` — a `DevelopmentExec` may record `SATISFIED` or `FAILED` only, and an attempt to waive is likewise `ERR_UNAUTHORIZED`.

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

### 2.3. Pagination and List Ordering

Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10, may be no smaller than 1 and no larger than 100. `offset` controls the starting position: it defaults to 0 and may not be negative. A value outside those ranges is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

List responses are ordered by `created_at` ascending — oldest row first — unless a specific endpoint states otherwise. The rights checks filed against a pitch, for instance, are returned newest last, which is exactly this default ordering.

Every list response carries four pagination fields inside `meta`, alongside `api_request_id` and `api_request_timestamp`: `limit` and `offset` echo the effective values used for the page, `total_count` reports how many rows matched the request's filters (not how many rows exist in the collection as a whole), and `has_more` is true exactly when `offset` plus the number of rows returned in `data` is still less than `total_count`. The page's rows themselves live in `data` with `response_type` set to "array".

### 2.4. The Logical Development Clock

Nothing in this system reads wall-clock time. A single server-side logical clock is the sole source of every server-stamped timestamp, every date comparison, and every window or expiry rule in the domain. Before the clock is ever set it reads exactly its startup default of `2026-08-01T00:00:00Z`, and it never falls back to real time under any circumstance.

A `PlatformAdmin` moves the clock by supplying a `to_iso8601` instant; the response body reports the new setting as `current_utc`. Moving the clock transitions nothing by itself — no entity changes state because time passed. What it changes is the answer that every clock-derived read gives from that point onward: a holding deal's `term_state`, a writer's `exclusivity_status`, a project's `turnaround_window_open` flag, whether a rights check's holdback window still blocks an advance, whether a step's option period is still open, whether a pilot's shoot window has elapsed, and how much recoupment an abandoned project has accrued. A rights check's own `result` is the exception: it is fixed at the moment the check is filed and is never revised by a later clock movement.

### 2.5. Common Resource Properties

Every persisted resource carries an `id`: a server-minted UUID with no type prefix and no client influence over its value. Alongside it, `created_at` records when the row was first written, as an ISO 8601 UTC timestamp with exactly three fractional digits (for example `2026-08-01T00:00:00.000Z`), stamped from the logical clock.

Most resources — agencies, slates, writers, holding deals, pitches, development projects, script deals, deal steps, pilot orders, test screenings, series-order negotiations and greenlight requests — additionally carry `updated_at` and `version`. `updated_at` is refreshed to the current logical-clock instant on every mutation of the row, in the same ISO 8601 UTC format. `version` is an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation, including mutations that only change a derived field. A cascade that touches three rows increments the `version` of all three.

The one exception is the rights check. A rights check is an immutable clearance record: it carries only `id` and `created_at`. It has no `updated_at` and no `version` at all, because nothing in the system ever modifies a filed clearance — a later search is filed as a new record instead.

### 2.6. Path Resolution and Referential Integrity

Identifiers in a URL path are resolved strictly left to right, and the first identifier that does not resolve determines the 404 response. A request naming a deal step under a script deal resolves the script deal first: if that deal does not exist the answer is `ERR_SCRIPT_DEAL_NOT_FOUND`, and only once the deal is found does the server look for the step. A step that exists but belongs to a different script deal than the one in the path is treated as not found for that path and answered with `ERR_DEAL_STEP_NOT_FOUND`. The same discipline applies to test screenings addressed beneath a pilot order.

Each entity has its own not-found code: `ERR_AGENCY_NOT_FOUND`, `ERR_SLATE_NOT_FOUND`, `ERR_WRITER_NOT_FOUND`, `ERR_HOLDING_DEAL_NOT_FOUND`, `ERR_PITCH_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_SCRIPT_DEAL_NOT_FOUND`, `ERR_DEAL_STEP_NOT_FOUND`, `ERR_PILOT_ORDER_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND` and `ERR_GREENLIGHT_NOT_FOUND`, all with HTTP status 404.

Foreign keys carried in a request body are resolved with the same codes. Any of `agency_id`, `slate_id`, `writer_id`, `project_id` or `negotiation_id` that names a row which does not exist produces that entity's not-found error. Path resolution and body-key resolution both happen before any state, business or fiscal rule is consulted.

### 2.7. Money, Basis Points and Rounding

All monetary amounts in this system are integer counts of cents, named with a `_cents` suffix, and are transmitted as JSON integers — never as strings and never as decimal fractions of a dollar. No money calculation anywhere in the system uses floating-point arithmetic. Wherever a monetary computation divides, the division discards any remainder: the result is the largest integer not greater than the true quotient. Wherever a computation takes the larger or smaller of two amounts, it does so on the integer cents directly. The ledgers described in §2.8 perform no rounding of any kind — they are pure sums and differences of integers.

Proportions are expressed in **basis points** — hundredths of a percent — and named with a `_bps` suffix, so 10000 basis points means one times the base quantity and 12500 means one and a quarter times it. Any computation that scales an amount by a basis-point figure multiplies first and divides by 10000 second, discarding the remainder. Percentages that are genuinely percentages, such as an ownership split, are plain integers from 0 to 100.

Only the audience-research scores are decimals, and they carry their own pinned precision. Each weighted score component is rounded half up to 2 decimal places, and only the rounded components are summed to form `weighted_raw_score`; the normalised figure `norm_adjusted_score` is rounded half up to 1 decimal place. A coverage score is a number from 0 to 100 with at most 1 decimal place, and a comparable-title norm index is a number from 50.0 to 150.0, also with at most 1 decimal place.

### 2.8. Slate Ledgers: Development Dollars and Episode Inventory

A slate is the only place in the system where scarcity lives, and it is scarce in two independent currencies. Both are recomputed on every write that could move them, and both are exposed on a slate read.

One project-level figure feeds both the ledger and the feasibility economics, so it belongs here too. A development project's `cumulative_dev_cost_cents` is the sum of `encumbered_cents` over every script deal whose `project_id` is this project — every one of them, whatever the deal's own `deal_status`, because the per-step filter inside `encumbered_cents` already carries all of the state logic — plus the sum of `budget_cents` over this project's pilot orders whose `production_status` is `ORDERED`, `GREEN_TO_SHOOT` or `WRAPPED`. A `COLLAPSED` pilot's budget leaves the figure entirely, which is why one pilot collapse simultaneously lowers a project's development cost and raises its slate's available budget in a single response. This number is recomputed after every deal-step transition, every script-deal transition and every pilot-order transition on the project.

The **dollar ledger** works as follows. `committed_dev_cents` is the sum of `encumbered_cents` over every script deal whose project belongs to this slate — with no filter on the deal's own status, because all of the state logic already lives inside `encumbered_cents` — plus the sum of `budget_cents` over every pilot order on this slate's projects whose `production_status` is `ORDERED`, `GREEN_TO_SHOOT` or `WRAPPED`. `reserved_holding_cents` is the sum of `annual_cost_cents` over the slate's holding deals whose `status` is `ACTIVE`. `writeoff_dev_cents` is the sum of `writeoff_cents` over the slate's projects whose `dev_status` is `ABANDONED`. `recouped_dev_cents` is the sum of `recoupment_paid_cents` over the slate's projects. From those four, `available_dev_cents` is `total_dev_budget_cents` less `committed_dev_cents`, less `reserved_holding_cents`, less `writeoff_dev_cents`, plus `recouped_dev_cents`.

That arithmetic is an invariant, not a suggestion: after every single request, `available_dev_cents` plus `committed_dev_cents` plus `reserved_holding_cents` plus `writeoff_dev_cents`, minus `recouped_dev_cents`, must equal `total_dev_budget_cents` exactly, with no drift. Because the input sets are state-filtered, releasing a commitment is automatic — terminating a holding deal removes its row from the `reserved_holding_cents` sum, collapsing a pilot removes its budget from the `committed_dev_cents` sum, and in both cases the released cents reappear in `available_dev_cents` in the very same response.

The **episode ledger** is the same idea in units of episodes. `reserved_episode_count` is the sum of `episode_count` over the slate's negotiations whose `status` is `NETWORK_OFFER` or `STUDIO_COUNTER`; `committed_episode_count` is the same sum over negotiations whose `status` is `AGREED`; a `WITHDRAWN` negotiation contributes to neither. `available_episode_count` is `episode_capacity` less `committed_episode_count` less `reserved_episode_count`, and the invariant here is that `episode_capacity` always equals `available_episode_count` plus `reserved_episode_count` plus `committed_episode_count`.

From the episode ledger the slate derives its trading `posture`, which is one of `OPEN`, `RESTRICTED` or `LOCKED`. The slate is `LOCKED` when `committed_episode_count` is greater than or equal to `episode_capacity`. Otherwise, take `committed_episode_count` plus `reserved_episode_count`, multiply by 10000, divide by `episode_capacity` discarding the remainder, and compare the result against 6000 basis points — that is, against sixty percent utilisation: at 6000 or above the slate is `RESTRICTED`, and below it the slate is `OPEN`. The boundary is inclusive on the restricted side, so a slate whose committed and reserved episodes come to exactly sixty percent of capacity is `RESTRICTED`. A newly opened slate has nothing committed and nothing reserved, so its `posture` starts `OPEN`. A `LOCKED` slate takes no new development, pilot or series commitment at all, and the attempt is answered with `ERR_SLATE_POSTURE_LOCKED` (HTTP 409).

### 2.9. Stale-Read Protection on Filed Requests

Two writes in this system are legitimate under the product rules yet destructive to something the client may not have seen, and both are therefore guarded by optimistic concurrency control against the version of a parent row.

Filing a greenlight request — a `POST /greenlight-requests` — must carry `expected_project_version`, a required and never-optional field holding the `version` of the `DevelopmentProject` the client last observed. Filing a request legitimately supersedes whatever request was still open on that project, so the write itself is permitted; the version check is what identifies a filer whose picture of the project — its term sheet, its already-superseded request, the committee votes recorded on it — is out of date. If `expected_project_version` does not equal the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

Fielding a test screening — a `POST /pilot-orders/{id}/test-screenings` — must likewise carry `expected_pilot_order_version` as a required, never-optional field, holding the `version` of the `PilotOrder` the client last observed. Fielding a new screening legitimately invalidates the pilot's earlier screenings, so again the write is permitted; the version check identifies a researcher who has not seen a screening that already superseded the one they believe is current. A mismatch against the pilot order's current `version` is rejected with `ERR_STALE_PILOT_ORDER_VERSION` (HTTP 412).

No other endpoint takes a version field. Every other write is admitted or refused purely on the state and business rules that govern it.

### 2.10. Cascades and Cross-Aggregate Consistency

Several operations in this domain deliberately reach beyond the row named in the path, and the specification treats those reaches as ordered links in a chain rather than as incidental bookkeeping. Three chains matter enough to name here, and each is spelled out in full where its workflow is described: resolving a pilot contingency to `FAILED` collapses the pilot, returns its project to active development and releases the pilot's budget on the slate; the third approving committee vote on a greenlight request orders the series, completes the project's live script deals, cuts off their pending steps and releases that money on the slate; and abandoning a project freezes its write-off first and then unwinds its deals, its steps, its open negotiations and its live pilots.

Two consequences hold for every cascade. Every row the cascade touches has its `updated_at` refreshed and its `version` incremented, including the slate whose ledgers moved. And the ordering of links is significant whenever a later link reads a value the earlier link wrote — most sharply in abandonment, where the write-off snapshot must be taken before any deal is terminated, because terminating the deals is precisely what drives the project's cost to zero.

### 2.11. The Order in Which a Request Is Refused

Validation is strictly ordered. The first rule whose condition is violated determines the response, and no later rule is evaluated — so a request that offends three rules always reports the earliest of the three. The full order is:

1. Both `X-User-ID` and `X-User-Role` are present and non-empty, else `ERR_UNAUTHENTICATED`.
2. `X-User-Role` names one of the seven roles and that role is authorised on the target endpoint, else `ERR_UNAUTHORIZED`.
3. An `AgencyRep`'s `X-User-ID` matches the `agency_id` of the agency the request touches, else `ERR_AGENCY_SCOPE_VIOLATION`.
4. A greenlight decision's `committee` matches the acting role, else `ERR_UNAUTHORIZED`.
5. A contingency clearance whose `resolution` is `WAIVED` comes from `BusinessAffairs`, else `ERR_UNAUTHORIZED`.
6. The acting `X-User-ID` has not already decided another committee on this greenlight request, else `ERR_SEGREGATION_OF_DUTIES`.
7. Every identifier in the path exists, resolved left to right, else that entity's not-found code.
8. Every foreign key in the body resolves, and a nested identifier belongs to its path parent, else that entity's not-found code.
9. The request body is well formed: required fields present, enum values drawn from their declared sets, integers non-negative where the field demands it, panel scores within 0 to 100, the comparable-title norm index greater than zero, ownership percentages within 0 to 100, dates in ISO 8601 form, the steps array holding between 1 and 6 entries each with a valid step type and a non-negative fee, and the guaranteed step count between 1 and the number of submitted steps — else `ERR_INVALID_REQUEST`.
10. The pitch is in a status that permits the operation, else `ERR_INVALID_PITCH_STATE`.
11. The development project is in a `dev_status` that permits the operation, else `ERR_INVALID_PROJECT_STATE`.
12. The script deal is still `EXECUTED`, else `ERR_INVALID_DEAL_STATE`.
13. The deal step is in the status its operation requires, and for an exercise every lower-indexed step is already accepted or cut off, else `ERR_INVALID_DEAL_STEP_STATE`.
14. The pilot order's `production_status` permits the operation, else `ERR_INVALID_PILOT_ORDER_STATE`.
15. The contingency dimension named by `kind` is still pending, else `ERR_CONTINGENCY_ALREADY_RESOLVED`.
16. The test screening is still `FIELDED`, else `ERR_INVALID_SCREENING_STATE`.
17. The negotiation is still open, or the negotiation named in a greenlight request is `AGREED`, else `ERR_INVALID_NEGOTIATION_STATE`.
18. The greenlight request is still `OPEN`, else `ERR_INVALID_GREENLIGHT_STATE`.
19. The named committee has not yet decided, else `ERR_COMMITTEE_ALREADY_DECIDED`.
20. The accepting side is not the side that tabled the standing offer, else `ERR_ACCEPT_BY_OFFERING_SIDE`.
21. `expected_project_version` equals the project's current `version`, else `ERR_STALE_PROJECT_VERSION`.
22. `expected_pilot_order_version` equals the pilot order's current `version`, else `ERR_STALE_PILOT_ORDER_VERSION`.
23. A pitch carrying packaging elements comes from an agency permitted to package, else `ERR_PACKAGING_NOT_PERMITTED`.
24. The pitch's rights are clear, else `ERR_RIGHTS_NOT_CLEAR`.
25. The writer is not exclusive to another slate, else `ERR_WRITER_EXCLUSIVITY_CONFLICT`.
26. No guaranteed step is being cut, else `ERR_GUARANTEED_STEP_NOT_CUTTABLE`.
27. The screening's panel is large enough to certify, else `ERR_TEST_SAMPLE_TOO_SMALL`.
28. The underlying IP is free of holdback today, else `ERR_RIGHTS_HOLDBACK_CONFLICT`.
29. The writer has no overlapping active holding deal, else `ERR_HOLDING_DEAL_OVERLAP`.
30. The step's option period has not expired, else `ERR_OPTION_PERIOD_EXPIRED`.
31. The pilot's shoot window has elapsed, else `ERR_SHOOT_WINDOW_NOT_ELAPSED`.
32. The turnaround window is still open, else `ERR_TURNAROUND_WINDOW_CLOSED`.
33. The slate's `posture` is not `LOCKED`, else `ERR_SLATE_POSTURE_LOCKED`.
34. The writer's open-step load stays within its ceiling, else `ERR_WRITER_STEP_LOAD_EXCEEDED`.
35. The step has notes rounds left, else `ERR_NOTES_ROUNDS_EXHAUSTED`.
36. The negotiation has rounds left, else `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`.
37. The term sheet is internally coherent, else `ERR_TERM_SHEET_INVALID`.
38. The license fee is at or below the slate's cap, else `ERR_LICENSE_FEE_ABOVE_CAP`.
39. The pilot budget is within tolerance of the pattern budget, else `ERR_PILOT_BUDGET_ABOVE_PATTERN`.
40. The slate has a free pilot shoot window, else `ERR_STAGE_CAPACITY_EXCEEDED`.
41. The agency has submissions left in its allotment, else `ERR_AGENCY_SUBMISSION_CAP_REACHED`.
42. The negotiation named in a greenlight request belongs to the project named in the same request, else `ERR_NEGOTIATION_PROJECT_MISMATCH`.
43. The project has a certified test screening, else `ERR_NO_CERTIFIED_TEST`.
44. That screening's normalised score clears the floor, else `ERR_TEST_SCORE_BELOW_FLOOR`.
45. The slate's available development dollars cover the new commitment, else `ERR_SLATE_DEV_BUDGET_EXCEEDED`.
46. The slate's available episodes cover the reservation, else `ERR_EPISODE_CAPACITY_EXCEEDED`.
47. A finance approval's feasibility verdict is favourable, else `ERR_FEASIBILITY_FAILED`.

The shape of that ordering is worth internalising, because it is what makes error reporting predictable: authentication and authorisation first, then existence, then request shape, then state preconditions, then the two version checks, then rights and talent-safety rules, then temporal windows, then capacity and coherence constraints, and fiscal checks last of all. A pitch advance that is simultaneously rights-encumbered and aimed at a locked slate reports `ERR_RIGHTS_NOT_CLEAR`, not `ERR_SLATE_POSTURE_LOCKED`. A script deal against a writer held by another slate on a slate with no money left reports `ERR_WRITER_EXCLUSIVITY_CONFLICT`, not `ERR_SLATE_DEV_BUDGET_EXCEEDED`.

## 3. Business Logic & Workflows

### 3.1. The Standing Registry: Slates, Agencies and Writers

Before a single pitch can be read, a `PlatformAdmin` must open at least one slate. A slate names the `platform` whose economics govern it — one of `BROADCAST`, `CABLE` or `STREAMING` — and the `season_year` it serves, which must be an integer from 2026 through 2035. Its dollar side is set by `total_dev_budget_cents`, which may be zero or more, and its per-episode economics by `pattern_budget_per_episode_cents` (the benchmark production budget the network believes an episode of this kind costs, which must be greater than zero), `license_fee_cap_per_episode_cents` (the most the network may ever commit per episode, greater than zero) and `max_deficit_per_episode_cents` (the largest per-episode deficit the network is still willing to call feasible, zero or more). Its episode side is set by `episode_capacity`, the total episode inventory orderable in that season, which must be at least 1, and `default_episode_count`, the episode count feasibility reads assume when the caller does not name one, also at least 1. Two ceilings complete the picture: `max_backend_points_bps`, the ceiling on backend participation grantable in a series order, expressed in basis points from 0 to 10000, and `max_concurrent_pilot_shoots`, the number of pilot shoot windows that may overlap on this slate's stages, at least 1. All of the ledger figures described in §2.8 start at zero on a fresh slate.

An agency is registered with its legal `name` (non-blank, at most 120 characters) and an `agency_code` — a short trading code of 2 to 6 uppercase letters A through Z which must be unique across every agency on the system. Its standing with the network is the `relationship_tier`, one of `PREMIER`, `STANDARD` or `PROBATION`. Whether the agency may attach packaged elements to its pitches is the boolean `packaging_allowed`, which defaults to false when the field is omitted. Its baseline allotment is `annual_submission_cap`, an integer of at least 1.

The allotment the agency actually gets is `effective_submission_cap`, and the tier bends it. An agency on `PROBATION` is cut to a single submission per season regardless of what its baseline says — the probation ceiling is 1. An agency at `PREMIER` gets its `annual_submission_cap` plus a premier bonus of 2 further submissions. A `STANDARD` agency gets exactly its `annual_submission_cap`. Against that ceiling stands `submissions_used_count`, which counts the agency's own pitches whose `status` is `SUBMITTED`, `COVERED` or `ADVANCED` and whose slate has the same `season_year` as the slate named in the request currently being evaluated — so an agency's allotment is per season, not global, and a pitch on a 2027 slate does not consume any part of the 2028 allotment. A pitch the network has passed on is forgiven: a `PASSED` pitch stops counting immediately, which frees a slot the moment coverage is recorded. A newly registered agency has used nothing, so `submissions_used_count` begins at 0. The cap is enforced with a greater-than-or-equal comparison — a further submission is refused with `ERR_AGENCY_SUBMISSION_CAP_REACHED` as soon as `submissions_used_count` has reached `effective_submission_cap`, which makes the cap-th pitch the last one accepted.

Writers are registered either by a `PlatformAdmin` or by the `AgencyRep` of the agency that represents them, with a `full_name` (non-blank, at most 120 characters), the `agency_id` of that representing agency, a `guild_minimum_tier` of either `LOW` or `HIGH`, and a `quote_per_step_cents` of zero or more. The quote is the writer's asking price per step and is recorded for reference only — no calculation in this system reads it. Two figures on a writer are computed rather than supplied: `exclusivity_status`, which is `HOLDING_DEAL` when at least one holding deal naming this writer is simultaneously `ACTIVE` in status and `IN_TERM` in term state, and `FREE` otherwise; and `open_step_count`, the number of deal steps across all of the writer's script deals whose status is `EXERCISED`, `DELIVERED` or `NOTES_ISSUED`. A brand-new writer is `FREE` with an `open_step_count` of 0. The writer list may be narrowed to one `agency_id`, to one `exclusivity_status`, or both, and paged with `limit` and `offset`.

### 3.2. Pitch Intake: Coverage, Clearance and Advancement

An `AgencyRep` submits a pitch naming its own `agency_id`, the `slate_id` it targets, a working `title` (non-blank, at most 160 characters) and a `logline` (non-blank, at most 600 characters). Two optional inputs shape what happens next. `packaging_elements` is an array of the talent, directors and showrunners the agency has attached to the pitch — non-blank strings, at most 6 of them, defaulting to an empty array when omitted — and an agency whose `packaging_allowed` is false may not submit a pitch that carries any at all, which is refused with `ERR_PACKAGING_NOT_PERMITTED`. `underlying_ip_key` is the canonical key of the source material when the pitch is an adaptation: either null, which is the default, or a non-blank string of at most 80 characters. Underlying-IP keys are compared case-sensitively everywhere they are compared, so `MIDNIGHT_LINE` and `midnight_line` are different properties. A fresh pitch has `status` `SUBMITTED`, a `coverage_round` of 0, and a null `coverage_score` and null `recommendation`.

Coverage is the creative read, and only a `DevelopmentExec` records one. The payload carries a `coverage_score` — a number from 0 to 100 with at most 1 decimal place — and a `recommendation` of either `ADVANCE` or `PASS`. Each coverage write overwrites `coverage_score` and `recommendation` with what was submitted and increments `coverage_round` by 1, so `coverage_round` is a count of how many reads a pitch has had rather than a version of any one read. A recommendation of `ADVANCE` on a `SUBMITTED` pitch moves it `SUBMITTED → COVERED`; on a pitch that is already `COVERED` it is a self-loop, leaving the pitch `COVERED` while overwriting the score and incrementing the round, and development may re-cover a pitch this way any number of times. A recommendation of `PASS` moves the pitch to `PASSED` from either `SUBMITTED` or `COVERED`, and `PASSED` is terminal: a passed pitch can never be re-covered and can never be advanced. Coverage is therefore only accepted while the pitch is `SUBMITTED` or `COVERED`; anything else is `ERR_INVALID_PITCH_STATE`.

Clearance runs on a separate track, filed by `BusinessAffairs` against the pitch. A rights check records the `underlying_ip_key` being cleared (non-blank, at most 80 characters), the `chain_of_title_status` that the search returned — one of `CLEAN`, `DISPUTED` or `UNKNOWN` — and the exclusive holdback window the seller has asked for, as `holdback_start_date` and `holdback_end_date` in `YYYY-MM-DD` form, with the end on or after the start. That window is a closed interval: both endpoints are inside it. The record also carries the `pitch_id` of the pitch it belongs to. Two values are computed at filing. `quiet_period_end_date` extends the window by a quiet buffer of 90 calendar days beyond `holdback_end_date`, inclusive, and `result` maps the title search onto a clearance verdict: `CLEAN` yields `CLEAR`, `DISPUTED` yields `ENCUMBERED`, and `UNKNOWN` yields `BLOCKED`. A `result` is fixed at the instant of filing and is never revised; a later, better search is filed as a new record, and it is the newest record that governs.

Advancing a pitch is the act that creates a development project, and it is reserved to `DevelopmentExec`. Four gates stand in front of it, and they are evaluated in exactly this order. First the pitch must be `COVERED`, and its standing `recommendation` must be `ADVANCE` — a `SUBMITTED`, `PASSED` or already `ADVANCED` pitch is refused with `ERR_INVALID_PITCH_STATE`. Second, the pitch must have at least one rights check on file and the most recent one, meaning the one with the highest `created_at`, must have `result` `CLEAR`; a pitch with no clearance at all, or one whose newest clearance came back `ENCUMBERED` or `BLOCKED`, is refused with `ERR_RIGHTS_NOT_CLEAR`. Third, the underlying property must actually be free today: if the logical clock's current date falls anywhere inside that newest check's closed holdback interval from `holdback_start_date` through `holdback_end_date`, or anywhere in the quiet buffer that runs through `quiet_period_end_date` inclusive, the advance is refused with `ERR_RIGHTS_HOLDBACK_CONFLICT` even though the title itself is clean. Fourth, the target slate's `posture` must not be `LOCKED`, else `ERR_SLATE_POSTURE_LOCKED`.

When all four gates pass, the pitch moves `COVERED → ADVANCED` — also terminal — and a development project is created in the same request. The new project copies `pitch_id` from the pitch it came from, `slate_id` from the pitch's target slate, and `title` from the pitch's working title. It starts with `dev_status` `ACTIVE_DEVELOPMENT`, `turnaround_status` `NONE`, a null `predecessor_project_id` because it is not a turnaround successor, and a `cumulative_dev_cost_cents` of 0. The slate's `version` is incremented by 1 as well, because the set of projects hanging off it has changed. The created project — not the pitch — is what the response returns. Projects may afterwards be listed and narrowed by originating `pitch_id`, by `slate_id`, by `predecessor_project_id`, or by `dev_status`.

### 3.3. Holding Deals and Writer Exclusivity

A holding deal takes a writer off the market for a term and charges the cost to a slate. `BusinessAffairs` writes one by naming the `writer_id` being held, the `slate_id` whose development budget funds the hold, the `annual_cost_cents` (which must be greater than zero), and the term as `term_start_date` and `term_end_date`, both in `YYYY-MM-DD` form, with the end strictly after the start. The term is half-open: it covers the start date and every date up to but not including the end date. That detail is what makes back-to-back holds legal — one term ending on exactly the date the next begins does not overlap it.

The term drives a computed `term_state` read against the logical clock's current date: `PENDING_START` while today is before `term_start_date`, `IN_TERM` while today is on or after `term_start_date` and still before `term_end_date`, and `EXPIRED` once today has reached `term_end_date`. A deal's own `status` is a separate matter: it is `ACTIVE` from creation, becomes `TERMINATED` when it is torn up, and `termination_reason` is null for as long as the deal remains `ACTIVE`.

Two checks guard creation. The writer must not already have another `ACTIVE` holding deal whose half-open term intersects the requested term, else `ERR_HOLDING_DEAL_OVERLAP`; and the funding slate's `available_dev_cents` must be at least the `annual_cost_cents` being asked, else `ERR_SLATE_DEV_BUDGET_EXCEEDED`. On success the slate's `reserved_holding_cents` rises by `annual_cost_cents`, which lowers `available_dev_cents` by exactly the same amount, the writer's `exclusivity_status` is recomputed — it becomes `HOLDING_DEAL` as soon as the term contains the clock date — and both the slate's `version` and the writer's `version` are incremented by 1.

Termination is the exact compensating move, and `BusinessAffairs` performs it with a `termination_reason`. The deal must still be `ACTIVE`. It moves `ACTIVE → TERMINATED`, records the supplied reason, and its `annual_cost_cents` leaves `reserved_holding_cents`, restoring `available_dev_cents` to the cent — the create/terminate pair introduces no drift into the slate ledger. The writer's `exclusivity_status` falls back to `FREE` unless some other `ACTIVE`, in-term hold still covers them, and again both the slate's `version` and the writer's `version` are incremented by 1. `TERMINATED` is the deal's terminal state. Holding deals may be listed and narrowed by `writer_id`, by `slate_id`, or by `status`.

Exclusivity has teeth on the deal-making side rather than here. A writer whose `exclusivity_status` is `HOLDING_DEAL` may take a script deal only on a project belonging to the slate that holds them: an attempt to attach them to a project on any other slate is refused with `ERR_WRITER_EXCLUSIVITY_CONFLICT`. Concretely, the deal is refused when the writer has any holding deal that is `ACTIVE`, is `IN_TERM`, and names a slate other than the project's slate. A writer whose hold is `PENDING_START` or `EXPIRED`, or whose hold has been terminated, is free to be attached anywhere.

### 3.4. Step Deals: the Guaranteed Floor, the Option Ladder and the Notes Cycle

A script deal is how a writer is attached to a development project. `BusinessAffairs` executes one by naming the `project_id` and the `writer_id`, then describing the writing ladder: `steps` is an array of between 1 and 6 entries submitted in the order they are to be written, each entry carrying a `step_type` of `STORY`, `FIRST_DRAFT`, `REVISION` or `POLISH` and a `fee_cents` of zero or more. `guaranteed_step_count` says how many of the leading steps the network guarantees; it must be at least 1 and no more than the number of steps submitted. `option_period_days`, an integer from 1 to 365, sets how long each step's option runs.

Materialising the deal creates one deal step per submitted entry, in submitted order, with `step_index` running from 1 upward, each carrying the `script_deal_id` of its parent deal, a `status` of `PENDING`, a `notes_round` of 0, and null `exercised_at`, `delivered_at` and `accepted_at` stamps. Each step's `option_expires_at` is the deal's own `created_at` plus its `step_index` multiplied by `option_period_days` days — so on a deal with a 30-day option period, step 1 expires 30 days after execution, step 2 sixty days after, step 3 ninety days after, and the ladder walks outward from a single anchor rather than from each step's own exercise. The deal itself is created with `deal_status` `EXECUTED`, and its `step_count` simply reports how many steps it carries.

Fees are floored by the guild before any money is counted. Each `step_type` has a guild minimum: a `STORY` step is 3,500,000 cents, a `FIRST_DRAFT` 5,500,000 cents, a `REVISION` 2,500,000 cents and a `POLISH` 1,500,000 cents — thirty-five, fifty-five, twenty-five and fifteen thousand dollars respectively. That base is scaled by the writer's tier factor in basis points, which is 10000 for a `LOW` `guild_minimum_tier` and 12500 for `HIGH`: multiply the base by the factor, divide by 10000, and discard the remainder. A step's `effective_fee_cents` is then the greater of the submitted `fee_cents` and that scaled guild floor. A `HIGH`-tier writer's `STORY` step therefore cannot be worth less than 4,375,000 cents no matter what fee was negotiated, while a submitted fee above the floor is honoured as submitted.

From the effective fees the deal derives three sums, and the difference between them is the whole economic point of a step deal. `guaranteed_commitment_cents` is the total of `effective_fee_cents` over the steps whose `step_index` is less than or equal to `guaranteed_step_count`, counted regardless of what status those steps are in — this is the contractual floor, the money the network owes even if it cuts the writer off at the first opportunity. `full_option_exposure_cents` is the total of `effective_fee_cents` over every step of the deal without exception — the worst case if every option is exercised — and so it is always at least the guaranteed figure and strictly larger whenever the deal has any optional step at all. `encumbered_cents` is the money the slate is actually carrying at this moment, and it filters differently on either side of the guarantee line: a step whose `step_index` is at or below `guaranteed_step_count` counts as long as its status is anything other than `CUT_OFF`, while a step above that line counts only once its status is `EXERCISED`, `DELIVERED`, `NOTES_ISSUED` or `ACCEPTED`. A guaranteed step is money owed from execution onward; an optional step is money owed only once its option is exercised; and `CUT_OFF` always releases, on either side of the line. A deal whose optional steps are all still `PENDING` therefore has an `encumbered_cents` exactly equal to its `guaranteed_commitment_cents`.

Three gates guard execution, in this order: the project must be in `dev_status` `ACTIVE_DEVELOPMENT` or `SCRIPT_COMPLETE`, else `ERR_INVALID_PROJECT_STATE`; the writer must not be held exclusive by another slate, as described in §3.3; and the slate's `available_dev_cents` must cover the deal's `guaranteed_commitment_cents`, else `ERR_SLATE_DEV_BUDGET_EXCEEDED`. On success the slate's `committed_dev_cents` rises by the deal's `encumbered_cents` — which at creation is the guaranteed commitment — `available_dev_cents` falls by the same amount, the project's `cumulative_dev_cost_cents` rises accordingly, and both the project's `version` and the slate's `version` are incremented by 1. Deals may be listed and narrowed by `project_id`, `writer_id` or `deal_status`, and a deal's steps may be listed in `step_index` order with their effective fees and option expiries.

Exercising an option is exclusive to `BusinessAffairs` and moves a step `PENDING → EXERCISED`, stamping `exercised_at` from the logical clock. Five conditions apply. The step must be `PENDING` and every step with a lower `step_index` on the same deal must already be `ACCEPTED` or `CUT_OFF` — the ladder is climbed in order — else `ERR_INVALID_DEAL_STEP_STATE`. The deal must still be `EXECUTED`, since a `COMPLETED`, `CUT_OFF` or `TERMINATED` deal has frozen steps, else `ERR_INVALID_DEAL_STATE`. The logical clock's current instant must be strictly before the step's `option_expires_at`; an exercise at exactly `option_expires_at` is one instant too late and is refused with `ERR_OPTION_PERIOD_EXPIRED`. And the writer must have room on their desk: a writer may carry at most two open steps at once across every deal they are on, so an exercise is refused with `ERR_WRITER_STEP_LOAD_EXCEEDED` unless the writer's `open_step_count` is below 2 before the exercise. On success `open_step_count` rises by 1. If the exercised step is optional — its `step_index` above `guaranteed_step_count` — its `effective_fee_cents` newly enters `encumbered_cents`, so the slate's `committed_dev_cents` rises, `available_dev_cents` drops, and the project's `cumulative_dev_cost_cents` rises by the same figure; if the step was guaranteed, it was already encumbered at execution and neither ledger moves. The step's own `version`, the deal's `version`, the project's `version` and the slate's `version` are each incremented by 1.

Delivery is recorded by either `BusinessAffairs` or `DevelopmentExec`, and it works from two starting points: a step that is `EXERCISED` moves `EXERCISED → DELIVERED`, and a step that is `NOTES_ISSUED` moves `NOTES_ISSUED → DELIVERED` as a redelivery. Either way `delivered_at` is stamped, or overwritten, with the current logical-clock instant, and `notes_round` is left untouched. Any other starting status is `ERR_INVALID_DEAL_STEP_STATE`.

Review is the creative executive's call and only a `DevelopmentExec` makes it, on a step that is `DELIVERED`. The payload carries an `outcome` and, optionally, a `notes_summary`. An `outcome` of `NOTES` moves the step `DELIVERED → NOTES_ISSUED` and increments `notes_round` by 1; because a step may carry at most two notes rounds, a third is refused with `ERR_NOTES_ROUNDS_EXHAUSTED` once `notes_round` has reached 2. The pair `NOTES_ISSUED → DELIVERED → NOTES_ISSUED` may therefore cycle until that ceiling is hit. An `outcome` of `ACCEPT` moves the step `DELIVERED → ACCEPTED`, stamps `accepted_at`, and drops the writer's `open_step_count` by 1, freeing capacity on their desk. Acceptance also bubbles up: when every step with a `step_index` at or below `guaranteed_step_count` has reached `ACCEPTED` and the project is still in `ACTIVE_DEVELOPMENT`, the project moves `ACTIVE_DEVELOPMENT → SCRIPT_COMPLETE` and its `version` is incremented, alongside the step's own `version` and the deal's.

That completion is reversible, which is the one genuinely cyclic corner of the development lifecycle. Exercising an optional step — one above the guarantee line — on a project that has already reached `SCRIPT_COMPLETE` pushes the project back `SCRIPT_COMPLETE → ACTIVE_DEVELOPMENT`, because there is live writing outstanding again. Accepting that step then returns the project to `SCRIPT_COMPLETE`, and the pair may repeat for as many optional steps as the ladder holds.

Cutting the writer off closes the deal early. `BusinessAffairs` submits a `cutoff_reason` on a deal that is still `EXECUTED`. A guaranteed step is never cuttable, individually or by this deal-level action, so the whole operation is refused with `ERR_GUARANTEED_STEP_NOT_CUTTABLE` while any step at or below `guaranteed_step_count` is still `PENDING`. When it is permitted, every remaining `PENDING` step moves to `CUT_OFF`, the deal moves `EXECUTED → CUT_OFF`, and the released fees leave `encumbered_cents`, so the slate's `committed_dev_cents` drops, the project's `cumulative_dev_cost_cents` drops, and `available_dev_cents` and `posture` are recomputed. The deal's `version`, the project's `version` and the slate's `version` are each incremented by 1. `CUT_OFF` is the only terminal state a step has, and it is reachable in three ways: this deal-level cutoff, the system cascade when a deal is completed by a series order, and the system cascade when a deal is terminated by an abandonment. The ledger effect of a single cut differs by side of the guarantee line: cutting a guaranteed step removes its `effective_fee_cents` from `encumbered_cents` and therefore lowers `committed_dev_cents`, whereas cutting an optional step that was still `PENDING` moves no money at all, because an unexercised option was never encumbered in the first place.

### 3.5. Pilot Orders and the Two Contingency Dimensions

A pilot order is placed by a `DevelopmentExec` on a project that has reached `SCRIPT_COMPLETE`, and it names the `project_id`, the approved `budget_cents` (greater than zero), the shoot window as `shoot_start_date` and `shoot_end_date` in `YYYY-MM-DD` form with the end on or after the start, and two contingency deadlines, `casting_deadline_date` and `location_deadline_date`, recorded as the dates by which each contingency is expected to be resolved. The shoot window is a closed interval covering both endpoints.

Four business gates apply beyond the project's state, and they are consulted in this order: the slate's `posture` must not be `LOCKED` (`ERR_SLATE_POSTURE_LOCKED`); the budget must sit within tolerance of the slate's pattern budget (`ERR_PILOT_BUDGET_ABOVE_PATTERN`); the slate must have a free stage window (`ERR_STAGE_CAPACITY_EXCEEDED`); and the slate's `available_dev_cents` must cover the `budget_cents` (`ERR_SLATE_DEV_BUDGET_EXCEEDED`). Tolerance is measured by `budget_variance_bps`, computed as the pilot's `budget_cents` less the slate's `pattern_budget_per_episode_cents`, multiplied by 10000, divided by that same pattern budget with the remainder discarded — a figure that is negative for a pilot cheaper than pattern. The pilot is refused when `budget_variance_bps` exceeds 1500 basis points, so a pilot may run up to fifteen percent over the slate's pattern budget and no further. Stage capacity counts how many pilot orders the slate already has whose `production_status` is `ORDERED` or `GREEN_TO_SHOOT`; that running count, including the new order, may not exceed `max_concurrent_pilot_shoots`.

A new pilot order starts with `production_status` `ORDERED`, `casting_status` `PENDING`, `location_status` `PENDING` and a null `collapsed_reason`. Its project moves `SCRIPT_COMPLETE → PILOT_ORDERED`. The slate's `committed_dev_cents` rises by `budget_cents` and `available_dev_cents` falls by the same amount, which may change `posture`; the project's `cumulative_dev_cost_cents` rises by the same figure; and both the project's `version` and the slate's `version` are incremented by 1. A project's pilot orders can be listed afterwards, collapsed ones included.

`casting_status` and `location_status` are genuinely independent dimensions on the same row — either may be resolved first, and neither constrains the other's value. Both take the same four values, `PENDING`, `SATISFIED`, `WAIVED` and `FAILED`. A clearance is recorded by a `DevelopmentExec` or by `BusinessAffairs` and names the `kind` being resolved — `CASTING` or `LOCATION` — the `resolution` being recorded, and an optional `note`. As §2.1 states, only `BusinessAffairs` may record a `WAIVED` resolution. The pilot must be in `production_status` `ORDERED` or `GREEN_TO_SHOOT` for a clearance to be accepted at all, else `ERR_INVALID_PILOT_ORDER_STATE`, and the dimension named by `kind` must still be `PENDING`, else `ERR_CONTINGENCY_ALREADY_RESOLVED`.

The third, production dimension is never set directly; it derives from the other two. Resolving one dimension while the other is still `PENDING` sets that dimension and leaves `production_status` at `ORDERED` — a self-loop, in effect. Resolving the last `PENDING` dimension such that `casting_status` is `SATISFIED` or `WAIVED` and `location_status` is likewise `SATISFIED` or `WAIVED` auto-advances the pilot `ORDERED → GREEN_TO_SHOOT` in the same request, and the pilot's `version` is incremented by 1. A mixture of `SATISFIED` on one dimension and `WAIVED` on the other is as green as two satisfactions.

A resolution of `FAILED` collapses the pilot, and this is a three-link cascade. The named dimension is set to `FAILED`, `production_status` becomes `COLLAPSED`, and `collapsed_reason` records the kind of contingency that failed — the string `CASTING` or `LOCATION`. Because of that first link, the project falls back `PILOT_ORDERED → ACTIVE_DEVELOPMENT`, its script development effectively reopened. Also because of that first link, the pilot's `budget_cents` leaves the slate's `committed_dev_cents` — a `COLLAPSED` pilot is outside the set of statuses the dollar ledger counts — so `available_dev_cents` rises by the full budget and `posture` is recomputed. The pilot's `version`, the project's `version` and the slate's `version` are each incremented by 1. A `FAILED` resolution collapses the pilot from `ORDERED` and from `GREEN_TO_SHOOT` alike, with identical effects in both cases. `COLLAPSED` is terminal.

Wrapping the shoot is a `DevelopmentExec` action on a pilot that is `GREEN_TO_SHOOT`; from any other production status it is `ERR_INVALID_PILOT_ORDER_STATE`. It additionally requires that the logical clock's current date be on or after the pilot's `shoot_end_date` — a wrap filed while the shoot window is still running is refused with `ERR_SHOOT_WINDOW_NOT_ELAPSED`. On success the pilot moves `GREEN_TO_SHOOT → WRAPPED`, which is also terminal, and the project moves `PILOT_ORDERED → PILOT_DELIVERED`. Both the pilot's `version` and the project's `version` are incremented by 1. A `WRAPPED` pilot keeps its `budget_cents` in the slate's `committed_dev_cents`: the money was spent, and only a collapse or an abandonment ever takes it back out.

### 3.6. Testing and Research on a Wrapped Pilot

Research is fielded only by a `ResearchAnalyst`, and only on a pilot whose `production_status` is `WRAPPED` — on any other production status the request is refused with `ERR_INVALID_PILOT_ORDER_STATE`. The screening carries the `pilot_order_id` of the pilot that was screened, the `panel_size` (at least 1 respondent), three raw integer scores from 0 through 100 — `overall_score` for overall opinion, `intent_to_view_score` for stated intent, and `appeal_score` for lead appeal — and a `comp_norm_index`, the comparable-title norm the raw result is adjusted against, a number from 50.0 to 150.0 with at most 1 decimal place where 100.0 means exactly at norm. The screening is also required to carry `expected_pilot_order_version`, the stale-read guard described in §2.9.

Two figures are computed at the moment the screening is filed, and their evaluation order is pinned. The three components are weighted first: overall opinion carries 4550 basis points of the composite, stated intent 2975, and lead appeal 2475 — forty-five and a half, twenty-nine and three-quarter, and twenty-four and three-quarter percent respectively, which together account for the whole composite. Each component is computed on its own by multiplying its raw score by its weight in basis points, dividing by 10000, and rounding the quotient half up to 2 decimal places. Only then are the three rounded components added together, and their sum is `weighted_raw_score`, itself carrying 2 decimal places. Summing the three unrounded products and rounding the total afterwards produces a different number and is not the specified answer. `norm_adjusted_score` follows from it: multiply `weighted_raw_score` by 100, divide by `comp_norm_index`, and round the quotient half up to 1 decimal place. Neither number is affected by `panel_size`; sample size is a certification gate, not a scoring input.

A newly fielded screening has `status` `FIELDED` and a null `certified_at`. Fielding it supersedes the pilot's research history: every earlier screening on the same pilot order whose `status` is `FIELDED` or `CERTIFIED` is moved to `INVALIDATED` in the same request, and the pilot order's `version` is incremented by 1. If the invalidated screening was the project's only certified research, the project loses its certification and its path to a series-order negotiation closes again until fresh research is certified. Screenings may be listed per pilot order, invalidated ones included, and the list may be narrowed by `status`.

Certification is the act that turns a fielded screening into research of record, and it too is a `ResearchAnalyst` action. The screening must still be `FIELDED` — a screening that is already `CERTIFIED`, or that a newer screening has `INVALIDATED`, is refused with `ERR_INVALID_SCREENING_STATE` — and its `panel_size` must be at least 300 respondents, else `ERR_TEST_SAMPLE_TOO_SMALL`. Certification moves the screening `FIELDED → CERTIFIED` and stamps `certified_at` from the logical clock. Once `CERTIFIED`, a screening accepts no client-driven write of any kind; the sole way out of it is system supersession by a newer screening fielded on the same pilot order, which drives it to `INVALIDATED`. Both `CERTIFIED` and `INVALIDATED` are terminal with respect to every client request.

### 3.7. Series-Order Negotiation with the Studio

A negotiation is the standing term sheet between the network and the studio, and `BusinessAffairs` opens it on a project that has reached `PILOT_DELIVERED`. The opening offer names the `project_id` and five commercial terms: `episode_count` (at least 1), `license_fee_per_episode_cents` (greater than zero), `backend_points_bps` (the backend participation granted to the studio, from 0 to 10000 basis points), and the ownership split as `network_ownership_pct` and `studio_ownership_pct`, each an integer from 0 to 100.

Research gates the opening. The project must have at least one `CERTIFIED` screening on one of its pilot orders, else `ERR_NO_CERTIFIED_TEST`. Then the project's most recently certified screening — the one with the highest `certified_at`, with ties broken by the lowest `created_at` — must have a `norm_adjusted_score` of at least 62.0, else `ERR_TEST_SCORE_BELOW_FLOOR`. The floor comparison is inclusive: a normalised score of exactly 62.0 passes, and 61.9 does not.

Three commercial gates follow, and they are ordered. The term sheet must be internally coherent — `network_ownership_pct` and `studio_ownership_pct` must add to exactly 100, `backend_points_bps` must not exceed the slate's `max_backend_points_bps`, and `episode_count` must be at least 1 — else `ERR_TERM_SHEET_INVALID`. Then `license_fee_per_episode_cents` must be at or below the slate's `license_fee_cap_per_episode_cents`, else `ERR_LICENSE_FEE_ABOVE_CAP`. And, last, the slate must have the inventory: `available_episode_count` must be at least the `episode_count` being reserved, else `ERR_EPISODE_CAPACITY_EXCEEDED`. A `LOCKED` slate `posture` blocks the opening outright with `ERR_SLATE_POSTURE_LOCKED`, and that check is evaluated before any of the three commercial gates.

The opening offer is created with `status` `NETWORK_OFFER`, a `round_number` of 1, a `last_offer_side` of `NETWORK`, a null `agreed_at` and a null `withdrawn_reason`. Its `total_license_commitment_cents` is `episode_count` multiplied by `license_fee_per_episode_cents`. The slate's `reserved_episode_count` rises by `episode_count`, `available_episode_count` falls by the same, `posture` is recomputed, and the slate's `version` is incremented by 1.

Countering alternates strictly by side. A `StudioPartner` counters a standing `NETWORK_OFFER`, which moves the negotiation `NETWORK_OFFER → STUDIO_COUNTER`; `BusinessAffairs` counters a standing `STUDIO_COUNTER`, which moves it `STUDIO_COUNTER → NETWORK_OFFER`. A counter on an `AGREED` or `WITHDRAWN` negotiation is refused with `ERR_INVALID_NEGOTIATION_STATE`. The negotiation's `round_number` must be below 4 for a counter to be accepted — four term sheets is the ceiling — else `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. A counter submits the same five commercial terms and they face the same coherence, backend-ceiling and license-cap checks as the opening. Its capacity check is a delta rather than an absolute: because the negotiation already holds a reservation of its current `episode_count`, the submitted `episode_count` is admissible when the slate's `available_episode_count` plus the negotiation's currently reserved `episode_count` is at least the submitted figure. On success the five term-sheet fields are overwritten with the counter's terms, `status` and `last_offer_side` both flip, `round_number` is incremented by 1, `total_license_commitment_cents` is recomputed from the new terms, and the slate's `reserved_episode_count` is reconciled by the difference between the new `episode_count` and the old one — a counter that raises the count from 8 to 10 adds 2 to the reservation rather than reserving 10 a second time. `available_episode_count` and `posture` are recomputed, and the negotiation's `version` and the slate's `version` are each incremented by 1. The cycle `NETWORK_OFFER → STUDIO_COUNTER → NETWORK_OFFER` may repeat until the round ceiling is reached.

Acceptance closes the deal, and the rule is that the side which tabled the standing sheet may not accept it. A `StudioPartner` may accept only while `last_offer_side` is `NETWORK`, moving the negotiation `NETWORK_OFFER → AGREED`; `BusinessAffairs` may accept only while `last_offer_side` is `STUDIO`, moving it `STUDIO_COUNTER → AGREED`. The wrong side accepting its own offer is refused with `ERR_ACCEPT_BY_OFFERING_SIDE`, and accepting a negotiation that is no longer open is `ERR_INVALID_NEGOTIATION_STATE`. Acceptance stamps `agreed_at` from the logical clock and converts the reservation into a commitment: the `episode_count` moves out of the slate's `reserved_episode_count` and into `committed_episode_count`, which leaves `available_episode_count` unchanged while `posture` is recomputed — and since `posture`'s locked test reads `committed_episode_count` alone, an acceptance is the event most likely to lock a slate. The negotiation's `version` and the slate's `version` are each incremented by 1. `AGREED` and `WITHDRAWN` are the negotiation's terminal states. A project's negotiations may be listed, which is the one read surface a `StudioPartner` is given on the development side.

### 3.8. Feasibility Economics and the Greenlight Fork-Join

Before anyone signs, the department wants a number for what a series order would cost the network per episode, and the feasibility computation supplies it. It is exposed as a computed read on a project for `DevelopmentExec`, `BusinessAffairs` and `FinanceController`, parameterised by two optional query values: `basis`, which selects the variant and defaults to `PATTERN`, and `episode_count`, which defaults to the slate's `default_episode_count` when the caller omits it. The response reports the `basis` and `episode_count` actually used along with `per_episode_cost_cents`, `tier_factor_bps`, `license_fee_final_cents`, `deficit_per_episode_cents`, `total_deficit_cents` and a `verdict`. Every figure is integer cents and every division discards its remainder.

The computation runs in four steps, in exactly this order. Step one establishes the per-episode cost. On the `PATTERN` basis — the network's own view, what it believes the show costs to make in its slot — the cost base is the slate's `pattern_budget_per_episode_cents` taken directly, with no platform factor applied. On the `LICENSE` basis — the studio's deficit-financing view — the cost base is instead the slate's `license_fee_cap_per_episode_cents` multiplied by the platform's cost factor in basis points, divided by 10000 with the remainder discarded; that factor is 11000 for a `BROADCAST` slate, 10500 for `CABLE` and 12000 for `STREAMING`. To whichever base applies, add the amortised development cost: the project's `cumulative_dev_cost_cents` divided by the `episode_count` in play, remainder discarded. The sum is `per_episode_cost_cents`.

Step two chooses a pricing tier, and it does so from a **provisional** deficit rather than from the deficit the calculation eventually reports. The provisional deficit is `per_episode_cost_cents` less the slate's `license_fee_cap_per_episode_cents` — the deficit the slate would carry if the network simply paid its full cap. When that provisional figure is zero or negative, `tier_factor_bps` is 10000. When it is positive but no greater than 1,500,000 cents — fifteen thousand dollars per episode — `tier_factor_bps` is 9500. When it is greater than that, `tier_factor_bps` is 9000. This ordering is pinned deliberately: the final license fee depends on the tier and the tier depends on the provisional deficit, so the tier must be read off the provisional figure in a single forward pass. Re-deriving the tier from the final `deficit_per_episode_cents`, or iterating the pair until it settles, produces a different and incorrect license fee whenever the two deficits fall on opposite sides of the 1,500,000-cent breakpoint.

Step three sets the fee. Multiply `per_episode_cost_cents` by `tier_factor_bps`, divide by 10000 and discard the remainder; `license_fee_final_cents` is the smaller of that result and the slate's `license_fee_cap_per_episode_cents`. Step four reports the outcome: `deficit_per_episode_cents` is `per_episode_cost_cents` less `license_fee_final_cents`, `total_deficit_cents` is that per-episode deficit multiplied by `episode_count`, and `verdict` is `FEASIBLE` when `deficit_per_episode_cents` is less than or equal to the slate's `max_deficit_per_episode_cents` and `INFEASIBLE` otherwise. Because the `LICENSE` base exceeds the cap on any `STREAMING` or `BROADCAST` slate, that variant lands in the deepest tier and reports a strictly larger `deficit_per_episode_cents` than `PATTERN` does on identical data — the two bases can and do return opposite verdicts on the same project, which is exactly why the caller must choose one.

Filing for a greenlight is a `BusinessAffairs` act, and the request names the `project_id`, the `negotiation_id` of the `AGREED` term sheet being submitted, and `expected_project_version`. The negotiation must be `AGREED`, else `ERR_INVALID_NEGOTIATION_STATE`; the project must be at `PILOT_DELIVERED`, else `ERR_INVALID_PROJECT_STATE`; the version guard of §2.9 applies; and the negotiation must belong to the project named in the same request, else `ERR_NEGOTIATION_PROJECT_MISMATCH`. On acceptance the request is created with `status` `OPEN`, all three of `creative_decision`, `business_decision` and `finance_decision` at `PENDING`, all three of `creative_decided_by_user_id`, `business_decided_by_user_id` and `finance_decided_by_user_id` null, a null `decided_at`, and `project_version_at_request` stamped with the project `version` that was observed — the same number the caller supplied as `expected_project_version`. Every other greenlight request on the same project that was still `OPEN` becomes `SUPERSEDED`, with whatever committee decisions it had already collected frozen exactly as they stand, and the project's `version` is incremented by 1. Greenlight requests may be listed and narrowed by `project_id`, `negotiation_id` or `status`.

A decision names the `committee` — `CREATIVE`, `BUSINESS` or `FINANCE` — and the `decision` itself, either `APPROVED` or `REJECTED`, with an optional `note`. The committee-to-role pairing and the one-decision-per-person rule are both stated in §2.1. Beyond those, the request must still be `OPEN`, else `ERR_INVALID_GREENLIGHT_STATE`, and the named committee's own decision must still be `PENDING`, else `ERR_COMMITTEE_ALREADY_DECIDED`. One further gate applies to a `FINANCE` vote of `APPROVED` only: the server re-evaluates the feasibility computation on the `PATTERN` basis at the `episode_count` of the negotiation attached to the request, and refuses the approval with `ERR_FEASIBILITY_FAILED` when the verdict comes back `INFEASIBLE`. A `FINANCE` vote of `REJECTED` faces no such check. Recording a decision sets that committee's decision field and its matching decided-by field from `X-User-ID`, and the request stays `OPEN` while any committee is still `PENDING` — so the first and second votes are self-loops on `OPEN`.

The third approving vote is the join, and it fires a four-link cascade. The request moves `OPEN → APPROVED` and `decided_at` is stamped from the logical clock. Because of that, the project moves `PILOT_DELIVERED → SERIES_ORDERED`. Because of that, every script deal of the project whose `deal_status` is `EXECUTED` becomes `COMPLETED`, and within each such deal every step still `PENDING` becomes `CUT_OFF`. Because those steps have left `encumbered_cents`, the slate's `committed_dev_cents` drops by the released fees and its `available_dev_cents` and `posture` are recomputed. The project's `version` and the slate's `version` are each incremented by 1, alongside the request's own. Note how much narrower this cascade is than abandonment's: it cuts off only `PENDING` steps and leaves `ACCEPTED`, `EXERCISED`, `DELIVERED` and `NOTES_ISSUED` work encumbered, because that writing was done and the network owes for it. `SERIES_ORDERED` is terminal for the project.

Any `REJECTED` vote short-circuits the join instead. The named committee's decision is set to `REJECTED`, the request moves `OPEN → REJECTED` and `decided_at` is stamped, and the committees that had not yet voted stay `PENDING` forever — nobody is asked to vote on a dead request. The project is deliberately left at `PILOT_DELIVERED` rather than being pushed anywhere, so business affairs may renegotiate the term sheet and file a fresh request, which is the moment the supersession rule described above earns its keep. `APPROVED`, `REJECTED` and `SUPERSEDED` are all terminal.

### 3.9. Abandonment, Write-Offs and Turnaround Rights

Most development dies, and the system makes that death explicit rather than letting a project rot in `ACTIVE_DEVELOPMENT`. A `DevelopmentExec` abandons a project with an `abandon_reason`, and it may be abandoned from any of `ACTIVE_DEVELOPMENT`, `SCRIPT_COMPLETE`, `PILOT_ORDERED` or `PILOT_DELIVERED`; from `SERIES_ORDERED` or from `ABANDONED` it is refused with `ERR_INVALID_PROJECT_STATE`. The side effects form one ordered cascade, and the ordering is load-bearing.

Until a project is abandoned, both of its write-off figures read zero: `writeoff_cents` is 0 and `recoupment_paid_cents` is 0, and `abandoned_at`, `abandon_reason` and `turnaround_offered_at` are all null. The first link of the cascade, evaluated before every other effect of the request, freezes the accounting: `writeoff_cents` is set to the project's `cumulative_dev_cost_cents` as it stands at that instant, `abandoned_at` is stamped from the logical clock, `abandon_reason` records the submitted reason, and `dev_status` becomes `ABANDONED`. That snapshot must be taken first, because everything that follows drives the project's live cost toward zero — if the write-off were computed after the deals were torn up it would come out at nothing. `writeoff_cents` is never recomputed after this instant.

Three unwindings then follow from that first link. Every script deal of the project whose `deal_status` is `EXECUTED` becomes `TERMINATED`; and caused by that, every step of each terminated deal that is not already `CUT_OFF` becomes `CUT_OFF` — `ACCEPTED` steps included, which is the sharpest difference between this cascade and the series-order cascade of §3.8. Caused in turn by that, each terminated deal's `encumbered_cents` falls to 0, so the slate's `committed_dev_cents` drops by the whole deal encumbrance and `available_dev_cents` and `posture` are recomputed. Separately, every negotiation of the project whose `status` is `NETWORK_OFFER` or `STUDIO_COUNTER` becomes `WITHDRAWN` with `withdrawn_reason` set to the same submitted reason, and because of that the slate's `reserved_episode_count` drops by those negotiations' `episode_count`, so `available_episode_count` and `posture` are recomputed. And separately again, every pilot order of the project whose `production_status` is `ORDERED` or `GREEN_TO_SHOOT` becomes `COLLAPSED` with `collapsed_reason` set to the string `PROJECT_ABANDONED`, which removes its `budget_cents` from the slate's `committed_dev_cents` — a `WRAPPED` pilot is left alone, since its money was genuinely spent.

Finally the slate's `writeoff_dev_cents` rises by the project's `writeoff_cents`, holding those spent development dollars out of `available_dev_cents` permanently. Both the project's `version` and the slate's `version` are incremented by 1. The arithmetic closes exactly: the cents the cut-off steps released are the same cents link one froze into `writeoff_cents`, which is why the slate's dollar invariant shows no drift across an abandonment.

An abandoned project can still be sold. `BusinessAffairs` offers it into turnaround, which requires `dev_status` `ABANDONED` and `turnaround_status` `NONE`, and moves the turnaround dimension `NONE → OFFERED` while stamping `turnaround_offered_at` from the logical clock. `turnaround_status` is a second, wholly independent state dimension on the same row: `dev_status` stays `ABANDONED` throughout, and offering turnaround transitions nothing else. From that moment `turnaround_window_open` reads true — it is true exactly while `turnaround_status` is `OFFERED` and the logical clock is strictly before the instant 180 days after `turnaround_offered_at` — and `recoupment_amount_cents` becomes a live number rather than the 0 it reads while `turnaround_status` is `NONE`.

Recoupment is what the studio must pay to take the project away, and it is priced off the frozen write-off in four moves. First, count `months_elapsed`: the number of whole calendar months from the project's `abandoned_at` date to the logical clock's current date, floored, so a partial month contributes nothing. Second, compute interest at an annual rate of 900 basis points — nine percent a year — pro-rated by those whole months: multiply `writeoff_cents` by 900 and by `months_elapsed`, then divide by 120,000, which is 10000 basis points times twelve months, discarding the remainder. Third, add a handling fee tiered on the size of the write-off: 250,000 cents when `writeoff_cents` is at or below 10,000,000 cents, 750,000 cents when it is above 10,000,000 but at or below 50,000,000, and 1,500,000 cents when it is above 50,000,000 — two and a half, seven and a half, or fifteen thousand dollars. Fourth, take the smaller of two figures: the write-off plus the interest plus the handling fee, or 135 percent of the write-off, computed by multiplying `writeoff_cents` by 13500 basis points, dividing by 10000 and discarding the remainder. That minimum is `recoupment_amount_cents`, and the nested cap means a long-dormant project stops accruing once its total reaches 135 percent of what the network sank into it.

Exercising the turnaround is again a `BusinessAffairs` act and carries a `successor_title`. It requires `turnaround_status` `OFFERED`, and it requires the window still open — an exercise at or after the instant 180 days past `turnaround_offered_at` is refused with `ERR_TURNAROUND_WINDOW_CLOSED`. On success the recoupment is evaluated at the current clock and frozen into `recoupment_paid_cents`, and `turnaround_status` moves `OFFERED → EXERCISED`; from then on `recoupment_amount_cents` reads exactly `recoupment_paid_cents` and stops moving with the clock. Caused by that payment, the slate's `recouped_dev_cents` rises by `recoupment_paid_cents`, so `available_dev_cents` rises by the same amount and `posture` is recomputed — this is the only route by which development dollars ever come back to a slate. And a successor project is created in the same request: it carries `predecessor_project_id` pointing at the abandoned project, `pitch_id` and `slate_id` copied from it, a `title` equal to the submitted `successor_title`, `dev_status` `ACTIVE_DEVELOPMENT` and `turnaround_status` `NONE`, so the successor begins its own development life from the top and may itself be deal-papered, piloted, ordered or abandoned. The predecessor's `version` and the slate's `version` are each incremented by 1, and the response body is the newly created successor project rather than the predecessor.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`: registering an agency, a slate or a writer, writing a holding deal, submitting a pitch, filing a rights check, advancing a pitch (which returns the newly created development project), executing a script deal, ordering a pilot, fielding a test screening, opening a negotiation, filing a greenlight request, and exercising a turnaround (which returns the newly created successor project). Every operation that modifies an existing resource returns `200 OK` — coverage, holding-deal termination, every deal-step action and deal cutoff, contingency clearance, wrap, certification, negotiation rounds and acceptance, committee decisions, project abandonment, offering a turnaround, and setting the clock. All reads return `200 OK`. Because the API prefix is empty, every path below is a complete path. The table names only the HTTP contract; the request bodies, response bodies and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agencies` | Register a talent/literary agency and its submission relationship with the network. | PlatformAdmin |
| GET | `/agencies/{id}` | Read one agency including its computed submission allotment and usage. | PlatformAdmin, DevelopmentExec, BusinessAffairs, AgencyRep |
| POST | `/slates` | Open a development slate for a platform and season with its budget and episode economics. | PlatformAdmin |
| GET | `/slates/{id}` | Read one slate with its live dollar ledger, episode inventory and posture. | PlatformAdmin, DevelopmentExec, BusinessAffairs, FinanceController |
| POST | `/writers` | Register a writer represented by an agency, with their guild tier and quote. | PlatformAdmin, AgencyRep |
| GET | `/writers/{id}` | Read one writer with computed exclusivity_status and open_step_count. | PlatformAdmin, DevelopmentExec, BusinessAffairs, AgencyRep |
| GET | `/writers` | List writers, optionally narrowed to one agency or one exclusivity status. | PlatformAdmin, DevelopmentExec, BusinessAffairs, AgencyRep |
| POST | `/holding-deals` | Put a writer under an exclusive holding deal funded by a slate's development budget. | BusinessAffairs |
| GET | `/holding-deals/{id}` | Read one holding deal with its computed term_state. | PlatformAdmin, BusinessAffairs, DevelopmentExec |
| GET | `/holding-deals` | List holding deals, optionally narrowed by writer, slate or status. | PlatformAdmin, BusinessAffairs, DevelopmentExec |
| POST | `/holding-deals/{id}/terminate` | Terminate an ACTIVE holding deal and release its reservation against the slate. | BusinessAffairs |
| POST | `/pitches` | Submit a pitch from an agency against a slate. | AgencyRep |
| GET | `/pitches/{id}` | Read one pitch with its coverage state. | PlatformAdmin, DevelopmentExec, BusinessAffairs, AgencyRep |
| GET | `/pitches` | List pitches, optionally narrowed by agency, slate or status. | PlatformAdmin, DevelopmentExec, BusinessAffairs, AgencyRep |
| POST | `/pitches/{id}/coverage` | Record a coverage read on a pitch; a PASS recommendation closes the pitch and refunds the agency's slot. | DevelopmentExec |
| POST | `/pitches/{id}/rights-checks` | File a chain-of-title and availability clearance record against a pitch's underlying IP. | BusinessAffairs |
| GET | `/pitches/{id}/rights-checks` | List every rights check filed against a pitch, newest last. | PlatformAdmin, BusinessAffairs, DevelopmentExec |
| POST | `/pitches/{id}/advance` | Advance a covered, rights-clear pitch into active development, creating the DevelopmentProject. | DevelopmentExec |
| GET | `/development-projects/{id}` | Read one development project with its cumulative dev cost and turnaround state. | PlatformAdmin, DevelopmentExec, BusinessAffairs, FinanceController |
| GET | `/development-projects` | List development projects, optionally narrowed by originating pitch, slate, predecessor project or dev_status. | PlatformAdmin, DevelopmentExec, BusinessAffairs, FinanceController |
| GET | `/development-projects/{id}/feasibility` | Computed read of the pilot_series_feasibility calculation for this project. basis selects the PATTERN (default) or LICENSE variant; episode_count defaults to the slate's default_episode_count. | DevelopmentExec, BusinessAffairs, FinanceController |
| GET | `/development-projects/{id}/pilot-orders` | List the pilot orders placed on this project, including collapsed ones. | PlatformAdmin, DevelopmentExec, BusinessAffairs, ResearchAnalyst |
| GET | `/development-projects/{id}/negotiations` | List the series-order negotiations opened on this project. | PlatformAdmin, DevelopmentExec, BusinessAffairs, FinanceController, StudioPartner |
| POST | `/development-projects/{id}/abandon` | Abandon a development project, freezing its write-off and unwinding every downstream commitment in one cascade. | DevelopmentExec |
| POST | `/development-projects/{id}/turnaround` | Offer an abandoned project into turnaround, opening the 180-day exercise window. | BusinessAffairs |
| POST | `/development-projects/{id}/turnaround-exercise` | Exercise a turnaround offer: the studio pays the recoupment and a successor project is created carrying the same underlying pitch. | BusinessAffairs |
| POST | `/script-deals` | Execute a step deal attaching a writer to a project, with its full step ladder and the option period that governs each optional step. | BusinessAffairs |
| GET | `/script-deals/{id}` | Read one script deal with both commitment variants and its live encumbrance. | PlatformAdmin, BusinessAffairs, DevelopmentExec, FinanceController |
| GET | `/script-deals` | List script deals, optionally narrowed by project, writer or deal_status. | PlatformAdmin, BusinessAffairs, DevelopmentExec, FinanceController |
| GET | `/script-deals/{id}/steps` | List the deal's steps in step_index order with their effective fees and option expiries. | PlatformAdmin, BusinessAffairs, DevelopmentExec, FinanceController |
| POST | `/script-deals/{id}/steps/{step_id}/exercise` | Exercise an optional step inside its option period, committing the network to its fee. | BusinessAffairs |
| POST | `/script-deals/{id}/steps/{step_id}/deliver` | Record delivery of an exercised step's material, or redelivery after a notes round. | BusinessAffairs, DevelopmentExec |
| POST | `/script-deals/{id}/steps/{step_id}/review` | Review a delivered step: outcome NOTES issues a further notes round, outcome ACCEPT closes the step and may complete the deal. | DevelopmentExec |
| POST | `/script-deals/{id}/cutoff` | Cut the writer off after the guaranteed steps, releasing every remaining optional step. | BusinessAffairs |
| POST | `/pilot-orders` | Order a pilot on a script-complete project, with casting and location contingencies pending. | DevelopmentExec |
| GET | `/pilot-orders/{id}` | Read one pilot order with both contingency dimensions and its budget variance. | PlatformAdmin, DevelopmentExec, BusinessAffairs, ResearchAnalyst, FinanceController |
| POST | `/pilot-orders/{id}/contingency-clearances` | Resolve one of the pilot's two contingency dimensions. kind is CASTING or LOCATION; resolution is SATISFIED, WAIVED (BusinessAffairs only) or FAILED. | DevelopmentExec, BusinessAffairs |
| POST | `/pilot-orders/{id}/wrap` | Wrap a green-lit pilot shoot once its shoot window has elapsed. | DevelopmentExec |
| POST | `/pilot-orders/{id}/test-screenings` | Field a research screening on a wrapped pilot, superseding any earlier screening on the same pilot. Requires the caller's observed PilotOrder version. | ResearchAnalyst |
| GET | `/pilot-orders/{id}/test-screenings` | List every screening fielded on this pilot order, including invalidated ones. | PlatformAdmin, ResearchAnalyst, DevelopmentExec, BusinessAffairs, FinanceController |
| POST | `/test-screenings/{id}/certify` | Certify a fielded screening as research of record; refused when the panel is under 300. | ResearchAnalyst |
| POST | `/negotiations` | Open the network's series-order offer on a pilot-delivered project with certified research. | BusinessAffairs |
| POST | `/negotiations/{id}/rounds` | Table a counter on an open negotiation. StudioPartner counters a network offer; BusinessAffairs counters a studio counter. | BusinessAffairs, StudioPartner |
| POST | `/negotiations/{id}/accept` | Accept the standing offer. Only the side that did not table it may accept, which converts the episode reservation into a commitment. | BusinessAffairs, StudioPartner |
| POST | `/greenlight-requests` | File a series greenlight request against an AGREED term sheet, superseding any request still OPEN on the same project. Requires the caller's observed DevelopmentProject version. | BusinessAffairs |
| GET | `/greenlight-requests/{id}` | Read one greenlight request with each committee's decision and decider. | PlatformAdmin, DevelopmentExec, BusinessAffairs, FinanceController |
| GET | `/greenlight-requests` | List greenlight requests, optionally narrowed by project, negotiation or status. | PlatformAdmin, DevelopmentExec, BusinessAffairs, FinanceController |
| POST | `/greenlight-requests/{id}/decisions` | Record one committee's decision. committee is CREATIVE, BUSINESS or FINANCE and must match the acting role; the same user may not decide twice on one request. | DevelopmentExec, BusinessAffairs, FinanceController |
| POST | `/_clock/set_current_utc` | Set the server's logical clock, which is the sole source of every server-stamped timestamp, every date comparison and every window/expiry rule in this domain. Before any call to this endpoint the logical clock reads exactly its startup default 2026-08-01T00:00:00Z and never falls back to real wall-clock time. | PlatformAdmin |

## 5. Error Code Catalogue

The trigger condition for each code is specified in the §2 and §3 narrative that governs the rule it enforces; this table fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_AGENCY_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_AGENCY_NOT_FOUND` | 404 |
| `ERR_SLATE_NOT_FOUND` | 404 |
| `ERR_WRITER_NOT_FOUND` | 404 |
| `ERR_HOLDING_DEAL_NOT_FOUND` | 404 |
| `ERR_PITCH_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_SCRIPT_DEAL_NOT_FOUND` | 404 |
| `ERR_DEAL_STEP_NOT_FOUND` | 404 |
| `ERR_PILOT_ORDER_NOT_FOUND` | 404 |
| `ERR_SCREENING_NOT_FOUND` | 404 |
| `ERR_NEGOTIATION_NOT_FOUND` | 404 |
| `ERR_GREENLIGHT_NOT_FOUND` | 404 |
| `ERR_INVALID_PITCH_STATE` | 409 |
| `ERR_INVALID_PROJECT_STATE` | 409 |
| `ERR_INVALID_DEAL_STATE` | 409 |
| `ERR_INVALID_DEAL_STEP_STATE` | 409 |
| `ERR_INVALID_PILOT_ORDER_STATE` | 409 |
| `ERR_CONTINGENCY_ALREADY_RESOLVED` | 409 |
| `ERR_INVALID_SCREENING_STATE` | 409 |
| `ERR_INVALID_NEGOTIATION_STATE` | 409 |
| `ERR_INVALID_GREENLIGHT_STATE` | 409 |
| `ERR_COMMITTEE_ALREADY_DECIDED` | 409 |
| `ERR_ACCEPT_BY_OFFERING_SIDE` | 409 |
| `ERR_SLATE_POSTURE_LOCKED` | 409 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_STALE_PILOT_ORDER_VERSION` | 412 |
| `ERR_PACKAGING_NOT_PERMITTED` | 422 |
| `ERR_RIGHTS_NOT_CLEAR` | 422 |
| `ERR_RIGHTS_HOLDBACK_CONFLICT` | 422 |
| `ERR_HOLDING_DEAL_OVERLAP` | 422 |
| `ERR_WRITER_EXCLUSIVITY_CONFLICT` | 422 |
| `ERR_WRITER_STEP_LOAD_EXCEEDED` | 422 |
| `ERR_GUARANTEED_STEP_NOT_CUTTABLE` | 422 |
| `ERR_TEST_SAMPLE_TOO_SMALL` | 422 |
| `ERR_OPTION_PERIOD_EXPIRED` | 422 |
| `ERR_SHOOT_WINDOW_NOT_ELAPSED` | 422 |
| `ERR_TURNAROUND_WINDOW_CLOSED` | 422 |
| `ERR_NOTES_ROUNDS_EXHAUSTED` | 422 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 422 |
| `ERR_TERM_SHEET_INVALID` | 422 |
| `ERR_LICENSE_FEE_ABOVE_CAP` | 422 |
| `ERR_PILOT_BUDGET_ABOVE_PATTERN` | 422 |
| `ERR_STAGE_CAPACITY_EXCEEDED` | 422 |
| `ERR_AGENCY_SUBMISSION_CAP_REACHED` | 422 |
| `ERR_NEGOTIATION_PROJECT_MISMATCH` | 422 |
| `ERR_NO_CERTIFIED_TEST` | 422 |
| `ERR_TEST_SCORE_BELOW_FLOOR` | 422 |
| `ERR_SLATE_DEV_BUDGET_EXCEEDED` | 422 |
| `ERR_EPISODE_CAPACITY_EXCEEDED` | 422 |
| `ERR_FEASIBILITY_FAILED` | 422 |
