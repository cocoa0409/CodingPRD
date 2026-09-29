"""Refurbishment effort: per-line costing, the rework cycle and the QC decision."""

from test_helpers import (
    BAY_CLEANING,
    BAY_REPAIR,
    GRADE_POLICY_FOOTWEAR_A,
    MERCH,
    TECH1,
    TECH2,
    api_client,
    assert_pagination_meta,
    assert_refurb_task,
    assert_unit_dimensions,
    create_refurb_bay,
    fetch_customer,
    fetch_refurb_order,
    fetch_unit,
    list_unit_payload,
    log_refurb_task,
    qc_decision_payload,
    schedule_refurb_order,
    setup_accepted_trade_in,
    setup_estate,
    start_refurb_order,
    submit_refurb_qc,
    validate_error,
    validate_paginated,
    validate_success,
)

def _outerwear_repair_estate():
    """The OUTERWEAR grade B tier plus a single REPAIR bay at ST-01."""
    return setup_estate(bays=(BAY_REPAIR,))


def _footwear_repair_estate():
    """The FOOTWEAR grade A tier (cap 2500 bp) plus a single REPAIR bay."""
    return setup_estate(grade_policies=(GRADE_POLICY_FOOTWEAR_A,), bays=(BAY_REPAIR,))


def _footwear_unit(estate):
    """A PLUS participant's accepted 120000-msrp FOOTWEAR grade A item."""
    return setup_accepted_trade_in(
        estate,
        loyalty_tier="PLUS",
        product_category="FOOTWEAR",
        declared_grade="A",
        assessed_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )


def _in_progress_order(unit, bay, window=("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")):
    """Book the unit into the bay and take the order to IN_PROGRESS under tech-001."""
    order = schedule_refurb_order(unit, bay, window)
    return start_refurb_order(order["id"], TECH1)


def test_two_identical_repair_lines_round_up_before_they_are_summed():
    """784, not 783: the half-cent is resolved once per line.

    PRD §3.5: "Labour is booked at 145 minor units per labour minute, and that
    rate is then scaled by the multiplier of the **bay** the order booked — not by
    the line's own `task_type`."
    PRD §3.5: "That raw labour value is rounded **half up to whole minor units
    first**, and only then is the line's `parts_cost_minor` added; the sum is the
    line's `cost_minor`."
    PRD §3.5: "The order's `logged_cost_minor` is then the plain integer sum of
    the `cost_minor` values of every task line belonging to it, taken in ascending
    `sequence_no` order."
    PRD §3.5: "The sequence matters for reproducibility, and the per-line
    rounding matters for the answer: summing the unrounded labour products across
    lines and rounding once at the end yields a different, incorrect total."
    PRD §3.5: "When that baseline is greater than zero, `viability_ratio_bp` is
    the order's `logged_cost_minor` multiplied by ten thousand, divided by the
    baseline, rounded down."

    Design: Difficulty/combinatorial_formula/refurb_cost_rounds_per_task_line_before_summation
    """
    estate = _outerwear_repair_estate()
    unit = setup_accepted_trade_in(estate)["unit"]
    order = _in_progress_order(unit, estate["bay"])

    # Each line: 2 * 145 * 13500 / 10000 = 391.5, rounded half up to 392.
    first = log_refurb_task(order["id"], "REPAIR", 2, 0)
    second = log_refurb_task(order["id"], "REPAIR", 2, 0)

    assert_refurb_task(first)
    assert_refurb_task(second)
    assert first["cost_minor"] == 392
    assert second["cost_minor"] == 392
    assert first["sequence_no"] == 1
    assert second["sequence_no"] == 2

    after = fetch_refurb_order(order["id"])
    assert after["logged_cost_minor"] == 784
    # Summing 391.5 + 391.5 and rounding once would have produced 783.
    assert after["logged_cost_minor"] != 783
    # Baseline floor(50000 * 3900 / 10000) = 19500, so floor(784 * 10000 / 19500).
    assert after["viability_ratio_bp"] == 402
    # Logging effort does not move the order.
    assert after["status"] == "IN_PROGRESS"
    assert fetch_unit(unit["id"])["lifecycle_state"] == "IN_REFURB"


