"""State-machine shape and conserved-quantity tests (queue A)."""
import pytest
from test_helpers import PM, SF, validate_success
from test_helpers import api_client as api
from test_helpers.fixtures import (
    acknowledge_crew_day,
    advance_fabrication,
    create_component,
    create_coordinated_model,
    create_crew_day,
    create_project,
    create_rack,
    create_rate,
    create_worker,
    fetch_component,
    fetch_ledger_row,
    fetch_order,
    fetch_project,
    fabricate_component,
    release_order_ok,
    setup_crew_pair,
)


# --------------------------------------------------------------------------
# non_linear_state_machine / prefab_order_parallel_dimensions_with_manual_reverts
# --------------------------------------------------------------------------

def _revertible_order(project_code="P-3333-PAR"):
    """A FABRICATED work package holding one FABRICATED component, undelivered."""
    project = create_project(project_code=project_code)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    rack = create_rack(mv["id"], rack_code=f"R-{project_code}")
    order = validate_success(
        api_create_order(project["id"], mv["id"], "HW-P1", 1), expected_status=201)
    comp = create_component(order["id"], lines[0]["id"], rack_id=rack["id"],
                            quantity=100)
    order = release_order_ok(order)
    order = advance_fabrication(order, target="IN_FABRICATION")
    comp = fabricate_component(comp["id"])
    order = validate_success(
        api.set_fabrication_status(order["id"], {"fabricate_status": "FABRICATED"},
                                   SF),
        expected_status=200,
    )
    return project, mv, rack, order, comp


def api_create_order(project_id, model_version_id, hoisting_window_id, fabricate_quantity):
    from test_helpers import api_client
    return api_client.create_prefab_order(
        {
            "project_id": project_id, "model_version_id": model_version_id,
            "stage_code": "FIRST_STAGE", "zone_code": "Z-1",
            "transport_kind": "FLATBED", "hoisting_window_id": hoisting_window_id,
            "required_on_site_iso": "2026-11-20T00:00:00Z",
            "installation_window_start_iso": "2026-11-21T00:00:00Z",
            "fabricate_quantity": fabricate_quantity,
            "shop_utilisation_basis_pct": 0.50,
        },
        PM,
    )


def test_revert_moves_only_the_shop_dimension(api, project_manager_headers):
    """PRD §3.3: "Reverting a `FABRICATED` package back to `PLANNED` requires
    `deliver_status` to be `AWAITING`, and it releases the laydown slot back to the
    free pool, clears `hoisting_start_iso`, `hoisting_end_iso` and
    `release_to_shop_iso` to null, reverts every component of the package whose
    `install_status` is `FABRICATED` back to `PLANNED`".

    Design: Difficulty/non_linear_state_machine/prefab_order_parallel_dimensions_with_manual_reverts
    """
    _project, _mv, _rack, order, comp = _revertible_order()
    assert order["fabricate_status"] == "FABRICATED"
    assert order["deliver_status"] == "AWAITING"

    reverted = validate_success(
        api.ressue_prefab_order(order["id"], project_manager_headers)
    )
    assert reverted["fabricate_status"] == "PLANNED", (
        "the shop dimension is undone by the revert"
    )
    assert reverted["deliver_status"] == "AWAITING", (
        "the delivery dimension is untouched because it never advanced"
    )
    assert fetch_component(comp["id"])["install_status"] == "PLANNED", (
        "a FABRICATED component of the package reverts to PLANNED"
    )


def test_revert_clears_the_frozen_window_and_frees_the_laydown_slot(
        api, project_manager_headers):
    """PRD §3.3: "it releases the laydown slot back to the free pool, clears
    `hoisting_start_iso`, `hoisting_end_iso` and `release_to_shop_iso` to null".

    Design: Difficulty/non_linear_state_machine/prefab_order_parallel_dimensions_with_manual_reverts
    """
    _project, _mv, _rack, order, _comp = _revertible_order()
    assert order["laydown_slot_index"] == 1
    assert order["hoisting_start_iso"] is not None

    validate_success(api.ressue_prefab_order(order["id"], project_manager_headers))
    after = fetch_order(order["id"])
    assert after["laydown_slot_index"] is None
    assert after["hoisting_start_iso"] is None
    assert after["hoisting_end_iso"] is None


# --------------------------------------------------------------------------
# non_linear_state_machine / trade_activity_disallow_and_resume_cycle
# --------------------------------------------------------------------------

