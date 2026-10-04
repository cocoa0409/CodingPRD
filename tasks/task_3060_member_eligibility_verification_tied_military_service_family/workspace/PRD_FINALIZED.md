# Member Eligibility Military Lineage API — Product Requirements Document

## 1. Introduction

Membership in this association is not purchased; it is earned through service or inherited through family. The Member Eligibility Military Lineage API governs the full lifecycle of that determination — from an applicant's first submission of service documentation, through adjudication by verification officers, to the issuance of a permanent member number and the lineage linkage of spouses, children, and widows across generations. Because the product surface spans banking, insurance, and investment offerings with category-gated availability, every decision the API makes about who a member is propagates directly into what that member may hold.

The system is built for the hard cases, not the easy ones. Records burn in archive fires; the API supports a formal record-reconstruction path for lost service documentation, but separates the officer who reconstructs from the officer who approves. Families fracture and reform through divorce, remarriage, and adoption; extended lineage verification applies a stricter evidence chain to those derivations. Members deploy, and federal servicemember protections entitle them to rate relief and claim deferrals that must be computed to the cent. Members die, and the survivor cascade must move entitlements, compute continuance support, and re-anchor households without manual rekeying. Throughout, a logical clock — never wall-clock time — drives every date comparison, so that deferred activations, relief windows, and evidence freshness checks are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `EligibilityApplicant`, `VerificationOfficer`, `Member`, `BenefitsOfficer`, `ProductAdministrator`, and `PlatformAdmin`.

Identity semantics differ by role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` row itself; ownership checks on any route of the form `/membership/members/{memberId}/...` compare the `{memberId}` path parameter against `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_ROLE`. When `X-User-Role` is `EligibilityApplicant`, `VerificationOfficer`, `BenefitsOfficer`, `ProductAdministrator`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `verification_officer_id` on an approved `EligibilityCase`, `record_reconstruction_officer_id` on a reconstructed case, or `approved_by_officer_id` on an approved `ProtectionClaim` — but it never compares such an identifier to any entity's `id`, except where a segregation-of-duties rule explicitly requires the comparison.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Every list response is sorted by `created_at` in ascending order unless otherwise specified, and every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Member Number

Every resource in the system carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that increments by exactly 1 on every mutation to the resource. All eleven resource types — `EligibilityCase`, `ServiceRecord`, `EvidenceDocument`, `Member`, `Household`, `AddressAssignment`, `DeploymentOrder`, `ProtectionClaim`, `ProductOffering`, `ProductEntitlement`, and `SurvivorSupportCase` — carry the full set.

The `Member` resource additionally carries `member_number`, a zero-padded ten-digit sequential number assigned at the moment a case is approved. The first member ever minted receives `0000000001`; the counter advances by one per approval, numbers are permanent, and a number is never reassigned even if the member is later revoked.

### 2.5. The Logical Clock

All date and time comparisons in the system — deployment activation windows, service-period length, evidence freshness, relief periods, duty-station retroactivity — are evaluated against a **logical clock**, never against wall-clock time. Before any call is made, the logical clock reads exactly `2026-09-01T00:00:00Z`, and the server must not fall back to wall-clock time under any circumstance. A `PlatformAdmin` may advance the clock by supplying a `to_iso8601` instant through the clock-setting capability described in §4. Advancing the clock has exactly one retroactive consequence: every `REGISTERED` deployment order whose `start_date` is on or before the new clock reading auto-activates to `ACTIVE`, carrying the posture cascade described in §3.5 when the owning member is `ACTIVE`. No other recomputation is triggered by a clock advance.

### 2.6. Case Adjudication Integrity and Segregation of Duties

Adjudication power is deliberately split. When an eligibility case has passed through the record-reconstruction path for lost records, the officer who performed that reconstruction is barred from approving the same case: at decide time the acting officer's `X-User-ID` must differ from the case's `record_reconstruction_officer_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The same wall stands between a member and their own protection claims: the approving officer's `X-User-ID` must differ from the claim's owning `member_id`. These checks are evaluated after role authorization but before the business-rule checks described in §3, so a duty violation surfaces as `ERR_SEGREGATION_OF_DUTIES` rather than being masked by a downstream derivation or fiscal failure.

### 2.7. Validation Order and Nested Resource Retrieval

Validations are applied in a fixed priority order on every request, and an earlier failure masks every later one. The order is: (1) header authentication, producing `ERR_UNAUTHENTICATED`; (2) role authorization and `Member`-role ownership of the `{memberId}` path parameter, producing `ERR_FORBIDDEN_ROLE`; (3) path-parameter existence, producing `ERR_NOT_FOUND`; (4) request-body well-formedness — every required input field present and every enum field carrying a declared value — producing `ERR_INVALID_REQUEST`; (5) state-machine preconditions on state-transition endpoints, producing `ERR_INVALID_STATE`; then (6) onward, the business checks — duplicate-content and duplicate-order guards, segregation of duties, interval-overlap rules, foreign-key resolution producing `ERR_INVALID_REFERENCE`, and the domain constraints described in §3 — each surfacing its own declared error code. Existence checks on nested paths are performed strictly left to right: for a path such as `/membership/members/{memberId}/entitlements/{entitlementId}/close`, an unknown `memberId` yields `ERR_NOT_FOUND` before the entitlement identifier is ever examined.

