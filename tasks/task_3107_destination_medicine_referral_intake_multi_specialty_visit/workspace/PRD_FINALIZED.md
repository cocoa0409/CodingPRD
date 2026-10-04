# Destination Medicine API — Product Requirements Document

## 1. Introduction

Destination medicine programs — flagship referral practices that draw patients from across the country and around the world — live or die on coordination. A patient in another state or another country sends records, waits for a physician to review them, clears a deposit, and only then boards a plane; on arrival, the program must compress consultations, imaging, and laboratory work from several specialties into an itinerary measured in days rather than weeks, and then hand results back to the home physician with a clear continuity plan. Every stage of that journey crosses departmental lines: intake coordinators, physician reviewers, financial counselors, and logistics staff each own one link of the chain, and no link may silently do another link's job.

This document specifies the Destination Medicine Referral Intake & Multi-Specialty Visit Bundling API. The system manages remote referral intake with medical-record acquisition and case review prior to travel authorization; appointment bundling that compresses multiple specialist visits, imaging, and testing into a short itinerary; financial clearance with tiered deposits and estimate letters for out-of-state and international patients; travel, lodging, and interpreter coordination for patients and their companions; remote second-opinion and remote-consult products for patients who do not travel; results communication back to the referring physician; and capacity allocation that reserves a per-specialty daily pool of appointment slots for destination patients so that local demand cannot crowd them out.

The API is rooted at the path level (`/referrals`, `/visit-cases`, `/slots`, and so on — there is no versioned mount prefix) and is built around a strict segregation-of-duties role model, a tiered deposit and dual-variant estimate calculation engine, optimistic concurrency control on itinerary booking, and a logical clock that governs all temporal rules so that deadlines, visit-due checks, and review-day accounting are fully deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are present, the role is checked against the permission matrix; an authenticated user attempting an operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly five roles, spelled as follows: `PlatformAdmin`, `IntakeCoordinator`, `CaseReviewer`, `FinancialCounselor`, and `LogisticsCoordinator`. For every one of these five roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `assigned_coordinator_id` on a `VisitCase`, as `reviewer_id` on a `CaseReview`, or as the receiving coordinator remembered on a `MedicalRecord` — but it never compares `X-User-ID` against any entity's `id` for ownership purposes. Segregation-of-duties checks compare recorded operator identifiers to each other, never to resource identifiers.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. The Logical Clock

All temporal reasoning in the system — deposit deadlines, visit-due checks, review-day counting, no-show detection — runs against a server-maintained logical clock, never against wall-clock time. Before any administrator action, the logical clock reads exactly `2026-09-01T00:00:00Z`. A `PlatformAdmin` may advance it by submitting a `current_utc` value to the test-driving clock capability, which replies with the accepted `current_utc` echoed verbatim, exactly as submitted (no re-formatting or normalization of the submitted string). Advancing the clock never fires retroactive transitions; rules that depend on the clock evaluate at the moment a request arrives against the clock's current reading. Server-stamped timestamps such as `received_at` on a `MedicalRecord` and `sent_at` on a `Communication` are taken from this logical clock, as is the calendar date recorded as `reviewed_on_date` on a `CaseReview`.

### 2.5. Common Resource Properties and Mutation Semantics

Every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` field is an integer that increments on every mutation to the resource, including mutations caused by cascading side effects initiated elsewhere. Because cascades bump versions, a client that has observed a case, placed no writes of its own, and then attempted a write may still find the case's `version` advanced — that is the intended behavior and feeds directly into the optimistic concurrency rule of §2.7.

### 2.6. Monetary Values and Precision

All monetary amounts are integer cents. Every derived monetary figure — per-visit effective prices, itinerary totals, deposits, settlement amounts — is rounded half-up to whole cents. No fractional cents ever appear in a stored or returned value. The one subtlety is *when* rounding happens for itinerary totals, which is a first-class business distinction covered in §3.5: the provisional quote rounds each visit's price before summing, while the final settlement figure sums unrounded products and rounds once at the end.

### 2.7. Optimistic Concurrency Control on Itinerary Booking

Exactly one write operation in the system is guarded by optimistic concurrency control: placing a slot hold on a visit case. The request must carry a non-optional `expected_case_version` field containing the `version` of the `VisitCase` the client last observed. If that value does not match the case's current `version` — for example because another coordinator has just placed or released a hold on the same case, each of which legitimately advances the case's `version` — the hold is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; all other writes proceed without an optimistic-concurrency check.

### 2.8. Validation Ordering

When several validation rules could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic. First, the authentication context is checked (missing or empty `X-User-ID` / `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), followed by role authorization (`ERR_INSUFFICIENT_PERMISSIONS`). Next, path resources are validated for existence left-to-right (`ERR_NOT_FOUND` — see §2.9). Only then does the server check request-body shape — required fields present, enums valid, types correct (`ERR_INVALID_REQUEST`) — and then entity state preconditions (`ERR_INVALID_STATE`). After state come the remaining business rules: the optimistic-concurrency check on slot holds (`ERR_STALE_VERSION`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), the interpreter-requirement rule (`ERR_INTERPRETER_NOT_REQUIRED`), care-team composition (`ERR_INVALID_CARE_TEAM`), remote-product eligibility (`ERR_REMOTE_PRODUCT_UNSUPPORTED`), service-window and slot-date checks (`ERR_OUTSIDE_SERVICE_WINDOW`), interval overlap (`ERR_SLOT_OVERLAP`), itinerary window span (`ERR_ITINERARY_WINDOW_EXCEEDED`), imaging support (`ERR_IMAGING_NOT_SUPPORTED`), capacity pool exhaustion (`ERR_CAPACITY_EXHAUSTED`), financial-clearance gating (`ERR_FINANCIAL_CLEARANCE_REQUIRED`), the international-waiver prohibition (`ERR_INTERNATIONAL_WAIVER_FORBIDDEN`), settlement prerequisites (`ERR_MINIMUM_COMPLETED_VISITS`), estimate-letter freshness (`ERR_STALE_ESTIMATE_LETTER`), results-transmission requirements (`ERR_RESULTS_NOT_TRANSMITTED`), and the review fatigue guard (`ERR_FATIGUE_GUARD`). A failure earlier in this sequence masks all later failures for that request.

