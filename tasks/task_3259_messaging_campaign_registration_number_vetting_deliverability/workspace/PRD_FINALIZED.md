# Messaging Deliverability API — Product Requirements Document

## 1. Introduction

Application-to-person messaging has become a regulated channel. Mobile carriers now require every brand that sends traffic over ten-digit long codes, toll-free numbers, or short codes to register its identity, declare each campaign's use case and sample content, and retain proof that every recipient opted in. Platforms that onboard thousands of customer organizations must therefore operate a registration, vetting, and deliverability pipeline that looks far more like a compliance ledger than a simple send API.

This document specifies the Messaging Deliverability API, a REST service mounted under `/messaging` that models exactly that pipeline. Customer organizations are represented as accounts; each account registers one or more brands whose business identity is scored and verified by carrier reviewers; campaigns declare their message use case, sample content, and a throughput path (`TEN_DLC`, `TOLL_FREE`, or `SHORT_CODE`) and pass through carrier approval; sender numbers are provisioned, ported, attached to campaigns, and released; consent records retain opt-in evidence and react to STOP keywords; and an operational "run" drains the message queue, applies deterministic carrier filtering, settles per-message and registration fees, recomputes trust scores from daily deliverability snapshots, and suspends campaigns whose spam rates breach the carrier floor.

The design goals are auditability and determinism. Every state change is an explicit transition with a named actor role; every fee is a ledger entry; every deliverability signal is a recorded event that accrues into a per-day snapshot; and a server-side logical clock (not wall-clock time) drives all temporal decisions so that carrier SLAs, retention windows, recurring billing periods, and queue staleness are reproducible. This document is the sole specification for implementers: it defines the global API contract, the role model, every entity lifecycle, every gate and fee rule, and the complete endpoint and error surface.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or carrying a role not in the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The authentication check runs before the authorization check, which runs before any resource existence check.

The platform recognizes exactly eight roles, spelled as follows:

- `PlatformAdmin` — platform operator; owns accounts, ops runs, the logical clock, and account closure. May co-own creation of brands, campaigns, and numbers, and may read every resource.
- `BrandManager` — customer-side operator managing brand identity and consent evidence. Submits brands for verification and records or revokes consent.
- `CampaignManager` — customer-side operator managing campaigns, message sends, retries, and cancellations; co-owns consent record creation.
- `CarrierReviewer` — carrier-side reviewer; verifies or fails brands, and approves or rejects campaigns.
- `NumberProvisioner` — operator provisioning, porting, activating, attaching, detaching, reinstating, and releasing sender numbers.
- `ComplianceOfficer` — compliance operator; suspends and reinstates accounts, revokes brands, suspends and reactivates campaigns, and revokes consent.
- `DeliverabilityAnalyst` — analyst computing daily deliverability snapshots; reads snapshots, messages, and feedback events.
- `SystemDriver` — test/system driver emitting simulated carrier delivery outcomes and feedback events.

For every role listed above, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity. The server never compares `X-User-ID` to any resource's `id` or foreign-key field; authorization is decided by role membership alone. This applies uniformly to `PlatformAdmin`, `BrandManager`, `CampaignManager`, `CarrierReviewer`, `NumberProvisioner`, `ComplianceOfficer`, `DeliverabilityAnalyst`, and `SystemDriver`.

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

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100; `offset` defaults to 0 and must be non-negative. Responses for list endpoints carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope. Unless a subsection says otherwise, every list is sorted by `created_at` ascending (oldest first). Filter query parameters specific to each collection (for example `status`, `brand_id`, `campaign_id`, `account_id`, `phone_number`, `kind`, `message_id`, `sender_number_id`, `consent_record_id`, `reference_type`, `reference_id`, `day_utc` where supported) narrow the result set before pagination is applied.

### 2.4. Resource Identity and Common Properties

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Accounts, brands, campaigns, sender numbers, and messages additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer starting at 1 that increments by exactly 1 on every mutation of that resource, including mutations performed as a cascade side effect of another resource's transition). Consent records, feedback events, charges, daily snapshots, and ops runs are append-style records: they carry only `id` and `created_at`, and expose neither `updated_at` nor `version`.

### 2.5. The Logical Clock

All temporal behavior in this system — retention windows, recurring billing periods, queue staleness, throughput windows, and snapshot day boundaries — is evaluated against a server-side **logical clock**, never wall-clock time. At server startup the logical clock is exactly `2026-09-01T00:00:00Z`. It advances only when a `PlatformAdmin` sets it to a supplied `to_iso8601` instant via the clock endpoint; the clock never falls back to wall-clock time and never advances on its own. The endpoint responds 200 with the new `current_utc`. A message or fee "created within the trailing 1 second" and a snapshot covering a "UTC calendar day" are always measured against this clock.

### 2.6. Precision, Rounding, and Monetary Representation

All monetary amounts are integer cents in `currency` `USD`; no rounding is ever performed on charge amounts because every fee is constructed as an integer product of segments and per-segment cent rates. Percentage metrics (`delivery_rate_pct`) are numbers with exactly 2 decimal places, rounded half up. Basis-point metrics (`block_rate_bps`, `spam_rate_bps`) are integers produced by truncating (flooring) the exact value toward zero after scaling by 10,000. Scores (`identity_score`, `trust_score`) are integers clamped into the closed range 0 through 100; no rounding is needed because every additive term is an integer. Timestamps are always ISO 8601 UTC with three fractional digits.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, both against the parent **campaign**:

- Resubmitting a campaign for carrier review (the submit action taken while the campaign is `REJECTED`) must carry `expected_campaign_version` equal to the campaign's current `version`. A resubmission legitimately replaces the prior review cycle, so a stale view of the campaign is a true conflict rather than a state precondition.
- Attaching a number to a campaign must carry `expected_campaign_version` equal to the campaign's current `version`, because attachment mutates the campaign's sender pool and a stale campaign view would silently bind the number to an outdated throughput or vetting profile.

In both cases, if the supplied `expected_campaign_version` does not match the campaign's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no state changes. The submit endpoint accepts `expected_campaign_version` as optional on the first submission from `DRAFT` (no OCC check applies there) but it is effectively required on resubmission from `REJECTED`; the attach endpoint requires it unconditionally. No other endpoint takes a version field. Both guarded operations increment the campaign's `version` by 1 when they succeed.

### 2.8. Validation Order and Nested Path Resolution

Incoming requests are checked in a fixed priority order, and the first failing check determines the rejection:

