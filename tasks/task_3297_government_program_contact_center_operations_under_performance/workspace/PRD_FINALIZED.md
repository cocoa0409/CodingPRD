# Gov Program Contact Center API — Product Requirements Document

## 1. Introduction

Government agencies increasingly outsource citizen-facing contact centers under performance-based contracts, and the financial stakes of those contracts ride on measurable service levels: how fast calls are answered, how rarely callers abandon, and how accurately agents apply program eligibility rules. This document specifies an API for operating such a contact center end to end — from contract award and service-level definition, through staffing certification and call routing, to quality monitoring, surge planning, knowledge maintenance, privacy incident handling, and invoice settlement with performance-driven withholding.

The system serves a coalition of peer roles. An operations lead shapes the commercial and topological skeleton — contracts, service levels, queues, surge windows. A floor supervisor registers and routes calls and manages coaching. Agents answer only the calls placed on their own desks. A quality analyst scores completed calls and adjudicates disputes. A knowledge manager publishes rule changes and administers the training pipeline that keeps certifications honest. A security officer commands the incident lifecycle, and a billing analyst prepares invoices whose withheld amounts are computed from measured performance rather than asserted effort. A platform operator creates contracts and drives the logical clock against which all time-dependent behavior is evaluated.

Two design commitments pervade everything that follows. First, time in this system is a logical quantity, not a wall-clock one: every timestamp that drives an auto-transition, a measurement window, a certification freshness check, or a cure deadline is read from a settable logical clock. Second, money follows measurement: invoice gross is derived from certified staffing, withholding is derived from measured misses against contractually binding service levels, and cure periods give the operator a bounded window to buy back a breach before it hardens into a permanent forfeiture.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The recognized roles, spelled exactly, are `PlatformAdmin`, `OpsManager`, `Supervisor`, `Agent`, `QualityAnalyst`, `KnowledgeManager`, `SecurityOfficer`, and `BillingAnalyst`. A request missing either header, or presenting an `X-User-Role` value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). The clock-setting capability is exempt from the general authentication check in only one respect — it still requires the `PlatformAdmin` role — and every other endpoint enforces both checks.

Role identity is interpreted as follows. When `X-User-Role` is `Agent`, the `X-User-ID` is the `id` of the acting Agent record; ownership checks on any resource that references an Agent — most importantly the call the agent answers or completes, and the quality review the agent disputes — compare the resource's agent foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `OpsManager`, `Supervisor`, `QualityAnalyst`, `KnowledgeManager`, `SecurityOfficer`, or `BillingAnalyst`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as the preparing user id remembered on an invoice for later segregation-of-duties comparison) but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All time-dependent behavior in the system — auto-transitions, measurement windows, certification freshness, cure deadlines, surge activation and expiry, incident reporting timeliness — is evaluated against a single logical clock, never against wall-clock time. Before any clock-setting request is issued, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to real time; like every timestamp the system emits, this reading is rendered with three fractional digits wherever it surfaces in a resource field (`2026-09-01T00:00:00.000Z`). A `PlatformAdmin` may advance the clock to a supplied `to_iso8601` instant; the response reports the new clock reading as `current_utc`. Every clock-set fires the system's time-driven auto-transitions: surge windows whose start has been reached move from `DECLARED` to `ACTIVE`, active surge windows whose end has passed move from `ACTIVE` to `EXPIRED`, and cure periods whose deadline has passed while still `PENDING` are forfeited. These same surge-window auto-transitions are also re-evaluated on every read of a surge window — both list reads and single-resource reads — so a window never reports a stale status to its reader.

### 2.5. Common Resource Properties and the Unified Transition Surface

Most resources carry four system-managed fields: `id`, a server-minted UUID rendered in its canonical 36-character hyphenated string form (for example `3f6b2a7e-4c1d-4e5f-8a9b-0c1d2e3f4a5b`), with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer that increments on every mutation of the resource. Two resources are deliberately leaner: a Certification and a CourseCompletion carry only `id` and `created_at` — both `updated_at` and `version` are absent from them, because neither resource is ever mutated after creation (a certification is invalidated by setting fields on it once, at cascade time, as part of the publishing operation that created that state).

State changes on every entity are driven through a single, uniform surface: a state-transition endpoint on the resource whose request body carries a `to_status` discriminator naming the desired target state. The server dispatches on the pair of the resource's current state and the requested `to_status`. Each transition endpoint recognizes a declared set of target states — exactly the target states named in that entity's lifecycle in §3 — and `to_status` behaves as an enum: a value outside the recognized set is a request-shape failure rejected with `ERR_INVALID_REQUEST` (HTTP 400) at priority 4 of §2.6, before any state-machine consideration. If the requested target is recognized but not reachable from the current state — including re-firing a transition that has already happened, or any request against a resource already in a terminal state — the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Successful transitions return HTTP 200; successful creations of new resources return HTTP 201.

### 2.6. Validation Order and Existence Checking

Every request is validated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication — both headers present and the role recognized, else `ERR_UNAUTHENTICATED`; (2) authorization — the role is permitted for this endpoint, else `ERR_FORBIDDEN`; (3) existence — path identifiers are validated left to right, and body foreign keys are checked in the endpoint's declared input order, each miss producing the entity-specific 404 (`ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_LEVEL_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_QUEUE_NOT_FOUND`, `ERR_CALL_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_COACHING_PLAN_NOT_FOUND`, `ERR_ARTICLE_NOT_FOUND`, `ERR_TRAINING_COURSE_NOT_FOUND`, `ERR_SURGE_WINDOW_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_INVOICE_LINE_NOT_FOUND`, or `ERR_CERTIFICATION_NOT_FOUND`); (4) request shape — required fields present, values well-typed, enum values inside their declared sets, referential fields well-formed, else `ERR_INVALID_REQUEST` (HTTP 400); (5) optimistic-concurrency staleness on the guarded writes, else `ERR_STALE_VERSION` (HTTP 412); (6) state-machine legality of the requested transition, else `ERR_INVALID_STATE`; (7) privacy and ownership gates, else `ERR_FORBIDDEN`; (8) segregation-of-duties on auto-reviewed invoice approval, else `ERR_AUTO_REVIEW_REQUIRES_SECOND_APPROVER`; (9) domain constraint rules (conflicts, locks, duplicates, overlaps, routing failures) carrying their specific error ids; (10) temporal business rules (window ordering, future-dated validity, cure windows, pre-activation cancellation); and (11) fiscal gates on contract close, service-level archive, and agent deactivation.