### 2.9. Nested Resource Retrieval

Endpoints whose paths contain multiple resource identifiers — for example a medical record nested under a referral, or a logistics arrangement nested under a visit case — validate path resources in strict left-to-right order. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, and later segments are never consulted. This holds equally for reads, mutations, and creations of child resources.

### 2.10. Hierarchical Consistency and Cascading Side Effects

State changes propagate across the aggregate hierarchy in both directions. Parent-terminal events cascade downward: withdrawing or forfeiting a case releases its held slots, cancels its pending visits, cancels its draft itinerary, and cancels its requested or booked logistics arrangements. Child-terminal events bubble upward: a clearance reaching `CLEARED` lifts its case from `AWAITING_FINANCIAL` to `FINANCIAL_CLEARED`; a case reaching `COMPLETED` eventually closes its referral once communications obligations are met. Every such propagation is a real mutation on the affected resource — `updated_at` refreshes and `version` increments — so observers can always detect that a cascade passed through. Status fields everywhere hold exact uppercase enumeration strings; the complete enumeration for each entity appears alongside its lifecycle in §3.

## 3. Business Logic & Workflows

### 3.1. Specialty Services, Slot Pools, and Destination Capacity

A `PlatformAdmin` bootstraps the clinical catalog by registering each specialty service with a unique `code` (short mnemonics such as `CARD`, `NEUR`, `ORTH` are conventional), a display `name`, and the service's daily bookable window expressed as minutes from midnight: `service_window_start_min` and `service_window_end_min`, where the start must lie in the range 0 to 1439, the end in the range 0 to 1440, and the start must be strictly earlier than the end. The end is exclusive — a window ending at minute 1020 (17:00) admits slots that finish exactly at 17:00 but none that extend past it.

Each service also declares `destination_daily_capacity`, an integer of at least 1 representing the per-day appointment pool reserved for destination (referral-routed) patients, and two capability flags. `supports_imaging` defaults to false and gates whether `IMAGING`-type visits may be scheduled against the service; `supports_remote_products` defaults to true and gates whether `SECOND_OPINION` and `REMOTE_CONSULT` cases may target it.

Within a service, a `PlatformAdmin` opens appointment slots by supplying a `slot_date` (a calendar date in `YYYY-MM-DD` form), a `start_min` in the range 0 to 1439, and an `end_min` in the range 1 to 1440 strictly greater than the start. Slot creation is rejected with `ERR_OUTSIDE_SERVICE_WINDOW` when the interval falls outside the service's window or when the `slot_date` is in the past relative to the logical clock. Two slots on the same service and date collide when each one's start falls strictly before the other's end — the half-open interval rule — and creation overlapping an existing slot in any non-terminal status (`OPEN`, `HELD`, or `CONFIRMED`) is rejected with `ERR_SLOT_OVERLAP`; terminal `RELEASED` and `CANCELLED` slots do not block creation, so releasing or cancelling a slot genuinely frees its interval. Adjacency is explicitly legal: one slot ending at the exact minute another begins does not overlap. Slots on different services or different dates never collide. New slots are born `OPEN`; a slot's `status` walks `OPEN → HELD → CONFIRMED`, with `RELEASED` and `CANCELLED` as terminal exits described in §3.4. Slots may be listed per service with optional `slot_date` and `status` filters, and each slot records its owning `specialty_service_id`.

The capacity pool is enforced at hold time, not slot-creation time: a slot may always be opened, but the number of slots simultaneously in `HELD` or `CONFIRMED` status for a given service on a given date must stay strictly below `destination_daily_capacity` for a new hold to succeed. The count is aggregate per date — two held slots on the same date consume two units of the pool regardless of whether their time intervals overlap — while the overlap rule independently forbids time collisions. When the pool has already reached exactly capacity, the next hold is rejected with `ERR_CAPACITY_EXHAUSTED`; a hold that would bring the count to exactly capacity succeeds.

### 3.2. Referral Intake and Medical Records

