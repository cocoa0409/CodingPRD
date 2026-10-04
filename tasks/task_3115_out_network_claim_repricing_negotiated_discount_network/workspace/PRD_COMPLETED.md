# Oon Claim Repricing API — Product Requirements Document

## 1. Introduction

Payers sitting on out-of-network medical claims face a fragmented pricing landscape: contracted discount networks, Medicare-referenced fee schedules, usual-and-customary benchmarks, federal no-surprises dispute processes, and one-off single-claim negotiations all coexist. The platform described here is a MultiPlan-style repricing service that takes payer-side claim feeds, applies the repricing methodology the payer has configured for each claim type and network status, and produces a defensible, auditable repriced allowed amount — while preserving provider rights to negotiate, appeal, and invoke independent dispute resolution.

The system serves several cooperating parties. Payer operations staff configure repricing policies and ingest claims; network administrators maintain the contracted provider network and the underlying rate tables; payer and provider representatives run bilateral negotiations on individual out-of-network claims; an independent dispute resolution entity renders baseball-style decisions under the federal no-surprises process; and feed operators shepherd bulk claim data through turnaround service levels. Revenue for the repricing vendor accrues as a percentage-of-savings fee, invoiced against finalized claims and capped per claim, with optional client-facing transparency reporting.

Every repricing decision is frozen into an append-only determination record carrying a full input snapshot and computation trace, so a regulator, a provider, or a court can reconstruct exactly which rates were read and how the allowed amount was derived. Determinations are never edited in place: appeals, settlements, negotiation agreements, and dispute decisions each append a new determination that supersedes the prior one, keeping the chain intact.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. When either header is missing, or when the value of `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is recognized but not permitted for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles are exactly: `OpsAdmin`, `PayerAdmin`, `PayerRep`, `ProviderRep`, `NetworkAdmin`, `FeedOperator`, and `IdrEntity`.

Identity binding differs by role and is conventional rather than enforced. When `X-User-Role` is `PayerAdmin`, `X-User-ID` denotes the `id` of the acting `PayerClient`; when it is `PayerRep`, `X-User-ID` likewise denotes the acting `PayerClient`'s `id`; when it is `ProviderRep`, `X-User-ID` denotes the acting `Provider`'s `id`. For `OpsAdmin`, `NetworkAdmin`, `FeedOperator`, and `IdrEntity`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server authenticates the role and enforces only the per-endpoint role membership of §4: it does not compare `X-User-ID` against any resource's `payer_client_id` or `provider_id`, so a caller in a permitted role may act on resources naming any payer or provider.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, is never below 1, and is never above 100. The `offset` parameter defaults to 0 and is never negative. Responses include `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope so the caller can page deterministically. List endpoints sort by `created_at` ascending unless otherwise specified, and ties between same-`created_at` entries are broken by insertion order so the earlier-created entity comes first; the same ordering governs every place the specification refers to a claim's first-created line, such as the primary line used by reference-based pricing and the qualifying payment amount.

### 2.4. Common Resource Properties

Every resource exposes an `id` field carrying a server-minted UUID with no type prefix. All timestamp fields (`created_at`, `updated_at`, and any domain-specific timestamps such as `received_at`, `submitted_at`, `payer_signed_at`, `provider_signed_at`, `initiated_at`, `expires_at`, `appeal_window_deadline`, `sla_due_at`, `processed_at`) are ISO 8601 UTC strings with three fractional digits. All entities except `MedicareFeeScheduleEntry` and `UsualCustomaryRate` carry `created_at`, `updated_at`, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that resource, including system-driven cascades that touch the entity. `MedicareFeeScheduleEntry` and `UsualCustomaryRate` are exception rows: they carry only `id` and `created_at` — `updated_at` and `version` are absent from both entities.

### 2.5. The Logical Clock

Time in this system is not wall-clock time. A logical clock governs every timestamp the server writes, and an administrative capability advances the clock to a supplied `current_utc` instant. Before the clock has ever been set, it reads exactly `2026-09-01T00:00:00Z` — the server never falls back to the host's wall-clock time. Advancing the clock has a side effect on open negotiations: any `OpenNegotiation` whose `expires_at` has been reached transitions from `ACTIVE` to `EXPIRED` and bumps its `version`. The clock endpoint's response data is an object carrying the newly set `current_utc`.

### 2.6. Precision, Rounding, and Per-Line Order of Operations

All money is stored as integer cents. Whenever a repricing, fee, or benchmark computation produces a fractional cent, it is rounded half-up to a whole cent. The rounding order for repricing is pinned: each claim line's allowed amount is rounded half-up to whole cents first, and only then are the per-line allowed amounts summed into the claim-level `allowed_amount_cents`. This ordering is the `PER_LINE_THEN_SUM` value of the `rounding_order` policy field, which is fixed at that value across the system; the alternative of summing raw values and rounding once at the end is explicitly not used. Fee computation on invoices also rounds per claim before summing across claims. Median benchmarks (such as the qualifying payment amount) operate over integer cent values and need no rounding.

### 2.7. Optimistic Concurrency Control

Two write operations are protected against stale-version writes:

- Repricing a claim — the request body may carry `expected_claim_version`, holding the caller's last observed `version` of the target `Claim`. When the field is present it must be an integer — a non-integer value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and if it does not equal the claim's current `version` (for example because another writer added a claim line that legitimately changed the billed amount the repricing is based on), the reprice is rejected with `ERR_STALE_VERSION` (HTTP 412). When the field is omitted, no version comparison is performed.
- Placing an offer on a negotiation case — the request body may carry `expected_case_version`, holding the caller's last observed `version` of the target `NegotiationCase`. When present it must be an integer (else `ERR_INVALID_REQUEST`, HTTP 400), and a value not equal to the case's current `version` (for example because the provider countered and changed the offer currently on the table) is rejected with `ERR_STALE_VERSION` (HTTP 412). When the field is omitted, no version comparison is performed.

