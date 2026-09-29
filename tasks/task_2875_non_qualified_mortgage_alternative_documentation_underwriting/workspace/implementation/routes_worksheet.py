"""Income worksheets, statement months and the calculate / accept actions."""
from decimal import Decimal

from flask import Blueprint, request

from core import (ApiError, Field, authenticate, dec, invalid, iso_instant, ordered,
                  paginate, raw_body, require_range, respond_collection,
                  respond_created, respond_object, validate_body)
from store import Tx, db, resolve_fk
import services
from routes_loanfile import gate_segregation

bp = Blueprint("worksheets", __name__)

METHODS = ("BANK_STATEMENT", "ASSET_DEPLETION", "DSCR", "PROFIT_AND_LOSS")
WORKSHEET_READERS = ("Underwriter", "CreditCommittee", "ChiefCreditOfficer",
                     "PostCloseAuditor")
OPEN_FILE_STATUSES = ("DOC_TYPE_SELECTED", "UNDERWRITING", "SUSPENDED")

WORKSHEET_FIELDS = [
    Field("loan_file_id", "str", True),
    Field("method", "enum", True, METHODS),
    Field("expected_loan_file_version", "int", True),
    Field("expense_factor_source", "enum", False, ("PROGRAM_DEFAULT", "CPA_LETTER")),
    Field("cpa_expense_factor_pct", "num", scale=2),
    Field("p_and_l_net_income_cents", "int"),
    Field("p_and_l_period_months", "int"),
    Field("asset_bucket_checking_cents", "int"),
    Field("asset_bucket_brokerage_cents", "int"),
    Field("asset_bucket_retirement_cents", "int"),
]

MONTH_FIELDS = [
    Field("period_start_date", "datetime", True),
    Field("period_end_date", "datetime", True),
    Field("deposits_total_cents", "int", True),
    Field("ineligible_transfer_cents", "int"),
]


def worksheet_state(worksheet, allowed):
    """validations priority 11."""
    if worksheet["status"] not in allowed:
        raise ApiError("ERR_WORKSHEET_STATE_INVALID",
                       "worksheet status %s does not permit this trigger"
                       % worksheet["status"])


def loan_file_of(worksheet):
    return db.find("loan_files", worksheet["loan_file_id"])


