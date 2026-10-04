# Specialty Glass Co-Development & Capacity Commitment API — Product Requirements Document

## 1. Introduction

Specialty glass for consumer devices, vehicles, pharmaceutical packaging, and architecture is not a catalog product; it is co-developed. A device maker arrives with an industrial design, and the glass manufacturer tunes a composition and its strengthening process to that design under a confidentiality agreement, runs customer reliability qualification cycles against a design-freeze deadline, and only then locks the formulation. This document specifies the API that manages that entire co-development pipeline — from the first executed NDA through composition tuning, qualification attempts, and design freeze — together with the commercial machinery that funds the manufacturing capacity behind it.

Capacity is the scarce resource. Building a new melting tank is a multi-year capital decision that the manufacturer will not make on spec: a customer must post a volume commitment, backed by a prepayment, before construction begins. Once built, a tank runs melting campaigns that span years, changeovers between compositions are costly and effectively irreversible while a campaign is running, and yield on a new composition improves along a learning curve that the cost model must reflect. Commitments, allocations of campaign output, breach watching on under-covered commitments, and the three-bucket prepayment ledger are all first-class concerns of this system.

On top of the qualified platform sits a brand-licensing business: device makers license the platform for their primary market and for secondary applications in adjacent markets, submit marketing materials for legal review, and report channel-split usage for royalty settlement. Because the platform's value is its intellectual property, the system also carries a reverse-engineering monitoring posture per device maker, with a confirmed-infringement cascade that suspends licenses and holds unsettled royalty reports. All of this is exposed under the `/glass` mount to six segregated roles, against a controllable logical clock rather than the wall clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. A request that is missing either header, or whose `X-User-Role` value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system declares exactly six roles, spelled as follows: `PlatformAdmin`, `ProgramManager`, `CapacityPlanner`, `FinanceController`, `LegalCounsel`, and `DeviceMaker`.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform operator registers device makers and drives the logical clock. The same opaque form applies to `ProgramManager` (who owns programs, compositions, qualification submissions, and commitment proposals and releases), to `CapacityPlanner` (who owns tanks, campaigns, production records, the allocation waterfall, and commitment countersignature), to `FinanceController` (who confirms prepayments, applies prepayment to invoices, and adjudicates royalty reports), and to `LegalCounsel` (who owns licenses, marketing review, and IP monitoring). For these five roles the server may record `X-User-ID` — for example, as `countersigned_by` on a Commitment when a `CapacityPlanner` countersigns — but it does not compare the header to any entity's `id`.

When `X-User-Role` is `DeviceMaker`, `X-User-ID` is the `id` of the acting DeviceMaker entity; ownership checks on any resource that references a DeviceMaker compare the resource's foreign-key field to `X-User-ID`. Signing a commitment, beginning or recording a qualification test, submitting marketing materials, and creating a usage report are all ownership-checked writes: if the header does not equal the owning maker's `id`, the request fails with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. List results are sorted by `created_at` ascending unless otherwise stated.

### 2.4. The Logical Clock

The system runs on a logical clock, never on wall-clock time. Before any call to the clock-setting capability, the logical clock reads exactly 2026-09-01T00:00:00Z (CONST.DEFAULT_CLOCK_ISO), and the server must not fall back to wall-clock time if the clock has never been set. The logical clock is read by every time-dependent rule in this document: campaign start and completion windows, tank construction readiness, design-freeze deadlines, license term boundaries, report periods, and breach deadlines all compare against it.

The clock advances in exactly one way: a `PlatformAdmin` invokes the admin-only clock-setting capability, supplying the target instant as `to_iso8601` in ISO 8601 UTC; the response body carries the new reading as `current_utc`. There is no other operation that moves the clock. Time-driven state changes do not fire spontaneously when the clock moves: they are applied only when an authorized operator runs the operations checkpoint sweep described in §3.9, which reads the logical clock and applies every due transition in one pass.

### 2.5. Common Resource Properties and Addressing

Every entity in this API — DeviceMaker, Program, Composition, QualCycle, Tank, Campaign, Commitment, Allocation, License, and UsageReport — carries the same four system-managed properties in addition to its own fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the entity, including mutations caused by a cascade; and `version`, an integer that increments by exactly 1 on every mutation of the entity, again including cascade-driven mutations.

Resources are addressed by path parameters that name the entity being acted on: `deviceMakerId`, `programId`, `compositionId`, `qualCycleId`, `tankId`, `campaignId`, `commitmentId`, `allocationId`, `licenseId`, and `usageReportId`. Path identifiers and foreign-key references carried in request bodies are validated left to right: the first identifier that does not resolve to an existing entity is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on their parent entity's `version`; no other endpoint accepts a version field.

Creating a capacity commitment requires the request to carry `expected_program_version`, the client-provided value of the target Program's `version` as last observed by the client. If the Program's current `version` does not equal `expected_program_version` — because another writer has advanced it since the client last read the program — the creation is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), and the client must re-observe the program before proposing.

Creating an allocation requires the request to carry `expected_commitment_version`, the client-provided value of the target Commitment's `version` as last observed by the client. If the Commitment's current `version` does not match, the creation is rejected with `ERR_STALE_COMMITMENT_VERSION` (HTTP 412), and the client must re-observe the commitment before allocating.

### 2.7. Money, Units, and Rounding Discipline

All monetary amounts in this API are integer numbers of cents; no fractional cents ever appear on the wire. Unit counts are integers. Three rounding modes are used, each pinned to its site: **floor** for computed unit counts (expected good units, prepayment credit units, effective commitment units), **ceiling** for cost components (each campaign unit-cost component is ceilinged to integer cents separately, and the ceilinged components are then summed), and **round half up** wherever a rate is applied to a revenue base or a ratio is stored (per-line and final royalty amounts, realized yield to six decimal places, supply coverage and effective coverage to four decimal places). Every calculation in §3 states its mode, precision, and operand order at its own site.

### 2.8. Validation Order