No other endpoint takes a version field. Endpoints not listed here must not require or consume `expected_*_version` inputs.

### 2.8. Rate Inputs as Defensible Snapshots

Every repricing decision freezes its inputs. The `RepricingDetermination` created at pricing time carries an `input_snapshot` (a frozen JSON object naming every rate input used — fee schedule row ids, UCR row ids, agreement discount, policy parameters) and a `computation_trace` (an ordered list of computation steps with intermediate values). Both are written exactly once at determination creation and are immutable thereafter. A `defensibility_notes` free-text field may be supplied at repricing time for any methodology and is recorded verbatim on the determination; it is optional for every methodology, including `REFERENCE_BASED`.

### 2.9. The Append-Only Determination Chain

A `RepricingDetermination` is born `ACTIVE` and may be superseded exactly once, after which its status is `SUPERSEDED`. Each repricing event — an appeal resolved in the provider's favor, an executed settlement, an open-negotiation agreement, or an IDR decision — creates a new `ACTIVE` determination whose `supersedes_determination_id` points at the previously active determination, and the prior determination transitions to `SUPERSEDED`. The first determination of a claim carries `supersedes_determination_id` equal to null. Determinations created through negotiation carry `methodology` `NEGOTIATED` with `policy_id` null; determinations created through the contracted-network path carry `agreement_id` referencing the applied `NetworkAgreement`, with `agreement_id` null on other paths.

### 2.10. Validation Ordering

When a request would trip multiple validation rules, the checks resolve in a fixed priority order so the surfaced error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then role authorization (`ERR_FORBIDDEN_ROLE`), then path-id existence checked left-to-right (`ERR_NOT_FOUND`). Only after those pass do business rules fire: suspended-payer checks (`ERR_PAYER_SUSPENDED`), generic state-transition validity (`ERR_INVALID_STATE`), NSA methodology conflict (`ERR_NSA_METHODOLOGY_CONFLICT`), temporal window rules (`ERR_OPEN_NEGOTIATION_ACTIVE`, `ERR_APPEAL_WINDOW_CLOSED`), rate-input existence (`ERR_RATE_INPUT_MISSING`, `ERR_NO_CONTRACTED_AGREEMENT`), repricing-policy selection (`ERR_NO_REPRICING_POLICY`, `ERR_NEGOTIATION_REQUIRED`, `ERR_CLAIM_HAS_NO_LINES`), offer/counter bounds (`ERR_COUNTER_BELOW_OFFER`, `ERR_OFFER_OUT_OF_RANGE`), fee-invoice fiscal rules (`ERR_CLAIM_NOT_FINALIZED`, `ERR_CLAIM_ALREADY_INVOICED`), IDR amount matching (`ERR_IDR_AMOUNT_MISMATCH`), uniqueness rules (`ERR_DUPLICATE_CLAIM_REF`, `ERR_DUPLICATE_NPI`), agreement-interval overlap (`ERR_AGREEMENT_OVERLAP`), transparency gating (`ERR_TRANSPARENCY_NOT_ENABLED`), and finally optimistic-concurrency checks (`ERR_STALE_VERSION`). Malformed request bodies — missing required fields, wrong types, non-positive amounts, or `quantity_units` below 1 — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Where a later section names a check "first" within a single endpoint's validation sequence — for example the §3.4 statement that a claim must have at least one non-`VOID` line before any other reprice check — that sequencing applies among requests whose path state permits the operation; for a request whose claim or resource is in a status where the operation is never defined, the endpoint's generic state gate still applies under this section's global priority, and either `ERR_INVALID_STATE` or the section-specific error satisfies the contract.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Payer and Configuring Repricing Policies

An `OpsAdmin` onboards a payer by supplying the payer's organization name as `payer_name`, the default percent-of-savings fee rate `fee_percent` (for example 0.25), a per-claim fee ceiling `fee_cap_cents_per_claim` in cents, an optional `minimum_invoice_cents` floor that defaults to 0 (fee invoices whose gross fees fall strictly below the floor are still issued; the floor gates nothing when it is 0), and an optional `transparency_reporting_enabled` flag that defaults to false. A newly created `PayerClient` is `ACTIVE`.

Once a payer exists, a `PayerAdmin` acting for that payer configures `RepricingPolicy` rows. Each policy names its owning payer via `payer_client_id` — which must reference an existing `PayerClient`, else `ERR_NOT_FOUND` (HTTP 404) — picks a `claim_type` from `PROFESSIONAL`, `FACILITY`, `ANCILLARY`, or `EMERGENCY`, picks a `network_status` from `IN_NETWORK`, `OUT_OF_NETWORK`, or `EMERGENCY_OON`, and selects a `methodology` from `CONTRACTED_NETWORK`, `REFERENCE_BASED`, `PERCENT_OF_MEDICARE`, `UCR`, or `NEGOTIATION_REQUIRED`. Methodology-specific parameters are carried on the same policy row: `percent_of_medicare` (a multiplier over the Medicare schedule, e.g. 1.50) for `PERCENT_OF_MEDICARE`, `rbp_markup_percent` (markup over the benchmark gap, e.g. 1.20) for `REFERENCE_BASED`, and `ucr_percentile` (either 50 or 80) for `UCR`; each may be omitted and is null when not supplied. A policy's `priority` is a required integer selector rank — lower wins — and ties are broken by the policy's `created_at` ascending, so the earliest-created policy at the lowest priority value is the one selected. New policies are `ACTIVE`; a `PayerAdmin` may retire one, which flips its status to `RETIRED` and bumps its `version`. A payer's repricing policies may be listed with optional `payer_client_id`, `methodology`, and `status` filters, plus `limit` and `offset`.

