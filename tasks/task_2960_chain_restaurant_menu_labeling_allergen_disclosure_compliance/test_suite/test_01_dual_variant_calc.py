"""Two calculations that answer differently depending on the basis chosen.

Coverage counting under `OPERATING_ONLY` versus `REGISTERED_ALL`, and penalty
assessment under `PER_BOARD` versus `PER_ESTABLISHMENT`.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_brand_counters,
    assert_money_cents,
    validate_unpaginated,
)
from test_helpers.constants import (
    ACTION_ESCALATED,
    ACTION_PENALTY_ASSESSED,
    ACTION_RESPONSE_SUBMITTED,
    ACTION_TYPE_ASSESS_PENALTY,
    ACTION_TYPE_ESCALATE,
    ACTION_TYPE_REQUEST_INFO,
    ACTION_TYPE_RESCIND_PENALTY,
    BASIS_OPERATING_ONLY,
    BASIS_REGISTERED_ALL,
    BOARD_DRIVE_THRU_BOARD,
    BOARD_PRIMARY_MENU_BOARD,
    BOARD_PRINTED_MENU,
    CITATION_CALORIES_NOT_DECLARED,
    COVERAGE_COVERED,
    COVERAGE_NOT_COVERED,
    PENALTY_BASIS_PER_BOARD,
    PENALTY_BASIS_PER_ESTABLISHMENT,
    POSTURE_COMPLIANT,
    PREEMPTION_PREEMPTED,
    REASON_BELOW_UNIT_THRESHOLD,
    REASON_COVERED_BY_UNIT_COUNT,
    RESPONSE_DISPUTED,
    TIER_ENHANCED,
    UNIT_TEMPORARILY_CLOSED,
)
from test_helpers.factories import (
    coverage_determination_payload,
    regulator_action_payload,
    status_change_payload,
)
from test_helpers.fixtures import (
    Env,
    certified_sandwich,
    certify_recipe_version,
    draft_and_publish_packet,
    file_response,
    make_establishment,
    make_menu_item,
    open_citation,
    published_board,
    regulator_action,
    sandwich_components,
    seed_registry,
)


# ---------------------------------------------------------------------------
# Nineteen operating units and one temporarily closed unit
# ---------------------------------------------------------------------------
def _estate_of_nineteen_operating_and_one_closed(api: ApiClient) -> Env:
    env = seed_registry(
        api, code="CA-VAR", name="California", unit_count=19,
        unit_label="CA-0001", unit_label_prefix="CA-OP",
    )
    closed = make_establishment(
        api,
        brand_id=env.brand_id,
        jurisdiction_id=env.jurisdiction_id,
        unit_label="CA-TMP-0001",
    )
    validate_success(
        api.change_establishment_status(
            closed["id"],
            status_change_payload(
                new_unit_status=UNIT_TEMPORARILY_CLOSED,
                effective_note="Closed for a kitchen refit",
            ),
            env.admin,
        )
    )
    make_menu_item(env)
    return env


def test_operating_only_basis_excludes_the_temporarily_closed_unit(api):
    """PRD §3.1: "Under the `OPERATING_ONLY` basis, `counted_unit_count` is the
    number of the brand's units whose `unit_status` is `OPERATING` and whose
    `operates_under_brand_name` is true."

    Design: Difficulty/dual_variant_calc/coverage_basis_divergence_operating_only_vs_registered_all
    """
    env = _estate_of_nineteen_operating_and_one_closed(api)

    result = validate_unpaginated(
        env.api.determine_coverage(
            env.brand_id,
            coverage_determination_payload(basis=BASIS_OPERATING_ONLY),
            env.officer,
        )
    )

    assert result["basis"] == BASIS_OPERATING_ONLY
    assert result["counted_unit_count"] == 19
    assert result["standard_item_count"] == 1
    assert result["coverage_status"] == COVERAGE_NOT_COVERED
    assert result["coverage_reason"] == REASON_BELOW_UNIT_THRESHOLD


def test_registered_all_basis_counts_the_temporarily_closed_unit(api):
    """PRD §3.1: "Under the `REGISTERED_ALL` basis, `counted_unit_count` is the
    number of the brand's units whose `unit_status` is either `OPERATING` or
    `TEMPORARILY_CLOSED` and whose `operates_under_brand_name` is true."

    Design: Difficulty/dual_variant_calc/coverage_basis_divergence_operating_only_vs_registered_all
    """
    env = _estate_of_nineteen_operating_and_one_closed(api)

    result = validate_unpaginated(
        env.api.determine_coverage(
            env.brand_id,
            coverage_determination_payload(basis=BASIS_REGISTERED_ALL),
            env.officer,
        )
    )

    assert result["basis"] == BASIS_REGISTERED_ALL
    assert result["counted_unit_count"] == 20
    assert result["coverage_status"] == COVERAGE_COVERED
    assert result["coverage_reason"] == REASON_COVERED_BY_UNIT_COUNT


def test_registered_all_determination_is_persisted_onto_the_brand(api):
    """PRD §3.1: "An explicit determination overwrites the brand's stored
    `coverage_status`, `coverage_reason`, `counted_unit_count` and
    `standard_item_count` with the chosen basis's result, increments the
    brand's `version`, and reports `brand_id`, the `basis` used,
    `counted_unit_count`, `standard_item_count`, `coverage_status`,
    `coverage_reason` and a `persisted` flag."

    Design: Difficulty/dual_variant_calc/coverage_basis_divergence_operating_only_vs_registered_all
    """
    env = _estate_of_nineteen_operating_and_one_closed(api)
    version_before = env.brand_version

    result = validate_unpaginated(
        env.api.determine_coverage(
            env.brand_id,
            coverage_determination_payload(basis=BASIS_REGISTERED_ALL),
            env.officer,
        )
    )

    assert result["brand_id"] == env.brand_id
    assert result["persisted"] is True

    brand = env.read_brand()
    assert_brand_counters(
        brand,
        coverage_status=COVERAGE_COVERED,
        coverage_reason=REASON_COVERED_BY_UNIT_COUNT,
        counted_unit_count=20,
        standard_item_count=1,
        compliance_posture=POSTURE_COMPLIANT,
    )
    assert brand["version"] > version_before


# ---------------------------------------------------------------------------
# One unit, three published boards all out of step, in an ENHANCED authority
# ---------------------------------------------------------------------------
def _escalated_citation_over_three_stale_boards(api: ApiClient):
    """Three published boards of one unit go stale, then a citation escalates."""
    env = seed_registry(
        api,
        code="NY-ENH",
        name="New York",
        preemption_mode=PREEMPTION_PREEMPTED,
        enforcement_tier=TIER_ENHANCED,
        unit_label="NY-0001",
        unit_label_prefix="NY-B",
    )
    item = certified_sandwich(env)
    draft_and_publish_packet(env)
    for board_type in (
        BOARD_PRIMARY_MENU_BOARD,
        BOARD_DRIVE_THRU_BOARD,
        BOARD_PRINTED_MENU,
    ):
        published_board(env, item.item_id, board_type=board_type)

    # A second certification lifts the declared maximum from 530 to 700 Cal,
    # which is far outside the tolerance band and stales every printed line.
    certify_recipe_version(
        env,
        item.item_id,
        sandwich_components(mayonnaise_grams=45),
        change_note="Larger herb mayonnaise portion",
    )

    action = open_citation(env, CITATION_CALORIES_NOT_DECLARED)
    file_response(env, action["id"], RESPONSE_DISPUTED)
    regulator_action(env, action["id"], ACTION_TYPE_REQUEST_INFO)
    file_response(env, action["id"], RESPONSE_DISPUTED)
    regulator_action(env, action["id"], ACTION_TYPE_ESCALATE)
    return env, action


def test_per_board_basis_counts_one_violation_unit_per_non_current_board(api):
    """PRD §3.9: "Under `PER_BOARD`, `violation_unit_count` is the number of the
    cited establishment's boards whose `publication_status` is `PUBLISHED` and
    whose `calorie_compliance_status` is either `REPRINT_REQUIRED` or
    `OVERDUE` — one violation unit per board that is out of step."

    Design: Difficulty/dual_variant_calc/penalty_basis_divergence_per_board_vs_per_establishment
    """
    env, action = _escalated_citation_over_three_stale_boards(api)

    assessed = validate_unpaginated(
        env.api.create_regulator_action(
            action["id"],
            regulator_action_payload(
                action_type=ACTION_TYPE_ASSESS_PENALTY,
                penalty_basis=PENALTY_BASIS_PER_BOARD,
                action_note="Three boards out of step",
            ),
            env.regulator,
        )
    )

    assert assessed["status"] == ACTION_PENALTY_ASSESSED
    assert assessed["penalty_basis"] == PENALTY_BASIS_PER_BOARD
    assert assessed["violation_unit_count"] == 3
    assert_money_cents(assessed["base_penalty_cents"], 225000, "base_penalty_cents")
    assert_money_cents(assessed["admin_fee_cents"], 18000, "admin_fee_cents")
    assert_money_cents(assessed["penalty_total_cents"], 243000, "penalty_total_cents")

    assert_money_cents(
        env.read_establishment()["outstanding_penalty_cents"],
        243000,
        "Establishment.outstanding_penalty_cents",
    )
    assert_money_cents(
        env.read_jurisdiction()["assessed_penalty_cents_total"],
        243000,
        "Jurisdiction.assessed_penalty_cents_total",
    )


def test_per_establishment_basis_counts_exactly_one_violation_unit(api):
    """PRD §3.9: "Under `PER_ESTABLISHMENT`, `violation_unit_count` is exactly 1
    regardless of how many boards are out of step."

    Design: Difficulty/dual_variant_calc/penalty_basis_divergence_per_board_vs_per_establishment
    """
    env, action = _escalated_citation_over_three_stale_boards(api)

    assessed = validate_unpaginated(
        env.api.create_regulator_action(
            action["id"],
            regulator_action_payload(
                action_type=ACTION_TYPE_ASSESS_PENALTY,
                penalty_basis=PENALTY_BASIS_PER_ESTABLISHMENT,
                action_note="Assessed against the unit as a whole",
            ),
            env.regulator,
        )
    )

    assert assessed["violation_unit_count"] == 1
    assert_money_cents(assessed["base_penalty_cents"], 75000, "base_penalty_cents")
    assert_money_cents(assessed["admin_fee_cents"], 3750, "admin_fee_cents")
    assert_money_cents(assessed["penalty_total_cents"], 78750, "penalty_total_cents")


def test_the_two_bases_land_in_different_fee_tiers_on_the_same_unit(api):
    """PRD §3.9: "A unit with three non-current published boards in an `ENHANCED`
    authority assessed `PER_BOARD` yields a base of 225000 cents, lands in the
    eight-per-cent tier for a fee of 18000 cents, and totals 243000 cents. The
    same unit assessed `PER_ESTABLISHMENT` yields a base of 75000 cents, lands
    in the five-per-cent tier for a fee of 3750 cents, and totals 78750 cents."

    Design: Difficulty/dual_variant_calc/penalty_basis_divergence_per_board_vs_per_establishment
    """
    env, action = _escalated_citation_over_three_stale_boards(api)

    per_board = regulator_action(
        env, action["id"], ACTION_TYPE_ASSESS_PENALTY,
        penalty_basis=PENALTY_BASIS_PER_BOARD,
    )
    assert_money_cents(per_board["penalty_total_cents"], 243000, "PER_BOARD total")

    rescinded = regulator_action(env, action["id"], ACTION_TYPE_RESCIND_PENALTY)
    assert rescinded["status"] == ACTION_RESPONSE_SUBMITTED
    assert_money_cents(rescinded["penalty_total_cents"], 0, "rescinded total")

    reescalated = regulator_action(env, action["id"], ACTION_TYPE_ESCALATE)
    assert reescalated["status"] == ACTION_ESCALATED

    per_establishment = regulator_action(
        env, action["id"], ACTION_TYPE_ASSESS_PENALTY,
        penalty_basis=PENALTY_BASIS_PER_ESTABLISHMENT,
    )
    assert_money_cents(
        per_establishment["penalty_total_cents"], 78750, "PER_ESTABLISHMENT total"
    )
