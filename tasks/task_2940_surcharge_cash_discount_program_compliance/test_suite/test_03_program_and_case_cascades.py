"""How a program, its terminals and its complaint cases move each other: the
quarantine reasons that distinguish an operator action from a cascade, the
guarded restore fork, and the closures that let a program come back."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_terminal_census,
    create_jurisdiction,
    create_merchant,
    create_refund,
    cost_documentation_payload,
    file_complaint,
    investigation_action,
    list_total,
    program_status_action,
    provision_terminal,
    read_complaint_case,
    read_merchant,
    read_program,
    read_terminal,
    read_transaction,
    remediation_action,
    set_clock,
    setup_active_surcharge_program,
    setup_enforcing_surcharge_estate,
    setup_merchant_with_documentation,
    setup_refundable_sale,
    terminal_action,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, OFFICER_ONE_USER_ID, TS_AUG_31
from test_helpers.fixtures import ADMIN, AUDITOR, OFFICER_ONE, OFFICER_TWO
from test_helpers.test_users import make_merchant_operator_headers

CLOCK_AUG_05 = "2026-08-05T00:00:00Z"
TS_AUG_05 = "2026-08-05T00:00:00.000Z"


def test_an_officer_quarantine_is_recorded_as_an_operator_action(api):
    """PRD §3.8: "**`QUARANTINE`**, available to a `MerchantOperator` or a `ComplianceOfficer`, requires the terminal to be in `ENFORCING` and moves it to `QUARANTINED` with `quarantine_reason` set to `OPERATOR_ACTION`."
    PRD §3.8: "The same `ENFORCING → QUARANTINED` transition is also reached by three system cascades, which differ only in the reason they record: `PROGRAM_SUSPENDED` when the bound program leaves `ACTIVE` for `SUSPENDED`, `PROGRAM_DISABLED` when a jurisdictional prohibition disables the program, and `DISCLOSURE_EXPIRED` when a remediation order strips the program's attested disclosures."
    PRD §3.8: "It recomputes `enforcing_terminal_count` for the merchant and bumps the terminal's `version` by 1."

    Design: Corner/state_machines/compliance_officer_quarantine_records_operator_action_reason
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    terminal_id = ctx["terminal"]["id"]

    quarantined = validate_success(
        api_client.terminal_state_action(
            terminal_id,
            {"action": "QUARANTINE", "note": "suspected BIN table drift"},
            OFFICER_ONE,
        )
    )
    assert quarantined["state"] == "QUARANTINED"
    assert quarantined["quarantine_reason"] == "OPERATOR_ACTION"

    assert_terminal_census(read_merchant(ctx["merchant"]["id"]), 0)
    program = read_program(ctx["program"]["id"])
    assert program["status"] == "ACTIVE"
    assert program["disable_reason"] == "NONE"


