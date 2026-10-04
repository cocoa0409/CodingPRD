# Dealer Survey Incentives API — Product Requirements Document

## 1. Introduction

Dealer satisfaction measurement is the connective tissue between a factory's brand promise and the dealership's day-to-day conduct. When a vehicle is sold or serviced, the customer's perception of that interaction feeds the factory's understanding of network health — and, in turn, determines which dealers earn margin incentives and which require coaching. This document specifies the Dealer Satisfaction Survey Administration & Incentive Qualification API: a system for deploying post-visit surveys under sampling rules and response windows, scoring responses at the dealer, department, and advisor grain, gating incentive payouts on those scores, and detecting manipulation by dealers who would rather game the metric than improve it.

The system serves six constituencies with deliberately segregated duties. Platform operations configures the network — regions, dealers, question sets, survey waves — and administers the lifecycle from deployment through payment. Regional managers oversee benchmarks and route appeals to review. Field consultants embed with underperforming dealers and shepherd remediation plans. An independent compliance function, firewalled from operations, investigates coaching, opt-out suppression, and contact tampering, and holds sole authority over the decisions that exclude responses and confirm flags. A third-party survey vendor dispatches invitations. Dealer principals see their own results, file appeals, and own their remediation. Finally, customers respond — or opt out — under the protection of a master do-not-contact flag.

A distinguishing feature of the design is that scores are not decorative. At wave close, an adjusted composite score — computed from scored responses with a deduction per confirmed manipulation flag — is written onto each dealer record and re-derives the dealer's posture along a `GOOD_STANDING → WATCH → PROBATION → SUSPENDED` ladder. Posture, in turn, gates behavior: suspended dealers lose self-serve plan submission, and their draft remediation plans are auto-routed to field review. Incentive statements settle against the same numbers, with a minimum response-rate gate that makes survey administration quality a precondition of payout. The result is a system in which measurement integrity, dealer accountability, and monetary consequences are mechanically linked — and in which every shortcut around that linkage is observable.

## 2. Global Specifications & System-Wide Principles

This section defines contract-level rules that apply uniformly across the API. Every reader implementing against this document should treat §2 as binding on all resources and all endpoints.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the seven recognized roles. The roles are `PlatformAdmin`, `RegionalManager`, `FieldConsultant`, `ComplianceAuditor`, `SurveyVendor`, `DealerPrincipal`, and `Customer`. A request missing either header, or presenting a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). A third failure mode, `ERR_FORBIDDEN` (HTTP 403), applies to entity-backed roles whose identity does not own the target resource — for example, a customer attempting to respond to someone else's invitation.

The meaning of `X-User-ID` depends on the role's identity model. When `X-User-Role` is `DealerPrincipal`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` — appeals, action plans, statements viewed through the dealer's lens — compare the resource's dealer foreign key to `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on `SurveyInvitation` resources compare the invitation's `customer_id` to `X-User-ID`. For `PlatformAdmin`, `RegionalManager`, `FieldConsultant`, `ComplianceAuditor`, and `SurveyVendor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.

Segregation of duties is a load-bearing design choice. `ComplianceAuditor` is firewalled from wave administration (cannot open, close, or finalize waves) and from action-plan review (cannot approve or reject plans). `FieldConsultant` is firewalled from manipulation-flag resolution. `PlatformAdmin` holds broad write authority but cannot decide appeals or resolve flags. `DealerPrincipal` and `Customer` act only on resources they own.

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

List endpoints accept two query parameters controlling windowing. The `limit` parameter specifies the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Both are integers; out-of-range values are rejected as malformed input.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order — oldest first. The `meta` block of a paginated response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true when the requested window does not exhaust the underlying collection.

### 2.4. Common Resource Properties

Every primary resource in the system — regions, dealers, departments, advisors, customers, question sets, waves, invitations, responses, appeals, manipulation flags, incentive statements, and action plans — carries a standard set of system-managed fields:

- `id`: a unique, server-generated UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits marking creation.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on any mutation.
- `version`: an integer starting at 1 on creation and incremented on every mutation, including mutations driven by cascading side effects.

The exception is the `Transaction` entity, which is immutable after recording and therefore carries only `id` and `created_at` — both `updated_at` and `version` are absent. This asymmetry matters for optimistic concurrency: transactions cannot be the parent of an OCC contract because there is nothing to version against.

### 2.5. Optimistic Concurrency Control

Two write endpoints in the system are protected by optimistic concurrency checks against a parent entity's `version`. Both use the same failure contract: when the client-supplied expected version does not equal the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The first guard applies to incentive statement creation. A request to create an `IncentiveStatement` must carry `expected_wave_version`, set to the `SurveyWave.version` the client last observed. If another writer has since closed or finalized the wave — each of those transitions bumps the wave's `version` — the client's view is stale and the create is rejected with `ERR_STALE_VERSION`, forcing a re-read before the statement is computed against numbers the caller has actually seen.

The second guard applies to appeal filing. A request to file an `Appeal` must carry `expected_response_version`, matching the `SurveyResponse.version` the dealer last observed. A system cascade — a manipulation-flag confirmation or an invitation suppression — may have already excluded the response, advancing its version; the stale appeal attempt is rejected with `ERR_STALE_VERSION` so the caller re-reads the response before arguing against it.

Endpoints not listed above do not take a version field. Submitting one is treated as an unknown field and rejected as malformed input.

### 2.6. Nested Resource Retrieval

Endpoints whose paths contain multiple resource identifiers validate them left to right. The system confirms each path segment against existence in order; the first segment that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) for that segment, and no further validation runs. The same discipline applies to body-referenced identifiers — a payload naming a non-existent `dealer_id`, `wave_id`, `question_set_id`, `invitation_id`, or `response_id` is rejected with `ERR_NOT_FOUND` before any business rule is evaluated.

Beyond existence, cross-references must be internally consistent. Recording a transaction whose `department_id` belongs to a different dealer than `dealer_id`, or whose `advisor_id` belongs to a different department than `department_id`, is rejected with `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 422). Filing an appeal whose resolved dealer does not match the `X-User-ID` dealer fails the same way.

