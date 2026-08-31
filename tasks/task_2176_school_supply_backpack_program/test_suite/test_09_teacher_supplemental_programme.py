"""The teacher supplemental programme and its two budget caps."""

from test_helpers import (
    ApiErrorId,
    adjust_inventory,
    assert_teacher_request,
    create_cash_gift,
    create_collecting_cycle,
    create_teacher_request,
    move_school,
    move_teacher_request,
    setup_supplemental_budget,
    setup_three_active_partners,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]
WL = TEST_USERS["warehouse_lead_headers"]


def test_supplemental_cap_equality_passes(api):
    """PRD §3.8: "Whenever a cash gift is booked, the cycle's `supplemental_cap_cents`
    is recomputed as fifteen percent of its `unrestricted_gross_cents`, **floored**
    rather than rounded to a whole cent."
    PRD §3.8: "The approval passes when that committed spend plus this request's own
    `request_cost_cents` is less than or equal to `supplemental_cap_cents` — **equality
    passes**, and only a strict overshoot fails, with `ERR_SUPPLEMENTAL_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/supplemental_cap_equality_passes_then_one_more_pack_is_rejected
    """
    scene = setup_supplemental_budget(unrestricted_cents=50_000)
    request = create_teacher_request(
        scene.school_id, scene.cycle_id, scene.pencil_id, qty_requested=30
    )
    assert_teacher_request(request)
    assert request["request_cost_cents"] == 7500, "30 pencils at 250 cents"
    cycle = validate_success(api.get_drive_cycle(scene.cycle_id, PD))
    assert cycle["supplemental_cap_cents"] == 7500, "floor(50000 * 0.15)"

    approved = validate_success(move_teacher_request(request["id"], "APPROVED"))
    assert approved["status"] == "APPROVED", "0 + 7500 == 7500 must be accepted"


def test_one_more_pack_over_the_supplemental_cap_is_rejected(api):
    """PRD §3.8: "Committed spend is the sum of `request_cost_cents` over this cycle's
    requests whose `status` is `APPROVED` or `FULFILLED`; requests still `SUBMITTED`
    and requests already `DENIED` never consume budget."
    PRD §3.8: "The approval passes when that committed spend plus this request's own
    `request_cost_cents` is less than or equal to `supplemental_cap_cents` — **equality
    passes**, and only a strict overshoot fails, with `ERR_SUPPLEMENTAL_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/supplemental_cap_equality_passes_then_one_more_pack_is_rejected
    """
    scene = setup_supplemental_budget(unrestricted_cents=50_000)
    at_cap = create_teacher_request(
        scene.school_id, scene.cycle_id, scene.pencil_id,
        qty_requested=30, teacher_name="Ms Rivera",
    )
    over_cap = create_teacher_request(
        scene.school_id, scene.cycle_id, scene.pencil_id,
        qty_requested=1, teacher_name="Mr Osei", justification="One more pack",
    )
    validate_success(move_teacher_request(at_cap["id"], "APPROVED"))

    response = move_teacher_request(over_cap["id"], "APPROVED")
    validate_error(
        response, ApiErrorId.ERR_SUPPLEMENTAL_CAP_EXCEEDED.value, expected_status=409
    )

    reread = validate_success(api.get_teacher_request(over_cap["id"], PD))
    assert reread["status"] == "SUBMITTED"
    assert reread["request_cost_cents"] == 250


