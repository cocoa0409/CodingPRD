# Law Firm Intake API — Product Requirements Document

## 1. Introduction

At a large law firm, no new matter may open until the firm knows exactly whom it would be acting for — and against. This document specifies the Law Firm Intake API, the system of record for an AmLaw-scale intake department. The platform registers parties and their affiliate trees, normalizes and phonetically indexes every known name, runs conflict searches across all live matters, routes the resulting hits to the responsible attorney for review, erects ethical walls that hard-block read access, negotiates client waivers under segregation of duties, generates engagement letters carrying scope and rate terms, vets client credit, collects and refunds retainers, and sweeps the books of lateral hires for imputed conflicts from their prior firms.

Two design commitments shape everything that follows. First, compliance evidence must be reproducible: every temporal rule runs on a server-side logical clock, all money is integer cents, and every status flip is versioned and immediately visible. Second, duties are segregated — the attorney who requests a waiver can never approve it, and ethical walls are administered only by the conflicts partner. All business resources are mounted under `/intake`.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request in which either header is missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly six roles, spelled as follows: `FirmAdmin`, `IntakeSpecialist`, `ResponsibleAttorney`, `ConflictsPartner`, `BillingClerk`, and `Client`. Each endpoint admits a fixed set of roles (§4), and transition-style endpoints further restrict individual actions within an endpoint to particular roles; a caller whose role is not admitted to the attempted operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity binds to stored entities for three of the six roles. When `X-User-Role` is `ResponsibleAttorney`, `X-User-ID` is the `id` of the acting `Attorney`; ownership checks on any resource that references an attorney — a matter's `responsible_attorney_id`, a waiver's `requested_by_attorney_id` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `ConflictsPartner`, `X-User-ID` is likewise the `id` of the acting `Attorney`, compared in the same fashion wherever a rule speaks of the acting attorney (for example, the segregation-of-duties comparison on waiver approval). When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the client `Party`; ownership checks on client-scoped operations compare the matter's `client_party_id` to `X-User-ID`.

The remaining three roles are opaque. When `X-User-Role` is `FirmAdmin`, `IntakeSpecialist`, or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

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
- Requests to unknown paths fail as `ERR_NOT_FOUND` (HTTP 404) in this same envelope, and an unexpected server failure is rendered in the same envelope with `error_id` `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset` fails with `ERR_INVALID_REQUEST`; an integer value outside the permitted range is clamped, not rejected — `limit` into [1, 100] and `offset` up to a floor of 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The conflict-hit listing is the one specified exception and uses the deterministic hit ordering defined in §3.4.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Resource Identity, Timestamps, and Version Semantics

Every resource in the system — Party, Attorney, Matter, MatterParty, ConflictCheck, ConflictHit, EthicalWall, WaiverRequest, EngagementLetter, CreditAssessment, and RetainerDeposit — carries a common envelope of system-managed fields:

- **`id`** (string): a server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the row.
- **`version`** (integer): starts at 1 and increments by one on every mutation of that row, including mutations written by cascaded side effects that originate from another resource.

Consistency is immediate: every mutation and all of its cascaded effects are visible in the same request's response and in any re-read that follows it.

### 2.5. The Logical Clock and Deterministic Time

The server runs on a logical clock rather than the host wall clock. Before any clock-setting call has been made, the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. Every server-assigned timestamp is read from this logical clock: the resource `created_at` and `updated_at` markers of §2.4 and the event timestamps named throughout §3 (`sent_at`, `expires_at`, `issued_at`, `countersigned_at`, `assessed_at`, `opened_at`, `closed_at`, `lifted_at`).

A `FirmAdmin`-only test-driving capability advances or moves the clock by supplying `to_iso8601`; arbitrary target instants are allowed and there is no monotonicity constraint. A `to_iso8601` value without an explicit UTC offset is read as UTC; a missing or unparseable value fails with `ERR_INVALID_REQUEST`. Setting the clock performs a waiver-expiry sweep: every waiver still `SENT` whose `expires_at` is less than or equal to the new current time transitions to `EXPIRED` — the boundary is inclusive, so a waiver expiring exactly at the new time is swept. The capability's response reports the resulting `current_utc` and the list `expired_waiver_ids` of waivers swept by that call; `current_utc` is rendered with seconds precision when the target lands exactly on a whole second (matching this document's `2026-08-01T00:00:00Z` notation) and with three fractional digits otherwise.

### 2.6. Party Name Normalization and Phonetic Keys

All name comparison in the system rests on one normalization transform. Normalization of a string proceeds in three steps. First, the string is lowercased; every character that is not a lowercase letter, a digit, or a space is replaced with a single space; runs of whitespace are collapsed; and the result is trimmed. Second, trailing tokens are dropped repeatedly while the last remaining token is one of the twelve corporate suffixes `inc`, `incorporated`, `corp`, `corporation`, `co`, `company`, `llc`, `llp`, `lp`, `ltd`, `pc`, or `pllc`, continuing until no trailing token matches. Third, the surviving tokens are joined with single spaces to form the normalized result. The transform is exact string processing; no rounding or approximation is involved.

The phonetic key of a name is the four-character American Soundex of its normalized form with spaces removed and letters uppercased. The first letter is kept as-is. Each subsequent letter maps to a digit — B, F, P, or V to 1; C, G, J, K, Q, S, X, or Z to 2; D or T to 3; L to 4; M or N to 5; R to 6 — while vowels and the letters H, W, and Y are dropped. Consecutive duplicate codes produced by adjacent letters of the same code in the original string collapse into a single code. The result is padded on the right with zeros or truncated so that the key is exactly four characters long; a name whose normalized form is empty yields the all-zero key `0000`.

Normalization is applied at party creation to the `legal_name` (yielding the stored `normalized_name` and `phonetic_key`) and to every alias's `alias_name` (yielding its `normalized_alias`), and again at match time to conflict-check query strings, to candidate names, and to each prior-client string of a lateral sweep.

