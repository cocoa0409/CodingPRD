# Injection Molding Job Shop API — Product Requirements Document

## 1. Introduction

A custom injection molding job shop lives or dies on two ledgers that are almost never reconciled by hand: the ledger of **press minutes** — who owns which machine, for which window, at what burden rate — and the ledger of **material and shots** — how much virgin resin left which lot, how many cavities filled, how many parts survived the gate. Between those two ledgers sits a third concern that the shop's customers care about more than either: whether the tool running their part has cleared first-article inspection and a Production Part Approval Process package, and whether the regrind ratio the press operator dialed in is one the customer actually signed off on. Today those three concerns live in a scheduling whiteboard, a spreadsheet of resin certificates, and a folder of scanned PPAP binders, and the shop discovers the contradictions between them only when a shipment is rejected.

This document specifies the API for a system that holds all three in one place. The system tracks tool ownership and the tonnage band each mold may run in, routes jobs onto presses that are both physically adequate and formally qualified through a run-at-rate trial, prices quotes from cavitation and cycle time against a resin cost roll, enforces first-article and PPAP gates before a tool may take production work, meters resin lots and regrind against approved ceilings, accumulates the shot counter that drives preventive maintenance, adjudicates customer-owned tool transfers, and settles the capacity blocks the sales organization sells against what the shop floor actually consumed.

The design principle running through every requirement below is that **no derived number is ever entered by hand**. Shot counts, yield, mass balance, cost rolls, utilization and shortfall fees are all recomputed from the underlying shift reports every time one is posted or reversed, and every accumulator is defined so that reversing a report returns the system to exactly the state it was in before that report — with no rounding drift, because every quantity in the system is an integer: money in cents, mass in grams, time in whole minutes, and every ratio in basis points.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting in. If either header is absent, or if `X-User-Role` does not name one of the six roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other rule in the system is consulted. Once the headers are accepted, the acting role must appear in the authorized-role list for the endpoint being called; if it does not, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Exactly six roles exist:

- **`PlantAdmin`** — plant operations administrator. Masters customers, presses and tools; adjudicates and completes tool transfers; settles and cancels capacity commitments; drives the logical clock. Shares mold quality-hold, qualification creation, resin receipt, job cancellation, report reversal, maintenance orders, transfer requests, capacity-commit creation and PPAP internal review with the roles that own them, and may read every collection.
- **`SalesEngineer`** — owns the commercial surface. Drafts and prices quotes, sends them to the customer, and sells blocks of press capacity. A `SalesEngineer` may never render the customer's own decision on a quote.
- **`ProcessEngineer`** — owns the manufacturing surface. Opens qualification rows and books run-at-rate trials, opens and schedules jobs, stages material, starts and completes jobs, unblocks them, and posts shift reports. A `ProcessEngineer` may never render a quality verdict.
- **`QualityEngineer`** — owns every quality verdict. Resin lot disposition, mold quarantine and release, PPAP filing, internal endorsement, run-at-rate verdicts and shift-report reversal all belong to this role.
- **`ToolroomTech`** — runs the toolroom. Opens and closes maintenance orders, which is the only mechanism in the system that ever resets the preventive-maintenance shot counter.
- **`CustomerRep`** — acts on behalf of exactly one buying customer. Accepts or declines quotes, renders the customer decision on a PPAP package, and requests tool transfers.

Role identity binds to `X-User-ID` in two different ways, and the distinction matters for every ownership check in the system. When `X-User-Role` is `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `QualityEngineer` or `ToolroomTech`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it on the resources where the workflow calls for an audit stamp — as `submitted_by_user_id` and `internal_reviewed_by_user_id` on a PPAP package, for example — but never compares it to any entity's `id`. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; every ownership check on a resource that references a customer compares that resource's customer foreign key to `X-User-ID`. Concretely, a `CustomerRep` deciding a quote must match the quote's `customer_id`, a `CustomerRep` rendering a PPAP customer decision must match the `customer_id` of the mold the package qualifies, a `CustomerRep` requesting a tool transfer must match the `to_customer_id` named in the request, and a `CustomerRep` reading a customer record must match that record's `id`. Any mismatch is rejected with `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403).

One further identity rule is specific to quality governance. The `X-User-ID` that filed a PPAP package may not be the `X-User-ID` that endorses or rejects it at internal review; an attempt to do so is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This is the system's only segregation-of-duties rule, and it is deliberately enforced on the person, not the role — two different `QualityEngineer` principals are exactly what the rule is asking for.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1 and no larger than 100. The `offset` parameter defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of records matching the filters before pagination is applied and `has_more` is true when records remain beyond the current page.

Beyond pagination, every list endpoint accepts optional filters that make the system's foreign keys reverse-navigable, since no resource is nested inside another in the URL space. Presses may be filtered by `status` and by `min_tonnage`, which selects presses whose `tonnage` is at least the supplied value. Molds may be filtered by `customer_id`, `status`, `service_state` and `ownership`. Qualification rows may be filtered by `mold_id`, `press_id` and `status`. Quotes may be filtered by `customer_id`, `mold_id`, `rate_press_id` and `status`. PPAP packages may be filtered by `mold_id`, `quote_id`, `supersedes_submission_id` — which walks the revision chain — and `status`. Jobs may be filtered by `quote_id`, `mold_id`, `press_id`, `staged_resin_lot_id`, `run_status` and `material_status`. Shift reports may be filtered by `job_id`, `resin_lot_id` and `is_reversed`. Maintenance orders may be filtered by `mold_id` and `status`. Tool transfers may be filtered by `mold_id`, `to_customer_id` and `status`. Capacity commitments may be filtered by `customer_id`, `press_id` and `status`.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource in the system carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Every resource in this system additionally carries an `updated_at` timestamp in the same format and an integer `version`; there is no entity here that omits them. The `version` of a resource starts at 1 when the resource is created and is incremented by exactly 1 on every mutation of that resource, and `updated_at` is refreshed to the current logical time on the same mutation. A read never changes either.

Timestamps come from a **logical clock**, not from wall-clock time. Before any caller moves it, the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A `PlantAdmin` may advance or rewind it by supplying a `to_iso8601` instant to the administrative clock endpoint mounted at `/_clock/set_current_utc`, which answers with the new `current_utc`. Every subsequent `created_at` and `updated_at` stamp, and every window comparison performed anywhere in the system, uses the logical now.

All scheduling windows — a job's `scheduled_start` and `scheduled_end`, a maintenance order's `window_start` and `window_end`, a capacity commitment's `window_start` and `window_end`, and a run-at-rate trial's `scheduled_start` and `scheduled_end` — are ISO 8601 UTC instants aligned to whole minutes. A window whose start is not strictly before its end, or whose endpoints are not whole-minute UTC instants, is rejected with `ERR_INVALID_WINDOW` (HTTP 400).

