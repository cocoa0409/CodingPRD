# Card Issuing Program API — Product Requirements Document

## 1. Introduction

Operating a card issuing business means coordinating far more than printing plastic. A single program spans BIN range allocation and product parameter setup, card production and personalization through third-party fulfillment vendors, cardholder activation and PIN issuance, authorization policy (velocity, merchant-category, and geography controls), network compliance releases and mandate implementation, interchange qualification and program economics, replacement campaigns for expiring or compromised cards, and ultimately program termination with portfolio conversion. This document specifies an issuing platform API that manages that entire lifecycle under the `/issuing` mount, giving the program operator one coherent surface on which every one of those concerns is modeled as a first-class, auditable resource.

The platform is built for a regulated, multi-operator environment. Work is divided across six roles with strict segregation of duties: the operator who submits a network-mandate acknowledgement may never be the one who verifies it, and the operator who schedules a portfolio conversion may not cancel it. Money is tracked in integer cents, interchange is computed under pinned evaluation orders, and a logical server clock — not wall-clock time — drives every time-dependent behavior, from BIN range activation windows to mandate effective dates to card expiry sweeps. Optimistic concurrency control guards the few mutable product parameters so that two administrators editing the same program or account cannot silently overwrite one another.

This PRD is written for the engineering team implementing the service. Section 2 defines the system-wide contracts (envelope, pagination, identity, clock, concurrency, validation order). Section 3 walks the business workflows in narrative form; the numeric thresholds, state pairs, and error identifiers that govern each workflow are stated where they naturally belong. Section 4 is the endpoint index, and Section 5 is the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API call carries two headers: `X-User-ID`, identifying the operator, and `X-User-Role`, naming the operator's role. If the `X-User-Role` header is absent or does not name one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is declared but not permitted to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). No endpoint is anonymous; every call requires a role.

The declared roles are:

- `PlatformAdmin` — break-glass operator. Exclusively owns the logical-clock test-driving capability, vendor registration, and the forced PIN-block capability; shares account funding and settlement with `FinanceController`, and authorization creation with `CardholderOps`; may read all resources.
- `ProgramManager` — owns the card program lifecycle (create, update, publish, sunset, cancel-sunset, terminate), BIN range management, card account lifecycle, card issuance, and conversion job scheduling.
- `ComplianceOfficer` — owns network mandates and their acknowledgements (submit, return, verify, reject), authorization rules, and card compromise actions.
- `OperationsAnalyst` — owns production batches and reissue campaigns.
- `FinanceController` — owns program economics reporting, and shares account funding and settlement with `PlatformAdmin`.
- `CardholderOps` — performs card activation, PIN management, and initiates authorizations on behalf of the cardholder.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: when `X-User-Role` is `PlatformAdmin`, `ProgramManager`, `ComplianceOfficer`, `OperationsAnalyst`, `FinanceController`, or `CardholderOps`, the server never compares `X-User-ID` to any entity's `id`. The identifier is still recorded where segregation of duties demands it — a mandate acknowledgement stores the submitting operator as `submitted_by_user_id` and the verifier as `verified_by_user_id`, and a conversion job remembers its scheduling operator — so that later SoD checks compare operator identities, not entity rows.

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

List endpoints accept two query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless a workflow states a different ordering, every list is sorted by `created_at` ascending.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource has an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Resources that participate in the normal lifecycle additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and an integer `version` that increments by one on every mutation of that resource, including state transitions and self-loop transitions such as a PIN change. Two resources are deliberate exceptions: the authorization event log and the settlement ledger are append-only, and each carries only `id` and `created_at` — `updated_at` and `version` are absent from both, because neither resource is ever modified after creation.

A terminated card program remains fully queryable after termination (soft-delete semantics): reads against it and its historical sub-resources continue to succeed.

### 2.5. The Logical Clock and Time-Driven Transitions

All time-dependent behavior in the platform is governed by a single server-side logical clock, never by wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and before any clock-advance call it must report exactly that instant. A `PlatformAdmin` may advance the logical clock by supplying a target instant in the `to_iso8601` field; the capability responds with the clock's new reading in `current_utc`.

Several transitions are lazy: rather than firing through background jobs, they are applied when the clock has passed their threshold and the affected resource is next read or written (advancing the clock is the canonical way to make them observable). The lazy transitions are: a BIN range moving from `PENDING_ACTIVATION` to `ACTIVE` once the clock reaches its `effective_from`; a mandate moving from `ANNOUNCED` to `EFFECTIVE` once the clock reaches its `effective_at`; a reissue campaign moving from `SCHEDULED` to `EXECUTING` once the clock reaches its `scheduled_for`; a conversion job moving from `SCHEDULED` to `EXECUTING` once the clock reaches its `execution_at`; a card moving from `ACTIVE` to `EXPIRED` when the clock reaches the first day of the month after its expiry; and an activation token moving from `PENDING` to `EXPIRED` once the clock passes its `expires_at`.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each naming the parent entity whose version the client must echo back:

- Updating a card program's product parameters requires `expected_program_version`, carrying the client's last-observed `version` of the `CardProgram`.
- Updating a card account's spend cap or credit limit requires `expected_account_version`, carrying the client's last-observed `version` of the `CardAccount`.
- Activating an authorization rule requires `expected_rule_version`, carrying the client's last-observed `version` of the `AuthorizationRule`.

On each of these three operations the expected-version field is non-optional: if it is missing entirely, the request is rejected with `ERR_MISSING_OCC_FIELD` (HTTP 400). If it is present but no longer matches the entity's current `version` — because another writer has advanced the entity since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client can never overwrite state it has not observed. Endpoints other than these three do not take a version field.

### 2.7. Request Evaluation Order

When several checks could reject the same request, the server evaluates them in a fixed order so the returned error is deterministic. The global order is:

1. Authentication — the role header must be present and declared (`ERR_UNAUTHENTICATED`).
2. Authorization — the role must be permitted on the endpoint (`ERR_UNAUTHORIZED`).
3. Path existence — every id in a path template (program, bin range, vendor, batch, account, card, activation token, authorization event, settlement, rule, mandate, acknowledgement, campaign, conversion job) must resolve to an existing row, and nested paths validate parents left to right (`ERR_NOT_FOUND`).
4. OCC field presence — on the three OCC-guarded operations the expected-version field must be present (`ERR_MISSING_OCC_FIELD`).
5. OCC version match — the expected version must equal the server's current version (`ERR_STALE_VERSION`).
6. State validity — the target resource must be in a state that permits the requested transition (`ERR_INVALID_STATE`).
7. Business checks — segregation of duties (`ERR_SOD_SAME_USER`), the mandate compliance deadline (`ERR_MANDATE_DEADLINE_PASSED`), program rule locking (`ERR_PROGRAM_RULES_LOCKED`), program posture gating (`ERR_PROGRAM_NOT_LIVE` / `ERR_PROGRAM_NOT_EDITABLE`), production vendor admissibility (`ERR_VENDOR_INACTIVE`, `ERR_VENDOR_NETWORK_MISMATCH`, `ERR_VENDOR_CAPACITY_EXCEEDED`), temporal windows (`ERR_BATCH_DATE_PAST`, `ERR_CAMPAIGN_DATE_PAST`, `ERR_CONVERSION_DATE_PAST`), vendor batch overlap (`ERR_VENDOR_BATCH_OVERLAP`), BIN effective windows (`ERR_BIN_NOT_IN_WINDOW`), referential integrity of foreign-key inputs (`ERR_INVALID_REFERENCE`), BIN capacity (`ERR_NO_BIN_CAPACITY`), then the fiscal checks on authorizations in the order funds (`ERR_INSUFFICIENT_FUNDS`), velocity (`ERR_VELOCITY_EXCEEDED`), daily cap (`ERR_DAILY_CAP_EXCEEDED`), the account close balance check (`ERR_ACCOUNT_BALANCE_NONZERO`), and finally conversion target admissibility (`ERR_CONVERSION_TARGET_INVALID`).

