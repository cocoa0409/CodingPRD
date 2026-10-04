# Patent Trial Proceedings API — Product Requirements Document

## 1. Introduction

Post-grant review before the Patent Trial and Appeal Board is a statutory machine: every step — petition filing, the institution decision, briefing, amendment practice, oral hearing, and the final written decision — runs against hard deadlines and threshold standards, and every ruling cascades into parallel district-court litigation through stays and estoppel. This document specifies an API for administering that docket end to end. It covers petition intake challenging issued patent claims on limited statutory grounds, an institution decision made within a fixed window under likelihood-of-success thresholds and discretionary-denial factors informed by parallel litigation timing, a sequenced trial schedule with patent owner response, petitioner reply, sur-reply, expert declarations and limited discovery, claim construction and amendment practice during the proceeding, oral hearing logistics, and the final written decision with its estoppel consequences, appeal to the federal appellate court, and remand handling.

The system serves five distinct actors with deliberately disjoint write surfaces: a docketing administrator who registers the record and operates the clock, an administrative patent judge panel that adjudicates, counsel for the petitioner and counsel for the patent owner who drive the trial, and a federal appellate clerk who enters dispositions. Because the docket is a legal record, the API is built around immutable event records for decisions, explicit state machines for every mutable entity, optimistic concurrency on the writes that interleave with system cascades, and a logical clock that pins every statutory deadline to a deterministic timeline.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. If either header is missing or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS`. The system recognizes exactly five roles, spelled as follows: `PlatformAdmin`, `BoardPanel`, `Petitioner`, `PatentOwner`, and `AppealsCourt`.

`PlatformAdmin` is the docketing administrator: it registers parties, patents, hearing rooms, and litigation dockets, and it alone operates the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

`BoardPanel` is the administrative patent judge panel: it accords filing dates, decides institution, rules on discovery and amendments, schedules and holds hearings, and issues final written decisions. When `X-User-Role` is `BoardPanel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `lead_judge_user_id` on the `InstitutionDecision` and `Proceeding` a panel member decides — but does not compare it to any entity's `id`.

`Petitioner` is counsel for the petitioner. When `X-User-Role` is `Petitioner`, `X-User-ID` is the `id` of the acting `Party` — a party whose `party_type` is `PETITIONER`. Ownership checks on any resource that references a `Party` compare the resource's foreign-key field to `X-User-ID`: a petition's `petitioner_id`, for instance, must equal the caller's `X-User-ID` at filing time.

`PatentOwner` is counsel for the patent owner. When `X-User-Role` is `PatentOwner`, `X-User-ID` is the `id` of the owning `Party` referenced by the challenged patent's `owner_id`, and ownership checks compare that owner reference to `X-User-ID`.

`AppealsCourt` is the federal appellate clerk entering dispositions on appeals. When `X-User-Role` is `AppealsCourt`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

Access to every operation is restricted by role, and several operations split further by outcome: only `BoardPanel` may resolve a hearing as held or continued while only a party to the proceeding may waive it, and only `BoardPanel` may grant or deny an amendment motion while only the patent owner may withdraw one. An attempt to perform an action outside the caller's designated role — or to request an outcome reserved for another role — is rejected with `ERR_FORBIDDEN_ROLE`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Statutory Timekeeping

Every statutory deadline and every system-generated timestamp in this docket is governed by a single logical clock, never by wall-clock time. An administrator-only test-driving capability sets the current logical time to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Before any call to that capability, the logical clock reads exactly 2026-09-01T00:00:00Z, and the system must not fall back to wall-clock time under any circumstance.

All system timestamps — `created_at`, `filing_date`, `accorded_date`, `institution_date`, `cycle_anchor_date`, `decided_at`, `issued_at` — are stamped from this clock, and every deadline comparison in this document (the one-year time bar, the 93-day institution window, the briefing windows, the final-decision deadline, the hearing cutoff) is evaluated against it. The docket API itself is mounted under the `/ptab` prefix; the clock capability is a platform-level endpoint and lives outside that prefix.

### 2.5. Common Resource Properties

All primary resources — parties, patents, litigation matters, petitions, proceedings, briefs, expert declarations, discovery requests, amendment motions, oral hearings, hearing rooms, and appeals — carry a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that increments with every modification to the resource, including modifications applied by system cascades; it underpins optimistic concurrency control.

Two resources are immutable event records rather than mutable entities: the `InstitutionDecision` and the `FinalWrittenDecision`. Each is written once and never modified, and each therefore carries only `id` and `created_at` — both `updated_at` and `version` are absent from these records.

### 2.6. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — a brief beneath a proceeding, a declaration beneath a brief, a matter beneath a patent — the system validates the existence of each identifier in sequential, left-to-right order and rejects the request immediately with the 404 error corresponding to the *first* identifier that does not resolve. A request aimed at a proceeding under a non-existent patent therefore fails on the patent before the proceeding is ever consulted. Body-referenced entities are validated after the path chain: a payload naming a missing party (`owner_id`, `petitioner_id`, or `defendant_party_id`) is rejected with `ERR_PARTY_NOT_FOUND`; a missing patent reference with `ERR_PATENT_NOT_FOUND`; and a missing hearing room named in a scheduling payload with `ERR_ROOM_NOT_FOUND`.

