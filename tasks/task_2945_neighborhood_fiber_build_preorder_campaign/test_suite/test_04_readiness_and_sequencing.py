"""Readiness-score composition and the build-order the sequencing run writes."""

from test_helpers import (
    PM,
    CLOCK_AFTER_DEADLINE,
    api_client,
    assert_cents,
    assert_pct,
    assert_two_decimal_places,
    make_account,
    make_address,
    make_campaign,
    make_permit,
    make_pole_request,
    make_preorder,
    make_zone,
    read_zone,
    set_clock,
    set_serviceability,
    setup_zone_with_preorders,
    validate_success,
)

BOTH_PERMIT_TYPES = ["ROW", "TRAFFIC_CONTROL"]
HEAVY_MAKE_READY_CENTS = 500000
UNACCEPTED_QUOTE_CENTS = 60000


def _two_qualified_zones_with_different_readiness():
    """One high-demand zone carrying heavy make-ready, one lower-demand zone carrying none.

    The first zone beats its bar twofold, holds only one of its two required permits
    and has an ATTACHED pole request quoted at 500,000 cents. The second sits exactly
    on its bar, holds both permits and has a pole request left at SURVEYED, so no
    make-ready cost was ever accepted onto it.
    """
    set_clock()
    campaign = make_campaign(default_threshold_pct=10.0, deposit_amount_cents=1000)
    heavy = make_zone(
        campaign["id"],
        name="Zone Alpha",
        zone_code="A1",
        household_count=10,
        threshold_pct=10.0,
        required_permit_types=list(BOTH_PERMIT_TYPES),
    )
    light = make_zone(
        campaign["id"],
        name="Zone Bravo",
        zone_code="B1",
        household_count=10,
        threshold_pct=10.0,
        required_permit_types=list(BOTH_PERMIT_TYPES),
    )
    plan = [
        (heavy, "1 Elm St", 100, 0),
        (heavy, "3 Elm St", 105, 1),
        (light, "10 Oak Ave", 95, 2),
    ]
    for zone, street, distance, account_index in plan:
        address = make_address(
            zone["id"], street_address=street, distance_to_node_m=distance
        )
        address = set_serviceability(address["id"], "SERVICEABLE")
        account = make_account(account_index)
        make_preorder(zone["id"], address["id"], account["id"])

    make_permit(heavy["id"], permit_type="ROW", target_status="APPROVED")
    make_permit(heavy["id"], permit_type="TRAFFIC_CONTROL", target_status="SUBMITTED")
    make_pole_request(
        heavy["id"],
        target_status="ATTACHED",
        make_ready_cost_cents=HEAVY_MAKE_READY_CENTS,
    )

    for permit_type in BOTH_PERMIT_TYPES:
        make_permit(light["id"], permit_type=permit_type, target_status="APPROVED")
    make_pole_request(
        light["id"],
        target_status="SURVEYED",
        make_ready_cost_cents=UNACCEPTED_QUOTE_CENTS,
    )

    set_clock(CLOCK_AFTER_DEADLINE)
    validate_success(api_client.qualification_run(campaign["id"], PM))
    return {"campaign": campaign, "heavy": heavy, "light": light}


def test_demand_factor_is_capped_and_the_pole_factor_takes_the_best_request():
    """Twice the bar earns no more than once the bar, and 500,000 cents costs 7.50 points.

    PRD 3.5: "The raw score is the demand factor multiplied by 50, plus the permit factor
    multiplied by 25, plus the pole factor multiplied by 20, minus the make-ready penalty.
    That raw value is rounded half up to two decimal places exactly once, after composition,
    and the result is written to `readiness_score`"

    Design: Difficulty/combinatorial_formula/readiness_score_nonlinear_min_max_composition
    """
    world = _two_qualified_zones_with_different_readiness()

    validate_success(api_client.sequencing_run(world["campaign"]["id"], PM))

    zone = read_zone(world["heavy"]["id"])
    assert_pct(zone["final_rate_pct"], 20.00, "final_rate_pct")
    assert_cents(
        zone["make_ready_cost_cents"], HEAVY_MAKE_READY_CENTS, "make_ready_cost_cents"
    )
    assert_pct(zone["readiness_score"], 75.00, "readiness_score")
    assert_two_decimal_places(zone["readiness_score"], "readiness_score")