### 2.7. Precision, Rounding, and Measurement Windows

Numeric outputs obey fixed precision rules. Money is always an integer number of cents, produced by round-half-up. Average speed of answer is expressed in whole seconds, round-half-up. Abandonment is a fraction carried to exactly 4 decimal places, round-half-up. Quality averages are scores carried to exactly 2 decimal places, round-half-up. Review total scores are integers from 0 to 100, round-half-up, and the weighted sum is rounded exactly once at full precision — rounding the two weighted components separately and then summing is a rejected alternative, because at exact half-point boundaries the results diverge, and a half always rounds up, never to even. Staffing targets are whole persons, rounded up to the next integer. Wherever a sum feeds a rounding step, the sum is computed at full precision first and rounded once — never rounded per component.

Each contract declares a `measurement_tz`, an IANA timezone name, and all monthly measurement windows for that contract are evaluated as naive local wall time in that timezone — not as UTC conversions. The measurement window for an invoice whose `period` is a `YYYY-MM` month string runs from midnight at the start of the first day of that month, inclusive, up to but not including midnight at the start of the following month, both interpreted in the contract's declared timezone.

### 2.8. Optimistic Concurrency Control on Contract Terms

Two writes are guarded against stale observation of contract terms, because both commit money or binding targets against a contract the client may have read before another writer changed it. Activating a service level, and approving an invoice, each require the request body to carry `expected_contract_version`, set to the value of the parent Contract's `version` the client last observed. If the contract's current `version` differs from the supplied value — because activation, closure, or any other mutation has advanced it since — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state change occurs. The `expected_contract_version` field is required on those two transitions when, and only when, the requested `to_status` is `EFFECTIVE` (for a service level) or `APPROVED` (for an invoice); requests targeting any other `to_status` on those same endpoints do not carry the field, and no other endpoint in the system takes a version field at all.

### 2.9. Privacy and Ownership Scope

Program data is sensitive, and the API enforces scope rules beyond simple role permission. No endpoint ever returns a Call or Incident row to a caller acting outside the row's visible scope. An `Agent` may act only on calls assigned to that agent's own `X-User-ID`: answering or completing a call whose `agent_id` names someone else is rejected with `ERR_FORBIDDEN`, as is disputing a quality review of a call the agent did not handle. These ownership gates are evaluated after state-machine legality — a request that is both an illegal transition and an ownership violation surfaces the state error first.

## 3. Business Logic & Workflows

### 3.1. Awarding the Contract and Binding Its Service Levels

A `PlatformAdmin` opens commercial life in the system by creating a **Contract**, supplying the `agency_name` of the awarding government agency, the `measurement_tz` timezone in which every monthly measurement window will be evaluated, and the `cap_absolutes` flag that selects the withholding-cap regime (see §3.9). A new contract is born in `DRAFT` with `withheld_cents_cum` at 0 and `cure_periods_used` at 0. The contract collection is readable by every role and can be filtered by `status`.

An `OpsManager` then shapes what the contract promises by creating **ServiceLevel** records. Each service level names its `contract_id`, the `program_code` it scopes (for example MEDICAID), the `metric` it governs — one of `ASA`, `ABANDON`, or `QA_AVG` — and the contractual `target`. Targets are interpreted per metric: for `ASA` the target is seconds and the contract is compliant when the measured value is less than or equal to the target; for `ABANDON` the target is a fraction and compliance likewise means measured less than or equal to target; for `QA_AVG` the target is a score from 0 to 100 and compliance means measured greater than or equal to target. Each service level also carries `cap_pct_of_gross`, the per-line absolute cap on withholding expressed as a fraction of invoice gross, a `remedy_fee_cents` amount that later prices the cure of a breach, and an `effective_from` instant marking the start of its effectiveness window. New service levels are created in `DRAFT`. The service-level collection can be filtered by `contract_id`, `program_code`, `metric`, and `status`.

Activation is where service levels acquire force. An `OpsManager` activates a `DRAFT` service level by requesting `to_status` of `EFFECTIVE`, and two preconditions must hold: the parent Contract must be `ACTIVE`, and the service level's `effective_from` must be at or before the current logical-clock reading. Because activation commits targets against contract terms the client may have read stale, this is one of the two optimistic-concurrency-guarded writes described in §2.8 — the request must carry `expected_contract_version` matching the contract's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) before any state changes. The parent-contract precondition and the contract's own activation precondition (below) are mutually recursive — the first service level of a fresh contract could never activate, because its `DRAFT` parent cannot activate until a service level is `EFFECTIVE`. The system breaks the cycle in the service-level activation write: when the parent Contract is still `DRAFT`, the same request that activates the service level also activates the parent Contract to `ACTIVE` (the parent's `version` increments once for this activation, in addition to the increment the service-level activation itself applies below), and the service-level activation then proceeds against the now-`ACTIVE` parent. A parent Contract in `CLOSED` (or any non-`DRAFT`, non-`ACTIVE` state) remains a hard failure: the activation is rejected with `ERR_INVALID_STATE` (HTTP 409). Note the asymmetry this creates: direct contract activation through the contract's own transition endpoint always requires an already-`EFFECTIVE` service level and never bootstraps one. A successful activation does three things at once: the service level becomes `EFFECTIVE`; every other service level of the same contract, `program_code`, and `metric` that is currently `EFFECTIVE` and has a strictly earlier `effective_from` is cascaded to `SUPERSEDED`; and the parent Contract's `version` is incremented by 1. If the activation's `effective_from` exactly equals that of an already-`EFFECTIVE` sibling for the same contract, program, and metric, the activation is rejected with `ERR_SL_CONFLICT` (HTTP 409) — two service levels may never stand effective at the same instant for the same key. Supersession itself is never requested; it is the system cascade that fires from a later activation.

At any time `t`, the binding service level for a contract, program, and metric triple is the one in `EFFECTIVE` whose `effective_from` is at or before `t`; ties are broken first by the latest `effective_from` and then by the latest `created_at`. This binding rule is what invoice preparation consults when it binds lines to service levels at a period's end.

