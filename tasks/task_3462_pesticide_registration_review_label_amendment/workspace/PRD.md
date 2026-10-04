# EPA Pesticide Registration Review API — Product Requirements Document

## 1. Introduction

The Environmental Protection Agency's pesticide program re-evaluates every registered product against evolving science, and this API is the operational backbone of that program. It manages the full regulatory arc of a pesticide: the initial registration application with its efficacy, toxicology, environmental-fate, and residue-chemistry data requirements; quantitative risk assessment across dietary, occupational, and ecological exposure with tolerance establishment for food uses; the recurring registration review cycle that reopens every product on a fixed schedule with new data call-ins; label amendment requests for new uses, rate changes, and application methods, each with its own statutory review timeline; restricted-use classification with applicator certification requirements; endangered-species consultation bulletins that restrict use by geography; cancellation and suspension proceedings with existing-stocks sell-through provisions; and state registrations layered on top of the federal approval, each carrying its own fees and additional restrictions.

Two design commitments shape every workflow that follows. First, all time-dependent behavior — review cycles opening, data call-in deadlines lapsing, certifications expiring, state registrations lapsing — is driven by a single server-owned logical clock, so the entire regulatory calendar is deterministic and testable. Second, the program enforces segregation of duties at its two most consequential junctures: the scientist who assesses a product's risk may not approve its application, and the reviewer who initiates a cancellation or suspension proceeding may not issue its order. Every rule in this document is a hard requirement; wherever a number, threshold, state name, or error identifier appears, it is part of the contract.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to the entire API. All registry resources are mounted under the `/pesticide-registry` prefix; the single platform endpoint, the logical-clock control, lives outside it (§2.4).

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. Six roles are recognized, spelled exactly as follows: `SystemAdministrator`, `RegistrantRepresentative`, `RegistrationReviewer`, `RiskAssessor`, `StateLeadAgency`, and `CertificationAuthority`. A request missing either header, or carrying a role outside this set of six, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not among the roles an operation authorizes is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Across all six roles, `X-User-ID` is an opaque operator identifier; it is never the `id` of a persisted entity row, and the server never compares it against any entity's `id`. What the server records differs by role:

- When `X-User-Role` is `RegistrantRepresentative`, the identifier is stamped as `registrant_ref` on every product the representative creates and as `submitted_by_ref` on every study they submit. Ownership checks on registrant-scoped mutations — submitting or withdrawing an application, filing or withdrawing a label amendment, proposing a tolerance, submitting a study, responding to a data call-in, and applying for or renewing a state registration — compare the owning product's `registrant_ref` to `X-User-ID`, rejecting a mismatch with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `RiskAssessor`, the identifier is recorded as `assessor_ref` on each risk assessment the assessor runs and as `decided_by_ref` on each study they accept or reject; it anchors the segregation-of-duties check at application approval (§3.4) but is otherwise opaque.
- When `X-User-Role` is `RegistrationReviewer`, the identifier is recorded as `initiated_by_ref` on each cancellation or suspension proceeding the reviewer initiates — the literal string `system` appears there instead on the auto-created proceeding of the delinquency cascade — and it anchors the segregation-of-duties check at order issuance (§3.8).
- When `X-User-Role` is `SystemAdministrator`, `StateLeadAgency`, or `CertificationAuthority`, `X-User-ID` remains purely opaque: the server performs no ownership comparison for these roles and persists the identifier only where a workflow explicitly stamps it.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses include four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Scheduled Sweep

Every time-dependent rule in this system is evaluated against a single server-owned logical clock, never against wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-09-01T00:00:00Z` — a fixed server default, not the host's wall clock. A `SystemAdministrator` advances it through the platform endpoint `POST /_clock/set_current_utc`, which sits outside the `/pesticide-registry` prefix, takes a `to_iso8601` instant, and answers 200 with the resulting time in `current_utc`.

The clock never moves backward. A set call whose `to_iso8601` is strictly earlier than the current value fails with `ERR_INVALID_REQUEST` (HTTP 400); a value exactly equal to the current clock is an idempotent no-op; only a strictly later value advances time. Each advance runs a four-step batch sweep, and both the step order and the comparison operators are pinned:

1. Every registration review case still `SCHEDULED` whose `opened_at` is at or before the new time opens — `SCHEDULED` → `OPEN` — and when the case's product is `REGISTERED` the product moves to `UNDER_REVIEW` (a `SUSPENDED` product is left untouched).
2. Every data call-in in `ISSUED`, `RESPONDED`, or `DEFICIENT` whose `response_deadline` is strictly earlier than the new time becomes `DELINQUENT`, firing the referral-and-suspension cascade described in §3.7. The comparison here is strict: a deadline exactly equal to the new time does not delinquent.
3. Every applicator certification in `ACTIVE` whose `certified_until` is strictly earlier than the new time flips to `EXPIRED`.
4. Every state registration in `GRANTED` whose grace period has fully elapsed — the instant exactly thirty days after its `renewal_due_at` is strictly earlier than the new time — becomes `LAPSED`.

Step 1 uses an inclusive comparison; steps 2, 3, and 4 use strict ones. The order itself is part of the contract: cases open before any data call-in can delinquent, delinquency cascades run before certifications expire, and certifications expire before state registrations lapse.

### 2.5. Common Resource Properties

Every resource in the registry — active ingredients, products, registration applications, study submissions, use sites, risk assessments, tolerances, label amendments, applicator certifications, endangered-species bulletins, registration review cases, data call-ins, cancellation proceedings, and state registrations — carries a common set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix. Identifiers are never used for ranking, tie-breaking, or any other observable business decision.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource, including mutations caused by system cascades.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

Timestamps the workflows stamp — `submitted_at`, `decided_at`, `assessed_at`, `granted_at`, `effective_at`, and their kin — always read from the logical clock of §2.4.

### 2.6. Numeric Precision and Rounding Discipline

All quantitative outputs follow a uniform rounding discipline: round half up, with the number of decimal places pinned per quantity. The three risk quotients — `dietary_rq`, `occupational_rq`, and `ecological_rq` — are stored rounded half-up to three decimal places. Inside the dietary exposure computation, each per-commodity term is rounded half-up to four decimal places before the terms are summed, and the summed exposure is then rounded half-up to three decimal places. Monetary amounts are always integer numbers of cents; the one fractional money computation in the system, the state-registration late penalty, is rounded half-up to a whole cent. Day counts are whole days, and where a formula produces a fraction of a day the result rounds up to the next whole day. Datetime arithmetic is exact to the instant on the logical clock.

### 2.7. Optimistic Concurrency Control on Label Amendment Filing

Exactly one operation in the API is guarded by optimistic concurrency control: filing a label amendment (`POST /pesticide-registry/label-amendments`). The request body must carry `expected_product_version`, holding the `version` of the target product as the filing client last observed it; the field is not optional. If another writer has advanced the product's `version` since that observation, the two values differ and the filing is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412) — even when every state precondition on the product still holds. This check is not decorative: every successful amendment filing itself advances the product's `version` by one, so a client holding a stale observation is necessarily filing against a label record that no longer matches its view. The stale-version check runs before any business validation on the request (§2.8). No other endpoint accepts a version field; operations not named here must not be called with one.

### 2.8. The Validation Pipeline and Its Priority Order

Every mutation request passes through a fixed validation pipeline. The stages are evaluated in the order below, and a failure at any stage short-circuits all later stages:

1. **Operator context** — the presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400).
2. **Role authorization** — the role must be listed for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403).
3. **Request schema** — required fields present, types correct, enum members inside their declared sets, unknown keys rejected, and every conditional-requiredness rule honored: `final_classification` on an approval decision; `pct_crop_treated` required on `REFINED` assessments and forbidden on `SCREENING` ones; `rate_cap_lbs_acre` exactly when a bulletin's `restriction_code` is `RATE_CAP`; `commodity_code` and `field_trial_residue_ppm` exactly when the `study_type` is `RESIDUE_CHEMISTRY`; `depletion_rate_units_per_month` exactly when the `stocks_method` is `DEPLETION`; existing-stocks fields required on a cancellation order and forbidden on a suspension order; `expedited` only on a `METHOD_CHANGE` amendment; exactly one of a study's two parents (`application_id` or `data_call_in_id`); and a clock set that is not before the current time. Any failure is `ERR_INVALID_REQUEST` (HTTP 400).
4. **Existence** — path identifiers resolve left to right, then body-supplied foreign keys resolve; the first miss produces the resource-appropriate 404 (§2.9).
5. **Ownership** — the registrant-scoping rule of §2.1 (`ERR_NOT_RESOURCE_OWNER`, HTTP 403).
6. **Optimistic concurrency** — the `expected_product_version` check of §2.7 (`ERR_STALE_PRODUCT_VERSION`, HTTP 412), which therefore fires ahead of every business rule below it.
7. **State gates** — from-state and cross-entity state preconditions of the state machines (`ERR_APPLICATION_NOT_SUBMITTABLE`, `ERR_APPLICATION_NOT_IN_REVIEW`, `ERR_APPLICATION_ALREADY_DECIDED`, `ERR_PRODUCT_NOT_UNREGISTERED`, `ERR_PRODUCT_NOT_REGISTERED`, `ERR_PRODUCT_TERMINAL`, `ERR_PRODUCT_NOT_SUSPENDED`, `ERR_REINSTATEMENT_BLOCKED`, `ERR_STUDY_NOT_DECIDABLE`, `ERR_AMENDMENT_NOT_PENDING`, `ERR_CASE_NOT_OPEN`, `ERR_CASE_NOT_COMPLETABLE`, `ERR_DCI_OUTSTANDING`, `ERR_DCI_NOT_RESPONDABLE`, `ERR_PROCEEDING_INVALID_STEP`, `ERR_STATE_REG_NOT_DECIDABLE`, `ERR_BULLETIN_NOT_LIFTABLE`; all HTTP 409).
8. **Business safety** — the absolute rate cap, endangered-species conflicts, applicator-certification requirements, required-study completeness, and the approval risk gates (`ERR_RATE_EXCEEDS_SAFETY_CAP`, `ERR_ESA_PROHIBITION_CONFLICT`, `ERR_NO_VALID_APPLICATOR_CERTIFICATION`, `ERR_MISSING_REQUIRED_STUDIES`, `ERR_NO_RISK_ASSESSMENT`, `ERR_LOC_EXCEEDED`, `ERR_NO_PROPOSED_TOLERANCE`; all HTTP 422).
9. **Uniqueness, overlap, and segregation of duties** — one open application per product, one live tolerance per product-and-commodity, non-overlapping bulletin windows and review-case windows, one non-terminal state registration per product-and-state, one non-terminal proceeding per product via the manual route, the two segregation-of-duties checks, and the stocks-quantity ceiling (`ERR_DUPLICATE_OPEN_APPLICATION`, `ERR_DUPLICATE_TOLERANCE`, `ERR_BULLETIN_WINDOW_OVERLAP`, `ERR_REVIEW_CASE_WINDOW_OVERLAP`, `ERR_DUPLICATE_STATE_REGISTRATION`, `ERR_DUPLICATE_OPEN_PROCEEDING`, `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403), `ERR_EXISTING_STOCKS_QUANTITY_EXCEEDED`; the remainder HTTP 409 except the quantity check at 422).
10. **Cross-reference integrity** — study parents that resolve and belong to the acting registrant's product, amendment use-site targets on the same product, and commodity codes known to the dietary model (`ERR_STUDY_PARENT_MISMATCH`, `ERR_USE_SITE_PRODUCT_MISMATCH` (both HTTP 400), `ERR_UNKNOWN_COMMODITY` (HTTP 422)).
11. **Temporal rules** — existing-stocks disposal windows, certification renewal instants, bulletin month ranges, and case window ordering (`ERR_EXISTING_STOCKS_WINDOW_CLOSED` (HTTP 422), `ERR_CERTIFICATION_RENEWAL_INVALID` (HTTP 400), `ERR_INVALID_REQUEST`).
12. **Fiscal exactness** — fees must equal the computed amount to the cent (`ERR_INCORRECT_FEE_PAYMENT`, HTTP 402), evaluated last.

