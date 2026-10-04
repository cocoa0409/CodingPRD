# Biometric Identity Lanes API — Product Requirements Document

## 1. Introduction

This document specifies a biometric identity verification platform operating expedited airport security lanes, in the style of a CLEAR-type service. Travelers enroll once — presenting a government identity document and submitting a biometric capture at a kiosk or staffed enrollment center — and thereafter pass through partner airports by verifying at a lane, where an ambassador escorts them to the front of physical screening. Where an airport's partner agreement carries a federal integration flag, a successful lane verification against an eligible document substitutes for the document check at screening and upgrades the member's standing to a federally trusted level.

The platform's commercial life runs through three parallel rails. Airport partners sign agreements that govern lane placement, staffing footprint, and a revenue share on both per-verification lane revenue and subscription MRR attributed to their airport; periodic settlements reconcile what the partner is owed against a monthly minimum guarantee. Members hold subscriptions — individual or family — billed monthly, with partner-sponsored percentage discounts, deferred plan upgrades, and a dunning path from failed payment through past-due to cancellation. Beyond airports, the same verified membership unlocks access at stadiums and other venues, where admission rules are venue-local (age gates independent of airport rules) and venues are paid out under a separate event-based settlement variant.

Because the system holds biometric data, compliance is a first-class workflow rather than an afterthought. Enrollment submissions pass through a weighted fraud-risk score that can route an application into manual review or reject it outright; identity disputes suspend the member, are adjudicated under segregation of duties, and on a confirmed finding terminate the member and schedule biometric deletion. A retention clock governs when biometric data must be purged, every retention action lands in an immutable audit log, and a test-driving logical clock plus billing and watchlist simulators let operators exercise every deadline, sweep, and threshold deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the caller and `X-User-Role` naming the caller's role. A request missing either header, or carrying a role string the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). These two checks precede all other validation on every endpoint.

The declared roles are exactly: `Member`, `Ambassador`, `OpsAdmin`, `PartnerManager`, `ComplianceOfficer`, and `VenueOps`.

Identity binding differs by role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` — own enrollments, own subscription and invoices, own family group, own lane verifications, own venue access — compare the resource's member foreign key to `X-User-ID`. Ownership comparison applies to member-scoped mutations (opening or acting on an enrollment, creating or managing a subscription, managing a family group, checking in, recording venue access, requesting biometric deletion); plain reads of a resource by id are not ownership-restricted. When `X-User-Role` is `Ambassador`, `X-User-ID` is the `id` of the acting `Ambassador`; completing an escort requires that the lane verification's named ambassador match `X-User-ID`. When `X-User-Role` is `OpsAdmin`, `PartnerManager`, `ComplianceOfficer`, or `VenueOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `resolved_by` on an `IdentityDispute` or as `actor_user_id` on a `BiometricRetentionLog` — but does not compare it to any entity's `id`.

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

All list endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10; the minimum accepted value is 1 and the maximum is 100. The default `offset` is 0. List responses include `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope. Unless a list endpoint states otherwise, results are sorted by `created_at` ascending, with ties broken by `id` ascending.

### 2.4. Common Resource Properties and the Logical Clock

Every entity carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp. All entities except `BiometricRetentionLog` additionally carry `updated_at` and an integer `version` that starts at 1 and increments by exactly one on every mutation of that entity. `BiometricRetentionLog` carries only `id` and `created_at` — both `updated_at` and `version` are absent on retention log entries, since audit rows are append-only. All timestamps are ISO 8601 UTC with three fractional digits. State machines surface through a `status` field on the owning entity, whose value is always one of the exact UPPERCASE strings named throughout this document.

The platform never reads wall-clock time for business logic. A single logical clock drives every deadline, expiry, window, retention, and sweep decision. Before any test-driving call, the logical clock reads exactly 2026-09-01T00:00:00Z. An `OpsAdmin` advances it through an admin-only capability that sets the clock to a supplied `to_iso8601` instant; whenever that call crosses a date boundary, the daily sweep runs — cancelling subscriptions whose past-due timer has elapsed, expiring stale escort windows, purging biometric data past its retention due date, and expiring agreements whose term has ended. Within a single logical date, consecutive sets that do not change the date do not re-run the sweep; the sweep fires on each set whose new date differs from the date the clock held immediately before that set. The response echoes the new clock as `current_utc`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several resources are addressed through hierarchical paths. Path identifiers are validated left to right — the parent is resolved before the child — and a missing identifier at any level yields the 404 for that level, never a deeper error. For example, on a path that threads airport, agreement, and lane, an unknown airport surfaces as `ERR_AIRPORT_NOT_FOUND` before the agreement is ever examined (`ERR_AGREEMENT_NOT_FOUND`), and an unknown lane surfaces as `ERR_LANE_NOT_FOUND` only after its ancestors resolved. The same discipline applies to subscription before family group and to every other nested route: each resource class has its own not-found code — `ERR_KIOSK_NOT_FOUND`, `ERR_ENROLLMENT_CENTER_NOT_FOUND`, `ERR_AMBASSADOR_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_FAMILY_GROUP_NOT_FOUND`, `ERR_DISCOUNT_NOT_FOUND`, `ERR_LANE_VERIFICATION_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_VENUE_EVENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, and `ERR_SETTLEMENT_NOT_FOUND`.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency on a parent entity's `version`; both reject a stale caller view with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here take no version field at all.

First, completing an escort — the ambassador action that moves a lane verification from `PENDING` to `ESCORTED` — requires the non-optional input `expected_member_version`, carrying the member `version` the client observed at check-in (which the check-in response itself pinned as `version_confirmed`). If the member's version has advanced since check-in — for instance because a dispute suspension or a family-slot change landed in between — the escort is rejected with `ERR_STALE_VERSION`, forcing the caller to re-read the member before proceeding.

Second, changing a subscription's plan requires the non-optional input `expected_subscription_version`, carrying the subscription `version` the client last observed. If the version has advanced since — for instance because a renewal invoice applied a deferred plan change — the request is rejected with `ERR_STALE_VERSION` so the client re-reads `price_cents` before deciding.