Retirement of a service level moves it to `ARCHIVED`, the terminal state, via a request with `to_status` of `ARCHIVED`. From `EFFECTIVE`, archival is blocked while any invoice line referencing the service level sits on an invoice in `DRAFT` or `SUBMITTED` — the fiscal gate of §2.6 priority 11 — surfacing as `ERR_INVALID_STATE`; from `SUPERSEDED`, archival is unconditional. The full lifecycle is therefore `DRAFT → EFFECTIVE → SUPERSEDED → ARCHIVED`, with `EFFECTIVE → ARCHIVED` also permitted.

The contract's own lifecycle is short and guarded. From `DRAFT`, an `OpsManager` may activate the contract by requesting `to_status` of `ACTIVE`, which requires that at least one of its service levels has already reached `EFFECTIVE`, and increments the contract's `version` by 1. From `DRAFT`, a contract may also be withdrawn directly to `CLOSED` with no preconditions — the award never took effect. From `ACTIVE`, closure is permitted only when three fiscal gates all pass: no queue of the contract is `OPEN`, no invoice of the contract is in `DRAFT`, `SUBMITTED`, or `APPROVED`, and no incident of the contract is in `OPEN`, `CONTAINED`, or `RESOLVED`. Both successful closure paths increment `version` by 1, and `CLOSED` is terminal.

### 3.2. The Staffing Pipeline: Agents, Courses, and Certifications

An `OpsManager` registers each **Agent** with a `full_name` and a list of `languages` — ISO 639-1 codes such as "en" or "es" that later act as a hard routing filter. Agents begin with `employment_status` of `ACTIVE`. The agent collection can be filtered by `employment_status`.

Program knowledge is taught through **TrainingCourse** records, created by a `KnowledgeManager` with a `program_code`, an optional `knowledge_article_id` linking the course to its source article, and a `required` flag that defaults to true when omitted. When an agent finishes a course, the `KnowledgeManager` records the completion by supplying the `agent_id` and the `valid_until` expiry of the certification that completion grounds; `valid_until` must lie in the future at that moment, otherwise the request is rejected with `ERR_INVALID_REQUEST` under the temporal rules of §2.6 priority 10. Recording a completion has two effects. First, it creates a **CourseCompletion** stamped with `completed_at` taken from the logical clock, and it mints a **Certification** carrying the `agent_id`, the course's `program_code`, the grounding `training_course_id`, and the supplied `valid_until`. Second, when the course has a `knowledge_article_id` set, completion is the retraining path: every certification of that same agent for that same program whose `invalidated_by_article_id` equals the linked article is re-validated — its `invalidated_at` and `invalidated_by_article_id` are both reset to null. Completions of an agent are reverse-reachable through the agent's completions collection, and course completions can be listed with `training_course_id` or `agent_id` filters; the certification collection answers to `agent_id`, `program_code`, `training_course_id`, and `invalidated_by_article_id` filters.

A certification is **standing** at time `t` when its `valid_until` is strictly after `t` — a certification expiring exactly at `t` is already stale — and its `invalidated_at` is null. Standing-ness drives reactivation, routing, staffing counts, and gross-fee computation throughout the system.

Deactivation and reactivation are the two agent transitions, requested with `to_status` of `INACTIVE` or `ACTIVE`. An `OpsManager` may deactivate an `ACTIVE` agent only when the agent is not the `agent_id` of any call in `ASSIGNED` or `ANSWERED`; attempting otherwise is rejected with `ERR_AGENT_HAS_LIVE_CALLS` (HTTP 409). Deactivation excludes the agent from all future routing pools and from every `staffing_actual` count, and increments the agent's `version` by 1. Reactivation from `INACTIVE` requires certification freshness: the agent must hold at least one standing certification, and a successful reactivation likewise increments `version` by 1. There is no terminal state for an agent; employment can oscillate.

### 3.3. Queues, Overflow Topology, and the Routing Selectors

Queues are the dispatch topology of a contract. An `OpsManager` creates a **Queue** with its `contract_id`, the `program_code` it serves, the ISO 639-1 `language_code` spoken on it, and a `queue_type` of either `GENERAL` or `SPECIALTY`. A `GENERAL` queue takes any call of its program and must carry a null `specialty_tag`; a `SPECIALTY` queue requires a `specialty_tag` and only takes calls whose `required_specialty` equals it. A queue is born `OPEN`. The queue collection is filterable by `contract_id`, `program_code`, `status`, and `overflow_queue_id`.

A queue may designate an overflow target through `overflow_queue_id`. The target must be another queue of the same contract, with the same `language_code`, and — when the queue is `SPECIALTY` — the same `specialty_tag`; the referenced queue must already exist both at creation and on every later update, and any mismatch is rejected with `ERR_QUEUE_OVERFLOW_MISMATCH` (HTTP 409). An `OpsManager` may update a queue's `overflow_queue_id` afterward, which increments the queue's `version` by 1 — but clearing the overflow reference (setting it back to null) is forbidden once at least one call has been assigned to the queue, and such an attempt is rejected with `ERR_OVERFLOW_LOCKED` (HTTP 409). Setting or replacing the reference with a valid target remains allowed.

Queue lifecycle is a pause-resume cycle with a guarded exit. Requesting `to_status` of `PAUSED` from `OPEN` removes the queue from routing eligibility unconditionally; requesting `OPEN` from `PAUSED` restores it. Closure, requested with `to_status` of `CLOSED` from either `OPEN` or `PAUSED`, is terminal and guarded: any call whose `queue_id` is this queue and whose status is `WAITING`, `ASSIGNED`, or `ANSWERED` blocks closure with `ERR_QUEUE_NOT_EMPTY` (HTTP 409). Calls parked on a queue are reverse-reachable through the queue's calls collection, filterable by `status`.

Routing a call is a deterministic two-stage selection, and determinism is contractual: ties are always broken by `created_at` ascending, and resource ids are never consulted as tie-breakers. For a call with contract C, program P, language L, and specialty S, the **queue selector** first builds the candidate set: queues of contract C, in program P, in `OPEN` status, whose type matches the call — `GENERAL` candidates when S is null, or `SPECIALTY` candidates whose `specialty_tag` equals S. Filter A then retains only candidates whose `language_code` equals L. Among the survivors that have at least one available certified agent (per the agent selector below), the queue with the earliest `created_at` wins, and the call is marked `assigned_via` of `PRIMARY` with `route_depth` of 1.

