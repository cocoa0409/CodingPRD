"""Regulatory reporting: the period lock a submitted filing lays over reversals,
the open-findings gate that binds one report type only, the reject-and-resubmit
loop that ends in a terminal acceptance, and the variance tolerance whose
boundary is inclusive at exactly half a percent."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_INVALID_REPORT_STATE,
    ERR_OPEN_INTEGRITY_FINDINGS,
    ERR_REPORTING_PERIOD_LOCKED,
    ERR_REPORT_VARIANCE_EXCEEDED,
    ERR_SOD_REMEDIATION_SELF_VERIFICATION,
)
from test_helpers.assertions import (
    assert_error_envelope,
    assert_field_derived_block,
    assert_ok,
    assert_variance_pct,
    assert_volume,
)
from test_helpers.constants import (
    AGENCY_ACCEPTED,
    AGENCY_REJECTED,
    DIRECTION_INJECTION,
    INTEGRITY_REMEDIATED,
    REMEDIATION_COMPLETED,
    REPORT_ACCEPTED,
    REPORT_DRAFT,
    REPORT_REJECTED,
    REPORT_SUBMITTED,
    REPORT_TYPE_INTEGRITY,
    REPORT_TYPE_INVENTORY,
    TICKET_REVERSED,
    TIER_3,
)
from test_helpers.fixtures import (
    create_field,
    create_report,
    create_std_field,
    create_well,
    fail_mit_on_well,
    moved_gas,
    read_contract,
    read_field,
    read_program,
    read_well,
    remediate_well,
    reverse_ticket,
    submit_report,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_B,
    FIELD_OPERATOR,
    OFFICER_A_ID,
    OFFICER_B_ID,
    SCHEDULING_COORDINATOR,
)


def _submit(api, report_id, headers=None):
    """Raw submission, defaulting to the second officer so the duty split holds."""
    return api.submit_regulatory_report(report_id, headers or COMPLIANCE_OFFICER_B)


def _agency_response(api, report_id, outcome, note=None):
    return api.record_agency_response(
        report_id, F.agency_response_payload(outcome, note), COMPLIANCE_OFFICER
    )


def _reports_on_field(api, field_id, **params):
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(
        api.list_field_regulatory_reports(field_id, COMPLIANCE_OFFICER, query)
    )


def _read_report(api, field_id, report_id):
    """The PRD gives reports no individual read channel, so they are re-read
    through the reservoir's own report listing."""
    rows, _ = _reports_on_field(api, field_id)
    matching = [row for row in rows if row["id"] == report_id]
    assert len(matching) == 1, f"Expected report {report_id} in the field listing"
    return matching[0]


