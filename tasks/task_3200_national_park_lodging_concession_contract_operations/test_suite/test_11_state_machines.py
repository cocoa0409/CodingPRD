"""State-machine corners: invalid transitions, idempotency, lockdown,
bubble-up version effects, supersession, and clock-driven sweeps.
"""

from test_helpers import constants as C
from test_helpers.api_errors import ERR_INVALID_STATE
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    get_success_data,
    validate_error,
)
from test_helpers.fixtures import (
    accept_report,
    accepted_report,
    bookable_inventory,
    active_contract,
    add_room_class,
    add_study,
    approve_filing,
    hire_employee,
    housing_scenario,
    issue_statement,
    read_contract,
    reset_clock,
    set_clock,
    submit_filing,
    vouchers_for_hire,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    ACCOUNTANT,
    HR_MANAGER,
    INSPECTOR,
    OPS_MANAGER,
    RATE_ANALYST,
)


class TestContractActivation:
    def test_second_activation_is_an_invalid_state(self, client):
        """PRD 3.1: "a `ConcessionerOpsManager` activates the contract,
        moving it from `DRAFT` to `ACTIVE`." — the transition table lists no
        ACTIVE -> ACTIVE edge, and PRD 2.10 assigns target-entity state
        violations to `ERR_INVALID_STATE`.

        Design: Corner/state_machines/contract_activate_from_active_returns_invalid_state
        """
        contract, _season, _lines = active_contract(client)
        version_after_activation = contract["version"]
        response = client.activate_contract(contract["id"], headers=OPS_MANAGER)
        validate_error(response, ERR_INVALID_STATE)
        reread = read_contract(client, contract["id"])
        assert reread["status"] == C.CONTRACT_ACTIVE
        assert reread["version"] == version_after_activation


class TestStatementPayment:
    def _paid_statement(self, client):
        reset_clock(client)
        contract, _season, lines = active_contract(
            client, contract_number="YELL-106", franchise_fee_rate=0.04
        )
        contract_id = contract["id"]
        accepted_report(
            client, contract_id, lines[C.LINE_LODGING]["id"],
            gross_receipts_cents=20000,
        )
        statement = issue_statement(client, contract_id, "2027-07")
        paid = get_success_data(client.pay_fee_statement(
            contract_id, statement["id"], headers=ACCOUNTANT
        ))
        assert paid["status"] == C.STATEMENT_PAID
        return contract_id, paid

    def test_paying_a_paid_statement_is_an_invalid_state(self, client):
        """PRD 3.5: "Payment by the `ConcessionerAccountant` moves it to
        `PAID`, records the payment, and renders the statement immutable
        thereafter."

        Design: Corner/state_machines/statement_pay_twice_is_idempotency_rejected
        """
        contract_id, paid = self._paid_statement(client)
        response = client.pay_fee_statement(
            contract_id, paid["id"], headers=ACCOUNTANT
        )
        validate_error(response, ERR_INVALID_STATE)

    def test_the_statement_fee_is_computed_per_line(self, client):
        """PRD 3.5: "each line's fee is that line's gross receipts multiplied
        by the contract's `franchise_fee_rate`, rounded half-up to whole
        cents, and the statement's `total_fee_cents` is the sum of those
        per-line fees."

        Design: Corner/state_machines/statement_pay_twice_is_idempotency_rejected
        """
        _contract_id, paid = self._paid_statement(client)
        assert_cents(paid["total_fee_cents"], 800, "total_fee_cents (20000 * 0.04)")




class TestIncidentTerminalLockdown:
    def _closed_incident(self, client):
        reset_clock(client)
        contract, _season, _lines = active_contract(
            client, contract_number="YELL-107", franchise_fee_rate=0.04
        )
        contract_id = contract["id"]
        from test_helpers.fixtures import report_incident
        incident = report_incident(
            client, contract_id,
            protocol=C.PROTOCOL_WATER, severity=C.SEVERITY_MINOR,
            description="Greywater discharge report",
        )
        client.start_review_incident(contract_id, incident["id"], headers=INSPECTOR)
        closed = get_success_data(client.close_incident(
            contract_id, incident["id"], headers=INSPECTOR
        ))
        assert closed["status"] == C.INCIDENT_CLOSED
        return contract_id, incident

    def test_start_review_from_closed_is_rejected(self, client):
        """PRD 3.8: "An incident under review is closed by the inspector,
        moving it to `CLOSED`, the terminal state."

        Design: Corner/state_machines/terminal_state_lockdown_on_closed_incident
        """
        contract_id, incident = self._closed_incident(client)
        response = client.start_review_incident(
            contract_id, incident["id"], headers=INSPECTOR
        )
        validate_error(response, ERR_INVALID_STATE)

    def test_require_plan_from_closed_is_rejected(self, client):
        """PRD 3.8: "An incident under review is closed by the inspector,
        moving it to `CLOSED`, the terminal state."

        Design: Corner/state_machines/terminal_state_lockdown_on_closed_incident
        """
        contract_id, incident = self._closed_incident(client)
        response = client.require_corrective_plan(
            contract_id, incident["id"], headers=INSPECTOR
        )
        validate_error(response, ERR_INVALID_STATE)


