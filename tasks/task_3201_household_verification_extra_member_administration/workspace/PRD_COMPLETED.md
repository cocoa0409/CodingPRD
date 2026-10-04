# Household Verification & Extra Member Administration API — Product Requirements Document

## 1. Introduction

Subscription streaming platforms face a persistent tension: account sharing drives growth but erodes per-household revenue, while overly aggressive enforcement alienates legitimate subscribers and drives churn. The Household Verification & Extra Member Administration API gives a platform operator the machinery to define, verify, and monetize the household boundary of an account — anchoring a household to a primary location through device network signals, challenging accounts for periodic or drift-triggered verification without locking out legitimate traveling members, and selling extra-member slots whose pricing, proration, and transfer rights follow deterministic fiscal rules.

This document specifies the API surface mounted under `/hv`. It covers account lifecycle and billing simulation, household establishment and relocation, device trust built on a household-match confidence score, verification challenge flows with accessibility fallbacks, travel passes for temporary access, profile transfer with history preservation, plan-tier entitlement enforcement at play time, regional enforcement policies with grace periods, and churn monitoring through enforcement metrics. A server-side logical clock governs all temporal reasoning so that expiry, proration, and billing-cycle behavior are fully deterministic and testable.

The intended audience is the engineering team implementing this API. All structural contracts (envelope, pagination, common fields, OCC, role enumeration) appear in §2; business rules are narrated in §3 and deliberately distributed across subsections so that any single behavior must be reconstructed from more than one passage, mirroring how such requirements arrive in a real product organization.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting principal and `X-User-Role` naming their operational capacity. The system recognizes exactly five roles: `PlatformAdmin`, `SupportAgent`, `AccountOwner`, `HouseholdMember`, and `ExtraMember`. A request missing either header, carrying an undeclared role value, or carrying an entity-backed id that does not resolve is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); for the three member-backed roles, an `X-User-ID` resolving to a member whose `member_role` does not match the declared role is likewise `ERR_UNAUTHENTICATED`. A request whose role is not listed for the endpoint — or, for the three member-backed roles, whose `X-User-ID` resolves to a member that does not belong to the target account — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics are fixed as follows:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; it may be used purely for attribution.
- When `X-User-Role` is `SupportAgent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, with no ownership comparison performed.
- When `X-User-Role` is `AccountOwner`, `X-User-ID` is the `id` of the acting `Member` whose `member_role` is `OWNER`; ownership checks on any resource that references an `Account` compare the resource's `account_id` to that member's own `account_id`.
- When `X-User-Role` is `HouseholdMember`, `X-User-ID` is the `id` of the acting `Member` whose `member_role` is `HOUSEHOLD`; ownership checks compare the target resource's account reference to that member's `account_id`.
- When `X-User-Role` is `ExtraMember`, `X-User-ID` is the `id` of the acting `Member` whose `member_role` is `EXTRA`; ownership checks follow the same account-matching rule.

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

Before any endpoint-specific rule runs, every request that carries a body must be well-formed — all required fields present, enum values within their declared sets, and datetime fields parsing as ISO 8601; a malformed body is rejected with `ERR_VALIDATION` (HTTP 400). Authentication and authorization checks (§2.1) follow, then path-identifier existence (§2.5), then optimistic-concurrency checks (§2.6), then account- and entity-level state gates, and finally the business rules narrated in §3.

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and must not exceed 100; `offset` defaults to 0 when omitted. Unless a specific endpoint narrative states otherwise, list endpoints sort results by `created_at` in ascending order, breaking ties by `id` ascending. The `meta` object of every list response includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, with `has_more` true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource (Account, Household, Member, Device, ExtraMemberSlot, VerificationChallenge, TravelPass, ProfileTransfer, EnforcementPolicy) carries a standard system-managed set of fields:

- `id` — a server-minted UUID in canonical dashed form (e.g. `550e8400-e29b-41d4-a716-446655440000`), with no type prefix embedded in the value. (Fields that are not resource `id`s — such as `recommendation_seed` — are server-minted opaque strings and do not follow this format.)
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- `version` — an integer starting at 1 on creation and incremented by 1 on every mutation, including mutations caused by cascades from other resources.

Two resource kinds are deliberately lighter: `PlaybackSession`, `Download`, and `EnforcementMetric` carry only `id` and `created_at`. Neither `updated_at` nor `version` is present on those resources, and clients must not send or expect them.

### 2.5. Nested Resource Retrieval

When an endpoint path contains more than one resource identifier, the server validates path identifiers strictly left to right — the account identifier first, then the household, member, device, or other intermediate identifier, then the final child identifier. The first identifier that fails to resolve produces the response: a missing account yields `ERR_ACCOUNT_NOT_FOUND`, a missing household yields `ERR_HOUSEHOLD_NOT_FOUND`, a missing member yields `ERR_MEMBER_NOT_FOUND`, a missing device yields `ERR_DEVICE_NOT_FOUND`, and so on for slots (`ERR_SLOT_NOT_FOUND`), challenges (`ERR_CHALLENGE_NOT_FOUND`), travel passes (`ERR_TRAVEL_PASS_NOT_FOUND`), transfers (`ERR_TRANSFER_NOT_FOUND`), sessions (`ERR_SESSION_NOT_FOUND`), downloads (`ERR_DOWNLOAD_NOT_FOUND`), and policies (`ERR_POLICY_NOT_FOUND`). Later identifiers in the path are not examined once an earlier one has failed.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to present the version of a parent resource it most recently observed, protecting decisions whose pricing or side effects depend on that parent's current state:

- Purchasing an extra-member slot for an account requires `expected_account_version` in the request body, equal to the account's current `version`. If the account's version has advanced since the client last read it, the purchase is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) — the slot's price snapshot legitimately depends on the account's current plan tier and slot index, so a purchase based on a stale account view is refused rather than silently re-priced.
- Accepting a profile transfer requires `expected_profile_transfer_version` in the request body, equal to the transfer's current `version`. A mismatch is rejected with `ERR_STALE_TRANSFER_VERSION` (HTTP 412), because acceptance moves the member and creates the target account — an accept carrying a stale transfer version must be refused before any state check runs.

Endpoints not listed above do not accept a version field; sending one has no effect.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integer cents. Wherever a fee or credit formula requires rounding, the system applies round-half-up to integer cents, and the rounding step occurs exactly where the governing formula specifies it — never earlier, never later, and never reordered (in particular, the slot-revocation credit rounds the per-day rate before multiplying by remaining days; rounding the product instead is a different and forbidden computation). Churn-rate figures, by contrast, are reported as numbers rounded half-up to exactly 4 decimal places. The household-match confidence is expressed as integer percentage points.

### 2.8. The Logical Clock

All temporal reasoning in the system — challenge expiry, travel-pass windows, download expiry, transfer expiry, proration day indices, billing-month bucketing, enforcement grace periods — is evaluated against a server-side logical clock, never the host wall clock. Before any administrative call sets it, the logical clock reads exactly 2026-09-01T00:00:00Z. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and echoes the resulting logical time back as `current_utc`; after such a call, all lazy state transitions (challenge expiry, pass expiry, download expiry, transfer expiry) re-evaluate against the new time the next time the affected resource is read or operated on. Resource timestamps (`created_at`, `updated_at`, `started_at`, `ended_at`, `recorded_at`, `last_signal_at`, and the like) are stamped from this same logical clock.

### 2.9. Lazy State Materialization

Certain lifecycle transitions are applied lazily rather than by a background scheduler: a `PENDING` verification challenge becomes `EXPIRED` the first time it is read or submitted against at or after its `expires_at`; an `ACTIVE` travel pass becomes `EXPIRED` the first time it is read or a new pass is created on the same device at or after its `ends_at`; an `ACTIVE` download becomes `EXPIRED` 30 days after its creation; an `AWAITING_ACCEPTANCE` profile transfer becomes `EXPIRED` the first time it is read or accepted against at or after its `expires_at`. Clients must treat the persisted state as authoritative only after such a read or operation has occurred.

### 2.10. Hierarchical Consistency and Cascade Semantics

Parent state changes propagate to children deterministically. Suspending an account ends every active playback session across all of its members, untrusts every trusted device of its household, and revokes each affected device's active travel passes — and each such pass revocation records a churn-signal enforcement metric on the account. Reactivating the account restores its status but not device trust: devices must re-earn trust through the normal confidence evaluation. Cancelling an account removes all of its members, ends all active sessions, and revokes all of its offered or active extra-member slots with zero credit. Dissolving a household removes all of its devices (any device not already `REMOVED`), ending each removed device's `ACTIVE` playback sessions and revoking their active travel passes. Each mutation that a cascade performs on a resource refreshes that resource's `updated_at` and, where the resource carries one, increments its `version`.

### 2.11. Enforcement Policy Exclusivity per Region

Enforcement is governed regionally through `EnforcementPolicy` resources keyed by `region_code`. At most one policy per region may be `ACTIVE` at any time: activating a `DRAFT` policy automatically retires whatever other policy for the same region is currently `ACTIVE`. A retired policy never reactivates; new behavior requires creating a fresh `DRAFT`.

## 3. Business Logic & Workflows

### 3.1. Account Onboarding, Suspension, and Cancellation

A `PlatformAdmin` opens an account by supplying its `email`, `region_code` (one of `NA`, `LATAM`, `EMEA`, `APAC`), and `plan_tier` (one of `BASIC`, `STANDARD`, `PREMIUM`). Creation performs two additional pieces of work atomically: it records `billing_anchor_day` as the creation day-of-month clamped into the range 1 through 28 — this value anchors both slot-fee proration and the monthly download allowance reset — and it creates the account's first `Member` with `member_role` `OWNER`, status `ACTIVE`, an empty `viewing_history`, and a server-minted `recommendation_seed`; the new member's id is stored back on the account as `owner_member_id`. A new account begins with `status` `ACTIVE` and `verification_posture` `VERIFIED`, and its three fiscal counters `extra_member_billed_cents`, `extra_member_credit_cents`, and `extra_member_net_revenue_cents` all read zero. The net-revenue counter is always the billed lifetime gross minus the lifetime revocation credits — it is derived on read as `extra_member_billed_cents` minus `extra_member_credit_cents` rather than stored — and is never decremented by any other event.

An account's lifecycle runs `ACTIVE` → `SUSPENDED` → `ACTIVE` as a repeatable cycle, or `ACTIVE`/`SUSPENDED` → `CANCELLED` as a one-way exit. A `PlatformAdmin` suspends an `ACTIVE` account directly, and the billing simulator (see §3.9) produces the same transition when a charge fails. Suspension triggers the full cascade described in §2.10: every `ACTIVE` playback session of every member of the account is ended (with `ended_at` set to the current logical time and each ended session decrementing its member's `current_streams`), every `TRUSTED` device of the account's household becomes `UNTRUSTED`, each such untrust revokes that device's `ACTIVE` travel passes, and each pass revocation creates an `EnforcementMetric` of `metric_type` `CHURN_SIGNAL` on the account. The account's `version` increments by 1. Reactivation returns a `SUSPENDED` account to `ACTIVE` and increments `version` by 1, but — per §2.10 — does not restore device trust. Cancellation, available to both `PlatformAdmin` and the account's own `AccountOwner` from either `ACTIVE` or `SUSPENDED`, moves the account to `CANCELLED`: all members become `REMOVED`, all active sessions end, and all slots still `OFFERED` or `ACTIVE` are revoked with `credit_cents` zero, again incrementing the account's `version` by 1.

While an account is `SUSPENDED`, new revenue or usage operations are refused with `ERR_ACCOUNT_SUSPENDED` (HTTP 409): purchasing, assigning, or re-offering extra-member slots; creating or relocating a household; adding a member; removing a member; registering or trusting a device; issuing, reissuing, or converting anything that writes (including granting a travel pass and converting one); starting playback; and creating downloads are all gated this way. Once an account is `CANCELLED`, every operation other than reads is refused with `ERR_ACCOUNT_CANCELLED` (HTTP 409); a plan-tier patch on a `CANCELLED` account is refused the same way, before the stale-version check runs. (An already-`SUSPENDED` account yields `ERR_INVALID_STATE` to a further suspend, and an already-`ACTIVE` account yields `ERR_INVALID_STATE` to reactivation; suspension is legal only from `ACTIVE`, reactivation only from `SUSPENDED`.)

Separately from `status`, each account carries a parallel dimension `verification_posture` that evolves independently through `VERIFIED`, `CHALLENGE_PENDING`, and `LOCKED`: issuing a challenge moves the posture from `VERIFIED` to `CHALLENGE_PENDING` (issuing further challenges while the posture is `CHALLENGE_PENDING` or `LOCKED` is permitted and leaves the posture unchanged); a successful submission returns it to `VERIFIED`; a lockout moves it to `LOCKED`; and a subsequent successful verification from a later challenge returns a `LOCKED` account to `VERIFIED`. Two account-level operations require the posture to be `VERIFIED` and are otherwise rejected with `ERR_ACCOUNT_NOT_VERIFIED` (HTTP 409): marking a device trusted, and assigning an extra-member slot.

A plan change is performed by `PlatformAdmin` or the `AccountOwner` by patching the account with a new `plan_tier` together with `expected_account_version`; a version mismatch is rejected with `ERR_STALE_ACCOUNT_VERSION` per §2.6, and a successful change increments the account's `version` by 1. A plan change does not require the account to be `ACTIVE` — it is allowed on a `SUSPENDED` account (though never on a `CANCELLED` one, per the gate above). Future slot purchases price at the new tier; price snapshots already stored on existing slots are never rewritten.

### 3.2. Establishing, Relocating, and Dissolving the Household

An account's household is its physical anchor. The `AccountOwner` establishes it by supplying a `label`, a `primary_location` free-text anchor, the canonical `network_fingerprint` of the home network, and the coarse `geo_cell` of the location. At most one household per account may be non-dissolved at any moment: attempting to establish a second household while one exists in any status other than `DISSOLVED` is rejected with `ERR_ACCOUNT_ALREADY_HAS_HOUSEHOLD` (HTTP 409). A household records `trusted_device_count` — the number of its child devices currently in `trust_status` `TRUSTED` — and `last_verified_at`, which stays null until the first successful verification event and is then set to the current logical time.

Moving home is a first-class operation. When the `AccountOwner` relocates the household, they supply the new `primary_location`, `network_fingerprint`, and `geo_cell`; the household must currently be `ESTABLISHED` and the owning account `ACTIVE`. The household transitions `ESTABLISHED` → `RELOCATING`, its three anchor fields are overwritten with the new values, and — exactly as under account suspension — every `TRUSTED` device becomes `UNTRUSTED`, each untrust revoking that device's `ACTIVE` travel passes and recording a `CHURN_SIGNAL` metric per revoked pass. The household returns `RELOCATING` → `ESTABLISHED` when any device of the household records a network signal whose `network_fingerprint` equals the household's new anchor; at that moment `last_verified_at` is set to the current logical time. This relocation cycle may repeat indefinitely. Dissolution, available from either `ESTABLISHED` or `RELOCATING`, moves the household to `DISSOLVED` and removes every device not already `REMOVED`, revoking their `ACTIVE` travel passes.

### 3.3. Members, Devices, and the Confidence Score

Beyond the auto-created owner, the `AccountOwner` adds household profiles by supplying a `display_name`; each such member is created with `member_role` `HOUSEHOLD` and status `ACTIVE`, an empty `viewing_history`, and a server-minted `recommendation_seed`. Members accumulate two live consumption counters: `current_streams`, the count of their playback sessions currently `ACTIVE`, and `downloads_used_this_month`, the count of their downloads created in the current billing month (formatted `YYYY-MM`) that remain `ACTIVE`; both counters are derived on read from the live sessions and downloads rather than stored on the member. Removing a non-owner member transitions them to `REMOVED` and ends any of their `ACTIVE` playback sessions; the owner member cannot be removed through this operation — attempting it is rejected with `ERR_INVALID_STATE` (HTTP 409), as is removing a member not currently `ACTIVE`.

Devices are registered under a household — the device records the household's id as its `household_id` — by any member of the account (`AccountOwner`, `HouseholdMember`, or `ExtraMember`) with a `device_label`, a `device_type` (one of `TV`, `MOBILE`, `WEB`, `CONSOLE`), and the observed `network_fingerprint` and `geo_cell`. Registration into a `DISSOLVED` household is rejected with `ERR_INVALID_STATE` (HTTP 409). A new device starts `UNTRUSTED`, with `last_signal_at` set to the creation time. Each subsequent signal — recorded by any member of the account with fresh `network_fingerprint` and `geo_cell` values — overwrites those two observed fields and refreshes `last_signal_at`; as described in §3.2, a matching fingerprint additionally settles a `RELOCATING` household back to `ESTABLISHED`.

Trust is earned through the household-match confidence score, an integer percentage computed from the device's current fields against the household's current anchor. The evaluation order is pinned to break the apparent cycle between confidence and trust: first the signal scores are computed from the device's current fields, then they are summed into the confidence value, and only then is the trust threshold applied — trust state never feeds back into the confidence being computed. A device whose `network_fingerprint` equals the household's `network_fingerprint` contributes 40 points; a device whose `geo_cell` equals the household's `geo_cell` contributes 30 points. Recency contributes a further 30 points when the last signal is at most 7 days old, 10 points when it is more than 7 but at most 30 days old, and 0 points beyond 30 days, where the signal age is the whole number of days between `last_signal_at` and the current logical time (partial days discarded). Two variants of the score exist. The strict variant caps the total at 50 when the network fingerprint does not match — so without a network match, geo plus fresh recency alone can never exceed 50 — and applies no cap otherwise. The lenient variant applies no cap at all, so geo plus fresh recency can reach 60. A computed read on any device returns the breakdown: `network_match` and `geo_match` booleans, the `recency_score` in points, and the two totals `strict_pct` and `lenient_pct`. A read of a device that does not exist yields `ERR_DEVICE_NOT_FOUND`.

Marking a device trusted is an `AccountOwner` operation with three gates, and the strict variant of the confidence score governs: the device must currently be `UNTRUSTED` (otherwise `ERR_INVALID_STATE`), its strict confidence must be at least 70, the owning account's `verification_posture` must be `VERIFIED` (otherwise `ERR_ACCOUNT_NOT_VERIFIED`), and the account must be `ACTIVE` (otherwise `ERR_ACCOUNT_SUSPENDED` or `ERR_ACCOUNT_CANCELLED`). On success the device transitions `UNTRUSTED` → `TRUSTED` and the household's `trusted_device_count` increments by 1. Because the strict variant caps a network-less device at 50, reaching the 70-point threshold in practice requires the network match. The cycle `UNTRUSTED` → `TRUSTED` → `UNTRUSTED` is repeatable: untrusting (an explicit `AccountOwner` action, or the cascades from §2.10 and §3.2) requires the device to be `TRUSTED` (otherwise `ERR_INVALID_STATE`), decrements `trusted_device_count` by 1, and revokes every `ACTIVE` travel pass on the device, recording a `CHURN_SIGNAL` metric for each revocation. Removing a device — permitted from either `TRUSTED` or `UNTRUSTED` (from any other trust status the attempt is rejected with `ERR_INVALID_STATE`) — is terminal: the device becomes `REMOVED`, its `ACTIVE` playback sessions end, and its `ACTIVE` travel passes are revoked.

### 3.4. Verification Challenges and Accessibility

Verification challenges are the system's mechanism for re-proving that an account's users still inhabit the declared household. Issuing a challenge — available to `PlatformAdmin` and the `AccountOwner` — requires a `channel` (one of `EMAIL`, `SMS`, `VOICE_CALL`; the voice-call channel is the accessibility fallback for members who cannot receive email or text) and a `challenge_reason` (one of `NEW_DEVICE`, `PERIODIC`, `LOCATION_DRIFT`). Issuance succeeds only while the account is `ACTIVE`; on success a `VerificationChallenge` is created in status `PENDING`, the account's `verification_posture` flips from `VERIFIED` to `CHALLENGE_PENDING`, a 6-digit `code` is generated (never the reserved value `000000`, which is guaranteed to be a wrong submission), `attempts_used` starts at 0, and `expires_at` is set to 900 seconds after issuance for `EMAIL` and `SMS` or 1800 seconds for `VOICE_CALL`.

Timing for periodic challenges is governed regionally. A challenge with `challenge_reason` `PERIODIC` may only be issued when the account's region has an `ACTIVE` `EnforcementPolicy` with `enforcement_enabled` true and the current logical time is at or past the policy's `effective_from` plus its `grace_days`; otherwise issuance is rejected with `ERR_ENFORCEMENT_GRACE_ACTIVE` (HTTP 409). The policy's `messaging_variant` (`SOFT` or `HARD`) selects the user-facing tone but does not alter timing.

Submitting a code is available to all three member roles of the account and takes the submitted `code` plus the submitting `member_id`; a `member_id` matching no member at all yields `ERR_MEMBER_NOT_FOUND` (HTTP 404), and the identified member must have status `ACTIVE` and belong to the challenged account, otherwise the submission is rejected with `ERR_MEMBER_NOT_IN_ACCOUNT` (HTTP 422). Submission against a `LOCKED_OUT` challenge is rejected with `ERR_CHALLENGE_LOCKED` (HTTP 409). Submission against a challenge already `VERIFIED` (or otherwise no longer `PENDING`) is rejected with `ERR_INVALID_STATE` (HTTP 409). Submission at or past `expires_at` flips the challenge to `EXPIRED` and is rejected with `ERR_CHALLENGE_EXPIRED` (HTTP 409). A wrong code — including the reserved `000000` — is rejected with `ERR_CHALLENGE_CODE_MISMATCH` (HTTP 422) and increments `attempts_used` by 1; when that increment reaches the channel's attempt cap — 3 attempts for `EMAIL` and `SMS`, 5 for `VOICE_CALL` — the challenge transitions `PENDING` → `LOCKED_OUT` and the account's `verification_posture` becomes `LOCKED`. A correct submission while the challenge is `PENDING` and unexpired transitions it to `VERIFIED`, restores the account's `verification_posture` to `VERIFIED` (including from `LOCKED`), and sets the household's `last_verified_at` to the current logical time.

An `EXPIRED` challenge can be reissued — by the `AccountOwner` or `PlatformAdmin` — only once at least 300 seconds have elapsed beyond its `expires_at`; an earlier attempt is rejected with `ERR_CHALLENGE_COOLDOWN` (HTTP 409), and reissuing a challenge in any status other than `EXPIRED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Reissue returns the challenge to `PENDING` with a freshly generated 6-digit code, `attempts_used` reset to 0, and `expires_at` recomputed per its channel. The `PENDING` → `EXPIRED` → `PENDING` cycle may repeat, subject to that cooldown buffer.