Because the order is pinned, a request that would fail two checks always surfaces the earlier one: for example, an acknowledgement verification attempted by the submitting operator after the compliance deadline reports `ERR_SOD_SAME_USER`, never `ERR_MANDATE_DEADLINE_PASSED`; an authorization that is both over the velocity limit and over the daily cap reports `ERR_VELOCITY_EXCEEDED`; and a rule activation with a missing `expected_rule_version` reports `ERR_MISSING_OCC_FIELD` even if the rule is also locked.

### 2.8. Monetary Precision and Rounding

All monetary quantities are integer cents — interchange, production cost, reissue fees, balances, caps, and fees alike carry zero decimal places. The only rounding operation used anywhere in the platform is round-down (floor), and it is applied only at the final step of a calculation, never at intermediate steps. Aggregation sums are order-invariant integer sums with no rounding at all.

### 2.9. Nested Resources and Referential Integrity

Many resources live beneath a parent in the URL hierarchy — BIN ranges, production batches, reissue campaigns, conversion jobs, and account listings beneath a program; cards beneath an account; acknowledgements beneath a mandate. Nested paths are validated left to right: the parent id must resolve before the child id is examined, and the first unresolvable id yields `ERR_NOT_FOUND`. Separately, any foreign key supplied in a request body — a program, account, BIN range, vendor, mandate, or target program reference — must resolve to an existing row, or the request is rejected with `ERR_INVALID_REFERENCE` (HTTP 422). Where a resource references another aggregate, the platform also offers reverse-reachability listings, so a batch is visible from its vendor, a card from its BIN range or its reissue campaign, an authorization event from its account, program, or deciding rule, and a settlement from its card, account, or source authorization.

## 3. Business Logic & Workflows

### 3.1. Establishing a Card Program and Its BIN Ranges

A `ProgramManager` begins by creating a card program. The creation payload carries a `program_code` that must be unique across all programs — including programs that have since been `TERMINATED`, so a retired code is never recycled — together with the `product_class` (one of `CONSUMER_PREPAID`, `CORPORATE_FLEET`, `DEBIT_CONSUMER`, `COMMERCIAL_CREDIT`), the `network` (`VISA`, `MASTERCARD`, `STAR`, or `PULSE`), the ISO 4217 `currency_code` (immutable once set), and a program-wide `daily_spend_cap_cents` that acts as a hard ceiling for every card in the program and must be greater than zero. A `termination_reason` may optionally be recorded at creation, though it only becomes required at termination time. A new program starts in `DRAFT` posture with `authorization_rules_locked` false and `open_card_count` zero; `open_card_count` is a computed figure counting the program's cards whose lifecycle is `ISSUED`, `ACTIVE`, or `SUSPENDED`.

With a program in place, the manager allocates BIN ranges beneath it. Each range is created with a `bin_prefix` of 6 or 8 numeric digits, a `range_size` that must be a power of ten no smaller than one thousand and no larger than ten million, and an effective window delimited by `effective_from` and `effective_until`, where `effective_until` must be strictly later than `effective_from` — a violation is rejected with `ERR_BIN_NOT_IN_WINDOW`. A fresh range starts `PENDING_ACTIVATION` with `pans_allocated` at zero; its `pans_available` is always the range size minus the allocated count. The range flips itself to `ACTIVE` lazily once the clock reaches `effective_from`, provided the owning program's posture is `DRAFT` or `LIVE`. Should the allocated count ever consume the whole range, the range flips itself to `DEPLETED`. The range collection of a program can be listed and filtered by `status`, and individual ranges are readable on their own.

Product parameters remain adjustable while the program lives. Updating a program's `daily_spend_cap_cents` is an OCC-guarded write (§2.6) and increments the program's `version`. If the program cap is lowered below some account's own cap, those accounts are not silently rewritten — each affected account keeps its recorded cap, and new authorizations on such an account are evaluated against the smaller of the account cap and the program cap.

A program's current posture is part of its computed state: `posture` reads `DRAFT`, `LIVE`, `SUNSETTING`, or `TERMINATED`, and when a program terminates the server stamps `terminated_at` with the clock. Programs can be listed with filters on `posture`, `network`, and `product_class`.

### 3.2. Program Posture: Publishing, Sunset, and Termination

Publishing moves a program from `DRAFT` to `LIVE`. Publishing requires the program to actually be in `DRAFT` — attempting it from any other posture fails posture gating with `ERR_PROGRAM_NOT_LIVE` — and then enforces its preconditions in order: at least one of the program's BIN ranges must be `ACTIVE` (otherwise `ERR_PROGRAM_NO_ACTIVE_BIN`), the program's `daily_spend_cap_cents` must be greater than zero, and no acknowledgement submitted by this program may still be in flight against a mandate that has already gone `EFFECTIVE` (otherwise `ERR_MANDATE_ACK_IN_FLIGHT`). A successful publish flips `posture` to `LIVE` and increments the program's `version`.

Sunsetting begins a program's wind-down: the `LIVE` → `SUNSETTING` transition is refused with `ERR_PROGRAM_BATCH_IN_FLIGHT` while any production batch under the program sits in `SUBMITTED` or `IN_PRODUCTION`. The moment a program sunsets, every `ACTIVE` BIN range beneath it is frozen to `FROZEN` by cascade, and while accounts keep their existing lifecycle, no new cards may be issued under the program. Sunset is revocable: cancelling the sunset returns the program from `SUNSETTING` to `LIVE` and restores the ranges it froze from `FROZEN` back to `ACTIVE` — but only while no conversion job for the program is `SCHEDULED` or `EXECUTING`; if one is, the cancellation is rejected with `ERR_CONVERSION_IN_FLIGHT`.

