"""Clinical appropriateness scoring, interval spacing, and the OCC and capacity gates."""
import pytest

from test_helpers import (
    CLAIMS,
    NETWORK,
    api_client,
    assert_bundle_entitlement,
    create_advocate,
    create_bundle,
    create_clinic,
    create_cycle,
    create_employer,
    create_member,
    create_plan,
    create_preauthorization,
    create_surrender_route_payload,
    create_treatment_cycle_payload,
    drive_cycle_to_outcome_recorded,
    drive_cycle_to_transfer,
    is_iso8601_timestamp,
    approve_preauthorization,
    make_care_advocate_headers,
    make_clinical_reviewer_headers,
    make_clinic_coordinator_headers,
    make_member_headers,
    make_network_manager_headers,
    select_clinic_for_plan,
    setup_approved_authorization,
    setup_approved_authorizations,
    setup_authorization_near_score_floor,
    setup_clinic_with_reported_workset,
    setup_clock,
    setup_contracted_clinic,
    setup_employer_bundle,
    setup_member_plan_clinic,
    setup_member_with_plan,
    setup_routed_surrender_route,
    setup_surrender_route,
    tick_clock,
    validate_success,
)


class TestClinicalCriteriaFloor:
    """The approval floor is 70 inclusive, and the penalties are summed before the clamp."""

    def test_profile_scoring_sixty_nine_is_denied_with_criteria_not_met(self):
        """PRD §3.5: "In practical terms the score is a clinical-appropriateness gate
        whose approval floor is 70, inclusive."
        PRD §3.5: "A score below the floor produces a denial instead, recorded for the
        reason `CLINICAL_CRITERIA_NOT_MET`"

        Design: Difficulty/boundary_precision_check/clinical_criteria_approval_floor_exactly_seventy
        """
        scenario = setup_authorization_near_score_floor(score_profile="69")
        preauth = scenario["preauthorization"]
        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)

        assert preauth["clinical_criteria_score"] == 65, (
            "prior cycles 3 (25) + fsh 13 (10) = 35 off 100, below the 70 floor"
        )

        response = api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "APPROVE", "expected_treatment_plan_version": plan_now["version"]},
            make_clinical_reviewer_headers("rev-floor"))

        assert response.status_code == 422
        assert response.json()["data"]["error_id"] == "ERR_CLINICAL_CRITERIA_NOT_MET"
        denied = validate_success(api_client.get_preauthorization(preauth["id"], CLAIMS), 200)
        assert denied["review_status"] == "DENIED"
        assert denied["denial_reason_code"] == "CLINICAL_CRITERIA_NOT_MET"

    def test_profile_scoring_exactly_seventy_is_approved(self):
        """PRD §3.5: "The steps, in the order they are applied, are: subtract an age
        penalty of 0 for an age under 35, 20 for an age from 35 through 37, 40 for an age
        from 38 through 40, and 60 for an age of 41 or over; subtract 20 when `amh_ng_ml`
        is below 0.5, 10 when it is below 1.0 but at least 0.5, and nothing otherwise;
        add 15 when the member has a prior live birth; subtract 25 when `prior_cycles` is
        3 or more, 15 when it is exactly 2, and nothing otherwise; and subtract 10 when
        `fsh_iu_l` is above 12."
        PRD §3.5: "inputs that total 74 approve, and an implementation that clamps after
        every subtraction would land on 70 and also approve, but one step further down the
        inputs diverge at 70 versus 69"

        Design: Difficulty/boundary_precision_check/clinical_criteria_approval_floor_exactly_seventy
        """
        scenario = setup_authorization_near_score_floor(score_profile="70")
        preauth = scenario["preauthorization"]
        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)

        assert preauth["clinical_criteria_score"] == 70, (
            "the bands total 74; the inclusive floor of 70 admits it"
        )

        approved = validate_success(api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "APPROVE", "expected_treatment_plan_version": plan_now["version"]},
            make_clinical_reviewer_headers("rev-floor")), 200)

        assert approved["review_status"] == "APPROVED"
        assert approved["approved_cycles"] == 1
        plan_after = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        assert plan_after["plan_status"] == "IN_PROGRESS"

    def test_absent_criteria_keys_read_as_neutral_values(self):
        """PRD §3.5: "Missing keys are read as neutral values rather than rejected: an
        absent `age_years` reads 30, an absent `amh_ng_ml` reads 2.0, an absent
        `prior_cycles` reads 0, an absent `prior_live_birth` reads false, and an absent
        `fsh_iu_l` reads 6. Neutral inputs therefore score 100 and approve."

        Design: Difficulty/boundary_precision_check/clinical_criteria_approval_floor_exactly_seventy
        """
        scenario = setup_member_plan_clinic()
        preauth = validate_success(api_client.create_preauthorization(
            scenario["plan"]["id"],
            {"cycle_sequence_index": 1, "criteria_inputs": {}, "member_cost_share_pct": 20},
            make_care_advocate_headers(scenario["advocate"]["id"])), 201)

        reviewing = validate_success(api_client.begin_clinical_review(
            preauth["id"], make_clinical_reviewer_headers("rev-neutral")), 200)

        assert reviewing["clinical_criteria_score"] == 100
        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        approved = validate_success(api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "APPROVE", "expected_treatment_plan_version": plan_now["version"]},
            make_clinical_reviewer_headers("rev-neutral")), 200)
        assert approved["approved_cycles"] == 1
        assert approved["review_status"] == "APPROVED"