### 2.7. Precision and Rounding

All money in the system is integer cents — `margin_cents` on transactions, `eligible_margin_cents` and `payout_cents` on statements — never fractional currency. Scores and rates, by contrast, are decimal numbers with explicit precision contracts. Individual survey `score` values, dealer composite scores, statement `score_used`, and historical `normalized_score` values are rounded half-up to two decimal places. Response rates (`current_response_rate` on the dealer, `response_rate_used` on the statement) are rounded half-up to four decimal places. The phrase "rounded half-up" means a value exactly at the midpoint rounds away from zero — `0.005` becomes `0.01`, not `0.00`.

### 2.8. The Logical Clock

The server maintains a logical clock distinct from wall-clock time. It starts at `2026-09-01T00:00:00Z` on boot and advances only when an operator explicitly sets it; it never falls back to wall-clock, and never advances on its own. A `PlatformAdmin` advances the clock by supplying a `current_utc` timestamp to the clock-control capability. All time-sensitive behavior — response windows, wave close eligibility, action-plan overdue evaluation — reads from this logical clock, never from the host's wall clock.

Advancing the clock triggers one lazy side effect: any `ActionPlan` in `IN_PROGRESS` whose `due_date` is now at or before the current logical time transitions to `OVERDUE`. The same lazy evaluation runs on every read of an individual plan, so overdue marking is observably correct immediately after a clock advance without requiring a separate sweep.

### 2.9. Validation Priority Order

When a request could fail for more than one reason, the system surfaces exactly one error, chosen by a fixed priority order. The order below is authoritative — earlier checks mask later ones:

1. Authentication — headers present, role recognized (`ERR_UNAUTHENTICATED`).
2. Authorization — role permitted on this endpoint (`ERR_UNAUTHORIZED`).
3. Ownership — entity-backed identity owns the target (`ERR_FORBIDDEN`).
4. Existence — every referenced id resolves (`ERR_NOT_FOUND`).
5. Cross-reference consistency — department under dealer, advisor under department, appeal dealer matches caller (`ERR_CROSS_REFERENCE_MISMATCH`).
6. State validity — resource is in a from-state for the requested transition (`ERR_INVALID_STATE`).
7. Optimistic concurrency — `expected_wave_version` or `expected_response_version` matches the parent's current `version` (`ERR_STALE_VERSION`).
8. Response window — the response is being submitted before the exclusive `window_closes_at` bound (`ERR_RESPONSE_WINDOW_CLOSED`).
9. Wave timing — close is not attempted before `period_end` (`ERR_WAVE_STILL_OPEN`).
10. Contact restriction — customer has not flipped `do_not_contact` since queueing (`ERR_CONTACT_RESTRICTED`).
11. Structural constraints — uniqueness, schema shape, weights positive (`ERR_VALIDATION`).
12. Question-set singleton — at most one `ACTIVE` set at activation (`ERR_ACTIVE_QUESTION_SET_EXISTS`).
13. Wave-open precondition — pinned set is `ACTIVE` (`ERR_QUESTION_SET_NOT_ACTIVE`).
14. Send precondition — wave is `OPEN` (`ERR_WAVE_NOT_OPEN`).
15. Appeal singleton — no open appeal exists on the response (`ERR_APPEAL_ALREADY_OPEN`).
16. Finalize appeal gate — no open appeals on the wave's responses (`ERR_APPEALS_PENDING`).
17. Finalize flag gate — no open manipulation flags on the wave's dealers (`ERR_FLAGS_PENDING`).
18. Suspended-dealer plan submission — `ERR_DEALER_SUSPENDED`.
19. Request shape — required fields present, well-typed, enums valid (`ERR_INVALID_REQUEST`).

The ordering matters most when several checks could fire on the same request. A wave-close attempted before `period_end` on a wave that is already `CLOSED` yields `ERR_INVALID_STATE`, not `ERR_WAVE_STILL_OPEN`, because state validity outranks business-temporal checks. An appeal filed against a non-existent response with a stale `expected_response_version` yields `ERR_NOT_FOUND`, never `ERR_STALE_VERSION`.

## 3. Business Logic & Workflows

This section describes the domain behavior end-to-end. Subsections are organized by lifecycle — network setup, instrument design, wave administration, response collection, integrity, remediation, and settlement — and deliberately interleave rules that §4's endpoint table only names. A reader implementing from this document should expect the full specification of any single endpoint to require reading two or three of these subsections.

