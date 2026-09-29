"""The role matrix read as a matrix: both exclusive halves, and the two edges.

Every claim here is about who may call an endpoint rather than about what the
endpoint computes, so each test drives real fixtures to a state where the call
would otherwise succeed and then makes it from the wrong role.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_error_envelope,
    assert_same_instant,
    assert_unpaginated_list,
)
from test_helpers.constants import NON_EXISTENT_ID
from test_helpers.factories import (
    adjudication_payload,
    biological_assessment_payload,
    changed_circumstance_event_payload,
    circumstance_response_payload,
    concurrence_payload,
    conservation_bank_payload,
    critical_habitat_unit_payload,
    database_query_payload,
    funding_assurance_payload,
    habitat_conservation_plan_payload,
    incidental_take_permit_payload,
    information_request_payload,
    listing_change_payload,
    mitigation_commitment_payload,
    monitoring_report_payload,
    plan_decision_payload,
    project_action_payload,
    proponent_payload,
    species_payload,
)
from test_helpers.fixtures import (
    AUDITOR,
    CANONICAL_CLOCK,
    REGISTRAR,
    build_scenario,
    file_monitoring_report,
    read_action,
    read_plan,
    read_species,
    register_proponent,
    register_species,
    report_circumstance,
    set_clock,
    setup_canonical_permit,
)
from test_helpers.test_users import (
    anonymous_headers,
    auditor_headers_without_user_id,
    make_proponent_headers,
)


class TestProponentExclusiveWrites:
    """Eleven writes the agency may never make on the proponent's behalf."""

    def test_no_other_role_may_assert_anything_in_the_proponents_name(self, api):
        """The agency, the auditor and the anonymous caller are all refused the same eleven.

        PRD: "a recognised role attempting an endpoint it is not listed for is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)"

        PRD: "(3) The role being permitted on the target endpoint -
        `ERR_ROLE_NOT_PERMITTED`."

        PRD: "The `Auditor` role can perform no write of any kind - every write
        attempt by an auditor returns `ERR_ROLE_NOT_PERMITTED` - and the `Anonymous`
        role can perform exactly one operation, proponent self-registration, with
        every other endpoint likewise returning `ERR_ROLE_NOT_PERMITTED`."

        The monitoring-report attempt carries the permit's current `version` and the
        permit is `ACTIVE`, so it would clear rungs 8, 9 and 10; the refusal at rung 3
        happens anyway, and nothing is created by any of the thirty-three attempts.

        Design: Corner/rbac/proponent_exclusive_writes_are_refused_to_every_other_role
        """
        scenario = setup_canonical_permit()
        action_id = scenario["action"]["id"]
        plan_id = scenario["plan"]["id"]
        permit_id = scenario["permit"]["id"]
        consultation_id = scenario["consultation"]["id"]
        proponent_id = scenario["proponent"]["id"]
        event = report_circumstance(
            plan_id, scenario["proponent"], response_cost_cents=700_000
        )
        permit_version = scenario["permit"]["version"]
        plan_before = read_plan(plan_id)

        assert scenario["permit"]["status"] == "ACTIVE"
        assert event["status"] == "RESPONSE_REQUIRED"
        assert event["required_additional_cents"] == 161_445

        def proponent_exclusive_calls(headers):
            return [
                api_client.create_project_action(
                    project_action_payload(proponent_id, action_name="Agency Filed Action"),
                    headers,
                ),
                api_client.create_presence_determination(
                    action_id,
                    database_query_payload(
                        scenario["species"]["id"], habitat_overlap_acres=2.00
                    ),
                    headers,
                ),
                api_client.run_effect_determination(action_id, headers),
                api_client.create_habitat_conservation_plan(
                    action_id, habitat_conservation_plan_payload(), headers
                ),
                api_client.submit_biological_assessment(
                    consultation_id, biological_assessment_payload(), headers
                ),
                api_client.create_mitigation_commitment(
                    plan_id,
                    mitigation_commitment_payload(
                        scenario["plan"]["version"],
                        units=1.00,
                        conservation_bank_id=scenario["bank"]["id"],
                    ),
                    headers,
                ),
                api_client.create_funding_assurance(
                    plan_id, funding_assurance_payload(100_000), headers
                ),
                api_client.submit_plan(plan_id, headers),
                api_client.create_monitoring_report(
                    permit_id,
                    monitoring_report_payload(
                        permit_version,
                        period_start="2026-10-01",
                        period_end="2026-11-01",
                        take_units_reported=0.50,
                        mitigation_units_verified=59.72,
                    ),
                    headers,
                ),
                api_client.create_changed_circumstance_event(
                    plan_id, changed_circumstance_event_payload(), headers
                ),
                api_client.respond_to_circumstance_event(
                    event["id"], circumstance_response_payload(161_445), headers
                ),
            ]

        for headers in (REGISTRAR, AUDITOR, anonymous_headers()):
            responses = proponent_exclusive_calls(headers)
            assert len(responses) == 11
            for response in responses:
                assert_error_envelope(
                    response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403
                )

        plan = read_plan(plan_id)
        action = read_action(action_id)
        reports = assert_unpaginated_list(
            api_client.list_permit_monitoring_reports(permit_id, AUDITOR)
        )

        assert plan["plan_status"] == "IMPLEMENTING"
        assert plan["endowment_secured_cents"] == 5_026_514
        assert plan["version"] == plan_before["version"]
        assert action["status"] == "PERMITTED"
        assert reports == []