def test_the_parts_leg_is_added_only_after_the_labour_leg_is_rounded():
    """Three lines, one of them carrying parts, and the gap widens to two.

    PRD §3.5: "That raw labour value is rounded **half up to whole minor units
    first**, and only then is the line's `parts_cost_minor` added; the sum is the
    line's `cost_minor`."
    PRD §3.5: "Each line takes its `refurb_order_id` from the order segment of
    the creation path and declares a `task_type` of `CLEANING`, `REPAIR` or
    `REPACKAGING`, the `labor_minutes` booked to the line — a whole number of at
    least zero — and the `parts_cost_minor` spent on it, also at least zero."
    PRD §3.5: "The order's `logged_cost_minor` is then the plain integer sum of
    the `cost_minor` values of every task line belonging to it, taken in ascending
    `sequence_no` order."
    PRD §3.5: "Both `logged_cost_minor` and `viability_ratio_bp` are
    re-materialized on every task-line append and again when the order is
    submitted for quality control, and each re-materialization increments the
    order's version."

    Design: Difficulty/combinatorial_formula/refurb_cost_rounds_per_task_line_before_summation
    """
    estate = _outerwear_repair_estate()
    unit = setup_accepted_trade_in(estate)["unit"]
    order = _in_progress_order(unit, estate["bay"])
    version_before_lines = order["version"]

    plain_one = log_refurb_task(order["id"], "REPAIR", 2, 0)
    plain_two = log_refurb_task(order["id"], "CLEANING", 2, 0)
    # 392 of rounded labour plus 100 of parts, in that order.
    with_parts = log_refurb_task(order["id"], "REPACKAGING", 2, 100)

    assert plain_one["cost_minor"] == 392
    assert plain_two["cost_minor"] == 392
    assert with_parts["cost_minor"] == 492
    assert with_parts["parts_cost_minor"] == 100
    assert with_parts["sequence_no"] == 3

    after = fetch_refurb_order(order["id"])
    # 392 + 392 + 492; rounding the summed labour once would give 1275.
    assert after["logged_cost_minor"] == 1276
    assert after["logged_cost_minor"] != 1275
    assert after["viability_ratio_bp"] == 654
    # Three appends, three re-materializations, three version bumps.
    assert after["version"] == version_before_lines + 3

    submitted = submit_refurb_qc(order["id"], TECH1)
    assert submitted["status"] == "QC_PENDING"
    assert submitted["logged_cost_minor"] == 1276
    assert submitted["viability_ratio_bp"] == 654


