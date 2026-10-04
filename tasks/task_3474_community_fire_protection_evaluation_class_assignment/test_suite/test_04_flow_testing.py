"""Certified flow testing: normalization literal, staleness window, correction cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    certify_flow_test,
    correct_flow_test,
    create_score_sheet,
    get_success_data,
    setup_scoring_cycle,
)

ANALYST = TEST_USERS["field_analyst_headers"]


def test_flow_normalization_certify_literal_1810(api):
    """PRD §3.4: "the `measured_flow_gpm` is multiplied by the ratio of
    `static_psi` minus the 20 psi reference residual to `static_psi` minus
    `residual_psi`, that ratio raised to the power 0.54, and the product is
    rounded half-up to a whole gallon per minute." and "Certification also
    records `certified_by`, updates the hydrant's `max_flow_gpm` and
    `last_certified_test_date` from the test, and recomputes the system's
    `active_certified_flow_gpm` and `creditworthy_hydrant_count`."

    Design: Corner/calculations/flow_normalization_certify_literal_1810
    """
    ctx = setup_scoring_cycle(
        api, name="Norman", target_state="FIELD_VERIFICATION",
        hydrant_count=1, flow_tests=[{"outcome": "witnessed"}],
    )
    test_id = ctx["flow_tests"][0]["id"]
    certified = certify_flow_test(api, test_id)
    assert certified["flow_at_20psi_gpm"] == 1810, "1000 * ((80-20)/(80-60))^0.54 rounds to 1810"
    hydrant = get_success_data(api.get_hydrant(ctx["hydrants"][0]["id"], ANALYST))
    assert hydrant["max_flow_gpm"] == 1810
    assert hydrant["last_certified_test_date"] == "2026-08-15"
    system = get_success_data(api.get_water_supply_system(ctx["system"]["id"], ANALYST))
    assert system["active_certified_flow_gpm"] == 1810
    assert system["creditworthy_hydrant_count"] == 1


def test_stale_flow_test_half_credit_and_cutoff_fresh(api):
    """PRD §3.6: "its test is fresh when `last_certified_test_date` falls no
    earlier than sixty calendar months before the cycle's `data_freeze_date`,
    and a stale hydrant's effective flow is half its `max_flow_gpm`, the
    halving applied per hydrant before any summation."

    Design: Corner/calculations/stale_flow_test_half_credit_and_cutoff_fresh
    """
    ctx = setup_scoring_cycle(
        api, name="Staleton", population=9000, area_sq_miles=18, rural_area_pct=10,
        needed_fire_flow_gpm=3000, supply_works_capacity_gpm=3000, daily_consumption_gpm=500,
        hydrant_count=3,
        flow_tests=[
            {"hydrant": 0, "test_date": "2026-08-15", "measured_flow_gpm": 1200, "outcome": "certified"},
            {"hydrant": 1, "test_date": "2021-11-30", "measured_flow_gpm": 900, "outcome": "certified"},
            {"hydrant": 2, "test_date": "2021-12-01", "measured_flow_gpm": 700, "outcome": "certified"},
        ],
    )
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    # Freeze 2026-12-01 minus 60 months is 2021-12-01: the 2021-11-30 test is
    # stale (halved to 814.5), the 2021-12-01 test is exactly at the cutoff
    # and counts fully — the comparison is strict-before.
    assert sheet["flow_points"] == pytest.approx(17.01, abs=0.005)
    assert sheet["distribution_points"] == pytest.approx(4.67, abs=0.005)
    assert sheet["water_total_points"] == pytest.approx(31.68, abs=0.005)


def _cascade_setup(api):
    return setup_scoring_cycle(
        api, name="Cascade City", population=9000, area_sq_miles=18, rural_area_pct=10,
        needed_fire_flow_gpm=3000, supply_works_capacity_gpm=4000, daily_consumption_gpm=500,
        hydrant_count=2,
        flow_tests=[
            {"hydrant": 0, "measured_flow_gpm": 1200, "outcome": "certified"},
            {"hydrant": 1, "measured_flow_gpm": 900, "outcome": "certified"},
        ],
    )


def test_flow_test_correction_replacement_and_aggregates(api):
    """PRD §3.4: "The original test becomes `SUPERSEDED`, and a replacement
    test is created directly in `CERTIFIED` status carrying the corrected
    measurements, the recorded `correction_reason`, and a
    `supersedes_test_id` pointing back to the original; the response returns
    the replacement row."

    Design: Difficulty/transitive_cascade/flow_test_correction_cascade
    """
    ctx = _cascade_setup(api)
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["status"] == "DRAFT"
    original = ctx["flow_tests"][1]
    replacement = correct_flow_test(api, original["id"], corrected_measured_flow_gpm=1100)
    assert replacement["status"] == "CERTIFIED"
    assert replacement["flow_at_20psi_gpm"] == 1991, "1100 * 3^0.54 rounds to 1991"
    assert replacement["supersedes_test_id"] == original["id"]
    superseded = get_success_data(api.get_flow_test(original["id"], ANALYST))
    assert superseded["status"] == "SUPERSEDED"
    hydrant = get_success_data(api.get_hydrant(ctx["hydrants"][1]["id"], ANALYST))
    assert hydrant["max_flow_gpm"] == 1991, "link 1: hydrant recomputed from the replacement"
    system = get_success_data(api.get_water_supply_system(ctx["system"]["id"], ANALYST))
    assert system["active_certified_flow_gpm"] == 4163, "link 2: 2172 + 1991"


def test_flow_test_correction_recomputes_draft_sheet(api):
    """PRD §3.4: "Correction then runs a three-link cascade: the hydrant's
    `max_flow_gpm` and `last_certified_test_date` are recomputed from the
    replacement (its latest certified, non-superseded test), the system
    aggregates are recomputed from the hydrants, and if the cycle is in
    `SCORING` its `DRAFT` score sheet is recomputed."

    Design: Difficulty/transitive_cascade/flow_test_correction_cascade
    """
    ctx = _cascade_setup(api)
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["flow_points"] == pytest.approx(15.20, abs=0.005)
    assert sheet["water_total_points"] == pytest.approx(29.87, abs=0.005)
    assert sheet["adjusted_total_points"] == pytest.approx(30.87, abs=0.005)
    correct_flow_test(api, ctx["flow_tests"][1]["id"], corrected_measured_flow_gpm=1100)
    recomputed = get_success_data(api.get_score_sheet(sheet["id"], ANALYST))
    assert recomputed["status"] == "DRAFT", "link 3 recomputes the same sheet in place"
    assert recomputed["flow_points"] == pytest.approx(16.65, abs=0.005)
    assert recomputed["water_total_points"] == pytest.approx(31.32, abs=0.005)
    assert recomputed["adjusted_total_points"] == pytest.approx(32.32, abs=0.005)