### 3.1. Establishing the Network: Regions, Dealers, Departments, Advisors, Customers

A `PlatformAdmin` begins by laying down the organizational skeleton. A `Region` is created with a unique `code` (e.g., `SW`) and a display `name`. A `Dealer` is created against a region by supplying `region_id`, a display `name`, and a factory-issued `dealer_code` that must be unique across all dealers — duplicates are rejected with `ERR_VALIDATION`. At creation, a dealer's `posture` is `GOOD_STANDING`, its `confirmed_flag_count` is `0`, and both `current_score_adjusted` and `current_response_rate` are null until the first wave close writes them.

Beneath a dealer sit exactly two `Department` rows, distinguished by `kind` — one of `SALES` or `SERVICE`. The pair (`dealer_id`, `kind`) is unique: attempting to register a second `SALES` department on the same dealer fails with `ERR_VALIDATION`. Each department has its own display `name`. Within a department, an `Advisor` is registered with `department_id`, a full `name`, and an `employee_ref` unique within that department.

Customers are registered independently of any dealer, with `full_name`, `email`, `phone`, and an optional `do_not_contact` boolean defaulting to `false`. The `email` must contain `@`; the `phone` must be digits only, between ten and fifteen characters. Malformed values are rejected with `ERR_INVALID_REQUEST`. The `do_not_contact` flag is the customer's master opt-out and has teeth throughout the system: it is consulted at sampling time, re-checked at send time, and flipped to `true` permanently by any explicit opt-out action.

Listing endpoints exist across this skeleton. Dealers are listable with an optional `region_id` filter; departments are listed under a dealer via the nested path; advisors are listed under a department. Reading a single customer record is restricted to `PlatformAdmin` and `ComplianceAuditor` — neither dealers nor regional staff may pull raw contact data, a deliberate containment against contact tampering.

### 3.2. Designing the Instrument: Question Sets

The survey instrument is a `QuestionSet` created by a `PlatformAdmin` with a unique `code` (for example, `QS-2026-A`), a `questions` array, and a `comparability_factor`. Each entry in `questions` carries a `question_code`, a `prompt`, and a positive numeric `weight`; the array must contain at least one question, and `question_code` values must be unique within the set. Violations are rejected with `ERR_VALIDATION`. The `comparability_factor` is a multiplier strictly greater than 0.5 and at most 1.5; it maps this set's scores onto its predecessor's scale so that year-over-year score history remains meaningful when the instrument changes.

A question set begins life in `DRAFT`. Activation — a `PlatformAdmin` action — moves it to `ACTIVE`, but only if no other set is currently `ACTIVE`; the check fires with `ERR_ACTIVE_QUESTION_SET_EXISTS` when a singleton is violated. Retirement moves `ACTIVE` to `RETIRED`. At most one set is ever `ACTIVE` at a time, and that set is the one pinned to subsequently created waves. Retiring a set does not disturb existing waves — they keep their pinned `question_set_id` — but no new wave may be created against a `RETIRED` set.

### 3.3. Recording What Happened: Transactions

Every sale or service visit that could trigger a survey is recorded as a `Transaction`. A `PlatformAdmin` records the visit with `dealer_id`, `department_id`, an optional `advisor_id`, the visiting `customer_id`, the visit `kind` (one of `SALE` or `SERVICE_VISIT`), the `completed_at` timestamp, and the `margin_cents` attributable to the visit — an integer at or above zero. The department must belong to the named dealer, and the advisor, when present, must belong to the named department; mismatches surface as `ERR_CROSS_REFERENCE_MISMATCH`. Transactions are immutable once recorded and carry no `version` — corrections require new records, not edits.

Transactions feed two downstream consumers. At wave open, they are the population from which survey invitations are sampled. At wave close and statement creation, their `margin_cents` sum becomes the eligible margin base against which incentive payouts are computed.

### 3.4. Running a Wave: From Draft Through Finalized

A `SurveyWave` is the administrative unit of measurement. A `PlatformAdmin` creates one with `period_start` (inclusive), `period_end` (exclusive, strictly after `period_start`), and `question_set_id`. The wave is born in `DRAFT` with all counters — `invitations_total`, `queued_count`, `sent_count`, `responded_count`, `expired_count`, `opted_out_count`, `suppressed_count` — at zero.

Opening the wave is the moment the instrument meets the population. The transition `DRAFT → OPEN` requires the pinned question set to be `ACTIVE`; otherwise the request fails with `ERR_QUESTION_SET_NOT_ACTIVE`. On success, a sampling sweep runs exactly once. For each dealer, the sweep collects transactions whose `completed_at` falls within the half-open period [`period_start`, `period_end`), whose customer's `do_not_contact` is `false`, and for which no other invitation already exists pairing the same `customer_id` and `kind` in any wave whose period overlaps the trailing ninety days — the contact-suppression rule that prevents a customer from being resurveyed on the same visit type within a quarter. The ninety-day contact-suppression window is anchored to the new wave, not to the prior invitation: a candidate transaction is suppressed only when another invitation exists for the same customer and the same `kind` whose wave's period overlaps the new wave's trailing ninety days — the half-open window running from `period_start` minus ninety days up to (but not including) the new wave's `period_end`. The eligible set is sorted by `completed_at` ascending, ties broken by transaction `created_at` ascending, and at most twenty transactions per (dealer, `kind`) pair are kept. Each selected transaction spawns a `SurveyInvitation` in `QUEUED` status, with `customer_id` and `question_set_id` copied from the transaction and the wave respectively; each creation increments the wave's `invitations_total` and `queued_count` by one.