Only when that primary set is empty does the overflow fallback engage. The candidates are re-considered ignoring the language filter but still requiring `OPEN` status, and for each the selector walks its `overflow_queue_id` chain at most one hop; the overflow target must itself have an available certified agent for the program. Overflow targets are ranked by the parent queue's `created_at` ascending, and a call routed this way is marked `assigned_via` of `OVERFLOW` with `route_depth` set to the parent hop's depth plus one. A hop is forbidden in two cases: when it would push the call's `route_depth` past the maximum of 2 — a call may overflow at most once, and attempting a second overflow is rejected with `ERR_CALL_OVERFLOW_FORBIDDEN` (HTTP 409) — and when the overflow target is `PAUSED` or `CLOSED`. If no eligible queue exists even after the fallback, the route attempt fails with `ERR_NO_ELIGIBLE_QUEUE` (HTTP 409).

The **agent selector** runs inside the queue selector, once per candidate queue. For queue q and a call of program P and language L, candidate agents must satisfy all of: `employment_status` is `ACTIVE`; L appears in the agent's `languages`; the agent holds a standing certification for P (per §3.2); and the agent is not the `agent_id` of any call currently `ASSIGNED` or `ANSWERED`. The ranking prefers the agent with the fewest calls `COMPLETED` for program P today — where "today" is the logical date in the contract's `measurement_tz` — with ties broken by the agent's `created_at` ascending. An empty agent set means the queue has no available agent, and the queue selector moves on to the next candidate.

### 3.4. The Call Lifecycle: From Enqueue to Completion or Abandonment

A **Call** enters the system when a `Supervisor` (or an `OpsManager`) registers it with the `contract_id` it arrived under, the `program_code` the caller dialed, the caller's `language_code`, an optional `required_specialty`, and the `enqueued_at` logical timestamp of arrival. A new call is `WAITING` with `route_depth` 0 and no `queue_id`, `agent_id`, or `assigned_via` — all three stay null while the call waits. `enqueued_at` drives both chronological measurement ordering and surge-window membership later. The call collection can be filtered by `contract_id`, `program_code`, `status`, `queue_id`, `agent_id`, and `handled_by_agent_id`.

Routing is requested by a `Supervisor` with `to_status` of `ASSIGNED`. Two preconditions gate it: the contract must be `ACTIVE`, and the selectors of §3.3 must find both an eligible queue and a certified available agent on it. A successful route writes `queue_id`, `agent_id`, `assigned_via`, and `route_depth` in one stroke and increments the call's `version` by 1.

From `ASSIGNED`, the call can only be answered by the agent it was routed to: the answering transition requests `to_status` of `ANSWERED` with an `X-User-ID` equal to the call's `agent_id`, acting in the `Agent` role; anyone else is refused with `ERR_FORBIDDEN`. Answering stamps `answered_at` from the logical clock, computes `answer_seconds` as the whole-second difference between `answered_at` and `enqueued_at`, and freezes `handled_by_agent_id` to the answering `agent_id` — a copy that never changes afterward and survives any later reassignment of the call record. Completion follows the same ownership rule: requesting `to_status` of `COMPLETED` from `ANSWERED` stamps `ended_at` from the logical clock and computes `talk_seconds` as the whole-second difference between `ended_at` and `answered_at`.

Abandonment is the caller's exit. A `Supervisor` may request `to_status` of `ABANDONED` from `WAITING` — the caller hung up before routing — or from `ASSIGNED` — the caller hung up while the phone rang. Either path stamps `abandoned_at` from the logical clock. `COMPLETED` and `ABANDONED` are the terminal states. One subtlety matters for later measurement: a call that is `ASSIGNED` but not yet answered has not resolved, so it counts neither as answered nor as abandoned in any metric.

### 3.5. Quality Monitoring, Disputes, and Coaching

Once a call is `COMPLETED`, a `QualityAnalyst` may score it by creating a **QualityReview** with the `call_id`, an `accuracy_score` from 0 to 100, a `compliance_score` from 0 to 100, and optionally an `accuracy_weight`. The weight must lie strictly between 0 and 1 — endpoints excluded — and defaults to 0.5 when omitted; the compliance weight is always one minus the accuracy weight. The review's `total_score` is computed immediately as the round-half-up of the accuracy weight times the accuracy score plus the compliance weight times the compliance score, computed at full precision and rounded exactly once to an integer. New reviews are `SUBMITTED` with `final` false. The review collection is filterable by `call_id` and `status`.

A review is resolved along two paths. Acceptance, requested by a `QualityAnalyst` with `to_status` of `ACCEPTED`, sets `final` to true and fires the auto-coaching cascade described below. Dispute, requested with `to_status` of `DISPUTED`, is the reviewed agent's prerogative: the acting `X-User-ID` must equal the `handled_by_agent_id` of the reviewed call, and anyone else's dispute is refused with `ERR_FORBIDDEN`. A disputed review is then adjudicated by a `QualityAnalyst`: `to_status` of `UPHELD` confirms the score, sets `final` to true, and fires the identical auto-coaching cascade as acceptance; `to_status` of `OVERTURNED` voids it — the review is excluded from `QA_AVG` aggregation and from coaching triggers, and `final` stays false. `ACCEPTED`, `UPHELD`, and `OVERTURNED` are all terminal; the lifecycle is `SUBMITTED → ACCEPTED | DISPUTED`, then `DISPUTED → UPHELD | OVERTURNED`. Only final reviews — those in `ACCEPTED` or `UPHELD` — ever feed the quality average or coaching.

The auto-coaching cascade watches every review that becomes final. When a final review's `total_score` is below the auto-coach threshold of 70, and the agent named by the reviewed call's `handled_by_agent_id` has no CoachingPlan in `OPEN` or `ESCALATED`, and no `AUTO_QUALITY` CoachingPlan already exists for that agent with a `created_at` within the trailing seven days up to now, the system creates a new CoachingPlan for that agent with `trigger` of `AUTO_QUALITY`, a `due_date` fourteen days after now, and `status` `OPEN`. The review itself records nothing of this — the cascade increments nothing on the review.

