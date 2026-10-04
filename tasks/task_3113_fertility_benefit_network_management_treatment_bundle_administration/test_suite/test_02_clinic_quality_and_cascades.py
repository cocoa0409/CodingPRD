"""Clinic-side evidence: outcome records, the derived quality readings, and the
cascades and compensations that ride on them."""
import pytest

from test_helpers import (
    CLAIMS,
    NETWORK,
    PHARMACIST,
    api_client,
    assert_clinic,
    assert_clinic_quality_invariants,
    assert_quality_composite,
    create_treatment_cycle_payload,
    create_preauthorization,
    create_cycle,
    drive_cycle_to_outcome_recorded,
    report_clinic_outcome,
    setup_clinic_with_live_birth_meeting_floor,
    setup_clinic_with_reported_workset,
    setup_recorded_outcome_cycle,
    setup_reported_outcome_cycle,
    validate_success,
)


class TestQualityWorksetSemantics:
    """The rate readings are recomputed from the live workset in place."""

    def test_amending_a_record_replaces_it_in_place(self):
        """PRD §3.3: "The quality readings themselves are computed from the clinic's live
        workset — the records whose `outcome_status` is `RECORDED` or `AMENDED`, each
        counted once regardless of which of those two it is."
        PRD §3.10: "An amendment rewrites the record in place rather than appending a
        correction beside it, so the clinic's workset recomputes at the new values and the
        rate readings move to the amended value rather than being averaged against the
        superseded one; an implementation that appends instead of replacing will drift
        away from the true rate a little further with every amendment."

        Design: Difficulty/dual_variant_calc/network_quality_amended_workset_divergence
        """
        scenario = setup_clinic_with_reported_workset(
            [{"live_birth": True, "births_count": 1, "multiple_birth": False,
              "gestational_weeks": 39}])
        clinic = scenario["clinic"]
        record = scenario["records"][0]
        assert clinic["cycles_reported"] == 1
        assert clinic["live_birth_rate_bps"] == 10000

        amended = validate_success(api_client.amend_outcome_record(
            record["id"],
            {"live_birth": False, "births_count": 0, "multiple_birth": False,
             "gestational_weeks": 39, "amendment_reason": "chart correction"},
            NETWORK), 200)
        assert amended["outcome_status"] == "AMENDED"

        after = validate_success(api_client.get_clinic(clinic["id"], NETWORK), 200)
        assert after["cycles_reported"] == 1, (
            "the amended record is counted once, not twice"
        )
        assert after["live_birth_rate_bps"] == 0, (
            "the rate moves to the amended value rather than averaging with the superseded one"
        )
        assert after["multiple_birth_rate_bps"] == 0

    def test_second_amendment_of_one_record_is_refused(self):
        """PRD §3.10: "A second amendment of the same record is refused with
        `ERR_DUPLICATE_OPERATION`, as is a second report for the same cycle."
        PRD §3.10: "the amendment is accepted only while the record is still `RECORDED`"

        Design: Difficulty/dual_variant_calc/network_quality_amended_workset_divergence
        """
        scenario = setup_clinic_with_reported_workset(
            [{"live_birth": False, "births_count": 0, "multiple_birth": False,
              "gestational_weeks": 0}])
        record = scenario["records"][0]
        amend_payload = {"live_birth": True, "births_count": 1, "multiple_birth": False,
                         "gestational_weeks": 38, "amendment_reason": "first correction"}
        first = validate_success(
            api_client.amend_outcome_record(record["id"], amend_payload, NETWORK), 200)
        assert first["outcome_status"] == "AMENDED"

        second = api_client.amend_outcome_record(
            record["id"],
            {"live_birth": False, "births_count": 0, "multiple_birth": False,
             "gestational_weeks": 38, "amendment_reason": "second correction"},
            NETWORK)

        assert second.status_code == 409
        assert second.json()["data"]["error_id"] == "ERR_DUPLICATE_OPERATION"


