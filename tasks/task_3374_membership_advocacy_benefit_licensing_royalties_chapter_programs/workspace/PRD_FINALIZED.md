# Membership Advocacy & Licensing API — Product Requirements Document

## 1. Introduction

A large membership organization serving older adults runs several operationally distinct businesses under one roof, and this API is the system of record for all of them. Members join as households, choose multi-year terms, and expect automatic renewal to just work; insurers and service companies pay royalties to license the organization's brand and reach its membership; a publications desk sells advertising against guaranteed circulation; hundreds of local chapters run volunteer-taught tax preparation and driver safety courses; and an advocacy operation mobilizes members behind federal and state campaigns. Each of these businesses has its own failure modes — lapsed standing, under-reported royalties, escalating member complaints, commingled funds between the charitable and lobbying arms, and misuse of member data for commercial targeting — and the requirements below exist to make those failure modes impossible to express through the API.

Two structural commitments run through every workflow in this document. First, a single server-held logical clock anchors every date- and time-derived rule: household standing, campaign windows, session lifecycles, trailing escalation counts, and calendar-year fiscal caps all read from it, never from wall-clock time, so behavior is fully deterministic and replayable. Second, money and authority are deliberately separated: the staff who request fund transfers never approve them, the provider staff who report royalty sales never finalize them, and every ledger movement conserves value across the accounts it touches. The result is an API where compliance boundaries are enforced structurally rather than by convention.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or naming a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Beyond authentication, every endpoint restricts which roles may call it, and certain action endpoints further restrict which role may supply which action; a caller whose role is not entitled to the endpoint or the requested action is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes ten roles:

- `PlatformAdmin` — system operator; drives the logical clock and the renewal batch, and holds read access across the surface.
- `MemberServicesAgent` — membership organization staff; runs enrollment, membership terms, chapter chartering, and reads member data.
- `Member` — an enrolled member acting as themselves.
- `ProviderManager` — staff of a benefit provider; manages that provider's own license agreements and royalty reports.
- `GovernanceOfficer` — organization governance staff; admits providers, drives the business side of the agreement lifecycle, creates legal entities, and requests fund transfers.
- `OversightAnalyst` — member-facing quality oversight; adjudicates complaints and drives agreement probation actions.
- `FinanceController` — organization finance; approves or rejects fund transfers (and never requests them) and finalizes royalty statements (and never submits them).
- `StandardsReviewer` — publication advertising standards and circulation desk.
- `ChapterCoordinator` — volunteer coordinator of one chapter; schedules its sessions and assists enrollments.
- `AdvocacyDirector` — advocacy campaigns and member mobilization.

The `X-User-ID` header binds to resources differently depending on the role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on member-scoped writes compare the request's `member_id` field to `X-User-ID`, so a member may file complaints and enroll in course sessions only as themselves — a mismatch is `ERR_FORBIDDEN`. When `X-User-Role` is `ProviderManager`, `X-User-ID` is the `id` of the acting `Provider`; drafting a license agreement compares it to the provider identified in the path, and submitting a royalty statement compares it to the provider that owns the target agreement — a mismatch is `ERR_FORBIDDEN`. When `X-User-Role` is `ChapterCoordinator`, `X-User-ID` is the `id` of the acting `Chapter`; creating a course session compares it to the chapter identified in the path — a mismatch is `ERR_FORBIDDEN`. For the seven remaining roles — `PlatformAdmin`, `MemberServicesAgent`, `GovernanceOfficer`, `OversightAnalyst`, `FinanceController`, `StandardsReviewer`, and `AdvocacyDirector` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `requested_by_user_id` or `decided_by_user_id` on a fund transfer) but never compares it to any entity's `id`.

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

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10 when not provided, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Derived State

Every date- and time-sensitive rule in the system reads from a single server-held logical clock, never from wall-clock time. At server startup, before any operator intervention, the clock reads exactly `2026-09-01T00:00:00Z`, and the server must not fall back to wall-clock time under any circumstances. A `PlatformAdmin`-only capability sets the clock: the request carries a `to_iso8601` timestamp and the response echoes the new reading as `current_utc`. Moving the clock re-anchors every lazily computed derivation in the system — campaign status, course-session status, household standing, member ages, trailing escalation windows, and calendar-year fiscal cap windows all derive from the new reading.

Several states are never stored as mutable fields at all; they are derived from the logical clock at read time. A household's `status`, each member's `in_good_standing` and `age_years`, a campaign's `computed_status`, a course session's `status`, a publication's `circulation_count`, and both escalation trailing counts are all recomputed whenever they are read, so advancing the clock is sufficient to change what any read returns.

### 2.5. Common Resource Properties

Every resource in the system — households, members, membership terms, providers, license agreements, royalty statements, complaints, legal entities, fund transfers, publications, ad bookings, chapters, course sessions, campaigns, and mobilization events — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

Mutation cascades count as mutations of every resource they touch. Cancelling a membership term, for example, increments the owning household's `version` and refreshes its `updated_at`, because the household's lifetime counters change; finalizing a royalty statement increments both the agreement's `version` and the provider's `version`; admitting a provider increments the provider's `version`. Clients watching a parent resource therefore always see its `version` advance when a child-side operation ripples into it.

### 2.6. Money, Integer Cents, and Rounding Discipline

All monetary values in the system are integers denominated in cents — dues, refunds, royalties, entity balances, transfer amounts, rate-card bounds, and advertising estimates alike. No floating-point money ever appears on the wire or in storage.

Rounding rules are pinned per calculation and differ deliberately. Membership pricing rounds half up exactly once, at the end of the formula. Cancellation refunds round the per-month basis half up first and only then multiply by whole months — rounding only the final product is a different, incorrect algorithm. Royalty tier computations round half up exactly once per statement. Governance caps truncate (round down) to whole cents before the comparison is made. Advertising cost estimates round half up once. Where a comparison against a cap or threshold is involved, the comparison is always "no more than" or "at least" exactly as stated — a value landing precisely on a boundary passes or fires exactly as the inclusive reading implies.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are protected by optimistic concurrency control, and they are the only two endpoints that accept a version field at all.

Drafting a license agreement under a provider (`POST /api/providers/{id}/license-agreements`) requires a non-optional `expected_provider_version` field carrying the client's last observed `version` of that provider. If the value does not match the provider's current `version`, the request is rejected with `ERR_STALE_PROVIDER_VERSION` (HTTP 412). This captures the case where another writer has just drafted an agreement — an act which itself mutates the provider's `version` — so the current writer's view of the provider, including its admission state and existing category coverage, is stale.

