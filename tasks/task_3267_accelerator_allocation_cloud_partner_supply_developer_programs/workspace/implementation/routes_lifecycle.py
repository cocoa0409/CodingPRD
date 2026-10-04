"""Supply contracts and long-term availability commitments."""

import calc
import constants as K
from auth import roles
from error import (
    CatalogError,
    ERR_CONTRACT_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LIFECYCLE_HORIZON_TOO_SHORT,
    ERR_LIFECYCLE_UNITS_UNCOMMITTED,
    ERR_PARTNER_NOT_FOUND,
    ERR_QUALIFICATION_NOT_MET,
)
from envelope import created, ok, page
from rules import check_product_version, resolve, resource_or_404
from services import serialize
from store import DB
from util import by_created, optional, paginate, parse_utc, require, require_enum

GROUP = "lifecycle"


def _month_index(value):
    """YYYY-MM to a monotonic month ordinal."""
    text = str(value)
    if len(text) != 7 or text[4] != "-":
        raise CatalogError(ERR_INVALID_REQUEST, "Months must be formatted YYYY-MM.")
    try:
        year = int(text[:4])
        month = int(text[5:])
    except ValueError:
        raise CatalogError(ERR_INVALID_REQUEST, "Months must be formatted YYYY-MM.")
    if month < 1 or month > 12:
        raise CatalogError(ERR_INVALID_REQUEST, "Months must be formatted YYYY-MM.")
    return year * 12 + (month - 1)


# -------------------------------------------------------- supply contracts --
def _create_contract(caller):
    from flask import request
    body = request.raw_payload or {}
    product = resolve("products", require(body, "product_sku_id"))
    if product is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'product_sku_id' does not resolve.")
    partner_id = optional(body, "partner_id")
    if not partner_id and caller.role == "PartnerOps":
        partner_id = caller.user_id
    partner = DB.partners.get(partner_id) if partner_id else None
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND, "The contract holder does not exist.")

    start = require(body, "start_month")
    end = require(body, "end_month")
    start_index = _month_index(start)
    end_index = _month_index(end)
    if end_index < start_index:
        raise CatalogError(ERR_INVALID_REQUEST, "end_month precedes start_month.")

    # Half-open month windows [start, end + 1).  Two windows collide only when
# they share a month; a contract starting in the month after an existing
# contract's last contracted month is adjacent and therefore legal (PRD 3.9).
    for contract in DB.contracts.values():
        if contract.get("product_sku_id") != product["id"]:
            continue
        existing_start = _month_index(contract.get("start_month"))
        existing_end = _month_index(contract.get("end_month"))
        if start_index <= existing_end and end_index >= existing_start:
            raise CatalogError(ERR_CONTRACT_WINDOW_OVERLAP)

    contract = DB.mint({
        "partner_id": partner["id"],
        "product_sku_id": product["id"],
        "start_month": start,
        "end_month": end,
        "contracted_units": require(body, "contracted_units", "int"),
        "window_status": "OPEN",
    })
    DB.contracts[contract["id"]] = contract
    return created(serialize(contract))