Within the business tier the relative ordering matters where rules overlap. Duplicate evidence (`ERR_DUPLICATE_EVIDENCE`) is checked before duplicate deployment orders (`ERR_DUPLICATE_ORDER`); both precede segregation of duties. Interval checks — address overlap (`ERR_ADDRESS_OVERLAP`) and deployment overlap (`ERR_DEPLOYMENT_OVERLAP`) — precede foreign-key resolution (`ERR_INVALID_REFERENCE`). Lineage depth (`ERR_LINEAGE_DEPTH_EXCEEDED`), extended lineage proof (`ERR_LINEAGE_PROOF_INSUFFICIENT`), and eligibility derivation (`ERR_ELIGIBILITY_DERIVATION_FAILED`) are evaluated in that relative order; the product category gate (`ERR_PRODUCT_CATEGORY_FORBIDDEN`), household non-emptiness (`ERR_HOUSEHOLD_NOT_EMPTY`), and SCRA eligibility (`ERR_SCRA_NOT_ELIGIBLE`) follow; the fiscal relief cap (`ERR_RELIEF_CAP_EXCEEDED`) is evaluated after SCRA eligibility. The stale-version optimistic-concurrency check (`ERR_STALE_VERSION`) sits between the fiscal checks and the remaining referential checks — sponsor activeness (`ERR_SPONSOR_NOT_ACTIVE`) and beneficiary activeness (`ERR_BENEFICIARY_NOT_ACTIVE`) — which in turn precede the evidence-presence family: service-record presence (`ERR_SERVICE_RECORD_REQUIRED`), evidence presence (`ERR_EVIDENCE_REQUIRED`), new-evidence-on-resubmit (`ERR_NO_NEW_EVIDENCE`), and all-records-verified (`ERR_SERVICE_RECORD_UNVERIFIED`). The temporal deployment checks (`ERR_DEPLOYMENT_NOT_ENDED`, then `ERR_DEPLOYMENT_END_DATE_REQUIRED`), the positive-relief check (`ERR_NO_RELIEF_AVAILABLE`), the reinstatement-evidence check (`ERR_REINSTATEMENT_EVIDENCE_REQUIRED`), and the duty-station conflict check (`ERR_DUTY_STATION_CONFLICT`) close the order. Between the two address guards, a duty-station posting whose `effective_from` is not earlier than the member's current open duty-station interval — and so is not a retroactive PCS under §3.11 — but that overlaps an existing same-type interval is rejected with `ERR_ADDRESS_OVERLAP`, not `ERR_DUTY_STATION_CONFLICT`.

### 2.8. Optimistic Concurrency Control on Member-Anchored Writes

Two writes against a member are guarded by optimistic concurrency control, and both name the same field. Linking a member into a household requires the request body to carry `expected_member_version`, the client-side copy of the member's current `version`. Registering a deployment order against a member likewise requires `expected_member_version`. In both cases, if the supplied value does not equal the member's current `version` on the server, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the situation where another writer has legitimately re-linked the member to a different household — linking supersedes the prior linkage — or where an approval or posture cascade has advanced the member's `version` since the client last read it. Both guarded writes themselves increment the member's `version` by 1 on success. Endpoints not named here do not accept a version field at all.

### 2.9. Household Aggregation Discipline

A household's `aggregate_product_count` is a derived integer, never edited directly. It is recomputed on every event that could change it: a member linking or delinking, a member approval that auto-links to a sponsor's household, a category assignment, any member status transition, any deployment-posture transition, any product-offering flag or category change, and any entitlement close. The recompute proceeds in a pinned order: first each contributing member's product availability matrix is recomputed, then the per-member available-facet counts are summed. Only members linked to the household whose status is `ACTIVE` or `SUSPENDED` contribute; `DECEASED` and `REVOKED` members are excluded from the sum. The result is always an exact integer.

### 2.10. Monetary Precision

All monetary values in the system are integer cents. Rate-relief computations floor each monthly period's relief to whole cents before summing across periods — the order is per-period floor, then sum, never sum-then-round. Survivor continuance amounts floor once, after the share-rate multiplication and before the month multiplication. Rates themselves are expressed in basis points as integers.

## 3. Business Logic & Workflows

### 3.1. Opening an Eligibility Case

An `EligibilityApplicant` opens an eligibility case by supplying the `applicant_legal_name` exactly as it appears on the submitted documentation, the `applicant_dob` as an ISO 8601 date, and the `basis_type` — one of `DIRECT_SERVICE`, `FAMILY_DERIVATION`, or `CADET_APPOINTMENT`. The case is persisted in `INTAKE` status.

The family-derivation basis carries two additional fields that are mandatory for that basis and forbidden otherwise: `sponsor_member_id`, referencing the sponsoring `Member`, and `claimed_relationship`, one of `SPOUSE`, `WIDOW_WIDOWER`, `CHILD`, `STEPCHILD`, or `FORMER_SPOUSE`. A direct-service or cadet case must leave both null. An optional boolean `adoption_or_divorce_flag`, defaulting to `false`, marks derivations that run through an adoption or a divorce-and-remarriage event and selects the extended lineage-verification variant described in §3.3. Until approval, the case's `member_id`, `eligibility_category`, `verification_officer_id`, `record_reconstruction_officer_id`, `denial_reason`, and `decision_note` are all null.

