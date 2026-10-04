# Child Device Monitoring API — Product Requirements Document

## 1. Introduction

Families today face a difficult trade-off: children carry internet-connected devices that expose them to bullying, self-harm ideation, explicit material, and predatory contact, yet wholesale surveillance of a child's private messages is both ethically fraught and corrosive to trust. This document specifies the Child Device Monitoring platform, a REST API that lets parents connect a child's messaging, social, and email accounts with consent, analyzes the ingested content for risk signals, and delivers alerts to parents as short excerpts — never full message logs — so that privacy is preserved while genuinely dangerous situations surface.

The platform also carries obligations beyond the household. School districts may be linked to enrolled children, and in mandated-reporting jurisdictions a severe alert creates a legal reporting duty with a 24-hour deadline that the system must track, escalate, and close out. Managed devices enforce screen-time windows and web filtering, and the system detects bypass attempts (VPNs, secondary accounts, timezone shifts, uninstall attempts), escalating a device's posture from normal operation to watch status to full lockdown as strikes accumulate.

Because a platform like this operates on sensitive family data and legal deadlines, the API is built around explicit state machines, optimistic concurrency on the writes that matter, derived counters that must reconcile exactly with their underlying collections, and a logical clock that administrators can advance to exercise time-dependent behavior deterministically. This document is the complete and sole specification an implementer needs; it defines the response envelope, roles, state machines, calculations, validations, endpoints, and error catalogue for the entire surface.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted for the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). These two authentication checks run before any other validation on every endpoint.

Four roles exist, spelled exactly as follows:

- `PlatformAdmin` — the platform operator. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.
- `Parent` — a parent or guardian. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `ParentMember`; ownership checks on any resource that references a `ParentMember` or that belongs to the parent member's family compare the resource's family linkage to the family of the `ParentMember` identified by `X-User-ID`.
- `SchoolAdmin` — a school district administrator. When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is the `id` of the acting `District`; access to a child is permitted only when an `ACTIVE` `DistrictLink` connects that child to the district identified by `X-User-ID`.
- `DeviceAgent` — the on-device monitoring client. When `X-User-Role` is `DeviceAgent`, `X-User-ID` is the `id` of the acting `Device`; the agent may report content and bypass events only for its own device, so the `{id}` path parameter of the bypass-reporting endpoint must equal `X-User-ID`.

Cross-scope access is forbidden even when the role is otherwise allowed. A `Parent` attempting to read or mutate a resource that belongs to a different family is rejected with `ERR_CROSS_FAMILY_ACCESS` (HTTP 403). A `SchoolAdmin` attempting to access a child for whom their district has no `ACTIVE` `DistrictLink` is rejected with `ERR_CROSS_DISTRICT_ACCESS` (HTTP 403). A `SchoolAdmin` may only ever view alerts whose severity is `HIGH` or `SEVERE`; attempting to view an alert with severity `LOW` or `MODERATE` is rejected with `ERR_SEVERITY_VISIBILITY_DENIED` (HTTP 403).

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

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0. List responses always sort by `created_at` ascending unless a specific endpoint narrative states otherwise. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of matching records and `has_more` indicates whether further records exist beyond the returned window.

### 2.4. Common Resource Properties and the Logical Clock

