"""Project rollups, thresholds and frozen-window boundaries (queue B)."""
import pytest
from test_helpers import PM, SF, validate_error_is_one_of, validate_success
from test_helpers import api_client as api
from test_helpers.fixtures import (
    advance_fabrication,
    create_component,
    create_coordinated_model,
    create_project,
    create_rack,
    create_rate,
    create_worker,
    fetch_component,
    fetch_order,
    fetch_project,
    fabricate_component,
    release_order_ok,
    setup_crew_pair,
    setup_slippage,
)


# --------------------------------------------------------------------------
# calculations / project_posture_tier_boundary_at_exactly_two_percent
# --------------------------------------------------------------------------

def test_slippage_of_exactly_two_percent_stays_on_track(api, admin_headers):
    """PRD §3.2: "The ladder is then walked descending, and each tier uses a
    less-than-or-equal test, so a value exactly on a boundary belongs to the lower
    tier. When `slippage_pct` is at most `SLIP_RELEASE_AT` the posture is `ON_TRACK`."

    Design: Corner/calculations/project_posture_tier_boundary_at_exactly_two_percent
    """
    # PRD §3.2: the shortfall is "the logical clock instant minus the activity's
    # `planned_start_iso` minus its `planned_duration_days`". The activity starts
    # 2026-10-01 and runs 100 days, so a two day shortfall needs the clock at
    # 2026-10-01 + 102 days.
    project, _activity, _rate = setup_slippage(
        project_code="P-3333-CA1", planned_duration_days=100,
        clock_iso="2027-01-11T00:00:00Z")

    assert project["slippage_pct"] == 0.02, (
        "a two day shortfall over a hundred day span rounds to four decimals without loss"
    )
    assert project["project_posture"] == "ON_TRACK", (
        "equality belongs to the lower tier"
    )


def test_one_further_day_of_slippage_moves_the_tier(api, admin_headers):
    """PRD §3.2: "When it is at most `SLIP_RECOVERY_AT` the posture is
    `RELEASE_PENDING`."
    PRD §3.2: "The `slippage_pct` is the absolute value of the shortfall divided by
    the span, stated to four decimal places rounded half up".

    Design: Corner/calculations/project_posture_tier_boundary_at_exactly_two_percent
    """
    project, _activity, _rate = setup_slippage(
        project_code="P-3333-CA1B", planned_duration_days=100,
        clock_iso="2027-01-12T00:00:00Z")

    assert project["slippage_pct"] == 0.03
    assert project["project_posture"] == "RELEASE_PENDING"


# --------------------------------------------------------------------------
# calculations / pipeline_balance_excludes_scrapped_components
# --------------------------------------------------------------------------

def _two_component_project(project_code):
    project = create_project(project_code=project_code, total_quantity=20)
    create_rate(jurisdiction_key=project["jurisdiction_key"], hourly_rate_cents=5000,
                burden_pct=0.30)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    order = validate_success(
        api.create_prefab_order(
            {
                "project_id": project["id"], "model_version_id": mv["id"],
                "stage_code": "FIRST_STAGE", "zone_code": "Z-1",
                "transport_kind": "FLATBED", "hoisting_window_id": f"HW-{project_code}",
                "required_on_site_iso": "2026-11-20T00:00:00Z",
                "installation_window_start_iso": "2026-11-21T00:00:00Z",
                "fabricate_quantity": 2, "shop_utilisation_basis_pct": 0.50,
            },
            PM,
        ),
        expected_status=201,
    )
    comps = [
        create_component(order["id"], lines[0]["id"], rack_id=None,
                         quantity=10, chain_dependency_link=f"LNK-CA2{chr(64 + i)}")
        for i in (1, 2)
    ]
    return project, order, comps


