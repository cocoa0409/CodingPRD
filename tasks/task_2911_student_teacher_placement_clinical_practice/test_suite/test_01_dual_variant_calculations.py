"""Two variants of the same calculation, disagreeing on identical rows.

The readiness gate is scored either `STRICT` or `ROLLING`, and the cooperating
teacher's stipend is settled either `PROVISIONAL` or `FINAL`.  Both pairs read
exactly the same underlying evidence and are expected to produce different
numbers, so each test pins both branches and the delta between them.
"""
from test_helpers import (
    CLEARANCE_WEIGHT_POINTS,
    COMPLETION_PREMIUM_CENTS,
    CREDENTIAL_ANALYST,
    assert_agreement_ledger,
    assert_readiness,
    assert_stipend,
    complete_placement,
    factories as f,
    read_agreement,
    read_candidate,
    read_item,
    read_placement,
    set_clock,
    setup_active_placement,
    setup_completed_placement,
    setup_passed_assessment,
    validate_success,
)

EXPIRING_CLEARANCE = {"expires_on": "2026-10-01"}
LOOK_BACK_CLOCK = "2026-12-08T00:00:00Z"


def test_strict_drops_the_lapsed_clearance_that_rolling_still_counts(api):
    """The two variants score the same three items 55 and 90.

    PRD §3.2: "Under **`STRICT`**, an item counts if its `status` is `VERIFIED`
    and it either has no `expires_on` at all or its `expires_on` is on or after
    the current logical-clock date. Under **`ROLLING`**, an item counts if its
    `status` is `VERIFIED`, or if its `status` is `EXPIRED` and its `expires_on`
    is strictly later than the `start_date` of the candidate's most recent
    placement whose `placement_status` is `ACTIVE`, `REMOVAL_PENDING`,
    `REMOVED` or `COMPLETED`."

    Design: Difficulty/dual_variant_calc/readiness_strict_versus_rolling_variant_divergence_on_candidate
    """
    scenario = setup_active_placement(api, clearance=dict(EXPIRING_CLEARANCE))
    set_clock(api, LOOK_BACK_CLOCK)

    strict = validate_success(api.evaluate_readiness(
        scenario.candidate_id, f.readiness_evaluate_payload("STRICT"),
        CREDENTIAL_ANALYST))
    assert_readiness(strict, 55, "LAPSED", "STRICT")

    rolling = validate_success(api.evaluate_readiness(
        scenario.candidate_id, f.readiness_evaluate_payload("ROLLING"),
        CREDENTIAL_ANALYST))
    assert_readiness(rolling, 90, "READY", "ROLLING")

    assert rolling["readiness_score"] - strict["readiness_score"] == (
        CLEARANCE_WEIGHT_POINTS), (
        "the clearance component is the only term the two variants disagree on")


def test_the_strict_sweep_expires_the_clearance_row_it_stops_counting(api):
    """The evaluation's own lazy sweep is what drives READY to LAPSED.

    PRD §3.2: "Every readiness evaluation, whichever variant it runs under,
    first sweeps the candidate's `VERIFIED` items and lazily transitions any
    whose `expires_on` has fallen behind the clock to `EXPIRED`, bumping each
    item's own `version`."

    Design: Difficulty/dual_variant_calc/readiness_strict_versus_rolling_variant_divergence_on_candidate
    """
    scenario = setup_active_placement(api, clearance=dict(EXPIRING_CLEARANCE))
    before = read_item(api, scenario.clearance_item["id"])
    assert before["status"] == "VERIFIED"
    set_clock(api, LOOK_BACK_CLOCK)

    validate_success(api.evaluate_readiness(
        scenario.candidate_id, f.readiness_evaluate_payload("STRICT"),
        CREDENTIAL_ANALYST))

    swept = read_item(api, scenario.clearance_item["id"])
    assert swept["status"] == "EXPIRED", "the sweep moved the lapsed row"
    assert swept["expires_on"] == "2026-10-01", "the evidence itself is intact"
    assert swept["clearance_scope"] == "DISTRICT_FINGERPRINT"
    assert swept["version"] > before["version"], (
        "a lazy transition is a real mutation and bumps the row's version")

    validate_success(api.evaluate_readiness(
        scenario.candidate_id, f.readiness_evaluate_payload("ROLLING"),
        CREDENTIAL_ANALYST))
    assert_readiness(read_candidate(api, scenario.candidate_id), 55, "LAPSED")


def test_confirmation_settles_provisionally_and_completion_settles_finally(api):
    """The same placement is worth 181468 provisionally and 183968 finally.

    PRD §3.6: "Under the `PROVISIONAL` variant — the one confirmation uses,
    recorded in `stipend_variant` — the number of credited weeks is the full
    planned `weeks_scheduled` and the premium is zero."  PRD §3.9: "The premium
    is 2500 cents, and it is added only when the placement reached `COMPLETED`
    **and** its `observation_compliance_ratio` is exactly 1.0".

    Design: Difficulty/dual_variant_calc/stipend_provisional_versus_final_variant_divergence_on_placement
    """
    scenario = setup_passed_assessment(api)
    provisional = read_placement(api, scenario.placement_id)
    assert_stipend(provisional, variant="PROVISIONAL", weekly_cents=12962,
                   weeks_credited=14, gross_cents=181468, travel_cents=137886)

    set_clock(api, LOOK_BACK_CLOCK)
    final = complete_placement(api, scenario.placement_id)
    assert final["placement_status"] == "COMPLETED"
    assert_stipend(final, variant="FINAL", weekly_cents=12962,
                   weeks_credited=14, gross_cents=183968, travel_cents=137886)
    assert final["stipend_gross_cents"] - provisional["stipend_gross_cents"] == (
        COMPLETION_PREMIUM_CENTS), (
        "the credited weeks are unchanged, so the whole delta is the premium")


def test_the_variant_switch_re_derives_the_agreement_ledger(api):
    """The ledger carries the final gross, never the sum of both variants.

    PRD §2.9: "`stipend_committed_cents` is the sum of `stipend_gross_cents`
    over that agreement's placements whose `stipend_status` is `ACCRUED`,
    `APPROVED` or `PAID`".  PRD §3.9: "The agreement's
    `stipend_committed_cents` is re-derived from the new gross, but its
    `seats_committed` is **unchanged**, because a completed placement never
    leaves the committed set".

    Design: Difficulty/dual_variant_calc/stipend_provisional_versus_final_variant_divergence_on_placement
    """
    scenario = setup_completed_placement(api)
    agreement = read_agreement(api, scenario.agreement_id)
    assert_agreement_ledger(agreement, seats_reserved=0, seats_committed=1,
                            stipend_committed_cents=183968,
                            capacity_posture="CAP_REACHED")
    assert agreement["stipend_committed_cents"] != 181468 + 183968, (
        "the ledger is re-derived on the variant switch, never incremented twice")

    settled = read_placement(api, scenario.placement_id)
    assert_stipend(settled, variant="FINAL", gross_cents=183968,
                   travel_cents=137886)