### 3.2. Building the File: Service Records and Evidence

While a case is in `INTAKE` or `MORE_INFO_REQUIRED`, the applicant attaches service records. Each record names a `branch` — one of `ARMY`, `NAVY`, `AIR_FORCE`, `MARINES`, `COAST_GUARD`, `SPACE_FORCE`, `NOAA_CORPS`, or `PHS_CORPS` — a `component` of `ACTIVE_DUTY`, `RESERVE`, `NATIONAL_GUARD`, or `CADET`, the highest `rank_grade` attained (free text such as E-6 or O-3), a `service_start_date`, and a `discharge_characterization` drawn from `HONORABLE`, `GENERAL_UNDER_HONORABLE`, `OTHER_THAN_HONORABLE`, `BAD_CONDUCT`, `DISHONORABLE`, `MEDICAL`, `ENTRY_LEVEL`, or `STILL_SERVING`. The `service_end_date` is optional; it stays null while the period is ongoing. From these the system computes `service_days` as the calendar-day count from `service_start_date` to the `service_end_date` when one is set, or to the current logical-clock date when the period is open; a zero-length period yields 0. A direct-service case carries exactly one service record. Every record begins with `service_verified` set to `false`, flipping to `true` only when verification accepts it — whether through submitted evidence or an approved reconstruction.

Evidence documents attach to cases in `INTAKE`, `MORE_INFO_REQUIRED`, or `APPROVED`; post-approval uploads exist to support reinstatement evidence and audit trails, while uploads to a `DENIED` case are rejected with `ERR_INVALID_STATE`. Each document declares a `doc_type` — one of `DD214`, `NGB22`, `MARRIAGE_CERTIFICATE`, `BIRTH_CERTIFICATE`, `ADOPTION_DECREE`, `DIVORCE_DECREE`, `DEATH_CERTIFICATE`, `LEAVE_EARNINGS_STATEMENT`, or `ORDERS` — the `issuing_authority` named on the document, an `issued_on` date, and a client-computed SHA-256 hex digest in `content_hash`. A document may name a `covers_service_record_id` tying it to a specific service record; purely lineage evidence leaves it null. The `authenticity_channel` is fixed at upload and defaults to `SELF_DECLARED`; the other declared channels are `ISSUER_CONFIRMED` and `ARCHIVES_CONFIRMED`. Within a case, the pair of case and `content_hash` is a uniqueness anchor: a second upload with a digest already present on that case is rejected with `ERR_DUPLICATE_EVIDENCE` (HTTP 409).

### 3.3. Submission, Review, and Decision

Submission moves a case from `INTAKE` to `UNDER_REVIEW`. A case on the direct-service or cadet basis cannot be submitted without at least one service record, failing with `ERR_SERVICE_RECORD_REQUIRED`; no case of any basis can be submitted without at least one evidence document, failing with `ERR_EVIDENCE_REQUIRED`. A family-derivation submission additionally requires that the sponsor `Member` exists, that the sponsor's status is `ACTIVE` — otherwise `ERR_SPONSOR_NOT_ACTIVE` — and that the sponsor's `lineage_depth` plus one does not exceed the maximum lineage depth of 3, failing with `ERR_LINEAGE_DEPTH_EXCEEDED` when it would.

A `VerificationOfficer` then decides the case by supplying a `decision` and an optional `decision_note`. Three outcomes exist. A decision of `REQUEST_MORE_INFO` moves the case to `MORE_INFO_REQUIRED` and records the note; the applicant may then upload further evidence, and resubmission back to `UNDER_REVIEW` requires at least one additional evidence document uploaded since the case entered `MORE_INFO_REQUIRED`, failing with `ERR_NO_NEW_EVIDENCE` otherwise. This review loop is unbounded. A decision of `DENY` moves the case to `DENIED` and records the supplied `denial_reason`; a denied case becomes immutable. A decision of `APPROVE` runs the full adjudication gate described next.

Approval is gated by a battery of checks. Every service record on the case must carry `service_verified` true, failing with `ERR_SERVICE_RECORD_UNVERIFIED` otherwise. The segregation-of-duties rule of §2.6 applies against the `record_reconstruction_officer_id`. A family-derivation case requires the sponsor still `ACTIVE` at decide time. Then the derivation rule itself runs, failing with `ERR_ELIGIBILITY_DERIVATION_FAILED` when unsatisfied. Category assignment proceeds by basis. A `CADET_APPOINTMENT` case always yields `OFFICER_CADET`. A `DIRECT_SERVICE` case inspects its single service record: a discharge characterization of `OTHER_THAN_HONORABLE`, `BAD_CONDUCT`, or `DISHONORABLE` fails the derivation outright; a characterization of `STILL_SERVING`, or a null `service_end_date`, yields `ENLISTED_ACTIVE`; anything else yields `VETERAN_HONORABLE`. A `FAMILY_DERIVATION` case maps the `claimed_relationship` — `WIDOW_WIDOWER` to `FAMILY_WIDOW`, `CHILD` or `STEPCHILD` to `FAMILY_CHILD`, and `SPOUSE` or `FORMER_SPOUSE` to `FAMILY_SPOUSE`. The resulting `eligibility_category` is always one of the six values `OFFICER_CADET`, `ENLISTED_ACTIVE`, `VETERAN_HONORABLE`, `FAMILY_SPOUSE`, `FAMILY_WIDOW`, or `FAMILY_CHILD`.

