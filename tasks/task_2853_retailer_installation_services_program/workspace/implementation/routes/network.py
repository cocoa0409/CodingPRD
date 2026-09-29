"""The installer network: recruitment, licences, verification, activation, removal."""
from decimal import Decimal

from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import B, E, I, S, T, auth, body, need, occ, pagination, validate
from services import calc, cascade

bp = Blueprint("network", __name__)

INSTALLER_READ = ["ProgramAdmin", "NetworkManager", "ProjectCoordinator", "ServiceManager"]
INSTALLER_READ_ONE = INSTALLER_READ + ["Installer"]

INSTALLER_CREATE = [
    S("legal_name", maxlen=160),
    S("contact_email", maxlen=320),
    E("primary_trade_code", fields.TRADE_CODES),
    I("liability_coverage_cents", minimum=0),
    T("insurance_expires_on"),
]

INSTALLER_PATCH = [
    S("contact_email", required=False, maxlen=320),
    I("liability_coverage_cents", required=False, minimum=0),
    T("insurance_expires_on", required=False),
]

CREDENTIAL_CREATE = [
    S("jurisdiction_id"),
    E("trade_code", fields.TRADE_CODES),
    S("license_number", maxlen=40),
    T("license_expires_on"),
    B("permit_pulling_authorized", required=False),
]

VERIFY_DECISION = [
    E("verification_decision", fields.VERIFICATION_DECISIONS),
    S("rejection_reason", required=False, maxlen=300),
]

BACKGROUND_CHECK = [
    E("result", fields.BACKGROUND_RESULTS),
    T("completed_at"),
]

REMOVE = [S("removal_reason", maxlen=300)]

EVENT_CREATE = [
    E("event_type", fields.EVENT_TYPES),
    T("occurred_at"),
    S("project_id", required=False),
    I("csat_score", required=False, minimum=1, maximum=5),
]


def _not_removed(installer):
    """Rank 13: REMOVED is terminal for the Installer machine."""
    if installer["status"] == "REMOVED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _recompute_credential_count(installer):
    installer["verified_credential_count"] = len([
        c for c in store.all_rows("installer_credentials")
        if c["installer_id"] == installer["id"] and c["verification_status"] == "VERIFIED"
    ])
    return installer["verified_credential_count"]


def promote_if_pair_complete(installer):
    """DOCS_PENDING -> VERIFIED, evaluated at the end of both promoting handlers."""
    if installer["status"] != "DOCS_PENDING":
        return False
    if installer["verified_credential_count"] < 1:
        return False
    if installer["background_check_result"] != "PASS":
        return False
    matching = [
        c for c in store.all_rows("installer_credentials")
        if c["installer_id"] == installer["id"]
        and c["verification_status"] == "VERIFIED"
        and c["trade_code"] == installer["primary_trade_code"]
    ]
    if not matching:
        return False
    installer["status"] = "VERIFIED"
    return True


@bp.post("/installers")
def create_installer():
    auth(["NetworkManager"])
    data = validate(body(), INSTALLER_CREATE)
    row = {
        "legal_name": data["legal_name"],
        "contact_email": data["contact_email"],
        "primary_trade_code": data["primary_trade_code"],
        "liability_coverage_cents": data["liability_coverage_cents"],
        "insurance_expires_on": data["insurance_expires_on"],
        "status": "APPLIED",
        "background_check_completed_at": None,
        "background_check_result": "NONE",
        "committed_minutes": 0,
        "verified_credential_count": 0,
        "rolling_event_count": 0,
        "rolling_no_show_count": 0,
        "completed_project_count": 0,
        "quality_score": Decimal("85.00"),
        "timeliness_score": Decimal("85.00"),
        "satisfaction_score": Decimal("85.00"),
        "composite_score": Decimal("85.00"),
        "lifetime_composite_score": Decimal("85.00"),
        "removal_eligible": False,
        "probation_started_at": None,
        "removed_at": None,
        "removal_reason": None,
    }
    store.insert("installers", row)
    return envelope.obj(row, 201)