class TestOutcomeVoidCancels:
    """A void removes the record from both the numerator and the denominator."""

    def test_void_removes_the_record_from_rate_and_count(self):
        """PRD §3.10: "Voiding moves the record to `VOIDED`, which is terminal, and
        removes it from the clinic's workset entirely rather than merely flagging it,
        which is why voiding a record that was not a live birth raises the clinic's
        live-birth rate while voiding one that was a live birth lowers it — a removal
        from both numerator and denominator rather than from the numerator alone."

        Design: Difficulty/compensating_invariant/outcome_void_restores_conserved_record_count_and_rate_denominator
        """
        scenario = setup_clinic_with_reported_workset(
            [{"live_birth": True, "births_count": 1, "multiple_birth": False,
              "gestational_weeks": 38}])
        clinic = scenario["clinic"]
        record = scenario["records"][0]
        assert clinic["cycles_reported"] == 1
        assert clinic["live_birth_rate_bps"] == 10000

        voided = validate_success(api_client.void_outcome_record(
            record["id"], {"void_reason": "duplicate submission from the clinic feed"}, NETWORK), 200)

        assert voided["outcome_status"] == "VOIDED"
        assert voided["void_reason"] == "duplicate submission from the clinic feed"
        after = validate_success(api_client.get_clinic(clinic["id"], NETWORK), 200)
        assert after["cycles_reported"] == 0
        assert after["live_birth_rate_bps"] == 0
        assert after["multiple_birth_rate_bps"] == 0
        assert_clinic_quality_invariants(after)

    def test_voided_record_is_retained_rather_than_deleted(self):
        """PRD §3.10: "A voided record cannot be resurrected, and `void_reason` is
        populated only while a record sits in the `VOIDED` outcome state — the
        counterpart of `amendment_reason`, which is populated only while a record sits
        in `AMENDED`."

        Design: Difficulty/compensating_invariant/outcome_void_restores_conserved_record_count_and_rate_denominator
        """
        scenario = setup_clinic_with_reported_workset(
            [{"live_birth": True, "births_count": 1, "multiple_birth": False,
              "gestational_weeks": 38}])
        clinic = scenario["clinic"]
        record = scenario["records"][0]
        member_before = validate_success(
            api_client.get_member(record["member_id"], NETWORK), 200)
        assert member_before["live_births_recorded"] == 1

        validate_success(api_client.void_outcome_record(
            record["id"], {"void_reason": "voided for the conservation check"}, NETWORK), 200)

        data, meta = validate_paginated_outcome_records(clinic["id"])
        assert meta["total_count"] == 1, "the voided row is retained rather than deleted"
        assert data[0]["outcome_status"] == "VOIDED"

        voided_only, voided_meta = validate_paginated_voided(clinic["id"])
        assert voided_meta["total_count"] == 1
        assert voided_only[0]["id"] == record["id"]

        member_after = validate_success(
            api_client.get_member(member_before["id"], NETWORK), 200)
        assert member_after["live_births_recorded"] == 0, (
            "a voided record is treated as if it had never existed"
        )


def validate_paginated_outcome_records(clinic_id: str):
    from test_helpers import validate_paginated
    return validate_paginated(api_client.list_outcome_records(NETWORK, {"clinic_id": clinic_id}))


def validate_paginated_voided(clinic_id: str):
    from test_helpers import validate_paginated
    return validate_paginated(api_client.list_outcome_records(
        NETWORK, {"clinic_id": clinic_id, "outcome_status": "VOIDED"}))


