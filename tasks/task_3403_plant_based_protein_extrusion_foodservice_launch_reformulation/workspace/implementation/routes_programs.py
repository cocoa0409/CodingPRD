# GrowthProgram domain (PRD 3.6): foodservice LTO launches and sampling/demo
# programs, the partner window-gap rule, clock-gated window occupancy, the
# conversion scorecard gates, and the compensating reservation release.
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from services import compute_redemption_rate, recompute_program_attainment
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_bool, get_dt, get_enum, get_int, get_str

bp = Blueprint("programs", __name__, url_prefix="/protein-ops/programs")

ANY_ROLE = constants.ROLES
PROGRAM_STATES = ["PROPOSED", "ACTIVE", "IN_WINDOW", "EVALUATING", "CONVERTED", "CONCLUDED", "TERMINATED"]
PROGRAM_TRANSITIONS = {
    ("PROPOSED", "ACTIVE"),
    ("ACTIVE", "IN_WINDOW"),
    ("IN_WINDOW", "EVALUATING"),
    ("EVALUATING", "CONVERTED"),
    ("EVALUATING", "CONCLUDED"),
    ("PROPOSED", "TERMINATED"),
    ("ACTIVE", "TERMINATED"),
    ("IN_WINDOW", "TERMINATED"),
    ("EVALUATING", "TERMINATED"),
}


@bp.route("", methods=["POST"])
def create_program():
    _user_id, role = authenticate()
    authorize(role, ["ChannelManager"])

    body = body_json()
    shape = Shape()
    program_code = get_str(body, "program_code", shape, non_empty=True)
    program_type = get_enum(body, "program_type", constants.PROGRAM_TYPES, shape)
    product_id = get_str(body, "product_id", shape)
    start_raw, start_dt = get_dt(body, "window_start", shape)
    end_raw, end_dt = get_dt(body, "window_end", shape)
    partner_code = get_str(body, "partner_code", shape, required=False)
    committed_cases = get_int(body, "committed_cases", shape, required=False, minv=1)
    dedicated_run_required = get_bool(body, "dedicated_run_required", shape, required=False, default=True)
    budget_cents = get_int(body, "budget_cents", shape, required=False)
    coupons_issued = get_int(body, "coupons_issued", shape, required=False, minv=0)

    # Tier 3: body FK existence (product_id).
    if product_id is not None and product_id not in db["products"]:
        raise err("ERR_NOT_FOUND", "product_id does not reference a product")

    # Tier 7 temporal: window end must sit after window start.
    if start_dt is not None and end_dt is not None and end_dt <= start_dt:
        raise err("ERR_INVALID_WINDOW", "window_end must be after window_start")

    # Tier 8: uniqueness of program_code.
    if program_code is not None:
        for existing in db["programs"].values():
            if existing["program_code"] == program_code:
                raise err("ERR_UNIQUE_CONSTRAINT", "program_code already exists")

    # Tier 11: type-conditional payloads — mutually exclusive per program type.
    if program_type == "FOODSERVICE_LTO":
        if partner_code is None:
            shape.add("partner_code", "is required for FOODSERVICE_LTO")
        if committed_cases is None:
            shape.add("committed_cases", "is required for FOODSERVICE_LTO")
        if budget_cents is not None:
            shape.add("budget_cents", "must be null for FOODSERVICE_LTO")
        if coupons_issued is not None:
            shape.add("coupons_issued", "must be null for FOODSERVICE_LTO")
    elif program_type == "SAMPLING_DEMO":
        if budget_cents is None:
            shape.add("budget_cents", "is required for SAMPLING_DEMO")
        if partner_code is not None:
            shape.add("partner_code", "must be null for SAMPLING_DEMO")
        if committed_cases is not None:
            shape.add("committed_cases", "must be null for SAMPLING_DEMO")
    shape.raise_if_any()

    if program_type == "SAMPLING_DEMO" and coupons_issued is None:
        coupons_issued = 0

    program = make_entity(
        "programs",
        {
            "program_code": program_code,
            "program_type": program_type,
            "partner_code": partner_code,
            "product_id": product_id,
            "window_start": start_raw,
            "window_end": end_raw,
            "committed_cases": committed_cases,
            "dedicated_run_required": dedicated_run_required,
            "budget_cents": budget_cents,
            "coupons_issued": coupons_issued,
            "coupons_redeemed": 0,
            "delivered_cases": 0,
            "attainment_pct": None,
            "redemption_rate_pct": (
                compute_redemption_rate(0, coupons_issued)
                if program_type == "SAMPLING_DEMO"
                else None
            ),
            "commitment_met": False,
            "status": "PROPOSED",
        },
    )
    program["_dt"]["window_start"] = start_dt
    program["_dt"]["window_end"] = end_dt
    return success(public(program), "object", 201)


