"""Software packages and update deliveries, including the consent-minting
delivery creation and the consent-preserving retry loop (PRD section 3.6)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import (
    as_bool,
    as_enum,
    as_int,
    as_str,
    body_json,
    caller,
    get_or_404,
    list_resources,
    need,
    require_role,
    access_denied,
)
from constants import CONSENT_TTL_HOURS
from db import STORES, now
from domain import (
    cascade_package_withdrawn,
    new_record,
    serialize,
    touch,
)
from envelope import created, ok, ok_list
from errors import (
    ERR_DELIVERY_ALREADY_PENDING,
    ERR_INVALID_REQUEST,
    ERR_MACHINE_NOT_ACTIVATED,
    ERR_MACHINE_POSTURE_BLOCKED,
    ERR_PACKAGE_MODEL_MISMATCH,
    ERR_PACKAGE_NOT_PUBLISHED,
    ApiError,
    invalid_state,
)

bp = Blueprint("updates", __name__)

TERMINAL_DELIVERY_STATES = {"INSTALLED", "DECLINED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Software packages
# ---------------------------------------------------------------------------

@bp.post("/software-packages")
def create_package():
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    package_code = as_str(need(b, "package_code"), "package_code")
    target_model_code = as_str(need(b, "target_model_code"), "target_model_code")
    firmware_version = as_str(need(b, "firmware_version"), "firmware_version")
    size_mb = as_int(need(b, "size_mb"), "size_mb")
    mandatory = as_bool(need(b, "mandatory"), "mandatory")
    for p in STORES["software_packages"].values():
        if p["package_code"] == package_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "package_code must be unique")
    rec = new_record(
        {
            "package_code": package_code,
            "target_model_code": target_model_code,
            "firmware_version": firmware_version,
            "size_mb": size_mb,
            "mandatory": mandatory,
            "status": "DRAFT",
        }
    )
    STORES["software_packages"][rec["id"]] = rec
    return created(serialize(rec))


@bp.get("/software-packages/<pid>")
def get_package(pid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "GrowerManager"})
    p = get_or_404("software_packages", pid, "software package")
    return ok(serialize(p))


@bp.post("/software-packages/<pid>/publish")
def publish_package(pid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    p = get_or_404("software_packages", pid, "software package")
    if p["status"] != "DRAFT":
        raise invalid_state("package is not DRAFT")
    p["status"] = "PUBLISHED"
    touch(p)
    return ok(serialize(p))


@bp.post("/software-packages/<pid>/withdraw")
def withdraw_package(pid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    p = get_or_404("software_packages", pid, "software package")
    if p["status"] != "PUBLISHED":
        raise invalid_state("package is not PUBLISHED")
    p["status"] = "WITHDRAWN"
    touch(p)
    cascade_package_withdrawn(p)
    return ok(serialize(p))


# ---------------------------------------------------------------------------
# Update deliveries
# ---------------------------------------------------------------------------

@bp.post("/update-deliveries")
def create_delivery():
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    machine_id = as_str(need(b, "machine_id"), "machine_id")
    package_id = as_str(need(b, "package_id"), "package_id")
    machine = get_or_404("machines", machine_id, "machine")
    pkg = get_or_404("software_packages", package_id, "software package")
    # State gates (priority 6), listed order
    if pkg["status"] != "PUBLISHED":
        raise ApiError(ERR_PACKAGE_NOT_PUBLISHED, 409, "package is not PUBLISHED")
    if machine["lifecycle_status"] not in ("ACTIVATED", "IN_SERVICE"):
        raise ApiError(ERR_MACHINE_NOT_ACTIVATED, 409, "machine is not ACTIVATED or IN_SERVICE")
    # Capacity gates (priority 8)
    if pkg["target_model_code"] != machine["model_code"]:
        raise ApiError(
            ERR_PACKAGE_MODEL_MISMATCH, 409, "package targets a different model_code"
        )
    for d in STORES["update_deliveries"].values():
        if (
            d["machine_id"] == machine_id
            and d["package_id"] == package_id
            and d["status"] not in TERMINAL_DELIVERY_STATES
        ):
            raise ApiError(
                ERR_DELIVERY_ALREADY_PENDING,
                409,
                "a non-terminal delivery already exists for this machine and package",
            )
    # Creation mints the bound SOFTWARE_UPDATE consent ticket (requester
    # 'platform') in REQUESTED and links both directions.
    delivery = new_record(
        {
            "machine_id": machine_id,
            "package_id": package_id,
            "consent_ticket_id": None,
            "status": "AWAITING_CONSENT",
            "download_attempts": 0,
            "failure_reason": None,
            "installed_at": None,
        }
    )
    ticket = new_record(
        {
            "organization_id": machine["organization_id"],
            "machine_id": machine_id,
            "ticket_type": "SOFTWARE_UPDATE",
            "requester_ref_id": "platform",
            "status": "REQUESTED",
            "expires_at": now() + timedelta(hours=CONSENT_TTL_HOURS),
            "granted_at": None,
            "bound_session_id": None,
            "bound_delivery_id": delivery["id"],
        }
    )
    delivery["consent_ticket_id"] = ticket["id"]
    STORES["update_deliveries"][delivery["id"]] = delivery
    STORES["consent_tickets"][ticket["id"]] = ticket
    return created(serialize(delivery))


def _delivery_org(delivery):
    m = STORES["machines"].get(delivery["machine_id"])
    return m["organization_id"] if m is not None else None


@bp.get("/update-deliveries/<did>")
def get_delivery(did):
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "GrowerManager"})
    d = get_or_404("update_deliveries", did, "update delivery")
    if role == "GrowerManager" and uid != _delivery_org(d):
        raise access_denied("delivery belongs to another organization")
    return ok(serialize(d))


@bp.get("/update-deliveries")
def list_deliveries():
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "GrowerManager"})
    filters = []
    for f in ("machine_id", "package_id", "consent_ticket_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "PlatformAdmin":
        visible = lambda r: True
    else:
        visible = lambda r: _delivery_org(r) == uid
    page, total, limit, offset = list_resources("update_deliveries", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/update-deliveries/<did>/start-download")
def start_download(did):
    uid, role = caller()
    require_role(role, {"System"})
    d = get_or_404("update_deliveries", did, "update delivery")
    if d["status"] not in ("CONSENT_GRANTED", "FAILED"):
        raise invalid_state("delivery cannot start downloading from %s" % d["status"])
    pkg = STORES["software_packages"].get(d["package_id"])
    machine = STORES["machines"].get(d["machine_id"])
    posture = machine["connectivity_posture"] if machine is not None else None
    mandatory = pkg["mandatory"] if pkg is not None else False
    if not (posture == "CONNECTED" or (posture == "THROTTLED" and mandatory)):
        raise ApiError(ERR_MACHINE_POSTURE_BLOCKED, 409, "machine posture blocks download")
    first_start = d["status"] == "CONSENT_GRANTED"
    d["status"] = "DOWNLOADING"
    d["download_attempts"] += 1
    touch(d)
    if first_start:
        # The bound ticket is consumed exactly once, on the first start;
        # retries from FAILED leave the CONSUMED ticket untouched.
        t = STORES["consent_tickets"].get(d["consent_ticket_id"])
        if t is not None and t["status"] == "GRANTED":
            t["status"] = "CONSUMED"
            touch(t)
    return ok(serialize(d))


@bp.post("/update-deliveries/<did>/report-installed")
def report_installed(did):
    uid, role = caller()
    require_role(role, {"System"})
    d = get_or_404("update_deliveries", did, "update delivery")
    if d["status"] != "DOWNLOADING":
        raise invalid_state("delivery is not DOWNLOADING")
    pkg = STORES["software_packages"].get(d["package_id"])
    machine = STORES["machines"].get(d["machine_id"])
    d["status"] = "INSTALLED"
    d["installed_at"] = now()
    touch(d)
    if machine is not None and pkg is not None:
        machine["modem_firmware_version"] = pkg["firmware_version"]
        touch(machine)
    return ok(serialize(d))


@bp.post("/update-deliveries/<did>/report-failed")
def report_failed(did):
    uid, role = caller()
    require_role(role, {"System"})
    b = body_json()
    failure_reason = as_str(need(b, "failure_reason"), "failure_reason")
    d = get_or_404("update_deliveries", did, "update delivery")
    if d["status"] != "DOWNLOADING":
        raise invalid_state("delivery is not DOWNLOADING")
    d["status"] = "FAILED"
    d["failure_reason"] = failure_reason
    touch(d)
    return ok(serialize(d))
