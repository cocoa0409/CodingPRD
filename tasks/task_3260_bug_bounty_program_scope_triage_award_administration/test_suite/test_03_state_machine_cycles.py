"""Difficulty tests: non-linear state machines — revert cycles out of penalty states."""
import pytest

from test_helpers import ApiErrorId, get_success_data, validate_error, validate_success
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    approve_award,
    create_award,
    create_validated_report,
    get_award,
    get_program,
    get_researcher,
    get_report,
    register_researcher,
    setup_active_program,
    submit_report,
    submit_tax_document,
)


def _setup_anchor_and_duplicate_reports(vulnerability_class="XSS"):
    """ACTIVE program; researcher; repA VALIDATED, repB TRIAGED (same class)."""
    program, asset = setup_active_program()
    researcher = register_researcher()
    rep_a = create_validated_report(
        program, asset, researcher, impact=5, exploitability=5, affected_scope=5,
        vulnerability_class=vulnerability_class)
    rep_b = submit_report(program, asset, researcher, title="dupe",
                          vulnerability_class=vulnerability_class)
    get_success_data(api_triage(rep_b["id"]))
    return program, asset, researcher, rep_a, rep_b


def api_triage(report_id, payload=None):
    from test_helpers import api_client
    return api_client.triage_report(report_id, payload or {"action": "TRIAGE"}, TRIAGER)


def test_report_duplicate_reopen_cycle_state_restored(api):
    """PRD §3.6: "Reopening is the compensating move: from `DUPLICATE` or
    `NOT_APPLICABLE` a triager returns the report to `TRIAGED`. Reopening clears
    `duplicate_of_id` to null, and the reputation ledger compensates exactly — a
    report reopened out of `DUPLICATE` restores +10, one reopened out of
    `NOT_APPLICABLE` restores +15."

    Design: Difficulty/non_linear_state_machine/report_duplicate_reopen_cycle
    """
    program, asset, researcher, rep_a, rep_b = _setup_anchor_and_duplicate_reports()
    duped = get_success_data(api.triage_report(
        rep_b["id"], {"action": "MARK_DUPLICATE", "duplicate_of_id": rep_a["id"]}, TRIAGER))
    assert duped["status"] == "DUPLICATE"
    assert duped["duplicate_of_id"] == rep_a["id"]
    reopened = get_success_data(api.triage_report(rep_b["id"], {"action": "REOPEN"}, TRIAGER))
    assert reopened["status"] == "TRIAGED"
    assert reopened["duplicate_of_id"] is None


def test_report_duplicate_reopen_cycle_reputation_compensated(api):
    """PRD §3.6: "Duplicate marking moves a report from `NEW`, `TRIAGED`,
    `NEEDS_INFO`, or even `VALIDATED` into `DUPLICATE`. ... A successful marking
    stores the anchor on `duplicate_of_id` and debits the researcher −10
    reputation, applied to both lifetime and rolling figures."
    PRD §3.6: "the reputation ledger compensates exactly — a report reopened out of
    `DUPLICATE` restores +10, one reopened out of `NOT_APPLICABLE` restores +15."

    Design: Difficulty/non_linear_state_machine/report_duplicate_reopen_cycle
    """
    program, asset, researcher, rep_a, rep_b = _setup_anchor_and_duplicate_reports()
    get_success_data(api.triage_report(
        rep_b["id"], {"action": "MARK_DUPLICATE", "duplicate_of_id": rep_a["id"]}, TRIAGER))
    after_mark = get_researcher(researcher["id"])
    assert after_mark["reputation_lifetime"] == 90
    get_success_data(api.triage_report(rep_b["id"], {"action": "REOPEN"}, TRIAGER))
    after_reopen = get_researcher(researcher["id"])
    assert after_reopen["reputation_lifetime"] == 100


