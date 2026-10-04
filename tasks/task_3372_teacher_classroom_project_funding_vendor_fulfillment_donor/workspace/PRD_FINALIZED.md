# Teacher Classroom Funding API — Product Requirements Document

## 1. Introduction

Public-school teachers routinely pay for classroom materials out of pocket. This platform closes that gap with a DonorsChoose-style funding pipeline: a teacher composes a project from itemized requests drawn from approved vendor catalogs, the platform screens the request for eligibility and vets it for appropriateness, cost reasonableness, and verification of the teacher's employment, and only then does the project open for donations. Donors give partial or full amounts against a frozen goal; optional corporate and foundation matching campaigns amplify gifts toward chosen subject areas, schools, or geographies. Once a project is fully funded, the platform issues purchase orders directly to the vendors, who ship straight to the school — money never passes through the teacher's hands.

The lifecycle does not end at funding. Teachers owe donors a thank-you note and an impact report before they may post further projects, equity-focused funding programs steer grants toward high-poverty schools, and a fraud process polices materials diverted from classrooms, with account suspension and a full financial clawback when a case is confirmed. Every time-dependent behavior — funding deadlines, donor reallocation windows, campaign and program windows — is driven by a server-side logical clock so that the entire pipeline is deterministic and testable. This document specifies the REST API for that platform, mounted under `/giving`, and is the sole contract an implementer should need.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level structures, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their role. This includes the self-service registration endpoints, which are called under the `Anonymous` role. A request missing either header, or carrying a role that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the endpoint, or that violates entity-backed ownership, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly six roles:

- `Anonymous` — an unauthenticated self-service registrant signing up as a teacher or a donor. For `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `Teacher` — a classroom teacher who creates and edits their own projects, confirms deliveries, and submits thank-you packages. `X-User-ID` is the `id` of the acting Teacher; ownership checks on any resource that references a Teacher (such as a project's `teacher_id`) compare that foreign-key field to `X-User-ID`.
- `Reviewer` — a vetting reviewer who screens and vets projects. For `Reviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on the project as `screened_by_id` or `vetted_by_id` when a review decision is made, but never compares it to an entity `id` for ownership.
- `Donor` — an individual donor who donates and makes reallocation choices on their own donations. `X-User-ID` is the `id` of the acting Donor; ownership checks compare a donation's `donor_id` to `X-User-ID`.
- `Vendor` — an approved catalog vendor managing its own catalog and shipping its own purchase orders. `X-User-ID` is the `id` of the acting Vendor; ownership checks compare a catalog item's or purchase order's `vendor_id` to `X-User-ID`.
- `PlatformAdmin` — the platform operator, who manages schools, vendors, employment verification, match campaigns, equity funds, sweeps, and fraud resolution. For `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

List endpoints paginate via two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and the Expiration Sweep

All time-dependent behavior in the system — funding deadlines, choice windows, campaign windows, equity program windows — reads a single server-side logical clock. Before any call has set it, the clock reads exactly `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability advances the clock by supplying a `current_utc` instant; the response echoes the new `current_utc`. Advancing the clock mutates no entity and triggers no automatic sweep — expirations happen only when the sweep runs. All timestamp comparisons are made at second precision.

A second `PlatformAdmin`-only capability runs the expiration sweep, an ops-run checkpoint that executes four phases in a fixed order within a single run:

1. **Project expiry.** Every project in `FUNDING` whose `funding_deadline` is at or before now transitions to `EXPIRED` — the boundary is inclusive, so a project whose deadline equals now expires in this run. Projects are processed in `funding_started_at` ascending order, ties broken by `created_at` ascending. Each `CAPTURED` donation on each expired project moves to `CHOICE_PENDING` with `choice_deadline` set to the sweep timestamp plus 14 days, and each such donation's `matched_cents` is clawed back to its match campaign (see §3.6).
2. **Choice auto-refund.** Every donation still in `CHOICE_PENDING` whose `choice_deadline` is at or before now — equality auto-refunds — transitions to `REFUNDED` with `refund_reason` set to `EXPIRED_AUTO`, processed in `choice_deadline` ascending order, ties broken by `created_at` ascending.
3. **Campaign closeout.** Every match campaign in `ACTIVE` or `EXHAUSTED` whose `ends_at` is at or before now transitions to `CLOSED`.
4. **Equity fund closeout.** Every equity fund in `ACTIVE` or `DEPLETED` whose `window_end` is strictly before now transitions to `CLOSED`.

The sweep response summarizes the run with five lists: `expired_project_ids`, `choice_pending_donation_ids`, `auto_refunded_donation_ids`, `closed_match_campaign_ids`, and `closed_equity_fund_ids`. Both test-driving endpoints live outside the `/giving` business surface and are restricted to `PlatformAdmin`.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, rendered in the canonical dashed 8-4-4-4-12 string form (e.g., `550e8400-e29b-41d4-a716-446655440000`).
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that increments by one on every mutation of the resource, powering optimistic concurrency control.

The one exception is the ThankYouPackage: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Money, Precision, and Rounding

All monetary amounts in the system are integer cents; monetary arithmetic never rounds. School percentages (`poverty_pct`, `ell_pct`) carry one decimal place and lie between 0.0 and 100.0 inclusive. Exactly two computations round, and both round half up: the weighted equity score is rounded half up to one decimal place, and each donation's raw match is rounded half up to whole cents before any accumulation (the per-donation rounding order is pinned — see §3.5). The shipping quote rounds only its billable pounds, always up to a whole number, and clamps its final fee between fixed bounds (see §3.2).

### 2.7. Optimistic Concurrency Control

Three write endpoints require an optimistic-concurrency field, and only those three take a version field at all:

