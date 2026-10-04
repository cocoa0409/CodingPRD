# Classroom Book Club API — Product Requirements Document

## 1. Introduction

Every month, classroom book clubs live or die on a paper flyer: a teacher hands out a grade-appropriate catalog, families send back order forms (or order online), the teacher consolidates everything into a single class shipment to the school, and the club rewards the teacher with points redeemable for classroom books and supplies. Behind that simple ritual sits a surprisingly dense web of economics — tiered discounts on the consolidated order, bonus-point promotions that shape what families buy, per-title licensing with royalty caps that can suspend a title mid-season, school book fairs whose featured titles must not double-count for rewards, and donation-matching programs that ship free books into low-income classrooms. This document specifies the REST API that operates that whole machine: monthly flyer cycles per school and grade band, teacher-managed class orders that merge parent online submissions with teacher-entered lines, a reward-points ledger with earning, redemption, clawback, and expiry, plus the licensing, fair-scheduling, and donation-matching subsystems that constrain them.

The platform serves five constituencies — club operations staff, school administrators, teachers, parents, and donors — whose permissions overlap in deliberate ways and whose actions cascade across entities. A single school program suspension cancels every open class order in the building; a single royalty threshold crossing suspends a license and backorders every future order line for that title; a single clock advance activates book fairs, expires promotions, and re-derives which fair is "current" at every school. Because correctness here is a matter of money, points, and contractual royalties, the specification below is precise about arithmetic, rounding, and ordering, and deliberately scatters business rules across the narrative sections where they naturally live. The API is mounted under the `/club` path prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting user and `X-User-Role` naming their role. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authentication is always evaluated before authorization, and both are evaluated before any resource lookup or business rule.

The declared roles are exactly these five:

- **`ClubAdmin`** — the club platform operator. Owns school registration and program suspension/reinstatement, title acquisition and license renegotiation, promotion management, flyer cycle creation/publication/closure and their offerings, the operational sweeps (shipping and points expiry), the logical clock, and donation fulfillment. May also schedule and cancel book fairs and cancel donation requests, and may read any resource.
- **`SchoolAdmin`** — school staff. Schedules and cancels book fairs and adds fair titles, registers teachers, creates and cancels donation requests, and reads school-scoped resources.
- **`Teacher`** — a classroom teacher. Creates, submits, and cancels their own class orders; creates, updates, and cancels order lines; creates, confirms, and cancels their own redemptions; creates donation requests; reads flyers, offerings, and their own points ledger.
- **`Parent`** — a parent or guardian submitting online orders. Creates, updates, and cancels order lines, but only lines originally submitted through the parent online channel, and reads offerings and orders.
- **`Donor`** — a sponsor. Matches donation requests and reads donation requests, schools, and titles.

Role identity semantics differ by role. When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting `Teacher` entity; ownership checks on any resource that references a `Teacher` — class orders, redemptions, donation requests, points ledgers — compare the resource's `teacher_id` field to `X-User-ID`, and a mismatch on an ownership-guarded action is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `ClubAdmin`, `SchoolAdmin`, `Parent`, or `Donor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Parent line-level ownership is instead mediated by the `submitted_by` channel recorded on each order line, as described in §3.4.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and must not exceed 100. The `offset` parameter defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are always sorted by `created_at` in ascending order, with ties broken by `id` in ascending order, and their `meta` object carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more` (true exactly when `offset` plus the returned page size is less than `total_count`).

Several list endpoints additionally accept domain filter query parameters, all optional: `grade_band` and `status` on flyer cycle lists; `status` on book fair, donation request, class order, order line, promotion, and redemption lists; `school_id` on the teacher list; `entry_type` on the points ledger list; and `format` and `license_status` on the title list. The promotion list also accepts `kind`.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Every resource in this system additionally carries `updated_at` (same format, refreshed on every mutation) and `version`, an integer that starts at 1 on creation and increments by exactly one on every mutation of that resource. The `version` field is the backbone of optimistic concurrency control (§2.6); clients read it and quote it back on guarded writes.

### 2.5. The Logical Clock

The server maintains a logical clock that governs every time-dependent rule in the system: promotion windows, book fair activation and completion, the derivation of each school's current fair, and points expiry. At server startup, before any clock-setting call, the logical clock is exactly `2026-09-01T00:00:00Z`; the server never falls back to the wall clock. A `ClubAdmin` advances the logical clock through an admin-only test-driving capability that accepts a target instant `to_iso8601` in ISO 8601 — `Z` suffixed and offset forms are both accepted and normalized to a `YYYY-MM-DDTHH:MM:SSZ` UTC instant, with an unparseable value rejected with `ERR_INVALID_REQUEST` — and the set responds with HTTP 200 and an empty `data` object. The clock may move backward as well as forward; only transitions whose boundary was crossed fire, in `created_at` then `id` order per fair. Advancing the clock fires every scheduled transition whose boundary was crossed: book fairs move from `SCHEDULED` to `ACTIVE` when the clock date enters the fair's `[start_date, end_date)` window and from `ACTIVE` to `COMPLETED` when the clock date reaches or passes `end_date` — and when a single advance jumps past the entire window, the fair moves directly from `SCHEDULED` to `COMPLETED` — and every fair whose status changed increments its `version`; promotions move from `ACTIVE` to `EXPIRED` once the clock date is on or after the promotion's `ends_on`; and each school's `active_fair_id` is recomputed. A promotion's `status` and a school's `active_fair_id` are computed on read rather than stored, so any clock setting — including a backward move — is reflected in them immediately. An `EXPIRED` promotion never applies to any calculation, regardless of when it was created.

Dates supplied by clients — promotion windows, fair windows, enrollment dates — use the `YYYY-MM-DD` calendar-date format; a value that does not parse in that format is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control. Each requires the client to quote the version of the parent entity it last observed, as a non-optional request field.

A class order submission must carry `expected_class_order_version`, equal to the class order's current `version`. Because adding, updating, or cancelling a line recomputes the order's aggregates and bumps the order's `version`, a client whose priced view predates the latest line mutation holds a stale version; if `expected_class_order_version` does not match the order's current `version`, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a teacher from submitting a consolidated order whose pricing and points preview they have not actually observed.

A title license renegotiation must carry `expected_title_version`, equal to the title's current `version`. If another acquisition or a royalty-driven license flip has advanced the title's `version` since the client last read it, the renegotiation is rejected with `ERR_STALE_VERSION` (HTTP 412), since the client based its proposed cap on a cap-and-accrual picture that no longer exists. No other endpoint accepts a version field; endpoints not named here must not require one.