Submitting a royalty statement under a license agreement (`POST /api/license-agreements/{id}/royalty-statements`) requires a non-optional `expected_agreement_version` field carrying the client's last observed `version` of that agreement. If the value does not match the agreement's current `version`, the request is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). A submission for a quarter that already holds a provisional statement legitimately supersedes that statement, so a client holding a stale agreement version would unknowingly overwrite a fresher submission; the stale write is rejected instead of racing the supersede.

No other endpoint takes a version field; all other writes proceed without an OCC check.

### 2.8. Validation Pipeline and Error Precedence

Every request passes through a fixed twelve-rung validation pipeline, evaluated in the order below. A request that would fail several rungs is rejected with the error from the earliest rung it fails.

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is declared; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization.** The role is listed for the endpoint, and on action endpoints the role owns the requested action — agreement transitions restrict `ACTIVATE` and `TERMINATE` to `GovernanceOfficer` and restrict `PROBATE` and `REINSTATE` to `OversightAnalyst`; otherwise `ERR_FORBIDDEN` (HTTP 403).
3. **Entity-backed ownership.** For the entity-backed roles, the caller acts on its own resource: `ProviderManager`'s `X-User-ID` equals the path provider id on agreement and statement writes, `ChapterCoordinator`'s equals the path chapter id on session creation, and `Member`'s equals the body's `member_id` on complaint filing and enrollment; otherwise `ERR_FORBIDDEN` (HTTP 403).
4. **Segregation of duties.** A fund transfer's approver is not its requester; otherwise `ERR_SELF_APPROVAL` (HTTP 403).
5. **Request schema.** Required fields are present, enum values are valid, dates parse, ranges are not inverted (`effective_to` strictly after `effective_from`, `end_time` strictly after `start_time`, `max_cpm_cents` at least `min_cpm_cents`, campaign `end_date` on or after `start_date`), conditional fields hold (`state_code` present exactly when a campaign's `level` is `STATE`, `secondary_date_of_birth` present exactly when `secondary_full_name` is supplied), and no unknown `audience_spec` keys appear; otherwise `ERR_INVALID_REQUEST` (HTTP 400).
6. **Existence.** Path identifiers exist, validated left to right, followed by body-supplied foreign keys (`member_id`, `license_agreement_id`, `sponsor_entity_id`, `from_entity_id`, `to_entity_id`); otherwise `ERR_NOT_FOUND` (HTTP 404).
7. **Optimistic concurrency.** The two OCC-guarded writes match their expected versions; otherwise `ERR_STALE_PROVIDER_VERSION` or `ERR_STALE_AGREEMENT_VERSION` (HTTP 412).
8. **Target-resource state.** The addressed resource is in a state that permits the operation: term `ACTIVE` for cancellation (`ERR_TERM_NOT_ACTIVE`), agreement transition valid from the current status (`ERR_AGREEMENT_STATE`), statement `PROVISIONAL` for finalization (`ERR_STATEMENT_NOT_PROVISIONAL`), complaint transition valid from the current status (`ERR_COMPLAINT_STATE`), transfer `PENDING_APPROVAL` for a decision (`ERR_TRANSFER_STATE`), session still open for enrollment (`ERR_ENROLLMENT_CLOSED`); all HTTP 409.
9. **Cross-entity state.** Related resources are in required states: provider `LICENSED` for agreement creation, activation, and reinstatement (`ERR_PROVIDER_NOT_LICENSED`); campaign `ACTIVE` for mobilization (`ERR_CAMPAIGN_NOT_ACTIVE`); member in good standing for complaint filing and enrollment (`ERR_MEMBER_NOT_ACTIVE`); all HTTP 409.
10. **Eligibility and compliance.** The primary member is old enough (`ERR_AGE_INELIGIBLE`), the transfer direction is permitted (`ERR_PROHIBITED_ENTITY_PAIR`), the campaign sponsor is the lobbying arm (`ERR_SPONSOR_KIND_INVALID`), the mobilization audience is free of benefit-marketing keys (`ERR_DATA_USE_RESTRICTED`), and the ad category passes advertising standards (`ERR_AD_CATEGORY_RESTRICTED`); all HTTP 422.
11. **Business constraints.** Term length is one of the allowed values (`ERR_INVALID_TERM_YEARS`, 422); legal-entity kinds stay unique (`ERR_ENTITY_KIND_EXISTS`, 409); the activation window contains the clock date (`ERR_AGREEMENT_NOT_IN_WINDOW`, 422); category coverage stays unique (`ERR_DUPLICATE_CATEGORY_AGREEMENT`, 409); no quarter is reported twice after finalization (`ERR_QUARTER_ALREADY_FINALIZED`, 409); reinstatement thresholds have cleared (`ERR_REINSTATE_BLOCKED`, 422); room and instructor schedules stay conflict-free (`ERR_SESSION_OVERLAP`, 409; `ERR_INSTRUCTOR_DOUBLE_BOOKED`, 409); enrollment stays unique (`ERR_ALREADY_ENROLLED`, 409) and within capacity (`ERR_SESSION_FULL`, 409).
12. **Fiscal checks, in pinned order.** Transfer amount against the source balance (`ERR_INSUFFICIENT_ENTITY_BALANCE`, 422), then the per-transfer cap (`ERR_PER_TRANSFER_CAP_EXCEEDED`, 422), then the annual caps (`ERR_ANNUAL_CAP_EXCEEDED`, 422); for advertising, the rate card first (`ERR_RATE_CARD_VIOLATION`, 422) and then the circulation base (`ERR_NO_CIRCULATION_BASE`, 422).

### 2.9. Nested Resource Retrieval

Requests that target a resource nested under another are validated strictly left to right along the path. The system confirms the parent identifier exists before it ever looks at the child segment, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404) immediately, without examining later segments. A request addressed to the agreements of a provider that does not exist, for instance, fails on the provider segment regardless of whether the agreement id would have resolved.

### 2.10. Segregation of Duties Across the Organization