def test_breaching_crew_suspends_the_active_activity(api, general_foreman_headers):
    """PRD §3.5: "An `ACTIVE` activity moves to `DISALLOWED` when at least one crew
    member on it carries a compliance-ledger row with `excess_apprentice_hours`
    greater than zero; the activity's `suspension_reason` is stamped with the
    apprenticeship ratio breach".

    Design: Difficulty/non_linear_state_machine/trade_activity_disallow_and_resume_cycle
    """
    # PRD §3.6 refuses a crew day that would breach the project-wide cap, so the
    # project carries one extra journeyman hour on a second activity: the crew of
    # this activity then breaches its own activity cap (5.0 > 1.0 x 4.0) while
    # the project as a whole stays inside the agreement.
    _project, _rate, _jm, _ap, activity, _jm_day, _ap_day = setup_crew_pair(
        project_code="P-3333-CYC", journeyman_hours=4.0, apprentice_hours=5.0,
        project_journeyman_hours=1.0)

    assert activity["status"] == "DISALLOWED", (
        "apprentice hours 5.0 exceed ratio_limit 1.0 x journeyman hours 4.0"
    )
    assert activity["suspension_reason"], "the suspension reason is stamped on the breach"


def test_top_up_hours_return_the_activity_to_active(api, general_foreman_headers):
    """PRD §3.5: "The activity resumes when every crew member assigned to it has
    `excess_apprentice_hours` equal to zero — which happens when later crew-day
    acknowledgments bring the ratio back inside the cap — at which point the
    activity returns to `ACTIVE`, its `suspension_reason` is cleared to null".

    Design: Difficulty/non_linear_state_machine/trade_activity_disallow_and_resume_cycle
    """
    project, _rate, jm, _ap, activity, _jm_day, _ap_day = setup_crew_pair(
        project_code="P-3333-CYC2", journeyman_hours=4.0, apprentice_hours=5.0,
        project_journeyman_hours=1.0)
    assert activity["status"] == "DISALLOWED"

    top_up = create_crew_day(project["id"], jm["id"], activity["id"],
                             foreman_id=jm["id"], regular_hours=1.0,
                             report_sequence=2, acknowledge_mode="FINAL")
    acknowledge_crew_day(top_up)

    ledger = fetch_ledger_row(project["id"], jm["id"])
    assert ledger["excess_apprentice_hours"] == 0.0, (
        "4.0 journeyman hours plus the 1.0 hour top-up brings the ratio inside the cap"
    )
    listed = api.list_trade_activities(general_foreman_headers,
                                       {"project_id": project["id"]})
    resumed = {row["id"]: row for row in listed.json()["data"]}[activity["id"]]
    assert resumed["status"] == "ACTIVE", (
        "the activity visits ACTIVE twice, so no linearly ordered chain can express it"
    )
    assert resumed["suspension_reason"] in (None, ""), "the suspension reason is cleared"


# --------------------------------------------------------------------------
# compensating_invariant / released_craft_hours_balance_survives_ressue_revert
# --------------------------------------------------------------------------

def _balance_scenario(project_code="P-3333-INV1", jurisdiction_key="J3",
                      rate_cents=5000, burden_pct=0.30):
    """Two components of quantity 50 on one work package in jurisdiction J3."""
    project = create_project(project_code=project_code, jurisdiction_key=jurisdiction_key,
                             total_quantity=200, released_quantity=0)
    rate = create_rate(jurisdiction_key=jurisdiction_key, hourly_rate_cents=rate_cents,
                       burden_pct=burden_pct)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    rack = create_rack(mv["id"], rack_code=f"R-{project_code}")
    order = validate_success(
        api_create_order(project["id"], mv["id"], "HW-AB1", 2), expected_status=201)
    comps = [
        create_component(order["id"], lines[0]["id"], rack_id=rack["id"],
                         quantity=50, chain_dependency_link=f"LNK-AB{i}")
        for i in (1, 2)
    ]
    return project, rate, mv, order, comps