An `IntakeCoordinator` opens the pipeline by submitting a referral carrying the external referring physician's `referring_physician_name`, a `referring_physician_contact` handle (email or phone) used later for results transmission, the clinical `reason` for the referral, and an inline `patient` payload. The patient payload requires `full_name`, `date_of_birth`, `residence_country` (an ISO 3166-1 alpha-2 code; anything other than `US` marks the case international), and `preferred_language` (a BCP-47 tag; anything other than `en` implies an interpreter need). US residents must additionally supply `residence_state`, and that state must differ from the system's home state of `MN` — a referral for a Minnesota resident is rejected, since the destination program does not route local patients through this pipeline. The payload may also carry an optional boolean `needs_interpreter`; when omitted, the interpreter requirement is derived from whether `preferred_language` differs from `en`.

Submission cascade-creates the `Patient` record, copying `full_name`, `date_of_birth`, `residence_country`, `residence_state` (null for international patients), and `preferred_language` onto it, and computing two flags: `is_international`, true exactly when `residence_country` is not `US`, and `requires_interpreter`, which follows the supplied `needs_interpreter` when present and otherwise mirrors whether `preferred_language` is not `en`. The referral itself is born `SUBMITTED`, and its `status` then walks a single linear pipeline with one branch: `SUBMITTED` → `RECORDS_PENDING` → `IN_REVIEW` → `REVIEWED` → `CLOSED`, with `DECLINED` as a terminal diversion reachable from `IN_REVIEW`. The patient created by a referral is retrievable through the referral (an array of zero or one), and referrals may be listed with an optional `status` filter.

Records then arrive. For each shipment of outside material, the coordinator registers a `MedicalRecord` against the referral with a `record_type` — one of `IMAGING`, `LAB`, `PATHOLOGY`, `CLINICAL_NOTES`, or `MEDICATION_LIST` — and the originating `source_facility`. The server stamps `received_at` from the logical clock and records which coordinator received it; the record is born `RECEIVED` and remembers its owning `referral_id`. The very first record receipt moves the referral from `SUBMITTED` to `RECORDS_PENDING`; attempting to register a record against a referral in any other state is rejected with `ERR_INVALID_STATE`. Records may be listed per referral with an optional `status` filter.

Verification belongs to a different set of hands. A `CaseReviewer` may verify or reject a record that is currently `RECEIVED`; acting on a record in any other state yields `ERR_INVALID_STATE`. Verification enforces segregation of duties: the verifying reviewer's `X-User-ID` must differ from the coordinator who received the record, or the request fails with `ERR_SEGREGATION_OF_DUTIES`. A successful verification moves the record to `VERIFIED` and fires the fatigue cascade of §3.3. Rejection requires the record to be `RECEIVED` and moves it to `REJECTED`; the referral remains in `RECORDS_PENDING` (the self-transition is recorded for audit), inviting the coordinator to chase replacement material. Both outcomes are terminal for the record.

Once at least one record stands `VERIFIED`, the coordinator submits the referral for review, moving it `RECORDS_PENDING → IN_REVIEW`. Submitting with zero verified records is rejected with `ERR_NO_VERIFIED_RECORDS`; submitting from any state other than `RECORDS_PENDING` is rejected with `ERR_INVALID_STATE`.

### 3.3. Case Review, Segregation of Duties, and the Fatigue Accumulator

With a referral `IN_REVIEW`, an `IntakeCoordinator` opens a visit case by naming the `referral_id`, the `case_type`, and the `care_team_specialty_ids`. Three case types exist. A `DESTINATION` case is the travel product: its care team must list between 2 and 4 distinct specialty services, and approval will spin up a full itinerary. `SECOND_OPINION` and `REMOTE_CONSULT` are the remote products for patients who do not travel; each takes exactly one specialty, and that specialty must have `supports_remote_products` true, or creation fails with `ERR_REMOTE_PRODUCT_UNSUPPORTED`. A care team that references unknown services, or whose size violates the case-type rule, is rejected with `ERR_INVALID_CARE_TEAM`. Opening a case against a referral that is not `IN_REVIEW` fails with `ERR_REFERRAL_NOT_IN_REVIEW`. The creating coordinator's `X-User-ID` is frozen onto the case as `assigned_coordinator_id` at creation; the case is born `INTAKE` with `fatigue_score` 0 and `review_days_used` 0, and its `deposit_amount_cents` is left for review approval to populate. Cases may be listed with optional `referral_id` and `status` filters.

Review is again a `CaseReviewer` duty, performed by recording a `CaseReview` with an `outcome` of `APPROVE` or `DECLINE` and free-text `notes`. The server stamps the acting reviewer as `reviewer_id` and the calendar date from the logical clock as `reviewed_on_date`. Three guards fire on every review, in this order: the case must currently be `INTAKE` (`ERR_INVALID_STATE` otherwise), its referral must still be `IN_REVIEW` (`ERR_REFERRAL_NOT_IN_REVIEW`), and the reviewer must not be the case's `assigned_coordinator_id` (`ERR_SEGREGATION_OF_DUTIES`). A fourth guard is the fatigue guard: a single reviewer may record reviews on at most 3 distinct calendar dates for the same case — recording a review that would push the case past 3 distinct review dates is rejected with `ERR_FATIGUE_GUARD`. After any accepted review, `review_days_used` is recomputed as the count of distinct `reviewed_on_date` values across the case's reviews.

