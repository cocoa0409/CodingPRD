# Athlete Endorsement Booking API — Product Requirements Document

## 1. Introduction

An athlete marketing agency sits between two parties who rarely agree on anything: brands that want a face for a campaign, and the talent whose calendar, reputation and category exclusivity are finite resources. The desk described here automates that middle seat. Brands file endorsement opportunities against rostered athletes; an independent compliance desk screens each opportunity for brand fit; the agency and the brand then trade rounds of paper over the appearance fee, the usage rights, the strictness of the morals clause and the length of category exclusivity. When the brand finally signs, the agreement becomes an engagement that must be countersigned by finance, staffed with appearances and shoots, policed for paid-promotion disclosure, and eventually settled into a payout with the agency's commission taken out.

Three properties make this system harder to build than a simple CRUD booking tool. First, an engagement carries **two independent status dimensions** — a contract dimension and a settlement dimension — which advance on their own schedules and are only loosely coupled through a small number of declared cascades. Second, three different kinds of scarce capacity are tracked with three deliberately different interval conventions: an athlete's physical calendar (closed intervals padded by travel time), a studio's production capacity (half-open intervals with an aggregate ceiling), and category exclusivity (inclusive whole-day ranges). Third, money is never mutated in place — every movement is an append-only ledger entry, and the derived money fields on an engagement are nothing more than sums over that stream.

All time in this system is derived from a **logical clock**, never from wall-clock time. Offer expiries, renewal deadlines and every `*_at` stamp read the logical clock. This makes the whole negotiation and settlement timeline reproducible, which matters because several transitions are *lazy*: they fire only when a caller tries to act after a deadline has passed, and the refusal itself is what moves the record to its terminal state.

## 2. Global Specifications & System-Wide Principles

### 2.1. Desk Roles and Caller Identity

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, blank, or if `X-User-Role` names a role outside the declared set, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the named role is not listed among the roles authorised for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly five roles: `TalentAgent`, `BrandRep`, `Athlete`, `ComplianceOfficer`, and `FinanceManager`.

A `TalentAgent` is the agency-side booking agent. They build the roster, draft and submit the paper, revise it after a counter, withdraw it, run all appearance logistics, open production slots, schedule deliverables and open renewal options. When `X-User-Role` is `TalentAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a transition asks for it, but it never compares it to any entity's `id`.

A `ComplianceOfficer` runs the independent compliance desk: brand-fit screening, brand sanctions, roster status changes, disclosure rulings and engagement terminations. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It *is* recorded on two entities — as `screened_by_user_id` on an opportunity when that officer screens it, and as `ruled_by_user_id` on a disclosure record when that officer rules on it — but it is never matched against any entity's `id`.

A `FinanceManager` countersigns contracts and builds and disburses payout statements. When `X-User-Role` is `FinanceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `countersigned_by_user_id` on the engagement it countersigns, but does not compare it to any entity's `id`.

The remaining two roles are entity-backed, and this is what ties `X-User-ID` to resource ownership. When `X-User-Role` is `BrandRep`, `X-User-ID` is the `id` of the acting `Brand`; ownership checks on any resource that references a `Brand` compare the resource's brand foreign-key field — `brand_id` on an opportunity, or `brand_id` on an engagement — to `X-User-ID`. When `X-User-Role` is `Athlete`, `X-User-ID` is the `id` of the acting `Athlete`; ownership checks on any resource that references an `Athlete` compare the resource's athlete foreign-key field — `athlete_id` on the engagement behind the resource — to `X-User-ID`. A mismatch in either case is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Ownership is enforced on exactly eight operations: filing an opportunity, countering a term sheet, accepting a term sheet, submitting a deliverable, reviewing a deliverable, filing a disclosure record, remediating a disclosure record, and deciding a renewal option. On the first three and on review and renewal decision the caller is a `BrandRep` and the comparison is against the brand behind the resource; on deliverable submission, disclosure filing and disclosure remediation the caller is an `Athlete` and the comparison is against `athlete_id` on the engagement behind the resource.

One further identity rule cuts across the compliance desk. The officer who screened an opportunity may not later rule on any disclosure record belonging to that opportunity's engagement. If the `X-User-ID` presented on a disclosure ruling equals the `screened_by_user_id` recorded on the opportunity behind that deliverable's engagement, the ruling is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1 and a maximum of 100; a `limit` below 1 or above 100 is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400). `offset` defaults to 0 and its minimum is 0.

Unless a specific list says otherwise, results are ordered by `created_at` ascending. List responses carry `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` is true when rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource is identified by a server-minted UUID exposed as `id`. Identifiers carry no type prefix — a term-sheet id and an engagement id are indistinguishable by shape, and clients must not attempt to infer a resource's type from its identifier.

Almost every resource additionally carries `created_at`, `updated_at` and `version`. `created_at` and `updated_at` are ISO 8601 UTC timestamps with exactly three fractional-second digits, both derived from the logical clock rather than from wall-clock time. `version` is an integer that starts at 1 when the resource is created and increments by 1 on every mutation of that resource; `updated_at` is refreshed on the same occasions. There is exactly one exception: a `LedgerEntry` is an immutable, append-only record and carries only `id` and `created_at` — it has neither `updated_at` nor `version`, and it is never modified once written.

The logical clock is pinned by a test-driving capability available to every role, `POST /_clock/set_current_utc`, which takes a single field `to_iso8601` and answers with `current_utc`. Before the first call to that endpoint the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time — not for `created_at`, not for `updated_at`, and not for any of the domain stamps (`screened_at`, `offer_expires_at`, `countersigned_at`, `released_at`, `disbursed_at`, `decided_at`). Advancing the clock mutates no entity.

### 2.5. Version Stamping and Optimistic Concurrency on Engagements

Two write operations are guarded by optimistic concurrency control against the `Engagement` aggregate, because both restate figures the client must have observed first.

Creating an appearance booking (`POST /appearance-bookings`) requires a non-optional `expected_engagement_version` field carrying the client's last observed `version` of the target engagement. Additional bookings against the same engagement are perfectly legitimate, so the guard cannot come from a state precondition; it exists because the writer would otherwise be extending a commitment on top of a stale view of the engagement's accrual and committed-day figures. If `expected_engagement_version` does not equal the engagement's current `version`, the create is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412). A successful create increments the engagement's `version` by 1.

Creating a payout statement (`POST /payout-statements`) likewise requires a non-optional `expected_engagement_version` carrying the client's last observed engagement `version`. A newer statement legitimately supersedes a standing draft statement, so again the guard is not a state check: it forces the writer to prove its view of the engagement's settlement figures is current before restating them. A mismatch is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412). A successful create increments the engagement's `version` by 1.

No other endpoint takes a version field. In particular, confirming, closing or cancelling a booking, reviewing a deliverable, countersigning, terminating and disbursing all carry no expected-version input.

### 2.6. Money, Rounding and the Append-Only Ledger

All monetary amounts are integers in cents. Wherever a monetary result requires rounding, the method is round half up — a value exactly halfway between two whole cents rounds away from zero, upward in magnitude. Every calculation in this document states exactly where its rounding steps fall, and those positions are binding: rounding a step earlier or later than specified produces a different, wrong answer.

Money is never edited in place. Each movement is appended as an immutable `LedgerEntry` carrying `engagement_id`, an `entry_type`, a signed `amount_cents` (credits positive, debits negative), a human-readable `memo`, and a polymorphic source pair `source_entity` and `source_id`. `source_entity` records which kind of row caused the movement — one of `AppearanceBooking`, `Deliverable`, `PayoutStatement` or `RenewalOption` — and `source_id` is that row's identifier. The pair is a label, not a declared foreign key; nothing enforces referential integrity on it.

There are five movement kinds: `TRAVEL_ACCRUAL`, `REVERSAL`, `PENALTY`, `BONUS` and `DISBURSEMENT`. An engagement's `accrued_fee_cents` is the running sum of the `amount_cents` of that engagement's entries whose `entry_type` is `TRAVEL_ACCRUAL`, `REVERSAL`, `PENALTY` or `BONUS`. Disbursement entries are deliberately excluded from that sum; disbursed money is tracked separately in `gross_settled_cents`, which is the sum of `gross_amount_cents` over that engagement's payout statements whose `status` is `DISBURSED`.

