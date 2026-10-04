# Medical Identification Membership API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Medical Identification Membership API, the back-end for a foundation operating a medical identification and emergency record service. Members wear an engraved identifier product — a bracelet, necklace, or card — whose lookup code connects emergency responders to the member's verified medical profile in seconds. The value of the service rests on three pillars: the medical record behind each identifier must be verified against provider documentation before it is disclosed; the membership must remain in good standing so the identifier remains disclosable; and every access to a member's record must be authenticated, scoped to the requester's need to know, and recorded in a tamper-evident audit trail.

The API orchestrates the full lifecycle of that promise. It covers member enrollment with tier-based fees, capture and verification of conditions, medications and allergies, ordering of engraved identification products whose text can stay synchronized with the underlying record, emergency responder access by identifier lookup or operator-assisted hotline, storage of advance directives with graduated release rules, wandering-response support for members with cognitive conditions, renewal and reminder cycles with lapse handling, delegated administration of minor and dependent memberships by guardians, and a dispute channel through which members challenge the accuracy of their own records.

Because the audience spans paying members, caregivers, clinical verifiers, engravers, hotline staff, emergency responders, and platform administrators, the document is organized first by the system-wide contracts every consumer relies on, then by the business workflows each actor participates in, and finally by the endpoint and error catalogues that anchor the prose to a concrete HTTP surface.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules, envelope contracts, and invariants that apply to every endpoint in the system.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once headers are present, the role is checked against the endpoint's authorization list; a role not permitted for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes seven roles, spelled exactly as follows: `Member`, `Guardian`, `RecordVerifier`, `Responder`, `HotlineOperator`, `FulfillmentAgent`, and `PlatformAdmin`.

Identity binding differs by role, and the binding determines how `X-User-ID` is interpreted:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`. A `Member` may act only on their own record — self-service operations on another member's resources are rejected with `ERR_GUARDIANSHIP_REQUIRED`.
- When `X-User-Role` is `Guardian`, `X-User-ID` is also the `id` of a `Member` — the administering adult. A `Guardian` acting on a dependent's resource must hold an `ACTIVE` `GuardianLink` whose `guardian_member_id` equals `X-User-ID` and whose `member_id` equals the path's `memberId`; otherwise the request is rejected with `ERR_GUARDIANSHIP_REQUIRED` (HTTP 403).
- When `X-User-Role` is `Responder`, `X-User-ID` is the `id` of the acting `ResponderCredential`; for identifier-based emergency access it must equal the `id` of the credential that owns the presented `credential_code`.
- When `X-User-Role` is `RecordVerifier`, `HotlineOperator`, `FulfillmentAgent`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as the `operator_id` field an access event carries when the lookup was operator-assisted, or as `actor_id` on audit rows — but it is never compared against any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry four fields in the `meta` block of the envelope: `limit`, `offset`, `total_count`, and `has_more`. List filters are simple exact-match query parameters and are listed per endpoint in §4; no other filtering is supported.

### 2.4. Logical Clock and Lapse Sweep

The service keeps its own logical clock rather than trusting wall-clock time. Before any client interaction, the logical clock reads exactly `2026-09-01T00:00:00Z`; it is the only notion of "today" the server will ever use for expiry, reminder due dates, trailing-window counts, or age derivation, and it must never silently fall back to wall-clock time. An admin-only test-driving capability advances this logical clock to a supplied `current_utc` instant, and the response echoes the new `current_utc`.

Advancing the clock is not a passive operation: it triggers the **lapse sweep**. Every `Member` whose `status` is `ACTIVE`, whose `membership_tier` is anything other than `LIFETIME`, and whose `expires_on` is on or before the new logical date transitions to `SUSPENDED` per the member lifecycle (see §3.2). Members on the `LIFETIME` tier never lapse.

### 2.5. Validation Order and Nested Resource Retrieval

When several checks could reject the same request, the server evaluates them in a fixed priority order so the surfaced error is deterministic. The order is:

1. Authentication header presence — missing or empty headers produce `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization for the endpoint — `ERR_INSUFFICIENT_PERMISSIONS`.
3. Path identifier existence, validated left-to-right — `ERR_MEMBER_NOT_FOUND` for a bad `memberId`, then the child-segment errors `ERR_RECORD_ITEM_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, or `ERR_RESPONDER_NOT_FOUND` according to the segment type. Any id segment equal to the zero UUID `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id.
4. Guardian scoping — `ERR_GUARDIANSHIP_REQUIRED` when a `Guardian` lacks the link described in §2.1, or when a `Member` touches another member's resource.
5. Member lifecycle gating — `ERR_MEMBER_NOT_ACTIVE` when the operation requires an `ACTIVE` member (see §2.6).
6. State-machine from-state checks — `ERR_INVALID_STATE` when the target entity is not in the state the transition requires (for example, confirming an order that is not `PENDING`, engraving one that is not `CONFIRMED`, resolving a ticket that is not `OPEN`, or resolving a dispute that is not `UNDER_REVIEW`).
7. Payload shape — `ERR_INVALID_REQUEST` for missing required fields, enum values outside their declared sets, malformed ISO 8601 dates, or integers out of range.
8. Uniqueness — `ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_CREDENTIAL`, or `ERR_DUPLICATE_SKU`, by resource.
9. Business-safety rules specific to the endpoint — emergency responder authentication (`ERR_RESPONDER_AUTH_FAILED`), member disclosability (`ERR_MEMBER_NOT_DISCLOSABLE`), wandering eligibility (`ERR_WANDERING_NOT_ELIGIBLE`), guardian-link validity (`ERR_GUARDIAN_LINK_INVALID`), contact priority conflicts (`ERR_CONTACT_PRIORITY_CONFLICT`), engraving capacity (`ERR_ENGRAVING_OVERFLOW`), dispute eligibility (`ERR_RECORD_ITEM_NOT_DISPUTABLE`), renewal funds (`ERR_INSUFFICIENT_FUNDS`), and optimistic-concurrency mismatches (`ERR_STALE_VERSION`).