def test_the_rework_cycle_reenters_in_progress_until_the_third_failure_is_refused():
    """The counter is incremented by the restart, and it caps the cycle at two.

    PRD §3.5: "A **fail** sends the order to `QC_FAILED` and leaves the unit
    sitting in `IN_REFURB`."
    PRD §3.5: "From `QC_FAILED` it moves the order back to `IN_PROGRESS` as a
    rework round: `rework_count` is incremented by one, and on this leg there is
    **no** cross-entity move at all — the unit was already `IN_REFURB` and stays
    there."
    PRD §3.5: "A rework round is only admissible while `rework_count` is still
    below two."
    PRD §3.5: "It is admissible only while `rework_count` is below two; once two
    rework rounds have been consumed, a further fail is refused with
    `ERR_REWORK_LIMIT_EXCEEDED` and the order must be passed or salvaged instead."
    PRD §3.5: "That cap is what makes the cycle that runs from `IN_PROGRESS` to
    `QC_PENDING`, on to `QC_FAILED`, and back to `IN_PROGRESS` finite: a third
    failure is unreachable."

    Design: Difficulty/non_linear_state_machine/refurb_order_rework_cycle_reenters_in_progress_until_limit
    """
    estate = _outerwear_repair_estate()
    unit = setup_accepted_trade_in(estate)["unit"]

    # Round 0: the SCHEDULED leg, which is not a rework round.
    first_pass = _in_progress_order(unit, estate["bay"])
    assert first_pass["status"] == "IN_PROGRESS"
    assert first_pass["rework_count"] == 0
    assert fetch_unit(unit["id"])["lifecycle_state"] == "IN_REFURB"

    submit_refurb_qc(first_pass["id"], TECH1)
    failed_once = validate_success(
        api_client.decide_refurb_order_qc(
            first_pass["id"], qc_decision_payload("FAIL"), TECH2
        )
    )
    assert failed_once["status"] == "QC_FAILED"
    # The failure itself consumes no round; the restart is what counts one.
    assert failed_once["rework_count"] == 0
    assert fetch_unit(unit["id"])["lifecycle_state"] == "IN_REFURB"

    # Round 1.
    rework_one = start_refurb_order(first_pass["id"], TECH1)
    assert rework_one["status"] == "IN_PROGRESS"
    assert rework_one["rework_count"] == 1
    assert fetch_unit(unit["id"])["lifecycle_state"] == "IN_REFURB"

    submit_refurb_qc(first_pass["id"], TECH1)
    failed_twice = validate_success(
        api_client.decide_refurb_order_qc(
            first_pass["id"], qc_decision_payload("FAIL"), TECH2
        )
    )
    assert failed_twice["status"] == "QC_FAILED"
    assert failed_twice["rework_count"] == 1

    # Round 2, the last one the cap admits.
    rework_two = start_refurb_order(first_pass["id"], TECH1)
    assert rework_two["status"] == "IN_PROGRESS"
    assert rework_two["rework_count"] == 2

    third_submission = submit_refurb_qc(first_pass["id"], TECH1)
    assert third_submission["status"] == "QC_PENDING"
    # No lines were ever logged, so the viability gate can never be the reason.
    assert third_submission["logged_cost_minor"] == 0
    assert third_submission["viability_ratio_bp"] == 0

    validate_error(
        api_client.decide_refurb_order_qc(
            first_pass["id"], qc_decision_payload("FAIL"), TECH2
        ),
        "ERR_REWORK_LIMIT_EXCEEDED",
        409,
    )

    after = fetch_refurb_order(first_pass["id"])
    assert after["rework_count"] == 2
    assert after["status"] == "QC_PENDING"
    assert fetch_unit(unit["id"])["lifecycle_state"] == "IN_REFURB"

    # The order must now be passed or salvaged instead, and a pass still works.
    passed = validate_success(
        api_client.decide_refurb_order_qc(
            first_pass["id"], qc_decision_payload("PASS"), TECH2
        )
    )
    assert passed["status"] == "COMPLETED"
    assert passed["rework_count"] == 2


def test_a_rework_round_keeps_its_earlier_lines_and_rotates_the_technician():
    """The cycle accumulates cost and hands the sign-off partner over.

    PRD §3.5: "Either leg requires the booked bay to be `AVAILABLE`, and either
    leg writes the acting operator's identifier into `performed_by_user_id`,
    overwriting whatever was there, so the technician on record — and hence the
    partner who is allowed to sign quality control — can change from round to
    round."
    PRD §3.5: "Task lines are never amended, never voided and never deleted;
    there is no exclusion status, so every line an order has ever accumulated —
    including lines appended during rework rounds — is part of its cost forever."
    PRD §3.5: "Whatever the decision, the signer's `X-User-ID` must differ from
    the order's `performed_by_user_id` or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`, and a successful decision records the signer in
    `qc_by_user_id`."
    PRD §3.5: "For an `OWNED_INVENTORY` unit, `capitalized_cost_minor` is that
    acquisition cost plus the completing order's `logged_cost_minor`: the brand
    currency the programme paid at intake, plus the refurbishment capitalized into
    the same carrying value."

    Design: Difficulty/non_linear_state_machine/refurb_order_rework_cycle_reenters_in_progress_until_limit
    """
    estate = _outerwear_repair_estate()
    scenario = setup_accepted_trade_in(estate)
    unit = scenario["unit"]
    # An in-store STANDARD participant: base 50000 * 2000bp and no bonus term.
    assert scenario["grant"]["issued_amount_minor"] == 10000

    order = _in_progress_order(unit, estate["bay"])
    assert order["performed_by_user_id"] == "tech-001"
    log_refurb_task(order["id"], "REPAIR", 2, 0, TECH1)
    submit_refurb_qc(order["id"], TECH1)

    failed = validate_success(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("FAIL"), TECH2)
    )
    assert failed["status"] == "QC_FAILED"
    assert failed["logged_cost_minor"] == 392
    assert failed["qc_by_user_id"] == "tech-002"

    # The second technician picks the job up, so the record of the performer moves.
    reworking = start_refurb_order(order["id"], TECH2)
    assert reworking["performed_by_user_id"] == "tech-002"
    assert reworking["rework_count"] == 1
    # The round-one line is still on the order and still counted.
    assert reworking["logged_cost_minor"] == 392

    log_refurb_task(order["id"], "REPAIR", 2, 0, TECH2)
    resubmitted = submit_refurb_qc(order["id"], TECH2)
    assert resubmitted["logged_cost_minor"] == 784

    lines, meta = validate_paginated(api_client.list_refurb_tasks(order["id"], TECH1))
    assert_pagination_meta(meta, 2)
    assert [line["sequence_no"] for line in lines] == [1, 2]
    assert [line["logged_by_user_id"] for line in lines] == ["tech-001", "tech-002"]

    # tech-002 now owns the work, so tech-002 may no longer sign it off.
    validate_error(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), TECH2),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )

    passed = validate_success(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), TECH1)
    )
    assert passed["status"] == "COMPLETED"
    assert passed["qc_by_user_id"] == "tech-001"

    ready = fetch_unit(unit["id"])
    assert_unit_dimensions(ready, "READY", "CAPITALIZED")
    # 10000 of brand currency at intake plus both rework rounds' 784.
    assert ready["capitalized_cost_minor"] == 10784


