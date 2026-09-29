"""Two contended resources under two different interval conventions: a pasture whose
half-open windows only collide when they genuinely intersect, and an allotment whose closure
orders are closed at both ends and carry a one-sided forward buffer."""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    assert_pct,
    make_officer_headers,
    make_specialist_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    add_use_record,
    allotment_with_pasture,
    create_aoi,
    create_closure_order,
    create_permit,
    get_allotment,
    get_aoi,
    issue_permit,
    lift_closure_order,
    permittee_with_base_property,
)


def _overlap_setup():
    """A 300-AUM pasture already carrying one 206.67-AUM leg over [2026-04-01, 2026-05-02)."""
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                  required_pasture_rotation_count=1, acres=24000)
    holder = permittee_with_base_property(carrying_capacity_aums=600)
    permit = issue_permit(create_permit(
        land["allotment"]["id"], holder["permittee"]["id"], holder["base_property"]["id"],
        requested_aums=500)["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=500,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    first = add_use_record(aoi["id"], land["pasture"]["id"], planned_head_count=200,
                           livestock_kind="CATTLE", planned_entry_date="2026-04-01",
                           planned_exit_date="2026-05-02")
    assert_aums(first["planned_aums"], 206.67)
    return {"allotment": land["allotment"], "pasture": land["pasture"], "permit": permit,
            "aoi": aoi, "first": first}


def _leg(setup, entry, exit_date, head):
    return f.use_record_payload(setup["pasture"]["id"], planned_entry_date=entry,
                                planned_exit_date=exit_date, planned_head_count=head,
                                livestock_kind="CATTLE")


def test_legs_that_overlap_by_eighteen_days_are_summed_against_the_pasture_capacity():
    """A second leg of 100 head over [2026-04-15, 2026-05-16) intersects the standing
    206.67-AUM leg, so the temporal aggregate is 206.67 + 103.33 = 310.00 AUMs against a
    300-AUM pasture and the request is refused with ERR_PASTURE_CAPACITY_EXCEEDED; nothing is
    stored, so the instruction's planned total is still 206.67.

    PRD 3.4: "For the pasture named by a new or newly reported leg, sum `planned_aums` over every
    use record on that pasture whose half-open planned window **intersects** the window of the leg
    under evaluation — records belonging to any operating instruction of the same `grazing_year`
    count, and the leg under evaluation is included in its own sum."
    PRD 3.4: "If that sum exceeds the pasture's `pasture_aum_capacity`, the request is refused
    with `ERR_PASTURE_CAPACITY_EXCEEDED`."
    PRD 3.4: "Multiply the head count by the animal-unit equivalent of the livestock kind, which
    is 1.0 for `CATTLE`, 0.2 for `SHEEP` and 1.25 for `HORSES`."
    PRD 3.4: "Round the result half-up to 2 decimal places, exactly once."

    Design: Difficulty/resource_temporal_overlap/pasture_half_open_interval_capacity_aggregate
    """
    setup = _overlap_setup()

    validate_error(
        api_client.create_use_record(setup["aoi"]["id"],
                                     _leg(setup, "2026-04-15", "2026-05-16", 100),
                                     make_specialist_headers()),
        ApiErrorId.ERR_PASTURE_CAPACITY_EXCEEDED, 422)

    aoi = get_aoi(setup["aoi"]["id"])
    assert_aums(aoi["planned_aums_total"], 206.67)  # the refused leg was never stored
    assert aoi["distinct_pasture_count"] == 1
    assert aoi["aoi_status"] == "DRAFT"


def test_a_leg_touching_the_first_legs_exit_date_does_not_intersect_it():
    """[2026-05-02, 2026-06-01) begins exactly where the standing leg ends, so the two are never
    aggregated: 200 head are accepted at 200.00 AUMs even though the pasture's yearly scheduled
    total then reaches 406.67 on a 300-AUM pasture — capacity is temporal, never an annual sum.

    PRD 3.4: "Two legs that merely touch, where one's exit date equals the other's entry date, do
    not intersect and are never aggregated together; two legs that overlap by even a single day
    are."
    PRD 3.4: "Pasture capacity is enforced as a temporal aggregate rather than a running total,
    and this is where the half-open convention earns its keep."
    PRD 3.4: "Once the leg is stored, the instruction's `planned_aums_total` is recomputed as the
    sum of `planned_aums` over **all** of its use records regardless of `record_status`, its
    `distinct_pasture_count` as the number of distinct `pasture_id` values across all of those
    records, and the named pasture's `scheduled_aums` roll-up is refreshed."

    Design: Difficulty/resource_temporal_overlap/pasture_half_open_interval_capacity_aggregate
    """
    setup = _overlap_setup()

    touching = get_success_data(api_client.create_use_record(
        setup["aoi"]["id"], _leg(setup, "2026-05-02", "2026-06-01", 200),
        make_specialist_headers()), 201)
    assert_aums(touching["planned_aums"], 200.00)  # 30 whole days; the exit day is not grazed
    assert touching["record_status"] == "SCHEDULED"

    aoi = get_aoi(setup["aoi"]["id"])
    assert_aums(aoi["planned_aums_total"], 406.67)
    assert aoi["distinct_pasture_count"] == 1, "both legs name the same pasture"


def test_moving_the_touching_leg_one_day_earlier_makes_it_an_intersection():
    """The same 200-head leg shifted one day back to [2026-05-01, 2026-05-31) shares 2026-05-01
    with the standing leg, so the aggregate becomes 206.67 + 200.00 = 406.67 AUMs and the very
    request that succeeded a day later is refused.

    PRD 3.4: "The window is **half-open**: grazing is counted from `planned_entry_date` up to but
    not including `planned_exit_date`, so the exit day itself is not grazed and a window whose
    exit equals its entry is never valid."
    PRD 2.6: "**Pasture capacity** — `ERR_PASTURE_CAPACITY_EXCEEDED`, HTTP 422, on use-record
    scheduling and on actual-use reporting. Evaluated as a temporal aggregate, as specified in
    §3.4."

    Design: Difficulty/resource_temporal_overlap/pasture_half_open_interval_capacity_aggregate
    """
    setup = _overlap_setup()

    validate_error(
        api_client.create_use_record(setup["aoi"]["id"],
                                     _leg(setup, "2026-05-01", "2026-05-31", 200),
                                     make_specialist_headers()),
        ApiErrorId.ERR_PASTURE_CAPACITY_EXCEEDED, 422)

    assert_aums(get_aoi(setup["aoi"]["id"])["planned_aums_total"], 206.67)


def _buffer_setup():
    """An allotment held by an ACTIVE 0.30 drought order running 2026-08-05..2026-08-31."""
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                  required_pasture_rotation_count=1, acres=24000)
    order = create_closure_order(
        land["allotment"]["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.30,
        effective_start_date="2026-08-05", effective_end_date="2026-08-31",
        justification="Thirty percent drought reduction for the late summer period.")
    assert order["order_status"] == "ACTIVE"
    allotment = get_allotment(land["allotment"]["id"])
    assert allotment["effective_capacity_aums"] == 840
    return {"allotment": allotment, "order": order}


def _order_body(setup, start, end="2026-10-31", reduction_pct=0.20):
    return f.closure_order_payload(
        setup["allotment"]["id"], order_type="DROUGHT_REDUCTION",
        reduction_pct=reduction_pct, effective_start_date=start, effective_end_date=end,
        justification="Extended reduction while forage recovers.")


def _post_order(setup, start, **kwargs):
    return api_client.create_closure_order(_order_body(setup, start, **kwargs),
                                           make_officer_headers())


def test_a_new_order_inside_the_seven_day_forward_buffer_is_refused():
    """2026-09-07 is the seventh day after the standing order's 2026-08-31 end, so it falls
    within the buffer and is refused with ERR_CLOSURE_ORDER_OVERLAP; a start on the closed end
    itself and a start inside the standing interval are refused for the same reason, and none of
    the three rejections runs a cascade.

    PRD 2.6: "Formally the new order is refused whenever its `effective_start_date` falls on or
    before the existing order's `effective_end_date` plus seven days; a start on the eighth day
    after that end is accepted."
    PRD 2.6: "Both endpoints of both intervals are inclusive, so intervals that merely touch do
    overlap."
    PRD 3.10: "Concretely: with an active order ending on a given day, a new order starting on
    that day itself overlaps, because both intervals are inclusive and touching ends collide; a
    new order starting on any of the following 7 days is inside the buffer and is refused; a new
    order starting on the eighth day after that end date is accepted."

    Design: Difficulty/resource_temporal_overlap/closure_order_closed_interval_with_forward_buffer
    """
    setup = _buffer_setup()

    validate_error(_post_order(setup, "2026-09-07"),
                   ApiErrorId.ERR_CLOSURE_ORDER_OVERLAP, 409)
    validate_error(_post_order(setup, "2026-08-31"),
                   ApiErrorId.ERR_CLOSURE_ORDER_OVERLAP, 409)
    validate_error(_post_order(setup, "2026-08-20"),
                   ApiErrorId.ERR_CLOSURE_ORDER_OVERLAP, 409)

    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.30)
    assert allotment["allotment_status"] == "RESTRICTED"
    assert allotment["effective_capacity_aums"] == 840, "no rejected order moved the cascade"


