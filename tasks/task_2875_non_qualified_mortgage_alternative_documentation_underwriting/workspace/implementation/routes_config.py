"""Documentation programs, investor overlays and the logical clock."""
from flask import Blueprint

from core import (ApiError, Field, ROLES, authenticate, invalid, require_range,
                  respond_created, respond_empty, respond_object, validate_body)
from store import db

bp = Blueprint("config", __name__)

PROGRAM_CODES = ("BANK_STATEMENT_12MO", "BANK_STATEMENT_24MO", "ASSET_DEPLETION",
                 "DSCR", "PROFIT_AND_LOSS")
SEASONING_KEYS = ("FORECLOSURE", "SHORT_SALE", "DEED_IN_LIEU", "BK_CH7", "BK_CH13",
                  "MODIFICATION", "MORTGAGE_LATE_60")
RULE_METRICS = ("MIN_FICO", "MAX_LTV_PCT", "MIN_DSCR", "MAX_DTI_PCT",
                "MIN_RESERVES_MONTHS", "MIN_SEASONING_MONTHS", "MAX_LOAN_AMOUNT_CENTS")

PROGRAM_FIELDS = [
    Field("program_code", "enum", True, PROGRAM_CODES),
    Field("name", "str", True),
    Field("statement_period_months", "int"),
    Field("default_expense_factor_pct", "num", scale=2),
    Field("min_expense_factor_pct", "num", scale=2),
    Field("depletion_horizon_months", "int"),
    Field("min_dscr", "num", scale=4),
    Field("max_ltv_pct", "num", True, scale=2),
    Field("min_fico", "int", True),
    Field("min_reserves_months", "int", True),
    Field("max_dti_pct", "num", scale=2),
    Field("min_residual_income_cents", "int", True),
    Field("second_valuation_ltv_threshold_pct", "num", True, scale=2),
    Field("second_valuation_loan_amount_threshold_cents", "int", True),
    Field("atr_exempt_flag", "bool"),
    Field("seasoning_matrix", "object", True),
]

OVERLAY_FIELDS = [
    Field("investor_code", "str", True),
    Field("overlay_code", "str", True),
    Field("applies_to_program_code", "enum", False, PROGRAM_CODES),
    Field("rule_metric", "enum", True, RULE_METRICS),
    Field("comparator", "enum", True, ("GTE", "LTE")),
    Field("threshold_value", "num", True),
    Field("waivable_flag", "bool"),
    Field("required_authority_tier", "int", True),
    Field("severity", "enum", True, ("MINOR", "MATERIAL")),
]


def _require_present(values, name):
    if name not in values:
        invalid("%s is required for this program_code" % name)


def _require_absent(values, name):
    if name in values:
        invalid("%s is not permitted for this program_code" % name)


