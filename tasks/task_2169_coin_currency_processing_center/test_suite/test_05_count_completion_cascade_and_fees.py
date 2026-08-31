"""Completing the count: the per-bag fee, the materiality flag and the three cascade hops."""

from test_helpers import (
    ApiErrorId,
    TELLER_1,
    TELLER_2,
    assert_bag_settlement_identity,
    assert_count_session,
    assert_sealed_bag,
    complete_count_session_payload,
    complete_session,
    lot_entry,
    make_teller_headers,
    open_bag,
    read_bag,
    read_session,
    read_ticket,
    schedule_session,
    setup_two_counted_bags,
    setup_verified_ticket,
    start_session,
    validate_error,
    validate_paginated,
    validate_success,
)

# Bag S-3001 counts 100 notes: 250 + (100 * 35 / 1000) = 253.50 cents raw.
BAG_100_NOTES = {
    "declared_amount_cents": 100_000,
    "declared_note_count": 100,
    "counted_amount_cents": 100_000,
    "counted_note_count": 100,
}
# Bag S-3002 counts 300 notes: 250 + (300 * 35 / 1000) = 260.50 cents raw.
BAG_300_NOTES = {
    "declared_amount_cents": 110_000,
    "declared_note_count": 300,
    "counted_amount_cents": 110_000,
    "counted_note_count": 300,
    "lots": [lot_entry("FIT", 500, 200), lot_entry("UNFIT", 100, 100)],
}


class TestPerBagFeeRounding:
    def test_each_bag_fee_is_rounded_half_up_on_its_own(self, api):
        """PRD §3.4: "The **per-bag processing fee** starts from a base charge of 250 cents
        for handling any bag at all. To that is added a per-note charge: each counted note
        costs 35 millicents, which is thirty-five thousandths of one cent, so the note
        component is the bag's `counted_note_count` multiplied by 35 and then divided by
        1,000."
        PRD §3.4: "That raw figure is then rounded half up to a whole number of cents and
        stored as the bag's `processing_fee_cents`."
        PRD §2.7: "Wherever a computation must be reduced to a coarser unit, the rounding
        method is **round half up** — a value exactly at the midpoint rounds away from zero
        to the larger magnitude."

        Design: Difficulty/combinatorial_formula/per_bag_fee_rounded_half_up_before_summation
        """
        scenario = setup_two_counted_bags(BAG_100_NOTES, BAG_300_NOTES)
        first_bag, second_bag = scenario["bags"]

        assert_sealed_bag(first_bag)
        assert_sealed_bag(second_bag)
        assert first_bag["processing_fee_cents"] == 254, (
            "A raw fee of 253.50 rounds half up to 254, got "
            f"{first_bag['processing_fee_cents']}"
        )
        assert second_bag["processing_fee_cents"] == 261, (
            "A raw fee of 260.50 rounds half up to 261, got "
            f"{second_bag['processing_fee_cents']}"
        )

    def test_the_ticket_total_sums_the_already_rounded_per_bag_fees(self, api):
        """PRD §3.4: "The order matters and is not interchangeable: each bag is rounded on
        its own, **before** any summation. The ticket's `processing_fee_total_cents` is the
        exact integer sum of the already-rounded `processing_fee_cents` of every bag on
        that ticket whose counting axis reads `COUNTED` or `ADJUSTED`, and that sum is
        never re-rounded."
        PRD §3.4: "Rounding each bag first and summing afterwards can exceed the
        sum-then-round figure by one cent for every pair of bags whose raw fee lands exactly
        on a half-cent, and the per-bag order is the one this system uses."
        PRD §3.4: "Its `counted_total_cents` is recomputed as the sum of
        `settlement_amount_cents` over every bag on the ticket whose counting axis reads
        `COUNTED` or `ADJUSTED`, and its `processing_fee_total_cents` is recomputed as just
        described."

        Design: Difficulty/combinatorial_formula/per_bag_fee_rounded_half_up_before_summation
        """
        scenario = setup_two_counted_bags(BAG_100_NOTES, BAG_300_NOTES)
        ticket = scenario["ticket"]

        assert ticket["processing_fee_total_cents"] == 515, (
            "254 + 261 = 515; summing the raw 514.00 and rounding once would give 514. Got "
            f"{ticket['processing_fee_total_cents']}"
        )
        assert ticket["counted_total_cents"] == 210_000, (
            f"Expected counted_total_cents 210000, got {ticket['counted_total_cents']}"
        )
        assert ticket["status"] == "SETTLEMENT_READY", (
            f"Both bags are counted, so the ticket auto-advances; got {ticket['status']}"
        )

    def test_mixed_bag_fee_adds_the_coin_weight_rate_and_the_surcharge(self, api):
        """PRD §3.4: "To that is added a coin-weight charge of 180 cents per kilogram, where
        the kilogram figure is the bag's `counted_coin_weight_grams` divided by 1,000 and is
        *not* rounded before the multiplication. Finally, a mixed-handling surcharge of 125
        cents is added when and only when the bag's `bag_type` is `MIXED`; `CURRENCY` and
        `COIN` bags add nothing here."
        PRD §3.4: "That raw figure is then rounded half up to a whole number of cents and
        stored as the bag's `processing_fee_cents`."
        PRD §3.4: "The `materiality_flag` is set true when the absolute value of
        `variance_cents` is at least 2,500 cents — a twenty-five dollar swing in either
        direction — and false otherwise."

        Design: Corner/calculations/mixed_bag_fee_applies_surcharge_and_coin_weight_rate
        """
        scenario = setup_verified_ticket(
            bag_specs=[
                {
                    "bag_type": "MIXED",
                    "declared_amount_cents": 40_000,
                    "declared_note_count": 40,
                    "declared_coin_weight_grams": 4_500,
                }
            ],
            machine_type="MIXED_PROCESSOR",
        )
        bag = scenario["bag"]
        session = schedule_session(bag["id"], scenario["machine"]["id"])
        open_bag(bag["id"], bag["seal_number"])
        start_session(session["id"])

        complete_session(
            session["id"],
            counted_amount_cents=40_000,
            counted_note_count=40,
            lots=[lot_entry("FIT", 1000, 40)],
            counted_coin_weight_grams=4_500,
        )

        counted_bag = read_bag(bag["id"])
        assert counted_bag["processing_fee_cents"] == 1186, (
            "250 + 1.4 + 810 + 125 = 1186.40 rounds half up to 1186, got "
            f"{counted_bag['processing_fee_cents']}"
        )
        assert counted_bag["variance_cents"] == 0
        assert counted_bag["materiality_flag"] is False
        assert read_ticket(scenario["ticket"]["id"])["processing_fee_total_cents"] == 1186


