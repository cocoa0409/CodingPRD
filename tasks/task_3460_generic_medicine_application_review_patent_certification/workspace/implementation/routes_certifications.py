"""Patent certifications: OCC-guarded filing and the one-way P4->P3 amend."""
from flask import Blueprint, request

from auth import ALL_ROLES, auth, own_application, require_role
from clock import today
from domain import TERMINAL_APPLICATION_STATES, award_for_app
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import certification
from state import STORE, create_entity, get, touch
from system_eval import forfeit_award, reevaluate_tentative_approvals
from validate import body, req_enum, req_int, req_str

bp = Blueprint("certifications", __name__)

CERT_TYPES = (
    "PARAGRAPH_II_EXPIRED",
    "PARAGRAPH_III_DEFER",
    "PARAGRAPH_IV_CHALLENGE",
)


@bp.post("/generic-drug-review/applications/<app_id>/patent-certifications")
def create_certification(app_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    app = get("applications", app_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    own_application(uid, app)
    b = body()
    pid = b.get("patent_id")
    if isinstance(pid, str) and get("patents", pid) is None:
        fail("ERR_LISTED_PATENT_NOT_FOUND", "Listed patent id does not exist")
    pid = req_str(b, "patent_id")
    cert_type = req_enum(b, "certification_type", CERT_TYPES)
    expected = req_int(b, "expected_application_version")
    # Priority 6 OCC, then priority 7 state.
    if expected != app["version"]:
        fail("ERR_STALE_VERSION",
             "expected_application_version does not match the application's "
             "current version")
    if app["status"] != "DRAFT":
        fail("ERR_INVALID_STATE",
             "Certifications are filed while the application is a DRAFT")
    # Priority 16 uniqueness, then priority 19 referential listing.
    for c in STORE["certifications"].values():
        if c["application_id"] == app_id and c["patent_id"] == pid:
            fail("ERR_DUPLICATE_CERTIFICATION",
                 "A certification already exists for this application and patent")
    patent = get("patents", pid)
    if patent["reference_product_id"] != app["reference_product_id"]:
        fail("ERR_PATENT_NOT_LISTED_FOR_REFERENCE_PRODUCT",
             "The patent is not listed on the application's reference product")
    ent = create_entity("certifications", {
        "application_id": app_id,
        "patent_id": pid,
        "certification_type": cert_type,
        "status": "CERTIFIED",
        "filed_date": today().isoformat(),
        "amended_date": None,
    })
    touch(app)
    return success_object(certification(ent), 201)


@bp.get("/generic-drug-review/patent-certifications/<cert_id>")
def get_certification(cert_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    ent = get("certifications", cert_id)
    if ent is None:
        fail("ERR_CERTIFICATION_NOT_FOUND", "Patent certification id does not exist")
    return success_object(certification(ent))


@bp.get("/generic-drug-review/patent-certifications")
def list_certifications():
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    items = list(STORE["certifications"].values())
    f_app = request.args.get("application_id")
    f_patent = request.args.get("patent_id")
    if f_app is not None:
        items = [c for c in items if c["application_id"] == f_app]
    if f_patent is not None:
        items = [c for c in items if c["patent_id"] == f_patent]
    return success_list([certification(c) for c in sort_default(items)])


@bp.post("/generic-drug-review/patent-certifications/<cert_id>/amend")
def amend_certification(cert_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    cert = get("certifications", cert_id)
    if cert is None:
        fail("ERR_CERTIFICATION_NOT_FOUND", "Patent certification id does not exist")
    app = get("applications", cert["application_id"])
    own_application(uid, app)
    if not (cert["status"] == "CERTIFIED"
            and cert["certification_type"] == "PARAGRAPH_IV_CHALLENGE"):
        fail("ERR_CERTIFICATION_NOT_AMENDABLE",
             "Only a CERTIFIED PARAGRAPH_IV_CHALLENGE certification may amend")
    if (app["status"] == "APPROVED"
            or app["status"] in TERMINAL_APPLICATION_STATES):
        fail("ERR_INVALID_STATE",
             "The parent application is APPROVED or in a terminal state")
    # One-way: henceforth treated as PARAGRAPH_III_DEFER (block to expiry).
    cert["status"] = "AMENDED_TO_P3"
    cert["amended_date"] = today().isoformat()
    touch(cert)
    aw = award_for_app(app["id"])
    if aw is not None and aw["status"] in ("ELIGIBLE", "AWARDED"):
        forfeit_award(aw, "CERTIFICATION_AMENDED")
    touch(app)
    reevaluate_tentative_approvals()
    return success_object(certification(cert))
