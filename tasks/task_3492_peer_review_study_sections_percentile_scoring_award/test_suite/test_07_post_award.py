"""Post-award administration: progress reports (period and window gates,
disbursal), carryover and no-cost-extension modifications, termination, and
change-of-institution transfers (both proration variants and the successor
cascade)."""
from decimal import Decimal, ROUND_HALF_UP

import pytest

from test_helpers import (
    api_client,
    fixtures,
    factories,
    TEST_USERS,
    make_applicant_headers,
    validate_success,
    validate_error,
    ApiErrorId,
    TERM_TRANSFERRED_AWARD,
    TERM_STANDARD,
    iso_days_between,
    assert_transfer_conservation,
)

_GO = TEST_USERS["grants_officer_headers"]


def _rhup_int(value) -> int:
    """Round half up to a whole cent (PRD money precision rule)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _time_prorated_relinquished(total_cents: int, start_iso: str, end_iso: str,
                                effective_iso: str) -> int:
    """PRD §3.9 TIME_PRORATED variant: total x (whole days remaining from
    effective_date to end_date, never below zero) / (whole days from
    start_date to end_date), rounded half up to a whole cent."""
    total_days = iso_days_between(start_iso, end_iso)
    days_remaining = max(iso_days_between(effective_iso, end_iso), 0)
    return _rhup_int(Decimal(total_cents) * Decimal(days_remaining) / Decimal(total_days))


def test_transfer_relinquishment_time_vs_ledger_variants():
    """PRD §3.9: "When at least one progress report has been accepted on the award, so its `disbursed_cents` is greater than zero, the `LEDGER_ACTUALS` variant applies: the entire undisbursed balance moves, and `relinquished_amount_cents` is the `total_awarded_cents` minus the `disbursed_cents`."
    PRD §3.9: "When no report has been accepted, the `TIME_PRORATED` variant applies a straight-line calendar proration: the relinquished amount is the award's `total_awarded_cents` multiplied by the fraction of the award remaining — the whole days from the `effective_date` to the `end_date` (never below zero) divided by the whole days from the `start_date` to the `end_date` — rounded half up to a whole cent."
    Derivation: both awards total 30,000,000 cents over 2027-01-01..
    2028-01-01 (365 days). Award A accepted a 12,000,000 report, so it
    relinquishes 30,000,000 - 12,000,000 = 18,000,000 wholesale. Award B has
    no report: 184 days remain at the 2027-07-01 effective date, so it
    relinquishes rhup(30,000,000 x 184 / 365) = 15,123,288.

    Design: Difficulty/dual_variant_calc/transfer_relinquishment_time_vs_ledger_variants
    """
    scen_a = fixtures.setup_proposed_transfer(with_report_cents=12_000_000)
    tr_a = fixtures.relinquish_transfer_request(scen_a["transfer"]["id"])
    award_a = fixtures.refresh_award(scen_a["award"]["id"])
    assert award_a["disbursed_cents"] == 12_000_000
    assert tr_a["status"] == "RELINQUISHED"
    assert tr_a["proration_variant"] == "LEDGER_ACTUALS"
    assert tr_a["relinquished_amount_cents"] == (
        award_a["total_awarded_cents"] - award_a["disbursed_cents"]
    ) == 18_000_000

    scen_b = fixtures.setup_proposed_transfer()
    tr_b = fixtures.relinquish_transfer_request(scen_b["transfer"]["id"])
    award_b = fixtures.refresh_award(scen_b["award"]["id"])
    assert award_b["disbursed_cents"] == 0
    expected_b = _time_prorated_relinquished(
        award_b["total_awarded_cents"], award_b["start_date"], award_b["end_date"],
        scen_b["transfer"]["effective_date"])
    assert expected_b == 15_123_288
    assert tr_b["status"] == "RELINQUISHED"
    assert tr_b["proration_variant"] == "TIME_PRORATED"
    assert tr_b["relinquished_amount_cents"] == expected_b
    # Identical totals and dates still diverge across variants once spending
    # deviates from the straight line.
    assert tr_a["relinquished_amount_cents"] != tr_b["relinquished_amount_cents"]


def test_transfer_accept_cascade_spawns_successor_award():
    """PRD §3.9: "A `decision` of `ACCEPT` fires a three-level cascade: first, the original award moves from `ACTIVE` to the terminal `TRANSFERRED` state, and the institute's `committed_cents` is reduced by the relinquished amount plus the retained amount; second, a successor award is created for the same application and institute, with `institution_id` set to the `to_institution_id`, `total_awarded_cents` equal to the relinquished amount, `start_date` equal to the `effective_date`, `end_date` equal to the original award's `end_date`, a single-element `period_total_cents` holding exactly the relinquished amount, `current_period` at 1, `terms_and_conditions` gaining `TRANSFERRED_AWARD` alongside `STANDARD_TERMS_V1`, and `originating_transfer_id` set to the transfer request's `id`; third, the institute's `committed_cents` grows back by the `relinquished_amount_cents`."

    Design: Difficulty/transitive_cascade/transfer_accept_cascade_spawns_successor_award
    """
    scen = fixtures.setup_relinquished_transfer()
    transfer = scen["transfer"]
    award = scen["award"]
    relinquished = transfer["relinquished_amount_cents"]
    assert relinquished == 15_123_288  # TIME_PRORATED, no accepted reports
    committed_at_issue = scen["institute"]["committed_cents"]
    assert committed_at_issue == award["total_awarded_cents"] == 30_000_000

    resp = api_client.decide_transfer(
        transfer["id"], factories.transfer_decide_payload("ACCEPT"), _GO)
    assert validate_success(resp, 200)["status"] == "ACCEPTED"

    original = fixtures.refresh_award(award["id"])
    assert original["status"] == "TRANSFERRED"

    successor = fixtures.fetch_successor_award(transfer["id"])
    assert successor["institution_id"] == scen["to_institution"]["id"]
    assert successor["total_awarded_cents"] == relinquished
    assert successor["status"] == "ACTIVE"
    assert successor["period_total_cents"] == [relinquished]
    assert successor["current_period"] == 1
    assert successor["start_date"] == transfer["effective_date"]
    assert successor["end_date"] == original["end_date"]
    assert successor["originating_transfer_id"] == transfer["id"]
    assert TERM_TRANSFERRED_AWARD in successor["terms_and_conditions"]
    assert TERM_STANDARD in successor["terms_and_conditions"]

    institute = fixtures.refresh_institute(scen["context"]["institute"]["id"])
    retained = award["total_awarded_cents"] - award["disbursed_cents"] - relinquished
    # committed falls by (relinquished + retained) then regains relinquished.
    assert institute["committed_cents"] == (
        committed_at_issue - relinquished - retained + relinquished
    ) == relinquished


def test_nce_extensions_adjoin_without_gap_or_overlap():
    """PRD §3.9: "For a no-cost extension, the request must arrive while the logical clock is not past the award's `end_date` (`ERR_NCE_TOO_LATE`); the `new_end_date` must fall after the current `end_date` (`ERR_VALIDATION`); and the requested extension must not exceed 365 days beyond the current `end_date` (`ERR_NCE_LIMIT_EXCEEDED`)."
    PRD §3.9: "The first approved extension of up to 365 days auto-approves at creation into `AUTO_APPROVED`; when the award already has an approved extension, the request waits in `PENDING_APPROVAL`."
    PRD §3.9: "Approval sets the award's `end_date` to the `new_end_date`, the extension adjoining the prior end date with no gap and no overlap."
    Derivation: the 1-year award ends 2028-01-01; the first extension to
    2028-07-01 spans 182 days (<= 365) and auto-approves; the second, to
    2028-12-31, spans 183 days but is never automatic because an approved
    extension already exists.

    Design: Difficulty/resource_temporal_overlap/nce_extensions_adjoin_without_gap_or_overlap
    """
    scen = fixtures.setup_active_award()
    award = scen["award"]
    pi_id = scen["applicant"]["id"]
    assert award["end_date"] == "2028-01-01T00:00:00Z"
    total_at_issue = award["total_awarded_cents"]

    nce1 = validate_success(api_client.create_award_modification(
        award["id"],
        factories.award_modification_payload(
            "NO_COST_EXTENSION", new_end_date="2028-07-01T00:00:00Z",
            reason="first extension"),
        make_applicant_headers(pi_id)), 201)
    assert nce1["status"] == "AUTO_APPROVED"
    assert nce1["auto_approved"] is True

    nce2 = validate_success(api_client.create_award_modification(
        award["id"],
        factories.award_modification_payload(
            "NO_COST_EXTENSION", new_end_date="2028-12-31T00:00:00Z",
            reason="second extension"),
        make_applicant_headers(pi_id)), 201)
    assert nce2["status"] == "PENDING_APPROVAL", (
        "a second extension never auto-approves, even within the 365-day limit"
    )
    assert nce2["auto_approved"] is False

    approved = fixtures.decide_modification(nce2["id"], "APPROVE")
    assert approved["status"] == "APPROVED"

    final = fixtures.refresh_award(award["id"])
    assert final["end_date"] == "2028-12-31T00:00:00Z", (
        "extensions adjoin: 2028-01-01 -> 2028-07-01 -> 2028-12-31, no gap, no overlap"
    )
    assert final["total_awarded_cents"] == total_at_issue, (
        "an NCE adds time, never funds"
    )


def test_institute_funds_conserved_across_issue_disbursal_termination():
    """PRD §2.8: "The commitment authority available to any funding decision is the appropriation reduced by outstanding commitments, cumulative disbursements, and the reserve."
    PRD §2.8: "Accepting a progress report converts commitment into outlay: the institute's `committed_cents` falls and its `disbursed_cents` rises by the disbursed amount."
    PRD §3.9: "A termination always auto-approves at creation: the modification lands in `AUTO_APPROVED`, the award moves from `ACTIVE` to the terminal `TERMINATED` state, and the institute's `committed_cents` is reduced by the award's undisbursed balance — its `total_awarded_cents` minus its `disbursed_cents`."
    Derivation: issue 30,000,000; accept a 12,000,000 report; terminating
    returns the undisbursed 18,000,000, so committed ends at 0, disbursed at
    12,000,000, and the headroom 100,000,000 - 5,000,000 - 0 - 12,000,000 =
    83,000,000 is unchanged by the round-trip.

    Design: Difficulty/compensating_invariant/institute_funds_conserved_across_issue_disbursal_termination
    """
    scen = fixtures.setup_award_with_accepted_report(
        actual_expenditure_cents=12_000_000,
        context_kwargs={"appropriation_cents": 100_000_000, "reserve_cents": 5_000_000})
    award = scen["award"]
    assert award["disbursed_cents"] == 12_000_000

    mod = validate_success(api_client.create_award_modification(
        award["id"],
        factories.award_modification_payload(
            "TERMINATION", reason="PI withdrew from research"),
        _GO), 201)
    assert mod["status"] == "AUTO_APPROVED"
    assert mod["auto_approved"] is True

    assert fixtures.refresh_award(award["id"])["status"] == "TERMINATED"
    institute = fixtures.refresh_institute(scen["context"]["institute"]["id"])
    assert institute["committed_cents"] == 0
    assert institute["disbursed_cents"] == 12_000_000
    headroom = (institute["appropriation_cents"] - institute["reserve_cents"]
                - institute["committed_cents"] - institute["disbursed_cents"])
    assert headroom == 83_000_000


def test_transfer_lineage_conserves_total_awarded():
    """PRD §3.9: "Either way, the retained amount is whatever neither moved nor was spent — the total minus the disbursed minus the relinquished — and the three parts always re-sum to the award's `total_awarded_cents`."
    PRD §3.9: "second, a successor award is created for the same application and institute, with `institution_id` set to the `to_institution_id`, `total_awarded_cents` equal to the relinquished amount, `start_date` equal to the `effective_date`, `end_date` equal to the original award's `end_date`, a single-element `period_total_cents` holding exactly the relinquished amount, `current_period` at 1, `terms_and_conditions` gaining `TRANSFERRED_AWARD` alongside `STANDARD_TERMS_V1`, and `originating_transfer_id` set to the transfer request's `id`; third, the institute's `committed_cents` grows back by the `relinquished_amount_cents`."
    Derivation: no disbursal, so TIME_PRORATED relinquishes 15,123,288 of the
    30,000,000 total and retains 14,876,712; the successor carries exactly the
    relinquished amount and the institute's committed ends at 15,123,288.

    Design: Difficulty/compensating_invariant/transfer_lineage_conserves_total_awarded
    """
    scen = fixtures.setup_relinquished_transfer()
    transfer = scen["transfer"]
    award = scen["award"]
    relinquished = transfer["relinquished_amount_cents"]
    fixtures.decide_transfer_request(transfer["id"], "ACCEPT")

    original = fixtures.refresh_award(award["id"])
    assert original["status"] == "TRANSFERRED"
    assert original["total_awarded_cents"] == award["total_awarded_cents"] == 30_000_000
    assert original["disbursed_cents"] == 0

    successor = fixtures.fetch_successor_award(transfer["id"])
    assert successor["total_awarded_cents"] == relinquished
    assert successor["disbursed_cents"] == 0

    # Conservation along the lineage: total == disbursed + retained + moved.
    assert_transfer_conservation(original, successor, relinquished)
    retained = original["total_awarded_cents"] - original["disbursed_cents"] - relinquished
    assert retained == 14_876_712

    institute = fixtures.refresh_institute(scen["context"]["institute"]["id"])
    assert institute["committed_cents"] == relinquished == 15_123_288
    assert institute["disbursed_cents"] == 0


def test_transfer_decide_before_relinquish_rejected():
    """PRD §3.9: "The final decision by a `GrantsOfficer` requires the `RELINQUISHED` state (`ERR_TRANSFER_INVALID_STATE`)."
    PRD §3.9: "A `decision` of `DECLINE` moves the request to the terminal `DECLINED` state with an optional `decline_reason` and no fiscal movement."

    Design: Corner/state_machines/transfer_decide_before_relinquish_rejected
    """
    scen = fixtures.setup_proposed_transfer()
    transfer = scen["transfer"]
    assert transfer["status"] == "PROPOSED"

    early = api_client.decide_transfer(
        transfer["id"], factories.transfer_decide_payload("ACCEPT"), _GO)
    validate_error(early, ApiErrorId.ERR_TRANSFER_INVALID_STATE)

    relinquished = fixtures.relinquish_transfer_request(transfer["id"])
    assert relinquished["status"] == "RELINQUISHED"
    award = fixtures.refresh_award(scen["award"]["id"])
    assert relinquished["relinquished_amount_cents"] == _time_prorated_relinquished(
        award["total_awarded_cents"], award["start_date"], award["end_date"],
        transfer["effective_date"]) == 15_123_288

    declined = fixtures.decide_transfer_request(transfer["id"], "DECLINE")
    assert declined["status"] == "DECLINED"
    assert fixtures.refresh_award(scen["award"]["id"])["status"] == "ACTIVE", (
        "a declined transfer leaves the award untouched"
    )


def test_carryover_quarter_boundary_auto_then_pending():
    """PRD §3.9: "The source period's unobligated balance is its `period_total_cents` entry minus its `disbursed_per_period_cents` entry; `carried_out_per_period_cents` is an audit trail only and is never subtracted again, because prior carryovers have already reduced `period_total_cents`."
    PRD §3.9: "When the amount is at most one quarter of the unobligated balance — the quarter computed with half-up rounding to a whole cent — the modification lands directly in the terminal `AUTO_APPROVED` state and its effects apply immediately; otherwise it waits in `PENDING_APPROVAL`."
    PRD §3.9: "The effects, immediate or upon later approval: the source period's `period_total_cents` entry is reduced by the amount, the source period's `carried_out_per_period_cents` grows by it, and the current period's `period_total_cents` entry grows by the same amount, so the award's total budget is conserved."
    Derivation: period totals [30,000,000, 30,000,000]; the accepted period-1
    report disburses 18,000,000, so unobligated(1) = 12,000,000 and exactly
    one quarter (3,000,000, boundary is <=) auto-approves; after it,
    unobligated(1) = 9,000,000 and its quarter is 2,250,000, so 3,000,001
    waits pending.

    Design: Corner/calculations/carryover_quarter_boundary_auto_then_pending
    """
    scen = fixtures.setup_award_with_accepted_report(
        actual_expenditure_cents=18_000_000,
        direct_cents_per_year=[20_000_000, 20_000_000],
        requested_years=2)
    award = scen["award"]
    pi_id = scen["applicant"]["id"]
    assert award["period_total_cents"] == [30_000_000, 30_000_000]
    assert award["current_period"] == 2

    co1 = validate_success(api_client.create_award_modification(
        award["id"],
        factories.award_modification_payload(
            "CARRYOVER", amount_cents=3_000_000, from_period=1,
            reason="quarter of unobligated"),
        make_applicant_headers(pi_id)), 201)
    assert co1["status"] == "AUTO_APPROVED"
    assert co1["auto_approved"] is True

    co2 = validate_success(api_client.create_award_modification(
        award["id"],
        factories.award_modification_payload(
            "CARRYOVER", amount_cents=3_000_001, from_period=1,
            reason="one cent over recomputed quarter"),
        make_applicant_headers(pi_id)), 201)
    assert co2["status"] == "PENDING_APPROVAL"
    assert co2["auto_approved"] is False

    approved = fixtures.decide_modification(co2["id"], "APPROVE")
    assert approved["status"] == "APPROVED"

    final = fixtures.refresh_award(award["id"])
    assert final["period_total_cents"] == [23_999_999, 36_000_001]
    assert final["total_awarded_cents"] == 60_000_000, (
        "the award's total budget is conserved across both carryovers"
    )
    assert final["current_period"] == 2


def test_progress_report_period_window_and_late_flag():
    """PRD §3.9: "The `period_year` must equal the award's `current_period` (`ERR_REPORT_PERIOD_MISMATCH`)."
    PRD §3.9: "Each budget period spans 365 days from the award's `start_date`, and the filing window closes ninety days after the current period's end: filing past that close is rejected with `ERR_REPORT_WINDOW_CLOSED`, while filing after the period's end but within the grace window succeeds and records `submitted_late` as true."
    PRD §3.9: "Acceptance disburses the period: the disbursed amount is the lesser of the report's `actual_expenditure_cents` and the award's `period_total_cents` entry for the current period."
    Derivation: period 1 spans [2027-01-01, 2028-01-01); a filing at
    2028-02-01 is late but inside the 90-day grace; period 2's window closes
    90 days after 2029-01-01, so a filing at 2029-05-01 is past the close.

    Design: Corner/calculations/progress_report_period_window_and_late_flag
    """
    scen = fixtures.setup_active_award(
        direct_cents_per_year=[20_000_000, 20_000_000], requested_years=2)
    award = scen["award"]
    pi_id = scen["applicant"]["id"]
    headers = make_applicant_headers(pi_id)

    # current_period is 1, so a report for period 2 mismatches.
    wrong_period = api_client.create_progress_report(
        award["id"], factories.progress_report_payload(2, 1_000_000, 0), headers)
    validate_error(wrong_period, ApiErrorId.ERR_REPORT_PERIOD_MISMATCH)

    # After period-1 end but within the +90-day grace: late but accepted.
    fixtures.advance_clock("2028-02-01T00:00:00Z")
    created = api_client.create_progress_report(
        award["id"], factories.progress_report_payload(1, 5_000_000, 1), headers)
    report = validate_success(created, 201)
    assert report["submitted_late"] is True
    assert report["status"] == "SUBMITTED"

    accepted = fixtures.accept_report(report["id"])
    assert accepted["status"] == "ACCEPTED"
    after = fixtures.refresh_award(award["id"])
    # disbursed = min(5,000,000, period_total_cents[1] == 30,000,000)
    assert after["disbursed_cents"] == 5_000_000
    assert after["current_period"] == 2

    # Period 2's grace closed 90 days after 2029-01-01; 2029-05-01 is past it.
    fixtures.advance_clock("2029-05-01T00:00:00Z")
    closed = api_client.create_progress_report(
        award["id"], factories.progress_report_payload(2, 1_000_000, 0), headers)
    validate_error(closed, ApiErrorId.ERR_REPORT_WINDOW_CLOSED)


def test_applicant_cannot_create_termination_modification():
    """PRD §2.1: "Within the shared post-award modification capability, the two entity-adjacent roles split by modification type: an `Applicant` may request only `CARRYOVER` or `NO_COST_EXTENSION` modifications, while a `GrantsOfficer` may create only `TERMINATION` modifications; crossing that line is rejected with `ERR_MODIFICATION_TYPE_ROLE_MISMATCH`."

    Design: Corner/rbac/applicant_cannot_create_termination_modification
    """
    scen = fixtures.setup_active_award()
    award = scen["award"]
    resp = api_client.create_award_modification(
        award["id"],
        factories.award_modification_payload(
            "TERMINATION", reason="applicant self-termination attempt"),
        make_applicant_headers(scen["applicant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_MODIFICATION_TYPE_ROLE_MISMATCH)
    assert fixtures.refresh_award(award["id"])["status"] == "ACTIVE"
