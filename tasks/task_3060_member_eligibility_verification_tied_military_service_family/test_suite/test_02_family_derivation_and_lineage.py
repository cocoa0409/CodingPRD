"""Family derivation: lineage depth boundary, sponsor activeness dependency,
and the extended lineage-verification variant for adoption/divorce cases."""
from test_helpers import ApiErrorId, fixtures, validate_error, validate_success
from test_helpers.fixtures import (
    APPLICANT,
    OFFICER_A,
    add_evidence,
    build_case,
)


def _approve_generation(api, sponsor_id, gen_name, dob):
    """Approve one CHILD derivation from sponsor_id; return new member id."""
    _, member_id = fixtures.approve_family_member(
        api, sponsor_id, "CHILD", name=gen_name, dob=dob,
        doc_type="BIRTH_CERTIFICATE",
    )
    return member_id


class TestLineageDepthBoundary:
    def _build_chain(self, api):
        """G0 direct -> G1 -> G2 -> G3, returning all member ids."""
        _, g0 = fixtures.approve_direct_member(
            api, name="Gen Zero", dob="1950-01-01",
            start="1970-01-01", end="1974-01-01",
        )
        g1 = _approve_generation(api, g0, "Gen One", "1972-01-01")
        g2 = _approve_generation(api, g1, "Gen Two", "1994-01-01")
        g3 = _approve_generation(api, g2, "Gen Three", "2016-01-01")
        return g0, g1, g2, g3

    def test_depth_three_sponsor_approval_succeeds_at_boundary(self, api):
        """PRD §3.3: "the sponsor's `lineage_depth` plus one does not exceed
        the maximum lineage depth of 3, failing with
        `ERR_LINEAGE_DEPTH_EXCEEDED` when it would."

        Design: Difficulty/boundary_precision_check/lineage_depth_boundary_at_max
        """
        _, _, g2, g3 = self._build_chain(api)
        m2 = validate_success(api.get_member(g2, OFFICER_A))
        m3 = validate_success(api.get_member(g3, OFFICER_A))
        assert m2["lineage_depth"] == 2
        assert m3["lineage_depth"] == 3
        assert m3["status"] == "ACTIVE"

    def test_fourth_generation_submit_rejected_depth_exceeded(self, api):
        """PRD §3.3: "the sponsor's `lineage_depth` plus one does not exceed
        the maximum lineage depth of 3, failing with
        `ERR_LINEAGE_DEPTH_EXCEEDED` when it would."

        Design: Difficulty/boundary_precision_check/lineage_depth_boundary_at_max
        """
        _, _, _, g3 = self._build_chain(api)
        case4 = build_case(
            api, applicant_legal_name="Gen Four", applicant_dob="2038-01-01",
            basis_type="FAMILY_DERIVATION", sponsor_member_id=g3,
            claimed_relationship="CHILD",
        )
        add_evidence(api, case4["id"], doc_type="BIRTH_CERTIFICATE")
        resp = api.submit_case(case4["id"], APPLICANT)
        validate_error(resp, ApiErrorId.ERR_LINEAGE_DEPTH_EXCEEDED)


