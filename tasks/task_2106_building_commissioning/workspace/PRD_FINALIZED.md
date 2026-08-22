# Building Commissioning API — Product Requirements Document

## 1. Introduction

A commissioning authority (CxA) firm is hired to prove that a building actually does what its owner asked for. That proof is not a single sign-off; it is a chain of custody that runs from the written Owner Project Requirements, through design review and submittal verification, through equipment-by-equipment pre-functional checklists, through witnessed functional performance testing, into a live deficiency log, and finally out into training records, systems-manual sections, seasonal re-tests and green-certification credit packages. Today most CxA firms carry that chain in spreadsheets. The chain breaks quietly: a requirement is revised after a test plan was written against it, a checklist is signed by the same person who executed it, a credit package is submitted on evidence that a failed re-test invalidated a week earlier, and nobody notices until the certifying body asks.

This API is the system of record for that chain. Its job is not merely to store commissioning artifacts but to keep them mutually consistent at all times: when a functional test fails, the deficiency it opens must immediately withdraw the equipment's verified standing, invalidate every certification-evidence row that pointed at that equipment, and pull back any credit package that was submitted on the strength of it — in one request, with no background reconciliation and no eventual consistency. The same discipline runs in reverse: when the deficiency is genuinely corrected and closed with re-test evidence, every quantity the deficiency consumed must be returned exactly, to the cent and to the weight unit.

Two audiences pull in opposite directions and the design accommodates both. The owner's representative wants a conservative, defensible number before signing an acceptance certificate or awarding a certification credit. The construction team wants an optimistic, forward-looking read so it can see whether the project is trending toward closeout. The system therefore maintains **two variants** of its central completion measure and of its retro-commissioning savings estimate, computes both from the same underlying rows, and is explicit about which variant governs which decision. Everything is scoped to a single commissioning engagement, and every engagement carries a derived **readiness posture** that throttles what may be done next as the deficiency backlog grows or clears.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply to every endpoint in the API. The domain workflows in Section 3 assume everything stated here.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the individual acting, and `X-User-Role`, declaring the capacity in which they act. A request that omits either header, or supplies either as an empty string, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose `X-User-Role` is not one of the five recognised roles is rejected with the same `ERR_UNAUTHENTICATED` (HTTP 401) — an unknown role is treated as a failure to authenticate, not as a permission problem. A request whose role is recognised but is not listed for the endpoint in the Section 4 table is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The five roles are `PlatformAdmin`, `CxAuthority`, `Contractor`, `DesignTeam`, and `OwnerRepresentative`.

- A `PlatformAdmin` is the operator of the commissioning software itself. It opens engagements, registers equipment alongside the commissioning authority, and drives the server's logical clock. It never signs off commissioning work.
- A `CxAuthority` is the commissioning authority firm's agent — the professional whose signature the certification body ultimately relies on. It reviews submittals, owns pre-functional checklists, witnesses functional performance tests, runs the issue log, schedules seasonal work, records retro-commissioning measures and assembles certification credit packages.
- A `Contractor` is the installing contractor. It advances the installation status of equipment, records and executes pre-functional checklist items, proposes corrective actions against deficiencies, and delivers training sessions and closeout documents.
- A `DesignTeam` is the architect and engineer of record. It lodges and resubmits submittals and contributes systems-manual sections.
- An `OwnerRepresentative` acts for the building owner. It owns the Owner Project Requirements, approves the commissioning plan, defers deficiencies to seasonal testing, adjudicates certification credits and issues acceptance certificates.

Every one of the five roles carries an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `CxAuthority`, `Contractor`, `DesignTeam` or `OwnerRepresentative`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity in this system: the server never resolves it to a stored row and never compares it to any entity's `id`. What the server does with it is record it where a transition explicitly captures the actor — as `executed_by_user_id` and `verified_by_user_id` on a pre-functional checklist, as `recorded_by_user_id` on an individual checklist item, as `witness_user_id` on a functional test, as `opened_by_user_id` and `proposed_by_user_id` on an issue, and as `delivered_by_user_id` and `accepted_by_user_id` on a closeout deliverable. Those recorded values are then compared against the acting `X-User-ID` of a *later* step on the *same* artifact, which is the whole mechanism behind the segregation-of-duties rules in Section 2.11. There is no resource-ownership model beyond that: no role is scoped to a subset of projects, and any authorised role may act on any engagement.

Where the Section 4 table lists an endpoint's authorised roles as "Any", it means all five roles named above.

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