1. Authentication — headers present and role declared (`ERR_UNAUTHENTICATED`, 401).
2. Authorization — role permitted for the endpoint (`ERR_UNAUTHORIZED`, 403).
3. Existence — every path id exists and nests correctly under its parent, validated left to right (account, then brand/campaign/number/consent/message under it) (`ERR_NOT_FOUND`, 404).
4. Account gate — mutating endpoints are rejected while the account is `SUSPENDED` (`ERR_ACCOUNT_SUSPENDED`, 409) or `CLOSED` (`ERR_ACCOUNT_CLOSED`, 409); reads, account reinstate, and account close are exempt from this gate.
5. Compliance gate for sends — the campaign named by `campaign_id` must be `APPROVED`, and only then is the sender number resolved: the sender number named by `sender_number_id` must exist under the account, be `ACTIVE`, and be attached to the campaign. The campaign-approval check precedes every sender-number check, including the sender number's existence lookup.
6. Consent gate for sends — an `ACTIVE` consent record must exist for the campaign's brand and the recipient number.
7. State validity — the entity is in a valid from-state for the requested transition (`ERR_INVALID_STATE`, 409; this also surfaces `ERR_BRAND_REVOKED` for revoked brands and `ERR_MESSAGE_NOT_RETRYABLE` for non-retryable error codes where those more specific codes apply).
8. Throughput gate — the campaign's per-second send capacity must not be met or exceeded.
9. Brand gates on campaign submit — brand verified, toll-free score gate, short-code tier/geography/use-case gates, resubmission caps.
10. Temporal overlap — number-type uniqueness on attach and recipient in-flight uniqueness on send.
11. Porting prerequisites for port-in number creation (`ERR_PORT_REQUIREMENTS`, 422).
12. Geography — short-code restrictions (`ERR_SHORT_CODE_GEO`, 422).
13. Fiscal — the final monthly-number-fee rule on release is internal to the ops run and never a client-visible rejection path (`ERR_FEE_SCHEDULE`, 422).
14. Field-shape validation — required fields present, enum membership, formats, sample-message count between 1 and 5 inclusive, message body length between 1 and 1600 characters inclusive (`ERR_VALIDATION`, 400).
15. OCC — `expected_campaign_version` present on guarded endpoints and equal to the campaign's current `version` (`ERR_STALE_VERSION`, 412).

### 2.9. Hierarchical Consistency and Cascades

The resource hierarchy is account at the root; brands, campaigns, sender numbers, consent records, messages, feedback events, snapshots, charges, and ops runs all belong to exactly one account. Certain parent transitions cascade downward and always bump the affected child's `updated_at` and, where the child carries one, `version`:

- Suspending an account cascades to every `APPROVED` campaign of that account (processed in `created_at` ascending order), suspending each in turn, and then to every `ACTIVE` sender number attached to those campaigns, stamping each number's `suspended_reason` as `ACCOUNT_SUSPENDED`. Numbers attached to campaigns that are not `APPROVED`, and unattached numbers, are untouched.
- Suspending a campaign — by any cause (direct suspension, brand revocation, account cascade, or the spam-floor breach described in §3) — cascades to every `ACTIVE` sender number attached to that campaign (in `created_at` ascending order), moving each to `SUSPENDED`. The stamped `suspended_reason` is `CAMPAIGN_SUSPENDED` for direct suspension, brand revocation, and account cascade, and `SPAM_FLOOR_BREACH` when the trigger is the spam-floor check.
- Reinstating an account restores only the account itself; campaigns remain `SUSPENDED` until a `ComplianceOfficer` reactivates each one individually, and numbers follow their campaigns.
- Reactivating a campaign returns to `ACTIVE` only those numbers whose `suspended_reason` is exactly `CAMPAIGN_SUSPENDED` from that campaign's cascade; numbers suspended for any other reason stay `SUSPENDED`.
- Closing an account moves every `ACTIVE` or `SUSPENDED` sender number to `RELEASED` with `suspended_reason` set to `ACCOUNT_CLOSED`, and permanently detaches them by clearing their `campaign_id`.

### 2.10. Nested Resource Retrieval and Prefix-Level Aliases

Nested paths are validated left to right: the account id must exist, then the child id must exist and belong to that account, and so on for deeper segments; any break in the chain yields `ERR_NOT_FOUND`. In addition to the account-nested routes, every entity exposes a prefix-level single-resource route (for example, fetching a brand by id directly under the `/messaging` prefix rather than through its account) that returns the identical representation as the nested fetch, and prefix-level collection routes list each resource type across accounts with an `account_id` filter available for tenant scoping. Foreign-key reverse reachability is provided through dedicated sub-collection routes: the campaigns of a brand, the consent records of a brand, the numbers of a campaign, the messages of a campaign, the feedback events of a campaign, the messages of a number, the messages gated by a consent record, and the feedback events tied to a message are all listable from the parent resource.

### 2.11. The Charge Ledger

Every fee in the system is an immutable ledger entry — a charge — recording `kind` (one of `BRAND_VETTING`, `CAMPAIGN_REGISTRATION`, `CAMPAIGN_RECURRING`, `MESSAGE`, `CARRIER_PASSTHROUGH`, `NUMBER_MONTHLY`), `reference_type` (one of `BRAND`, `CAMPAIGN`, `MESSAGE`, `NUMBER`, identifying which entity accrued the charge), `reference_id` (the id of that accruing entity), `amount_cents` (a non-negative integer; negative amounts are never permitted), `currency` (always `USD`), and a `status` that begins as `RECORDED` and may settle to `SETTLED`. Charges are never edited, refunded, or deleted; canceling a message after it was sent leaves its message and carrier passthrough charges settled in place. The ledger exists so that per-message and per-registration pass-through fees are fully auditable against the brand, campaign, message, or number that accrued them.

## 3. Business Logic & Workflows

### 3.1. Account Lifecycle and Platform Operations

A `PlatformAdmin` creates an account by supplying the organization `name`, a `plan_tier` of `STANDARD` or `PREMIUM`, and a `country_code` of `US`, `CA`, or `GB`. The plan tier gates geographic reach for short codes and provisioning authority, and the country drives number-path availability and the short-code geographic restriction. New accounts begin `ACTIVE` with an empty `suspend_reason`.

When a compliance problem surfaces at the account level, a `ComplianceOfficer` suspends the account, supplying a `reason` that is recorded in `suspend_reason`. The account moves `ACTIVE → SUSPENDED` and the account-level cascade described in §2.9 fires: every `APPROVED` campaign of the account is suspended in creation order, and each of those campaigns' `ACTIVE` numbers is suspended with `suspended_reason` `ACCOUNT_SUSPENDED`. While an account is `SUSPENDED`, all mutating endpoints other than reinstate and close are rejected with `ERR_ACCOUNT_SUSPENDED`; while an account is `CLOSED`, any operation other than a read is rejected with `ERR_ACCOUNT_CLOSED`.