# ---------------------------------------------------------------------------
# creation and reads
# ---------------------------------------------------------------------------
@bp.post("/income-worksheets")
def create_worksheet():
    actor = authenticate(("Underwriter",))
    raw = raw_body()
    loan_file = resolve_fk(raw, "loan_file_id", "loan_files")
    values = validate_body(WORKSHEET_FIELDS)
    method = values["method"]
    source = values.get("expense_factor_source", "PROGRAM_DEFAULT")

    if source == "CPA_LETTER":
        if "cpa_expense_factor_pct" not in values:
            invalid("cpa_expense_factor_pct is required when expense_factor_source is CPA_LETTER")
    elif "cpa_expense_factor_pct" in values:
        invalid("cpa_expense_factor_pct is only permitted with expense_factor_source CPA_LETTER")
    if method == "PROFIT_AND_LOSS":
        for name in ("p_and_l_net_income_cents", "p_and_l_period_months"):
            if name not in values:
                invalid("%s is required when method is PROFIT_AND_LOSS" % name)
        if values["p_and_l_net_income_cents"] < 0:
            invalid("p_and_l_net_income_cents must not be negative")
        if values["p_and_l_period_months"] <= 0:
            invalid("p_and_l_period_months must be positive")
    if method == "ASSET_DEPLETION":
        for name in ("asset_bucket_checking_cents", "asset_bucket_brokerage_cents",
                     "asset_bucket_retirement_cents"):
            if name not in values:
                invalid("%s is required when method is ASSET_DEPLETION" % name)
            if values[name] < 0:
                invalid("%s must not be negative" % name)

    # still priority 6: the CPA factor domain and the program floor are both
    # reported as ERR_INVALID_REQUEST, so they precede the concurrency check
    program = services.program_of(loan_file)
    if source == "CPA_LETTER":
        factor = values["cpa_expense_factor_pct"]
        if factor < Decimal(0) or factor > Decimal(100):
            invalid("cpa_expense_factor_pct must be within 0.00..100.00")
        floor = program.get("min_expense_factor_pct")
        if floor is not None and factor < dec(floor):
            invalid("cpa_expense_factor_pct is below the program minimum expense factor")

    # priority 8: optimistic concurrency on the parent loan file
    if int(values["expected_loan_file_version"]) != int(loan_file["version"]):
        raise ApiError("ERR_STALE_LOAN_FILE_VERSION",
                       "expected_loan_file_version does not match the loan file version")
    # priority 10
    if loan_file["status"] not in OPEN_FILE_STATUSES:
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "loan file status %s does not permit a worksheet" % loan_file["status"])
    # priority 17
    if loan_file.get("doc_type") != method:
        raise ApiError("ERR_DOC_TYPE_PROGRAM_MISMATCH",
                       "method must equal the loan file doc_type")
    # priority 23
    gate_segregation(actor, loan_file)

    tx = Tx()
    row = db.insert("worksheets", {
        "loan_file_id": loan_file["id"],
        "method": method,
        "expense_factor_source": source,
        "cpa_expense_factor_pct": values.get("cpa_expense_factor_pct"),
        "p_and_l_net_income_cents": values.get("p_and_l_net_income_cents"),
        "p_and_l_period_months": values.get("p_and_l_period_months"),
        "asset_bucket_checking_cents": values.get("asset_bucket_checking_cents"),
        "asset_bucket_brokerage_cents": values.get("asset_bucket_brokerage_cents"),
        "asset_bucket_retirement_cents": values.get("asset_bucket_retirement_cents"),
        "status": "DRAFT",
        "eligible_deposit_total_cents": 0,
        "net_deposit_total_cents": 0,
        "included_month_count": 0,
        "eligible_assets_after_haircut_cents": 0,
        "depletable_assets_cents": 0,
        "expense_factor_pct_applied": None,
        "gross_monthly_income_cents": 0,
        "monthly_qualifying_income_cents": 0,
        "variant_applied": None,
        "calculation_count": 0,
    })
    tx.watch(loan_file)
    tx.bump(loan_file)
    tx.commit()
    return respond_created(row)


@bp.get("/income-worksheets/<ident>")
def read_worksheet(ident):
    authenticate(WORKSHEET_READERS)
    return respond_object(db.fetch("worksheets", ident))


@bp.get("/loan-files/<ident>/income-worksheets")
def list_worksheets(ident):
    authenticate(WORKSHEET_READERS)
    loan_file = db.fetch("loan_files", ident)
    rows = services.worksheets_of(loan_file)
    wanted = request.args.get("status")
    if wanted:
        rows = [r for r in rows if r["status"] == wanted]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)


# ---------------------------------------------------------------------------
# statement months
# ---------------------------------------------------------------------------
@bp.post("/income-worksheets/<ident>/statement-months")
def attach_statement_month(ident):
    authenticate(("Underwriter",))
    worksheet = db.fetch("worksheets", ident)
    values = validate_body(MONTH_FIELDS)
    start = values["period_start_date"]
    end = values["period_end_date"]
    # priority 7
    require_range(values["deposits_total_cents"] >= 0,
                  "deposits_total_cents must not be negative")
    if values.get("ineligible_transfer_cents") is not None:
        require_range(values["ineligible_transfer_cents"] >= 0,
                      "ineligible_transfer_cents must not be negative")
    require_range(start < end, "period_start_date must be before period_end_date")
    # priority 11
    worksheet_state(worksheet, ("DRAFT", "CALCULATED"))
    loan_file = loan_file_of(worksheet)
    # priority 26
    if services.statement_period_overlaps(worksheet, start, end):
        raise ApiError("ERR_STATEMENT_PERIOD_OVERLAP",
                       "the statement period overlaps an attached month")
    # priority 27
    program = services.program_of(loan_file)
    if not services.statement_period_in_window(program, start, end):
        raise ApiError("ERR_STATEMENT_PERIOD_OUT_OF_WINDOW",
                       "the statement period is outside the permitted lookback window")

    deposits = int(values["deposits_total_cents"])
    ineligible = int(values.get("ineligible_transfer_cents") or 0)
    row = db.insert("statement_months", {
        "worksheet_id": worksheet["id"],
        "period_start_date": iso_instant(start),
        "period_end_date": iso_instant(end),
        "deposits_total_cents": deposits,
        "ineligible_transfer_cents": ineligible,
        "eligible_deposit_cents": max(0, deposits - ineligible),
        "inclusion_status": "INCLUDED",
        "exclusion_reason": None,
    })
    return respond_created(row)


