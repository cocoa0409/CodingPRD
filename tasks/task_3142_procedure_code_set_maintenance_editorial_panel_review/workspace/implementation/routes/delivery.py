"""Content delivery, coding education and interpretation requests."""

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import (
    ERR_DUPLICATE_DELIVERY_RESERVATION,
    ERR_EDUCATION_NOT_COMPLETED,
    ERR_ELECTRONIC_MEDIA_REQUIRED,
    ERR_INVALID_STATE,
    ERR_NOT_ENTITLED,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
    ERR_VERSION_QUALIFIER_REQUIRED,
    ApiError,
)
from money import dec
from response import object_response
from routes.common import guard, list_response, one
from services import licensing as LIC

bp = Blueprint("delivery", __name__)

DELIVERY_FILERS = (auth.LICENSEE, auth.LICENSING_OFFICER)
DELIVERY_READERS = (auth.LICENSEE, auth.LICENSING_OFFICER, auth.EDITORIAL_STAFF)
STAFF = (auth.EDITORIAL_STAFF,)
OFFICER = (auth.LICENSING_OFFICER,)
GRANT_READERS = (auth.LICENSING_OFFICER, auth.EDITORIAL_STAFF, auth.LICENSEE)
LICENSE_LIST_READERS = (auth.LICENSEE, auth.LICENSING_OFFICER, auth.EDITORIAL_STAFF)

OPEN_SLOT_STATUSES = ("RESERVED", "READY")
QUALIFIER_FLOOR = dec("2026.1")


# --- content delivery orders ----------------------------------------------

@bp.post("/content-delivery-orders")
@guard(DELIVERY_FILERS)
def reserve_delivery(actor):
    data = P.body()
    license_record = R.license(P.text_or_none(data.get("license_id")) or "")
    channel = P.text(data.get("distribution_channel"))
    format_params = data.get("format_params") or {}
    payer_identifier = P.text_or_none(data.get("payer_identifier"))
    expected = data.get("expected_license_version")

    if license_record.get("agreement_status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "the licence is not active")

    # Guard 1: the EDI requirement for a payer identifier and a version
    # qualifier is evaluated before the qualifier's minimum schema gate.
    qualifier = format_params.get("version_qualifier")
    if channel == "EDI":
        if not qualifier or not payer_identifier:
            raise ApiError(ERR_ELECTRONIC_MEDIA_REQUIRED,
                           "an EDI delivery requires payer_identifier and a version qualifier")
    # Guard 2: the qualifier's own minimum schema gate.
    territory = store.territories.get(license_record.get("territory_id")) \
        if license_record.get("territory_id") else None
    if channel != "SITE" and LIC.metadatschema_requires_qualifier(territory):
        if qualifier is None or qualifier == "" or dec(qualifier) < QUALIFIER_FLOOR:
            raise ApiError(ERR_VERSION_QUALIFIER_REQUIRED,
                           "an electronic delivery requires a 2026.1 or later version qualifier")

    # Guard 3: the single-slot occupancy check, then the version echo.
    if expected is None or expected == "":
        raise ApiError(ERR_STALE_VERSION, "expected_license_version is required")
    if int(license_record.get("version") or 0) != int(expected):
        raise ApiError(ERR_STALE_VERSION,
                       "the licence has moved since the licensee last observed it")
    if _occupied_slot(license_record["id"]) is not None:
        raise ApiError(ERR_DUPLICATE_DELIVERY_RESERVATION,
                       "the licence already holds an open delivery slot")

    order = store.create(store.deliveries, {
        "license_id": license_record["id"],
        "distribution_channel": channel,
        "format_params": {
            "electronic_format": format_params.get("electronic_format"),
            "media": format_params.get("media"),
            "version_qualifier": qualifier,
            "payer_identifier_qualifier": format_params.get("payer_identifier_qualifier"),
        },
        "payer_identifier": payer_identifier,
        "delivery_status": "RESERVED",
        "reserved_at": logical_now(),
        "ready_at": None,
        "released_at": None,
        "activation_mode": LIC.activation_mode(channel, format_params),
    })
    # Cascade: reserving advances the licence's version.
    store.bump(license_record)
    return object_response(one(order), 201)


@bp.get("/content-delivery-orders")
@guard(DELIVERY_READERS)
def list_deliveries(actor):
    rows = store.sorted_rows(store.deliveries)
    for field in ("license_id", "delivery_status", "distribution_channel"):
        wanted = request.args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    return list_response(rows)


@bp.get("/content-delivery-orders/<order_id>")
@guard(DELIVERY_READERS)
def read_delivery(actor, order_id):
    return object_response(one(R.delivery(order_id)))


@bp.get("/licensing-agreements/<license_id>/content-delivery-orders")
@guard(LICENSE_LIST_READERS)
def list_license_deliveries(actor, license_id):
    license_record = R.license(license_id)
    rows = [d for d in store.sorted_rows(store.deliveries)
            if d.get("license_id") == license_record["id"]]
    return list_response(rows)


@bp.post("/content-delivery-orders/<order_id>/readiness")
@guard(STAFF)
def mark_ready(actor, order_id):
    order = R.delivery(order_id)
    if order.get("delivery_status") != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, "only a reserved order may be marked ready")

    data = P.body()
    media = data.get("media")
    if order.get("distribution_channel") == "PRINT_AND_ELECTRONIC" and media in (None, ""):
        raise ApiError(ERR_ELECTRONIC_MEDIA_REQUIRED,
                       "a print-and-electronic delivery requires media")
    if _occupied_slot(order["license_id"], ignore=order["id"]) is not None:
        raise ApiError(ERR_DUPLICATE_DELIVERY_RESERVATION,
                       "the licence already holds an open delivery slot")

    if media not in (None, ""):
        params = dict(order.get("format_params") or {})
        params["media"] = media
        order["format_params"] = params
    order["delivery_status"] = "READY"
    order["ready_at"] = logical_now()
    store.bump(order)
    return object_response(one(order), 200)


