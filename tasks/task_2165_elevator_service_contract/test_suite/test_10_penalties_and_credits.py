"""Assessing the month: the two penalty schedules, service credits and the ledger."""
from test_helpers import (
    ApiErrorId,
    UNUSED_UUID,
    assert_contract_ledger_invariant,
    assert_penalty_assessment,
    assess_penalty,
    contract_version,
    create_draft_contract,
    create_penalty_payload,
    dispute_penalty,
    read_contract,
    read_penalty,
    set_clock,
    setup_entrapment_breach_month,
    setup_late_callback_month,
    setup_program,
    setup_three_car_late_callbacks,
    setup_two_schedules_with_identical_incidents,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_two_schedules_produce_different_amounts_from_identical_data(api):
    """PRD §3.8: "Under **`SCHEDULE_A`** the penalty is a sum of flat per-incident
    fees plus a linear charge for the uptime shortfall. `raw_amount_cents` is 25,000
    cents for each late callback, plus 100,000 cents for each entrapment breach,
    plus 75,000 cents for each missed or rejected visit, plus the shortfall in
    percentage points multiplied by 40,000 cents per percentage point and rounded
    half up to a whole cent. `cap_amount_cents` is 25 percent of the contract's
    `monthly_base_fee_cents`, rounded half up to a whole cent."
    PRD §3.8: "The breach rate is 2 percent multiplied by a weighted incident count
    in which each late callback counts once, each entrapment breach counts
    **twice**, and each missed or rejected visit counts once."
    PRD §3.8: "`raw_amount_cents` is then the contract's `monthly_base_fee_cents`
    multiplied by the sum of the tiered uptime rate and the breach rate, multiplied
    by the severity weight, with the whole product rounded half up to a whole cent
    exactly once. `cap_amount_cents` is 30 percent of `monthly_base_fee_cents`,
    rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/penalty_schedule_a_vs_b_diverge_on_identical_incident_data
    """
    worlds = setup_two_schedules_with_identical_incidents()
    penalty_a = assess_penalty(worlds["schedule_a"], "2026-08")
    penalty_b = assess_penalty(worlds["schedule_b"], "2026-08")

    assert_penalty_assessment(penalty_a)
    assert_penalty_assessment(penalty_b)

    assert penalty_a["schedule_applied"] == "SCHEDULE_A"
    assert penalty_a["raw_amount_cents"] == 25_000
    assert penalty_a["cap_amount_cents"] == 120_000
    assert penalty_a["amount_cents"] == 25_000

    assert penalty_b["schedule_applied"] == "SCHEDULE_B"
    assert penalty_b["raw_amount_cents"] == 9_600
    assert penalty_b["cap_amount_cents"] == 144_000
    assert penalty_b["amount_cents"] == 9_600

    assert penalty_a["amount_cents"] != penalty_b["amount_cents"], (
        "identical incident data must produce materially different amounts"
    )


def test_both_schedules_share_the_same_uptime_and_credit_inputs(api):
    """PRD §3.8: "`uptime_variant_applied` is `EXCLUSIVE` when the contract's
    `scope_type` is `FULL_MAINTENANCE` and `INCLUSIVE` when it is `OIL_AND_GREASE`."
    PRD §3.8: "`late_callback_count` counts callbacks on the car set whose `status`
    is `CLEARED`, whose `callback_type` is *not* `ENTRAPMENT`, whose `sla_breached`
    is true, and whose `reported_at` falls inside the half-open period window."
    PRD §3.8: "For each car in `car_code` ascending order, that car's raw credit is
    the contract's `monthly_base_fee_cents`, multiplied by one divided by the car
    count — kept as an exact fraction and never pre-rounded — multiplied by 100 less
    that car's own uptime percentage under the applied variant, divided by 100."

    Design: Difficulty/dual_variant_calc/penalty_schedule_a_vs_b_diverge_on_identical_incident_data
    """
    worlds = setup_two_schedules_with_identical_incidents()
    penalty_a = assess_penalty(worlds["schedule_a"], "2026-08")
    penalty_b = assess_penalty(worlds["schedule_b"], "2026-08")

    for penalty in (penalty_a, penalty_b):
        assert penalty["uptime_variant_applied"] == "EXCLUSIVE"
        assert penalty["uptime_pct_applied"] == 99.14
        assert penalty["late_callback_count"] == 1
        assert penalty["service_credit_cents"] == 4_128


def test_schedule_b_tier_breach_and_severity_are_clamped_by_the_cap(api):
    """PRD §3.8: "The tiered uptime rate is 0 when `uptime_pct_applied` is 98.50 or
    above, 5 percent when it is 97.00 or above but below 98.50, 10 percent when it
    is 95.00 or above but below 97.00, and 20 percent when it is below 95.00. The
    breach rate is 2 percent multiplied by a weighted incident count in which each
    late callback counts once, each entrapment breach counts **twice**, and each
    missed or rejected visit counts once. The severity weight is 3 whenever
    `entrapment_breach_count` is greater than zero; otherwise it is 2 whenever the
    shortfall in percentage points is at least 2.00; otherwise it is 1."
    PRD §3.8: "Whichever schedule ran, `amount_cents` is the smaller of
    `raw_amount_cents` and `cap_amount_cents`."

    Design: Difficulty/combinatorial_formula/schedule_b_tier_breach_severity_and_cap_interact_nonlinearly
    """
    program = setup_entrapment_breach_month()
    penalty = assess_penalty(program, "2026-08")

    assert penalty["uptime_variant_applied"] == "INCLUSIVE"
    assert penalty["uptime_pct_applied"] == 92.74
    assert penalty["raw_amount_cents"] == 360_000
    assert penalty["cap_amount_cents"] == 150_000
    assert penalty["amount_cents"] == 150_000, (
        "the 30-percent cap clamps the raw amount"
    )


def test_schedule_b_breach_counters_and_service_credit(api):
    """PRD §3.8: "`entrapment_breach_count` applies the identical filter except that
    `callback_type` must be `ENTRAPMENT`. `missed_visit_count` counts maintenance
    visits on the car set whose `period_month` string equals the assessed period
    exactly and whose `status` is either `MISSED` or `REJECTED`."
    PRD §3.8: "That raw figure is rounded half up to a whole cent **per car**, and
    only then are the per-car figures summed into `service_credit_cents`."
    PRD §3.8: "The new `amount_cents` is then added to
    `penalty_lifetime_assessed_cents`, `penalty_balance_cents` is recomputed, and the
    contract's `version` is incremented by 1."

    Design: Difficulty/combinatorial_formula/schedule_b_tier_breach_severity_and_cap_interact_nonlinearly
    """
    program = setup_entrapment_breach_month()
    penalty = assess_penalty(program, "2026-08")

    assert penalty["entrapment_breach_count"] == 1
    assert penalty["late_callback_count"] == 0
    assert penalty["missed_visit_count"] == 0
    assert penalty["service_credit_cents"] == 36_300

    contract = read_contract(program.contract_id)
    assert contract["penalty_balance_cents"] == 150_000
    assert_contract_ledger_invariant(contract)


def test_service_credit_rounds_once_per_car_before_summing(api):
    """PRD §3.8: "That raw figure is rounded half up to a whole cent **per car**, and
    only then are the per-car figures summed into `service_credit_cents`. Rounding
    once per car before summation, rather than summing exact fractions and rounding
    once at the end, is the required order; the two orders differ, and for three
    cars on a 500,000-cent fee each running 99.14 percent uptime the pinned order
    yields 1,433 plus 1,433 plus 1,433, or 4,299 cents, where the alternative would
    yield 4,300."

    Design: Difficulty/combinatorial_formula/service_credit_rounds_per_car_before_summing
    """
    program = setup_three_car_late_callbacks()
    penalty = assess_penalty(program, "2026-08")

    assert penalty["uptime_pct_applied"] == 99.14
    assert penalty["service_credit_cents"] == 4_299
    assert penalty["service_credit_cents"] != 4_300, (
        "sum-then-round-once is explicitly not the required order"
    )


def test_three_late_callbacks_draw_three_flat_fees(api):
    """PRD §3.8: "`raw_amount_cents` is 25,000 cents for each late callback, plus
    100,000 cents for each entrapment breach, plus 75,000 cents for each missed or
    rejected visit, plus the shortfall in percentage points multiplied by 40,000
    cents per percentage point and rounded half up to a whole cent."
    PRD §3.1: "Whenever the contract is in `SERVICE_ALERT` and the count falls to
    **one or fewer**, it de-escalates `SERVICE_ALERT → ACTIVE`, again incrementing
    `version`."

    Design: Difficulty/combinatorial_formula/service_credit_rounds_per_car_before_summing
    """
    program = setup_three_car_late_callbacks()
    penalty = assess_penalty(program, "2026-08")

    assert penalty["late_callback_count"] == 3
    assert penalty["raw_amount_cents"] == 75_000
    assert penalty["amount_cents"] == 75_000

    contract = read_contract(program.contract_id)
    assert contract["status"] == "ACTIVE"
    assert contract["cars_out_of_service_count"] == 0


def test_waiving_a_penalty_restores_the_balance_exactly(api):
    """PRD §3.8: "`DISPUTED → WAIVED` adds `amount_cents` to
    `penalty_lifetime_waived_cents` and recomputes `penalty_balance_cents` from the
    defining relation, restoring the pre-assessment balance exactly."
    PRD §3.8: "The contract's ledger is a conserved quantity with a single defining
    relation: `penalty_balance_cents` always equals `penalty_lifetime_assessed_cents`
    less `penalty_lifetime_waived_cents` less `penalty_lifetime_credited_cents`."

    Design: Difficulty/compensating_invariant/penalty_waiver_conserves_contract_money_ledger_exactly
    """
    program = setup_late_callback_month(
        car_code="CAR-V1",
        monthly_base_fee_cents=480_000,
        building_name="Upsilon Flats",
        building_address="20 Ups Ave",
        building_manager_user_id="bm-v",
        contractor_user_id="sc-v",
    )
    balance_before = read_contract(program.contract_id)["penalty_balance_cents"]
    assert balance_before == 0

    penalty = assess_penalty(program, "2026-08")
    assert penalty["amount_cents"] == 25_000
    assert read_contract(program.contract_id)["penalty_balance_cents"] == 25_000

    dispute_penalty(program, penalty["id"], "outage was owner-caused power loss")
    resolved = validate_success(
        api.resolve_penalty(
            penalty["id"],
            {"resolution": "WAIVED", "resolution_note": "accepted owner evidence"},
            program.second_admin_headers,
        )
    )
    assert resolved["status"] == "WAIVED"
    assert resolved["resolved_by_user_id"] == "pa-2"

    contract = read_contract(program.contract_id)
    assert contract["penalty_lifetime_assessed_cents"] == 25_000
    assert contract["penalty_lifetime_waived_cents"] == 25_000
    assert contract["penalty_lifetime_credited_cents"] == 0
    assert contract["penalty_balance_cents"] == 0
    assert contract["penalty_balance_cents"] == balance_before
    assert_contract_ledger_invariant(contract)


def test_disputing_a_penalty_leaves_the_balance_untouched(api):
    """PRD §3.8: "A `BuildingManager` who disagrees disputes the assessment, driving
    `ISSUED → DISPUTED` and recording a `dispute_reason`. Disputing changes no
    money: `penalty_balance_cents` is left exactly as it was while the argument is
    had."
    PRD §3.8: "Under **`SCHEDULE_A`** the penalty is a sum of flat per-incident fees
    plus a linear charge for the uptime shortfall."

    Design: Difficulty/compensating_invariant/penalty_waiver_conserves_contract_money_ledger_exactly
    """
    program = setup_late_callback_month(
        car_code="CAR-V1",
        monthly_base_fee_cents=480_000,
        building_name="Upsilon Flats",
        building_address="20 Ups Ave",
        building_manager_user_id="bm-v",
        contractor_user_id="sc-v",
    )
    penalty = assess_penalty(program, "2026-08")
    assert penalty["raw_amount_cents"] == 25_000
    assert penalty["cap_amount_cents"] == 120_000
    assert penalty["uptime_pct_applied"] == 100.00
    assert penalty["service_credit_cents"] == 0

    disputed = dispute_penalty(program, penalty["id"], "owner-caused power loss")
    assert disputed["status"] == "DISPUTED"
    assert read_contract(program.contract_id)["penalty_balance_cents"] == 25_000


def test_contract_status_is_checked_before_the_cars_in_scope_rule(api, admin_headers):
    """PRD §2.7: "**Governing contract status.** Operational writes require the
    governing contract to be in either `ACTIVE` or `SERVICE_ALERT`; opening a
    renegotiation requires the contract to be exactly `ACTIVE`; countering,
    accepting or closing a round requires it to be exactly `UNDER_RENEGOTIATION`. A
    violation is `ERR_CONTRACT_NOT_ACTIVE` (409)."
    PRD §2.7: "**Cars in scope.** A penalty may only be assessed on a contract that
    has at least one car whose `availability_state` is not `DECOMMISSIONED`,
    otherwise `ERR_NO_CARS_IN_SCOPE` (422)."
    PRD §2.7: "Checks are applied strictly in the sequence below and **the first
    check that fails determines the response**; no later check is consulted. A
    request that would trip several rules always reports the earliest one."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_penalty_on_draft_contract_with_no_cars
    """
    contract = create_draft_contract(
        building_name="Lambda Annex",
        building_address="11 Lambda Ct",
        building_manager_user_id="bm-l",
        contractor_user_id="sc-l",
    )
    set_clock("2026-09-01T00:00:00Z")

    error = validate_error(
        api.create_penalty(
            create_penalty_payload(
                contract["id"], "2026-08", contract_version(contract["id"])
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_NO_CARS_IN_SCOPE.value, (
        "the contract-status rule is earlier in the rejection order"
    )


def test_the_rejected_draft_assessment_writes_nothing(api, admin_headers):
    """PRD §3.1: "A newly drafted contract lands in `status` `DRAFT` with `version` 1
    and its entire penalty ledger zeroed — `penalty_lifetime_assessed_cents`,
    `penalty_lifetime_waived_cents`, `penalty_lifetime_credited_cents` and
    `penalty_balance_cents` all 0 — along with `cars_out_of_service_count` 0,
    `renegotiation_round_count` 0, and `performance_score` null, because no score
    has yet been evaluated."
    PRD §2.7: "**Governing contract status.** Operational writes require the
    governing contract to be in either `ACTIVE` or `SERVICE_ALERT`; opening a
    renegotiation requires the contract to be exactly `ACTIVE`; countering,
    accepting or closing a round requires it to be exactly `UNDER_RENEGOTIATION`. A
    violation is `ERR_CONTRACT_NOT_ACTIVE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_penalty_on_draft_contract_with_no_cars
    """
    contract = create_draft_contract(
        building_name="Lambda Annex",
        building_address="11 Lambda Ct",
        building_manager_user_id="bm-l",
        contractor_user_id="sc-l",
    )
    set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api.create_penalty(
            create_penalty_payload(
                contract["id"], "2026-08", contract_version(contract["id"])
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
    )

    stored = read_contract(contract["id"])
    assert stored["status"] == "DRAFT"
    assert stored["penalty_lifetime_assessed_cents"] == 0

    rows, meta = validate_paginated(
        api.list_penalties(admin_headers, {"contract_id": contract["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_assessing_a_month_that_is_still_open_is_refused(api, admin_headers):
    """PRD §3.8: "It can only be run on a **closed** month — the logical clock must
    already have reached or passed the first instant of the month following
    `period_month`, or the request is refused with `ERR_PENALTY_PERIOD_NOT_CLOSED` —
    and only on a contract that still has at least one car whose
    `availability_state` is not `DECOMMISSIONED`, or the request is refused with
    `ERR_NO_CARS_IN_SCOPE`."

    Design: Corner/validations/assessing_a_still_open_month_returns_period_not_closed
    """
    program = setup_program(
        ["CAR-V6"],
        building_name="Val Six",
        building_address="6 Val St",
        building_manager_user_id="bm-v6",
        contractor_user_id="sc-v6",
    )
    set_clock("2026-08-31T23:59:00Z", program.admin_headers)

    validate_error(
        api.create_penalty(
            create_penalty_payload(
                program.contract_id, "2026-08", contract_version(program.contract_id)
            ),
            program.admin_headers,
        ),
        ApiErrorId.ERR_PENALTY_PERIOD_NOT_CLOSED.value,
    )

    rows, meta = validate_paginated(
        api.list_penalties(admin_headers, {"contract_id": program.contract_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_contract(program.contract_id)["penalty_balance_cents"] == 0


def test_assessing_an_active_contract_with_no_cars_is_refused(api, admin_headers):
    """PRD §3.8: "It can only be run on a **closed** month — the logical clock must
    already have reached or passed the first instant of the month following
    `period_month`, or the request is refused with `ERR_PENALTY_PERIOD_NOT_CLOSED` —
    and only on a contract that still has at least one car whose
    `availability_state` is not `DECOMMISSIONED`, or the request is refused with
    `ERR_NO_CARS_IN_SCOPE`."

    Design: Corner/errors/assessing_an_active_contract_with_no_cars_returns_no_cars_in_scope
    """
    program = setup_program(
        building_name="Er Three",
        building_address="3 Er St",
        building_manager_user_id="bm-e3",
        contractor_user_id="sc-e3",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    validate_error(
        api.create_penalty(
            create_penalty_payload(
                program.contract_id, "2026-08", contract_version(program.contract_id)
            ),
            program.admin_headers,
        ),
        ApiErrorId.ERR_NO_CARS_IN_SCOPE.value,
    )

    contract = read_contract(program.contract_id)
    assert contract["status"] == "ACTIVE"
    assert contract["penalty_balance_cents"] == 0

    rows, meta = validate_paginated(
        api.list_penalties(admin_headers, {"contract_id": program.contract_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_existence_is_checked_before_the_period_close_rule(api, admin_headers):
    """PRD §2.7: "**Existence.** Every resource the request names must exist, checked
    left to right: the identifier in the URL path first, and then the foreign-key
    fields in the request body in the fixed order `contract_id`, `car_id`,
    `part_id`, `window_id`, `project_id`. A missing contract yields
    `ERR_CONTRACT_NOT_FOUND`"
    PRD §2.7: "**Penalty period closed.** The assessed month must be closed, meaning
    the logical clock has reached or passed the first instant of the month following
    `period_month`, otherwise `ERR_PENALTY_PERIOD_NOT_CLOSED` (422)."

    Design: Corner/validations/existence_check_runs_before_period_close_check_and_returns_not_found
    """
    real_contract = create_draft_contract(
        building_name="Val One",
        building_address="1 Val St",
        building_manager_user_id="bm-v1",
        contractor_user_id="sc-v1",
    )

    error = validate_error(
        api.create_penalty(
            create_penalty_payload(UNUSED_UUID, "2026-08", real_contract["version"]),
            admin_headers,
        ),
        ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_PENALTY_PERIOD_NOT_CLOSED.value, (
        "existence is checked before the period-closed rule"
    )
    assert read_contract(real_contract["id"])["penalty_lifetime_assessed_cents"] == 0


def test_a_stale_contract_version_blocks_a_reassessment(api, admin_headers):
    """PRD §2.8: "Assessing a penalty must carry `expected_contract_version`, a
    non-optional field holding the `version` of the target `ServiceContract` as the
    client last observed it."
    PRD §2.8: "If `expected_contract_version` does not equal the contract's current
    `version`, the request is rejected with `ERR_STALE_CONTRACT_VERSION` and HTTP
    412, and the client must re-read the contract before retrying."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_contract_version_blocks_penalty_reassessment
    """
    program = setup_late_callback_month(
        car_code="CAR-CC1",
        monthly_base_fee_cents=480_000,
        building_name="Cc One",
        building_address="1 Cc St",
        building_manager_user_id="bm-c1x",
        contractor_user_id="sc-c1x",
    )
    observed_version = contract_version(program.contract_id)

    first = validate_success(
        api.create_penalty(
            create_penalty_payload(program.contract_id, "2026-08", observed_version),
            program.admin_headers,
        ),
        201,
    )
    assert first["amount_cents"] == 25_000
    assert first["status"] == "ISSUED"
    assert contract_version(program.contract_id) == observed_version + 1

    validate_error(
        api.create_penalty(
            create_penalty_payload(program.contract_id, "2026-08", observed_version),
            program.admin_headers,
        ),
        ApiErrorId.ERR_STALE_CONTRACT_VERSION.value,
    )

    assert read_penalty(first["id"])["status"] == "ISSUED"
    contract = read_contract(program.contract_id)
    assert contract["penalty_lifetime_assessed_cents"] == 25_000
    assert contract["penalty_balance_cents"] == 25_000

    rows, meta = validate_paginated(
        api.list_penalties(admin_headers, {"contract_id": program.contract_id})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_a_fresh_contract_version_supersedes_the_prior_assessment(api, admin_headers):
    """PRD §3.8: "Re-assessing a period is explicitly supported: when an assessment
    for the same `contract_id` and `period_month` already exists in `ISSUED`, that
    prior assessment is driven to `SUPERSEDED` and its `amount_cents` is subtracted
    back out of the contract's `penalty_lifetime_assessed_cents`, so assessments for
    one period supersede rather than accumulate."
    PRD §2.8: "Re-assessing a period is a supported operation — a fresh assessment
    supersedes the earlier `ISSUED` one for the same `contract_id` and
    `period_month` and rewrites the contract's penalty ledger — so a client working
    from a stale view of that ledger would otherwise overwrite balances it never
    saw."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_contract_version_supersedes_the_prior_assessment
    """
    program = setup_late_callback_month(
        car_code="CAR-CC2",
        monthly_base_fee_cents=480_000,
        building_name="Cc Two",
        building_address="2 Cc St",
        building_manager_user_id="bm-c2x",
        contractor_user_id="sc-c2x",
    )
    version_before = contract_version(program.contract_id)
    first = validate_success(
        api.create_penalty(
            create_penalty_payload(program.contract_id, "2026-08", version_before),
            program.admin_headers,
        ),
        201,
    )

    version_after = contract_version(program.contract_id)
    assert version_after == version_before + 1

    second = validate_success(
        api.create_penalty(
            create_penalty_payload(program.contract_id, "2026-08", version_after),
            program.admin_headers,
        ),
        201,
    )
    assert read_penalty(first["id"])["status"] == "SUPERSEDED"
    assert second["status"] == "ISSUED"
    assert second["amount_cents"] == 25_000

    contract = read_contract(program.contract_id)
    assert contract["penalty_lifetime_assessed_cents"] == 25_000, (
        "assessments for one period supersede rather than accumulate"
    )
    assert contract["penalty_balance_cents"] == 25_000

    rows, meta = validate_paginated(
        api.list_penalties(admin_headers, {"contract_id": program.contract_id})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
