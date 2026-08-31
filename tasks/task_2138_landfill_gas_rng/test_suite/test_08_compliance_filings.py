"""Regulatory filings: segregation of duties, the revision loop, permit
exceedances, and the three-hop cascade a returned filing sets off."""

from test_helpers import (
    OFFICER_ALICE,
    OFFICER_BOB,
    ApiErrorId,
    approx_2dp,
    assert_compliance_report,
    create_compliance_report_payload,
    fixtures,
    make_compliance_officer_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import SEPTEMBER_CLOCK_UTC

ALICE = make_compliance_officer_headers(OFFICER_ALICE)
BOB = make_compliance_officer_headers(OFFICER_BOB)


def _producing_site_with_attributes_and_issued_statement():
    """A site whose August production has been settled and issued, with both an
    RIN_D3 and an LCFS attribute batch generated for 2026-08."""
    context = fixtures.setup_injected_batch()
    context["rin_batch"] = fixtures.generate_attribute_batch(
        context["batch"]["id"], program="RIN_D3"
    )
    context["lcfs_batch"] = fixtures.generate_attribute_batch(
        context["batch"]["id"], program="LCFS"
    )
    set_clock(SEPTEMBER_CLOCK_UTC)
    context["statement"] = fixtures.setup_issued_statement(
        context["site"]["id"], period="2026-08"
    )
    return context


class TestReportReturnCascade:
    def test_returning_a_filing_puts_the_periods_attribute_batches_on_qa_hold(self, api):
        """PRD §3.9: "Taking `UNDER_REVIEW → RETURNED` requires a `return_reason`, which
        is recorded on the filing, and increments the filing's `revision_count` by one.
        It then puts every attribute batch whose `status` is `GENERATED`, whose
        `generation_period` falls inside the filing's period, and whose producing plant
        belongs to the filing's site, onto `QA_HOLD`."
        PRD §3.8: "A generated batch may be put on `QA_HOLD` pending review and released
        from `QA_HOLD` back to `GENERATED`, closing a review loop that moves no ledger at
        all — attributes on QA hold are still counted in the site's
        `rin_available_count`."

        Design: Difficulty/transitive_cascade/report_return_cascades_attributes_to_qa_hold_and_royalty_to_disputed
        """
        context = _producing_site_with_attributes_and_issued_statement()
        report = fixtures.setup_report_under_review(
            context["site"]["id"], report_type="QUARTERLY_RIN_QAP", period="2026-Q3"
        )

        returned = validate_success(
            api.set_compliance_report_status(
                report["id"],
                {
                    "to_status": "RETURNED",
                    "return_reason": "Meter QA records missing for the August true-up",
                },
                BOB,
            )
        )
        assert returned["status"] == "RETURNED"
        assert returned["revision_count"] == 1
        assert (
            returned["return_reason"]
            == "Meter QA records missing for the August true-up"
        )

        assert fixtures.read_attribute_batch(context["rin_batch"]["id"])["status"] == (
            "QA_HOLD"
        )
        assert fixtures.read_attribute_batch(context["lcfs_batch"]["id"])["status"] == (
            "QA_HOLD"
        )

        site = fixtures.read_site(context["site"]["id"])
        assert site["rin_available_count"] == 3988, (
            "attributes on QA hold are still held"
        )
        assert site["compliance_posture"] == "WATCH"

    def test_returning_a_filing_disputes_the_issued_statement_and_unwinds_the_payable(
        self, api
    ):
        """PRD §3.9: "And because at least one attribute batch has entered QA hold, every
        royalty statement of that site whose `status` is `ISSUED` and whose settlement
        month falls inside the filing's period is moved to `DISPUTED` with its
        `dispute_reason` recorded as `ATTRIBUTE_QA_HOLD`, and the site's
        `royalty_payable_usd` is reduced by each such statement's `royalty_amount_usd`."
        PRD §3.9: "A `ProjectAdmin` issues one, taking `DRAFT → ISSUED` and raising the
        site's `royalty_payable_usd` by the statement's `royalty_amount_usd`."

        Design: Difficulty/transitive_cascade/report_return_cascades_attributes_to_qa_hold_and_royalty_to_disputed
        """
        context = _producing_site_with_attributes_and_issued_statement()
        site_id = context["site"]["id"]
        statement_id = context["statement"]["id"]
        assert context["statement"]["royalty_amount_usd"] == approx_2dp(1711.50)
        assert fixtures.read_site(site_id)["royalty_payable_usd"] == approx_2dp(1711.50)

        report = fixtures.setup_report_under_review(
            site_id, report_type="QUARTERLY_RIN_QAP", period="2026-Q3"
        )
        validate_success(
            api.set_compliance_report_status(
                report["id"],
                {
                    "to_status": "RETURNED",
                    "return_reason": "Meter QA records missing for the August true-up",
                },
                BOB,
            )
        )

        disputed = fixtures.read_royalty_statement(statement_id)
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "ATTRIBUTE_QA_HOLD"
        assert disputed["royalty_amount_usd"] == approx_2dp(1711.50)

        assert fixtures.read_site(site_id)["royalty_payable_usd"] == approx_2dp(0.0), (
            "the third hop of the cascade moves the money"
        )


class TestFilingLifecycle:
    def test_returned_filing_walks_back_to_draft_and_is_resubmitted(self, api):
        """PRD §3.9: "Filings move through `DRAFT → SUBMITTED → UNDER_REVIEW` and then
        either to `RETURNED` and back to `DRAFT`, or to `ACCEPTED`, and every hop is
        governed by segregation of duties enforced against `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.9: "And the officer who takes a returned filing back to `DRAFT` for
        revision must again be the `prepared_by_user_id`."
        PRD §3.1: "It reads `VIOLATION` when any compliance filing of the site whose
        `status` is `SUBMITTED`, `UNDER_REVIEW`, `RETURNED` or `ACCEPTED` carries an
        `exceedance_flag` of true. Failing that, it reads `WATCH` when any filing of the
        site is in `RETURNED`. Otherwise it reads `COMPLIANT`."

        Design: Corner/state_machines/compliance_report_returned_to_draft_completes_revision_loop
        """
        set_clock("2026-08-10T00:00:00Z")
        site = fixtures.create_site()
        report = fixtures.setup_report_under_review(
            site["id"],
            report_type="TITLE_V_SEMIANNUAL",
            period="2026-Q3",
            nmoc_lb_per_hr_reported=2.0,
        )
        validate_success(
            api.set_compliance_report_status(
                report["id"],
                {"to_status": "RETURNED", "return_reason": "Stack test data not attached"},
                BOB,
            )
        )

        back_to_draft = validate_success(
            api.set_compliance_report_status(report["id"], {"to_status": "DRAFT"}, ALICE)
        )
        assert back_to_draft["status"] == "DRAFT"
        assert back_to_draft["revision_count"] == 1

        resubmitted = validate_success(
            api.set_compliance_report_status(
                report["id"], {"to_status": "SUBMITTED"}, ALICE
            )
        )
        assert_compliance_report(resubmitted)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1
        assert resubmitted["prepared_by_user_id"] == OFFICER_ALICE
        assert resubmitted["reviewed_by_user_id"] == OFFICER_BOB
        assert resubmitted["exceedance_flag"] is False

        assert fixtures.read_site(site["id"])["compliance_posture"] == "COMPLIANT"

    def test_a_second_live_filing_for_the_same_site_type_and_period_is_refused(
        self, api
    ):
        """PRD §3.9: "Only one filing may exist for a given site, report type and period
        in any status other than `RETURNED`; a second is refused with
        `ERR_REPORT_PERIOD_DUPLICATE`, which is what allows a returned filing to be
        superseded while a live one cannot be."

        Design: Corner/errors/duplicate_compliance_report_for_same_site_type_and_period_is_rejected
        """
        site = fixtures.create_site()
        first = fixtures.create_compliance_report(
            site["id"],
            report_type="QUARTERLY_RIN_QAP",
            period="2026-Q3",
            nmoc_lb_per_hr_reported=2.0,
        )
        assert first["status"] == "DRAFT"
        assert first["revision_count"] == 0
        assert first["reviewed_by_user_id"] is None

        validate_error(
            api.create_compliance_report(
                create_compliance_report_payload(
                    site["id"],
                    report_type="QUARTERLY_RIN_QAP",
                    period="2026-Q3",
                    nmoc_lb_per_hr_reported=2.5,
                ),
                ALICE,
            ),
            ApiErrorId.ERR_REPORT_PERIOD_DUPLICATE.value,
        )

        _, meta = validate_paginated(
            api.list_compliance_reports(
                ALICE, params={"site_id": site["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1

    def test_accepting_an_exceedance_filing_requires_a_corrective_action_note(
        self, api
    ):
        """PRD §3.9: "The filing's `exceedance_flag` is computed at creation and frozen
        there: it is true when the reported rate is strictly greater than the site's
        `permit_nmoc_limit_lb_per_hr`, and a rate that exactly equals the permit limit is
        not an exceedance."
        PRD §3.9: "Accepting a filing whose `exceedance_flag` is true requires a
        `corrective_action_note`, without which the acceptance is refused with
        `ERR_PERMIT_EXCEEDANCE_UNRESOLVED`; the note is recorded on the filing when
        supplied."

        Design: Corner/errors/accepting_an_exceedance_report_without_corrective_action_is_rejected
        """
        site = fixtures.create_site()
        report = fixtures.setup_report_under_review(
            site["id"],
            report_type="NSPS_ANNUAL",
            period="2026-Q3",
            nmoc_lb_per_hr_reported=5.0,
        )
        assert report["exceedance_flag"] is True, "5.0 exceeds the 3.5 permit limit"

        validate_error(
            api.set_compliance_report_status(
                report["id"], {"to_status": "ACCEPTED"}, BOB
            ),
            ApiErrorId.ERR_PERMIT_EXCEEDANCE_UNRESOLVED.value,
        )
        assert fixtures.read_compliance_report(report["id"])["status"] == "UNDER_REVIEW"

        note = "Additional cover installed on cells 4-6; re-test scheduled"
        accepted = validate_success(
            api.set_compliance_report_status(
                report["id"],
                {"to_status": "ACCEPTED", "corrective_action_note": note},
                BOB,
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["corrective_action_note"] == note

        assert fixtures.read_site(site["id"])["compliance_posture"] == "VIOLATION"

    def test_an_officer_cannot_take_their_own_filing_under_review(self, api):
        """PRD §3.9: "The officer who submits a filing must be its
        `prepared_by_user_id`. The officer who takes it `SUBMITTED → UNDER_REVIEW` must
        **not** be its `prepared_by_user_id`, and that officer's identifier is stamped as
        `reviewed_by_user_id`."
        PRD §3.9: "The creating officer's identifier is recorded as
        `prepared_by_user_id`."

        Design: Corner/rbac/compliance_officer_cannot_take_their_own_report_under_review
        """
        site = fixtures.create_site()
        report = fixtures.create_compliance_report(
            site["id"],
            report_type="LCFS_QUARTERLY",
            period="2026-Q3",
            nmoc_lb_per_hr_reported=1.5,
        )
        fixtures.drive_report(report["id"], OFFICER_ALICE, to_status="SUBMITTED")

        validate_error(
            api.set_compliance_report_status(
                report["id"], {"to_status": "UNDER_REVIEW"}, ALICE
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )
        blocked = fixtures.read_compliance_report(report["id"])
        assert blocked["status"] == "SUBMITTED"
        assert blocked["reviewed_by_user_id"] is None

        under_review = validate_success(
            api.set_compliance_report_status(
                report["id"], {"to_status": "UNDER_REVIEW"}, BOB
            )
        )
        assert under_review["status"] == "UNDER_REVIEW"
        assert under_review["reviewed_by_user_id"] == OFFICER_BOB
        assert under_review["prepared_by_user_id"] == OFFICER_ALICE