When a request fails several checks, the failure reported is the one with the highest priority: checks are evaluated in the fixed order below and the first failure wins. The enumeration is normative; later checks never mask earlier ones.

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is a declared role; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role is listed for the endpoint; otherwise `ERR_FORBIDDEN_ROLE`.
3. **Request shape.** Required fields are present, types and enum members are valid, `complexity_multiplier` lies within the inclusive range 1.0 to 2.5, a usage report's `period_start` is strictly before its `period_end`, the `lines` array is non-empty, a license term spans at least the minimum term, an apply-prepayment `amount_cents` is strictly positive, and a qualification's `design_freeze_date` lies strictly in the future; any violation yields `ERR_INVALID_REQUEST`.
4. **Existence.** Path ids and body foreign-key references resolve to existing entities, validated left to right; otherwise `ERR_NOT_FOUND`.
5. **Ownership.** For `DeviceMaker`-role writes — signing a commitment, beginning or recording a qualification test, submitting marketing materials, creating a usage report — `X-User-ID` equals the owning maker's `id`; otherwise `ERR_OWNERSHIP_MISMATCH`.
6. **State legality.** The target entity is in a state from which the requested transition is defined. This covers retiring a `LOCKED` composition, acting on `TERMINATED` or `CLOSED` programs, starting a campaign at or after its `end_date`, and every other off-transition attempt, and it also covers the creation-time state gates on referenced entities: creating an allocation requires its commitment to be `SECURED` or `BREACH_WATCH` and its campaign to be `SCHEDULED` or `RUNNING`, and creating a usage report requires its license to be `ACTIVE` or `SUSPENDED`. Violations yield `ERR_INVALID_STATE`.
7. **Optimistic concurrency.** `expected_program_version` on commitment creation equals the Program's current `version` (`ERR_STALE_PROGRAM_VERSION`), and `expected_commitment_version` on allocation creation equals the Commitment's current `version` (`ERR_STALE_COMMITMENT_VERSION`); the two share this priority.
8. **Confidentiality.** The program must be past `DRAFT` — its NDA executed — before any composition, commitment, or license is created against it; otherwise `ERR_NDA_REQUIRED`.
9. **IP litigation hold.** The referenced device maker must not be in `CONFIRMED_INFRINGEMENT`; this blocks license activation and reinstatement, allocation creation, and usage-report creation with `ERR_IP_LITIGATION_HOLD`.
10. **Segregation of duties.** The caller confirming prepayment must differ from the commitment's `countersigned_by`; otherwise `ERR_SEGREGATION_OF_DUTIES`.
11. **Design freeze deadline.** Freezing a design is allowed only at or before `design_freeze_date`; a later attempt yields `ERR_DESIGN_FREEZE_PASSED`.
12. **Campaign window.** A new campaign's `end_date` must be strictly after its `start_date`, and the window length in days must be at least the minimum campaign length and at most the maximum campaign length; otherwise `ERR_INVALID_CAMPAIGN_WINDOW`.
13. **Tank schedule.** On the same tank, the new half-open window must not overlap any existing non-terminal campaign window, and versus every existing campaign on that tank carrying a different `composition_id` the gap between the adjoining window edges must be at least the changeover gap; same-composition adjacency needs a gap of zero. Violations yield `ERR_TANK_SCHEDULE_CONFLICT`.
14. **Clock-gated transitions.** Campaign start requires the logical clock to have reached `start_date` (`ERR_CAMPAIGN_NOT_STARTED`); campaign completion requires it to have reached `end_date` (`ERR_CAMPAIGN_NOT_ENDED`); tank commissioning requires it to have reached `construction_ready_date` (`ERR_TANK_UNDER_CONSTRUCTION`). These three share this priority.
15. **License term.** Activation and reinstatement require the logical clock inside the closed interval from `effective_date` through `expiry_date` (`ERR_LICENSE_TERM_INVALID`), and no closed-interval term overlap with another `ACTIVE` license of the same maker and market (`ERR_LICENSE_TERM_OVERLAP`); the two share this priority.
16. **Report period.** A new usage report's period must not overlap an existing report of the same license in `SUBMITTED` or `ACCEPTED`; otherwise `ERR_REPORT_PERIOD_OVERLAP`. Overlap with `DISPUTED` or `HELD` reports is permitted as supersession.
17. **Composition maturity.** Campaign creation requires the referenced composition to be `TUNED`, `QUALIFIED`, or `LOCKED`, and campaign start requires `QUALIFIED` or `LOCKED`; otherwise `ERR_COMPOSITION_NOT_QUALIFIED`. A referenced tank still `CONSTRUCTING` fails at this same priority with `ERR_TANK_UNDER_CONSTRUCTION`.
18. **Program frozen for licensing.** License activation requires the program to be `DESIGN_FROZEN` (`ERR_PROGRAM_NOT_FROZEN`); a secondary-market license additionally requires a `LOCKED` base composition in the program (`ERR_BASE_PLATFORM_NOT_QUALIFIED`). The two share this priority.
19. **Program alignment.** An allocation's campaign and commitment must belong to the same program — the campaign's composition's program must equal the commitment's program; otherwise `ERR_PROGRAM_MISMATCH`.
20. **Secured funding.** Tank creation requires the referenced commitment to be `SECURED`; otherwise `ERR_COMMITMENT_NOT_SECURED`.
21. **Business constraints.** Resubmitting a qualification cycle is allowed only while `attempt_number` is below the attempt cap (`ERR_MAX_QUAL_ATTEMPTS`); allocation `units`, campaign `planned_units`, and a production record's combined good plus scrap units must be strictly positive, with zero rejected (`ERR_NONPOSITIVE_UNITS`); a commitment may fund at most one tank (`ERR_TANK_ALREADY_EXISTS`); a `composition_code` must be unique within its program (`ERR_COMPOSITION_CODE_CONFLICT`); a campaign's `planned_units` must not exceed the tank's daily capacity multiplied by the window length in days (`ERR_CAMPAIGN_OVER_CAPACITY`); and freezing a design requires at least one `QUALIFIED` or `LOCKED` composition in the program (`ERR_NO_QUALIFIED_COMPOSITION`).
22. **Fiscal rules, evaluated last.** A commitment's `prepayment_cents` must be at least the minimum prepayment (`ERR_PREPAYMENT_INSUFFICIENT`); prepayment confirmation requires the coverage gate to pass (`ERR_COMMITMENT_COVERAGE_INSUFFICIENT`); an allocation's `units` must not exceed the commitment's remaining need (`ERR_COMMITMENT_UNITS_EXCEEDED`) nor the campaign's `unallocated_units` (`ERR_INSUFFICIENT_CAMPAIGN_HEADROOM`), with remaining-need checked before headroom; an apply-prepayment amount must not exceed `prepayment_remaining_cents` (`ERR_PREPAYMENT_OVERAPPLY`); and accepting a usage report requires the license's marketing to be `APPROVED` (`ERR_MARKETING_NOT_APPROVED`). Within this row the checks fire in the order just listed when several fail.

### 2.9. State Machines, Cascades, and Consistency Discipline

Every lifecycle-bearing entity in this API follows the state machine defined for it in §3. A request whose trigger has no defined transition from the entity's current state is rejected with `ERR_INVALID_STATE` (HTTP 409); the machine definitions are exhaustive, and states not listed as a transition's source never produce that transition.

Several transitions produce **cascades** — ordered, multi-hop side effects that cross entity boundaries. Cascades execute their hops in the stated order: a first hop may cancel campaigns, a second hop may release the reservations those campaigns held, a third hop may recompute coverage on the affected commitments and drop them into breach watch, and a fourth hop may demote the standing of the makers behind them. Every entity mutated by any hop of a cascade has its `version` incremented and its `updated_at` refreshed, exactly as if it had been mutated directly. Two integrity notes deserve emphasis up front: a `LOCKED` composition is immutable and can never be retired, and a cascade that cancels `SCHEDULED` campaigns never touches `RUNNING` ones — molten glass cannot be un-run.

## 3. Business Logic & Workflows

### 3.1. Device Maker Onboarding, Commercial Standing, and IP Monitoring

A relationship begins when a `PlatformAdmin` registers a device maker, supplying the maker's legal `name` and headquarters `region` code. The maker's commercial standing, `standing_tier`, is one of `STANDARD`, `STRATEGIC`, or `PROBATION`; when omitted at registration it defaults to `STANDARD`. Standing is never auto-restored: the breach-watch cascade described in §3.4 and §3.6 demotes a maker one step — `STRATEGIC` down to `STANDARD`, `STANDARD` down to `PROBATION`, and `PROBATION` remaining `PROBATION` — and only deliberate commercial action outside this API could restore it. The roster can be listed with optional `standing_tier` and `ip_review_status` filters.

Intellectual-property monitoring lives on the maker, not on any license: every maker carries an `ip_review_status`, which is `CLEAR` at registration and moves under `LegalCounsel` control through the IP-review action, whose request carries the target state as `to_status`. The machine is small but consequential: from `CLEAR` a review may open (`UNDER_REVIEW`); from `UNDER_REVIEW` counsel either confirms infringement (`CONFIRMED_INFRINGEMENT`) or clears the maker (`CLEARED`); and from `CONFIRMED_INFRINGEMENT` a later review may return the maker to `CLEARED`. There are no terminal states in this machine.