Every entity in the system carries a server-minted `id` formatted as a UUID with no type prefix, plus `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that entity. All entities in this system carry the full common field set; no entity is exempt from `updated_at` or `version`.

Time inside the platform is governed by a logical clock, not wall-clock time. Before any administrative clock-setting call, the clock reads exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock. An administrator with the `PlatformAdmin` role sets the logical clock by supplying the target instant in the `to_iso8601` field; advancing the clock re-evaluates every device's bypass strike window and posture (a device whose strike count has decayed to zero automatically returns to the `NORMAL` posture), recomputes every access grant's status against the new time, and re-evaluates the overdue flag on every escalation case. Content timestamps (`occurred_at`) and bypass detection timestamps (`detected_at`) must never lie in the future relative to the logical clock; supplying one that does is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.5. Numeric Precision and Rounding

All risk scores, severity levels, strike counts, device counts, and counters in the system are integers. Where a calculation produces a fractional intermediate value — the per-day subscription rate is the only such case — the value is rounded half-up to the nearest integer at the step the relevant workflow narrative specifies. Money is always represented in integer cents. Deadline and timestamp arithmetic (such as the 24-hour legal reporting deadline) is second-exact.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two:

- Updating a child profile requires a non-optional `expected_child_version` field carrying the `version` of the `ChildProfile` the client last observed. If the value does not match the child profile's current `version` — because another write, such as a tuning change or an archive cascade, has advanced the profile since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Changing a family's subscription tier requires a non-optional `expected_family_version` field carrying the `version` of the `FamilyAccount` the client last observed. A mismatch against the family's current `version` — for example because another writer has just changed the tier or the family's state, which legitimately supersedes the prior billing view — is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the stale proration basis.

No other endpoint takes an expected-version field. Validation on these guarded writes evaluates the version check after authentication, authorization, existence, and scope checks, but before state-transition and business-rule checks.

### 2.7. Nested Resource Retrieval

Endpoints whose paths traverse a resource hierarchy validate path identifiers left to right: each identifier is resolved and checked for existence before the next identifier in the path is considered. Any identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404). After existence, scope checks apply — a `Parent` reaching into another family's subtree receives `ERR_CROSS_FAMILY_ACCESS`, and a `SchoolAdmin` reaching outside their district linkage receives `ERR_CROSS_DISTRICT_ACCESS` — so a caller can never distinguish "does not exist" from "exists but is out of scope" except through the distinct error codes above.

### 2.8. Derived Counters and Reconciliation

Several entities carry computed counters that must reconcile exactly with their underlying collections at all times. The `FamilyAccount.device_count` equals the number of devices across all children of the family whose `pairing_status` is `PAIRED`; pairing a device increases it by one and unpairing decreases it by one, a compensating pair that keeps the counter equal to the true count at every moment. The `FamilyAccount.open_escalation_count` equals the number of escalation cases for the family whose `case_status` is anything other than `CLOSED`. The `ChildProfile.open_alert_count` equals the number of the child's alerts whose `alert_status` is `DELIVERED`, `ACKNOWLEDGED`, or `REOPENED`; resolving an alert decreases it by one and reopening increases it by one, and a resolve followed by a reopen restores the prior value exactly. The `District.open_obligation_count` equals the number of the district's links whose `pending_legal_report` is true, and filing a legal report decreases it by one. The `Device.bypass_strike_count` counts the device's bypass events whose `detected_at` falls within the trailing fourteen-day window, inclusive at both edges.

### 2.9. Privacy Surface: Excerpts, Not Logs

The platform's founding privacy commitment is that parents and school administrators never see raw message text. The full `raw_text` of a content item is a restricted read surface: it is visible only to `PlatformAdmin` on the raw monitoring endpoints. Parents and school administrators interact with alerts, which carry only a truncated `excerpt_text` computed at alert creation. The `credential_token` supplied when connecting an external service is write-only: it is stored opaquely and never serialized in any response, to any role.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Family: Accounts, Parents, and Children

A family's journey begins when a `PlatformAdmin` creates the family account, supplying a `family_name`, the `primary_contact_email` used for billing and contact, and the `primary_parent_name` for the auto-created primary parent. Two optional inputs tune the account at creation: `subscription_tier`, one of `BASIC`, `STANDARD`, or `PREMIUM` (defaulting to `STANDARD` when omitted), and `analysis_variant`, one of `LEXICAL_V1` or `CONTEXTUAL_V2` (defaulting to `LEXICAL_V1`), which selects the risk-scoring variant applied to all content ingested for the family. Creation returns the new `FamilyAccount` with `account_status` set to `ACTIVE`, stamps `billing_period_start` at the current logical clock time, and sets `billing_period_end` exactly thirty days later. In the same operation the system creates the primary `ParentMember` with `is_primary` set to true and `member_status` `ACTIVE`; further parent members may be listed for a family through the family's parent-members collection, each carrying a `display_name` and `email`.

With the account in place, a `Parent` creates child profiles by submitting the `family_account_id`, the child's `display_name`, the child's `birth_year`, and optionally a `monitoring_sensitivity` of `LENIENT`, `STANDARD`, or `STRICT` (defaulting to `STANDARD`). The child's age is derived as the current clock year minus `birth_year`, and must fall between 0 and 17 inclusive; a `birth_year` implying a negative age or an age over 17 is rejected with `ERR_INVALID_REQUEST`. From the age, the system derives the child's `age_band`: `CHILD_9_UNDER` for age 9 or younger, `PRETEEN_10_12` for ages 10 through 12, `TEEN_13_15` for ages 13 through 15, and `OLDER_TEEN_16_17` for ages 16 and 17. The age band feeds severity classification and excerpt length elsewhere in this document, so it is recomputed whenever `birth_year` changes. A new profile starts with `profile_status` `ACTIVE` and an `open_alert_count` of zero.

### 3.2. Tuning, Archival, and the Child Update Contract

A `Parent` may update a child's tuning — a new `monitoring_sensitivity`, a corrected `birth_year` — through the child update operation, which also serves as the archival path: submitting `profile_status` set to `ARCHIVED` archives the child. Every update must carry `expected_child_version`, and a stale value is rejected with `ERR_STALE_VERSION` as described in §2.6. Any successful update increments the child's `version` by 1.

Archival is guarded. If any escalation case for the child has a `case_status` other than `CLOSED`, the archive is rejected with `ERR_ESCALATION_OPEN` — a family cannot archive a child out from under an open escalation. When archival succeeds, it cascades: every service connection of the child whose `consent_status` is `AWAITING_CONSENT`, `ACTIVE`, or `PAUSED` is moved to `REVOKED`, and the child's `version` increments. `ARCHIVED` is terminal; no transition leaves it, and attempting any further transition from it is rejected with `ERR_ALREADY_TERMINAL`.

Once a child is archived, child-scoped writes are blocked: consenting, resuming, or re-consenting a connection of an archived child is rejected with `ERR_CHILD_ARCHIVED`, as is district-link consent for an archived child.

### 3.3. Devices: Pairing, Unpairing, and the Tier Device Limit

Parents manage hardware by pairing devices to a child. Pairing requires the device's `platform` — one of `ANDROID`, `IOS`, or `CHROMEBOOK` — and a `nickname`, and creates the device with `pairing_status` `PAIRED` and `device_posture` `NORMAL`. Each new device increments the family's `device_count`, which at all times equals the number of `PAIRED` devices across all children of the family.

The subscription tier caps how many devices a family may have paired simultaneously: `BASIC` allows 2, `STANDARD` allows 5, and `PREMIUM` allows 10, and the family's computed `device_limit` always reflects the current tier. Pairing is permitted only while the family's `device_count` is strictly below its `device_limit`; a pair that would meet or exceed the limit is rejected with `ERR_DEVICE_LIMIT_EXCEEDED`. The same code guards downgrades: a tier change that would leave the family's `device_count` above the new tier's limit is rejected with `ERR_DEVICE_LIMIT_EXCEEDED`. Pairing also requires the family to be `ACTIVE` — a `SUSPENDED` family cannot pair, consent, or ingest, and any of these attempted against a suspended family is rejected with `ERR_FAMILY_SUSPENDED`.

Unpairing flips the device's `pairing_status` from `PAIRED` to `UNPAIRED`, recomputes the family's `device_count` down by one, and increments the device's `version`. `UNPAIRED` is terminal for a device: no transition returns it to `PAIRED`, and any attempt to drive another pairing-state transition on an unpaired device is rejected with `ERR_ALREADY_TERMINAL`. Certain operations also require the device to be `PAIRED` in the first place — re-enabling a screen-time window on an unpaired device, or reporting a bypass event for one, is rejected with `ERR_DEVICE_NOT_PAIRED`.

### 3.4. Service Connections and the Consent Lifecycle

Monitoring a child's messaging, social, or email presence begins when a `Parent` creates a service connection for the child, supplying the `service_type` (one of `MESSAGING`, `SOCIAL`, or `EMAIL`), the `external_handle` identifying the account on that service, and the `credential_token` granting access. The token is write-only and never appears in any response. A new connection starts in `AWAITING_CONSENT`.

At most one connection per combination of child, `service_type`, and `external_handle` may exist outside the `REVOKED` state. Creating a connection while another connection for the same child, service type, and handle is `AWAITING_CONSENT`, `ACTIVE`, or `PAUSED` is rejected with `ERR_DUPLICATE_CONNECTION`; once the earlier connection is `REVOKED`, the handle may be connected again.

Consent flows through the connection state operation, each accepted `to_status` describing one edge of a small cycle:

- From `AWAITING_CONSENT`, consenting moves the connection to `ACTIVE`. This requires the child to be `ACTIVE` (otherwise `ERR_CHILD_ARCHIVED`) and the family to be `ACTIVE` (otherwise `ERR_FAMILY_SUSPENDED`).
- From `ACTIVE`, pausing moves it to `PAUSED` with no further preconditions.
- From `PAUSED`, resuming moves it back to `ACTIVE`, requiring only that the child is still `ACTIVE` (`ERR_CHILD_ARCHIVED`).
- From either `ACTIVE` or `PAUSED`, revoking moves it to `REVOKED` with no further preconditions.
- From `REVOKED`, a re-consent flow returns it to `AWAITING_CONSENT`, again requiring the child to be `ACTIVE` (`ERR_CHILD_ARCHIVED`).

Every successful connection state change increments the connection's `version` by 1. Requesting a transition that does not exist from the connection's current state is rejected with `ERR_INVALID_STATE`. Only an `ACTIVE` connection accepts content ingestion; attempting to ingest content through a connection in any other state is rejected with `ERR_CONNECTION_NOT_ACTIVE`.

### 3.5. Content Ingestion and Risk Scoring

The on-device agent reports content by submitting a `service_connection_id`, the `occurred_at` timestamp of the content (which must not lie in the future relative to the logical clock, on pain of `ERR_INVALID_REQUEST`), a `direction` of `INBOUND` or `OUTBOUND`, the conversation's `thread_depth` (an integer of at least 1), a `signals` array whose entries each pair a `category` — one of `BULLYING`, `SELF_HARM`, `EXPLICIT`, or `PREDATORY_CONTACT` — with an integer `weight` between 1 and 100, and the full `raw_text`. Ingestion through a connection that is not `ACTIVE` is rejected with `ERR_CONNECTION_NOT_ACTIVE`, and ingestion for a suspended family is rejected with `ERR_FAMILY_SUSPENDED`.

At ingest, the system records `analysis_variant_used` by copying the family's current `analysis_variant`, and computes the content item's `risk_score` on a 0–100 integer scale using that variant. Both variants begin from the same base: the sum of the `weight` of every entry in the `signals` array, capped at 100. Under `LEXICAL_V1`, the `risk_score` is exactly that capped base — pure keyword weighting, with thread depth ignored. Under `CONTEXTUAL_V2`, the base is first multiplied by a thread-depth factor: one plus five-hundredths times the thread depth, where the depth used is the actual `thread_depth` or 5, whichever is smaller; the product is rounded half-up to the nearest integer and then capped at 100. A context-heavy thread therefore scores up to a quarter higher than the same signals in a shallow thread, but never above the cap.

### 3.6. Severity Classification and Alert Creation

Immediately after scoring, the system classifies severity on a four-step integer ladder. The base level comes from the `risk_score` alone: a score of at least 85 yields level 4 (`SEVERE`), a score from 60 to 84 inclusive yields level 3 (`HIGH`), a score from 30 to 59 inclusive yields level 2 (`MODERATE`), and anything below 30 yields level 1 (`LOW`). Two adjustments then apply. The age adjustment adds one level when the child's `age_band` is `CHILD_9_UNDER`, subtracts one level when the band is `OLDER_TEEN_16_17` and the dominant category is `EXPLICIT`, and adds nothing otherwise. The sensitivity adjustment adds one level when the child's `monitoring_sensitivity` is `STRICT`, subtracts one when it is `LENIENT`, and adds nothing when it is `STANDARD`. Separately, each dominant category imposes a floor: `PREDATORY_CONTACT` and `SELF_HARM` each floor the outcome at level 3, while `BULLYING` and `EXPLICIT` floor it at level 1. The final level is the larger of the adjusted base level and the dominant category's floor, clamped into the 1-to-4 range, and maps to `LOW`, `MODERATE`, `HIGH`, and `SEVERE` respectively. The dominant category is the signal entry with the greatest `weight`; ties break to the entry appearing earliest in the `signals` array.

An alert is created exactly when the resulting `severity` is `MODERATE`, `HIGH`, or `SEVERE`; the content item's `alert_created` flag records this, and its `alert_id` references the created alert, remaining null for suppressed `LOW` content. The alert is created in `DELIVERED` status, copies the `severity` from the content item, takes the dominant category as its own `category`, links back through `content_item_id`, and carries the excerpt described next. When the severity is `SEVERE`, the same ingest additionally opens an escalation case, as detailed in §3.8.

### 3.7. The Excerpt Rule

An alert's `excerpt_text` is a truncation of the content item's `raw_text`, computed once at alert creation. The character cap is 140, with one exception: when the child's `age_band` is `OLDER_TEEN_16_17` and the child's `monitoring_sensitivity` is `LENIENT`, the cap is 70 characters. If the raw text fits within the cap, the excerpt is the raw text unchanged. Otherwise, the system takes the leading characters of the raw text up to the cap; if that head contains a space, the head is cut back to end just before its last space; the excerpt is then that head followed by a single ellipsis character. The full `raw_text` is never exposed to `Parent` or `SchoolAdmin` under any circumstances.

### 3.8. Escalation Cases and Legal Reporting Obligations

A `SEVERE` alert always opens an escalation case in `OPEN` status, linked through the case's `alert_id` and the child's `child_profile_id`, with the alert's `escalation_case_id` pointing back (the field remains null for non-severe alerts). At case creation the system populates `crisis_resource_codes` from the alert's category: `SELF_HARM` maps to the codes `CRISIS_TEXT_LINE` and `988_LIFELINE`; `PREDATORY_CONTACT` maps to `NCMEC_CYBERTIPLINE`; `BULLYING` maps to `STOPBULLYING_GOV`; and `EXPLICIT` maps to `COMMON_SENSE_MEDIA`.

Case creation is also the moment the legal reporting clock may start. If an `ACTIVE` `DistrictLink` exists for the child whose district's `jurisdiction` is `MANDATED_REPORTING`, the case's `legal_report_due_at` is set to exactly 24 hours after the case's `created_at`, that link's `pending_legal_report` flips to true, and the case's `district_link_id` references the obligating link — when several links qualify, the one with the earliest `consented_at` is chosen. Without such a link, `legal_report_due_at` remains null. A case's `overdue` flag is computed as true precisely when `legal_report_due_at` is set, `legal_report_filed_at` is still null, and the current clock has passed the deadline; clock advancement re-evaluates this flag on every case.

The case lifecycle proceeds as follows. When the parent acknowledges the linked alert, an `OPEN` case automatically advances to `GUIDANCE_ISSUED`. From `GUIDANCE_ISSUED`, the parent may either move the case to `RESOURCE_REFERRED` or escalate it to `CRISIS_ESCALATED`. From `RESOURCE_REFERRED`, the parent closes the case directly into `CLOSED`, which recomputes the family's `open_escalation_count`. From `CRISIS_ESCALATED`, two exits exist: filing the legal report moves the case to `LEGAL_REPORTED`, or the parent closes the case directly — but only when no `ACTIVE` district link for the child carries a true `pending_legal_report`; attempting that close while a mandated report is still owed is rejected with `ERR_INVALID_ESCALATION_STEP`. Finally, from `LEGAL_REPORTED`, the case moves to `CLOSED`, again recomputing the family's `open_escalation_count`. `CLOSED` is terminal, and any further transition attempt on a closed case is rejected with `ERR_ALREADY_TERMINAL`. Any requested transition that does not correspond to an edge from the case's current state is rejected with `ERR_INVALID_ESCALATION_STEP` — this includes a role attempting a step it is not permitted to perform.

The legal-reporting steps have role restrictions. Filing the report — the move from `CRISIS_ESCALATED` to `LEGAL_REPORTED` — is permitted only to `SchoolAdmin` and `PlatformAdmin`, and it requires that an `ACTIVE` `MANDATED_REPORTING` district link for the child currently has `pending_legal_report` true; otherwise the attempt is rejected with `ERR_LEGAL_REPORT_NOT_REQUIRED`. Filing clears that link's `pending_legal_report` to false, stamps the case's `legal_report_filed_at` at the current clock time, and recomputes the district's `open_obligation_count` down by one. Closing a case from `LEGAL_REPORTED` is likewise restricted to `SchoolAdmin` and `PlatformAdmin`.

### 3.9. Working an Alert: Acknowledge, Resolve, Reopen

Parents work their alert queue through the alert state operation. From `DELIVERED`, acknowledging moves the alert to `ACKNOWLEDGED`; when the alert has a linked escalation case still `OPEN`, that case advances to `GUIDANCE_ISSUED` as part of the same action, and the child's `open_alert_count` is recomputed. From `ACKNOWLEDGED` or from `REOPENED`, resolving moves the alert to `RESOLVED` and recomputes the child's `open_alert_count` down by one — with one guard: resolving a `SEVERE` alert requires its linked escalation case to be `CLOSED` first, and is otherwise rejected with `ERR_ESCALATION_OPEN`. From `REOPENED`, acknowledging returns the alert to `ACKNOWLEDGED` with the count recomputed. From `RESOLVED`, reopening moves the alert to `REOPENED` and recomputes the count up by one. Requesting any transition that does not exist from the alert's current state is rejected with `ERR_INVALID_STATE`. Recall from §2.8 that the resolve-then-reopen pair restores the count exactly.

The alert feed supports two reading modes selected by the `variant` query parameter. The default, `IMMEDIATE`, surfaces each of a child's alerts whose `alert_status` is `DELIVERED`, `ACKNOWLEDGED`, or `REOPENED` and whose severity is `MODERATE`, `HIGH`, or `SEVERE`. The `DIGEST` variant applies the same status filter but admits only `HIGH` and `SEVERE` severities, dropping moderate noise from the periodic summary. Both variants exclude `RESOLVED` alerts entirely, and both sort the feed by `created_at` descending — the one list surface in the system that departs from the ascending default. The feed may be further narrowed with `child_profile_id`, `content_item_id`, or `alert_status` query parameters, alongside the usual `limit` and `offset`.

### 3.10. Screen-Time Windows and Web Filtering

Parents schedule device availability with screen-time windows, each defined by a `weekday` (one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`), a `start_minute` from 0 to 1439, an `end_minute` from 1 to 1440 that must be strictly greater than `start_minute`, and a `window_kind` of `BLOCKED` or `ALLOWED`. A window's minutes describe a half-open interval: it covers its start minute and every minute up to but not including its end minute. Bounds violations — a start minute outside 0 to 1439, an end minute outside 1 to 1440, or an end minute not greater than the start — are rejected with `ERR_INVALID_REQUEST`. Each window and grant belongs to its device through the recorded `device_id` back-reference, and each window carries a `window_status` of `ACTIVE` or `DISABLED`; new windows are created `ACTIVE`.