Reinstatement, again by a `ComplianceOfficer`, moves the account `SUSPENDED → ACTIVE` and clears `suspend_reason` — but deliberately does **not** restore children. Campaigns suspended by the account cascade remain `SUSPENDED` until a compliance officer reactivates each campaign individually; this asymmetric restore is the intended compliance posture. A `PlatformAdmin` may close a suspended account, moving it `SUSPENDED → CLOSED`; every `ACTIVE` or `SUSPENDED` number of the account is then released, stamped with `suspended_reason` `ACCOUNT_CLOSED` and permanently detached.

The same `PlatformAdmin` role drives the operational heartbeat of an account: the **ops run**. Each ops run stamps a new `OpsRun` record whose `run_index` is a monotone per-account counter starting at 1 on the first run and whose `executed_at` is the logical clock at execution time, then performs three duties in order — the queue drain with its staleness sweep, and the recurring-fee pass — recording how much work it did in `messages_dequeued`, `messages_stale_cancelled`, `recurring_fees_charged`, and `number_fees_charged`. The full drain and fee mechanics are specified in §3.6 and §3.7.

### 3.2. Brand Identity and Verification

A `BrandManager` (or `PlatformAdmin`) registers a brand under an account with the business's `legal_name`, `tax_id`, `business_type` (`PRIVATE_PROFIT`, `PUBLIC_PROFIT`, `NON_PROFIT`, or `SOLE_PROPRIETOR`), the registered address split across `address_line1`, `city`, `region_code`, `postal_code`, and `country_code`, a public `website_url` used in identity vetting (`website_url` is optional — it may be omitted or empty at both creation and submission, in which case it simply forgoes its scoring term below), and the program's `opt_in_mechanism` (`WEB_FORM`, `KEYWORD`, `PAPER_FORM`, or `POINT_OF_SALE`), which drives consent evidence expectations. The brand is born `DRAFT` with `identity_score` 0 and `resubmission_count` 0.

Submission by a `BrandManager` moves the brand `DRAFT → PENDING_VERIFICATION` (and, later, `UNVERIFIED → PENDING_VERIFICATION` on resubmission). Two preconditions guard submission: every required brand field must be present and non-empty — the required fields are `legal_name`, `tax_id`, `business_type`, `address_line1`, `city`, `region_code`, `postal_code`, `country_code`, and `opt_in_mechanism` (`website_url` is not among them) — and the brand's `country_code` must equal the account's `country_code`; a violation is rejected with `ERR_VALIDATION`. Each submission round does two things: it computes the brand's `identity_score`, and it records a `BRAND_VETTING` charge of 200 cents (`reference_type` `BRAND`, `reference_id` the brand's id) — every submission round is billable, including resubmissions, and resubmission does not change the score rule.

The identity score is a weighted sum built from a base of 50, applying the additive terms in exactly this order: plus 10 if `website_url` is non-empty; plus 10 if `business_type` is `PUBLIC_PROFIT`; plus 5 if `business_type` is `NON_PROFIT`; minus 20 if `business_type` is `SOLE_PROPRIETOR`; plus 10 if `tax_id` matches the EIN shape of two digits, a hyphen, then seven digits; plus 10 if `postal_code` matches the country format (for `US`, exactly five digits; for `CA`, letter-digit-letter-digit-letter-digit with no separator, such as `K1A0B1`; for `GB`, one or two letters, a digit, an optional letter or digit, a space, a digit, then two letters); and plus 5 if `opt_in_mechanism` is `WEB_FORM` or `POINT_OF_SALE`. After all terms are applied, the total is clamped into the closed range 0 to 100 — the clamp is the last step, never interleaved with the additive terms.

A `CarrierReviewer` then adjudicates. Verification moves `PENDING_VERIFICATION → VERIFIED` but only when the brand's `identity_score` is at least 60; a lower score is rejected with `ERR_BRAND_SCORE_TOO_LOW`. A verified brand may back campaign submissions. Failing verification moves `PENDING_VERIFICATION → UNVERIFIED` and increments `resubmission_count` by 1 — with one sharp edge: if the increment would bring `resubmission_count` to 3 (the resubmission cap), the brand lands directly in `REVOKED` instead of `UNVERIFIED`, exhausting its chances. A brand in `REVOKED` is terminal; any operation attempted on a revoked brand is rejected with `ERR_BRAND_REVOKED`.

A `ComplianceOfficer` may also revoke a verified brand outright (`VERIFIED → REVOKED`), supplying a `reason`. Revocation cascades: every `APPROVED` campaign backed by that brand moves to `SUSPENDED`, and the campaign cascade then suspends each of those campaigns' `ACTIVE` numbers with `suspended_reason` `CAMPAIGN_SUSPENDED`.

### 3.3. Campaign Registration and Carrier Review

A `CampaignManager` (or `PlatformAdmin`) drafts a campaign under an account by naming its backing `brand_id`, choosing a `use_case` (`MARKETING`, `TRANSACTIONAL`, `MIXED`, `ACCOUNT_NOTIFICATION`, or `LOW_VOLUME_MIXED`), writing a free-text `description` of the message flow, supplying between 1 and 5 `sample_messages` that carriers will review, authoring the mandatory `help_message` and `stop_message` reply texts, and selecting the `path_kind` — `TEN_DLC`, `TOLL_FREE`, or `SHORT_CODE` — which fixes the campaign's throughput and vetting profile. New campaigns begin `DRAFT` with `trust_score` 0, `allocated_mps` 0, an empty `rejection_reason_code`, `rejected_cycle_count` 0, and `recurring_fee_last_charge_at` unset.

Submitting a campaign (from `DRAFT`, or from `REJECTED` as a resubmission) is the densest gate in the system. In order, the submit action enforces:

1. The backing brand exists and is `VERIFIED`; otherwise `ERR_BRAND_NOT_VERIFIED`. On resubmission the brand must *still* be verified.
2. If `path_kind` is `TOLL_FREE`, the brand's `identity_score` must be at least 75; otherwise `ERR_TOLLFREE_VETTING_INSUFFICIENT`.
3. If `path_kind` is `SHORT_CODE`, the account's `plan_tier` must be `PREMIUM` and its `country_code` must be `US` (otherwise `ERR_SHORT_CODE_GEO`), and the campaign's `use_case` must be `MARKETING` (otherwise `ERR_SHORT_CODE_USE_CASE`).
4. On resubmission only, `rejected_cycle_count` must be below 3, the campaign resubmission cap; at or above the cap the submit is rejected with `ERR_CAMPAIGN_RESUBMISSION_LIMIT`. These brand-side gates are evaluated before field-shape validation.
5. `description`, `help_message`, and `stop_message` must be non-empty and `sample_messages` must number between 1 and 5 inclusive; otherwise `ERR_VALIDATION`. The OCC rule of §2.7 applies last on resubmission: the request must carry `expected_campaign_version` matching the campaign's current `version`, else `ERR_STALE_VERSION` (HTTP 412).