def test_a_viability_ratio_exactly_at_the_tier_cap_still_passes():
    """2500 against a cap of 2500 is inside the gate, not outside it.

    PRD §3.5: "The order's `viability_ratio_bp` must be at most the
    `refurb_budget_cap_pct_bp` of the `ACTIVE` condition-tier policy for the unit's
    (`product_category`, `condition_grade`) pair."
    PRD §3.5: "The comparison is inclusive: a ratio exactly equal to the cap is
    viable, and only a strictly greater ratio trips the gate with
    `ERR_REFURB_NOT_VIABLE`."
    PRD §3.5: "The baseline resale value is the unit's `reference_msrp_minor`
    multiplied by the `resale_price_pct_bp` of the `ACTIVE` condition-tier policy
    for the unit's own (`product_category`, `condition_grade`) pair, divided by ten
    thousand and rounded down."
    PRD §3.5: "As a caused second link it advances the unit's `lifecycle_state`
    from `IN_REFURB` to `READY`, and — only when the unit's `ownership_treatment`
    is `OWNED_INVENTORY` — advances its `accounting_state` from `UNCAPITALIZED` to
    `CAPITALIZED` and writes `capitalized_cost_minor`; the unit's version is
    incremented either way."

    Design: Difficulty/boundary_precision_check/viability_ratio_exactly_at_tier_cap_is_still_viable
    """
    estate = _footwear_repair_estate()
    scenario = _footwear_unit(estate)
    unit = scenario["unit"]
    # Base 42000 with no mail-in term and a PLUS bonus of 2100.
    assert scenario["grant"]["issued_amount_minor"] == 44100
    assert unit["reference_msrp_minor"] == 120000

    order = _in_progress_order(unit, estate["bay"])
    # 392 of rounded labour plus 19108 of parts lands exactly on the cap.
    line = log_refurb_task(order["id"], "REPAIR", 2, 19108)
    assert line["cost_minor"] == 19500

    priced = fetch_refurb_order(order["id"])
    assert priced["logged_cost_minor"] == 19500
    # Baseline floor(120000 * 6500 / 10000) = 78000, so 19500 * 10000 / 78000.
    assert priced["viability_ratio_bp"] == 2500

    submit_refurb_qc(order["id"], TECH1)
    passed = validate_success(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), TECH2)
    )
    assert passed["status"] == "COMPLETED"
    assert passed["viability_ratio_bp"] == 2500

    ready = fetch_unit(unit["id"])
    assert_unit_dimensions(ready, "READY", "CAPITALIZED")
    assert ready["capitalized_cost_minor"] == 63600