@bp.route("", methods=["GET"])
def list_programs():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["programs"].values())
    for param in ("product_id", "program_type", "partner_code", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate([public(p) for p in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<pid>", methods=["GET"])
def get_program(pid):
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    program = db["programs"].get(pid)
    if program is None:
        raise err("ERR_NOT_FOUND", "program not found")
    return success(public(program), "object", 200)


@bp.route("/<pid>/lifecycle", methods=["POST"])
def program_lifecycle(pid):
    _user_id, role = authenticate()
    authorize(role, ["ChannelManager"])

    program = db["programs"].get(pid)
    if program is None:
        raise err("ERR_NOT_FOUND", "program not found")

    body = body_json()
    shape = Shape()
    target = get_enum(body, "target_status", PROGRAM_STATES, shape)
    final_coupons_redeemed = get_int(body, "final_coupons_redeemed", shape, required=False, minv=0)

    # Tier 5: transition must exist from the current state (terminal states
    # CONVERTED/CONCLUDED/TERMINATED reject everything).
    if target is not None and (program["status"], target) not in PROGRAM_TRANSITIONS:
        raise err("ERR_INVALID_STATE", "no program transition %s -> %s" % (program["status"], target))

    if target == "ACTIVE":
        # Tier 7 temporal: the fourteen-day same-partner LTO gap rule.
        if program["program_type"] == "FOODSERVICE_LTO":
            new_start = program["_dt"]["window_start"]
            new_end = program["_dt"]["window_end"]
            gap = timedelta(days=constants.MIN_PROGRAM_GAP_DAYS)
            for other in db["programs"].values():
                if other["id"] == program["id"]:
                    continue
                if other["program_type"] != "FOODSERVICE_LTO":
                    continue
                if other["partner_code"] != program["partner_code"]:
                    continue
                if other["status"] not in ("ACTIVE", "IN_WINDOW", "EVALUATING"):
                    continue
                o_start = other["_dt"]["window_start"]
                o_end = other["_dt"]["window_end"]
                ok = (o_end + gap <= new_start) or (new_end + gap <= o_start)
                if not ok:
                    raise err("ERR_PROGRAM_WINDOW_OVERLAP", "same-partner LTO windows need a 14 day gap")
        # Tier 9 cross-entity: featured product must be PILOT or ACTIVE.
        product = db["products"].get(program["product_id"])
        if product is None or product["status"] not in ("PILOT", "ACTIVE"):
            raise err("ERR_PRODUCT_NOT_PRODUCIBLE", "product status is not PILOT or ACTIVE")
        program["status"] = "ACTIVE"
        mark(program)

    elif target == "IN_WINDOW":
        # Tier 7 temporal: clock inside the window, both bounds inclusive.
        now = clock.now()
        if not (program["_dt"]["window_start"] <= now <= program["_dt"]["window_end"]):
            raise err("ERR_OUTSIDE_TEST_WINDOW", "current clock is outside the test window")
        program["status"] = "IN_WINDOW"
        mark(program)

    elif target == "EVALUATING":
        if program["program_type"] == "SAMPLING_DEMO":
            # Tier 10 capacity: redeemed may not exceed issued.
            if final_coupons_redeemed is not None and final_coupons_redeemed > program["coupons_issued"]:
                raise err("ERR_REDEMPTION_EXCEEDS_ISSUED", "final_coupons_redeemed exceeds coupons_issued")
            # Tier 11: the redemption tally is required to close a sampling window.
            if final_coupons_redeemed is None:
                shape.add("final_coupons_redeemed", "is required when closing a SAMPLING_DEMO window")
            shape.raise_if_any()
            program["coupons_redeemed"] = final_coupons_redeemed
            program["redemption_rate_pct"] = compute_redemption_rate(
                final_coupons_redeemed, program["coupons_issued"]
            )
        else:
            shape.raise_if_any()
            recompute_program_attainment(program)
        program["status"] = "EVALUATING"
        mark(program)

    elif target == "CONVERTED":
        # Conversion scorecard gate.
        if program["program_type"] == "FOODSERVICE_LTO":
            attainment = program["attainment_pct"]
            if attainment is None or not (
                Decimal(str(attainment)) >= constants.LAUNCH_MIN_ATTAINMENT_PCT
            ):
                raise err("ERR_PROGRAM_TARGET_NOT_MET", "attainment_pct below 85.00")
        else:
            rate = program["redemption_rate_pct"]
            if rate is None or not (
                Decimal(str(rate)) >= constants.SAMPLING_MIN_REDEMPTION_PCT
            ):
                raise err("ERR_PROGRAM_TARGET_NOT_MET", "redemption_rate_pct below 12.00")
        shape.raise_if_any()
        program["status"] = "CONVERTED"
        mark(program)

    elif target == "CONCLUDED":
        shape.raise_if_any()
        program["status"] = "CONCLUDED"
        mark(program)

    elif target == "TERMINATED":
        shape.raise_if_any()
        program["status"] = "TERMINATED"
        mark(program)
        # Compensating release: every batch reserved to this program returns
        # its reserved cases to availability.
        for batch in db["batches"].values():
            if batch["reserved_for_program_id"] == program["id"]:
                batch["available_cases"] += batch["reserved_cases"]
                batch["reserved_cases"] = 0
                batch["reserved_for_program_id"] = None
                mark(batch)
    else:
        shape.raise_if_any()  # missing/invalid target_status
        return  # unreachable

    flush_dirty()
    return success(public(program), "object", 200)
