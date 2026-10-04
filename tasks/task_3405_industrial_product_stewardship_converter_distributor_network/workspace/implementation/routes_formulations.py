"""Formulation lifecycle: root creation, successors (OCC), discontinuation
(LTB window), and immutable formulation-component join rows (PRD §3.2)."""

from flask import Blueprint, request

import auth
import envelope
import serialization as ser
import store
import validation
from errors import invalid_request, invalid_state, not_found, stale_version

bp = Blueprint("formulations", __name__)


def _product_code_taken(product_code):
    return any(f["product_code"] == product_code
               for f in store.STORE["formulations"].values())


def _get_formulation(fid):
    row = store.STORE["formulations"].get(fid)
    if row is None:
        raise not_found("Formulation not found")
    return row


@bp.post("/stewardship/formulations")
def create_formulation():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ProductManager"])
    payload = validation.get_payload()
    product_code = validation.req_str(payload, "product_code")
    name = validation.req_str(payload, "name")
    family = validation.req_str(payload, "base_polymer_family")
    if _product_code_taken(product_code):
        raise invalid_request("product_code must be unique across Formulation")
    row = store.stamp_new({
        "product_code": product_code,
        "name": name,
        "base_polymer_family": family,
        "status": "DRAFT",
        "revision_number": 1,
        "successor_of_id": None,
        "active_clearance_count": 0,
        "discontinued_at": None,
        "ltb_deadline": None,
        "last_ship_date": None,
        "ltb_pool_quantity": None,
        "ltb_pool_remaining": None,
    })
    store.STORE["formulations"][row["id"]] = row
    return envelope.success_object(ser.formulation(row), 201)


@bp.get("/stewardship/formulations/<fid>")
def get_formulation(fid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.formulation(_get_formulation(fid)), 200)


@bp.get("/stewardship/formulations")
def list_formulations():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["formulations"].values(), request.args,
        ["status", "successor_of_id"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.formulation(r) for r in page], len(rows), limit, offset)


@bp.post("/stewardship/formulations/<fid>/successors")
def create_successor(fid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ProductManager"])
    payload = validation.get_payload()
    product_code = validation.req_str(payload, "product_code")
    name = validation.req_str(payload, "name")
    family = validation.req_str(payload, "base_polymer_family")
    expected = validation.req_int(payload, "expected_formulation_version")
    if _product_code_taken(product_code):
        raise invalid_request("product_code must be unique across Formulation")
    predecessor = _get_formulation(fid)
    if expected != predecessor["version"]:
        raise stale_version(
            "expected_formulation_version does not match the formulation's "
            "current version")
    row = store.stamp_new({
        "product_code": product_code,
        "name": name,
        "base_polymer_family": family,
        "status": "DRAFT",
        "revision_number": predecessor["revision_number"] + 1,
        "successor_of_id": predecessor["id"],
        "active_clearance_count": 0,
        "discontinued_at": None,
        "ltb_deadline": None,
        "last_ship_date": None,
        "ltb_pool_quantity": None,
        "ltb_pool_remaining": None,
    })
    store.STORE["formulations"][row["id"]] = row
    # Cross-entity bump: creating a successor mutates the predecessor (§2.5).
    store.touch(predecessor)
    return envelope.success_object(ser.formulation(row), 201)


@bp.post("/stewardship/formulations/<fid>/discontinue")
def discontinue_formulation(fid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ProductManager"])
    payload = validation.get_payload()
    ltb_deadline = validation.req_dt(payload, "last_time_buy_deadline")
    last_ship_date = validation.req_dt(payload, "last_ship_date")
    ltb_pool_quantity = validation.req_int(payload, "ltb_pool_quantity")
    if ltb_pool_quantity <= 0:
        raise invalid_request("ltb_pool_quantity must be > 0")
    formulation = _get_formulation(fid)
    if formulation["status"] != "ACTIVE":
        raise invalid_state(
            "Only an ACTIVE formulation can be discontinued")
    if ltb_deadline < store.now():
        raise invalid_request(
            "last_time_buy_deadline must not already have passed")
    if last_ship_date < ltb_deadline:
        raise invalid_request(
            "last_ship_date must not fall before last_time_buy_deadline")
    formulation["status"] = "DISCONTINUED"
    formulation["discontinued_at"] = store.now()
    formulation["ltb_deadline"] = ltb_deadline
    formulation["last_ship_date"] = last_ship_date
    formulation["ltb_pool_quantity"] = ltb_pool_quantity
    formulation["ltb_pool_remaining"] = ltb_pool_quantity
    store.touch(formulation)
    return envelope.success_object(ser.formulation(formulation), 200)


@bp.post("/stewardship/formulation-components")
def create_component():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["ProductManager"])
    payload = validation.get_payload()
    formulation_id = validation.req_str(payload, "formulation_id")
    substance_id = validation.req_str(payload, "substance_id")
    concentration = validation.req_int(payload, "concentration_ppm")
    if concentration <= 0:
        raise invalid_request("concentration_ppm must be > 0")
    formulation = store.STORE["formulations"].get(formulation_id)
    if formulation is None:
        raise not_found("Formulation not found")
    if store.STORE["substances"].get(substance_id) is None:
        raise not_found("Substance not found")
    if formulation["status"] != "DRAFT":
        raise invalid_state(
            "Components may only be added to a DRAFT formulation")
    for comp in store.STORE["components"].values():
        if (comp["formulation_id"] == formulation_id
                and comp["substance_id"] == substance_id):
            raise invalid_request(
                "A component for this (formulation, substance) pair already "
                "exists")
    row = store.stamp_new({
        "formulation_id": formulation_id,
        "substance_id": substance_id,
        "concentration_ppm": concentration,
    }, with_version=False)
    store.STORE["components"][row["id"]] = row
    # Content mutation of the parent formulation (§2.5).
    store.touch(formulation)
    return envelope.success_object(ser.component(row), 201)


@bp.get("/stewardship/formulation-components/<cid>")
def get_component(cid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    row = store.STORE["components"].get(cid)
    if row is None:
        raise not_found("FormulationComponent not found")
    return envelope.success_object(ser.component(row), 200)


@bp.get("/stewardship/formulation-components")
def list_components():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["components"].values(), request.args,
        ["formulation_id", "substance_id"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.component(r) for r in page], len(rows), limit, offset)