### 2.7. Monetary Precision and Rounding

All money is represented as integer cents. Fields such as `base_price_cents`, `royalty_cap_cents`, `royalty_accrued_cents`, `flyer_price_cents`, `unit_price_cents`, `subtotal_cents`, `rewardable_subtotal_cents`, `discount_cents`, `net_total_cents`, and `shipping_fee_cents` are whole-cent integers. Where a computation produces a fraction of a cent, it is rounded half-up to a whole cent, applied exactly once to the aggregate — never per line and then summed. Where a computation produces points or derived prices by division, the result is floored to the integer below. These precision rules are stated again beside each calculation in §3 where they apply.

### 2.8. Validation Order and Error Precedence

When several validation rules could reject the same request, the server evaluates them in a fixed priority order and reports the first failure. The order is:

1. Authentication (`ERR_UNAUTHENTICATED`) — headers present, role declared.
2. Authorization (`ERR_UNAUTHORIZED`) — role permitted for the endpoint.
3. Path existence (`ERR_NOT_FOUND`) — path identifiers exist, checked left to right. Unmatched URL routes and unsupported methods on known routes also surface as `ERR_NOT_FOUND` (HTTP 404).
4. Body reference existence (`ERR_REFERENCE_NOT_FOUND`) — foreign keys in the request body exist.
5. Transition legality (`ERR_INVALID_STATE`) — the entity is in a state from which the requested transition exists.
6. Terminal lockdown (`ERR_ALREADY_TERMINAL`) — no transition leaves a terminal state. Terminal lockdown is detected before generic transition legality: a transition attempted from a terminal state reports `ERR_ALREADY_TERMINAL`, never `ERR_INVALID_STATE`.
7. School posture (`ERR_SCHOOL_RESTRICTED`) — the school's posture gates the operation.
8. License status (`ERR_LICENSE_SUSPENDED`) — the title's license gates the operation.
9. Royalty cap sanity (`ERR_ROYALTY_CAP_INVALID`).
10. Grade band agreement (`ERR_GRADE_BAND_MISMATCH`).
11. Offering format gate (`ERR_FORMAT_NOT_ALLOWED`).
12. Published-cycle uniqueness (`ERR_CYCLE_ALREADY_PUBLISHED`).
13. Non-empty cycle for publish (`ERR_EMPTY_CYCLE`).
14. Book fair window overlap (`ERR_FAIR_OVERLAP`).
15. Fair title overlap cap (`ERR_TITLE_OVERLAP_CAP`).
16. Promotion window sanity (`ERR_PROMO_WINDOW_INVALID`).
17. Promotion shape (`ERR_PROMO_SHAPE_INVALID`).
18. Redemption affordability (`ERR_INSUFFICIENT_POINTS`).
19. Clawback solvency (`ERR_POINTS_BALANCE_NEGATIVE`).
20. Low-income program gate (`ERR_NOT_LOW_INCOME`).
21. Ownership (`ERR_FORBIDDEN_OWNERSHIP`).
22. Order open for line mutation (`ERR_ORDER_NOT_OPEN`).
23. Field shape (`ERR_INVALID_REQUEST`) — quantity at least one, dates parse, enum members valid, integer fields actually integers, required string fields actually strings, `email` unique across all teachers, `isbn` unique across all titles.
24. Submit non-emptiness (`ERR_ORDER_EMPTY`).
25. Optimistic concurrency (`ERR_STALE_VERSION`).

So, for example, a submission attempted by a teacher who does not own the order against a school whose posture is `RESTRICTED` surfaces `ERR_SCHOOL_RESTRICTED`, because posture (priority 7) is evaluated before ownership (priority 21); and a submission carrying a stale version on an otherwise valid order surfaces `ERR_STALE_VERSION` only after every other check has passed.

### 2.9. Nested Resource Retrieval and Path Existence

Endpoints with hierarchical paths validate path identifiers strictly left to right — school before cycle, cycle before order, order before line. The first identifier that does not exist yields `ERR_NOT_FOUND` (HTTP 404), and later identifiers are not consulted. Foreign keys supplied in a request body — `teacher_id`, `cycle_id`, `offering_id`, `title_id`, `fair_id`, `school_id` — are validated separately from path identifiers; a body-referenced id that does not exist yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404). Every mutation that changes a resource refreshes its `updated_at` and increments its `version` by one, and mutations that cascade into child resources (for example, cancelling a class order cancelling its lines) increment each affected resource's `version` accordingly.

## 3. Business Logic & Workflows

### 3.1. Schools, Program Enrollment, and Posture

A `ClubAdmin` registers a school with a display `name` and a street `address`. The address is the ship-to for everything physical: every consolidated class order and every donation shipment delivers to the school's `address`. At registration the school may also be flagged with `low_income_program`, a boolean defaulting to false, which marks enrollment in the low-income school program. That flag unlocks two privileges described later: order-level free shipping regardless of basket size (§3.6), and eligibility to create donation requests (§3.9).

A school carries a computed `posture`, either `NORMAL` or `RESTRICTED`, derived entirely from its program enrollment history rather than stored as an input. A school is `NORMAL` when it has a program enrollment in `ACTIVE` status — or when no enrollment has ever been created for it at all — and `RESTRICTED` while its enrollment is suspended. A `ClubAdmin` enrolls a school by supplying an `enrolled_on` date, which creates a program enrollment in `ACTIVE` status; a school may hold at most one `ACTIVE` enrollment at a time, and an attempt to enroll a school that already has one is rejected with `ERR_ENROLLMENT_EXISTS` (HTTP 409) — checked before the `enrolled_on` date's format is validated. Each enrollment row records its `school_id` and `status`.

Posture is not decorative: it gates five operations. Submitting a class order, publishing a flyer cycle, matching a donation request, confirming a redemption, and scheduling a book fair all require the relevant school's posture to be `NORMAL`; while the school is `RESTRICTED`, each of these is rejected with `ERR_SCHOOL_RESTRICTED` (HTTP 409).