def test_inactive_partnership_is_reported_ahead_of_the_supplemental_cap(api):
    """PRD §3.8: "It requires the request to be `SUBMITTED`, requires the governing
    school's `partnership_status` to be `ACTIVE` (`ERR_SCHOOL_PARTNERSHIP_INACTIVE`),
    and requires the governing cycle to be in `COLLECTING`, `SORTING` or `DISTRIBUTION`
    (`ERR_CYCLE_PHASE_INVALID`)."
    PRD §2.7: "13. Governing school partnership is `ACTIVE`. This guards four
    operations — publishing or retiring a needs list, creating a distribution event,
    publishing a distribution event, and approving a teacher request. Otherwise
    `ERR_SCHOOL_PARTNERSHIP_INACTIVE`, 409."

    Design: Difficulty/priority_pair_validation_conflict/school_partnership_referential_beats_supplemental_cap
    """
    scene = setup_supplemental_budget(unrestricted_cents=50_000)
    request = create_teacher_request(
        scene.school_id, scene.cycle_id, scene.pencil_id, qty_requested=100
    )
    validate_success(move_school(scene.school_id, "SUSPENDED"))

    response = move_teacher_request(request["id"], "APPROVED")
    validate_error(
        response, ApiErrorId.ERR_SCHOOL_PARTNERSHIP_INACTIVE.value, expected_status=409
    )

    assert validate_success(api.get_teacher_request(request["id"], PD))["status"] == "SUBMITTED"


def test_the_supplemental_cap_never_masks_the_partnership_rule(api):
    """PRD §2.7: "31. Cycle supplemental cap when a teacher request is approved —
    `ERR_SUPPLEMENTAL_CAP_EXCEEDED`, 409."
    PRD §3.8: "On creation the server computes `request_cost_cents` as `qty_requested`
    multiplied by the item's `unit_cost_cents`, and files the request in `SUBMITTED`
    with `approved_at` null."

    Design: Difficulty/priority_pair_validation_conflict/school_partnership_referential_beats_supplemental_cap
    """
    scene = setup_supplemental_budget(unrestricted_cents=50_000)
    request = create_teacher_request(
        scene.school_id, scene.cycle_id, scene.pencil_id, qty_requested=100
    )
    assert request["request_cost_cents"] == 25_000
    cycle = validate_success(api.get_drive_cycle(scene.cycle_id, PD))
    assert cycle["supplemental_cap_cents"] == 7500, (
        "the request would also breach the cap, so both rules are unsatisfied"
    )
    validate_success(move_school(scene.school_id, "SUSPENDED"))

    response = move_teacher_request(request["id"], "APPROVED")
    error = response.json()["data"]
    assert error["error_id"] != ApiErrorId.ERR_SUPPLEMENTAL_CAP_EXCEEDED.value, (
        "the fiscal rule sits below the partnership rule in the ladder"
    )
    assert error["error_id"] == ApiErrorId.ERR_SCHOOL_PARTNERSHIP_INACTIVE.value


def test_per_school_sub_cap_activates_once_three_partners_are_active(api):
    """PRD §3.8: "Count the schools whose `partnership_status` is `ACTIVE` and that have
    at least one needs list in `PUBLISHED`."
    PRD §3.8: "If the count is three or more, the sub-cap activates: the per-school
    ceiling is forty percent of `supplemental_cap_cents`, again floored rather than
    rounded to a whole cent, and the approval passes only when the sum of
    `request_cost_cents` over this cycle's requests belonging to the **same**
    `school_id` with `status` in `APPROVED` or `FULFILLED`, plus this request's own
    `request_cost_cents`, is less than or equal to that ceiling."
    PRD §3.8: "Equality passes here too; a strict overshoot is
    `ERR_SCHOOL_SUBCAP_EXCEEDED`."

    Design: Corner/calculations/per_school_subcap_activates_once_three_partners_are_active
    """
    partners = setup_three_active_partners()
    cycle = create_collecting_cycle()
    create_cash_gift(
        cycle["id"], donor_name="Acme Corp", amount_cents=50_000, restriction_type="UNRESTRICTED"
    )
    first_school = partners.schools[0]
    request = create_teacher_request(
        first_school["id"], cycle["id"], partners.pencil_id, qty_requested=13
    )
    assert request["request_cost_cents"] == 3250
    assert validate_success(api.get_drive_cycle(cycle["id"], PD))["supplemental_cap_cents"] == 7500

    response = move_teacher_request(request["id"], "APPROVED")
    validate_error(response, ApiErrorId.ERR_SCHOOL_SUBCAP_EXCEEDED.value, expected_status=409)

    assert validate_success(api.get_teacher_request(request["id"], PD))["status"] == "SUBMITTED"