@bp.post("/content-delivery-orders/<order_id>/releases")
@guard(STAFF)
def release_delivery(actor, order_id):
    order = R.delivery(order_id)
    if order.get("delivery_status") != "READY":
        raise ApiError(ERR_INVALID_STATE, "only a ready order may be released")

    license_record = store.licenses.get(order.get("license_id"))
    if license_record is None:
        raise ApiError(ERR_INVALID_STATE, "the licence no longer exists")
    if license_record.get("agreement_status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "the licence is not active")

    channel = order.get("distribution_channel")
    params = order.get("format_params") or {}
    if channel == "EDI" and (not order.get("payer_identifier") or not params.get("version_qualifier")):
        raise ApiError(ERR_ELECTRONIC_MEDIA_REQUIRED,
                       "an EDI delivery requires payer_identifier and a version qualifier")

    territory = store.territories.get(license_record.get("territory_id")) \
        if license_record.get("territory_id") else None
    if territory is not None and territory.get("territory_status") == "RESERVED":
        raise ApiError(ERR_INVALID_STATE, "the licence territory is still reserved")

    order["delivery_status"] = "RELEASED"
    order["released_at"] = logical_now()
    store.bump(order)
    store.bump(license_record)
    return object_response(one(order), 200)


@bp.post("/content-delivery-orders/<order_id>/withdrawals")
@guard((auth.LICENSEE,))
def withdraw_delivery(actor, order_id):
    order = R.delivery(order_id)
    if order.get("license_id") != actor.user_id:
        raise ApiError(ERR_UNAUTHORIZED, "only the licence holder may withdraw the order")
    if order.get("delivery_status") != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, "only a reserved order may be withdrawn")

    order["delivery_status"] = "WITHDRAWN"
    order["released_at"] = None
    order["withdrawal_reason"] = P.text_or_none(P.body().get("reason"))
    store.bump(order)
    return object_response(one(order), 200)


def _occupied_slot(license_id, ignore=None):
    for order in store.deliveries.values():
        if order.get("license_id") != license_id:
            continue
        if ignore is not None and order.get("id") == ignore:
            continue
        if order.get("delivery_status") in OPEN_SLOT_STATUSES:
            return order
    return None


# --- coding education activities ------------------------------------------

@bp.post("/education-activities")
@guard(OFFICER)
def create_education(actor):
    data = P.body()
    license_record = R.license(P.text_or_none(data.get("licensee_id")) or "")
    code = P.text(data.get("activity_code"))
    for existing in store.education_activities.values():
        if existing.get("activity_code") == code:
            raise ApiError(ERR_INVALID_STATE, "activity_code must be unique")

    clock_hours = P.number(data.get("clock_hours"), 0)
    awarded, rounded = LIC.education_credits(clock_hours)
    activity = store.create(store.education_activities, {
        "licensee_id": license_record["id"],
        "activity_code": code,
        "clock_hours": float(clock_hours),
        "assistant_targeted": P.boolean(data.get("assistant_targeted"), False),
        "cea_credits_awarded": awarded,
        "cea_credits_rounded": rounded,
        "activity_status": "REGISTERED",
        "completed_at": None,
    })
    return object_response(one(activity), 201)