A payer that misbehaves can be put on ice: suspending a `PayerClient` flips its status to `SUSPENDED`, and reinstating flips it back to `ACTIVE`; both operations bump the payer's `version`. While a payer is `SUSPENDED`, claim ingest, claim-line addition, and repricing for that payer are all rejected with `ERR_PAYER_SUSPENDED` (HTTP 409).

### 3.2. Building the Contracted Network and the Rate Tables

A `NetworkAdmin` registers providers by supplying `npi` (the National Provider Identifier, unique across the platform — registering a provider whose `npi` is already on file is rejected with `ERR_DUPLICATE_NPI`, HTTP 409), the provider's `legal_name`, and the tax identifier `tin`. Providers may be fetched individually or listed with `limit` and `offset`.

Against each provider the `NetworkAdmin` establishes `NetworkAgreement` rows carrying a `network_name`, the contracted `provider_id`, a `discount_percent` expressed as a fraction off billed charges (for example 0.40 meaning forty percent off), and an effective interval bracketed by `effective_start` (inclusive) and `effective_end` (required to be strictly after `effective_start`, else `ERR_INVALID_REQUEST` (HTTP 400); the interval is half-open — a `service_date` is covered when `effective_start` ≤ `service_date` < `effective_end` — and overlap detection likewise treats the interval as half-open at the end). Contracted agreements always prohibit balance billing — `balance_billing_prohibited` is true for every contracted agreement — so patient responsibility is capped at in-network cost share. Two agreements for the same provider whose intervals overlap are forbidden among `ACTIVE` or `SUSPENDED` rows; a creation that would overlap is rejected with `ERR_AGREEMENT_OVERLAP` (HTTP 409). Agreements are born `ACTIVE`, may be suspended to `SUSPENDED`, reinstated from `SUSPENDED` back to `ACTIVE`, and terminated from either `ACTIVE` or `SUSPENDED` to `TERMINATED`; each transition bumps the agreement's `version`. Agreements may be listed filtered by `provider_id` or `status`.

Rate tables are loaded by the `NetworkAdmin` as well. A `MedicareFeeScheduleEntry` row carries `procedure_code` (a CPT/HCPCS code), `region_code` (a pricing locality), `base_rate_cents` (the Medicare base rate per unit in cents), a `geographic_adjustment_factor` (a GPCI-style multiplier applied to the base rate), and an `effective_year`. A `UsualCustomaryRate` row carries `procedure_code`, `region_code`, `percentile_50_cents`, and `percentile_80_cents` — the 80th-percentile figure doubles as the defensibility benchmark used by reference-based pricing. Both rate tables can be listed filtered by `procedure_code` or `region_code`. Neither table row carries `updated_at` or `version`; they are immutable reference data once loaded.

### 3.3. Claim Intake, Line Assembly, and Billed-Amount Recomputation

A `PayerRep` ingests a claim by supplying `payer_client_id`, `provider_id`, an `external_claim_ref` that is unique among that payer's claims (a duplicate surfaces `ERR_DUPLICATE_CLAIM_REF`, HTTP 409), a `claim_type`, a `network_status`, the `service_date` (which later selects the covering `NetworkAgreement` by its effective interval), the member cost-share `patient_responsibility_cents`, and an optional `nsa_flag` defaulting to false. Both `payer_client_id` and `provider_id` must reference existing entities, else `ERR_NOT_FOUND` (HTTP 404). A newly ingested claim is in `RECEIVED` status with `billed_amount_cents` equal to 0, and `methodology_used`, `allowed_amount_cents`, `payer_liability_cents`, `savings_cents`, and `rbp_amount_cents` are all null.

Lines are then added to the claim, one call per line. Lines may be added only while the claim is in `RECEIVED` or `PENDING_LINES`; any other claim status is rejected with `ERR_INVALID_STATE` (HTTP 409). Each `ClaimLine` carries `claim_id`, a priced `procedure_code`, a `quantity_units` of at least 1, a `unit_charge_cents` greater than 0, and a `region_code`. The first line added moves the claim from `RECEIVED` to `PENDING_LINES`; subsequent lines keep it in `PENDING_LINES`. Every line addition recomputes the claim's `billed_amount_cents` as the sum over all non-`VOID` lines of each line's `unit_charge_cents` multiplied by its `quantity_units`, and bumps the claim's `version`. New lines are `PENDING`. Lines may be listed under their claim with `limit` and `offset`. Claims themselves may be fetched, or listed with `payer_client_id`, `provider_id`, `status`, or `network_status` filters plus pagination.

### 3.4. Repricing a Claim Under the Selected Policy

