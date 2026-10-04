"""Uptime accounting: dual variants and the service-credit cascade (PRD §3.7, §3.9)."""

import pytest

from test_helpers import (
    get_agreement,
    setup_resolved_downtime_case,
)


def test_uptime_reported_variant_excludes_free_calibration_hours(api):
    """PRD §3.9: "The breach variant `breach_uptime_pct` counts all downtime:
    subtract from 2160 the smaller of the qualifying downtime and 2160,
    divide by 2160, and round half up to four decimal places." PRD §3.9: "The
    reporting variant `reported_uptime_pct` forgives routine calibration:
    from the qualifying downtime subtract the smaller of the calibration
    downtime and sixteen hours (`CALIBRATION_FREE_HOURS_PER_YEAR`, 16
    hours)". One 20-hour calibration case: breach (2160-20)/2160 = 0.9907,
    reported (2160-4)/2160 = 0.9981.

    Design: Difficulty/dual_variant_calc/uptime_reported_vs_breach_variants
    """
    scenario = setup_resolved_downtime_case(
        case_type="PREVENTIVE_CALIBRATION", downtime_hours=20,
        resolution_note="calibrated",
    )
    case = scenario["service_case"]
    analyzer = scenario["analyzer"]

    assert case["downtime_hours"] == 20
    assert case["sla_met"] is True  # resolved 20h after open, due at +24h
    assert case["status"] == "RESOLVED"
    assert float(analyzer["breach_uptime_pct"]) == pytest.approx(0.9907, abs=1e-9)
    assert float(analyzer["reported_uptime_pct"]) == pytest.approx(0.9981, abs=1e-9)
    assert analyzer["operational_status"] == "IN_SERVICE"  # resolve returns the unit


def test_uptime_variants_diverge_but_grant_no_credit_above_threshold(api):
    """PRD §3.9: "The two variants diverge whenever the window contains
    calibration downtime, and both are recomputed at every case resolution."
    PRD §3.9: "When a service-case resolution leaves `breach_uptime_pct`
    strictly below 0.985 (`UPTIME_BREACH_THRESHOLD_PCT`), the placement
    agreement behind the analyzer is credited 25000 cents" — 0.9907 is not
    strictly below 0.985, so no credit lands.

    Design: Difficulty/dual_variant_calc/uptime_reported_vs_breach_variants
    """
    scenario = setup_resolved_downtime_case(
        case_type="PREVENTIVE_CALIBRATION", downtime_hours=20,
    )
    analyzer = scenario["analyzer"]
    assert analyzer["total_downtime_hours"] == 20
    assert float(analyzer["breach_uptime_pct"]) == pytest.approx(0.9907, abs=1e-9)
    assert float(analyzer["reported_uptime_pct"]) == pytest.approx(0.9981, abs=1e-9)

    agreement = get_agreement(scenario["agreement"]["id"])
    assert agreement["service_credit_cents"] == 0


def test_uptime_breach_grants_exactly_one_service_credit(api):
    """PRD §3.9: "When a service-case resolution leaves `breach_uptime_pct`
    strictly below 0.985 (`UPTIME_BREACH_THRESHOLD_PCT`), the placement
    agreement behind the analyzer is credited 25000 cents
    (`UPTIME_SERVICE_CREDIT_CENTS`), added to its `service_credit_cents` — at
    most one credit per service case". A 33-hour REPAIR: breach (2160-33)/
    2160 = 0.9847 < 0.985; REPAIR downtime is never calibration-free, so
    reported matches breach. PRD §3.7: "`sla_met` — true when `resolved_at`
    falls at or before `response_due_at`" — 33h exceeds the 24h SLA.

    Design: Corner/calculations/uptime_breach_grants_exactly_one_service_credit
    """
    scenario = setup_resolved_downtime_case(case_type="REPAIR", downtime_hours=33)
    case = scenario["service_case"]
    analyzer = scenario["analyzer"]

    assert case["downtime_hours"] == 33
    assert case["sla_met"] is False
    assert float(analyzer["breach_uptime_pct"]) == pytest.approx(0.9847, abs=1e-9)
    assert float(analyzer["reported_uptime_pct"]) == pytest.approx(0.9847, abs=1e-9)
    assert analyzer["total_downtime_hours"] == 33

    agreement = get_agreement(scenario["agreement"]["id"])
    assert agreement["service_credit_cents"] == 25000
