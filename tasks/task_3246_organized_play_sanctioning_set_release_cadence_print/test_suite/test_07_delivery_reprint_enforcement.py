"""Print-run allocation, reprint policy verdicts, enforcement scoring, and the
ordering between completing an event and reporting it."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_allocation_order,
    create_enforcement_case_payload,
    create_reprint_plan_payload,
    current_product_configuration,
    get_case,
    get_order,
    get_product_configuration,
    get_reprint_plan,
    get_set_release,
    increase_print_run,
    make_judge_headers,
    setup_judge_with_case,
    setup_product_configuration,
    setup_release_context,
    transition_allocation_order_raw,
    transition_payload,
    validate_error,
    validate_success,
)


# ─── Print-run allocation (PRD §3.12) ─────────────────

def test_an_order_within_availability_is_approved_for_its_full_quantity(api):
    """PRD §3.12: "Approving it is available only when the requested quantity does
    not exceed the configuration's `units_available`; the order's `fulfilled_qty`
    is set to the full requested quantity and the configuration's
    `units_allocated` rises by that quantity."

    Design: Corner/state_machines/allocation_order_denied_when_print_run_exhausted
    """
    _store, _set_release, configuration, orders = setup_product_configuration(
        print_run_units=10, order_quantities=[8, 8]
    )
    first = orders[0]

    approved = approve_allocation_order(
        first["id"], current_product_configuration(configuration["id"])["version"]
    )
    assert approved["status"] == "APPROVED"
    assert approved["fulfilled_qty"] == 8

    updated = get_product_configuration(configuration["id"])
    assert updated["units_allocated"] == 8
    assert updated["units_available"] == 2


def test_a_second_order_larger_than_the_remaining_print_run_is_refused(api):
    """PRD §3.12: "An approval attempted when the requested quantity exceeds
    availability is rejected with `ERR_PRINT_RUN_EXHAUSTED`, and the rejection is
    specifically the approve path's — a partial fulfilment request in the same
    situation is not an error, it is the intended response."

    Design: Corner/state_machines/allocation_order_denied_when_print_run_exhausted
    """
    _store, _set_release, configuration, orders = setup_product_configuration(
        print_run_units=10, order_quantities=[8, 8]
    )
    first, second = orders
    approve_allocation_order(
        first["id"], current_product_configuration(configuration["id"])["version"]
    )

    refused = transition_allocation_order_raw(
        second["id"], "APPROVE",
        expected_version=current_product_configuration(configuration["id"])["version"],
    )
    validate_error(refused, "ERR_PRINT_RUN_EXHAUSTED", expected_status=402)

    assert get_order(second["id"])["status"] == "PENDING"
    assert get_order(second["id"])["fulfilled_qty"] == 0
    updated = get_product_configuration(configuration["id"])
    assert updated["units_available"] == 2
    assert updated["units_allocated"] == 8


def test_a_stale_configuration_version_blocks_fulfilment(api):
    """PRD §2.10: "The second is the fulfilment of a distributor allocation order,
    which must be submitted with `expected_product_configuration_version`, the
    client's last observed `version` of the `ProductConfiguration` being drawn
    against."
    PRD §2.10: "In both cases the supplied value is compared with the parent's
    current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`."

    Design: Corner/validations/allocation_order_fulfilment_requires_current_configuration_version
    """
    _store, _set_release, configuration, orders = setup_product_configuration(
        print_run_units=50, order_quantities=[10]
    )
    order = orders[0]
    observed = current_product_configuration(configuration["id"])["version"]

    refused = transition_allocation_order_raw(
        order["id"], "APPROVE", expected_version=observed - 1
    )
    validate_error(refused, "ERR_STALE_VERSION", expected_status=412)

    assert get_order(order["id"])["status"] == "PENDING"
    assert get_order(order["id"])["fulfilled_qty"] == 0
    unchanged = get_product_configuration(configuration["id"])
    assert unchanged["units_allocated"] == 0
    assert unchanged["units_available"] == 50


def test_the_same_fulfilment_succeeds_with_the_current_configuration_version(api):
    """PRD §2.10: "In both cases the supplied value is compared with the parent's
    current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`."
    PRD §3.12: "Approving it is available only when the requested quantity does
    not exceed the configuration's `units_available`; the order's `fulfilled_qty`
    is set to the full requested quantity and the configuration's
    `units_allocated` rises by that quantity."

    Design: Corner/validations/allocation_order_fulfilment_requires_current_configuration_version
    """
    _store, _set_release, configuration, orders = setup_product_configuration(
        print_run_units=50, order_quantities=[10]
    )
    order = orders[0]
    observed = current_product_configuration(configuration["id"])["version"]

    refused = transition_allocation_order_raw(
        order["id"], "APPROVE", expected_version=observed - 1
    )
    validate_error(refused, "ERR_STALE_VERSION", expected_status=412)

    approved = approve_allocation_order(order["id"], observed)
    assert approved["status"] == "APPROVED"
    assert approved["fulfilled_qty"] == 10
    advanced = get_product_configuration(configuration["id"])
    assert advanced["version"] > observed
    assert advanced["units_allocated"] == 10


def test_units_available_reconciles_across_allocation_and_print_run_growth(api):
    """PRD §3.12: "The configuration starts with nothing allocated and its
    availability is always derived rather than stored: `units_available` is
    `print_run_units` minus `units_allocated`"
    PRD §3.12: "An operator may add units to a configuration, supplying the number
    to add as `additional_units`; the addition raises `print_run_units` directly
    and advances the configuration's `version` by one."

    Design: Corner/endpoints/product_configuration_derived_units_available_lags_allocations
    """
    _store, _set_release, configuration, orders = setup_product_configuration(
        print_run_units=50, configuration_kind="DRAFT_BOOSTER", pack_count=6,
        order_quantities=[10],
    )
    order = orders[0]
    before = get_product_configuration(configuration["id"])
    assert before["units_available"] == 50
    assert before["units_allocated"] == 0

    observed = before["version"]
    approve_allocation_order(order["id"], observed)
    after_approval = get_product_configuration(configuration["id"])
    assert after_approval["units_available"] == 40
    assert after_approval["units_allocated"] == 10
    assert after_approval["version"] > observed

    increase_print_run(configuration["id"], 60).raise_for_status()
    grown = get_product_configuration(configuration["id"])
    assert grown["print_run_units"] == 110
    assert grown["units_allocated"] == 10
    assert grown["units_available"] == 100
    assert grown["configuration_kind"] == "DRAFT_BOOSTER"
    assert grown["pack_count"] == 6


# ─── Reprint policy (PRD §3.9) ────────────────────────

def test_an_index_at_the_ceiling_lifts_above_it_under_the_addendum(api):
    """PRD §3.9: "A card whose raw secondary-market index is exactly forty-two
    sits precisely on the ceiling, and with the addendum in force that index lifts
    to sixty-one, which is above the ceiling and therefore denied; only when the
    addendum is suppressed for an accessibility audit does an index of exactly
    forty-two clear."

    Design: Difficulty/dual_variant_calc/reprint_verdict_addendum_vs_suppressed_ceiling
    """
    _store, set_release, fmt = setup_release_context()

    plan = validate_success(api_client.create_reprint_plan(
        create_reprint_plan_payload(
            set_release["id"], fmt["id"],
            card_name="Ceiling Card", secondary_market_index=42, first_print_index=40,
        ),
        TEST_USERS["ops_admin_headers"],
    ), 201)

    assert plan["verdict"] == "REPRINT_DENIED"
    assert plan["status"] == "DRAFT"
    assert get_reprint_plan(plan["id"])["verdict"] == "REPRINT_DENIED"


def test_an_index_inside_the_ceiling_stays_allowed(api):
    """PRD §3.9: "The filing is then compared against a ceiling index of
    forty-two: a plan whose addendum-adjusted index is strictly greater than
    forty-two yields a `REPRINT_DENIED` verdict, and a plan at or below the
    ceiling yields `REPRINT_ALLOWED`."
    PRD §3.9: "The `first_print_index` the operator supplies does not enter the
    verdict at all — it is recorded so that the market context of the decision can
    be audited afterwards."

    Design: Difficulty/dual_variant_calc/reprint_verdict_addendum_vs_suppressed_ceiling
    """
    _store, set_release, fmt = setup_release_context()

    below = validate_success(api_client.create_reprint_plan(
        create_reprint_plan_payload(
            set_release["id"], fmt["id"],
            card_name="Slack Card", secondary_market_index=28, first_print_index=30,
        ),
        TEST_USERS["ops_admin_headers"],
    ), 201)
    assert below["verdict"] == "REPRINT_ALLOWED"
    assert below["first_print_index"] == 30

    at_ceiling = validate_success(api_client.create_reprint_plan(
        create_reprint_plan_payload(
            set_release["id"], fmt["id"],
            card_name="Ceiling Card", secondary_market_index=42, first_print_index=1,
        ),
        TEST_USERS["ops_admin_headers"],
    ), 201)
    assert at_ceiling["verdict"] == "REPRINT_DENIED", (
        "with the addendum in force an index of 42 lifts to 61 and is denied"
    )


def test_publishing_an_approved_plan_is_closed_once_the_release_is_retired(api):
    """PRD §3.7: "Retirement additionally closes the reprint review: a reprint
    plan whose cited set release has already been retired cannot be transitioned
    at all, and such an attempt is rejected with `ERR_REPRINT_REVIEW_CLOSED`."

    Design: Corner/errors/reprint_plan_publish_closed_after_release_retired
    """
    _store, set_release, fmt = setup_release_context()

    plan = validate_success(api_client.create_reprint_plan(
        create_reprint_plan_payload(
            set_release["id"], fmt["id"],
            card_name="Accessible Card", secondary_market_index=10, first_print_index=9,
        ),
        TEST_USERS["ops_admin_headers"],
    ), 201)
    assert plan["verdict"] == "REPRINT_ALLOWED"

    api_client.transition_reprint_plan(
        plan["id"], transition_payload("APPROVE"), TEST_USERS["ops_admin_headers"]
    ).raise_for_status()
    assert get_reprint_plan(plan["id"])["status"] == "APPROVED"

    api_client.transition_set_release(
        set_release["id"], transition_payload("RETIRE"),
        TEST_USERS["ops_admin_headers"],
    ).raise_for_status()
    assert get_set_release(set_release["id"])["status"] == "RETIRED"

    refused = api_client.transition_reprint_plan(
        plan["id"], transition_payload("PUBLISH"), TEST_USERS["ops_admin_headers"]
    )
    validate_error(refused, "ERR_REPRINT_REVIEW_CLOSED", expected_status=409)
    assert get_reprint_plan(plan["id"])["status"] == "APPROVED"
    assert get_reprint_plan(plan["id"])["verdict"] == "REPRINT_ALLOWED"


# ─── Enforcement scoring (PRD §3.10) ──────────────────

def test_penalty_points_apply_the_class_times_level_matrix(api):
    """PRD §3.10: "The base points are two for a `MINOR` offense, five for a
    `MAJOR` offense and eleven for a `SEVERE` one; the multiplier is one at
    `REGULAR`, two at `COMPETITIVE` and three at `PROFESSIONAL`."
    PRD §3.10: "Filing the case sets `current_points` equal to `penalty_points`."

    Design: Corner/calculations/enforcement_points_follow_class_times_level_matrix
    """
    _store, _set_release, _fmt, application, judge, case = setup_judge_with_case(
        judge_ref="JUDGE-BETA", offense_class="MINOR",
        rules_enforcement_level="REGULAR",
    )

    high = validate_success(api_client.create_enforcement_case(
        create_enforcement_case_payload(
            application["id"], judge_ref=judge["judge_ref"],
            player_ref="PLAYER-HIGH", offense_class="SEVERE",
            rules_enforcement_level="PROFESSIONAL",
        ),
        make_judge_headers(judge["id"]),
    ), 201)

    assert case["status"] == "FILED"
    assert case["penalty_points"] == 2
    assert case["current_points"] == 2
    assert high["penalty_points"] == 33
    assert high["current_points"] == 33


def test_escalation_multiplies_a_repeat_and_increments_a_first_offense(api):
    """PRD §3.10: "Escalating the case moves it to `ESCALATED` and is the one
    branch that consults the case's `repeated_offense` flag: if the flag is set —
    meaning this player already carries an enforcement case on this same event
    application — the working penalty becomes the underlying penalty multiplied by
    three; if the flag is not set, the working penalty becomes the underlying
    penalty plus four points."
    PRD §3.10: "The case also carries a `repeated_offense` flag recording whether
    this player already has an enforcement case on this same event application;
    the flag may be supplied at filing"

    Design: Corner/calculations/enforcement_escalation_branches_on_repeated_offense
    """
    _store, _set_release, _fmt, application, judge, repeat_case = setup_judge_with_case(
        level="LEVEL_3", judge_ref="JUDGE-GAMMA", offense_class="MAJOR",
        rules_enforcement_level="COMPETITIVE", repeated_offense=True,
    )

    first_case = validate_success(api_client.create_enforcement_case(
        create_enforcement_case_payload(
            application["id"], judge_ref=judge["judge_ref"],
            player_ref="PLAYER-FIRST", offense_class="MAJOR",
            rules_enforcement_level="COMPETITIVE", repeated_offense=False,
        ),
        make_judge_headers(judge["id"]),
    ), 201)

    assert repeat_case["penalty_points"] == 10
    assert first_case["penalty_points"] == 10

    api_client.transition_enforcement_case(
        repeat_case["id"], transition_payload("ESCALATE"),
        TEST_USERS["ops_admin_headers"],
    ).raise_for_status()
    api_client.transition_enforcement_case(
        first_case["id"], transition_payload("ESCALATE"),
        TEST_USERS["ops_admin_headers"],
    ).raise_for_status()

    assert get_case(repeat_case["id"])["current_points"] == 30, "10 * 3"
    assert get_case(repeat_case["id"])["status"] == "ESCALATED"
    assert get_case(first_case["id"])["current_points"] == 14, "10 + 4"