class TestMaterialityBoundary:
    def test_variance_of_exactly_2500_flags_but_2499_does_not(self, api):
        """PRD §3.4: "The bag's `variance_cents` is computed as `counted_amount_cents` minus
        `declared_amount_cents` and is signed, so a short bag is negative and a long bag
        positive."
        PRD §3.4: "The `materiality_flag` is set true when the absolute value of
        `variance_cents` is at least 2,500 cents — a twenty-five dollar swing in either
        direction — and false otherwise."

        Design: Difficulty/boundary_precision_check/variance_materiality_flags_at_exactly_2500_but_not_at_2499
        """
        scenario = setup_two_counted_bags(
            {
                "declared_amount_cents": 102_500,
                "declared_note_count": 100,
                "counted_amount_cents": 100_000,
                "counted_note_count": 100,
            },
            {
                "declared_amount_cents": 102_499,
                "declared_note_count": 100,
                "counted_amount_cents": 100_000,
                "counted_note_count": 100,
            },
            tier="PREMIUM",
        )
        at_threshold, one_cent_below = scenario["bags"]

        assert at_threshold["variance_cents"] == -2500, (
            f"Expected variance -2500, got {at_threshold['variance_cents']}"
        )
        assert at_threshold["materiality_flag"] is True, (
            "An absolute variance of exactly 2500 is material"
        )
        assert one_cent_below["variance_cents"] == -2499, (
            f"Expected variance -2499, got {one_cent_below['variance_cents']}"
        )
        assert one_cent_below["materiality_flag"] is False, (
            "An absolute variance of 2499 is one cent short of material"
        )

    def test_only_the_flagged_bag_raises_the_open_variance_counter(self, api):
        """PRD §3.4: "If the bag that just finished was flagged material, the ticket's
        `material_variance_open_count` is incremented by 1; that counter tracks bags with
        `materiality_flag` true whose counting axis is still `COUNTED` — that is, neither
        adjusted by an approved claim nor released by a denied one."
        PRD §3.4: "Once no bag on the ticket remains outside `COUNTED` or `ADJUSTED`, the
        ticket moves itself to `SETTLEMENT_READY`."

        Design: Difficulty/boundary_precision_check/variance_materiality_flags_at_exactly_2500_but_not_at_2499
        """
        scenario = setup_two_counted_bags(
            {
                "declared_amount_cents": 102_500,
                "declared_note_count": 100,
                "counted_amount_cents": 100_000,
                "counted_note_count": 100,
            },
            {
                "declared_amount_cents": 102_499,
                "declared_note_count": 100,
                "counted_amount_cents": 100_000,
                "counted_note_count": 100,
            },
            tier="PREMIUM",
        )
        ticket = scenario["ticket"]

        assert ticket["material_variance_open_count"] == 1, (
            "Only the exactly-2500 bag is flagged, so the counter is 1, got "
            f"{ticket['material_variance_open_count']}"
        )
        assert ticket["status"] == "SETTLEMENT_READY", (
            f"Expected SETTLEMENT_READY once both bags are counted, got {ticket['status']}"
        )