@bp.post("/documentation-programs")
def create_program():
    authenticate(("ProgramAdmin",))
    values = validate_body(PROGRAM_FIELDS)
    code = values["program_code"]

    if code in ("BANK_STATEMENT_12MO", "BANK_STATEMENT_24MO"):
        _require_present(values, "statement_period_months")
        if values["statement_period_months"] not in (12, 24):
            invalid("statement_period_months must be 12 or 24")
    elif code == "PROFIT_AND_LOSS":
        _require_present(values, "statement_period_months")
        if values["statement_period_months"] != 12:
            invalid("statement_period_months must be 12 for PROFIT_AND_LOSS")
    else:
        _require_absent(values, "statement_period_months")

    if code in ("BANK_STATEMENT_12MO", "BANK_STATEMENT_24MO", "PROFIT_AND_LOSS"):
        _require_present(values, "default_expense_factor_pct")
        _require_present(values, "min_expense_factor_pct")
    else:
        _require_absent(values, "default_expense_factor_pct")
        _require_absent(values, "min_expense_factor_pct")

    if code == "ASSET_DEPLETION":
        _require_present(values, "depletion_horizon_months")
    else:
        _require_absent(values, "depletion_horizon_months")

    if code == "DSCR":
        _require_present(values, "min_dscr")
        _require_absent(values, "max_dti_pct")
    else:
        _require_absent(values, "min_dscr")
        _require_present(values, "max_dti_pct")

    matrix = values["seasoning_matrix"]
    if set(matrix.keys()) != set(SEASONING_KEYS):
        invalid("seasoning_matrix must carry exactly the seven declared event types")
    for key, months in matrix.items():
        if isinstance(months, bool) or not isinstance(months, int):
            invalid("seasoning_matrix.%s must be an integer" % key)

    require_range(0 <= values["max_ltv_pct"] <= 100, "max_ltv_pct must be within 0..100")
    require_range(0 <= values["second_valuation_ltv_threshold_pct"] <= 100,
                  "second_valuation_ltv_threshold_pct must be within 0..100")
    require_range(300 <= values["min_fico"] <= 850, "min_fico must be within 300..850")
    require_range(values["min_reserves_months"] >= 0, "min_reserves_months must not be negative")
    require_range(values["min_residual_income_cents"] >= 0,
                  "min_residual_income_cents must not be negative")
    require_range(values["second_valuation_loan_amount_threshold_cents"] > 0,
                  "second_valuation_loan_amount_threshold_cents must be greater than zero")
    if "default_expense_factor_pct" in values:
        require_range(0 <= values["default_expense_factor_pct"] <= 100,
                      "default_expense_factor_pct must be within 0..100")
        require_range(0 <= values["min_expense_factor_pct"] <= 100,
                      "min_expense_factor_pct must be within 0..100")
    if "max_dti_pct" in values:
        require_range(0 <= values["max_dti_pct"] <= 100, "max_dti_pct must be within 0..100")
    if "min_dscr" in values:
        require_range(values["min_dscr"] >= 0, "min_dscr must not be negative")
    if "depletion_horizon_months" in values:
        require_range(values["depletion_horizon_months"] > 0,
                      "depletion_horizon_months must be a positive integer")
    for key, months in matrix.items():
        require_range(months >= 0, "seasoning_matrix.%s must not be negative" % key)

    for existing in db.rows("programs"):
        if existing["program_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", "program_code is already registered")

    row = db.insert("programs", {
        "program_code": code,
        "name": values["name"],
        "statement_period_months": values.get("statement_period_months"),
        "default_expense_factor_pct": values.get("default_expense_factor_pct"),
        "min_expense_factor_pct": values.get("min_expense_factor_pct"),
        "depletion_horizon_months": values.get("depletion_horizon_months"),
        "min_dscr": values.get("min_dscr"),
        "max_ltv_pct": values["max_ltv_pct"],
        "min_fico": values["min_fico"],
        "min_reserves_months": values["min_reserves_months"],
        "max_dti_pct": values.get("max_dti_pct"),
        "min_residual_income_cents": values["min_residual_income_cents"],
        "second_valuation_ltv_threshold_pct": values["second_valuation_ltv_threshold_pct"],
        "second_valuation_loan_amount_threshold_cents":
            values["second_valuation_loan_amount_threshold_cents"],
        "atr_exempt_flag": values.get("atr_exempt_flag", False),
        "seasoning_matrix": dict(matrix),
    })
    return respond_created(row)


@bp.get("/documentation-programs/<ident>")
def read_program(ident):
    authenticate(ROLES)
    return respond_object(db.fetch("programs", ident))


@bp.post("/investor-overlays")
def create_overlay():
    authenticate(("ProgramAdmin",))
    values = validate_body(OVERLAY_FIELDS)
    if values["required_authority_tier"] not in (1, 2):
        invalid("required_authority_tier must be 1 or 2")
    require_range(values["threshold_value"] >= 0, "threshold_value must not be negative")
    for existing in db.rows("overlays"):
        if (existing["investor_code"] == values["investor_code"]
                and existing["overlay_code"] == values["overlay_code"]):
            raise ApiError("ERR_DUPLICATE_CODE",
                           "overlay_code is already registered for this investor")
    row = db.insert("overlays", {
        "investor_code": values["investor_code"],
        "overlay_code": values["overlay_code"],
        "applies_to_program_code": values.get("applies_to_program_code"),
        "rule_metric": values["rule_metric"],
        "comparator": values["comparator"],
        "threshold_value": values["threshold_value"],
        "waivable_flag": values.get("waivable_flag", True),
        "required_authority_tier": values["required_authority_tier"],
        "severity": values["severity"],
    })
    return respond_created(row)


@bp.get("/investor-overlays/<ident>")
def read_overlay(ident):
    authenticate(("ProgramAdmin", "LoanOfficer", "Underwriter", "CreditCommittee",
                  "ChiefCreditOfficer", "SecuritizationAnalyst"))
    return respond_object(db.fetch("overlays", ident))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ROLES)
    values = validate_body([Field("current_utc", "datetime", True)])
    db.clock = values["current_utc"]
    return respond_empty()