For any nested path — for instance a record item addressed under a member — the parent segment is validated before the child, so a missing parent surfaces its 404 before the child is even looked up. A child id that exists but belongs to a different parent is treated as not found for this path and yields the child's 404 (`ERR_RECORD_ITEM_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`, or `ERR_CASE_NOT_FOUND` as applicable). Two resources have no error id of their own: a missing guardian-link id and a missing reminder id surface `ERR_MEMBER_NOT_FOUND`, as do missing access-event and audit-event ids.

### 2.6. Member Status Gating and Emergency Exception

Writes that mutate a member's records, orders, contacts, directives, wandering cases, or disputes require the member to be `ACTIVE`; against a `SUSPENDED` or `CANCELLED` member they are rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409). This gating covers record-item creation, submission for verification, and supersession; order creation, confirmation, and cancellation (but not the `FulfillmentAgent`-only engrave and ship transitions, which are exempt and may proceed even when the member is not `ACTIVE`); contact creation and removal; directive creation and revocation; opening a wandering case (but not resolving one); and opening a dispute.

Emergency record access is the deliberate exception. Because an engraved identifier must keep working through a billing lapse, access to a `SUSPENDED` member's record is still granted under the emergency rules of §3.6. A `CANCELLED` member, by contrast, is never disclosed — see §3.6.

### 2.7. Common Resource Properties and Money Precision

Most resources in the system carry the standard four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, the same format, refreshed on every mutation; and `version`, an integer that starts at 1 and increments by 1 on every mutation of the resource. Record timestamps are taken from the logical clock of §2.4 — the same clock that drives expiry and reminders — normalized to milliseconds; only the envelope's `api_request_timestamp` uses wall-clock UTC. Three resources are append-only logs and carry only `id` and `created_at` — both `updated_at` and `version` are absent: `AccessEvent`, `Reminder`, and `AuditEvent`.

Separately from `version`, every `Member` also carries a `record_revision` integer that starts at 0 and increments on every medical-record change (creation, verification, supersession of a record item). It is a content revision, not an optimistic-concurrency token, and it drives engraving freshness for synchronized orders.

All monetary amounts are integers of **whole cents** with zero decimal places. Where a calculation multiplies a base by a fractional factor — the dependent discount on membership fees, or a percentage discount on an order — the product is rounded half-up to whole cents at the step the scaffold of each calculation pins (see §3.1 and §3.4). Monetary values in API payloads are plain integers, never strings.

### 2.8. Optimistic Concurrency Control

Two write endpoints take a mandatory optimistic-concurrency token. Confirming a product order requires the request to carry `expected_member_version`, the client's last observed `version` of the purchasing `Member`. Superseding a verified record item likewise requires `expected_member_version`, the client's last observed `version` of the owning `Member`. If the supplied value does not equal the member's current `version` — because some other write has advanced the member since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; requests to other endpoints never include a concurrency token.

### 2.9. The Audit Spine

Every state-changing workflow in the system appends an `AuditEvent` row naming the acting role (`actor_role`, the request's `X-User-Role`), the actor (`actor_id`, the request's `X-User-ID`), a machine `action` name, and a `detail` payload snapshot carrying entity ids and before/after field values. Audit events are scoped to the subject member — every row carries a `member_id` — and are queryable through the per-member audit feed or the platform-wide audit feed. Audit rows are immutable once written: there is no endpoint that mutates or deletes one, and they have no `updated_at` or `version`. Machine action names include `ENROLL`, `RENEWAL`, `LAPSE`, `CANCEL`, `RECORD_CAPTURE`, `RECORD_VERIFY`, `RECORD_REJECT`, `RECORD_RESUBMIT`, `RECORD_SUPERSEDE`, `GUARDIAN_LINK`, `GUARDIAN_REVOKE`, `CONTACT_ADD`, `CONTACT_REMOVE`, `DIRECTIVE_STORE`, `DIRECTIVE_RELEASE`, `DIRECTIVE_REVOKE`, `ORDER_CONFIRM`, `ORDER_ENGRAVE`, `ORDER_SHIP`, `ORDER_CANCEL`, `ACCESS_GRANT`, `ACCESS_RATE_FLAG`, `WANDERING_OPEN`, `WANDERING_RESOLVE`, `DISPUTE_OPEN`, `DISPUTE_CLAIM`, `DISPUTE_RETURN`, `DISPUTE_RESOLVE`, and `DISPUTE_DISMISS`.

## 3. Business Logic & Workflows

### 3.1. Enrollment, Tiers, and the Membership Fee

A `PlatformAdmin` enrolls a new member by supplying the member's legal `full_name`, a contact `email`, a `membership_tier` of `STANDARD`, `PREMIUM`, or `LIFETIME`, and a `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form. The email must be unique across all members; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. From `date_of_birth` and the current logical date, the system derives `member_type`: a person younger than 18 at enrollment becomes `MINOR`, otherwise `ADULT`, where age is completed years — a person turns 18 on their eighteenth birthday. The derivation is fixed at enrollment and does not drift as the member ages.

Enrollment immediately places the member in `ACTIVE` status, mints a public `identifier_code` in the format `MID-######` — unique, printed on the engraved products, and never used for ordering or tie-breaks — and computes `expires_on` as the current logical date (the enrollment date) plus the tier's term: twelve months for `STANDARD`, twenty-four months for `PREMIUM`, with month addition clamped to the last day of the target month when the day overflows. For `LIFETIME` members `expires_on` is null; their membership never expires, never lapses, and never renews.

The enrollment fee is computed by the membership-fee schedule. The base fee is 4000 cents for `STANDARD` per twelve-month term, 7500 cents for `PREMIUM` per twenty-four-month term, and 50000 cents for `LIFETIME` as a one-time charge with no renewal. When the member being enrolled or renewed is administered — meaning they hold an `ACTIVE` `GuardianLink` as the dependent — the base is multiplied by a dependent factor of one-half, with the product rounded half-up to whole cents immediately after the multiplication. When the member's `has_cognitive_condition` is true at the time the fee is computed (at renewal time; at enrollment the flag is always false, so a fresh enrollment never pays the surcharge), a flat cognitive-service surcharge of 1000 cents is added. The evaluation order is pinned: the dependent factor is applied to the base and rounded first, and only then is the cognitive surcharge added; the dependent factor never amplifies the surcharge. The resulting fee is debited to the member's `balance_cents`, which starts at 0.

