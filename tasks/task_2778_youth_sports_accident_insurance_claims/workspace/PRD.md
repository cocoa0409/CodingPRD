# Youth Sports Accident Insurance Claims API — Product Requirements Document

## 1. Introduction

Youth sports accident programs sit in an awkward place in the insurance market. The buyer is a volunteer-run league with a few dozen to a few thousand athletes; the coverage is deliberately thin, written as excess over whatever family health insurance already exists; and the people who touch a claim — a league administrator filing paperwork, a governing-body official attesting that an injury really happened at a sanctioned practice, a claims examiner chasing an explanation of benefits from a family's HMO, a medical reviewer deciding whether a spinal injury is catastrophic — all work for different organisations and cannot be allowed to substitute for one another. The result is a product whose economics are simple but whose controls are not.

This document specifies the backend API that runs such a program end to end: enrolling leagues onto sport-specific policy terms and rating the premium off declared participant counts and hazard class; capturing team activities and having them independently sanctioned; accepting injury reports inside a filing window and having them independently verified; coordinating with the family's own health plan before a dollar is committed; repricing provider charges against a fee schedule and a severity-adjusted benefit schedule while protecting families from balance billing; layering a catastrophic excess above the per-injury limit with a lifetime maximum per athlete; and finally rolling the term's loss experience into a renewal quote.

Two themes recur throughout and are worth stating up front. The first is **segregation of duties**: no single actor can move an injury from the field to a cheque. The second is **derived state**: almost every number a reader cares about — a policy's premium, its incurred loss, its operating posture, a claim's payable benefit, an athlete's remaining lifetime catastrophic benefit — is computed from rows elsewhere in the graph and must be recomputed the moment any of those rows changes. Implementers should treat every stored aggregate named in this document as a projection that the server owes the reader, not as a value a client may supply.

## 2. Global Specifications & System-Wide Principles

Resources in this API are mounted flat at the root. There is no nesting of collections in URL paths: peer entities are joined by explicit identifier fields carried in request bodies, and related rows are reached through filtered list endpoints rather than through composite paths.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. If either header is missing or empty, or if `X-User-Role` does not name one of the six roles declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognised but is not among the roles authorised for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The six roles are `ProgramAdministrator`, `LeagueAdministrator`, `LeagueOfficial`, `ClaimsExaminer`, `MedicalReviewer` and `GuardianPortal`.

- A `ProgramAdministrator` is the accident program's underwriting desk. It owns master data — leagues and sport classifications — the entire policy lifecycle including renewal quoting, and the logical clock.
- A `LeagueAdministrator` acts for one league. It builds the athlete roster, enrols athletes onto policies, schedules team activities, files injury reports, resubmits corrected reports, accepts renewal terms and may withdraw a claim the league no longer wishes to pursue.
- A `LeagueOfficial` is a credentialed official of the national governing body. Officials sanction scheduled activities and independently decide injury-report verifications.
- A `ClaimsExaminer` is the program's claims desk: verifying the family's other coverage, recording and repricing provider charges, collecting explanations of benefits, adjudicating claims and issuing or voiding benefit payments. An examiner may not certify a catastrophic injury and may not touch the policy lifecycle.
- A `MedicalReviewer` alone may certify — or revoke certification of — a catastrophic injury, which is what unlocks the catastrophic excess layer. A reviewer deliberately cannot adjudicate or pay, so the decision that unlocks the dollars and the decision that releases them sit with different people.
- A `GuardianPortal` caller is a parent or guardian acting for a single athlete. Guardians file the family's other health coverage and read that athlete's claims, provider bills and payments so the family can see its protected balance.

Two of these roles are **entity-backed**, meaning `X-User-ID` is not an arbitrary operator string but the identifier of a persisted row, and ownership is checked against it. When `X-User-Role` is `LeagueAdministrator`, `X-User-ID` is the `id` of the acting `League`; ownership checks on any addressed resource compare `X-User-ID` to the `League` reached from that resource — directly for a league, through `league_id` for a policy or a participant, through the policy for an enrollment or an activity, through the enrollment and then the policy for an injury report, and through `league_policy_id` for a claim. When `X-User-Role` is `GuardianPortal`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks compare `X-User-ID` to the participant reached from the addressed resource — directly for a participant, through `participant_id` for a family health plan, and through the claim's enrollment for a claim, a provider bill or a benefit payment. A caller in either role that reaches outside its own subtree is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

The other four roles — `ProgramAdministrator`, `LeagueOfficial`, `ClaimsExaminer` and `MedicalReviewer` — carry **opaque** identities. For these, `X-User-ID` is an operator identifier not tied to any persisted entity, and the server never compares it to any row's `id`. The server does, however, record it wherever an audit trail or a segregation rule needs it: as `sanctioning_official_id` on a sanctioned activity, as `verifying_official_id` on an injury report, as `verified_by_user_id` on a family health plan, as `repriced_by_user_id` on a provider bill, as `adjudicated_by_user_id` and `cat_certified_by_user_id` on a claim, and as `issued_by_user_id` on a benefit payment.

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

### 2.3. Pagination and List Filtering

List endpoints are paginated by two query parameters. `limit` sets the maximum number of rows returned; it defaults to 10 when absent, must be at least 1, and must not exceed 100. `offset` sets how many rows to skip; it defaults to 0 and must not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is a request-shape failure and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, list results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

Beyond pagination, list endpoints accept optional equality filters drawn from the resource's own attributes; supplying several filters narrows the result to rows matching all of them. Leagues may be filtered by `state_code` and `sanctioning_status`. Sport classifications may be filtered by `hazard_class`. Policies may be filtered by `league_id`, `sport_classification_id`, `status` and `coverage_posture`. Participants may be filtered by `league_id` and `roster_status`. Enrollments may be filtered by `participant_id`, `league_policy_id`, `status` and `coverage_status`. Family health plans may be filtered by `participant_id`, `verification_status` and `coverage_state`. Activities may be filtered by `league_policy_id`, `status` and `activity_type`. Injury reports may be filtered by `enrollment_id`, `sanctioned_activity_id`, `status` and `severity_tier`. Claims may be filtered by `injury_report_id`, `league_policy_id`, `enrollment_id`, `adjudication_status` and `coordination_status` — and because a claim is born as a side effect of verification rather than by a direct create call, this filtered list is the only channel through which a client discovers a newly created claim. Provider bills may be filtered by `claim_id`, `status`, `network_status` and `service_category`. Coordination records may be filtered by `claim_id`, `provider_bill_id`, `family_health_plan_id`, `superseded_by_record_id` and `status`. Benefit payments may be filtered by `claim_id`, `provider_bill_id`, `layer`, `payee_type` and `status`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in this system — `League`, `SportClassification`, `LeaguePolicy`, `Participant`, `Enrollment`, `FamilyHealthPlan`, `SanctionedActivity`, `InjuryReport`, `Claim`, `ProviderBill`, `CoordinationRecord` and `BenefitPayment` — carries the same four system-managed properties:

- `id` — a server-minted UUID string. It carries no type prefix; the resource's collection, not its identifier, tells you what kind of thing it is. Clients never supply an `id`.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first written.
- `updated_at` — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row.
- `version` — an integer that starts at 1 and increments by one on every mutation of the row.

A change to a *derived* field counts as a mutation for these purposes. When a claim's payment activity causes its policy's `paid_loss_cents` and `coverage_posture` to be recomputed, the policy's `updated_at` is refreshed and its `version` increments even though no client addressed the policy directly.

All temporal reasoning in this system is measured against a **logical clock**, never against real wall-clock time. Before the clock is ever set it reads exactly `2026-08-01T00:00:00Z`, and the implementation must not fall back to the host's actual time. A `ProgramAdministrator` may move the clock to any ISO 8601 UTC instant by supplying `to_iso8601`; doing so re-evaluates every family health plan's `coverage_state` against the new instant and arms the lazy explanation-of-benefits waiver sweep described in §3.6, which then runs on the next touch of each affected claim. Every filing window, verification window and waiver window in this document is measured against this clock.

### 2.5. Money, Basis Points and Rounding Discipline

All monetary amounts in this system are integers denominated in whole cents. Every field whose name ends in `_cents` is an integer count of cents, and a client that sends a decimal where cents are expected has made a request-shape error. There are no fractional-cent amounts anywhere in a response body.

Rates, loads, credits and modifiers are expressed in **basis points** — hundredths of one percent, so 10000 basis points is exactly one times the base, and every field whose name ends in `_bps` is an integer count of basis points. Applying a basis-point figure means multiplying by that figure and dividing by 10000.

Wherever a calculation in §3 produces a non-integral number of cents or basis points, the result is rounded **half up** to the nearest whole unit at exactly the point the calculation names — never earlier and never later. Several calculations in this document deliberately pin the rounding point, because rounding a sequence of line items individually and then adding them can differ by a cent or two from adding first and rounding once. Where a calculation says a rounding happens per line item, an implementation that rounds only the total is wrong even though the difference is small.

### 2.6. Path and Reference Resolution Order

Identifiers reach the server two ways: as templated path segments and as identifier fields inside request bodies. Both are resolved before any business rule runs, and both are resolved in a fixed order so that failures are reproducible.

Templated path segments — `{league_id}`, `{sport_classification_id}`, `{league_policy_id}`, `{participant_id}`, `{enrollment_id}`, `{family_health_plan_id}`, `{sanctioned_activity_id}`, `{injury_report_id}`, `{claim_id}`, `{provider_bill_id}`, `{coordination_record_id}` and `{benefit_payment_id}` — are resolved strictly left to right. The first segment that does not resolve to a live row determines the response, which is the 404 code naming that entity: `ERR_LEAGUE_NOT_FOUND`, `ERR_SPORT_CLASSIFICATION_NOT_FOUND`, `ERR_LEAGUE_POLICY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_FAMILY_HEALTH_PLAN_NOT_FOUND`, `ERR_SANCTIONED_ACTIVITY_NOT_FOUND`, `ERR_INJURY_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PROVIDER_BILL_NOT_FOUND`, `ERR_COORDINATION_RECORD_NOT_FOUND` or `ERR_BENEFIT_PAYMENT_NOT_FOUND`. Later segments are not consulted once an earlier one has failed.

Identifier fields carried in a request body are resolved after the path and in the order the endpoint declares its input fields, using the same catalogue of 404 codes. Only once every referenced row exists does the server check that those rows are *mutually in scope* — that they actually belong together in the same aggregate. A scope failure is `ERR_SCOPE_MISMATCH` (HTTP 422) and is described where each affected workflow appears in §3.

### 2.7. The Rule Evaluation Ladder

Because a single request can violate several rules at once, the order in which checks run is part of the contract rather than an implementation detail. Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed. Two requests that differ only in which rules they break must therefore produce predictable, non-overlapping errors.