Suspension is the dramatic path. When a `ClubAdmin` suspends the program of a school whose posture is `NORMAL` and which has an `ACTIVE` enrollment, four things happen in one cascade: the school's posture flips from `NORMAL` to `RESTRICTED`; the enrollment's `status` moves from `ACTIVE` to `SUSPENDED`; every class order still `OPEN` belonging to any teacher of that school is auto-cancelled — its status moves to `CANCELLED` and every one of its open order lines moves to `CANCELLED` with it; and the school's `active_fair_id` is recomputed (which changes nothing unless the clock has moved). The suspension also touches the school's own `version` (increment by one). Reinstatement is the mirror: for a school in `RESTRICTED`, a `ClubAdmin` reinstatement flips the enrollment back to `ACTIVE` (also bumping the school's `version`), the posture back to `NORMAL`, and recomputes `active_fair_id` against the logical clock. Attempting to suspend a school whose posture is not `NORMAL` — or which has no `ACTIVE` enrollment — is rejected with `ERR_INVALID_STATE` (HTTP 409); likewise, attempting to reinstate a school whose posture is not `RESTRICTED` is rejected with `ERR_INVALID_STATE`. Because enrollment drives posture, enrollments can be listed per school, and teachers, flyer cycles, book fairs, and donation requests are all listed per school as well.

### 3.2. Teachers and the Points Ledger

A `ClubAdmin` or `SchoolAdmin` registers a teacher with a `full_name`, a login `email` (unique across all teachers — duplicates are rejected with `ERR_INVALID_REQUEST`; both fields must be strings), the `school_id` of their school, and the `grade_band` they teach: exactly one of `K_2`, `G3_5`, or `G6_8`. A newly registered teacher starts with all five points counters at zero. The `school_id` is immutable after registration; the grade band scopes everything the teacher touches, because flyer cycles and their offerings are band-scoped and class orders require the teacher's band to match the cycle's band.

Teachers accumulate reward points. Five computed counters track the lifetime of those points: `points_earned_total` (all points ever earned — base, bonus, and incentive, at the rate in force when awarded), `points_redeemed_total` (all points consumed by redemption transactions), `points_expired_total` (all points voided by the monthly expiry sweep), `donated_books_received` (the cumulative count of matched donation copies delivered to this teacher), and `points_balance`, the currently redeemable total. The balance is not independently stored truth — it must always reconcile as earned minus redeemed minus expired, and every mechanism that moves points maintains that identity.

Every movement of points is recorded in the teacher's points ledger. A ledger entry carries the `teacher_id` of its owner, an `entry_type` of `EARN`, `REDEEM`, `EXPIRE`, `CLAWBACK`, or `ADJUST`; a signed `points` amount (positive for `EARN`, negative for `REDEEM`, `EXPIRE`, and `CLAWBACK`, either sign for `ADJUST`); a `ref_type` naming what the entry references — `CLASS_ORDER`, `REDEMPTION`, `OPS_RUN`, or `MANUAL` — with the referenced id in `ref_id`; and a free-text `note` (required for `ADJUST` entries, otherwise defaulting to empty). A teacher can read their own ledger, as can a `ClubAdmin`; the ledger is the audit trail behind every balance figure in the system.

### 3.3. Title Acquisition, Licensing, and Royalties

Before a title can appear on any flyer, a `ClubAdmin` acquires it, registering the catalog entry with its `isbn` (an ISBN-13 key, unique across all titles), display `name`, physical `format` (one of `HARDCOVER`, `PAPERBACK`, or `CLUB_PAPERBACK`), the `grade_band` it may be offered to, its `base_price_cents` list price in cents (must be greater than zero — this is what families pay before club pricing), its `points_cost` in reward points for one copy redeemed as a classroom book (must be greater than zero), the `rights_holder` licensor name (a string, as are `isbn` and `name`), and the `royalty_cap_cents` — the lifetime royalty ceiling owed to the rights holder, in cents, which must be greater than zero; a `royalty_cap_cents` of zero or negative is a field-shape failure rejected with `ERR_INVALID_REQUEST`, never `ERR_ROYALTY_CAP_INVALID`, because zero accrued royalties can never exceed any cap. At acquisition the cap is validated against the title's accrued royalties, which are zero at creation; a proposed `royalty_cap_cents` below the title's current `royalty_accrued_cents` is rejected with `ERR_ROYALTY_CAP_INVALID` (HTTP 422), because a license can never cap below what is already owed. The same rule guards renegotiation: a `ClubAdmin` may later set a new `royalty_cap_cents` on an existing title — a write guarded by optimistic concurrency as described in §2.6 — after which the title's license status is recomputed against the new cap and the title's `version` increments.

Royalties accrue at a flat 90 cents per unit moved. Three events accrue royalty, each per unit: a class order submission accrues for every ordered line's quantity; a donation fulfillment accrues for the matched quantity; and confirming a book-kind redemption accrues for the redeemed quantity, since redemption copies are club editions. Units are applied in chronological order of the triggering event's `created_at`, earliest first. The first unit that pushes the title's `royalty_accrued_cents` strictly above its `royalty_cap_cents` flips the title's `license_status` from `ACTIVE` to `SUSPENDED`; the comparison is strict — landing exactly on the cap leaves the license `ACTIVE`. Suspension never blocks the in-flight event: the whole submission, fulfillment, or confirmation completes first, and only then does the title flip. Later submissions involving that title backorder instead (§3.6). Cancellation of a submitted class order reverses accrual, decrementing `royalty_accrued_cents` by 90 cents times each line's quantity; if the running total falls back to at or below the cap, the license flips from `SUSPENDED` back to `ACTIVE`.

A `SUSPENDED` license is a hard gate on four operations: adding the title as a flyer offering, creating a donation request for it, matching a donation request for it, and confirming a book-kind redemption of it are each rejected with `ERR_LICENSE_SUSPENDED` (HTTP 409). Titles can be listed with filters on `grade_band`, `format`, and `license_status`, and each title exposes reverse listings of the promotions, flyer offerings, fair-title rows, donation requests, and redemptions that reference it.

### 3.4. Promotions

Promotions shape ordering behavior by boosting the points a class order earns. A `ClubAdmin` creates a promotion with a `name`, a `kind`, an inclusive `starts_on` date, an exclusive `ends_on` date, and kind-dependent fields. When a kind-dependent field is absent the server treats it as null. Two kinds exist. A `BONUS_POINTS` promotion applies a class-value multiplier and requires `multiplier_bp`, the bonus multiplier in basis points, which must be at least 100 (100 basis points is the neutral base; 200 means double earn) — and its `title_id` must be null and it must not carry a `bonus_points_per_unit`. A `TITLE_INCENTIVE` promotion applies a flat per-unit bonus to one title and requires a non-null `title_id` (which must reference an existing title) and a `bonus_points_per_unit` value of at least zero — and it must not carry a `multiplier_bp`. A promotion whose kind-field combination violates these shapes is rejected with `ERR_PROMO_SHAPE_INVALID` (HTTP 422).

The `ends_on` must be strictly after `starts_on`, and creating a promotion whose window already lies wholly in the past — `ends_on` on or before the current logical clock date — is rejected with `ERR_PROMO_WINDOW_INVALID` (HTTP 422). An optional `grade_band` scopes the promotion to one band; a null `grade_band` means the promotion applies to all bands. A promotion's computed `status` is `ACTIVE` until the logical clock date reaches `ends_on`, at which point the clock advance flips it to `EXPIRED`, and expired promotions never apply. How active promotions combine at award time — one best multiplier plus stacking per-title incentives — is specified with the points calculation in §3.7.

### 3.5. Flyer Cycles and Offerings

The monthly flyer is modeled as a flyer cycle: a `ClubAdmin` creates one for a `school_id`, a `month` key in `YYYY-MM` form, and a `grade_band`, and it begins life in `DRAFT`. While `DRAFT`, the cycle accumulates offerings. Each offering is created inside its cycle — the `cycle_id` is fixed by the creation path — by referencing a `title_id`, and adding one is gated three ways, evaluated in this exact order: the title's license must be `ACTIVE` (otherwise `ERR_LICENSE_SUSPENDED`); the title's `grade_band` must equal the cycle's `grade_band` (otherwise `ERR_GRADE_BAND_MISMATCH`, HTTP 422); and only `PAPERBACK` and `CLUB_PAPERBACK` titles may appear on club flyers, so a `HARDCOVER` title is rejected with `ERR_FORMAT_NOT_ALLOWED` (HTTP 422). Offerings may be added only while the cycle is `DRAFT`: a closed cycle yields `ERR_ALREADY_TERMINAL` and any other non-`DRAFT` status yields `ERR_INVALID_STATE`, both checked before the three title gates. Each accepted offering increments the cycle's computed `offering_count` by one. The offering's `fair_overlap` flag is derived live from the school's fairs rather than stored.

At the moment an offering is added, its `flyer_price_cents` is pinned once and never recomputed, even if the title's `base_price_cents` later changes. For a `CLUB_PAPERBACK` title the pinned price is the title's `base_price_cents` multiplied by 70 and divided by 100, floored to whole cents — the club edition is priced at 70% of list. For `PAPERBACK` (and any other offered format) the pinned price is simply the title's `base_price_cents`.

Publishing is the gated transition from `DRAFT` to `PUBLISHED`, performed by a `ClubAdmin`, and its three checks are evaluated in the §2.8 priority order. First, the cycle's school must have posture `NORMAL`, else `ERR_SCHOOL_RESTRICTED`. Second — because published-cycle uniqueness (priority 12) outranks non-emptiness (priority 13) — no other flyer cycle for the same school and grade band may currently be `PUBLISHED`; publishing a second is rejected with `ERR_CYCLE_ALREADY_PUBLISHED` (HTTP 409). Third, the cycle must contain at least one offering; publishing an empty cycle is rejected with `ERR_EMPTY_CYCLE` (HTTP 422). At most one `PUBLISHED` cycle exists per school per band at any moment. On publication, the cycle's `version` increments, and every offering's `fair_overlap` flag is recomputed against the school's book fairs overlapping the cycle's month; for each offering whose `fair_overlap` recomputes to true, the offered title's `fair_count_used` increases by one (§3.8 defines both).

Closing moves a cycle to `CLOSED`, its terminal state. Closing from `PUBLISHED` requires that every class order in the cycle be out of `OPEN` — submitted or cancelled — else the transition is rejected with `ERR_INVALID_STATE`; lines still `BACKORDERED` at close time simply remain backordered, because backordered lines belong to their order, not to the cycle. On close, each offering whose `fair_overlap` is true stops counting against the title's fair-overlap tally, because `fair_count_used` counts only offerings of `PUBLISHED` cycles and the closing cycle leaves that set; the close changes only the cycle's own `status` and `version` and does not touch the offerings. Closing directly from `DRAFT` — a cycle abandoned before publication — is always permitted; its offerings are simply discarded for ordering purposes. Once `CLOSED`, a cycle accepts no further transitions; attempts are rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).

