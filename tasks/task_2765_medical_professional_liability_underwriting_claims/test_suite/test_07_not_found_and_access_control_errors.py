"""Not-found, authentication, authorisation, ownership, segregation-of-duties,
pagination and optimistic-concurrency refusals across the professional
liability book (PRD 2.1, 2.3, 2.7, 2.8 and 2.9)."""
import pytest
from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import ABSENT_UUID
from test_helpers.fixtures import (
    build_claim,
    build_credentialed_insured,
    build_in_force_term,
    build_insured,
    build_investigated_claim,
    build_policy,
    build_specialty_class,
    credential_insured,
    decide_coverage,
)
from test_helpers.test_users import make_insured_headers, make_operator_headers

# The 2026-08-01 term period the whole file books its cover under.
TERM_EFFECTIVE = "2026-08-01"
TERM_EXPIRATION = "2027-08-01"
INCIDENT_DATE = "2026-08-05"
REPORT_DATE = "2026-09-01"

FIRST_GROUP_LOOKUPS = [
    ("get_specialty_class", ApiErrorId.ERR_SPECIALTY_CLASS_NOT_FOUND),
    ("get_insured", ApiErrorId.ERR_INSURED_NOT_FOUND),
    ("get_enrollment", ApiErrorId.ERR_ENROLLMENT_NOT_FOUND),
    ("get_peer_review_case", ApiErrorId.ERR_PEER_REVIEW_CASE_NOT_FOUND),
    ("get_policy", ApiErrorId.ERR_POLICY_NOT_FOUND),
    ("get_policy_term", ApiErrorId.ERR_POLICY_TERM_NOT_FOUND),
    ("get_tail_endorsement", ApiErrorId.ERR_TAIL_ENDORSEMENT_NOT_FOUND),
    ("get_claim", ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ("get_counsel_firm", ApiErrorId.ERR_COUNSEL_FIRM_NOT_FOUND),
    ("get_counsel_assignment", ApiErrorId.ERR_COUNSEL_ASSIGNMENT_NOT_FOUND),
]

SECOND_GROUP_LOOKUPS = [
    ("get_settlement_negotiation", ApiErrorId.ERR_NEGOTIATION_NOT_FOUND),
    ("get_npdb_report", ApiErrorId.ERR_NPDB_REPORT_NOT_FOUND),
    ("get_rate_filing", ApiErrorId.ERR_RATE_FILING_NOT_FOUND),
]


def _book_with_live_term(api, **insured_overrides):
    """A rating class, a credentialed insured and one live claims-made term."""
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"], **insured_overrides)
    policy = build_policy(api, insured["id"])
    term = build_in_force_term(api, policy["id"], TERM_EFFECTIVE, TERM_EXPIRATION)
    return {"specialty_class": specialty, "insured": insured, "policy": policy,
            "term": term}


class TestAbsentIdentifierLookups:
    """Each entity answers an absent identifier with its own 404 code."""

    @pytest.mark.parametrize("reader,expected_error", FIRST_GROUP_LOOKUPS)
    def test_first_existence_group_returns_its_own_not_found_code(
        self, api, underwriting_officer_headers, reader, expected_error
    ):
        """An absent identifier on each first-group entity answers that entity's own 404.

        PRD: "**Existence, first group** — the addressed or referenced specialty class (`ERR_SPECIALTY_CLASS_NOT_FOUND`), insured (`ERR_INSURED_NOT_FOUND`), enrollment (`ERR_ENROLLMENT_NOT_FOUND`), peer review case (`ERR_PEER_REVIEW_CASE_NOT_FOUND`), policy (`ERR_POLICY_NOT_FOUND`), policy term (`ERR_POLICY_TERM_NOT_FOUND`), tail endorsement (`ERR_TAIL_ENDORSEMENT_NOT_FOUND`), claim (`ERR_CLAIM_NOT_FOUND`), defence firm (`ERR_COUNSEL_FIRM_NOT_FOUND`) and counsel assignment (`ERR_COUNSEL_ASSIGNMENT_NOT_FOUND`), resolved in that order."

        Design: Corner/errors/every_absent_uuid_lookup_returns_its_own_not_found_code
        """
        response = getattr(api, reader)(ABSENT_UUID, underwriting_officer_headers)
        body = validate_error(response, expected_error.value, 404)
        assert body.get("message"), "every error body carries a human-readable message"

    @pytest.mark.parametrize("reader,expected_error", SECOND_GROUP_LOOKUPS)
    def test_second_existence_group_returns_its_own_not_found_code(
        self, api, underwriting_officer_headers, reader, expected_error
    ):
        """The negotiation, data bank report and rate filing each answer their own 404.

        PRD: "**Existence, second group** — the addressed settlement negotiation (`ERR_NEGOTIATION_NOT_FOUND`), data bank report (`ERR_NPDB_REPORT_NOT_FOUND`) and rate filing (`ERR_RATE_FILING_NOT_FOUND`), resolved in that order."

        Design: Corner/errors/every_absent_uuid_lookup_returns_its_own_not_found_code
        """
        response = getattr(api, reader)(ABSENT_UUID, underwriting_officer_headers)
        body = validate_error(response, expected_error.value, 404)
        assert body.get("message"), "every error body carries a human-readable message"


class TestUnrecognisedRoleHeader:
    """A role string outside the eight declared roles never reaches the store."""

    def test_bogus_role_publishing_a_specialty_class_is_unauthenticated(
        self, api, actuarial_analyst_headers
    ):
        """A role header outside the eight declared roles is refused 401 and persists nothing.

        PRD: "If either header is absent, or if `X-User-Role` does not spell one of the eight declared roles exactly, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/unknown_role_header_returns_401_unauthenticated
        """
        bogus_headers = build_user_headers("bogus-1", "RiskManagerBogusRole")
        payload = factories.specialty_class_payload(
            specialty_code="NEUROSURGERY",
            base_class_code="CLASS_8",
            base_rate_per_million=60000.00,
            hazard_index=9.0,
            benchmark_severity=900000.00,
        )
        refused = api.create_specialty_class(payload, bogus_headers)
        validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        classes, meta = validate_paginated(
            api.list_specialty_classes(actuarial_analyst_headers,
                                       {"limit": 10, "offset": 0})
        )
        assert classes == [], "the refused publication left no specialty class behind"
        assert meta["total_count"] == 0


class TestRoleGateOnSettlementAuthority:
    """The committee's exclusive decision refuses an underwriter outright."""

    def test_underwriting_officer_is_refused_before_the_negotiation_is_looked_up(
        self, api, underwriting_officer_headers
    ):
        """An underwriter deciding settlement authority is refused 403 even on an absent negotiation.

        PRD: "If both headers are well formed but the named role is not authorised for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/errors/underwriting_officer_cannot_decide_settlement_authority_and_is_refused_before_existence
        """
        payload = factories.authority_decision_payload(
            "GRANT", 100000.00, "underwriter reaching into claims"
        )
        response = api.record_authority_decision(
            ABSENT_UUID, payload, underwriting_officer_headers
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


class TestInsuredOwnershipOfClaimReads:
    """The physician named on the claim reads it; a stranger physician cannot."""

    def test_other_insured_reading_the_claim_is_not_the_resource_owner(self, api):
        """A claim asserted against one physician is unreadable by a different physician.

        PRD: "An `Insured` actor may read only its own insured record, its own policies, the terms of those policies, tail endorsements on those policies, claims asserted against it and settlement negotiations on those claims; an attempt to read any record belonging to a different insured is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/errors/insured_actor_cannot_read_another_insureds_claim
        """
        book = _book_with_live_term(api)
        insured_a = book["insured"]
        insured_b = build_insured(
            api, book["specialty_class"]["id"], legal_name="Okafor OBGYN PC"
        )
        claim = build_claim(
            api, insured_a["id"],
            incident_date=INCIDENT_DATE, report_date=REPORT_DATE,
        )

        refused = api.get_claim(claim["id"], make_insured_headers(insured_b["id"]))
        validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        owned = validate_success(
            api.get_claim(claim["id"], make_insured_headers(insured_a["id"]))
        )
        assert owned["id"] == claim["id"]
        assert owned["coverage_status"] == "UNDER_REVIEW"


class TestSegregationOfDutiesOnSettlementAuthority:
    """Whoever framed the offer may not authorise it, however senior the role."""

    @staticmethod
    def _negotiation_prepared_by(api, preparer_headers):
        book = _book_with_live_term(api)
        claim = build_investigated_claim(
            api, book["insured"]["id"], "COVERED",
            incident_date=INCIDENT_DATE, report_date=REPORT_DATE,
        )
        claim_version = validate_success(
            api.get_claim(claim["id"], preparer_headers)
        )["version"]
        payload = factories.negotiation_payload(
            proposed_amount=400000.00,
            authority_requested=450000.00,
            expected_claim_version=claim_version,
        )
        return validate_success(
            api.create_settlement_negotiation(claim["id"], payload, preparer_headers),
            201,
        )

    def test_preparing_approver_cannot_grant_its_own_authority_request(
        self, api, claims_committee_approver_headers
    ):
        """The committee member who opened the negotiation is refused its own authority grant.

        PRD: "The acting `X-User-ID` must differ from the negotiation's `prepared_by_user_id`: whoever framed the offer may not authorise it, and self-approval is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/negotiation_preparer_cannot_decide_the_authority_it_requested
        """
        negotiation = self._negotiation_prepared_by(
            api, claims_committee_approver_headers
        )
        payload = factories.authority_decision_payload(
            "GRANT", 450000.00, "self-approval attempt"
        )
        refused = api.record_authority_decision(
            negotiation["id"], payload, claims_committee_approver_headers
        )
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        standing = validate_success(
            api.get_settlement_negotiation(
                negotiation["id"], claims_committee_approver_headers
            )
        )
        assert standing["prepared_by_user_id"] == "appr-1"
        assert standing["status"] == "AUTHORITY_REQUESTED"

    def test_independent_approver_grants_the_same_authority_request(
        self, api, claims_committee_approver_headers
    ):
        """A second committee member grants the identical request the preparer could not.

        PRD: "The acting `X-User-ID` must differ from the negotiation's `prepared_by_user_id`: whoever framed the offer may not authorise it, and self-approval is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/negotiation_preparer_cannot_decide_the_authority_it_requested
        """
        negotiation = self._negotiation_prepared_by(
            api, claims_committee_approver_headers
        )
        second_approver = make_operator_headers("appr-2", "ClaimsCommitteeApprover")
        payload = factories.authority_decision_payload(
            "GRANT", 450000.00, "independent committee grant"
        )
        granted = validate_success(
            api.record_authority_decision(negotiation["id"], payload, second_approver)
        )
        assert granted["status"] == "AUTHORITY_GRANTED"
        assert granted["prepared_by_user_id"] == "appr-1"
        assert granted["approved_by_user_id"] == "appr-2"
        assert float(granted["authority_granted"]) == pytest.approx(450000.00, abs=0.01)
        assert granted["round_index"] == 1


class TestPaginationWindow:
    """The page window is the inclusive one-to-one-hundred interval."""

    @pytest.mark.parametrize("params", [
        {"limit": 101, "offset": 0},
        {"limit": 10, "offset": -1},
    ])
    def test_arguments_outside_the_window_are_refused(
        self, api, underwriting_officer_headers, params
    ):
        """A limit above one hundred and a negative offset are both refused 400 on the insured list.

        PRD: "A `limit` outside the inclusive range 1 to 100, a non-integer `limit` or `offset`, or a negative `offset` is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

        Design: Corner/errors/pagination_bounds_outside_the_declared_window_return_400
        """
        response = api.list_insureds(underwriting_officer_headers, params)
        validate_error(response, ApiErrorId.ERR_PAGINATION_INVALID.value, 400)

    def test_limit_of_exactly_one_hundred_is_inside_the_window(
        self, api, underwriting_officer_headers
    ):
        """A limit of exactly one hundred sits inside the window and lists the empty book.

        PRD: "A `limit` outside the inclusive range 1 to 100, a non-integer `limit` or `offset`, or a negative `offset` is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

        Design: Corner/errors/pagination_bounds_outside_the_declared_window_return_400
        """
        insureds, meta = validate_paginated(
            api.list_insureds(underwriting_officer_headers,
                              {"limit": 100, "offset": 0})
        )
        assert insureds == []
        assert meta["limit"] == 100
        assert meta["total_count"] == 0
        assert meta["has_more"] is False


class TestStaleParentVersionGuards:
    """A child write carrying a superseded parent version is refused 412."""

    def test_reserve_entry_carrying_the_intake_claim_version_is_refused(
        self, api, claims_adjuster_headers
    ):
        """A reserve posting quoting the claim version from before the coverage decision is refused 412.

        PRD: "If it does not equal the claim's current `version`, the posting is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

        Design: Corner/errors/reserve_entry_carrying_the_pre_decision_claim_version_returns_412
        """
        book = _book_with_live_term(api)
        claim = build_claim(
            api, book["insured"]["id"],
            incident_date=INCIDENT_DATE, report_date=REPORT_DATE,
        )
        version_at_intake = claim["version"]
        decide_coverage(api, claim["id"], "COVERED")

        stale = api.create_reserve_entry(
            claim["id"],
            factories.reserve_entry_payload(
                method="FORMULA_BASIS",
                effective_at="2026-09-02T00:00:00Z",
                rationale="initial formula reserve on a stale claim version",
                expected_claim_version=version_at_intake,
            ),
            claims_adjuster_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CLAIM_VERSION.value, 412)

        current_version = validate_success(
            api.get_claim(claim["id"], claims_adjuster_headers)
        )["version"]
        validate_success(
            api.create_reserve_entry(
                claim["id"],
                factories.reserve_entry_payload(
                    method="FORMULA_BASIS",
                    effective_at="2026-09-02T00:00:00Z",
                    rationale="initial formula reserve on the current claim version",
                    expected_claim_version=current_version,
                ),
                claims_adjuster_headers,
            ),
            201,
        )

        entries, meta = validate_paginated(
            api.list_reserve_entries(claim["id"], claims_adjuster_headers)
        )
        assert meta["total_count"] == 1, "the refused posting was never written"
        assert len(entries) == 1
        reserved = validate_success(api.get_claim(claim["id"], claims_adjuster_headers))
        assert reserved["reserve_method_current"] == "FORMULA_BASIS"

    def test_enrollment_carrying_the_registration_insured_version_is_refused(
        self, api, underwriting_officer_headers
    ):
        """An enrollment quoting the insured version from before credentialing is refused 412.

        PRD: "Enrolling an insured in a risk-management program requires `expected_insured_version` matching the insured's current `version`; a mismatch is rejected with `ERR_STALE_INSURED_VERSION` (HTTP 412)."

        Design: Corner/errors/enrollment_carrying_the_pre_credentialing_insured_version_returns_412
        """
        specialty = build_specialty_class(api)
        insured = build_insured(api, specialty["id"])
        version_at_registration = insured["version"]
        credential_insured(api, insured["id"], "CREDENTIALED", "2028-01-01")

        stale = api.create_enrollment(
            insured["id"],
            factories.enrollment_payload(
                program_code="SIM_LAB",
                enrolled_on="2026-08-05",
                expected_insured_version=version_at_registration,
            ),
            underwriting_officer_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_INSURED_VERSION.value, 412)

        current_version = validate_success(
            api.get_insured(insured["id"], underwriting_officer_headers)
        )["version"]
        enrollment = validate_success(
            api.create_enrollment(
                insured["id"],
                factories.enrollment_payload(
                    program_code="SIM_LAB",
                    enrolled_on="2026-08-05",
                    expected_insured_version=current_version,
                ),
                underwriting_officer_headers,
            ),
            201,
        )
        assert enrollment["status"] == "ENROLLED"
        assert float(enrollment["credit_pct_snapshot"]) == pytest.approx(0, abs=0.00005)