Authority over money and oversight is split so that no single role both initiates and ratifies a sensitive act. A `GovernanceOfficer` requests fund transfers but can never decide them; a `FinanceController` decides them but can never request one — and the decision-maker's `X-User-ID` must additionally differ from the requester's recorded `requested_by_user_id`, enforced per transfer rather than per role. Provider staff (`ProviderManager`) report quarterly royalty sales, but only the organization's `FinanceController` finalizes a statement against audited figures. Agreement probation and reinstatement belong to `OversightAnalyst`, while activation and termination belong to `GovernanceOfficer`, so the business side of licensing cannot clear its own quality findings.

### 2.11. Member Data Usage Restrictions

Member data may never be used for benefit marketing. Mobilization audiences may filter members only by geography and age — the `audience_spec` keys `state_code` and `min_age` are the complete allow-list. The three benefit-marketing keys `owns_licensed_product`, `benefit_product_category`, and `provider_customer` are forbidden outright and their presence is rejected with `ERR_DATA_USE_RESTRICTED` (HTTP 422); any other key is simply malformed and rejected with `ERR_INVALID_REQUEST` (HTTP 400). Independently, any member may set `benefit_marketing_opt_out`, and an opted-out member is excluded from every mobilization audience snapshot regardless of the filter supplied.

## 3. Business Logic & Workflows

### 3.1. Enrolling Households and Pricing Membership

Enrollment begins with the household. A `MemberServicesAgent` creates a household, its primary member, an optional secondary member, and the initial membership term in a single atomic operation — if any part fails validation, nothing is persisted. The payload carries the household's `state_code`, the desired `term_years`, and the primary applicant's `primary_full_name` and `primary_date_of_birth`; it may also carry `auto_renew_enabled` (defaulting to `false` when omitted), `primary_benefit_marketing_opt_out` (defaulting to `false`), and the optional trio `secondary_full_name`, `secondary_date_of_birth`, and `secondary_benefit_marketing_opt_out`. Supplying `secondary_full_name` without `secondary_date_of_birth` — or a birth date without a name — is a conditional-field violation rejected with `ERR_INVALID_REQUEST`.

Age eligibility gates the whole enrollment. The system computes the primary applicant's `age_years` as the whole years between `primary_date_of_birth` and the logical clock date, with a birthday falling exactly on the clock date counting as reached. The primary member must be at least 50 years old; a younger applicant is rejected with `ERR_AGE_INELIGIBLE` (HTTP 422), while an applicant whose 50th birthday falls exactly on the enrollment date is eligible. This eligibility gate is evaluated before the term-length constraint, so an under-age applicant with an invalid term length hears about age first. The term length itself must be exactly 1, 3, or 5 years — any other `term_years` value is rejected with `ERR_INVALID_TERM_YEARS` (HTTP 422).

Pricing is household-level and rewards commitment. Annual base dues are 1,600 cents (sixteen dollars) per year. Multi-year terms earn a discount of 0% for one year, 10% for three years, or 20% for five years; a term created by the renewal batch adds a further 5 percentage points of loyalty discount. The combined discount is capped at 25% — a five-year renewal reaches exactly the cap and no more. The price charged, recorded as the term's `paid_cents`, is the base annual dues multiplied by the number of years and then by one minus the effective discount, rounded half up exactly once at the end to integer cents. A five-year initial purchase therefore costs 6,400 cents, and a five-year renewal costs 6,000 cents. A secondary member adds 0 cents: household pricing covers up to two members at no additional charge.

The created member records carry `full_name`, `date_of_birth`, and `benefit_marketing_opt_out` taken from the correspondingly prefixed payload fields, a `role_in_household` of `PRIMARY` or `SECONDARY` derived from which creation slot each occupies, and a `household_id` back-reference to the owning household — members are only ever created through household enrollment. The household in turn records `primary_member_id` and `secondary_member_id`, the latter null when no secondary member was supplied. The initial term starts `ACTIVE` with `is_renewal` false, its `start_date` set to the clock date at purchase, its `end_date` set to the start date advanced by `term_years` years, and its `purchased_at` stamped from the logical clock. Coverage is a half-open window: the start date is covered and the end date is not. The household's `lifetime_collected_cents`, which starts at 0, accumulates the new term's `paid_cents`. A successful enrollment returns the household with HTTP 201.

### 3.2. Renewal, Lapse, Cancellation, and Household Standing

A household's `status` is a derived value, never stored as a mutable field: it is `ACTIVE` when at least one of the household's membership terms is itself `ACTIVE` and covers the current clock date — `start_date` on or before the clock date and the clock date strictly before `end_date` — and `LAPSED` otherwise. The derivation is recomputed whenever any term of the household changes status, whenever the renewal batch runs, and on every read of the household. Every member's `in_good_standing` simply mirrors the household's standing — true exactly when the household is `ACTIVE` — and is recomputed at the same moments.

The renewal batch is a `PlatformAdmin`-driven sweep with no request body. It visits every `ACTIVE` membership term whose `end_date` is on or before the current clock date and splits them by household preference. When the household's `auto_renew_enabled` is true, the expiring term transitions `ACTIVE` → `RENEWED` and a fresh term is created seamlessly: `is_renewal` true, `start_date` equal to the old term's `end_date`, `end_date` advanced by `term_years` years from there, priced by the standard schedule including the loyalty discount, with the household's `lifetime_collected_cents` growing by the new term's `paid_cents`. When `auto_renew_enabled` is false, the expiring term transitions `ACTIVE` → `LAPSED` with no successor. After the sweep, each touched household's standing is recomputed — a renewed household stays `ACTIVE` because the new term covers the clock date, while a non-renewed household becomes `LAPSED` if no other covering term exists — and every member's `in_good_standing` follows. The batch response tallies the run as `renewed_count`, `lapsed_count`, `renewed_term_ids`, and `lapsed_term_ids`.

Cancellation is a `MemberServicesAgent` act on an individual term, supplying a `reason` of `VOLUNTARY` or `DECEASED` (any other value is `ERR_INVALID_REQUEST`). Only an `ACTIVE` term can be cancelled; a term already `RENEWED`, `LAPSED`, or `CANCELLED` is rejected with `ERR_TERM_NOT_ACTIVE` (HTTP 409). The refund computation first derives `months_used`, the count of calendar months started including the cancellation month itself: the year difference times twelve, plus the month difference, plus one — the day of the month is irrelevant, because the current month is always consumed. Two refund variants then diverge by reason. Under `VOLUNTARY`, a short-rate clawback applies: the refund is the greater of zero and `paid_cents` minus `months_used` times 133 cents, where 133 is the undiscounted monthly basis — the base annual dues of 1,600 cents divided by twelve and rounded half up — so the multi-year discount is clawed back. Under `DECEASED`, the estate keeps the discount: the effective monthly rate is `paid_cents` divided by the term's total months and rounded half up, and the refund is the lesser of `paid_cents` and the remaining months multiplied by that rate. The rounding order is pinned in both variants — the per-month basis is rounded half up first and only then multiplied by whole months. A one-year term purchased at 1,600 cents and cancelled as `DECEASED` in its third calendar month, for example, refunds nine months at 133 cents — 1,197 cents — not the 1,200 cents that rounding only the final product would yield.