### 2.9. Nested Resource Resolution and Fixed Reference Sets

Where a path nests one resource beneath another, identifiers are validated in a strict left-to-right order, and the first identifier that does not resolve produces the 404 for its own resource type: `ERR_PRODUCT_NOT_FOUND` for a product, `ERR_APPLICATION_NOT_FOUND` for an application, `ERR_STATE_REGISTRATION_NOT_FOUND` for a state registration, and the generic `ERR_NOT_FOUND` for every other resource type. Body-supplied foreign keys are checked for existence only after the path has fully resolved.

Two small reference sets are fixed by regulation and shared across workflows. The dietary model knows exactly five commodities — `CORN`, `SOYBEAN`, `WHEAT`, `APPLE`, and `COTTON` — and any `commodity_code` outside this set is rejected with `ERR_UNKNOWN_COMMODITY` (HTTP 422). State registration is offered in exactly four states — `CA`, `TX`, `IA`, and `FL` — and a `state_code` outside this set fails request-schema validation with `ERR_INVALID_REQUEST`. The consumption values and fee values attached to these sets are stated where they are used (§3.3 and §3.9 respectively).

## 3. Business Logic & Workflows

### 3.1. Reference Chemistry and the Product Shell

Before any product can exist, a `SystemAdministrator` registers the chemistry it is built on. An active ingredient is recorded with its public `common_name` (for example, chlorpyrifos), a `cas_number` that must be unique across all active-ingredient rows, an acute `tox_category` of `I`, `II`, `III`, or `IV`, a chronic `reference_dose_mg_kg_day` strictly greater than zero, and an `aquatic_lc50_ppm` strictly greater than zero. The reference dose and the aquatic LC50 anchor every risk quotient the agency later computes (§3.3).

Against that reference data, a `RegistrantRepresentative` creates a product shell by supplying a `product_name`, the `active_ingredient_id` of the product's single active ingredient, and a `formulation_type` of `EMULSIFIABLE_CONCENTRATE`, `GRANULAR`, `WETTABLE_POWDER`, `READY_TO_USE`, or `SEED_TREATMENT`. Creation stamps the representative's `X-User-ID` as the product's `registrant_ref`, sets `status` to `UNREGISTERED`, leaves `classification` at its default of `GENERAL_USE`, and leaves both `signal_word` and `epa_registration_number` null — those three fields are written only by the approval cascade of §3.4, and `classification` is immutable once set there. The product catalogue can be listed with optional `active_ingredient_id`, `registrant_ref`, and `status` filters, and each product exposes its label use sites, tolerances, bulletins, and review cases as sub-resource listings filterable by `status` (bulletins also by `county_fips`).

A product's `status` walks a cyclic regulatory graph. `UNREGISTERED` becomes `REGISTERED` exactly through a successful application approval. From `REGISTERED` the product cycles into `UNDER_REVIEW` whenever one of its scheduled review cases opens, and back to `REGISTERED` when the product's last open case completes; it drops to `SUSPENDED` under an effective suspension order and returns through reinstatement; and it falls to `CANCELLED` under a cancellation order. `CANCELLED` is terminal with exactly one documented exception: vacatur of the cancellation order restores the product to the status captured when the order took effect (§3.8).

### 3.2. Filing the Registration Application: Studies, Fees, and the Deficiency Loop