A successful submit moves the campaign `DRAFT → PENDING_REVIEW` (or `REJECTED → PENDING_REVIEW`), initializes or recomputes `trust_score` and `allocated_mps` per §3.4, records a `CAMPAIGN_REGISTRATION` charge of 1500 cents — resubmission is billable too — and increments the campaign's `version` by 1.

Carrier adjudication is then in the `CarrierReviewer`'s hands. Approval moves `PENDING_REVIEW → APPROVED` unconditionally. Rejection moves `PENDING_REVIEW → REJECTED` and requires a `rejection_reason_code` drawn from exactly `CONTENT_VIOLATION`, `MISSING_CONSENT_FLOW`, `BRAND_MISMATCH`, or `SAMPLE_MESSAGE_INSUFFICIENT`; any other code is rejected with `ERR_REJECTION_REASON_INVALID` (HTTP 400), and per the general field-shape rule an invalid code also satisfies `ERR_VALIDATION`. The code is recorded on the campaign and `rejected_cycle_count` increments by 1.

After approval, a `ComplianceOfficer` may suspend the campaign (`APPROVED → SUSPENDED`, with a `reason` input accepted), which fires the campaign cascade of §2.9. Reactivation (`SUSPENDED → APPROVED`) is likewise a compliance action with two preconditions checked in order: the account must be `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`) and the backing brand must be `VERIFIED` (else `ERR_BRAND_NOT_VERIFIED`). On reactivation, numbers whose `suspended_reason` is exactly `CAMPAIGN_SUSPENDED` return to `ACTIVE`; numbers suspended for any other reason remain `SUSPENDED`.

Finally, a `CampaignManager` may deactivate a campaign from `DRAFT`, `REJECTED`, or `APPROVED`, moving it to the terminal `DEACTIVATED` state — but only while no `ACTIVE` sender number is attached to it; if one is, the request fails with `ERR_CAMPAIGN_NOT_DEACTIVATABLE`. Deactivation is how a campaign that will never (or no longer) send is retired from review circulation.

### 3.4. Trust Scores and Throughput Allocation

A campaign's `trust_score` begins at submission. For a `TEN_DLC` campaign the initial `trust_score` equals the backing brand's `identity_score`; for `TOLL_FREE` and `SHORT_CODE` campaigns the initial `trust_score` is a flat 50 — those paths ignore trust for throughput entirely. The score is not static: every daily snapshot recomputes it, as described in §3.8.

Throughput — `allocated_mps`, the approved ceiling in messages per second — is derived from `path_kind` at submit and re-derived on every read of the campaign:

- A `SHORT_CODE` campaign is allocated a flat 100 messages per second; `trust_score` is ignored entirely.
- A `TOLL_FREE` campaign is allocated a flat 3 messages per second; the path is gated at submit by the vetting score instead (§3.3).
- A `TEN_DLC` campaign is tiered on `trust_score` with **inclusive** tier boundaries: a score of at least 75 allocates 10 messages per second; otherwise a score of at least 50 allocates 3; otherwise a score of at least 25 allocates 1; otherwise 0 — the campaign cannot send. A score of exactly 75 lands in the 10-per-second tier, not the 3-per-second tier.

Because `trust_score` moves with each snapshot and `allocated_mps` is re-derived from it, a `TEN_DLC` campaign's effective ceiling rises and falls with its deliverability behavior — good days lift it, block- and spam-heavy days drag it down.

### 3.5. Sender Numbers: Provisioning, Porting, Attachment, and Release

Numbers are provisioned by a `NumberProvisioner` (or `PlatformAdmin`) with a `phone_number` (national or E.164 form), a `number_type` (`TEN_DLC`, `TOLL_FREE`, or `SHORT_CODE`), and the number's home `country_code`. The system normalizes `phone_number` into the E.164 `e164` address. The `provisioning_source` is derived, not supplied: if `port_phone_number` is present the number is a `PORT_IN`; otherwise a `SHORT_CODE` number is a `SHORT_CODE_ORDER`; anything else is a `NEW_PURCHASE`. New purchases and short-code orders begin `PENDING`; port-ins skip `PENDING` and begin directly in `PORTING` with `port_requested_at` stamped at creation.

Each number type carries a fixed `base_mps` throughput from the number-type constant table; notably, a `SHORT_CODE` number's base throughput ignores the campaign tier entirely.

Two creation-time gates apply. Geography first: a `SHORT_CODE` number may only be provisioned for an account whose `country_code` is `US` and whose `plan_tier` is `PREMIUM`; otherwise creation fails with `ERR_SHORT_CODE_GEO` (422). Porting prerequisites second: a `PORT_IN` request must supply `port_phone_number`, `port_letter_of_agency` (the LOA document reference), and `port_losing_carrier` (the current carrier name), and the number's `country_code` must match the account's `country_code`; any gap fails with `ERR_PORT_REQUIREMENTS` (422).

The number lifecycle then proceeds:

- A `PENDING` (non-port) number is activated by a `NumberProvisioner` (`PENDING → ACTIVE`). Activating a port-in through this route is rejected with `ERR_INVALID_STATE` — porting numbers activate only by completing the port.
- A `PORTING` number is completed by a `NumberProvisioner` (`PORTING → ACTIVE`) or failed (`PORTING → FAILED`, with a `reason` input accepted).
- Numbers move `ACTIVE → SUSPENDED` only through system cascades — campaign suspension, account suspension, or a spam-floor breach — which stamp `suspended_reason` as `CAMPAIGN_SUSPENDED`, `ACCOUNT_SUSPENDED`, or `SPAM_FLOOR_BREACH` respectively.
- A `SUSPENDED` number returns to `ACTIVE` either automatically when its campaign is reactivated (only if its `suspended_reason` is `CAMPAIGN_SUSPENDED`), or explicitly through reinstatement by a `NumberProvisioner`. Reinstatement requires that the attached campaign, if any, is `APPROVED` (else `ERR_CAMPAIGN_NOT_APPROVED`) and that the account is `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`); on success `suspended_reason` is cleared.
- Release by a `NumberProvisioner` is terminal (`→ RELEASED`) and is available from `PENDING`, `FAILED`, `ACTIVE`, or `SUSPENDED`. Releasing a number that is attached to a campaign detaches it first by clearing its `campaign_id`; the `FAILED → RELEASED` path has no detach step because a failed number was never attachable.