Because the topology is flat, every resource is its own top-level collection and children carry their parent references in the request body rather than in the URL. Where an endpoint does carry path parameters, they are resolved strictly left to right, and the first segment that names a resource which does not exist determines the error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESS_NOT_FOUND`, `ERR_MOLD_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_PPAP_SUBMISSION_NOT_FOUND`, `ERR_RESIN_LOT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_MAINTENANCE_ORDER_NOT_FOUND`, `ERR_TOOL_TRANSFER_NOT_FOUND` or `ERR_CAPACITY_COMMIT_NOT_FOUND`, each with HTTP 404. The same catalogue answers a foreign key carried in a request body that does not resolve, and body-carried foreign keys are checked in the order in which the endpoint's input fields are listed.

### 2.5. Stale-View Rejection on Shared Parents

Seven write operations in this system mutate a resource whose correctness depends on a *second* resource the caller has read but does not itself address — a press whose minute ledger the caller is about to change, a job whose accumulators the caller is about to move, a tool whose approval terms the caller is about to rewrite. For those seven, the caller must echo back the `version` of that shared parent as it stood when the caller last read it, and the server rejects the write when the echoed value does not equal the parent's current `version`. This is optimistic concurrency control on the parent, and it exists precisely because the losing request in these cases is otherwise perfectly legal: a second job on the same press, a second report on the same running job, a second decision on a different quote for the same mold would each succeed on their own merits, so no state precondition catches them. Only the stale parent version identifies the caller's view as out of date.

The seven rules are:

- Scheduling a production job requires `expected_press_version` matching the target press's current `version`. A mismatch is rejected with `ERR_STALE_PRESS_VERSION` (HTTP 412).
- Unblocking a production job, which re-reserves the press minutes the job released when it was blocked, likewise requires `expected_press_version` matching the press's current `version`, and a mismatch is rejected with `ERR_STALE_PRESS_VERSION` (HTTP 412).
- Posting a shift report requires `expected_job_version` matching the target job's current `version`. A mismatch is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412).
- Rendering the customer's decision on a quote requires `expected_mold_version` matching the current `version` of the mold the quote is priced against. A mismatch is rejected with `ERR_STALE_MOLD_VERSION` (HTTP 412).
- Rendering the customer's decision on a PPAP package requires `expected_mold_version` matching the mold's current `version`. A mismatch is rejected with `ERR_STALE_MOLD_VERSION` (HTTP 412).
- Closing a maintenance order, which may zero the mold's PM shot counter, requires `expected_mold_version` matching the mold's current `version`. A mismatch is rejected with `ERR_STALE_MOLD_VERSION` (HTTP 412).
- Completing a tool transfer, which rewrites the mold's ownership and customer, requires `expected_mold_version` matching the mold's current `version`. A mismatch is rejected with `ERR_STALE_MOLD_VERSION` (HTTP 412).

These seven inputs are mandatory on their respective operations — they are not optional hints. No other endpoint in the system accepts a version field of any kind, and supplying one elsewhere is meaningless.

### 2.6. Integer Arithmetic, Basis Points and Rounding

Nothing in this system is stored as a floating-point number. Money is integer **cents**. Mass is integer **grams**, except where a resin lot is received, which is recorded in whole **kilograms** and converted to grams by multiplying by 1,000. Durations are whole **minutes**, except molding cycle times, which are whole **seconds**. Every ratio — yield, regrind, margin, overhead, utilization, run-at-rate achievement — is expressed in **basis points**, where 10,000 basis points is 100 percent and 1 basis point is one hundredth of one percent.

Three rounding behaviours appear, and each calculation below names which one it uses at which step:

- **Round half up** on a quotient of non-negative integers: the exact quotient is rounded to the nearest whole number, and a value exactly halfway between two whole numbers rounds upward.
- **Round up** (ceiling): the exact quotient is raised to the next whole number unless it is already whole.
- **Round down** (floor): the exact quotient is lowered to the preceding whole number unless it is already whole.

Where a formula rounds more than once, the order of rounding is part of the specification and is stated explicitly. Two rules recur and are worth stating once here: a per-line cost is rounded at the line and the already-rounded lines are then summed, never the reverse; and a tiered rate is always selected from the value *before* the tier's own contribution is added, so no tier selection is ever circular.

Wherever a ranking or a tie-break is needed — selecting a press, ordering maintenance history — the final tie-break is `created_at` ascending. No selector, ordering or tie-break rule anywhere in this system reads `id`.

### 2.7. Order of Request Screening

Requests are screened in a fixed order, and the **first** check that fails determines the response. This ordering is normative: a request that would fail two different checks always reports the earlier one. The ladder runs as follows.

1. **Authentication.** Headers present and the role recognized, or `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** The acting role is listed for the endpoint, or `ERR_FORBIDDEN_ROLE` (403).
3. **Path existence.** Every resource named by a path segment exists, checked left to right, or the matching not-found error (404).
4. **Request shape.** Every required body field is present, every type is correct, every enum member is recognized, every integer sits inside its declared range, and pagination parameters are in range — otherwise `ERR_INVALID_REQUEST` (400).
5. **Window validity.** Supplied windows have start strictly before end and whole-minute UTC endpoints, or `ERR_INVALID_WINDOW` (400). This applies to job creation, maintenance order creation, capacity commitment creation and run-at-rate scheduling.
6. **Body foreign keys.** Every `*_id` carried in the body resolves, in the order the endpoint lists its inputs, or the matching not-found error (404).
7. **Customer scope.** A `CustomerRep` is acting only on its own customer's resources, or `ERR_CUSTOMER_SCOPE_VIOLATION` (403). This applies to the quote customer decision, the PPAP customer decision, tool transfer requests, and reading a single customer record.
8. **Parent version freshness.** The supplied `expected_press_version`, `expected_job_version` or `expected_mold_version` equals the parent's current `version`, or the matching stale-version error (412), as set out in §2.5.
9. **Transition legality.** The target resource is in a state from which the requested transition is declared, or a 409 state error — the specific one where the system defines it, and `ERR_INVALID_STATE` otherwise.
10. **Segregation of duties.** The PPAP internal reviewer differs from the submitter, or `ERR_SEGREGATION_OF_DUTIES` (403).
11. **Mold lifecycle gate.** The mold is in the lifecycle status the operation requires, or one of `ERR_MOLD_QUARANTINED`, `ERR_MOLD_RETIRED`, `ERR_MOLD_TRANSFERRED` or `ERR_MOLD_NOT_PPAP_APPROVED` (409).
12. **Material and first-article gates.** Resin release status, resin grade match, first-article verdict and incoming moisture, answered with `ERR_RESIN_LOT_NOT_RELEASED`, `ERR_RESIN_GRADE_MISMATCH`, `ERR_FAI_NOT_PASSED` or `ERR_RESIN_MOISTURE_TOO_HIGH` (422).
13. **Tool service gate.** The mold's `service_state` is `SERVICEABLE`, or `ERR_PM_OVERDUE` (409).
14. **Transfer interlock.** No transfer is in flight on the mold, and no job on the mold is running when a transfer completes, or `ERR_MOLD_TRANSFER_IN_PROGRESS` (409).
15. **Press routing eligibility.** The press is online, within the tonnage band, large enough in shot size, and qualified for the tool — or `ERR_PRESS_OFFLINE`, `ERR_PRESS_TONNAGE_MISMATCH`, `ERR_PRESS_SHOT_SIZE_EXCEEDED`, `ERR_PRESS_NOT_QUALIFIED` or `ERR_NO_ELIGIBLE_PRESS` (the first at 409, the rest at 422).
16. **Press window overlap.** `ERR_PRESS_WINDOW_CONFLICT` (409).
17. **Mold window overlap.** `ERR_MOLD_WINDOW_CONFLICT` (409).
18. **Parts conservation on a shift report.** `ERR_PARTS_BALANCE_MISMATCH` (422).
19. **Regrind ratio control on a shift report.** `ERR_REGRIND_RATIO_EXCEEDED` (422).
20. **Resin sufficiency on a shift report.** `ERR_RESIN_LOT_INSUFFICIENT` (422).
21. **Press daily capacity.** `ERR_PRESS_DAILY_CAPACITY_EXCEEDED` (422).
22. **Capacity commitment availability.** `ERR_CAPACITY_COMMIT_EXCEEDED` (422).
23. **Uniqueness.** `ERR_DUPLICATE_CODE`, `ERR_DUPLICATE_QUALIFICATION`, `ERR_MAINTENANCE_ALREADY_OPEN` or `ERR_MOLD_TRANSFER_IN_PROGRESS` (409).
24. **Credit standing.** The customer is not on credit hold, or `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402). This applies to accepting a quote and to opening a capacity commitment.

Two consequences of this ordering are worth calling out because they are easy to get backwards. A shift report that both violates parts conservation and exceeds the regrind ceiling reports the parts imbalance, because conservation is checked first. And a job scheduling request against a quarantined mold on an offline press reports the mold quarantine, because the lifecycle gate precedes routing eligibility.

### 2.8. Parallel State Axes and Cascade Discipline

Two entities in this system carry **two independent state axes** that advance separately and must never be conflated.

A production job carries `run_status`, whose values are `DRAFT`, `SCHEDULED`, `BLOCKED`, `RUNNING`, `COMPLETED` and `CANCELLED`, and `material_status`, whose values are `UNSTAGED`, `STAGED` and `CONSUMED`. Staging resin moves the material axis without touching the run axis; scheduling and starting move the run axis without touching the material axis. `COMPLETED` and `CANCELLED` are terminal on the run axis; `CONSUMED` is terminal on the material axis.

A mold carries `status`, whose values are `NEW`, `SAMPLING`, `PPAP_APPROVED`, `INTERIM_APPROVED`, `QUARANTINED`, `TRANSFERRED` and `RETIRED`, and `service_state`, whose values are `SERVICEABLE`, `PM_DUE` and `IN_MAINTENANCE`. The first axis records the tool's approval history with the customer; the second records whether the toolroom will let it run. `TRANSFERRED` and `RETIRED` are terminal on the lifecycle axis; the maintenance axis has no terminal state and cycles indefinitely.

Cascades in this system are **chained, not flat**: a side effect that moves a second entity then fires that second entity's own documented side effects, and so on. Three chains exist and each is spelled out where it originates in §3. Completing a tool transfer rewrites the mold and drives it to `TRANSFERRED`; the mold's arrival at `TRANSFERRED` revokes every qualified mold/press pairing; and each revocation cancels that pairing's unfinished jobs — three links deep. A mold reaching `PM_DUE` or `QUARANTINED` blocks that mold's scheduled jobs; and each job's arrival at `BLOCKED` then de-stages its material and releases its press minutes — two links deep. Every entity touched anywhere along a chain has its `updated_at` refreshed and its `version` incremented by 1, exactly as if it had been written directly.

### 2.9. Press and Tool Occupancy

Two different interval semantics govern occupancy in this shop, and confusing them is the single most common way a schedule goes wrong.

**Press windows are half-open and carry a changeover allowance.** A press cannot go from one tool to the next instantaneously; a mandatory changeover buffer of **45 minutes** must separate two occupancies of the same machine, and the buffer is applied to the *gap* between them. A candidate job collides with an existing job on the same press unless either the candidate starts at least 45 minutes after the existing job ends, or the candidate ends at least 45 minutes before the existing job starts. A candidate starting exactly 45 minutes after an existing job ends is accepted; one minute earlier collides. The existing set consists of the other jobs on the same press whose `run_status` is `SCHEDULED` or `RUNNING` — jobs that are `DRAFT`, `BLOCKED`, `COMPLETED` or `CANCELLED` free the window entirely. A collision is rejected with `ERR_PRESS_WINDOW_CONFLICT`.

**Mold windows are closed and carry no allowance at all.** A tool is physically in exactly one place at a time, so two occupancies that merely touch at an endpoint do collide, and the buffer between mold occupancies is zero minutes. A candidate window collides with an existing one when the candidate's start is at or before the existing window's end *and* the existing window's start is at or before the candidate's end. The existing set for a tool spans both open maintenance orders on that mold and jobs on that mold whose `run_status` is `SCHEDULED` or `RUNNING`, regardless of which press those jobs occupy; a job's `scheduled_start` and `scheduled_end` are read as its window endpoints for this purpose. A collision is rejected with `ERR_MOLD_WINDOW_CONFLICT`.

Alongside the collision rules, each press carries a **minute ledger**, `committed_minutes_scheduled`, defined as the sum of the whole-minute durations of every job on that press whose `run_status` is `SCHEDULED` or `RUNNING`. Every forward reservation increases it and every compensating release decreases it, so the ledger is an exact identity at rest rather than an approximation. A job's duration for ledger purposes is the number of whole minutes from its `scheduled_start` to its `scheduled_end`.

Finally, a press may not be booked past **1,224 minutes — twenty hours and twenty-four minutes — of committed time on any single UTC calendar day**. The day is the UTC calendar date of the candidate job's `scheduled_start`; the running total is the summed duration of every job on that press whose `run_status` is `SCHEDULED` or `RUNNING` and whose own `scheduled_start` falls on that same UTC date; and if that total plus the candidate's duration exceeds 1,224 minutes, the request is rejected with `ERR_PRESS_DAILY_CAPACITY_EXCEEDED`. The daily gate is evaluated when a job is scheduled and when a blocked job is returned to the schedule, and at no other time.

### 2.10. Reversibility of the Shop Floor Ledgers

Shift reporting is the only place in this system where a mistake can propagate into four separate ledgers at once — parts, resin mass, shot counters and cost — and it is therefore the only place with an explicit compensating action. A posted shift report is never deleted or edited; it is **reversed**, which sets `is_reversed` to true and records the supplied `reversal_reason`. Every accumulator in the system is defined as a function of the *non-reversed* reports that feed it, so a reversal is applied simply by recomputing those accumulators from the remaining reports. Because every quantity involved is an integer, the recomputation restores the exact prior values with zero drift; there is no compensating-entry arithmetic and no residue. A report that has already been reversed cannot be reversed again, and a second attempt is rejected with `ERR_REPORT_ALREADY_REVERSED`.

## 3. Business Logic & Workflows

### 3.1. Master Records: Customers, Machines and Tools

Everything in the shop hangs off three master records that only a `PlantAdmin` may create. A **customer** is registered with a legal `name` and a short `code` that must be between 2 and 16 characters and unique across all customers; an optional `credit_hold` flag may be supplied at registration and defaults to false when it is omitted. A customer on credit hold is not blocked from being quoted — the sales conversation continues — but is blocked at the two moments where money is committed, as §3.3 and §3.9 describe.

A **press** is registered with a `press_code` unique across all machines, a clamp `tonnage` of at least 1, a `shot_size_grams_max` of at least 1 giving the largest shot mass the barrel can deliver in grams, and an `hourly_rate_cents` of at least 1 that is the machine burden rate every cost roll in the system reads. A newly registered press begins with `status` `AVAILABLE` and `committed_minutes_scheduled` at 0. The two values `status` may hold are `AVAILABLE` and `OFFLINE`, and a `PlantAdmin` moves a machine between them by supplying the new `status` together with an optional `note`. Taking a machine `OFFLINE` removes it from the candidate set of both press selectors described in §3.3 and §3.6; it does not disturb work already booked on it.

A **mold** — the tool itself — is registered with a `mold_code` unique across all tools, the `customer_id` of the customer whose part program it runs, a `cavity_count` of at least 1 giving the parts produced per shot, a `shot_weight_grams` of at least 1 covering the total shot mass including the runner, a tonnage band expressed as `required_min_tonnage` and `required_max_tonnage` where the maximum must be at least the minimum and both are at least 1, a `pm_interval_shots` of at least 1 giving the shots between preventive maintenance events, and a `tooling_cost_cents` of at least 0 that is the capitalised tool cost. An `ownership` value of `SHOP_OWNED` or `CUSTOMER_OWNED` may be supplied and defaults to `SHOP_OWNED`. A new tool starts with `status` `NEW`, `service_state` `SERVICEABLE`, `total_shot_count` and `shots_since_pm` both at 0, and `approved_max_regrind_bp`, `interim_expiry_shots` and `active_transfer_id` all unset. Any of the four unique codes in the system — a customer's `code`, a press's `press_code`, a mold's `mold_code` or a resin lot's `supplier_lot_code` — colliding with an existing record is rejected with `ERR_DUPLICATE_CODE`.

Retiring a tool is permanent and is reserved to a `PlantAdmin`, who may supply an optional `reason`. A tool may be retired from `NEW` or from `PPAP_APPROVED`, and in both cases retirement is refused while any job on that tool is `SCHEDULED`, `BLOCKED` or `RUNNING`. Retirement drives the lifecycle axis to `RETIRED` and, in both cases equally, revokes every qualification row on that tool whose status is `QUALIFIED` — a tool scrapped before it ever sampled carries its qualifications down with it exactly as an approved one does — and each such revocation then fires its own job-cancellation cascade as described in §3.2. Once a tool is `RETIRED` or `TRANSFERRED`, operations targeting it are rejected with `ERR_MOLD_RETIRED` or `ERR_MOLD_TRANSFERRED` respectively.

### 3.2. Qualifying a Tool to a Press

Pricing a quote and running production ask two different questions about a machine. Pricing asks only whether a press is physically adequate; production additionally asks whether the shop has *proved* that this tool runs at rate on that specific machine. The proof is a **qualification row**, a junction record opened by a `ProcessEngineer` or a `PlantAdmin` that names a `mold_id` and a `press_id` and begins life with `status` `UNQUALIFIED` and `attempt_count` at 0. At most one qualification row may exist per tool-and-machine pair; a second attempt on the same pair is rejected with `ERR_DUPLICATE_QUALIFICATION`.

A `ProcessEngineer` books the trial by supplying `scheduled_start`, `scheduled_end` and a `target_parts_per_hour` — the contracted rate the trial must hit. Booking is accepted out of `UNQUALIFIED`, out of `FAILED` and out of `REVOKED`, and in all three cases moves the row to `RUN_AT_RATE_SCHEDULED`, requires that the press's `status` is `AVAILABLE`, and requires that the supplied window's start is strictly before its end. Booking out of `UNQUALIFIED` and out of `REVOKED` additionally requires that the tool's lifecycle status is neither `TRANSFERRED` nor `RETIRED`. Rebooking after a failure clears the previously recorded `actual_parts_per_hour` back to unset before storing the new window and target, so a failed row never carries a stale observation into its next trial.

A `QualityEngineer` settles the trial by supplying the observed `actual_parts_per_hour`. The achievement is computed as the observed rate multiplied by 10,000, divided by the contracted `target_parts_per_hour`, and rounded down to a whole number of basis points. If that achievement is at least 9,000 basis points — ninety percent of contract, with an exact ninety percent qualifying — the row moves `RUN_AT_RATE_SCHEDULED → QUALIFIED`; below it, the row moves `RUN_AT_RATE_SCHEDULED → FAILED`. Either verdict stores the observed rate and increments `attempt_count` by 1, and the verdict reads only the trial just recorded — earlier attempts do not average in. Recording a rate against a row that is not in `RUN_AT_RATE_SCHEDULED` is rejected with `ERR_RUN_AT_RATE_NOT_SCHEDULED`.

Qualification is withdrawn, never re-earned automatically. When a tool's lifecycle status reaches `TRANSFERRED` or `RETIRED`, every qualification row on that tool whose status is `QUALIFIED` moves `QUALIFIED → REVOKED`. Each revocation is itself a cascade origin: every job that names both that tool and that machine and whose `run_status` is `DRAFT`, `SCHEDULED` or `BLOCKED` is driven to `CANCELLED` with its `block_reason` set to `QUALIFICATION_REVOKED`. A revoked row is not dead — a `ProcessEngineer` may book a fresh trial on it, provided the tool is once again neither `TRANSFERRED` nor `RETIRED` and the press is `AVAILABLE` — but until a new trial qualifies it, that machine is no longer a routing candidate for that tool.

### 3.3. Quoting: Pricing the Lot and Winning the Order

A `SalesEngineer` drafts a quote against an existing tool by supplying the `customer_id` being quoted, the `mold_id` the price is built on, a `part_weight_grams` of at least 1 giving the finished mass of a single part, a nominal `cycle_time_sec` of at least 1 in whole seconds, a `cavitation` of at least 1 naming how many cavities this quote actually runs, a `resin_grade` string naming the material specification, a `resin_price_cents_per_kg` of at least 1 giving the contracted resin price, and an `annual_volume` of at least 1. Cavitation may be lower than the tool's `cavity_count` when cavities are blocked off, but it may never exceed it. A new quote's `status` is `DRAFT` and no price exists yet.

Pricing is a separate, deliberate act. The `SalesEngineer` may pin the rate machine by supplying a `press_id`, or may omit it and let the system pick. Pricing is refused outright when the tool's lifecycle status is `TRANSFERRED` or `RETIRED`, and when the quote's `cavitation` exceeds the tool's `cavity_count`. If a machine is pinned, that machine must exist, must have `status` `AVAILABLE` — otherwise `ERR_PRESS_OFFLINE` — must have a `tonnage` that sits at or above the tool's `required_min_tonnage` and at or below its `required_max_tonnage`, otherwise `ERR_PRESS_TONNAGE_MISMATCH`, and must have a `shot_size_grams_max` at least as large as the tool's `shot_weight_grams`, otherwise `ERR_PRESS_SHOT_SIZE_EXCEEDED`.

When no machine is pinned, a **rate-press selector** runs. Its candidate set is every press in the shop whose `status` is `AVAILABLE`, whose `tonnage` is at or above the tool's `required_min_tonnage` and at or below its `required_max_tonnage`, and whose `shot_size_grams_max` is at or above the tool's `shot_weight_grams`. Note carefully what is *not* in that filter: a qualification row is deliberately **not** required here, because quoting prices the cheapest adequate machine long before any run-at-rate trial exists. The candidates are ordered by `tonnage` ascending, then by `hourly_rate_cents` ascending, then by `created_at` ascending, and the first is taken. If the candidate set is empty the pricing request is rejected with `ERR_NO_ELIGIBLE_PRESS`. Whichever way the machine is determined, its id is recorded on the quote as `rate_press_id`, and the quote moves `DRAFT → PRICED`.

The price itself is built from a fixed **lot of 1,000 parts**, and every step is integer arithmetic in cents:

1. **Shots per lot** is 1,000 divided by the quote's `cavitation`, rounded up to a whole shot.
2. **Machine seconds** is that shot count multiplied by the cycle time in seconds.
3. **Machine cost** in cents is the machine seconds multiplied by the rate press's `hourly_rate_cents`, divided by 3,600 seconds in an hour, rounded half up.
4. **Gross resin grams** is 1,000 multiplied by `part_weight_grams`, multiplied by 10,000, divided by the yield in basis points, rounded up — the division by yield is what grosses the buy up to cover the parts that will not survive.
5. **Resin cost** in cents is the gross resin grams multiplied by `resin_price_cents_per_kg`, divided by the 1,000 grams in a kilogram, rounded half up.
6. **Tooling amortisation** is `tooling_cost_cents` divided by 50 lots, rounded up, when the tool's `ownership` is `SHOP_OWNED`; when the tool is `CUSTOMER_OWNED` it is exactly zero, because the customer has already paid for the tool.
7. **Packaging** is a flat 1,800 cents per lot.
8. **Direct lot cost** is the sum of those four components — machine, resin, tooling and packaging — each of which was already rounded to whole cents in its own step. The rounding happens per component and only then are the components summed.
9. **Margin** is selected from `annual_volume` and stored on the quote as `margin_bp`: an annual volume below 50,000 parts takes 2,800 basis points, an annual volume from 50,000 up to but not including 250,000 parts takes 2,200 basis points, and an annual volume of 250,000 parts or more takes 1,600 basis points.
10. **Lot price** is the direct lot cost multiplied by 10,000 plus the margin basis points, divided by 10,000, rounded half up. The margin is applied exactly once, to the already-rounded subtotal.
11. **Piece price** is the larger of 12 cents and the lot price divided by 1,000 parts rounded **up**. This final per-piece step is the last rounding in the chain and it is a round-up, not a round-half-up.

Pricing a quote writes the lot figure to `quoted_lot_price_cents` and the per-piece figure to `quoted_piece_price_cents`. In this quoting pass the cycle time is the quote's own nominal `cycle_time_sec`, the yield is the shop's standard 9,700 basis points, and the machine is the one named by `rate_press_id`. §3.7 runs the identical eleven steps a second time with observed inputs, and the difference between the two answers is the whole point of the exercise.

Sending the quote to the customer moves it `PRICED → SUBMITTED` and requires that `quoted_piece_price_cents` has been computed; nothing but the status, `updated_at` and `version` changes. Attempting to send a quote whose status is not `PRICED` is rejected with `ERR_QUOTE_NOT_PRICED`.

The customer's own answer is reserved to a `CustomerRep` acting for the quoting customer, who supplies a `decision` of either `ACCEPT` or `DECLINE`, the mandatory `expected_mold_version` described in §2.5, and an optional `reason`. Either answer requires the quote to be `SUBMITTED` — a decision on a quote in any other status is rejected with `ERR_INVALID_STATE` — and either answer stamps the acting `X-User-ID` onto the quote as `decided_by_user_id`. Beyond that the two branches diverge sharply:

- **`ACCEPT`** additionally requires that the customer's `credit_hold` is false, otherwise `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402), and that the tool's lifecycle status is `NEW` or `SAMPLING`. Acceptance moves the quote `SUBMITTED → ACCEPTED`, drives the tool `NEW → SAMPLING` (a no-op on the status when the tool is already `SAMPLING`, since a second program has been won on a tool already in sampling), and increments the tool's `version` by 1 in either case. Acceptance is also exclusive: every *other* quote on the same tool whose status is `DRAFT`, `PRICED` or `SUBMITTED` is driven to `SUPERSEDED` — an unpriced draft is closed out alongside a submitted rival, with no further cascade of its own.
- **`DECLINE`** moves the quote `SUBMITTED → DECLINED` and touches nothing else. The tool is not mutated and its `version` is unchanged. A declined quote does not supersede its siblings.

