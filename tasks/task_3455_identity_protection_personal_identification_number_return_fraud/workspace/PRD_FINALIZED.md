# Identity Protection Return Fraud API — Product Requirements Document

## 1. Introduction

Tax-related identity theft reaches the Internal Revenue Service through two doors: a second return filed for the same taxpayer and tax year, and a victim's own report that someone else filed in their name. This document specifies the Identity Protection & Return Fraud API, the system of record for both doors. It governs how identity-theft victims are flagged and enrolled into the Identity Protection Personal Identification Number (IP PIN) program, how protection numbers are issued, delivered, and regenerated each filing season, and how incoming returns are scored by a configurable filtering model that holds suspicious refunds for review — accepting, as a deliberate policy trade-off, that a fraction of legitimate filers will carry a false-positive burden while their identity is proven.

The system further covers the full disposition pipeline that follows a hold: identity verification over online, phone, and in-person channels with channel-specific document requirements and hard deadlines; refund scheduling and release with statutory interest computed on delayed refunds; dependent-claim conflicts when two filers claim the same person, resolved by evidence, analyst decision, default, or fraud forfeit; refund-fraud scheme detection across preparer networks and bank-product routing patterns, with preparer suspension as the terminal sanction; and Taxpayer Advocate Service escalation for hardship cases, which compresses verification deadlines and prioritizes review. All endpoints are mounted under the `/identity-protection` prefix, with a single platform-level logical-clock endpoint that lives outside that prefix. Six cooperating roles operate the pipeline under strict segregation-of-duties rules, and every state change, cascade, and financial adjustment described here is driven by a controllable logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contract of the API: authentication, response envelopes, pagination, the logical clock, resource identity conventions, monetary precision, optimistic concurrency, the global validation order, nested-path resolution, and lifecycle discipline.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request with either header missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly six roles, spelled as follows: `Taxpayer`, `TaxPreparer`, `VerificationAgent`, `FraudAnalyst`, `TaxpayerAdvocate`, and `SystemAdmin`. Each endpoint declares the roles permitted to call it (see §4); a caller whose role is not in an endpoint's role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Taxpayer`, `X-User-ID` is the `id` of the acting `Taxpayer` record; ownership checks on any resource that references a taxpayer — returns, reports, pins, verification cases, advocate cases, appointments, holds, disbursements, and claims — compare the resource's taxpayer foreign key to `X-User-ID`, and acting on another taxpayer's resource is rejected with `ERR_UNAUTHORIZED` (HTTP 403). When `X-User-Role` is `TaxPreparer`, `X-User-ID` is the `id` of the acting `Preparer` record; ownership checks on returns compare the return's `preparer_id` to `X-User-ID`, so a preparer may file only returns carrying their own `preparer_id` and may read only their own preparer record, alerts, and filed returns.

The remaining four roles are opaque operator identities. When `X-User-Role` is `VerificationAgent`, `FraudAnalyst`, `TaxpayerAdvocate`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires an audit anchor — for example as `created_by_user_id` on an `IdentityTheftReport`, as `confirmed_by_user_id` on a `FraudSchemeAlert`, or as `opened_by_user_id` on an `AdvocateCase` — but never compares it to any entity's `id` for ownership.