class TestAuthorizationDimensionIndependence:
    """Review status and consumption status move independently on one row."""

    def test_denied_authorization_returns_to_review_with_consumption_untouched(self):
        """PRD §3.5: "The advocate may revise the clinical inputs of a denied
        authorization by supplying a fresh `criteria_inputs` object, which returns it to
        `CLINICAL_REVIEW`, recomputes the score from the new inputs, and clears the denial
        reason, leaving `decision_actor` untouched"
        PRD §3.6: "The consumption dimension is independent of all of it and is described
        in §3.6."

        Design: Difficulty/non_linear_state_machine/preauthorization_parallel_review_and_consumption_dimensions
        """
        scenario = setup_authorization_near_score_floor(score_profile="69")
        preauth = scenario["preauthorization"]
        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        denied = validate_success(api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "DENY", "denial_reason_code": "CLINICAL_CRITERIA_NOT_MET",
             "expected_treatment_plan_version": plan_now["version"]},
            make_clinical_reviewer_headers("rev-loop")), 200)
        assert denied["review_status"] == "DENIED"
        assert denied["consumption_status"] == "UNCONSUMED"

        revised = validate_success(api_client.revise_preauthorization(
            preauth["id"],
            {"criteria_inputs": {"age_years": 32, "amh_ng_ml": 2.4, "prior_cycles": 0,
                                 "prior_live_birth": False, "fsh_iu_l": 6}},
            make_care_advocate_headers(scenario["advocate"]["id"])), 200)

        assert revised["review_status"] == "CLINICAL_REVIEW"
        assert revised["consumption_status"] == "UNCONSUMED", (
            "the consumption dimension is untouched by the review loop"
        )
        assert revised["denial_reason_code"] is None
        assert revised["clinical_criteria_score"] == 100, (
            "the score is recomputed from the new inputs, not carried over"
        )
        assert revised["decision_actor"] == "rev-loop", (
            "the reviewer who denied it remains on the record"
        )

    def test_review_and_consumption_dimensions_are_separately_filterable(self):
        """PRD §3.6: "authorizations accept `treatment_plan_id`, `review_status`, and
        `consumption_status`."

        Design: Difficulty/non_linear_state_machine/preauthorization_parallel_review_and_consumption_dimensions
        """
        scenario = setup_authorization_near_score_floor(score_profile="69")
        preauth = scenario["preauthorization"]
        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        validate_success(api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "DENY", "denial_reason_code": "CLINICAL_CRITERIA_NOT_MET",
             "expected_treatment_plan_version": plan_now["version"]},
            make_clinical_reviewer_headers("rev-loop")), 200)

        in_review = validate_success(api_client.list_preauthorizations(
            CLAIMS, {"treatment_plan_id": scenario["plan"]["id"],
                      "review_status": "CLINICAL_REVIEW"}), 200)
        assert in_review == []

        denied = validate_success(api_client.list_preauthorizations(
            CLAIMS, {"treatment_plan_id": scenario["plan"]["id"],
                      "review_status": "DENIED"}), 200)
        assert len(denied) == 1

        validate_success(api_client.revise_preauthorization(
            preauth["id"],
            {"criteria_inputs": {"age_years": 32, "amh_ng_ml": 2.4, "prior_cycles": 0,
                                 "prior_live_birth": False, "fsh_iu_l": 6}},
            make_care_advocate_headers(scenario["advocate"]["id"])), 200)

        in_review_after = validate_success(api_client.list_preauthorizations(
            CLAIMS, {"treatment_plan_id": scenario["plan"]["id"],
                      "review_status": "CLINICAL_REVIEW"}), 200)
        assert len(in_review_after) == 1, "the row came back into review"
        denied_after = validate_success(api_client.list_preauthorizations(
            CLAIMS, {"treatment_plan_id": scenario["plan"]["id"],
                      "review_status": "DENIED"}), 200)
        assert denied_after == []