def test_restoring_under_a_suspended_program_lands_in_configured(api):
    """PRD §3.8: "**Branch B — restore to configuration.** When the bound program's `status` is not `ACTIVE`, or its `disclosure_ready` is false, the terminal moves `QUARANTINED → CONFIGURED` instead."
    PRD §3.8: "Because the terminal does not reach `ENFORCING`, `enforcing_terminal_count` is unchanged by this branch."
    PRD §3.8: "Both branches require the operator to own the terminal, both reset `quarantine_reason` to `NONE`, and both bump the terminal's `version` by 1."

    Design: Corner/state_machines/quarantined_terminal_restores_to_configured_while_program_is_suspended
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    program_id = ctx["program"]["id"]
    merchant_id = ctx["merchant"]["id"]
    terminal_id = ctx["terminal"]["id"]
    program_status_action(program_id, "SUSPEND", reason="operator pauses the estate")

    before = read_terminal(terminal_id)
    assert before["state"] == "QUARANTINED"
    assert before["quarantine_reason"] == "PROGRAM_SUSPENDED"

    restored = terminal_action(terminal_id, merchant_id, "RESTORE")
    assert restored["state"] == "CONFIGURED"
    assert restored["quarantine_reason"] == "NONE"

    assert_terminal_census(read_merchant(merchant_id), 0)
    program = read_program(program_id)
    assert program["status"] == "SUSPENDED"
    assert program["disable_reason"] == "OPERATOR_SUSPENSION"


def test_revoking_an_effective_registration_suspends_the_program_and_its_terminal(api):
    """PRD §3.5: "When a `NetworkAuditor` revokes a registration that was `EFFECTIVE`, and the owning program's `status` is `ACTIVE`, the program moves `ACTIVE → SUSPENDED` with `disable_reason` set to `REGISTRATION_REVOKED`; every `Terminal` of that program in state `ENFORCING` moves to `QUARANTINED` with `quarantine_reason` set to `PROGRAM_SUSPENDED`; and each of those terminal transitions recomputes `enforcing_terminal_count` on the terminal's merchant."
    PRD §3.5: "`REVOKE` moves `EFFECTIVE → REVOKED`, stamps `revoked_at` from the logical clock, and carries a cross-entity consequence described below."

    Design: Corner/state_machines/revoked_registration_suspends_active_program_and_quarantines_its_terminals
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    assert ctx["registration"]["state"] == "EFFECTIVE"
    assert_terminal_census(read_merchant(ctx["merchant"]["id"]), 1)

    revoked = validate_success(
        api_client.decide_network_registration(
            ctx["registration"]["id"],
            {"decision": "REVOKE", "decision_note": "registration withdrawn by the network"},
            AUDITOR,
        )
    )
    assert revoked["state"] == "REVOKED"
    assert revoked["decided_by_user_id"] == "auditor-1"
    assert_instant_equals(revoked["revoked_at"], TS_AUG_31, "revoked_at")

    program = read_program(ctx["program"]["id"])
    assert program["status"] == "SUSPENDED"
    assert program["disable_reason"] == "REGISTRATION_REVOKED"

    terminal = read_terminal(ctx["terminal"]["id"])
    assert terminal["state"] == "QUARANTINED"
    assert terminal["quarantine_reason"] == "PROGRAM_SUSPENDED"
    assert_terminal_census(read_merchant(ctx["merchant"]["id"]), 0)


def test_a_dismissed_case_never_opens_its_remediation_track(api):
    """PRD §3.10: "A case whose investigation ends in `DISMISSED` keeps `remediation_state` at `NONE` forever, and no remediation action ever becomes available on it."
    PRD §3.10: "**`SUBMIT_PLAN`** is available to a `ComplianceOfficer` only, requires `remediation_state` of `PLAN_REQUIRED`, and moves it to `PLAN_SUBMITTED`; `plan_summary` must be present in the request, else the request is rejected with `ERR_INVALID_REQUEST`, and the supplied text is stored on the case."
    PRD §3.10: "**`DISMISS`** is available to the same two roles under the same channel rule, requires `investigation_state` of `OPEN` or `UNDER_REVIEW`, and moves it to `DISMISSED`; `remediation_state` stays `NONE`, both exposure scores are recomputed (a dismissed case contributes zero to both), and the case's `version` is bumped by 1."

    Design: Corner/state_machines/dismissed_complaint_case_rejects_every_remediation_action
    """
    ctx = setup_active_surcharge_program()
    case = file_complaint(ctx["program"]["id"], "CARDHOLDER")
    dismissed = investigation_action(case["id"], "DISMISS", "CARDHOLDER")
    assert dismissed["investigation_state"] == "DISMISSED"

    response = api_client.complaint_remediation_action(
        case["id"], {"action": "SUBMIT_PLAN", "plan_summary": "retrain cashiers"}, OFFICER_ONE
    )
    validate_error(response, ApiErrorId.ERR_INVALID_COMPLAINT_STATE)

    reread = read_complaint_case(case["id"])
    assert reread["investigation_state"] == "DISMISSED"
    assert reread["remediation_state"] == "NONE"
    assert reread["plan_summary"] is None

    program = read_program(ctx["program"]["id"])
    assert program["status"] == "ACTIVE"
    assert program["network_exposure_score"] == pytest.approx(0.00, abs=0.005)
    assert program["ag_exposure_score"] == pytest.approx(0.00, abs=0.005)