### 3.5. Travel and Temporary Access

Legitimate travel must not read as account sharing. Any member of the account may grant a device a `TravelPass` by choosing a `grant_type` (`TEMPORARY_14D` or `TEMPORARY_30D`) and a `starts_at` instant; the pass's `ends_at` is derived as exactly 14 or 30 days after `starts_at` respectively, and the pass begins `ACTIVE`. A device's passes must not overlap: the new half-open window — inclusive at `starts_at`, exclusive at `ends_at` — must not intersect any other `ACTIVE` pass of the same device, and a violation is rejected with `ERR_TRAVEL_PASS_OVERLAP` (HTTP 409). Because the windows are half-open, back-to-back passes whose start equals the prior pass's end are allowed. A device holding at least one `ACTIVE` pass reports `travel_pass_active` true; the flag is recomputed whenever a pass is granted, revoked, converted, or lazily expires.

A pass ends in one of three ways. It expires lazily per §2.9 when the logical clock reaches `ends_at`. The `AccountOwner` may revoke an `ACTIVE` pass — revoking a pass in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) — which records an `EnforcementMetric` of `metric_type` `CHURN_SIGNAL` on the owning account — revocation is treated as a friction signal worth monitoring. Finally, when the traveler comes home, converting the pass — available to the `AccountOwner` and `PlatformAdmin` — is permitted while the pass is `ACTIVE` (otherwise `ERR_INVALID_STATE`) and the device's current `network_fingerprint` equals its household's `network_fingerprint` (otherwise `ERR_DEVICE_NOT_TRUSTED`, HTTP 403): the pass becomes `CONVERTED`, and the device transitions `UNTRUSTED` → `TRUSTED` directly, bypassing the confidence threshold of §3.3 (the household's `trusted_device_count` increments by 1; a device already `TRUSTED` simply stays trusted with no count change). Conversion is the one path to trust that does not require a strict confidence of at least 70, on the theory that a device physically back on the home network has already proven itself.

### 3.6. Extra-Member Slots: Pricing, Assignment, and Revocation

Extra-member slots monetize sharing beyond the household. Purchasing a slot is an `AccountOwner` operation carrying `payer_member_id` — which must identify the account's `OWNER` member, to whom the fee is attributed (a `payer_member_id` matching no member yields `ERR_MEMBER_NOT_FOUND`, HTTP 404, and a member that exists but is not the account's `OWNER` yields `ERR_VALIDATION`, HTTP 400) — plus `transfer_rights` (one of `TRANSFERABLE`, `LOCKED`, governing whether the eventual assigned profile may transfer out) and `expected_account_version` per §2.6. Purchase additionally requires the account `ACTIVE`, and the count of the account's slots currently `OFFERED` or `ACTIVE` must be strictly below the plan tier's slot cap — `BASIC` allows 0, `STANDARD` allows 1, `PREMIUM` allows 2 — or the purchase is rejected with `ERR_SLOT_LIMIT_EXCEEDED` (HTTP 422).