A successful cancellation records `refunded_cents` (which is 0 on any term until it is cancelled), `cancel_reason`, and `cancelled_at` stamped from the logical clock, and moves the term to `CANCELLED`. The household's `lifetime_refunded_cents`, which starts at 0, grows by the refund; this cascade mutation increments the household's `version` and refreshes its `updated_at`. Household standing is then recomputed — cancelling the household's only covering term typically flips it to `LAPSED` — and each member's `in_good_standing` follows. The operation returns the updated term with HTTP 200.

### 3.3. Licensing Benefit Providers and Managing Agreements

Benefit providers are onboarded by governance. A `GovernanceOfficer` registers a provider with its `legal_name`; the provider begins life as an `APPLICANT` with a `royalty_balance_cents` of 0. Admission by a `GovernanceOfficer` moves the provider `APPLICANT` → `LICENSED`, incrementing the provider's `version` by one. The same admission action serves re-admission after a suspension: a `SUSPENDED` provider may return to `LICENSED` only when its `escalations_trailing_12mo` has fallen below 5 at readmission time — otherwise the attempt is rejected with `ERR_REINSTATE_BLOCKED` (HTTP 422). Re-admission deliberately does not rehabilitate the provider's agreements: any agreement sitting in `PROBATION` stays there until its own reinstatement action clears it.

License agreements are drafted by the provider's own staff. A `ProviderManager` whose `X-User-ID` matches the provider in the path — a mismatch is `ERR_FORBIDDEN` — submits `product_category`, `effective_from`, `effective_to`, and `expected_provider_version`. The category must be one of `INSURANCE_HEALTH`, `INSURANCE_AUTO`, `INSURANCE_LIFE`, `FINANCIAL_SERVICES`, `TRAVEL_SERVICES`, or `HOME_SERVICES`, and the window must open strictly before it closes: an `effective_to` on or before `effective_from` is `ERR_INVALID_REQUEST`. Validation runs schema first, then existence, then the OCC check described in §2.7, then provider standing, then category uniqueness. The provider must be `LICENSED` — drafting against an `APPLICANT` or `SUSPENDED` provider is rejected with `ERR_PROVIDER_NOT_LICENSED` (HTTP 409). Category coverage must be unique at draft time: if a `DRAFT` or `ACTIVE` agreement already exists for the same provider and `product_category`, the draft is rejected with `ERR_DUPLICATE_CATEGORY_AGREEMENT` (HTTP 409). A successful draft is created in `DRAFT` status with `probation_count`, `recognized_royalty_cents`, and `provisional_outstanding_cents` all at 0, records its `provider_id`, and — because drafting is a provider mutation — increments the provider's `version` by one. This increment is exactly what makes a second drafter working from a stale provider read fail its OCC check. Creation returns HTTP 201, and the provider's agreement listing supports an optional `status` filter.

Once drafted, an agreement's lifecycle is driven through a single transition capability carrying an `action` of `ACTIVATE`, `PROBATE`, `REINSTATE`, or `TERMINATE`, with the role split described in §2.1 and §2.10. Activation (`ACTIVATE`, `GovernanceOfficer` only) moves `DRAFT` → `ACTIVE` and is the most heavily gated transition: the provider must be `LICENSED` (otherwise `ERR_PROVIDER_NOT_LICENSED`), the current clock date must lie within the agreement's window with both bounds inclusive — `effective_from` on or before the clock date and the clock date on or before `effective_to`, otherwise `ERR_AGREEMENT_NOT_IN_WINDOW` (HTTP 422) — and no other `ACTIVE` agreement may already exist for the same provider and category, otherwise `ERR_DUPLICATE_CATEGORY_AGREEMENT`. Probation (`PROBATE`, `OversightAnalyst` only) moves `ACTIVE` → `PROBATION` with no preconditions beyond the state itself, incrementing `probation_count` by one. Reinstatement (`REINSTATE`, `OversightAnalyst` only) moves `PROBATION` → `ACTIVE` and requires both a `LICENSED` provider (`ERR_PROVIDER_NOT_LICENSED` otherwise) and an agreement `escalations_trailing_12mo` below 3 — at 3 or more the request is rejected with `ERR_REINSTATE_BLOCKED` (HTTP 422). Termination (`TERMINATE`, `GovernanceOfficer` only) is permitted from any of `DRAFT`, `ACTIVE`, or `PROBATION` and lands in the terminal `TERMINATED` state. Every other combination — activating from `PROBATION`, reinstating from `ACTIVE`, probating from `DRAFT`, or any action at all from `TERMINATED` — is rejected with `ERR_AGREEMENT_STATE` (HTTP 409), as is any of these actions offered by the wrong role producing `ERR_FORBIDDEN` instead. Every successful transition increments the agreement's `version` by one and refreshes its `updated_at`.

### 3.4. Royalty Reporting and Settlement

Royalties flow through quarterly statements that the provider reports and the organization finalizes. A `ProviderManager` of the provider that owns the agreement — the caller's `X-User-ID` is compared to that provider's `id`, not merely to any provider — submits a statement under the agreement with `period_year` (the calendar year, for example 2026), `period_quarter` (1 through 4), `reported_sales_cents` (the provider-reported gross licensed-product sales for the quarter), and `expected_agreement_version`. A quarter out of range is `ERR_INVALID_REQUEST`; the OCC mismatch is `ERR_STALE_AGREEMENT_VERSION` as described in §2.7. One quarter can hold only one live statement: if a `FINALIZED` statement already exists for the same agreement, year, and quarter, the submission is rejected with `ERR_QUARTER_ALREADY_FINALIZED` (HTTP 409). If a `PROVISIONAL` statement exists for that quarter, the new submission supersedes it — the superseded statement's provisional posting is first reversed out of both the agreement's `provisional_outstanding_cents` and the provider's `royalty_balance_cents`, the old statement moves to `SUPERSEDED`, and the agreement's `version` increments for the reversal before the new submission's own effects increment it again. The new statement is created `PROVISIONAL`, with `audited_sales_cents`, `final_royalty_cents`, and `delta_cents` remaining null until finalization, and its `license_agreement_id` recording the agreement it reports against. Submission returns HTTP 201; the agreement's statement listing supports an optional `status` filter.