**Attachment** binds an `ACTIVE` number to a campaign: the provisioner supplies the target `campaign_id` and, per §2.7, `expected_campaign_version` matching the campaign's current `version` (mismatch: `ERR_STALE_VERSION`, 412). A campaign may hold at most one `ACTIVE` number of each `number_type`; attaching a second `ACTIVE` number of a type the campaign already has is rejected with `ERR_NUMBER_TYPE_OCCUPIED`. Attachment sets the number's `campaign_id` and increments the campaign's `version` by 1. Detachment clears it again. An unattached number's `campaign_id` is empty.

**Fiscal last-resort rule on release.** Number monthly fees (§3.7) normally accrue on the 30-day cadence. Releasing a number that carries an unsettled `NUMBER_MONTHLY` charge younger than 30 days is allowed, but immediately bills one final `NUMBER_MONTHLY` charge for that number before release completes. This rule is internal to the fee schedule (`ERR_FEE_SCHEDULE`, 422, exists only as an internal inconsistency signal during the ops fee pass); it never surfaces as a client-visible rejection of a release request.

### 3.6. Consent, Sending, and the Message Lifecycle

**Consent records.** Before a campaign may send to a subscriber, consent must be on file. A `BrandManager` or `CampaignManager` records consent with the `brand_id` it scopes to, the subscriber's `phone_number` in E.164, an `evidence_url` pointing at the retained opt-in artifact, a human-readable `evidence_text` describing the capture, the `captured_at` instant, and the `consent_method` — `WEB_FORM`, `KEYWORD`, `PAPER_FORM`, `POINT_OF_SALE`, or `POST_BRAND`. When `consent_method` is `POST_BRAND`, `captured_at` must be at or after the instant the brand was verified; evidence predating verification is not acceptable on that path. The record is born `ACTIVE`, and its `retention_expires_at` is computed as `captured_at` plus 1460 days: the evidence must be retained until that instant.

Consent ends in one of two ways. A `BrandManager` or `ComplianceOfficer` may revoke a record manually, moving it `ACTIVE → REVOKED`. Or the subscriber texts a STOP keyword: a `STOP` feedback event (§3.8) revokes the matching `ACTIVE` record — the one with the same brand and phone number — stamping `revoked_at` and recording the exact keyword variant in `revoked_by_keyword`. After revocation by either path, subsequent sends from that brand to that number are rejected with `ERR_NO_CONSENT`.

**Sending.** A `CampaignManager` sends by naming the `campaign_id`, the originating `sender_number_id`, the destination `to_number`, the message `body` (1 to 1600 characters inclusive), and the simulated `carrier_code` — `ATT`, `TMO`, `VZW`, `ROGERS`, or `EE`. Acceptance is gated by a fixed gauntlet, in this order:

1. The account must be `ACTIVE` (account gate, §2.8).
2. The campaign named by `campaign_id` must exist under the account, and it must be `APPROVED`; otherwise `ERR_CAMPAIGN_NOT_APPROVED`. This campaign-approval check fires before any sender-number check — including the sender number's existence — so a send against an unapproved campaign is rejected with `ERR_CAMPAIGN_NOT_APPROVED` even when the `sender_number_id` does not resolve.
3. The sender number named by `sender_number_id` must then exist under the account, be `ACTIVE`, and be attached to this campaign; an unknown number fails with `ERR_NOT_FOUND`, a number not attached to the campaign fails with `ERR_NUMBER_NOT_ATTACHED`, and a number in the wrong state fails with `ERR_INVALID_STATE`.
4. An `ACTIVE` consent record must exist for the campaign's brand and `to_number`; otherwise `ERR_NO_CONSENT`. The accepted message's `consent_record_id` is resolved at this moment to that record.
5. Throughput: the count of this campaign's messages created within the trailing 1 second of the logical clock must be strictly below `allocated_mps`. When the count has reached exactly `allocated_mps`, the send is rejected with `ERR_THROUGHPUT_EXCEEDED` (HTTP 429) — the boundary is exclusive of the cap, so the cap-th send in the window fails.
6. The recipient must not already have an in-flight (`QUEUED`) message from this campaign; a duplicate in-flight recipient is rejected with `ERR_RECIPIENT_BUSY`.
7. Field shape: `body` between 1 and 1600 characters, `carrier_code` a declared carrier, ids present (`ERR_VALIDATION`).

On acceptance the message's segment count is computed (§3.7), the message transitions `ACCEPTED → QUEUED` immediately, and `queued_at` plus `queued_run_index` — the account's current ops-run index, or 0 if the account has never run ops — are stamped.

**Delivery outcomes.** A `SystemDriver` reports the simulated carrier outcome for a `SENT` message: `outcome` `DELIVERED` moves `SENT → DELIVERED`; `outcome` `UNDELIVERED` moves `SENT → UNDELIVERED`; `outcome` `FAILED` moves `SENT → FAILED` and requires an `error_code` drawn from the carrier error code set. The carrier error code set is defined by shape rather than by enumeration: a valid carrier error code is a string beginning with the letter `E` followed by one or more digits (for example `E30034`, `E30007`, or `E21610`); any `error_code` not matching that shape fails with `ERR_VALIDATION`. A valid code is then recorded in `failed_error_code`.

**Retry and cancel.** A `FAILED` message may be retried by a `CampaignManager`, but only when its `failed_error_code` is one of the retryable carrier codes `E30034` or `E30007`; any other failure code is rejected with `ERR_MESSAGE_NOT_RETRYABLE`. A retry returns the message to `ACCEPTED` and then immediately re-queues it (`ACCEPTED → QUEUED`), but not before re-validating consent (a revocation since the original send surfaces as `ERR_NO_CONSENT`) and re-validating throughput against the campaign's current cap (`ERR_THROUGHPUT_EXCEEDED` if the trailing-second count has reached `allocated_mps`). Alternatively, a `CampaignManager` may cancel a `QUEUED` or `FAILED` message, moving it to the terminal `STALE_CANCELLED` state; any message and carrier passthrough charges from the original send remain settled — canceling never refunds.

### 3.7. Queue Drain, Segments, and the Fee Schedule

**Queue drain.** Each ops run drains every `APPROVED` campaign's queue, processing campaigns in `created_at` ascending order. A campaign's drain capacity for one run is its `allocated_mps` multiplied by 60 — the run models a 60-second drain window. Within a campaign, candidate messages are the campaign's `QUEUED` messages ordered by `queued_at` ascending, with ties broken by `created_at` ascending, and up to capacity candidates are drained; the remainder stay queued. A message queued during run N was not a candidate of run N and first becomes drainable in run N+1. The run's `messages_dequeued` counts drained messages.