class TestSponsorActivenessDependency:
    def _suspended_sponsor_with_child_case(self, api):
        """Sponsor suspended; child family case in INTAKE with evidence."""
        sponsor_case, sponsor_id = fixtures.approve_direct_member(
            api, name="Pat Parent", dob="1978-02-02",
        )
        child_case = build_case(
            api, applicant_legal_name="Kid Parent", applicant_dob="2008-03-03",
            basis_type="FAMILY_DERIVATION", sponsor_member_id=sponsor_id,
            claimed_relationship="CHILD",
        )
        add_evidence(api, child_case["id"], doc_type="BIRTH_CERTIFICATE")
        validate_success(api.record_eligibility_loss(
            sponsor_id, {"loss_type": "DOCUMENTATION_REVOKED"}, OFFICER_A,
        ))
        return sponsor_case, sponsor_id, child_case

    def test_submit_rejected_while_sponsor_suspended(self, api):
        """PRD §3.3: "A family-derivation submission additionally requires
        that the sponsor `Member` exists, that the sponsor's status is
        `ACTIVE` — otherwise `ERR_SPONSOR_NOT_ACTIVE`..."

        Design: Difficulty/cross_entity_state_dependency/family_case_submit_depends_on_sponsor_member_state
        """
        _, sponsor_id, child_case = self._suspended_sponsor_with_child_case(api)
        resp = api.submit_case(child_case["id"], APPLICANT)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_ACTIVE)
        current = validate_success(
            api.get_eligibility_case(child_case["id"], OFFICER_A)
        )
        assert current["status"] == "INTAKE"

    def test_submit_succeeds_after_sponsor_reinstated(self, api):
        """PRD §3.3: "A family-derivation submission additionally requires
        that the sponsor `Member` exists, that the sponsor's status is
        `ACTIVE` — otherwise `ERR_SPONSOR_NOT_ACTIVE`..." and PRD §3.8:
        "Reinstatement from `SUSPENDED` back to `ACTIVE` requires restoration
        evidence: an evidence document on the member's case uploaded after
        the loss event."

        Design: Difficulty/cross_entity_state_dependency/family_case_submit_depends_on_sponsor_member_state
        """
        sponsor_case, sponsor_id, child_case = (
            self._suspended_sponsor_with_child_case(api)
        )
        # Restoration evidence on the sponsor's (APPROVED) case.
        add_evidence(api, sponsor_case["id"], content_hash="restore-1")
        validate_success(api.reinstate_member(sponsor_id, OFFICER_A))
        submitted = validate_success(api.submit_case(child_case["id"], APPLICANT))
        assert submitted["status"] == "UNDER_REVIEW"


class TestExtendedLineageVerification:
    def _sponsor(self, api):
        _, sponsor_id = fixtures.approve_direct_member(
            api, name="Lin Larry", dob="1972-01-01",
            start="1992-01-01", end="1998-01-01",
        )
        return sponsor_id

    def test_flagged_case_with_single_self_declared_doc_type_rejected(self, api):
        """PRD §3.3: "When the case's `adoption_or_divorce_flag` is true, the
        extended lineage-verification variant adds an evidence-chain
        completeness requirement on top of the mapping: every evidence
        document on the case must carry an `authenticity_channel` of
        `ISSUER_CONFIRMED` or `ARCHIVES_CONFIRMED`, and at least two distinct
        `doc_type` values must be present across the case's documents.
        Failure is rejected with `ERR_LINEAGE_PROOF_INSUFFICIENT`."

        Design: Corner/validations/extended_lineage_proof_requires_two_doc_types
        """
        sponsor_id = self._sponsor(api)
        case = build_case(
            api, applicant_legal_name="Adopt Ann", applicant_dob="2000-01-01",
            basis_type="FAMILY_DERIVATION", sponsor_member_id=sponsor_id,
            claimed_relationship="CHILD", adoption_or_divorce_flag=True,
        )
        add_evidence(api, case["id"], doc_type="BIRTH_CERTIFICATE",
                     content_hash="adopt-1")
        fixtures.submit_case(api, case["id"])
        resp = api.decide_case(case["id"], {"decision": "APPROVE"}, OFFICER_A)
        validate_error(resp, ApiErrorId.ERR_LINEAGE_PROOF_INSUFFICIENT)

    def test_unflagged_case_with_same_evidence_approves(self, api):
        """PRD §3.3: "A `FAMILY_DERIVATION` case maps the
        `claimed_relationship` — ... `CHILD` or `STEPCHILD` to
        `FAMILY_CHILD`..." and "When the case's `adoption_or_divorce_flag` is
        true, the extended lineage-verification variant adds an
        evidence-chain completeness requirement..." (the requirement is
        conditional on the flag).

        Design: Corner/validations/extended_lineage_proof_requires_two_doc_types
        """
        sponsor_id = self._sponsor(api)
        decided, member_id = fixtures.approve_family_member(
            api, sponsor_id, "CHILD", name="Plain Pam", dob="2000-06-01",
            doc_type="BIRTH_CERTIFICATE",
        )
        assert decided["status"] == "APPROVED"
        assert member_id is not None