Against an `UNREGISTERED` product it owns, a registrant drafts a registration application with a `product_id`, a `use_pattern` of `FOOD_USE`, `NON_FOOD_USE`, or `MIXED_USE`, a `requested_classification` of `GENERAL_USE` or `RESTRICTED_USE`, and a `proposed_use_sites` array. Each element of `proposed_use_sites` is a use-site object carrying `site_code` (a crop or site code such as CORN, WHEAT, or TURF), `pest_code`, `max_application_rate_lbs_acre`, `max_applications_per_season`, `preharvest_interval_days`, `application_method`, and `restricted_entry_interval_hours`. Creating the application — which is born in `DRAFT` — mints one use-site row per array element, each in `PROPOSED` status with `origin` `INITIAL_APPLICATION` and its `product_id` pointing at the label owner.

Field bounds on the use-site object are fixed. Every application rate proposed anywhere in the system is bounded by an absolute safety cap: `max_application_rate_lbs_acre` must be greater than zero and no more than 8.0 pounds per acre, and a rate above the cap is rejected with `ERR_RATE_EXCEEDS_SAFETY_CAP` (HTTP 422) — the cap applies both at application creation and inside amendment payloads (§3.5). `max_applications_per_season` is at least 1; `preharvest_interval_days` and `restricted_entry_interval_hours` are at least 0; `application_method` is one of `GROUND`, `AERIAL`, `CHEMIGATION`, or `SEED_TREATMENT`.

Submission moves the application `DRAFT` → `IN_REVIEW` and is gated by five checks. The application must actually be in `DRAFT` — a submit against any other status fails `ERR_APPLICATION_NOT_SUBMITTABLE` (HTTP 409). The product must still be `UNREGISTERED`, failing `ERR_PRODUCT_NOT_UNREGISTERED` otherwise. No other application of the same product may sit in `DRAFT`, `IN_REVIEW`, or `DATA_DEFICIENCY`, or the submit collides with `ERR_DUPLICATE_OPEN_APPLICATION`. The dossier must already contain at least one study submission — of any status, decided or not — for every study type the use pattern requires, failing `ERR_MISSING_REQUIRED_STUDIES` (HTTP 422) otherwise: `FOOD_USE` and `MIXED_USE` each require `EFFICACY`, `TOXICOLOGY`, `ENVIRONMENTAL_FATE`, and `RESIDUE_CHEMISTRY`, while `NON_FOOD_USE` requires `EFFICACY`, `TOXICOLOGY`, and `ENVIRONMENTAL_FATE`. Finally, the `payment_cents` in the request must equal the filing fee for the use pattern exactly — 500,000 cents for `FOOD_USE`, 150,000 cents for `NON_FOOD_USE`, and 500,000 cents for `MIXED_USE` — with any mismatch failing `ERR_INCORRECT_FEE_PAYMENT` (HTTP 402).

A successful first submit stamps `submitted_at` from the logical clock, computes `review_due_at` as the submission instant plus the statutory review timeline for the use pattern — 540 days for `FOOD_USE`, 270 days for `NON_FOOD_USE`, and 540 days for `MIXED_USE` — and stores the fee in `payment_cents`. Applications can be listed with `product_id`, `registrant_ref`, and `status` filters.

Review is not one-shot. An application is born with `deficiency_count` zero, and a reviewer who finds the dossier incomplete issues a deficiency decision, moving the application `IN_REVIEW` → `DATA_DEFICIENCY`, incrementing `deficiency_count` by exactly one, and optionally recording `deficiency_notes`. The registrant cures and resubmits, moving `DATA_DEFICIENCY` → `IN_REVIEW`; resubmission re-checks the required-study completeness rule (failing `ERR_MISSING_REQUIRED_STUDIES` if still short), and the request must omit `payment_cents` entirely — no second fee is ever charged. Resubmission refreshes `submitted_at` but never recomputes `review_due_at`: the statutory clock runs from the first submission only.

The registrant may also withdraw an application, optionally giving a `reason`, from any of `DRAFT`, `IN_REVIEW`, or `DATA_DEFICIENCY`; withdrawing an application that has already reached `APPROVED`, `DENIED`, or `WITHDRAWN` fails `ERR_APPLICATION_ALREADY_DECIDED`. Withdrawal — like a denial, and like the cancellation cascade of §3.8 — cleans up the application's proposed label rows: its `PROPOSED` use sites become `REMOVED` and its `PROPOSED` tolerances become `REVOKED`. On the deny and withdraw paths the `pre_removal_status` and `pre_revocation_status` fields stay null; only the cancellation cascade writes them, which is what makes the vacatur restore of §3.8 able to tell cascade removals apart from ordinary ones.

### 3.3. Study Submissions and Quantitative Risk Assessment

A study submission carries exactly one parent: `application_id` when the study supports an application dossier, or `data_call_in_id` when it answers a data call-in (§3.7); supplying both or neither is `ERR_INVALID_REQUEST`. Every study records a `study_type` — one of `EFFICACY`, `TOXICOLOGY`, `ENVIRONMENTAL_FATE`, `RESIDUE_CHEMISTRY`, `OCCUPATIONAL_EXPOSURE`, or `ECOLOGICAL_EFFECTS` — and a free-form `guideline_reference` string. Two further fields are conditional: `commodity_code` and `field_trial_residue_ppm` are required exactly when the study type is `RESIDUE_CHEMISTRY` and forbidden on every other type; the commodity must be one of the five known commodities (`ERR_UNKNOWN_COMMODITY`), and the measured residue must be at least 0. A study filed against an application is accepted only while that application is `DRAFT`, `IN_REVIEW`, or `DATA_DEFICIENCY` — filing against an `APPROVED`, `DENIED`, or `WITHDRAWN` application fails `ERR_APPLICATION_ALREADY_DECIDED` — and whichever parent is named must belong to a product the acting representative owns, failing `ERR_STUDY_PARENT_MISMATCH` (HTTP 400) otherwise. New studies are born `RECEIVED`, with `submitted_by_ref` stamped from the request header, `decided_by_ref` and `decided_at` null. The study collection lists with `application_id`, `data_call_in_id`, `study_type`, and `status` filters.

A `RiskAssessor` decides each study: an accept decision moves `RECEIVED` → `ACCEPTED`, a reject decision moves `RECEIVED` → `REJECTED`, and any decision attempted on a study no longer `RECEIVED` fails `ERR_STUDY_NOT_DECIDABLE`. Either decision stamps `decided_by_ref` from the assessor's header and `decided_at` from the clock, and may carry `decision_notes`. When the study answers a data call-in, the decision additionally moves the call-in's obligation ledger (§3.7).

Risk assessment itself is a computed artifact. A `RiskAssessor` runs an assessment against an application that is `IN_REVIEW` or `DATA_DEFICIENCY` — an application in any other status fails `ERR_APPLICATION_NOT_IN_REVIEW`. The request names the `application_id`, a `tier` of `SCREENING` or `REFINED`, and — exactly when the tier is `REFINED` — a `pct_crop_treated` fraction greater than 0 and at most 1; supplying the fraction on a `SCREENING` run, or omitting it on a `REFINED` run, is `ERR_INVALID_REQUEST`. Each assessment of an application takes the next 1-based `assessment_seq` in creation order, so the "latest" assessment of an application is the one with the highest `assessment_seq`. Creation stamps `assessor_ref` and `assessed_at` and computes four outputs: `dietary_exposure_mg_day`, `dietary_rq`, `occupational_rq`, `ecological_rq`, and the boolean `level_of_concern_exceeded`.

