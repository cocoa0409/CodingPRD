"""Member chartering and organizational assessment workflow tests."""
import pytest
from test_helpers import (
    TEST_USERS, ApiErrorId, validate_success, validate_error,
    validate_error_is_one_of, validate_paginated,
    create_member, create_member_under_assessment, create_provisional_member,
    setup_chartered_member_with_counselor,
    make_network_director_headers,
)
from test_helpers.factories import create_member_payload
from test_helpers.assertions import assert_member

DIRECTOR = TEST_USERS["network_director_headers"]
ASSESSOR = TEST_USERS["assessor_headers"]


class TestMemberCreation:
    def test_create_member_persists_fields_and_defaults(self, api):
        """PRD §3.1: "The new member begins life as an `APPLICANT`, with
        `chartered_at` null, `open_finding_count` at zero, `failed_review_flag`
        false, and `compliance_posture` derived as `CLEAR`."

        Design: Corner/entities/create_member_persists_fields_and_defaults
        """
        payload = create_member_payload(
            legal_name="Corner Housing", ein="100000001", state_code="CA",
            service_regions=["06037"])
        resp = api.create_member(payload, DIRECTOR)
        data = validate_success(resp, expected_status=201)
        assert_member(data)
        assert data["charter_status"] == "APPLICANT"
        assert data["compliance_posture"] == "CLEAR"
        assert data["version"] == 1
        assert data["open_finding_count"] == 0
        assert data["failed_review_flag"] is False
        assert data["chartered_at"] is None

        got = validate_success(api.get_member(data["id"], TEST_USERS["grant_officer_headers"]))
        assert got["legal_name"] == "Corner Housing"
        assert got["open_finding_count"] == 0

    def test_member_missing_ein_rejected(self, api):
        """PRD §3.1: "A prospective member enters the system when a
        `NetworkDirector` registers it with its `legal_name`, its nine-digit
        `ein`, the two-letter `state_code` of its principal office, and the
        list of `service_regions`" and §2.9 lists "payload shape, enum
        validity, and range checks (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/member_missing_ein_rejected
        """
        resp = api.create_member(
            {"legal_name": "No EIN Org", "state_code": "CA", "service_regions": ["06037"]},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_member_duplicate_ein_rejected(self, api):
        """PRD §3.1: "The legal name and the EIN must each be unique across all
        member organizations, and the EIN must be exactly nine digits;
        duplicates are rejected with `ERR_DUPLICATE`."

        Design: Corner/entities/member_duplicate_ein_rejected
        """
        create_member(legal_name="Dup A", ein="100000002", state_code="CA",
                      service_regions=["06037"])
        resp = api.create_member(
            create_member_payload(legal_name="Dup B", ein="100000002", state_code="NV",
                                  service_regions=["32001"]),
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_get_member_not_found(self, api):
        """PRD §2.7: "Path identifiers are validated left to right, and the
        first identifier that does not resolve yields `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_member_not_found
        """
        resp = api.get_member("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_members_pagination_envelope(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to
        10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_members_pagination_envelope
        """
        create_member(legal_name="Page One", ein="100000003", service_regions=["06037"])
        create_member(legal_name="Page Two", ein="100000004", service_regions=["06038"])
        data, meta = validate_paginated(api.list_members(DIRECTOR, params={"limit": 1, "offset": 0}))
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestAssessmentWorkflow:
    def test_assessment_composite_provisional_vs_final(self, api):
        """PRD §3.1: "the provisional `composite_score` is the weighted sum of
        the three dimensions — governance weighted at 0.40, finance at 0.35,
        and program capacity at 0.25 — rounded half up to two decimal places"
        PRD §3.1: "Adjudication recomputes the composite under the final
        variant: the same weighted base as the provisional computation, plus
        the site-visit adjustment, clamped so the result never exceeds 100,
        then rounded half up to two decimal places."
        PRD §3.1: "a `STRONG` or `ADEQUATE` final rating moves the member from
        `UNDER_ASSESSMENT` to `PROVISIONAL`"

        Design: Difficulty/dual_variant_calc/assessment_composite_provisional_vs_final
        """
        member, assessment = create_member_under_assessment(
            member_overrides={"legal_name": "Harbor Housing", "ein": "111111111",
                              "state_code": "CA", "service_regions": ["06037"]},
            governance_score=80, finance_score=90, program_capacity_score=70)
        assert assessment["composite_score"] == pytest.approx(81.00, abs=0.001)
        assert assessment["provisional_rating"] == "ADEQUATE"

        resp = api.adjudicate_assessment(
            assessment["id"], {"site_visit_adjustment": 5},
            make_network_director_headers("u-director-1"))
        final = validate_success(resp)
        assert final["composite_score"] == pytest.approx(86.00, abs=0.001)
        assert final["final_rating"] == "STRONG"
        assert final["provisional_rating"] == "ADEQUATE"

        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["charter_status"] == "PROVISIONAL"

    def test_assessment_provisional_rating_uses_bands_without_adjustment(self, api):
        """PRD §3.1: "The `final_rating` falls out of the bands: a composite of
        at least 85 is `STRONG`, at least 70 but below 85 is `ADEQUATE`, at
        least 50 but below 70 is `MARGINAL`, and below 50 is `DEFICIENT`. The
        same bands apply to the provisional rating; identical dimension scores
        yield a different composite and potentially a different rating whenever
        the adjustment is non-zero."

        Design: Difficulty/dual_variant_calc/assessment_composite_provisional_vs_final
        """
        member, assessment = create_member_under_assessment(
            member_overrides={"legal_name": "Band Org", "ein": "111111112",
                              "state_code": "CA", "service_regions": ["06038"]},
            governance_score=90, finance_score=90, program_capacity_score=90)
        assert assessment["composite_score"] == pytest.approx(90.00, abs=0.001)
        assert assessment["provisional_rating"] == "STRONG"
        assert assessment["final_rating"] is None

    def test_deficient_assessment_returns_member_to_applicant(self, api):
        """PRD §3.1: "a `DEFICIENT` rating sends the member back to `APPLICANT`
        to revise and try again; both outcomes increment the member's
        `version`."
        PRD §3.1: "`ADJUDICATED` and `WITHDRAWN` are the assessment's terminal
        states."

        Design: Corner/state_machines/deficient_assessment_returns_member_to_applicant
        """
        member, assessment = create_member_under_assessment(
            member_overrides={"legal_name": "Deficient Org", "ein": "200000003",
                              "state_code": "CA", "service_regions": ["06040"]},
            governance_score=55, finance_score=55, program_capacity_score=55)
        resp = api.adjudicate_assessment(
            assessment["id"], {"site_visit_adjustment": -10},
            make_network_director_headers("u-director-1"))
        final = validate_success(resp)
        assert final["final_rating"] == "DEFICIENT"
        assert final["composite_score"] == pytest.approx(45.00, abs=0.001)
        assert final["assessment_status"] == "ADJUDICATED"

        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["charter_status"] == "APPLICANT"

    def test_revoke_from_chartered_rejected_invalid_state(self, api):
        """PRD §3.1: "A `NetworkDirector` may revoke the charter of a
        `PROBATION` member, recording the supplied `revocation_reason`."
        PRD §2.9: "then whether the target resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/revoke_from_chartered_rejected_invalid_state
        """
        member, _counselor, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "SM Housing", "ein": "200000001",
                              "state_code": "CA", "service_regions": ["06037"]},
            course_code="HO-111")
        resp = api.revoke_member(member["id"], {"revocation_reason": "premature"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["charter_status"] == "CHARTERED"

    def test_charter_requires_certified_counselor(self, api):
        """PRD §3.1: "A `PROVISIONAL` member becomes `CHARTERED` when the
        `NetworkDirector` charters it, but only once at least one counselor of
        the member holds a certification in `CERTIFIED` status."

        Design: Difficulty/dual_variant_calc/assessment_composite_provisional_vs_final
        """
        member, _assessment = create_provisional_member(
            member_overrides={"legal_name": "No Cert Org", "ein": "200000010",
                              "state_code": "CA", "service_regions": ["06070"]})
        resp = api.charter_member(member["id"], DIRECTOR)
        # No counselor holds CERTIFIED; the transition is refused.
        validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE])

    def test_charter_stamps_chartered_at_and_succeeds_with_certified_counselor(self, api):
        """PRD §3.1: "Chartering stamps `chartered_at` with the current logical
        clock and increments the member's `version`."

        Design: Difficulty/dual_variant_calc/assessment_composite_provisional_vs_final
        """
        member, _counselor, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Charter Org", "ein": "200000011",
                              "state_code": "CA", "service_regions": ["06071"]},
            course_code="HO-114")
        assert member["charter_status"] == "CHARTERED"
        assert member["chartered_at"] is not None
