"""Loan files: creation, reads and the nine lifecycle actions."""
from decimal import Decimal

from flask import Blueprint, request

from core import (ApiError, Field, authenticate, dec, invalid, iso_instant, ordered,
                  paginate, raw_body, require_range, respond_collection,
                  respond_created, respond_object, validate_body)
from store import Tx, db, resolve_fk
import services

bp = Blueprint("loan_files", __name__)

DOC_TYPES = ("BANK_STATEMENT", "ASSET_DEPLETION", "DSCR", "PROFIT_AND_LOSS")
LOAN_STATUSES = ("DRAFT", "DOC_TYPE_SELECTED", "UNDERWRITING", "SUSPENDED", "APPROVED",
                 "CLOSED", "DENIED", "AUDIT_DEFECT")

READ_ONE_ROLES = ("LoanOfficer", "Underwriter", "CreditCommittee", "ChiefCreditOfficer",
                  "AppraisalReviewer", "PostCloseAuditor", "SecuritizationAnalyst")
READ_LIST_ROLES = ("LoanOfficer", "Underwriter", "CreditCommittee", "ChiefCreditOfficer",
                   "PostCloseAuditor", "SecuritizationAnalyst")

LOAN_FILE_FIELDS = [
    Field("borrower_id", "str", True),
    Field("program_id", "str", True),
    Field("investor_code", "str", True),
    Field("loan_amount_cents", "int", True),
    Field("purchase_price_cents", "int"),
    Field("property_value_cents", "int", True),
    Field("occupancy", "enum", True, ("PRIMARY", "SECOND_HOME", "INVESTMENT")),
    Field("purpose", "enum", True, ("PURCHASE", "RATE_TERM_REFI", "CASH_OUT_REFI")),
    Field("lien_position", "enum", True, ("FIRST", "SECOND")),
    Field("note_rate_pct", "num", True, scale=3),
    Field("apor_pct", "num", True, scale=3),
    Field("term_months", "int", True),
    Field("amortization_type", "enum", True, ("FULLY_AMORTIZING", "INTEREST_ONLY")),
    Field("monthly_taxes_cents", "int", True),
    Field("monthly_insurance_cents", "int", True),
    Field("monthly_hoa_cents", "int"),
    Field("gross_market_rent_cents", "int"),
    Field("lease_rent_cents", "int"),
]


# ---------------------------------------------------------------------------
# shared gates
# ---------------------------------------------------------------------------
def gate_state(loan_file, allowed):
    """validations priority 10."""
    if loan_file["status"] not in allowed:
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "loan file status %s does not permit this trigger"
                       % loan_file["status"])


def gate_segregation(actor, loan_file):
    """validations priority 23 clause (a)."""
    assigned = loan_file.get("assigned_underwriter_id")
    if assigned is not None and actor.user_id != assigned:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "this loan file is assigned to another underwriter")


def seasoning_probe(loan_file):
    """Evaluate seasoning at the current logical clock without mutating the row."""
    probe = dict(loan_file)
    services.compute_seasoning(probe)
    return probe


def gate_seasoning(loan_file):
    """validations priority 20."""
    if not seasoning_probe(loan_file)["seasoning_satisfied"]:
        raise ApiError("ERR_SEASONING_NOT_SATISFIED",
                       "the governing credit event is not sufficiently seasoned")


