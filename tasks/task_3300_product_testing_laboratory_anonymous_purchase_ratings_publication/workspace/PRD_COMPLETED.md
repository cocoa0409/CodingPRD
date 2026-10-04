# Product Testing Lab Ratings API — Product Requirements Document

## 1. Introduction

Independent product testing only earns public trust when every step of the pipeline is insulated from manufacturer influence: the samples must be bought anonymously at retail, the laboratory work must follow a published, repeatable protocol, the member survey evidence must clear a declared sample-size bar, and the final ratings must be free of advertising money. This document specifies the API of a consumer product testing laboratory that operationalizes that discipline end to end — from category selection and program budgeting, through anonymous purchasing, lab measurement, member surveying, scoring, publication, safety escalation, and membership-funded access control.

The platform serves ten distinct roles with deliberately segregated duties: the person who proposes a test program may not approve it; the agent who places a purchase order may not verify its sourcing documentation; the editor who drafts a ratings publication may not approve or publish it. Ratings carry editorial designations driven by a pinned threshold order — safety always outranks score and price — and a `CRITICAL` hazard finding can cascade all the way to withdrawing an already-published rating and reverting its test program. Members fund the operation through subscriptions with a fourteen-day grace window, and the whole system runs on a test-driveable logical clock so that refresh urgency, embargo expiry, and subscription aging are all deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the actor and `X-User-Role` declaring the actor's role. A request missing either header, or declaring a role the system does not know, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The recognized role names, spelled exactly, are: `LabManager`, `EditorialDirector`, `MethodologyOfficer`, `PurchasingAgent`, `ComplianceOfficer`, `LabTechnician`, `SurveyDirector`, `ContentEditor`, `SafetyOfficer`, and `Member`.

For every role except `Member`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition writes an actor stamp — for example `proposed_by_user_id` and `approved_by_user_id` on a test program, `placed_by_user_id` and `verified_by_user_id` on a purchase order, or `recorded_by_user_id` on a measurement — but it does not compare the value to any entity's `id`. Segregation-of-duties checks compare these recorded actor stamps against each other, never against entity identifiers.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity. Ownership checks on any resource that references a member compare the resource's member field to `X-User-ID`: a member submitting a survey response must present `member_id` equal to the acting `X-User-ID`, subscription actions on a member record require the path `id` to equal the acting `X-User-ID` (or the actor must be a `LabManager`), and a member reading their own record likewise resolves identity through `X-User-ID`.

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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. List responses sort by `created_at` ascending. The `meta` block of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. All resources except `Measurement` additionally carry `updated_at` (same format, refreshed on every mutation) and `version` (an integer starting at 1, incremented by exactly one on every mutation of the resource, including mutations caused by cascade side effects). A `Measurement` is an append-only lab record: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, and no operation ever modifies a measurement after creation.

Time inside the system is governed by a logical clock, never the host wall clock. At server startup the current logical instant is exactly `2026-09-01T00:00:00Z`, and it advances only when a `LabManager` sets it through the test-driving capability, supplying the target instant as `to_iso8601`; the response echoes the new position as `current_utc`. Everywhere this document says "the clock" — embargo checks, survey windows, subscription aging, refresh urgency, `placed_at`, `published_at`, `received_at`, `submitted_at` — it means this logical clock. The server must never fall back to wall-clock time.

### 2.5. Validation Priority Order

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic:

1. Authentication — `X-User-Role` and `X-User-ID` present and the role declared; failure yields `ERR_UNAUTHENTICATED` (401).
2. Authorization — the declared role is permitted for the endpoint; failure yields `ERR_UNAUTHORIZED` (403).
3. Existence — path-templated resources exist, checked left to right along the URL; failure yields `ERR_NOT_FOUND` (404).
4. State — the target resource is in a valid from-state for the requested action and the action name itself is known; failure yields `ERR_INVALID_STATE` (409).
5. Sourcing integrity — `ERR_SOURCING_INTEGRITY` (422).
6. Segregation of duties — `ERR_SOD_VIOLATION` (422).
7. Safety gate — `ERR_SAFETY_GATE` (422).
8. Referential integrity — `ERR_REFERENTIAL_INTEGRITY` (422).
9. Protocol weights and live protocol-code uniqueness — `ERR_PROTOCOL_WEIGHTS` (422).
10. Temporal windows — `ERR_TEMPORAL_WINDOW` (422).
11. Survey sampling rules — `ERR_SAMPLE_SIZE_NOT_MET` (422).
12. Embargo — `ERR_EMBARGOED` (422).
13. Budget — `ERR_BUDGET_EXCEEDED` (422).
14. Marketing-use refusal — `ERR_MARKETING_USE_FORBIDDEN` (422).
15. Membership activity — `ERR_MEMBERSHIP_INACTIVE` (403).
16. Optimistic concurrency — `ERR_STALE_VERSION` (412).
17. Uniqueness — `ERR_DUPLICATE` (422).
18. Structural request validity — required fields present, well-typed, enum values valid, numeric ranges respected; failure yields `ERR_INVALID_REQUEST` (400).