### 2.7. Monetary Precision, Integer Scores, and Boundary Conventions

All monetary quantities are integer cents. Where a calculation must round, it rounds half up. A letter's `fee_estimate_cents` is computed by multiplying each fee line's `hours` by its `rate_cents`, rounding each line's product half up to a whole cent first, and only then summing the per-line amounts — the order is pinned, per line before summation. The rejected reading (sum first, round once) diverges: two lines of 0.5 hours at 101 cents produce 51 + 51 = 102 cents under the pinned order but 101 under sum-then-round. Match scores are integers from 0 to 100, and the token-overlap channel of §3.4 floors its intermediate quotient to an integer.

Boundary conventions differ deliberately by rule, and each is stated where the rule lives; they are collected here for cross-reference. Retainer funding counts equality as funded: a held balance equal to the requirement is `FUNDED`. The match threshold is inclusive: a candidate scoring exactly the `match_threshold` becomes a hit. Credit bands use inclusive lower bounds: 740 is `PRIME`, 739 is `STANDARD`, 670 is `STANDARD`, 669 is `SUBPRIME`. Credit-assessment validity is strict on staleness: an assessment is stale only when current time is strictly later than `assessed_at` plus ninety days, so an assessment exactly ninety days old is still valid. Engagement-letter staleness uses the same strict convention over thirty days: a letter exactly thirty days past `issued_at` is still countersignable. Waiver expiry uses the opposite, inclusive, convention: a `SENT` waiver expires the moment current time reaches `expires_at`. Lateral employment intervals treat `lateral_employed_to` as an inclusive last day.

### 2.8. The Matter's Dual Status Dimensions

A matter carries two independent status dimensions on one row. The `lifecycle_status` dimension walks `INTAKE` → `OPEN` → `CLOSED`, with `INTAKE` → `DECLINED` as the early-exit branch; `CLOSED` and `DECLINED` are terminal. The `clearance_status` dimension — `UNCHECKED`, `HITS_PENDING`, `CLEARED`, `BLOCKED`, `WAIVED` — is not set by any caller; it is derived, and it has no terminal state because it remains recomputable even on `OPEN` matters.

The derivation looks at the hits of the matter's non-superseded conflict checks of both kinds and applies the first matching rule of a fixed precedence: (1) if any hit has `review_status` `CONFIRMED`, the matter is `BLOCKED`; (2) otherwise, if any hit is `PENDING`, the matter is `HITS_PENDING`; (3) otherwise, if any hit is `WAIVED`, the matter is `WAIVED`; (4) otherwise, if at least one `COMPLETED` non-superseded check exists, the matter is `CLEARED`; (5) otherwise the matter is `UNCHECKED`. The recompute runs after every conflict-check creation, every hit review, every waiver approval or revocation, every roster change (which supersedes intake checks), every lateral-sweep hit creation, and every hit staling. Each recompute that flips the derived value is a mutation of the matter row: `version` increments and `updated_at` refreshes.

Observable clearance flips therefore include: `UNCHECKED` → `HITS_PENDING` when a check or lateral sweep produces a pending hit; `UNCHECKED` → `CLEARED` when a check completes with zero hits; `HITS_PENDING` → `CLEARED` when the last pending hit is dismissed; `HITS_PENDING` → `BLOCKED` when a hit is confirmed; `BLOCKED` → `WAIVED` when a waiver approval waives the last confirmed hit; `WAIVED` → `BLOCKED` when a revocation un-waives a hit; `CLEARED` → `UNCHECKED` when a roster change supersedes all of the matter's intake checks so that no non-superseded checks remain; and `CLEARED` → `HITS_PENDING` or `WAIVED` → `HITS_PENDING` when a lateral sweep lands a new pending hit on a previously cleared or waived matter.

### 2.9. Ethical Wall Read Gating

Reads of a single matter are gated by that matter's ethical walls. When the caller belongs to an entity-backed attorney role — `ResponsibleAttorney` or `ConflictsPartner` — and their `X-User-ID` appears in the `excluded_attorney_ids` of any `ACTIVE` EthicalWall on the requested matter, the read is denied with `ERR_WALL_EXCLUDED` (HTTP 403). Callers in opaque roles and the matter's own client are never wall-blocked. Separately, an attorney whose `status` is `LATERAL_PENDING` may not read any matter at all; such a read is denied with the same `ERR_WALL_EXCLUDED`. The wall gate fires before ownership checks in the validation order of §2.11. Because the very existence of a wall is confidential, listing a matter's walls is restricted to `ConflictsPartner` and `FirmAdmin`.

### 2.10. Optimistic Concurrency Control

Two write operations participate in optimistic concurrency control over the matter row: amending a matter's intake fields (`PATCH /intake/matters/{id}`) and creating an engagement letter for a matter (`POST /intake/matters/{id}/engagement-letters`). Each such request must carry `expected_matter_version`, a non-optional input field holding the matter `version` the caller last observed. If the matter's current `version` no longer equals that value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A missing or non-integer `expected_matter_version` instead fails at the request-shape tier with `ERR_INVALID_REQUEST`; only an integer value is ever compared against the matter's `version`. The rationale differs by operation but the mechanism is one: on amendment, another writer may have changed the roster or details, each of which legitimately supersedes the matter's open conflict checks, leaving the caller's picture of the intake stale; on letter creation, the create legitimately supersedes any existing `DRAFT` or `ISSUED` letter, so a caller working from an older matter version would unknowingly supersede terms it never saw. Endpoints other than these two take no version field.

### 2.11. Nested Resource Resolution and Validation Order

Requests that address nested resources resolve path identifiers strictly left to right — the matter first, then the letter, waiver, wall, deposit, hit, party, or attorney beneath it — and the first identifier that does not resolve fails the whole request with `ERR_NOT_FOUND` (HTTP 404). Foreign-key fields in request bodies — `client_party_id`, `responsible_attorney_id`, `party_id`, `conflict_hit_id`, and `attorney_id` — must likewise resolve to existing resources or the request fails with `ERR_NOT_FOUND`.