`ACCEPTED`, `DECLINED` and `SUPERSEDED` are all terminal. A `SUPERSEDED` quote can no longer be sent, no longer be decided, and can no longer be used to open a production job.

### 3.4. First Article, PPAP and the Tool's Approval Standing

Winning the order puts the tool into `SAMPLING`, and nothing may be produced for sale until the customer has approved a Production Part Approval Process package for it. A `QualityEngineer` opens the package by naming the `mold_id` it qualifies, the `quote_id` it is filed against, a PPAP `level` between 1 and 5 inclusive, and a `max_regrind_bp` between 0 and 10,000 basis points inclusive — the regrind ceiling this package asks the customer to sign off on. A revision of an earlier package additionally names the rejected package it replaces as `supersedes_submission_id`; a first filing leaves that unset. Opening a package is deliberately ungated: it starts in `DRAFT` with `revision_no` at 1, and the tool-status gate bites at filing time, not at creation time.

Filing the package is where the first-article evidence enters the record. The `QualityEngineer` supplies `fai_dimensional_pass`, the dimensional verdict on the first-article sample, and `fai_sample_shots`, the shot count of the sample run that produced it. Filing requires that the tool's lifecycle status is `SAMPLING` — otherwise `ERR_MOLD_NOT_PPAP_APPROVED` — and that the first-article evidence is adequate: the dimensional verdict must be true, and the sample must have been drawn from a run of at least 30 shots. A false verdict or a sample below 30 shots is rejected with `ERR_FAI_NOT_PASSED`. On success both values are stored, the acting `X-User-ID` is recorded as `submitted_by_user_id`, and the package moves `DRAFT → SUBMITTED`.