Because the state check (priority 4) precedes every business check, an action attempted from the wrong state always surfaces `ERR_INVALID_STATE` even when a business rule would also reject it; conversely, a structurally malformed request that would also violate a business rule surfaces the business error first and `ERR_INVALID_REQUEST` only when all earlier checks pass.

### 2.6. Optimistic Concurrency Control

Three write operations participate in optimistic concurrency control, each naming a parent entity whose `version` the caller must have last observed:

- Protocol activation: the transitions call on a lab protocol with `action` set to `activate` must carry `expected_category_version` equal to the current `version` of the protocol's `ProductCategory`. If the category version has advanced — for example because a prior activation for the same category superseded the previously `ACTIVE` protocol and bumped the category — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The field is optional on other actions of the same endpoint but mandatory for `activate`.
- Publication approval: the transitions call on a rating publication with `action` set to `approve` must carry `expected_program_version` equal to the current `version` of the publication's `TestProgram`. An intervening mutation of the program makes the approver's readiness view stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Wave qualification: the transitions call on a survey wave with `action` set to `qualify` must carry `expected_wave_version` equal to the wave's current `version`. A late response exclusion recomputes `threshold_met` and bumps the wave version, so a qualifier acting on an older observation is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes an expected-version field.

### 2.7. Money, Precision, and Rounding

All monetary amounts are integer cents. Wherever a numeric result is rounded, the system rounds half-up to two decimal places, and multi-stage calculations round at every pinned stage rather than only at the end — the pinned rounding order for purchase-order tax is round per line first, then sum; the pinned order for laboratory scoring is per-metric means first, then the across-metric mean.

### 2.8. Independence and Marketing Refusal

The laboratory accepts no advertising and forbids the use of its ratings in marketing. Any read of the rating-publication collection or of a single rating publication that carries the header `X-Marketing-Use: true` is refused with `ERR_MARKETING_USE_FORBIDDEN` (422), regardless of the caller's role. Sourcing independence is likewise enforced: all test samples are procured under `sourcing_mode` `ANONYMOUS_RETAIL` — the only value that field can take — and purchase channels that amount to buying directly from the manufacturer are rejected (see §3.3).

## 3. Business Logic & Workflows

### 3.1. Categories, Refresh Cycles, and the Selection Score

A `LabManager` creates a `ProductCategory` by supplying its display `name` (unique across categories — a duplicate is rejected with `ERR_DUPLICATE`), the `refresh_cycle_months` between mandatory retest cycles (an integer of at least 1), the `market_share_pct` and `member_interest_pct` inputs (each a number from 0 to 100 inclusive). A category starts in `status` `ACTIVE`; it may later be `SUSPENDED`, and once `RETIRED` it is excluded from the periodic rescoring sweep entirely.

Each category carries a computed `selection_score` that ranks it for the next round of testing. The score blends three signals with fixed weights: forty percent of `market_share_pct`, thirty-five percent of `member_interest_pct`, and twenty-five percent of a refresh-urgency component, with the final figure rounded half-up to two decimal places. The urgency component measures how overdue the category is: take the number of whole months between `last_published_at` and the current clock — computed as the number of days between them divided by 30 and rounded down to a whole number — capped at 60 months; if the category has never published (`last_published_at` is null), the full 60-month cap applies. Urgency itself is then one hundred times those months divided by `refresh_cycle_months`, rounded half-up to two decimal places, and capped at 100.

`last_published_at` is computed: it is the logical-clock instant of the most recent `PUBLISHED` and non-`WITHDRAWN` rating publication across all programs of the category, or null when none exists. The selection score is recomputed on two kinds of events, which can legitimately disagree because they evaluate at different clock positions: the periodic ops-run checkpoint (§3.8) recomputes it for every category whose `status` is not `RETIRED` using the cycle-run clock, and publication or withdrawal of a rating recomputes it synchronously using the event-moment clock. The same category with the same inputs can therefore score differently between two clock positions.

### 3.2. Test Programs: Proposal, Approval, and the Program Pipeline

A test program begins when a `LabManager` proposes one for a category, supplying `category_id`, the `fiscal_year`, and the `budget_cents` allocated to it (at least 0). The referenced category must exist and be in `ACTIVE` status, otherwise the create is rejected with `ERR_REFERENTIAL_INTEGRITY`. The proposing actor's opaque identifier is stamped into `proposed_by_user_id`, and the program starts in `PROPOSED` with `committed_cents` at 0.

An `EditorialDirector` then approves the program, moving it `PROPOSED → APPROVED`. Segregation of duties applies at this seam: the approver's `X-User-ID` must differ from `proposed_by_user_id`, or the request is rejected with `ERR_SOD_VIOLATION`. On approval the approver's identifier is stamped into `approved_by_user_id`. Cancellation is available from either `PROPOSED` or `APPROVED` at the `EditorialDirector`'s hand, moving the program to its terminal `CANCELLED` state and cascading every `DRAFT` purchase order of the program to `CANCELLED` as well.