class TestCycleSpacingBoundary:
    """The plan's minimum inter-cycle spacing is a whole-day buffer."""

    def test_cycle_creation_one_day_inside_the_spacing_buffer_is_refused(self):
        """PRD §3.6: "The logical clock must be at least `min_inter_cycle_days` whole
        days after the plan's most recent prior transfer instant, and the cycle must not
        fall inside a retention window already reserved by a routed surrender route
        belonging to the same member; a violation is refused with `ERR_CYCLE_SLOT_OVERLAP`
        and a 409 status."

        Design: Difficulty/resource_temporal_overlap/cycle_slot_overlap_touching_interval_and_spacing_buffer
        """
        scenario = setup_spaced_plan(prior_transfer="2026-09-10T00:00:00Z",
                                     min_inter_cycle_days=14)
        setup_clock("2026-09-23T00:00:00Z")  # thirteen whole days after the transfer
        second_auth = scenario["second_preauthorization"]

        response = api_client.create_treatment_cycle(
            scenario["plan"]["id"],
            create_treatment_cycle_payload(
                second_auth["id"], retrieval_date="2026-09-24T00:00:00Z",
                transfer_date="2026-09-26T00:00:00Z"),
            make_clinic_coordinator_headers(scenario["clinic"]["id"]))

        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_CYCLE_SLOT_OVERLAP"
        rows = validate_success(api_client.list_treatment_cycles(
            NETWORK, {"treatment_plan_id": scenario["plan"]["id"]}), 200)
        assert len(rows) == 1, "the refused cycle was never persisted"

    def test_cycle_creation_exactly_at_the_spacing_buffer_is_admitted(self):
        """PRD §3.6: "The logical clock must be at least `min_inter_cycle_days` whole
        days after the plan's most recent prior transfer instant"

        Design: Difficulty/resource_temporal_overlap/cycle_slot_overlap_touching_interval_and_spacing_buffer
        """
        scenario = setup_spaced_plan(prior_transfer="2026-09-10T00:00:00Z",
                                     min_inter_cycle_days=14)
        setup_clock("2026-09-24T00:00:00Z")  # exactly fourteen whole days
        second_auth = scenario["second_preauthorization"]

        created = validate_success(api_client.create_treatment_cycle(
            scenario["plan"]["id"],
            create_treatment_cycle_payload(
                second_auth["id"], retrieval_date="2026-09-25T00:00:00Z",
                transfer_date="2026-09-27T00:00:00Z"),
            make_clinic_coordinator_headers(scenario["clinic"]["id"])), 201)

        assert created["cycle_index"] == 2
        assert created["cycle_status"] == "SCHEDULED"
        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        assert plan_now["min_inter_cycle_days"] == 14, (
            "the buffer is a plan-level field rather than a global default"
        )


