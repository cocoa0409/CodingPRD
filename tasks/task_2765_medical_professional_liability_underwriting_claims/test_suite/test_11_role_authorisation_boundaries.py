"""Role-based access control across the underwriting, claims, peer review, data
bank and actuarial write surfaces, together with the ownership boundary that
separates one insured from another (PRD 2.1, 2.8).
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import ABSENT_UUID, CLOCK_EPOCH, OPERATOR_IDS
from test_helpers.fixtures import (
    advance_clock,
    build_claim,
    build_credentialed_insured,
    build_insured,
    build_policy,
    build_specialty_class,
    build_term,
    decide_coverage,
    issue_term,
)
from test_helpers.test_users import (
    CARRIER_ROLE_NAMES,
    TEST_USERS,
    make_insured_headers,
    make_operator_headers,
)

UW = TEST_USERS["underwriting_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
APPROVER = TEST_USERS["claims_committee_approver_headers"]
CHAIR = TEST_USERS["peer_review_chair_headers"]
ANALYST = TEST_USERS["actuarial_analyst_headers"]
CHIEF = TEST_USERS["chief_actuary_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

SECOND_APPROVER = make_operator_headers("appr-2", "ClaimsCommitteeApprover")

TERM_EFFECTIVE = "2026-08-01"
TERM_EXPIRATION = "2027-08-01"


def _live_claims_made_book(api):
    """A rated class, a credentialed insured and one live claims-made term."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"])
    term = build_term(
        api, policy["id"],
        effective_date=TERM_EFFECTIVE, expiration_date=TERM_EXPIRATION,
    )
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": issue_term(api, term["id"]),
    }


def _covered_claim(api, insured_id, **overrides):
    """An intaken claim carried to a COVERED position in INVESTIGATION."""
    claim = build_claim(api, insured_id, **overrides)
    return decide_coverage(api, claim["id"], "COVERED")


