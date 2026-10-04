"""Compliance reports: deficiency/resubmission cycle, closed-interval overlap,
and the temporal-before-referential validation ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    api_client,
    create_company,
    create_compliance_report_payload,
    get_success_data,
    make_company_representative_headers,
    mark_report_deficient,
    resubmit_report,
    setup_monitored_order,
    submit_compliance_report,
    validate_error,
    validate_success,
)

_ATTORNEY = TEST_USERS["staff_attorney_headers"]


def test_compliance_report_deficiency_resubmission_cycle():
    """PRD section 3.4: "the company's representative resubmits, moving
    `DEFICIENT` back to `SUBMITTED` with a fresh `report_document_ref` under
    the same subject-company ownership rule, which increments
    `resubmission_count` and clears `deficiency_notes`."
    PRD section 3.4: "Acceptance moves `SUBMITTED` to `ACCEPTED` — the
    report's terminal state — recording the reviewer in
    `reviewed_by_user_id`."

    Design: Difficulty/non_linear_state_machine/compliance_report_deficiency_resubmission_cycle
    """
    bundle = setup_monitored_order(
        monetary_relief_cents=2_000_000,
        conduct_prohibitions=["NO_HIDDEN_FEES"],
    )
    order_id = bundle["order"]["id"]
    company_id = bundle["company"]["id"]

    report = submit_compliance_report(
        order_id,
        company_id,
        period_start="2026-10-01T00:00:00Z",
        period_end="2027-03-31T00:00:00Z",
        report_document_ref="doc-cycle-1",
    )
    mark_report_deficient(report["id"], deficiency_notes="Section 4 omits refund ledgers")

    resubmitted = resubmit_report(report["id"], company_id, report_document_ref="doc-cycle-2")
    assert resubmitted["status"] == "SUBMITTED", "the cure-and-resubmit cycle must complete"
    assert resubmitted["resubmission_count"] == 1
    assert resubmitted["deficiency_notes"] is None

    accepted = accept_report(report["id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["reviewed_by_user_id"] == "cm-1"
    assert accepted["resubmission_count"] == 1, "resubmission_count persists after acceptance"


def test_report_window_closed_interval_touching_counts_as_overlap():
    """PRD section 3.4: "a new report's interval must not overlap the interval
    of any existing report on the same order that is `SUBMITTED` or `ACCEPTED`,
    and because both ends are inclusive, merely touching endpoints already
    count as overlap, drawing `ERR_REPORTING_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/report_window_closed_interval_touching_counts_as_overlap
    """
    bundle = setup_monitored_order(
        monetary_relief_cents=2_000_000,
        conduct_prohibitions=["NO_HIDDEN_FEES"],
    )
    order_id = bundle["order"]["id"]
    company_id = bundle["company"]["id"]
    company_headers = make_company_representative_headers(company_id)

    report_1 = submit_compliance_report(
        order_id,
        company_id,
        period_start="2027-01-01T00:00:00Z",
        period_end="2027-06-30T00:00:00Z",
        report_document_ref="doc-h1",
    )

    touching = api_client.create_compliance_report(
        order_id,
        create_compliance_report_payload(
            period_start="2027-06-30T00:00:00Z",
            period_end="2027-12-31T00:00:00Z",
            report_document_ref="doc-h2-touching",
        ),
        company_headers,
    )
    validate_error(touching, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP)

    report_2 = validate_success(
        api_client.create_compliance_report(
            order_id,
            create_compliance_report_payload(
                period_start="2027-07-01T00:00:00Z",
                period_end="2027-12-31T00:00:00Z",
                report_document_ref="doc-h2-clean",
            ),
            company_headers,
        ),
        201,
    )
    assert report_2["status"] == "SUBMITTED"

    rows = get_success_data(api_client.list_compliance_reports(order_id, _ATTORNEY))
    assert sorted(r["id"] for r in rows) == sorted([report_1["id"], report_2["id"]])


def test_report_window_overlap_temporal_beats_company_mismatch_referential():
    """PRD section 2.8: "The company-match check is intentionally evaluated
    *after* the tier-10 overlap check, so a wrong-company submission on an
    overlapping window reports the overlap rather than the mismatch."
    PRD section 3.4: "that identity must equal the order's
    `subject_company_id` — a report filed by any other company is rejected
    with `ERR_REPORT_COMPANY_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/report_window_overlap_temporal_beats_company_mismatch_referential
    """
    bundle = setup_monitored_order(
        monetary_relief_cents=2_000_000,
        conduct_prohibitions=["NO_HIDDEN_FEES"],
    )
    order_id = bundle["order"]["id"]
    company_a_id = bundle["company"]["id"]

    report_1 = submit_compliance_report(
        order_id,
        company_a_id,
        period_start="2027-01-01T00:00:00Z",
        period_end="2027-06-30T00:00:00Z",
        report_document_ref="doc-h1",
    )
    company_b = create_company(legal_name="Beta Brakes Corp", complaint_count_90d=3)
    company_b_headers = make_company_representative_headers(company_b["id"])

    overlapping = api_client.create_compliance_report(
        order_id,
        create_compliance_report_payload(
            period_start="2027-03-01T00:00:00Z",
            period_end="2027-09-01T00:00:00Z",
            report_document_ref="doc-intruder-1",
        ),
        company_b_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP)

    disjoint = api_client.create_compliance_report(
        order_id,
        create_compliance_report_payload(
            period_start="2028-01-01T00:00:00Z",
            period_end="2028-06-30T00:00:00Z",
            report_document_ref="doc-intruder-2",
        ),
        company_b_headers,
    )
    validate_error(disjoint, ApiErrorId.ERR_REPORT_COMPANY_MISMATCH)

    rows = get_success_data(api_client.list_compliance_reports(order_id, _ATTORNEY))
    assert [r["id"] for r in rows] == [report_1["id"]], (
        "both wrong-company submissions must be rejected without persisting a report"
    )