### 2.7. Money, Rates, and Rounding Discipline

All monetary amounts are integer cents. Where a calculation produces a fractional share — revenue shares on settlements — each share is rounded independently to two decimal places, round half up, before any further combination; rounding after combination is a different, forbidden variant. Where invoice line amounts are computed, each per-member line is rounded half up to zero decimal places first, and the invoice total is the sum of those rounded lines; summing unrounded lines and rounding once at the end yields a different cent in boundary cases and is likewise forbidden.

Partner agreement rates are fractions: both `rev_share_rate` and `subscription_share_rate` must be strictly greater than zero and at most 0.30. A value outside that band, like any other field-level shape failure, is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.8. Validation Order of Precedence

When several validations could fire on the same request, they are evaluated in a fixed order so that the surfaced error is deterministic. Authentication comes first (missing or unrecognized credentials, `ERR_UNAUTHENTICATED`), then authorization (role not permitted, `ERR_UNAUTHORIZED`), then existence of path identifiers left to right (the `ERR_*_NOT_FOUND` family), then state legality (`ERR_INVALID_STATE`). Only after those four come the business rules, in this sequence: age floors and venue age gates; document validity (expiry, format, uniqueness); biometric safety gates (open-dispute deletion block, active-event requirement); segregation of duties on dispute resolution; structural uniqueness and shape constraints; temporal windows (agreement effectiveness, kiosk activation window, escort window, event-window conflicts, event-already-started); cross-entity state requirements (agreement active, member active, lane open, subscription active, right ambassador); and finally capacity and quota rules (lane footprint, family slots, discount redemptions and expiry, rate bands).

## 3. Business Logic & Workflows

### 3.1. Airports, Partner Agreements, and Lanes

Onboarding a partner airport begins when an `OpsAdmin` registers the airport with its `iata_code` (a globally unique three-letter uppercase code), display `name`, `city`, and two-letter `state_code`. The new airport starts in `ONBOARDING` and stays there until its first partner agreement activates.

A `PartnerManager` drafts a `PartnerAgreement` against an airport, supplying `airport_id`, the `rev_share_rate` on lane verification revenue, the `subscription_share_rate` on attributed subscription MRR, a `monthly_minimum_cents` floor (zero or greater), the `federal_integration` flag, the contracted `staffing_footprint_seats` (at least one), a `term_months` length between 1 and 120, and an `effective_from` instant. At most one agreement per airport may sit in `DRAFT` or `ACTIVE` at a time; a second attempt is refused with `ERR_DUPLICATE_AGREEMENT`. A fresh draft carries `lane_capacity` of zero.

Activating a `DRAFT` agreement requires the logical clock to have reached `effective_from`; earlier activation is refused with `ERR_AGREEMENT_NOT_YET_EFFECTIVE`. On activation the agreement's `effective_to` is computed as `effective_from` plus `term_months` (calendar months, with the day-of-month clamped to the last day of the target month), and if this is the airport's first activation the airport cascades from `ONBOARDING` to `ACTIVE`. A `SUSPENDED` agreement may be re-activated, but only while the logical clock is still before `effective_to`; at or past that instant the attempt fails with `ERR_AGREEMENT_EXPIRED`. Independently, a daily sweep flips an `ACTIVE` agreement to `EXPIRED` once the logical clock reaches `effective_to`.

Lanes are planned under an agreement at a specific airport with a `terminal` label, a `position_index` that must be at least 1, an `open_time` and `close_time` (airport-local HH:MM, with close strictly after open), and a `capacity_hours` figure between 1 and 24 — the verification hours the lane can serve per logical day. New lanes start `PLANNED`. The agreement named by `agreement_id` must belong to the same airport named by `airport_id`.

Opening a lane — from `PLANNED`, or re-opening from `MAINTENANCE` — requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise) and passes a staffing-footprint capacity check. The lane's own state legality is checked first: a lane that is neither `PLANNED` nor `MAINTENANCE` (for example one already `CLOSED` by an agreement termination or expiry cascade) fails with `ERR_INVALID_STATE` before the agreement state is examined, so both `ERR_INVALID_STATE` and `ERR_AGREEMENT_NOT_ACTIVE` are acceptable surfaces for an open attempt on a lane whose agreement is no longer active. The agreement's `lane_capacity` is the sum of `capacity_hours` across its lanes in `OPEN` or `MAINTENANCE`; `PLANNED` and `CLOSED` lanes do not count. Opening is allowed only if the resulting total, including the lane being opened, stays within the agreement's `staffing_footprint_seats` multiplied by four ambassador seat-hours per seat; a projected total exactly equal to that ceiling is allowed, and anything above it is refused with `ERR_CAPACITY_EXCEEDED`. Because `MAINTENANCE` lanes already count toward `lane_capacity`, re-opening a maintenance lane leaves the total unchanged, while opening a planned lane raises it.

Closing a lane takes a `mode`: maintenance mode moves an `OPEN` lane to `MAINTENANCE`, while closed mode moves an `OPEN` or `MAINTENANCE` lane to `CLOSED`. Every such transition recomputes the agreement's `lane_capacity`.

Suspensions cascade downward. Suspending an `ACTIVE` airport pushes its `ACTIVE` agreement to `SUSPENDED` and each of that agreement's `OPEN` lanes to `MAINTENANCE` (the lanes still count toward capacity while in maintenance). Re-activating a `SUSPENDED` airport — which requires the airport to have an agreement in `ACTIVE` or `SUSPENDED` status, failing `ERR_AGREEMENT_NOT_ACTIVE` otherwise — flips the suspended agreement back to `ACTIVE`, but the lanes stay in `MAINTENANCE` and must be re-opened individually. An agreement can also be suspended on its own, with the same lane cascade. Terminating an agreement, from either `ACTIVE` or `SUSPENDED`, moves every lane of that agreement in `PLANNED`, `OPEN`, or `MAINTENANCE` to `CLOSED` and drives `lane_capacity` to zero, releasing each lane's hours from the airport-day capacity pool so the airport's capacity accounting returns to zero. Agreement expiry applies the same lane cascade.