A `Supervisor` may also open a **CoachingPlan** directly, supplying the `agent_id` and a `due_date`; such plans carry `trigger` of `MANUAL` and open in `OPEN`. At most one plan per agent may be open at any time: creating any plan — manual or automatic — for an agent who already has a plan in `OPEN` or `ESCALATED` is rejected with `ERR_DUPLICATE_PLAN` (HTTP 409). The plan collection is filterable by `agent_id`, `status`, and `trigger`. From `OPEN`, a `Supervisor` may drive a plan to `COMPLETED`, to `ESCALATED`, or to `CANCELLED`; from `ESCALATED`, the plan may still reach `COMPLETED` after corrective action resolves, or be `CANCELLED`. `COMPLETED` and `CANCELLED` are terminal.

### 3.6. Knowledge Maintenance and the Retraining Cascade

Program rules change, and the knowledge pipeline is how the contact center stays honest about who still knows the rules. A `KnowledgeManager` authors a **KnowledgeArticle** with its `program_code`, `title`, `body`, and the `effective_at` instant at which the underlying program rule takes effect; articles are created in `DRAFT`. The article collection is filterable by `program_code` and `status`.

Publication is the consequential act. When a `KnowledgeManager` requests `to_status` of `PUBLISHED` on a draft article, the retraining cascade fires: every certification whose `program_code` equals the article's, and whose grounding course completion's `completed_at` is strictly before the article's `effective_at`, is invalidated — its `invalidated_at` is set to the current logical-clock reading and its `invalidated_by_article_id` to the publishing article's id. Agents left holding no remaining standing certification for that program are not deactivated, but they become unroutable for it: the agent selector of §3.3 will no longer match them to that program's queues, and they no longer count toward that program's `staffing_actual`. The way back is the retraining path of §3.2 — completing a course linked to the published article re-validates exactly the certifications that article invalidated.

Retirement, requested with `to_status` of `RETIRED` on a published article, is terminal and deliberately one-way: retirement never resurrects invalidated certifications. Courses linked to an article are reverse-reachable through the article's training-courses collection.

### 3.7. Surge Planning Around Enrollment Periods and Public Events

Volume surges — enrollment periods, policy changes, public events — are declared ahead of time so staffing targets and gross fees can flex with demand. An `OpsManager` declares a **SurgeWindow** with its `contract_id`, the affected `program_code`, a `surge_type` of `ENROLLMENT_PERIOD`, `POLICY_CHANGE`, or `PUBLIC_EVENT`, the `starts_on` and `ends_on` bounds, and an `expected_volume_factor` forecast multiplier. Two shape rules apply at creation: `ends_on` must be strictly after `starts_on`, and `expected_volume_factor` must be strictly greater than 1.0; violations are `ERR_INVALID_REQUEST` (HTTP 400). A window is created `DECLARED` — or `ACTIVE` immediately if the logical clock has already reached `starts_on` at creation time.

Windows of the same contract and program may not overlap, and adjacency counts as collision: a candidate window spanning the half-open interval from its start to its end collides with an existing `DECLARED` or `ACTIVE` window whenever the candidate's start is at or before the existing window's end and the candidate's end is at or after the existing window's start — so a candidate beginning exactly when another ends is rejected. Collisions surface as `ERR_SURGE_OVERLAP` (HTTP 409).

Windows ride the logical clock. When the clock reaches a declared window's `starts_on` — evaluated on every clock-set and on every list or detail read of surge windows — the window moves from `DECLARED` to `ACTIVE` on its own. When the clock passes an active window's `ends_on`, the window moves from `ACTIVE` to `EXPIRED`. Cancellation is the only manual transition and is available only before activation: an `OpsManager` may request `to_status` of `CANCELLED` from `DECLARED` while the logical clock is still strictly before `starts_on`; once the clock has reached the start, cancellation is no longer a defined transition and fails with `ERR_INVALID_STATE`. `EXPIRED` and `CANCELLED` are terminal. A contract's windows are reverse-reachable through its surge-windows collection, and the window collection itself is filterable by `contract_id`, `program_code`, and `status`.

The surge multiplier used by money and staffing math — the same selector everywhere — is: the `expected_volume_factor` of the `ACTIVE` window for the contract and program at the instant in question; if none is active, that of the most recently `EXPIRED` window by `ends_on`, with ties broken by the latest `created_at`; if no window exists at all, 1.0.

### 3.8. Privacy Incidents and the Reporting SLA

Sensitive program data demands a disciplined incident lifecycle. A `SecurityOfficer` reports an **Incident** with the affected `contract_id`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, a `category` of `PRIVACY_BREACH`, `SECURITY`, or `DATA_QUALITY`, the `occurred_at` instant of the event — which may be earlier than the report — and a free-text `description`. The incident opens in `OPEN`, stamped with `reported_at` taken from the logical clock. Incidents are listable with `contract_id`, `severity`, and `status` filters, and a contract's incidents are reverse-reachable through its incidents collection.

The reporting SLA is a read-time derivation, never a gate. For a `CRITICAL` incident, the reporting delay is the whole-second difference between `reported_at` and `occurred_at` divided by 3600 to yield hours; when that delay is strictly greater than 24 hours, the incident reads back with `sla_breached` true. Late reporting never blocks creation — the incident is created regardless, and the breach flag is derived on every read rather than stored.

Incident handling is a `SecurityOfficer`'s chain of transitions: from `OPEN` to `CONTAINED`, from `CONTAINED` to `RESOLVED`, and from `RESOLVED` to `CLOSED`, which is terminal. Regression is anticipated: from `RESOLVED`, an incident may be reopened to `OPEN` — and when it is, the reporting-sla timestamps are deliberately not reset; `reported_at` is immutable for the life of the incident.

### 3.9. Invoice Preparation: Measurements, Gross Fee, and Staffing

Billing begins when a `BillingAnalyst` creates an **Invoice** shell with its `contract_id` and a `period` in `YYYY-MM` form. The period is unique per contract — a second invoice for the same contract and period is rejected with `ERR_INVOICE_PERIOD_DUPLICATE` (HTTP 409). The shell is born `DRAFT` with `withheld_cents` at 0, and `gross_cents` and `net_cents` unset until preparation. Invoices are listable with `contract_id`, `status`, and `period` filters.

Preparation — the capability that turns a shell into a measured bill — is available only while the invoice is `DRAFT`. It synthesizes one **InvoiceLine** per binding service level at the period end, one line per (program, metric) pair, each line recording its `invoice_id`, the `service_level_id` of the binding service level, and the `metric` copied from that service level. Each line then carries the four computed pillars: `measured_value`, `staffing_actual`, `staffing_target`, and `compliant`, plus the fiscal outcome `withheld_cents`. Lines of an invoice are reverse-reachable through the invoice's lines collection; lines bound to a service level are reverse-reachable through the service level's invoice-lines collection.

