"""Endpoint-driven workflows: the clock, transition finalization, and
conditional statement issuance (PRD 2.4, 3.9, 3.5).
"""

from test_helpers import constants as C
from test_helpers.api_errors import ERR_NO_ACCEPTED_REPORTS
from test_helpers.assertions import (
    assert_cents,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    accepted_report,
    active_contract,
    add_season,
    approved_project,
    create_contract,
    create_report,
    read_contract,
    reset_clock,
    set_clock,
    submit_report,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    OFFICER,
    OPS_MANAGER,
)


class TestLogicalClockDrivesSeasonTransitions:
    def test_crossing_the_open_date_flips_the_season_to_open(self, client):
        """PRD 2.4: "Before any clock-setting call, the logical clock reads
        exactly `2026-09-01T00:00:00Z` — a fixed startup default that never
        falls back to wall-clock time." and "seasons open when the clock
        reaches their opening instant and close when it reaches their closing
        instant".

        Design: Corner/endpoints/clock_set_endpoint_drives_system_transitions
        """
        contract = create_contract(client, contract_number="YELL-110",
                                   franchise_fee_rate=0.04)
        season = add_season(client, contract["id"])
        assert season["status"] == C.SEASON_PLANNED, (
            "the startup clock (2026-09-01) precedes the 2027-06-01 opening"
        )
        set_clock(client, "2027-06-01T00:00:01Z")
        reread = get_success_data(client.get_season(
            contract["id"], season["id"], headers=OPS_MANAGER
        ))
        assert reread["status"] == C.SEASON_OPEN


class TestTransitionAndAssetTransfer:
    def _transition_ready(self, client):
        """C1 ACTIVE with one APPROVED project; C2 DRAFT as the successor."""
        reset_clock(client)
        contract, _season, _lines = active_contract(
            client, contract_number="YELL-111"
        )
        contract_id = contract["id"]
        approved_project(
            client, contract_id,
            title="Water main", asset_ref="UTIL-9",
            authorized_cost_cents=800000, actual_cost_cents=780000,
            in_service_month_offset=3,
        )
        successor = create_contract(
            client, contract_number="YELL-111R",
            start_date="2037-01-01T00:00:00Z", franchise_fee_rate=0.04,
            employee_housing_capacity=120,
            lsi_annual_schedule_type=C.LSI_DECLINING_BALANCE,
        )
        return contract_id, successor["id"]

    def test_finalize_closes_the_contract_and_marks_the_project_expended(
        self, client
    ):
        """PRD 3.9: "Finalization completes the handoff, moving the contract
        from `TRANSITION_PENDING` to its terminal `CLOSED` state." and "Each
        `APPROVED` capital project is marked `EXPENDED`, its
        `accrued_lsi_cents` frozen at the transition offset, and an identical
        project — same `title`, `asset_ref`, and `authorized_cost_cents`,
        with `actual_cost_cents` reset to zero — is created in `PROPOSED`
        status on the successor contract."

        Design: Corner/endpoints/designate_successor_and_finalize_transfer_assets
        """
        contract_id, successor_id = self._transition_ready(client)
        client.initiate_transition(contract_id, headers=OFFICER)
        client.designate_successor(
            contract_id, {"successor_contract_id": successor_id},
            headers=OFFICER,
        )
        finalized = get_success_data(client.finalize_transition(
            contract_id, headers=OFFICER
        ))
        assert finalized["status"] == C.CONTRACT_CLOSED
        assert finalized["successor_contract_id"] == successor_id
        old_projects, _meta = validate_paginated(client.list_capital_projects(
            contract_id, headers=OFFICER
        ))
        assert len(old_projects) == 1
        assert old_projects[0]["status"] == C.PROJECT_EXPENDED

    def test_the_successor_receives_equivalent_projects_and_lines(self, client):
        """PRD 3.9: "Each service line on the outgoing contract is marked
        `TERMINATED`, and the same four service lines are created fresh in
        `AUTHORIZED` status on the successor."

        Design: Corner/endpoints/designate_successor_and_finalize_transfer_assets
        """
        contract_id, successor_id = self._transition_ready(client)
        client.initiate_transition(contract_id, headers=OFFICER)
        client.designate_successor(
            contract_id, {"successor_contract_id": successor_id},
            headers=OFFICER,
        )
        client.finalize_transition(contract_id, headers=OFFICER)
        new_projects, _meta = validate_paginated(client.list_capital_projects(
            successor_id, headers=OFFICER
        ))
        assert len(new_projects) == 1
        clone = new_projects[0]
        assert clone["title"] == "Water main"
        assert clone["asset_ref"] == "UTIL-9"
        assert_cents(clone["authorized_cost_cents"], 800000,
                     "clone authorized_cost_cents")
        assert_cents(clone["actual_cost_cents"], 0, "clone actual_cost_cents")
        assert clone["status"] == C.PROJECT_PROPOSED
        old_lines, _meta = validate_paginated(client.list_service_lines(
            contract_id, headers=OFFICER
        ))
        assert {l["status"] for l in old_lines} == {C.LINE_TERMINATED}
        assert len(old_lines) == 4
        new_lines, _meta = validate_paginated(client.list_service_lines(
            successor_id, headers=OFFICER
        ))
        assert len(new_lines) == 4
        assert {l["line_type"] for l in new_lines} == set(C.ALL_LINE_TYPES)
        assert {l["status"] for l in new_lines} == {C.LINE_AUTHORIZED}


class TestStatementIssuanceGate:
    def test_issuance_requires_an_accepted_report(self, client):
        """PRD 3.5: "Once at least one report for a period has been
        `ACCEPTED`, the `ConcessionerAccountant` issues the franchise fee
        statement for that `period_month`; with no accepted reports the
        issuance is rejected with `ERR_NO_ACCEPTED_REPORTS`."

        Design: Corner/endpoints/fee_statement_issue_requires_accepted_reports
        """
        reset_clock(client)
        contract, _season, lines = active_contract(client)
        contract_id = contract["id"]
        report = create_report(
            client, contract_id, lines[C.LINE_LODGING]["id"],
            gross_receipts_cents=20000,
        )
        submit_report(client, contract_id, report["id"])
        response = client.create_fee_statement(
            contract_id, {"period_month": "2027-07"}, headers=ACCOUNTANT
        )
        validate_error(response, ERR_NO_ACCEPTED_REPORTS)
        rows, meta = validate_paginated(client.list_fee_statements(
            contract_id, headers=ACCOUNTANT
        ))
        assert meta["total_count"] == 0
