"""Uniqueness, dating and cross-entity eligibility rules of the MPL book.

Five validation surfaces are exercised here: the one-live-row-per-programme
uniqueness unit on risk-management enrollments, the dating of an extended
reporting period against the term whose reporting obligation it extends, the
aggregate ceiling that stops a settlement disbursement, the consent
prerequisite under a policy that grants the physician no veto, and the
underwriting eligibility of an insured whose credentialing has lapsed.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories, fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.constants import OPERATOR_IDS

UW = fx.UW
ADJ = fx.ADJ
APPROVER = fx.APPROVER


# --------------------------------------------------------------------------
# State builders. The store is empty at the head of every test, so each
# recipe is rebuilt from the public endpoints.
# --------------------------------------------------------------------------
def _obgyn_insured(api):
    """The obstetrics rating class with one Cook County physician on it."""
    specialty = fx.build_specialty_class(api)
    return fx.build_insured(api, specialty["id"])


def _insured_with_a_live_cme_enrollment(api):
    """One insured already carrying an ENROLLED CME_RISK_101 row."""
    insured = _obgyn_insured(api)
    first = fx.enrol_insured(api, insured["id"], "CME_RISK_101", "2026-08-01")
    current = validate_success(api.get_insured(insured["id"], UW))
    return insured, first, current["version"]


def _enrollments_of(api, insured_id):
    rows, meta = validate_paginated(
        api.list_enrollments(UW, {"insured_id": insured_id})
    )
    return rows, meta


def _expired_claims_made_term(api):
    """A credentialed physician whose only term has run its course.

    The term binds live on its effective date and then expires when the
    logical clock is carried onto its expiration date.
    """
    specialty = fx.build_specialty_class(api)
    insured = fx.build_credentialed_insured(
        api, specialty["id"], credentialing_expires_on="2030-01-01"
    )
    policy = fx.build_policy(api, insured["id"])
    term = fx.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    fx.issue_term(api, term["id"])
    fx.advance_clock(api, "2027-08-01T00:00:00Z")
    return policy, validate_success(api.get_policy_term(term["id"], UW))


def _granted_negotiation_over_the_aggregate(api):
    """A 600000.00 authority grant behind a 500000.00 annual aggregate.

    The per-claim limit is left at 1000000.00 so the offer clears that
    ceiling both when it is framed and when it is disbursed, leaving the
    annual aggregate as the only ceiling in the way.
    """
    specialty = fx.build_specialty_class(api)
    insured = fx.build_credentialed_insured(api, specialty["id"])
    policy = fx.build_policy(
        api, insured["id"], limit_per_claim=1000000.00, limit_aggregate=500000.00
    )
    term = fx.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    fx.issue_term(api, term["id"])
    claim = fx.build_claim(
        api, insured["id"], incident_date="2026-08-05", report_date="2026-09-01"
    )
    fx.decide_coverage(api, claim["id"], "COVERED")
    negotiation = fx.open_negotiation(api, claim["id"], 600000.00, 600000.00)
    granted = fx.decide_authority(api, negotiation["id"], "GRANT", 600000.00)
    return {
        "policy": policy,
        "term": term,
        "claim": claim,
        "negotiation": granted,
    }


def _granted_negotiation_with_no_consent_clause(api):
    """A 400000.00 authority grant on a policy that grants no veto.

    The policy is written at the one-million per-claim limit against a
    three-million annual aggregate with the clause set to NONE, so neither
    fiscal ceiling nor any physician right stands in the way.
    """
    specialty = fx.build_specialty_class(api)
    insured = fx.build_credentialed_insured(api, specialty["id"])
    policy = fx.build_policy(api, insured["id"], consent_to_settle_clause="NONE")
    term = fx.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    fx.issue_term(api, term["id"])
    claim = fx.build_claim(
        api, insured["id"], incident_date="2026-08-05", report_date="2026-09-01"
    )
    fx.decide_coverage(api, claim["id"], "COVERED")
    negotiation = fx.open_negotiation(api, claim["id"], 400000.00, 400000.00)
    granted = fx.decide_authority(api, negotiation["id"], "GRANT", 400000.00)
    return {"policy": policy, "claim": claim, "negotiation": granted}


def _suspended_by_a_lapsed_verdict(api):
    """An insured carried into ACTIVE by issuance and then suspended.

    Issuing the first term takes the physician out of PROSPECT; the LAPSED
    credentialing verdict recorded afterwards is what drops the underwriting
    axis to SUSPENDED.
    """
    specialty = fx.build_specialty_class(api)
    insured = fx.build_credentialed_insured(api, specialty["id"])
    policy = fx.build_policy(api, insured["id"])
    term = fx.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    fx.issue_term(api, term["id"])
    validate_success(api.record_credentialing_decision(
        insured["id"],
        factories.credentialing_decision_payload("LAPSED", None),
        UW,
    ))
    return {
        "insured": validate_success(api.get_insured(insured["id"], UW)),
        "policy": policy,
        "term": validate_success(api.get_policy_term(term["id"], UW)),
    }


class TestOneLiveEnrollmentPerProgramme:
    """The uniqueness unit on loss-prevention enrollments is the programme."""

    def test_a_second_live_cme_enrollment_is_a_conflict(self, api):
        """A repeat enrollment in a programme already running is a conflict.

        PRD: "The insured may not already hold an enrollment in the same programme that is still `ENROLLED`; a second concurrent enrollment in the same programme is refused with `ERR_DUPLICATE_PROGRAM_ENROLLMENT`."

        Design: Corner/validations/a_second_live_enrollment_in_the_same_program_is_a_conflict
        """
        insured, _first, version = _insured_with_a_live_cme_enrollment(api)
        response = api.create_enrollment(
            insured["id"],
            factories.enrollment_payload("CME_RISK_101", "2026-08-10", version),
            UW,
        )
        validate_error(response, "ERR_DUPLICATE_PROGRAM_ENROLLMENT", 409)

    def test_the_refused_enrollment_leaves_one_live_row(self, api):
        """The conflict adds nothing: the original course enrollment stands alone.

        PRD: "The insured may not already hold an enrollment in the same programme that is still `ENROLLED`; a second concurrent enrollment in the same programme is refused with `ERR_DUPLICATE_PROGRAM_ENROLLMENT`."

        Design: Corner/validations/a_second_live_enrollment_in_the_same_program_is_a_conflict
        """
        insured, first, version = _insured_with_a_live_cme_enrollment(api)
        validate_error(
            api.create_enrollment(
                insured["id"],
                factories.enrollment_payload("CME_RISK_101", "2026-08-10", version),
                UW,
            ),
            "ERR_DUPLICATE_PROGRAM_ENROLLMENT",
            409,
        )
        rows, meta = _enrollments_of(api, insured["id"])
        assert meta["total_count"] == 1, (
            "the refused enrollment must not have been recorded"
        )
        assert [row["id"] for row in rows] == [first["id"]]
        standing = validate_success(api.get_enrollment(first["id"], UW))
        assert standing["status"] == "ENROLLED"
        assert standing["program_code"] == "CME_RISK_101"
        assert validate_success(api.get_insured(insured["id"], UW))["version"] == version


class TestUniquenessIsScopedToTheProgrammeCode:
    """A different loss-prevention programme is a different uniqueness unit."""

    def test_a_distinct_programme_enrols_alongside_the_live_course(self, api):
        """The simulation lab opens while the course enrollment is still running.

        PRD: "The insured may not already hold an enrollment in the same programme that is still `ENROLLED`; a second concurrent enrollment in the same programme is refused with `ERR_DUPLICATE_PROGRAM_ENROLLMENT`."

        Design: Corner/validations/a_distinct_program_enrollment_passes_the_same_uniqueness_check
        """
        insured, first, version = _insured_with_a_live_cme_enrollment(api)
        second = validate_success(
            api.create_enrollment(
                insured["id"],
                factories.enrollment_payload("SIM_LAB", "2026-08-10", version),
                UW,
            ),
            201,
        )
        assert second["program_code"] == "SIM_LAB"
        assert second["status"] == "ENROLLED"
        assert validate_success(api.get_enrollment(first["id"], UW))["status"] == "ENROLLED"
        _rows, meta = _enrollments_of(api, insured["id"])
        assert meta["total_count"] == 2, (
            "both programmes must be on file for the insured"
        )

    def test_the_fresh_enrollment_has_earned_nothing_yet(self, api):
        """A newly opened programme row carries no completion and no credit.

        PRD: "A fresh enrollment opens in `ENROLLED` status with `completed_on`, `attestation_reference` and `expires_on` all null and `credit_pct_snapshot` at 0, because nothing has yet been earned, and it increments the insured's `version` by 1."

        Design: Corner/validations/a_distinct_program_enrollment_passes_the_same_uniqueness_check
        """
        insured, _first, version = _insured_with_a_live_cme_enrollment(api)
        second = validate_success(
            api.create_enrollment(
                insured["id"],
                factories.enrollment_payload("SIM_LAB", "2026-08-10", version),
                UW,
            ),
            201,
        )
        assert second["status"] == "ENROLLED"
        assert second["completed_on"] is None
        assert second["attestation_reference"] is None
        assert second["expires_on"] is None
        assert float(second["credit_pct_snapshot"]) == 0
        assert validate_success(api.get_insured(insured["id"], UW))["version"] == version + 1


class TestTailDatingAgainstTheExpiringTerm:
    """An extended reporting period cannot open before the cover it extends ends."""

    def test_a_tail_effective_before_expiry_is_refused_on_dates(self, api):
        """A window opening a month before the term ends is bad dating.

        PRD: "The triggering term must be `EXPIRED` or `CANCELLED_PRO_RATA` (any other status is refused with `ERR_TERM_STATE_INVALID`) and must belong to the addressed policy, and the tail's `effective_date` must be on or after that term's `expiration_date`, or its `cancel_effective_date` where the term was cancelled pro rata; an earlier date is refused with `ERR_TAIL_EFFECTIVE_DATE_INVALID`."

        Design: Corner/validations/a_tail_effective_before_the_terms_expiry_is_rejected_on_dates
        """
        policy, term = _expired_claims_made_term(api)
        response = api.create_tail_endorsement(
            policy["id"],
            factories.tail_endorsement_payload(
                term["id"], "ERP_5YR", "RETIREMENT", "2027-07-01"
            ),
            UW,
        )
        validate_error(response, "ERR_TAIL_EFFECTIVE_DATE_INVALID", 422)

    def test_the_refused_tail_is_not_recorded_on_the_policy(self, api):
        """Bad dating on a properly expired term still leaves no endorsement.

        PRD: "The triggering term must be `EXPIRED` or `CANCELLED_PRO_RATA` (any other status is refused with `ERR_TERM_STATE_INVALID`) and must belong to the addressed policy, and the tail's `effective_date` must be on or after that term's `expiration_date`, or its `cancel_effective_date` where the term was cancelled pro rata; an earlier date is refused with `ERR_TAIL_EFFECTIVE_DATE_INVALID`."

        Design: Corner/validations/a_tail_effective_before_the_terms_expiry_is_rejected_on_dates
        """
        policy, term = _expired_claims_made_term(api)
        assert term["status"] == "EXPIRED", (
            "the triggering term must be past its expiration date"
        )
        validate_error(
            api.create_tail_endorsement(
                policy["id"],
                factories.tail_endorsement_payload(
                    term["id"], "ERP_5YR", "RETIREMENT", "2027-07-01"
                ),
                UW,
            ),
            "ERR_TAIL_EFFECTIVE_DATE_INVALID",
            422,
        )
        rows, meta = validate_paginated(
            api.list_tail_endorsements(UW, {"policy_id": policy["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestAggregateCeilingOnASettlementDisbursement:
    """The annual aggregate stops a payment the per-claim limit would allow."""

    def test_a_disbursement_over_the_aggregate_remaining_is_refused(self, api):
        """Six hundred thousand cannot be paid out of a five hundred thousand aggregate.

        PRD: "The amount being disbursed must not exceed the responding term's `aggregate_limit_remaining` (`ERR_AGGREGATE_LIMIT_EXCEEDED`) nor the policy's `limit_per_claim` less the claim's `paid_indemnity` (`ERR_PER_CLAIM_LIMIT_EXCEEDED`)."

        Design: Corner/validations/a_single_payment_above_the_aggregate_remaining_is_refused
        """
        book = _granted_negotiation_over_the_aggregate(api)
        response = api.pay_settlement(
            book["negotiation"]["id"],
            factories.settlement_payment_payload("2026-10-01"),
            ADJ,
        )
        validate_error(response, "ERR_AGGREGATE_LIMIT_EXCEEDED", 409)

    def test_the_refused_disbursement_moves_no_money(self, api):
        """The blocked payment leaves the aggregate and the claim untouched.

        PRD: "The amount being disbursed must not exceed the responding term's `aggregate_limit_remaining` (`ERR_AGGREGATE_LIMIT_EXCEEDED`) nor the policy's `limit_per_claim` less the claim's `paid_indemnity` (`ERR_PER_CLAIM_LIMIT_EXCEEDED`)."

        Design: Corner/validations/a_single_payment_above_the_aggregate_remaining_is_refused
        """
        book = _granted_negotiation_over_the_aggregate(api)
        validate_error(
            api.pay_settlement(
                book["negotiation"]["id"],
                factories.settlement_payment_payload("2026-10-01"),
                ADJ,
            ),
            "ERR_AGGREGATE_LIMIT_EXCEEDED",
            409,
        )
        negotiation = validate_success(
            api.get_settlement_negotiation(book["negotiation"]["id"], ADJ)
        )
        assert negotiation["status"] == "AUTHORITY_GRANTED"
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert_money(term["aggregate_limit_remaining"], 500000.00,
                     "aggregate_limit_remaining")
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert_money(claim["paid_indemnity"], 0.00, "paid_indemnity")


class TestConsentUnderAPolicyWithNoVeto:
    """With no consent-to-settle provision there is no physician veto to solicit."""

    def test_tendering_consent_under_a_none_clause_is_refused(self, api):
        """Nothing can be tendered to a physician who holds no veto right.

        PRD: "Tendering consent on a negotiation whose clause is `NONE` is refused with `ERR_CONSENT_REQUIRED`, since there is no consent-to-settle provision to exercise."

        Design: Corner/validations/consent_cannot_be_requested_when_the_policy_has_no_consent_clause
        """
        book = _granted_negotiation_with_no_consent_clause(api)
        response = api.request_consent(book["negotiation"]["id"], ADJ)
        validate_error(response, "ERR_CONSENT_REQUIRED", 409)
        standing = validate_success(
            api.get_settlement_negotiation(book["negotiation"]["id"], ADJ)
        )
        assert standing["status"] == "AUTHORITY_GRANTED", (
            "the refused tender must not advance the consent loop"
        )
        assert standing["consent_requested_at"] is None

    def test_the_negotiation_carries_its_own_copy_of_the_clause(self, api):
        """The clause under which the offer will be settled is frozen on the negotiation.

        PRD: "Crucially, `consent_clause_applied` is frozen at creation from the responding policy's `consent_to_settle_clause`, so the negotiation carries its own copy of the physician's consent right for its whole life and is unaffected by anything later done to the policy record."

        Design: Corner/validations/consent_cannot_be_requested_when_the_policy_has_no_consent_clause
        """
        book = _granted_negotiation_with_no_consent_clause(api)
        assert book["policy"]["consent_to_settle_clause"] == "NONE"
        assert book["negotiation"]["consent_clause_applied"] == "NONE"

    def test_the_grant_records_the_authority_and_its_approver(self, api):
        """The committee's grant is stamped with the amount and the approving user.

        PRD: "`AUTHORITY_REQUESTED` → `AUTHORITY_GRANTED` records `authority_granted` and `approved_by_user_id`; `AUTHORITY_REQUESTED` → `AUTHORITY_DENIED` records `approved_by_user_id` and leaves `authority_granted` null."

        Design: Corner/validations/consent_cannot_be_requested_when_the_policy_has_no_consent_clause
        """
        book = _granted_negotiation_with_no_consent_clause(api)
        assert book["negotiation"]["status"] == "AUTHORITY_GRANTED"
        assert_money(book["negotiation"]["authority_granted"], 400000.00,
                     "authority_granted")
        assert book["negotiation"]["approved_by_user_id"] == (
            OPERATOR_IDS["ClaimsCommitteeApprover"]
        )


class TestUnderwritingASuspendedInsured:
    """Eligibility to be written turns on the insured's own underwriting state."""

    def test_a_new_policy_for_a_suspended_insured_is_refused(self, api):
        """No fresh cover may be quoted for a physician under suspension.

        PRD: "A suspended insured may not have a new policy quoted for it; that attempt is refused with `ERR_INSURED_STATE_INVALID`."

        Design: Corner/validations/a_policy_cannot_be_written_for_a_suspended_insured
        """
        book = _suspended_by_a_lapsed_verdict(api)
        response = api.create_policy(
            factories.policy_payload(book["insured"]["id"]), UW
        )
        validate_error(response, "ERR_INSURED_STATE_INVALID", 409)
        rows, meta = validate_paginated(
            api.list_policies(UW, {"insured_id": book["insured"]["id"]})
        )
        assert meta["total_count"] == 1, (
            "only the policy written before the suspension may exist"
        )
        assert [row["id"] for row in rows] == [book["policy"]["id"]]

    def test_a_lapsed_verdict_suspends_the_active_insured(self, api):
        """Letting credentials lapse on a written physician suspends the account.

        PRD: "Recording `LAPSED` or `DENIED` on an insured whose underwriting status is `ACTIVE` drives that status to `SUSPENDED`."

        Design: Corner/validations/a_policy_cannot_be_written_for_a_suspended_insured
        """
        book = _suspended_by_a_lapsed_verdict(api)
        assert book["insured"]["credentialing_status"] == "LAPSED"
        assert book["insured"]["status"] == "SUSPENDED"