- **Adding an item to a project** requires `expected_project_version` carrying the client's last observed `version` of the project. If the project's current `version` has advanced since the client last read it — for example because another item add or a submit changed the item set and totals — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Submitting a project** likewise requires `expected_project_version` matching the project's current `version`. Because the submit pins prices and freezes the goal, it must be based on the current item set; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Recording a reallocation choice on a donation** requires `expected_donation_version` matching the donation's current `version`. A client whose observed version predates, for example, the sweep's transition of the donation into `CHOICE_PENDING` with a fresh `choice_deadline` holds a stale view, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not accept a version field.

### 2.8. Validation Order and Nested Resource Retrieval

When a single request violates several rules at once, the checks are evaluated in a fixed priority order and the earliest failing check determines the error returned. The ladder is:

1. **Request well-formedness** — required fields present, enum values valid, scalar ranges respected: `funding_window_days` between 30 and 180 inclusive, `quantity` at least 1, `amount_cents` at least 1, `match_ratio` greater than 0 and at most 2.0, poverty and ELL percentages between 0.0 and 100.0 inclusive, and minimum lengths on the thank-you note and impact report at submission. Violations yield `ERR_INVALID_REQUEST` (HTTP 400).
2. **Authentication** — `X-User-ID` and `X-User-Role` present, and the role declared; otherwise `ERR_UNAUTHENTICATED`.
3. **Authorization and ownership** — the acting role is permitted on the endpoint, and entity-backed ownership holds (a teacher owns the project, a donor owns the donation, a vendor owns the catalog item or purchase order); otherwise `ERR_FORBIDDEN`.
4. **Existence** — path identifiers and body-referenced ids exist. Nested paths are validated strictly left to right — the project before the item, the fund before the allocation — and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first missing identifier.
5. **Optimistic concurrency** — `ERR_STALE_VERSION` as described in §2.7.
6. **State suitability** — the target entity is in a state that permits the operation: a project is editable only in `DRAFT` or `RETURNED`, a donation lands only on a `FUNDING` project, a purchase-order action fires only from the matching prior status, a review decision applies only from the matching stage's state, a thank-you package submits only while the project is `FULFILLED`, a reallocation choice applies only from `CHOICE_PENDING`, a named match campaign or equity fund must be `ACTIVE`, and a vendor must be `ACTIVE` to ship. Violations yield `ERR_INVALID_STATE` (HTTP 409).
7. **Employment pending** — a teacher in `PENDING_VERIFICATION` creating or submitting a project is rejected with `ERR_TEACHER_NOT_VERIFIED`. This check is evaluated *before* the suspension check.
8. **Employment suspended** — a `SUSPENDED` teacher attempting any teacher-initiated write (creating a project, adding an item, submitting, or submitting a thank-you package) is rejected with `ERR_TEACHER_SUSPENDED`.
9. **Temporal windows**, in this order: donation after the funding deadline (`ERR_FUNDING_WINDOW_CLOSED`), a named match campaign whose window does not cover now (`ERR_MATCH_WINDOW_CLOSED`), a reallocation choice after the choice deadline (`ERR_CHOICE_WINDOW_EXPIRED`), an equity allocation outside the fund's window (`ERR_EQUITY_WINDOW_CLOSED`), a new campaign window overlapping a sibling campaign (`ERR_CAMPAIGN_WINDOW_OVERLAP`), and a new equity fund window overlapping or touching a sibling fund (`ERR_EQUITY_WINDOW_OVERLAP`).
10. **Business constraints**, in this order: the teacher already has an active pipeline project (`ERR_ACTIVE_PROJECT_EXISTS`), the teacher owes a thank-you package (`ERR_THANK_YOU_OUTSTANDING`), the vetting reviewer also screened the project (`ERR_SEGREGATION_OF_DUTIES`), the project already contains the catalog item (`ERR_DUPLICATE_CATALOG_ITEM`), and an open fraud case already exists for the teacher (`ERR_FRAUD_CASE_ALREADY_OPEN`).
11. **Referential business rules**, in this order: the catalog item is unavailable or over its per-project cap (`ERR_CATALOG_ITEM_UNAVAILABLE`), the named campaign's target does not match the project (`ERR_MATCH_TARGET_MISMATCH`), and the reallocation target fund is invalid (`ERR_INVALID_REALLOCATION_TARGET`).
12. **Fiscal rules**, in this order: the project has no items at submit (`ERR_NO_ITEMS` — always checked before the goal range, so an empty project reports `ERR_NO_ITEMS` and never `ERR_GOAL_OUT_OF_RANGE`), the computed goal is out of range (`ERR_GOAL_OUT_OF_RANGE`), the donation exceeds the remaining need or is too small (`ERR_DONATION_EXCEEDS_REMAINING`), the donation falls below the campaign minimum (`ERR_DONATION_BELOW_MATCH_MIN`), and the equity selector finds no eligible project (`ERR_NO_ELIGIBLE_PROJECT`).

### 2.9. Conservation Invariants

Two ledger-style invariants hold at all times, and every workflow in §3 preserves them.

**Donor conservation.** For every donor, `lifetime_donated_cents` always equals the sum of `amount_cents` over that donor's donations currently in `CAPTURED` or `CHOICE_PENDING`, plus `lifetime_refunded_cents`, plus `lifetime_reallocated_cents`. Capture is the forward action; refund and reallocation are the two compensating actions, and each moves `amount_cents` between buckets without changing the total. The `lifetime_donated_cents` counter itself sums `amount_cents` over all donations the donor has ever created, in any status, and never decreases.

**Campaign budget conservation.** For every match campaign, `budget_cents` always equals `matched_so_far_cents` plus `remaining_budget_cents`. Applying a match moves cents from remaining to matched-so-far; a clawback — whether from project expiry or from a fraud confirmation — moves exactly the same cents back. The sum is conserved.

## 3. Business Logic & Workflows

### 3.1. Schools, Teachers, and Vendors: The Registry Layer