Confirming infringement is the single most destructive non-administrative act in the system, and its cascade runs in two hops. Hop one: every License whose `device_maker_id` is this maker and whose `license_status` is `ACTIVE` transitions to `SUSPENDED`, with `suspension_reason` set to `IP_REVIEW`. Hop two: for each license suspended in hop one, every UsageReport of that license still in `SUBMITTED` transitions to `HELD`. A later clearing — `CONFIRMED_INFRINGEMENT` back to `CLEARED` — performs no automatic license reinstatement; suspended licenses stay `SUSPENDED` until counsel manually reinstates them one by one.

While a maker sits in `CONFIRMED_INFRINGEMENT`, four operations are blocked with `ERR_IP_LITIGATION_HOLD`: activating a license for that maker, reinstating one, creating an allocation whose commitment belongs to that maker, and submitting a usage report against that maker's license. The block is on the maker's posture, independent of any license's own state.

### 3.2. Co-Development Program Lifecycle

A `ProgramManager` opens a co-development program by naming the customer (`device_maker_id`), the confidential program code `name`, and the `primary_market` the device targets — one of `CONSUMER_ELECTRONICS`, `AUTOMOTIVE`, `PHARMA_PACKAGING`, or `ARCHITECTURAL`. The `confidentiality_tier` may be supplied as `STANDARD_CONFIDENTIAL` or `HIGH_CONFIDENTIAL` and defaults to `STANDARD_CONFIDENTIAL`. A new program starts in `DRAFT`. Programs may be listed filtered by `device_maker_id` and lifecycle `status`.

Confidentiality precedes everything. Executing the NDA moves a program from `DRAFT` to `NDA_EXECUTED` and stores the payload's `nda_reference` on the program, where it remains visible thereafter; the Program's `version` increments. Until that has happened, no composition, commitment, or license may be created against the program — the attempt fails with `ERR_NDA_REQUIRED`.

The moment the program's first composition is created, the system itself advances the program from `NDA_EXECUTED` to `COMPOSITION_TUNING`, incrementing the Program's `version`; there is no manual transition for this step. When the composition work is stable enough to schedule reliability testing, the program manager begins qualification, moving the program from `COMPOSITION_TUNING` to `QUALIFICATION`. That request carries `design_freeze_date`, which must lie strictly after the current logical clock time — a deadline at or before the present is rejected with `ERR_INVALID_REQUEST` — and the accepted deadline is stored on the program, again incrementing its `version`. If tuning must resume, a rework action returns the program from `QUALIFICATION` to `COMPOSITION_TUNING` and clears `design_freeze_date` to null.

Freezing the design is allowed only while the program is in `QUALIFICATION`, only while the logical clock is at or before `design_freeze_date` — the boundary instant itself is allowed, and a later attempt fails with `ERR_DESIGN_FREEZE_PASSED` — and only when at least one of the program's compositions has reached `QUALIFIED` or `LOCKED`, failing with `ERR_NO_QUALIFIED_COMPOSITION` otherwise. A successful freeze moves the program to `DESIGN_FROZEN` and increments its `version`.

A frozen program is closed by the program manager once nothing is in flight: closing requires that no campaign over the program's compositions is `SCHEDULED` or `RUNNING`, and that none of the program's commitments is in `PROPOSED`, `SIGNED`, `COUNTERSIGNED`, `SECURED`, or `BREACH_WATCH`. A program that meets those conditions moves from `DESIGN_FROZEN` to `CLOSED`, terminal, with its `version` incremented.

Termination harsher: from any of `DRAFT`, `NDA_EXECUTED`, `COMPOSITION_TUNING`, `QUALIFICATION`, or `DESIGN_FROZEN`, the program manager may terminate the program — optionally recording a `reason` — moving it to `TERMINATED`, also terminal. Termination cascades. Hop one releases every commitment of the program in `PROPOSED`, `SIGNED`, `COUNTERSIGNED`, `SECURED`, or `BREACH_WATCH`: each such commitment moves to `RELEASED`, its `prepayment_refunded_cents` is increased by its `prepayment_remaining_cents`, and its `prepayment_remaining_cents` is then set to zero. The same hop cancels every `SCHEDULED` campaign over the program's compositions. Hop two releases every `RESERVED` allocation held by those cancelled campaigns. Commitments released by hop one do not pass through `BREACH_WATCH` on the way out, and no breach recomputation applies to them; none of the program's commitments remain `SECURED` once hop one completes, so there is nothing left to recompute.

### 3.3. Glass Compositions and Qualification Cycles

Compositions are the lab's unit of work. A `ProgramManager` creates one under a program by supplying the `program_id`, a lab `composition_code`, and a `complexity_multiplier` expressing melting difficulty — a number from 1.0 to 2.5 inclusive; anything outside that range fails with `ERR_INVALID_REQUEST`. The `composition_code` must be unique within its program; a duplicate is rejected with `ERR_COMPOSITION_CODE_CONFLICT`. A new composition starts `EXPERIMENTAL`, and if it is the program's first, the program advances to `COMPOSITION_TUNING` as described in §3.2. Compositions may be listed filtered by `program_id` and `status`.

A composition matures through customer reliability testing. The program manager submits a composition for a qualification cycle with a `composition_id` and the customer's reliability `test_plan_ref`; the new QualCycle starts `SUBMITTED` with `attempt_number` set to 1. From there the customer drives: beginning testing — a `DeviceMaker` write, ownership-checked so that `X-User-ID` must equal the program's maker — moves the cycle from `SUBMITTED` to `IN_TESTING`, and if the referenced composition is still `EXPERIMENTAL` this first contact with the test bench tunes it, moving the composition from `EXPERIMENTAL` to `TUNED`. Recording the result, again ownership-checked, carries an `outcome` of `PASSED` or `FAILED` and moves the cycle from `IN_TESTING` to the matching state; either way `result_recorded_at` is stamped with the current logical clock time. A `PASSED` outcome on a `TUNED` composition qualifies it, moving the composition from `TUNED` to `QUALIFIED`. Qualification cycles may be listed filtered by `composition_id` and `status`.

Failure is recoverable up to a hard cap. A `FAILED` cycle may be resubmitted by the program manager, returning it from `FAILED` to `SUBMITTED` and incrementing `attempt_number` by 1 — but only while `attempt_number` is below 3 (CONST.MAX_QUAL_ATTEMPTS); attempting a resubmit at the cap fails with `ERR_MAX_QUAL_ATTEMPTS`. `PASSED` is the cycle machine's only terminal state; a failed cycle at the cap simply has no legal successor.

Qualification is not the end of maturity. The program manager may lock a `QUALIFIED` composition, moving it from `QUALIFIED` to `LOCKED`; a locked composition is immutable. Locking matters commercially: as §3.7 explains, a license for a market outside the program's `primary_market` cannot activate unless the program holds at least one `LOCKED` composition — `QUALIFIED` alone is insufficient for adjacent-market certification.

Retirement runs the other way. The program manager may retire a composition from `EXPERIMENTAL`, `TUNED`, or `QUALIFIED`, moving it to `RETIRED`, terminal. A `LOCKED` composition can never be retired — the attempt fails with `ERR_INVALID_STATE`. Retiring cascades in four hops. Hop one: every `SCHEDULED` campaign over this composition is `CANCELLED`; `RUNNING` campaigns are untouched, because molten glass cannot be un-run. Hop two: every `RESERVED` allocation held by those cancelled campaigns transitions to `RELEASED`, and each affected campaign's `unallocated_units` is increased by the released units. Hop three: for each commitment referenced by an allocation released in hop two that is still `SECURED`, its `supply_coverage` is recomputed, and if it has fallen below 1.0 (CONST.SUPPLY_COVERAGE_MIN) the commitment moves from `SECURED` to `BREACH_WATCH` with a `breach_deadline` set to the current logical clock plus 90 days (CONST.BREACH_GRACE_DAYS). Hop four: for each commitment that entered `BREACH_WATCH` in hop three, its device maker's `standing_tier` is demoted one step, per the demotion ladder in §3.1.

