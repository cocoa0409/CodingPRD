# Hardware Security Key Distribution API — Product Requirements Document

## 1. Introduction

Enterprise phishing-resistant authentication programs fail in two places: procurement buys keys that do not fit the fleet, and recovery workflows quietly reintroduce the phishable paths the program was meant to eliminate. This document specifies a platform that manages the full lifecycle of hardware security keys for enterprise customers — from key-model selection against the organization's device fleet, through bulk purchasing, pre-registration, secure distribution, and enrollment ceremonies that bind keys to identity accounts, all the way to lost-key handling, firmware attestation, and subscription-driven key refresh.

The system serves a vendor operating at Yubico-like scale: organizations declare their identity-provider protocol surface and their assurance posture (including a high-assurance track requiring supply-chain certificates and approved firmware lists), then procure keys in bulk against a catalog of models differentiated by connector, protocol support, form factor, and price. Employees receive keys through a controlled distribution chain; enrollment ceremonies bind a distributed, attested key to the employee's identity account, with backup-key minimums enforced per organization policy. When keys are lost, help-desk workflows must resolve cases without ever falling back to a phishable-only recovery channel: time-based one-time-password temporary access is forbidden outright for organizations under a phishing-resistant policy, and a revoke-and-replace resolution requires that the organization still accepts at least one hardware protocol.

Two test-driving capabilities are part of the contract. An administrative endpoint sets the logical clock — server startup initializes it to exactly 2026-09-01T00:00:00Z and must never fall back to wall-clock time — and a periodic-run endpoint executes one cycle of the enrollment expiry sweep, temporary-access expiry, subscription refresh, and subscription expiry logic. All time-dependent behavior in this document is evaluated against that logical clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the acting user, and `X-User-Role` naming the caller's role. A request missing either header, or carrying a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles are `PlatformAdmin`, `SecurityAdmin`, `ProcurementAdmin`, `LogisticsCoordinator`, `HelpDeskAgent`, and `Employee`.

For `PlatformAdmin`, `SecurityAdmin`, `ProcurementAdmin`, `LogisticsCoordinator`, and `HelpDeskAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by` on a purchase order or as `opened_by_agent_id` on a help-desk case, where it anchors segregation-of-duties checks — but it is never compared to any entity's `id`. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on resources that reference an `Employee` or its identity account compare the resource's foreign-key field to `X-User-ID`. In particular, consuming a temporary access grant requires that the acting employee's identity account is the account the grant was issued to.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; unlike entity timestamps (§2.4) it is stamped from real wall-clock time, never the logical clock.
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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and must be at least 0; a non-numeric value or a value outside these bounds is `ERR_INVALID_REQUEST`. List responses order results by `created_at` ascending, breaking the ties the shared logical clock makes common by `id` ascending (except where a different tie-break is explicitly pinned, as for `uncovered_device_ids` in §3.2 and the replacement selector in §3.9). The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Filter parameters that name an enum field reject a value outside the field's declared set with `ERR_INVALID_REQUEST`; filters on free-form identifiers match exactly.

### 2.4. Common Resource Properties and Mutation Semantics

Every entity in this system carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC format with three fractional digits, an `updated_at` timestamp in the same format refreshed on every mutation, and an integer `version` that increments by one on every state-changing mutation of that resource. Entity timestamps are stamped from the logical clock (§2.7) — never wall-clock time — with the fractional digits always `.000`, so `created_at`, `updated_at`, and `version` all derive from the same per-mutation touch. The initial `version` of a freshly created entity is 1. There are no exceptions in this domain: all entities — organizations, key models, devices, employees, identity accounts, purchase orders, security keys, enrollment ceremonies, temporary access grants, subscriptions, and help-desk cases — carry the full common-field set.

### 2.5. Validation Order and Failure Precedence