**Dietary exposure and quotient.** The input set is the distinct `commodity_code` values over the product's tolerances in `PROPOSED` or `ESTABLISHED` at assessment time. For each commodity, the per-commodity term depends on the tier. Under `SCREENING`, the term is the tolerance's `tolerance_ppm` multiplied by the commodity's daily consumption in grams, rounded half-up to four decimal places — the legal maximum residue, assuming the entire crop is treated. Under `REFINED`, when at least one `ACCEPTED` study of type `RESIDUE_CHEMISTRY` exists bearing this commodity code and this application's id, the term instead takes the mean of those studies' `field_trial_residue_ppm` values — the mean itself rounded half-up to four decimal places — multiplied by the consumption and by `pct_crop_treated`, rounded half-up to four decimal places; where no such accepted study exists for a commodity, the `REFINED` term falls back to the `SCREENING` term for that commodity, so identical inputs never produce a higher exposure under `REFINED` than under `SCREENING`. The daily consumption values, in grams per day, are: `CORN` 12.5, `SOYBEAN` 8.0, `WHEAT` 20.0, `APPLE` 15.0, and `COTTON` 0.0. The rounding order is pinned: round each per-commodity term to four decimal places first, then sum the rounded terms, then round the sum half-up to three decimal places — that sum is `dietary_exposure_mg_day`. The dietary risk quotient `dietary_rq` is the exposure divided by the product of the active ingredient's `reference_dose_mg_kg_day` and a 70-kilogram reference body weight, rounded half-up to three decimal places. When no tolerance qualifies, the input set is empty and both outputs are exactly 0.000.

**Occupational quotient.** Take the maximum `max_application_rate_lbs_acre` over the product's use sites in `PROPOSED` or `ACTIVE` — zero when none qualify — multiply by an exposure factor of 0.01 milligrams per day per pound per acre, divide by the reference dose times the 70-kilogram body weight, and round half-up to three decimal places. The result is identical across tiers.

**Ecological quotient.** For each use site of the product in `PROPOSED` or `ACTIVE`, multiply its rate by the runoff factor of its `application_method` — 0.05 for `GROUND`, 0.15 for `AERIAL`, 0.10 for `CHEMIGATION`, and 0.02 for `SEED_TREATMENT` — and take the maximum of those products, or zero when no site qualifies. Divide that maximum by the active ingredient's `aquatic_lc50_ppm` and round half-up to three decimal places. This quotient, too, is identical across tiers.

**Level of concern.** The boolean `level_of_concern_exceeded` is true when the stored, rounded `dietary_rq` is at least 1.0, or the stored, rounded `occupational_rq` is at least 1.0, or the stored, rounded `ecological_rq` is at least 0.5. The comparisons are inclusive and run against the rounded stored values, so a dietary quotient of exactly 1.000 exceeds the level of concern.

### 3.4. Tolerances and the Approval Decision

Food uses cannot be approved without a legal residue ceiling. For a product the representative owns that is not `CANCELLED` — a cancelled product forbids the operation with `ERR_PRODUCT_TERMINAL` — a tolerance is proposed with `product_id`, `commodity_code`, and a `tolerance_ppm` strictly greater than zero; an unknown commodity fails `ERR_UNKNOWN_COMMODITY`. At most one tolerance in `PROPOSED` or `ESTABLISHED` may exist for a given product-and-commodity pair; a colliding proposal is rejected with `ERR_DUPLICATE_TOLERANCE` (HTTP 409). A new tolerance is born `PROPOSED` with `origin` `INITIAL_APPLICATION`, its `established_at`, `revoked_at`, and `pre_revocation_status` all null.

The decision on an `IN_REVIEW` application belongs to a `RegistrationReviewer`, whose `decision` payload is `APPROVE`, `DENY`, or `DEFICIENCY`; any decision attempted on an application not `IN_REVIEW` fails `ERR_APPLICATION_NOT_IN_REVIEW`. The deficiency branch is the loop of §3.2. The deny branch stamps `decided_at` and performs the same proposed-row cleanup as a withdrawal: the application's `PROPOSED` use sites become `REMOVED` and its `PROPOSED` tolerances become `REVOKED`, with `pre_removal_status` and `pre_revocation_status` left null.

Approval carries the heaviest gate chain in the system. Every required study type for the use pattern must have at least one `ACCEPTED` study on the application — merely submitted studies no longer suffice, and a shortfall fails `ERR_MISSING_REQUIRED_STUDIES`. At least one risk assessment must exist for the application (`ERR_NO_RISK_ASSESSMENT`). The latest assessment — the one with the highest `assessment_seq` — must have `level_of_concern_exceeded` false, else `ERR_LOC_EXCEEDED`. A `FOOD_USE` or `MIXED_USE` application must have at least one `PROPOSED` tolerance on the product, else `ERR_NO_PROPOSED_TOLERANCE`. The payload must include `final_classification` (`GENERAL_USE` or `RESTRICTED_USE`); its absence is `ERR_INVALID_REQUEST`. And segregation of duties applies: the deciding reviewer's `X-User-ID` must differ from the `assessor_ref` of the latest risk assessment, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).

An approval stamps `decided_at`, stores `final_classification` on the application, and flips the product `UNREGISTERED` → `REGISTERED` in a single cascade. The product's `classification` takes the decision's `final_classification`; its `signal_word` is derived from the active ingredient's `tox_category` — category `I` maps to `DANGER_POISON`, `II` maps to `WARNING`, and both `III` and `IV` map to `CAUTION`; and its `epa_registration_number` is minted as the literal prefix `EPA-RR-` followed by a zero-padded six-digit sequence equal to one more than the count of previously approved applications, so the very first approval in the system mints `EPA-RR-000001`. The application's `PROPOSED` use sites become `ACTIVE`; the product's `PROPOSED` tolerances become `ESTABLISHED` with `established_at` stamped from the clock. Finally, the first registration review case is auto-created: `cycle_number` 1, born `SCHEDULED`, with `opened_at` exactly 5,475 days — fifteen years — after the approval instant and `due_at` 180 days after it opens (§3.7).

### 3.5. Label Amendments After Registration

Once a product is registered, its label evolves through amendments. A registrant files one with `product_id`, an `amendment_type` of `NEW_USE`, `RATE_CHANGE`, or `METHOD_CHANGE`, a type-keyed `payload`, and the concurrency field `expected_product_version` of §2.7 — remember that the stale-version rejection `ERR_STALE_PRODUCT_VERSION` fires before any business rule below is even consulted. Filing requires the product to be `REGISTERED` or `UNDER_REVIEW`: a `CANCELLED` product forbids the filing with `ERR_PRODUCT_TERMINAL`, and an `UNREGISTERED` or `SUSPENDED` product fails `ERR_PRODUCT_NOT_REGISTERED`. Every successful filing advances the product's `version` by one, stamps `registrant_ref` and `submitted_at`, and births the amendment in `SUBMITTED` with `decided_at` still null. Amendments list with `product_id`, `amendment_type`, and `status` filters.

The `payload` shape depends on the type. A `NEW_USE` payload carries `use_site` — the same seven-field use-site object used at application creation (§3.2), with `site_code`, `pest_code`, `max_application_rate_lbs_acre`, `max_applications_per_season`, `preharvest_interval_days`, `application_method`, and `restricted_entry_interval_hours` — plus an optional `commodity_code` and `tolerance_ppm` when the new use needs a tolerance. A `RATE_CHANGE` payload carries `use_site_id` and `new_max_application_rate_lbs_acre`. A `METHOD_CHANGE` payload carries `use_site_id`, `new_application_method`, and an optional `expedited` flag; setting `expedited` on any other amendment type is `ERR_INVALID_REQUEST`. A `use_site_id` that does not name a use site of the same product fails `ERR_USE_SITE_PRODUCT_MISMATCH` (HTTP 400). The 8.0-pound-per-acre absolute rate cap applies here as well: a `NEW_USE` site rate or a `RATE_CHANGE` target rate above the cap is rejected with `ERR_RATE_EXCEEDS_SAFETY_CAP`.

The statutory review timeline is computed at filing. The base is 365 days for a `NEW_USE`, 180 days for a `RATE_CHANGE`, and 91 days for a `METHOD_CHANGE`. Three adders accumulate onto the base: 90 days when the product's `classification` is `RESTRICTED_USE`; 180 days when a `NEW_USE` payload includes `tolerance_ppm` (a new food use); and 60 days when any endangered-species bulletin of the product is `IN_EFFECT`. A `METHOD_CHANGE` filed with `expedited` true halves the accumulated total, rounding up to a whole number of days. The amendment's `review_due_at` is its `submitted_at` plus the total days, and its `priia_category` is the amendment-type string, suffixed `-EXPEDITED` exactly when the halving applied.

