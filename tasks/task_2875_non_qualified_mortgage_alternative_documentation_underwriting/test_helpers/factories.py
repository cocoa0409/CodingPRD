"""Request-payload builders.

Conventions, applied everywhere:

* Money is sent as a JSON integer number of cents (PRD 2.5), never as a string.
* Percentages, ratios and other decimal-valued inputs are sent as JSON numbers.
* Every date-or-time input is sent as a full ISO-8601 UTC instant, never as a
  bare calendar date; ``instant()`` widens ``"2026-05-01"`` to
  ``"2026-05-01T00:00:00Z"`` so a caller may pin either spelling.
* Optional fields are omitted entirely rather than sent as null, because PRD 3.1
  and 3.3 make "supplying a field the context forbids" an ``ERR_INVALID_REQUEST``
  in its own right.
"""

from typing import Any, Dict, List, Optional

from .constants import SEASONING_MATRIX


def instant(value: str) -> str:
    """Widen a bare ``YYYY-MM-DD`` to a full UTC instant; pass instants through."""
    if len(value) == 10 and value.count("-") == 2:
        return f"{value}T00:00:00Z"
    return value


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is ``None`` so omitted fields are truly absent."""
    return {key: value for key, value in payload.items() if value is not None}


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override of ``None`` removes the field entirely."""
    merged = dict(payload)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# --- Documentation programs (PRD 3.1) -------------------------------------
def program_payload(program_code: str, **overrides: Any) -> Dict[str, Any]:
    """A documentation program with the methodology fields its family requires.

    ``statement_period_months``, the two expense-factor percentages,
    ``depletion_horizon_months``, ``min_dscr`` and ``max_dti_pct`` are each only
    included for the families PRD 3.1 requires them for.
    """
    payload: Dict[str, Any] = {
        "program_code": program_code,
        "name": f"{program_code} program",
        "max_ltv_pct": 80.00,
        "min_fico": 660,
        "min_reserves_months": 6,
        "min_residual_income_cents": 0,
        "second_valuation_ltv_threshold_pct": 90.00,
        "second_valuation_loan_amount_threshold_cents": 200000000,
        "atr_exempt_flag": False,
        "seasoning_matrix": dict(SEASONING_MATRIX),
    }
    if program_code.startswith("BANK_STATEMENT_"):
        payload["statement_period_months"] = 12 if program_code.endswith("12MO") else 24
        payload["default_expense_factor_pct"] = 50.00
        payload["min_expense_factor_pct"] = 20.00
    elif program_code == "PROFIT_AND_LOSS":
        payload["statement_period_months"] = 12
        payload["default_expense_factor_pct"] = 50.00
        payload["min_expense_factor_pct"] = 20.00
    elif program_code == "ASSET_DEPLETION":
        payload["depletion_horizon_months"] = 120
    elif program_code == "DSCR":
        payload["min_dscr"] = 1.0000
    if program_code != "DSCR":
        payload["max_dti_pct"] = 50.00
    return _merge(payload, overrides)


# --- Investor overlays (PRD 3.1) -----------------------------------------
def overlay_payload(investor_code: str, overlay_code: str, rule_metric: str,
                    comparator: str, threshold_value: Any,
                    **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "investor_code": investor_code,
        "overlay_code": overlay_code,
        "rule_metric": rule_metric,
        "comparator": comparator,
        "threshold_value": threshold_value,
        "severity": "MINOR",
    }
    return _merge(payload, overrides)


# --- Borrowers and credit events (PRD 3.2) -------------------------------
def borrower_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Dana Alvarez",
        "fico_score": 720,
        "self_employed_flag": True,
        "entity_ownership_pct": 100.00,
        "monthly_debt_obligations_cents": 0,
        "verified_liquid_assets_cents": 30000000,
        "age_years": 45,
    }
    return _merge(payload, overrides)


def credit_event_payload(borrower_id: str, event_type: str, completion_date: str,
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "borrower_id": borrower_id,
        "event_type": event_type,
        "completion_date": instant(completion_date),
    }
    return _merge(payload, overrides)


# --- Loan files (PRD 3.3) -------------------------------------------------
def loan_file_payload(borrower_id: str, program_id: str, investor_code: str,
                      **overrides: Any) -> Dict[str, Any]:
    """A loan file. ``purchase_price_cents`` rides only on a ``PURCHASE``."""
    payload: Dict[str, Any] = {
        "borrower_id": borrower_id,
        "program_id": program_id,
        "investor_code": investor_code,
        "loan_amount_cents": 40000000,
        "property_value_cents": 55000000,
        "occupancy": "PRIMARY",
        "purpose": "RATE_TERM_REFI",
        "lien_position": "FIRST",
        "note_rate_pct": 8.750,
        "apor_pct": 6.500,
        "term_months": 360,
        "amortization_type": "FULLY_AMORTIZING",
        "monthly_taxes_cents": 0,
        "monthly_insurance_cents": 0,
    }
    merged = _merge(payload, overrides)
    if merged.get("purpose") == "PURCHASE" and "purchase_price_cents" not in merged:
        merged["purchase_price_cents"] = merged["property_value_cents"]
    if merged.get("purpose") != "PURCHASE":
        merged.pop("purchase_price_cents", None)
    return merged