When the case's `adoption_or_divorce_flag` is true, the extended lineage-verification variant adds an evidence-chain completeness requirement on top of the mapping: every evidence document on the case must carry an `authenticity_channel` of `ISSUER_CONFIRMED` or `ARCHIVES_CONFIRMED`, and at least two distinct `doc_type` values must be present across the case's documents. Failure is rejected with `ERR_LINEAGE_PROOF_INSUFFICIENT`.

A successful approval mints the `Member`. The new member receives the next sequential `member_number`, a `legal_name` and `dob` copied from the case, the derived `eligibility_category`, and a `case_id` back-reference to the approving case — unique per member — while the case's `member_id` is set to the new row. The `lineage_depth` is 0 for a direct-service or cadet basis, and the sponsor's `lineage_depth` plus one for a derived member; `sponsor_member_id` and `claimed_relationship` are copied onto the member for derived members and remain null for direct-service members. The deciding officer's `X-User-ID` is recorded as the case's `verification_officer_id`. The member's initial 24-facet `product_matrix_cache` is computed per §3.7. When the sponsor is linked to a household, the new member's `household_id` is set to the sponsor's household and that household's `aggregate_product_count` is recomputed; otherwise `household_id` starts null.

### 3.4. The Lost-Records Exception: Record Reconstruction

Service records burn, floods destroy archives, and applicants should not lose eligibility for the government's lost paper. A `VerificationOfficer` may record an archives-reconstruction decision on a case in `UNDER_REVIEW`, supplying a `decision` and a mandatory `decision_note`. A reconstruction `APPROVE` sets `service_verified` to true on every service record of the case and records the acting officer's `X-User-ID` as the case's `record_reconstruction_officer_id` — the anchor the segregation-of-duties rule later checks at approval time. A reconstruction `DENY` moves the case directly to `DENIED`. The `decision_note` field on the case always reflects the most recent reconstruction decision.

### 3.5. Deployment: Orders, Posture, and the Clock

Deployment orders are registered against a member by a `VerificationOfficer` carrying `orders_number` (unique across all orders — a collision is rejected with `ERR_DUPLICATE_ORDER`), a `theater` label, a `start_date`, a boolean `scra_eligible` flag declaring whether servicemember-protection rate relief applies, the OCC field `expected_member_version` per §2.8, and optionally an `end_date`, which must be on or after the `start_date` when set and stays null while the deployment is open-ended. Registration creates the order in `REGISTERED` and increments the member's `version` by 1. When the `start_date` is on or before the current logical-clock date, the order auto-activates to `ACTIVE` at creation; the same auto-activation happens later for still-`REGISTERED` orders when the clock advances past their start, per §2.5.

A member's `deployment_posture` is a second, independent state dimension alongside status, with values `NONE` and `DEPLOYED`. Posture flips from `NONE` to `DEPLOYED` whenever an order activates — provided the member's status is `ACTIVE` — and flips back to `NONE` when the last `ACTIVE` order completes or is cancelled, leaving no remaining `ACTIVE` order for the member. Every posture flip recomputes the member's `product_matrix_cache` (adding or removing the deployment-only facet group per §3.7) and recomputes the household aggregate when the member is linked.

Per member, the date intervals of non-cancelled orders must not overlap. Deployment intervals are treated as inclusive at both ends, so two orders where one ends on the very day another begins are in conflict, failing with `ERR_DEPLOYMENT_OVERLAP` (HTTP 409). An officer may adjust an order's `end_date` and `theater` while it is `REGISTERED` or `ACTIVE`; the adjustment revalidates the same interval rules. Completing an order — from either `REGISTERED` or `ACTIVE` to `COMPLETED` — requires an `end_date` to be present, failing with `ERR_DEPLOYMENT_END_DATE_REQUIRED` on an open-ended order, and requires that `end_date` to be on or before the logical-clock date, failing with `ERR_DEPLOYMENT_NOT_ENDED` when it lies in the future. Completion releases posture when no other `ACTIVE` order remains. A `REGISTERED` order may instead be moved to `CANCELLED`, the order's other terminal state; an `ACTIVE` order must be completed rather than cancelled, and attempting to cancel one is rejected with `ERR_INVALID_STATE`.

### 3.6. Servicemember Protection Claims

A member files a protection claim with a `claim_type` of `RATE_REDUCTION`, `CLAIM_DEFERRAL`, or `LEASE_TERMINATION`, an `obligation_label` identifying the underlying obligation (free text such as AUTO_LOAN_1 or HOMEOWNERS_PREM), and optionally a `deployment_order_id` tying the claim to a registered deployment — null when the claim predates any order registration. Rate-reduction claims additionally carry `base_rate_bps`, the pre-claim annual rate in basis points, and `monthly_interest_cents`, the monthly interest at that base rate. A new claim sits in `REQUESTED`, with `periods_granted`, `total_relief_cents`, `approval_effective_date`, and `approved_by_officer_id` all null.