### 2.7. Three Kinds of Occupied Capacity

Scarcity in this domain is tracked three different ways, and the interval convention differs deliberately in each.

**The athlete's calendar uses closed intervals with per-booking travel padding.** A booking occupies not merely the window between `start_at` and `end_at` but that window inflated on *both* sides by its own `travel_buffer_hours`. Two bookings collide when the inflated interval of one touches or overlaps the inflated interval of the other — that is, when the new booking's inflated start is at or before the other's inflated end and the new booking's inflated end is at or after the other's inflated start. Touching endpoints therefore *do* count as a collision.

**A production slot uses half-open intervals with an aggregate ceiling.** A shoot reservation covers the instants from `shoot_start_at` inclusive up to `shoot_end_at` exclusive. Two reservations whose boundaries merely meet — one ending exactly where the next begins — do not overlap. What is capped is not pairwise overlap but the aggregate: at no single instant may the number of live reservations on the same slot exceed that slot's `capacity`.

**Category exclusivity uses inclusive whole-day ranges.** A grant occupies every day from `start_date` through `end_date`, both endpoints included. Adjacency is clean: a new grant that starts on the day immediately after another's `end_date` is fine, while a new grant that starts *on* another's `end_date` conflicts.

### 2.8. Order of Evaluation

When more than one rule could reject the same request, the rules are evaluated in a fixed order and the first failure is the one reported. Implementations must honour this ordering, because a request can violate several rules at once and only one error id may be returned.

The ladder runs as follows. Authentication comes first, then endpoint role authorisation. Next, path parameters are resolved strictly left to right, each reporting its own not-found code: an athlete id reports `ERR_ATHLETE_NOT_FOUND`, a brand id `ERR_BRAND_NOT_FOUND`, an opportunity id `ERR_OPPORTUNITY_NOT_FOUND`, a term-sheet id `ERR_TERM_SHEET_NOT_FOUND`, an engagement id `ERR_ENGAGEMENT_NOT_FOUND`, a booking id `ERR_BOOKING_NOT_FOUND`, a deliverable id `ERR_DELIVERABLE_NOT_FOUND`, a disclosure-record id `ERR_DISCLOSURE_NOT_FOUND`, a production-slot id `ERR_SLOT_NOT_FOUND`, a payout-statement id `ERR_PAYOUT_NOT_FOUND` and a renewal-option id `ERR_RENEWAL_NOT_FOUND` — all HTTP 404.

Only then is the request body checked for schema validity: required fields present, enum values inside their declared member sets, integers non-negative where constrained, end instants strictly after start instants, ISO dates and datetimes well formed, and `limit` inside 1 to 100. Any of those failures yields `ERR_INVALID_REQUEST` (HTTP 400).

After the schema check, foreign keys carried *in the request body* are resolved — `athlete_id`, `brand_id`, `opportunity_id`, `engagement_id`, `booking_id`, `production_slot_id` and `deliverable_id` — checked left to right in the order the fields are listed for that endpoint, each reporting its own entity's not-found code. Body foreign-key resolution applies to opportunity creation, term-sheet creation, appearance-booking creation, deliverable creation, disclosure-record creation, payout-statement creation and renewal-option creation.