Segregation of duties overlays role checks on two workflows: confirming an identity-theft report is forbidden to the user who created that report, and resolving an advocate case is forbidden to the user who opened it. Both violations are rejected with `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Scheduled Sweeps

The platform runs on a logical clock, not wall-clock time. At server startup the logical clock is exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time; every system-generated timestamp in the domain — a return's `received_at`, a document's `received_at`, a disbursement's `scheduled_at` and `released_at`, every deadline and window end — reads this clock. A SystemAdmin-only, test-driving capability sets the logical clock to a supplied instant: the request carries `to_iso8601`, and the response reports the new time as `current_utc`. This endpoint is deliberately mounted outside the API prefix at exactly `/_clock/set_current_utc` — it is not under `/identity-protection`.

Advancing the logical clock triggers exactly two sweeps. First, every `OPEN` dependent conflict whose `evidence_window_ends_at` is earlier than the new clock time is auto-resolved by the evidence rule described in §3.6. Second, every `BOOKED` verification appointment whose `end_at` has passed transitions to `COMPLETED`. Verification cases are deliberately not swept: a case leaves its open states only through a verification outcome or a third failed attempt, which keeps the document-deadline validation reachable at any clock position.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp is ISO 8601 UTC with three fractional digits, taken from the logical clock at creation. The `updated_at` timestamp follows the same format and refreshes on every mutation. The `version` is an integer that starts at its initial value on creation and increments by 1 on every mutation of the resource, including mutations caused by cascade side effects — for example, a theft-report confirmation that flips a taxpayer's flags increments that taxpayer's `version`.

`VerificationDocument` is the sole exception to this convention: as an immutable submission record it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.6. Monetary Values, Scores, and Rounding

All monetary amounts are represented as integer cents — the API surface names them accordingly (`claimed_refund_cents`, `prior_year_refund_cents`, `adjustment_cents`, `credit_cents`, `base_cents`, `provisional_interest_cents`, `final_interest_cents`, `amount_cents`, `expected_amount_cents`) — and all interest arithmetic produces integer cents using round-half-up. Two rounding disciplines apply and must not be interchanged: the provisional interest estimate performs a single round-half-up at the end of the computation, while the final interest computation rounds each interest component individually and then sums the already-rounded components (summing first and rounding once at the end is explicitly rejected). Risk scores are integers; the refund-delta component of the score uses floor division into whole steps, and the final score is clamped into the inclusive range 0 to 100. Counts produced by batch and scan operations are integers compared with at-least thresholds, so a count exactly at a threshold fires the threshold's effect.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, both anchored on the `Taxpayer` aggregate: the taxpayer profile update, and the manual IP PIN reissue. Each of these requests must carry `expected_taxpayer_version`, a non-optional input field holding the caller's last observed `version` of the target `Taxpayer`. If the taxpayer's current `version` no longer equals `expected_taxpayer_version` — because another writer, such as a profile edit or a report-confirmation cascade, has legitimately advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller must re-read the taxpayer before retrying. In the reissue case this guard matters because a reissue supersedes the prior `ACTIVE` pin, so issuing from a stale taxpayer view could supersede a pin the caller never saw. No other endpoint accepts or requires a version field.

### 2.8. Validation Order for Incoming Requests

Every request is validated against the following checks in strict priority order; the first failing check determines the response, so a higher-priority rejection always masks lower-priority ones.

1. **Authentication.** `X-User-ID` and `X-User-Role` are present and non-empty, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization.** The caller's role is listed in the endpoint's authorized roles, else `ERR_UNAUTHORIZED` (HTTP 403).
3. **Ownership and segregation of duties.** Entity-backed ownership: a `Taxpayer` caller may act only on resources whose `taxpayer_id` equals their `X-User-ID`, and a `TaxPreparer` caller only on returns whose `preparer_id` equals their `X-User-ID`; an ownership mismatch yields `ERR_UNAUTHORIZED` (HTTP 403). Segregation of duties: confirming a report whose `created_by_user_id` equals the caller's `X-User-ID`, or resolving an advocate case whose `opened_by_user_id` equals the caller's `X-User-ID`, yields `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403).
4. **Path existence.** Path identifiers resolve to existing resources, validated left to right as described in §2.9, else the resource-specific 404.
5. **Optimistic concurrency.** On the two OCC-guarded writes, `expected_taxpayer_version` equals the taxpayer's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
6. **State permission.** The target entity's current state permits the requested transition; requests against entities in a terminal state are rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) and all other impermissible transitions with `ERR_INVALID_STATE` (HTTP 409).
7. **Filing gate.** For return intake only: an `ENROLLED` filer must present `ip_pin_submitted` (absent yields `ERR_IP_PIN_REQUIRED`, HTTP 422) and it must equal the `ACTIVE` pin for that taxpayer and tax year (mismatch yields `ERR_IP_PIN_MISMATCH`, HTTP 422); the named preparer must not be `SUSPENDED` (else `ERR_PREPARER_SUSPENDED`, HTTP 409).
8. **Uniqueness and exclusivity.** A duplicate `tin` on taxpayer creation yields `ERR_DUPLICATE_TIN` (HTTP 409); a second non-terminal return for the same taxpayer TIN and tax year yields `ERR_DUPLICATE_RETURN` (HTTP 409); a claim on a dependent TIN and tax year that already has an `OPEN` conflict yields `ERR_DEPENDENT_CONFLICT_OPEN` (HTTP 409); a second non-terminal verification case for the same return yields `ERR_CASE_ALREADY_OPEN` (HTTP 409); and uniqueness violations of `ptin`, `office_code`, or `model_version` yield `ERR_INVALID_REQUEST` (HTTP 400).
9. **Temporal-window exclusivity.** A new theft report submitted inside the closed 60-day review window of the taxpayer's existing `SUBMITTED` report yields `ERR_ACTIVE_REPORT_WINDOW` (HTTP 409); a new appointment whose interval would breach office capacity yields `ERR_APPOINTMENT_CAPACITY_EXCEEDED` (HTTP 409).
10. **Document deadline.** A document submitted after the case's `deadline_at` yields `ERR_VERIFICATION_WINDOW_EXPIRED` (HTTP 422).
11. **Cross-entity requirements.** Release of a held refund without a `VERIFIED` linked case yields `ERR_VERIFICATION_INCOMPLETE` (HTTP 422); a verification case for a `GRAY`-zone hold opened on a channel other than `ONLINE`, or an appointment booked for a case whose channel is not `IN_PERSON`, yields `ERR_CHANNEL_NOT_ALLOWED` (HTTP 422); a verification case opened for a return that is not `FILTER_HELD` yields `ERR_RETURN_NOT_HELD` (HTTP 409); expediting a hardship case without a linked `FILTER_HELD` return yields `ERR_HARDSHIP_NOT_EXPEDITABLE` (HTTP 409); opt-out or manual pin reissue while not `ENROLLED` yields `ERR_NOT_ENROLLED` (HTTP 422); filing a return when no filter model config is `ACTIVE` yields `ERR_CONFIG_NOT_ACTIVE` (HTTP 409).
12. **Money consistency.** A disbursement release whose `expected_amount_cents` does not equal the computed total yields `ERR_DISBURSEMENT_AMOUNT_MISMATCH` (HTTP 422).
13. **Config coherence.** A filter model config whose `gray_zone_threshold` is not strictly below its `hold_threshold`, at creation or activation, yields `ERR_THRESHOLD_ORDER_INVALID` (HTTP 422).
14. **Payload shape.** Required fields present, enum values inside their declared sets, well-formed dates and TINs (a `tin` is exactly 9 digits), appointment `end_at` strictly after `start_at`, `tax_year` equal to 2026 unless an operation states otherwise, and integers within range — violations yield `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Nested Resource Retrieval

Endpoints whose paths contain multiple identifiers validate them strictly left to right, and the first identifier that does not resolve to an existing resource determines the error. A request for a taxpayer's theft reports under a non-existent taxpayer id fails with `ERR_TAXPAYER_NOT_FOUND` (HTTP 404) before any report lookup is attempted. Each resource type has its own not-found error: `ERR_TAXPAYER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CONFLICT_NOT_FOUND`, `ERR_PREPARER_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_OFFICE_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_CONFIG_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, and `ERR_ADVOCATE_CASE_NOT_FOUND`, all HTTP 404. The same rule governs identifiers carried in request bodies, such as a `taxpayer_id` or `case_id` that names a missing resource.

### 2.10. Lifecycle Discipline and Terminal States

Every entity in the domain follows a state machine, and §3 narrates each machine's transitions with their guards and side effects. Two rejection modes discipline all transitions. A request that targets an entity in one of the terminal states `REFUND_RELEASED`, `FRAUD_CONFIRMED`, `RELEASED`, `CANCELLED`, `VERIFIED`, `EXPIRED`, `RESOLVED`, `RETIRED`, or `SUSPENDED` is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409): terminal entities accept no further transitions. Any other transition attempt that the entity's current state does not permit is rejected with `ERR_INVALID_STATE` (HTTP 409) — this covers, for example, actions against pins in `SUPERSEDED` or `REVOKED`, holds in any `RESOLVED_*` state, claims in `SUSTAINED` or `DISALLOWED`, alerts in `CONFIRMED_SCHEME` or `CLEARED`, appointments in `COMPLETED`, and theft reports in `CONFIRMED`, none of which are classified as terminal even though they admit no outbound transitions. State transitions triggered internally by the server — intake scoring, verification outcomes, clock sweeps, fraud cascades — mutate the affected resources directly, refreshing `updated_at` and incrementing `version` on each mutated resource, without requiring a client request addressed to that resource.

## 3. Business Logic & Workflows

### 3.1. Registries: Taxpayers, Preparers, and Service Offices

Before anything can be filed, flagged, or verified, the platform's registries must exist. A `SystemAdmin` registers each taxpayer with a `tin` (exactly 9 digits, unique across all taxpayers — a duplicate is rejected with `ERR_DUPLICATE_TIN`), a `full_name`, a `date_of_birth` in ISO 8601 `YYYY-MM-DD` form, an optional `prior_year_refund_cents` recording the refund claimed on the prior year's accepted return (an integer no smaller than 0, defaulting to 0, and later fed into refund-delta scoring), and an optional `pin_delivery_channel` preference of `POSTAL_MAIL` or `ONLINE_ACCOUNT` that defaults to `POSTAL_MAIL`. A newly registered taxpayer has `status` `ACTIVE` and `ip_pin_enrollment` `NOT_ENROLLED`; both flags are system-managed. The `status` flag moves to `VICTIM_FLAGGED` when one of the taxpayer's theft reports is confirmed and never reverts, while `ip_pin_enrollment` cycles through the enrollment transitions of §3.2.

Profile stewardship is shared between the taxpayer and the platform: a `Taxpayer` acting on their own record, or a `SystemAdmin`, may update `full_name`, `date_of_birth`, `prior_year_refund_cents`, and `pin_delivery_channel`. This update is one of the two OCC-guarded writes of §2.7 — the request must carry `expected_taxpayer_version` matching the taxpayer's current `version`, a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and a successful update increments the taxpayer's `version` by exactly 1.