def test_a_pole_request_left_at_survey_scores_a_quarter_and_costs_no_penalty():
    """A surveyed-only quote never enters make_ready_cost_cents, so the penalty term is zero.

    PRD 3.5: "each request contributes 1.00 when its status is `ATTACHED`, 0.50 when
    `ACCEPTED`, 0.25 when `SURVEYED`, 0.10 when `REQUESTED` and 0.00 when `DENIED`, and the
    pole factor is the largest of those contributions, or 0.00 when the zone has no requests
    at all."

    Design: Difficulty/combinatorial_formula/readiness_score_nonlinear_min_max_composition
    """
    world = _two_qualified_zones_with_different_readiness()

    validate_success(api_client.sequencing_run(world["campaign"]["id"], PM))

    zone = read_zone(world["light"]["id"])
    assert_pct(zone["final_rate_pct"], 10.00, "final_rate_pct")
    assert_cents(zone["make_ready_cost_cents"], 0, "make_ready_cost_cents")
    assert_pct(zone["readiness_score"], 80.00, "readiness_score")


def test_sequencing_ranks_by_score_descending_and_writes_a_one_based_index():
    """The 80.00 zone is built first even though the 75.00 zone has twice the demand.

    PRD 3.5: "The run then ranks the campaign's qualified zones by `readiness_score`
    descending, breaking ties by the earlier `prereg_deadline_at`, then by the larger
    `household_count`, then by the earlier `created_at`, and writes `build_sequence_index` as
    the one-based position in that order."

    Design: Difficulty/combinatorial_formula/readiness_score_nonlinear_min_max_composition
    """
    world = _two_qualified_zones_with_different_readiness()

    validate_success(api_client.sequencing_run(world["campaign"]["id"], PM))

    light = read_zone(world["light"]["id"])
    heavy = read_zone(world["heavy"]["id"])
    assert light["build_sequence_index"] == 1, light["build_sequence_index"]
    assert heavy["build_sequence_index"] == 2, heavy["build_sequence_index"]
    for zone in (light, heavy):
        assert zone["construction_status"] == "SEQUENCED", zone["construction_status"]


def test_zones_that_never_qualified_keep_null_score_and_null_index():
    """A zone still inside its window is skipped entirely by the run.

    PRD 3.5: "It considers only zones whose `campaign_status` is `QUALIFIED`; zones sitting
    in `PREREG_OPEN`, `PREREG_EXTENDED` or `NOT_QUALIFIED` are skipped entirely, keeping
    `readiness_score` and `build_sequence_index` null and receiving no `version` bump at
    all."

    Design: Difficulty/combinatorial_formula/readiness_score_nonlinear_min_max_composition
    """
    base = setup_zone_with_preorders(preorder_count=1, household_count=10, threshold_pct=10.0)
    failing = make_zone(
        base["campaign"]["id"],
        name="Zone Charlie",
        zone_code="C1",
        household_count=40,
        threshold_pct=50.0,
    )
    set_clock(CLOCK_AFTER_DEADLINE)
    validate_success(api_client.qualification_run(base["campaign"]["id"], PM))
    before = read_zone(failing["id"])

    validate_success(api_client.sequencing_run(base["campaign"]["id"], PM))

    after = read_zone(failing["id"])
    assert after["campaign_status"] == "NOT_QUALIFIED", after["campaign_status"]
    assert after["readiness_score"] is None, after["readiness_score"]
    assert after["build_sequence_index"] is None, after["build_sequence_index"]
    assert after["version"] == before["version"], (before["version"], after["version"])