@bp.get("/income-worksheets/<ident>/statement-months")
def list_statement_months(ident):
    authenticate(WORKSHEET_READERS)
    worksheet = db.fetch("worksheets", ident)
    rows = services.months_of(worksheet)
    wanted = request.args.get("inclusion_status")
    if wanted:
        rows = [r for r in rows if r["inclusion_status"] == wanted]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)


@bp.post("/statement-months/<ident>/exclude")
def exclude_statement_month(ident):
    authenticate(("Underwriter",))
    month = db.fetch("statement_months", ident)
    values = validate_body([Field("exclusion_reason", "str", True)])
    # priority 12
    if month["inclusion_status"] != "INCLUDED":
        raise ApiError("ERR_STATEMENT_MONTH_STATE_INVALID",
                       "the statement month is already EXCLUDED")
    worksheet = db.find("worksheets", month["worksheet_id"])
    loan_file = loan_file_of(worksheet)
    # priority 30
    included = services.included_months(worksheet)
    if len(included) <= 1:
        raise ApiError("ERR_NO_INCLUDED_STATEMENT_MONTHS",
                       "the last INCLUDED statement month cannot be excluded")

    tx = Tx()
    tx.watch(month)
    month["inclusion_status"] = "EXCLUDED"
    month["exclusion_reason"] = values["exclusion_reason"]
    if worksheet["status"] == "CALCULATED":
        tx.watch(worksheet)
        services.calculate_worksheet(worksheet, loan_file, count=False)
    tx.commit()
    return respond_object(month)


# ---------------------------------------------------------------------------
# calculate / accept
# ---------------------------------------------------------------------------
@bp.post("/income-worksheets/<ident>/calculate")
def calculate(ident):
    authenticate(("Underwriter",))
    worksheet = db.fetch("worksheets", ident)
    validate_body([])
    # priority 11
    worksheet_state(worksheet, ("DRAFT", "CALCULATED"))
    loan_file = loan_file_of(worksheet)

    tx = Tx()
    tx.watch(worksheet)
    services.calculate_worksheet(worksheet, loan_file)
    tx.commit()
    return respond_object(worksheet)


@bp.post("/income-worksheets/<ident>/accept")
def accept(ident):
    authenticate(("Underwriter",))
    worksheet = db.fetch("worksheets", ident)
    validate_body([])
    # priority 11
    worksheet_state(worksheet, ("CALCULATED",))
    loan_file = loan_file_of(worksheet)
    # priority 29
    if worksheet["method"] == "BANK_STATEMENT":
        program = services.program_of(loan_file)
        required = int(program["statement_period_months"])
        if int(worksheet["included_month_count"]) != required:
            raise ApiError("ERR_INSUFFICIENT_STATEMENT_MONTHS",
                           "exactly %d INCLUDED statement months are required" % required)

    tx = Tx()
    tx.watch(worksheet)
    for other in services.worksheets_of(loan_file):
        if other["id"] != worksheet["id"] and other["status"] == "ACCEPTED":
            tx.watch(other)
            other["status"] = "SUPERSEDED"
    worksheet["status"] = "ACCEPTED"
    tx.watch(loan_file)
    tx.bump(loan_file)
    loan_file["qualifying_income_monthly_cents"] = int(
        worksheet["monthly_qualifying_income_cents"])
    services.recompute_income_derived(loan_file)
    services.invalidate_determination(loan_file)
    services.sweep_and_cascade(loan_file, tx)
    tx.commit()
    return respond_object(worksheet)