Termination is final and moves `SUNSETTING` → `TERMINATED`. The request must carry a `termination_reason` of `VOLUNTARY`, `NETWORK_DIRECTIVE`, or `PORTFOLIO_CONVERSION`, and the reason selects the gate: for `PORTFOLIO_CONVERSION`, a completed conversion job whose source is this program must already exist, or the termination is rejected with `ERR_CONVERSION_NOT_COMPLETED`; for the other two reasons, every card account under the program must already be `CLOSED` or `CONVERTED_OUT`, or the request fails with `ERR_PROGRAM_HAS_OPEN_ACCOUNTS`. A successful termination stamps `terminated_at`, flips every BIN range under the program to `RETIRED`, flips every card under the program to `CANCELLED` (each card's `pin_status` is preserved), and retires every authorization rule whose subject is the program itself. Because termination is a soft delete, the terminated program and its history remain queryable.

A manager may also retire a BIN range directly: a range in `ACTIVE`, `FROZEN`, or `DEPLETED` may be moved to `RETIRED`. From `ACTIVE` or `FROZEN` the range must have nothing allocated from it — if `pans_allocated` is above zero the retirement is rejected with `ERR_BIN_HAS_ALLOCATED_PANS`; a `DEPLETED` range carries no such check and may be retired directly, which matters when a reissue has freed a depleted range's PANs. Freezing and unfreezing individual ranges is likewise available; unfreezing is permitted only while the owning program's posture is `DRAFT` or `LIVE`, and it returns the range from `FROZEN` to `ACTIVE`.

### 3.3. Production Vendors and Card Production Batches

Physical card fulfillment is delegated to registered vendors. A `PlatformAdmin` registers each vendor with a unique `vendor_code`, a non-empty `capability_flags` list drawn from `EMV_CHIP`, `CONTACTLESS`, `MAGSTRIPE`, `VIRTUAL`, and `DUAL_INTERFACE`, a `daily_capacity_cards` greater than zero expressing how many cards the vendor can personalize per UTC day, and the vendor's `supported_networks` (a subset of the four networks). Vendors are created `is_active` true unless explicitly registered inactive, and an inactive vendor cannot be selected for new batches.

An `OperationsAnalyst` plans production by creating a batch under a program, naming the `vendor_id`, the production date `scheduled_for_utc_date` (a YYYY-MM-DD UTC date), the `requested_card_count` (greater than zero), and the `unit_cost_cents` (zero or more). The batch starts `PLANNED` with `fulfilled_card_count` zero. Submitting the batch (`PLANNED` → `SUBMITTED`) runs a fixed gauntlet of checks in this order: the program must be `LIVE` (`ERR_PROGRAM_NOT_LIVE`); the vendor must be active (`ERR_VENDOR_INACTIVE`); the vendor's `supported_networks` must contain the program's network (`ERR_VENDOR_NETWORK_MISMATCH`); the requested count must not exceed the vendor's daily capacity (`ERR_VENDOR_CAPACITY_EXCEEDED`); the production date must not be in the past relative to the server clock (`ERR_BATCH_DATE_PAST`); and no other batch for the same vendor on the same UTC date may already be `SUBMITTED` or `IN_PRODUCTION` (`ERR_VENDOR_BATCH_OVERLAP`).

From `SUBMITTED` the analyst starts production (`IN_PRODUCTION`), then marks the batch shipped. Marking shipped is the point of fiscal truth: the payload carries `fulfilled_card_count`, which must not exceed `requested_card_count` (violations are rejected with `ERR_FULFILLED_EXCEEDS_REQUESTED`), and the batch cost is booked as the fulfilled count multiplied by `unit_cost_cents` in integer cents with no rounding. The evaluation order is pinned so the books are never half-written: the fulfilled count is written from the payload, the batch cost is recomputed from it, the status flips to `SHIPPED`, and only then does program economics reflect the batch — no observer can ever see a `SHIPPED` batch whose cost is undefined. When the vendor fulfills fewer cards than requested, the shortfall is not re-allocated to other batches; the batch simply books less. A shipped batch is later marked `DELIVERED`. A batch still `PLANNED` or `SUBMITTED` may be cancelled outright (`CANCELLED`), while a batch that fails mid-production is marked `FAILED`, and any cards minted against it that never reached `ACTIVE` flip to `CANCELLED`. Batches are listed per program with filters on `status` and `vendor_id`, and a vendor's delegated workload is likewise listed by `status`.

### 3.4. Card Accounts, Card Issuance, and the PIN Dimension

Card accounts are created by a `ProgramManager` with a payload naming the owning program via `program_id`, a client-supplied `external_account_ref` that must be unique within that program, an `account_class` of `INDIVIDUAL`, `BUSINESS`, or `FLEET_POOL`, an optional `credit_limit_cents`, and a per-account `daily_spend_cap_cents` that must not exceed the program's cap. The account inherits its `currency_code` from the program, immutably. `credit_limit_cents` is meaningful only for accounts under a `COMMERCIAL_CREDIT` program; under any other product class it must equal zero. A new account starts `ONBOARDING` with `available_balance_cents` zero and a computed `risk_tier` of `STANDARD`; the tier is system-derived from velocity breaches and mandate posture, with values `STANDARD`, `ELEVATED`, and `RESTRICTED`. Both the cap and the credit limit may later be updated through the OCC-guarded account write (§2.6), which increments the account's `version`. Accounts are listed flat with `program_id` and `lifecycle_status` filters, or as a sub-listing beneath a program filtered by `lifecycle_status`.

Activation moves an account `ONBOARDING` → `OPEN` and is permitted only while the program is `LIVE` (`ERR_PROGRAM_NOT_LIVE`), and only while the program still has at least one `ACTIVE` BIN range with `pans_available` of at least one (`ERR_NO_BIN_CAPACITY`). Suspending an account (`OPEN` → `SUSPENDED`) cascades: every card of the account that is `ACTIVE` flips to `SUSPENDED` with its `pin_status` preserved. Resuming (`SUSPENDED` → `OPEN`, again requiring the program to be `LIVE`) reverses that cascade, returning the account's `SUSPENDED` cards to `ACTIVE`. Closing an account — from either `OPEN` or `SUSPENDED` — requires `available_balance_cents` to be exactly zero, failing with `ERR_ACCOUNT_BALANCE_NONZERO` otherwise, and flips all of the account's cards to `CANCELLED`, decrementing the program's `open_card_count` by the number of cards that flipped. A `FinanceController` or `PlatformAdmin` tops up an account by funding it with `amount_cents`, which is added to `available_balance_cents`.

Cards are issued against an account with an `expiry_month` of 1 through 12, an `expiry_year` that must be later than the current clock year — or equal to it, in which case `expiry_month` must be at least the current month — and a `form_factor` of `PHYSICAL` or `VIRTUAL`. The PAN is drawn from a BIN range: the caller may name `bin_range_id`, or omit it and let the selector choose the program's `ACTIVE` ranges with at least one PAN available, ordered by `bin_prefix` ascending, then `effective_from` ascending, then `created_at` ascending. Issuance requires the chosen range to be inside its effective window — the clock must be at or after `effective_from` and strictly before `effective_until`, else `ERR_BIN_NOT_IN_WINDOW` — and requires available capacity (`ERR_NO_BIN_CAPACITY`). Issuing consumes one PAN: `pans_allocated` increases by one. The card never exposes a real PAN; the server mints a `pan_token` handle, and the card's `last4` is derived deterministically from that token. A new card starts `ISSUED` with `pin_status` `UNSET`, and issuance also mints a one-time activation token: a server-generated `token_value` whose `issued_at` is the clock at mint and whose `expires_at` is exactly 72 hours later, starting in `PENDING`.

The card's two dimensions evolve independently. In the PIN dimension, `CardholderOps` sets a PIN — allowed only while the card's lifecycle is `ISSUED` or `ACTIVE`, otherwise `ERR_CARD_TERMINAL_STATE` — by supplying `new_pin`, which must be 4 to 12 digits (`ERR_PIN_FORMAT_INVALID` otherwise), moving `UNSET` → `SET`. Changing a PIN is a `SET` → `SET` self-loop that additionally requires `current_pin` to match the stored PIN, and it still increments the card's `version`. After `PIN_FAIL_LIMIT` consecutive PIN verification failures the system blocks the PIN (`SET` → `BLOCKED`); a `PlatformAdmin` may force the same transition directly as a test-driving capability. From `BLOCKED`, `CardholderOps` requests a reset (`RESET_PENDING`), after which setting a fresh PIN returns the dimension to `SET`.

Card activation (`ISSUED` → `ACTIVE`) is performed by `CardholderOps` and enforces its checks in order: the owning account must be `OPEN` (`ERR_ACCOUNT_NOT_OPEN`); a `PENDING` activation token must exist for the card whose `expires_at` is still ahead of the clock, and the request's `activation_token` must match that token's `token_value` — either failure yields `ERR_ACTIVATION_TOKEN_INVALID`; and the card's `pin_status` must be `SET` (`ERR_PIN_NOT_SET`). A successful activation consumes the token — it flips to `CONSUMED` with `consumed_at` stamped — and increments the program's `open_card_count`. Tokens that outlive their 72-hour window flip to `EXPIRED`, and a `PENDING` token is revoked to `REVOKED` automatically if its card is cancelled.

Individual cards may be suspended (`ACTIVE` → `SUSPENDED`), resumed (`SUSPENDED` → `ACTIVE`, requiring the account to be `OPEN`), or cancelled by a `ProgramManager`. Cancelling from any of `ISSUED`, `ACTIVE`, or `SUSPENDED` releases the PAN (`pans_allocated` decreases by one); cancelling an `ISSUED` card also revokes its pending token, and cancelling an `ACTIVE` card additionally decrements `open_card_count`. A card whose expiry passes flips itself `ACTIVE` → `EXPIRED` on the clock, likewise releasing its PAN and decrementing the count. Cards are listed per account (filterable by `lifecycle_status` and `pin_status`), per BIN range (by `lifecycle_status`), or flat with filters on `account_id`, `bin_range_id`, `replaced_by_card_id`, `replaced_from_card_id`, `reissue_campaign_id`, and `lifecycle_status`.

Compromise handling is a `ComplianceOfficer` action that moves an `ACTIVE` card to `COMPROMISED`, releasing its PAN and decrementing the open-card count. Compromise carries a contagious risk rule: if this is the third or later card under the same account to flip `ACTIVE` → `COMPROMISED` within a rolling seven-day window measured from the clock at the transition, the account's `risk_tier` is set to `RESTRICTED` and the account itself is suspended `OPEN` → `SUSPENDED`; that suspension then cascades as usual, flipping every other `ACTIVE` card on the account to `SUSPENDED` with PIN state preserved. The chain is deliberately transitive — card compromise, account suspension, sibling card suspension — so a single compromised wallet cannot leave stragglers spending.

### 3.5. Authorization Rules and Transaction Decisioning

Authorization policy is expressed as rules created by a `ComplianceOfficer`. A rule's `subject_kind` is `PROGRAM` or `ACCOUNT`, and its `subject_ref` is the id of the program or account it governs — one rule kind of polymorphic reference. The `rule_kind` is one of `VELOCITY`, `MCC_ALLOW`, `MCC_BLOCK`, or `GEO_BLOCK`, and the kind dictates the remaining shape: a `VELOCITY` rule requires `window_seconds` (greater than zero), `max_txn_count` (at least one), and `max_amount_cents` (at least one); `MCC_ALLOW` and `MCC_BLOCK` rules require a non-empty `mcc_list` of four-digit strings; a `GEO_BLOCK` rule requires a non-empty `country_code_list` of ISO 3166-1 alpha-2 codes. Every rule carries a `priority_rank`; when several rules match a single authorization, the lower rank wins and ties break by `created_at` ascending. Rules start in `DRAFT`, are editable only while in `DRAFT` (each edit increments the rule's `version`), and can be retired from either `DRAFT` or `ACTIVE`. The rule collection is listed with `subject_kind`, `subject_ref`, `rule_kind`, and `status` filters.

