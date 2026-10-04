# Mobile Wallet Card Provisioning API — Product Requirements Document

## 1. Introduction

Adding a payment card to a mobile wallet looks trivial to the person holding the phone — scan the plastic, answer a challenge, tap to pay. Behind that gesture sits a lattice of obligations that this API is built to carry: the issuing bank must verify the cardholder's identity through one-time codes or an in-app confirmation before any credential is minted; the credential actually stored on the device is a device account number (DPAN) that must never collide with the funding PAN; every tap carries a cryptogram the issuer validates, and every decline must be traceable to a reason; when a phone is lost, every credential on it must fall silent within a single report; and when a card is reissued or an issuer leaves the platform, the downstream accounts, artifacts, and tokens must unwind in a defined order with an audit trail.

This document specifies the Mobile Wallet Card Provisioning, Token Lifecycle & Device Binding API. It governs five cooperating parties — the wallet platform itself, issuer-side operators, cardholders, a customer-service desk, and transit operators — across the full arc of a card's life in the wallet: registration of the cardholder and their devices, onboarding of issuers under participation agreements with fee and branding terms, provisioning sessions with two-factor identity verification, tokenization that binds a DPAN to one device and one funding account, transaction authorization under biometric, fiscal, express-transit, and allowlist gates, default-card selection per device, dispute intake that traces a wallet charge back to the underlying card account, and the suspension, resumption, deactivation, and reissuance flows that keep the device fleet consistent with issuer reality. Security posture is a first-class, continuously recomputed property of every device, and payment capability is gated on it at all times.

The design is deliberately posture-driven: whether any given operation is permitted depends less on who asks than on the current, derived state of the device, the token, the funding account, and the issuer standing behind it. A separate audit stream records every meaningful token event so that disputes, risk scoring, and fee accrual can be reconstructed after the fact. All rules below are normative.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply to every endpoint and every entity in the system.

### 2.1. User and Role-Based Access Control

Every request is authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting party, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly five role values, spelled precisely as follows: `PlatformAdmin`, `IssuerOperator`, `Cardholder`, `CustomerService`, and `Any`.

The `Any` role is special: endpoints whose authorized-role list is exactly `[Any]` — cardholder registration, the test-driving clock endpoint, and every GET endpoint — skip the header-presence check entirely and may be called without authentication. Every other endpoint requires both headers to be present and well-formed; a missing or malformed header is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once headers are accepted, the declared role must be permitted on the endpoint being called; a role outside the endpoint's authorized set is rejected with `ERR_FORBIDDEN` (HTTP 403). Authorization is checked only after the header check, so a request with missing headers always surfaces `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` even when the role would also have been wrong.

The five roles have distinct identity semantics that determine how `X-User-ID` is interpreted:

- When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id` of the acting `Cardholder` entity; ownership checks on any resource that references a `Cardholder` — most importantly a `Device`, whose owning cardholder is recorded as `cardholder_id` — compare that foreign-key field to `X-User-ID`. A `Cardholder` may act only on devices they own on ownership-scoped endpoints; a mismatch is `ERR_FORBIDDEN`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `IssuerOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is never compared to an `Issuer`'s `id` or any other entity key.
- When `X-User-Role` is `CustomerService`, `X-User-ID` is likewise an opaque desk identifier with no entity binding.
- When `X-User-Role` is `Any`, `X-User-ID` is an opaque caller identifier, and the endpoints in this category do not require the headers at all.

Broadly speaking, `PlatformAdmin` governs the platform's commercial substrate — issuers, their agreements, and transit operators. `IssuerOperator` runs the issuer's book: card accounts, card artifacts, reissues and closures, authorization adjudication, and dispute resolution. `Cardholder` drives the device-facing lifecycle: device registration and security settings, provisioning, token suspension and removal, and default-card selection. `CustomerService` is read-mostly, able to report a device lost or found and to intake disputes. Read access via GET is universal.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. Resource serialization returns the entity's full persisted field set; any purely server-internal bookkeeping fields (names beginning with an underscore) are stripped before serialization.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints; `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned in one page; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. The `offset` parameter sets how many items to skip before the page begins and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order — oldest first — and ties on an identical `created_at` are broken by creation order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted entity in the system carries an `id` that is a server-minted UUID with no type prefix — the identifier is the bare UUID string, not something like `tok_...` or `dev_...`. Thirteen of the fifteen entities additionally carry the full set of common fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at its initial value on creation and increments by one on every mutation of that row. The two exceptions are `TransitAllowlist` entries and `TokenEvent` records: both carry only `id` and `created_at` — `updated_at` and `version` are absent from both, and no operation may be specified as depending on them.

Any mutation of an entity — whether driven by a client request or by an internal cascade such as an issuer suspension fanning out to tokens — refreshes that entity's `updated_at` and increments its `version`. Cascades therefore produce observable version bumps on every row they touch, not only on the row named in the request path.

### 2.5. Optimistic Concurrency Control

Two write endpoints in the system are guarded by optimistic concurrency control, and only those two. The rule is identical in shape for both: the request body must carry a non-optional expectation field containing the parent entity's `version` as the client last observed it; if the parent's current `version` no longer matches, the write is rejected and no state changes.

- Tokenizing a provisioning session requires the field `expected_session_version` in the request body, carrying the `ProvisioningSession`'s `version` as last read by the caller. If the session's version has advanced — for example because an earlier verify or tokenize already moved it — the tokenize is rejected with `ERR_VERSION_CONFLICT` (HTTP 412). The stale caller's view no longer reflects the session it claims to finalize.
- Setting the device default card requires the field `expected_device_version`, carrying the `Device`'s `version` as last read. Because an intervening token deactivation also mutates `default_card_id` and bumps the device version, a mismatch means the caller's choice set may be invalidated, and the write is rejected with `ERR_VERSION_CONFLICT` (HTTP 412).

No other endpoint accepts or requires any `expected_*_version` field. Rejections under this rule carry HTTP 412, and a successful guarded write itself increments the parent's `version` by one, so the next writer must re-read.

### 2.6. Nested Resource Retrieval and Identifier Resolution

