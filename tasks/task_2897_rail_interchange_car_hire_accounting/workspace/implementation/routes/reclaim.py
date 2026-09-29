"""Reclaim claims and embargo orders (PRD section 3.5)."""
from decimal import Decimal

from flask import Blueprint

import db
import middleware
import response
import shapes
from errors import fail
from middleware import endpoint
from services import ledger, money, pricing, serialize, settlement

bp = Blueprint("reclaim", __name__)

SPLIT_FULL = Decimal("1.0")
SPLIT_HALF = Decimal(db.DETENTION_SPLIT_PCT)


def split_for(reason):
    return SPLIT_HALF if reason == "CUSTOMER_DETENTION" else SPLIT_FULL


def movement_junctions(movement):
    ids = set()
    for key in ("received_event_id", "delivered_event_id"):
        event_id = movement.get(key)
        if event_id:
            event = db.events.get(event_id)
            if event is not None:
                ids.add(event["junction_id"])
    return ids


def embargo_coverage_end(order):
    end = order["effective_to"]
    if order["status"] == "LIFTED" and order["lifted_at"] is not None:
        end = min(end, order["lifted_at"])
    return end


def embargo_covers(order, car, movement, window_from, window_to):
    if order["car_type_id"] is not None and order["car_type_id"] != car["car_type_id"]:
        return False
    if order["junction_id"] not in movement_junctions(movement):
        return False
    if window_from < order["effective_from"]:
        return False
    return window_to <= embargo_coverage_end(order)


# --------------------------------------------------------------------------
# filing
# --------------------------------------------------------------------------
@bp.post("/car-hire/reclaim-claims")
@endpoint(roles=[db.ROLE_ACCOUNTANT])
def file_claim():
    body = shapes.body()
    movement_id = shapes.s_id(body, "movement_id")
    reason = shapes.s_str(body, "reason")
    window_from = shapes.s_dt(body, "window_from")
    window_to = shapes.s_dt(body, "window_to")
    expected_movement_version = shapes.s_int(body, "expected_movement_version")
    supporting_embargo_id = shapes.s_id(body, "supporting_embargo_id", required=False)
    detention_notified_at = shapes.s_dt(body, "detention_notified_at", required=False)
    filing_note = shapes.s_str(body, "filing_note", required=False)
    shapes.check_enum("reason", reason, db.RECLAIM_REASON)

    movement = db.lookup("movement", movement_id)
    embargo = None
    if supporting_embargo_id is not None:
        embargo = db.lookup("embargo", supporting_embargo_id)

    # step 9 -- the filing belongs to the handling road
    middleware.require_party(movement["handling_road_id"])
    # step 10 -- optimistic concurrency
    if expected_movement_version != movement["version"]:
        fail("ERR_STALE_VERSION")
    # step 12 -- only a closed segment can be reclaimed against
    if movement["status"] != "CLOSED":
        fail("ERR_MOVEMENT_NOT_CLOSED")
    # step 14 -- an archived cycle is immutable
    cycle = db.cycles.get(movement["settlement_cycle_id"]) if movement["settlement_cycle_id"] else None
    if cycle is not None and cycle["status"] == "ARCHIVED":
        fail("ERR_CYCLE_ARCHIVED_IMMUTABLE")
    # step 18 -- suspension
    middleware.require_active(
        middleware.acting(), movement["handling_road_id"], movement["owner_road_id"]
    )
    # step 26 -- evidence
    car = db.cars.get(movement["car_id"])
    if reason == "BAD_ORDER":
        if movement["bad_order_from"] is None:
            fail("ERR_RECLAIM_EVIDENCE_MISSING")
    elif reason == "EMBARGO":
        if embargo is None:
            fail("ERR_RECLAIM_EVIDENCE_MISSING")
    else:  # CUSTOMER_DETENTION
        if detention_notified_at is None:
            fail("ERR_RECLAIM_EVIDENCE_MISSING")
        if not (window_from <= detention_notified_at < window_to):
            fail("ERR_RECLAIM_EVIDENCE_MISSING")
    # step 27 -- embargo coverage
    if reason == "EMBARGO" and not embargo_covers(embargo, car, movement, window_from, window_to):
        fail("ERR_EMBARGO_DOES_NOT_COVER_WINDOW")
    # step 33 -- the window must lie inside the segment
    if window_from < movement["start_at"] or (
        movement["end_at"] is not None and window_to > movement["end_at"]
    ):
        fail("ERR_RECLAIM_WINDOW_OUTSIDE_MOVEMENT")
    # step 34 -- sixty days from the segment's end, inclusive
    if movement["end_at"] is not None and db.now() > movement["end_at"] + db.days(
        db.RECLAIM_FILING_WINDOW_DAYS
    ):
        fail("ERR_RECLAIM_FILING_WINDOW_EXPIRED")
    # step 40 -- interval ordering
    if window_from >= window_to:
        fail("ERR_INVALID_INTERVAL")
    # step 41 -- minimum reclaimable length
    claimed_hours = money.elapsed_hours(window_from, window_to)
    if claimed_hours < Decimal(db.MIN_RECLAIM_HOURS):
        fail("ERR_RECLAIM_WINDOW_TOO_SHORT")
    # step 42 -- half-open overlap with a live claim
    for other in db.claims.values():
        if other["movement_id"] != movement["id"] or other["status"] not in ("FILED", "ALLOWED"):
            continue
        if window_from < other["window_to"] and other["window_from"] < window_to:
            fail("ERR_RECLAIM_WINDOW_OVERLAP")
    # step 44 -- a penalised segment is locked
    if movement["reclaim_locked"]:
        fail("ERR_MOVEMENT_RECLAIM_LOCKED")

    row = db.base_row()
    row.update(
        {
            "movement_id": movement["id"],
            "filed_by_road_id": movement["handling_road_id"],
            "against_road_id": movement["owner_road_id"],
            "supporting_embargo_id": supporting_embargo_id,
            "reason": reason,
            "window_from": window_from,
            "window_to": window_to,
            "detention_notified_at": detention_notified_at,
            "claimed_hours": claimed_hours,
            "allowed_hours": None,
            "split_pct_applied": None,
            "credit_cents": 0,
            "status": "FILED",
            "filing_note": filing_note,
            "decision_note": None,
            "disallow_reason": None,
            "withdraw_reason": None,
            "decided_at": None,
        }
    )
    db.claims[row["id"]] = row
    db.touch(movement)
    return response.ok(serialize.claim(row), 201)