class TestFilingApprovalSideEffects:
    def _under_review(self, client):
        scenario = bookable_inventory(client, clock=None)
        filing = submit_filing(
            client, scenario["contract"]["id"], scenario["season"]["id"],
            scenario["room_class"]["id"], scenario["study"]["id"],
        )
        client.start_review_filing(
            scenario["contract"]["id"], filing["id"], headers=RATE_ANALYST
        )
        return scenario, filing

    def test_approval_bubbles_the_contract_version_and_freezes_fields(
        self, client
    ):
        """PRD 3.2: "Approval freezes the filing's economics. The filing's
        `effective_date` is set to the season's `open_date` ... and the
        contract's `version` is bumped by one."

        Design: Corner/state_machines/approve_filing_bubbles_up_contract_version
        """
        scenario, filing = self._under_review(client)
        contract_id = scenario["contract"]["id"]
        version_before = read_contract(client, contract_id)["version"]
        approved = get_success_data(client.approve_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        ))
        assert approved["status"] == C.FILING_APPROVED
        assert_instant(approved["effective_date"], "2027-06-01T00:00:00Z",
                       "effective_date")
        version_after = read_contract(client, contract_id)["version"]
        assert version_after == version_before + 1

    def test_a_second_approval_supersedes_the_first(self, client):
        """PRD 3.2: "Any previously `APPROVED` filing for the same season and
        room class is moved to `SUPERSEDED` — a supersession the system
        performs automatically whenever a subsequent filing for the same slot
        reaches `APPROVED`."

        Design: Corner/state_machines/supersede_side_effect_on_second_approval
        """
        scenario, _first_under_review = self._under_review(client)
        contract_id = scenario["contract"]["id"]
        first = get_success_data(client.approve_filing(
            contract_id, _first_under_review["id"], headers=RATE_ANALYST
        ))
        assert first["status"] == C.FILING_APPROVED
        second = submit_filing(
            client, contract_id, scenario["season"]["id"],
            scenario["room_class"]["id"], scenario["study"]["id"],
            submitted_rates=f.band_rates_payload(18000, 22000, 25000),
        )
        approve_filing(client, contract_id, second["id"])
        reread = get_success_data(client.get_filing(
            contract_id, first["id"], headers=RATE_ANALYST
        ))
        assert reread["status"] == C.FILING_SUPERSEDED


class TestHireNoShowSweep:
    def test_grace_expiry_marks_no_show_and_voids_the_voucher(self, client):
        """PRD 3.7: "If the logical clock passes the `arrival_date` plus the
        24-hour grace with no arrival recorded, the hire becomes `NO_SHOW`:
        its housing bed is released and its linked booked voucher is `VOID`."

        Design: Corner/state_machines/hire_no_show_auto_transition_on_grace_expiry
        """
        scenario = housing_scenario(client, bed_count=2)
        contract_id = scenario["contract"]["id"]
        hire = hire_employee(
            client, contract_id,
            scenario["season"]["id"],
            scenario["lines"][C.LINE_LODGING]["id"],
            scenario["unit"]["id"],
            needs_transport=True, transport_origin="Salt Lake City",
        )
        # arrival 2027-06-01 + 24h grace -> sweep at 2027-06-02T00:00:01Z.
        set_clock(client, "2027-06-02T00:00:01Z")
        reread = get_success_data(client.get_hire_flat(
            hire["id"], headers=HR_MANAGER
        ))
        assert reread["status"] == C.HIRE_NO_SHOW
        vouchers = vouchers_for_hire(client, contract_id, hire["id"])
        assert len(vouchers) == 1
        assert vouchers[0]["status"] == C.VOUCHER_VOID

    def test_the_freed_bed_admits_a_new_hire_after_the_sweep(self, client):
        """PRD 3.7: "If the logical clock passes the `arrival_date` plus the
        24-hour grace with no arrival recorded, the hire becomes `NO_SHOW`:
        its housing bed is released and its linked booked voucher is `VOID`."

        Design: Corner/state_machines/hire_no_show_auto_transition_on_grace_expiry
        """
        scenario = housing_scenario(client, bed_count=1)
        contract_id = scenario["contract"]["id"]
        hire = hire_employee(
            client, contract_id,
            scenario["season"]["id"],
            scenario["lines"][C.LINE_LODGING]["id"],
            scenario["unit"]["id"],
            needs_transport=True, transport_origin="Salt Lake City",
        )
        set_clock(client, "2027-06-02T00:00:01Z")
        replacement = hire_employee(
            client, contract_id,
            scenario["season"]["id"],
            scenario["lines"][C.LINE_LODGING]["id"],
            scenario["unit"]["id"],
            arrival_date="2027-06-05T00:00:00Z",
        )
        assert replacement["status"] == C.HIRE_HIRED