Every request is checked against a fixed precedence ladder, and the first failing rung determines the response. Well-formedness comes first: required fields present, enum values valid, no unknown fields, and bulk elements structurally valid — a malformed body is rejected with `ERR_INVALID_REQUEST` before anything else is examined. Next, the presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`), then whether the declared role is permitted for the endpoint (`ERR_UNAUTHORIZED`). Only then does existence checking occur: every path identifier and every foreign-key reference in the body must resolve, validated left-to-right along the path, and every referenced entity must belong to the organization scope carried in the path — a resource that exists but sits outside the caller's organization scope is reported as not found, never as forbidden. Both of those failures surface as `ERR_NOT_FOUND`.

After existence, state checks fire: if the target resource is not in a state from which the requested transition exists, the request is rejected with `ERR_INVALID_STATE`. Then optimistic-concurrency checks: a stale `expected_identity_account_version` or `expected_purchase_order_version` yields `ERR_STALE_VERSION`. Business-safety policy checks come next — phishing-resistance and high-assurance violations surface as `ERR_PHISHABLE_PATH_FORBIDDEN`, and segregation-of-duties violations as `ERR_SEGREGATION_OF_DUTIES`. Business constraints follow: protocol-compatibility failures are `ERR_PROTOCOL_MISMATCH`, uniqueness violations are `ERR_DUPLICATE`, and temporary-access window violations are `ERR_GRANT_WINDOW`. Parent-state gating on order-dependent operations yields `ERR_ORDER_STATE`, subscription fiscal-capacity failures yield `ERR_INSUFFICIENT_CREDITS`, an empty replacement pool yields `ERR_NO_ELIGIBLE_KEY`, and a fleet-fit report against a device-less organization yields `ERR_EMPTY_FLEET`.

### 2.6. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and on both the version field is optional: the request body may carry the field as a non-null integer, in which case the check below applies, or it may omit the field (or send it null), in which case no version check is performed at all — the endpoint proceeds to its ordinary state checks. Approving a purchase order accepts `expected_purchase_order_version`, holding the order's `version` as the client last observed it; if the order's current `version` has advanced — because a prior approval attempt or shipment-state change legitimately moved it forward — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), since the approver's quoted figures are stale. To keep that outcome reachable, purchase-order approval is an exception to the general rung order of §2.5: the stale-version check is evaluated before the order's state check, so an approval attempt quoting a superseded version on an order that has since left `PENDING_APPROVAL` is rejected with `ERR_STALE_VERSION`, not `ERR_INVALID_STATE`. Activating an enrollment ceremony accepts `expected_identity_account_version`, holding the account's `version` as last observed; if another writer has since advanced the account's version — for instance by activating a different ceremony for the same account, legitimately raising `registered_key_count` — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a view of the account it has not observed. On ceremony activation the stale-version check fires only once the ceremony's own state check has passed — the ceremony must still be `PENDING`, per the §2.5 rung order, which has no second exception. No other endpoint accepts a version field.

### 2.7. Logical Clock and Time Semantics

All expiry, window, and period computations evaluate against the server's logical clock, never wall-clock time. The clock starts at exactly 2026-09-01T00:00:00Z at server startup. A `PlatformAdmin` sets it by supplying a `to_iso8601` timestamp to the clock-setting capability; the response reports the new time as `now_iso8601`. Any ISO 8601 timestamp is accepted and normalized to UTC — a missing offset is read as UTC, and any fractional seconds are truncated — and the set is not restricted to forward movement: the value becomes the current logical time verbatim, even if it precedes the previous reading. Datetime comparisons throughout this document are at second precision.

### 2.8. Assurance Posture and Phishing-Resistance Policy

Each organization declares an `assurance_tier` of `STANDARD` or `HIGH_ASSURANCE` and an `authentication_policy` of `STANDARD` or `PHISHING_RESISTANT` at creation. The two axes are independent. `HIGH_ASSURANCE` organizations face supply-chain obligations: shipping an order requires a supply-chain certificate reference in the request, and attesting a key requires that the key's order carries one. `PHISHING_RESISTANT` organizations face recovery restrictions: the `TOTP` temporary-access method is forbidden for them, a revoke-and-replace help-desk resolution is forbidden when the organization's `idp_protocols` contain none of the hardware protocols `FIDO2`, `U2F`, or `PIV`, and their effective backup-key minimum is one higher than the configured `backup_key_minimum`. Any request that would violate these policy walls is rejected with `ERR_PHISHABLE_PATH_FORBIDDEN` (HTTP 422).

### 2.9. Segregation of Duties

Two workflows separate the actor who initiates from the actor who completes. A purchase order records the `X-User-ID` of its creator in `created_by`; the approval must come from a different user — an approver whose `X-User-ID` equals `created_by` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). A help-desk case records its opener in `opened_by_agent_id`; the resolving agent must differ, and the resolver's id is recorded in `resolved_by_agent_id`. Resolution by the opener is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. Nested Resource Addressing and Organization Scoping

Organization-scoped resources are addressed through nested paths, and path identifiers are validated left to right: the organization first, then each nested resource, each of which must exist and belong to the organization named further left. A device, employee, purchase order, security key, or subscription referenced under the wrong organization is `ERR_NOT_FOUND`, even when it exists elsewhere. Identity accounts, enrollment ceremonies, temporary access grants, and help-desk cases are addressed directly by id.

### 2.11. Money, Units, and Rounding

All monetary amounts are integer cents; there is no fractional-cent arithmetic anywhere in the system. Two rounding rules are pinned: per-line quantity discounts are floored per line before summing (sum-then-round is rejected), and subscription credit-unit conversions are ceiled. Percentage outputs — the fleet-fit coverage figure — are integer percents rounded half up. Counts (`registered_key_count`, `line_count`, credit units) are exact integers.

## 3. Business Logic & Workflows

### 3.1. Onboarding an Organization and Building the Key Catalog

A `PlatformAdmin` onboards an enterprise customer by creating an organization with its `legal_name`, its `assurance_tier` (`STANDARD` or `HIGH_ASSURANCE`), its `authentication_policy` (`STANDARD` or `PHISHING_RESISTANT`), and the `idp_protocols` its identity provider accepts. The protocol list must be a non-empty array whose elements are drawn from `FIDO2`, `U2F`, `OATH_HOTP`, and `PIV`; it is the reference surface against which every key model's protocol support is later checked at assign time and at enrollment creation. Two optional inputs complete the organization's posture: `approved_firmware_versions`, a list of firmware version strings approved for attestation which defaults to an empty list, and `backup_key_minimum`, the minimum number of registered keys each identity account must hold, which defaults to 2 and must be at least 1. A new organization starts with `status` set to `ACTIVE` (the only other lifecycle value is `SUSPENDED`).

The semantics of an empty `approved_firmware_versions` list diverge sharply by tier, and this divergence is deliberate. A `STANDARD` organization with an empty approved list accepts any firmware at attestation — the empty list means "no allow-list configured". A `HIGH_ASSURANCE` organization with an empty approved list fails every attestation it attempts — the empty list means "nothing approved yet". Operators of high-assurance programs must therefore populate the list before any key can reach `VERIFIED`.

In parallel, a `PlatformAdmin` builds the catalog of key models. Each model carries a `model_code` (a vendor code such as YK5C-NFC, unique across the entire catalog — a duplicate is `ERR_DUPLICATE`), the `connectors` it offers (a non-empty array drawn from `USB_A`, `USB_C`, `LIGHTNING`, `NFC`, and `BLE`), the `protocols` it supports (a non-empty array drawn from the same four-protocol set as `idp_protocols`), a `form_factor` of `KEYCHAIN`, `NANO`, `CARD`, or `BIOMETRIC`, and a `unit_price_cents` list price that must be greater than zero.

### 3.2. Fleet Registration and Fit Assessment

Before purchasing, a `SecurityAdmin` registers the organization's device fleet. Each device record carries an `asset_tag` unique within the organization, a `platform` of `WINDOWS`, `MACOS`, `LINUX`, `CHROMEOS`, `ANDROID`, or `IOS`, the physical `connectors` the device exposes, and the `protocol_capability` of its OS and browser stack. A device's `lifecycle_status` is `ACTIVE` by default — the create request may set it directly to `RETIRED` — and may be set to `RETIRED`; only `ACTIVE` devices participate in fit computations and in the connector pool used by replacement selection. Devices are listed with optional `lifecycle_status` and `platform` filters, alongside `limit` and `offset`.

The fleet-fit report answers the purchasing question "how much of the fleet can this model serve?" Given a `model_code` — a missing `model_code` parameter is `ERR_INVALID_REQUEST` — the report considers every `ACTIVE` device of the organization — if there are none, the request is rejected with `ERR_EMPTY_FLEET`. A device is fit when both conditions hold: the device's `connectors` share at least one element with the model's `connectors`, and the device's `protocol_capability` shares at least one element with the model's `protocols`. The report returns `coverage_pct` — the count of fit devices divided by the total count of devices, expressed as an integer percent rounded half up — together with `total_devices` and `uncovered_device_ids`, the ids of the non-fit devices ordered by `created_at` ascending with ties broken by `asset_tag` ascending. A `model_code` that matches no catalog entry is `ERR_NOT_FOUND`, and that check fires before the empty-fleet check, so an unknown model reported against a device-less organization is `ERR_NOT_FOUND`. Both `SecurityAdmin` and `ProcurementAdmin` may request this report.

### 3.3. Employees and Their Identity Accounts

A `SecurityAdmin` registers each employee with an `employee_ref` — the organization-scoped HR identifier, unique within the organization — a `location` label used for distribution routing, and a `directory_user_id`, the immutable user key in the organization's identity-provider directory, also unique within the organization. Both uniqueness checks reject with `ERR_DUPLICATE`. Creating an employee atomically creates exactly one identity account bound to that employee; the account's id is returned on the employee record as `identity_account_id`. The account copies `directory_user_id` and `employee_ref` from the employee at creation and never changes them, and it inherits the employee's `organization_id`. The account begins `UNENROLLED`, with `registered_key_count` at 0 and `backup_compliant` false. The employee record itself begins with `employment_status` set to `ACTIVE` (its only other value is the terminal `TERMINATED`).

`registered_key_count` is a derived counter, recomputed on every enrollment activation, renewal-related transition, expiry, revocation, or supersede that touches the account: it counts the account's ceremonies whose status is `ACTIVE` or `EXPIRING`. Ceremonies in `PENDING`, `REVOKED`, or `SUPERSEDED` never count — an `EXPIRING` ceremony still counts because the key still works during the grace window. `backup_compliant` compares that count against the effective backup minimum: the organization's configured `backup_key_minimum` when its `authentication_policy` is `STANDARD`, or that value plus one when the policy is `PHISHING_RESISTANT`. The account is compliant when its count is at least the effective minimum. Whenever a recomputation finds an `ENROLLED` account whose count has fallen to zero, the account transitions to `LOCKED`.

Terminating an employee — a `SecurityAdmin` action on an `ACTIVE` employee, moving `employment_status` to the terminal `TERMINATED` — triggers the widest cascade in the system. Every security key assigned to the employee's account with `hardware_status` in `ASSIGNED` or `DISTRIBUTED` is revoked, carrying the enrollment-and-account cascade described in §3.6. Every enrollment ceremony of the account in `PENDING`, `ACTIVE`, or `EXPIRING` is revoked. Every `ACTIVE` temporary access grant of the account is voided. Finally the identity account itself is `LOCKED`. The employee's `version` increments once for the termination.

An account can also be locked directly. A `SecurityAdmin` may lock an `ENROLLED` account — and, as an administrative pre-enrollment lockout, an `UNENROLLED` account — moving it to `LOCKED`; locking voids every `ACTIVE` temporary access grant on the account. The system path into `LOCKED` is the zero-count cascade above. A `LOCKED` account returns to `ENROLLED` through enrollment activation, which is the sanctioned re-enrollment route described in §3.7. Fetching an account returns the computed `registered_key_count` and `backup_compliant` alongside its `employee_id`, `organization_id`, `directory_user_id`, `employee_ref`, and `status`.

### 3.4. Procurement and the Two-Variant Order Total

A `ProcurementAdmin` raises a purchase order by supplying `lines` and a `shipping_location`. Each line names a `model_code` referencing an existing catalog model and a `quantity` of at least one; the `lines` array must be non-empty, and no `model_code` may appear twice within one order — a duplicate line model is `ERR_DUPLICATE`. The order is created in `PENDING_APPROVAL`, its `created_by` is set from the caller's `X-User-ID`, and two derived figures are frozen at creation: `line_count`, the total unit count across all lines, and `quoted_total_cents`, computed by the provisional variant of the order-total calculation.

The provisional variant is deliberately simple: for each line in array order, the line base is the referenced model's `unit_price_cents` multiplied by the line's quantity, and `quoted_total_cents` is the exact integer-cent sum of the line bases. No coverage, no discount; `final_total_cents` stays null and `credit_applied_cents` and `quantity_discount_cents` stay zero until approval.

Approval is a `SecurityAdmin` action on a `PENDING_APPROVAL` order, guarded by optimistic concurrency on `expected_purchase_order_version` (§2.6) and by segregation of duties against `created_by` (§2.9). Within the endpoint the checks fire in a pinned order: the stale-version check first (per the §2.6 exception), then the `PENDING_APPROVAL` state check, then segregation of duties, and only then fiscal capacity. When the organization has an `ACTIVE` subscription, approval also requires that the credit cost of the order — the credit-applied amount converted to credit units by dividing by 100 cents per credit unit and rounding up — does not exceed the subscription's `credits_remaining`; a shortfall is `ERR_INSUFFICIENT_CREDITS`. On success the order moves to `APPROVED` and the final variant of the total is computed, in a pinned evaluation order of base, then coverage, then per-line discount, then sum.

The final variant works as follows. First the base: the same per-line `unit_price_cents`-times-quantity products summed over all lines in array order. Then coverage: if the organization has no `ACTIVE` subscription, `credit_applied_cents` is zero; otherwise it is the smaller of the base and the subscription's `coverage_cents_remaining`. Coverage is allocated to lines sequentially in array order — each line absorbs the smaller of its own line base and the remaining pool — so each line's remainder is its base minus the coverage it absorbed, and the overall remainder is the base minus `credit_applied_cents`. Then the discount: a volume tier percentage is selected from the order's `line_count`, where at least 100 units earns 10 percent, at least 50 units (but fewer than 100) earns 5 percent, and fewer than 50 earns nothing, with the tier boundaries inclusive of the higher tier — at exactly 100 units the 10 percent tier applies and at exactly 50 units the 5 percent tier applies; the effective percentage is the larger of that tier percentage and the subscription's `percent_discount` (zero when there is no subscription). `quantity_discount_cents` is the sum over lines of each line's remainder multiplied by the effective percentage, divided by 100, and floored per line — flooring happens per line before summation, never after. `final_total_cents` is the overall remainder minus `quantity_discount_cents`. The discount is always computed on the post-coverage remainder and never feeds back into the coverage amount; this ordering is what breaks the otherwise circular dependency between a discount keyed on order size and a total keyed on discounts.

Approval settles accounts with the subscription when coverage was consumed. The credit cost of the order — the credit-applied cents divided by 100 and rounded up — is added to the subscription's `credits_used` and subtracted from its `credits_remaining`, while `credit_applied_cents` itself is added to `coverage_cents_used` and subtracted from `coverage_cents_remaining`. If the draw leaves `credits_remaining` at exactly zero, the subscription transitions from `ACTIVE` to `EXHAUSTED`. The order's `version` increments once for the approval. This is a depth-3 cascade: approve, order fields recompute, subscription counters move, and the subscription may exhaust.

Purchase orders are listed for an organization with optional `status` filtering by `SecurityAdmin`, `ProcurementAdmin`, and `LogisticsCoordinator` callers.

### 3.5. Shipment, Receipt, and Quarantine

Once approved, physical movement is a `LogisticsCoordinator` workflow. Shipping an `APPROVED` order moves it to `IN_TRANSIT`; the state check fires before the certificate requirement, so shipping an order that is not `APPROVED` is `ERR_INVALID_STATE` even when no certificate is supplied. For a `STANDARD` organization the request may omit `supply_chain_cert_id`, and the order's field is set to the request value — null for standard shipments. For a `HIGH_ASSURANCE` organization the request must carry `supply_chain_cert_id`; shipping without one is rejected with `ERR_PHISHABLE_PATH_FORBIDDEN`. Receiving an `IN_TRANSIT` order moves it to `RECEIVED`, at which point the order's keys become eligible for assignment.

Quarantine is the containment instrument for compromised stock. A `SecurityAdmin` may quarantine any `RECEIVED` order, and a high-assurance attestation failure can quarantine one automatically (§3.6); both paths move the order to `QUARANTINED` and fire the same depth-4 cascade. Every key of the order with `hardware_status` in `PRE_REGISTERED`, `ASSIGNED`, or `DISTRIBUTED` is revoked. For every revoked key whose enrollment ceremony is in `PENDING`, `ACTIVE`, or `EXPIRING`, the ceremony is revoked and its `revoked_at` set. For each affected account, `registered_key_count` is recomputed (only `ACTIVE` and `EXPIRING` ceremonies count), `backup_compliant` is recomputed, and the account is locked if and only if it was `ENROLLED` and the count is now zero.

Release moves a `QUARANTINED` order back to `RECEIVED` — a `SecurityAdmin` action that, for a `HIGH_ASSURANCE` organization, requires the order's `supply_chain_cert_id` to be set. Release never un-revokes hardware: keys revoked by any earlier quarantine stay `REVOKED` permanently, even as the order itself cycles between `RECEIVED` and `QUARANTINED` repeatedly. The purchase order has no terminal state; this cyclic containment dimension is intentional.

### 3.6. Security Keys: Pre-Registration, Distribution, Revocation, and Attestation

A security key carries two independent state dimensions. `hardware_status` tracks distribution — `PRE_REGISTERED`, `ASSIGNED`, `DISTRIBUTED`, or the terminal `REVOKED` — while `attestation_status` tracks firmware verification — `UNVERIFIED`, `VERIFIED`, or `FAILED`, where `FAILED` is terminal for that dimension. A key begins `PRE_REGISTERED` and `UNVERIFIED`.

Physical keys enter the system through bulk pre-registration: a `LogisticsCoordinator` posts a batch of `keys` against an `APPROVED` order — pre-registration against an order in any other state is `ERR_ORDER_STATE`. Each element carries its `serial_number` — globally unique across all keys, whether the duplicate sits inside the same batch or anywhere in the system, duplicates rejected with `ERR_DUPLICATE` — and its `firmware_version` string. Each key's `model_code` must appear among the parent order's lines. The per-key `model_code` may be omitted when the order has exactly one line model, in which case that model applies; a top-level `model_code` on the request applies to every key in the batch and overrides any per-key value. A mismatch between a key's model and the order's lines is `ERR_ORDER_STATE`. Keys are created `PRE_REGISTERED` and `UNVERIFIED`, each stamped with its `purchase_order_id`.

From there the distribution chain is deliberately narrow. Assigning a key — a `SecurityAdmin` action moving `hardware_status` from `PRE_REGISTERED` to `ASSIGNED` and recording the target in `assigned_identity_account_id` — requires that the key itself is still `PRE_REGISTERED` (checked first, as the transition's state gate), that the key's order is `RECEIVED` (otherwise `ERR_ORDER_STATE`), that the target account belongs to the same organization, that the account's employee is still `ACTIVE`, and that the intersection of the key model's protocols with the organization's `idp_protocols` is non-empty (otherwise `ERR_PROTOCOL_MISMATCH`). Marking a key distributed — a `LogisticsCoordinator` action moving `ASSIGNED` to `DISTRIBUTED` — likewise requires the parent order to be `RECEIVED`, and the account assignment does not change hands: `assigned_identity_account_id` is carried over unchanged. Returning a key to stock reverses an assignment, moving `ASSIGNED` back to `PRE_REGISTERED` and clearing `assigned_identity_account_id` to null; it is only possible while no ceremony binds the key in `PENDING`, `ACTIVE`, or `EXPIRING` — otherwise the transition does not exist and the request is `ERR_INVALID_STATE`. The `assigned_identity_account_id` field is null unless the key is `ASSIGNED` or `DISTRIBUTED`.

Revocation is the terminal hardware move. A `SecurityAdmin` may revoke any key in `PRE_REGISTERED`, `ASSIGNED`, or `DISTRIBUTED`; the same transition fires from the quarantine cascade (§3.5), from employee termination (§3.3), and — for `DISTRIBUTED` keys — from the help-desk lost-key resolution (§3.9). Revoking sets `hardware_status` to `REVOKED`; if a ceremony binds the key in `PENDING`, `ACTIVE`, or `EXPIRING`, that ceremony is revoked with `revoked_at` set, and if the ceremony had been `ACTIVE` or `EXPIRING` the account's `registered_key_count` and `backup_compliant` are recomputed, locking the account exactly when it was `ENROLLED` and the count reached zero. Keys are listed with filters on `purchase_order_id`, `hardware_status`, `attestation_status`, `assigned_identity_account_id`, and `model_code`.

Attestation runs on the independent second dimension. A `SecurityAdmin` attests a key that is `UNVERIFIED` and not `REVOKED`. Two gates apply: for a `HIGH_ASSURANCE` organization the key's order must carry a `supply_chain_cert_id` — attesting without one is `ERR_PHISHABLE_PATH_FORBIDDEN` — and the key's `firmware_version` must be approved, meaning either it appears in the organization's `approved_firmware_versions`, or the organization is `STANDARD` and its approved list is empty. When both gates pass, `attestation_status` becomes `VERIFIED`. When the firmware gate fails, the attestation still succeeds as a recorded act but the outcome is `FAILED`; if the organization is `HIGH_ASSURANCE` and the key's order is `RECEIVED`, the order is immediately quarantined with the full receipt-to-quarantine cascade of §3.5. `FAILED` is terminal — a failed key cannot be re-attested.

### 3.7. Enrollment Ceremonies: Binding, Activation, Renewal, Expiry

An enrollment ceremony binds a security key to an identity account. A `SecurityAdmin` creates one by naming the `security_key_id`; the ceremony starts `PENDING`. Creation enforces protocol compatibility — the key model's protocols must intersect the organization's `idp_protocols`, otherwise `ERR_PROTOCOL_MISMATCH`. Ceremonies are listed for an account with optional `status` and `security_key_id` filters.

Activation is where binding becomes real, and it is heavily preconditioned. The ceremony must be `PENDING`; the key's `hardware_status` must be `DISTRIBUTED` and its `attestation_status` must be `VERIFIED`; the key's `assigned_identity_account_id` must equal the ceremony's account; the account must be `UNENROLLED`, `ENROLLED`, or `LOCKED` — the `LOCKED` path being the sanctioned re-enrollment route back into service; the employee must be `ACTIVE`; and no other ceremony may bind the same key in `ACTIVE` or `EXPIRING`. The request must also carry `expected_identity_account_version` per §2.6. On success the ceremony becomes `ACTIVE`, its `activated_at` is set to the current logical time, its `expires_at` is set to exactly 365 days later, and its `renewal_count` is reset to 0. The account's `registered_key_count` rises by one and `backup_compliant` is recomputed. The account's status moves from `UNENROLLED` to `ENROLLED`, from `LOCKED` back to `ENROLLED`, or stays `ENROLLED`.

Validity runs 365 days from activation. The periodic expiry sweep watches two thresholds. When the current time reaches 30 days before a ceremony's `expires_at` — that is, when now is at or past the point 30 days before expiry while still within validity — an `ACTIVE` ceremony becomes `EXPIRING`, and entering `EXPIRING` sets `renewal_count` to 0, arming exactly one renewal for this validity period. When the current time passes `expires_at`, a ceremony in `ACTIVE` or `EXPIRING` is revoked by the sweep with `revoked_at` set, the account's count falls by one, `backup_compliant` is recomputed, and the account locks if it was `ENROLLED` and the count hit zero. The boundary is strict: at the exact instant equal to `expires_at` the enrollment is still valid — lapse requires now to be strictly later than `expires_at` — and a ceremony already in `EXPIRING` whose `expires_at` is exactly now is left untouched by the sweep, neither re-marked nor revoked.

Renewal lets a `SecurityAdmin` pull an `EXPIRING` ceremony back to `ACTIVE`, provided the single per-period renewal has not been consumed — `renewal_count` must still be 0 — and the key remains `DISTRIBUTED` and `VERIFIED`. Renewal recomputes `expires_at` to 365 days from the renewal moment, sets `renewal_count` to 1, consuming the period's renewal, and recomputes the account's `registered_key_count` and `backup_compliant` — the ceremony counted toward the account in `EXPIRING` and still counts in `ACTIVE`, so the figures are unchanged by the renewal, and the account's own status is untouched (a `LOCKED` account stays `LOCKED` until an activation re-enrolls it); a second renewal attempt before the next sweep-driven transition is rejected with `ERR_INVALID_STATE`.

Revocation of a ceremony — by a `SecurityAdmin` or `HelpDeskAgent`, or through the key-revocation, quarantine, termination, help-desk-resolution, or expiry-sweep cascades — applies to ceremonies in `PENDING`, `ACTIVE`, or `EXPIRING` and moves them to the terminal `REVOKED` with `revoked_at` set. Revoking a `PENDING` ceremony never touches account counters; revoking an `ACTIVE` or `EXPIRING` one drops `registered_key_count` by one, recomputes `backup_compliant`, and locks the account if it was `ENROLLED` and left with zero keys.

The final terminal state, `SUPERSEDED`, belongs to the subscription refresh run (§3.8).

### 3.8. Subscription Programs, Coverage Pools, and Refresh Runs

A `ProcurementAdmin` creates the organization's subscription program with a `tier` of `BASIC` or `ENTERPRISE`, a `refresh_interval_days` greater than zero governing the cadence of periodic key-refresh runs, a `replacement_credits_total` greater than zero minting the term's replacement-credit pool, and optionally a `coverage_cents_total` (default 0, never negative) fiscal coverage pool and a `percent_discount` between 0 and 100 inclusive (default 0) applied on post-coverage remainders at order approval. At most one subscription per organization may be `ACTIVE` at a time — creating a second is `ERR_DUPLICATE`. At creation `current_period_start` is set to the current logical time and `current_period_end` to that time plus `refresh_interval_days`; the subscription starts `ACTIVE` with `credits_used` and `coverage_cents_used` at zero.

Two invariants hold on every mutation: `credits_used` plus `credits_remaining` always equals `replacement_credits_total`, and `coverage_cents_used` plus `coverage_cents_remaining` always equals `coverage_cents_total`. Credits are consumed by purchase-order coverage at approval (§3.4, converting consumed cents to credit units at 100 cents per unit rounded up) and by refresh runs at a flat cost of one credit per refreshed account. Coverage cents are consumed only by order approvals.

When a periodic run finds an `ACTIVE` subscription whose `current_period_end` has been reached — the boundary is inclusive, now at or past the period end — the refresh step processes the organization's eligible accounts — those holding at least one ceremony in `ACTIVE` or `EXPIRING` — in chronological order: oldest ceremony `expires_at` first, ties broken by the account's `created_at` ascending. For each account in that order: if the subscription's `credits_remaining` is below the per-account refresh cost of one credit, the run stops immediately as a partial run with the remainder deferred. Otherwise the replacement selector (§3.9) nominates a key; if the pool is empty for that account, the account is skipped and the run continues. A successful refresh creates a ceremony binding the nominated key to the account and activates it within the run — subscription keys are drop-shipped, so the key moves atomically from `PRE_REGISTERED` through `ASSIGNED` to `DISTRIBUTED` in one step, stamped with the account in `assigned_identity_account_id`, without the manual activation path's distribution preconditions; the new ceremony is created directly in `ACTIVE` with `activated_at` at the run's logical time, `expires_at` 365 days later, and `renewal_count` 0. Every one of the account's other ceremonies in `ACTIVE` or `EXPIRING` — not just the oldest — becomes `SUPERSEDED` and each old key is revoked; because the replacement activation offsets the supersedes in the same run, the account's `registered_key_count` reflects exactly the exchange: one new counting ceremony replacing every superseded one. The subscription's `credits_used` rises by one and `credits_remaining` falls by one; if that empties the pool, the subscription becomes `EXHAUSTED` — which, because the account was still refreshed, counts as a refreshed account for the roll-forward decision below.

If no account could be refreshed at all — every account hit an empty pool, or the run started with zero credits — the subscription becomes `EXPIRED` instead. Otherwise the period rolls forward: `current_period_start` takes the old `current_period_end`, and `current_period_end` advances by `refresh_interval_days`. Independently of refresh outcome, a periodic run in which the current time has reached `current_period_end` may expire the subscription directly when the caller passes `expire` set to true; expiry applies to subscriptions in `ACTIVE` or `EXHAUSTED` and takes precedence over every other outcome of the run for that subscription — an `expire` run never rolls the period forward and never reports the subscription as expiring on the no-refresh path. `EXPIRED` is the only terminal state — `EXHAUSTED` is reachable but not terminal, since expiry sweeps still apply to it: an `EXHAUSTED` subscription past its period end performs no refresh work and no period roll — it stays `EXHAUSTED` with its period dates unchanged unless the run expires it directly. Subscriptions are listed for an organization with optional `status` filtering.

The periodic run endpoint executes, in one cycle, the enrollment expiry sweep (§3.7), temporary-access expiry (§3.9), the refresh run above, and the subscription expiry path, optionally scoped by `organization_id`. It reports counts for `enrollments_expiring`, `enrollments_expired`, `grants_expired`, `refreshed_accounts`, `subscriptions_exhausted`, and `subscriptions_expired`.

### 3.9. Help Desk: Temporary Access, Cases, and Phishing-Resistant Recovery

Temporary access bridges the gap between losing a key and completing re-enrollment. A `HelpDeskAgent` issues a grant to an identity account by naming a `method` — `TOTP`, `SMART_CARD`, or `SERVICE_DESK_TOKEN` — and a `duration_hours` between 1 and 72 inclusive; a duration outside that window is `ERR_GRANT_WINDOW`. Under a `PHISHING_RESISTANT` policy the `TOTP` method is forbidden — requesting it is `ERR_PHISHABLE_PATH_FORBIDDEN`, because the whole point of the policy is that help-desk flows never reintroduce phishable recovery. At most one grant per account may be `ACTIVE` at any moment; issuing a second while one is live is `ERR_GRANT_WINDOW`. The grant is created `ACTIVE`, its `starts_at` set to the creation instant on the logical clock, and its `expires_at` computed as `starts_at` plus `duration_hours` hours. The boundary is exclusive: the grant is usable while the current time is strictly before `expires_at`.

Only the owning employee consumes a grant: the acting employee's identity account must be the account the grant was issued to — a use attempted by any other employee is rejected with `ERR_UNAUTHORIZED` — and use requires the grant to be `ACTIVE` and unexpired — a use at or after expiry is `ERR_GRANT_WINDOW`. Successful use moves the grant to `USED`. A `SecurityAdmin` or `HelpDeskAgent` may void an `ACTIVE` grant, and account locks and employee terminations void all `ACTIVE` grants of the account as cascades. When the current time reaches `expires_at`, the grant becomes `EXPIRED` — the boundary is inclusive for expiry (now at or past `expires_at`, so the exclusive usability boundary above and the inclusive expiry boundary meet exactly at `expires_at`), this derivation applies at read time whenever a stored-`ACTIVE` grant is read past its expiry, and the periodic sweep persists the transition, bumping the grant's `version` on the sweep path only. Read-side surfaces reflect the derivation: the list endpoint's `status` filter compares against the derived status, so a stored-`ACTIVE` grant past expiry is returned — and filterable — as `EXPIRED`, and the one-live-grant rule above also applies it, so an expired-but-unswept grant does not block a new issuance. `USED`, `VOIDED`, and `EXPIRED` are all terminal. Grants are listed per account with an optional `status` filter.

Help-desk cases formalize recovery. A `HelpDeskAgent` opens a case against an identity account with a `category` of `LOST_KEY`, `LOCKOUT`, or `OTHER` and a free-text `description`; the opener's `X-User-ID` is recorded in `opened_by_agent_id`, and the case starts `OPEN` with `resolution` null. Cases are listed with optional `identity_account_id`, `status`, and `category` filters.

An `OPEN` case in the `LOST_KEY` or `LOCKOUT` category may be submitted for review, moving to `PENDING_REVIEW`; an `OTHER` case has no review path, and the state check fires before the category check, so submitting a case that is not `OPEN` is `ERR_INVALID_STATE` regardless of category. Resolution then separates duties: the resolving agent's `X-User-ID` must differ from `opened_by_agent_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), and the resolver is recorded in `resolved_by_agent_id`. The case-state check fires before the segregation check, so resolving a case already in a terminal state is `ERR_INVALID_STATE` even for a resolver who is the opener. A `PENDING_REVIEW` case resolves with any resolution code; an `OPEN` case may be resolved directly only with `REJECTED` — a direct `OPEN`-to-`RESOLVED` transition does not exist and is `ERR_INVALID_STATE`. A `REJECTED` resolution sets the case to `REJECTED` and records `resolution` accordingly; `RESOLVED` and `REJECTED` are terminal.