def test_craft_hours_balance_is_unchanged_by_the_revert(api, project_manager_headers,
                                                        shop_foreman_headers):
    """PRD §3.8: "The project's `craft_hours_balance` is the labor base plus the
    material base."
    PRD §3.8: "Reverting a fabricated order moves the released labor figure out of
    the released balance and the reinstated figure back in, and because both are the
    same expression over the same released quantity the net movement is exactly zero."

    Design: Difficulty/compensating_invariant/released_craft_hours_balance_survives_ressue_revert
    """
    project, rate, _mv, order, comps = _balance_scenario()
    before = fetch_project(project["id"])["craft_hours_balance"]
    assert before > 0

    order = release_order_ok(order)
    order = advance_fabrication(order, target="IN_FABRICATION")
    fabricate_component(comps[0]["id"])
    order = validate_success(
        api.set_fabrication_status(order["id"], {"fabricate_status": "FABRICATED"},
                                   shop_foreman_headers),
        expected_status=200,
    )
    validate_success(api.ressue_prefab_order(order["id"], project_manager_headers))

    after = fetch_project(project["id"])["craft_hours_balance"]
    assert after == before, (
        "the compensated revert leaves the named quantity with zero drift"
    )


def test_craft_hours_balance_is_the_labor_plus_material_base(api, project_manager_headers):
    """PRD §3.8: "Its labor base is the project's `man_hours_total` multiplied by
    the journeyman hourly rate for the project's jurisdiction, rounded to whole
    cents. Its material base is the sum of `crafted_hours` over the project's
    components, multiplied by the same journeyman rate, rounded to whole cents."
    PRD §3.8: "Component rows whose install status is `SCRAPPED` are excluded, and
    `released_quantity` is read at the release instant and again at the revert instant."

    Design: Difficulty/compensating_invariant/released_craft_hours_balance_survives_ressue_revert
    """
    project, rate, _mv, order, comps = _balance_scenario(project_code="P-3333-INV1B")
    summary = fetch_project(project["id"])
    crafted_total = sum(c["crafted_hours"] for c in comps)
    expected = round(summary["man_hours_total"] * rate["hourly_rate_cents"], 0) \
        + round(crafted_total * rate["hourly_rate_cents"], 0)

    assert summary["craft_hours_balance"] == expected, (
        "with released_quantity 0 the balance is exactly the labor base plus the material base"
    )


# --------------------------------------------------------------------------
# compensating_invariant / apprentice_hours_reconciliation_survives_adjustment_and_reversal
# --------------------------------------------------------------------------

def _balanced_ledger(project_code, acknowledge=True):
    return setup_crew_pair(project_code=project_code, journeyman_hours=4.0,
                           apprentice_hours=4.0, acknowledge=acknowledge)


def test_apprentice_hours_land_exactly_on_the_cap_with_zero_excess(
        api, general_foreman_headers):
    """PRD §3.6: "Its `excess_apprentice_hours` is the apprentice hours carried in
    excess of the resolved `ratio_limit` multiplied by the journeyman hours, and
    that figure is what drives activity suspension."
    PRD §3.6: "the row's `apprentice_hours` must equal its original apprentice hours
    plus `adjustment_delta_hours` at all times."

    Design: Difficulty/compensating_invariant/apprentice_hours_reconciliation_survives_adjustment_and_reversal
    """
    project, _rate, jm, _ap, activity, _jm_day, _ap_day = _balanced_ledger("P-3333-INV2")
    ledger = fetch_ledger_row(project["id"], jm["id"])

    assert ledger["ratio_limit"] == 1.0
    assert ledger["journeyman_hours"] == 4.0
    assert ledger["apprentice_hours"] == 4.0
    assert ledger["excess_apprentice_hours"] == 0.0, (
        "4.0 apprentice hours equals ratio_limit 1.0 x 4.0 journeyman hours"
    )
    assert ledger["adjustment_delta_hours"] == 0.0
    assert activity["status"] == "ACTIVE"


def test_reconciliation_identity_holds_on_a_fresh_project(api, general_foreman_headers):
    """PRD §3.6: "Its `adjustment_delta_hours` is the signed sum of the compliance
    corrections applied to the row, and the row carries a conservation requirement:
    the row's `apprentice_hours` must equal its original apprentice hours plus
    `adjustment_delta_hours` at all times."

    Design: Difficulty/compensating_invariant/apprentice_hours_reconciliation_survives_adjustment_and_reversal
    """
    project, _rate, jm, _ap, _activity, jm_day, ap_day = _balanced_ledger(
        "P-3333-INV2B", acknowledge=False)
    acknowledge_crew_day(ap_day)
    acknowledge_crew_day(jm_day)

    ledger = fetch_ledger_row(project["id"], jm["id"])
    original_apprentice_hours = ap_day["regular_hours"] + 1.5 * ap_day["overtime_hours"]
    assert ledger["apprentice_hours"] == original_apprentice_hours + ledger["adjustment_delta_hours"]
    assert ledger["excess_apprentice_hours"] == 0.0, (
        "the quantity is conserved rather than merely settled once"
    )