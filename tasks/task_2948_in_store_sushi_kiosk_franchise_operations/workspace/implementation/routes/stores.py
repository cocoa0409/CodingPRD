"""Host stores and license agreements -- PRD 3.1."""

import re

from flask import Blueprint

import db
from core import LOCK, dec, logical_now_iso
from errors import ApiError
from middleware import (ROLE_FRANCHISE_CHEF, ROLE_FRANCHISOR_OPS,
                        ROLE_HOST_STORE_MANAGER, ROLE_QUALITY_AUDITOR, authorize,
                        body, own_store, req_date, req_enum, req_int, req_num,
                        req_str, strictly_ordered)
from response import created, ok
from routes.base import (agreement_or_404, fk_lookup, filters, paginate,
                         store_or_404)
from services import domain

bp = Blueprint("stores", __name__)

POS_STATES = ("NOT_CONNECTED", "CONNECTED", "SUSPENDED")
REVENUE_SHARE_MODELS = ("GROSS_SALES", "NET_OF_MARKDOWN")
MARKDOWN_POLICIES = ("PRORATED_REMAINING_LIFE", "FLAT_STEP")
_STATE_CODE = re.compile(r"^[A-Z]{2}$")


# ==========================================================================
# Host stores
# ==========================================================================


@bp.post("/host-stores")
def register_host_store():
    authorize(ROLE_FRANCHISOR_OPS)
    payload = body()
    name = req_str(payload, "name")
    banner_chain = req_str(payload, "banner_chain")
    store_number = req_str(payload, "store_number")
    state_code = req_str(payload, "state_code")
    if not _STATE_CODE.match(state_code):
        raise ApiError("ERR_INVALID_REQUEST",
                       "state_code must be exactly two uppercase letters.")
    weekly_traffic_count = req_int(payload, "weekly_traffic_count", minimum=0)
    sushi_space_sqft = req_int(payload, "sushi_space_sqft", minimum=0)
    case_linear_ft = req_num(payload, "refrigerated_case_linear_ft",
                             exclusive_minimum=0)
    case_capacity = req_int(payload, "refrigerated_case_capacity_packs",
                            exclusive_minimum=0)

    with LOCK:
        row = db.new_row(db.host_stores, {
            "name": name,
            "banner_chain": banner_chain,
            "store_number": store_number,
            "state_code": state_code,
            "weekly_traffic_count": weekly_traffic_count,
            "sushi_space_sqft": sushi_space_sqft,
            "refrigerated_case_linear_ft": float(case_linear_ft),
            "refrigerated_case_capacity_packs": case_capacity,
            "pos_integration_status": "NOT_CONNECTED",
            "pos_terminal_count": 0,
            "attested_sushi_space_sqft": None,
            "attested_case_linear_ft": None,
            "last_attested_on": None,
            "space_compliance_state": "UNVERIFIED",
        })
    return created(db.public(row))


@bp.get("/host-stores/<store_id>")
def get_host_store(store_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_QUALITY_AUDITOR)
    own_store(actor, store_id)
    return ok(db.public(store_or_404(store_id)))


@bp.get("/host-stores")
def list_host_stores():
    authorize(ROLE_FRANCHISOR_OPS, ROLE_QUALITY_AUDITOR)
    rows = filters(list(db.host_stores.values()), {
        "banner_chain": "banner_chain",
        "pos_integration_status": "pos_integration_status",
        "space_compliance_state": "space_compliance_state",
    })
    return paginate(rows)


@bp.post("/host-stores/<store_id>/pos-integration")
def set_pos_integration(store_id):
    actor = authorize(ROLE_HOST_STORE_MANAGER)
    own_store(actor, store_id)
    store = store_or_404(store_id)
    payload = body()
    status = req_enum(payload, "pos_integration_status", POS_STATES)
    terminals = req_int(payload, "pos_terminal_count", minimum=0)
    with LOCK:
        db.apply_changes(store, {
            "pos_integration_status": status,
            "pos_terminal_count": terminals,
        })
    return ok(db.public(store))


@bp.post("/host-stores/<store_id>/space-attestation")
def space_attestation(store_id):
    actor = authorize(ROLE_HOST_STORE_MANAGER)
    own_store(actor, store_id)
    store = store_or_404(store_id)
    payload = body()
    sqft = req_int(payload, "attested_sushi_space_sqft", minimum=0)
    linear_ft = req_num(payload, "attested_case_linear_ft", minimum=0)
    attested_on = req_date(payload, "attested_on")

    with LOCK:
        db.apply_changes(store, {
            "attested_sushi_space_sqft": sqft,
            "attested_case_linear_ft": float(linear_ft),
            "last_attested_on": attested_on,
        })
        state, _ = domain.apply_space_derivation(store)
        db.apply_changes(store, {"space_compliance_state": state})
    return ok(db.public(store))


# ==========================================================================
# License agreements
# ==========================================================================