The royalty itself uses annual marginal tiers applied to the agreement's calendar-year sales accumulation: the first 100,000,000 cents (one million dollars) of year-to-date sales is taxed at 8%, the next tranche up to 500,000,000 cents (five million dollars) of year-to-date sales at 10%, and everything above 500,000,000 cents at 12%. Statements are processed in chronological quarter order — `period_year`, then `period_quarter`, ascending. For any given statement, the system first sums the effective sales of the agreement's same-calendar-year statements from strictly earlier quarters, where a `FINALIZED` statement contributes its `audited_sales_cents` and any other counted statement contributes its `reported_sales_cents`; `SUPERSEDED` statements are excluded entirely. The statement's own sales figure is then allocated marginally against the tiers given that year-to-date base — the portion still fitting under the one-million-dollar tier line at 8%, the portion spilling into the next band at 10%, and any remainder at 12% — summed across every tier crossed and rounded half up exactly once per statement to integer cents. A first-quarter statement reporting 120,000,000 cents of sales, for instance, owes 8,000,000 cents on the first hundred million plus 2,000,000 cents on the twenty million above it: 10,000,000 cents of provisional royalty. The provisional variant of this computation runs at submission on `reported_sales_cents` and posts the resulting `provisional_royalty_cents` into the provider's `royalty_balance_cents` and the agreement's `provisional_outstanding_cents`. The final variant runs at finalization on `audited_sales_cents`. Later statements are never re-based: each statement's tier allocation is fixed at its own computation time, so finalizing an earlier quarter does not change a later quarter's provisional figure.

Finalization belongs to the organization's `FinanceController` — segregation of duties means the provider that reported the sales can never audit-confirm them — and carries the `audited_sales_cents` figure. Only a `PROVISIONAL` statement can be finalized; a statement already `FINALIZED` or `SUPERSEDED` is rejected with `ERR_STATEMENT_NOT_PROVISIONAL` (HTTP 409). On success, `final_royalty_cents` is recomputed by the marginal-tier schedule against the prior quarters' effective sales, `delta_cents` is set to the final royalty minus the provisional royalty, and the ledger postings land: the provider's `royalty_balance_cents` moves by exactly `delta_cents` (negative deltas post downward corrections), the agreement's `recognized_royalty_cents` grows by `final_royalty_cents`, and its `provisional_outstanding_cents` shrinks by the released `provisional_royalty_cents` — bucket conservation. Because the bucket mutation is an agreement mutation and the balance posting is a provider mutation, both the agreement's `version` and the provider's `version` increment by one. The agreement's `royalty_exposure_cents`, defined as its `recognized_royalty_cents` plus its `provisional_outstanding_cents`, is maintained as an invariant equal to this agreement's contribution to the provider's `royalty_balance_cents`.

### 3.5. Member Complaints and the Oversight Escalation Cascade

Complaints are the member-facing quality signal for licensed products. A `Member` files a complaint as themselves: the body's `member_id` must equal the caller's `X-User-ID` (a mismatch is `ERR_FORBIDDEN`), alongside the `license_agreement_id` of the licensed product's agreement, a `category` of `PRODUCT_QUALITY`, `BILLING`, `SERVICE`, or `CLAIMS`, a `severity` of `LOW` or `HIGH`, and a free-text `description`. Filing gates on standing before it gates on the agreement: a member whose household has lapsed is not in good standing and is rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409) before the agreement's state is examined, and the target agreement must be `ACTIVE` or `PROBATION` — filing against a `DRAFT` or `TERMINATED` agreement is rejected with `ERR_AGREEMENT_STATE` (HTTP 409). A successfully filed complaint starts in `FILED` with `filed_at` stamped from the logical clock, and creation returns HTTP 201. The complaints listing supports optional `member_id`, `license_agreement_id`, and `status` filters.

Adjudication belongs to `OversightAnalyst`, driving the complaint through its lifecycle with an `action` and an optional `resolution_code`. Opening review (`OPEN_REVIEW`) moves `FILED` → `UNDER_REVIEW`. Resolution (`RESOLVE`) is a sibling pair: it is permitted from either `UNDER_REVIEW` or `ESCALATED`, lands in the terminal `RESOLVED` state, and records `resolution_code` when one is supplied. Escalation (`ESCALATE`) moves `UNDER_REVIEW` → `ESCALATED`, stamps `escalated_at` from the logical clock, and is permitted only while the complaint's agreement is `ACTIVE` or `PROBATION` — escalating a complaint against a `TERMINATED` agreement is rejected with `ERR_AGREEMENT_STATE`. Every other adjudication pairing — resolving from `FILED`, escalating from `ESCALATED` or `RESOLVED`, or acting on a `RESOLVED` complaint at all — is rejected with `ERR_COMPLAINT_STATE` (HTTP 409).

Escalation is where oversight bites, because it fires a three-link cascade within the same request. Link one recomputes the agreement's `escalations_trailing_12mo`: the count of this agreement's complaints currently in `ESCALATED` status whose `escalated_at` is on or after the instant exactly 365 days before the logical clock — the window bound is inclusive, so an escalation exactly 365 days old still counts. When that count reaches 3 — the comparison is at-least, so exactly 3 fires — and the agreement is `ACTIVE`, the agreement moves to `PROBATION` with `probation_count` incremented by one and `version` advanced. Link two recomputes the provider's `escalations_trailing_12mo` the same way across all of the provider's agreements; when that count reaches 5 — again, exactly 5 fires — and the provider is `LICENSED`, the provider moves to `SUSPENDED` with its `version` incremented by one. Link three propagates a suspension: every still-`ACTIVE` agreement of the newly suspended provider moves to `PROBATION` with `probation_count` incremented by one each, while agreements already in `PROBATION` or `TERMINATED` are left untouched. Only complaints currently in `ESCALATED` status count toward either trailing threshold — a complaint resolved after escalation stops counting from the moment it resolves, which is precisely how agreements and providers eventually requalify for reinstatement and re-admission.

### 3.6. Legal-Entity Governance and Fund Movement

