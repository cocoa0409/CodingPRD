"""The thrombolytic checklist: two state dimensions, two scores (PRD 3.5)."""
from decimal import Decimal

from flask import Blueprint

import db
import response as resp
from constants import (
    CASE_TERMINAL,
    CONTRAINDICATION_SEVERITIES,
    REQUIRED_INCLUSION_ITEM_CODES,
    REQUIRED_INCLUSION_ITEM_COUNT,
)
from errors import fail
from middleware import (
    Field,
    apply_filters,
    authenticate,
    load_path,
    load_ref,
    pagination,
    read_body,
)
from services import calculations as calc
from services import reporting

bp = Blueprint("checklists", __name__)

CREATE_SPEC = [Field("case_id", "str")]
INCLUSION_SPEC = [Field("item_code", "str", min_len=1)]
CONTRAINDICATION_SPEC = [
    Field("code", "str", min_len=1),
    Field("severity", "str", enum=CONTRAINDICATION_SEVERITIES),
    Field("documented_evidence", "str", required=False),
]
DETERMINE_SPEC = [Field("override_justification", "str", required=False, min_len=1)]
AMEND_SPEC = [Field("last_amendment_note", "str", min_len=1)]

WRITABLE_DOCUMENTATION = ("NOT_STARTED", "IN_PROGRESS", "AMENDED")


def _case_of(checklist):
    return db.get("cases", checklist["case_id"])


def _require_live_case(case):
    if case is None or case["status"] in CASE_TERMINAL:
        fail("ERR_CASE_NOT_ACTIVE", "The checklist's case is no longer active.")


def _recompute_screening(checklist):
    checklist["confirmed_inclusion_item_count"] = len(
        checklist["confirmed_inclusion_item_codes"])
    checklist["absolute_contraindication_count"] = len(
        [c for c in checklist["contraindications"] if c["severity"] == "ABSOLUTE"])
    checklist["relative_contraindication_count"] = len(
        [c for c in checklist["contraindications"] if c["severity"] == "RELATIVE"])
    checklist["screening_eligibility_score"] = calc.screening_score(
        checklist["confirmed_inclusion_item_count"],
        checklist["relative_contraindication_count"],
        checklist["absolute_contraindication_count"])


@bp.route("/checklists", methods=["POST"])
def create_checklist():
    authenticate(("EdPhysician",))
    body = read_body(CREATE_SPEC)
    case = load_ref("cases", body["case_id"])
    if case["status"] in CASE_TERMINAL:
        fail("ERR_CASE_NOT_ACTIVE", "The case is %s." % case["status"])
    if reporting.checklist_for_case(case["id"]) is not None:
        fail("ERR_DUPLICATE_CHECKLIST", "The case already carries a checklist.")
    record = {
        "case_id": case["id"],
        "documentation_status": "NOT_STARTED",
        "determination_status": "PENDING",
        "confirmed_inclusion_item_codes": [],
        "confirmed_inclusion_item_count": 0,
        "contraindications": [],
        "absolute_contraindication_count": 0,
        "relative_contraindication_count": 0,
        "amendment_count": 0,
        "screening_eligibility_score": Decimal("0.00"),
        "attested_eligibility_score": None,
        "override_justification": None,
        "determined_at": None,
        "overridden_by_neurologist_id": None,
        "last_amendment_note": None,
    }
    db.insert("checklists", record)
    return resp.object_response(record, 201)


@bp.route("/checklists/<record_id>", methods=["GET"])
def read_checklist(record_id):
    authenticate("any")
    return resp.object_response(load_path("checklists", record_id))


