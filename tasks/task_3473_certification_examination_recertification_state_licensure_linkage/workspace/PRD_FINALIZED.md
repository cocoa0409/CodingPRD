# EMS Certification Registry API — Product Requirements Document

## 1. Introduction

Emergency medical services rest on a two-layer credentialing structure: a national registry certifies that a clinician has completed an accredited education program and passed standardized cognitive and psychomotor examinations, and each state then decides how that national certification maps onto a license to practice within its borders. This document specifies the EMS Certification Registry API, the system of record for that lifecycle. It governs candidate registration, education-program accreditation, completion attestation, adaptive cognitive examination delivery with retake budgeting, psychomotor skill verification, national certification issuance, continuing-education recertification with audit sampling, lapsed-certification reentry, state licensure linkage across divergent adoption models, and disciplinary due process whose sanctions cascade across every credential the subject holds.

The design is compliance-first. Every decision the registry records — an approval, a denial, an audit verdict, a sanction — must be reproducible from stored evidence, so the system pins policy and fee snapshots at application-creation time, evaluates validations in a fixed priority order, advances time through a single deterministic logical clock rather than the wall clock, and applies every cascade in a published hop order. Seven operator roles act under strict segregation of duties: the director who attests a candidate's education may not evaluate that same candidate's psychomotor skills, and the official who opens a disciplinary case may not hear it. State adoption itself varies — some states accept the national certification outright, some administer their own examination, some accept either — and the API links national credentials to state licensure applications without ever conflating the two authorities.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and contracts that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than candidate self-registration must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request to any authenticated endpoint that arrives with either header missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The single header-exempt endpoint is candidate self-registration, which is open to the unauthenticated `Anonymous` role and returns the newly minted Candidate record whose `id` becomes that caller's `X-User-ID` on all subsequent calls.

The system recognizes seven roles, spelled exactly as follows: `Anonymous`, `Candidate`, `ProgramDirector`, `StateOfficial`, `RegistryAdmin`, `ExamProctor`, and `HearingOfficer`. Access to every operation is restricted by role, and a caller whose role is not on an endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity — what `X-User-ID` refers to — differs by role, and each role's binding is fixed:

- When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting Candidate, minted at self-registration; ownership checks on any resource that references a Candidate compare the resource's candidate foreign key to `X-User-ID`. A Candidate acts only on their own exam applications, exam attempts, recertification applications, reentry applications, and license applications, and may respond to or appeal only a disciplinary case in which they are the subject.
- When `X-User-Role` is `ProgramDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted user entity. On program-scoped attestations the server compares it against the `director_user_id` recorded on the target education program: a completion attestation naming a program whose `director_user_id` differs from the caller's `X-User-ID` is rejected with `ERR_FORBIDDEN_ROLE`.
- When `X-User-Role` is `StateOfficial`, `RegistryAdmin`, or `ExamProctor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `opened_by_user_id` on a disciplinary case or `evaluator_user_id` on a psychomotor verification) but never compares it to any entity's `id`.
- When `X-User-Role` is `HearingOfficer`, `X-User-ID` is likewise opaque, with one segregation constraint: it must differ from the `opened_by_user_id` of the disciplinary case being scheduled or decided.
- When `X-User-Role` is `Anonymous`, no identity headers are expected at all.

Segregation of duties is enforced wherever a workflow has two sides: the evaluator on a program-administered psychomotor verification must differ from the director who attested the candidate's completion record, and the hearing officer must differ from the case opener; violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). All six authenticated roles may call any read (GET) endpoint; write access is per-endpoint as narrated in §3 and summarized in §4.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, and the `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every operational resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, whether client-driven, sweep-driven, or cascade-driven.
- `version` — a system-managed integer that increments by one on every mutation of the resource; it is the token the optimistic-concurrency guards of §2.7 compare against.

The two configuration resources are the exception. A level definition and a state adoption policy are configuration rows that carry only `id` and `created_at`; both `updated_at` and `version` are absent on those two resources.

### 2.5. The Logical Clock and the Deterministic Time Sweep

All time-dependent behavior in the registry — validity windows, deadlines, expirations, sweeps — reads a single logical clock, never wall-clock time. The clock is driven through an administrative endpoint mounted outside the `/registry` prefix, `POST /_clock/set_current_utc`, restricted to `RegistryAdmin`. Before any call, the logical clock stands at exactly 2026-09-01T00:00:00Z, and it must never fall back to wall-clock time. A call carries `to_iso8601` and advances the clock to that instant. The clock is monotonic: a request whose target lies earlier than the current logical time is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409).

Every advance runs a deterministic sweep in this pinned order:

1. Authorizations to test still `ISSUED` whose `expires_on` is earlier than now become `EXPIRED`.
2. Attempts still `SCHEDULED` whose `scheduled_end` is earlier than now, and that were never delivered, become `NO_SHOW`, and their authorization becomes `CONSUMED`.
3. Certifications `ACTIVE` whose `expires_on` is earlier than now become `LAPSED`.
4. Certifications `LAPSED` whose `lapse_deadline` is earlier than now become `EXPIRED`.
5. Certifications `SUSPENDED` whose `suspension_ends` is at or before now are lifted — returning to `ACTIVE` when their `expires_on` is at or after now, otherwise becoming `LAPSED`.
6. Disciplinary cases in `NOTICE_ISSUED` whose `response_deadline` has passed advance to `UNDER_REVIEW`.
7. Disciplinary cases in `DECIDED` whose `appeal_deadline` has passed enter `FINAL`, and the sanction cascade of §3.9 applies.

The clock response reports the new logical time as `current_utc` together with per-step counters: `att_expired_count`, `attempts_no_show_count`, `certifications_lapsed_count`, `certifications_expired_count`, `suspensions_lifted_count`, `cases_advanced_count`, and `cases_finalized_count`.

### 2.6. Calendar Arithmetic, Units, and Rounding

Every validity window and extension in the system is expressed in calendar months through a single primitive: advancing a timestamp by a number of calendar months preserves the day-of-month, and when the target month lacks that day the result clamps to the target month's last day; time-of-day and the UTC zone are preserved. Deadline arithmetic is in calendar days, also in UTC. Where a boundary is described as inclusive, an instant exactly on the boundary satisfies it.

Hour quantities — remedial education and continuing education — are recorded in half-hour increments and compared exactly. Attempt-slot, delivery-window, and sweep comparisons are made at second precision; completion and examination dates are compared at day precision.

Two rounding rules are contractual. The cognitive examination's final ability estimate is stored rounded half up to four decimal places, while every pass/fail comparison is made on the unrounded value (§3.4). All money is integer cents, and the registry's licensure revenue share is rounded half up per fee line before summing (§3.8).

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control on a parent entity's `version`; the guard field is mandatory on exactly these three operations and appears on no other endpoint:

- Opening a recertification draft requires `expected_certification_version`, carrying the `version` of the target certification as the client last observed it. When the certification's version has advanced since — for example because another writer opened a draft (which supersedes the previous draft) or a renewal was applied — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of the certification is stale.
- Creating a state licensure application on the national-certification path likewise requires `expected_certification_version` matching the cited certification's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since licensure must be pinned to the certification state the client actually observed — the credential may have been renewed, suspended, or revoked in between.
- Recording a disciplinary hearing decision requires `expected_case_version` matching the case's current `version`; a mismatch — an intermediate mutation such as an appeal filing or a rehearing reschedule has advanced the case — is rejected with `ERR_STALE_VERSION` (HTTP 412), so a decision is never recorded against a stage the officer did not observe.

