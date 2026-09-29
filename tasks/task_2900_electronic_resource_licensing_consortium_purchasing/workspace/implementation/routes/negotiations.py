"""Section 3.4 and 3.5 - negotiation rounds and the signing cascade."""

from flask import Blueprint, request

import auth
import calc
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("negotiations", __name__)

ILL_ORDER = {"PROHIBITED": 0, "PRINT_ONLY": 1, "SECURE_ELECTRONIC": 2}
PERPETUAL_ORDER = {"NONE": 0, "POST_CANCELLATION_SUBSET": 1, "FULL_ARCHIVE": 2}

READ_ROLES = (auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_LICENSE_NEGOTIATOR, auth.ROLE_VENDOR_REP)


@bp.post("/erm/negotiations")
def create_negotiation():
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    data = shape.body()
    # priority 4 - body foreign keys resolve left to right before the shape
    if shape.present(data, "product_id"):
        auth.get_product(data["product_id"])
    if shape.present(data, "trial_id"):
        auth.get_trial(data["trial_id"])
    row = store.new_row({
        "product_id": shape.req_string(data, "product_id"),
        "trial_id": shape.req_string(data, "trial_id"),
        "status": "DRAFTING",
        "round_count": 0,
        "target_term_start": shape.req_date(data, "target_term_start"),
        "target_term_end": shape.req_date(data, "target_term_end"),
        "requested_ill_mode": shape.req_enum(data, "requested_ill_mode", shape.ILL_MODES),
        "requested_text_mining": shape.req_bool(data, "requested_text_mining"),
        "requested_accessibility_conformance": shape.req_enum(
            data, "requested_accessibility_conformance", shape.ACCESSIBILITY_LEVELS
        ),
        "requested_perpetual_access": shape.req_enum(
            data, "requested_perpetual_access", shape.PERPETUAL_MODES
        ),
        "granted_ill_mode": None,
        "granted_text_mining": None,
        "granted_accessibility_conformance": None,
        "granted_perpetual_access": None,
        "vendor_counter_price_cents": None,
        "agreed_price_cents": None,
        "last_submitted_by_user_id": None,
        "last_vendor_disposition": None,
    })
    store.negotiations[row["id"]] = row
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/negotiations/<negotiation_id>")
def read_negotiation(negotiation_id):
    auth.require_roles(*READ_ROLES)
    row = auth.get_negotiation(negotiation_id)
    return envelope.object_response(store.serialize(row))