Internal review comes next, and it is the system's segregation-of-duties checkpoint. A `QualityEngineer` or a `PlantAdmin` supplies a `decision` of `ENDORSE` or `REJECT` and an optional `note`, and in either case the acting `X-User-ID` is recorded as `internal_reviewed_by_user_id`. The reviewer's `X-User-ID` must differ from the `submitted_by_user_id` already stored on the package; when they are the same principal the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. An endorsement moves the package `SUBMITTED → UNDER_REVIEW` and puts it in front of the customer. An internal rejection moves it `SUBMITTED → REJECTED` and leaves the tool entirely untouched.

The customer's verdict is rendered by the `CustomerRep` whose `X-User-ID` matches the tool's `customer_id`, supplying a `decision`, the mandatory `expected_mold_version`, an optional `reason`, and — for one of the three branches — an `interim_expiry_shots` value. All three branches require the package to be in `UNDER_REVIEW` and all three stamp `customer_decided_by_user_id` with the acting `X-User-ID`. Each branch is specified in full below, because their effects on the tool differ in ways that matter downstream:

- **`APPROVE`** additionally requires the tool's lifecycle status to be `SAMPLING`. The package moves `UNDER_REVIEW → APPROVED`. The tool moves `SAMPLING → PPAP_APPROVED`, its `approved_max_regrind_bp` is set to the package's `max_regrind_bp`, its `interim_expiry_shots` is cleared to unset, and its `version` is incremented by 1.
- **`INTERIM_APPROVE`** additionally requires the tool's lifecycle status to be `SAMPLING` and requires that `interim_expiry_shots` is supplied with a value of at least 1. The package moves `UNDER_REVIEW → INTERIM_APPROVED` and stores that shot ceiling on itself as `interim_expiry_shots`. The tool moves `SAMPLING → INTERIM_APPROVED`, its `approved_max_regrind_bp` is set to the package's `max_regrind_bp`, its own `interim_expiry_shots` is set to the tool's current `total_shot_count` plus the supplied allowance — so the ceiling is expressed as an absolute lifetime shot count, not a remaining balance — and its `version` is incremented by 1.
- **`REJECT`** carries no tool-status requirement beyond the package being `UNDER_REVIEW`. The package moves `UNDER_REVIEW → REJECTED`, and the tool is not mutated: its status, its `approved_max_regrind_bp`, its `interim_expiry_shots` and its `version` are all unchanged.

`APPROVED` and `INTERIM_APPROVED` are terminal for the package. A rejected package — whether rejected internally or by the customer — is not. A `QualityEngineer` may send it back for another round, optionally supplying a replacement `max_regrind_bp`, which moves it `REJECTED → DRAFT`, increments `revision_no` by 1, and clears `fai_dimensional_pass`, `fai_sample_shots`, `submitted_by_user_id`, `internal_reviewed_by_user_id` and `customer_decided_by_user_id` all back to unset, so the next round re-earns every one of them. Revision requires the tool to still be in `SAMPLING`.

Quality retains one further lever over an approved tool. A `QualityEngineer` or a `PlantAdmin` may place a hold on it by supplying an `action` of `QUARANTINE` together with an optional `reason`, which is accepted when the tool's status is `SAMPLING`, `PPAP_APPROVED` or `INTERIM_APPROVED` and drives it to `QUARANTINED`. Quarantining a tool that is still `SAMPLING` fires no cascade at all — a sampling tool has no production jobs, by construction — but it does mean any package sitting in `UNDER_REVIEW` can no longer be approved until the tool is released. Quarantining an approved tool, by contrast, is a cascade origin: every job on that tool whose `run_status` is `SCHEDULED` is driven to `BLOCKED` with its `block_reason` set to `MOLD_QUARANTINED`, and each of those jobs then fires its own blocking side effects — de-staging its material and releasing its press minutes — as §3.6 describes.

Releasing a hold uses the same lever with an `action` of `RELEASE` and is accepted only from `QUARANTINED`, and where the tool lands depends on whether it had ever reached an approved PPAP. If `approved_max_regrind_bp` is set, the tool had already been approved before it was quarantined and it returns to `PPAP_APPROVED`, with `interim_expiry_shots` cleared to unset — an approved tool always returns to full approval and never to `INTERIM_APPROVED`, even if that is where it came from. If `approved_max_regrind_bp` is still unset, the tool was quarantined while it was still sampling and it returns to `SAMPLING`, where its pending package becomes decidable again. In neither case are blocked jobs restored automatically; each must be returned to the schedule explicitly, one at a time. An operation aimed at a tool that is currently `QUARANTINED` is rejected with `ERR_MOLD_QUARANTINED`.

### 3.5. Resin: Receipt, Disposition, Staging and Mass Balance