### 3.6. Class Orders and Order Lines

Once a cycle is `PUBLISHED`, a `Teacher` opens a class order on it by supplying `cycle_id` and their own `teacher_id`. The order's teacher must teach at the cycle's school and their `grade_band` must equal the cycle's `grade_band`, else the creation is rejected with `ERR_GRADE_BAND_MISMATCH`; and the cycle must be `PUBLISHED`, else `ERR_CYCLE_NOT_PUBLISHED` (HTTP 409). The new order opens with three independent status dimensions, each evolving in parallel: `status` begins `OPEN` and tracks the order lifecycle (`OPEN`, `SUBMITTED`, `CANCELLED`); `ship_status` begins `PENDING` and tracks fulfillment (`PENDING`, `PARTIAL`, `SHIPPED`); and `points_status` begins `UNAWARDED` and tracks reward disposition (`UNAWARDED`, `AWARDED`, `CLAWED_BACK`). No dimension implies another; the workflows below advance each explicitly.

Into an `OPEN` order, teachers and parents add order lines. A line is created inside its order — the `class_order_id` is fixed by the creation path — with an `offering_id` referencing the offered title being purchased, the `student_name` the books are for, a `submitted_by` channel of either `PARENT_ONLINE` or `TEACHER`, and a `qty` of at least one copy. Line creation, quantity updates, and line cancellation are permitted only while the parent order is `OPEN` and its cycle is `PUBLISHED`; otherwise the mutation is rejected with `ERR_ORDER_NOT_OPEN` (HTTP 409). On the quantity-update and line-cancel endpoints, a line that is already `CANCELLED` is terminal — the attempt is rejected with `ERR_ALREADY_TERMINAL` before any open-order gate. A `Parent` may create a line only with `submitted_by` equal to `PARENT_ONLINE`; a parent creating a line with `submitted_by` `TEACHER` is rejected with `ERR_FORBIDDEN_OWNERSHIP`, and that channel check is evaluated before the open-order gate. At creation each line snapshots three values from its offering that are never recomputed afterward: `unit_price_cents` copies the offering's pinned `flyer_price_cents`; `fair_overlap` copies the offering's `fair_overlap` flag; and `donation_funded` is false unless the line was created by donation matching (§3.9), in which case it is true. A line's lifecycle `status` runs from `ACTIVE` through optional `BACKORDERED` to terminal `CANCELLED`.

