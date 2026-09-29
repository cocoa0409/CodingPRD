"""Borrowers and credit events."""
from flask import Blueprint

from core import (Field, authenticate, ordered, paginate, raw_body, require_range,
                  respond_collection, respond_created, respond_object, validate_body)
from store import Tx, db, resolve_fk
import services

bp = Blueprint("borrowers", __name__)

EVENT_TYPES = ("FORECLOSURE", "SHORT_SALE", "DEED_IN_LIEU", "BK_CH7", "BK_CH13",
               "MODIFICATION", "MORTGAGE_LATE_60")

BORROWER_READERS = ("LoanOfficer", "Underwriter", "CreditCommittee", "ChiefCreditOfficer",
                    "PostCloseAuditor")

BORROWER_FIELDS = [
    Field("legal_name", "str", True),
    Field("fico_score", "int", True),
    Field("self_employed_flag", "bool"),
    Field("entity_ownership_pct", "num", scale=2),
    Field("monthly_debt_obligations_cents", "int", True),
    Field("verified_liquid_assets_cents", "int", True),
    Field("age_years", "int", True),
]

CREDIT_EVENT_FIELDS = [
    Field("borrower_id", "str", True),
    Field("event_type", "enum", True, EVENT_TYPES),
    Field("completion_date", "datetime", True),
    Field("documented_flag", "bool"),
]


@bp.post("/borrowers")
def create_borrower():
    authenticate(("LoanOfficer",))
    values = validate_body(BORROWER_FIELDS)
    require_range(300 <= values["fico_score"] <= 850, "fico_score must be within 300..850")
    require_range(values["monthly_debt_obligations_cents"] >= 0,
                  "monthly_debt_obligations_cents must not be negative")
    require_range(values["verified_liquid_assets_cents"] >= 0,
                  "verified_liquid_assets_cents must not be negative")
    require_range(18 <= values["age_years"] <= 120, "age_years must be within 18..120")
    ownership = values.get("entity_ownership_pct")
    if ownership is not None:
        require_range(0 < ownership <= 100,
                      "entity_ownership_pct must be within 0.01..100.00")
    row = db.insert("borrowers", {
        "legal_name": values["legal_name"],
        "fico_score": values["fico_score"],
        "self_employed_flag": values.get("self_employed_flag", False),
        "entity_ownership_pct": ownership if ownership is not None else __import__(
            "decimal").Decimal("100.00"),
        "monthly_debt_obligations_cents": values["monthly_debt_obligations_cents"],
        "verified_liquid_assets_cents": values["verified_liquid_assets_cents"],
        "age_years": values["age_years"],
        "credit_event_count": 0,
    })
    return respond_created(row)


@bp.get("/borrowers/<ident>")
def read_borrower(ident):
    authenticate(BORROWER_READERS)
    return respond_object(db.fetch("borrowers", ident))


@bp.post("/credit-events")
def create_credit_event():
    authenticate(("LoanOfficer", "Underwriter"))
    raw = raw_body()
    borrower = resolve_fk(raw, "borrower_id", "borrowers")
    values = validate_body(CREDIT_EVENT_FIELDS)
    completion = values["completion_date"]
    require_range(completion <= db.clock, "completion_date must not be in the future")

    tx = Tx()
    row = db.insert("credit_events", {
        "borrower_id": borrower["id"],
        "event_type": values["event_type"],
        "completion_date": __import__("core").iso_instant(completion),
        "documented_flag": values.get("documented_flag", True),
    }, versioned=False)
    tx.watch(borrower)
    borrower["credit_event_count"] = len(services.credit_events_of(borrower["id"]))
    for loan_file in db.rows("loan_files"):
        if loan_file["borrower_id"] != borrower["id"] or loan_file["status"] == "DENIED":
            continue
        tx.watch(loan_file)
        services.compute_seasoning(loan_file)
        services.recompute_eligibility(loan_file)
    tx.commit()
    return respond_created(row)


@bp.get("/borrowers/<ident>/credit-events")
def list_credit_events(ident):
    authenticate(BORROWER_READERS)
    borrower = db.fetch("borrowers", ident)
    rows = [e for e in db.rows("credit_events") if e["borrower_id"] == borrower["id"]]
    event_type = __import__("flask").request.args.get("event_type")
    if event_type:
        rows = [e for e in rows if e["event_type"] == event_type]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)