### 3.4. Capacity Commitments, Coverage Tiers, and the Prepayment Ledger

No tank is built on spec. Before construction, the customer must post a capacity commitment: a `ProgramManager` creates one against a program, carrying `program_id`, the volume the customer commits to take (`committed_units`, strictly positive), the capacity ask used as the coverage denominator (`required_units`, strictly positive), the prepayment backing the investment (`prepayment_cents`, at least 1000000 cents — CONST.MIN_PREPAYMENT_CENTS — with exactly the minimum allowed; a smaller amount fails with `ERR_PREPAYMENT_INSUFFICIENT`), and the OCC guard `expected_program_version` described in §2.6. Creation copies the program's `device_maker_id` onto the commitment, initializes `prepayment_remaining_cents` to the full `prepayment_cents` with `prepayment_applied_cents` and `prepayment_refunded_cents` at zero, starts the commitment in `PROPOSED`, and increments the Program's `version` by 1.

Two commercial semantics deserve emphasis. First, multiple active commitments per program are allowed — customers commit in tranches — and the only uniqueness the system enforces is over `PROPOSED`: creating a new commitment legitimately supersedes any existing `PROPOSED` commitment on the same program, releasing each superseded proposal exactly as the release cascade below describes, and it is precisely because creation supersedes that the OCC guard exists — a client holding a stale program view must re-observe before proposing. Second, the prepayment is a three-bucket ledger, not a balance: cents sit in `prepayment_remaining_cents` until finance applies them to invoices, moving them into `prepayment_applied_cents`, or until release refunds them into `prepayment_refunded_cents`. The three buckets never mix in the other direction. Commitments may be listed filtered by `program_id`, `device_maker_id`, and `status`.

Signature is a three-party handshake with segregated duties. The customer signs first: a `DeviceMaker` whose `X-User-ID` equals the commitment's `device_maker_id` moves it from `PROPOSED` to `SIGNED`, stamping `signed_at` with the current logical clock time; anyone else attempting the signature fails with `ERR_OWNERSHIP_MISMATCH`. A `CapacityPlanner` then countersigns, moving the commitment from `SIGNED` to `COUNTERSIGNED` and recording the planner's `X-User-ID` in `countersigned_by`. Finally a `FinanceController` confirms prepayment receipt, moving the commitment from `COUNTERSIGNED` to `SECURED` — but the confirming controller must not be the person who countersigned: if `X-User-ID` equals `countersigned_by`, the confirmation fails with `ERR_SEGREGATION_OF_DUTIES`.

Confirmation is gated on the coverage calculation, whose evaluation order is pinned so that later steps never feed back into earlier ones. Step one: the prepayment buys credit units — `prepayment_cents` divided by 1000 cents per unit (CONST.PREPAYMENT_UNIT_CREDIT_CENTS), floored to a whole unit. Step two: base units are the sum of `committed_units` and those credit units. Step three: base coverage is base units divided by `required_units`, carried unrounded into all comparisons. Step four: the coverage tier derives from pre-bonus base coverage only — `TIER_A` when base coverage is at least 1.2 (CONST.TIER_A_COVERAGE_MIN), otherwise `TIER_B` when it is at least 1.0 (CONST.TIER_B_COVERAGE_MIN), otherwise `TIER_C`. Step five: the tier sets a bonus rate of 0.05 (CONST.TIER_A_BONUS_RATE) for `TIER_A`, 0.02 (CONST.TIER_B_BONUS_RATE) for `TIER_B`, and zero for `TIER_C`. Step six: `effective_units` is base units multiplied by one plus the bonus rate, floored to a whole unit. Step seven: effective coverage is `effective_units` divided by `required_units`, computed at four decimal places rounded half up; the value is an intermediate of this confirmation calculation and is not stored on the commitment. The gate: confirmation succeeds only when base coverage is at least 1.0 — exactly 1.0 passes — and fails otherwise with `ERR_COMMITMENT_COVERAGE_INSUFFICIENT`. On success the computed `coverage_tier` and `effective_units` are stored on the commitment; until then both are null. The dependency that looks circular is resolved by construction: the tier bonus depends on the tier, the tier derives from pre-bonus base coverage only, and `effective_units` never re-enters the tier derivation.

Once `SECURED`, a commitment's health is tracked by `supply_coverage`: the sum of `units` over its allocations in `RESERVED` or `FULFILLED`, divided by `committed_units`, stored at four decimal places rounded half up. When a release cascade — an allocation manually released, a campaign aborted or cancelled, a composition retired — recomputes that figure below 1.0, the commitment moves from `SECURED` to `BREACH_WATCH`, its `breach_deadline` is set to the current logical clock plus 90 days (CONST.BREACH_GRACE_DAYS), and its maker's `standing_tier` is demoted one step. Coverage can also heal: when a new allocation — manual or waterfall-created — recomputes the coverage of a `BREACH_WATCH` commitment at or above 1.0, the commitment returns to `SECURED` and its `breach_deadline` clears to null. Two terminal exits arrive only through the operations checkpoint of §3.9: a commitment in `SECURED` or `BREACH_WATCH` whose `fulfilled_units` — the sum of `units` over its `FULFILLED` allocations — has reached its `committed_units` is marked `EXHAUSTED`, and a commitment still in `BREACH_WATCH` once the logical clock passes its `breach_deadline` is marked `BREACHED`.

While a commitment lives, finance may apply its prepayment to invoices: an apply-prepayment request carries `amount_cents`, which must be strictly positive — zero or negative fails with `ERR_INVALID_REQUEST` — and must not exceed `prepayment_remaining_cents`, failing with `ERR_PREPAYMENT_OVERAPPLY` when it does. A successful application adds the amount to `prepayment_applied_cents` and subtracts it from `prepayment_remaining_cents`; the refunded bucket is untouched.

A non-terminal commitment — one in `PROPOSED`, `SIGNED`, `COUNTERSIGNED`, `SECURED`, or `BREACH_WATCH` — may be released by the program manager, optionally recording a `reason`, or by the system through program termination or supersession. Release moves the commitment to `RELEASED`, terminal, refunds the ledger by adding `prepayment_remaining_cents` into `prepayment_refunded_cents` and zeroing the remaining bucket, and releases every `RESERVED` allocation of the commitment, increasing each affected campaign's `unallocated_units` by the released units. `EXHAUSTED`, `BREACHED`, and `RELEASED` are the commitment machine's terminal states.

### 3.5. Melting Tanks and Campaign Scheduling

A secured commitment funds steel and refractory. A `CapacityPlanner` builds a melting tank by naming the funding `commitment_id` and the tank's `capacity_units_per_day` in units per day, strictly positive. The referenced commitment must be `SECURED` — capacity investment is gated on a secured customer commitment, and any other status fails with `ERR_COMMITMENT_NOT_SECURED` — and a commitment funds at most one tank: a second tank against the same commitment fails with `ERR_TANK_ALREADY_EXISTS`. A new tank starts `CONSTRUCTING`, and its `construction_ready_date` is fixed at creation to its `created_at` plus 540 days (CONST.TANK_CONSTRUCTION_DAYS). Commissioning moves the tank from `CONSTRUCTING` to `COMMISSIONED` and is allowed only once the logical clock has reached `construction_ready_date`; an early attempt fails with `ERR_TANK_UNDER_CONSTRUCTION`. Tanks are never decommissioned in this model — `COMMISSIONED` has no outgoing transitions. Tanks may be listed filtered by `commitment_id` and `status`.

