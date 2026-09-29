"""Retailer label display authorizations (PRD 3.8)."""

from flask import Blueprint

import cascades
import lookups
import serialize
import store
import validation as v
from auth import MANUFACTURER, PROGRAM_ADMINISTRATOR, RETAILER, caller, own
from envelope import add_days, created, ok
from errors import ApiError, bad_request
from store import touch, base_row
from validation import ensure

bp = Blueprint("display", __name__)

CHANNELS = ("IN_STORE", "ONLINE")
AUTHORIZATION_STATUSES = ("AUTHORIZED", "WITHDRAWN", "EXPIRED")
CHANGEOVER_BUFFER_DAYS = 7
AUTHORIZATION_READERS = (PROGRAM_ADMINISTRATOR, RETAILER, MANUFACTURER)


@bp.post("/labeling/display-authorizations")
def create_display_authorization():
    actor = caller(RETAILER)
    body = v.raw_body()

    # Ownership (rung 3) is directly comparable and precedes existence.
    pending_retailer = body.get("retailer_id")
    if isinstance(pending_retailer, str) and pending_retailer != "":
        own(pending_retailer == actor.user_id)

    lookups.resolve_fk(body, "retailer_id", lookups.need_retailer)
    lookups.resolve_fk(body, "label_grant_id", lookups.need_grant)

    retailer_id = v.field_str(body, "retailer_id")
    label_grant_id = v.field_str(body, "label_grant_id")
    channel = v.field_enum(body, "channel", CHANNELS)
    display_from = v.field_instant(body, "display_from")
    display_until = v.field_instant(body, "display_until")
    if display_until <= display_from:
        raise bad_request("Field 'display_until' must be strictly after 'display_from'.")

    retailer = lookups.need_retailer(retailer_id)
    grant = lookups.need_grant(label_grant_id)

    ensure(
        grant["grant_status"] == "ACTIVE"
        and grant["registry_publication_status"] == "PUBLISHED",
        "ERR_GRANT_NOT_PUBLISHED",
        "The grant must be both ACTIVE and PUBLISHED to be displayed.",
    )
    ensure(
        retailer["education_materials_ack"],
        "ERR_EDUCATION_ACK_REQUIRED",
        "The retailer has not acknowledged the consumer-education materials.",
    )
    ensure(
        grant["valid_from"] is not None
        and grant["valid_until"] is not None
        and display_from >= grant["valid_from"]
        and display_until <= grant["valid_until"],
        "ERR_DISPLAY_WINDOW_OUTSIDE_VALIDITY",
        "The display window must lie inside the grant's validity window.",
    )

    # The changeover buffer widens the requested window backwards by seven days;
    # both the buffer and both endpoints are inclusive.
    widened_start = add_days(display_from, -CHANGEOVER_BUFFER_DAYS)
    for other in store.authorizations_of_retailer(retailer["id"]):
        if other["label_grant_id"] != grant["id"] or other["channel"] != channel:
            continue
        if other["status"] != "AUTHORIZED":
            continue
        if widened_start <= other["display_until"] and other["display_from"] <= display_until:
            raise ApiError(
                "ERR_DISPLAY_WINDOW_CONFLICT",
                "The display window does not clear the changeover buffer.",
            )

    row = base_row()
    row.update(
        {
            "retailer_id": retailer["id"],
            "label_grant_id": grant["id"],
            "channel": channel,
            "display_from": display_from,
            "display_until": display_until,
            "status": "AUTHORIZED",
            "withdrawal_reason": None,
        }
    )
    store.display_authorizations[row["id"]] = row
    cascades.recount_retailer(retailer)
    return created(serialize.display_authorization(row))


@bp.get("/labeling/display-authorizations/<identifier>")
def read_display_authorization(identifier):
    caller(*AUTHORIZATION_READERS)
    return ok(serialize.display_authorization(lookups.need_authorization(identifier)))


@bp.get("/labeling/display-authorizations")
def list_display_authorizations():
    caller(*AUTHORIZATION_READERS)
    retailer_id = v.query_str("retailer_id")
    label_grant_id = v.query_str("label_grant_id")
    channel = v.query_enum("channel", CHANNELS)
    status = v.query_enum("status", AUTHORIZATION_STATUSES)

    rows = list(store.display_authorizations.values())
    if retailer_id is not None:
        rows = [row for row in rows if row["retailer_id"] == retailer_id]
    if label_grant_id is not None:
        rows = [row for row in rows if row["label_grant_id"] == label_grant_id]
    if channel is not None:
        rows = [row for row in rows if row["channel"] == channel]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    rows.sort(key=lambda row: (row["display_from"], row["created_at"], row["id"]))
    return lookups.listing(rows, serialize.display_authorization)


@bp.post("/labeling/display-authorizations/<identifier>/withdraw")
def withdraw_display_authorization(identifier):
    actor = caller(RETAILER)
    pending = store.display_authorizations.get(identifier)
    if pending is not None:
        own(pending["retailer_id"] == actor.user_id)
    authorization = lookups.need_authorization(identifier)

    body = v.raw_body()
    v.field_str(body, "withdrawal_reason", max_len=500)

    ensure(
        authorization["status"] == "AUTHORIZED",
        "ERR_INVALID_AUTHORIZATION_STATE",
        "Only an AUTHORIZED display authorization may be withdrawn.",
    )

    authorization["status"] = "WITHDRAWN"
    # An explicit retailer-initiated withdrawal always records RETAILER_REQUEST.
    authorization["withdrawal_reason"] = "RETAILER_REQUEST"
    touch(authorization)

    retailer = store.retailers.get(authorization["retailer_id"])
    if retailer is not None:
        cascades.recount_retailer(retailer)
    return created(serialize.display_authorization(authorization))
