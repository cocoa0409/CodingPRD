"""Optimistic concurrency, version bookkeeping, derived reads and immediacy.

The two optimistic-concurrency endpoints are driven with tokens that went stale
for the two different reasons the PRD names — the caller's own counterparty
exchanged the cycle, and a sibling claim's approval rewrote the shared segment —
and each is shown outranking the business rules the same body also violates.
The remaining cases prove that `version` moves on every write and never on a
read, that the exposure block is re-derived rather than stored, and that a
cascade is already complete in the response of the call that triggered it.
"""

from test_helpers import (
    AUGUST_BOOTSTRAP,
    DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS,
    ERR_DISPUTED_AMOUNT_EXCEEDS_SUBJECT,
    ERR_RECLAIM_EVIDENCE_MISSING,
    ERR_RECLAIM_WINDOW_TOO_SHORT,
    ERR_STALE_VERSION,
    ApiClient,
    allow_reclaim,
    assert_error_envelope,
    assert_hours,
    assert_instant_equals,
    assert_money,
    assert_no_common_update_fields,
    closed_movement_of,
    closed_segment_world,
    deliver_back,
    deliver_out,
    exchanged_cycle,
    exposure,
    file_dispute,
    file_reclaim,
    ledger_entries,
    open_cycle,
    read_cycle,
    read_movement,
    set_clock,
    settled_cycle,
    standard_world,
    validate_paginated,
    validate_success,
)
import test_helpers.factories as f

DISPUTED_CENTS = 5000
ABSURD_CENTS = 999999999
DISPUTE_DEADLINE = "2026-10-01T00:00:00Z"
RESOLVED_AT = "2026-09-01T00:00:00Z"


def _disputes_on(api, world, cycle_id):
    """Every dispute row filed against one cycle, with its pagination meta."""
    return validate_paginated(api.list_disputes(
        world.accountant(world.bn), params={"settlement_cycle_id": cycle_id}))


def _stale_dispute_world(api):
    """The 11464 segment inside an EXCHANGED August cycle, with all three tokens."""
    world, movement = closed_segment_world(api)
    cycle, computed, exchanged = exchanged_cycle(api, world)
    return world, movement, cycle, computed, exchanged