Material arrives at the dock long before anyone knows which job will burn it. A `PlantAdmin` or a `ProcessEngineer` receives a lot by recording its `resin_grade`, the supplier's traceability code as `supplier_lot_code` — unique across every lot the shop has ever received — a `qty_kg_received` of at least 1 kilogram, and an incoming `moisture_bp` between 0 and 10,000 basis points of mass. A received lot begins in `QUARANTINE`, and its running balance `qty_grams_remaining` is initialised to the received kilograms multiplied by the 1,000 grams in a kilogram.

Disposition is a quality verdict and belongs to a `QualityEngineer`, who supplies a `decision` of `RELEASE`, `HOLD` or `REJECT` with an optional `reason`. A `RELEASE` decision is accepted out of `QUARANTINE` and out of `HOLD`, and in both cases requires that the lot's `moisture_bp` is no greater than 200 basis points — two percent of mass — with a lot sitting exactly at 200 basis points passing. A wetter lot is rejected with `ERR_RESIN_MOISTURE_TOO_HIGH`. Releasing out of `QUARANTINE` initialises `qty_grams_remaining` to the received kilograms multiplied by 1,000 if it is somehow still unset; releasing out of `HOLD` makes already-staged jobs startable again. A `HOLD` decision is accepted only from `RELEASED` and moves the lot to `HOLD`; jobs that have already staged that lot keep their `material_status` at `STAGED` but can no longer be started. A `REJECT` decision is accepted from `QUARANTINE` or from `HOLD` and moves the lot to `REJECTED`, after which it can never be staged again. `REJECTED` and `DEPLETED` are the lot's two terminal states.

Binding a lot to a job is a `ProcessEngineer` action that moves the job's **material axis only**, `UNSTAGED → STAGED`, and leaves the run axis exactly where it was — the clearest demonstration in the system that the two axes are genuinely independent. The engineer supplies the `resin_lot_id` to bind. Staging requires the job's `run_status` to be `SCHEDULED`, otherwise `ERR_JOB_NOT_SCHEDULED`; requires the lot's `status` to be `RELEASED`, otherwise `ERR_RESIN_LOT_NOT_RELEASED`; requires the lot's `resin_grade` to equal the `resin_grade` on the job's quote, otherwise `ERR_RESIN_GRADE_MISMATCH`; and requires the lot to have at least 1 gram remaining. On success the lot's id is written to the job's `staged_resin_lot_id`.

The lot's balance is a **conserved quantity**, not a running subtraction. At every point in time, `qty_grams_remaining` equals the received kilograms multiplied by 1,000, minus the sum of `virgin_grams` over every non-reversed shift report whose `resin_lot_id` points at that lot. Regrind never touches a resin lot at all — it comes out of the grinder bin, and no lot balance is debited for it. Because the balance is recomputed from the surviving reports rather than adjusted incrementally, reversing a report restores the grams exactly, with no drift, since grams are whole numbers throughout. When a report drives the balance of a `RELEASED` lot to exactly 0, that lot moves `RELEASED → DEPLETED` and may no longer be staged by another job.

### 3.6. The Production Job: Opening, Routing, Scheduling and the Run Axis

A production job is opened by a `ProcessEngineer` against an accepted quote. The request names the `quote_id`, a `planned_qty` of at least 1 giving the good parts the job is expected to deliver, and the press occupancy window as `scheduled_start` and `scheduled_end`, whose end must be strictly after its start. The machine may be pinned by supplying a `press_id`, or omitted and left to the router. On success the job copies `mold_id` from the quote as a snapshot, records the resolved `press_id`, and comes into existence with `run_status` `DRAFT` and `material_status` `UNSTAGED`. Opening a job reserves **no** press minutes — a `DRAFT` job is a plan, not a booking. Every one of the job's rollups starts at zero: `total_shots`, `parts_molded_total`, `good_parts_total`, `scrap_parts_total`, `short_shot_shots_total`, `total_run_minutes`, `cumulative_regrind_bp`, `job_direct_cost_cents`, `job_overhead_cents` and `job_total_cost_cents` are all 0, `first_pass_yield_bp` stands at 10,000 basis points because nothing has been molded yet, and `actual_cycle_time_sec`, `block_reason`, `staged_resin_lot_id`, `as_run_piece_price_cents` and `price_variance_cents` are all unset.

Opening is gated on the tool before it is gated on the machine. The tool's lifecycle status must be `PPAP_APPROVED` or `INTERIM_APPROVED`, otherwise `ERR_MOLD_NOT_PPAP_APPROVED`; its `service_state` must be `SERVICEABLE`, otherwise `ERR_PM_OVERDUE`; and its `active_transfer_id` must be unset, otherwise `ERR_MOLD_TRANSFER_IN_PROGRESS` — a tool with a transfer in flight takes no new work. Only then is the machine considered. A pinned press must be `AVAILABLE`, must sit inside the tool's tonnage band, must have a `shot_size_grams_max` at least as large as the tool's `shot_weight_grams`, and must carry a `QUALIFIED` qualification row for that tool-and-machine pair — a missing or unqualified row is rejected with `ERR_PRESS_NOT_QUALIFIED`.

When the machine is omitted, the **routing selector** runs, and its filter is strictly narrower than the rate-press selector used at quoting time. Candidates are presses whose `status` is `AVAILABLE`, whose `tonnage` sits at or above the tool's `required_min_tonnage` and at or below its `required_max_tonnage`, whose `shot_size_grams_max` is at or above the tool's `shot_weight_grams`, for which a qualification row with status `QUALIFIED` exists on this tool-and-machine pair, and whose existing occupancy does not collide with the requested window under the half-open plus 45-minute changeover semantics of §2.9. Candidates are ranked by `tonnage` ascending, then `hourly_rate_cents` ascending, then `created_at` ascending, and the first is chosen. An empty candidate set is rejected with `ERR_NO_ELIGIBLE_PRESS`.

Scheduling turns the plan into a booking and is where the press ledger first moves. The `ProcessEngineer` supplies `expected_press_version`, and the job advances `DRAFT → SCHEDULED`. Scheduling requires the press to still be `AVAILABLE`, the tool to still be `PPAP_APPROVED` or `INTERIM_APPROVED`, the tool's `service_state` to still be `SERVICEABLE`, the tool's `active_transfer_id` to still be unset, the job's window to be free of collision with other `SCHEDULED` or `RUNNING` jobs on that press under the press semantics, the window to be free of collision with open maintenance orders and other `SCHEDULED` or `RUNNING` jobs on that *tool* under the closed-interval mold semantics, and the press's committed minutes on the window's UTC start date to remain within 1,224 minutes once this job's duration is added. On success the job's whole-minute duration is added to the press's `committed_minutes_scheduled` and the press's `version` is incremented by 1. Scheduling a job whose `run_status` is not `DRAFT` is rejected with `ERR_INVALID_STATE`.

Starting a job carries no request body at all. It advances `SCHEDULED → RUNNING` and requires that the job's `material_status` is `STAGED` — otherwise `ERR_JOB_MATERIAL_NOT_STAGED` — that the staged lot's `status` is still `RELEASED`, otherwise `ERR_RESIN_LOT_NOT_RELEASED`, and that the tool is still `PPAP_APPROVED` or `INTERIM_APPROVED` with `service_state` `SERVICEABLE`. No counter changes on starting; the job simply becomes eligible to receive shift reports. Starting a job that is not `SCHEDULED` is rejected with `ERR_JOB_NOT_SCHEDULED`.

The system blocks a job on its own initiative. Whenever a tool's `service_state` reaches `PM_DUE`, or its lifecycle status reaches `QUARANTINED` by either route, every job on that tool whose `run_status` is `SCHEDULED` is driven `SCHEDULED → BLOCKED`, with `block_reason` set to `MOLD_PM_DUE`, `MOLD_QUARANTINED` or `INTERIM_PPAP_EXPIRED` according to which condition fired. Arriving at `BLOCKED` fires the job's own two side effects in turn: its `material_status` moves `STAGED → UNSTAGED` with `staged_resin_lot_id` cleared, and its whole-minute duration is subtracted from the press's `committed_minutes_scheduled` with the press's `version` incremented by 1. Note that only `SCHEDULED` jobs are blocked — a job already `RUNNING` on the tool that posted the tripping report keeps running.

Returning a blocked job to the schedule is explicit and never automatic. The `ProcessEngineer` supplies `expected_press_version`, and the job advances `BLOCKED → SCHEDULED` only when the tool's `service_state` is once again `SERVICEABLE` and its lifecycle status is once again `PPAP_APPROVED` or `INTERIM_APPROVED`, and only when the job's original window is still free under both the press and the mold collision rules and still within the press's 1,224-minute daily capacity. On success `block_reason` is cleared, the job's duration is added back to the press's `committed_minutes_scheduled`, and the press's `version` is incremented by 1. The material axis is **not** restored: `material_status` stays `UNSTAGED` and the lot must be staged again from scratch. Unblocking a job that is not `BLOCKED` is rejected with `ERR_JOB_NOT_BLOCKED`.

Completing a job is the terminal act of the run axis and the moment the as-run economics are settled. It advances `RUNNING → COMPLETED`, requires that the job's `total_shots` is at least 1, and carries no request body. On completion the material axis moves `STAGED → CONSUMED`, freezing the lot binding for audit and closing the job to further reports; `actual_cycle_time_sec` and `first_pass_yield_bp` are computed; the as-run pricing pass of §3.7 fills `as_run_piece_price_cents` and `price_variance_cents`; and the job's duration is released from the press's `committed_minutes_scheduled` with the press's `version` incremented by 1. Completing a job that is not `RUNNING` is rejected with `ERR_JOB_NOT_RUNNING`.