Line cancellation has ownership rules layered on the state rules. A teacher may cancel any line while the parent order is `OPEN`. A parent may cancel only lines whose `submitted_by` is `PARENT_ONLINE`, and only while the parent order is `OPEN`; a parent attempting to cancel a teacher-entered line is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When the parent order itself is cancelled, the system cascade cancels every line regardless of channel. Every line creation, quantity change, or cancellation recomputes all of the parent order's aggregates — `subtotal_cents`, `rewardable_subtotal_cents`, `discount_cents`, `net_total_cents`, `shipping_fee_cents`, and the awarded-points previews — refreshes the order's `updated_at`, and increments the order's `version`. That version bump is exactly what the optimistic-concurrency rule on submission (§2.6) observes: any line change between a client's read and its submit invalidates the quoted version.

### 3.7. Order Economics: Pricing, Discounts, Shipping, and Points

The order's money fields are computed live while the order is `OPEN` and pinned at submission. The `subtotal_cents` is the sum, over all lines whose status is not `CANCELLED`, of each line's `qty` times its `unit_price_cents`. The `rewardable_subtotal_cents` is the same sum but restricted to lines whose `fair_overlap` is false and whose `donation_funded` is false — it is the earning base for reward points.

The tier discount is computed on the whole subtotal, never per line. Four tiers apply, each with an inclusive lower bound on the subtotal: below 5000 cents the discount rate is zero basis points; at or above 5000 cents the rate is 500 basis points (5.00%); at or above 15000 cents it is 1000 basis points (10.00%); and at or above 40000 cents it is 1500 basis points (15.00%). The applicable tier is the highest tier whose inclusive minimum the subtotal has reached. The `discount_cents` is the subtotal multiplied by the applicable tier's basis points, divided by 10000, and rounded once, half-up, to whole cents. Computing per-line discounts, rounding each, and summing is expressly forbidden — it produces different cents at tier boundaries. The `net_total_cents` charged to families is the `subtotal_cents` minus the `discount_cents`.

Shipping resolves to a flat 750 cents, with two independent waivers, each yielding a fee of zero. The school-level waiver applies whenever the school's `low_income_program` flag is true. The order-level waiver applies whenever the order's `rewardable_subtotal_cents` is at least 2500 cents — the boundary is inclusive, so a rewardable subtotal of exactly 2500 cents ships free. If neither waiver applies, `shipping_fee_cents` is the 750-cent flat fee.

Reward points are computed in a pinned three-step order. Step one derives base points from the earning base: the base is the `rewardable_subtotal_cents` divided by 100 cents per point and floored to an integer — 100 cents of rewardable spend earns one point. The earning base is the full rewardable subtotal; the tier discount never reduces it. Step two scans promotions: among promotions that are `ACTIVE`, whose `[starts_on, ends_on)` window contains the logical clock date, and whose `grade_band` is either null or equal to the ordering teacher's band, the `BONUS_POINTS` promotions contribute a single best multiplier — the highest `multiplier_bp`, with ties broken by the earliest promotion `created_at` and then by `name` in ascending order. The multiplier bonus is the base multiplied by the best multiplier's excess over 100 basis points, divided by 100, and floored: at double earn (200 basis points), the multiplier bonus equals the base itself. Independently, each `TITLE_INCENTIVE` promotion contributes its `bonus_points_per_unit` times the ordered quantity of its title across the order's qualifying lines — those not cancelled, not fair-overlapped, and not donation-funded — and multiple incentive promotions on the same title stack additively. Step three totals: `awarded_base_points` is the base; `awarded_bonus_points` is the multiplier bonus plus the summed title incentives; `awarded_total_points` is their sum. Evaluation order is pinned: base first, then promotions reading the already-computed base; the multiplier bonus never feeds back into the base.

Each line also carries its own `points_earned` attribution: the line's rewardable value (its `qty` times `unit_price_cents`, for qualifying lines) divided by 100 cents per point and floored, with the order-level remainder — the difference between the floored order base and the sum of floored line attributions — given to the earliest-created qualifying line, ties broken by `student_name` in ascending order. On `OPEN` orders the three awarded-points fields are a live preview, recomputed with every line mutation; at submission they pin and drive the award.

### 3.8. Submission, Cancellation, and the Shipping Sweep

Submission consolidates the class order and is the single most side-effect-rich operation in the system. A `Teacher` submits an `OPEN` order — any other starting `status` is rejected with `ERR_INVALID_STATE` — and must be the order's owning teacher, else `ERR_FORBIDDEN_OWNERSHIP`. The school's posture must be `NORMAL` (else `ERR_SCHOOL_RESTRICTED`), the cycle must be `PUBLISHED` (else `ERR_CYCLE_NOT_PUBLISHED`, HTTP 409), and at least one line must exist with a status other than `CANCELLED` (else `ERR_ORDER_EMPTY`, HTTP 422). The checks are evaluated in the order given here: posture first, then cycle-published, then ownership, then non-emptiness, then the version guard. The submission carries `expected_class_order_version` per §2.6.

A successful submission performs all of the following. The order's `status` moves from `OPEN` to `SUBMITTED`. The pinned `awarded_total_points` is credited to the teacher's `points_balance` and `points_earned_total`, a points-ledger `EARN` entry referencing the class order is appended, and the order's `points_status` moves from `UNAWARDED` to `AWARDED`. Royalty accrues at 90 cents per ordered unit on every ordered title, which may flip one or more licenses to `SUSPENDED` per §3.3. Then the backorder pass: every non-cancelled line whose title's license is now `SUSPENDED` moves from `ACTIVE` to `BACKORDERED`, and the order's `ship_status` is forced to remain `PENDING`; if zero non-cancelled lines are backordered after the pass, `ship_status` advances directly from `PENDING` to `SHIPPED`, otherwise it stays `PENDING`. The order's `version` increments by one.

Cancellation has two paths. From `OPEN`, a teacher who owns the order (or the school-suspension cascade of §3.1) cancels it: every line — `ACTIVE` or `BACKORDERED` — moves to `CANCELLED`, no points movement occurs because none were awarded (`points_status` stays `UNAWARDED`), no royalty had accrued, and the order's `version` increments. From `SUBMITTED`, cancellation additionally requires `ship_status` to be `PENDING` — once anything has shipped the order cannot be cancelled, and the attempt is rejected with `ERR_ORDER_HAS_SHIPPED` (HTTP 409). The shipped-state check is evaluated before ownership and before clawback solvency, so a non-owning teacher cancelling a shipped order surfaces `ERR_ORDER_HAS_SHIPPED`. The submitted-path cancel performs the full unwind: every non-cancelled line moves to `CANCELLED`; royalty accrual is reversed per §3.3, potentially flipping licenses back to `ACTIVE`; and the clawback runs — the original pinned `awarded_total_points` (never a recomputation, so later promotion expiries or price edits cannot change it) is subtracted from the teacher's `points_balance`, a points-ledger `CLAWBACK` entry is appended, and `points_status` moves from `AWARDED` to `CLAWED_BACK`. The teacher's `points_earned_total` is left unchanged — the clawback is tracked as a negative ledger entry and the balance is recomputed, not rewritten. Because the clawback may not drive the balance below zero, a teacher who has already redeemed part of the award may be insolvent for cancellation: if the teacher's `points_balance` is below the order's `awarded_total_points`, the cancel is rejected with `ERR_POINTS_BALANCE_NEGATIVE` (HTTP 422), and no state — lines, royalties, points, or statuses — is changed. From `CANCELLED`, nothing further is possible — the state is terminal and any further transition attempt is rejected with `ERR_ALREADY_TERMINAL`.