Closing the wave — `OPEN → CLOSED` — requires the logical clock to have reached `period_end`; an early attempt is rejected with `ERR_WAVE_STILL_OPEN`. On close, four things happen. First, every invitation still in `QUEUED` or `SENT` transitions to `EXPIRED`, with `queued_count` and `sent_count` decrementing and `expired_count` incrementing by the number expired. Second, the wave's `closed_at` is stamped with the current logical time — it remains null until this moment and serves as the close-time anchor for downstream trailing-window calculations. Third, for every dealer with at least one transaction in the period, the system computes that wave's scores and response rate, writes them onto the dealer as `current_score_adjusted` and `current_response_rate`, and re-derives `posture`. Fourth, the wave's `version` increments by one — a fact that matters to the OCC guard on statement creation.

Finalizing the wave — `CLOSED → FINALIZED` — is the point of no return for appeals and investigations. It is blocked when any appeal on a response belonging to this wave is still in `FILED` or `UNDER_REVIEW` (the rejection is `ERR_APPEALS_PENDING`), and independently blocked when any manipulation flag on a dealer with invitations in this wave is still `OPEN` (the rejection is `ERR_FLAGS_PENDING`). Both gates are checked; an administrator attempting finalize with both kinds of pending work sees `ERR_APPEALS_PENDING` first because that check outranks the flag gate in the validation order. On success, every `IncentiveStatement` for this wave in `PROVISIONAL` transitions to `FINAL`, and the wave's `version` increments again.

### 3.5. The Customer's Part: Send, Respond, Opt Out, Suppress

An invitation's lifecycle begins in `QUEUED`. A `SurveyVendor` sends it — the transition `QUEUED → SENT` — which requires two preconditions evaluated in priority order: the owning wave must be `OPEN` (otherwise `ERR_WAVE_NOT_OPEN`), and the customer's `do_not_contact` must still be `false` (otherwise `ERR_CONTACT_RESTRICTED`). The second check exists because a customer may have opted out through another channel after the invitation was queued; send-time re-evaluation is the safety net. On a successful send, the invitation's `sent_at` is stamped with the current logical time, and `window_closes_at` is computed as `sent_at` plus fourteen days. The wave's `queued_count` decrements and `sent_count` increments.

A `Customer` responds by submitting an `answers` array against the invitation. The array must cover every question in the invitation's pinned question set exactly once — each entry pairs a `question_code` with an integer `score` between 1 and 10 — and any deviation (missing questions, duplicate `question_code`s, scores out of range, unknown codes) is rejected with `ERR_INVALID_REQUEST`. Submission requires the invitation to be in `SENT`; the logical clock must be strictly before `window_closes_at`, with the boundary exclusive — a submission exactly at `window_closes_at` is rejected with `ERR_RESPONSE_WINDOW_CLOSED`. The caller's `X-User-ID` must equal the invitation's `customer_id`; any other caller is `ERR_FORBIDDEN`. On success, a `SurveyResponse` is created in `SCORED` status with a computed `score`, a `submitted_at` stamped from the logical clock, and the invitation transitions `SENT → RESPONDED` — `sent_count` decrements, `responded_count` increments.

The response's `score` is a weighted mean scaled to the 0–100 range. Each answer's `score` is multiplied by the corresponding question's `weight`, the products are summed, the result is multiplied by ten and divided by the sum of all question weights in the set, and the quotient is rounded half-up to two decimal places. Because each answer's `score` lies between 1 and 10, the weighted mean itself lies on a 0–10 scale; multiplying by ten (not by one hundred) is what lands the response `score` on the stated 0–100 range — a response where every answer is 10 scores exactly 100.00. Because weights are part of the instrument, changing the question set changes what a "9 out of 10" means — which is precisely what `comparability_factor` exists to correct for downstream.

A customer may instead opt out. The opt-out action — available on invitations in either `QUEUED` or `SENT`, and guarded by the same `X-User-ID` ownership check — transitions the invitation to `OPTED_OUT`, decrements whichever of `queued_count` or `sent_count` applied, increments `opted_out_count`, and permanently flips the customer's `do_not_contact` to `true`. That last side effect is the important one: a single opt-out on any wave silences future sampling for that customer across all dealers and all waves until the flag is explicitly cleared by a `PlatformAdmin`.

A `ComplianceAuditor` may suppress an invitation in `QUEUED` or `SENT` when contact tampering is suspected. Suppression moves the invitation to `SUPPRESSED` with the corresponding counter adjustments, and carries a cross-entity cascade: if the invitation was `SENT` and a response has already been recorded against it, that response transitions from `SCORED` to `EXCLUDED` with `excluded_reason` set to `MANIPULATION_CONFIRMED`. Suppression is the audit function's emergency brake — it removes a compromised invitation from the denominator and claws back any score it had already produced.

### 3.6. Scoring at Wave Close

When a wave closes, the system computes two numbers per dealer and writes them onto the dealer record. Both are recomputed from scratch against the closing wave's data; they are not incremental.