Each metric's `measured_value` is computed over the period window defined in §2.7. For `ASA`, the input set is the calls of the line's contract and program whose status is `ANSWERED` or `COMPLETED` and whose `enqueued_at` falls inside the window — abandoned calls never enter the set, and overflow-routed calls count toward the call's own program, not the overflow queue's program. The calls are processed in `enqueued_at` order with `created_at` ascending as the tie-break, the arithmetic mean of their `answer_seconds` is taken, and the result is rounded half-up to whole seconds. An empty set — a month with no answered calls — yields a `measured_value` of 0, which is compliant for `ASA`. For `ABANDON`, the input set is all calls of the contract and program enqueued in the window whose status is `ANSWERED`, `COMPLETED`, or `ABANDONED` — `WAITING` and `ASSIGNED` calls are excluded because they have not resolved — and the rate is the count of `ABANDONED` calls divided by the size of the input set, rounded half-up to 4 decimal places; an empty set yields 0.0000. For `QA_AVG`, the input set is the reviews with `final` true — status `ACCEPTED` or `UPHELD` — whose call belongs to the line's contract and program and whose call's `enqueued_at` falls inside the window; the arithmetic mean of their `total_score` values is rounded half-up to 2 decimal places. An empty quality set yields a null `measured_value`, and a null `measured_value` counts as non-compliant for `QA_AVG`.

Measurement comes in two variants. The first preparation of an invoice takes the **provisional** variant: the input set is taken at the preparation instant and stored on the line — for quality, only reviews already final at that instant count. Every recompute while the invoice is not yet `PAID` takes the **official** variant: the input set is re-taken at the recompute instant, so late-arriving completions shift the answer-speed mean, reviews that became final since preparation — a dispute resolved `UPHELD`, a late acceptance — enter the quality set, and the new value overwrites the line's `measured_value`.

The line's `staffing_actual` is the count of distinct `ACTIVE` agents holding a standing certification for the line's program at preparation time. The `staffing_target` is the baseline staffing of 10 multiplied by the surge multiplier for the program at period end — the selector of §3.7 — rounded up to the next integer. The surge multiplier affects the target only, never the actual.

Compliance is decided per line. For `ASA` and `ABANDON`, the line is compliant when `measured_value` is less than or equal to the service level's `target`; for `QA_AVG`, when `measured_value` is greater than or equal to the target — remembering that null counts as non-compliant. Overriding all three, a staffing shortfall — `staffing_actual` strictly less than `staffing_target` — forces the line to non-compliant regardless of the metric.

The invoice's `gross_cents` is the monthly fee before withholding, computed as follows. First, determine the program set: the distinct `program_code` values for which the contract has a service level that reached `EFFECTIVE` at any time on or before the period end — including ones since `SUPERSEDED` or `ARCHIVED`. For each program, count the agents with `employment_status` `ACTIVE` who hold at least one standing certification for the program at the period end — standing meaning `valid_until` strictly after the period end and `invalidated_at` null — and count, across those agents, the total number of standing certifications for the program. Each such certification contributes the fixed per-agent monthly rate of 4000 cents, scaled by the program's surge multiplier clamped so it never falls below 1.0. The program subtotals are computed at full precision, summed, and rounded half-up exactly once — never rounded per program — and the fixed monthly base fee of 50000 cents is added to produce `gross_cents`.

### 3.10. Withholding: Tiers, Per-Line Caps, and the Cumulative Cap

A compliant line always withholds 0. For a non-compliant line, the withheld amount is tiered by miss magnitude against the line's service-level target. The miss is metric-directed: for `ASA`, the measured seconds minus the target; for `ABANDON`, the measured fraction minus the target; for `QA_AVG`, the target minus the measured score — and when the measured value is null, the miss is the whole target. The miss ratio is the miss divided by the target, and the tier boundaries are asymmetric by design: a ratio strictly below 0.05 withholds 10 percent of gross; a ratio at least 0.05 and strictly below 0.15 withholds 25 percent; a ratio of 0.15 or greater withholds 40 percent. The raw withholding is the invoice's `gross_cents` multiplied by the tier rate, rounded half-up to cents.

Two caps then bind, in order. The per-line absolute cap always applies, in both cap modes: the line's withholding may not exceed the service level's `cap_pct_of_gross` times the invoice `gross_cents`, rounded half-up to cents. The cumulative cap applies only when the contract's `cap_absolutes` is false: invoices of the contract are processed in chronological period order — the `YYYY-MM` string order — and the sum of `withheld_cents` across all of them may never exceed the sum of their `gross_cents`. Concretely, each line's withholding is floored at the larger of 0 and the cumulative gross through this invoice's period minus the contract's `withheld_cents_cum` as it stood before this invoice — applied after the per-line cap. So under the floor regime, a first-month gross of 50000 caps month-1 withholding at 50000, however large the raw tier result; under the absolutes regime, the cumulative check is skipped entirely and a month-1 line may withhold more than month-1 gross. The invoice's `withheld_cents` is the sum of its lines' withholdings, and `net_cents` is `gross_cents` minus `withheld_cents`. Preparation also resyncs the contract's `withheld_cents_cum` to reflect the new lines.

### 3.11. Breaches, Cure Periods, and Buying Back a Miss

Every non-compliant line opens a breach. At preparation or recompute, the system creates a **CurePeriod** for each non-compliant line, stamped with the breaching line's id as its `invoice_line_id`: `status` `PENDING`, `opened_at` stamped from the logical clock at detection, a `deadline` exactly 72 hours after `opened_at`, and `remedy_fee_cents` copied from the line's service level at creation. The cure periods of a line are reverse-reachable through the line's cure-periods collection.

A `BillingAnalyst` may pay the remedy on a `PENDING` cure period, which moves it to `REMEDIED` and cures the breach: the line's `withheld_cents` is set to 0, the invoice's `withheld_cents` and `net_cents` are recomputed, the contract's `withheld_cents_cum` is decremented by the released amount, and the contract's `cure_periods_used` is incremented by 1. Payment is only possible inside the cure window — after the deadline, or on a cure period no longer `PENDING`, the attempt is rejected with `ERR_CURE_WINDOW_CLOSED` (HTTP 409).

