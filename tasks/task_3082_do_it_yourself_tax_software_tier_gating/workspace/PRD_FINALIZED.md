# DIY Tax Tier Gating API — Product Requirements Document

## 1. Introduction

Consumer do-it-yourself tax software lives or dies on two promises: the filer pays only for the complexity their return actually requires, and the price they were shown mid-return is the price they pay at filing. This document specifies the API surface behind a TurboTax-style DIY filing product: a guided question flow that assembles a federal return form by form, classifies the return's complexity against a four-tier product catalog, gates free filing on both form usage and income, prompts for paid-tier upgrades with explicit price-change acknowledgment, supports prior-year carryforward import, state add-on returns with part-year and non-resident allocation, a refund-transfer product that pays preparation fees out of the refund through a partner bank, an accuracy-guarantee claims program, and a simulated tax-authority e-file loop with rejection codes and guided correction.

The system is built for auditability. Every tier classification is reproducible from the forms physically present on the return, every fee total is derivable from the tier catalog and the elected add-ons, and every state transition on a return, prompt, filing attempt, agreement, or claim is explicit. Three roles share the surface: the `Taxpayer` who owns and drives their return, the `ClaimsAdjuster` who reviews accuracy-guarantee claims, and the `PlatformOperator` who seeds catalogs, drives the simulated authority, and administers accounts. The API is mounted under the `/tax` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the principal acts. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Three roles exist, spelled exactly as follows:

- **`Taxpayer`** — the DIY filer. When `X-User-Role` is `Taxpayer`, `X-User-ID` is the `id` of the acting `TaxpayerAccount`; ownership checks on any resource that references a `TaxpayerAccount` compare the resource's account foreign key to `X-User-ID`. Account registration itself is a bootstrap operation: it is performed under the `Taxpayer` role before any account id exists, and the newly minted account id becomes the caller's identity for all subsequent calls.
- **`ClaimsAdjuster`** — the reviewer of accuracy-guarantee claims. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`PlatformOperator`** — the operations and system-simulation role. When `X-User-Role` is `PlatformOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

The `Taxpayer` exclusively performs return-graph mutations: registering accounts, starting returns, adding and removing forms, importing snapshots, selecting tiers, resolving upgrade prompts, managing state returns, electing and voiding refund transfer, filing, amending, and filing claims. The `ClaimsAdjuster` exclusively performs claim review operations (start-review, adjudicate, reopen-review, pay) and otherwise has read access to accounts, returns, forms, state returns, claims, filing attempts, and the tier and form catalogs. The `PlatformOperator` exclusively seeds the tier and form catalogs, suspends accounts, sets the logical clock, and injects authority filing callbacks. The exact per-endpoint role grants are listed in §4.

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

All list endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses are sorted by `created_at` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether further records exist beyond the returned window.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource has an `id`, a server-minted UUID with no type prefix. Mutable domain resources — `TaxpayerAccount`, `PriorYearReturnSnapshot`, `TaxReturn`, `ReturnForm`, `UpgradePrompt`, `StateReturn`, `FilingAttempt`, `RefundTransferAgreement`, and `AccuracyClaim` — additionally carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and an integer `version` that starts at creation and increments by exactly 1 on every mutation of that resource. The two catalog resources, `ProductTier` and `FormSpec`, are configuration rows: they carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

The `version` field of a `TaxReturn` is the coordination point for the entire return graph. Any mutation that touches the return's derived state — adding or removing a form, importing a snapshot, selecting a tier, acknowledging or declining an upgrade prompt, adding, readying, or removing a state return, creating, activating, or voiding a refund-transfer agreement, submitting for review, reopening, filing, amending — increments the owning return's `version` by 1 and refreshes its `updated_at`, even when the primary object of the call is a child resource. The authority callback of §3.7 is the exception: it is a system-driven, not filer-driven, transition, so it updates the return's `status` without incrementing the return's `version` or refreshing its `updated_at` — a reopen or re-filing after a rejection therefore continues from the version the return carried at submission.

### 2.5. Money, Precision, and the Catalog Constants

All monetary amounts are integer cents. Fields such as `agi_cents`, `price_cents`, `state_addon_price_cents`, `amount_cents`, `price_delta_cents`, `federal_refund_cents`, `total_fees_due_cents`, `service_fee_cents`, `allocated_tax_cents`, `claimed_error_amount_cents`, `reviewed_error_amount_cents`, and `reimbursement_cents` are exact integer-cent values; fee summation and refund aggregation involve no rounding stage at all. Lifecycle fields on every domain resource — each entity's `status` field — carry the exact UPPERCASE state strings used throughout §3. The single rounding rule in the system belongs to state tax allocation: the final allocated tax product is rounded half-up to whole cents, and the allocation ratio itself is never pre-rounded.

Four money constants are fixed by the platform and recur throughout this document. The free-file income ceiling is $84,000.00 of adjusted gross income — an inclusive upper bound, so an account at exactly $84,000.00 remains eligible and one cent over does not. The refund-transfer bank-partner service fee is a flat $40.00. Every state's income tax is a flat 5% rate. The accuracy guarantee reimburses at most $1,000.00 per return. The registered bank partners are exactly `BANK_A` and `BANK_B`, and the currently active bank disclosure version is the string `RTD-2026-1`.

### 2.6. The Logical Clock

The server maintains a logical clock distinct from wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformOperator` advances it through an admin-only test-driving capability that sets the current UTC instant from a supplied `to_iso8601` value. Two pieces of domain state read this clock: the `resolved_at` timestamp stamped on a `FilingAttempt` when its outcome leaves `PENDING`, and the 24-hour amendment hold window that anchors to that timestamp. Time comparisons on the logical clock are made at second granularity.

