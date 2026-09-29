"""Reachability of the declared error catalogue: not-found codes, malformed
bodies, state gates, report-lifecycle conflicts, licence-scope refusals,
station and reinstatement refusals, permit windows and renewal state.
"""

import pytest

from test_helpers import (
    ACTIVITY_NONE,
    AMENDMENT_CLERICAL_CORRECTION,
    BOND_LAPSED,
    BOND_TERMINATED,
    CONDUCIVE_WOOD_TO_GROUND,
    CONSTRUCTION_BASEMENT,
    CONSTRUCTION_CRAWLSPACE,
    ERR_AMENDMENT_WINDOW_CLOSED,
    ERR_APPLICATION_BEFORE_PERMIT_WINDOW,
    ERR_BAIT_STATION_NOT_FOUND,
    ERR_BOND_NOT_FOUND,
    ERR_BOND_RENEWAL_NOT_FOUND,
    ERR_CATEGORY_NOT_LICENSED,
    ERR_CLOSING_LEAD_TIME_MISSED,
    ERR_DAMAGE_CLAIM_NOT_FOUND,
    ERR_FIELD_COMBINATION_INVALID,
    ERR_FORM_CODE_MISMATCH,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INSPECTION_NOT_GRAPHED,
    ERR_INSPECTION_PURPOSE_MISMATCH,
    ERR_INSPECTOR_NOT_FOUND,
    ERR_INVALID_BOND_STATE,
    ERR_INVALID_INSPECTION_STATE,
    ERR_INVALID_INSPECTOR_STATE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_PLAN_STATE,
    ERR_INVALID_RENEWAL_STATE,
    ERR_INVALID_REPORT_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATION_STATE,
    ERR_LICENSE_STATE_MISMATCH,
    ERR_METHOD_NOT_PERMITTED,
    ERR_PRODUCT_METHOD_INCOMPATIBLE,
    ERR_PROPERTY_MISMATCH,
    ERR_PROPERTY_NOT_FOUND,
    ERR_REINSTATEMENT_INSPECTION_STALE,
    ERR_REINSTATEMENT_PAYMENT_INSUFFICIENT,
    ERR_REINSTATEMENT_WINDOW_EXPIRED,
    ERR_SERVICE_TIME_INVALID,
    ERR_TREATMENT_PLAN_NOT_FOUND,
    ERR_WDO_REPORT_NOT_FOUND,
    FINDING_ACTIVE_INFESTATION,
    FINDING_CONDUCIVE_CONDITION,
    FINDING_DAMAGE,
    FORM_GA_100,
    INSPECTION_GRAPHED,
    LICENSE_STATUS_ACTIVE,
    MANAGER_HEADERS,
    METHOD_LIQUID_BARRIER,
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    PLAN_APPROVED,
    PLAN_COMPLETED,
    PRODUCT_HEXA_BAIT_2,
    PURPOSE_INITIAL,
    PURPOSE_REAL_ESTATE,
    RENEWAL_PAID,
    RENEWAL_PENDING,
    REPORT_ISSUED,
    STATION_INSTALLED,
    STATION_REMOVED,
    TIER_RETREAT_ONLY,
    amendment_payload,
    application_payload,
    applicator_only_inspector_payload,
    approve_plan,
    approved_plan,
    assert_instant_equals,
    assert_money,
    assert_page,
    assert_status,
    assert_version,
    attested_graph_complete_payload,
    bonded_property,
    complete_renewal,
    completed_bait_plan,
    finding_payload,
    fumigation_inspector_payload,
    fumigation_plan_payload,
    get_success_data,
    graphed_inspection,
    inspection_payload,
    issue_bond,
    issue_wdo_report,
    license_status_payload,
    list_stations,
    make_applicator_headers,
    make_field_inspector_headers,
    next_license_number,
    open_graph,
    open_renewal,
    open_wdo_report,
    propose_plan,
    record_application,
    register_inspector,
    register_property,
    register_property_and_inspector,
    reinstatement_graph,
    reinstatement_payload,
    renewal_completion_payload,
    renewal_graph,
    review_bond_term,
    set_clock,
    sign_empty_graph,
    station_service_payload,
    treatment_plan_payload,
    validate_error,
    validate_success,
    wdo_report_payload,
)

# The nine typed path segments of the endpoint table, each with the not-found
# code its own type reports.
NOT_FOUND_READS = [
    ("get_property", ERR_PROPERTY_NOT_FOUND),
    ("get_inspector", ERR_INSPECTOR_NOT_FOUND),
    ("get_inspection", ERR_INSPECTION_NOT_FOUND),
    ("get_treatment_plan", ERR_TREATMENT_PLAN_NOT_FOUND),
    ("get_bond", ERR_BOND_NOT_FOUND),
    ("get_renewal", ERR_BOND_RENEWAL_NOT_FOUND),
    ("get_wdo_report", ERR_WDO_REPORT_NOT_FOUND),
    ("get_bait_station", ERR_BAIT_STATION_NOT_FOUND),
    ("get_damage_claim", ERR_DAMAGE_CLAIM_NOT_FOUND),
]


class TestNotFoundCodesAreEachReachable:
    """Every declared not-found code is reachable by path id and by body reference."""

    @pytest.mark.parametrize("method_name,expected_error", NOT_FOUND_READS)
    def test_each_typed_path_segment_reports_its_own_not_found_code(
        self, api, method_name, expected_error
    ):
        """An unresolvable path id reports the not-found code of its own type.

        PRD 2.6 stage 4: "Every identifier segment in the request path resolves
        to a persisted row of that segment's type, validated left to right; the
        leftmost segment that fails to resolve reports its own type's not-found
        code ... all at HTTP 404."

        Design: Corner/errors/every_declared_not_found_code_is_reachable_by_id_and_by_body_reference
        """
        response = getattr(api, method_name)(NON_EXISTENT_UUID, OFFICER_HEADERS)
        validate_error(response, expected_error, 404)

    def test_an_unknown_body_reference_reports_the_first_declared_reference(
        self, api
    ):
        """A body carrying several unknown references reports the first one.

        PRD 2.6 stage 8: "Every identifier carried in a request body resolves to
        a persisted row: `property_id`, `inspector_id`,
        `supersedes_inspection_id`, `inspection_id`, `treatment_plan_id`,
        `bond_id`, `verifying_inspection_id` and `reinstatement_inspection_id`.
        The applicable not-found code is reported at HTTP 404."

        Design: Corner/errors/every_declared_not_found_code_is_reachable_by_id_and_by_body_reference
        """
        inspector = register_inspector(api)
        payload = treatment_plan_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, inspector["id"]
        )
        response = api.create_treatment_plan(payload, MANAGER_HEADERS)
        validate_error(response, ERR_PROPERTY_NOT_FOUND, 404)

    def test_a_resolvable_property_exposes_the_unknown_graph_reference(self, api):
        """With the structure resolved, the unknown graph reference surfaces.

        PRD 2.6 stage 8: "Every identifier carried in a request body resolves to
        a persisted row: `property_id`, `inspector_id`,
        `supersedes_inspection_id`, `inspection_id`, `treatment_plan_id`,
        `bond_id`, `verifying_inspection_id` and `reinstatement_inspection_id`."

        Design: Corner/errors/every_declared_not_found_code_is_reachable_by_id_and_by_body_reference
        """
        prop, inspector = register_property_and_inspector(api)
        payload = treatment_plan_payload(
            prop["id"], NON_EXISTENT_UUID, inspector["id"]
        )
        response = api.create_treatment_plan(payload, MANAGER_HEADERS)
        validate_error(response, ERR_INSPECTION_NOT_FOUND, 404)

    def test_every_error_body_carries_an_identifier_and_a_message(self, api):
        """A refusal body names the code and explains itself.

        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/errors/every_declared_not_found_code_is_reachable_by_id_and_by_body_reference
        """
        response = api.get_bond(NON_EXISTENT_UUID, OFFICER_HEADERS)
        error = validate_error(response, ERR_BOND_NOT_FOUND, 404)
        assert error["error_id"] == ERR_BOND_NOT_FOUND
        assert error["message"].strip()


