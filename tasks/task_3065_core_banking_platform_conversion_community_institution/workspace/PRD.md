# Core Banking Conversion API — Product Requirements Document

## 1. Introduction

A community financial institution replacing its incumbent core platform with a Fiserv target core faces one of the highest-risk undertakings in retail banking: every deposit and loan account must be mapped, balanced, and re-opened on the new system over a single weekend, with general ledger integrity provable at every step. This document specifies the Core Banking Conversion API, the system of record through which the institution and its vendor jointly drive that conversion — from discovery of the incumbent core's product catalog and chart of accounts, through product parameter design and repeated mock conversion runs, to the cutover weekend itself and the post-conversion stabilization period.

The platform serves both sides of the conversion table. Institution-side staff (a `ProjectManager`, an `OperationsLead`, a `Trainer`, a `CommunicationsOfficer`, and a `FinanceController`) own phase advancement, ancillary reintegration, branch readiness, customer notification waves, and vendor financial accountability. Vendor-side staff (a `ConversionEngineer` and a `VendorTriageLead`) own product parameter design, account-to-ledger mapping, exception clearing, mock runs, and post-live defect remediation. Because both organizations act on the same data, the API enforces strict segregation of duties and optimistic concurrency on the writes where a stale view of the project's phase would be dangerous.

Three properties dominate the design. First, **provable balancing**: every mock run recomputes per-account accruals, per-GL variances, and run-level balancing counts, and the cutover may only be planned against a fully passed run. Second, **deterministic cutover mechanics**: a logical clock under the project manager's control drives every window check — file freeze, conversion windows with their completion grace, go/no-go checkpoints, comm send windows, and SLA deadlines — so that a rehearsal and the real weekend execute against the same rules. Third, **financial accountability after go-live**: severity-classed defects carry service-level deadlines, and missed deadlines aggregate into monthly vendor service credit claims whose approval, dispute, and payment are themselves state-guarded workflows.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly across the API: authentication, response envelopes, pagination, the logical clock, monetary precision, optimistic concurrency, and the validation ordering every endpoint observes.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly seven roles, spelled as follows: `ProjectManager`, `ConversionEngineer`, `OperationsLead`, `Trainer`, `CommunicationsOfficer`, `VendorTriageLead`, and `FinanceController`.

For **every** role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares `X-User-ID` to any entity's `id`. It does, however, record the identifier on specific resources for accountability and segregation-of-duties enforcement: a reported defect captures the reporter's `X-User-ID` in `reported_by`, and an approved service credit claim captures the approver's `X-User-ID` in `approved_by`. Two segregation pairs are enforced against these recorded identifiers: the operator who reported a defect may not be the one who triages it, and the operator who approved a service credit claim may not be the one who pays it — either attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Note that the `Trainer` role name and the staff member's `role_scope` enumeration (`TELLER`, `LENDER`, `OPS`, `BRANCH_MANAGER`) are distinct vocabularies: the former is an API caller role, the latter a business attribute of enrolled branch staff.

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

List endpoints accept two optional query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending.

### 2.4. The Logical Clock

All temporal reasoning in the system — conversion windows, comm send windows, training windows, SLA deadlines, accrual day counts, and checkpoint comparisons — is evaluated against a server-maintained **logical clock**, never against wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `ProjectManager` advances the clock by supplying a `current_utc` instant through the clock-setting capability; the call returns the now-current `current_utc`. Advancing the clock is purely a read-model change: no catch-up batch transitions occur as a side effect. In particular, scheduled customer communications are never flushed by clock advancement alone — the only system-driven flush of due communications happens at project go-live.

### 2.5. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` is an integer starting at creation and incrementing by exactly one on every mutation — including system-driven mutations such as phase advances, mapping actions, and go-live cascades — and it is the field against which optimistic concurrency checks are evaluated.

This standard set applies to the conversion project, product types, accounts, GL accounts, mock runs, ancillary systems, training sessions, staff members, customer communications, defects, and service credit claims. Two resource kinds are lighter-weight: **enrollments** and **cutover plan/task records** (the cutover plan and its tasks) carry only `id` and `created_at`; both `updated_at` and `version` are absent on those resources, and no endpoint targeting them participates in optimistic concurrency.

### 2.6. Monetary Precision and Rate Conventions

All monetary quantities in the system — balances, accrued interest, fees, GL variances, service credits — are integer cents. No floating-point money exists anywhere in the API. Interest computation rounds the **daily** interest amount half-up to a whole cent before multiplying by the number of accrual days; all subsequent aggregation is exact integer arithmetic. The nominal annual product `rate` is expressed as a decimal fraction (for example, 0.03 for three percent), not as basis points or percent units.

### 2.7. Optimistic Concurrency Control on Project-Scoped Writes

Two write endpoints are guarded by optimistic concurrency against the owning conversion project. Both the account mapping action and the comm scheduling action require a non-optional `expected_project_version` field in the request body, carrying the client's last observed `version` of the project. If the supplied value does not equal the project's current `version` — because another writer has since advanced the phase, mapped a sibling account, scheduled a comm, or otherwise mutated the project — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Both guarded actions themselves increment the project's `version` by one on success, so every successful mapping or scheduling invalidates every other client's previously observed version. Endpoints not named here do not accept a version field.

### 2.8. Validation Ordering

