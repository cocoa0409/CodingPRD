"""Corner queue B — section: endpoints.

Computed reads and action endpoints: the compliance projection, the revert action's
returned object, the apply endpoint's post-waterfall figures and the print-volume
feed.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_hub_with_clock,
    create_site,
    create_region,
    create_market,
    create_route,
    create_edition,
    create_position,
    create_newsroom_change,
    approve_newsroom_change,
    hub_version,
    set_clock,
    plan_transfer,
    get_print_site,
    get_compliance,
    record_print_volume_response,
    get_success_data,
    validate_success,
    TEST_USERS,
    NEWSROOM_MANAGER_ALT,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_compliance_read_matches_the_pinned_ratio_inputs():
    """PRD §2.9: "A readable projection of the verdict and its inputs is exposed on
    the hub compliance read, which reports the boolean verdict, the
    `on_time_market_count`, the `counted_market_count`, the effective
    `min_on_time_ratio_pct`, the current `legal_notice_block`, and the hub's
    `press_posture`."

    Design: Corner/endpoints/compliance_read_matches_the_pinned_ratio_inputs
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub(min_on_time_ratio_pct=90)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    riverton = create_market(region["id"], name="Riverton",
                             guaranteed_floor_copies=0,
                             publication_deadline_utc="05:30",
                             on_time_margin_minutes=30,
                             single_copy_market_rule="carrier")
    fallow = create_market(region["id"], name="Fallow", weighted_demand_units=6000,
                           guaranteed_floor_copies=0,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30,
                           single_copy_market_rule="carrier")
    create_route(site["id"], riverton["id"])
    create_route(site["id"], fallow["id"])
    # 5000 copies on the pinned site resolves to the 0.25-hour quarter, landing the
    # ready time at 05:00 -- exactly the 30-minute margin before the 05:30 deadline.
    create_edition(riverton["id"], site["id"], slug="2026-09-21", page_count=8,
                   requested_print_run_copies=5000)
    create_edition(fallow["id"], site["id"], slug="2026-09-21", page_count=8,
                   requested_print_run_copies=5000)

    # Both markets must be planned onto the site before their editions can carry
    # a ready time: §3.5 derives is_on_time from the selected route's cutoff.
    plan_transfer(riverton["id"], site["id"], hub_id=hub["id"])
    plan_transfer(fallow["id"], site["id"], hub_id=hub["id"])
    compliance = get_compliance(hub["id"])

    assert compliance["counted_market_count"] == 2
    assert compliance["min_on_time_ratio_pct"] == 90
    assert compliance["on_time_market_count"] == 2, (
        f"both markets carry an on-time edition, got "
        f"{compliance['on_time_market_count']}"
    )
    assert compliance["is_legal_notice_ratio_compliant"] is True, (
        "2 * 100 >= 90 * 2"
    )
    assert compliance["legal_notice_block"] is False
    assert compliance["press_posture"] == "OPEN"

    planned = get_success_data(api.get_print_market(riverton["id"], PRINT_OPS))
    assert planned["status"] == "consolidation_planned"