1. **Authentication** — headers present and the role recognised (`ERR_UNAUTHENTICATED`).
2. **Role authorisation** — the role appears in the endpoint's authorised set (`ERR_ROLE_NOT_PERMITTED`).
3. **Ownership** — for the two entity-backed roles, the caller owns the addressed resource (`ERR_OWNERSHIP_MISMATCH`). This applies to every endpoint whose authorised roles include `LeagueAdministrator` or `GuardianPortal`.
4. **Request shape** — every required input field present and non-null; every enum value a declared member of its set; every integer within its declared bound; `provider_npi` exactly ten digits; `state_code` exactly two uppercase letters; every datetime a parseable ISO 8601 UTC instant; `limit` within 1 through 100 and `offset` not negative (`ERR_INVALID_REQUEST`). Undeclared body fields, and computed or system-managed fields sent by a client, are ignored rather than honoured — they neither cause a rejection nor overwrite server state.
5. **Path existence** — every templated identifier resolves, left to right (the entity-specific 404 codes).
6. **Body reference existence** — every identifier field in the body resolves, in declared field order (the same 404 codes).
7. **Referential scope** — referenced rows belong to the same aggregate (`ERR_SCOPE_MISMATCH`).
8. **The addressed resource's own state** — the row is in a state from which the requested transition is legal. The rejection names the entity whose state blocked it: `ERR_INVALID_POLICY_STATE`, `ERR_INVALID_ENROLLMENT_STATE`, `ERR_INVALID_FAMILY_PLAN_STATE`, `ERR_INVALID_ACTIVITY_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_COORDINATION_STATE`, `ERR_INVALID_BILL_STATE` or `ERR_INVALID_PAYMENT_STATE`, each HTTP 409.
9. **Governing policy in force** — the policy whose term the operation falls under is in an acceptable lifecycle state (`ERR_POLICY_NOT_IN_FORCE`).
10. **League standing** — the owning league is currently sanctioned (`ERR_LEAGUE_NOT_SANCTIONED`).
11. **Policy not frozen** — the governing policy's operating posture is not `FROZEN` (`ERR_POLICY_FROZEN`).
12. **Policy not under claims review** — for enrolling a new athlete only, the posture is not `CLAIMS_REVIEW` (`ERR_POLICY_UNDER_CLAIMS_REVIEW`).
13. **Claim version freshness** — the coordination-record write carries the claim version it expects (`ERR_STALE_CLAIM_VERSION`).
14. **Policy version freshness** — the renewal-quote write carries the policy version it expects (`ERR_STALE_POLICY_VERSION`).
15. through 19. **Coverage safety** — the activity is a covered type (`ERR_ACTIVITY_NOT_COVERED`); the activity's sanctioning state permits the operation (`ERR_ACTIVITY_NOT_SANCTIONED`); the acting official is not the one who sanctioned the activity (`ERR_OFFICIAL_SEGREGATION_VIOLATION`); catastrophic certification is only touched on a catastrophic-severity injury (`ERR_SEVERITY_NOT_CATASTROPHIC`); and a determination that reaches into the catastrophic layer requires certification first (`ERR_CAT_CERTIFICATION_REQUIRED`), in exactly that order.
20. through 27. **Temporal windows** — in order: the injury instant lies inside the activity window (`ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW`); the filing window has not expired (`ERR_FILING_WINDOW_EXPIRED`); the verification window has not expired (`ERR_VERIFICATION_WINDOW_EXPIRED`); the activity lies inside the policy term (`ERR_ACTIVITY_OUTSIDE_TERM`); the enrollment date lies inside the term (`ERR_ENROLLMENT_OUTSIDE_TERM`); the service date lies inside the term (`ERR_SERVICE_DATE_OUTSIDE_TERM`); term and renewal dates are ordered correctly (`ERR_TERM_DATES_INVALID`); and coordination has reached a settled position (`ERR_COORDINATION_INCOMPLETE`).
28. through 37. **Business constraints** — in order: no overlapping in-force term for the same league and sport (`ERR_POLICY_TERM_OVERLAP`); no per-athlete activity collision (`ERR_PARTICIPANT_ACTIVITY_CONFLICT`); no duplicate active enrollment (`ERR_DUPLICATE_ENROLLMENT`); correction rounds not exhausted (`ERR_CORRECTION_ROUNDS_EXHAUSTED`); the service category is on the benefit schedule (`ERR_SERVICE_CATEGORY_NOT_SCHEDULED`); league and sport codes unique (`ERR_DUPLICATE_LEAGUE_CODE`, `ERR_DUPLICATE_SPORT_CODE`); no other coverage on file when none is being attested (`ERR_OTHER_COVERAGE_ON_FILE`); the policy permits a full-excess footing (`ERR_FULL_EXCESS_NOT_PERMITTED`); some other coverage exists when an explanation of benefits is requested (`ERR_NO_OTHER_COVERAGE_ON_FILE`); and no issued payment stands in the way of a void or withdrawal (`ERR_PAYMENT_ON_FILE`).
38. through 42. **Fiscal limits** — last of all, in order: the declared head count meets the sport's minimum (`ERR_MINIMUM_PARTICIPANTS_NOT_MET`); the enrollment's lifetime catastrophic benefit is not exhausted (`ERR_LIFETIME_BENEFIT_EXHAUSTED`); nothing being closed out still carries an open claim (`ERR_OPEN_CLAIMS_ON_ENROLLMENT`, `ERR_OPEN_CLAIMS_ON_POLICY`); the payment does not overdraw its layer (`ERR_PAYMENT_EXCEEDS_BENEFIT`); and the payment does not breach the term aggregate (`ERR_AGGREGATE_LIMIT_EXCEEDED`).

The practical consequence worth internalising is that **authorisation outranks existence, existence outranks state, state outranks safety, safety outranks time, time outranks constraints, and constraints outrank money**. A guardian addressing another family's claim gets an ownership failure, not a not-found. A frozen policy's rejection surfaces before any temporal window is examined. A payment that would both overdraw its layer and breach the term aggregate reports the layer overdraw.

### 2.8. Coverage Posture — the Program's Circuit Breaker

Alongside its lifecycle `status`, every policy carries a derived operating posture, `coverage_posture`, taking one of three values: `OPEN`, `CLAIMS_REVIEW` or `FROZEN`. Posture is what actually gates whether new exposure and new claim activity may be written; `status` records where the term is in its life, posture records whether the program is presently willing to let anything happen under it. Posture is recomputed at the end of every write that changes the policy itself, changes its league's sanctioning standing, or changes any claim or benefit payment beneath it.

The posture is selected by walking six tests strictly from the top and stopping at the first that matches:

1. If the policy's `status` is `CLOSED` or `CANCELLED`, the posture is `FROZEN`.
2. Otherwise, if the holding league's `sanctioning_status` is `SUSPENDED`, the posture is `FROZEN`.
3. Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`. The test is inclusive: an incurred loss exactly equal to the aggregate limit freezes the term.
4. Otherwise, if the policy's `open_claim_count` is three or more, the posture is `CLAIMS_REVIEW`.
5. Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`.
6. Failing all of them, the posture is `OPEN`.

Because the tests are ordered and the first match wins, a policy whose league is suspended reads `FROZEN` even if it also has four open claims; the `CLAIMS_REVIEW` tests are never reached. A `FROZEN` posture blocks essentially every forward-moving write under the term and yields `ERR_POLICY_FROZEN`. A `CLAIMS_REVIEW` posture is narrower: it blocks only the writing of *new covered lives*, so enrolling a further athlete is refused with `ERR_POLICY_UNDER_CLAIMS_REVIEW` while claims already in flight continue to be repriced, coordinated, adjudicated and paid.

Posture sits beside a second, separate policy gate. Independently of posture, many operations require the governing policy's lifecycle `status` to be *in force for that particular operation*, and the required set differs by operation. Enrolling an athlete, scheduling an activity and taking a sanction decision on an activity require the policy to be `BOUND` or `ACTIVE`. Every injury-report operation — filing a report, returning one for correction, resubmitting a corrected one and taking the verification decision — requires the policy to be `ACTIVE`, and only `ACTIVE`; a term that has moved into run-off admits no new or in-flight injury reporting at all. Recording a provider bill, repricing one, filing a coordination record, requesting an explanation of benefits, confirming that no other coverage exists, adjudicating a claim, issuing a benefit payment and quoting a renewal all require the policy to be `ACTIVE` or `RUN_OFF`, because these are the claim-settlement operations that a run-off term exists to let finish. Any of these attempted against a policy outside its required set is refused with `ERR_POLICY_NOT_IN_FORCE`.

The frozen gate then covers the same list of operations with one exception: returning an injury report for correction is *not* blocked by a `FROZEN` posture, whereas filing, resubmitting and deciding a report are. So `ERR_POLICY_FROZEN` can arise from enrolling an athlete, scheduling an activity, taking a sanction decision, filing an injury report, resubmitting one, taking a verification decision, recording a provider bill, repricing one, filing a coordination record, requesting an explanation of benefits, confirming no other coverage, adjudicating a claim, issuing a benefit payment or quoting a renewal. Compensating and closing actions are deliberately absent from both lists: voiding a bill, voiding a payment, withdrawing a claim, withdrawing an enrollment and cancelling the term itself all remain available under a frozen posture, because a circuit breaker that prevented anyone from cleaning up would be worse than no breaker at all.

### 2.9. Cascade Propagation and Recomputation Discipline

This system has no eventual consistency and no background jobs. Every aggregate is correct at the end of the request that disturbed it, and the propagation is explicitly chained: each link is caused by the link before it alone, so an implementation that fires only the first hop will diverge on the second and third.

Four propagation chains recur, and the workflow subsections in §3 spell each one out where it belongs:

- **Verification opening a claim.** An official's verification of an injury report stamps the report, creates exactly one claim, brings that claim into the policy's open set, forces the policy's loss aggregates and posture to be recomputed, and — if the posture lands on `FROZEN` — sweeps the policy's still-unsanctioned activities into rejection.
- **Payment consuming lifetime catastrophic benefit.** Issuing a payment updates the claim's paid totals, may advance the claim to `PAID`, re-accumulates the athlete's lifetime catastrophic usage, may flip that enrollment's coverage to exhausted, and then rejects every injury report of that enrollment still awaiting a verification decision.
- **Voiding a payment.** A void must leave the program's books exactly where they stood before the payment. It reverses the claim's paid totals, may reopen a `PAID` claim back to `APPROVED`, and forces the policy's paid loss, reserves, incurred loss, both loss ratios, open-claim count, experience tier and posture back to their prior values. Where the voided payment drew on the catastrophic layer, the athlete's lifetime usage is recomputed downward and their coverage may leave the exhausted state.
- **Suspending a league.** Suspension freezes every policy the league holds, which rejects those policies' unsanctioned activities, which in turn rejects the injury reports hanging off those activities.

Reinstatement is deliberately **forward-only**. Restoring a suspended league to good standing lifts the freeze on its policies, but activities and injury reports already driven to `REJECTED` stay rejected; nothing is revived.

### 2.10. Stale-Version Protection on Coordination and Renewal Writes

Two writes in this system overwrite data that another writer may legitimately have changed since the client last looked, and both are therefore guarded by optimistic concurrency control. In each case the guard is a required input field carrying the client's last observed `version` of a *parent* row, and a value that does not match that parent's current `version` is rejected outright.

Filing an explanation-of-benefits record requires `expected_claim_version`, carrying the `version` the client last read on the claim named by `claim_id`. If it does not equal that claim's current `version`, the request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). The reason is concrete: a corrected explanation of benefits supersedes the prior active record for the same provider-bill-and-family-plan pair and rewrites the claim's `other_insurance_paid_cents`, so a client working from a stale view of the claim would supersede a record it never saw.

Producing a renewal quote requires `expected_league_policy_version`, carrying the `version` the client last read on the addressed policy. A mismatch with the policy's current `version` is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). Again the reason is concrete: a new quote overwrites the whole previous renewal block, and the loss experience it is priced from moves on every claim, payment and reserve change, so a stale writer would publish a quote rated off superseded loss figures.

These are the only two version-carrying writes in the system. No other endpoint accepts a version field, and no other endpoint performs a version comparison.

### 2.11. Interval Conventions

Three kinds of interval appear in this specification and they do **not** share a convention. Getting them confused is the single easiest way to produce off-by-one behaviour, so each is stated explicitly.