When several checks could reject the same request, the system applies them in a fixed priority order so that the surfaced error is deterministic. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role authorization for the endpoint (`ERR_FORBIDDEN`); third, existence of every path identifier, validated left to right, with nested resources verified to belong to the project they are addressed under (`ERR_NOT_FOUND`); fourth, request body well-formedness — required fields present, types correct, enum values valid, no unknown fields (`ERR_INVALID_REQUEST`); then the optimistic concurrency check on the two guarded endpoints (`ERR_STALE_VERSION`); then state-machine legality of the requested transition (`ERR_INVALID_STATE`); then clock and window geometry rules (`ERR_OUTSIDE_WINDOW`); then cross-entity referential validity (`ERR_INVALID_REFERENCE`); then entity invariants (`ERR_INVARIANT_VIOLATION`); then per-project uniqueness (`ERR_DUPLICATE`); then service-credit eligibility (`ERR_CREDIT_INELIGIBLE`); then project phase gates (`ERR_PHASE_GATE`); then file-freeze protection (`ERR_FROZEN`); then branch-room overlap on training sessions (`ERR_SESSION_OVERLAP`); then the mock-run singleton rule (`ERR_RUN_IN_PROGRESS`); then the cross-project freeze-channel exclusion (`ERR_FREEZE_CHANNEL_BUSY`); and finally segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). A consequence worth internalizing: because phase-gate checks precede the file-freeze check, a mapping attempt against a `CLOSED` project surfaces `ERR_INVALID_STATE` (the from-state is terminal) rather than `ERR_FROZEN`, while the same attempt against a `CUTOVER_PLANNED` or `LIVE` project surfaces `ERR_FROZEN`.

### 2.9. Cross-Project Freeze Channel

A conversion weekend consumes a shared operational channel: while one institution's cutover tasks are inside their conversion windows (plus a thirty-minute completion grace after each window's end), no other project may open its file freeze inside that span. The exclusion is evaluated across **all** projects known to the system, not merely the project being planned, and plans that have been rolled back release the channel. Both the cutover-planning action and the plan-scheduling action enforce this rule; a violating `file_freeze_start` is rejected with `ERR_FREEZE_CHANNEL_BUSY` (HTTP 409).

### 2.10. File Freeze

Once a project reaches `CUTOVER_PLANNED` — and through `LIVE` — its account inventory is frozen. Every account's `frozen_flag` reads true, and the four account-mutation capabilities (mapping an account, flagging an exception, clearing an exception, and scheduling a customer communication) are all rejected with `ERR_FROZEN` (HTTP 409). The freeze lifts only through cutover rollback, which returns the project to `MOCK_CONVERSION` and blocks the previously mapped inventory.

## 3. Business Logic & Workflows

This section walks the conversion as it actually unfolds: program setup, product design, account staging and mapping, mock runs and balancing, cutover planning and execution, ancillary reintegration, staff readiness, customer communication, and the post-live defect and service-credit cycle. State names appear as exact UPPERCASE strings; the state pair on each transition is the bridge back to the endpoint table in §4.

### 3.1. Program Setup and Phase Advancement

A `ProjectManager` opens a conversion program by creating a project with the institution's legal `institution_name`, the `incumbent_core_name` being replaced, and the `target_core_name` being adopted; an optional `cutover_scheduled_date` may be supplied at creation or left null until the cutover is planned. The new project begins with its `status` in `DISCOVERY`, with `mock_runs_used` at zero and `cutoff_business_date` null. When a `cutover_scheduled_date` is set, it must fall strictly after the current logical clock date.

Phase advancement is a single capability used twice. Advancing `DISCOVERY → CONFIGURATION` requires that at least one product type (in any status) and at least one GL account already exist for the project. Advancing `CONFIGURATION → MOCK_CONVERSION` requires at least one `ACTIVE` product type and at least one `MAPPED` account. Each successful advance increments the project's `version` by one. A failure of any phase precondition — on advance, on cutover planning, on go-live, or on close — is rejected with `ERR_PHASE_GATE` (HTTP 409). From `LIVE`, a `ProjectManager` may close the program (`LIVE → CLOSED`) only when no defect remains in `OPEN`, `TRIAGED`, `IN_FIX`, or `REOPENED` status and no service credit claim is still `OPEN`; `CLOSED` is terminal for the project.

### 3.2. Product Parameter Design

The `ConversionEngineer` designs the target product catalog during `DISCOVERY` and `CONFIGURATION`. Each product type is created under a `project_id` with a `product_code` unique within the project, a `kind` of `DEPOSIT` or `LOAN`, an `accrual_method`, a nominal annual `rate`, a `statement_frequency` of `MONTHLY` or `QUARTERLY`, and optional `monthly_fee_cents` (default zero, never negative), `fee_waiver_threshold_cents` (null meaning the fee is never waived), and `minimum_balance_cents` (default zero).

Accrual legality is kind-dependent and enforced both at activation and as a product invariant (violations surface `ERR_INVARIANT_VIOLATION`, HTTP 422): a `DEPOSIT` product may use `ACT_365` or `ACT_360` but never `THIRTY_360`; a `LOAN` product may use `ACT_360` or `THIRTY_360` but never `ACT_365`. The `rate` must be at least zero for a deposit product and strictly greater than zero for a loan product.

A product is created in `DRAFT` status. Activation (`DRAFT → ACTIVE`) is permitted only while the project is in `DISCOVERY` or `CONFIGURATION` and re-checks the accrual legality, rate sign, and statement frequency above. Deactivation (`ACTIVE → DRAFT`), likewise restricted to those two phases, carries an important cascade: every account governed by that product which is currently `MAPPED` flips to `EXCEPTION` with the exception note "product deactivated". Retirement (`DRAFT → RETIRED` or `ACTIVE → RETIRED`) is allowed only when no account references the product in `STAGED`, `MAPPED`, `EXCEPTION`, or `CLEARED` status; `RETIRED` is terminal.

### 3.3. Account Staging, Mapping, and the General Ledger

Accounts are staged onto the conversion by a `ConversionEngineer` supplying the `project_id`, the `legacy_account_number` from the incumbent core (unique within the project), the `account_type` (`DEPOSIT` or `LOAN`), the governing `product_type_id`, the `opening_principal_cents` ledger balance at freeze (never negative), the `statement_cycle_day` of month on which the statement cycle closes (an integer from 1 to 28), and the `accrual_start_date` from which interest begins accruing. The system mints the `new_account_number` on the target core at staging time — renumbering policy is outside this API's scope — and the account begins in `STAGED` status with `gl_account_id` null and `frozen_flag` false.