The fee charged is computed at purchase and stored on the slot as `price_cents_snapshot`. Start from the regional base fee: 799 cents for `NA`, 299 for `LATAM`, 499 for `EMEA`, and 349 for `APAC`. Apply the tier multiplier — `STANDARD` accounts pay the base unchanged (multiplier 1.0), `PREMIUM` accounts pay three quarters of the base (multiplier 0.75) — rounding half-up to integer cents; note that `BASIC` accounts cannot purchase slots at all because of the zero cap. Then add a per-slot surcharge of 200 cents multiplied by one less than the slot's index, where `slot_index` is 1 plus the count of the account's slots in `OFFERED` or `ACTIVE` immediately before this purchase — so the first slot pays no surcharge, the second pays 200, and so on. Call this the full-cycle fee. Two purchase-time variants then apply. When the purchase lands exactly on the account's billing anchor day — the day-of-month equals `billing_anchor_day`, i.e. cycle day index 0 — the prospective full-cycle variant charges the full-cycle fee with no proration. On any other cycle day, the mid-cycle prorated variant charges the full-cycle fee multiplied by the number of days remaining in the 30-day cycle and divided by 30, rounded half-up to integer cents — a result strictly less than the full-cycle fee. The cycle day index counts days since the anchor within the current 30-day cycle, wrapping at 30: it is computed as the current day-of-month minus `billing_anchor_day`, reduced modulo 30, so it is 0 on the anchor day itself. The purchased cycle day index is recorded on the slot as `purchased_day`. A successful purchase creates the slot in status `OFFERED` with `member_id` null, adds the charged fee to the account's `extra_member_billed_cents` (which never decreases), and increments the account's `version` by 1.