Endangered-species restrictions gate the filing itself (§3.6 details the bulletins): an `IN_EFFECT` bulletin with `restriction_code` `PROHIBITED` blocks `NEW_USE` filings on the product outright, and an `IN_EFFECT` `RATE_CAP` bulletin caps any new rate — the `RATE_CHANGE` target or a `NEW_USE` site rate — at the bulletin's `rate_cap_lbs_acre`; either conflict fails `ERR_ESA_PROHIBITION_CONFLICT` (HTTP 422).

Decision power rests with a `RegistrationReviewer`, who approves or rejects a `SUBMITTED` amendment (optionally recording `decision_notes`); acting on an amendment no longer `SUBMITTED` fails `ERR_AMENDMENT_NOT_PENDING`. The product gate is re-checked at decision time exactly as at filing: `CANCELLED` fails `ERR_PRODUCT_TERMINAL`, and `UNREGISTERED` or `SUSPENDED` fails `ERR_PRODUCT_NOT_REGISTERED`. An approval stamps `decided_at` and applies the payload to the label. For `NEW_USE`, the system mints the payload's use site directly in `ACTIVE` with `origin` `AMENDMENT` — a documented exception to the usual rule that use sites are born `PROPOSED` — and when the payload carries `tolerance_ppm` it also mints a tolerance directly in `ESTABLISHED` with `origin` `AMENDMENT` and `established_at` stamped, again bypassing the usual `PROPOSED` birth. For `RATE_CHANGE`, the target use site's `max_application_rate_lbs_acre` is rewritten to `new_max_application_rate_lbs_acre`. For `METHOD_CHANGE`, the target's `application_method` is rewritten to `new_application_method`. A rejection stamps `decided_at` and leaves the label untouched; rejection can also arrive from the system itself, when the cancellation cascade of §3.8 auto-rejects commodity-matched `NEW_USE` amendments. The registrant may withdraw a `SUBMITTED` amendment with an optional `reason`; withdrawal from any other status is likewise `ERR_AMENDMENT_NOT_PENDING`. `SUBMITTED`, `APPROVED`, `REJECTED`, and `WITHDRAWN` are the amendment's four statuses, the last three terminal.

### 3.6. Endangered-Species Bulletins and Geographic Restriction

Endangered-species consultation produces county-level use restrictions published as bulletins. A `RegistrationReviewer` publishes one with `product_id`, a five-digit `county_fips`, a `restriction_code` of `PROHIBITED`, `RATE_CAP`, or `SEASONAL_WINDOW`, a `consultation_reference` string for the underlying Biological Opinion, and a restricted month window running from `window_start_month` to `window_end_month`. Each month value is an integer from 1 to 12 inclusive — a value outside that range is `ERR_INVALID_REQUEST` — and the window is the closed set of months from start to end, wrapping past December, so a start of 11 with an end of 2 means the set {11, 12, 1, 2}. The `rate_cap_lbs_acre` field — strictly greater than zero — is required exactly when the restriction code is `RATE_CAP` and forbidden otherwise. Two bulletins of the same product and county that would both be `IN_EFFECT` may not share a calendar month; an overlapping publication is rejected with `ERR_BULLETIN_WINDOW_OVERLAP` (HTTP 409). A bulletin is born `IN_EFFECT` with `effective_at` stamped from the clock and `lifted_at` null.

While a bulletin is `IN_EFFECT` it has two teeth, both felt at amendment filing time (§3.5): a `PROHIBITED` bulletin blocks `NEW_USE` filings on the product, and a `RATE_CAP` bulletin caps newly filed rates at its `rate_cap_lbs_acre` — violations fail `ERR_ESA_PROHIBITION_CONFLICT` — and the mere presence of any `IN_EFFECT` bulletin on the product adds 60 days to every amendment's review timeline. A `SEASONAL_WINDOW` bulletin participates in the timeline adder and the overlap rule like any other restriction.

When the consultation resolves, a reviewer lifts the bulletin, optionally recording a `lift_reason`; lifting moves `IN_EFFECT` → `LIFTED`, stamps `lifted_at`, and is the bulletin's only transition — lifting one that is not `IN_EFFECT` fails `ERR_BULLETIN_NOT_LIFTABLE` (HTTP 409).

### 3.7. The Registration Review Cycle and Data Call-Ins

Registration review re-evaluates every registered product on a recurring cycle. Cases arrive three ways: the first is auto-created at application approval (§3.4); each completion auto-schedules the next; and a `RegistrationReviewer` may also schedule one manually for a `REGISTERED` product — a product in any other status refuses the manual create with `ERR_PRODUCT_NOT_REGISTERED`. Manual scheduling takes `product_id`, an `opened_at` instant, and an optional `due_at` that defaults to 180 days after opening; an `opened_at` later than `due_at` is `ERR_INVALID_REQUEST`. The half-open window from `opened_at` (inclusive) to `due_at` (exclusive) must not intersect the window of any other non-terminal case of the same product — touching endpoints are permitted — or the creation fails `ERR_REVIEW_CASE_WINDOW_OVERLAP` (HTTP 409). However a case arrives, its `cycle_number` is one plus the count of pre-existing cases for the product, so creation order (`created_at` ascending) fully determines cycle order and identifiers never participate.

A case is born `SCHEDULED` and opens when the clock reaches its `opened_at` (sweep step 1, §2.4), pulling a `REGISTERED` product into `UNDER_REVIEW` and leaving a `SUSPENDED` one alone. While a case is `OPEN` or `UNDER_REVIEW`, a reviewer may issue a data call-in against it with `review_case_id`, a non-empty `required_study_types` array of study-type values, and a `response_deadline` strictly later than the logical clock — a deadline not strictly in the future fails `ERR_INVALID_REQUEST`. Issuance stamps `issued_at`, births the call-in in `ISSUED`, and moves the case to `DCI_PENDING`; issuing against a case in any other status fails `ERR_CASE_NOT_OPEN`.

The registrant answers by responding with a `study_submission_ids` array. Every id must exist, must already bear this call-in's `data_call_in_id`, and must belong to the responding registrant's own product — any mismatch fails `ERR_STUDY_PARENT_MISMATCH`. Responding is permitted from `ISSUED`, from `RESPONDED` (additional studies), from `DEFICIENT` (a cure response), and even from `DELINQUENT` — a late cure, which is accepted on its merits but does not undo the suspension the delinquency already fired, and the case stays `REFERRED`; only a `SATISFIED` call-in refuses further response, with `ERR_DCI_NOT_RESPONDABLE`. Each response stamps `responded_at` and recomputes the obligation ledger that every call-in carries: `satisfied_study_types` are the required types with at least one `ACCEPTED` study bearing this call-in, `pending_study_types` are the required types with no accepted study but at least one still `RECEIVED`, and `outstanding_study_types` are the remainder. The three sets partition `required_study_types` exactly at all times — every required type is in precisely one of them.

Two automatic transitions keep the ledger honest. When a response leaves every required type satisfied, the call-in becomes `SATISFIED` on the spot; when instead a study acceptance completes the set, the promotion happens only if the call-in currently sits in `RESPONDED` or `DEFICIENT`. In both cases, once every call-in of a `DCI_PENDING` case has reached `SATISFIED`, the case returns to `UNDER_REVIEW`. Conversely, a rejection of a linked study while its call-in is `RESPONDED` knocks the call-in back to `DEFICIENT`.