Mapping (`STAGED → MAPPED`) ties an account to the general ledger: the call supplies a `gl_account_id` referencing a GL account of the same project, plus the OCC field `expected_project_version` described in §2.7. The project's status must be `DISCOVERY`, `CONFIGURATION`, or `MOCK_CONVERSION` — attempts during `CUTOVER_PLANNED` or `LIVE` are rejected with `ERR_FROZEN`, and against a `CLOSED` project with `ERR_INVALID_STATE`. The referenced product must be `ACTIVE` and its `kind` must equal the account's `account_type`; a kind mismatch or a GL account belonging to a different project is rejected with `ERR_INVALID_REFERENCE` (HTTP 422). A successful mapping stores the `gl_account_id`, recomputes the referenced GL's expected, converted, and variance totals, and increments the project `version`.

GL accounts themselves are created by a `ConversionEngineer` with a `gl_code` unique within the project and a human-readable `description`. Each GL continuously exposes three computed totals: `expected_balance_cents`, the sum of `opening_principal_cents` across its accounts in `MAPPED`, `EXCEPTION`, `CLEARED`, or `CONVERTED` status; `converted_balance_cents`, the sum of `conversion_balance_cents` across the same set; and `variance_cents`, the converted total minus the expected total. A GL is balanced exactly when its variance is zero cents.

During `MOCK_CONVERSION`, an engineer may flag a `MAPPED` or `CLEARED` account into `EXCEPTION` by supplying a `note`, which is recorded as the account's `exception_note`; the account's `frozen_flag` must be false. Clearing an exception (`EXCEPTION → CLEARED`) requires a `resolution_note`, the same phase and freeze conditions, and recomputes the owning GL's three totals. Beyond these explicit actions, `MAPPED → EXCEPTION` also fires as a system cascade — on product deactivation ("product deactivated") and at go-live for any account still uncleared ("uncleared at go-live"). The remaining account transitions are system-only: at go-live every `CLEARED` account becomes `CONVERTED` (never a `MAPPED` one — uncleared accounts fall to `EXCEPTION` instead), and on cutover rollback every account in `MAPPED`, `CLEARED`, or `EXCEPTION` becomes `BLOCKED`. Both `CONVERTED` and `BLOCKED` are terminal.

### 3.4. Interest Accrual and Monthly Fee Assessment

Interest accrual is computed per account from its `opening_principal_cents`, the product `rate`, the product `accrual_method`, the account's `accrual_start_date`, and a computation date. The daily interest is the principal times the rate divided by the method's divisor — 365 for `ACT_365`, 360 for `ACT_360`, and 360 for `THIRTY_360` — rounded half-up to a whole cent; this is the account's `daily_interest_cents`. If the accrual start date falls after the computation date, the day count is zero (accrual never runs backward); otherwise the day count spans the start date through the computation date inclusive. Under `ACT_365` and `ACT_360` the count is calendar days; under `THIRTY_360` every month counts as exactly thirty days — the count is 360 times the year difference, plus 30 times the month difference, plus the smaller of the computation date's day-of-month and 30, minus the smaller of the start date's day-of-month and 30, plus one. The accrued interest `cutoff_accrued_interest_cents` is the daily amount times the day count. For a `DEPOSIT` account the `conversion_balance_cents` is the principal plus the accrued interest; for a `LOAN` account the `conversion_balance_cents` always equals the principal exactly — loan interest is tracked separately and never folds into the converted balance. Accrual is computed for accounts in `MAPPED`, `EXCEPTION`, `CLEARED`, or `CONVERTED` status; `STAGED` and `BLOCKED` accounts are excluded.

The monthly fee assessment runs per account over the `MAPPED`, `EXCEPTION`, and `CLEARED` population (excluding `STAGED`, `CONVERTED`, and `BLOCKED`). The computed `conversion_balance_cents` stands in for the cycle's average daily balance. For a `DEPOSIT` account: if the product's `fee_waiver_threshold_cents` is null, the full `monthly_fee_cents` is assessed; otherwise, when the balance is at least the threshold the fee is waived to zero — equality waives — and below the threshold the full fee is assessed. For a `LOAN` account the assessed fee is always zero. The result is recorded as `monthly_fee_assessed_cents`.

### 3.5. Mock Conversion Runs and Balancing

Once the project is in `MOCK_CONVERSION`, a `ConversionEngineer` starts mock runs, each labelled with a `run_label` unique within the project (for example, "MOCK-1"). A run begins in `RUNNING` state with `started_at` stamped from the logical clock. Only one run per project may be in flight: starting a second run while another is `RUNNING` is rejected with `ERR_RUN_IN_PROGRESS` (HTTP 409), and finalization likewise requires that no other run of the project is still `RUNNING`.

Finalizing a run is the heart of the balancing story. The system stamps `finished_at` from the clock, computes `duration_seconds` as the whole seconds between start and finish, recomputes the accrual and monthly fee for every in-scope account at the finalize clock date, recomputes every GL's variance, and then snapshots three run-level figures: `balanced_account_count`, the number of accounts in `MAPPED`, `CLEARED`, or `BLOCKED` status; `exception_account_count`, the number in `EXCEPTION`; and `converted_total_cents`, the sum of `conversion_balance_cents` over **all** accounts of the project regardless of status — which therefore includes mapped-to-GL accounts and unmapped accounts alike (the unmapped contribute their converted balance but no expected balance). The run's `outcome` — mirrored into `state` — is then decided from the counts: zero balanced accounts yields `FAILED`; otherwise any exception accounts yield `PASSED_WITH_EXCEPTIONS`; otherwise the run is `PASSED`. Every finalization increments the project's `mock_runs_used` by one.

