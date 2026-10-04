"""Print-run projection: authority variants and the quality-floor variant.

Every test here freezes a print run through the projection arithmetic that
PRD §3.3 specifies, and shows that the same card set freezes to different
quantities when the evidence base or the claim review state changes.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    assert_card_set,
    assert_print_run_decision,
    CARDS_PER_SET,
    CLAIM_BACKDATE_WINDOW_DAYS,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    create_print_run_decision_payload,
    create_quality_claim_payload,
    get_success_data,
    MARKET_DEMAND_UNITS_PER_CASE,
    PROJECTION_FLOOR,
    PROJECTION_MULTIPLE_OF,
    REORDER_HIT_RATE,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]
PM = TEST_USERS["product_manager_headers"]
QA = TEST_USERS["quality_analyst_headers"]
DIST = TEST_USERS["distribution_manager_headers"]


def _scenario(api, *, reserved_cases=(10, 15)):
    """Active license, READY line, approved BASE set. 20 x 10 x 10 per case."""
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api,
        line["id"],
        set_tier="BASE",
        announced=True,
        print_run_quantity=500,
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(
        approve_card_set(api, card_set["id"], card_set["version"])
    )
    for channel, cases in zip(("HOBBY", "MASS"), reserved_cases):
        get_success_data(
            api.create_allocation(
                {
                    "product_line_id": line["id"],
                    "channel": channel,
                    "quantity_allocated": cases,
                    "effective_price_cents": 72000,
                },
                DIST,
            )
        )
    line = get_success_data(api.get_product_line(line["id"], PM))
    return license_obj, line, card_set


def test_market_demand_projection_ignores_the_directive_base(api):
    """PRD §3.3: "Under `MARKET_DEMAND` the base is instead built from channel
    reservations: the platform sums `quantity_allocated` across all
    distribution allocations for the set's parent product line whose `channel`
    is either `HOBBY` or `MASS` — direct-channel reservations are excluded —
    and multiplies that sum by `MARKET_DEMAND_UNITS_PER_CASE`, which is 10
    cards per reserved case".

    Design: Difficulty/dual_variant_calc/print_run_projection_authority_vs_directive_variant
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))
    resp = api.create_print_run_decision(
        create_print_run_decision_payload(
            card_set_id=card_set["id"],
            authority="MARKET_DEMAND",
            proposed_against_line_version=line["version"],
            demand_multiplier=1.0,
            declared_quantity=1500,
            announced=True,
        ),
        PLANNER,
    )
    decision = validate_success(resp, expected_status=201)
    assert_print_run_decision(decision)
    # 10 + 15 reserved cases x 10 cards = 250 observed, raised to the BASE floor.
    observed = (10 + 15) * MARKET_DEMAND_UNITS_PER_CASE
    assert observed == 250
    assert decision["final_quantity"] == PROJECTION_FLOOR["BASE"], (
        f"observed base {observed} sits below the BASE floor "
        f"{PROJECTION_FLOOR['BASE']}, so the projection collapses to the floor"
    )


def test_market_demand_projection_rejecting_a_mismatched_declared_quantity(api):
    """PRD §3.9: "the recomputed `final_quantity` must equal the decision's
    `declared_quantity` (`ERR_INVALID_REQUEST`)".

    PRD §3.3: "Under `MARKET_DEMAND` the base is instead built from channel
    reservations: the platform sums `quantity_allocated` across all
    distribution allocations for the set's parent product line whose `channel`
    is either `HOBBY` or `MASS` — direct-channel reservations are excluded —
    and multiplies that sum by `MARKET_DEMAND_UNITS_PER_CASE`, which is 10
    cards per reserved case".

    Design: Difficulty/dual_variant_calc/print_run_projection_authority_vs_directive_variant
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))
    resp = api.create_print_run_decision(
        create_print_run_decision_payload(
            card_set_id=card_set["id"],
            authority="MARKET_DEMAND",
            proposed_against_line_version=line["version"],
            demand_multiplier=1.0,
            declared_quantity=1500,
            announced=True,
        ),
        PLANNER,
    )
    decision = get_success_data(resp)
    resp = api.approve_print_run_decision(
        decision["id"],
        {
            "expected_card_set_version": card_set["version"],
            "expected_product_line_version": line["version"],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    after = get_success_data(api.get_card_set(card_set["id"], PM))
    assert after["print_run_status"] == "UNDECIDED"


def test_brand_directive_projection_ignores_channel_reservations(api):
    """PRD §3.3: "Under `BRAND_DIRECTIVE` the platform reads no observed
    activity whatsoever: the base is simply the `BRAND_DIRECTIVE_BASE` entry
    for the tier, which is 12000 for `BASE`, 3000 for `INSERT` and 400 for
    `PREMIUM`."

    Design: Difficulty/dual_variant_calc/print_run_projection_authority_vs_directive_variant
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))
    resp = api.create_print_run_decision(
        create_print_run_decision_payload(
            card_set_id=card_set["id"],
            authority="BRAND_DIRECTIVE",
            proposed_against_line_version=line["version"],
            demand_multiplier=1.0,
            declared_quantity=12000,
            announced=True,
        ),
        PLANNER,
    )
    decision = validate_success(resp, expected_status=201)
    assert_print_run_decision(decision)
    assert decision["final_quantity"] == 12000, (
        "the directive base ignores the 250 observed cards entirely"
    )
    resp = api.approve_print_run_decision(
        decision["id"],
        {
            "expected_card_set_version": card_set["version"],
            "expected_product_line_version": line["version"],
        },
        PLANNER,
    )
    frozen = validate_success(resp)
    assert frozen["final_quantity"] == 12000
    after = get_success_data(api.get_card_set(card_set["id"], PM))
    assert after["print_run_quantity"] == 12000, (
        "the freeze writes the directive projection onto the set"
    )
    assert after["print_run_status"] == "DISCLOSED", (
        "the compound status resolves past LOCKED for an announcing decision"
    )