A cure period that is still `PENDING` when the logical clock passes its `deadline` is automatically forfeited: it moves to `FORFEIT` on the next clock-set, the withholding stands, and the contract's `cure_periods_used` is incremented by 1. Both `REMEDIED` and `FORFEIT` are completed cure periods — both count in `cure_periods_used`, and that count is what drives auto-review on invoice preparation.

Recompute reconciles cures with reality. When an invoice is recomputed, existing `PENDING` cure periods whose line is now compliant are removed, and newly detected breaches open new `PENDING` cure periods; the contract's `withheld_cents_cum` is resynced to match. One exception stands: a remedy is permanent for the line it cured. A line with a `REMEDIED` cure period keeps its released zero withholding across recomputes — even if the recomputed measurement is still non-compliant — and recompute neither re-detects the breach nor opens a new cure period for that line.

### 3.12. Invoice Settlement: Submission, Approval, and the Revision Loop

An invoice moves to `SUBMITTED` when a `BillingAnalyst` requests `to_status` of `SUBMITTED`, provided at least one invoice line exists for it. Approval is an `OpsManager` act with two stacked gates. The optimistic-concurrency gate of §2.8 fires first: a request with `to_status` of `APPROVED` must carry `expected_contract_version` equal to the contract's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). The segregation-of-duties gate fires when the invoice's `auto_review` flag is true: the approving `X-User-ID` must differ from the user id of the `BillingAnalyst` recorded as preparer on the invoice, or the approval is rejected with `ERR_AUTO_REVIEW_REQUIRES_SECOND_APPROVER` (HTTP 409). The `auto_review` flag is set by preparation whenever it recomputed any line while a completed cure period — `REMEDIED` or `FORFEIT` — existed for that line's service level. A successful approval increments the parent Contract's `version` by 1. From `APPROVED`, the invoice is marked `PAID` by an `OpsManager` — `PAID` is terminal, and once paid an invoice is never recomputed again.