class TestReportingPeriodLock:
    """The lock is period-scoped and status-scoped, never permanent."""

    def test_a_submitted_filing_blocks_the_reversal_until_the_agency_rejects_it(self, api, mini_world):
        """A submitted inventory verification covering all of August freezes the
        2026-08-20 ticket, and recording a rejection -- a state change on a completely
        different aggregate -- unlocks the very same call, which then puts every
        reservoir and contract quantity back where it started.

        PRD §2.11 rung 31: "**Reporting period lock.** A gas movement ticket may not be
        reversed while a regulatory report on the same storage field, in `SUBMITTED` or
        `ACCEPTED` status, covers the ticket's nomination `gas_day` — otherwise
        `ERR_REPORTING_PERIOD_LOCKED` (409)."

        Design: Corner/state_machines/ticket_reversal_locked_by_a_submitted_report_until_the_agency_rejects_it
        """
        moved = moved_gas(
            api, mini_world.contract_id, mini_world.shipper_id,
            mini_world.field_id, mini_world.well_id, 76000,
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
        )
        prepared = create_report(api, mini_world.field_id, 326000.000)
        assert_volume(prepared["book_inventory_dth"], 326000.000, "book_inventory_dth")
        assert_volume(prepared["variance_dth"], 0.000, "variance_dth")
        assert_variance_pct(prepared["variance_pct"], 0.0000)
        assert prepared["open_finding_count"] == 0, (
            f"No remediation program exists, got {prepared['open_finding_count']}"
        )
        assert prepared["prepared_by_user_id"] == OFFICER_A_ID
        assert prepared["status"] == REPORT_DRAFT

        submitted = submit_report(api, prepared["id"])
        assert submitted["status"] == REPORT_SUBMITTED
        assert submitted["submitted_by_user_id"] == OFFICER_B_ID, (
            f"submitted_by_user_id: expected {OFFICER_B_ID}, got {submitted['submitted_by_user_id']}"
        )

        assert_error_envelope(
            api.reverse_ticket(
                moved.ticket["id"],
                F.ticket_reversal_payload("chart integration error"),
                FIELD_OPERATOR,
            ),
            ERR_REPORTING_PERIOD_LOCKED,
        )

        rejected = assert_ok(
            _agency_response(
                api, prepared["id"], AGENCY_REJECTED, "resubmit with corrected meter data"
            )
        )
        assert rejected["status"] == REPORT_REJECTED
        assert rejected["agency_outcome"] == AGENCY_REJECTED
        assert rejected["agency_response_note"] == "resubmit with corrected meter data"

        unlocked = reverse_ticket(api, moved.ticket["id"], "chart integration error")
        assert unlocked["status"] == TICKET_REVERSED, (
            f"The rejection unlocks the covered gas days, got {unlocked['status']}"
        )
        assert unlocked["reversal_reason"] == "chart integration error"

        field = read_field(api, mini_world.field_id)
        assert_field_derived_block(
            field, working_gas=250000.000, inventory_pct=50.00, pressure=1500,
            injection_rate=150000, withdrawal_rate=150000,
        )
        assert_volume(field["retained_fuel_pool_dth"], 0.000, "retained_fuel_pool_dth")
        contract = read_contract(api, mini_world.contract_id)
        assert_volume(contract["inventory_balance_dth"], 0.000, "inventory_balance_dth")
        assert_volume(contract["imbalance_dth"], 0.000, "imbalance_dth")

        _, meta = validate_paginated(
            api.list_ledger_entries(mini_world.contract_id, SCHEDULING_COORDINATOR, {"limit": 100})
        )
        assert meta["total_count"] == 2, (
            "The reversal appends the negated row instead of editing the original, got "
            f"{meta['total_count']}"
        )


class TestOpenIntegrityFindingsGate:
    """`open_finding_count` is snapshotted on both report types but gates one."""

    def test_only_the_integrity_filing_is_refused_while_a_program_stands_open(self, api):
        """With one open remediation program on the reservoir, the inventory verification
        submits successfully while the integrity filing is refused -- and because the count
        is refreshed at submission rather than trusted from preparation, closing the program
        lets the very same report through without re-preparing it.

        PRD §3.9: "a filing of type `INTEGRITY_PROGRAM_STATUS` may only go out when the
        reservoir has no open integrity work: `open_finding_count` is refreshed at
        submission to the current number of `OPEN` or `ESCALATED` remediation programs on
        the reservoir's wellbores, and must be zero, otherwise the submission is refused
        with `ERR_OPEN_INTEGRITY_FINDINGS`."

        Design: Corner/validations/integrity_report_submission_is_gated_only_for_the_integrity_report_type
        """
        field = create_field(api)
        first_well = create_well(api, field["id"], well_name="MINI-1")
        create_well(api, field["id"], well_name="MINI-2")
        failure = fail_mit_on_well(api, first_well["id"])

        inventory = create_report(api, field["id"], 250000.000, report_type=REPORT_TYPE_INVENTORY)
        integrity = create_report(api, field["id"], 250000.000, report_type=REPORT_TYPE_INTEGRITY)
        for report in (inventory, integrity):
            assert_volume(report["book_inventory_dth"], 250000.000, "book_inventory_dth")
            assert_volume(report["variance_dth"], 0.000, "variance_dth")
            assert_variance_pct(report["variance_pct"], 0.0000)
            assert report["open_finding_count"] == 1, (
                f"Both types snapshot the one open program, got {report['open_finding_count']}"
            )

        filed = assert_ok(_submit(api, inventory["id"]))
        assert filed["status"] == REPORT_SUBMITTED, (
            f"An inventory verification is not gated on findings, got {filed['status']}"
        )

        assert_error_envelope(_submit(api, integrity["id"]), ERR_OPEN_INTEGRITY_FINDINGS)
        assert _read_report(api, field["id"], integrity["id"])["status"] == REPORT_DRAFT, (
            "A refused submission leaves the report where it was"
        )

        closed = remediate_well(api, failure.program["id"], notes="Casing repair verified independently")
        assert closed["status"] == REMEDIATION_COMPLETED
        assert read_program(api, failure.program["id"])["status"] == REMEDIATION_COMPLETED
        assert read_well(api, first_well["id"])["integrity_state"] == INTEGRITY_REMEDIATED

        admitted = assert_ok(_submit(api, integrity["id"]))
        assert admitted["status"] == REPORT_SUBMITTED, (
            f"The identical call must now pass, got {admitted['status']}"
        )
        assert admitted["open_finding_count"] == 0, (
            f"The count is refreshed at submission, got {admitted['open_finding_count']}"
        )

        rows, meta = _reports_on_field(api, field["id"])
        assert meta["total_count"] == 2, f"Expected two filings, got {meta['total_count']}"
        assert [row["status"] for row in rows] == [REPORT_SUBMITTED, REPORT_SUBMITTED]