The mock-run accrual variant is **advisory**: it refreshes `conversion_balance_cents`, `cutoff_accrued_interest_cents`, and `daily_interest_cents` per account but never flags exceptions on accounts as a side effect of the computation itself. A `PASSED` run carries one further cascade with two links: every account that was `CLEARED` at finalize time returns to `MAPPED` — the passed run certifies the current mapping, so previously cleared exceptions must be re-certified by the next run — and each such flip re-triggers the GL variance recomputation on that account's GL.

### 3.6. Cutover Planning and the Freeze Channel

Cutover planning (`MOCK_CONVERSION → CUTOVER_PLANNED`) is a single `ProjectManager` action carrying four parameters: the `cutover_scheduled_date`, the `file_freeze_start`, the `go_no_go_checkpoint`, and the `reopen_target`. The preconditions are strict: exactly one mock run of the project must be in `PASSED` state and no run may yet be marked as the cutover baseline; no account may sit in `EXCEPTION`; the `cutover_scheduled_date` must be provided and strictly after the current clock date; and the `file_freeze_start` must respect the cross-project freeze channel of §2.9 — it must not fall inside any non-rolled-back plan's task window span, from `conversion_window_start` through `conversion_window_end` plus thirty minutes, on **any other** project, or the planning call is rejected with `ERR_FREEZE_CHANNEL_BUSY`.

On success, the system creates the project's single cutover plan in `DRAFT` status with `planned_cutover_date` set to the supplied `cutover_scheduled_date`, marks the `PASSED` run's `is_cutover_baseline` true, sets every account's `frozen_flag` true (the file freeze begins at planning time, not at the freeze timestamp), and increments the project `version`. A project may only ever have one cutover plan; a second plan creation violates `ERR_INVARIANT_VIOLATION`.

The `ProjectManager` then builds the plan's runbook as cutover tasks. Each task is created under a `plan_id` with a `task_name`, a `sequence` number dense and unique within the plan (1 through N), a `conversion_window_start` strictly after the plan's `file_freeze_start`, a `conversion_window_end` strictly after its own start, an `owner_role` of `CONVERSION_ENGINEER` or `OPERATIONS_LEAD`, and an optional `depends_on_task_id`. A dependency must reference a task of the **same plan** with a strictly smaller sequence — self-reference and forward reference are both rejected with `ERR_INVALID_REFERENCE`. Each task record is anchored to its plan through the `parent_plan_id` it carries. Tasks begin in `PENDING` status with `duration_minutes` null.

Scheduling the plan (`DRAFT → SCHEDULED`) validates the full window geometry: at least one task exists; `file_freeze_start` falls strictly before the earliest task's `conversion_window_start`; the `go_no_go_checkpoint` sits strictly between `file_freeze_start` and `reopen_target`; and `reopen_target` is at or after the latest task's `conversion_window_end`. The freeze-channel exclusion is checked again at scheduling time. Geometry violations surface `ERR_OUTSIDE_WINDOW` (HTTP 409). At or after the `go_no_go_checkpoint`, and provided no task has `FAILED`, the plan may be declared `GO` (`SCHEDULED → GO`); declaring go before the checkpoint is an `ERR_OUTSIDE_WINDOW` rejection.

Rollback (`SCHEDULED → ROLLED_BACK` or `GO → ROLLED_BACK`) is the escape hatch and cascades broadly: every `PENDING` or `RUNNING` task becomes `SKIPPED` while `COMPLETE` tasks keep their status; every account in `MAPPED`, `CLEARED`, or `EXCEPTION` becomes `BLOCKED` with `frozen_flag` left true; the project returns to `MOCK_CONVERSION` with `cutover_scheduled_date` cleared to null; and the baseline run's `is_cutover_baseline` returns to false, freeing a future passed run to serve as the new baseline. `ROLLED_BACK` is terminal for the plan. The remaining plan transition, `GO → LIVE`, is system-driven: it fires when the project goes live.

### 3.7. Executing the Cutover Weekend

Once the plan is `GO`, task execution is governed by the logical clock. Starting a task (`PENDING → RUNNING`) is performed by the role named as the task's `owner_role` — a `ConversionEngineer` for engineering tasks, an `OperationsLead` for operations tasks — and requires the clock to be at or after `conversion_window_start` and strictly before `conversion_window_end`; additionally, if the task names a `depends_on_task_id`, the predecessor must be `COMPLETE`. Starting too early or too late, or completing outside the allowed span, is rejected with `ERR_OUTSIDE_WINDOW`. Completing a task (`RUNNING → COMPLETE`) is permitted up to thirty minutes past the window's end — the completion grace — and stamps `duration_minutes` as the whole minutes between the start and completion clock times. A task may instead be failed (`RUNNING → FAILED`), which blocks the plan's go declaration until rolled back. `COMPLETE`, `SKIPPED`, and `FAILED` are all terminal for a task.

Project go-live (`CUTOVER_PLANNED → LIVE`) is the point of no return and its gate is exacting: the plan must be in `GO` status; every task of the plan must be `COMPLETE` or `SKIPPED`; every ancillary system of the project must be `VERIFIED` or `RETEST_PASSED`; and no `SEV1` defect may sit in `OPEN`, `TRIAGED`, `IN_FIX`, or `REOPENED`. On success the system: sets the project's `cutoff_business_date` to the current clock date — the authoritative business date for cutoff, against which day-1 accrual runs; moves the plan `GO → LIVE`; transitions every `CLEARED` account to `CONVERTED` and recomputes each such account's accrual authoritatively with the computation date set to `cutoff_business_date` (this cutover variant writes the final `conversion_balance_cents` and accrued interest for day-1 opening, and only `CLEARED` accounts are converted); flips every still-`MAPPED` account to `EXCEPTION` with the note "uncleared at go-live"; flushes every `SCHEDULED` customer communication whose `scheduled_send_date` is at or before the current clock time to `SENT` — this go-live flush is exempt from the comm's `send_before` upper bound; and increments the project `version`.