A `DECLINE` outcome moves the case `INTAKE → DECLINED`, drags the referral to `DECLINED` alongside it, and cascade-cancels every logistics arrangement of the case still in `REQUESTED` or `BOOKED`. An `APPROVE` outcome moves the case `INTAKE → AWAITING_FINANCIAL` and performs a multi-resource fan-out: for `DESTINATION` cases an `Itinerary` is created in `DRAFT` status at `revision` 1; a `FinancialClearance` is created in `PENDING` status with `deposit_paid_cents` 0 and `required_deposit_cents` initialized to that same seeded tiered deposit; the case's `deposit_amount_cents` is computed from the tiered deposit rule of §3.5 — at approval the itinerary is still empty, so the tier floor applies against a base estimate seeded from the care-team size; and the owning referral advances `IN_REVIEW → REVIEWED`. Approving any case of a referral therefore marks the referral reviewed; declining any case declines the referral outright.

The fatigue accumulator ties records and remote consultations together. Each time a medical record is verified, `fatigue_score` increases by 2 on every non-terminal visit case under the same referral. Each time a `REMOTE_CONSULT` visit completes, the case's `fatigue_score` decreases by 3, floored at 0 — that compensating decrement is evaluated only for cases still in a non-terminal state, since a completed case is terminal and never withdraws. After any increment lands, the system re-checks the withdrawal threshold: if `fatigue_score` has reached at least 10 — the boundary is inclusive, so exactly 10 triggers — and the case is in `INTAKE`, `AWAITING_FINANCIAL`, `FINANCIAL_CLEARED`, or `SCHEDULING`, the case auto-withdraws with the standard release cascade of §3.7. The threshold check always runs after the increment, never before.

### 3.4. Slot Holds, Visit Booking, and the Concurrency Contract

Booking opens only after money clears. The first slot hold placed against a case in `FINANCIAL_CLEARED` flips the case into `SCHEDULING` and bumps the case's `version`; attempting to hold a slot before clearance — while the case is still `INTAKE` or `AWAITING_FINANCIAL` — is rejected with `ERR_INVALID_STATE`. Every hold request carries `appointment_slot_id`, `visit_type`, `listed_price_cents`, `sequencing_priority`, and the OCC field `expected_case_version` described in §2.7; the created `Visit` is the response, and each hold also re-bumps the case's `version`.

The hold itself is an `IntakeCoordinator` action with a battery of preconditions. The target slot must be `OPEN` — holding anything else yields `ERR_SLOT_NOT_OPEN`. The slot's interval must not overlap any `HELD` or `CONFIRMED` slot for the same service and date under the half-open rule of §3.1 (`ERR_SLOT_OVERLAP`, with adjacency allowed). The hold must not push the service-date pool to capacity's limit — if the count of `HELD` plus `CONFIRMED` slots already equals `destination_daily_capacity`, the hold is rejected with `ERR_CAPACITY_EXHAUSTED`. The slot must sit inside the service window (`ERR_OUTSIDE_SERVICE_WINDOW`). And when the requested `visit_type` is `IMAGING`, the slot's service must have `supports_imaging` true, or the hold fails with `ERR_IMAGING_NOT_SUPPORTED`; `CONSULT`, `LAB_TEST`, and `PROCEDURE` visit types carry no such flag requirement. `listed_price_cents` must be a positive integer — it is the base price fed into the estimate engine — and `sequencing_priority` is an integer from 1 to 99 used for same-day ordering.

A successful hold moves the slot `OPEN → HELD` and creates a `Visit` under the case's itinerary in `PENDING` status, bound to the slot. The visit denormalizes its context for filtering: it records its `itinerary_id`, its `visit_case_id`, its `appointment_slot_id`, and the slot's `specialty_service_id`. Both itinerary totals are recomputed on every hold. Visits may be listed per itinerary, or through the global filtered list accepting `visit_case_id`, `appointment_slot_id`, `specialty_service_id`, and `status` filters.

Confirming a held slot is a separate coordinator action: it requires the slot to be `HELD` (`ERR_INVALID_STATE` otherwise) and the owning case's clearance to be `CLEARED` or `WAIVED` (`ERR_FINANCIAL_CLEARANCE_REQUIRED` — HTTP 402 — otherwise). Confirmation moves the slot `HELD → CONFIRMED` and drives its visit `PENDING → CONFIRMED` in the same breath. Releasing a held slot returns it to the pool terminally: the slot becomes `RELEASED`, its pending visit becomes `CANCELLED`, the itinerary's `revision` increments by one, and both totals are recomputed — this revision bump and totals recompute apply unconditionally, regardless of the itinerary's current status. A `CONFIRMED` slot can no longer be released — releasing one yields `ERR_INVALID_STATE`; a confirmed booking unwinds only through visit-level cancellation, which moves the visit `CONFIRMED → CANCELLED`, moves the slot terminally to `CANCELLED` (a cancelled slot is never reusable), bumps the itinerary `revision`, recomputes totals — again unconditionally, regardless of the itinerary's current status — and — because the revision moved — renders any outstanding issued estimate letter stale per §3.5.

### 3.5. Estimates, Deposits, and Estimate Letters

The estimate engine maintains two variants of the itinerary total in parallel, recomputed whenever the visit set changes — on every slot hold, every slot release, every visit cancellation, and at estimate-letter issuance. The visit set for both variants comprises the itinerary's visits in `PENDING`, `CONFIRMED`, or `COMPLETED` status; `CANCELLED` and `NO_SHOW` visits are excluded.