def test_the_eighth_day_after_the_end_clears_the_buffer_and_the_stronger_source_still_wins():
    """A start of 2026-09-08 is one day past the buffer and is accepted, and the weaker 0.20
    reduction it carries does not disturb the posture: the maximum over ACTIVE sources is still
    0.3000 and capacity is still 840, never 0.50 and never 600.

    PRD 3.10: "Otherwise it is the **maximum** over two families of contributors: the
    `reduction_pct` of every closure order on the allotment in `order_status` `ACTIVE`, and the
    `adjustment_pct` of every permit decision on the allotment with `decision_type`
    `STOCKING_ADJUSTMENT` and `decision_status` `EFFECTIVE`."
    PRD 3.10: "Contributors are **never summed**: a 0.40 drought reduction standing beside a 0.30
    effective stocking adjustment yields 0.40, not 0.70."

    Design: Difficulty/resource_temporal_overlap/closure_order_closed_interval_with_forward_buffer
    """
    setup = _buffer_setup()

    accepted = get_success_data(_post_order(setup, "2026-09-08"), 201)
    assert accepted["order_status"] == "ACTIVE"
    assert_pct(accepted["reduction_pct"], 0.20)

    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.30)
    assert allotment["effective_capacity_aums"] == 840
    assert allotment["allotment_status"] == "RESTRICTED"


