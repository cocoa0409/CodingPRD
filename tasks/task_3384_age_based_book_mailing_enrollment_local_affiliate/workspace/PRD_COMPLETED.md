# Age-Based Book Mailing API — Product Requirements Document

## 1. Introduction

Local affiliates of a childhood book-mailing program carry a dual burden: they must enroll every eligible under-five child in their territory, and they must raise the local share of what those books cost to print and post. State and provincial programs offset part of that cost, publishers grant volume pricing, and a central platform keeps the monthly machinery honest — deciding which child gets which book, which affiliate is genuinely operating, and who owes what after the mail goes out. This document specifies the API that coordinates that machinery.

The system governs the full enrollment lifecycle: a child registers with a birth date and a mailing address, receives an age-band-appropriate book every month from registration through the fifth birthday, and eventually graduates, moves, or falls off the mailing list when mail comes back undeliverable. Around that lifecycle sit partner agreements covering defined postal geographies, a monthly title-selection process run by an advisory committee under segregation of duties, print ordering against a finite press capacity, mailing-wave manifestation with duplicate prevention, and per-affiliate invoicing that splits each book's cost between state funding and local fundraising. All resources are served under the `/library` prefix. A logical clock — not the wall clock — decides what "this month" means, so that schedulers, sweeps, and eligibility rules all agree.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` specifies their operational capacity. The system recognizes exactly six roles: `PlatformAdmin`, `StateProgramOfficer`, `AffiliateCoordinator`, `AdvisoryCommitteeMember`, `PublisherOps`, and `MailOps`. A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN`.

Two roles are entity-backed. When `X-User-Role` is `AffiliateCoordinator`, `X-User-ID` is the `id` of the `Affiliate` that coordinator runs; ownership checks on any resource that references an affiliate — children, address changes, population stats, invoice payment and dispute, and affiliate-scoped reads — compare the resource's affiliate reference to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `StateProgramOfficer`, `X-User-ID` is the `id` of the `StateProgram` the officer serves; the officer may act only on agreements whose affiliate belongs to that program, again with `ERR_FORBIDDEN` on mismatch. The remaining four roles — `PlatformAdmin`, `AdvisoryCommitteeMember`, `PublisherOps`, and `MailOps` — carry an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `proposed_by` or `approved_by` on a selection) but never compares it against an entity's `id`.

Read access is broad: every role may call every retrieval and list endpoint, though an `AffiliateCoordinator`'s list reads for children, address changes, population stats, invoices, and penetration reporting are scoped to their own affiliate. Single-resource retrievals carry no coordinator scope — any authenticated role may read any single resource by id, including one owned by another affiliate. Write access is narrow and follows segregation of duties — no single role can enroll a child, approve its own book selection, and print the order.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the wall clock rather than the logical clock of §2.4.
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

List endpoints are paginated through query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, list endpoints return resources sorted by creation timestamp in ascending order, with timestamp ties broken by creation order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock and Calendar-Month Semantics

The server maintains a logical clock that is fully decoupled from wall-clock time. At startup the logical clock reads exactly `2026-09-01T00:00:00Z`, and before any client advances it the clock continues to read exactly that instant — it never silently falls back to real time. An admin-only test-driving capability advances the logical clock to a supplied `current_utc` instant — adopted unconditionally, with no requirement that it be later than the current reading — and, in the same action, runs the due-date sweep described in §3.2 and §3.3; its response reports the new `current_utc` (echoing the supplied string verbatim) together with `graduated_child_ids` and `expired_agreement_ids`, the two lists of entities the sweep touched.

Calendar months are first-class values throughout the system and are always rendered as `YYYY-MM` strings. Month arithmetic — adding fifty-nine months to a birth month, stepping one calendar month back from a mailing month, or walking a trailing twelve-month window — is calendar-month arithmetic, not day arithmetic. A child's age at any reference month is measured in whole months: take the reference month's year times twelve plus its month number, subtract the birth date's year times twelve plus its month number, and ignore the day of the month entirely. Two children born on the 2nd and the 28th of the same month are always the same age for every rule in this system.

### 2.5. Common Resource Properties

Every resource in the system — state programs, affiliates, agreements, population stats, children, address changes, titles, selections, print orders, waves, mailing items, and invoices alike — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created, stamped from the logical clock of §2.4.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any modification of the resource, also stamped from the logical clock.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments on every modification, usable for optimistic concurrency control.

These fields are read-only to clients. A request body that supplies `id`, `version`, or any other system or computed field (for instance `enrolled_count` on an affiliate) is malformed and rejected under the body well-formedness check of §2.8.

### 2.6. Money in Integer Cents and Rounding Discipline

