"""Cross-entity state dependencies: a cycle blocked by its chamber, a load
position blocked by a qualification's audit window, and a cycle blocked by the
permit two hops away."""

import pytest

from test_helpers import (
    ApiErrorId,
    add_load_position,
    api_client,
    assert_instant_equals,
    build_cycle_scenario,
    create_cycle,
    create_load_position_payload,
    create_lot,
    get_chamber,
    get_cycle,
    get_lot,
    get_permit,
    get_qualification,
    operator,
    set_chamber_status,
    set_clock,
    set_permit_status,
    setup_reference_data,
    validate_error,
)


def test_ready_cycle_cannot_start_while_its_chamber_is_in_maintenance():
    """PRD 3.6: "The chamber must be `AVAILABLE`; one in `MAINTENANCE` or
    `DECOMMISSIONED` is refused with `ERR_CHAMBER_UNAVAILABLE`."
    PRD 3.6: "Every lot referenced by a load position of this cycle moves
    `STAGED → IN_PROCESS`."

    Design: Difficulty/cross_entity_state_dependency/cycle_start_depends_on_chamber_status
    """
    env = build_cycle_scenario(stage="ready")
    set_chamber_status(env["chamber"]["id"], "MAINTENANCE")

    response = api_client.start_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_CHAMBER_UNAVAILABLE)
    assert get_cycle(env["cycle"]["id"])["status"] == "READY"
    assert get_lot(env["lot"]["id"])["status"] == "STAGED", "the lot never advanced"
    assert get_chamber(env["chamber"]["id"])["status"] == "MAINTENANCE"


def test_ready_cycle_cannot_start_in_a_decommissioned_chamber():
    """PRD 3.6: "The chamber must be `AVAILABLE`; one in `MAINTENANCE` or
    `DECOMMISSIONED` is refused with `ERR_CHAMBER_UNAVAILABLE`."
    PRD 3.2: "The administrator may also retire it, `AVAILABLE →
    DECOMMISSIONED` or `MAINTENANCE → DECOMMISSIONED`; `DECOMMISSIONED` is
    terminal and additionally blocks scheduling any new cycle into that
    chamber, again with `ERR_CHAMBER_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/cycle_start_depends_on_chamber_status
    """
    env = build_cycle_scenario(stage="ready")
    set_chamber_status(env["chamber"]["id"], "DECOMMISSIONED")

    response = api_client.start_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_CHAMBER_UNAVAILABLE)
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "READY"
    assert cycle["operator_user_id"] is None


def _setup_lot_and_cycle_for_audit_window():
    env = setup_reference_data()
    lot = create_lot(env["customer"]["id"], env["product"]["id"])
    cycle = create_cycle(
        env["chamber"]["id"],
        env["recipe"]["id"],
        scheduled_start_at="2026-11-04T00:00:00Z",
        scheduled_end_at="2026-11-04T06:00:00Z",
    )
    env.update({"lot": lot, "cycle": cycle})
    assert_instant_equals(
        get_qualification(env["qualification"]["id"])["next_audit_due_at"],
        "2026-11-03T00:00:00Z",
        "next_audit_due_at",
    )
    return env


def test_load_position_refused_once_the_clock_reaches_the_audit_due_instant():
    """PRD 3.3: "`QUALIFIED → AUDIT_DUE` and `CONDITIONAL → AUDIT_DUE` both
    fire when the logical clock reaches `next_audit_due_at`, evaluated lazily
    at the moment the qualification is consulted during load-position creation,
    and both are also driven by the deviation cascade of §3.6; in either case
    load-position creation for that product-and-recipe pair is thereafter
    blocked with `ERR_QUALIFICATION_NOT_CURRENT`."
    PRD 2.7: "A qualification whose `next_audit_due_at` has been reached is
    first moved lazily to `AUDIT_DUE` and therefore fails here."

    Design: Difficulty/cross_entity_state_dependency/load_position_depends_on_qualification_audit_window
    """
    env = _setup_lot_and_cycle_for_audit_window()
    version = get_cycle(env["cycle"]["id"])["version"]
    set_clock("2026-11-03T00:00:00Z")

    response = api_client.create_load_position(
        env["cycle"]["id"],
        create_load_position_payload(env["lot"]["id"], version),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_QUALIFICATION_NOT_CURRENT)
    qualification = get_qualification(env["qualification"]["id"])
    assert qualification["status"] == "AUDIT_DUE"
    assert_instant_equals(
        qualification["next_audit_due_at"], "2026-11-03T00:00:00Z", "next_audit_due_at"
    )
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "PLANNED"
    assert cycle["loaded_pallet_count"] == 0
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "RECEIVED"
    assert lot["staged_pallet_count"] == 0