def test_the_two_authorities_disagree_by_a_fixed_500_cards(api):
    """PRD §3.3: "Because that dependence runs through claim review state,
    crediting a claim (which moves it out of `APPROVED`) lowers the floor again
    on the next projection."

    PRD §2.12: "once a decision is frozen it reads as `LOCKED` — and thereafter
    resolves to either `DISCLOSED` or `UNDISCLOSED` according to whether the
    frozen decision published its quantity."

    Design: Difficulty/dual_variant_calc/print_run_projection_authority_vs_directive_variant
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))

    observed = validate_success(
        api.create_print_run_decision(
            create_print_run_decision_payload(
                card_set_id=card_set["id"],
                authority="MARKET_DEMAND",
                proposed_against_line_version=line["version"],
                demand_multiplier=1.0,
                declared_quantity=1000,
                announced=True,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    directive = validate_success(
        api.create_print_run_decision(
            create_print_run_decision_payload(
                card_set_id=card_set["id"],
                authority="BRAND_DIRECTIVE",
                proposed_against_line_version=line["version"],
                demand_multiplier=1.0,
                declared_quantity=12000,
                announced=True,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert observed["final_quantity"] == 1000
    # Both decisions are proposed before either is frozen: approval supersedes
    # the set's other APPROVED decisions, so a frozen observed decision would
    # make the directive a replacement rather than a second reading of the
    # same demand evidence.
    directive_frozen = validate_success(
        api.approve_print_run_decision(
            directive["id"],
            {
                "expected_card_set_version": card_set["version"],
                "expected_product_line_version": line["version"],
            },
            PLANNER,
        )
    )
    assert directive_frozen["final_quantity"] == 12000
    assert directive_frozen["final_quantity"] > observed["final_quantity"], (
        "identical reservations, two authorities that disagree: the directive "
        "ignores the observed activity, while MARKET_DEMAND floors to the 1000 "
        "raised by the 250 cards the reservations justify"
    )
    after = get_success_data(api.get_card_set(card_set["id"], PM))
    assert after["print_run_quantity"] == 12000


def test_an_approved_claim_lifts_the_projection_by_one_whole_quantum(api):
    """PRD §3.3: "The platform takes all quality claims whose `card_set_id` is this
    set and whose `status` is `APPROVED` — a `FILED`, `UNDER_REVIEW`, `DENIED`
    or `CREDITED` claim contributes nothing — sums their `affected_quantity`
    into a verifiable total, multiplies that total by `REORDER_HIT_RATE`, the
    reorder hit rate of 0.005, to obtain a threshold, and computes a safety
    floor by ceiling that threshold up to the tier's `PROJECTION_MULTIPLE_OF`
    quantum."

    Design: Difficulty/dual_variant_calc/quality_floor_variant_flips_the_same_decision_by_review_state
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(
                claim_type="MISPRINT",
                severity="MINOR",
                affected_quantity=300000,
                filed_on="2026-09-01T00:00:00Z",
            ),
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    approved = get_success_data(api.approve_quality_claim(claim["id"], QA))
    assert approved["status"] == "APPROVED"

    threshold = int(REORDER_HIT_RATE * 300000)
    quantum = PROJECTION_MULTIPLE_OF["BASE"]
    assert threshold == 1500, "0.005 x 300000 is a 1500-card verifiable threshold"
    expected_floor = -(-threshold // quantum) * quantum
    assert expected_floor == 1500

    resp = api.create_print_run_decision(
        create_print_run_decision_payload(
            card_set_id=card_set["id"],
            authority="MARKET_DEMAND",
            proposed_against_line_version=line["version"],
            demand_multiplier=1.0,
            declared_quantity=1000,
            announced=False,
        ),
        PLANNER,
    )
    decision = validate_success(resp, expected_status=201)
    assert decision["final_quantity"] == 1000 + quantum, (
        "the safety floor raises the 1000-card authority projection by 500"
    )


def test_approved_claim_makes_the_unlifted_declared_quantity_stale_and_rejected(api):
    """PRD §3.9: "the recomputed `final_quantity` must equal the decision's
    `declared_quantity` (`ERR_INVALID_REQUEST`)".

    PRD §3.3: "a set with even a modest approved defect exposure gets its
    projection lifted by at least one whole quantum".

    Design: Difficulty/dual_variant_calc/quality_floor_variant_flips_the_same_decision_by_review_state
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(
                severity="MINOR", affected_quantity=300000, filed_on="2026-09-01T00:00:00Z"
            ),
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    get_success_data(api.approve_quality_claim(claim["id"], QA))

    decision = get_success_data(
        api.create_print_run_decision(
            create_print_run_decision_payload(
                card_set_id=card_set["id"],
                authority="MARKET_DEMAND",
                proposed_against_line_version=line["version"],
                demand_multiplier=1.0,
                declared_quantity=1000,
                announced=False,
            ),
            PLANNER,
        )
    )
    resp = api.approve_print_run_decision(
        decision["id"],
        {
            "expected_card_set_version": card_set["version"],
            "expected_product_line_version": line["version"],
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    after = get_success_data(api.get_card_set(card_set["id"], PM))
    assert after["print_run_status"] == "UNDECIDED"
    assert after["print_run_quantity"] == 500, "the set's own quantity is untouched"
    assert_card_set(after)


def test_crediting_the_claim_drops_the_next_projection_back_to_1000(api):
    """PRD §3.3: "Because that dependence runs through claim review state,
    crediting a claim (which moves it out of `APPROVED`) lowers the floor again
    on the next projection."

    Design: Difficulty/dual_variant_calc/quality_floor_variant_flips_the_same_decision_by_review_state
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(
                severity="MINOR", affected_quantity=100000, filed_on="2026-09-01T00:00:00Z"
            ),
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    get_success_data(api.approve_quality_claim(claim["id"], QA))
    credited = get_success_data(api.credit_quality_claim(claim["id"], QA))
    assert credited["status"] == "CREDITED"

    resp = api.create_print_run_decision(
        create_print_run_decision_payload(
            card_set_id=card_set["id"],
            authority="MARKET_DEMAND",
            proposed_against_line_version=line["version"],
            demand_multiplier=1.0,
            declared_quantity=1000,
            announced=False,
        ),
        PLANNER,
    )
    decision = validate_success(resp, expected_status=201)
    assert decision["final_quantity"] == 1000, (
        "a credited claim contributes nothing to the verifiable floor"
    )


def test_a_filed_claim_contributes_nothing_to_the_verifiable_floor(api):
    """PRD §3.3: "The platform takes all quality claims whose `card_set_id` is
    this set and whose `status` is `APPROVED` — a `FILED`, `UNDER_REVIEW`,
    `DENIED` or `CREDITED` claim contributes nothing".

    Design: Difficulty/dual_variant_calc/quality_floor_variant_flips_the_same_decision_by_review_state
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))

    resp = api.create_print_run_decision(
        create_print_run_decision_payload(
            card_set_id=card_set["id"],
            authority="MARKET_DEMAND",
            proposed_against_line_version=line["version"],
            demand_multiplier=1.0,
            declared_quantity=1000,
            announced=False,
        ),
        PLANNER,
    )
    baseline = validate_success(resp, expected_status=201)
    assert baseline["final_quantity"] == 1000

    filed = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(
                severity="MINOR", affected_quantity=100000, filed_on="2026-09-01T00:00:00Z"
            ),
            QA,
        )
    )
    assert filed["status"] == "FILED"

    resp = api.create_print_run_decision(
        create_print_run_decision_payload(
            card_set_id=card_set["id"],
            authority="MARKET_DEMAND",
            proposed_against_line_version=line["version"],
            demand_multiplier=1.0,
            declared_quantity=1000,
            announced=False,
        ),
        PLANNER,
    )
    after_filing = validate_success(resp, expected_status=201)
    assert after_filing["final_quantity"] == 1000, "a FILED claim is not defect evidence"


def test_reviewing_an_old_claim_is_refused_but_filing_it_still_counts(api):
    """PRD §3.7: "the claim's `filed_on` must be strictly after the instant
    thirty days before the clock. A claim filed exactly thirty days ago, or
    earlier, is refused with `ERR_CLAIM_BACKDATE_EXCEEDED`."

    Design: Difficulty/dual_variant_calc/quality_floor_variant_flips_the_same_decision_by_review_state
    """
    _, line, card_set = _scenario(api, reserved_cases=(10, 15))
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(
                severity="MINOR", affected_quantity=100000, filed_on="2026-01-01T00:00:00Z"
            ),
            QA,
        )
    )
    resp = api.open_claim_review(claim["id"], QA)
    validate_error(resp, ApiErrorId.ERR_CLAIM_BACKDATE_EXCEEDED)
    after = get_success_data(api.get_card_set(card_set["id"], PM))
    assert after["quality_claim_count"] == 1
    assert CLAIM_BACKDATE_WINDOW_DAYS == 30
    assert CARDS_PER_SET == 100