def setup_spaced_plan(prior_transfer: str, min_inter_cycle_days: int) -> dict:
    """A plan with a spacing rule, two approved authorizations and one completed cycle
    whose transfer instant anchors the buffer."""
    scenario = setup_member_plan_clinic(
        allocation_method="CONCURRENT_BUNDLE",
        bundle_overrides={"lifetime_max_cycles": 6, "max_cycles_per_year": 6},
        plan_overrides={"planned_cycles": 2, "min_inter_cycle_days": min_inter_cycle_days})
    plan = scenario["plan"]
    advocate = scenario["advocate"]
    clinic = scenario["clinic"]

    # Both authorizations are approved at the clock's start: an authorization's
# validity window opens at the instant of approval, so the later cycle's
# back-dated service instants only fall inside it if the approval is early.
    first = approve_preauthorization(
        create_preauthorization(plan, advocate, 1,
                                criteria_inputs={"age_years": 33, "amh_ng_ml": 2.0,
                                                 "prior_cycles": 0, "prior_live_birth": False,
                                                 "fsh_iu_l": 6}),
        plan, reviewer_id="rev-spacing")
    second = approve_preauthorization(
        create_preauthorization(plan, advocate, 2,
                                criteria_inputs={"age_years": 33, "amh_ng_ml": 2.0,
                                                 "prior_cycles": 1, "prior_live_birth": False,
                                                 "fsh_iu_l": 6}),
        plan, reviewer_id="rev-spacing")
    cycle = create_cycle(plan, first, clinic, retrieval_date="2026-09-08T00:00:00Z",
                         transfer_date=prior_transfer)
    cycle = drive_cycle_to_outcome_recorded(
        cycle, clinic, at_clock="2026-09-26T00:00:00Z", transfer_date=prior_transfer,
        outcome={"live_birth": False, "births_count": 0, "multiple_birth": False,
                 "gestational_weeks": 0})

    return {
        "employer": scenario["employer"], "bundle": scenario["bundle"],
        "advocate": advocate, "member": scenario["member"], "clinic": clinic,
        "contract": scenario["contract"], "plan": plan, "first_cycle": cycle,
        "first_preauthorization": first, "second_preauthorization": second,
    }