class TestQualityBreachCascade:
    """A single clinic-side report walks three causally chained hops."""

    def test_report_that_breaches_the_floor_cascades_clinic_contract_plan_auth(self):
        """PRD §3.3: "A clinic in `CONTRACTED` posture whose workset has reached the
        maturity threshold and whose live-birth rate has fallen below the floor or whose
        multiple-birth rate has risen above the ceiling is moved to `PROBATION`, and
        every contract the clinic holds that was `ACTIVE` is frozen with `frozen_reason`
        `QUALITY_BREACH`."
        PRD §3.4: "Whenever a plan's selected clinic stops being `CONTRACTED`, the plan
        is moved into `PLANNING_REVISION` with `plan_blocked_reason` reading
        `CLINIC_NOT_CONTRACTED`."

        Design: Difficulty/transitive_cascade/quality_breach_cascade_three_hop_clinic_to_contract_to_plan_to_auth
        """
        scenario = build_quality_breach_scenario()
        clinic = scenario["clinic"]
        contract = scenario["contract"]
        plan = scenario["target_plan"]
        target_auth = scenario["target_preauthorization"]

        assert clinic["cycles_reported"] == 2
        assert clinic["live_birth_rate_bps"] == 5000, "below the 6000 floor"

        # hop 1 — the clinic's posture
        clinic_after = validate_success(api_client.get_clinic(clinic["id"], NETWORK), 200)
        assert clinic_after["clinic_status"] == "PROBATION"

        # hop 2 — the contract is frozen as a consequence of hop 1
        contract_after = validate_success(
            api_client.get_clinic_contract(contract["id"], NETWORK), 200)
        assert contract_after["contracting_status"] == "FROZEN"
        assert contract_after["frozen_reason"] == "QUALITY_BREACH"

        # hop 3 — the dependent plan is blocked
        plan_after = validate_success(
            api_client.get_treatment_plan(plan["id"], NETWORK), 200)
        assert plan_after["plan_status"] == "PLANNING_REVISION"
        assert plan_after["plan_blocked_reason"] == "CLINIC_NOT_CONTRACTED"

        auth_after = validate_success(
            api_client.get_preauthorization(target_auth["id"], CLAIMS), 200)
        assert auth_after["review_status"] == "DENIED"
        assert auth_after["denial_reason_code"] == "CLINIC_NOT_CONTRACTED"

    def test_quality_breach_hop_three_leaves_the_breaching_clinics_own_plans_consumed(self):
        """PRD §3.6: "That single act is the point at which the cycle consumes its
        bundle slot: the cycle's `consumption_marker` becomes `CONSUMED`"
        PRD §3.6: "the plan's `cycles_completed` is recomputed with the plan moving to
        `COMPLETED` once `cycles_completed` has reached `planned_cycles`."

        Design: Difficulty/transitive_cascade/quality_breach_cascade_three_hop_clinic_to_contract_to_plan_to_auth
        """
        scenario = build_quality_breach_scenario()
        breaching_cycle = scenario["breaching_cycle"]
        reported_cycle = scenario["reported_cycle"]

        cycle_after = validate_success(
            api_client.get_treatment_cycle(breaching_cycle["id"], NETWORK), 200)
        assert cycle_after["cycle_status"] == "OUTCOME_RECORDED"
        assert cycle_after["consumption_marker"] == "CONSUMED"

        healthy_plan = validate_success(
            api_client.get_treatment_plan(scenario["healthy_plan"]["id"], NETWORK), 200)
        assert healthy_plan["cycles_completed"] == 1
        assert healthy_plan["plan_status"] == "COMPLETED"

        reported_after = validate_success(
            api_client.get_treatment_cycle(reported_cycle["id"], NETWORK), 200)
        assert reported_after["cycle_status"] == "OUTCOME_RECORDED"