Shipping is an operational sweep, never a family-facing action, and it is the only way `ship_status` advances after submission. A `ClubAdmin` runs the shipping sweep, which considers every `SUBMITTED` order whose `ship_status` is `PENDING` or `PARTIAL`. Within each such order, every `BACKORDERED` line whose title's license is `ACTIVE` ships — its status returns from `BACKORDERED` to `ACTIVE` and it counts as shipped for that run — while lines whose titles remain `SUSPENDED` stay `BACKORDERED`. Each order's `ship_status` is then re-derived: from `PENDING` to `PARTIAL` when at least one line shipped and at least one remains backordered; from `PENDING` to `SHIPPED` when no lines remain backordered; from `PARTIAL` to `SHIPPED` when the remaining backordered lines all ship. Each touched order's `version` increments. The sweep returns a summary with `shipped_line_count` (lines shipped in the run) and `orders_touched` (orders whose shipment state advanced).

### 3.9. Book Fairs and Title Overlap

A school hosts book fairs, scheduled by a `SchoolAdmin` or `ClubAdmin` with the `school_id`, an inclusive `start_date`, and an exclusive `end_date` that must fall strictly after `start_date`. Scheduling requires the school's posture to be `NORMAL`, else `ERR_SCHOOL_RESTRICTED`. One school may never hold two non-cancelled fairs whose `[start_date, end_date)` windows intersect; the windows are half-open, so adjacency — one fair's `start_date` equal to another's `end_date` — is allowed, but any true intersection is rejected with `ERR_FAIR_OVERLAP` (HTTP 409); cancelled fairs impose no constraint. A fair begins `SCHEDULED`, turns `ACTIVE` when the logical clock enters its window, and `COMPLETED` when the clock reaches or passes `end_date` (a clock advance that jumps past the entire window moves the fair directly from `SCHEDULED` to `COMPLETED`); both transitions are fired by clock advancement, and each recomputes the hosting school's `active_fair_id` — the id of the fair whose window contains today's clock date, or null when none. The school's `active_fair_id` is derived on read: among the school's `ACTIVE` fairs whose windows contain the clock date, the earliest-created (ties broken by `id`) is reported, and any overlapping `SCHEDULED` fairs are not surfaced until they activate.

Each fair features titles. Adding a fair title — creating a row with the fair's `fair_id` fixed by the path and an input `title_id` — is subject to a catalog-wide overlap cap: a title whose `fair_count_used` has already reached the limit of 2 is rejected with `ERR_TITLE_OVERLAP_CAP` (HTTP 409); the boundary is inclusive, so the title is rejected at the limit, not above it. A fair's title list contains no duplicate titles: adding a title already featured at that fair is rejected with `ERR_INVALID_REQUEST`, checked before the overlap cap. Fair-title rows may be added to `SCHEDULED` or `ACTIVE` fairs alike; a `COMPLETED` or `CANCELLED` fair accepts none (the attempt is `ERR_ALREADY_TERMINAL`). Adding a fair title touches the hosting fair's `version` and recomputes `fair_overlap` across the school's `PUBLISHED` cycles; each offering whose recomputed flag changed increments its own `version`. The `fair_count_used` counter tracks, per title, how many flyer-offering rows across all `PUBLISHED` cycles currently carry `fair_overlap` true in connection with that title — incremented at cycle publication per §3.5, decremented at cycle close, and recomputed as fairs come and go.

The `fair_overlap` flag on an offering is true when the school has a fair in `SCHEDULED` or `ACTIVE` status whose window intersects the offering's cycle month and whose fair-title list includes the offered title. Order lines snapshot it at creation, and — the teeth of the rule — lines with `fair_overlap` true are excluded from reward-point earning via the `rewardable_subtotal_cents` definition in §3.7. The flag is recomputed on every offering in the school's `PUBLISHED` cycles whenever a fair is activated, whenever a title is added to a fair, and whenever a fair is cancelled. Fair cancellation is permitted from `SCHEDULED` or `ACTIVE`; in either case the cancelled fair drops out of every overlap computation (since only `SCHEDULED` and `ACTIVE` fairs count), which decrements `fair_count_used` for every featured title that had been counted, clears the school's `active_fair_id` when the cancelled fair was the active one, and recomputes `fair_overlap` on the affected published-cycle offerings. Cancelling a `COMPLETED` fair is rejected with `ERR_FAIR_NOT_CANCELLABLE` (HTTP 409), and both `COMPLETED` and `CANCELLED` are terminal.

### 3.10. Donation Requests and Sponsor Matching

Low-income schools can request donated books. A `Teacher` or `SchoolAdmin` creates a donation request with the `school_id`, the requesting `teacher_id`, the requested `title_id`, and a `qty_requested` of at least one copy. The school must carry `low_income_program` true, else the request is rejected with `ERR_NOT_LOW_INCOME` (HTTP 422), and the title's license must be `ACTIVE`, else `ERR_LICENSE_SUSPENDED`. The request begins `OPEN`, with `qty_matched` null until a match occurs.

A `Donor` matches an `OPEN` request. Matching requires the school's `low_income_program` to be true and its posture to be `NORMAL`, and the title's license to be `ACTIVE`. The match is all-or-nothing: `qty_matched` is set equal to `qty_requested`, the request moves from `OPEN` to `MATCHED`, and its `version` increments. Partial matches do not exist.