A **policy term** is the half-open interval running from `term_effective_date` inclusive to `term_expiration_date` exclusive. A date equal to the effective date is inside the term; a date equal to the expiration date is outside it. Two terms that merely touch — one term's expiration date equal to the next term's effective date — do not overlap, and both may be bound.

An **activity window** is the closed interval running from `starts_at` to `ends_at`, with both endpoints inside the window. An injury recorded at exactly `starts_at` or exactly `ends_at` happened during the activity.

A **buffered activity window**, used only for detecting collisions between activities that share an athlete, widens the closed window symmetrically by that activity's own `travel_buffer_minutes` on each side, and the resulting intervals are also closed. Two buffered windows that merely touch at a single instant *do* collide.

Day counts — the filing window, the verification window and the explanation-of-benefits waiver window — are whole UTC calendar days, computed by taking the calendar date of each endpoint and counting the days between them. Each window is inclusive of the stated day count: a count equal to the limit is still inside the window, and only the first day beyond it is late.

## 3. Business Logic & Workflows

### 3.1. Master Data: Leagues, Sanctioning Standing and Sport Classifications

Everything in the program hangs off two pieces of master data that only the underwriting desk may author. A `ProgramAdministrator` registers a **League** by supplying its legal `name`, a short operator-assigned `league_code`, the two-letter `state_code` of the US state in which it operates, the `governing_body_code` of the national body that sanctions it, and a `contact_email` for the league administrator of record. The `league_code` must be unique across all leagues and must be between 3 and 16 characters drawn from uppercase letters, digits and the hyphen; re-using a code already on file is refused with `ERR_DUPLICATE_LEAGUE_CODE`. A newly registered league starts with `sanctioning_status` set to `SANCTIONED` and `in_force_policy_count` set to 0. That count is derived, not stored input: at any moment it is the number of policy terms held by this league whose lifecycle `status` is `BOUND`, `ACTIVE` or `RUN_OFF`.

Governing bodies do occasionally discipline leagues, and the underwriting desk records those decisions by submitting a new `sanctioning_status` together with a free-text `reason`. Standing moves among exactly three values — `SANCTIONED`, `PROBATION` and `SUSPENDED` — and only along five legal edges: `SANCTIONED → PROBATION`, `SANCTIONED → SUSPENDED`, `PROBATION → SUSPENDED`, `PROBATION → SANCTIONED` and `SUSPENDED → SANCTIONED`. A submission whose target value is not reachable from the league's present standing — restating the value the league already holds, or trying to move a suspended league straight onto probation — is not a legal transition. Placing a league on probation is a soft signal: every policy the league holds recomputes its `coverage_posture`, but probation alone never forces a freeze. Suspension is the hard signal, and it drives the three-link cascade of §2.9: every policy of the league recomputes its posture and lands on `FROZEN` because its holding league is suspended; because those policies just became frozen, each of their activities still in `PENDING_SANCTION` moves to `REJECTED` with `rejection_reason` set to `POLICY_FROZEN`; and because those activities just became rejected, every injury report pointing at one of them whose own status is `PENDING_VERIFICATION` or `RETURNED_FOR_CORRECTION` moves to `REJECTED` with `rejection_reason` set to `ACTIVITY_NOT_SANCTIONED`. Restoring a suspended league to `SANCTIONED` recomputes posture on all its policies, and a policy leaves `FROZEN` unless its own `incurred_loss_cents` has reached its `aggregate_limit_cents` — but as §2.9 says, the activities and reports already rejected are never revived.

The second piece of master data is the **SportClassification**, which is where the underwriting desk fixes both the rating basis and every coverage limit for a sport-and-age-band combination. A classification is created with a unique `sport_code` (a duplicate is refused with `ERR_DUPLICATE_SPORT_CODE`), a human-readable `sport_name`, a `hazard_class` of `CLASS_1_LOW`, `CLASS_2_MODERATE`, `CLASS_3_HIGH` or `CLASS_4_CONTACT`, and a manual annual `base_rate_per_participant_cents` of at least one cent. The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard.

The same row also carries the coverage architecture. `deductible_cents` is the per-claim deductible the program applies when it pays excess of other insurance, and may be zero. `per_injury_limit_cents`, at least one cent, is the base layer's maximum benefit for a single injury. `cat_attachment_point_cents` is the benefit amount above which the catastrophic layer attaches, and must be at least the per-injury limit; where it is strictly greater, the corridor between the two is uninsured by design and the specification deliberately does not close it. `aggregate_limit_cents`, also at least the per-injury limit, is the term aggregate ceiling on incurred loss for one policy. `cat_lifetime_max_cents`, which may be zero, is the lifetime catastrophic-layer maximum for a single enrolled athlete. `minimum_participants`, at least one, is the smallest declared head count the program will write for the sport. `travel_buffer_minutes`, which may be zero, is the default buffer applied on both sides of an activity window when looking for athlete scheduling collisions.

Finally, the classification carries the benefit schedule itself as `service_category_caps` — a map from a service category to the maximum allowed amount in cents for that category. Its keys must be a subset of the seven recognised categories `EMERGENCY_ROOM`, `SURGERY`, `DIAGNOSTIC_IMAGING`, `PHYSICAL_THERAPY`, `DENTAL`, `AMBULANCE` and `PHYSICIAN_OFFICE`, and every value must be an integer of zero or more cents; a map containing a key outside that set is a request-shape failure. A category simply absent from the map is **not scheduled** under this sport, which has a direct consequence at repricing time described in §3.7.

### 3.2. Quoting, Binding and Activating a Policy Term

A **LeaguePolicy** is one league's coverage of one sport classification for one term, and the underwriting desk creates it as a quote. The request names the `league_id` of the holding league and the `sport_classification_id` that fixes the rating basis and every limit, sets the term boundaries `term_effective_date` and `term_expiration_date`, and declares the `enrolled_participant_count` — at least one — that the premium will be rated on. That declared count is a rating input and is deliberately independent of how many enrollment rows the league later actually creates. Two optional elections complete the request: `coverage_basis_election`, which is `EXCESS_ONLY` unless the request says `FULL_EXCESS_PERMITTED`, and `cat_layer_elected`, a boolean that is false unless the request says otherwise. The expiration date must be strictly after the effective date, or the quote is refused with `ERR_TERM_DATES_INVALID`.

A newly quoted policy takes `status` `QUOTED` and `renewal_quote_status` `NONE`, and immediately mirrors five figures from its sport classification onto itself — `deductible_cents`, `per_injury_limit_cents`, `cat_attachment_point_cents`, `aggregate_limit_cents` and `cat_lifetime_max_cents` — so that a claim can be determined without traversing back to master data. Its premium is computed on the spot, so the league can see the number before committing, and it is recomputed from scratch when the term is bound. The `cancel_reason` field stays null unless and until the term is cancelled.

**How the premium is built.** The gross premium slices the declared head count into three cumulative volume bands and prices each band separately. The first band covers participants 1 through 75 at full rate — a factor of exactly 1.0000. The second band covers participants 76 through 400 at a factor of 0.9250, a seven-and-a-half percent volume discount. The third band covers every participant beyond 400 at a factor of 0.8500. Concretely, the first band's head count is the declared count capped at 75; the second band's head count is the declared count capped at 400 with 75 subtracted, and is zero if that subtraction would go negative; the third band's head count is the declared count with 400 subtracted, and is likewise zero if that would go negative.

Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**. The hazard load is folded into each band line before that line is rounded; it is never applied to a summed total. `gross_premium_cents` is then the plain sum of the three already-rounded band lines. This ordering is pinned and consequential: an implementation that adds the three unrounded band amounts and rounds once at the end will differ from the specification by a cent or two on many head counts, and that answer is wrong.

From the gross premium, five further steps run in exactly this order and no other:

1. If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents. If the layer was not elected, the charge is exactly 0.
2. `premium_subtotal_cents` is the gross premium plus the catastrophic layer charge.
3. `volume_credit_bps` is the credit rate selected **from the subtotal computed in step 2** — never from the gross premium, and never from the final annual premium. A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points.
4. `volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents.
5. `annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars. The floor is applied **after** the credit, not before it.

Keying the credit on the subtotal rather than on the gross premium is a deliberate design decision with a visible effect: because the catastrophic layer charge is inside the subtotal, electing that layer can push a policy into a higher credit tier and change the credit *rate*, not merely the credit amount. `annual_premium_cents` is also the earned-premium denominator for every loss ratio in §3.9.

**Binding.** A quoted term is bound by the underwriting desk, which is the moment the program actually goes on risk. Binding requires the policy to be in `QUOTED`, the holding league to be `SANCTIONED` (otherwise `ERR_LEAGUE_NOT_SANCTIONED`), the declared `enrolled_participant_count` to be at least the sport's `minimum_participants` (otherwise `ERR_MINIMUM_PARTICIPANTS_NOT_MET`), and no other policy for the same league-and-sport pairing whose `status` is `BOUND`, `ACTIVE` or `RUN_OFF` to hold a term intersecting this one (otherwise `ERR_POLICY_TERM_OVERLAP`). Because terms are half-open, a prior term whose expiration date equals this term's effective date does not intersect and both may be bound. On success the whole premium build-up is recomputed from scratch, `status` moves `QUOTED → BOUND`, the holding league's `in_force_policy_count` increases by one, and posture is recomputed.

**Activation and run-off.** A bound term goes on risk as `BOUND → ACTIVE` once the logical clock has reached or passed its `term_effective_date`; attempting it earlier is refused, and posture is recomputed on success. When the clock has reached or passed `term_expiration_date`, the underwriting desk moves the term `ACTIVE → RUN_OFF`, which stops all new exposure — no further enrollment, activity or injury report may be created under the term — while letting the claims already open continue to be adjudicated and paid. If the term's `open_claim_count` is already zero at that instant, the system's own `RUN_OFF → CLOSED` transition fires within the same request. That closing transition is re-evaluated by the server at the end of every write that changes the term's open-claim count as well as on entry to run-off; it requires the term to be in `RUN_OFF` with an open-claim count of zero, and when it fires it decreases the league's `in_force_policy_count` by one and drives the posture to `FROZEN`, because a closed term accepts no further child writes.

**Cancellation.** Cancelling a term is available from three states and always requires a `cancel_reason`, which is stored on the policy. From `QUOTED` the cancellation is unconditional: `status` becomes `CANCELLED`, the reason is stored, and posture becomes `FROZEN`; nothing else changes, because a quoted term was never counted as in force. From `BOUND` the cancellation additionally requires the term's `open_claim_count` to be zero; on success the reason is stored, `status` becomes `CANCELLED`, the league's `in_force_policy_count` decreases by one, and posture becomes `FROZEN`. From `ACTIVE` the cancellation likewise requires an open-claim count of zero; on success the reason is stored, `status` becomes `CANCELLED`, the league's `in_force_policy_count` decreases by one, posture becomes `FROZEN`, and — the one behaviour unique to the active case, because an active term is the only one that can have live scheduling under it — every activity of the policy still in `PENDING_SANCTION` moves to `REJECTED` with `rejection_reason` set to `POLICY_FROZEN`. A cancellation attempted against a term that still carries an open claim is refused with `ERR_OPEN_CLAIMS_ON_POLICY`; run-off, and not cancellation, is the sanctioned path for a term whose claims have not finished, which is precisely why the run-off transition deliberately carries no such check. A cancellation attempted from `CLOSED`, `CANCELLED` or `RUN_OFF` is refused with `ERR_INVALID_POLICY_STATE`.

### 3.3. Building the Roster: Athletes and Their Enrollments