### 2.7. Optimistic Concurrency Control on the Return Graph

Because so many child-resource operations mutate the parent return's derived state, return-mutating write endpoints accept an `expected_return_version` field carrying the client's last observed `version` of the parent `TaxReturn`. On two endpoints this field is mandatory and load-bearing:

- **Adding a form to a return** requires `expected_return_version`. If the return's current `version` has advanced since the client last read it — because a prior form add or remove, or a prior-year import, already recomputed the minimum tier and possibly created or superseded an upgrade prompt — the add is rejected with `ERR_STALE_VERSION` (HTTP 412), since the stale writer's view of the return's tier state is outdated.
- **Submitting a return for review** requires `expected_return_version`. A mismatch with the return's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because an intervening upgrade acknowledgment, form removal, or state-return change may have altered the fee and tier state after the client last read the return.

On the remaining return-mutating endpoints that accept `expected_return_version` (tier selection, form removal, reopening, filing, amending, prompt acknowledgment and decline, state-return creation, readying and removal, refund-transfer creation, disclosure acceptance, and voiding), a supplied value must equal the return's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Read endpoints do not take a version field.

### 2.8. Validation Order, Path Resolution, and Suspension

When several checks could reject the same request, the server evaluates them in a fixed priority order so the surfaced error is deterministic. First come the two authentication checks in §2.1 (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, then `ERR_INSUFFICIENT_PERMISSIONS`). Next, path identifiers are resolved left to right — account, then return, then the child resource — and the first missing segment produces the corresponding 404: `ERR_ACCOUNT_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_FORM_NOT_FOUND`, `ERR_PROMPT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, or `ERR_STATE_RETURN_NOT_FOUND`. After path resolution, body-referenced catalog resources are checked: an unregistered `form_code` yields `ERR_FORM_SPEC_NOT_FOUND` and an unregistered `bank_partner_code` yields `ERR_BANK_PARTNER_NOT_FOUND`. Only then does the server consult state: a `SUSPENDED` account rejects every return-graph mutation with `ERR_ACCOUNT_SUSPENDED` (HTTP 409), and a target resource in an illegal from-state for the requested transition is rejected with `ERR_INVALID_STATE` (HTTP 409) — this covers terminal-state lockdowns, a direct file attempt on an `AMENDED` return, and double-resolution of an already-settled prompt, among others. The optimistic-concurrency check of §2.7 follows, and business-rule validations run last, in the relative order stated alongside each workflow in §3.

### 2.9. The Tier and Form Catalogs

Two configuration catalogs underpin classification. A `ProductTier` row pairs a `code` — one of `FREE`, `DELUXE`, `PREMIER`, or `SELF_EMPLOYED`, unique across the catalog — with a `price_cents` federal price and a `state_addon_price_cents` per-state add-on price (both non-negative integer cents), a `supported_forms` array of form codes the tier supports natively, and a `tier_rank` ordinal. Ranks are fixed: `FREE` ranks 0, `DELUXE` ranks 1, `PREMIER` ranks 2, and `SELF_EMPLOYED` ranks 3; every tier comparison in this document is a rank comparison. A `FormSpec` row pairs a unique `code` (such as `F1040`, `SCH_C`, `SCH_D`, `F8949`, `SCH_E`, `F4562`, or `W2_WH`) with a `minimum_tier` naming the cheapest tier that supports the form, a `disqualifies_free_file` flag, and a `counts_toward_refund` flag defaulting to false. Both catalogs are seeded exclusively by the `PlatformOperator` and are readable by all three roles. Catalog seeding is idempotent on the natural key: re-seeding a `ProductTier` code or `FormSpec` code with a payload identical to the existing row returns the existing row with HTTP 201 and changes nothing; re-seeding the same code with any differing field is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Opening an Account and Starting a Return

A new filer begins by registering a `TaxpayerAccount` with their `email` (unique across all accounts), `full_name`, `filing_status`, `agi_cents`, and `resident_state_code`. The filing status is one of `SINGLE`, `MARRIED_FILING_JOINTLY`, `MARRIED_FILING_SEPARATELY`, `HEAD_OF_HOUSEHOLD`, or `QUALIFYING_WIDOWER`; the adjusted gross income is a non-negative integer-cent figure and drives the free-file income gate for every return the account ever files. Registration also accepts an optional `accuracy_guarantee_enrolled` flag, which defaults to true and later gates the claims workflow. New accounts start in `ACTIVE` status with `disclosure_accepted_version` null — the version tag of the refund-transfer bank disclosure the taxpayer last accepted, which stays null until a disclosure is actually accepted.

A `PlatformOperator` may suspend an account, moving it from `ACTIVE` to `SUSPENDED`. Suspension is one-way — this surface offers no reactivation path — and from that moment every mutating endpoint on the account's returns fails with `ERR_ACCOUNT_SUSPENDED`, while reads remain available.

From an active account, the filer starts a `TaxReturn` for a given `tax_year`. The return records its owner on `account_id` and opens in `DRAFT` status with `current_tier` set to `FREE` and `minimum_required_tier` set to `FREE`. With no forms yet present, the free-file determination collapses to the pure income check: `free_file_eligible` is true exactly when the account's `agi_cents` is at most the $84,000.00 ceiling. The return's computed ledger fields start clean — `federal_refund_cents` at zero, `total_fees_due_cents` at the `FREE` tier's price, `refund_transfer_selected` false, and `upgrade_prompt_pending` false.

### 3.2. The Question Flow: Forms, Classification, and the Price Ladder

Each answer in the guided interview materializes as a `ReturnForm` added to the return, carrying a `form_code` registered in the form catalog and an `amount_cents` figure (which may be negative, for losses). Manually added forms are stamped with `source` set to `MANUAL` and a `carryforward_item_type` of `NONE`, and begin in `ACTIVE` status. Two forms with the same `form_code` may not both be `ACTIVE` on one return; a duplicate add is rejected with `ERR_DUPLICATE_FORM_ON_RETURN` (HTTP 409).

Every form add — and every form removal — triggers an eager **provisional classification**. The system considers only `ACTIVE` forms (removed rows are excluded from classification and refund math but retained for audit) and takes the highest `tier_rank` among the `minimum_tier` values of their form specs; the tier at that rank becomes the return's `minimum_required_tier`. An empty form set classifies as `FREE`. The same moment recomputes `free_file_eligible`: eligibility requires both that no `ACTIVE` form's spec has `disqualifies_free_file` set and that the account's AGI is at most the inclusive $84,000.00 ceiling. And because withholding and estimated-payment forms feed the refund, `federal_refund_cents` is recomputed as the exact cent sum of `amount_cents` over `ACTIVE` forms whose form spec has `counts_toward_refund` set; a negative total means the taxpayer owes rather than receives.

When a provisional classification lands above the return's `current_tier`, the system raises an `UpgradePrompt`. The prompt opens in `PENDING` status, recording `from_tier` (the return's tier at that moment), `to_tier` (the freshly computed minimum), and a `price_delta_cents` frozen at creation as the destination tier's `price_cents` minus the source tier's `price_cents` — this frozen figure is what the taxpayer is asked to acknowledge, so a later catalog price change cannot move the number under them. At most one prompt per return is ever `PENDING`; creating a newer one automatically moves the previous `PENDING` prompt to `SUPERSEDED`. The reverse direction holds too: when a recomputation — most directly a form removal — collapses the provisional minimum back to or below the return's `current_tier`, any outstanding `PENDING` prompt is stale and likewise moves to `SUPERSEDED`. While any prompt is `PENDING`, the return's `upgrade_prompt_pending` flag is true and review is gated, as §3.6 describes.

Resolving a prompt is the filer's explicit choice, and both resolutions require the return to be editable — `DRAFT` or `AMENDED`; acting on a prompt from any other return status is rejected with `ERR_RETURN_NOT_EDITABLE`. **Acknowledging** moves the prompt `PENDING` → `ACKNOWLEDGED`, sets its `acknowledged` flag true, ratchets the return's `current_tier` up to the prompt's `to_tier`, recomputes `upgrade_prompt_pending` (it clears when this was the last pending prompt), and reprices the return at the new tier. **Declining** takes the downgrade path: the prompt moves `PENDING` → `DECLINED_DOWNGRADED`, and every `ACTIVE` form with `source` `MANUAL` whose form spec's `minimum_tier` outranks the prompt's `from_tier` is swept to `REMOVED`, after which `minimum_required_tier`, `free_file_eligible`, and `upgrade_prompt_pending` are recomputed. Imported carryforward forms are the exception to this sweep — they represent data the filer asked to bring forward and are never silently discarded. If any `ACTIVE` form with `source` `IMPORTED` still requires a tier above the prompt's `from_tier`, the decline is refused with `ERR_DOWNGRADE_WOULD_LEAVE_GAP` (HTTP 409); the filer must remove those imported forms explicitly first. Because decline-downgrade can shrink the active form set, a return that provisionally required `SELF_EMPLOYED` may settle all the way back at `FREE` once the offending forms are gone.

A filer may also climb the ladder voluntarily through tier selection, the required path for an over-income filer stuck at `FREE` (whose return can never pass review while free-file ineligible). Tier selection names a `target_tier` whose rank must be strictly greater than the current tier's rank — a sideways or downward request is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and whose rank must also be at least the `minimum_required_tier` rank, otherwise `ERR_TIER_BELOW_REQUIRED` (HTTP 422). A successful selection sets `current_tier` to the target and reprices the return.

Repricing follows a fixed recipe everywhere it occurs. `total_fees_due_cents` is the sum of three components, evaluated in order: the `price_cents` of the return's `current_tier`; the per-state add-on charge, computed as the count of the return's `StateReturn` rows in `DRAFT`, `READY`, or `FILED` status (anything not `REMOVED`) multiplied by the current tier's `state_addon_price_cents`; and the $40.00 refund-transfer service fee, included only while `refund_transfer_selected` is true. The total is an exact integer-cent sum with no rounding stage, and it is recomputed on tier change, on state-return add or removal, on refund-transfer election or void, and again at review time. A return can exist before its current tier's catalog row has been seeded — every fresh return starts at `FREE`, whose row need not yet exist. Whenever the catalog row for the return's `current_tier` is absent, that tier's `price_cents` and `state_addon_price_cents` both price as zero, so an unseeded `FREE` return owes nothing until its tier row exists and a repricing pass runs.

### 3.3. Prior-Year Snapshots and Carryforward Import

Filers returning year over year register a `PriorYearReturnSnapshot` on their account, supplying a `tax_year` and a `carryforward_items` array whose entries each name an `item_type` of `DEPRECIATION`, `CAPITAL_LOSS`, or `BASIS`, an `asset_tag`, and a `remaining_amount_cents`. A snapshot opens with `import_status` `AVAILABLE`. Registering a newer snapshot for the same account and tax year automatically moves any existing `AVAILABLE` or `IMPORTED` snapshot for that pair to `SUPERSEDED`; a superseded snapshot may never be imported, and an import attempt against one fails with `ERR_SNAPSHOT_SUPERSEDED` (HTTP 422).

Importing a snapshot targets a specific return via `return_id` and is guarded by `expected_return_version` in the usual way. Two preconditions apply: the target return must be editable (`DRAFT` or `AMENDED`, else `ERR_RETURN_NOT_EDITABLE`), and the snapshot's `tax_year` must be strictly earlier than the return's `tax_year` (else `ERR_SNAPSHOT_YEAR_INVALID`, HTTP 422). On success, each carryforward entry materializes as a new `ReturnForm` with `source` `IMPORTED`, its `carryforward_item_type` set to the entry's item type, its `amount_cents` taken from `remaining_amount_cents`, and its form code mapped by type: `DEPRECIATION` becomes `F4562`, `CAPITAL_LOSS` becomes `SCH_D`, and `BASIS` becomes `F8949`. The import then runs the full recomputation pass — provisional minimum-tier classification, free-file eligibility, and the federal refund — and if the new minimum outranks the return's current tier, a `PENDING` upgrade prompt is created (superseding any existing pending prompt) exactly as in the question flow. The snapshot itself moves `AVAILABLE` → `IMPORTED`. Note that imported forms participate fully in classification, which is why the provisional minimum after an import can sit above the tier the return ultimately settles at — and why, as §3.2 described, decline-downgrade refuses to sweep them.

### 3.4. State Add-On Returns: Allocation and Residency

A filer with obligations beyond their home state adds a `StateReturn` to the federal return, supplying a two-letter `state_code`. The row's `is_resident_state` is derived: it is true exactly when `state_code` equals the owning account's `resident_state_code`. Only one live state return per state is allowed — adding a second non-`REMOVED` row with the same `state_code` is rejected with `ERR_DUPLICATE_STATE_RETURN` (HTTP 409), and this uniqueness check runs before the residency-window and allocation checks described below. The add is priced immediately: the per-state add-on charge folds into `total_fees_due_cents` per the recipe in §3.2.

Non-resident states carry an allocation. The filer supplies `allocation_numerator_cents` — the income sourced to that state, non-negative — and `allocation_denominator_cents`, the total allocation base. The numerator may never exceed the denominator, and whenever the numerator is positive the denominator must be present and greater than zero; violations are rejected with `ERR_ALLOCATION_EXCEEDS_BASE` (HTTP 422). Allocated tax is then computed at the flat 5% rate every state in this product shares. For a **resident** state return the allocation inputs are ignored entirely: `allocated_tax_cents` is the account's full AGI multiplied by 5%, rounded half-up to whole cents. For a **non-resident** state return with a zero numerator, the allocated tax is zero; otherwise the allocation ratio — numerator over denominator — is carried as an exact rational and never pre-rounded to a percentage, and `allocated_tax_cents` is the account's AGI multiplied by that ratio and then by 5%, with only this final product rounded half-up to whole cents. The allocation is re-derived whenever the allocation inputs change.

Part-year filers may attach a residency window to a state return: an optional `residency_start_date` (ISO `YYYY-MM-DD`) paired with a `residency_end_date`. The end date is required whenever a start date is present and must be strictly later than the start. Windows are half-open — a window covers its start date and runs up to but not including its end date — and across the non-`REMOVED` state returns of one return, two windows overlap exactly when each window's start precedes the other's end; bare adjacency, where one window ends on the day the next begins, is permitted. A colliding add is rejected with `ERR_RESIDENCY_OVERLAP` (HTTP 409).

A state return opens in `DRAFT`. Marking it ready moves it `DRAFT` → `READY` and requires the parent return to be editable (`DRAFT` or `AMENDED`, else `ERR_INVALID_STATE`). Removal moves a `DRAFT` or `READY` state return to its terminal `REMOVED` status — again requiring an editable parent return — and backs the per-state charge out of `total_fees_due_cents`. The remaining transitions are system-driven and ride on the federal filing cycle: when the parent return is filed, every `READY` state return moves to `FILED`, and if the authority later rejects that filing, every `FILED` state return rolls back to `READY` so it can be re-filed alongside the corrected federal return.

### 3.5. Refund Transfer: Paying Fees Out of the Refund

A filer who would rather not pay out of pocket elects refund transfer: a partner bank receives the refund, deducts the preparation fees, and disburses the remainder. Creating a `RefundTransferAgreement` on a return names a `bank_partner_code`, which must be one of the registered partners `BANK_A` or `BANK_B` — anything else is rejected with `ERR_BANK_PARTNER_NOT_FOUND` (HTTP 404). The agreement opens in `PENDING_DISCLOSURE` status with two figures frozen at creation: `service_fee_cents` fixed at the flat $40.00 bank-partner fee, and `disclosure_version` stamped from the currently active disclosure registry, `RTD-2026-1`.

The disclosure is a hard gate. Accepting it moves the agreement `PENDING_DISCLOSURE` → `ACTIVE` — allowed while the return is `DRAFT`, `AMENDED`, or `READY_FOR_REVIEW`, and rejected from any other status with `ERR_INVALID_STATE` — and produces three effects: the owning account's `disclosure_accepted_version` is set to the agreement's `disclosure_version`, the return's `refund_transfer_selected` flag becomes true (it is never set directly, only by acceptance), and the $40.00 service fee folds into `total_fees_due_cents`.

Voiding unwinds the election. From `PENDING_DISCLOSURE` the void always succeeds; from `ACTIVE` it is refused while a filing attempt is in flight, rejected with `ERR_FILING_IN_FLIGHT` (HTTP 409). Either way the agreement lands in its terminal `VOIDED` status, `refund_transfer_selected` returns to false (a no-op if the election was never activated), and the service fee is removed from the total if it had been included. At most one agreement per return is live at a time. The final transition is system-driven: when the return's filing is accepted by the authority, an `ACTIVE` agreement moves to `SETTLED` and the bank partner deducts the full `total_fees_due_cents` from the refund before disbursement.

### 3.6. Review and Filing

Submitting a return for review is the gate between editing and filing, reachable from `DRAFT` and from `AMENDED`, and it is the most heavily guarded transition in the system. Its checks resolve in a fixed order. The account must be `ACTIVE`. Any outstanding `PENDING` upgrade prompt blocks review with `ERR_UPGRADE_ACK_REQUIRED` (HTTP 409) — the price change must be acknowledged or decline-downgraded first, and this gate is evaluated before the free-file gate. The return must contain at least one `ACTIVE` form, else `ERR_NO_FORMS_ON_RETURN` (HTTP 422). The submission then runs the **settled classification**: the minimum-tier formula of §3.2 recomputed over the form set as it now stands, after every prompt has been resolved and every decline-downgrade sweep applied. If the settled minimum's rank exceeds the current tier's rank, the submission is rejected with `ERR_TIER_BELOW_REQUIRED` (HTTP 422). Finally, the free-file disclosure gate: a return still priced at `FREE` whose `free_file_eligible` is false may not pass review, and is rejected with `ERR_FREE_FILE_INELIGIBLE` (HTTP 422). On success the return moves to `READY_FOR_REVIEW` and its fees are recomputed one last time.

Review is not a one-way door. Reopening a `READY_FOR_REVIEW` return takes it back to `DRAFT`, and the revision loop between `DRAFT` and `READY_FOR_REVIEW` may cycle any number of times. The in-flight guard applies to reopening from any status: whenever a `PENDING` filing attempt exists for the return, the reopen is rejected with `ERR_FILING_IN_FLIGHT` — so a `SUBMITTED` return, whose latest attempt is always `PENDING` until the authority resolves it, fails this gate rather than any state check.

Filing transmits the return to the authority. The filer supplies a `transmission_payload_hash`, a client-computed hash of the transmitted payload that lets the system recognize resubmissions. Filing is allowed only from `READY_FOR_REVIEW` — filing an `AMENDED` return directly is explicitly forbidden and rejected with `ERR_INVALID_STATE`, since an amended return must pass through review again first — and its preconditions resolve in a fixed order: if refund transfer was elected, an `ACTIVE` agreement must exist, else `ERR_REFUND_TRANSFER_NOT_ACTIVE` (HTTP 409); no other filing attempt may be `PENDING`, else `ERR_FILING_IN_FLIGHT`; the amendment hold window of §3.7 must have expired, else `ERR_AMENDMENT_HOLD_ACTIVE` (HTTP 409); and if refund transfer was elected, the refund must cover the fees — `federal_refund_cents` must be at least `total_fees_due_cents`, checked against the fully computed total, else `ERR_REFUND_INSUFFICIENT_FOR_FEES` (HTTP 402). A successful filing moves the return `READY_FOR_REVIEW` → `SUBMITTED`, creates a `FilingAttempt` in `PENDING` outcome, and moves every `READY` state return to `FILED`. Each attempt is numbered: `attempt_sequence` is a 1-based, monotonically increasing sequence per return, assigned at creation in `created_at` order as one greater than the largest existing sequence for that return.

### 3.7. Authority Outcomes, Guided Correction, and Amendment

The authority's verdict arrives asynchronously as a `PlatformOperator`-injected callback naming a `filing_attempt_id`, an `outcome`, and, for rejections, a `rejection_code`; the targeted attempt must still be `PENDING`. An acceptance moves the attempt `PENDING` → `ACCEPTED`, stamps `resolved_at` from the logical clock, moves the parent return `SUBMITTED` → `ACCEPTED` (its terminal state for the original filing), and settles any `ACTIVE` refund-transfer agreement as §3.5 described.

A rejection moves the attempt `PENDING` → `REJECTED`, records the `rejection_code`, stamps `resolved_at`, moves the parent return `SUBMITTED` → `REJECTED`, and rolls every `FILED` state return back to `READY`. The rejection code is one of `R0000_SSN_MISMATCH`, `R0500_NAME_CONTROL`, `R1000_DUPLICATE_FILED`, `R2000_DEPENDENT_CLAIMED`, or `R3000_MATH_ERROR`, and each maps to a fixed guided-correction text stored on the attempt's `correction_hint`: an SSN mismatch yields "Verify the SSN exactly as printed on the Social Security card."; a name-control mismatch yields "Name control mismatch: check last-name spelling against SSA records."; a duplicate-filing yields "A return for this SSN was already accepted; amend instead of refiling."; a dependent-claimed yields "A dependent on this return was claimed elsewhere; review the dependent list."; and a math error yields "The authority recomputed a line; review the flagged worksheet totals."

Recovery is a loop, not a dead end. Reopening a `REJECTED` return takes it back to `DRAFT`, the filer corrects and re-submits through review, and each new filing creates a fresh attempt with the next `attempt_sequence`. A return that was accepted can instead be **amended**: amending requires at least one `ACCEPTED` filing attempt on the return and moves it `ACCEPTED` → `AMENDED`, reopening it for edits — forms may be added and removed, state returns reworked, snapshots imported. `ACCEPTED` remains terminal for the original filing; the amendment starts a new filing cycle that must again pass through review, and direct filing from `AMENDED` remains forbidden.

Re-filing after an acceptance is throttled by the **amendment hold**. When any filing attempt for the return previously resolved `ACCEPTED`, the system takes the most recent such attempt's `resolved_at` and rejects any new filing while the logical clock reads at or before `resolved_at` plus 24 hours. The boundary is closed: filing at exactly the 24-hour mark is still rejected with `ERR_AMENDMENT_HOLD_ACTIVE`, and only a clock reading strictly past the boundary — one second suffices — allows the filing through.

### 3.8. Accuracy Guarantee Claims

When the authority assesses a penalty or interest the filer attributes to a software miscalculation, the filer files an `AccuracyClaim` against the return, supplying a `claimed_error_amount_cents` that must be greater than zero (else `ERR_INVALID_CLAIM_AMOUNT`, HTTP 422). The claim requires the referenced return to have reached `ACCEPTED` at least once — its current status must be `ACCEPTED` or `AMENDED`; a claim against a return that never got there is rejected with `ERR_RETURN_NOT_FILED` (HTTP 409), a check evaluated before the amount check. New claims open in `FILED` status, with `reviewed_error_amount_cents` unset and `reimbursement_cents` at zero.

A `ClaimsAdjuster` then works the claim. Moving it `FILED` → `UNDER_REVIEW` requires the owning account to be enrolled in the guarantee program — `accuracy_guarantee_enrolled` must be true, else `ERR_GUARANTEE_NOT_ENROLLED` (HTTP 409). Adjudication supplies a `reviewed_error_amount_cents` (never negative, else `ERR_INVALID_CLAIM_AMOUNT`) and the outcome branches on how it compares to the claimed amount, with the reimbursement computed identically on every branch: the lesser of the reviewed and claimed amounts, then capped at the $1,000.00 per-return guarantee maximum — a claim landing exactly on the cap reimburses exactly the cap. A reviewed amount equal to the claimed amount (and positive) moves the claim `UNDER_REVIEW` → `APPROVED`. A reviewed amount strictly between zero and the claimed amount moves it `UNDER_REVIEW` → `PARTIALLY_APPROVED`. A reviewed amount of exactly zero moves it `UNDER_REVIEW` → `DENIED`, a terminal state, with `reimbursement_cents` set to zero.

A partially approved claim is not final: the adjuster may reopen it, moving `PARTIALLY_APPROVED` → `UNDER_REVIEW` provided the claim has never reached `PAID`, and the reopening resets `reimbursement_cents` to zero pending the new adjudication — the review and partial-approval states may loop until payment locks the claim. Payment moves a claim from `APPROVED` or `PARTIALLY_APPROVED` to the terminal `PAID` state with no further amount changes. Claims remain readable to the filer and the adjuster throughout.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; modifications, actions, and state transitions return HTTP 200. All endpoints live under the `/tax` prefix and require the headers of §2.1. The table below is a summary only — request fields, computed effects, and guard conditions for each operation are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/tax/_clock/set_current_utc` | Set the server's logical clock (test-driving) | PlatformOperator |
| POST | `/tax/_authority/filing-callback` | Simulated authority callback resolving a pending filing attempt | PlatformOperator |
| POST | `/tax/_tiers/seed` | Register a product tier catalog row | PlatformOperator |
| POST | `/tax/_forms/seed` | Register a form specification catalog row | PlatformOperator |
| POST | `/tax/accounts/{id}/suspend` | Suspend a taxpayer account (one-way) | PlatformOperator |
| POST | `/tax/accounts` | Register a taxpayer account (bootstrap) | Taxpayer |
| GET | `/tax/accounts/{id}` | Fetch an account | Taxpayer, PlatformOperator, ClaimsAdjuster |
| GET | `/tax/tiers` | List product tiers | Taxpayer, PlatformOperator, ClaimsAdjuster |
| GET | `/tax/form-specs` | List form specifications | Taxpayer, PlatformOperator, ClaimsAdjuster |
| POST | `/tax/accounts/{id}/prior-year-snapshots` | Register a prior-year snapshot for carryforward import | Taxpayer |
| GET | `/tax/accounts/{id}/prior-year-snapshots` | List snapshots for an account | Taxpayer |
| GET | `/tax/accounts/{id}/prior-year-snapshots/{snapshotId}` | Fetch a single snapshot | Taxpayer |
| POST | `/tax/accounts/{id}/prior-year-snapshots/{snapshotId}/import` | Import carryforward items into a target return | Taxpayer |
| POST | `/tax/accounts/{id}/returns` | Start a new tax return | Taxpayer |
| GET | `/tax/accounts/{id}/returns` | List returns for an account | Taxpayer, ClaimsAdjuster |
| GET | `/tax/returns/{id}` | Fetch a return with all computed fields | Taxpayer, ClaimsAdjuster, PlatformOperator |
| POST | `/tax/returns/{id}/select-tier` | Voluntary paid-tier selection (upgrade only) | Taxpayer |
| POST | `/tax/returns/{id}/forms` | Add a form to a return (question-flow answer) | Taxpayer |
| GET | `/tax/returns/{id}/forms` | List forms on a return, including removed rows | Taxpayer, ClaimsAdjuster |
| POST | `/tax/returns/{id}/forms/{formId}/remove` | Remove (soft-delete) a form from a return | Taxpayer |
| POST | `/tax/returns/{id}/submit-review` | Submit the return for pre-filing review | Taxpayer |
| POST | `/tax/returns/{id}/reopen` | Reopen a return from review-ready or rejected back to draft | Taxpayer |
| POST | `/tax/returns/{id}/file` | E-file the return, creating a filing attempt | Taxpayer |
| POST | `/tax/returns/{id}/amend` | Amend an accepted return | Taxpayer |
| GET | `/tax/returns/{id}/filing-attempts` | List filing attempts for a return | Taxpayer, ClaimsAdjuster, PlatformOperator |
| GET | `/tax/returns/{id}/upgrade-prompts` | List upgrade prompts for a return | Taxpayer |
| POST | `/tax/returns/{id}/upgrade-prompts/{promptId}/acknowledge` | Accept the tier upgrade and price change | Taxpayer |
| POST | `/tax/returns/{id}/upgrade-prompts/{promptId}/decline` | Decline the upgrade, downgrading offending manual forms | Taxpayer |
| POST | `/tax/returns/{id}/state-returns` | Add a state return add-on | Taxpayer |
| GET | `/tax/returns/{id}/state-returns` | List state returns for a return | Taxpayer, ClaimsAdjuster |
| POST | `/tax/returns/{id}/state-returns/{stateReturnId}/ready` | Mark a state return ready for filing | Taxpayer |
| POST | `/tax/returns/{id}/state-returns/{stateReturnId}/remove` | Remove a state return add-on | Taxpayer |
| POST | `/tax/returns/{id}/refund-transfer` | Create a refund-transfer agreement | Taxpayer |
| GET | `/tax/returns/{id}/refund-transfer` | List refund-transfer agreements for a return | Taxpayer, PlatformOperator |
| POST | `/tax/returns/{id}/refund-transfer/accept-disclosure` | Accept the bank-partner disclosure, activating the agreement | Taxpayer |
| POST | `/tax/returns/{id}/refund-transfer/void` | Void the refund-transfer agreement | Taxpayer |
| POST | `/tax/returns/{id}/claims` | File a calculation-accuracy guarantee claim | Taxpayer |
| GET | `/tax/returns/{id}/claims` | List claims for a return | Taxpayer, ClaimsAdjuster |
| POST | `/tax/claims/{claimId}/start-review` | Move a claim into review | ClaimsAdjuster |
| POST | `/tax/claims/{claimId}/adjudicate` | Adjudicate a claim with a reviewed error amount | ClaimsAdjuster |
| POST | `/tax/claims/{claimId}/reopen-review` | Reopen a partially approved claim for re-adjudication | ClaimsAdjuster |
| POST | `/tax/claims/{claimId}/pay` | Pay an approved or partially approved claim | ClaimsAdjuster |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status reference.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_FORM_NOT_FOUND` | 404 |
| `ERR_PROMPT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 |
| `ERR_STATE_RETURN_NOT_FOUND` | 404 |
| `ERR_FORM_SPEC_NOT_FOUND` | 404 |
| `ERR_BANK_PARTNER_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_ALLOCATION_EXCEEDS_BASE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RETURN_NOT_EDITABLE` | 409 |
| `ERR_UPGRADE_ACK_REQUIRED` | 409 |
| `ERR_FREE_FILE_INELIGIBLE` | 422 |
| `ERR_TIER_BELOW_REQUIRED` | 422 |
| `ERR_DOWNGRADE_WOULD_LEAVE_GAP` | 409 |
| `ERR_REFUND_TRANSFER_NOT_ACTIVE` | 409 |
| `ERR_REFUND_INSUFFICIENT_FOR_FEES` | 402 |
| `ERR_DUPLICATE_FORM_ON_RETURN` | 409 |
| `ERR_DUPLICATE_STATE_RETURN` | 409 |
| `ERR_RESIDENCY_OVERLAP` | 409 |
| `ERR_AMENDMENT_HOLD_ACTIVE` | 409 |
| `ERR_FILING_IN_FLIGHT` | 409 |
| `ERR_INVALID_CLAIM_AMOUNT` | 422 |
| `ERR_GUARANTEE_NOT_ENROLLED` | 409 |
| `ERR_RETURN_NOT_FILED` | 409 |
| `ERR_SNAPSHOT_YEAR_INVALID` | 422 |
| `ERR_SNAPSHOT_SUPERSEDED` | 422 |
| `ERR_NO_FORMS_ON_RETURN` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