The response rate is the count of the dealer's invitations in this wave that ended in `RESPONDED`, divided by the total count of the dealer's invitations in this wave — every terminal status counts in the denominator, so `RESPONDED`, `EXPIRED`, `OPTED_OUT`, and `SUPPRESSED` all weigh against the dealer equally. The quotient is rounded half-up to four decimal places and stored as `current_response_rate`. A dealer with no invitations in the wave has a null rate — such a dealer is not scored for this wave and is treated as ineligible in tiering.

The composite score begins from the same population as the response rate's numerator: the dealer's `SurveyResponse` rows in this wave whose status is `SCORED`. `FLAGGED` responses — those under appeal — are excluded, as are `EXCLUDED` responses; only unscored-by-caveat responses enter the average. The mean of the individual `score` values is multiplied by ten to land on the 0–1000 scale and rounded half-up to two decimal places; this is the raw composite, reported on the wave summary but never used for tiering. The adjusted composite — the one stored as `current_score_adjusted` and consumed downstream — subtracts twenty-five points per `CONFIRMED` manipulation flag on the dealer, with the trailing-two-wave `confirmed_flag_count` as the multiplier, rounds half-up to two decimal places, and floors at zero so the adjusted score can never go negative.

Posture derivation runs immediately after, using the freshly written `current_score_adjusted` and the current `confirmed_flag_count`. The ladder is evaluated top-down: if the dealer has no score yet (the field is null), posture is `GOOD_STANDING`. Otherwise, if `confirmed_flag_count` is at least three, posture is `SUSPENDED`. Otherwise, if the count is at least two or the adjusted score is below seven hundred, posture is `PROBATION`. Otherwise, if the count is exactly one or the adjusted score is below eight hundred, posture is `WATCH`. Otherwise, the dealer is in `GOOD_STANDING`. The same derivation runs whenever a manipulation flag is confirmed, so a dealer's posture can degrade mid-wave — not just at close — and the resulting transitions are system-driven rather than user-initiated. A dealer whose posture lands on `SUSPENDED` triggers a further cascade: every `ActionPlan` they hold in `DRAFT` is immediately pushed to `SUBMITTED`, routing it to a field consultant without waiting for the principal.

### 3.7. Appeals: Contesting a Single Response

A `DealerPrincipal` who believes a specific response is unfair — the customer reviewed the wrong visit, the score reflects a factory-side parts delay, the response is fraudulent — may file an `Appeal`. The payload carries `response_id`, a free-text `reason`, and `expected_response_version` capturing the response's `version` as the dealer last observed it. Three validations guard the filing. The caller must be the dealer that owns the response — resolved by walking the response's invitation back to its transaction's `dealer_id` — or the request fails with `ERR_CROSS_REFERENCE_MISMATCH`. The response must currently be in `SCORED`; a response already `FLAGGED` or `EXCLUDED` rejects with `ERR_INVALID_STATE`. And the response must not already have an open appeal — one in `FILED` or `UNDER_REVIEW` — which would surface `ERR_APPEAL_ALREADY_OPEN`. The OCC check on `expected_response_version` runs at its priority position, after state validity: a mismatch against the response's current `version` is `ERR_STALE_VERSION`. Because each of these three checks sits at its own position in §2.9's priority order — state validity at position 6, optimistic concurrency at position 7, and the appeal singleton at position 15 — an earlier check masks a later one whenever both would fire on the same request. A filing against a response that is not `SCORED` always surfaces `ERR_INVALID_STATE`, even if the response already carries an open appeal (which is in fact the common way a response left `SCORED`); likewise `ERR_INVALID_STATE` masks `ERR_STALE_VERSION`, and `ERR_STALE_VERSION` masks `ERR_APPEAL_ALREADY_OPEN`.

A successful filing does two things atomically. The new `Appeal` is created in `FILED` status, with `dealer_id` resolved from the response's invitation transaction and `prior_response_status` capturing the response's status at the moment of filing. And the response itself transitions `SCORED → FLAGGED`, which removes it from every subsequent score computation sweep until the appeal resolves — the response's `version` increments as part of the transition.

Routing the appeal to review is a `RegionalManager` action: assignment moves `FILED → UNDER_REVIEW`. Decision belongs to `ComplianceAuditor`, who supplies an `outcome` and a `decision_rationale`. The rationale must be non-empty — an empty or missing rationale is `ERR_INVALID_REQUEST`. An `UPHELD` outcome moves the appeal to its terminal `UPHELD` state and cascades the response from `FLAGGED` to `EXCLUDED` with `excluded_reason` set to `APPEAL_UPHELD` — the response is permanently out of all scoring. A `DENIED` outcome terminates the appeal at `DENIED` and cascades the response back from `FLAGGED` to `SCORED`, restoring it to the input set for any future score computation.

### 3.8. Manipulation Flags: The Compliance Function

Independent of appeals, a `ComplianceAuditor` may open a `ManipulationFlag` against a dealer. The payload carries `dealer_id`, an optional `response_id` (null for dealer-level signals that do not implicate a specific response), a `kind` drawn from `COACHING`, `OPT_OUT_SUPPRESSION`, or `CONTACT_TAMPERING`, and a free-text `evidence` summary. The flag is born `OPEN`.