def test_one_basis_point_past_the_tier_cap_trips_the_viability_gate():
    """2501 is strictly greater, and eight minor units of parts are the difference.

    PRD §3.5: "The comparison is inclusive: a ratio exactly equal to the cap is
    viable, and only a strictly greater ratio trips the gate with
    `ERR_REFURB_NOT_VIABLE`."
    PRD §3.5: "That raw labour value is rounded **half up to whole minor units
    first**, and only then is the line's `parts_cost_minor` added; the sum is the
    line's `cost_minor`."
    PRD §3.5: "When that baseline is greater than zero, `viability_ratio_bp` is
    the order's `logged_cost_minor` multiplied by ten thousand, divided by the
    baseline, rounded down."
    PRD §3.5: "A pass moves the order to `COMPLETED`, bumps its version and
    releases the bay window."

    Design: Difficulty/boundary_precision_check/viability_ratio_exactly_at_tier_cap_is_still_viable
    """
    estate = _footwear_repair_estate()
    unit = _footwear_unit(estate)["unit"]

    order = _in_progress_order(unit, estate["bay"])
    line = log_refurb_task(order["id"], "REPAIR", 2, 19116)
    assert line["cost_minor"] == 19508

    submitted = submit_refurb_qc(order["id"], TECH1)
    assert submitted["logged_cost_minor"] == 19508
    # floor(19508 * 10000 / 78000) = 2501, one basis point past the cap.
    assert submitted["viability_ratio_bp"] == 2501

    validate_error(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), TECH2),
        "ERR_REFURB_NOT_VIABLE",
        409,
    )

    # The refused pass moved neither the order nor either unit dimension.
    after = fetch_refurb_order(order["id"])
    assert after["status"] == "QC_PENDING"
    assert after["qc_by_user_id"] is None
    blocked_unit = fetch_unit(unit["id"])
    assert_unit_dimensions(blocked_unit, "IN_REFURB", "UNCAPITALIZED")
    assert blocked_unit["capitalized_cost_minor"] == 0


def test_the_identity_rule_answers_first_when_the_order_is_also_over_budget():
    """One request breaks two rules and hears about the operator, not the money.

    PRD §2.11: "**Segregation of duties**, enforced with
    `ERR_SEGREGATION_OF_DUTIES` (409), on the re-grade of an appealed trade-in and
    on a quality-control decision."
    PRD §2.11: "**Refurbishment viability**, enforced with
    `ERR_REFURB_NOT_VIABLE` (409), then the override-privilege check
    `ERR_OVERRIDE_ROLE_REQUIRED` (403), both on a quality-control decision."
    PRD §3.5: "Whatever the decision, the signer's `X-User-ID` must differ from
    the order's `performed_by_user_id` or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`, and a successful decision records the signer in
    `qc_by_user_id`."
    PRD §3.5: "Supplying `viability_override_reason` as a `RefurbTechnician` or a
    `MerchandisingManager` is refused with `ERR_OVERRIDE_ROLE_REQUIRED` — the
    override authority is the `ProgramAdmin`'s alone and cannot be borrowed."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_refurb_viability_threshold
    """
    estate = _footwear_repair_estate()
    unit = _footwear_unit(estate)["unit"]

    order = _in_progress_order(unit, estate["bay"])
    assert order["performed_by_user_id"] == "tech-001"
    line = log_refurb_task(order["id"], "REPAIR", 2, 19116, TECH1)
    assert line["cost_minor"] == 19508

    submitted = submit_refurb_qc(order["id"], TECH1)
    assert submitted["logged_cost_minor"] == 19508
    assert submitted["viability_ratio_bp"] == 2501

    # tech-001 both performed the work and is over budget: the identity rule wins.
    validate_error(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), TECH1),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )

    # A different signer clears the identity rule and exposes the money rule.
    validate_error(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), TECH2),
        "ERR_REFURB_NOT_VIABLE",
        409,
    )

    # And borrowing the escape hatch as a technician is its own refusal.
    validate_error(
        api_client.decide_refurb_order_qc(
            order["id"],
            qc_decision_payload("PASS", "flagship consignment, margin accepted by finance"),
            TECH2,
        ),
        "ERR_OVERRIDE_ROLE_REQUIRED",
        403,
    )

    after = fetch_refurb_order(order["id"])
    assert after["status"] == "QC_PENDING"
    assert after["qc_by_user_id"] is None
    assert after["viability_override_reason"] is None
    assert fetch_unit(unit["id"])["accounting_state"] == "UNCAPITALIZED"