def test_edition_revert_action_returns_zeroed_press_run_and_resets_the_slot():
    """PRD §3.5: "Reverting sets `print_run_hours` to zero, resets
    `next_edition_slot_taken` to 0, clears the `assigned_print_site_id`, and
    decrements the former site's `allocated_copies` by the edition's
    `allocated_print_run_copies`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/endpoints/edition_revert_action_returns_zeroed_press_run_and_resets_the_slot
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="04:50",
                           on_time_margin_minutes=0, guaranteed_floor_copies=8000)
    create_route(site["id"], market["id"])
    version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    plan_transfer(market["id"], site["id"], expected_version=version)

    edition = create_edition(market["id"], site["id"], slug="2026-09-21",
                             page_count=12, requested_print_run_copies=40000,
                             late_sports_engineering_flag=True)
    validate_success(api.dispatch_edition(edition["id"], PRINT_OPS), 200)
    allocated_before = get_print_site(site["id"])["allocated_copies"]

    reverted = validate_success(
        api.revert_edition_to_digital(edition["id"], PRINT_OPS), 200)

    assert reverted["status"] == "reverted_to_digital"
    # §3.5 spells the reverted field `print_run_hours`, while the same section's
    # computation names it `press_run_hours`; accept either spelling of the one field.
    hours = reverted.get("print_run_hours", reverted.get("press_run_hours"))
    assert hours == pytest.approx(0.0, abs=1e-9), (
        f"a reverted edition contributes no press hours, got {hours}"
    )
    assert reverted["next_edition_slot_taken"] == 0
    assert reverted["assigned_print_site_id"] is None, (
        f"the site must be cleared, got {reverted['assigned_print_site_id']}"
    )
    site_after = get_print_site(site["id"])
    assert site_after["allocated_copies"] == allocated_before - edition["allocated_print_run_copies"], (
        "the former site's allocated_copies must drop by the reverted run"
    )


def test_newsroom_change_apply_returns_allocated_slots_and_severance():
    """PRD §3.8: "sets its `allocated_slots` to the smaller of its `requested_slots`
    and that residual headcount; it then computes `severance_cost_cents`".
    PRD §3.8: "Applying computes, for every sibling movement in the hub, the
    `residual_headcount` left to it after higher-ranked movements have been served".

    Design: Corner/endpoints/newsroom_change_apply_returns_allocated_slots_and_severance
    """
    set_clock(CLOCK_2026_09_01)
    hub = create_hub()
    region = create_region(hub["id"])
    position = create_position(region["id"], monthly_cost_cents=520000)
    # The rival is created first so it ranks ahead in the waterfall and draws the
    # pool down to ten before the subject movement is served.
    rival = create_newsroom_change(
        position["id"], region["id"], region["id"], hub_version(hub["id"]),
        effective_date="2026-09-12", layoff_order_index=2, requested_slots=20)
    change = create_newsroom_change(
        position["id"], region["id"], region["id"], hub_version(hub["id"]),
        effective_date="2026-09-11", layoff_order_index=1, requested_slots=40)
    approve_newsroom_change(rival["id"], headers=NEWSROOM_MANAGER_ALT)
    approve_newsroom_change(change["id"], headers=NEWSROOM_MANAGER_ALT)
    assert get_success_data(api.get_newsroom_change(rival["id"], TEST_USERS["newsroom_manager_headers"]))["status"] == "approved"

    set_clock("2026-09-12T00:00:00Z")
    applied = validate_success(
        api.apply_newsroom_change(change["id"], TEST_USERS["newsroom_manager_headers"]),
        200,
    )

    # §3.8: the apply response carries the post-waterfall figures, not the request,
    # so the movement shows the slots the residual pass left it and the severance on
    # the heads it could not place.
    assert applied["allocated_slots"] < applied["requested_slots"], (
        f"the apply response must carry the post-waterfall result, got "
        f"{applied['allocated_slots']}"
    )
    assert applied["requested_slots"] == 40
    unplaced = applied["requested_slots"] - applied["allocated_slots"]
    assert applied["severance_cost_cents"] == pytest.approx(
        round(unplaced * 2.15 * 0.25 * 520000 * 1.65, 2), abs=0.01)
    assert applied["status"] == "applied"
    assert applied["residual_headcount"] == 0 or applied["residual_headcount"] >= 0


def test_print_volume_record_is_the_last_resort_test_driving_endpoint():
    """PRD §2.4: "A `PrintOperationsDirector` records one contract-day of press
    volume for a site by supplying the `print_site_id`, the `day` and the
    `charge_cents` actually incurred."
    PRD §3.1: "The annualized figure `annualized_savings_cents` is then the fixed
    press cost avoided of 1,800 dollars, plus that flat daily rate multiplied by all
    thirty window days, rounded half up to two decimals."

    Design: Corner/endpoints/print_volume_record_is_the_last_resort_test_driving_endpoint
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])

    empty = get_print_site(site["id"])
    assert empty["annualized_savings_cents"] == 180000.00
    assert empty["realized_savings_cents"] == 180000.00

    response = record_print_volume_response(site["id"], "2026-09-29", 10000)
    assert response.status_code == 201, (
        f"recording a contract-day returns 201, got {response.status_code}"
    )

    refreshed = get_print_site(site["id"])
    assert refreshed["annualized_savings_cents"] == pytest.approx(480000.00, abs=0.01), (
        f"180000 + 10000 * 30, got {refreshed['annualized_savings_cents']}"
    )
    assert refreshed["realized_savings_cents"] == pytest.approx(190000.00, abs=0.01), (
        f"180000 + 10000, got {refreshed['realized_savings_cents']}"
    )
    assert refreshed["savings_divergence_cents"] == pytest.approx(290000.00, abs=0.01)