@bp.get("/installers")
def list_installers():
    auth(INSTALLER_READ)
    limit, offset = pagination()
    rows = store.all_rows("installers")
    rows = fields.filter_eq(rows, "status", fields.arg("status"))
    rows = fields.filter_eq(rows, "primary_trade_code", fields.arg("primary_trade_code"))
    rows = fields.filter_bool(rows, "removal_eligible", fields.arg("removal_eligible"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/installers/<row_id>")
def get_installer(row_id):
    auth(INSTALLER_READ_ONE)
    return envelope.obj(need("installers", row_id))


@bp.patch("/installers/<row_id>")
def patch_installer(row_id):
    auth(["NetworkManager"])
    data = validate(body(), INSTALLER_PATCH)
    row = need("installers", row_id)
    for spec in INSTALLER_PATCH:
        if spec.name in data:
            row[spec.name] = data[spec.name]
    store.touch(row)
    return envelope.obj(row)


@bp.post("/installers/<row_id>/credentials")
def create_credential(row_id):
    auth(["NetworkManager"])
    data = validate(body(), CREDENTIAL_CREATE)
    installer = need("installers", row_id)
    need("jurisdictions", data["jurisdiction_id"])
    for existing in store.all_rows("installer_credentials"):
        if (existing["installer_id"] == installer["id"]
                and existing["jurisdiction_id"] == data["jurisdiction_id"]
                and existing["trade_code"] == data["trade_code"]
                and existing["verification_status"] != "REJECTED"):
            raise ApiError("ERR_DUPLICATE_CODE")
    _not_removed(installer)
    first = not any(c["installer_id"] == installer["id"]
                    for c in store.all_rows("installer_credentials"))
    row = {
        "installer_id": installer["id"],
        "jurisdiction_id": data["jurisdiction_id"],
        "trade_code": data["trade_code"],
        "license_number": data["license_number"],
        "license_expires_on": data["license_expires_on"],
        "permit_pulling_authorized": data.get("permit_pulling_authorized", False),
        "verification_status": "PENDING",
        "verified_at": None,
        "rejection_reason": None,
    }
    store.insert("installer_credentials", row)
    if first and installer["status"] == "APPLIED":
        installer["status"] = "DOCS_PENDING"
        store.touch(installer)
    return envelope.obj(row, 201)


@bp.get("/installers/<row_id>/credentials")
def list_installer_credentials(row_id):
    auth(INSTALLER_READ_ONE)
    limit, offset = pagination()
    installer = need("installers", row_id)
    rows = [c for c in store.all_rows("installer_credentials")
            if c["installer_id"] == installer["id"]]
    rows = fields.filter_eq(rows, "verification_status", fields.arg("verification_status"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/installer-credentials")
def list_credentials():
    auth(INSTALLER_READ)
    limit, offset = pagination()
    rows = store.all_rows("installer_credentials")
    rows = fields.filter_eq(rows, "installer_id", fields.arg("installer_id"))
    rows = fields.filter_eq(rows, "jurisdiction_id", fields.arg("jurisdiction_id"))
    rows = fields.filter_eq(rows, "trade_code", fields.arg("trade_code"))
    rows = fields.filter_eq(rows, "verification_status", fields.arg("verification_status"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/installer-credentials/<row_id>")
def get_credential(row_id):
    auth(INSTALLER_READ_ONE)
    return envelope.obj(need("installer_credentials", row_id))


@bp.post("/installer-credentials/<row_id>/verify")
def verify_credential(row_id):
    auth(["NetworkManager"])
    data = validate(body(), VERIFY_DECISION)
    credential = need("installer_credentials", row_id)
    installer = store.get("installers", credential["installer_id"])
    decision = data["verification_decision"]

    if decision == "VERIFY":
        if (credential["verification_status"] != "PENDING"
                or credential["license_expires_on"] <= store.now()):
            raise ApiError("ERR_INVALID_STATE")
        credential["verification_status"] = "VERIFIED"
        credential["verified_at"] = store.now()
        store.touch(credential)
        if installer is not None:
            count = _recompute_credential_count(installer)
            changed = promote_if_pair_complete(installer)
            if (not changed and installer["status"] == "SUSPENDED" and count >= 1
                    and installer["insurance_expires_on"] > store.now()):
                installer["status"] = "ACTIVE"
                installer["probation_started_at"] = None
                changed = True
            if changed:
                store.touch(installer)
    else:
        if credential["verification_status"] not in ("PENDING", "VERIFIED"):
            raise ApiError("ERR_INVALID_STATE")
        credential["verification_status"] = "REJECTED"
        credential["rejection_reason"] = data.get("rejection_reason")
        credential["verified_at"] = credential["verified_at"]
        store.touch(credential)
        if installer is not None:
            _recompute_credential_count(installer)
            if cascade.suspend_if_unlicensed(installer):
                store.touch(installer)
    return envelope.obj(credential)


@bp.post("/installers/<row_id>/background-check")
def background_check(row_id):
    auth(["NetworkManager"])
    data = validate(body(), BACKGROUND_CHECK)
    installer = need("installers", row_id)
    _not_removed(installer)
    installer["background_check_result"] = data["result"]
    installer["background_check_completed_at"] = data["completed_at"]
    promote_if_pair_complete(installer)
    store.touch(installer)
    return envelope.obj(installer)


@bp.post("/installers/<row_id>/activate")
def activate_installer(row_id):
    auth(["NetworkManager"])
    installer = need("installers", row_id)
    _not_removed(installer)
    if (installer["status"] != "VERIFIED"
            or installer["insurance_expires_on"] <= store.now()
            or installer["background_check_result"] != "PASS"):
        raise ApiError("ERR_INVALID_STATE")
    installer["status"] = "ACTIVE"
    calc.rescore(installer)
    store.touch(installer)
    return envelope.obj(installer)


@bp.post("/installers/<row_id>/remove")
def remove_installer(row_id):
    auth(["ServiceManager"])
    payload = body()
    data = validate(payload, REMOVE)
    installer = need("installers", row_id)
    expected = occ(payload, "expected_installer_version")
    if expected != installer["version"]:
        raise ApiError("ERR_STALE_INSTALLER_VERSION")
    _not_removed(installer)
    if installer["status"] not in ("ACTIVE", "PROBATION", "SUSPENDED"):
        raise ApiError("ERR_REMOVAL_NOT_ELIGIBLE")
    if not installer["removal_eligible"]:
        raise ApiError("ERR_REMOVAL_NOT_ELIGIBLE")
    if any(a["status"] == "IN_PROGRESS" for a in calc.installer_assignments(installer["id"])):
        raise ApiError("ERR_REMOVAL_NOT_ELIGIBLE")
    cascade.remove_installer(installer, data["removal_reason"])
    store.touch(installer)
    return envelope.obj(installer)


@bp.post("/installers/<row_id>/scorecard-events")
def create_scorecard_event(row_id):
    auth(["ServiceManager", "ProjectCoordinator"])
    data = validate(body(), EVENT_CREATE)
    if data["event_type"] == "CSAT_SURVEY":
        if data.get("csat_score") is None:
            raise ApiError("ERR_INVALID_FIELD_TYPE",
                           "csat_score is required when event_type is CSAT_SURVEY.")
    elif data.get("csat_score") is not None:
        raise ApiError("ERR_INVALID_FIELD_TYPE",
                       "csat_score is forbidden unless event_type is CSAT_SURVEY.")
    installer = need("installers", row_id)
    project_id = data.get("project_id")
    if project_id is not None:
        need("projects", project_id)
    _not_removed(installer)
    event = cascade.append_event(
        installer, data["event_type"], data["occurred_at"], "MANUAL",
        project_id=project_id, csat_score=data.get("csat_score"))
    cascade.rescore_and_touch(installer)
    return envelope.obj(event, 201)


@bp.get("/installers/<row_id>/scorecard-events")
def list_installer_events(row_id):
    auth(INSTALLER_READ_ONE)
    limit, offset = pagination()
    installer = need("installers", row_id)
    rows = [e for e in store.all_rows("scorecard_events")
            if e["installer_id"] == installer["id"]]
    rows = fields.filter_eq(rows, "event_type", fields.arg("event_type"))
    rows = fields.filter_eq(rows, "source", fields.arg("source"))
    return envelope.collection(envelope.order_scorecard_events(rows), limit, offset)


@bp.get("/installers/<row_id>/scorecard")
def get_scorecard(row_id):
    auth(INSTALLER_READ_ONE)
    installer = need("installers", row_id)
    report = calc.compute_scores(installer["id"])
    return envelope.raw({
        "rolling_quality_score": report["rolling_quality_score"],
        "rolling_timeliness_score": report["rolling_timeliness_score"],
        "rolling_satisfaction_score": report["rolling_satisfaction_score"],
        "rolling_composite_score": report["rolling_composite_score"],
        "rolling_event_count": report["rolling_event_count"],
        "rolling_no_show_count": report["rolling_no_show_count"],
        "lifetime_quality_score": report["lifetime_quality_score"],
        "lifetime_timeliness_score": report["lifetime_timeliness_score"],
        "lifetime_satisfaction_score": report["lifetime_satisfaction_score"],
        "lifetime_composite_score": report["lifetime_composite_score"],
        "lifetime_event_count": report["lifetime_event_count"],
        "removal_eligible": report["removal_eligible"],
        "probation_active": installer["status"] == "PROBATION",
    })