@bp.get("/car-hire/reclaim-claims")
@endpoint(roles=db.ALL_ROLES)
def list_claims():
    response.page_params()
    reason = shapes.q_enum("reason", db.RECLAIM_REASON)
    status = shapes.q_enum("status", db.RECLAIM_STATUS)
    movement_id = shapes.q_str("movement_id")
    filed_by = shapes.q_str("filed_by_road_id")
    against = shapes.q_str("against_road_id")
    embargo_id = shapes.q_str("supporting_embargo_id")
    rows = list(db.claims.values())
    if reason is not None:
        rows = [r for r in rows if r["reason"] == reason]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if movement_id is not None:
        rows = [r for r in rows if r["movement_id"] == movement_id]
    if filed_by is not None:
        rows = [r for r in rows if r["filed_by_road_id"] == filed_by]
    if against is not None:
        rows = [r for r in rows if r["against_road_id"] == against]
    if embargo_id is not None:
        rows = [r for r in rows if r["supporting_embargo_id"] == embargo_id]
    rows.sort(key=lambda r: (r["window_from"], r["created_at"], r["_seq"]))
    return response.paginate(rows, serialize.claim)


@bp.get("/car-hire/reclaim-claims/<reclaim_claim_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("reclaim_claim_id", "claim")])
def read_claim(claim):
    middleware.party_claim(claim)
    return response.ok(serialize.claim(claim))


# --------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------


def _archived_guard(movement):
    cycle_id = movement["settlement_cycle_id"]
    if not cycle_id:
        return None
    cycle = db.cycles.get(cycle_id)
    if cycle is not None and cycle["status"] == "ARCHIVED":
        fail("ERR_CYCLE_ARCHIVED_IMMUTABLE")
    return cycle


@bp.post("/car-hire/reclaim-claims/<reclaim_claim_id>/allow")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("reclaim_claim_id", "claim")])
def allow_claim(claim):
    body = shapes.body()
    allowed_hours = shapes.s_num(body, "allowed_hours", required=False)
    decision_note = shapes.s_str(body, "decision_note", required=False)

    movement = db.movements[claim["movement_id"]]
    middleware.party_claim(claim)
    if claim["status"] != "FILED":
        fail("ERR_INVALID_STATE_TRANSITION")
    cycle = _archived_guard(movement)
    middleware.require_active(
        middleware.acting(), claim["filed_by_road_id"], claim["against_road_id"]
    )
    if claim["against_road_id"] != middleware.acting() and not middleware.is_admin():
        fail("ERR_RECLAIM_DECISION_NOT_OWNER_ROAD")
    claimed = Decimal(claim["claimed_hours"])
    if allowed_hours is None:
        allowed_hours = claimed
    else:
        allowed_hours = money.half_up_2(allowed_hours)
        if allowed_hours <= 0 or allowed_hours > claimed:
            fail("ERR_INVALID_REQUEST", "allowed_hours must be positive and at most claimed_hours.")

    split = split_for(claim["reason"])
    credit = money.reclaim_credit_cents(
        movement["time_component_cents"], movement["chargeable_hours"], allowed_hours, split
    )
    claim["status"] = "ALLOWED"
    claim["allowed_hours"] = allowed_hours
    claim["split_pct_applied"] = split
    claim["credit_cents"] = credit
    claim["decision_note"] = decision_note
    claim["decided_at"] = db.now()
    db.touch(claim)

    before = int(movement["reclaim_credit_cents"] or 0)
    pricing.apply_waterfall(movement)
    pricing.recompute_net(movement)
    db.touch(movement)
    applied = int(movement["reclaim_credit_cents"] or 0) - before

    if cycle is not None and applied != 0:
        ledger.mint(
            "RECLAIM_CREDIT",
            -applied,
            cycle["payer_road_id"],
            cycle["payee_road_id"],
            "POST /car-hire/reclaim-claims/{id}/allow credited movement %s" % movement["id"],
            settlement_cycle_id=cycle["id"],
            movement_id=movement["id"],
            reclaim_claim_id=claim["id"],
        )
    if cycle is not None:
        settlement.recompute(cycle)
    return response.ok(serialize.claim(claim))