Resource ownership (`ERR_NOT_RESOURCE_OWNER`) is checked next, and after it the optimistic-concurrency version check (`ERR_STALE_ENGAGEMENT_VERSION`). Only once all of that passes does the domain layer run, in this order: athlete bookability (`ERR_ATHLETE_NOT_BOOKABLE`), opportunity-screened (`ERR_OPPORTUNITY_NOT_SCREENED`), term-sheet from-state (`ERR_TERM_SHEET_INVALID_STATE`), offer expiry (`ERR_OFFER_EXPIRED`), engagement contract-status fitness (`ERR_ENGAGEMENT_NOT_ACTIVE`), engagement terminality for countersign and terminate (`ERR_ENGAGEMENT_ALREADY_TERMINAL`), booking from-state (`ERR_BOOKING_INVALID_STATE`), deliverable from-state (`ERR_DELIVERABLE_INVALID_STATE`), disclosure from-state (`ERR_DISCLOSURE_INVALID_STATE`), settlement billability (`ERR_SETTLEMENT_NOT_BILLABLE`), payout from-state (`ERR_PAYOUT_INVALID_STATE`), renewal window (`ERR_RENEWAL_WINDOW_CLOSED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), brand sanction (`ERR_BRAND_SANCTIONED`), disclosure compliance (`ERR_DISCLOSURE_NOT_COMPLIANT`), morals-tier downgrade (`ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN`), deliverable reference coherence (`ERR_BOOKING_ENGAGEMENT_MISMATCH`), shoot-inside-slot-window (`ERR_SLOT_WINDOW_VIOLATION`), athlete calendar overlap (`ERR_BOOKING_OVERLAP`), slot capacity (`ERR_SLOT_CAPACITY_EXCEEDED`), booking-inside-term (`ERR_BOOKING_WINDOW_OUTSIDE_TERM`), exclusivity conflict (`ERR_EXCLUSIVITY_CONFLICT`), counter-round limit (`ERR_COUNTER_LIMIT_EXCEEDED`), duplicate disclosure (`ERR_DUPLICATE_DISCLOSURE`), fee cap (`ERR_FEE_CAP_EXCEEDED`) and finally the billable-set check (`ERR_NO_BILLABLE_DELIVERABLES`).

Two consequences of the ladder are worth calling out. Because ownership precedes the optimistic-concurrency check, a `BrandRep` acting on someone else's engagement gets `ERR_NOT_RESOURCE_OWNER` even when its `expected_engagement_version` is also stale. And because the deliverable reference-coherence check precedes the slot window and capacity checks, a shoot that both names the wrong slot shape and exceeds capacity surfaces as `ERR_BOOKING_ENGAGEMENT_MISMATCH`.

### 2.9. Cascades and Derived Counters

Several counters in this system are *derived*: they are definitions, not free-standing fields, and every operation that changes their inputs must refresh them in the same request. An athlete's `active_exclusivity_count` is the number of that athlete's exclusivity grants whose `status` is `ACTIVE`. An athlete's `no_show_count` is the number of that athlete's appearance bookings whose `outcome` is `NO_SHOW`. An engagement's `approved_deliverable_count` is the number of that engagement's deliverables whose `status` is `APPROVED`. A production slot's `reserved_count` is the number of deliverable rows referencing that slot whose `status` is anything other than `VOIDED`.

An athlete's `exposure_risk_snapshot_score` is a denormalised copy of the roster-snapshot exposure figure described later. It is recomputed and rewritten whenever `active_exclusivity_count` changes, whenever an engagement owned by that athlete changes its contract dimension, or whenever a disclosure record belonging to one of that athlete's engagements changes its ruling.

Whenever a cascade mutates a resource, that resource's own `updated_at` and `version` move as well — a cascaded change is a mutation like any other.

### 2.10. Sanctions and Roster Status

Two administrative levers block work without deleting anything. A `Brand` carries a `sanctioned` flag, false at registration, together with a free-text `sanction_reason` that is null while `sanctioned` is false. While a brand is sanctioned, neither acceptance of its paper nor countersignature of its engagement may proceed; both are refused with `ERR_BRAND_SANCTIONED` (HTTP 422). Clearing the flag restores both.

An `Athlete` carries a roster `status` of `ACTIVE`, `SUSPENDED` or `RETIRED`, defaulting to `ACTIVE` at registration. A `SUSPENDED` or `RETIRED` athlete may not be negotiated for or booked: submitting a term sheet, revising one, and creating an appearance booking are all refused with `ERR_ATHLETE_NOT_BOOKABLE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Building the Roster and Filing an Opportunity

A `TalentAgent` puts talent on the books first. Registration takes the athlete's `full_name`, their `sport` as free text (for example `BASKETBALL`), a `market_tier` of `GLOBAL`, `NATIONAL` or `REGIONAL` describing commercial reach, a `base_appearance_rate_cents` card rate for a single appearance day expressed in cents and required to be at least 1, and a `commission_pct` giving the agency's cut as a fraction — strictly greater than 0 and at most 0.50. An optional `home_market` code may be supplied; when it is omitted the athlete is recorded as belonging to the `US` market, and the value is purely informational. A newly rostered athlete opens with roster `status` `ACTIVE`, `active_exclusivity_count` 0, `exposure_risk_snapshot_score` 0 and `no_show_count` 0.

Roster status is not the agent's to change. A `ComplianceOfficer` replaces an athlete's `status` with `ACTIVE`, `SUSPENDED` or `RETIRED`, optionally recording a free-text `reason` alongside the change.

Advertisers register themselves. A `BrandRep` supplies the brand's trading `name`, the endorsement `category` it competes in — one of `BEVERAGE`, `FOOTWEAR`, `FINANCIAL`, `AUTOMOTIVE`, `GAMING` or `NUTRITION` — the contracting `legal_entity_name`, and a third-party `compliance_rating` between 0 and 100 inclusive. The identifier minted for the brand *is* the `X-User-ID` its representative will act under from then on. Compliance may later raise or clear the `sanctioned` flag on any brand, recording a `reason` that is stored as `sanction_reason`.

With both sides on file, a `BrandRep` files an endorsement opportunity naming the `brand_id` it acts as — which must equal its own `X-User-ID` — and the `athlete_id` it wants to book. The request states the engagement term as `requested_start_date` and `requested_end_date`, both ISO calendar dates in `YYYY-MM-DD` form, with the end date required to fall on or after the start date. It carries the brand's opening offer as `proposed_fee_cents` in cents (zero is permitted), and it declares the planned workload as three counts, each of which may be zero: `planned_posts` for social posts, `planned_appearances` for appearance days, and `planned_shoots` for studio shoots. Rights are declared up front too: `exclusivity_category` names the category the brand wants locked on the athlete, `exclusivity_months` gives the requested lock length in whole months from 0 to 36 inclusive, `territory` is `DOMESTIC`, `NORTH_AMERICA` or `GLOBAL`, and `usage_rights_tier` is `SOCIAL_ONLY`, `BROADCAST` or `PERPETUAL`. A freshly filed opportunity enters `INTAKE`, and its `expected_fee_cents` and `brand_fit_score` both remain null until screening runs.

Opportunities can be listed and filtered by `athlete_id`, by `brand_id` and by `status`.

### 3.2. Brand-Fit Screening

Screening is the compliance desk's gate, and it is where an opportunity leaves `INTAKE` for exactly one of two destinations. A `ComplianceOfficer` screens an opportunity that is still in `INTAKE`; the call carries no payload, and it always computes the same two figures before choosing a branch.

The first figure is what the requested workload is worth at the athlete's card rate. Each planned appearance counts as four workload units, each planned shoot as two, and each planned post as one; those three weighted counts are added together. The athlete's `base_appearance_rate_cents` is multiplied by that total and the product divided by four, and the result rounded half up to whole cents becomes `expected_fee_cents`. (The division by four is what converts workload units back into appearance-day equivalents, since an appearance day is itself four units.)

The second figure measures how well the brand's money matches that expectation. If `expected_fee_cents` came out as zero — which happens only when nothing at all was planned — fee alignment is taken to be 100. Otherwise fee alignment is 100 multiplied by the ratio of `proposed_fee_cents` to `expected_fee_cents`, with that ratio capped at 1 before the multiplication, so over-paying never scores above par while under-paying scores proportionally lower.

Three ingredients then combine. Brand quality contributes 40 percent of the brand's `compliance_rating`. Reach contributes 30 percent of a tier figure obtained by multiplying 100 by a reach weight of 1.00 for a `GLOBAL` athlete, 0.85 for a `NATIONAL` athlete and 0.70 for a `REGIONAL` athlete. Money contributes 30 percent of the fee-alignment figure. From that sum an exclusivity burden is subtracted: one and a half points for each requested exclusivity month, but never more than 20 points however long the requested lock. The resulting raw figure is rounded half up to a whole number exactly once — never at the intermediate weighted terms — and then clamped so it cannot fall below 0 or rise above 100. That whole number is written to `brand_fit_score`.

A score of 60 or higher screens the opportunity in and moves it `INTAKE → SCREENED`. Anything below 60 moves it `INTAKE → REJECTED_FIT`, and no term sheet may ever be drafted against an opportunity in that state. Both branches write `expected_fee_cents` and `brand_fit_score`, and both stamp `screened_by_user_id` with the officer's `X-User-ID` and `screened_at` with the logical clock — the rejected branch records the officer just as the accepted one does. `screened_by_user_id` is the key the segregation-of-duties rule reads much later, when disclosures on the resulting engagement come up for ruling.

Screening only ever reads one opportunity plus its brand and athlete rows; no other opportunity on the roster contributes anything to the score.

### 3.3. Papering the Deal: Rounds, Counters and Revisions

Once an opportunity is `SCREENED`, a `TalentAgent` drafts round one of the paper against it by naming the `opportunity_id`. Drafting against an opportunity in any other state — still `INTAKE`, already `REJECTED_FIT`, `CONTRACTED` or `CLOSED_LOST` — is refused with `ERR_OPPORTUNITY_NOT_SCREENED`. The draft states the headline `fee_cents` (at least 1), a `usage_rights_tier`, the licence length in `usage_term_months` between 1 and 60 inclusive, a `territory`, the `morals_clause_tier` the athlete will accept, the `exclusivity_months` on the table between 0 and 36 inclusive, and the `appearance_days` the agent commits to in this round, which may be zero. The morals tiers run `TIER_A` (strictest), `TIER_B`, then `TIER_C` (loosest). The term sheet's `exclusivity_category` is *not* client-settable: it is copied verbatim from the parent opportunity at creation. A new paper opens in `DRAFT` with `round_number` 1 and `counter_count` 0. Term sheets can be listed filtered by `opportunity_id` and by `status`.

Submitting the paper moves it `DRAFT → SUBMITTED` and requires the opportunity's athlete to be `ACTIVE` on the roster — a cross-entity guard, since it is the *athlete* record and not the term sheet that is being checked. Submission recomputes `provisional_fee_cents` and stamps `offer_expires_at` at the logical clock plus fourteen days. Submission takes no payload.

The provisional figure is the forward-looking estimate of what the paper is worth. Three multipliers apply to the headline fee: a usage multiplier of 1.00 for `SOCIAL_ONLY`, 1.35 for `BROADCAST` and 1.80 for `PERPETUAL`; a morals multiplier of 1.15 for `TIER_A`, 1.05 for `TIER_B` and 1.00 for `TIER_C`; and a territory multiplier of 1.00 for `DOMESTIC`, 1.20 for `NORTH_AMERICA` and 1.45 for `GLOBAL`. The `fee_cents` figure is multiplied by all three multipliers and the whole product is rounded half up to whole cents exactly once — never once per multiplier — giving the rights component. Separately, an exclusivity uplift is taken as the athlete's `base_appearance_rate_cents` multiplied by five percent for each month of exclusivity on the table, with the month count capped at 24 before the multiplication, rounded half up to whole cents once. The two components are added to a travel component, which for the provisional figure is always exactly zero — even when confirmed bookings already exist elsewhere on the athlete's book. Finally a ceiling applies: `fee_cents` multiplied by 2.5 and rounded half up to whole cents. The provisional figure is the lesser of the summed components and that ceiling.

The brand answers with a counter, moving the paper `SUBMITTED → COUNTERED`. The counter carries `counter_fee_cents`, `counter_usage_rights_tier`, `counter_morals_clause_tier` and `counter_exclusivity_months`, plus an optional `note`, and those four values overwrite `fee_cents`, `usage_rights_tier`, `morals_clause_tier` and `exclusivity_months` on the paper outright. Countering increments `counter_count` by 1 and records the countered tier in `last_counter_morals_tier`. Only the `BrandRep` whose `X-User-ID` equals the opportunity's `brand_id` may counter. A brand gets at most three counters on one paper: if `counter_count` has already reached 3, a fourth counter is refused with `ERR_COUNTER_LIMIT_EXCEEDED`.

The agent answers a counter by revising, closing the cycle `COUNTERED → SUBMITTED`; a paper can therefore travel `SUBMITTED → COUNTERED → SUBMITTED` repeatedly, bounded only by the counter ceiling. Revision carries a fresh `fee_cents`, `usage_rights_tier`, `usage_term_months`, `morals_clause_tier`, `exclusivity_months` and `appearance_days`. Like submission it requires the athlete to be `ACTIVE`. It also enforces a one-way ratchet on reputation risk: the `morals_clause_tier` proposed in the revision must be at least as strict as the tier recorded in `last_counter_morals_tier`, where `TIER_A` is stricter than `TIER_B` and `TIER_B` is stricter than `TIER_C`. Proposing a looser tier than the brand's most recent counter demanded is refused with `ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN`. A successful revision increments `round_number` by 1, recomputes `provisional_fee_cents` by exactly the same rules as submission, and re-stamps `offer_expires_at` at the logical clock plus another fourteen days.

The agent may pull the paper off the table at any live point, so the withdrawal edge exists three times over: `DRAFT → WITHDRAWN`, `SUBMITTED → WITHDRAWN` and `COUNTERED → WITHDRAWN`. All three take the same optional `reason` and behave identically. Withdrawal has a knock-on effect on the parent: if, after the withdrawal, no term sheet of that opportunity remains in `DRAFT`, `SUBMITTED` or `COUNTERED`, the opportunity itself moves `SCREENED → CLOSED_LOST` and accepts no further term sheets. If a live sibling remains, the opportunity stays `SCREENED`.

Any negotiation action attempted from the wrong state — submitting something that is not `DRAFT`, countering or accepting something that is not `SUBMITTED`, revising something that is not `COUNTERED`, or withdrawing something already `ACCEPTED`, `WITHDRAWN` or `EXPIRED` — is refused with `ERR_TERM_SHEET_INVALID_STATE`.

### 3.4. Acceptance: Minting the Engagement and Locking the Category

Acceptance is the single most consequential call in the system, and it is guarded by five conditions before anything is written. The paper must be `SUBMITTED`. The acting `BrandRep`'s `X-User-ID` must equal the opportunity's `brand_id`. The logical clock must be at or before `offer_expires_at`. The brand must not be sanctioned, or the acceptance is refused with `ERR_BRAND_SANCTIONED`. The negotiated `fee_cents` must not exceed the athlete's `base_appearance_rate_cents` multiplied by eight, or the acceptance is refused with `ERR_FEE_CAP_EXCEEDED`. And the category slot the acceptance would occupy must be free, as described below.

Expiry is handled lazily, and the refusal is itself the state change. If acceptance is attempted when the logical clock has already passed `offer_expires_at`, the paper moves `SUBMITTED → EXPIRED` and the call is refused with `ERR_OFFER_EXPIRED`. No engagement is created, no grant is minted, and the paper is now terminal — a later, punctual acceptance attempt is impossible.

The exclusivity check reads the athlete's category register. Acceptance would mint a grant covering the inclusive day range that begins on the engagement's `term_start_date` and ends on the day that is the requested number of exclusivity months later, minus one day — so a six-month lock starting on the first of March runs through the last day of August. If any other exclusivity grant of the *same* `athlete_id` and the *same* `category` whose `status` is `PENDING` or `ACTIVE` shares even one calendar day with that range, the acceptance is refused with `ERR_EXCLUSIVITY_CONFLICT`. Grants that merely abut — one ending the day before the other begins — do not conflict; grants that share their boundary day do.

When all five conditions hold, acceptance moves the paper `SUBMITTED → ACCEPTED` and writes four things at once. First, an **engagement** is minted, carrying `term_sheet_id` for the accepted paper, `opportunity_id` carried through for the later segregation-of-duties lookup, and `athlete_id` and `brand_id` copied from the opportunity. It opens with `contract_status` `PENDING_COUNTERSIGN` and `settlement_status` `UNBILLED`. It freezes the negotiated terms as they stood at acceptance: `base_fee_cents` takes the term sheet's `fee_cents`, and `usage_rights_tier`, `morals_clause_tier`, `territory`, `exclusivity_category` and `exclusivity_months` are all copied across. Its `term_start_date` and `term_end_date` take the opportunity's `requested_start_date` and `requested_end_date`, and they are the inclusive first and last days on which any booking of this engagement may fall. The term sheet's `provisional_fee_cents` is frozen onto the engagement under the same name, while `binding_fee_cents` stays null until countersignature. `required_deliverable_count` is frozen as the sum of the opportunity's `planned_posts`, `planned_appearances` and `planned_shoots`, and `appearance_days_committed` takes the term sheet's `appearance_days`. The counters `accrued_fee_cents`, `gross_settled_cents` and `approved_deliverable_count` all start at 0, and `countersigned_by_user_id`, `countersigned_at` and `terminated_reason_code` all start null.

Second, an **exclusivity grant** is created in `PENDING` status for that athlete and category over the inclusive range just described, recording `athlete_id`, `engagement_id`, `category`, `start_date` and `end_date`, with `released_at` null. A `PENDING` grant already occupies the register for conflict-detection purposes even though it has not yet been counted into `active_exclusivity_count` — only `ACTIVE` grants are counted there.

Third, the parent opportunity moves `SCREENED → CONTRACTED`. Fourth, because that opportunity is now contracted, every *sibling* term sheet of the same opportunity whose `status` is `DRAFT`, `SUBMITTED` or `COUNTERED` is moved to `WITHDRAWN`. Competing papers cannot survive a signed deal.

Engagements can be listed and filtered by `athlete_id`, `brand_id`, `term_sheet_id`, `opportunity_id`, `contract_status` and `settlement_status`. The grants held against an athlete can be listed and filtered by `status` and by `category`; the grants held by a single engagement can be listed filtered by `status`.

### 3.5. Countersignature and the Binding Fee

A signed deal is not yet a live deal. A `FinanceManager` countersigns an engagement sitting in `PENDING_COUNTERSIGN`, supplying a `signed_by_reference` naming the executed paper copy, and the engagement moves `PENDING_COUNTERSIGN → ACTIVE`. Countersignature is refused with `ERR_BRAND_SANCTIONED` while the brand is sanctioned, and countersigning an engagement that has already left `PENDING_COUNTERSIGN` — whether it is `ACTIVE`, `COMPLETED` or `TERMINATED` — is refused with `ERR_ENGAGEMENT_ALREADY_TERMINAL`. The call stamps `countersigned_by_user_id` with the finance manager's `X-User-ID` and `countersigned_at` with the logical clock.

Countersignature is where the fee stops being an estimate. `binding_fee_cents` is computed by the same three-multiplier engine that produced the provisional figure — the same usage, morals and territory multipliers applied to the frozen fee with a single rounding of the whole product, the same exclusivity uplift of five percent of the athlete's `base_appearance_rate_cents` per exclusivity month capped at 24 months and rounded half up once, and the same ceiling of the fee multiplied by 2.5 and rounded half up. The one and only difference is the travel component, which for the binding figure is no longer zero. It is the sum of `travel_cost_cents` over the engagement's appearance bookings whose `status` is `CONFIRMED` or `COMPLETED`, taken in `created_at` ascending order, plus a travel-day allowance obtained by multiplying the athlete's `base_appearance_rate_cents` by twenty-five percent and by the total travel days of those same bookings, rounded half up to whole cents once. Total travel days is the sum of the `travel_days` of each qualifying booking. Bookings sitting in `HOLD`, `CANCELLED` or `NO_SHOW` contribute nothing. The rights component, the exclusivity uplift and the travel component are each rounded to whole cents in their own right and only then summed, and the lesser of that sum and the ceiling is written to `binding_fee_cents`. With no qualifying bookings, the binding figure equals the provisional figure exactly; with one or more, it is strictly larger before the ceiling applies. Once written, `binding_fee_cents` is frozen — later bookings do not move it.

Countersignature also propagates outward. Because the engagement went `ACTIVE`, its exclusivity grant moves `PENDING → ACTIVE`; because that grant became `ACTIVE`, the athlete's `active_exclusivity_count` increments by 1; and because that counter changed, the athlete's `exposure_risk_snapshot_score` is recomputed and rewritten.

### 3.6. Appearance Logistics and Travel Accrual

A `TalentAgent` places a hold on the athlete's calendar by naming the `engagement_id` being billed, a `city` (informational only), the appearance window as `start_at` and `end_at` in UTC ISO 8601 form with the end strictly after the start, a `travel_buffer_hours` figure between 0 and 72 inclusive, and the `expected_engagement_version` the concurrency guard demands. The engagement must be `PENDING_COUNTERSIGN` or `ACTIVE`, or the request is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`; the athlete must be `ACTIVE` on the roster, or it is refused with `ERR_ATHLETE_NOT_BOOKABLE`. The booking's calendar days must sit inside the engagement's term: the date of `start_at` must be on or after `term_start_date` and the date of `end_at` on or before `term_end_date`, both inclusive, or the request is refused with `ERR_BOOKING_WINDOW_OUTSIDE_TERM`.

The calendar itself is the scarcest resource. The new booking's window inflated by its own `travel_buffer_hours` on each side must not intersect the equivalently inflated window of *any* other appearance booking of the same athlete whose `status` is `HOLD` or `CONFIRMED` — and crucially that sweep spans every engagement that athlete holds, not just the one being booked. Because the intervals are closed, an intersection includes the case where the two inflated windows merely touch at an endpoint: the collision test is that the new inflated start falls at or before the other's inflated end *and* the new inflated end falls at or after the other's inflated start. A collision is refused with `ERR_BOOKING_OVERLAP`. Bookings already `COMPLETED`, `NO_SHOW` or `CANCELLED` release the calendar and are not consulted.

A new booking opens in `HOLD`, with `travel_cost_cents` 0, `travel_days` 0, `outcome` null and `cancel_reason_code` null. Creating one increments the engagement's `version` by 1. Bookings can be listed and filtered by `engagement_id` and by `status`.

Confirming a hold moves it `HOLD → CONFIRMED` and requires the engagement to still be `PENDING_COUNTERSIGN` or `ACTIVE`. The call carries the reimbursable `travel_cost_cents` actually committed, and it derives `travel_days`: take the span from `start_at` to `end_at` in hours, add twice `travel_buffer_hours`, divide by 24 and round *up* to a whole number of days. The ceiling is exact — a padded span of exactly 24.0 hours yields 1 day, while 24.01 hours yields 2. No spans are ever merged across bookings; each booking's travel days are computed from that booking alone. Confirmation appends a `TRAVEL_ACCRUAL` ledger entry whose `amount_cents` is the positive `travel_cost_cents`, and because that entry was appended the engagement's `accrued_fee_cents` increases by the same amount.

A confirmed booking is closed with an `outcome` of either `COMPLETED` or `NO_SHOW`, and the two branches diverge sharply. Closing `CONFIRMED → COMPLETED` writes the `outcome` and nothing else — no ledger movement, no counter change. Closing `CONFIRMED → NO_SHOW` writes the `outcome`, increments the athlete's `no_show_count` by 1, and appends a `PENALTY` ledger entry whose `amount_cents` is the negative of ten percent of the engagement's `binding_fee_cents`, rounded half up to whole cents; because that entry was appended, the engagement's `accrued_fee_cents` decreases by that amount.

Cancellation is available to both a `TalentAgent` and a `BrandRep`, and it records a `cancel_reason_code` from the supplied `reason_code`. Cancelling from `HOLD` moves the booking `HOLD → CANCELLED` and writes no ledger entry, because nothing was ever accrued against a hold. Cancelling from `CONFIRMED` moves it `CONFIRMED → CANCELLED` and appends the compensating `REVERSAL` ledger entry whose `amount_cents` is the negative of that booking's `travel_cost_cents`; because that entry was appended, the engagement's `accrued_fee_cents` returns to its pre-confirmation value. Either way, any deliverable of type `APPEARANCE` that references the cancelled booking and is still `PENDING`, `SUBMITTED` or `REVISION_REQUESTED` is voided by the same cascade — `PENDING → VOIDED`, `SUBMITTED → VOIDED` or `REVISION_REQUESTED → VOIDED` as appropriate.

Confirming a booking that is not `HOLD`, closing one that is not `CONFIRMED`, or cancelling one already in a terminal state is refused with `ERR_BOOKING_INVALID_STATE`. An engagement's money movements can be read back as an append-only stream ordered by `created_at` ascending, optionally filtered by `entry_type`.

### 3.7. Production Slots, Deliverables and the Approval Cascade

Studio and crew capacity is modelled explicitly. A `TalentAgent` opens a `ProductionSlot` with a `name` labelling the studio or crew, a `capacity` of at least 1, and a bookable window running from `window_start_at` inclusive to `window_end_at` inclusive, the latter required to be strictly after the former. A new slot opens with `reserved_count` 0; that counter tracks how many deliverable rows currently reference the slot without having been voided, and it is readable alongside the slot itself.

Deliverables are scheduled by the agent against an engagement that is `PENDING_COUNTERSIGN` or `ACTIVE`; scheduling against a `COMPLETED` or `TERMINATED` engagement is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`. Each deliverable names its `engagement_id`, its `type` — `SOCIAL_POST`, `APPEARANCE` or `SHOOT` — and a `due_date` as an ISO calendar date. An optional `disclosure_required` flag defaults to true when omitted; while it is true the deliverable cannot be approved without a compliant disclosure on file.

The three types carry sharply different references, and the coherence rule is unforgiving. An `APPEARANCE` deliverable must carry a `booking_id`, and the booking it names must belong to the *same* engagement as the deliverable itself; it must not carry a `production_slot_id`, a `shoot_start_at` or a `shoot_end_at`. A `SHOOT` deliverable must carry a `production_slot_id` together with both `shoot_start_at` and `shoot_end_at`, and must not carry a `booking_id`. A `SOCIAL_POST` deliverable carries neither a booking reference nor any shoot reference. Any departure from that shape — an appearance without a booking, an appearance whose booking belongs to another engagement, a shoot missing its slot or window, a social post carrying either — is refused with `ERR_BOOKING_ENGAGEMENT_MISMATCH`.

Shoot scheduling then meets the slot twice. First the reservation must lie inside the slot's own window: `shoot_start_at` at or after `window_start_at` and `shoot_end_at` at or before `window_end_at`, or the request is refused with `ERR_SLOT_WINDOW_VIOLATION`. Second the aggregate capacity is tested. The reservation covers the instants from `shoot_start_at` inclusive up to `shoot_end_at` exclusive, and across all deliverable rows on that same slot whose `status` is anything other than `VOIDED`, no single instant may be covered by more reservations than the slot's `capacity` allows. Because the intervals are half-open, back-to-back reservations — one ending exactly where the next begins — never overlap and never contend for the same unit of capacity. Breaching the ceiling is refused with `ERR_SLOT_CAPACITY_EXCEEDED`. A successful shoot creation increments that slot's `reserved_count` by 1.

Every new deliverable opens in `PENDING` with `asset_url` null, `line_value_cents` null and `revision_count` 0, and its `weight` is derived from its `type` and never supplied by the client: a `SOCIAL_POST` weighs 1, an `APPEARANCE` weighs 4, and a `SHOOT` weighs 2. These are the same relative weights the intake screen used to size the workload. Deliverables can be listed and filtered by `engagement_id`, `booking_id`, `production_slot_id`, `status` and `type`.

The athlete produces the asset. Submitting supplies an `asset_url`, requires the engagement to be `ACTIVE`, requires the submitting `Athlete`'s `X-User-ID` to equal the engagement's `athlete_id`, and moves the deliverable `PENDING → SUBMITTED` on a first submission or `REVISION_REQUESTED → SUBMITTED` on a resubmission, overwriting the stored `asset_url` in the latter case. Submitting from any other status — `APPROVED`, `VOIDED` or `SUBMITTED` — is refused with `ERR_DELIVERABLE_INVALID_STATE`, and submitting against an engagement that is not `ACTIVE` is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`.

Review belongs to the brand, and only to the `BrandRep` whose `X-User-ID` equals the engagement's `brand_id`. The review carries a `decision` of either `APPROVE` or `REQUEST_REVISION`, plus an optional `revision_note`. Review too requires the engagement to be `ACTIVE`, failing with `ERR_ENGAGEMENT_NOT_ACTIVE` otherwise, and it requires the deliverable to be `SUBMITTED`, failing with `ERR_DELIVERABLE_INVALID_STATE` otherwise. The two branches are deliberately asymmetric.

A `decision` of `REQUEST_REVISION` moves the deliverable `SUBMITTED → REVISION_REQUESTED` and increments its `revision_count` by 1. Nothing else moves: `approved_deliverable_count` is unchanged and no completion cascade fires. The athlete may then resubmit, closing the cycle `SUBMITTED → REVISION_REQUESTED → SUBMITTED` as many times as the parties need.

A `decision` of `APPROVE` first checks the disclosure gate: when the deliverable's `disclosure_required` is true, at least one disclosure record filed against it must have `status` `COMPLIANT`, or the approval is refused with `ERR_DISCLOSURE_NOT_COMPLIANT`. When the gate passes, the deliverable moves `SUBMITTED → APPROVED` and a four-hop cascade runs: because the deliverable became `APPROVED`, the engagement's `approved_deliverable_count` increments by 1; if that counter has now reached `required_deliverable_count`, the engagement's `contract_status` moves `ACTIVE → COMPLETED`; and because `contract_status` became `COMPLETED`, the engagement's `settlement_status` moves `UNBILLED → BILLABLE`, opening settlement. If the counter has not yet reached the required total, the engagement stays `ACTIVE` and the settlement dimension does not move.

### 3.8. Disclosure Compliance for Paid Promotion

Paid promotion has to be labelled, and the labelling is audited independently of the brand's own approval. The athlete files a disclosure record naming the `deliverable_id` it covers, the `platform` on which the asset was published — one of `INSTAGRAM`, `X`, `TIKTOK`, `YOUTUBE` or `BROADCAST` — the `disclosure_tag` actually used on the post, and the `posted_at` publication instant in UTC ISO 8601 form. Only the `Athlete` whose `X-User-ID` equals the engagement's `athlete_id` may file. A record opens in `PENDING_REVIEW` with `ruled_by_user_id` null, `finding_note` null and `remediation_count` 0. A deliverable may hold at most one record whose `status` is `PENDING_REVIEW` or `COMPLIANT` at any moment; filing a second while one of those is live is refused with `ERR_DUPLICATE_DISCLOSURE`. Records filed against a deliverable can be listed and filtered by `status`.

A `ComplianceOfficer` rules on a record still in `PENDING_REVIEW`, supplying a `ruling` of `COMPLIANT` or `NON_COMPLIANT` and an optional `finding_note`. Ruling on a record that is not `PENDING_REVIEW` is refused with `ERR_DISCLOSURE_INVALID_STATE`. Whichever way the ruling goes, the officer must not be the same person who screened the underlying opportunity — the officer's `X-User-ID` is compared against the `screened_by_user_id` recorded on the opportunity behind this deliverable's engagement, and a match is refused with `ERR_SEGREGATION_OF_DUTIES`.

A `COMPLIANT` ruling additionally requires that the record's `disclosure_tag` be one of exactly three accepted markers: `#ad`, `#sponsored` or `#paidpartnership`. The comparison is an exact, case-sensitive membership test — `#Ad`, `#ads` and `#sponsoredpost` are all outside the set. A `COMPLIANT` ruling on a tag outside that set is refused with `ERR_DISCLOSURE_NOT_COMPLIANT`. When it passes, the record moves `PENDING_REVIEW → COMPLIANT`, `ruled_by_user_id` is stamped with the officer, and the parent deliverable's approval gate is thereby unblocked.

A `NON_COMPLIANT` ruling has no tag restriction — any tag may be found wanting. It moves the record `PENDING_REVIEW → NON_COMPLIANT`, stamps `ruled_by_user_id` and stores the `finding_note`, and because the athlete's non-compliance tally has grown by one, that athlete's `exposure_risk_snapshot_score` is recomputed and rewritten.

The athlete gets a second chance. Remediating a record that is `NON_COMPLIANT` supplies a corrected `disclosure_tag` and a fresh `posted_at`, overwriting both, increments `remediation_count` by 1, clears `ruled_by_user_id` back to null, and moves the record `NON_COMPLIANT → PENDING_REVIEW` — closing the cycle `PENDING_REVIEW → NON_COMPLIANT → PENDING_REVIEW`. Because the athlete's non-compliance tally has now shrunk by one, `exposure_risk_snapshot_score` is recomputed again. Only the owning `Athlete` may remediate, and remediating a record that is not `NON_COMPLIANT` is refused with `ERR_DISCLOSURE_INVALID_STATE`.

### 3.9. Termination and the Four-Hop Unwind

Compliance can pull an engagement down at any point before it completes. Termination is available while the engagement's `contract_status` is `PENDING_COUNTERSIGN` or `ACTIVE`; attempting it on an engagement already `COMPLETED` or `TERMINATED` is refused with `ERR_ENGAGEMENT_ALREADY_TERMINAL`. The call carries a `reason_code`, which is stored as `terminated_reason_code`, and moves the engagement `PENDING_COUNTERSIGN → TERMINATED` or `ACTIVE → TERMINATED` respectively.

Termination then runs an unwind across four fronts, all in the same request.

Exclusivity is released first. Every exclusivity grant of this engagement whose `status` is `PENDING` or `ACTIVE` is released, so the edge fires as `ACTIVE → RELEASED` or as `PENDING → RELEASED` depending on where the grant stood, and `released_at` is stamped with the logical clock in both cases. On an `ACTIVE → RELEASED` release the athlete's `active_exclusivity_count` decrements by 1, and because that counter changed, `exposure_risk_snapshot_score` is recomputed. On a `PENDING → RELEASED` release the athlete's counter is left untouched, because that slot was never counted into it — which means terminating from `PENDING_COUNTERSIGN` releases the register without moving `active_exclusivity_count` at all.

The calendar is released second. Every appearance booking of this engagement whose `status` is `HOLD` or `CONFIRMED` moves to `CANCELLED` with `cancel_reason_code` set to the literal string `AUTO_TERMINATION`. For each booking that was `CONFIRMED`, a `REVERSAL` ledger entry is appended whose `amount_cents` is the negative of that booking's `travel_cost_cents`; because those entries were appended, the engagement's `accrued_fee_cents` falls by the same total. Bookings that were merely on `HOLD` accrued nothing and therefore reverse nothing.

Outstanding work is voided third. Every deliverable of this engagement whose `status` is `PENDING`, `SUBMITTED` or `REVISION_REQUESTED` is voided — the edge fires as `PENDING → VOIDED`, `SUBMITTED → VOIDED` or `REVISION_REQUESTED → VOIDED` as appropriate — and for each voided deliverable of type `SHOOT` the referenced production slot's `reserved_count` decrements by 1, freeing that half-open window for other reservations. Deliverables already `APPROVED` are left alone — the work was done and it stays billable.

Settlement is opened fourth. Because the engagement became `TERMINATED`, its `settlement_status` moves `UNBILLED → BILLABLE`, so whatever was accrued and approved before the termination can still be paid out. Termination is thus not a way to avoid settling; it is a way to stop new commitments.

### 3.10. Settlement, Renewal and Exposure Reporting

The money dimension of an engagement advances on its own track. It sits at `UNBILLED` from acceptance and moves to `BILLABLE` the moment the contract dimension enters either `COMPLETED` or `TERMINATED` — those are the only two doors into billability, and neither is triggered directly by a caller.

A `FinanceManager` then builds the settlement statement, naming the `engagement_id` and the `expected_engagement_version`. The engagement's `settlement_status` must be `BILLABLE` or `INVOICED`; both `UNBILLED` and `SETTLED` are refused with `ERR_SETTLEMENT_NOT_BILLABLE`. At least one deliverable of the engagement must be `APPROVED`, or the request is refused with `ERR_NO_BILLABLE_DELIVERABLES`. Building from `BILLABLE` moves the money dimension `BILLABLE → INVOICED`. Building again while already `INVOICED` is a legitimate self-loop `INVOICED → INVOICED`: the statement is restated, the standing statement — which must be in `DRAFT` — moves `DRAFT → VOIDED`, the replacement is created in `DRAFT`, and the money dimension stays at `INVOICED`. A voided statement no longer counts toward `gross_settled_cents`. Either way the engagement's `version` increments by 1, which is precisely why the next writer's `expected_engagement_version` must be refreshed.

The statement's arithmetic is a per-line waterfall over the engagement's `APPROVED` deliverables, taken in `created_at` ascending order; the deliverable identifier is never consulted for ordering. Deliverables in `PENDING`, `SUBMITTED`, `REVISION_REQUESTED` or `VOIDED` are excluded outright. The total weight is the sum of the `weight` of every line in that set. Each line's `line_value_cents` is then the engagement's `binding_fee_cents` multiplied by that line's own `weight` and divided by the total weight, rounded half up to whole cents — and the rounding order is pinned: **each line is rounded first, and the rounded line values are then summed.** `gross_amount_cents` is that sum of rounded line values, and it will generally differ slightly from `binding_fee_cents`; that residue is expected and is never redistributed across the lines. `agency_commission_cents` follows the same discipline: each line's own rounded `line_value_cents` is multiplied by the athlete's `commission_pct` and rounded half up to whole cents, and those per-line commissions are summed. `penalty_cents` is the absolute value of the sum of the `amount_cents` of every `PENALTY` ledger entry on this engagement, with no time window filter — no-show penalties booked at any point in the engagement's life all count. `athlete_net_cents` is `gross_amount_cents` less `agency_commission_cents` less `penalty_cents`, and `line_count` is the number of lines that entered the statement. Building the statement also writes each line's `line_value_cents` back onto the deliverable row itself, so a superseding rebuild overwrites the previous figures.

Disbursing a statement requires it to be in `DRAFT`; disbursing one already `DISBURSED` or `VOIDED` is refused with `ERR_PAYOUT_INVALID_STATE`. Disbursement moves the statement `DRAFT → DISBURSED`, stamps `disbursed_at` with the logical clock, appends a `DISBURSEMENT` ledger entry whose `amount_cents` is the negative of `athlete_net_cents`, raises the engagement's `gross_settled_cents` by the statement's `gross_amount_cents`, and moves the money dimension `INVOICED → SETTLED`. Because disbursement entries are excluded from the accrual sum by definition, `accrued_fee_cents` is untouched by it. An engagement's statements can be listed and filtered by `status`.

Renewal is the agent's business. A renewal option may only be opened against an engagement whose `contract_status` is `COMPLETED` or `TERMINATED` and whose `binding_fee_cents` is not null; opening one against an engagement still `PENDING_COUNTERSIGN` or `ACTIVE` is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`. The agent names the `engagement_id`, an `option_deadline_date` giving the inclusive last ISO calendar date on which the brand may decide, and a `proposed_base_fee_cents` headline fee of at least 1 for the renewal term. Opening the option runs the bonus-and-renewal computation once, in a pinned order, with no iteration to a fixed point.

The steps run exactly once each, in this order. Step one takes `base_value_cents` as the engagement's `binding_fee_cents` — the bonus is excluded from the tier key by construction. Step two computes `approval_rate` as the engagement's `approved_deliverable_count` divided by its `required_deliverable_count`, rounded half up to four decimal places. Step three picks `bonus_tier` from the pair of figures produced so far, taking the **first** matching rule: `TIER_1` when `approval_rate` is at least 1.0000 and `base_value_cents` is at least thirty thousand dollars expressed as 3,000,000 cents; otherwise `TIER_2` when `approval_rate` is at least 0.8000 and `base_value_cents` is at least fifteen thousand dollars expressed as 1,500,000 cents; otherwise `TIER_3` when `approval_rate` is at least 0.5000; otherwise `NONE`. Step four computes `bonus_cents` as `base_value_cents` multiplied by the tier's bonus percentage — twelve percent for `TIER_1`, seven percent for `TIER_2`, three percent for `TIER_3` and zero for `NONE` — rounded half up to whole cents exactly once. Step five computes `total_engagement_value_cents` as `base_value_cents` plus `bonus_cents`; this figure is reported only and must never be fed back into the tier selection of step three, even in the case where adding the bonus would push the value across a higher tier's floor. Step six builds the renewal multiplier by starting at 1.00, adding 0.10 when `bonus_tier` is `TIER_1` or 0.05 when it is `TIER_2` and nothing for `TIER_3` or `NONE`, and then adding a market escalator drawn from the athlete's `market_tier` — 0.03 for `GLOBAL`, 0.015 for `NATIONAL` and nothing for `REGIONAL`. `renewal_fee_cents` is the supplied `proposed_base_fee_cents` multiplied by that multiplier, rounded half up to whole cents exactly once. Deliverable rows themselves are never re-read here; only the frozen approved and required counters on the engagement are consulted. The option opens in `OPEN` with `decided_at` null, and an engagement's options can be listed and filtered by `status`.

The brand decides, supplying a `decision` of `EXERCISE` or `DECLINE`; only the `BrandRep` whose `X-User-ID` equals the engagement's `brand_id` may do so. A decision is only valid while the option is `OPEN` and the date component of the logical clock is on or before `option_deadline_date`. Exercising moves the option `OPEN → EXERCISED`, stamps `decided_at`, and appends a `BONUS` ledger entry whose `amount_cents` is the positive `bonus_cents`; because that entry was appended, the engagement's `accrued_fee_cents` rises by that amount. Declining moves the option `OPEN → DECLINED` and stamps `decided_at`, and writes no ledger entry at all — a declined option never accrues its bonus. Like offer expiry, the deadline is enforced lazily: a decision arriving when the clock's date is already past `option_deadline_date` moves the option `OPEN → LAPSED` and the call is refused with `ERR_RENEWAL_WINDOW_CLOSED`; the same error answers a decision on an option that is no longer `OPEN`.

Finally, the agency, compliance and finance can all read an athlete's exposure position on demand. The read answers with the `athlete_id`, the `variant` applied, and four figures: `category_load`, `morals_exposure`, `noncompliance_hits` and the combined `score`. `category_load` counts the athlete's exclusivity grants. `morals_exposure` sums a morals weight over the athlete's engagements, weighting a `TIER_A` morals clause as 3, `TIER_B` as 2 and `TIER_C` as 1. `noncompliance_hits` counts the disclosure records that are currently `NON_COMPLIANT` and belong, through their deliverable, to an engagement of this athlete. The `score` is twelve points for each unit of `category_load`, plus eight points for each unit of `morals_exposure`, plus fifteen points for each unit of `noncompliance_hits`, with a ceiling of 100 applied once at the very end. All of the arithmetic is integer arithmetic.

Two variants of that read exist, selected by the `variant` query parameter, which defaults to `ROSTER_SNAPSHOT` when omitted. `ROSTER_SNAPSHOT` counts only committed rows: `category_load` counts exclusivity grants whose `status` is `ACTIVE`, and `morals_exposure` sums the morals weight over engagements whose `contract_status` is `ACTIVE`. `PIPELINE_PROJECTED` counts the same committed rows plus everything in flight: `category_load` additionally counts grants whose `status` is `PENDING`, and `morals_exposure` additionally adds a morals weight for every engagement whose `contract_status` is `PENDING_COUNTERSIGN` and for every term sheet whose `status` is `SUBMITTED` or `COUNTERED` and whose opportunity names this athlete, using that term sheet's *current* `morals_clause_tier`. `noncompliance_hits` is computed identically in both variants. It is the `ROSTER_SNAPSHOT` figure — and only that one — which is denormalised onto the athlete as `exposure_risk_snapshot_score`.

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Operations that create a new resource answer with HTTP 201; operations that modify or read an existing resource answer with HTTP 200. The table below gives only the HTTP contract and the roles permitted to call each operation — the request payloads, the response contents and the side effects are specified in the narratives of Section 3 and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Pin the server's logical clock to a supplied instant. Before this is ever called the clock reads 2026-08-01T00:00:00Z. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/athletes` | Register an athlete on the agency roster. | TalentAgent |
| GET | `/athletes/{id}` | Read one athlete, including the denormalized exposure snapshot. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/athletes/{id}/status` | Set an athlete's roster status. | ComplianceOfficer |
| GET | `/athletes/{id}/exposure-summary` | Computed exposure position for one athlete, in either variant. | TalentAgent, ComplianceOfficer, FinanceManager |
| GET | `/athletes/{id}/exclusivity-grants` | List the exclusivity grants held against one athlete. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/brands` | Register a brand. The minted id is the identifier its representative acts under. | BrandRep |
| GET | `/brands/{id}` | Read one brand. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/brands/{id}/sanction` | Raise or clear the sanction flag on a brand. | ComplianceOfficer |
| POST | `/opportunities` | Brand files an endorsement opportunity against a rostered athlete. | BrandRep |
| GET | `/opportunities/{id}` | Read one opportunity, including its screening outputs. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| GET | `/opportunities` | Filtered, paginated opportunity list. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/opportunities/{id}/screen` | Screen an opportunity for brand fit and branch it in or out. | ComplianceOfficer |
| POST | `/term-sheets` | Agent drafts round one of a term sheet against a screened opportunity. | TalentAgent |
| GET | `/term-sheets/{id}` | Read one term sheet, including its provisional value and offer expiry. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| GET | `/term-sheets` | Filtered, paginated term-sheet list. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/term-sheets/{id}/submit` | Put the drafted paper in front of the brand. | TalentAgent |
| POST | `/term-sheets/{id}/counter` | Brand counters the paper with revised terms. | BrandRep |
| POST | `/term-sheets/{id}/revise` | Agent answers the brand's counter. | TalentAgent |
| POST | `/term-sheets/{id}/accept` | Brand accepts the paper, minting the engagement and its exclusivity grant. | BrandRep |
| POST | `/term-sheets/{id}/withdraw` | Agent pulls the paper off the table. | TalentAgent |
| GET | `/engagements/{id}` | Read one engagement, both status dimensions and all derived figures. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| GET | `/engagements` | Filtered, paginated engagement list. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/engagements/{id}/countersign` | Finance countersigns the engagement and freezes its binding fee. | FinanceManager |
| POST | `/engagements/{id}/terminate` | Compliance terminates the engagement and runs the unwind cascade. | ComplianceOfficer |
| GET | `/engagements/{id}/ledger-entries` | Append-only money movements of one engagement, oldest first. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| GET | `/engagements/{id}/exclusivity-grants` | List the exclusivity grants held by one engagement. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| GET | `/engagements/{id}/payout-statements` | List the payout statements of one engagement. | TalentAgent, ComplianceOfficer, FinanceManager, Athlete |
| GET | `/engagements/{id}/renewal-options` | List the renewal options of one engagement. | TalentAgent, BrandRep, ComplianceOfficer, FinanceManager |
| POST | `/appearance-bookings` | Agent places an appearance hold on the athlete's calendar. | TalentAgent |
| GET | `/appearance-bookings/{id}` | Read one appearance booking. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| GET | `/appearance-bookings` | Filtered, paginated appearance-booking list. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/appearance-bookings/{id}/confirm` | Confirm a held booking and record its travel cost. | TalentAgent |
| POST | `/appearance-bookings/{id}/close` | Close a confirmed booking with its outcome. | TalentAgent |
| POST | `/appearance-bookings/{id}/cancel` | Cancel a held or confirmed booking. | TalentAgent, BrandRep |
| POST | `/production-slots` | Open a studio or crew slot with an aggregate capacity. | TalentAgent |
| GET | `/production-slots/{id}` | Read one production slot, including its reserved count. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/deliverables` | Agent schedules a deliverable against an engagement. | TalentAgent |
| GET | `/deliverables/{id}` | Read one deliverable. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| GET | `/deliverables` | Filtered, paginated deliverable list. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/deliverables/{id}/submit` | Athlete submits the asset for review. | Athlete |
| POST | `/deliverables/{id}/review` | Brand approves the asset or sends it back for revision. | BrandRep |
| GET | `/deliverables/{id}/disclosure-records` | List the disclosure records filed against one deliverable. | TalentAgent, BrandRep, Athlete, ComplianceOfficer, FinanceManager |
| POST | `/disclosure-records` | Athlete files the paid-promotion disclosure for a deliverable. | Athlete |
| POST | `/disclosure-records/{id}/rule` | Compliance rules on a filed disclosure. | ComplianceOfficer |
| POST | `/disclosure-records/{id}/remediate` | Athlete re-tags a non-compliant disclosure and returns it to review. | Athlete |
| POST | `/payout-statements` | Finance builds the settlement statement for an engagement. | FinanceManager |
| POST | `/payout-statements/{id}/disburse` | Finance disburses a draft statement. | FinanceManager |
| POST | `/renewal-options` | Agent opens a renewal option on a finished engagement. | TalentAgent |
| POST | `/renewal-options/{id}/decide` | Brand exercises or declines the option. | BrandRep |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below in the `error_id` field of its envelope. The conditions that raise each one are described in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ATHLETE_NOT_FOUND` | 404 |
| `ERR_BRAND_NOT_FOUND` | 404 |
| `ERR_OPPORTUNITY_NOT_FOUND` | 404 |
| `ERR_TERM_SHEET_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_DELIVERABLE_NOT_FOUND` | 404 |
| `ERR_DISCLOSURE_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_RENEWAL_NOT_FOUND` | 404 |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 |
| `ERR_ATHLETE_NOT_BOOKABLE` | 409 |
| `ERR_OPPORTUNITY_NOT_SCREENED` | 409 |
| `ERR_TERM_SHEET_INVALID_STATE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_ENGAGEMENT_NOT_ACTIVE` | 409 |
| `ERR_ENGAGEMENT_ALREADY_TERMINAL` | 409 |
| `ERR_BOOKING_INVALID_STATE` | 409 |
| `ERR_DELIVERABLE_INVALID_STATE` | 409 |
| `ERR_DISCLOSURE_INVALID_STATE` | 409 |
| `ERR_SETTLEMENT_NOT_BILLABLE` | 409 |
| `ERR_PAYOUT_INVALID_STATE` | 409 |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 |
| `ERR_BRAND_SANCTIONED` | 422 |
| `ERR_DISCLOSURE_NOT_COMPLIANT` | 422 |
| `ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN` | 422 |
| `ERR_BOOKING_ENGAGEMENT_MISMATCH` | 422 |
| `ERR_SLOT_WINDOW_VIOLATION` | 422 |
| `ERR_BOOKING_OVERLAP` | 409 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_BOOKING_WINDOW_OUTSIDE_TERM` | 422 |
| `ERR_EXCLUSIVITY_CONFLICT` | 409 |
| `ERR_COUNTER_LIMIT_EXCEEDED` | 422 |
| `ERR_DUPLICATE_DISCLOSURE` | 409 |
| `ERR_FEE_CAP_EXCEEDED` | 422 |
| `ERR_NO_BILLABLE_DELIVERABLES` | 422 |