Both variants share the same per-visit pricing. Let the bundled count be the size of that visit set at evaluation time. The discount percentage is 0 percent when the bundled count is at most 2, 5 percent when the bundled count is exactly 3, and 10 percent when the bundled count is 4 or more. An international multiplier of 1.20 applies when the patient `is_international`, and 1.00 otherwise. Each visit's effective price is its `listed_price_cents` scaled by one minus the discount percentage and then by the international multiplier. The two variants differ only in rounding order. The **provisional** variant — exposed as `provisional_total_cents` and shown on estimate letters as the conservative, higher quote — rounds each visit's effective price half-up to whole cents first, then sums. The **final** variant — exposed as `final_total_cents` and used for settlement billing — sums the unrounded per-visit products and rounds the grand total half-up once at the end. Whenever any per-visit product carries a fractional cent, the provisional total is therefore greater than or equal to the final total, and the two diverge.

The deposit is tiered off the *final* estimate, with inclusive lower boundaries: a final estimate of at least 500000 cents takes a 30 percent deposit; a final estimate of at least 100000 cents but under 500000 takes 20 percent; anything below 100000 takes 10 percent. Each tier's deposit is rounded half-up to whole cents. Exactly 500000 cents takes the 30 percent tier; exactly 100000 takes the 20 percent tier. At case-review approval the itinerary has no visits yet, so the seed estimate used for the tier computation is the care-team size multiplied by 150000 cents per visit — a base visit price — which keeps the tier well-defined even against an empty itinerary; this seeded figure is what lands in the case's `deposit_amount_cents`. International patients are computed through the same tiers applied to their multiplied estimate.

A `FinancialCounselor` formalizes the numbers by issuing an `EstimateLetter` for the case. Issuance snapshots the itinerary's current `revision` into `itinerary_revision_at_issue`, the provisional total into `provisional_estimate_cents`, the final total into `final_estimate_cents`, and the tiered deposit computed from that final estimate into the letter's own `deposit_amount_cents`. At most one letter per case stands `ISSUED` at a time: issuing a fresh letter supersedes the prior one, moving it to `SUPERSEDED`, and updates the case clearance's `required_deposit_cents` from the new letter's deposit. A letter's `is_stale` flag is computed, not stored: it is true exactly when `itinerary_revision_at_issue` is lower than the itinerary's current `revision` — so any confirmed-slot reschedule or cancellation that bumped the revision instantly stales the outstanding letter, and travel authorization (§3.6) will refuse to rely on it.

### 3.6. Financial Clearance, Deposits, Waivers, Forfeiture, and Settlement

Every approved case carries exactly one `FinancialClearance`, born `PENDING` with `deposit_paid_cents` 0, `holds_released` false, and `required_deposit_cents` initialized to the case's seeded tiered deposit (the value approval computed into the case's `deposit_amount_cents` per §3.5). Its lifecycle is `PENDING → CLEARED` on the happy path, with `FORFEITED`, `SETTLED`, and `WAIVED` as terminal exits and one reversible edge back from `CLEARED` to `PENDING`. The clearance required before itinerary confirmation is taken from the issued estimate letter as `required_deposit_cents`, whose issuance overwrites the seeded initial value.

Money moves through billing transactions recorded by a `FinancialCounselor` against the case, each carrying a `txn_type` of `DEPOSIT`, `SETTLEMENT`, or `REFUND` and a positive integer `amount_cents`; every transaction also records its `visit_case_id` and `financial_clearance_id` and is born `POSTED`. A `DEPOSIT` adds its amount to `deposit_paid_cents`, and after each posting the system checks the clearance threshold: when `deposit_paid_cents` reaches or exceeds `required_deposit_cents` — equality clears — the clearance flips `PENDING → CLEARED` and the case bubbles from `AWAITING_FINANCIAL` to `FINANCIAL_CLEARED`. (A clearance whose required deposit is zero clears immediately upon creation; otherwise it waits for money.) A `REFUND` reverses a prior deposit: the referenced source `DEPOSIT` transaction is voided — its `status` becomes `VOID` — and the refunded amount is subtracted from `deposit_paid_cents`. A refund has no other effects: in particular it never changes the clearance's `status` (the only way back from `CLEARED` to `PENDING` is the reopen action described below) and it does not re-run the clearance threshold check. Transactions may be listed per case with a `txn_type` filter, or through the global transaction list filtered by `financial_clearance_id` and `txn_type`.

Domestic cases may be excused from the deposit entirely: a counselor may waive a `PENDING` clearance, moving it to terminal `WAIVED` and bubbling the case `AWAITING_FINANCIAL → FINANCIAL_CLEARED`. International patients may never be waived — the request is rejected with `ERR_INTERNATIONAL_WAIVER_FORBIDDEN` — and waiving a clearance not in `PENDING` fails with `ERR_INVALID_STATE`.

Cleared is not irrevocable. When insurance verification reverses, a counselor may reopen a `CLEARED` clearance, returning it to `PENDING` and bubbling the case from `FINANCIAL_CLEARED` back to `AWAITING_FINANCIAL`. Two limits apply: reopening a clearance that is not `CLEARED` yields `ERR_INVALID_STATE`, and once forfeiture has released the case's holds — `holds_released` true — the clearance can never return to `PENDING`, and the attempt is rejected with `ERR_CLEARANCE_HOLD_RELEASED`. Note the asymmetry: reopening affects only the clearance state; a case that has already advanced into `SCHEDULING` or `SCHEDULED` is *not* demoted.