# ---------------------------------------------------------------------------
# creation and reads
# ---------------------------------------------------------------------------
@bp.post("/loan-files")
def create_loan_file():
    authenticate(("LoanOfficer",))
    raw = raw_body()
    resolve_fk(raw, "borrower_id", "borrowers")
    resolve_fk(raw, "program_id", "programs")
    values = validate_body(LOAN_FILE_FIELDS)
    if values["purpose"] == "PURCHASE":
        if "purchase_price_cents" not in values:
            invalid("purchase_price_cents is required when purpose is PURCHASE")
    elif "purchase_price_cents" in values:
        invalid("purchase_price_cents must be null unless purpose is PURCHASE")

    require_range(values["loan_amount_cents"] > 0, "loan_amount_cents must be positive")
    require_range(values["property_value_cents"] > 0,
                  "property_value_cents must be positive")
    if "purchase_price_cents" in values:
        require_range(values["purchase_price_cents"] > 0,
                      "purchase_price_cents must be positive")
    require_range(Decimal(0) < values["note_rate_pct"] <= Decimal("25.000"),
                  "note_rate_pct must be within 0.001..25.000")
    require_range(values["apor_pct"] > Decimal(0), "apor_pct must be positive")
    require_range(1 <= values["term_months"] <= 480,
                  "term_months must be within 1..480")
    for name in ("monthly_taxes_cents", "monthly_insurance_cents", "monthly_hoa_cents",
                 "gross_market_rent_cents", "lease_rent_cents"):
        if values.get(name) is not None:
            require_range(values[name] >= 0, "%s must not be negative" % name)

    tx = Tx()
    row = db.insert("loan_files", {
        "borrower_id": values["borrower_id"],
        "program_id": values["program_id"],
        "pool_id": None,
        "investor_code": values["investor_code"],
        "assigned_underwriter_id": None,
        "loan_amount_cents": values["loan_amount_cents"],
        "purchase_price_cents": values.get("purchase_price_cents"),
        "property_value_cents": values["property_value_cents"],
        "occupancy": values["occupancy"],
        "purpose": values["purpose"],
        "lien_position": values["lien_position"],
        "note_rate_pct": values["note_rate_pct"],
        "apor_pct": values["apor_pct"],
        "term_months": values["term_months"],
        "amortization_type": values["amortization_type"],
        "monthly_taxes_cents": values["monthly_taxes_cents"],
        "monthly_insurance_cents": values["monthly_insurance_cents"],
        "monthly_hoa_cents": values.get("monthly_hoa_cents", 0),
        "gross_market_rent_cents": values.get("gross_market_rent_cents"),
        "lease_rent_cents": values.get("lease_rent_cents"),
        "doc_type": None,
        "status": "DRAFT",
        "qualifying_income_monthly_cents": 0,
        "pitia_monthly_cents": 0,
        "dti_pct": None,
        "dscr_ratio": None,
        "residual_income_cents": 0,
        "documented_reserves_months": Decimal("0.00"),
        "ltv_pct": None,
        "points_and_fees_total_cents": 0,
        "total_loan_amount_cents": 0,
        "points_and_fees_cap_cents": 0,
        "points_and_fees_test_result": "NOT_TESTED",
        "atr_documentation_status": "INCOMPLETE",
        "safe_harbor_class": "NOT_EVALUATED",
        "rate_spread_pct": None,
        "governing_credit_event_id": None,
        "seasoning_months_required": 0,
        "seasoning_months_elapsed": 0,
        "seasoning_satisfied": True,
        "overlay_breach_codes": [],
        "unresolved_overlay_breach_count": 0,
        "securitization_eligible": False,
        "second_valuation_required": False,
        "investor_notification_required": False,
        "repurchase_flag": False,
    })
    services.recompute_payment(row)
    # PRD 3.3 opens the file with `second_valuation_required` false, and PRD 3.5
    # re-tests the requirement only at submission and on a later `ltv_pct`
    # recomputation, so creation computes the ratio without running the retest.
    services.compute_ltv_only(row)
    tx.commit()
    return respond_created(row)


@bp.get("/loan-files/<ident>")
def read_loan_file(ident):
    authenticate(READ_ONE_ROLES)
    return respond_object(db.fetch("loan_files", ident))


@bp.get("/loan-files")
def list_loan_files():
    authenticate(READ_LIST_ROLES)
    rows = db.rows("loan_files")
    for key in ("borrower_id", "program_id", "pool_id", "status", "doc_type"):
        wanted = request.args.get(key)
        if wanted:
            rows = [r for r in rows if r.get(key) == wanted]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)


