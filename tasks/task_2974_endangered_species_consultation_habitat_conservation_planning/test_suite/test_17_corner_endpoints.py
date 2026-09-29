"""Endpoint-surface claims: the two envelopes, the filters, and the status codes.

Each test drives one §1.9 `endpoints` recipe. The paginated pair carry a window
and rejected bounds, every other list carries the whole collection under a null
pagination block, the filters recompute `total_count` over derived columns, the
bank-to-commitment link crosses aggregates under an agency-only role list, an
undeclared enum value outranks both the state and the version rung, and the
declared status codes separate row creations from pure transitions.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_error_envelope, assert_unpaginated_list
from test_helpers.constants import NON_EXISTENT_ID
from test_helpers.factories import (
    adjudication_payload,
    biological_assessment_payload,
    changed_circumstance_event_payload,
    circumstance_response_payload,
    conservation_bank_payload,
    critical_habitat_unit_payload,
    database_query_payload,
    field_survey_payload,
    funding_assurance_payload,
    habitat_conservation_plan_payload,
    incidental_take_permit_payload,
    listing_change_payload,
    mitigation_commitment_payload,
    monitoring_report_payload,
    plan_decision_payload,
    project_action_payload,
    proponent_payload,
    species_payload,
    threatened_species_payload,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    APPROVER,
    AUDITOR,
    ISSUER,
    REGISTRAR,
    add_commitment,
    build_scenario,
    issue_biological_opinion,
    read_bank,
    read_plan,
    record_database_query,
    record_field_survey,
    run_effect_determination,
    setup_action_with_determination_count,
    setup_canonical_permit,
    setup_permit_with_accepted_first_quarter_report,
    setup_second_action,
    submit_biological_assessment,
)
from test_helpers.test_users import anonymous_headers, make_proponent_headers


class TestPaginatedListEnvelope:
    """`total_count` describes the filtered set; the bounds are rejections."""

    def test_the_window_defaults_to_ten_and_the_bounds_are_never_clamped(self, api):
        """Eleven rows page as 10 + 1 while limit 0, limit 101 and offset -1 are 400.

        PRD: "`limit` defaults to 10 when omitted, may not be smaller than 1, and may
        not be larger than 100. `offset` defaults to 0 and may not be negative. Both
        must be integers. A `limit` outside the range 1 through 100 is **rejected**,
        never silently clamped, and an out-of-range or non-integer `limit` or `offset`
        is reported as `ERR_INVALID_REQUEST` (HTTP 400)."

        PRD: "Paginated responses carry `limit`, `offset`, `total_count`, and
        `has_more` inside `meta`, where `total_count` is the size of the full filtered
        result set before the window is applied and `has_more` is true when rows remain
        beyond the window."

        PRD: "All lists, paginated and unpaginated alike, are ordered by `created_at`
        ascending."

        Design: Corner/endpoints/paginated_lists_carry_total_count_has_more_and_bounded_limits
        """
        scenario = setup_action_with_determination_count(11)
        action_id = scenario["action"]["id"]
        headers = scenario["proponent_headers"]
        expected_ids = [row["id"] for row in scenario["determinations"]]

        first_page, first_meta = validate_paginated(
            api_client.list_presence_determinations(
                headers, params={"project_action_id": action_id}
            )
        )

        assert len(first_page) == 10
        assert first_meta["limit"] == 10
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 11
        assert first_meta["has_more"] is True
        assert [row["id"] for row in first_page] == expected_ids[:10]

        whole_set, whole_meta = validate_paginated(
            api_client.list_presence_determinations(
                headers, params={"project_action_id": action_id, "limit": 100}
            )
        )

        assert len(whole_set) == 11
        assert whole_meta["total_count"] == 11
        assert whole_meta["has_more"] is False
        assert [row["id"] for row in whole_set] == expected_ids

        tail, tail_meta = validate_paginated(
            api_client.list_presence_determinations(
                headers,
                params={"project_action_id": action_id, "limit": 10, "offset": 10},
            )
        )

        assert [row["id"] for row in tail] == expected_ids[10:]
        assert tail_meta["total_count"] == 11
        assert tail_meta["has_more"] is False

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            assert_error_envelope(
                api_client.list_presence_determinations(headers, params=params),
                ApiErrorId.ERR_INVALID_REQUEST,
                400,
            )
            assert_error_envelope(
                api_client.list_project_actions(headers, params=params),
                ApiErrorId.ERR_INVALID_REQUEST,
                400,
            )


class TestUnpaginatedSubResourceLists:
    """Sub-resource lists return the whole collection under a null block."""

    def test_every_sub_resource_list_carries_a_null_pagination_block(self, api):
        """Commitments, permits, consultations and an empty event list all agree.

        PRD: "Every other list endpoint in this specification - a species' critical
        habitat units, a species' conservation banks, an action's consultations, an
        action's plans, a consultation's biological opinions, a bank's mitigation
        commitments, a plan's mitigation commitments, a plan's permits, a plan's
        circumstance events, and a permit's monitoring reports - is **unpaginated**.
        Those endpoints return the complete collection, accept no `limit` or `offset`,
        and carry a null pagination block in `meta` rather than pagination counters."

        The plan's two commitments come back in the order they were created, which is
        the order the approval cascade walks, and the plan's event list is empty while
        still reporting the null block - emptiness and unpagination are independent.

        Design: Corner/endpoints/sub_resource_lists_are_unpaginated_with_a_null_pagination_block
        """
        scenario = setup_canonical_permit()
        plan_id = scenario["plan"]["id"]
        headers = scenario["proponent_headers"]

        commitments = assert_unpaginated_list(
            api_client.list_plan_mitigation_commitments(plan_id, headers)
        )

        assert [row["id"] for row in commitments] == [
            row["id"] for row in scenario["commitments"]
        ]
        assert [row["units"] for row in commitments] == [45.01, 14.71]

        permits = assert_unpaginated_list(
            api_client.list_plan_incidental_take_permits(plan_id, headers)
        )

        assert [row["id"] for row in permits] == [scenario["permit"]["id"]]

        consultations = assert_unpaginated_list(
            api_client.list_action_consultations(scenario["action"]["id"], headers)
        )

        assert [row["id"] for row in consultations] == [scenario["consultation"]["id"]]

        events = assert_unpaginated_list(
            api_client.list_plan_changed_circumstance_events(plan_id, headers)
        )

        assert events == []

        reports = assert_unpaginated_list(
            api_client.list_permit_monitoring_reports(scenario["permit"]["id"], headers)
        )

        assert reports == []


class TestListFilters:
    """Filters cut across derived columns and `total_count` follows the filter."""

    def test_each_filter_narrows_the_rows_and_the_total_count_follows(self, api):
        """Seven filters select their row out of three determinations and two actions.

        PRD: "Actions can be narrowed by `proponent_id`, by `active_consultation_id`,
        by `status`, and by `effect_determination`, alongside the `limit` and `offset`
        window of §2.3. Determinations can be narrowed by `project_action_id`, by
        `species_id`, by `critical_habitat_unit_id`, by `presence_status`, and by
        `requires_reevaluation`, again alongside `limit` and `offset`. Every filter is
        optional and filters combine conjunctively."

        PRD: "`requires_reevaluation` is set to false on creation and is only ever
        raised afterwards by the uplisting cascade of §3.1."

        The first action screened to `LAA` and carries a confirmed row plus a presumed
        one; the second action is still `SCREENING` with a `PRESUMED_ABSENT` row, so
        the status and effect filters read the fork's landing state and its verdict
        rather than any input field.

        Design: Corner/endpoints/list_filters_narrow_the_rows_without_disturbing_the_envelope
        """
        scenario = build_scenario("effect_determination")
        headers = scenario["proponent_headers"]
        action_id = scenario["action"]["id"]
        present_id = scenario["field_determination"]["id"]

        second_action = setup_second_action(scenario)
        absent = record_database_query(
            second_action,
            scenario["proponent"],
            scenario["threatened_species"]["id"],
            detection_result="NOT_DETECTED",
        )

        assert scenario["action"]["effect_determination"] == "LAA"
        assert second_action["status"] == "SCREENING"
        assert second_action["effect_determination"] == "PENDING"
        assert absent["presence_status"] == "PRESUMED_ABSENT"

        def determinations(**params):
            return validate_paginated(
                api_client.list_presence_determinations(headers, params=params)
            )

        def actions(**params):
            return validate_paginated(api_client.list_project_actions(headers, params=params))

        rows, meta = determinations(presence_status="PRESENT")

        assert [row["id"] for row in rows] == [present_id]
        assert meta["total_count"] == 1

        rows, meta = determinations(project_action_id=second_action["id"])

        assert [row["id"] for row in rows] == [absent["id"]]
        assert meta["total_count"] == 1

        rows, _ = determinations(critical_habitat_unit_id=scenario["unit"]["id"])

        assert [row["id"] for row in rows] == [present_id]

        rows, _ = determinations(
            species_id=scenario["threatened_species"]["id"],
            presence_status="PRESUMED_ABSENT",
        )

        assert [row["id"] for row in rows] == [absent["id"]]

        rows, meta = determinations(requires_reevaluation="true")

        assert rows == []
        assert meta["total_count"] == 0

        rows, _ = actions(status="SCREENING")

        assert [row["id"] for row in rows] == [second_action["id"]]

        rows, _ = actions(effect_determination="LAA")

        assert [row["id"] for row in rows] == [action_id]

        rows, meta = actions(proponent_id=scenario["proponent"]["id"], limit=10)

        assert [row["id"] for row in rows] == [action_id, second_action["id"]]
        assert meta["total_count"] == 2

        rows, _ = actions(active_consultation_id=scenario["consultation"]["id"])

        assert [row["id"] for row in rows] == [action_id]

        _, unfiltered = determinations()

        assert unfiltered["total_count"] == 3


class TestBankCommitmentLink:
    """The bank link crosses plans and is closed to the proponent that owns them."""

    def test_the_link_spans_plans_and_excludes_the_proponent(self, api):
        """Three commitments from two plans list under one bank, agency-side only.

        PRD: "| GET | `/conservation-banks/{id}/mitigation-commitments` | List every
        mitigation commitment drawn against a bank, across all plans. Unpaginated;
        restricted because it exposes other proponents' commitments. |
        `WildlifeAgency`, `Auditor` |"

        PRD: "On a conservation bank, `credits_available` plus `credits_reserved` plus
        `credits_transferred` always equals `credits_total_minted`"

        The two approved commitments are `SECURED` and account for the bank's 59.72
        transferred credits, while the third belongs to a different plan of a
        different action and is still `RESERVED`; the proponent that owns all three
        rows is nevertheless refused, because its route to them is the plan's own list.

        Design: Corner/endpoints/the_bank_commitment_link_is_agency_only_and_spans_every_plan
        """
        scenario = setup_canonical_permit()
        headers = scenario["proponent_headers"]
        bank_id = scenario["bank"]["id"]

        second_action = setup_second_action(scenario)
        record_field_survey(
            second_action,
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=15.00,
        )
        second_action = run_effect_determination(second_action, scenario["proponent"])
        second_consultation_id = second_action["active_consultation_id"]
        submit_biological_assessment(second_consultation_id, scenario["proponent"])
        issue_biological_opinion(second_consultation_id)
        second_plan = get_success_data(
            api_client.create_habitat_conservation_plan(
                second_action["id"],
                habitat_conservation_plan_payload(plan_name="Sunrise Park Phase II HCP"),
                headers,
            ),
            201,
        )
        third_commitment = add_commitment(
            second_plan["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 10.00,
                "conservation_bank_id": bank_id,
            },
        )

        expected_ids = [row["id"] for row in scenario["commitments"]] + [
            third_commitment["id"]
        ]

        auditor_rows = assert_unpaginated_list(
            api_client.list_bank_mitigation_commitments(bank_id, AUDITOR)
        )

        assert [row["id"] for row in auditor_rows] == expected_ids
        assert [row["status"] for row in auditor_rows] == [
            "SECURED",
            "SECURED",
            "RESERVED",
        ]
        assert auditor_rows[2]["hcp_id"] == second_plan["id"]

        agency_rows = assert_unpaginated_list(
            api_client.list_bank_mitigation_commitments(bank_id, REGISTRAR)
        )

        assert [row["id"] for row in agency_rows] == expected_ids

        refused = api_client.list_bank_mitigation_commitments(bank_id, headers)
        assert_error_envelope(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        missing = api_client.list_bank_mitigation_commitments(NON_EXISTENT_ID, AUDITOR)
        assert_error_envelope(missing, ApiErrorId.ERR_CONSERVATION_BANK_NOT_FOUND, 404)

        bank = read_bank(bank_id)

        assert bank["credits_reserved"] == 10.00
        assert bank["credits_transferred"] == 59.72
        assert bank["credits_available"] == 430.28
        assert (
            bank["credits_available"] + bank["credits_reserved"] + bank["credits_transferred"]
            == bank["credits_total_minted"]
        )


class TestEnumRejectionOrder:
    """An undeclared enum value is 400 even when the row would refuse the legal one."""

    def test_an_undeclared_value_is_400_before_the_version_and_state_rungs(self, api):
        """Six closed vocabularies each reject an outside value with one 400.

        PRD: "(7) Request-body shape and type conformance - `ERR_INVALID_REQUEST`. (8)
        Optimistic-concurrency version match - `ERR_STALE_HCP_VERSION` or
        `ERR_STALE_PERMIT_VERSION`. (9) The target row's current state being a legal
        source state for the requested transition - `ERR_INVALID_STATE_TRANSITION`."

        PRD: "It requires every mandatory field present, no unknown fields, correct
        JSON types, enum values drawn from the declared member set for that field,
        monetary fields as non-negative integers, quantity fields non-negative and
        carrying at most two decimal places"

        The plan is `IMPLEMENTING`, so it would refuse a legal `APPROVE` with a state
        error, and the report is terminally `ACCEPTED`; the permit's version has also
        moved since issuance. Every probe is still reported as a shape defect, and no
        row changes state.

        Design: Corner/endpoints/action_endpoints_reject_undeclared_enum_values_before_any_state_check
        """
        scenario = setup_permit_with_accepted_first_quarter_report()
        plan_id = scenario["plan"]["id"]
        permit_id = scenario["permit"]["id"]
        report_id = scenario["r1"]["id"]
        headers = scenario["proponent_headers"]

        assert read_plan(plan_id)["plan_status"] == "IMPLEMENTING"
        assert scenario["permit"]["version"] > 1
        reports = assert_unpaginated_list(
            api_client.list_permit_monitoring_reports(permit_id, headers)
        )
        assert [row["status"] for row in reports] == ["ACCEPTED"]

        live_version = read_plan(plan_id)["version"]

        probes = (
            api_client.decide_plan(
                plan_id,
                plan_decision_payload("DENY", decision_note="Rejected outright."),
                APPROVER,
            ),
            api_client.adjudicate_monitoring_report(
                report_id,
                adjudication_payload("REVISE", adjudication_note="Send it back."),
                ADJUDICATOR,
            ),
            api_client.create_changed_circumstance_event(
                plan_id,
                changed_circumstance_event_payload(
                    circumstance_type="ACT_OF_GOD",
                    description="Wildfire crossed the mitigation parcel.",
                    response_cost_cents=700_000,
                ),
                headers,
            ),
            api_client.create_funding_assurance(
                plan_id,
                funding_assurance_payload(100_000, instrument_type="CASH_IN_HAND"),
                headers,
            ),
            api_client.create_mitigation_commitment(
                plan_id,
                mitigation_commitment_payload(
                    live_version,
                    mechanism="MITIGATION_CREDIT",
                    units=5.00,
                    conservation_bank_id=scenario["bank"]["id"],
                ),
                headers,
            ),
            api_client.create_monitoring_report(
                permit_id,
                monitoring_report_payload(
                    1,
                    period_start="2027-04-01",
                    period_end="2027-05-01",
                    take_units_reported="3.00",
                    mitigation_units_verified=59.72,
                ),
                headers,
            ),
        )
        for response in probes:
            assert_error_envelope(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        settled = read_plan(plan_id)

        assert settled["plan_status"] == "IMPLEMENTING"
        assert settled["version"] == live_version
        assert [
            row["status"]
            for row in assert_unpaginated_list(
                api_client.list_permit_monitoring_reports(permit_id, headers)
            )
        ] == ["ACCEPTED"]
        assert (
            assert_unpaginated_list(
                api_client.list_plan_changed_circumstance_events(plan_id, headers)
            )
            == []
        )


class TestDeclaredStatusCodes:
    """201 belongs to the calls that materialise a row; everything else is 200."""

    def test_creations_answer_201_while_pure_transitions_answer_200(self, api):
        """One end-to-end walk pins the code of every POST it makes.

        PRD: "An operation that brings a **new** resource row into existence returns
        201 Created, and its `data` carries the newly created resource. An operation
        that modifies an existing resource, or that reads one, returns 200 OK, and its
        `data` carries the affected resource in its post-operation state - except for
        the logical-clock capability, which returns 200 OK with an empty `data`
        object."

        PRD: "On `LAA`, the action moves `SCREENING - FORMAL_CONSULTATION`, the same
        three fields are written, and exactly one consultation is created"

        The effect determination is the sharp case: it answers 200 with the project
        action even though it creates a consultation as a side effect, and the
        consultation's id is reachable only through `active_consultation_id`. The
        biological assessment and the biological opinion act on the same consultation
        and split 200 from 201 for the same reason.

        Design: Corner/endpoints/declared_status_codes_separate_creations_from_transitions
        """
        clock = get_success_data(
            api_client.set_clock("2026-10-01T00:00:00Z", REGISTRAR), 200
        )

        assert clock == {}

        proponent = get_success_data(
            api_client.create_proponent(proponent_payload(), anonymous_headers()), 201
        )
        headers = make_proponent_headers(proponent["id"])
        species = get_success_data(
            api_client.create_species(species_payload(), REGISTRAR), 201
        )
        unit = get_success_data(
            api_client.create_critical_habitat_unit(
                species["id"], critical_habitat_unit_payload(), REGISTRAR
            ),
            201,
        )
        threatened = get_success_data(
            api_client.create_species(threatened_species_payload(), REGISTRAR), 201
        )
        bank = get_success_data(
            api_client.create_conservation_bank(
                conservation_bank_payload(species["id"]), REGISTRAR
            ),
            201,
        )
        action = get_success_data(
            api_client.create_project_action(project_action_payload(proponent["id"]), headers),
            201,
        )
        get_success_data(
            api_client.create_presence_determination(
                action["id"],
                field_survey_payload(species["id"], critical_habitat_unit_id=unit["id"]),
                headers,
            ),
            201,
        )
        get_success_data(
            api_client.create_presence_determination(
                action["id"], database_query_payload(threatened["id"]), headers
            ),
            201,
        )

        screened = get_success_data(api_client.run_effect_determination(action["id"], headers), 200)

        assert screened["id"] == action["id"]
        assert screened["status"] == "FORMAL_CONSULTATION"
        assert screened["active_consultation_id"] is not None

        consultation_id = screened["active_consultation_id"]
        reviewed = get_success_data(
            api_client.submit_biological_assessment(
                consultation_id, biological_assessment_payload(), headers
            ),
            200,
        )

        assert reviewed["id"] == consultation_id
        assert reviewed["status"] == "UNDER_REVIEW"

        opinion = get_success_data(
            api_client.issue_biological_opinion(consultation_id, {}, ISSUER), 201
        )

        assert opinion["consultation_id"] == consultation_id
        assert opinion["conclusion"] == "NO_JEOPARDY"

        plan = get_success_data(
            api_client.create_habitat_conservation_plan(
                action["id"], habitat_conservation_plan_payload(), headers
            ),
            201,
        )
        get_success_data(
            api_client.create_mitigation_commitment(
                plan["id"],
                mitigation_commitment_payload(
                    plan["version"], units=45.01, conservation_bank_id=bank["id"]
                ),
                headers,
            ),
            201,
        )
        live = get_success_data(
            api_client.get_habitat_conservation_plan(plan["id"], headers), 200
        )
        get_success_data(
            api_client.create_mitigation_commitment(
                plan["id"],
                mitigation_commitment_payload(
                    live["version"], units=14.71, conservation_bank_id=bank["id"]
                ),
                headers,
            ),
            201,
        )
        assured = get_success_data(
            api_client.create_funding_assurance(
                plan["id"], funding_assurance_payload(5_026_514), headers
            ),
            200,
        )

        assert assured["id"] == plan["id"]
        assert assured["funding_status"] == "FULLY_ASSURED"

        submitted = get_success_data(api_client.submit_plan(plan["id"], headers), 200)

        assert submitted["plan_status"] == "SUBMITTED"

        approved = get_success_data(
            api_client.decide_plan(plan["id"], plan_decision_payload("APPROVE"), APPROVER),
            200,
        )

        assert approved["plan_status"] == "APPROVED"

        permit = get_success_data(
            api_client.issue_incidental_take_permit(
                plan["id"], incidental_take_permit_payload(), ISSUER
            ),
            201,
        )

        assert permit["hcp_id"] == plan["id"]

        get_success_data(api_client.set_clock("2027-05-16T00:00:00Z", REGISTRAR), 200)

        report = get_success_data(
            api_client.create_monitoring_report(
                permit["id"],
                monitoring_report_payload(
                    permit["version"],
                    take_units_reported=0.50,
                    mitigation_units_verified=59.72,
                ),
                headers,
            ),
            201,
        )
        adjudicated = get_success_data(
            api_client.adjudicate_monitoring_report(
                report["id"],
                adjudication_payload("ACCEPT", adjudication_note="Take within authorized limits."),
                ADJUDICATOR,
            ),
            200,
        )

        assert adjudicated["id"] == report["id"]
        assert adjudicated["status"] == "ACCEPTED"

        event = get_success_data(
            api_client.create_changed_circumstance_event(
                plan["id"],
                changed_circumstance_event_payload(
                    description=(
                        "Prolonged drought reduced forage cover across the mitigation parcel."
                    ),
                    response_cost_cents=700_000,
                ),
                headers,
            ),
            201,
        )
        responded = get_success_data(
            api_client.respond_to_circumstance_event(
                event["id"],
                circumstance_response_payload(
                    161_445, response_note="Reserve draw plus permittee contribution."
                ),
                headers,
            ),
            200,
        )

        assert responded["id"] == event["id"]
        assert responded["status"] == "RESPONDED"

        relisted = get_success_data(
            api_client.change_species_listing(
                threatened["id"],
                listing_change_payload(
                    "ENDANGERED",
                    rationale="Range-wide decline documented in the 5-year status review.",
                ),
                REGISTRAR,
            ),
            200,
        )

        assert relisted["id"] == threatened["id"]
        assert relisted["listing_status"] == "ENDANGERED"