@bp.route("/checklists", methods=["GET"])
def list_checklists():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("checklists"), {
        "case_id": "case_id",
        "overridden_by_neurologist_id": "overridden_by_neurologist_id",
        "documentation_status": "documentation_status",
        "determination_status": "determination_status",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/checklists/<record_id>/inclusion-items", methods=["POST"])
def confirm_inclusion_item(record_id):
    authenticate(("EdPhysician",))
    record = load_path("checklists", record_id)
    body = read_body(INCLUSION_SPEC)
    _require_live_case(_case_of(record))
    if record["documentation_status"] not in WRITABLE_DOCUMENTATION:
        fail("ERR_CASE_NOT_ACTIVE",
             "No documentation write is declared from documentation_status %s."
             % record["documentation_status"])
    code = body["item_code"]
    if (code not in REQUIRED_INCLUSION_ITEM_CODES
            or code in record["confirmed_inclusion_item_codes"]):
        fail("ERR_DUPLICATE_INCLUSION_ITEM",
             "'%s' is not an unconfirmed inclusion item code." % code)
    record["confirmed_inclusion_item_codes"] = (
        record["confirmed_inclusion_item_codes"] + [code])
    _recompute_screening(record)
    if record["documentation_status"] == "NOT_STARTED":
        record["documentation_status"] = "IN_PROGRESS"
    db.touch(record)
    return resp.object_response(record)


@bp.route("/checklists/<record_id>/contraindications", methods=["POST"])
def document_contraindication(record_id):
    user_id, _role = authenticate(("EdPhysician",))
    record = load_path("checklists", record_id)
    body = read_body(CONTRAINDICATION_SPEC)
    _require_live_case(_case_of(record))
    if record["documentation_status"] not in WRITABLE_DOCUMENTATION:
        fail("ERR_CASE_NOT_ACTIVE",
             "No documentation write is declared from documentation_status %s."
             % record["documentation_status"])
    evidence = body["documented_evidence"]
    if body["severity"] == "ABSOLUTE" and not evidence:
        # Rejected before any mutation: nothing is appended and no count moves.
        fail("ERR_CONTRAINDICATION_EVIDENCE_REQUIRED",
             "An ABSOLUTE contraindication requires documented_evidence.")
    entry = {
        "code": body["code"],
        "severity": body["severity"],
        "documented_evidence": evidence,
        "recorded_by_user_id": user_id,
        "recorded_at": db.now_raw(),
    }
    record["contraindications"] = record["contraindications"] + [entry]
    _recompute_screening(record)
    if record["documentation_status"] == "NOT_STARTED":
        record["documentation_status"] = "IN_PROGRESS"
    db.touch(record)
    return resp.object_response(record, 201)


def _attesting_neurologist(checklist, user_id):
    """PRD 2.11 rule 4: the caller must own an in-session or completed consult
    on this case that carries at least one valid video session."""
    for consult in reporting.consults_for_case(checklist["case_id"]):
        if (consult["assigned_neurologist_id"] == user_id
                and consult["status"] in ("IN_SESSION", "COMPLETED")
                and consult["valid_video_session_count"] >= 1):
            neurologist = db.get("neurologists", user_id)
            if neurologist is not None:
                return neurologist
    fail("ERR_NOT_CONSULT_OWNER",
         "The caller does not own a qualifying consult on this case.")


@bp.route("/checklists/<record_id>/determine", methods=["POST"])
def determine(record_id):
    user_id, _role = authenticate(("Neurologist",))
    record = load_path("checklists", record_id)
    neurologist = _attesting_neurologist(record, user_id)
    body = read_body(DETERMINE_SPEC)
    case = _case_of(record)
    _require_live_case(case)
    if record["determination_status"] != "PENDING":
        fail("ERR_CASE_NOT_ACTIVE",
             "No determination is declared from determination_status %s."
             % record["determination_status"])
    if case["status"] not in ("CONSULT_IN_PROGRESS", "ELIGIBILITY_DETERMINED"):
        fail("ERR_CASE_NOT_ACTIVE",
             "No determination is declared from case status %s." % case["status"])
    if record["confirmed_inclusion_item_count"] != REQUIRED_INCLUSION_ITEM_COUNT:
        fail("ERR_CHECKLIST_INCOMPLETE",
             "%d of %d inclusion items are confirmed."
             % (record["confirmed_inclusion_item_count"],
                REQUIRED_INCLUSION_ITEM_COUNT))
    justification = body["override_justification"]
    relative_count = record["relative_contraindication_count"]
    if relative_count > 0 and not justification:
        fail("ERR_OVERRIDE_JUSTIFICATION_REQUIRED",
             "override_justification is required when a relative "
             "contraindication is documented.")
    if relative_count == 0 and justification:
        fail("ERR_OVERRIDE_JUSTIFICATION_REQUIRED",
             "override_justification is not accepted without a relative "
             "contraindication.")
    # The window class is re-derived first: the window penalty feeds the score.
    window = calc.window_class(case, db.now_dt())
    attested = calc.attested_score(
        record["confirmed_inclusion_item_count"], relative_count,
        record["absolute_contraindication_count"], window,
        neurologist["board_certified"])
    outcome = calc.determination_outcome(
        record["absolute_contraindication_count"], relative_count, attested,
        justification)
    record["attested_eligibility_score"] = attested
    record["determined_at"] = db.now_raw()
    record["documentation_status"] = "DOCUMENTED"
    record["determination_status"] = outcome
    if outcome == "ELIGIBLE_WITH_RELATIVE_OVERRIDE":
        record["overridden_by_neurologist_id"] = user_id
        record["override_justification"] = justification
    else:
        record["overridden_by_neurologist_id"] = None
        record["override_justification"] = None
    db.touch(record)
    case["thrombolytic_window_class"] = window
    case["status"] = "ELIGIBILITY_DETERMINED"
    case["disposition"] = "NO_TREATMENT" if outcome == "INELIGIBLE" else "PENDING"
    db.touch(case)
    return resp.object_response(record)


@bp.route("/checklists/<record_id>/amend", methods=["POST"])
def amend(record_id):
    authenticate(("EdPhysician",))
    record = load_path("checklists", record_id)
    body = read_body(AMEND_SPEC)
    case = _case_of(record)
    _require_live_case(case)
    if record["documentation_status"] != "DOCUMENTED":
        fail("ERR_CASE_NOT_ACTIVE",
             "No amendment is declared from documentation_status %s."
             % record["documentation_status"])
    if case["status"] != "ELIGIBILITY_DETERMINED":
        fail("ERR_CASE_NOT_ACTIVE",
             "No amendment is declared from case status %s." % case["status"])
    record["documentation_status"] = "AMENDED"
    record["amendment_count"] = record["amendment_count"] + 1
    record["last_amendment_note"] = body["last_amendment_note"]
    # Compensation: the verdict dimension is rewound all the way.
    record["determination_status"] = "PENDING"
    record["attested_eligibility_score"] = None
    record["determined_at"] = None
    record["overridden_by_neurologist_id"] = None
    record["override_justification"] = None
    db.touch(record)
    case["disposition"] = "PENDING"
    db.touch(case)
    return resp.object_response(record)