The organization's money is separated across three legal entities, and the separation is structural rather than customary. A `GovernanceOfficer` creates each entity with a `kind` of `MEMBERSHIP_ORG`, `FOUNDATION`, or `LOBBY_ARM`, a human-readable `display_name`, and an opening `balance_cents`. At most one entity of each kind may exist in the system; a duplicate kind is rejected with `ERR_ENTITY_KIND_EXISTS` (HTTP 409). After creation, an entity's `balance_cents` is mutated only by executed fund transfers — there is no other balance-write path.

Moving money is a two-role affair. A `GovernanceOfficer` requests a transfer with `from_entity_id`, `to_entity_id`, `amount_cents` (at least 1 cent; anything less is `ERR_INVALID_REQUEST`), and a free-text `purpose`; the request is created in `PENDING_APPROVAL` with `requested_by_user_id` recorded from the caller's `X-User-ID`. A `FinanceController` then decides it with a `decision` of `APPROVE` or `REJECT`. Segregation of duties is enforced per transfer: the decider's `X-User-ID` must differ from the transfer's `requested_by_user_id`, on rejection with `ERR_SELF_APPROVAL` (HTTP 403), and this check guards both decisions — an officer may neither approve nor reject their own request. The segregation check runs before the transfer's state is examined; a decision attempted on a transfer no longer in `PENDING_APPROVAL` is rejected with `ERR_TRANSFER_STATE` (HTTP 409).

Whether a direction is permitted at all is decided by a fixed governance matrix, and any pair not listed is prohibited with `ERR_PROHIBITED_ENTITY_PAIR` (HTTP 422). The membership organization may grant to the foundation — `MEMBERSHIP_ORG` → `FOUNDATION` is allowed and uncapped. The membership organization may fund the lobbying arm — `MEMBERSHIP_ORG` → `LOBBY_ARM` is allowed subject to the annual lobbying cap below. The foundation may support the membership organization — `FOUNDATION` → `MEMBERSHIP_ORG` is allowed subject to both a per-transfer cap and an annual outflow cap. Everything else is prohibited: `FOUNDATION` → `LOBBY_ARM` (foundation money never funds lobbying), any transfer where the lobbying arm is the sender (the lobbying arm never sends), and any self-transfer from an entity to itself.

Approval executes atomically — there is no separate execution step — and its fiscal checks run in a pinned order: balance first, then the per-transfer cap, then the annual cap. The balance check applies to every transfer: `amount_cents` may not exceed the source entity's current `balance_cents`, otherwise `ERR_INSUFFICIENT_ENTITY_BALANCE` (HTTP 422). For `FOUNDATION` → `MEMBERSHIP_ORG`, the per-transfer cap limits the amount to 5% of the foundation's current balance, truncated down to whole cents before comparison — an amount exactly at the cap passes, and anything above is `ERR_PER_TRANSFER_CAP_EXCEEDED` (HTTP 422). The foundation's annual outflow cap then limits the sum of all of the foundation's `EXECUTED` outflows whose `executed_at` falls in the clock's calendar year, plus the requested amount, to 15% of the foundation's current balance, again truncated down — an excess is `ERR_ANNUAL_CAP_EXCEEDED` (HTTP 422). For `MEMBERSHIP_ORG` → `LOBBY_ARM`, the annual cap is measured against dues revenue: net dues year-to-date are the sum of `paid_cents` minus `refunded_cents` across all membership terms — of any status, with refunds netting out — whose `purchased_at` falls in the clock's calendar year, and the sum of this calendar year's `EXECUTED` membership-to-lobby transfers plus the requested amount may not exceed 20% of that figure, truncated down, on pain of `ERR_ANNUAL_CAP_EXCEEDED`.

An approved transfer lands in `EXECUTED`: the source entity's `balance_cents` decreases by `amount_cents`, the destination's increases by the same amount — balance conservation is the standing invariant — and the transfer records `from_balance_after_cents`, `to_balance_after_cents`, `decided_by_user_id`, and `executed_at` stamped from the logical clock, the last of which anchors the calendar-year cap windows. A rejected transfer lands in `REJECTED` with `decided_by_user_id` recorded and both balances untouched. Both outcomes are terminal. The per-entity transfer listing matches transfers touching the entity on either side — as `from_entity_id` or as `to_entity_id` — and supports an optional `status` filter.

### 3.7. Publications, Circulation, and Advertising Standards

The publications desk guarantees advertisers a circulation base and enforces advertising standards at booking time. A `StandardsReviewer` creates an issue with a `title`, a `publication_date`, and a rate card: `min_cpm_cents` as the floor and `max_cpm_cents` as the ceiling for negotiated cost-per-thousand impressions. A ceiling below the floor is an inverted range rejected with `ERR_INVALID_REQUEST`. An issue's `circulation_count` is derived, never stored as a mutable figure: it counts the distinct households holding at least one membership term in `ACTIVE` or `RENEWED` status whose window covers the issue's `publication_date` — `start_date` on or before the publication date and the publication date strictly before `end_date`, a half-open window. A household with several covering terms still counts once, and `CANCELLED` or `LAPSED` terms never cover, regardless of when they flipped. The count is recomputed on every read of the publication and at every booking.

Booking an ad is a `StandardsReviewer` act carrying `advertiser_name`, a `category`, and the negotiated `agreed_cpm_cents`, and all standards enforcement happens at creation — a booking is created directly in `BOOKED` status with no review states. The category must clear advertising standards first among the fiscal checks: `TOBACCO`, `FIREARMS`, and `POLITICAL` are prohibited categories rejected with `ERR_AD_CATEGORY_RESTRICTED` (HTTP 422), leaving `TRAVEL`, `INSURANCE`, `HEALTH`, `FINANCE`, and `RETAIL` bookable. The rate card then bounds the negotiation: `agreed_cpm_cents` must lie between the issue's `min_cpm_cents` and `max_cpm_cents` inclusive — exactly at either bound passes — otherwise `ERR_RATE_CARD_VIOLATION` (HTTP 422). Finally, an issue with a `circulation_count` of 0 has no audience to sell and rejects the booking with `ERR_NO_CIRCULATION_BASE` (HTTP 422) before any cost computation runs. The booking's `estimated_cost_cents` is then the agreed rate times the current circulation, divided by one thousand, rounded half up once to integer cents — evaluated once, at booking time, against the circulation at that moment — and the booking records its `publication_id`. Creation returns HTTP 201.