# ---------------------------------------------------------------------------
# DRAFT -> DOC_TYPE_SELECTED
# ---------------------------------------------------------------------------
@bp.post("/loan-files/<ident>/doc-type-selection")
def select_doc_type(ident):
    actor = authenticate(("Underwriter",))
    loan_file = db.fetch("loan_files", ident)
    values = validate_body([Field("doc_type", "enum", True, DOC_TYPES)])
    gate_state(loan_file, ("DRAFT",))
    if loan_file.get("doc_type") is not None:
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID", "doc_type is already set")

    doc_type = values["doc_type"]
    program = services.program_of(loan_file)
    if services.DOC_TYPE_FOR_PROGRAM.get(program["program_code"]) != doc_type:
        raise ApiError("ERR_DOC_TYPE_PROGRAM_MISMATCH",
                       "doc_type %s is not offered by program %s"
                       % (doc_type, program["program_code"]))
    if doc_type == "DSCR":
        if (loan_file["occupancy"] != "INVESTMENT"
                or loan_file.get("gross_market_rent_cents") is None):
            raise ApiError("ERR_DOC_TYPE_PROGRAM_MISMATCH",
                           "DSCR requires an INVESTMENT property with market rent")
    if doc_type in ("BANK_STATEMENT", "PROFIT_AND_LOSS"):
        if not services.borrower_of(loan_file)["self_employed_flag"]:
            raise ApiError("ERR_DOC_TYPE_PROGRAM_MISMATCH",
                           "%s requires a self-employed borrower" % doc_type)

    tx = Tx()
    tx.watch(loan_file)
    loan_file["doc_type"] = doc_type
    loan_file["assigned_underwriter_id"] = actor.user_id
    services.recompute_payment(loan_file)
    loan_file["status"] = "DOC_TYPE_SELECTED"
    tx.commit()
    return respond_object(loan_file)


# ---------------------------------------------------------------------------
# DOC_TYPE_SELECTED -> UNDERWRITING
# ---------------------------------------------------------------------------
@bp.post("/loan-files/<ident>/submit-to-underwriting")
def submit_to_underwriting(ident):
    authenticate(("LoanOfficer",))
    loan_file = db.fetch("loan_files", ident)
    validate_body([])
    gate_state(loan_file, ("DOC_TYPE_SELECTED",))
    if not any(f["status"] == "ACTIVE" for f in services.fee_items_of(loan_file)):
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "the file needs at least one ACTIVE points-and-fees item")

    tx = Tx()
    tx.watch(loan_file)
    # PRD 3.3: submission "recomputes the credit-event seasoning fields against the
    # current logical clock"; PRD 3.2 stores the governing event, its requirement and
    # its elapsed months on the file, and the priority-20 refusal is defined in terms
    # of that stored verdict, so the recompute lands before the gate answers.
    services.compute_seasoning(loan_file)
    if not loan_file["seasoning_satisfied"]:
        raise ApiError("ERR_SEASONING_NOT_SATISFIED",
                       "the governing credit event is not sufficiently seasoned")
    loan_file["status"] = "UNDERWRITING"
    services.ensure_review(loan_file, tx)
    services.compute_ltv_only(loan_file)
    services.retest_second_valuation(loan_file, tx)
    services.overlay_sweep(loan_file, tx)
    services.recompute_eligibility(loan_file)
    tx.commit()
    return respond_object(loan_file)


# ---------------------------------------------------------------------------
# points-and-fees test / ATR determination
# ---------------------------------------------------------------------------
@bp.post("/loan-files/<ident>/points-and-fees-test")
def run_points_and_fees_test(ident):
    actor = authenticate(("Underwriter",))
    loan_file = db.fetch("loan_files", ident)
    validate_body([])
    gate_state(loan_file, tuple(s for s in LOAN_STATUSES if s != "DENIED"))
    gate_segregation(actor, loan_file)

    tx = Tx()
    tx.watch(loan_file)
    services.points_and_fees_recompute(loan_file, tx, run_test=True)
    tx.commit()
    return respond_object(loan_file)