Activating a rule (`DRAFT` → `ACTIVE`) is the third OCC-guarded operation (§2.6) and layers further gates beyond the version check: for a program-scoped rule the program's `authorization_rules_locked` must be false — a locked program rejects the activation with `ERR_PROGRAM_RULES_LOCKED` — and the program's posture must be `DRAFT` or `LIVE` (`ERR_PROGRAM_NOT_EDITABLE`); for an account-scoped rule the account must be `OPEN` or `SUSPENDED` (`ERR_ACCOUNT_TERMINAL_STATE`). A `VELOCITY` rule whose three numeric fields do not satisfy their minima cannot be activated.

When `CardholderOps` (or a `PlatformAdmin`) initiates an authorization on a card — supplying `amount_cents` greater than zero, a four-digit `mcc`, and the merchant's alpha-2 `country_code` — the platform evaluates the attempt and appends an authorization event to the card's append-only log. The event denormalizes `account_id` and `program_id` alongside `card_id` so velocity aggregation never needs joins, and records the outcome in `decision` — one of `APPROVED`, `DECLINED_LIMIT`, `DECLINED_RULE`, `DECLINED_STATE`, or `DECLINED_VELOCITY` — with a stable machine-readable `decision_reason`, the server clock in `authorized_at`, and, when a rule determined a decline, that rule's id in `applied_rule_id`. A card that is not `ACTIVE`, or whose account is not `OPEN`, cannot be authorized and records `DECLINED_STATE`. `MCC_BLOCK` rules decline listed merchant categories, `MCC_ALLOW` rules decline everything outside their list, and `GEO_BLOCK` rules decline listed countries; a rule-determined decline records `DECLINED_RULE` with the winning rule's id.