Every enrollment also opens the member's reminder cadence: a `RENEWAL` reminder is scheduled for non-`LIFETIME` members, due thirty days before the computed `expires_on`, and a `RECORD_UPDATE` reminder is scheduled regardless of tier, due one hundred eighty days after the enrollment date (see §3.7). The member's prepaid `wallet_credit_cents` starts at 0, and an `AuditEvent` with action `ENROLL` is appended.

### 3.2. Renewal, Lapse, and Cancellation

Renewal serves two situations with the same funds logic but different term arithmetic. A `Member` or their `Guardian` initiates renewal by paying `amount_paid_cents`. The funds test is the same in both directions: the member's `wallet_credit_cents` plus the supplied `amount_paid_cents` must cover the renewal fee for their tier — computed exactly as in §3.1, including the dependent factor when an active guardianship exists and the cognitive surcharge when the member's `has_cognitive_condition` flag is currently true. A shortfall is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402). Funds are applied wallet-first: the wallet is debited by the lesser of its current balance and the renewal fee, and the remainder of the fee is covered from `amount_paid_cents`. Independently of how the funds are split, the renewal fee itself is debited to the member's `balance_cents`, exactly as the enrollment fee is in §3.1.

An **early renewal** moves `ACTIVE` to `ACTIVE`: the new `expires_on` is the later of the current `expires_on` and the current logical date, plus the tier's term — so an early renewal never shortens the remaining term. A **reactivation** moves `SUSPENDED` back to `ACTIVE`: the new `expires_on` is the current logical date plus the tier's term. In both cases the member's pending `RENEWAL` reminder is re-anchored to thirty days before the new `expires_on`; a reactivation additionally cancels this cycle's `LAPSE_WARNING` reminder. `LIFETIME` members cannot renew — their membership never suspends, so neither renewal transition applies to them — and a renewal request on their behalf, or on behalf of a `CANCELLED` member, is rejected with `ERR_INVALID_STATE` for failing the tier/status precondition. Each successful renewal appends an `AuditEvent` with action `RENEWAL`, and the member's `version` increments by 1.

The lapse sweep (§2.4) drives `ACTIVE` to `SUSPENDED` for non-`LIFETIME` members whose `expires_on` has arrived. The sweep cancels every `PENDING` reminder on the member, generates a fresh `LAPSE_WARNING` reminder due on `expires_on`, increments the member's `version` by 1, and appends an `AuditEvent` with action `LAPSE`. While `SUSPENDED`, the member cannot perform the writes listed in §2.6, but emergency access to their record continues to work — a deliberate safety rule.

Cancellation, from either `ACTIVE` or `SUSPENDED`, moves the member to the terminal `CANCELLED` state and is available to the `Member` themselves, their `Guardian`, or a `PlatformAdmin`; cancelling an already-`CANCELLED` member is rejected with `ERR_INVALID_STATE`. The cascade is comprehensive and identical from either source state: every `PENDING` `ProductOrder` is cancelled with a refund of its `price_cents` into the member's `wallet_credit_cents`; every `OPEN` or `UNDER_REVIEW` `Dispute` is dismissed; every `OPEN` `WanderingCase` is resolved with outcome `OTHER`; every `PENDING` reminder is cancelled; and every `ACTIVE` `GuardianLink` in which the member appears as either the dependent or the guardian is revoked. Each cascade-touched order, dispute, wandering case, and guardian link has its own `version` incremented by 1, the member's `version` increments by 1, and an `AuditEvent` with action `CANCEL` closes the record.

### 3.3. Medical Record Capture and Verification

The member's medical record is a set of `MedicalRecordItem` entries. A `Member` or `Guardian` captures a new item with an `item_kind` of `CONDITION`, `MEDICATION`, or `ALLERGY`; a `label` meant for engraving (for example, "Penicillin Allergy"); a free-text clinical `detail`; a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`; and a `provider_document_ref` pointing at the provider documentation the verifier will check. For condition items only, `condition_kind` distinguishes `GENERAL` from `COGNITIVE`; it defaults to `GENERAL` when omitted, and only the `COGNITIVE` value flags the member for wandering and caregiver services.

Capture places the item in `PENDING_VERIFICATION` and opens a `VerificationTicket` — status `OPEN`, `submission_round` 1 — carrying the same `provider_document_ref`. Three things happen on the owning `Member`: `record_revision` increments, `has_cognitive_condition` is recomputed, and the `RECORD_UPDATE` reminder is re-anchored (§3.7); the member's `version` increments by 1 as well. The flag `has_cognitive_condition` is true exactly when the member has at least one item with `status` `VERIFIED` whose `condition_kind` is `COGNITIVE`; a newly captured item is not yet verified, so capture alone never flips the flag true, though a capture that leaves the verified set unchanged may recompute it to the same value. Each item records its own `record_revision` snapshot equal to the member's revision immediately after that item's creation. Capturing an item appends an `AuditEvent` with action `RECORD_CAPTURE` and re-syncs every synchronized pending order per §3.5.

A `RecordVerifier` works the ticket queue and resolves each ticket with a `decision` and a mandatory non-empty `decision_note`, recorded on the ticket. Approval — decision `APPROVE` — requires the ticket to be `OPEN` and moves the underlying item from `PENDING_VERIFICATION` to `VERIFIED` while the ticket becomes `APPROVED`; the member's `has_cognitive_condition` is recomputed (and can flip true when the approved item is a `COGNITIVE` condition), `record_revision` increments, the member's `version` increments by 1, the item's own `version` increments by 1, the `RECORD_UPDATE` reminder is re-anchored, every synchronized pending order re-syncs per §3.5, and an `AuditEvent` with action `RECORD_VERIFY` is appended. Rejection — decision `REJECT` — moves the item to `REJECTED` and the ticket to `REJECTED`, increments the item's `version` by 1, and appends an `AuditEvent` with action `RECORD_REJECT`; rejection touches nothing on the member — no `record_revision` or `version` increment, no reminder re-anchor, no order re-sync.