@bp.post("/loan-files/<ident>/atr-determination")
def run_atr_determination(ident):
    actor = authenticate(("Underwriter",))
    loan_file = db.fetch("loan_files", ident)
    validate_body([])
    gate_state(loan_file, tuple(s for s in LOAN_STATUSES if s != "DENIED"))
    gate_segregation(actor, loan_file)

    tx = Tx()
    tx.watch(loan_file)
    services.atr_determination(loan_file)
    tx.commit()
    return respond_object(loan_file)


# ---------------------------------------------------------------------------
# suspend / clear-conditions
# ---------------------------------------------------------------------------
@bp.post("/loan-files/<ident>/suspend")
def suspend_loan_file(ident):
    actor = authenticate(("Underwriter",))
    loan_file = db.fetch("loan_files", ident)
    values = validate_body([Field("suspension_reason", "str", True)])
    gate_state(loan_file, ("UNDERWRITING",))
    gate_segregation(actor, loan_file)

    tx = Tx()
    tx.watch(loan_file)
    loan_file["_suspension_reason"] = values["suspension_reason"]
    services.cascade_suspend(loan_file)
    tx.commit()
    return respond_object(loan_file)


@bp.post("/loan-files/<ident>/clear-conditions")
def clear_conditions(ident):
    actor = authenticate(("Underwriter",))
    loan_file = db.fetch("loan_files", ident)
    values = validate_body([Field("resolution_note", "str", True)])
    gate_state(loan_file, ("SUSPENDED",))
    gate_segregation(actor, loan_file)
    if int(loan_file["unresolved_overlay_breach_count"]) != 0:
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "conditions cannot be cleared while an overlay breach is unresolved")

    tx = Tx()
    tx.watch(loan_file)
    loan_file["_resolution_note"] = values["resolution_note"]
    loan_file["status"] = "UNDERWRITING"
    services.overlay_sweep(loan_file, tx)
    services.recompute_eligibility(loan_file)
    tx.commit()
    return respond_object(loan_file)


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------
def _approval_gate(actor, loan_file):
    program = services.program_of(loan_file)
    borrower = services.borrower_of(loan_file)
    doc_type = loan_file.get("doc_type")

    # priority 18
    if loan_file["points_and_fees_test_result"] == "FAIL":
        raise ApiError("ERR_HIGH_COST_LOAN_PROHIBITED",
                       "included points and fees exceed the tier cap")
    # priority 19
    if (loan_file["atr_documentation_status"] not in ("DOCUMENTED", "EXEMPT")
            or loan_file["safe_harbor_class"] == "NOT_EVALUATED"):
        raise ApiError("ERR_ATR_DOCUMENTATION_INCOMPLETE",
                       "ability-to-repay documentation is not complete")
    if doc_type != "DSCR":
        if not any(w["status"] == "ACCEPTED" for w in services.worksheets_of(loan_file)):
            raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                           "the file has no ACCEPTED income worksheet")
    # priority 20
    gate_seasoning(loan_file)
    # priorities 21 and 22
    primary_status, second_status = services.review_dimensions(loan_file)
    if second_status in ("SECOND_REQUIRED", "SECOND_ORDERED", "SECOND_RECEIVED"):
        raise ApiError("ERR_SECOND_VALUATION_REQUIRED",
                       "an accepted second appraisal is required before approval")
    if primary_status != "PRIMARY_CLEARED":
        raise ApiError("ERR_APPRAISAL_ESCALATION_UNRESOLVED",
                       "the primary appraisal review is not cleared")
    if int(loan_file["unresolved_overlay_breach_count"]) != 0:
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "the file carries an unresolved overlay breach")
    # priority 23
    gate_segregation(actor, loan_file)

    # priority 36
    dti = loan_file.get("dti_pct")
    max_dti = program.get("max_dti_pct")
    if not (doc_type == "DSCR" and dti is None) and max_dti is not None:
        if dti is None or dec(dti) > dec(max_dti):
            raise ApiError("ERR_DTI_ABOVE_PROGRAM_MAX",
                           "dti_pct is above the program maximum")
    # priority 37
    if dec(loan_file["documented_reserves_months"]) < dec(program["min_reserves_months"]):
        raise ApiError("ERR_RESERVES_INSUFFICIENT",
                       "documented_reserves_months is below the program minimum")
    # priority 38
    floor = int(program["min_residual_income_cents"])
    if doc_type != "DSCR" and floor != 0:
        if int(loan_file["residual_income_cents"]) < floor:
            raise ApiError("ERR_RESIDUAL_INCOME_INSUFFICIENT",
                           "residual_income_cents is below the program floor")
    # priority 39
    if int(borrower["fico_score"]) < int(program["min_fico"]):
        raise ApiError("ERR_FICO_BELOW_PROGRAM_MIN",
                       "fico_score is below the program minimum")
    # priority 40
    ltv = loan_file.get("ltv_pct")
    if ltv is None or dec(ltv) > dec(program["max_ltv_pct"]):
        raise ApiError("ERR_LTV_ABOVE_PROGRAM_MAX",
                       "ltv_pct is above the program maximum")
    # priority 41
    if doc_type == "DSCR" and program.get("min_dscr") is not None:
        ratio = loan_file.get("dscr_ratio")
        if ratio is None or dec(ratio) < dec(program["min_dscr"]):
            raise ApiError("ERR_DSCR_BELOW_PROGRAM_MIN",
                           "dscr_ratio is below the program minimum")