def _zero_variance_report(api):
    """The standard reservoir at its opening 3,000,000 Dth with a filing measured at
    exactly that figure, so the variance gate can never interfere with the loop."""
    field = create_std_field(api)
    create_well(api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=600000)
    report = create_report(api, field["id"], 3000000.000)
    return field, report


class TestRejectedResubmissionLoop:
    """`REJECTED` is a back edge into `SUBMITTED`; `ACCEPTED` is the end."""

    def test_the_back_edge_re_runs_the_second_officer_rule(self, api):
        """A rejected filing may be submitted again, and the re-submission is held to the
        same duty split as the original: the preparing officer is still refused, the
        reviewing officer still succeeds, and the report re-enters SUBMITTED without ever
        being re-prepared.

        PRD §3.9: "A rejected report is not terminal: it may be submitted again, moving
        from `REJECTED` back to `SUBMITTED`, and that re-submission is held to the same
        second-officer rule and the same variance tolerance as the original, re-locking
        the covered gas days on success."

        Design: Difficulty/non_linear_state_machine/regulatory_report_rejected_resubmission_loop_then_terminal_lockdown
        """
        field, report = _zero_variance_report(api)
        assert_volume(report["book_inventory_dth"], 3000000.000, "book_inventory_dth")
        assert_volume(report["variance_dth"], 0.000, "variance_dth")
        assert_variance_pct(report["variance_pct"], 0.0000)
        assert report["open_finding_count"] == 0

        first = assert_ok(_submit(api, report["id"]))
        assert first["status"] == REPORT_SUBMITTED
        assert first["submitted_by_user_id"] == OFFICER_B_ID

        rejected = assert_ok(
            _agency_response(
                api, report["id"], AGENCY_REJECTED, "Measurement basis needs restating."
            )
        )
        assert rejected["status"] == REPORT_REJECTED
        assert rejected["agency_response_note"] == "Measurement basis needs restating."

        assert_error_envelope(
            _submit(api, report["id"], COMPLIANCE_OFFICER),
            ERR_SOD_REMEDIATION_SELF_VERIFICATION,
        )
        assert _read_report(api, field["id"], report["id"])["status"] == REPORT_REJECTED, (
            "The refused re-submission leaves the report REJECTED"
        )

        second = assert_ok(_submit(api, report["id"]))
        assert second["status"] == REPORT_SUBMITTED, (
            f"The back edge from REJECTED must fire, got {second['status']}"
        )
        assert second["submitted_by_user_id"] == OFFICER_B_ID
        assert second["prepared_by_user_id"] == OFFICER_A_ID, (
            "Re-submission never re-stamps the preparer, got "
            f"{second['prepared_by_user_id']}"
        )

    def test_acceptance_is_terminal_and_closes_the_loop(self, api):
        """Once the agency accepts, the loop is over: a fourth submission is refused with
        the report's own transition-legality code and the filing stays ACCEPTED.

        PRD §3.9: "An `ACCEPTED` disposition moves the report from `SUBMITTED` to the
        terminal `ACCEPTED` status and the covered gas days stay locked permanently — an
        accepted filing can never be undermined by a later reversal."

        Design: Difficulty/non_linear_state_machine/regulatory_report_rejected_resubmission_loop_then_terminal_lockdown
        """
        field, report = _zero_variance_report(api)
        assert_ok(_submit(api, report["id"]))
        assert_ok(_agency_response(api, report["id"], AGENCY_REJECTED, "Restate the basis."))
        assert_ok(_submit(api, report["id"]))

        accepted = assert_ok(_agency_response(api, report["id"], AGENCY_ACCEPTED))
        assert accepted["status"] == REPORT_ACCEPTED, (
            f"status: expected ACCEPTED, got {accepted['status']}"
        )
        assert accepted["agency_outcome"] == AGENCY_ACCEPTED

        assert_error_envelope(_submit(api, report["id"]), ERR_INVALID_REPORT_STATE)
        final = _read_report(api, field["id"], report["id"])
        assert final["status"] == REPORT_ACCEPTED, (
            f"The refused submit changes nothing on a terminal row, got {final['status']}"
        )
        assert final["prepared_by_user_id"] == OFFICER_A_ID
        assert final["submitted_by_user_id"] == OFFICER_B_ID


