"""Rejections raised along the settlement authority ladder: hammer availability
under the consent-to-settle clause, authority grant bounds, reserve method
inputs, defence expense binding and the per-claim and aggregate limit gates.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import TEST_USERS

UW = TEST_USERS["underwriting_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
APPROVER = TEST_USERS["claims_committee_approver_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

TERM_EFFECTIVE = "2026-09-01"
TERM_EXPIRATION = "2027-09-01"


def _live_book(api, consent_to_settle_clause="NONE", **policy_overrides):
    """A rated class, a credentialed insured and one live claims-made term."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_specialty_class(api)
    insured = fixtures.build_credentialed_insured(api, specialty["id"])
    policy = fixtures.build_policy(
        api, insured["id"],
        consent_to_settle_clause=consent_to_settle_clause,
        **policy_overrides,
    )
    term = fixtures.build_in_force_term(
        api, policy["id"], TERM_EFFECTIVE, TERM_EXPIRATION
    )
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
    }


def _negotiation_count(api, claim_id):
    rows, meta = validate_paginated(
        api.list_settlement_negotiations(ADJ, {"claim_id": claim_id})
    )
    return meta["total_count"]


def _npdb_count(api, claim_id):
    rows, meta = validate_paginated(
        api.list_npdb_reports(COMPLIANCE, {"claim_id": claim_id})
    )
    return meta["total_count"]


class TestHammerAvailabilityUnderTheConsentClause:
    def test_hammer_invocation_over_an_absolute_veto_is_refused(self, api):
        """A vetoed offer written under an absolute consent clause cannot be hammered.

        PRD: "The negotiation must be in `VETOED` — a veto is the only thing a hammer overrides — and its `consent_clause_applied` must be `HAMMER`; invoking it under `ABSOLUTE`, which gives the physician an unqualified veto, or under `NONE`, where there is no veto to override, is refused with `ERR_HAMMER_NOT_AVAILABLE`."

        Design: Corner/errors/hammer_invocation_under_an_absolute_consent_clause_is_rejected
        """
        book = _live_book(api, consent_to_settle_clause="ABSOLUTE")
        insured_id = book["insured"]["id"]
        claim = fixtures.build_investigated_claim(api, insured_id)
        negotiation = fixtures.build_vetoed_negotiation(
            api, claim["id"], insured_id, 400000.00
        )
        assert negotiation["consent_clause_applied"] == "ABSOLUTE"
        assert negotiation["status"] == "VETOED"

        response = api.invoke_hammer(
            negotiation["id"],
            factories.hammer_invocation_payload("2026-12-15"),
            APPROVER,
        )
        validate_error(response, ApiErrorId.ERR_HAMMER_NOT_AVAILABLE.value, 409)

        after = validate_success(api.get_settlement_negotiation(negotiation["id"], ADJ))
        assert after["status"] == "VETOED"
        assert after["hammer_invoked"] is False
        refreshed_claim = validate_success(api.get_claim(claim["id"], ADJ))
        assertions.assert_money(
            refreshed_claim["insured_share_receivable"], 0.00,
            "insured_share_receivable",
        )