A `VerificationOfficer` decides a `REQUESTED` claim with a `decision` of `APPROVE` or `DENY` and an optional `decision_note`. Denial needs nothing further. Approval enforces, in order: the segregation-of-duties rule that the approving officer differ from the claim's owning member (`ERR_SEGREGATION_OF_DUTIES`); for rate-reduction claims, that the referenced `deployment_order_id` resolves to an `ACTIVE` order whose `scra_eligible` flag is true (`ERR_SCRA_NOT_ELIGIBLE`); and that the computed relief actually yields at least one period of positive relief (`ERR_NO_RELIEF_AVAILABLE`, which also fires when the base rate sits at or below the statutory cap). The fiscal cap of §3.6.1 is evaluated after SCRA eligibility. Approval stamps `approval_effective_date` with the logical-clock date and records the officer as `approved_by_officer_id`. Approving a claim for an obligation that already has an `APPROVED` claim automatically moves that older claim to `SUPERSEDED` — the only exit from `APPROVED` — while the superseded claim keeps its historical `total_relief_cents` and the newer claim's relief is computed from its own `approval_effective_date` forward.

#### 3.6.1. Rate Relief Arithmetic and the Exposure Cap

Rate-reduction relief is computed per period and summed. The number of periods is the count of whole months from the `approval_effective_date` to the deployment's `end_date`, capped at 60; when the order is open-ended at approval time, the obligation-proration variant fixes the count at exactly 12 periods regardless of any `end_date` entered later. The statutory rate cap is 600 basis points: the capped rate is the lesser of `base_rate_bps` and 600. Each period's relief, in integer cents, is the `monthly_interest_cents` scaled by the fraction of the rate removed — that is, multiplied by the difference between `base_rate_bps` and the capped rate, divided by `base_rate_bps` — with each period's result floored to whole cents before the periods are summed into `total_relief_cents`. When the base rate is at or below 600 basis points, the per-period relief is zero and approval fails with `ERR_NO_RELIEF_AVAILABLE`. The floored per-period value populates `periods_granted` with the period count.

Approval also runs the relief-cap check, a validation-time fiscal guard with a pinned four-step evaluation order. First, the gross relief is the `total_relief_cents` proposed for the new claim. Second, the bank offset is the sum of `total_relief_cents` over the member's other claims currently in `APPROVED` status — `SUPERSEDED` and `DENIED` claims are excluded. Third, because offset netting is mandated, the net relief is the gross relief reduced by the lesser of the bank offset and the gross relief minus one, floored at zero. Fourth, the check itself: the net relief plus the sum of `total_relief_cents` across the member's `APPROVED` claims must not exceed the member's exposure cap, which is the sum of `exposure_cents` over the member's `OPEN` and `GRANDFATHERED` entitlements. A violation is rejected with `ERR_RELIEF_CAP_EXCEEDED`. When the member holds no `OPEN` or `GRANDFATHERED` entitlements at all, the cap does not apply — the relief is a statutory protection, not a product benefit.

### 3.7. The Product Catalog and the Availability Matrix

A `ProductAdministrator` authors the catalog. Each offering carries a unique `product_code` (free text such as CK_BASIC, AUTO_INS, or IRA_BROKERAGE), a `product_line` of `BANKING`, `INSURANCE`, or `INVESTMENT`, a display `product_name`, and the `allowed_categories` array naming the subset of the six eligibility categories permitted to hold it. Two boolean flags shape availability: `requires_active_status`, defaulting to true, restricts the product to members whose status is `ACTIVE`; `deployment_enhanced`, defaulting to false, grants the offering a deployment-only facet while the member is deployed. The system-managed `is_active_flag`, defaulting to true, marks retired offerings when set to false.

Every member carries a cached 24-facet availability matrix: four facet groups — `BANKING`, `INSURANCE`, `INVESTMENT`, and `DEPLOYMENT` — of six facets each. The matrix is recomputed on category assignment at approval, on every member status transition, on every posture transition, on every product-offering flag or category change, and lazily on read whenever the cache is stale. The rule: for each offering whose `is_active_flag` is true, the offering's base availability holds when its `allowed_categories` contains the member's `eligibility_category`; when the member's status is not `ACTIVE` and the offering's `requires_active_status` is true, base availability is forced off. A base-available offering turns all six facets of its `product_line` group to `AVAILABLE`. The `DEPLOYMENT` group's six facets are `AVAILABLE` only when there exists an active, base-available, `deployment_enhanced` offering and the member's `deployment_posture` is `DEPLOYED`. For a `SUSPENDED` member, the suspended variant applies: offerings requiring active status flip to unavailable even when the category is allowed, and the deployment group is always entirely unavailable. The `available_facet_count` is six times the number of fully available groups, and therefore is always one of 0, 6, 12, 18, or 24. The matrix response exposes the member's `member_id`, `eligibility_category`, `status`, `deployment_posture`, `available_facet_count`, and the per-group `facets` detail including per-offering base availability.