A `LeagueAdministrator` builds the league's roster by adding **Participants**. Each athlete is recorded against the `league_id` of the league whose roster carries them, with `first_name`, `last_name`, a `date_of_birth` expressed as an ISO 8601 UTC instant at midnight, a `guardian_email` for the parent or guardian of record, and optionally a `guardian_phone`. A newly added athlete begins with `roster_status` `ROSTERED` and `enrolled_policy_count` 0.

Both of those athlete-level fields are derived from enrollment rows rather than supplied. `enrolled_policy_count` is the number of this athlete's enrollments whose `status` is `ENROLLED`. `roster_status` is `ROSTERED` while at least one enrollment of the athlete is `ENROLLED`, becomes `INACTIVE` once every enrollment of the athlete has been withdrawn, and — importantly for the moment just after an athlete is added — reads `ROSTERED` when the athlete has no enrollment rows at all.

An **Enrollment** is the pairing that actually puts an athlete on risk, and it is a genuine many-to-many join: one athlete may be enrolled under several sport policies at the same time, which is exactly how a multi-sport child ends up with two live coverages. The league administrator creates one by naming the `participant_id`, the `league_policy_id` of the sport policy the athlete is to be covered under, and the `enrolled_on_date` on which the athlete joined that roster. Four gates apply. The athlete and the policy must belong to the same league — the athlete's own `league_id` must equal the policy's `league_id`, and a mismatch is `ERR_SCOPE_MISMATCH`. The `enrolled_on_date` must fall inside the policy's half-open term, or the request is refused with `ERR_ENROLLMENT_OUTSIDE_TERM`. The policy must not already carry an enrollment of this same athlete whose `status` is `ENROLLED`, or the request is refused with `ERR_DUPLICATE_ENROLLMENT` — note that a previously withdrawn enrollment does not block a fresh one. And, uniquely among the operations in this system, enrolling is also blocked when the policy's posture is `CLAIMS_REVIEW`, with `ERR_POLICY_UNDER_CLAIMS_REVIEW`: a term whose loss position has deteriorated may finish the claims it already has but may not take on further covered lives until that position clears.

A new enrollment starts with `status` `ENROLLED`, `lifetime_cat_benefit_used_cents` 0 and `coverage_status` `COVERED`, and its creation immediately recomputes the athlete's `enrolled_policy_count` and `roster_status`. The `withdrawn_on_date` field stays null while the enrollment is live.

`coverage_status` is the single field the rest of the system consults to ask "is this athlete actually covered right now?", and it is derived by three ordered tests. If the enrollment's `status` is `WITHDRAWN`, the coverage status is `WITHDRAWN_NO_COVERAGE`. Otherwise, if `lifetime_cat_benefit_used_cents` has reached or passed the governing policy's `cat_lifetime_max_cents`, the coverage status is `LIFETIME_EXHAUSTED` — the test is inclusive, so paying out exactly the lifetime maximum exhausts the athlete. Otherwise the coverage status is `COVERED`.

Withdrawing an athlete from a policy roster is the league administrator's own act, carried out with a `withdrawal_note`, and it drives the enrollment `ENROLLED → WITHDRAWN`. It is refused if the enrollment still carries a claim in `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`, with `ERR_OPEN_CLAIMS_ON_ENROLLMENT`; the league must let those claims finish or withdraw them first. On success the enrollment's `withdrawn_on_date` is stamped with the logical clock, its `coverage_status` becomes `WITHDRAWN_NO_COVERAGE`, and the athlete's `enrolled_policy_count` and `roster_status` are recomputed — which is how an athlete's last withdrawal flips them to `INACTIVE`. Withdrawing an already-withdrawn enrollment is refused with `ERR_INVALID_ENROLLMENT_STATE`, as is filing an injury report against a withdrawn enrollment.

### 3.4. Scheduling and Sanctioning Team Activities

Coverage attaches to activities, not to calendar days, so the league administrator records each **SanctionedActivity** the team intends to hold. An activity is created against a `league_policy_id` with an `activity_type`, a `venue_name` describing the venue or the travel, and the closed window `starts_at` to `ends_at`. The optional `travel_buffer_minutes` may be supplied to widen this particular activity's collision footprint; when it is omitted, the activity inherits the governing sport classification's own `travel_buffer_minutes` as its default. Every new activity starts in `PENDING_SANCTION`, with `sanctioning_official_id` and `rejection_reason` both null.

`activity_type` takes one of five values: `PRACTICE`, `GAME`, `SANCTIONED_TRAVEL`, `TRYOUT` and `TEAM_SOCIAL`. Only the first four are covered activities, and the boolean `is_covered_activity` is computed from the type on this basis — true for a practice, a game, sanctioned travel or a tryout, and false for a team social. The team barbecue is scheduled like anything else, but an injury there is never a covered loss.

Scheduling runs two checks beyond the ordinary shape and reference validation. First, the activity's own **unbuffered** closed window must lie inside the governing policy's half-open term, and `starts_at` must not be later than `ends_at`; a violation is `ERR_ACTIVITY_OUTSIDE_TERM`. Note the asymmetry with the buffer: the buffer widens the collision footprint but never extends the coverage window, so the term test uses the raw window.

Second, and more subtly, the program refuses to schedule an athlete into two places at once — and it enforces this **per athlete, across policy and sport boundaries**, not per policy. The candidate activity's window is widened symmetrically by the candidate's own `travel_buffer_minutes`, once before `starts_at` and once after `ends_at`. Every activity it is compared against is widened by **its own** buffer, not the candidate's; two activities with different buffers therefore contribute different footprints. The comparison set is assembled by walking from the candidate's policy to the athletes enrolled under it, then out from each of those athletes to every other policy they are also enrolled under, and collecting every activity of those policies whose `status` is `PENDING_SANCTION` or `SANCTIONED`. Rejected activities are ignored. Two widened windows collide when the candidate's widened start is at or before the other's widened end **and** the other's widened start is at or before the candidate's widened end — both intervals being closed, so windows that merely touch at a single instant do collide. Any collision refuses the request with `ERR_PARTICIPANT_ACTIVITY_CONFLICT`. Contrast this deliberately with the half-open policy term of §2.11: two terms that touch at an endpoint do not overlap, while two buffered activity windows that touch at an endpoint do.

A `LeagueOfficial` then decides the activity by supplying a `decision` of either `SANCTION` or `REJECT`, optionally with a `reason`. Both branches require the activity to be in `PENDING_SANCTION`; a decision on an activity that has already been decided is refused with `ERR_INVALID_ACTIVITY_STATE`. A `SANCTION` decision additionally requires the governing policy's `status` to be `BOUND` or `ACTIVE` and its posture not to be `FROZEN`; on success the activity moves `PENDING_SANCTION → SANCTIONED` and the deciding official's `X-User-ID` is written to `sanctioning_official_id`. That recorded identity matters far beyond the audit trail: as §3.5 explains, it bars that same official from later deciding an injury report arising from this activity. A `REJECT` decision carries no policy-state requirement of its own; on success the activity moves `PENDING_SANCTION → REJECTED` with `rejection_reason` set to `OFFICIAL_DECLINED`.

An activity can also be rejected without any official acting, by the system, when the owning policy's posture becomes `FROZEN` — whether that freeze arrives from a league suspension, from a cancellation of an active term, or from the loss-driven freeze described in §3.5. In that case the activity moves `PENDING_SANCTION → REJECTED` with `rejection_reason` set to `POLICY_FROZEN`, and, as the next link in the chain, every injury report pointing at this activity whose own status is `PENDING_VERIFICATION` or `RETURNED_FOR_CORRECTION` moves to `REJECTED` with `rejection_reason` set to `ACTIVITY_NOT_SANCTIONED`.

### 3.5. Injury Reporting and Independent Verification

When an athlete is hurt, the league administrator files an **InjuryReport**. The filing names the `enrollment_id` of the covered athlete-and-policy pairing the injury is reported under and the `sanctioned_activity_id` of the activity during which it happened, and records the `injury_datetime`, the injured `body_part`, a narrative `injury_description` of the mechanism of injury, and a `severity_tier`. The body region is one of `HEAD_NECK`, `SHOULDER_ARM`, `HAND_WRIST`, `TORSO`, `HIP_GROIN`, `KNEE`, `ANKLE_FOOT`, `DENTAL` or `OTHER`. The severity classification — `MINOR`, `MODERATE`, `SEVERE` or `CATASTROPHIC` — is what later drives both the benefit-schedule severity factor of §3.7 and the case reserve struck when a claim is opened.

The activity and the enrollment must belong together: the activity's `league_policy_id` must equal the enrollment's `league_policy_id`, and a report that reaches across policies is refused with `ERR_SCOPE_MISMATCH`. Beyond that, filing runs a chain of coverage checks in the ladder order of §2.7. The activity must be a covered type, so a report against a team social is refused with `ERR_ACTIVITY_NOT_COVERED`. The activity's own status must not be `REJECTED`, or the filing is refused with `ERR_ACTIVITY_NOT_SANCTIONED` — note that filing against an activity still merely `PENDING_SANCTION` is allowed, because in practice the paperwork often arrives before the official's sanction does; the sanction is required later, at verification. The `injury_datetime` must fall inside the activity's closed window from `starts_at` to `ends_at`, with both endpoints counting as inside, or the filing is refused with `ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW`. And the athlete's enrollment must not have run out of lifetime catastrophic benefit; a `coverage_status` of `LIFETIME_EXHAUSTED` refuses the filing with `ERR_LIFETIME_BENEFIT_EXHAUSTED`.

Two timestamp fields are stamped by the server, never by the client. `reported_on_date` is the logical clock's UTC calendar date, truncated to midnight of that date. `days_to_report` is the whole number of UTC calendar days from the calendar date of `injury_datetime` to `reported_on_date`. The program's **filing window is ninety days**: a `days_to_report` of ninety or fewer is timely, and ninety-one or more refuses the filing with `ERR_FILING_WINDOW_EXPIRED`. A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null.

**The correction loop.** A `LeagueOfficial` reviewing an incomplete report may send it back rather than decide it, supplying a `correction_note`. This moves the report `PENDING_VERIFICATION → RETURNED_FOR_CORRECTION`, increments `correction_round_count` by one, and stores the note as the most recent correction note on the report. The loop is bounded at **two rounds**: a return attempted when `correction_round_count` already equals two is refused with `ERR_CORRECTION_ROUNDS_EXHAUSTED`. Returning a report is also subject to segregation of duties — the official sending it back may not be the official who sanctioned the underlying activity.

The league administrator answers a return by resubmitting, supplying a fresh `injury_description` and `severity_tier` which **overwrite** the values previously on the report. Resubmission moves the report `RETURNED_FOR_CORRECTION → PENDING_VERIFICATION` and deliberately does **not** reset `correction_round_count`, so the two-round budget is consumed across the whole life of the report rather than per round-trip. A resubmission is also bounded in time: the whole number of UTC days from the report's `created_at` to the logical clock must be no more than **thirty**, and a later attempt is refused with `ERR_VERIFICATION_WINDOW_EXPIRED`. Because the eventual case reserve is struck from the report's severity tier at the moment a claim is opened, a resubmission that changes the severity before verification changes the reserve the claim is eventually born with. A resubmission attempted on a report that is not `RETURNED_FOR_CORRECTION`, or a return or verification decision attempted on a report that is not `PENDING_VERIFICATION`, is refused with `ERR_INVALID_REPORT_STATE`.