Beyond resolution, every request passes through twelve ordered validation tiers, and the first failure wins. The tiers are: (1) header authentication, failing as `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint and action, failing as `ERR_FORBIDDEN`; (3) existence of path and body references, failing as `ERR_NOT_FOUND`; (4) the ethical-wall read gate of §2.9, failing as `ERR_WALL_EXCLUDED`; (5) ownership — attorney-scoped operations failing as `ERR_NOT_RESPONSIBLE_ATTORNEY` and client-scoped ownership mismatches failing as `ERR_FORBIDDEN`; (6) state and concurrency gates, failing as `ERR_MATTER_NOT_INTAKE`, `ERR_MATTER_NOT_OPEN`, `ERR_MATTER_TERMINAL`, `ERR_HIT_NOT_PENDING`, `ERR_WAIVER_INVALID_STATE`, `ERR_LETTER_INVALID_STATE`, `ERR_WALL_INVALID_STATE`, or `ERR_STALE_VERSION`; (7) business safety, failing as `ERR_MATTER_CLEARANCE_BLOCKED`, `ERR_SOD_SELF_APPROVAL`, `ERR_ATTORNEY_ADVERSE_OVERLAP`, or `ERR_ATTORNEY_NOT_ACTIVE`; (8) business temporal rules, failing as `ERR_LETTER_STALE`; (9) business referential rules, failing as `ERR_CHECK_SUPERSEDED` or `ERR_HIT_NOT_CONFIRMED`; (10) business constraints, failing as `ERR_WAIVER_ACTIVE_EXISTS`, `ERR_WALL_INVALID_STATE`, `ERR_ATTORNEY_ALREADY_EXCLUDED`, `ERR_ATTORNEY_NOT_EXCLUDED`, or `ERR_PARTY_ALREADY_ON_MATTER`; (11) business fiscal rules, failing as `ERR_CREDIT_MISSING`, `ERR_CREDIT_STALE`, `ERR_RETAINER_UNFUNDED`, or `ERR_REFUND_EXCEEDS_BALANCE`; and (12) request shape — including an unrecognized `action` value on a transition endpoint — failing as `ERR_INVALID_REQUEST`. The ordering is observable: a stale-version rejection at tier 6 masks a clearance problem at tier 7 on the same request, and a malformed payload addressed to a nonexistent matter returns `ERR_NOT_FOUND`, never `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Registering Parties and the Affiliate Tree

Parties are the anchor records of conflicts analysis — clients, adversaries, witnesses, and affiliates alike. A `FirmAdmin` registers a party by supplying its `legal_name`, a `party_type` of `CORPORATION`, `INDIVIDUAL`, `PARTNERSHIP`, `TRUST`, or `GOVERNMENT`, an optional `aliases` list, and an optional `affiliate_of_id`. Each alias is recorded as an object pairing the supplied `alias_name` with a server-computed `normalized_alias` produced by the transform of §2.6; when `aliases` is omitted it defaults to an empty list. An alias whose normalized value duplicates the party's own `normalized_name`, or the normalized value of another alias on the same party, is rejected with `ERR_INVALID_REQUEST`. The party's `normalized_name` and four-character `phonetic_key` are computed at creation and stored.

Corporate families are expressed through `affiliate_of_id`. When omitted it defaults to null and the party is a root of its own affiliate tree; when present it must reference an already-existing party, or creation fails with `ERR_NOT_FOUND`. Because an affiliate may only point at a party created earlier, affiliate chains are acyclic by construction and no cycle check is ever needed at write time.

Party search accepts an optional `q` that is lowercased (but not otherwise normalized) and filters on substrings of `normalized_name`, plus optional `party_type` and `affiliate_of_id` filters — the latter returns the parties naming the given party as their parent, giving reverse reach down the affiliate tree. A separate view lists the roster rows that name a given party, providing the reverse reach from party to matters. A `Client` caller may read only its own party record: the requested party's `id` must equal the caller's `X-User-ID`, otherwise the read fails with `ERR_FORBIDDEN`.

### 3.2. Attorney Onboarding and the Lateral Hire Sweep

A `FirmAdmin` onboards attorneys with a `full_name`, a `bar_number`, a `practice_group` of `LITIGATION`, `CORPORATE`, `TAX`, or `IP`, and a `hire_type` that defaults to `INTERNAL`. Every attorney record exposes a `status` of `ACTIVE` or `LATERAL_PENDING`, and reading an attorney returns that status together with the disclosed `prior_client_names`.

Lateral hiring carries extra obligations. When `hire_type` is `LATERAL`, three further inputs are required: `lateral_employed_from` and `lateral_employed_to`, calendar dates in year-month-day form whose last day counts as inclusive in every overlap test, and `prior_client_names`, a list of prior-firm client name strings that must be present though it may be empty. Omitting any of the three fails with `ERR_INVALID_REQUEST`. For an `INTERNAL` hire the lateral date fields are stored as null, and `prior_client_names` defaults to an empty list when omitted.

Onboarding a lateral synchronously runs the lateral sweep. For each string in `prior_client_names`, the system runs a `PHONETIC`-variant match with a threshold of 60 (the mechanics of §3.4) against parties appearing on matters whose `lifecycle_status` is `INTAKE` or `OPEN`, then applies an employment-overlap filter at day granularity. A candidate matter overlaps the lateral's prior employment when its activity start day — the `opened_at` day for an `OPEN` or `CLOSED` matter, or the `created_at` day for an `INTAKE` matter, which counts as an active prospect — is on or before `lateral_employed_to`, and either the matter has no `closed_at` or its closing day is on or after `lateral_employed_from`.