A member opens an entitlement by naming a `product_offering_id` and optionally an `exposure_cents` annualized premium, loan, or book-value figure that defaults to 0. The category gate enforces that the offering's `allowed_categories` contains the member's current `eligibility_category` and that the offering's `is_active_flag` is true; otherwise the open is rejected with `ERR_PRODUCT_CATEGORY_FORBIDDEN`. A successful open creates the entitlement in `OPEN` status, stamps `opened_at` from the logical clock, and leaves `closure_reason` null and `grandfathered` false. Retiring an offering — setting `is_active_flag` to false — closes every entitlement on it with `closure_reason` `GRANDFATHERED_RETIRE` and recomputes the affected members' matrices and household aggregates. Updating an offering's `allowed_categories` so that it no longer contains a holding member's category moves that member's `OPEN` entitlement to `GRANDFATHERED` with `grandfathered` true; grandfathered exposure continues to count toward survivor continuance. An `OPEN` or `GRANDFATHERED` entitlement may also be closed voluntarily by the holding member or a `BenefitsOfficer`, recording `closure_reason` `VOLUNTARY`; every close recomputes the household aggregate when the member is linked. `CLOSED` is terminal.

### 3.8. Eligibility Loss, Grandfathering, and Reinstatement

Eligibility is not irrevocable. A `VerificationOfficer` records an eligibility-loss event by supplying a `loss_type` and an optional `loss_note`. The `DOCUMENTATION_REVOKED` loss type moves an `ACTIVE` member to `SUSPENDED`: every `OPEN` entitlement transitions to `GRANDFATHERED` with `grandfathered` set true — documentation loss grandfathers the entire book, and entitlements already `GRANDFATHERED` stay so — while the member's matrix is recomputed under the suspended variant and the household aggregate is recomputed. The `FRAUD_CONFIRMED` loss type moves a `SUSPENDED` member to `REVOKED`, a terminal state: every `OPEN` and every `GRANDFATHERED` entitlement closes with `closure_reason` `MEMBER_LOSS`, ending grandfathering. Revocation cascades one generation down the lineage: every member whose `sponsor_member_id` is the revoked member and whose status is `ACTIVE` moves to `SUSPENDED`, with their product matrices and their households' aggregates recomputed alongside the revoked member's own.

Reinstatement from `SUSPENDED` back to `ACTIVE` requires restoration evidence: an evidence document on the member's case uploaded after the loss event. Without it the attempt fails with `ERR_REINSTATEMENT_EVIDENCE_REQUIRED`. Reinstatement recomputes the member's matrix and household aggregate; entitlements already `GRANDFATHERED` remain so — reinstatement restores status, not the original entitlement states.

### 3.9. Death Processing and Survivor Support

Only an `ACTIVE` member can be processed as deceased; a `SUSPENDED` member must be reinstated before death processing, and attempting otherwise fails with `ERR_INVALID_STATE`. A `BenefitsOfficer` marks the member deceased, optionally supplying a `date_of_death` and a `beneficiary_member_id`. The transition to `DECEASED` — a terminal state — recomputes the member's matrix with all facets unavailable and recomputes the household aggregate. It also creates a `SurvivorSupportCase` in `OPEN` status for the beneficiary: the supplied `beneficiary_member_id` when one is provided, else the surviving spouse member, else the earliest-created surviving child member by `created_at` ascending. When no surviving family member exists, no case is created.

Granting a survivor case requires the deceased member to be `DECEASED` and the beneficiary to be an `ACTIVE` member, failing with `ERR_BENEFICIARY_NOT_ACTIVE` otherwise. The grant computes the continuance window and amount by a waterfall. The exposure base is the sum of `exposure_cents` over the deceased member's entitlements in `OPEN` or `GRANDFATHERED` status — `CLOSED` entitlements are excluded. A deductible of 50000 cents is absorbed first, and only the overflow above it flows into the benefit: the covered amount is the exposure minus the deductible, floored at zero. For a beneficiary whose `claimed_relationship` is `SPOUSE` or `WIDOW_WIDOWER`, the member share rate is 0.20 over 3 months; for `CHILD`, `STEPCHILD`, or any other relationship — the lineal-descendant variant — the rate is 0.30 over 2 months, so identical exposure inputs yield a different amount over a shorter window. The covered amount is multiplied by the share rate, floored to whole cents, and then multiplied by the month count to produce `continuance_amount_cents`; `continuance_months` records the month count.

The grant cascade then transfers wealth and household. Every `GRANDFATHERED` entitlement of the deceased member whose offering permits the beneficiary's category is re-keyed to the `beneficiary_member_id` in an ownership transfer; the remaining entitlements close with `closure_reason` `MEMBER_LOSS`. The beneficiary's `household_id` is set to the deceased member's household when one is set, recorded on the case as `transfer_household_id`, and both the old and new household aggregates are recomputed. The case moves to `GRANTED`. A `BenefitsOfficer` later closes a `GRANTED` case by supplying a mandatory `resolution_note` — omitting it fails with `ERR_INVALID_REQUEST` — moving the case to `CLOSED`, its terminal state.

### 3.10. Households and Lineage Linkage

A household is created with a `household_name` display label and a `primary_member_id` naming the member whose lineage anchors it; the primary member is immutable after creation and is auto-linked at creation, with the household's `aggregate_product_count` computed immediately per §2.9. A household begins `ACTIVE`.

Linking a member into a household is a deliberate write carrying the `household_id` and the OCC field `expected_member_version` per §2.8; linking supersedes any prior linkage, increments the member's `version` by 1, and recomputes both the old and the new household's aggregate. Delinking removes the member from their household by nulling `household_id` and recomputes the abandoned household's aggregate.

Dissolving a household requires that no member with status `ACTIVE` or `SUSPENDED` is currently linked, failing with `ERR_HOUSEHOLD_NOT_EMPTY` otherwise. Dissolution moves the household to `DISSOLVED`, a terminal state, freezing `aggregate_product_count` at its last computed value.

