# Legal Research Citator API — Product Requirements Document

## 1. Introduction

A legal research platform trades on two commodities: the speed with which raw primary law becomes citable, analyzable content, and the commercial discipline with which that content is licensed, metered, and paid for. This document specifies the Legal Research Citator API, a system that operates the full pipeline of a primary-law research service — from ingestion of court, legislature, and agency materials, through editorial enhancement and citation analysis, to subscription billing, secondary-source royalty settlement, and court-ordered retroactive removal.

Nine operator roles cooperate across four business concerns. A content operations track ingests raw documents, normalizes their citations into a canonical form, and publishes them into a citable corpus where every citation edge feeds a weighted citator signal. An editorial track layers attorney-authored headnotes, topic classifications, and synopses onto published law under strict segregation-of-duties review. A commercial track manages subscription plans, subscriber accounts, seat assignment, metered usage, invoicing with cost-recovery allocation, and royalty statements for licensed treatises and practice guides. A compliance track executes court sealing and removal orders that retroactively change what the database shows — and what the citator reports — while preserving an auditable, reversible trail. Every time-dependent rule in the system reads a single logical clock; wall-clock time is never consulted.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint. The entire API is mounted under the `/legal-research` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request whose headers are missing, blank, or whose `X-User-Role` value is not one of the declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The declared roles are `PlatformAdmin`, `ContentIngester`, `CitatorAnalyst`, `AttorneyEditor`, `LicensingManager`, `FirmAdmin`, `Researcher`, `BillingAdmin`, and `ComplianceOfficer`. Each endpoint admits a specific subset of these roles; a request whose role is not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403).

For two roles, `X-User-ID` is bound to a persisted entity. When `X-User-Role` is `FirmAdmin`, `X-User-ID` is the `id` of the acting SubscriberAccount; ownership checks on any resource that references a SubscriberAccount compare the resource's account field to `X-User-ID`, and a mismatch is rejected with `ERR_ACCOUNT_MISMATCH` (HTTP 403). This ownership comparison is applied only where an endpoint performs an ownership check — seat management (§3.5); list and read endpoints perform no account scoping. When `X-User-Role` is `Researcher`, `X-User-ID` is the `id` of the acting SubscriberUser, and metered activity is attributed to that user record. For the remaining seven roles — `PlatformAdmin`, `ContentIngester`, `CitatorAnalyst`, `AttorneyEditor`, `LicensingManager`, `BillingAdmin`, and `ComplianceOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as the author or reviewer of a Headnote) but never compares it to any entity's `id`. A headnote submission attempted by anyone other than its recorded author is rejected with `ERR_NOT_HEADNOTE_AUTHOR` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 — wall-clock time is never consulted.
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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and any value below 1 or above 100 is out of range — the minimum is 1 and the maximum is 100. The `offset` parameter says how many items to skip and defaults to 0. An out-of-range `limit`, a non-integer `limit` or `offset`, or a negative `offset` is a shape violation rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items on the returned page is below `total_count`.

### 2.4. The Logical Clock and Lazy Overdue Materialization

A single logical clock governs every time-gated rule in the system: overdue-invoice materialization, removal-order effective windows, and bulk-rate windows all read only this clock. At server startup the clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformAdmin` may advance it through a test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`. The setter accepts any well-formed ISO 8601 instant; it does not require the new reading to be later than the current one.

The clock's most consequential consumer is the billing lifecycle. `OVERDUE` is not pushed by any scheduler; it is materialized lazily. Before the system handles any request that reads or writes an invoice, or that reads or writes the subscription behind one, it first re-examines every invoice still in `ISSUED` status whose `due_at` is earlier than the current logical-clock reading, flips each such invoice to `OVERDUE`, and applies the subscription suspension cascade described in §3.6. Only after this sweep does the original request proceed, so a client never observes an `ISSUED` invoice whose due date has already passed.

### 2.5. Common Resource Properties

Nearly every resource in the system shares four system-managed properties:

- `id` — a server-minted UUID rendered in its canonical hyphenated string form (five hexadecimal groups of 8-4-4-4-12 characters, as produced by a standard UUID library's string conversion), with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource; at creation it equals `created_at`.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation, including mutations caused by system cascades such as a citator recompute or a removal-order fan-out.

Two resources are deliberate exceptions, behaving as immutable ledger entries rather than mutable records: a UsageEvent and a RoyaltyStatement each carry only `id` and `created_at`. Both `updated_at` and `version` are absent from them — a UsageEvent is never modified after recording, and a RoyaltyStatement's computed amount is immutable once written.

### 2.6. Citator Treatment Scoring

Every PrimaryDocument carries a computed `citator_score` and a computed `citator_signal`, and both are derived from the same eligible reference set: the CitingReference rows whose `cited_document_id` is the document in question, whose own `status` is `ACTIVE`, and whose citing document is both `PUBLISHED` and `PUBLIC`. References that fail any leg of that test contribute nothing. When no reference qualifies, the score is 0.

The score is a weighted sum over the eligible set, where each reference contributes a weight keyed by its `treatment` and its `depth`. The weight table is fixed platform-wide. An `OVERRULED` treatment contributes 100 points when `EXAMINED`, 80 when `DISCUSSED`, 50 when `CITED`, and 20 when `MENTIONED`. A `CRITICIZED` treatment contributes 60, 45, 25, and 10 points across those same four depths. A `QUESTIONED` treatment contributes 50, 35, 20, and 8. A `DISTINGUISHED` treatment contributes 20, 15, 8, and 3. A `FOLLOWED` treatment is favorable authority and subtracts: minus 30, minus 20, minus 10, and minus 4 across the four depths. A `CITED_NEUTRALLY` treatment contributes 0 at every depth.

The signal is then derived from the score by fixed thresholds. When the score reaches at least 80 the signal is `RED`; below that, a score of at least 40 yields `YELLOW`; anything lower — including negative scores — yields `GREEN`. This threshold derivation applies only while the document's `editorial_override_signal` is unset. When an analyst has pinned an override, the signal equals `editorial_override_signal` regardless of the score; the score continues to be computed and stored so that the underlying arithmetic stays visible. Both variants share the identical eligible set and the identical score, so an override that disagrees with the threshold result is the only way two documents with identical reference sets show different signals.

### 2.7. Monetary Precision and Rounding

All money in the system is represented as integer cents; no fractional-cent value is ever stored or returned. Three rounding disciplines apply, and each is pinned to a specific calculation. Invoice overage components are rounded half-up to whole cents per component before the components are summed — rounding the combined amount once instead would produce a different cent value, and the per-component order is the contract. Revenue-share royalty amounts are rounded half-up to whole cents after the basis-point multiplication. Cost-recovery allocations are computed with a floor first pass, and only the leftover cents are distributed afterward. The arithmetic details, including worked examples, live with the workflows in §3.6 and §3.7.

### 2.8. Optimistic Concurrency Control

Two write operations in the system legitimately supersede whatever value was there before, so no state field can protect them from a stale client; both are guarded by optimistic concurrency instead.

Pinning a citator override on a document requires the request to carry `expected_document_version`, holding the document `version` the client last observed. Because a new override supersedes any earlier override on the same document, a second write is never blocked by the first one's state — but when the document's `version` has advanced past the supplied value since the client last read it (another override, or a cascade recompute that landed meanwhile), the write is rejected as stale with `ERR_STALE_VERSION` (HTTP 412).

Changing a subscription's plan works the same way. The change-plan request must carry `expected_subscription_version` equal to the subscription's current `version`. Seat operations, suspensions, and earlier plan changes all bump that version, so a plan change built on an outdated read is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently overwriting a plan the client never saw. Endpoints not named here take no version field at all.

### 2.9. Validation Cascade and Error Priority

Every request passes a fixed cascade of checks, and the cascade's order is part of the contract: when several checks would fail, the earliest one determines which error the caller receives. Authentication comes first — a request with missing, blank, or undeclared headers is rejected with `ERR_UNAUTHENTICATED` before anything else is examined — followed by role authorization (`ERR_FORBIDDEN`), and then the ownership rules (`ERR_ACCOUNT_MISMATCH` on seat management, `ERR_NOT_HEADNOTE_AUTHOR` on headnote submission) — an ownership rule is evaluated against the already-resolved target resource, so when the path identifier itself does not resolve, the not-found error preempts the ownership check. Request-shape validation (`ERR_INVALID_REQUEST`) follows, covering missing required fields, enum values outside their domain, malformed dates, inverted windows and periods, non-positive seat counts, duplicate emails, and metered events that pair the wrong fields.

Only after the body is well-formed does the system resolve identifiers, in a fixed order: documents first (`ERR_DOCUMENT_NOT_FOUND`, which also covers entries of a publish payload's `references` list), then headnotes (`ERR_HEADNOTE_NOT_FOUND`), subscriptions (`ERR_SUBSCRIPTION_NOT_FOUND`), invoices (`ERR_INVOICE_NOT_FOUND`), users (`ERR_USER_NOT_FOUND`), removal orders (`ERR_ORDER_NOT_FOUND`), license agreements (`ERR_AGREEMENT_NOT_FOUND`), body-referenced plans (`ERR_PLAN_NOT_FOUND`), body-referenced accounts (`ERR_ACCOUNT_NOT_FOUND`), usage events (`ERR_USAGE_EVENT_NOT_FOUND`), and royalty statements (`ERR_STATEMENT_NOT_FOUND`). A document whose `visibility_status` is `REMOVED` surfaces at this same stage on reads: the single-document read and the citing-reference lookup fail with `ERR_DOCUMENT_REMOVED`, exactly as if the document did not exist. Write operations that reference the document — publishing, citator override, headnote creation, and removal-order docketing — resolve it normally and are governed only by their own state gates.

With every identifier resolved, current-state legality is evaluated: the generic transition check (`ERR_INVALID_STATE`) first, then the editorial document gates (`ERR_DOCUMENT_NOT_PUBLISHED` before `ERR_DOCUMENT_SEALED`), then `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_INVOICE_PERIOD_CLOSED`, `ERR_SEAT_ALREADY_HELD`, and `ERR_NO_SEAT_HELD`, in that order. Business-safety gates come next — segregation of duties (`ERR_REVIEWER_IS_AUTHOR`), bulk-rate limits (`ERR_BULK_RATE_EXCEEDED`), and scope enforcement (`ERR_USAGE_OUT_OF_SCOPE`) — followed by the business constraints in their pinned order: citation uniqueness (`ERR_DUPLICATE_CITATION`) before self-citation (`ERR_SELF_CITATION`) before citation-target publication (`ERR_CITATION_TARGET_NOT_PUBLISHED`); then `ERR_LICENSE_WINDOW_OVERLAP`, `ERR_REMOVAL_WINDOW_OVERLAP`, `ERR_SUBSCRIPTION_OVERLAP`, and stale optimistic-concurrency versions (`ERR_STALE_VERSION`). Referential rules follow (`ERR_MATTER_CODE_REQUIRED`, then `ERR_PLAN_ACCOUNT_INCOMPATIBLE`), and the fiscal seat-capacity check (`ERR_NO_SEATS_AVAILABLE`) is always the final gate, evaluated only after every state and safety check has passed.

### 2.10. Identifier Resolution and Reverse Reachability

For any request whose URL carries an identifier, the system validates identifiers left to right and rejects with the not-found error of the first identifier that fails to resolve. Collections are reachable in reverse through query-parameter filters rather than nested paths: the document list accepts `source_type`, `jurisdiction_code`, `ingestion_status`, and `visibility_status`; the headnote list accepts `document_id`, `author_editor_id`, and `status`; the subscription list accepts `account_id`, `plan_id`, and `status`; the user list accepts `account_id` and `seat_subscription_id`; the usage-event list accepts `subscription_id`, `user_id`, `license_agreement_id`, and `event_type`; the invoice list accepts `subscription_id` and `status`; the royalty-statement list accepts `license_agreement_id`; and the removal-order list accepts `document_id` and `status`. One listing rule deserves emphasis: documents whose `visibility_status` is `REMOVED` are excluded from list results unless the caller explicitly passes `visibility_status` with the value `REMOVED`. A filter whose value lies outside the field's enum domain is a shape violation rejected with `ERR_INVALID_REQUEST`; identifier-valued filters are not resolved and simply yield an empty page when nothing matches.

### 2.11. Interval Semantics Across the Domain

Four families of date windows appear in this system, and they do not all behave alike. Subscription contract periods, invoice billing windows, license exclusivity windows, and royalty settlement windows are all half-open: the start date is included and the end date is excluded, so a back-to-back neighbor whose start equals the prior window's end does not overlap it. Removal-order windows are the exception — they are closed intervals that include both `effective_from` and `effective_until`, and for them mere adjacency already counts as overlap. Internally, well-formedness of any window is part of request-shape validation: `window_start` must be earlier than `window_end`, `period_start` must be earlier than `period_end`, `effective_from` must be on or before `effective_until`, and `seats_total` must be a positive integer; violations are rejected with `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Ingesting Primary Law: From Raw Feed to Published Document

A `ContentIngester` introduces each piece of primary law by describing what arrived from the feed: a `source_type` of `COURT`, `LEGISLATURE`, or `AGENCY`; a `jurisdiction_code` such as US, CA9, or NY; a `document_type` of `CASE`, `STATUTE`, or `REGULATION`; the document's `title`; the `raw_citation_string` exactly as the source delivered it; and the `decision_date`, an ISO calendar date of the decision, enactment, or adoption. The new PrimaryDocument is born into a two-dimensional state: its `ingestion_status` starts at `RECEIVED` and its `visibility_status` starts at `PUBLIC`. These axes are independent — a document may be sealed while still `RECEIVED` and later published into the combination of `PUBLISHED` ingestion and `SEALED` visibility. While the document remains `RECEIVED`, its `normalized_citation` is null and its `published_at` is null; the derived citator fields `citator_score` and `citator_signal` begin with no qualifying references, so the score reads 0.

Publication is the act that makes a document citable, and a `ContentIngester` triggers it with a payload of `references` describing what the document cites. Each entry of `references` names a `cited_document_id`, an editorial `treatment` drawn from `OVERRULED`, `CRITICIZED`, `QUESTIONED`, `DISTINGUISHED`, `FOLLOWED`, or `CITED_NEUTRALLY`, and a `depth` of `EXAMINED`, `DISCUSSED`, `CITED`, or `MENTIONED`. Before the transition commits, the publishing document's `raw_citation_string` is normalized: leading and trailing whitespace is trimmed, the text is uppercased (ASCII), every period character is removed, and every run of internal whitespace is collapsed to a single space — so a raw string like "123 F.3d  456" emerges as "123 F3D 456". That canonical form is stored as `normalized_citation` and must be globally unique among all documents that have one; a collision is rejected with `ERR_DUPLICATE_CITATION` (HTTP 409).

The `references` payload is screened in the cascade order of §2.9. Every `cited_document_id` must resolve to an existing document, else `ERR_DOCUMENT_NOT_FOUND` (HTTP 404) — and this existence screen applies to the payload entries just as it does to the path identifier. An entry that points back at the publishing document itself is rejected with `ERR_SELF_CITATION` (HTTP 422). An entry whose target has not yet reached `PUBLISHED` ingestion status is rejected with `ERR_CITATION_TARGET_NOT_PUBLISHED` (HTTP 409). Publishing a document that is already `PUBLISHED` fails the transition's from-state requirement with `ERR_INVALID_STATE` (HTTP 409), and per §2.9 the duplicate-citation check fires before the self-citation check, which fires before the target-publication check.

When publication commits, the side effects fan out. The document's `ingestion_status` becomes `PUBLISHED`, its `published_at` is stamped from the logical clock, and its `version` increments by one. One CitingReference is created per `references` entry, each recording the publishing document's id as its `citing_document_id`, starting in `ACTIVE` status with `deactivated_by_order_id` null. The `references` list may be empty, and duplicate entries are not screened: each entry creates its own CitingReference row. CitingReference rows are created only by this cascade — no client endpoint creates or mutates them directly. Finally, every document named as a citation target has its `citator_score` and `citator_signal` recomputed under §2.6, and that recompute may itself change the cited document's signal and bump its `version`.

The citation graph is browsable in both directions from any document. Asking for a document's citing references with `direction` set to `FROM` returns the rows where this document cites others; `direction` set to `TO` returns the rows that cite this document, and a `status` filter narrows the result by reference status. Omitting `direction` returns the union of both directions — every reference in which the document is the citing or the cited side. Reading a single document returns it together with its derived citator fields — unless its `visibility_status` is `REMOVED`, in which case the read fails with `ERR_DOCUMENT_REMOVED` (HTTP 404) exactly as if the document did not exist, and the citing-reference lookup on such a document fails the same way.

### 3.2. The Citator: Signals, Scores, and Editorial Override

The citator's arithmetic is defined once in §2.6; what remains is the editorial workflow that can supersede it. A `CitatorAnalyst` who disagrees with a derived signal pins an editorial override by submitting an `override_signal` of `GREEN`, `YELLOW`, or `RED`, an optional free-text `rationale`, and the mandatory `expected_document_version` described in §2.8. A successful write stores the pin in the document's `editorial_override_signal` and records the reasoning in `editorial_override_rationale`, which always reflects the latest override and stays null until the first one; the `citator_signal` field then reports the pinned value under the EDITORIAL_OVERRIDE variant, while `citator_score` continues to be computed and stored from the live reference set. The document's `version` increments by one on every override.

Overrides supersede rather than conflict: a later pin replaces an earlier one without ceremony, which is precisely why the stale-version guard of §2.8 is the only defense against a client pinning a signal over a document it has not re-read. A mismatch between `expected_document_version` and the document's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Signal recomputation is triggered from three directions, and only these: the publication cascade of §3.1, which recomputes every newly cited document; the removal-order cascades of §3.8, which recompute a cited document each time one of its incoming references flips between `ACTIVE` and `INACTIVE`; and the override write described here. There is no path by which a client edits `citator_score` or `citator_signal` directly.

### 3.3. Editorial Enhancement: The Headnote Workflow

Attorney editors enrich published law through Headnotes. An `AttorneyEditor` drafts one against a document by supplying a `topic_code` — one of `LITIGATION`, `CORPORATE`, `TAX`, `IP`, `CRIMINAL`, or `FAMILY` — together with the `headnote_text` and a `synopsis_text` summarizing the document. The author's identity is never taken from the request body: the system copies `X-User-ID` into `author_editor_id` at creation. A new headnote starts in `DRAFT` status, with `reviewer_editor_id` and `review_note` both null until a first review decision is recorded. Creation itself asks only that the target document exist (`ERR_DOCUMENT_NOT_FOUND` otherwise); the heavier document-state gates wait for the workflow transitions.

When the author considers a draft ready, submitting it moves the headnote from `DRAFT` to `IN_REVIEW`. Submission is personal: if the caller's `X-User-ID` differs from the headnote's `author_editor_id`, the request is rejected with `ERR_NOT_HEADNOTE_AUTHOR` (HTTP 403). Submitting also requires the underlying document to be `PUBLISHED` and `PUBLIC` — a document still in `RECEIVED` ingestion yields `ERR_DOCUMENT_NOT_PUBLISHED` (HTTP 409), and one whose visibility is `SEALED` or `REMOVED` yields `ERR_DOCUMENT_SEALED` (HTTP 409), with the not-published check firing first per §2.9. A headnote not currently in `DRAFT` cannot be submitted (`ERR_INVALID_STATE`).

Review is a decision between two outcomes, expressed through a `decision` of `APPROVE` or `REJECT` with an optional `review_note`. Segregation of duties is absolute: the reviewer's `X-User-ID` must differ from `author_editor_id`, and a self-review is rejected with `ERR_REVIEWER_IS_AUTHOR` (HTTP 422). Either decision requires the headnote to be `IN_REVIEW` and the document to satisfy the same publication and visibility gates as submission. An approval moves the headnote to `PUBLISHED`; a rejection sends it back to `DRAFT`, and the author may revise and resubmit without limit — the loop between `DRAFT` and `IN_REVIEW` is unbounded. Both branches record `reviewer_editor_id` from the caller's header and store the supplied `review_note`, and each transition increments the headnote's `version` by one.

There is one further transition, and no editor can invoke it. When a compliance cascade seals or removes the underlying document (§3.8), every `PUBLISHED` headnote on that document flips to `RETRACTED`. `RETRACTED` is terminal — nothing transitions out of it, and reversing the removal order does not bring a retracted headnote back.

### 3.4. Commercial Onboarding: Plans, Accounts, and Subscriptions

The commercial side begins with a `LicensingManager` defining a SubscriptionPlan. A plan carries a display `name`; a `practice_area` scope of `LITIGATION`, `CORPORATE`, `TAX`, `IP`, `CRIMINAL`, `FAMILY`, or `ALL`; a `jurisdiction_scope` of `FEDERAL`, `STATE`, or `NATIONAL`; and a `firm_size_tier` of `SOLO`, `SMALL`, `MID`, or `LARGE`. The `billing_model` selects the pricing regime: `FLAT_RATE` means a monthly base fee plus included quotas plus overage charges, while `TRANSACTIONAL` means pure per-event fees with no base fee, no quotas, and no discount. Conditional fields follow the model: `monthly_fee_cents` is required for `FLAT_RATE` and ignored for `TRANSACTIONAL`; `included_searches`, `included_doc_views`, `overage_search_fee_cents`, `overage_doc_view_fee_cents`, `volume_discount_pct`, and `discount_threshold_overage_units` are `FLAT_RATE`-only inputs; `per_search_fee_cents` and `per_doc_view_fee_cents` are `TRANSACTIONAL`-only. The `scope_enforcement` flag chooses between `HARD`, which rejects out-of-scope usage outright, and `SOFT`, which records it flagged. Two booleans shape eligibility and billing behavior: `government_only` restricts subscription to government accounts, and `cost_recovery_allowed` permits subscriptions on the plan to bill usage back to client matter codes. Plans also carry the bulk-rate guardrails `bulk_hourly_limit` and `bulk_daily_limit`; when either is omitted it takes the platform default — 100 events per trailing sixty minutes and 500 events per UTC day respectively. Every other omitted numeric plan field defaults to 0, except `monthly_fee_cents`, which has no default and is stored as null when a `TRANSACTIONAL` plan omits it; a conditional field supplied against the wrong billing model is stored but never consulted. `volume_discount_pct` is expressed as a fraction, so a fifteen-percent discount is supplied as 0.15.

A `LicensingManager` also registers each SubscriberAccount with its `org_name`, an `account_type` of `LAW_FIRM`, `GOVERNMENT`, or `CORPORATE`, and the `cost_recovery_enabled` flag that obliges every usage event on the account to name a client matter.

Opening a Subscription binds an account to a plan for a contract period. The request names the `account_id`, the `plan_id`, an inclusive `period_start`, an exclusive `period_end`, and a positive `seats_total`. Both identifiers must resolve — an unknown plan yields `ERR_PLAN_NOT_FOUND` (HTTP 404) and an unknown account `ERR_ACCOUNT_NOT_FOUND` (HTTP 404). The contract period is half-open, and it must not overlap the period of any non-`CANCELLED` subscription of the same account; adjacency is fine — a new period whose `period_start` equals an existing period's `period_end` is allowed — but interior overlap is rejected with `ERR_SUBSCRIPTION_OVERLAP` (HTTP 409). Eligibility is enforced after the overlap check per §2.9: subscribing a `government_only` plan to an account whose `account_type` is not `GOVERNMENT` fails with `ERR_PLAN_ACCOUNT_INCOMPATIBLE` (HTTP 422). A new subscription starts `ACTIVE` with `suspension_reason` null and `seats_used` at zero; `seats_used` is never written directly but is always the count of SubscriberUser rows holding an `ACTIVE` seat on the subscription.

Plans change mid-contract. A `LicensingManager` changes the plan by naming a `new_plan_id` alongside the OCC field `expected_subscription_version` of §2.8; the subscription's `plan_id` adopts the new value for future invoices, its `version` increments by one, and a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). An unresolvable `new_plan_id` fails with `ERR_PLAN_NOT_FOUND`. The change is not gated on the subscription's status; only the version guard applies.

The subscription lifecycle itself is steered through a `target_status`. Suspending an `ACTIVE` subscription moves it to `SUSPENDED` and records a `suspension_reason` — `MANUAL` when a `LicensingManager` asks for it directly, `INVOICE_OVERDUE` when the billing cascade of §3.6 drives it. Suspension does not release seats; it only bars new usage, as §3.5 describes. Resuming returns the subscription from `SUSPENDED` to `ACTIVE` and clears `suspension_reason` to null; a manual resume is always allowed, while the system's automatic resume fires only when the reason is `INVOICE_OVERDUE` and no `ISSUED` or `OVERDUE` invoice remains on the subscription. Cancellation is available from either `ACTIVE` or `SUSPENDED` and is terminal: every seated user loses the seat (`seat_status` becomes `NONE`, `seat_subscription_id` is cleared, and `seats_used` falls to zero), every `DRAFT` invoice of the subscription is voided, `suspension_reason` is cleared to null, and `CANCELLED` admits no further transition. Any request that asks for a transition the current state does not list — cancelling a `CANCELLED` subscription, resuming an `ACTIVE` one, and so on — is rejected with `ERR_INVALID_STATE` (HTTP 409). Every successful lifecycle step increments the subscription's `version` by one.

### 3.5. Seat Management and Metered Usage

Subscribers consume seats, not the platform's operator roles. Seat administration belongs to the `FirmAdmin`, whose `X-User-ID` is the id of the SubscriberAccount it acts for; when that id does not match the account owning the target subscription, the request is rejected with `ERR_ACCOUNT_MISMATCH` (HTTP 403). Seat operations are expressed with an `action` of `ASSIGN` or `RELEASE`.

Assigning a seat is atomic with user creation: the `FirmAdmin` supplies a `user_email` and `user_full_name`, which the system stores on the new SubscriberUser as its `email` and `full_name`, with `account_id` copied from the seat-granting subscription's account — the user is created already holding an `ACTIVE` seat, its `seat_subscription_id` pointing at that subscription, and the subscription's `seats_used` rising by one. The supplied `user_email` must be unique within the account, and a duplicate is a shape violation rejected with `ERR_INVALID_REQUEST` (HTTP 400). Beyond shape, the gauntlet runs in the order of §2.9: the subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`, HTTP 409); the account must not already hold an `ACTIVE`-seated user under that same email (`ERR_SEAT_ALREADY_HELD`, HTTP 409); and only after every state and safety gate has passed does the capacity check fire — when `seats_used` has already reached `seats_total`, the assignment is rejected with `ERR_NO_SEATS_AVAILABLE` (HTTP 409). Releasing a seat is the mirror: the request names the `user_id` of an existing user (an unknown id fails with `ERR_USER_NOT_FOUND`, HTTP 404) whose `seat_status` must be `ACTIVE` on this very subscription, else `ERR_NO_SEAT_HELD` (HTTP 409). Release sets the user's `seat_status` to `NONE`, clears `seat_subscription_id` to null, and lowers `seats_used` by one. Either action increments the subscription's `version` by one, and both actions answer with `200 OK` carrying the updated subscription object. A SubscriberUser is created exclusively through seat assignment; there is no standalone user-creation capability.

Metered usage is the `Researcher`'s domain. Each usage event names an `event_type` of `SEARCH` or `DOC_VIEW` and a `practice_area_tag` from the six practice-area values, and may optionally carry a `license_agreement_id` — permitted only on a `DOC_VIEW` event, where it marks a view of a licensed secondary work; attaching it to a `SEARCH` is rejected with `ERR_INVALID_REQUEST`. The caller never names the subscription: the system derives the event's `subscription_id` from the acting user's `ACTIVE` seat and copies `X-User-ID` into the event's `user_id`. The event's `occurred_at` is stamped from the logical clock at creation and is immutable thereafter.

Recording an event passes a fixed gauntlet, evaluated in the priority order of §2.9. The subscription behind the seat must be `ACTIVE`, else `ERR_SUBSCRIPTION_NOT_ACTIVE` (HTTP 409). A referenced license agreement must still be `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). The event's `occurred_at` must not fall inside the billing window of any invoice of the same subscription that is `ISSUED`, `OVERDUE`, or `PAID`; such a period is closed and the event is rejected with `ERR_INVOICE_PERIOD_CLOSED` (HTTP 409) — note that a `DRAFT` invoice does not close its window. The acting user must actually hold an `ACTIVE` seat, else `ERR_NO_SEAT_HELD` (HTTP 409).

Two business-safety gates follow. The bulk-rate guard counts the acting user's prior events: those whose `occurred_at` lies within the trailing sixty-minute window `(now − 60 minutes, now]` — up to and including now, but excluding an event exactly sixty minutes old — and those falling on the current UTC calendar date. When the trailing-hour count has already reached the plan's `bulk_hourly_limit`, or the calendar-day count has already reached its `bulk_daily_limit`, the new event is rejected with `ERR_BULK_RATE_EXCEEDED` (HTTP 422); an event that merely brings either count up to the limit is still admitted, and only the one after it is refused. Scope enforcement then compares the event's `practice_area_tag` to the plan's `practice_area`: a match, or a plan scoped to `ALL`, records the event with `in_scope` true; a mismatch on a `SOFT` plan is recorded with `in_scope` false, while a mismatch on a `HARD` plan is rejected with `ERR_USAGE_OUT_OF_SCOPE` (HTTP 422). The `in_scope` flag is computed, never supplied. The final gate is referential: when the subscription's account has `cost_recovery_enabled` set, every event must carry a `matter_code`, and when it does not, the `matter_code` must be omitted entirely — either violation fails with `ERR_MATTER_CODE_REQUIRED` (HTTP 422).

### 3.6. Invoicing, Collections, and Cost Recovery

Billing begins when a `BillingAdmin` generates an invoice for a subscription and a billing window, naming the `subscription_id`, an inclusive `period_start`, and an exclusive `period_end`. Generation is refused with `ERR_INVOICE_PERIOD_CLOSED` (HTTP 409) when the window overlaps any existing non-`VOID` invoice of the same subscription — and for this purpose even a `DRAFT` invoice blocks overlap, in contrast to the usage-event rule of §3.5 where only issued-or-later windows close. Generation is not gated on the subscription's status — a suspended or cancelled subscription can still be invoiced for an open window. The new invoice snapshots the subscription's current plan: its `billing_model` field records whether the plan was `FLAT_RATE` or `TRANSACTIONAL` at generation time, and all quota and rate figures are read from that plan snapshot. The invoice is born `DRAFT`, with `issued_at` and `due_at` both null.

Totals are computed from the subscription's UsageEvent rows whose `occurred_at` falls inside the billing window, counting in-scope and out-of-scope events alike. The `search_count` tallies `SEARCH` events and `doc_view_count` tallies `DOC_VIEW` events. What happens next depends on the snapshot model.

On a `FLAT_RATE` plan, `base_fee_cents` is the plan's `monthly_fee_cents`. Overage units are the shortfall past the included quotas, never below zero: `overage_search_units` is however many searches exceed `included_searches`, and `overage_view_units` however many views exceed `included_doc_views`. When the two overage quantities together reach at least the plan's `discount_threshold_overage_units` — exactly at the threshold does qualify — the volume discount applies, and the rounding order is pinned: each component is rounded half-up to whole cents on its own, the search component being the overage search units times `overage_search_fee_cents` times one-minus-`volume_discount_pct`, the view component the overage view units times `overage_doc_view_fee_cents` times the same factor, and `overage_fee_cents` is the sum of the two rounded components. Summing first and rounding once is a different, forbidden calculation: three overage searches at 250 cents and three overage views at 105 cents under a 15 percent discount yield per-component results of 638 and 268 cents, an `overage_fee_cents` of 906, whereas rounding the combined 1065 times 0.85 once would yield 905. Below the threshold, no discount applies and each component is simply units times its overage fee. The invoice `total_cents` is `base_fee_cents` plus `overage_fee_cents`. A concrete walkthrough: a plan with a 5000-cent monthly fee, two included searches, one included view, overage fees of 250 and 105 cents, and a discount threshold the combined overage meets sees five searches and four views produce three overage searches and three overage views, an overage fee of 906 cents, and a `total_cents` of 5906.

On a `TRANSACTIONAL` plan there is no base fee, no quota, and no discount: `base_fee_cents`, `overage_search_units`, `overage_view_units`, and `overage_fee_cents` are all 0, and `total_cents` is the `search_count` times `per_search_fee_cents` plus the `doc_view_count` times `per_doc_view_fee_cents`. The same five searches and four views billed transactionally at, say, 300 cents per search and 120 cents per view total 1980 cents — identical usage, a different regime, a different bill.

When the subscription's account is cost-recovery enabled, the invoice additionally exposes a `cost_recovery_allocation`: one row per distinct `matter_code` in the window's event set, each row carrying its `matter_code`, its `event_count`, and an `amount_cents` share of the invoice total. Shares are apportioned by a waterfall. Each matter's raw share is the invoice `total_cents` multiplied by the matter's event count and divided by the total event count; every share is first floored to whole cents, and the leftover cents — the total minus the sum of the floored shares, always fewer than the number of matters — are distributed one cent at a time to matters ordered by event count descending, ties broken by `matter_code` ascending. The emitted allocation rows are ordered by `matter_code` ascending. With a 5906-cent invoice across matters M-A (four events), M-B (three), and M-C (two), the floored shares are 2624, 1968, and 1312 cents (summing to 5904), the remainder is 2 cents, and the final allocation reads M-A 2625, M-B 1969, M-C 1312. Accounts without cost recovery see an empty array.

Issuance is the point of no return for the window. Transitioning a `DRAFT` invoice to `ISSUED` stamps `issued_at` from the logical clock and sets `due_at` to `issued_at` plus the platform's standard net-terms period, `NET_TERMS_DAYS` (30) days; from that moment the period is closed, and any later usage event whose `occurred_at` falls inside the window is rejected with `ERR_INVOICE_PERIOD_CLOSED` per §3.5. Payment moves an invoice from `ISSUED` — or from `OVERDUE` — to `PAID`. Voiding moves an invoice from `DRAFT`, `ISSUED`, or `OVERDUE` to `VOID`; a voided invoice's `total_cents` stops counting toward the subscription's outstanding balance and toward any royalty revenue base (voiding a `DRAFT` invoice changes no balance, since drafts never counted). `PAID` and `VOID` are terminal, and any transition the current state does not list — paying a `DRAFT` invoice, voiding a `PAID` one, issuing twice — is rejected with `ERR_INVALID_STATE` (HTTP 409). Every transition increments the invoice's `version` by one.

Collections run through the lazy materialization of §2.4. When the logical clock passes an unpaid invoice's `due_at`, the next request that touches invoices or subscriptions flips it to `OVERDUE` and suspends the owning subscription — if still `ACTIVE` — with `suspension_reason` `INVOICE_OVERDUE`. Settlement in either direction (`PAID` or `VOID`) triggers the auto-resume evaluation: the subscription returns to `ACTIVE` when its suspension reason is `INVOICE_OVERDUE` and no `ISSUED` or `OVERDUE` invoice remains on it, clearing `suspension_reason` to null.

### 3.7. Licensing Secondary Sources and Settling Royalties

Treatises and practice guides enter the catalog through LicenseAgreements. A `LicensingManager` records the `work_title`, the `author_name` who receives royalties, the work's `practice_area`, and a `royalty_basis` selecting the settlement algorithm: `PER_VIEW` pays a fixed amount per viewing, while `REVENUE_SHARE` pays a fraction of invoiced revenue. The conditional fields follow the basis — `per_view_fee_cents` is required for `PER_VIEW` and ignored otherwise; `revenue_share_bps`, the royalty in basis points of the period revenue base, is required for `REVENUE_SHARE` and ignored otherwise. Each agreement runs for a half-open license window from the inclusive `window_start` to the exclusive `window_end`, starts in `ACTIVE` status, and carries an `exclusive` flag.

Exclusivity is where windows collide. Two agreements in the same `practice_area` that both carry the `exclusive` flag must not have overlapping windows: interior overlap is rejected with `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 409), while pure adjacency — one window's `window_end` equaling the other's `window_start` — is permitted under the half-open semantics of §2.11. Only `ACTIVE` exclusive agreements are consulted, and agreements without the exclusive flag never conflict with anything.

Termination ends an agreement's commercial life. A `LicensingManager` terminates an `ACTIVE` agreement into `TERMINATED` — the only transition, and terminal; repeating it or acting on a terminated agreement fails with `ERR_INVALID_STATE`. From termination onward, usage events carrying that `license_agreement_id` are refused with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409), and royalty generation against the agreement is refused the same way. Every termination increments the agreement's `version` by one.

Royalty settlement produces an immutable RoyaltyStatement. A `BillingAdmin` requests one by naming the `license_agreement_id` and a half-open settlement window from `period_start` to `period_end`. Generation requires the agreement to be `ACTIVE` and the settlement window to intersect the agreement's own license window; a terminated agreement, or a window falling entirely outside the license window, is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. The statement's `view_count` counts the `DOC_VIEW` usage events carrying that `license_agreement_id` whose `occurred_at` falls inside the settlement window. The amount then follows the basis. Under `PER_VIEW`, `revenue_base_cents` is 0 and `royalty_amount_cents` is simply the `view_count` times the agreement's `per_view_fee_cents`. Under `REVENUE_SHARE`, `revenue_base_cents` sums the `total_cents` of every invoice in `ISSUED` or `PAID` status whose own billing window overlaps the settlement window and whose subscription's plan `practice_area` equals the agreement's `practice_area` — voided, overdue, and draft invoices contribute nothing — and `royalty_amount_cents` is that base multiplied by `revenue_share_bps` and divided by ten thousand, rounded half-up to whole cents. The contrast is stark on identical traffic: three licensed views at 45 cents each settle at 135 cents under `PER_VIEW`, while a 250-basis-point share of a 5906-cent revenue base settles at 148 cents. Once written, `royalty_amount_cents` never changes.

### 3.8. Compliance: Sealing and Removal Orders

Court orders that retract content are docketed as RemovalOrders by a `ComplianceOfficer`. An order names its target `document_id`, a `scope` of `SEAL` — hide the content but keep the metadata — or `REMOVE` — withdraw the document retroactively — and a closed effective window from `effective_from` through `effective_until`, both dates inclusive, with an optional free-text `reason` carrying the court reference. Orders on the same document must not crowd each other: among orders still in `RECEIVED` or `APPLIED` status, any overlap of their closed windows is rejected with `ERR_REMOVAL_WINDOW_OVERLAP` (HTTP 409), and because the interval is closed, even adjacency — one order's `effective_until` equaling the next order's `effective_from` — already counts as overlap. A docketed order starts in `RECEIVED`.

Applying an order is what actually changes the database. The transition from `RECEIVED` to `APPLIED` requires the logical clock's current date to be on or after `effective_from` — an order may not be applied before its window opens — and requires the target document's `visibility_status` to be `PUBLIC`; an order arriving out of state or against a document no longer public is rejected with `ERR_INVALID_STATE` (HTTP 409). On application, the document's visibility leaves `PUBLIC`: to `SEALED` under a `SEAL` scope, to `REMOVED` under a `REMOVE` scope. The cascade that follows is identical for both scopes and runs four levels deep. Every CitingReference whose `citing_document_id` is the target document and whose `status` is still `ACTIVE` flips to `INACTIVE`, recording the order's id in `deactivated_by_order_id` and bumping its own `version`; each such flip recomputes the cited document's `citator_score` and `citator_signal` under §2.6; every `PUBLISHED` Headnote on the target document is retracted to `RETRACTED`, permanently; and the target document's `version` increments by one. A `REMOVE` scope adds one further consequence: subsequent single-document reads of the target fail with `ERR_DOCUMENT_REMOVED`, and the document vanishes from list results unless the caller explicitly filters `visibility_status` to `REMOVED` (§2.10).

Reversal compensates what compensation can reach. Moving an `APPLIED` order to `REVERSED` — the order's terminal state — restores the document's visibility from `SEALED` or `REMOVED` back to `PUBLIC` with the mirror cascade: every CitingReference whose `deactivated_by_order_id` equals this order's id flips back to `ACTIVE`, clears the field to null, and bumps its `version`, and each reactivation recomputes the cited document's citator fields, restoring the pre-apply values. Headnotes are the explicit exception: retraction is not compensated, and retracted headnotes remain `RETRACTED` after reversal. Each order transition increments the order's own `version` by one, and any transition outside the `RECEIVED`-to-`APPLIED`-to-`REVERSED` chain — re-applying an applied order, reversing a merely received one — fails with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — a document, headnote, plan, account, subscription, usage event, invoice, license agreement, royalty statement, or removal order — answer with `201 Created`. Operations that modify an existing resource or drive a state transition — publishing, overriding a signal, submitting or deciding a headnote, changing a plan or status, managing seats, transitioning an invoice or removal order, terminating an agreement, and setting the clock — answer with `200 OK`, as do all reads. The complete request and response shape of each operation is defined by the narratives of §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/legal-research/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/legal-research/documents` | Ingest a raw primary-law document | ContentIngester |
| GET | `/legal-research/documents` | List documents with filters | Any declared role |
| GET | `/legal-research/documents/{id}` | Read one document with derived citator fields | Any declared role |
| GET | `/legal-research/documents/{id}/citing-references` | Reverse lookup of citation edges by direction | Any declared role |
| POST | `/legal-research/documents/{id}/publish` | Normalize citation, publish, fan out references and citator recompute | ContentIngester |
| POST | `/legal-research/documents/{id}/citator-override` | Pin an editorial citator signal (OCC-guarded) | CitatorAnalyst |
| POST | `/legal-research/documents/{id}/headnotes` | Draft a headnote with topic classification and synopsis | AttorneyEditor |
| GET | `/legal-research/headnotes` | List headnotes with filters | Any declared role |
| GET | `/legal-research/headnotes/{id}` | Read one headnote | Any declared role |
| POST | `/legal-research/headnotes/{id}/submit` | Author submits a draft for review | AttorneyEditor |
| POST | `/legal-research/headnotes/{id}/decide` | Reviewer approves or rejects an in-review headnote | AttorneyEditor |
| POST | `/legal-research/plans` | Create a subscription plan | LicensingManager |
| POST | `/legal-research/accounts` | Create a subscriber account | LicensingManager |
| POST | `/legal-research/subscriptions` | Open a subscription for an account on a plan | LicensingManager |
| GET | `/legal-research/subscriptions` | List subscriptions with filters | LicensingManager, FirmAdmin, BillingAdmin |
| GET | `/legal-research/subscriptions/{id}` | Read one subscription including computed seats used | LicensingManager, FirmAdmin, BillingAdmin |
| PATCH | `/legal-research/subscriptions/{id}/change-plan` | Change the subscription's plan (OCC-guarded) | LicensingManager |
| POST | `/legal-research/subscriptions/{id}/status` | Suspend, resume, or cancel a subscription | LicensingManager |
| POST | `/legal-research/subscriptions/{id}/seats` | Assign or release a seat on the subscription | FirmAdmin |
| GET | `/legal-research/users` | List subscriber users with filters | LicensingManager, FirmAdmin |
| GET | `/legal-research/users/{id}` | Read one subscriber user | LicensingManager, FirmAdmin |
| POST | `/legal-research/usage-events` | Record a metered search or document view | Researcher |
| GET | `/legal-research/usage-events` | List usage events with filters | BillingAdmin, LicensingManager |
| GET | `/legal-research/usage-events/{id}` | Read one usage event | BillingAdmin, LicensingManager |
| POST | `/legal-research/invoices/generate` | Generate the draft invoice for a subscription and window | BillingAdmin |
| GET | `/legal-research/invoices` | List invoices with filters | BillingAdmin, LicensingManager, FirmAdmin |
| GET | `/legal-research/invoices/{id}` | Read one invoice with totals and allocation | BillingAdmin, LicensingManager, FirmAdmin |
| POST | `/legal-research/invoices/{id}/transition` | Issue, pay, or void an invoice | BillingAdmin |
| POST | `/legal-research/license-agreements` | License a secondary work with royalty terms | LicensingManager |
| GET | `/legal-research/license-agreements/{id}` | Read one license agreement | LicensingManager, BillingAdmin |
| POST | `/legal-research/license-agreements/{id}/terminate` | Terminate an active agreement | LicensingManager |
| POST | `/legal-research/royalty-statements/generate` | Generate the immutable royalty statement for a window | BillingAdmin |
| GET | `/legal-research/royalty-statements` | List royalty statements with filters | BillingAdmin, LicensingManager |
| GET | `/legal-research/royalty-statements/{id}` | Read one royalty statement | BillingAdmin, LicensingManager |
| POST | `/legal-research/removal-orders` | Docket a court sealing or removal order | ComplianceOfficer |
| GET | `/legal-research/removal-orders` | List removal orders with filters | ComplianceOfficer, PlatformAdmin |
| GET | `/legal-research/removal-orders/{id}` | Read one removal order | ComplianceOfficer, PlatformAdmin |
| POST | `/legal-research/removal-orders/{id}/transition` | Apply or reverse an order, executing the retroactive cascade | ComplianceOfficer |

## 5. Error Code Catalogue

The trigger condition for each error is defined where its workflow lives in §2 and §3; this catalogue is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_ACCOUNT_MISMATCH` | 403 Forbidden |
| `ERR_NOT_HEADNOTE_AUTHOR` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_HEADNOTE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_USER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_USAGE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_REMOVED` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DOCUMENT_NOT_PUBLISHED` | 409 Conflict |
| `ERR_DOCUMENT_SEALED` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVOICE_PERIOD_CLOSED` | 409 Conflict |
| `ERR_SEAT_ALREADY_HELD` | 409 Conflict |
| `ERR_NO_SEAT_HELD` | 409 Conflict |
| `ERR_NO_SEATS_AVAILABLE` | 409 Conflict |
| `ERR_REVIEWER_IS_AUTHOR` | 422 Unprocessable Entity |
| `ERR_BULK_RATE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_USAGE_OUT_OF_SCOPE` | 422 Unprocessable Entity |
| `ERR_MATTER_CODE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PLAN_ACCOUNT_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CITATION` | 409 Conflict |
| `ERR_SELF_CITATION` | 422 Unprocessable Entity |
| `ERR_CITATION_TARGET_NOT_PUBLISHED` | 409 Conflict |
| `ERR_LICENSE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REMOVAL_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SUBSCRIPTION_OVERLAP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