def test_award_blocked_to_paid_cycle_after_tax_document_submission(api):
    """PRD §3.9: "A `BLOCKED` award may be retried through the same payment path.
    Retry is possible only when `block_reason` is `TAX_DOCUMENT` and the
    researcher's `tax_document_status` has advanced to `SUBMITTED` or `VERIFIED`
    by retry time; a successful retry clears `block_reason` and applies the same
    ledger effects as a first-time payment."
    PRD §3.9: "paying an award of 60000 cents or more to a researcher whose
    `tax_document_status` is `MISSING` returns `ERR_TAX_DOC_REQUIRED` and moves the
    award to `BLOCKED` with `block_reason` set to `TAX_DOCUMENT`, again retaining
    the reservation."

    Design: Difficulty/non_linear_state_machine/award_approved_blocked_paid_cycle
    """
    program, asset = setup_active_program()
    researcher = register_researcher()  # tax MISSING
    report = create_validated_report(
        program, asset, researcher, impact=6, exploitability=5, affected_scope=4,
        vulnerability_class="SSRF")
    # base 5.3 * 1.2 = 6.36 -> 6.4 MEDIUM; raw = 150000 * 2.0 = 300000;
    # first-report NOVICE bonus 0.10 -> 30000; amount 330000
    assert report["severity_final"] == "MEDIUM"
    award = create_award(report["id"], "BOUNTY")
    approve_award(award["id"])
    first_pay = api.pay_award(award["id"], PLATFORM_ADMIN)
    validate_error(first_pay, ApiErrorId.ERR_TAX_DOC_REQUIRED)
    blocked = get_award(award["id"])
    assert blocked["status"] == "BLOCKED"
    assert blocked["block_reason"] == "TAX_DOCUMENT"
    # Cure the tax block and retry
    submit_tax_document(researcher, document_type="W9")
    paid = get_success_data(api.pay_award(award["id"], PLATFORM_ADMIN))
    assert paid["status"] == "PAID"
    assert paid["block_reason"] is None


def test_award_blocked_to_paid_cycle_ledger_effects(api):
    """PRD §3.9: "The program ledger then settles all at once: the amount leaves
    `bounty_reserved_cents`, the gross amount joins `bounty_paid_cents`, the
    per-award withholding joins `total_withheld_cents`, and `paid_at` is stamped."
    PRD §3.9: "The raw figure is the severity base for the report's
    `severity_final` — 1000000 cents for `CRITICAL`, 500000 for `HIGH`, 150000 for
    `MEDIUM`, 30000 for `LOW`, and 0 for `NONE` — multiplied by the asset
    criticality multiplier: 2.0 for `CRITICAL`, 1.5 for `HIGH`, 1.0 for `MEDIUM`,
    0.5 for `LOW`."

    Design: Difficulty/non_linear_state_machine/award_approved_blocked_paid_cycle
    """
    program, asset = setup_active_program()
    researcher = register_researcher()  # tax MISSING
    report = create_validated_report(
        program, asset, researcher, impact=6, exploitability=5, affected_scope=4,
        vulnerability_class="SSRF")
    award = create_award(report["id"], "BOUNTY")
    # MEDIUM severity base 150000 * CRITICAL asset 2.0 = 300000 raw;
    # +10% first report = 30000 -> amount 330000
    assert award["amount_cents"] == 330_000
    approve_award(award["id"])
    first_pay = api.pay_award(award["id"], PLATFORM_ADMIN)
    validate_error(first_pay, ApiErrorId.ERR_TAX_DOC_REQUIRED)
    program_blocked = get_program(program["id"])
    assert program_blocked["bounty_reserved_cents"] == 330_000  # reservation retained
    submit_tax_document(researcher, document_type="W9")
    paid = get_success_data(api.pay_award(award["id"], PLATFORM_ADMIN))
    # SUBMITTED -> 24% backup withholding: round(330000 * 0.24) = 79200
    assert paid["withheld_cents"] == 79_200
    assert paid["net_paid_cents"] == 250_800
    program_after = get_program(program["id"])
    assert program_after["bounty_reserved_cents"] == 0
    assert program_after["bounty_paid_cents"] == 330_000
    assert program_after["total_withheld_cents"] == 79_200