class TestSurrenderRouteOverlap:
    """Route occupancy is extended by a storage-retention tail and refuses a touching start."""

    def test_route_touching_the_prior_routes_close_is_refused(self):
        """PRD §3.8: "it is refused when the requested route disagrees with an
        overlapping route already on file for the same member, reported as
        `ERR_SURRENDER_ROUTE_CONFLICT` with a 409 status."
        PRD §2.10: "the requested route must not disagree with an overlapping route
        already on file, refused with `ERR_SURRENDER_ROUTE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/surrender_route_overlap_adjacent_intervals_with_retention_extension
        """
        scenario = setup_route_scenario()
        member = scenario["member"]
        advocate = scenario["advocate"]

        current = validate_success(api_client.get_member(member["id"], NETWORK), 200)
        # The new window starts exactly where the prior route's own window closes, so
        # the raw intervals only abut. It is the retention tail the routed route
        # reserves that carries the occupied window out to 2026-10-31, and the carrier
        # kinds disagree, which is what makes the overlap a refusal.
        response = api_client.create_surrender_route(
            member["id"],
            create_surrender_route_payload(
                current["version"], pathway_type="PRESERVATION",
                carrier_kind="GESTATIONAL_CARRIER",
                route_from="2026-10-01T00:00:00Z", route_to="2026-11-01T00:00:00Z"),
            make_care_advocate_headers(advocate["id"]))

        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_SURRENDER_ROUTE_CONFLICT"
        # The member's own nested collection is the read the PRD opens to the widest
        # role set; the standing collection read is narrower.
        rows = validate_success(
            api_client.list_member_surrender_routes(
                member["id"], make_care_advocate_headers(advocate["id"])), 200)
        assert len(rows) == 1, "the refused route was never persisted"

    def test_route_admitted_once_the_retention_tail_has_closed(self):
        """PRD §3.8: "A survival note: a route that is currently `ROUTED` reserves the
        retention window it occupies, and a new treatment cycle that would fall inside
        that window is refused as a slot overlap under the rule in §3.6."
        PRD §3.8: "a routed route is retired by the advocate, also naming `route_id`, once
        the logical clock has reached the route's `route_to` plus the configured
        storage-retention interval"

        Design: Difficulty/resource_temporal_overlap/surrender_route_overlap_adjacent_intervals_with_retention_extension
        """
        scenario = setup_route_scenario()
        member = scenario["member"]
        advocate = scenario["advocate"]
        assert scenario["route"]["route_status"] == "ROUTED"

        current = validate_success(api_client.get_member(member["id"], NETWORK), 200)
        admitted = validate_success(api_client.create_surrender_route(
            member["id"],
            create_surrender_route_payload(
                current["version"], pathway_type="PRESERVATION", carrier_kind="GESTATIONAL_CARRIER",
                route_from="2026-11-30T00:00:00Z", route_to="2026-12-31T00:00:00Z"),
            make_care_advocate_headers(advocate["id"])), 200)

        assert admitted["route_status"] == "SUBMITTED"
        rows = validate_success(
            api_client.list_member_surrender_routes(
                member["id"], make_care_advocate_headers(advocate["id"])), 200)
        assert len(rows) == 2

    def test_overlapping_route_with_a_disagreeing_carrier_kind_is_refused(self):
        """PRD §2.10: "the requested route must not disagree with an overlapping route
        already on file, refused with `ERR_SURRENDER_ROUTE_CONFLICT`."
        PRD §3.8: "a `carrier_kind` of `MEMBER`, `GESTATIONAL_CARRIER`, or `CUSTODIAN`, an
        inclusive `route_from` and an exclusive `route_to` marking the occupancy window"

        Design: Corner/errors/surrogacy_route_conflict_on_disagreeing_overlapping_carrier_kind
        """
        employer, bundle = setup_employer_bundle()
        advocate = create_advocate(specializations=["STANDARD_IVF"])
        member = create_member(employer["id"], advocate=advocate,
                               member_overrides={"external_ref": "CONFLICT-1"})
        holder = setup_surrender_route(
            member, advocate, pathway_type="PRESERVATION", carrier_kind="CUSTODIAN",
            route_from="2026-09-01T00:00:00Z", route_to="2026-10-01T00:00:00Z")
        assert holder["carrier_kind"] == "CUSTODIAN"
        assert holder["route_status"] == "SUBMITTED"

        current = validate_success(api_client.get_member(member["id"], NETWORK), 200)
        response = api_client.create_surrender_route(
            member["id"],
            create_surrender_route_payload(
                current["version"], pathway_type="SURROGACY",
                carrier_kind="GESTATIONAL_CARRIER",
                route_from="2026-09-15T00:00:00Z", route_to="2026-11-15T00:00:00Z"),
            make_care_advocate_headers(advocate["id"]))

        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_SURRENDER_ROUTE_CONFLICT"
        # The member's own nested collection is the read the PRD opens to the widest
        # role set; the standing collection read is narrower.
        rows = validate_success(
            api_client.list_member_surrender_routes(
                member["id"], make_care_advocate_headers(advocate["id"])), 200)
        assert len(rows) == 1, "the refused route was never persisted"
        member_after = validate_success(api_client.get_member(member["id"], NETWORK), 200)
        assert member_after["version"] == current["version"], (
            "the refusal advanced the member's version by nothing"
        )

    def test_same_carrier_kind_on_a_disjoint_interval_is_admitted(self):
        """PRD §3.8: "It is filed by a `CareAdvocate` against the member with the
        `pathway_type` it belongs to, a `carrier_kind` of `MEMBER`, `GESTATIONAL_CARRIER`,
        or `CUSTODIAN`, an inclusive `route_from` and an exclusive `route_to` marking the
        occupancy window"

        Design: Corner/errors/surrogacy_route_conflict_on_disagreeing_overlapping_carrier_kind
        """
        employer, bundle = setup_employer_bundle()
        advocate = create_advocate(specializations=["STANDARD_IVF"])
        member = create_member(employer["id"], advocate=advocate,
                               member_overrides={"external_ref": "CONFLICT-2"})
        setup_surrender_route(
            member, advocate, pathway_type="PRESERVATION", carrier_kind="CUSTODIAN",
            route_from="2026-09-01T00:00:00Z", route_to="2026-10-01T00:00:00Z")

        current = validate_success(api_client.get_member(member["id"], NETWORK), 200)
        admitted = validate_success(api_client.create_surrender_route(
            member["id"],
            create_surrender_route_payload(
                current["version"], pathway_type="PRESERVATION", carrier_kind="GESTATIONAL_CARRIER",
                route_from="2026-11-15T00:00:00Z", route_to="2026-12-15T00:00:00Z"),
            make_care_advocate_headers(advocate["id"])), 200)

        assert admitted["route_status"] == "SUBMITTED"
        # PRD section 2.6 declares the instant format: ISO 8601 UTC with three
        # fractional digits, so the value is compared as an instant.
        assert is_iso8601_timestamp(admitted["route_to"])
        assert admitted["route_to"].startswith("2026-12-15T00:00:00")
        rows = validate_success(
            api_client.list_member_surrender_routes(
                member["id"], make_care_advocate_headers(advocate["id"])), 200)
        assert len(rows) == 2
        member_after = validate_success(api_client.get_member(member["id"], NETWORK), 200)
        assert member_after["version"] > current["version"]