### 3.8. Chapters, Volunteer Course Sessions, and Enrollment

Local chapters deliver the organization's volunteer-taught courses. A `MemberServicesAgent` charters a chapter with its `name`, two-letter `state_code`, and `city`. Within a chapter, its `ChapterCoordinator` — identified by `X-User-ID` equal to the chapter's `id`, with mismatches rejected as `ERR_FORBIDDEN` — schedules course sessions with a `course_kind` of `TAX_PREP` or `DRIVER_SAFETY`, the volunteer's `instructor_name`, a `start_time` that must be strictly in the future at creation, an `end_time` strictly after the start (both timing faults rejected as `ERR_INVALID_REQUEST`), and a `capacity` of at least 1 enrollee. Each session records its `chapter_id` back-reference to the hosting chapter identified in the path.

Two distinct overlap semantics guard the schedule, and both run against sessions of any computed status — a session that has already been held still occupies its historical slot. The chapter-room rule protects the physical room: a new session conflicts with an existing session of the same chapter unless the new session starts at least 30 minutes after the existing one ends, or the existing one starts at least 30 minutes after the new one ends. An existing session ending at 11:00 therefore blocks any new session starting before 11:30, while a start at exactly 11:30 is allowed; a violation is rejected with `ERR_SESSION_OVERLAP` (HTTP 409). The instructor rule protects the volunteer: `instructor_name` is a case-sensitive identity, and across all chapters a plain half-open overlap test applies — the new session conflicts exactly when its start is strictly before an existing session's end and that session's start is strictly before the new session's end. Adjacency is allowed — a session starting at the exact moment another of the instructor's sessions ends does not conflict — and no buffer applies; a violation is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409). Creation returns HTTP 201.

A session's `status` is derived lazily from the logical clock: `SCHEDULED` while the clock is before `end_time`, and `HELD` once the clock reaches `end_time`. Enrollment into a session is open to two paths: a `Member` self-enrolls with a `member_id` equal to their own `X-User-ID`, or a `ChapterCoordinator` enrolls any member on their behalf. The gates run in a fixed order. Timing first: the session must still be `SCHEDULED` with a `start_time` strictly after the clock — once the clock reaches `end_time`, or once the start time has been reached or passed, enrollment is rejected with `ERR_ENROLLMENT_CLOSED` (HTTP 409). Standing second: the member must be in good standing, otherwise `ERR_MEMBER_NOT_ACTIVE` (HTTP 409). Uniqueness third: a member already present in the session's `enrolled_member_ids` is rejected with `ERR_ALREADY_ENROLLED` (HTTP 409). Capacity last: when `enrolled_count` has already reached `capacity`, the next enrollment is rejected with `ERR_SESSION_FULL` (HTTP 409) — which means the enrollment that brings the count exactly to capacity succeeds. A successful enrollment appends the member id to `enrolled_member_ids`, recomputes `enrolled_count` as the list's length, and returns the updated session with HTTP 200.

### 3.9. Advocacy Campaigns and Member Mobilization

Advocacy is a lobbying-arm activity, and the campaign record enforces that boundary. An `AdvocacyDirector` creates a campaign with a `title`, a `level` of `FEDERAL` or `STATE`, an `issue_area` naming the policy area (for example HEALTHCARE or RETIREMENT), a `start_date` and `end_date` bounding the campaign window with `end_date` on or after `start_date` (an inverted window is `ERR_INVALID_REQUEST`), a `sponsor_entity_id`, and a conditional `state_code`: required when the level is `STATE` and required to be absent when the level is `FEDERAL`, with either violation rejected as `ERR_INVALID_REQUEST`. The sponsor entity must exist — an unknown `sponsor_entity_id` is `ERR_NOT_FOUND` — and its `kind` must be `LOBBY_ARM`, because advocacy spend belongs to the lobbying arm; a campaign sponsored by the membership organization or the foundation is rejected with `ERR_SPONSOR_KIND_INVALID` (HTTP 422). A campaign's `computed_status` is derived lazily on every read: `UPCOMING` while the clock date is before `start_date`, `ACTIVE` from `start_date` through `end_date` with both bounds inclusive, and `CLOSED` once the clock date passes `end_date`. The campaign listing supports optional `sponsor_entity_id`, `level`, and `status` filters.

Mobilization turns a campaign's window into member outreach. An `AdvocacyDirector` creates a mobilization event under a campaign with a `channel` of `EMAIL`, `PHONE`, or `MAIL` and an `audience_spec` describing the target audience. The campaign must be `ACTIVE` at request time — mobilizing under an `UPCOMING` or `CLOSED` campaign is rejected with `ERR_CAMPAIGN_NOT_ACTIVE` (HTTP 409), and this activity check is evaluated before the audience specification's data-use screening. The `audience_spec` allow-list is exactly two keys: `state_code` and `min_age`. The three benefit-marketing keys `owns_licensed_product`, `benefit_product_category`, and `provider_customer` are forbidden per §2.11 and rejected with `ERR_DATA_USE_RESTRICTED` (HTTP 422); any other key is malformed and rejected with `ERR_INVALID_REQUEST`. The event's `audience_count` is a snapshot computed at creation: it counts the members who are in good standing, who have not set `benefit_marketing_opt_out`, whose household's `state_code` equals the supplied `state_code` when that key is present, and whose `age_years` is at least `min_age` when that key is present — a member exactly `min_age` years old is included. Because the count is frozen at creation, later opt-outs, birthdays, or standing changes never mutate a stored mobilization event, and each event keeps its `campaign_id` back-reference to its parent campaign. Creation returns HTTP 201.

## 4. Endpoint Definitions