Two `BLOCKED` windows on the same device and weekday must never overlap: creating a `BLOCKED` window whose half-open interval intersects an existing `ACTIVE` `BLOCKED` window for the same device and weekday is rejected with `ERR_WINDOW_OVERLAP`. Because the intervals are half-open, adjacency is allowed — a window ending at minute 480 and another beginning at minute 480 do not overlap.

Windows may be disabled and later re-enabled through the window state operation. Disabling moves `ACTIVE` to `DISABLED` freely. Re-enabling moves `DISABLED` back to `ACTIVE` under two preconditions: the device must currently be `PAIRED` (otherwise `ERR_DEVICE_NOT_PAIRED`), and re-enabling a `BLOCKED` window must not recreate an overlap with another `ACTIVE` `BLOCKED` window on the same device and weekday (otherwise `ERR_WINDOW_OVERLAP`).

Separately, parents maintain web filter rules for a child, each a `rule_kind` of `CATEGORY_BLOCK`, `DOMAIN_BLOCK`, or `DOMAIN_ALLOW` paired with a `target` naming the category or domain pattern. Rules are created with `rule_status` `ACTIVE` (the alternative being `DISABLED`).

### 3.11. Bypass Detection, Device Posture, and Lockdown

Managed devices report their own tampering. The on-device agent reports a bypass event with a `bypass_kind` — one of `VPN`, `SECONDARY_ACCOUNT`, `TIMEZONE_SHIFT`, or `UNINSTALL_ATTEMPT` — and the `detected_at` timestamp, which must not lie in the future relative to the logical clock (`ERR_INVALID_REQUEST`). Reporting a bypass for a device that is not `PAIRED` is rejected with `ERR_DEVICE_NOT_PAIRED`.