### 3.2. Kiosks, Enrollment Centers, and Ambassadors

An `OpsAdmin` registers a kiosk at an airport with a globally unique hardware `code`; a duplicate code (like a duplicate `iata_code` or discount code) is refused with `ERR_DUPLICATE_CODE`. Kiosks begin in `PROVISIONING`. Activation — permitted from `PROVISIONING`, or from `SUSPENDED` as a re-activation — requires the kiosk's airport to hold an `ACTIVE` agreement, failing `ERR_AGREEMENT_NOT_ACTIVE` otherwise. Each activation stamps `activated_at` with the logical clock and resets `consecutive_capture_failures` to zero; the stamp anchors the twenty-four-hour enrollment completion window described in §3.3, and a re-activation restarts that window. An `ACTIVE` kiosk can be suspended — manually, or automatically the moment a third consecutive capture failure is recorded — and an `ACTIVE` or `SUSPENDED` kiosk can be retired to `RETIRED`, which is a terminal state from which no further transition exists.

Enrollment centers are the staffed counterpart: created at an airport with a display `name` and an `ambassador_capacity` of at least one seat, and born `ACTIVE`. Ambassadors are registered at a single home airport with a `display_name` and a globally unique `employee_ref`, also born `ACTIVE`; operations may suspend an ambassador, and a suspended ambassador cannot escort.

### 3.3. Member Enrollment and the Fraud Pipeline

A traveler self-registers with `email`, `full_name` exactly as printed on the identity document, and `date_of_birth`. The email is unique across members case-insensitively. The new member starts in `PENDING_ENROLLMENT` with `verification_level` of `NONE`, `risk_score` of zero, and `document_reject_count_90d` of zero.

The member then opens an enrollment at a site, providing `member_id`, a `site_type` of `KIOSK` or `ENROLLMENT_CENTER`, the `site_id` of the chosen kiosk or enrollment center (a polymorphic reference resolved by `site_type`), the `document_type` (`PASSPORT`, `DRIVERS_LICENSE`, or `STATE_ID`), the `document_number`, the `document_expiry` date, and the hardware-reported `biometric_capture_ok` flag. The enrollment is born `DRAFT`. If the member already has a prior `COMPLETED` enrollment, the new draft is flagged `is_re_enrollment`, which changes two behaviors downstream: the document-expiry check is skipped, and on completion the prior enrollment is displaced.

Submitting the document is the risk gate. Four checks run in a fixed order. First, the member must be at least 18 years old — the `date_of_birth` must fall at least eighteen years before the logical clock date — failing `ERR_MEMBER_UNDERAGE`. Second, unless this is a re-enrollment, `document_expiry` must lie strictly after the logical clock date, failing `ERR_DOCUMENT_EXPIRED`. Third, the `document_number` must not appear on any other enrollment that ever reached the document-verified milestone — including one subsequently routed into `FRAUD_REVIEW` — failing `ERR_DOCUMENT_ALREADY_ENROLLED`. Fourth, the member's `document_reject_count_90d` — the count of this member's enrollments that flipped to `REJECTED` within the trailing ninety logical days, recomputed on every rejection — must be below three, failing `ERR_TOO_MANY_REJECTED_ENROLLMENTS`.

With those passed, the platform computes the member's fraud risk score from current facts. Four additive rules may fire: `VELOCITY` contributes 8 points when the member's `document_reject_count_90d` has reached three; `WATCHLIST` contributes 8 points when the pairing of `document_number` and `date_of_birth` appears on the fraud watchlist (an `OpsAdmin` maintains that list, adding or removing a pair by `action`; the `action` value is matched case-insensitively, so `add`/`ADD` and `remove`/`REMOVE` are equivalent, and any other value fails `ERR_VALIDATION`); `DOC_FORMAT` contributes 4 points when the `document_number` fails its MOD-7 checksum, meaning the sum of the digits of its numeric portion is not divisible by seven; `SELFIE_MISMATCH` contributes 5 points when `biometric_capture_ok` was declared false on the draft. The member's `risk_score` is the sum of firing rules, floored at zero, and the ordered list of fired rule codes is recorded on the enrollment as `risk_flags`. Because the velocity component reads the rejection counter at evaluation time, a rejection landing between submission and a later review legitimately changes the score the review sees.

Routing is by threshold, with inclusive boundaries: a score of exactly 15 or more but below 20 routes the enrollment to `FRAUD_REVIEW` instead of `DOCUMENT_VERIFIED`; a score of exactly 20 or more rejects the enrollment outright — it lands in `REJECTED` without ever being document-verified, and the member's `document_reject_count_90d` increments. Below 15, the enrollment proceeds to `DOCUMENT_VERIFIED`.

From `DOCUMENT_VERIFIED`, the member records the biometric capture. The capture requires `biometric_capture_ok` to be true; a false flag is refused with `ERR_BIOMETRIC_CAPTURE_FAILED`, and when the failed capture happens at a kiosk site the kiosk's `consecutive_capture_failures` increments — the third consecutive failure auto-suspends the kiosk. A successful capture moves the enrollment to `BIOMETRIC_CAPTURED`.

Completion turns an enrollment into a live credential. At a kiosk site, completion must occur no later than twenty-four hours after the kiosk's `activated_at`; later completion is refused with `ERR_KIOSK_ACTIVATION_WINDOW_EXPIRED`. Enrollment-center sites carry no such window. On completion three cascades run: the member moves from `PENDING_ENROLLMENT` to `ACTIVE` with `version` incremented, and if the member already holds a `subscription_id` that subscription is created or confirmed in `ACTIVE` with `current_period_start` at now and `current_period_end` thirty days out; on a re-enrollment, the member's previous `COMPLETED` enrollment moves to `SUPERSEDED` with its `superseded_by_id` pointing at the new enrollment; and a member whose subscription sat in `PAST_DUE` stays `PAST_DUE` — completion does not implicitly cure delinquency.