class TestAuthorityGrantBounds:
    def _requested_negotiation(self, api):
        book = _live_book(api)
        claim = fixtures.build_investigated_claim(api, book["insured"]["id"])
        negotiation = fixtures.open_negotiation(
            api, claim["id"], proposed_amount=400000.00,
            authority_requested=450000.00,
        )
        return book, claim, negotiation

    def test_grant_above_the_requested_ceiling_is_refused(self, api):
        """The committee may not authorise more than the adjuster asked for.

        PRD: "Every departure from that shape — a grant above the request, a grant of zero or a negative figure, a grant with no amount, or a denial carrying one — is refused with `ERR_AUTHORITY_GRANT_EXCEEDS_REQUEST`."

        Design: Corner/errors/authority_grants_outside_the_requested_ceiling_are_rejected_while_a_partial_grant_is_accepted
        """
        _book, _claim, negotiation = self._requested_negotiation(api)

        response = api.record_authority_decision(
            negotiation["id"],
            {
                "decision": "GRANT",
                "granted_amount": 500000.00,
                "approver_note": "above the request",
            },
            APPROVER,
        )
        validate_error(
            response, ApiErrorId.ERR_AUTHORITY_GRANT_EXCEEDS_REQUEST.value, 422
        )

        after = validate_success(api.get_settlement_negotiation(negotiation["id"], ADJ))
        assert after["status"] == "AUTHORITY_REQUESTED"
        assert after["authority_granted"] is None

    def test_denial_carrying_a_granted_amount_is_refused(self, api):
        """A denial of authority may not carry an authorised figure with it.

        PRD: "Every departure from that shape — a grant above the request, a grant of zero or a negative figure, a grant with no amount, or a denial carrying one — is refused with `ERR_AUTHORITY_GRANT_EXCEEDS_REQUEST`."

        Design: Corner/errors/authority_grants_outside_the_requested_ceiling_are_rejected_while_a_partial_grant_is_accepted
        """
        _book, _claim, negotiation = self._requested_negotiation(api)

        response = api.record_authority_decision(
            negotiation["id"],
            {
                "decision": "DENY",
                "granted_amount": 100000.00,
                "approver_note": "denial carrying an amount",
            },
            APPROVER,
        )
        validate_error(
            response, ApiErrorId.ERR_AUTHORITY_GRANT_EXCEEDS_REQUEST.value, 422
        )

        after = validate_success(api.get_settlement_negotiation(negotiation["id"], ADJ))
        assert after["status"] == "AUTHORITY_REQUESTED"
        assert after["authority_granted"] is None

    def test_partial_grant_below_the_proposal_is_accepted(self, api):
        """Authority of 300000.00 against a 400000.00 offer is a lawful partial grant.

        PRD: "Note what is deliberately *not* checked here: a grant below the `proposed_amount` is perfectly legal, because the committee is entitled to authorise less than the adjuster wants to offer."

        Design: Corner/errors/authority_grants_outside_the_requested_ceiling_are_rejected_while_a_partial_grant_is_accepted
        """
        _book, _claim, negotiation = self._requested_negotiation(api)

        granted = validate_success(api.record_authority_decision(
            negotiation["id"],
            {
                "decision": "GRANT",
                "granted_amount": 300000.00,
                "approver_note": "partial authority below the proposal",
            },
            APPROVER,
        ))
        assert granted["status"] == "AUTHORITY_GRANTED"
        assertions.assert_money(granted["authority_granted"], 300000.00,
                                "authority_granted")
        assertions.assert_money(granted["proposed_amount"], 400000.00,
                                "proposed_amount")
        assertions.assert_money(granted["authority_requested"], 450000.00,
                                "authority_requested")
        assert granted["approved_by_user_id"] == "appr-1"
        assert granted["round_index"] == 1


class TestAuthoritySufficiencyAtDisbursement:
    def test_payment_over_a_partial_authority_is_refused_before_the_limit_gates(
        self, api
    ):
        """Disbursing a 400000.00 offer on 300000.00 of authority is refused outright.

        PRD: "The `proposed_amount` must not exceed `authority_granted`, which is where a partial grant finally bites: the offer must be reduced by a revision until it fits the authority, and disbursing over it is refused with `ERR_AUTHORITY_INSUFFICIENT`."

        Design: Corner/errors/payment_above_a_partially_granted_authority_is_rejected_before_any_limit_check
        """
        book = _live_book(api)
        claim = fixtures.build_investigated_claim(api, book["insured"]["id"])
        negotiation = fixtures.build_authorised_negotiation(
            api, claim["id"], proposed_amount=400000.00,
            authority_requested=450000.00, granted_amount=300000.00,
        )
        assert negotiation["status"] == "AUTHORITY_GRANTED"

        response = api.pay_settlement(
            negotiation["id"],
            factories.settlement_payment_payload("2026-12-15"),
            ADJ,
        )
        validate_error(response, ApiErrorId.ERR_AUTHORITY_INSUFFICIENT.value, 409)

        after = validate_success(api.get_settlement_negotiation(negotiation["id"], ADJ))
        assert after["status"] == "AUTHORITY_GRANTED"
        assert after["paid_amount"] is None
        refreshed_claim = validate_success(api.get_claim(claim["id"], ADJ))
        assertions.assert_money(refreshed_claim["paid_indemnity"], 0.00,
                                "paid_indemnity")
        assert refreshed_claim["claim_status"] == "INVESTIGATION"
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assertions.assert_money(term["aggregate_limit_remaining"], 3000000.00,
                                "aggregate_limit_remaining")
        assert _npdb_count(api, claim["id"]) == 0