A `PlatformAdmin` registers each school with its `name`, its two-letter uppercase `state_code`, its `district`, and two percentages: `poverty_pct` (students in poverty) and `ell_pct` (English-language-learner students), each between 0.0 and 100.0 inclusive with one decimal place. Every school carries two equity scores, computed at creation and reflected on every read, which deliberately diverge. The **banded** score, `equity_score_banded`, is a step function of `poverty_pct` alone: at least 90.0 scores 100; at least 75.0 (but below 90.0) scores 80; at least 50.0 (but below 75.0) scores 50; below 50.0 scores 10. The plateaus matter — poverty rates of 75.0 and 89.9 both score 80 — and the banded score drives equity *eligibility* checks and reporting. The **weighted** score, `equity_score_weighted`, is seven-tenths of `poverty_pct` plus three-tenths of `ell_pct`, rounded half up to one decimal place; it drives equity allocation *ranking*, and because it blends in the ELL share it can rank a lower-poverty school above a higher-poverty one.

Teachers self-register under the `Anonymous` role with a `full_name`, an `email` (unique across teachers), the `school_id` of their employing school, and optionally `subjects_taught`, an array of subject values defaulting to empty. A new teacher's `employment_status` is `PENDING_VERIFICATION`, and in that state they cannot create or submit a project — the attempt fails with `ERR_TEACHER_NOT_VERIFIED`. A `PlatformAdmin` resolves employment through a review action: `action` value `VERIFY` moves a `PENDING_VERIFICATION` teacher to `VERIFIED` (any other starting state fails with `ERR_INVALID_STATE`), and `action` value `REINSTATE` moves a `SUSPENDED` teacher back to `VERIFIED` — but only while no `OPEN` fraud case exists for that teacher, otherwise `ERR_FRAUD_CASE_ALREADY_OPEN`. After reinstatement the teacher may create projects again, though the thank-you gate (§3.7) still applies. The full employment state set is `PENDING_VERIFICATION`, `VERIFIED`, and `SUSPENDED`; a `SUSPENDED` teacher is barred from every teacher-initiated write — creating a project, adding an item, submitting a project, or submitting a thank-you package — with `ERR_TEACHER_SUSPENDED`, and this check is evaluated after the pending-verification check.

Vendors are registered by a `PlatformAdmin` with a legal `name`, the `ship_from_state` orders ship from, and a `contact_email`; a new vendor's `status` is `ACTIVE`. Suspending a vendor moves it to `SUSPENDED`, which blocks adding new catalog items and blocks the shipment action on its purchase orders; existing purchase orders are otherwise unaffected.

### 3.2. The Vendor Catalog and Shipping Economics

A vendor — acting as itself, with `X-User-ID` equal to the vendor's `id` — or a `PlatformAdmin` adds catalog items to a vendor. Each item carries a `sku` that must be unique within that vendor, a display `name`, a `category` (one of `BOOKS`, `TECHNOLOGY`, `FURNITURE`, `SUPPLIES`, `LAB_EQUIPMENT`, `SPORTS`), `subject_tags` (an array of subject values, defaulting to empty), a `unit_price_cents` of at least 1 cent, a `weight_oz` of at least 1 ounce, and a `shipping_zone` of `A`, `B`, or `C` — carrying per-pound rates of 120, 180, and 260 cents respectively. Two optional fields complete the item: `fragile` (default false) marks items needing fragile handling, and `max_quantity_per_project` (default null) caps how many units one project may request, where null means 99. A new item's `status` is `ACTIVE`.

A vendor or admin may later edit an item's current `unit_price_cents` and/or its `status`, but status moves only one way: `ACTIVE` to `DISCONTINUED`. A price change moves the provisional quote of every `DRAFT` or `RETURNED` project referencing the item on that project's next read; it never moves pinned totals. A `DISCONTINUED` item can no longer be added to any project — the add fails with `ERR_CATALOG_ITEM_UNAVAILABLE`.

The per-vendor shipping quote governs both draft-time estimates and issued purchase orders, and works on the lines of one vendor within one project. The total weight is the sum, over that vendor's lines, of `quantity` times `weight_oz`, in ounces. The tier base depends on total ounces: at most 32 ounces the base is 299 cents; more than 32 and at most 128 ounces it is 599 cents; more than 128 ounces it is 899 cents. The zone rate is the highest per-pound zone rate among the vendor's lines — 120 cents for zone `A`, 180 for `B`, 260 for `C`. Billable pounds are the total ounces divided by 16 and rounded up to a whole number. The raw fee is the tier base plus the billable pounds times the zone rate, plus a flat 350 cents if any line is fragile. The final fee clamps the raw fee: never below 199 cents and never above 4999 cents.

### 3.3. Composing and Submitting a Project

A `Teacher` creates a project with a `title`, a `description`, a `subject` (one of `MATH`, `SCIENCE`, `LITERACY`, `ARTS`, `SOCIAL_STUDIES`, `HEALTH_PE`, `OTHER`), a `grade_band` (one of `K_2`, `G3_5`, `G6_8`, `G9_12`), and `funding_window_days`, the number of days the project will stay in funding once vetted — between 30 and 180 days inclusive. The project's `teacher_id` is taken from the acting teacher's `X-User-ID`, and its `school_id` is denormalized from the teacher's employing school at creation and never changes afterward. A new project starts in `DRAFT` with `funded_cents` at 0 and its provisional totals null until items exist. Creation is gated: the teacher must be `VERIFIED` (not `PENDING_VERIFICATION`, not `SUSPENDED`), must not already have another project in `DRAFT`, `IN_REVIEW`, `VETTING`, `RETURNED`, `FUNDING`, or `FUNDED` (`ERR_ACTIVE_PROJECT_EXISTS`), and must not owe a thank-you package (`ERR_THANK_YOU_OUTSTANDING`, see §3.7).