Repricing is the heart of the platform. When a `PayerRep` asks to reprice a claim in `PENDING_LINES`, the request must carry `expected_claim_version` (see §2.7) and may carry `defensibility_notes`. The selection and validation sequence runs in a defined order. First, the claim must have at least one non-`VOID` line, else `ERR_CLAIM_HAS_NO_LINES` (HTTP 422). Second, the payer must be `ACTIVE`, else `ERR_PAYER_SUSPENDED`. Third, when the claim's `network_status` is `IN_NETWORK`, an `ACTIVE` `NetworkAgreement` covering the claim's `provider_id` and `service_date` must exist — absence yields `ERR_NO_CONTRACTED_AGREEMENT` (HTTP 422), and in-network claims price directly off that agreement rather than off a policy. Fourth, when the claim's `nsa_flag` is true and the selected policy's methodology is `NEGOTIATION_REQUIRED`, the reprice is rejected with `ERR_NSA_METHODOLOGY_CONFLICT` (HTTP 422) — NSA-protected claims route through the federal open negotiation process instead of being force-priced. Because the NSA conflict is defined relative to the selected policy, for out-of-network claims the policy selection of the fifth step necessarily executes first: an out-of-network claim with an empty policy candidate set surfaces `ERR_NO_REPRICING_POLICY` even when `nsa_flag` is true, and `ERR_NSA_METHODOLOGY_CONFLICT` applies only once a policy has been selected. In-network claims never consult a policy — they price directly off the covering agreement — so neither the NSA conflict check nor the `NEGOTIATION_REQUIRED` check applies to them. Fifth, for out-of-network claims, exactly one `ACTIVE` `RepricingPolicy` must be selectable: candidates are filtered by the claim's `payer_client_id`, `claim_type`, and `network_status`, ranked by `priority` ascending with `created_at` ascending as tie-breaker; an empty candidate set is rejected with `ERR_NO_REPRICING_POLICY` (HTTP 422). Sixth, if the selected policy's methodology is `NEGOTIATION_REQUIRED`, direct repricing is forbidden and the request is rejected with `ERR_NEGOTIATION_REQUIRED` (HTTP 422). Seventh, the rate inputs the methodology needs must exist: a `MedicareFeeScheduleEntry` matching each priced line's `procedure_code` and `region_code` for `PERCENT_OF_MEDICARE`, a `UsualCustomaryRate` row for `REFERENCE_BASED` or `UCR`, and the covering `NetworkAgreement` whenever the applied methodology is `CONTRACTED_NETWORK` — for an in-network claim that agreement is the one located in the third step, and for an out-of-network claim whose selected policy's methodology is `CONTRACTED_NETWORK` it is the `ACTIVE` `NetworkAgreement` covering the claim's `provider_id` and `service_date` — a missing row yields `ERR_RATE_INPUT_MISSING` (HTTP 422).

The per-line allowed amount is computed by methodology. Each line's gross is its `unit_charge_cents` multiplied by its `quantity_units`. Under `CONTRACTED_NETWORK`, the line's allowed amount is the gross multiplied by one minus the agreement's `discount_percent`, rounded half-up to whole cents. Under `PERCENT_OF_MEDICARE`, a schedule base is first computed as the fee schedule entry's `base_rate_cents` multiplied by its `geographic_adjustment_factor` and by the line's `quantity_units`, rounded half-up; the line's allowed amount is then that base multiplied by the policy's `percent_of_medicare`, again rounded half-up. Under `UCR`, the per-line benchmark is the UCR row's `percentile_80_cents` when the policy's `ucr_percentile` is 80, or its `percentile_50_cents` when the percentile is 50, multiplied by the line's `quantity_units`; the line's allowed amount is the lesser of the line's gross and that benchmark. Under `REFERENCE_BASED`, the per-line benchmark always uses the 80th-percentile UCR figure multiplied by the line's `quantity_units`, and the line's allowed amount is the lesser of the line's gross and the benchmark multiplied by the policy's `rbp_markup_percent` rounded half-up. Per §2.6, every per-line amount is rounded half-up before the line amounts are summed. Note that the same claim priced under `CONTRACTED_NETWORK` and under `PERCENT_OF_MEDICARE` will generally produce different allowed amounts, because the former's baseline is billed charges and the latter's baseline is the Medicare schedule.

When the selected methodology is `REFERENCE_BASED`, the claim also receives a `rbp_amount_cents` value. The evaluation order is pinned: `allowed_amount_cents` is fully computed first, then `rbp_amount_cents` reads it. The reference benchmark is the 80th-percentile UCR figure for the claim's primary (first-created) line's `procedure_code` and `region_code`, multiplied by that primary line's `quantity_units`. The `rbp_amount_cents` value is the lesser of the claim's `billed_amount_cents` and the claim's `allowed_amount_cents` plus the policy's `rbp_markup_percent` multiplied by the gap between the benchmark and the allowed amount — the gap taken as zero when the benchmark does not exceed the allowed amount — with the markup-over-gap term rounded half-up to whole cents. For all other methodologies `rbp_amount_cents` stays null.

A successful reprice returns the created `RepricingDetermination` as the response's data object. It is created in `ACTIVE` status recording the `claim_id`, the applied `methodology`, the driving `policy_id` (null for negotiated determinations and null for in-network claims priced directly off an agreement), the `agreement_id` when the methodology is `CONTRACTED_NETWORK` (null otherwise), the frozen `input_snapshot`, the `computation_trace`, and any `defensibility_notes`. Every non-`VOID` line's `allowed_amount_cents` is set and each line's status moves to `PRICED`. The claim's `allowed_amount_cents` is the sum of the line allowed amounts; `payer_liability_cents` is the allowed amount minus `patient_responsibility_cents`; `savings_cents` is `billed_amount_cents` minus `allowed_amount_cents` plus `patient_responsibility_cents`; and `methodology_used` records the selected methodology. The claim transitions to `PRICED` and its `version` increments. As a downstream ledger effect, when the methodology is `CONTRACTED_NETWORK` the applied `NetworkAgreement` is touched: its `version` increments by 1 as the second hop of the repricing cascade. A failed reprice — one rejected with `ERR_NEGOTIATION_REQUIRED`, `ERR_NO_REPRICING_POLICY`, or `ERR_RATE_INPUT_MISSING` — is a pure rejection: the claim remains `PENDING_LINES` and no failure state is persisted. A claim's full determination chain can be listed under the claim, and determinations across claims can be listed filtered by `policy_id`, `agreement_id`, `supersedes_determination_id`, or `status`, giving reverse reachability for determination foreign keys; a single determination can also be fetched by id.

### 3.5. Bilateral Negotiation on Out-of-Network Claims