class TestReserveMethodInputs:
    def _intaken_claim(self, api):
        book = _live_book(api)
        claim = fixtures.build_claim(api, book["insured"]["id"])
        assert claim["claim_status"] == "INTAKE"
        return claim

    def _assert_no_reserve_landed(self, api, claim, expected_version):
        rows, meta = validate_paginated(api.list_reserve_entries(claim["id"], ADJ))
        assert meta["total_count"] == 0
        assert rows == []
        after = validate_success(api.get_claim(claim["id"], ADJ))
        assertions.assert_money(after["indemnity_reserve"], 0.00, "indemnity_reserve")
        assertions.assert_money(after["expense_reserve"], 0.00, "expense_reserve")
        assert after["reserve_method_current"] is None
        assert after["version"] == expected_version

    def test_case_basis_posting_without_its_component_amounts_is_refused(self, api):
        """A case-basis reserve that omits the adjuster's two figures is refused.

        PRD: "The two methods have mutually exclusive inputs: `CASE_BASIS` requires both amounts and `FORMULA_BASIS` requires neither, and any other combination — a case-basis posting missing one amount, or a formula-basis posting carrying either — is refused with `ERR_RESERVE_METHOD_INPUT_MISMATCH`."

        Design: Corner/errors/reserve_method_input_mismatches_are_rejected_in_both_directions
        """
        claim = self._intaken_claim(api)

        response = api.create_reserve_entry(
            claim["id"],
            factories.reserve_entry_payload(
                method="CASE_BASIS",
                effective_at="2026-11-05T00:00:00Z",
                rationale="case reserve without its components",
                expected_claim_version=claim["version"],
            ),
            ADJ,
        )
        validate_error(
            response, ApiErrorId.ERR_RESERVE_METHOD_INPUT_MISMATCH.value, 422
        )
        self._assert_no_reserve_landed(api, claim, claim["version"])

    def test_formula_basis_posting_carrying_component_amounts_is_refused(self, api):
        """A formula-basis reserve that supplies explicit figures is refused.

        PRD: "The two methods have mutually exclusive inputs: `CASE_BASIS` requires both amounts and `FORMULA_BASIS` requires neither, and any other combination — a case-basis posting missing one amount, or a formula-basis posting carrying either — is refused with `ERR_RESERVE_METHOD_INPUT_MISMATCH`."

        Design: Corner/errors/reserve_method_input_mismatches_are_rejected_in_both_directions
        """
        claim = self._intaken_claim(api)

        response = api.create_reserve_entry(
            claim["id"],
            factories.reserve_entry_payload(
                method="FORMULA_BASIS",
                effective_at="2026-11-05T00:00:00Z",
                rationale="formula reserve carrying explicit components",
                expected_claim_version=claim["version"],
                indemnity_amount=500000.00,
                expense_amount=140000.00,
            ),
            ADJ,
        )
        validate_error(
            response, ApiErrorId.ERR_RESERVE_METHOD_INPUT_MISMATCH.value, 422
        )
        self._assert_no_reserve_landed(api, claim, claim["version"])


