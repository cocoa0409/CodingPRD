"""License endpoints: create, get, list, activate, suspend, reinstate,
terminate, submit-marketing, review-marketing (two parallel state dimensions)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants as C
import serializers
import store
from errors import (
    ApiError,
    ERR_BASE_PLATFORM_NOT_QUALIFIED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_IP_LITIGATION_HOLD,
    ERR_LICENSE_TERM_INVALID,
    ERR_LICENSE_TERM_OVERLAP,
    ERR_NDA_REQUIRED,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_PROGRAM_NOT_FROZEN,
)
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_LEGAL_COUNSEL,
    ROLE_DEVICE_MAKER,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_enum,
    as_datetime,
    pagination_args,
)

bp = Blueprint("licenses", __name__)

MARKETS = {"CONSUMER_ELECTRONICS", "AUTOMOTIVE", "PHARMA_PACKAGING", "ARCHITECTURAL"}
DECISIONS = {"APPROVED", "CHANGES_REQUIRED"}


def _get_license_or_404(license_id):
    lic = store.licenses.get(license_id)
    if lic is None:
        raise ApiError(ERR_NOT_FOUND, "License not found")
    return lic


def _overlap_exists(lic):
    """Closed-interval term collision with another ACTIVE license of the same
    maker and market; terms merely touching at an expiry date count."""
    for other in store.licenses.values():
        if other["id"] == lic["id"]:
            continue
        if other["device_maker_id"] != lic["device_maker_id"]:
            continue
        if other["market"] != lic["market"]:
            continue
        if other["license_status"] != "ACTIVE":
            continue
        if (
            lic["effective_date"] <= other["expiry_date"]
            and other["effective_date"] <= lic["expiry_date"]
        ):
            return True
    return False


@bp.route("/glass/licenses", methods=["POST"])
def create_license():
    authenticate({ROLE_LEGAL_COUNSEL})
    body = get_body()
    device_maker_id = as_str(req_field(body, "device_maker_id"), "device_maker_id")
    program_id = as_str(req_field(body, "program_id"), "program_id")
    market = as_enum(req_field(body, "market"), "market", MARKETS)
    effective = as_datetime(req_field(body, "effective_date"), "effective_date")
    expiry = as_datetime(req_field(body, "expiry_date"), "expiry_date")
    # Closed interval, inclusive at both ends, spanning at least the min term.
    if expiry - effective < timedelta(days=C.LICENSE_MIN_TERM_DAYS):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "License term must span at least {} days".format(C.LICENSE_MIN_TERM_DAYS),
        )
    if device_maker_id not in store.device_makers:
        raise ApiError(ERR_NOT_FOUND, "Device maker not found")
    program = store.programs.get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, "Program not found")
    # Priority 8: confidentiality gate.
    if program["status"] == "DRAFT":
        raise ApiError(ERR_NDA_REQUIRED, "Program NDA must be executed first")
    lic = store.base_fields()
    lic.update(
        {
            "device_maker_id": device_maker_id,
            "program_id": program["id"],
            "market": market,
            "effective_date": effective,
            "expiry_date": expiry,
            "license_status": "NEGOTIATION",
            "marketing_status": "DRAFT",
            "suspension_reason": "NONE",
            "cumulative_royalty_cents": 0,
        }
    )
    store.licenses[lic["id"]] = lic
    return success_object(serializers.license_(lic), status=201)


@bp.route("/glass/licenses/<licenseId>", methods=["GET"])
def get_license(licenseId):
    authenticate(ALL_ROLES)
    return success_object(serializers.license_(_get_license_or_404(licenseId)))


@bp.route("/glass/licenses", methods=["GET"])
def list_licenses():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_maker = request.args.get("device_maker_id")
    f_program = request.args.get("program_id")
    f_market = request.args.get("market")
    f_status = request.args.get("license_status")
    items = list(store.licenses.values())
    if f_maker is not None:
        items = [l for l in items if l["device_maker_id"] == f_maker]
    if f_program is not None:
        items = [l for l in items if l["program_id"] == f_program]
    if f_market is not None:
        items = [l for l in items if l["market"] == f_market]
    if f_status is not None:
        items = [l for l in items if l["license_status"] == f_status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.license_(l) for l in page], limit, offset, total)


@bp.route("/glass/licenses/<licenseId>/activate", methods=["POST"])
def activate_license(licenseId):
    authenticate({ROLE_LEGAL_COUNSEL})
    get_body()
    lic = _get_license_or_404(licenseId)
    if lic["license_status"] != "NEGOTIATION":
        raise ApiError(ERR_INVALID_STATE, "activate requires NEGOTIATION")
    # Priority 9: IP litigation hold.
    maker = store.device_makers[lic["device_maker_id"]]
    if maker["ip_review_status"] == "CONFIRMED_INFRINGEMENT":
        raise ApiError(ERR_IP_LITIGATION_HOLD, "Device maker under IP litigation hold")
    # Priority 15: clock inside the closed term interval, then overlap.
    now = clock.now()
    if now < lic["effective_date"] or now > lic["expiry_date"]:
        raise ApiError(ERR_LICENSE_TERM_INVALID, "Clock outside the license term")
    if _overlap_exists(lic):
        raise ApiError(
            ERR_LICENSE_TERM_OVERLAP, "Term collides with another ACTIVE license"
        )
    # Priority 18: program frozen; secondary market additionally needs LOCKED.
    program = store.programs[lic["program_id"]]
    if program["status"] != "DESIGN_FROZEN":
        raise ApiError(ERR_PROGRAM_NOT_FROZEN, "Program is not DESIGN_FROZEN")
    if lic["market"] != program["primary_market"]:
        locked = any(
            c["program_id"] == program["id"] and c["status"] == "LOCKED"
            for c in store.compositions.values()
        )
        if not locked:
            raise ApiError(
                ERR_BASE_PLATFORM_NOT_QUALIFIED,
                "Secondary application requires a LOCKED base composition",
            )
    lic["license_status"] = "ACTIVE"
    store.touch(lic)
    return success_object(serializers.license_(lic))


@bp.route("/glass/licenses/<licenseId>/suspend", methods=["POST"])
def suspend_license(licenseId):
    authenticate({ROLE_LEGAL_COUNSEL})
    get_body()
    lic = _get_license_or_404(licenseId)
    if lic["license_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "suspend requires ACTIVE")
    lic["license_status"] = "SUSPENDED"
    lic["suspension_reason"] = "MANUAL"
    store.touch(lic)
    return success_object(serializers.license_(lic))


@bp.route("/glass/licenses/<licenseId>/reinstate", methods=["POST"])
def reinstate_license(licenseId):
    authenticate({ROLE_LEGAL_COUNSEL})
    get_body()
    lic = _get_license_or_404(licenseId)
    if lic["license_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "reinstate requires SUSPENDED")
    # Only CLEAR or CLEARED posture may reinstate (any other fails the hold).
    maker = store.device_makers[lic["device_maker_id"]]
    if maker["ip_review_status"] not in ("CLEAR", "CLEARED"):
        raise ApiError(ERR_IP_LITIGATION_HOLD, "Device maker IP posture blocks reinstatement")
    if clock.now() > lic["expiry_date"]:
        raise ApiError(ERR_LICENSE_TERM_INVALID, "License term has expired")
    if _overlap_exists(lic):
        raise ApiError(
            ERR_LICENSE_TERM_OVERLAP, "Term collides with another ACTIVE license"
        )
    lic["license_status"] = "ACTIVE"
    lic["suspension_reason"] = "NONE"
    store.touch(lic)
    return success_object(serializers.license_(lic))


@bp.route("/glass/licenses/<licenseId>/terminate", methods=["POST"])
def terminate_license(licenseId):
    authenticate({ROLE_LEGAL_COUNSEL})
    get_body()
    lic = _get_license_or_404(licenseId)
    if lic["license_status"] not in ("NEGOTIATION", "ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "terminate requires a non-terminal license")
    lic["license_status"] = "TERMINATED"
    store.touch(lic)
    return success_object(serializers.license_(lic))


@bp.route("/glass/licenses/<licenseId>/submit-marketing", methods=["POST"])
def submit_marketing(licenseId):
    user_id = authenticate({ROLE_DEVICE_MAKER})
    body = get_body()
    as_str(req_field(body, "materials_ref"), "materials_ref")
    lic = _get_license_or_404(licenseId)
    if user_id != lic["device_maker_id"]:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, "Caller is not the licensee")
    if lic["license_status"] not in ("NEGOTIATION", "ACTIVE"):
        raise ApiError(
            ERR_INVALID_STATE, "License must be NEGOTIATION or ACTIVE to submit marketing"
        )
    if lic["marketing_status"] not in ("DRAFT", "CHANGES_REQUIRED"):
        raise ApiError(
            ERR_INVALID_STATE, "submit-marketing requires DRAFT or CHANGES_REQUIRED"
        )
    lic["marketing_status"] = "IN_REVIEW"
    store.touch(lic)
    return success_object(serializers.license_(lic))


@bp.route("/glass/licenses/<licenseId>/review-marketing", methods=["POST"])
def review_marketing(licenseId):
    authenticate({ROLE_LEGAL_COUNSEL})
    body = get_body()
    decision = as_enum(req_field(body, "decision"), "decision", DECISIONS)
    lic = _get_license_or_404(licenseId)
    if lic["marketing_status"] != "IN_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "review-marketing requires IN_REVIEW")
    lic["marketing_status"] = decision
    store.touch(lic)
    return success_object(serializers.license_(lic))