The API enforces strict left-to-right validation of hierarchical paths. When a URL contains multiple resource identifiers — issuer, agreement, device, session, token, authorization, or dispute segments — the server resolves each identifier in path order and rejects the request immediately with a 404 for the first identifier that does not resolve, before examining any later segment or any request body. The 404 is entity-specific where a specific code exists: `ERR_ISSUER_NOT_FOUND` for an unknown issuer, `ERR_DEVICE_NOT_FOUND` for a device, `ERR_TOKEN_NOT_FOUND` for a payment token, `ERR_CARD_ACCOUNT_NOT_FOUND` for a card account, `ERR_AUTHORIZATION_NOT_FOUND` for an authorization, `ERR_DISPUTE_NOT_FOUND` for a dispute, `ERR_AGREEMENT_NOT_FOUND` for an issuer agreement, `ERR_PROGRAM_NOT_FOUND` for a merchant program, and `ERR_OPERATOR_NOT_FOUND` for a transit operator; resources without a dedicated code fall back to the generic `ERR_NOT_FOUND`. Foreign keys supplied in the request body — such as a `card_artifact_id` on session creation or a `merchant_program_id` on enrollment — are resolved only after all path identifiers have resolved. Existence failures surface as 404 regardless of which other rules the request would also violate, because the existence check outranks every business rule except the header, role, and payload-schema checks that precede it (see §2.10 for the full ordering).

### 2.7. The Logical Clock

The system keeps its own logical clock rather than trusting wall-clock time. At server startup the logical clock is exactly `2026-09-01T00:00:00Z`, and the server must not fall back to wall-clock time if the clock has never been set — an unset clock is simply that fixed earliest instant. An admin-facing test-driving capability lets any caller set the logical clock to a supplied `current_utc` instant. All temporal logic in the system — provisioning session expiry in particular — is evaluated against this logical clock, and nothing else.

### 2.8. Precision and Money

All monetary amounts in the system are integer cents. Fee computation uses floor division — the raw fee is the amount multiplied by the agreement's basis-point rate and divided by ten thousand, truncated toward zero — and rounding-half-up is never used anywhere in fee accrual or projection. Computed scores such as the account risk score are integers with an explicit cap and floor as described in §3.8. No floating-point money ever appears on the wire.

### 2.9. Status Codes

Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, perform a state transition, or answer a read respond with HTTP 200. Client errors use the HTTP status attached to each error identifier in §5 — 400 for malformed contexts and payloads, 403 for role violations, 404 for unresolved identifiers, 409 for state and business-constraint conflicts, 412 for optimistic-concurrency rejections, and 422 for fiscal and eligibility gate failures.

### 2.10. Priority Ordering of Checks

When a request would violate several rules at once, the system does not choose arbitrarily which error to return — checks are evaluated in a fixed global priority order, and the first failing check determines the response. The ordering is normative and is described here once so that the scattered rules of §3 can be read as slots in a single sequence:

1. **Header presence** — `X-User-ID` and `X-User-Role` must be present and well-formed, except on the `[Any]` endpoints (cardholder registration, the clock endpoint, all GETs). Failure: `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role and ownership** — the declared role must be authorized on the endpoint, and an entity-backed `Cardholder` caller must own the target resource on ownership-scoped endpoints. Failure: `ERR_FORBIDDEN`.
3. **Payload schema** — required fields present, enum members valid, integers non-negative where required. Failure: `ERR_VALIDATION`. Applies to all POST endpoints.
4. **Existence, left to right** — path identifiers resolve in path order (issuer, agreement, device, session, token, authorization, dispute), then body foreign keys. Failure: the entity-specific 404 (`ERR_ISSUER_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_TOKEN_NOT_FOUND`, `ERR_CARD_ACCOUNT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`) or the generic `ERR_NOT_FOUND`.
5. **Provisioning session lazy expiry** — on verify and tokenize, if the logical clock has reached the session's `expires_at`, the session is transitioned to `EXPIRED` before any other check runs, and the request fails with `ERR_PROVISIONING_SESSION_EXPIRED`.
6. **State precondition** — the target resource must be in a state from which the requested transition is defined; any state-machine rejection, whether phrased as a precondition violation or as an undefined transition, surfaces as `ERR_INVALID_STATE` (HTTP 409).
7. **Idempotency** — on provisioning-session creation, a repeated `idempotency_key` on the same device replays the original session; the same key with a different payload is `ERR_IDEMPOTENCY_CONFLICT`.
7.5. **One active provisioning window per device** — a device that already has a non-terminal provisioning session (one in `INITIATED`, `VERIFICATION_REQUIRED`, or `VERIFIED` that has not yet expired) rejects a second session creation with `ERR_INVALID_STATE`. This check sits between idempotency and the authorization gates.

Priorities 8 through 17 form the **authorization gate chain** — the request-level gates that run before an `Authorization` row is ever persisted. They are described in detail in §3.5 and §3.6 but occupy fixed slots here: token-active (8, `ERR_TOKEN_NOT_ACTIVE`), device-unsecured (9, `ERR_DEVICE_UNSECURED`), device-lost (10, `ERR_DEVICE_LOST`), issuer participation (11, `ERR_ISSUER_NOT_ACTIVE`), card account open (12, `ERR_CARD_ACCOUNT_RESTRICTED`), authentication (13, `ERR_AUTHENTICATION_REQUIRED`), per-authorization amount cap (14, `ERR_AUTH_AMOUNT_EXCEEDS_CAP`), merchant-program cap (15, `ERR_PROGRAM_AMOUNT_EXCEEDS_CAP`), express-transit eligibility (16, `ERR_EXPRESS_TRANSIT_NOT_SUPPORTED`), and transit allowlist (17, `ERR_TRANSIT_NOT_ALLOWED`). Because lower numbers run first, a request that would fail both the token-active check and the amount cap always surfaces `ERR_TOKEN_NOT_ACTIVE`; a lost device masks an amount-cap violation with `ERR_DEVICE_LOST`; and so on down the chain.

The remaining priorities guard specific operations: merchant-program enrollment eligibility (18, `ERR_PROGRAM_NOT_ACTIVE` or `ERR_PROGRAM_INELIGIBLE`), dispute traceability (19, `ERR_DISPUTE_AMOUNT_MISMATCH` or `ERR_INVALID_STATE`), agreement activation exclusivity (20, `ERR_ISSUER_NOT_ACTIVE` or `ERR_AGREEMENT_OVERLAP`), default-card candidate state (21, `ERR_TOKEN_NOT_ACTIVE`), and DPAN uniqueness on tokenize (22, `ERR_VALIDATION`). Each is described alongside its workflow in §3.

### 2.11. Derived Security Posture

A device's `security_posture` is never stored as client input; it is recomputed on every read of the device and on every device-security change (security-flag updates, lost reports, found reports). The derivation is deterministic: if the device's `is_lost` flag is set, posture is `LOST`; otherwise, if `passcode_enabled` is false, posture is `DEGRADED`; otherwise — passcode enabled and not lost — posture is `HEALTHY`. A freshly registered device, which has no passcode configured, therefore reports `DEGRADED` until the cardholder enables a passcode. Posture is not cosmetic: tokenization, token resumption, and ordinary (non-express) authorization all require the device not to be `DEGRADED`, and a `LOST` device blocks those operations outright. The biometric flag `biometric_enabled` does not enter the posture computation; it gates authentication at authorization time instead (§3.6).

### 2.12. Audit Trail

Every `PaymentToken` accumulates an append-only audit stream of `TokenEvent` records. An event has an `event_type` drawn from exactly eight values — `PROVISIONING`, `ACTIVATION`, `AUTHORIZATION_APPROVED`, `AUTHORIZATION_DECLINED`, `SUSPENSION`, `RESUMPTION`, `DEACTIVATION`, `DEVICE_BINDING_LOST` — and a structured `payload` object carrying event detail. Every state change or counter-affecting decision on a token that the workflows of §3 describe as "appending a TokenEvent" must produce exactly one such record, whether the trigger was a cardholder action, an issuer action, or a system cascade. Token events are readable per token and as a globally filterable stream. Because `TokenEvent` rows carry no `version` and no `updated_at` (§2.4), they are immutable once written.

## 3. Business Logic & Workflows

This section describes the domain end to end. It is organized around the parties and lifecycles a reader must understand to implement the system: the issuer substrate first, then the cardholder's devices, then provisioning and tokenization, then authorization, then the merchant and transit overlays, then disputes and risk, and finally the teardown paths that unwind everything.

### 3.1. Onboarding Issuers and Their Commercial Terms

A `PlatformAdmin` begins by creating an `Issuer` with an `issuer_name` and a two-letter `country_code`. A new issuer is born in `DRAFT` status and can do nothing of consequence until it is activated — and activation is deliberately hard: an issuer may move from `DRAFT` to `ACTIVE` only when at least one `IssuerAgreement` under it is in `ACTIVE` status. Activating an issuer without one is rejected with `ERR_AGREEMENT_REQUIRED`.

Agreements are the commercial heart of issuer participation. An agreement is created with the `issuer_id` it governs, a `branding_color` (the hex color branding rules demand on card art), a `branding_logo_ref` pointing at the logo asset, a `terms_version` label, a participation fee expressed as `fee_bps` (basis points of settled amount), a per-transaction `fee_cap_cents` ceiling which must be a positive integer (a non-positive value is rejected with `ERR_TERMS_VALIDATION_FAILED`, HTTP 422), an optional `fee_floor_cents` floor that defaults to 0 when omitted, an `express_transit_supported` flag declaring whether tokens under this agreement may be express-enabled, and the window bracketed by `effective_at` and `expires_at` during which the agreement is usable. New agreements are born `PENDING`.

Activating an agreement — moving it `PENDING → ACTIVE` — is guarded by two checks evaluated at priority 20: the parent issuer must not be `OFFBOARDED` (otherwise `ERR_ISSUER_NOT_ACTIVE`), and no other agreement of the same issuer may already be `ACTIVE` (otherwise `ERR_AGREEMENT_OVERLAP`). There is at most one active fee schedule per issuer at any moment.

Commercial terms change over time, and the system models that as supersession rather than mutation. Superseding an `ACTIVE` agreement requires a complete new-terms payload — `branding_color`, `branding_logo_ref`, `terms_version`, `fee_bps`, `fee_cap_cents`, optional `fee_floor_cents`, `express_transit_supported`, `effective_at`, and `expires_at` — and the new terms must be valid: fees non-negative, the cap not below the floor, branding present. Invalid terms are rejected with `ERR_TERMS_VALIDATION_FAILED` (HTTP 422). On success the old agreement becomes `SUPERSEDED`, a new agreement for the same issuer is created directly in `ACTIVE` status, and the response carries the newly created agreement (HTTP 200); every `ACTIVE` payment token bound to that issuer is silently re-fee'd: no token changes state, but all future authorizations accrue under the new agreement's schedule. Both `SUPERSEDED` and `TERMINATED` are terminal for an agreement.

Terminating the `ACTIVE` agreement has a sharper edge: if it was the issuer's last active agreement, the parent issuer drops to `SUSPENDED`, which in turn fires the issuer-suspension cascade described in §3.7 — every `ACTIVE` token of that issuer is suspended. Agreement termination is therefore never a purely clerical act.

Issuer suspension and offboarding, and their cascades into accounts and tokens, are detailed in §3.7.

### 3.2. Cardholders and Their Devices

Anyone may register a cardholder — the endpoint is unauthenticated by design — supplying `legal_name`, a contact `email` that must be unique across cardholders, and a contact `phone` in E.164 format. A new `Cardholder` is born with `status` `ACTIVE`; the only other status is `BLOCKED`.

Devices belong to cardholders. A `Cardholder` registers a device by supplying the owning `cardholder_id` (which must equal their own `X-User-ID`), a `device_serial` that is unique across all devices, a `device_model` string, and an `os_version` string. Registration initializes the security flags conservatively: `passcode_enabled` false, `biometric_enabled` false, `is_lost` false — which means, per §2.11, the device is born `DEGRADED` and cannot provision or authorize anything until a passcode is set. The device also tracks `reported_lost_at` and `found_at` timestamps (both null until used), an `active_token_count` of tokens currently `ACTIVE` on it (starting at 0), and a nullable `default_card_id` naming the token that is the device's default payment card.

The cardholder alone may tune the device's security flags through a dedicated update carrying `passcode_enabled` and `biometric_enabled`; each update recomputes `security_posture` and, like any mutation, refreshes `updated_at` and bumps `version`. Devices are readable singly and as a per-cardholder list.

Loss and recovery are first-class events. Reporting a device lost — a privilege shared by the owning `Cardholder`, any `IssuerOperator`, and `CustomerService`, because loss reports arrive through many channels — sets `is_lost` true, stamps `reported_lost_at`, and flips posture to `LOST`. The same report sweeps the device: every `ACTIVE` payment token bound to it moves to `SUSPENDED` (recorded with reason lost-device), each such token's `suspension_count` increments by one, a `SUSPENSION` token event is appended to each, and the device's `default_card_id` is cleared. Reporting the device found — available to the `Cardholder` and `CustomerService` — stamps `found_at` (overwriting any earlier found timestamp), clears `is_lost` while leaving `reported_lost_at` untouched as the record of the most recent loss, and recomputes posture: `HEALTHY` if a passcode is enabled, `DEGRADED` otherwise. Found reports do **not** resurrect the suspended tokens; each token must be resumed individually through its own resume flow (§3.5). This asymmetry is intentional: recovering the hardware does not prove the credentials are still trustworthy.

### 3.3. Card Accounts and Card Artifacts

On the issuer's side of the house, an `IssuerOperator` or `PlatformAdmin` opens a `CardAccount` for a cardholder by supplying `cardholder_id`, the issuing `issuer_id`, the `fpan_last4` (last four digits of the funding primary account number), and a `card_product` drawn from exactly `CREDIT`, `DEBIT`, `PREPAID`, or `TRANSIT`. Accounts are born `OPEN`; the full status set is `OPEN`, `RESTRICTED`, `REISSUED`, and the terminal `CLOSED`. Accounts also carry a self-referencing `reissue_of_account_id`, null unless the account was created by reissue. Accounts are listable with optional `issuer_id`, `cardholder_id`, and `status` filters.

A card account may carry one or more `CardArtifact`s — the embossed-plastic view of the account — created by an `IssuerOperator` with the owning `card_account_id`, the artifact's own `pan_last4`, an `expiry` in MMYY format, and the `embossing_name`. Artifacts are born `ACTIVE` and live among `ACTIVE`, `SUSPENDED`, and terminal `DEACTIVATED`. An artifact's `pan_last4` matters beyond display: merchant programs may key enrollment eligibility to it (§3.6).

Artifact suspension — `ACTIVE → SUSPENDED` — requires the parent account to be `OPEN` (else `ERR_INVALID_STATE`) and cascades: every `ACTIVE` token bound to that artifact moves to `SUSPENDED`, each with `suspension_count` incremented and a `SUSPENSION` event appended. Resuming an artifact — `SUSPENDED → ACTIVE` — likewise requires an `OPEN` account and, notably, does **not** resume the tokens; like found-devices, recovered plastic does not imply trusted credentials. Deactivating an artifact from either `ACTIVE` or `SUSPENDED` moves it to `DEACTIVATED` and pushes every token bound to it that is `ACTIVE` or `SUSPENDED` into `DEACTIVATED` — recorded as `CARD_REISSUE` when the cascade arrives via account reissue, and `ISSUER_REVOKE` otherwise — with a `DEACTIVATION` event on each token.

Reissue is the heavyweight account operation, available to an `IssuerOperator` from either `OPEN` or `RESTRICTED` — with one asymmetry: from `OPEN`, an account that is not actually `OPEN` at request time rejects with `ERR_INVALID_STATE` under the transition's precondition, while the `RESTRICTED → REISSUED` path carries no additional precondition. Reissuing creates a successor `CardAccount` in `OPEN` status whose `reissue_of_account_id` points back at the predecessor, flips the predecessor to `REISSUED`, deactivates every artifact on the predecessor, and deactivates every `ACTIVE` or `SUSPENDED` token on the predecessor with `deactivated_reason` `CARD_REISSUE`, appending a `DEACTIVATION` event per token — identically for both source states. Closure, from `OPEN` or `REISSUED`, moves the account to terminal `CLOSED` — but closing an `OPEN` account is blocked while any `OPEN` dispute exists on tokens of the account, surfacing `ERR_CARD_HAS_OPEN_DISPUTES`; closing a `REISSUED` account is not blocked by open disputes, since its tokens were already deactivated by the reissue itself. A successful closure deactivates the account's `ACTIVE` and `SUSPENDED` tokens with `deactivated_reason` `USER_REMOVE` (the issuer acting on the user's behalf), each with its `DEACTIVATION` event. The `OPEN ↔ RESTRICTED` transitions are not client-driven at all: they are fired by the dispute machinery of §3.7.

### 3.4. Provisioning: From Plastic to Bound Credential

Provisioning is the cardholder-driven ceremony that turns a card artifact into a device-bound token, and it runs as a session with its own lifecycle: `INITIATED → VERIFICATION_REQUIRED → VERIFIED → TOKENIZED`, with `EXPIRED` and `FAILED` as the two terminal failure exits.

A `Cardholder` starts a session on one of their devices by supplying the `card_artifact_id` being provisioned and a client-chosen `idempotency_key`. Creation checks the issuer-participation and account-open gates (priorities 11–12): the artifact's account must be `OPEN` and its issuer `ACTIVE` with an `ACTIVE` agreement, else `ERR_ISSUER_NOT_ACTIVE` or `ERR_CARD_ACCOUNT_RESTRICTED` respectively. Idempotency (priority 7) makes retries safe: the same `idempotency_key` on the same device replays the original session unchanged, while the same key with a different payload is `ERR_IDEMPOTENCY_CONFLICT`. Independently (priority 7.5), a device may host only one live provisioning window at a time — if any session on the device sits in `INITIATED`, `VERIFICATION_REQUIRED`, or `VERIFIED` and has not yet expired, a second creation is rejected with `ERR_INVALID_STATE`.

A created session lands in `INITIATED` and immediately, automatically, transitions to `VERIFICATION_REQUIRED`. Its `expires_at` is computed at creation as exactly 24 hours after `created_at`, measured on the logical clock. The session also carries a `device_account_number` field, null until tokenization writes the minted DPAN onto it. Expiry is lazy: a session whose expiry has passed is flipped to `EXPIRED` the next time it is accessed — on verify, on tokenize, or on read — and the boundary is inclusive, so a clock reading exactly `expires_at` already means expired. On verify and tokenize this expiry flip happens before every other check, and the failed request surfaces `ERR_PROVISIONING_SESSION_EXPIRED` (priority 5).

Identity verification is two-factor in the strict counting sense. Each verify call presents a `method` — one of `OTP_TEXT`, `OTP_EMAIL`, or `ISSUER_APP`, recorded on the session as `verification_method` (each successive verify overwrites it, so the field reflects the most recent attempt's method) — and a `code`. The issued challenge value is not surfaced to the caller; for all three methods the canonical correct codes are the literals `111111`, `222222`, and `333333`, and any other `code` value counts as a wrong code. The first successful challenge leaves the session in `VERIFICATION_REQUIRED` and raises `verification_attempt_count` to 1; the second successful challenge — bringing the count to 2 — moves the session to `VERIFIED`. A wrong code is rejected with `ERR_OTP_MISMATCH` (HTTP 409), and the third consecutive mismatch on a session fails it outright: the session transitions to terminal `FAILED` even as the error is returned. Successes must therefore be consecutive in effect — a session that absorbs two mismatches is one mistake away from death.

Tokenization is the payoff step and the system's first OCC-guarded write. The tokenize request may carry `express_transit_enabled` (optional) and must carry `expected_session_version` matching the session's current `version`; a stale expectation is `ERR_VERSION_CONFLICT` (§2.5). Tokenize requires the session to be `VERIFIED` (anything else is a state-machine rejection), and then runs its gates in order: the device must be `HEALTHY` — a `DEGRADED` device yields `ERR_DEVICE_UNSECURED` and a `LOST` device yields `ERR_DEVICE_LOST`; the funding account must be `OPEN` and the issuer `ACTIVE` with an `ACTIVE` agreement (`ERR_CARD_ACCOUNT_RESTRICTED`, `ERR_ISSUER_NOT_ACTIVE`); requesting `express_transit_enabled` true requires the account's `card_product` to be `TRANSIT` and the agreement's `express_transit_supported` to be true, else `ERR_EXPRESS_TRANSIT_NOT_SUPPORTED`; and the session must still be inside its 24-hour window. The minted `device_account_number` — the DPAN — is a randomly generated 16-digit numeric string; it is generated independently of the card's PAN and must not collide with the DPAN of any existing non-terminated token (one in `PENDING`, `ACTIVE`, or `SUSPENDED`); the server retries internally with a fresh DPAN on collision, and an unresolvable collision surfaces as `ERR_VALIDATION` (priority 22).

On success, the session moves to `TOKENIZED`, its `version` increments by one, and a `PaymentToken` is created directly in `ACTIVE` status — bound to this device (`device_id`), this funding account (`card_account_id`), this artifact (`card_artifact_id`), and, denormalized for issuer scoping, the `issuer_id` — carrying the minted `device_account_number`, the requested `express_transit_enabled` flag, and a full set of zeroed counters: `auth_attempt_count`, `approved_auth_count`, `decline_count`, `consecutive_decline_count`, and `suspension_count`, plus null `last_decline_reason` and `deactivated_reason`. The device's `active_token_count` increments by one, and an `ACTIVATION` token event is appended to the new token. (The token entity does define a `PENDING` initial state on paper — the lifecycle axis is `PENDING | ACTIVE | SUSPENDED | DEACTIVATED` — but in practice tokens are minted directly into `ACTIVE` by tokenization; status is the single lifecycle axis while the counters evolve independently on the same row.)

### 3.5. Living With Tokens: Suspension, Resumption, Deactivation, and the Default Card

Once a token exists, the cardholder controls its day-to-day posture through three transitions. Suspending a token — `ACTIVE → SUSPENDED` — requires the token to be `ACTIVE` (else `ERR_INVALID_STATE`), increments its `suspension_count` by one, and appends a `SUSPENSION` event. Resuming — `SUSPENDED → ACTIVE` — is deliberately harder: the device must be `HEALTHY` (a `DEGRADED` device fails with `ERR_DEVICE_UNSECURED`, and per the device-lost rule a `LOST` device fails with `ERR_DEVICE_LOST`), the funding account must be `OPEN` (else `ERR_CARD_ACCOUNT_RESTRICTED`), and the token must actually be `SUSPENDED`. A successful resume appends a `RESUMPTION` event. Deactivation is available from either `ACTIVE` or `SUSPENDED` and is terminal: the token's `deactivated_reason` is recorded, the device's `active_token_count` is recomputed (as a fresh count of the device's tokens currently `ACTIVE`, never a blind decrement), a `DEACTIVATION` event is appended, and — critically — if the deactivated token was the device's default card, the device's `default_card_id` is cleared. The `deactivated_reason` value is one of `LOST_DEVICE`, `ISSUER_REVOKE`, `CARD_REISSUE`, `DEVICE_UNSECURED`, or `USER_REMOVE`, depending on which path killed the token.

There is also a suspension nobody asks for. When a token's `consecutive_decline_count` reaches 3 — the system's decline-streak threshold — the token auto-suspends: it moves `ACTIVE → SUSPENDED`, `suspension_count` increments, a `SUSPENSION` event is appended, and if the token was the device default, `default_card_id` is cleared. Auto-suspended tokens come back only through the ordinary resume flow with its full device-and-account gating.

Each device may designate exactly one default payment card. Setting the default is the second OCC-guarded write in the system: the request names a `token_id` and must carry `expected_device_version` matching the device's current `version`, with mismatches rejected as `ERR_VERSION_CONFLICT` (§2.5). The candidate token must be `ACTIVE` and bound to that device — otherwise `ERR_TOKEN_NOT_ACTIVE` (priority 21). Setting a new default replaces whatever `default_card_id` previously held; there is no multi-default. A successful set bumps the device's `version` by one. Reads of the device and per-device token listings let the cardholder observe the result.

### 3.6. Authorization: Cryptograms, Gates, and Declines

Authorization is where everything converges, and it is run exclusively by `IssuerOperator` — the issuer adjudicates its own book. The request carries the `cryptogram` payload, the `amount_cents`, an ISO `currency`, the `merchant_id`, a `merchant_category` of `GENERAL` or `TRANSIT`, and three optional flags/fields: `biometric_verified` (default false), `express_mode` (default false), and `transit_operator_id` for transit taps.

The architecture of an authorization attempt is two-phase, and the boundary between phases is the single most important rule in this subsection. **Phase one** is the gate chain — priorities 8 through 17 of §2.10, evaluated in order. A failure at any gate rejects the request with that gate's 4xx error and **no `Authorization` row is persisted at all**; none of the token's decline counters move. **Phase two** begins only when every gate passes: a `PENDING` `Authorization` row is created, the token's `auth_attempt_count` increments by one, the token's `version` increments by one, and the cryptogram payload alone decides the outcome. A cryptogram equal to the literal `DECLINE` resolves the authorization `DECLINED` with `declined_reason` `ISSUER_DECLINED`; the literal `DECLINE_FRAUD` resolves it `DECLINED` with `declined_reason` `FRAUD_SUSPECTED`; any other cryptogram value resolves it `APPROVED`. An approval increments the token's `approved_auth_count` by one, resets `consecutive_decline_count` to zero, accrues the issuer fee (below), and appends an `AUTHORIZATION_APPROVED` event. A decline increments `decline_count` and `consecutive_decline_count` by one each, records the reason in the token's `last_decline_reason`, appends an `AUTHORIZATION_DECLINED` event — and when the streak reaches 3, fires the auto-suspension of §3.5. Both `APPROVED` and `DECLINED` are terminal for the authorization.

The gate chain, slot by slot. First (8) the token must be `ACTIVE`, else `ERR_TOKEN_NOT_ACTIVE`. Then (9) the device must not be `DEGRADED` — tokenize, resume, and every non-express authorization require a passcode; an express-mode tap is exempt from this gate by design, mirroring the authentication gate below — else `ERR_DEVICE_UNSECURED`; and (10) a `LOST` device blocks tokenize, resume, and authorization in any mode with `ERR_DEVICE_LOST`. Next (11) the funding account's issuer must be `ACTIVE` and hold an `ACTIVE` agreement at authorization time, else `ERR_ISSUER_NOT_ACTIVE`; and (12) the funding account itself must be `OPEN`, else `ERR_CARD_ACCOUNT_RESTRICTED`. The authentication gate (13) follows: on a device with `biometric_enabled` true, a non-express authorization presented with `biometric_verified` false fails with `ERR_AUTHENTICATION_REQUIRED` (HTTP 422); express-mode authorizations skip this gate entirely, which is precisely why express mode is restricted below. Then the fiscal caps: (14) `amount_cents` must not exceed the global per-authorization cap of 100000 cents, else `ERR_AUTH_AMOUNT_EXCEEDS_CAP`; and (15) when the request's `merchant_id` equals the `merchant_name` of a merchant program in which the account holds an `ACTIVE` enrollment and whose own status is `ACTIVE`, the amount must not exceed that program's `max_auth_amount_cents`, else `ERR_PROGRAM_AMOUNT_EXCEEDS_CAP`. Express eligibility (16) requires the whole chain — token `express_transit_enabled`, account `card_product` `TRANSIT`, agreement `express_transit_supported`, and an `ACTIVE` transit operator whose `express_cap_cents` is at least the requested amount — else `ERR_EXPRESS_TRANSIT_NOT_SUPPORTED`. Finally (17), when the operator's `allowlist_active` flag is set, the funding account must appear on that operator's allowlist in `ACTIVE` standing, else `ERR_TRANSIT_NOT_ALLOWED`; a `SUSPENDED` operator likewise blocks the tap under the same code.

One transit-specific calculation sits on top of the gates. For an express-mode tap (`merchant_category` `TRANSIT`, `express_mode` true), the effective express ceiling is the smaller of the operator's `express_cap_cents` and the global 100000-cent cap — the global cap is enforced independently at gate 14, and gate 16 enforces the operator's `express_cap_cents` as a hard cap applied before decline-reason evaluation: a requested amount above the ceiling is rejected at the gate and is never partially approved. The recorded and fee-bearing `amount_cents` on a successful authorization is exactly the requested amount; no clamping occurs after the gates pass.

Issuer fees accrue per issuer agreement and come in two variants that share one formula. For a given authorization, the raw fee is the `amount_cents` multiplied by the agreement's `fee_bps` and divided by 10000 with floor division (truncation toward zero); the result is then capped from above by `fee_cap_cents` (the smaller of the raw fee and the cap is kept), and finally floored from below by `fee_floor_cents` (the larger of the capped value and the floor is kept). The **accrual** variant is computed at approval time and persisted to the agreement's running fee ledger, counting only `APPROVED` authorizations. The **projection** variant — what the issuer-fee-projection read returns — is computed at read time, never persisted, and counts `APPROVED` plus `PENDING` authorizations. The two variants must therefore diverge whenever at least one `PENDING` authorization exists for the issuer, and agree when none does. The projection read returns `projected_fee_cents`, `approved_fee_cents`, and `authorization_count`, and is available to `IssuerOperator`, `PlatformAdmin`, and `CustomerService`. When the issuer has no `ACTIVE` agreement at read time, every authorization contributes zero to both fee figures, so both return 0 while `authorization_count` still counts the `APPROVED` plus `PENDING` authorizations.

### 3.7. Disputes, Restriction, and Risk

A wallet charge that a cardholder doesn't recognize becomes a `Dispute`, opened by the `Cardholder` or `CustomerService` against a specific authorization with a disputed `amount_cents` and a `reason` of `UNRECOGNIZED`, `DUPLICATE`, `FRAUD`, or `GOODS_NOT_RECEIVED`. Traceability is the point of the design: the dispute's `card_account_id` is not supplied by the caller but computed by tracing the authorization's token back to its funding account, and `payment_token_id` and `authorization_id` are likewise recorded from the path. Creation is guarded at priority 19: the disputed amount must equal the authorization's `amount_cents` exactly — otherwise `ERR_DISPUTE_AMOUNT_MISMATCH` — and the authorization must be in `APPROVED` status, otherwise `ERR_INVALID_STATE`. A dispute is born `OPEN`, and opening a `FRAUD` dispute has an immediate system effect: the funding `CardAccount` moves `OPEN → RESTRICTED`, freezing it out of the account-open gates (priority 12) until the dispute resolves.

Resolution is an `IssuerOperator` decision expressed as an `outcome` of `WON` or `LOST` against an `OPEN` dispute (any other state fails `ERR_INVALID_STATE`). Either outcome moves the dispute to its terminal state, and either outcome of a `FRAUD` dispute flips the account back `RESTRICTED → OPEN`. The system exposes open exposure per account as `total_disputed_cents` — the sum of `amount_cents` over disputes in `OPEN` status traced to that account — computed on demand from the dispute set rather than stored on the account, and resolution removes the dispute's amount from that open set. The conservation invariant holds across create-and-resolve pairs: the platform-wide sum of open disputed amounts changes by exactly the disputed amount at creation and by exactly its negation at resolution.

Risk scoring gives issuers and the platform a single read of account health. The account risk read — available to `IssuerOperator`, `PlatformAdmin`, and `CustomerService` — returns `risk_score`, `open_dispute_count`, and `open_disputed_cents`. The score is computed as: four points per decline accumulated by tokens of the account that currently carry an `OPEN` dispute; plus one point per decline accumulated by the account's other tokens; plus a flat 15-point bonus for each `OPEN` dispute on the account; plus a flat 25-point bonus if any device bound to the account's tokens is currently reported lost. The result is capped at 100 and can never go below zero.

The issuer-level teardown paths close the loop. Suspending an `ACTIVE` issuer — `ACTIVE → SUSPENDED` — cascades: every `ACTIVE` payment token with that `issuer_id` moves to `SUSPENDED`, each with `suspension_count` incremented and a `SUSPENSION` event appended. Reactivating a suspended issuer (`SUSPENDED → ACTIVE`) is allowed without precondition, but deliberately does **not** resume any tokens — suspended tokens return only through the per-token resume flow. Offboarding, from either `ACTIVE` or `SUSPENDED`, is terminal (`OFFBOARDED`) and comprehensive: every card account of the issuer in `OPEN` or `RESTRICTED` moves to `CLOSED`, and each closed account cascades to its tokens, moving every `ACTIVE` or `SUSPENDED` token to `DEACTIVATED` with `deactivated_reason` `ISSUER_REVOKE` and a `DEACTIVATION` event per token. Recall from §3.1 that terminating an issuer's last `ACTIVE` agreement also drops the issuer to `SUSPENDED`, firing the same suspension cascade — agreement hygiene and issuer posture are one mechanism.

### 3.8. Merchant Programs and Transit Operators

Merchant programs let an issuer attach merchant-specific behavior to enrolled cards. An `IssuerOperator` or `PlatformAdmin` creates a `MerchantProgram` under an `issuer_id` with a `program_code` (unique per issuer among non-retired programs), a `merchant_name`, a `required_pan_last4` constraint (an empty string means no constraint), a `max_auth_amount_cents` ceiling, and an optional `active_sessions_required` flag defaulting to true. Programs are born `ACTIVE` and may later be `RETIRED`. Programs are readable singly, as a filterable list (by `issuer_id` and `status`), and through their enrollments.

Enrollment — creating a `MerchantCardProgram` row joining `merchant_program_id` to `card_account_id`, stamped with `enrolled_at` and born `ACTIVE` (the alternative status being `REVOKED`) — may be performed by the `Cardholder` or an `IssuerOperator` and is guarded at priority 18. The program must be `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`). The card account must be `OPEN` — because a `CardAccount` has no `SUSPENDED` status, the `active_sessions_required` flag never widens the account-state gate — otherwise the rejection is `ERR_CARD_ACCOUNT_RESTRICTED` under the account-open gate. And when `required_pan_last4` is non-empty, the `pan_last4` of the account's earliest-created card artifact must match it exactly, else `ERR_PROGRAM_INELIGIBLE`; when the constraint is the empty string this check is skipped entirely. Enrollment rows are listable per card account, per program, and globally with `merchant_program_id`, `card_account_id`, and `status` filters. Enrolled programs feed back into authorization through the program cap (gate 15, §3.6).

Transit is the other overlay. A `PlatformAdmin` registers a `TransitOperator` with an `operator_code` that must be unique across all operators (a duplicate is rejected with `ERR_VALIDATION`), a display `name`, a `flat_fare_cents` recorded as the per-tap fare reference (it is stored and returned but does not alter the authorized amount, which is always the requested `amount_cents`), an `express_cap_cents` ceiling for express-mode authorizations at this operator, and an optional `allowlist_active` flag defaulting to false. Operators are born `ACTIVE` and may be `SUSPENDED` — and a suspended operator blocks taps under `ERR_TRANSIT_NOT_ALLOWED` as described in §3.6. When `allowlist_active` is true, only allowlisted cards may tap: `IssuerOperator` and `PlatformAdmin` add accounts to an operator's allowlist by creating `TransitAllowlist` rows keyed on `transit_operator_id` and `card_account_id`, born `ACTIVE` with `REMOVED` as the exit status. Allowlist entries are listable per operator, per card account, and globally with `transit_operator_id`, `card_account_id`, and `status` filters. Remember that `TransitAllowlist` rows are lightweight: they carry `id` and `created_at` only (§2.4).

### 3.9. Reading the System

Every entity in the system is readable by any caller, with or without authentication, consistent with the `Any` role's coverage of all GET endpoints. Single-resource reads exist for cardholders, devices, issuers, agreements, card accounts, artifacts, provisioning sessions, tokens, disputes, merchant programs, merchant-card enrollments, transit operators, allowlist entries, and the clock-adjacent computed reads. Collection reads exist per parent — devices of a cardholder, agreements of an issuer, artifacts of an account, provisioning sessions of a device, tokens of a device, authorizations of a token, disputes of a token, merchant enrollments of a card account or of a program, allowlist entries of an operator or of a card account, and the audit events of a token — and as global filterable lists for card accounts, merchant programs, enrollments, provisioning sessions (`device_id`, `card_artifact_id`, `status`), payment tokens (`device_id`, `card_account_id`, `card_artifact_id`, `issuer_id`, `status`), authorizations (`payment_token_id`, `status`, `merchant_id`), disputes (`payment_token_id`, `authorization_id`, `card_account_id`, `status`), allowlist entries, card artifacts (`card_account_id`, `status`), and token events (`payment_token_id`, `event_type`). All list reads follow the pagination and ordering contract of §2.3, and all reads of a device recompute `security_posture` before responding (§2.11). The fee-projection read (§3.6) and the risk read (§3.7) are the two computed reads with restricted role sets; everything else is open.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, drive a state transition, or serve a read respond with HTTP 200. The two OCC-guarded writes and all error semantics are as specified in §2 and §3; request and response bodies are reconstructable from the narratives above and are intentionally not repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /cardholders | Register a cardholder | Any |
| GET | /cardholders/{cardholderId} | Get a cardholder | Any |
| POST | /devices | Register a device for a cardholder | Cardholder |
| GET | /devices/{deviceId} | Get a device (security_posture computed at read) | Any |
| GET | /cardholders/{id}/devices | List devices of a cardholder | Any |
| POST | /devices/{deviceId}/set-security | Set passcode/biometric flags | Cardholder |
| POST | /devices/{deviceId}/report_lost | Mark the device lost; suspends its active tokens | Cardholder, IssuerOperator, CustomerService |
| POST | /devices/{deviceId}/report_found | Mark the device found | Cardholder, CustomerService |
| POST | /issuers | Create an issuer | PlatformAdmin |
| GET | /issuers/{issuerId} | Get an issuer | Any |
| POST | /issuers/{issuerId}/activate | Activate an issuer (requires an ACTIVE agreement) | PlatformAdmin |
| POST | /issuers/{issuerId}/suspend | Suspend an issuer (cascades token suspension) | PlatformAdmin |
| POST | /issuers/{issuerId}/offboard | Offboard an issuer (closes accounts, deactivates tokens) | PlatformAdmin |
| GET | /issuers/{issuerId}/fee-projection | Fee projection (APPROVED + PENDING authorizations) | IssuerOperator, PlatformAdmin, CustomerService |
| POST | /issuer-agreements | Create an issuer agreement | PlatformAdmin |
| GET | /issuer-agreements/{agreementId} | Get an issuer agreement | Any |
| GET | /issuers/{id}/agreements | List agreements of an issuer | Any |
| POST | /issuer-agreements/{agreementId}/activate | Activate an agreement | PlatformAdmin |
| POST | /issuer-agreements/{agreementId}/supersede | Supersede this agreement with new terms | PlatformAdmin |
| POST | /issuer-agreements/{agreementId}/terminate | Terminate an agreement (may suspend the issuer) | PlatformAdmin |
| POST | /card-accounts | Open a card account | IssuerOperator, PlatformAdmin |
| GET | /card-accounts/{cardAccountId} | Get a card account | Any |
| GET | /card-accounts | List card accounts (filterable) | Any |
| POST | /card-accounts/{cardAccountId}/reissue | Reissue the account (successor created; artifacts/tokens deactivated) | IssuerOperator |
| POST | /card-accounts/{cardAccountId}/close | Close the account | IssuerOperator |
| GET | /card-accounts/{cardAccountId}/risk | Aggregate risk score of the account | IssuerOperator, PlatformAdmin, CustomerService |
| POST | /card-artifacts | Create a card artifact on an account | IssuerOperator |
| GET | /card-artifacts/{cardArtifactId} | Get a card artifact | Any |
| GET | /card-accounts/{id}/artifacts | List artifacts of an account | Any |
| POST | /card-artifacts/{cardArtifactId}/suspend | Suspend an artifact (token cascade) | IssuerOperator |
| POST | /card-artifacts/{cardArtifactId}/resume | Resume an artifact | IssuerOperator |
| POST | /card-artifacts/{cardArtifactId}/deactivate | Deactivate an artifact (token cascade to DEACTIVATED) | IssuerOperator |
| POST | /devices/{deviceId}/provisioning-sessions | Start card provisioning for a device | Cardholder |
| GET | /devices/{id}/provisioning-sessions | List provisioning sessions of a device | Any |
| GET | /provisioning-sessions/{sessionId} | Get a provisioning session | Any |
| POST | /devices/{deviceId}/provisioning-sessions/{sessionId}/verify | Complete one identity challenge (OTP or issuer-app) | Cardholder |
| POST | /devices/{deviceId}/provisioning-sessions/{sessionId}/tokenize | Mint the DPAN and create the bound PaymentToken (OCC on session version) | Cardholder |
| GET | /devices/{id}/tokens | List tokens on a device | Any |
| GET | /payment-tokens/{tokenId} | Get a payment token | Any |
| POST | /devices/{deviceId}/tokens/{tokenId}/suspend | Suspend a token | Cardholder |
| POST | /devices/{deviceId}/tokens/{tokenId}/resume | Resume a suspended token | Cardholder |
| POST | /devices/{deviceId}/tokens/{tokenId}/deactivate | Deactivate (delete) a token | Cardholder |
| POST | /devices/{deviceId}/default-card | Set the device default card (OCC on device version) | Cardholder |
| POST | /payment-tokens/{tokenId}/authorizations | Attempt an authorization carrying a cryptogram | IssuerOperator |
| GET | /payment-tokens/{id}/authorizations | List authorizations of a token | Any |
| POST | /authorizations/{authorizationId}/disputes | Open a dispute traced from a wallet transaction to the card account | Cardholder, CustomerService |
| GET | /disputes/{disputeId} | Get a dispute | Any |
| GET | /payment-tokens/{id}/disputes | List disputes of a token | Any |
| POST | /disputes/{disputeId}/resolve-dispute | Resolve a dispute WON or LOST | IssuerOperator |
| POST | /merchant-programs | Create a merchant program under an issuer | IssuerOperator, PlatformAdmin |
| GET | /merchant-programs/{programId} | Get a merchant program | Any |
| POST | /merchant-card-programs | Enroll a card account in a merchant program | Cardholder, IssuerOperator |
| GET | /card-accounts/{id}/merchant-enrollments | List merchant program enrollments of a card | Any |
| POST | /transit-operators | Register a transit operator | PlatformAdmin |
| GET | /transit-operators/{operatorId} | Get a transit operator | Any |
| POST | /transit-allowlist | Add a card account to an operator's allowlist | IssuerOperator, PlatformAdmin |
| GET | /transit-operators/{id}/allowlist | List allowlist entries of an operator | Any |
| GET | /payment-tokens/{id}/events | List the token's audit events | Any |
| GET | /merchant-programs | List merchant programs (filterable by issuer) | Any |
| GET | /merchant-card-programs | List merchant program enrollments (filterable) | Any |
| GET | /provisioning-sessions | List provisioning sessions (filterable) | Any |
| GET | /payment-tokens | List payment tokens (filterable) | Any |
| GET | /authorizations | List authorizations (filterable) | Any |
| GET | /disputes | List disputes (filterable) | Any |
| GET | /transit-allowlist | List transit allowlist entries (filterable) | Any |
| GET | /token-events | List token audit events (filterable) | Any |
| GET | /card-artifacts | List card artifacts (filterable) | Any |
| GET | /merchant-programs/{id} | Get a merchant program (id-keyed) | Any |
| GET | /merchant-card-programs/{id} | Get one merchant card enrollment | Any |
| GET | /merchant-programs/{id}/enrollments | List enrollments under a merchant program | Any |
| GET | /transit-allowlist/{id} | Get one allowlist entry | Any |
| GET | /card-accounts/{id}/transit-allowlist | List allowlist entries for a card account | Any |
| POST | /_clock/set_current_utc | Set the logical clock (startup default 2026-09-01T00:00:00Z) | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflows they guard; this table fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_ISSUER_NOT_FOUND | 404 |
| ERR_DEVICE_NOT_FOUND | 404 |
| ERR_TOKEN_NOT_FOUND | 404 |
| ERR_CARD_ACCOUNT_NOT_FOUND | 404 |
| ERR_AUTHORIZATION_NOT_FOUND | 404 |
| ERR_DISPUTE_NOT_FOUND | 404 |
| ERR_AGREEMENT_NOT_FOUND | 404 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_OPERATOR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_INVALID_TRANSITION | 409 |
| ERR_IDEMPOTENCY_CONFLICT | 409 |
| ERR_VERSION_CONFLICT | 412 |
| ERR_DEVICE_UNSECURED | 409 |
| ERR_DEVICE_LOST | 409 |
| ERR_TOKEN_NOT_ACTIVE | 409 |
| ERR_CARD_ACCOUNT_RESTRICTED | 409 |
| ERR_CARD_HAS_OPEN_DISPUTES | 409 |
| ERR_PROVISIONING_SESSION_EXPIRED | 409 |
| ERR_OTP_MISMATCH | 409 |
| ERR_ISSUER_NOT_ACTIVE | 409 |
| ERR_AGREEMENT_REQUIRED | 409 |
| ERR_AGREEMENT_OVERLAP | 409 |
| ERR_TERMS_VALIDATION_FAILED | 422 |
| ERR_AUTHENTICATION_REQUIRED | 422 |
| ERR_AUTH_AMOUNT_EXCEEDS_CAP | 422 |
| ERR_PROGRAM_AMOUNT_EXCEEDS_CAP | 422 |
| ERR_EXPRESS_TRANSIT_NOT_SUPPORTED | 422 |
| ERR_TRANSIT_NOT_ALLOWED | 422 |
| ERR_PROGRAM_NOT_ACTIVE | 409 |
| ERR_PROGRAM_INELIGIBLE | 409 |
| ERR_DISPUTE_AMOUNT_MISMATCH | 409 |