def test_closing_the_last_substantiated_case_returns_the_program_to_active(api):
    """PRD §3.10: "When a case reaches `remediation_state` of `CLOSED`, and the owning program's `status` is `REMEDIATION`, and no other case of that program has `investigation_state` of `SUBSTANTIATED` with a `remediation_state` other than `CLOSED`, and readiness now yields true again because a fresh set of disclosure artifacts has been attested, then the program moves `REMEDIATION → ACTIVE` with `disable_reason` reset to `NONE`, its `disclosure_ready` is recomputed, and its `version` is bumped by 1."
    PRD §3.10: "Closing moves `remediation_state` to `CLOSED` and recomputes the case's `refund_total_cents`."
    PRD §3.6: "An empty required set — the case of a jurisdiction with every disclosure flag false — yields true vacuously."

    Design: Corner/state_machines/case_closure_bubbles_program_from_remediation_back_to_active
    """
    ctx = setup_active_surcharge_program()
    program_id = ctx["program"]["id"]
    case = file_complaint(program_id, "NETWORK")
    investigation_action(case["id"], "SUBSTANTIATE", "NETWORK")
    remediation_action(case["id"], "SUBMIT_PLAN", "NETWORK")
    accepted = remediation_action(case["id"], "ACCEPT_PLAN", "NETWORK")
    assert accepted["remediation_state"] == "PLAN_ACCEPTED"

    before = read_program(program_id)
    assert before["status"] == "REMEDIATION"
    assert before["disable_reason"] == "REMEDIATION_ORDER"

    closed = validate_success(
        api_client.complaint_remediation_action(case["id"], {"action": "CLOSE"}, AUDITOR)
    )
    assert closed["remediation_state"] == "CLOSED"
    assert closed["investigation_state"] == "SUBSTANTIATED"
    assert closed["refund_total_cents"] == 0

    after = read_program(program_id)
    assert after["status"] == "ACTIVE"
    assert after["disable_reason"] == "NONE"
    assert after["network_exposure_score"] == pytest.approx(30.00, abs=0.005)
    assert after["ag_exposure_score"] == pytest.approx(10.00, abs=0.005)


