# EEOC Charge Processing API — Product Requirements Document

## 1. Introduction

Every year the Commission receives tens of thousands of discrimination charges from workers, and every one of them must be screened, routed, investigated, and — where the law requires — released into private litigation, all under statutory deadlines that differ from state to state. A charge filed 181 days after the alleged harm is dead on arrival in one state and perfectly timely in another, because a state fair-employment agency's work-sharing agreement extends the window. An employer with fourteen employees sits outside the statute entirely, while the same facts pled against a twenty-employee employer proceed. These jurisdictional gates are unforgiving, and the system that administers them must apply them mechanically, record the outcome faithfully, and never silently drop a charge on the floor.

This document specifies the EEOC Charge Processing API: a case-management platform covering the full life of a discrimination charge — intake with synchronous jurisdictional screening, voluntary mediation held behind a strict confidentiality firewall, formal investigation with compulsory evidence requests and witness interviews, cause and no-cause determinations reviewed under segregation of duties, conciliation with statutory damages caps, and issuance of right-to-sue notices that start the charging party's court-filing clock. Beyond the individual complaint, the API supports Commissioner-initiated systemic investigations that seal linked charges and amplify their priority, and it maintains an append-only disclosure audit trail for every release of charge data. All dates and deadlines derive from a single logical clock, so that limitation periods, response windows, and notice expirations are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` specifies their operational capacity. The system recognizes exactly nine roles: `PlatformAdmin`, `IntakeOfficer`, `ChargingParty`, `RespondentRep`, `Mediator`, `Investigator`, `Director`, `Commissioner`, and `StateAgencyOfficer`. A request missing either header, or carrying a role string outside these nine, is rejected with `ERR_UNAUTHENTICATED`. A properly authenticated caller whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

Two roles are entity-backed. When `X-User-Role` is `ChargingParty`, `X-User-ID` is the `id` of the acting `Complainant`; ownership checks on any resource that references a complainant compare the resource's `complainant_id` field to `X-User-ID`. When `X-User-Role` is `RespondentRep`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an employer compare the resource's `employer_id` field to `X-User-ID`.