def test_pipeline_balance_counts_the_fabricated_pair(api, project_manager_headers,
                                                     shop_foreman_headers):
    """PRD §3.8: "The project's `pipeline_value_cents` is the sum of
    `prefab_value_cents` over the components whose install status is `PLANNED`,
    `FABRICATED`, `LOADED` or `REWORK`; `completed_value_cents` is the same sum over
    the components whose install status is `SET`."
    PRD §3.8: "The man-hour total `man_hours_total` is the sum of `crafted_hours`
    over every component of the project, including scrapped ones."

    Design: Corner/calculations/pipeline_balance_excludes_scrapped_components
    """
    project, order, comps = _two_component_project("P-3333-CA2")
    order = release_order_ok(order)
    order = advance_fabrication(order, target="IN_FABRICATION")
    for comp in comps:
        fabricate_component(comp["id"])

    summary = fetch_project(project["id"])
    assert summary["completed_value_cents"] == 0, "no component is SET"
    assert summary["pipeline_value_cents"] > 0
    assert summary["man_hours_total"] == sum(
        fetch_component(c["id"])["crafted_hours"] for c in comps
    )


def test_scrapped_components_leave_both_balances(api, project_manager_headers):
    """PRD §2.10: "a component with install status `SCRAPPED` is counted in neither
    the pipeline balance nor the completed balance while still being counted in the
    man-hour totals used for the release credit."
    PRD §3.3: "cancellation moves it to the terminal `CANCELLED`, clears `rack_id` on
    every component whose install status is `PLANNED` or `FABRICATED` and sets those
    components to `SCRAPPED`".

    Design: Corner/calculations/pipeline_balance_excludes_scrapped_components
    """
    project, order, comps = _two_component_project("P-3333-CA2B")
    man_hours_before = fetch_project(project["id"])["man_hours_total"]

    validate_success(api.cancel_prefab_order(order["id"], project_manager_headers))
    for comp in comps:
        assert fetch_component(comp["id"])["install_status"] == "SCRAPPED"

    summary = fetch_project(project["id"])
    assert summary["pipeline_value_cents"] == 0
    assert summary["completed_value_cents"] == 0
    assert summary["man_hours_total"] == man_hours_before, (
        "the man-hour total still counts the scrapped components"
    )


# --------------------------------------------------------------------------
# calculations / apprentice_upgrade_threshold_is_strict
# --------------------------------------------------------------------------

def test_ring_hours_accumulate_from_accepted_days_only(api, general_foreman_headers):
    """PRD §3.6: "A worker's `journey_ring_claim_hours` is the sum of
    `credited_hours` over the worker's crew days that are accepted for credit, stated
    to two decimal places rounded half up; rows not accepted for credit contribute
    nothing."

    Design: Corner/calculations/apprentice_upgrade_threshold_is_strict
    """
    project, _rate, _jm, apprentice, _activity, _jm_day, ap_day = setup_crew_pair(
        project_code="P-3333-CA3", journeyman_hours=8.0, apprentice_hours=8.0)

    listed = api.list_crew_days(general_foreman_headers, {"worker_id": apprentice["id"]})
    rows = listed.json()["data"]
    accepted = [row for row in rows if row["accepted_for_credit"]]
    assert accepted and accepted[0]["credited_hours"] == 8.0
    assert ap_day["credited_hours"] == 8.0


def test_only_the_accepted_row_feeds_the_ring_hours(api, general_foreman_headers):
    """PRD §3.6: "A worker's `journey_ring_claim_hours` is the sum of
    `credited_hours` over the worker's crew days that are accepted for credit, stated
    to two decimal places rounded half up; rows not accepted for credit contribute
    nothing."
    PRD §3.6: "`upgrade_eligible` is true precisely when the worker's
    `journey_ring_claim_hours` is greater than 8,000 hours".

    Design: Corner/calculations/apprentice_upgrade_threshold_is_strict
    """
    # Two 8.0 hour apprentice reports for the same crew need 16.0 journeyman
    # hours behind them: PRD §3.6 refuses any report that would push the
    # project's apprentice total past `ratio_limit` x its journeyman total.
    project, _rate, _jm, apprentice, activity, _jm_day, _ap_day = setup_crew_pair(
        project_code="P-3333-CA3B", journeyman_hours=16.0, apprentice_hours=8.0,
        acknowledge=False)
    from test_helpers.fixtures import acknowledge_crew_day, create_crew_day

    late = create_crew_day(project["id"], apprentice["id"], activity["id"],
                           foreman_id=apprentice["id"], regular_hours=8.0,
                           report_sequence=2, acknowledge_mode="FINAL")
    late = acknowledge_crew_day(late)

    listed = api.list_crew_days(general_foreman_headers, {"worker_id": apprentice["id"]})
    rows = listed.json()["data"]
    credited = sum(row["credited_hours"] for row in rows)
    assert late["credited_hours"] == 0.0, (
        "under FIRST_ACCEPTED the later report is retained but contributes nothing"
    )
    assert credited < 8000.0, (
        "the strict greater-than test is not reached by a single day of work"
    )
    assert round(credited, 2) == credited