The fiscal gates then apply in their pinned order. The balance check comes first: if the account's `available_balance_cents` is less than the authorization amount, the attempt is rejected with `ERR_INSUFFICIENT_FUNDS`. Next is velocity: every `ACTIVE` `VELOCITY` rule whose subject is the card's account or program is considered in `priority_rank` order with `created_at` tie-breaks, and each rule's sliding window spans from the clock minus `window_seconds` up to the clock — both bounds inclusive, so an event sitting exactly at the window's start counts. Only `APPROVED` events consume velocity; declines never burn the limit. The attempt breaches the rule when adding this transaction would push the window strictly past either ceiling — a count one greater than `max_txn_count`, or a summed amount exceeding `max_amount_cents` — while hitting a ceiling exactly still approves; the first rule to fail decides the outcome, and the attempt is rejected with `ERR_VELOCITY_EXCEEDED` and recorded `DECLINED_VELOCITY`. Last, the daily cap: the cumulative approved authorizations over the rolling 24 hours must not push the account past its effective `daily_spend_cap_cents` — the smaller of the account cap and the program cap when the two diverge — or the attempt is rejected with `ERR_DAILY_CAP_EXCEEDED`. An insufficient-balance decline records `DECLINED_LIMIT`. On `APPROVED`, the amount is subtracted from `available_balance_cents`; on any decline the balance is untouched. Every attempt, approved or declined, remains queryable through the card, account, and program authorization listings — each filterable by `decision` — and through the deciding rule's own event listing.

### 3.6. Settlement, Interchange Qualification, and Program Economics

Settlement converts an approved authorization into booked economics. A `FinanceController` or `PlatformAdmin` settles an `APPROVED` authorization event by supplying `settled_amount_cents`, which may be less than the authorized amount to support partial captures but must be greater than zero. The settlement is appended to the ledger with the settled authorization referenced by its `authorization_event_id`, the clock in `settled_at`, and denormalized `card_id` and `account_id`; each authorization settles at most once, so the settlement listing beneath an authorization event returns zero or one row. When the settled amount falls short of the authorized amount, the remainder is released back to the account's `available_balance_cents`.

Every settlement is assigned a `qualification_tier` of `QUALIFIED`, `MID_QUALIFIED`, or `NON_QUALIFIED` before any rate is consulted, through a tier evaluation with pinned boundaries. If the settlement's `mcc` appears on the network's blocked list — `7995` and `6012` for `VISA`, `7995` alone for `MASTERCARD`, and empty lists for `STAR` and `PULSE` — the tier is `NON_QUALIFIED`. Otherwise, if the gap between `authorized_at` and `settled_at` exceeds 172,800 seconds (48 hours), the tier is `NON_QUALIFIED`; the boundary is exclusive, so a gap of exactly 172,800 seconds falls through to the next test. Otherwise, if the card is not EMV-chip capable — a property derived from the card's form factor and the producing vendor's capabilities — the tier is `NON_QUALIFIED`. Otherwise, when the gap is at most 86,400 seconds (24 hours, inclusive) and the card is EMV capable, the tier is `QUALIFIED`. Every remaining case is `MID_QUALIFIED`.

Booked `interchange_cents` is then computed in a pinned order. The base rate in basis points comes from the network-and-tier table: `VISA` pays 145 at `QUALIFIED`, 185 at `MID_QUALIFIED`, and 230 at `NON_QUALIFIED`; `MASTERCARD` pays 148, 188, and 235; `STAR` pays 90, 130, and 175; `PULSE` pays 85, 125, and 170. When the program's `product_class` is `COMMERCIAL_CREDIT` or `CORPORATE_FLEET`, a commercial uplift of 65 basis points is added to the chosen rate before any multiplication. The interchange is then the settled amount in cents multiplied by that rate, divided by ten thousand, increased by the network's per-item fee — 10 cents for `VISA`, 11 for `MASTERCARD`, and 5 each for `STAR` and `PULSE` — with the final total rounded down to a whole cent and no rounding at any intermediate step. A provisional variant of the same figure is computed advisory-only at authorization time, optimistically assuming the authorization's merchant category will settle at `QUALIFIED` and within a day; it is never booked, and the final settlement figure differs from it whenever the real tier is not `QUALIFIED` or the commercial uplift applies.

Monthly program economics are exposed to a `FinanceController` (or `PlatformAdmin`) as a computed report requested with a `month` in YYYY-MM form and an optional `variant`. The window is the half-open month, from the first instant of the month up to but not including the first instant of the next. The report returns `month`, `variant`, and four integer-cent figures. `interchange_revenue_cents` sums the `interchange_cents` of the program's settlements whose `settled_at` falls inside the window. `production_cost_cents` sums, over the program's batches in `SHIPPED` or `DELIVERED` whose `scheduled_for_utc_date` falls inside the window, each batch's fulfilled count multiplied by its `unit_cost_cents`. `reissue_fee_cents` sums the booked per-card fees of the program's campaigns that reached `COMPLETED` inside the window. `net_economics_cents` is the revenue minus the two cost lines. Two variants exist: the `FINAL` variant — the default when the requested month is before the current month — counts only shipped-or-delivered batches at fulfilled counts and campaigns completed in-window; the `PROVISIONAL` variant — the default when the requested month is the current month — counts settlements only up to the clock and adds a forward-looking accrual for batches still `SUBMITTED` or `IN_PRODUCTION`, valued at requested count multiplied by unit cost. All figures are integer cents with no rounding.

### 3.7. Network Mandates and the Acknowledgement Workflow

Networks publish compliance releases, modeled as mandates announced by a `ComplianceOfficer` with a `network`, a `mandate_code` unique per network-and-code pair, a human-readable `title`, the `effective_at` instant when the mandate becomes binding, a `compliance_deadline` that must be strictly later than `effective_at`, and a `severity` of `ADVISORY`, `REQUIRED`, or `EMERGENCY`. A mandate starts `ANNOUNCED` and flips itself to `EFFECTIVE` once the clock reaches `effective_at`; at that moment any acknowledgement of it still sitting in `DRAFT` is force-returned to `RETURNED` with the string "AUTO-RETURNED: mandate went effective" appended to its `implementation_notes`. Mandates are listed with `network` and `status` filters.

Each program responds to a mandate through an acknowledgement created under the mandate — the parent link recorded in its `mandate_id` — naming the responding `program_id` and free-form `implementation_notes`. The acknowledgement starts `DRAFT` with `revision_count` zero. Submitting it (`DRAFT` → `SUBMITTED`) requires the mandate to be `ANNOUNCED` or `EFFECTIVE` and the program's posture to be `LIVE` or `SUNSETTING` (`ERR_PROGRAM_NOT_EDITABLE`); it also requires the program's rules not to be locked by a different in-flight acknowledgement — the one exception being a resubmission of the very acknowledgement holding the lock. Submission locks the program: `authorization_rules_locked` becomes true, and the server records `submitted_by_role` and `submitted_by_user_id` from the request headers. While the lock is held, no authorization rule under that program can be activated (§3.5).

