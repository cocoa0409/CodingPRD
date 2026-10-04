"""Potato lot endpoints: two-mode intake (CONTRACTED / IMPORT) and disposal.

Validation precedence (PRD 2.10): ownership (3) -> shape (4) -> existence (5,
body FKs in declared input order: contract_id, shortage_event_id, facility_id)
-> state (6) -> quarantine (7) -> delivery window / variety (9) -> capacity (10).
"""

from decimal import Decimal

import calcs
import domain
from db import clock_now, store
from errors import ApiError
from flask import Blueprint, g, request
from middleware import ANY_ROLES, require_roles
from response import list_response, sort_default, success_object
from util import body_json, req_enum, req_number
from constants import DISPOSITIONS, VARIETIES

bp = Blueprint("lots", __name__)


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}': {why}", 400)


@bp.route("/potato-ops/potato-lots", methods=["POST"])
@require_roles("Grower", "GrowerRelationsManager")
def create_lot():
    body = body_json()
    contract_id = body.get("contract_id")
    shortage_event_id = body.get("shortage_event_id")
    has_contract = contract_id is not None
    has_event = shortage_event_id is not None

    # Priority 3: entity-backed ownership / role-by-rule for the two modes.
    # (Evaluated when the mode is determinable; an invalid mode falls through
    # to the priority-4 shape check below.)
    if has_contract and not has_event:
        if g.user_role != "Grower":
            raise ApiError(
                "ERR_OWNERSHIP_MISMATCH",
                "Contracted lot delivery requires the Grower role",
                403,
            )
        known = store.contracts.get(contract_id) if isinstance(contract_id, str) else None
        if known is not None and known["grower_id"] != g.user_id:
            raise ApiError(
                "ERR_OWNERSHIP_MISMATCH",
                "Grower may deliver only against a contract whose grower_id equals X-User-ID",
                403,
            )
    elif has_event and not has_contract:
        if g.user_role != "GrowerRelationsManager":
            raise ApiError(
                "ERR_OWNERSHIP_MISMATCH",
                "Import-mode lot creation requires the GrowerRelationsManager role",
                403,
            )

    # Priority 4: request shape.
    if has_contract == has_event:
        raise ApiError(
            "ERR_LOT_SOURCE_MODE_INVALID",
            "Potato lot creation must carry exactly one of contract_id (CONTRACTED) "
            "or shortage_event_id (IMPORT)",
            400,
        )
    if has_contract and not isinstance(contract_id, str):
        _bad("contract_id", "must be a string")
    if has_event and not isinstance(shortage_event_id, str):
        _bad("shortage_event_id", "must be a string")
    facility_id = body.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id:
        _bad("facility_id", "is required and must be a non-empty string")
    variety = req_enum(body, "variety", VARIETIES)
    gross = req_number(body, "gross_weight_cwt")
    if gross <= 0:
        _bad("gross_weight_cwt", "must be > 0")
    tare = req_number(body, "tare_weight_cwt")
    if tare < 0:
        _bad("tare_weight_cwt", "must be >= 0")
    if tare >= gross:
        _bad("tare_weight_cwt", "must be < gross_weight_cwt")
    defect = req_number(body, "defect_pct")
    if defect < 0 or defect > 100:
        _bad("defect_pct", "must be between 0 and 100")
    gravity = req_number(body, "specific_gravity")
    sugar = req_number(body, "sugar_end_rating")
    if sugar < Decimal("1.0") or sugar > Decimal("5.0"):
        _bad("sugar_end_rating", "must be between 1.0 and 5.0")

    # Priority 5: existence, body FKs in declared input order.
    contract = domain.get_contract_or_404(contract_id) if has_contract else None
    event = domain.get_shortage_event_or_404(shortage_event_id) if has_event else None
    facility = domain.get_facility_or_404(facility_id)

    # Priority 6: state preconditions.
    if contract is not None and contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE",
            "Contracted lot delivery requires the contract ACTIVE",
            409,
        )
    if event is not None and event["status"] != "OPEN":
        raise ApiError(
            "ERR_SHORTAGE_EVENT_NOT_OPEN",
            "Import lot creation requires the shortage event OPEN",
            409,
        )

    # Priority 7: quarantine isolation.
    if facility["posture"] == "QUARANTINED":
        raise ApiError(
            "ERR_FACILITY_QUARANTINED",
            "Lot intake into a QUARANTINED facility is forbidden",
            409,
        )

    # Priority 9: delivery window (inclusive both ends) then variety.
    if contract is not None:
        now = clock_now()
        if not (contract["delivery_window_start"] <= now <= contract["delivery_window_end"]):
            raise ApiError(
                "ERR_OUTSIDE_DELIVERY_WINDOW",
                "Contracted lot delivered outside the contract delivery window",
                422,
            )
        if variety != contract["variety"]:
            raise ApiError(
                "ERR_VARIETY_MISMATCH",
                "Contracted lot variety differs from the contract variety",
                422,
            )

    # Priority 10: facility capacity.
    net = calcs.compute_net_weight(gross, tare)
    free = Decimal(facility["capacity_cwt"]) - domain.current_stock_cwt(facility)
    if free < net:
        raise ApiError(
            "ERR_FACILITY_CAPACITY_EXCEEDED",
            "Lot intake would exceed the facility's capacity_cwt",
            422,
        )

    grade = calcs.compute_grade(defect, gravity, sugar)
    provisional = (
        calcs.provisional_payment(net, contract["base_price_per_cwt_cents"], grade)
        if contract is not None
        else None
    )
    lot = domain.new_entity()
    lot.update({
        "contract_id": contract_id if has_contract else None,
        "shortage_event_id": shortage_event_id if has_event else None,
        "facility_id": facility_id,
        "origin": "CONTRACTED" if has_contract else "IMPORT",
        "variety": variety,
        "gross_weight_cwt": body["gross_weight_cwt"],
        "tare_weight_cwt": body["tare_weight_cwt"],
        "net_weight_cwt": net,
        "defect_pct": body["defect_pct"],
        "specific_gravity": body["specific_gravity"],
        "sugar_end_rating": body["sugar_end_rating"],
        "grade": grade,
        "provisional_payment_cents": provisional,
        "final_payment_cents": None,
        "status": "IN_STORAGE",
        "disposition": None,
    })
    store.lots[lot["id"]] = lot
    domain.touch(facility)  # current_stock_cwt increased (derived-field reconciliation)
    if contract is not None:
        domain.touch(contract)  # delivered_volume_cwt increased
        domain.maybe_auto_fulfill(contract)
    return success_object(domain.lot_view(lot), 201)