def test_a_denied_request_cannot_later_be_approved(api):
    """PRD §3.8: "`DENIED` and `FULFILLED` are both terminal, and a request move not
    declared from the request's current `status` is rejected with
    `ERR_INVALID_TEACHER_REQUEST_STATE`."
    PRD §3.8: "A `ProgramDirector` may instead move a `SUBMITTED` request to `DENIED`,
    which requires only that it be `SUBMITTED` and which increments the request's
    `version` by 1."

    Design: Corner/state_machines/denied_teacher_request_cannot_later_be_approved
    """
    scene = setup_supplemental_budget(unrestricted_cents=50_000)
    request = create_teacher_request(
        scene.school_id, scene.cycle_id, scene.pencil_id, qty_requested=10
    )
    validate_success(move_teacher_request(request["id"], "DENIED"))

    response = move_teacher_request(request["id"], "APPROVED")
    validate_error(
        response, ApiErrorId.ERR_INVALID_TEACHER_REQUEST_STATE.value, expected_status=409
    )

    reread = validate_success(api.get_teacher_request(request["id"], PD))
    assert reread["status"] == "DENIED"
    assert reread["approved_at"] is None


def test_fulfilment_requires_a_covering_inventory_position(api):
    """PRD §3.8: "Fulfilment belongs to the `WarehouseLead`: an `APPROVED` request moves
    to `FULFILLED` provided the inventory position for the request's `drive_cycle_id`
    and `supply_item_id` has an `on_hand_qty` of at least `qty_requested`, failing
    otherwise with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Difficulty/cross_entity_state_dependency/teacher_request_fulfilment_requires_covering_inventory_position
    """
    scene = setup_supplemental_budget(unrestricted_cents=50_000)
    adjust_inventory(scene.cycle_id, scene.pencil_id, 10)
    request = create_teacher_request(
        scene.school_id, scene.cycle_id, scene.pencil_id, qty_requested=30
    )
    validate_success(move_teacher_request(request["id"], "APPROVED"))

    response = move_teacher_request(request["id"], "FULFILLED", headers=WL)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, expected_status=409)

    assert validate_success(api.get_teacher_request(request["id"], PD))["status"] == "APPROVED"


def test_a_refused_fulfilment_leaves_the_position_untouched(api):
    """PRD §3.8: "Fulfilment subtracts `qty_requested` from `on_hand_qty` and adds it to
    `distributed_qty`, recomputes the cycle's `total_items_on_hand`, and increments
    `version` by 1 on the request, the position and the cycle."
    PRD §3.8: "Fulfilment belongs to the `WarehouseLead`: an `APPROVED` request moves to
    `FULFILLED` provided the inventory position for the request's `drive_cycle_id` and
    `supply_item_id` has an `on_hand_qty` of at least `qty_requested`, failing
    otherwise with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Difficulty/cross_entity_state_dependency/teacher_request_fulfilment_requires_covering_inventory_position
    """
    scene = setup_supplemental_budget(unrestricted_cents=50_000)
    position = adjust_inventory(scene.cycle_id, scene.pencil_id, 10)
    request = create_teacher_request(
        scene.school_id, scene.cycle_id, scene.pencil_id, qty_requested=30
    )
    validate_success(move_teacher_request(request["id"], "APPROVED"))

    move_teacher_request(request["id"], "FULFILLED", headers=WL)

    reread = validate_success(api.get_inventory_position(position["id"], WL))
    assert reread["on_hand_qty"] == 10, "no units may leave the shelf on a refused fulfilment"
    assert reread["distributed_qty"] == 0
