"""SenderNumber routes: provision, port lifecycle, attach/detach/reinstate/release."""
import re

from flask import Blueprint, request

import store
from constants import PATH_KINDS, COUNTRY_CODES, SHORT_CODE_MPS
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_NUMBER_TYPE_OCCUPIED,
    ERR_PORT_REQUIREMENTS,
    ERR_SHORT_CODE_GEO,
    ERR_CAMPAIGN_NOT_APPROVED,
    ERR_ACCOUNT_SUSPENDED,
    validation,
)
from response import success_object, success_list
from serializers import ser_number, ser_message
from services.shared import check_account_gate, final_number_fee_on_release
from util import (
    find_or_404,
    get_json_body,
    new_id,
    now_dt,
    pagination_params,
    require_auth,
    require_enum,
    require_nonempty,
    sort_by_created,
    touch,
)

bp = Blueprint("numbers", __name__)

NUMBER_READ_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "CampaignManager",
    "NumberProvisioner", "CarrierReviewer", "SystemDriver",
]
NUMBER_LIST_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "CampaignManager",
    "NumberProvisioner", "CarrierReviewer",
]

BASE_MPS = {"TEN_DLC": 1, "TOLL_FREE": 3, "SHORT_CODE": SHORT_CODE_MPS}


def normalize_e164(phone_number, country_code):
    digits = re.sub(r"\D", "", phone_number)
    if country_code == "US" and len(digits) == 10:
        digits = "1" + digits
    if country_code == "CA" and len(digits) == 10:
        digits = "1" + digits
    if country_code == "GB" and len(digits) == 10:
        digits = "44" + digits
    return "+" + digits


@bp.post("/messaging/accounts/<account_id>/numbers")
def create_number(account_id):
    require_auth(["NumberProvisioner", "PlatformAdmin"])
    account = find_or_404(store.ACCOUNTS, account_id)
    check_account_gate(account)
    body = get_json_body()
    require_nonempty(body, ["phone_number"])
    number_type = require_enum(body, "number_type", PATH_KINDS)
    country_code = require_enum(body, "country_code", COUNTRY_CODES)

    if number_type == "SHORT_CODE":
        if account["country_code"] != "US" or account["plan_tier"] != "PREMIUM":
            raise ApiError(
                ERR_SHORT_CODE_GEO,
                "SHORT_CODE numbers require a US PREMIUM account",
                422,
            )

    port_phone = body.get("port_phone_number")
    if port_phone is not None:
        loa = body.get("port_letter_of_agency")
        carrier = body.get("port_losing_carrier")
        if (
            not isinstance(port_phone, str) or not port_phone.strip()
            or not isinstance(loa, str) or not loa.strip()
            or not isinstance(carrier, str) or not carrier.strip()
        ):
            raise ApiError(
                ERR_PORT_REQUIREMENTS,
                "PORT_IN requires port_phone_number, port_letter_of_agency, port_losing_carrier",
                422,
            )
        if country_code != account["country_code"]:
            raise ApiError(
                ERR_PORT_REQUIREMENTS,
                "Ported number country must match account country",
                422,
            )
        provisioning_source = "PORT_IN"
    elif number_type == "SHORT_CODE":
        provisioning_source = "SHORT_CODE_ORDER"
    else:
        provisioning_source = "NEW_PURCHASE"

    number = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "updated_at": store.now_iso(),
        "version": 1,
        "account_id": account_id,
        "campaign_id": "",
        "e164": normalize_e164(body["phone_number"], country_code),
        "phone_number": body["phone_number"],
        "number_type": number_type,
        "country_code": country_code,
        "provisioning_source": provisioning_source,
        "port_phone_number": body.get("port_phone_number"),
        "port_letter_of_agency": body.get("port_letter_of_agency"),
        "port_losing_carrier": body.get("port_losing_carrier"),
        "base_mps": BASE_MPS[number_type],
        "suspended_reason": "",
        "port_requested_at": None,
        "activated_at": None,
        "status": "PENDING",
    }
    if provisioning_source == "PORT_IN":
        number["status"] = "PORTING"
        number["port_requested_at"] = store.now_iso()
    store.NUMBERS[number["id"]] = number
    return success_object(ser_number(number), 201)


@bp.get("/messaging/accounts/<account_id>/numbers/<number_id>")
def get_number(account_id, number_id):
    require_auth(NUMBER_READ_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    number = find_or_404(store.NUMBERS, number_id, account_id)
    return success_object(ser_number(number))


@bp.get("/messaging/numbers/<number_id>")
def get_number_alias(number_id):
    require_auth(NUMBER_LIST_ROLES)
    number = find_or_404(store.NUMBERS, number_id)
    return success_object(ser_number(number))


def _filter_numbers(items):
    status_filter = request.args.get("status")
    if status_filter:
        items = [n for n in items if n["status"] == status_filter]
    campaign_filter = request.args.get("campaign_id")
    if campaign_filter:
        items = [n for n in items if n.get("campaign_id") == campaign_filter]
    return items


@bp.get("/messaging/accounts/<account_id>/numbers")
def list_account_numbers(account_id):
    require_auth(NUMBER_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    limit, offset = pagination_params()
    items = [n for n in store.NUMBERS.values() if n["account_id"] == account_id]
    items = _filter_numbers(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_number(n) for n in page], limit, offset, total)


@bp.get("/messaging/accounts/<account_id>/numbers/<number_id>/messages")
def list_number_messages(account_id, number_id):
    require_auth(NUMBER_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.NUMBERS, number_id, account_id)
    limit, offset = pagination_params()
    items = [
        m for m in store.MESSAGES.values()
        if m["account_id"] == account_id and m["sender_number_id"] == number_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_message(m) for m in page], limit, offset, total)