For every surviving (name, matter) pair, the system creates a conflict check of `check_kind` `LATERAL_SWEEP` on that existing matter — never on any new matter — with its `search_variant` fixed to `PHONETIC`, its `match_threshold` at 60, its `lateral_attorney_id` attributing the onboarding attorney, and its `query_label` recording the prior-client string that produced it; the sweep's hits carry the same `lateral_attorney_id` attribution, which the activation gate below reads. Each affected matter's `clearance_status` is recomputed. The new attorney starts `LATERAL_PENDING` if the sweep created at least one hit, and `ACTIVE` otherwise; `INTERNAL` hires always start `ACTIVE`.

Activation is automatic. After every lateral-sweep hit review, the system counts that attorney's sweep hits still `PENDING`; when the count reaches zero, the attorney flips from `LATERAL_PENDING` to `ACTIVE` with its `version` incremented, and the imputation cascade runs immediately: for each `CONFIRMED` sweep hit's matter, if an `ACTIVE` ethical wall already exists on that matter, the attorney is appended to its `excluded_attorney_ids` unless already present; otherwise a new wall is created on that matter with reason `LATERAL_IMPUTATION` and an `excluded_attorney_ids` list containing exactly that attorney.

### 3.3. Opening a Matter and Maintaining Its Roster

An `IntakeSpecialist` opens intake for a new matter by supplying `client_party_id`, `responsible_attorney_id`, a `practice_group` from the same four-value enumeration as attorneys, and an optional `matter_title` that defaults to an empty string. Both foreign keys must resolve or creation fails with `ERR_NOT_FOUND`. A new matter starts with `lifecycle_status` `INTAKE` and `clearance_status` `UNCHECKED`; `matter_number` stays null until countersignature, `opened_at` stays null until the same event, `closed_at` stays null unless the matter is later closed, and `decline_reason` starts empty.

Two safety gates guard the choice of responsible attorney, both at creation and again whenever a later amendment changes `responsible_attorney_id`. First, the adverse-overlap rule rejects the assignment with `ERR_ATTORNEY_ADVERSE_OVERLAP` when that attorney is already the responsible attorney on another matter currently `OPEN` and either the new matter's client appears on that other matter's roster in an `ADVERSE` role, or that other matter's client appears on the target matter's roster as `ADVERSE`. The other matter's activity window is the half-open interval from its `opened_at` up to but not including its `closed_at`, so a closed matter whose `closed_at` is at or before the current time does not overlap. Second, the referenced attorney's `status` must be `ACTIVE`; assigning a `LATERAL_PENDING` attorney is rejected with `ERR_ATTORNEY_NOT_ACTIVE`. The identical adverse-overlap evaluation also guards roster additions, where it runs against the roster as it would stand after the addition — the candidate row counts.

Roster rows bind parties to the matter. Adding one takes a `party_id` and a `role_in_matter` of `ADVERSE`, `WITNESS`, or `RELATED`, and stores the row with its `matter_id`; adding a party already on the roster fails with `ERR_PARTY_ALREADY_ON_MATTER`. Additions are accepted while the matter is `INTAKE` or `OPEN`; on a `CLOSED` or `DECLINED` matter they fail with `ERR_MATTER_TERMINAL`. Because the roster feeds the conflict-search query set, every addition supersedes the matter's `COMPLETED` checks of `INTAKE` kind, moves any of their hits still `PENDING` to `STALE` with each staled hit's `version` incremented, recomputes `clearance_status`, and increments the matter's `version`.

Amendments follow the same discipline. An `IntakeSpecialist` may amend `matter_title`, `practice_group`, or `responsible_attorney_id`, and every such request must carry the OCC token `expected_matter_version` described in §2.10. A field explicitly supplied as null is treated as absent and left unchanged. Re-assigning the responsible attorney re-runs both assignment gates and, as a roster-affecting edit, supersedes the matter's `COMPLETED` intake checks. Amendments are rejected with `ERR_MATTER_TERMINAL` once the matter is `CLOSED` or `DECLINED`, and every successful amendment increments the matter's `version`.

Declining and closing drive the lifecycle dimension. A `ConflictsPartner` declines a matter by posting an `action` of `DECLINE` with an optional `reason`, which is stored as `decline_reason`; declining from any state other than `INTAKE` fails with `ERR_MATTER_NOT_INTAKE`. Closing takes an `action` of `CLOSE`, requires the matter to be `OPEN` (else `ERR_MATTER_NOT_OPEN`), and may be performed by a `ConflictsPartner` or by the matter's responsible attorney — a `ResponsibleAttorney` caller whose `X-User-ID` differs from the matter's `responsible_attorney_id` is rejected with `ERR_NOT_RESPONSIBLE_ATTORNEY`. A successful close stamps `closed_at` from the logical clock. Both transitions increment the matter's `version`.

The matter index lists matters with optional filters `client_party_id`, `responsible_attorney_id`, `lifecycle_status`, and `clearance_status`, doubling as the reverse-reach view from a client party or an attorney to their matters. Reading a single matter is subject to the wall gate of §2.9, and a `Client` caller may read only matters where its `X-User-ID` equals the matter's `client_party_id` — any other matter read by a client fails with `ERR_FORBIDDEN`.

### 3.4. Conflict Checks, Match Scoring, and Hit Review

Running a conflict check is available to an `IntakeSpecialist` or a `ResponsibleAttorney` while the matter is `INTAKE` or `OPEN`; on a terminal matter the attempt fails with `ERR_MATTER_TERMINAL`. The caller chooses a `search_variant` of `STRICT` or `PHONETIC` and may supply a `match_threshold` — an integer from 0 to 100 inclusive, defaulting to 60 — below which candidates are discarded. The check executes synchronously and is created already `COMPLETED`, with `check_kind` `INTAKE`, both `lateral_attorney_id` and `query_label` null, and `hit_count` recording how many hits it produced. Running a check through this endpoint is itself a mutation of the matter row: the matter's `version` increments and `updated_at` refreshes, in addition to any increment from a clearance flip (§2.8).

The query subjects of an intake check are the matter's client party plus every party on its roster. The candidate pool is every party that appears — as client or as roster member — on any other matter whose `lifecycle_status` is `INTAKE` or `OPEN`; the check's own matter is always excluded, so a hit's `matched_matter_id` never equals the matter the check ran for.