### 3.11. Addresses and Duty-Station Changes

Members carry address intervals of three types — `DOMESTIC_RESIDENCE`, `MILITARY_APO_FPO_DPO`, and `OVERSEAS_FOREIGN` — each recording `line1`, `city`, `region_code` (a state code, a military AE/AP/AA region, or a foreign region label), `postal_code`, and `country_code` (the ISO country code, which is US for domestic and military-post addresses). Coverage runs from `effective_from` to an optional `effective_to`, which when set must be strictly later than `effective_from`; a null `effective_to` marks the interval as ongoing. The boolean `is_duty_station`, defaulting to false, marks a permanent-change-of-station posting.

Address intervals of the same `addr_type` for one member must not overlap. The intervals are half-open — the end instant is excluded — so two intervals that merely touch, one ending exactly when the next begins, are legal. A collision, or an `effective_to` at or before its `effective_from`, is rejected with `ERR_ADDRESS_OVERLAP` (HTTP 409). Intervals may be adjusted after the fact — typically to close `effective_to` on a duty-station change — and every adjustment revalidates the same interval rules.

Duty-station moves carry one further guard. When a new `is_duty_station` address has an `effective_from` earlier than the member's current open duty-station interval — a retroactive PCS — the request must close the previous duty interval within the same request set; otherwise it is rejected with `ERR_DUTY_STATION_CONFLICT` (HTTP 409).

## 4. Endpoint Definitions