Resolution — also a `ComplianceAuditor` action — supplies an `outcome` of `CONFIRMED` or `DISMISSED`. A dismissal simply terminates the flag at `DISMISSED`. A confirmation carries the system's heaviest cascade. If the flag's `response_id` is non-null and that response is currently `SCORED`, the response transitions to `EXCLUDED` with `excluded_reason` set to `MANIPULATION_CONFIRMED`. The dealer's `confirmed_flag_count` is recomputed — it counts `CONFIRMED` flags over the trailing two closed waves — and posture is re-derived against the new count and the current `current_score_adjusted`. If the new posture is `SUSPENDED`, every `ActionPlan` the dealer holds in `DRAFT` transitions to `SUBMITTED`, escalating remediation out of the principal's hands.

The trailing-two-wave window for `confirmed_flag_count` is the deliberate middle ground between permanence and amnesia: a dealer cannot shed a confirmed flag by surviving one clean wave, but a flag from three waves ago no longer counts against posture.

### 3.9. Action Plans: Remediation for Underperformers

An `ActionPlan` is the structured response to a bad wave. Either a `DealerPrincipal` (drafting their own plan) or a `FieldConsultant` (drafting on the dealer's behalf) may create one, supplying `dealer_id`, the `wave_id` whose results triggered the plan, a `title`, an `items` array of `{action, owner, due_date}` entries with at least one item, and an overall `due_date`. The plan begins in `DRAFT`.

From `DRAFT`, the principal submits the plan for review — the transition is guarded by ownership (`X-User-ID` must equal the plan's `dealer_id`, failing with `ERR_FORBIDDEN`) and by posture: a dealer in `SUSPENDED` may not submit at all, and the request is rejected with `ERR_DEALER_SUSPENDED`. The suspended-dealer rule is the visible teeth of the posture ladder: once suspended, the dealer's path back runs through field consultation, not self-service. (Recall from §3.6 and §3.8 that reaching `SUSPENDED` auto-submits any of the dealer's draft plans anyway, so a suspension never strands work in `DRAFT`.)

A `FieldConsultant` reviews a `SUBMITTED` plan with an `outcome` and a `review_note`. The note must be non-empty — its absence is `ERR_INVALID_REQUEST`. An `APPROVED` outcome moves the plan to `APPROVED`; a `REJECTED` outcome moves it to `REJECTED`. Rejection is not terminal: the principal may revise, which returns the plan to `DRAFT` and clears `review_note` back to null, ready for another cycle. An `APPROVED` plan is started by the principal — again ownership-guarded — moving it to `IN_PROGRESS`. Completion belongs to the field consultant, whose action moves `IN_PROGRESS → COMPLETED`, the plan's only terminal state.

The overdue rule is lazy. Whenever a plan in `IN_PROGRESS` is read, and whenever a wave closes, the system compares the current logical time to the plan's `due_date`; if the clock has reached or passed the due date, the plan transitions to `OVERDUE`. Clock advances trigger the same evaluation on next read, so an `OVERDUE` badge appears promptly without requiring a synchronous sweep at clock-set time.

### 3.10. Incentive Settlement: Statements, Tiers, and Payment

The monetary consequence of a wave is the `IncentiveStatement`. Either a `PlatformAdmin` or a `RegionalManager` may create one against a (`dealer_id`, `wave_id`) pair, supplying `expected_wave_version` for the OCC guard described in §2.5. The wave need not be closed — statements may be drafted provisionally against an open wave's projected numbers — but the OCC contract ensures the caller is reasoning about a wave version they have actually observed.

Creation computes three values and stores them on the statement. `score_used` is the dealer's current `current_score_adjusted`; `response_rate_used` is the dealer's current `current_response_rate`. `eligible_margin_cents` is the sum of `margin_cents` over the dealer's transactions whose `completed_at` falls within the wave's period. The `tier` is derived by a strict evaluation order — eligibility first, then tier selection by score. If either `score_used` or `response_rate_used` is null, the tier is `INELIGIBLE`. Otherwise, if `response_rate_used` is below 0.30 — the minimum response-rate gate that makes survey administration quality a precondition of payment — the tier is `INELIGIBLE`. Otherwise, tier selection by score: at least 900 earns `GOLD`; at least 800 but below 900 earns `SILVER`; at least 700 but below 800 earns `BRONZE`; below 700 is `INELIGIBLE`. `payout_cents` is `eligible_margin_cents` multiplied by the tier rate — eight percent for `GOLD`, five percent for `SILVER`, two percent for `BRONZE`, zero for `INELIGIBLE` — rounded half-up to zero decimal places, so payouts land on whole cents.

A statement is born `PROVISIONAL`. If a prior `PROVISIONAL` statement already exists for the same (`dealer_id`, `wave_id`), creating the new one supersedes the old: the old statement transitions to `SUPERSEDED`, and the new statement's `supersedes_id` points back at it. This is the mechanism by which restatements — typically driven by appeal resolutions or flag confirmations that arrived after the first statement was drafted — leave a clean audit trail rather than an in-place edit. Statement creation also increments the wave's `version` by one, which means a second statement attempt carrying the now-stale `expected_wave_version` will fail the OCC check.

At wave finalize, every `PROVISIONAL` statement for the wave promotes to `FINAL`. A `PlatformAdmin` may then mark a `FINAL` statement paid, transitioning it to `PAID`. `PAID` and `SUPERSEDED` are the terminal states; there is no path back.

### 3.11. Benchmarks and Historical Comparability

Two read-side computations round out the dealer-facing story. The regional benchmark, requested against a wave and a dealer, ranks the target dealer among peers. The eligible peer set is the dealers in the same `region_id` who have at least one transaction in the wave period and a non-null `current_score_adjusted`. The target's rank is one plus the count of eligible peers whose adjusted score is strictly greater than the target's — so dealers tied on score share a rank. The percentile is one hundred times the quantity one minus the ratio of (rank minus one) to the eligible count, rounded half-up to two decimal places; when the target is the only eligible dealer, the count is treated as one so the percentile lands at 100.00 rather than dividing by zero. The response shape includes `region_id`, `wave_id`, `dealer_count`, `dealer_rank`, and `percentile`.

Score history answers a different question: how has this dealer trended across instrument changes? For every prior wave in `CLOSED` or `FINALIZED` status with at least one `SCORED` response for the dealer, the history reports `wave_id`, the `raw_score` as computed under that wave's own question set on the 0–1000 scale, and a `normalized_score` equal to the raw score multiplied by that wave's question set's `comparability_factor`, rounded half-up to two decimal places. Crucially, the factor applied is the historical set's own — not the current set's — so a wave administered under a lenient instrument stays corrected by its own leniency factor even after the network has moved on.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a region, a dealer, a question set, a wave, a transaction, an appeal, a flag, a statement, a plan, a response) return `201 Created`. Operations that modify an existing resource — state transitions like open, close, finalize, send, opt-out, suppress, assign, decide, resolve, pay, submit, review, revise, start, complete, activate, retire — return `200 OK`. The clock-control endpoint returns `200 OK`. All list and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/survey/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/survey/regions` | Create a region | PlatformAdmin |
| GET | `/survey/regions/{id}` | Get a region | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant |
| POST | `/survey/dealers` | Create a dealer | PlatformAdmin |
| GET | `/survey/dealers/{id}` | Get a dealer | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant, DealerPrincipal |
| GET | `/survey/dealers` | List dealers (optional `region_id` filter) | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant |
| GET | `/survey/dealers/{id}/score-history` | Historical score series with comparability normalization | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant, DealerPrincipal |
| POST | `/survey/departments` | Create a department under a dealer | PlatformAdmin |
| GET | `/survey/departments/{id}` | Get a department | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant, DealerPrincipal |
| GET | `/survey/dealers/{id}/departments` | List departments of a dealer | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant, DealerPrincipal |
| POST | `/survey/advisors` | Create an advisor under a department | PlatformAdmin |
| GET | `/survey/advisors/{id}` | Get an advisor | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant, DealerPrincipal |
| GET | `/survey/departments/{id}/advisors` | List advisors of a department | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant, DealerPrincipal |
| POST | `/survey/customers` | Register a customer | PlatformAdmin |
| GET | `/survey/customers/{id}` | Get a customer | PlatformAdmin, ComplianceAuditor |
| POST | `/survey/question-sets` | Create a question set | PlatformAdmin |
| GET | `/survey/question-sets/{id}` | Get a question set | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant |
| POST | `/survey/question-sets/{id}/activate` | Activate a question set (singleton) | PlatformAdmin |
| POST | `/survey/question-sets/{id}/retire` | Retire a question set | PlatformAdmin |
| POST | `/survey/waves` | Create a wave pinned to a question set | PlatformAdmin |
| GET | `/survey/waves/{id}` | Get a wave with counters | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant, DealerPrincipal |
| GET | `/survey/waves` | List waves, filterable by `question_set_id` and `status` | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant |
| POST | `/survey/waves/{id}/open` | Open wave; runs sampling sweep | PlatformAdmin |
| POST | `/survey/waves/{id}/close` | Close wave; expires invitations, recomputes dealer scores/posture | PlatformAdmin |
| POST | `/survey/waves/{id}/finalize` | Finalize wave; promotes statements | PlatformAdmin |
| GET | `/survey/waves/{id}/benchmarks/{dealer_id}` | Regional benchmark for a dealer in this wave | PlatformAdmin, RegionalManager, ComplianceAuditor, FieldConsultant, DealerPrincipal |
| GET | `/survey/waves/{id}/invitations` | List invitations in a wave, filterable by `status` | PlatformAdmin, RegionalManager, ComplianceAuditor, SurveyVendor |
| POST | `/survey/transactions` | Record a sale or service visit | PlatformAdmin |
| GET | `/survey/transactions/{id}` | Get a transaction | PlatformAdmin, ComplianceAuditor, RegionalManager |
| GET | `/survey/transactions` | List transactions, filterable by `dealer_id`, `department_id`, `advisor_id`, `customer_id`, `kind` | PlatformAdmin, ComplianceAuditor, RegionalManager |
| GET | `/survey/dealers/{id}/transactions` | List transactions for a dealer, filterable by `kind` | PlatformAdmin, ComplianceAuditor, RegionalManager, DealerPrincipal |
| GET | `/survey/invitations/{id}` | Get an invitation | PlatformAdmin, ComplianceAuditor, SurveyVendor, Customer |
| GET | `/survey/invitations` | List invitations, filterable by `transaction_id`, `customer_id`, `wave_id`, `question_set_id`, `status` | PlatformAdmin, ComplianceAuditor, SurveyVendor, RegionalManager |
| POST | `/survey/invitations/{id}/send` | Send an invitation (QUEUED → SENT) | SurveyVendor |
| POST | `/survey/invitations/{id}/responses` | Submit a response to an invitation | Customer |
| GET | `/survey/invitations/{id}/responses` | List the response(s) for an invitation (0 or 1) | PlatformAdmin, ComplianceAuditor, RegionalManager, DealerPrincipal |
| POST | `/survey/invitations/{id}/opt-out` | Customer opts out; flips `do_not_contact` | Customer |
| POST | `/survey/invitations/{id}/suppress` | Compliance suppresses an invitation | ComplianceAuditor |
| GET | `/survey/responses/{id}` | Get a response | PlatformAdmin, ComplianceAuditor, RegionalManager, DealerPrincipal |
| GET | `/survey/responses` | List responses, filterable by `invitation_id`, `status` | PlatformAdmin, ComplianceAuditor, RegionalManager |
| POST | `/survey/appeals` | File an appeal on a response | DealerPrincipal |
| GET | `/survey/appeals/{id}` | Get an appeal | PlatformAdmin, ComplianceAuditor, RegionalManager, DealerPrincipal |
| GET | `/survey/appeals` | List appeals, filterable by `response_id`, `dealer_id`, `status` | PlatformAdmin, ComplianceAuditor, RegionalManager |
| GET | `/survey/dealers/{id}/appeals` | List appeals for a dealer | PlatformAdmin, ComplianceAuditor, RegionalManager, DealerPrincipal |
| POST | `/survey/appeals/{id}/assign` | Assign appeal to review | RegionalManager |
| POST | `/survey/appeals/{id}/decide` | Decide appeal (UPHELD or DENIED) | ComplianceAuditor |
| POST | `/survey/flags` | Open a manipulation flag | ComplianceAuditor |
| GET | `/survey/flags/{id}` | Get a flag | PlatformAdmin, ComplianceAuditor, RegionalManager |
| GET | `/survey/flags` | List flags, filterable by `dealer_id`, `response_id`, `status` | PlatformAdmin, ComplianceAuditor, RegionalManager |
| GET | `/survey/dealers/{id}/flags` | List flags for a dealer | PlatformAdmin, ComplianceAuditor, RegionalManager, DealerPrincipal |
| POST | `/survey/flags/{id}/resolve` | Resolve a flag (CONFIRMED or DISMISSED) | ComplianceAuditor |
| POST | `/survey/statements` | Create a provisional incentive statement | PlatformAdmin, RegionalManager |
| GET | `/survey/statements/{id}` | Get a statement | PlatformAdmin, RegionalManager, ComplianceAuditor, DealerPrincipal |
| GET | `/survey/statements` | List statements, filterable by `dealer_id`, `wave_id`, `supersedes_id`, `status` | PlatformAdmin, RegionalManager, ComplianceAuditor |
| GET | `/survey/dealers/{id}/statements` | List statements for a dealer, filterable by `wave_id` | PlatformAdmin, RegionalManager, ComplianceAuditor, DealerPrincipal |
| POST | `/survey/statements/{id}/pay` | Mark a FINAL statement paid | PlatformAdmin |
| POST | `/survey/action-plans` | Draft an action plan | DealerPrincipal, FieldConsultant |
| GET | `/survey/action-plans/{id}` | Get an action plan (lazy OVERDUE evaluation) | PlatformAdmin, RegionalManager, FieldConsultant, DealerPrincipal |
| GET | `/survey/action-plans` | List action plans, filterable by `dealer_id`, `wave_id`, `status` | PlatformAdmin, RegionalManager, FieldConsultant, ComplianceAuditor |
| GET | `/survey/dealers/{id}/action-plans` | List action plans for a dealer | PlatformAdmin, RegionalManager, FieldConsultant, DealerPrincipal |
| POST | `/survey/action-plans/{id}/submit` | Submit plan for review | DealerPrincipal |
| POST | `/survey/action-plans/{id}/review` | Field consultant reviews a plan | FieldConsultant |
| POST | `/survey/action-plans/{id}/revise` | Return a rejected plan to DRAFT | DealerPrincipal |
| POST | `/survey/action-plans/{id}/start` | Begin execution of an approved plan | DealerPrincipal |
| POST | `/survey/action-plans/{id}/complete` | Mark an in-progress plan complete | FieldConsultant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 400 |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ACTIVE_QUESTION_SET_EXISTS` | 409 |
| `ERR_QUESTION_SET_NOT_ACTIVE` | 409 |
| `ERR_WAVE_NOT_OPEN` | 409 |
| `ERR_WAVE_STILL_OPEN` | 422 |
| `ERR_RESPONSE_WINDOW_CLOSED` | 422 |
| `ERR_CONTACT_RESTRICTED` | 422 |
| `ERR_APPEAL_ALREADY_OPEN` | 409 |
| `ERR_APPEALS_PENDING` | 409 |
| `ERR_FLAGS_PENDING` | 409 |
| `ERR_DEALER_SUSPENDED` | 422 |