Each query–candidate pair is scored through name channels. The direct channel scores 100 when the normalized query string equals the candidate's `normalized_name`, and otherwise falls back to token overlap against it. The alias channel scores 100 when the normalized query equals any of the candidate's `normalized_alias` values, otherwise falls back to token overlap against each alias and keeps the best alias result. Token overlap between two names is the floored integer of one hundred times the number of tokens shared by both names divided by the larger of the two token counts, and it is counted only when that value is at least 80 — below that floor it contributes 0. Under the `STRICT` variant the base score is simply the higher of the direct and alias channels; the phonetic channel is ignored, so names that sound alike but share no tokens — "Smyth" versus "Smith" — score 0 and produce no hit. Under the `PHONETIC` variant a third channel contributes 70 whenever the query string's Soundex key equals the candidate's `phonetic_key`, and the base score is the best of the three channels — identical inputs can therefore yield different hit sets under the two variants. When the direct and alias channels tie on score the direct channel is preferred, and a hit produced by the phonetic channel alone records `matched_via` `DIRECT`, since the Soundex key derives from the normalized name.

Every matched candidate then expands through its affiliate tree. Each descendant party reachable by following `affiliate_of_id` links downward from the candidate, at a depth of one to three levels, is emitted as an additional hit candidate whose score is the base score discounted by ten points per level of depth; when several paths reach the same descendant, only the highest score is kept. A candidate becomes a hit exactly when its score is greater than or equal to the `match_threshold` — the boundary is inclusive. Every hit records its producing `check_id`, the `matched_party_id`, the `matched_matter_id`, the `matched_via` channel — `DIRECT` for a `normalized_name` match, `ALIAS` for an alias-value match, `AFFILIATE` for affiliate-tree expansion, `LATERAL` for a lateral-sweep name match — the integer `match_score`, and a `review_status` that begins at `PENDING` and may move to `CONFIRMED`, `DISMISSED`, `WAIVED`, or `STALE`. A new hit's `reviewed_by_attorney_id` is null and its `review_note` empty. When several derivations reach the same (matched party, matched matter) pair with equal scores, the kept `matched_via` prefers `DIRECT` over `ALIAS` over `LATERAL` over `AFFILIATE`.

Hits are emitted — and the hit listing is ordered — deterministically: by `match_score` descending, then by the matched party's `created_at` ascending, then by the matched matter's `created_at` ascending; the sort is stable, so hits still tied after all three keys keep their creation order. The listing endpoint accepts the filters `check_id`, `matched_party_id`, `matched_matter_id`, and `review_status`, which also serve as the reverse reach from a check, party, or matter to its hits.

Supersession keeps only the freshest evidence. Creating a new conflict check supersedes the prior `COMPLETED` check of the same `check_kind` on the same matter — intake checks never supersede sweep checks, nor the reverse — and a roster addition supersedes `INTAKE`-kind checks as §3.3 describes. Supersession moves the older check from `COMPLETED` to `SUPERSEDED`, cascades every one of its hits still `PENDING` to `STALE` with each such hit's `version` incremented, and triggers a clearance recompute on the matter.

Review is the attorney's judgment call. A hit may be reviewed by the matter's responsible attorney or by any `ConflictsPartner`; the reviewer submits a `decision` of `CONFIRMED` or `DISMISSED` with an optional `note`, stored verbatim as `review_note` (when no `note` is supplied, `review_note` stays empty). The hit must still be `PENDING` — reviewing a hit already `CONFIRMED`, `DISMISSED`, `WAIVED`, or `STALE` fails with `ERR_HIT_NOT_PENDING` — and a `ResponsibleAttorney` caller who is not the responsible attorney of the check's matter is rejected with `ERR_NOT_RESPONSIBLE_ATTORNEY`. A successful review stamps `reviewed_by_attorney_id` with the caller's identifier and recomputes the clearance of the check's matter. When the reviewed hit belonged to a lateral sweep and it was that lateral attorney's last `PENDING` sweep hit, the activation and wall cascade of §3.2 fires as part of the same request.

### 3.5. Ethical Walls and Exclusion Management

Ethical walls hard-block read access and are administered exclusively by a `ConflictsPartner`. Creating one on a matter takes a `reason` of `CONFLICT_CONFIRMED`, `LATERAL_IMPUTATION`, or `CLIENT_REQUEST`, an `excluded_attorney_ids` list that must contain at least one entry (duplicates are removed server-side and the given order is preserved), and an optional `memo` that defaults to an empty string. The exclusion entries are stored as given; they are not resolved against the attorney table at creation. The wall is born `ACTIVE` and takes effect at once: excluded attorneys lose read access to the matter immediately under the gate of §2.9. At most one wall per matter may be `ACTIVE` — attempting a second fails with `ERR_WALL_INVALID_STATE` — and wall creation on a `CLOSED` or `DECLINED` matter fails with `ERR_MATTER_TERMINAL`. Wall existence is itself confidential, so only `ConflictsPartner` and `FirmAdmin` may list a matter's walls.

While a wall is `ACTIVE`, its exclusion list can be amended in place: an `EXCLUDE` action carrying an `attorney_id` appends that attorney, failing with `ERR_ATTORNEY_ALREADY_EXCLUDED` if the attorney is already listed, and a `RELEASE` action removes the named attorney, failing with `ERR_ATTORNEY_NOT_EXCLUDED` if the attorney is not currently listed. Both actions leave the wall `ACTIVE` and increment the wall's `version`. A `LIFT` action — available from `ACTIVE` only — moves the wall to `LIFTED`, stamps `lifted_at` from the logical clock, and immediately restores read access to every formerly excluded attorney. `LIFT` takes no `attorney_id`; one supplied with it is neither resolved nor stored. A second lift, or any `EXCLUDE` or `RELEASE` attempted after a lift, is rejected with `ERR_WALL_INVALID_STATE`. Walls created automatically by lateral activation (§3.2) obey exactly the same rules as manually created ones.