Cancellation is available to a `ProcessEngineer` or a `PlantAdmin` with a mandatory `reason`, from `DRAFT`, `SCHEDULED`, `BLOCKED` and `RUNNING`, and its side effects depend on where the job was standing. Cancelling a `SCHEDULED` or a `RUNNING` job releases its duration from the press's `committed_minutes_scheduled` and increments the press's `version` by 1, and moves `material_status` `STAGED → UNSTAGED` with `staged_resin_lot_id` cleared. Cancelling a `BLOCKED` job performs no second release, because the minutes were already given back when the job entered `BLOCKED`. Cancelling a `DRAFT` job releases nothing, because a draft never reserved anything. When a cancellation arrives through the qualification-revocation cascade of §3.2, `block_reason` is set to `QUALIFICATION_REVOKED`; when a person cancels the job explicitly, `block_reason` is left unset. In every cancellation path, shift reports already posted against the job keep their `resin_lot_id` snapshot and remain non-reversed, so the resin and shot ledgers are untouched by the cancellation; and `as_run_piece_price_cents` and `price_variance_cents` stay unset, because the as-run pricing pass runs only on completion.

### 3.7. Shift Reporting: Parts, Regrind, Mass, Cost and the As-Run Price

Every hour the press runs is accounted for by a shift report, posted by a `ProcessEngineer` against a job whose `run_status` is `RUNNING` — a posting against a job in any other run status is rejected with `ERR_JOB_NOT_RUNNING`. The report names the `job_id` it belongs to, the `shots` taken during the interval (at least 1), the `short_shot_shots` that filled incompletely (at least 0 and no more than `shots`), the `good_parts` accepted at the press and the `scrap_parts` rejected there (each at least 0), the `virgin_grams` drawn from the staged lot and the `regrind_grams` drawn from the grinder bin (each at least 0), the `run_minutes` of press occupancy covered (at least 1), and the mandatory `expected_job_version` described in §2.5. On acceptance the report snapshots the job's `staged_resin_lot_id` into its own `resin_lot_id`, so the material traceability of the report survives any later de-staging, and the job's `version` is incremented by 1.

Three gates guard the posting, and §2.7 fixes the order in which they are consulted. **Parts must conserve**: `good_parts` plus `scrap_parts` must equal `shots` multiplied by the tool's `cavity_count`, and `scrap_parts` must be at least `short_shot_shots` multiplied by `cavity_count`, since a short shot cannot yield a good part in any cavity. A failure of either is rejected with `ERR_PARTS_BALANCE_MISMATCH`. **Regrind must stay inside the approved ceiling**, as detailed below. And **the lot must actually have the material**: `virgin_grams` may not exceed the staged lot's `qty_grams_remaining`, otherwise `ERR_RESIN_LOT_INSUFFICIENT`.

The regrind ceiling is whatever the customer approved. When the tool's `approved_max_regrind_bp` is set, that is the limit; when it is still unset — the tool has never carried an approved or interim-approved package — the shop's default ceiling of 1,500 basis points, fifteen percent, applies instead. Two ratios are then computed against that one limit. The report's own **instantaneous** ratio, stored as `instantaneous_regrind_bp`, is `regrind_grams` multiplied by 10,000, divided by the sum of `virgin_grams` and `regrind_grams`, rounded half up; when that sum is zero the ratio is zero. The job's **cumulative** ratio is the candidate report's `regrind_grams` plus the `regrind_grams` of every existing non-reversed report on the job, multiplied by 10,000, divided by the candidate's total mass plus the summed `virgin_grams` and `regrind_grams` of those same existing reports, rounded half up; when that denominator is zero the ratio is zero. Both gates compare with a ceiling that is inclusive — a ratio landing exactly on the limit is accepted — and the instantaneous gate is evaluated **first**, with the cumulative gate consulted only if the instantaneous one passes. Either failure is reported as `ERR_REGRIND_RATIO_EXCEEDED`. On success the cumulative figure is written to the job's `cumulative_regrind_bp`.

Once the report is accepted, five recomputations fire, each defined purely as a function of the job's non-reversed reports so that the same definitions serve both posting and reversal.

**Yield accounting** rebuilds the job's counters from scratch: `total_shots` is the summed `shots`; `parts_molded_total` is the summed product of each report's `shots` and the tool's `cavity_count`; `good_parts_total`, `scrap_parts_total`, `short_shot_shots_total` and `total_run_minutes` are the summed `good_parts`, `scrap_parts`, `short_shot_shots` and `run_minutes` respectively. `first_pass_yield_bp` is `good_parts_total` multiplied by 10,000 and divided by `parts_molded_total`, rounded **down**, and stands at 10,000 basis points whenever `parts_molded_total` is zero. `actual_cycle_time_sec` is `total_run_minutes` multiplied by the 60 seconds in a minute and divided by `total_shots`, rounded half up, and is unset whenever `total_shots` is zero. Because parts conserve at every line, `parts_molded_total` always equals `good_parts_total` plus `scrap_parts_total`, after a posting and after a reversal alike.

**The cost roll** is where rounding order matters most. Each report line carries its own `report_direct_cost_cents`, computed as the machine burden — `run_minutes` multiplied by the press's `hourly_rate_cents`, divided by the 60 minutes in an hour, rounded half up — plus the material cost — the sum of `virgin_grams` and `regrind_grams`, multiplied by the quote's `resin_price_cents_per_kg`, divided by the 1,000 grams in a kilogram, rounded half up. The job's `job_direct_cost_cents` is then the sum of those **already-rounded** line figures. Rounding per line and then summing is the rule; summing raw minutes and raw grams and rounding once at the end is explicitly not the rule, and the two produce different totals whenever two or more lines each carry a half-cent fraction. The overhead tier is keyed on `job_direct_cost_cents` **before** any overhead is added: a direct cost below 500,000 cents takes 3,500 basis points, a direct cost from 500,000 up to but not including 2,000,000 cents takes 2,800 basis points, and a direct cost of 2,000,000 cents or more takes 2,200 basis points. `job_overhead_cents` is `job_direct_cost_cents` multiplied by that basis-point rate, divided by 10,000, rounded half up, and `job_total_cost_cents` is simply `job_direct_cost_cents` plus `job_overhead_cents`. Pinning the evaluation order this way is what prevents the apparent circularity of a tier keyed on a total that would otherwise include its own overhead.

**The lot balance** is recomputed as described in §3.5, and **the tool's shot counters** are recomputed as described in §3.8. The fifth recomputation, the as-run price, waits for completion.

When the job completes, the eleven pricing steps of §3.3 run a second time on the same quote, with three inputs swapped: the cycle time is the job's observed `actual_cycle_time_sec` rather than the quote's nominal `cycle_time_sec`, the yield is the job's observed `first_pass_yield_bp` rather than the standard 9,700 basis points, and the machine rate comes from the job's own `press_id` rather than from the quote's `rate_press_id`. Every other input — `cavitation`, `part_weight_grams`, `resin_price_cents_per_kg`, `annual_volume`, the tool's `ownership` and `tooling_cost_cents` — is identical, which is exactly why the two answers diverge only where the shop's actual cycle and yield diverged from what it promised. The per-piece result is stored as `as_run_piece_price_cents`, and `price_variance_cents` is that figure minus the quote's `quoted_piece_price_cents` — positive when the job cost more per piece to produce than it was sold for.

Reversal is available to a `QualityEngineer` or a `PlantAdmin`, who supplies a mandatory `reason` that is stored on the report as `reversal_reason`. Reversal sets `is_reversed` to true and re-runs every one of the recomputations above from the reports that remain. The lot's `qty_grams_remaining`, the tool's `total_shot_count` and `shots_since_pm`, and every one of the job's part, minute, ratio and cost counters return to precisely their pre-report values. A tool whose `service_state` was driven to `PM_DUE` by the reversed report returns to `SERVICEABLE` once `shots_since_pm` falls back below `pm_interval_shots`; a tool that has meanwhile gone `IN_MAINTENANCE` is left exactly where it is. Reversing a report whose `is_reversed` is already true is rejected with `ERR_REPORT_ALREADY_REVERSED`.

### 3.8. The Toolroom: Shot Counters and Preventive Maintenance

A tool's two shot counters are recomputed on every shift-report posting and on every reversal, and neither is ever incremented in place. `total_shot_count` is the summed `shots` of every non-reversed report whose job names that tool — a lifetime figure that nothing resets. `shots_since_pm` is the summed `shots` of that same set restricted to reports created at or after the tool's last counter reset, where the reset instant is the `created_at` of the most recent maintenance order on that tool whose `status` is `CLOSED` and whose `shots_reset` is true, taking the latest such order by `created_at` descending; when no such order has ever existed, the reset instant is the tool's own `created_at`.

Two threshold gates are then evaluated in a fixed order, and both use an inclusive comparison, so the shot that lands exactly on the threshold trips it. **The preventive-maintenance gate is evaluated first**: if `shots_since_pm` has reached or passed `pm_interval_shots` and the tool's `service_state` is `SERVICEABLE`, the tool moves `SERVICEABLE → PM_DUE`, which is a cascade origin that blocks that tool's scheduled jobs with `block_reason` `MOLD_PM_DUE`. **The interim-approval gate is evaluated second**: if the tool's `interim_expiry_shots` is set, `total_shot_count` has reached or passed it, and the tool's lifecycle status is `INTERIM_APPROVED`, the tool moves `INTERIM_APPROVED → QUARANTINED`, which is likewise a cascade origin, blocking that tool's scheduled jobs with `block_reason` `INTERIM_PPAP_EXPIRED`. An interim approval is thus a shot-metered licence: the customer bought a fixed number of shots, and when they are exhausted the tool takes itself out of production without anyone intervening.

Opening a toolroom order is the only way a tool leaves service deliberately. A `ToolroomTech` or a `PlantAdmin` names the `mold_id`, a `kind` of either `PM` or `REPAIR`, and the toolroom occupancy window as `window_start` and `window_end`, whose end must be strictly after its start. At most one order per tool may be `OPEN` at a time; a second is rejected with `ERR_MAINTENANCE_ALREADY_OPEN`. The window is checked against the tool's other occupancies under the closed-interval, zero-buffer mold semantics of §2.9, which means a maintenance window that merely touches a scheduled job's window on the same tool is a conflict and is rejected with `ERR_MOLD_WINDOW_CONFLICT`. On success the order is created with `status` `OPEN`, `shots_reset` false, and `shots_at_open` snapshotting the tool's `shots_since_pm` at that instant; the tool's `service_state` moves to `IN_MAINTENANCE`, and it may do so from either `SERVICEABLE` or `PM_DUE`.