def setup_route_scenario() -> dict:
    """A member in routed-pathway custody with one route occupying September."""
    employer, bundle = setup_employer_bundle(allocation_method="CONCURRENT_BUNDLE")
    advocate = create_advocate(specializations=["STANDARD_IVF"])
    member = create_member(employer["id"], advocate=advocate,
                           member_overrides={"external_ref": "ROUTE-1"})
    route = setup_routed_surrender_route(
        member, advocate, pathway_type="PRESERVATION", carrier_kind="CUSTODIAN",
        route_from="2026-09-01T00:00:00Z", route_to="2026-10-01T00:00:00Z")
    return {"employer": employer, "advocate": advocate, "member": member, "route": route}


class TestAdvocateGateOnIntake:
    """Intake closes only while the assigned advocate is neither at capacity nor lapsed."""

    def test_complete_intake_refused_at_the_capacity_arm_of_the_gate(self):
        """PRD §3.2: "that the assigned advocate reads `ACTIVE` or `AT_CAPACITY`, and that
        the logical clock is still before the advocate's `credentials_expire_on`."
        PRD §2.10: "the acting advocate's credential must be unexpired and the advocate
        must not have reached their caseload ceiling — refused with
        `ERR_ADVOCATE_CREDENTIAL_LAPSED`"

        Design: Difficulty/cross_entity_state_dependency/member_intake_gate_on_advocate_credential_and_capacity
        """
        scenario = setup_advocate_at_capacity()
        second = scenario["pending_member"]
        advocate = scenario["advocate"]

        assert scenario["seated_member"]["member_status"] == "CARE_ACTIVE"
        advocate_now = validate_success(
            api_client.get_care_advocate(advocate["id"], NETWORK), 200)
        assert advocate_now["current_caseload"] == 1
        assert advocate_now["advocate_status"] == "AT_CAPACITY"

        response = api_client.complete_intake(
            second["id"], make_care_advocate_headers(advocate["id"]))

        assert response.status_code == 422
        assert response.json()["data"]["error_id"] == "ERR_ADVOCATE_CREDENTIAL_LAPSED"
        unchanged = validate_success(api_client.get_member(second["id"], NETWORK), 200)
        assert unchanged["member_status"] == "INTAKE"
        assert unchanged["intake_completed_at"] is None

    def test_complete_intake_refused_at_the_lapsed_credential_arm(self):
        """PRD §3.2: "Closing intake requires that the member is still in `INTAKE`, that
        a guide has actually been assigned — a member cannot complete intake before an
        advocate is on the record — that the assigned advocate reads `ACTIVE` or
        `AT_CAPACITY`, and that the logical clock is still before the advocate's
        `credentials_expire_on`."
        PRD §3.2: "`INACTIVE` once their credential has lapsed, and `ACTIVE` otherwise."

        Design: Difficulty/cross_entity_state_dependency/member_intake_gate_on_advocate_credential_and_capacity
        """
        scenario = setup_advocate_at_capacity()
        second = scenario["pending_member"]
        advocate = scenario["advocate"]

        setup_clock("2026-11-01T00:00:00Z")  # past the credential's lapse instant
        advocate_after = validate_success(
            api_client.get_care_advocate(advocate["id"], NETWORK), 200)
        assert advocate_after["advocate_status"] == "INACTIVE"

        response = api_client.complete_intake(
            second["id"], make_care_advocate_headers(advocate["id"]))

        assert response.status_code == 422
        assert response.json()["data"]["error_id"] == "ERR_ADVOCATE_CREDENTIAL_LAPSED"
        unchanged = validate_success(api_client.get_member(second["id"], NETWORK), 200)
        assert unchanged["member_status"] == "INTAKE"