@bp.post("/messaging/accounts/<account_id>/numbers/<number_id>/activate")
def activate_number(account_id, number_id):
    require_auth(["NumberProvisioner"])
    account = find_or_404(store.ACCOUNTS, account_id)
    number = find_or_404(store.NUMBERS, number_id, account_id)
    check_account_gate(account)
    if number["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Number is not PENDING", 409)
    if number["provisioning_source"] == "PORT_IN":
        raise ApiError(
            ERR_INVALID_STATE,
            "Port-in numbers activate via complete_port",
            409,
        )
    number["status"] = "ACTIVE"
    number["activated_at"] = store.now_iso()
    touch(number)
    return success_object(ser_number(number))


@bp.post("/messaging/accounts/<account_id>/numbers/<number_id>/complete_port")
def complete_port(account_id, number_id):
    require_auth(["NumberProvisioner"])
    account = find_or_404(store.ACCOUNTS, account_id)
    number = find_or_404(store.NUMBERS, number_id, account_id)
    check_account_gate(account)
    if number["status"] != "PORTING":
        raise ApiError(ERR_INVALID_STATE, "Number is not PORTING", 409)
    number["status"] = "ACTIVE"
    number["activated_at"] = store.now_iso()
    touch(number)
    return success_object(ser_number(number))


@bp.post("/messaging/accounts/<account_id>/numbers/<number_id>/fail_port")
def fail_port(account_id, number_id):
    require_auth(["NumberProvisioner"])
    account = find_or_404(store.ACCOUNTS, account_id)
    number = find_or_404(store.NUMBERS, number_id, account_id)
    check_account_gate(account)
    if number["status"] != "PORTING":
        raise ApiError(ERR_INVALID_STATE, "Number is not PORTING", 409)
    body = get_json_body()
    reason = body.get("reason", "")
    if not isinstance(reason, str):
        raise validation("reason must be a string")
    number["status"] = "FAILED"
    touch(number)
    return success_object(ser_number(number))


@bp.post("/messaging/accounts/<account_id>/numbers/<number_id>/attach")
def attach_number(account_id, number_id):
    require_auth(["NumberProvisioner"])
    account = find_or_404(store.ACCOUNTS, account_id)
    number = find_or_404(store.NUMBERS, number_id, account_id)
    check_account_gate(account)
    if number["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Only ACTIVE numbers may be attached", 409)
    body = get_json_body()
    require_nonempty(body, ["campaign_id"])
    campaign = store.CAMPAIGNS.get(body["campaign_id"])
    if campaign is None or campaign["account_id"] != account_id:
        raise ApiError(ERR_NOT_FOUND, "Campaign not found under account", 404)
    if campaign["status"] != "APPROVED":
        raise ApiError(ERR_CAMPAIGN_NOT_APPROVED, "Campaign is not APPROVED", 409)
    occupied = any(
        n is not number
        and n.get("campaign_id") == campaign["id"]
        and n["status"] == "ACTIVE"
        and n["number_type"] == number["number_type"]
        for n in store.NUMBERS.values()
    )
    if occupied:
        raise ApiError(
            ERR_NUMBER_TYPE_OCCUPIED,
            "Campaign already has an ACTIVE number of this number_type",
            409,
        )
    expected = body.get("expected_campaign_version")
    if expected is None or expected != campaign["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_campaign_version does not match current version",
            412,
        )
    number["campaign_id"] = campaign["id"]
    touch(number)
    touch(campaign)
    return success_object(ser_number(number))


@bp.post("/messaging/accounts/<account_id>/numbers/<number_id>/detach")
def detach_number(account_id, number_id):
    require_auth(["NumberProvisioner"])
    account = find_or_404(store.ACCOUNTS, account_id)
    number = find_or_404(store.NUMBERS, number_id, account_id)
    check_account_gate(account)
    number["campaign_id"] = ""
    touch(number)
    return success_object(ser_number(number))


@bp.post("/messaging/accounts/<account_id>/numbers/<number_id>/reinstate")
def reinstate_number(account_id, number_id):
    require_auth(["NumberProvisioner"])
    account = find_or_404(store.ACCOUNTS, account_id)
    number = find_or_404(store.NUMBERS, number_id, account_id)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account is not ACTIVE", 409)
    if number["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Number is not SUSPENDED", 409)
    campaign_id = number.get("campaign_id")
    if campaign_id:
        campaign = store.CAMPAIGNS.get(campaign_id)
        if campaign is None or campaign["status"] != "APPROVED":
            raise ApiError(ERR_CAMPAIGN_NOT_APPROVED, "Attached campaign is not APPROVED", 409)
    number["status"] = "ACTIVE"
    number["suspended_reason"] = ""
    touch(number)
    return success_object(ser_number(number))


@bp.post("/messaging/accounts/<account_id>/numbers/<number_id>/release")
def release_number(account_id, number_id):
    require_auth(["NumberProvisioner"])
    account = find_or_404(store.ACCOUNTS, account_id)
    number = find_or_404(store.NUMBERS, number_id, account_id)
    check_account_gate(account)
    if number["status"] not in ("PENDING", "FAILED", "ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "Number cannot be released from this state", 409)
    final_number_fee_on_release(number, now_dt())
    number["status"] = "RELEASED"
    number["campaign_id"] = ""
    touch(number)
    return success_object(ser_number(number))


@bp.get("/messaging/numbers")
def list_numbers():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.NUMBERS.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [n for n in items if n["account_id"] == account_filter]
    items = _filter_numbers(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_number(n) for n in page], limit, offset, total)