While the project is in `DRAFT` or `RETURNED`, its owning teacher builds the item list. Each add names a `catalog_item_id` and a `quantity`, and carries `expected_project_version` per the concurrency rule in §2.7 — a stale view is rejected with `ERR_STALE_VERSION`. The referenced catalog item must exist, must be `ACTIVE`, and the requested `quantity` must lie between 1 and the item's per-project cap — the lesser of `max_quantity_per_project` and 99, with a null cap treated as 99 — otherwise the add fails with `ERR_CATALOG_ITEM_UNAVAILABLE`. Adding the same `catalog_item_id` twice within one project fails with `ERR_DUPLICATE_CATALOG_ITEM`. Every successful add increments the project's `version` by one and the provisional totals recompute. Items added to a project are readable individually or as a list (optionally filtered by `project_id` or `catalog_item_id`); each item row shows its `project_id`, `catalog_item_id`, `quantity`, and `pinned_unit_price_cents`.

A project's cost has two faces. While the project is in `DRAFT` or `RETURNED`, every read recomputes `provisional_total_cents` as the sum of `quantity` times the *current* catalog `unit_price_cents` over the project's items, plus the shipping quote computed over each distinct vendor's current lines — a live quote that moves when a vendor edits a price. In these states each item's `pinned_unit_price_cents` is null. The pinned face arrives at submit and never changes afterward.

Submitting moves a project from `DRAFT` (or `RETURNED`, as a revision loop) to `IN_REVIEW`. The request carries `expected_project_version` and fails stale with `ERR_STALE_VERSION`; a project in any other state fails with `ERR_INVALID_STATE`; the employment checks apply as in creation. Two fiscal checks then run in a pinned order: the project must contain at least one item (`ERR_NO_ITEMS`, checked first, so an empty project never reports the goal-range error), and the computed goal must lie between 10000 and 200000 cents inclusive (`ERR_GOAL_OUT_OF_RANGE`). On success the submit snapshots each item's current catalog price into that item's `pinned_unit_price_cents`, freezes `pinned_items_total_cents` (the sum of pinned price times quantity over the items), `pinned_shipping_total_cents` (the sum of per-vendor shipping quotes over the pinned lines), and `goal_cents` (the sum of those two frozen totals), sets `provisional_total_cents` to null permanently, increments the project's `version` by one, and moves the project to `IN_REVIEW`. Later catalog price edits leave the pinned totals and the goal untouched. A resubmission from `RETURNED` re-pins prices and re-checks the goal identically, and additionally clears `screened_by_id` and `vetted_by_id` so the next review round starts clean.

### 3.4. Screening, Vetting, and the Funding Window

Reviewers drive projects through a two-stage gauntlet using a `stage` and an `outcome`. Screening — `stage` value `SCREEN` — applies to a project in `IN_REVIEW`: `APPROVE` advances it to `VETTING` and records the acting reviewer's `X-User-ID` as the project's `screened_by_id`; `RETURN` sends it back to `RETURNED`, where the teacher may edit items and resubmit. Vetting applies to a project in `VETTING` and admits three outcomes: `APPROVE` moves the project to `FUNDING`, records the acting reviewer as `vetted_by_id`, stamps `funding_started_at` with the current logical-clock time, and computes `funding_deadline` as that instant plus the project's `funding_window_days`; `RETURN` sends the project back to `RETURNED`; and `REJECT` terminates it as `REJECTED`. The `REJECT` outcome is permitted only at the `VET` stage. Any decision against a project not in the state matching its stage fails with `ERR_INVALID_STATE`.

Segregation of duties binds the vet stage: for all three vetting outcomes, the acting reviewer's `X-User-ID` must differ from the project's `screened_by_id` — the person who screened a project may not vet it — otherwise the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. The full project state set is `DRAFT`, `IN_REVIEW`, `VETTING`, `RETURNED`, `REJECTED`, `FUNDING`, `FUNDED`, `EXPIRED`, `CANCELLED`, `FULFILLED`, and `CLOSED`; `REJECTED`, `EXPIRED`, `CANCELLED`, and `CLOSED` are terminal.

### 3.5. Donations, Matching, and Reaching the Goal

Donors self-register under the `Anonymous` role with a `display_name` and an `email` unique across donors. Each donor carries three lifetime aggregates: `lifetime_donated_cents` (the sum of `amount_cents` over all donations the donor has ever created, in any status; it never decreases), `lifetime_refunded_cents`, and `lifetime_reallocated_cents`, all readable on the donor record along with the conservation property of §2.9.

A `Donor` donates `amount_cents` to a project, optionally naming a `match_campaign_id`. The project must be in `FUNDING` — otherwise `ERR_INVALID_STATE` — and the logical clock must be strictly before the project's `funding_deadline`; note that a project past its deadline still reads `FUNDING` until the sweep runs, and donations into it are rejected with `ERR_FUNDING_WINDOW_CLOSED`. The `amount_cents` must be at least 100 cents and no more than the project's remaining need (`goal_cents` minus `funded_cents`); violating either bound fails with `ERR_DONATION_EXCEEDS_REMAINING`. Donor principal may never overshoot the goal. A successful donation starts in status `CAPTURED` with `kind` set to `DONOR`, `donor_id` set to the acting donor, `matched_cents` at 0 unless a match applies, `equity_fund_id` null, and `refund_reason` null; the donor's `lifetime_donated_cents` grows by `amount_cents`, and the project's `funded_cents` grows by `amount_cents` plus `matched_cents`.

When the donation names a campaign, three extra gates apply. The campaign must be `ACTIVE` (a non-`ACTIVE` campaign fails with `ERR_INVALID_STATE`) and its half-open window must cover now — `starts_at` at or before now, and now strictly before `ends_at` — otherwise `ERR_MATCH_WINDOW_CLOSED`. The campaign's target must match the project: a `SCHOOL` target requires `target_value` equal to the project's `school_id`, a `SUBJECT` target requires it equal to the project's `subject`, and a `STATE` target requires it equal to the school's `state_code`; a mismatch fails with `ERR_MATCH_TARGET_MISMATCH`. Finally, `amount_cents` must be at least the campaign's `min_donation_cents` (which defaults to 0), otherwise `ERR_DONATION_BELOW_MATCH_MIN`.

