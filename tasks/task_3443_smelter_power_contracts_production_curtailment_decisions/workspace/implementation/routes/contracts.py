"""Power contracts (create/read/activate) and interrupt events (PRD 3.2)."""
from flask import Blueprint

from auth import require_roles
from constants import COMPONENT_TYPES, DEFAULT_TAKE_OR_PAY_PCT, ROLES
from db import STORE, bump, logical_clock, new_id, now_wall, stamp_new
from envelope import ok_list, ok_object
from errors import raise_err
from serializers import contract_json, interrupt_event_json
from services.core import (
    contract_year_bounds,
    expire_contracts,
    lazy_expire_contract,
)
from services.pricing import interruptible_hours_used
from util import D, as_datetime, as_enum, as_number, as_str, get_body, parse_pagination, req

bp = Blueprint("contracts", __name__, url_prefix="/smelter-ops")


def get_contract_or_404(contract_id):
    c = STORE["power_contracts"].get(contract_id)
    if c is None:
        raise_err("ERR_NOT_FOUND", "PowerContract not found.")
    return c


def _validate_components(raw):
    if not isinstance(raw, list) or len(raw) < 1:
        raise_err("ERR_INVALID_REQUEST", "components must be a non-empty array.")
    interruptible_count = 0
    for comp in raw:
        if not isinstance(comp, dict):
            raise_err("ERR_INVALID_REQUEST", "Each component must be an object.")
        ctype = as_enum(req(comp, "component_type"), "component_type", COMPONENT_TYPES)
        volume = as_number(req(comp, "volume_mw"), "volume_mw")
        if volume <= 0:
            raise_err("ERR_INVALID_REQUEST", "component volume_mw must be > 0.")
        if ctype == "FIXED":
            price = as_number(
                req(comp, "fixed_price_per_mwh"), "fixed_price_per_mwh"
            )
            if price < 0:
                raise_err(
                    "ERR_INVALID_REQUEST", "fixed_price_per_mwh must be >= 0."
                )
        if ctype == "INTERRUPTIBLE":
            interruptible_count += 1
            cap = as_number(
                req(comp, "interruptible_cap_hours_per_year"),
                "interruptible_cap_hours_per_year",
            )
            if cap <= 0:
                raise_err(
                    "ERR_INVALID_REQUEST",
                    "interruptible_cap_hours_per_year must be > 0.",
                )
    if interruptible_count > 1:
        raise_err(
            "ERR_INVALID_REQUEST",
            "At most one INTERRUPTIBLE component is allowed.",
        )


@bp.post("/power-contracts")
@require_roles("EnergyManager")
def create_contract():
    body = get_body()
    smelter_id = as_str(req(body, "smelter_id"), "smelter_id")
    if STORE["smelters"].get(smelter_id) is None:
        raise_err("ERR_NOT_FOUND", "Smelter not found.")
    supplier = as_str(req(body, "supplier_name"), "supplier_name")
    window_start = as_datetime(req(body, "window_start"), "window_start")
    window_end = as_datetime(req(body, "window_end"), "window_end")
    if not window_start < window_end:
        raise_err(
            "ERR_INVALID_REQUEST", "window_start must be strictly before window_end."
        )
    components = req(body, "components")
    _validate_components(components)
    raw_top = body.get("take_or_pay_pct")
    if raw_top is None:
        take_or_pay = float(DEFAULT_TAKE_OR_PAY_PCT)
    else:
        take_or_pay = as_number(raw_top, "take_or_pay_pct")
        if not (D(take_or_pay) > 0 and D(take_or_pay) <= 1):
            raise_err("ERR_INVALID_REQUEST", "take_or_pay_pct must be in (0, 1].")
    rec = stamp_new(
        {
            "id": new_id(),
            "smelter_id": smelter_id,
            "supplier_name": supplier,
            "window_start": window_start,
            "window_end": window_end,
            "components": components,
            "take_or_pay_pct": take_or_pay,
            "status": "DRAFT",
        }
    )
    STORE["power_contracts"][rec["id"]] = rec
    return ok_object(contract_json(rec), 201)