def setup_advocate_at_capacity() -> dict:
    """An advocate whose one-member caseload ceiling is already reached, with a second
    member assigned and still in intake, and a credential that lapses in October."""
    setup_clock()
    employer = create_employer()
    advocate = create_advocate(caseload_limit=1, credentials_expire_on="2026-10-01T00:00:00Z")
    seated = create_member(employer["id"], advocate=advocate,
                           member_overrides={"external_ref": "CAP-1"})
    pending = create_member(employer["id"], assign_advocate=True, complete_intake=False,
                            member_overrides={"external_ref": "CAP-2"})
    return {"employer": employer, "advocate": advocate,
            "seated_member": seated, "pending_member": pending}


class TestClinicSelectionGatedOnContractState:
    """A plan leaves PLAN_DRAFT only while the named clinic is genuinely contracted."""

    def test_select_clinic_refused_while_the_clinic_is_still_in_review(self):
        """PRD §3.4: "The clinic named must read `CONTRACTED`, must hold a contract whose
        status is `ACTIVE` and whose interval covers the logical clock, and that contract
        must carry a negotiated rate for the member's bundle type — a clinic that fails
        any of those three is refused with `ERR_CLINIC_NOT_CONTRACTED`."

        Design: Difficulty/cross_entity_state_dependency/plan_clinic_selection_gated_on_clinic_contract_state
        """
        scenario = setup_member_plan_clinic(select_clinic=False)
        plan = scenario["plan"]
        advocate = scenario["advocate"]
        untendered = create_clinic(min_live_birth_rate_bps=0)
        member_now = validate_success(api_client.get_member(plan["member_id"], NETWORK), 200)

        response = api_client.select_plan_clinic(
            plan["id"],
            {"clinic_id": untendered["id"], "expected_member_version": member_now["version"]},
            make_care_advocate_headers(advocate["id"]))

        assert response.status_code == 422
        assert response.json()["data"]["error_id"] == "ERR_CLINIC_NOT_CONTRACTED"
        unchanged = validate_success(api_client.get_treatment_plan(plan["id"], NETWORK), 200)
        assert unchanged["plan_status"] == "PLAN_DRAFT"
        assert unchanged["clinic_id"] is None

    def test_select_clinic_admitted_once_the_contract_is_active(self):
        """PRD §3.4: "On success the plan records the clinic, moves to `CLINIC_SELECTED`,
        snapshots the negotiated rate into `selected_bundle_price_cents` so that the
        plan's price is pinned at the rate that was in force when the clinic was chosen,
        and mirrors the same clinic onto the member's own `clinic_id`, advancing the
        member's `version`."

        Design: Difficulty/cross_entity_state_dependency/plan_clinic_selection_gated_on_clinic_contract_state
        """
        scenario = setup_member_plan_clinic(rate=1196000, select_clinic=False)
        plan = scenario["plan"]
        advocate = scenario["advocate"]
        clinic = scenario["clinic"]

        member_before = validate_success(api_client.get_member(plan["member_id"], NETWORK), 200)
        selected = validate_success(api_client.select_plan_clinic(
            plan["id"],
            {"clinic_id": clinic["id"], "expected_member_version": member_before["version"]},
            make_care_advocate_headers(advocate["id"])), 200)

        assert selected["plan_status"] == "CLINIC_SELECTED"
        assert selected["clinic_id"] == clinic["id"]
        member_after = validate_success(api_client.get_member(plan["member_id"], NETWORK), 200)
        assert member_after["clinic_id"] == clinic["id"]
        assert member_after["version"] > member_before["version"]