Rejection is the revision loop: an `OpsManager` may move a `SUBMITTED` invoice to `REJECTED`, and a `BillingAnalyst` may return a `REJECTED` invoice to `DRAFT`. The lines are not discarded on rejection or revision — the next recompute refreshes them against current measurements and caps, using the official variant of §3.9. Recompute is available on `DRAFT` invoices, including those revised back from `REJECTED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions, completions, preparations, recomputes, remedy payments, queue updates, and clock-sets — return `200 OK`. The table below is a summary only; request bodies, response payloads, side effects, and the exact conditions under which each operation succeeds or fails are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; fires time-based auto-transitions | PlatformAdmin |
| POST | `/contracts` | Create a contract in `DRAFT` | PlatformAdmin |
| GET | `/contracts` | List contracts, filterable by `status` | PlatformAdmin, OpsManager, BillingAnalyst, QualityAnalyst, Supervisor, KnowledgeManager, SecurityOfficer, Agent |
| GET | `/contracts/{id}` | Get one contract | PlatformAdmin, OpsManager, BillingAnalyst, QualityAnalyst, Supervisor, KnowledgeManager, SecurityOfficer, Agent |
| POST | `/contracts/{id}/transition` | Contract state transition; dispatch on `to_status` | OpsManager |
| GET | `/contracts/{id}/surge-windows` | Surge windows of a contract | PlatformAdmin, OpsManager, BillingAnalyst |
| GET | `/contracts/{id}/incidents` | Incidents of a contract | PlatformAdmin, OpsManager, SecurityOfficer |
| POST | `/service-levels` | Create a service level in `DRAFT` | OpsManager |
| GET | `/service-levels` | List service levels, filterable by `contract_id`, `program_code`, `metric`, `status` | PlatformAdmin, OpsManager, BillingAnalyst |
| GET | `/service-levels/{id}` | Get one service level | PlatformAdmin, OpsManager, BillingAnalyst |
| POST | `/service-levels/{id}/transition` | Service-level state transition; dispatch on `to_status`; `expected_contract_version` required when `to_status` is `EFFECTIVE` | OpsManager |
| GET | `/service-levels/{id}/invoice-lines` | Invoice lines bound to this service level | PlatformAdmin, OpsManager, BillingAnalyst |
| POST | `/agents` | Register an agent (`ACTIVE`) | OpsManager |
| GET | `/agents` | List agents, filterable by `employment_status` | PlatformAdmin, OpsManager, Supervisor, QualityAnalyst |
| GET | `/agents/{id}` | Get one agent | PlatformAdmin, OpsManager, Supervisor, QualityAnalyst |
| POST | `/agents/{id}/transition` | Agent state transition; dispatch on `to_status` | OpsManager |
| GET | `/agents/{id}/completions` | Course completions of this agent | PlatformAdmin, OpsManager, KnowledgeManager |
| POST | `/training-courses` | Create a training course for a program | KnowledgeManager |
| GET | `/training-courses/{id}` | Get one training course | PlatformAdmin, OpsManager, KnowledgeManager, Supervisor |
| POST | `/training-courses/{id}/complete` | Record an agent's completion; mints a certification; re-validates invalidated certifications | KnowledgeManager |
| GET | `/certifications` | List certifications, filterable by `agent_id`, `program_code`, `training_course_id`, `invalidated_by_article_id` | PlatformAdmin, OpsManager, KnowledgeManager, Supervisor |
| GET | `/certifications/{id}` | Get one certification | PlatformAdmin, OpsManager, KnowledgeManager, Supervisor |
| GET | `/course-completions` | List course completions, filterable by `training_course_id`, `agent_id` | PlatformAdmin, OpsManager, KnowledgeManager, Supervisor |
| GET | `/course-completions/{id}` | Get one course completion | PlatformAdmin, OpsManager, KnowledgeManager, Supervisor |
| POST | `/queues` | Create a queue in `OPEN` | OpsManager |
| GET | `/queues` | List queues, filterable by `contract_id`, `program_code`, `status`, `overflow_queue_id` | PlatformAdmin, OpsManager, Supervisor |
| GET | `/queues/{id}` | Get one queue | PlatformAdmin, OpsManager, Supervisor |
| PATCH | `/queues/{id}` | Update a queue's `overflow_queue_id` | OpsManager |
| POST | `/queues/{id}/transition` | Queue state transition; dispatch on `to_status` | OpsManager |
| GET | `/queues/{id}/calls` | Calls assigned to this queue, filterable by `status` | PlatformAdmin, OpsManager, Supervisor |
| POST | `/calls` | Register an inbound call in `WAITING` | Supervisor, OpsManager |
| GET | `/calls` | List calls, filterable by `contract_id`, `program_code`, `status`, `queue_id`, `agent_id`, `handled_by_agent_id` | PlatformAdmin, OpsManager, Supervisor, QualityAnalyst, BillingAnalyst |
| GET | `/calls/{id}` | Get one call | PlatformAdmin, OpsManager, Supervisor, QualityAnalyst, BillingAnalyst, Agent |
| POST | `/calls/{id}/transition` | Call state transition; dispatch on `to_status` | Supervisor, Agent |
| POST | `/quality-reviews` | Score a `COMPLETED` call | QualityAnalyst |
| GET | `/quality-reviews` | List reviews, filterable by `call_id`, `status` | PlatformAdmin, OpsManager, QualityAnalyst, Supervisor |
| GET | `/quality-reviews/{id}` | Get one quality review | PlatformAdmin, OpsManager, QualityAnalyst, Supervisor, Agent |
| POST | `/quality-reviews/{id}/transition` | Review state transition; dispatch on `to_status` | QualityAnalyst, Agent |
| POST | `/coaching-plans` | Open a `MANUAL` coaching plan | Supervisor |
| GET | `/coaching-plans` | List coaching plans, filterable by `agent_id`, `status`, `trigger` | PlatformAdmin, OpsManager, Supervisor, QualityAnalyst |
| GET | `/coaching-plans/{id}` | Get one coaching plan | PlatformAdmin, OpsManager, Supervisor, QualityAnalyst |
| POST | `/coaching-plans/{id}/transition` | Coaching-plan state transition; dispatch on `to_status` | Supervisor |
| POST | `/knowledge-articles` | Create an article in `DRAFT` | KnowledgeManager |
| GET | `/knowledge-articles` | List articles, filterable by `program_code`, `status` | PlatformAdmin, OpsManager, KnowledgeManager, Supervisor, Agent |
| GET | `/knowledge-articles/{id}` | Get one article | PlatformAdmin, OpsManager, KnowledgeManager, Supervisor, Agent |
| POST | `/knowledge-articles/{id}/transition` | Article state transition; dispatch on `to_status` | KnowledgeManager |
| GET | `/knowledge-articles/{id}/training-courses` | Courses linked to this article | PlatformAdmin, OpsManager, KnowledgeManager |
| POST | `/surge-windows` | Declare a surge window | OpsManager |
| GET | `/surge-windows` | List surge windows, filterable by `contract_id`, `program_code`, `status` | PlatformAdmin, OpsManager, Supervisor, BillingAnalyst |
| GET | `/surge-windows/{id}` | Get one surge window | PlatformAdmin, OpsManager, Supervisor, BillingAnalyst |
| POST | `/surge-windows/{id}/transition` | Surge-window state transition; dispatch on `to_status` | OpsManager |
| POST | `/incidents` | Report an incident in `OPEN` | SecurityOfficer |
| GET | `/incidents` | List incidents, filterable by `contract_id`, `severity`, `status` | PlatformAdmin, OpsManager, SecurityOfficer |
| GET | `/incidents/{id}` | Get one incident (includes the derived `sla_breached` field) | PlatformAdmin, OpsManager, SecurityOfficer |
| POST | `/incidents/{id}/transition` | Incident state transition; dispatch on `to_status` | SecurityOfficer |
| POST | `/invoices` | Create an invoice shell in `DRAFT` for a contract and period | BillingAnalyst |
| GET | `/invoices` | List invoices, filterable by `contract_id`, `status`, `period` | PlatformAdmin, OpsManager, BillingAnalyst |
| GET | `/invoices/{id}` | Get one invoice | PlatformAdmin, OpsManager, BillingAnalyst |
| POST | `/invoices/{id}/transition` | Invoice state transition; dispatch on `to_status`; `expected_contract_version` required when `to_status` is `APPROVED` | BillingAnalyst, OpsManager |
| POST | `/invoices/{id}/prepare` | Synthesize invoice lines and compute gross, measurements, staffing, and withholding | BillingAnalyst |
| POST | `/invoices/{id}/recompute` | Recompute all lines with the official variant; reconcile cure periods | BillingAnalyst |
| GET | `/invoices/{id}/lines` | Invoice lines of an invoice | PlatformAdmin, OpsManager, BillingAnalyst |
| GET | `/invoice-lines/{id}` | Get one invoice line | PlatformAdmin, OpsManager, BillingAnalyst |
| GET | `/invoice-lines/{id}/cure-periods` | Cure periods of an invoice line | PlatformAdmin, OpsManager, BillingAnalyst |
| POST | `/cure-periods/{id}/pay-remedy` | Pay the remedy on a `PENDING` cure period | BillingAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table lists only identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_LEVEL_NOT_FOUND` | 404 Not Found |
| `ERR_AGENT_NOT_FOUND` | 404 Not Found |
| `ERR_QUEUE_NOT_FOUND` | 404 Not Found |
| `ERR_CALL_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_COACHING_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_ARTICLE_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_COURSE_NOT_FOUND` | 404 Not Found |
| `ERR_SURGE_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SL_CONFLICT` | 409 Conflict |
| `ERR_QUEUE_OVERFLOW_MISMATCH` | 409 Conflict |
| `ERR_OVERFLOW_LOCKED` | 409 Conflict |
| `ERR_QUEUE_NOT_EMPTY` | 409 Conflict |
| `ERR_CALL_OVERFLOW_FORBIDDEN` | 409 Conflict |
| `ERR_NO_ELIGIBLE_QUEUE` | 409 Conflict |
| `ERR_AGENT_HAS_LIVE_CALLS` | 409 Conflict |
| `ERR_DUPLICATE_PLAN` | 409 Conflict |
| `ERR_INVOICE_PERIOD_DUPLICATE` | 409 Conflict |
| `ERR_SURGE_OVERLAP` | 409 Conflict |
| `ERR_CURE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_AUTO_REVIEW_REQUIRES_SECOND_APPROVER` | 409 Conflict |