### 3.6. Waiver Requests and Client Consent

When review confirms a hit, the matter's responsible attorney may seek the client's informed waiver. Drafting a waiver request on the matter references the `conflict_hit_id` and lays out the `proposed_terms` to be presented to the client. The referenced hit must be `CONFIRMED` — anything else fails with `ERR_HIT_NOT_CONFIRMED` — and the check that produced it must not be `SUPERSEDED`, or the draft fails with `ERR_CHECK_SUPERSEDED`; of these two referential gates, supersession is evaluated first when both would fail. A `ResponsibleAttorney` caller who is not the matter's responsible attorney is rejected with `ERR_NOT_RESPONSIBLE_ATTORNEY`. The referenced hit is not required to belong to the matter named in the path; no cross-matter check is performed. At most one waiver per hit may be active at a time, where active means `DRAFT`, `SENT`, `CONSENTED`, or `APPROVED`; a second attempt against the same hit fails with `ERR_WAIVER_ACTIVE_EXISTS`. The new waiver records the caller as `requested_by_attorney_id`, starts in `DRAFT`, and leaves `sent_at`, `expires_at`, `consent_document_ref`, and `approved_by_attorney_id` null and `decline_reason` empty.

Sending is the requester's own act. A `SEND` action requires the waiver to be in `DRAFT` (otherwise `ERR_WAIVER_INVALID_STATE`), requires the caller's `X-User-ID` to equal `requested_by_attorney_id` (otherwise `ERR_NOT_RESPONSIBLE_ATTORNEY`), and re-verifies that the referenced hit is still `CONFIRMED` (otherwise `ERR_HIT_NOT_CONFIRMED`). A successful send stamps `sent_at` from the logical clock and sets `expires_at` exactly thirty days later.

From `SENT`, the ball is with the client. The caller's `X-User-ID` must equal the matter's `client_party_id`, or the attempt fails with `ERR_FORBIDDEN`. Recording consent — a `RECORD_CONSENT` action — requires a `consent_document_ref` (an absent, empty, or non-string value fails with `ERR_INVALID_REQUEST`), stores the reference, and moves the waiver to `CONSENTED`. Declining stores the supplied `decline_reason` and moves the waiver to `DECLINED`. Meanwhile the clock watches the deadline: a waiver still `SENT` when the logical clock reaches or passes `expires_at` is swept to `EXPIRED` by the next clock-set, the boundary inclusive, and the sweep never alters clearance because a `SENT` waiver has waived nothing yet. A consent attempt arriving after the sweep fails with `ERR_WAIVER_INVALID_STATE`, since the waiver is no longer `SENT`.

An `APPROVE` action belongs to a `ConflictsPartner` and is bound by segregation of duties: the approver's `X-User-ID` must differ from the waiver's `requested_by_attorney_id`, or the request fails with `ERR_SOD_SELF_APPROVAL`. Approving from `CONSENTED` stamps `approved_by_attorney_id` with the caller, cascades the referenced hit from `CONFIRMED` to `WAIVED`, and recomputes the matter's clearance — which becomes `WAIVED` when no `CONFIRMED` hits remain.

A `REVOKE` action unwinds in proportion to how far the waiver got. The owning client or a `ConflictsPartner` may revoke from either `CONSENTED` or `APPROVED` — from any other state the transition fails with `ERR_WAIVER_INVALID_STATE`. Revoking a merely `CONSENTED` waiver changes no hit state, because the hit was never waived. Revoking an `APPROVED` waiver unwinds the whole chain: the referenced hit returns from `WAIVED` to `CONFIRMED`, the matter's clearance recomputes to `BLOCKED`, and every engagement letter of the matter still `ISSUED` is voided to `VOID`, while letters in `DRAFT` or already `COUNTERSIGNED` are untouched. All waiver lifecycle payloads accept an optional `note`.

Redrafting closes the cycle. From `DECLINED`, `REVOKED`, or `EXPIRED`, the original requester — and only the requester, on pain of `ERR_NOT_RESPONSIBLE_ATTORNEY` — may issue a `REDRAFT` action returning the waiver to `DRAFT`. Redrafting resets `sent_at`, `expires_at`, `consent_document_ref`, `decline_reason`, and `approved_by_attorney_id` to null or empty, and the same payload may supply replacement `proposed_terms`. A waiver's full history stays reachable both per hit and per matter through the waiver listing views.

### 3.7. Engagement Letters and the Path to an Open Matter

An engagement letter is drafted against an `INTAKE` matter by a `ResponsibleAttorney` or an `IntakeSpecialist`. The draft carries `scope_text`, a `fee_lines` list with at least one line — each line a `description`, an `hours` number greater than zero, and a `rate_cents` integer greater than zero — and the OCC token `expected_matter_version` of §2.10. Creating a letter on a matter that has left `INTAKE` fails with `ERR_MATTER_NOT_INTAKE`, and malformed fee lines fail with `ERR_INVALID_REQUEST`. The server computes `fee_estimate_cents` under the pinned per-line rounding of §2.7. The new letter starts `DRAFT` with `issued_at` and `countersigned_at` null; its creation supersedes any existing `DRAFT` or `ISSUED` letter of the same matter to `SUPERSEDED` — the OCC check is precisely what stops a caller from unknowingly superseding terms it never saw — and increments the matter's `version`.

Issuing is the responsible attorney's act: an `ISSUE` action requires the letter to be `DRAFT` (otherwise `ERR_LETTER_INVALID_STATE`), the matter still `INTAKE` (otherwise `ERR_MATTER_NOT_INTAKE`), and a `ResponsibleAttorney` caller to be the matter's `responsible_attorney_id` (otherwise `ERR_NOT_RESPONSIBLE_ATTORNEY`). Issuance stamps `issued_at` from the logical clock. It also stands up the money side: if the matter has no retainer deposit yet, one is created — exactly one deposit ever exists per matter — with `required_cents` computed per §3.8 and status `PENDING`; if a deposit already exists, issuance instead recomputes its `required_cents` against the newly issued letter and re-derives its status.

