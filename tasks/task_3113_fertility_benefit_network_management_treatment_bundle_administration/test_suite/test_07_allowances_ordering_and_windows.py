"""Remaining breadth coverage: allowance slices, cycle ordering, window errors,
listing partitions and the derived-counter reconciliation."""
import pytest

from test_helpers import (
    ADMIN,
    CLAIMS,
    NETWORK,
    PHARMACIST,
    REVIEWER_ID,
    api_client,
    approve_preauthorization,
    assert_ancillary_slice,
    assert_claim,
    assert_pharmacy_pool_conserved,
    create_advocate,
    create_bundle,
    create_clinic,
    create_clinic_contract_payload,
    create_claim_payload,
    create_contract,
    create_cycle,
    create_employer,
    create_member,
    create_medication_order_payload,
    create_plan,
    create_preauthorization,
    create_treatment_cycle_payload,
    drive_cycle_to_outcome_recorded,
    drive_cycle_to_transfer,
    is_iso8601_timestamp,
    make_care_advocate_headers,
    make_clinical_reviewer_headers,
    make_network_manager_headers,
    select_clinic_for_plan,
    setup_approved_authorization,
    setup_clock,
    setup_denied_claim,
    setup_dispensed_medication_order,
    setup_employer_bundle,
    setup_member_plan_clinic,
    setup_member_with_plan,
    setup_paid_claim,
    setup_reported_outcome_cycle,
    tick_clock,
    validate_paginated,
    validate_success,
)


class TestAncillarySlicesAreIndependent:
    """The ancillary caps are separate slices of one ceiling, not a shared pool."""

    def test_lab_and_storage_claims_each_reach_their_own_slice(self):
        """PRD §3.9: "The four ancillary categories are each capped at their own slice of
        the same ceiling, and those slices are computed independently rather than divided
        out of one another: a laboratory claim is capped at 12 percent of the ceiling, a
        storage claim at 4 percent, a donor-material claim at 18 percent, and a
        surrogacy-fee claim at 25 percent, each rounded half-up to whole cents, each
        compared against the billed charge with the smaller of the two becoming the
        allowance"
        PRD §3.9: "Because the slices are not additive, four ancillary claims may each
        reach their own slice against the same ceiling."

        Design: Corner/calculations/claim_allowed_amount_ancillary_slices_are_independent_not_additive
        """
        scenario = setup_approved_authorization()
        ceiling = scenario["plan"]["selected_bundle_price_cents"]
        assert ceiling > 0, "the plan's price is pinned when the clinic is selected"

        lab = validate_success(api_client.create_claim(
            create_claim_payload(scenario["member"]["id"], scenario["preauthorization"]["id"],
                                 service_category="LAB", billed_cents=200000,
                                 service_date_iso="2026-09-01T00:00:00Z"),
            CLAIMS), 201)
        storage = validate_success(api_client.create_claim(
            create_claim_payload(scenario["member"]["id"], scenario["preauthorization"]["id"],
                                 service_category="STORAGE", billed_cents=40000,
                                 service_date_iso="2026-09-01T00:00:00Z"),
            CLAIMS), 201)

        lab_now = validate_success(api_client.adjudicate_claim(lab["id"], CLAIMS), 200)
        assert lab_now["adjudication_basis"] == "BUNDLE_COMPONENT_RULE", (
            "the bill exceeded the laboratory slice, so the allowance clamped"
        )
        assert_ancillary_slice(lab_now["allowed_cents"], ceiling, "LAB", 200000)

        storage_now = validate_success(api_client.adjudicate_claim(storage["id"], CLAIMS), 200)
        assert storage_now["adjudication_basis"] == "CONTRACT_RATE", (
            "the storage bill sat under its own slice, so it is allowed in full"
        )
        assert storage_now["allowed_cents"] == 40000
        assert_ancillary_slice(storage_now["allowed_cents"], ceiling, "STORAGE", 40000)

        # The two slices did not consume each other's headroom.
        assert lab_now["allowed_cents"] + storage_now["allowed_cents"] > ceiling * 0.04
        assert_claim(lab_now)
        assert_claim(storage_now)

    def test_medication_allowance_is_the_amount_the_pool_already_settled(self):
        """PRD §3.9: "For a `MEDICATION` claim the allowance is simply the amount the
        pharmacy pool already settled on the corresponding order, and the adjudication
        basis reads `BUNDLE_COMPONENT_RULE`."

        Design: Corner/calculations/claim_allowed_amount_ancillary_slices_are_independent_not_additive
        """
        scenario = setup_dispensed_medication_order(acquisition_cost_cents=300000)
        order = scenario["medication_order"]
        assert order["plan_paid_cents"] == 300000

        claim = validate_success(api_client.create_claim(
            create_claim_payload(scenario["member"]["id"], scenario["preauthorization"]["id"],
                                 service_category="MEDICATION", billed_cents=300000,
                                 service_date_iso="2026-09-01T00:00:00Z"),
            CLAIMS), 201)
        adjudicated = validate_success(api_client.adjudicate_claim(claim["id"], CLAIMS), 200)

        assert adjudicated["allowed_cents"] == order["plan_paid_cents"]
        assert adjudicated["adjudication_basis"] == "BUNDLE_COMPONENT_RULE"