The match itself is computed per donation: the raw match is `amount_cents` multiplied by the campaign's `match_ratio`, rounded half up to whole cents, and `matched_cents` is the lesser of that rounded amount and the campaign's `remaining_budget_cents`. The campaign's `matched_so_far_cents` grows by `matched_cents` and its `remaining_budget_cents` shrinks by the same amount; when the remaining budget reaches exactly 0, the campaign flips from `ACTIVE` to `EXHAUSTED`. The rounding order is pinned: each donation's match is rounded first and only then accumulated. Summing raw matches across donations and rounding once is forbidden — two 101-cent donations at ratio 0.5 yield 51 plus 51, that is 102 matched cents, never the 101 that a single rounding of the pooled raw match would produce. Unlike principal, the matched portion is not capped by the project's remaining need and may push `funded_cents` past `goal_cents`.

Funding progress is measured by `funded_cents`, the sum of `amount_cents` plus `matched_cents` over the project's donations in `CAPTURED` or `CHOICE_PENDING` status only. The instant a donation or an equity allocation makes `funded_cents` greater than or equal to `goal_cents` — the boundary is inclusive, so exact equality funds the project — the project transitions from `FUNDING` to `FUNDED` automatically. At that moment the system groups the project's pinned items by vendor, auto-issues exactly one purchase order per distinct vendor with at least one item (§3.7), and auto-creates exactly one thank-you package for the project in status `PENDING` — there is exactly one package per funded project, enforced by uniqueness of the package's `project_id`.

### 3.6. Expiration, Donor Choice, and Reallocation

When the sweep (§2.4) expires a `FUNDING` project, the project lands in terminal `EXPIRED`, and each of its `CAPTURED` donations cascades to `CHOICE_PENDING` with `choice_deadline` set to the sweep timestamp plus 14 days. At the same moment each such donation's `matched_cents` is clawed back to its match campaign: the campaign's `matched_so_far_cents` decreases and its `remaining_budget_cents` increases by the same amount, and an `EXHAUSTED` campaign whose window is still open flips back to `ACTIVE`. Because the match is clawed at expiry, a later refund moves only principal.

A donation in `CHOICE_PENDING` waits on its donor's decision, expressed as a `choice` of `REFUND` or `REALLOCATE` together with `expected_donation_version` (the concurrency rule of §2.7; a stale observation, for example one captured before the sweep bumped the donation into `CHOICE_PENDING`, fails with `ERR_STALE_VERSION`). The donation must still be `CHOICE_PENDING` (`ERR_INVALID_STATE` otherwise), the logical clock must be strictly before the donation's `choice_deadline` (`ERR_CHOICE_WINDOW_EXPIRED`), and the acting donor must own the donation — its `donor_id` must equal `X-User-ID` (`ERR_FORBIDDEN`).

Choosing `REFUND` moves the donation to `REFUNDED` with `refund_reason` set to `EXPIRED_CHOICE`; the project's `funded_cents` decreases by `amount_cents` (and nothing more — the match left at expiry), and the donor's `lifetime_refunded_cents` increases by `amount_cents`. Choosing `REALLOCATE` additionally names an `equity_fund_id`, which must reference an equity fund that is `ACTIVE` and whose closed window covers now; a missing fund id, a non-`ACTIVE` fund, or an out-of-window fund all fail with `ERR_INVALID_REALLOCATION_TARGET`. On success the donation moves to `REALLOCATED` with its `equity_fund_id` set to the receiving fund, the fund's `remaining_cents` increases by `amount_cents` (and a `DEPLETED` fund flips back to `ACTIVE` if its window still covers now), the donor's `lifetime_reallocated_cents` increases by `amount_cents`, and the project's `funded_cents` decreases by `amount_cents`.

A donor who never chooses forfeits the choice: the sweep auto-refunds any donation still `CHOICE_PENDING` once the clock reaches its `choice_deadline` (equality triggers the refund), moving it to `REFUNDED` with `refund_reason` set to `EXPIRED_AUTO`, with the same principal movements as a chosen refund. `REFUNDED` and `REALLOCATED` are the terminal states of a donation.

### 3.7. Fulfillment: Purchase Orders, Delivery, and the Thank-You Gate

Each auto-issued purchase order records its `project_id` and `vendor_id`, a `line_items` snapshot array — each entry carrying `catalog_item_id`, `sku`, `quantity`, and `pinned_unit_price_cents` — sorted by the catalog item's `created_at` ascending (never by id), a `line_total_cents` equal to the sum of pinned price times quantity over those lines, and a `shipping_fee_cents` equal to the shipping quote of §3.2 computed over those lines at issuance. The order starts in status `ISSUED`, stamped with `issued_at` at the current logical-clock time, with `ship_by_due` set to `issued_at` plus 10 days. Purchase orders are readable individually or as a list (filtered by `vendor_id`, `project_id`, or `status`); each row also shows `tracking_number`, `shipped_at`, and `delivered_at` as the shipment progresses.

The vendor ships its own orders: advancing the purchase order identified by `po_id` with `action` value `SHIP` requires the acting `X-User-ID` to equal the order's `vendor_id` (`ERR_FORBIDDEN` otherwise), the order to be `ISSUED` (`ERR_INVALID_STATE` otherwise), the vendor's `status` to be `ACTIVE` (a `SUSPENDED` vendor cannot ship — `ERR_INVALID_STATE`), and a `tracking_number` in the request (its absence fails with `ERR_INVALID_REQUEST`). Shipping moves the order to `SHIPPED` and stamps `shipped_at`.