@bp.get("/power-contracts/<contract_id>")
@require_roles(*ROLES)
def get_contract(contract_id):
    return ok_object(contract_json(get_contract_or_404(contract_id)))


@bp.post("/power-contracts/<contract_id>/activate")
@require_roles("EnergyManager")
def activate_contract(contract_id):
    c = get_contract_or_404(contract_id)
    lazy_expire_contract(c)
    if c["status"] != "DRAFT":
        raise_err(
            "ERR_INVALID_LIFECYCLE_STATE",
            "Only a DRAFT contract can be activated.",
        )
    expire_contracts(c["smelter_id"])
    for other in STORE["power_contracts"].values():
        if (
            other["id"] != c["id"]
            and other["smelter_id"] == c["smelter_id"]
            and other["status"] == "ACTIVE"
            and c["window_start"] < other["window_end"]
            and other["window_start"] < c["window_end"]
        ):
            raise_err(
                "ERR_CONTRACT_WINDOW_OVERLAP",
                "Window overlaps another ACTIVE contract of the smelter.",
            )
    c["status"] = "ACTIVE"
    bump(c)
    return ok_object(contract_json(c))


@bp.post("/interrupt-events")
@require_roles("EnergyManager")
def create_interrupt_event():
    body = get_body()
    contract_id = as_str(req(body, "contract_id"), "contract_id")
    contract = STORE["power_contracts"].get(contract_id)
    if contract is None:
        raise_err("ERR_NOT_FOUND", "PowerContract not found.")
    lazy_expire_contract(contract)
    start_at = as_datetime(req(body, "start_at"), "start_at")
    end_at = as_datetime(req(body, "end_at"), "end_at")
    mw_reduced = as_number(req(body, "mw_reduced"), "mw_reduced")
    now = logical_clock()
    if start_at < contract["window_start"]:
        raise_err(
            "ERR_INVALID_REQUEST", "start_at must be at or after window_start."
        )
    if not end_at > start_at:
        raise_err("ERR_INVALID_REQUEST", "end_at must be strictly after start_at.")
    if start_at > now or end_at > now:
        raise_err(
            "ERR_INVALID_REQUEST",
            "start_at and end_at must not lie after the current logical clock.",
        )
    if mw_reduced <= 0:
        raise_err("ERR_INVALID_REQUEST", "mw_reduced must be > 0.")
    icomp = next(
        (c for c in contract["components"] if c["component_type"] == "INTERRUPTIBLE"),
        None,
    )
    if icomp is None:
        raise_err(
            "ERR_INVALID_REQUEST", "Contract has no INTERRUPTIBLE component."
        )
    if D(mw_reduced) > D(icomp["volume_mw"]):
        raise_err(
            "ERR_INVALID_REQUEST",
            "mw_reduced must not exceed the INTERRUPTIBLE component volume_mw.",
        )
    hours = (end_at - start_at).total_seconds() / 3600.0
    cap = D(icomp["interruptible_cap_hours_per_year"])
    year_start, year_end = contract_year_bounds(contract)
    used = interruptible_hours_used(contract)
    counted = hours if year_start <= start_at < year_end else 0.0
    if D(used + counted) > cap:
        raise_err(
            "ERR_INTERRUPTIBLE_CAP_EXCEEDED",
            "Cumulative interruptible hours would exceed the contract-year cap.",
        )
    rec = {
        "id": new_id(),
        "contract_id": contract_id,
        "start_at": start_at,
        "end_at": end_at,
        "mw_reduced": mw_reduced,
        "hours": hours,
        "created_at": now_wall(),
    }
    STORE["interrupt_events"][rec["id"]] = rec
    return ok_object(interrupt_event_json(rec), 201)


@bp.get("/power-contracts/<contract_id>/interrupt-events")
@require_roles(*ROLES)
def list_interrupt_events(contract_id):
    get_contract_or_404(contract_id)
    limit, offset = parse_pagination()
    items = [
        r for r in STORE["interrupt_events"].values() if r["contract_id"] == contract_id
    ]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page = items[offset : offset + limit]
    return ok_list([interrupt_event_json(r) for r in page], limit, offset, len(items))