def test_load_position_accepted_one_day_before_the_audit_becomes_due():
    """PRD 3.5: "A `ProductQualification` must exist for the lot's product and
    the cycle's recipe with `status` `QUALIFIED` or `CONDITIONAL`, failing
    which the write is refused with `ERR_QUALIFICATION_NOT_CURRENT`."
    PRD 3.3: "`QUALIFIED → AUDIT_DUE` and `CONDITIONAL → AUDIT_DUE` both fire
    when the logical clock reaches `next_audit_due_at`, evaluated lazily at the
    moment the qualification is consulted during load-position creation, and
    both are also driven by the deviation cascade of §3.6; in either case
    load-position creation for that product-and-recipe pair is thereafter
    blocked with `ERR_QUALIFICATION_NOT_CURRENT`."

    Design: Difficulty/cross_entity_state_dependency/load_position_depends_on_qualification_audit_window
    """
    env = _setup_lot_and_cycle_for_audit_window()
    set_clock("2026-11-02T00:00:00Z")

    position = add_load_position(env["cycle"]["id"], env["lot"]["id"])

    assert position["pallet_count"] == 2
    assert get_qualification(env["qualification"]["id"])["status"] == "QUALIFIED"
    assert get_cycle(env["cycle"]["id"])["status"] == "LOADING"


def test_ready_cycle_cannot_start_under_a_suspended_permit():
    """PRD 3.6: "The permit behind the chamber must be `ACTIVE`; one that is
    `SUSPENDED` or `EXPIRED` is refused with `ERR_PERMIT_NOT_ACTIVE`."
    PRD 3.2: "while `SUSPENDED`, further cycle starts under this permit are
    refused with `ERR_PERMIT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/cycle_start_depends_on_emission_permit_status
    """
    env = build_cycle_scenario(stage="ready", modality="ETO")
    set_permit_status(env["permit"]["id"], "SUSPENDED")

    response = api_client.start_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)
    assert get_chamber(env["chamber"]["id"])["status"] == "AVAILABLE"
    permit = get_permit(env["permit"]["id"])
    assert permit["consumed_kg_ytd"] == pytest.approx(0, abs=1e-9)
    assert permit["total_emission_fee_usd"] == pytest.approx(0, abs=1e-9)
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "READY"
    assert cycle["abated_eto_kg"] == pytest.approx(0, abs=1e-9)


def test_ready_cycle_cannot_start_under_an_expired_permit():
    """PRD 3.2: "`ACTIVE → EXPIRED` and `SUSPENDED → EXPIRED` are both
    commanded by a `RegulatoryAdmin` and are permanent — there is no transition
    out of `EXPIRED`, and an `EXPIRED` permit blocks cycle starts with the same
    `ERR_PERMIT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/cycle_start_depends_on_emission_permit_status
    """
    env = build_cycle_scenario(stage="ready", modality="ETO")
    set_permit_status(env["permit"]["id"], "EXPIRED")

    response = api_client.start_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)
    assert get_cycle(env["cycle"]["id"])["status"] == "READY"
    assert get_permit(env["permit"]["id"])["consumed_kg_ytd"] == pytest.approx(0, abs=1e-9)
