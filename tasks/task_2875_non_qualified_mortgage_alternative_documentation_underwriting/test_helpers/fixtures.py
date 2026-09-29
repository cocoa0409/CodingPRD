"""Composite scenario drivers.

Each driver performs one legitimate PRD workflow step, asserts only that the
step itself succeeded, and returns the created or advanced resource row (already
unwrapped from the envelope by ``validate_success``). Tests keep every pinned
literal they assert on in their own body; these drivers only carry a scenario to
the state under test.

Two conventions worth calling out:

* Underwriter identity. PRD 3.3 stores the acting ``X-User-ID`` of the
  documentation-type selection in ``assigned_underwriter_id``, and PRD 3.4, 3.6
  and 3.8 then require that same identifier for the worksheet, points-and-fees
  and approval operations. Drivers therefore thread one explicit underwriter
  header dictionary rather than reaching for a shared default.
* Fee schedule before submission. PRD 3.3 accepts a submission "only once at
  least one points-and-fees item in ``ACTIVE`` status exists on the file", so a
  scenario that submits must first attach a charge. ``attach_escrow_fee``
  attaches an ``ESCROW_TAXES`` charge, which PRD 3.6 always classifies
  ``EXCLUDED``, so it changes no total, no cap and no verdict.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import validate_success

from . import factories
from .test_users import (
    ADMIN,
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    POST_CLOSE_AUDITOR,
    SECURITIZATION_ANALYST,
    underwriter,
)

Json = Dict[str, Any]
Headers = Dict[str, str]


# --- Clock ----------------------------------------------------------------
def set_clock(api, current_utc: str, headers: Optional[Headers] = None) -> Json:
    """Move the logical clock (PRD 2.6)."""
    response = api.set_clock(factories.clock_payload(current_utc), headers or ADMIN)
    return validate_success(response)


# --- Configuration --------------------------------------------------------
def create_program(api, program_code: str, headers: Optional[Headers] = None,
                   **overrides: Any) -> Json:
    response = api.create_program(
        factories.program_payload(program_code, **overrides), headers or ADMIN)
    return validate_success(response, 201)


def create_overlay(api, investor_code: str, overlay_code: str, rule_metric: str,
                   comparator: str, threshold_value: Any,
                   headers: Optional[Headers] = None, **overrides: Any) -> Json:
    response = api.create_overlay(
        factories.overlay_payload(investor_code, overlay_code, rule_metric,
                                  comparator, threshold_value, **overrides),
        headers or ADMIN)
    return validate_success(response, 201)


# --- Borrower and history -------------------------------------------------
def create_borrower(api, headers: Optional[Headers] = None, **overrides: Any) -> Json:
    response = api.create_borrower(factories.borrower_payload(**overrides),
                                   headers or LOAN_OFFICER)
    return validate_success(response, 201)


def create_credit_event(api, borrower_id: str, event_type: str,
                        completion_date: str, headers: Optional[Headers] = None,
                        **overrides: Any) -> Json:
    response = api.create_credit_event(
        factories.credit_event_payload(borrower_id, event_type, completion_date,
                                       **overrides),
        headers or LOAN_OFFICER)
    return validate_success(response, 201)


# --- Loan file ------------------------------------------------------------
def create_loan_file(api, borrower_id: str, program_id: str, investor_code: str,
                     headers: Optional[Headers] = None, **overrides: Any) -> Json:
    response = api.create_loan_file(
        factories.loan_file_payload(borrower_id, program_id, investor_code,
                                    **overrides),
        headers or LOAN_OFFICER)
    return validate_success(response, 201)


def get_loan_file(api, loan_file_id: str, headers: Optional[Headers] = None) -> Json:
    return validate_success(api.get_loan_file(loan_file_id, headers or LOAN_OFFICER))


def select_doc_type(api, loan_file_id: str, doc_type: str, uw_headers: Headers) -> Json:
    response = api.select_doc_type(loan_file_id,
                                   factories.doc_type_selection_payload(doc_type),
                                   uw_headers)
    return validate_success(response)


def attach_escrow_fee(api, loan_file_id: str, headers: Optional[Headers] = None,
                      fee_code: str = "ESC-PLACEHOLDER",
                      amount_cents: int = 180000) -> Json:
    """Attach an ``ESCROW_TAXES`` charge, which is always ``EXCLUDED`` (PRD 3.6)."""
    response = api.create_fee_item(
        factories.fee_item_payload(loan_file_id, fee_code, "ESCROW_TAXES",
                                   amount_cents),
        headers or LOAN_OFFICER)
    return validate_success(response, 201)


def create_fee_item(api, loan_file_id: str, fee_code: str, fee_category: str,
                    amount_cents: int, headers: Optional[Headers] = None,
                    **overrides: Any) -> Json:
    response = api.create_fee_item(
        factories.fee_item_payload(loan_file_id, fee_code, fee_category,
                                   amount_cents, **overrides),
        headers or LOAN_OFFICER)
    return validate_success(response, 201)


def void_fee_item(api, fee_item_id: str, headers: Optional[Headers] = None,
                  void_reason: str = "Charge corrected") -> Json:
    response = api.void_fee_item(fee_item_id, factories.void_payload(void_reason),
                                headers or LOAN_OFFICER)
    return validate_success(response)


def submit_to_underwriting(api, loan_file_id: str,
                           headers: Optional[Headers] = None) -> Json:
    return validate_success(api.submit_to_underwriting(loan_file_id,
                                                       headers or LOAN_OFFICER))


def run_points_and_fees_test(api, loan_file_id: str, uw_headers: Headers) -> Json:
    return validate_success(api.run_points_and_fees_test(loan_file_id, uw_headers))


def run_atr_determination(api, loan_file_id: str, uw_headers: Headers) -> Json:
    return validate_success(api.run_atr_determination(loan_file_id, uw_headers))


def suspend(api, loan_file_id: str, uw_headers: Headers,
            suspension_reason: str = "Conditions issued") -> Json:
    return validate_success(api.suspend_loan_file(
        loan_file_id, factories.suspend_payload(suspension_reason), uw_headers))


def clear_conditions(api, loan_file_id: str, uw_headers: Headers,
                     resolution_note: str = "Conditions satisfied") -> Json:
    return validate_success(api.clear_conditions(
        loan_file_id, factories.clear_conditions_payload(resolution_note), uw_headers))


def approve(api, loan_file_id: str, uw_headers: Headers) -> Json:
    return validate_success(api.approve_loan_file(loan_file_id, uw_headers))


def close(api, loan_file_id: str, headers: Optional[Headers] = None) -> Json:
    return validate_success(api.close_loan_file(loan_file_id, headers or LOAN_OFFICER))


# --- Income worksheets ----------------------------------------------------
def create_worksheet(api, loan_file_id: str, method: str,
                     expected_loan_file_version: int, uw_headers: Headers,
                     **overrides: Any) -> Json:
    response = api.create_worksheet(
        factories.worksheet_payload(loan_file_id, method,
                                    expected_loan_file_version, **overrides),
        uw_headers)
    return validate_success(response, 201)


def attach_statement_month(api, worksheet_id: str, period_start_date: str,
                           period_end_date: str, deposits_total_cents: int,
                           uw_headers: Headers, **overrides: Any) -> Json:
    response = api.create_statement_month(
        worksheet_id,
        factories.statement_month_payload(period_start_date, period_end_date,
                                          deposits_total_cents, **overrides),
        uw_headers)
    return validate_success(response, 201)


def exclude_statement_month(api, statement_month_id: str, uw_headers: Headers,
                            exclusion_reason: str = "Non-recurring transfer") -> Json:
    return validate_success(api.exclude_statement_month(
        statement_month_id, factories.exclusion_payload(exclusion_reason), uw_headers))


def calculate_worksheet(api, worksheet_id: str, uw_headers: Headers) -> Json:
    return validate_success(api.calculate_worksheet(worksheet_id, uw_headers))


def accept_worksheet(api, worksheet_id: str, uw_headers: Headers) -> Json:
    return validate_success(api.accept_worksheet(worksheet_id, uw_headers))


# --- Valuations -----------------------------------------------------------
def order_valuation(api, loan_file_id: str, valuation_type: str,
                    effective_date: str, headers: Optional[Headers] = None,
                    **overrides: Any) -> Json:
    response = api.create_valuation_order(
        factories.valuation_order_payload(loan_file_id, valuation_type,
                                          effective_date, **overrides),
        headers or LOAN_OFFICER)
    return validate_success(response, 201)


def receive_valuation(api, order_id: str, appraised_value_cents: int,
                      headers: Optional[Headers] = None) -> Json:
    return validate_success(api.receive_valuation(
        order_id, factories.receive_payload(appraised_value_cents),
        headers or APPRAISAL_REVIEWER))


def accept_valuation(api, order_id: str, headers: Optional[Headers] = None) -> Json:
    return validate_success(api.decide_valuation(
        order_id, factories.accept_valuation_payload(),
        headers or APPRAISAL_REVIEWER))


def reject_valuation(api, order_id: str, headers: Optional[Headers] = None,
                     rejection_reason: str = "Unsupported adjustments") -> Json:
    return validate_success(api.decide_valuation(
        order_id, factories.reject_valuation_payload(rejection_reason),
        headers or APPRAISAL_REVIEWER))


def order_receive_accept(api, loan_file_id: str, valuation_type: str,
                         effective_date: str, appraised_value_cents: int,
                         order_headers: Optional[Headers] = None,
                         reviewer_headers: Optional[Headers] = None) -> Json:
    """Order, receive and accept one valuation; returns the accepted order."""
    order = order_valuation(api, loan_file_id, valuation_type, effective_date,
                            order_headers)
    receive_valuation(api, order["id"], appraised_value_cents, reviewer_headers)
    return accept_valuation(api, order["id"], reviewer_headers)


def get_review(api, loan_file_id: str, headers: Optional[Headers] = None) -> Json:
    """The file's appraisal review row; PRD 4 makes the file-scoped list its only
    discovery channel."""
    rows = validate_success(api.list_appraisal_reviews(loan_file_id,
                                                       headers or LOAN_OFFICER))
    assert isinstance(rows, list) and len(rows) == 1, (
        f"expected exactly one appraisal review row, got {rows!r}"
    )
    return rows[0]


def override_escalation(api, review_id: str, headers: Optional[Headers] = None,
                        override_justification: str = "Second value accepted as the basis") -> Json:
    return validate_success(api.override_escalation(
        review_id, factories.override_escalation_payload(override_justification),
        headers or APPRAISAL_REVIEWER))


# --- Exceptions -----------------------------------------------------------
def create_exception_request(api, loan_file_id: str, overlay_id: str,
                             uw_headers: Headers, **overrides: Any) -> Json:
    response = api.create_exception_request(
        factories.exception_request_payload(loan_file_id, overlay_id, **overrides),
        uw_headers)
    return validate_success(response, 201)


def approve_exception(api, exception_id: str, headers: Headers,
                      decision_reason: str = "Committee concurs") -> Json:
    return validate_success(api.decide_exception_request(
        exception_id, factories.exception_approve_payload(decision_reason), headers))


def deny_exception(api, exception_id: str, headers: Headers,
                   decision_reason: str = "Insufficient compensating factors") -> Json:
    return validate_success(api.decide_exception_request(
        exception_id, factories.exception_deny_payload(decision_reason), headers))


# --- Pools and audits -----------------------------------------------------
def create_pool(api, pool_code: str, investor_code: str, target_balance_cents: int,
                headers: Optional[Headers] = None, **overrides: Any) -> Json:
    response = api.create_pool(
        factories.pool_payload(pool_code, investor_code, target_balance_cents,
                               **overrides),
        headers or SECURITIZATION_ANALYST)
    return validate_success(response, 201)


def assign_loan(api, pool_id: str, loan_file_id: str, expected_pool_version: int,
                headers: Optional[Headers] = None) -> Json:
    return validate_success(api.assign_loan_to_pool(
        pool_id,
        factories.pool_assignment_payload(loan_file_id, expected_pool_version),
        headers or SECURITIZATION_ANALYST))


def remove_loan(api, pool_id: str, removal_reason: str, expected_pool_version: int,
                loan_file_id: Optional[str] = None,
                headers: Optional[Headers] = None) -> Json:
    return validate_success(api.remove_from_pool(
        pool_id,
        factories.pool_removal_payload(removal_reason, expected_pool_version,
                                       loan_file_id),
        headers or SECURITIZATION_ANALYST))


def create_audit(api, loan_file_id: str, sample_reason: str = "RANDOM",
                 headers: Optional[Headers] = None) -> Json:
    response = api.create_audit(factories.audit_payload(loan_file_id, sample_reason),
                                headers or POST_CLOSE_AUDITOR)
    return validate_success(response, 201)


def create_finding(api, audit_id: str, finding_code: str, category: str,
                   severity: str, headers: Optional[Headers] = None,
                   **overrides: Any) -> Json:
    response = api.create_finding(
        factories.finding_payload(audit_id, finding_code, category, severity,
                                  **overrides),
        headers or POST_CLOSE_AUDITOR)
    return validate_success(response, 201)


def rebut_finding(api, finding_id: str, headers: Optional[Headers] = None,
                  rebuttal_text: str = "Documentation is in the imaged file") -> Json:
    return validate_success(api.rebut_finding(
        finding_id, factories.rebuttal_payload(rebuttal_text),
        headers or LOAN_OFFICER))


def adjudicate_finding(api, finding_id: str, decision: str,
                       headers: Optional[Headers] = None,
                       adjudication_note: Optional[str] = None) -> Json:
    return validate_success(api.adjudicate_finding(
        finding_id, factories.adjudication_payload(decision, adjudication_note),
        headers or POST_CLOSE_AUDITOR))