List endpoints are paginated through two optional query parameters. `limit` sets the maximum number of rows returned; it defaults to 10, has a minimum of 1 and a maximum of 100. `offset` sets the number of rows to skip; it defaults to 0 and its minimum is 0. A `limit` below 1 or above 100, or a negative `offset`, is a request-shape failure and is rejected with `ERR_VALIDATION` (HTTP 400).

Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by creation timestamp in ascending order.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` is the number of rows matching the request's filters before pagination is applied, and `has_more` is true when rows remain beyond the current page.

### 2.4. Common Resource Properties, Timestamps and the Logical Clock

Every stored resource in this system — commissioning engagements, owner requirements, commissioning plans, submittals, equipment units, pre-functional checklists, functional tests, issues, deferred tests, closeout deliverables, certification credits, credit evidence rows and energy baselines alike — carries the same four system-managed properties:

- `id` — a server-minted UUID. It carries no type prefix and no embedded meaning; clients must never construct one.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations the server performs on its own initiative as part of a cascade.
- `version` — an integer that starts at 1 and increments by one on every mutation of the row. This is the value optimistic concurrency control reads (Section 2.9).

No entity in this system is exempt: there is no resource that carries only `id` and `created_at`.

Embedded structures that are not standalone resources do not receive these properties. The line items inside a pre-functional checklist are the one such structure: each item is an object holding `item_code`, `description`, `is_safety_critical`, `result`, `recorded_by_user_id` and `recorded_at`, stored in insertion order inside the checklist's `items` array, and it has no `id`, no `version` and no independent addressability.

**The logical clock.** This service does not read wall-clock time for business decisions. It keeps a single logical clock that reads exactly `2026-08-01T00:00:00Z` until an administrator moves it, and that never falls back to real time thereafter. An administrator-only test-driving capability sets the clock to a supplied `to_iso8601` instant and answers with the new `current_utc`. Every business timestamp the server stamps reads this clock — `opened_at`, `approved_at`, `started_at`, `completed_at`, `executed_at`, `session_start`, `submitted_at` and `staled_at` — and every window comparison and every issue-aging computation reads it too. Because deficiency aging is clock-dependent, moving the clock recomputes the severity index and re-derives the readiness posture for **every** engagement in the system, not only for one.

### 2.5. Order of Rejection: How a Request Is Screened

When a request violates more than one rule, exactly one error is returned and no side effect of any kind is written. The server evaluates the checks below strictly in the order listed, and the **first** failing check decides the response. This ordering is a contract: a request that is both unauthenticated and semantically nonsensical answers `ERR_UNAUTHENTICATED`, never `ERR_VALIDATION`; a request naming a non-existent project on a frozen engagement answers the not-found error, never `ERR_PROJECT_FROZEN`.

1. Both `X-User-Role` and `X-User-ID` are present and non-empty — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. `X-User-Role` names one of `PlatformAdmin`, `CxAuthority`, `Contractor`, `DesignTeam`, `OwnerRepresentative` — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
3. The named role appears in the endpoint's authorised-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint.
4. Every identifier embedded in the request path resolves to a stored row, checked from left to right, answering with the not-found code of the first identifier that fails: `ERR_PROJECT_NOT_FOUND`, `ERR_REQUIREMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHECKLIST_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`, `ERR_DEFERRED_TEST_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_CREDIT_NOT_FOUND` or `ERR_BASELINE_NOT_FOUND` (all 404). Applies to every endpoint that carries a path identifier.
5. The request body carries every required field with a well-formed type, every enumerated value is a declared member of its enumeration, every numeric field satisfies its declared range constraint, every datetime parses as ISO 8601 UTC, and `limit` and `offset` are inside the pagination bounds — otherwise `ERR_VALIDATION` (400). Applies to every endpoint.
6. Every foreign key supplied in the request **body** resolves to a stored row, checked in the field order the endpoint declares its inputs, answering `ERR_PROJECT_NOT_FOUND`, `ERR_REQUIREMENT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND` or `ERR_TEST_NOT_FOUND` (all 404). This guards the creation of owner requirements, commissioning plans, submittals, equipment units, pre-functional checklists, functional tests, issues, deferred tests, closeout deliverables, certification credits, credit evidence rows and energy baselines, and it also guards issue closure verification.
7. Every entity named anywhere in the request resolves to the **same** engagement as the primary resource — the equipment, the requirement, the issue, the re-test, the credit and the deliverable must all share one `project_id` — otherwise `ERR_PROJECT_SCOPE_MISMATCH` (409). This guards submittal creation, pre-functional checklist creation, functional test scheduling, issue logging, deferred test scheduling, closeout deliverable planning and credit evidence attachment.
8. `expected_project_version` equals the engagement's current `version` — otherwise `ERR_STALE_PROJECT_VERSION` (412). This guards commissioning plan creation and certification credit submission, and only those two.
9. The engagement's `readiness_posture` is not `FROZEN` — otherwise `ERR_PROJECT_FROZEN` (409). This guards phase advance, acceptance issuance, deferred test scheduling, closeout deliverable acceptance and certification credit submission — five operations.
10. The engagement's `delivery_phase` permits the operation — otherwise `ERR_PHASE_NOT_ALLOWED` (409). Phase advance accepts only the single next phase along `PLANNING` → `DESIGN` → `CONSTRUCTION` → `FUNCTIONAL_TESTING` → `ACCEPTANCE` → `WARRANTY` → `CLOSED`; acceptance issuance requires the engagement to be in `ACCEPTANCE`; commissioning plan approval requires the engagement to be in `PLANNING` or `DESIGN`.
11. The target resource is in a status from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). This applies to every state-changing action endpoint in the system.
12. The referenced equipment unit is commissioning-ready — otherwise `ERR_EQUIPMENT_NOT_READY` (409). Scheduling a **new** functional test requires the unit to be `PREFUNCTIONAL_VERIFIED` *and* `STARTED_UP`; scheduling a re-test and starting a test require only `STARTED_UP`, so a unit that the very failure being re-tested demoted to `UNVERIFIED` can still be re-tested; executing a pre-functional checklist requires the unit to be `INSTALLED` or `STARTED_UP`. Four operations are guarded: functional test scheduling, re-test scheduling, test start and checklist execution.
13. The engagement's newest commissioning plan — the one with the greatest `created_at` — has status `APPROVED`, otherwise `ERR_PLAN_NOT_APPROVED` (409). Three operations are guarded: functional test scheduling, re-test scheduling and certification credit submission.
14. The engagement's newest commissioning plan has `pin_stale` false — otherwise `ERR_PLAN_PIN_STALE` (409). Only certification credit submission is guarded.
15. The acting `X-User-ID` differs from the user id recorded on the preceding step of the same artifact — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Two operations are guarded: a checklist verifier may not be the checklist's executor, and a deliverable acceptor may not be its deliverer.
16. Closing an issue whose `origin` is `FUNCTIONAL` and whose `severity` is `S1` or `S2` supplies `closure_retest_id`, and the functional test it names has status `PASSED` — otherwise `ERR_RETEST_EVIDENCE_REQUIRED` (422). Only issue closure verification is guarded.
17. No checklist item whose `is_safety_critical` is true carries `result` of `FAIL` — otherwise `ERR_SAFETY_ITEM_FAILED` (422). Only checklist verification is guarded.
18. `scheduled_end` is strictly after `scheduled_start`, and `window_end` is strictly after `window_start` — otherwise `ERR_INVALID_WINDOW` (422). Three operations are guarded: functional test scheduling, re-test scheduling and deferred test scheduling.
19. The buffered witness-window occupancy check finds fewer colliding occupants than the engagement's `witness_capacity` — otherwise `ERR_WITNESS_WINDOW_CONFLICT` (409). Two operations are guarded: functional test scheduling and re-test scheduling.
20. The seasonal-window occupancy check finds no colliding occupant on the same equipment unit — otherwise `ERR_SEASONAL_WINDOW_CONFLICT` (409). Only deferred test scheduling is guarded.
21. The logical clock is at or after `window_start` and strictly before `window_end` — otherwise `ERR_OUTSIDE_SEASONAL_WINDOW` (409). Only deferred test execution is guarded.
22. The supplied `closure_retest_id` names a functional test whose `equipment_id` equals the issue's `equipment_id` — otherwise `ERR_RETEST_SCOPE_MISMATCH` (422). Only issue closure verification is guarded.
23. The supplied `requirement_id` appears in the `pinned_requirement_ids` array of the engagement's newest approved commissioning plan — otherwise `ERR_REQUIREMENT_NOT_PINNED` (422). Two operations are guarded: functional test scheduling and deferred test scheduling.
24. The supplied `evidence_ref_id` resolves to a row of the entity family its `evidence_type` declares, and that row belongs to the credit's engagement — otherwise `ERR_EVIDENCE_REF_INVALID` (422). Only credit evidence attachment is guarded.
25. The checklist carries at least one item, meaning `item_count` is 1 or more — otherwise `ERR_CHECKLIST_EMPTY` (422). Only checklist execution is guarded.
26. No checklist item is left with `result` of `PENDING` — otherwise `ERR_CHECKLIST_INCOMPLETE` (422). Only checklist execution is guarded.
27. When appending an item, its `item_code` is not already present on the checklist, answering `ERR_DUPLICATE_ITEM_CODE` (422) if it is; when recording a result, the supplied `item_code` names an item the checklist already carries, answering `ERR_ITEM_NOT_FOUND` (422) if it does not. Two operations are guarded: item append and item result recording.
28. `fresh_evidence_count` is greater than or equal to `required_evidence_count` — otherwise `ERR_EVIDENCE_INSUFFICIENT` (422). Only certification credit submission is guarded.
29. For a deliverable whose `deliverable_kind` is `TRAINING_SESSION`, `coverage_ratio` is at least 0.80 — otherwise `ERR_TRAINING_COVERAGE_INSUFFICIENT` (422). Only closeout deliverable acceptance is guarded.
30. The submittal's `review_round` is below 3 — otherwise `ERR_REVIEW_ROUNDS_EXCEEDED` (422). Only submittal resubmission is guarded.
31. The engagement's `project_type` is `RETRO_COMMISSIONING` — otherwise `ERR_RETRO_ONLY` (422). Only energy baseline creation is guarded.
32. The requested savings variant is permitted for the engagement's `certification_target`: an `ENHANCED` target accepts only `MEASURED` — otherwise `ERR_VARIANT_NOT_PERMITTED` (422). Only savings certification is guarded.
33. The resulting `retainage_withheld_cents` does not exceed the retainage cap — otherwise `ERR_RETAINAGE_CAP_EXCEEDED` (422). Only issue logging is guarded.
34. The `FINAL` variant of the acceptance completion score meets the floor the requested certificate demands — otherwise `ERR_ACCEPTANCE_SCORE_TOO_LOW` (422). Only acceptance issuance is guarded.
35. The open-deficiency condition the requested acceptance kind demands is satisfied — otherwise `ERR_OPEN_BLOCKING_ISSUES` (422). Only acceptance issuance is guarded.

### 2.6. The Readiness Posture Gate

Each engagement carries a `readiness_posture` that is never set by a client and never appears in any request body. It is a pure function of the engagement's `issue_severity_index`, which in turn is an aged, severity-weighted score over the engagement's live deficiencies.

**Computing the index.** The input set is every issue belonging to the engagement whose `status` is `OPEN` or `IN_REVIEW`. Issues in `DEFERRED`, `VERIFIED_CLOSED` or `VOID` contribute nothing at all. The live issues are walked in ascending order of their `created_at` — because the result is a sum, the order changes nothing observable, but it is pinned so that two implementations audit identically. For each live issue the server computes four things in sequence:

- **Age.** Subtract the issue's `opened_at` from the current logical clock to get an elapsed duration, which is never negative, and convert it to whole elapsed days by discarding any partial day (a duration of one day is 86,400 seconds).
- **Aging steps.** Divide the whole elapsed days by the fourteen-day aging step and discard the remainder, giving the number of complete fortnights the deficiency has been open.
- **Aging multiplier.** Start at 1.00 and add 0.25 for each complete fortnight, then cap the result at 2.00. A deficiency opened today multiplies by 1.00; one open for exactly fourteen days multiplies by 1.25; one open for four or more complete fortnights multiplies by 2.00 and no more.
- **Blocking multiplier.** Multiply by 2.0 when the issue's `blocks_acceptance` flag is true, and by 1.0 when it is false.

The issue's contribution is its severity weight multiplied by its aging multiplier multiplied by its blocking multiplier, **rounded half up to two decimal places at that point**. The severity weights are 25.0 for `S1`, 12.0 for `S2`, 8.0 for `S3` and 2.0 for `S4`. The per-issue contributions are then summed, the sum is rounded half up to two decimal places again, and the result is capped at 100.00. Rounding per issue and then summing is the rule; summing unrounded products and rounding once at the end is explicitly not the rule and can produce a different number.

**Deriving the posture.** Immediately after every recomputation of the index, the posture is re-derived from it alone. An index of 40.00 or more yields `FROZEN`. An index below 40.00 but at or above 16.00 yields `RESTRICTED`. An index below 16.00 yields `OPEN`. The lower bounds are inclusive: exactly 40.00 is `FROZEN`, exactly 16.00 is `RESTRICTED`, and 15.99 is `OPEN`. Because the derivation is total, every posture pair is reachable in both directions — `OPEN` to `RESTRICTED`, `OPEN` to `FROZEN`, `RESTRICTED` to `FROZEN`, `FROZEN` to `RESTRICTED`, `FROZEN` to `OPEN`, and `RESTRICTED` to `OPEN` — and each posture change is itself a mutation of the engagement that increments its `version` by one and refreshes its `updated_at`.

**What the posture does.** A `RESTRICTED` posture is advisory: it changes nothing about what may be done, and exists so that a project manager can see the backlog trending badly before it bites. A `FROZEN` posture is hard. While an engagement is `FROZEN`, five operations are refused with `ERR_PROJECT_FROZEN`: advancing the delivery phase, issuing an acceptance certificate, scheduling seasonal or deferred testing, accepting a closeout deliverable, and submitting a certification credit package. Entering `FROZEN` additionally moves every deferred test of the engagement that is `PLANNED` into `BLOCKED`. Leaving `FROZEN` — whether the posture lands on `RESTRICTED` or on `OPEN` — returns every `BLOCKED` deferred test of that engagement to `PLANNED`. A posture change from `RESTRICTED` to `OPEN` touches no deferred test, because nothing was blocked in the first place.

The index is recomputed, and the posture re-derived, after every issue creation, resolution proposal, closure verification, re-opening, deferral and voiding; after every advance of the logical clock; and after every seasonal sweep.

### 2.7. Retainage: the Withheld-Money Invariant

Money withheld against open deficiencies is the first of two conserved quantities the system guarantees. Each issue freezes a `retainage_hold_cents` at the moment it is created — computed once, never recomputed, even if the equipment's contract value or criticality is later understood differently.

The per-issue hold is derived from three inputs. The **base** is the equipment unit's `contract_value_cents` when the issue names an `equipment_id`, and the engagement's own `contract_value_cents` when it does not. The **criticality factor** is 1.5 for `LIFE_SAFETY` equipment, 1.2 for `CRITICAL` equipment and 1.0 for `STANDARD` equipment; an issue with no equipment always uses the `STANDARD` factor of 1.0. The **base hold rate** comes from the issue's own severity: 0.05 for `S1`, 0.02 for `S2`, 0.005 for `S3` and 0.0 for `S4`. Multiply base by rate by factor and round half up to a whole number of cents — that is the issue's frozen hold. An `S4` issue therefore always freezes a hold of zero.

The engagement's `retainage_withheld_cents` is the sum of `retainage_hold_cents` over the issues of that engagement whose `status` is `OPEN`, `IN_REVIEW` or `DEFERRED`. Note that `DEFERRED` issues keep their hold even though they have left the severity index: deferring a deficiency to a seasonal test relieves posture pressure but does not release the owner's money. Issues in `VERIFIED_CLOSED` and `VOID` are excluded entirely. The order of operations in the roll-up is pinned: each issue is rounded to whole cents **first**, and the already-rounded per-issue holds are **then** summed. Summing the unrounded products and rounding the total once is a different rule and may differ by one or more cents; it is not what this system does.

A retainage cap protects the contractor. The cap is the engagement's `contract_value_cents` multiplied by 0.10 with any fractional cent discarded — that is, the largest whole number of cents not exceeding ten percent of the contract value. Logging a new deficiency whose hold would push `retainage_withheld_cents` above that cap is refused with `ERR_RETAINAGE_CAP_EXCEEDED` and **no issue row is written at all**; the deficiency simply does not exist, and none of the cascades a new issue would have triggered run.

The invariant the system guarantees is exact reversal: closing, voiding or seasonally discharging a deficiency drops `retainage_withheld_cents` by exactly that issue's frozen `retainage_hold_cents`, and re-opening it grows the figure back by exactly the same amount. There is no drift and no recomputation from current contract values.

### 2.8. Conserved Roll-Ups and Cross-Aggregate Cascades

The engagement row is a materialised summary of its sub-trees, and every figure on it must agree with the rows beneath it after every request. Besides `readiness_posture`, `issue_severity_index` and `retainage_withheld_cents`, the engagement maintains:

- `verified_prefunctional_units` — the sum of `weight_units` over every equipment unit of the engagement whose pre-functional checklist is `VERIFIED`. This is the second conserved quantity: verification adds the unit's weight, and the compensating rejection subtracts exactly the same weight, so a verify-then-reject cycle must leave the figure precisely where it started.
- `open_blocking_issue_count` — the number of issues of the engagement whose `status` is `OPEN` or `IN_REVIEW` and whose `blocks_acceptance` is true.
- `acceptance_completion_score` — the `PROVISIONAL` variant of the acceptance completion score (Section 3.9), refreshed on every contributing mutation.
- `final_acceptance_score` — the `FINAL` variant, which starts as null and is persisted only when an acceptance certificate is issued.
- `acceptance_kind` — null until an acceptance certificate is issued, then `SUBSTANTIAL` or `FINAL`.
- `withdrawn_credit_count` — the number of certification credits this engagement has driven from `SUBMITTED` to `WITHDRAWN`.
- `total_awarded_points` — the sum of `awarded_points` over the engagement's credits whose `status` is `AWARDED`.

Reconciliation is **immediate**. There is no background job, no eventual convergence and no lazy recomputation on read: by the time a mutating request returns, every roll-up it touched is already correct. A single request routinely mutates several aggregates that are not in a parent-child relationship at all — a functional test result reaches equipment, issues, evidence rows and credit packages in one transaction. Each entity the cascade touches has its own `updated_at` refreshed and its own `version` incremented, exactly as if a client had modified it directly.

The engagement's `version` deserves particular care because optimistic concurrency reads it. It is incremented by one on each of the following: advancing the delivery phase; issuing an acceptance certificate; running the seasonal sweep; creating a commissioning plan; verifying a pre-functional checklist; rejecting a pre-functional checklist; recording a functional test result; logging an issue; verifying an issue closure; re-opening an issue; deferring an issue; voiding an issue; executing a deferred test; accepting a closeout deliverable; returning a closeout deliverable; submitting a certification credit; and adjudicating a certification credit. A posture change carries its **own** increment on top of the increment of whichever request provoked it, so a single deficiency log that pushes the index over 40.00 advances the engagement's `version` twice.

### 2.9. Guarding Against Stale Project Views

Two write operations snapshot an engagement's whole posture, and both therefore require the caller to prove that its view of the engagement is current. Both use the same request field and the same rejection.

Creating a commissioning plan — `POST /cx-plans` — requires a non-optional `expected_project_version` in the request body, carrying the `version` of the target engagement as the client last observed it. A newly created plan legitimately supersedes every prior plan of the same engagement, so the writer must demonstrate that its view of the approved requirement set, the posture and the acceptance figures is current before that supersede is allowed to land. If `expected_project_version` does not equal the engagement's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP 412, and no plan is created.

Submitting a certification credit package — `POST /certification-credits/{id}/submit` — likewise requires a non-optional `expected_project_version` carrying the engagement's last-observed `version`. Submission snapshots the evidence posture of the whole engagement; when the engagement's `version` has advanced since the client read it, because a cascade staled evidence, a deficiency was logged or the posture moved, the submission is built on a view that no longer holds and is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP 412.

No other endpoint takes a version field of any kind. Endpoints not named above perform no concurrency check, and supplying an unrecognised field to them has no effect on their outcome.

### 2.10. Numeric Precision, Rounding and Interval Geometry

Unless a rule states otherwise, every derived number in this system is rounded **half up** to **2 decimal places**. Three quantities depart from that default and each says so explicitly at the point of definition: `completeness_ratio` and `coverage_ratio` are rounded half up to 4 decimal places, and per-issue retainage holds are rounded half up to whole cents. Rounding is applied where the rule places it and nowhere else — the retainage roll-up and the severity index both round per row and then sum, whereas the acceptance completion score sums unrounded per-equipment contributions and rounds exactly once at the very end. Moving a rounding step changes the answer, so the placement is part of the contract.

Monetary quantities are held as integers of cents and are never expressed as fractional currency. Energy quantities are held as ordinary numbers in kWh.

The system also runs two overlap checks with deliberately **different** interval geometry, and they must not be conflated.

- The **witness calendar** for functional performance testing uses **closed** intervals expanded by a mobilisation buffer of one hour at each end, compared at second resolution. Two windows collide when the first one's buffered start is at or before the second one's buffered end **and** the second one's buffered start is at or before the first one's buffered end. Touching endpoints therefore **do** collide: a new window whose buffered start falls exactly on an occupant's buffered end is a collision.
- The **seasonal calendar** for deferred testing uses **half-open** intervals running from `window_start` inclusive to `window_end` exclusive, with no buffer at all. Two windows collide when the occupant's start is strictly before the new window's end **and** the new window's start is strictly before the occupant's end. Touching endpoints therefore do **not** collide: a new window starting exactly when an occupant's window ends is accepted.

### 2.11. Segregation of Duties and Engagement Scope

Two rules exist purely to keep the commissioning record defensible.

**Nobody verifies their own work.** The `X-User-ID` recorded as a checklist's `executed_by_user_id` may not be the `X-User-ID` that verifies that checklist, and the `X-User-ID` recorded as a deliverable's `delivered_by_user_id` may not be the `X-User-ID` that accepts it. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403. Note that this is an identity comparison, not a role comparison: two different people holding the same role satisfy the rule, and the same person switching roles does not.

**Everything in one request belongs to one engagement.** Whenever a request names more than one entity — a checklist naming equipment, a functional test naming both equipment and a requirement, an issue naming equipment, a deferred test naming equipment, a requirement and an issue, an evidence row naming an artifact — every named entity must resolve to the same `project_id`. A request that reaches across engagements is rejected with `ERR_PROJECT_SCOPE_MISMATCH` and HTTP 409. Because commissioning artifacts are peer top-level collections joined by explicit foreign keys rather than nested URL segments, this check is the only thing preventing an evidence row on one building from being backed by a test on another.

## 3. Business Logic & Workflows

### 3.1. Opening an Engagement: Phases, Owner Requirements and the Commissioning Plan

A `PlatformAdmin` opens a commissioning engagement by naming it. The payload carries a `name` for the engagement, a `building_name` for the facility it covers, a `project_type` of either `NEW_CONSTRUCTION` or `RETRO_COMMISSIONING`, and a `contract_value_cents` giving the total construction contract value in cents, which must be at least 1. Two optional inputs shape later behaviour: `certification_target` declares the green-certification package the owner is pursuing and is one of `NONE`, `STANDARD` or `ENHANCED`, defaulting to `NONE`; and `witness_capacity` declares how many functional performance tests the CxA firm can witness on this engagement at one instant, defaulting to 1 and never below 1. A freshly opened engagement sits in `delivery_phase` `PLANNING` with `readiness_posture` `OPEN`, and every derived roll-up starts at its zero value — `issue_severity_index`, `retainage_withheld_cents`, `verified_prefunctional_units`, `open_blocking_issue_count`, `acceptance_completion_score`, `withdrawn_credit_count` and `total_awarded_points` all read 0, while `final_acceptance_score` and `acceptance_kind` are null. Engagements can be listed and narrowed by `project_type`, by `delivery_phase` and by `readiness_posture`.

Delivery proceeds strictly one phase at a time, always forward, along `PLANNING` → `DESIGN` → `CONSTRUCTION` → `FUNCTIONAL_TESTING` → `ACCEPTANCE` → `WARRANTY` → `CLOSED`. A `CxAuthority` drives each step by naming the `target_phase` it wants to reach. Any `target_phase` that skips a phase, repeats the current one, or moves backwards is refused with `ERR_PHASE_NOT_ALLOWED`, and `CLOSED` is terminal. Every hop shares one precondition — the engagement's posture must not be `FROZEN`, which is enforced as `ERR_PROJECT_FROZEN` before anything else about the phase is considered — and every hop adds one of its own:

- `PLANNING` → `DESIGN` requires at least one owner requirement of this engagement to be `APPROVED`.
- `DESIGN` → `CONSTRUCTION` requires exactly one commissioning plan of this engagement to be `APPROVED` — no more and no fewer.
- `CONSTRUCTION` → `FUNCTIONAL_TESTING` requires `verified_prefunctional_units` to be at least 1.
- `FUNCTIONAL_TESTING` → `ACCEPTANCE` requires every equipment unit of this engagement to sit in `PREFUNCTIONAL_VERIFIED`, `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED`; a single unit still `UNVERIFIED` holds the whole engagement back.
- `ACCEPTANCE` → `WARRANTY` requires `acceptance_kind` to be set, meaning an acceptance certificate has actually been issued.
- `WARRANTY` → `CLOSED` requires that no deferred test of the engagement remains `PLANNED` or `BLOCKED`, and that no issue of the engagement remains `OPEN`, `IN_REVIEW` or `DEFERRED`.

When the target phase is the correct next one and the posture permits it but the hop's own precondition is unmet, the request is refused with `ERR_INVALID_STATE`. A successful hop writes the new `delivery_phase` and increments the engagement's `version` by one.

**Owner Project Requirements** are the measurable promises the whole engagement is judged against, and only an `OwnerRepresentative` may author them. Each line names its engagement through a `project_id`, carries a `metric_key` identifying what is being measured (for example `SUPPLY_AIRFLOW_CFM`), a `target_value` the owner expects which may not be negative, a `tolerance_pct` giving the acceptable deviation band in percent which must be at least 0 and at most 100, and a `criticality` of `LIFE_SAFETY`, `CRITICAL` or `STANDARD`. A new line is born in `status` `DRAFT` with `revision` 1 and `supersedes_requirement_id` null. Owner approval moves it `DRAFT` → `APPROVED`, which is what makes it eligible for plan pinning.

Requirements change, and the system records the change rather than overwriting it. Revising an `APPROVED` line moves that line `APPROVED` → `SUPERSEDED` and mints a **new** requirement row in `DRAFT` whose `revision` is one greater than its predecessor's, whose `supersedes_requirement_id` points at the predecessor, and whose `target_value`, `tolerance_pct` and `criticality` come from the revise payload while its `project_id` and `metric_key` are inherited. The revision chain is walkable by filtering the requirement list on `supersedes_requirement_id`, and the list also narrows by `project_id` and by `status`. Crucially, the revision reaches sideways: every commissioning plan of the engagement whose `pinned_requirement_ids` array contains the superseded predecessor has its `pin_stale` flag set to true. That flag is the tripwire that later stops a certification package from being submitted against a requirement set the owner has already moved on from.

**The commissioning plan** is authored by a `CxAuthority` and carries a `project_id` and a `title`. Because a newly drafted plan supersedes every plan that came before it on the same engagement, the author must also present `expected_project_version` — see Section 2.9. On creation, every prior plan of that engagement moves to `SUPERSEDED`, whether it was sitting in `DRAFT` or in `APPROVED`; the new plan is born `DRAFT` with an empty `pinned_requirement_ids`, a `pinned_requirement_count` of 0, `pin_stale` false and `approved_at` null; and the engagement's `version` increments by one. Plans are listable by `project_id` and by `status`.

Plan approval belongs to the `OwnerRepresentative` and is where the requirement set is frozen. Approval is permitted only while the plan is `DRAFT`, only while the engagement is in `PLANNING` or `DESIGN` — any other phase yields `ERR_PHASE_NOT_ALLOWED` — and only when at least one owner requirement of the engagement is `APPROVED`. It moves the plan `DRAFT` → `APPROVED`, stamps `approved_at` with the current logical clock, writes into `pinned_requirement_ids` the identifiers of every owner requirement of that engagement whose `status` is `APPROVED` at that exact instant ordered by their creation timestamp ascending, sets `pinned_requirement_count` to the length of that array, and sets `pin_stale` false. From that moment on, only a requirement whose identifier appears in that array may be tested against.

### 3.2. Design Review: Submittals and the Resubmission Loop

The `DesignTeam` lodges each document for review as a **submittal**, naming the engagement through `project_id`, giving it a `title` and declaring its `submittal_kind` as one of `DESIGN_DOCUMENT`, `PRODUCT_DATA`, `SHOP_DRAWING` or `OM_DATA`. An optional `equipment_id` ties the submittal to a specific equipment unit; leaving it out marks the document as project-wide. Every submittal begins in `RECEIVED` at `review_round` 1, with `last_decision`, `review_comment` and `escalation_issue_id` all null. The submittal list narrows by `project_id`, by `equipment_id` and by `status`.

Design review is the `CxAuthority`'s call. The reviewer supplies a `decision` and a `comment`, and the comment is retained on the row as `review_comment` alongside `last_decision` in all three branches, which are given equal standing here because the differences between them are the whole point:

- A decision of `APPROVED` moves the submittal `RECEIVED` → `APPROVED`. Nothing else happens; the document is accepted as lodged and the state is terminal.
- A decision of `APPROVED_AS_NOTED` moves the submittal `RECEIVED` → `APPROVED_AS_NOTED` and is also terminal, but it leaves a paper trail: the server opens an issue with `origin` `DESIGN_REVIEW`, `severity` `S4`, the submittal's own `equipment_id` copied across, `source_ref_id` pointing at the submittal, and `opened_by_user_id` recorded as the literal string `SYSTEM`. An `S4` deficiency carries no retainage hold and does not block acceptance, so this is a marker rather than a penalty — but it does add weight to the severity index until somebody closes it.
- A decision of `REVISE_AND_RESUBMIT` moves the submittal `RECEIVED` → `REVISE_AND_RESUBMIT` and hands it back. When — and only when — the submittal is already at `review_round` 3 at the moment that decision is recorded, the server additionally opens an escalation issue with `origin` `SUBMITTAL`, `severity` `S2`, the submittal's `equipment_id`, `source_ref_id` pointing at the submittal and `opened_by_user_id` of `SYSTEM`, and writes that issue's identifier into the submittal's `escalation_issue_id`. An `S2` deficiency does block acceptance, so a document that has failed three rounds of review becomes a real obstacle to closeout.

The loop closes when the `DesignTeam` resubmits: `REVISE_AND_RESUBMIT` → `RECEIVED` with `review_round` incremented by one, optionally supplying a revised `title`. Resubmission is refused with `ERR_REVIEW_ROUNDS_EXCEEDED` once `review_round` has reached 3, which makes a fourth review round structurally impossible — three rounds is the ceiling, and the third `REVISE_AND_RESUBMIT` decision is the one that escalates.

Because the escalation issue is minted by the server, clients discover it by reading the issue log filtered to the engagement and matching on `source_ref_id` equal to the submittal's identifier — the same discovery pattern used for every automatically opened deficiency in the system.

### 3.3. Equipment Scope and Pre-Functional Verification

Equipment is registered by a `PlatformAdmin` or a `CxAuthority` against a `project_id`, with a `tag` such as AHU-1, a `system_type` drawn from `AHU`, `CHILLER`, `BOILER`, `LIGHTING`, `FIRE_ALARM`, `ELEVATOR` and `BAS`, a `criticality` of `LIFE_SAFETY`, `CRITICAL` or `STANDARD`, a `contract_value_cents` of at least 1 giving the contract value attributable to this unit, and a `weight_units` of at least 1 giving its relative weight in the engagement's completion score. Registration alone changes the engagement's numbers: the new unit joins the completion-score denominator, so the provisional acceptance completion score is recomputed on the spot. A newly registered unit reads `install_status` `NOT_INSTALLED`, `verification_status` `UNVERIFIED` and `blocking_issue_count` 0.

Every equipment unit carries **two independent state dimensions on the same row**, and neither constrains the other except where a rule says so in as many words. Equipment lists can be narrowed on either dimension, by `install_status` or by `verification_status`, as well as by `project_id`.

The **installation dimension** belongs to the `Contractor`, who advances it by naming the `install_status` it should reach. Progress runs `NOT_INSTALLED` → `INSTALLED` → `STARTED_UP`, one step at a time. Removal is reachable from all three of `NOT_INSTALLED`, `INSTALLED` and `STARTED_UP`, and moving to `REMOVED` does two things regardless of where it started from: every functional test of that unit sitting in `SCHEDULED` or `IN_PROGRESS` is moved to `CANCELLED`, releasing its witness window; and the unit drops out of the completion-score denominator entirely, so the engagement's provisional acceptance completion score is recomputed over whatever units remain.

The **verification dimension** is never driven directly by a client. It starts at `UNVERIFIED` and reaches `PREFUNCTIONAL_VERIFIED`, `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED` only as a consequence of checklist and test outcomes described below, and it falls back to `UNVERIFIED` when the commissioning evidence behind it is withdrawn.

**Pre-functional checklists** are the first real verification gate. A `CxAuthority` opens one against a single `equipment_id` with a `template_code` such as PFC-AHU-STD, and it is born `DRAFT` with an empty `items` array, `item_count`, `passed_item_count` and `failed_item_count` all 0, `executed_by_user_id` and `verified_by_user_id` null and `rework_cycle_count` 0. Checklists are listable by `equipment_id` and by `status`.

The `CxAuthority` then appends line items one at a time, each carrying an `item_code` unique within that checklist, a `description` of what is to be checked, and an `is_safety_critical` flag. An appended item enters the `items` array in insertion order with its `result` set to `PENDING` and its `recorded_by_user_id` and `recorded_at` null, and `item_count` is refreshed. Items may be appended only while the checklist is `DRAFT` or in `REWORK`; an attempt against a checklist already in `EXECUTED` or `VERIFIED` is refused with `ERR_INVALID_STATE`. Appending an `item_code` the checklist already carries is refused with `ERR_DUPLICATE_ITEM_CODE`.

Recording results is the `Contractor`'s job: it names an `item_code`, supplies a `result` of `PASS`, `FAIL` or `NA`, and may attach a free-text `note`. The server writes the result onto that item together with `recorded_by_user_id` taken from `X-User-ID` and `recorded_at` taken from the logical clock, then refreshes `passed_item_count` — the number of items whose result is either `PASS` or `NA` — and `failed_item_count` — the number whose result is `FAIL`. Naming an `item_code` the checklist does not carry is refused with `ERR_ITEM_NOT_FOUND`.

When the sheet is complete the `Contractor` signs it off, moving the checklist to `EXECUTED` from either `DRAFT` or `REWORK` and recording `executed_by_user_id`. Three conditions gate that sign-off: the checklist must carry at least one item, or it is refused with `ERR_CHECKLIST_EMPTY`; no item may still read `PENDING`, or it is refused with `ERR_CHECKLIST_INCOMPLETE`; and the unit's `install_status` must be `INSTALLED` or `STARTED_UP`, or it is refused with `ERR_EQUIPMENT_NOT_READY`.

Verification is the `CxAuthority`'s countersignature and the point at which the engagement's numbers move. It is permitted only from `EXECUTED`, only when the acting `X-User-ID` differs from `executed_by_user_id`, only when no item whose `is_safety_critical` is true carries a `result` of `FAIL` — that one is refused with `ERR_SAFETY_ITEM_FAILED` — and only when the unit's `blocking_issue_count` is 0. A successful verification moves the checklist `EXECUTED` → `VERIFIED`, records `verified_by_user_id`, adds the unit's `weight_units` to the engagement's `verified_prefunctional_units`, drives the unit's verification dimension `UNVERIFIED` → `PREFUNCTIONAL_VERIFIED`, recomputes the provisional acceptance completion score, and increments the engagement's `version` by one.

Rejection is the exact compensating action and it accepts a `reason`. It is reachable from both `EXECUTED` and `VERIFIED`, and both branches send the checklist to `REWORK`, increment `rework_cycle_count` by one, clear `executed_by_user_id`, and reset every item's `result` back to `PENDING` while clearing that item's `recorded_by_user_id` and `recorded_at`. Rejecting from `VERIFIED` does strictly more, because there is more to unwind: it additionally clears `verified_by_user_id`, subtracts the unit's `weight_units` from `verified_prefunctional_units` so that a verify-then-reject cycle leaves that figure exactly where it started, and drives the unit's verification dimension back to `UNVERIFIED` from whichever of `PREFUNCTIONAL_VERIFIED`, `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED` it had reached. That demotion in turn cancels every functional test of the unit still sitting in `SCHEDULED` and flips every `EQUIPMENT_VERIFICATION` evidence row pointing at that unit to stale. Either branch recomputes the provisional acceptance completion score and increments the engagement's `version` by one. Once in `REWORK` the checklist can be re-executed, which is what makes the `EXECUTED` or `VERIFIED` → `REWORK` → `EXECUTED` loop cyclic.

**Blocking deficiencies move the verification dimension on their own.** The `blocking_issue_count` on a unit is by definition the number of issues charged to that unit whose `blocks_acceptance` is true and whose `status` is `OPEN` or `IN_REVIEW`; any transition that moves such an issue into or out of that status pair adjusts the count. When a blocking issue attaches to a unit that is sitting in `PREFUNCTIONAL_VERIFIED`, `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED`, that unit is demoted to `UNVERIFIED` and every `EQUIPMENT_VERIFICATION` evidence row whose `evidence_ref_id` names it flips `is_stale` to true and stamps `staled_at`. When blocking issues leave the `OPEN`/`IN_REVIEW` pair by any route and the count thereby reaches 0, and the unit's own pre-functional checklist is still `VERIFIED`, the unit is promoted back `UNVERIFIED` → `PREFUNCTIONAL_VERIFIED`, every `EQUIPMENT_VERIFICATION` evidence row pointing at it flips `is_stale` back to false, and the provisional acceptance completion score is recomputed.

### 3.4. Functional Performance Testing and the Witness Calendar

A functional performance test is scheduled by a `CxAuthority` against a specific `equipment_id` and a specific `requirement_id`, with a `script_code` naming the test script (for example FPT-AHU-ECON) and a witnessed window running from `scheduled_start` to `scheduled_end`, both ISO 8601 UTC. Scheduling a **new** test is heavily gated: the engagement's newest commissioning plan must be `APPROVED` or the request is refused with `ERR_PLAN_NOT_APPROVED`; the `requirement_id` must appear in that plan's `pinned_requirement_ids` or the request is refused with `ERR_REQUIREMENT_NOT_PINNED`; the unit must be both `PREFUNCTIONAL_VERIFIED` and `STARTED_UP` or the request is refused with `ERR_EQUIPMENT_NOT_READY`; `scheduled_end` must be strictly after `scheduled_start` or the request is refused with `ERR_INVALID_WINDOW`; and the witness calendar must have room. A new test is born `SCHEDULED` with `retest_of_test_id`, `measured_value`, `outcome_deviation_pct`, `witness_user_id`, `started_at`, `completed_at` and `generated_issue_id` all null. Tests are listable by `equipment_id`, by `requirement_id`, by `retest_of_test_id` and by `status`.

The **witness calendar** models the reality that the CxA firm can only be in so many places at once. Each test's window is expanded by a mobilisation buffer of one hour before `scheduled_start` and one hour after `scheduled_end`, and the resulting buffered intervals are treated as closed at both ends — two buffered windows collide when each one's buffered start falls at or before the other one's buffered end, so windows that merely touch **do** collide. The occupants counted are the functional tests of the same engagement, across all of its equipment, whose `status` is `SCHEDULED` or `IN_PROGRESS`; tests in `PASSED`, `PASSED_WITH_EXCEPTIONS`, `FAILED` or `CANCELLED` have released their windows and are not counted. If the number of colliding occupants is greater than or equal to the engagement's `witness_capacity`, the request is refused with `ERR_WITNESS_WINDOW_CONFLICT`. An engagement left at the default capacity of 1 therefore admits no overlap at all, whereas one configured for a capacity of 2 tolerates a single overlapping occupant and refuses the second.

Witnessing begins when the `CxAuthority` starts the test, moving it `SCHEDULED` → `IN_PROGRESS` and stamping `started_at` from the logical clock. Starting requires the unit's `install_status` to be `STARTED_UP`; it does **not** require the verification dimension to be in any particular state.

Recording the result is where the branch is decided. The witness supplies a `measured_value` and may attach a `note`. The server compares that value against the owner requirement the test was scheduled against — specifically against the exact requirement row named by `requirement_id`, using that row's `target_value` and `tolerance_pct` even if that row has since been moved to `SUPERSEDED` by a later revision. The percentage deviation is computed as follows: when the requirement's `target_value` is 0, the deviation is 0.00 if the measured value is also 0 and 100.00 otherwise; when the target is not 0, the deviation is the absolute difference between the measured value and the target, divided by the target, multiplied by 100, and rounded half up to two decimal places. That number is written to `outcome_deviation_pct`, and the outcome follows from it with both comparisons inclusive: a deviation at or below `tolerance_pct` is `PASSED`; a deviation above `tolerance_pct` but at or below twice `tolerance_pct` is `PASSED_WITH_EXCEPTIONS`; a deviation above twice `tolerance_pct` is `FAILED`. A deviation of exactly the tolerance is therefore a pass, and a deviation of exactly twice the tolerance is a pass with exceptions.

All three branches leave `IN_PROGRESS`, write `measured_value`, `outcome_deviation_pct`, `witness_user_id` from the acting `X-User-ID` and `completed_at` from the logical clock, and increment the engagement's `version` by one. What they do beyond that diverges sharply, and each branch is spelled out here in full:

- **`IN_PROGRESS` → `PASSED`.** The unit is promoted `PREFUNCTIONAL_VERIFIED` → `FUNCTIONAL_ACCEPTED` and the engagement's provisional acceptance completion score is recomputed. No deficiency is opened and no money is withheld.
- **`IN_PROGRESS` → `PASSED_WITH_EXCEPTIONS`.** The server opens an issue with `origin` `FUNCTIONAL`, `severity` `S3`, the test's own equipment as `equipment_id`, `source_ref_id` pointing at the test and `opened_by_user_id` of `SYSTEM`, and writes that issue's identifier into the test's `generated_issue_id`. Because `S3` does not block acceptance, the unit's `blocking_issue_count` is unchanged and the unit is **not** demoted; instead it moves `PREFUNCTIONAL_VERIFIED` → `CONDITIONALLY_ACCEPTED`. The new issue's retainage hold is frozen, the engagement's `retainage_withheld_cents` grows by it, and the severity index, the posture and the provisional acceptance completion score are all recomputed.
- **`IN_PROGRESS` → `FAILED`.** This is the deepest cascade in the system and it runs in four hops within the single request. **First**, the test is written to `FAILED` and an issue is opened with `origin` `FUNCTIONAL`, the test's equipment as `equipment_id`, `source_ref_id` pointing at the test, `opened_by_user_id` of `SYSTEM`, and a `severity` taken from the equipment's own `criticality`: `LIFE_SAFETY` equipment yields `S1`, `CRITICAL` equipment yields `S2` and `STANDARD` equipment yields `S3`. The issue's identifier is written to `generated_issue_id`, its retainage hold is frozen, the engagement's `retainage_withheld_cents` grows and the severity index and posture are recomputed. **Second**, when that issue's severity makes `blocks_acceptance` true — that is, when it came out `S1` or `S2` — the unit's `blocking_issue_count` increments and its verification dimension is demoted to `UNVERIFIED`. **Third**, because the unit has left its verified states, every `EQUIPMENT_VERIFICATION` evidence row whose `evidence_ref_id` names that unit flips `is_stale` to true and stamps `staled_at`, and every certification credit holding such a row recomputes its `completeness_ratio`, `provisional_tier`, `documentation_score` and `final_tier`. **Fourth**, any credit whose recomputed `final_tier` has fallen to `NONE` while its `status` was `SUBMITTED` is moved `SUBMITTED` → `WITHDRAWN` and the engagement's `withdrawn_credit_count` increments by one. Hops two through four are conditional on that first issue blocking acceptance: a failure on a `STANDARD` unit produces an `S3` deficiency, which withholds retainage and loads the severity index but leaves the unit's standing, its evidence rows and its credit packages untouched.

A failed or conditionally passed test can be re-tested. The `CxAuthority` supplies only a fresh `scheduled_start` and `scheduled_end`; the server mints a **new** functional test row in `SCHEDULED` whose `retest_of_test_id` points at the test being re-tested and whose `equipment_id`, `requirement_id` and `script_code` are copied from it. The original row is left exactly as it was — a re-test does not reopen or rewrite history. Re-tests are subject to the same window-ordering rule, the same buffered witness-calendar rule and the same approved-plan rule as an original scheduling, but their equipment precondition is deliberately looser: the unit need only be `STARTED_UP`. That relaxation is what makes the workflow usable at all, because the very failure being re-tested will normally have demoted the unit to `UNVERIFIED`.

Two events cancel a test outright rather than resolving it. Rejecting a `VERIFIED` pre-functional checklist cancels every `SCHEDULED` test of that unit, and removing the equipment cancels every test of that unit in `SCHEDULED` **or** `IN_PROGRESS`. In both cases the row moves to `CANCELLED` and its buffered window is released for the witness-calendar count.

### 3.5. The Issue Log

The issue log is the engagement's live record of every deficiency, and it is the single input to both conserved quantities. A `CxAuthority` or a `Contractor` may log one directly, naming the engagement through `project_id`, an `origin` drawn from `DESIGN_REVIEW`, `SUBMITTAL`, `PREFUNCTIONAL`, `FUNCTIONAL`, `SEASONAL` and `RETRO_CX`, a `severity` of `S1`, `S2`, `S3` or `S4`, and a `description` narrating the deficiency. Two optional inputs carry the cross-references: `equipment_id` charges the deficiency to a specific unit and is left out for project-wide findings, and `source_ref_id` is a polymorphic pointer whose meaning is fixed by `origin` — under `SUBMITTAL` it names a submittal, under `FUNCTIONAL` it names a functional test, under `PREFUNCTIONAL` it names a pre-functional checklist, under `SEASONAL` it names a deferred test, and under `DESIGN_REVIEW` or `RETRO_CX` it is null. The issue log is readable filtered by `project_id`, `equipment_id`, `closure_retest_id`, `status`, `severity` and `origin`.

A new issue is born in `status` `OPEN` with `opened_at` stamped from the logical clock — that stamp is the aging clock the severity index reads — and `opened_by_user_id` set to the acting `X-User-ID`, or to the literal string `SYSTEM` for the deficiencies the server opens by itself. `blocks_acceptance` is derived on the spot and is true exactly when the `severity` is `S1` or `S2`; `retainage_hold_cents` is computed once and frozen; `reopen_count` starts at 0; and `closure_retest_id`, `proposed_by_user_id` and `proposed_resolution` are all null. The engagement's `retainage_withheld_cents` grows by the frozen hold, `open_blocking_issue_count` is refreshed, the severity index is recomputed and the posture re-derived, a blocking issue demotes its equipment and stales that equipment's verification evidence, and the engagement's `version` increments by one. If the new hold would push `retainage_withheld_cents` past the cap, none of this happens and the request is refused with `ERR_RETAINAGE_CAP_EXCEEDED`.

The corrective loop runs through four client-driven transitions and one system-driven one, and they differ in exactly which input sets the row belongs to:

- **`OPEN` → `IN_REVIEW`**, driven by the `Contractor` supplying a `proposed_resolution`. The text is stored on the row, `proposed_by_user_id` records the acting `X-User-ID`, and nothing else moves: the row stays inside the severity-index input set and keeps its retainage hold, because a proposal is not a correction.
- **`IN_REVIEW` → `VERIFIED_CLOSED`**, driven by the `CxAuthority` supplying a `closure_note` and, where required, a `closure_retest_id`. This is the reverse of the failure cascade and runs in three hops. First, the row is written closed with its `closure_retest_id`, and because it has left both the severity-index input set and the retainage input set, the engagement's `retainage_withheld_cents` drops by exactly this issue's frozen `retainage_hold_cents` and the severity index is recomputed. Second, because the issue has left the `OPEN`/`IN_REVIEW` pair, a blocking issue's departure decrements the unit's `blocking_issue_count`, and when that count reaches 0 while the unit's checklist is still `VERIFIED`, the unit is promoted `UNVERIFIED` → `PREFUNCTIONAL_VERIFIED` and every `EQUIPMENT_VERIFICATION` evidence row pointing at it flips `is_stale` back to false. Third, because a unit was promoted and the index fell, the provisional acceptance completion score is recomputed and the posture re-derived; if that takes the engagement out of `FROZEN`, every `BLOCKED` deferred test of the engagement returns to `PLANNED`. The engagement's `version` increments by one.
- **Back to `OPEN`**, driven by the `CxAuthority` supplying a `reason`, and reachable from `IN_REVIEW`, from `VERIFIED_CLOSED` and from `DEFERRED`. All three branches set `status` to `OPEN` and increment `reopen_count` by one. Re-opening from `IN_REVIEW` additionally clears `proposed_by_user_id`, `proposed_resolution` and `closure_retest_id`, and moves no conserved quantity, because an `IN_REVIEW` row was already inside both input sets. Re-opening from `VERIFIED_CLOSED` clears the same three fields and puts the row back into both input sets, so `retainage_withheld_cents` grows again by exactly the frozen `retainage_hold_cents`, and when the row blocks acceptance the unit's `blocking_issue_count` increments and the unit is demoted to `UNVERIFIED`. Re-opening from `DEFERRED` puts the row back into the severity-index input set only, since a deferred row never left the retainage input set. The engagement's `version` increments by one.
- **`OPEN` → `DEFERRED`**, driven by the `OwnerRepresentative` supplying a `deferral_reason`. Deferral is permitted only when at least one deferred test already exists whose `issue_id` names this issue and whose `status` is `PLANNED` or `BLOCKED` — an owner may not simply park a deficiency, they must park it against scheduled seasonal work. The row leaves the severity-index input set, so the posture may improve, but it **stays** in the retainage input set, so `retainage_withheld_cents` does not move. The engagement's `version` increments by one.
- **To `VOID`**, driven by the `CxAuthority` supplying a `reason`, and reachable from `OPEN`, from `IN_REVIEW` and from `DEFERRED`. This is the compensating action for issue creation: the row leaves every input set, so `retainage_withheld_cents` drops by exactly the frozen `retainage_hold_cents` and the severity index is recomputed in all three branches. When the voided row was blocking acceptance from `OPEN` or `IN_REVIEW`, the unit's `blocking_issue_count` decrements and the promotion rule may re-verify the unit; a `DEFERRED` row was never counted in `blocking_issue_count`, so voiding it triggers neither a demotion nor a promotion. `VOID` is the only terminal state in the issue lifecycle, and the engagement's `version` increments by one.

Because `VERIFIED_CLOSED` and `DEFERRED` both return to `OPEN`, the issue lifecycle is genuinely cyclic and `reopen_count` is the audit trail of how many times a supposed correction did not hold.

One closure rule exists purely to stop paperwork closures of real failures. Closing an issue whose `origin` is `FUNCTIONAL` and whose `severity` is `S1` or `S2` requires a `closure_retest_id`, and the functional test it names must have `status` `PASSED`; without it, or with a test in any other status, the closure is refused with `ERR_RETEST_EVIDENCE_REQUIRED`. That re-test must also belong to the same unit: if its `equipment_id` differs from the issue's `equipment_id`, the closure is refused with `ERR_RETEST_SCOPE_MISMATCH`. Issues of other origins and lower severities may be closed on the `closure_note` alone.

### 3.6. Seasonal and Deferred Testing

Some performance can only be proved in the right weather. A `CxAuthority` schedules seasonal or deferred work against an `equipment_id` and a `requirement_id`, declaring the `season` as `HEATING`, `COOLING` or `SHOULDER` and bounding it with a `window_start` and a `window_end`. An optional `issue_id` links the seasonal test to the deficiency it is meant to discharge; planned seasonal work that is not discharging anything leaves it null. Scheduling requires the engagement's posture not to be `FROZEN`, requires the `requirement_id` to appear in the newest approved commissioning plan's `pinned_requirement_ids`, and requires `window_end` to be strictly after `window_start`.

The seasonal calendar is scoped per equipment unit and admits exactly one live window at a time. The occupants are the deferred tests of the **same** `equipment_id` whose `status` is `PLANNED` or `BLOCKED`; rows in `EXECUTED_PASS`, `EXECUTED_FAIL` or `MISSED` have released their windows. Windows here are half-open and unbuffered, so a new window whose `window_start` falls exactly on an occupant's `window_end` is accepted, whereas any genuine overlap is refused with `ERR_SEASONAL_WINDOW_CONFLICT`. A new deferred test is born `PLANNED` with `executed_at` and `measured_value` null, and its creation recomputes the engagement's provisional acceptance completion score, because outstanding seasonal work is credited at half weight in that variant. Deferred tests are listable by `equipment_id`, by `requirement_id`, by `issue_id`, by `status` and by `season`.

Seasonal work is suspended and resumed by the posture rather than by a client. When an engagement's posture becomes `FROZEN`, every deferred test of that engagement in `PLANNED` moves to `BLOCKED`; when the posture leaves `FROZEN` in either direction, every `BLOCKED` row returns to `PLANNED`.

Execution is the `CxAuthority`'s, and it carries only a `measured_value`. The row must be `PLANNED`, and the logical clock must be at or after `window_start` and strictly before `window_end` — outside that half-open span the request is refused with `ERR_OUTSIDE_SEASONAL_WINDOW`, which also means a `BLOCKED` row cannot be executed at all. The outcome is derived from the linked owner requirement's tolerance the same way a functional test's is: a measured value inside the tolerance band gives `PLANNED` → `EXECUTED_PASS`, and one outside it gives `PLANNED` → `EXECUTED_FAIL`. Either way `executed_at` and `measured_value` are stamped. When the row carries an `issue_id` whose issue is sitting in `DEFERRED`, the two outcomes diverge: a pass moves that issue `DEFERRED` → `VERIFIED_CLOSED` and releases its retainage hold, dropping the engagement's `retainage_withheld_cents` by exactly the frozen `retainage_hold_cents`, and because a `DEFERRED` row was never counted in `blocking_issue_count`, no demotion or promotion follows from that hop; a failure instead returns the issue `DEFERRED` → `OPEN` with `reopen_count` incremented by one, putting it back into the severity-index input set. Execution recomputes the acceptance completion score, the severity index and the posture, and increments the engagement's `version` by one.

Missed seasons are caught by an operations checkpoint that a `CxAuthority` runs against the engagement. The sweep takes every deferred test of the engagement whose `status` is `PLANNED` or `BLOCKED` and whose `window_end` is at or before the current logical clock, and moves each to `MISSED`. For **each** swept row the server opens an issue with `origin` `SEASONAL`, `severity` `S2`, the deferred test's equipment as `equipment_id`, `source_ref_id` pointing at the deferred test and `opened_by_user_id` of `SYSTEM`; and where the swept row carried an `issue_id` whose issue was `DEFERRED`, that issue returns to `OPEN` with `reopen_count` incremented by one. The sweep then recomputes the severity index, re-derives the posture, increments the engagement's `version` by one, and answers with the engagement itself rather than with the swept rows.

### 3.7. Training Verification, the Systems Manual and Closeout Acceptance

Closeout obligations are planned early and settled late. A `Contractor` or a `DesignTeam` plans one against a `project_id`, declaring its `deliverable_kind` as `TRAINING_SESSION`, `SYSTEMS_MANUAL_SECTION` or `OM_DATA_PACKAGE` and giving it a `title` naming the topic or document. An optional `equipment_id` ties it to a specific unit, and an optional `required_attendee_count` — which may not be negative and defaults to 0 — states how many of the owner's staff must attend; non-training deliverables leave it at 0. A planned deliverable reads `status` `PLANNED`, `attendee_count` 0, `duration_minutes` 0, `session_start` null, `delivered_by_user_id` and `accepted_by_user_id` null and `coverage_ratio` 0. Planning one against a unit changes the engagement's numbers immediately, because that unit now carries a closeout obligation that the acceptance completion score measures. Deliverables are listable by `project_id`, `equipment_id`, `deliverable_kind` and `status`.

Delivery is recorded by a `Contractor` or a `DesignTeam` and is reachable from `PLANNED` and from `RETURNED` alike, with both branches behaving identically: the payload supplies the `attendee_count` actually present and the `duration_minutes` the session ran, and the server moves the row to `DELIVERED`, records `delivered_by_user_id` from the acting `X-User-ID`, stamps `session_start` from the logical clock, and recomputes `coverage_ratio`. That ratio is exactly 1.0 when `required_attendee_count` is 0; otherwise it is the attendee count divided by the required attendee count, capped at 1.0, rounded half up to four decimal places.

Acceptance belongs to a `CxAuthority` or an `OwnerRepresentative`, who attests with an `attestation_note`. It is permitted only from `DELIVERED`, only while the engagement's posture is not `FROZEN`, and only when the acting `X-User-ID` differs from `delivered_by_user_id`. For a `TRAINING_SESSION` there is one further gate: `coverage_ratio` must be at least 0.80, with the boundary inclusive so that exactly 0.80 is accepted, and a shortfall is refused with `ERR_TRAINING_COVERAGE_INSUFFICIENT`. That gate does not apply to `SYSTEMS_MANUAL_SECTION` or `OM_DATA_PACKAGE` deliverables. Acceptance moves the row `DELIVERED` → `ACCEPTED`, records `accepted_by_user_id`, recomputes the provisional acceptance completion score and increments the engagement's `version` by one. `ACCEPTED` is terminal.

Return is the `CxAuthority`'s way of sending work back, and it accepts a `reason`. It moves the row `DELIVERED` → `RETURNED` and clears `delivered_by_user_id` so that the next delivery is judged on its own actor. It also reaches across into certification documentation: every credit evidence row whose `evidence_type` is `TRAINING` or `MANUAL_SECTION` and whose `evidence_ref_id` names this deliverable flips `is_stale` to true. The engagement's `version` increments by one, and the `RETURNED` → `DELIVERED` → `RETURNED` loop can run as many times as the reviewer needs.

### 3.8. Certification Credit Documentation and Evidence Freshness

A certification credit package is opened by a `CxAuthority` against a `project_id`, with a `credit_code` identifying the credit (for example EA-CX-ENHANCED), a `required_evidence_count` stating how many evidence rows full completeness demands which may not be negative, and a `max_points` stating what the credit is worth at the top tier which may not be negative. A new package sits in `NOT_STARTED` with `evidence_count`, `fresh_evidence_count`, `stale_evidence_count`, `completeness_ratio`, `documentation_score` and `awarded_points` all 0, `provisional_tier` and `final_tier` both `NONE`, and `submitted_at` null. Credits are listable by `project_id` and by `status`.

Evidence is attached one row at a time by a `CxAuthority`, naming an `evidence_type` and an `evidence_ref_id`; the stored row records the package it documents through its own `credit_id`. The `evidence_type` fixes what the reference means and what "still valid" means for it: `EQUIPMENT_VERIFICATION` names an equipment unit, `FUNCTIONAL_TEST` names a functional test, `CHECKLIST` names a pre-functional checklist, `TRAINING` and `MANUAL_SECTION` both name a closeout deliverable, and `ENERGY_BASELINE` names a retro-commissioning measure. A reference that does not resolve to a row of the declared family, or that resolves to a row belonging to another engagement, is refused with `ERR_EVIDENCE_REF_INVALID`. Attaching the first evidence row to a package moves it `NOT_STARTED` → `IN_PREPARATION`; attaching one to a package that had been withdrawn moves it `WITHDRAWN` → `IN_PREPARATION`. Either way the four-step documentation score is recomputed end to end. The evidence rows of a credit can be listed and narrowed by `is_stale`.

**Freshness** is evaluated the instant an evidence row is created and re-evaluated every time the artifact it points at changes state. A row's `is_stale` is true precisely when the referenced artifact is no longer in its evidentiary state: an `EQUIPMENT_VERIFICATION` row is stale unless the unit's `verification_status` is one of `PREFUNCTIONAL_VERIFIED`, `FUNCTIONAL_ACCEPTED` or `CONDITIONALLY_ACCEPTED`; a `FUNCTIONAL_TEST` row is stale unless the test's `status` is `PASSED` or `PASSED_WITH_EXCEPTIONS`; a `CHECKLIST` row is stale unless the checklist's `status` is `VERIFIED`; a `TRAINING` row and a `MANUAL_SECTION` row are each stale unless the deliverable's `status` is `ACCEPTED`; and an `ENERGY_BASELINE` row is stale unless the measure's `status` is `CERTIFIED`. A row attached to an artifact that is already outside its evidentiary state is therefore born with `is_stale` true and with `staled_at` already stamped from the logical clock, while a row born fresh carries `is_stale` false and `staled_at` null; that initial evaluation is part of writing the row rather than a later mutation of it, so a row born stale is still returned with `version` 1. Each time `is_stale` flips from false to true the row's `staled_at` is stamped with the current logical clock; a flip back from true to false leaves `staled_at` exactly as it was, preserving the record that the evidence once lapsed. The credit's `evidence_count` is the number of its evidence rows, `fresh_evidence_count` counts those whose `is_stale` is false, and `stale_evidence_count` counts those whose `is_stale` is true.

**The documentation score** looks circular — the tier depends on the score and the score depends on the tier — and it is not. The evaluation order is pinned to exactly four steps, executed once, top to bottom, with no iteration and no search for a fixed point. `final_tier` is derived from `documentation_score` and is **never** fed back into it.

1. **Completeness.** When `required_evidence_count` is 0, `completeness_ratio` is 0.0 — a credit demanding no evidence scores nothing rather than everything. Otherwise `completeness_ratio` is the fresh evidence count divided by the required evidence count, capped at 1.0, rounded half up to four decimal places. Stale rows never count toward completeness.
2. **Provisional tier.** `provisional_tier` is `GOLD` when `completeness_ratio` is at least 1.00, `SILVER` when it is at least 0.75, `BRONZE` when it is at least 0.50, and `NONE` otherwise. All three bounds are inclusive.
3. **Score.** `documentation_score` starts from 100.0 multiplied by `completeness_ratio` multiplied by the quality weight of the **provisional** tier just computed — 1.00 for `GOLD`, 0.85 for `SILVER`, 0.60 for `BRONZE` and 0.40 for `NONE`. From that product a flat penalty of 15.00 points is subtracted for **each** stale evidence row the credit holds. The result is floored at 0.0 and rounded half up to two decimal places.
4. **Final tier.** `final_tier` is `GOLD` when `documentation_score` is at least 90.00, `SILVER` when it is at least 70.00, `BRONZE` when it is at least 50.00, and `NONE` otherwise. All three bounds are inclusive.

The whole four-step pass reruns whenever an evidence row is added to the credit and whenever any of its evidence rows flips `is_stale` in either direction.

Submission is the `CxAuthority`'s, and it is the most heavily gated write in the system. The package must be `IN_PREPARATION`; the engagement's posture must not be `FROZEN`; the engagement's newest commissioning plan must be `APPROVED` with `pin_stale` false, failing with `ERR_PLAN_NOT_APPROVED` and `ERR_PLAN_PIN_STALE` respectively; `fresh_evidence_count` must be at least `required_evidence_count`, failing with `ERR_EVIDENCE_INSUFFICIENT`; and the caller must present `expected_project_version` matching the engagement's current `version` as described in Section 2.9. A successful submission moves the package `IN_PREPARATION` → `SUBMITTED`, stamps `submitted_at` from the logical clock and increments the engagement's `version` by one.

Adjudication belongs to the `OwnerRepresentative`, who supplies a `decision` of `AWARDED` or `DENIED` and may attach a `reason`. Awarding requires the package to be `SUBMITTED` and its `final_tier` to be anything other than `NONE`; it moves the package to `AWARDED` and writes `awarded_points` as `max_points` multiplied by the award fraction of the final tier — 1.00 for `GOLD`, 0.75 for `SILVER`, 0.50 for `BRONZE` and 0.00 for `NONE` — rounded to two decimal places, and adds that figure to the engagement's `total_awarded_points`. Denying requires only that the package be `SUBMITTED`; it moves the package to `DENIED` and sets `awarded_points` to 0. Both branches increment the engagement's `version` by one, and both `AWARDED` and `DENIED` are terminal.

Between submission and adjudication the package remains exposed to the rest of the engagement. Whenever a recomputation of the four-step score drives a `SUBMITTED` package's `final_tier` down to `NONE`, the server withdraws it on its own initiative, moving it `SUBMITTED` → `WITHDRAWN` and incrementing the engagement's `withdrawn_credit_count` by one. That is the fourth hop of the failed-test cascade in Section 3.4, and it is the reason a package can evaporate without anyone touching it. Attaching a fresh evidence row brings a withdrawn package back to `IN_PREPARATION`, from where it can be re-submitted.

### 3.9. Retro-Commissioning Savings and the Acceptance Certificate

Retro-commissioning engagements — those whose `project_type` is `RETRO_COMMISSIONING` — carry energy measures that new-construction engagements do not. A `CxAuthority` records a measure with a `project_id`, a `measure_code` identifying it (for example RCX-SAT-RESET), a `baseline_kwh` giving pre-retrofit annual consumption which must be greater than 0, a `baseline_hdd` giving the heating degree days of the baseline period which must also be greater than 0, a `stipulated_kwh_per_hour` giving the deemed savings rate for the measure which may not be negative, and an `operating_hours` giving the annual operating hours claimed which may not be negative either. Attempting this on a `NEW_CONSTRUCTION` engagement is refused with `ERR_RETRO_ONLY`. A new measure sits in `BASELINE_SET` with `post_kwh`, `post_hdd`, `deemed_savings_kwh`, `measured_savings_kwh`, `certified_savings_kwh` and `certified_variant` all null, and measures are listable by `project_id` and by `status`.

Recording the post-retrofit period moves the measure `BASELINE_SET` → `POST_PERIOD_RECORDED` on a payload of `post_kwh` and `post_hdd`, and computes **both** savings variants side by side so that the owner can compare them before choosing:

- The **`DEEMED`** variant is the stipulated engineering estimate and reads no metered data at all. It is `stipulated_kwh_per_hour` multiplied by `operating_hours` multiplied by a realisation factor of 0.85, rounded half up to two decimal places, and written to `deemed_savings_kwh`.
- The **`MEASURED`** variant is weather-normalised measurement and verification. First the baseline is adjusted for weather: `baseline_kwh` is multiplied by the post period's degree days divided by the baseline period's degree days, and that adjusted baseline is rounded half up to two decimal places **before** anything is subtracted from it. Then the metered `post_kwh` is subtracted from the rounded adjusted baseline to give gross savings. Gross savings are floored at zero — a measure that used more energy after the retrofit claims zero, never a negative. Finally a fixed uncertainty deduction of ten percent is applied by multiplying the floored figure by 0.90, and the result is rounded half up to two decimal places and written to `measured_savings_kwh`.

Certification freezes one of the two. The `CxAuthority` names a `variant` of `DEEMED` or `MEASURED`, and the server copies that variant's value into `certified_savings_kwh`, records the choice in `certified_variant`, and moves the measure `POST_PERIOD_RECORDED` → `CERTIFIED`. The `MEASURED` variant may be certified on any engagement whatever its certification target. The `DEEMED` variant may be certified only when the engagement's `certification_target` is `NONE` or `STANDARD`; an engagement chasing `ENHANCED` may certify only `MEASURED`, and asking for `DEEMED` there is refused with `ERR_VARIANT_NOT_PERMITTED`.

**The acceptance completion score** is the engagement's headline number and, like the savings estimate, it exists in two variants computed from identical rows. Both walk the engagement's equipment units whose `install_status` is not `REMOVED`, ordered by creation timestamp ascending. The denominator, `total_weight_units`, is the sum of `weight_units` over exactly those units; when that sum is 0 — because no equipment is registered, or every unit has been removed — the score is 0.00 and the walk stops there. Each surviving unit contributes its `weight_units` multiplied by a blend of three sub-scores: the pre-functional sub-score weighted at 0.30, the functional sub-score weighted at 0.50 and the closeout sub-score weighted at 0.20. The per-unit contributions are **not** rounded. Their sum is multiplied by 100, divided by the total weight, and rounded half up to two decimal places exactly once, at the very end.

The three sub-scores are defined as follows. The **pre-functional** sub-score is 1.0 when the unit's pre-functional checklist is `VERIFIED` and 0.0 otherwise, and it is identical in both variants. The **closeout** sub-score is 1.0 when the unit has at least one closeout deliverable **and** every one of them is `ACCEPTED`, and 0.0 otherwise — a unit with no deliverables at all scores 0.0, not 1.0. The **functional** sub-score is where the two variants part, and both read the same anchor: the unit's *latest completed test*, meaning the functional test of that unit whose `status` is `PASSED`, `PASSED_WITH_EXCEPTIONS` or `FAILED` having the greatest `completed_at`, with ties on identical `completed_at` broken by creation timestamp ascending so that the last such row wins. If the unit has no such test, it has no latest completed test.

- In the **`PROVISIONAL`** variant, the functional sub-score is 1.0 when the latest completed test is `PASSED` or `PASSED_WITH_EXCEPTIONS`; otherwise it is 0.5 when the unit has at least one deferred test in `PLANNED` or `BLOCKED`; otherwise it is 0.0. This variant reads optimistically during construction: it credits a pass-with-exceptions as a full pass and credits still-scheduled seasonal work at half.
- In the **`FINAL`** variant, the functional sub-score is 1.0 only when the latest completed test is `PASSED` **and** every deferred test of that unit is `EXECUTED_PASS`; otherwise it is 0.5 only when the latest completed test is `PASSED_WITH_EXCEPTIONS` **and** the unit's `blocking_issue_count` is 0; otherwise it is 0.0. Unexecuted seasonal work scores 0.0 here rather than 0.5.

The `PROVISIONAL` variant is the one persisted on the engagement as `acceptance_completion_score`, and it is refreshed after every checklist verification and rejection, every functional test result, every deliverable acceptance and return, every deferred test creation and execution, and every equipment removal. The `FINAL` variant is computed on demand and is persisted to `final_acceptance_score` only when an acceptance certificate is issued.

A dedicated computed read exposes the whole picture for one engagement without mutating anything. It answers with `readiness_posture`, `issue_severity_index`, `acceptance_completion_score_provisional` and `acceptance_completion_score_final` side by side, `open_blocking_issue_count`, `retainage_withheld_cents`, `retainage_cap_cents` (the engagement's `contract_value_cents` multiplied by 0.10 with any fractional cent discarded), `verified_prefunctional_units`, `total_weight_units`, `withdrawn_credit_count` and `total_awarded_points`. It is the natural pre-flight check before asking for a certificate.

**Issuing acceptance** is the `OwnerRepresentative`'s final act on the delivery side. The payload carries a single `acceptance_kind` of `SUBSTANTIAL` or `FINAL`. The engagement must be in `delivery_phase` `ACCEPTANCE`, or the request is refused with `ERR_PHASE_NOT_ALLOWED`, and its posture must not be `FROZEN`. The server then computes the `FINAL` variant of the acceptance completion score and applies two gates in order. The score gate comes first: `SUBSTANTIAL` requires at least 70.00 and `FINAL` requires at least 95.00, and a shortfall is refused with `ERR_ACCEPTANCE_SCORE_TOO_LOW`. The deficiency gate comes second and is deliberately asymmetric: `SUBSTANTIAL` requires that no issue of the engagement with `severity` `S1` remains `OPEN` or `IN_REVIEW`, tolerating lower-severity and deferred deficiencies; `FINAL` requires that **no** issue of the engagement remains `OPEN`, `IN_REVIEW` or `DEFERRED` at any severity. Either shortfall is refused with `ERR_OPEN_BLOCKING_ISSUES`. When both gates pass, the computed `FINAL` variant is persisted to `final_acceptance_score`, `acceptance_kind` is written, and the engagement's `version` increments by one — which in turn unlocks the `ACCEPTANCE` → `WARRANTY` hop described in Section 3.1.

## 4. Endpoint Definitions

Operations that mint a new stand-alone resource — an engagement, an owner requirement, a commissioning plan, a submittal, an equipment unit, a pre-functional checklist, a checklist line item, a functional test, a re-test row, an issue, a deferred test, a closeout deliverable, a certification credit or an evidence row, or an energy baseline — answer with `201 Created`. Every other successful operation, including all reads, all state transitions on existing resources and all recorded results, answers with `200 OK`. The request and response payloads of each endpoint are not repeated here; they are defined by the workflow narratives in Section 3. Where the authorised roles read "Any", all five roles named in Section 2.1 are permitted.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cx-projects` | Open a commissioning engagement | PlatformAdmin |
| GET | `/cx-projects/{id}` | Read one engagement, including its version for optimistic concurrency | Any |
| GET | `/cx-projects` | List engagements | Any |
| POST | `/cx-projects/{id}/advance-phase` | Advance the engagement exactly one phase forward | CxAuthority |
| POST | `/cx-projects/{id}/issue-acceptance` | Issue a substantial or final acceptance certificate; computes and persists the FINAL variant of acceptance_completion_score | OwnerRepresentative |
| GET | `/cx-projects/{id}/readiness` | Computed read exposing both variants of acceptance_completion_score side by side, plus the posture inputs | Any |
| POST | `/cx-projects/{id}/run-seasonal-sweep` | Ops checkpoint: sweeps every DeferredTest of the project whose window_end is at or before the current logical clock into MISSED and opens a SEASONAL issue for each | CxAuthority |
| POST | `/owner-requirements` | Add an Owner Project Requirement line | OwnerRepresentative |
| GET | `/owner-requirements` | List OPR lines; filter by project, by predecessor (revision chain) or by status | Any |
| GET | `/owner-requirements/{id}` | Read one OPR line | Any |
| POST | `/owner-requirements/{id}/approve` | Owner approves an OPR line, making it eligible for plan pinning | OwnerRepresentative |
| POST | `/owner-requirements/{id}/revise` | Supersede an approved OPR line with a new DRAFT revision | OwnerRepresentative |
| POST | `/cx-plans` | Draft a commissioning plan; the new plan supersedes every prior plan of the project, so the caller must present the project version it last observed | CxAuthority |
| GET | `/cx-plans` | List commissioning plans | Any |
| GET | `/cx-plans/{id}` | Read one commissioning plan including its pinned requirement set | Any |
| POST | `/cx-plans/{id}/approve` | Owner approves the plan; pins the project's currently APPROVED OwnerRequirement ids onto the plan | OwnerRepresentative |
| POST | `/submittals` | Design team lodges a submittal for review | DesignTeam |
| GET | `/submittals` | List submittals | Any |
| GET | `/submittals/{id}` | Read one submittal | Any |
| POST | `/submittals/{id}/review` | Commissioning authority records a design-review decision | CxAuthority |
| POST | `/submittals/{id}/resubmit` | Design team resubmits a rejected submittal, opening a new review round | DesignTeam |
| POST | `/equipment-units` | Register a piece of equipment in the commissioning scope | PlatformAdmin, CxAuthority |
| GET | `/equipment-units` | List equipment | Any |
| GET | `/equipment-units/{id}` | Read one equipment unit with both of its state dimensions | Any |
| POST | `/equipment-units/{id}/install-status` | Advance the installation dimension (NOT_INSTALLED -> INSTALLED -> STARTED_UP, or -> REMOVED) | Contractor |
| POST | `/prefunctional-checklists` | Open a pre-functional checklist for one equipment unit | CxAuthority |
| GET | `/prefunctional-checklists` | List pre-functional checklists | Any |
| GET | `/prefunctional-checklists/{id}` | Read one checklist including its embedded items array | Any |
| POST | `/prefunctional-checklists/{id}/items` | Append a line item to a checklist that is still DRAFT or in REWORK | CxAuthority |
| POST | `/prefunctional-checklists/{id}/record-item` | Contractor records PASS / FAIL / NA against one line item | Contractor |
| POST | `/prefunctional-checklists/{id}/execute` | Contractor signs the checklist off as executed | Contractor |
| POST | `/prefunctional-checklists/{id}/verify` | Commissioning authority verifies an executed checklist; the verifier may not be the executor | CxAuthority |
| POST | `/prefunctional-checklists/{id}/reject` | Compensating action for verify: sends an executed or verified checklist back to REWORK and unwinds every effect the verification had | CxAuthority |
| POST | `/functional-tests` | Schedule a witnessed functional performance test against a pinned OPR line | CxAuthority |
| GET | `/functional-tests` | List functional tests; filter by equipment, by requirement or by retest lineage | Any |
| GET | `/functional-tests/{id}` | Read one functional test | Any |
| POST | `/functional-tests/{id}/start` | Begin witnessing a scheduled test | CxAuthority |
| POST | `/functional-tests/{id}/record-result` | Record the measured value; the server derives PASSED / PASSED_WITH_EXCEPTIONS / FAILED from the requirement tolerance and runs the matching branch | CxAuthority |
| POST | `/functional-tests/{id}/schedule-retest` | Mint a retest row linked to a failed or conditionally passed test | CxAuthority |
| POST | `/issues` | Log a deficiency in the issue log | CxAuthority, Contractor |
| GET | `/issues` | Read the issue log; filter by project, equipment, closing retest, status, severity or origin | Any |
| GET | `/issues/{id}` | Read one issue | Any |
| POST | `/issues/{id}/propose-resolution` | Contractor proposes a corrective action, moving the issue to IN_REVIEW | Contractor |
| POST | `/issues/{id}/verify-closure` | Commissioning authority verifies the correction and closes the issue | CxAuthority |
| POST | `/issues/{id}/reopen` | Re-open a closed, deferred or in-review issue | CxAuthority |
| POST | `/issues/{id}/defer` | Owner defers an issue to a scheduled seasonal test | OwnerRepresentative |
| POST | `/issues/{id}/void` | Compensating action for issue creation: voids an issue and returns every conserved quantity to its pre-issue value | CxAuthority |
| POST | `/deferred-tests` | Schedule seasonal or deferred testing inside a half-open window on one equipment unit | CxAuthority |
| GET | `/deferred-tests` | List seasonal/deferred tests | Any |
| GET | `/deferred-tests/{id}` | Read one seasonal/deferred test | Any |
| POST | `/deferred-tests/{id}/execute` | Execute a planned seasonal test inside its window; the outcome is derived from the requirement tolerance | CxAuthority |
| POST | `/closeout-deliverables` | Plan a training session, a systems-manual section or an O and M data package | Contractor, DesignTeam |
| GET | `/closeout-deliverables` | List closeout deliverables | Any |
| GET | `/closeout-deliverables/{id}` | Read one closeout deliverable | Any |
| POST | `/closeout-deliverables/{id}/deliver` | Record delivery of the training session or document package | Contractor, DesignTeam |
| POST | `/closeout-deliverables/{id}/accept` | Verify the training or manual section; the acceptor may not be the deliverer | CxAuthority, OwnerRepresentative |
| POST | `/closeout-deliverables/{id}/return` | Return a delivered deliverable for rework | CxAuthority |
| POST | `/certification-credits` | Open a certification credit documentation package | CxAuthority |
| GET | `/certification-credits` | List certification credits | Any |
| GET | `/certification-credits/{id}` | Read one credit with its four-step documentation score fields | Any |
| POST | `/certification-credits/{id}/evidence` | Attach an evidence row pointing at a commissioning artifact | CxAuthority |
| GET | `/certification-credits/{id}/evidence` | List the evidence rows attached to a credit | Any |
| POST | `/certification-credits/{id}/submit` | Submit the credit package; requires the project version the caller last observed | CxAuthority |
| POST | `/certification-credits/{id}/adjudicate` | Owner awards or denies a submitted credit | OwnerRepresentative |
| POST | `/energy-baselines` | Record a retro-commissioning measure baseline; permitted only on RETRO_COMMISSIONING projects | CxAuthority |
| GET | `/energy-baselines` | List retro-commissioning measures | Any |
| GET | `/energy-baselines/{id}` | Read one measure with both savings variants side by side | Any |
| POST | `/energy-baselines/{id}/post-period` | Record post-retrofit metering and compute BOTH savings variants | CxAuthority |
| POST | `/energy-baselines/{id}/certify-savings` | Freeze one savings variant as the certified number | CxAuthority |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a supplied instant | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_REQUIREMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMITTAL_NOT_FOUND` | 404 Not Found |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CHECKLIST_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_ISSUE_NOT_FOUND` | 404 Not Found |
| `ERR_DEFERRED_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERABLE_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_BASELINE_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_SCOPE_MISMATCH` | 409 Conflict |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_PROJECT_FROZEN` | 409 Conflict |
| `ERR_PHASE_NOT_ALLOWED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EQUIPMENT_NOT_READY` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_PLAN_PIN_STALE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_RETEST_EVIDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SAFETY_ITEM_FAILED` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_WITNESS_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SEASONAL_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_OUTSIDE_SEASONAL_WINDOW` | 409 Conflict |
| `ERR_RETEST_SCOPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REQUIREMENT_NOT_PINNED` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_REF_INVALID` | 422 Unprocessable Entity |
| `ERR_CHECKLIST_EMPTY` | 422 Unprocessable Entity |
| `ERR_CHECKLIST_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ITEM_CODE` | 422 Unprocessable Entity |
| `ERR_ITEM_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_TRAINING_COVERAGE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_REVIEW_ROUNDS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RETRO_ONLY` | 422 Unprocessable Entity |
| `ERR_VARIANT_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_RETAINAGE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ACCEPTANCE_SCORE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_OPEN_BLOCKING_ISSUES` | 422 Unprocessable Entity |