Delivery confirmation belongs to the project's owning teacher — or to a `PlatformAdmin`; anyone else is `ERR_FORBIDDEN`. Advancing with `action` value `DELIVER` moves a `SHIPPED` order to `DELIVERED` and stamps `delivered_at`. When every purchase order of the project has reached `DELIVERED`, the project bubbles up from `FUNDED` to `FULFILLED` automatically, and from that moment the thank-you gate applies to the teacher: while any `PENDING` thank-you package sits on a `FULFILLED` project of theirs, creating a new project is rejected with `ERR_THANK_YOU_OUTSTANDING`.

The teacher discharges that obligation by submitting the package — the project's single thank-you package, readable as an array of length 0 or 1 — carrying a `thank_you_note` of at least 20 characters and an `impact_report` of at least 40 characters (shorter texts fail with `ERR_INVALID_REQUEST`). The package must be `PENDING` and the project must be `FULFILLED` (`ERR_INVALID_STATE` otherwise), the actor must be the project's owning teacher (`ERR_FORBIDDEN`), and a suspended teacher is blocked by `ERR_TEACHER_SUSPENDED`. On success the package moves to `SUBMITTED`, `submitted_at` is stamped from the logical clock, and the project bubbles up from `FULFILLED` to terminal `CLOSED`.

### 3.8. Fraud: Diversion Reports and the Clawback Cascade

When materials never reach the classroom, a `PlatformAdmin` reports diversion on the shipment: advancing a purchase order with `action` value `REPORT_DIVERSION` requires the order to be `SHIPPED` (`ERR_INVALID_STATE` otherwise) and requires that no `OPEN` fraud case already exist for that teacher — at most one case per teacher may be open at a time, and a duplicate report fails with `ERR_FRAUD_CASE_ALREADY_OPEN`. The order moves to terminal `DIVERSION_REPORTED`, and a fraud case is created in status `OPEN` linking the accused `teacher_id`, the `project_id`, and the `purchase_order_id`, with its `reason` copied verbatim from the report's `reason` text. Fraud cases are readable individually or as a list filtered by `teacher_id`, `project_id`, `purchase_order_id`, or `status`.

Resolving a case takes an `outcome` and an optional `notes` text. `DISMISSED` moves an `OPEN` case to `DISMISSED` with no side effects. `CONFIRMED` moves it to `CONFIRMED` and fires the full clawback cascade, in this fixed order:

1. The teacher transitions to `SUSPENDED`.
2. Every project of that teacher in `DRAFT`, `IN_REVIEW`, `VETTING`, `RETURNED`, `FUNDING`, or `FUNDED` transitions to `CANCELLED`, processed in project `created_at` ascending order. Projects already in a terminal or post-funding state (`EXPIRED`, `REJECTED`, `FULFILLED`, `CLOSED`, already `CANCELLED`) are outside the cascade.
3. For each project cancelled out of `FUNDING` or `FUNDED`, every donation in `CAPTURED` or `CHOICE_PENDING` transitions to `REFUNDED` with `refund_reason` set to `FRAUD_CLAWBACK`: the donor's `lifetime_refunded_cents` increases by `amount_cents`, and the project's `funded_cents` decreases by `amount_cents` plus `matched_cents`.
4. Each refunded donation's `matched_cents` returns to its match campaign — `matched_so_far_cents` decreases and `remaining_budget_cents` increases by the same amount — and an `EXHAUSTED` campaign whose window is still open flips back to `ACTIVE`.
5. Each purchase order of those projects in `ISSUED` or `SHIPPED` transitions to `CANCELLED`; orders already `DELIVERED` or `DIVERSION_REPORTED` are left untouched as the evidence trail.

Any transition attempted on a case that is no longer `OPEN` fails with `ERR_INVALID_STATE`. Because a confirmed case suspends the teacher, the reinstatement path of §3.1 (blocked while a case is `OPEN`) is how a wrongly accused teacher returns after a dismissal.

### 3.9. Match Campaigns and Equity Funding Programs

A `PlatformAdmin` creates a match campaign with a `sponsor_name`, a `match_ratio` greater than 0 and at most 2.0, a `budget_cents` of at least 1, a `target_type` of `SCHOOL`, `SUBJECT`, or `STATE` with its `target_value` (a school id, a subject value, or a state code respectively), a `starts_at`, an `ends_at`, and optionally a `min_donation_cents` (default 0). The window is half-open: the campaign is active exactly when `starts_at` is at or before now and now is strictly before `ends_at`. A new campaign starts `ACTIVE` with `matched_so_far_cents` at 0 and `remaining_budget_cents` equal to `budget_cents`. Its window must not overlap any `ACTIVE` campaign sharing the same `sponsor_name`, `target_type`, and `target_value`, judged with half-open arithmetic — the existing campaign's `starts_at` strictly before the new campaign's `ends_at`, and the new campaign's `starts_at` strictly before the existing campaign's `ends_at`; two windows that merely touch at an endpoint are allowed. An overlap fails with `ERR_CAMPAIGN_WINDOW_OVERLAP`. Thereafter the campaign flips `ACTIVE` to `EXHAUSTED` when its remaining budget reaches 0 after a match, flips back from `EXHAUSTED` to `ACTIVE` when a clawback restores the remaining budget above 0 while the window is still open, and is swept to terminal `CLOSED` once `ends_at` is at or before now. The budget conservation invariant of §2.9 holds throughout.