Once approved, the program pipeline is driven by the `LabManager` through four further moves. Starting sourcing (`APPROVED → SAMPLE_SOURCING`) requires at least one `TestSample` planned for the program and an `ACTIVE` laboratory protocol for the program's category; every `PLANNED` sample of the program cascades to `SOURCING`. Starting testing (`SAMPLE_SOURCING → TESTING`) requires that every sample of the program has `sourcing_complete` true and that no purchase order of the program remains in `DRAFT` or `PLACED`; every sample cascades to `IN_LAB`. Starting scoring (`TESTING → SCORING`) requires that every sample has `testing_complete` true, and it is at this moment that each sample's `lab_score` is computed from its recorded measurements (§3.5). Declaring readiness (`SCORING → READY_FOR_PUBLICATION`) is gated by safety: if any safety finding of the program is in `OPEN` or `ESCALATED` status with an `escalation_tier` of at least 2, the transition is rejected with `ERR_SAFETY_GATE`; otherwise every `IN_LAB` sample cascades to `SCORED`. Each of these gating preconditions of the program pipeline transitions — the at-least-one-sample and active-protocol requirements of start-sourcing, the sourcing-complete and no-open-order requirements of start-testing, and the testing-complete requirement of start-scoring — is evaluated as part of the state check of §2.5 (priority 4), so its failure surfaces `ERR_INVALID_STATE` (409); only the readiness safety gate raises `ERR_SAFETY_GATE`. Finally, when a rating publication of the program is published (§3.6), the program bubbles up from `READY_FOR_PUBLICATION` to `PUBLISHED` automatically, and if that publication is later withdrawn the program reverts from `PUBLISHED` back to `READY_FOR_PUBLICATION` — both cascades bump the program's `version`.

### 3.3. Anonymous Purchasing and the Budget Ledger

Samples may only be bought anonymously at retail. Every `TestSample` carries `sourcing_mode` fixed at `ANONYMOUS_RETAIL` — manufacturer-supplied units are structurally impossible. A `PurchasingAgent` creates a purchase order against a program by supplying `program_id`, a `buyer_alias` (an anonymous purchasing identity, never a manufacturer name), the `retailer_name` of the retail channel, a `receipt_doc_ref` referencing the sourcing documentation, a `shipping_cents` amount (at least 0), and a `lines` array with at least one line. Each line carries `sample_id`, `unit_price_cents` (at least 0), `qty` (at least 1), and `tax_rate_bp` in basis points from 0 to 20000. Every line's `sample_id` must reference a sample belonging to the same program, and the program must be in `SAMPLE_SOURCING` status at create; violations surface `ERR_REFERENTIAL_INTEGRITY`. A purchase order is immutable after creation — its line set is fixed and tax is computed once at create.

Sourcing integrity is policed at three moments: order creation, placement, and verification. The `retailer_name` must not name a manufacturer-direct channel — that is, it must neither end with the suffix `-direct` nor equal the brand manufacturer's name — and the `buyer_alias` must not equal a manufacturer name. For these checks, a manufacturer name is exactly the `model_label` of any `TestSample` known to the system — the model label is the system's only record of a brand manufacturer identity, so any retailer or buyer string equal to some sample's `model_label` is treated as manufacturer-direct and rejected. Violations are rejected with `ERR_SOURCING_INTEGRITY`.

The order's money fields are computed. The `subtotal_cents` is the sum over lines of `unit_price_cents` multiplied by `qty`. Tax is pinned to a per-line-then-sum order: for each line the server computes `line_tax_cents` as `unit_price_cents` times `qty` times `tax_rate_bp` divided by 10000, rounded half-up to whole cents per line, and `tax_cents` is the sum of those per-line figures. This matters: summing raw fractional tax across lines and rounding once would differ — three lines each with half a cent of raw tax yield 2 cents under the pinned rule but 1 cent under the rejected alternative. `total_cents` is then `subtotal_cents` plus `shipping_cents` plus `tax_cents`.

Placement moves the order `DRAFT → PLACED` and is the budget checkpoint: the order's `total_cents` must not exceed the program's remaining budget, defined as `budget_cents` minus `committed_cents`, or the request is rejected with `ERR_BUDGET_EXCEEDED`. On placement the logical clock is stamped into `placed_at`, the actor into `placed_by_user_id`, the order's `total_cents` is added to the program's `committed_cents`, and the program's `version` bumps. The program's `committed_cents` is the ledger sum of `total_cents` over the program's orders in `PLACED`, `RECEIVED`, or `VERIFIED` status; it stays in sync because cancellation compensates: cancelling a `PLACED` order subtracts its `total_cents` from `committed_cents` as a compensating ledger entry, while cancelling a `DRAFT` order touches nothing. Cancellation is allowed from `DRAFT` or `PLACED`, ending the order in `CANCELLED`.