def doc_type_selection_payload(doc_type: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"doc_type": doc_type}, overrides)


# --- Income worksheets and statement months (PRD 3.4) --------------------
def worksheet_payload(loan_file_id: str, method: str,
                      expected_loan_file_version: int,
                      **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loan_file_id": loan_file_id,
        "method": method,
        "expected_loan_file_version": expected_loan_file_version,
    }
    return _merge(payload, overrides)


def statement_month_payload(period_start_date: str, period_end_date: str,
                           deposits_total_cents: int,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start_date": instant(period_start_date),
        "period_end_date": instant(period_end_date),
        "deposits_total_cents": deposits_total_cents,
    }
    return _merge(payload, overrides)


def exclusion_payload(exclusion_reason: str = "Non-recurring transfer") -> Dict[str, Any]:
    return {"exclusion_reason": exclusion_reason}


# --- Valuations (PRD 3.5) ------------------------------------------------
def valuation_order_payload(loan_file_id: str, valuation_type: str,
                            effective_date: str,
                            vendor_code: str = "AMC-ONE",
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loan_file_id": loan_file_id,
        "valuation_type": valuation_type,
        "vendor_code": vendor_code,
        "effective_date": instant(effective_date),
    }
    return _merge(payload, overrides)


def receive_payload(appraised_value_cents: int) -> Dict[str, Any]:
    return {"appraised_value_cents": appraised_value_cents}


def accept_valuation_payload() -> Dict[str, Any]:
    return {"decision": "ACCEPTED"}


def reject_valuation_payload(rejection_reason: str = "Unsupported adjustments") -> Dict[str, Any]:
    return {"decision": "REJECTED", "rejection_reason": rejection_reason}


def override_escalation_payload(
        override_justification: str = "Second value accepted as the basis") -> Dict[str, Any]:
    return {"override_justification": override_justification}


# --- Points-and-fees items (PRD 3.6) ------------------------------------
def fee_item_payload(loan_file_id: str, fee_code: str, fee_category: str,
                     amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loan_file_id": loan_file_id,
        "fee_code": fee_code,
        "fee_category": fee_category,
        "amount_cents": amount_cents,
    }
    return _merge(payload, overrides)


def void_payload(void_reason: str = "Charge corrected") -> Dict[str, Any]:
    return {"void_reason": void_reason}


# --- Exception requests (PRD 3.7) ---------------------------------------
def exception_request_payload(loan_file_id: str, overlay_id: str,
                              justification: str = "Compensating factors support the waiver",
                              compensating_factors: Optional[List[str]] = None,
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "loan_file_id": loan_file_id,
        "overlay_id": overlay_id,
        "justification": justification,
    }
    if compensating_factors is not None:
        payload["compensating_factors"] = compensating_factors
    return _merge(payload, overrides)


def exception_approve_payload(decision_reason: str = "Committee concurs") -> Dict[str, Any]:
    return {"decision": "APPROVE", "decision_reason": decision_reason}


def exception_deny_payload(decision_reason: str = "Insufficient compensating factors") -> Dict[str, Any]:
    return {"decision": "DENY", "decision_reason": decision_reason}


# --- Loan-file credit decision (PRD 3.8) --------------------------------
def suspend_payload(suspension_reason: str = "Conditions issued") -> Dict[str, Any]:
    return {"suspension_reason": suspension_reason}


def clear_conditions_payload(resolution_note: str = "Conditions satisfied") -> Dict[str, Any]:
    return {"resolution_note": resolution_note}


def deny_payload(denial_reason: str = "Guideline decline") -> Dict[str, Any]:
    return {"denial_reason": denial_reason}


# --- Securitization and audit (PRD 3.9) ---------------------------------
def pool_payload(pool_code: str, investor_code: str,
                 target_balance_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pool_code": pool_code,
        "investor_code": investor_code,
        "target_balance_cents": target_balance_cents,
    }
    return _merge(payload, overrides)


def pool_assignment_payload(loan_file_id: str, expected_pool_version: int) -> Dict[str, Any]:
    return {"loan_file_id": loan_file_id, "expected_pool_version": expected_pool_version}


def pool_removal_payload(removal_reason: str, expected_pool_version: int,
                         loan_file_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "removal_reason": removal_reason,
        "expected_pool_version": expected_pool_version,
    }
    if loan_file_id is not None:
        payload["loan_file_id"] = loan_file_id
    return payload


def audit_payload(loan_file_id: str, sample_reason: str = "RANDOM",
                  **overrides: Any) -> Dict[str, Any]:
    return _merge({"loan_file_id": loan_file_id, "sample_reason": sample_reason},
                  overrides)


def finding_payload(audit_id: str, finding_code: str, category: str,
                    severity: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "audit_id": audit_id,
        "finding_code": finding_code,
        "category": category,
        "severity": severity,
    }
    return _merge(payload, overrides)


def rebuttal_payload(rebuttal_text: str = "Documentation is in the imaged file") -> Dict[str, Any]:
    return {"rebuttal_text": rebuttal_text}


def adjudication_payload(decision: str,
                         adjudication_note: Optional[str] = None) -> Dict[str, Any]:
    return _prune({"decision": decision, "adjudication_note": adjudication_note})


# --- Logical clock (PRD 2.6) --------------------------------------------
def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": instant(current_utc)}