Assigning an `OFFERED` slot is an `AccountOwner` operation carrying the new member's `email`, `display_name`, and `member_region`. Assignment requires the account `ACTIVE`, the account's `verification_posture` `VERIFIED` (otherwise `ERR_ACCOUNT_NOT_VERIFIED`), the slot currently `OFFERED` (otherwise `ERR_INVALID_STATE`), and the extra member's region to equal the account's `region_code` — a cross-region assignment is rejected with `ERR_REGION_MISMATCH` (HTTP 422). On success a new `Member` is created on the account with `member_role` `EXTRA` and status `ACTIVE`, the slot transitions `OFFERED` → `ACTIVE`, and `member_id` is set to the new member.

Revoking an `ACTIVE` slot — by the `AccountOwner` or `PlatformAdmin` — computes a credit and transitions the slot to `REVOKED`; revoking a slot in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). The credit rule has two branches. If the revocation occurs within 7 cycle-days of the slot's `purchased_day` — the current cycle day index minus `purchased_day` is at most 7 — the credit equals the full `price_cents_snapshot`. Otherwise the credit is prorated: first compute the per-day rate by dividing `price_cents_snapshot` by 30 and rounding half-up to integer cents, then multiply that per-day rate by the number of days remaining in the current cycle (30 minus the current cycle day index). The rounding order is pinned: the per-day rate is rounded to integer cents first, then multiplied — computing the unrounded product and rounding once at the end is a different, forbidden order. The computed credit is stored as the slot's `credit_cents` (0 until revoked) and added to the account's `extra_member_credit_cents`, and the assigned member is transitioned to `REMOVED`. Two revocation cascades deliberately bypass the credit rule: when revocation results from a profile transfer of the assigned member or from account cancellation, `credit_cents` is set to 0 and no credit is added (and the transfer cascade moves the member rather than removing them; see §3.8).