Rejection is not the end of the line. A `Member` or `Guardian` may resubmit a `REJECTED` item for another round with fresh `provider_document_ref`, provided the member is `ACTIVE` and no `OPEN` ticket currently exists for that item — attempting either against a non-`REJECTED` item or while an `OPEN` ticket exists is rejected with `ERR_INVALID_STATE`. Resubmission updates the item's `provider_document_ref` to the fresh value, returns the item to `PENDING_VERIFICATION`, increments the item's `version` by 1, and opens a new ticket whose `submission_round` is the previous maximum round for that item plus one; it touches nothing else on the member — no `record_revision` or `version` increment, no reminder re-anchor, no order re-sync. An `AuditEvent` with action `RECORD_RESUBMIT` is appended. The loop is bounded only by verifier decisions.

Supersession is how a member corrects an already-`VERIFIED` item: the request supplies `replacement_label`, `replacement_detail`, fresh `provider_document_ref`, and — because supersession mutates derived fields on the member — the OCC token `expected_member_version` per §2.8. The member must be `ACTIVE`, and the item must be `VERIFIED` (a supersede against any other item status is rejected with `ERR_INVALID_STATE`). The old item moves `VERIFIED` → `SUPERSEDED` with its own `version` incremented by 1; a brand-new item is created in `PENDING_VERIFICATION` carrying the replacement label and detail, with `item_kind` and `severity` copied from the superseded item and `condition_kind` reset to the `GENERAL` default — supersede payloads never carry a `condition_kind`; a fresh ticket opens for the replacement at `submission_round` 1. The supersede endpoint returns the newly created replacement item (status `PENDING_VERIFICATION`) with HTTP 200, not the superseded original. On the member, `record_revision` increments, `version` increments by 1, and `has_cognitive_condition` is recomputed — it can flip false if the superseded item was the member's last verified `COGNITIVE` condition. An `AuditEvent` with action `RECORD_SUPERSEDE` is appended, and every synchronized pending order re-syncs per §3.5.

A ticket itself is a small lifecycle: `OPEN` on creation, and terminally `APPROVED` or `REJECTED` upon resolution. Tickets expose the verifier's round history for an item — each resubmission adds another round.

### 3.4. Identification Products, Ordering, and Pricing

The product catalog is administered by a `PlatformAdmin`, who registers each `IDProduct` with a unique `product_sku`, a display `product_name`, a `base_price_cents` at or above zero, and a `max_engrave_chars` of at least one describing how much text fits on the engraving surface. A duplicate SKU is rejected with `ERR_DUPLICATE_SKU`.

A `Member` or `Guardian` places a `ProductOrder` against a catalog product by supplying `product_id`, an `engraving_text`, and an optional `engrave_mode` of `MANUAL` or `SYNC_WITH_RECORD`, defaulting to `MANUAL`; an unknown `product_id` is rejected with `ERR_PRODUCT_NOT_FOUND` (HTTP 404). The order starts `PENDING` with a provisional `price_cents` computed from the member's tier at creation time. For `MANUAL` orders the engraving text is taken as given, subject to capacity: if the text's length exceeds the product's `max_engrave_chars`, creation is rejected with `ERR_ENGRAVING_OVERFLOW` (HTTP 422) — the server never silently truncates. For `SYNC_WITH_RECORD` orders the server overwrites `engraving_text` at creation from the member's verified record per §3.5 and stamps `synced_revision` with the member's current `record_revision`; for `MANUAL` orders `synced_revision` stays 0.

Pricing at both creation and confirm uses the order-pricing rule. The price is the product's `base_price_cents`. `PREMIUM` members receive a fifteen percent discount on the base, rounded half-up to whole cents. `STANDARD` members receive no discount. `LIFETIME` members receive a twenty-five percent discount on the base — except for their first-ever `SYNC_WITH_RECORD` order, which is free: its price is 0. The free-first-order entitlement is gated by the member's `first_lifetime_sync_order_consumed` flag, which is false until a `LIFETIME` member confirms an order in `SYNC_WITH_RECORD` mode; the flag is set at confirm time, not at creation. The provisional price therefore uses the tier and the flag as observed at creation, while the final price re-prices with the tier and the flag as observed at confirm — so when the tier or the flag changed between the two moments, the final price deliberately differs from the provisional one for identical product input. In particular, two `PENDING` synchronized orders on a `LIFETIME` member both see the free provisional price; whichever confirms second re-prices to the discounted, non-free final price.

Confirming an order is the point of commitment, and it is one of the two OCC-protected writes of §2.8: the request must carry `expected_member_version` matching the member's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The member must be `ACTIVE`, or the confirm is rejected with `ERR_MEMBER_NOT_ACTIVE`. For a `SYNC_WITH_RECORD` order, confirm first re-syncs: the engraving text is regenerated from the member's verified items, `synced_revision` is set to the member's current `record_revision`, and only then is the order priced — a stale engraving is never confirmed. For a `MANUAL` order, confirm re-checks capacity: if the engraving text exceeds the product's current `max_engrave_chars`, the confirm is rejected with `ERR_ENGRAVING_OVERFLOW` (HTTP 422). Then the final price is computed, the member's `balance_cents` is debited by that `price_cents`, and — when the order is synchronized and the member is `LIFETIME` — the member's `first_lifetime_sync_order_consumed` becomes true. An `AuditEvent` with action `ORDER_CONFIRM` is appended, and the member's `version` increments by 1.

After confirm, fulfillment is linear: a `FulfillmentAgent` engraves the order, moving `CONFIRMED` → `ENGRAVED` with an `AuditEvent` of action `ORDER_ENGRAVE`; then ships it, moving `ENGRAVED` → `SHIPPED`, which settles the ledger — the member's `balance_cents` is credited back by `price_cents` because the order is settled on shipment — the member's `version` increments by 1, and an `AuditEvent` with action `ORDER_SHIP` is appended. The engrave and ship transitions are exempt from the `ACTIVE`-member gating of §2.6, so fulfillment continues even if the member lapses mid-fulfillment.