class TestDisputeFiledWithAPreExchangeCycleVersion:
    """The token read from the caller's own compute response dies at exchange."""

    def test_the_version_read_at_compute_is_already_dead_after_exchange(self, api: ApiClient):
        """Filing with the compute-time version is 412 and creates no dispute row.

        PRD: "If the payee has recomputed the cycle since, or a cascade has reopened it, the version has moved on and the filing is rejected with `ERR_STALE_VERSION` (HTTP 412) with no `Dispute` row created."

        Design: Corner/cross-cutting complexity layers/dispute_filed_with_a_pre_exchange_cycle_version_returns_412
        """
        world, movement, cycle, computed, exchanged = _stale_dispute_world(api)
        assert cycle["version"] < computed["version"] < exchanged["version"]
        assert_money(computed["gross_hire_cents"], 11464, "gross_hire_cents")

        refused = api.create_dispute(
            f.dispute_payload(cycle["id"], "HIRE_RATE_MISAPPLIED", DISPUTED_CENTS,
                              computed["version"], movement_id=movement["id"],
                              filing_note="Filed from the statement we read at compute time"),
            world.accountant(world.bn))
        assert refused.status_code == 412
        body = assert_error_envelope(refused, ERR_STALE_VERSION, 412)
        assert body["message"].strip() != ""

        rows, meta = _disputes_on(api, world, cycle["id"])
        assert rows == []
        assert meta["total_count"] == 0
        assert read_cycle(api, world, cycle["id"])["version"] == exchanged["version"]

    def test_a_stale_token_outranks_the_amount_check_the_same_body_also_fails(self, api: ApiClient):
        """An absurd amount on a stale token still reports only ERR_STALE_VERSION.

        PRD: "This runs before every state and business rule below, so a stale version outranks all of them: a dispute filing that is both stale and names a subject outside the cycle reports `ERR_STALE_VERSION`, not `ERR_DISPUTE_SUBJECT_NOT_IN_CYCLE`; a reclaim filing that is both stale and targets a still-open segment reports `ERR_STALE_VERSION`, not `ERR_MOVEMENT_NOT_CLOSED`."

        Design: Corner/cross-cutting complexity layers/dispute_filed_with_a_pre_exchange_cycle_version_returns_412
        """
        world, movement, cycle, computed, exchanged = _stale_dispute_world(api)

        refused = api.create_dispute(
            f.dispute_payload(cycle["id"], "HIRE_RATE_MISAPPLIED", ABSURD_CENTS,
                              cycle["version"], movement_id=movement["id"]),
            world.accountant(world.bn))
        body = assert_error_envelope(refused, ERR_STALE_VERSION, 412)
        assert body["error_id"] != ERR_DISPUTED_AMOUNT_EXCEEDS_SUBJECT
        assert refused.status_code != 422

        rows, meta = _disputes_on(api, world, cycle["id"])
        assert meta["total_count"] == 0
        assert read_cycle(api, world, cycle["id"])["version"] == exchanged["version"]

    def test_the_freshly_exchanged_version_files_the_dispute(self, api: ApiClient):
        """The same body with the exchanged version is 201, OPEN at round 0, subject 11464.

        PRD: "The dispute is created `OPEN` with `round_number` 0, `filed_by_road_id` set to the cycle's payer and `respondent_road_id` to the cycle's payee, and the cycle's `version` is incremented by 1."

        Design: Corner/cross-cutting complexity layers/dispute_filed_with_a_pre_exchange_cycle_version_returns_412
        """
        world, movement, cycle, computed, exchanged = _stale_dispute_world(api)
        assert_instant_equals(exchanged["dispute_deadline_at"], DISPUTE_DEADLINE,
                              "dispute_deadline_at")

        dispute = validate_success(api.create_dispute(
            f.dispute_payload(cycle["id"], "HIRE_RATE_MISAPPLIED", DISPUTED_CENTS,
                              exchanged["version"], movement_id=movement["id"]),
            world.accountant(world.bn)), 201)

        assert dispute["status"] == "OPEN"
        assert dispute["round_number"] == 0
        assert dispute["filed_by_road_id"] == world.bn
        assert dispute["respondent_road_id"] == world.cx
        assert_money(dispute["subject_net_at_filing_cents"], 11464,
                     "subject_net_at_filing_cents")

        after = read_cycle(api, world, cycle["id"])
        assert after["version"] == exchanged["version"] + 1

        rows, meta = _disputes_on(api, world, cycle["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == dispute["id"]


FIRST_FROM = "2026-08-25T00:00:00Z"
FIRST_TO = "2026-08-26T00:00:00Z"
SECOND_FROM = "2026-08-26T00:00:00Z"
SECOND_TO = "2026-08-27T00:00:00Z"
SHORT_TO = "2026-08-26T06:00:00Z"


def _claims_on(api, world, movement_id):
    """Every reclaim claim resting on one segment, with its pagination meta."""
    return validate_paginated(api.list_reclaim_claims(
        world.accountant(world.bn), params={"movement_id": movement_id}))


def _sibling_allowed_world(api):
    """The 11464 segment after a sibling claim was allowed for 1422, and its fresh row."""
    world, movement = closed_segment_world(api)
    first = file_reclaim(api, world, movement, "CUSTOMER_DETENTION",
                        FIRST_FROM, FIRST_TO, detention_notified_at=FIRST_FROM)
    allowed = allow_reclaim(api, world, first)
    fresh = read_movement(api, world, movement["id"])
    return world, movement, allowed, fresh


def _second_claim_body(movement_id, version):
    """A perfectly legal 24-hour detention claim for the window after the first."""
    return f.reclaim_payload(movement_id, "CUSTOMER_DETENTION", SECOND_FROM,
                             SECOND_TO, version,
                             detention_notified_at=SECOND_FROM)


class TestReclaimFiledWithAVersionStaleFromASiblingAllowance:
    """A third party's approval of another claim invalidates the shared token."""

    def test_the_sibling_allowance_is_what_killed_the_token(self, api: ApiClient):
        """Refiling with the version used for the first claim is 412 and writes nothing.

        PRD: "If `expected_movement_version` does not equal the segment's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."

        Design: Corner/cross-cutting complexity layers/reclaim_filed_with_a_movement_version_stale_from_an_earlier_allow_returns_412
        """
        world, movement, allowed, fresh = _sibling_allowed_world(api)
        assert_money(allowed["credit_cents"], 1422, "credit_cents")
        assert_money(fresh["net_hire_cents"], 10042, "net_hire_cents")
        assert fresh["version"] > movement["version"]

        refused = api.create_reclaim_claim(
            _second_claim_body(movement["id"], movement["version"]),
            world.accountant(world.bn))
        assert_error_envelope(refused, ERR_STALE_VERSION, 412)

        rows, meta = _claims_on(api, world, movement["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == allowed["id"]
        assert read_movement(api, world, movement["id"])["version"] == fresh["version"]

    def test_a_stale_token_outranks_the_window_and_evidence_gates(self, api: ApiClient):
        """A stale, too-short, unevidenced body still reports only ERR_STALE_VERSION.

        PRD: "This runs before every state and business rule below, so a stale version outranks all of them: a dispute filing that is both stale and names a subject outside the cycle reports `ERR_STALE_VERSION`, not `ERR_DISPUTE_SUBJECT_NOT_IN_CYCLE`; a reclaim filing that is both stale and targets a still-open segment reports `ERR_STALE_VERSION`, not `ERR_MOVEMENT_NOT_CLOSED`."

        Design: Corner/cross-cutting complexity layers/reclaim_filed_with_a_movement_version_stale_from_an_earlier_allow_returns_412
        """
        world, movement, allowed, fresh = _sibling_allowed_world(api)

        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "BAD_ORDER", SECOND_FROM, SHORT_TO,
                              movement["version"]),
            world.accountant(world.bn))
        body = assert_error_envelope(refused, ERR_STALE_VERSION, 412)
        assert body["error_id"] != ERR_RECLAIM_WINDOW_TOO_SHORT
        assert body["error_id"] != ERR_RECLAIM_EVIDENCE_MISSING
        assert refused.status_code != 422

        rows, meta = _claims_on(api, world, movement["id"])
        assert meta["total_count"] == 1
        assert read_movement(api, world, movement["id"])["version"] == fresh["version"]

    def test_a_fresh_read_files_and_the_identical_body_then_goes_stale(self, api: ApiClient):
        """The re-read version files a 24.00-hour claim, and replaying it is 412.

        PRD: "On success, the segment's `version` is incremented by 1 — which means resubmitting the identical body a second time also fails with `ERR_STALE_VERSION`, and the client must re-read the segment between filings."

        Design: Corner/cross-cutting complexity layers/reclaim_filed_with_a_movement_version_stale_from_an_earlier_allow_returns_412
        """
        world, movement, allowed, fresh = _sibling_allowed_world(api)
        body = _second_claim_body(movement["id"], fresh["version"])

        second = validate_success(api.create_reclaim_claim(
            body, world.accountant(world.bn)), 201)
        assert second["status"] == "FILED"
        assert_hours(second["claimed_hours"], 24.00, "claimed_hours")
        assert_money(second["credit_cents"], 0, "credit_cents")

        replayed = api.create_reclaim_claim(body, world.accountant(world.bn))
        assert_error_envelope(replayed, ERR_STALE_VERSION, 412)

        rows, meta = _claims_on(api, world, movement["id"])
        assert meta["total_count"] == 2


BAD_ORDER_AT = "2026-08-20T06:00:00Z"
RELEASED_AT = "2026-08-20T12:00:00Z"
ISSUED_AT = "2026-08-20T13:00:00Z"
DUE_AT = "2026-08-25T00:00:00Z"
JULY_MONTH = "2026-07"


def _registered_car(api):
    """A CX-owned car registered by its FleetOwner at the bootstrap clock."""
    world = standard_world(api, bootstrap_clock=AUGUST_BOOTSTRAP,
                           register_first_car=False)
    car = validate_success(api.create_car(
        f.car_payload("CX 100001", world.xm, world.cx,
                      initial_handling_road_id=world.cx),
        world.owner(world.cx)), 201)
    return world, car


class TestVersionMovesOnWritesOnly:
    """Every successful write bumps by exactly 1; no read ever does."""

    def test_a_new_row_starts_at_one_and_two_reads_leave_it_there(self, api: ApiClient):
        """The car is created at version 1 and stays there across two GETs.

        PRD: "Most resources additionally carry `updated_at` — refreshed on every mutation, in the same ISO 8601 UTC format with three fractional digits — and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, including mutations that only touch derived money fields."

        Design: Corner/cross-cutting complexity layers/version_increments_on_every_write_and_never_on_a_read
        """
        world, car = _registered_car(api)
        assert car["version"] == 1
        assert_instant_equals(car["created_at"], AUGUST_BOOTSTRAP, "created_at")
        assert_instant_equals(car["updated_at"], car["created_at"], "updated_at")

        set_clock(api, BAD_ORDER_AT, world)
        first = validate_success(api.get_car(car["id"], world.owner(world.cx)))
        second = validate_success(api.get_car(car["id"], world.owner(world.cx)))

        assert first["version"] == 1
        assert second["version"] == 1
        assert_instant_equals(first["updated_at"], car["updated_at"], "updated_at")
        assert_instant_equals(second["updated_at"], car["updated_at"], "updated_at")
        assert_instant_equals(second["created_at"], car["created_at"], "created_at")

    def test_three_single_dimension_actions_bump_by_exactly_one_each(self, api: ApiClient):
        """Bad order, release and obligation take the car to versions 2, 3 and 4.

        PRD: "Most resources additionally carry `updated_at` — refreshed on every mutation, in the same ISO 8601 UTC format with three fractional digits — and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, including mutations that only touch derived money fields."

        Design: Corner/cross-cutting complexity layers/version_increments_on_every_write_and_never_on_a_read
        """
        world, car = _registered_car(api)

        set_clock(api, BAD_ORDER_AT, world)
        bad = validate_success(api.report_bad_order(
            car["id"], f.bad_order_payload(BAD_ORDER_AT), world.clerk(world.cx)))
        assert bad["version"] == 2
        assert bad["mechanical_status"] == "BAD_ORDER"
        assert_instant_equals(bad["updated_at"], BAD_ORDER_AT, "updated_at")

        set_clock(api, RELEASED_AT, world)
        released = validate_success(api.release_to_service(
            car["id"], f.release_payload(RELEASED_AT), world.clerk(world.cx)))
        assert released["version"] == 3
        assert released["mechanical_status"] == "SERVICEABLE"
        assert_instant_equals(released["updated_at"], RELEASED_AT, "updated_at")

        set_clock(api, ISSUED_AT, world)
        obliged = validate_success(api.issue_empty_routing_obligation(
            car["id"], f.routing_obligation_payload(world.jct, ISSUED_AT, DUE_AT),
            world.owner(world.cx)))
        assert obliged["version"] == 4
        assert obliged["routing_status"] == "OBLIGATION_ACTIVE"
        assert obliged["custody_status"] == "ON_HOME_ROAD"
        assert obliged["mechanical_status"] == "SERVICEABLE"
        assert_instant_equals(obliged["updated_at"], ISSUED_AT, "updated_at")
        assert_instant_equals(obliged["created_at"], car["created_at"], "created_at")

    def test_compute_and_exchange_are_writes_to_the_cycle(self, api: ApiClient):
        """An empty July cycle goes 1, 2, 3 across creation, compute and exchange.

        PRD: "A successful compute takes the cycle `OPEN → COMPUTED` on the first pass and `REOPENED → COMPUTED` on any later one, stamps `computed_at` and increments `version`."

        Design: Corner/cross-cutting complexity layers/version_increments_on_every_write_and_never_on_a_read
        """
        world, car = _registered_car(api)
        cycle = open_cycle(api, world, period_month=JULY_MONTH, clock=None)
        assert cycle["version"] == 1
        assert cycle["status"] == "OPEN"

        read_back = read_cycle(api, world, cycle["id"])
        assert read_back["version"] == 1

        computed = validate_success(api.compute_settlement_cycle(
            cycle["id"], {}, world.accountant(world.cx)))
        assert computed["version"] == 2
        assert computed["status"] == "COMPUTED"

        exchanged = validate_success(api.exchange_settlement_cycle(
            cycle["id"], {}, world.accountant(world.cx)))
        assert exchanged["version"] == 3
        assert exchanged["status"] == "EXCHANGED"

    def test_ledger_entries_carry_no_version_and_no_updated_at(self, api: ApiClient):
        """The settled cycle's ledger rows expose id and created_at only.

        PRD: "Three record kinds are immutable by design and carry only `id` and `created_at` — for these, both `updated_at` and `version` are absent from the payload entirely:"

        Design: Corner/cross-cutting complexity layers/version_increments_on_every_write_and_never_on_a_read
        """
        world, movement = closed_segment_world(api)
        cycle, computed, exchanged, settled = settled_cycle(api, world)
        assert settled["version"] > exchanged["version"]

        rows = ledger_entries(api, world.accountant(world.bn),
                              settlement_cycle_id=cycle["id"])
        assert len(rows) == 2
        for row in rows:
            assert_no_common_update_fields(row, "hire ledger entry")
            assert row["settlement_cycle_id"] == cycle["id"]

        kinds = sorted(row["entry_type"] for row in rows)
        assert kinds == ["HIRE_CHARGE", "SETTLEMENT_PAYMENT"]


OUT_AT = "2026-08-24T00:00:00Z"
MID_CLOCK = "2026-08-26T00:00:00Z"
BACK_AT = "2026-08-28T00:00:00Z"


def _open_at_mid_clock(api):
    """BN holding a CX car since 08-24, read with the clock at 08-26."""
    world = standard_world(api)
    before = exposure(api, world, world.bn)
    deliver_out(api, world, world.car, OUT_AT, 1000)
    set_clock(api, MID_CLOCK, world)
    return world, before


def _closed_at_back_at(api):
    """The same segment closed at 08-28 for 240 miles, netting 11464."""
    world, before = _open_at_mid_clock(api)
    deliver_back(api, world, world.car, BACK_AT, 1240)
    return world


class TestExposureIsDerivedOnEveryRead:
    """Open, closed and reversed states each reconcile with no recompute call."""

    def test_an_empty_road_reads_zero_and_an_open_segment_accrues_to_the_clock(self, api: ApiClient):
        """BN reads 0 before the handoff and 4700 with the segment still open.

        PRD: "Under the `SNAPSHOT` variant — the default, and the variant that maintains the stored `per_diem_exposure_cents` — a `CLOSED` segment contributes its `net_hire_cents` as it stands, while an `OPEN` segment is accrued as if it closed at the logical clock, running the time component of §3.4 with `end_at` set to now and adding mileage of 0, since no delivery odometer has been reported yet."

        Design: Corner/cross-cutting complexity layers/exposure_derived_block_reconciles_after_open_close_and_reversal
        """
        world, before = _open_at_mid_clock(api)
        assert before["variant_applied"] == "SNAPSHOT"
        assert_money(before["exposure_cents"], 0, "exposure_cents")
        assert before["open_movement_count"] == 0
        assert before["foreign_car_balance"] == 0
        assert_money(before["closed_unsettled_cents"], 0, "closed_unsettled_cents")

        during = exposure(api, world, world.bn)
        assert during["open_movement_count"] == 1
        assert during["foreign_car_balance"] == 1
        assert_money(during["exposure_cents"], 4700, "exposure_cents")
        assert_money(during["closed_unsettled_cents"], 0, "closed_unsettled_cents")
        assert_money(during["settled_paid_cents"], 0, "settled_paid_cents")

    def test_closing_moves_the_accrual_between_buckets_without_changing_the_total(self, api: ApiClient):
        """The return leaves 0 open segments, 11464 closed-unsettled and 11464 exposure.

        PRD: "The input set is every segment whose `handling_road_id` is that railroad, whose `hire_liable` is true, and whose `status` is `OPEN` or `CLOSED`, less the amounts already remitted."

        Design: Corner/cross-cutting complexity layers/exposure_derived_block_reconciles_after_open_close_and_reversal
        """
        world = _closed_at_back_at(api)
        after = exposure(api, world, world.bn)

        assert after["open_movement_count"] == 0
        assert after["foreign_car_balance"] == 0
        assert_money(after["closed_unsettled_cents"], 11464, "closed_unsettled_cents")
        assert_money(after["exposure_cents"], 11464, "exposure_cents")
        assert_money(after["settled_paid_cents"], 0, "settled_paid_cents")

    def test_filing_changes_nothing_and_allowing_reverses_the_accrual(self, api: ApiClient):
        """The pending claim leaves 11464 standing; the allowance drops it to 10042.

        PRD: "Exposure is refreshed on every segment close, reclaim decision, correction application and cycle settlement."

        Design: Corner/cross-cutting complexity layers/exposure_derived_block_reconciles_after_open_close_and_reversal
        """
        world = _closed_at_back_at(api)
        movement = closed_movement_of(api, world.car, world.bn,
                                     world.accountant(world.bn))

        claim = file_reclaim(api, world, movement, "CUSTOMER_DETENTION",
                            FIRST_FROM, FIRST_TO, detention_notified_at=FIRST_FROM)
        pending = exposure(api, world, world.bn)
        assert_money(pending["exposure_cents"], 11464, "exposure_cents")

        allowed = allow_reclaim(api, world, claim)
        assert_money(allowed["credit_cents"], 1422, "credit_cents")

        reversed_read = exposure(api, world, world.bn)
        assert_money(reversed_read["closed_unsettled_cents"], 10042,
                     "closed_unsettled_cents")
        assert_money(reversed_read["exposure_cents"], 10042, "exposure_cents")
        assert reversed_read["open_movement_count"] == 0

    def test_headroom_is_derived_from_the_very_exposure_figure_reported(self, api: ApiClient):
        """Headroom reads 99988536 against 11464 and 99989958 after the 1422 credit.

        PRD: "`credit_headroom_cents` is `per_diem_credit_limit_cents` minus the exposure, and a statement compute that would drive headroom negative is refused with `ERR_PER_DIEM_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/cross-cutting complexity layers/exposure_derived_block_reconciles_after_open_close_and_reversal
        """
        world = _closed_at_back_at(api)
        movement = closed_movement_of(api, world.car, world.bn,
                                     world.accountant(world.bn))

        closed = exposure(api, world, world.bn)
        assert_money(closed["credit_limit_cents"], DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS,
                     "credit_limit_cents")
        assert_money(closed["credit_headroom_cents"], 99988536, "credit_headroom_cents")
        assert (closed["credit_limit_cents"] - closed["exposure_cents"]
                == closed["credit_headroom_cents"])

        claim = file_reclaim(api, world, movement, "CUSTOMER_DETENTION",
                            FIRST_FROM, FIRST_TO, detention_notified_at=FIRST_FROM)
        allow_reclaim(api, world, claim)

        after = exposure(api, world, world.bn)
        assert_money(after["credit_headroom_cents"], 99989958, "credit_headroom_cents")
        assert (after["credit_limit_cents"] - after["exposure_cents"]
                == after["credit_headroom_cents"])


def _accepted_dispute_world(api):
    """The 11464 line disputed at 5000 inside an exchanged cycle, then accepted."""
    world, movement = closed_segment_world(api)
    cycle, computed, exchanged = exchanged_cycle(api, world)
    dispute = file_dispute(api, world, exchanged, "HIRE_RATE_MISAPPLIED",
                          DISPUTED_CENTS, movement_id=movement["id"])
    accepted = validate_success(api.accept_dispute(dispute["id"], {},
                                                world.accountant(world.cx)))
    return world, movement, cycle, exchanged, dispute, accepted


class TestCascadesAreCompleteInTheTriggeringResponse:
    """The accept response already carries what a later read will report."""

    def test_the_accepting_call_returns_the_final_outcome_itself(self, api: ApiClient):
        """The accept body carries ACCEPTED, 5000 and the resolution instant.

        PRD: "Either way `resolution_amount_cents` becomes the standing `counter_amount_cents` when a counter stands and `disputed_amount_cents` when none does, `resolved_at` is stamped, and the money moves: the subject segment's `adjusted_net_hire_cents` becomes its `net_hire_cents` minus `resolution_amount_cents`, a `DISPUTE_ADJUSTMENT` ledger entry for the negative of the resolution is minted, and the cycle is recomputed under `RECONCILED`."

        Design: Corner/consistency model/every_cascade_is_visible_in_the_same_response_not_on_a_later_read
        """
        world, movement, cycle, exchanged, dispute, accepted = _accepted_dispute_world(api)
        assert_money(exchanged["net_settlement_cents"], 11407, "net_settlement_cents")
        assert dispute["status"] == "OPEN"

        assert accepted["status"] == "ACCEPTED"
        assert_money(accepted["resolution_amount_cents"], 5000,
                     "resolution_amount_cents")
        assert_instant_equals(accepted["resolved_at"], RESOLVED_AT, "resolved_at")
        assert_money(accepted["subject_net_at_filing_cents"], 11464,
                     "subject_net_at_filing_cents")

    def test_the_first_read_after_the_accept_already_agrees_with_it(self, api: ApiClient):
        """Segment, cycle, ledger and statement all report the adjustment at once.

        PRD: "The rule is that every consequence is applied immediately and synchronously within the request that triggered it — there is no deferred or batched reconciliation — and every row touched has its `updated_at` refreshed and its `version` incremented."

        Design: Corner/consistency model/every_cascade_is_visible_in_the_same_response_not_on_a_later_read
        """
        world, movement, cycle, exchanged, dispute, accepted = _accepted_dispute_world(api)

        line = read_movement(api, world, movement["id"])
        assert_money(line["adjusted_net_hire_cents"], 6464, "adjusted_net_hire_cents")
        assert_money(line["net_hire_cents"], 11464, "net_hire_cents")

        stored = read_cycle(api, world, cycle["id"])
        assert stored["status"] == "EXCHANGED"
        assert stored["variant_applied"] == "RECONCILED"
        assert_money(stored["pre_fee_net_cents"], 6464, "pre_fee_net_cents")
        assert_money(stored["clearinghouse_fee_cents"], 32, "clearinghouse_fee_cents")
        assert_money(stored["net_settlement_cents"], 6432, "net_settlement_cents")

        rows = ledger_entries(api, world.accountant(world.bn),
                              dispute_id=dispute["id"])
        assert len(rows) == 1
        assert rows[0]["entry_type"] == "DISPUTE_ADJUSTMENT"
        assert_money(rows[0]["amount_cents"], -5000, "amount_cents")

        statement = validate_success(api.get_settlement_statement(
            cycle["id"], world.accountant(world.bn),
            params={"variant": "RECONCILED"}))
        assert_money(statement["dispute_adjustment_cents"], -5000,
                     "dispute_adjustment_cents")
        assert_money(statement["net_settlement_cents"], 6432, "net_settlement_cents")

    def test_repeating_every_read_returns_the_same_figures(self, api: ApiClient):
        """Nothing was still settling: the second pass of reads matches the first.

        PRD: "The rule is that every consequence is applied immediately and synchronously within the request that triggered it — there is no deferred or batched reconciliation — and every row touched has its `updated_at` refreshed and its `version` incremented."

        Design: Corner/consistency model/every_cascade_is_visible_in_the_same_response_not_on_a_later_read
        """
        world, movement, cycle, exchanged, dispute, accepted = _accepted_dispute_world(api)

        first_line = read_movement(api, world, movement["id"])
        first_cycle = read_cycle(api, world, cycle["id"])
        first_rows = ledger_entries(api, world.accountant(world.bn),
                                    dispute_id=dispute["id"])
        first_statement = validate_success(api.get_settlement_statement(
            cycle["id"], world.accountant(world.bn),
            params={"variant": "RECONCILED"}))

        assert read_movement(api, world, movement["id"]) == first_line
        assert read_cycle(api, world, cycle["id"]) == first_cycle
        assert ledger_entries(api, world.accountant(world.bn),
                              dispute_id=dispute["id"]) == first_rows
        assert validate_success(api.get_settlement_statement(
            cycle["id"], world.accountant(world.bn),
            params={"variant": "RECONCILED"})) == first_statement

        assert first_cycle["version"] == read_cycle(api, world, cycle["id"])["version"]
        assert_money(first_statement["net_settlement_cents"], 6432,
                     "net_settlement_cents")
