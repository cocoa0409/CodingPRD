"""Earning, paying and reversing the enrolment incentive."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_SERIAL_START,
    accrue_award,
    apply_device,
    assert_award_lines_sum_to_total,
    assert_incentive_award,
    clawback_award,
    create_active_premises,
    create_approved_supplier,
    create_incentive_award_payload,
    enroll_producer,
    issue_lot,
    make_producer_headers,
    make_program_admin_headers,
    pay_award,
    read_producer,
    receive_arrival,
    register_premises,
    register_producer,
    report_departure,
    set_clock,
    setup_enrolled_producer_with_head,
    validate_error,
    validate_paginated,
)

ADMIN = make_program_admin_headers("admin-reg")


class TestAwardLineRounding:
    def test_each_premises_line_is_rounded_half_up_to_whole_cents(self, api):
        """PRD §3.9: "The award is then built as a list of per-premises lines. Only premises whose `registration_status` is `ACTIVE` at the accrual instant contribute, and they contribute in order of their own `created_at` ascending; a suspended or still-pending premises produces no line at all, rather than a zero-valued line. Each line records the `premises_id`, the premises' `animal_count`, and a `line_cents` amount computed as a base rate of 137 cents per head multiplied by that premises' `animal_count`, multiplied by the frozen `tier_factor`, multiplied by the frozen `compliance_multiplier`, and **rounded half up to whole cents at the line level**."
        PRD §3.9: "Accrual freezes three inputs onto the award so that later drift cannot change a settled amount. The `head_count_snapshot` copies the producer's `enrolled_head_count` at that instant. The `tier_factor` is the multiplier attached to the producer's `incentive_tier`, and the tier table is read directly from the head count: an enrolled head count of 0 is `TIER_0` with a factor of 0.00; from 1 through 99 head is `TIER_1` with a factor of 1.00; from 100 through 499 head is `TIER_2` with a factor of 1.15; and 500 head or more is `TIER_3` with a factor of 1.30. The `compliance_multiplier` is read from the producer's `on_time_movement_pct`: at least 95.00 percent earns 1.25; at least 80.00 but below 95.00 earns 1.00; at least 50.00 but below 80.00 earns 0.60; and below 50.00 earns 0.00, extinguishing the award entirely."

        Design: Difficulty/combinatorial_formula/incentive_award_rounds_each_premises_line_then_sums
        """
        scenario = setup_enrolled_producer_with_head(
            premises_count=2, animals_per_premises=2, capacity=60, state_code="KS",
            legal_name="Twin Creek Ranch",
        )
        award = accrue_award(
            scenario["producer"]["id"], period_start="2026-07-01", period_end="2026-09-30"
        )
        assert_incentive_award(award)

        assert award["head_count_snapshot"] == 4
        assert award["tier_factor"] == 1.00
        assert award["compliance_multiplier"] == 1.25
        assert len(award["line_items"]) == 2
        assert award["line_items"][0]["premises_id"] == scenario["premises_list"][0]["id"], (
            "lines follow the premises created_at ordering"
        )
        # 137 * 2 * 1.00 * 1.25 is exactly 342.5 cents, which rounds half up to 343.
        assert award["line_items"][0]["line_cents"] == 343
        assert award["line_items"][1]["line_cents"] == 343

    def test_award_total_is_the_sum_of_already_rounded_lines(self, api):
        """PRD §2.9: "Where a monetary total is assembled from several lines, the rounding point is pinned: each line is rounded to whole cents first, and the rounded lines are then summed. Summing unrounded products and rounding once at the end is not equivalent and is not what this programme specifies."
        PRD §3.9: "The award's `awarded_cents` is the plain sum of the rounded `line_cents` values across `line_items`; the rounding is never deferred to the sum. A new award is created in `status` `ACCRUED` with `clawback_cents` at 0."

        Design: Difficulty/combinatorial_formula/incentive_award_rounds_each_premises_line_then_sums
        """
        scenario = setup_enrolled_producer_with_head(
            premises_count=2, animals_per_premises=2, capacity=60, state_code="KS",
            legal_name="Twin Creek Ranch",
        )
        award = accrue_award(
            scenario["producer"]["id"], period_start="2026-07-01", period_end="2026-09-30"
        )

        assert award["awarded_cents"] == 686, (
            "rounding each 342.5-cent line first gives 686; rounding the sum once gives 685"
        )
        assert_award_lines_sum_to_total(award)
        assert award["status"] == "ACCRUED"
        assert award["clawback_cents"] == 0

    def test_compliance_multiplier_drops_to_sixty_percent_at_half_on_time(self, api):
        """PRD §3.9: "The `compliance_multiplier` is read from the producer's `on_time_movement_pct`: at least 95.00 percent earns 1.25; at least 80.00 but below 95.00 earns 1.00; at least 50.00 but below 80.00 earns 0.60; and below 50.00 earns 0.00, extinguishing the award entirely."
        PRD §3.9: "The award is then built as a list of per-premises lines. Only premises whose `registration_status` is `ACTIVE` at the accrual instant contribute, and they contribute in order of their own `created_at` ascending; a suspended or still-pending premises produces no line at all, rather than a zero-valued line. Each line records the `premises_id`, the premises' `animal_count`, and a `line_cents` amount computed as a base rate of 137 cents per head multiplied by that premises' `animal_count`, multiplied by the frozen `tier_factor`, multiplied by the frozen `compliance_multiplier`, and **rounded half up to whole cents at the line level**."
        PRD §3.5: "Rolled up to the producer, `on_time_movement_pct` counts every movement whose origin premises belongs to that producer and whose `status` is `REPORTED`, `RECEIVED` or `DISPUTED` as the denominator, and those of them whose `on_time` is true as the numerator; the percentage is 100.0 multiplied by numerator over denominator, rounded half up to two decimal places."

        Design: Corner/calculations/compliance_multiplier_drops_to_sixty_percent_at_half_on_time
        """
        producer = register_producer(legal_name="Half Time Cattle", state_code="KS")
        origin = create_active_premises(
            producer["id"], operation_type="COW_CALF", state_code="KS", capacity=10
        )
        destination = create_active_premises(
            producer["id"], operation_type="FEEDLOT", state_code="KS", capacity=10
        )
        supplier = create_approved_supplier(company_name="Y-Tex Devices")
        lot = issue_lot(supplier["id"], origin["id"], DEFAULT_SERIAL_START, 10)
        first_animal = apply_device(lot["id"], producer["id"], DEFAULT_SERIAL_START, origin["id"])
        second_animal = apply_device(
            lot["id"], producer["id"], DEFAULT_SERIAL_START + 1, origin["id"]
        )
        enroll_producer(producer["id"])

        on_time_move = report_departure(
            producer["id"],
            first_animal["id"],
            origin["id"],
            destination["id"],
            "2026-08-01T00:00:00Z",
        )
        assert on_time_move["on_time"] is True
        receive_arrival(on_time_move["id"], producer["id"], "2026-08-01T00:00:00Z")

        set_clock("2026-08-06T00:00:00Z")
        late_move = report_departure(
            producer["id"],
            second_animal["id"],
            origin["id"],
            destination["id"],
            "2026-08-01T00:00:00Z",
        )
        assert late_move["reporting_lag_hours"] == 120.00
        assert late_move["on_time"] is False
        receive_arrival(late_move["id"], producer["id"], "2026-08-06T00:00:00Z")

        assert read_producer(producer["id"])["on_time_movement_pct"] == 50.00

        award = accrue_award(
            producer["id"], period_start="2026-08-01", period_end="2026-08-31"
        )
        assert award["compliance_multiplier"] == 0.60
        assert award["tier_factor"] == 1.00
        assert award["head_count_snapshot"] == 2
        assert len(award["line_items"]) == 2
        assert award["line_items"][0]["premises_id"] == origin["id"]
        assert award["line_items"][0]["line_cents"] == 0, (
            "an ACTIVE premises holding no head still contributes an explicit zero line"
        )
        assert award["line_items"][1]["line_cents"] == 164
        assert award["awarded_cents"] == 164


class TestIncentiveBalanceConservation:
    def test_clawback_restores_the_balance_to_its_pre_payment_value(self, api):
        """PRD §3.9: "Payment is available only from `ACCRUED` and again requires the owning producer to be `ENROLLED`, else `ERR_PRODUCER_NOT_ENROLLED`. The award moves `ACCRUED → PAID` and the producer's `incentive_balance_cents` increases by the award's `awarded_cents`."
        PRD §3.9: "Reversal is the compensating action, available only from `PAID`. The award moves `PAID → CLAWED_BACK`, its `clawback_cents` is set equal to its `awarded_cents`, the producer's `incentive_balance_cents` decreases by that same amount — restoring the balance exactly to its pre-payment value — and the producer's `lifetime_clawback_cents` increases by that amount."

        Design: Difficulty/compensating_invariant/incentive_balance_conserved_when_award_is_clawed_back
        """
        scenario = setup_enrolled_producer_with_head(
            premises_count=1, animals_per_premises=2, capacity=20, state_code="AZ"
        )
        producer_id = scenario["producer"]["id"]
        assert scenario["producer"]["incentive_balance_cents"] == 0

        award = accrue_award(producer_id, period_start="2026-07-01", period_end="2026-09-30")
        assert award["awarded_cents"] == 343

        pay_award(award["id"])
        assert read_producer(producer_id)["incentive_balance_cents"] == 343

        clawed_back = clawback_award(award["id"])
        assert clawed_back["status"] == "CLAWED_BACK"
        assert clawed_back["clawback_cents"] == 343
        assert read_producer(producer_id)["incentive_balance_cents"] == 0, (
            "the balance returns to exactly its pre-payment value"
        )

    def test_clawback_ratchets_the_lifetime_figure_which_never_decreases(self, api):
        """PRD §3.9: "Reversal is the compensating action, available only from `PAID`. The award moves `PAID → CLAWED_BACK`, its `clawback_cents` is set equal to its `awarded_cents`, the producer's `incentive_balance_cents` decreases by that same amount — restoring the balance exactly to its pre-payment value — and the producer's `lifetime_clawback_cents` increases by that amount. Lifetime clawbacks only ever accumulate; the figure never decreases. Consistent with that, a producer's `incentive_balance_cents` is always the sum of `awarded_cents` across its `PAID` awards less the sum of `clawback_cents` across its `CLAWED_BACK` awards. `CLAWED_BACK` is terminal."
        PRD §2.8: "Second, compensating actions restore the totals they unwind: voiding a movement returns the animal to its origin so that the sum of origin and destination `animal_count` returns to its pre-departure value, and clawing back an award returns a producer's `incentive_balance_cents` to its pre-payment value."

        Design: Difficulty/compensating_invariant/incentive_balance_conserved_when_award_is_clawed_back
        """
        scenario = setup_enrolled_producer_with_head(
            premises_count=1, animals_per_premises=2, capacity=20, state_code="AZ"
        )
        producer_id = scenario["producer"]["id"]
        assert scenario["producer"]["lifetime_clawback_cents"] == 0

        award = accrue_award(producer_id, period_start="2026-07-01", period_end="2026-09-30")
        pay_award(award["id"])
        clawback_award(award["id"])

        producer_after = read_producer(producer_id)
        assert producer_after["lifetime_clawback_cents"] == 343
        assert producer_after["incentive_balance_cents"] == 0


class TestAwardLifecycleAndGates:
    def test_a_clawed_back_award_can_never_be_paid_again(self, api):
        """PRD §3.9: "Payment is available only from `ACCRUED` and again requires the owning producer to be `ENROLLED`, else `ERR_PRODUCER_NOT_ENROLLED`. The award moves `ACCRUED → PAID` and the producer's `incentive_balance_cents` increases by the award's `awarded_cents`."
        PRD §3.9: "Lifetime clawbacks only ever accumulate; the figure never decreases. Consistent with that, a producer's `incentive_balance_cents` is always the sum of `awarded_cents` across its `PAID` awards less the sum of `clawback_cents` across its `CLAWED_BACK` awards. `CLAWED_BACK` is terminal."
        PRD §2.5: "A tag lot whose status was forced by an external event — `RECALLED` or `VOIDED` — cannot supply an application and yields `ERR_LOT_NOT_ISSUABLE`; a `DEPLETED` lot is instead treated as a capacity failure and is handled in band 16; every other invalid transition yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/clawed_back_award_cannot_be_paid_again
        """
        scenario = setup_enrolled_producer_with_head(
            premises_count=1, animals_per_premises=2, capacity=10, state_code="AZ",
            legal_name="Terminal Ranch",
        )
        producer_id = scenario["producer"]["id"]
        award = accrue_award(producer_id, period_start="2026-07-01", period_end="2026-09-30")
        pay_award(award["id"])
        clawback_award(award["id"])

        resp = api.pay_incentive_award(award["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        rows, _meta = validate_paginated(api.list_producer_incentive_awards(producer_id, ADMIN))
        assert rows[0]["status"] == "CLAWED_BACK"
        assert read_producer(producer_id)["incentive_balance_cents"] == 0

    def test_enrolment_and_accrual_gates_reject_their_own_violations(self, api):
        """PRD §3.1: "Enrolment is the producer's own act and is self-service: the acting `X-User-ID` must be the producer being enrolled. A producer may enrol from `NOT_ENROLLED` or re-enrol from `LAPSED`, and either way at least one of its premises must currently be in `registration_status` `ACTIVE`, else the attempt is refused with `ERR_NO_ACTIVE_PREMISES`."
        PRD §3.9: "The producer's `enrollment_status` must be `ENROLLED` at that moment, else `ERR_PRODUCER_NOT_ENROLLED`; and at most one award in status `ACCRUED` or `PAID` may exist for a given producer and identical period pair, with a second refused as `ERR_AWARD_PERIOD_DUPLICATE`."

        Design: Corner/validations/enrollment_and_award_gates_reject_unenrolled_and_duplicate_periods
        """
        unenrolled = register_producer(legal_name="Gate A")
        register_premises(unenrolled["id"], capacity=10)

        enrolled = register_producer(legal_name="Gate B")
        create_active_premises(enrolled["id"], capacity=10)
        enroll_producer(enrolled["id"])
        first_award = accrue_award(
            enrolled["id"], period_start="2026-07-01", period_end="2026-09-30"
        )
        assert first_award["awarded_cents"] == 0, (
            "an enrolled producer with zero head sits in TIER_0 with a 0.00 factor"
        )

        no_active = api.enroll_producer(
            unenrolled["id"], make_producer_headers(unenrolled["id"])
        )
        validate_error(no_active, ApiErrorId.ERR_NO_ACTIVE_PREMISES, expected_status=409)

        not_enrolled = api.create_incentive_award(
            create_incentive_award_payload(
                unenrolled["id"], period_start="2026-07-01", period_end="2026-09-30"
            ),
            ADMIN,
        )
        validate_error(
            not_enrolled, ApiErrorId.ERR_PRODUCER_NOT_ENROLLED, expected_status=409
        )

        duplicate = api.create_incentive_award(
            create_incentive_award_payload(
                enrolled["id"], period_start="2026-07-01", period_end="2026-09-30"
            ),
            ADMIN,
        )
        validate_error(
            duplicate, ApiErrorId.ERR_AWARD_PERIOD_DUPLICATE, expected_status=409
        )

        assert read_producer(unenrolled["id"])["enrollment_status"] == "NOT_ENROLLED"
        _rows, meta = validate_paginated(
            api.list_producer_incentive_awards(enrolled["id"], ADMIN)
        )
        assert meta["total_count"] == 1