Closing the order requires `reset_shot_counter` and the mandatory `expected_mold_version` of §2.5, and is accepted only while the order's `status` is `OPEN`. The order moves `OPEN → CLOSED` and the tool's `version` is incremented by 1 either way, but the two branches are not symmetric. When `reset_shot_counter` is true, the tool moves `IN_MAINTENANCE → SERVICEABLE`, its `shots_since_pm` is set to 0, and the order's `shots_reset` is set to true — this is the one and only mechanism in the system that zeroes the PM counter, and note that `total_shot_count` is deliberately *not* reset, since a tool's lifetime shot history survives every maintenance event. When `reset_shot_counter` is false, the tool moves `IN_MAINTENANCE → PM_DUE`, `shots_since_pm` is left exactly as it was and `shots_reset` stays false; that branch is declared only when `shots_since_pm` is at or above `pm_interval_shots`, and a close-without-reset on a tool that is not yet due is rejected with `ERR_INVALID_STATE`. `CLOSED` is terminal for the order. Any job operation attempted on a tool whose `service_state` is `PM_DUE` or `IN_MAINTENANCE` is rejected with `ERR_PM_OVERDUE`.

### 3.9. Commercial Commitments: Tool Ownership and Press Capacity

Customer-owned tooling changes hands through a three-step transfer that a `CustomerRep` — acting for the customer receiving the tool — or a `PlantAdmin` initiates by naming the `mold_id` changing hands, the `to_customer_id` taking ownership, and a `settlement_cents` buy-out amount of at least 0. The request snapshots the tool's current `ownership` into `from_ownership`, writes its own id onto the tool as `active_transfer_id`, increments the tool's `version` by 1, and lands in `REQUESTED`. Only one transfer per tool may hold `REQUESTED` or `APPROVED` at a time; a second request, or any job operation attempted on a tool while `active_transfer_id` is set, is rejected with `ERR_MOLD_TRANSFER_IN_PROGRESS`.

A `PlantAdmin` adjudicates by supplying a `decision` of `APPROVE` or `DECLINE` with an optional `reason`, stored on the transfer as `decision_reason`. Approval requires the tool's lifecycle status to be neither `RETIRED` nor `TRANSFERRED`, moves the transfer `REQUESTED → APPROVED`, and deliberately leaves `active_transfer_id` pointing at it — the tool stays reserved. A decline moves the transfer `REQUESTED → DECLINED`, clears the tool's `active_transfer_id` back to unset and increments the tool's `version` by 1, releasing the tool for production work again. `DECLINED` and `COMPLETED` are the transfer's terminal states.

Completion is the deepest cascade in the system and is reserved to a `PlantAdmin`, who supplies the mandatory `expected_mold_version`. It requires the transfer's `status` to be `APPROVED` — otherwise `ERR_TRANSFER_NOT_APPROVED` — and requires that no job on that tool is currently `RUNNING`, otherwise `ERR_MOLD_TRANSFER_IN_PROGRESS`. On success the transfer moves `APPROVED → COMPLETED` and the tool is rewritten in one step: `ownership` becomes `CUSTOMER_OWNED`, `customer_id` becomes the `to_customer_id`, the lifecycle status moves `PPAP_APPROVED → TRANSFERRED`, `active_transfer_id` is cleared, and `version` is incremented by 1. The tool's arrival at `TRANSFERRED` then fires its own cascade — every `QUALIFIED` qualification row on that tool moves `QUALIFIED → REVOKED` — and each of those revocations fires its own cascade in turn, cancelling every `DRAFT`, `SCHEDULED` and `BLOCKED` job on that tool-and-machine pair with `block_reason` `QUALIFICATION_REVOKED`. Three links, one request.

Press capacity is sold ahead of the work. A `SalesEngineer` or a `PlantAdmin` opens a commitment by naming the `customer_id` buying the time, the `press_id` whose time is committed, the `window_start` and `window_end` of the commitment window, a `committed_minutes` of at least 1, and a `shortfall_policy` of either `STRICT` or `GOODWILL`. A customer whose `credit_hold` is true may not open one, and the attempt is rejected with `ERR_CUSTOMER_CREDIT_HOLD`. The commitment is also gated on what the machine can realistically deliver: the window's length in whole minutes is multiplied by 8,500 basis points — eighty-five percent, the shop's assumed press availability — and divided by 10,000, rounded down, to give the available minutes; every other commitment on that press whose `status` is `OPEN` and whose window strictly overlaps the candidate's, meaning that commitment starts before the candidate's window ends and the candidate starts before that commitment's window ends, has its `committed_minutes` summed; and if that sum plus the candidate's `committed_minutes` exceeds the available minutes, the request is rejected with `ERR_CAPACITY_COMMIT_EXCEEDED`. Windows that merely touch do not aggregate, and only `OPEN` commitments reserve anything — settled and cancelled ones release their reservation. A new commitment lands in `OPEN` with `consumed_minutes`, `shortfall_minutes`, `shortfall_fee_cents` and `utilization_bp` all at 0.

Settlement is a `PlantAdmin` act on an `OPEN` commitment and freezes all four of those figures at once; settling or cancelling a commitment that is not `OPEN` is rejected with `ERR_CAPACITY_COMMIT_NOT_OPEN`. The consumption set is every job on the commitment's press whose `run_status` is `RUNNING` or `COMPLETED`, whose tool belongs to the commitment's customer, and whose window sits **entirely** inside the commitment window — that is, whose `scheduled_start` is at or after `window_start` and whose `scheduled_end` is at or before `window_end`. A job that straddles either boundary is excluded in its entirety rather than pro-rated. `consumed_minutes` is the summed whole-minute duration of that set. `utilization_bp` is `consumed_minutes` multiplied by 10,000, divided by `committed_minutes`, rounded down. `shortfall_minutes` is `committed_minutes` minus `consumed_minutes` when that difference is positive, and 0 otherwise.

The fee then follows the `shortfall_policy` chosen when the commitment was sold, and the two variants are genuinely different products:

- Under **`STRICT`**, every unconsumed committed minute is billed at the press's full rate: `shortfall_fee_cents` is `shortfall_minutes` multiplied by the press's `hourly_rate_cents`, divided by the 60 minutes in an hour, rounded half up. No waiver band exists.
- Under **`GOODWILL`**, a waiver is granted first: the waived minutes are `committed_minutes` multiplied by 1,000 basis points — ten percent of what was committed — divided by 10,000 and rounded down. The billable minutes are `shortfall_minutes` minus those waived minutes when that difference is positive, and 0 otherwise. `shortfall_fee_cents` is then the billable minutes multiplied by the press's `hourly_rate_cents`, multiplied by 5,000 basis points — half the press rate — divided by the product of 60 minutes and 10,000 basis points, rounded half up. For identical `committed_minutes` and identical consumption, a goodwill commitment therefore settles at a strictly lower fee than a strict one whenever any shortfall exists at all.

Settlement moves the commitment `OPEN → SETTLED`. Cancelling one instead — a `PlantAdmin` act carrying a mandatory `reason` — moves it `OPEN → CANCELLED` with `consumed_minutes`, `shortfall_minutes`, `shortfall_fee_cents` and `utilization_bp` all left at 0, and returns the reserved minutes to the pool that future commitments on that press are measured against. `SETTLED` and `CANCELLED` are both terminal.

## 4. Endpoint Definitions