@bp.post("/car-hire/reclaim-claims/<reclaim_claim_id>/disallow")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("reclaim_claim_id", "claim")])
def disallow_claim(claim):
    body = shapes.body()
    disallow_reason = shapes.s_str(body, "disallow_reason")

    movement = db.movements[claim["movement_id"]]
    middleware.party_claim(claim)
    if claim["status"] != "FILED":
        fail("ERR_INVALID_STATE_TRANSITION")
    _archived_guard(movement)
    middleware.require_active(
        middleware.acting(), claim["filed_by_road_id"], claim["against_road_id"]
    )
    if claim["against_road_id"] != middleware.acting() and not middleware.is_admin():
        fail("ERR_RECLAIM_DECISION_NOT_OWNER_ROAD")

    claim["status"] = "DISALLOWED"
    claim["disallow_reason"] = disallow_reason
    claim["credit_cents"] = 0
    claim["decided_at"] = db.now()
    db.touch(claim)
    return response.ok(serialize.claim(claim))


@bp.post("/car-hire/reclaim-claims/<reclaim_claim_id>/withdraw")
@endpoint(roles=[db.ROLE_ACCOUNTANT], path_params=[("reclaim_claim_id", "claim")])
def withdraw_claim(claim):
    body = shapes.body()
    withdraw_reason = shapes.s_str(body, "withdraw_reason")

    movement = db.movements[claim["movement_id"]]
    middleware.party_claim(claim)
    if claim["status"] not in ("FILED", "ALLOWED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    cycle = _archived_guard(movement)
    middleware.require_active(
        middleware.acting(), claim["filed_by_road_id"], claim["against_road_id"]
    )
    if claim["filed_by_road_id"] != middleware.acting() and not middleware.is_admin():
        fail("ERR_RECLAIM_DECISION_NOT_OWNER_ROAD")

    was_allowed = claim["status"] == "ALLOWED"
    claim["status"] = "WITHDRAWN"
    claim["withdraw_reason"] = withdraw_reason
    db.touch(claim)

    if was_allowed:
        before = int(movement["reclaim_credit_cents"] or 0)
        # Withdrawal is a compensating transaction: the claim's own credit
        # returns to 0 before the segment waterfall is re-run from the start.
        claim["credit_cents"] = 0
        pricing.apply_waterfall(movement)
        pricing.recompute_net(movement)
        db.touch(movement)
        removed = before - int(movement["reclaim_credit_cents"] or 0)
        if cycle is not None and removed != 0:
            ledger.mint(
                "RECLAIM_REVERSAL",
                removed,
                cycle["payer_road_id"],
                cycle["payee_road_id"],
                "POST /car-hire/reclaim-claims/{id}/withdraw reversed a credit on movement %s"
                % movement["id"],
                settlement_cycle_id=cycle["id"],
                movement_id=movement["id"],
                reclaim_claim_id=claim["id"],
            )
        if cycle is not None:
            settlement.recompute(cycle)
    return response.ok(serialize.claim(claim))


# --------------------------------------------------------------------------
# embargo orders
# --------------------------------------------------------------------------
@bp.post("/car-hire/embargo-orders")
@endpoint(roles=[db.ROLE_CLERK])
def create_embargo():
    body = shapes.body()
    issuing_road_id = shapes.s_id(body, "issuing_road_id")
    junction_id = shapes.s_id(body, "junction_id")
    car_type_id = shapes.s_id(body, "car_type_id", required=False)
    effective_from = shapes.s_dt(body, "effective_from")
    effective_to = shapes.s_dt(body, "effective_to")
    reason = shapes.s_str(body, "reason")

    db.lookup("railroad", issuing_road_id)
    junction = db.lookup("junction", junction_id)
    if car_type_id is not None:
        db.lookup("car_type", car_type_id)

    middleware.require_active(middleware.acting(), issuing_road_id)
    if issuing_road_id != middleware.acting() or issuing_road_id not in (
        junction["road_a_id"],
        junction["road_b_id"],
    ):
        fail("ERR_EMBARGO_SELF_ISSUED")
    if effective_from >= effective_to:
        fail("ERR_INVALID_INTERVAL")

    cooling = db.hours(24)
    for other in db.embargoes.values():
        if other["status"] != "ACTIVE":
            continue
        if other["junction_id"] != junction_id or other["car_type_id"] != car_type_id:
            continue
        # The new interval must start strictly within the 24 hours following the
        # existing effective_to to conflict: a start exactly one full cooling gap
        # later honours the mandatory gap and is granted.
        if effective_from < other["effective_to"] + cooling and effective_to >= other[
            "effective_from"
        ]:
            fail("ERR_EMBARGO_WINDOW_CONFLICT")

    row = db.base_row()
    row.update(
        {
            "issuing_road_id": issuing_road_id,
            "junction_id": junction_id,
            "car_type_id": car_type_id,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "reason": reason,
            "status": "ACTIVE",
            "lifted_at": None,
        }
    )
    db.embargoes[row["id"]] = row
    return response.ok(serialize.embargo(row), 201)


@bp.get("/car-hire/embargo-orders")
@endpoint(roles=db.ALL_ROLES)
def list_embargoes():
    response.page_params()
    status = shapes.q_enum("status", db.EMBARGO_STATUS)
    issuing = shapes.q_str("issuing_road_id")
    junction_id = shapes.q_str("junction_id")
    car_type_id = shapes.q_str("car_type_id")
    from_from = shapes.q_dt("effective_from_from")
    to_to = shapes.q_dt("effective_to_to")
    rows = list(db.embargoes.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if issuing is not None:
        rows = [r for r in rows if r["issuing_road_id"] == issuing]
    if junction_id is not None:
        rows = [r for r in rows if r["junction_id"] == junction_id]
    if car_type_id is not None:
        rows = [r for r in rows if r["car_type_id"] == car_type_id]
    if from_from is not None:
        rows = [r for r in rows if r["effective_from"] >= from_from]
    if to_to is not None:
        rows = [r for r in rows if r["effective_to"] <= to_to]
    rows.sort(key=lambda r: (r["effective_from"], r["created_at"], r["_seq"]))
    return response.paginate(rows, serialize.embargo)


@bp.get("/car-hire/embargo-orders/<embargo_order_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("embargo_order_id", "embargo")])
def read_embargo(embargo):
    return response.ok(serialize.embargo(embargo))


@bp.post("/car-hire/embargo-orders/<embargo_order_id>/lift")
@endpoint(roles=[db.ROLE_CLERK], path_params=[("embargo_order_id", "embargo")])
def lift_embargo(embargo):
    body = shapes.body()
    lifted_at = shapes.s_dt(body, "lifted_at")

    middleware.require_party(embargo["issuing_road_id"])
    if embargo["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(middleware.acting(), embargo["issuing_road_id"])
    if lifted_at > db.now():
        fail("ERR_EVENT_IN_FUTURE")
    if lifted_at < embargo["effective_from"]:
        fail("ERR_INVALID_INTERVAL")

    embargo["status"] = "LIFTED"
    embargo["lifted_at"] = lifted_at
    db.touch(embargo)
    return response.ok(serialize.embargo(embargo))