A `REVOKED_AND_REPLACED` resolution carries the lost-key cascade. It requires, first, that the organization's `idp_protocols` contain at least one of the hardware protocols `FIDO2`, `U2F`, or `PIV` — otherwise recovery would fall back to phishable-only channels and the resolution is `ERR_PHISHABLE_PATH_FORBIDDEN` — and, second, that the replacement selector finds an eligible key, otherwise `ERR_NO_ELIGIBLE_KEY`. On success, every ceremony of the account in `ACTIVE` or `EXPIRING` is revoked and its key revoked — ceremonies in `PENDING` are left untouched, keeping the cascade narrower than a key revocation's; the replacement key is auto-selected, auto-assigned to the account, and bound by a new ceremony created in `PENDING`; and the account's counters are recomputed, locking the account if the count is zero. The selector is deterministic. Eligible keys are those still `PRE_REGISTERED`, belonging to a `RECEIVED` order of the same organization, whose model's protocols intersect the organization's `idp_protocols`, and whose model's connectors intersect the union of connectors across the organization's `ACTIVE` devices. Among eligible keys the cheapest wins — lowest `unit_price_cents` first — with ties broken by the key's `created_at` ascending, and any remaining ties broken by pre-registration order (the order in which the keys were created, earliest first), keeping the selector deterministic even when `created_at` values coincide. The same selector serves the subscription refresh run, where an empty pool skips the account rather than raising an error.