Countersignature — a `COUNTERSIGN` action by the owning client — is the moment intake becomes an open matter, and it is guarded by a strict gate chain evaluated in order. The caller must be the owning client whose `X-User-ID` equals the matter's `client_party_id`, else `ERR_FORBIDDEN`. The letter must be `ISSUED`, else `ERR_LETTER_INVALID_STATE`. The matter's `clearance_status` must be `CLEARED` or `WAIVED`, else `ERR_MATTER_CLEARANCE_BLOCKED`. The letter must not be stale: the current logical time must be at most thirty days after `issued_at` — exactly thirty days is still countersignable, anything later fails with `ERR_LETTER_STALE`. At least one credit assessment must exist for the matter, else `ERR_CREDIT_MISSING`. The latest assessment must still be valid under the ninety-day rule of §3.8, else `ERR_CREDIT_STALE`. And the retainer deposit must stand `FUNDED`, else `ERR_RETAINER_UNFUNDED`.

On a successful countersign, the letter becomes `COUNTERSIGNED` with `countersigned_at` stamped, and the matter flips `INTAKE` → `OPEN` in the same transaction: its `matter_number` is assigned exactly once — the letter "M" followed by a zero-padded six-digit counter handed out in countersign completion order across the whole system — and `opened_at` records the logical time. Billing setup is complete at that instant.

Voiding is the escape hatch. A `ConflictsPartner` may void a letter from `DRAFT` or `ISSUED`; from any other state the attempt fails with `ERR_LETTER_INVALID_STATE`. Independently, the system itself voids every `ISSUED` letter of a matter when an approved waiver on that matter is revoked (§3.6), while `DRAFT` and `COUNTERSIGNED` letters survive that cascade. Letters are listed per matter, and a `Client` caller sees only letters of its own matters.

### 3.8. Credit Assessment and Retainer Funding

A `BillingClerk` records a credit assessment for a matter by supplying a `score` between 300 and 850 inclusive; the score must be an integer, and a non-integer or out-of-range value fails with `ERR_INVALID_REQUEST`. The server stamps `assessed_at` from the logical clock and derives the `band`: `PRIME` when the score is at least 740, `STANDARD` from 670 through 739, and `SUBPRIME` below 670 — so 740 is `PRIME`, 739 is `STANDARD`, 670 is `STANDARD`, and 669 is `SUBPRIME`. An assessment remains valid for ninety days: it is stale only when the current logical time is strictly later than `assessed_at` plus ninety days, so an assessment exactly ninety days old is still valid. Recording a new assessment recomputes the matter's retainer requirement whenever a deposit already exists and re-derives the deposit's status.

The retainer requirement combines credit and fee data under one pinned interpretation. The governing band is the band of the valid assessment with the latest `assessed_at`, with a tie on `assessed_at` broken in favor of the later `created_at`; when no valid assessment exists, the band defaults conservatively to `SUBPRIME`. The rejected alternative — picking the client-favorable best band among the valid assessments — is not permitted: with an older `PRIME` assessment and a newer `STANDARD` assessment both inside their validity windows, the requirement follows the newer assessment's band and multiplies by two, not one. The fee base is the `fee_estimate_cents` of the matter's latest-created engagement letter in `DRAFT` or `ISSUED`; when no such letter exists the fee base is zero, so the requirement rests at the 50000-cent floor. The raw requirement is the fee base multiplied by the band's months multiplier — one for `PRIME`, two for `STANDARD`, three for `SUBPRIME` — and the stored `required_cents` is that raw value clamped to a floor of 50000 cents and a ceiling of 10000000 cents.

The deposit itself tracks three counters. `funded_total_cents` and `refunded_total_cents` are cumulative sums that start at zero; `received_cents` is the currently held balance, computed as funded minus refunded. The deposit's `status` is re-derived after every mutation: `PENDING` when nothing is held, `PARTIALLY_FUNDED` when the held balance is greater than zero but below the requirement, and `FUNDED` when the held balance is greater than or equal to the requirement — equality counts as funded.

Funding and refunding are `BillingClerk` operations carrying an `action` of `FUND` or `REFUND` and an `amount_cents`. A funding amount must be greater than zero, else `ERR_INVALID_REQUEST`; it adds to `funded_total_cents`, recomputes `received_cents`, and re-derives status, which may move the deposit `PENDING` → `PARTIALLY_FUNDED`, `PARTIALLY_FUNDED` → `FUNDED`, or `PENDING` → `FUNDED` in a single call when the amount covers the entire requirement. A refund must likewise be greater than zero and may not exceed the held balance — an amount above `received_cents` fails with `ERR_REFUND_EXCEEDS_BALANCE`; it adds to `refunded_total_cents` and re-derives status, cycling `FUNDED` → `PENDING` or `PARTIALLY_FUNDED` → `PENDING` when the full balance is returned, and dropping `FUNDED` → `PARTIALLY_FUNDED` on a partial refund. The same `FUNDED` → `PARTIALLY_FUNDED` regression fires automatically — with no client call — whenever a recomputed requirement rises above the held balance after a new credit assessment or a new letter issuance. The deposit view returns an array of zero or one element for the matter, created only at first issuance, and an owning `Client` may read it for its own matters.

## 4. Endpoint Definitions