class TestCycleIndexOrdering:
    """cycle_index is a dense ordinal over every cycle of the plan, cancellations included."""

    def test_cancellation_does_not_renumber_the_later_cycle(self):
        """PRD §3.6: "the index is a dense ordinal over all cycles of the plan including
        cancelled ones, so a plan whose first cycle is cancelled and whose second cycle
        records an outcome reads `cycle_index` 2 on the recorded cycle while its
        `cycles_completed` reads 1."

        Design: Corner/calculations/cycle_index_assigned_by_created_at_ordering_with_tie_breaks
        """
        scenario = setup_two_cycle_plan()
        first = scenario["first_cycle"]
        second = scenario["second_cycle"]
        clinic = scenario["clinic"]
        headers = make_clinic_coordinator_headers_for(clinic["id"])

        before = validate_success(api_client.list_treatment_cycles(
            NETWORK, {"treatment_plan_id": scenario["plan"]["id"]}), 200)
        assert [row["cycle_index"] for row in before] == [1, 2]

        cancelled = validate_success(api_client.cancel_cycle(first["id"], headers), 200)
        assert cancelled["cycle_status"] == "CANCELLED"
        assert cancelled["consumption_marker"] == "UNCONSUMED", (
            "a cancelled cycle releases the slot it had claimed"
        )

        second_after = validate_success(
            api_client.get_treatment_cycle(second["id"], NETWORK), 200)
        assert second_after["cycle_index"] == 2, "cancellation does not renumber"

        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        assert plan_now["cycles_completed"] == 0

        cancelled_only = validate_success(api_client.list_treatment_cycles(
            NETWORK, {"treatment_plan_id": scenario["plan"]["id"],
                      "cycle_status": "CANCELLED"}), 200)
        assert len(cancelled_only) == 1


def make_clinic_coordinator_headers_for(clinic_id: str):
    from test_helpers import make_clinic_coordinator_headers
    return make_clinic_coordinator_headers(clinic_id)


def setup_two_cycle_plan() -> dict:
    """A plan with two approved authorizations and two scheduled cycles."""
    from test_helpers import NEUTRAL_CRITERIA

    scenario = setup_member_plan_clinic(
        allocation_method="CONCURRENT_BUNDLE",
        bundle_overrides={"lifetime_max_cycles": 6, "max_cycles_per_year": 6},
        plan_overrides={"planned_cycles": 2, "min_inter_cycle_days": 0})
    plan = scenario["plan"]
    advocate = scenario["advocate"]
    clinic = scenario["clinic"]

    first_auth = approve_preauthorization(
        create_preauthorization(plan, advocate, 1, criteria_inputs=NEUTRAL_CRITERIA),
        plan, reviewer_id=REVIEWER_ID)
    first_cycle = create_cycle(plan, first_auth, clinic,
                               retrieval_date="2026-09-05T00:00:00Z",
                               transfer_date="2026-09-10T00:00:00Z")
    second_auth = approve_preauthorization(
        create_preauthorization(plan, advocate, 2, criteria_inputs=NEUTRAL_CRITERIA),
        plan, reviewer_id=REVIEWER_ID)
    second_cycle = create_cycle(plan, second_auth, clinic,
                                retrieval_date="2026-09-20T00:00:00Z",
                                transfer_date="2026-09-25T00:00:00Z")
    scenario["first_cycle"] = first_cycle
    scenario["second_cycle"] = second_cycle
    scenario["plan"] = validate_success(
        api_client.get_treatment_plan(plan["id"], NETWORK), 200)
    return scenario