@bp.route("/potato-ops/potato-lots", methods=["GET"])
@require_roles(*ANY_ROLES)
def list_lots():
    items = list(store.lots.values())
    contract_id = request.args.get("contract_id")
    facility_id = request.args.get("facility_id")
    shortage_event_id = request.args.get("shortage_event_id")
    status = request.args.get("status")
    if contract_id is not None:
        items = [l for l in items if l.get("contract_id") == contract_id]
    if facility_id is not None:
        items = [l for l in items if l["facility_id"] == facility_id]
    if shortage_event_id is not None:
        items = [l for l in items if l.get("shortage_event_id") == shortage_event_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(sort_default(items), domain.lot_view)


@bp.route("/potato-ops/potato-lots/<lid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_lot(lid):
    return success_object(domain.lot_view(domain.get_lot_or_404(lid)), 200)


@bp.route("/potato-ops/potato-lots/<lid>/dispose", methods=["POST"])
@require_roles("QualityAssuranceLead")
def dispose_lot(lid):
    body = body_json()
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    lot = domain.get_lot_or_404(lid)
    if lot["status"] != "IN_STORAGE":
        raise ApiError(
            "ERR_LOT_NOT_AVAILABLE", "lot must be IN_STORAGE for disposal", 409
        )
    lot["status"] = "DISPOSED"
    lot["disposition"] = disposition
    domain.touch(lot)
    domain.touch(store.facilities[lot["facility_id"]])  # current_stock_cwt decreased
    domain.new_batch(
        source_lot_id=lot["id"],
        source_run_id=None,
        stream="WHOLE_LOT",
        routing=disposition,
        weight_cwt=lot["net_weight_cwt"],
    )
    return success_object(domain.lot_view(lot), 200)