Equity funds are the platform's programs for steering money to high-poverty schools. A `PlatformAdmin` creates one with a `name`, the two-letter `state_code` it serves, a `min_poverty_pct` between 0.0 and 100.0 inclusive, a `budget_cents` of at least 1, a `window_start`, a `window_end`, and optionally a `subject` restriction (default null, meaning any subject). Unlike campaigns, the fund window is a *closed* interval: the fund is allocatable exactly when `window_start` is at or before now and now is at or before `window_end`. A school qualifies for a fund when its `poverty_pct` is greater than or equal to `min_poverty_pct` — the boundary is inclusive. A new fund starts `ACTIVE` with `remaining_cents` equal to `budget_cents`. The overlap rule is stricter than the campaign rule: a new fund's window must not overlap *or touch* any `ACTIVE` fund with the same `state_code` — closed-interval arithmetic, meaning the existing fund's `window_start` is at or before the new fund's `window_end` and the new fund's `window_start` is at or before the existing fund's `window_end` — so an adjacent window sharing a boundary day already conflicts, and fails with `ERR_EQUITY_WINDOW_OVERLAP`.

Allocating from the fund identified by `fund_id` is a `PlatformAdmin` action with no request body. The fund must be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and its closed window must cover now (`ERR_EQUITY_WINDOW_CLOSED`). The eligible candidate set is every project in `FUNDING` whose `funding_deadline` is still strictly ahead of the clock, whose school's `state_code` equals the fund's, whose school's `poverty_pct` is at least the fund's `min_poverty_pct`, and whose `subject` equals the fund's `subject` whenever the fund restricts one. Candidates are ranked by their school's `equity_score_weighted` in descending order, with ties broken by the project's `created_at` ascending — `created_at` is the only tie-break and id is never used — and the selector picks the single best project. An empty candidate set fails with `ERR_NO_ELIGIBLE_PROJECT`.

The grant amount is the lesser of the project's remaining need (`goal_cents` minus `funded_cents`) and the fund's `remaining_cents`. It is recorded as a donation with `kind` set to `EQUITY_GRANT`, `donor_id` null, `equity_fund_id` set to the fund, `matched_cents` 0, and status `CAPTURED`. The fund's `remaining_cents` decreases by the granted amount, flipping to `DEPLETED` if it reaches exactly 0, and the project's `funded_cents` increases by the same amount. The grant may tip the project past its goal — the inclusive funding rule of §3.5 applies identically — in which case the project moves to `FUNDED` and purchase-order issuance plus the `PENDING` thank-you package fire exactly as they would for a donor's tip. A `DEPLETED` fund returns to `ACTIVE` when a reallocated donation raises its `remaining_cents` above 0 while its window still covers now (reallocated principal adds to the fund's balance), and the sweep moves `ACTIVE` or `DEPLETED` funds to terminal `CLOSED` once `window_end` is strictly before now.

## 4. Endpoint Definitions