### 3.8. Ancillary System Reintegration

The target core does not stand alone: card processing, online banking, item processing, and reporting feeds must all be re-pointed. An `OperationsLead` registers each ancillary system under a `project_id` with a `name` unique within the project, a `category` of `CARDS`, `ONLINE_BANKING`, `ITEM_PROCESSING`, or `REPORTING`, and a target `interface_version` string; new systems begin in `PENDING` status.

Integration work (`PENDING → INTEGRATING`, or `FAILED → INTEGRATING` on a retry) is permitted while the project is in `MOCK_CONVERSION` or `CUTOVER_PLANNED`. From `INTEGRATING`, the system may be marked `VERIFIED` — a terminal success state reachable under the same phase gate — or marked `FAILED`. A failed system can be retested to `RETEST_PASSED`, which is also terminal and equally satisfies the go-live requirement. Integration status is not static, however: as §3.10 describes, resolving a defect linked to a system knocks a `VERIFIED` system back to `INTEGRATING` and a `RETEST_PASSED` system back to `FAILED`, forcing re-verification before any later go-live gate evaluation.

### 3.9. Staff Training and Branch Readiness

Parallel operations during cutover weekend demand certified staff. A `Trainer` registers staff under a `project_id` with an `employee_code` unique within the project, a `full_name`, a home `branch_name`, and a `role_scope` of `TELLER`, `LENDER`, `OPS`, or `BRANCH_MANAGER`. Training sessions are scheduled per branch with a `branch_name`, a `scheduled_start` and `scheduled_end` (the end strictly after the start), and a seat `capacity` of at least one; a new session begins in `SCHEDULED` status with `reserved_count` and `attended_count` at zero. Two sessions covering the same `branch_name` may not overlap in time — the interval from `scheduled_start` to `scheduled_end` is treated as half-open, so a session whose start exactly equals another session's end is allowed — and a genuinely overlapping, non-`CANCELLED` session causes rejection with `ERR_SESSION_OVERLAP` (HTTP 409).

Each enrollment record carries a `parent_session_id` identifying the owning training session, alongside the `employee_id` naming the enrolled staff member. Enrolling a staff member pairs a `session_id` with an `employee_id` and creates an enrollment in `RESERVED` state, bumping the session's `reserved_count` by one. Enrollment respects the session's capacity — enrolling beyond `capacity` violates `ERR_INVARIANT_VIOLATION` — and the same staff member may not be enrolled twice in the same session, likewise an invariant violation.

Starting a session (`SCHEDULED → IN_PROGRESS`) requires the clock to be at or after `scheduled_start` and strictly before `scheduled_end`. While the session is in progress, the trainer marks each `RESERVED` enrollment as attended or no-show. Marking attended (`RESERVED → ATTENDED`) moves one from `reserved_count` to `attended_count`; marking no-show (`RESERVED → NO_SHOW`) decrements `reserved_count` alone; cancelling an enrollment (`RESERVED → CANCELLED`) does the same. Completing a session (`IN_PROGRESS → COMPLETED`) requires the clock to be at or past `scheduled_end` and **no** enrollment left in `RESERVED`; it then recomputes both counts from the enrollments and fires the certification cascade: every staff member holding at least one `ATTENDED` enrollment in that session has `parallel_ops_certified` set true. Certification is granted at session completion, never at attend time. One refinement keeps the flow tight: if marking the last remaining non-cancelled enrollment out of `RESERVED` happens when the clock is already at or past `scheduled_end`, the session auto-completes on the spot (`IN_PROGRESS → COMPLETED`) and the certification cascade fires immediately. Cancelling a session (`SCHEDULED → CANCELLED`) cascades every `RESERVED` enrollment to `CANCELLED` and recomputes `reserved_count`; `COMPLETED` and `CANCELLED` are terminal.

### 3.10. Customer Communication Waves

Customers must be told about changed account numbers, card reissues, and payment redirection — in planned waves, never ad hoc. A `CommunicationsOfficer` creates a communication under a `project_id` for a specific `account_id`, with a `comm_type` of `ACCOUNT_NUMBER_CHANGE`, `CARD_REISSUE`, or `PAYMENT_REDIRECTION`, and a `wave` number starting at 1. The send window is derived deterministically from the project's creation clock time: `send_after` is the project creation time plus (wave − 1) whole days, and `send_before` is exactly three days after `send_after` — the window closes three days after it opens. A new comm begins in `DRAFT` status with `scheduled_send_date` initialized to `send_after` and `resend_count` zero.

Scheduling (`DRAFT → SCHEDULED`) requires the covered account to be in `MAPPED`, `EXCEPTION`, or `CLEARED` status with `frozen_flag` false, and carries the OCC field `expected_project_version` per §2.7 — a project that has been re-phased since the client last read it (for example, moved into `CUTOVER_PLANNED`, which froze the accounts) makes the client's wave assumptions stale, and the call is rejected with `ERR_STALE_VERSION`. Successful scheduling sets `scheduled_send_date` to the `send_after` baseline and increments the project `version`. A comm whose account or phase conditions are violated during the freeze is rejected with `ERR_FROZEN`.