@bp.get("/education-activities")
@guard(GRANT_READERS)
def list_education(actor):
    rows = store.sorted_rows(store.education_activities)
    args = request.args
    for field in ("licensee_id", "activity_status"):
        wanted = args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    targeted = args.get("assistant_targeted")
    if targeted not in (None, ""):
        wanted = P.boolean(targeted)
        rows = [r for r in rows if bool(r.get("assistant_targeted")) == wanted]
    return list_response(rows)


@bp.get("/education-activities/<activity_id>")
@guard(GRANT_READERS)
def read_education(actor, activity_id):
    return object_response(one(R.education(activity_id)))


@bp.get("/licensing-agreements/<license_id>/education-activities")
@guard(GRANT_READERS)
def list_license_education(actor, license_id):
    license_record = R.license(license_id)
    rows = [a for a in store.sorted_rows(store.education_activities)
            if a.get("licensee_id") == license_record["id"]]
    return list_response(rows)


@bp.post("/education-activities/<activity_id>/completions")
@guard(OFFICER)
def complete_education(actor, activity_id):
    activity = R.education(activity_id)
    if activity.get("activity_status") != "REGISTERED":
        raise ApiError(ERR_EDUCATION_NOT_COMPLETED,
                       "an activity may be completed only from REGISTERED")

    awarded, rounded = LIC.education_credits(activity.get("clock_hours"))
    activity["cea_credits_awarded"] = awarded
    activity["cea_credits_rounded"] = rounded
    activity["activity_status"] = "COMPLETED"
    activity["completed_at"] = logical_now()
    store.bump(activity)
    return object_response(one(activity), 200)


# --- interpretation requests ----------------------------------------------

@bp.post("/interpretation-requests")
@guard(OFFICER)
def create_interpretation(actor):
    data = P.body()
    license_record = R.license(P.text_or_none(data.get("requesting_licensee_id")) or "")
    request_row = store.create(store.interpretation_requests, {
        "requesting_licensee_id": license_record["id"],
        "code": P.text(data.get("code")),
        "question": P.text(data.get("question")),
        "response_status": "PENDING",
        "entitlement_status": LIC.interpretation_entitlement(license_record),
        "answered_at": None,
    })
    return object_response(one(request_row), 201)


@bp.get("/interpretation-requests")
@guard(GRANT_READERS)
def list_interpretations(actor):
    rows = store.sorted_rows(store.interpretation_requests)
    for field in ("response_status", "requesting_licensee_id"):
        wanted = request.args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    return list_response(rows)


@bp.get("/interpretation-requests/<request_id>")
@guard(GRANT_READERS)
def read_interpretation(actor, request_id):
    return object_response(one(R.interpretation(request_id)))


@bp.get("/licensing-agreements/<license_id>/interpretation-requests")
@guard(GRANT_READERS)
def list_license_interpretations(actor, license_id):
    license_record = R.license(license_id)
    rows = [r for r in store.sorted_rows(store.interpretation_requests)
            if r.get("requesting_licensee_id") == license_record["id"]]
    return list_response(rows)


@bp.post("/interpretation-requests/<request_id>/answers")
@guard(STAFF)
def answer_interpretation(actor, request_id):
    request_row = R.interpretation(request_id)
    if request_row.get("entitlement_status") != "ENTITLED":
        raise ApiError(ERR_NOT_ENTITLED,
                       "the requesting licensee is not entitled to a written interpretation")

    license_record = store.licenses.get(request_row.get("requesting_licensee_id"))
    if license_record is None or license_record.get("agreement_status") not in (
        "ACTIVE", "SUSPENDED"
    ):
        raise ApiError(ERR_INVALID_STATE,
                       "the requesting licence is not active or suspended")

    request_row["answer_text"] = P.text_or_none(P.body().get("answer_text"))
    request_row["response_status"] = "ANSWERED"
    request_row["answered_at"] = logical_now()
    # The entitlement is recomputed from the requesting licensee class.
    request_row["entitlement_status"] = LIC.interpretation_entitlement(license_record)
    store.bump(request_row)
    return object_response(one(request_row), 200)