Campaigns occupy tanks. A `CapacityPlanner` schedules one by naming the `tank_id`, the `composition_id` to be melted, the window `start_date` and `end_date`, and the `planned_units` for the window. The window is a half-open interval — it includes its start instant and excludes its end instant — and several guards fire at scheduling time. The `end_date` must be strictly after the `start_date`, and the window's length in days must be at least 365 days (CONST.MIN_CAMPAIGN_DAYS, with exactly 365 allowed) and at most 1825 days (CONST.MAX_CAMPAIGN_DAYS); violations fail with `ERR_INVALID_CAMPAIGN_WINDOW`. The referenced composition must have reached at least `TUNED` — `TUNED`, `QUALIFIED`, and `LOCKED` are all schedulable — failing otherwise with `ERR_COMPOSITION_NOT_QUALIFIED`, and the referenced tank must already be `COMMISSIONED`, failing otherwise with `ERR_TANK_UNDER_CONSTRUCTION`. The `planned_units` must be strictly positive, failing with `ERR_NONPOSITIVE_UNITS` at zero, and must not exceed the tank's `capacity_units_per_day` multiplied by the window's length in days, failing with `ERR_CAMPAIGN_OVER_CAPACITY`. Finally, the tank schedule itself: the new half-open window must not overlap any existing non-terminal campaign window on the same tank, and versus every existing campaign on that tank with a different `composition_id`, the gap between the adjoining window edges must be at least 45 days (CONST.CHANGEOVER_GAP_DAYS) on whichever side they adjoin — same-composition neighbors may abut with a gap of zero. A violation fails with `ERR_TANK_SCHEDULE_CONFLICT`.

Yield on a new composition follows a learning curve, and the provisional variant is computed at scheduling time from `planned_units` alone. When `planned_units` is below 20000 units (CONST.YIELD_STEP1_MAX_UNITS) the provisional yield rate is 0.62 (CONST.YIELD_STEP1_RATE); at 20000 units or more but below 80000 units (CONST.YIELD_STEP2_MAX_UNITS) it is 0.78 (CONST.YIELD_STEP2_RATE); and at 80000 units or more it is 0.90 (CONST.YIELD_STEP3_RATE). The campaign's `expected_good_units` is `planned_units` multiplied by that provisional rate, floored to a whole unit, and fixed at creation — it is the allocatable supply pool, and the campaign's `unallocated_units` starts equal to it.

The provisional unit cost is computed at the same moment, per the cost model whose two variants share one formula and differ only in their inputs. The window's length in days is the campaign-day count. For the provisional variant, the basis units are `planned_units` and the yield basis is the provisional rate; for the final variant, described in §3.6, the basis units are the campaign's `cumulative_good_units` and the yield basis is the realized yield. The energy surcharge per unit is re-selected on the basis units: 60 cents (CONST.ENERGY_SURCHARGE_T2_CENTS) when the basis units are at least 50000 (CONST.ENERGY_SURCHARGE_T1_MAX_UNITS), and 120 cents (CONST.ENERGY_SURCHARGE_T1_CENTS) below that. Changeover amortization depends on the prior campaign on the same tank — the one with the latest `end_date` at or before this campaign's `start_date` among those in `SCHEDULED`, `RUNNING`, `COMPLETED`, or `ABORTED`: if there is no such prior campaign, or the prior campaign melts the same `composition_id`, the changeover total is zero; otherwise it is 4000 cents per campaign day (CONST.CHANGEOVER_AMORTIZATION_CENTS_PER_DAY) multiplied by the campaign-day count. The unit cost in integer cents is then the sum of two separately ceilinged components — the first component is the ceiling, to whole cents, of the quantity 850 cents base melt cost per unit (CONST.BASE_MELT_COST_CENTS_PER_UNIT) multiplied by the composition's `complexity_multiplier` plus the energy surcharge, all divided by the yield basis; the second component is the ceiling, to whole cents, of the changeover total divided by the basis units. The two ceilings are applied per component and only then summed; the order is pinned, and summing before ceiling is a different, wrong number. The result is stored on the campaign as `provisional_unit_cost_cents`. A new campaign starts `SCHEDULED`. Campaigns may be listed filtered by `tank_id`, `composition_id`, and `status`.

### 3.6. Running Campaigns, Production Records, and the Allocation Waterfall

Starting a campaign is a `CapacityPlanner` act gated on the clock and on readiness: the campaign must be `SCHEDULED`, the logical clock must have reached the campaign's `start_date` — an early start fails with `ERR_CAMPAIGN_NOT_STARTED` — and must not yet have reached its `end_date`, since the half-open window excludes its end instant and a start at or after it fails with `ERR_INVALID_STATE`. The composition must by then be `QUALIFIED` or `LOCKED` — scheduling accepted `TUNED`, but the melt itself does not — failing otherwise with `ERR_COMPOSITION_NOT_QUALIFIED`, and the tank must be `COMMISSIONED`, failing otherwise with `ERR_TANK_UNDER_CONSTRUCTION`. A legal start moves the campaign from `SCHEDULED` to `RUNNING`.

While the melt runs, the planner records production tallies against the `RUNNING` campaign, each carrying a `record_date`, the `good_units`, and the `scrap_units`. The two figures together must be strictly positive; a tally of zero good and zero scrap fails with `ERR_NONPOSITIVE_UNITS`. Each record adds its `good_units` into the campaign's `cumulative_good_units` and its `scrap_units` into `cumulative_scrap_units`, and recomputes `realized_yield`: total good divided by the sum of total good and total scrap across all of the campaign's production records regardless of `record_date` order, stored at six decimal places rounded half up. Until the first production record exists, `realized_yield` is null.

Completion closes the books. Once the logical clock has reached the campaign's `end_date` — earlier attempts fail with `ERR_CAMPAIGN_NOT_ENDED` — the planner may complete the `RUNNING` campaign, and the operations checkpoint of §3.9 completes any `RUNNING` campaign whose `end_date` has passed. Completion moves the campaign to `COMPLETED`, recomputes `realized_yield` from the production records, and computes `final_unit_cost_cents` per the final variant of the cost model in §3.5 — cumulative good units as the basis, realized yield as the yield basis, and the energy tier re-selected on the actual good units. If the campaign has no production records at all, `realized_yield` stays null and `final_unit_cost_cents` is null.

Aborting is the planner's emergency stop, defined from either `SCHEDULED` or `RUNNING` and moving the campaign to `ABORTED`. When a `RUNNING` campaign with at least one production record is aborted, `final_unit_cost_cents` is computed per the same final variant; aborting a campaign that never ran, or ran without records, leaves it null. Abort then cascades exactly as composition retirement did in §3.3, minus the first hop: every `RESERVED` allocation of the campaign is `RELEASED` with the campaign's `unallocated_units` increased by the released units; each still-`SECURED` commitment referenced by a released allocation has its `supply_coverage` recomputed and drops into `BREACH_WATCH` — deadline set to the clock plus 90 days (CONST.BREACH_GRACE_DAYS) — when coverage falls below 1.0 (CONST.SUPPLY_COVERAGE_MIN); and each maker behind a newly watched commitment is demoted one standing step.

A campaign can also be cancelled, but only by the system and only from `SCHEDULED`: a composition retirement, a program termination, or an operations checkpoint that finds a still-`SCHEDULED` campaign whose `end_date` has passed all move it to `CANCELLED`. Cancellation releases the campaign's `RESERVED` allocations with `unallocated_units` restored, recomputes the referenced still-`SECURED` commitments' coverage, and applies the same breach-watch transition with standing demotion where coverage falls below 1.0. `COMPLETED`, `ABORTED`, and `CANCELLED` are the campaign machine's terminal states.