def build_quality_breach_scenario() -> dict:
    """A CONTRACTED clinic one quality report away from breaching its live-birth floor,
    a second plan committed to it with an authorization under review, and the cycle
    whose report trips the breach."""
    from test_helpers import (
        REVIEWER_ID, REVIEWER_2_ID, NEUTRAL_CRITERIA, create_advocate, create_bundle,
        create_clinic, create_contract, create_cycle, create_employer, create_member,
        create_plan, create_preauthorization, approve_preauthorization,
        drive_cycle_to_outcome_recorded, report_clinic_outcome, select_clinic_for_plan,
        setup_clock, make_clinical_reviewer_headers,
    )

    setup_clock()
    employer = create_employer(allocation_method="CONCURRENT_BUNDLE")
    bundle = create_bundle(
        employer["id"],
        lifetime_max_cycles=6, max_cycles_per_year=6, max_multiple_birth_rate_bps=None,
        pharmacy_pool_cents=1000000)
    advocate = create_advocate(caseload_limit=8)
    clinic, contract = create_contract_and_clinic(rate=1450000)

    # Plan one: a live-birth record that keeps the clinic inside its floor.
    member_one = create_member(employer["id"], advocate=advocate,
                               member_overrides={"external_ref": "CASCADE-1"})
    plan_one = select_clinic_for_plan(create_plan(member_one, bundle, advocate, planned_cycles=1),
                                      clinic, advocate)
    auth_one = approve_preauthorization(
        create_preauthorization(plan_one, advocate, 1, criteria_inputs=NEUTRAL_CRITERIA),
        plan_one, reviewer_id=REVIEWER_ID)
    cycle_one = create_cycle(plan_one, auth_one, clinic,
                             retrieval_date="2026-09-04T00:00:00Z",
                             transfer_date="2026-09-06T00:00:00Z")
    cycle_one = drive_cycle_to_outcome_recorded(
        cycle_one, clinic, at_clock="2026-09-26T00:00:00Z",
        transfer_date="2026-09-06T00:00:00Z",
        outcome={"live_birth": True, "births_count": 1, "multiple_birth": False,
                 "gestational_weeks": 38})
    reported = report_clinic_outcome(clinic, cycle_one, live_birth=True, births_count=1,
                                     multiple_birth=False, gestational_weeks=38)
    assert reported["outcome_status"] == "RECORDED"

    # Plan two: the breaching cycle, whose report drives the rate below the floor.
    # The clock is returned to its start first: the authorization's validity window
    # opens at the instant of approval, so a back-dated retrieval date only falls
    # inside it when the approval itself is taken at the early instant.
    setup_clock()
    member_two = create_member(employer["id"], advocate=advocate,
                               member_overrides={"external_ref": "CASCADE-2"})
    plan_two = select_clinic_for_plan(create_plan(member_two, bundle, advocate, planned_cycles=2),
                                      clinic, advocate)
    auth_two = approve_preauthorization(
        create_preauthorization(plan_two, advocate, 1, criteria_inputs=NEUTRAL_CRITERIA),
        plan_two, reviewer_id=REVIEWER_ID)
    cycle_two = create_cycle(plan_two, auth_two, clinic,
                             retrieval_date="2026-09-04T00:00:00Z",
                             transfer_date="2026-09-06T00:00:00Z")
    cycle_two = drive_cycle_to_outcome_recorded(
        cycle_two, clinic, at_clock="2026-09-26T00:00:00Z",
        transfer_date="2026-09-06T00:00:00Z",
        outcome={"live_birth": False, "births_count": 0, "multiple_birth": False,
                 "gestational_weeks": 0})

    # Plan three: the hop-three target, its authorization sitting in clinical review.
    member_three = create_member(employer["id"], advocate=advocate,
                                 member_overrides={"external_ref": "CASCADE-3"})
    plan_three = select_clinic_for_plan(create_plan(member_three, bundle, advocate, planned_cycles=1),
                                        clinic, advocate)
    auth_three = create_preauthorization(plan_three, advocate, 1, criteria_inputs=NEUTRAL_CRITERIA)
    validate_success(api_client.begin_clinical_review(
        auth_three["id"], make_clinical_reviewer_headers(REVIEWER_2_ID)), 200)

    # The trigger: reporting the second cycle's outcome breaches the floor.
    report_clinic_outcome(clinic, cycle_two, live_birth=False, births_count=0,
                          multiple_birth=False, gestational_weeks=0)

    return {
        "employer": employer,
        "bundle": bundle,
        "advocate": advocate,
        "clinic": validate_success(api_client.get_clinic(clinic["id"], NETWORK), 200),
        "contract": contract,
        "reported_cycle": cycle_one,
        "breaching_cycle": cycle_two,
        "healthy_plan": plan_one,
        "target_plan": plan_three,
        "target_preauthorization": auth_three,
    }


def create_contract_and_clinic(rate: int):
    """A CONTRACTED clinic whose live-birth floor sits at 6000 with a maturity
    threshold of one report."""
    from test_helpers import create_clinic, create_contract
    clinic = create_clinic(min_live_birth_rate_bps=6000, maturity_report_threshold=1,
                           required_quality_report_count=0)
    contract = create_contract(clinic, bundle_rates={"IVF_RETRIEVAL_TRANSFER": rate})
    return clinic, contract