**The verification decision.** A `LeagueOfficial` decides a pending report by supplying a `decision` of `VERIFY` or `REJECT`, with an `official_attestation` on verification and optionally a `reason` on rejection. Both branches require the report to be in `PENDING_VERIFICATION` and both are subject to the program's central segregation rule: the deciding official's `X-User-ID` must differ from the `sanctioning_official_id` recorded on the linked activity. An official who sanctioned an activity may not decide an injury report arising from it, and an attempt is refused with `ERR_OFFICIAL_SEGREGATION_VIOLATION`. In practice this means at least two distinct official identities are needed to move any claim forward — which is the whole point.

A `VERIFY` decision carries five further requirements beyond the report's own state and the segregation rule. The linked activity must actually be in `SANCTIONED` (not merely un-rejected), or the decision is refused with `ERR_ACTIVITY_NOT_SANCTIONED`. The activity's `is_covered_activity` must be true, or the decision is refused with `ERR_ACTIVITY_NOT_COVERED`. The whole number of UTC days from the report's `created_at` to the logical clock must be no more than thirty, or the decision is refused with `ERR_VERIFICATION_WINDOW_EXPIRED`. The athlete's enrollment must not read `LIFETIME_EXHAUSTED`, or the decision is refused with `ERR_LIFETIME_BENEFIT_EXHAUSTED`. And the governing policy's posture must not be `FROZEN`, or the decision is refused with `ERR_POLICY_FROZEN`.

Verification is the single most consequential write in the system, because it runs the five-link chain of §2.9 end to end:

1. The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text.
2. Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`. It copies `league_policy_id` and `enrollment_id` off the report's enrollment onto itself — the latter so that lifetime catastrophic accumulation is addressable without traversing back through the report — records the originating report as `injury_report_id`, and is struck with a case reserve. Note that the new claim is **not** returned in the verification response body; it is discovered through the filtered claim list of §2.3.
3. Caused by the claim's creation alone, the claim joins its policy's open set, so the policy's `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `open_claim_count` and `experience_tier` are all recomputed.
4. Caused by those recomputed figures alone, the policy's `coverage_posture` is re-derived and may move to `CLAIMS_REVIEW` or `FROZEN` — a third open claim is exactly what tips a policy into claims review.
5. Caused by that posture change alone, if the posture landed on `FROZEN`, every activity of that policy still in `PENDING_SANCTION` moves to `REJECTED` with `rejection_reason` `POLICY_FROZEN`, which in turn rejects the injury reports hanging off those activities as described in §3.4.

**The case reserve.** The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers. The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one. The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone. Taking the smaller of the two prevents the program from reserving more than the policy could ever pay.

A `REJECT` decision is far simpler: the report moves `PENDING_VERIFICATION → REJECTED`, `rejection_reason` is set to `OFFICIAL_DECLINED`, `verifying_official_id` is set to the deciding official's `X-User-ID`, and **no claim is created**. Beyond the report's own state and the segregation rule, a rejection carries none of the five additional requirements the verification branch carries — an official must be able to decline a report even when the activity was never sanctioned or the window has run out.

Reports can also be rejected without any official acting. When the system rejects a report — either because the athlete's enrollment has just become `LIFETIME_EXHAUSTED`, or because the linked activity has just been rejected by the system — the report moves to `REJECTED` from **either** `PENDING_VERIFICATION` or `RETURNED_FOR_CORRECTION`, with `rejection_reason` set to `LIFETIME_BENEFIT_EXHAUSTED` in the first case and `ACTIVITY_NOT_SANCTIONED` in the second, and in neither case is a claim created. The two starting states behave identically here; a report sitting in the correction loop is not shielded from either cause.

### 3.6. Coordinating with the Family's Own Health Plan

This is excess coverage, so before the program commits a dollar it needs to know what the family's own health insurance did. Two things make that hard in practice: families forget to tell anyone they have coverage, and carriers take weeks to produce an explanation of benefits. The coordination axis exists to make both of those situations resolvable without stalling a claim forever.

**Recording the family's coverage.** Either a `GuardianPortal` caller acting for the athlete or a `ClaimsExaminer` may record a **FamilyHealthPlan** against a `participant_id`. The record carries the `carrier_name`, the `policy_number`, a `plan_type` of `HMO`, `PPO`, `HDHP`, `MEDICAID` or `TRICARE`, the plan's own `individual_deductible_cents` (zero or more) and `coinsurance_bps` (between 0 and 10000 basis points inclusive) — both recorded purely for file completeness and never used in any program calculation — and the coverage dates `effective_date` and optional `termination_date`. A termination date left absent means the coverage is open-ended.

The plan's `coverage_state` is derived from the logical clock rather than stored: it is `ACTIVE` when the `effective_date` is at or before the current logical clock **and** either the `termination_date` is absent or the clock is strictly before it; otherwise it is `TERMINATED`. Moving the clock therefore re-evaluates every family plan's coverage state, which is one of the two documented consequences of setting the clock in §2.4.

Separately from the clock-derived coverage state, a plan carries a `verification_status` recording whether the claims desk has actually spoken to the carrier. It begins `UNVERIFIED`, with `verified_at` and `verified_by_user_id` null. A `ClaimsExaminer` records the outcome by supplying a `decision` and a `note`, and the plan moves either `UNVERIFIED → VERIFIED` — the carrier confirmed the coverage — or `UNVERIFIED → NO_COVERAGE_ATTESTED`, meaning the carrier confirmed there is in fact no coverage here. Both branches stamp `verified_at` with the logical clock and `verified_by_user_id` with the examiner's `X-User-ID`. The two branches differ in exactly one further respect: a plan attested as having no coverage stops counting as other coverage on file, which is what unblocks the full-excess route below. A verification attempted on a plan that is no longer `UNVERIFIED` is refused with `ERR_INVALID_FAMILY_PLAN_STATE`.

Throughout the rest of this section, the phrase **other coverage on file** means precisely this: the set of family health plans belonging to the claim's athlete whose `coverage_state` is `ACTIVE` and whose `verification_status` is *not* `NO_COVERAGE_ATTESTED`. A single such plan is enough to constitute other coverage.

**The coordination axis.** Every claim carries `coordination_status` as a second, independent state axis alongside its adjudication status, and the two evolve without reference to one another except at a single declared join described in §3.8. Coordination begins at `NOT_STARTED` and settles at one of three values — `EOB_RECEIVED`, `EOB_WAIVED` or `NO_OTHER_COVERAGE_CONFIRMED` — and both moves out of `NOT_STARTED` require the claim's `adjudication_status` to be `PENDING_COORDINATION` or `UNDER_ADJUDICATION`.

A `ClaimsExaminer` requesting the explanation of benefits, optionally with a `note`, drives `NOT_STARTED → EOB_REQUESTED` and stamps `eob_requested_at` with the logical clock. It requires other coverage to be on file; if the athlete holds no qualifying plan, there is nothing to request an explanation of benefits from and the request is refused with `ERR_NO_OTHER_COVERAGE_ON_FILE`.

The mirror-image move is the examiner confirming that no other coverage exists, supplied with an `attestation_note`, which drives `NOT_STARTED → NO_OTHER_COVERAGE_CONFIRMED`. It carries the opposite membership test: the set of qualifying plans must be **empty**, and any single plan with an `ACTIVE` coverage state that has not been attested as no-coverage refuses the request with `ERR_OTHER_COVERAGE_ON_FILE`. It carries one further requirement of its own: the governing policy's `coverage_basis_election` must be `FULL_EXCESS_PERMITTED`. A term written on an `EXCESS_ONLY` basis may never run a claim as program-primary, and the attempt is refused with `ERR_FULL_EXCESS_NOT_PERMITTED`. On success the claim's `coordination_basis` becomes `FULL_EXCESS`, which — as §3.7 makes precise — doubles the deductible the claim must absorb.

Either move attempted from a coordination status that is not `NOT_STARTED` is refused with `ERR_INVALID_COORDINATION_STATE`.

**The forty-five-day waiver.** Requesting an explanation of benefits starts a clock, and the program refuses to let a slow carrier hold a family's claim hostage indefinitely. The system lazily re-evaluates each claim at the start of every read or write that touches it: when the claim's coordination status is `EOB_REQUESTED`, `eob_requested_at` is not null, and the whole number of days from `eob_requested_at` to the logical clock is **more than forty-five**, the claim moves `EOB_REQUESTED → EOB_WAIVED` before anything else in that request happens. A day count of exactly forty-five leaves the claim in `EOB_REQUESTED`; the forty-sixth day waives it. A waived claim takes `coordination_basis` `EXCESS_OF_OTHER` with `other_insurance_paid_cents` treated as zero, and no explanation-of-benefits record may be filed against it afterwards. Because the sweep runs *before* the rest of the request, a claim whose request has gone stale passes the coordination-settled test at adjudication rather than failing it.

`coordination_basis` itself is derived, never supplied. It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`.

**Filing the explanation of benefits.** A `ClaimsExaminer` files a **CoordinationRecord** naming the `claim_id` whose coordination file it belongs to, the `provider_bill_id` of the specific charge the family plan adjudicated, and the `family_health_plan_id` of the plan that issued it. The record carries the `eob_received_date` on which the program received it, plus the three figures off the explanation of benefits itself: `other_plan_allowed_cents` (zero or more), `other_plan_paid_cents` (zero or more and never greater than the allowed amount) and `patient_responsibility_cents` (zero or more). It must also carry `expected_claim_version` as described in §2.10.

The three references must be mutually in scope: the named provider bill must belong to the named claim, and the named family health plan must belong to the claim's own athlete — the plan's `participant_id` must equal the participant behind the claim's enrollment. Either mismatch is refused with `ERR_SCOPE_MISMATCH`. The claim's coordination status must be `EOB_REQUESTED` or `EOB_RECEIVED`; filing against any other coordination status — including a claim that has already been waived — is refused with `ERR_INVALID_COORDINATION_STATE`. A record filed for an athlete who holds no family health plan with an `ACTIVE` coverage state is refused with `ERR_NO_OTHER_COVERAGE_ON_FILE`.

A newly filed record takes `status` `ACTIVE` with `superseded_by_record_id` null, and increments the parent claim's `version` by one. Carriers do reissue corrected explanations of benefits, and the program handles that by superseding rather than editing: any record already `ACTIVE` for the **same combination of provider bill and family health plan** moves to `SUPERSEDED`, and its `superseded_by_record_id` is set to the identifier of the new record. Only `ACTIVE` records contribute to any total. Filing the first record on a claim also drives the coordination axis `EOB_REQUESTED → EOB_RECEIVED`, after which `coordination_basis` reads `EXCESS_OF_OTHER`, and the claim's `other_insurance_paid_cents` and its whole benefit determination are recomputed.

At the provider-bill level the same accumulation is exposed as `other_plan_paid_cents` on the bill itself — the sum of `other_plan_paid_cents` across the `ACTIVE` coordination records pointing at that bill. At the claim level, `other_insurance_paid_cents` is the sum of `other_plan_paid_cents` across this claim's `ACTIVE` coordination records whose `provider_bill_id` names one of the claim's bills in `REPRICED` or `ADJUDICATED` status.

### 3.7. Provider Billing, Repricing and Balance Protection

Medical charges arrive from providers, and a `ClaimsExaminer` records each one as a **ProviderBill** against a `claim_id`. The record identifies the billing provider by `provider_npi` — exactly ten digits — and `provider_name`, states whether the provider participates in the program network through `network_status` (`IN_NETWORK` or `OUT_OF_NETWORK`), classifies the charge with a `service_category` drawn from `EMERGENCY_ROOM`, `SURGERY`, `DIAGNOSTIC_IMAGING`, `PHYSICAL_THERAPY`, `DENTAL`, `AMBULANCE` or `PHYSICIAN_OFFICE`, gives the `service_date`, and carries the two money figures the repricing engine needs: `billed_charge_cents`, the gross amount the provider billed, of at least one cent, and `fee_schedule_amount_cents`, the program's own fee-schedule amount for the service, which may be zero.

The `service_date` must fall inside the governing policy's half-open term, and it must not precede the calendar date of the injury the claim arose from; either violation is refused with `ERR_SERVICE_DATE_OUTSIDE_TERM`. A recorded bill enters `SUBMITTED` with `allowed_amount_cents` 0 and with `negotiated_amount_cents`, `scheduled_cap_cents`, `balance_billed_cents`, `family_responsibility_cents`, `repriced_at`, `repriced_by_user_id` and `void_reason` all still unset. **No repricing happens at record time**; recording a charge and pricing it are deliberately separate acts.

**Repricing.** The examiner then reprices the charge, which requires the bill to be `SUBMITTED` (otherwise `ERR_INVALID_BILL_STATE`), the parent claim's `adjudication_status` to be `PENDING_COORDINATION` or `UNDER_ADJUDICATION`, the governing policy's posture not to be `FROZEN`, and — the substantive gate — the bill's `service_category` to be a declared key of the governing sport classification's `service_category_caps` benefit schedule. A charge in a category the sport does not schedule cannot be priced at all and is refused with `ERR_SERVICE_CATEGORY_NOT_SCHEDULED`.

Repricing computes five figures, in this order:

1. `negotiated_amount_cents` branches on the network status. For an in-network provider it is the smaller of the billed charge and the fee-schedule amount. For an out-of-network provider the program is willing to go above its own fee schedule but not without limit: take the fee-schedule amount, multiply by 14000 basis points — one hundred and forty percent — divide by ten thousand and round half up to whole cents, then take the smaller of the billed charge and that number.
2. `scheduled_cap_cents` is the benefit schedule's cap for this service category, adjusted for how badly the athlete was hurt. Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents. The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter. Because the factor is pulled from the injury report rather than from the bill, the same charge for the same service reprices differently depending on the severity recorded on the claim's report.
3. `allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero.
4. `balance_billed_cents` is the billed charge less the allowed amount, floored at zero.
5. `family_responsibility_cents` is the balance-protection figure and it is where the program's promise to families lives. For an in-network provider it is **always exactly zero** — a participating provider may bill the family nothing above the allowed amount. For an out-of-network provider it is the balance billed, but capped at 15,000 cents (one hundred and fifty dollars); anything beyond that cap is the provider's problem, not the family's.