class TestAgencyExclusiveWrites:
    """Ten determinations the regulated party may never make about itself."""

    def test_the_proponent_may_not_register_uplist_opine_approve_issue_or_adjudicate(
        self, api
    ):
        """All ten agency-exclusive writes answer the proponent with the same 403.

        PRD: "Record a change to a species' listing status; raising the rank starts
        the uplisting cascade."

        PRD: "Issue the incidental take permit and its implementing agreement for an
        approved plan."

        PRD: "Agency adjudication of a submitted monitoring report."

        PRD: "The official who approved a habitat conservation plan may not also issue
        that plan's incidental take permit: an issuance request whose `X-User-ID`
        equals the plan's `approved_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        The self-approval and self-issuance refusals land at rung 3, so the
        segregation-of-duties rules at rungs 11 and 12 - which compare agency user
        ids against one another - are never reached; and the registry stays outside
        the proponent's reach, which is what keeps its own mitigation ratio out of
        its hands.

        Design: Corner/rbac/agency_exclusive_writes_are_refused_to_the_proponent
        """
        scenario = setup_canonical_permit()
        species_id = scenario["species"]["id"]
        consultation_id = scenario["consultation"]["id"]
        plan_id = scenario["plan"]["id"]
        permit_id = scenario["permit"]["id"]
        headers = scenario["proponent_headers"]
        set_clock("2027-05-16T00:00:00Z")
        report = file_monitoring_report(permit_id, scenario["proponent"])
        plan_before = read_plan(plan_id)

        assert report["status"] == "SUBMITTED"
        assert scenario["species"]["listing_status"] == "ENDANGERED"

        agency_exclusive_calls = [
            api_client.create_species(
                species_payload(
                    scientific_name="Rana draytonii",
                    common_name="California red-legged frog",
                    listing_status="THREATENED",
                ),
                headers,
            ),
            api_client.create_critical_habitat_unit(
                species_id, critical_habitat_unit_payload(unit_code="CHU-7"), headers
            ),
            api_client.change_species_listing(
                species_id,
                listing_change_payload(
                    new_listing_status="THREATENED", rationale="Proponent asserts recovery."
                ),
                headers,
            ),
            api_client.create_conservation_bank(
                conservation_bank_payload(species_id, bank_name="Self Serve Bank"),
                headers,
            ),
            api_client.request_information(
                consultation_id, information_request_payload(), headers
            ),
            api_client.record_concurrence(consultation_id, concurrence_payload(), headers),
            api_client.issue_biological_opinion(consultation_id, {}, headers),
            api_client.decide_plan(
                plan_id,
                plan_decision_payload(decision="APPROVE", decision_note="Self approval."),
                headers,
            ),
            api_client.issue_incidental_take_permit(
                plan_id,
                incidental_take_permit_payload(
                    implementing_agreement_reference="IA-SELF-0001"
                ),
                headers,
            ),
            api_client.adjudicate_monitoring_report(
                report["id"],
                adjudication_payload(
                    decision="ACCEPT", adjudication_note="Self adjudication."
                ),
                headers,
            ),
        ]

        assert len(agency_exclusive_calls) == 10
        for response in agency_exclusive_calls:
            assert_error_envelope(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        species = read_species(species_id)
        plan = read_plan(plan_id)
        reports = assert_unpaginated_list(
            api_client.list_permit_monitoring_reports(permit_id, AUDITOR)
        )

        assert species["listing_status"] == "ENDANGERED"
        assert species["listing_change_count"] == 0
        assert plan["plan_status"] == "IMPLEMENTING"
        assert plan["version"] == plan_before["version"]
        assert plan["approved_by_user_id"] is not None
        assert len(reports) == 1
        assert reports[0]["status"] == "SUBMITTED"
        assert reports[0]["adjudicated_by_user_id"] is None


class TestAuditorReadOnly:
    """The one role with an empty write set and the widest read set."""

    def test_the_auditor_reads_all_five_trees_and_is_refused_every_write(self, api):
        """Five reads succeed without an X-User-ID; three writes are refused; the clock is the exception.

        PRD: "A third, read-only party - the auditor - sees everything and changes
        nothing."

        PRD: "`X-User-ID` must be present and non-empty whenever `X-User-Role` is
        `Proponent` or `WildlifeAgency`; the `Auditor` and `Anonymous` roles do not
        require it."

        PRD: "List every mitigation commitment drawn against a bank, across all plans.
        Unpaginated; restricted because it exposes other proponents' commitments."

        The bank-commitment ledger is the single asymmetry in the read matrix: the
        auditor sees it and the proponent whose own commitments are on it does not.
        The refused writes include a pure state transition, so an empty exclusive
        operation set means no writes at all rather than no creations.

        Design: Corner/rbac/the_auditor_reads_every_tree_and_writes_nothing
        """
        scenario = setup_canonical_permit()
        auditor = auditor_headers_without_user_id()
        proponent_headers = scenario["proponent_headers"]
        bank_id = scenario["bank"]["id"]

        assert "X-User-ID" not in auditor

        action = get_success_data(
            api_client.get_project_action(scenario["action"]["id"], auditor), 200
        )
        consultation = get_success_data(
            api_client.get_consultation(scenario["consultation"]["id"], auditor), 200
        )
        opinions = assert_unpaginated_list(
            api_client.list_biological_opinions(scenario["consultation"]["id"], auditor)
        )
        plan = get_success_data(
            api_client.get_habitat_conservation_plan(scenario["plan"]["id"], auditor), 200
        )
        commitments = assert_unpaginated_list(
            api_client.list_bank_mitigation_commitments(bank_id, auditor)
        )

        assert action["status"] == "PERMITTED"
        assert consultation["status"] == "OPINION_ISSUED"
        assert len(opinions) == 1
        assert opinions[0]["conclusion"] == "NO_JEOPARDY"
        assert plan["plan_status"] == "IMPLEMENTING"
        assert len(commitments) == 2
        assert commitments[0]["status"] == "SECURED"

        assert_error_envelope(
            api_client.list_bank_mitigation_commitments(bank_id, proponent_headers),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        auditor_writes = [
            api_client.create_species(
                species_payload(
                    scientific_name="Rana draytonii",
                    common_name="California red-legged frog",
                    listing_status="THREATENED",
                ),
                auditor,
            ),
            api_client.run_effect_determination(scenario["action"]["id"], auditor),
            api_client.decide_plan(
                scenario["plan"]["id"],
                plan_decision_payload(
                    decision="RETURN_FOR_REVISION", decision_note="Auditor decision."
                ),
                auditor,
            ),
        ]
        for response in auditor_writes:
            assert_error_envelope(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        clock = get_success_data(
            api_client.set_clock("2026-11-01T00:00:00Z", auditor), 200
        )

        assert clock == {}

        after = read_plan(scenario["plan"]["id"])

        assert after["plan_status"] == "IMPLEMENTING"
        assert after["version"] == plan["version"]


class TestAnonymousSingleOperation:
    """Self-registration is the whole of the anonymous surface."""

    def test_registration_succeeds_and_every_other_endpoint_including_the_clock_is_403(
        self, api
    ):
        """The anonymous caller cannot even read back the row it just minted.

        PRD: "`X-User-Role` must be present and non-empty on every endpoint; the single
        exception is proponent self-registration, which is exempt from the
        header-presence check altogether, is reachable by the `Anonymous` role, and is
        the only way a proponent identity comes into existence in the first place."

        PRD: "Registration returns the new proponent row, and the `id` on that row is
        the value the organisation presents in `X-User-ID` on every subsequent call. A
        freshly registered proponent has `compliance_standing_score` at 100.00,
        `compliance_variant_applied` at `LIFETIME`, and `open_reinitiation_count` at 0,
        because no reports exist yet to score it against."

        PRD: "Exactly four roles exist: `Proponent`, `WildlifeAgency`, `Auditor`, and
        `Anonymous`. A role string outside that set of four is treated as
        **unauthenticated**, not as forbidden - it also yields `ERR_UNAUTHENTICATED`
        with HTTP 401, never a 403."

        `Anonymous` is inside that set of four, so its refusals are 403 rather than the
        401 an undeclared role string would draw, and the refused clock write leaves the
        clock where it stood.

        Design: Corner/rbac/anonymous_has_exactly_one_permitted_operation
        """
        set_clock(CANONICAL_CLOCK)
        species = register_species()
        anonymous = anonymous_headers()

        assert "X-User-ID" not in anonymous

        registered = get_success_data(
            api_client.create_proponent(
                proponent_payload(
                    org_name="Harbor Sands Quarry LLC",
                    contact_email="permits@harbor-sands.example",
                    is_federal_agency=False,
                ),
                anonymous,
            ),
            201,
        )
        new_proponent_id = registered["id"]

        assert registered["compliance_standing_score"] == 100.00
        assert registered["compliance_variant_applied"] == "LIFETIME"
        assert registered["open_reinitiation_count"] == 0

        anonymous_refusals = [
            api_client.get_proponent(new_proponent_id, anonymous),
            api_client.get_species(species["id"], anonymous),
            api_client.create_species(
                species_payload(
                    scientific_name="Rana draytonii",
                    common_name="California red-legged frog",
                    listing_status="THREATENED",
                ),
                anonymous,
            ),
            api_client.set_clock("2027-01-01T00:00:00Z", anonymous),
        ]
        for response in anonymous_refusals:
            assert_error_envelope(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        own_headers = make_proponent_headers(new_proponent_id)
        readable = get_success_data(
            api_client.get_proponent(new_proponent_id, own_headers), 200
        )

        assert readable["id"] == new_proponent_id
        assert readable["compliance_standing_score"] == 100.00

        witness = get_success_data(
            api_client.create_project_action(
                project_action_payload(new_proponent_id, action_name="Anonymous Witness"),
                own_headers,
            ),
            201,
        )

        assert_same_instant(witness["created_at"], CANONICAL_CLOCK, "created_at")


class TestSharedClockWrite:
    """One global clock, three roles that may move it, one that may not."""

    def test_three_roles_move_the_same_clock_and_the_last_write_stamps_the_next_row(
        self, api
    ):
        """Proponent, auditor and agency writes all take, anonymous is refused, and rows read the survivor.

        PRD: "Any role - proponent, agency official, or auditor - may advance or
        reposition it through an administrative test-driving capability that accepts a
        single field, `to_iso8601`, carrying the instant to move to."

        PRD: "Nothing in this system reads the host's wall clock."

        PRD: "Instants supplied by clients (there is exactly one such field, discussed
        under the logical clock below) must be ISO 8601 UTC with a trailing `Z` and
        either whole seconds or exactly three fractional digits; both forms are accepted
        and denote the same instant."

        There is no per-role clock: the row created after three successive writes by
        three different roles is stamped from the last write that succeeded, whoever
        made it, and two reads with no clock call between them are identical.

        Design: Corner/rbac/the_clock_endpoint_is_the_only_write_shared_across_roles
        """
        set_clock(CANONICAL_CLOCK)
        register_species()
        proponent = register_proponent()
        proponent_headers = make_proponent_headers(proponent["id"])

        for headers, instant in (
            (proponent_headers, "2026-11-01T00:00:00Z"),
            (auditor_headers_without_user_id(), "2026-12-01T00:00:00Z"),
            (REGISTRAR, "2027-01-15T00:00:00Z"),
        ):
            assert get_success_data(api_client.set_clock(instant, headers), 200) == {}

        assert_error_envelope(
            api_client.set_clock("2027-02-01T00:00:00Z", anonymous_headers()),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        witness = get_success_data(
            api_client.create_project_action(
                project_action_payload(proponent["id"], action_name="Clock Witness Action"),
                proponent_headers,
            ),
            201,
        )

        assert_same_instant(witness["created_at"], "2027-01-15T00:00:00Z", "created_at")

        first_read = read_action(witness["id"])
        second_read = read_action(witness["id"])

        assert first_read["created_at"] == second_read["created_at"]
        assert first_read["updated_at"] == second_read["updated_at"]
        assert first_read["version"] == second_read["version"]

        assert get_success_data(
            api_client.set_clock("2027-01-15T00:00:00.000Z", REGISTRAR), 200
        ) == {}

        second_witness = get_success_data(
            api_client.create_project_action(
                project_action_payload(proponent["id"], action_name="Fractional Witness"),
                proponent_headers,
            ),
            201,
        )

        assert_same_instant(
            second_witness["created_at"], witness["created_at"], "created_at"
        )


class TestProponentIdentityIsEntityBacked:
    """Three near-identical bad requests split 403, 404 and 403 - and none is a 401."""

    def test_the_body_is_bound_to_the_header_and_an_unknown_header_is_an_ownership_failure(
        self, api
    ):
        """Naming a rival is 403, naming nobody is 404, and being nobody is 403.

        PRD: "When `X-User-Role` is `Proponent`, `X-User-ID` is the `id` of the acting
        `Proponent` row; ownership checks on any resource that reaches a `Proponent` -
        directly through a project action's `proponent_id`, or transitively through a
        plan, a permit, a consultation, a monitoring report, or a circumstance event -
        compare the resolved owner against `X-User-ID`."

        PRD: "The same code applies when `X-User-ID` on a `Proponent` request names no
        `Proponent` row at all - an unknown proponent identity is an ownership failure
        on every proponent endpoint, never an authentication failure."

        PRD: "There is one non-path variant of the same rule: when a proponent registers
        a new project action, the `proponent_id` in the body must be the proponent named
        by `X-User-ID`, so that no proponent can open an action in another's name. If
        that body `proponent_id` resolves to no row at all, the ownership check does not
        fire and the request instead falls through to referential resolution and is
        reported as `ERR_PROPONENT_NOT_FOUND`."

        Proponent B may open its own action with the very payload that was refused to A,
        so the refusals are about the identity pairing rather than about the body.

        Design: Corner/rbac/proponent_identity_is_entity_backed_and_bound_to_the_body
        """
        scenario = build_scenario("effect_determination")
        headers_a = scenario["proponent_headers"]
        proponent_a_id = scenario["proponent"]["id"]
        proponent_b = register_proponent(
            org_name="Rival Grading Company LLC",
            contact_email="permits@rival-grading.example",
        )
        headers_b = make_proponent_headers(proponent_b["id"])
        rival_payload = project_action_payload(
            proponent_b["id"], action_name="Filed In Rivals Name", footprint_acres=40.00
        )

        assert proponent_b["id"] != proponent_a_id

        assert_error_envelope(
            api_client.create_project_action(rival_payload, headers_a),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )
        assert_error_envelope(
            api_client.create_project_action(
                project_action_payload(
                    NON_EXISTENT_ID, action_name="Filed For Nobody", footprint_acres=40.00
                ),
                headers_a,
            ),
            ApiErrorId.ERR_PROPONENT_NOT_FOUND,
            404,
        )
        assert_error_envelope(
            api_client.get_project_action(
                scenario["action"]["id"], make_proponent_headers(NON_EXISTENT_ID)
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            403,
        )

        own_action = get_success_data(
            api_client.create_project_action(
                project_action_payload(
                    proponent_b["id"],
                    action_name="Rival Own Action",
                    footprint_acres=40.00,
                ),
                headers_b,
            ),
            201,
        )

        assert own_action["proponent_id"] == proponent_b["id"]

        b_rows, b_meta = validate_paginated(
            api_client.list_project_actions(AUDITOR, {"proponent_id": proponent_b["id"]})
        )
        a_rows, a_meta = validate_paginated(
            api_client.list_project_actions(AUDITOR, {"proponent_id": proponent_a_id})
        )

        assert b_meta["total_count"] == 1
        assert b_rows[0]["id"] == own_action["id"]
        assert a_meta["total_count"] == 1
        assert a_rows[0]["id"] == scenario["action"]["id"]