Sending (`SCHEDULED → SENT`) requires the clock to be at or after `scheduled_send_date` and at or before `send_before`; a comm whose window has expired cannot be sent and the attempt is rejected with `ERR_OUTSIDE_WINDOW`. (Recall from §3.7 that the go-live flush applies its own rule and is exempt from the upper bound.) From `SENT`, the comm may be marked `DELIVERED` (terminal) or marked `FAILED`. Resending a failed comm (`FAILED → SENT`) increments `resend_count` and applies wave backoff: the new `scheduled_send_date` is `send_after` shifted later by `resend_count` whole days, computed with the count after its increment. Backoff only ever pushes a comm later, never earlier than `send_after`, and it may legitimately push `scheduled_send_date` beyond `send_before` — the resent comm remains bound by `send_before` on its next send attempt, so a sufficiently backed-off comm can become unsendable. Cancelling (`DRAFT → CANCELLED` or `SCHEDULED → CANCELLED`) is always available before sending; `CANCELLED` is terminal.

### 3.11. Defect Triage After Go-Live

Post-conversion defects are reported by a `ProjectManager` or `OperationsLead` under a `project_id` with a `title`, a `severity` of `SEV1`, `SEV2`, or `SEV3`, and optionally a `linked_system_id` pointing at an ancillary system of the same project — a cross-project link is rejected with `ERR_INVALID_REFERENCE`. The system records the reporter's `X-User-ID` in `reported_by`, stamps `opened_at` from the logical clock, and computes the `sla_deadline`: twenty-four hours after opening for `SEV1`, seventy-two hours for `SEV2`, and one hundred sixty-eight hours for `SEV3`. The defect begins `OPEN` with `triage_priority` null, `resolved_at` null, `credit_eligible` false, and `reopened_count` zero.

Triage (`OPEN → TRIAGED`) belongs to the `VendorTriageLead` and is allowed from the moment the defect exists, including pre-live dry runs — but never by the same `X-User-ID` that reported it, on pain of `ERR_SEGREGATION_OF_DUTIES`. Triage assigns the `triage_priority` from a score. The severity contributes a weight: 100 for `SEV1`, 50 for `SEV2`, 20 for `SEV3`. Age contributes in steps: the whole hours since `opened_at`, divided into complete twenty-four-hour steps, capped at three steps, times 10 points per step. The score is the sum; the priority band is 1 when the score is at least 110, 2 when at least 90, 3 when at least 60, 4 when at least 30, and 5 otherwise — every boundary inclusive, so a score of exactly 110 yields priority 1 while 109 yields priority 2.

From `TRIAGED`, the vendor moves the defect into `IN_FIX` to start work, or resolves it directly; from `IN_FIX`, the vendor may reject the fix, returning the defect to `OPEN` with its `triage_priority` retained. Resolution is possible from `OPEN`, `TRIAGED`, `IN_FIX`, and `REOPENED`, and always does the same three things: stamps `resolved_at` from the clock; sets `credit_eligible` true exactly when `resolved_at` falls after the `sla_deadline`; and, when `linked_system_id` is set, knocks the linked ancillary system back — `VERIFIED` to `INTEGRATING`, `RETEST_PASSED` to `FAILED`. The SLA deadline never moves: resolving a `REOPENED` defect recomputes `credit_eligible` against the original deadline.

A `ProjectManager` may reopen a resolved defect (`RESOLVED → REOPENED`), which increments `reopened_count`, clears `resolved_at` to null, forces `credit_eligible` false, and — critically — disputes money in flight: every `OPEN` service credit claim of the project whose `defect_ids` reference this defect transitions to `DISPUTED` with the dispute note "auto: defect reopened". Closing a defect (`RESOLVED → CLOSED`, terminal) is permitted only while no `OPEN` service credit claim references it.

### 3.12. Vendor Service Credit Claims

Missed SLAs cost the vendor money, aggregated monthly. A `FinanceController` files a claim under a `project_id` for an accrual `month` in YYYY-MM form — the month of the covered defects' SLA deadlines — with a non-empty `defect_ids` list. Every referenced defect must currently be `credit_eligible`, must have its `sla_deadline` fall in the claim's `month`, and must not already appear in another `OPEN` claim of the project; additionally there may be only one `OPEN` claim per project per month. Eligibility failures are rejected with `ERR_CREDIT_INELIGIBLE` (HTTP 422); the one-open-claim-per-month rule is an invariant violation. The claim begins with its `claim_status` in `OPEN` and with `dispute_note` null.

The credit amount is computed at creation (and again on reopen-from-dispute) in a pinned four-step order. First, per defect and preserving the `defect_ids` order, the breach hours are the seconds from the defect's `sla_deadline` to its `resolved_at`, divided into hours and rounded **up** to the next whole hour — these populate `breach_hours` positionally. Second, the total breach hours are summed across the claim. Third, the first four hours per month are covered under the contract, so the uncovered hours are the total minus four, floored at zero. Fourth, the raw credit is the uncovered hours times 25,000 cents per hour (that is, 250 dollars per hour), and the final `credit_cents` is that raw amount capped at 200,000 cents (2,000 dollars) for the month — the cap applies to the aggregated monthly claim, not per defect.