Review is segregated. Returning, verifying, or rejecting a submitted acknowledgement must be performed by a different operator than the one who submitted it — a matching `X-User-ID` is rejected with `ERR_SOD_SAME_USER` — and this segregation check precedes the deadline check. Returning (`SUBMITTED` → `RETURNED`) releases the program's lock without touching `revision_count`. A returned acknowledgement may be resubmitted (`RETURNED` → `SUBMITTED`), which increments `revision_count`, re-locks the program, and records the new submitter's identity; the cycle can iterate until the acknowledgement is finally disposed. Verification (`SUBMITTED` → `VERIFIED`) additionally requires the clock to still be ahead of the mandate's `compliance_deadline` — a verification at or past the deadline fails with `ERR_MANDATE_DEADLINE_PASSED` — and records `verified_by_user_id` while releasing the lock. Rejection (`SUBMITTED` → `REJECTED`) likewise releases the lock. `VERIFIED` and `REJECTED` are terminal. A program's acknowledgements are listed beneath the program or beneath the mandate, filterable by `status`, and the mandate-side listing also accepts a `program_id` filter.

Retiring a mandate is permitted from `ANNOUNCED` or `EFFECTIVE`. From `EFFECTIVE` it is refused while any acknowledgement of the mandate is still `SUBMITTED` (`ERR_MANDATE_HAS_OPEN_ACKS`); from either state, retiring flips all of the mandate's `DRAFT` and `RETURNED` acknowledgements to `REJECTED`. Retiring an `EFFECTIVE` mandate also recomputes every affected program's lock: a program's `authorization_rules_locked` becomes true if any other acknowledgement against a still-active mandate is `SUBMITTED` for that program, and false otherwise. The lock therefore always reflects exactly the set of in-flight submissions, whether it changed through submission, review, or mandate retirement.

### 3.8. Reissue Campaigns and Portfolio Conversion

Reissue campaigns replace cards in bulk. An `OperationsAnalyst` creates a campaign under a program with a `campaign_kind` of `EXPIRY_SWEEP`, `COMPROMISE_BLAST`, or `NETWORK_MANDATE_REISSUE`, a `scheduled_for` instant that must be strictly in the future at creation, and a `selection_filter` object with three optional keys: `expiry_before` (a YYYY-MM-DD date), `lifecycle_in` (a list of lifecycle states), and `form_factor_in` (a list of form factors). Fee fields depend on the kind: `targeted_unit_fee_cents` prices a `COMPROMISE_BLAST` per card, while `blanket_unit_fee_cents` prices an `EXPIRY_SWEEP` per card; each is ignored for the other kinds. A new campaign is `DRAFT` with `estimated_card_count` zero, and campaigns are listed with `status` and `campaign_kind` filters.

Scheduling a campaign (`DRAFT` → `SCHEDULED`) recomputes the selection: cards belong to the program, their lifecycle is in `lifecycle_in` (defaulting to `ACTIVE`, `SUSPENDED`, and `ISSUED` when the filter omits it), their form factor is in `form_factor_in` (defaulting to all), and when `expiry_before` is given, a card qualifies only if its expiry — compared as year-then-month — falls strictly before the filter's year and month. The matching set is ranked by `expiry_year` ascending, then `expiry_month` ascending, then the card's `created_at` ascending; ties never fall back to card id. The recomputed size lands in `estimated_card_count`, and a selection that comes up empty rejects the scheduling with `ERR_CAMPAIGN_EMPTY_SELECTION`; scheduling also enforces the future-dated rule afresh, rejecting a stale `scheduled_for` with `ERR_CAMPAIGN_DATE_PAST`. A campaign still in `DRAFT` or `SCHEDULED` may be cancelled.

When the clock reaches `scheduled_for`, the campaign starts `EXECUTING` and converts each selected card whose lifecycle is still `ISSUED`, `ACTIVE`, or `SUSPENDED`: a successor card is minted with the same `form_factor`, an expiry 36 months out, lifecycle `ISSUED`, `pin_status` `UNSET`, the source card's id in `replaced_from_card_id`, and the campaign's id in `reissue_campaign_id`; the source card flips to `REPLACED` with `replaced_by_card_id` pointing at the successor. PAN conservation across a reissue is exact — the source PAN is retired from the allocation pool while the successor consumes a fresh PAN, so the program's total allocated PANs rises by exactly one per reissued card. If execution finds no matching cards at all, the campaign flips to `FAILED` with `empty_execution_reason` set to `NO_MATCHING_CARDS`. Once every successor is minted, the campaign completes and books its fee: for a `COMPROMISE_BLAST`, the fee is simply the per-card `targeted_unit_fee_cents` summed across successors; for an `EXPIRY_SWEEP`, a four-percent volume discount is taken on the total — the gross fee is the integer sum of the per-card `blanket_unit_fee_cents`, the discount is that gross multiplied by four and divided by one hundred, rounded down, and the booked fee is the gross minus the discount. The order matters and is pinned at the total level: with a 333-cent blanket fee and three cards, discounting each card first would book 957 cents, while the prescribed total-level computation books a gross of 999, a discount of 39, and a net of 960 — the platform books 960. A campaign's minted successors are listed beneath it.

Portfolio conversion is the graceful exit. A `ProgramManager` schedules a conversion job beneath a `SUNSETTING` source program — the source recorded on the job as `source_program_id` — naming a `target_program_id` and an `execution_at` that must be strictly in the future at scheduling (`ERR_CONVERSION_DATE_PAST`). The target must be admissible — a `LIVE` program on the same network and in the same `currency_code` as the source, and not the source itself — or scheduling fails with `ERR_CONVERSION_TARGET_INVALID`. A scheduled job computes `accounts_planned` as the count of the source program's accounts in `OPEN` or `SUSPENDED`. The job may be cancelled while still `SCHEDULED`, but not by the operator who scheduled it; the scheduler's identity is recorded at creation and a matching canceller is refused. When the clock reaches `execution_at` the job starts `EXECUTING` — unless the source program is no longer `SUNSETTING`, in which case it flips straight to `FAILED` — and moves each planned account out of the source: the account is re-parented to the target program, its source-side lifecycle is recorded `CONVERTED_OUT`, and it carries its posture into the target (an `OPEN` account arrives `OPEN`; a `SUSPENDED` account stays `SUSPENDED`), with its cards remaining `ACTIVE` and re-parented by reference. `accounts_converted` climbs as each account moves, and when it equals `accounts_planned` the job is `COMPLETED`; if the target program leaves `LIVE` mid-flight, or the planned count unexpectedly collapses to zero, the job flips to `FAILED`. A completed conversion is the key that unlocks termination with reason `PORTFOLIO_CONVERSION` (§3.2). Jobs are listed beneath the source program with a `status` filter.

## 4. Endpoint Definitions

