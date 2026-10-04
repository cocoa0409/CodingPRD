"""Fixed validation ordering: earlier checks mask later ones."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_patient,
    create_visit_request_payload,
    get_success_data,
    set_clock,
    setup_market_team_shift,
    validate_error,
    validate_success,
)

NURSE = TEST_USERS["triage_nurse_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestValidationEvaluationOrder:
    def test_state_error_wins_when_visit_not_triaged(self, api):
        """PRD §2.11: "When several checks could reject the same request, they
        are evaluated in a fixed priority order so the client always sees the
        most fundamental failure first: ... then (6) the target entity's
        state-machine eligibility, and only then (7) the business rules —
        safety, temporal, fiscal, and payload shape — in the order each
        subsection of §3 lists them. A request failing an earlier check never
        surfaces a later check's error code."
        PRD §3.2: "Any action attempted against a visit that is not in a state
        from which that action is defined is rejected with
        `ERR_VR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_dispatch_offer
        """
        ctx = setup_market_team_shift(
            app_user="app-H", tech_user="tech-H", md_user="md-H"
        )
        patient = create_patient(
            full_name="Hank H", member_id="M900", pcp_npi="6666666666"
        )
        # Visit left in INTAKE: a dispatch offer is not defined from INTAKE,
        # so the state-machine eligibility check must fire.
        vr = get_success_data(
            api.create_visit_request(
                create_visit_request_payload(
                    patient["id"], ctx["market"]["id"], chief_complaint="cough"
                ),
                NURSE,
            )
        )
        resp = api.create_dispatch_offer(
            vr["id"],
            {"expected_visit_request_version": vr["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_VR_INVALID_STATE)
        vr_after = validate_success(api.get_visit_request(vr["id"], DISPATCHER))
        assert vr_after["status"] == "INTAKE"

    def test_state_error_masks_empty_selector_pool(self, api):
        """PRD §2.11: "then (6) the target entity's state-machine eligibility,
        and only then (7) the business rules — safety, temporal, fiscal, and
        payload shape — in the order each subsection of §3 lists them."
        PRD §3.4: "An empty pool refuses the offer with
        `ERR_NO_AVAILABLE_CARE_TEAM` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_dispatch_offer
        """
        # A visit in INTAKE in a market with no AVAILABLE team at all: both a
        # state failure and (potentially) an empty-pool failure apply; the
        # state-machine check fires first.
        set_clock()
        ctx = setup_market_team_shift(
            app_user="app-H2", tech_user="tech-H2", md_user="md-H2",
            go_available=False, start_shift=False,
        )
        patient = create_patient(
            full_name="Hank H2", member_id="M901", pcp_npi="6666666661"
        )
        vr = get_success_data(
            api.create_visit_request(
                create_visit_request_payload(
                    patient["id"], ctx["market"]["id"], chief_complaint="cough"
                ),
                NURSE,
            )
        )
        resp = api.create_dispatch_offer(
            vr["id"],
            {"expected_visit_request_version": vr["version"]},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_VR_INVALID_STATE)