class TestListingDiscoveryChannels:
    """The filtered collections are the reverse-reachability channels."""

    def test_clinic_contract_list_partitions_by_contracting_status(self):
        """PRD §3.4: "Read-side, clinics may be filtered by `state_code`, `network_tier`,
        `clinic_status`, `bundle_type`, and `min_composite_quality_bps`, and contracts by
        `clinic_id` and `contracting_status`."

        Design: Corner/endpoints/clinic_contract_list_filters_by_status_and_reports_pagination
        """
        from test_helpers import create_clinic, create_clinic_contract_payload, create_contract

        clinic = create_clinic()
        pending = validate_success(api_client.create_clinic_contract(
            clinic["id"], create_clinic_contract_payload(), make_network_manager_headers("nm-list")), 201)
        assert pending["contracting_status"] == "IN_REVIEW"
        assert pending["frozen_reason"] is None

        rows = validate_success(
            api_client.list_clinic_contracts(NETWORK, {"clinic_id": clinic["id"]}), 200)
        assert len(rows) == 1

        empty = validate_success(api_client.list_clinic_contracts(
            NETWORK, {"clinic_id": clinic["id"], "contracting_status": "ACTIVE"}), 200)
        assert empty == [], "an IN_REVIEW contract does not appear under ACTIVE"

        clinic_now = validate_success(api_client.get_clinic(clinic["id"], NETWORK), 200)
        active = validate_success(api_client.activate_clinic_contract(
            pending["id"], {"expected_clinic_version": clinic_now["version"]}, NETWORK), 200)
        assert active["contracting_status"] == "ACTIVE"
        clinic_after = validate_success(api_client.get_clinic(clinic["id"], NETWORK), 200)
        assert clinic_after["clinic_status"] == "CONTRACTED"

        present = validate_success(api_client.list_clinic_contracts(
            NETWORK, {"clinic_id": clinic["id"], "contracting_status": "ACTIVE"}), 200)
        assert len(present) == 1

    def test_nested_surrender_route_collection_returns_the_child_array(self):
        """PRD §3.8: "Routes belonging to one member may be listed beneath that member,
        and the full collection accepts `member_id`, `pathway_type`, `carrier_kind`, and
        `route_status` as filters."

        Design: Corner/endpoints/members_id_surrender_routes_returns_the_child_array
        """
        from test_helpers import validate_paginated

        employer, bundle = setup_employer_bundle()
        advocate, member = setup_advocate_and_member(employer)
        setup_surrender_route(member, advocate)

        data, meta = validate_paginated(api_client.list_member_surrender_routes(
            member["id"], make_member_headers(member["id"])))
        assert len(data) == 1
        assert meta["total_count"] == 1
        assert data[0]["pathway_type"] == "PRESERVATION"
        assert data[0]["carrier_kind"] == "CUSTODIAN"
        assert data[0]["route_status"] == "SUBMITTED"
        assert data[0]["member_id"] == member["id"]

        routed_before, _ = validate_paginated(api_client.list_surrender_routes(
            NETWORK, {"route_status": "ROUTED"}))
        assert routed_before == [], "no route has routed before the clock sweeps"

        tick_clock()
        routed_after, routed_meta = validate_paginated(
            api_client.list_member_surrender_routes(
                member["id"], make_member_headers(member["id"]), {"route_status": "ROUTED"}))
        assert routed_meta["total_count"] == 1
        assert routed_after[0]["route_status"] == "ROUTED"


def setup_advocate_and_member(employer, **kwargs):
    from test_helpers import setup_advocate_and_member as _impl
    return _impl(employer, **kwargs)