def test_each_rule_of_the_pair_also_fires_on_its_own():
    """A comfortably viable order still refuses its own performer's signature.

    PRD §3.5: "Whatever the decision, the signer's `X-User-ID` must differ from
    the order's `performed_by_user_id` or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`, and a successful decision records the signer in
    `qc_by_user_id`."
    PRD §3.5: "The submission recomputes `logged_cost_minor` and
    `viability_ratio_bp` over all task lines — an order that logged nothing submits
    with both at zero — and bumps the version."
    PRD §3.5: "An order with no task lines at all has a `logged_cost_minor` of 0."
    PRD §3.5: "A pass moves the order to `COMPLETED`, bumps its version and
    releases the bay window."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_refurb_viability_threshold
    """
    estate = _footwear_repair_estate()
    scenario = _footwear_unit(estate)
    unit = scenario["unit"]

    order = _in_progress_order(unit, estate["bay"])
    submitted = submit_refurb_qc(order["id"], TECH1)
    # Nothing was logged, so the viability rule has nothing to object to.
    assert submitted["logged_cost_minor"] == 0
    assert submitted["viability_ratio_bp"] == 0

    validate_error(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), TECH1),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )

    passed = validate_success(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), TECH2)
    )
    assert passed["status"] == "COMPLETED"
    assert passed["qc_by_user_id"] == "tech-002"

    ready = fetch_unit(unit["id"])
    assert_unit_dimensions(ready, "READY", "CAPITALIZED")
    # Acquisition cost alone, because the order logged no effort at all.
    assert ready["capitalized_cost_minor"] == scenario["grant"]["issued_amount_minor"]


def test_the_labour_multiplier_follows_the_bay_and_ignores_the_line_type():
    """A REPAIR line in a cleaning bay is the cheap one, and that is the point.

    PRD §3.5: "Labour is booked at 145 minor units per labour minute, and that
    rate is then scaled by the multiplier of the **bay** the order booked — not by
    the line's own `task_type`."
    PRD §3.5: "A `CLEANING` bay multiplies by ten thousand basis points, that is,
    leaves the labour rate unchanged; a `REPAIR` bay multiplies by thirteen
    thousand five hundred basis points, a thirty-five percent premium; and a
    `REPACKAGING` bay multiplies by nine thousand basis points, a ten percent
    discount."
    PRD §3.5: "The server assigns `sequence_no`, the 1-based append position of
    the line within its order, records `logged_by_user_id` as the acting operator,
    and computes `cost_minor`."
    PRD §3.5: "When that baseline is greater than zero, `viability_ratio_bp` is
    the order's `logged_cost_minor` multiplied by ten thousand, divided by the
    baseline, rounded down."

    Design: Corner/calculations/refurb_cost_multiplier_is_keyed_on_bay_type_not_task_type
    """
    estate = setup_estate(bays=(BAY_CLEANING, BAY_REPAIR))
    cleaning_bay, repair_bay = estate["bays"]
    assert cleaning_bay["bay_type"] == "CLEANING"
    assert repair_bay["bay_type"] == "REPAIR"

    first = setup_accepted_trade_in(estate)
    unit_in_cleaning_bay = first["unit"]
    unit_in_repair_bay = setup_accepted_trade_in(estate, customer=first["customer"])["unit"]

    cleaning_order = _in_progress_order(unit_in_cleaning_bay, cleaning_bay)
    repair_order = _in_progress_order(unit_in_repair_bay, repair_bay)

    # Identical ten-minute lines, opposite task types, different bays.
    in_cleaning_bay = log_refurb_task(cleaning_order["id"], "REPAIR", 10, 0)
    in_repair_bay = log_refurb_task(repair_order["id"], "CLEANING", 10, 0)

    # 10 * 145 * 10000 / 10000 = 1450 exactly.
    assert in_cleaning_bay["cost_minor"] == 1450
    # round_half_up(10 * 145 * 13500 / 10000) = round_half_up(1957.5) = 1958.
    assert in_repair_bay["cost_minor"] == 1958
    # sequence_no counts within one order, so both lines are the first of theirs.
    assert in_cleaning_bay["sequence_no"] == 1
    assert in_repair_bay["sequence_no"] == 1

    cheap = fetch_refurb_order(cleaning_order["id"])
    dear = fetch_refurb_order(repair_order["id"])
    assert cheap["logged_cost_minor"] == 1450
    assert dear["logged_cost_minor"] == 1958
    # Both against the same baseline of floor(50000 * 3900 / 10000) = 19500.
    assert cheap["viability_ratio_bp"] == 743
    assert dear["viability_ratio_bp"] == 1004
    # Both sit far below the tier's 3000 bp budget cap.
    assert cheap["viability_ratio_bp"] < 3000
    assert dear["viability_ratio_bp"] < 3000