def test_a_newer_document_supersedes_the_old_one_and_repoints_the_merchant(api):
    """PRD §3.2: "The merchant's existing document in state `ACTIVE`, if there is one, moves to `SUPERSEDED` with `superseded_at` stamped from the logical clock and its own `version` bumped; the merchant's `active_cost_documentation_id` is repointed at the new document; and the merchant's `version` is bumped by 1."
    PRD §3.2: "The circle is broken by freezing both derived numbers onto the `CostDocumentation` row at filing time: `average_ticket_cents` and `documented_cost_pct` are never recomputed afterwards."
    PRD §3.2: "A merchant therefore has at most one `ACTIVE` document at any instant, and the sequence of superseded documents is the audit trail."

    Design: Corner/state_machines/newer_cost_documentation_supersedes_predecessor_and_repoints_merchant
    """
    ctx = setup_merchant_with_documentation(clock=CLOCK_AUG_05)
    merchant_id = ctx["merchant"]["id"]
    doc_a_id = ctx["cost_documentation"]["id"]

    doc_b = validate_success(
        api_client.create_cost_documentation(
            merchant_id,
            cost_documentation_payload(
                read_merchant(merchant_id)["version"],
                "docB",
                evidence_uri="s3://acq/az/2026-08.pdf",
            ),
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert doc_b["state"] == "ACTIVE"
    assert doc_b["average_ticket_cents"] == 5000
    assert doc_b["documented_cost_pct"] == pytest.approx(3.05, abs=0.00001)
    assert_instant_equals(doc_b["effective_from"], TS_AUG_05, "effective_from")
    assert doc_b["superseded_at"] is None

    doc_a = validate_success(api_client.get_cost_documentation(doc_a_id, ADMIN))
    assert doc_a["state"] == "SUPERSEDED"
    assert_instant_equals(doc_a["superseded_at"], TS_AUG_05, "superseded_at")
    assert doc_a["documented_cost_pct"] == pytest.approx(2.19, abs=0.00001)
    assert doc_a["version"] == 2

    assert read_merchant(merchant_id)["active_cost_documentation_id"] == doc_b["id"]
    assert (
        list_total(
            api_client.list_cost_documentations(
                ADMIN, params={"merchant_id": merchant_id, "state": "ACTIVE"}
            )
        )
        == 1
    )


def test_voiding_a_pending_refund_moves_no_money(api):
    """PRD §3.11: "Voiding a refund in state `PENDING` also moves it to `VOIDED` and stamps `voided_at`, but no ledger field moves at all, because the refund was never issued; only the refund's own `version` is bumped."
    PRD §3.11: "Creation moves no ledger field whatsoever: a pending refund is an intention, not a payment."
    PRD §3.11: "A case's `refund_total_cents` is always the sum of `refund_amount_cents` over that case's refunds in state `ISSUED` — pending and voided refunds are excluded — and a sale's `refunded_surcharge_cents` is likewise the sum over the `ISSUED` refunds referencing it."

    Design: Corner/state_machines/pending_refund_void_leaves_merchant_ledger_untouched
    """
    ctx = setup_refundable_sale(serial_prefix="TRM-AZ-")
    case_id = ctx["complaint_case"]["id"]
    transaction_id = ctx["transaction"]["id"]
    refund = create_refund(case_id, transaction_id, 219, OFFICER_ONE_USER_ID)
    assert refund["state"] == "PENDING"

    voided = validate_success(
        api_client.void_refund(
            refund["id"], {"reason": "cardholder withdrew the dispute"}, OFFICER_TWO
        )
    )
    assert voided["state"] == "VOIDED"
    assert_instant_equals(voided["voided_at"], TS_AUG_31, "voided_at")
    assert voided["issued_at"] is None
    assert voided["issued_by_user_id"] is None
    assert voided["version"] == 2

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 219
    assert merchant["net_surcharge_collected_cents"] == 219
    assert read_transaction(transaction_id)["refunded_surcharge_cents"] == 0

    case = read_complaint_case(case_id)
    assert case["refund_total_cents"] == 0
    assert case["remediation_state"] == "PLAN_ACCEPTED"


def test_a_provisioned_terminal_declares_no_state_action_at_all(api):
    """PRD §3.8: "Any of the three actions requested from a state that does not declare it — enforcing a terminal that is not `CONFIGURED`, quarantining one that is not `ENFORCING`, restoring one that is not `QUARANTINED`, or any action at all on a `DISABLED` terminal — is rejected with `ERR_INVALID_TERMINAL_STATE`."
    PRD §3.8: "A provisioned terminal begins in state `PROVISIONED` with `program_id` null, `debit_exclusion_enabled` false, `bin_table_version` null, `quarantine_reason` of `NONE`, and `last_configured_at` null."

    Design: Corner/state_machines/provisioned_terminal_rejects_every_state_action
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    merchant = create_merchant(jurisdiction["id"])
    terminal = provision_terminal(merchant["id"], "TRM-AZ-0001")
    operator = make_merchant_operator_headers(merchant["id"])

    for payload in (
        {"action": "ENFORCE"},
        {"action": "QUARANTINE", "note": "operator caution"},
        {"action": "RESTORE"},
    ):
        response = api_client.terminal_state_action(terminal["id"], payload, operator)
        validate_error(response, ApiErrorId.ERR_INVALID_TERMINAL_STATE)

    reread = read_terminal(terminal["id"])
    assert reread["state"] == "PROVISIONED"
    assert reread["program_id"] is None
    assert reread["quarantine_reason"] == "NONE"
    assert reread["version"] == 1
    assert_terminal_census(read_merchant(merchant["id"]), 0)
