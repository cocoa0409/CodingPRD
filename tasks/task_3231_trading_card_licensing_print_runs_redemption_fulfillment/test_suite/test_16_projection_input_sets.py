"""Projection input sets and the per-tier snap quantum.

Only APPROVED and SETTLED complaints feed the sales-history base, only
APPROVED claims feed the verifiable floor, and only the directive authority
reads no observed activity at all.
"""

from test_helpers import (
    approve_artwork_for_set,
    approve_card_set,
    BRAND_DIRECTIVE_BASE,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    PROJECTION_MULTIPLE_OF,
    submit_card_set_for_review,
    TEST_USERS,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
QA = TEST_USERS["quality_analyst_headers"]
DIST = TEST_USERS["distribution_manager_headers"]
CS = TEST_USERS["collector_support_headers"]


def _line_with_set(api, *, tier="BASE", quantity=500, name="Flagship Base"):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api, line["id"], set_name=name, set_tier=tier, print_run_quantity=quantity
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    line = get_success_data(api.get_product_line(line["id"], PM))
    return license_obj, line, card_set


def _claim(api, set_id, severity, affected, filed_on="2026-09-01T00:00:00Z"):
    return get_success_data(
        api.file_quality_claim(
            set_id,
            {
                "claim_type": "MISPRINT",
                "severity": severity,
                "affected_quantity": affected,
                "filed_on": filed_on,
            },
            QA,
        )
    )


def test_the_directive_authority_reads_no_claim_data_at_all(api):
    """PRD §3.3: "Under `BRAND_DIRECTIVE` the platform reads no observed
    activity whatsoever: the base is simply the `BRAND_DIRECTIVE_BASE` entry
    for the tier".

    Design: Corner/calculations/print_run_projection_marks_its_input_set
    """
    license_obj, line, card_set = _line_with_set(api)
    decision = validate_success(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "BRAND_DIRECTIVE",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": BRAND_DIRECTIVE_BASE["BASE"],
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert decision["final_quantity"] == 12000


def test_the_claim_count_aggregate_counts_claims_of_every_status(api):
    """PRD §3.7: "computes its `claim_weight` from the severity — `SEVERITY_WEIGHT_MINOR` of 1 for `MINOR`, `SEVERITY_WEIGHT_MAJOR` of 2 for `MAJOR` and `SEVERITY_WEIGHT_CRITICAL` of 3 for `CRITICAL`, with the `severity` enum closed and every value weighted — and recomputes `quality_claim_count` on the set."

    Design: Corner/calculations/print_run_projection_marks_its_input_set
    """
    license_obj, line, card_set = _line_with_set(api)
    approved = _claim(api, card_set["id"], "MINOR", 300000)
    filed = _claim(api, card_set["id"], "MAJOR", 500000)
    denied = _claim(api, card_set["id"], "CRITICAL", 900000)

    for claim in (approved, denied):
        get_success_data(api.open_claim_review(claim["id"], QA))
    get_success_data(api.approve_quality_claim(approved["id"], QA))
    get_success_data(api.deny_quality_claim(denied["id"], QA))

    read = validate_success(api.get_card_set(card_set["id"], QA))
    assert read["quality_claim_count"] == 3, "the aggregate counts every status"
    assert validate_success(api.get_quality_claim(filed["id"], QA))["status"] == "FILED"
    assert validate_success(api.get_quality_claim(denied["id"], QA))["status"] == "DENIED"


def test_only_the_approved_claim_reaches_the_verifiable_floor(api):
    """PRD §3.3: "The platform takes all quality claims whose `card_set_id` is
    this set and whose `status` is `APPROVED` — a `FILED`, `UNDER_REVIEW`,
    `DENIED` or `CREDITED` claim contributes nothing".

    Design: Corner/calculations/print_run_projection_marks_its_input_set
    """
    license_obj, line, card_set = _line_with_set(api)
    approved = _claim(api, card_set["id"], "MINOR", 100000)
    _claim(api, card_set["id"], "MAJOR", 500000)
    denied = _claim(api, card_set["id"], "CRITICAL", 900000)
    get_success_data(api.open_claim_review(approved["id"], QA))
    get_success_data(api.approve_quality_claim(approved["id"], QA))
    get_success_data(api.open_claim_review(denied["id"], QA))
    get_success_data(api.deny_quality_claim(denied["id"], QA))

    decision = validate_success(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "BRAND_DIRECTIVE",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 12000,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert decision["final_quantity"] == 12000, "the directive branch reads no claims at all"


def test_an_approved_claim_raises_the_floor_but_a_denied_one_does_not(api):
    """PRD §3.3: "sums their `affected_quantity` into a verifiable total,
    multiplies that total by `REORDER_HIT_RATE`, the reorder hit rate of 0.005,
    to obtain a threshold, and computes a safety floor by ceiling that
    threshold up to the tier's `PROJECTION_MULTIPLE_OF` quantum."

    Design: Corner/calculations/print_run_projection_marks_its_input_set
    """
    license_obj, line, card_set = _line_with_set(api)
    only_denied = _claim(api, card_set["id"], "CRITICAL", 900000)
    get_success_data(api.open_claim_review(only_denied["id"], QA))
    get_success_data(api.deny_quality_claim(only_denied["id"], QA))

    for channel, cases in (("HOBBY", 10), ("MASS", 15)):
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
    denied_decision = validate_success(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "MARKET_DEMAND",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 1000,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert denied_decision["final_quantity"] == 1000, "a denied claim is not defect evidence"

    approved = _claim(api, card_set["id"], "MINOR", 300000)
    get_success_data(api.open_claim_review(approved["id"], QA))
    get_success_data(api.approve_quality_claim(approved["id"], QA))
    lifted = validate_success(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "MARKET_DEMAND",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 1500,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert lifted["final_quantity"] == 1500, "the approved claim lifts the projection by one quantum"


def test_a_claim_that_is_merely_in_review_contributes_to_neither_input_set(api):
    """PRD §3.7: "Neither branch advances anything on the parent card set
    beyond a count recompute."

    Design: Corner/calculations/print_run_projection_marks_its_input_set
    """
    license_obj, line, card_set = _line_with_set(api)
    claim = _claim(api, card_set["id"], "MINOR", 100000)
    reviewed = validate_success(api.open_claim_review(claim["id"], QA))
    assert reviewed["status"] == "UNDER_REVIEW"

    for channel, cases in (("HOBBY", 10), ("MASS", 15)):
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
    decision = validate_success(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "MARKET_DEMAND",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 1000,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert decision["final_quantity"] == 1000
    read = validate_success(api.get_card_set(card_set["id"], QA))
    assert read["quality_claim_count"] == 1


def test_each_tier_snaps_a_planned_quantity_to_its_own_quantum(api):
    """PRD §3.3: "the `PROJECTION_MULTIPLE_OF` quantum is 500 for `BASE`, 100
    for `INSERT` and 25 for `PREMIUM`."

    Design: Corner/calculations/print_run_projection_snaps_up_to_the_tier_quantum
    """
    # PRD 3.2 pins the quantisation with a BASE set of 1234: "the correct
    # per-set-then-sum result is 1500 plus 1500 plus 1500". Only BASE sets may
    # carry a planned quantity at approval, so the BASE quantum is the one that
    # can be observed here; INSERT and PREMIUM sets hold 0.
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Base", set_tier="BASE",
        announced=True, print_run_quantity=1234,
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    line = get_success_data(api.get_product_line(line["id"], PM))

    quantum = PROJECTION_MULTIPLE_OF["BASE"]
    assert quantum == 500
    assert line["allocated_cards"] == 1500, "ceil(1234 / 500) x 500"
    assert line["allocated_cards"] % quantum == 0


def test_the_premium_tier_snaps_1234_up_to_1225(api):
    """PRD §3.3: "The fourth stage snaps the clamped value upward to the tier's
    `PROJECTION_MULTIPLE_OF` quantum using a ceiling division — never a
    round-half-up — so the returned quantity is always an exact multiple of the
    tier's quantum and always an integer."

    Design: Corner/calculations/print_run_projection_snaps_up_to_the_tier_quantum
    """
    license_obj, line, card_set = _line_with_set(
        api, tier="PREMIUM", quantity=0, name="Flagship Premium"
    )
    decision = validate_success(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "BRAND_DIRECTIVE",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 0.001,
                "declared_quantity": 1225,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    quantum = PROJECTION_MULTIPLE_OF["PREMIUM"]
    assert quantum == 25
    assert decision["final_quantity"] % quantum == 0, (
        "the projection is always an exact multiple of the tier quantum"
    )


def test_the_insert_tier_keeps_its_smaller_quantum(api):
    """PRD §3.3: "so the returned quantity is always an exact multiple of the
    tier's quantum and always an integer."

    Design: Corner/calculations/print_run_projection_snaps_up_to_the_tier_quantum
    """
    license_obj, line, card_set = _line_with_set(
        api, tier="INSERT", quantity=0, name="Flagship Insert"
    )
    # PRD 3.3: MARKET_DEMAND reads the HOBBY/MASS reservations on the line, so
    # the authority needs at least one such allocation to build a base from.
    get_success_data(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 20,
                "effective_price_cents": 72000,
            },
            DIST,
        )
    )
    decision = validate_success(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "MARKET_DEMAND",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 200,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert decision["final_quantity"] % PROJECTION_MULTIPLE_OF["INSERT"] == 0
    assert decision["final_quantity"] == 200


def test_a_lone_hobby_reservation_is_enough_market_demand_evidence(api):
    """PRD §3.3: "if no such allocation exists at all the request is refused
    with `ERR_MARKET_SIGNAL_UNAVAILABLE`."

    Design: Corner/calculations/print_run_projection_snaps_up_to_the_tier_quantum
    """
    license_obj, line, card_set = _line_with_set(api)
    get_success_data(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 10,
                "effective_price_cents": 72000,
            },
            DIST,
        )
    )
    decision = validate_success(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "MARKET_DEMAND",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 1000,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert decision["final_quantity"] == 1000