The remaining seven roles carry opaque identities. When `X-User-Role` is `PlatformAdmin`, `IntakeOfficer`, `Mediator`, `Investigator`, `Director`, `Commissioner`, or `StateAgencyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `mediator_user_id` on a `MediationSession`, as `investigator_user_id` on a `WitnessInterview`, as `assigned_investigator_id` on an `InvestigationCase`, as `prepared_by_user_id` or `reviewed_by_user_id` on a `Determination`, or as `commissioner_user_id` on a `SystemicCase` — but it never compares these values to any entity's `id`. Scoping rules that mention these opaque identifiers (such as "only the assigned investigator may log evidence") compare `X-User-ID` to the recorded field, not to a role-backed entity.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Lazy State Transitions

The system never reads the wall clock. A single logical clock governs every date stamp, deadline computation, and time-based state change. Before any clock-setting call has been made, the logical clock reads exactly `2026-09-01T00:00:00Z` — a fixed startup default, never the host's wall-clock time. A `PlatformAdmin` may advance the clock through a test-driving capability that accepts a target instant in the `to_iso8601` field and reports the new time as `current_utc`; every subsequent read evaluates time-dependent state against the new clock value.

Dates are handled at day granularity throughout. Date-valued inputs such as `incident_date` carry date precision only — their time component must be `T00:00:00Z` — and date comparisons (deadline tests, overdue tests) compare whole days.

Three state changes are lazy: they are evaluated when a resource is read, not by a background job. An `EvidenceRequest` flips from `PENDING` to `OVERDUE` on read once the logical clock passes its `due_date`. A `RightToSueNotice` flips from `ISSUED` to `EXPIRED` on read once the logical clock is strictly after its `court_filing_deadline` — on the exact deadline date the notice is still `ISSUED`. A `MediationSession` flips from `SCHEDULED` to `HELD` on read once the logical clock passes its `scheduled_end`. Advancing the clock therefore changes what later reads return without any write occurring.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource, including mutations driven by cascades.

The `DisclosureRecord` is the sole exception. Because it is an append-only audit row with no update or delete path, it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Nested Resource Retrieval

Requests that target nested resources are validated hierarchically, left to right along the path. Existence of the parent identifier is confirmed before any child identifier is examined, and the request is rejected with the `404` variant naming the first missing resource: `ERR_CHARGE_NOT_FOUND`, `ERR_MEDIATION_CASE_NOT_FOUND`, `ERR_INVESTIGATION_CASE_NOT_FOUND`, `ERR_EVIDENCE_REQUEST_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_CONCILIATION_NOT_FOUND`, or `ERR_SYSTEMIC_CASE_NOT_FOUND`, depending on which identifier in the path fails to resolve. Body-supplied references are validated after the path identifiers — `complainant_id` and `employer_id` at charge intake (yielding `ERR_COMPLAINANT_NOT_FOUND` or `ERR_EMPLOYER_NOT_FOUND` when unknown), and `charge_id` when linking a charge into a systemic case. Existence therefore precedes ownership checks, state checks, and confidentiality checks; a read against a non-existent charge returns `ERR_CHARGE_NOT_FOUND` even if the caller could never have been entitled to see it.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both reject stale clients with `ERR_STALE_VERSION` (HTTP 412):

- Amending a charge (`POST /eeoc/charges/{id}/amend`) requires the non-optional field `expected_charge_version`, carrying the client's last observed `version` of the target `Charge`. If another writer has advanced the charge's version since the client last read it, the amendment is rejected with `ERR_STALE_VERSION`, because a later amendment legitimately supersedes earlier factual allegations and a stale client would otherwise silently overwrite edits it never observed.
- Tabling a conciliation offer (`POST /eeoc/conciliation-processes/{id}/offers`) requires the non-optional field `expected_conciliation_version`, carrying the client's last observed `version` of the `ConciliationProcess`. A mismatch with the process's current version is rejected with `ERR_STALE_VERSION`, because a newer offer changes `current_offer_cents` and `last_offer_by` without changing the negotiation's status, so a stale view is otherwise undetectable and would silently displace the newest offer.

Endpoints not named in this section do not accept a version field.

### 2.8. Validation Ordering and Error Precedence

Every request passes through a fixed validation pipeline, and the first failing check wins — its error is returned and later checks are not evaluated. The ordering is:

1. **Authentication** — missing `X-User-Role`/`X-User-ID`, or an unrecognized role string: `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** — the authenticated role is not in the endpoint's authorized list: `ERR_FORBIDDEN_ROLE` (403).
3. **Request-body schema** — required fields present, enum members valid, types correct, conditional requirements met (an outcome of `SETTLED` requires `settlement_amount_cents`; an outcome of `CAUSE` requires the four remedy components plus `harm_start_date`; a `decision` of `RETURN` requires `return_reason`; an end time must be strictly after its start time; `basis_codes` must be non-empty; an agency's `filing_deadline_days` must be 180 or 300): `ERR_VALIDATION_FAILED` (400).
4. **Resource existence** — path identifiers left to right, then body references: the 404 family (`ERR_CHARGE_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_COMPLAINANT_NOT_FOUND`, `ERR_MEDIATION_CASE_NOT_FOUND`, `ERR_INVESTIGATION_CASE_NOT_FOUND`, `ERR_EVIDENCE_REQUEST_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_CONCILIATION_NOT_FOUND`, `ERR_SYSTEMIC_CASE_NOT_FOUND`).
5. **Ownership scope** — the caller's `X-User-ID` does not match the resource's owning party: `ERR_NOT_RESOURCE_OWNER` (403).
6. **State preconditions** — the target resource is in a state that forbids the transition: `ERR_INVALID_STATE` (409). On a terminal charge the more specific `ERR_CHARGE_ALREADY_CLOSED` (409) is returned instead, and it outranks the business-temporal checks below — an operation on a closed charge reports its closedness, not a deadline failure. A right-to-sue request against a charge in `CONCILIATION` returns the equally specific `ERR_CONCILIATION_ACTIVE` (409) at this same step.
7. **Confidentiality and segregation of duties** — `ERR_CONFIDENTIALITY_SEALED` (403), `ERR_DISCLOSURE_FORBIDDEN` (403), `ERR_SEGREGATION_OF_DUTIES` (409); the exact triggers are specified in §2.9.
8. **Business constraints** — duplicate agency state (`ERR_DUPLICATE_AGENCY_STATE`), mediator session overlap (`ERR_SESSION_OVERLAP`), investigator interview buffer violation (`ERR_INTERVIEW_BUFFER_CONFLICT`), a third mediation round (`ERR_MEDIATION_ROUND_EXHAUSTED`), a second non-terminal determination (`ERR_DETERMINATION_EXISTS`), an offer tabled out of turn (`ERR_OFFER_OUT_OF_TURN`), and the link gates on systemic cases — all 409.
9. **Business-temporal rules** — premature right-to-sue request (`ERR_RTS_PREMATURE`), a session scheduled in the past (`ERR_SESSION_IN_PAST`), an expired vacatur window (`ERR_VACATE_WINDOW_EXPIRED`), a future incident date (`ERR_INCIDENT_DATE_FUTURE`) — all 422.
10. **Optimistic concurrency** — `expected_charge_version` or `expected_conciliation_version` does not equal the parent's current version: `ERR_STALE_VERSION` (412).

Because schema validation (step 3) precedes existence (step 4), a malformed body is rejected with `ERR_VALIDATION_FAILED` even when the addressed resource does not exist; because existence precedes ownership, a wrong-party caller probing a non-existent resource receives the 404.

### 2.9. Confidentiality, Sealing, and the Mediation–Investigation Firewall

Each charge carries a confidentiality dimension, `disclosure_hold`, that is fully independent of its `case_status`. A charge is normally `NONE`; it becomes `SEALED` while linked to a systemic case, and returns to `NONE` when that systemic case resolves. Reading a `SEALED` charge is restricted: any role outside the privileged set {`IntakeOfficer`, `Director`, `Commissioner`} that attempts to read it — including the charge's own `ChargingParty` and `RespondentRep` — is rejected with `ERR_CONFIDENTIALITY_SEALED`. When a privileged role does read a `SEALED` charge, the system appends an `INTERNAL_ACCESS` `DisclosureRecord` to the charge's audit log automatically.

Explicit disclosures of charge data are recorded by a `Director`. On a `SEALED` charge, only the legal basis `COURT_ORDER` is permitted; an explicit disclosure attempted with any other basis is rejected with `ERR_DISCLOSURE_FORBIDDEN`.

Two firewalls separate mediation from investigation, reflecting the statutory bar on using mediation content in enforcement. The `Mediator` role is excluded from all investigation content, and the `Investigator` role is excluded from all mediation content — each receives `ERR_FORBIDDEN_ROLE` when reaching for the other side's resources. The firewall also follows people across roles over time: assigning an investigator who previously served as `mediator_user_id` on any session of the same charge is rejected with `ERR_SEGREGATION_OF_DUTIES`. Segregation of duties applies within investigation as well: the `Director` reviewing a determination must not be the investigator who drafted it — a review whose `X-User-ID` equals the determination's `prepared_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. Money, Interest, and Rounding

All monetary values in the system are integer numbers of cents — settlement amounts, remedy components, statutory caps, and offers are all whole cents, and no monetary field ever carries a fractional value. Dates and durations are integers of whole days. Where a calculation produces a fractional cent (the per-diem interest computation), the result is rounded half-up to the nearest whole cent, and — as detailed in §3.7 — each interest component is rounded individually before any summation takes place. This per-component round-then-sum order is load-bearing and must not be rearranged into sum-then-round.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Deferral Agencies, Employers, and Complainants

Before any charge can be screened, the Commission's reference data must exist. A `PlatformAdmin` registers each state or local fair-employment agency (FEPA) as a `DeferralAgency`, supplying its two-letter `state_code`, its display `agency_name`, the `filing_deadline_days` that governs timeliness for charges in that state, the `work_sharing_policy` tier, and `covers_age`, which records whether the state agency's own statute covers age discrimination. Only two deadline values are accepted — 180 or 300 days — and any other value is rejected with `ERR_VALIDATION_FAILED`. One agency exists per state: registering a second agency for a `state_code` already on file is rejected with `ERR_DUPLICATE_AGENCY_STATE`. The `work_sharing_policy` takes one of three values. Under `EEOC_RETAINS_ALL` the Commission investigates and the charge is not dual-filed. Under `DUAL_FILE_DEFAULT` the charge is dual-filed with the agency but the Commission still investigates. Under `FEPA_EXCLUSIVE` the charge is dual-filed and the FEPA investigates — the charge lands directly in `DELEGATED_TO_FEPA`.

An `IntakeOfficer` registers each respondent `Employer` with its `legal_name`, the two-letter `state_code` of the worksite, and the most recently verified headcount `employee_count_current` (a non-negative integer). From that headcount the system derives the employer's `size_band`, recomputed on creation and again on every update: `UNDER_15` for 0–14 employees, `FROM_15_TO_19` for 15–19, `FROM_20_TO_100` for 20–100, `FROM_101_TO_200` for 101–200, `FROM_201_TO_500` for 201–500, and `OVER_500` for 501 or more. Band boundaries are inclusive at the low end: a headcount of 14 lands `UNDER_15`, 15 lands `FROM_15_TO_19`, 20 lands `FROM_20_TO_100`, 100 stays `FROM_20_TO_100`, and 101 lands `FROM_101_TO_200`. Updating an employer (the intake officer may patch `employee_count_current` and/or `legal_name`) increments the employer's `version` by 1, recomputes `size_band`, and re-bands every `PROVISIONAL` `RemedyPackage` attached to that employer's non-terminal conciliations — each re-banded package keeps its original `projection_date`, only the cap tier moves.

Complainants are registered by an `IntakeOfficer` with a `full_name` and a contact `email`. The email is deliberately not unique: multiple complainants may share an inbox.

### 3.2. Charge Intake and Jurisdictional Screening

A charge is the central aggregate of the system. Either an `IntakeOfficer` or the `ChargingParty` may file one; a `ChargingParty` caller must file as themselves, so the payload's `complainant_id` must equal the caller's `X-User-ID`, otherwise the filing is rejected with `ERR_NOT_RESOURCE_OWNER`. The intake payload names the respondent via `employer_id`, asserts one or more protected bases in `basis_codes` — a non-empty array drawn from `RACE`, `COLOR`, `RELIGION`, `SEX`, `NATIONAL_ORIGIN`, `AGE`, `DISABILITY`, `GENETIC_INFO`, and `RETALIATION`, where an empty array fails schema validation — gives the `incident_date` of the alleged harm at date precision (time component `T00:00:00Z`), a free-text `harm_description`, and the `employee_count_at_incident` snapshot: the respondent's headcount during the incident period. An `incident_date` after the current logical clock is rejected with `ERR_INCIDENT_DATE_FUTURE`, and it must never be after the charge's `received_date`.

Creation synchronously runs jurisdictional screening; intake never rejects a charge for being late or too small — it records the outcome. First the system auto-matches a `DeferralAgency` by the employer's `state_code` and stamps `deferral_agency_id` on the charge (null when the state has no agency; clients never supply it). The `received_date` is stamped from the logical clock. The filing deadline is then resolved: when an agency matched, its `filing_deadline_days` governs; when none matched, the federal default of 180 days applies. The charge's `filing_deadline_date` is the `incident_date` plus that many days, and the timeliness test is inclusive — a charge whose `received_date` falls on or before the `filing_deadline_date` is timely; one received after it is not. The same `incident_date`/`received_date` pair that is untimely for a no-agency state (a filing 181 days after the incident is dismissed) can be timely in a state whose agency sets a 300-day deadline.

The size screen uses only the `employee_count_at_incident` snapshot — never the employer's current headcount. An `AGE` basis survives only when the snapshot headcount is at least 20 and either no deferral agency matched or the matched agency's `covers_age` is true; when the state agency's statute does not cover age, an `AGE` basis is stripped from coverage even against a 20-or-more-employee employer. Every other basis survives when the snapshot headcount is at least 15. The surviving bases are recorded in `covered_bases`, preserving the order of `basis_codes`. The evaluation order is pinned: the size screen runs first and timeliness second, so a charge failing both is dismissed for lack of jurisdiction, not lateness. The resulting `jurisdiction_outcome` is `DISMISSED_NO_JURISDICTION` when `covered_bases` is empty, `DISMISSED_UNTIMELY` when coverage exists but the charge is late, and `TIMELY_CONFIRMED` otherwise.

Routing follows from the match. `investigation_owner` is `EEOC` when no agency matched or the policy is `EEOC_RETAINS_ALL` or `DUAL_FILE_DEFAULT`, `FEPA` when the policy is `FEPA_EXCLUSIVE`, and `NONE` when the charge is dismissed at intake. `dual_filed` is true exactly when an agency matched and its policy is `DUAL_FILE_DEFAULT` or `FEPA_EXCLUSIVE`. The newly created charge lands in `DOCKETED` (timely, Commission-retained), `DELEGATED_TO_FEPA` (FEPA-exclusive), `DISMISSED_UNTIMELY`, or `DISMISSED_NO_JURISDICTION`, and is returned with a 201. `DISMISSED_UNTIMELY`, `DISMISSED_NO_JURISDICTION`, `CLOSED_NO_CAUSE`, `RTS_ISSUED`, and `WITHDRAWN` are the charge's terminal states; `CLOSED_SETTLED` and `LITIGATION_REFERRED` are non-terminal, for reasons §3.7 and §3.8 make concrete. Every read of a charge recomputes `days_elapsed_since_filing`, the whole days between `received_date` and the current logical clock, which drives the 180-day right-to-sue gate of §3.8.

The paginated charge list supports filters `status`, `employer_id`, `complainant_id`, `deferral_agency_id`, `systemic_case_id`, and `basis`, alongside the standard `limit` and `offset`. A `StateAgencyOfficer` participates only in the work-sharing partition: they see — in lists and in detail reads alike — only charges whose `investigation_owner` is `FEPA`, and any attempt to touch a Commission-owned charge is rejected with `ERR_NOT_RESOURCE_OWNER`.

### 3.3. Amending and Withdrawing a Charge

A charging party may amend the factual allegations of their own charge while it remains workable — that is, while its `case_status` is `DOCKETED`, `IN_MEDIATION`, `UNDER_INVESTIGATION`, or `DELEGATED_TO_FEPA`. Amendment is blocked in `DETERMINATION_REVIEW` and `CONCILIATION` (rejected with `ERR_INVALID_STATE`) and on terminal charges (rejected with `ERR_CHARGE_ALREADY_CLOSED`). The amendment payload must carry `expected_charge_version` per the OCC rule of §2.7, plus any of `basis_codes`, `incident_date`, or `harm_description` to change. A successful amendment increments the charge's `version` by 1.

Amending `incident_date` re-runs the full timeliness screening of §3.2 against the recomputed `filing_deadline_date`. When the re-screening yields `DISMISSED_UNTIMELY`, the charge flips to that terminal state, its `investigation_owner` becomes `NONE`, and the dismissal cascade resolves everything in flight: any `OFFERED` or `ACTIVE` mediation case for the charge is moved to `DECLINED` (with its still-`SCHEDULED` sessions moved to `CANCELLED` when one was active), the investigation case — if one exists — is moved to `CLOSED`, and its `PENDING` or `OVERDUE` evidence requests are moved to `WAIVED`. When the re-screening still passes, the charge simply keeps its current state with the amended facts.

Withdrawal is the charging party's unilateral exit. The caller's `X-User-ID` must equal the charge's `complainant_id`, and withdrawal is allowed from exactly the four amend-eligible states, with the cleanup shaped by the state left behind. From `DOCKETED`, any `OFFERED` mediation case is moved to `DECLINED`. From `IN_MEDIATION`, the `ACTIVE` or `OFFERED` mediation case is moved to `DECLINED` and its `SCHEDULED` sessions to `CANCELLED`. From `UNDER_INVESTIGATION`, an `OFFERED` mediation case awaiting a re-offer response is moved to `DECLINED`, the investigation case — whether `OPEN`, `GATHERING`, or `SUSPENDED_MEDIATION` — is moved to `CLOSED`, and its `PENDING`/`OVERDUE` evidence requests are `WAIVED`. From `DELEGATED_TO_FEPA`, only the charge's own status changes. In all four, the charge lands in `WITHDRAWN`.

### 3.4. Mediation: Offers, Responses, Sessions, and Conclusion

Mediation is voluntary, capped, and firewalled. An `IntakeOfficer` offers mediation on a charge that is `DOCKETED` or `UNDER_INVESTIGATION`, provided every prior mediation case on the charge is in a terminal state and fewer than 2 mediation cases already exist — offering a third is rejected with `ERR_MEDIATION_ROUND_EXHAUSTED`, the hard cap being 2 rounds per charge. Each new `MediationCase` records its charge via `charge_id`, is assigned a `round_number` equal to 1 plus the count of prior mediation cases for that charge, and opens in `OFFERED` with both `complainant_response` and `respondent_response` set to `PENDING`.

Each party answers the offer through a response call carrying a `response` of `ACCEPTED` or `DECLINED`. The party being recorded is derived from the caller's identity: a caller whose `X-User-ID` matches the charge's `complainant_id` sets `complainant_response`; one matching the charge's `employer_id` sets `respondent_response`. A party may respond only while its own response field is still `PENDING`. If either party declines, the case moves `OFFERED` → `DECLINED`; when this happens on a `DOCKETED` charge, the charge moves to `UNDER_INVESTIGATION` and an `InvestigationCase` is auto-created (status `OPEN`, `assigned_investigator_id` null, and the charge's `investigation_case_id` stamped with the new case's id), while a decline during an `UNDER_INVESTIGATION` re-offer leaves the charge where it is. When the second `ACCEPTED` arrives — both responses now `ACCEPTED` — the mediation moves `OFFERED` → `ACTIVE` and the charge moves to `IN_MEDIATION`; on re-entry from `UNDER_INVESTIGATION`, the charge's investigation case, if it exists and is `GATHERING`, suspends to `SUSPENDED_MEDIATION`.

While a mediation is active, the assigned neutral schedules sessions. Each session belongs to its case through `mediation_case_id`, taken from the path. Creating a session takes `scheduled_start` and `scheduled_end`; the start must not be before the current logical clock (a past start is rejected with `ERR_SESSION_IN_PAST`) and the end must be strictly after the start. The system stamps `mediator_user_id` from the caller's `X-User-ID`, ignoring any client-supplied value. A mediator's calendar is protected by a half-open overlap rule: sessions are treated as the interval from start inclusive to end exclusive, so back-to-back sessions are allowed, but any true overlap with another `SCHEDULED` session of the same mediator — on any mediation case — is rejected with `ERR_SESSION_OVERLAP`. Sessions open as `SCHEDULED`, flip to `HELD` on read once the clock passes `scheduled_end`, and are moved to `CANCELLED` if their parent mediation concludes while they are still scheduled.

Concluding an active mediation is the mediator's call, made with an `outcome` of `SETTLED` or `IMPASSE`, and is gated on the charge still being `IN_MEDIATION` — a mediation orphaned by a right-to-sue issuance (§3.8) can no longer settle, and its conclusion is rejected with `ERR_INVALID_STATE`. A `SETTLED` conclusion requires `settlement_amount_cents` to be present and greater than zero; supplying it with any other outcome, or omitting it here, fails schema validation. On settlement the mediation case becomes `SETTLED` with `concluded_at` stamped from the clock, the charge records `settled_amount_cents` equal to the agreed amount with `settled_via` set to `MEDIATION` and `settled_at` stamped from the clock, every `SCHEDULED` session is `CANCELLED`, and the charge moves `IN_MEDIATION` → `CLOSED_SETTLED`. On `IMPASSE` the case becomes `IMPASSE` with `concluded_at` stamped, scheduled sessions are cancelled, the charge returns to `UNDER_INVESTIGATION`, and the investigation resumes — an existing case moves `SUSPENDED_MEDIATION` → `GATHERING`, or, if somehow none exists, one is auto-created in `OPEN`.

`SETTLED` is not terminal for a mediation case: settlement vacatur (§3.8) reverts it to `VACATED`. The terminal states of a mediation case are `IMPASSE`, `DECLINED`, and `VACATED`.

### 3.5. Investigation: Assignment, Evidence, Interviews, and Priority

An `InvestigationCase` is born by cascade: the system auto-creates one, in `OPEN` with a null `assigned_investigator_id`, the first time its charge enters `UNDER_INVESTIGATION`, stamping the charge's `investigation_case_id`; the pair is one-to-one, and the case can be found from the charge through the investigation list filtered by `charge_id` (the list also supports `status` and `assigned_investigator_id` filters, so a director can survey any investigator's caseload). Reading an investigation case returns its live `priority_score`, recomputed on every read.

Staffing is the `Director`'s responsibility. Assignment (or reassignment, which transfers the caseload slot) names the target in `investigator_user_id`, stamps `assigned_investigator_id`, and recomputes the priority score. The mediation firewall of §2.9 applies here: the target must never have served as `mediator_user_id` on any session of the same charge, or the assignment is rejected with `ERR_SEGREGATION_OF_DUTIES`. Once assigned, only that investigator may write to the case — evidence requests, interviews, and determinations all require the caller's `X-User-ID` to equal `assigned_investigator_id`, otherwise `ERR_NOT_RESOURCE_OWNER`.

The investigator compels evidence by issuing an `EvidenceRequest` against the case (which must be `OPEN` or `GATHERING`), choosing a `request_type` of `POSITION_STATEMENT`, `RFI`, or `DOCUMENT_DEMAND`. The `issued_date` is stamped from the logical clock and the `due_date` is computed as exactly 30 days after issuance — the respondent's statutory response window. The first evidence activity on a case (a request or an interview) moves it `OPEN` → `GATHERING`. A request is `PENDING` at issuance and flips to `OVERDUE` on read once the clock passes its `due_date`. The respondent answers through its `RespondentRep` — whose `X-User-ID` must equal the `employer_id` of the charge that owns the investigation — by submitting `response_text`. The request then becomes `RESPONDED`, and a response that arrives while the request is `OVERDUE` is still accepted, flagged `responded_late` true; an on-time response carries `responded_late` false. Requests still `PENDING` or `OVERDUE` when the owning charge reaches a terminal state are moved to `WAIVED`. Each case tracks `open_request_count` — its requests in `PENDING` or `OVERDUE`, excluding `RESPONDED` and `WAIVED` — and `overdue_request_count`, counting `OVERDUE` only; both are recomputed whenever a request transitions. When reading the request list, a `RespondentRep` sees only requests directed at its own employer.

Investigators also log `WitnessInterview` records against the case, supplying `witness_name`, `interview_start`, `interview_end` (strictly after the start), and a `summary`. Interviews are logged after the fact, so past dates are entirely legitimate — the `ERR_SESSION_IN_PAST` rule does not apply to them. The logging investigator is stamped as `investigator_user_id` and must be the case's assignee. One investigator's interviews are kept apart by a 30-minute buffer on both sides, evaluated across all of that investigator's interviews regardless of case: if the gap between the new interview and any existing interview of the same investigator is less than 30 minutes on either side, the logging is rejected with `ERR_INTERVIEW_BUFFER_CONFLICT`.

Every investigation case carries a `priority_score`, recomputed on each read and on every evidence-request transition, from four inputs. The severity term is the maximum basis weight among the charge's `basis_codes` — not a sum — using 30 for `RETALIATION`, 25 for `DISABILITY`, 20 for `AGE`, and 15 for each of `SEX`, `RACE`, `COLOR`, `RELIGION`, `NATIONAL_ORIGIN`, and `GENETIC_INFO`. The age term comes from the charge's `days_elapsed_since_filing`: 0 points under 90 days, 10 points from 90 through 179 days, 20 points from 180 through 364 days, and 35 points at 365 days or more. The overdue term adds 15 points per currently-`OVERDUE` evidence request, capped at 45 points no matter how many requests are late. If the charge's `systemic_case_id` is set, the sum of those three terms is multiplied by 1.5; otherwise the multiplier is 1.0. The product is rounded half-up once — a single rounding after the multiplication — and the score is clamped to a ceiling of 100. The first time a recomputed score reaches 80 or more, the charge's `priority_escalated` flag flips to true; it is sticky and never auto-clears, even if the score later subsides.

### 3.6. Determinations and Director Review

When the evidence is in, the assigned investigator drafts a `Determination` against the case — which must be `GATHERING`, so at least one evidence activity must have occurred first — and at most one non-terminal determination may exist per investigation: drafting a second while one sits in `DRAFT`, `PENDING_REVIEW`, or `RETURNED` is rejected with `ERR_DETERMINATION_EXISTS`. The draft carries an `outcome` of `CAUSE`, `NO_CAUSE`, or `UNABLE_TO_DETERMINE`, a written `rationale`, and, when the outcome is `CAUSE`, the four remedy components — `back_pay_cents` (documented wage loss), `front_pay_cents` (projected future wage loss), `compensatory_damages_cents` (non-pecuniary damages, pre-cap), and `punitive_damages_cents` (pre-cap), each a non-negative integer — plus `harm_start_date`, the date the wage harm began and from which interest accrues. For `NO_CAUSE` or `UNABLE_TO_DETERMINE` all five of those fields must be null; providing them anyway fails schema validation. The drafting investigator is stamped as `prepared_by_user_id`, and the determination opens in `DRAFT`.

Submitting moves the determination `DRAFT` → `PENDING_REVIEW` and the charge `UNDER_INVESTIGATION` → `DETERMINATION_REVIEW`. Only the drafting investigator may submit — the caller's `X-User-ID` must equal `prepared_by_user_id` — and the charge must still be `UNDER_INVESTIGATION`. A determination sent back by review may be submitted again: the same submission moves `RETURNED` → `PENDING_REVIEW`, so the cycle can repeat.

Review belongs to a `Director`, who supplies a `decision` of `APPROVE` or `RETURN`. Segregation of duties is enforced at this gate: the reviewer's `X-User-ID` must differ from `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. A `RETURN` decision requires a `return_reason` (which must conversely be null on an approval); it stamps `reviewed_by_user_id`, moves the determination to `RETURNED`, and sends the charge back `DETERMINATION_REVIEW` → `UNDER_INVESTIGATION` for further work. An `APPROVE` stamps `reviewed_by_user_id`, moves the determination to its terminal `APPROVED`, and forks on the outcome. Approving a `CAUSE` determination drives a three-link cascade: the charge moves to `CONCILIATION`; that entry auto-creates a `ConciliationProcess` in `INITIATED` with its `origin_determination_id` set to the approved determination, `rounds_count` at 0, and both `current_offer_cents` and `last_offer_by` null; and the new conciliation's creation in turn auto-creates exactly one `RemedyPackage` with `valuation_variant` `PROVISIONAL`, valued per §3.7. Approving a `NO_CAUSE` or `UNABLE_TO_DETERMINE` determination instead closes the charge into `CLOSED_NO_CAUSE` and auto-issues a `RightToSueNotice` with `issuance_basis` `AUTO_ON_DISMISSAL`, `requested_by_role` recorded as `system`, `issued_date` stamped from the clock, and `court_filing_deadline` set 90 days out. Either approval cascade also closes the investigation case and moves its `PENDING`/`OVERDUE` evidence requests to `WAIVED`. The components and history of the originating determination remain traceable through the investigation's determination list.

### 3.7. Conciliation and Remedy Valuation

A cause finding does not go straight to litigation; the statute requires the Commission to attempt conciliation first. The `ConciliationProcess` tracks a structured negotiation between the two sides, and offers are tabled through a single operation open to the `Director` — who tables as the `COMMISSION` side — and the `RespondentRep` — who tables as the `RESPONDENT` side. Every offer carries `amount_cents` and, per §2.7, the non-optional `expected_conciliation_version`; a stale view of the negotiation is rejected with `ERR_STALE_VERSION`. The first offer moves the process `INITIATED` → `OFFER_TABLED`. From then on the sides must strictly alternate: a counter-offer by the side that did not table the current offer flips the process `OFFER_TABLED` → `COUNTERED`, and the next counter flips `COUNTERED` → `OFFER_TABLED` again — a two-state negotiation cycle. An offer tabled by the same side twice in a row is rejected with `ERR_OFFER_OUT_OF_TURN`. Each successful offer records the new `amount_cents` in `current_offer_cents`, sets or flips `last_offer_by` to the tabling side, increments `rounds_count` by 1, and increments the process `version` by 1.

Acceptance belongs to the charging party alone: a caller whose `X-User-ID` equals the charge's `complainant_id` may accept while an offer is outstanding — the process in `OFFER_TABLED` or `COUNTERED`. Acceptance moves the conciliation to its terminal `SETTLED`, recomputes the remedy package as `FINAL` (below), settles the charge at the negotiated figure — `settled_amount_cents` takes the conciliation's `current_offer_cents`, `settled_via` becomes `CONCILIATION`, `settled_at` is stamped from the clock — and moves the charge `CONCILIATION` → `CLOSED_SETTLED`. Alternatively, a `Director` may declare failure — supplying a `reason` — from `INITIATED`, `OFFER_TABLED`, or `COUNTERED`; the process moves to its terminal `FAILED` and the charge is referred for litigation, landing in `LITIGATION_REFERRED`. That referral is not the end of the road: `LITIGATION_REFERRED` is a non-terminal state, and a right-to-sue notice may still be requested from it.

The `RemedyPackage` — exactly one per conciliation, created by the cause-approval cascade and tied to its process via `conciliation_process_id` — copies `back_pay_cents`, `front_pay_cents`, `compensatory_damages_cents`, `punitive_damages_cents`, and `harm_start_date` from its origin determination, and exists in two valuation variants that diverge on exactly two inputs: which employer-size band supplies the damages cap, and which date ends the interest accrual. While the conciliation is open (`INITIATED`, `OFFER_TABLED`, or `COUNTERED`), the package is `PROVISIONAL`: `band_used` is the employer's current `size_band` at computation time (so the employer update of §3.1 re-bands it in place), and `projection_date` is pinned to the conciliation-initiation date. At acceptance the package flips to `FINAL`: `band_used` is re-derived from the charge's immutable `employee_count_at_incident` snapshot — never from the employer's mutable headcount — and `projection_date` is pinned to the acceptance date. The `FINAL` computation happens once, on acceptance, and never recomputes again.

The valuation itself runs in a pinned order. `interest_days` is the whole number of days from `harm_start_date` to `projection_date`. Interest accrues at an annual rate of 0.05 (five percent) on each wage component independently: `back_pay_interest_cents` is `back_pay_cents` multiplied by 0.05, multiplied by `interest_days`, divided by 365, then rounded half-up to whole cents — and `front_pay_interest_cents` is computed identically from `front_pay_cents`. Each component is rounded before any summation; per §2.10 this round-then-sum order is load-bearing (with both wage components at 3650 cents and a single interest day, the pinned order yields 1 cent of interest on each — 2 cents total — where summing first would yield only 1). The non-pecuniary components are then capped together: `capped_nonpecuniary_cents` is the smaller of (`compensatory_damages_cents` plus `punitive_damages_cents`) and the statutory cap tier for `band_used` — 5000000 cents for `FROM_15_TO_19` and `FROM_20_TO_100` alike, 10000000 cents for `FROM_101_TO_200`, 20000000 cents for `FROM_201_TO_500`, and 30000000 cents for `OVER_500`. An `UNDER_15` employer never reaches conciliation, so no tier is defined for it. Finally, `total_cents` is the sum of `back_pay_cents`, `front_pay_cents`, `back_pay_interest_cents`, `front_pay_interest_cents`, and `capped_nonpecuniary_cents`; since every component is already whole cents, no rounding occurs at this summation.

### 3.8. Right-to-Sue Notices and Settlement Vacatur

A right-to-sue notice releases the charging party to court and starts their filing clock. Exactly one notice may ever exist for a charge; a request made when one already exists is rejected with `ERR_INVALID_STATE`. Issuance is open to the `ChargingParty` and the `Director`, with two distinct gates. The charging-party path requires `days_elapsed_since_filing` of at least 180 — a request earlier than that is rejected with `ERR_RTS_PREMATURE` — and produces a notice whose `issuance_basis` is `ELAPSED_180_DAYS`. The Director may issue at discretion from any non-terminal, non-conciliating status, producing `issuance_basis` `DIRECTOR_DISCRETION`. A request made while the charge sits in `CONCILIATION` is rejected with `ERR_CONCILIATION_ACTIVE` — a live conciliation blocks issuance — and a request against a terminal charge is rejected with `ERR_CHARGE_ALREADY_CLOSED`, which outranks the prematurity check. The third basis, `AUTO_ON_DISMISSAL`, is system-only and arises from the no-cause approval cascade of §3.6; in that case `requested_by_role` is recorded as `system`, while party- and Director-initiated notices stamp the requesting role.

The notice records its `charge_id`, stamps `issued_date` from the logical clock, and computes `court_filing_deadline` as exactly 90 days after issuance — the charging party's window to file in court. The notice is `ISSUED` while the clock is on or before that deadline and flips to `EXPIRED` on read once the clock is strictly past it. Issuance moves the charge to the terminal `RTS_ISSUED` and closes out enforcement activity: the investigation case, if one exists, moves to `CLOSED` and its `PENDING`/`OVERDUE` evidence requests are `WAIVED`. The mediation side of the cascade is deliberately asymmetric by issuance state. From `DOCKETED`, any `OFFERED` mediation case is moved to `DECLINED`. From `IN_MEDIATION`, the mediation case is deliberately not touched — an `ACTIVE` or `OFFERED` mediation may be orphaned, and any later attempt to conclude it fails the charge-state gate of §3.4 — while the investigation, which may be sitting in `SUSPENDED_MEDIATION`, is closed with its requests waived. From `UNDER_INVESTIGATION` or `DETERMINATION_REVIEW`, the investigation closes and requests are waived. From `DELEGATED_TO_FEPA` or `LITIGATION_REFERRED`, only the notice and the charge's new status result.

A mediation settlement, unlike a conciliation settlement, carries a short regret window. Within 10 days of `settled_at` — the logical clock must be on or before `settled_at` plus 10 days; a later attempt is rejected with `ERR_VACATE_WINDOW_EXPIRED` — a `Director` may vacate, supplying a `reason`. Vacatur is available only when the charge is `CLOSED_SETTLED` with `settled_via` equal to `MEDIATION`; conciliation settlements are final and a vacate attempt against one is rejected with `ERR_INVALID_STATE`. On vacatur the charge reopens to `UNDER_INVESTIGATION` with `settled_amount_cents` zeroed and both `settled_via` and `settled_at` cleared to null; the `SETTLED` mediation case moves to `VACATED`, retaining its own `settlement_amount_cents` for audit; and the investigation reopens — an existing case moves `CLOSED` → `GATHERING`, or, if none exists, one is auto-created in `OPEN`.

### 3.9. Systemic Cases, Sealing, and Disclosure

A `Commissioner` may open a `SystemicCase` — a commissioner charge or pattern-or-practice investigation reaching beyond any individual complaint — by supplying a `title` and a `basis_focus`: a non-empty array of the same basis codes used on charges, naming the protected bases the probe targets. The creator is stamped as `commissioner_user_id`, and the case opens in `OPENED`.

Linking pulls individual charges into the probe. A link call names the target in `charge_id`; the charge must be non-terminal and not already linked to a systemic case, and the target case must not be `RESOLVED` — any of these is rejected with `ERR_INVALID_STATE`. Linking sets the charge's `systemic_case_id`, seals it by moving `disclosure_hold` to `SEALED` (engaging the read restrictions and access logging of §2.9), switches on the 1.5 priority multiplier of §3.5 for that charge, and re-evaluates consolidation. The case's `linked_charge_count` counts every linked charge regardless of those charges' statuses. The first link moves the case `OPENED` → `EXPANDING`.

Consolidation and resolution are threshold rules re-evaluated on every link and on every transition of a linked charge into a terminal state. The case becomes `CONSOLIDATED` once at least 3 linked charges are non-terminal and at least 2 of those non-terminal charges share a basis with `basis_focus` — that is, the intersection of the charge's `basis_codes` with the case's `basis_focus` is non-empty. The case becomes `RESOLVED` automatically once at least one charge is linked and no linked charge remains non-terminal. For this rule, a charge counts as terminal in `DISMISSED_UNTIMELY`, `DISMISSED_NO_JURISDICTION`, `CLOSED_NO_CAUSE`, `RTS_ISSUED`, `WITHDRAWN`, or `CLOSED_SETTLED` — every state except `DOCKETED`, `IN_MEDIATION`, `UNDER_INVESTIGATION`, `DETERMINATION_REVIEW`, `CONCILIATION`, `DELEGATED_TO_FEPA`, and `LITIGATION_REFERRED`. Resolution lifts the seal: every linked charge's `disclosure_hold` returns from `SEALED` to `NONE`.

Every release of charge data is audited. A `Director` records an explicit disclosure with a `legal_basis` of `COURT_ORDER`, `FEPA_WORK_SHARE`, or `PARTY_CONSENT` — the fourth value, `INTERNAL_ACCESS`, is never client-supplied; it is system-stamped on the automatic log rows that privileged reads of `SEALED` charges generate — and a `target_description` of who or what received the data (null on the automatic `INTERNAL_ACCESS` rows). On a `SEALED` charge only `COURT_ORDER` is permitted, per §2.9. Each `DisclosureRecord` stamps the acting `accessor_role` and `accessor_user_id` and the clock time `disclosed_at`. The audit log is append-only: there is no update or delete path, and a charge's disclosure list is the complete record of both explicit disclosures and privileged sealed reads.

## 4. Endpoint Definitions

All endpoints are mounted under the `/eeoc` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource, record a party action, or drive a state transition return `200 OK`, as do all reads. Request payloads, preconditions, cascades, and error triggers are specified in §2 and §3; this table is an index, not a restatement.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/eeoc/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/eeoc/deferral-agencies` | Register a state/local fair-employment agency | PlatformAdmin |
| POST | `/eeoc/employers` | Register a respondent employer | IntakeOfficer |
| PATCH | `/eeoc/employers/{id}` | Update verified headcount or legal name | IntakeOfficer |
| POST | `/eeoc/complainants` | Register a complainant | IntakeOfficer |
| POST | `/eeoc/charges` | File a charge with synchronous jurisdictional screening | IntakeOfficer, ChargingParty |
| GET | `/eeoc/charges/{id}` | Charge detail (sealed-read rules apply) | IntakeOfficer, ChargingParty, RespondentRep, Investigator, Mediator, Director, Commissioner, StateAgencyOfficer |
| GET | `/eeoc/charges` | Paginated charge list with filters | IntakeOfficer, Investigator, Director, Commissioner, StateAgencyOfficer |
| POST | `/eeoc/charges/{id}/amend` | Amend factual allegations (OCC-guarded) | ChargingParty |
| POST | `/eeoc/charges/{id}/withdraw` | Withdraw a charge | ChargingParty |
| POST | `/eeoc/charges/{id}/mediation-cases` | Offer mediation (initial offer or re-offer) | IntakeOfficer |
| GET | `/eeoc/charges/{id}/mediation-cases` | List a charge's mediation cases | IntakeOfficer, Mediator, Director, Commissioner, ChargingParty, RespondentRep |
| GET | `/eeoc/mediation-cases/{id}` | Mediation case detail (firewalled from Investigator) | IntakeOfficer, Mediator, Director, Commissioner, ChargingParty, RespondentRep |
| POST | `/eeoc/mediation-cases/{id}/respond` | Record the acting party's response to a mediation offer | ChargingParty, RespondentRep |
| POST | `/eeoc/mediation-cases/{id}/sessions` | Schedule a mediation session | Mediator |
| GET | `/eeoc/mediation-cases/{id}/sessions` | List sessions of a mediation case | Mediator, Director, IntakeOfficer, ChargingParty, RespondentRep |
| POST | `/eeoc/mediation-cases/{id}/conclude` | Conclude an active mediation (settle or impasse) | Mediator |
| GET | `/eeoc/investigation-cases/{id}` | Investigation case detail with live priority score | Investigator, Director, Commissioner |
| GET | `/eeoc/investigation-cases` | Paginated investigation list with caseload filters | Investigator, Director, Commissioner |
| POST | `/eeoc/investigation-cases/{id}/assign` | Assign or reassign the investigator | Director |
| POST | `/eeoc/investigation-cases/{id}/evidence-requests` | Issue a position-statement request, RFI, or document demand | Investigator |
| GET | `/eeoc/investigation-cases/{id}/evidence-requests` | List evidence requests of an investigation | Investigator, Director, Commissioner, RespondentRep |
| POST | `/eeoc/evidence-requests/{id}/respond` | Submit the respondent's response to an evidence request | RespondentRep |
| POST | `/eeoc/investigation-cases/{id}/interviews` | Log a witness interview | Investigator |
| GET | `/eeoc/investigation-cases/{id}/interviews` | List witness interviews of an investigation | Investigator, Director |
| POST | `/eeoc/investigation-cases/{id}/determinations` | Draft a determination | Investigator |
| GET | `/eeoc/investigation-cases/{id}/determinations` | List determinations of an investigation | Investigator, Director |
| POST | `/eeoc/determinations/{id}/submit` | Submit (or resubmit) a determination for review | Investigator |
| POST | `/eeoc/determinations/{id}/review` | Approve or return a pending determination | Director |
| GET | `/eeoc/charges/{id}/conciliation-processes` | List a charge's conciliation processes | Director, Commissioner, ChargingParty, RespondentRep |
| GET | `/eeoc/conciliation-processes/{id}` | Conciliation detail | Director, Commissioner, ChargingParty, RespondentRep |
| POST | `/eeoc/conciliation-processes/{id}/offers` | Table an offer (OCC-guarded, strictly alternating) | Director, RespondentRep |
| POST | `/eeoc/conciliation-processes/{id}/accept` | Accept the outstanding offer and settle | ChargingParty |
| POST | `/eeoc/conciliation-processes/{id}/fail` | Declare conciliation failed and refer for litigation | Director |
| GET | `/eeoc/conciliation-processes/{id}/remedy-packages` | List the conciliation's remedy package | Director, ChargingParty, RespondentRep |
| POST | `/eeoc/charges/{id}/right-to-sue-notices` | Issue a right-to-sue notice | ChargingParty, Director |
| GET | `/eeoc/charges/{id}/right-to-sue-notices` | List a charge's right-to-sue notices | ChargingParty, Director, IntakeOfficer |
| POST | `/eeoc/systemic-cases` | Open a systemic investigation | Commissioner |
| POST | `/eeoc/systemic-cases/{id}/links` | Link a charge into a systemic case | Commissioner |
| POST | `/eeoc/charges/{id}/disclosures` | Record an authorized disclosure of charge data | Director |
| GET | `/eeoc/charges/{id}/disclosures` | Audit log of disclosures for a charge | Director, Commissioner, IntakeOfficer |
| POST | `/eeoc/charges/{id}/vacate-settlement` | Vacate a mediation-path settlement within the window | Director |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION_FAILED` | 400 |
| `ERR_CHARGE_NOT_FOUND` | 404 |
| `ERR_EMPLOYER_NOT_FOUND` | 404 |
| `ERR_COMPLAINANT_NOT_FOUND` | 404 |
| `ERR_MEDIATION_CASE_NOT_FOUND` | 404 |
| `ERR_INVESTIGATION_CASE_NOT_FOUND` | 404 |
| `ERR_EVIDENCE_REQUEST_NOT_FOUND` | 404 |
| `ERR_DETERMINATION_NOT_FOUND` | 404 |
| `ERR_CONCILIATION_NOT_FOUND` | 404 |
| `ERR_SYSTEMIC_CASE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CHARGE_ALREADY_CLOSED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CONFIDENTIALITY_SEALED` | 403 |
| `ERR_DISCLOSURE_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_SESSION_OVERLAP` | 409 |
| `ERR_INTERVIEW_BUFFER_CONFLICT` | 409 |
| `ERR_MEDIATION_ROUND_EXHAUSTED` | 409 |
| `ERR_DETERMINATION_EXISTS` | 409 |
| `ERR_OFFER_OUT_OF_TURN` | 409 |
| `ERR_RTS_PREMATURE` | 422 |
| `ERR_CONCILIATION_ACTIVE` | 409 |
| `ERR_VACATE_WINDOW_EXPIRED` | 422 |
| `ERR_SESSION_IN_PAST` | 422 |
| `ERR_INCIDENT_DATE_FUTURE` | 422 |
| `ERR_DUPLICATE_AGENCY_STATE` | 409 |
