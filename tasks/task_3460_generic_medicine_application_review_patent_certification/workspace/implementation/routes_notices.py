"""Paragraph-IV notices and litigation events (PRD 3.4)."""
from flask import Blueprint

from auth import ALL_ROLES, auth, own_application, own_reference_product, require_role
from clock import add_days, add_months, parse_date, today
from domain import award_for_app, notice_for_cert
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import notice
from state import create_entity, get, touch
from system_eval import forfeit_award, reevaluate_tentative_approvals
from validate import body, req_date, req_enum

bp = Blueprint("notices", __name__)


@bp.post("/generic-drug-review/patent-certifications/<cert_id>/notices")
def create_notice(cert_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    cert = get("certifications", cert_id)
    if cert is None:
        fail("ERR_CERTIFICATION_NOT_FOUND", "Patent certification id does not exist")
    app = get("applications", cert["application_id"])
    own_application(uid, app)
    if app["status"] not in ("RECEIVED", "TENTATIVE_APPROVAL"):
        fail("ERR_INVALID_STATE",
             "A notice requires the application to be RECEIVED or "
             "TENTATIVE_APPROVAL")
    if not (cert["status"] == "CERTIFIED"
            and cert["certification_type"] == "PARAGRAPH_IV_CHALLENGE"):
        fail("ERR_INVALID_STATE",
             "A notice binds to a CERTIFIED PARAGRAPH_IV_CHALLENGE certification")
    if notice_for_cert(cert_id) is not None:
        fail("ERR_NOTICE_ALREADY_EXISTS",
             "Exactly one notice may exist per paragraph-IV certification")
    t = today()
    received = parse_date(app["received_date"])
    is_timely = (t - received).days <= 20  # day 20 inclusive
    ent = create_entity("notices", {
        "certification_id": cert_id,
        "notice_date": t.isoformat(),
        "is_timely": is_timely,
        "suit_deadline": add_days(t, 45).isoformat(),
        "suit_filed_date": None,
        "stay_until": None,
        "court_outcome": "NONE",
        "court_decision_date": None,
        "status": "NOTICE_SENT",
    })
    if not is_timely:
        aw = award_for_app(app["id"])
        if aw is not None and aw["status"] == "ELIGIBLE":
            forfeit_award(aw, "NOTICE_LATE")
    return success_object(notice(ent), 201)


@bp.get("/generic-drug-review/patent-certifications/<cert_id>/notices")
def list_notices(cert_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    if get("certifications", cert_id) is None:
        fail("ERR_CERTIFICATION_NOT_FOUND", "Patent certification id does not exist")
    items = [n for n in _all_notices() if n["certification_id"] == cert_id]
    return success_list([notice(n) for n in sort_default(items)])


@bp.post("/generic-drug-review/patent-notices/<notice_id>/litigation-events")
def litigation_event(notice_id):
    uid, role = auth()
    require_role(role, ["InnovatorSponsor", "ProgramAdmin"])
    n = get("notices", notice_id)
    if n is None:
        fail("ERR_NOTICE_NOT_FOUND", "Patent challenge notice id does not exist")
    b = body()
    event_type = req_enum(b, "event_type", ("SUIT_FILED", "COURT_DECIDED"))
    # The event selects which of the two authorized roles may act.
    if event_type == "SUIT_FILED" and role != "InnovatorSponsor":
        fail("ERR_INSUFFICIENT_PERMISSIONS",
             "SUIT_FILED events are recorded by the InnovatorSponsor")
    if event_type == "COURT_DECIDED" and role != "ProgramAdmin":
        fail("ERR_INSUFFICIENT_PERMISSIONS",
             "COURT_DECIDED events are recorded by the ProgramAdmin")
    cert = get("certifications", n["certification_id"])
    app = get("applications", cert["application_id"])
    rp = get("reference_products", app["reference_product_id"])
    if event_type == "SUIT_FILED":
        own_reference_product(uid, rp)
    event_date = req_date(b, "event_date")
    t = today()
    if event_type == "SUIT_FILED":
        if n["status"] != "NOTICE_SENT":
            fail("ERR_INVALID_STATE",
                 "A suit can only be recorded while the notice is NOTICE_SENT")
        nd = parse_date(n["notice_date"])
        sd = parse_date(n["suit_deadline"])
        if event_date < nd or event_date > sd or event_date > t:
            fail("ERR_INVALID_REQUEST",
                 "event_date must be on or after notice_date, on or before "
                 "suit_deadline (day 45 inclusive), and not in the future")
        n["suit_filed_date"] = event_date.isoformat()
        n["stay_until"] = add_months(nd, 30).isoformat()  # clamped
        n["status"] = "SUIT_FILED"
        touch(n)
    else:
        outcome = req_enum(b, "outcome",
                           ("PATENT_VALID", "PATENT_INVALID_OR_NOT_INFRINGED"))
        if n["status"] != "SUIT_FILED":
            fail("ERR_INVALID_STATE",
                 "A court decision requires the notice to be SUIT_FILED")
        if event_date < parse_date(n["suit_filed_date"]) or event_date > t:
            fail("ERR_INVALID_REQUEST",
                 "event_date must be on or after suit_filed_date and not in "
                 "the future")
        n["court_outcome"] = outcome
        n["court_decision_date"] = event_date.isoformat()
        n["status"] = ("DECIDED_VALID" if outcome == "PATENT_VALID"
                       else "DECIDED_INVALID")
        touch(n)
    reevaluate_tentative_approvals()
    return success_object(notice(n))


def _all_notices():
    from state import STORE
    return STORE["notices"].values()