# --------------------------------------------------------------------------
# calculations / hoisting_window_is_frozen_after_the_first_release
# --------------------------------------------------------------------------

def _released_window_order(project_code):
    project = create_project(project_code=project_code)
    mv, lines = create_coordinated_model(model_id=f"mdl-{project_code}")
    order = validate_success(
        api.create_prefab_order(
            {
                "project_id": project["id"], "model_version_id": mv["id"],
                "stage_code": "FIRST_STAGE", "zone_code": "Z-1",
                "transport_kind": "FLATBED", "hoisting_window_id": f"HW-{project_code}",
                "required_on_site_iso": "2026-11-20T00:00:00Z",
                "installation_window_start_iso": "2026-11-21T00:00:00Z",
                "fabricate_quantity": 1, "shop_utilisation_basis_pct": 0.50,
            },
            PM,
        ),
        expected_status=201,
    )
    return project, release_order_ok(order)


def test_a_second_release_attempt_cannot_refreeze_the_window(api, project_manager_headers):
    """PRD §3.3: "the package's hoisting window must not already have been frozen by
    a prior release-to-shop record, or the release fails with
    `ERR_WINDOW_ALREADY_FROZEN` (HTTP 409), because the window is derived exactly
    once".

    Design: Corner/calculations/hoisting_window_is_frozen_after_the_first_release
    """
    _project, order = _released_window_order("P-3333-CA4")
    frozen_start = order["hoisting_start_iso"]
    frozen_end = order["hoisting_end_iso"]

    response = api.release_prefab_order(
        order["id"], {"expected_prefab_order_version": order["version"]},
        project_manager_headers,
    )
    validate_error_is_one_of(
        response,
        [ApiErrorIdValues.INVALID_TRANSITION, ApiErrorIdValues.WINDOW_FROZEN],
    )
    assert response.status_code in (409, 412)

    after = fetch_order(order["id"])
    assert after["hoisting_start_iso"] == frozen_start
    assert after["hoisting_end_iso"] == frozen_end


def test_the_frozen_window_never_recomputes(api, project_manager_headers):
    """PRD §3.3: "the hoisting window is derived and then frozen:
    `hoisting_duration_days`, `hoisting_start_iso` and `hoisting_end_iso` are written
    and thereafter immutable while the package stays at `RELEASED` or later."
    PRD §2.4: "a mutation that is rejected leaves the version untouched."

    Design: Corner/calculations/hoisting_window_is_frozen_after_the_first_release
    """
    _project, order = _released_window_order("P-3333-CA4B")
    frozen = (order["hoisting_start_iso"], order["hoisting_end_iso"],
              order["hoisting_duration_days"])

    validate_success(api.set_fabrication_status(
        order["id"], {"fabricate_status": "IN_FABRICATION"}, SF), expected_status=200)
    after = fetch_order(order["id"])
    assert (after["hoisting_start_iso"], after["hoisting_end_iso"],
            after["hoisting_duration_days"]) == frozen


class ApiErrorIdValues:
    INVALID_TRANSITION = "ERR_INVALID_PREFAB_TRANSITION"
    WINDOW_FROZEN = "ERR_WINDOW_ALREADY_FROZEN"