The full 404 family, one code per resource kind, is: `ERR_PARTY_NOT_FOUND`, `ERR_PATENT_NOT_FOUND`, `ERR_MATTER_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_PROCEEDING_NOT_FOUND`, `ERR_BRIEF_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_MOTION_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, and `ERR_APPEAL_NOT_FOUND`.

### 2.7. Optimistic Concurrency Control

Exactly two writes in the system are optimistic-concurrency guarded, each against the version of a parent entity whose state the client must have observed:

- Filing a petition (`POST /ptab/petitions`) requires the request to carry `expected_patent_version`, the client's last observed `version` of the target patent. If the patent's current `version` differs — because a prior filing or a decision cascade has advanced it since the client last read the patent — the request is rejected with `ERR_STALE_PATENT_VERSION` (HTTP 412). A successful petition filing itself increments the patent's `version` by one, so a second filing built on a stale read cannot silently overwrite the first.
- Updating a litigation matter (`PATCH /ptab/litigation-matters/{matterId}`) requires the request to carry `expected_litigation_matter_version`, the client's last observed `version` of the matter. A mismatch with the matter's current `version` — advanced by another docket update or by an institution or full-cancellation cascade — is rejected with `ERR_STALE_MATTER_VERSION` (HTTP 412), preventing a stale view from silently dropping a legitimate change.

No other endpoint accepts a version field; writes not listed here perform no optimistic-concurrency check.

### 2.8. Monetary Values, Scores, and Rounding Discipline

All monetary amounts are integer cents; no fractional cents are ever stored or returned. Scores — the institution merits scores, the advisory aggregate, the Fintiv discretionary score, and the Garmin interest-of-justice score — are integer points.

Two rounding rules are pinned. The advisory aggregate merits score is rounded half-up to the nearest integer. Brief overage fees are rounded half-up to whole cents **per brief first**, and only then accumulated into the proceeding's running total; summing the raw per-page products and rounding once at the end is a different, non-conformant calculation. To make the distinction concrete: two briefs that each run one page over their fee-free limit contribute 316 + 316 = 632 cents to the proceeding total under the pinned order, whereas summing the raw products first would yield 632.5, which rounds to 633.

### 2.9. The Patent Claim Ledger

Every patent carries a conserved claim ledger built from `total_claims`, `claims_cancelled_count`, and `claims_amended_count`, together with the derived `claims_alive`. At all times, `claims_alive` equals `total_claims` minus `claims_cancelled_count`, so the invariant `claims_alive` + `claims_cancelled_count` == `total_claims` holds after every amendment grant and every final written decision.

When an amendment motion is granted, each substitute claim swaps an original claim out of the patent: `total_claims` increases by one, `claims_cancelled_count` increases by one because the original is cancelled, and `claims_amended_count` increases by one — `claims_alive` is therefore unchanged by the swap. When a final written decision issues, each claim outcome moves the ledger exactly once: an `UNPATENTABLE` outcome adds one to `claims_cancelled_count`; an `AMENDED_SUBSTITUTED` outcome changes no counter, because the original was already cancelled at grant time and double counting is forbidden; a `NOT_UNPATENTABLE` outcome changes no counter.

After a decision, the patent's `status` is re-derived from the ledger by strict precedence: if `claims_alive` is zero the patent becomes `FULLY_CANCELLED`; otherwise, if `claims_amended_count` is greater than zero it becomes `AMENDED`; otherwise, if `claims_cancelled_count` is greater than zero it becomes `PARTIALLY_CANCELLED`; otherwise it becomes `CONFIRMED`.

### 2.10. Cascading Docket Effects

State changes rarely stay on the entity that received the write. Three cascade links recur throughout this document. **Cascade link 1 — institution spawns the trial:** an institution decision that institutes creates the proceeding, with its deadlines, its zeroed briefing cycle, and its budget of one amendment motion of right. **Cascade link 2 — the patent follows the docket:** institution moves the patent from `ISSUED` to `IN_REVIEW`; a final written decision re-derives the patent's claim counters and status per §2.9; a vacating remand returns the patent to `IN_REVIEW`. **Cascade link 3 — parallel litigation feels the board:** institution stays every `ACTIVE` litigation matter for the patent with reason `INSTITUTION_STAY`; a decision that fully cancels the patent stays every still-`ACTIVE` matter with reason `PATENT_CANCELLED`; a decision attaches estoppel claim sets to the matters naming the petitioner as defendant; a vacating remand clears those sets again.

Every mutation, including each cascade hop, is applied atomically within the triggering request, and all recomputed fields are visible in that request's response. Any mutation to a versioned entity — whether client-initiated or cascade-driven — refreshes its `updated_at` and increments its `version` per §2.5.

### 2.11. Validation Order

When a request would fail several checks at once, the system evaluates its defenses in a fixed priority order and reports the first failure. The order is: (1) presence of the authentication headers (`ERR_MISSING_AUTH_HEADERS`); (2) whether the caller's role may invoke the operation, including the per-outcome role splits (`ERR_FORBIDDEN_ROLE`); (3) existence of path resources, validated left-to-right, followed by existence of body-referenced entities (the 404 family of §2.6); (4) ownership of the target resource by the caller (`ERR_NOT_RESOURCE_OWNER`); (5) request-schema well-formedness — required fields present, enums in range, structural rules on arrays (`ERR_VALIDATION`); (6) optimistic-concurrency version agreement (`ERR_STALE_PATENT_VERSION` or `ERR_STALE_MATTER_VERSION`); (7) state-machine preconditions (`ERR_PETITION_WRONG_STATE`, `ERR_INVALID_PHASE`, `ERR_INVALID_STATE`, `ERR_PROCEEDING_NOT_DECIDED`, `ERR_DECISION_ALREADY_ISSUED`, `ERR_APPEAL_ALREADY_PENDING`, `ERR_HEARING_ALREADY_PENDING`, `ERR_EXTENSION_ALREADY_USED`); (8) statutory clocks (`ERR_PETITION_TIME_BARRED`, `ERR_INSTITUTION_WINDOW_LAPSED`, `ERR_BRIEF_WINDOW_CLOSED`, `ERR_FWD_DEADLINE_PASSED`, `ERR_HEARING_PAST_FWD_DATE`); (9) domain constraints — permitted grounds and prior-art types, page caps, brief sequence, new-evidence limits, amendment quotas, substitute-claim matching, room conflicts, panel capacity, interval validity, and outcome-set coverage; and (10) filing-fee sufficiency (`ERR_FEE_INSUFFICIENT`). A request that violates both an earlier and a later category always reports the earlier one.

## 3. Business Logic & Workflows

### 3.1. Docket Registration: Parties, Patents, and Hearing Rooms

Before any trial can exist, a `PlatformAdmin` builds the docket. Parties are registered with a legal `name`, a `party_type` of `PETITIONER` or `PATENT_OWNER` that fixes which side of a trial the party may act on, and an optional `counsel_firm` lead-counsel label that remains null when omitted.

Patents enter the docket with a `patent_number` unique across the system, a `title`, an `issue_date` recording when the patent issued, an `owner_id` referencing the owning party, and a `total_claims` count of issued claims, which must be at least one. The referenced owner must exist (`ERR_PARTY_NOT_FOUND`) and must be a party whose `party_type` is `PATENT_OWNER`; naming a petitioner-side party as owner is `ERR_VALIDATION`. A newly registered patent stands in `ISSUED` status with `claims_alive` equal to `total_claims` and both `claims_cancelled_count` and `claims_amended_count` at zero; `total_claims` later grows by the number of granted substitute claims, per the ledger rules of §2.9. The patent roster can be browsed with optional `owner_id` and `status` filters.

Hearing rooms are registered with a `name` unique across the board facility and a seating `capacity` of at least one.

### 3.2. Parallel District-Court Litigation: Docketing and Maintaining Matters

Each parallel district-court case is docketed by a `PlatformAdmin` beneath its patent. The record captures the `defendant_party_id` of the accused infringer, the `court_name`, the court's `docket_number`, and the `complaint_served_date` — the service date that later drives the one-year petition time bar — plus an optional `trial_date`, which stays null until the court sets one and which feeds the proximity factor of the discretionary-denial score. The `patent_id` of the matter is taken from the creation path. A new matter starts in `ACTIVE` status with `stay_reason` null and `estoppel_claims` empty. Matters can be listed with optional `patent_id`, `defendant_party_id`, and `status` filters.

From `ACTIVE`, a matter may be stayed, settled, marked `TRIAL_COMPLETED`, or `DISMISSED`; from `STAYED`, it may return to `ACTIVE` — the stay is lifted and `stay_reason` returns to null — or it may settle. `SETTLED`, `TRIAL_COMPLETED`, and `DISMISSED` are terminal; patching a matter that has reached any of them is rejected with `ERR_INVALID_STATE`. Every docket update, whether it changes the `trial_date`, the `status`, or both, flows through a single guarded write by a `PlatformAdmin` carrying `expected_litigation_matter_version`; the optimistic-concurrency rules of §2.7 apply, a mismatch is `ERR_STALE_MATTER_VERSION`, and a successful write increments the matter's `version` by one. The `stay_reason` field records provenance whenever the matter stands in `STAYED`: `MANUAL_STAY` when the administrator stayed it directly, `INSTITUTION_STAY` when the institution cascade stayed it, and `PATENT_CANCELLED` when the full-cancellation cascade stayed it; the field is null in every non-`STAYED` status.

Because the discretionary-denial screen is forward-looking, every one of these docket updates — and both of the cascades that can stay a matter — refreshes the provisional `fintiv_score` stored on each petition against the same patent that is still pending, meaning in `FILED` or `NOTICE_ACCORDED` status. The panel therefore always screens institution against the live litigation posture rather than the posture at filing.

### 3.3. Petition Filing: Grounds, Fees, and the One-Year Time Bar

A `Petitioner` opens a review by filing a petition against a registered patent. The payload names the `patent_id` of the challenged patent and a `petitioner_id` that must reference an existing party whose `party_type` is `PETITIONER` and must equal the caller's `X-User-ID` — the former kind of mismatch is `ERR_VALIDATION`, the latter `ERR_NOT_RESOURCE_OWNER`. The `review_type` selects the statutory track: `IPR` or `PGR`. The petition asserts `challenged_claims`, a non-empty array of unique claim numbers, each between 1 and the patent's `total_claims`; `grounds`, a non-empty array whose entries pair a `claim_number` with a `basis`, where every `claim_number` appears among the `challenged_claims` and every `basis` is one of `ANTICIPATION_102`, `OBVIOUSNESS_103`, `PUBLIC_USE`, `ON_SALE`, or `OTHER_STATUTORY`; and `prior_art`, a non-empty array whose entries pair a `reference_type` of `PATENT`, `PRINTED_PUBLICATION`, `PRODUCT`, or `TESTIMONY` with a `citation`. A non-empty `real_party_in_interest` disclosure is mandatory, and any structural defect in these arrays is `ERR_VALIDATION`.

The filing fee scales with the breadth of the challenge: a base of 1,900,000 cents covers up to twenty challenged claims, and each challenged claim beyond twenty adds 15,000 cents. When `fee_paid_cents` falls below the required amount, the filing is rejected with `ERR_FEE_INSUFFICIENT` (HTTP 402).

Two statutory screens also run at filing. The first is the one-year time bar: if any litigation matter exists for the same patent naming the petitioner as defendant whose `complaint_served_date` lies strictly more than 365 days before the filing date, the petition is rejected with `ERR_PETITION_TIME_BARRED`. Exactly 365 days elapsed is not barred, while 366 days is; and the matter's later disposition does not lift the bar — a complaint served in a case since `DISMISSED` or `SETTLED` still bars the petition. The second screen is the state of the patent itself: a patent that has reached `FULLY_CANCELLED` no longer admits new petitions, and filing against one is rejected with `ERR_INVALID_STATE`.

Filing is also the docket's first optimistic-concurrency checkpoint. The payload must carry `expected_patent_version` equal to the patent's current `version`; a mismatch is rejected with `ERR_STALE_PATENT_VERSION` (HTTP 412) per §2.7. A successful filing stamps `filing_date` from the logical clock as the petition's receipt date, sets the petition's `status` to `FILED`, computes and stores the provisional `fintiv_score` described in §3.4, and — because a new challenge changes the docket every other filer sees — increments the patent's `version` by one. The `accorded_date`, `merits_max_score`, and `advisory_aggregate_score` fields remain null at this stage. Pending petitions can be browsed with optional `patent_id`, `petitioner_id`, and `status` filters.

### 3.4. Institution: Formal Review, Merits Thresholds, and Discretionary Denial

Formal review begins when a `BoardPanel` member accords the petition a filing date. Accordance is allowed only while the petition is `FILED`; against any other status it fails with `ERR_PETITION_WRONG_STATE`. Accordance is also where the statutory ground limits bite — for the `IPR` track only. Every asserted ground `basis` on an `IPR` petition must be `ANTICIPATION_102` or `OBVIOUSNESS_103`, or accordance is rejected with `ERR_GROUND_NOT_PERMITTED`; and every `prior_art` entry on an `IPR` petition must have a `reference_type` of `PATENT` or `PRINTED_PUBLICATION`, or accordance is rejected with `ERR_PRIOR_ART_TYPE_NOT_PERMITTED`. The `PGR` track carries no such restrictions: all five bases and all four reference types remain admissible there. A successful accordance moves the petition from `FILED` to `NOTICE_ACCORDED`, stamps `accorded_date` from the logical clock — opening the institution window — and refreshes the provisional `fintiv_score` against the decision-relevant matters.

The institution decision itself is a panel action whose payload carries `per_ground_scores` — one entry per scored ground, each naming a `claim_number`, a `basis`, and an integer `score` from 0 to 100, with every scored claim lying among the petition's `challenged_claims` — together with the `lead_judge_user_id` of the designated panel lead. The petition must be in `NOTICE_ACCORDED` (`ERR_PETITION_WRONG_STATE` otherwise), and the decision must land within the statutory window: a decision on or before `accorded_date` plus 93 days is timely, while one attempted 94 or more days after accordance is rejected with `ERR_INSTITUTION_WINDOW_LAPSED`.

The merits test is per-ground. The `merits_max_score` is the single highest score across the payload, and the threshold depends on the track: 40 for `IPR`, the reasonable-likelihood standard, and 51 for `PGR`, the more-likely-than-not standard. The merits are met when the maximum score is at least the threshold — a top score of exactly 40 institutes an `IPR`, while 39 does not. Alongside this operative test, the decision record carries an advisory `advisory_aggregate_score`: seven-tenths of the maximum score plus three-tenths of the mean of all scores, rounded half-up to an integer. The aggregate is a panel-screening metric reported on the record only and never decides institution; for ground scores of 80, 40, and 20, the operative maximum is 80 while the advisory aggregate is 70 — same inputs, different value, and only the maximum governs.

The discretionary screen is the Fintiv score, computed from the litigation matters for the same patent that name the petitioner as defendant and stand in `ACTIVE` or `STAYED` status — matters that are `SETTLED`, `TRIAL_COMPLETED`, or `DISMISSED` are excluded from the input set. If no qualifying matter exists, the score is zero. Otherwise each qualifying matter contributes a base of 20 points for the existence of the parallel case; 40 further points if its `trial_date` is set and falls on or before the projected final-decision date; 20 further points if strictly more than 180 days elapsed between that matter's `complaint_served_date` and the petition's `filing_date`; and a 20-point credit if the matter currently stands `STAYED`. Each matter's total is clamped into the 0–100 range, and the petition's score is the maximum across qualifying matters. The projected final-decision date used for the proximity factor is always the base statutory deadline — the decision date plus 365 days; any extension granted later never retroactively widens that comparison date. Discretionary denial applies exactly when the score is at least 70 and the merits were independently met, producing the outcome `DENIED_DISCRETIONARY`; when the merits are not met, the outcome is `DENIED_MERITS`. Two evaluations of the same formula exist: the provisional variant, computed at filing (and refreshed on docket updates per §3.2) with each `trial_date` read as-is — a matter whose `trial_date` is null contributes no proximity points — and the decision-time variant, recomputed from the live matter rows when the panel decides, so a petition filed while no trial date was set can face a materially higher score by decision day.

When the computed outcome would be to institute, one capacity check remains: a panel lead may front at most two active proceedings. Counting proceedings whose `lead_judge_user_id` equals the payload designee and whose `phase` is any of `INSTITUTED`, `REPLY_WINDOW`, `SUR_REPLY_WINDOW`, `HEARING_PHASE`, `DECISION_PHASE`, or `REMANDED` — `DECIDED` and `CLOSED` proceedings release the slot — a count of exactly one still admits the assignment, while a count of two rejects the institution with `ERR_PANEL_CAPACITY_EXCEEDED`.

Every decision, whether to institute or to deny, creates exactly one immutable `InstitutionDecision` for the petition, recording the `petition_id`, the `outcome`, the `merits_max_score`, the `threshold_used` (40 or 51 per the track), the `advisory_aggregate_score`, the decision-time `fintiv_score`, the deciding `lead_judge_user_id`, and the `decided_at` timestamp; the petition's own `merits_max_score` and `advisory_aggregate_score` are recorded on the petition as well. The decision record is retrievable as an array holding zero or one entries. A denial leaves the petition `DENIED` and terminal.

An institution moves the petition to `INSTITUTED` and fires the full institution cascade atomically within the same request. The new proceeding is created with `phase` `INSTITUTED`; its `petition_id` bound to the petition and its `patent_id` copied from the petition; `instituted_claims` equal to the petition's `challenged_claims` in the all-claims style — every challenged claim is instituted, never a subset; `institution_date` and `cycle_anchor_date` stamped with the decision timestamp; `fwd_due_date` set 365 days out; `advisory_anniversary_date` set 12 calendar months out; `amendment_slots_available` at 1; `briefing_cycle` at 0; `extension_used` and `estoppel_applied` false; `total_overage_fee_cents` at zero; and the payload's `lead_judge_user_id` recorded as the panel lead. In the same stroke the patent moves `ISSUED → IN_REVIEW` with its `version` incremented by one, and every `ACTIVE` litigation matter for the patent is stayed with `stay_reason` set to `INSTITUTION_STAY`. Multiple petitions against the same patent may be instituted over time: a patent already `IN_REVIEW` simply remains `IN_REVIEW` (its `version` still increments), and a patent that had settled into `PARTIALLY_CANCELLED`, `AMENDED`, or `CONFIRMED` after an earlier proceeding returns to `IN_REVIEW` upon a new institution. The response to a decided petition carries the `decision_id`, the `outcome`, the `merits_max_score`, the `advisory_aggregate_score`, the `threshold_used`, the decision-time `fintiv_score`, and — when trial is instituted — the new `proceeding_id`. Proceedings can be browsed with optional `patent_id`, `petition_id`, `lead_judge_user_id`, and `phase` filters.

### 3.5. The Trial Briefing Cycle: Windows, Page Limits, and Expert Declarations

An instituted trial runs a fixed briefing choreography anchored at the proceeding's `cycle_anchor_date` — the `institution_date` for the original cycle 0, and the remand timestamp for any later cycle. The patent owner opens with a `PO_RESPONSE`, due within 90 days of the anchor; the petitioner answers with a `PETITIONER_REPLY`, due within 132 days; and the patent owner may close the written record with a `PO_SUR_REPLY`, due within 146 days. A brief tendered after its window has closed is rejected with `ERR_BRIEF_WINDOW_CLOSED`.

Each brief type carries a page allowance. The first 90 pages of a `PO_RESPONSE` are fee-free, as are the first 45 pages of a `PETITIONER_REPLY` and the first 20 pages of a `PO_SUR_REPLY`. Beyond the fee-free limit, each additional page is billed at 316.25 cents, and the brief's `overage_fee_cents` is that product rounded half-up to whole cents — computed per brief first and only then accumulated into the proceeding's `total_overage_fee_cents`, per the pinned rounding order of §2.8. Hard caps bind absolutely: a `PO_RESPONSE` above 110 pages, a `PETITIONER_REPLY` above 65 pages, or a `PO_SUR_REPLY` above 40 pages is rejected with `ERR_PAGE_LIMIT_EXCEEDED`, and every brief's `page_count` must be at least one.

Acceptance of a `PO_RESPONSE` requires the proceeding to be in `INSTITUTED` or `REMANDED` phase and advances it to `REPLY_WINDOW`. Acceptance of a `PETITIONER_REPLY` requires `REPLY_WINDOW` and advances it to `SUR_REPLY_WINDOW`. Acceptance of a `PO_SUR_REPLY` requires `SUR_REPLY_WINDOW` and leaves the phase unchanged — the sur-reply closes the briefing record, but the phase advances only when a hearing is later scheduled. Filings against the wrong phase draw `ERR_INVALID_PHASE`. Only one brief of each type may exist per briefing cycle, so a second filing of the same type within the same cycle is `ERR_BRIEF_SEQUENCE_VIOLATION`. Authorship is enforced side-for-side: the `PO_RESPONSE` and `PO_SUR_REPLY` may be filed only by the patent's owner, and the `PETITIONER_REPLY` only by the proceeding's petitioner; violations are rejected with `ERR_NOT_RESOURCE_OWNER`. Every accepted brief records its `proceeding_id` from the filing path, its `brief_type`, the filer's identity as `author_user_id`, the `page_count`, the computed `overage_fee_cents`, and the `cycle` — the proceeding's `briefing_cycle` at filing time.

Expert declarations attach to an existing brief and may be filed only by that brief's author; anyone else draws `ERR_NOT_RESOURCE_OWNER`. Each declaration carries the `brief_id` from its path, a `declarant_name`, a `page_count` of at least one, and a `contains_new_evidence` flag. Because the petitioner's reply may not smuggle new evidence into the record, a declaration whose `contains_new_evidence` is true attached to a `PETITIONER_REPLY` brief is rejected with `ERR_NEW_EVIDENCE_IN_REPLY`; declarations attached to patent-owner briefs may introduce new evidence freely.

### 3.6. Discovery and Amendment Practice

Discovery in these trials is deliberately narrow. Either party to the proceeding — the petitioner or the patent owner, and a non-party is rejected with `ERR_NOT_RESOURCE_OWNER` — files a request carrying a `discovery_type`. A `ROUTINE` request is granted automatically at creation and lands directly in `GRANTED`; any `factor_scores` supplied with it are simply ignored. An `ADDITIONAL` request requires `factor_scores` of exactly five integers, each from 0 to 2 — any other shape is `ERR_VALIDATION` — and is created `PENDING` with a computed `garmin_score`, the interest-of-justice measure. The score sums the five factor scores, but if any single factor is zero the total is capped at the lesser of the raw sum and 4; a request filed while the proceeding stands in `REPLY_WINDOW` earns a one-point diligence bonus; and the final score is capped at 10. The panel's ruling on a pending request is deterministic from the stored score: the request must still be `PENDING` and of type `ADDITIONAL` — ruling on anything else is `ERR_INVALID_STATE` — and it is granted when its `garmin_score` is at least 6 and denied below that line, moving from `PENDING` to `GRANTED` or `DENIED`. Every request records its `proceeding_id` from the creation path and the requester's identity as `requester_user_id`.

Amendment practice gives the patent owner one motion of right per briefing cycle, tracked by the proceeding's `amendment_slots_available`, which stands at 1 at the start of each cycle. Filing a motion consumes the slot immediately: the motion is created in `FILED` status, stamped with the current `cycle`, and the slot count drops by one — maintaining the per-cycle invariant that the slots available plus the cycle's motions in `FILED`, `GRANTED`, or `DENIED` status always total exactly one. Filing with no slot available is rejected with `ERR_AMENDMENT_QUOTA_EXCEEDED`, and filing while the proceeding is in any phase other than `INSTITUTED`, `REPLY_WINDOW`, or `REMANDED` is `ERR_INVALID_PHASE`. The motion carries `substitute_claims`, a non-empty array pairing each `original_claim_number` with its `substitute_text`; every original must lie among the proceeding's `instituted_claims` (`ERR_SUBSTITUTE_CLAIM_MISMATCH`), and the number of substitutes may not exceed the number of instituted claims (`ERR_AMENDMENT_VOLUME_EXCEEDED`). Substitute claims are construed under the `PHILLIPS` standard — the same construction standard a district court would apply — recorded as the motion's fixed `construction_standard`.

Resolution of a motion splits by outcome and by role. Only the panel may grant or deny; only the patent owner may withdraw. A role reaching for an outcome reserved for another role is `ERR_FORBIDDEN_ROLE`, and a withdrawal attempted by anyone other than the patent owner is `ERR_NOT_RESOURCE_OWNER`. Any resolution requires the motion to still stand `FILED` (`ERR_INVALID_STATE`), and a grant additionally requires that the parent proceeding not be `DECIDED` or `CLOSED` (`ERR_INVALID_PHASE`). A grant swaps each substitute claim in per the claim ledger of §2.9 — for each substitute, `total_claims`, `claims_cancelled_count`, and `claims_amended_count` each rise by one while `claims_alive` holds steady — and increments the patent's `version` by one. A denial spends the motion of right: the amendment slot stays consumed. A withdrawal is compensating: `amendment_slots_available` rises by one, returning the slot for reuse within the cycle. The resolution payload takes the `outcome` — `GRANTED`, `DENIED`, or `WITHDRAWN` — and may carry an optional `rationale`.

### 3.7. Oral Hearing: Request, Scheduling, and Resolution

Either party to the proceeding — and only a party, on pain of `ERR_NOT_RESOURCE_OWNER` — may request oral argument, optionally sizing the session with `argument_minutes`, which defaults to 60 when omitted. The proceeding must stand in `INSTITUTED`, `REPLY_WINDOW`, `SUR_REPLY_WINDOW`, `HEARING_PHASE`, or `REMANDED` phase, otherwise `ERR_INVALID_PHASE`; and at most one hearing may be in flight per proceeding, so a request while another stands `REQUESTED` or `SCHEDULED` is rejected with `ERR_HEARING_ALREADY_PENDING`. A fresh hearing is created in `REQUESTED` status with `hearing_room_id`, `start_at`, and `end_at` all null. The hearing docket can be browsed with optional `proceeding_id`, `hearing_room_id`, and `status` filters.

Scheduling is a panel action supplying the `hearing_room_id`, `start_at`, and `end_at`; the named room must exist (`ERR_ROOM_NOT_FOUND`). The hearing must still stand `REQUESTED` (`ERR_INVALID_STATE`), `end_at` must be strictly after `start_at` (`ERR_INVALID_INTERVAL`), and the hearing must start on or before the proceeding's `fwd_due_date` — a start beyond the final-decision deadline is `ERR_HEARING_PAST_FWD_DATE`. Room bookings are half-open intervals protected by a turnover buffer: the new hearing occupies the interval from `start_at` up to but not including `end_at`, while every other `SCHEDULED` hearing in the same room occupies its own interval extended by a trailing 30-minute buffer. A conflict exists precisely when the new start falls before another booking's buffered end and the new end falls after that booking's start, and is rejected with `ERR_HEARING_ROOM_CONFLICT`; starting exactly at another booking's buffered end is accepted, starting one minute earlier conflicts, and ending exactly when another booking begins is accepted. The proceeding must stand in `REPLY_WINDOW`, `SUR_REPLY_WINDOW`, or `HEARING_PHASE` (`ERR_INVALID_PHASE`), and a successful scheduling moves it to `HEARING_PHASE` if it is not already there — scheduling is the action that closes the briefing record.

Resolution of a scheduled hearing splits three ways by role. Marking the hearing held is panel-only; waiver belongs to a party to the proceeding — petitioner or patent owner — and a non-party waiver is `ERR_NOT_RESOURCE_OWNER`; continuance is panel-only. Any other role–outcome pairing is `ERR_FORBIDDEN_ROLE`, and any resolution attempted on a hearing not currently `SCHEDULED` is `ERR_INVALID_STATE`. The resolution payload carries the `outcome` — `HELD`, `WAIVED`, or `CONTINUED`. A hearing held or waived moves the proceeding from `HEARING_PHASE` to `DECISION_PHASE`. A continuance releases the booking: `hearing_room_id`, `start_at`, and `end_at` return to null, the hearing drops back to `REQUESTED`, and the proceeding's phase is left unchanged, whether that phase is `HEARING_PHASE` or an earlier briefing phase it never left.

### 3.8. The Final Written Decision, Its Deadline, and Estoppel

The statute gives the board one year. The operative deadline, `fwd_due_date`, is the `institution_date` plus 365 days, extended by a further 183 days if good cause is shown. An advisory anniversary value, `advisory_anniversary_date`, is maintained alongside it — `institution_date` plus 12 calendar months, plus 6 further calendar months if extended — for schedule-order display only; it never gates any transition. The two values diverge whenever the span contains a leap day: a proceeding instituted on 2027-03-10 shows an operative deadline of 2028-03-09 against an advisory anniversary of 2028-03-10, and every deadline check in the system uses the operative value.

Good cause may be shown once per proceeding. A party to the proceeding — petitioner or patent owner, with non-parties rejected as `ERR_NOT_RESOURCE_OWNER` — files an extension request whose `justification` runs at least 20 characters (`ERR_VALIDATION` otherwise). If `extension_used` is already true, the request is rejected with `ERR_EXTENSION_ALREADY_USED`; a request lodged after the proceeding has reached `DECIDED` or `CLOSED` is `ERR_INVALID_PHASE`. A granted extension adds 183 days to `fwd_due_date` and 6 calendar months to `advisory_anniversary_date`, sets `extension_used` to true, and increments the proceeding's `version` by one.

Issuing the final written decision is a panel action whose guards are checked in a fixed order: first, that no decision already exists for the current `briefing_cycle` — exactly one decision may issue per cycle, and a second attempt is `ERR_DECISION_ALREADY_ISSUED`; then that the proceeding stands in `DECISION_PHASE` (`ERR_INVALID_PHASE`); then that the logical clock has not passed `fwd_due_date` — issuance after the deadline is `ERR_FWD_DEADLINE_PASSED`, and an extension must be obtained first. The payload's `outcomes` pair each `claim_number` with an `outcome` of `UNPATENTABLE`, `NOT_UNPATENTABLE`, or `AMENDED_SUBSTITUTED`. The set must cover every instituted claim exactly once — no claim outside the instituted set, no duplicates — and every claim carrying a granted substitute must be marked `AMENDED_SUBSTITUTED`; any deviation is `ERR_OUTCOME_SET_INVALID`.

An accepted issuance creates the immutable `FinalWrittenDecision`, recording its `proceeding_id`, the `cycle` in which it issues, the `outcomes`, the `issued_at` timestamp from the logical clock, and its own `claims_cancelled_count` tallying the `UNPATENTABLE` outcomes in that decision. The proceeding moves `DECISION_PHASE → DECIDED` and its `estoppel_applied` flag is set true. The decision then reconciles the patent per the ledger and status precedence of §2.9, and attaches estoppel: every litigation matter for the patent that names the petitioner as defendant — whatever its current status, including the terminal ones — receives `estoppel_claims` equal to the petition's `challenged_claims`, every challenged claim falling within scope under the all-claims institution rule. Finally, if the reconciliation leaves the patent `FULLY_CANCELLED`, every still-`ACTIVE` litigation matter for the patent is automatically stayed with `stay_reason` set to `PATENT_CANCELLED`; matters already `STAYED` keep their existing reason.

### 3.9. Appeal and Remand

A party to a decided proceeding — and only a party, `ERR_NOT_RESOURCE_OWNER` otherwise — may carry the final written decision to the federal appellate court. Appeal creation requires the proceeding to stand in `DECIDED` (`ERR_PROCEEDING_NOT_DECIDED`), and admits only one pending appeal at a time: a second appeal while one already stands `FILED` is rejected with `ERR_APPEAL_ALREADY_PENDING`. The appeal is created in `FILED` status with the caller's identity stored as `appellant_user_id` and its `proceeding_id` taken from the creation path.

Disposition belongs to the `AppealsCourt` alone, acting on an appeal that must still stand `FILED` (`ERR_INVALID_STATE`). The payload carries an `outcome` and, conditionally, `remand_instructions`. `AFFIRMED` and `DISMISSED` each close the trial — the proceeding moves `DECIDED → CLOSED`, a terminal phase admitting no further mutations — and both of those outcomes forbid `remand_instructions` entirely: supplying them is `ERR_VALIDATION`. `VACATED_AND_REMANDED` is the inverse: it requires `remand_instructions` of `REOPEN_RECORD` or `RECONSIDER`, and their absence is likewise `ERR_VALIDATION`.

A vacatur unwinds the decision in one atomic cascade. The proceeding moves `DECIDED → REMANDED`: `briefing_cycle` increments by one; `cycle_anchor_date` re-anchors to the remand timestamp, so all three briefing windows of §3.5 reopen from it; `amendment_slots_available` gains one, a fresh motion of right for the new cycle; and `estoppel_applied` flips back to false, the vacated decision voiding the estoppel. In the same stroke the patent returns from `PARTIALLY_CANCELLED`, `AMENDED`, or `CONFIRMED` to `IN_REVIEW`, and every litigation matter for the patent has its `estoppel_claims` cleared to empty. The new cycle then reruns the standard choreography: the patent owner's `PO_RESPONSE` filed from `REMANDED` re-enters `REPLY_WINDOW` under the same 90-day window, sequence, and page rules as the original cycle, and a further final written decision for the new cycle reconciles the claim ledger and attaches estoppel afresh.

## 4. Endpoint Definitions

Operations that create a new resource — a party, patent, litigation matter, petition, institution decision, brief, expert declaration, discovery request, amendment motion, oral hearing, final written decision, appeal, or hearing room — return a `201 Created` status code. Operations that modify an existing resource or perform a non-creating action — setting the clock, according a filing date, patching a matter or a hearing, ruling on discovery, resolving a motion or hearing, requesting an extension, deciding an appeal — return a `200 OK` status code, as do all reads. Readers should refer back to §3's narratives to reconstruct each endpoint's complete request and response shape.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock driving every statutory deadline and timestamp | PlatformAdmin |
| POST | `/ptab/parties` | Register a party (petitioner-side or patent-owner-side) | PlatformAdmin |
| POST | `/ptab/patents` | Register an issued patent on the docket | PlatformAdmin |
| GET | `/ptab/patents` | List patents with optional filters | Any |
| GET | `/ptab/patents/{patentId}` | Get a patent | Any |
| POST | `/ptab/patents/{patentId}/litigation-matters` | Docket a parallel district-court litigation matter for a patent | PlatformAdmin |
| GET | `/ptab/litigation-matters` | List litigation matters with optional filters | Any |
| GET | `/ptab/litigation-matters/{matterId}` | Get a litigation matter | Any |
| PATCH | `/ptab/litigation-matters/{matterId}` | Update a matter's trial date and/or status (OCC-guarded) | PlatformAdmin |
| POST | `/ptab/petitions` | File a petition for post-grant review (IPR or PGR); OCC-guarded against the patent | Petitioner |
| GET | `/ptab/petitions` | List petitions with optional filters | Any |
| GET | `/ptab/petitions/{petitionId}` | Get a petition | Any |
| POST | `/ptab/petitions/{petitionId}/accord-filing-date` | Accord a filing date (screens IPR grounds and prior-art types) | BoardPanel |
| POST | `/ptab/petitions/{petitionId}/decide-institution` | Institution decision: merits threshold, Fintiv screen, window, panel capacity; on institution creates the proceeding and fires the cascade | BoardPanel |
| GET | `/ptab/petitions/{id}/institution-decision` | Get the institution decision for a petition (array of 0 or 1) | Any |
| GET | `/ptab/proceedings` | List proceedings with optional filters | Any |
| GET | `/ptab/proceedings/{proceedingId}` | Get a proceeding | Any |
| POST | `/ptab/proceedings/{proceedingId}/briefs` | File a brief (PO response, petitioner reply, or PO sur-reply) within the current window | Petitioner, PatentOwner |
| GET | `/ptab/proceedings/{id}/briefs` | List briefs filed in a proceeding | Any |
| GET | `/ptab/briefs/{briefId}` | Get a brief | Any |
| POST | `/ptab/briefs/{briefId}/expert-declarations` | Attach an expert declaration to a brief | Petitioner, PatentOwner |
| GET | `/ptab/briefs/{id}/expert-declarations` | List expert declarations attached to a brief | Any |
| POST | `/ptab/proceedings/{proceedingId}/discovery-requests` | Request discovery (ROUTINE auto-granted; ADDITIONAL awaits a panel ruling) | Petitioner, PatentOwner |
| GET | `/ptab/proceedings/{id}/discovery-requests` | List discovery requests in a proceeding | Any |
| POST | `/ptab/discovery-requests/{requestId}/rule` | Panel ruling on an ADDITIONAL discovery request (deterministic from the Garmin score) | BoardPanel |
| POST | `/ptab/proceedings/{proceedingId}/amendment-motions` | File a motion to amend with substitute claims (one motion of right per cycle) | PatentOwner |
| GET | `/ptab/proceedings/{id}/amendment-motions` | List amendment motions in a proceeding | Any |
| POST | `/ptab/amendment-motions/{motionId}/resolve` | Resolve a motion: grant or deny (panel), withdraw (patent owner) | BoardPanel, PatentOwner |
| POST | `/ptab/proceedings/{proceedingId}/extension-requests` | Request the single good-cause extension of the final-decision deadline | Petitioner, PatentOwner |
| POST | `/ptab/proceedings/{proceedingId}/oral-hearings` | Request oral argument | Petitioner, PatentOwner |
| GET | `/ptab/oral-hearings` | List oral hearings with optional filters | Any |
| GET | `/ptab/oral-hearings/{hearingId}` | Get an oral hearing | Any |
| PATCH | `/ptab/oral-hearings/{hearingId}` | Schedule (or re-schedule after continuance) a requested hearing; closes the briefing record | BoardPanel |
| POST | `/ptab/oral-hearings/{hearingId}/resolve` | Resolve a scheduled hearing: held (panel), waived (a party), or continued (panel) | BoardPanel, Petitioner, PatentOwner |
| POST | `/ptab/proceedings/{proceedingId}/final-decisions` | Issue the final written decision for the current briefing cycle | BoardPanel |
| GET | `/ptab/proceedings/{id}/final-decisions` | List final written decisions of a proceeding (one per cycle) | Any |
| POST | `/ptab/proceedings/{proceedingId}/appeals` | Appeal the final written decision to the federal appellate court | Petitioner, PatentOwner |
| GET | `/ptab/proceedings/{id}/appeals` | List appeals of a proceeding | Any |
| POST | `/ptab/appeals/{appealId}/decide` | Enter the appellate disposition: affirmed, dismissed, or vacated and remanded | AppealsCourt |
| POST | `/ptab/hearing-rooms` | Register a hearing room at the board facility | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows they guard; this catalogue is the index of codes and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADERS` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_PARTY_NOT_FOUND` | 404 Not Found |
| `ERR_PATENT_NOT_FOUND` | 404 Not Found |
| `ERR_MATTER_NOT_FOUND` | 404 Not Found |
| `ERR_PETITION_NOT_FOUND` | 404 Not Found |
| `ERR_PROCEEDING_NOT_FOUND` | 404 Not Found |
| `ERR_BRIEF_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_MOTION_NOT_FOUND` | 404 Not Found |
| `ERR_HEARING_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_PATENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_MATTER_VERSION` | 412 Precondition Failed |
| `ERR_PETITION_WRONG_STATE` | 409 Conflict |
| `ERR_INVALID_PHASE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROCEEDING_NOT_DECIDED` | 409 Conflict |
| `ERR_DECISION_ALREADY_ISSUED` | 409 Conflict |
| `ERR_APPEAL_ALREADY_PENDING` | 409 Conflict |
| `ERR_HEARING_ALREADY_PENDING` | 409 Conflict |
| `ERR_EXTENSION_ALREADY_USED` | 409 Conflict |
| `ERR_HEARING_ROOM_CONFLICT` | 409 Conflict |
| `ERR_PANEL_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PETITION_TIME_BARRED` | 422 Unprocessable Entity |
| `ERR_INSTITUTION_WINDOW_LAPSED` | 422 Unprocessable Entity |
| `ERR_BRIEF_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_FWD_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_HEARING_PAST_FWD_DATE` | 422 Unprocessable Entity |
| `ERR_GROUND_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_PRIOR_ART_TYPE_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_PAGE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BRIEF_SEQUENCE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_NEW_EVIDENCE_IN_REPLY` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_QUOTA_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_VOLUME_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SUBSTITUTE_CLAIM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_OUTCOME_SET_INVALID` | 422 Unprocessable Entity |
| `ERR_FEE_INSUFFICIENT` | 402 Payment Required |