@bp.get("/erm/negotiations")
def list_negotiations():
    auth.require_roles(*READ_ROLES)
    rows = list(store.negotiations.values())
    for field in ("product_id", "trial_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return envelope.paged(rows)


@bp.post("/erm/negotiations/<negotiation_id>/submit")
def submit_negotiation(negotiation_id):
    auth.require_roles(auth.ROLE_LICENSE_NEGOTIATOR)
    negotiation = auth.get_negotiation(negotiation_id)
    if negotiation["status"] != "DRAFTING":
        raise ApiError("ERR_NEGOTIATION_INVALID_STATE")
    if negotiation["round_count"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")
    store.mutate(negotiation, {
        "round_count": negotiation["round_count"] + 1,
        "last_submitted_by_user_id": auth.user_id(),
        "status": "VENDOR_REVIEW",
    })
    return envelope.object_response(store.serialize(negotiation))


@bp.post("/erm/negotiations/<negotiation_id>/vendor-response")
def vendor_response(negotiation_id):
    auth.require_roles(auth.ROLE_VENDOR_REP)
    negotiation = auth.get_negotiation(negotiation_id)
    product = store.products[negotiation["product_id"]]
    auth.require_vendor_scope(product)

    data = shape.body()
    disposition = shape.req_enum(data, "disposition", shape.DISPOSITIONS)
    granted_ill = shape.req_enum(data, "granted_ill_mode", shape.ILL_MODES)
    granted_mining = shape.req_bool(data, "granted_text_mining")
    granted_access = shape.req_enum(
        data, "granted_accessibility_conformance", shape.ACCESSIBILITY_LEVELS
    )
    granted_perpetual = shape.req_enum(
        data, "granted_perpetual_access", shape.PERPETUAL_MODES
    )
    price_field = "accepted_price_cents" if disposition == "ACCEPT" else "counter_price_cents"
    price = shape.req_int(data, price_field, minimum=1)

    if negotiation["status"] != "VENDOR_REVIEW":
        raise ApiError("ERR_NEGOTIATION_INVALID_STATE")

    # priority 12 - a vendor never concedes more than the package offers
    if ILL_ORDER[granted_ill] > ILL_ORDER[product["ill_mode_offered"]]:
        raise ApiError("ERR_TERM_EXCEEDS_PRODUCT_OFFER")
    if PERPETUAL_ORDER[granted_perpetual] > PERPETUAL_ORDER[product["perpetual_access_mode_offered"]]:
        raise ApiError("ERR_TERM_EXCEEDS_PRODUCT_OFFER")
    if granted_mining and not product["text_mining_offered"]:
        raise ApiError("ERR_TERM_EXCEEDS_PRODUCT_OFFER")

    changes = {
        "granted_ill_mode": granted_ill,
        "granted_text_mining": granted_mining,
        "granted_accessibility_conformance": granted_access,
        "granted_perpetual_access": granted_perpetual,
        "last_vendor_disposition": disposition,
    }
    if disposition == "ACCEPT":
        changes["agreed_price_cents"] = price
        changes["status"] = "AGREED"
    else:
        changes["vendor_counter_price_cents"] = price
        changes["status"] = "COUNTERED"
    store.mutate(negotiation, changes)
    return envelope.object_response(store.serialize(negotiation))


@bp.post("/erm/negotiations/<negotiation_id>/revise")
def revise_negotiation(negotiation_id):
    auth.require_roles(auth.ROLE_LICENSE_NEGOTIATOR)
    negotiation = auth.get_negotiation(negotiation_id)
    data = shape.body()
    changes = {
        "requested_ill_mode": shape.req_enum(data, "requested_ill_mode", shape.ILL_MODES),
        "requested_text_mining": shape.req_bool(data, "requested_text_mining"),
        "requested_accessibility_conformance": shape.req_enum(
            data, "requested_accessibility_conformance", shape.ACCESSIBILITY_LEVELS
        ),
        "requested_perpetual_access": shape.req_enum(
            data, "requested_perpetual_access", shape.PERPETUAL_MODES
        ),
    }
    if negotiation["status"] != "COUNTERED":
        raise ApiError("ERR_NEGOTIATION_INVALID_STATE")
    if negotiation["round_count"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")
    changes["status"] = "DRAFTING"
    store.mutate(negotiation, changes)
    return envelope.object_response(store.serialize(negotiation))


@bp.post("/erm/negotiations/<negotiation_id>/sign")
def sign_negotiation(negotiation_id):
    auth.require_roles(auth.ROLE_CONSORTIUM_ADMIN)
    negotiation = auth.get_negotiation(negotiation_id)
    data = shape.body()
    activation_start_date = shape.req_date(data, "activation_start_date")

    if negotiation["status"] != "AGREED":
        raise ApiError("ERR_NEGOTIATION_INVALID_STATE")

    product = store.products[negotiation["product_id"]]
    vendor = store.vendors[product["vendor_id"]]

    # priority 10 - accessibility must be genuinely settled
    if negotiation["granted_accessibility_conformance"] in (None, "NONE") \
            or not vendor["vpat_on_file"]:
        raise ApiError("ERR_ACCESSIBILITY_TERM_MISSING")

    # priority 11 - the signer may not be the last submitter
    if negotiation["last_submitted_by_user_id"] is not None \
            and auth.user_id() == negotiation["last_submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # priority 13 - the anchoring trial must be endorsed
    trial = store.trials.get(negotiation["trial_id"])
    if trial is None or trial["status"] != "ENDORSED":
        raise ApiError("ERR_TRIAL_NOT_ENDORSED")

    # a consortium purchase with no participants has nobody to invoice
    if not services.commitments_of_product(product["id"], ("PLEDGED",)):
        raise ApiError(
            "ERR_COMMITMENT_INVALID_STATE",
            "No PLEDGED commitment exists on the product, so there is nobody to invoice.",
        )

    subscription = services.sign_negotiation(negotiation, product, activation_start_date)
    return envelope.object_response(store.serialize(subscription), 201)