Supply reaches commitments through allocations, and there are two ways to create them. The manual way: a `CapacityPlanner` names the `commitment_id`, the `campaign_id`, the `units` to allocate, and the OCC guard `expected_commitment_version` of §2.6. The commitment must be `SECURED` or `BREACH_WATCH` and the campaign `SCHEDULED` or `RUNNING`, failing otherwise with `ERR_INVALID_STATE`; the campaign's composition's program must equal the commitment's program, failing otherwise with `ERR_PROGRAM_MISMATCH`; the commitment's maker must not sit in `CONFIRMED_INFRINGEMENT`, failing with `ERR_IP_LITIGATION_HOLD`; the `units` must be strictly positive (`ERR_NONPOSITIVE_UNITS`); and two fiscal caps apply in order — the `units` must not exceed the commitment's remaining need, meaning `committed_units` minus the units already reserved or fulfilled for it (`ERR_COMMITMENT_UNITS_EXCEEDED`), and must not exceed the campaign's `unallocated_units`, with an exactly-equal allocation allowed (`ERR_INSUFFICIENT_CAMPAIGN_HEADROOM`). A successful creation decrements the campaign's `unallocated_units` by the allocated `units`, increments the Commitment's `version` by 1, recomputes the commitment's `supply_coverage`, and recovers a `BREACH_WATCH` commitment to `SECURED` when coverage reaches 1.0. The new allocation starts `RESERVED`. Allocations may be listed filtered by `commitment_id`, `campaign_id`, and `status`.

The automatic way is the allocation waterfall, run by a `CapacityPlanner` against one campaign. Its candidate set is every commitment whose `program_id` equals the program of the campaign's composition, whose status is `SECURED` or `BREACH_WATCH`, and whose device maker is not in `CONFIRMED_INFRINGEMENT`. Candidates are ranked deterministically with no id anywhere in the ordering: first, commitments in `BREACH_WATCH` sort before those in `SECURED`; then by coverage tier descending, `TIER_A` above `TIER_B` above `TIER_C`; then by `signed_at` ascending, earliest signature first; then by `created_at` ascending. The waterfall walks that order with the campaign's `unallocated_units` as its headroom: for each candidate it computes the remaining need — `committed_units` minus the units of its allocations in `RESERVED` or `FULFILLED` — and grants the smaller of that need and the remaining headroom. A grant larger than zero creates a `RESERVED` allocation for that commitment and campaign, decrements both the headroom and the campaign's `unallocated_units` by the grant, increments that Commitment's `version` by 1, recomputes its `supply_coverage`, and — when the candidate was in `BREACH_WATCH` and coverage has recovered to at least 1.0 — returns it to `SECURED`. The walk continues while headroom remains. When no candidate qualifies, no allocations are created and the waterfall simply returns success with an empty list.

A reservation is settled in one of two directions. Fulfilling it — glass shipped — moves the allocation from `RESERVED` to `FULFILLED`, and requires the campaign to be `RUNNING` or `COMPLETED` and the commitment to be `SECURED` or `BREACH_WATCH`, with any other pairing rejected as `ERR_INVALID_STATE`; fulfillment adds the allocation's `units` into the commitment's `fulfilled_units` and recomputes `supply_coverage`, including the breach-watch recovery when coverage reaches 1.0. Releasing it moves the allocation from `RESERVED` to `RELEASED` — by planner action, or by the system cascades of campaign abort or cancellation, composition retirement, program termination, or commitment release — restoring the allocation's `units` to the campaign's `unallocated_units` and recomputing the commitment's coverage, so that a still-`SECURED` commitment whose coverage falls below 1.0 enters `BREACH_WATCH` with deadline and demotion as above. `FULFILLED` and `RELEASED` are the allocation machine's terminal states.

### 3.7. Brand Licensing and Marketing Coordination

Once a platform's design is frozen, the brand itself becomes licensable. Every License carries two parallel and independent state dimensions. The first, `license_status`, is the legal lifecycle: `NEGOTIATION`, `ACTIVE`, `SUSPENDED`, `TERMINATED`, or `EXPIRED`. The second, `marketing_status`, is the brand-usage coordination track: `DRAFT`, `IN_REVIEW`, `APPROVED`, or `CHANGES_REQUIRED`. Neither dimension implies the other; a license may be legally `ACTIVE` while its marketing sits in `CHANGES_REQUIRED`, and royalty settlement cares about both, as §3.8 shows.

`LegalCounsel` creates a license by naming the licensee (`device_maker_id`), the platform `program_id`, the licensed usage `market` — one of `CONSUMER_ELECTRONICS`, `AUTOMOTIVE`, `PHARMA_PACKAGING`, or `ARCHITECTURAL` — and the term boundaries `effective_date` and `expiry_date`. The term is a closed interval, inclusive at both ends, and must span at least 180 days (CONST.LICENSE_MIN_TERM_DAYS); a shorter term fails with `ERR_INVALID_REQUEST`. A license whose `market` differs from the program's `primary_market` is a secondary application. Creation requires the program to be past `DRAFT` per the confidentiality gate, starts the license in `NEGOTIATION` with marketing in `DRAFT`, `suspension_reason` at `NONE`, and `cumulative_royalty_cents` at zero. Licenses may be listed filtered by `device_maker_id`, `program_id`, `market`, and `license_status`.

Activation moves a license from `NEGOTIATION` to `ACTIVE` and carries the heaviest precondition stack in the licensing area. The referenced program must be `DESIGN_FROZEN`, failing otherwise with `ERR_PROGRAM_NOT_FROZEN`. The licensee must not sit in `CONFIRMED_INFRINGEMENT`, failing with `ERR_IP_LITIGATION_HOLD`. For a secondary application, at least one composition of the program must be `LOCKED` — `QUALIFIED` is insufficient for adjacent-market certification — failing otherwise with `ERR_BASE_PLATFORM_NOT_QUALIFIED`. The logical clock must read at or after `effective_date` and at or before `expiry_date`, failing otherwise with `ERR_LICENSE_TERM_INVALID`. And no other license of the same `device_maker_id` and `market` may be `ACTIVE` with a closed term interval intersecting this one — because both intervals are closed, terms that merely touch at an expiry date count as overlapping — failing otherwise with `ERR_LICENSE_TERM_OVERLAP`.

Suspension and reinstatement bracket the active life. Counsel may suspend an `ACTIVE` license, moving it to `SUSPENDED` with `suspension_reason` set to `MANUAL`; the IP cascade of §3.1 suspends with `IP_REVIEW` instead. Reinstating a `SUSPENDED` license returns it to `ACTIVE` and clears `suspension_reason` to `NONE`, but only when the maker's `ip_review_status` is `CLEAR` or `CLEARED` — any other posture fails with `ERR_IP_LITIGATION_HOLD` — the logical clock is at or before `expiry_date` — failing otherwise with `ERR_LICENSE_TERM_INVALID` — and the closed-interval overlap rule re-evaluated against the maker's other `ACTIVE` licenses in the same market passes — failing otherwise with `ERR_LICENSE_TERM_OVERLAP`. Counsel may terminate a license from `NEGOTIATION`, `ACTIVE`, or `SUSPENDED`, moving it to `TERMINATED`, terminal. The only system-driven transition in this machine is expiry: the operations checkpoint moves an `ACTIVE` license to `EXPIRED`, also terminal, once the logical clock has passed its `expiry_date`.

The marketing track has its own small machine with no terminal states. The licensee submits brand-usage materials — a `DeviceMaker` write, ownership-checked against the license's maker — carrying a `materials_ref`, moving marketing from `DRAFT` or `CHANGES_REQUIRED` to `IN_REVIEW`; the license's legal state must be `NEGOTIATION` or `ACTIVE` at that moment, failing otherwise with `ERR_INVALID_STATE`. Counsel then reviews with a `decision`: `APPROVED` moves marketing from `IN_REVIEW` to `APPROVED`, and `CHANGES_REQUIRED` returns it to `CHANGES_REQUIRED`, from which the maker may resubmit.