A `SystemAdmin` also registers each return preparer with a `ptin` (unique; a duplicate yields `ERR_INVALID_REQUEST`) and a display `firm_name`. A preparer starts `ACTIVE` with `filed_return_count` at 0; that counter is recomputed — incremented by 1 — on every return intake that names the preparer, whether the intake ends in a pass or a hold. Suspension is terminal: a `SUSPENDED` preparer accepts no further state changes and can never file again.

In-person identity proofing happens at registered offices. A `SystemAdmin` registers each office with a unique `office_code`, a display `name`, and a `capacity` of at least 1. The `capacity` is the office's overlap ceiling: it bounds the number of `BOOKED` appointments whose half-open intervals may share any single instant, and §3.5 describes how booking enforces it.

### 3.2. The Identity Protection PIN Program

Enrollment is voluntary and self-service. A taxpayer — acting for themselves, or with a `SystemAdmin` acting on their behalf — opts in by supplying a `tax_year` and, optionally, a `delivery_channel` that overrides their `pin_delivery_channel` preference for the issued pin. Opting in is permitted from `NOT_ENROLLED` and from `OPTED_OUT`; attempting it while already `ENROLLED` is rejected with `ERR_INVALID_STATE`. On success the taxpayer's `ip_pin_enrollment` becomes `ENROLLED`, the taxpayer's `version` increments by 1, and a `ProtectionPin` is minted for the supplied tax year: the pin carries a server-generated 6-digit `pin_value` unique per taxpayer and tax year, a `delivery_channel` taken from the request or defaulted from the taxpayer's preference, and `status` `ACTIVE`. At most one pin may be `ACTIVE` for a given taxpayer and tax year, so minting the new pin flips any previously `ACTIVE` pin for that same pair to `SUPERSEDED`.

Leaving the program revokes everything: opting out requires the taxpayer to be `ENROLLED` (otherwise the request is rejected with `ERR_NOT_ENROLLED`, HTTP 422), moves `ip_pin_enrollment` to `OPTED_OUT`, transitions every `ACTIVE` pin of that taxpayer to `REVOKED`, and increments the taxpayer's `version` by 1. Pins therefore live a simple lifecycle — `ACTIVE` at creation, then terminally `SUPERSEDED` whenever a replacement pin is minted for the same taxpayer and tax year (by opt-in, manual reissue, report confirmation, or annual regeneration), or terminally `REVOKED` on opt-out. A taxpayer, `SystemAdmin`, `FraudAnalyst`, or `TaxpayerAdvocate` may list a taxpayer's pins across all statuses.

Manual reissue is the service-desk path, available to `SystemAdmin` and `TaxpayerAdvocate`. The request names the `taxpayer_id`, the `tax_year`, an optional `delivery_channel`, and — because reissue is the second OCC-guarded write of §2.7 — a mandatory `expected_taxpayer_version`; a version that no longer matches is rejected with `ERR_STALE_VERSION` (HTTP 412). Reissue requires the taxpayer to be `ENROLLED` (else `ERR_NOT_ENROLLED`), creates the new pin in `ACTIVE`, supersedes the prior `ACTIVE` pin of the same taxpayer and tax year, and increments the taxpayer's `version` by 1.

Once per filing season a `SystemAdmin` runs the annual regeneration batch, supplying the new `tax_year`. The batch walks every taxpayer whose `ip_pin_enrollment` is `ENROLLED`, processed in `created_at` ascending order. For each taxpayer: if an `ACTIVE` pin already exists for that taxpayer and the batch's tax year, the taxpayer is skipped and counted in `skipped_count`; otherwise a new `ACTIVE` pin is created for the batch's tax year with `delivery_channel` taken from the taxpayer's `pin_delivery_channel`, every `ACTIVE` pin of that taxpayer belonging to a different tax year becomes `SUPERSEDED`, and the taxpayer is counted in `created_count`. The run reports `created_count`, `superseded_count` (the number of prior-year pins the run superseded), and `skipped_count`, and is idempotent per tax year: re-running it with the same `tax_year` creates nothing, so `created_count` comes back 0 and every previously created pin is counted as skipped.

### 3.3. Identity Theft Reports and Victim Flagging

A theft report opens the victim track. A `Taxpayer` files one for themselves, or a `FraudAnalyst` files on a victim's behalf, supplying a `source` and an optional free-text `description` that defaults to an empty string. The `source` is `TAXPAYER_REPORT` for victim-originated filings; `DUPLICATE_DETECTION` is reserved for reports the system auto-creates when it catches a duplicate filing (§3.4), and on those auto-created rows `created_by_user_id` holds the literal `system` rather than a user id — otherwise `created_by_user_id` records the filing caller's `X-User-ID`. A new report starts `SUBMITTED`, with `confirmed_tax_year` null until confirmation.

Reports have a review-window exclusivity rule. While a taxpayer has a report in `SUBMITTED`, a further report for that taxpayer is rejected with `ERR_ACTIVE_REPORT_WINDOW` (HTTP 409) whenever the new submission time falls inside the closed review window that runs from the earlier report's `created_at` through 60 days later, both endpoints inclusive. Once the earlier report leaves `SUBMITTED`, or the window has fully passed, a new report is accepted.