def test_effort_lines_are_append_only_and_carry_no_concurrency_fields():
    """Two lines, two sequence numbers, and nothing that could be amended.

    PRD §2.6: "A **brand-currency ledger entry** and a **refurbishment task
    line** carry only `id` and `created_at`."
    PRD §2.6: "Neither has an `updated_at` field and neither has a `version`
    field — those two fields are absent from their representations entirely,
    because neither row is ever mutated, voided or deleted after it is written."
    PRD §3.5: "Task lines are never amended, never voided and never deleted;
    there is no exclusion status, so every line an order has ever accumulated —
    including lines appended during rework rounds — is part of its cost forever."
    PRD §3.5: "The server assigns `sequence_no`, the 1-based append position of
    the line within its order, records `logged_by_user_id` as the acting operator,
    and computes `cost_minor`."

    Design: Corner/entities/refurb_task_row_is_immutable_and_carries_no_version
    """
    estate = _outerwear_repair_estate()
    unit = setup_accepted_trade_in(estate)["unit"]
    order = _in_progress_order(unit, estate["bay"])

    first = log_refurb_task(order["id"], "REPAIR", 2, 0, TECH1)
    second = log_refurb_task(order["id"], "REPAIR", 2, 0, TECH2)

    for line in (first, second):
        assert_refurb_task(line)
        assert line["refurb_order_id"] == order["id"]
        assert line["cost_minor"] == 392
        assert "version" not in line
        assert "updated_at" not in line

    assert first["sequence_no"] == 1
    assert second["sequence_no"] == 2
    assert first["logged_by_user_id"] == "tech-001"
    assert second["logged_by_user_id"] == "tech-002"

    listed, meta = validate_paginated(api_client.list_refurb_tasks(order["id"], TECH1))
    assert_pagination_meta(meta, 2)
    assert [row["id"] for row in listed] == [first["id"], second["id"]]
    assert [row["sequence_no"] for row in listed] == [1, 2]

    # The second line added to the first rather than replacing it.
    assert fetch_refurb_order(order["id"])["logged_cost_minor"] == 784


def test_the_task_line_listing_paginates_and_filters_within_its_order():
    """The sub-resource read is ordered, pageable and filterable by task type.

    PRD §3.5: "Lines may be listed with an optional `task_type` filter plus
    `limit` and `offset`."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object, alongside the request
    identifier and timestamp."
    PRD §3.5: "The order's `logged_cost_minor` is then the plain integer sum of
    the `cost_minor` values of every task line belonging to it, taken in ascending
    `sequence_no` order."
    PRD §3.5: "Effort is captured as **immutable task lines**, appended only by a
    `RefurbTechnician` and only while the order is `IN_PROGRESS`; logging against an
    order in any other status is `ERR_REFURB_ORDER_NOT_LOGGABLE`."

    Design: Corner/endpoints/refurb_task_subresource_read_is_paginated_and_filterable
    """
    estate = _outerwear_repair_estate()
    unit = setup_accepted_trade_in(estate)["unit"]
    order = _in_progress_order(unit, estate["bay"])

    repair_line = log_refurb_task(order["id"], "REPAIR", 2, 0)
    cleaning_line = log_refurb_task(order["id"], "CLEANING", 2, 0)
    # The bay is REPAIR for both lines, so both cost the same 392.
    assert repair_line["cost_minor"] == 392
    assert cleaning_line["cost_minor"] == 392

    everything, meta = validate_paginated(api_client.list_refurb_tasks(order["id"], TECH1))
    assert_pagination_meta(meta, 2)
    assert [row["task_type"] for row in everything] == ["REPAIR", "CLEANING"]

    page, page_meta = validate_paginated(
        api_client.list_refurb_tasks(order["id"], TECH1, {"limit": 1, "offset": 1})
    )
    assert_pagination_meta(page_meta, 2)
    assert len(page) == 1
    assert page[0]["task_type"] == "CLEANING"
    assert page[0]["sequence_no"] == 2

    filtered, filtered_meta = validate_paginated(
        api_client.list_refurb_tasks(order["id"], TECH1, {"task_type": "CLEANING"})
    )
    assert_pagination_meta(filtered_meta, 1)
    assert filtered[0]["id"] == cleaning_line["id"]

    parent = fetch_refurb_order(order["id"])
    assert parent["logged_cost_minor"] == 784
    assert parent["viability_ratio_bp"] == 402
    assert parent["status"] == "IN_PROGRESS"


