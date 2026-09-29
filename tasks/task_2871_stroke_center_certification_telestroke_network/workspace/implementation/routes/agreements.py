"""Hub-to-spoke coverage agreements and credentialing by proxy (PRD 3.1)."""
from flask import Blueprint

import db
import response as resp
from constants import AGREEMENT_STATUSES, COVERAGE_TIERS, PRIVILEGE_SCOPES
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
from services import derive

bp = Blueprint("agreements", __name__)

CREATE_SPEC = [
    Field("hub_center_id", "str"),
    Field("spoke_center_id", "str"),
    Field("coverage_tier", "str", enum=COVERAGE_TIERS),
    Field("max_concurrent_consults", "int", minimum=1, maximum=20),
    Field("effective_from", "dt"),
    Field("effective_until", "dt"),
]

SUSPEND_SPEC = [Field("suspension_reason", "str", min_len=1)]

GRANT_SPEC = [
    Field("neurologist_id", "str"),
    Field("privilege_scope", "str", enum=PRIVILEGE_SCOPES),
    Field("expires_at", "dt"),
]


@bp.route("/spoke-agreements", methods=["POST"])
def create_agreement():
    authenticate(("ProgramCoordinator",))
    body = read_body(CREATE_SPEC)
    hub = load_ref("centers", body["hub_center_id"])
    spoke = load_ref("centers", body["spoke_center_id"])
    if hub["id"] == spoke["id"] or hub["facility_type"] != "HUB_PRIMARY":
        fail("ERR_SPOKE_AGREEMENT_SELF_PAIR",
             "An agreement binds one HUB_PRIMARY hub to a different spoke facility.")
    if not db.parse_iso(body["effective_from"]) < db.parse_iso(body["effective_until"]):
        fail("ERR_INVALID_PERIOD_RANGE",
             "effective_from must be strictly earlier than effective_until.")
    record = {
        "hub_center_id": hub["id"],
        "spoke_center_id": spoke["id"],
        "coverage_tier": body["coverage_tier"],
        "max_concurrent_consults": body["max_concurrent_consults"],
        "effective_from": body["effective_from"],
        "effective_until": body["effective_until"],
        "status": "DRAFT",
        "proxy_credentials": [],
        "active_consult_count": 0,
        "suspension_reason": None,
    }
    db.insert("agreements", record)
    return resp.object_response(record, 201)


@bp.route("/spoke-agreements/<record_id>", methods=["GET"])
def read_agreement(record_id):
    authenticate("any")
    return resp.object_response(load_path("agreements", record_id))


@bp.route("/spoke-agreements", methods=["GET"])
def list_agreements():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("agreements"), {
        "hub_center_id": "hub_center_id",
        "spoke_center_id": "spoke_center_id",
        "status": "status",
        "coverage_tier": "coverage_tier",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/spoke-agreements/<record_id>/activate", methods=["POST"])
def activate_agreement(record_id):
    authenticate(("ProgramCoordinator",))
    record = load_path("agreements", record_id)
    read_body([])
    if record["status"] not in ("DRAFT", "SUSPENDED"):
        fail("ERR_INVALID_AGREEMENT_STATE",
             "An agreement in %s cannot be activated." % record["status"])
    hub = db.get("centers", record["hub_center_id"])
    if hub is None or hub["certification_status"] in ("SUSPENDED", "WITHDRAWN"):
        fail("ERR_INVALID_AGREEMENT_STATE",
             "The hub facility's certification does not permit activation.")
    if not db.now_dt() < db.parse_iso(record["effective_until"]):
        fail("ERR_INVALID_AGREEMENT_STATE",
             "The agreement's coverage window has already closed.")
    if record["status"] == "DRAFT":
        spoke = db.get("centers", record["spoke_center_id"])
        if spoke is None or spoke["certification_status"] == "WITHDRAWN":
            fail("ERR_INVALID_AGREEMENT_STATE",
                 "The spoke facility has been withdrawn from the network.")
    record["status"] = "ACTIVE"
    record["suspension_reason"] = None
    db.touch(record)
    return resp.object_response(record)


@bp.route("/spoke-agreements/<record_id>/suspend", methods=["POST"])
def suspend_agreement(record_id):
    authenticate(("ProgramCoordinator", "CertificationReviewer"))
    record = load_path("agreements", record_id)
    body = read_body(SUSPEND_SPEC)
    if record["status"] != "ACTIVE":
        fail("ERR_INVALID_AGREEMENT_STATE",
             "Only an ACTIVE agreement can be suspended.")
    derive.suspend_agreement_cascade(record, body["suspension_reason"],
                                    "agreement suspended")
    return resp.object_response(record)


@bp.route("/spoke-agreements/<record_id>/proxy-credentials", methods=["POST"])
def grant_proxy_credential(record_id):
    authenticate(("ProgramCoordinator",))
    record = load_path("agreements", record_id)
    body = read_body(GRANT_SPEC)
    neurologist = load_ref("neurologists", body["neurologist_id"])
    if neurologist["home_center_id"] != record["hub_center_id"]:
        fail("ERR_PROXY_CREDENTIAL_INVALID",
             "The neurologist is not employed by this agreement's hub facility.")
    for grant in record["proxy_credentials"]:
        if (grant["neurologist_id"] == neurologist["id"]
                and grant["privilege_scope"] == body["privilege_scope"]
                and grant["status"] == "GRANTED"):
            fail("ERR_PROXY_CREDENTIAL_INVALID",
                 "A GRANTED credential already exists for that scope.")
    record["proxy_credentials"].append({
        "neurologist_id": neurologist["id"],
        "privilege_scope": body["privilege_scope"],
        "expires_at": body["expires_at"],
        "status": "GRANTED",
        "granted_at": db.now_raw(),
    })
    db.touch(record)
    return resp.object_response(record, 201)