Receipt moves the order `PLACED → RECEIVED`, at which point each line's `qty` is added to the referenced sample's `sourced_units` and the sample's `sourcing_complete` flag recomputes — it is true exactly when `sourced_units` is at least `required_units`. Samples are not promoted to `IN_LAB` here; that promotion is deferred to the program's start-testing transition. Verification moves the order `RECEIVED → VERIFIED` under a `ComplianceOfficer`'s hand and is the second segregated seam: `receipt_doc_ref` must be non-empty, the verifier's `X-User-ID` must differ from `placed_by_user_id` (`ERR_SOD_VIOLATION` otherwise), and the sourcing-integrity check on `retailer_name` is re-applied. The verifier is stamped into `verified_by_user_id`. `VERIFIED` and `CANCELLED` are the order's terminal states.

### 3.4. Laboratory Protocols

A `LabManager` drafts a `LabProtocol` for a category by supplying `category_id` — the category must exist, else the create is rejected with `ERR_REFERENTIAL_INTEGRITY` — a `protocol_code`, the `measurement_repeat_min` (at least 1 — the repeats required per unit per metric), and two scoring weights: `perf_weight_pct` and `reliability_weight_pct`, each an integer from 1 to 98 whose sum must not exceed 99, so that the computed `convenience_weight_pct` — one hundred minus the two supplied weights — is always at least 1. Violations of the weight arithmetic, of the minimum repeat count, or of `protocol_code` uniqueness within the category among protocols in `DRAFT`, `IN_REVIEW`, or `ACTIVE` status are rejected with `ERR_PROTOCOL_WEIGHTS`; the weight check is re-applied when a draft is submitted for review. A protocol starts in `DRAFT`.

Review is a dialogue between roles: the `LabManager` submits a `DRAFT` protocol into `IN_REVIEW`; a `MethodologyOfficer` may return it to `DRAFT`, or activate it. Activation (`IN_REVIEW → ACTIVE`) stamps `activated_at` with the clock, supersedes any other `ACTIVE` protocol of the same category (moving it to `SUPERSEDED`), bumps the category's `version`, and — because that category bump invalidates any other client holding the category's prior version — is guarded by `expected_category_version` as described in §2.6. Retirement is allowed from `DRAFT` or `ACTIVE`, but an `ACTIVE` protocol can be retired only when no program of its category is in `SAMPLE_SOURCING`, `TESTING`, or `SCORING`; `RETIRED` is terminal.

### 3.5. Test Samples and Laboratory Measurement

A `LabManager` plans a `TestSample` for a program by supplying `program_id`, the `model_label` of the product model under test, and `required_units` (at least 1). The program must be in `PROPOSED` or `APPROVED` status, otherwise the create is rejected with `ERR_REFERENTIAL_INTEGRITY`. The sample starts `PLANNED` and advances `PLANNED → SOURCING → IN_LAB → SCORED` purely by system cascade from the program's transitions, never by direct action: to `SOURCING` when the program starts sourcing, to `IN_LAB` when the program starts testing and the sample's `sourcing_complete` holds, and to `SCORED` when the program declares readiness and the sample's `testing_complete` holds.