Cancellation has two compensating branches. Cancelling a `PENDING` order moves it to `CANCELLED` with no financial side effects beyond an `AuditEvent` of action `ORDER_CANCEL`. Cancelling a `CONFIRMED` order reverses the confirm's ledger effect exactly: `balance_cents` is credited back by `price_cents` and the same amount lands in `wallet_credit_cents` as a refund, so balance and wallet return exactly to their pre-confirm values, the member's `version` increments by 1, with an `AuditEvent` of action `ORDER_CANCEL`. Engraved or shipped orders cannot be cancelled; an attempt is rejected with `ERR_INVALID_STATE`.

### 3.5. Engraving Synchronization

The promise of `SYNC_WITH_RECORD` is that the text on the member's wrist always reflects the current verified record. The regeneration rule runs whenever a `MedicalRecordItem` transitions into `VERIFIED` or `SUPERSEDED` while any of the member's orders is `PENDING` with `engrave_mode` `SYNC_WITH_RECORD`, and it runs again at confirm time per §3.4.

The engraving text is assembled from the member's items whose `status` is `VERIFIED`, ordered by severity rank — `CRITICAL` first, then `HIGH`, then `MEDIUM`, then `LOW` — with ties broken by `created_at` ascending, never by id. Each selected item contributes its `label`, and the lines are joined with the separator " | ". If the joined text exceeds the ordered product's `max_engrave_chars`, the lowest-severity lines are dropped from the tail of the ordering until the text fits; a member with zero verified items yields the empty string. After regeneration, `synced_revision` is set to the member's `record_revision`. This regeneration never rejects: overflow rejection happens only at confirm, and only for `MANUAL` orders, via `ERR_ENGRAVING_OVERFLOW` — synchronized orders absorb overflow by truncation. An order whose `synced_revision` trails the member's `record_revision` is considered stale; confirm refuses to proceed on a stale engraving by re-syncing first, so what ships always matches the record at confirm time.

### 3.6. Emergency Access, Disclosure Scope, and Rate Flagging

An emergency access begins when a `Responder` or `HotlineOperator` presents a `credential_code`, an `identifier_code`, a `lookup_method` of `IDENTIFIER` or `HOTLINE`, and — for the hotline path only — an `operator_id`. The hotline path requires the operator id and rejects the attempt otherwise with `ERR_RESPONDER_AUTH_FAILED` (HTTP 403); that rejection is still logged as a `DENIED` `AccessEvent` (its `responder_id` is null because no credential has been consulted yet, and its `operator_id` is null) before the error response is returned. The identifier path must carry no operator id at all, and one that does is rejected with `ERR_INVALID_REQUEST` (HTTP 400) as a payload-shape violation — that rejection happens before any access attempt is evaluated, so no `AccessEvent` row is recorded for it.

The responder credential behind the presented `credential_code` must exist, be `ACTIVE`, and have an `expires_on` strictly later than the current logical date — a credential is invalid on or after its expiry date. In addition, when the acting role is `Responder`, the `X-User-ID` header must equal the `id` of the credential that owns the presented `credential_code` (per §2.1); the `HotlineOperator` role is exempt from that identity binding. A credential that is unknown, `REVOKED`, or expired, a hotline lookup missing its `operator_id`, or a `Responder` whose `X-User-ID` does not match the credential's id fails authentication with `ERR_RESPONDER_AUTH_FAILED` (HTTP 403). Revocation is performed by a `PlatformAdmin`, moves the credential `ACTIVE` → `REVOKED` (revoking a non-`ACTIVE` credential is rejected with `ERR_INVALID_STATE`), and ensures every subsequent access attempt with that credential is denied on this same check. Credentials are registered by a `PlatformAdmin` with an `agency_name`, a globally unique `credential_code` (duplicates rejected with `ERR_DUPLICATE_CREDENTIAL`), an `access_tier` of `BASIC` or `FULL`, and an `expires_on`.

The member is then located by `identifier_code`. If no member carries that code, or the member's status is `CANCELLED`, the access is denied with `ERR_MEMBER_NOT_DISCLOSABLE` (HTTP 409) — cancelled members are never disclosed. `ACTIVE` and `SUSPENDED` members are both disclosable, per the safety exception of §2.6.

For a granted access, the disclosure scope is computed. The credential tier supplies the base scope: a `BASIC` credential discloses the member's conditions, medications, and allergies; a `FULL` credential additionally discloses emergency contacts, and discloses those advance directives whose `release_scope` is `EMERGENCY_AND_CONTACTS` or `FULL` and whose status is `STORED`. The wandering/cognitive override then widens the scope: when the member's `has_cognitive_condition` is true, directives with `release_scope` `EMERGENCY_ONLY` are also disclosed regardless of tier, and contacts are disclosed even to a `BASIC` credential; a cognitive flag also brings `EMERGENCY_AND_CONTACTS` and `FULL` directives into scope even for a `BASIC` credential. The `DIRECTIVES` section appears in `disclosed_scope` only when at least one directive is actually in scope and `STORED` — a member with no releasable directives yields no `DIRECTIVES` entry. The event's `disclosed_scope` is the union actually released, drawn from the section set {`CONDITIONS`, `MEDICATIONS`, `ALLERGIES`, `CONTACTS`, `DIRECTIVES`} and serialized in sorted order; `is_escalated` is true exactly when that union exceeds what the credential tier alone grants — so the same lookup against a cognitively flagged member yields a strictly larger scope with `is_escalated` true. A granted access also flips every in-scope `STORED` directive to `RELEASED` (a one-way disclosure marker; the directive remains readable), incrementing each flipped directive's `version` by 1, and appends an `AuditEvent` with action `DIRECTIVE_RELEASE` for each. The granted access endpoint returns the recorded `AccessEvent` with HTTP 201.

Every access attempt produces an `AccessEvent` row recording the `member_id`, the `responder_id`, the `lookup_method`, the `operator_id` when applicable, the `disclosed_scope`, the `is_escalated` flag, and an `outcome` of `GRANTED` or `DENIED`. This includes denied attempts: a denial is still logged as a `DENIED` row before the error response is returned. The `member_id` is resolved from the presented `identifier_code` before authentication runs, so a denied attempt against a known identifier still appears in that member's access-event feed; when no member carries the code, the denied row's `member_id` is null. Likewise the denied row's `responder_id` is the id of the credential behind the presented `credential_code` when one exists, and null when the credential is unknown. Denied events disclose nothing — their `disclosed_scope` is empty and `is_escalated` is false — and carry a `reason_code` equal to the denying error id; granted events leave `reason_code` null. Granted events append an `AuditEvent` with action `ACCESS_GRANT`; denied attempts append no audit event.