Enrollments parked in `FRAUD_REVIEW` await a `ComplianceOfficer` decision. Review requires the enrollment to actually be in `FRAUD_REVIEW` (`ERR_ENROLLMENT_NOT_IN_REVIEW` otherwise) and takes a `decision`: approval runs the same completion cascades as an ordinary completion, while rejection moves the enrollment to `REJECTED`, increments the member's `document_reject_count_90d`, and recomputes the velocity component of the member's risk score.

### 3.4. Subscriptions, Family Groups, Discounts, and Billing

A member creates a subscription with `member_id`, a `plan` of `INDIVIDUAL` or `FAMILY`, and a `billing_cycle_day` anchor between 1 and 28. At most one subscription per member may be in `ACTIVE` or `PAST_DUE` at a time; a second attempt while one exists fails with `ERR_INVALID_STATE`. The base monthly price is 18900 cents for both plans; choosing `FAMILY` also creates a `FamilyGroup` for the subscription with `slots_total` of three and the primary member already attached, so `slots_used` starts at one. The subscription activates when the member's enrollment completes, with the period running thirty days from activation. When the member is already `ACTIVE` at creation time, creation itself stamps `current_period_start` at the logical clock and `current_period_end` thirty days out as part of creating the subscription — not as a post-creation mutation — so the subscription's `version` is still 1 when the creation response is returned.

