"""Panel firm round trips, the severity trend read and the defence expense ledger.

Exercises the public surface of the defence-panel and analytics areas of the
PRD: admitting a firm and finding it again through the venue and specialty
filters, the two populations behind the severity trend figures, and the way a
single expense payment lands in three ledgers at once.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    assign_counsel,
    build_claim,
    build_counsel_firm,
    build_credentialed_insured,
    build_policy,
    build_specialty_class,
    build_term,
    decide_coverage,
    dispose_claim,
    issue_term,
)

TERM_EFFECTIVE = "2026-08-01"
TERM_EXPIRATION = "2027-08-01"

HALLORAN_TWO_VENUES = {
    "firm_name": "Halloran Defense LLP",
    "admitted_venue_codes": ["COOK_IL", "TRAVIS_TX"],
    "allegation_specialties": ["OBSTETRIC_INJURY", "SURGICAL_ERROR"],
    "blended_hourly_rate": 500.00,
    "quality_score": 95,
}

HALLORAN_COOK_ONLY = {
    "firm_name": "Halloran Defense LLP",
    "admitted_venue_codes": ["COOK_IL"],
    "allegation_specialties": ["OBSTETRIC_INJURY"],
    "blended_hourly_rate": 500.00,
    "quality_score": 95,
    "max_concurrent_assignments": 5,
    "conflict_insured_ids": [],
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


class TestPanelFirmAdmissionRoundTrip:
    """Admitting a defence firm, reading it back and finding it by filter."""

    @staticmethod
    def _admit_halloran(api, headers):
        payload = factories.counsel_firm_payload(**HALLORAN_TWO_VENUES)
        return validate_success(api.create_counsel_firm(payload, headers), 201)

    def test_a_newly_admitted_firm_reads_back_active_with_an_empty_work_ledger(
        self, api, claims_committee_approver_headers, claims_adjuster_headers
    ):
        """The firm just admitted to the panel carries no work and no standing note.

        PRD: "A new firm opens with `panel_status` `ACTIVE`, `open_assignment_count` 0, `billed_expense_total` 0.00 and `panel_status_reason` null."

        Design: Corner/endpoints/counsel_firm_create_read_and_filtered_list_round_trip
        """
        firm = self._admit_halloran(api, claims_committee_approver_headers)

        fetched = validate_success(
            api.get_counsel_firm(firm["id"], claims_adjuster_headers)
        )

        assert fetched["id"] == firm["id"]
        assert fetched["panel_status"] == "ACTIVE"
        assert int(fetched["open_assignment_count"]) == 0
        assertions.assert_money(fetched["billed_expense_total"], 0.00,
                                "billed_expense_total")
        assert fetched["panel_status_reason"] is None
        assertions.assert_counsel_firm(fetched)

    def test_the_capacity_ceiling_and_conflict_list_default_when_left_unsaid(
        self, api, claims_committee_approver_headers, claims_adjuster_headers
    ):
        """An admission silent on capacity and conflicts takes five slots and no conflicts.

        PRD: "A `ClaimsCommitteeApprover` admits a firm by supplying its `firm_name`, the non-empty `admitted_venue_codes` array of venues where it may practise, the non-empty `allegation_specialties` array of allegation categories it is qualified to defend, its negotiated `blended_hourly_rate` (greater than zero, at most two decimal places), its `quality_score` (an integer from 0 to 100 inclusive), and optionally `max_concurrent_assignments`, a capacity ceiling of at least 1 defaulting to 5, and `conflict_insured_ids`, the insureds it is conflicted out of representing, defaulting to empty."

        Design: Corner/endpoints/counsel_firm_create_read_and_filtered_list_round_trip
        """
        firm = self._admit_halloran(api, claims_committee_approver_headers)

        fetched = validate_success(
            api.get_counsel_firm(firm["id"], claims_adjuster_headers)
        )

        assert int(fetched["max_concurrent_assignments"]) == 5
        assert fetched["conflict_insured_ids"] == []
        assert fetched["firm_name"] == "Halloran Defense LLP"
        assert fetched["admitted_venue_codes"] == ["COOK_IL", "TRAVIS_TX"]
        assert fetched["allegation_specialties"] == [
            "OBSTETRIC_INJURY", "SURGICAL_ERROR"
        ]
        assertions.assert_money(fetched["blended_hourly_rate"], 500.00,
                                "blended_hourly_rate")
        assert int(fetched["quality_score"]) == 95

    def test_the_venue_and_specialty_filters_find_the_firm_a_foreign_venue_does_not(
        self, api, claims_committee_approver_headers, claims_adjuster_headers
    ):
        """The Cook County obstetric filter returns the firm; a Kings County filter returns none.

        PRD: "Panel defence firms filter on `panel_status`, `venue_code` — matching firms admitted in that venue — and `allegation_category`, matching firms carrying that specialty."

        Design: Corner/endpoints/counsel_firm_create_read_and_filtered_list_round_trip
        """
        firm = self._admit_halloran(api, claims_committee_approver_headers)

        matched, matched_meta = validate_paginated(
            api.list_counsel_firms(
                claims_adjuster_headers,
                {"venue_code": "COOK_IL", "allegation_category": "OBSTETRIC_INJURY",
                 "limit": 10, "offset": 0},
            )
        )
        _foreign, foreign_meta = validate_paginated(
            api.list_counsel_firms(claims_adjuster_headers,
                                   {"venue_code": "KINGS_NY"})
        )

        assert matched_meta["total_count"] == 1
        assert matched_meta["has_more"] is False
        assert [row["id"] for row in matched] == [firm["id"]]
        assert foreign_meta["total_count"] == 0


class TestSeverityTrendPopulations:
    """One paying verdict and one defence verdict on the same obstetrics book."""

    @staticmethod
    def _one_paid_and_one_defended_verdict(api):
        """Resolves two claims on one live term: a 400000.00 plaintiff verdict and a
        defence verdict."""
        book = _live_obgyn_book(api)
        insured_id = book["insured"]["id"]

        paying = build_claim(
            api, insured_id, incident_date="2026-08-05", report_date="2026-09-01",
            venue_code="COOK_IL", allegation_category="OBSTETRIC_INJURY",
            demand_amount=800000.00,
        )
        decide_coverage(api, paying["id"], "COVERED")
        paying = dispose_claim(api, paying["id"], "PLAINTIFF_VERDICT",
                               resolved_on="2026-10-01", verdict_amount=400000.00)

        defended = build_claim(
            api, insured_id, incident_date="2026-08-06", report_date="2026-09-01",
            venue_code="COOK_IL", allegation_category="SURGICAL_ERROR",
            demand_amount=300000.00,
        )
        decide_coverage(api, defended["id"], "COVERED")
        defended = dispose_claim(api, defended["id"], "DEFENSE_VERDICT",
                                 resolved_on="2026-10-01")

        return book, paying, defended

    @staticmethod
    def _read_trend(api, book, headers):
        return validate_success(api.get_severity_trend(
            headers,
            {"specialty_class_id": book["specialty_class"]["id"],
             "venue_code": "COOK_IL"},
        ))

    def test_only_the_paying_verdict_is_counted_and_totalled_for_severity(
        self, api, chief_actuary_headers
    ):
        """The defended claim paid nothing, so the severity population is the one claim.

        PRD: "`closed_severity_claim_count` is the number of claims in that scope and `paid_indemnity_total` the sum of their `paid_indemnity`, rounded half up to two decimal places."

        Design: Corner/endpoints/severity_trend_read_uses_a_wider_scope_for_verdicts_than_for_severity
        """
        book, _paying, _defended = self._one_paid_and_one_defended_verdict(api)

        trend = self._read_trend(api, book, chief_actuary_headers)

        assert int(trend["closed_severity_claim_count"]) == 1
        assertions.assert_money(trend["paid_indemnity_total"], 400000.00,
                                "paid_indemnity_total")

    def test_the_paid_average_is_measured_against_the_class_benchmark(
        self, api, chief_actuary_headers
    ):
        """A 400000.00 average against a 640000.00 benchmark runs at 0.6250 of it.

        PRD: "Otherwise `paid_severity_avg` is `paid_indemnity_total` divided by `closed_severity_claim_count` rounded half up to two decimal places, and `trend_index` is that average divided by the specialty class's `benchmark_severity` rounded half up to four decimal places — a figure above 1 meaning the book is running worse than the industry benchmark it is measured against."

        Design: Corner/endpoints/severity_trend_read_uses_a_wider_scope_for_verdicts_than_for_severity
        """
        book, _paying, _defended = self._one_paid_and_one_defended_verdict(api)

        trend = self._read_trend(api, book, chief_actuary_headers)

        assertions.assert_money(trend["paid_severity_avg"], 400000.00,
                                "paid_severity_avg")
        assertions.assert_ratio(trend["trend_index"], 0.6250, "trend_index")

    def test_the_denominator_of_the_trend_index_is_returned_alongside_it(
        self, api, chief_actuary_headers
    ):
        """The obstetrics benchmark of 640000.00 is visible in the same read.

        PRD: "`benchmark_severity` is echoed in the response so the denominator is visible."

        Design: Corner/endpoints/severity_trend_read_uses_a_wider_scope_for_verdicts_than_for_severity
        """
        book, _paying, _defended = self._one_paid_and_one_defended_verdict(api)

        trend = self._read_trend(api, book, chief_actuary_headers)

        assertions.assert_money(trend["benchmark_severity"], 640000.00,
                                "benchmark_severity")

    def test_the_tried_population_splits_the_two_verdicts_evenly(
        self, api, chief_actuary_headers
    ):
        """One defence verdict against one plaintiff verdict is a 0.5000 win rate.

        PRD: "`defense_verdict_count` and `plaintiff_verdict_count` count each of those dispositions within it, and `defense_win_rate` is `defense_verdict_count` divided by the sum of the two counts, rounded half up to four decimal places, or null when no claim was tried at all."

        Design: Corner/endpoints/severity_trend_read_uses_a_wider_scope_for_verdicts_than_for_severity
        """
        book, _paying, _defended = self._one_paid_and_one_defended_verdict(api)

        trend = self._read_trend(api, book, chief_actuary_headers)

        assert int(trend["defense_verdict_count"]) == 1
        assert int(trend["plaintiff_verdict_count"]) == 1
        assertions.assert_ratio(trend["defense_win_rate"], 0.5000,
                                "defense_win_rate")

    def test_the_leading_allegation_is_taken_from_the_paying_population_only(
        self, api, chief_actuary_headers
    ):
        """The surgical-error claim never paid, so obstetric injury leads the severity scope.

        PRD: "`top_allegation_category` is the `allegation_category` occurring most often in the severity scope, ties broken by the earliest creation timestamp among the tied claims, and null when the scope is empty."

        Design: Corner/endpoints/severity_trend_read_uses_a_wider_scope_for_verdicts_than_for_severity
        """
        book, _paying, _defended = self._one_paid_and_one_defended_verdict(api)

        trend = self._read_trend(api, book, chief_actuary_headers)

        assert trend["top_allegation_category"] == "OBSTETRIC_INJURY"

    def test_the_plaintiff_verdict_alone_erodes_the_terms_aggregate_limit(
        self, api, claims_adjuster_headers, underwriting_officer_headers
    ):
        """400000.00 comes off the three-million aggregate; the defended claim takes nothing.

        PRD: "Indemnity moves: on a `PLAINTIFF_VERDICT` the claim's `paid_indemnity` increases by the lesser of `verdict_amount` and the policy's `limit_per_claim`, and the responding term's `aggregate_limit_remaining` is debited by that same capped figure, so a verdict above the per-claim limit erodes the aggregate only to the extent the carrier actually owes it; on a settlement the increase and the debit are both the negotiation's `paid_amount`."

        Design: Corner/endpoints/severity_trend_read_uses_a_wider_scope_for_verdicts_than_for_severity
        """
        book, paying, defended = self._one_paid_and_one_defended_verdict(api)

        paying = validate_success(
            api.get_claim(paying["id"], claims_adjuster_headers)
        )
        defended = validate_success(
            api.get_claim(defended["id"], claims_adjuster_headers)
        )
        term = validate_success(
            api.get_policy_term(book["term"]["id"], underwriting_officer_headers)
        )

        assertions.assert_money(paying["paid_indemnity"], 400000.00,
                                "paid_indemnity of the paid claim")
        assertions.assert_money(defended["paid_indemnity"], 0.00,
                                "paid_indemnity of the defended claim")
        assertions.assert_money(term["aggregate_limit_remaining"], 2600000.00,
                                "aggregate_limit_remaining")


class TestDefenceExpenseLedger:
    """A defence invoice paid against one assignment on one claim."""

    @staticmethod
    def _obstetric_claim(api, insured_id, incident_date="2026-08-05",
                         demand_amount=800000.00):
        claim = build_claim(
            api, insured_id, incident_date=incident_date,
            report_date="2026-09-01", venue_code="COOK_IL",
            allegation_category="OBSTETRIC_INJURY", demand_amount=demand_amount,
        )
        return decide_coverage(api, claim["id"], "COVERED")

    @classmethod
    def _claim_with_counsel(cls, api):
        book = _live_obgyn_book(api)
        firm = build_counsel_firm(api, **HALLORAN_COOK_ONLY)
        claim = cls._obstetric_claim(api, book["insured"]["id"])
        assignment = assign_counsel(api, claim["id"])
        return book, firm, claim, assignment

    def test_the_invoice_lands_in_the_claim_the_assignment_and_the_firm_ledger(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """One 12000.00 defence invoice shows up as 12000.00 in all three ledgers.

        PRD: "The payment increases the claim's `paid_expense`, the assignment's `billed_expense_amount` and the firm's `billed_expense_total` each by the paid amount, and recomputes both incurred figures — which is the point at which `case_incurred` and `actuarial_incurred` begin to diverge, since paid expense erodes the carried expense reserve in the first figure and sits on top of it in the second."

        Design: Corner/endpoints/an_expense_payment_links_the_claim_the_assignment_and_the_firm_ledger
        """
        _book, firm, claim, assignment = self._claim_with_counsel(api)

        paid_claim = validate_success(api.pay_expense(
            claim["id"],
            factories.expense_payment_payload(
                amount=12000.00, invoice_reference="INV-2026-0001",
                counsel_assignment_id=assignment["id"],
            ),
            claims_adjuster_headers,
        ))

        assertions.assert_money(paid_claim["paid_expense"], 12000.00,
                                "paid_expense")
        assertions.assert_money(paid_claim["paid_indemnity"], 0.00,
                                "paid_indemnity")

        reread_assignment = validate_success(api.get_counsel_assignment(
            assignment["id"], claims_adjuster_headers
        ))
        assertions.assert_money(reread_assignment["billed_expense_amount"],
                                12000.00, "billed_expense_amount")

        reread_firm = validate_success(api.get_counsel_firm(
            firm["id"], claims_committee_approver_headers
        ))
        assertions.assert_money(reread_firm["billed_expense_total"], 12000.00,
                                "billed_expense_total")

    def test_paying_an_invoice_leaves_the_assignment_live_and_the_slot_taken(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """Billing against the assignment neither closes it nor releases the firm's slot.

        PRD: "A successful assignment records `claim_id` and the selected `counsel_firm_id`, opens in `ASSIGNED` status with `assigned_at` at the current logical timestamp, `billed_expense_amount` at 0.00 and `decline_reason` and `closed_at` null, increments the firm's `open_assignment_count` by 1, and sets the claim's `counsel_reassignment_required` back to false."

        Design: Corner/endpoints/an_expense_payment_links_the_claim_the_assignment_and_the_firm_ledger
        """
        _book, firm, claim, assignment = self._claim_with_counsel(api)

        validate_success(api.pay_expense(
            claim["id"],
            factories.expense_payment_payload(
                amount=12000.00, invoice_reference="INV-2026-0001",
                counsel_assignment_id=assignment["id"],
            ),
            claims_adjuster_headers,
        ))

        reread_assignment = validate_success(api.get_counsel_assignment(
            assignment["id"], claims_adjuster_headers
        ))
        reread_firm = validate_success(api.get_counsel_firm(
            firm["id"], claims_committee_approver_headers
        ))

        assert reread_assignment["assignment_status"] == "ASSIGNED"
        assert reread_assignment["closed_at"] is None
        assert int(reread_firm["open_assignment_count"]) == 1

    def test_an_invoice_billed_under_another_claims_assignment_is_refused(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """The second claim's counsel cannot be billed against the first claim.

        PRD: "The named assignment must exist (`ERR_COUNSEL_ASSIGNMENT_NOT_FOUND`), must belong to the addressed claim rather than another one (`ERR_ASSIGNMENT_CLAIM_MISMATCH`), and must still be in `ASSIGNED` status (`ERR_ASSIGNMENT_STATE_INVALID`)."

        Design: Corner/endpoints/an_expense_payment_links_the_claim_the_assignment_and_the_firm_ledger
        """
        book, firm, first_claim, _first_assignment = self._claim_with_counsel(api)

        second_claim = self._obstetric_claim(
            api, book["insured"]["id"], incident_date="2026-08-06",
            demand_amount=300000.00,
        )
        second_assignment = assign_counsel(api, second_claim["id"])

        response = api.pay_expense(
            first_claim["id"],
            factories.expense_payment_payload(
                amount=12000.00, invoice_reference="INV-2026-0002",
                counsel_assignment_id=second_assignment["id"],
            ),
            claims_adjuster_headers,
        )

        validate_error(response, ApiErrorId.ERR_ASSIGNMENT_CLAIM_MISMATCH.value, 422)

        reread_claim = validate_success(
            api.get_claim(first_claim["id"], claims_adjuster_headers)
        )
        assertions.assert_money(reread_claim["paid_expense"], 0.00,
                                "paid_expense")
        reread_firm = validate_success(api.get_counsel_firm(
            firm["id"], claims_committee_approver_headers
        ))
        assertions.assert_money(reread_firm["billed_expense_total"], 0.00,
                                "billed_expense_total")