Delinquency is the clock's enforcement arm. When sweep step 2 (§2.4) finds a call-in in `ISSUED`, `RESPONDED`, or `DEFICIENT` whose `response_deadline` is now strictly past, the call-in becomes `DELINQUENT` and its case — whether that case sits in `DCI_PENDING` or `UNDER_REVIEW`, the cascade is identical — becomes `REFERRED`, firing a four-hop cascade: unless the product is already `SUSPENDED` or `CANCELLED`, the system creates a suspension proceeding with `proceeding_type` `SUSPENSION`, `reason` `DCI_DELINQUENCY`, status already `EFFECTIVE`, `auto_created` true, `initiated_by_ref` the literal string `system`, `effective_at` stamped from the clock, and every existing-stocks field null; that effective suspension moves the product from `REGISTERED` or `UNDER_REVIEW` to `SUSPENDED`; and the suspension in turn denies each of the product's `SUBMITTED` state registrations.

Completion closes the loop. A reviewer completes a case that is `OPEN` or `UNDER_REVIEW`, optionally recording a `completion_summary`; a case in any other status fails `ERR_CASE_NOT_COMPLETABLE`, and any call-in of the case still in `ISSUED`, `RESPONDED`, `DEFICIENT`, or `DELINQUENT` blocks completion with `ERR_DCI_OUTSTANDING`. Because a `DCI_PENDING` case always has at least one unsatisfied call-in, that call-in check is the one that fires there — successful completion is reachable only from `OPEN` (no call-ins yet) or `UNDER_REVIEW`. Completion stamps `completed_at`, returns the product from `UNDER_REVIEW` to `REGISTERED` when no other non-terminal case of the product remains, and auto-schedules the next cycle: a fresh `SCHEDULED` case with the next `cycle_number`, `opened_at` exactly 5,475 days after the completion instant, and `due_at` 180 days after it opens. `SCHEDULED`, `OPEN`, `DCI_PENDING`, `UNDER_REVIEW`, `COMPLETED`, and `REFERRED` are the six case statuses, the last two terminal.

### 3.8. Suspension, Cancellation, and Existing Stocks

Enforcement begins when a `RegistrationReviewer` opens a proceeding against a product in `REGISTERED`, `UNDER_REVIEW`, or `SUSPENDED`, naming `product_id`, a `proceeding_type` of `CANCELLATION` or `SUSPENSION`, and a `reason` of `RISK_FINDING`, `IMMINENT_HAZARD`, `DCI_DELINQUENCY`, or `REGISTRANT_REQUEST`. The manual route admits at most one non-terminal proceeding per product — while another is `INITIATED`, `HEARING_HELD`, or `EFFECTIVE`, the create fails `ERR_DUPLICATE_OPEN_PROCEEDING`; the auto-created delinquency suspension of §3.7 is created outside this endpoint and is not subject to that check. A manually opened proceeding is born `INITIATED` with `auto_created` false and `initiated_by_ref` and `initiated_at` stamped.

The two proceeding types walk different gaits. A `CANCELLATION` proceeds deliberately: the reviewer first holds the hearing — hearings exist only for cancellations, and hearing a suspension or a proceeding no longer `INITIATED` fails `ERR_PROCEEDING_INVALID_STEP` — optionally recording `hearing_notes` and stamping `hearing_held_at`, which moves the proceeding to `HEARING_HELD`; the cancellation order then issues from `HEARING_HELD`. A `SUSPENSION` is an emergency order: it issues directly from `INITIATED` with no hearing at all. Issuing from the wrong step or with the wrong type fails `ERR_PROCEEDING_INVALID_STEP` (HTTP 409), and segregation of duties applies at the order: the issuing reviewer's `X-User-ID` must differ from the proceeding's `initiated_by_ref`, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

The order payload differs by type. A cancellation order requires `existing_stocks_authorized_units` (at least 0) and a `stocks_method` of `FIXED` or `DEPLETION`, plus `depletion_rate_units_per_month` (strictly greater than 0) exactly when the method is `DEPLETION`. A suspension order must carry none of those three fields. Either violation is `ERR_INVALID_REQUEST`.

Issuing either order stamps `effective_at` and captures `pre_effective_product_status` from the product's current status. A suspension order then flips the product from `REGISTERED` or `UNDER_REVIEW` to `SUSPENDED` and, as its one cascading hop, denies each of the product's `SUBMITTED` state registrations. A cancellation order computes the existing-stocks deadlines and fires the full cancellation cascade.

The existing-stocks deadlines come in two variants, selected by `stocks_method`. Under `FIXED`, the deadlines are statutory and independent of quantity: `allow_sale_until` is 365 days after `effective_at`, and `allow_use_until` is 730 days after. Under `DEPLETION`, the sale window in days is the authorized units divided by the declared monthly depletion rate, multiplied by thirty, and rounded up to a whole number of days; `allow_sale_until` is that many days after `effective_at`, and `allow_use_until` is exactly twice that many days. The variants genuinely diverge: 12,000 authorized units depleting at 2,000 units per month produce a 180-day sale window under `DEPLETION` against the 365 days `FIXED` would give.

The cancellation cascade runs hop by hop. Hop 1: the product becomes `CANCELLED`, whether it stood at `REGISTERED`, `UNDER_REVIEW`, or `SUSPENDED` when the order issued. Hop 2, caused by hop 1: every tolerance of the product in `PROPOSED` or `ESTABLISHED` becomes `REVOKED`, with `pre_revocation_status` capturing the prior status and `revoked_at` stamped; every use site in `ACTIVE` becomes `REMOVED`, with `pre_removal_status` set to `ACTIVE` and `removed_at` stamped; every non-terminal application of the product — `DRAFT`, `IN_REVIEW`, or `DATA_DEFICIENCY` — becomes `WITHDRAWN`, and the use sites and tolerances those applications still held in `PROPOSED` are removed and revoked with `pre_removal_status` and `pre_revocation_status` left null; and the product's state registrations in `GRANTED` or `LAPSED` become `REVOKED` while those still `SUBMITTED` become `DENIED`. Hop 3, caused by hop 2's tolerance revocations: every `SUBMITTED` amendment of type `NEW_USE` whose payload `commodity_code` equals the commodity code of a tolerance just revoked in hop 2 is auto-rejected with `decided_at` stamped; all other pending amendments are left untouched.

Existing-stocks sell-through is recorded as disposals against the effective order. Recording one requires the proceeding to be `EFFECTIVE` with a stocks provision — a disposal against any other proceeding fails `ERR_PROCEEDING_INVALID_STEP`. Each disposal carries `units` and a `method` of `SALE`, `RETURN`, or `DESTRUCTION`. `SALE` and `RETURN` disposals are accepted only while the clock is at or before `allow_sale_until`; every method is accepted only while the clock is at or before `allow_use_until`; a disposal outside its window fails `ERR_EXISTING_STOCKS_WINDOW_CLOSED` (HTTP 422). The running total `existing_stocks_disposed_units` — the sum of `units` over the append-only `existing_stocks_disposals` records, zero when the array is empty — may never exceed `existing_stocks_authorized_units`, and a record that would push it past the ceiling fails `ERR_EXISTING_STOCKS_QUANTITY_EXCEEDED` (HTTP 422). Each accepted record appends `{disposed_at, units, method}` to `existing_stocks_disposals` with `disposed_at` stamped from the clock, and the total is recomputed.

