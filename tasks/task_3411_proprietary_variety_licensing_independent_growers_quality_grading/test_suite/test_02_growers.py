"""Grower lifecycle: suspend cascade selectivity, exit gates, exit cascade."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_grower_payload, create_agreement_payload,
    set_clock, create_grower, suspend_grower, exit_grower,
    create_released_variety, create_active_agreement, apply_for_agreement,
    create_plant_lot, plan_planting, get_agreement, get_planting,
    get_plant_lot, setup_planting_confirmed,
    make_grower_principal_headers, get_success_data,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_grower_exited_terminal_lockdown(api):
    """PRD section 3.2: "`EXITED` is terminal; plantings already in the ground
    are precisely what the first blocker protects, so the network never strands
    living plants."
    PRD section 2.8: "the generic `ERR_INVALID_STATE` (which covers
    terminal-state lockdown and repeated transitions)".

    Design: Corner/state_machines/grower_exited_terminal_lockdown
    """
    set_clock("2026-06-01T00:00:00Z")
    grower = create_grower()
    exited = exit_grower(grower["id"])
    assert exited["status"] == "EXITED"
    resp = api.suspend_grower(grower["id"], COMPLIANCE, {"reason": "too late"})
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp2 = api.exit_grower(grower["id"], COMPLIANCE)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
    # The PRD endpoint table exposes no GET for growers; the observable
    # lockdown evidence is the exit response plus both rejected transitions.
    assert exited["exited_at"] is not None


def test_suspend_cascade_suspends_only_active_agreements(api):
    """PRD section 3.2: "Suspension moves the grower `ACTIVE → SUSPENDED`,
    stamps `suspended_at` from the logical clock, increments the grower's
    `version` by 1, and cascades exactly one link: every agreement of this
    grower that is `ACTIVE` moves to `SUSPENDED`, with each such agreement
    incrementing its own `version` by 1."

    Design: Corner/cross_cutting/suspend_cascade_suspends_only_active_agreements
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower()
    agreement = create_active_agreement(grower, variety)  # version 2, ACTIVE
    headers = make_grower_principal_headers(grower["id"])
    pending = get_success_data(api.create_agreement(
        create_agreement_payload(
            grower["id"], variety["id"], max_planting_units=500,
            cultural_practice_codes=["ORGANIC"],
            effective_from="2028-01-01T00:00:00Z",
            effective_to="2028-12-31T00:00:00Z"),
        headers))
    assert pending["status"] == "PENDING_REVIEW"
    suspended = suspend_grower(grower["id"], reason="compliance investigation")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspended_at"] is not None
    assert suspended["version"] == 2
    a1 = get_agreement(agreement["id"])
    assert a1["status"] == "SUSPENDED"
    assert a1["version"] == 3, "create 1, decide 2, cascade 3"
    a1b = get_agreement(pending["id"])
    assert a1b["status"] == "PENDING_REVIEW"
    assert a1b["version"] == 1, "the cascade touches only ACTIVE agreements"


def test_exit_blocked_by_live_plantings(api):
    """PRD section 3.2: "If any planting reachable through the grower's
    agreements is `PLANTED` or `HARVESTING`, the exit is rejected with
    `ERR_GROWER_HAS_LIVE_PLANTINGS`".

    Design: Corner/errors/exit_blocked_by_live_plantings
    """
    bundle = setup_planting_confirmed()  # planting PLANTED, no harvest lots
    resp = api.exit_grower(bundle["grower"]["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_GROWER_HAS_LIVE_PLANTINGS)
    agreement = get_agreement(bundle["agreement"]["id"])
    assert agreement["status"] == "ACTIVE"
    planting = get_planting(bundle["planting"]["id"])
    assert planting["status"] == "PLANTED"


def _setup_g6_exit_scenario(api):
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    grower = create_grower(legal_name="Pajaro River Organics")
    agreement = create_active_agreement(
        grower, variety, max_planting_units=10000,
        cultural_practice_codes=["ORGANIC"])
    lot = create_plant_lot(agreement, variety, quantity_plants=500,
                           nursery_code="NUR-CA-02")
    planting = plan_planting(agreement, lot, grower, planned_plants=300)
    mid_lot = get_plant_lot(lot["id"])
    assert mid_lot["plants_reserved"] == 300
    assert mid_lot["plants_available"] == 200
    return variety, grower, agreement, lot, planting


def test_grower_exit_cascade_terminates_and_cancels(api):
    """PRD section 3.2: "When both gates pass, the exit cascades three links:
    first, every agreement of the grower in `ACTIVE` or `SUSPENDED` moves to
    `TERMINATED`, each incrementing its own `version` by 1; second, every
    planting of each terminated agreement that is still `PLANNED` moves to
    `CANCELLED`; third, each cancelled planting releases its reservation,
    decreasing its plant lot's `plants_reserved` by its `planned_plants`."

    Design: Difficulty/transitive_cascade/grower_exit_depth_cascade
    """
    variety, grower, agreement, lot, planting = _setup_g6_exit_scenario(api)
    exited = exit_grower(grower["id"])
    assert exited["status"] == "EXITED"
    assert exited["exited_at"] is not None
    a = get_agreement(agreement["id"])
    assert a["status"] == "TERMINATED", "link 1: agreement terminated"
    p = get_planting(planting["id"])
    assert p["status"] == "CANCELLED", "link 2: PLANNED planting cancelled"
    l = get_plant_lot(lot["id"])
    assert l["plants_reserved"] == 0, "link 3: reservation released"
    assert l["plants_available"] == 500
    assert l["status"] == "SHIPPED", "exit does not touch lot lifecycle"


def test_grower_exit_then_reengage_rejected(api):
    """PRD section 3.2: "`EXITED` is terminal".
    PRD section 3.3: "Three further gates apply at application time: the grower
    must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`)".

    Design: Difficulty/transitive_cascade/grower_exit_depth_cascade
    """
    variety, grower, agreement, lot, planting = _setup_g6_exit_scenario(api)
    exit_grower(grower["id"])
    resp = api.create_agreement(
        create_agreement_payload(
            grower["id"], variety["id"], max_planting_units=100,
            cultural_practice_codes=["ORGANIC"],
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2027-12-31T00:00:00Z"),
        make_grower_principal_headers(grower["id"]))
    validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ACTIVE)