@bp.post("/license-agreements")
def draft_agreement():
    authorize(ROLE_FRANCHISOR_OPS)
    payload = body()
    fk_lookup(payload, "host_store_id", store_or_404)
    host_store_id = req_str(payload, "host_store_id")
    revenue_share_model = req_enum(payload, "revenue_share_model",
                                   REVENUE_SHARE_MODELS)
    markdown_policy = req_enum(payload, "markdown_policy", MARKDOWN_POLICIES)
    min_space = req_int(payload, "min_space_sqft_obligation", exclusive_minimum=0)
    min_linear = req_num(payload, "min_case_linear_ft_obligation",
                         exclusive_minimum=0)
    credit_rate = req_int(payload, "space_credit_cents_per_sqft", minimum=0)
    effective_from = req_date(payload, "effective_from")
    effective_to = req_date(payload, "effective_to")
    strictly_ordered("effective_from", effective_from, "effective_to", effective_to)

    with LOCK:
        row = db.new_row(db.license_agreements, {
            "host_store_id": host_store_id,
            "status": "DRAFT",
            "revenue_share_model": revenue_share_model,
            "markdown_policy": markdown_policy,
            "min_space_sqft_obligation": min_space,
            "min_case_linear_ft_obligation": float(min_linear),
            "space_credit_cents_per_sqft": credit_rate,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "space_shortfall_sqft": 0,
            "active_kiosk_count": 0,
            "lifetime_share_accrued_cents": 0,
            "suspension_reason": None,
        })
    return created(db.public(row))


@bp.get("/license-agreements/<agreement_id>")
def get_agreement(agreement_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_QUALITY_AUDITOR)
    agreement = agreement_or_404(agreement_id)
    own_store(actor, agreement["host_store_id"])
    return ok(db.public(agreement))


@bp.get("/license-agreements")
def list_agreements():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_QUALITY_AUDITOR)
    rows = list(db.license_agreements.values())
    if actor.is_manager:
        rows = [r for r in rows if r["host_store_id"] == actor.user_id]
    rows = filters(rows, {"host_store_id": "host_store_id", "status": "status"})
    return paginate(rows)


def _require_connected(store):
    if store["pos_integration_status"] != "CONNECTED":
        raise ApiError("ERR_POS_NOT_CONNECTED")


@bp.post("/license-agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authorize(ROLE_FRANCHISOR_OPS)
    agreement = agreement_or_404(agreement_id)
    with LOCK:
        if agreement["status"] not in ("DRAFT", "SUSPENDED"):
            raise ApiError("ERR_LICENSE_INVALID_STATE")
        store = domain.store_of_agreement(agreement)
        _require_connected(store)
        if agreement["status"] == "DRAFT" and store["last_attested_on"] is None:
            raise ApiError("ERR_SPACE_OBLIGATION_DEFICIENT")
        agreement["status"] = "ACTIVE"
        agreement["suspension_reason"] = None
        db.touch(agreement)
        state, shortfalls = domain.apply_space_derivation(store)
        db.apply_changes(store, {"space_compliance_state": state})
    return ok(db.public(agreement))


@bp.post("/license-agreements/<agreement_id>/suspend")
def suspend_agreement(agreement_id):
    authorize(ROLE_FRANCHISOR_OPS)
    agreement = agreement_or_404(agreement_id)
    payload = body()
    reason = req_str(payload, "suspension_reason")
    with LOCK:
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_LICENSE_INVALID_STATE")
        # PRD 3.1: suspension records the reason, moves the agreement, suspends
        # every operating kiosk, sets `active_kiosk_count` to 0 "and the
        # agreement's `version` increments" -- one increment for the request, so
        # the cascaded kiosks must not each bump the agreement as well.
        for kiosk in domain.kiosks_of_agreement(agreement["id"]):
            if kiosk["operational_state"] == "OPERATING":
                domain.suspend_kiosk(kiosk, "LICENSE_SUSPENDED",
                                     refresh_agreement=False)
        agreement["status"] = "SUSPENDED"
        agreement["suspension_reason"] = reason
        agreement["active_kiosk_count"] = 0
        db.touch(agreement)
    return ok(db.public(agreement))


@bp.post("/license-agreements/<agreement_id>/reinstate")
def reinstate_agreement(agreement_id):
    authorize(ROLE_FRANCHISOR_OPS)
    agreement = agreement_or_404(agreement_id)
    with LOCK:
        if agreement["status"] != "SUSPENDED":
            raise ApiError("ERR_LICENSE_INVALID_STATE")
        _require_connected(domain.store_of_agreement(agreement))
        agreement["status"] = "ACTIVE"
        agreement["suspension_reason"] = None
        db.touch(agreement)
    return ok(db.public(agreement))


@bp.post("/license-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    authorize(ROLE_FRANCHISOR_OPS)
    agreement = agreement_or_404(agreement_id)
    payload = body()
    reason = req_str(payload, "termination_reason")
    with LOCK:
        if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_LICENSE_INVALID_STATE")
        for statement in db.settlement_statements.values():
            if statement["license_agreement_id"] != agreement["id"]:
                continue
            if statement["status"] in ("ISSUED", "ACKNOWLEDGED", "DISPUTED"):
                raise ApiError("ERR_LICENSE_INVALID_STATE")
        # PRD 3.1: "`active_kiosk_count` becomes 0, `version` increments" -- again
        # a single increment for the terminating request.
        for kiosk in domain.kiosks_of_agreement(agreement["id"]):
            if kiosk["operational_state"] in ("PROVISIONING", "OPERATING",
                                              "SUSPENDED"):
                domain.decommission_kiosk(kiosk, "LICENSE_TERMINATED",
                                          refresh_agreement=False)
        agreement["status"] = "TERMINATED"
        agreement["suspension_reason"] = reason
        agreement["active_kiosk_count"] = 0
        db.touch(agreement)
    return ok(db.public(agreement))