class TestClinicQualityReadings:
    """The published readings follow the workset and the composite formula."""

    def test_empty_workset_reads_zero_rather_than_failing(self):
        """PRD §3.3: "The `live_birth_rate_bps` reading is ten thousand times the number
        of live-birth records divided by the workset size, rounded half-up to a whole
        number of basis points, and it reads zero when the workset is empty rather than
        failing."

        Design: Corner/entities/clinic_quality_readings_computed_with_client_values_ignored_input
        """
        from test_helpers import create_clinic
        clinic = create_clinic()
        assert clinic["live_birth_rate_bps"] == 0
        assert clinic["multiple_birth_rate_bps"] == 0
        assert clinic["composite_quality_bps"] == 0
        assert clinic["cycles_reported"] == 0
        assert clinic["clinic_status"] == "IN_REVIEW"
        assert_clinic(clinic)

    def test_composite_quality_is_the_weighted_reading_over_the_workset(self):
        """PRD §3.3: "The composite score is a weighted reading over the same workset,
        published as `composite_quality_bps` and rounded half-up to whole basis points:
        60 times `live_birth_rate_bps` capped at ten thousand, minus 45 times
        `multiple_birth_rate_bps`, plus 20 times `cycles_reported` capped at 5."

        Design: Corner/entities/clinic_quality_readings_computed_with_client_values_ignored_input
        """
        scenario = setup_clinic_with_reported_workset(
            [{"live_birth": True, "births_count": 2, "multiple_birth": True,
              "gestational_weeks": 36},
             {"live_birth": True, "births_count": 1, "multiple_birth": False,
              "gestational_weeks": 39}])
        clinic = scenario["clinic"]
        assert clinic["cycles_reported"] == 2
        assert clinic["live_birth_rate_bps"] == 10000, "both records are live births"
        assert clinic["multiple_birth_rate_bps"] == 5000, "one of two live births was multiple"
        assert_quality_composite(clinic)
        assert_clinic_quality_invariants(clinic)

    def test_workset_one_report_short_of_maturity_takes_the_third_gate(self):
        """PRD §3.3: "the third gate is satisfied when the workset has reached exactly
        one report fewer than the maturity threshold."
        PRD §3.3: "The first gate is satisfied when the workset has reached the clinic's
        `maturity_report_threshold` and the live-birth rate is at or above the clinic's
        `min_live_birth_rate_bps` and the multiple-birth rate is at or below the clinic's
        `max_multiple_birth_rate_bps`."

        Design: Difficulty/compensating_invariant/outcome_void_restores_conserved_record_count_and_rate_denominator
        """
        from test_helpers import (
            setup_clinic_report_one_short_of_maturity, create_clinic,
            setup_clinic_with_reported_workset,
        )
        scenario = setup_clinic_report_one_short_of_maturity(
            clinic_overrides={"min_live_birth_rate_bps": 6000})
        clinic = scenario["clinic"]
        assert clinic["maturity_report_threshold"] == 2
        assert clinic["cycles_reported"] == 1, "exactly one short of the maturity window"
        assert clinic["live_birth_rate_bps"] == 0, "the single record is not a live birth"
        assert clinic["clinic_status"] == "CONTRACTED", (
            "the third gate treats a workset one report short of maturity as eligible"
        )


class TestCycleOutcomeCascade:
    """A cycle's recorded outcome walks onwards into its authorization and bundle."""

    def test_recorded_outcome_consumes_the_authorization_and_exhausts_the_bundle(self):
        """PRD §3.6: "the cycle's `consumption_marker` becomes `CONSUMED`, the
        authorization's `consumed_cycles` is incremented and its consumption posture
        recomputed — moving from `UNCONSUMED` to `PARTIALLY_CONSUMED`"
        PRD §3.10: "When a bundle's cycle allowance and its specialty-pharmacy pool are
        both empty — the condition that makes the bundle read as `EXHAUSTED`"

        Design: Difficulty/transitive_cascade/cycle_outcome_cascade_two_hop_cycle_to_auth_to_bundle_posture
        """
        scenario = build_exhaustion_cascade_scenario()

        cycle = validate_success(
            api_client.get_treatment_cycle(scenario["cycle"]["id"], NETWORK), 200)
        assert cycle["cycle_status"] == "OUTCOME_RECORDED"
        assert cycle["consumption_marker"] == "CONSUMED"

        preauth = validate_success(
            api_client.get_preauthorization(scenario["preauthorization"]["id"], CLAIMS), 200)
        assert preauth["consumed_cycles"] == 1
        assert preauth["consumption_status"] == "PARTIALLY_CONSUMED"

        bundle = validate_success(
            api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST), 200)
        assert bundle["cycles_consumed"] == 1
        assert bundle["cycles_remaining"] == 0
        assert bundle["pharmacy_remaining_cents"] == 0
        assert bundle["bundle_status"] == "EXHAUSTED"

    def test_exhaustion_denies_a_sibling_plans_undecided_authorization(self):
        """PRD §3.10: "every authorization on a plan drawing that entitlement that is
        still awaiting a first decision is denied, recorded for the reason
        `BUNDLE_EXHAUSTED`"

        Design: Difficulty/transitive_cascade/cycle_outcome_cascade_two_hop_cycle_to_auth_to_bundle_posture
        """
        scenario = build_exhaustion_cascade_scenario()

        sibling = validate_success(
            api_client.get_preauthorization(scenario["sibling_preauthorization"]["id"], CLAIMS), 200)
        assert sibling["review_status"] == "DENIED"
        assert sibling["denial_reason_code"] == "BUNDLE_EXHAUSTED"

        completed_plan = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        assert completed_plan["cycles_completed"] == 1
        assert completed_plan["plan_status"] == "COMPLETED"


