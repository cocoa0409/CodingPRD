"""Transitive cascades: clock-sweep expiry and reduction execution."""
import pytest

from test_helpers import (
    TEST_USERS, approve_alteration, complete_alteration, create_alteration,
    create_plan, create_survey, estimate_alteration, finalize_survey,
    generate_bill, list_reduction_actions, set_clock, setup_active_leased_oa,
    setup_active_owned_oa, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
PM = TEST_USERS["gsa_property_manager_headers"]


def test_lease_expiry_cascades_oa_alteration_writeoff(api):
    """PRD §3.9: "When the current date passes an `EXPIRING` lease's `end_date`,
    the sweep moves it to `SUCCEEDED` if its `executed_option` is
    `SUCCEEDING_LEASE`, and to `EXPIRED` otherwise — including when no option
    was ever executed."
    PRD §3.9: "Either landing fires the same cascade across the lease's
    dependents: every occupancy agreement on the lease still in `DRAFT` or
    `ACTIVE` moves to `EXPIRED`, and each of those expirations in turn runs the
    agreement's terminal cascade — its non-terminal alterations are cancelled
    with pending lump charges reversed, its completed amortized alterations'
    remaining balances accelerate into `terminal_writeoff_cents`, and
    owned-space agreements release their square footage (§3.5)."
    PRD §3.9: "Finally, every expiration plan of the lease still sitting in
    `OPEN` or `OPTION_SELECTED` is moved to `CANCELLED` — a plan that was not
    executed in time simply lapses."
    PRD §2.9: "On a `LEASED_STOCK` building, `available_sf` equals `total_sf`
    minus the sum of `leased_sf` over that building's leases in `AWARDED`,
    `COMMENCED`, or `EXPIRING` status."

    Depth-3 cascade: the sweep expires the lease (hop 1), which expires the OA
    (hop 2), which cancels the in-flight APPROVED alteration reversing its
    PENDING lump charge and accelerates the COMPLETED alteration's balance
    (6,000,000 at 7%/12 over 12 months, six payments of 519,160 applied ->
    3,052,345) into terminal_writeoff_cents (hop 3).

    Design: Difficulty/transitive_cascade/lease_expiry_cascades_oa_alteration_writeoff
    """
    bundle = setup_active_leased_oa()  # 2027 stmt actual 460 recorded
    oa, agency, lease, building = (bundle["oa"], bundle["agency"],
                                   bundle["lease"], bundle["building"])

    alt1 = create_alteration(oa, agency, title="HVAC renewal",
                             description="Replace air handlers", scope_sf=68300)
    estimate_alteration(alt1, estimated_cost_cents=6000000,
                        work_start_date="2035-09-01", work_end_date="2035-12-05")
    approve_alteration(alt1, agency, funding_method="AMORTIZED")
    done1 = complete_alteration(alt1, "2035-12-10")
    assert done1["monthly_amort_cents"] == 519160

    alt2 = create_alteration(oa, agency, title="Lobby refresh",
                             description="Cosmetic lobby work", scope_sf=1500)
    estimate_alteration(alt2, estimated_cost_cents=3000000,
                        work_start_date="2036-03-01", work_end_date="2036-04-30")
    approve_alteration(alt2, agency, funding_method="LUMP_SUM")

    for month in ("2036-01", "2036-02", "2036-03", "2036-04", "2036-05", "2036-06"):
        generate_bill(oa, month)  # six amortization payments applied to alt1

    set_clock("2035-07-01T00:00:00Z")  # lease swept COMMENCED -> EXPIRING
    plan = create_plan(lease)          # OPEN, never executed

    sweep = set_clock("2037-01-01T00:00:00Z")
    assert lease["id"] in sweep["transitioned_lease_ids"]

    lease_after = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert lease_after["status"] == "EXPIRED", "executed_option was null"

    oa_after = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert oa_after["status"] == "EXPIRED", "hop 2: forced by the lease"
    assert oa_after["terminal_writeoff_cents"] == 3052345, (
        "hop 3: exact balance after six applied payments of 519160")

    alts, _ = validate_paginated(api.list_alterations(oa["id"], ADMIN))
    by_id = {a["id"]: a for a in alts}
    assert by_id[alt2["id"]]["status"] == "CANCELLED"
    assert by_id[alt2["id"]]["lump_charge_status"] == "REVERSED", (
        "hop 3: the PENDING lump charge is reversed by the cascade")
    assert by_id[alt1["id"]]["status"] == "COMPLETED", (
        "terminal alterations are not cancelled")

    plans, _ = validate_paginated(api.list_expiration_plans(lease["id"], ADMIN))
    assert plans[0]["id"] == plan["id"]
    assert plans[0]["status"] == "CANCELLED", (
        "an unexecuted plan lapses with the lease")

    building_after = validate_success(api.get_building(building["id"], ADMIN), 200)
    assert building_after["available_sf"] == 200000, (
        "leased stock released on expiry: 68300 returned to the pool")


def test_reduction_execute_amends_oa_and_restores_building_sf(api):
    """PRD §3.8: "Finalization also sets `recommended_release_sf`: the
    `assigned_sf` minus the `measured_headcount` times the same
    150-square-feet-per-person standard, floored at zero."
    PRD §3.8: "When the finalized rate falls strictly below 0.60 — a rate of
    exactly 0.6000 does not qualify — the system auto-creates a space reduction
    action in `PROPOSED` on the same agreement, copies the recommendation into
    it, and links it back through the survey's `reduction_action_id`; otherwise
    that field stays null."
    PRD §3.8: "Execution behaves like a downward amendment: the agreement's
    `assigned_sf` decreases by the recommended release, `amendment_history`
    gains an entry whose `delta_sf` is the negative of the released footage,
    and the agreement's `version` increments; an owned building's
    `available_sf` rises by the released footage, while on leased space the
    footage is released against the lease."
    PRD §3.8: "The action records `executed_release_sf` — equal to the
    recommendation — and stamps `executed_at` from the logical clock."

    Depth-2 cascade: EXECUTED mutates the OA (20,000 -> 10,500, hop 1) and that
    mutation restores the owned building's available_sf 30,000 -> 39,500
    (hop 2).

    Design: Difficulty/transitive_cascade/reduction_execute_amends_oa_and_restores_building_sf
    """
    bundle = setup_active_owned_oa(clock="2027-03-20T00:00:00Z")
    oa, building = bundle["oa"], bundle["building"]

    survey = create_survey(oa, method="HEADCOUNT_BASED", measured_headcount=70,
                           utilized_sf=10500)
    finalized = finalize_survey(survey)
    assert finalized["utilization_rate"] == pytest.approx(0.5250, abs=1e-9)
    assert finalized["reduction_action_id"] is not None

    actions = list_reduction_actions(oa)
    assert len(actions) == 1
    action = actions[0]
    assert action["status"] == "PROPOSED"
    assert action["recommended_release_sf"] == 9500

    validate_success(api.approve_reduction(action["id"], ADMIN), 200)
    oa_before = validate_success(api.get_oa(oa["id"], ADMIN), 200)

    executed = validate_success(api.execute_reduction(action["id"], PM), 200)
    assert executed["status"] == "EXECUTED"
    assert executed["executed_release_sf"] == 9500

    oa_after = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert oa_after["assigned_sf"] == 10500
    assert oa_after["version"] == oa_before["version"] + 1, (
        "the OA mutation bumps its version by exactly 1")
    last = oa_after["amendment_history"][-1]
    assert last["delta_sf"] == -9500
    assert last["old_sf"] == 20000
    assert last["new_sf"] == 10500

    building_after = validate_success(api.get_building(building["id"], ADMIN), 200)
    assert building_after["available_sf"] == 39500, (
        "hop 2: 30,000 + 9,500 restored by the OA mutation")
