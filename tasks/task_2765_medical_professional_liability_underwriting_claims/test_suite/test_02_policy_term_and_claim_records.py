"""Policy quoting, step-chain terms, claim intake and reserve postings.

Covers the record shapes of PRD 3.4 through 3.7: the quoted policy and its
defaults, the step-chain predecessor rule, the severity band computed at claim
intake, the append-only reserve posting, and the counsel assignment junction
between a claim and a panel defence firm.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import ABSENT_UUID
from test_helpers.fixtures import (
    assign_counsel,
    build_claim,
    build_counsel_firm,
    build_credentialed_insured,
    build_insured,
    build_policy,
    build_specialty_class,
    build_term,
    decide_coverage,
    issue_term,
    post_reserve,
)

TERM_EFFECTIVE = "2026-08-01"
TERM_EXPIRATION = "2027-08-01"

ORTHOPEDIC_CLASS = {
    "specialty_code": "ORTHOPEDIC_SURGERY",
    "base_class_code": "CLASS_5",
    "base_rate_per_million": 24800.00,
    "hazard_index": 6.0,
    "benchmark_severity": 480000.00,
}


def _live_obgyn_book(api):
    """An obstetrics class, a credentialed Cook County insured and one live term."""
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"])
    term = build_term(api, policy["id"], TERM_EFFECTIVE, TERM_EXPIRATION)
    term = issue_term(api, term["id"])
    return {
        "specialty_class": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
    }


def _covered_obstetric_claim(api, insured_id):
    claim = build_claim(
        api,
        insured_id,
        incident_date="2026-08-05",
        report_date="2026-09-01",
        venue_code="COOK_IL",
        allegation_category="OBSTETRIC_INJURY",
        demand_amount=800000.00,
    )
    return decide_coverage(api, claim["id"], "COVERED")


class TestPolicyRetrieval:
    """Addressing the policy collection with an identifier that resolves to nothing."""

    def test_an_unknown_policy_identifier_returns_the_policy_not_found_code(
        self, api, underwriting_officer_headers
    ):
        """A syntactically valid but absent policy id answers 404, never an empty success.

        PRD: "10. **Existence, first group** — the addressed or referenced specialty class (`ERR_SPECIALTY_CLASS_NOT_FOUND`), insured (`ERR_INSURED_NOT_FOUND`), enrollment (`ERR_ENROLLMENT_NOT_FOUND`), peer review case (`ERR_PEER_REVIEW_CASE_NOT_FOUND`), policy (`ERR_POLICY_NOT_FOUND`), policy term (`ERR_POLICY_TERM_NOT_FOUND`), tail endorsement (`ERR_TAIL_ENDORSEMENT_NOT_FOUND`), claim (`ERR_CLAIM_NOT_FOUND`), defence firm (`ERR_COUNSEL_FIRM_NOT_FOUND`) and counsel assignment (`ERR_COUNSEL_ASSIGNMENT_NOT_FOUND`), resolved in that order."

        Design: Corner/entities/policy_get_with_an_unknown_id_returns_policy_not_found
        """
        response = api.get_policy(ABSENT_UUID, underwriting_officer_headers)

        validate_error(response, ApiErrorId.ERR_POLICY_NOT_FOUND.value, 404)


class TestPolicyQuoteDefaults:
    """What a quote and its insured look like when every optional input is omitted."""

    @staticmethod
    def _ortho_insured_without_optional_inputs(api, headers,
                                               actuarial_analyst_headers):
        specialty = validate_success(
            api.create_specialty_class(
                factories.specialty_class_payload(**ORTHOPEDIC_CLASS),
                actuarial_analyst_headers,
            ),
            201,
        )
        payload = {
            "entity_type": "PHYSICIAN",
            "legal_name": "Default Ortho PLLC",
            "specialty_class_id": specialty["id"],
            "venue_code": "MARICOPA_AZ",
            "high_severity_procedure_pct": 30,
        }
        insured = validate_success(api.create_insured(payload, headers), 201)
        return specialty, insured

    def test_the_two_optional_insured_inputs_default_to_zero_years_and_uncertified(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """A registration silent on practice years and board certification stores 0 and false.

        PRD: "Two further inputs are optional: `years_in_practice`, a non-negative integer defaulting to 0 that later gates death, disability and retirement tail eligibility, and `board_certified`, a boolean defaulting to false."

        Design: Corner/entities/policy_create_applies_declared_defaults_for_omitted_optional_inputs
        """
        _specialty, insured = self._ortho_insured_without_optional_inputs(
            api, underwriting_officer_headers, actuarial_analyst_headers
        )

        fetched = validate_success(
            api.get_insured(insured["id"], underwriting_officer_headers)
        )

        assert int(fetched["years_in_practice"]) == 0
        assert fetched["board_certified"] is False
        assert fetched["status"] == "PROSPECT"
        assert fetched["credentialing_status"] == "PENDING"
        assert fetched["credentialing_expires_on"] is None
        assert int(fetched["open_claim_count"]) == 0
        assert int(fetched["closed_paid_claim_count"]) == 0

    def test_a_new_quote_opens_numbered_and_with_an_empty_premium_ledger(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """The first quote on file is MPL-000001, QUOTED, with no current term and no premium.

        PRD: "The new policy receives a `policy_number` of the form `MPL-` followed by a six-digit zero-padded creation sequence assigned in creation-timestamp ascending order beginning at `MPL-000001`, opens in `QUOTED` status with `current_term_id` null, and starts with `quoted_premium_total` and `written_premium_net_total` both at 0.00."

        Design: Corner/entities/policy_create_applies_declared_defaults_for_omitted_optional_inputs
        """
        _specialty, insured = self._ortho_insured_without_optional_inputs(
            api, underwriting_officer_headers, actuarial_analyst_headers
        )

        payload = factories.policy_payload(
            insured["id"],
            coverage_form="CLAIMS_MADE",
            retroactive_date="2026-08-01",
            consent_to_settle_clause="NONE",
        )
        payload.pop("prior_acts_step_credit")
        policy = validate_success(
            api.create_policy(payload, underwriting_officer_headers), 201
        )

        assert int(policy["prior_acts_step_credit"]) == 0
        assert policy["status"] == "QUOTED"
        assert policy["current_term_id"] is None
        assertions.assert_money(policy["quoted_premium_total"], 0.00,
                                "quoted_premium_total")
        assertions.assert_money(policy["written_premium_net_total"], 0.00,
                                "written_premium_net_total")
        assert policy["policy_number"] == "MPL-000001"
        assertions.assert_policy(policy)


class TestPolicyQuoteEnumeration:
    """The coverage form a quote may be written on."""

    def test_an_undeclared_coverage_form_is_refused_and_quotes_nothing(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """A surplus-lines coverage form is not a declared member, so no policy is quoted.

        PRD: "5. **Payload shape** — on every write endpoint: required fields present, enum values drawn from the declared members, money fields non-negative and carrying at most two decimal places, and every declared numeric range respected (`ERR_VALIDATION`, HTTP 400)."

        Design: Corner/entities/policy_create_with_an_invalid_enum_coverage_form_returns_validation_error
        """
        specialty = validate_success(
            api.create_specialty_class(
                factories.specialty_class_payload(**ORTHOPEDIC_CLASS),
                actuarial_analyst_headers,
            ),
            201,
        )
        insured = validate_success(
            api.create_insured(
                factories.insured_payload(
                    specialty["id"],
                    legal_name="Desert Orthopedics PLLC",
                    venue_code="MARICOPA_AZ",
                    high_severity_procedure_pct=30,
                ),
                underwriting_officer_headers,
            ),
            201,
        )

        payload = factories.policy_payload(
            insured["id"],
            coverage_form="SURPLUS_LINES",
            retroactive_date="2026-08-01",
            consent_to_settle_clause="NONE",
        )
        response = api.create_policy(payload, underwriting_officer_headers)

        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        _rows, meta = validate_paginated(
            api.list_policies(underwriting_officer_headers)
        )
        assert meta["total_count"] == 0


class TestClaimIntakeSeverityBand:
    """The severity band and factor the server derives from the plaintiff's demand."""

    @staticmethod
    def _uninsured_obgyn_physician(api):
        specialty = build_specialty_class(api)
        return build_insured(api, specialty["id"])

    def test_the_band_and_factor_are_computed_from_the_demand_not_from_the_payload(
        self, api, claims_adjuster_headers
    ):
        """A demand of 800000.00 lands in BAND_3 at factor 0.45 despite a smuggled BAND_1.

        PRD: "Independently of how coverage resolved, intake assigns the claim's `severity_band` from the demand."

        Design: Corner/entities/claim_severity_band_is_computed_and_a_client_supplied_band_input_ignored
        """
        insured = self._uninsured_obgyn_physician(api)

        payload = factories.claim_payload(
            insured["id"],
            incident_date="2026-08-05",
            report_date="2026-09-01",
            venue_code="COOK_IL",
            allegation_category="OBSTETRIC_INJURY",
            demand_amount=800000.00,
            severity_band="BAND_1",
            severity_band_factor=0.20,
        )
        claim = validate_success(
            api.create_claim(payload, claims_adjuster_headers), 201
        )

        assert claim["severity_band"] == "BAND_3"
        assert float(claim["severity_band_factor"]) == pytest.approx(0.45, abs=0.001)
        assertions.assert_claim(claim)

    def test_an_intake_with_no_coverage_on_file_is_denied_for_no_responding_coverage(
        self, api, claims_adjuster_headers
    ):
        """With no policy at all behind the insured, intake denies and names no responding term.

        PRD: "Where no tail responds either, `coverage_status` is `DENIED` with `denial_reason` `NO_RESPONDING_COVERAGE`."

        Design: Corner/entities/claim_severity_band_is_computed_and_a_client_supplied_band_input_ignored
        """
        insured = self._uninsured_obgyn_physician(api)

        claim = build_claim(
            api,
            insured["id"],
            incident_date="2026-08-05",
            report_date="2026-09-01",
            venue_code="COOK_IL",
            allegation_category="OBSTETRIC_INJURY",
            demand_amount=800000.00,
        )

        assert claim["coverage_status"] == "DENIED"
        assert claim["denial_reason"] == "NO_RESPONDING_COVERAGE"
        assert claim["policy_term_id"] is None
        assert claim["tail_endorsement_id"] is None