### 3.8. Royalty Usage Reporting and Settlement

Licensed usage settles through usage reports. The licensee — a `DeviceMaker` write ownership-checked against the license's maker — submits a report naming the `license_id`, the reporting `period_start` and `period_end` as a closed interval inclusive at both ends with `period_end` strictly after `period_start`, and the `lines`: a non-empty array, each line carrying a `channel` of `DOMESTIC` or `EXPORT`, a strictly positive `units`, and a `net_revenue_cents` of zero or more. Malformed periods, empty `lines`, and invalid line members all fail with `ERR_INVALID_REQUEST`. The license must be `ACTIVE` or `SUSPENDED`, failing otherwise with `ERR_INVALID_STATE`, and its maker must not sit in `CONFIRMED_INFRINGEMENT`, failing with `ERR_IP_LITIGATION_HOLD`. One report per period: the new period must not overlap an existing report of the same license in `SUBMITTED` or `ACCEPTED`, failing otherwise with `ERR_REPORT_PERIOD_OVERLAP`; overlap with `DISPUTED` or `HELD` reports is expressly permitted, because a disputed or held report is superseded by its replacement. A new report starts `SUBMITTED`. Reports may be listed filtered by `license_id` and `status`.

The royalty rate is an average rate selected by volume, not a marginal one: the report's total units are the sum of `units` across all lines, and that total picks one rate for the whole report — 0.03 (CONST.ROYALTY_T1_RATE) when the total is at most 100000 units (CONST.ROYALTY_T1_MAX_UNITS), 0.022 (CONST.ROYALTY_T2_RATE) when it is above 100000 and at most 500000 units (CONST.ROYALTY_T2_MAX_UNITS), and 0.015 (CONST.ROYALTY_T3_RATE) above 500000. The selected rate is stored on the report as `royalty_rate_applied`.

The two royalty figures differ by rounding order, and the difference is by design. At submission, `provisional_royalty_cents` rounds per line first: each line's `net_revenue_cents` is multiplied by the selected rate, the product is rounded half up to integer cents line by line, and those rounded line amounts are then summed. At acceptance, `final_royalty_cents` sums first: the raw `net_revenue_cents` of all lines are summed unrounded, the total is multiplied by the selected rate, and the single product is rounded half up to integer cents exactly once. Whenever per-line fractional parts cross a rounding boundary in aggregate, the two figures differ; both are stored, and it is the final figure that settles.

A `SUBMITTED` report is adjudicated by a `FinanceController`. Acceptance requires the license's `license_status` to be `ACTIVE` or `SUSPENDED` — failing otherwise with `ERR_INVALID_STATE` — and its `marketing_status` to be `APPROVED`, failing otherwise with `ERR_MARKETING_NOT_APPROVED`. Acceptance moves the report to `ACCEPTED`, terminal, computes `final_royalty_cents` per the sum-then-round rule above, and adds it into the license's `cumulative_royalty_cents`. Dispute moves the report from `SUBMITTED` to `DISPUTED`, terminal, optionally recording a `reason`; a fresh report may then be submitted for an overlapping period per the supersession rule. The system's only transition here is the hold: the IP cascade of §3.1 moves a `SUBMITTED` report to `HELD`, also terminal, when the maker's infringement is confirmed.

### 3.9. The Operations Checkpoint