Finally, a soft rate cap guards against credential misuse. The system counts the responder's access events with `outcome` `GRANTED` within the trailing twenty-four hours, a window inclusive of the event being recorded. When that count exceeds ten, the access is still granted, but an `AuditEvent` with action `ACCESS_RATE_FLAG` is appended against the accessed member; the `AccessEvent` row itself is otherwise untouched — the flag lives only in the audit detail. The boundary is strict: a count of exactly ten does not flag, while a count of eleven does.

### 3.7. Reminders and the Dispatch Batch

Three reminder kinds keep members engaged. A `RENEWAL` reminder is due thirty days before `expires_on` and exists only for non-`LIFETIME` tiers; it is cancelled and re-anchored on every renewal. A `RECORD_UPDATE` reminder is due one hundred eighty days after the member's last record change, where the last record change is the latest `created_at` among the member's items whose status is `VERIFIED` or `PENDING_VERIFICATION`, falling back to the member's own `created_at` when no such item exists; it re-anchors whenever `record_revision` increments. A `LAPSE_WARNING` reminder is due on `expires_on` itself and is generated by the lapse sweep of §3.2.

Each `Reminder` carries a `reminder_kind` of `RENEWAL`, `RECORD_UPDATE`, or `LAPSE_WARNING`, a `due_on` date, and a `sent_on` date that stays null until dispatch. Dispatch is an ops-run batch performed by a `PlatformAdmin`: it sends every reminder in `PENDING` whose `due_on` is on or before the current logical date — the boundary is inclusive, so a reminder due today is sent today — stamping `sent_on` with the current logical date and moving the reminder to `SENT`, and returns a `sent_count` alongside the `sent_reminder_ids`. Reminders leave `PENDING` in only one other way: cancellation by the member cancel or lapse cascades, or by renewal re-anchoring, moving them to `CANCELLED`.

### 3.8. Guardianship, Contacts, Directives, and Wandering Support

**Guardianship.** A `PlatformAdmin` attaches a guardian to a dependent member by creating a `GuardianLink` with the `guardian_member_id` of the administering adult and a free-text `relation_label` such as "parent" or "caregiver". Three constraints guard creation, and a violation of any is rejected with `ERR_GUARDIAN_LINK_INVALID` (HTTP 409): the guardian must be an `ACTIVE` member whose `member_type` is `ADULT`; the guardian must differ from the dependent — self-links are forbidden; and the dependent must not already have another `ACTIVE` link. The dependent member's own status is not constrained — a link may be attached to a `SUSPENDED` or `CANCELLED` dependent. The link starts `ACTIVE` and is revoked either explicitly by a `PlatformAdmin` or by the member-cancel cascade, moving to the terminal `REVOKED` state with an `AuditEvent` of action `GUARDIAN_REVOKE`; revoking a link that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. While `ACTIVE`, the link both delegates the dependent's self-service operations to the guardian (§2.1) and, at renewal time, halves the dependent's base fee via the dependent factor of §3.1. Members can list the links where they are the dependent, list the links where they are the guardian, and platform staff can list links across the system filtered by `member_id`, `guardian_member_id`, or `status`.

**Emergency contacts.** A `Member` or `Guardian` adds a contact with a `contact_name`, an E.164 `phone`, and a `priority_rank` where 1 marks the primary contact; a `priority_rank` below 1 is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The rank must be unique among the member's contacts whose status is `ACTIVE`; a collision is rejected with `ERR_CONTACT_PRIORITY_CONFLICT` (HTTP 409). Removal is soft: a `Member` or `Guardian` removes a contact, moving it `ACTIVE` → `REMOVED` — removing a contact that is not `ACTIVE` is rejected with `ERR_INVALID_STATE` — the row stays for audit history — with `AuditEvent` actions `CONTACT_ADD` and `CONTACT_REMOVE` bracketing the lifecycle. Contact operations never mutate the member itself: neither adding nor removing a contact increments the member's `version` or `record_revision`.

**Advance directives.** A `Member` or `Guardian` stores a directive with a `directive_type` of `DNR`, `POLST`, `LIVING_WILL`, or `HEALTHCARE_PROXY`, a `document_ref` to the stored document, and a `release_scope` of `EMERGENCY_ONLY`, `EMERGENCY_AND_CONTACTS`, or `FULL` controlling which accessor tiers may read it. Storage lands the directive in `STORED` with an `AuditEvent` of action `DIRECTIVE_STORE`. From `STORED`, the directive moves to `RELEASED` only as a side effect of a granted emergency access whose disclosure rules reach it (§3.6), and to `REVOKED` when the `Member` or `Guardian` revokes it — revocation is also available from `RELEASED`, requires an `ACTIVE` member, is rejected with `ERR_INVALID_STATE` when the directive is already `REVOKED`, and appends an `AuditEvent` of action `DIRECTIVE_REVOKE`.

**Wandering support.** Members flagged with `has_cognitive_condition` may have a wandering case opened by their `Guardian` or by a `HotlineOperator`, recording how the case came in via `opened_via` — `SELF_REPORT` or `HOTLINE_ESCALATION`. Two eligibility constraints are enforced together, with violations rejected as `ERR_WANDERING_NOT_ELIGIBLE` (HTTP 409): the member's `has_cognitive_condition` must be true, and the member must not already have an `OPEN` case — at most one open case per member. Opening stamps `opened_at` with the current logical timestamp and appends an `AuditEvent` of action `WANDERING_OPEN`. Resolution, by the same two roles, requires an `outcome` of `REUNITED` or `OTHER`, stamps `resolved_at`, moves the case `OPEN` → `RESOLVED`, and appends an `AuditEvent` of action `WANDERING_RESOLVE`.

### 3.9. Accuracy Disputes

A member who believes a record item is wrong opens a `Dispute` naming the `record_item_id` and stating their case in `claim_text`. The disputed item must belong to the member in the path and must not be `SUPERSEDED`; otherwise the dispute is rejected with `ERR_RECORD_ITEM_NOT_DISPUTABLE` (HTTP 409). Opening lands the dispute in `OPEN` with an `AuditEvent` of action `DISPUTE_OPEN`.

