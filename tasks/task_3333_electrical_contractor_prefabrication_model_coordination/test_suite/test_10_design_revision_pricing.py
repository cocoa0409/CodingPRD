"""Dual-variant calculation tests (queue A).

Every test in this file translates exactly one difficulty-design instance.
"""
import math

import pytest
from test_helpers import (
    PM,
    GF,
    MC,
    validate_error,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.fixtures import (
    acknowledge_crew_day,
    advance_fabrication,
    create_activity,
    create_apprentice,
    create_component,
    create_coordinated_model,
    create_crew_day,
    create_draft_model,
    create_project,
    create_rack,
    create_rate,
    create_worker,
    fabricate_component,
    fetch_order,
    fetch_project,
    register_default_assembly,
    release_order_ok,
    set_activity_status,
    setup_revision,
)

DIVISOR = 4


def _engineering_hours(impact_qualified_hours, revision_quantity):
    return round(impact_qualified_hours * revision_quantity / DIVISOR, 2)


@pytest.fixture
def revision_pricing_scenario():
    """Project + coordinated model A + successor B + SUBMITTED revision carrying
    the pricing worksheet inputs. Returns (project, model_a, successor, revision).

    PRD §3.7: submission requires the successor to name "a model version whose
    zone quantity total is at least 1", and approval "requires the revision to be
    `SUBMITTED`" — so the successor carries an extraction line and the revision
    is submitted before the caller approves it.
    """
    project = create_project(project_code="P-3333-A")
    model_a, lines = create_coordinated_model(model_id="mdl-alpha", revision_letter="A")
    successor = create_draft_model(model_id="mdl-alpha", revision_letter="B")
    register_default_assembly()
    validate_success(
        api.create_takeoff_line(
            {"model_version_id": successor["id"], "zone_code": "Z-1",
             "assembly_code": "A-RACK", "conduit_run_type": "RIGID_RACK",
             "conduit_run_type_code": "RC50", "quantity": 100,
             "prefab_share_pct": 0.5},
            MC,
        ),
        expected_status=201,
    )
    revision = setup_revision(
        project, model_a, lines[0], successor["id"],
        impact_qualified_hours=40,
        revision_quantity=3,
        direct_shop_cost_cents=200000,
        kludge_rate_per_hour_cents=8500,
        negotiated_rate_per_hour_cents=7800,
        submitted_markup_pct=0.18,
    )
    revision = validate_success(api.submit_revision(revision["id"], PM))
    return project, model_a, successor, revision


def test_memo_ceiling_caps_the_kludge_variant(api, admin_headers, project_manager_headers,
                                              revision_pricing_scenario):
    """PRD §3.7: "The memo rework ceiling is then the smaller of those engineering
    hours multiplied by the kludge rate and the revision's `direct_shop_cost_cents`;
    it uses the kludge rate of 8,500 cents per hour, it is capped by
    `direct_shop_cost_cents`, it never adds markup and it is never rounded."

    Design: Difficulty/dual_variant_calc/revision_memo_ceiling_versus_negotiated_change_order
    """
    _project, model_a, _successor, revision = revision_pricing_scenario
    hours = _engineering_hours(40, 3)
    assert hours == 30.00

    result = validate_success(
        api.approve_revision(
            revision["id"],
            {"expected_model_version_version": model_a["version"], "resolution": "APPROVED"},
            project_manager_headers,
        )
    )
    impact = result["impact_values"][0]
    assert impact["rework_value_cents"] == min(hours * 8500, 200000) == 200000, (
        "the memo variant is capped by direct_shop_cost_cents and never adds markup"
    )


def test_negotiated_change_order_exceeds_the_memo_ceiling(api, admin_headers,
                                                          project_manager_headers,
                                                          revision_pricing_scenario):
    """PRD §3.7: "The negotiated change-order value is the engineering hours
    multiplied by the negotiated rate of 7,800 cents per hour, multiplied by one
    plus the submitted markup fraction of 0.18, stated in whole cents rounded half
    up; it is not capped by `direct_shop_cost_cents`, so it can exceed the memo
    value."
    PRD §3.7: "Both values are written per impact into `impact_values`, one entry
    per impact key, the memo value as `rework_value_cents` and the change-order
    value as `negotiated_value_cents`."

    Design: Difficulty/dual_variant_calc/revision_memo_ceiling_versus_negotiated_change_order
    """
    _project, model_a, _successor, revision = revision_pricing_scenario
    hours = _engineering_hours(40, 3)

    result = validate_success(
        api.approve_revision(
            revision["id"],
            {"expected_model_version_version": model_a["version"], "resolution": "APPROVED"},
            project_manager_headers,
        )
    )
    impact = result["impact_values"][0]
    assert impact["negotiated_value_cents"] == round(hours * 7800 * 1.18, 0) == 276120
    assert impact["negotiated_value_cents"] > impact["rework_value_cents"], (
        "the two variants legitimately disagree on the same engineering hours"
    )


def _two_report_day(project_code, policy, jm_hours=8.0, final_hours=10.0):
    """One journeyman, one ACTIVE activity, two reports for the same work date:
    sequence 1 with 8.0 hours and sequence 2 with 10.0 hours, the second FINAL."""
    project = create_project(project_code=project_code, credit_policy=policy)
    rate = create_rate(jurisdiction_key=project["jurisdiction_key"])
    worker = create_worker(worker_code=f"{project_code}-JM")
    activity = create_activity(project["id"], rate_id=rate["id"],
                               planned_duration_days=4, written_sequence_index=1)
    set_activity_status(activity["id"], "PERMITTED")
    set_activity_status(activity["id"], "ACTIVE")

    first = create_crew_day(project["id"], worker["id"], activity["id"],
                            foreman_id=worker["id"], regular_hours=jm_hours,
                            report_sequence=1, acknowledge_mode="RELEASE")
    second = create_crew_day(project["id"], worker["id"], activity["id"],
                             foreman_id=worker["id"], regular_hours=final_hours,
                             report_sequence=2, acknowledge_mode="FINAL")
    second = acknowledge_crew_day(second)
    return project, first["id"], second


def test_first_accepted_credits_the_earliest_report(api, general_foreman_headers):
    """PRD §3.6: "The candidates are the crew-day rows for the same project, worker
    and work date with a `report_sequence` of at least 1 — so a report sequence of
    zero is not a candidate. When the policy is `FIRST_ACCEPTED`, the winning row is
    the one with the smallest `report_sequence`, ties broken by the earliest
    `created_at`."

    Design: Difficulty/dual_variant_calc/crew_day_first_accepted_versus_highest_total_credit
    """
    _project, first_id, second = _two_report_day("P-3333-FIRST", "FIRST_ACCEPTED")

    listed = api.list_crew_days(general_foreman_headers, {"project_id": _project["id"]})
    by_id = {row["id"]: row for row in listed.json()["data"]}

    assert by_id[first_id]["credited_hours"] == 8.0
    assert by_id[first_id]["accepted_for_credit"] is True
    assert second["credited_hours"] == 0.0
    assert second["accepted_for_credit"] is False


def test_highest_total_credits_the_largest_report(api, general_foreman_headers):
    """PRD §3.6: "When the policy is `HIGHEST_TOTAL`, the winning row is the one
    with the largest sum of its regular hours plus one and a half times its overtime
    hours, ties broken by the smaller `report_sequence`."
    PRD §3.6: "The two policies therefore disagree in a specific way: under
    `FIRST_ACCEPTED` the earliest report wins even when a later report claims more
    hours, whereas under `HIGHEST_TOTAL` a mid-day re-report with more hours flips
    the winner."

    Design: Difficulty/dual_variant_calc/crew_day_first_accepted_versus_highest_total_credit
    """
    _project, first_id, second = _two_report_day("P-3333-HIGH", "HIGHEST_TOTAL")

    listed = api.list_crew_days(general_foreman_headers, {})
    by_id = {row["id"]: row for row in listed.json()["data"]}

    assert second["credited_hours"] == 10.0
    assert second["accepted_for_credit"] is True
    assert by_id[first_id]["credited_hours"] == 0.0
    assert by_id[first_id]["accepted_for_credit"] is False


def _hoist_order(model_id, shop_utilization_pct, project_manager_headers=None):
    """Project + coordinated model + rack + FIRST_STAGE work package holding two
    chained components, released by the caller."""
    project = create_project(
        project_code=f"P-3333-HOIST-{model_id}", shop_utilization_pct=shop_utilization_pct)
    mv, lines = create_coordinated_model(model_id=model_id)
    rack = create_rack(mv["id"], rack_code="R-H1")
    order = validate_success(
        api.create_prefab_order(
            {
                "project_id": project["id"], "model_version_id": mv["id"],
                "stage_code": "FIRST_STAGE", "zone_code": "Z-1",
                "transport_kind": "FLATBED", "hoisting_window_id": "HW-1",
                "required_on_site_iso": "2026-11-20T00:00:00Z",
                "installation_window_start_iso": "2026-11-21T00:00:00Z",
                "fabricate_quantity": 2,
                "shop_utilisation_basis_pct": shop_utilization_pct,
            },
            project_manager_headers,
        ),
        expected_status=201,
    )
    first = create_component(order["id"], lines[0]["id"], rack_id=rack["id"],
                             quantity=50, chain_mode="CHAIN_DEPENDENT",
                             chain_dependency_link="LNK-1")
    second = create_component(order["id"], lines[0]["id"], rack_id=rack["id"],
                              quantity=50, chain_mode="CHAIN_DEPENDENT",
                              chain_dependency_link="LNK-2",
                              predecessor_component_id=first["id"])
    released = release_order_ok(order)
    return project, mv, first, second, released


def test_hoisting_multiplier_ladder_selects_the_loaded_row(api, admin_headers,
                                                           project_manager_headers):
    """PRD §3.3: "A capacity multiplier is taken from a three-row shop capacity
    ladder by first matching row: a multiplier of 1.0 when `shop_utilization_pct`
    is at most 0.85, 1.2 when it is at most 1.00, and 1.5 for any higher load."
    PRD §3.3: "The length `hoisting_duration_days` is that base clamped to the
    inclusive range from 1 to 10 days."

    Design: Difficulty/combinatorial_formula/hoisting_window_ladder_with_chain_depth_and_shop_capacity
    """
    _project, _mv, _first, _second, order = _hoist_order(
        "mdl-hoist-90", 0.90, project_manager_headers)
    stage = {"clash_slots": 4, "trade_count": 2}
    chain_depth, penalty, multiplier = 1, 1, 1.2
    # "rounded up to a whole number of days": 9.6 rounds up to 10, it is not
    # truncated to 9.
    base_days = math.ceil((stage["clash_slots"] + stage["trade_count"]
                           + chain_depth + penalty) * multiplier)
    assert base_days == 10

    assert order["hoisting_duration_days"] == min(max(base_days, 1), 10) == 10


def test_hoisting_multiplier_ladder_drops_on_a_less_loaded_shop(api, admin_headers,
                                                               project_manager_headers):
    """PRD §3.3: "A capacity multiplier is taken from a three-row shop capacity
    ladder by first matching row: a multiplier of 1.0 when `shop_utilization_pct`
    is at most 0.85, 1.2 when it is at most 1.00, and 1.5 for any higher load."
    PRD §3.3: "The base day count is the sum of the clash slots, the trade count,
    the chain depth and the productivity penalty, multiplied by that capacity
    multiplier and rounded up to a whole number of days."

    Design: Difficulty/combinatorial_formula/hoisting_window_ladder_with_chain_depth_and_shop_capacity
    """
    _project, _mv, _first, _second, order = _hoist_order(
        "mdl-hoist-80", 0.80, project_manager_headers)
    stage = {"clash_slots": 4, "trade_count": 2}
    base_days = -(-int((stage["clash_slots"] + stage["trade_count"] + 1 + 1) * 1.0) // 1)
    assert base_days == 8

    assert order["hoisting_duration_days"] == 8, (
        "the ladder placement alone changes the derived window"
    )


def _aggregation_scenario(project_manager_headers=None):
    """Two parallel components of quantity 50 on one released work package, with
    one of them fabricated before the release."""
    project = create_project(project_code="P-3333-AGG", jurisdiction_key="J2",
                             shop_utilization_pct=0.90, total_quantity=200)
    rate = create_rate(jurisdiction_key="J2", hourly_rate_cents=7000, burden_pct=0.40)
    mv, lines = create_coordinated_model(model_id="mdl-agg")
    rack = create_rack(mv["id"], rack_code="R-G1")
    order = validate_success(
        api.create_prefab_order(
            {
                "project_id": project["id"], "model_version_id": mv["id"],
                "stage_code": "FIRST_STAGE", "zone_code": "Z-1",
                "transport_kind": "FLATBED", "hoisting_window_id": "HW-1",
                "required_on_site_iso": "2026-11-20T00:00:00Z",
                "installation_window_start_iso": "2026-11-21T00:00:00Z",
                "fabricate_quantity": 2, "shop_utilisation_basis_pct": 0.90,
            },
            project_manager_headers,
        ),
        expected_status=201,
    )
    components = [
        create_component(order["id"], lines[0]["id"], rack_id=rack["id"],
                        quantity=50, chain_dependency_link=f"LNK-G{i}")
        for i in (1, 2)
    ]
    # PRD §3.3: "`assembly_count` is the number of the package's components" —
    # a derived field, so the returned row must be the post-release one rather
    # than the snapshot taken before the components existed.
    order = release_order_ok(order)
    return project, rate, mv, order, components


def test_pipeline_balance_sums_crafted_hours_at_the_journeyman_rate(api, admin_headers,
                                                                    project_manager_headers):
    """PRD §3.8: "The component's `prefab_value_cents` is those crafted hours
    multiplied by the hourly rate resolved for the project's jurisdiction at the
    `JOURNEYMAN` classification, multiplied by one plus that rate's burden fraction."
    PRD §3.8: "The man-hour total `man_hours_total` is the sum of `crafted_hours`
    over every component of the project, including scrapped ones."

    Design: Difficulty/combinatorial_formula/project_aggregation_round_then_divide_versus_divide_then_round
    """
    project, rate, _mv, order, components = _aggregation_scenario(
        project_manager_headers)
    summary = fetch_project(project["id"])

    assert order["assembly_count"] == 2
    assert summary["man_hours_total"] == sum(
        c["crafted_hours"] for c in components
    ), "the man-hour total sums the crafted hours of every component"

    expected_pipeline = round(
        summary["man_hours_total"] * rate["hourly_rate_cents"] * (1 + rate["burden_pct"]), 0
    )
    assert summary["pipeline_value_cents"] == expected_pipeline
    assert summary["installed_pct"] == 0.0, (
        "no component is SET, so the completed balance stays zero and installed_pct is zero"
    )


def test_effective_flow_rounds_the_total_volume_before_dividing(api, admin_headers,
                                                               project_manager_headers):
    """PRD §3.8: "The effective flow percentage is the project's installed work
    volume divided by its total work volume, with the installed figure expressed as
    a whole percent before the division: the man-hour total is multiplied by a
    factor that is 11 when `installed_pct` is at least 0.40 and 16 otherwise, the
    product is rounded to a whole number, and that is divided by the man-hour total
    or by one, whichever is greater."
    PRD §3.8: "The project's `craft_hours_credit` is `man_hours_total` minus the
    expected released hours, floored at zero, so the credit decreases as the
    released quantity increases and never goes negative."

    Design: Difficulty/combinatorial_formula/project_aggregation_round_then_divide_versus_divide_then_round
    """
    project, _rate, _mv, _order, _components = _aggregation_scenario(
        project_manager_headers)
    summary = fetch_project(project["id"])

    assert summary["installed_pct"] == 0.0
    assert summary["effective_flow_pct"] == 16.0, (
        "round(man_hours_total * 16) / man_hours_total is exactly 16.0"
    )
    assert summary["craft_hours_credit"] == summary["man_hours_total"], (
        "released_quantity is zero at the release instant so no release credit is consumed"
    )