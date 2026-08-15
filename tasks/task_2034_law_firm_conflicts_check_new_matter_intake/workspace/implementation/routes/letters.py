"""Engagement letter endpoints (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import stamp_new, bump, now_iso, parse_ts
from errors import (
    ApiError, invalid, forbidden,
    ERR_NOT_RESPONSIBLE_ATTORNEY, ERR_MATTER_NOT_INTAKE,
    ERR_LETTER_INVALID_STATE, ERR_LETTER_STALE,
    ERR_MATTER_CLEARANCE_BLOCKED, ERR_CREDIT_MISSING, ERR_CREDIT_STALE,
    ERR_RETAINER_UNFUNDED,
)
from middleware import caller, admit, admit_action, body
from response import ok_object, paginate, sort_by_created
from services import money
from services.cascades import stand_up_deposit, countersign as do_countersign
from services.validate import (
    resolve, check_occ, require_occ, is_int, is_number,
)

bp = Blueprint("letters", __name__)

STAFF = ("FirmAdmin", "IntakeSpecialist", "ResponsibleAttorney",
         "ConflictsPartner", "BillingClerk")
LETTER_STALE_DAYS = 30


def _validate_fee_lines(fee_lines):
    if not isinstance(fee_lines, list) or len(fee_lines) < 1:
        raise invalid("fee_lines must contain at least one line")
    for line in fee_lines:
        if not isinstance(line, dict):
            raise invalid("each fee line must be an object")
        if not isinstance(line.get("description"), str):
            raise invalid("each fee line requires a description")
        if not is_number(line.get("hours")) or line["hours"] <= 0:
            raise invalid("fee line hours must be a number greater than zero")
        if not is_int(line.get("rate_cents")) or line["rate_cents"] <= 0:
            raise invalid("fee line rate_cents must be an integer greater "
                          "than zero")


@bp.post("/intake/matters/<mid>/engagement-letters")
def create_letter(mid):
    _, role = caller()
    admit(role, ("ResponsibleAttorney", "IntakeSpecialist"))
    matter = resolve(db.store.matters, mid)
    data = body()

    # Tier 6: letter creation requires an INTAKE matter; then OCC.
    if matter["lifecycle_status"] != "INTAKE":
        raise ApiError(ERR_MATTER_NOT_INTAKE, 409,
                       "Engagement letters are drafted against INTAKE matters")
    check_occ(data, matter)

    # Tier 12: request shape.
    require_occ(data)
    scope_text = data.get("scope_text")
    if not isinstance(scope_text, str) or scope_text == "":
        raise invalid("scope_text is required")
    fee_lines = data.get("fee_lines")
    _validate_fee_lines(fee_lines)

    # Supersede any existing DRAFT/ISSUED letter of the matter.
    for letter in db.store.engagement_letters.values():
        if (letter["matter_id"] == matter["id"]
                and letter["status"] in ("DRAFT", "ISSUED")):
            letter["status"] = "SUPERSEDED"
            bump(letter)

    letter = stamp_new({
        "matter_id": matter["id"],
        "scope_text": scope_text,
        "fee_lines": [
            {"description": l["description"], "hours": l["hours"],
             "rate_cents": l["rate_cents"]}
            for l in fee_lines
        ],
        "fee_estimate_cents": money.fee_estimate_cents(fee_lines),
        "status": "DRAFT",
        "issued_at": None,
        "countersigned_at": None,
    })
    db.store.engagement_letters[letter["id"]] = letter
    bump(matter)
    return ok_object(letter, 201)


@bp.get("/intake/matters/<mid>/engagement-letters")
def list_letters(mid):
    user_id, role = caller()
    admit(role, STAFF + ("Client",))
    matter = resolve(db.store.matters, mid)
    # Tier 5 ownership: a Client sees only letters of its own matters.
    if role == "Client" and user_id != matter["client_party_id"]:
        raise forbidden("Client may read only its own matters' letters")
    rows = [l for l in db.store.engagement_letters.values()
            if l["matter_id"] == mid]
    return paginate(sort_by_created(rows), request.args)


@bp.post("/intake/engagement-letters/<lid>/transition")
def letter_transition(lid):
    user_id, role = caller()
    admit(role, ("ResponsibleAttorney", "Client", "ConflictsPartner"))
    data = body()
    action = data.get("action")

    # Tier 2 per-action role rules.
    if action == "ISSUE":
        admit_action(role, ("ResponsibleAttorney",))
    elif action == "COUNTERSIGN":
        admit_action(role, ("Client",))
    elif action == "VOID":
        admit_action(role, ("ConflictsPartner",))

    # Tier 3: path resolution.
    letter = resolve(db.store.engagement_letters, lid)
    matter = db.store.matters.get(letter["matter_id"])

    if action == "ISSUE":
        # Tier 5 ownership: caller must be the matter's responsible attorney.
        if matter is None or user_id != matter["responsible_attorney_id"]:
            raise ApiError(ERR_NOT_RESPONSIBLE_ATTORNEY, 403,
                           "Only the matter's responsible attorney may issue "
                           "its letter")
        # Tier 6: letter DRAFT, then matter still INTAKE.
        if letter["status"] != "DRAFT":
            raise ApiError(ERR_LETTER_INVALID_STATE, 409,
                           "ISSUE requires a DRAFT letter")
        if matter["lifecycle_status"] != "INTAKE":
            raise ApiError(ERR_MATTER_NOT_INTAKE, 409,
                           "ISSUE requires the matter to be INTAKE")
        letter["status"] = "ISSUED"
        letter["issued_at"] = now_iso()
        bump(letter)
        # Money side: create (first ISSUE) or recompute the deposit.
        stand_up_deposit(matter)
        return ok_object(letter)

    if action == "COUNTERSIGN":
        # Tier 5 ownership: caller must be the owning client.
        if matter is None or user_id != matter["client_party_id"]:
            raise forbidden("Only the matter's client may countersign")
        # Tier 6 state.
        if letter["status"] != "ISSUED":
            raise ApiError(ERR_LETTER_INVALID_STATE, 409,
                           "COUNTERSIGN requires an ISSUED letter")
        # Tier 7 business safety: clearance must be CLEARED or WAIVED.
        if matter["clearance_status"] not in ("CLEARED", "WAIVED"):
            raise ApiError(ERR_MATTER_CLEARANCE_BLOCKED, 422,
                           "Matter clearance is not CLEARED or WAIVED")
        # Tier 8 temporal: strict staleness -- exactly 30 days is still
        # countersignable.
        if db.now() > parse_ts(letter["issued_at"]) + timedelta(days=LETTER_STALE_DAYS):
            raise ApiError(ERR_LETTER_STALE, 422,
                           "Letter is stale (issued_at + 30 days has passed)")
        # Tier 11 fiscal gates, in order.
        assessments = [a for a in db.store.credit_assessments.values()
                       if a["matter_id"] == matter["id"]]
        if not assessments:
            raise ApiError(ERR_CREDIT_MISSING, 422,
                           "No credit assessment exists for the matter")
        # Latest by assessed_at; tie on assessed_at broken by later
        # created_at (insertion order as final stable tiebreak).
        latest = None
        latest_key = None
        for a in assessments:
            key = (parse_ts(a["assessed_at"]), a["created_at"])
            if latest is None or key >= latest_key:
                latest = a
                latest_key = key
        if not money.assessment_valid(latest):
            raise ApiError(ERR_CREDIT_STALE, 422,
                           "The latest credit assessment is stale")
        deposit = money.deposit_for_matter(matter["id"])
        if deposit is None or deposit["status"] != "FUNDED":
            raise ApiError(ERR_RETAINER_UNFUNDED, 422,
                           "Retainer deposit is not FUNDED")
        do_countersign(letter, matter)
        return ok_object(letter)

    if action == "VOID":
        # Tier 6: only DRAFT or ISSUED letters may be voided.
        if letter["status"] not in ("DRAFT", "ISSUED"):
            raise ApiError(ERR_LETTER_INVALID_STATE, 409,
                           "Only a DRAFT or ISSUED letter may be voided")
        letter["status"] = "VOID"
        bump(letter)
        return ok_object(letter)

    raise invalid("action must be ISSUE, COUNTERSIGN, or VOID")
