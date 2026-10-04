"""Contagion propagation: the incident term, its decay bands, and the risk tier
the combined score lands in."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_account,
    get_account,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_policy,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]


def test_incident_term_accumulates_into_the_tier_bands(api):
    """PRD §2.4: "Each qualifying incident contributes a base weight — 20 for `S1`, 60 for
    `S2`, 140 for `S3` and 260 for `S4` — multiplied by a decay factor and by the incident's
    `cluster_risk_multiplier_pct` divided by 100."
    PRD §2.4: "A score of **640 or more** is `TIER_SEVERE`; otherwise **420 or more** is
    `TIER_HIGH`; otherwise **210 or more** is `TIER_ELEVATED`; otherwise `TIER_LOW`."

    Design: Difficulty/combinatorial_formula/combinatorial_risk_contagion_three_input_nonlinear
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="cy.okafor")

    # One S4 incident: 260.00, no enforcement term, no cluster link.
    make_incident(account["id"], incident_category="PHYSICAL_ASSAULT")
    one = get_account(account["id"])
    assert one["risk_score"] == pytest.approx(260.0, abs=0.005), (
        f"a single S4 incident contributes its 260 base, got {one['risk_score']}"
    )
    assert one["risk_tier"] == "TIER_ELEVATED", (
        "260.00 is at or above the 210 elevated cutoff and below the 420 high cutoff"
    )

    # A second S4 incident: 260 + 260 = 520.00.
    make_incident(account["id"], incident_category="SEXUAL_MISCONDUCT")
    two = get_account(account["id"])
    assert two["risk_score"] == pytest.approx(520.0, abs=0.005), (
        "each qualifying incident contributes its base weight independently, "
        f"got {two['risk_score']}"
    )
    assert two["risk_tier"] == "TIER_HIGH", "520.00 crosses the 420 high cutoff"

    # A third, S3 incident: 520 + 140 = 660.00.
    make_incident(account["id"], incident_category="SAFETY_VIOLATION",
                  aggravator_codes=["S3_INJURY"])
    three = get_account(account["id"])
    assert three["risk_score"] == pytest.approx(660.0, abs=0.005), (
        "the S3 incident contributes 140 on top of the two S4 bases, "
        f"got {three['risk_score']}"
    )
    assert three["risk_tier"] == "TIER_SEVERE", (
        "660.00 is at or above the 640 severe cutoff"
    )
    assert three["standing_enforcement_count"] == 0, (
        "no decision has been committed, so the enforcement term contributes exactly 0"
    )
    assert three["safety_posture"] == "OPEN"
    assert three["deactivation_count"] == 0
    assert_account(three)


def test_incident_contribution_decays_to_zero_past_the_second_band(api):
    """PRD §2.4: "The decay factor is 1.00 while the incident is **strictly less than 90
    days** old, 0.50 once it is **strictly less than 180 days** old, and 0.00 from 180 days
    onward"
    PRD §3.2: "Every release re-propagates the account's `risk_score`."

    Design: Difficulty/combinatorial_formula/combinatorial_risk_contagion_three_input_nonlinear
    """
    set_clock("2026-01-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="cy.decayed")

    incident = make_incident(account["id"], incident_category="PHYSICAL_ASSAULT")
    get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
    released = get_success_data(api_client.release_hold(incident["id"], INVESTIGATOR))
    assert released["incident_status"] == "OPEN"
    fresh = get_account(account["id"])
    assert fresh["risk_score"] == pytest.approx(260.0, abs=0.005), (
        "an incident younger than 90 days decays at 1.00, so it contributes its full base"
    )

    # A hold placed 120 days after intake leaves the incident inside the second
    # decay band, so its contribution is carried at half weight.
    set_clock("2026-05-01T00:00:00Z")
    held = get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
    assert held["incident_status"] == "INVESTIGATING"
    carried = get_account(account["id"])
    assert carried["risk_score"] == pytest.approx(130.0, abs=0.005), (
        "the incident is strictly less than 180 days old here, so the 0.50 factor applies "
        "and the S4 base of 260 is carried at exactly half weight"
    )

    # Three hundred and sixty days after intake the decay factor has fallen to 0.00.
    set_clock("2026-12-27T00:00:00Z")
    get_success_data(api_client.release_hold(incident["id"], INVESTIGATOR))

    decayed = get_account(account["id"])
    assert decayed["risk_score"] == pytest.approx(0.0, abs=0.005), (
        "from 180 days onward an incident contributes nothing at all, "
        f"got {decayed['risk_score']}"
    )
    assert decayed["risk_tier"] == "TIER_LOW"
    assert_account(decayed)