Confirmation is the consequential act, and it belongs to a `FraudAnalyst` who is not the report's creator — segregation of duties rejects a confirming caller whose `X-User-ID` equals the report's `created_by_user_id` with `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403). Only a `SUBMITTED` report can be confirmed, and the confirmation payload carries the `tax_year` for which protection is being granted. Confirmation fires a three-link cascade plus a stamp: first, the subject taxpayer's `status` becomes `VICTIM_FLAGGED` and their `ip_pin_enrollment` becomes `ENROLLED`, incrementing the taxpayer's `version`; second, because the taxpayer is now enrolled, a `ProtectionPin` is created for the payload tax year in `ACTIVE`; third, that minting supersedes any previously `ACTIVE` pin for the same taxpayer and tax year; and the report's `confirmed_tax_year` is set to the payload `tax_year`. Rejection is the quiet sibling: a `FraudAnalyst` moves a `SUBMITTED` report to `REJECTED` with no side effects.

The report lifecycle is cyclic in one place only: a `REJECTED` report may be reopened to `SUBMITTED` by the taxpayer themselves or by a `TaxpayerAdvocate`, re-entering review. `CONFIRMED` is sticky — it admits no outbound transitions — so a confirmed victim flag is permanent, matching the taxpayer-level rule that `VICTIM_FLAGGED` never reverts.

### 3.4. Return Intake, Risk Scoring, and Filter Holds

Filing a return is the system's main event, and a single intake request runs validations, dependent-claim creation, conflict detection, risk scoring, and scheme scans before it answers. A `Taxpayer` files their own return; a `TaxPreparer` files returns carrying their own `preparer_id` (a null `preparer_id` marks a self-filed return). The filing payload names the `taxpayer_id`, the `tax_year` (this deployment serves tax year 2026; any other value is rejected with `ERR_INVALID_REQUEST`), a `filing_status` of `SINGLE`, `MARRIED_JOINT`, or `HEAD_OF_HOUSEHOLD`, the `claimed_refund_cents` (an integer no smaller than 0), an optional `ip_pin_submitted` defaulting to null, an optional `bank_product` of `NONE` or `REFUND_TRANSFER` defaulting to `NONE`, an optional `bank_account_fingerprint` that hashes the deposit account and stays null when `bank_product` is `NONE`, and an optional `dependents` array. The intake stamps `received_at` from the logical clock.

The gate sequence follows the global order of §2.8, and its filing-specific steps deserve emphasis. Filing requires an `ACTIVE` filter model config; when no config is `ACTIVE` the filing is rejected with `ERR_CONFIG_NOT_ACTIVE` (HTTP 409). If the filer's `ip_pin_enrollment` is `ENROLLED`, the filing must present `ip_pin_submitted` — its absence yields `ERR_IP_PIN_REQUIRED` (HTTP 422) — and the presented value must equal the `ACTIVE` pin for that taxpayer and tax year, else `ERR_IP_PIN_MISMATCH` (HTTP 422); filers who are `NOT_ENROLLED` or `OPTED_OUT` carry no pin requirement. A filing that names a `SUSPENDED` preparer is rejected with `ERR_PREPARER_SUSPENDED` (HTTP 409). At most one non-terminal return may exist per taxpayer TIN and tax year: a filing that collides with a live earlier return is rejected with `ERR_DUPLICATE_RETURN` (HTTP 409) — and this rejection is itself a fraud signal, so the system still auto-creates an `IdentityTheftReport` with `source` `DUPLICATE_DETECTION` and `created_by_user_id` `system` against that taxpayer, even though the filing fails.

Each entry of the `dependents` array creates a `DependentClaim` on the new return, carrying the claimed person's `dependent_tin` (exactly 9 digits) and a `relationship` of `CHILD`, `STEPCHILD`, `SIBLING`, `PARENT`, or `OTHER`. Every claim's `credit_cents` is fixed at 200000 cents — the dependent credit at stake — and every claim starts `CLAIMED`. Conflict detection then runs per claim. If a different return already holds a claim on the same dependent TIN and tax year, both the pre-existing claim and the new claim flip to `CONTESTED`, and a `DependentConflict` is created as §3.6 describes — this flip happens inside the same intake request, before scoring. If that dependent TIN and tax year already sit inside an `OPEN` conflict, the filing is refused outright with `ERR_DEPENDENT_CONFLICT_OPEN` (HTTP 409).

Only after all validations pass and the claims and any conflicts exist does the filter model score the return, using the weights of the single `ACTIVE` `FilterModelConfig`. The score assembles five weighted signals plus an interaction term. The refund-delta signal measures the absolute difference between the return's `claimed_refund_cents` and the taxpayer's `prior_year_refund_cents`, divides it into whole steps of 100000 cents (that is, $1,000 per step) using floor division, and caps the result at 3 steps; the config's `w_refund_delta` weight is applied once per step. The victim signal adds `w_victim_flagged` when the taxpayer's `status` is `VICTIM_FLAGGED`. The bank-product signal adds `w_bank_product` when the return's `bank_product` is `REFUND_TRANSFER`. The preparer signal adds `w_preparer_flagged` when the return names a preparer and that preparer currently has a `FLAGGED` scheme alert. The dependent signal adds `w_dependent_conflict` when any claim on the return is `CONTESTED` at intake — including claims that flipped to `CONTESTED` by conflict creation within this same request. Finally, when the taxpayer is `VICTIM_FLAGGED` and the return routes through a `REFUND_TRANSFER` bank product at the same time, the config's `interaction_bonus` is added on top. The raw sum is clamped to an integer score no lower than 0 and no higher than 100, the score cap.

The score selects the return's tier, and `RECEIVED` is transient — the creation response already shows the post-scoring state. A score that reaches the config's `hold_threshold` moves the return to `FILTER_HELD` and opens a `FilterHold` in zone `FULL`. A score at or above the `gray_zone_threshold` but still below the `hold_threshold` also moves the return to `FILTER_HELD`, with the hold in zone `GRAY`. A score below the `gray_zone_threshold` moves the return to `FILTER_PASSED` with no hold. Either way, the return's `risk_score` records the computed score and its `scoring_model_version` stamps the `model_version` of the config that scored it — so activating a new config changes the scores of identical payloads from that moment on, while previously scored returns keep their original stamp. A return holds at most one `FilterHold`: the hold copies the intake `risk_score` and `model_version`, records its `zone`, lists machine `reason_codes` drawn from the signals that contributed — `REFUND_DELTA`, `BANK_PRODUCT`, `VICTIM_FLAGGED`, and `INTERACTION` for intake holds, with `SCHEME_CONFIRMED` reserved for cascade-created holds — starts with `priority_review` false, and opens in `OPEN`. Whenever the filing named a preparer, that preparer's `filed_return_count` is recomputed with an increment of 1 on both the pass and the hold path.

Filter model governance sits with the `SystemAdmin`. A config is created in `DRAFT` with a unique `model_version` label (a duplicate yields `ERR_INVALID_REQUEST`) and nine integer knobs: the five weights `w_victim_flagged`, `w_refund_delta`, `w_bank_product`, `w_preparer_flagged`, and `w_dependent_conflict`, the `interaction_bonus`, the `gray_zone_threshold`, and the `hold_threshold`. The thresholds must be coherent — `gray_zone_threshold` strictly below `hold_threshold` — both at creation and again at activation, or the request is rejected with `ERR_THRESHOLD_ORDER_INVALID` (HTTP 422). Activating a config requires it to be `DRAFT` (activating a config in any other non-terminal state yields `ERR_CONFIG_NOT_DRAFT`, HTTP 409, while activating a `RETIRED` config is rejected with `ERR_ALREADY_TERMINAL`, HTTP 409, under the terminal-state rule of §2.10); activation moves it to `ACTIVE` and retires the previously `ACTIVE` config to `RETIRED`, so exactly one config is `ACTIVE` at any moment.

### 3.5. Identity Verification: Channels, Documents, and Appointments

A held return is released only through identity proofing, and the proofing case is its own lifecycle. A `FraudAnalyst` or `VerificationAgent` opens a case by naming the `taxpayer_id`, a `channel` of `ONLINE`, `PHONE`, or `IN_PERSON`, and optionally a `return_id`. Omitting `return_id` creates an enrollment-verification case — account-level proofing not tied to any filing. Supplying `return_id` creates a return-linked case, and then three requirements bind: the return must currently be `FILTER_HELD` (else `ERR_RETURN_NOT_HELD`, HTTP 409); when the return's hold is a `GRAY`-zone hold the channel must be `ONLINE` — the lighter-touch review is deliberately remote-only — and any other channel is rejected with `ERR_CHANNEL_NOT_ALLOWED` (HTTP 422); and no second non-terminal case may already exist for that return (else `ERR_CASE_ALREADY_OPEN`, HTTP 409).

A new case opens in `OPENED` with `attempts_count` at 0. Its `deadline_at` is set to 30 days after creation by the logical clock, and its `required_document_types` derive from the channel: an `ONLINE` case requires `PHOTO_ID` and `PRIOR_YEAR_RETURN`; a `PHONE` case requires `PHOTO_ID` and `SSA_CARD`; an `IN_PERSON` case requires `PHOTO_ID` and `UTILITY_BILL`. Cases can be listed filtered by `return_id`, `taxpayer_id`, or `status`, and read individually.

A `VerificationAgent` moves a case into document collection by requesting documents, which is permitted from `OPENED` and from `FAILED` alike — this is the retry-loop entry — and lands the case in `DOCS_REQUESTED`. The taxpayer (for their own case) or a `VerificationAgent` then submits documents, one `doc_type` per submission, drawn from `PHOTO_ID`, `PRIOR_YEAR_RETURN`, `W2`, `SSA_CARD`, and `UTILITY_BILL`; each accepted submission creates an immutable `VerificationDocument` for the case stamped with `received_at` from the logical clock, and the case's document list can be read back. Two guards apply at submission: the case must be in `DOCS_REQUESTED` under the general state rule, and the current logical time must be at or before the case's `deadline_at` — a document arriving after the deadline is rejected with `ERR_VERIFICATION_WINDOW_EXPIRED` (HTTP 422). Coverage is computed over the set of received `doc_type` values: the moment that set covers `required_document_types`, the case auto-advances from `DOCS_REQUESTED` to `DOCS_SUBMITTED`. Extra document types beyond the required set are accepted and stored but do not change the transition.

Verification itself is a `VerificationAgent` decision on a `DOCS_SUBMITTED` case (any other state is rejected with `ERR_INVALID_STATE`). A successful verification moves the case to `VERIFIED`, and when the case is return-linked and the return is still `FILTER_HELD`, the return passes the filter — `FILTER_HELD` to `FILTER_PASSED` — and its `OPEN` hold resolves as `RESOLVED_VERIFIED`. A failed verification attempt is recorded by the same role against a case in `DOCS_REQUESTED` or `DOCS_SUBMITTED`. The first and second failures increment `attempts_count` by 1 and move the case to `FAILED`, from which another document request re-enters the loop. The third failure is terminal and severe: with `attempts_count` reaching its maximum of 3, the case lands in `EXPIRED` instead of `FAILED` with `attempts_count` set to 3, and — when the case is return-linked to a `FILTER_HELD` return — the expiry cascades the return to `FRAUD_CONFIRMED`, which in turn disallows the return's dependent claims, resolves any `OPEN` dependent conflicts involving those claims by fraud forfeit, and resolves the return's `OPEN` hold as `RESOLVED_FRAUD`, exactly as §3.8's fraud cascade specifies.

In-person proofing is scheduled. A `VerificationAgent` books an appointment at a registered office for a case by supplying the `case_id`, a `start_at`, and an `end_at`; the created appointment records the hosting office as its `office_id`. The case must be an `IN_PERSON` case — booking against any other channel is rejected with `ERR_CHANNEL_NOT_ALLOWED` — and the interval is half-open: it occupies every instant from `start_at` up to but not including `end_at`, and `end_at` must be strictly after `start_at` (else `ERR_INVALID_REQUEST`). The office's `capacity` caps simultaneous bookings: a new appointment is rejected with `ERR_APPOINTMENT_CAPACITY_EXCEEDED` (HTTP 409) when any instant inside its half-open interval would bring the number of overlapping `BOOKED` appointments at that office to the office's capacity. An appointment starts `BOOKED` and completes on its own — when the logical clock advances past its `end_at`, the clock sweep moves it to `COMPLETED`. Appointments can be listed per office and per case.

### 3.6. Dependent Claims and Conflict Resolution

When two returns claim the same person, neither filer keeps the credit by default — the dispute becomes a first-class workflow. The `DependentConflict` record created at intake (§3.4) captures the `dependent_tin` and `tax_year` in dispute, names the earlier-filed return as `return_a_id` and the later-filed return as `return_b_id` — ordering by `received_at`, with ties broken by `created_at` ascending — sets an `evidence_window_ends_at` exactly 30 days after the conflict's creation, starts both `evidence_a_submitted` and `evidence_b_submitted` at false, leaves `resolution` and `resolved_reason` null, and opens in `OPEN`. Conflicts can be listed with `dependent_tin`, `status`, `return_a_id`, or `return_b_id` filters and read individually; each return's own claims can be listed from the return.

During the evidence window, each side may submit supporting evidence: a `Taxpayer` submits for their own side, or a `FraudAnalyst` submits on a filer's behalf, supplying a `side` that identifies which filer the evidence supports plus an optional `note`. Evidence for the earlier filer sets `evidence_a_submitted` true; evidence for the later filer sets `evidence_b_submitted` true. There is deliberately no late-evidence error of its own: because the clock sweep auto-resolves an expired conflict before any late evidence can arrive, evidence offered after the window meets `ERR_CONFLICT_ALREADY_RESOLVED` (HTTP 409) instead.

Resolution forks three ways, and the branch determines the side effects. An analyst decision — a `FraudAnalyst` resolving an `OPEN` conflict with a payload `winner` naming the first or second filer — requires the conflict to still be `OPEN` (a resolved conflict rejects further action with `ERR_CONFLICT_ALREADY_RESOLVED`, HTTP 409), records the payload winner as the `resolution` (`FIRST_FILER` or `SECOND_FILER`) with `resolved_reason` `ANALYST_DECISION`. A default resolution fires from the clock sweep of §2.4 when the clock advances past `evidence_window_ends_at` while the conflict is still `OPEN`: the `resolution` becomes `SECOND_FILER` exactly when `evidence_b_submitted` is true and `evidence_a_submitted` is false, and `FIRST_FILER` in every other evidence combination, with `resolved_reason` `DEFAULT_NO_EVIDENCE`. A fraud forfeit fires when one side's return becomes `FRAUD_CONFIRMED`: the `resolution` is the filer whose return is not fraud-confirmed, with `resolved_reason` `FRAUD_FORFEIT`.

The financial consequence rides on the loser, and its shape depends on the branch. Under analyst decision and default resolution, the winner's claim moves from `CONTESTED` to `SUSTAINED` and the loser's claim moves to `DISALLOWED`, and the losing return absorbs a credit adjustment: the adjustment amount is the lesser of 200000 cents (the dependent credit at stake) and the losing return's `claimed_refund_cents`; that amount is subtracted from `claimed_refund_cents` — the minimum guarantees the floor of 0 is never breached — and the same signed amount is subtracted from the return's `adjustment_cents`, which accumulates negative adjustments. If the losing return happens to be `REFUND_SCHEDULED` at that moment, its disbursement re-syncs: `base_cents` is rewritten to the new `claimed_refund_cents` plus `adjustment_cents`, and `provisional_interest_cents` is recomputed under the provisional interest rules of §3.8 against the new base. Under fraud forfeit the money moves differently: the winning claim still moves to `SUSTAINED`, but the losing claim was already `DISALLOWED` by the fraud cascade itself, so no credit adjustment is applied — no double adjustment — because the fraud confirmation denies the losing return's entire refund. That same fraud-driven disallowance reaches every claim on the fraud-confirmed return, whether `CLAIMED` or `CONTESTED`, and carries no credit adjustment for the same reason.

### 3.7. Scheme Detection and Preparer Discipline

Beyond per-return scoring, two pattern scans watch for coordinated refund fraud, and they run after every return intake that carries the relevant signal — after each filing that names a `preparer_id`, and after each filing that carries a `bank_account_fingerprint`. Both scans window every return in the system, regardless of status, by `received_at` against the current logical clock, over the trailing 7-day window ending now, with both window bounds inclusive.

The preparer-velocity scan fires only when the newly filed return names a preparer and routes its refund through a `REFUND_TRANSFER` bank product. It counts the returns naming that same preparer with `bank_product` `REFUND_TRANSFER` whose `received_at` falls inside the window. When the count reaches at least 10 — a count of exactly 10 fires — and no `FLAGGED` alert already exists for that preparer, the system creates a `FraudSchemeAlert` with `pattern_type` `PREPARER_NETWORK_VELOCITY`. The alert's `evidence` object records `return_ids` (the matching returns' ids ordered by `received_at` ascending, ties broken by `created_at` ascending), the `window_days` (7), and the `match_count`.

The bank-product cluster scan fires only when the newly filed return carries a `bank_account_fingerprint`. It counts the distinct taxpayers across all returns sharing that fingerprint whose `received_at` falls inside the same inclusive 7-day window. When that distinct-taxpayer count reaches at least 3 — exactly 3 fires — and no `FLAGGED` alert already exists carrying that fingerprint in its `evidence`, the system creates a `FraudSchemeAlert` with `pattern_type` `BANK_PRODUCT_CLUSTER` and a null `preparer_id`, since routing clusters span self-filers; its `evidence` lists the matching returns under `return_ids` with the same ordering, plus `window_days` and `match_count`.

Alerts begin `FLAGGED` and are adjudicated by a `FraudAnalyst`. Clearing an alert moves it to `CLEARED` with no side effects. Confirming an alert — permitted only from `FLAGGED`, as is clearing; either action against a decided alert is rejected with `ERR_INVALID_STATE` — moves it to `CONFIRMED_SCHEME` and stamps `confirmed_by_user_id` with the confirming analyst's `X-User-ID`. Confirmation of a preparer-linked alert carries the heaviest cascade in the system: the named preparer moves from `ACTIVE` to `SUSPENDED`, terminally, and every one of that preparer's returns currently sitting in `FILTER_PASSED` is pulled back to `FILTER_HELD`; for each such return that has no hold yet, a `FilterHold` is created in zone `FULL` with `reason_codes` exactly `[SCHEME_CONFIRMED]`, its `risk_score` and `model_version` copied from the return's own stamped values. A preparer's alert history can be listed from the preparer record (optionally filtered by `status`), and the global alert feed can be listed with `pattern_type` and `status` filters and read individually by `FraudAnalyst` and `SystemAdmin` roles.

### 3.8. Refund Scheduling, Interest, and Disbursement

A return that has passed the filter — or been cleared from it — earns a scheduled refund. A `FraudAnalyst` schedules the refund of a `FILTER_PASSED` return directly. Scheduling from `FILTER_HELD` is also possible but guarded: a linked identity-verification case in `VERIFIED` must exist for the return, else the request is rejected with `ERR_VERIFICATION_INCOMPLETE` (HTTP 422). Scheduling moves the return to `REFUND_SCHEDULED` and creates the return's one and only `RefundDisbursement` — exactly one disbursement ever exists per return — in `SCHEDULED`. At creation the disbursement's `base_cents` is fixed as the return's `claimed_refund_cents` plus its `adjustment_cents` at that moment; `scheduled_at` is stamped from the logical clock; `released_at` and `final_interest_cents` stay null; and `provisional_interest_cents` carries the provisional interest estimate. While `SCHEDULED`, the disbursement's `amount_cents` reads as `base_cents` plus `provisional_interest_cents`. A return's disbursement (zero or one row) can be listed from the return.

Interest compensates the taxpayer when the refund leaves after the statutory interest-free window, and it is computed twice with two different disciplines. Both variants share an anchor date: the later of the return's filing date (the calendar date of its `received_at`) and the filing deadline for the return's tax year — for tax year 2026, that deadline is 2027-04-15. Both also share the statutory parameters: an interest-free window of 45 days after the anchor, an annual rate of 7.0 percent, and a 365-day year basis, giving a daily rate of 7 percent divided by 365.

The provisional variant runs at scheduling and projects the release date as the scheduling date itself. Its days-late count is the number of days from the anchor date to the scheduling date, minus the 45 interest-free days. When that count is zero or negative, `provisional_interest_cents` is 0. Otherwise it is the base multiplied by the daily rate multiplied by the days-late count, rounded half-up to integer cents in a single rounding at the end.

The final variant runs at release and compounds daily against the actual release date, rounding per component and then summing. Its component zero is the base as it stood at scheduling — the `claimed_refund_cents` at that time — accruing for the number of days from the anchor date to the release date minus the 45 interest-free days, floored at zero days. Each signed adjustment the return absorbed after scheduling forms its own component: an adjustment applied at its resolution date accrues from the later of (the anchor date plus 45 days) and that adjustment's resolution date through the release date, again floored at zero days. Each component's interest is that component multiplied by the growth factor of one plus the daily rate, raised to the component's day count, minus one — rounded half-up to integer cents individually. The `final_interest_cents` is the sum of those per-component rounded amounts; rounding once after summing is explicitly rejected, and for identical base and day counts the final figure therefore differs from the provisional estimate.

Release is a `SystemAdmin` act with a money-consistency handshake. The disbursement must be `SCHEDULED` — a disbursement already `RELEASED` or `CANCELLED` rejects the attempt with `ERR_ALREADY_TERMINAL` (HTTP 409). The release payload carries `expected_amount_cents`, which must equal the disbursement's `base_cents` plus the freshly computed `final_interest_cents`; a mismatch is rejected with `ERR_DISBURSEMENT_AMOUNT_MISMATCH` (HTTP 422), so the operator's expectation and the server's computation must agree to the cent before funds move. A successful release stamps `final_interest_cents`, finalizes `amount_cents` as `base_cents` plus `final_interest_cents`, sets `released_at` from the logical clock, moves the disbursement to `RELEASED`, and advances the return from `REFUND_SCHEDULED` to `REFUND_RELEASED`.

Fraud confirmation is the other way a held or scheduled return ends, and it belongs to a `FraudAnalyst`. Confirming fraud is permitted while the return is `FILTER_HELD` or `REFUND_SCHEDULED` — attempts against any other non-terminal state fail the state rule with `ERR_INVALID_STATE`, and against a terminal return with `ERR_ALREADY_TERMINAL`. The confirmation moves the return to `FRAUD_CONFIRMED` and fires the full cascade: the return's `OPEN` hold resolves as `RESOLVED_FRAUD`; any non-terminal linked verification case is forced to `EXPIRED`; every dependent claim on the return moves to `DISALLOWED` with no credit adjustment, since the entire refund is denied; and every `OPEN` dependent conflict involving any of those claims resolves by forfeit in favor of the other filer with `resolved_reason` `FRAUD_FORFEIT` (§3.6). When the confirmed return was `REFUND_SCHEDULED`, a compensation step additionally moves its `SCHEDULED` disbursement to `CANCELLED` — no funds move, and the base and interest are voided.

The compassionate counterweight is the false-positive release. A `FraudAnalyst` who judges a hold to be a mistake marks it as a false positive, which requires the hold to be `OPEN` (else `ERR_INVALID_STATE`): the hold resolves as `RESOLVED_FALSE_POSITIVE` and the return passes the filter, moving from `FILTER_HELD` to `FILTER_PASSED`. This path exists so legitimate filers caught by the model — the false-positive burden the program accepts — can be freed without a full identity-verification cycle.

### 3.9. Hardship Advocacy and Expedited Handling

When a delayed refund creates genuine hardship, the Taxpayer Advocate Service steps in through an `AdvocateCase`. A `TaxpayerAdvocate` opens a case naming the `taxpayer_id`, a `hardship_type` of `LEVY_THREAT`, `EVICTION`, `MEDICAL`, `UTILITY_SHUTOFF`, or `OTHER`, and optionally a `return_id` — omitting it opens an account-level hardship not tied to any filing. The case records the opener's `X-User-ID` as `opened_by_user_id`, starts with `expedited` false and an empty `resolution_note` default, and opens in `OPENED`. Cases can be listed with `taxpayer_id`, `return_id`, or `status` filters and read individually.

Expedited handling is the advocate's lever on a stuck refund, and it is available only from `OPENED`. It requires the case to name a `return_id` whose return is currently `FILTER_HELD` — expediting an account-level case, or one whose return is not held, is rejected with `ERR_HARDSHIP_NOT_EXPEDITABLE` (HTTP 409). A successful expedite moves the case to `EXPEDITED_REVIEW`, sets `expedited` true, flips the held return's `OPEN` hold to `priority_review` true, and compresses the verification clock: a linked non-terminal identity-verification case on the same return, if one exists, has its `deadline_at` shrunk to the earlier of its current deadline and seven days from now by the logical clock.

Resolution closes the loop from either `OPENED` or `EXPEDITED_REVIEW`, landing the case in `RESOLVED` with an optional `resolution_note` recorded from the request. Segregation of duties applies here as everywhere: the resolving advocate's `X-User-ID` must differ from the case's `opened_by_user_id`, or the request is rejected with `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403) — the advocate who opened a hardship case may not be the one who closes it.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — registering a taxpayer, filing a theft report, reissuing a pin, filing a return, opening a verification case, submitting a document, registering an office, booking an appointment, registering a preparer, opening an advocate case, or creating a filter model config — return `201 Created`; scheduling a refund also returns `201 Created` because its primary effect is creating the disbursement. All other operations — reads, lists, and state-transition actions — return `200 OK`. List endpoints accept the pagination parameters `limit` and `offset` (§2.3) plus the optional filter query parameters noted in §3: `taxpayer_id`, `preparer_id`, `status`, `return_id`, `dependent_tin`, `return_a_id`, `return_b_id`, and `pattern_type`. Request and response bodies follow the narratives of §3; this table is the routing and authorization contract only. Every path below is mounted exactly as written — note that the logical-clock endpoint is the single platform-level exception and lives outside the `/identity-protection` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/identity-protection/taxpayers` | Register a taxpayer | SystemAdmin |
| GET | `/identity-protection/taxpayers/{id}` | Read one taxpayer | SystemAdmin, FraudAnalyst, VerificationAgent, TaxpayerAdvocate, Taxpayer |
| PUT | `/identity-protection/taxpayers/{id}` | Update taxpayer profile; OCC-guarded on `expected_taxpayer_version`; increments the taxpayer's `version` by 1 | Taxpayer, SystemAdmin |
| POST | `/identity-protection/taxpayers/{id}/ip-pin-opt-in` | Enroll in the IP PIN program and issue an `ACTIVE` pin for `tax_year` | Taxpayer, SystemAdmin |
| POST | `/identity-protection/taxpayers/{id}/ip-pin-opt-out` | Leave the IP PIN program; all `ACTIVE` pins revoked | Taxpayer, SystemAdmin |
| POST | `/identity-protection/taxpayers/{id}/identity-theft-reports` | File an identity-theft report | Taxpayer, FraudAnalyst |
| GET | `/identity-protection/taxpayers/{id}/identity-theft-reports` | List a taxpayer's theft reports | Taxpayer, FraudAnalyst, TaxpayerAdvocate, SystemAdmin |
| POST | `/identity-protection/identity-theft-reports/{id}/confirm` | Confirm a theft report; cascades victim flag, enrollment, pin issuance and supersession | FraudAnalyst |
| POST | `/identity-protection/identity-theft-reports/{id}/reject` | Reject a theft report | FraudAnalyst |
| POST | `/identity-protection/identity-theft-reports/{id}/reopen` | Reopen a `REJECTED` report back to `SUBMITTED` | Taxpayer, TaxpayerAdvocate |
| GET | `/identity-protection/taxpayers/{id}/protection-pins` | List a taxpayer's IP PINs (all statuses) | Taxpayer, SystemAdmin, FraudAnalyst, TaxpayerAdvocate |
| POST | `/identity-protection/protection-pins` | Manually reissue an IP PIN; OCC-guarded; supersedes the `ACTIVE` pin of the same tax year; increments the taxpayer's `version` by 1 | SystemAdmin, TaxpayerAdvocate |
| POST | `/identity-protection/ops/annual-pin-regeneration` | Ops run: issue next-season pins to all `ENROLLED` taxpayers and supersede prior-year `ACTIVE` pins; idempotent per tax year | SystemAdmin |
| POST | `/identity-protection/tax-returns` | File a return; runs intake validations, dependent-claim creation and conflict detection, risk scoring, and scheme scans; duplicate filings are rejected but still auto-create a `DUPLICATE_DETECTION` theft report | Taxpayer, TaxPreparer |
| GET | `/identity-protection/tax-returns` | List returns with filters | FraudAnalyst, SystemAdmin, VerificationAgent |
| GET | `/identity-protection/tax-returns/{id}` | Read one return | Taxpayer, TaxPreparer, FraudAnalyst, VerificationAgent, TaxpayerAdvocate, SystemAdmin |
| POST | `/identity-protection/tax-returns/{id}/release-refund` | Schedule the refund disbursement; `FILTER_HELD` returns require a `VERIFIED` case | FraudAnalyst |
| POST | `/identity-protection/tax-returns/{id}/confirm-fraud` | Mark a held or scheduled return as fraud; cascades claim disallowance, conflict forfeit-resolution, case expiry and disbursement cancellation | FraudAnalyst |
| GET | `/identity-protection/tax-returns/{id}/dependent-claims` | List a return's dependent claims | Taxpayer, TaxPreparer, FraudAnalyst, SystemAdmin |
| GET | `/identity-protection/tax-returns/{id}/filter-holds` | List a return's filter holds (0 or 1 row) | Taxpayer, FraudAnalyst, VerificationAgent, TaxpayerAdvocate, SystemAdmin |
| GET | `/identity-protection/tax-returns/{id}/refund-disbursements` | List a return's disbursements (0 or 1 row) | Taxpayer, FraudAnalyst, SystemAdmin, TaxpayerAdvocate |
| POST | `/identity-protection/filter-holds/{id}/mark-false-positive` | Analyst releases a hold as a false positive (false-positive burden tracking) | FraudAnalyst |
| POST | `/identity-protection/verification-cases` | Open an identity-verification case for a held return (or an enrollment case with `return_id` omitted) | FraudAnalyst, VerificationAgent |
| GET | `/identity-protection/verification-cases` | List verification cases with filters | FraudAnalyst, VerificationAgent, TaxpayerAdvocate, SystemAdmin |
| GET | `/identity-protection/verification-cases/{id}` | Read one verification case | FraudAnalyst, VerificationAgent, TaxpayerAdvocate, SystemAdmin, Taxpayer |
| POST | `/identity-protection/verification-cases/{id}/request-documents` | Move case `OPENED`/`FAILED` to `DOCS_REQUESTED` (retry-loop entry) | VerificationAgent |
| POST | `/identity-protection/verification-cases/{id}/documents` | Submit a verification document; the case auto-advances to `DOCS_SUBMITTED` when required types are covered | Taxpayer, VerificationAgent |
| GET | `/identity-protection/verification-cases/{id}/documents` | List a case's documents | VerificationAgent, FraudAnalyst, Taxpayer, SystemAdmin |
| POST | `/identity-protection/verification-cases/{id}/verify` | Mark a `DOCS_SUBMITTED` case `VERIFIED`; the held return auto-passes | VerificationAgent |
| POST | `/identity-protection/verification-cases/{id}/fail` | Record a failed verification attempt; the third failure lands the case in `EXPIRED` and cascades fraud confirmation | VerificationAgent |
| POST | `/identity-protection/service-offices` | Register an in-person verification office | SystemAdmin |
| GET | `/identity-protection/service-offices/{id}` | Read one office | SystemAdmin, VerificationAgent, FraudAnalyst |
| POST | `/identity-protection/service-offices/{id}/appointments` | Book an in-person verification appointment; rejected when the half-open interval would push the overlapping `BOOKED` count to office capacity | VerificationAgent |
| GET | `/identity-protection/service-offices/{id}/appointments` | List an office's appointments | VerificationAgent, FraudAnalyst, SystemAdmin |
| GET | `/identity-protection/verification-cases/{id}/appointments` | List a case's appointments | VerificationAgent, FraudAnalyst, SystemAdmin, Taxpayer |
| GET | `/identity-protection/dependent-conflicts` | List dependent conflicts with filters | FraudAnalyst, TaxpayerAdvocate, SystemAdmin |
| GET | `/identity-protection/dependent-conflicts/{id}` | Read one dependent conflict | FraudAnalyst, TaxpayerAdvocate, SystemAdmin |
| POST | `/identity-protection/dependent-conflicts/{id}/submit-evidence` | Submit conflict evidence for one side within the evidence window | Taxpayer, FraudAnalyst |
| POST | `/identity-protection/dependent-conflicts/{id}/resolve` | Analyst resolves an `OPEN` conflict; the loser absorbs the dependent-credit adjustment | FraudAnalyst |
| POST | `/identity-protection/preparers` | Register a tax preparer | SystemAdmin |
| GET | `/identity-protection/preparers/{id}` | Read one preparer | SystemAdmin, FraudAnalyst, TaxPreparer |
| GET | `/identity-protection/preparers/{id}/fraud-scheme-alerts` | List a preparer's scheme alerts | FraudAnalyst, TaxPreparer, SystemAdmin |
| GET | `/identity-protection/fraud-scheme-alerts` | List all scheme alerts with filters | FraudAnalyst, SystemAdmin |
| GET | `/identity-protection/fraud-scheme-alerts/{id}` | Read one scheme alert | FraudAnalyst, SystemAdmin |
| POST | `/identity-protection/fraud-scheme-alerts/{id}/confirm` | Confirm a `FLAGGED` scheme alert; suspends the preparer and re-holds their passed returns | FraudAnalyst |
| POST | `/identity-protection/fraud-scheme-alerts/{id}/clear` | Clear a `FLAGGED` scheme alert | FraudAnalyst |
| POST | `/identity-protection/refund-disbursements/{id}/release` | Execute a scheduled disbursement; computes final interest; the payload amount must match the computed total | SystemAdmin |
| POST | `/identity-protection/advocate-cases` | Open a taxpayer-advocate hardship case | TaxpayerAdvocate |
| GET | `/identity-protection/advocate-cases` | List advocate cases with filters | TaxpayerAdvocate, FraudAnalyst, SystemAdmin |
| GET | `/identity-protection/advocate-cases/{id}` | Read one advocate case | TaxpayerAdvocate, FraudAnalyst, SystemAdmin |
| POST | `/identity-protection/advocate-cases/{id}/expedite` | Expedited handling for hardship: requires a linked `FILTER_HELD` return; prioritizes the hold and shrinks the case deadline | TaxpayerAdvocate |
| POST | `/identity-protection/advocate-cases/{id}/resolve` | Resolve an advocate case; segregation of duties forbids the opener resolving | TaxpayerAdvocate |
| POST | `/identity-protection/filter-model-configs` | Create a `DRAFT` filtering-model config | SystemAdmin |
| GET | `/identity-protection/filter-model-configs/{id}` | Read one model config | SystemAdmin, FraudAnalyst |
| POST | `/identity-protection/filter-model-configs/{id}/activate` | Activate a `DRAFT` config; retires the previously `ACTIVE` config | SystemAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving endpoint, outside the API prefix); advancing the clock sweeps expired evidence windows to default conflict resolutions and completes elapsed appointments | SystemAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. Trigger conditions are intentionally not repeated here — they are specified in the workflow narratives of §2 and §3 alongside the rules that raise them.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_DUTY_SEGREGATION_VIOLATION` | 403 Forbidden |
| `ERR_TAXPAYER_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CONFLICT_NOT_FOUND` | 404 Not Found |
| `ERR_PREPARER_NOT_FOUND` | 404 Not Found |
| `ERR_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_OFFICE_NOT_FOUND` | 404 Not Found |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONFIG_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_ADVOCATE_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_RETURN_NOT_HELD` | 409 Conflict |
| `ERR_CASE_ALREADY_OPEN` | 409 Conflict |
| `ERR_CONFLICT_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_CONFIG_NOT_DRAFT` | 409 Conflict |
| `ERR_CONFIG_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_TIN` | 409 Conflict |
| `ERR_DUPLICATE_RETURN` | 409 Conflict |
| `ERR_DEPENDENT_CONFLICT_OPEN` | 409 Conflict |
| `ERR_ACTIVE_REPORT_WINDOW` | 409 Conflict |
| `ERR_APPOINTMENT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PREPARER_SUSPENDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_IP_PIN_REQUIRED` | 422 Unprocessable Content |
| `ERR_IP_PIN_MISMATCH` | 422 Unprocessable Content |
| `ERR_NOT_ENROLLED` | 422 Unprocessable Content |
| `ERR_THRESHOLD_ORDER_INVALID` | 422 Unprocessable Content |
| `ERR_VERIFICATION_WINDOW_EXPIRED` | 422 Unprocessable Content |
| `ERR_VERIFICATION_INCOMPLETE` | 422 Unprocessable Content |
| `ERR_CHANNEL_NOT_ALLOWED` | 422 Unprocessable Content |
| `ERR_DISBURSEMENT_AMOUNT_MISMATCH` | 422 Unprocessable Content |
| `ERR_HARDSHIP_NOT_EXPEDITABLE` | 409 Conflict |