When direct repricing is inappropriate — typically because the policy says `NEGOTIATION_REQUIRED` or because either side wants to bargain — either a `PayerRep` or a `ProviderRep` opens a `NegotiationCase` against a claim that is in `PRICED` or `PENDING_LINES` status, supplying the `claim_id`. Only one non-terminal case — one in `OPEN`, `OFFER_PENDING`, `COUNTERED`, or `ACCEPTED` — may exist per claim; opening a second surfaces `ERR_CASE_ALREADY_OPEN` (HTTP 409). The case records `opened_by_role` as `PayerRep` or `ProviderRep`, starts with `round_count` 0, and is in `OPEN` status with no offer yet on the table.

The payer makes the first move. Placing an offer carries `offer_cents` and `expected_case_version` (see §2.7). The offer must be greater than zero and no more than the claim's `billed_amount_cents`, else the request is rejected with `ERR_OFFER_OUT_OF_RANGE` (HTTP 422). A valid offer from `OPEN` moves the case to `OFFER_PENDING` and sets `current_offer_cents` to the offer. From `COUNTERED`, a new payer offer returns the case to `OFFER_PENDING` and replaces `current_offer_cents`, again bounded above by `billed_amount_cents`. Either transition bumps the case's `version`.

The provider's reply is a counteroffer carrying `counter_cents`. The counter must be at least the `current_offer_cents` on the table — a lower counter is rejected with `ERR_COUNTER_BELOW_OFFER` (HTTP 422) — and must not exceed the claim's `billed_amount_cents`. A valid counter moves the case from `OFFER_PENDING` to `COUNTERED`, sets `current_offer_cents` to the counter, and increments `round_count`. The negotiation has a hard round cap: when `round_count` reaches 5, the counter call itself leaves the case in `EXPIRED` — the move out of `OFFER_PENDING` lands directly on `EXPIRED` with the accepted counter still recorded in `current_offer_cents`, all within the counter call's single `version` increment. The cycle `OPEN` to `OFFER_PENDING` to `COUNTERED` and back to `OFFER_PENDING` is intentionally non-linear and may repeat until agreement, withdrawal, or expiry.

Either side may walk away while the case is in `OPEN`, `OFFER_PENDING`, or `COUNTERED`: withdrawal moves the case to `WITHDRAWN`. Acceptance works from both directions — the provider accepts the payer's offer while the case is `OFFER_PENDING`, or the payer accepts the provider's counter while the case is `COUNTERED`; an acceptance attempted by the wrong side for the case's current status (a payer accepting an `OFFER_PENDING` case, or a provider accepting a `COUNTERED` case) is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Either acceptance moves the case to `ACCEPTED` and creates a `SettlementAgreement` in `PENDING_SIGNATURES` whose `settled_amount_cents` equals the `current_offer_cents` at acceptance time and whose `claim_id` is copied from the negotiation case. The accept call's response data is the updated `NegotiationCase`; the created `SettlementAgreement` is reachable through the settlement-agreement list and get endpoints. Cases may be fetched or listed with `claim_id` or `status` filters.

### 3.6. Settlement Execution and the Compensation Path

A settlement agreement sits in `PENDING_SIGNATURES` until both parties have signed. Each side signs once: the first signature sets either `payer_signed_at` or `provider_signed_at` depending on the signer's role, and the case remains `PENDING_SIGNATURES`. A party attempting to sign twice is rejected with `ERR_ALREADY_SIGNED` (HTTP 409). The second signature — which requires the other party to have already signed and the underlying claim not yet `FINALIZED` — moves the agreement to `EXECUTED`. The `FINALIZED` guard fires only at the moment of execution and is checked after the signature itself has been recorded: a second signature against a `FINALIZED` claim is rejected with `ERR_INVALID_STATE` (HTTP 409), yet the rejected call still leaves the signer's signature timestamp and the resulting `version` bump persisted on the agreement. Execution sets `balance_billing_prohibited` true (patient responsibility stays exactly as recorded on the claim) and fires two cascades: first the claim transitions `PRICED` to `SETTLED`, its `allowed_amount_cents` is replaced by the agreement's `settled_amount_cents` with `payer_liability_cents` and `savings_cents` recomputed from the new allowed amount, and a new `RepricingDetermination` with `methodology` `NEGOTIATED` and `policy_id` null is created superseding the previously active determination; second, the parent `NegotiationCase` transitions `ACCEPTED` to `SETTLED` as the cascade's next hop. Each hop bumps the touched entity's `version`.

If no signature has been recorded yet, a `PayerRep` may void the agreement instead: voiding moves the agreement to `VOIDED` and, as the compensating action, reverts the `NegotiationCase` from `ACCEPTED` back to `COUNTERED` with `current_offer_cents` unchanged. Voiding after any signature is rejected with `ERR_ALREADY_SIGNED`. Agreements may be fetched or listed with `claim_id`, `negotiation_case_id`, or `status` filters.

### 3.7. No-Surprises Open Negotiation and Independent Dispute Resolution

Claims flagged `nsa_flag` true are protected by the federal no-surprises process and follow a distinct dispute path. Either a `PayerRep` or a `ProviderRep` initiates an `OpenNegotiation` against the claim, supplying `claim_id` and `initiated_by` (`PAYER` or `PROVIDER`). The negotiation is born `ACTIVE`, its `initiated_at` is stamped from the logical clock, and its `expires_at` is computed as `initiated_at` plus 30 business days — business days being Monday through Friday, with counting starting the day after initiation.

While the negotiation is `ACTIVE`, the two sides may reach agreement by recording an `agreed_amount_cents` greater than zero and no more than the claim's `billed_amount_cents` — an amount outside that range is rejected with `ERR_OFFER_OUT_OF_RANGE` (HTTP 422). Agreement moves the negotiation to `AGREED`, re-prices the claim to the agreed amount — the claim's `allowed_amount_cents` is replaced, `payer_liability_cents` and `savings_cents` are recomputed, and a new `NEGOTIATED` `RepricingDetermination` supersedes the prior one — and transitions the claim from `PRICED` to `SETTLED`. If no agreement is reached, the negotiation expires on its own: when the logical clock reaches or passes `expires_at`, the negotiation transitions from `ACTIVE` to `EXPIRED` (this is the side effect of clock advancement described in §2.5).