A successful reprice moves the bill `SUBMITTED → REPRICED`, stamps `repriced_at` with the logical clock and `repriced_by_user_id` with the examiner's `X-User-ID`, recomputes the parent claim's totals and its benefit determination, and — if the parent claim is still in `PENDING_COORDINATION` — drives the claim's adjudication axis `PENDING_COORDINATION → UNDER_ADJUDICATION`. That advance happens on the **first** successful reprice on any bill of the claim and is independent of where the coordination axis has got to.

**The benefit determination.** Everything above feeds one waterfall, recomputed from scratch every time a bill is repriced or voided, every time an explanation-of-benefits record is filed, every time the coordination axis moves out of `NOT_STARTED`, and every time a catastrophic certification is issued or revoked. It runs as follows.

`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`. Alongside it, `balance_billed_total_cents` is the sum of `balance_billed_cents` and `family_responsibility_total_cents` the sum of `family_responsibility_cents` across the same set of bills — the latter being the balance-protection figure the family is shown.

Two variant-dependent quantities come next, and they are what make the coordination basis matter financially. The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case. The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents. The doubling is the price of the program standing primary: when the family carries no other coverage at all, the claim runs on a `FULL_EXCESS` basis and the offset is zero, but the family absorbs twice the deductible, which lowers the payable benefit relative to an `EXCESS_OF_OTHER` claim on which the other plan happened to pay nothing.

From there:

- The **net after other insurance** is the allowed-amount total less the offset, floored at zero.
- `deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb.
- `benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero.
- `base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`.
- The **catastrophic-eligible amount** is `benefit_before_limit_cents` less the policy's `cat_attachment_point_cents`, floored at zero.
- The athlete's **remaining lifetime catastrophic benefit** is the policy's `cat_lifetime_max_cents` less the enrollment's `lifetime_cat_benefit_used_cents`, floored at zero.
- `cat_layer_benefit_cents` is the smaller of the catastrophic-eligible amount and that remaining lifetime benefit — but **only** when the policy's `cat_layer_elected` is true *and* the claim's `cat_certification_status` is `CERTIFIED`. If either condition fails, `cat_layer_benefit_cents` is exactly zero.
- `benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`.

Two properties of this waterfall are intentional and must not be "fixed". First, because the base layer is capped at the per-injury limit while the catastrophic layer attaches above the attachment point, and because the attachment point is allowed to exceed the per-injury limit, benefit amounts strictly between the two are payable by **neither** layer and stay with the family. That uninsured corridor is a priced feature of the product; the determination deliberately does not close it. Second, the catastrophic-eligible amount is measured from `benefit_before_limit_cents`, not from what the base layer failed to absorb, so on a policy whose attachment point equals its per-injury limit the two layers can both be paying at once.

**Voiding a charge.** A charge recorded in error is voided by the examiner with a `void_reason`. From `SUBMITTED` the void is unconditional. From `REPRICED` and from `ADJUDICATED` it additionally requires that no benefit payment with `status` `ISSUED` references the bill, and an attempt against a paid bill is refused with `ERR_PAYMENT_ON_FILE`. Voiding from `VOIDED` or `DENIED` is refused with `ERR_INVALID_BILL_STATE`. The consequences differ by starting state, and the difference is the whole point of freezing a determination: a void from `SUBMITTED` or `REPRICED` recomputes the parent claim's totals **and** its benefit determination, whereas a void from `ADJUDICATED` recomputes only `balance_billed_total_cents` and `family_responsibility_total_cents`, because an adjudicated claim's determination is frozen and is never recomputed afterwards.

A repriced bill also changes state without anyone addressing it. When the parent claim is approved, every bill of that claim still in `REPRICED` moves `REPRICED → ADJUDICATED`, which is what makes it payable. When the parent claim is denied, every bill still in `REPRICED` moves `REPRICED → DENIED` and nothing further happens to it.

### 3.8. Certification, Adjudication and Paying the Benefit

**Certifying a catastrophic injury.** The catastrophic excess layer is not unlocked by arithmetic alone; it takes an independent clinical judgement, and only a `MedicalReviewer` may make it. A reviewer certifies by supplying a `certification_note`, which moves the claim's `cat_certification_status` from `NONE` to `CERTIFIED`, stamps `cat_certified_at` with the logical clock and `cat_certified_by_user_id` with the reviewer's `X-User-ID`, stores the note as `cat_certification_note`, and recomputes the benefit determination — which is what can lift `cat_layer_benefit_cents` above zero for the first time. Certification may only be issued on a claim whose originating report carries a `severity_tier` of `CATASTROPHIC`; anything else is refused with `ERR_SEVERITY_NOT_CATASTROPHIC`. Certification is also refused with `ERR_INVALID_CLAIM_STATE` on a claim whose adjudication axis has already reached a terminal state.

A certification issued in error is revoked by a reviewer supplying a `revocation_reason`, which is stored as `cat_revocation_reason`. Revocation moves `cat_certification_status` `CERTIFIED → REVOKED` and recomputes the determination, dropping `cat_layer_benefit_cents` back to zero — because the determination only funds the catastrophic layer while the status reads exactly `CERTIFIED`, and `REVOKED` is not `CERTIFIED`. Revocation carries the same catastrophic-severity requirement as certification, refusing with `ERR_SEVERITY_NOT_CATASTROPHIC` otherwise, and is refused with `ERR_INVALID_CLAIM_STATE` when the claim's certification status is not `CERTIFIED`. Note the asymmetry of authority here: a reviewer who can unlock several million cents of catastrophic benefit cannot adjudicate or pay a single cent of it, and the examiner who adjudicates and pays cannot certify.

**Adjudication.** A `ClaimsExaminer` adjudicates with an `examiner_note`, and this is the one place where the claim's two state axes meet. Four requirements are common to both outcomes: the claim's `adjudication_status` must be `UNDER_ADJUDICATION` (otherwise `ERR_INVALID_CLAIM_STATE`); its `coordination_status` must have reached a settled value — `EOB_RECEIVED`, `EOB_WAIVED` or `NO_OTHER_COVERAGE_CONFIRMED` — which is the **single declared join** between the two axes, and a claim still `NOT_STARTED`, or still `EOB_REQUESTED` with the forty-five-day waiver window not yet elapsed, is refused with `ERR_COORDINATION_INCOMPLETE`; the governing policy's `status` must be `ACTIVE` or `RUN_OFF`; and the policy's posture must not be `FROZEN`. Every other transition on either axis is legal from any value of the other axis; this is the only coupling.

Given those, adjudication branches. It reaches `UNDER_ADJUDICATION → APPROVED` when the athlete's enrollment `status` is `ENROLLED` and `benefit_payable_cents` is at least one cent, and when the determination does not reach into the catastrophic layer without certification: where the policy's `cat_layer_elected` is true and `benefit_before_limit_cents` exceeds the policy's `cat_attachment_point_cents`, the claim's `cat_certification_status` must be `CERTIFIED`, and otherwise the adjudication is refused with `ERR_CAT_CERTIFICATION_REQUIRED` rather than quietly paying the base layer alone. Approval stamps `adjudicated_at` and `adjudicated_by_user_id` and **freezes** five determination figures — `deductible_applied_cents`, `benefit_before_limit_cents`, `base_layer_benefit_cents`, `cat_layer_benefit_cents` and `benefit_payable_cents` — which are never recomputed again on that claim. Approval also moves every bill of the claim still in `REPRICED` to `ADJUDICATED`.

Adjudication reaches `UNDER_ADJUDICATION → DENIED` when exactly one of two conditions holds, and the order in which they are tested is fixed: the enrollment's `status` being `WITHDRAWN` is tested **first** and sets `denial_reason` to `ENROLLMENT_WITHDRAWN`; only if the enrollment is still enrolled is `benefit_payable_cents` of zero tested, setting `denial_reason` to `NO_BENEFIT_PAYABLE`. A withdrawn athlete's claim therefore always denies as `ENROLLMENT_WITHDRAWN` even when the payable benefit also happens to be zero. Denial stamps `adjudicated_at`, `adjudicated_by_user_id` and `denial_reason`, moves every bill still in `REPRICED` to `DENIED`, and takes the claim out of the policy's open set — so the policy's `reserve_cents`, `incurred_loss_cents`, `open_claim_count`, `coverage_posture` and `experience_tier` are all recomputed, which is frequently what lifts a policy back out of `CLAIMS_REVIEW`.

**Issuing benefit payments.** A `ClaimsExaminer` issues a **BenefitPayment** naming the `claim_id` the dollars are drawn against and the `provider_bill_id` of the charge being satisfied, with a `payee_type` of `PROVIDER` or `FAMILY_REIMBURSEMENT`, a `layer` of `BASE` or `CATASTROPHIC` naming which coverage layer the dollars come from, and an `amount_cents` of at least one cent. The bill must belong to the named claim, or the request is refused with `ERR_SCOPE_MISMATCH`. The claim must be `APPROVED` and the bill must be `ADJUDICATED`, refused with `ERR_INVALID_CLAIM_STATE` and `ERR_INVALID_BILL_STATE` respectively.