Status codes follow one general rule: endpoints that create a new resource respond with 201 Created and return the new resource; all other successful operations — reads, state transitions, edits, sweeps — respond with 200 OK and return the affected resource (or, for the clock and sweep utilities, a small summary payload). Error responses follow §2.2 and use the codes catalogued in §5. The full request/response detail behind each row lives in §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server's logical clock (starts at `2026-09-01T00:00:00Z`; never wall-clock) | PlatformAdmin |
| POST | `/_sweeps/expiration_run` | Run the four-phase expiration sweep: expire funding projects, open donor choice windows, auto-refund expired choices, close out-of-window campaigns and funds | PlatformAdmin |
| POST | `/giving/schools` | Register a school; both equity score variants are computed at creation | PlatformAdmin |
| GET | `/giving/schools/{school_id}` | Read a school, including `equity_score_banded` and `equity_score_weighted` | PlatformAdmin, Reviewer, Teacher |
| POST | `/giving/teachers` | Self-service teacher registration; `employment_status` starts `PENDING_VERIFICATION` | Anonymous |
| GET | `/giving/teachers/{teacher_id}` | Read a teacher | PlatformAdmin, Reviewer, Teacher |
| GET | `/giving/teachers` | List teachers with optional `school_id` and `employment_status` filters | PlatformAdmin, Reviewer |
| POST | `/giving/teachers/{teacher_id}/employment-review` | `action=VERIFY` (PENDING_VERIFICATION → VERIFIED) or `action=REINSTATE` (SUSPENDED → VERIFIED, blocked while a fraud case is OPEN) | PlatformAdmin |
| POST | `/giving/vendors` | Register a vendor; `status` starts `ACTIVE` | PlatformAdmin |
| GET | `/giving/vendors/{vendor_id}` | Read a vendor | PlatformAdmin, Reviewer, Teacher, Vendor |
| POST | `/giving/vendors/{vendor_id}/suspend` | Suspend a vendor: blocks new catalog items and SHIP actions; other existing purchase orders unaffected | PlatformAdmin |
| POST | `/giving/vendors/{vendor_id}/catalog-items` | Add a catalog item to the vendor | PlatformAdmin, Vendor (own vendor only) |
| GET | `/giving/vendors/{vendor_id}/catalog-items` | List a vendor's catalog items with optional `category` and `status` filters | PlatformAdmin, Reviewer, Teacher, Vendor, Donor |
| PATCH | `/giving/vendors/{vendor_id}/catalog-items/{item_id}` | Edit an item's current `unit_price_cents` and/or move `status` from `ACTIVE` to `DISCONTINUED`; price edits move provisional quotes of DRAFT/RETURNED projects, never pinned totals | PlatformAdmin, Vendor (own vendor only) |
| POST | `/giving/projects` | Create a DRAFT project for the acting teacher (`teacher_id` from `X-User-ID`, `school_id` denormalized) | Teacher |
| GET | `/giving/projects` | List projects with optional `teacher_id`, `school_id`, `status`, `subject`, and `state_code` filters | PlatformAdmin, Reviewer, Teacher, Donor, Vendor |
| GET | `/giving/projects/{project_id}` | Read a project; while DRAFT or RETURNED, `provisional_total_cents` recomputes at current catalog prices on each read | PlatformAdmin, Reviewer, Teacher, Donor, Vendor |
| POST | `/giving/projects/{project_id}/items` | Add a catalog item to a DRAFT/RETURNED project (OCC via `expected_project_version`) | Teacher (own project) |
| GET | `/giving/project-items/{item_id}` | Read one project item | PlatformAdmin, Reviewer, Teacher, Donor |
| GET | `/giving/project-items` | List project items with optional `project_id` and `catalog_item_id` filters | PlatformAdmin, Reviewer, Teacher, Donor |
| POST | `/giving/projects/{project_id}/submit` | Submit for screening (DRAFT/RETURNED → IN_REVIEW); pins unit prices and freezes the goal (OCC via `expected_project_version`) | Teacher (own project) |
| POST | `/giving/projects/{project_id}/review` | Reviewer decision: `stage=SCREEN` on IN_REVIEW, `stage=VET` on VETTING; `outcome` APPROVE/RETURN (REJECT only at VET); VET actor must differ from `screened_by_id` | Reviewer |
| POST | `/giving/donors` | Self-service donor registration | Anonymous |
| GET | `/giving/donors/{donor_id}` | Read a donor, including the three lifetime aggregates | PlatformAdmin, Donor (self) |
| POST | `/giving/projects/{project_id}/donations` | Donate to a FUNDING project; optional `match_campaign_id` applies a per-donation rounded match; tipping `funded_cents` to the goal flips the project to FUNDED and auto-issues purchase orders | Donor |
| GET | `/giving/donations/{donation_id}` | Read a donation | PlatformAdmin, Donor, Teacher, Reviewer |
| GET | `/giving/donations` | List donations with optional `donor_id`, `project_id`, `status`, `match_campaign_id`, and `equity_fund_id` filters | PlatformAdmin, Donor |
| POST | `/giving/donations/{donation_id}/reallocation-choice` | Donor choice on a CHOICE_PENDING donation: `choice=REFUND` or `choice=REALLOCATE` to an equity fund (OCC via `expected_donation_version`) | Donor (own donation) |
| POST | `/giving/match-campaigns` | Create a targeted match campaign; half-open window; same sponsor+target windows may not overlap (touching allowed) | PlatformAdmin |
| GET | `/giving/match-campaigns/{campaign_id}` | Read a match campaign, including `matched_so_far_cents` and `remaining_budget_cents` | PlatformAdmin, Reviewer, Donor |
| GET | `/giving/purchase-orders/{po_id}` | Read a purchase order | PlatformAdmin, Reviewer, Teacher, Vendor |
| GET | `/giving/purchase-orders` | List purchase orders with optional `vendor_id`, `project_id`, and `status` filters | PlatformAdmin, Reviewer, Teacher, Vendor |
| POST | `/giving/purchase-orders/{po_id}/advance` | `action=SHIP` (Vendor, ISSUED → SHIPPED, `tracking_number` required), `action=DELIVER` (owning Teacher or PlatformAdmin, SHIPPED → DELIVERED), `action=REPORT_DIVERSION` (PlatformAdmin, SHIPPED → DIVERSION_REPORTED, opens a fraud case) | Vendor, Teacher, PlatformAdmin (per action) |
| POST | `/giving/projects/{project_id}/thank-you-package` | Submit `thank_you_note` and `impact_report` for a FULFILLED project's PENDING package; bubbles the project to CLOSED | Teacher (own project) |
| GET | `/giving/projects/{project_id}/thank-you-package` | Read the project's thank-you package (array of length 0 or 1) | PlatformAdmin, Reviewer, Teacher |
| GET | `/giving/fraud-cases/{case_id}` | Read a fraud case | PlatformAdmin, Reviewer |
| GET | `/giving/fraud-cases` | List fraud cases with optional `teacher_id`, `project_id`, `purchase_order_id`, and `status` filters | PlatformAdmin, Reviewer |
| POST | `/giving/fraud-cases/{case_id}/resolve` | Resolve an OPEN case: `outcome=CONFIRMED` runs the full clawback cascade; `outcome=DISMISSED` has no side effects | PlatformAdmin |
| POST | `/giving/equity-funds` | Create an equity funding program; closed-interval window; same-state fund windows may not overlap or touch | PlatformAdmin |
| GET | `/giving/equity-funds/{fund_id}` | Read an equity fund | PlatformAdmin, Reviewer, Donor |
| POST | `/giving/equity-funds/{fund_id}/allocate` | Select the best eligible FUNDING project (weighted equity score descending, `created_at` ascending) and grant the lesser of remaining need and fund balance as an EQUITY_GRANT donation | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them (§2 and §3); this table is only the code-to-status index.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TEACHER_NOT_VERIFIED` | 409 |
| `ERR_TEACHER_SUSPENDED` | 409 |
| `ERR_FUNDING_WINDOW_CLOSED` | 409 |
| `ERR_MATCH_WINDOW_CLOSED` | 409 |
| `ERR_CHOICE_WINDOW_EXPIRED` | 409 |
| `ERR_EQUITY_WINDOW_CLOSED` | 409 |
| `ERR_CAMPAIGN_WINDOW_OVERLAP` | 409 |
| `ERR_EQUITY_WINDOW_OVERLAP` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_ACTIVE_PROJECT_EXISTS` | 409 |
| `ERR_THANK_YOU_OUTSTANDING` | 409 |
| `ERR_DUPLICATE_CATALOG_ITEM` | 409 |
| `ERR_FRAUD_CASE_ALREADY_OPEN` | 409 |
| `ERR_CATALOG_ITEM_UNAVAILABLE` | 422 |
| `ERR_MATCH_TARGET_MISMATCH` | 422 |
| `ERR_INVALID_REALLOCATION_TARGET` | 422 |
| `ERR_NO_ITEMS` | 422 |
| `ERR_GOAL_OUT_OF_RANGE` | 422 |
| `ERR_DONATION_EXCEEDS_REMAINING` | 422 |
| `ERR_DONATION_BELOW_MATCH_MIN` | 422 |
| `ERR_NO_ELIGIBLE_PROJECT` | 422 |