def _list_contracts(caller):
    from flask import request
    rows = by_created(list(DB.contracts.values()))
    for field in ("partner_id", "product_sku_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_contract(caller, contract_id):
    return ok(serialize(resource_or_404("contracts", contract_id, "supply contract")))


# ------------------------------------------------------ lifecycle commits --
def _create_commitment(caller):
    from flask import request
    body = request.raw_payload or {}
    product = resolve("products", require(body, "product_sku_id"))
    if product is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'product_sku_id' does not resolve.")
    partner = DB.partners.get(require(body, "embedded_partner_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    availability = require(body, "availability_through")
    from datetime import timedelta

    # The horizon grace gate belongs to the grant path (PRD 3.9): a request may be
    # filed with any horizon and is only refused when it is granted.
    parse_utc(availability)

    commitment = DB.mint({
        "product_sku_id": product["id"],
        "embedded_partner_id": partner["id"],
        "availability_through": availability,
        "commitment_floor_days": 0,
        "commitment_status": "REQUESTED",
        "covered_units": require(body, "covered_units", "int"),
        "expected_product_version": None,
    })
    DB.commitments[commitment["id"]] = commitment
    return created(serialize(commitment))


def _list_commitments(caller):
    from flask import request
    rows = by_created(list(DB.commitments.values()))
    for field in ("partner_id", "embedded_partner_id", "product_sku_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_commitment(caller, commitment_id):
    return ok(serialize(resource_or_404("commitments", commitment_id, "lifecycle commitment")))


def _grant(caller, commitment_id):
    from flask import request
    body = request.raw_payload if isinstance(request.raw_payload, dict) else {}
    commitment = resource_or_404("commitments", commitment_id, "lifecycle commitment")
    if commitment.get("commitment_status") != "REQUESTED":
        raise CatalogError(ERR_INVALID_STATE, "Only a REQUESTED commitment may be granted.")
    partner = DB.partners.get(commitment.get("embedded_partner_id"))
    product = DB.products.get(commitment.get("product_sku_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    if product is None:
        raise CatalogError(ERR_INVALID_REQUEST, "The product no longer exists.")
    if partner.get("qualification_status") != "QUALIFIED":
        raise CatalogError(ERR_QUALIFICATION_NOT_MET)
    # PRD 3.9 lists the three grant conditions in order: qualification, then the
    # horizon grace floor, then the unit-availability bound.  The horizon rule is
    # therefore evaluated above the units rule.
    from datetime import timedelta
    if parse_utc(commitment.get("availability_through")) < DB.clock + timedelta(days=K.LIFECYCLE_GRACE_DAYS):
        raise CatalogError(ERR_LIFECYCLE_HORIZON_TOO_SHORT)
    if int(commitment.get("covered_units", 0)) > int(product.get("available_units", 0) or 0):
        raise CatalogError(ERR_LIFECYCLE_UNITS_UNCOMMITTED)
    check_product_version(product, body.get("expected_product_version"))

    floor_days, product_min = calc.lifecycle_commitment_floor(
        partner, product, commitment.get("availability_through"), DB.clock
    )
    commitment["commitment_status"] = "GRANTED"
    commitment["commitment_floor_days"] = floor_days
    commitment["expected_product_version"] = body.get("expected_product_version")
    DB.touch(commitment)

    product["lifecycle_min_remaining_days"] = product_min
    DB.bump(product)
    partner["lifecycle_floor_expires_at"] = commitment.get("availability_through")
    DB.touch(partner)
    return ok(serialize(commitment))


def _decline(caller, commitment_id):
    commitment = resource_or_404("commitments", commitment_id, "lifecycle commitment")
    if commitment.get("commitment_status") != "REQUESTED":
        raise CatalogError(ERR_INVALID_STATE, "Only a REQUESTED commitment may be declined.")
    commitment["commitment_status"] = "DECLINED"
    DB.touch(commitment)
    return ok(serialize(commitment))


ROUTES = [
    ("POST", "/accelerators/supply-contracts", _create_contract, ("LifecycleProgramManager",)),
    ("GET", "/accelerators/supply-contracts", _list_contracts, ("LifecycleProgramManager",)),
    ("GET", "/accelerators/supply-contracts/<contract_id>", _read_contract, ("LifecycleProgramManager",)),
    ("POST", "/accelerators/lifecycle-commitments", _create_commitment, ("LifecycleProgramManager",)),
    ("GET", "/accelerators/lifecycle-commitments", _list_commitments, ("LifecycleProgramManager",)),
    ("GET", "/accelerators/lifecycle-commitments/<commitment_id>", _read_commitment, ("LifecycleProgramManager",)),
    ("POST", "/accelerators/lifecycle-commitments/<commitment_id>/grant", _grant, ("LifecycleProgramManager",)),
    ("POST", "/accelerators/lifecycle-commitments/<commitment_id>/decline", _decline, ("LifecycleProgramManager",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])