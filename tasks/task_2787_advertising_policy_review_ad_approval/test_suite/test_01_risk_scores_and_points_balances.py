"""Two pairs of same-subject figures that are deliberately allowed to disagree.

A creative carries a provisional and a final risk score at the same instant, and
an advertiser carries a raw and a decayed points balance at the same instant. Both
pairs are recomputed from their inputs, and in both pairs the divergence is a
contract, not an artefact.
"""

import pytest

from test_helpers import (
    ADMIN,
    fixtures,
)

ALC_SPIRITS = "ALC_SPIRITS"


def _spirits_rule(**overrides):
    """The ALC_SPIRITS rule: RESTRICTED, weight 6.00, licence and disclaimer demanded."""
    payload = {
        "title": "Alcohol - spirits",
        "requires_certification": True,
        "requires_disclaimer": True,
        "confidence_auto_disapprove_threshold": 0.90,
        "confidence_manual_threshold": 0.55,
        "review_sla_hours": 48,
        "default_queue": "REGULATED_CERT",
    }
    payload.update(overrides)
    return fixtures.create_policy_rule(ALC_SPIRITS, "RESTRICTED", 6.00, **payload)


def _covered_us_creative_screened_at_080():
    """A US spirits creative with an ACTIVE licence, screened at confidence 0.80.

    The US variation carries `severity_multiplier` 1.50, so the single finding
    contributes 6.00 * 1.50 * 0.80 = 7.20 to the provisional score, and the held
    licence earns the 8.00 certification credit against the final score.
    """
    rule = _spirits_rule()
    fixtures.add_country_override(
        rule["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        requires_disclaimer=True,
        severity_multiplier=1.50,
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Northline Spirits LLC", industry_code="ALCOHOL_RETAIL"
    )
    certification = fixtures.create_certification(
        advertiser["id"],
        rule["id"],
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2027-01-01T00:00:00Z",
        license_number="US-SPIRITS-4471",
    )
    submitted = fixtures.submitted_creative(
        advertiser["id"],
        [ALC_SPIRITS],
        ["US"],
        headline="Small-batch bourbon delivered",
        body_text="Order our single-barrel bourbon online today.",
        landing_page_url="https://www.northline.example/bourbon",
        display_url="https://www.northline.example/bourbon",
        disclaimer_text="Drink responsibly. 21+",
    )
    run = fixtures.screen_creative(
        submitted["id"], [(rule["id"], 0.80)], submitted["version"], "clf-2026.07"
    )
    return {
        "rule": rule,
        "advertiser": advertiser,
        "certification": certification,
        "creative_id": submitted["id"],
        "run": run,
    }


def test_certification_credit_drives_the_final_score_below_the_provisional_score():
    """The same creative reads 7.20 provisional and 0.00 final at the same instant.

    PRD §3.4: "The provisional score, stored as `risk_score_provisional` and
    mirrored onto the run's `provisional_risk_score`, is what the screening layer
    publishes before any destination evidence or licence credit exists."
    PRD §3.4: "The certification credit rewards licences actually held: count the
    distinct rules among the findings for which the licence-coverage test of §3.5
    returns at least one candidate certification, at the current logical clock, for
    at least one of the creative's target countries; multiply that count by 8.00;
    and cap the credit at 24.00, so three covered rules already exhaust it."

    Design: Difficulty/dual_variant_calc/creative_risk_provisional_vs_final_diverge_across_cert_credit_and_mismatch_penalty
    """
    bundle = _covered_us_creative_screened_at_080()

    assert bundle["certification"]["status"] == "ACTIVE"
    assert bundle["run"]["outcome"] == "ROUTED_MANUAL"
    assert bundle["run"]["provisional_risk_score"] == pytest.approx(7.20, abs=0.01)

    creative = fixtures.read_creative(bundle["creative_id"], headers=ADMIN)
    assert creative["review_status"] == "PENDING_MANUAL_REVIEW"
    assert creative["destination_status"] == "DESTINATION_PENDING"
    assert creative["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)
    assert creative["risk_score_final"] == pytest.approx(0.00, abs=0.01)


def test_host_mismatch_penalty_lifts_the_final_score_above_the_provisional_score():
    """A host mismatch leaves the provisional score alone and reverses the ordering.

    PRD §3.4: "The destination penalty is 40.00 when the creative's
    `destination_status` is `CLOAKING_CONFIRMED`, 15.00 when it is
    `MISMATCH_FLAGGED`, and 0.00 in the three remaining cases `NOT_CHECKED`,
    `DESTINATION_PENDING` and `DESTINATION_CLEARED`."
    PRD §3.4: "Because the provisional score is rounded before it enters this
    expression while the two adjustments are exact, the two scores may diverge by
    more than a rounding artifact — that divergence is intended, and either score may
    be the larger of the two depending on whether penalty or credit dominates."

    Design: Difficulty/dual_variant_calc/creative_risk_provisional_vs_final_diverge_across_cert_credit_and_mismatch_penalty
    """
    bundle = _covered_us_creative_screened_at_080()

    check = fixtures.record_destination_check(
        bundle["creative_id"],
        "https://promo-partner.example/bourbon",
        fetched_content_category=ALC_SPIRITS,
    )
    assert check["result"] == "MISMATCH"
    assert check["mismatch_detail"] == "HOST_MISMATCH"

    creative = fixtures.read_creative(bundle["creative_id"], headers=ADMIN)
    assert creative["destination_status"] == "MISMATCH_FLAGGED"
    assert creative["review_status"] == "PENDING_MANUAL_REVIEW"
    assert creative["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)
    assert creative["risk_score_final"] == pytest.approx(14.20, abs=0.01)


def _auto_disapproved_nordic_creative():
    """A spirits creative blocked in SE and auto-disapproved at confidence 0.95.

    The SE variation is `BLOCKED` at `severity_multiplier` 2.00, which is the
    strictest multiplier across the creative's SE and US targets.
    """
    rule = _spirits_rule()
    fixtures.add_country_override(
        rule["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        requires_disclaimer=True,
        severity_multiplier=1.50,
    )
    fixtures.add_country_override(
        rule["id"], "SE", "BLOCKED", severity_multiplier=2.00
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Northline Spirits LLC", industry_code="ALCOHOL_RETAIL"
    )
    submitted = fixtures.submitted_creative(
        advertiser["id"],
        [ALC_SPIRITS],
        ["SE", "US"],
        headline="Nordic spirits sale",
        body_text="Buy imported spirits with free shipping.",
        landing_page_url="https://www.northline.example/nordic",
        display_url="https://www.northline.example/nordic",
        disclaimer_text="Drink responsibly. 21+",
    )
    run = fixtures.screen_creative(
        submitted["id"], [(rule["id"], 0.95)], submitted["version"], "clf-2026.07"
    )
    return {"rule": rule, "advertiser": advertiser, "creative_id": submitted["id"], "run": run}


def test_a_fresh_assessment_leaves_both_points_balances_equal():
    """At the instant of assessment raw and decayed agree, and neither triggers action.

    PRD §3.9: "The raw balance, stored as `violation_points_raw` and disclosed to
    the advertiser through a notice's `disclosed_points_total`, is the sum of every
    entry's `delta_points` at full weight forever, rounded half-up to 2 decimals and
    floored at 0.00."
    PRD §3.9: "the entry then counts at full weight while its age is under 90 days,
    at half weight once its age is at least 90 days but still under 180 days, and at
    zero weight once its age is 180 days or more."

    Design: Difficulty/dual_variant_calc/advertiser_points_raw_vs_decayed_diverge_after_ninety_two_days
    """
    bundle = _auto_disapproved_nordic_creative()

    assert bundle["run"]["outcome"] == "AUTO_DISAPPROVED"
    assert bundle["run"]["provisional_risk_score"] == pytest.approx(11.40, abs=0.01)

    advertiser = fixtures.read_advertiser(bundle["advertiser"]["id"])
    assert advertiser["violation_points_raw"] == pytest.approx(9.60, abs=0.01)
    assert advertiser["violation_points_decayed"] == pytest.approx(9.60, abs=0.01)
    assert advertiser["severity_index"] == pytest.approx(9.60, abs=0.01)
    assert advertiser["account_status"] == "ACTIVE"
    assert fixtures.actions_for_advertiser(bundle["advertiser"]["id"]) == []

    entries = fixtures.ledger_for_advertiser(bundle["advertiser"]["id"])
    assert len(entries) == 1
    assert entries[0]["delta_points"] == pytest.approx(9.60, abs=0.01)
    assert entries[0]["reason"] == "DISAPPROVAL_ASSESSED"
    assert entries[0]["balance_after"] == pytest.approx(9.60, abs=0.01)
    assert entries[0]["entry_index"] == 1


def test_after_ninety_two_days_only_the_decayed_balance_halves():
    """The raw balance is untouched by age while the decayed balance halves.

    PRD §3.9: "The decayed balance, stored as `violation_points_decayed`, weights
    each entry by its own age: compute the entry's age in whole days by taking the
    difference between the logical clock and the entry's `created_at` in seconds,
    dividing by 86400 and discarding the fraction; the entry then counts at full
    weight while its age is under 90 days, at half weight once its age is at least 90
    days but still under 180 days, and at zero weight once its age is 180 days or
    more."
    PRD §3.9: "The decayed balance is refreshed by every ledger insert and again by
    the sweep's sixth phase, and it is the only one of the two that can create or
    lift an enforcement action."

    Design: Difficulty/dual_variant_calc/advertiser_points_raw_vs_decayed_diverge_after_ninety_two_days
    """
    bundle = _auto_disapproved_nordic_creative()

    counts = fixtures.advance_clock_and_sweep("2026-11-01T00:00:00Z")
    assert counts["expired_notices"] == 1
    assert counts["decay_refreshed_advertisers"] == 1

    advertiser = fixtures.read_advertiser(bundle["advertiser"]["id"])
    assert advertiser["violation_points_raw"] == pytest.approx(9.60, abs=0.01)
    assert advertiser["violation_points_decayed"] == pytest.approx(4.80, abs=0.01)
    assert advertiser["severity_index"] == pytest.approx(4.80, abs=0.01)
    assert advertiser["account_status"] == "ACTIVE"

    entries = fixtures.ledger_for_advertiser(bundle["advertiser"]["id"])
    assert len(entries) == 1, "the sweep never writes or rewrites a ledger entry"
    assert entries[0]["delta_points"] == pytest.approx(9.60, abs=0.01)