Operations that create a new resource — a party, attorney, matter, roster entry, conflict check, ethical wall, waiver request, engagement letter, or credit assessment — return `201 Created`. Reads, amendments, reviews, lifecycle transitions of every kind, and the clock-setting capability return `200 OK`. The table below is a routing summary only; request payloads, preconditions, cascades, and error conditions are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/intake/parties` | Create a party; computes normalized name and phonetic key | FirmAdmin |
| GET | `/intake/parties/{id}` | Read one party (Client reads only its own record) | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk, Client |
| GET | `/intake/parties` | List/search parties (name substring, type, affiliate filters) | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk |
| GET | `/intake/parties/{id}/matter-parties` | List roster rows naming this party | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk |
| POST | `/intake/attorneys` | Onboard an attorney; LATERAL hires trigger the lateral sweep | FirmAdmin |
| GET | `/intake/attorneys/{id}` | Read one attorney (incl. status and prior client names) | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk |
| POST | `/intake/matters` | Open intake for a new matter | IntakeSpecialist |
| GET | `/intake/matters` | List/filter matters; reverse reach for client and attorney | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk |
| GET | `/intake/matters/{id}` | Read one matter (wall-gated; Client reads only its own) | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk, Client |
| PATCH | `/intake/matters/{id}` | Amend intake fields (optimistic concurrency) | IntakeSpecialist |
| POST | `/intake/matters/{id}/parties` | Add a roster party; supersedes intake checks | IntakeSpecialist |
| GET | `/intake/matters/{id}/parties` | List the matter's roster | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk |
| POST | `/intake/matters/{id}/transition` | Matter lifecycle actions: DECLINE or CLOSE | ResponsibleAttorney, ConflictsPartner |
| GET | `/intake/matters/{id}/conflict-checks` | List the matter's conflict checks (both kinds) | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk |
| POST | `/intake/matters/{id}/conflict-checks` | Run a conflict check; supersedes the prior intake check | IntakeSpecialist, ResponsibleAttorney |
| GET | `/intake/conflict-hits` | List hits (score-ordered; filterable by check, party, matter, status) | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner |
| GET | `/intake/conflict-hits/{id}` | Read one hit | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner |
| GET | `/intake/conflict-hits/{id}/waiver-requests` | List waivers targeting this hit (all statuses) | ResponsibleAttorney, ConflictsPartner, FirmAdmin |
| POST | `/intake/conflict-hits/{id}/review` | Review a PENDING hit (confirm or dismiss) | ResponsibleAttorney, ConflictsPartner |
| POST | `/intake/matters/{id}/ethical-walls` | Create an ACTIVE ethical wall on the matter | ConflictsPartner |
| GET | `/intake/matters/{id}/ethical-walls` | List the matter's walls (existence is confidential) | ConflictsPartner, FirmAdmin |
| POST | `/intake/ethical-walls/{id}/transition` | Wall actions: EXCLUDE, RELEASE, or LIFT | ConflictsPartner |
| POST | `/intake/matters/{id}/waiver-requests` | Draft a waiver for a CONFIRMED hit | ResponsibleAttorney |
| GET | `/intake/matters/{id}/waiver-requests` | List the matter's waiver requests | ResponsibleAttorney, ConflictsPartner, FirmAdmin |
| POST | `/intake/waiver-requests/{id}/transition` | Waiver lifecycle: SEND, RECORD_CONSENT, DECLINE, APPROVE, REVOKE, REDRAFT | ResponsibleAttorney, ConflictsPartner, Client |
| POST | `/intake/matters/{id}/engagement-letters` | Create a DRAFT letter (optimistic concurrency; supersedes prior drafts) | ResponsibleAttorney, IntakeSpecialist |
| GET | `/intake/matters/{id}/engagement-letters` | List the matter's letters (Client: own matters only) | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk, Client |
| POST | `/intake/engagement-letters/{id}/transition` | Letter lifecycle: ISSUE, COUNTERSIGN, or VOID | ResponsibleAttorney, Client, ConflictsPartner |
| POST | `/intake/matters/{id}/credit-assessments` | Record a credit assessment; recomputes retainer requirement | BillingClerk |
| GET | `/intake/matters/{id}/credit-assessments` | List the matter's credit assessments | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk |
| GET | `/intake/matters/{id}/retainer-deposits` | The matter's deposit (array of zero or one) | FirmAdmin, IntakeSpecialist, ResponsibleAttorney, ConflictsPartner, BillingClerk, Client |
| POST | `/intake/retainer-deposits/{id}/transition` | Fund or refund the deposit | BillingClerk |
| POST | `/_clock/set_current_utc` | Set the logical clock; sweeps expired SENT waivers | FirmAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_WALL_EXCLUDED` | 403 Forbidden |
| `ERR_NOT_RESPONSIBLE_ATTORNEY` | 403 Forbidden |
| `ERR_SOD_SELF_APPROVAL` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MATTER_NOT_INTAKE` | 409 Conflict |
| `ERR_MATTER_NOT_OPEN` | 409 Conflict |
| `ERR_MATTER_TERMINAL` | 409 Conflict |
| `ERR_CHECK_SUPERSEDED` | 409 Conflict |
| `ERR_HIT_NOT_PENDING` | 409 Conflict |
| `ERR_HIT_NOT_CONFIRMED` | 422 Unprocessable Entity |
| `ERR_WAIVER_INVALID_STATE` | 409 Conflict |
| `ERR_WAIVER_ACTIVE_EXISTS` | 409 Conflict |
| `ERR_LETTER_INVALID_STATE` | 409 Conflict |
| `ERR_LETTER_STALE` | 422 Unprocessable Entity |
| `ERR_MATTER_CLEARANCE_BLOCKED` | 422 Unprocessable Entity |
| `ERR_CREDIT_MISSING` | 422 Unprocessable Entity |
| `ERR_CREDIT_STALE` | 422 Unprocessable Entity |
| `ERR_RETAINER_UNFUNDED` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_WALL_INVALID_STATE` | 409 Conflict |
| `ERR_ATTORNEY_ALREADY_EXCLUDED` | 409 Conflict |
| `ERR_ATTORNEY_NOT_EXCLUDED` | 409 Conflict |
| `ERR_ATTORNEY_ADVERSE_OVERLAP` | 422 Unprocessable Entity |
| `ERR_ATTORNEY_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_PARTY_ALREADY_ON_MATTER` | 409 Conflict |