Time-driven transitions do not fire on their own; they are applied in one sweep when a `PlatformAdmin` or `CapacityPlanner` runs the operations checkpoint, which reads the current logical clock and settles everything due. One run performs five sweeps. It completes every `RUNNING` campaign whose `end_date` the clock has reached, computing realized yield and final unit cost as in §3.6. It cancels every still-`SCHEDULED` campaign whose `end_date` the clock has passed, with the full cancellation cascade of allocation release, coverage recomputation, breach watch, and standing demotion. It expires every `ACTIVE` license whose `expiry_date` the clock has passed. It marks every commitment in `SECURED` or `BREACH_WATCH` whose `fulfilled_units` have reached its `committed_units` as `EXHAUSTED`. And it flips every commitment still in `BREACH_WATCH` whose `breach_deadline` the clock has passed to `BREACHED`. The response reports the sweep's work as counts: `campaigns_completed`, `campaigns_cancelled`, `licenses_expired`, `commitments_exhausted`, and `commitments_breached`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/glass` prefix. Operations that create a new resource respond with HTTP 201; all other successful operations — reads, state transitions, and actions — respond with HTTP 200. Request payloads, preconditions, side effects, and error triggers for each endpoint are defined by the narratives of §2 and §3; the table below is a structural summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/glass/device-makers` | Register a device maker | PlatformAdmin |
| GET | `/glass/device-makers/{deviceMakerId}` | Get a device maker | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/device-makers` | List device makers | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/device-makers/{deviceMakerId}/ip-review` | Advance IP monitoring status; confirming infringement cascades to licenses and usage reports | LegalCounsel |
| POST | `/glass/programs` | Create a co-development program (starts DRAFT) | ProgramManager |
| GET | `/glass/programs/{programId}` | Get a program | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/programs` | List programs | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/programs/{programId}/execute-nda` | Execute the confidentiality agreement: DRAFT to NDA_EXECUTED | ProgramManager |
| POST | `/glass/programs/{programId}/begin-qualification` | Enter qualification and pin the design freeze deadline: COMPOSITION_TUNING to QUALIFICATION | ProgramManager |
| POST | `/glass/programs/{programId}/rework` | Send the program back to tuning: QUALIFICATION to COMPOSITION_TUNING | ProgramManager |
| POST | `/glass/programs/{programId}/freeze-design` | Freeze the device design: QUALIFICATION to DESIGN_FROZEN | ProgramManager |
| POST | `/glass/programs/{programId}/close` | Close a frozen program with nothing in flight: DESIGN_FROZEN to CLOSED | ProgramManager |
| POST | `/glass/programs/{programId}/terminate` | Terminate a program; releases non-terminal commitments with prepayment refunds and cancels SCHEDULED campaigns | ProgramManager |
| POST | `/glass/compositions` | Create a glass composition under a program (starts EXPERIMENTAL) | ProgramManager |
| GET | `/glass/compositions/{compositionId}` | Get a composition | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/compositions` | List compositions | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/compositions/{compositionId}/lock` | Lock a qualified composition, immutable thereafter: QUALIFIED to LOCKED | ProgramManager |
| POST | `/glass/compositions/{compositionId}/retire` | Retire a non-LOCKED composition; cancels its SCHEDULED campaigns and releases their allocations | ProgramManager |
| POST | `/glass/qual-cycles` | Submit a composition for a customer reliability qualification cycle (starts SUBMITTED, attempt 1) | ProgramManager |
| GET | `/glass/qual-cycles/{qualCycleId}` | Get a qualification cycle | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/qual-cycles` | List qualification cycles | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/qual-cycles/{qualCycleId}/begin-testing` | Customer begins reliability testing: SUBMITTED to IN_TESTING; first begin tunes the composition | DeviceMaker |
| POST | `/glass/qual-cycles/{qualCycleId}/record-result` | Customer records the reliability outcome: IN_TESTING to PASSED or FAILED; a pass qualifies a TUNED composition | DeviceMaker |
| POST | `/glass/qual-cycles/{qualCycleId}/resubmit` | Resubmit a failed cycle for another attempt: FAILED to SUBMITTED with the attempt counter incremented, hard cap applies | ProgramManager |
| POST | `/glass/tanks` | Build a melting tank funded by a SECURED commitment (starts CONSTRUCTING) | CapacityPlanner |
| GET | `/glass/tanks/{tankId}` | Get a tank | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/tanks` | List tanks | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/tanks/{tankId}/commission` | Commission a tank once the logical clock reaches its construction ready date | CapacityPlanner |
| POST | `/glass/campaigns` | Schedule a melting campaign on a tank for a composition (starts SCHEDULED); window, capacity, and changeover-buffer rules apply | CapacityPlanner |
| GET | `/glass/campaigns/{campaignId}` | Get a campaign | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/campaigns` | List campaigns | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/campaigns/{campaignId}/start` | Start a scheduled campaign: SCHEDULED to RUNNING | CapacityPlanner |
| POST | `/glass/campaigns/{campaignId}/abort` | Abort a SCHEDULED or RUNNING campaign; releases its reservations and may push commitments into breach watch | CapacityPlanner |
| POST | `/glass/campaigns/{campaignId}/complete` | Complete a RUNNING campaign at or after its end date; computes final yield and unit cost | CapacityPlanner |
| POST | `/glass/campaigns/{campaignId}/record-production` | Record a production tally of good and scrap units against a RUNNING campaign | CapacityPlanner |
| POST | `/glass/campaigns/{campaignId}/auto-allocate` | Run the allocation waterfall over the eligible commitments of the campaign's program; returns the created allocations, empty when none qualify | CapacityPlanner |
| POST | `/glass/commitments` | Propose a capacity commitment against a program (OCC-guarded); supersedes any existing PROPOSED commitment on the same program | ProgramManager |
| GET | `/glass/commitments/{commitmentId}` | Get a commitment | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/commitments` | List commitments | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/commitments/{commitmentId}/sign` | Device maker signs the commitment: PROPOSED to SIGNED | DeviceMaker |
| POST | `/glass/commitments/{commitmentId}/countersign` | Capacity planner countersigns: SIGNED to COUNTERSIGNED | CapacityPlanner |
| POST | `/glass/commitments/{commitmentId}/confirm-prepayment` | Finance confirms prepayment receipt: COUNTERSIGNED to SECURED; computes and stores the coverage tier; segregated from the countersigner | FinanceController |
| POST | `/glass/commitments/{commitmentId}/apply-prepayment` | Apply part of the remaining prepayment to an invoice, moving cents from the remaining bucket to the applied bucket | FinanceController |
| POST | `/glass/commitments/{commitmentId}/release` | Release a non-terminal commitment; refunds remaining prepayment and releases its RESERVED allocations | ProgramManager |
| POST | `/glass/allocations` | Allocate campaign supply to a commitment (OCC-guarded); same-program, remaining-need, and headroom rules apply | CapacityPlanner |
| GET | `/glass/allocations/{allocationId}` | Get an allocation | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/allocations` | List allocations | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/allocations/{allocationId}/release` | Release a RESERVED allocation; restores campaign headroom and may push the commitment into breach watch | CapacityPlanner |
| POST | `/glass/allocations/{allocationId}/fulfill` | Mark a RESERVED allocation fulfilled: glass shipped | CapacityPlanner |
| POST | `/glass/licenses` | Create a brand license (license status NEGOTIATION, marketing DRAFT); a market differing from the program's primary market is a secondary application | LegalCounsel |
| GET | `/glass/licenses/{licenseId}` | Get a license | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/licenses` | List licenses | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/licenses/{licenseId}/activate` | Activate a negotiated license: NEGOTIATION to ACTIVE | LegalCounsel |
| POST | `/glass/licenses/{licenseId}/suspend` | Suspend an active license with reason MANUAL: ACTIVE to SUSPENDED | LegalCounsel |
| POST | `/glass/licenses/{licenseId}/reinstate` | Reinstate a suspended license: SUSPENDED to ACTIVE | LegalCounsel |
| POST | `/glass/licenses/{licenseId}/terminate` | Terminate a license from any non-terminal state | LegalCounsel |
| POST | `/glass/licenses/{licenseId}/submit-marketing` | Device maker submits brand-usage materials: marketing DRAFT or CHANGES_REQUIRED to IN_REVIEW | DeviceMaker |
| POST | `/glass/licenses/{licenseId}/review-marketing` | Legal reviews marketing materials: IN_REVIEW to APPROVED or CHANGES_REQUIRED | LegalCounsel |
| POST | `/glass/usage-reports` | Submit a royalty usage report (starts SUBMITTED); provisional royalty computed with per-line rounding | DeviceMaker |
| GET | `/glass/usage-reports/{usageReportId}` | Get a usage report | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| GET | `/glass/usage-reports` | List usage reports | PlatformAdmin, ProgramManager, CapacityPlanner, FinanceController, LegalCounsel, DeviceMaker |
| POST | `/glass/usage-reports/{usageReportId}/accept` | Accept a report: computes the final royalty sum-then-round and accrues it to the license; requires marketing APPROVED | FinanceController |
| POST | `/glass/usage-reports/{usageReportId}/dispute` | Dispute a report: SUBMITTED to DISPUTED; a fresh report may then be submitted for an overlapping period | FinanceController |
| POST | `/glass/_clock/set_current_utc` | Set the logical clock to a supplied ISO 8601 UTC instant | PlatformAdmin |
| POST | `/glass/ops/checkpoint` | Run the operations checkpoint sweep: campaign completion and cancellation, license expiry, commitment exhaustion and breach | PlatformAdmin, CapacityPlanner |

## 5. Error Code Catalogue

The catalogue below lists every machine-readable error identifier and its HTTP status. The conditions that trigger each error are defined by the narratives of §2 and §3, not restated here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_PROGRAM_VERSION | 412 |
| ERR_STALE_COMMITMENT_VERSION | 412 |
| ERR_NDA_REQUIRED | 403 |
| ERR_IP_LITIGATION_HOLD | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_DESIGN_FREEZE_PASSED | 422 |
| ERR_INVALID_CAMPAIGN_WINDOW | 422 |
| ERR_TANK_SCHEDULE_CONFLICT | 422 |
| ERR_CAMPAIGN_NOT_STARTED | 422 |
| ERR_CAMPAIGN_NOT_ENDED | 422 |
| ERR_TANK_UNDER_CONSTRUCTION | 422 |
| ERR_LICENSE_TERM_INVALID | 422 |
| ERR_LICENSE_TERM_OVERLAP | 422 |
| ERR_REPORT_PERIOD_OVERLAP | 422 |
| ERR_COMPOSITION_NOT_QUALIFIED | 422 |
| ERR_PROGRAM_NOT_FROZEN | 422 |
| ERR_BASE_PLATFORM_NOT_QUALIFIED | 422 |
| ERR_PROGRAM_MISMATCH | 422 |
| ERR_COMMITMENT_NOT_SECURED | 422 |
| ERR_MAX_QUAL_ATTEMPTS | 422 |
| ERR_NONPOSITIVE_UNITS | 422 |
| ERR_TANK_ALREADY_EXISTS | 422 |
| ERR_NO_QUALIFIED_COMPOSITION | 422 |
| ERR_COMPOSITION_CODE_CONFLICT | 422 |
| ERR_CAMPAIGN_OVER_CAPACITY | 422 |
| ERR_PREPAYMENT_INSUFFICIENT | 422 |
| ERR_COMMITMENT_COVERAGE_INSUFFICIENT | 422 |
| ERR_COMMITMENT_UNITS_EXCEEDED | 422 |
| ERR_INSUFFICIENT_CAMPAIGN_HEADROOM | 422 |
| ERR_PREPAYMENT_OVERAPPLY | 422 |
| ERR_MARKETING_NOT_APPROVED | 422 |
