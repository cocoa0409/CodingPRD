"""DeviceMaker endpoints: register, get, list, ip-review (+ IP cascade)."""
from flask import Blueprint, request

import serializers
import store
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND
from response import success_list, success_object
from validation import (
    ALL_ROLES,
    ROLE_PLATFORM_ADMIN,
    ROLE_LEGAL_COUNSEL,
    authenticate,
    get_body,
    req_field,
    as_str,
    as_enum,
    pagination_args,
)

bp = Blueprint("device_makers", __name__)

STANDING_TIERS = {"STANDARD", "STRATEGIC", "PROBATION"}
IP_STATUSES = {"CLEAR", "UNDER_REVIEW", "CONFIRMED_INFRINGEMENT", "CLEARED"}

# DeviceMaker ip_review_status machine (no terminal states).
_IP_TRANSITIONS = {
    "CLEAR": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"CONFIRMED_INFRINGEMENT", "CLEARED"},
    "CONFIRMED_INFRINGEMENT": {"CLEARED"},
    "CLEARED": set(),
}


@bp.route("/glass/device-makers", methods=["POST"])
def create_device_maker():
    authenticate({ROLE_PLATFORM_ADMIN})
    body = get_body()
    name = as_str(req_field(body, "name"), "name")
    region = as_str(req_field(body, "region"), "region")
    standing = body.get("standing_tier")
    if standing is not None:
        standing = as_enum(standing, "standing_tier", STANDING_TIERS)
    else:
        standing = "STANDARD"
    maker = store.base_fields()
    maker.update(
        {
            "name": name,
            "region": region,
            "standing_tier": standing,
            "ip_review_status": "CLEAR",
        }
    )
    store.device_makers[maker["id"]] = maker
    return success_object(serializers.device_maker(maker), status=201)


@bp.route("/glass/device-makers/<deviceMakerId>", methods=["GET"])
def get_device_maker(deviceMakerId):
    authenticate(ALL_ROLES)
    maker = store.device_makers.get(deviceMakerId)
    if maker is None:
        raise ApiError(ERR_NOT_FOUND, "Device maker not found")
    return success_object(serializers.device_maker(maker))


@bp.route("/glass/device-makers", methods=["GET"])
def list_device_makers():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    f_tier = request.args.get("standing_tier")
    f_ip = request.args.get("ip_review_status")
    items = list(store.device_makers.values())
    if f_tier is not None:
        items = [m for m in items if m["standing_tier"] == f_tier]
    if f_ip is not None:
        items = [m for m in items if m["ip_review_status"] == f_ip]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializers.device_maker(m) for m in page], limit, offset, total)


@bp.route("/glass/device-makers/<deviceMakerId>/ip-review", methods=["POST"])
def ip_review(deviceMakerId):
    authenticate({ROLE_LEGAL_COUNSEL})
    body = get_body()
    to_status = as_enum(req_field(body, "to_status"), "to_status", IP_STATUSES)
    maker = store.device_makers.get(deviceMakerId)
    if maker is None:
        raise ApiError(ERR_NOT_FOUND, "Device maker not found")
    if to_status not in _IP_TRANSITIONS[maker["ip_review_status"]]:
        raise ApiError(
            ERR_INVALID_STATE,
            "No ip_review_status transition from {} to {}".format(
                maker["ip_review_status"], to_status
            ),
        )
    maker["ip_review_status"] = to_status
    store.touch(maker)
    if to_status == "CONFIRMED_INFRINGEMENT":
        # Cascade hop 1: every ACTIVE license of this maker -> SUSPENDED/IP_REVIEW.
        suspended_ids = []
        for lic in list(store.licenses.values()):
            if (
                lic["device_maker_id"] == maker["id"]
                and lic["license_status"] == "ACTIVE"
            ):
                lic["license_status"] = "SUSPENDED"
                lic["suspension_reason"] = "IP_REVIEW"
                store.touch(lic)
                suspended_ids.append(lic["id"])
        # Cascade hop 2: SUBMITTED usage reports of suspended licenses -> HELD.
        for rep in list(store.usage_reports.values()):
            if rep["license_id"] in suspended_ids and rep["status"] == "SUBMITTED":
                rep["status"] = "HELD"
                store.touch(rep)
    # CONFIRMED_INFRINGEMENT -> CLEARED performs no automatic reinstatement.
    return success_object(serializers.device_maker(maker))