Vacatur unwinds an order — within limits. A reviewer vacates a proceeding in `INITIATED`, `HEARING_HELD`, or `EFFECTIVE`, supplying `vacatur_reason`; vacating a proceeding in any other status fails `ERR_PROCEEDING_INVALID_STEP`. Vacatur stamps `vacated_at`, and from `INITIATED` or `HEARING_HELD` nothing else happens, because nothing has yet taken effect. Vacating an `EFFECTIVE` cancellation performs the documented restore, and it is the sole documented exception to the terminality of `CANCELLED`: the product returns to the proceeding's `pre_effective_product_status` — which may be `REGISTERED`, `UNDER_REVIEW`, or `SUSPENDED`, so the restore target is whatever was captured, not always `REGISTERED`; every tolerance whose `pre_revocation_status` is non-null and whose `revoked_at` equals the vacated proceeding's `effective_at` returns to its `pre_revocation_status`, whether that prior status was `PROPOSED` or `ESTABLISHED`, and the marker is cleared; and every use site whose `pre_removal_status` is `ACTIVE` and whose `removed_at` equals that same instant returns to `ACTIVE`, marker cleared — use sites removed from the `PROPOSED` state by deny or withdraw carry a null marker and never restore. Three documented asymmetries are deliberately not restored: state registrations stay `REVOKED` or `DENIED`, withdrawn applications stay `WITHDRAWN`, and cascade-rejected amendments stay `REJECTED`. Vacating an `EFFECTIVE` suspension restores nothing at all — the product simply remains `SUSPENDED` until reinstatement.

Reinstatement is the way back from suspension. A reviewer reinstates a product that is `SUSPENDED`; calling it on a product in any other status fails `ERR_PRODUCT_NOT_SUSPENDED`. Two blockers refuse with `ERR_REINSTATEMENT_BLOCKED`: any proceeding of the product still `EFFECTIVE`, and any data call-in of any case of the product still in `ISSUED`, `RESPONDED`, `DEFICIENT`, or `DELINQUENT`. A clean reinstatement returns the product to `REGISTERED` — unless a case of the product is currently `OPEN`, `DCI_PENDING`, or `UNDER_REVIEW`, in which case it returns to `UNDER_REVIEW` instead; a merely `SCHEDULED` future cycle does not hold the product under review.

### 3.9. Applicator Certification and State Registration

Restricted-use products can only be sold into a state when certified applicators exist there, and the certification lifecycle is small but strict. A `CertificationAuthority` issues a certification with `applicator_name`, a `state_code` (for example, `TX`), a `category` of `AGRICULTURAL_PEST_CONTROL`, `AERIAL_APPLICATION`, `STRUCTURAL`, or `AQUATIC`, and a `certified_until` instant that must be strictly later than the logical clock — a non-future expiry fails `ERR_INVALID_REQUEST`. A certification is born `ACTIVE` with `renewed_count` zero, and the clock sweep (§2.4, step 3) flips it to `EXPIRED` once its `certified_until` is strictly earlier than the current time; an expiry exactly equal to the clock does not expire. Renewal is allowed from both `ACTIVE` (early renewal) and `EXPIRED`, under identical rules: the supplied `new_certified_until` must be strictly later than the logical clock, failing `ERR_CERTIFICATION_RENEWAL_INVALID` (HTTP 400) otherwise, and a successful renewal writes `certified_until`, increments `renewed_count` by one, and returns the row to `ACTIVE`. Certifications list with `state_code`, `category`, and `status` filters.

State registration layers state approval on top of the federal one. For a `REGISTERED` product it owns, the representative applies with `product_id` and `state_code`; the state must be one of the four supported states (`ERR_INVALID_REQUEST` otherwise), the product must be `REGISTERED` at filing (`ERR_PRODUCT_NOT_REGISTERED` otherwise), and at most one non-terminal registration — one in `SUBMITTED`, `GRANTED`, or `LAPSED` — may exist per product-and-state pair, with a collision failing `ERR_DUPLICATE_STATE_REGISTRATION` (HTTP 409). The application is born `SUBMITTED` with `submitted_at` and `registrant_ref` stamped, `renewal_count` zero, and `granted_at`, `renewal_due_at`, `last_renewal_at`, and `annual_fee_cents` all null until the first grant.

A `StateLeadAgency` then decides. A grant requires the row still in `SUBMITTED` (else `ERR_STATE_REG_NOT_DECIDABLE`, HTTP 409); it re-checks that the product is `REGISTERED` at decision time, not merely at filing (`ERR_PRODUCT_NOT_REGISTERED`); and when the product's `classification` is `RESTRICTED_USE`, it requires at least one applicator certification whose `state_code` equals the registration's state, whose `status` is `ACTIVE`, and whose `certified_until` is at or after the current clock — without one, the grant fails `ERR_NO_VALID_APPLICATOR_CERTIFICATION` (HTTP 422). A successful grant stamps `granted_at`, sets `renewal_due_at` 365 days out, records the payload's `additional_restrictions` array (defaulting to empty), and stamps `annual_fee_cents` as the state's base fee — 40,000 cents for `CA`, 25,000 for `TX`, 18,000 for `IA`, and 30,000 for `FL` — plus a restricted-use surcharge of 10,000 cents when the product is `RESTRICTED_USE` at grant time. A denial simply moves `SUBMITTED` → `DENIED`. The agency may also revoke a registration in `GRANTED` or `LAPSED`, optionally recording a `reason`; revoking from any other status fails `ERR_STATE_REG_NOT_DECIDABLE`. `DENIED` and `REVOKED` are terminal.

Renewal is annual, and its fee arithmetic is pinned because the due date is both input and output. When the clock is at or before `renewal_due_at`, the registration is zero months overdue; otherwise the count of months overdue is the whole days between `renewal_due_at` and the clock, divided by thirty and rounded down, plus one. The subtotal is the `annual_fee_cents` stamped at grant. The late penalty is ten percent of that subtotal per month overdue, rounded half-up to a whole cent. The fee due is the subtotal plus the penalty, and the representative's `payment_cents` must equal it exactly, failing `ERR_INCORRECT_FEE_PAYMENT` (HTTP 402) on any difference. Renewal requires the registration in `GRANTED` or `LAPSED` (else `ERR_STATE_REG_NOT_DECIDABLE`) and the product in `REGISTERED` or `UNDER_REVIEW` — a product in any other non-terminal status fails `ERR_PRODUCT_NOT_REGISTERED`, while a `CANCELLED` product forbids the renewal outright with `ERR_PRODUCT_TERMINAL`. Only after the fee is fixed does the anniversary move: `renewal_due_at` advances by exactly 365 days from its previous value — never from the payment date, so chronically late renewals do not reset the anniversary — while `last_renewal_at` is stamped from the clock and `renewal_count` increments by one. A renewed `LAPSED` registration returns to `GRANTED`; a `GRANTED` one stays `GRANTED`.