@bp.post("/loan-files/<ident>/approve")
def approve_loan_file(ident):
    actor = authenticate(("Underwriter",))
    loan_file = db.fetch("loan_files", ident)
    values = validate_body([Field("approval_note", "str")])
    gate_state(loan_file, ("UNDERWRITING",))
    _approval_gate(actor, loan_file)

    tx = Tx()
    tx.watch(loan_file)
    if "approval_note" in values:
        loan_file["_approval_note"] = values["approval_note"]
    loan_file["status"] = "APPROVED"
    services.compute_seasoning(loan_file)
    services.recompute_eligibility(loan_file)
    tx.commit()
    return respond_object(loan_file)


# ---------------------------------------------------------------------------
# deny / close
# ---------------------------------------------------------------------------
@bp.post("/loan-files/<ident>/deny")
def deny_loan_file(ident):
    actor = authenticate(("Underwriter",))
    loan_file = db.fetch("loan_files", ident)
    values = validate_body([Field("denial_reason", "str", True)])
    gate_state(loan_file, ("UNDERWRITING", "SUSPENDED"))
    gate_segregation(actor, loan_file)

    tx = Tx()
    tx.watch(loan_file)
    loan_file["_denial_reason"] = values["denial_reason"]
    loan_file["status"] = "DENIED"
    loan_file["securitization_eligible"] = False
    for pending in services.exceptions_of(loan_file):
        if pending["status"] in ("PENDING_REVIEW", "AWAITING_SECOND_SIGNATURE"):
            tx.watch(pending)
            pending["status"] = "VOIDED"
            pending["decision_reason"] = "LOAN_DENIED"
    tx.commit()
    return respond_object(loan_file)


@bp.post("/loan-files/<ident>/close")
def close_loan_file(ident):
    authenticate(("LoanOfficer",))
    loan_file = db.fetch("loan_files", ident)
    validate_body([])
    gate_state(loan_file, ("APPROVED",))
    # priority 18
    if loan_file["points_and_fees_test_result"] == "FAIL":
        raise ApiError("ERR_HIGH_COST_LOAN_PROHIBITED",
                       "included points and fees exceed the tier cap")
    # priority 24
    order = services.supporting_valuation(loan_file)
    if order is not None and services.valuation_expired(order):
        raise ApiError("ERR_VALUATION_EXPIRED",
                       "the accepted valuation is outside its 120-day validity window")
    if not loan_file["securitization_eligible"]:
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "the file is not eligible for closing")

    tx = Tx()
    tx.watch(loan_file)
    loan_file["_closing_date"] = iso_instant(db.clock)
    loan_file["status"] = "CLOSED"
    services.recompute_eligibility(loan_file)
    tx.commit()
    return respond_object(loan_file)