Two fiscal ceilings then apply, in order. The payment must not overdraw its own layer: for a `BASE` payment, the claim's `paid_base_cents` plus this amount must not exceed the frozen `base_layer_benefit_cents`, and for a `CATASTROPHIC` payment, `paid_cat_cents` plus this amount must not exceed the frozen `cat_layer_benefit_cents`. Nor may a payment exceed the bill's own `allowed_amount_cents`, or drive the claim's `paid_to_date_cents` above `benefit_payable_cents`. Any of these is refused with `ERR_PAYMENT_EXCEEDS_BENEFIT`. Then the term aggregate: the policy's `paid_loss_cents` plus this amount must not exceed its `aggregate_limit_cents`, because the aggregate is a hard ceiling on cash out the door, and a breach is refused with `ERR_AGGREGATE_LIMIT_EXCEEDED`.

An issued payment takes `status` `ISSUED`, stamps `issued_at` with the logical clock and `issued_by_user_id` with the examiner's `X-User-ID`, and leaves `void_reason` and `voided_at` null. It then runs the four-link chain of §2.9. The claim's `paid_base_cents` (the sum of `ISSUED` `BASE`-layer amounts on the claim), `paid_cat_cents` (the same for the `CATASTROPHIC` layer) and `paid_to_date_cents` (their sum) are recomputed, and once `paid_to_date_cents` has reached or passed `benefit_payable_cents` the claim moves `APPROVED → PAID`, taking it out of the open set. Caused by that alone, the athlete's `lifetime_cat_benefit_used_cents` is re-accumulated — it is the sum of `amount_cents` over every `ISSUED` payment on the `CATASTROPHIC` layer across **every** claim of that enrollment, regardless of those claims' adjudication statuses — and the enrollment's `coverage_status` may flip to `LIFETIME_EXHAUSTED`. Caused by *that* alone, every injury report of the same enrollment still in `PENDING_VERIFICATION` or `RETURNED_FOR_CORRECTION` moves to `REJECTED` with `rejection_reason` `LIFETIME_BENEFIT_EXHAUSTED`. And in the same request the policy's `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, both loss ratios, `open_claim_count`, `experience_tier` and `coverage_posture` are recomputed.

**Voiding a payment.** A payment issued in error is voided with a `void_reason`, which requires the payment to be `ISSUED` (otherwise `ERR_INVALID_PAYMENT_STATE`). This is the compensating action for issuance and its governing requirement is that it must leave the policy's `paid_loss_cents` exactly where it stood before the payment. The void stamps `voided_at` with the logical clock and stores the reason, moving the payment `ISSUED → VOIDED`. Because of that alone, the claim's `paid_base_cents`, `paid_cat_cents` and `paid_to_date_cents` are recomputed, and if the claim was `PAID` and its `paid_to_date_cents` now falls below `benefit_payable_cents`, the claim moves `PAID → APPROVED`. This reopen leg is what makes the adjudication axis non-linear: a claim can travel `APPROVED → PAID → APPROVED` any number of times. Because of the reopen alone, the claim re-joins the open set and the policy's `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, `open_claim_count`, `incurred_loss_ratio_bps`, `paid_loss_ratio_bps`, `experience_tier` and `coverage_posture` are all recomputed. Where the voided payment's `layer` was `CATASTROPHIC`, the enrollment's `lifetime_cat_benefit_used_cents` is recomputed downward as well, and its `coverage_status` may leave `LIFETIME_EXHAUSTED` — though, per §2.9, injury reports already rejected for exhaustion are not revived.

**Withdrawing a claim.** A league that no longer wishes to pursue a claim withdraws it, supplying a `withdrawal_reason`. Withdrawal is available from three points on the adjudication axis and in every case requires the claim's `paid_to_date_cents` to be zero; an attempt while any `ISSUED` payment exists on the claim is refused with `ERR_PAYMENT_ON_FILE`. From `PENDING_COORDINATION` the claim moves to `WITHDRAWN`, the reason is stored, and the claim leaves the open set so the policy's `reserve_cents`, `incurred_loss_cents`, `open_claim_count`, `coverage_posture` and `experience_tier` are recomputed. From `UNDER_ADJUDICATION` the same happens, and in addition every bill of the claim in `SUBMITTED` or `REPRICED` moves to `VOIDED` with `void_reason` set to `CLAIM_WITHDRAWN`. From `APPROVED` the same happens again, and the set of bills swept to `VOIDED` with that reason widens to include `ADJUDICATED` bills as well as `SUBMITTED` and `REPRICED` ones. Withdrawal from `PAID`, `DENIED` or `WITHDRAWN` is refused with `ERR_INVALID_CLAIM_STATE`.

### 3.9. Loss Experience and Renewal Pricing

**The loss position.** Everything the program knows about how a policy term is performing is recomputed at the end of every write that changes one of its claims, changes a benefit payment beneath one of those claims, or changes the policy's own `annual_premium_cents`. There is no batch job and no nightly close: the figures are always current as of the last write, and they are exposed as a computed read that returns `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `paid_loss_ratio_bps`, `open_claim_count`, `experience_tier` and the current `coverage_posture` together.

The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`. A claim that has reached `PAID`, `DENIED` or `WITHDRAWN` is not in the open set. From that:

- `paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not. Cash that left the account is not un-spent by the claim it paid subsequently closing, so a `PAID` claim keeps contributing paid loss forever. `VOIDED` payments contribute nothing, which is exactly what makes a void restore the prior figure.
- `reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**. Closing a claim by any route therefore releases its whole case reserve at once.
- `incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`.
- `open_claim_count` is the number of claims in the open set.
- `incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up. `paid_loss_ratio_bps` is the same computation over `paid_loss_cents`.
- `experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`.

Note that closing a claim moves two of these figures in opposite directions when the closure was a payment: the final payment adds to `paid_loss_cents` while simultaneously removing the claim's reserve from `reserve_cents`, so `incurred_loss_cents` can fall on a write that spent money. That is the intended behaviour of a reserve — it is an estimate that is displaced by actuals, not added to them.

**Quoting the following term.** The underwriting desk quotes the next term off this term's experience, supplying a `loss_experience_basis`, a `renewal_effective_date`, a `renewal_enrolled_participant_count` and the `expected_league_policy_version` described in §2.10. Quoting requires the policy's `status` to be `ACTIVE` or `RUN_OFF` (otherwise `ERR_INVALID_POLICY_STATE`) and the league to be currently sanctioned. The renewal term may abut the expiring term but may not reach back into it: `renewal_effective_date` must be on or after the expiring term's `term_expiration_date`, and an earlier date is refused with `ERR_TERM_DATES_INVALID`.

The quote is built in four pinned steps.

1. **Freeze the loss ratio under the elected basis.** `renewal_loss_ratio_bps` is set to `incurred_loss_ratio_bps` when `loss_experience_basis` is `INCURRED`, and to `paid_loss_ratio_bps` when it is `PAID_ONLY`. This is the whole of the difference between the two variants, and it is a large difference: the incurred basis charges the league for case reserves on claims that have not paid a cent, while the paid-only basis ignores every reserve. On a term whose losses are all still sitting in reserve, the paid-only basis reads zero basis points where the incurred basis reads a substantial positive ratio, so the two elections select different tiers and different modifiers from byte-identical claim data. The elected basis is recorded as `renewal_loss_experience_basis`.
2. **Band it.** `renewal_experience_tier` is banded from `renewal_loss_ratio_bps` using the same four bands as `experience_tier`, and `renewal_experience_modifier_bps` is read from that tier: `PREFERRED` is −1500 basis points (a credit), `STANDARD` is 0, `ADVERSE` is +2750 and `DECLINE` is +6000. Because step 1 may have selected the paid-only ratio, `renewal_experience_tier` is not required to agree with the policy's own `experience_tier`, which is always banded from the incurred ratio.
3. **Re-rate from scratch on the renewal head count.** The banded gross premium of §3.2 and the six-step annual assembly that follows it are both run again with the participant count set to `renewal_enrolled_participant_count`, keeping the **same** `SportClassification` and the same `cat_layer_elected` election as the expiring term. The result is `renewal_base_premium_cents`. This is a full re-rate, not a scaling of the expiring premium: the per-band rounding, the catastrophic layer charge, the volume credit tier lookup and the minimum annual premium floor all apply again on the new head count, so a league that grew across a volume tier boundary picks up the larger credit here.
4. **Apply the experience modifier, then the floor.** `renewal_quoted_premium_cents` is the larger of 25,000 cents (the same minimum annual premium as a new term) and `renewal_base_premium_cents` multiplied by the quantity 10000 plus `renewal_experience_modifier_bps`, divided by 10000, rounded half up. This is the only rounding in the renewal calculation itself; the per-band rounding inside step 3 is separate and happens first.

A `DECLINE` tier does **not** block the quote. The program prices the risk at plus 6000 basis points and publishes the number; the league declines it by simply never accepting. Quoting increments the policy's `version`, sets `renewal_quote_status` to `QUOTED`, records `renewal_quote_effective_date` and `renewal_enrolled_participant_count`, and **overwrites any previous renewal block wholesale** — a second quote on the same policy leaves no trace of the first, which is precisely why the stale-version guard matters here.

**Accepting the quote.** The league accepts the quoted terms, moving `renewal_quote_status` `QUOTED → ACCEPTED` and incrementing the policy's `version`. Acceptance requires `renewal_quote_status` to be exactly `QUOTED`; accepting when it reads `NONE` or `ACCEPTED` is refused with `ERR_INVALID_POLICY_STATE`. Acceptance records the league's agreement to the price and nothing more — it does not create the renewal term, does not alter the expiring term's own `annual_premium_cents`, and does not change the expiring term's `status`. The next term is created as a new policy through the ordinary quote-and-bind flow of §3.2.

## 4. API Endpoint Definitions