While a sample is `IN_LAB`, a `LabTechnician` records measurements against it, each supplying `sample_id`, the `unit_index` (from 1 up to the sample's `required_units`), a `metric_code` such as `SUCTION_KPA`, and the raw `value_num`. Recording against a sample not in `IN_LAB` is rejected with `ERR_REFERENTIAL_INTEGRITY`. Each record stamps `recorded_at` from the clock and `recorded_by_user_id` from the actor. A sample's `tested_units` is the count of distinct unit indexes among 1 through `required_units` for which at least `measurement_repeat_min` measurements exist under the category's `ACTIVE` protocol, and `testing_complete` becomes true when `tested_units` reaches `required_units`. The measurements of a sample are readable as a reverse-reachable sub-resource of the sample.

Scoring is a two-stage mean, and the staging is pinned. When the program starts scoring, each sample's `lab_score` is computed as follows: first, for each distinct `metric_code`, average the `value_num` of all of the sample's measurements with that metric code across all unit indexes, rounding each per-metric mean half-up to two decimal places; second, average those per-metric means across the distinct metric codes, again rounding half-up to two decimal places. Because each metric weighs equally regardless of how many repeats it received, this two-stage result differs from a flat mean over all raw rows whenever repeat counts per metric are unequal — the flat mean is a rejected alternative, not an acceptable shortcut. Until the program reaches `SCORING`, a sample's `lab_score` is null.

### 3.6. Rating Publications, Designations, and Embargo

A `ContentEditor` creates a `RatingPublication` for a program by supplying `program_id` — the program must exist, else `ERR_REFERENTIAL_INTEGRITY` — an `embargo_until` instant, and an optional `version_note` (defaulting to an empty string). At most one publication per program may ever reach `PUBLISHED`. The publication starts in `DRAFT` with `rated_models` empty and `model_count` at 0.

The editor builds the publication's rated-model table one entry at a time through the add-rated-model action, supplying a `sample_id`. The sample must belong to the publication's program and be in `SCORED` status (`ERR_REFERENTIAL_INTEGRITY` otherwise). Each entry captures `sample_id`, the sample's `lab_score`, a `survey_score`, an `overall_score`, a `designation`, and a `price_cents`, all computed at add time:

- The protocol weights come from the publication's `protocol_id_snapshot` if one has been pinned, else from the category's currently `ACTIVE` protocol — call the performance weight `p` and the reliability weight `r`.
- The `survey_score` is the mean of `reliability_score` over the `COUNTED` responses of the pinned-or-available `QUALIFIED` survey wave whose `model_label` matches the sample's `model_label`, rounded half-up to two decimal places; when no such responses exist it is null.
- When `survey_score` is present, `overall_score` blends the two: the lab score weighted by `p` hundredths plus the survey score weighted by the remaining hundredths — that is, `r` plus the convenience weight (one hundred minus `p` minus `r`) hundredths — rounded half-up to two decimal places. When `survey_score` is null, the survey weight folds away entirely and `overall_score` equals the `lab_score` exactly — treating the missing survey as a zero score is a rejected alternative (with `p` at 60 and a lab score of 90 it would wrongly yield 54.00 instead of 90.00).
- The entry's `price_cents` is the median of `unit_price_cents` over the lines of the sample's purchase orders in `RECEIVED` or `VERIFIED` status; when an even number of such lines exists, the lower of the two middle values is taken, and when no such lines exist the price is null, which makes the `BEST_BUY` designation impossible for that entry.

The `designation` is then assigned by a threshold ladder evaluated in a pinned order, safety first:

1. If any safety finding of the program references the entry's sample and is in `OPEN` or `ESCALATED` status with `escalation_tier` at least 1, the designation is `NOT_RECOMMENDED` — regardless of score or price.
2. Otherwise, if `overall_score` is at least 75 and `price_cents` is at most 20000 cents, the designation is `BEST_BUY`.
3. Otherwise, if `overall_score` is at least 80, the designation is `RECOMMENDED`.
4. Otherwise, if `overall_score` is at least 50, the designation is `STANDARD`.
5. Otherwise the designation is `NOT_RECOMMENDED`.

All boundaries are inclusive. The safety gate is deliberately evaluated before the score and price tiers: a high-scoring, cheap model carrying an open tier-1 finding is `NOT_RECOMMENDED`, and evaluating score tiers first is a rejected alternative. Designations are re-evaluated under the same ladder when a safety escalation cascade touches an entry (§3.7).

Editorial flow proceeds by transition actions. Submission by the `ContentEditor` moves the publication from `DRAFT` (or from `REVISION_REQUESTED` on resubmission) to `UNDER_REVIEW`, and requires the program to be in `READY_FOR_PUBLICATION` and `model_count` to be at least 1. Approval by the `EditorialDirector` (`UNDER_REVIEW → APPROVED`) is guarded three ways: by `expected_program_version` as described in §2.6; by the safety gate, which rejects the approval with `ERR_SAFETY_GATE` if any finding of the program is `OPEN` or `ESCALATED` with `escalation_tier` equal to 3; and it is on approval that the publication pins its methodology — `protocol_id_snapshot` captures the category's `ACTIVE` protocol, and `survey_wave_id_snapshot` captures the latest `QUALIFIED` survey wave of the category, chosen by latest `field_end` with ties broken by latest `created_at`, or null when none exists. The program's `version` bumps on approval. Alternatively the director may send the publication back, `UNDER_REVIEW → REVISION_REQUESTED`.

Publication (`APPROVED → PUBLISHED`) is allowed only when the clock has reached `embargo_until` (before that instant the attempt is rejected with `ERR_EMBARGOED`), when no other publication of the same program is already `PUBLISHED` (`ERR_DUPLICATE` otherwise), when no `OPEN` or `ESCALATED` finding of the program has `escalation_tier` equal to 3 (`ERR_SAFETY_GATE` otherwise), and when the program is in `READY_FOR_PUBLICATION`. On publish the clock is stamped into `published_at`, the program bubbles up `READY_FOR_PUBLICATION → PUBLISHED`, the category's `last_published_at` is set to the publication instant, the category's `selection_score` is recomputed, and the `version` of publication, program, and category each increment.

Withdrawal moves a publication to `WITHDRAWN` from `DRAFT`, `UNDER_REVIEW`, `REVISION_REQUESTED`, or `PUBLISHED`. A manual withdrawal out of `PUBLISHED` additionally requires justification: either an `ESCALATED` tier-3 finding on the program, or a non-empty `version_note`. Withdrawing a `PUBLISHED` publication reverts the program `PUBLISHED → READY_FOR_PUBLICATION` and recomputes the category's `last_published_at` from the remaining `PUBLISHED` non-`WITHDRAWN` publications (null when none remain) together with its `selection_score`. Withdrawals from pre-publication states carry no such recompute.

Visibility for the `Member` role is narrow: members see only publications that are `PUBLISHED`, not `WITHDRAWN`, and whose `embargo_until` has been reached by the clock — a member read of a publication in any other status (including `WITHDRAWN`) is rejected with `ERR_NOT_FOUND` (404), as though the publication did not exist, while a member read of a `PUBLISHED` publication still under embargo is rejected with `ERR_EMBARGOED`, and member-only operations additionally require the acting member's own `status` to be `ACTIVE`, else `ERR_MEMBERSHIP_INACTIVE` (403).

### 3.7. Safety Findings and Escalation Cascades

A `SafetyOfficer` or a `LabTechnician` logs a `SafetyFinding` against a program by supplying `program_id`, `sample_id`, a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, a `description_text` narrative, and a `hazard_flag` (defaulting to false) marking an immediate hazard. The sample must belong to the named program (`ERR_REFERENTIAL_INTEGRITY` otherwise). The finding starts `OPEN`.

Two figures are computed when a finding is created and re-evaluated when it is escalated. `recalled_model_count` counts the rated-model entries across the program's non-`WITHDRAWN` publications whose sample's `model_label` matches the finding's sample's `model_label` and whose `designation` is `NOT_RECOMMENDED`. The `escalation_tier` then climbs a cumulative ladder: tier 0 is merely logged; a `MAJOR` or `CRITICAL` severity lifts the finding to tier 1 (manufacturer notice); a `CRITICAL` finding whose `recalled_model_count` is at least 2 lifts it to tier 2 (recall advocacy); and a `CRITICAL` finding with `hazard_flag` set lifts it to tier 3 (regulator communication). The rules are cumulative — a `CRITICAL` hazard finding with at least 2 recalled models is tier 3 — and the hazard flag alone never forces tier 3: a `MAJOR` hazard finding stays at tier 1, which is the pinned behavior (treating hazard alone as tier 3 is a rejected alternative that would wrongly trigger publication withdrawal).

Escalation moves an `OPEN` finding to `ESCALATED` and requires the computed `escalation_tier` to be at least 1 — a tier-0 finding cannot be escalated. The cascade depth depends on the tier. At tier 2 or higher, every rated-model entry in the program's non-`WITHDRAWN` publications whose sample's `model_label` matches the finding's sample's `model_label` flips its `designation` to `NOT_RECOMMENDED`. At tier 3 exactly, the cascade goes one level deeper: every `PUBLISHED` rating publication of the program is withdrawn, which in turn reverts the program from `PUBLISHED` to `READY_FOR_PUBLICATION` and recomputes the category's `last_published_at` and `selection_score` — a depth-3 cascade from escalate, through designation flip, to withdrawal.

Resolution moves an `ESCALATED` finding to `RESOLVED`, and requires either that the `escalation_tier` be at most 1, or that an `ACCEPTED` manufacturer response exists on the program's publication. Closure is the terminal move to `CLOSED`, available from `RESOLVED` always, or directly from `OPEN` when the `escalation_tier` is 0. The safety gate defined in §3.2 and §3.6 consults exactly these states: tier-2-and-above findings in `OPEN` or `ESCALATED` block the program's readiness transition, and tier-3 findings in those states block publication approval and publication itself.

### 3.8. Survey Waves and Member Responses

A `SurveyDirector` opens a `SurveyWave` for a category by supplying `category_id` — the category must exist, else `ERR_REFERENTIAL_INTEGRITY` — the `field_start` and `field_end` of the collection window, and `min_responses` (at least 1) as the sample-size threshold. The window must be sane — `field_end` strictly after `field_start` — or creation is rejected with `ERR_TEMPORAL_WINDOW`. The wave starts `OPEN`.

While a wave is `OPEN` and the clock sits within the window — at or after `field_start` and at or before `field_end`, with attempts outside the window rejected with `ERR_TEMPORAL_WINDOW` — a `Member` submits a response through the wave's transition action, supplying `member_id`, `model_label`, `reliability_score` (0 to 100), and `satisfaction_score` (0 to 100). The `member_id` must equal the acting `X-User-ID`, and the acting member's `status` must be `ACTIVE` (`ERR_MEMBERSHIP_INACTIVE` otherwise). At most one `COUNTED` response per member per wave is allowed; a second submission from the same member is rejected with `ERR_SAMPLE_SIZE_NOT_MET`. Accepted responses are appended to the wave's embedded `responses` array with a system-assigned `response_index` sequencing from 1, a system-stamped `submitted_at`, a system-stamped `submitted_by_user_id`, and `status` `COUNTED`. The `SurveyDirector` may exclude a response by its `response_index` (an index that does not exist yields `ERR_SAMPLE_SIZE_NOT_MET`), flipping its status to `EXCLUDED`. The wave's `response_count` counts only `COUNTED` responses, and `threshold_met` — true exactly when `response_count` is at least `min_responses` — recomputes on both submission and exclusion.

Closing a wave requires the clock to have reached `field_end` (a premature close yields `ERR_TEMPORAL_WINDOW`) and moves it `OPEN → CLOSED`. From `CLOSED` the director adjudicates: qualification moves the wave to `QUALIFIED` and requires `threshold_met` to be true (`ERR_SAMPLE_SIZE_NOT_MET` otherwise) plus the `expected_wave_version` OCC guard of §2.6; disqualification moves it to `DISQUALIFIED` and requires `threshold_met` to be false. Both are terminal. Only `QUALIFIED` waves feed the survey side of publication scoring (§3.6).

### 3.9. Membership, Subscriptions, and the Ops-Run Checkpoint

A member self-registers under the `Member` role by supplying a unique `email` — lowercased before comparison, with duplicates rejected as `ERR_DUPLICATE` — and a `full_name`. The `Member` record starts in `ACTIVE` status with an empty embedded `subscriptions` array.

The member manages their own subscriptions through transition actions on their own record — the path `id` must be the acting member's own `id`, and the acting member's `status` must be `ACTIVE`, otherwise `ERR_MEMBERSHIP_INACTIVE` (403) — while a `LabManager` may also read any member record. Adding a subscription supplies `plan_tier` (`DIGITAL` or `ALL_ACCESS`), `term_start`, and `term_end`; the term must have `term_end` strictly after `term_start` (`ERR_TEMPORAL_WINDOW` otherwise), and at most one subscription per member may be in `ACTIVE` or `GRACE` status at a time (`ERR_DUPLICATE` otherwise). The system assigns the subscription's `subscription_id` as a sequence string, computes `grace_until` as `term_end` plus 14 days, and starts the subscription `ACTIVE` with `renewal_count` 0. Renewal supplies `subscription_id` and a new `term_end`, recomputes `grace_until` from the new term end, and increments `renewal_count` by one; a successful renewal on a `GRACE` subscription cascades the member from `LAPSED` back to `ACTIVE`. Cancellation supplies `subscription_id` and moves the subscription to `CANCELLED`, cascading the member to the terminal `CANCELLED` status whether the member was `ACTIVE` or `LAPSED`.

Subscription aging runs on the ops-run checkpoint, a `LabManager`-only capability with no request body that performs three sweeps against the logical clock and reports back `categories_rescored`, `subscriptions_transitioned`, and `members_lapsed`:

1. Every `ProductCategory` whose `status` is not `RETIRED` has its `selection_score` recomputed per §3.1, using the cycle-run clock.
2. Every subscription in `ACTIVE` or `GRACE` is re-epoch'd against the clock with closed interval boundaries: at or before `term_end` the subscription stays `ACTIVE`; strictly after `term_end` but at or before `grace_until` it is `GRACE` — note the boundary instant `grace_until` itself is still `GRACE`, and only the first instant after it is `EXPIRED` (a half-open reading of the window would lapse the member one instant early and is a rejected alternative). Transitions are counted in `subscriptions_transitioned`.
3. Every member whose latest subscription has become `EXPIRED` cascades from `ACTIVE` to `LAPSED` — a depth-2 cascade from the cycle run through the subscription transition to the member — counted in `members_lapsed`.

### 3.10. Methodology Transparency and Manufacturer Response Handling

The laboratory answers manufacturer challenges on the record. Through the log-manufacturer-response transition action on a publication, a `ContentEditor` records an incoming manufacturer statement by supplying `manufacturer_name` and `body_text`; each entry is appended to the publication's embedded `manufacturer_responses` array with a system-assigned `response_index` sequencing from 1, a system-stamped `received_at` taken from the clock, and an initial status of `RECEIVED`. The editor then adjudicates each logged response in place through the accept-manufacturer-response or reject-manufacturer-response actions, referencing the entry by its `response_index` and moving its status to `ACCEPTED` or `REJECTED`. The publication's `manufacturer_response_text` always reflects the `body_text` of the latest `ACCEPTED` response, and is null when no accepted response exists. An accepted manufacturer response is more than a courtesy: it is the only way a safety finding whose `escalation_tier` exceeds 1 can move from `ESCALATED` to `RESOLVED` (§3.7).

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource in `data`; all other successful operations — reads, list queries, transitions, clock setting, and the cycle run — return HTTP 200. Where a transitions endpoint accepts fields that only some actions use, fields not required by the chosen action are omitted from the request.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock; startup default is exactly 2026-09-01T00:00:00Z with no wall-clock fallback | LabManager |
| POST | /_cycle/run | Ops-run checkpoint: rescore non-RETIRED categories, age subscriptions, lapse members | LabManager |
| POST | /product-categories | Create a category; selection_score computed with null last_published_at | LabManager |
| GET | /product-categories/{id} | Read a category | LabManager, EditorialDirector, MethodologyOfficer, SurveyDirector, SafetyOfficer, ContentEditor, ComplianceOfficer, PurchasingAgent, LabTechnician |
| POST | /test-programs | Propose a program; proposer stamped | LabManager |
| GET | /test-programs | List programs; optional `category_id`, `status` filters | LabManager, EditorialDirector, MethodologyOfficer, SurveyDirector, SafetyOfficer, ContentEditor, ComplianceOfficer, PurchasingAgent, LabTechnician |
| GET | /test-programs/{id} | Read a program | LabManager, EditorialDirector, MethodologyOfficer, SurveyDirector, SafetyOfficer, ContentEditor, ComplianceOfficer, PurchasingAgent, LabTechnician |
| POST | /test-programs/{id}/transitions | Program actions: approve, start_sourcing, start_testing, start_scoring, ready, cancel | LabManager, EditorialDirector |
| POST | /lab-protocols | Create a DRAFT protocol; convenience weight computed | LabManager |
| GET | /lab-protocols | List protocols; optional `category_id`, `status` filters | LabManager, EditorialDirector, MethodologyOfficer, LabTechnician, ContentEditor |
| GET | /lab-protocols/{id} | Read a protocol | LabManager, EditorialDirector, MethodologyOfficer, LabTechnician, ContentEditor |
| POST | /lab-protocols/{id}/transitions | Protocol actions: submit_review, return_draft, activate (OCC), retire | LabManager, MethodologyOfficer |
| POST | /test-samples | Plan a sample; program must be PROPOSED or APPROVED | LabManager |
| GET | /test-samples | List samples; optional `program_id`, `status` filters | LabManager, LabTechnician, PurchasingAgent, ComplianceOfficer, ContentEditor, SafetyOfficer |
| GET | /test-samples/{id} | Read a sample | LabManager, LabTechnician, PurchasingAgent, ComplianceOfficer, ContentEditor, SafetyOfficer |
| GET | /test-samples/{id}/measurements | List a sample's measurements | LabTechnician, LabManager, MethodologyOfficer |
| POST | /purchase-orders | Create a DRAFT purchase order with embedded lines; tax computed | PurchasingAgent |
| GET | /purchase-orders | List purchase orders; optional `program_id`, `status` filters | PurchasingAgent, ComplianceOfficer, LabManager |
| GET | /purchase-orders/{id} | Read a purchase order | PurchasingAgent, ComplianceOfficer, LabManager |
| POST | /purchase-orders/{id}/transitions | Order actions: place, receive, verify, cancel | PurchasingAgent, ComplianceOfficer |
| POST | /measurements | Record a measurement for an IN_LAB sample | LabTechnician |
| POST | /survey-waves | Open a survey wave | SurveyDirector |
| GET | /survey-waves | List waves; optional `category_id`, `status` filters | SurveyDirector, LabManager, ContentEditor, EditorialDirector |
| GET | /survey-waves/{id} | Read a wave including embedded responses | SurveyDirector, LabManager, ContentEditor, EditorialDirector |
| POST | /survey-waves/{id}/transitions | Wave actions: submit_response, exclude_response, close, qualify (OCC), disqualify | SurveyDirector, Member |
| POST | /rating-publications | Create a DRAFT publication | ContentEditor |
| GET | /rating-publications | List publications; Member sees only PUBLISHED non-embargoed non-WITHDRAWN; optional `program_id`, `status` filters | ContentEditor, EditorialDirector, LabManager, SafetyOfficer, Member |
| GET | /rating-publications/{id} | Read a publication; Member gated by status, embargo, membership | ContentEditor, EditorialDirector, LabManager, SafetyOfficer, Member |
| POST | /rating-publications/{id}/transitions | Publication actions: add_rated_model, submit, approve (OCC), request_revision, publish, withdraw, log_manufacturer_response, accept_manufacturer_response, reject_manufacturer_response | ContentEditor, EditorialDirector |
| POST | /safety-findings | Log a finding; escalation tier computed | SafetyOfficer, LabTechnician |
| GET | /safety-findings | List findings; optional `program_id`, `sample_id`, `status`, `severity` filters | SafetyOfficer, EditorialDirector, LabManager, ContentEditor |
| GET | /safety-findings/{id} | Read a finding | SafetyOfficer, EditorialDirector, LabManager, ContentEditor |
| POST | /safety-findings/{id}/transitions | Finding actions: escalate, resolve, close | SafetyOfficer |
| POST | /members | Register a member | Member |
| GET | /members/{id} | Read a member record (self, or LabManager) | Member, LabManager |
| POST | /members/{id}/transitions | Member actions: add_subscription, renew, cancel | Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SOURCING_INTEGRITY | 422 |
| ERR_SOD_VIOLATION | 422 |
| ERR_SAFETY_GATE | 422 |
| ERR_REFERENTIAL_INTEGRITY | 422 |
| ERR_PROTOCOL_WEIGHTS | 422 |
| ERR_TEMPORAL_WINDOW | 422 |
| ERR_SAMPLE_SIZE_NOT_MET | 422 |
| ERR_EMBARGOED | 422 |
| ERR_BUDGET_EXCEEDED | 422 |
| ERR_MARKETING_USE_FORBIDDEN | 422 |
| ERR_MEMBERSHIP_INACTIVE | 403 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE | 422 |
| ERR_INVALID_REQUEST | 400 |