Fulfillment, performed by a `ClubAdmin` on a `MATCHED` request — a request still `OPEN` yields `ERR_DONATION_NOT_MATCHED` (HTTP 409), and a `FULFILLED` or `CANCELLED` request yields `ERR_ALREADY_TERMINAL` — requires the title's license still to be `ACTIVE` at fulfillment time and turns the match into a physical shipment. Fulfillment creates a class order on the school's currently `PUBLISHED` cycle for the requesting teacher, in `SUBMITTED` status with `ship_status` `PENDING` and `points_status` `UNAWARDED`, containing a single order line of `qty_matched` copies with `student_name` `"DONATION"`, `submitted_by` `TEACHER`, marked `donation_funded` true at `unit_price_cents` zero. If no `PUBLISHED` cycle exists for the school and the teacher's grade band, the system creates an ad-hoc `DRAFT` cycle keyed to the logical clock's current month, force-publishes it — bypassing the non-empty-offerings requirement — and attaches the donation order to it; either way, if the cycle has no existing offering for the requested title, the system creates one with `flyer_price_cents` zero so the donation line has an offering to reference. Donation-funded lines never earn points, both because they are excluded from the earning base and because their price is zero. Fulfillment then adds `qty_matched` to the teacher's `donated_books_received` and accrues royalty on the title for the matched units, which may flip the license to `SUSPENDED`. A request in `OPEN` may instead be cancelled by a `SchoolAdmin` or `ClubAdmin`, moving it to `CANCELLED` (a `MATCHED` request cannot be cancelled — the attempt is rejected with `ERR_INVALID_STATE`); both `FULFILLED` and `CANCELLED` are terminal.

### 3.11. Redeeming Points for Books and Supplies

Teachers spend points through redemptions. A `Teacher` creates a redemption with their `teacher_id`, a `kind` of `BOOK` or `SUPPLY`, and a `qty` of at least one unit; the redemption begins `PENDING`. The basket shapes the payload: a `BOOK` redemption requires a `title_id` naming the classroom book title (which must reference an existing title), while a `SUPPLY` redemption must not carry one — the wrong combination is rejected with `ERR_REDEMPTION_SHAPE_INVALID` (HTTP 422), checked after the body-referenced `teacher_id` and `qty` field-shape validations. The `points_cost` is computed at creation: for `BOOK`, the `qty` times the title's `points_cost`; for `SUPPLY`, the `qty` times a flat 200 points per unit. No points move at creation — the `PENDING` state is a hold in name only.

Confirming a `PENDING` redemption is done by the owning teacher (a mismatch is `ERR_FORBIDDEN_OWNERSHIP`) and is the moment points are spent. The school's posture must be `NORMAL`, else `ERR_SCHOOL_RESTRICTED`. The teacher's `points_balance` must be at least the redemption's `points_cost`, else the confirm is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 422). For `BOOK` redemptions the title's license must be `ACTIVE`, else `ERR_LICENSE_SUSPENDED`. On confirmation the teacher's `points_balance` decreases by `points_cost`, `points_redeemed_total` increases by `points_cost`, a points-ledger `REDEEM` entry referencing the redemption is appended, and a `BOOK` redemption additionally accrues royalty on the title for the redeemed units at 90 cents per unit, which may flip the license to `SUSPENDED` per §3.3. A `PENDING` redemption may instead be cancelled by its owning teacher, which moves it to `CANCELLED` with no points movement whatsoever; a `CONFIRMED` redemption cannot be cancelled — the attempt is rejected with `ERR_INVALID_STATE`. `CONFIRMED` redemptions are final — no transition leaves the state — and `CANCELLED` is terminal.

### 3.12. The Monthly Ops Run and Points Expiry

Reward points do not live forever. A `ClubAdmin` runs the monthly ops epoch, which sweeps expired points across every teacher (in `created_at`, then `id`, order) and then re-fires the clock transitions — recomputing each school's `active_fair_id` and expiring promotions whose `ends_on` is on or before the clock date, exactly as a clock advance would.