All endpoints are mounted under `/issuing`. Operations that create a new resource respond with 201 Created; reads, modifications, and state transitions respond with 200 OK. Request and response bodies are not repeated here — each operation's payload and effects are defined by the workflow narratives in Section 3, and the envelope contract in Section 2.2 applies throughout.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /issuing/_clock/set_current_utc | Advance the server logical clock | PlatformAdmin |
| POST | /issuing/programs | Create a card program (DRAFT) | ProgramManager |
| GET | /issuing/programs | List card programs | ProgramManager, ComplianceOfficer, OperationsAnalyst, FinanceController, PlatformAdmin |
| GET | /issuing/programs/{id} | Get a card program (terminated programs remain queryable) | ProgramManager, ComplianceOfficer, OperationsAnalyst, FinanceController, PlatformAdmin |
| PUT | /issuing/programs/{id} | Update program product parameters (OCC-guarded) | ProgramManager |
| POST | /issuing/programs/{id}/publish | DRAFT → LIVE | ProgramManager |
| POST | /issuing/programs/{id}/sunset | LIVE → SUNSETTING | ProgramManager |
| POST | /issuing/programs/{id}/cancel_sunset | SUNSETTING → LIVE | ProgramManager |
| POST | /issuing/programs/{id}/terminate | SUNSETTING → TERMINATED with cascades | ProgramManager |
| GET | /issuing/programs/{id}/economics | Computed monthly program economics | FinanceController, PlatformAdmin |
| POST | /issuing/programs/{id}/bin-ranges | Create a BIN range under a program | ProgramManager |
| GET | /issuing/programs/{id}/bin-ranges | List BIN ranges under a program | ProgramManager, ComplianceOfficer, OperationsAnalyst, PlatformAdmin |
| GET | /issuing/bin-ranges/{id} | Get a BIN range | ProgramManager, OperationsAnalyst, PlatformAdmin |
| POST | /issuing/bin-ranges/{id}/freeze | ACTIVE → FROZEN | ProgramManager |
| POST | /issuing/bin-ranges/{id}/unfreeze | FROZEN → ACTIVE | ProgramManager |
| POST | /issuing/bin-ranges/{id}/retire | ACTIVE, FROZEN, or DEPLETED → RETIRED | ProgramManager |
| POST | /issuing/vendors | Register a production vendor | PlatformAdmin |
| GET | /issuing/vendors/{id} | Get a vendor | ProgramManager, OperationsAnalyst, PlatformAdmin |
| GET | /issuing/vendors/{id}/production-batches | List batches delegated to a vendor | ProgramManager, OperationsAnalyst, PlatformAdmin |
| POST | /issuing/programs/{id}/production-batches | Create a production batch (PLANNED) | OperationsAnalyst |
| GET | /issuing/programs/{id}/production-batches | List batches under a program | ProgramManager, OperationsAnalyst, FinanceController, PlatformAdmin |
| GET | /issuing/production-batches/{id} | Get a batch | ProgramManager, OperationsAnalyst, FinanceController, PlatformAdmin |
| POST | /issuing/production-batches/{id}/submit | PLANNED → SUBMITTED | OperationsAnalyst |
| POST | /issuing/production-batches/{id}/start | SUBMITTED → IN_PRODUCTION | OperationsAnalyst |
| POST | /issuing/production-batches/{id}/mark_shipped | IN_PRODUCTION → SHIPPED (books batch cost) | OperationsAnalyst |
| POST | /issuing/production-batches/{id}/mark_delivered | SHIPPED → DELIVERED | OperationsAnalyst |
| POST | /issuing/production-batches/{id}/cancel | PLANNED or SUBMITTED → CANCELLED | OperationsAnalyst |
| POST | /issuing/production-batches/{id}/mark_failed | IN_PRODUCTION → FAILED | OperationsAnalyst |
| POST | /issuing/accounts | Create a card account (ONBOARDING) | ProgramManager |
| GET | /issuing/accounts | List card accounts | ProgramManager, OperationsAnalyst, FinanceController, PlatformAdmin |
| GET | /issuing/accounts/{id} | Get a card account | ProgramManager, OperationsAnalyst, FinanceController, PlatformAdmin |
| GET | /issuing/programs/{id}/accounts | List accounts under a program | ProgramManager, OperationsAnalyst, FinanceController, PlatformAdmin |
| PUT | /issuing/accounts/{id} | Update account parameters (OCC-guarded) | ProgramManager |
| POST | /issuing/accounts/{id}/activate | ONBOARDING → OPEN | ProgramManager |
| POST | /issuing/accounts/{id}/suspend | OPEN → SUSPENDED (cascades cards) | ProgramManager |
| POST | /issuing/accounts/{id}/resume | SUSPENDED → OPEN (cascades cards) | ProgramManager |
| POST | /issuing/accounts/{id}/close | OPEN or SUSPENDED → CLOSED (zero balance required) | ProgramManager |
| POST | /issuing/accounts/{id}/fund | Credit available balance | FinanceController, PlatformAdmin |
| POST | /issuing/accounts/{id}/cards | Issue a card against an account | ProgramManager |
| GET | /issuing/cards/{id} | Get a card | ProgramManager, OperationsAnalyst, CardholderOps, PlatformAdmin |
| GET | /issuing/accounts/{id}/cards | List cards under an account | ProgramManager, OperationsAnalyst, CardholderOps, PlatformAdmin |
| GET | /issuing/bin-ranges/{id}/cards | List cards issued from a BIN range | ProgramManager, OperationsAnalyst, PlatformAdmin |
| GET | /issuing/cards | Flat card list with relationship filters | ProgramManager, OperationsAnalyst, PlatformAdmin |
| POST | /issuing/cards/{id}/activate | ISSUED → ACTIVE (consumes activation token) | CardholderOps |
| POST | /issuing/cards/{id}/suspend | ACTIVE → SUSPENDED | ProgramManager |
| POST | /issuing/cards/{id}/resume | SUSPENDED → ACTIVE | ProgramManager |
| POST | /issuing/cards/{id}/cancel | ISSUED, ACTIVE, or SUSPENDED → CANCELLED | ProgramManager |
| POST | /issuing/cards/{id}/mark_compromised | ACTIVE → COMPROMISED | ComplianceOfficer |
| POST | /issuing/cards/{id}/pin | Set or change PIN | CardholderOps |
| POST | /issuing/cards/{id}/pin_reset_request | BLOCKED → RESET_PENDING | CardholderOps |
| POST | /issuing/cards/{id}/pin_block | SET → BLOCKED (test-driving) | PlatformAdmin |
| POST | /issuing/cards/{id}/authorizations | Create an authorization event | CardholderOps, PlatformAdmin |
| GET | /issuing/cards/{id}/authorizations | List authorization events for a card | ProgramManager, OperationsAnalyst, ComplianceOfficer, PlatformAdmin |
| GET | /issuing/accounts/{id}/authorization-events | List authorization events for an account | ProgramManager, OperationsAnalyst, ComplianceOfficer, PlatformAdmin |
| GET | /issuing/programs/{id}/authorization-events | List authorization events under a program | ProgramManager, OperationsAnalyst, ComplianceOfficer, PlatformAdmin |
| GET | /issuing/authorization-rules/{id}/authorization-events | List authorization events decided by a rule | ComplianceOfficer, PlatformAdmin |
| GET | /issuing/cards/{id}/activation-tokens | List activation tokens for a card | CardholderOps, PlatformAdmin |
| POST | /issuing/authorization-events/{id}/settle | Settle an approved authorization (creates a settlement) | PlatformAdmin, FinanceController |
| GET | /issuing/authorization-events/{id} | Get an authorization event | FinanceController, PlatformAdmin, ProgramManager, ComplianceOfficer |
| GET | /issuing/authorization-events/{id}/settlements | List settlements for an authorization event | FinanceController, PlatformAdmin |
| GET | /issuing/settlements/{id} | Get a settlement | FinanceController, PlatformAdmin |
| GET | /issuing/cards/{id}/settlements | List settlements for a card | FinanceController, PlatformAdmin |
| GET | /issuing/accounts/{id}/settlements | List settlements for an account | FinanceController, PlatformAdmin |
| POST | /issuing/authorization-rules | Create an authorization rule (DRAFT) | ComplianceOfficer |
| GET | /issuing/authorization-rules | List authorization rules | ComplianceOfficer, ProgramManager, PlatformAdmin |
| GET | /issuing/authorization-rules/{id} | Get an authorization rule | ComplianceOfficer, ProgramManager, PlatformAdmin |
| PUT | /issuing/authorization-rules/{id} | Edit a DRAFT rule | ComplianceOfficer |
| POST | /issuing/authorization-rules/{id}/activate | DRAFT → ACTIVE (OCC-guarded) | ComplianceOfficer |
| POST | /issuing/authorization-rules/{id}/retire | DRAFT or ACTIVE → RETIRED | ComplianceOfficer |
| POST | /issuing/mandates | Announce a network mandate | ComplianceOfficer |
| GET | /issuing/mandates | List mandates | ComplianceOfficer, ProgramManager, PlatformAdmin |
| GET | /issuing/mandates/{id} | Get a mandate | ComplianceOfficer, ProgramManager, PlatformAdmin |
| POST | /issuing/mandates/{id}/retire | ANNOUNCED or EFFECTIVE → RETIRED (cascades acks) | ComplianceOfficer |
| POST | /issuing/mandates/{id}/acks | Create a mandate acknowledgement (DRAFT) | ComplianceOfficer |
| GET | /issuing/mandates/{id}/acks | List acknowledgements for a mandate | ComplianceOfficer, ProgramManager, PlatformAdmin |
| GET | /issuing/mandates/{id}/acks/{id} | Get an acknowledgement | ComplianceOfficer, ProgramManager, PlatformAdmin |
| POST | /issuing/mandates/{id}/acks/{id}/submit | DRAFT or RETURNED → SUBMITTED | ComplianceOfficer |
| POST | /issuing/mandates/{id}/acks/{id}/return | SUBMITTED → RETURNED (SoD enforced) | ComplianceOfficer |
| POST | /issuing/mandates/{id}/acks/{id}/verify | SUBMITTED → VERIFIED (SoD and deadline enforced) | ComplianceOfficer |
| POST | /issuing/mandates/{id}/acks/{id}/reject | SUBMITTED → REJECTED (SoD enforced) | ComplianceOfficer |
| GET | /issuing/programs/{id}/mandate-acks | List acknowledgements referencing a program | ComplianceOfficer, ProgramManager, PlatformAdmin |
| POST | /issuing/programs/{id}/reissue-campaigns | Create a reissue campaign (DRAFT) | OperationsAnalyst |
| GET | /issuing/programs/{id}/reissue-campaigns | List campaigns for a program | ProgramManager, OperationsAnalyst, FinanceController, PlatformAdmin |
| GET | /issuing/reissue-campaigns/{id} | Get a campaign | ProgramManager, OperationsAnalyst, FinanceController, PlatformAdmin |
| GET | /issuing/reissue-campaigns/{id}/cards | List successor cards minted by a campaign | ProgramManager, OperationsAnalyst, PlatformAdmin |
| POST | /issuing/reissue-campaigns/{id}/schedule | DRAFT → SCHEDULED (recomputes selection) | OperationsAnalyst |
| POST | /issuing/reissue-campaigns/{id}/cancel | DRAFT or SCHEDULED → CANCELLED | OperationsAnalyst |
| POST | /issuing/programs/{id}/conversion-jobs | Schedule a conversion job | ProgramManager |
| GET | /issuing/programs/{id}/conversion-jobs | List conversion jobs for a program | ProgramManager, PlatformAdmin |
| GET | /issuing/conversion-jobs/{id} | Get a conversion job | ProgramManager, PlatformAdmin |
| POST | /issuing/conversion-jobs/{id}/cancel | SCHEDULED → CANCELLED (SoD enforced) | ProgramManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of Sections 2 and 3; this catalogue is the index of identifiers and statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_MISSING_OCC_FIELD | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_PROGRAM_NO_ACTIVE_BIN | 409 |
| ERR_MANDATE_ACK_IN_FLIGHT | 409 |
| ERR_PROGRAM_BATCH_IN_FLIGHT | 409 |
| ERR_PROGRAM_HAS_OPEN_ACCOUNTS | 409 |
| ERR_CONVERSION_NOT_COMPLETED | 409 |
| ERR_CONVERSION_IN_FLIGHT | 409 |
| ERR_PROGRAM_NOT_LIVE | 409 |
| ERR_PROGRAM_NOT_EDITABLE | 409 |
| ERR_PROGRAM_RULES_LOCKED | 409 |
| ERR_BIN_HAS_ALLOCATED_PANS | 409 |
| ERR_NO_BIN_CAPACITY | 409 |
| ERR_BIN_NOT_IN_WINDOW | 409 |
| ERR_VENDOR_INACTIVE | 409 |
| ERR_VENDOR_NETWORK_MISMATCH | 409 |
| ERR_VENDOR_CAPACITY_EXCEEDED | 409 |
| ERR_VENDOR_BATCH_OVERLAP | 409 |
| ERR_BATCH_DATE_PAST | 409 |
| ERR_FULFILLED_EXCEEDS_REQUESTED | 409 |
| ERR_ACCOUNT_NOT_OPEN | 409 |
| ERR_ACCOUNT_TERMINAL_STATE | 409 |
| ERR_ACCOUNT_BALANCE_NONZERO | 409 |
| ERR_CARD_TERMINAL_STATE | 409 |
| ERR_ACTIVATION_TOKEN_INVALID | 409 |
| ERR_PIN_NOT_SET | 409 |
| ERR_PIN_FORMAT_INVALID | 400 |
| ERR_INSUFFICIENT_FUNDS | 409 |
| ERR_VELOCITY_EXCEEDED | 409 |
| ERR_DAILY_CAP_EXCEEDED | 409 |
| ERR_SOD_SAME_USER | 409 |
| ERR_MANDATE_DEADLINE_PASSED | 409 |
| ERR_MANDATE_HAS_OPEN_ACKS | 409 |
| ERR_CAMPAIGN_DATE_PAST | 409 |
| ERR_CAMPAIGN_EMPTY_SELECTION | 409 |
| ERR_CONVERSION_DATE_PAST | 409 |
| ERR_CONVERSION_TARGET_INVALID | 409 |