def _structure_and_draft_graph(api):
    """One FL slab structure, one FL licensee and one DRAFT graph on it."""
    prop, inspector = register_property_and_inspector(
        api,
        address_line1="9 Marsh Lane",
        square_footage=1800,
        linear_footage=160,
        year_built=2001,
    )
    graph = open_graph(api, prop["id"], inspector["id"])
    return prop, inspector, graph


class TestMalformedBodiesAreRejectedFirst:
    """Shape and cross-field failures are reported before any row is touched."""

    def test_an_undeclared_enum_member_is_a_shape_failure(self, api):
        """A purpose outside the declared set fails the shape stage.

        PRD 2.6 stage 5: "every enumerated field holds a declared member ... Any
        failure is `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/malformed_bodies_are_rejected_before_any_state_or_reference_is_touched
        """
        prop, inspector, _ = _structure_and_draft_graph(api)
        payload = inspection_payload(
            prop["id"],
            inspector["id"],
            purpose="MONTHLY",
            scheduled_start_at="2026-08-02T09:00:00Z",
            scheduled_end_at="2026-08-02T12:00:00Z",
        )
        response = api.create_inspection(
            payload, make_field_inspector_headers(inspector["id"])
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

    def test_a_real_estate_graph_without_a_closing_date_is_a_cross_field_failure(
        self, api
    ):
        """A real-estate visit must declare the closing it is filed for.

        PRD 2.6 stage 6: "`closing_date` present exactly when `purpose` is
        `REAL_ESTATE` and null otherwise ... Any failure is
        `ERR_FIELD_COMBINATION_INVALID` (422)."

        Design: Corner/errors/malformed_bodies_are_rejected_before_any_state_or_reference_is_touched
        """
        prop, inspector, _ = _structure_and_draft_graph(api)
        payload = inspection_payload(
            prop["id"],
            inspector["id"],
            purpose=PURPOSE_REAL_ESTATE,
            scheduled_start_at="2026-08-02T09:00:00Z",
            scheduled_end_at="2026-08-02T12:00:00Z",
        )
        response = api.create_inspection(
            payload, make_field_inspector_headers(inspector["id"])
        )
        validate_error(response, ERR_FIELD_COMBINATION_INVALID, 422)

    def test_a_closing_date_on_a_routine_graph_is_a_cross_field_failure(self, api):
        """The same rule bites from the other side on a non-real-estate visit.

        PRD 2.6 stage 6: "`closing_date` present exactly when `purpose` is
        `REAL_ESTATE` and null otherwise ... Any failure is
        `ERR_FIELD_COMBINATION_INVALID` (422)."

        Design: Corner/errors/malformed_bodies_are_rejected_before_any_state_or_reference_is_touched
        """
        prop, inspector, _ = _structure_and_draft_graph(api)
        payload = inspection_payload(
            prop["id"],
            inspector["id"],
            purpose=PURPOSE_INITIAL,
            closing_date="2026-08-20",
            scheduled_start_at="2026-08-02T09:00:00Z",
            scheduled_end_at="2026-08-02T12:00:00Z",
        )
        response = api.create_inspection(
            payload, make_field_inspector_headers(inspector["id"])
        )
        validate_error(response, ERR_FIELD_COMBINATION_INVALID, 422)

    def test_a_zero_length_diary_occupation_is_a_cross_field_failure(self, api):
        """A visit that ends when it begins occupies no interval at all.

        PRD 2.6 stage 6: "`scheduled_end_at` strictly after
        `scheduled_start_at` ... Any failure is `ERR_FIELD_COMBINATION_INVALID`
        (422)."

        Design: Corner/errors/malformed_bodies_are_rejected_before_any_state_or_reference_is_touched
        """
        prop, inspector, _ = _structure_and_draft_graph(api)
        payload = inspection_payload(
            prop["id"],
            inspector["id"],
            scheduled_start_at="2026-08-02T09:00:00Z",
            scheduled_end_at="2026-08-02T09:00:00Z",
        )
        response = api.create_inspection(
            payload, make_field_inspector_headers(inspector["id"])
        )
        validate_error(response, ERR_FIELD_COMBINATION_INVALID, 422)

    def test_a_cell_outside_the_printed_grid_is_a_shape_failure(self, api):
        """The printed graph stops at column J, so K1 is not a cell.

        PRD 2.6 stage 5: "a `grid_ref` is a single column letter from `A`
        through `J` immediately followed by a row number from 1 through 10 ...
        Any failure is `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/malformed_bodies_are_rejected_before_any_state_or_reference_is_touched
        """
        _, inspector, graph = _structure_and_draft_graph(api)
        response = api.create_finding(
            graph["id"],
            finding_payload(FINDING_ACTIVE_INFESTATION, "K1"),
            make_field_inspector_headers(inspector["id"]),
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

    def test_damage_with_a_zero_estimate_is_a_cross_field_failure(self, api):
        """A damage notation that costs nothing is not a damage notation.

        PRD 2.6 stage 6: "`damage_estimate_usd` greater than zero exactly when
        `finding_type` is `DAMAGE` ... Any failure is
        `ERR_FIELD_COMBINATION_INVALID` (422)."

        Design: Corner/errors/malformed_bodies_are_rejected_before_any_state_or_reference_is_touched
        """
        _, inspector, graph = _structure_and_draft_graph(api)
        response = api.create_finding(
            graph["id"],
            finding_payload(FINDING_DAMAGE, "C4", damage_estimate_usd=0.00),
            make_field_inspector_headers(inspector["id"]),
        )
        validate_error(response, ERR_FIELD_COMBINATION_INVALID, 422)

    @pytest.mark.parametrize(
        "query", [{"limit": 0}, {"limit": 101}, {"offset": -1}]
    )
    def test_pagination_bounds_are_rejected_at_the_pagination_stage(self, api, query):
        """Page size and starting position have declared bounds.

        PRD 2.3: "When `limit` falls outside the range 1 through 100, or
        `offset` is negative, or either value is not an integer, the read is
        rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/errors/malformed_bodies_are_rejected_before_any_state_or_reference_is_touched
        """
        _structure_and_draft_graph(api)
        response = api.list_inspections(OFFICER_HEADERS, params=query)
        validate_error(response, ERR_INVALID_PAGINATION, 400)

    def test_none_of_the_refused_writes_left_a_row_behind(self, api):
        """A refused write is not a partially applied write.

        PRD 2.6: "The checks below are evaluated in exactly this order, and the
        first violated check determines the response. No later check is
        evaluated once one has failed."

        Design: Corner/errors/malformed_bodies_are_rejected_before_any_state_or_reference_is_touched
        """
        prop, inspector, graph = _structure_and_draft_graph(api)
        headers = make_field_inspector_headers(inspector["id"])
        api.create_inspection(
            inspection_payload(
                prop["id"],
                inspector["id"],
                purpose="MONTHLY",
                scheduled_start_at="2026-08-02T09:00:00Z",
                scheduled_end_at="2026-08-02T12:00:00Z",
            ),
            headers,
        )
        api.create_finding(
            graph["id"], finding_payload(FINDING_ACTIVE_INFESTATION, "K1"), headers
        )
        api.create_finding(
            graph["id"],
            finding_payload(FINDING_DAMAGE, "C4", damage_estimate_usd=0.00),
            headers,
        )
        assert_page(api.list_inspections(OFFICER_HEADERS), 1)
        assert_page(api.list_findings(graph["id"], OFFICER_HEADERS), 0)


class TestStateGatesNameTheWrongEntity:
    """A wrong start state is refused with the code of the entity that is wrong."""

    def test_reasserting_an_active_licence_is_an_inspector_state_conflict(self, api):
        """ACTIVE to ACTIVE is not one of the four declared licence moves.

        PRD 3.2: "Any other pairing — a second `ACTIVE → ACTIVE` request, a move
        from `SUSPENDED` straight to `EXPIRED` — is not a declared transition and
        is refused with `ERR_INVALID_INSPECTOR_STATE`."

        Design: Corner/errors/state_gate_rejects_a_wrong_start_state_for_licence_inspection_and_plan
        """
        inspector = register_inspector(api)
        response = api.set_license_status(
            inspector["id"],
            license_status_payload(LICENSE_STATUS_ACTIVE),
            OFFICER_HEADERS,
        )
        validate_error(response, ERR_INVALID_INSPECTOR_STATE, 409)

    def test_a_signed_graph_refuses_a_further_notation(self, api):
        """Cell notations belong to a draft, never to a signed graph.

        PRD 3.3: "Cell notations are added one at a time to a graph while it is
        still `DRAFT`; adding one to a graph in any other status is
        `ERR_INVALID_INSPECTION_STATE`."

        Design: Corner/errors/state_gate_rejects_a_wrong_start_state_for_licence_inspection_and_plan
        """
        prop, inspector = register_property_and_inspector(api)
        graph = graphed_inspection(api, prop["id"], inspector["id"])
        assert_status(graph, INSPECTION_GRAPHED, "inspection")
        response = api.create_finding(
            graph["id"],
            finding_payload(
                FINDING_CONDUCIVE_CONDITION,
                "B2",
                conducive_code=CONDUCIVE_WOOD_TO_GROUND,
            ),
            make_field_inspector_headers(inspector["id"]),
        )
        validate_error(response, ERR_INVALID_INSPECTION_STATE, 409)

    def test_a_signed_graph_refuses_a_second_signature(self, api):
        """Signing consumes the draft, so there is nothing left to sign.

        PRD 2.6 stage 10: "The row named by the path is in a status from which
        the requested transition is declared. Signing a graph requires a `DRAFT`
        graph ... The code names the entity whose state is wrong ...
        `ERR_INVALID_INSPECTION_STATE`."

        Design: Corner/errors/state_gate_rejects_a_wrong_start_state_for_licence_inspection_and_plan
        """
        prop, inspector = register_property_and_inspector(api)
        graph = graphed_inspection(api, prop["id"], inspector["id"])
        response = api.graph_complete(
            graph["id"],
            {"no_findings_attested": True},
            make_field_inspector_headers(inspector["id"]),
        )
        validate_error(response, ERR_INVALID_INSPECTION_STATE, 409)

    def test_a_proposed_plan_refuses_a_pesticide_application(self, api):
        """Chemical may only be discharged against an authorised plan.

        PRD 3.6: "The plan must be `APPROVED`; recording against a plan in any
        other status is `ERR_INVALID_PLAN_STATE`."

        Design: Corner/errors/state_gate_rejects_a_wrong_start_state_for_licence_inspection_and_plan
        """
        prop, inspector = register_property_and_inspector(api)
        graph = graphed_inspection(api, prop["id"], inspector["id"])
        plan = propose_plan(api, prop["id"], graph["id"], inspector["id"])
        response = api.create_application(
            plan["id"],
            application_payload(plan["version"]),
            make_applicator_headers(inspector["id"]),
        )
        validate_error(response, ERR_INVALID_PLAN_STATE, 409)

    def test_an_approved_plan_refuses_a_second_approval(self, api):
        """Approval consumes the proposal, so it cannot run twice.

        PRD 3.6: "Approving a plan that is not `PROPOSED` is
        `ERR_INVALID_PLAN_STATE`."

        Design: Corner/errors/state_gate_rejects_a_wrong_start_state_for_licence_inspection_and_plan
        """
        prop, inspector = register_property_and_inspector(api)
        graph = graphed_inspection(api, prop["id"], inspector["id"])
        plan = approved_plan(api, prop["id"], graph["id"], inspector["id"])
        assert_status(plan, PLAN_APPROVED, "treatment plan")
        response = api.approve_treatment_plan(plan["id"], {}, MANAGER_HEADERS)
        validate_error(response, ERR_INVALID_PLAN_STATE, 409)

    def test_no_refused_state_gate_advanced_a_version(self, api):
        """A refusal is not a write, so no counter moves.

        PRD 2.4: "`version`, an integer that starts at 1 when the row is created
        and increases by exactly 1 on every mutation of that row."

        Design: Corner/errors/state_gate_rejects_a_wrong_start_state_for_licence_inspection_and_plan
        """
        prop, inspector = register_property_and_inspector(api)
        graph = graphed_inspection(api, prop["id"], inspector["id"])
        plan = approved_plan(api, prop["id"], graph["id"], inspector["id"])
        inspector_version = get_success_data(
            api.get_inspector(inspector["id"], OFFICER_HEADERS)
        )["version"]
        graph_version = graph["version"]
        plan_version = plan["version"]

        api.set_license_status(
            inspector["id"],
            license_status_payload(LICENSE_STATUS_ACTIVE),
            OFFICER_HEADERS,
        )
        api.graph_complete(
            graph["id"],
            {"no_findings_attested": True},
            make_field_inspector_headers(inspector["id"]),
        )
        api.approve_treatment_plan(plan["id"], {}, MANAGER_HEADERS)

        assert_version(
            get_success_data(api.get_inspector(inspector["id"], OFFICER_HEADERS)),
            inspector_version,
            "inspector",
        )
        assert_version(
            get_success_data(api.get_inspection(graph["id"], OFFICER_HEADERS)),
            graph_version,
            "inspection",
        )
        assert_version(
            get_success_data(api.get_treatment_plan(plan["id"], OFFICER_HEADERS)),
            plan_version,
            "treatment plan",
        )


CLOSING_DATE = "2026-08-20"
LEAD_DEADLINE = "2026-08-19T00:00:00Z"


def _pending_sale_and_routine_graph(api):
    """A DRAFT real-estate graph plus a signed routine graph on one structure."""
    prop, inspector = register_property_and_inspector(api)
    pending = open_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_REAL_ESTATE,
        closing_date=CLOSING_DATE,
    )
    routine = graphed_inspection(api, prop["id"], inspector["id"])
    return prop, inspector, pending, routine


class TestWdoReportLifecycleConflicts:
    """The statutory filing lifecycle surfaces five distinct conflict codes."""

    def test_another_states_form_is_refused_at_creation(self, api):
        """A Florida structure may only be filed on the Florida form.

        PRD 2.10: "A report filed on any other state's form is not a compliant
        filing and is refused with `ERR_FORM_CODE_MISMATCH` (422)."

        Design: Corner/errors/wdo_report_lifecycle_surfaces_five_distinct_conflict_codes
        """
        _, _, pending, _ = _pending_sale_and_routine_graph(api)
        response = api.create_wdo_report(
            wdo_report_payload(pending["id"], form_code=FORM_GA_100), OFFICER_HEADERS
        )
        validate_error(response, ERR_FORM_CODE_MISMATCH, 422)
        assert_page(api.list_wdo_reports(OFFICER_HEADERS), 0)

    def test_issuing_against_an_unsigned_graph_is_refused(self, api):
        """A draft graph is not evidence, so nothing may be issued against it.

        PRD 3.4: "The underlying graph must be in status `GRAPHED` — a draft or
        superseded graph is not evidence, and offering one is
        `ERR_INSPECTION_NOT_GRAPHED`."

        Design: Corner/errors/wdo_report_lifecycle_surfaces_five_distinct_conflict_codes
        """
        _, _, pending, _ = _pending_sale_and_routine_graph(api)
        report = open_wdo_report(api, pending["id"])
        response = api.issue_wdo_report(report["id"], {}, OFFICER_HEADERS)
        validate_error(response, ERR_INSPECTION_NOT_GRAPHED, 409)

    def test_issuing_against_a_routine_graph_is_refused(self, api):
        """A signed graph of the wrong purpose still cannot support a filing.

        PRD 3.4: "its `purpose` must be `REAL_ESTATE`, or the attempt is
        `ERR_INSPECTION_PURPOSE_MISMATCH`."

        Design: Corner/errors/wdo_report_lifecycle_surfaces_five_distinct_conflict_codes
        """
        _, _, _, routine = _pending_sale_and_routine_graph(api)
        assert_status(routine, INSPECTION_GRAPHED, "inspection")
        report = open_wdo_report(api, routine["id"])
        response = api.issue_wdo_report(report["id"], {}, OFFICER_HEADERS)
        validate_error(response, ERR_INSPECTION_PURPOSE_MISMATCH, 422)

    def test_issuance_one_second_inside_the_final_day_is_refused(self, api):
        """The lead-time deadline is the last instant, not the first refused one.

        PRD 3.4: "taking the report's snapshotted `closing_date` at midnight UTC
        and subtracting 24 hours gives the latest instant at which a report may
        still be issued ... An attempt that would land inside the final 24 hours
        before closing is refused with `ERR_CLOSING_LEAD_TIME_MISSED` rather than
        issued late."

        Design: Corner/errors/wdo_report_lifecycle_surfaces_five_distinct_conflict_codes
        """
        _, inspector, pending, _ = _pending_sale_and_routine_graph(api)
        report = open_wdo_report(api, pending["id"])
        sign_empty_graph(api, pending["id"], inspector["id"])
        set_clock(api, "2026-08-19T00:00:01Z")
        response = api.issue_wdo_report(report["id"], {}, OFFICER_HEADERS)
        validate_error(response, ERR_CLOSING_LEAD_TIME_MISSED, 409)

    def test_issuance_exactly_on_the_lead_deadline_is_permitted(self, api):
        """Issuance is permitted at, not merely before, the deadline instant.

        PRD 3.4: "issuance is permitted when the clock instant is at or before
        that deadline."

        Design: Corner/errors/wdo_report_lifecycle_surfaces_five_distinct_conflict_codes
        """
        _, inspector, pending, _ = _pending_sale_and_routine_graph(api)
        report = open_wdo_report(api, pending["id"])
        sign_empty_graph(api, pending["id"], inspector["id"])
        set_clock(api, LEAD_DEADLINE)
        issued = validate_success(
            api.issue_wdo_report(report["id"], {}, OFFICER_HEADERS)
        )
        assert_status(issued, REPORT_ISSUED, "report")
        assert_instant_equals(issued["issued_at"], LEAD_DEADLINE)

    def test_reissuing_an_already_issued_report_is_refused(self, api):
        """Only a draft or an amended report may be issued.

        PRD 3.4: "Attempting to issue a report that is neither `DRAFT` nor
        `AMENDED`, or to amend one that is not `ISSUED`, or to touch one that is
        already `VOID`, is `ERR_INVALID_REPORT_STATE`."

        Design: Corner/errors/wdo_report_lifecycle_surfaces_five_distinct_conflict_codes
        """
        _, inspector, pending, _ = _pending_sale_and_routine_graph(api)
        report = open_wdo_report(api, pending["id"])
        sign_empty_graph(api, pending["id"], inspector["id"])
        set_clock(api, LEAD_DEADLINE)
        issue_wdo_report(api, report["id"])
        response = api.issue_wdo_report(report["id"], {}, OFFICER_HEADERS)
        validate_error(response, ERR_INVALID_REPORT_STATE, 409)

    def test_amending_one_day_past_the_window_is_refused(self, api):
        """The correction window closes 30 days after the current issuance date.

        PRD 3.4: "is only available while the clock's UTC date is no later than
        30 days after the date of the report's current `issued_at`; later
        attempts are `ERR_AMENDMENT_WINDOW_CLOSED`."

        Design: Corner/errors/wdo_report_lifecycle_surfaces_five_distinct_conflict_codes
        """
        _, inspector, pending, _ = _pending_sale_and_routine_graph(api)
        report = open_wdo_report(api, pending["id"])
        sign_empty_graph(api, pending["id"], inspector["id"])
        set_clock(api, LEAD_DEADLINE)
        issue_wdo_report(api, report["id"])
        set_clock(api, "2026-09-19T00:00:00Z")
        response = api.amend_wdo_report(
            report["id"],
            amendment_payload(AMENDMENT_CLERICAL_CORRECTION),
            OFFICER_HEADERS,
        )
        validate_error(response, ERR_AMENDMENT_WINDOW_CLOSED, 409)
        unchanged = get_success_data(api.get_wdo_report(report["id"], OFFICER_HEADERS))
        assert_status(unchanged, REPORT_ISSUED, "report")
        assert unchanged["amendment_count"] == 0


def _crawlspace_and_basement(api):
    """Two FL structures whose substructures admit different methods."""
    crawl = register_property(
        api,
        address_line1="12 Fern Hollow",
        construction_type=CONSTRUCTION_CRAWLSPACE,
        crawl_clearance_inches=22,
        square_footage=1800,
        linear_footage=160,
        year_built=1988,
    )
    basement = register_property(
        api,
        address_line1="18 Cypress Row",
        construction_type=CONSTRUCTION_BASEMENT,
        square_footage=1800,
        linear_footage=160,
        year_built=1979,
    )
    inspector = register_inspector(api)
    crawl_graph = graphed_inspection(api, crawl["id"], inspector["id"])
    basement_graph = graphed_inspection(api, basement["id"], inspector["id"])
    return crawl, basement, inspector, crawl_graph, basement_graph


class TestPlanCreationAndLicenceScopeCodes:
    """Method, product, structure and licence-scope refusals are each reachable."""

    def test_a_crawlspace_refuses_fumigation(self, api):
        """A vented crawlspace cannot hold fumigant, so the method is refused.

        PRD 3.5: "a crawlspace admits `LIQUID_BARRIER` and `BAIT_STATION` only,
        because a vented crawlspace cannot be sealed tightly enough to hold
        fumigant ... A method outside the structure's permitted set is
        `ERR_METHOD_NOT_PERMITTED`."

        Design: Corner/errors/plan_creation_and_licence_scope_codes_are_each_independently_triggerable
        """
        crawl, _, inspector, crawl_graph, _ = _crawlspace_and_basement(api)
        response = api.create_treatment_plan(
            fumigation_plan_payload(
                crawl["id"], crawl_graph["id"], inspector["id"]
            ),
            MANAGER_HEADERS,
        )
        validate_error(response, ERR_METHOD_NOT_PERMITTED, 422)

    def test_a_basement_refuses_a_liquid_barrier(self, api):
        """No continuous trench can be cut below a basement footing.

        PRD 3.5: "a basement admits `BAIT_STATION` and `FUMIGATION` only, because
        a continuous exterior trench cannot be cut below a basement footing ... A
        method outside the structure's permitted set is
        `ERR_METHOD_NOT_PERMITTED`."

        Design: Corner/errors/plan_creation_and_licence_scope_codes_are_each_independently_triggerable
        """
        _, basement, inspector, _, basement_graph = _crawlspace_and_basement(api)
        response = api.create_treatment_plan(
            treatment_plan_payload(
                basement["id"],
                basement_graph["id"],
                inspector["id"],
                method=METHOD_LIQUID_BARRIER,
            ),
            MANAGER_HEADERS,
        )
        validate_error(response, ERR_METHOD_NOT_PERMITTED, 422)

    def test_a_bait_cartridge_cannot_be_trenched_into_the_ground(self, api):
        """The chemical gate is separate from the physical one.

        PRD 3.5: "a `LIQUID_BARRIER` plan may only be loaded with `FIPRO_9` or
        `IMID_4`, a `BAIT_STATION` plan only with `HEXA_BAIT_2` ... a mismatch is
        `ERR_PRODUCT_METHOD_INCOMPATIBLE`."

        Design: Corner/errors/plan_creation_and_licence_scope_codes_are_each_independently_triggerable
        """
        crawl, _, inspector, crawl_graph, _ = _crawlspace_and_basement(api)
        response = api.create_treatment_plan(
            treatment_plan_payload(
                crawl["id"],
                crawl_graph["id"],
                inspector["id"],
                method=METHOD_LIQUID_BARRIER,
                chemical_product_code=PRODUCT_HEXA_BAIT_2,
            ),
            MANAGER_HEADERS,
        )
        validate_error(response, ERR_PRODUCT_METHOD_INCOMPATIBLE, 422)

    def test_a_graph_of_another_structure_cannot_justify_the_work(self, api):
        """The justifying graph must belong to the structure being treated.

        PRD 3.5: "The graph named must belong to the same structure as
        `property_id`, or the proposal is refused with `ERR_PROPERTY_MISMATCH`."

        Design: Corner/errors/plan_creation_and_licence_scope_codes_are_each_independently_triggerable
        """
        crawl, _, inspector, _, basement_graph = _crawlspace_and_basement(api)
        response = api.create_treatment_plan(
            treatment_plan_payload(
                crawl["id"],
                basement_graph["id"],
                inspector["id"],
                method=METHOD_LIQUID_BARRIER,
            ),
            MANAGER_HEADERS,
        )
        validate_error(response, ERR_PROPERTY_MISMATCH, 422)

    def test_an_out_of_state_licence_cannot_open_a_graph(self, api):
        """Jurisdiction is checked the moment the diary slot is taken.

        PRD 3.3: "The inspector's `license_state` must equal the structure's
        `state_code`, or the request is refused with
        `ERR_LICENSE_STATE_MISMATCH`."

        Design: Corner/errors/plan_creation_and_licence_scope_codes_are_each_independently_triggerable
        """
        crawl, _, _, _, _ = _crawlspace_and_basement(api)
        outsider = register_inspector(
            api, license_state="GA", license_number=next_license_number("GA")
        )
        response = api.create_inspection(
            inspection_payload(
                crawl["id"],
                outsider["id"],
                scheduled_start_at="2026-08-03T09:00:00Z",
                scheduled_end_at="2026-08-03T12:00:00Z",
            ),
            make_field_inspector_headers(outsider["id"]),
        )
        validate_error(response, ERR_LICENSE_STATE_MISMATCH, 422)

    def test_an_applicator_only_licence_cannot_sign_a_graph(self, api):
        """Signing demands the inspection endorsement, not the spraying one.

        PRD 2.9: "Signing a graph requires `WDO_INSPECTOR` among the acting
        inspector's `license_categories` ... Any shortfall is
        `ERR_CATEGORY_NOT_LICENSED` (422)."

        Design: Corner/errors/plan_creation_and_licence_scope_codes_are_each_independently_triggerable
        """
        crawl, _, _, _, _ = _crawlspace_and_basement(api)
        applicator = get_success_data(
            api.create_inspector(
                applicator_only_inspector_payload(license_state="FL"), OFFICER_HEADERS
            )
        )
        graph = open_graph(
            api,
            crawl["id"],
            applicator["id"],
            scheduled_start_at="2026-08-04T09:00:00Z",
            scheduled_end_at="2026-08-04T12:00:00Z",
        )
        response = api.graph_complete(
            graph["id"],
            attested_graph_complete_payload(),
            make_field_inspector_headers(applicator["id"]),
        )
        validate_error(response, ERR_CATEGORY_NOT_LICENSED, 422)


BAIT_BOND_ISSUE_INSTANT = "2026-08-06T00:00:00Z"
BAIT_BOND_TERM_END = "2027-08-06"
FIRST_SERVICE_INSTANT = "2026-08-05T09:00:00Z"
LAPSE_REVIEW_INSTANT = "2027-09-06T00:00:00Z"
EXPECTED_LAPSE_DATE = "2027-09-05"
REINSTATEMENT_GRAPH_INSTANT = "2027-09-10T00:00:00Z"
STALE_ATTEMPT_INSTANT = "2027-10-15T00:00:00Z"
WINDOW_CLOSED_INSTANT = "2027-12-05T00:00:00Z"


def _bait_plan_and_stations(api):
    """A COMPLETED bait plan on a 160-linear-foot FL structure, hardware in."""
    prop, inspector = register_property_and_inspector(
        api,
        address_line1="9 Marsh Lane",
        square_footage=1800,
        linear_footage=160,
        year_built=2001,
    )
    graph = graphed_inspection(api, prop["id"], inspector["id"])
    plan = completed_bait_plan(api, prop["id"], graph["id"], inspector["id"])
    assert_status(plan, PLAN_COMPLETED, "treatment plan")
    stations = list_stations(api, plan["id"], limit=100)
    return prop, inspector, graph, plan, stations


def _lapsed_retreat_only_bond(api):
    """The same bait plan, bonded RETREAT_ONLY and reviewed into LAPSED."""
    prop, inspector, graph, plan, stations = _bait_plan_and_stations(api)
    set_clock(api, BAIT_BOND_ISSUE_INSTANT)
    bond = issue_bond(
        api, prop["id"], plan["id"], coverage_tier=TIER_RETREAT_ONLY
    )
    assert bond["current_term_end"] == BAIT_BOND_TERM_END
    set_clock(api, LAPSE_REVIEW_INSTANT)
    lapsed = review_bond_term(api, bond["id"])
    return prop, inspector, graph, plan, stations, lapsed


class TestStationAndReinstatementCodes:
    """Station and reinstatement refusals are each reachable on one bond."""

    def test_a_visit_at_the_installation_instant_is_refused(self, api):
        """A station's history must strictly increase from its installation.

        PRD 3.9: "the clock instant that will stamp `serviced_at` must be
        strictly after the station's current `last_serviced_at`, so that a
        station's visit history forms a strictly increasing chain. A clock
        rewound to, or exactly onto, the previous visit is refused with
        `ERR_SERVICE_TIME_INVALID`."

        Design: Corner/errors/station_service_and_reinstatement_codes_are_each_reachable_on_one_bond
        """
        _, inspector, _, plan, stations = _bait_plan_and_stations(api)
        assert_status(stations[0], STATION_INSTALLED, "bait station")
        assert_instant_equals(stations[0]["last_serviced_at"], plan["completed_at"])
        response = api.create_station_service(
            stations[0]["id"],
            station_service_payload(ACTIVITY_NONE),
            make_field_inspector_headers(inspector["id"]),
        )
        validate_error(response, ERR_SERVICE_TIME_INVALID, 422)

    def test_a_later_visit_is_accepted_and_moves_the_service_marker(self, api):
        """One second past the installation instant is already lawful.

        PRD 3.9: "the clock instant that will stamp `serviced_at` must be
        strictly after the station's current `last_serviced_at`" and
        "`days_since_last_service` is the number of whole UTC days from the
        station's `last_serviced_at` as it stood before this visit to
        `serviced_at`."

        Design: Corner/errors/station_service_and_reinstatement_codes_are_each_reachable_on_one_bond
        """
        _, inspector, _, _, stations = _bait_plan_and_stations(api)
        set_clock(api, FIRST_SERVICE_INSTANT)
        visit = validate_success(
            api.create_station_service(
                stations[0]["id"],
                station_service_payload(ACTIVITY_NONE),
                make_field_inspector_headers(inspector["id"]),
            ),
            201,
        )
        assert_instant_equals(visit["serviced_at"], FIRST_SERVICE_INSTANT)
        station = get_success_data(
            api.get_bait_station(stations[0]["id"], OFFICER_HEADERS)
        )
        assert_instant_equals(station["last_serviced_at"], FIRST_SERVICE_INSTANT)

    def test_the_lapse_records_the_missed_deadline_not_the_review_date(self, api):
        """A review run a day late still records the deadline that was missed.

        PRD 3.8: "The bond's `lapse_date` is set to `current_term_end` plus 30
        days — the grace deadline that was actually missed, not the date on which
        the review happened to run, so a review three weeks late still records
        the true deadline."

        Design: Corner/errors/station_service_and_reinstatement_codes_are_each_reachable_on_one_bond
        """
        _, _, _, _, _, lapsed = _lapsed_retreat_only_bond(api)
        assert_status(lapsed, BOND_LAPSED, "bond")
        assert lapsed["lapse_date"] == EXPECTED_LAPSE_DATE

    def test_an_underpaid_buyback_is_refused_with_the_reinstatement_money_code(
        self, api
    ):
        """A token payment cannot buy the bond back.

        PRD 3.8: "the amount owed is the premium charge plus a flat
        reinstatement fee of 95.00 plus 1.75 for each day of lapse ... If
        `amount_usd` is less than the amount owed, the attempt is
        `ERR_REINSTATEMENT_PAYMENT_INSUFFICIENT`."

        Design: Corner/errors/station_service_and_reinstatement_codes_are_each_reachable_on_one_bond
        """
        prop, inspector, graph, _, _, lapsed = _lapsed_retreat_only_bond(api)
        set_clock(api, REINSTATEMENT_GRAPH_INSTANT)
        clean = reinstatement_graph(api, prop["id"], inspector["id"], graph["id"])
        response = api.reinstate_bond(
            lapsed["id"], reinstatement_payload(clean["id"], 0.01), MANAGER_HEADERS
        )
        validate_error(response, ERR_REINSTATEMENT_PAYMENT_INSUFFICIENT, 402)

    def test_a_graph_older_than_thirty_days_is_refused_inside_the_open_window(
        self, api
    ):
        """A generous payment cannot rescue a stale graph.

        PRD 3.8: "must have been signed recently — its `graph_completed_at` no
        earlier than 30 days before the current clock instant, otherwise
        `ERR_REINSTATEMENT_INSPECTION_STALE`."

        Design: Corner/errors/station_service_and_reinstatement_codes_are_each_reachable_on_one_bond
        """
        prop, inspector, graph, _, _, lapsed = _lapsed_retreat_only_bond(api)
        set_clock(api, REINSTATEMENT_GRAPH_INSTANT)
        clean = reinstatement_graph(api, prop["id"], inspector["id"], graph["id"])
        set_clock(api, STALE_ATTEMPT_INSTANT)
        response = api.reinstate_bond(
            lapsed["id"], reinstatement_payload(clean["id"], 5000.00), MANAGER_HEADERS
        )
        validate_error(response, ERR_REINSTATEMENT_INSPECTION_STALE, 422)

    def test_the_closed_buyback_window_outranks_the_stale_graph(self, api):
        """Both faults are live, and the window failure is reported.

        PRD 2.6 stage 22: "In order within this stage:
        `ERR_INSPECTOR_SCHEDULE_OVERLAP` (409), `ERR_RENEWAL_WINDOW_NOT_OPEN`
        (409), `ERR_REINSTATEMENT_WINDOW_EXPIRED` (409),
        `ERR_REINSTATEMENT_INSPECTION_STALE` (422)."

        Design: Corner/errors/station_service_and_reinstatement_codes_are_each_reachable_on_one_bond
        """
        prop, inspector, graph, _, _, lapsed = _lapsed_retreat_only_bond(api)
        set_clock(api, REINSTATEMENT_GRAPH_INSTANT)
        clean = reinstatement_graph(api, prop["id"], inspector["id"], graph["id"])
        set_clock(api, WINDOW_CLOSED_INSTANT)
        response = api.reinstate_bond(
            lapsed["id"], reinstatement_payload(clean["id"], 5000.00), MANAGER_HEADERS
        )
        validate_error(response, ERR_REINSTATEMENT_WINDOW_EXPIRED, 409)

    def test_termination_removes_the_hardware_and_closes_the_bond(self, api):
        """Termination pulls the stations and leaves no further buyback path.

        PRD 3.8: "every bait station belonging to the bond's treatment plan that
        is still `INSTALLED`, `ACTIVE_HIT` or `ESCALATED` moves to `REMOVED`."

        Design: Corner/errors/station_service_and_reinstatement_codes_are_each_reachable_on_one_bond
        """
        prop, inspector, graph, _, stations, lapsed = _lapsed_retreat_only_bond(api)
        set_clock(api, REINSTATEMENT_GRAPH_INSTANT)
        clean = reinstatement_graph(api, prop["id"], inspector["id"], graph["id"])
        set_clock(api, WINDOW_CLOSED_INSTANT)
        terminated = review_bond_term(api, lapsed["id"])
        assert_status(terminated, BOND_TERMINATED, "bond")

        station = get_success_data(
            api.get_bait_station(stations[0]["id"], OFFICER_HEADERS)
        )
        assert_status(station, STATION_REMOVED, "bait station")
        refused_visit = api.create_station_service(
            stations[0]["id"],
            station_service_payload(ACTIVITY_NONE),
            make_field_inspector_headers(inspector["id"]),
        )
        validate_error(refused_visit, ERR_INVALID_STATION_STATE, 409)

        refused_buyback = api.reinstate_bond(
            lapsed["id"], reinstatement_payload(clean["id"], 5000.00), MANAGER_HEADERS
        )
        validate_error(refused_buyback, ERR_INVALID_BOND_STATE, 409)


FUMIGATION_PERMIT = "FUM-100001"
FUMIGATION_START = "2026-08-10T08:00:00Z"
FUMIGATION_REENTRY = "2026-08-12T08:00:00Z"
ONE_SECOND_EARLY = "2026-08-10T07:59:59Z"


def _approved_fumigation_plan(api):
    """An APPROVED fumigation plan and the certified licensee who may work it."""
    prop = register_property(api)
    licensee = get_success_data(
        api.create_inspector(
            fumigation_inspector_payload(license_state="FL"), OFFICER_HEADERS
        )
    )
    graph = graphed_inspection(api, prop["id"], licensee["id"])
    proposed = get_success_data(
        api.create_treatment_plan(
            fumigation_plan_payload(
                prop["id"],
                graph["id"],
                licensee["id"],
                fumigation_start_at=FUMIGATION_START,
                fumigation_reentry_at=FUMIGATION_REENTRY,
                fumigation_permit_number=FUMIGATION_PERMIT,
            ),
            MANAGER_HEADERS,
        )
    )
    return prop, licensee, graph, approve_plan(api, proposed["id"])


class TestFumigationPermitAndReentryWindows:
    """The permit window bounds the application and the re-entry bounds completion."""

    def test_a_discharge_one_second_before_the_permit_opens_is_refused(self, api):
        """Fumigant may not be recorded before the tenting window opens.

        PRD 3.6: "the clock instant that will stamp the record must be at or
        after the plan's `fumigation_start_at`, because fumigant cannot be
        recorded as discharged before the permitted start of the tenting window;
        an earlier instant is `ERR_APPLICATION_BEFORE_PERMIT_WINDOW`."

        Design: Corner/errors/fumigation_permit_window_bounds_the_application_and_the_reentry_bounds_completion
        """
        _, licensee, _, plan = _approved_fumigation_plan(api)
        set_clock(api, ONE_SECOND_EARLY)
        response = api.create_application(
            plan["id"],
            application_payload(plan["version"], gallons_applied=0.10),
            make_applicator_headers(licensee["id"]),
        )
        validate_error(response, ERR_APPLICATION_BEFORE_PERMIT_WINDOW, 422)

    def test_a_discharge_exactly_at_the_permit_instant_is_accepted(self, api):
        """The permitted start instant is inclusive.

        PRD 3.5: "`fumigation_start_at`, the inclusive instant at which the
        tenting occupation of the property begins."

        Design: Corner/errors/fumigation_permit_window_bounds_the_application_and_the_reentry_bounds_completion
        """
        _, licensee, _, plan = _approved_fumigation_plan(api)
        set_clock(api, FUMIGATION_START)
        record = validate_success(
            api.create_application(
                plan["id"],
                application_payload(plan["version"], gallons_applied=0.10),
                make_applicator_headers(licensee["id"]),
            ),
            201,
        )
        assert_instant_equals(record["applied_at"], FUMIGATION_START)

    def test_closing_the_plan_out_under_tent_is_a_plan_state_conflict(self, api):
        """A structure still under tent has not been cleared.

        PRD 3.6: "A `FUMIGATION` plan may only be completed once the clock
        instant has reached or passed `fumigation_reentry_at`, because a
        structure still under tent has not been cleared."

        Design: Corner/errors/fumigation_permit_window_bounds_the_application_and_the_reentry_bounds_completion
        """
        _, licensee, _, plan = _approved_fumigation_plan(api)
        set_clock(api, FUMIGATION_START)
        record_application(
            api, plan["id"], licensee["id"], plan["version"], gallons_applied=0.10
        )
        response = api.complete_treatment_plan(
            plan["id"], {}, make_applicator_headers(licensee["id"])
        )
        validate_error(response, ERR_INVALID_PLAN_STATE, 409)
        still_open = get_success_data(
            api.get_treatment_plan(plan["id"], OFFICER_HEADERS)
        )
        assert_status(still_open, PLAN_APPROVED, "treatment plan")

    def test_closing_the_plan_out_at_the_reentry_instant_succeeds(self, api):
        """The re-entry instant is inclusive, and no hardware is installed.

        PRD 3.5: "`fumigation_reentry_at`, the inclusive clearance-and-re-entry
        instant that ends it, which must fall strictly after the start."

        Design: Corner/errors/fumigation_permit_window_bounds_the_application_and_the_reentry_bounds_completion
        """
        _, licensee, _, plan = _approved_fumigation_plan(api)
        set_clock(api, FUMIGATION_START)
        record_application(
            api, plan["id"], licensee["id"], plan["version"], gallons_applied=0.10
        )
        set_clock(api, FUMIGATION_REENTRY)
        completed = validate_success(
            api.complete_treatment_plan(
                plan["id"], {}, make_applicator_headers(licensee["id"])
            )
        )
        assert_status(completed, PLAN_COMPLETED, "treatment plan")
        assert_instant_equals(completed["completed_at"], FUMIGATION_REENTRY)
        assert completed["target_station_count"] == 0
        assert_page(api.list_bait_stations(plan["id"], OFFICER_HEADERS), 0)


RENEWAL_BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"
RENEWAL_WINDOW_OPEN_INSTANT = "2027-07-03T00:00:00Z"
ROLLED_TERM_START = "2027-09-01"
ROLLED_TERM_END = "2028-08-31"
PROVISIONAL_INVOICE_TOTAL = 211.27
TENDERED_USD = 1000.00


def _pending_renewal(api):
    """An ACTIVE bond with a PENDING invoice and a signed renewal graph."""
    chain = bonded_property(api, issue_instant=RENEWAL_BOND_ISSUE_INSTANT)
    set_clock(api, RENEWAL_WINDOW_OPEN_INSTANT)
    invoice = open_renewal(api, chain["bond"]["id"])
    assert_status(invoice, RENEWAL_PENDING, "renewal")
    graph = renewal_graph(
        api,
        chain["property"]["id"],
        chain["inspector"]["id"],
        chain["inspection"]["id"],
    )
    return chain, invoice, graph


class TestRenewalCompletionLeavesPending:
    """Completion is refused once the invoice has left PENDING."""

    def test_the_first_completion_pays_the_invoice_and_rolls_the_term(self, api):
        """Payment moves the invoice to PAID and rolls the coverage window on.

        PRD 3.8: "On success the invoice records the attached `inspection_id`,
        moves to `PAID`, stamps `paid_at` with the clock instant, and records
        `amount_paid_usd` as the amount tendered."

        Design: Corner/errors/renewal_completion_is_refused_once_the_renewal_leaves_pending
        """
        chain, invoice, graph = _pending_renewal(api)
        paid = complete_renewal(api, invoice["id"], graph["id"], TENDERED_USD)
        assert_status(paid, RENEWAL_PAID, "renewal")
        assert_instant_equals(paid["paid_at"], RENEWAL_WINDOW_OPEN_INSTANT)
        assert paid["inspection_id"] == graph["id"]

        bond = get_success_data(api.get_bond(chain["bond"]["id"], OFFICER_HEADERS))
        assert bond["term_index"] == 2
        assert bond["current_term_start"] == ROLLED_TERM_START
        assert bond["current_term_end"] == ROLLED_TERM_END

    def test_a_second_completion_is_refused_with_the_renewal_state_code(self, api):
        """A paid invoice is no longer PENDING, so it cannot be paid again.

        PRD 3.8: "The invoice must be `PENDING`, or the attempt is
        `ERR_INVALID_RENEWAL_STATE`."

        Design: Corner/errors/renewal_completion_is_refused_once_the_renewal_leaves_pending
        """
        _, invoice, graph = _pending_renewal(api)
        complete_renewal(api, invoice["id"], graph["id"], TENDERED_USD)
        response = api.complete_renewal(
            invoice["id"],
            renewal_completion_payload(graph["id"], TENDERED_USD),
            MANAGER_HEADERS,
        )
        validate_error(response, ERR_INVALID_RENEWAL_STATE, 409)

    def test_the_refused_completion_moves_neither_version_nor_the_term(self, api):
        """The refusal cascades nowhere: no second roll-forward happens.

        PRD 2.6 stage 10: "The code names the entity whose state is wrong ...
        `ERR_INVALID_RENEWAL_STATE` ... each at HTTP 409."

        Design: Corner/errors/renewal_completion_is_refused_once_the_renewal_leaves_pending
        """
        chain, invoice, graph = _pending_renewal(api)
        paid = complete_renewal(api, invoice["id"], graph["id"], TENDERED_USD)
        bond_after_payment = get_success_data(
            api.get_bond(chain["bond"]["id"], OFFICER_HEADERS)
        )

        api.complete_renewal(
            invoice["id"],
            renewal_completion_payload(graph["id"], TENDERED_USD),
            MANAGER_HEADERS,
        )

        assert_version(
            get_success_data(api.get_renewal(invoice["id"], OFFICER_HEADERS)),
            paid["version"],
            "renewal",
        )
        bond_now = get_success_data(api.get_bond(chain["bond"]["id"], OFFICER_HEADERS))
        assert_version(bond_now, bond_after_payment["version"], "bond")
        assert bond_now["term_index"] == 2
        assert bond_now["current_term_end"] == ROLLED_TERM_END

    def test_the_overpayment_is_recorded_as_tendered_rather_than_clamped(self, api):
        """The invoice keeps its own total and records what was actually paid.

        PRD 3.8: "records `amount_paid_usd` as the amount tendered."

        Design: Corner/errors/renewal_completion_is_refused_once_the_renewal_leaves_pending
        """
        _, invoice, graph = _pending_renewal(api)
        assert_money(invoice["invoice_total_usd"], PROVISIONAL_INVOICE_TOTAL)
        paid = complete_renewal(api, invoice["id"], graph["id"], TENDERED_USD)
        assert_money(paid["amount_paid_usd"], TENDERED_USD)
        assert_money(paid["invoice_total_usd"], PROVISIONAL_INVOICE_TOTAL)