The verifier queue then drives a cyclic review loop. A `RecordVerifier` claims a dispute, moving `OPEN` → `UNDER_REVIEW` with action `DISPUTE_CLAIM`. A claim can be handed back — `UNDER_REVIEW` → `OPEN` with action `DISPUTE_RETURN` — for another round. From `UNDER_REVIEW`, the verifier resolves with a `resolution` and a mandatory non-empty `resolution_note`, recorded on the dispute: resolution `UPHELD` moves the dispute to `RESOLVED_UPHELD`, while resolution `CORRECTED` moves it to `RESOLVED_CORRECTED` and, in the same operation, supersedes the disputed item through the full supersede side-effect set of §3.3 when the disputed item is `VERIFIED` — the old item becomes `SUPERSEDED`, a replacement item is created in `PENDING_VERIFICATION` copying the old item's label, detail, `item_kind`, and `severity`, with `condition_kind` reset to `GENERAL` and the disputed item's existing `provider_document_ref` carried over, with a fresh ticket, the member's `record_revision` increments, `has_cognitive_condition` is recomputed, and the member's `version` increments by 1; when the disputed item is not `VERIFIED` (for example it is still `PENDING_VERIFICATION` or was `REJECTED`), a `CORRECTED` resolution changes only the dispute itself and performs no supersede. Both resolutions append an `AuditEvent` of action `DISPUTE_RESOLVE` — exactly one such event per resolution, including the superseding case. An `OPEN` dispute may instead be dismissed outright, moving `OPEN` → `DISMISSED` with action `DISPUTE_DISMISS`. The three terminal states are `RESOLVED_UPHELD`, `RESOLVED_CORRECTED`, and `DISMISSED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — and the granted emergency access of §3.6 also returns `201` with the recorded `AccessEvent`; operations that modify an existing resource, run an action, or return data return `200 OK`. The complete request and response semantics of each endpoint live in §2 and §3 — this table is a routing summary only. List endpoints support exact-match filter query parameters as follows: members by `status`, `membership_tier`, `member_type`; guardian links by `status`, `member_id`, `guardian_member_id`; record items by `status`, `item_kind`, `member_id`; verification tickets by `status`, `member_id`, `record_item_id`; contacts, directives, reminders, and wandering cases by `status` and/or `member_id` (reminders also by `reminder_kind`); orders by `status`, `member_id`, `product_id`; responders by `status`, `access_tier`; access events by `outcome`, `responder_id`, `member_id`; disputes by `status`, `member_id`, `record_item_id`; and audit events by `member_id`, `action`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/medical-id/_clock/set_current_utc` | Advance the server's logical clock; triggers the lapse sweep | PlatformAdmin |
| POST | `/medical-id/_reminders/dispatch` | Ops batch: send all due pending reminders | PlatformAdmin |
| POST | `/medical-id/members` | Enroll a member | PlatformAdmin |
| GET | `/medical-id/members` | List members with filters | PlatformAdmin, HotlineOperator |
| GET | `/medical-id/members/{memberId}` | Get one member | Member, Guardian, PlatformAdmin, HotlineOperator |
| POST | `/medical-id/members/{memberId}/renew` | Renew or reactivate a membership | Member, Guardian |
| POST | `/medical-id/members/{memberId}/cancel` | Cancel a membership with full cascade | Member, Guardian, PlatformAdmin |
| POST | `/medical-id/members/{memberId}/guardian-links` | Attach a guardian to a dependent member | PlatformAdmin |
| GET | `/medical-id/members/{memberId}/guardian-links` | List links where this member is the dependent | Member, Guardian, PlatformAdmin |
| GET | `/medical-id/members/{memberId}/guardianships` | List links where this member is the guardian | Member, Guardian, PlatformAdmin |
| GET | `/medical-id/guardian-links` | List guardian links filtered by dependent or guardian | PlatformAdmin |
| GET | `/medical-id/guardian-links/{linkId}` | Get one guardian link | Member, Guardian, PlatformAdmin |
| POST | `/medical-id/guardian-links/{linkId}/revoke` | Revoke a guardian link | PlatformAdmin |
| POST | `/medical-id/members/{memberId}/record-items` | Capture a record item; opens verification round 1 | Member, Guardian |
| GET | `/medical-id/members/{memberId}/record-items` | List the member's record items | Member, Guardian, RecordVerifier, PlatformAdmin |
| POST | `/medical-id/members/{memberId}/record-items/{itemId}/submit-for-verification` | Resubmit a rejected record item | Member, Guardian |
| POST | `/medical-id/members/{memberId}/record-items/{itemId}/supersede` | Supersede a verified record item (OCC) | Member, Guardian |
| GET | `/medical-id/record-items/{itemId}` | Get one record item by id | Member, Guardian, RecordVerifier, PlatformAdmin |
| GET | `/medical-id/record-items` | List record items filtered by member | RecordVerifier, PlatformAdmin |
| GET | `/medical-id/members/{memberId}/record-items/{itemId}` | Get one record item under a member | Member, Guardian, RecordVerifier, PlatformAdmin |
| GET | `/medical-id/members/{memberId}/record-items/{itemId}/tickets` | List verification tickets for one record item | Member, Guardian, RecordVerifier, PlatformAdmin |
| GET | `/medical-id/verification-tickets` | List verification tickets (verifier queue) | RecordVerifier, PlatformAdmin |
| GET | `/medical-id/verification-tickets/{ticketId}` | Get one verification ticket | RecordVerifier, PlatformAdmin |
| POST | `/medical-id/verification-tickets/{ticketId}/resolve` | Approve or reject a verification ticket | RecordVerifier |
| POST | `/medical-id/members/{memberId}/contacts` | Add an emergency contact | Member, Guardian |
| GET | `/medical-id/members/{memberId}/contacts` | List the member's emergency contacts | Member, Guardian, PlatformAdmin |
| GET | `/medical-id/contacts/{contactId}` | Get one emergency contact | Member, Guardian, PlatformAdmin |
| GET | `/medical-id/contacts` | List contacts filtered by member | PlatformAdmin |
| POST | `/medical-id/members/{memberId}/contacts/{contactId}/remove` | Soft-remove an emergency contact | Member, Guardian |
| POST | `/medical-id/members/{memberId}/directives` | Store an advance directive | Member, Guardian |
| GET | `/medical-id/members/{memberId}/directives` | List the member's directives | Member, Guardian, PlatformAdmin |
| GET | `/medical-id/directives/{directiveId}` | Get one directive | Member, Guardian, PlatformAdmin |
| GET | `/medical-id/directives` | List directives filtered by member | PlatformAdmin |
| POST | `/medical-id/members/{memberId}/directives/{directiveId}/revoke` | Revoke a stored or released directive | Member, Guardian |
| POST | `/medical-id/products` | Create a catalog product | PlatformAdmin |
| GET | `/medical-id/products` | List catalog products | Member, Guardian, FulfillmentAgent, PlatformAdmin |
| GET | `/medical-id/products/{productId}` | Get one catalog product | Member, Guardian, FulfillmentAgent, PlatformAdmin |
| POST | `/medical-id/members/{memberId}/orders` | Order an engraved identification product | Member, Guardian |
| GET | `/medical-id/members/{memberId}/orders` | List the member's orders | Member, Guardian, FulfillmentAgent, PlatformAdmin |
| GET | `/medical-id/orders/{orderId}` | Get one product order | Member, Guardian, FulfillmentAgent, PlatformAdmin |
| GET | `/medical-id/orders` | List orders filtered by member or product | FulfillmentAgent, PlatformAdmin |
| POST | `/medical-id/members/{memberId}/orders/{orderId}/confirm` | Confirm an order (OCC; final pricing; sync first) | Member, Guardian |
| POST | `/medical-id/members/{memberId}/orders/{orderId}/engrave` | Mark an order engraved | FulfillmentAgent |
| POST | `/medical-id/members/{memberId}/orders/{orderId}/ship` | Mark an order shipped; settles balance | FulfillmentAgent |
| POST | `/medical-id/members/{memberId}/orders/{orderId}/cancel` | Cancel a pending or confirmed order | Member, Guardian |
| POST | `/medical-id/responders` | Register a responder credential | PlatformAdmin |
| GET | `/medical-id/responders` | List responder credentials | PlatformAdmin, HotlineOperator |
| GET | `/medical-id/responders/{responderId}` | Get one responder credential | PlatformAdmin, HotlineOperator |
| POST | `/medical-id/responders/{responderId}/revoke` | Revoke a responder credential | PlatformAdmin |
| POST | `/medical-id/access-events` | Emergency record access by identifier or hotline | Responder, HotlineOperator |
| GET | `/medical-id/members/{memberId}/access-events` | Audit: list access events for a member | Member, Guardian, PlatformAdmin |
| GET | `/medical-id/access-events/{eventId}` | Get one access event | PlatformAdmin |
| GET | `/medical-id/access-events` | Audit: list access events filtered by responder | PlatformAdmin |
| POST | `/medical-id/members/{memberId}/wandering-cases` | Open a wandering case | Guardian, HotlineOperator |
| GET | `/medical-id/members/{memberId}/wandering-cases` | List wandering cases for a member | Member, Guardian, HotlineOperator, PlatformAdmin |
| GET | `/medical-id/wandering-cases` | List wandering cases filtered by member | PlatformAdmin, HotlineOperator |
| GET | `/medical-id/wandering-cases/{caseId}` | Get one wandering case | Member, Guardian, HotlineOperator, PlatformAdmin |
| POST | `/medical-id/members/{memberId}/wandering-cases/{caseId}/resolve` | Resolve an open wandering case | Guardian, HotlineOperator |
| GET | `/medical-id/reminders` | List reminders filtered by member | PlatformAdmin |
| GET | `/medical-id/reminders/{reminderId}` | Get one reminder | Member, Guardian, PlatformAdmin |
| GET | `/medical-id/members/{memberId}/reminders` | List reminders for a member | Member, Guardian, PlatformAdmin |
| POST | `/medical-id/members/{memberId}/disputes` | Open a record-accuracy dispute | Member, Guardian |
| GET | `/medical-id/members/{memberId}/disputes` | List disputes for a member | Member, Guardian, RecordVerifier, PlatformAdmin |
| GET | `/medical-id/disputes` | List all disputes (verifier queue) | RecordVerifier, PlatformAdmin |
| GET | `/medical-id/disputes/{disputeId}` | Get one dispute | Member, Guardian, RecordVerifier, PlatformAdmin |
| POST | `/medical-id/disputes/{disputeId}/claim-for-review` | Verifier claims a dispute for review | RecordVerifier |
| POST | `/medical-id/disputes/{disputeId}/return-to-queue` | Return a dispute to the open queue | RecordVerifier |
| POST | `/medical-id/disputes/{disputeId}/resolve` | Resolve a dispute; corrected cascades a supersede | RecordVerifier |
| POST | `/medical-id/disputes/{disputeId}/dismiss` | Dismiss an open dispute | RecordVerifier |
| GET | `/medical-id/audit-events` | List audit events filtered by member | PlatformAdmin |
| GET | `/medical-id/audit-events/{eventId}` | Get one audit event | PlatformAdmin |
| GET | `/medical-id/members/{memberId}/audit-events` | Tamper-evident audit log for a member | Member, Guardian, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_RECORD_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTACT_NOT_FOUND` | 404 Not Found |
| `ERR_DIRECTIVE_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_RESPONDER_NOT_FOUND` | 404 Not Found |
| `ERR_GUARDIANSHIP_REQUIRED` | 403 Forbidden |
| `ERR_GUARDIAN_LINK_INVALID` | 409 Conflict |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_RESPONDER_AUTH_FAILED` | 403 Forbidden |
| `ERR_MEMBER_NOT_DISCLOSABLE` | 409 Conflict |
| `ERR_WANDERING_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_CONTACT_PRIORITY_CONFLICT` | 409 Conflict |
| `ERR_ENGRAVING_OVERFLOW` | 422 Unprocessable Entity |
| `ERR_RECORD_ITEM_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDS` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_CREDENTIAL` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