At drain time, simulated **carrier filtering** decides each message's fate deterministically. A drained message becomes `FILTERED` when any of these holds: the campaign path is `TEN_DLC`, the carrier is `ATT`, and the body is longer than 160 characters; or the carrier is `TMO` and the body contains the substring `FREE`; or the originating number is `TOLL_FREE` and the backing brand's `identity_score` is below 75 (a legacy port-in edge unreachable through the gated submit). Every other drained message becomes `SENT`. Filter evaluation happens **before** charge recording, so a `FILTERED` message accrues only its `MESSAGE` charge — no carrier passthrough — while a `SENT` message accrues both a `MESSAGE` charge and a `CARRIER_PASSTHROUGH` charge, each with `reference_type` `MESSAGE` and `reference_id` the message's id.

After the per-campaign drains, a **staleness sweep** runs: any message still `QUEUED` whose age in runs — the current `run_index` minus its `queued_run_index` — has reached 3 runs is moved to `STALE_CANCELLED`. Stale-cancelled messages record no charges. The sweep count lands in the run's `messages_stale_cancelled`.

**Segments and per-message fees.** The encoding of a body is GSM-7 exactly when every character belongs to the GSM-7 basic character set; otherwise the body is treated as UCS-2. The computed `segments` count is the body length divided by 160 for GSM-7, or by 70 for UCS-2, each rounded up to a whole number, with a minimum of 1 segment. Fees are computed in a pinned order: first the segment count for the message, then the per-segment products, then the sum — never an average rate times total segments. The `MESSAGE` charge is the segment count times 75 cents. The `CARRIER_PASSTHROUGH` charge is the segment count times the carrier's per-segment rate: 40 cents for `ATT`, 35 for `TMO`, 45 for `VZW`, 50 for `ROGERS`, and 55 for `EE`. When a message runs longer than 3 segments, a one-time long-message surcharge of 50 cents is added to the message's fee **once**, after the per-segment sum. All amounts are integer cents by construction; no rounding is performed.

**Registration and recurring fees.** Brand submission rounds bill 200 cents of `BRAND_VETTING` each, and campaign submission rounds bill 1500 cents of `CAMPAIGN_REGISTRATION` each, as described in §3.2 and §3.3. The recurring pass inside each ops run then walks the account's `APPROVED` campaigns in `created_at` ascending order: for each campaign whose `recurring_fee_last_charge_at` is unset (first run since approval) or whose logical-clock now is at least 30 days past `recurring_fee_last_charge_at`, a `CAMPAIGN_RECURRING` charge of 1000 cents is recorded and `recurring_fee_last_charge_at` is stamped to the clock. The cadence is keyed on the trailing window from the last charge, **not** on calendar months — two runs 30 or more days apart each charge exactly once — and `recurring_fees_charged` counts how many campaign charges the run emitted. The same pass bills numbers: for each sender number in `ACTIVE` or `SUSPENDED` status (suspended numbers are still billed) that became `ACTIVE` at least 30 days ago and has no `NUMBER_MONTHLY` charge within the trailing 30 days, a `NUMBER_MONTHLY` charge is recorded at the type's monthly rate — 200 cents for `TEN_DLC`, 300 cents for `TOLL_FREE`, and 100000 cents for `SHORT_CODE` — and `number_fees_charged` counts them.

### 3.8. Feedback, Daily Snapshots, and the Spam Floor

**Feedback events.** Carriers and subscribers talk back through feedback events, recorded by the `SystemDriver` with a `campaign_id` and a `kind` of `BLOCK`, `SPAM_COMPLAINT`, or `STOP`. For `BLOCK` and `SPAM_COMPLAINT`, a `message_id` is required and the message must belong to the named campaign. For `STOP`, `message_id` is left empty and instead the `keyword` the subscriber sent and the subscriber's `to_number` are required. A feedback event is born `RECORDED` and applied within the same request, ending `APPLIED`. Application means: a `STOP` event revokes the matching `ACTIVE` consent record — same brand as the campaign, same phone number as `to_number` — stamping `revoked_at` and setting `revoked_by_keyword` to the sent `keyword`; a `BLOCK` or `SPAM_COMPLAINT` event accrues to the campaign's daily snapshot counters for the event's UTC day, and the spam-floor and suspension checks are re-evaluated.

**Daily snapshots.** A `DeliverabilityAnalyst` (or `PlatformAdmin`) computes a snapshot for a campaign and a UTC calendar `day_utc` (a `YYYY-MM-DD` string). The snapshot aggregates: `attempted` counts the campaign's messages created on that day whose status is in the terminal-send set `SENT`, `DELIVERED`, `UNDELIVERED`, `FILTERED`, or `FAILED` — `ACCEPTED`, `QUEUED`, and `STALE_CANCELLED` messages are excluded; `delivered` counts the subset in `DELIVERED`; `blocked` counts the campaign's `BLOCK` feedback events of that day; `spam` counts its `SPAM_COMPLAINT` events of that day. Derived rates follow: when `attempted` is zero, `delivery_rate_pct`, `block_rate_bps`, and `spam_rate_bps` are all 0. Otherwise `delivery_rate_pct` is 100 times `delivered` divided by `attempted`, rounded half-up to two decimals; `block_rate_bps` is 10,000 times `blocked` divided by `attempted`, floored to an integer; and `spam_rate_bps` is 10,000 times `spam` divided by `attempted`, floored to an integer.

**Trust recompute.** Snapshot creation also recomputes the campaign's `trust_score`, applying snapshots in chronological `day_utc` order — a day with no snapshot produces no adjustment. Per snapshot, the recompute starts from the current `trust_score` and applies penalties **before** the good-day bonus, clamping last: minus 5 if the snapshot's `block_rate_bps` is at least 300; minus 15 if its `spam_rate_bps` is at least 100; then plus 2 if the snapshot's `attempted` is at least 1000 and its `spam_rate_bps` is below 100. The result is clamped into the closed range 0 to 100. The recompute mutates the campaign, so the campaign's `version` increments and `updated_at` refreshes — a campaign read after a heavy snapshot day reflects the new score and, for `TEN_DLC`, the re-derived `allocated_mps` of §3.4.

