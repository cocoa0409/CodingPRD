"""Corner tests (calculations): severity band boundaries, tax thresholds, pool
exhaustion."""
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
    register_researcher,
    setup_active_program,
    submit_report,
)


def test_severity_band_boundary_exactly_7_is_high(api):
    """PRD §3.7: "The final severity `severity_final` is banded from the
    environmental score alone: `CRITICAL` at 9.0 or above, `HIGH` at 7.0 or
    above, `MEDIUM` at 4.0 or above, `LOW` at 0.1 or above, and `NONE` only when
    the adjusted score is exactly 0.0 — every band threshold inclusive."

    Design: Corner/calculations/severity_band_boundary_exactly_7_is_high
    """
    program, asset = setup_active_program(criticality="MEDIUM", exposure_modifier=1.0)
    researcher = register_researcher()
    report = submit_report(program, asset, researcher, vulnerability_class="AUTHZ")
    get_success_data(api.triage_report(report["id"], {"action": "TRIAGE"}, TRIAGER))
    validated = get_success_data(api.validate_report(
        report["id"],
        {"impact": 8, "exploitability": 6, "affected_scope": 6},
        TRIAGER,
    ))
    # base = 0.5*8 + 0.3*6 + 0.2*6 = 7.0; adjusted = 7.0 * 1.0 * 1.0 = 7.0
    assert validated["severity_score_base"] == pytest.approx(7.0, abs=1e-9)
    assert validated["severity_score_adjusted"] == pytest.approx(7.0, abs=1e-9)
    assert validated["severity_final"] == "HIGH"


def test_tax_threshold_59999_missing_pays_with_backup_withholding(api):
    """PRD §3.9: "paying an award of 60000 cents or more to a researcher whose
    `tax_document_status` is `MISSING` returns `ERR_TAX_DOC_REQUIRED`"
    PRD §3.9: "24 percent whenever the status is `SUBMITTED`, or `MISSING` with an
    amount below 60000 cents. The award's `withheld_cents` is the amount times the
    rate rounded half-up, and `net_paid_cents` is the amount minus the
    withholding."

    Design: Corner/calculations/tax_threshold_59999_missing_pays_with_backup_withholding
    """
    program, asset = setup_active_program(criticality="MEDIUM")
    researcher = register_researcher()  # tax MISSING
    report = create_validated_report(
        program, asset, researcher, impact=2, exploitability=2, affected_scope=2,
        vulnerability_class="OTHER")
    award = create_award(report["id"], "BONUS", amount_cents=59_999)
    approve_award(award["id"])
    paid = get_success_data(api.pay_award(award["id"], PLATFORM_ADMIN))
    assert paid["status"] == "PAID"
    assert paid["withheld_cents"] == 14_400  # round_half_up(59999 * 0.24)
    assert paid["net_paid_cents"] == 45_599


def test_pool_exhaustion_at_approve_time(api):
    """PRD §3.9: "Approval moves `PROPOSED` to `APPROVED` provided the program's
    reserved funds plus the award amount do not exceed the pool net of what has
    already been paid; breaching that ceiling is rejected with
    `ERR_POOL_EXHAUSTED`."

    Design: Corner/calculations/pool_exhaustion_at_approve_time
    """
    program, asset = setup_active_program(
        criticality="MEDIUM", bounty_pool_cents=100_000)
    researcher = register_researcher()
    rep1 = create_validated_report(
        program, asset, researcher, impact=2, exploitability=2, affected_scope=2,
        vulnerability_class="XSS")
    rep2 = create_validated_report(
        program, asset, researcher, impact=2, exploitability=2, affected_scope=2,
        vulnerability_class="CSRF")
    award1 = create_award(rep1["id"], "BONUS", amount_cents=80_000)
    approve_award(award1["id"])
    award2 = create_award(rep2["id"], "BONUS", amount_cents=50_000)
    resp = api.approve_award(award2["id"], PROGRAM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_POOL_EXHAUSTED)
    # The failed approve leaves the award PROPOSED and the reservation intact
    assert get_award(award2["id"])["status"] == "PROPOSED"
    assert get_program(program["id"])["bounty_reserved_cents"] == 80_000