Family groups carry `primary_subscription_id`, a `slots_total` of two or three (the total counting the primary), and a `slots_used` counter that must never exceed `slots_total`; the boundary where `slots_used` equals `slots_total` is full. The primary member attaches a dependant by `member_id`; the added member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE` otherwise) and not already attached to another group (a member already carrying a `family_group_id` fails `ERR_VALIDATION`), and attaching into a full group fails with `ERR_FAMILY_FULL`; an attach attempt on a dissolved group fails `ERR_INVALID_STATE`. Detaching a member (never the primary) — addressed by the group's `id` and the `memberId` of the dependant in the path — decrements `slots_used` and clears that member's `family_group_id`; detaching the primary or a member not attached to the group fails `ERR_VALIDATION`. Family members retain access while the subscription is `PAST_DUE`.

Partner discounts are created by a `PartnerManager` for a sponsoring airport with a globally unique `code`, a `percent_off` between 1 and 100, a `max_redemptions` cap of at least one, and an `expires_at` instant. A member attaches a discount to a subscription by `discount_code`. The attach requires the discount to be `ACTIVE`, the logical clock to be strictly before `expires_at` (`ERR_DISCOUNT_EXPIRED` at or past it), and remaining redemption headroom — a discount whose `redemptions_used` has reached `max_redemptions` has already flipped to `EXHAUSTED` and attaching to it fails with `ERR_DISCOUNT_EXHAUSTED`. A successful attach increments `redemptions_used` (which is never decremented, even on detach or cancel), flips the discount to `EXHAUSTED` the moment the counter reaches the cap, sets the subscription's `partner_discount_id`, and recomputes `price_cents`. Detaching clears `partner_discount_id` and recomputes `price_cents` at full price. A `PartnerManager` may suspend an active discount.

Invoice amounts follow a pinned rounding order. The base is 18900 cents for either plan. When a discount is attached, the discount factor is one minus `percent_off` hundredths; otherwise the factor is one. The discounted base rounds half up to whole cents. For a family plan, each dependant — that is, `slots_used` minus one members — contributes a line of 9900 cents times the discount factor, each line independently rounded half up to whole cents. The invoice `amount_cents` is the discounted base plus the sum of the rounded lines. The subscription's own `price_cents` equals the discounted base for both plans; the dependant lines appear on the invoice, not on `price_cents`.

Plan changes are requested with a `new_plan` value and are asymmetric. Switching from `FAMILY` to `INDIVIDUAL` applies immediately with no refund of the current period: `price_cents` is recomputed and the family group is dissolved. Switching from `INDIVIDUAL` to `FAMILY` is always deferred: the request records `pending_plan`, and the change is applied at the next renewal — at that point `plan` becomes the pending value, `price_cents` is recomputed, `pending_plan` clears, and a `FamilyGroup` is created. No pro-rata mid-cycle invoice is ever issued for the upgrade direction. Every plan change carries the OCC guard of §2.6 and increments the subscription's `version` by one regardless of direction. A `CANCELLED` subscription rejects any plan change with `ERR_INVALID_STATE`, and a `new_plan` equal to the current plan fails `ERR_VALIDATION`.

Billing runs through an `OpsAdmin`-triggered renewal that issues a `SubscriptionInvoice` in `DUE` status for the current period, with `due_at` equal to the period end; a `CANCELLED` subscription has no renewal (`ERR_INVALID_STATE`), and a payment recorded after `due_at` is still accepted but counts as late. Payments themselves are recorded through the billing simulator by `invoice_id` and `outcome`; only an invoice still in `DUE` accepts a payment — an already `PAID` or `VOID` invoice fails `ERR_INVALID_STATE`. A succeeded payment moves the invoice to `PAID`, advances the subscription's `current_period_end` by thirty days, and — if the subscription was `PAST_DUE` — returns it to `ACTIVE`, clears `past_due_since`, and applies any `pending_plan` exactly as described above. A failed payment is recorded against the invoice as a `FAILED` attempt while the invoice itself stays `DUE`, increments its `attempt_count`, and on the first failure moves the subscription from `ACTIVE` to `PAST_DUE`, stamping `past_due_since` with the logical clock. From there, a daily sweep cancels the subscription once the logical clock reaches seven days past `past_due_since` — the deadline is inclusive, so a clock exactly seven days on is already past due for cancellation. When a subscription cancels, any of its `DUE` invoices move to `VOID`.

Voluntary cancellation is a member action on a subscription in `ACTIVE` or `PAST_DUE`, but only while the member itself is `ACTIVE` — a suspended member cannot self-cancel (`ERR_MEMBER_NOT_ACTIVE`) because their cancellation rides the dispute cascade instead. Cancellation moves the family group to its terminal `DISSOLVED` status (detaching all dependants and clearing each `family_group_id`), detaches the partner discount without decrementing its redemptions, schedules biometric retention on the member, and voids outstanding invoices. Service continues until `current_period_end`; the member's status stays `ACTIVE` until then rather than flipping immediately.

### 3.5. Lane Check-In and Escort

At the airport, a member checks in at a lane by presenting `member_id`, `lane_id`, and the `ambassador_id` of the escorting ambassador. Check-in requires the lane to be `OPEN` (`ERR_LANE_NOT_OPEN`), the member to be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), the member's subscription to be `ACTIVE` or `PAST_DUE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`), the lane's agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), and the ambassador to be `ACTIVE` and homed at the same airport as the lane (`ERR_WRONG_AMBASSADOR`). A member whose biometric data has been purged cannot check in at all — the attempt is refused with `ERR_BIOMETRIC_PURGED` and the member must re-enroll.

A successful check-in creates a `LaneVerification` whose `escort_status` begins at `PENDING`, with `verified_at` stamped from the logical clock, `expires_at` set fifteen minutes later, `version_confirmed` pinned to the member's current `version`, and the check-in `outcome` (`VERIFIED` or `REJECTED`, with a `reject_reason` of `BIOMETRIC_MISMATCH`, `LANE_CLOSED`, `MEMBER_INELIGIBLE`, or `WRONG_AMBASSADOR` on failure) recorded synchronously in the response. The `federal_program` flag is computed at check-in: it is true when the lane's agreement has `federal_integration` enabled and the member's enrolled `document_type` is `PASSPORT` or `DRIVERS_LICENSE`, in which case the verified identity substitutes for the document check at screening.

The escort completes when the named ambassador finishes walking the member to screening. The `X-User-ID` of the calling ambassador must equal the verification's `ambassador_id`; any other ambassador's attempt is refused with `ERR_WRONG_AMBASSADOR`. The escort window check permits completion while the logical clock is at or before `expires_at`; exactly at the deadline is allowed, and one minute later is refused with `ERR_ESCORT_WINDOW_EXPIRED`. The OCC guard of §2.6 applies with full force here because of the side effect: when `federal_program` is true and the member's `verification_level` is not yet `FEDERAL_TRUSTED`, completing the escort upgrades the member to `FEDERAL_TRUSTED`, which increments the member's `version` — precisely the mutation the `expected_member_version` pin protects against. A daily sweep moves any verification still `PENDING` past its `expires_at` to `EXPIRED`.

### 3.6. Venues, Events, and Member Access

Expansion beyond airports runs through venues, which a `VenueOps` operator creates with a `name`, a `venue_type` of `STADIUM`, `ARENA`, or `OTHER`, a `city` and `state_code`, and an optional `access_rule_mode` defaulting to `AGE_18_PLUS`. Venue access rules are independent of airport lane rules. Venues are born `ACTIVE` and can be suspended.

Events are scheduled against a venue with a `venue_id`, a `name`, a future `start_time`, an `end_time` strictly after the start, and a `buffer_hours` setup/teardown padding between zero and twelve (defaulting to zero). Scheduling applies a padded-window conflict check against every other non-`CANCELLED` event at the same venue: each event's effective window runs from its start minus its buffer to its end plus its buffer, and two events conflict only when the padded windows strictly overlap — the candidate's padded start is before the existing event's padded end and the existing event's padded start is before the candidate's padded end. Touching edges do not conflict; the windows behave as half-open intervals. A conflict is refused with `ERR_EVENT_WINDOW_CONFLICT`. Cancelling an event is possible only while the logical clock is still before its `start_time`; at or after the start the attempt fails with `ERR_EVENT_ALREADY_STARTED`. A cancelled event no longer admits members and no longer counts toward venue payout event totals.

Member access at a venue is recorded as a `VenueAccessEvent` with `venue_id` and `member_id`, stamped `accessed_at` from the logical clock, and its `outcome` — `ADMITTED` or `REJECTED` with a `reject_reason` of `AGE_RULE`, `VENUE_SUSPENDED`, `MEMBER_INELIGIBLE`, or `NO_ACTIVE_EVENT` — is decided synchronously. Admission requires the venue to be `ACTIVE` (a suspended venue rejects the attempt with a 201 response carrying a recorded `VenueAccessEvent` of `outcome` `REJECTED` and `reject_reason` `VENUE_SUSPENDED`), the member to be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), and a `SCHEDULED` event at that venue whose window — start through end, not padded by `buffer_hours` — covers the logical clock, with endpoints inclusive — without one the attempt is refused with `ERR_NO_ACTIVE_EVENT` and no event is recorded. The age gate follows the venue's mode using the member's age in whole years at the logical clock date, with a birthday reached on the day counting: `ALL_MEMBERS` admits any active member; `AGE_18_PLUS` admits members aged at least eighteen, and `AGE_21_PLUS` those at least twenty-one — a member whose eighteenth (respectively twenty-first) birthday is exactly the access date is admitted. A failed age gate surfaces as `ERR_AGE_RULE_VIOLATION` (HTTP 422, not a 201 carrying the event), and the rejected attempt is still recorded as a `VenueAccessEvent` with `outcome` of `REJECTED` and `reject_reason` of `AGE_RULE`, visible through the venue-access-event listing endpoints.

### 3.7. Identity Disputes, Suspension, and Termination

A `ComplianceOfficer` opens an `IdentityDispute` against a member with `member_id`, the contested `enrollment_id`, and a `reason` of `IDENTITY_TAKEOVER`, `BIOMETRIC_FALSE_MATCH`, `DOCUMENT_FRAUD`, or `DATA_ERROR`. Opening a dispute is itself a cascade: a member in `ACTIVE` moves to `SUSPENDED` (opening against a member in any other status leaves that status unchanged), every in-flight `DRAFT` enrollment of that member flips to `REJECTED` (each rejection incrementing `document_reject_count_90d`), and the dispute lands in `OPEN`.

Investigation moves an `OPEN` dispute to `INVESTIGATING`. Resolution, from either `OPEN` or `INVESTIGATING`, takes an `outcome` and a mandatory `resolution_note` of one to one thousand characters (its absence fails `ERR_VALIDATION`). Segregation of duties is enforced on resolution: the resolving officer's `X-User-ID` must differ from the opener's, and a self-resolution is refused with `ERR_SEGREGATION_OF_DUTIES`; the resolver is recorded as `resolved_by`. A clear outcome — `RESOLVED_CLEAR` — returns the suspended member to `ACTIVE` (a member no longer `SUSPENDED` is left untouched), leaving the member's `verification_level` (`NONE`, `BIOMETRIC_ID`, or `FEDERAL_TRUSTED`) untouched. A confirmed outcome — `RESOLVED_CONFIRMED` — moves the member to `TERMINATED` and triggers the full termination cascade when the member is still `SUSPENDED` (a member already terminated is not cascaded again): the member's subscription (if any) is cancelled with the same semantics as a voluntary cancel, the member is detached from any family group with `slots_used` decremented, `deletion_due_at` is set to the logical clock plus the retention period, and a `BiometricRetentionLog` entry of type `DELETION_SCHEDULED` is appended.

Operations also hold two override levers. An `OpsAdmin` may directly suspend an `ACTIVE` member — for instance on an external fraud signal — with the same draft-enrollment rejection cascade (a member not in `ACTIVE` fails `ERR_MEMBER_NOT_ACTIVE`). And an `OpsAdmin` may directly terminate a `SUSPENDED` member, but only when at least one dispute for that member has already resolved `RESOLVED_CONFIRMED`; without one the termination fails `ERR_DISPUTE_NOT_CONFIRMED`. The admin termination runs the same cascade as the dispute-driven termination.

### 3.8. Biometric Retention and Audit

Biometric data lives under a thirty-day retention clock. Whenever a subscription cancels or a member is terminated, the member's `deletion_due_at` is set to the trigger instant plus thirty days and a `DELETION_SCHEDULED` entry lands in the retention audit log. The daily sweep purges biometric data only when the logical clock is strictly after `deletion_due_at` — exactly at the due instant is not yet due — and appends a `DELETED` entry with `actor_user_id` recorded as system.

A member or a `ComplianceOfficer` may also request manual deletion ahead of the due date; the request carries a mandatory free-text `note`. Manual deletion is blocked while the member has a dispute in `OPEN` or `INVESTIGATING`, refused with `ERR_DISPUTE_OPEN`. A successful manual delete appends the `DELETED` log entry, clears the member's `deletion_due_at`, and from then on any lane check-in for the member is refused with `ERR_BIOMETRIC_PURGED` until they re-enroll. Audit exports append an `AUDIT_EXPORTED` entry. Every log row records the subject `member_id`, the `action`, the `actor_user_id` (the triggering `X-User-ID`, or system for the sweep), and the `note`.

### 3.9. Partner Settlements — Airport and Venue Variants

Settlements reconcile what a partner is owed for a period, and come in two variants that deliberately produce different fees for identical period revenue inputs.

The airport variant is created by a `PartnerManager` against an agreement with `period_start` (inclusive), `period_end` (exclusive, and strictly after the start), `attributable_mrr_cents`, and `verification_revenue_cents` (both zero or greater). The fee evaluation order is pinned. First the subscription share: `attributable_mrr_cents` multiplied by the agreement's `subscription_share_rate`, rounded half up to two decimal places. Second the revenue share: `verification_revenue_cents` multiplied by the agreement's `rev_share_rate`, likewise rounded half up to two decimal places. Third, the variable fee is the sum of the two rounded shares. Fourth and last, the monthly minimum guarantee applies: `fee_cents` is the greater of the agreement's `monthly_minimum_cents` and the variable fee. Rounding each share before taking the maximum is required; rounding after the maximum is a forbidden variant. The settlement records `calculation_variant` of `AIRPORT`.

The venue variant is created by a `VenueOps` operator against a venue — its `venue_id` is set while `agreement_id` stays unset — with `period_start`, `period_end`, `verification_revenue_cents`, an `events_count` of non-`CANCELLED` events hosted in the period, and `venue_capacity_seats` supplied on the request (venue capacity is not derived from any airport figure); `attributable_mrr_cents` plays no part in the venue variant and is stored as zero. The payout is the greater of a pinned venue minimum floor of 50000 cents and a computed variable amount, where the variable amount is the venue's capacity value — `venue_capacity_seats` times a per-seat base of 500 cents — times a venue revenue share of 0.20, rounded half up to two decimal places, plus a per-event fee of 100000 cents per event. The per-event fee is earned on every event once `events_count` reaches the venue event threshold of five, and is zero below the threshold; it is not marginal — crossing the threshold prices all events, not just those past it. The settlement records `calculation_variant` of `VENUE`.

Both variants are born `DRAFT`. While a settlement is in `DRAFT`, its `fee_cents` recomputes from current inputs on every read. A `PartnerManager` finalizes a draft — moving it to `FINALIZED` — once its `period_end` is on or before the current logical date — finalizing a period that has not ended fails with `ERR_PERIOD_NOT_ENDED` — and finalization freezes `fee_cents` at its computed value; later corrections to the inputs require a new settlement. A `FINALIZED` settlement is then marked paid, reaching the terminal `PAID` state.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, record an action, or drive a state transition respond with HTTP 200. All responses use the envelope of §2.2, all list endpoints paginate per §2.3, and authorization follows §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock; runs the daily sweep when the date advances | OpsAdmin |
| POST | /_fraud/watchlist | Add or remove a (document_number, date_of_birth) pair on the fraud watchlist | OpsAdmin |
| POST | /_billing/record-payment | Record a payment outcome for a DUE invoice (billing test driver) | OpsAdmin |
| POST | /_admin/members/{id}/suspend | Administratively suspend an ACTIVE member | OpsAdmin |
| POST | /_admin/members/{id}/terminate | Administratively terminate a SUSPENDED member with a confirmed dispute | OpsAdmin |
| POST | /airports | Onboard an airport | OpsAdmin |
| GET | /airports | List airports | OpsAdmin, PartnerManager, ComplianceOfficer |
| GET | /airports/{id} | Get an airport | OpsAdmin, PartnerManager, ComplianceOfficer |
| POST | /airports/{id}/suspend | Suspend an airport; cascades to agreement and lanes | OpsAdmin |
| POST | /airports/{id}/activate | Re-activate a suspended airport; cascades agreement re-activation | OpsAdmin |
| POST | /partner-agreements | Draft a partner agreement for an airport | PartnerManager |
| GET | /partner-agreements | List agreements (filterable by airport_id) | OpsAdmin, PartnerManager |
| GET | /partner-agreements/{id} | Get an agreement | OpsAdmin, PartnerManager |
| POST | /partner-agreements/{id}/activate | Activate a DRAFT or SUSPENDED agreement | PartnerManager |
| POST | /partner-agreements/{id}/suspend | Suspend an agreement; OPEN lanes go to MAINTENANCE | PartnerManager |
| POST | /partner-agreements/{id}/terminate | Terminate an agreement; all non-CLOSED lanes close | PartnerManager |
| POST | /lanes | Plan a lane under an agreement at an airport | OpsAdmin |
| GET | /lanes | List lanes (filterable by agreement_id, airport_id) | OpsAdmin, PartnerManager, Ambassador, Member |
| GET | /lanes/{id} | Get a lane | OpsAdmin, PartnerManager, Ambassador, Member |
| POST | /lanes/{id}/open | Open a PLANNED or MAINTENANCE lane; capacity check applies | OpsAdmin |
| POST | /lanes/{id}/close | Move a lane to MAINTENANCE or CLOSED | OpsAdmin |
| POST | /kiosks | Register a kiosk at an airport | OpsAdmin |
| GET | /kiosks | List kiosks (filterable by airport_id) | OpsAdmin, PartnerManager |
| GET | /kiosks/{id} | Get a kiosk | OpsAdmin, PartnerManager |
| POST | /kiosks/{id}/activate | Activate or re-activate a kiosk; restarts the 24h window | OpsAdmin |
| POST | /kiosks/{id}/suspend | Suspend a kiosk | OpsAdmin |
| POST | /kiosks/{id}/retire | Retire a kiosk (terminal) | OpsAdmin |
| POST | /enrollment-centers | Create an enrollment center at an airport | OpsAdmin |
| GET | /enrollment-centers | List enrollment centers (filterable by airport_id) | OpsAdmin, PartnerManager |
| GET | /enrollment-centers/{id} | Get an enrollment center | OpsAdmin, PartnerManager |
| POST | /ambassadors | Register an ambassador at an airport | OpsAdmin |
| GET | /ambassadors | List ambassadors (filterable by airport_id) | OpsAdmin, PartnerManager |
| GET | /ambassadors/{id} | Get an ambassador | OpsAdmin, PartnerManager |
| POST | /ambassadors/{id}/suspend | Suspend an ambassador | OpsAdmin |
| POST | /members/register | Register a member (PENDING_ENROLLMENT) | Member |
| GET | /members | List members (filterable by subscription_id, family_group_id) | OpsAdmin, ComplianceOfficer |
| GET | /members/{id} | Get a member | OpsAdmin, ComplianceOfficer, Member, Ambassador |
| POST | /enrollments | Open an enrollment draft at a kiosk or enrollment center | Member |
| GET | /enrollments | List enrollments (filterable by member_id, superseded_by_id) | OpsAdmin, ComplianceOfficer, Member |
| GET | /enrollments/{id} | Get an enrollment | OpsAdmin, ComplianceOfficer, Member |
| POST | /enrollments/{id}/submit-document | Submit the identity document; risk scoring and routing | Member |
| POST | /enrollments/{id}/capture-biometric | Record biometric capture for a DOCUMENT_VERIFIED enrollment | Member |
| POST | /enrollments/{id}/complete | Complete a BIOMETRIC_CAPTURED enrollment | Member |
| POST | /enrollments/{id}/review | Compliance decision on a FRAUD_REVIEW enrollment | ComplianceOfficer |
| POST | /subscriptions | Create a subscription for a member | Member |
| GET | /subscriptions | List subscriptions (filterable by member_id, partner_discount_id) | OpsAdmin, Member |
| GET | /subscriptions/{id} | Get a subscription | OpsAdmin, Member |
| POST | /subscriptions/{id}/attach-discount | Attach a partner discount code | Member |
| POST | /subscriptions/{id}/detach-discount | Detach the current discount | Member |
| POST | /subscriptions/{id}/change-plan | Change plan; INDIVIDUAL to FAMILY deferred, reverse immediate; OCC-guarded | Member |
| POST | /subscriptions/{id}/cancel | Voluntarily cancel a subscription | Member |
| POST | /subscriptions/{id}/invoices/run-cycle | Issue the renewal invoice for the current period | OpsAdmin |
| GET | /subscriptions/{id}/invoices | List invoices of a subscription | OpsAdmin, Member |
| GET | /subscription-invoices/{id} | Get an invoice | OpsAdmin, Member |
| GET | /family-groups | List family groups (filterable by primary_subscription_id) | OpsAdmin, Member |
| GET | /family-groups/{id} | Get a family group | OpsAdmin, Member |
| POST | /family-groups/{id}/members | Attach a member to a family group slot | Member |
| DELETE | /family-groups/{id}/members/{memberId} | Detach a non-primary member from a family group | Member |
| POST | /partner-discounts | Create a partner discount | PartnerManager |
| GET | /partner-discounts | List discounts (filterable by airport_id) | OpsAdmin, PartnerManager, Member |
| GET | /partner-discounts/{id} | Get a discount | OpsAdmin, PartnerManager, Member |
| POST | /partner-discounts/{id}/suspend | Suspend a discount | PartnerManager |
| POST | /lane-verifications | Member check-in at a lane; 15-minute escort window | Member |
| GET | /lane-verifications | List lane verifications (filterable by member_id, lane_id, ambassador_id) | OpsAdmin, Member, Ambassador |
| GET | /lane-verifications/{id} | Get a lane verification | OpsAdmin, Member, Ambassador |
| POST | /lane-verifications/{id}/escort | Ambassador completes the escort; OCC on member version | Ambassador |
| POST | /venues | Create a venue | VenueOps |
| GET | /venues | List venues | OpsAdmin, VenueOps, Member |
| GET | /venues/{id} | Get a venue | OpsAdmin, VenueOps, Member |
| POST | /venue-events | Schedule a venue event; padded-window conflict check | VenueOps |
| GET | /venue-events | List venue events (filterable by venue_id) | OpsAdmin, VenueOps, Member |
| GET | /venue-events/{id} | Get a venue event | OpsAdmin, VenueOps, Member |
| POST | /venue-events/{id}/cancel | Cancel a SCHEDULED event (only before start) | VenueOps |
| POST | /venue-access | Record a member's access attempt at a venue | Member |
| GET | /venue-access-events | List venue access events (filterable by venue_id, member_id) | OpsAdmin, VenueOps |
| GET | /venues/{id}/access-events | List venue access events for a venue | OpsAdmin, VenueOps |
| GET | /members/{id}/venue-access-events | List venue access events for a member | OpsAdmin, VenueOps, ComplianceOfficer |
| POST | /identity-disputes | Open an identity dispute; suspends the member | ComplianceOfficer |
| GET | /identity-disputes | List disputes (filterable by member_id, enrollment_id) | OpsAdmin, ComplianceOfficer |
| GET | /identity-disputes/{id} | Get a dispute | OpsAdmin, ComplianceOfficer |
| POST | /identity-disputes/{id}/investigate | Move an OPEN dispute to INVESTIGATING | ComplianceOfficer |
| POST | /identity-disputes/{id}/resolve | Resolve a dispute; resolver must differ from opener | ComplianceOfficer |
| POST | /members/{id}/biometric-deletion | Manually delete a member's biometric data; note mandatory | ComplianceOfficer, Member |
| GET | /biometric-retention-logs | List retention audit log entries (filterable by member_id) | OpsAdmin, ComplianceOfficer |
| GET | /members/{id}/biometric-retention-logs | List retention audit entries for a member | OpsAdmin, ComplianceOfficer |
| POST | /partner-agreements/{id}/settlements | Create an airport-fee settlement (AIRPORT variant) | PartnerManager |
| POST | /venues/{id}/payout-settlements | Create a venue payout settlement (VENUE variant) | VenueOps |
| GET | /agreement-settlements | List settlements (filterable by agreement_id, venue_id) | OpsAdmin, PartnerManager, VenueOps |
| GET | /agreement-settlements/{id} | Get a settlement | OpsAdmin, PartnerManager, VenueOps |
| POST | /agreement-settlements/{id}/finalize | Finalize a DRAFT settlement; freezes fee_cents | PartnerManager |
| POST | /agreement-settlements/{id}/mark-paid | Mark a FINALIZED settlement paid | PartnerManager |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows they guard. `ERR_NOT_FOUND` additionally covers any request to a path the API does not define, and `ERR_INTERNAL` is the envelope for any unexpected server fault.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_AIRPORT_NOT_FOUND | 404 |
| ERR_AGREEMENT_NOT_FOUND | 404 |
| ERR_LANE_NOT_FOUND | 404 |
| ERR_KIOSK_NOT_FOUND | 404 |
| ERR_ENROLLMENT_CENTER_NOT_FOUND | 404 |
| ERR_AMBASSADOR_NOT_FOUND | 404 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_SUBSCRIPTION_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_FAMILY_GROUP_NOT_FOUND | 404 |
| ERR_DISCOUNT_NOT_FOUND | 404 |
| ERR_LANE_VERIFICATION_NOT_FOUND | 404 |
| ERR_VENUE_NOT_FOUND | 404 |
| ERR_VENUE_EVENT_NOT_FOUND | 404 |
| ERR_DISPUTE_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ENROLLMENT_NOT_IN_REVIEW | 409 |
| ERR_MEMBER_NOT_ACTIVE | 409 |
| ERR_LANE_NOT_OPEN | 409 |
| ERR_AGREEMENT_NOT_ACTIVE | 409 |
| ERR_SUBSCRIPTION_NOT_ACTIVE | 409 |
| ERR_DISPUTE_NOT_CONFIRMED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_MEMBER_UNDERAGE | 422 |
| ERR_AGE_RULE_VIOLATION | 422 |
| ERR_DOCUMENT_EXPIRED | 422 |
| ERR_DOCUMENT_ALREADY_ENROLLED | 409 |
| ERR_TOO_MANY_REJECTED_ENROLLMENTS | 409 |
| ERR_BIOMETRIC_CAPTURE_FAILED | 422 |
| ERR_DISPUTE_OPEN | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_BIOMETRIC_PURGED | 409 |
| ERR_NO_ACTIVE_EVENT | 409 |
| ERR_VALIDATION | 400 |
| ERR_DUPLICATE_AGREEMENT | 409 |
| ERR_DUPLICATE_CODE | 409 |
| ERR_CAPACITY_EXCEEDED | 422 |
| ERR_FAMILY_FULL | 422 |
| ERR_DISCOUNT_EXHAUSTED | 422 |
| ERR_DISCOUNT_EXPIRED | 422 |
| ERR_PERIOD_NOT_ENDED | 409 |
| ERR_AGREEMENT_NOT_YET_EFFECTIVE | 409 |
| ERR_AGREEMENT_EXPIRED | 409 |
| ERR_KIOSK_ACTIVATION_WINDOW_EXPIRED | 409 |
| ERR_ESCORT_WINDOW_EXPIRED | 409 |
| ERR_EVENT_WINDOW_CONFLICT | 409 |
| ERR_EVENT_ALREADY_STARTED | 409 |
| ERR_WRONG_AMBASSADOR | 409 |
| ERR_INTERNAL | 500 |