class TestPerClaimCeilingAtFraming:
    def test_offer_above_the_per_claim_limit_is_refused_when_first_framed(self, api):
        """A 1200000.00 offer under a 1000000.00 per-claim limit never opens.

        PRD: "The amount being negotiated must not exceed the responding policy's `limit_per_claim` less the claim's `paid_indemnity`, or the request is refused with `ERR_PER_CLAIM_LIMIT_EXCEEDED`; this ceiling is tested both here, when the offer is first framed, and again when it is disbursed."

        Design: Corner/errors/negotiation_proposed_above_the_per_claim_limit_is_rejected_at_creation
        """
        book = _live_book(api)
        claim = fixtures.build_investigated_claim(
            api, book["insured"]["id"], demand_amount=1500000.00
        )

        response = api.create_settlement_negotiation(
            claim["id"],
            factories.negotiation_payload(
                proposed_amount=1200000.00,
                authority_requested=1200000.00,
                expected_claim_version=claim["version"],
            ),
            ADJ,
        )
        validate_error(response, ApiErrorId.ERR_PER_CLAIM_LIMIT_EXCEEDED.value, 422)

        assert _negotiation_count(api, claim["id"]) == 0
        after = validate_success(api.get_claim(claim["id"], ADJ))
        assert after["version"] == claim["version"]
        assertions.assert_money(after["paid_indemnity"], 0.00, "paid_indemnity")


class TestDefenceExpenseAssignmentBinding:
    def _two_defended_claims(self, api):
        """One panel firm defending two claims on the same insured."""
        book = _live_book(api)
        firm = fixtures.build_counsel_firm(
            api,
            admitted_venue_codes=["COOK_IL"],
            allegation_specialties=["OBSTETRIC_INJURY", "SURGICAL_ERROR"],
            max_concurrent_assignments=5,
        )
        claim_a = fixtures.build_litigated_claim(api, book["insured"]["id"])
        assignment_a = fixtures.assign_counsel(api, claim_a["id"])
        claim_b = fixtures.build_litigated_claim(
            api, book["insured"]["id"],
            report_date="2026-11-02",
            allegation_category="SURGICAL_ERROR",
            demand_amount=600000.00,
        )
        assignment_b = fixtures.assign_counsel(api, claim_b["id"])
        return {
            "firm": firm,
            "claim_a": claim_a, "assignment_a": assignment_a,
            "claim_b": claim_b, "assignment_b": assignment_b,
        }

    def test_expense_payment_naming_another_claims_assignment_is_refused(self, api):
        """Billing the second claim against the first claim's assignment is refused.

        PRD: "The named assignment must exist (`ERR_COUNSEL_ASSIGNMENT_NOT_FOUND`), must belong to the addressed claim rather than another one (`ERR_ASSIGNMENT_CLAIM_MISMATCH`), and must still be in `ASSIGNED` status (`ERR_ASSIGNMENT_STATE_INVALID`)."

        Design: Corner/errors/expense_payment_naming_another_claims_assignment_is_rejected
        """
        book = self._two_defended_claims(api)

        response = api.pay_expense(
            book["claim_b"]["id"],
            factories.expense_payment_payload(
                amount=9000.00,
                invoice_reference="INV-0007",
                counsel_assignment_id=book["assignment_a"]["id"],
            ),
            ADJ,
        )
        validate_error(response, ApiErrorId.ERR_ASSIGNMENT_CLAIM_MISMATCH.value, 422)

        claim_b = validate_success(api.get_claim(book["claim_b"]["id"], ADJ))
        assertions.assert_money(claim_b["paid_expense"], 0.00, "paid_expense")
        claim_a = validate_success(api.get_claim(book["claim_a"]["id"], ADJ))
        assertions.assert_money(claim_a["paid_expense"], 0.00, "paid_expense")
        assignment_a = validate_success(
            api.get_counsel_assignment(book["assignment_a"]["id"], ADJ)
        )
        assertions.assert_money(
            assignment_a["billed_expense_amount"], 0.00, "billed_expense_amount"
        )
        firm = validate_success(api.get_counsel_firm(book["firm"]["id"], APPROVER))
        assertions.assert_money(
            firm["billed_expense_total"], 0.00, "billed_expense_total"
        )

    def test_expense_payment_naming_the_claims_own_assignment_is_booked(self, api):
        """A matched 9000.00 invoice lands on the claim, the assignment and the firm.

        PRD: "The payment increases the claim's `paid_expense`, the assignment's `billed_expense_amount` and the firm's `billed_expense_total` each by the paid amount, and recomputes both incurred figures — which is the point at which `case_incurred` and `actuarial_incurred` begin to diverge, since paid expense erodes the carried expense reserve in the first figure and sits on top of it in the second."

        Design: Corner/errors/expense_payment_naming_another_claims_assignment_is_rejected
        """
        book = self._two_defended_claims(api)

        claim_b = validate_success(api.pay_expense(
            book["claim_b"]["id"],
            factories.expense_payment_payload(
                amount=9000.00,
                invoice_reference="INV-0007",
                counsel_assignment_id=book["assignment_b"]["id"],
            ),
            ADJ,
        ))
        assertions.assert_money(claim_b["paid_expense"], 9000.00, "paid_expense")

        assignment_b = validate_success(
            api.get_counsel_assignment(book["assignment_b"]["id"], ADJ)
        )
        assertions.assert_money(
            assignment_b["billed_expense_amount"], 9000.00, "billed_expense_amount"
        )
        firm = validate_success(api.get_counsel_firm(book["firm"]["id"], APPROVER))
        assertions.assert_money(
            firm["billed_expense_total"], 9000.00, "billed_expense_total"
        )
        claim_a = validate_success(api.get_claim(book["claim_a"]["id"], ADJ))
        assertions.assert_money(claim_a["paid_expense"], 0.00, "paid_expense")


