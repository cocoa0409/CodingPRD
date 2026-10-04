"""The corrective-plan deadline (PRD 3.8) and input-set filtering on
statement issuance (PRD 3.5).
"""

from test_helpers import constants as C
from test_helpers.api_errors import (
    ERR_CORRECTIVE_PLAN_LATE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    get_success_data,
    validate_error,
)
from test_helpers.fixtures import (
    accept_report,
    active_contract,
    create_report,
    incident_in_corrective_plan_required,
    issue_statement,
    report_incident,
    reset_clock,
    set_clock,
    submit_report,
)
from test_helpers.test_users import INSPECTOR, OPS_MANAGER


class TestCorrectivePlanDeadline:
    def _two_incidents(self, client):
        """Two incidents at CORRECTIVE_PLAN_REQUIRED, both occurred 7/1."""
        reset_clock(client)
        contract, _season, _lines = active_contract(
            client, franchise_fee_rate=0.04
        )
        contract_id = contract["id"]
        first = incident_in_corrective_plan_required(
            client, contract_id,
            protocol=C.PROTOCOL_WILDLIFE, severity=C.SEVERITY_CRITICAL,
            occurred_at="2027-07-01T00:00:00Z",
            description="Food storage violation near bear habitat",
        )
        second = incident_in_corrective_plan_required(
            client, contract_id,
            protocol=C.PROTOCOL_WASTE, severity=C.SEVERITY_MAJOR,
            occurred_at="2027-07-01T00:00:00Z",
            description="Recycling contamination",
        )
        return contract_id, first, second

    def test_the_deadline_is_fourteen_days_after_the_incident(self, client):
        """PRD 3.8: "At report time the server computes the
        `corrective_plan_deadline` as exactly 14 days after `occurred_at`".

        Design: Corner/errors/corrective_plan_after_deadline_rejected
        """
        reset_clock(client)
        contract, _season, _lines = active_contract(client)
        incident = report_incident(
            client, contract["id"],
            occurred_at="2027-07-01T00:00:00Z",
        )
        assert_instant(
            incident["corrective_plan_deadline"], "2027-07-15T00:00:00Z",
            "corrective_plan_deadline",
        )

    def test_a_plan_submitted_before_the_deadline_returns_to_review(
        self, client
    ):
        """PRD 3.8: "the `ConcessionerOpsManager` submits a plan carrying
        `plan_text`, which returns the incident to `UNDER_REVIEW` — the
        review loop is cyclic and a further plan requirement may follow."

        Design: Corner/errors/corrective_plan_after_deadline_rejected
        """
        contract_id, _first, second = self._two_incidents(client)
        set_clock(client, "2027-07-14T00:00:00Z")
        returned = get_success_data(client.submit_corrective_plan(
            contract_id, second["id"],
            {"plan_text": "Double-bag recycling; daily pickup."},
            headers=OPS_MANAGER,
        ))
        assert returned["status"] == C.INCIDENT_UNDER_REVIEW

    def test_a_plan_submitted_after_the_deadline_is_late(self, client):
        """PRD 3.8: "The deadline is hard: if the logical clock has already
        passed the `corrective_plan_deadline` when the plan is submitted, the
        submission is rejected with `ERR_CORRECTIVE_PLAN_LATE`."

        Design: Corner/errors/corrective_plan_after_deadline_rejected
        """
        contract_id, first, second = self._two_incidents(client)
        # Resolve the second incident before its deadline, then pass the
        # deadline and try the first.
        set_clock(client, "2027-07-14T00:00:00Z")
        client.submit_corrective_plan(
            contract_id, second["id"], {"plan_text": "on time"},
            headers=OPS_MANAGER,
        )
        set_clock(client, "2027-07-16T00:00:00Z")
        response = client.submit_corrective_plan(
            contract_id, first["id"],
            {"plan_text": "Bear-proof lockers installed."},
            headers=OPS_MANAGER,
        )
        validate_error(response, ERR_CORRECTIVE_PLAN_LATE)
        reread = get_success_data(client.get_incident_flat(
            first["id"], headers=INSPECTOR
        ))
        assert reread["status"] == C.INCIDENT_CORRECTIVE_PLAN_REQUIRED


class TestStatementInputSetFiltering:
    def test_only_accepted_reports_feed_the_statement(self, client):
        """PRD 3.5: "The statement's `lines` array carries one row per
        accepted report in the period" and "Once at least one report for a
        period has been `ACCEPTED`, the `ConcessionerAccountant` issues the
        franchise fee statement for that `period_month`".

        Design: Corner/calculations/franchise_fee_uses_only_accepted_reports_in_input_set
        """
        reset_clock(client)
        contract, _season, lines = active_contract(
            client, contract_number="YELL-114", franchise_fee_rate=0.0385
        )
        contract_id = contract["id"]
        lodging = create_report(
            client, contract_id, lines[C.LINE_LODGING]["id"],
            gross_receipts_cents=20000,
        )
        submit_report(client, contract_id, lodging["id"])
        accept_report(client, contract_id, lodging["id"])
        retail = create_report(
            client, contract_id, lines[C.LINE_RETAIL]["id"],
            gross_receipts_cents=90000,
        )
        submit_report(client, contract_id, retail["id"])
        statement = issue_statement(client, contract_id, "2027-07")
        assert len(statement["lines"]) == 1, (
            "the SUBMITTED retail report contributes no line"
        )
        assert statement["lines"][0]["service_line_id"] == \
            lines[C.LINE_LODGING]["id"]
        assert_cents(statement["total_fee_cents"], 770,
                     "total_fee_cents (20000 * 0.0385)")
