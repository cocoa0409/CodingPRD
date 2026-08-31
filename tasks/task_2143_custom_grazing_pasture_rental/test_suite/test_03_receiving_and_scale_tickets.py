"""Receiving cattle, pencil shrink, scale tickets and the weigh-out guards."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_weight_event,
    is_valid_uuid,
    make_grazier_headers,
    read_lot,
    read_pasture,
    receive_payload,
    record_treatment,
    report_death_loss,
    review_death_loss_as_consultant,
    setup_north_bench_active_contract,
    setup_north_bench_lot_on_feed,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Pencil shrink is applied once, at the lot level
# ===========================================================================

def test_receiving_applies_the_pencil_shrink_to_the_lot_level_gross_weight(api):
    """PRD 3.4: "The shrunk figure is computed once, at the lot level: the ticket's
    gross weight is multiplied by one minus the applicable shrink percentage divided by
    100, and that single product is rounded half up to a whole pound and stored as
    `shrunk_weight_lbs`."
    PRD 3.4: "The order here is pinned and it is not merely a style preference — a
    63745-pound gross ticket on 150 head at 3.5 percent shrink yields 61514 pounds.
    Dividing the gross by the head count, shrinking the per-head figure, rounding it and
    multiplying back would give 61500 pounds, and that answer is wrong by 14 pounds."

    Design: Difficulty/combinatorial_formula/shrunk_weight_lot_level_rounding_order_mode_b
    """
    world = setup_north_bench_active_contract()
    lot = validate_success(
        api.create_lot(
            world.contract_id,
            {"scheduled_head_count": 150, "scheduled_delivery_date": "2026-08-10"},
            make_grazier_headers(world.grazier_id),
        ),
        201,
    )

    resp = api.receive_lot(
        lot["id"], receive_payload(), make_grazier_headers(world.grazier_id)
    )
    received = validate_success(resp, 200)

    assert received["gross_weight_in_lbs"] == pytest.approx(63745)
    assert received["shrunk_weight_in_lbs"] == 61514, (
        "The per-head-then-multiply order would have produced 61500"
    )
    assert received["head_count_received"] == 150
    assert received["status"] == "ON_FEED"
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 150


def test_the_in_scale_ticket_records_the_applied_shrink_and_the_shrunk_weight(api):
    """PRD 3.4: "Pencil shrink is a discount off the scale, and which discount applies
    depends on which end of the season the ticket comes from: an `IN` ticket takes the
    contract's `shrink_pct`, while `INTERIM` and `OUT` tickets take its
    `out_shrink_pct`. Whichever applies is recorded on the weight record as
    `shrink_pct_applied`."
    PRD 3.4: "Receiving writes an accompanying weight record with `event_type` `IN`
    carrying that ticket, copies the head and gross weight onto the lot as
    `head_count_received` and `gross_weight_in_lbs`, stamps `in_date` from the weigh
    time, computes `shrunk_weight_in_lbs`, recomputes the pasture's
    `stocked_head_count`, and increments the lot's `version`."

    Design: Difficulty/combinatorial_formula/shrunk_weight_lot_level_rounding_order_mode_b
    """
    world = setup_north_bench_lot_on_feed()

    events, meta = validate_paginated(
        api.list_weight_events(
            world.lot_id, make_grazier_headers(world.grazier_id), params={"event_type": "IN"}
        )
    )
    assert meta["total_count"] == 1
    in_event = events[0]
    assert_weight_event(in_event)

    assert in_event["event_type"] == "IN"
    assert in_event["shrink_pct_applied"] == pytest.approx(3.5)
    assert in_event["shrunk_weight_lbs"] == 61514
    assert_same_instant(world.lot["in_date"], "2026-08-10T09:00:00Z", "CattleLot.in_date")


def test_the_receiving_weight_record_is_server_minted_and_bound_to_its_lot(api):
    """PRD 2.4: "Every resource the API creates is addressed by an `id` that the server
    mints as a UUID."
    PRD 2.4: "Identifiers carry no type prefix; a settlement id and a pasture id are
    indistinguishable by shape, and clients must never parse them."
    PRD 3.4: "Interim and weigh-out tickets are posted directly against the lot, each
    stating its `event_type`, `gross_weight_lbs`, `head_count`, `scale_ticket_ref` and
    `weighed_at`."

    Design: Corner/entities/weight_event_identity_and_shrink_fields_are_server_minted
    """
    world = setup_north_bench_lot_on_feed()

    events, meta = validate_paginated(
        api.list_weight_events(world.lot_id, make_grazier_headers(world.grazier_id))
    )
    assert meta["total_count"] == 1, "Receiving writes exactly one accompanying record"
    in_event = events[0]

    assert is_valid_uuid(in_event["id"]), "The weight record's id is a server-minted UUID"
    assert "_" not in in_event["id"] and ":" not in in_event["id"], (
        "Identifiers carry no type prefix"
    )
    assert in_event["lot_id"] == world.lot_id
    assert in_event["event_type"] == "IN"
    assert in_event["shrink_pct_applied"] == pytest.approx(3.5)
    assert in_event["shrunk_weight_lbs"] == 61514


def test_receiving_a_lot_a_second_time_is_refused(api):
    """PRD 3.4: "A lot sitting in `RECEIVING_HELD` cannot be received either, since the
    transition is declared only from `SCHEDULED`; that attempt is `ERR_LOT_INVALID_STATE`."
    PRD 2.9: "Its `stocked_head_count` is the sum, over the lots on that pasture whose
    `status` is `ON_FEED` or `REMOVAL_SCHEDULED`, of the head received on the lot less
    the head confirmed dead on it."

    Design: Corner/state_machines/receiving_a_lot_twice_rejects_the_second_delivery
    """
    world = setup_north_bench_lot_on_feed()

    resp = api.receive_lot(
        world.lot_id,
        {
            "head_count_received": 20, "gross_weight_lbs": 9000,
            "scale_ticket_ref": "T-DUP", "received_at": "2026-08-11T09:00:00Z",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_LOT_INVALID_STATE.value, 409)

    _, meta = validate_paginated(
        api.list_weight_events(world.lot_id, make_grazier_headers(world.grazier_id))
    )
    assert meta["total_count"] == 1, "No second IN record was written"
    assert read_lot(world.lot_id, world.grazier_id)["head_count_received"] == 150
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 150


def test_posting_an_in_scale_ticket_directly_is_a_validation_failure(api):
    """PRD 3.4: "Only `INTERIM` and `OUT` may be posted this way — an attempt to post an
    `IN` ticket is a body-validation failure — and every such record carries the
    `lot_id` of the lot it belongs to."
    PRD 2.8: "Ranges include: `acres` greater than 0; `utilization_pct` greater than 0
    and no greater than 60; `shrink_pct` and `out_shrink_pct` between 0 and 10
    inclusive; `drought_index` between 0 and 5 inclusive; head counts and weights
    greater than 0; and the `event_type` supplied when recording a scale ticket
    restricted to `INTERIM` or `OUT`, since the `IN` ticket is created by receiving
    rather than posted directly."

    Design: Corner/validations/weight_event_endpoint_rejects_event_type_in
    """
    world = setup_north_bench_lot_on_feed()

    resp = api.create_weight_event(
        world.lot_id,
        {
            "event_type": "IN", "gross_weight_lbs": 60000, "head_count": 150,
            "scale_ticket_ref": "T-IN2", "weighed_at": "2026-08-11T09:00:00Z",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)

    _, meta = validate_paginated(
        api.list_weight_events(
            world.lot_id, make_grazier_headers(world.grazier_id), params={"event_type": "IN"}
        )
    )
    assert meta["total_count"] == 1, "No second IN record was written"


# ===========================================================================
# The drug-withdrawal interval is closed at both ends
# ===========================================================================

def test_weighing_out_on_the_last_withdrawal_day_is_refused(api):
    """PRD 3.5: "Separately, every treatment that is `RECORDED`, `DISPUTED` or
    `APPROVED` projects a drug-withdrawal interval running from its `treatment_date`
    through its `treatment_date` plus its `withdrawal_days`, and that interval is closed
    at both ends — a weigh-out on the treatment date itself and a weigh-out on the last
    day of the withdrawal period are both inside it. An `OUT` scale ticket whose
    `weighed_at` falls inside any such interval on the lot is refused with
    `ERR_WITHDRAWAL_PERIOD_ACTIVE`, because those cattle cannot lawfully go to market
    yet."

    Design: Difficulty/resource_temporal_overlap/withdrawal_interval_closed_inclusive_blocks_out_weigh_on_its_last_day
    """
    world = setup_north_bench_lot_on_feed()
    record_treatment(
        world.lot_id, world.grazier_id, protocol_code="PINK-EYE",
        classification="THERAPEUTIC", treatment_date="2026-09-20", withdrawal_days=14,
        head_treated=4, drug_cost_cents=4500, labor_cost_cents=1200,
    )

    resp = api.create_weight_event(
        world.lot_id,
        {
            "event_type": "OUT", "gross_weight_lbs": 70000, "head_count": 150,
            "scale_ticket_ref": "T-EARLY", "weighed_at": "2026-10-04T09:00:00Z",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_PERIOD_ACTIVE.value, 409)

    still_on_feed = read_lot(world.lot_id, world.grazier_id)
    assert still_on_feed["status"] == "ON_FEED"
    assert still_on_feed["days_on_feed"] == 0


def test_weighing_out_the_day_after_the_withdrawal_interval_succeeds(api):
    """PRD 3.5: "Separately, every treatment that is `RECORDED`, `DISPUTED` or
    `APPROVED` projects a drug-withdrawal interval running from its `treatment_date`
    through its `treatment_date` plus its `withdrawal_days`, and that interval is closed
    at both ends — a weigh-out on the treatment date itself and a weigh-out on the last
    day of the withdrawal period are both inside it."
    PRD 3.4: "It sets `head_count_out`, `gross_weight_out_lbs`, `shrunk_weight_out_lbs`
    and `out_date` on the lot, computes `days_on_feed` as the whole days from `in_date`
    to `out_date` with the fraction discarded, recomputes the pasture's
    `stocked_head_count`, and increments the lot's `version`."

    Design: Difficulty/resource_temporal_overlap/withdrawal_interval_closed_inclusive_blocks_out_weigh_on_its_last_day
    """
    world = setup_north_bench_lot_on_feed()
    record_treatment(
        world.lot_id, world.grazier_id, protocol_code="PINK-EYE",
        classification="THERAPEUTIC", treatment_date="2026-09-20", withdrawal_days=14,
        head_treated=4, drug_cost_cents=4500, labor_cost_cents=1200,
    )

    resp = api.create_weight_event(
        world.lot_id,
        {
            "event_type": "OUT", "gross_weight_lbs": 70000, "head_count": 150,
            "scale_ticket_ref": "T-OK", "weighed_at": "2026-10-05T09:00:00Z",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_success(resp, 201)

    lot = read_lot(world.lot_id, world.grazier_id)
    assert lot["status"] == "WEIGHED_OUT"
    assert lot["head_count_out"] == 150
    assert lot["shrunk_weight_out_lbs"] == 70000, "out_shrink_pct is 0 on this contract"
    assert lot["days_on_feed"] == 56
    assert_same_instant(lot["out_date"], "2026-10-05T09:00:00Z", "CattleLot.out_date")


# ===========================================================================
# Competing failures on the same weigh-out request
# ===========================================================================

def test_the_withdrawal_gate_is_reported_ahead_of_the_head_count_failure(api):
    """PRD 3.4: "Two guards stand in front of a weigh-out, and they are checked in the
    order given in §2.8. The first is the drug-withdrawal gate described in §3.5."
    PRD 2.8: "Rules are evaluated in a fixed ascending priority order and the **first**
    failing rule determines the response; no later rule is evaluated once one has
    failed."

    Design: Difficulty/priority_pair_validation_conflict/out_weigh_withdrawal_safety_beats_head_count_constraint
    """
    world = setup_north_bench_lot_on_feed()
    record_treatment(
        world.lot_id, world.grazier_id, protocol_code="PINK-EYE",
        classification="THERAPEUTIC", treatment_date="2026-09-20", withdrawal_days=14,
        head_treated=4, drug_cost_cents=4500, labor_cost_cents=1200,
    )
    report = report_death_loss(
        world.lot_id, world.grazier_id,
        death_date="2026-09-05", head_lost=5, cause="DISEASE",
    )
    review_death_loss_as_consultant(report["id"], world.consultant_id, "CONFIRM")

    resp = api.create_weight_event(
        world.lot_id,
        {
            "event_type": "OUT", "gross_weight_lbs": 70000, "head_count": 150,
            "scale_ticket_ref": "T-BAD", "weighed_at": "2026-10-04T09:00:00Z",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_PERIOD_ACTIVE.value, 409)

    lot = read_lot(world.lot_id, world.grazier_id)
    assert lot["status"] == "ON_FEED"
    assert lot["confirmed_death_head"] == 5
    assert lot["days_on_feed"] == 0


def test_the_head_count_failure_surfaces_once_the_withdrawal_gate_is_clear(api):
    """PRD 3.4: "The second is arithmetic honesty about head: the `head_count` on an
    `OUT` ticket may not exceed the head received on the lot less the head confirmed
    dead on it, and a request that claims more head walked off than were ever alive is
    rejected with `ERR_HEAD_COUNT_INCONSISTENT`."
    PRD 2.9: "On the lot side, `confirmed_death_head` is the sum of head lost across the
    lot's confirmed death-loss reports, and `days_on_feed` is the whole number of days
    from the `in_date` to the `out_date`, computed by discarding any fractional
    remainder and left at 0 until the weigh-out lands."

    Design: Difficulty/priority_pair_validation_conflict/out_weigh_withdrawal_safety_beats_head_count_constraint
    """
    world = setup_north_bench_lot_on_feed()
    record_treatment(
        world.lot_id, world.grazier_id, protocol_code="PINK-EYE",
        classification="THERAPEUTIC", treatment_date="2026-09-20", withdrawal_days=14,
        head_treated=4, drug_cost_cents=4500, labor_cost_cents=1200,
    )
    report = report_death_loss(
        world.lot_id, world.grazier_id,
        death_date="2026-09-05", head_lost=5, cause="DISEASE",
    )
    review_death_loss_as_consultant(report["id"], world.consultant_id, "CONFIRM")

    resp = api.create_weight_event(
        world.lot_id,
        {
            "event_type": "OUT", "gross_weight_lbs": 70000, "head_count": 150,
            "scale_ticket_ref": "T-BAD2", "weighed_at": "2026-10-05T09:00:00Z",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_HEAD_COUNT_INCONSISTENT.value, 422)

    lot = read_lot(world.lot_id, world.grazier_id)
    assert lot["status"] == "ON_FEED"
    assert lot["confirmed_death_head"] == 5
