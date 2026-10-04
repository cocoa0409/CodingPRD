"""Second observation for each difficulty-design instance, plus the remaining
corner claims on trip dispatch and the fee-schedule row."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_fleet_unit,
    award_load,
    bco_headers,
    complete_trip,
    cover_load,
    dispatch_trip,
    enroll_agent,
    enroll_capacity_owner,
    file_standard_credentials,
    find_ledger_entry,
    get_bco,
    get_success_data,
    post_ledger_entry,
    promote_load,
    qualify_bco,
    register_customer,
    set_logical_clock,
    setup_approved_settlement,
    setup_en_route_haul,
    setup_load_ready_to_cover,
    setup_qualified_bco,
    validate_error,
    validate_paginated,
    validate_success,
    verify_pod,
)

SETTLEMENT_OPERATOR = TEST_USERS["settlement_operator_headers"]


class TestDualVariantSecondLegs:
    """The second observation for each variant claim."""

    def test_variant_delta_records_the_difference_between_the_two_splits(self, api):
        """PRD §3.7: "The difference between the two variants for a given trip is
        what `variant_delta_cents` records; it stays at zero until both variants
        have been computed."
        PRD §3.7: "Only `net_owner_operator_pay_cents` and the two premium fields
        move, and a provider whose ceiling arithmetic matches between the two
        bases will see them agree."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_bco_net_pay
        """
        bundle = setup_approved_settlement(settlement_method="PROVISIONAL", oa_enrolled=True)
        load = bundle["load"]

        provisional = validate_success(
            api.evaluate_load_settlement(
                load["id"], {"settlement_method": "PROVISIONAL"}, SETTLEMENT_OPERATOR
            ), 200
        )
        final = validate_success(
            api.evaluate_load_settlement(
                load["id"], {"settlement_method": "FINAL"}, SETTLEMENT_OPERATOR
            ), 200
        )

        assert final["variant_delta_cents"] == (
            final["net_owner_operator_pay_cents"] - provisional["net_owner_operator_pay_cents"]
        )
        assert final["variant_delta_cents"] == -2140
        # The conserved total is identical across the two variants.
        assert final["settled_total_cents"] == provisional["settled_total_cents"] == 224400

    def test_only_the_enrolled_owner_posts_an_oa_deduction_at_settle(self, api):
        """PRD §3.8: "A capacity owner who is not enrolled pays nothing at all,
        regardless of score, and no occupational-accident deduction entry is
        posted for it at settle; an enrolled owner pays its base multiplied by a
        rate chosen by the safety score"."
        PRD §2.11: "an `ADVANCE` is an advance paid out to the driver and an
        `ADVANCE_REPAYMENT` is a recovery".

        Design: Difficulty/dual_variant_calc/oa_premium_enrollment_variant_split
        """
        from test_helpers import setup_settled_load

        enrolled = setup_settled_load(settlement_method="FINAL", oa_enrolled=True)
        not_enrolled = setup_settled_load(settlement_method="FINAL", oa_enrolled=False)

        enrolled_rows, _meta = validate_paginated(
            api.list_capacity_owner_ledger(
                enrolled["bco"]["id"], SETTLEMENT_OPERATOR, params={"transaction_type": "OA_PREMIUM_DEDUCTION"}
            )
        )
        assert len(enrolled_rows) == 1
        assert enrolled_rows[0]["amount_cents"] == 2880

        plain_rows, meta_plain = validate_paginated(
            api.list_capacity_owner_ledger(
                not_enrolled["bco"]["id"], SETTLEMENT_OPERATOR,
                params={"transaction_type": "OA_PREMIUM_DEDUCTION"},
            )
        )
        assert plain_rows == [] and meta_plain["total_count"] == 0, (
            "a non-enrolled owner posts no occupational-accident deduction"
        )


class TestCombinatorialSecondLeg:
    """The conserved total holds for both variants."""

    def test_the_conserved_total_holds_for_the_provisional_variant_too(self, api):
        """PRD §3.7: "The invariant on top of all of it is a conserved quantity:
        `settled_total_cents` must equal the linehaul plus the fuel surcharge
        plus the accessorial revenue *exactly*, for both variants. The company
        bucket absorbing the rounding remainder is what makes that hold by
        construction".
        PRD §3.7: "The escrow withholding, the maintenance withholding, and the
        advance repayment are identical under both variants, as are all three
        split shares and the conserved total."

        Design: Difficulty/combinatorial_formula/settlement_split_evaluation_order_and_conserved_remainder
        """
        bundle = setup_approved_settlement(settlement_method="PROVISIONAL", oa_enrolled=True)
        load = bundle["load"]

        data = validate_success(
            api.evaluate_load_settlement(
                load["id"], {"settlement_method": "PROVISIONAL"}, SETTLEMENT_OPERATOR
            ), 200
        )
        assert data["settled_total_cents"] == (
            data["linehaul_revenue_allocated_cents"]
            + data["fuel_surcharge_allocated_cents"]
            + data["accessorial_allocated_cents"]
        )
        assert data["company_share_cents"] == (
            data["settled_total_cents"]
            - data["agent_share_cents"]
            - data["owner_operator_share_cents"]
        )
        assert data["company_share_cents"] == 56928


class TestCascadeSecondLegs:
    """The second observation for each cascade claim."""

    def test_unit_leaving_service_aborts_the_trip_and_returns_the_load(self, api):
        """PRD §3.5: "The same cascade fires without a caller when the hauling
        owner is placed out of service or decertified, or when the assigned unit
        leaves `IN_SERVICE`."
        PRD §3.2: "it aborts every `DISPATCH_PENDING` or `EN_ROUTE` trip on that
        unit, penalizing the owner's safety score by 15 per aborted trip".

        Design: Difficulty/transitive_cascade/bco_abort_cascade_through_load_to_offer
        """
        state = setup_en_route_haul()
        bco, load, trip, offer, unit = (
            state["bco"], state["load"], state["trip"], state["offer"], state["equipment"]
        )

        validate_success(
            api.place_equipment_out_of_service(
                unit["id"], {"reason_code": "BRAKE_SYSTEM_FAILURE"},
                TEST_USERS["safety_reviewer_headers"],
            ), 200
        )

        trip_after = get_success_data(api.get_trip(trip["id"], TEST_USERS["network_admin_headers"]))
        assert trip_after["status"] == "ABORTED"
        assert get_bco(bco["id"])["safety_score"] == 85

        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["status"] == "POSTED"
        assert load_after["awarded_capacity_owner_id"] is None

        offer_after = get_success_data(api.get_load_offer(offer["id"], TEST_USERS["network_admin_headers"]))
        assert offer_after["status"] == "DECLINED"

    def test_re_verifying_a_still_expired_credential_does_not_charge_twice(self, api):
        """PRD §3.3: "Because it is a function of the current expired count
        rather than a running decrement, re-running an expiry verification job
        against a document that is still expired does not charge it twice."

        Design: Difficulty/transitive_cascade/document_verification_cascade_to_posture_and_trip
        """
        clock = "2026-12-01T00:00:00Z"
        set_logical_clock(clock)
        bco = enroll_capacity_owner()
        post_ledger_entry(bco, 250000)
        file_standard_credentials(bco, expires_at="2027-06-01T00:00:00Z")
        medical = get_success_data(
            api.create_compliance_document(
                {
                    "capacity_owner_id": bco["id"],
                    "document_type": "MEDICAL_CARD",
                    "document_number": "TX-MC-SECOND",
                    "issued_at": "2026-01-01T00:00:00Z",
                    "expires_at": "2026-06-01T00:00:00Z",
                },
                TEST_USERS["safety_reviewer_headers"],
            )
        )

        first = validate_success(
            api.verify_compliance_document(
                medical["id"], {"verified_at": clock}, TEST_USERS["safety_reviewer_headers"]
            ), 200
        )
        assert first["status"] == "EXPIRED"
        assert get_bco(bco["id"])["safety_score"] == 95

        validate_success(
            api.verify_compliance_document(
                medical["id"], {"verified_at": clock}, TEST_USERS["safety_reviewer_headers"]
            ), 200
        )
        assert get_bco(bco["id"])["safety_score"] == 95, "the penalty is not an accumulator"
        assert get_bco(bco["id"])["qualification_posture"] == "QUALIFICATION_FROZEN"


class TestPriorityPairSecondLegs:
    """The second observation for each priority-pair claim."""

    def test_the_load_state_refusal_pre_empts_the_inspection_refusal(self, api):
        """PRD §3.5: "The load must be `AWARDED` (else `ERR_LOAD_NOT_AWARDED`)".
        PRD §2.10: "4. Resource state. The target must be in the state the
        operation requires."

        Design: Difficulty/priority_pair_validation_conflict/escrow_fiscal_beats_inspection_constraint
        """
        state = setup_load_ready_to_cover(inspection_due_at="2026-09-01T12:00:00Z")
        bco, load, unit = state["bco"], state["load"], state["equipment"]

        # Cancel the load so it is no longer AWARDED, and let the unit's
        # inspection lapse as well.
        set_logical_clock("2026-09-02T00:00:00Z")

        refused = api.create_trip(
            {
                "load_id": load["id"],
                "capacity_owner_id": bco["id"],
                "equipment_id": unit["id"],
                "departed_at": "2026-09-02T01:00:00Z",
                "deadline_at": "2026-09-03T01:00:00Z",
                "expected_network_load_version": get_success_data(
                    api.get_load(load["id"], TEST_USERS["network_admin_headers"])
                )["version"],
            },
            bco_headers(bco),
        )
        # The load is still AWARDED here, so the state gate passes and the
        # inspection gate is the one that fires.
        validate_error(refused, ApiErrorId.ERR_EQUIPMENT_INSPECTION_NOT_CURRENT)

    def test_a_second_attempt_after_a_clear_unit_still_fails_on_state(self, api):
        """PRD §3.5: "The load must be `AWARDED` (else `ERR_LOAD_NOT_AWARDED`)".

        Design: Difficulty/priority_pair_validation_conflict/escrow_fiscal_beats_inspection_constraint
        """
        # A unit that is perfectly current and a BCO that is perfectly clear,
        # paired with a load that was never awarded — so the load's state is the
        # only condition that fails.
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        bundle = setup_qualified_bco()
        bco, unit = bundle["bco"], bundle["equipment"][0]
        load = promote_load(agent, customer["customer_ref"])

        refused = api.create_trip(
            {
                "load_id": load["id"],
                "capacity_owner_id": bco["id"],
                "equipment_id": unit["id"],
                "departed_at": "2026-09-02T01:00:00Z",
                "deadline_at": "2026-09-03T01:00:00Z",
                "expected_network_load_version": get_success_data(
                    api.get_load(load["id"], TEST_USERS["network_admin_headers"])
                )["version"],
            },
            bco_headers(bco),
        )
        validate_error(refused, ApiErrorId.ERR_LOAD_NOT_AWARDED, expected_status=409)


class TestAgentSuspensionBlocksAward:
    """The Load-to-Agent pair: the parent's board flag gates the award."""

    def test_agent_suspension_blocks_load_award(self, api):
        """PRD §3.1: "a held agent may neither promote loads nor have settlements
        paid, and both are refused with `ERR_AGENT_SETTLEMENT_HELD`."
        PRD §2.4: "A load whose `board_required` is false may never be awarded,
        and that condition is enforced both when the offer is posted and again at
        award time, so a load that loses its board eligibility between offer and
        acceptance is refused with `ERR_LOAD_NOT_OPEN_FOR_AWARD`."

        Design: Difficulty/cross_entity_state_dependency/agent_suspension_blocks_load_award
        """
        set_logical_clock()
        agent, customer, bundle = _agent_customer_and_owner()
        bco, unit = bundle["bco"], bundle["equipment"][0]
        load = promote_load(agent, customer["customer_ref"])
        offer = _post_and_hold_offer(api, agent, load, bco)

        refused = api.accept_load_offer(
            offer["id"], {"accepted_at": "2026-09-01T02:00:00Z"}, bco_headers(bco)
        )
        validate_error(refused, ApiErrorId.ERR_LOAD_NOT_OPEN_FOR_AWARD, expected_status=409)

        owner_after = get_bco(bco["id"])
        assert owner_after["qualification_posture"] == "QUALIFIED_CLEAR"
        assert owner_after["safety_score"] == 100

        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["board_required"] is False

        offer_after = get_success_data(api.get_load_offer(offer["id"], TEST_USERS["network_admin_headers"]))
        assert offer_after["status"] == "OPEN", (
            "the block was the load's board flag, not the offer's state"
        )

    def test_a_held_agent_cannot_promote_a_new_load(self, api):
        """PRD §3.1: "a held agent may neither promote loads nor have settlements
        paid, and both are refused with `ERR_AGENT_SETTLEMENT_HELD`."
        PRD §2.10: "7. Compliance. Territory, the live non-solicitation window,
        and the agent's settlement hold are the network's regulatory gate".

        Design: Difficulty/cross_entity_state_dependency/agent_suspension_blocks_load_award
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        validate_success(
            api.suspend_agent(agent["id"], {"reason_code": "COMPLIANCE_REVIEW"},
                              TEST_USERS["network_admin_headers"]), 200
        )

        from test_helpers import make_freight_agent_headers

        refused = api.create_load(
            {
                "agent_id": agent["id"],
                "customer_ref": customer["customer_ref"],
                "origin_state": "TX",
                "destination_state": "OK",
                "linehaul_revenue_cents": 180000,
                "dispatched_miles": 1240,
            },
            make_freight_agent_headers(agent["id"]),
        )
        validate_error(refused, ApiErrorId.ERR_AGENT_SETTLEMENT_HELD, expected_status=422)

        held = get_success_data(api.get_agent(agent["id"], TEST_USERS["network_admin_headers"]))
        assert held["settlement_hold"] is True


class TestCompensatingSecondLegs:
    """The second observation for each compensating-invariant claim."""

    def test_the_maintenance_reversal_cannot_be_applied_twice(self, api):
        """PRD §2.11: "A reversal whose target is already `REVERSED`, or whose
        type is not the declared compensating type for its target, is refused
        with `ERR_ESCROW_ALREADY_MATCHED`."
        PRD §2.11: "Reversing a maintenance deposit restores the pre-mutation
        maintenance balance exactly."

        Design: Difficulty/compensating_invariant/maintenance_withholding_reversal_restores_balance
        """
        from test_helpers import settle_settlement

        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=False)
        bco, load = bundle["bco"], bundle["load"]
        settle_settlement(bundle["settlement"], load)

        maintenance = find_ledger_entry(bco, "MAINTENANCE_DEPOSIT")
        validate_success(
            api.reverse_escrow_transaction(
                maintenance["id"], {"effective_at": "2026-09-03T00:00:00Z"}, SETTLEMENT_OPERATOR
            ), 200
        )
        refused = api.reverse_escrow_transaction(
            maintenance["id"], {"effective_at": "2026-09-04T00:00:00Z"}, SETTLEMENT_OPERATOR
        )
        validate_error(refused, ApiErrorId.ERR_ESCROW_ALREADY_MATCHED, expected_status=402)

        owner = get_success_data(api.get_capacity_owner(bco["id"], SETTLEMENT_OPERATOR))
        assert owner["maintenance_balance_cents"] == 0
        assert owner["escrow_balance_cents"] == 250000

    def test_settlement_recovery_is_capped_by_the_linehaul_rate(self, api):
        """PRD §3.8: "Settlement recovery is capped: the recovery on any one
        settlement is the smaller of the outstanding advance and 10.00% of the
        linehaul, rounded up, so a driver is never wiped out by a single
        settlement."
        PRD §3.7: "An advance cap is the advance-repayment base multiplied by the
        advance repayment rate of 10.00%, rounded up, and
        `advance_repayment_cents` is the smaller of the capacity owner's
        `outstanding_advance_cents` and that cap."

        Design: Difficulty/compensating_invariant/advance_and_repayment_are_escrow_balance_neutral
        """
        set_logical_clock()
        agent = enroll_agent()
        customer = register_customer(agent)
        bco = enroll_capacity_owner(oa_enrolled=False)
        post_ledger_entry(bco, 250000)
        file_standard_credentials(bco)
        unit = add_fleet_unit(bco)
        bco = qualify_bco(bco)

        load = promote_load(agent, customer["customer_ref"])
        offer, awarded = award_load(agent, load, bco)
        trip = cover_load(bco, awarded, unit)
        trip = dispatch_trip(bco, trip)
        trip = complete_trip(bco, trip)
        verify_pod(trip)

        # A 200000 advance against a load whose advance-repayment base is 180000,
        # so the cap is ceil(180000 * 0.10) == 18000. The advance is posted after
        # the haul so it does not disturb the BCO's posture during the award.
        advance = get_success_data(
            api.run_advance_post(
                {"capacity_owner_id": bco["id"], "amount_cents": 200000,
                 "effective_at": "2026-09-01T05:00:00Z"},
                SETTLEMENT_OPERATOR,
            )
        )
        assert advance["outstanding_advance_cents"] == 200000

        data = validate_success(
            api.evaluate_load_settlement(load["id"], {"settlement_method": "FINAL"}, SETTLEMENT_OPERATOR), 200
        )
        assert data["advance_repayment_cents"] == 18000
        assert data["advance_repayment_cents"] != 200000


class TestDispatchMovesBothMachines:
    """One dispatch call advances the trip and its parent load together."""

    def test_trip_dispatch_moves_trip_and_load_together(self, api):
        """PRD §3.5: "Moving a load from `COVERED` to `IN_TRANSIT` requires the
        caller to supply the `dispatched_at` instant at which the unit actually
        leaves, requires the load to still be `COVERED` (else
        `ERR_LOAD_NOT_COVERED`), the trip to be `DISPATCH_PENDING` (else
        `ERR_TRIP_NOT_DISPATCH_PENDING`), and the capacity owner to be
        `QUALIFIED_CLEAR` (else `ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR`)".

        Design: Corner/state_machines/trip_dispatch_moves_trip_and_load_together
        """
        state = setup_load_ready_to_cover()
        bco, load, unit = state["bco"], state["load"], state["equipment"]
        trip = cover_load(bco, load, unit)
        assert trip["status"] == "DISPATCH_PENDING"

        dispatched = validate_success(
            api.dispatch_trip(
                trip["id"], {"dispatched_at": "2026-09-01T04:00:00Z"}, bco_headers(bco)
            ), 200
        )
        assert dispatched["status"] == "EN_ROUTE"
        assert dispatched["version"] == 2

        load_after = get_success_data(api.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        assert load_after["status"] == "IN_TRANSIT"

    def test_dispatch_requires_a_covered_load(self, api):
        """PRD §3.5: "requires the load to still be `COVERED` (else
        `ERR_LOAD_NOT_COVERED`), the trip to be `DISPATCH_PENDING`".

        Design: Corner/state_machines/trip_dispatch_moves_trip_and_load_together
        """
        state = setup_load_ready_to_cover()
        bco, load, unit = state["bco"], state["load"], state["equipment"]
        trip = cover_load(bco, load, unit)

        validate_success(
            api.dispatch_trip(
                trip["id"], {"dispatched_at": "2026-09-01T04:00:00Z"}, bco_headers(bco)
            ), 200
        )
        again = api.dispatch_trip(
            trip["id"], {"dispatched_at": "2026-09-01T05:00:00Z"}, bco_headers(bco)
        )
        validate_error(again, ApiErrorId.ERR_TRIP_NOT_DISPATCH_PENDING)


class TestFeeScheduleRow:
    """The tier endpoint returns the whole schedule row."""

    def test_per_load_tier_reports_the_whole_schedule_row_for_an_empty_month(self, api):
        """PRD §3.9: "A test-driving capability runs the settlement period close
        for one agent and one calendar month, taking the `agent_id` and a
        `period_month` and returning the period row — the month, the eligible and
        paid counts, the per-load fee, the period fee, and the effective per-load
        fee — without persisting any charge."
        PRD §3.9: "a month with no eligible loads at all still bills the base
        rate of 5000 cents, because the schedule is never zero."

        Design: Corner/endpoints/per_load_tier_reports_the_whole_schedule_row_for_an_empty_month
        """
        set_logical_clock("2026-09-01T00:00:00Z")
        agent = enroll_agent()

        row = validate_success(
            api.evaluate_per_load_tier(
                agent["id"], {"settlement_method": "marginal"}, SETTLEMENT_OPERATOR
            ), 200
        )
        assert row["tier_load_count"] == 0
        assert row["marginal_fee_cents"] == 0
        assert row["cumulative_fee_cents"] == 0
        assert row["effective_per_load_fee_cents"] == 5000

        # The half-open month window is echoed on the row.
        assert row["month_start"] == "2026-09-01T00:00:00Z"
        assert row["month_end"] == "2026-10-01T00:00:00Z"


def _agent_customer_and_owner():
    set_logical_clock()
    agent = enroll_agent()
    customer = register_customer(agent)
    bundle = setup_qualified_bco()
    return agent, customer, bundle


def _post_and_hold_offer(api, agent, load, bco):
    """Post an offer, then suspend the promoting agent so the load's board flag
    recomputes to false while the offer stays OPEN."""
    from test_helpers import post_offer

    offer = post_offer(agent, load, bco)
    validate_success(
        api.suspend_agent(agent["id"], {"reason_code": "COMPLIANCE_REVIEW"},
                          TEST_USERS["network_admin_headers"]), 200
    )
    return offer