All monetary values are integer cents; there are no fractional cents and no floating-point money anywhere in the system. Three rounding rules govern every calculation, and each names its method explicitly. The reprint discount on a print order rounds **half up** to a whole cent. The state-share split on an invoice rounds **half up per line** — each billable item's share is rounded before any summation, and only then are the lines totaled. The effective per-unit price recovered from a confirmed print order uses **integer floor division** of the order's total by its quantity. A funding share is expressed in basis points as `funding_share_bp`, an integer from 0 to 10000 inclusive, where 10000 basis points means the program funds the entire capped per-book cost.

### 2.7. Optimistic Concurrency Control on Agreement Creation

Exactly one write in the system is protected by optimistic concurrency control: creating a partner agreement against an affiliate. The request must carry `expected_affiliate_version`, a non-optional field holding the affiliate `version` the client last observed. If that value does not match the affiliate's current `version` — because another writer has advanced the affiliate since, for example by creating an agreement of their own — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here take no version field at all.

### 2.8. Validation Ordering and Nested Resource Retrieval

Every request is evaluated against an ordered validation cascade. When a request violates several rules at once, the earliest applicable check in this order produces the error, and later checks are not consulted:

1. **Authentication** — `X-User-ID` and `X-User-Role` are present and the role is recognized, else `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the caller's role appears in the endpoint's authorized list, else `ERR_FORBIDDEN`.
3. **Path existence** — identifiers in the URL are resolved strictly left to right; the first identifier that does not exist yields that entity's specific 404. The entity-specific not-found codes are `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_AFFILIATE_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_CHILD_NOT_FOUND`, `ERR_ADDRESS_CHANGE_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_SELECTION_NOT_FOUND`, `ERR_PRINT_ORDER_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND`. A request for an address change under a non-existent child therefore fails with `ERR_CHILD_NOT_FOUND` before the address change is ever sought.
4. **Body well-formedness** — required fields are present (required string fields must be non-empty, and an address `postal_code` must contain non-whitespace), types are correct, enum values are in range, `postal_prefixes` is a non-empty array of two-to-five-character uppercase alphanumeric strings, month strings match the `YYYY-MM` shape with a month number between 01 and 12, and no unknown, system, or computed fields were supplied; any violation is `ERR_INVALID_REQUEST`.
5. **Entity-backed ownership** — the coordinator and officer scoping rules of §2.1, else `ERR_FORBIDDEN`.
6. **Optimistic concurrency** — the stale-version check of §2.7, else `ERR_STALE_VERSION`.
7. **State preconditions** — the target resource's state permits the requested transition, else `ERR_INVALID_STATE`.
8. **Segregation of duties** — the selection approver differs from its proposer, else `ERR_SELF_APPROVAL_FORBIDDEN`.
9. **Scalar temporal rules** — birth date not in the future, child young enough at registration, selection and wave months not in the past, agreement window strictly positive; these surface as `ERR_BIRTH_DATE_IN_FUTURE`, `ERR_CHILD_AGE_INELIGIBLE`, `ERR_SELECTION_MONTH_PAST`, `ERR_WAVE_MONTH_PAST`, or `ERR_AGREEMENT_WINDOW_INVALID`.
10. **Uniqueness and duplicate rules** — `ERR_DUPLICATE_REGISTRATION`, `ERR_SELECTION_EXISTS`, `ERR_POPULATION_YEAR_DUPLICATE`, `ERR_WAVE_MONTH_DUPLICATE`, and `ERR_SELECTION_ALREADY_SUPPLIED`.
11. **Foreign keys and their dependent rules** — body-referenced ids must exist (`title_id`, `selection_id`, `state_program_id`, `affiliate_id`), followed by the rules that depend on those references: affiliate operability, address coverage, title availability windows, agreement geography overlap, and print-order submission's requirement that the referenced selection be `APPROVED` (§3.6) (`ERR_AFFILIATE_NOT_OPERATIVE`, `ERR_ADDRESS_NOT_COVERED`, `ERR_TITLE_UNAVAILABLE_MONTH`, `ERR_AGREEMENT_GEOGRAPHY_OVERLAP`).
12. **Capacity, inventory, and fiscal gates** — press capacity, per-title stock at manifest, selection completeness at manifest, and credit-memo bounds: `ERR_PRESS_CAPACITY_EXCEEDED`, `ERR_INVENTORY_SHORTFALL`, `ERR_MANIFEST_SELECTIONS_INCOMPLETE`, and `ERR_CREDIT_EXCEEDS_GROSS`.

### 2.9. Derived Counters and Inventory Reconciliation

Two derived quantities are computed from the live store whenever the owning resource is read, so they are always fully reconciled. An affiliate's `enrolled_count` is the count of its children whose `enrollment_status` is `ACTIVE` or `UNDELIVERABLE_HOLD`; children who are `GRADUATED`, `UNENROLLED`, or `TRANSFERRED_OUT` never count. Every event that can move a child across that boundary — registration, return-driven unenrollment, transfer in or out, and the graduation sweep — is therefore reflected in the value immediately. A title's `stock_on_hand` is the sum of quantities over confirmed print orders whose selection names that title, minus the count of mailing items manifested from those selections; print-order confirmations and wave manifests move it, and the manifest's pre-checks guarantee it never goes negative. Both values are exposed as ordinary fields on their owning resources, so readers never recompute them themselves.

## 3. Business Logic & Workflows

### 3.1. State Programs and Local Affiliates

A `PlatformAdmin` begins by standing up the funding layer. Creating a state or provincial program takes a `state_code` — unique across all programs by exact, case-sensitive comparison, with a duplicate rejected as `ERR_INVALID_REQUEST` — a display `name`, the program's `funding_share_bp`, and optionally `max_state_share_per_book_cents`, the per-book cost cap against which the state share is computed; when omitted, the cap defaults to 300 cents, and when supplied it must be a non-negative integer.

With a program in place, the same administrator creates local affiliates. An affiliate is defined by a `name`, the `state_program_id` of the program it operates under (a reference that must resolve, else `ERR_STATE_PROGRAM_NOT_FOUND`), a non-empty `postal_prefixes` array declaring its covered geography, and a `contact_email` for its coordinator (any non-empty string; no address-format validation is applied). A freshly created affiliate starts with `enrolled_count` at zero and is **not** operative. Operability is a derived flag, `operative`, that turns true only when an `ACTIVE` agreement fully covers the current logical month — meaning the agreement's `effective_from` falls on or before the first day of that month and its `effective_to` falls on or after the first day of the following month. Partial-month coverage does not make an affiliate operative, and operability gates child registration and manifest eligibility alike.

Each affiliate also maintains a population series. A coordinator (for their own affiliate) or a `PlatformAdmin` records an `eligible_population` estimate — a positive integer — tagged with an `effective_year` between 2000 and 2100. One stat per affiliate per year: a second estimate for a year that already has one is rejected with `ERR_POPULATION_YEAR_DUPLICATE`. These stats feed the penetration reporting of §3.8. Affiliates can be listed with `state_program_id` and `name` filters (both exact-match); population stats are listed per affiliate.

### 3.2. Partner Agreements and Geographic Coverage

An affiliate becomes real through a partner agreement. A coordinator (for their own affiliate) or a `PlatformAdmin` proposes one by supplying `effective_from`, `effective_to`, and `local_fundraising_commitment_cents` — the annual local-share fundraising commitment, which may be zero but never negative — together with the concurrency token `expected_affiliate_version` described in §2.7. The two window bounds are ISO 8601 datetimes (a value without an offset is read as UTC) and are stored and echoed verbatim as supplied. The coverage window is half-open: it runs from `effective_from` inclusive to `effective_to` exclusive, and `effective_to` must be strictly after `effective_from` or the request fails with `ERR_AGREEMENT_WINDOW_INVALID`. A new agreement starts in `PENDING_APPROVAL` with `decided_by` null until a decision, and creating it increments the owning affiliate's `version` by one — which is precisely what makes a second writer's stale `expected_affiliate_version` detectable.

Approval belongs to the `StateProgramOfficer`, and only the officer whose program matches the affiliate's `state_program_id` may act (else `ERR_FORBIDDEN`). Approval requires the agreement to still be `PENDING_APPROVAL` (else `ERR_INVALID_STATE`) and then enforces the geography rule: no other `PENDING_APPROVAL` or `ACTIVE` agreement whose postal-prefix set intersects this affiliate's `postal_prefixes` may have a window overlapping this one, where overlap is judged on the half-open intervals — two windows that merely touch, one's `effective_to` equal to the other's `effective_from`, do **not** overlap and are allowed. A violation is rejected with `ERR_AGREEMENT_GEOGRAPHY_OVERLAP`. Because an affiliate's prefix set always intersects itself, this rule also guarantees an affiliate never holds two `ACTIVE` agreements at once. On approval the agreement becomes `ACTIVE`, `decided_by` records the officer's `X-User-ID`, and the affiliate's `operative` flag is recomputed — flipping true once the current logical month is fully covered. Rejection is the officer's other option against a `PENDING_APPROVAL` agreement; it moves the agreement to `REJECTED`, records `decided_by`, and is terminal — a rejected agreement cannot be resubmitted, so the parties create a fresh one instead.

Agreements age out on their own. When the logical clock advances to a date on or after an agreement's `effective_to`, the sweep moves that agreement from `ACTIVE` to `EXPIRED` and recomputes the affiliate's `operative`, which may drop to false and thereby freeze new registrations until a successor agreement is approved. The agreements of an affiliate can be listed with a `status` filter.

### 3.3. Child Registration and the Enrollment Lifecycle

Registration is the coordinator's daily work: an `AffiliateCoordinator` registers a child into their own affiliate by submitting `affiliate_id`, the child's `full_name` and `family_name`, the `birth_date`, and a `mailing_address` object with `line1`, `city`, `region`, `postal_code`, and `country`. The `birth_date` is accepted as an ISO 8601 date or datetime string and echoed verbatim; every rule that compares it (the future-birth rule and duplicate prevention alike) uses its calendar date value. The system derives three fields at creation: `postal_prefix`, the first three characters of the uppercased postal code; `registered_month`, the logical month of registration; and `expected_final_mailing_month`, the birth month plus fifty-nine months — the last month a book can mail to this child. A new child starts `ACTIVE` with `consecutive_returns` at zero and `unenroll_reason` and `transfer_source_child_id` null, and the affiliate's `enrolled_count` increases by one.

Registration is guarded by five business rules, each with its own rejection. The `birth_date` must lie strictly before the current logical date — a birth date on or after today is `ERR_BIRTH_DATE_IN_FUTURE`. The child's age in whole months at the registration month must be at most 59; a child who is already 60 months or older in that month is too old for the program and is rejected with `ERR_CHILD_AGE_INELIGIBLE` — note the split: future births and over-age children are different errors. The registering affiliate must be operative in the current logical month, else `ERR_AFFILIATE_NOT_OPERATIVE`. The child's derived `postal_prefix` must appear in the affiliate's `postal_prefixes`, else `ERR_ADDRESS_NOT_COVERED`. Finally, duplicate prevention: no non-terminal child in the same affiliate may share the same birth date, the same postal prefix, and the same family name compared case-insensitively — a match is `ERR_DUPLICATE_REGISTRATION`, while children in the terminal states `GRADUATED`, `UNENROLLED`, or `TRANSFERRED_OUT` never block a new registration. Children can be listed with `affiliate_id`, `enrollment_status`, and `transfer_source_child_id` filters, the last of which surfaces the enrollment a transfer created.

Graduation is automatic and age-driven. When the sweep finds the current logical month has moved beyond a child's `expected_final_mailing_month`, the child becomes `GRADUATED` and the affiliate's `enrolled_count` is recomputed. Graduation applies equally to `ACTIVE` children and to children sitting in `UNDELIVERABLE_HOLD` — a hold never defers a birthday.

### 3.4. Address Changes, Transfers, and Undeliverable Mail

Families move, and mail comes back. Both flows converge on the child's enrollment status. A coordinator submits an address change for a child in their own affiliate with a `new_address` of the same shape as the registration address; the system derives `new_postal_prefix` from it. Submission requires the child to be non-terminal — `ACTIVE` or `UNDELIVERABLE_HOLD` — else `ERR_INVALID_STATE`, and the request starts life `PENDING` with `decided_by` and `resulting_child_id` null. A child's address changes can be listed with a `status` filter.

Decision belongs to the coordinator who owns the child's current (source) affiliate, acting on a still-`PENDING` request; the decision payload carries an `outcome` of `APPROVE` or `REJECT` — exactly those uppercase tokens, anything else is `ERR_INVALID_REQUEST` — and `decided_by` records who acted. Approval first re-validates that the child is still non-terminal at decision time; a child that has reached a terminal state since submission fails with `ERR_INVALID_STATE`. Approval then forks into exactly three branches, evaluated in this order. If `new_postal_prefix` falls inside the child's current affiliate coverage, the change is `APPLIED_IN_AREA`: the child's `mailing_address` is replaced with `new_address`, `postal_prefix` is recomputed, and the address revalidation returns the child to `ACTIVE` with `consecutive_returns` reset to zero — this is the way a held child clears its hold. If the new prefix is not covered by the current affiliate but is covered by a different operative affiliate, the change is `APPLIED_TRANSFER`: the source child becomes `TRANSFERRED_OUT`, and a brand-new child enrollment is auto-created on the target affiliate carrying the same `full_name`, `family_name`, and `birth_date`, the new `mailing_address`, a `registered_month` of the current logical month, `transfer_source_child_id` pointing back at the source child, `ACTIVE` status, and a fresh zero `consecutive_returns`; the address change's `resulting_child_id` records the new enrollment, the source affiliate's `enrolled_count` drops by one and the target's rises by one, so global enrollment is conserved. The target is chosen by a selector over every affiliate whose `postal_prefixes` contain `new_postal_prefix` and that is operative in the current logical month, ranked by the earliest covering agreement's `effective_from` with ties broken by agreement `created_at` ascending and any remaining ties by agreement creation order. If that selector finds nobody, the third branch applies: `APPLIED_UNENROLLED` moves the child to `UNENROLLED` with `unenroll_reason` set to `MOVED_OUT_OF_AREA`, `resulting_child_id` stays null, and the affiliate count is recomputed. A hold never blocks a move — children in `UNDELIVERABLE_HOLD` follow the transfer and moved-out branches exactly as `ACTIVE` children do. Rejection is the quiet branch: the change becomes `REJECTED` and the child is untouched — status, address, and `consecutive_returns` all unchanged.

Undeliverable mail is the other pressure. `MailOps` records a return against a mailed item, allowed only while the item is `MAILED` and its wave is still `MANIFESTED` rather than `RECONCILED` (else `ERR_INVALID_STATE`). The item becomes `RETURNED_UNDELIVERABLE`, the wave's `returned_item_count` increases by one, and the child's `consecutive_returns` increases by one. The first consecutive return slides the child from `ACTIVE` into `UNDELIVERABLE_HOLD` — and a held child **remains manifest-eligible**, so books keep mailing while the family sorts out its address. When the counter reaches two — the program's auto-unenrollment threshold — the same return that raised it fires hold-then-unenroll atomically, netting out at `UNENROLLED` with `unenroll_reason` set to `UNDELIVERABLE` and the affiliate's `enrolled_count` recomputed; this holds whether the child was `ACTIVE` or already in `UNDELIVERABLE_HOLD` when that second return landed. A return recorded for a child who has already reached a terminal status still transitions the item, increments the wave's `returned_item_count`, and increments `consecutive_returns`, but leaves the child's terminal status unchanged.

### 3.5. Titles, Selections, and Committee Approval

The book side of the system starts with the catalog. A `PlatformAdmin` catalogs each title with its `title_name`, `author`, the `age_band` it suits, and an availability window from `available_from_month` through `available_until_month`, both inclusive, with the end never before the start. The five bands partition the program's age range: `INFANT` for 0–11 months, `TODDLER` for 12–23, `TWO` for 24–35, `THREE` for 36–47, and `FOUR` for 48–59. A cataloged title's `stock_on_hand` starts at zero and is thereafter maintained by §2.9's reconciliation.

Each mailing month needs one selection per band, proposed by an `AdvisoryCommitteeMember` with `mailing_month`, `age_band`, and a `title_id` that must resolve (else `ERR_TITLE_NOT_FOUND`). Three rules guard the proposal: the `mailing_month` must not be earlier than the current logical month (else `ERR_SELECTION_MONTH_PAST`); the pair of month and band must be unique, since a second selection for a slot that already has one is `ERR_SELECTION_EXISTS`; and the month must fall inside the named title's inclusive availability window, else `ERR_TITLE_UNAVAILABLE_MONTH`. The proposal lands in `PROPOSED` with `proposed_by` recording the proposer's `X-User-ID` and `approved_by` null until approval.

Approval enforces segregation of duties: a committee member approves a `PROPOSED` selection (else `ERR_INVALID_STATE`), but the approver's `X-User-ID` must differ from `proposed_by` — self-approval is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. Approval moves the selection to `APPROVED` and records `approved_by`. The cycle is reworkable: reopening an `APPROVED` selection — with an optional `reason`, which is accepted but not persisted — sends it back to `PROPOSED` and clears `approved_by`. That door closes permanently once a print order for the selection has been confirmed: confirmation locks the selection into the terminal `LOCKED` state, reopening a locked selection fails with `ERR_INVALID_STATE`, and any further print order against it is refused with `ERR_SELECTION_ALREADY_SUPPLIED`. Selections can be listed with `mailing_month`, `age_band`, `title_id`, and `status` filters.

### 3.6. Print Orders, Volume Pricing, and Press Capacity

`PublisherOps` turns approved selections into physical stock. Submitting a print order takes a `selection_id` (which must exist, else `ERR_SELECTION_NOT_FOUND`), a positive `quantity`, and an optional `is_reprint` flag — true when reprinting a title that was previously printed for an earlier month, defaulting to false. Submission also requires the referenced selection to be `APPROVED`; the guard against an existing `CONFIRMED` order for the selection is evaluated first (so a locked selection fails with `ERR_SELECTION_ALREADY_SUPPLIED`, per §3.5), and only then does the approval-state rule apply (a still-`PROPOSED` selection fails with `ERR_INVALID_STATE`). The order's `production_month` is derived as the selection's mailing month minus one calendar month. A submitted order sits in `SUBMITTED` with `unit_cents`, `plate_fee_cents`, and `total_cents` all null; those are priced only at confirmation. Orders can be listed with `selection_id` and `status` filters.

Confirmation is where the money and the constraints live, moving the order from `SUBMITTED` to `CONFIRMED`, and its guards are evaluated in order: the order must be `SUBMITTED` and its referenced selection `APPROVED` (else `ERR_INVALID_STATE`); no other `CONFIRMED` order may exist for the same selection (else `ERR_SELECTION_ALREADY_SUPPLIED`); and the press must have room — the sum of `quantity` over already-confirmed orders sharing this `production_month`, plus this order's quantity, must not exceed the monthly press capacity of 400,000 units, with exactly 400,000 permitted (else `ERR_PRESS_CAPACITY_EXCEEDED`). Submitted-but-unconfirmed orders consume no capacity.

Pricing locks at confirmation on a volume tier, with each tier's lower bound inclusive: 210 cents per unit below 5,000; 185 cents from 5,000; 160 cents from 20,000; and 140 cents from 50,000. A reprint pays nine-tenths of its tier price, rounded half up to a whole cent. The plate fee is 25,000 cents, waived entirely when the quantity is at least 20,000 or the order is a reprint. The confirmed `total_cents` is the quantity times the effective unit price plus the plate fee, and `unit_cents` records the effective per-unit figure. Confirmation then propagates: the selection moves to `LOCKED`, and the title's `stock_on_hand` increases by the ordered quantity.

### 3.7. Mailing Waves: Scheduling, Manifest, and Reconciliation

`MailOps` drives the monthly cycle. Scheduling a wave takes only a `mailing_month`, which must be unique across waves (else `ERR_WAVE_MONTH_DUPLICATE`) and must not be earlier than the current logical month (else `ERR_WAVE_MONTH_PAST`). A new wave is `SCHEDULED` with `manifested_item_count` and `returned_item_count` at zero.

Manifesting turns the wave into per-child mail pieces, and it is gated three times before anything is created: the wave must be `SCHEDULED` (else `ERR_INVALID_STATE`); all five age bands must have a `LOCKED` selection for the wave's month (else `ERR_MANIFEST_SELECTIONS_INCOMPLETE`); and demand is aggregated per title — for every selected title, its `stock_on_hand` must be at least the summed demand of every band whose locked selection names that title (a band's demand being the count of eligible children falling into the band) — else `ERR_INVENTORY_SHORTFALL`. A child is eligible for a wave month only when all five of the following hold: the child's `enrollment_status` is `ACTIVE` or `UNDELIVERABLE_HOLD`; the child's `registered_month` is strictly earlier than the wave month, so same-month registrants wait for the next wave; the child's age in whole months at the wave month is at most 59 — the month a child turns 60 months, the birthday month itself, mails nothing, and a negative age (which registration's birth-date rule makes unreachable) would mail nothing either; the child's affiliate is operative for the wave month under §3.1's full-coverage rule; and no mailing item already exists for that child and month, since the pair of child and month is unique across items and duplicates are prevented outright.

For each eligible child — processed in the order the children were registered — the manifest creates one mailing item in `MAILED` status, carrying the `wave_id`, the denormalized `mailing_month`, the `child_id`, the `affiliate_id` denormalized from the child for later invoice grouping, the `selection_id` of that month's locked selection for the child's band, and the computed `age_band`. An item's `billable` flag is true while the item is `MAILED` or `DELIVERED` and false once it comes back `RETURNED_UNDELIVERABLE`. Manifesting debits each selected title's `stock_on_hand` by its band's manifested count, sets the wave's `manifested_item_count` to the total pieces created, and moves the wave to `MANIFESTED`. Items can be listed with `wave_id`, `child_id`, `selection_id`, `affiliate_id`, and `status` filters.

Reconciliation closes the wave. Allowed only from `MANIFESTED` (else `ERR_INVALID_STATE`), it assumes the postal system succeeded wherever it was not told otherwise: every item still `MAILED` transitions to `DELIVERED`. Then the billing run of §3.8 creates one draft invoice per affiliate with at least one billable item — an affiliate whose items all came back undeliverable receives no invoice at all — and the wave settles into its terminal `RECONCILED` state.

### 3.8. Invoicing, Cost Sharing, Disputes, and Penetration Reporting

Each reconciliation mints `AffiliateInvoice` records in `DRAFT`, one per affiliate per wave, keyed by `affiliate_id` and `wave_id` (unique together) with `billing_month` denormalized from the wave. The invoice's `item_count` is its number of billable items. Money starts from the per-item book cost: take the item's selection, find its single confirmed print order, divide that order's `total_cents` by its `quantity` using integer floor division to get the effective order unit, and add the 35-cent per-book handling charge. Then `gross_cents` is the sum of per-item costs over the invoice's billable items.

The state/local split follows the pinned `PER_LINE` variant, which is the variant recorded in `pricing_variant` on every issued invoice. For each billable item, the capped cost is the lesser of the item cost and the program's `max_state_share_per_book_cents`; the state line is that capped cost times the program's `funding_share_bp` divided by 10,000, rounded half up to a whole cent; and the local line is the item cost minus the state line. `state_share_cents` is the sum of the state lines and `local_share_cents` is the sum of the local lines — equivalently `gross_cents` minus `state_share_cents` — because the rounding order is pinned: round each line first, then sum. An `AGGREGATE` variant, which rounds once over the summed capped amounts instead, exists for reporting and analytics comparison only and is never used on issued invoices; because per-line remainders accumulate differently, the two variants can differ by several cents on identical items. A fresh invoice's `credit_memo_cents` is zero.

From `DRAFT`, a `PlatformAdmin` issues the invoice, moving it to `ISSUED`. Payment is the coordinator's act on their own affiliate's invoice (else `ERR_FORBIDDEN`) and moves the invoice to `PAID` from either `ISSUED` or `ADJUSTED`. Disputes form a cycle with role-split outcomes. A coordinator opens a dispute from `ISSUED` with the `outcome` of `OPEN` — the open outcome is coordinator-only — landing the invoice in `DISPUTED`. Resolution belongs to `PlatformAdmin` alone (else `ERR_FORBIDDEN`) and takes two forms, selected by `outcome`: `RESOLVE_OVERRULED` returns the invoice to `ISSUED` unchanged, ready to be paid or disputed again; `RESOLVE_UPHELD` carries a `credit_amount_cents` that must be greater than zero and no more than the invoice's `gross_cents` — a missing, non-positive, or over-gross credit is `ERR_CREDIT_EXCEEDS_GROSS` — and moves the invoice to `ADJUSTED`. Any other `outcome` token is `ERR_INVALID_REQUEST`, and `credit_amount_cents`, when supplied, must be an integer and is consulted only by `RESOLVE_UPHELD`. On an upheld resolution: `credit_memo_cents` records the credit, `local_share_cents` becomes `gross_cents` minus `state_share_cents` minus the credit, and the invariant that `gross_cents` equals `state_share_cents` plus `local_share_cents` plus `credit_memo_cents` holds thereafter. The state share is never credited; credits come out of the local share only. Invoices can be listed with `affiliate_id`, `wave_id`, and `status` filters.

Finally, every affiliate's reach is measurable. The penetration report for a month — given as the optional `month` query parameter, defaulting to the current logical month; any well-formed month is accepted, and a malformed one is `ERR_INVALID_REQUEST` — first selects the population baseline: the affiliate's stat with the greatest `effective_year` not later than the report month's year, falling back to the stat with the smallest `effective_year` when no year qualifies, with ties impossible because year is unique per affiliate; if the affiliate has no stats at all, `eligible_population` is zero, `population_stat_year` is null, and both penetration rates are null. The report then carries two variants side by side. The snapshot numerator is the live `enrolled_count` — children currently `ACTIVE` or `UNDELIVERABLE_HOLD`, regardless of which month was requested — and `penetration_snapshot_bp` is that count times 10,000 divided by `eligible_population`, rounded half up, when the population is positive, else null. The trailing-twelve numerator, `trailing_12_unique_children`, counts distinct children with at least one mailing item of any status whose `mailing_month` falls inside the inclusive twelve-month window from eleven months before the report month through the report month itself — including children who have since graduated, transferred, or unenrolled — and `penetration_trailing_12_bp` is computed from it the same way. The two diverge whenever a served child left the program within the window. The response body reports `affiliate_id`, `month`, `enrolled_count`, `eligible_population`, `population_stat_year`, `penetration_snapshot_bp`, `trailing_12_unique_children`, and `penetration_trailing_12_bp`.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource, act on the logical clock, or decide a pending request return a `200 OK` status code. Readers must reconstruct full request and response shapes from the narratives in §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/library/_clock/set_current_utc` | Advance the logical clock and run the graduation/expiration sweep | PlatformAdmin |
| POST | `/library/state-programs` | Create a state/provincial funding program | PlatformAdmin |
| POST | `/library/affiliates` | Create a local affiliate | PlatformAdmin |
| GET | `/library/affiliates/{id}` | Get an affiliate with computed `enrolled_count` and `operative` | All roles |
| GET | `/library/affiliates` | List affiliates with filters and pagination | All roles |
| GET | `/library/affiliates/{id}/penetration` | Penetration report for a month (snapshot and trailing-12) | All roles |
| POST | `/library/affiliates/{id}/agreements` | Create a partner agreement (`PENDING_APPROVAL`, OCC on affiliate version) | AffiliateCoordinator, PlatformAdmin |
| GET | `/library/affiliates/{id}/agreements` | List agreements of an affiliate | All roles |
| POST | `/library/agreements/{id}/approve` | Officer approves a pending agreement after overlap checks | StateProgramOfficer |
| POST | `/library/agreements/{id}/reject` | Officer rejects a pending agreement (terminal) | StateProgramOfficer |
| POST | `/library/affiliates/{id}/population-stats` | Record an eligible-population estimate for a year | AffiliateCoordinator, PlatformAdmin |
| GET | `/library/affiliates/{id}/population-stats` | List population stats of an affiliate | All roles |
| POST | `/library/children` | Register a child into the coordinator's own affiliate | AffiliateCoordinator |
| GET | `/library/children/{id}` | Get a child | All roles |
| GET | `/library/children` | List children with filters and pagination | All roles |
| POST | `/library/children/{id}/address-changes` | Submit an address change for a non-terminal child | AffiliateCoordinator |
| GET | `/library/children/{id}/address-changes` | List address changes of a child | All roles |
| POST | `/library/address-changes/{id}/decide` | Approve (in-area / transfer / unenrolled) or reject a pending change | AffiliateCoordinator |
| POST | `/library/titles` | Catalog a book title with age band and availability window | PlatformAdmin |
| GET | `/library/titles/{id}` | Get a title with computed `stock_on_hand` | All roles |
| POST | `/library/selections` | Propose the title for a (month, age band) slot | AdvisoryCommitteeMember |
| GET | `/library/selections/{id}` | Get a selection | All roles |
| GET | `/library/selections` | List selections with filters and pagination | All roles |
| POST | `/library/selections/{id}/approve` | A different committee member approves a proposed selection | AdvisoryCommitteeMember |
| POST | `/library/selections/{id}/reopen` | Send an approved selection back to proposed (blocked once locked) | AdvisoryCommitteeMember |
| POST | `/library/print-orders` | Submit a print order for an approved selection | PublisherOps |
| GET | `/library/print-orders/{id}` | Get a print order | All roles |
| GET | `/library/print-orders` | List print orders with filters and pagination | All roles |
| POST | `/library/print-orders/{id}/confirm` | Confirm an order: capacity check, price lock, selection lock, stock credit | PublisherOps |
| POST | `/library/waves` | Schedule the mailing wave for a month | MailOps |
| POST | `/library/waves/{id}/manifest` | Generate mailing items for all eligible children | MailOps |
| POST | `/library/waves/{id}/reconcile` | Close the wave: auto-deliver unreturned items, create draft invoices | MailOps |
| GET | `/library/items/{id}` | Get a mailing item | All roles |
| GET | `/library/items` | List mailing items with filters and pagination | All roles |
| POST | `/library/items/{id}/mark-returned` | Record an undeliverable return; cascades hold / auto-unenroll | MailOps |
| GET | `/library/invoices/{id}` | Get an affiliate invoice | All roles |
| GET | `/library/invoices` | List invoices with filters and pagination | All roles |
| POST | `/library/invoices/{id}/issue` | Issue a draft invoice to the affiliate | PlatformAdmin |
| POST | `/library/invoices/{id}/pay` | Pay the local share (from issued or adjusted) | AffiliateCoordinator |
| POST | `/library/invoices/{id}/dispute` | Open a dispute or resolve it (overruled / upheld with credit memo) | AffiliateCoordinator, PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is only an index of identifiers to status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STATE_PROGRAM_NOT_FOUND` | 404 |
| `ERR_AFFILIATE_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_CHILD_NOT_FOUND` | 404 |
| `ERR_ADDRESS_CHANGE_NOT_FOUND` | 404 |
| `ERR_TITLE_NOT_FOUND` | 404 |
| `ERR_SELECTION_NOT_FOUND` | 404 |
| `ERR_PRINT_ORDER_NOT_FOUND` | 404 |
| `ERR_WAVE_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BIRTH_DATE_IN_FUTURE` | 422 |
| `ERR_CHILD_AGE_INELIGIBLE` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_ADDRESS_NOT_COVERED` | 422 |
| `ERR_AFFILIATE_NOT_OPERATIVE` | 409 |
| `ERR_AGREEMENT_WINDOW_INVALID` | 422 |
| `ERR_AGREEMENT_GEOGRAPHY_OVERLAP` | 409 |
| `ERR_SELECTION_EXISTS` | 409 |
| `ERR_SELECTION_MONTH_PAST` | 422 |
| `ERR_TITLE_UNAVAILABLE_MONTH` | 422 |
| `ERR_WAVE_MONTH_DUPLICATE` | 409 |
| `ERR_WAVE_MONTH_PAST` | 422 |
| `ERR_MANIFEST_SELECTIONS_INCOMPLETE` | 409 |
| `ERR_INVENTORY_SHORTFALL` | 409 |
| `ERR_PRESS_CAPACITY_EXCEEDED` | 409 |
| `ERR_POPULATION_YEAR_DUPLICATE` | 409 |
| `ERR_SELECTION_ALREADY_SUPPLIED` | 409 |
| `ERR_CREDIT_EXCEEDS_GROSS` | 422 |