Operations that create a new resource — an eligibility case, a service record, an evidence document, an address, a deployment order, a protection claim, a product offering, an entitlement, or a household — return `201 Created`. Operations that modify an existing resource, including all state transitions, links, delinks, decisions, and clock adjustments, return `200 OK`. All endpoints are mounted under the `/membership` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/membership/eligibility-cases` | Open an eligibility case in `INTAKE` | EligibilityApplicant |
| GET | `/membership/eligibility-cases` | List eligibility cases (filterable by status, basis type, sponsor, member) | EligibilityApplicant, VerificationOfficer, PlatformAdmin |
| GET | `/membership/eligibility-cases/{caseId}` | Fetch one eligibility case | EligibilityApplicant, VerificationOfficer, PlatformAdmin |
| POST | `/membership/eligibility-cases/{caseId}/service-records` | Attach a service record to an `INTAKE` or `MORE_INFO_REQUIRED` case | EligibilityApplicant |
| GET | `/membership/eligibility-cases/{caseId}/service-records` | List a case's service records | EligibilityApplicant, VerificationOfficer, PlatformAdmin |
| POST | `/membership/eligibility-cases/{caseId}/evidence` | Upload evidence to a case | EligibilityApplicant |
| GET | `/membership/eligibility-cases/{caseId}/evidence` | List a case's evidence documents | EligibilityApplicant, VerificationOfficer, PlatformAdmin |
| POST | `/membership/eligibility-cases/{caseId}/submit` | Submit or resubmit a case for verification | EligibilityApplicant |
| POST | `/membership/eligibility-cases/{caseId}/decide` | Officer decision: approve, deny, or request more info | VerificationOfficer |
| POST | `/membership/eligibility-cases/{caseId}/record-reconstruction` | Archives reconstruction decision for lost records | VerificationOfficer |
| GET | `/membership/service-records` | Filtered list of service records | VerificationOfficer, PlatformAdmin |
| GET | `/membership/service-records/{recordId}` | Fetch one service record | VerificationOfficer, PlatformAdmin |
| GET | `/membership/evidence` | Filtered list of evidence documents | EligibilityApplicant, VerificationOfficer, PlatformAdmin |
| GET | `/membership/evidence/{docId}` | Fetch one evidence document | EligibilityApplicant, VerificationOfficer, PlatformAdmin |
| GET | `/membership/members` | List members (filterable by status, category, household, sponsor) | Member, VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| GET | `/membership/members/{memberId}` | Fetch one member (ownership enforced for the Member role) | Member, VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| GET | `/membership/members/{memberId}/product-matrix` | Read the member's 24-facet product availability matrix | Member, VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| POST | `/membership/members/{memberId}/eligibility-loss` | Record an eligibility-loss event (suspend or revoke) | VerificationOfficer |
| POST | `/membership/members/{memberId}/reinstate` | Reinstate a suspended member | VerificationOfficer |
| POST | `/membership/members/{memberId}/deceased` | Mark an active member deceased and open survivor support | BenefitsOfficer |
| POST | `/membership/members/{memberId}/link-household` | Link a member into a household (OCC-guarded) | Member, VerificationOfficer |
| POST | `/membership/members/{memberId}/delink-household` | Remove a member from their household | Member, VerificationOfficer |
| POST | `/membership/members/{memberId}/addresses` | Record an address or duty-station interval | Member, VerificationOfficer |
| GET | `/membership/members/{memberId}/addresses` | List a member's address intervals | Member, VerificationOfficer, PlatformAdmin |
| GET | `/membership/addresses` | Filtered list of address assignments | VerificationOfficer, PlatformAdmin |
| GET | `/membership/addresses/{addressId}` | Fetch one address assignment | Member, VerificationOfficer, PlatformAdmin |
| PATCH | `/membership/addresses/{addressId}` | Adjust an address interval | Member, VerificationOfficer |
| POST | `/membership/members/{memberId}/deployment-orders` | Register a deployment order (OCC-guarded) | VerificationOfficer |
| GET | `/membership/members/{memberId}/deployment-orders` | List a member's deployment orders | Member, VerificationOfficer, PlatformAdmin |
| PATCH | `/membership/deployment-orders/{orderId}` | Enter or adjust end date and theater | VerificationOfficer |
| GET | `/membership/deployment-orders` | Filtered list of deployment orders | VerificationOfficer, PlatformAdmin |
| GET | `/membership/deployment-orders/{orderId}` | Fetch one deployment order | Member, VerificationOfficer, PlatformAdmin |
| POST | `/membership/deployment-orders/{orderId}/complete` | Complete an order, releasing posture when last active | VerificationOfficer |
| POST | `/membership/deployment-orders/{orderId}/cancel` | Cancel a registered order | VerificationOfficer |
| POST | `/membership/members/{memberId}/protection-claims` | File a servicemember-protection claim | Member |
| GET | `/membership/members/{memberId}/protection-claims` | List a member's protection claims | Member, VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| GET | `/membership/protection-claims` | Filtered list of protection claims | VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| GET | `/membership/protection-claims/{claimId}` | Fetch one protection claim | Member, VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| POST | `/membership/protection-claims/{claimId}/decide` | Approve or deny a requested claim | VerificationOfficer |
| POST | `/membership/product-offerings` | Create a product offering with its category gate | ProductAdministrator |
| GET | `/membership/product-offerings` | List product offerings | Member, VerificationOfficer, BenefitsOfficer, ProductAdministrator, PlatformAdmin |
| GET | `/membership/product-offerings/{offeringId}` | Fetch one product offering | Member, VerificationOfficer, BenefitsOfficer, ProductAdministrator, PlatformAdmin |
| PATCH | `/membership/product-offerings/{offeringId}` | Update category gates or flags, or retire the offering | ProductAdministrator |
| POST | `/membership/members/{memberId}/entitlements` | Open a product entitlement (category gate enforced) | Member, BenefitsOfficer |
| GET | `/membership/members/{memberId}/entitlements` | List a member's entitlements | Member, VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| GET | `/membership/entitlements` | Filtered list of entitlements | VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| GET | `/membership/entitlements/{entitlementId}` | Fetch one entitlement | Member, VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| POST | `/membership/members/{memberId}/entitlements/{entitlementId}/close` | Voluntarily close an open or grandfathered entitlement | Member, BenefitsOfficer |
| POST | `/membership/households` | Create a household anchored on a primary member | Member, VerificationOfficer |
| GET | `/membership/households` | List households | Member, VerificationOfficer, PlatformAdmin |
| GET | `/membership/households/{householdId}` | Fetch one household | Member, VerificationOfficer, PlatformAdmin |
| POST | `/membership/households/{householdId}/dissolve` | Dissolve an empty household | VerificationOfficer |
| GET | `/membership/members/{memberId}/survivor-cases` | List survivor support cases for a member | Member, VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| GET | `/membership/survivor-cases` | Filtered list of survivor support cases | VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| GET | `/membership/survivor-cases/{caseId}` | Fetch one survivor support case | VerificationOfficer, BenefitsOfficer, PlatformAdmin |
| POST | `/membership/survivor-cases/{caseId}/grant` | Grant survivor support with continuance and transfer cascades | BenefitsOfficer |
| POST | `/membership/survivor-cases/{caseId}/close` | Close a granted survivor case with a resolution note | BenefitsOfficer |
| POST | `/membership/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_EVIDENCE` | 409 |
| `ERR_DUPLICATE_ORDER` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ADDRESS_OVERLAP` | 409 |
| `ERR_DEPLOYMENT_OVERLAP` | 409 |
| `ERR_INVALID_REFERENCE` | 422 |
| `ERR_LINEAGE_DEPTH_EXCEEDED` | 422 |
| `ERR_LINEAGE_PROOF_INSUFFICIENT` | 422 |
| `ERR_ELIGIBILITY_DERIVATION_FAILED` | 422 |
| `ERR_PRODUCT_CATEGORY_FORBIDDEN` | 422 |
| `ERR_HOUSEHOLD_NOT_EMPTY` | 422 |
| `ERR_SCRA_NOT_ELIGIBLE` | 422 |
| `ERR_RELIEF_CAP_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SPONSOR_NOT_ACTIVE` | 422 |
| `ERR_BENEFICIARY_NOT_ACTIVE` | 422 |
| `ERR_SERVICE_RECORD_REQUIRED` | 422 |
| `ERR_EVIDENCE_REQUIRED` | 422 |
| `ERR_NO_NEW_EVIDENCE` | 422 |
| `ERR_SERVICE_RECORD_UNVERIFIED` | 422 |
| `ERR_DEPLOYMENT_NOT_ENDED` | 422 |
| `ERR_DEPLOYMENT_END_DATE_REQUIRED` | 422 |
| `ERR_NO_RELIEF_AVAILABLE` | 422 |
| `ERR_REINSTATEMENT_EVIDENCE_REQUIRED` | 422 |
| `ERR_DUTY_STATION_CONFLICT` | 409 |