Approval (`OPEN → APPROVED`) re-verifies that every listed defect is still `RESOLVED` and still `credit_eligible`. Payment (`APPROVED → PAID`, terminal) re-checks that every listed defect is still `RESOLVED`, and must not be performed by the same `X-User-ID` recorded in `approved_by` — the approver-payer split is the second segregation-of-duties pair. Either an `OPEN` or an `APPROVED` claim may be disputed by the `VendorTriageLead` (or by the system, via the defect-reopen cascade of §3.11), moving it to `DISPUTED` with a `dispute_note` recorded; the manual dispute call carries the note in its request. A disputed claim returns to `OPEN` (`DISPUTED → OPEN`) only when every listed defect is again `RESOLVED` and `credit_eligible`, and the return recomputes `credit_cents` under the four-step rule. Finally, an `OPEN` claim whose roster has lost eligibility — at least one defect no longer `credit_eligible` — may be rejected outright (`OPEN → REJECTED`, terminal). A project cannot close while any claim remains `OPEN`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api/v1` prefix. Endpoints that create a new resource respond with 201 and the created resource; all other successful operations — state transitions, retrievals, list queries — respond with 200. Error responses use the envelope of §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/v1/_clock/set_current_utc | Set the server's logical clock | ProjectManager |
| POST | /api/v1/conversions | Create a conversion project | ProjectManager |
| GET | /api/v1/conversions | List conversion projects | ProjectManager, ConversionEngineer, OperationsLead, Trainer, CommunicationsOfficer, VendorTriageLead, FinanceController |
| GET | /api/v1/conversions/{id} | Get a conversion project | ProjectManager, ConversionEngineer, OperationsLead, Trainer, CommunicationsOfficer, VendorTriageLead, FinanceController |
| POST | /api/v1/conversions/{id}/advance | Advance the project phase (DISCOVERY → CONFIGURATION → MOCK_CONVERSION) | ProjectManager |
| POST | /api/v1/conversions/{id}/plan-cutover | Plan the cutover: create the plan, freeze accounts, mark the baseline run | ProjectManager |
| POST | /api/v1/conversions/{id}/go-live | Go live: convert cleared accounts, flip uncleared to exception, flush due comms | ProjectManager |
| POST | /api/v1/conversions/{id}/close | Close the project once no defect is active and no claim is open | ProjectManager |
| POST | /api/v1/product-types | Create a product type | ConversionEngineer |
| GET | /api/v1/product-types | List product types of a project | ProjectManager, ConversionEngineer, OperationsLead |
| GET | /api/v1/product-types/{ptid} | Get a product type | ProjectManager, ConversionEngineer, OperationsLead |
| POST | /api/v1/product-types/{ptid}/activate | Activate a draft product type | ConversionEngineer |
| POST | /api/v1/product-types/{ptid}/deactivate | Return an active product type to draft; cascades mapped accounts to exception | ConversionEngineer |
| POST | /api/v1/product-types/{ptid}/retire | Retire a product type with no active accounts | ConversionEngineer |
| POST | /api/v1/gl-accounts | Create a GL account | ConversionEngineer |
| GET | /api/v1/gl-accounts | List GL accounts | ProjectManager, ConversionEngineer, FinanceController |
| GET | /api/v1/gl-accounts/{gid} | Get a GL account with computed expected/converted/variance | ProjectManager, ConversionEngineer, FinanceController |
| POST | /api/v1/accounts | Stage a legacy account for conversion | ConversionEngineer |
| GET | /api/v1/accounts | List accounts of a project | ProjectManager, ConversionEngineer, OperationsLead, FinanceController |
| GET | /api/v1/accounts/{aid} | Get an account with computed conversion fields | ProjectManager, ConversionEngineer, OperationsLead, FinanceController |
| POST | /api/v1/accounts/{aid}/map | Map a staged account to a GL account (OCC-guarded on project version) | ConversionEngineer |
| POST | /api/v1/accounts/{aid}/flag-exception | Flag a mapped or cleared account as exception | ConversionEngineer |
| POST | /api/v1/accounts/{aid}/clear-exception | Clear an exception account | ConversionEngineer |
| POST | /api/v1/mock-runs | Start a mock conversion run | ConversionEngineer |
| GET | /api/v1/mock-runs | List mock runs | ProjectManager, ConversionEngineer, OperationsLead |
| GET | /api/v1/mock-runs/{rid} | Get a mock run with balancing report fields | ProjectManager, ConversionEngineer, OperationsLead |
| POST | /api/v1/mock-runs/{rid}/finalize | Finalize a run: accruals, fees, GL variances, balancing counts, outcome | ConversionEngineer |
| POST | /api/v1/ancillary-systems | Register an ancillary system for reintegration | OperationsLead |
| GET | /api/v1/ancillary-systems | List ancillary systems | ProjectManager, OperationsLead, VendorTriageLead |
| GET | /api/v1/ancillary-systems/{sid} | Get an ancillary system | ProjectManager, OperationsLead, VendorTriageLead |
| POST | /api/v1/ancillary-systems/{sid}/start-integration | Begin integration work | OperationsLead |
| POST | /api/v1/ancillary-systems/{sid}/verify | Mark integration verified | OperationsLead |
| POST | /api/v1/ancillary-systems/{sid}/fail | Mark integration failed | OperationsLead |
| POST | /api/v1/ancillary-systems/{sid}/retest | Retest a failed integration | OperationsLead |
| POST | /api/v1/training-sessions | Schedule a branch training session | Trainer |
| GET | /api/v1/training-sessions | List training sessions | ProjectManager, Trainer, OperationsLead |
| GET | /api/v1/training-sessions/{tsid} | Get a training session with computed counts | ProjectManager, Trainer, OperationsLead |
| POST | /api/v1/training-sessions/{tsid}/start | Start a scheduled session within its window | Trainer |
| POST | /api/v1/training-sessions/{tsid}/complete | Complete a session; no reserved enrollments may remain | Trainer |
| POST | /api/v1/training-sessions/{tsid}/cancel | Cancel a scheduled session; reserved enrollments cascade to cancelled | Trainer |
| POST | /api/v1/staff | Register a staff member | Trainer |
| GET | /api/v1/staff | List staff members | ProjectManager, Trainer, OperationsLead |
| GET | /api/v1/staff/{smid} | Get a staff member | ProjectManager, Trainer, OperationsLead |
| POST | /api/v1/enrollments | Enroll a staff member in a session | Trainer |
| GET | /api/v1/enrollments | List enrollments of a session | ProjectManager, Trainer |
| POST | /api/v1/enrollments/{eid}/attend | Mark an enrollment attended; may auto-complete the session | Trainer |
| POST | /api/v1/enrollments/{eid}/no-show | Mark an enrollment no-show | Trainer |
| POST | /api/v1/enrollments/{eid}/cancel | Cancel a reserved enrollment | Trainer |
| POST | /api/v1/customer-comms | Create a customer communication for an account | CommunicationsOfficer |
| GET | /api/v1/customer-comms | List customer communications | ProjectManager, CommunicationsOfficer |
| GET | /api/v1/customer-comms/{cid} | Get a customer communication | ProjectManager, CommunicationsOfficer |
| POST | /api/v1/customer-comms/{cid}/schedule | Schedule a draft comm (OCC-guarded on project version) | CommunicationsOfficer |
| POST | /api/v1/customer-comms/{cid}/send | Send a scheduled comm once its scheduled send time is reached | CommunicationsOfficer |
| POST | /api/v1/customer-comms/{cid}/deliver | Mark a sent comm delivered | CommunicationsOfficer |
| POST | /api/v1/customer-comms/{cid}/fail | Mark a sent comm failed | CommunicationsOfficer |
| POST | /api/v1/customer-comms/{cid}/resend | Resend a failed comm; applies wave backoff | CommunicationsOfficer |
| POST | /api/v1/customer-comms/{cid}/cancel | Cancel a draft or scheduled comm | CommunicationsOfficer |
| POST | /api/v1/defects | Report a post-conversion defect | ProjectManager, OperationsLead |
| GET | /api/v1/defects | List defects | ProjectManager, OperationsLead, VendorTriageLead, FinanceController |
| GET | /api/v1/defects/{did} | Get a defect | ProjectManager, OperationsLead, VendorTriageLead, FinanceController |
| POST | /api/v1/defects/{did}/triage | Triage an open defect (reporter may not triage) | VendorTriageLead |
| POST | /api/v1/defects/{did}/start-fix | Move a triaged defect into fix | VendorTriageLead |
| POST | /api/v1/defects/{did}/reject-fix | Reject the fix; defect returns to open retaining its priority | VendorTriageLead |
| POST | /api/v1/defects/{did}/resolve | Resolve a defect; stamps resolution, computes credit eligibility, cascades the linked system | VendorTriageLead |
| POST | /api/v1/defects/{did}/reopen | Reopen a resolved defect; disputes open credit claims referencing it | ProjectManager |
| POST | /api/v1/defects/{did}/close | Close a resolved defect not referenced by any open claim | ProjectManager |
| POST | /api/v1/service-credits | Create a monthly vendor service credit claim over eligible defects | FinanceController |
| GET | /api/v1/service-credits | List service credit claims | ProjectManager, VendorTriageLead, FinanceController |
| GET | /api/v1/service-credits/{scid} | Get a service credit claim | ProjectManager, VendorTriageLead, FinanceController |
| POST | /api/v1/service-credits/{scid}/approve | Approve an open claim | FinanceController |
| POST | /api/v1/service-credits/{scid}/pay | Pay an approved claim (approver may not pay) | FinanceController |
| POST | /api/v1/service-credits/{scid}/dispute | Dispute an open or approved claim | VendorTriageLead |
| POST | /api/v1/service-credits/{scid}/reopen | Reopen a disputed claim; recomputes the credit | FinanceController |
| POST | /api/v1/service-credits/{scid}/reject | Reject an open claim whose defects lost eligibility | FinanceController |
| GET | /api/v1/plans | List cutover plans of a project (zero or one) | ProjectManager, ConversionEngineer, OperationsLead |
| GET | /api/v1/plans/{pid} | Get a cutover plan | ProjectManager, ConversionEngineer, OperationsLead |
| POST | /api/v1/tasks | Add a task to a draft cutover plan | ProjectManager |
| GET | /api/v1/tasks | List tasks of a plan | ProjectManager, ConversionEngineer, OperationsLead |
| GET | /api/v1/tasks/{tid} | Get a cutover task | ProjectManager, ConversionEngineer, OperationsLead |
| POST | /api/v1/plans/{pid}/schedule | Validate window geometry and schedule the plan | ProjectManager |
| POST | /api/v1/plans/{pid}/go | Declare go at or after the checkpoint | ProjectManager |
| POST | /api/v1/plans/{pid}/rollback | Roll back the cutover: tasks skipped, accounts blocked, project back to mock conversion | ProjectManager |
| POST | /api/v1/tasks/{tid}/start | Start a pending task within its window after its dependency completed | ConversionEngineer, OperationsLead |
| POST | /api/v1/tasks/{tid}/complete | Complete a running task (window end plus thirty-minute grace) | ConversionEngineer, OperationsLead |
| POST | /api/v1/tasks/{tid}/fail | Fail a running task | ConversionEngineer, OperationsLead |
| GET | /api/v1/product-types/{ptid}/accounts | List accounts governed by a product type | ProjectManager, ConversionEngineer |
| GET | /api/v1/gl-accounts/{gid}/accounts | List accounts mapped to a GL account | ProjectManager, ConversionEngineer, FinanceController |
| GET | /api/v1/staff/{id}/enrollments | List enrollments of a staff member across sessions | ProjectManager, Trainer |
| GET | /api/v1/accounts/{aid}/customer-comms | List customer communications for an account | ProjectManager, CommunicationsOfficer |
| GET | /api/v1/ancillary-systems/{sid}/defects | List defects linked to an ancillary system | ProjectManager, OperationsLead, VendorTriageLead |
| GET | /api/v1/tasks/{tid}/dependents | List tasks that depend on a given task | ProjectManager, ConversionEngineer, OperationsLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_OUTSIDE_WINDOW | 409 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_INVARIANT_VIOLATION | 422 |
| ERR_DUPLICATE | 409 |
| ERR_CREDIT_INELIGIBLE | 422 |
| ERR_PHASE_GATE | 409 |
| ERR_FROZEN | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STALE_VERSION | 412 |
| ERR_RUN_IN_PROGRESS | 409 |
| ERR_SESSION_OVERLAP | 409 |
| ERR_FREEZE_CHANNEL_BUSY | 409 |