def test_lifting_the_standing_order_frees_its_window_immediately():
    """Once the first order is LIFTED it constrains nothing, so the 2026-08-31 start that was
    refused a moment earlier is accepted and its own 0.20 reduction becomes the only surviving
    source.

    PRD 3.10: "Orders in `order_status` `LIFTED` or `EXPIRED` constrain nothing, so a lifted
    order's interval may be immediately re-covered."
    PRD 3.10: "Orders in `order_status` `LIFTED` or `EXPIRED` contribute nothing, and decisions in
    `decision_status` `DRAFT`, `PROPOSED`, `FINAL`, `STAYED` or `VACATED` contribute nothing."

    Design: Difficulty/resource_temporal_overlap/closure_order_closed_interval_with_forward_buffer
    """
    setup = _buffer_setup()
    validate_error(_post_order(setup, "2026-08-31"),
                   ApiErrorId.ERR_CLOSURE_ORDER_OVERLAP, 409)

    lifted = lift_closure_order(setup["order"]["id"])
    assert lifted["order_status"] == "LIFTED"
    assert_pct(get_allotment(setup["allotment"]["id"])["stocking_adjustment_pct"], 0.0)

    accepted = get_success_data(_post_order(setup, "2026-08-31"), 201)
    assert accepted["order_status"] == "ACTIVE"

    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.20)
    assert allotment["allotment_status"] == "RESTRICTED"
    assert allotment["effective_capacity_aums"] == 960