class TestAuthorizationListPartitions:
    """The authorization collection exposes both state dimensions as filters."""

    def test_review_and_consumption_filters_partition_the_same_row(self):
        """PRD §3.6: "Reading cycles back, the collection accepts `treatment_plan_id`,
        `preauthorization_id`, `member_id`, and `cycle_status` as filters, and
        authorizations accept `treatment_plan_id`, `review_status`, and
        `consumption_status`."

        Design: Corner/endpoints/preauthorizations_list_partitions_the_two_state_dimensions
        """
        from test_helpers import validate_paginated

        scenario = setup_approved_authorization()
        plan_id = scenario["plan"]["id"]
        preauth = scenario["preauthorization"]

        data, meta = validate_paginated(
            api_client.list_preauthorizations(CLAIMS, {"treatment_plan_id": plan_id}))
        assert meta["total_count"] == 1

        for params in ({"treatment_plan_id": plan_id, "review_status": "APPROVED"},
                       {"treatment_plan_id": plan_id, "consumption_status": "UNCONSUMED"}):
            data, meta = validate_paginated(api_client.list_preauthorizations(CLAIMS, params))
            assert meta["total_count"] == 1, f"expected the row under {params}"

        data, meta = validate_paginated(api_client.list_preauthorizations(
            CLAIMS, {"treatment_plan_id": plan_id,
                      "consumption_status": "PARTIALLY_CONSUMED"}))
        assert meta["total_count"] == 0, "nothing is consumed until a cycle's outcome is recorded"

        assert preauth["approved_cycles"] == 1
        assert preauth["consumed_cycles"] == 0
        # PRD 3.5: approval sets effective_from to the logical clock, which is the
        # instant the server adopts at startup.
        assert is_iso8601_timestamp(preauth["effective_from"])
        assert preauth["effective_from"].startswith("2026-09-01T00:00:00")


