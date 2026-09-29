"""Two temporal-occupancy resources with deliberately different interval
conventions: the half-open effective window of an incentive program's
(incentive_type, footprint) slot, and the closed pay period a payment batch
occupies in its region's calendar.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, AUG_16, AUG_31, BUILD_FROM, BUILD_TO

# --- The (incentive_type, eligibility footprint) slot ------------------------

OVERLAP_CLOCK = "2026-07-25T00:00:00.000Z"
AUG_10 = "2026-08-10T00:00:00.000Z"
AUG_15 = "2026-08-15T00:00:00.000Z"
AUG_20 = "2026-08-20T00:00:00.000Z"

MX5_FOOTPRINT = {
    "model_code": "MX5",
    "region_code": "WEST",
    "build_date_from": BUILD_FROM,
    "build_date_to": BUILD_TO,
    "allowed_deal_types": ["CASH"],
}


def _draft_cash_program(code, name, effective_from, effective_to, priority_rank,
                        footprint=None):
    """A DRAFT CUSTOMER_CASH program carrying exactly one footprint row, which is
    the minimum a submission requires."""
    program = fx.create_draft_program(
        payload=f.create_program_payload(
            program_code=code,
            name=name,
            incentive_type="CUSTOMER_CASH",
            effective_from=effective_from,
            effective_to=effective_to,
            per_unit_amount_cents=100000,
            budget_cents=20000000,
            stack_group="RTO",
            priority_rank=priority_rank,
            accrual_method="UNIT_BASED",
        )
    )
    fx.add_eligibility_rule(program["id"], **(footprint or MX5_FOOTPRINT))
    return program


def test_adjacent_disjoint_and_explicitly_stacked_windows_are_all_accepted():
    """A window starting exactly on the incumbent's exclusive effective_to is
    adjacent rather than overlapping; a disjoint footprint never collides
    however completely the calendars intersect; and an ALLOWED stackability edge
    is the declared escape hatch from the check.

    PRD: "The check looks for another program that is in `PENDING_APPROVAL` or
    `ACTIVE`, carries the same `incentive_type`, has an effective window that
    intersects this program's half-open window, and has an eligibility footprint
    that intersects this program's footprint — meaning some pair of footprint
    rows shares a `model_code`, has overlapping trim scope, shares a
    `region_code`, and has intersecting closed build-date intervals."
    PRD: "If such a program is found, the operation is refused with
    `ERR_PROGRAM_WINDOW_OVERLAP` — unless a stacking edge whose `mode` is
    `ALLOWED` or `CAPPED_TOTAL` joins the two programs, which is the designer's
    explicit statement that the collision is intentional and priced."

    Design: Difficulty/resource_temporal_overlap/half_open_program_windows_allow_adjacency_but_refuse_one_day_intersection
    """
    fx.set_clock(OVERLAP_CLOCK)

    incumbent = _draft_cash_program("RTO-A", "Overlap A", AUG_01, AUG_16, 131)
    pending_incumbent = fx.submit_program(incumbent["id"])
    a.assert_status(pending_incumbent, "PENDING_APPROVAL")

    adjacent = _draft_cash_program("RTO-B", "Overlap B adjacent", AUG_16, AUG_31, 132)
    stacked = _draft_cash_program(
        "RTO-D", "Overlap D with allowed edges", AUG_10, AUG_20, 134
    )
    fx.add_stack_edge(stacked["id"], incumbent["id"], "ALLOWED")
    fx.add_stack_edge(stacked["id"], adjacent["id"], "ALLOWED")
    disjoint = _draft_cash_program(
        "RTO-E",
        "Overlap E disjoint footprint",
        AUG_01,
        AUG_31,
        135,
        footprint=dict(MX5_FOOTPRINT, model_code="TRK9"),
    )

    accepted_adjacent = validate_success(
        api_client.submit_program(adjacent["id"], fx.DESIGNER)
    )
    a.assert_status(accepted_adjacent, "PENDING_APPROVAL")

    accepted_stacked = validate_success(
        api_client.submit_program(stacked["id"], fx.DESIGNER)
    )
    a.assert_status(accepted_stacked, "PENDING_APPROVAL")

    accepted_disjoint = validate_success(
        api_client.submit_program(disjoint["id"], fx.DESIGNER)
    )
    a.assert_status(accepted_disjoint, "PENDING_APPROVAL")


def test_one_day_of_window_intersection_is_refused_and_leaves_the_program_untouched():
    """One day of intersection is enough to collide, the refusal touches nothing
    on the refused program, and the occupancy set covers ACTIVE exactly as it
    covers PENDING_APPROVAL.

    PRD: "The check looks for another program that is in `PENDING_APPROVAL` or
    `ACTIVE`, carries the same `incentive_type`, has an effective window that
    intersects this program's half-open window, and has an eligibility footprint
    that intersects this program's footprint — meaning some pair of footprint
    rows shares a `model_code`, has overlapping trim scope, shares a
    `region_code`, and has intersecting closed build-date intervals."
    PRD: "Checks are evaluated in the following order, and the first failure
    short-circuits the request; no side effect of any kind is applied to any
    entity once a check fails."

    Design: Difficulty/resource_temporal_overlap/half_open_program_windows_allow_adjacency_but_refuse_one_day_intersection
    """
    fx.set_clock(OVERLAP_CLOCK)

    incumbent = _draft_cash_program("RTO-A", "Overlap A", AUG_01, AUG_16, 131)
    pending_incumbent = fx.submit_program(incumbent["id"])
    a.assert_status(pending_incumbent, "PENDING_APPROVAL")

    intersecting = _draft_cash_program(
        "RTO-C", "Overlap C one day early", AUG_15, AUG_31, 133
    )
    before = validate_success(api_client.get_program(intersecting["id"], fx.DESIGNER))
    a.assert_status(before, "DRAFT")
    assert before["submitted_by_user_id"] is None, before

    validate_error(
        api_client.submit_program(intersecting["id"], fx.DESIGNER),
        ApiErrorId.ERR_PROGRAM_WINDOW_OVERLAP.value,
    )

    after = validate_success(api_client.get_program(intersecting["id"], fx.DESIGNER))
    a.assert_identical_entity(before, after)
    a.assert_status(after, "DRAFT")
    assert after["submitted_by_user_id"] is None, after
    a.assert_version(after, before["version"])

    activated = fx.approve_program(incumbent["id"])
    a.assert_status(activated, "ACTIVE")

    validate_error(
        api_client.submit_program(intersecting["id"], fx.DESIGNER),
        ApiErrorId.ERR_PROGRAM_WINDOW_OVERLAP.value,
    )
    still_draft = validate_success(
        api_client.get_program(intersecting["id"], fx.DESIGNER)
    )
    a.assert_status(still_draft, "DRAFT")


# --- The region's closed pay-period calendar ---------------------------------

BATCH_CLOCK = "2026-08-20T00:00:00.000Z"
AUG_02 = "2026-08-02T00:00:00.000Z"
AUG_14 = "2026-08-14T00:00:00.000Z"
AUG_17 = "2026-08-17T00:00:00.000Z"
AUG_28 = "2026-08-28T00:00:00.000Z"
SEP_10 = "2026-09-10T00:00:00.000Z"
SEP_20 = "2026-09-20T00:00:00.000Z"
SEP_25 = "2026-09-25T00:00:00.000Z"


def _batch_payload(code, region, period_start, period_end, scheduled_pay_date):
    return f.create_payment_batch_payload(
        batch_code=code,
        region_code=region,
        period_start=period_start,
        period_end=period_end,
        scheduled_pay_date=scheduled_pay_date,
    )


def _open_incumbent_batch():
    """One OPEN WEST batch over the closed period 2026-08-01..2026-08-15. No
    claims are needed: period occupancy is a property of the batch itself."""
    fx.set_clock(BATCH_CLOCK)
    batch = validate_success(
        api_client.create_payment_batch(
            _batch_payload("RTB-1", "WEST", AUG_01, AUG_15, SEP_10), fx.CONTROLLER
        ),
        201,
    )
    a.assert_status(batch, "OPEN")
    a.assert_int_field(batch, "claim_count", 0)
    return batch


def test_pay_period_occupancy_is_region_scoped_and_cancellation_releases_it():
    """The very period one region refuses is free in another region, and once the
    incumbent batch is cancelled its interval may be reused.

    PRD: "The **period-overlap** check refuses a batch whose closed period
    intersects the closed period of any other batch of the **same**
    `region_code` whose `status` is `OPEN`, `LOCKED` or `DISBURSED`, reporting
    `ERR_BATCH_PERIOD_OVERLAP`; batches of different regions never collide, and
    a cancelled batch has stopped occupying its interval so a later batch may
    reuse it."
    PRD: "Cancellation releases the queue: every claim of this batch in
    `SCHEDULED` returns to `payment_status` `UNPAID` with its `payment_batch_id`
    cleared to null, and the batch's `claim_count` and `total_cents` are both set
    to 0."

    Design: Difficulty/resource_temporal_overlap/closed_batch_periods_need_a_strictly_greater_than_one_day_settlement_gap
    """
    incumbent = _open_incumbent_batch()

    validate_error(
        api_client.create_payment_batch(
            _batch_payload("RTB-3", "WEST", AUG_10, AUG_20, SEP_20), fx.CONTROLLER
        ),
        ApiErrorId.ERR_BATCH_PERIOD_OVERLAP.value,
    )

    other_region = validate_success(
        api_client.create_payment_batch(
            _batch_payload("RTB-5", "EAST", AUG_10, AUG_20, SEP_20), fx.CONTROLLER
        ),
        201,
    )
    a.assert_status(other_region, "OPEN")
    assert other_region["region_code"] == "EAST", other_region

    cancelled = validate_success(
        api_client.cancel_batch(incumbent["id"], fx.CONTROLLER)
    )
    a.assert_status(cancelled, "CANCELLED")
    a.assert_int_field(cancelled, "claim_count", 0)
    a.assert_money(cancelled, "total_cents", 0)

    reuser = validate_success(
        api_client.create_payment_batch(
            _batch_payload("RTB-6", "WEST", AUG_02, AUG_14, SEP_25), fx.CONTROLLER
        ),
        201,
    )
    a.assert_status(reuser, "OPEN")


def test_a_one_day_settlement_gap_is_refused_while_an_intersection_reports_overlap():
    """Adjacency is refused here, not accepted: the gap must be strictly greater
    than one whole day. When the closed periods actually intersect, the
    period-overlap check outranks the buffer check.

    PRD: "The **settlement-buffer** check goes further: even when the closed
    periods do not intersect, the gap between the new batch's `period_start` and
    the `period_end` of the nearest preceding batch of the same region must be
    strictly greater than one whole day, and back-to-back or exactly-one-day-apart
    periods are refused with `ERR_BATCH_BUFFER_VIOLATION`."
    PRD: "Checks are evaluated in the following order, and the first failure
    short-circuits the request; no side effect of any kind is applied to any
    entity once a check fails."

    Design: Difficulty/resource_temporal_overlap/closed_batch_periods_need_a_strictly_greater_than_one_day_settlement_gap
    """
    _open_incumbent_batch()

    validate_error(
        api_client.create_payment_batch(
            _batch_payload("RTB-2", "WEST", AUG_16, AUG_28, SEP_20), fx.CONTROLLER
        ),
        ApiErrorId.ERR_BATCH_BUFFER_VIOLATION.value,
    )

    validate_error(
        api_client.create_payment_batch(
            _batch_payload("RTB-3", "WEST", AUG_10, AUG_20, SEP_20), fx.CONTROLLER
        ),
        ApiErrorId.ERR_BATCH_PERIOD_OVERLAP.value,
    )

    two_day_gap = validate_success(
        api_client.create_payment_batch(
            _batch_payload("RTB-4", "WEST", AUG_17, AUG_28, SEP_20), fx.CONTROLLER
        ),
        201,
    )
    a.assert_status(two_day_gap, "OPEN")
    assert two_day_gap["period_start"] == AUG_17, two_day_gap

    # A refused create wrote no row, so neither refused batch_code was consumed.
    revived = validate_success(
        api_client.create_payment_batch(
            _batch_payload("RTB-2", "SOUTH", AUG_01, AUG_10, SEP_20), fx.CONTROLLER
        ),
        201,
    )
    a.assert_status(revived, "OPEN")
    assert revived["batch_code"] == "RTB-2", revived