Submission to independent dispute resolution is forbidden strictly before `expires_at`. An IDR submission attempted while the open negotiation is still within its window is rejected with `ERR_OPEN_NEGOTIATION_ACTIVE` (HTTP 409). Once the negotiation is `EXPIRED` and the logical clock has reached `expires_at`, either side may submit the dispute, supplying `claim_id`, the completed `open_negotiation_id`, a `payer_offer_cents`, and a `provider_offer_cents`. The submission is born `SUBMITTED`, the referenced `OpenNegotiation` transitions from `EXPIRED` to `SUPERSEDED_BY_IDR`, and the qualifying payment amount is computed at submission time. The QPA candidate set is every `ACTIVE` `NetworkAgreement` whose determination snapshots priced the claim's primary `procedure_code` in the claim's primary line's `region_code` under `CONTRACTED_NETWORK`, regardless of payer; each candidate contributes a per-unit contracted rate — the agreement's discount applied to the snapshotted per-unit charge (`unit_charge_cents`) recorded in its `input_snapshot`, rounded half-up to whole cents. The `qpa_cents` is the median of the candidate rates: the rates are sorted ascending, an odd count takes the middle element, and an even count takes the lower-middle element (the element at index count divided by two minus one, zero-based); equal values simply collapse, so no tie-break is needed. When no candidates exist the submission is rejected with `ERR_QPA_UNAVAILABLE` (HTTP 422).

The `IdrEntity` then renders a baseball-style decision. Deciding in the payer's favor requires `winner` indicating the payer and a `winning_amount_cents` exactly equal to the submission's `payer_offer_cents`; deciding in the provider's favor requires the `winning_amount_cents` to equal `provider_offer_cents`. A mismatch is rejected with `ERR_IDR_AMOUNT_MISMATCH` (HTTP 422). A decision moves the submission to `DECIDED_PAYER` or `DECIDED_PROVIDER` respectively, replaces the claim's `allowed_amount_cents` with the winning offer, recomputes the derived amounts, creates a new superseding determination — carrying `methodology` `NEGOTIATED` and `policy_id` null, like every dispute-path determination — and transitions the claim to `SETTLED`. The `IdrEntity` may instead dismiss the submission, moving it to `DISMISSED` with no claim-side effect. Submissions may be fetched or listed with `claim_id`, `open_negotiation_id`, or `status` filters.

### 3.8. Provider Appeals and Re-Review

A provider who disputes a repriced amount files a `ProviderAppeal` against the claim, supplying the `determination_id` of the determination being appealed and a free-text `appeal_reason`. The appeal is born `SUBMITTED`. The appeal window is hard: `appeal_window_deadline` is the determination's creation timestamp plus 45 calendar days, and an appeal submitted strictly after that instant is rejected with `ERR_APPEAL_WINDOW_CLOSED` (HTTP 409); a submission at exactly the deadline is admitted. Appeals may be fetched or listed with `claim_id`, `determination_id`, or `status` filters.

A `PayerRep` picks the appeal up, moving it from `SUBMITTED` to `UNDER_REVIEW`. Resolution then takes one of three outcomes. An `outcome` of upheld moves the appeal to `RE_REVIEWED_UPHELD`; an `outcome` of denied moves it to `DENIED`; both leave the claim's amounts untouched. An `outcome` of adjusted requires `adjusted_amount_cents` greater than zero and no more than the claim's `billed_amount_cents` — an amount outside that range is rejected with `ERR_OFFER_OUT_OF_RANGE` (HTTP 422) — moves the appeal to `RE_REVIEWED_ADJUSTED`, and fires a three-hop cascade: a new `RepricingDetermination` is created with the `methodology`, `policy_id`, and `agreement_id` copied from the appealed determination, superseding the previously active one; the prior determination's status flips to `SUPERSEDED`; and the claim's `allowed_amount_cents`, `payer_liability_cents`, and `savings_cents` are recomputed from the adjusted amount with the claim's `version` incrementing. The claim itself remains in `PRICED` through an adjusted re-review — the appeal re-prices in place rather than moving the claim through a visible status change. While any appeal for a claim is in `SUBMITTED` or `UNDER_REVIEW`, finalizing that claim is rejected with `ERR_APPEAL_IN_PROGRESS` (HTTP 409).

### 3.9. Finalization, Fee Invoicing, and Transparency Reporting

A claim in `PRICED` or `SETTLED` may be finalized by a `PayerRep`, provided no appeal for the claim is still `SUBMITTED` or `UNDER_REVIEW`. Finalization moves the claim to `FINALIZED` and makes it invoiceable.

An `OpsAdmin` creates a `FeeInvoice` in `DRAFT` status by supplying the `payer_client_id` and a list of `claim_ids`. Issuing the invoice applies two fiscal guards, in order: every listed claim must be `FINALIZED` — otherwise `ERR_CLAIM_NOT_FINALIZED` (HTTP 409) — and no listed claim may already appear on another non-voided invoice — otherwise `ERR_CLAIM_ALREADY_INVOICED` (HTTP 409); these guards apply both at invoice creation and at issue time. On issue, the per-claim fee is computed by a tiered waterfall over the claim's `savings_cents`: the first 20000 cents of savings are charged at 0.25, any savings beyond the first 20000 cents are charged at 0.20, the sum of the two tier amounts is rounded half-up to whole cents per claim, and that rounded figure is capped at the payer's `fee_cap_cents_per_claim`. This tier schedule is fixed system-wide and applies to every payer; no per-payer tier table exists, so the payer's `fee_percent` is retained as onboarding configuration but is not consulted by fee computation. The invoice's `gross_fee_cents` is the sum of the per-claim fees, and `aggregate_fee_cents` — the running sum of `gross_fee_cents` across all non-voided invoices of the same payer — is recomputed on every issue. Issued invoices can later be voided, moving them to `VOIDED`; voiding does not delete any transparency report already published, and voiding recomputes `aggregate_fee_cents` across the payer's remaining non-voided invoices. The `minimum_invoice_cents` floor never blocks issuance. Invoices may be fetched or listed with `payer_client_id`, `status`, or `transparency_report_id` filters.