class TestOutcomeRecordDiscovery:
    """The filtered outcome list is how a reported record is found again."""

    def test_outcome_records_are_discoverable_and_reconcile_both_derived_counters(self):
        """PRD §3.10: "The member's completed-cycle count counts their cycles that have
        reached `OUTCOME_RECORDED`, and the member's recorded-live-births figure sums the
        `births_count` across their outcome records that are `RECORDED` or `AMENDED`,
        treating voided records as if they had never existed."

        Design: Corner/endpoints/outcome_records_filtered_list_is_the_only_discovery_channel_for_a_cascade_created_record
        """
        scenario = setup_reported_outcome_cycle(
            outcome={"live_birth": True, "births_count": 2, "multiple_birth": True,
                     "gestational_weeks": 36})
        clinic = scenario["clinic"]
        record = scenario["outcome_record"]

        data, meta = validate_paginated(
            api_client.list_outcome_records(NETWORK, {"clinic_id": clinic["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == record["id"]
        assert data[0]["outcome_status"] == "RECORDED"
        assert data[0]["treatment_cycle_id"] == scenario["cycle"]["id"]
        assert data[0]["member_id"] == scenario["member"]["id"]
        assert data[0]["multiple_birth"] is True
        assert data[0]["births_count"] == 2

        assert clinic["cycles_reported"] == 1
        assert clinic["live_birth_rate_bps"] == 10000
        assert clinic["multiple_birth_rate_bps"] == 10000

        member = validate_success(api_client.get_member(scenario["member"]["id"], NETWORK), 200)
        assert member["live_births_recorded"] == 2
        assert member["completed_cycles"] == 1

        voided, voided_meta = validate_paginated(api_client.list_outcome_records(
            NETWORK, {"clinic_id": clinic["id"], "outcome_status": "VOIDED"}))
        assert voided_meta["total_count"] == 0


class TestWindowClosedErrors:
    """The reversal and amendment windows are separate errors on separate resources."""

    def test_reversal_and_amendment_window_errors_are_distinct(self):
        """PRD §2.10: "A correction after the fact fails outside its window with
        `ERR_REVERSAL_WINDOW_CLOSED` or `ERR_AMENDMENT_WINDOW_CLOSED`."

        Design: Corner/errors/reversal_window_closed_and_amendment_window_closed_are_distinct_errors
        """
        paid = setup_paid_claim()
        reported = setup_reported_outcome_cycle()

        # Close both windows by walking well past any plausible configured length.
        setup_clock("2028-06-01T00:00:00Z")

        reversal = api_client.reverse_claim(paid["claim"]["id"], CLAIMS)
        assert reversal.status_code == 422
        assert reversal.json()["data"]["error_id"] == "ERR_REVERSAL_WINDOW_CLOSED"

        amendment = api_client.amend_outcome_record(
            reported["outcome_record"]["id"],
            {"live_birth": True, "births_count": 1, "multiple_birth": False,
             "gestational_weeks": 38, "amendment_reason": "late chart correction"},
            NETWORK)
        assert amendment.status_code == 422
        assert amendment.json()["data"]["error_id"] == "ERR_AMENDMENT_WINDOW_CLOSED"

        assert (reversal.json()["data"]["error_id"]
                != amendment.json()["data"]["error_id"])

        claim_after = validate_success(api_client.get_claim(paid["claim"]["id"], CLAIMS), 200)
        assert claim_after["claim_status"] == "PAID"
        record_after = validate_success(
            api_client.get_outcome_record(reported["outcome_record"]["id"], NETWORK), 200)
        assert record_after["outcome_status"] == "RECORDED"
        assert record_after["amendment_reason"] is None


class TestBenefitInactiveOnSuspension:
    """Suspending the sponsor cascades into the entitlement and its pending authorizations."""

    def test_suspension_nulls_the_allowance_and_reactivation_restores_it(self):
        """PRD §2.4: "A suspended employer account is a special case of the ledger
        principle: while `account_status` is `SUSPENDED`, its entitlements are read as
        `DRAFT` and compute no netting at all, and their remaining counters read zero."

        Design: Corner/validations/employer_suspend_expires_pending_authorizations_and_nulls_the_bundle_allowance
        """
        scenario = setup_approved_authorization()
        employer = scenario["employer"]
        bundle = scenario["bundle"]

        suspended = validate_success(
            api_client.suspend_employer_account(employer["id"], ADMIN), 200)
        assert suspended["account_status"] == "SUSPENDED"

        bundle_after = validate_success(
            api_client.get_bundle_entitlement(bundle["id"], ADMIN), 200)
        assert bundle_after["cycles_remaining"] == 0
        assert bundle_after["bundle_status"] == "DRAFT", (
            "a suspended account's entitlements read as draft"
        )

        reactivated = validate_success(
            api_client.reactivate_employer_account(employer["id"], ADMIN), 200)
        assert reactivated["account_status"] == "ACTIVE"
        restored = validate_success(
            api_client.get_bundle_entitlement(bundle["id"], ADMIN), 200)
        assert restored["cycles_remaining"] > 0, (
            "reactivation restores the reading for an entitlement with allowance left"
        )

    def test_suspension_expires_a_pending_authorization(self):
        """PRD §3.1: "Any authorization belonging to a member of that account that is
        still `SUBMITTED` and awaiting a first clinical decision is expired at the same
        moment, and it is recorded as expired for the reason `ACCOUNT_SUSPENDED` rather
        than for lapse of time."

        Design: Corner/validations/employer_suspend_expires_pending_authorizations_and_nulls_the_bundle_allowance
        """
        scenario = setup_member_plan_clinic()
        pending = create_preauthorization(scenario["plan"], scenario["advocate"], 1)
        assert pending["review_status"] == "SUBMITTED"

        validate_success(api_client.suspend_employer_account(scenario["employer"]["id"], ADMIN), 200)

        expired = validate_success(
            api_client.get_preauthorization(pending["id"], CLAIMS), 200)
        assert expired["review_status"] == "EXPIRED"
        assert expired["denial_reason_code"] == "ACCOUNT_SUSPENDED"


class TestMemberClosureGate:
    """A member closes only once nothing is still running underneath them."""

    def test_complete_care_refused_while_a_plan_is_live_and_admitted_once_it_terminates(self):
        """PRD §3.2: "A member may be closed only when they are `CARE_ACTIVE` and when
        nothing is still running underneath them: no plan of theirs may be in
        `PLAN_DRAFT`, `CLINIC_SELECTED`, `AUTHORIZATION_PENDING`, `IN_PROGRESS`, or
        `PLANNING_REVISION`"

        Design: Corner/validations/member_care_complete_with_live_plan_returns_invalid_state
        """
        scenario = setup_member_plan_clinic()
        member = scenario["member"]
        advocate = scenario["advocate"]
        plan = scenario["plan"]
        headers = make_care_advocate_headers(advocate["id"])

        blocked = api_client.complete_care(member["id"], headers)
        assert blocked.status_code == 409
        assert blocked.json()["data"]["error_id"] == "ERR_INVALID_STATE"
        assert plan["plan_status"] == "CLINIC_SELECTED"

        validate_success(api_client.abandon_plan(plan["id"], headers), 200)

        closed = validate_success(api_client.complete_care(member["id"], headers), 200)
        assert closed["member_status"] == "CARE_COMPLETE"

        advocate_after = validate_success(
            api_client.get_care_advocate(advocate["id"], NETWORK), 200)
        assert advocate_after["assignments_completed"] == 1
        assert advocate_after["current_caseload"] == 1, (
            "a completed member still counts toward the live caseload"
        )


class TestDerivedCounterReconciliation:
    """Two denormalized counters move by different amounts on the same event."""

    def test_active_member_count_and_current_caseload_count_different_populations(self):
        """PRD §3.1: "`active_member_count` tracks members whose `member_status` is
        `INTAKE`, `CARE_ACTIVE`, or `CARE_COMPLETE`"
        PRD §3.2: "The live caseload counts members whose `member_status` is
        `CARE_ACTIVE` or `CARE_COMPLETE`, and the completed-assignment count counts only
        members who have reached `CARE_COMPLETE`"

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_on_advocate_caseload_and_employer_member_count
        """
        from test_helpers import create_surrender_route_payload, setup_surrender_route

        employer = create_employer()
        advocate = create_advocate()
        closing = create_member(employer["id"], advocate=advocate,
                                member_overrides={"external_ref": "DERIVED-1"})
        pending = create_member(employer["id"], advocate=advocate, complete_intake=False,
                                member_overrides={"external_ref": "DERIVED-2"})

        account = validate_success(api_client.get_employer_account(employer["id"], ADMIN), 200)
        advocate_now = validate_success(api_client.get_care_advocate(advocate["id"], ADMIN), 200)
        assert account["active_member_count"] == 2, "the INTAKE member is counted here"
        assert advocate_now["current_caseload"] == 1, "the INTAKE member is not counted here"

        validate_success(api_client.complete_care(
            closing["id"], make_care_advocate_headers(advocate["id"])), 200)

        account_after = validate_success(
            api_client.get_employer_account(employer["id"], ADMIN), 200)
        advocate_after = validate_success(
            api_client.get_care_advocate(advocate["id"], ADMIN), 200)
        assert account_after["active_member_count"] == 2, (
            "a closed member still counts, and so does the intake member"
        )
        assert advocate_after["current_caseload"] == 1
        assert advocate_after["assignments_completed"] == 1, (
            "only the completed member is counted here"
        )

        still_intake = validate_success(api_client.list_members(
            NETWORK, {"care_advocate_id": advocate["id"], "member_status": "INTAKE"}), 200)
        assert len(still_intake) == 1
        assert still_intake[0]["id"] == pending["id"]


class TestIdempotencyOfOutcomeReporting:
    """One outcome record per cycle is enforced at the idempotency gate."""

    def test_second_report_for_one_cycle_returns_duplicate_operation(self):
        """PRD §3.3: "a second report for the same cycle is refused with
        `ERR_DUPLICATE_OPERATION`"
        PRD §2.10: "four operations are idempotency-protected — reporting a cycle
        outcome, amending an outcome record, voiding an outcome record, and deciding an
        authorization — and a second attempt at an operation already carried out on the
        same resource is refused with `ERR_DUPLICATE_OPERATION` and a 409 status."

        Design: Corner/cross_cutting_complexity_layers/idempotency_second_outcome_report_for_one_cycle_returns_duplicate_operation
        """
        scenario = setup_reported_outcome_cycle()
        clinic = scenario["clinic"]
        cycle = validate_success(
            api_client.get_treatment_cycle(scenario["cycle"]["id"], NETWORK), 200)

        duplicate = api_client.report_outcome(
            clinic["id"],
            {"treatment_cycle_id": cycle["id"], "live_birth": True, "births_count": 1,
             "multiple_birth": False, "gestational_weeks": 39,
             "expected_treatment_cycle_version": cycle["version"]},
            make_clinic_coordinator_headers_for(clinic["id"]))

        assert duplicate.status_code == 409
        assert duplicate.json()["data"]["error_id"] == "ERR_DUPLICATE_OPERATION"
        assert duplicate.json()["data"]["error_id"] != "ERR_CYCLE_VERSION_STALE", (
            "the version token was current, so the idempotency gate is what fired"
        )

        records = validate_success(
            api_client.list_outcome_records(NETWORK, {"clinic_id": clinic["id"]}), 200)
        assert len(records) == 1
        clinic_now = validate_success(api_client.get_clinic(clinic["id"], NETWORK), 200)
        assert clinic_now["cycles_reported"] == 1


class TestDispenseRequiresAnApprovedAuthorization:
    """The dispense gate reads the authorization's review status before the pool."""

    def test_dispense_against_a_submitted_authorization_returns_invalid_state(self):
        """PRD §2.10: "A clinic whose active contract has been frozen for a quality breach
        is unavailable for new clinical authorization and for new medication orders,
        refused with `ERR_CLINIC_CONTRACT_FROZEN`."
        PRD §3.7: "It is available only from `PRESCRIBED`, requires that the order's
        authorization is `APPROVED`, and requires that the bundle's pharmacy pool holds at
        least one cent."

        Design: Corner/errors/medication_dispense_against_unapproved_authorization_returns_invalid_state
        """
        employer, bundle = setup_employer_bundle()
        advocate = create_advocate()
        member = create_member(employer["id"], advocate=advocate)
        clinic, contract = setup_clinic_and_contract()
        plan = select_clinic_for_plan(
            create_plan(member, bundle, advocate, planned_cycles=1), clinic, advocate)
        submitted = create_preauthorization(plan, advocate, 1)
        assert submitted["review_status"] == "SUBMITTED"

        order = validate_success(api_client.create_medication_order(
            create_medication_order_payload(member["id"], submitted["id"],
                                            acquisition_cost_cents=300000),
            PHARMACIST), 201)
        bundle_now = validate_success(
            api_client.get_bundle_entitlement(bundle["id"], PHARMACIST), 200)

        response = api_client.dispense_medication_order(
            order["id"], {"expected_bundle_entitlement_version": bundle_now["version"]},
            PHARMACIST)

        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_INVALID_STATE"
        assert response.json()["data"]["error_id"] != "ERR_PHARMACY_POOL_EXHAUSTED"

        unchanged = validate_success(api_client.get_medication_order(order["id"], PHARMACIST), 200)
        assert unchanged["pharmacy_status"] == "PRESCRIBED"
        assert unchanged["plan_paid_cents"] == 0
        assert unchanged["dispensed_on"] is None

        bundle_after = validate_success(
            api_client.get_bundle_entitlement(bundle["id"], PHARMACIST), 200)
        assert bundle_after["pharmacy_remaining_cents"] == 1000000
        assert bundle_after["pharmacy_consumed_cents"] == 0
        assert_pharmacy_pool_conserved(bundle_after)


def setup_clinic_and_contract(rate: int = 1450000):
    from test_helpers import setup_contracted_clinic
    return setup_contracted_clinic(rate=rate)


class TestImmediateConsistency:
    """Every cascaded field is readable on the very next request."""

    def test_record_outcome_cascades_are_visible_without_any_intervening_call(self):
        """PRD §2.5: "Cascaded updates are not exempt: when one operation moves a parent
        and a child at the same time, each row updates its own `updated_at` and its own
        `version` independently, and the operation's response reflects the row named in
        the request path."
        PRD §2.4: "These are ledgers in the strict sense — they are recomputed from the
        rows that reference the entitlement, never incremented blindly"

        Design: Corner/consistency_model/immediate_consistency_cascade_side_effects_visible_on_the_same_request
        """
        scenario = setup_reported_outcome_cycle(
            outcome={"live_birth": True, "births_count": 1, "multiple_birth": False,
                     "gestational_weeks": 38})

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

        member = validate_success(api_client.get_member(scenario["member"]["id"], NETWORK), 200)
        assert member["completed_cycles"] == 1
        assert member["live_births_recorded"] == 1

        plan = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        assert plan["cycles_completed"] == 1
        assert plan["plan_status"] == "COMPLETED", "planned_cycles was one"