"""The upper rungs of the validation ladder: headers, roles, ownership, shape.

Each test translates one `validations` instance from the corner design index and
probes a rung boundary: the asymmetric header rule, the 401/403 split between an
unknown role string and a declared-but-unpermitted one, role before path
existence, the four ownership hops, the nine defects that collapse into one 400,
the two segregation-of-duties comparisons, bank species eligibility, and the
consultation-type gate.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_error_envelope, assert_unpaginated_list
from test_helpers.constants import NON_EXISTENT_ID
from test_helpers.factories import (
    adjudication_payload,
    concurrence_payload,
    conservation_bank_payload,
    critical_habitat_unit_payload,
    incidental_take_permit_payload,
    proponent_payload,
    species_payload,
)
from test_helpers.fixtures import (
    APPROVER,
    ISSUER,
    REGISTRAR,
    REVIEWER,
    adjudicate_report,
    build_scenario,
    file_monitoring_report,
    issue_permit,
    read_consultation,
    record_field_survey,
    register_proponent,
    register_species,
    run_effect_determination,
    set_clock,
    setup_second_action,
    submit_biological_assessment,
)
from test_helpers.test_users import (
    anonymous_headers,
    auditor_headers_without_user_id,
    headers_with_blank_user_id,
    headers_with_unknown_role,
    headers_without_role,
    make_proponent_headers,
)


class TestAuthenticationHeaderShape:
    """Rung one is asymmetric: two roles need an identity and one endpoint needs nothing."""

    def test_a_blank_identity_fails_while_an_auditor_without_one_succeeds(self, api):
        """Four probes walk every branch of the header-presence rule.

        PRD: "`X-User-Role` must be present and non-empty on every endpoint; the
        single exception is proponent self-registration, which is exempt from the
        header-presence check altogether, is reachable by the `Anonymous` role, and is
        the only way a proponent identity comes into existence in the first place.
        `X-User-ID` must be present and non-empty whenever `X-User-Role` is
        `Proponent` or `WildlifeAgency`; the `Auditor` and `Anonymous` roles do not
        require it."

        PRD: "A missing, empty, or whitespace-only `X-User-Role`, and a missing or
        empty `X-User-ID` on a `Proponent` or `WildlifeAgency` request, are both
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        A present-but-blank `X-User-ID` is not a supplied identity, while an auditor
        that never sends one reads the action at 200.

        Design: Corner/validations/absent_or_blank_auth_headers_are_401_and_only_proponent_creation_is_exempt
        """
        scenario = build_scenario(
            "action", include_unit=False, include_threatened=False, include_bank=False
        )

        no_role = api_client.get_species(scenario["species"]["id"], headers_without_role())
        assert_error_envelope(no_role, ApiErrorId.ERR_UNAUTHENTICATED, 401)

        blank_user = api_client.list_project_actions(headers_with_blank_user_id("Proponent"))
        assert_error_envelope(blank_user, ApiErrorId.ERR_UNAUTHENTICATED, 401)

        seen = get_success_data(
            api_client.get_project_action(
                scenario["action"]["id"], auditor_headers_without_user_id()
            ),
            200,
        )

        assert seen["status"] == "SCREENING"

        registered = get_success_data(
            api_client.create_proponent(
                proponent_payload(
                    org_name="Coastal Aggregates Inc",
                    contact_email="compliance@coastal-agg.example",
                ),
                anonymous_headers(),
            ),
            201,
        )

        assert registered["id"] != scenario["proponent"]["id"]


class TestUnknownRoleVersusUnpermittedRole:
    """Rung two answers before rung three, so a stray role string reads as 401."""

    def test_anonymous_is_forbidden_while_an_undeclared_role_is_unauthenticated(self, api):
        """One request, two header sets, two different rungs.

        PRD: "A role string outside that set of four is treated as
        **unauthenticated**, not as forbidden - it also yields `ERR_UNAUTHENTICATED`
        with HTTP 401, never a 403."

        PRD: "the `Anonymous` role can perform exactly one operation, proponent
        self-registration, with every other endpoint likewise returning
        `ERR_ROLE_NOT_PERMITTED`."

        Both calls are refused, but `Anonymous` is a declared role that this endpoint
        does not list, while `Regulator` names no role at all.

        Design: Corner/validations/declared_but_unpermitted_role_is_403_while_an_unknown_role_string_is_401
        """
        scenario = build_scenario(
            "action", include_unit=False, include_threatened=False, include_bank=False
        )
        action_id = scenario["action"]["id"]

        forbidden = api_client.get_project_action(action_id, anonymous_headers())
        assert_error_envelope(forbidden, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        unknown = api_client.get_project_action(
            action_id, headers_with_unknown_role("Regulator", scenario["proponent"]["id"])
        )
        assert_error_envelope(unknown, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleRungPrecedesPathResolution:
    """A forbidden role never learns whether the path resolves."""

    def test_an_auditor_write_to_a_nonexistent_species_is_403_not_404(self, api):
        """The same body is 403 for an auditor and 404 for the registrar.

        PRD: "Requests are checked against an ordered ladder of 29 rules, and the
        **first** rule violated decides the response."

        PRD: "(3) The role being permitted on the target endpoint -
        `ERR_ROLE_NOT_PERMITTED`. (4) Left-to-right path existence - the eleven 404
        codes."

        PRD: "The `Auditor` role can perform no write of any kind - every write
        attempt by an auditor returns `ERR_ROLE_NOT_PERMITTED`"

        Neither call designates anything, so the real species still has no units.

        Design: Corner/validations/role_permission_is_decided_before_the_path_ids_are_resolved
        """
        species = register_species()
        payload = critical_habitat_unit_payload(unit_code="CHU-9", acres=100.00)

        role_first = api_client.create_critical_habitat_unit(
            NON_EXISTENT_ID, payload, auditor_headers_without_user_id()
        )
        assert_error_envelope(role_first, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

        then_missing = api_client.create_critical_habitat_unit(
            NON_EXISTENT_ID, payload, REGISTRAR
        )
        assert_error_envelope(then_missing, ApiErrorId.ERR_SPECIES_NOT_FOUND, 404)

        units = assert_unpaginated_list(
            api_client.list_critical_habitat_units(species["id"], REGISTRAR)
        )

        assert units == []


class TestOwnershipThroughTheParentChain:
    """One, two, three and four hops all resolve to the same owner."""

    def test_a_second_proponent_is_refused_at_every_depth_of_the_tree(self, api):
        """Action, consultation, plan and permit all reject proponent B.

        PRD: "A proponent may read and write only its own action tree. Reaching
        another proponent's project action, consultation, habitat conservation plan,
        incidental take permit, monitoring report, or changed-circumstance event is
        rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        PRD: "(4) Left-to-right path existence - the eleven 404 codes. (5) Proponent
        ownership of the target resource - `ERR_NOT_RESOURCE_OWNER`."

        PRD: "When `X-User-Role` is `Auditor`, `X-User-ID` is likewise an opaque
        operator identifier that is not tied to any persisted entity and is never
        compared to a row's `id`."

        A permit id that resolves to nothing is a 404 for the same caller, because
        existence is settled one rung above ownership, and the auditor reads the permit
        outright.

        Design: Corner/validations/proponent_ownership_is_resolved_through_the_whole_parent_chain
        """
        scenario = build_scenario("permit")
        intruder = register_proponent(
            org_name="Coastal Aggregates Inc",
            contact_email="compliance@coastal-agg.example",
        )
        intruder_headers = make_proponent_headers(intruder["id"])

        for response in (
            api_client.get_project_action(scenario["action"]["id"], intruder_headers),
            api_client.get_consultation(scenario["consultation"]["id"], intruder_headers),
            api_client.get_habitat_conservation_plan(scenario["plan"]["id"], intruder_headers),
            api_client.get_incidental_take_permit(scenario["permit"]["id"], intruder_headers),
        ):
            assert_error_envelope(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        missing = api_client.get_incidental_take_permit(NON_EXISTENT_ID, intruder_headers)
        assert_error_envelope(missing, ApiErrorId.ERR_PERMIT_NOT_FOUND, 404)

        audited = get_success_data(
            api_client.get_incidental_take_permit(
                scenario["permit"]["id"], auditor_headers_without_user_id()
            ),
            200,
        )

        assert audited["permit_number"] == "ITP-000001"

        owner = scenario["proponent_headers"]
        for response in (
            api_client.get_project_action(scenario["action"]["id"], owner),
            api_client.get_consultation(scenario["consultation"]["id"], owner),
            api_client.get_habitat_conservation_plan(scenario["plan"]["id"], owner),
            api_client.get_incidental_take_permit(scenario["permit"]["id"], owner),
        ):
            assert response.status_code == 200, response.text


class TestSchemaRungCollapsesEveryDefect:
    """Nine structurally different defects, one error id, one status."""

    def test_missing_unknown_typed_enum_scale_and_bound_defects_are_all_400(self, api):
        """The widest rung on the ladder never says which field went wrong.

        PRD: "It requires every mandatory field present, no unknown fields, correct
        JSON types, enum values drawn from the declared member set for that field,
        monetary fields as non-negative integers, quantity fields non-negative and
        carrying at most two decimal places, month fields as integers between 1 and 12
        inclusive, `permit_term_years` as an integer between 1 and 50 inclusive,
        calendar dates as valid `YYYY-MM-DD` values, and instants as valid ISO 8601
        UTC values."

        PRD: "Two cross-field checks also live at rung 7 rather than lower:
        `construction_start_date` must not be later than `construction_end_date` on
        project-action registration"

        The inverted date pair is therefore a 400 rather than one of the 422 temporal
        errors, and `permit_term_years` is refused at 0, at 50.5 and at 51 while 50 is
        accepted.

        Design: Corner/validations/every_input_schema_violation_collapses_to_one_400_error_id
        """
        scenario = build_scenario("opinion")
        proponent_id = scenario["proponent"]["id"]
        headers = scenario["proponent_headers"]
        action_id = scenario["action"]["id"]

        def action_body(**overrides):
            body = {
                "proponent_id": proponent_id,
                "action_name": "Probe Action",
                "action_type": "NON_FEDERAL",
                "footprint_acres": 200.00,
                "county_code": "06037",
                "construction_start_date": "2027-01-01",
                "construction_end_date": "2027-12-31",
            }
            body.update(overrides)
            return body

        missing = action_body()
        del missing["county_code"]
        unknown = action_body(estimated_cost_cents=90_000_000)
        wrong_type = action_body(footprint_acres="200.00")
        bad_enum = action_body(action_type="STATE_FUNDED")
        bad_scale = action_body(footprint_acres=200.005)
        inverted = action_body(
            construction_start_date="2027-12-31", construction_end_date="2027-01-01"
        )

        for body in (missing, unknown, wrong_type, bad_enum, bad_scale, inverted):
            assert_error_envelope(
                api_client.create_project_action(body, headers),
                ApiErrorId.ERR_INVALID_REQUEST,
                400,
            )

        bad_month = api_client.create_species(
            species_payload(
                scientific_name="Rana draytonii",
                common_name="California red-legged frog",
                survey_season_start_month=13,
            ),
            REGISTRAR,
        )
        assert_error_envelope(bad_month, ApiErrorId.ERR_INVALID_REQUEST, 400)

        for term in (0, 50.5, 51):
            bad_term = api_client.create_habitat_conservation_plan(
                action_id,
                {"plan_name": "Overlong Term HCP", "covered_acres": 20.00, "permit_term_years": term},
                headers,
            )
            assert_error_envelope(bad_term, ApiErrorId.ERR_INVALID_REQUEST, 400)

        bad_cents = api_client.create_conservation_bank(
            conservation_bank_payload(
                scenario["species"]["id"],
                bank_name="Fractional Cents Bank",
                credit_price_cents=250_000.5,
                credits_total_minted=100.00,
            ),
            REGISTRAR,
        )
        assert_error_envelope(bad_cents, ApiErrorId.ERR_INVALID_REQUEST, 400)

        rows, meta = validate_paginated(api_client.list_project_actions(headers))

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [action_id]

        accepted = get_success_data(
            api_client.create_habitat_conservation_plan(
                action_id,
                {"plan_name": "Upper Bound HCP", "covered_acres": 20.00, "permit_term_years": 50},
                headers,
            ),
            201,
        )

        assert accepted["permit_term_years"] == 50


class TestSegregationOfDuties:
    """Two rungs compare the caller against a user id stored on another row."""

    def test_the_approver_cannot_issue_and_the_issuer_cannot_adjudicate(self, api):
        """Two different error ids for two different identity comparisons.

        PRD: "The official who approved a habitat conservation plan may not also issue
        that plan's incidental take permit: an issuance request whose `X-User-ID`
        equals the plan's `approved_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The official who issued a permit may
        not adjudicate compliance reports filed against it: an adjudication whose
        `X-User-ID` equals the permit's `issued_by_user_id` is rejected with
        `ERR_ADJUDICATOR_CONFLICT` (HTTP 403)."

        The refusals are about identity, not state: the same issuance succeeds as a
        different official, and the approving official is free to adjudicate because
        rung 12 compares only against the permit's issuer.

        Design: Corner/validations/segregation_of_duties_separates_approver_issuer_and_adjudicator
        """
        scenario = build_scenario("approved")
        plan_id = scenario["plan"]["id"]

        assert scenario["plan"]["approved_by_user_id"] == "fws-user-approver"

        refused = api_client.issue_incidental_take_permit(
            plan_id, incidental_take_permit_payload(), APPROVER
        )
        assert_error_envelope(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        permit = issue_permit(plan_id)

        assert permit["issued_by_user_id"] == "fws-user-issuer"

        set_clock("2027-05-16T00:00:00Z")
        first = file_monitoring_report(
            permit["id"],
            scenario["proponent"],
            period_start="2027-01-01",
            period_end="2027-04-01",
            take_units_reported=0.50,
            mitigation_units_verified=59.72,
        )

        conflicted = api_client.adjudicate_monitoring_report(
            first["id"], adjudication_payload(), ISSUER
        )
        assert_error_envelope(conflicted, ApiErrorId.ERR_ADJUDICATOR_CONFLICT, 403)

        adjudicated = adjudicate_report(first["id"], "ACCEPT")

        assert adjudicated["status"] == "ACCEPTED"
        assert adjudicated["adjudicated_by_user_id"] == "fws-user-adjudicator"

        set_clock("2027-08-16T00:00:00Z")
        second = file_monitoring_report(
            permit["id"],
            scenario["proponent"],
            period_start="2027-04-01",
            period_end="2027-07-01",
            take_units_reported=0.50,
            mitigation_units_verified=59.72,
        )
        by_approver = adjudicate_report(second["id"], "ACCEPT", headers=APPROVER)

        assert by_approver["status"] == "ACCEPTED"
        assert by_approver["adjudicated_by_user_id"] == "fws-user-approver"


class TestConservationBankSpeciesEligibility:
    """Only two of the four listing statuses carry sellable credits."""

    def test_proposed_and_candidate_species_are_422_while_a_ghost_species_is_404(self, api):
        """Rung 6 answers before rung 13, so a bad key and a bad status differ.

        PRD: "A bank may only be established for a species whose `listing_status` is
        `ENDANGERED` or `THREATENED`; `PROPOSED` and `CANDIDATE` species carry no take
        liability and therefore no sellable credits, so naming one is
        `ERR_SPECIES_NOT_LISTED` (HTTP 422)."

        PRD: "A conservation bank's `covered_species_id` resolves against the species
        table and reports `ERR_SPECIES_NOT_FOUND` when it names nothing."

        The THREATENED species takes its bank at 201, and no partial row survives
        either 422.

        Design: Corner/validations/conservation_banks_may_only_cover_a_listed_species
        """
        scenario = build_scenario("registry", include_unit=False, include_bank=False)
        proposed = register_species(
            scientific_name="Coccyzus americanus",
            common_name="Western yellow-billed cuckoo",
            listing_status="PROPOSED",
        )
        candidate = register_species(
            scientific_name="Anaxyrus californicus",
            common_name="Arroyo toad",
            listing_status="CANDIDATE",
        )

        for species_id, bank_name in (
            (proposed["id"], "Cuckoo Riparian Bank"),
            (candidate["id"], "Arroyo Toad Bank"),
        ):
            response = api_client.create_conservation_bank(
                conservation_bank_payload(
                    species_id, bank_name=bank_name, credits_total_minted=100.00
                ),
                REGISTRAR,
            )
            assert_error_envelope(response, ApiErrorId.ERR_SPECIES_NOT_LISTED, 422)

        ghost = api_client.create_conservation_bank(
            conservation_bank_payload(
                NON_EXISTENT_ID, bank_name="Ghost Species Bank", credits_total_minted=100.00
            ),
            REGISTRAR,
        )
        assert_error_envelope(ghost, ApiErrorId.ERR_SPECIES_NOT_FOUND, 404)

        listed = get_success_data(
            api_client.create_conservation_bank(
                conservation_bank_payload(
                    scenario["threatened_species"]["id"], bank_name="Vireo Riparian Bank"
                ),
                REGISTRAR,
            ),
            201,
        )

        assert listed["covered_species_id"] == scenario["threatened_species"]["id"]

        empty = assert_unpaginated_list(
            api_client.list_species_conservation_banks(proposed["id"], REGISTRAR)
        )

        assert empty == []


class TestConsultationTypeGate:
    """Both concluding endpoints leave UNDER_REVIEW, so only the type separates them."""

    def test_each_conclusion_endpoint_refuses_the_other_branch(self, api):
        """Concurrence on a FORMAL row and an opinion on an INFORMAL row both 422.

        PRD: "Concurrence is available only on an `INFORMAL` consultation; attempting
        it on a `FORMAL` one is `ERR_CONSULTATION_TYPE_MISMATCH` (HTTP 422).
        Symmetrically, a formal consultation concludes by biological opinion, and
        attempting an opinion on an `INFORMAL` consultation is the same
        `ERR_CONSULTATION_TYPE_MISMATCH`."

        Neither refusal disturbs the row: both consultations remain `UNDER_REVIEW`, no
        opinion is created, and the correctly paired calls then conclude each branch.

        Design: Corner/validations/only_the_matching_consultation_type_may_be_concluded
        """
        scenario = build_scenario("ba_submitted")
        formal_id = scenario["consultation"]["id"]

        assert scenario["consultation"]["consultation_type"] == "FORMAL"
        assert scenario["consultation"]["status"] == "UNDER_REVIEW"

        informal_action = setup_second_action(scenario)
        record_field_survey(
            informal_action,
            scenario["proponent"],
            scenario["threatened_species"]["id"],
            habitat_overlap_acres=10.00,
        )
        informal_action = run_effect_determination(informal_action, scenario["proponent"])
        informal_id = informal_action["active_consultation_id"]
        informal = submit_biological_assessment(informal_id, scenario["proponent"])

        assert informal_action["effect_determination"] == "NLAA"
        assert informal["consultation_type"] == "INFORMAL"
        assert informal["status"] == "UNDER_REVIEW"

        wrong_concurrence = api_client.record_concurrence(
            formal_id, concurrence_payload(), REVIEWER
        )
        assert_error_envelope(
            wrong_concurrence, ApiErrorId.ERR_CONSULTATION_TYPE_MISMATCH, 422
        )
        wrong_opinion = api_client.issue_biological_opinion(informal_id, {}, ISSUER)
        assert_error_envelope(wrong_opinion, ApiErrorId.ERR_CONSULTATION_TYPE_MISMATCH, 422)

        assert read_consultation(formal_id)["status"] == "UNDER_REVIEW"
        assert read_consultation(informal_id)["status"] == "UNDER_REVIEW"
        assert (
            assert_unpaginated_list(api_client.list_biological_opinions(informal_id, REVIEWER))
            == []
        )

        concurred = get_success_data(
            api_client.record_concurrence(informal_id, concurrence_payload(), REVIEWER), 200
        )
        opinion = get_success_data(
            api_client.issue_biological_opinion(formal_id, {}, ISSUER), 201
        )

        assert concurred["status"] == "CONCLUDED_CONCURRENCE"
        assert opinion["consultation_id"] == formal_id