Lapse itself is automatic: sweep step 4 (§2.4) moves a `GRANTED` registration to `LAPSED` once the instant thirty days after its `renewal_due_at` is strictly earlier than the clock. And the state layer always follows the federal one: a product suspension denies its `SUBMITTED` registrations, a product cancellation revokes its `GRANTED` and `LAPSED` rows while denying its `SUBMITTED` ones, and vacatur of that cancellation restores none of them (§3.8).

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — submissions, decisions, withdrawals, renewals, lifts, completions, responses, hearings, orders, vacaturs, disposals, revocations, and reinstatements — return `200 OK`, as do all reads and the logical-clock set. The request and response bodies of each operation are specified by the narratives of §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; runs the four-step sweep | SystemAdministrator |
| POST | `/pesticide-registry/active-ingredients` | Register an active ingredient (reference data) | SystemAdministrator |
| GET | `/pesticide-registry/active-ingredients` | List active ingredients | All roles |
| POST | `/pesticide-registry/products` | Create a product shell | RegistrantRepresentative |
| GET | `/pesticide-registry/products` | List products with filters | All roles |
| GET | `/pesticide-registry/products/{id}` | Get a product | All roles |
| POST | `/pesticide-registry/products/{id}/reinstate` | Lift a suspension after cure | RegistrationReviewer |
| GET | `/pesticide-registry/products/{id}/use-sites` | List the product's label use sites | All roles |
| GET | `/pesticide-registry/products/{id}/tolerances` | List the product's tolerances | All roles |
| GET | `/pesticide-registry/products/{id}/endangered-species-bulletins` | List the product's bulletins | All roles |
| GET | `/pesticide-registry/products/{id}/registration-review-cases` | List the product's review cases | All roles |
| POST | `/pesticide-registry/registration-applications` | Create an application in DRAFT | RegistrantRepresentative |
| GET | `/pesticide-registry/registration-applications` | List applications | All roles |
| GET | `/pesticide-registry/registration-applications/{id}` | Get an application | All roles |
| POST | `/pesticide-registry/registration-applications/{id}/submit` | Submit or resubmit an application | RegistrantRepresentative |
| POST | `/pesticide-registry/registration-applications/{id}/withdraw` | Withdraw a non-terminal application | RegistrantRepresentative |
| POST | `/pesticide-registry/registration-applications/{id}/review-decisions` | Reviewer decision: APPROVE, DENY, or DEFICIENCY | RegistrationReviewer |
| GET | `/pesticide-registry/registration-applications/{id}/study-submissions` | List studies attached to the application | All roles |
| GET | `/pesticide-registry/registration-applications/{id}/risk-assessments` | List the application's risk assessments | All roles |
| POST | `/pesticide-registry/study-submissions` | Submit a study against an application or data call-in | RegistrantRepresentative |
| GET | `/pesticide-registry/study-submissions` | List studies with filters | All roles |
| GET | `/pesticide-registry/study-submissions/{id}` | Get a study | All roles |
| POST | `/pesticide-registry/study-submissions/{id}/review-decisions` | Accept or reject a study | RiskAssessor |
| POST | `/pesticide-registry/risk-assessments` | Run a SCREENING or REFINED risk assessment | RiskAssessor |
| POST | `/pesticide-registry/tolerances` | Propose a tolerance for a product | RegistrantRepresentative |
| POST | `/pesticide-registry/label-amendments` | File a label amendment (OCC-guarded) | RegistrantRepresentative |
| GET | `/pesticide-registry/label-amendments` | List label amendments | All roles |
| GET | `/pesticide-registry/label-amendments/{id}` | Get a label amendment | All roles |
| POST | `/pesticide-registry/label-amendments/{id}/withdraw` | Withdraw a pending amendment | RegistrantRepresentative |
| POST | `/pesticide-registry/label-amendments/{id}/review-decisions` | Approve or reject a pending amendment | RegistrationReviewer |
| POST | `/pesticide-registry/applicator-certifications` | Issue an applicator certification | CertificationAuthority |
| GET | `/pesticide-registry/applicator-certifications` | List applicator certifications | All roles |
| POST | `/pesticide-registry/applicator-certifications/{id}/renew` | Renew a certification (ACTIVE or EXPIRED) | CertificationAuthority |
| POST | `/pesticide-registry/endangered-species-bulletins` | Publish a county-level restriction bulletin | RegistrationReviewer |
| POST | `/pesticide-registry/endangered-species-bulletins/{id}/lift` | Lift an IN_EFFECT bulletin | RegistrationReviewer |
| POST | `/pesticide-registry/registration-review-cases` | Manually schedule a review case | RegistrationReviewer |
| GET | `/pesticide-registry/registration-review-cases/{id}` | Get a review case | All roles |
| POST | `/pesticide-registry/registration-review-cases/{id}/complete` | Complete a case; auto-schedules the next cycle | RegistrationReviewer |
| GET | `/pesticide-registry/registration-review-cases/{id}/data-call-ins` | List the case's data call-ins | All roles |
| POST | `/pesticide-registry/data-call-ins` | Issue a data call-in against a case | RegistrationReviewer |
| GET | `/pesticide-registry/data-call-ins/{id}` | Get a data call-in with its obligation ledger | All roles |
| POST | `/pesticide-registry/data-call-ins/{id}/respond` | Respond to a data call-in with linked studies | RegistrantRepresentative |
| POST | `/pesticide-registry/cancellation-proceedings` | Open a cancellation or suspension proceeding | RegistrationReviewer |
| GET | `/pesticide-registry/cancellation-proceedings` | List proceedings | All roles |
| GET | `/pesticide-registry/cancellation-proceedings/{id}` | Get a proceeding | All roles |
| POST | `/pesticide-registry/cancellation-proceedings/{id}/hear` | Hold the hearing (CANCELLATION only) | RegistrationReviewer |
| POST | `/pesticide-registry/cancellation-proceedings/{id}/issue-order` | Issue the cancellation or suspension order | RegistrationReviewer |
| POST | `/pesticide-registry/cancellation-proceedings/{id}/vacate` | Vacate a proceeding | RegistrationReviewer |
| POST | `/pesticide-registry/cancellation-proceedings/{id}/existing-stocks-disposals` | Record an existing-stocks disposal | RegistrationReviewer |
| POST | `/pesticide-registry/state-registrations` | Apply for state registration | RegistrantRepresentative |
| GET | `/pesticide-registry/state-registrations` | List state registrations | All roles |
| GET | `/pesticide-registry/state-registrations/{id}` | Get a state registration | All roles |
| POST | `/pesticide-registry/state-registrations/{id}/review-decisions` | State decision: GRANT or DENY | StateLeadAgency |
| POST | `/pesticide-registry/state-registrations/{id}/revoke` | Revoke a GRANTED or LAPSED registration | StateLeadAgency |
| POST | `/pesticide-registry/state-registrations/{id}/renew` | Renew a GRANTED or LAPSED registration | RegistrantRepresentative |

## 5. Error Code Catalogue

The trigger condition for each error is stated in the narrative of §2 and §3 where its workflow lives; this table is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_STATE_REGISTRATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_PRODUCT_VERSION` | 412 Precondition Failed |
| `ERR_APPLICATION_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_APPLICATION_ALREADY_DECIDED` | 409 Conflict |
| `ERR_PRODUCT_NOT_UNREGISTERED` | 409 Conflict |
| `ERR_PRODUCT_NOT_REGISTERED` | 409 Conflict |
| `ERR_PRODUCT_TERMINAL` | 409 Conflict |
| `ERR_PRODUCT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_REINSTATEMENT_BLOCKED` | 409 Conflict |
| `ERR_STUDY_NOT_DECIDABLE` | 409 Conflict |
| `ERR_AMENDMENT_NOT_PENDING` | 409 Conflict |
| `ERR_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_CASE_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_DCI_OUTSTANDING` | 409 Conflict |
| `ERR_DCI_NOT_RESPONDABLE` | 409 Conflict |
| `ERR_PROCEEDING_INVALID_STEP` | 409 Conflict |
| `ERR_STATE_REG_NOT_DECIDABLE` | 409 Conflict |
| `ERR_BULLETIN_NOT_LIFTABLE` | 409 Conflict |
| `ERR_RATE_EXCEEDS_SAFETY_CAP` | 422 Unprocessable Entity |
| `ERR_ESA_PROHIBITION_CONFLICT` | 422 Unprocessable Entity |
| `ERR_NO_VALID_APPLICATOR_CERTIFICATION` | 422 Unprocessable Entity |
| `ERR_MISSING_REQUIRED_STUDIES` | 422 Unprocessable Entity |
| `ERR_NO_RISK_ASSESSMENT` | 422 Unprocessable Entity |
| `ERR_LOC_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_PROPOSED_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_OPEN_APPLICATION` | 409 Conflict |
| `ERR_DUPLICATE_TOLERANCE` | 409 Conflict |
| `ERR_BULLETIN_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REVIEW_CASE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_STATE_REGISTRATION` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_PROCEEDING` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_EXISTING_STOCKS_QUANTITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STUDY_PARENT_MISMATCH` | 400 Bad Request |
| `ERR_USE_SITE_PRODUCT_MISMATCH` | 400 Bad Request |
| `ERR_UNKNOWN_COMMODITY` | 422 Unprocessable Entity |
| `ERR_EXISTING_STOCKS_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_RENEWAL_INVALID` | 400 Bad Request |
| `ERR_INCORRECT_FEE_PAYMENT` | 402 Payment Required |