A `REVOKED` slot can be returned to `OFFERED` by the `AccountOwner` while the account is `ACTIVE`; reoffering a slot in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Reoffering clears `member_id` to null and — importantly — does not recompute `slot_index`. The `OFFERED` → `ACTIVE` → `REVOKED` → `OFFERED` cycle may repeat. Separately, a failed billing charge (§3.9) lapses slots: any slot `OFFERED` or `ACTIVE` becomes `LAPSED` with no credit issued, and a lapsed `ACTIVE` slot's assigned member is `REMOVED`. `LAPSED` is terminal.

### 3.7. Entitlements at Play Time: Streams and Downloads

Enforcement of plan-tier limits happens at the moment of consumption, not at purchase. Starting a playback session — available to all three member roles — takes the `device_id` and the `requested_resolution` (one of `SD`, `HD`, `UHD`). The acting member must currently be `ACTIVE` (otherwise `ERR_INVALID_STATE`, HTTP 409). The `device_id` names a body-supplied identifier rather than a path segment, so §2.5's left-to-right path ordering does not govern it: the account-level state gates of §3.1 (suspended/cancelled, run per the §2.3 pipeline before §3 business rules) fire first, and only then is the device reference resolved — a `device_id` that matches no device at all yields `ERR_DEVICE_NOT_FOUND` (HTTP 404), while a device that exists but fails the first entitlement check below yields `ERR_DEVICE_NOT_TRUSTED`. Three checks apply in order. First, the device must exist, belong to the account's household (a device whose household is `DISSOLVED`, or belongs to another account, fails this check), and either be `TRUSTED` or hold an `ACTIVE` travel pass; otherwise the request is rejected with `ERR_DEVICE_NOT_TRUSTED` (HTTP 403). Second, the requested resolution must not exceed the plan tier's maximum — `BASIC` permits at most `SD`, `STANDARD` at most `HD`, `PREMIUM` at most `UHD`, with the ordering `SD` below `HD` below `UHD` — or the request is rejected with `ERR_RESOLUTION_NOT_ENTITLED` (HTTP 403). Third, the account-wide count of `ACTIVE` playback sessions across all members of the account must be strictly below the tier's stream cap — 1 for `BASIC`, 2 for `STANDARD`, 4 for `PREMIUM` — or the request is rejected with `ERR_STREAM_LIMIT_REACHED` (HTTP 409); at the boundary, a session is admitted when the active count is exactly one below the cap and rejected when it equals the cap. An admitted session is created `ACTIVE` with `started_at` set to the current logical time, `ended_at` null, and `resolution_granted` equal to the requested resolution, and the member's `current_streams` increments by 1. Ending a session (any member role of the account) transitions it to `ENDED`, stamps `ended_at`, and decrements the member's `current_streams` by 1; ending a session not currently `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409). The account must be `ACTIVE` to start a session; the suspended/cancelled gates of §3.1 apply.

Downloads follow the same device-reference convention and device-trust gate (a `device_id` matching no device yields `ERR_DEVICE_NOT_FOUND`; an existing device failing the gate yields `ERR_DEVICE_NOT_TRUSTED` under identical conditions) and a monthly allowance instead of a concurrency cap. Creating a download takes the `device_id` and a `title_id`; the account-wide count of downloads with status `ACTIVE` whose `billing_month` equals the current `YYYY-MM` from the logical clock must be strictly below the tier's monthly allowance — 5 for `BASIC`, 25 for `STANDARD`, 100 for `PREMIUM` — or the request is rejected with `ERR_DOWNLOAD_LIMIT_REACHED` (HTTP 409). A created download is `ACTIVE`, stamped with the current `billing_month`, and increments the member's `downloads_used_this_month` by 1. Deleting an `ACTIVE` download transitions it to `DELETED` and decrements `downloads_used_this_month` by 1, freeing its slot in the monthly allowance; deleting a download in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409); downloads that lapse to `EXPIRED` (30 days after creation, per §2.9) likewise no longer count against the allowance.

### 3.8. Profile Transfer to a New Account

When a household member or extra member strikes out on their own, the platform lets them carry their identity to a fresh account. The `AccountOwner` of the source account initiates a `ProfileTransfer` by naming the `member_id` to move and the `target_email` for the login of the account to be created. The named member must exist (otherwise `ERR_MEMBER_NOT_FOUND`, HTTP 404) and belong to the source account (otherwise `ERR_MEMBER_NOT_IN_ACCOUNT`, HTTP 422). The target email must differ from the source account's own `email`; a self-addressed transfer is rejected with `ERR_TRANSFER_TARGET_SELF` (HTTP 422). At initiation the system captures two audit snapshots — `history_snapshot` copying the member's `viewing_history` and `recommendation_snapshot` copying their `recommendation_seed` — and the transfer is created `AWAITING_ACCEPTANCE` with `expires_at` set 7 days after creation and `target_account_id` null. The transfer carries the originating account's id as its `source_account_id` for traceability. A transfer that is read or accepted against at or after its `expires_at` lapses to `EXPIRED` per §2.9; the `AccountOwner` may also cancel an `AWAITING_ACCEPTANCE` transfer outright, moving it to `CANCELLED` — cancelling a transfer in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409).

Acceptance is a `PlatformAdmin` operation and carries the new account's `new_account_email`, `new_account_region`, and `new_account_plan_tier` alongside the OCC field `expected_profile_transfer_version` per §2.6; a stale version is rejected with `ERR_STALE_TRANSFER_VERSION` (HTTP 412) before any state check, and a transfer no longer `AWAITING_ACCEPTANCE` — including one lazily expired — is rejected with `ERR_INVALID_STATE` (HTTP 409). Acceptance performs an atomic bundle: a new `Account` is created with the supplied email, region, and plan tier and its id is recorded as the transfer's `target_account_id`; the member row itself moves — `account_id` rewritten to the new account, `member_role` rewritten to `OWNER`, status remaining `ACTIVE` — with `viewing_history` and `recommendation_seed` preserved verbatim (the snapshots exist for audit, the live fields are what travel); the new account's `owner_member_id` is pointed at the transferred member, while the auto-created owner member of the new account is transitioned to `REMOVED` (retained on the new account for audit); and if the moving member was assigned to an `ACTIVE` `ExtraMemberSlot`, that slot transitions to `REVOKED` with `credit_cents` 0 as described in §3.6. The transfer lands in `COMPLETED` and its `version` increments by 1.

### 3.9. Billing Simulation, Regional Enforcement, and Churn Monitoring

Platform administration includes three operational surfaces. First, a `PlatformAdmin`-only billing simulator accepts an `account_id` and an `outcome` (`SUCCEEDED` or `FAILED`); when the outcome is `FAILED`, an `ACTIVE` account is suspended with the full cascade of §3.1 (sessions ended, devices untrusted, passes revoked with `CHURN_SIGNAL` metrics, `version` incremented), and additionally every slot of the account in `OFFERED` or `ACTIVE` lapses to `LAPSED` per §3.6 — `OFFERED` slots lapse with no credit and no member impact, `ACTIVE` slots lapse with no credit and their assigned member `REMOVED`. An outcome of `SUCCEEDED`, or a `FAILED` outcome against an account not currently `ACTIVE`, leaves the account unchanged and simply returns it.

Second, enforcement policies govern regional rollout. A `PlatformAdmin` creates a policy with `region_code`, `enforcement_enabled`, `grace_days` (zero or more), `messaging_variant`, and `effective_from`; it begins `DRAFT`. Activation (`DRAFT` → `ACTIVE`) retires any other `ACTIVE` policy for the same region per §2.11; activating a policy not in `DRAFT`, or retiring a policy not `ACTIVE`, is rejected with `ERR_INVALID_STATE` (HTTP 409), and retirement (`ACTIVE` → `RETIRED`) is permanent. The timing effect of an active enabled policy on periodic challenges is defined in §3.4.

Third, enforcement metrics feed the churn-monitoring loop. `PlatformAdmin` and `SupportAgent` may record a metric on an account with a `metric_type` of `CHURN_SIGNAL`, `COMPLAINT`, or `WINBACK` and an optional free-text `notes` (defaulting to an empty string); the metric's `recorded_at` is its creation time. Travel-pass revocations also create `CHURN_SIGNAL` metrics automatically, per §3.1, §3.2, §3.3, and §3.5. A computed per-account churn summary reports `churn_signals` (the count of the account's metrics of type `CHURN_SIGNAL`), `winbacks` (count of type `WINBACK`), `active_flag` (1 when the account's `status` is `ACTIVE`, otherwise 0), and two rates rounded half-up to 4 decimal places. The denominator for both rates is the sum of `churn_signals`, `winbacks`, and `active_flag`; when that denominator is zero both rates report 0.0. The `gross_churn_rate` is the churn-signal count divided by that denominator, counting every churn signal regardless of winbacks. The `net_churn_rate` subtracts winbacks from churn signals first, floors the difference at zero, and divides by the same denominator.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, perform a state transition, or execute a computed read return `200 OK`. All endpoints are mounted under `/hv`.

Certain list endpoints additionally accept exact-match query filters beyond `limit`/`offset`: `GET /hv/accounts` accepts `region_code` and `plan_tier`; `GET /hv/accounts/{id}/members` accepts `member_role` and `status`; `GET /hv/households/{id}/devices` accepts `trust_status`; `GET /hv/accounts/{id}/extra-member-slots` and `GET /hv/extra-member-slots` accept `status`, and the latter also `member_id` and `payer_member_id`; `GET /hv/accounts/{id}/verification-challenges`, `GET /hv/devices/{id}/travel-passes`, `GET /hv/accounts/{id}/profile-transfers`, `GET /hv/profile-transfers`, `GET /hv/members/{id}/playback-sessions`, and `GET /hv/devices/{id}/playback-sessions` accept `status` (the global transfer list also `member_id`); the download lists accept `status` and, on the member list, `billing_month`; `GET /hv/enforcement-policies` accepts `region_code` and `status`; and `GET /hv/accounts/{id}/enforcement-metrics` accepts `metric_type`. Each filter narrows the result set to exact matches before pagination.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hv/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/hv/_billing/simulate` | Simulate a billing outcome for an account | PlatformAdmin |
| POST | `/hv/accounts` | Create an account plus its OWNER member | PlatformAdmin |
| GET | `/hv/accounts/{id}` | Read one account | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/accounts` | List accounts | PlatformAdmin, SupportAgent |
| POST | `/hv/accounts/{id}/suspend` | Suspend an ACTIVE account with cascade | PlatformAdmin |
| POST | `/hv/accounts/{id}/reactivate` | Return a SUSPENDED account to ACTIVE | PlatformAdmin |
| POST | `/hv/accounts/{id}/cancel` | Cancel the account with cascade | PlatformAdmin, AccountOwner |
| PATCH | `/hv/accounts/{id}/plan` | Change plan tier with OCC | PlatformAdmin, AccountOwner |
| POST | `/hv/accounts/{id}/households` | Establish the account's household | AccountOwner |
| GET | `/hv/households/{id}` | Read one household | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/accounts/{id}/households` | List households of an account | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/households/{id}/relocate` | Move the household anchor | AccountOwner |
| POST | `/hv/households/{id}/dissolve` | Dissolve the household | AccountOwner |
| POST | `/hv/accounts/{id}/members` | Add a HOUSEHOLD member profile | AccountOwner |
| GET | `/hv/members/{id}` | Read one member | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/accounts/{id}/members` | List members of an account | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/members/{id}/remove` | Remove a non-OWNER member | AccountOwner |
| POST | `/hv/households/{id}/devices` | Register a device | AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/devices/{id}` | Read one device | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/households/{id}/devices` | List devices of a household | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/devices/{id}/confidence` | Household-match confidence breakdown | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/devices/{id}/signal` | Record a network signal | AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/devices/{id}/trust` | Mark a device TRUSTED | AccountOwner |
| POST | `/hv/devices/{id}/untrust` | Mark a TRUSTED device UNTRUSTED | AccountOwner |
| POST | `/hv/devices/{id}/remove` | Remove a device (terminal) | AccountOwner |
| POST | `/hv/accounts/{id}/extra-member-slots` | Purchase an extra member slot with OCC | AccountOwner |
| GET | `/hv/extra-member-slots/{id}` | Read one slot | PlatformAdmin, SupportAgent, AccountOwner |
| GET | `/hv/accounts/{id}/extra-member-slots` | List slots of an account | PlatformAdmin, SupportAgent, AccountOwner |
| GET | `/hv/extra-member-slots` | Filtered slot list by member or payer | PlatformAdmin, SupportAgent |
| POST | `/hv/extra-member-slots/{id}/assign` | Assign an OFFERED slot, creating the EXTRA member | AccountOwner |
| POST | `/hv/extra-member-slots/{id}/revoke` | Revoke an ACTIVE slot with prorated credit | AccountOwner, PlatformAdmin |
| POST | `/hv/extra-member-slots/{id}/reoffer` | Return a REVOKED slot to OFFERED | AccountOwner |
| POST | `/hv/accounts/{id}/verification-challenges` | Issue a verification challenge | PlatformAdmin, AccountOwner |
| GET | `/hv/verification-challenges/{id}` | Read one challenge (lazy expiry) | PlatformAdmin, SupportAgent, AccountOwner |
| GET | `/hv/accounts/{id}/verification-challenges` | List challenges of an account | PlatformAdmin, SupportAgent, AccountOwner |
| POST | `/hv/verification-challenges/{id}/submit` | Submit a verification code | AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/verification-challenges/{id}/reissue` | Reissue an EXPIRED challenge after cooldown | AccountOwner, PlatformAdmin |
| POST | `/hv/devices/{id}/travel-passes` | Grant a travel pass | AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/travel-passes/{id}` | Read one pass (lazy expiry) | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/devices/{id}/travel-passes` | List passes of a device | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/travel-passes/{id}/revoke` | Revoke an active pass | AccountOwner |
| POST | `/hv/travel-passes/{id}/convert` | Convert a pass, trusting the device | AccountOwner, PlatformAdmin |
| POST | `/hv/accounts/{id}/profile-transfers` | Initiate a profile transfer | AccountOwner |
| GET | `/hv/profile-transfers/{id}` | Read one transfer (lazy expiry) | PlatformAdmin, SupportAgent, AccountOwner |
| GET | `/hv/accounts/{id}/profile-transfers` | List transfers sourced from an account | PlatformAdmin, SupportAgent, AccountOwner |
| GET | `/hv/profile-transfers` | Filtered transfer list by member | PlatformAdmin, SupportAgent |
| POST | `/hv/profile-transfers/{id}/accept` | Accept a transfer with OCC | PlatformAdmin |
| POST | `/hv/profile-transfers/{id}/cancel` | Cancel a pending transfer | AccountOwner |
| POST | `/hv/members/{id}/playback-sessions` | Start a playback session | AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/playback-sessions/{id}` | Read one session | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/members/{id}/playback-sessions` | List sessions of a member | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/devices/{id}/playback-sessions` | List sessions on a device | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/playback-sessions/{id}/end` | End an active session | AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/members/{id}/downloads` | Create a download | AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/downloads/{id}` | Read one download (lazy 30-day expiry) | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/members/{id}/downloads` | List downloads of a member | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| GET | `/hv/devices/{id}/downloads` | List downloads on a device | PlatformAdmin, SupportAgent, AccountOwner, HouseholdMember, ExtraMember |
| DELETE | `/hv/downloads/{id}` | Delete an ACTIVE download | AccountOwner, HouseholdMember, ExtraMember |
| POST | `/hv/enforcement-policies` | Create a regional enforcement policy (DRAFT) | PlatformAdmin |
| GET | `/hv/enforcement-policies/{id}` | Read one policy | PlatformAdmin, SupportAgent |
| GET | `/hv/enforcement-policies` | List policies | PlatformAdmin, SupportAgent |
| POST | `/hv/enforcement-policies/{id}/activate` | Activate a DRAFT policy | PlatformAdmin |
| POST | `/hv/enforcement-policies/{id}/retire` | Retire an ACTIVE policy | PlatformAdmin |
| POST | `/hv/accounts/{id}/enforcement-metrics` | Record a churn/complaint/winback signal | PlatformAdmin, SupportAgent |
| GET | `/hv/accounts/{id}/enforcement-metrics` | List metrics of an account | PlatformAdmin, SupportAgent |
| GET | `/hv/accounts/{id}/churn-summary` | Gross and net churn rates | PlatformAdmin, SupportAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_HOUSEHOLD_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_CHALLENGE_NOT_FOUND` | 404 |
| `ERR_TRAVEL_PASS_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_DOWNLOAD_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_STALE_TRANSFER_VERSION` | 412 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_ACCOUNT_CANCELLED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_NOT_VERIFIED` | 409 |
| `ERR_CHALLENGE_LOCKED` | 409 |
| `ERR_CHALLENGE_CODE_MISMATCH` | 422 |
| `ERR_CHALLENGE_EXPIRED` | 409 |
| `ERR_CHALLENGE_COOLDOWN` | 409 |
| `ERR_ENFORCEMENT_GRACE_ACTIVE` | 409 |
| `ERR_TRAVEL_PASS_OVERLAP` | 409 |
| `ERR_DEVICE_NOT_TRUSTED` | 403 |
| `ERR_REGION_MISMATCH` | 422 |
| `ERR_MEMBER_NOT_IN_ACCOUNT` | 422 |
| `ERR_TRANSFER_TARGET_SELF` | 422 |
| `ERR_ACCOUNT_ALREADY_HAS_HOUSEHOLD` | 409 |
| `ERR_RESOLUTION_NOT_ENTITLED` | 403 |
| `ERR_STREAM_LIMIT_REACHED` | 409 |
| `ERR_DOWNLOAD_LIMIT_REACHED` | 409 |
| `ERR_SLOT_LIMIT_EXCEEDED` | 422 |