The concurrency check is evaluated immediately after existence checks and before any state-machine precondition. Endpoints not named above take no version field.

### 2.8. Validation Order and Error Precedence

When several checks could reject the same request, the system evaluates them in a fixed tier order and reports the first failure:

1. **Headers.** `X-User-ID` and `X-User-Role` must be present and non-empty on every endpoint except candidate self-registration (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role and ownership.** The caller's role is authorized for the endpoint and entity-backed ownership holds (`ERR_FORBIDDEN_ROLE`).
3. **Request shape.** Required fields are present, types match, enum values are valid, station lists are non-empty, a scheduling window's end is strictly after its start, examination dates are not in the future, hour quantities are positive, and a response-delivery payload carries no more than twelve item responses (`ERR_INVALID_REQUEST`). On the continuing-education entry endpoint specifically, one further shape check sits between this tier and existence: hours must be a positive multiple of one half hour (`ERR_CE_HOURS_INCREMENT`).
4. **Existence.** Path identifiers must exist, validated left to right so that the first missing identifier in the path is the one reported, and every record referenced in the body must exist (`ERR_NOT_FOUND`).
5. **Optimistic concurrency.** Any `expected_*_version` field must equal the parent entity's current `version` (`ERR_STALE_VERSION`) — evaluated immediately after existence, before any state precondition.
6. **State preconditions.** The target resource's current state must allow the requested transition: the generic `ERR_INVALID_STATE`, or the specific state error for the endpoint — `ERR_COMPLETION_NOT_PENDING`, `ERR_APPLICATION_NOT_SUBMITTED`, `ERR_APPLICATION_NOT_DENIED`, `ERR_ATT_NOT_ISSUABLE`, `ERR_ATTEMPT_NOT_SCHEDULED`, `ERR_RECERT_NOT_DRAFT`, `ERR_RECERT_NOT_SUBMITTED`, `ERR_RECERT_NOT_AUDIT_PENDING`, `ERR_RECERT_NOT_REOPENABLE`, `ERR_CERTIFICATION_NOT_ACTIVE`, `ERR_CERTIFICATION_NOT_LAPSED`, `ERR_LICENSE_NOT_ACTIONABLE`, `ERR_LICENSE_NOT_AWAITING_RESPONSE`, `ERR_PSYCHOMOTOR_NOT_SUBMITTED`, `ERR_CASE_STAGE_MISMATCH`, or `ERR_REENTRY_NOT_SUBMITTED`.
7. **Compliance gates**, evaluated in this order: the candidate is not `BARRED` (`ERR_PERMANENTLY_BARRED`); no disciplinary hold blocks new applications (`ERR_DISCIPLINARY_HOLD`); the education program's accreditation at the completion date was acceptable (`ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION`); segregation of duties is respected (`ERR_SEGREGATION_OF_DUTIES`).
8. **Cross-record consistency.** All referenced records agree on candidate and level; a certification's level is accepted by the target state; a cited state examination is usable (`ERR_CROSS_REFERENCE_MISMATCH`, `ERR_LEVEL_NOT_ACCEPTED_IN_STATE`, `ERR_STATE_EXAM_NOT_PASSING`).
9. **Temporal windows**, evaluated in the order these identifiers are listed: education validity (`ERR_EDUCATION_VALIDITY_EXPIRED`), delivery window (`ERR_DELIVERY_WINDOW_NOT_OPEN`), retake wait (`ERR_RETAKE_WAIT_ACTIVE`), recertification window (`ERR_RECERT_WINDOW_NOT_OPEN`), credential freshness (`ERR_CREDENTIAL_STALE`), CE entry inside the cycle (`ERR_CE_ENTRY_OUTSIDE_CYCLE`), reentry availability (`ERR_REENTRY_NOT_AVAILABLE`), clock monotonicity (`ERR_CLOCK_REGRESSION`).
10. **Uniqueness and occupation.** One scheduled attempt window per candidate; one active certification per candidate and level; no overlapping verified psychomotor window; course codes unique per application; one policy per state; level codes unique; at most one in-flight recertification per certification (`ERR_ATTEMPT_SLOT_OVERLAP`, `ERR_DUPLICATE_ACTIVE_CERTIFICATION`, `ERR_ACTIVE_VERIFICATION_EXISTS`, `ERR_DUPLICATE_COURSE_IN_CYCLE`, `ERR_DUPLICATE_STATE_POLICY`, `ERR_DUPLICATE_LEVEL_CODE`, `ERR_RECERT_IN_PROGRESS_CONFLICT`).
11. **Quota and sufficiency.** Attempt budget and the remedial gate at exam-application approval; continuing-education sufficiency at recertification submission; the jurisprudence attestation at license creation (`ERR_ATTEMPT_LIMIT_REACHED`, `ERR_REMEDIAL_REQUIRED`, `ERR_CE_COMPONENT_SHORTFALL`, `ERR_CE_TOTAL_SHORTFALL`, `ERR_JURISPRUDENCE_REQUIRED`).

### 2.9. Snapshots, Cascades, and Hop Discipline

Two habits keep the registry auditable. The first is **snapshots**: whenever a later decision must be reproducible, its inputs are pinned at creation — a licensure application pins the adopting policy's mode, fee lines, and revenue share; a recertification application pins its cycle window and the certification's expiry; an exam application pins its fee. Later edits to the source configuration never retroactively move an in-flight application.

The second is **ordered cascades**. Several events — program revocation, disciplinary finalization, completion-record invalidation, attempt voiding — fan out across certifications, applications, authorizations, and state exam records. Every cascade in this system executes its hops in a published order, and each hop computes its target set only after the previous hop has landed, so a certification revoked mid-cascade still propagates to the license applications citing it within the same event. Licensure denials inside cascades are always credential-mediated: an application is denied because a certification it cites was revoked, never as a blanket effect. Every mutation, whether client-driven, sweep-driven, or cascade-driven, refreshes the mutated resource's `updated_at` and increments its `version` on the resources that carry those fields.

## 3. Business Logic & Workflows

### 3.1. Registry Configuration: Levels and State Adoption Policies

Before any candidate activity, a `RegistryAdmin` configures the registry's two reference tables. Each **certification level** is defined with a unique `code` — one of `EMR`, `EMT`, `AEMT`, or `PARAMEDIC` — plus a human-readable `display_name` and a `scope_summary` describing the level's distinct scope of practice. The level record also carries the examination and recertification policy constants: the `cognitive_cut_score`, the adaptive-test pass threshold expressed as a value between zero and one; the continuing-education structure of the national model, `ce_total_hours` together with the component minimums `ce_national_min_hours`, `ce_local_min_hours`, and `ce_individual_min_hours`; the flat `hourly_model_total_hours` used under the hourly model; the `remedial_hours_required` that gate later cognitive attempts; and the `refresher_hours_required` of the reentry pathway. Two recorded fees complete the record: `initial_application_fee_cents` for a first exam application at the level and `recert_application_fee_cents` for a recertification application at the level. Defining a level whose `code` already exists is rejected with `ERR_DUPLICATE_LEVEL_CODE`.

Each **state adoption policy** records how one state links national certification to licensure. Keyed by a unique two-letter `state_code` — a duplicate is rejected with `ERR_DUPLICATE_STATE_POLICY` — the policy declares an `adoption_mode` of `NREMT_ACCEPTED`, `STATE_EXAM`, or `HYBRID`; optionally lists the `accepted_level_codes` the state accepts through the national-certification path (relevant to `NREMT_ACCEPTED` and `HYBRID` states); states whether a `jurisprudence_exam_required` attestation is demanded, defaulting to false; and sets the fee schedule: `base_license_fee_cents`, an optional `national_verification_surcharge_cents` applied on the national-certification path (default zero), an optional `state_exam_fee_cents` applied on the state-exam path (default zero), and the registry's `registry_share_bps` revenue share in basis points, defaulting to 1500 — that is, fifteen percent. Both configuration resources are readable by every authenticated role; level definitions can be listed with a `code` filter and policies with a `state_code` filter.

### 3.2. Candidates, Education Programs, and Accreditation

Anyone may self-register as a **candidate** with a `full_name` and an `email`; the record starts in `REGISTERED` status, and its `id` becomes the caller's identity for everything that follows. The record also exposes `disciplinary_hold`, a live-computed flag that is false at registration and true whenever any disciplinary case against the candidate that has not yet reached `FINAL` carries the interim action `HOLD_NEW_APPLICATIONS`. A candidate whose `status` has become `BARRED` — the terminal consequence of a finalized permanent-bar sanction — can no longer open exam, recertification, reentry, or license applications, each attempt rejected with `ERR_PERMANENTLY_BARRED`.

A `RegistryAdmin` registers each **education program** with a `name`, the `level_id` of the level it teaches, and the `director_user_id` of the program director accountable for its attestations. A program begins `ACCREDITED`, and that initial status seeds the first entry of its `accreditation_history` — an append-only log whose entry zero records the initial accreditation with an `effective_date` equal to the program's creation instant. Thereafter the administrator records each accreditation change as an event carrying `to_status`, `effective_date`, and `reason`; the history entry is appended and the program's `accreditation_status` follows. The permitted moves are `ACCREDITED` to `PROVISIONAL`, `SUSPENDED`, or `REVOKED`; `PROVISIONAL` back to `ACCREDITED` or onward to `SUSPENDED` or `REVOKED`; and `SUSPENDED` back to `ACCREDITED` or onward to `REVOKED`. `REVOKED` is terminal.

Revoking a program's accreditation fires the program-revocation cascade in five ordered hops, each computing its targets after the previous hop lands. First, the program's completion records still `PENDING_VERIFICATION` move to `REJECTED`. Second, its `VERIFIED` completion records whose `completion_date` falls strictly after the revocation's `effective_date` become `INVALIDATED`. Third, exam applications still `SUBMITTED` that cite a record invalidated in the second hop are `DENIED`, with the denial reason recording the program revocation. Fourth, certifications whose `basis_completion_record_id` was invalidated in the second hop and that stand `ACTIVE`, `SUSPENDED`, or `LAPSED` become `REVOKED`, each preserving its prior status in `pre_sanction_status`. Fifth, license applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` that cite a certification revoked in the fourth hop are `DENIED`. The same cascade fires whether the program stood `ACCREDITED`, `PROVISIONAL`, or `SUSPENDED` immediately before revocation.

### 3.3. Education Attestation and the Completion-Record Lifecycle

A `ProgramDirector` attests that a candidate completed their program by creating a **program completion record** naming the `candidate_id`, the `program_id`, and the `completion_date`. The caller's identity must match the program's `director_user_id` (`ERR_FORBIDDEN_ROLE`), and the program's accreditation status effective at the completion date — read from the accreditation history by each entry's `effective_date` — must have been `ACCREDITED` or `PROVISIONAL`, otherwise the attestation is rejected with `ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION`. The record is born `PENDING_VERIFICATION`, stamped with the attesting director in `created_by_user_id`.

A `RegistryAdmin` then decides the record; the decision payload carries an `outcome` and an optional `reason`. A verify decision requires the record to still be `PENDING_VERIFICATION` (`ERR_COMPLETION_NOT_PENDING`) and re-checks the accreditation-at-completion condition; on success the record becomes `VERIFIED` and `verified_at` is set to the decision instant. A reject decision requires only the pending state and ends the record `REJECTED`. Both `REJECTED` and `INVALIDATED` are terminal; `INVALIDATED` is reserved for once-verified records undone by a falsified-education case or by the program-revocation cascade. In the falsification case `invalidated_by_case_id` points at the responsible case, and the invalidation cascades exactly like the later hops of §3.2: exam applications still `SUBMITTED` that cite the record are `DENIED`, certifications whose `basis_completion_record_id` names the record and that stand `ACTIVE`, `SUSPENDED`, or `LAPSED` are `REVOKED`, and license applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` citing those certifications are `DENIED`. Completion-record lists may be filtered by `candidate_id`, `program_id`, `status`, or `invalidated_by_case_id`.

The record doubles as the **attempt-budget basis** for the cognitive examination. Its `within_validity_window` flag reports the date half of educational validity: the completion date is on or before the current instant, and the current instant is on or before the date twenty-four calendar months after the completion date — both ends inclusive. Educational validity in the full sense, which approval and issuance check, additionally requires the accreditation-at-completion leg above. Two live counters summarize the budget: `attempts_consumed`, the number of delivered attempts booked against this basis (only `SCORED_PASS` and `SCORED_FAIL` count; `NO_SHOW` and `VOIDED` never do), and `attempts_remaining`, the hard cap of six minus that count. A freshly verified record starts a fresh basis: attempts booked against earlier records do not carry over.

### 3.4. The Cognitive Examination: Applications, Authorizations, and Adaptive Delivery

A `Candidate` applies for the cognitive examination at a level by naming the `level_id` and the `completion_record_id` that grounds eligibility. The application is born `SUBMITTED`, its `application_fee_cents` snapshotting the level's `initial_application_fee_cents` at creation and its `candidate_id` fixed from the caller's identity. Creation is refused for a barred candidate (`ERR_PERMANENTLY_BARRED`) or one under a disciplinary hold (`ERR_DISCIPLINARY_HOLD`), and every referenced record must exist (`ERR_NOT_FOUND`).

Approval by a `RegistryAdmin` runs the full gate set in the precedence order of §2.8. The application must still be `SUBMITTED` (`ERR_APPLICATION_NOT_SUBMITTED`). The compliance tier then requires that the candidate is neither `BARRED` (`ERR_PERMANENTLY_BARRED`) nor under a hold (`ERR_DISCIPLINARY_HOLD`), and that the program stood `ACCREDITED` or `PROVISIONAL` at the completion date (`ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION`). The cited record must belong to this candidate and teach this level (`ERR_CROSS_REFERENCE_MISMATCH`), and it must be `VERIFIED` and inside its twenty-four-month validity window at decision time (`ERR_EDUCATION_VALIDITY_EXPIRED`). Two quota gates close the review: the basis must have consumed fewer than six attempts (`ERR_ATTEMPT_LIMIT_REACHED`), and once three or more attempts have been consumed on the basis, a **remedial education record** must exist for this candidate and level with `hours` of at least the level's `remedial_hours_required` and a `completed_date` strictly after the delivered date of the third failed attempt on the basis (`ERR_REMEDIAL_REQUIRED`). Program directors attest remedial education with `candidate_id`, `level_id`, `hours` (positive, in half-hour increments), `completed_date`, and `provider_name`; the record is verified at creation and carries the attester in `attested_by_user_id`. Remedial lists may be filtered by `candidate_id` or `level_id`.

Approval mints an **authorization to test**: `issued_on` at the approval instant, `expires_on` ninety calendar days later, status `ISSUED`, with the application's `att_id` pointing at it. Denial instead records a `denial_reason` and stamps `decided_at`. Denial is not the end of the road: the owning candidate may resubmit a `DENIED` application — any other state draws `ERR_APPLICATION_NOT_DENIED`, any other caller `ERR_FORBIDDEN_ROLE` — optionally swapping in a different `completion_record_id`. Resubmission returns the application to `SUBMITTED`, clears the `denial_reason`, and increments `resubmission_count` (which starts at zero on creation), and the full approval gate set re-runs on the next decision.

With an `ISSUED` authorization in hand, the candidate schedules a **cognitive exam attempt** by naming the `att_id` and a delivery window from `scheduled_start` to `scheduled_end`. Scheduling is allowed only while the authorization is `ISSUED` and the scheduling instant is on or before its `expires_on`, and only while no prior attempt already references it — one attempt per authorization — with violations rejected as `ERR_ATT_NOT_ISSUABLE`. The window's end must be strictly after its start (`ERR_INVALID_REQUEST`). If at least one attempt has already been consumed on the basis, the new window's start must fall at least fifteen days after the most recent scored attempt's `delivered_at` — equality allowed — otherwise `ERR_RETAKE_WAIT_ACTIVE`. A candidate may also hold at most one `SCHEDULED` attempt covering any instant: a new window conflicts with an existing scheduled window when the existing start is strictly before the new end and the new start is strictly before the existing end — a half-open intersection, so touching endpoints, the new window beginning exactly when the old one ends or ending exactly when the old one begins, do not conflict — and a conflict is rejected with `ERR_ATTEMPT_SLOT_OVERLAP`. Only `SCHEDULED` attempts occupy time; scored, no-show, and voided attempts leave no occupation. A scheduled attempt records its `attempt_number`, one more than the basis's consumed count at scheduling, along with the `basis_completion_record_id` it draws down, and the authorization notes the booking in its `attempt_id`. Attempt lists may be filtered by `candidate_id`, `att_id`, `level_id`, `basis_completion_record_id`, `status`, or `voided_by_case_id`; authorization lists by `candidate_id`, `exam_application_id`, or `status`.

Delivery is performed by an `ExamProctor`, who submits the attempt's `responses` — each entry carrying an `item_id`, a difficulty `difficulty_b` between 0.1 and 1.0, and a `correct` flag, in delivery order. The attempt must still be `SCHEDULED` (`ERR_ATTEMPT_NOT_SCHEDULED`), and the delivery instant must fall inside the window, both bounds inclusive (`ERR_DELIVERY_WINDOW_NOT_OPEN`); a payload of more than twelve responses is rejected outright at input validation (`ERR_INVALID_REQUEST`).

The adaptive engine then scores the submission. Responses are processed in delivery order, and after each prefix of items the engine maintains a difficulty-weighted accuracy: the sum of `difficulty_b` over the correct answers in the prefix divided by the sum of `difficulty_b` over all items in the prefix. Each prefix also carries a standard error — the square root of the accuracy multiplied by one minus the accuracy and then divided by the prefix length — which is defined as zero whenever the accuracy is exactly zero or exactly one. Once at least six items have been delivered, the engine reports a `provisional_outcome`: `PASS` when the weighted accuracy at exactly six items meets or exceeds the level's `cognitive_cut_score`, otherwise `FAIL`. The provisional outcome is a bare point estimate with no confidence qualification, and on identical response data it can diverge from the final outcome — a borderline estimate can be dragged across the cut in either direction by later items.

The final determination evaluates prefixes from six items onward through the whole submission. At each prefix it forms a lower confidence bound by subtracting 1.645 standard errors from the weighted accuracy and an upper confidence bound by adding the same quantity. The moment the lower bound meets or exceeds the cut score, the attempt stops and `final_outcome` is `PASS`; the moment the upper bound falls strictly below the cut score, the attempt stops and `final_outcome` is `FAIL`; in either case `items_delivered_count` records the prefix length at which the stop fired. When neither bound ever fires and at least six items were delivered, `final_outcome` is `PASS` exactly when the final weighted accuracy meets or exceeds the cut score, and `items_delivered_count` is the full response count. When fewer than six items were delivered in the first place, no provisional outcome and no band evaluation occur; the attempt is decided the same way on the final weighted accuracy, and `items_delivered_count` is the full response count. Every comparison uses the unrounded accuracy; the stored `theta_final` is the final weighted accuracy rounded half up to four decimal places.

The attempt then lands in `SCORED_PASS` or `SCORED_FAIL` according to `final_outcome`, `delivered_at` is stamped with the delivery instant, and the authorization becomes `CONSUMED`. Two later fates befall attempts without a proctor submission or with a tainted one. When the delivery window closes with no responses recorded, the sweep marks the attempt `NO_SHOW` and consumes the authorization — and a no-show never consumes attempt budget. When a disciplinary case finalizes with an exam-security violation implicating the attempt at sanction severity `SUSPENSION_12M` or higher, a scored attempt becomes `VOIDED`: `voided_by_case_id` is set, certifications whose `basis_attempt_id` names the attempt and that stand `ACTIVE`, `SUSPENDED`, or `LAPSED` are `REVOKED`, license applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` citing those certifications are `DENIED`, and — because `VOIDED` never counts toward `attempts_consumed` — the attempt budget is restored. The same compensation applies whether the voided attempt had passed or failed.

### 3.5. Psychomotor Verification and Certification Issuance

Psychomotor skills are examined out of band and documented into the registry by two kinds of submitters: a `ProgramDirector` for a program-administered examination, or a `StateOfficial` for a state-administered one. The submission names the `candidate_id`, the `level_id`, an `administered_by` of `PROGRAM` or `STATE`, a cross-referenced `completion_record_id`, the `exam_date` (which may not lie in the future), the individual `stations` — a non-empty list in which each entry pairs a `station_code` with a pass flag — and a `documentation_attached` flag recording whether supporting documents accompany the submission. A program-administered record must also name its `program_id`, and a state-administered record must not carry one; either mismatch is a shape error (`ERR_INVALID_REQUEST`). The cited completion record must belong to the same candidate and level (`ERR_CROSS_REFERENCE_MISMATCH`). Segregation of duties applies on the program path: the evaluator may not be the same user who attested the cited completion record (`ERR_SEGREGATION_OF_DUTIES`). The record is born `SUBMITTED` with the submitter preserved in `evaluator_user_id`, and lists may be filtered by `candidate_id`, `level_id`, `program_id`, `completion_record_id`, or `status`.

One containment rule protects the credential. Every `VERIFIED` psychomotor record for a candidate and level defines a half-open validity window running from the calendar date of its `verified_at` up to — but not including — the date twenty-four calendar months later. A new submission whose `exam_date` falls inside any such window is rejected with `ERR_ACTIVE_VERIFICATION_EXISTS`; an exam date exactly on the twenty-four-month boundary lies outside the window and is allowed. `SUBMITTED` and `REJECTED` records define no window.

A `RegistryAdmin` decides the submission. Verification requires the record to still be `SUBMITTED` (`ERR_PSYCHOMOTOR_NOT_SUBMITTED`), every station passed, and `documentation_attached` true — anything less is rejected with `ERR_PSYCHOMOTOR_REQUIREMENTS_UNMET`. A verified record stamps `verified_at` at the decision instant, opening its validity window; rejection ends the record `REJECTED`, and both outcomes are terminal.

With both examinations satisfied, a `RegistryAdmin` issues the **national certification** by explicitly referencing the basis records: the `candidate_id`, the `level_id`, the approved `exam_application_id`, the passing `attempt_id`, and the verified `psychomotor_id`. All references must agree on the candidate and the level (`ERR_CROSS_REFERENCE_MISMATCH`); the completion record behind the application must still sit inside its education-validity window (`ERR_EDUCATION_VALIDITY_EXPIRED`); and both examination credentials must be fresh — a cognitive pass delivered, or a psychomotor examination verified, more than twenty-four calendar months in the past is rejected with `ERR_CREDENTIAL_STALE`. One active credential per candidate and level is the rule: issuing while an `ACTIVE` certification already exists for the pair is rejected with `ERR_DUPLICATE_ACTIVE_CERTIFICATION`. The new certification is born `ACTIVE`, storing the basis trio as `basis_completion_record_id`, `basis_attempt_id`, and `basis_psychomotor_id`, with `issued_on` at the issuance instant, `expires_on` exactly twenty-four calendar months later, a `lapse_deadline` forty-eight calendar months beyond expiry, and `renewed_count` at zero. Certification lists may be filtered by `candidate_id`, `level_id`, `status`, any of the three basis references, or `revoked_by_case_id`.

### 3.6. Recertification: Continuing Education, the Credit Waterfall, and Audit

A certification is renewed through a **recertification application**. The owning candidate opens a draft against an `ACTIVE` certification by naming the `certification_id`, the continuing-education `model` — `NCCP` or `HOURLY` — and the concurrency token `expected_certification_version` described in §2.7. Opening the draft pins the cycle: `cycle_window_start` is captured as the instant twelve calendar months before the certification's current `expires_on`, and `cert_expires_on_at_creation` pins that expiry. Only one draft may exist for a certification: an existing `DRAFT` is automatically superseded to `SUPERSEDED` when a new draft opens, while another application for the same certification already `SUBMITTED` or `AUDIT_PENDING` blocks creation with `ERR_RECERT_IN_PROGRESS_CONFLICT`. Opening a draft is itself a mutation of the certification and increments its `version` by one — which is precisely what invalidates a second writer's pinned version. A barred candidate or one under a hold cannot open a draft (`ERR_PERMANENTLY_BARRED`, `ERR_DISCIPLINARY_HOLD`).

While the application is `DRAFT`, the candidate accumulates **continuing-education entries**, one per course, each naming a `component` of `NATIONAL`, `LOCAL`, or `INDIVIDUAL`; the `hours` earned, a positive multiple of one half hour (`ERR_CE_HOURS_INCREMENT`); a `delivery_method` of `DISTRIBUTED` or `IN_PERSON`; a `course_code` unique within the application — a repeat is rejected with `ERR_DUPLICATE_COURSE_IN_CYCLE`; the `course_date`; and the `provider_name`. The course date must fall inside the pinned cycle window, from `cycle_window_start` through `cert_expires_on_at_creation` inclusive (`ERR_CE_ENTRY_OUTSIDE_CYCLE`). Entries are born `RECORDED` and linked to their parent through `recert_application_id`. Only the draft's owner may add entries, and only to a draft — adding to an application in any other state is rejected with `ERR_RECERT_NOT_DRAFT`.

Submitting the portfolio re-checks the draft state and ownership, requires the submission instant to lie inside the pinned window (`ERR_RECERT_WINDOW_NOT_OPEN`), and requires the certification to still be `ACTIVE` (`ERR_CERTIFICATION_NOT_ACTIVE`). The credited hours are then computed by the **credit waterfall** over the eligible entries — those `RECORDED` at submission whose `course_date` sits inside the cycle window. Per component, distance learning is capped: the distributed-hours cap for a component is the level's minimum for that component multiplied by one half and rounded up to the next whole hour, and the credited distributed hours are the smaller of the summed `DISTRIBUTED` hours in the component and that cap. A component's claimed hours are its credited distributed hours plus the full sum of its `IN_PERSON` hours. Spillover is then evaluated in pinned order — national first, then local, then individual: the national spill is the amount by which claimed national hours exceed `ce_national_min_hours` (zero when they do not), and the local spill is the amount by which claimed local hours exceed `ce_local_min_hours`. The stored results are `national_credited_hours`, the lesser of claimed national hours and the national minimum; `local_credited_hours`, the lesser of claimed local hours and the local minimum; `individual_credited_hours`, the lesser of claimed individual hours plus both spills and `ce_individual_min_hours`; and `total_credited_hours`, the sum of the three credited figures.

Sufficiency under the `NCCP` model is checked in a fixed order, first failure wins: credited national hours against `ce_national_min_hours`, then local against `ce_local_min_hours`, then individual against `ce_individual_min_hours` — any shortfall rejected with `ERR_CE_COMPONENT_SHORTFALL` — and finally the credited total against `ce_total_hours` (`ERR_CE_TOTAL_SHORTFALL`). Under the `HOURLY` model the components and the spill are ignored: the credited total is the sum of all `IN_PERSON` hours on eligible entries plus the smaller of the total `DISTRIBUTED` hours and the level's `hourly_model_total_hours` halved and rounded up to a whole hour, and the portfolio is sufficient exactly when that total meets `hourly_model_total_hours`, otherwise `ERR_CE_TOTAL_SHORTFALL`. Identical entry sets can pass one model and fail the other.

Submission also runs the deterministic audit selector — no randomness anywhere. The application's `recert_seq` is one plus the number of other applications for the same certification that ever reached `SUBMITTED`, counting applications that stand in or passed through `SUBMITTED`, `AUDIT_PENDING`, `APPROVED`, `DENIED`, or `AUDIT_FAILED`, and never counting ones that stayed `DRAFT` or ended `SUPERSEDED`; the application being submitted never counts its own earlier submissions, so reopening and resubmitting the same application does not by itself advance its `recert_seq`. The flag `audit_selected` is true exactly when at least one of three predicates fires, and the fired predicates are recorded in `audit_reasons`: `SEQ_MOD` fires when `recert_seq` is an exact multiple of three; `PRIOR_AUDIT_FAILURE` fires when the same candidate has another application in `AUDIT_FAILED` whose `decided_at` lies within the sixty months before this submission; and `SINGLE_PROVIDER_CONCENTRATION` fires when the largest single-`provider_name` share of the application's entry hours reaches at least twenty hours. When nothing fires, the flag is false. A selected application enters `AUDIT_PENDING`; an unselected one enters `SUBMITTED`, and either way `recert_seq` and `submitted_at` are stamped.

A `RegistryAdmin` decides a non-audited application, which must stand `SUBMITTED` (`ERR_RECERT_NOT_SUBMITTED`), with the certification required to be `ACTIVE` at decision time (`ERR_CERTIFICATION_NOT_ACTIVE`). Approval extends the certification **anniversary-style**: the new `expires_on` is twenty-four calendar months after the pinned `cert_expires_on_at_creation`, never measured from the approval date, so approving early in the window loses no certified time; `lapse_deadline` is recomputed forty-eight calendar months beyond the new expiry, `renewed_count` increments by one, and the certification's `version` increments — all without any status transition, since the certification simply stays `ACTIVE`. Denial stamps `decided_at` and leaves the application `DENIED`.

An audited application instead waits for its audit outcome: the administrator records per-entry verdicts through `entry_verdicts`, moving each entry from `RECORDED` to `VERIFIED` or `REJECTED`, with a rejected entry keeping its `reject_reason`. The waterfall is then recomputed over the `VERIFIED` entries only. When sufficiency still holds — and the certification is still `ACTIVE` — the application is `APPROVED` with the same anniversary extension; when the surviving credits fall short, the application becomes `AUDIT_FAILED` and the certification is not extended. Recording an outcome against an application that is not `AUDIT_PENDING` is rejected with `ERR_RECERT_NOT_AUDIT_PENDING`.

Both `DENIED` and `AUDIT_FAILED` applications can be reopened by their owner — any other state draws `ERR_RECERT_NOT_REOPENABLE`, any other caller `ERR_FORBIDDEN_ROLE` — returning the application to `DRAFT`. A reopened application re-runs the full window check, waterfall, and audit selection on its next submission; entries already `REJECTED` stay rejected, and only `RECORDED` and `VERIFIED` entries count toward the recomputed credited hours. Application lists may be filtered by `candidate_id`, `certification_id`, or `status`.

### 3.7. Lapse and Reentry

A certification that passes its `expires_on` while `ACTIVE` lapses; one still `LAPSED` when its `lapse_deadline` — forty-eight calendar months after expiry — passes becomes `EXPIRED`, which is terminal. Between those two instants the reentry pathway is open. The candidate applies by naming the `certification_id`; the certification must stand `LAPSED` (`ERR_CERTIFICATION_NOT_LAPSED`), and the usual bar and hold gates apply (`ERR_PERMANENTLY_BARRED`, `ERR_DISCIPLINARY_HOLD`). The application computes `lapse_months_at_submission`, the whole calendar months between the certification's expiry and the submission instant, and assigns a `tier`: a submission on or before the date twelve calendar months after expiry receives `TIER_CE_ONLY`; one after that date but on or before the date twenty-four calendar months after expiry receives `TIER_REFRESHER`, with boundary equality always belonging to the lower tier. A submission later than twenty-four months after expiry is rejected with `ERR_REENTRY_NOT_AVAILABLE` — the pathway is closed and full re-examination is required instead. The application is born `SUBMITTED`.

Approval by a `RegistryAdmin` requires the application to be `SUBMITTED` (`ERR_REENTRY_NOT_SUBMITTED`) and the certification to still be `LAPSED` (`ERR_CERTIFICATION_NOT_LAPSED`), then checks the tier's evidence: a `TIER_CE_ONLY` application must claim `ce_makeup_hours_claimed` of at least the level's `ce_total_hours`, and a `TIER_REFRESHER` application must claim `refresher_hours_claimed` of at least the level's `refresher_hours_required`, with shortfalls rejected as `ERR_REENTRY_REQUIREMENTS_UNMET`. Approval reinstates the certification to `ACTIVE` with a **fresh** cycle: `expires_on` becomes twenty-four calendar months from the reinstatement instant — deliberately not anniversary-preserving, unlike recertification — and `lapse_deadline` is recomputed to match. Denial stamps `decided_at` and leaves the application `DENIED`. Reentry lists may be filtered by `candidate_id`, `certification_id`, or `status`.

### 3.8. State Licensure: Paths, Snapshots, and Fee Assessment

National certification and state licensure are linked but distinct authorities. A `StateOfficial` may register a state's **own examination** result — `candidate_id`, `state_code`, `level_id`, the `exam_date` (not in the future), the reported `score`, and the state's `passing_score` — and the record computes `passed` as the score meeting or exceeding the passing threshold. Such records are born `VALID`; a severe disciplinary finalization later voids them, setting `voided_by_case_id`, and `VOIDED` is terminal. Lists may be filtered by `candidate_id`, `state_code`, `level_id`, `status`, or `voided_by_case_id`.

A candidate applies for licensure by naming the target `state_code` and `level_id`, which resolve the state adoption policy at creation; the resolved policy is pinned onto the application as snapshots — `policy_id`, `adoption_mode_snapshot`, `registry_share_bps_snapshot`, and `fee_lines_snapshot` — so later policy edits never move an in-flight application. The application is born `UNDER_REVIEW`, with `jurisprudence_completed` defaulting to false when not supplied. The resolved `path` follows the pinned mode: `NREMT_ACCEPTED` requires a `certification_id`; `STATE_EXAM` requires a `state_exam_record_id`; `HYBRID` validates the national path first when a `certification_id` is present. A missing path-required reference is a shape error (`ERR_INVALID_REQUEST`).

On the national (`NREMT`) path, the cited certification must stand `ACTIVE` (`ERR_CERTIFICATION_NOT_ACTIVE`), its level's code must appear in the policy's `accepted_level_codes` (`ERR_LEVEL_NOT_ACCEPTED_IN_STATE`), and the concurrency field `expected_certification_version` must match the certification's current `version` (`ERR_STALE_VERSION`). The observed version is pinned as `certification_version_at_submission`, and creating the application itself increments the certification's `version` by one. On the state-exam (`STATE_EXAM`) path, the cited record must match the target state and level (`ERR_CROSS_REFERENCE_MISMATCH`) and must be usable — passing, still `VALID`, and not stale — with failures rejected as `ERR_STATE_EXAM_NOT_PASSING`; a state examination taken more than twenty-four calendar months before creation is rejected with `ERR_CREDENTIAL_STALE`. Where the policy requires the jurisprudence attestation, `jurisprudence_completed` must be true (`ERR_JURISPRUDENCE_REQUIRED`). Barred or held candidates cannot apply (`ERR_PERMANENTLY_BARRED`, `ERR_DISCIPLINARY_HOLD`).

A `StateOfficial` then decides applications standing `UNDER_REVIEW` (`ERR_LICENSE_NOT_ACTIONABLE`). A grant moves the application to `GRANTED`: it re-checks that a certification cited on the national path is still `ACTIVE` (`ERR_CERTIFICATION_NOT_ACTIVE`), assesses fees from the pinned snapshot, and stamps `granted_on`: the applicable lines are always the `base_license_fee_cents`, plus the `national_verification_surcharge_cents` on the national path or the `state_exam_fee_cents` on the state-exam path; `assessed_fee_cents` is their sum. The `registry_share_cents` is computed line by line — each applicable line multiplied by `registry_share_bps_snapshot`, divided by ten thousand, and rounded half up to a whole cent — and then summed from those per-line amounts. The rounding order is pinned: round each line first, then sum; summing first and rounding once is not the contract and diverges on half-cent lines. A denial records a `decision_reason`. An information request instead moves the application to `MORE_INFO_REQUIRED` with a `more_info_note`, and the owning candidate responds with a `response_note` — any other state draws `ERR_LICENSE_NOT_AWAITING_RESPONSE`, any other caller `ERR_FORBIDDEN_ROLE` — cycling the application back to `UNDER_REVIEW` with the policy snapshot still pinned. License applications also remain exposed to the credential cascades: whenever a cited certification is revoked while the application stands `UNDER_REVIEW` or `MORE_INFO_REQUIRED`, the application is `DENIED` — a credential-mediated denial, never a blanket one. Lists may be filtered by `candidate_id`, `state_code`, `level_id`, `certification_id`, `state_exam_record_id`, `policy_id`, or `status`.

### 3.9. Disciplinary Due Process and Sanction Cascades

A `RegistryAdmin` or a `StateOfficial` opens a **disciplinary case** against a candidate with a `violation_type` of `EXAM_SECURITY`, `FALSIFIED_EDUCATION`, or `CRIMINAL_CONDUCT`, a `description` of the allegation, an optional `interim_action` defaulting to `NONE`, and optional lists of `implicated_attempt_ids` and `implicated_completion_record_ids`. The case is born `OPENED`, recording the caller in `opened_by_user_id`. Interim actions bite immediately: `SUSPEND_CERTIFICATION` moves the subject's `ACTIVE` certifications to `SUSPENDED`, each storing its prior status in `pre_sanction_status`; `HOLD_NEW_APPLICATIONS` raises the candidate's live `disciplinary_hold`, blocking new exam, recertification, reentry, and license applications with `ERR_DISCIPLINARY_HOLD` for as long as any such case remains non-final.

Due process then proceeds stage by stage, each action requiring the exact preceding stage (`ERR_CASE_STAGE_MISMATCH` otherwise). The administrator issues the notice of allegations, moving the case to `NOTICE_ISSUED` and opening the response window: `response_deadline` is set thirty calendar days out, and a response arriving exactly at the deadline is accepted. The subject candidate may answer with a `response_text` — only the subject may respond, anyone else draws `ERR_FORBIDDEN_ROLE` — which closes the window early and moves the case to `UNDER_REVIEW`; if the deadline passes first, the sweep advances the case instead. A `HearingOfficer` then schedules the hearing — from `UNDER_REVIEW`, or from `REHEARING` on a remanded case — provided the officer's identity differs from the case opener's (`ERR_SEGREGATION_OF_DUTIES`); the case records the officer in `hearing_officer_user_id` and moves to `HEARING_SCHEDULED`.

The hearing decision is recorded by the officer with a `sanction_type` of `NONE`, `WARNING`, `SUSPENSION_12M`, `REVOCATION`, or `PERMANENT_BAR`, the `findings`, and the concurrency token `expected_case_version` (§2.7). The case becomes `DECIDED`, `decided_at` is stamped, an `appeal_deadline` opens thirty calendar days later with the boundary inclusive, and the case's `version` increments by one — but no sanction is applied yet. Within that window the subject may appeal with their `appeal_grounds`, moving the case to `APPEAL_PENDING`; because the sweep finalizes any `DECIDED` case whose appeal deadline has passed, a late appeal always observes `FINAL` and fails the stage check (`ERR_CASE_STAGE_MISMATCH`). An administrator then decides the appeal with an `outcome` and a `rationale`: `AFFIRMED` moves the case to `FINAL`, stamping `finalized_at` and firing the sanction cascade; `OVERTURNED` sends the case to `REHEARING`, clearing `sanction_type`, `findings`, `decided_at`, and `appeal_deadline` and incrementing `rehearing_count` (which starts at zero) by one. The loop `DECIDED` → `APPEAL_PENDING` → `REHEARING` → `HEARING_SCHEDULED` → `DECIDED` is the due-process rehearing cycle, and since no sanction has been applied at any point on it, overturning requires no compensation. A case whose appeal window lapses with no appeal filed is swept into `FINAL` in the same way.

Entry to `FINAL` applies the sanction cascade in a pinned order, each step computing its target set only after the previous step has landed:

1. A sanction of `NONE` or `WARNING` restores any certifications this case had interim-suspended — back to `ACTIVE`, or to `LAPSED` when their expiry has meanwhile passed.
2. `SUSPENSION_12M` moves the subject's `ACTIVE` or `SUSPENDED` certifications to `SUSPENDED` with `suspension_ends` set twelve calendar months after `finalized_at`.
3. `REVOCATION` or `PERMANENT_BAR` moves the subject's `ACTIVE`, `SUSPENDED`, or `LAPSED` certifications to `REVOKED` — each storing `pre_sanction_status` and, because the revocation is discipline-driven, `revoked_by_case_id`; the subject's still-`ISSUED` authorizations to test become `REVOKED`; their still-`SUBMITTED` exam applications are `DENIED`; license applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` citing a certification revoked by this event are `DENIED`; and the subject's `VALID` state exam records become `VOIDED`. `PERMANENT_BAR` additionally moves the candidate to `BARRED`.
4. A case whose violation is `FALSIFIED_EDUCATION`, finalized at severity `SUSPENSION_12M` or higher, moves each implicated completion record that stands `VERIFIED` to `INVALIDATED` with `invalidated_by_case_id` set, and then per record: citing exam applications still `SUBMITTED` are `DENIED`; certifications whose `basis_completion_record_id` names the record and that stand `ACTIVE`, `SUSPENDED`, or `LAPSED` are `REVOKED`; license applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` citing those certifications are `DENIED`.
5. A case whose violation is `EXAM_SECURITY`, finalized at severity `SUSPENSION_12M` or higher, moves each implicated attempt standing `SCORED_PASS` or `SCORED_FAIL` to `VOIDED`; certifications whose `basis_attempt_id` names a voided attempt and that stand `ACTIVE`, `SUSPENDED`, or `LAPSED` are `REVOKED`; license applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` citing those certifications are `DENIED`.

Because each numbered step computes its targets after the previous step lands, a certification revoked in the falsification or exam-security steps still propagates to the license applications citing it within the same finalization event. Case lists may be filtered by `subject_candidate_id`, `status`, `implicated_attempt_ids`, or `implicated_completion_record_ids`.

## 4. Endpoint Definitions

Creating a new, stand-alone resource returns `201 Created`; every other successful operation — decisions, transitions, submissions, responses, sweeps — returns `200 OK`. Rows marked "All authenticated roles" admit every role except `Anonymous`. The logical-clock endpoint is mounted outside the `/registry` prefix exactly as shown; all other paths are served under it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the deterministic sweep | RegistryAdmin |
| POST | `/registry/level-definitions` | Define a certification level with its cut score, CE minimums, and policy constants | RegistryAdmin |
| GET | `/registry/level-definitions` | List level definitions | All authenticated roles |
| POST | `/registry/state-adoption-policies` | Register a state's adoption posture and fee schedule | RegistryAdmin |
| GET | `/registry/state-adoption-policies` | List state adoption policies | All authenticated roles |
| POST | `/registry/candidates` | Self-register a candidate (header-exempt) | Anonymous |
| GET | `/registry/candidates/{id}` | Read a candidate, with `disciplinary_hold` computed live | All authenticated roles |
| POST | `/registry/education-programs` | Register an education program with its accountable director | RegistryAdmin |
| GET | `/registry/education-programs` | List education programs | All authenticated roles |
| GET | `/registry/education-programs/{id}` | Read an education program including its accreditation history | All authenticated roles |
| POST | `/registry/education-programs/{id}/accreditation-events` | Record an accreditation transition; revocation fires the program cascade | RegistryAdmin |
| POST | `/registry/program-completion-records` | Attest a candidate's completion of the caller's program | ProgramDirector |
| GET | `/registry/program-completion-records` | List completion records | All authenticated roles |
| GET | `/registry/program-completion-records/{id}` | Read a completion record, with attempt counters computed live | All authenticated roles |
| POST | `/registry/program-completion-records/{id}/decision` | Verify or reject a completion record | RegistryAdmin |
| POST | `/registry/exam-applications` | Apply for the cognitive examination on a completion record | Candidate |
| GET | `/registry/exam-applications` | List exam applications | All authenticated roles |
| GET | `/registry/exam-applications/{id}` | Read an exam application | All authenticated roles |
| POST | `/registry/exam-applications/{id}/decision` | Approve (minting the authorization) or deny an exam application | RegistryAdmin |
| POST | `/registry/exam-applications/{id}/resubmit` | Resubmit a denied application | Candidate |
| GET | `/registry/authorizations-to-test` | List authorizations to test | All authenticated roles |
| GET | `/registry/authorizations-to-test/{id}` | Read an authorization to test | All authenticated roles |
| POST | `/registry/cognitive-exam-attempts` | Schedule a cognitive attempt against an issued authorization | Candidate |
| GET | `/registry/cognitive-exam-attempts` | List cognitive exam attempts | All authenticated roles |
| GET | `/registry/cognitive-exam-attempts/{id}` | Read an attempt with its outcomes and final estimate | All authenticated roles |
| POST | `/registry/cognitive-exam-attempts/{id}/responses` | Deliver item responses and score the attempt | ExamProctor |
| POST | `/registry/remedial-education-records` | Attest completed remedial education | ProgramDirector |
| GET | `/registry/remedial-education-records` | List remedial education records | All authenticated roles |
| GET | `/registry/remedial-education-records/{id}` | Read a remedial education record | All authenticated roles |
| POST | `/registry/psychomotor-verifications` | Submit psychomotor verification documentation | ProgramDirector, StateOfficial |
| GET | `/registry/psychomotor-verifications` | List psychomotor verifications | All authenticated roles |
| GET | `/registry/psychomotor-verifications/{id}` | Read a psychomotor verification | All authenticated roles |
| POST | `/registry/psychomotor-verifications/{id}/decision` | Verify or reject psychomotor documentation | RegistryAdmin |
| POST | `/registry/certifications/issue` | Issue a national certification from explicitly referenced basis records | RegistryAdmin |
| GET | `/registry/certifications` | List certifications | All authenticated roles |
| GET | `/registry/certifications/{id}` | Read a certification | All authenticated roles |
| POST | `/registry/recert-applications` | Open a recertification draft (concurrency-guarded; supersedes an existing draft) | Candidate |
| GET | `/registry/recert-applications` | List recertification applications | All authenticated roles |
| GET | `/registry/recert-applications/{id}` | Read a recertification application, with credited hours computed live | All authenticated roles |
| POST | `/registry/recert-applications/{id}/ce-entries` | Add a continuing-education entry to a draft | Candidate |
| GET | `/registry/recert-applications/{id}/ce-entries` | List the CE entries of an application | All authenticated roles |
| POST | `/registry/recert-applications/{id}/submit` | Submit the CE portfolio; computes the waterfall and audit selection | Candidate |
| POST | `/registry/recert-applications/{id}/decision` | Approve (anniversary-style extension) or deny a non-audited submission | RegistryAdmin |
| POST | `/registry/recert-applications/{id}/audit-outcome` | Record per-entry audit verdicts; approve or fail the audit | RegistryAdmin |
| POST | `/registry/recert-applications/{id}/reopen` | Reopen a denied or audit-failed application back to draft | Candidate |
| POST | `/registry/reentry-applications` | Apply for lapsed-certification reentry; tier assigned by lapse duration | Candidate |
| GET | `/registry/reentry-applications` | List reentry applications | All authenticated roles |
| GET | `/registry/reentry-applications/{id}` | Read a reentry application | All authenticated roles |
| POST | `/registry/reentry-applications/{id}/decision` | Approve (reinstating with a fresh cycle) or deny a reentry application | RegistryAdmin |
| POST | `/registry/license-applications` | Apply for state licensure; policy snapshot pinned and path resolved at creation | Candidate |
| GET | `/registry/license-applications` | List license applications | All authenticated roles |
| GET | `/registry/license-applications/{id}` | Read a license application | All authenticated roles |
| POST | `/registry/license-applications/{id}/decision` | Grant (assessing fees), deny, or request more information | StateOfficial |
| POST | `/registry/license-applications/{id}/respond` | Respond to an information request, cycling back to review | Candidate |
| POST | `/registry/state-exam-records` | Register a state's own examination result | StateOfficial |
| GET | `/registry/state-exam-records` | List state exam records | All authenticated roles |
| GET | `/registry/state-exam-records/{id}` | Read a state exam record | All authenticated roles |
| POST | `/registry/disciplinary-cases` | Open a disciplinary case; the interim action applies immediately | RegistryAdmin, StateOfficial |
| GET | `/registry/disciplinary-cases` | List disciplinary cases | All authenticated roles |
| GET | `/registry/disciplinary-cases/{id}` | Read a disciplinary case | All authenticated roles |
| POST | `/registry/disciplinary-cases/{id}/issue-notice` | Issue the notice of allegations and open the response window | RegistryAdmin |
| POST | `/registry/disciplinary-cases/{id}/response` | Record the subject's response, closing the window early | Candidate |
| POST | `/registry/disciplinary-cases/{id}/schedule-hearing` | Schedule the hearing under a segregated officer | HearingOfficer |
| POST | `/registry/disciplinary-cases/{id}/decide` | Record the hearing decision (concurrency-guarded) | HearingOfficer |
| POST | `/registry/disciplinary-cases/{id}/appeal` | Appeal within the appeal window | Candidate |
| POST | `/registry/disciplinary-cases/{id}/appeal-decision` | Affirm (finalizing with cascades) or overturn to rehearing | RegistryAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CE_HOURS_INCREMENT` | 400 Bad Request |
| `ERR_CE_ENTRY_OUTSIDE_CYCLE` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_COMPLETION_NOT_PENDING` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_APPLICATION_NOT_DENIED` | 409 Conflict |
| `ERR_ATT_NOT_ISSUABLE` | 409 Conflict |
| `ERR_ATTEMPT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_RECERT_NOT_DRAFT` | 409 Conflict |
| `ERR_RECERT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_RECERT_NOT_AUDIT_PENDING` | 409 Conflict |
| `ERR_RECERT_NOT_REOPENABLE` | 409 Conflict |
| `ERR_CERTIFICATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_CERTIFICATION_NOT_LAPSED` | 409 Conflict |
| `ERR_LICENSE_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_LICENSE_NOT_AWAITING_RESPONSE` | 409 Conflict |
| `ERR_PSYCHOMOTOR_NOT_SUBMITTED` | 409 Conflict |
| `ERR_PSYCHOMOTOR_REQUIREMENTS_UNMET` | 422 Unprocessable Entity |
| `ERR_CASE_STAGE_MISMATCH` | 409 Conflict |
| `ERR_REENTRY_NOT_SUBMITTED` | 409 Conflict |
| `ERR_DISCIPLINARY_HOLD` | 403 Forbidden |
| `ERR_PERMANENTLY_BARRED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION` | 422 Unprocessable Entity |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LEVEL_NOT_ACCEPTED_IN_STATE` | 422 Unprocessable Entity |
| `ERR_STATE_EXAM_NOT_PASSING` | 422 Unprocessable Entity |
| `ERR_EDUCATION_VALIDITY_EXPIRED` | 409 Conflict |
| `ERR_RETAKE_WAIT_ACTIVE` | 409 Conflict |
| `ERR_RECERT_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_CREDENTIAL_STALE` | 409 Conflict |
| `ERR_REENTRY_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CLOCK_REGRESSION` | 409 Conflict |
| `ERR_ATTEMPT_SLOT_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CERTIFICATION` | 409 Conflict |
| `ERR_ACTIVE_VERIFICATION_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_COURSE_IN_CYCLE` | 409 Conflict |
| `ERR_DUPLICATE_STATE_POLICY` | 409 Conflict |
| `ERR_DUPLICATE_LEVEL_CODE` | 409 Conflict |
| `ERR_RECERT_IN_PROGRESS_CONFLICT` | 409 Conflict |
| `ERR_ATTEMPT_LIMIT_REACHED` | 409 Conflict |
| `ERR_REMEDIAL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CE_COMPONENT_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_CE_TOTAL_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_JURISPRUDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_REENTRY_REQUIREMENTS_UNMET` | 422 Unprocessable Entity |