All endpoints are mounted at the root of the service; no resource is nested inside another, and every parent reference travels in the request body or as a list filter. A request that creates a new resource answers with HTTP 201; every other successful request — reads, state transitions, decisions, settlements and the clock control — answers with HTTP 200. The table below is a routing summary only: the request body, the response payload and the side effects of each operation are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/customers` | Register a buying customer | `PlantAdmin` |
| GET | `/customers/{id}` | Read one customer | `PlantAdmin`, `SalesEngineer`, `CustomerRep` |
| POST | `/presses` | Register a molding machine | `PlantAdmin` |
| GET | `/presses/{id}` | Read one press, including its current version for OCC and its committed_minutes_scheduled ledger | `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `QualityEngineer`, `ToolroomTech` |
| GET | `/presses` | List presses with filtering and pagination | `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `QualityEngineer` |
| POST | `/presses/{id}/status` | Take a press offline or bring it back online | `PlantAdmin` |
| POST | `/molds` | Register a tool | `PlantAdmin` |
| GET | `/molds/{id}` | Read one tool, including its version for OCC, both state axes and both shot counters | `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `QualityEngineer`, `ToolroomTech`, `CustomerRep` |
| GET | `/molds` | List tools; customer_id is the reverse-reachability filter for Mold -> Customer | `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `QualityEngineer`, `ToolroomTech`, `CustomerRep` |
| POST | `/molds/{id}/quality-hold` | Quarantine a tool or release it from quarantine | `QualityEngineer`, `PlantAdmin` |
| POST | `/molds/{id}/retire` | Retire a tool permanently | `PlantAdmin` |
| POST | `/press-qualifications` | Open a mold/press qualification junction row | `ProcessEngineer`, `PlantAdmin` |
| GET | `/press-qualifications/{id}` | Read one qualification row | `PlantAdmin`, `ProcessEngineer`, `QualityEngineer` |
| GET | `/press-qualifications` | List qualification rows; mold_id and press_id are the reverse-reachability filters for the junction | `PlantAdmin`, `ProcessEngineer`, `QualityEngineer` |
| POST | `/press-qualifications/{id}/schedule-run-at-rate` | Book a run-at-rate trial window on the qualification row | `ProcessEngineer` |
| POST | `/press-qualifications/{id}/record-run-at-rate` | Record the observed rate and settle the trial verdict | `QualityEngineer` |
| POST | `/quotes` | Draft a quote against a tool | `SalesEngineer` |
| GET | `/quotes/{id}` | Read one quote including its computed price fields | `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `QualityEngineer`, `CustomerRep` |
| GET | `/quotes` | List quotes; customer_id, mold_id and rate_press_id are the reverse-reachability filters for Quote's foreign keys | `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `CustomerRep` |
| POST | `/quotes/{id}/price` | Price the quote with the quoted_estimate variant; press_id may pin the rate press, otherwise quote_press_rate_selection chooses it | `SalesEngineer` |
| POST | `/quotes/{id}/submit` | Send the priced quote to the customer | `SalesEngineer` |
| POST | `/quotes/{id}/customer-decision` | Customer accepts or declines the submitted quote | `CustomerRep` |
| POST | `/ppap-submissions` | Open a PPAP package for a mold and a quote. Creation itself is ungated; the SAMPLING gate is enforced at submit. | `QualityEngineer` |
| GET | `/ppap-submissions/{id}` | Read one PPAP package | `PlantAdmin`, `QualityEngineer`, `ProcessEngineer`, `CustomerRep` |
| GET | `/ppap-submissions` | List PPAP packages; mold_id, quote_id and supersedes_submission_id are the reverse-reachability filters, the last one walking the self-referential revision chain | `PlantAdmin`, `QualityEngineer`, `ProcessEngineer`, `CustomerRep` |
| POST | `/ppap-submissions/{id}/submit` | File the package with its first-article results | `QualityEngineer` |
| POST | `/ppap-submissions/{id}/internal-review` | Internal quality endorsement or rejection; the submitter may not review their own package | `QualityEngineer`, `PlantAdmin` |
| POST | `/ppap-submissions/{id}/customer-decision` | Customer approves, interim-approves or rejects the package | `CustomerRep` |
| POST | `/ppap-submissions/{id}/revise` | Send a rejected package back to DRAFT for another revision round | `QualityEngineer` |
| POST | `/resin-lots` | Receive a resin lot into quarantine | `PlantAdmin`, `ProcessEngineer` |
| GET | `/resin-lots/{id}` | Read one resin lot including its running mass balance | `PlantAdmin`, `ProcessEngineer`, `QualityEngineer` |
| POST | `/resin-lots/{id}/disposition` | Release, hold or reject a resin lot | `QualityEngineer` |
| POST | `/production-jobs` | Open a job against an accepted quote; press_id may pin the machine, otherwise press_routing_selection chooses it | `ProcessEngineer` |
| GET | `/production-jobs/{id}` | Read one job including both state axes, every rollup counter and the cost roll | `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `QualityEngineer`, `CustomerRep` |
| GET | `/production-jobs` | List jobs; quote_id, mold_id, press_id and staged_resin_lot_id are the reverse-reachability filters for the job's four foreign keys | `PlantAdmin`, `SalesEngineer`, `ProcessEngineer`, `QualityEngineer`, `CustomerRep` |
| POST | `/production-jobs/{id}/schedule` | Reserve the press window for a DRAFT job | `ProcessEngineer` |
| POST | `/production-jobs/{id}/stage-material` | Bind a released resin lot to the job (material axis only) | `ProcessEngineer` |
| POST | `/production-jobs/{id}/start` | Put the scheduled, staged job on the press | `ProcessEngineer` |
| POST | `/production-jobs/{id}/complete` | Close the job and roll the as-run cost | `ProcessEngineer` |
| POST | `/production-jobs/{id}/cancel` | Cancel a job that has not completed | `ProcessEngineer`, `PlantAdmin` |
| POST | `/production-jobs/{id}/unblock` | Return a BLOCKED job to SCHEDULED once the tool is serviceable again | `ProcessEngineer` |
| POST | `/production-reports` | Post a shift report against a RUNNING job | `ProcessEngineer` |
| GET | `/production-reports/{id}` | Read one shift report | `PlantAdmin`, `ProcessEngineer`, `QualityEngineer` |
| GET | `/production-reports` | List shift reports; job_id and resin_lot_id are the reverse-reachability filters for the report's foreign keys | `PlantAdmin`, `ProcessEngineer`, `QualityEngineer` |
| POST | `/production-reports/{id}/reverse` | Reverse a posted shift report; the compensating action for POST /production-reports | `QualityEngineer`, `PlantAdmin` |
| POST | `/maintenance-orders` | Open a toolroom order and take the mold out of service for the window | `ToolroomTech`, `PlantAdmin` |
| GET | `/maintenance-orders/{id}` | Read one toolroom order | `PlantAdmin`, `ToolroomTech`, `ProcessEngineer`, `QualityEngineer` |
| GET | `/maintenance-orders` | List toolroom orders; mold_id is the reverse-reachability filter | `PlantAdmin`, `ToolroomTech`, `ProcessEngineer`, `QualityEngineer` |
| POST | `/maintenance-orders/{id}/close` | Close the toolroom order, optionally zeroing the PM shot counter | `ToolroomTech`, `PlantAdmin` |
| POST | `/tool-transfers` | Request transfer of tool ownership to a customer | `CustomerRep`, `PlantAdmin` |
| GET | `/tool-transfers/{id}` | Read one transfer | `PlantAdmin`, `CustomerRep`, `ToolroomTech` |
| GET | `/tool-transfers` | List transfers; mold_id and to_customer_id are the reverse-reachability filters | `PlantAdmin`, `CustomerRep`, `ToolroomTech` |
| POST | `/tool-transfers/{id}/decision` | Approve or decline a requested transfer | `PlantAdmin` |
| POST | `/tool-transfers/{id}/complete` | Hand the tool over; rewrites ownership and cascades through qualifications into jobs | `PlantAdmin` |
| POST | `/capacity-commits` | Sell a block of press minutes to a customer for a window | `SalesEngineer`, `PlantAdmin` |
| GET | `/capacity-commits/{id}` | Read one commitment including its settled figures | `PlantAdmin`, `SalesEngineer`, `CustomerRep` |
| GET | `/capacity-commits` | List commitments; customer_id and press_id are the reverse-reachability filters | `PlantAdmin`, `SalesEngineer`, `CustomerRep` |
| POST | `/capacity-commits/{id}/settle` | Close the window and bill the shortfall with the variant named by shortfall_policy | `PlantAdmin` |
| POST | `/capacity-commits/{id}/cancel` | Cancel an open commitment without billing | `PlantAdmin` |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: move the server's logical clock. Before any call the clock reads exactly 2026-08-01T00:00:00Z and never falls back to real wall-clock time. | `PlantAdmin` |

## 5. Error Code Catalogue

Every error response uses the envelope of §2.2, carrying the identifier below in `error_id`. The conditions that raise each identifier are stated in the §2 and §3 narratives that govern the operation concerned; when more than one condition holds, the screening order of §2.7 decides which identifier is returned.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_CUSTOMER_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRESS_NOT_FOUND` | 404 |
| `ERR_MOLD_NOT_FOUND` | 404 |
| `ERR_QUALIFICATION_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_PPAP_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_RESIN_LOT_NOT_FOUND` | 404 |
| `ERR_JOB_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_MAINTENANCE_ORDER_NOT_FOUND` | 404 |
| `ERR_TOOL_TRANSFER_NOT_FOUND` | 404 |
| `ERR_CAPACITY_COMMIT_NOT_FOUND` | 404 |
| `ERR_STALE_PRESS_VERSION` | 412 |
| `ERR_STALE_JOB_VERSION` | 412 |
| `ERR_STALE_MOLD_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_QUOTE_NOT_PRICED` | 409 |
| `ERR_JOB_NOT_SCHEDULED` | 409 |
| `ERR_JOB_NOT_RUNNING` | 409 |
| `ERR_JOB_NOT_BLOCKED` | 409 |
| `ERR_JOB_MATERIAL_NOT_STAGED` | 409 |
| `ERR_REPORT_ALREADY_REVERSED` | 409 |
| `ERR_TRANSFER_NOT_APPROVED` | 409 |
| `ERR_CAPACITY_COMMIT_NOT_OPEN` | 409 |
| `ERR_RUN_AT_RATE_NOT_SCHEDULED` | 409 |
| `ERR_MOLD_NOT_PPAP_APPROVED` | 409 |
| `ERR_MOLD_QUARANTINED` | 409 |
| `ERR_MOLD_TRANSFERRED` | 409 |
| `ERR_MOLD_RETIRED` | 409 |
| `ERR_PM_OVERDUE` | 409 |
| `ERR_MOLD_TRANSFER_IN_PROGRESS` | 409 |
| `ERR_FAI_NOT_PASSED` | 422 |
| `ERR_RESIN_LOT_NOT_RELEASED` | 422 |
| `ERR_RESIN_GRADE_MISMATCH` | 422 |
| `ERR_RESIN_MOISTURE_TOO_HIGH` | 422 |
| `ERR_PRESS_OFFLINE` | 409 |
| `ERR_PRESS_TONNAGE_MISMATCH` | 422 |
| `ERR_PRESS_SHOT_SIZE_EXCEEDED` | 422 |
| `ERR_PRESS_NOT_QUALIFIED` | 422 |
| `ERR_NO_ELIGIBLE_PRESS` | 422 |
| `ERR_PRESS_WINDOW_CONFLICT` | 409 |
| `ERR_MOLD_WINDOW_CONFLICT` | 409 |
| `ERR_PARTS_BALANCE_MISMATCH` | 422 |
| `ERR_REGRIND_RATIO_EXCEEDED` | 422 |
| `ERR_RESIN_LOT_INSUFFICIENT` | 422 |
| `ERR_PRESS_DAILY_CAPACITY_EXCEEDED` | 422 |
| `ERR_CAPACITY_COMMIT_EXCEEDED` | 422 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_DUPLICATE_QUALIFICATION` | 409 |
| `ERR_MAINTENANCE_ALREADY_OPEN` | 409 |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 |