The deadline side of the ledger is forfeiture. A counselor may forfeit a `PENDING` clearance only after the deposit deadline has genuinely passed: the logical clock's current date must be strictly later than the earliest `HELD` slot date of the case's itinerary minus 14 days — attempting the forfeit earlier is rejected with `ERR_DEADLINE_NOT_BREACHED`, and attempting it on a clearance not in `PENDING` is rejected with `ERR_INVALID_STATE`. A successful forfeit fires a depth-3 cascade: the clearance becomes `FORFEITED` with `holds_released` set true; every slot `HELD` by the case is released to `RELEASED`, freeing capacity; each corresponding pending visit is cancelled; the itinerary, if still `DRAFT`, is cancelled and its `revision` increments by one; and the case itself is withdrawn to `WITHDRAWN`.

Settlement closes the books after care is delivered. Recording a `SETTLEMENT` transaction requires the clearance to be `CLEARED` (`ERR_INVALID_STATE` otherwise), the case to be `COMPLETED`, and at least 3 of the itinerary's visits to stand `COMPLETED` — fewer, and the request is rejected with `ERR_MINIMUM_COMPLETED_VISITS`. When the settlement posts, the server overwrites the submitted `amount_cents` with the exact remainder: the itinerary's `final_total_cents` minus `deposit_paid_cents`, floored at zero. The compensating invariant is that the deposits already paid plus the settlement amount equal the final total at settle time. Posting moves the clearance `CLEARED → SETTLED`, terminally.

### 3.7. Withdrawal, Itinerary Confirmation, Travel Authorization, and Visit Completion

A coordinator may withdraw a case manually at any point before the schedule locks: withdrawal is permitted from `INTAKE`, `AWAITING_FINANCIAL`, `FINANCIAL_CLEARED`, or `SCHEDULING`; attempting it from `SCHEDULED` or any later state is rejected with `ERR_INVALID_STATE`. Manual withdrawal and the fatigue auto-withdrawal of §3.3 share one release cascade: every slot the case holds moves `HELD → RELEASED` and the capacity pool is decremented accordingly; every logistics arrangement in `REQUESTED` or `BOOKED` is cancelled; the itinerary, if `DRAFT`, is cancelled; and every `PENDING` visit is cancelled. All of these are terminal moves on their respective entities.

On the happy path, the itinerary itself walks `DRAFT → CONFIRMED → LOCKED`, with `CANCELLED` as the terminal cascade exit. Confirming the itinerary is the coordinator's bundling act and carries four preconditions: the itinerary must be `DRAFT` (`ERR_INVALID_STATE`); the case's clearance must be `CLEARED` (`ERR_FINANCIAL_CLEARANCE_REQUIRED`); no visit under the itinerary may remain `PENDING` — every one must be `CONFIRMED` (`ERR_UNCONFIRMED_VISITS_REMAIN`); and the itinerary must compress into at most 5 distinct `slot_date` values among its `PENDING` and `CONFIRMED` visits — exactly 5 distinct dates is allowed, 6 is rejected with `ERR_ITINERARY_WINDOW_EXCEEDED`. Confirmation moves the itinerary `DRAFT → CONFIRMED` and the case `SCHEDULING → SCHEDULED` together.

Travel authorization is the final gate before the patient flies, and it is deliberately strict. The coordinator's authorization requires the case in `SCHEDULED` and the itinerary in `CONFIRMED` (`ERR_INVALID_STATE` for either mismatch); an `ISSUED` estimate letter that is not stale — `ERR_STALE_ESTIMATE_LETTER` when no letter is issued or the outstanding one was overtaken by an itinerary revision; and, whenever the patient's `requires_interpreter` flag is true, every interpreter arrangement the case needs must already be `BOOKED`, else `ERR_INTERPRETER_NOT_BOOKED`. Success moves the case `SCHEDULED → READY_TO_TRAVEL`. Only then may the itinerary be locked: locking requires the itinerary `CONFIRMED` and the case `READY_TO_TRAVEL`, moves the itinerary to terminal `LOCKED`, and renders all subsequent rescheduling attempts against it rejectable with `ERR_INVALID_STATE` — a locked itinerary is immutable.

Visits conclude on the ground. A coordinator marks a `CONFIRMED` visit completed, subject to two temporal rules: the logical clock's date must be at least the visit's `slot_date` — completing early is rejected with `ERR_VISIT_NOT_DUE` — and same-day sequencing must be respected: no other visit on the same itinerary and the same `slot_date` with a lower `sequencing_priority` may still be `CONFIRMED`, with ties broken by earlier `created_at` first; violating the order yields `ERR_SEQUENCING_VIOLATION`. Completing a visit that is not `CONFIRMED` is `ERR_INVALID_STATE`. Completion of a visit belonging to a `REMOTE_CONSULT` case additionally applies the fatigue compensating decrement of §3.3. A visit that never happens is marked no-show — either explicitly by the coordinator once the logical clock's date has passed the `slot_date` (marking earlier yields `ERR_VISIT_NOT_DUE`), or by the system when the clock advances past the slot date's end-of-day with the visit still `CONFIRMED`. Visit completion or no-show triggers re-evaluation of case auto-completion: when every non-cancelled visit under the itinerary has reached `COMPLETED` or `NO_SHOW` and at least one visit stands `COMPLETED`, the case moves `READY_TO_TRAVEL → COMPLETED`.