class TestUnderwritingWriteSurface:
    def test_claims_actuarial_and_compliance_roles_are_refused_underwriting_writes(
        self, api
    ):
        """Registration, term creation and issuance are refused to the adjuster, the analyst and the compliance officer but succeed for the underwriting officer.

        PRD: "If both headers are well formed but the named role is not authorised for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/underwriting_writes_cannot_be_performed_by_claims_actuarial_or_compliance_roles
        """
        advance_clock(api, CLOCK_EPOCH)
        specialty = build_specialty_class(api)
        insured = build_credentialed_insured(api, specialty["id"])
        policy = build_policy(api, insured["id"])
        version_before = policy["version"]

        # Registering an insured belongs to the underwriting officer alone.
        validate_error(
            api.create_insured(
                factories.insured_payload(
                    specialty["id"],
                    legal_name="Adjuster Own Insured",
                    high_severity_procedure_pct=10,
                ),
                ADJ,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        term_payload = factories.policy_term_payload(
            effective_date=TERM_EFFECTIVE,
            expiration_date=TERM_EXPIRATION,
            expected_policy_version=version_before,
        )
        validate_error(
            api.create_policy_term(policy["id"], term_payload, ANALYST),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        term = validate_success(
            api.create_policy_term(policy["id"], term_payload, UW), 201
        )

        after_term = validate_success(api.get_policy(policy["id"], UW))
        assert after_term["version"] == version_before + 1, (
            "only the accepted term creation may bump the policy version"
        )

        validate_error(
            api.issue_policy_term(term["id"], COMPLIANCE),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        issued = validate_success(api.issue_policy_term(term["id"], UW))
        assert issued["status"] == "IN_FORCE"

        insureds, insured_meta = validate_paginated(api.list_insureds(UW))
        assert insured_meta["total_count"] == 1, (
            "the refused registration must leave no insured behind"
        )
        terms, term_meta = validate_paginated(
            api.list_policy_terms(UW, {"policy_id": policy["id"]})
        )
        assert term_meta["total_count"] == 1
        assert terms[0]["id"] == term["id"]


class TestClaimHandlingAxisIsTheAdjustersAlone:
    def test_committee_and_chair_are_refused_intake_coverage_and_disposition(
        self, api
    ):
        """Claim intake, the coverage position and the disposition are refused to the committee approver, the peer review chair and the compliance officer.

        PRD: "If both headers are well formed but the named role is not authorised for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/claim_handling_writes_cannot_be_performed_by_the_committee_or_the_chair
        """
        book = _live_claims_made_book(api)
        insured_id = book["insured"]["id"]

        claim_payload = factories.claim_payload(
            insured_id,
            incident_date="2026-08-05",
            report_date="2026-09-01",
            demand_amount=800000.00,
        )
        validate_error(
            api.create_claim(claim_payload, APPROVER),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        claim = validate_success(api.create_claim(claim_payload, ADJ), 201)

        coverage_payload = factories.coverage_decision_payload("COVERED")
        validate_error(
            api.record_coverage_decision(claim["id"], coverage_payload, CHAIR),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        decided = validate_success(
            api.record_coverage_decision(claim["id"], coverage_payload, ADJ)
        )
        assert decided["coverage_status"] == "COVERED"
        assert decided["claim_status"] == "INVESTIGATION"

        validate_error(
            api.record_disposition(
                claim["id"],
                factories.disposition_payload("DISMISSED", "2026-10-01"),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        _claims, meta = validate_paginated(
            api.list_claims(ADJ, {"insured_id": insured_id})
        )
        assert meta["total_count"] == 1, (
            "the refused intake must leave no claim behind"
        )
        final = validate_success(api.get_claim(claim["id"], ADJ))
        assert final["disposition"] is None
        assert final["claim_status"] == "INVESTIGATION"


class TestSettlementAuthorityIsSplitFromOfferPreparation:
    def test_negotiation_creation_is_shared_by_the_adjuster_and_the_committee(
        self, api
    ):
        """Both the adjuster and a committee approver may open a settlement negotiation, and each is recorded as the preparer of its own offer.

        PRD: "A **settlement negotiation** is opened on a claim by either a `ClaimsAdjuster` or a `ClaimsCommitteeApprover`, who supplies the `proposed_amount` to be offered to the plaintiff, the `authority_requested` from the claims committee, and the `expected_claim_version` required by §2.9."

        Design: Corner/rbac/negotiation_creation_is_shared_but_the_authority_decision_cannot_be_taken_by_the_adjuster
        """
        book = _live_claims_made_book(api)
        insured_id = book["insured"]["id"]

        claim_a = _covered_claim(
            api, insured_id,
            incident_date="2026-08-05", report_date="2026-09-01",
            demand_amount=800000.00,
        )
        claim_b = _covered_claim(
            api, insured_id,
            incident_date="2026-08-06", report_date="2026-09-02",
            allegation_category="SURGICAL_ERROR", demand_amount=500000.00,
        )

        negotiation_a = validate_success(
            api.create_settlement_negotiation(
                claim_a["id"],
                factories.negotiation_payload(
                    300000.00, 300000.00,
                    validate_success(api.get_claim(claim_a["id"], ADJ))["version"],
                ),
                ADJ,
            ),
            201,
        )
        negotiation_b = validate_success(
            api.create_settlement_negotiation(
                claim_b["id"],
                factories.negotiation_payload(
                    200000.00, 200000.00,
                    validate_success(
                        api.get_claim(claim_b["id"], SECOND_APPROVER)
                    )["version"],
                ),
                SECOND_APPROVER,
            ),
            201,
        )

        assert negotiation_a["prepared_by_user_id"] == OPERATOR_IDS["ClaimsAdjuster"]
        assert negotiation_b["prepared_by_user_id"] == "appr-2"
        assert negotiation_a["status"] == "AUTHORITY_REQUESTED"
        assert negotiation_b["status"] == "AUTHORITY_REQUESTED"

    def test_the_authority_decision_cannot_be_taken_by_the_adjuster(self, api):
        """The adjuster is refused the committee's authority decision on an offer the committee itself prepared, which a second approver then grants.

        PRD: "If both headers are well formed but the named role is not authorised for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/negotiation_creation_is_shared_but_the_authority_decision_cannot_be_taken_by_the_adjuster
        """
        book = _live_claims_made_book(api)
        claim = _covered_claim(
            api, book["insured"]["id"],
            incident_date="2026-08-06", report_date="2026-09-02",
            allegation_category="SURGICAL_ERROR", demand_amount=500000.00,
        )
        negotiation = validate_success(
            api.create_settlement_negotiation(
                claim["id"],
                factories.negotiation_payload(
                    200000.00, 200000.00,
                    validate_success(
                        api.get_claim(claim["id"], SECOND_APPROVER)
                    )["version"],
                ),
                SECOND_APPROVER,
            ),
            201,
        )

        grant = factories.authority_decision_payload(
            "GRANT", 200000.00,
            approver_note="adjuster attempting the committee decision",
        )
        validate_error(
            api.record_authority_decision(negotiation["id"], grant, ADJ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        granted = validate_success(
            api.record_authority_decision(negotiation["id"], grant, APPROVER)
        )
        assert granted["status"] == "AUTHORITY_GRANTED"
        assert granted["approved_by_user_id"] == OPERATOR_IDS[
            "ClaimsCommitteeApprover"
        ]
        assert granted["prepared_by_user_id"] == "appr-2"


def _filing_submitted_by_the_chief_actuary(api):
    """A filing whose preparer and submitter are both the chief actuary."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    filing = validate_success(
        api.create_rate_filing(
            factories.rate_filing_payload(
                specialty["id"],
                proposed_rate_change_pct=4.00,
                experience_period_start="2025-08-01",
                experience_period_end="2026-08-01",
                effective_date="2026-09-01",
            ),
            CHIEF,
        ),
        201,
    )
    submitted = validate_success(api.submit_rate_filing(filing["id"], CHIEF))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["prepared_by_user_id"] == OPERATOR_IDS["ChiefActuary"]
    return {"specialty": specialty, "filing": submitted}


class TestRateFilingDecisionAuthority:
    def test_the_analyst_is_refused_the_chief_actuarys_filing_decision(self, api):
        """The actuarial analyst that may draft and submit a filing is still refused the decision reserved to the chief actuary.

        PRD: "If both headers are well formed but the named role is not authorised for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/filing_preparer_cannot_approve_or_reject_its_own_filing_but_may_withdraw_it
        """
        bundle = _filing_submitted_by_the_chief_actuary(api)
        validate_error(
            api.decide_rate_filing(
                bundle["filing"]["id"],
                factories.filing_decision_payload(
                    "APPROVE", "analyst attempting the chief actuary decision"
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        untouched = validate_success(
            api.get_rate_filing(bundle["filing"]["id"], CHIEF)
        )
        assert untouched["status"] == "SUBMITTED"
        assert untouched["approved_rate_change_pct"] is None

    def test_the_preparing_chief_actuary_may_not_approve_or_reject_its_own_filing(
        self, api
    ):
        """The chief actuary that prepared the filing is refused both approval and rejection of it on segregation-of-duties grounds.

        PRD: "A `ClaimsCommitteeApprover` may not decide settlement authority on a negotiation whose `prepared_by_user_id` equals its own `X-User-ID`, and a `ChiefActuary` may not approve or reject a rate filing whose `prepared_by_user_id` equals its own `X-User-ID`."

        Design: Corner/rbac/filing_preparer_cannot_approve_or_reject_its_own_filing_but_may_withdraw_it
        """
        bundle = _filing_submitted_by_the_chief_actuary(api)
        filing_id = bundle["filing"]["id"]
        assert bundle["filing"]["adequacy_flag"] == "NOT_EVALUABLE", (
            "with no claims in scope no reserve deficiency can mask the duties check"
        )

        validate_error(
            api.decide_rate_filing(
                filing_id,
                factories.filing_decision_payload(
                    "APPROVE", "preparer approving its own filing"
                ),
                CHIEF,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        validate_error(
            api.decide_rate_filing(
                filing_id,
                factories.filing_decision_payload(
                    "REJECT", "preparer rejecting its own filing"
                ),
                CHIEF,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        still_open = validate_success(api.get_rate_filing(filing_id, CHIEF))
        assert still_open["status"] == "SUBMITTED"
        assert still_open["approved_rate_change_pct"] is None
        specialty = validate_success(
            api.get_specialty_class(bundle["specialty"]["id"], CHIEF)
        )
        assert float(specialty["base_rate_per_million"]) == pytest.approx(
            38000.00, abs=0.01
        )
        assert specialty["rate_revision_index"] == 0

    def test_the_preparing_chief_actuary_may_still_withdraw_its_own_filing(self, api):
        """Withdrawal of a filing by its own preparer is exempt from the duties separation and lands the filing in WITHDRAWN.

        PRD: "Withdrawing a rate filing is deliberately exempt from that rule: an actuary is expected to be able to withdraw work it prepared itself."

        Design: Corner/rbac/filing_preparer_cannot_approve_or_reject_its_own_filing_but_may_withdraw_it
        """
        bundle = _filing_submitted_by_the_chief_actuary(api)
        withdrawn = validate_success(
            api.decide_rate_filing(
                bundle["filing"]["id"],
                factories.filing_decision_payload(
                    "WITHDRAW", "preparer withdrawing its own filing"
                ),
                CHIEF,
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["prepared_by_user_id"] == OPERATOR_IDS["ChiefActuary"]
        assert withdrawn["approved_rate_change_pct"] is None

        specialty = validate_success(
            api.get_specialty_class(bundle["specialty"]["id"], CHIEF)
        )
        assert float(specialty["base_rate_per_million"]) == pytest.approx(
            38000.00, abs=0.01
        )
        assert specialty["rate_revision_index"] == 0


class TestInsuredOwnershipBoundary:
    def test_an_insured_reads_its_own_record_but_not_a_siblings(self, api):
        """An insured actor reads its own registration and is refused the record of another insured on ownership grounds.

        PRD: "An `Insured` actor may read only its own insured record, its own policies, the terms of those policies, tail endorsements on those policies, claims asserted against it and settlement negotiations on those claims; an attempt to read any record belonging to a different insured is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/insured_cannot_read_other_insureds_or_reach_the_carrier_write_surface
        """
        advance_clock(api, CLOCK_EPOCH)
        specialty = build_specialty_class(api)
        insured_a = build_insured(api, specialty["id"])
        insured_b = build_insured(
            api, specialty["id"],
            legal_name="Okafor OBGYN PC", high_severity_procedure_pct=30,
            years_in_practice=9,
        )
        acting_as_a = make_insured_headers(insured_a["id"])

        own = validate_success(api.get_insured(insured_a["id"], acting_as_a))
        assert own["id"] == insured_a["id"]

        validate_error(
            api.get_insured(insured_b["id"], acting_as_a),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )

    def test_an_insured_cannot_reach_the_carrier_list_or_write_surface(self, api):
        """The insured roster and claim intake sit outside the insured's surface altogether, so both are refused as unauthorised rather than as unowned.

        PRD: "If both headers are well formed but the named role is not authorised for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/insured_cannot_read_other_insureds_or_reach_the_carrier_write_surface
        """
        advance_clock(api, CLOCK_EPOCH)
        specialty = build_specialty_class(api)
        insured_a = build_insured(api, specialty["id"])
        insured_b = build_insured(
            api, specialty["id"],
            legal_name="Okafor OBGYN PC", high_severity_procedure_pct=30,
            years_in_practice=9,
        )
        acting_as_a = make_insured_headers(insured_a["id"])

        validate_error(
            api.list_insureds(acting_as_a, {"limit": 10, "offset": 0}),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_claim(
                factories.claim_payload(
                    insured_a["id"],
                    incident_date="2026-08-05", report_date="2026-09-01",
                    demand_amount=800000.00,
                ),
                acting_as_a,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        _claims, meta = validate_paginated(api.list_claims(ADJ))
        assert meta["total_count"] == 0, (
            "the refused intake must leave no claim behind"
        )
        assert validate_success(
            api.get_insured(insured_b["id"], UW)
        )["open_claim_count"] == 0


class TestPeerReviewAndDataBankExclusives:
    def test_referral_is_shared_but_the_review_tracks_are_the_chairs_alone(self, api):
        """Both the chair and the adjuster may refer an insured to peer review, yet recording a review track is refused to the adjuster.

        PRD: "A `PeerReviewChair` or a `ClaimsAdjuster` refers an insured to **peer review** by supplying `insured_id`, a `trigger_source` of `CLAIM_INTAKE`, `CREDENTIALING_REVIEW`, `SENTINEL_EVENT` or `COMPLAINT`, and a free-text `referral_note`."

        Design: Corner/rbac/peer_review_and_data_bank_exclusives_cannot_be_crossed
        """
        advance_clock(api, CLOCK_EPOCH)
        specialty = build_specialty_class(api)
        insured = build_insured(api, specialty["id"])

        by_adjuster = validate_success(
            api.create_peer_review_case(
                factories.peer_review_case_payload(
                    insured["id"], trigger_source="CLAIM_INTAKE",
                    referral_note="referred by the adjuster",
                ),
                ADJ,
            ),
            201,
        )
        by_chair = validate_success(
            api.create_peer_review_case(
                factories.peer_review_case_payload(
                    insured["id"], trigger_source="SENTINEL_EVENT",
                    referral_note="referred by the chair",
                ),
                CHAIR,
            ),
            201,
        )
        assert by_chair["trigger_source"] == "SENTINEL_EVENT"

        validate_error(
            api.record_review_track(
                by_adjuster["id"],
                factories.review_track_payload("CHART", "NO_CONCERN"),
                ADJ,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        untouched = validate_success(
            api.get_peer_review_case(by_adjuster["id"], CHAIR)
        )
        assert untouched["status"] == "REFERRED"
        assert untouched["chart_review_outcome"] is None
        _cases, meta = validate_paginated(
            api.list_peer_review_cases(CHAIR, {"insured_id": insured["id"]})
        )
        assert meta["total_count"] == 2

    def test_the_role_check_outranks_the_absent_data_bank_report(self, api):
        """The chair reaching for a data bank transmission is refused as unauthorised before the report's non-existence is considered, which the compliance officer then sees.

        PRD: "When several checks could reject the same request, they are evaluated in a fixed order, and the response carries the error of the first check that fails."

        Design: Corner/rbac/peer_review_and_data_bank_exclusives_cannot_be_crossed
        """
        advance_clock(api, CLOCK_EPOCH)
        submission = factories.npdb_submission_payload(
            "2026-09-01", "reaching into compliance territory"
        )
        validate_error(
            api.submit_npdb_report(ABSENT_UUID, submission, CHAIR),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.submit_npdb_report(ABSENT_UUID, submission, COMPLIANCE),
            ApiErrorId.ERR_NPDB_REPORT_NOT_FOUND.value,
            404,
        )


class TestSharedCarrierReadAndClockSurface:
    @pytest.mark.parametrize("role_name", CARRIER_ROLE_NAMES)
    def test_the_rate_manual_listing_is_open_to_every_carrier_role(self, api, role_name):
        """Each of the seven carrier-side roles reads the published rating classes on equal footing.

        PRD: "If both headers are well formed but the named role is not authorised for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/every_carrier_role_shares_the_read_and_clock_surface_while_the_insured_cannot_use_it
        """
        advance_clock(api, CLOCK_EPOCH)
        specialty = build_specialty_class(api)

        headers = make_operator_headers(OPERATOR_IDS[role_name], role_name)
        classes, meta = validate_paginated(
            api.list_specialty_classes(headers, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert [row["id"] for row in classes] == [specialty["id"]]
        assert classes[0]["specialty_code"] == "OBSTETRICS_GYNECOLOGY"

    def test_the_insured_is_refused_the_carrier_rate_manual_listing(self, api):
        """The entity-backed insured has no place on the shared carrier read surface at all.

        PRD: "If both headers are well formed but the named role is not authorised for the addressed operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/every_carrier_role_shares_the_read_and_clock_surface_while_the_insured_cannot_use_it
        """
        advance_clock(api, CLOCK_EPOCH)
        specialty = build_specialty_class(api)
        insured = build_insured(api, specialty["id"])

        validate_error(
            api.list_specialty_classes(
                make_insured_headers(insured["id"]), {"limit": 10, "offset": 0}
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

    def test_the_logical_clock_moves_for_a_carrier_role_but_not_for_the_insured(self, api):
        """The compliance officer advances the shared logical clock, while the insured's attempt to move it is refused.

        PRD: "An operator in any of the seven carrier-side roles may advance it by supplying a `to_iso8601` instant; the response reports the resulting `current_utc` together with the identifier lists `promoted_term_ids`, `expired_term_ids`, `expired_enrollment_ids`, `lapsed_insured_ids` and `closed_claim_ids`, each naming the records the checkpoint sweep touched."

        Design: Corner/rbac/every_carrier_role_shares_the_read_and_clock_surface_while_the_insured_cannot_use_it
        """
        advance_clock(api, CLOCK_EPOCH)
        specialty = build_specialty_class(api)
        insured = build_insured(api, specialty["id"])

        swept = validate_success(api.set_clock("2026-08-02T00:00:00Z", COMPLIANCE))
        assertions.assert_same_instant(
            swept["current_utc"], "2026-08-02T00:00:00Z", "current_utc"
        )
        for sweep_list in (
            "promoted_term_ids", "expired_term_ids", "expired_enrollment_ids",
            "lapsed_insured_ids", "closed_claim_ids",
        ):
            assert swept[sweep_list] == []

        validate_error(
            api.set_clock("2026-08-03T00:00:00Z", make_insured_headers(insured["id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
