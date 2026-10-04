"""Licensing agreements and the distribution territories they are bound to."""

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import (
    ERR_INVALID_STATE,
    ERR_LICENSE_FEE_BELOW_MINIMUM,
    ERR_LICENSE_TERRITORY_RESERVED,
    ERR_TERRITORY_OCCUPIED,
    ApiError,
)
from response import object_response
from routes.common import guard, list_response, one
from services import licensing as LIC

bp = Blueprint("licensing", __name__)

OFFICER = (auth.LICENSING_OFFICER,)
READERS = (auth.LICENSING_OFFICER, auth.EDITORIAL_STAFF, auth.LICENSEE)
TERRITORY_LICENSE_READERS = (auth.LICENSING_OFFICER, auth.EDITORIAL_STAFF)

TERMINATED = "TERMINATED"


# --- territories -----------------------------------------------------------

@bp.post("/distribution-territories")
@guard(OFFICER)
def create_territory(actor):
    data = P.body()
    code = P.text(data.get("territory_code"))
    for existing in store.territories.values():
        if existing.get("territory_code") == code:
            raise ApiError(ERR_INVALID_STATE, "territory_code must be unique")

    territory = store.create(store.territories, {
        "territory_code": code,
        "method": P.text(data.get("method")),
        "edi_payer_network": P.boolean(data.get("edi_payer_network"), False),
        "metadata_schema_version": P.text(data.get("metadata_schema_version"), "2026.1"),
        "can_license": False,
        "distribution_channel": None,
        "site_exception": False,
        "transaction_set_required": False,
        "reserved_range": None,
        "territory_status": "OPEN",
        "reserved_at": None,
        "activation_details": {},
    })
    LIC.territory_characteristics(territory)
    return object_response(one(territory), 201)


@bp.get("/distribution-territories")
@guard(READERS)
def list_territories(actor):
    rows = store.sorted_rows(store.territories)
    args = request.args
    for field in ("method", "territory_status"):
        wanted = args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    edi = args.get("edi_payer_network")
    if edi not in (None, ""):
        wanted = P.boolean(edi)
        rows = [r for r in rows if bool(r.get("edi_payer_network")) == wanted]
    return list_response(rows)


@bp.get("/distribution-territories/<territory_id>")
@guard(READERS)
def read_territory(actor, territory_id):
    return object_response(one(R.territory(territory_id)))


@bp.post("/distribution-territories/<territory_id>/reservations")
@guard(OFFICER)
def reserve_territory(actor, territory_id):
    territory = R.territory(territory_id)
    data = P.body()
    if territory.get("method") not in ("DISTRIBUTION", "REPRINT"):
        raise ApiError(ERR_INVALID_STATE, "a reservation is only available on an ineligible method")
    if territory.get("territory_status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "the territory is not open")

    territory["reserved_range"] = {
        "start": P.text_or_none(data.get("reserved_start")),
        "end": P.text_or_none(data.get("reserved_end")),
    }
    territory["territory_status"] = "RESERVED"
    territory["reserved_at"] = logical_now()
    LIC.territory_characteristics(territory)
    territory["can_license"] = False
    store.bump(territory)
    return object_response(one(territory), 200)


@bp.post("/distribution-territories/<territory_id>/method-corrections")
@guard(OFFICER)
def correct_territory_method(actor, territory_id):
    territory = R.territory(territory_id)
    if territory.get("reserved_at") is None:
        raise ApiError(ERR_INVALID_STATE, "the territory has not been reserved")

    territory["method"] = "SITE"
    territory["territory_status"] = "OPEN"
    LIC.territory_characteristics(territory)
    territory["can_license"] = True
    territory["site_exception"] = True
    store.bump(territory)
    return object_response(one(territory), 200)


@bp.post("/distribution-territories/<territory_id>/withdrawals")
@guard(OFFICER)
def withdraw_territory(actor, territory_id):
    territory = R.territory(territory_id)
    if territory.get("territory_status") != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, "only a reserved territory may be withdrawn")

    territory["reserved_range"] = None
    territory["territory_status"] = "WITHDRAWN"
    territory["can_license"] = False
    store.bump(territory)

    # Cascade: every licence carrying this territory is unbound and reduced to
    # the internal-only scope.
    for license_record in store.licenses.values():
        if license_record.get("territory_id") != territory["id"]:
            continue
        license_record["territory_id"] = None
        license_record["distribution_scope"] = "INTERNAL_ONLY"
        store.bump(license_record)
    return object_response(one(territory), 200)


# --- agreements ------------------------------------------------------------

@bp.post("/licensing-agreements")
@guard(OFFICER)
def create_license(actor):
    data = P.body()
    territory_id = P.text_or_none(data.get("territory_id"))
    if territory_id is not None:
        territory = R.territory(territory_id)
        if _occupant(territory["id"]) is not None:
            raise ApiError(ERR_TERRITORY_OCCUPIED,
                           "the territory is already bound by a non-terminated licence")

    license_record = store.create(store.licenses, {
        "licensee_type": P.text(data.get("licensee_type")),
        "licensee_name": P.text(data.get("licensee_name")),
        "payer_revenue_tier": P.text_or_none(data.get("payer_revenue_tier")),
        "vendor_worldwide": P.boolean(data.get("vendor_worldwide"), False),
        "expected_users": P.integer(data.get("expected_users"), 0),
        "sales_unit_count": P.integer(data.get("sales_unit_count"), 0),
        "royalty_fee_cents": 0,
        "fee_threshold_gate_status": "PASS",
        "base_fee_cents": P.integer(data.get("base_fee_cents"), 0),
        "territory_id": territory_id,
        "distribution_scope": None,
        "ancillary_publication_codes": [],
        "agreement_status": "DRAFT",
        "activated_at": None,
    })
    LIC.recompute_fee_gate(license_record)
    LIC.recompute_royalty(license_record)
    LIC.recompute_scope(license_record)
    LIC.recompute_ancillary(license_record)
    return object_response(one(license_record), 201)