Each device's `bypass_strike_count` counts its bypass events whose `detected_at` falls within the trailing fourteen days, inclusive at both edges — an event detected exactly fourteen days ago still counts. Each event's `counted_in_strikes` flag records whether it was within that window at the last evaluation. The count drives the device's posture: at least one strike puts the device into `BYPASS_WATCH`; at least three strikes put it into `LOCKDOWN`; and when clock advancement causes the count to decay back to zero, the device auto-heals from either `BYPASS_WATCH` or `LOCKDOWN` back to `NORMAL`. Posture is re-evaluated both when a bypass event is created and whenever the logical clock advances.

Entering `LOCKDOWN` has teeth: every access grant of the device whose `grant_status` is `SCHEDULED` or `ACTIVE` is moved to `CANCELLED` as part of the posture change. While a device is in `LOCKDOWN`, creating a new access grant for it is rejected with `ERR_DEVICE_LOCKED_DOWN`.

### 3.12. Temporary Access Grants

A parent may grant a temporary unlock window on a device by supplying `start_at` and `end_at` (a closed interval — both endpoints included — with `start_at` strictly before `end_at`; violations are rejected with `ERR_INVALID_REQUEST`) and an optional free-text `reason` that defaults to an empty string. Grants are created in `SCHEDULED` status. When the logical clock enters the interval — reaching a moment on or after `start_at` and on or before `end_at` — the grant becomes `ACTIVE`; when the clock passes `end_at`, an `ACTIVE` grant becomes `EXPIRED`, and a `SCHEDULED` grant whose window elapsed without the clock having entered it likewise becomes `EXPIRED`. Both `EXPIRED` and `CANCELLED` are terminal. As noted above, a device entering `LOCKDOWN` cancels all of its `SCHEDULED` and `ACTIVE` grants.

