"""Merger review: comment windows, amendments, public interest decisions (PRD §3.6, §2.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    add_service_assurance_plan,
    amend_merger_payload,
    api_client,
    create_merger,
    decide_merger_payload,
    get_merger_data,
    get_plan_data,
    make_carrier_operator_headers,
    register_merger_pair,
    set_clock,
    setup_merger_with_plan,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_adjudicator_headers"]


class TestDecisionBranches:
    def test_merger_decision_branches_diverge_on_score_band(self):
        """PRD §3.6: "requires a `public_interest_score` of at least 45.00 but
        less than 60.00, at least one service assurance plan already on the
        application (`ERR_SERVICE_ASSURANCE_PLAN_REQUIRED`, HTTP 409), and a
        `conditions` input that is a non-empty array of condition strings (an
        absent or empty array is `ERR_INVALID_REQUEST`, HTTP 400)." (the
        `APPROVED_WITH_CONDITIONS` branch)
        PRD §3.6: "when the merger is decided `APPROVED` or
        `APPROVED_WITH_CONDITIONS` the plan moves to `MONITORING`; when the
        merger is `REJECTED` the plan becomes `MOOT`, a terminal state."

        Design: Difficulty/non_linear_state_machine/merger_decision_branches_diverge_on_score_band
        """
        acquirer, target = register_merger_pair()
        conditions = ["Five-year service assurance oversight",
                      "Gateway interchange commitment enforceable"]
        m1, sap1 = setup_merger_with_plan(
            acquirer["id"], target["id"],
            merger_overrides={
                "competition_preservation_score": 50,
                "service_reliability_score": 70,
                "shipper_impact_score": 60},
            plan_overrides={
                "plan_name": "M1 Service Assurance Plan",
                "commitments": ["Maintain Gulf gateway interchange windows",
                                "48-hour car supply restoration"]})
        assert m1["public_interest_score"] == pytest.approx(59.00)
        m2, sap2 = setup_merger_with_plan(
            acquirer["id"], target["id"],
            merger_overrides={
                "transaction_value_cents": 500000000,
                "competition_preservation_score": 40,
                "service_reliability_score": 50,
                "shipper_impact_score": 40},
            plan_overrides={
                "plan_name": "M2 Service Assurance Plan",
                "commitments": ["Hire 200 operating craft"]})
        assert m2["public_interest_score"] == pytest.approx(43.00)

        set_clock("2026-10-16T00:00:00Z")
        decided_m1 = validate_success(api_client.decide_merger_application(
            m1["id"],
            decide_merger_payload("APPROVED_WITH_CONDITIONS", conditions),
            BOARD))
        assert decided_m1["status"] == "APPROVED_WITH_CONDITIONS"
        assert decided_m1["conditions_imposed"] == conditions
        assert get_plan_data(m1["id"], sap1["id"])["status"] == "MONITORING"

        decided_m2 = validate_success(api_client.decide_merger_application(
            m2["id"], decide_merger_payload("REJECTED"), BOARD))
        assert decided_m2["status"] == "REJECTED"
        assert get_plan_data(m2["id"], sap2["id"])["status"] == "MOOT"

    def test_public_interest_score_bands_enforced(self):
        """PRD §3.6: "`ERR_DECISION_INCONSISTENT_WITH_SCORE` (HTTP 422) fires
        whenever the requested outcome does not match the band the
        `public_interest_score` has earned."
        PRD §2.6: "Every request is validated against the following seventeen
        checks in strict priority order. The first check that fails determines
        the response; no later check is evaluated." (plan-required gate 11
        precedes score consistency gate 12).

        Design: Corner/calculations/public_interest_score_bands_enforced
        """
        acquirer, target = register_merger_pair()
        merger = create_merger(
            acquirer["id"], target["id"],
            competition_preservation_score=50, service_reliability_score=70,
            shipper_impact_score=60)
        assert merger["public_interest_score"] == pytest.approx(59.00)
        set_clock("2026-10-16T00:00:00Z")

        resp1 = api_client.decide_merger_application(
            merger["id"], decide_merger_payload("APPROVED"), BOARD)
        validate_error(resp1, ApiErrorId.ERR_DECISION_INCONSISTENT_WITH_SCORE)

        resp2 = api_client.decide_merger_application(
            merger["id"],
            decide_merger_payload("APPROVED_WITH_CONDITIONS", ["Oversight"]),
            BOARD)
        validate_error(resp2, ApiErrorId.ERR_SERVICE_ASSURANCE_PLAN_REQUIRED)

        plan = add_service_assurance_plan(
            merger["id"], acquirer["id"],
            plan_name="Late SAP",
            commitments=["Weekly service metrics to the Board"])
        decided = validate_success(api_client.decide_merger_application(
            merger["id"],
            decide_merger_payload("APPROVED_WITH_CONDITIONS", ["Oversight"]),
            BOARD))
        assert decided["status"] == "APPROVED_WITH_CONDITIONS"
        assert get_plan_data(merger["id"], plan["id"])["status"] == "MONITORING"


class TestCommentWindow:
    def test_merger_decide_before_comment_close_rejected(self):
        """PRD §3.6: "the logical clock must have reached `comment_close_at` —
        a decision attempted earlier is rejected with
        `ERR_COMMENT_PERIOD_OPEN` (HTTP 409), while a decision at exactly
        `comment_close_at` is permitted."

        Design: Corner/errors/merger_decide_before_comment_close_rejected
        """
        acquirer, target = register_merger_pair()
        merger = create_merger(
            acquirer["id"], target["id"],
            competition_preservation_score=40, service_reliability_score=50,
            shipper_impact_score=40)
        assert merger["comment_close_at"] == "2026-10-16T00:00:00Z"

        set_clock("2026-10-15T23:59:59Z")
        resp = api_client.decide_merger_application(
            merger["id"], decide_merger_payload("REJECTED"), BOARD)
        validate_error(resp, ApiErrorId.ERR_COMMENT_PERIOD_OPEN)
        assert get_merger_data(merger["id"])["status"] == "COMMENT_PERIOD"

        set_clock("2026-10-16T00:00:00Z")
        decided = validate_success(api_client.decide_merger_application(
            merger["id"], decide_merger_payload("REJECTED"), BOARD))
        assert decided["status"] == "REJECTED"


class TestAmendment:
    def test_amend_with_stale_version_returns_412(self):
        """PRD §2.8: "An amendment request must carry
        `expected_merger_application_version`, a non-optional input field
        holding the `version` of the merger application the client last
        observed. If that value does not match the application's current
        `version`, the amendment is rejected with `ERR_STALE_VERSION`
        (HTTP 412) and nothing is modified."

        Design: Corner/cross_cutting_layers/amend_with_stale_version_returns_412
        """
        acquirer, target = register_merger_pair()
        merger = create_merger(acquirer["id"], target["id"])
        observed_version = merger["version"]
        operator = make_carrier_operator_headers(acquirer["id"])

        amended = validate_success(api_client.amend_merger_application(
            merger["id"], amend_merger_payload(
                observed_version, shipper_impact_score=62), operator))
        assert amended["version"] == 2
        # 0.40*80 + 0.30*70 + 0.30*62 = 71.60
        assert amended["public_interest_score"] == pytest.approx(71.60)

        resp = api_client.amend_merger_application(
            merger["id"], amend_merger_payload(
                observed_version, shipper_impact_score=64), operator)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        reread = get_merger_data(merger["id"])
        assert reread["version"] == 2
        assert reread["shipper_impact_score"] == 62

    def test_amend_resets_comment_window_and_recomputes_score(self):
        """PRD §3.6: "A successful amendment supersedes the prior content: the
        application's `version` increments by 1, `comment_close_at` resets to
        the amendment time plus 45 days, and `public_interest_score` is
        recomputed from the amended showings."

        Design: Corner/cross_cutting_layers/amend_resets_comment_window_and_recomputes_score
        """
        acquirer, target = register_merger_pair()
        merger = create_merger(acquirer["id"], target["id"])
        operator = make_carrier_operator_headers(acquirer["id"])

        set_clock("2026-10-10T00:00:00Z")
        amended = validate_success(api_client.amend_merger_application(
            merger["id"], amend_merger_payload(
                merger["version"], shipper_impact_score=50), operator))
        assert amended["version"] == 2
        # 0.40*80 + 0.30*70 + 0.30*50 = 68.00
        assert amended["public_interest_score"] == pytest.approx(68.00)
        assert amended["comment_close_at"] == "2026-11-24T00:00:00Z"

        set_clock("2026-11-23T00:00:00Z")
        resp = api_client.decide_merger_application(
            merger["id"], decide_merger_payload("APPROVED"), BOARD)
        validate_error(resp, ApiErrorId.ERR_COMMENT_PERIOD_OPEN)

        set_clock("2026-11-24T00:00:00Z")
        decided = validate_success(api_client.decide_merger_application(
            merger["id"], decide_merger_payload("APPROVED"), BOARD))
        assert decided["status"] == "APPROVED"

    def test_merger_amend_not_found_returns_404(self):
        """PRD §2.6: "Ownership is evaluated only when the target resource
        exists; an unknown path identifier cannot be ownership-checked and
        falls through to the existence failure below."
        PRD §2.6: "a missing merger application
        `ERR_MERGER_APPLICATION_NOT_FOUND`" (HTTP 404).

        Design: Corner/entities/merger_amend_not_found_returns_404
        """
        acquirer, target = register_merger_pair()
        merger = create_merger(acquirer["id"], target["id"])
        resp = api_client.amend_merger_application(
            NON_EXISTENT_ID,
            amend_merger_payload(merger["version"]),
            make_carrier_operator_headers(acquirer["id"]))
        validate_error(resp, ApiErrorId.ERR_MERGER_APPLICATION_NOT_FOUND)


class TestServiceAssurancePlan:
    def test_second_service_assurance_plan_rejected(self):
        """PRD §3.6: "The applicant may also file a **service assurance plan**
        on the application — at most one plan per application, a second
        attempt being rejected with `ERR_SERVICE_ASSURANCE_PLAN_EXISTS`
        (HTTP 409) — and only while the application is in `COMMENT_PERIOD`
        (`ERR_MERGER_NOT_IN_COMMENT_PERIOD`)."

        Design: Corner/validations/second_service_assurance_plan_rejected
        """
        acquirer, target = register_merger_pair()
        merger = create_merger(acquirer["id"], target["id"])
        add_service_assurance_plan(
            merger["id"], acquirer["id"],
            plan_name="Plan A", commitments=["Crewbase stability"])
        resp = api_client.create_service_assurance_plan(
            merger["id"],
            {"plan_name": "Plan B", "commitments": ["Fuel surcharge freeze"]},
            make_carrier_operator_headers(acquirer["id"]))
        validate_error(resp, ApiErrorId.ERR_SERVICE_ASSURANCE_PLAN_EXISTS)