For payers that have opted in — `transparency_reporting_enabled` true — an `OpsAdmin` may publish a client-facing savings transparency report from an `ISSUED` invoice. Publishing against a payer without the flag, or against an invoice not yet `ISSUED`, is rejected with `ERR_TRANSPARENCY_NOT_ENABLED` (HTTP 422). The published `TransparencyReport` is born in `PUBLISHED` status and aggregates across the invoice's claims: `total_billed_cents` sums the claims' `billed_amount_cents`, `total_allowed_cents` sums their `allowed_amount_cents`, `total_savings_cents` sums their `savings_cents`, and `total_fee_cents` captures the invoice's `gross_fee_cents` at publish time. Publishing also sets the invoice's `transparency_report_id`. Reports may be fetched or listed with a `fee_invoice_id` filter.

### 3.10. Data Feeds and Turnaround Service Levels

Payer claim systems exchange bulk data with the platform through feed batches. A `FeedOperator` registers a `ClaimFeedBatch` by supplying the `payer_client_id` — which must reference an existing `PayerClient`, else `ERR_NOT_FOUND` (HTTP 404) — a `feed_type` of `CLAIM_INTAKE`, `REMITTANCE`, or `ELIGIBILITY`, and the `record_count` of records in the batch. The batch is born `RECEIVED`, its `received_at` is stamped from the logical clock, and its `sla_due_at` is computed against a business-hours calendar.

The business-hours calendar runs Monday through Friday, from 09:00:00Z to 17:00:00Z. The turnaround budget is 4 business hours for `CLAIM_INTAKE` batches and 24 business hours for `REMITTANCE` and `ELIGIBILITY` batches. Hours accrue only inside the calendar window — time outside the window does not count — and a batch received outside business hours starts counting at the next 09:00:00Z. When the `FeedOperator` marks the batch processed, `processed_at` is stamped from the logical clock and `sla_met` is computed as true when `processed_at` is at or before `sla_due_at` — equality counts as met — and false otherwise; until processing, both `processed_at` and `sla_met` are null. Processing moves the batch to `PROCESSED`; alternatively the operator may mark it `FAILED`. Both operations are defined only on a batch still in `RECEIVED`; a process or fail call against a batch in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Batches may be fetched, or listed with `payer_client_id`, `feed_type`, `status`, or `sla_met` filters.

## 4. Endpoint Definitions