Grants on the same device must not collide. A new grant is rejected with `ERR_GRANT_CONFLICT` when its closed interval conflicts with an existing `SCHEDULED` or `ACTIVE` grant under padded closed-interval semantics: each existing grant is treated as though extended by a five-minute buffer on both sides, and any intersection between the new interval and a padded existing interval is a conflict.

### 3.13. Districts, Links, and Consent

A `PlatformAdmin` registers a school district with its `district_name`, `contact_email`, and `jurisdiction` — `MANDATED_REPORTING` or `DISCRETIONARY` — and the district starts with `district_status` `ACTIVE` (the alternative being `SUSPENDED`). A `SchoolAdmin` then requests visibility into a child by creating a district link carrying the target `child_profile_id`; the link records the owning district's `district_id` and starts with `link_status` set to `PENDING_CONSENT`. Link creation against a `SUSPENDED` district is rejected with `ERR_DISTRICT_SUSPENDED`.

Consent belongs to the parent. The parent's link state operation moves a link from `PENDING_CONSENT` to `ACTIVE`, which requires the district to be `ACTIVE` (otherwise `ERR_DISTRICT_SUSPENDED`) and the child to be `ACTIVE` (otherwise `ERR_CHILD_ARCHIVED`), and stamps the link's `consented_at` with the current clock time. Withdrawal moves a link from either `PENDING_CONSENT` or `ACTIVE` to `WITHDRAWN`, which is terminal; withdrawing an `ACTIVE` link is blocked while the link's `pending_legal_report` is true — a district with an outstanding mandated report cannot be quietly detached — and is rejected with `ERR_LINK_WITHDRAW_BLOCKED`. Recall from §3.8 that the link's `pending_legal_report` is set when a qualifying escalation case is created and cleared when the legal report is filed, and that the district's `open_obligation_count` tracks the number of its links with the flag set.