**The spam floor.** Immediately after the trust recompute, the spam-floor check runs: if the snapshot's `attempted` is at least 2000 **and** its `spam_rate_bps` is at least 300 — both boundaries inclusive, so exactly 2000 attempts with exactly 300 basis points suspends — the campaign moves to `SUSPENDED` for reason `SPAM_FLOOR`, and the campaign cascade suspends each attached `ACTIVE` number with `suspended_reason` `SPAM_FLOOR_BREACH`. Recovery from a spam-floor suspension is the compliance reactivation path of §3.3; note that numbers suspended with `SPAM_FLOOR_BREACH` do **not** auto-restore on campaign reactivation — each must be reinstated individually by a `NumberProvisioner`.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; all other successful operations — state transitions, reads, and list retrievals — return HTTP 200. The table below is a navigational index only: request payloads, response bodies, preconditions, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/messaging/accounts` | Create an Account | PlatformAdmin |
| GET | `/messaging/accounts/{id}` | Get an Account | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, NumberProvisioner, CarrierReviewer, SystemDriver |
| GET | `/messaging/accounts` | List Accounts | PlatformAdmin, ComplianceOfficer |
| POST | `/messaging/accounts/{id}/suspend` | Suspend an account; cascades to campaigns and numbers | ComplianceOfficer |
| POST | `/messaging/accounts/{id}/reinstate` | Reinstate a suspended account (children not auto-restored) | ComplianceOfficer |
| POST | `/messaging/accounts/{id}/close` | Close a suspended account; releases all numbers | PlatformAdmin |
| POST | `/messaging/accounts/{id}/run_ops` | Ops checkpoint: drain queues, staleness sweep, recurring/number fees | PlatformAdmin |
| GET | `/messaging/accounts/{id}/ops_runs` | List ops runs for an account | PlatformAdmin, ComplianceOfficer |
| GET | `/messaging/brands/{id}` | Get a Brand by id (prefix-level alias) | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, CarrierReviewer |
| GET | `/messaging/campaigns/{id}` | Get a Campaign by id | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, NumberProvisioner, CarrierReviewer, SystemDriver |
| GET | `/messaging/numbers/{id}` | Get a SenderNumber by id | PlatformAdmin, ComplianceOfficer, CampaignManager, NumberProvisioner, CarrierReviewer |
| GET | `/messaging/consent_records/{id}` | Get a ConsentRecord by id | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, CarrierReviewer |
| GET | `/messaging/messages/{id}` | Get a Message by id | PlatformAdmin, ComplianceOfficer, CampaignManager, CarrierReviewer, SystemDriver |
| GET | `/messaging/feedback_events/{id}` | Get a FeedbackEvent by id | PlatformAdmin, ComplianceOfficer, CampaignManager, CarrierReviewer |
| GET | `/messaging/snapshots/{id}` | Get a DailySnapshot by id | PlatformAdmin, ComplianceOfficer, DeliverabilityAnalyst |
| GET | `/messaging/ops_runs/{id}` | Get an OpsRun by id | PlatformAdmin, ComplianceOfficer |
| GET | `/messaging/brands` | List brands across accounts | PlatformAdmin, ComplianceOfficer |
| GET | `/messaging/campaigns` | List campaigns across accounts | PlatformAdmin, ComplianceOfficer |
| GET | `/messaging/numbers` | List sender numbers across accounts | PlatformAdmin, ComplianceOfficer |
| GET | `/messaging/consent_records` | List consent records across accounts | PlatformAdmin, ComplianceOfficer |
| GET | `/messaging/messages` | List messages across accounts | PlatformAdmin, ComplianceOfficer |
| GET | `/messaging/feedback_events` | List feedback events across accounts | PlatformAdmin, ComplianceOfficer |
| GET | `/messaging/snapshots` | List daily snapshots across accounts | PlatformAdmin, ComplianceOfficer, DeliverabilityAnalyst |
| GET | `/messaging/ops_runs` | List ops runs across accounts | PlatformAdmin, ComplianceOfficer |
| POST | `/messaging/accounts/{id}/brands` | Create a Brand (DRAFT) | BrandManager, PlatformAdmin |
| GET | `/messaging/accounts/{id}/brands/{id}` | Get a Brand | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, NumberProvisioner, CarrierReviewer, SystemDriver |
| GET | `/messaging/accounts/{id}/brands/{id}/campaigns` | List campaigns of a brand | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, CarrierReviewer |
| GET | `/messaging/accounts/{id}/brands/{id}/consent_records` | List consent records of a brand | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, CarrierReviewer |
| GET | `/messaging/accounts/{id}/brands` | List Brands for an account | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, CarrierReviewer |
| POST | `/messaging/accounts/{id}/brands/{id}/submit` | Submit brand for identity verification (from DRAFT or UNVERIFIED) | BrandManager |
| POST | `/messaging/accounts/{id}/brands/{id}/verify` | Carrier verifies brand identity (score at least 60) | CarrierReviewer |
| POST | `/messaging/accounts/{id}/brands/{id}/fail` | Carrier fails brand verification; UNVERIFIED or REVOKED at cap | CarrierReviewer |
| POST | `/messaging/accounts/{id}/brands/{id}/revoke` | Revoke a verified brand; cascades campaign suspensions | ComplianceOfficer |
| POST | `/messaging/accounts/{id}/campaigns` | Create a Campaign (DRAFT) | CampaignManager, PlatformAdmin |
| GET | `/messaging/accounts/{id}/campaigns/{id}` | Get a Campaign | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, NumberProvisioner, CarrierReviewer, SystemDriver |
| GET | `/messaging/accounts/{id}/campaigns/{id}/numbers` | List numbers attached to a campaign | PlatformAdmin, ComplianceOfficer, CampaignManager, NumberProvisioner, CarrierReviewer |
| GET | `/messaging/accounts/{id}/campaigns/{id}/messages` | List messages of a campaign | PlatformAdmin, ComplianceOfficer, CampaignManager, CarrierReviewer |
| GET | `/messaging/accounts/{id}/campaigns/{id}/feedback_events` | List feedback events of a campaign | PlatformAdmin, ComplianceOfficer, CampaignManager, CarrierReviewer |
| GET | `/messaging/accounts/{id}/campaigns` | List Campaigns; brand_id filter supported | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, NumberProvisioner, CarrierReviewer |
| POST | `/messaging/accounts/{id}/campaigns/{id}/submit` | Submit campaign for carrier review; OCC-guarded on resubmit | CampaignManager |
| POST | `/messaging/accounts/{id}/campaigns/{id}/approve` | Carrier approves campaign | CarrierReviewer |
| POST | `/messaging/accounts/{id}/campaigns/{id}/reject` | Carrier rejects campaign with reason code | CarrierReviewer |
| POST | `/messaging/accounts/{id}/campaigns/{id}/suspend` | Suspend an approved campaign; cascades to attached numbers | ComplianceOfficer |
| POST | `/messaging/accounts/{id}/campaigns/{id}/reactivate` | Reactivate a suspended campaign; restores cascade-suspended numbers | ComplianceOfficer |
| POST | `/messaging/accounts/{id}/campaigns/{id}/deactivate` | Deactivate a campaign with no ACTIVE numbers attached | CampaignManager |
| POST | `/messaging/accounts/{id}/numbers` | Provision a number (new purchase or port-in) | NumberProvisioner, PlatformAdmin |
| GET | `/messaging/accounts/{id}/numbers/{id}` | Get a SenderNumber | PlatformAdmin, ComplianceOfficer, CampaignManager, NumberProvisioner, CarrierReviewer, SystemDriver |
| GET | `/messaging/accounts/{id}/numbers/{id}/messages` | List messages sent from a number | PlatformAdmin, ComplianceOfficer, CampaignManager, NumberProvisioner, CarrierReviewer |
| GET | `/messaging/accounts/{id}/numbers` | List numbers; campaign_id filter supported | PlatformAdmin, ComplianceOfficer, CampaignManager, NumberProvisioner, CarrierReviewer |
| POST | `/messaging/accounts/{id}/numbers/{id}/activate` | Activate a PENDING (non-port) number | NumberProvisioner |
| POST | `/messaging/accounts/{id}/numbers/{id}/complete_port` | Complete a port-in (PORTING → ACTIVE) | NumberProvisioner |
| POST | `/messaging/accounts/{id}/numbers/{id}/fail_port` | Fail a port-in (PORTING → FAILED) | NumberProvisioner |
| POST | `/messaging/accounts/{id}/numbers/{id}/attach` | Attach an ACTIVE number to a campaign; OCC-guarded | NumberProvisioner |
| POST | `/messaging/accounts/{id}/numbers/{id}/detach` | Detach a number from its campaign | NumberProvisioner |
| POST | `/messaging/accounts/{id}/numbers/{id}/reinstate` | Reinstate a suspended number | NumberProvisioner |
| POST | `/messaging/accounts/{id}/numbers/{id}/release` | Release a number (from PENDING/FAILED/ACTIVE/SUSPENDED) | NumberProvisioner |
| POST | `/messaging/accounts/{id}/consent_records` | Record opt-in consent with retained evidence | BrandManager, CampaignManager |
| GET | `/messaging/accounts/{id}/consent_records/{id}` | Get a ConsentRecord | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, CarrierReviewer |
| GET | `/messaging/accounts/{id}/consent_records/{id}/messages` | List messages gated by a consent record | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, CarrierReviewer |
| GET | `/messaging/accounts/{id}/consent_records` | List consent records; brand_id and phone_number filters | PlatformAdmin, ComplianceOfficer, BrandManager, CampaignManager, CarrierReviewer |
| POST | `/messaging/accounts/{id}/consent_records/{id}/revoke` | Manually revoke consent | BrandManager, ComplianceOfficer |
| POST | `/messaging/accounts/{id}/messages` | Send a message: compliance, consent, throughput gates, then QUEUED | CampaignManager |
| GET | `/messaging/accounts/{id}/messages/{id}` | Get a Message | PlatformAdmin, ComplianceOfficer, CampaignManager, CarrierReviewer, SystemDriver |
| GET | `/messaging/accounts/{id}/messages/{id}/feedback_events` | List feedback events tied to a message | PlatformAdmin, ComplianceOfficer, CampaignManager, CarrierReviewer |
| GET | `/messaging/accounts/{id}/messages` | List messages; campaign_id and status filters | PlatformAdmin, ComplianceOfficer, CampaignManager, CarrierReviewer |
| POST | `/messaging/accounts/{id}/messages/{id}/delivery_outcome` | Simulated carrier outcome for a SENT message | SystemDriver |
| POST | `/messaging/accounts/{id}/messages/{id}/retry` | Retry a FAILED message with a retryable error code | CampaignManager |
| POST | `/messaging/accounts/{id}/messages/{id}/cancel` | Cancel a QUEUED or FAILED message | CampaignManager |
| POST | `/messaging/accounts/{id}/feedback_events` | Record carrier/user feedback: BLOCK, SPAM_COMPLAINT, or STOP | SystemDriver |
| GET | `/messaging/accounts/{id}/feedback_events` | List feedback events; campaign_id and kind filters | PlatformAdmin, ComplianceOfficer, CampaignManager, CarrierReviewer |
| POST | `/messaging/accounts/{id}/campaigns/{id}/snapshots` | Compute daily snapshot; recomputes trust_score; may trigger spam-floor suspension | DeliverabilityAnalyst, PlatformAdmin |
| GET | `/messaging/accounts/{id}/campaigns/{id}/snapshots/{id}` | Get a DailySnapshot | PlatformAdmin, ComplianceOfficer, CampaignManager, DeliverabilityAnalyst |
| GET | `/messaging/accounts/{id}/campaigns/{id}/snapshots` | List snapshots for a campaign | PlatformAdmin, ComplianceOfficer, CampaignManager, DeliverabilityAnalyst |
| GET | `/messaging/accounts/{id}/charges` | List charges (fee pass-through ledger) | PlatformAdmin, ComplianceOfficer, CampaignManager |
| GET | `/messaging/charges` | List charges across accounts | PlatformAdmin, ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions for each code are specified in the narratives of §2 and §3 where the guarded behavior lives.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_ACCOUNT_SUSPENDED | 409 |
| ERR_ACCOUNT_CLOSED | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_BRAND_SCORE_TOO_LOW | 409 |
| ERR_BRAND_NOT_VERIFIED | 409 |
| ERR_BRAND_REVOKED | 409 |
| ERR_TOLLFREE_VETTING_INSUFFICIENT | 409 |
| ERR_SHORT_CODE_GEO | 422 |
| ERR_SHORT_CODE_USE_CASE | 409 |
| ERR_CAMPAIGN_RESUBMISSION_LIMIT | 409 |
| ERR_CAMPAIGN_NOT_APPROVED | 409 |
| ERR_CAMPAIGN_NOT_DEACTIVATABLE | 409 |
| ERR_NUMBER_NOT_ATTACHED | 409 |
| ERR_NUMBER_TYPE_OCCUPIED | 409 |
| ERR_PORT_REQUIREMENTS | 422 |
| ERR_NO_CONSENT | 409 |
| ERR_THROUGHPUT_EXCEEDED | 429 |
| ERR_RECIPIENT_BUSY | 409 |
| ERR_MESSAGE_NOT_RETRYABLE | 409 |
| ERR_FEE_SCHEDULE | 422 |
| ERR_REJECTION_REASON_INVALID | 400 |