class TestCountCompletionCascade:
    def test_completion_writes_the_session_and_the_bag(self, api):
        """PRD §3.4: "On success the session moves `IN_PROGRESS → COMPLETED`, records the
        acting `X-User-ID` as `verifier_user_id`, and stamps `completed_at` from the logical
        clock."
        PRD §3.4: "The bag's `settlement_amount_cents` is then recomputed as
        `counted_amount_cents` plus `claim_adjustment_cents` minus `seized_amount_cents`; at
        this point both of those latter fields are still 0, but the same three-term
        recomputation is re-run every time any one of them changes."
        PRD §3.4: "The bag's counting axis moves `COUNTING → COUNTED` and its `version`
        increments by 1."
        PRD §3.3: "Third, multiply the eligible declared total by one minus that haircut
        fraction — so `PREMIUM` keeps the whole amount, `STANDARD` keeps ninety-eight
        hundredths of it, and `WATCH` keeps ninety-five hundredths of it — and round the
        product half up to a whole number of cents."

        Design: Difficulty/transitive_cascade/count_completion_cascades_session_to_bag_to_ticket_auto_advance
        """
        scenario = setup_verified_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 102_500,
                    "declared_note_count": 100,
                    "declared_coin_weight_grams": 0,
                }
            ],
            tier="PREMIUM",
            credit_branch="provisional",
        )
        assert scenario["ticket"]["provisional_credit_cents"] == 102_500, (
            "A PREMIUM depositor takes no haircut, so the whole 102500 is advanced"
        )

        bag = scenario["bag"]
        session = schedule_session(bag["id"], scenario["machine"]["id"])
        open_bag(bag["id"], bag["seal_number"])
        start_session(session["id"], teller_user_id=TELLER_1)

        response = api.complete_count_session(
            session["id"],
            complete_count_session_payload(100_000, 100, [lot_entry("FIT", 1000, 100)], 0),
            make_teller_headers(TELLER_2),
        )
        completed = validate_success(response, 200)
        assert_count_session(completed)
        assert completed["status"] == "COMPLETED", f"Expected COMPLETED, got {completed['status']}"
        assert completed["verifier_user_id"] == TELLER_2, (
            "verifier_user_id must record the acting X-User-ID"
        )

        counted_bag = read_bag(bag["id"])
        assert counted_bag["count_status"] == "COUNTED"
        assert counted_bag["variance_cents"] == -2500
        assert counted_bag["materiality_flag"] is True
        assert counted_bag["processing_fee_cents"] == 254
        assert counted_bag["settlement_amount_cents"] == 100_000, (
            f"100000 + 0 - 0 = 100000, got {counted_bag['settlement_amount_cents']}"
        )
        assert_bag_settlement_identity(counted_bag)

    def test_completion_bubbles_up_and_auto_advances_the_ticket(self, api):
        """PRD §3.4: "The second cascade hop lands on the deposit ticket. Its
        `counted_total_cents` is recomputed as the sum of `settlement_amount_cents` over
        every bag on the ticket whose counting axis reads `COUNTED` or `ADJUSTED`, and its
        `processing_fee_total_cents` is recomputed as just described."
        PRD §3.4: "This auto-transition fires from whichever of the three pre-count states
        the ticket happens to be in — `VERIFIED → SETTLEMENT_READY`, `PROVISIONAL_CREDITED →
        SETTLEMENT_READY`, or `HELD → SETTLEMENT_READY` — and in all three cases the
        accompanying effect is the same recomputation of `counted_total_cents` and
        `processing_fee_total_cents`."
        PRD §3.4: "If the bag that just finished was flagged material, the ticket's
        `material_variance_open_count` is incremented by 1; that counter tracks bags with
        `materiality_flag` true whose counting axis is still `COUNTED` — that is, neither
        adjusted by an approved claim nor released by a denied one."

        Design: Difficulty/transitive_cascade/count_completion_cascades_session_to_bag_to_ticket_auto_advance
        """
        scenario = setup_verified_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 102_500,
                    "declared_note_count": 100,
                    "declared_coin_weight_grams": 0,
                }
            ],
            tier="PREMIUM",
            credit_branch="provisional",
        )
        bag = scenario["bag"]
        session = schedule_session(bag["id"], scenario["machine"]["id"])
        open_bag(bag["id"], bag["seal_number"])
        start_session(session["id"])
        complete_session(session["id"], 100_000, 100, [lot_entry("FIT", 1000, 100)])

        ticket = read_ticket(scenario["ticket"]["id"])
        assert ticket["counted_total_cents"] == 100_000, (
            f"Expected counted_total_cents 100000, got {ticket['counted_total_cents']}"
        )
        assert ticket["processing_fee_total_cents"] == 254, (
            f"Expected processing_fee_total_cents 254, got {ticket['processing_fee_total_cents']}"
        )
        assert ticket["material_variance_open_count"] == 1, (
            f"The flagged bag raises the counter to 1, got {ticket['material_variance_open_count']}"
        )
        assert ticket["status"] == "SETTLEMENT_READY", (
            "The ticket auto-advances PROVISIONAL_CREDITED -> SETTLEMENT_READY, got "
            f"{ticket['status']}"
        )