def test_the_qc_decision_value_alone_decides_capitalization_or_write_off():
    """Two identical zero-cost orders diverge on the word in the body.

    PRD §3.5: "A pass moves the order to `COMPLETED`, bumps its version and
    releases the bay window."
    PRD §3.5: "The order moves to `SALVAGED`, its version is bumped and the bay
    window is released; as a cross-entity effect the unit's `lifecycle_state` goes
    from `IN_REFURB` to `SALVAGED`, its `accounting_state` goes from `UNCAPITALIZED`
    to `EXPENSED` when its `ownership_treatment` is `OWNED_INVENTORY` — with
    `capitalized_cost_minor` staying at 0, since nothing was ever capitalized — and
    its version is incremented."
    PRD §3.5: "The originating participant's `diverted_grams_total` is then
    recomputed and drops by exactly that unit's `mass_grams`."
    PRD §3.6: "The unit must be in `lifecycle_state` `READY` — its first listing
    after refurbishment — or `RETURNED`, which is the re-listing of a unit that came
    back on a refund; a unit in any other lifecycle state is refused with
    `ERR_UNIT_NOT_READY_FOR_LISTING`."

    Design: Corner/endpoints/qc_decision_branches_on_the_decision_value
    """
    estate = setup_estate()
    second_bay = create_refurb_bay(estate["store"]["id"], BAY_CLEANING, code="BAY-C2")

    first = setup_accepted_trade_in(estate, loyalty_tier="PLUS")
    customer = first["customer"]
    passing_unit = first["unit"]
    salvaged_unit = setup_accepted_trade_in(estate, customer=customer)["unit"]
    # Base 10000 with a PLUS bonus of 500 on the first, STANDARD terms after.
    assert first["grant"]["issued_amount_minor"] == 10500
    assert fetch_customer(customer["id"])["diverted_grams_total"] == 2800

    passing_order = _in_progress_order(passing_unit, estate["bay"])
    submit_refurb_qc(passing_order["id"], TECH1)
    salvaging_order = _in_progress_order(salvaged_unit, second_bay)
    submit_refurb_qc(salvaging_order["id"], TECH1)

    passed = validate_success(
        api_client.decide_refurb_order_qc(
            passing_order["id"], qc_decision_payload("PASS"), TECH2
        )
    )
    assert passed["status"] == "COMPLETED"
    assert passed["qc_by_user_id"] == "tech-002"
    kept = fetch_unit(passing_unit["id"])
    assert_unit_dimensions(kept, "READY", "CAPITALIZED")
    # The grant of 10500 plus a logged cost of 0.
    assert kept["capitalized_cost_minor"] == 10500

    written_off = validate_success(
        api_client.decide_refurb_order_qc(
            salvaging_order["id"], qc_decision_payload("SALVAGE"), TECH2
        )
    )
    assert written_off["status"] == "SALVAGED"
    scrapped = fetch_unit(salvaged_unit["id"])
    assert_unit_dimensions(scrapped, "SALVAGED", "EXPENSED")
    assert scrapped["capitalized_cost_minor"] == 0
    # The scrapped item leaves the diverted bucket it entered on acceptance.
    assert fetch_customer(customer["id"])["diverted_grams_total"] == 1400

    validate_error(
        api_client.list_resale_unit(
            salvaged_unit["id"], list_unit_payload(estate["channel"]["id"]), MERCH
        ),
        "ERR_UNIT_NOT_READY_FOR_LISTING",
        409,
    )