def build_exhaustion_cascade_scenario() -> dict:
    """A sequential account with a one-cycle bundle whose pharmacy pool is drawn to
    zero, a single cycle whose outcome record exhausts the cycle allowance, and a
    sibling plan whose authorization is still awaiting a first decision."""
    from test_helpers import (
        NEUTRAL_CRITERIA, PHARMACIST, REVIEWER_ID, approve_preauthorization,
        create_advocate, create_bundle, create_claim_payload, create_clinic, create_contract,
        create_cycle, create_employer, create_medication_order_payload, create_member,
        create_plan, create_preauthorization, drive_cycle_to_outcome_recorded,
        select_clinic_for_plan, setup_clock,
    )

    setup_clock()
    employer = create_employer(allocation_method="SEQUENTIAL_BUNDLE")
    bundle = create_bundle(employer["id"], lifetime_max_cycles=1, max_cycles_per_year=1,
                           pharmacy_pool_cents=300000)
    advocate = create_advocate()
    clinic = create_clinic()
    create_contract(clinic, bundle_rates={"IVF_RETRIEVAL_TRANSFER": 1450000})

    member = create_member(employer["id"], advocate=advocate,
                           member_overrides={"external_ref": "EXHAUST-1"})
    plan = select_clinic_for_plan(
        create_plan(member, bundle, advocate, planned_cycles=1), clinic, advocate)
    preauth = approve_preauthorization(
        create_preauthorization(plan, advocate, 1, criteria_inputs=NEUTRAL_CRITERIA),
        plan, reviewer_id=REVIEWER_ID)

    # A sibling plan on the same bundle, its authorization still awaiting a decision.
    # It is filed while the allowance is still open, so the exhaustion cascade is what
    # later denies it rather than the filing gate.
    sibling_plan = select_clinic_for_plan(
        create_plan(member, bundle, advocate, planned_cycles=1), clinic, advocate)
    sibling_auth = create_preauthorization(sibling_plan, advocate, 1,
                                           criteria_inputs=NEUTRAL_CRITERIA)

    # Draw the specialty-pharmacy pool down to exactly zero.
    order = validate_success(api_client.create_medication_order(
        create_medication_order_payload(member["id"], preauth["id"],
                                        acquisition_cost_cents=300000), PHARMACIST), 201)
    current = validate_success(api_client.get_bundle_entitlement(bundle["id"], PHARMACIST), 200)
    validate_success(api_client.dispense_medication_order(
        order["id"], {"expected_bundle_entitlement_version": current["version"]}, PHARMACIST), 200)

    cycle = create_cycle(plan, preauth, clinic, retrieval_date="2026-09-04T00:00:00Z",
                         transfer_date="2026-09-06T00:00:00Z")
    cycle = drive_cycle_to_outcome_recorded(
        cycle, clinic, at_clock="2026-09-26T00:00:00Z",
        transfer_date="2026-09-06T00:00:00Z",
        outcome={"live_birth": False, "births_count": 0, "multiple_birth": False,
                 "gestational_weeks": 0})

    return {
        "employer": employer,
        "bundle": bundle,
        "advocate": advocate,
        "clinic": clinic,
        "member": member,
        "plan": plan,
        "preauthorization": preauth,
        "cycle": cycle,
        "sibling_plan": sibling_plan,
        "sibling_preauthorization": sibling_auth,
    }