class TestVarianceToleranceBoundary:
    """0.5000 percent is admissible; 0.6000 percent is not."""

    def _five_million_field(self, api):
        field = create_std_field(api, opening_working_gas_dth=5000000)
        create_well(api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=600000)
        return field

    def test_exactly_half_a_percent_of_variance_is_admissible(self, api):
        """Against a book inventory of 5,000,000 Dth a measured 5,025,000 Dth is a
        25,000.000 Dth variance, which is 0.5000 percent -- exactly the tolerance -- so the
        filing must go out; an implementation comparing with a strict less-than rejects a
        compliant report.

        PRD §2.11 rung 38: "**Report variance.** A report's `variance_pct` is no greater
        than 0.5000 percent, compared after rounding to 4 decimal places with the boundary
        inclusive — otherwise `ERR_REPORT_VARIANCE_EXCEEDED` (422)."

        Design: Difficulty/boundary_precision_check/report_variance_tolerance_boundary_is_inclusive_at_exactly_half_a_percent
        """
        field = self._five_million_field(api)
        on_the_boundary = create_report(
            api, field["id"], 5025000.000,
            period_start_date="2026-07-01", period_end_date="2026-07-31",
        )
        assert_volume(on_the_boundary["book_inventory_dth"], 5000000.000, "book_inventory_dth")
        assert_volume(on_the_boundary["variance_dth"], 25000.000, "variance_dth")
        assert_variance_pct(on_the_boundary["variance_pct"], 0.5000)
        assert on_the_boundary["open_finding_count"] == 0

        filed = assert_ok(_submit(api, on_the_boundary["id"]))
        assert filed["status"] == REPORT_SUBMITTED, (
            f"0.5000 is inside an inclusive tolerance, got {filed['status']}"
        )
        assert_field_derived_block(
            read_field(api, field["id"]), working_gas=5000000.000, inventory_pct=62.50,
            pressure=1675, tier=TIER_3,
        )

    def test_six_tenths_of_a_percent_is_refused(self, api):
        """A measured 5,030,000 Dth against the same book inventory is a 30,000.000 Dth
        variance at 0.6000 percent, which is outside the tolerance, so the submission is
        refused and the filing stays in DRAFT.

        PRD §3.9: "The reported variance must be within tolerance: `variance_pct` must be
        no greater than 0.5000 percent, compared on the 4-decimal rounded value with the
        boundary inclusive, and a wider variance is refused with
        `ERR_REPORT_VARIANCE_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/report_variance_tolerance_boundary_is_inclusive_at_exactly_half_a_percent
        """
        field = self._five_million_field(api)
        beyond_the_boundary = create_report(api, field["id"], 5030000.000)
        assert_volume(beyond_the_boundary["book_inventory_dth"], 5000000.000, "book_inventory_dth")
        assert_volume(beyond_the_boundary["variance_dth"], 30000.000, "variance_dth")
        assert_variance_pct(beyond_the_boundary["variance_pct"], 0.6000)
        assert beyond_the_boundary["open_finding_count"] == 0

        assert_error_envelope(_submit(api, beyond_the_boundary["id"]), ERR_REPORT_VARIANCE_EXCEEDED)
        refused = _read_report(api, field["id"], beyond_the_boundary["id"])
        assert refused["status"] == REPORT_DRAFT, (
            f"A refused submission leaves the report in DRAFT, got {refused['status']}"
        )
        assert refused["submitted_by_user_id"] is None