### 3.14. Subscription Changes and Proration

A `Parent` or `PlatformAdmin` may change a family's subscription tier by submitting the `new_tier` together with `expected_family_version`; a stale version is rejected with `ERR_STALE_VERSION` as described in §2.6, and a downgrade that would strand more paired devices than the new tier permits is rejected with `ERR_DEVICE_LIMIT_EXCEEDED`. Monthly pricing is 999 cents for `BASIC`, 1999 cents for `STANDARD`, and 2999 cents for `PREMIUM`, and each billing period spans 30 days.

The prorated charge for a mid-period change is computed with a pinned rounding order. First, each tier's per-day rate is computed by dividing its monthly cents by 30 and rounding half-up to the nearest integer cent — rounding happens at this per-day step, before anything is multiplied. Second, the remaining days are counted as the integer number of days from the current clock up to, but not including, `billing_period_end`. Third, the charge is the per-day rate of the new tier minus the per-day rate of the old tier, multiplied by the number of remaining days; on a downgrade this charge is negative, representing a credit. The result is recorded on the family as `last_proration_charge_cents` (which defaults to 0 when no tier change has ever occurred), the family's `device_limit` is recomputed against the new tier, and the family's `version` increments by 1.

### 3.15. Family Suspension

A `PlatformAdmin` may suspend or reactivate a family through the family state operation, moving `account_status` between `ACTIVE` and `SUSPENDED` in either direction; each transition increments the family's `version` by 1. Suspension is a gate, not a cascade: while `account_status` is `SUSPENDED`, pairing devices, consenting connections, and ingesting content are all rejected with `ERR_FAMILY_SUSPENDED`, but existing records, alerts, and cases remain readable and otherwise unaffected.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Creating a new resource returns HTTP 201 with the created resource in the response envelope's `data` field; modifications, state transitions, and reads return HTTP 200. Error responses follow the §2.2 error envelope with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/api/_clock/set_current_utc` | Set the logical clock; re-evaluates strikes, postures, grants, and overdue flags | PlatformAdmin |
| POST | `/api/families` | Create a family account and auto-create the primary parent member | PlatformAdmin |
| GET | `/api/families/{id}` | Get a family account | PlatformAdmin, Parent |
| POST | `/api/families/{id}/state` | Suspend or reactivate a family | PlatformAdmin |
| POST | `/api/families/{id}/subscription/changes` | Change subscription tier with proration; OCC-guarded | Parent, PlatformAdmin |
| GET | `/api/families/{id}/parents` | List parent members of a family | Parent, PlatformAdmin |
| GET | `/api/families/{id}/children` | List children of a family | Parent, PlatformAdmin |
| POST | `/api/children` | Create a child profile | Parent |
| GET | `/api/children/{id}` | Get a child profile | Parent, SchoolAdmin, PlatformAdmin |
| PATCH | `/api/children/{id}` | Update tuning or archive a child; OCC-guarded | Parent |
| GET | `/api/children/{id}/connections` | List service connections of a child | Parent, PlatformAdmin |
| POST | `/api/children/{id}/connections` | Create a service connection (starts AWAITING_CONSENT) | Parent |
| GET | `/api/children/{id}/filter-rules` | List filter rules of a child | Parent, PlatformAdmin |
| POST | `/api/children/{id}/filter-rules` | Create a filter rule | Parent |
| GET | `/api/children/{id}/district-links` | List district links of a child | Parent, SchoolAdmin, PlatformAdmin |
| GET | `/api/children/{id}/devices` | List devices of a child | Parent, PlatformAdmin |
| POST | `/api/children/{id}/devices/pair` | Pair a new managed device | Parent |
| GET | `/api/connections/{id}` | Get a service connection | Parent, PlatformAdmin |
| GET | `/api/connections/{id}/content-items` | List content items of a connection (raw monitoring surface) | PlatformAdmin |
| POST | `/api/connections/{id}/state` | Consent, pause, resume, revoke, or re-consent a connection | Parent |
| GET | `/api/devices/{id}` | Get a device | Parent, PlatformAdmin |
| POST | `/api/devices/{id}/unpair` | Unpair a device | Parent |
| POST | `/api/devices/{id}/screen-time-windows` | Create a screen-time window | Parent |
| GET | `/api/devices/{id}/screen-time-windows` | List screen-time windows of a device | Parent |
| POST | `/api/screen-time-windows/{id}/state` | Disable or re-enable a window | Parent |
| POST | `/api/devices/{id}/bypass-events` | Report a bypass event from the managed device | DeviceAgent |
| GET | `/api/devices/{id}/bypass-events` | List bypass events of a device | Parent, PlatformAdmin |
| POST | `/api/devices/{id}/access-grants` | Create a temporary unlock grant | Parent |
| GET | `/api/devices/{id}/access-grants` | List access grants of a device | Parent |
| POST | `/api/content-items` | Ingest a content item; scores risk, classifies severity, creates alert and (for SEVERE) escalation case | DeviceAgent |
| GET | `/api/content-items/{id}` | Get a content item (raw monitoring surface) | PlatformAdmin |
| GET | `/api/alerts/{id}` | Get an alert (excerpted view) | Parent, SchoolAdmin, PlatformAdmin |
| GET | `/api/alerts` | List alerts; variant and filter parameters per §3.9 | Parent, SchoolAdmin, PlatformAdmin |
| POST | `/api/alerts/{id}/state` | Acknowledge, resolve, or reopen an alert | Parent |
| GET | `/api/escalation-cases/{id}` | Get an escalation case | Parent, SchoolAdmin, PlatformAdmin |
| GET | `/api/escalation-cases` | List escalation cases | Parent, SchoolAdmin, PlatformAdmin |
| POST | `/api/escalation-cases/{id}/state` | Advance an escalation case; LEGAL_REPORTED restricted to SchoolAdmin/PlatformAdmin | Parent, SchoolAdmin, PlatformAdmin |
| POST | `/api/districts` | Create a district | PlatformAdmin |
| GET | `/api/districts/{id}` | Get a district | SchoolAdmin, PlatformAdmin |
| POST | `/api/districts/{id}/links` | Request a district link to a child (starts PENDING_CONSENT) | SchoolAdmin |
| GET | `/api/districts/{id}/links` | List links of a district | SchoolAdmin, PlatformAdmin |
| POST | `/api/district-links/{id}/state` | Parent consent (ACTIVE) or withdrawal (WITHDRAWN) | Parent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_CROSS_FAMILY_ACCESS` | 403 |
| `ERR_CROSS_DISTRICT_ACCESS` | 403 |
| `ERR_SEVERITY_VISIBILITY_DENIED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_FAMILY_SUSPENDED` | 409 |
| `ERR_CHILD_ARCHIVED` | 409 |
| `ERR_DEVICE_NOT_PAIRED` | 409 |
| `ERR_DEVICE_LIMIT_EXCEEDED` | 409 |
| `ERR_DEVICE_LOCKED_DOWN` | 409 |
| `ERR_CONNECTION_NOT_ACTIVE` | 409 |
| `ERR_DUPLICATE_CONNECTION` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_GRANT_CONFLICT` | 409 |
| `ERR_ESCALATION_OPEN` | 409 |
| `ERR_INVALID_ESCALATION_STEP` | 409 |
| `ERR_LEGAL_REPORT_NOT_REQUIRED` | 409 |
| `ERR_LINK_WITHDRAW_BLOCKED` | 409 |
| `ERR_DISTRICT_SUSPENDED` | 409 |