### 3.8. Logistics, Communications, and Referral Closure

Logistics run in parallel with booking. A `LogisticsCoordinator` requests an arrangement for a case with an `arrangement_type` of `TRAVEL`, `LODGING`, or `INTERPRETER`, free-form `details` (carrier, hotel, language pair), and a `companion_count` between 0 and 2 covering the people traveling with the patient. An `INTERPRETER` arrangement is only lawful when the patient `requires_interpreter` — requesting one otherwise is rejected with `ERR_INTERPRETER_NOT_REQUIRED`. Arrangements are born `REQUESTED`; the coordinator confirms a requested arrangement to `BOOKED` (acting on a non-`REQUESTED` arrangement yields `ERR_INVALID_STATE`), and may cancel from either `REQUESTED` or `BOOKED` to `CANCELLED`. The interpreter confirmation repeats the requirement check. Case withdrawal and decline cascades cancel arrangements in either non-terminal state, as noted in §3.7. Arrangements may be listed per case with `arrangement_type` and `status` filters.

Closure of the loop belongs to the `CaseReviewer`, who communicates back to the referring physician. Each communication carries a `comm_type`, a free-text `body`, and a server-stamped `sent_at` from the logical clock. A `RESULTS_TO_REFERRER` communication transmits findings to the `referring_physician_contact` captured at intake. A `CONTINUITY_PLAN` communication additionally requires a structured `continuity_plan` object naming an `owner` — one of `LOCAL_PHYSICIAN`, `DESTINATION_TEAM`, or `SHARED` — and a `follow_up_weeks` horizon from 1 to 52; the object is required exactly when the communication is a continuity plan. Communications may be listed per case with a `comm_type` filter.

The referral closes only when the loop is fully closed. Once a case reaches `COMPLETED`, the system evaluates referral closure, and re-evaluates it on each new communication created for the case. Closure requires both a `RESULTS_TO_REFERRER` communication and a `CONTINUITY_PLAN` communication to exist for the case; the missing-results condition is reported as `ERR_RESULTS_NOT_TRANSMITTED` and the missing-plan condition as `ERR_CONTINUITY_PLAN_MISSING`. Until both exist, the case simply remains `COMPLETED` and the referral remains `REVIEWED`; with both in place, the referral moves `REVIEWED` → `CLOSED`, terminally.

## 4. Endpoint Definitions