All endpoints live under the API root. Successful creation of a new resource returns HTTP 201; successful modifications, state transitions, and reads return HTTP 200. Errors return the HTTP status paired with the `error_id` in §5. All list endpoints honor the pagination contract in §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock (default 2026-09-01T00:00:00Z before first set) | OpsAdmin, FeedOperator |
| POST | `/payer-clients` | Onboard a payer client with fee configuration | OpsAdmin |
| GET | `/payer-clients/{id}` | Get a payer client | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, NetworkAdmin, FeedOperator, IdrEntity |
| GET | `/payer-clients` | List payer clients | OpsAdmin, PayerAdmin |
| POST | `/payer-clients/{id}/suspend` | Suspend a payer client | OpsAdmin |
| POST | `/payer-clients/{id}/reinstate` | Reinstate a suspended payer | OpsAdmin |
| POST | `/repricing-policies` | Create a repricing policy for a payer | PayerAdmin |
| GET | `/repricing-policies/{id}` | Get a repricing policy | OpsAdmin, PayerAdmin, PayerRep |
| GET | `/repricing-policies` | List repricing policies | OpsAdmin, PayerAdmin, PayerRep |
| POST | `/repricing-policies/{id}/retire` | Retire a policy | PayerAdmin |
| GET | `/repricing-determinations/{id}` | Get a single repricing determination | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| GET | `/repricing-determinations` | List determinations filtered by policy, agreement, or supersession link | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| POST | `/providers` | Register a provider | NetworkAdmin |
| GET | `/providers/{id}` | Get a provider | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, NetworkAdmin, FeedOperator, IdrEntity |
| GET | `/providers` | List providers | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, NetworkAdmin |
| POST | `/network-agreements` | Create a contracted network agreement | NetworkAdmin |
| GET | `/network-agreements/{id}` | Get an agreement | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, NetworkAdmin |
| GET | `/network-agreements` | List agreements | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, NetworkAdmin |
| POST | `/network-agreements/{id}/suspend` | Suspend an agreement | NetworkAdmin |
| POST | `/network-agreements/{id}/reinstate` | Reinstate an agreement | NetworkAdmin |
| POST | `/network-agreements/{id}/terminate` | Terminate an agreement | NetworkAdmin |
| POST | `/medicare-fee-schedule` | Load a Medicare fee schedule entry | NetworkAdmin |
| GET | `/medicare-fee-schedule` | List Medicare fee schedule entries | OpsAdmin, PayerAdmin, PayerRep, NetworkAdmin |
| POST | `/ucr-rates` | Load a UCR benchmark row | NetworkAdmin |
| GET | `/ucr-rates` | List UCR rows | OpsAdmin, PayerAdmin, PayerRep, NetworkAdmin |
| POST | `/claims` | Ingest a claim from a payer feed | PayerRep |
| GET | `/claims/{id}` | Get a claim | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, NetworkAdmin, IdrEntity |
| GET | `/claims` | List claims | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| POST | `/claims/{id}/lines` | Add a claim line | PayerRep |
| GET | `/claims/{id}/lines` | List lines of a claim | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| POST | `/claims/{id}/reprice` | Price a pending claim under the selected policy | PayerRep |
| GET | `/claims/{id}/determinations` | List the determination chain of a claim | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| POST | `/claims/{id}/finalize` | Finalize a priced or settled claim (makes it invoiceable) | PayerRep |
| POST | `/negotiation-cases` | Open a negotiation on an out-of-network claim | PayerRep, ProviderRep |
| GET | `/negotiation-cases/{id}` | Get a negotiation case | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| GET | `/negotiation-cases` | List negotiation cases | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| POST | `/negotiation-cases/{id}/offer` | Payer places or improves an offer | PayerRep |
| POST | `/negotiation-cases/{id}/counter` | Provider counters the payer offer | ProviderRep |
| POST | `/negotiation-cases/{id}/accept` | Accept the offer currently on the table | PayerRep, ProviderRep |
| POST | `/negotiation-cases/{id}/withdraw` | Withdraw a negotiation | PayerRep, ProviderRep |
| GET | `/settlement-agreements/{id}` | Get a settlement agreement | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| GET | `/settlement-agreements` | List settlement agreements | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| POST | `/settlement-agreements/{id}/sign` | Sign a settlement (each party signs once; second signature executes) | PayerRep, ProviderRep |
| POST | `/settlement-agreements/{id}/void` | Void an unsigned settlement (compensating action) | PayerRep |
| POST | `/open-negotiations` | Initiate a federal open negotiation period for an NSA claim | PayerRep, ProviderRep |
| GET | `/open-negotiations/{id}` | Get an open negotiation | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, IdrEntity |
| GET | `/open-negotiations` | List open negotiations | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, IdrEntity |
| POST | `/open-negotiations/{id}/agree` | Record agreement during the open negotiation period | PayerRep, ProviderRep |
| POST | `/idr-submissions` | Submit a completed open negotiation to independent dispute resolution | PayerRep, ProviderRep |
| GET | `/idr-submissions/{id}` | Get an IDR submission | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, IdrEntity |
| GET | `/idr-submissions` | List IDR submissions | OpsAdmin, PayerAdmin, PayerRep, ProviderRep, IdrEntity |
| POST | `/idr-submissions/{id}/decide` | IDR entity renders a baseball-style decision | IdrEntity |
| POST | `/idr-submissions/{id}/dismiss` | Dismiss an IDR submission | IdrEntity |
| POST | `/claims/{id}/appeals` | Provider appeals a repriced claim | ProviderRep |
| GET | `/appeals/{id}` | Get an appeal | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| GET | `/appeals` | List appeals | OpsAdmin, PayerAdmin, PayerRep, ProviderRep |
| POST | `/appeals/{id}/start-review` | Payer starts re-review | PayerRep |
| POST | `/appeals/{id}/resolve` | Resolve the appeal | PayerRep |
| POST | `/feed-batches` | Register receipt of a payer data feed batch | FeedOperator |
| GET | `/feed-batches/{id}` | Get a feed batch | OpsAdmin, PayerAdmin, FeedOperator |
| GET | `/feed-batches` | List feed batches | OpsAdmin, PayerAdmin, FeedOperator |
| POST | `/feed-batches/{id}/process` | Mark a feed batch processed | FeedOperator |
| POST | `/feed-batches/{id}/fail` | Mark a feed batch failed | FeedOperator |
| POST | `/fee-invoices` | Create a draft fee invoice over finalized claims | OpsAdmin |
| GET | `/fee-invoices/{id}` | Get a fee invoice | OpsAdmin, PayerAdmin |
| GET | `/fee-invoices` | List fee invoices | OpsAdmin, PayerAdmin |
| POST | `/fee-invoices/{id}/issue` | Issue a fee invoice (computes fees) | OpsAdmin |
| POST | `/fee-invoices/{id}/void` | Void an issued invoice | OpsAdmin |
| POST | `/fee-invoices/{id}/publish-transparency-report` | Publish the client transparency report for an issued invoice | OpsAdmin |
| GET | `/transparency-reports/{id}` | Get a transparency report | OpsAdmin, PayerAdmin |
| GET | `/transparency-reports` | List transparency reports | OpsAdmin, PayerAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PAYER_SUSPENDED` | 409 |
| `ERR_DUPLICATE_CLAIM_REF` | 409 |
| `ERR_DUPLICATE_NPI` | 409 |
| `ERR_AGREEMENT_OVERLAP` | 409 |
| `ERR_NO_CONTRACTED_AGREEMENT` | 422 |
| `ERR_NO_REPRICING_POLICY` | 422 |
| `ERR_NEGOTIATION_REQUIRED` | 422 |
| `ERR_NSA_METHODOLOGY_CONFLICT` | 422 |
| `ERR_RATE_INPUT_MISSING` | 422 |
| `ERR_CLAIM_HAS_NO_LINES` | 422 |
| `ERR_CASE_ALREADY_OPEN` | 409 |
| `ERR_OFFER_OUT_OF_RANGE` | 422 |
| `ERR_COUNTER_BELOW_OFFER` | 422 |
| `ERR_ALREADY_SIGNED` | 409 |
| `ERR_OPEN_NEGOTIATION_ACTIVE` | 409 |
| `ERR_QPA_UNAVAILABLE` | 422 |
| `ERR_IDR_AMOUNT_MISMATCH` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_APPEAL_IN_PROGRESS` | 409 |
| `ERR_CLAIM_NOT_FINALIZED` | 409 |
| `ERR_CLAIM_ALREADY_INVOICED` | 409 |
| `ERR_TRANSPARENCY_NOT_ENABLED` | 422 |