class TestReserveEntryAppendOnlyPosting:
    """A reserve posting is an accounting document, never an editable record."""

    @staticmethod
    def _claim_with_one_case_basis_posting(api):
        book = _live_obgyn_book(api)
        claim = _covered_obstetric_claim(api, book["insured"]["id"])
        posting = post_reserve(
            api,
            claim["id"],
            method="CASE_BASIS",
            effective_at="2026-09-02T00:00:00Z",
            rationale="initial case reserve",
            indemnity_amount=300000.00,
            expense_amount=84000.00,
        )
        return claim, posting

    def test_the_posting_list_exposes_neither_a_version_nor_an_updated_at(
        self, api, claims_adjuster_headers
    ):
        """The claim's case-basis posting list returns one row carrying only its identity and creation stamp.

        PRD: "Both `updated_at` and `version` are absent from a reserve entry."

        Design: Corner/entities/reserve_entry_is_append_only_and_exposes_no_version_or_updated_at
        """
        claim, posting = self._claim_with_one_case_basis_posting(api)

        rows, meta = validate_paginated(
            api.list_reserve_entries(claim["id"], claims_adjuster_headers,
                                     {"method": "CASE_BASIS"})
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == posting["id"]
        assertions.assert_reserve_entry_absent_audit_fields(rows[0])
        assertions.assert_reserve_entry_absent_audit_fields(posting)
        assertions.assert_reserve_entry(rows[0])

    def test_a_case_basis_posting_stores_the_adjusters_own_figures_and_actor(
        self, api, claims_adjuster_headers
    ):
        """A case-basis posting of 300000.00 indemnity and 84000.00 expense is stored verbatim.

        PRD: "Under `CASE_BASIS` those are simply the adjuster's `indemnity_amount` and `expense_amount`, each rounded half up to two decimal places and taken verbatim otherwise: neither the per-claim limit cap nor the expense floor is applied to an adjuster's own numbers."

        Design: Corner/entities/reserve_entry_is_append_only_and_exposes_no_version_or_updated_at
        """
        claim, posting = self._claim_with_one_case_basis_posting(api)

        assert posting["claim_id"] == claim["id"]
        assert posting["method"] == "CASE_BASIS"
        assertions.assert_money(posting["computed_indemnity_amount"], 300000.00,
                                "computed_indemnity_amount")
        assertions.assert_money(posting["computed_expense_amount"], 84000.00,
                                "computed_expense_amount")
        assert posting["set_by_user_id"] == claims_adjuster_headers["X-User-ID"]


class TestStepChainPredecessorOwnership:
    """A step chain may only be built on a predecessor of the addressed policy."""

    def test_a_predecessor_belonging_to_another_policy_is_not_found(
        self, api, underwriting_officer_headers, actuarial_analyst_headers
    ):
        """The second policy cannot step off the first policy's term.

        PRD: "Identifiers supplied inside a payload are resolved after the path has resolved completely: a `predecessor_term_id` or `triggering_term_id` that names no term, or that names a term belonging to a different policy than the one addressed, yields `ERR_POLICY_TERM_NOT_FOUND`."

        Design: Corner/entities/term_create_with_a_predecessor_from_another_policy_returns_not_found
        """
        specialty = validate_success(
            api.create_specialty_class(
                factories.specialty_class_payload(**ORTHOPEDIC_CLASS),
                actuarial_analyst_headers,
            ),
            201,
        )
        insured = build_insured(
            api, specialty["id"], legal_name="Desert Orthopedics PLLC",
            venue_code="MARICOPA_AZ", high_severity_procedure_pct=30,
        )
        first_policy = build_policy(api, insured["id"])
        first_term = build_term(api, first_policy["id"], TERM_EFFECTIVE,
                                TERM_EXPIRATION)
        second_policy = build_policy(
            api, insured["id"], limit_per_claim=2000000.00,
            limit_aggregate=6000000.00,
        )
        second_version = second_policy["version"]

        payload = factories.policy_term_payload(
            effective_date="2027-08-01",
            expiration_date="2028-08-01",
            expected_policy_version=second_version,
            predecessor_term_id=first_term["id"],
        )
        response = api.create_policy_term(
            second_policy["id"], payload, underwriting_officer_headers
        )

        validate_error(response, ApiErrorId.ERR_POLICY_TERM_NOT_FOUND.value, 404)

        reread = validate_success(
            api.get_policy(second_policy["id"], underwriting_officer_headers)
        )
        assert reread["version"] == second_version
        assertions.assert_money(reread["quoted_premium_total"], 0.00,
                                "quoted_premium_total")

        _rows, meta = validate_paginated(
            api.list_policy_terms(underwriting_officer_headers,
                                  {"policy_id": second_policy["id"]})
        )
        assert meta["total_count"] == 0


class TestCounselAssignmentJunction:
    """The assignment row that joins one claim to one panel defence firm."""

    HALLORAN = {
        "firm_name": "Halloran Defense LLP",
        "admitted_venue_codes": ["COOK_IL"],
        "allegation_specialties": ["OBSTETRIC_INJURY"],
        "blended_hourly_rate": 500.00,
        "quality_score": 95,
        "max_concurrent_assignments": 5,
        "conflict_insured_ids": [],
    }

    @classmethod
    def _defended_obstetric_claim(cls, api):
        book = _live_obgyn_book(api)
        firm = build_counsel_firm(api, **cls.HALLORAN)
        claim = _covered_obstetric_claim(api, book["insured"]["id"])
        assignment = assign_counsel(api, claim["id"])
        return firm, claim, assignment

    def test_the_one_row_is_reachable_from_the_claim_side_and_the_firm_side(
        self, api, claims_committee_approver_headers
    ):
        """Filtering by claim and filtering by firm plus status both return the same assignment.

        PRD: "Counsel assignments filter on `claim_id`, `counsel_firm_id` and `assignment_status`."

        Design: Corner/entities/counsel_assignment_junction_is_listable_from_both_the_claim_and_firm_sides
        """
        firm, claim, assignment = self._defended_obstetric_claim(api)

        by_claim, claim_meta = validate_paginated(
            api.list_counsel_assignments(claims_committee_approver_headers,
                                         {"claim_id": claim["id"]})
        )
        by_firm, firm_meta = validate_paginated(
            api.list_counsel_assignments(
                claims_committee_approver_headers,
                {"counsel_firm_id": firm["id"], "assignment_status": "ASSIGNED"},
            )
        )

        assert claim_meta["total_count"] == 1
        assert firm_meta["total_count"] == 1
        assert [row["id"] for row in by_claim] == [assignment["id"]]
        assert [row["id"] for row in by_firm] == [assignment["id"]]
        assertions.assert_counsel_assignment(by_claim[0])
        assertions.assert_counsel_assignment(by_firm[0])

    def test_the_placement_names_both_sides_and_charges_the_firms_capacity(
        self, api, claims_committee_approver_headers
    ):
        """The assignment opens ASSIGNED with no billed expense and takes one of the firm's five slots.

        PRD: "A successful assignment records `claim_id` and the selected `counsel_firm_id`, opens in `ASSIGNED` status with `assigned_at` at the current logical timestamp, `billed_expense_amount` at 0.00 and `decline_reason` and `closed_at` null, increments the firm's `open_assignment_count` by 1, and sets the claim's `counsel_reassignment_required` back to false."

        Design: Corner/entities/counsel_assignment_junction_is_listable_from_both_the_claim_and_firm_sides
        """
        firm, claim, assignment = self._defended_obstetric_claim(api)

        assert assignment["claim_id"] == claim["id"]
        assert assignment["counsel_firm_id"] == firm["id"]
        assert assignment["assignment_status"] == "ASSIGNED"
        assertions.assert_money(assignment["billed_expense_amount"], 0.00,
                                "billed_expense_amount")
        assert assignment["decline_reason"] is None
        assert assignment["closed_at"] is None

        reread_firm = validate_success(
            api.get_counsel_firm(firm["id"], claims_committee_approver_headers)
        )
        assert int(reread_firm["open_assignment_count"]) == 1

    def test_the_pool_snapshot_counts_the_single_qualified_panel_firm(
        self, api, claims_committee_approver_headers
    ):
        """Only one firm was admitted in Cook County for obstetric injury, so the pool is one.

        PRD: "`candidate_pool_size` records how many firms passed that filter."

        Design: Corner/entities/counsel_assignment_junction_is_listable_from_both_the_claim_and_firm_sides
        """
        _firm, _claim, assignment = self._defended_obstetric_claim(api)

        assert int(assignment["candidate_pool_size"]) == 1

    def test_the_selected_firm_is_recorded_as_the_first_ranked_survivor(
        self, api, claims_committee_approver_headers
    ):
        """The firm the selector chose carries rank one on the resulting assignment.

        PRD: "The survivors are ranked by `quality_score` descending, then by `blended_hourly_rate` ascending, then by creation timestamp ascending — never by identifier — and the first-ranked firm is selected, so `selection_rank_snapshot` on the resulting assignment is 1."

        Design: Corner/entities/counsel_assignment_junction_is_listable_from_both_the_claim_and_firm_sides
        """
        firm, _claim, assignment = self._defended_obstetric_claim(api)

        assert int(assignment["selection_rank_snapshot"]) == 1
        assert assignment["counsel_firm_id"] == firm["id"]