Operations that create new resources — registering a service, opening a slot, submitting a referral, registering a record, opening a case, recording a review, issuing an estimate letter, recording a billing transaction, placing a slot hold (which creates the visit), requesting a logistics arrangement, or sending a communication — return `201 Created`. Operations that modify an existing resource in place — all state transitions, confirmations, releases, waivers, forfeits, withdrawals, completions, and the clock advance — return `200 OK`. Readers must consult §3 for each operation's request fields, preconditions, and side effects; the table below is a routing and authorization index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/specialty-services` | Register a specialty service with its destination capacity pool | PlatformAdmin |
| GET | `/specialty-services` | List specialty services (filter by `code`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/specialty-services/{id}` | Get one specialty service | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/specialty-services/{id}/slots` | Open an appointment slot in the service pool | PlatformAdmin |
| GET | `/specialty-services/{id}/slots` | List slots for a service (filters `slot_date`, `status`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/slots/{id}` | Get one slot | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/slots/{id}/confirm` | Confirm a HELD slot; drives its visit to CONFIRMED | IntakeCoordinator |
| POST | `/slots/{id}/release` | Release a HELD slot back to the pool | IntakeCoordinator |
| POST | `/referrals` | Submit a remote referral; cascade-creates the patient | IntakeCoordinator |
| GET | `/referrals` | List referrals (filter by `status`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/referrals/{id}` | Get one referral | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/referrals/{id}/patient` | Fetch the patient created by this referral (array of 0..1) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/patients/{id}` | Get one patient | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/referrals/{id}/medical-records` | Register receipt of a medical record | IntakeCoordinator |
| GET | `/referrals/{id}/medical-records` | List records of a referral (filter by `status`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/medical-records/{id}` | Get one medical record | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/referrals/{id}/medical-records/{id}/verify` | Verify a record (segregation of duties; fatigue cascade) | CaseReviewer |
| POST | `/referrals/{id}/medical-records/{id}/reject` | Reject a record | CaseReviewer |
| POST | `/referrals/{id}/submit-review` | Move the referral from RECORDS_PENDING to IN_REVIEW | IntakeCoordinator |
| POST | `/visit-cases` | Open a visit case against an IN_REVIEW referral | IntakeCoordinator |
| GET | `/visit-cases` | List visit cases (filters `referral_id`, `status`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/visit-cases/{id}` | Get one visit case | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/visit-cases/{id}/reviews` | Record a case review (APPROVE or DECLINE) | CaseReviewer |
| GET | `/visit-cases/{id}/reviews` | List reviews of a case | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/reviews/{id}` | Get one case review | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/visit-cases/{id}/withdraw` | Withdraw a case (release cascade) | IntakeCoordinator |
| POST | `/visit-cases/{id}/authorize-travel` | Authorize travel for a scheduled case | IntakeCoordinator |
| GET | `/visit-cases/{id}/financial-clearance` | Fetch the case's clearance (array of 0..1) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/visit-cases/{id}/financial-clearance/waive` | Waive the deposit (domestic patients only) | FinancialCounselor |
| POST | `/visit-cases/{id}/financial-clearance/reopen` | Reopen a CLEARED clearance | FinancialCounselor |
| POST | `/visit-cases/{id}/financial-clearance/forfeit` | Forfeit a PENDING clearance past the deposit deadline | FinancialCounselor |
| GET | `/financial-clearances/{id}` | Get one financial clearance | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/visit-cases/{id}/estimate-letters` | Issue an estimate letter snapshotting totals and deposit | FinancialCounselor |
| GET | `/visit-cases/{id}/estimate-letters` | List estimate letters of a case | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/estimate-letters/{id}` | Get one estimate letter | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/visit-cases/{id}/billing-transactions` | Record a DEPOSIT, SETTLEMENT, or REFUND transaction | FinancialCounselor |
| GET | `/visit-cases/{id}/billing-transactions` | List billing transactions of a case (filter by `txn_type`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/billing-transactions/{id}` | Get one billing transaction | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/billing-transactions` | List billing transactions (filters `financial_clearance_id`, `txn_type`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/visit-cases/{id}/itinerary` | Fetch the case itinerary (array of 0..1) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/itineraries/{id}` | Get one itinerary | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/visit-cases/{id}/slot-holds` | Hold an OPEN slot for this case (OCC-guarded); creates the visit | IntakeCoordinator |
| POST | `/itineraries/{id}/confirm` | Confirm the itinerary (visits confirmed, clearance ok, window within 5 days) | IntakeCoordinator |
| POST | `/itineraries/{id}/lock` | Lock a CONFIRMED itinerary after travel authorization | IntakeCoordinator |
| GET | `/itineraries/{id}/visits` | List visits of an itinerary (filter by `status`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/visits/{id}` | Get one visit | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/visits` | List visits (filters `visit_case_id`, `appointment_slot_id`, `specialty_service_id`, `status`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/visits/{id}/complete` | Mark a CONFIRMED visit completed (sequencing guard) | IntakeCoordinator |
| POST | `/visits/{id}/mark-no-show` | Mark a CONFIRMED visit as no-show | IntakeCoordinator |
| POST | `/visits/{id}/cancel` | Cancel a CONFIRMED visit; slot becomes CANCELLED | IntakeCoordinator |
| POST | `/visit-cases/{id}/logistics` | Request a travel, lodging, or interpreter arrangement | LogisticsCoordinator |
| GET | `/visit-cases/{id}/logistics` | List arrangements of a case (filters `arrangement_type`, `status`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/logistics-arrangements/{id}` | Get one logistics arrangement | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| POST | `/visit-cases/{id}/logistics/{id}/confirm` | Book a REQUESTED arrangement | LogisticsCoordinator |
| POST | `/visit-cases/{id}/logistics/{id}/cancel` | Cancel a REQUESTED or BOOKED arrangement | LogisticsCoordinator |
| POST | `/visit-cases/{id}/communications` | Send results to the referrer or set the continuity plan | CaseReviewer |
| GET | `/visit-cases/{id}/communications` | List communications of a case (filter by `comm_type`) | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |
| GET | `/communications/{id}` | Get one communication | PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflows they guard; this table is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NO_VERIFIED_RECORDS` | 409 |
| `ERR_REFERRAL_NOT_IN_REVIEW` | 409 |
| `ERR_INVALID_CARE_TEAM` | 422 |
| `ERR_REMOTE_PRODUCT_UNSUPPORTED` | 422 |
| `ERR_OUTSIDE_SERVICE_WINDOW` | 422 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_SLOT_NOT_OPEN` | 409 |
| `ERR_CAPACITY_EXHAUSTED` | 409 |
| `ERR_IMAGING_NOT_SUPPORTED` | 422 |
| `ERR_ITINERARY_WINDOW_EXCEEDED` | 422 |
| `ERR_UNCONFIRMED_VISITS_REMAIN` | 409 |
| `ERR_FINANCIAL_CLEARANCE_REQUIRED` | 402 |
| `ERR_INTERNATIONAL_WAIVER_FORBIDDEN` | 422 |
| `ERR_DEADLINE_NOT_BREACHED` | 409 |
| `ERR_CLEARANCE_HOLD_RELEASED` | 409 |
| `ERR_MINIMUM_COMPLETED_VISITS` | 409 |
| `ERR_STALE_ESTIMATE_LETTER` | 409 |
| `ERR_INTERPRETER_NOT_BOOKED` | 409 |
| `ERR_INTERPRETER_NOT_REQUIRED` | 422 |
| `ERR_RESULTS_NOT_TRANSMITTED` | 409 |
| `ERR_CONTINUITY_PLAN_MISSING` | 409 |
| `ERR_SEQUENCING_VIOLATION` | 409 |
| `ERR_VISIT_NOT_DUE` | 409 |
| `ERR_FATIGUE_GUARD` | 409 |
