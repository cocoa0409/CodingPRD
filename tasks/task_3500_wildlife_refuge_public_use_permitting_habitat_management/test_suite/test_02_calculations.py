"""Permit fee and population-objective calculations.

Covers the provisional-vs-assessed fee divergence, tiered crew pricing with
the commercial surcharge, both crew-tier boundaries, the fee floor and cap,
and the 70-percent population objective threshold.
"""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success,
    create_unit, create_final_determination,
    create_submitted_permit, create_under_review_permit,
    create_population_objective, record_survey,
    create_return_for_revision_payload,
    make_permit_applicant_headers,
)


def _approve(permit_id):
    resp = api_client.approve_permit(
        permit_id, TEST_USERS["permit_officer_headers"])
    return validate_success(resp)


def test_permit_fee_provisional_vs_assessed_diverge(api):
    """PRD §3.3: "Crew size, trip length, tiering, surcharge, floor, and cap
    are all ignored at this stage, so the provisional figure and the eventual
    assessed figure differ for identical application data: a research
    application for a crew of four over three days shows 15000 cents
    provisionally and will assess at 21000 cents."

    Design: Difficulty/dual_variant_calc/permit_fee_provisional_vs_assessed_diverge
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_submitted_permit(
        unit["id"], det["id"], applicant_ref="app-1", crew_size=4,
        start_date="2026-10-10", end_date="2026-10-12")
    provisional = permit["provisional_fee_cents"]
    api_client.return_permit_for_revision(
        permit["id"], create_return_for_revision_payload(note="Need methods detail."),
        TEST_USERS["permit_officer_headers"])
    api_client.resubmit_permit(
        permit["id"], {}, make_permit_applicant_headers("app-1"))
    approved = _approve(permit["id"])
    assessed = approved["assessed_fee_cents"]
    assert provisional == 15000, (
        f"provisional must be the flat RESEARCH base 15000, got {provisional}")
    assert assessed == 21000, (
        f"assessed must be 15000 + 2000 x 3 x 1.0 = 21000, got {assessed}")
    assert provisional != assessed, (
        "the two fee variants must diverge on identical application data")


def test_assessed_fee_tiered_crew_surcharge_mode_a(api):
    """PRD §3.3: "A flat surcharge of 10000 cents is added for
    `COMMERCIAL_FILMING` only."
    PRD §3.3: "1.0 for a crew of nine or fewer, 1.25 for a crew of ten through
    nineteen, and 1.5 for a crew of twenty or more."

    Design: Difficulty/combinatorial_formula/assessed_fee_tiered_crew_surcharge_mode_a
    """
    unit = create_unit(name="River Bluffs", habitat_type="FOREST", acreage=2400)
    det = create_final_determination(use_type="COMMERCIAL_FILMING")
    permit = create_under_review_permit(
        unit["id"], det["id"], applicant_ref="studio-1",
        use_type="COMMERCIAL_FILMING", crew_size=25,
        start_date="2026-10-10", end_date="2026-10-12")
    approved = _approve(permit["id"])
    assert approved["status"] == "APPROVED"
    assert approved["assessed_fee_cents"] == 52500, (
        "20000 base + round(5000 x 3 x 1.5)=22500 + 10000 surcharge = 52500, "
        f"got {approved['assessed_fee_cents']}")


def test_crew_size_20_crosses_large_tier_boundary(api):
    """PRD §3.3: "1.0 for a crew of nine or fewer, 1.25 for a crew of ten
    through nineteen, and 1.5 for a crew of twenty or more."

    Design: Difficulty/boundary_precision_check/crew_size_20_crosses_large_tier_boundary
    """
    unit = create_unit(name="River Bluffs", habitat_type="FOREST", acreage=2400)
    det = create_final_determination(use_type="COMMERCIAL_FILMING")
    permit19 = create_under_review_permit(
        unit["id"], det["id"], applicant_ref="studio-19",
        use_type="COMMERCIAL_FILMING", crew_size=19,
        start_date="2026-10-10", end_date="2026-10-10")
    permit20 = create_under_review_permit(
        unit["id"], det["id"], applicant_ref="studio-20",
        use_type="COMMERCIAL_FILMING", crew_size=20,
        start_date="2026-10-11", end_date="2026-10-11")
    fee19 = _approve(permit19["id"])["assessed_fee_cents"]
    fee20 = _approve(permit20["id"])["assessed_fee_cents"]
    assert fee19 == 36250, (
        f"crew 19 MEDIUM tier: 20000 + round(5000 x 1 x 1.25) + 10000 = 36250, "
        f"got {fee19}")
    assert fee20 == 37500, (
        f"crew 20 LARGE tier: 20000 + round(5000 x 1 x 1.5) + 10000 = 37500, "
        f"got {fee20}")
    assert fee20 - fee19 == 1250


def test_fee_floor_applies_to_guided_activity(api):
    """PRD §2.8: "Permit fees are additionally bounded: after the full
    assessed computation, the result is capped at a fee ceiling of 100000
    cents and then raised to at least a fee floor of 5000 cents — the cap
    applies first, the floor second."

    Design: Corner/calculations/fee_floor_applies_to_guided_activity
    """
    unit = create_unit(name="Visitor Center Unit", habitat_type="MIXED", acreage=500)
    det = create_final_determination(use_type="GUIDED_ACTIVITY")
    permit = create_under_review_permit(
        unit["id"], det["id"], applicant_ref="guide-1",
        use_type="GUIDED_ACTIVITY", crew_size=1,
        start_date="2026-10-10", end_date="2026-10-10")
    approved = _approve(permit["id"])
    assert permit["provisional_fee_cents"] == 3000, (
        f"provisional must be the flat GUIDED_ACTIVITY base 3000, "
        f"got {permit['provisional_fee_cents']}")
    assert approved["assessed_fee_cents"] == 5000, (
        f"raw 3800 must be lifted to the 5000 floor, "
        f"got {approved['assessed_fee_cents']}")


def test_fee_cap_applies_to_large_commercial(api):
    """PRD §3.3: "The raw result is then capped at the ceiling of 100000
    cents, and finally raised to at least the floor of 5000 cents — cap first,
    floor second."

    Design: Corner/calculations/fee_cap_applies_to_large_commercial
    """
    unit = create_unit(name="River Bluffs", habitat_type="FOREST", acreage=2400)
    det = create_final_determination(use_type="COMMERCIAL_FILMING")
    permit = create_under_review_permit(
        unit["id"], det["id"], applicant_ref="studio-1",
        use_type="COMMERCIAL_FILMING", crew_size=50,
        start_date="2026-10-01", end_date="2026-10-30")
    approved = _approve(permit["id"])
    assert approved["assessed_fee_cents"] == 100000, (
        f"raw 255000 must be capped at 100000, "
        f"got {approved['assessed_fee_cents']}")


def test_crew_tier_medium_boundary_9_vs_10(api):
    """PRD §3.3: "1.0 for a crew of nine or fewer, 1.25 for a crew of ten
    through nineteen, and 1.5 for a crew of twenty or more."

    Design: Corner/calculations/crew_tier_medium_boundary_9_vs_10
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit9 = create_under_review_permit(
        unit["id"], det["id"], applicant_ref="app-9", crew_size=9,
        start_date="2026-10-10", end_date="2026-10-10")
    permit10 = create_under_review_permit(
        unit["id"], det["id"], applicant_ref="app-10", crew_size=10,
        start_date="2026-10-10", end_date="2026-10-10")
    fee9 = _approve(permit9["id"])["assessed_fee_cents"]
    fee10 = _approve(permit10["id"])["assessed_fee_cents"]
    assert fee9 == 17000, (
        f"crew 9 SMALL tier: 15000 + 2000 x 1 x 1.0 = 17000, got {fee9}")
    assert fee10 == 17500, (
        f"crew 10 MEDIUM tier: 15000 + 2000 x 1 x 1.25 = 17500, got {fee10}")


def test_population_objective_threshold_at_70_percent(api):
    """PRD §3.9: "The test is an integer comparison with no floating point:
    the objective is `AT_TARGET` when ten times the survey count is at least
    seven times the target count, and `BELOW_TARGET` otherwise — so a survey
    count of exactly seventy percent of the target satisfies the objective,
    and one short of that does not."
    PRD §3.9: "A fresh objective stands in `NO_SURVEY` with its
    `current_survey_count` still null: until the first survey lands, there is
    nothing to measure."

    Design: Corner/calculations/population_objective_threshold_at_70_percent
    """
    unit = create_unit()
    objective = create_population_objective(
        unit["id"], species="Sandhill Crane", target_count=1000)
    assert objective["status"] == "NO_SURVEY"
    at_target = record_survey(objective["id"], 700)
    assert at_target["status"] == "AT_TARGET", (
        f"survey 700 on target 1000 must satisfy AT_TARGET (7000 >= 7000), "
        f"got {at_target['status']}")
    below = record_survey(objective["id"], 699)
    assert below["status"] == "BELOW_TARGET", (
        f"survey 699 must fall BELOW_TARGET (6990 < 7000), got {below['status']}")