@bp.get("/licensing-agreements")
@guard(READERS)
def list_licenses(actor):
    rows = store.sorted_rows(store.licenses)
    args = request.args
    for field in ("licensee_type", "agreement_status", "territory_id"):
        wanted = args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    minimum = args.get("min_royalty_fee_cents")
    if minimum not in (None, ""):
        rows = [r for r in rows if int(r.get("royalty_fee_cents") or 0) >= int(minimum)]
    maximum = args.get("max_royalty_fee_cents")
    if maximum not in (None, ""):
        rows = [r for r in rows if int(r.get("royalty_fee_cents") or 0) <= int(maximum)]
    return list_response(rows)


@bp.get("/licensing-agreements/<license_id>")
@guard(READERS)
def read_license(actor, license_id):
    return object_response(one(R.license(license_id)))


@bp.get("/distribution-territories/<territory_id>/licensing-agreements")
@guard(TERRITORY_LICENSE_READERS)
def list_territory_licenses(actor, territory_id):
    territory = R.territory(territory_id)
    rows = [l for l in store.sorted_rows(store.licenses)
            if l.get("territory_id") == territory["id"]]
    return list_response(rows)


@bp.post("/licensing-agreements/<license_id>/activations")
@guard(OFFICER)
def activate_license(actor, license_id):
    license_record = R.license(license_id)
    if license_record.get("agreement_status") != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "only a draft licence may be activated")

    # The fee threshold gate is evaluated before the territory reservation guard.
    LIC.recompute_fee_gate(license_record)
    if license_record.get("fee_threshold_gate_status") != "PASS":
        raise ApiError(ERR_LICENSE_FEE_BELOW_MINIMUM,
                       "the licence has not cleared the four-unit fee threshold")
    if license_record.get("territory_id") is None:
        raise ApiError(ERR_INVALID_STATE, "a licence must name a territory before activation")

    territory = store.territories.get(license_record["territory_id"])
    if territory is not None and territory.get("method") in ("DISTRIBUTION", "REPRINT") \
            and territory.get("territory_status") == "RESERVED":
        raise ApiError(ERR_LICENSE_TERRITORY_RESERVED,
                       "the licence territory is still reserved")

    license_record["agreement_status"] = "ACTIVE"
    license_record["activated_at"] = logical_now()
    LIC.recompute_royalty(license_record)
    LIC.recompute_scope(license_record)
    LIC.recompute_ancillary(license_record)
    store.bump(license_record)
    return object_response(one(license_record), 200)


@bp.post("/licensing-agreements/<license_id>/suspensions")
@guard(OFFICER)
def suspend_license(actor, license_id):
    license_record = R.license(license_id)
    if license_record.get("agreement_status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "only an active licence may be suspended")

    license_record["agreement_status"] = "SUSPENDED"
    # Scope is recomputed and then frozen at its last value.
    LIC.recompute_scope(license_record, frozen=True)
    store.bump(license_record)
    return object_response(one(license_record), 200)


@bp.post("/licensing-agreements/<license_id>/reactivations")
@guard(OFFICER)
def reactivate_license(actor, license_id):
    license_record = R.license(license_id)
    if license_record.get("agreement_status") != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "only a suspended licence may be reactivated")

    LIC.recompute_fee_gate(license_record)
    if license_record.get("fee_threshold_gate_status") != "PASS":
        raise ApiError(ERR_LICENSE_FEE_BELOW_MINIMUM,
                       "the licence has not cleared the four-unit fee threshold")

    license_record["agreement_status"] = "ACTIVE"
    LIC.recompute_royalty(license_record)
    store.bump(license_record)
    return object_response(one(license_record), 200)


@bp.post("/licensing-agreements/<license_id>/terminations")
@guard(OFFICER)
def terminate_license(actor, license_id):
    license_record = R.license(license_id)
    if license_record.get("agreement_status") not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "only an active or suspended licence may be terminated")

    # Cascade hop 1: released deliveries are withdrawn.
    for delivery in store.deliveries.values():
        if delivery.get("license_id") != license_record["id"]:
            continue
        if delivery.get("delivery_status") == "RELEASED":
            delivery["delivery_status"] = "WITHDRAWN"
            store.bump(delivery)

    license_record["agreement_status"] = TERMINATED
    license_record["termination_reason"] = P.text_or_none(P.body().get("reason"))
    # Cascade hop 2: the scope is recomputed and fixed at INTERNAL_ONLY.
    LIC.recompute_scope_internal_only(license_record)

    # Cascade hop 3: the bound territory is withdrawn and made unlicensable.
    territory = store.territories.get(license_record.get("territory_id")) \
        if license_record.get("territory_id") else None
    if territory is not None:
        territory["territory_status"] = "WITHDRAWN"
        territory["can_license"] = False
        store.bump(territory)

    store.bump(license_record)
    return object_response(one(license_record), 200)


def _occupant(territory_id):
    for license_record in store.licenses.values():
        if license_record.get("territory_id") != territory_id:
            continue
        if license_record.get("agreement_status") != TERMINATED:
            return license_record
    return None