class TestAggregateCeilingAtDisbursement:
    def test_payment_within_the_per_claim_limit_but_over_the_aggregate_is_refused(
        self, api
    ):
        """A 1200000.00 disbursement clears a 3000000.00 per-claim limit yet
        exhausts a 1000000.00 aggregate, so it is refused.

        PRD: "The amount being disbursed must not exceed the responding term's `aggregate_limit_remaining` (`ERR_AGGREGATE_LIMIT_EXCEEDED`) nor the policy's `limit_per_claim` less the claim's `paid_indemnity` (`ERR_PER_CLAIM_LIMIT_EXCEEDED`)."

        Design: Corner/errors/settlement_inside_the_per_claim_limit_but_over_the_aggregate_is_rejected
        """
        book = _live_book(
            api, limit_per_claim=3000000.00, limit_aggregate=1000000.00
        )
        claim = fixtures.build_investigated_claim(
            api, book["insured"]["id"], demand_amount=2500000.00
        )
        negotiation = fixtures.build_authorised_negotiation(
            api, claim["id"], proposed_amount=1200000.00,
            authority_requested=1200000.00,
        )
        assert negotiation["status"] == "AUTHORITY_GRANTED"

        response = api.pay_settlement(
            negotiation["id"],
            factories.settlement_payment_payload("2026-12-15"),
            ADJ,
        )
        validate_error(response, ApiErrorId.ERR_AGGREGATE_LIMIT_EXCEEDED.value, 409)

        after = validate_success(api.get_settlement_negotiation(negotiation["id"], ADJ))
        assert after["status"] == "AUTHORITY_GRANTED"
        assert after["paid_amount"] is None
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assertions.assert_money(term["aggregate_limit_remaining"], 1000000.00,
                                "aggregate_limit_remaining")
        refreshed_claim = validate_success(api.get_claim(claim["id"], ADJ))
        assertions.assert_money(refreshed_claim["paid_indemnity"], 0.00,
                                "paid_indemnity")
        assert refreshed_claim["claim_status"] == "INVESTIGATION"
        assert _npdb_count(api, claim["id"]) == 0