Every endpoint below is mounted at the root of the API; there are no nested collection paths, and a child resource is created by naming its parent in the request body rather than in the path. Endpoints that create a new resource return HTTP 201; every other successful call returns HTTP 200. All of them return the standard envelope of §2.2, and the state-changing ones return the affected resource in `data` — for a transition endpoint that is the resource whose state moved, not the cascade's downstream victims, which must be re-read through their own endpoints.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to an arbitrary ISO 8601 UTC instant. | ProgramAdministrator |
| POST | `/leagues` | Register a youth sports league; `sanctioning_status` starts at `SANCTIONED`. | ProgramAdministrator |
| GET | `/leagues/{league_id}` | Read one league. | ProgramAdministrator, LeagueAdministrator |
| GET | `/leagues` | List leagues. | ProgramAdministrator |
| POST | `/leagues/{league_id}/sanctioning-status` | Record a governing-body sanctioning decision on the league. | ProgramAdministrator |
| POST | `/sport-classifications` | Create a sport and age-band classification: hazard class, manual rate, every coverage limit and the benefit schedule. | ProgramAdministrator |
| GET | `/sport-classifications/{sport_classification_id}` | Read one sport classification. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer |
| GET | `/sport-classifications` | List sport classifications. | ProgramAdministrator, LeagueAdministrator |
| POST | `/league-policies` | Quote a policy term for one league on one sport classification; premium fields are computed immediately. | ProgramAdministrator |
| GET | `/league-policies/{league_policy_id}` | Read one policy including its premium build-up, loss aggregates and renewal block. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer |
| GET | `/league-policies` | List policies, filterable by holding league, sport classification and lifecycle state. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer |
| POST | `/league-policies/{league_policy_id}/bind` | Bind the quoted term; re-rates the premium and enforces the minimum head count and the no-overlapping-term rule. | ProgramAdministrator |
| POST | `/league-policies/{league_policy_id}/activate` | Put the bound term on risk once the logical clock has reached its effective date. | ProgramAdministrator |
| POST | `/league-policies/{league_policy_id}/run-off` | Move an expired term into run-off so its open claims can finish while no new exposure is written. | ProgramAdministrator |
| POST | `/league-policies/{league_policy_id}/cancel` | Cancel a policy term that carries no open claims. | ProgramAdministrator |
| POST | `/league-policies/{league_policy_id}/renewal-quote` | Quote the following term off this term's loss experience under the elected loss basis. | ProgramAdministrator |
| POST | `/league-policies/{league_policy_id}/renewal-acceptance` | The league accepts the quoted renewal terms. | LeagueAdministrator |
| GET | `/league-policies/{league_policy_id}/loss-experience` | Computed read of the policy's loss position: paid loss, case reserves, incurred loss, both loss ratios, the open-claim count, the experience tier and the coverage posture. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer |
| POST | `/participants` | Add an athlete to a league roster. | LeagueAdministrator |
| GET | `/participants/{participant_id}` | Read one athlete. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer, GuardianPortal |
| GET | `/participants` | List athletes, filterable by holding league. | ProgramAdministrator, LeagueAdministrator |
| POST | `/enrollments` | Enrol an athlete under a sport policy; one athlete may be enrolled under several policies at once. | LeagueAdministrator |
| GET | `/enrollments/{enrollment_id}` | Read one enrollment including its lifetime catastrophic usage. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer |
| GET | `/enrollments` | List enrollments, filterable by athlete and by policy. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer |
| POST | `/enrollments/{enrollment_id}/withdraw` | Withdraw an athlete from a policy roster. | LeagueAdministrator |
| POST | `/family-health-plans` | Record the family's other health coverage for an athlete. | GuardianPortal, ClaimsExaminer |
| GET | `/family-health-plans/{family_health_plan_id}` | Read one family health plan. | ProgramAdministrator, ClaimsExaminer, GuardianPortal |
| GET | `/family-health-plans` | List family health plans, filterable by athlete. | ProgramAdministrator, ClaimsExaminer, GuardianPortal |
| POST | `/family-health-plans/{family_health_plan_id}/verification` | Record the carrier verification outcome; `NO_COVERAGE_ATTESTED` removes the plan from the other-coverage-on-file set. | ClaimsExaminer |
| POST | `/sanctioned-activities` | Schedule a team activity under a policy; runs the per-athlete buffered conflict check across every policy that shares an enrolled athlete. | LeagueAdministrator |
| GET | `/sanctioned-activities/{sanctioned_activity_id}` | Read one activity. | ProgramAdministrator, LeagueAdministrator, LeagueOfficial, ClaimsExaminer |
| GET | `/sanctioned-activities` | List activities, filterable by policy. | ProgramAdministrator, LeagueAdministrator, LeagueOfficial, ClaimsExaminer |
| POST | `/sanctioned-activities/{sanctioned_activity_id}/sanction-decision` | A league official sanctions or declines a scheduled activity; sanctioning records the official's id, which then bars that official from deciding injury reports arising from it. | LeagueOfficial |
| POST | `/injury-reports` | File an injury report against a covered activity for an enrolled athlete; stamps the reported-on date and enforces the 90-day filing window. | LeagueAdministrator |
| GET | `/injury-reports/{injury_report_id}` | Read one injury report. | ProgramAdministrator, LeagueAdministrator, LeagueOfficial, ClaimsExaminer, MedicalReviewer |
| GET | `/injury-reports` | List injury reports, filterable by enrollment and by activity. | ProgramAdministrator, LeagueAdministrator, LeagueOfficial, ClaimsExaminer, MedicalReviewer |
| POST | `/injury-reports/{injury_report_id}/return-for-correction` | A league official returns an incomplete report to the league; allowed at most twice. | LeagueOfficial |
| POST | `/injury-reports/{injury_report_id}/resubmit` | The league resubmits a corrected report; the correction round count is not reset. | LeagueAdministrator |
| POST | `/injury-reports/{injury_report_id}/verification-decision` | A league official verifies or rejects the report; verification opens the claim. The deciding official may not be the official who sanctioned the activity. | LeagueOfficial |
| GET | `/claims/{claim_id}` | Read one claim: both state axes, the whole benefit determination, payment totals and the family's protected balance. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer, MedicalReviewer, GuardianPortal |
| GET | `/claims` | List claims, filterable by originating report, policy and enrollment; this is the only discovery channel for a cascade-created claim. | ProgramAdministrator, LeagueAdministrator, ClaimsExaminer, MedicalReviewer, GuardianPortal |
| POST | `/claims/{claim_id}/request-eob` | Request the explanation of benefits from the family's other carrier, starting the 45-day waiver clock. | ClaimsExaminer |
| POST | `/claims/{claim_id}/confirm-no-other-coverage` | Confirm the athlete carries no other coverage, putting the claim on a full-excess footing with a doubled deductible. | ClaimsExaminer |
| POST | `/claims/{claim_id}/cat-certification` | A medical reviewer certifies the injury as catastrophic, unlocking the catastrophic excess layer. | MedicalReviewer |
| POST | `/claims/{claim_id}/cat-certification-revocation` | A medical reviewer revokes a catastrophic certification issued in error. | MedicalReviewer |
| POST | `/claims/{claim_id}/adjudicate` | Adjudicate the claim against the settled coordination position; freezes the benefit determination and branches to approval or denial. | ClaimsExaminer |
| POST | `/claims/{claim_id}/withdraw` | The league withdraws a claim that has had no benefit dollars paid on it. | LeagueAdministrator |
| POST | `/provider-bills` | Record a provider charge against a claim. | ClaimsExaminer |
| GET | `/provider-bills/{provider_bill_id}` | Read one provider bill including its allowed amount, balance billed and the family's protected share. | ProgramAdministrator, ClaimsExaminer, GuardianPortal |
| GET | `/provider-bills` | List provider bills, filterable by claim. | ProgramAdministrator, ClaimsExaminer, GuardianPortal |
| POST | `/provider-bills/{provider_bill_id}/reprice` | Reprice the charge to an allowed amount against the network status, the fee schedule and the severity-adjusted benefit schedule cap. | ClaimsExaminer |
| POST | `/provider-bills/{provider_bill_id}/void` | Void a provider charge that carries no issued benefit payment. | ClaimsExaminer |
| POST | `/coordination-records` | File an explanation of benefits from the family's carrier against one provider charge; guarded by optimistic concurrency on the claim. | ClaimsExaminer |
| GET | `/coordination-records/{coordination_record_id}` | Read one explanation-of-benefits record. | ProgramAdministrator, ClaimsExaminer |
| GET | `/coordination-records` | List explanation-of-benefits records, filterable by claim, by provider bill, by family plan and by the record they superseded. | ProgramAdministrator, ClaimsExaminer |
| POST | `/benefit-payments` | Issue a benefit payment from a named coverage layer against an adjudicated charge. | ClaimsExaminer |
| GET | `/benefit-payments/{benefit_payment_id}` | Read one benefit payment. | ProgramAdministrator, ClaimsExaminer, GuardianPortal |
| GET | `/benefit-payments` | List benefit payments, filterable by claim and by provider bill. | ProgramAdministrator, ClaimsExaminer, GuardianPortal |
| POST | `/benefit-payments/{benefit_payment_id}/void` | Void an issued benefit payment; the compensating action for issuance, which must leave the policy's paid loss exactly where it stood before. | ClaimsExaminer |

## 5. Error Code Catalogue

Every failed request returns the error envelope of §2.2 with one of the identifiers below in `error_id`. When more than one condition is violated by the same request, the identifier returned is the one whose check comes first in the evaluation ladder of §2.7.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_LEAGUE_NOT_FOUND` | 404 |
| `ERR_SPORT_CLASSIFICATION_NOT_FOUND` | 404 |
| `ERR_LEAGUE_POLICY_NOT_FOUND` | 404 |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_FAMILY_HEALTH_PLAN_NOT_FOUND` | 404 |
| `ERR_SANCTIONED_ACTIVITY_NOT_FOUND` | 404 |
| `ERR_INJURY_REPORT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_PROVIDER_BILL_NOT_FOUND` | 404 |
| `ERR_COORDINATION_RECORD_NOT_FOUND` | 404 |
| `ERR_BENEFIT_PAYMENT_NOT_FOUND` | 404 |
| `ERR_SCOPE_MISMATCH` | 422 |
| `ERR_INVALID_POLICY_STATE` | 409 |
| `ERR_INVALID_ENROLLMENT_STATE` | 409 |
| `ERR_INVALID_FAMILY_PLAN_STATE` | 409 |
| `ERR_INVALID_ACTIVITY_STATE` | 409 |
| `ERR_INVALID_REPORT_STATE` | 409 |
| `ERR_INVALID_CLAIM_STATE` | 409 |
| `ERR_INVALID_COORDINATION_STATE` | 409 |
| `ERR_INVALID_BILL_STATE` | 409 |
| `ERR_INVALID_PAYMENT_STATE` | 409 |
| `ERR_POLICY_NOT_IN_FORCE` | 409 |
| `ERR_LEAGUE_NOT_SANCTIONED` | 409 |
| `ERR_POLICY_FROZEN` | 409 |
| `ERR_POLICY_UNDER_CLAIMS_REVIEW` | 409 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_STALE_POLICY_VERSION` | 412 |
| `ERR_ACTIVITY_NOT_COVERED` | 422 |
| `ERR_ACTIVITY_NOT_SANCTIONED` | 422 |
| `ERR_OFFICIAL_SEGREGATION_VIOLATION` | 422 |
| `ERR_SEVERITY_NOT_CATASTROPHIC` | 422 |
| `ERR_CAT_CERTIFICATION_REQUIRED` | 422 |
| `ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW` | 422 |
| `ERR_FILING_WINDOW_EXPIRED` | 422 |
| `ERR_VERIFICATION_WINDOW_EXPIRED` | 422 |
| `ERR_ACTIVITY_OUTSIDE_TERM` | 422 |
| `ERR_ENROLLMENT_OUTSIDE_TERM` | 422 |
| `ERR_SERVICE_DATE_OUTSIDE_TERM` | 422 |
| `ERR_TERM_DATES_INVALID` | 422 |
| `ERR_COORDINATION_INCOMPLETE` | 422 |
| `ERR_POLICY_TERM_OVERLAP` | 409 |
| `ERR_PARTICIPANT_ACTIVITY_CONFLICT` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_CORRECTION_ROUNDS_EXHAUSTED` | 409 |
| `ERR_SERVICE_CATEGORY_NOT_SCHEDULED` | 422 |
| `ERR_DUPLICATE_LEAGUE_CODE` | 409 |
| `ERR_DUPLICATE_SPORT_CODE` | 409 |
| `ERR_OTHER_COVERAGE_ON_FILE` | 409 |
| `ERR_NO_OTHER_COVERAGE_ON_FILE` | 409 |
| `ERR_FULL_EXCESS_NOT_PERMITTED` | 422 |
| `ERR_PAYMENT_ON_FILE` | 409 |
| `ERR_MINIMUM_PARTICIPANTS_NOT_MET` | 422 |
| `ERR_LIFETIME_BENEFIT_EXHAUSTED` | 422 |
| `ERR_OPEN_CLAIMS_ON_ENROLLMENT` | 409 |
| `ERR_OPEN_CLAIMS_ON_POLICY` | 409 |
| `ERR_PAYMENT_EXCEEDS_BENEFIT` | 422 |
| `ERR_AGGREGATE_LIMIT_EXCEEDED` | 422 |