A `TEMP_ACCESS_ISSUED` resolution creates a grant for the account in one step, subject to the same rules as direct issuance: the `method` must be permitted by the organization's `authentication_policy` (so `TOTP` is forbidden under `PHISHING_RESISTANT`), no other `ACTIVE` grant may exist for the account, and `duration_hours` must lie between 1 and 72 inclusive — violations surface as `ERR_PHISHABLE_PATH_FORBIDDEN` or `ERR_GRANT_WINDOW` as applicable. For this resolution `method` and `duration_hours` are required fields of the resolve request, and a missing one is `ERR_INVALID_REQUEST`. On success the case becomes `RESOLVED`, the grant is created `ACTIVE` with the requested method and duration, and `resolved_by_agent_id` is recorded.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix. Resource-creating operations respond with 201; state-changing actions and reads respond with 200. Request and response bodies follow the envelope in §2.2; validation and failure precedence follow §2.5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/_clock/set_current_utc | Set the logical clock (startup default exactly 2026-09-01T00:00:00Z; never wall-clock) | PlatformAdmin |
| POST | /v1/_ops/run_periodic | Run one periodic cycle: enrollment expiry sweep, temporary-access expiry, refresh runs, subscription expiry | PlatformAdmin |
| POST | /v1/organizations | Create an organization with its IdP protocol configuration | PlatformAdmin |
| POST | /v1/key-models | Create a key model in the catalog | PlatformAdmin |
| POST | /v1/organizations/{id}/devices | Register a fleet device | SecurityAdmin |
| GET | /v1/organizations/{id}/devices | List an organization's devices with pagination and filters | SecurityAdmin, ProcurementAdmin |
| GET | /v1/organizations/{id}/fleet-fit | Computed fleet-coverage report for a model against ACTIVE devices | SecurityAdmin, ProcurementAdmin |
| POST | /v1/organizations/{id}/employees | Create an employee; atomically creates the employee's identity account (UNENROLLED) | SecurityAdmin |
| POST | /v1/organizations/{id}/employees/{eid}/terminate | Terminate an employee; cascades key revocation, grant voiding, enrollment revocation, account lock | SecurityAdmin |
| GET | /v1/identity-accounts/{id} | Fetch one identity account including computed registered_key_count and backup_compliant | SecurityAdmin, HelpDeskAgent |
| POST | /v1/identity-accounts/{id}/lock | Administratively lock an account; voids ACTIVE temporary-access grants | SecurityAdmin |
| POST | /v1/organizations/{id}/purchase-orders | Create a purchase order in PENDING_APPROVAL; freezes quoted_total_cents (provisional variant) | ProcurementAdmin |
| GET | /v1/organizations/{id}/purchase-orders | List an organization's purchase orders | SecurityAdmin, ProcurementAdmin, LogisticsCoordinator |
| POST | /v1/organizations/{id}/purchase-orders/{po_id}/approve | Approve a PENDING_APPROVAL order (OCC); applies final pricing and consumes subscription pools | SecurityAdmin |
| POST | /v1/organizations/{id}/purchase-orders/{po_id}/ship | Ship an APPROVED order; HIGH_ASSURANCE orgs must supply a supply-chain certificate | LogisticsCoordinator |
| POST | /v1/organizations/{id}/purchase-orders/{po_id}/receive | Receive an IN_TRANSIT order; keys become assignable | LogisticsCoordinator |
| POST | /v1/organizations/{id}/purchase-orders/{po_id}/quarantine | Quarantine a RECEIVED order; revokes every key with enrollment/account cascade | SecurityAdmin |
| POST | /v1/organizations/{id}/purchase-orders/{po_id}/release | Release a QUARANTINED order back to RECEIVED; keys stay revoked | SecurityAdmin |
| POST | /v1/organizations/{id}/purchase-orders/{po_id}/keys | Bulk pre-register keys into an APPROVED order | LogisticsCoordinator |
| GET | /v1/organizations/{id}/security-keys | List keys with filters | SecurityAdmin, LogisticsCoordinator, HelpDeskAgent |
| POST | /v1/organizations/{id}/security-keys/{kid}/assign | Assign a PRE_REGISTERED key of a RECEIVED order to an identity account | SecurityAdmin |
| POST | /v1/organizations/{id}/security-keys/{kid}/mark-distributed | Mark an ASSIGNED key as physically distributed | LogisticsCoordinator |
| POST | /v1/organizations/{id}/security-keys/{kid}/return-to-stock | Return an ASSIGNED, never-enrolled key to stock | SecurityAdmin |
| POST | /v1/organizations/{id}/security-keys/{kid}/revoke | Administratively revoke a key; cascades enrollment revocation and account recompute | SecurityAdmin |
| POST | /v1/organizations/{id}/security-keys/{kid}/attest | Run firmware attestation; HIGH_ASSURANCE failure auto-quarantines a RECEIVED order | SecurityAdmin |
| POST | /v1/identity-accounts/{id}/enrollments | Create an enrollment ceremony (PENDING) binding a key to the account | SecurityAdmin |
| GET | /v1/identity-accounts/{id}/enrollments | List an account's enrollment ceremonies | SecurityAdmin, HelpDeskAgent |
| POST | /v1/identity-accounts/{id}/enrollments/{eid}/activate | Activate a PENDING ceremony (OCC); the re-enrollment route for LOCKED accounts | SecurityAdmin |
| POST | /v1/identity-accounts/{id}/enrollments/{eid}/renew | Renew an EXPIRING ceremony; at most one renewal per EXPIRING entry | SecurityAdmin |
| POST | /v1/identity-accounts/{id}/enrollments/{eid}/revoke | Revoke a ceremony; recomputes registered_key_count and may lock the account | SecurityAdmin, HelpDeskAgent |
| POST | /v1/identity-accounts/{id}/temporary-access | Issue a temporary access grant; TOTP forbidden under PHISHING_RESISTANT; one ACTIVE grant per account | HelpDeskAgent |
| GET | /v1/identity-accounts/{id}/temporary-access | List an account's grants (read-time EXPIRED derivation applies) | SecurityAdmin, HelpDeskAgent |
| POST | /v1/identity-accounts/{id}/temporary-access/{tid}/use | Consume an ACTIVE grant before expiry; only the owning employee | Employee |
| POST | /v1/identity-accounts/{id}/temporary-access/{tid}/void | Void an ACTIVE grant | SecurityAdmin, HelpDeskAgent |
| POST | /v1/organizations/{id}/subscriptions | Create the organization's subscription program (at most one ACTIVE per org) | ProcurementAdmin |
| GET | /v1/organizations/{id}/subscriptions | List an organization's subscriptions | SecurityAdmin, ProcurementAdmin |
| POST | /v1/help-desk-cases | Open a help-desk case for an identity account; opener recorded for segregation of duties | HelpDeskAgent |
| GET | /v1/help-desk-cases | List help-desk cases with filters | HelpDeskAgent, SecurityAdmin |
| POST | /v1/help-desk-cases/{id}/submit-review | Move an OPEN LOST_KEY or LOCKOUT case to PENDING_REVIEW | HelpDeskAgent |
| POST | /v1/help-desk-cases/{id}/resolve | Resolve an OPEN (REJECTED only) or PENDING_REVIEW case; resolver must differ from opener | HelpDeskAgent |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE | 409 |
| ERR_PHISHABLE_PATH_FORBIDDEN | 422 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_PROTOCOL_MISMATCH | 422 |
| ERR_GRANT_WINDOW | 422 |
| ERR_ORDER_STATE | 409 |
| ERR_INSUFFICIENT_CREDITS | 422 |
| ERR_NO_ELIGIBLE_KEY | 422 |
| ERR_EMPTY_FLEET | 422 |