The expiry sweep works per teacher over that teacher's points ledger. Entries are considered in chronological order of their `created_at`, earliest first, with ties broken by ledger `created_at` and then by `note` in ascending order. Points from `EARN` entries whose ledger entry is at least 12 calendar months older than the logical clock date — the entry's date plus twelve calendar months, clamped to the month's last day when needed, is on or before the clock date — and which have not yet been consumed by `REDEEM`, prior `EXPIRE`, or `CLAWBACK` entries expire. Consumption matching is first-in-first-out against the same chronological order: redemptions and clawbacks always consume the oldest unconsumed earned points first. For each teacher with points to expire, the expired points are aggregated into a single `EXPIRE` ledger entry referencing the ops run, the teacher's `points_expired_total` increases by the expired amount, and `points_balance` decreases by the same amount (with the teacher's `version` incrementing once), preserving the invariant that the balance equals earned minus redeemed minus expired. The run returns a summary with `expired_total_points` (points expired across all teachers) and `teachers_affected` (teachers whose balance changed).

## 4. Endpoint Definitions

All endpoints are mounted under `/club`. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource, perform an action, or read data respond with HTTP 200. Request payloads, response shapes, and side effects are specified in §2 and §3; this table is a summary index only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /club/schools | Register a school | ClubAdmin |
| GET | /club/schools | List schools | ClubAdmin, SchoolAdmin, Teacher, Parent, Donor |
| GET | /club/schools/{id} | Get one school (posture, active_fair_id derived) | ClubAdmin, SchoolAdmin, Teacher, Parent, Donor |
| GET | /club/schools/{id}/teachers | Teachers of a school | ClubAdmin, SchoolAdmin |
| GET | /club/schools/{id}/flyer-cycles | Flyer cycles of a school | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/schools/{id}/book-fairs | Book fairs of a school | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/schools/{id}/donation-requests | Donation requests of a school | ClubAdmin, SchoolAdmin, Donor |
| GET | /club/schools/{id}/enrollments | Program enrollments of a school | ClubAdmin, SchoolAdmin |
| POST | /club/schools/{id}/enroll-program | Create an ACTIVE program enrollment for the school | ClubAdmin |
| POST | /club/schools/{id}/suspend-program | Suspend the ACTIVE enrollment; posture flips; OPEN class orders cascade-cancel | ClubAdmin |
| POST | /club/schools/{id}/reinstate-program | Reinstate the enrollment; posture returns to NORMAL | ClubAdmin |
| POST | /club/teachers | Register a teacher at a school | ClubAdmin, SchoolAdmin |
| GET | /club/teachers | List teachers | ClubAdmin, SchoolAdmin |
| GET | /club/teachers/{id} | Get one teacher including points balances | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/teachers/{id}/points-ledger | Points ledger entries for a teacher | ClubAdmin, Teacher |
| GET | /club/teachers/{id}/class-orders | Class orders of a teacher | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/teachers/{id}/redemptions | Redemptions of a teacher | ClubAdmin, Teacher |
| GET | /club/teachers/{id}/donation-requests | Donation requests of a teacher | ClubAdmin, SchoolAdmin, Teacher, Donor |
| POST | /club/titles | Acquire a title (initial licensing) | ClubAdmin |
| POST | /club/titles/{id}/acquire | Renegotiate the royalty cap (OCC-guarded) | ClubAdmin |
| GET | /club/titles | List titles | ClubAdmin, SchoolAdmin, Teacher, Parent, Donor |
| GET | /club/titles/{id} | Get one title | ClubAdmin, SchoolAdmin, Teacher, Parent, Donor |
| GET | /club/titles/{id}/promotions | Promotions referencing a title | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/titles/{id}/offerings | Flyer offerings referencing a title | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/titles/{id}/fair-titles | Fair-title rows referencing a title | ClubAdmin, SchoolAdmin |
| GET | /club/titles/{id}/donation-requests | Donation requests referencing a title | ClubAdmin, SchoolAdmin, Donor |
| GET | /club/titles/{id}/redemptions | Redemptions referencing a title | ClubAdmin |
| GET | /club/flyer-cycles/{id}/class-orders | Class orders on a cycle | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/offerings/{id}/lines | Order lines referencing an offering | ClubAdmin, SchoolAdmin, Teacher |
| POST | /club/promotions | Create a promotion | ClubAdmin |
| GET | /club/promotions | List promotions | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/promotions/{id} | Get one promotion | ClubAdmin, SchoolAdmin, Teacher |
| POST | /club/flyer-cycles | Create a DRAFT monthly flyer cycle | ClubAdmin |
| GET | /club/flyer-cycles/{id} | Get one cycle | ClubAdmin, SchoolAdmin, Teacher, Parent |
| POST | /club/flyer-cycles/{id}/offerings | Add a title offering to a DRAFT cycle; pins flyer price | ClubAdmin |
| GET | /club/flyer-cycles/{id}/offerings | List offerings of a cycle | ClubAdmin, SchoolAdmin, Teacher, Parent |
| GET | /club/offerings/{id} | Get one offering | ClubAdmin, SchoolAdmin, Teacher, Parent |
| POST | /club/flyer-cycles/{id}/publish | Publish a DRAFT cycle | ClubAdmin |
| POST | /club/flyer-cycles/{id}/close | Close a cycle | ClubAdmin |
| POST | /club/class-orders | Open a class order on a PUBLISHED cycle | Teacher |
| GET | /club/class-orders/{id} | Get one class order with computed aggregates | ClubAdmin, SchoolAdmin, Teacher, Parent |
| GET | /club/class-orders/{id}/lines | List lines of an order | ClubAdmin, SchoolAdmin, Teacher, Parent |
| POST | /club/class-orders/{id}/lines | Add an order line to an OPEN order | Teacher, Parent |
| PATCH | /club/order-lines/{id} | Change quantity on a line of an OPEN order | Teacher, Parent |
| DELETE | /club/order-lines/{id} | Cancel a line on an OPEN order | Teacher, Parent |
| POST | /club/class-orders/{id}/submit | Submit the consolidated class order (OCC-guarded) | Teacher |
| POST | /club/class-orders/{id}/cancel | Cancel an OPEN or SUBMITTED (unshipped) order | Teacher |
| POST | /club/book-fairs | Schedule a book fair at a school | SchoolAdmin, ClubAdmin |
| GET | /club/book-fairs/{id} | Get one fair | ClubAdmin, SchoolAdmin, Teacher |
| GET | /club/book-fairs/{id}/titles | List fair titles | ClubAdmin, SchoolAdmin, Teacher |
| POST | /club/book-fairs/{id}/titles | Add a title to the fair | SchoolAdmin, ClubAdmin |
| POST | /club/book-fairs/{id}/cancel | Cancel a SCHEDULED or ACTIVE fair | SchoolAdmin, ClubAdmin |
| POST | /club/donation-requests | Create a donation request | Teacher, SchoolAdmin |
| GET | /club/donation-requests/{id} | Get one donation request | ClubAdmin, SchoolAdmin, Teacher, Donor |
| POST | /club/donation-requests/{id}/match | Donor matches the full requested quantity | Donor |
| POST | /club/donation-requests/{id}/fulfill | Fulfill a matched request into a donation-funded shipment | ClubAdmin |
| POST | /club/donation-requests/{id}/cancel | Cancel an OPEN donation request | SchoolAdmin, ClubAdmin |
| POST | /club/redemptions | Create a PENDING redemption | Teacher |
| GET | /club/redemptions/{id} | Get one redemption | ClubAdmin, Teacher |
| POST | /club/redemptions/{id}/confirm | Confirm a PENDING redemption; debits points | Teacher |
| POST | /club/redemptions/{id}/cancel | Cancel a PENDING redemption | Teacher |
| POST | /club/_clock/set_current_utc | Set the logical clock; fires scheduled transitions | ClubAdmin |
| POST | /club/_ops/run-ops | Run the monthly ops epoch (points expiry sweep) | ClubAdmin |
| POST | /club/_ops/run-shipping | Run the shipping sweep over SUBMITTED orders | ClubAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this table is a summary index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_SCHOOL_RESTRICTED | 409 |
| ERR_LICENSE_SUSPENDED | 409 |
| ERR_ROYALTY_CAP_INVALID | 422 |
| ERR_GRADE_BAND_MISMATCH | 422 |
| ERR_FORMAT_NOT_ALLOWED | 422 |
| ERR_CYCLE_ALREADY_PUBLISHED | 409 |
| ERR_EMPTY_CYCLE | 422 |
| ERR_FAIR_OVERLAP | 409 |
| ERR_TITLE_OVERLAP_CAP | 409 |
| ERR_PROMO_WINDOW_INVALID | 422 |
| ERR_PROMO_SHAPE_INVALID | 422 |
| ERR_INSUFFICIENT_POINTS | 422 |
| ERR_POINTS_BALANCE_NEGATIVE | 422 |
| ERR_NOT_LOW_INCOME | 422 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_ORDER_NOT_OPEN | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_ORDER_HAS_SHIPPED | 409 |
| ERR_ORDER_EMPTY | 422 |
| ERR_CYCLE_NOT_PUBLISHED | 409 |
| ERR_DONATION_NOT_MATCHED | 409 |
| ERR_FAIR_NOT_CANCELLABLE | 409 |
| ERR_REDEMPTION_SHAPE_INVALID | 422 |
| ERR_ENROLLMENT_EXISTS | 409 |