class TestLotReconciliation:
    def test_a_breakdown_that_does_not_reconcile_is_refused(self, api):
        """PRD §3.4: "The breakdown must reconcile with the totals in two ways at once: the
        sum over all lot entries of `denomination_cents` multiplied by `note_count` must
        equal the reported `counted_amount_cents`, and the sum of `note_count` across all lot
        entries must equal the reported `counted_note_count`. Either failure is
        `ERR_LOT_TOTAL_MISMATCH`."
        PRD §3.4: "One **fitness lot** is created per entry in `lots`, each carrying its
        `count_session_id`, its `category`, its `denomination_cents` and `note_count`, a
        computed `face_value_cents` equal to `denomination_cents` multiplied by `note_count`,
        and a null `fed_deposit_id`."

        Design: Corner/validations/lot_breakdown_that_does_not_reconcile_is_rejected_on_complete
        """
        scenario = setup_verified_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 100_000,
                    "declared_note_count": 100,
                    "declared_coin_weight_grams": 0,
                }
            ]
        )
        bag = scenario["bag"]
        session = schedule_session(bag["id"], scenario["machine"]["id"])
        open_bag(bag["id"], bag["seal_number"])
        start_session(session["id"])

        response = api.complete_count_session(
            session["id"],
            complete_count_session_payload(100_000, 90, [lot_entry("FIT", 1000, 90)], 0),
            make_teller_headers(TELLER_2),
        )
        validate_error(response, ApiErrorId.ERR_LOT_TOTAL_MISMATCH.value)
        assert response.status_code == 422

        assert read_session(session["id"])["status"] == "IN_PROGRESS", (
            "A refused completion leaves the session IN_PROGRESS"
        )
        assert read_bag(bag["id"])["count_status"] == "COUNTING", (
            "A refused completion leaves the counting axis at COUNTING"
        )
        _, meta = validate_paginated(
            api.list_session_fitness_lots(session["id"], make_teller_headers(TELLER_1))
        )
        assert meta["total_count"] == 0, (
            f"No FitnessLot may be created by a refused completion, got {meta['total_count']}"
        )