Operations that create a new resource — a household (with its members and initial term), a provider, a license agreement, a royalty statement, a complaint, a legal entity, a fund transfer, a publication, an ad booking, a chapter, a course session, a campaign, or a mobilization event — return `201 Created`. Operations that act on an existing resource without creating a new one — setting the clock, running the renewal batch, cancelling a term, admitting a provider, driving an agreement or complaint transition, finalizing a statement, deciding a transfer, or enrolling a member — return `200 OK`, as do all reads. The table below summarizes the surface; the full request and response semantics for each endpoint are defined by the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/api/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST   | `/api/_batch/renewal_run` | Run the membership renewal sweep | PlatformAdmin |
| POST   | `/api/households` | Create a household with its member(s) and initial term | MemberServicesAgent |
| GET    | `/api/households/{id}` | Read a household | MemberServicesAgent, PlatformAdmin |
| GET    | `/api/households/{id}/members` | List a household's members | MemberServicesAgent, AdvocacyDirector, PlatformAdmin |
| GET    | `/api/households/{id}/terms` | List a household's membership terms | MemberServicesAgent, PlatformAdmin |
| POST   | `/api/membership-terms/{id}/cancel` | Cancel an active membership term | MemberServicesAgent |
| POST   | `/api/providers` | Register a benefit provider | GovernanceOfficer |
| GET    | `/api/providers/{id}` | Read a provider | GovernanceOfficer, ProviderManager, OversightAnalyst, FinanceController, PlatformAdmin |
| POST   | `/api/providers/{id}/admit` | Admit or re-admit a provider | GovernanceOfficer |
| POST   | `/api/providers/{id}/license-agreements` | Draft a license agreement for a provider | ProviderManager |
| GET    | `/api/providers/{id}/license-agreements` | List a provider's license agreements | ProviderManager, GovernanceOfficer, OversightAnalyst, FinanceController, PlatformAdmin |
| GET    | `/api/license-agreements/{id}` | Read a license agreement | ProviderManager, GovernanceOfficer, OversightAnalyst, FinanceController, PlatformAdmin |
| POST   | `/api/license-agreements/{id}/transitions` | Drive an agreement state transition | GovernanceOfficer, OversightAnalyst |
| POST   | `/api/license-agreements/{id}/royalty-statements` | Submit a quarterly royalty statement | ProviderManager |
| GET    | `/api/license-agreements/{id}/royalty-statements` | List an agreement's royalty statements | ProviderManager, FinanceController, PlatformAdmin |
| POST   | `/api/royalty-statements/{id}/finalize` | Finalize a provisional royalty statement | FinanceController |
| POST   | `/api/complaints` | File a member complaint | Member |
| GET    | `/api/complaints/{id}` | Read a complaint | OversightAnalyst, MemberServicesAgent, PlatformAdmin |
| GET    | `/api/complaints` | List complaints with filters | OversightAnalyst, MemberServicesAgent, PlatformAdmin |
| POST   | `/api/complaints/{id}/adjudicate` | Drive a complaint state transition | OversightAnalyst |
| POST   | `/api/legal-entities` | Create a legal entity | GovernanceOfficer |
| GET    | `/api/legal-entities/{id}` | Read a legal entity | GovernanceOfficer, FinanceController, PlatformAdmin |
| POST   | `/api/fund-transfers` | Request a fund transfer | GovernanceOfficer |
| GET    | `/api/legal-entities/{id}/fund-transfers` | List transfers touching an entity | GovernanceOfficer, FinanceController, PlatformAdmin |
| POST   | `/api/fund-transfers/{id}/approve` | Approve or reject a fund transfer | FinanceController |
| POST   | `/api/publications` | Create a publication issue with its rate card | StandardsReviewer |
| GET    | `/api/publications/{id}` | Read a publication | StandardsReviewer, MemberServicesAgent, PlatformAdmin |
| POST   | `/api/publications/{id}/ad-bookings` | Book an ad into an issue | StandardsReviewer |
| GET    | `/api/publications/{id}/ad-bookings` | List an issue's ad bookings | StandardsReviewer, PlatformAdmin |
| POST   | `/api/chapters` | Charter a local chapter | MemberServicesAgent |
| GET    | `/api/chapters/{id}` | Read a chapter | MemberServicesAgent, ChapterCoordinator, PlatformAdmin |
| POST   | `/api/chapters/{id}/course-sessions` | Schedule a course session for a chapter | ChapterCoordinator |
| GET    | `/api/chapters/{id}/course-sessions` | List a chapter's course sessions | ChapterCoordinator, MemberServicesAgent, Member, PlatformAdmin |
| POST   | `/api/course-sessions/{id}/enroll` | Enroll a member in a course session | Member, ChapterCoordinator |
| POST   | `/api/campaigns` | Create an advocacy campaign | AdvocacyDirector |
| GET    | `/api/campaigns/{id}` | Read a campaign | AdvocacyDirector, PlatformAdmin |
| GET    | `/api/campaigns` | List campaigns with filters | AdvocacyDirector, PlatformAdmin |
| POST   | `/api/campaigns/{id}/mobilizations` | Create a mobilization event | AdvocacyDirector |
| GET    | `/api/campaigns/{id}/mobilizations` | List a campaign's mobilization events | AdvocacyDirector, PlatformAdmin |

## 5. Error Code Catalogue

The table below catalogues every error identifier and its HTTP status. The conditions that trigger each error are defined in the workflow narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SELF_APPROVAL` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_PROVIDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_AGE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INVALID_TERM_YEARS` | 422 Unprocessable Entity |
| `ERR_TERM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROVIDER_NOT_LICENSED` | 409 Conflict |
| `ERR_DUPLICATE_CATEGORY_AGREEMENT` | 409 Conflict |
| `ERR_AGREEMENT_NOT_IN_WINDOW` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_STATE` | 409 Conflict |
| `ERR_REINSTATE_BLOCKED` | 422 Unprocessable Entity |
| `ERR_QUARTER_ALREADY_FINALIZED` | 409 Conflict |
| `ERR_STATEMENT_NOT_PROVISIONAL` | 409 Conflict |
| `ERR_COMPLAINT_STATE` | 409 Conflict |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENTITY_KIND_EXISTS` | 409 Conflict |
| `ERR_PROHIBITED_ENTITY_PAIR` | 422 Unprocessable Entity |
| `ERR_TRANSFER_STATE` | 409 Conflict |
| `ERR_INSUFFICIENT_ENTITY_BALANCE` | 422 Unprocessable Entity |
| `ERR_PER_TRANSFER_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ANNUAL_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_AD_CATEGORY_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_RATE_CARD_VIOLATION` | 422 Unprocessable Entity |
| `ERR_NO_CIRCULATION_BASE` | 422 Unprocessable Entity |
| `ERR_SESSION_OVERLAP` | 409 Conflict |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_ALREADY_ENROLLED` | 409 Conflict |
| `ERR_ENROLLMENT_CLOSED` | 409 Conflict |
| `ERR_SPONSOR_KIND_INVALID` | 422 Unprocessable Entity |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 Conflict |
| `ERR_DATA_USE_RESTRICTED` | 422 Unprocessable Entity |



