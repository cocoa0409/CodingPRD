"""Placement cycles, arrival notices and charge lines (PRD §3.2 - §3.6)."""

from flask import Blueprint, request

import guards
import schema
from auth import (ROLE_ADJUDICATOR, ROLE_BILLING, ROLE_CUSTOMER, ROLE_RAILROAD,
                  ROLE_REGULATOR, authenticate, require_owner)
from calc import pick_acknowledgeable
from cascade import (finalize_cycle_days, open_agreement_for_release,
                     parents_of, rebuild_agreement_days, recompute_charge,
                     run_election)
from clockcal import add_minutes
from derive import (charge_json, charge_of_cycle, cycle_json,
                    facility_last_switch_at, facility_occupied_spot_count,
                    notification_json, notifications_of_cycle)
from envelope import listing, ok
from errors import fail
from store import base_record, db, touch

bp = Blueprint("cycles", __name__)

REASON_CODES = ("TRACK_FULL", "GATE_CLOSED", "CUSTOMER_HOLD", "EMBARGO",
                "YARD_ARRIVAL")
CHANNELS = ("EDI", "EMAIL", "FAX")
YARD_KINDS = ("RAIL_YARD", "INTERMODAL_TERMINAL")


# --------------------------------------------------------------------------
# shared guards
# --------------------------------------------------------------------------

def _scope_covers(scope, ownership):
    if scope == "ANY":
        return True
    if scope == "PRIVATE":
        return ownership in ("PRIVATE", "PRIVATE_ASSIGNED")
    return ownership == "RAILROAD_OWNED"


def tariff_referential_guard(tariff, car):
    """Ladder band 13, checked in exactly this order."""
    if tariff["status"] == "WITHDRAWN":
        fail("ERR_TARIFF_WITHDRAWN",
             "A withdrawn rule set can never back a placement cycle.")
    if not _scope_covers(tariff["car_ownership_scope"], car["ownership"]):
        fail("ERR_TARIFF_SCOPE_MISMATCH",
             "The rule set's ownership scope does not cover this car.")
    if tariff["status"] not in ("PUBLISHED", "CHALLENGED"):
        fail("ERR_TARIFF_NOT_PUBLISHED", "The rule set is not in force.")


def _charge_kind(facility, car):
    if facility["kind"] in YARD_KINDS:
        return "STORAGE"
    if car["ownership"] == "RAILROAD_OWNED":
        return "DEMURRAGE"
    return "DETENTION"


def _chronology(condition):
    if not condition:
        fail("ERR_NON_CHRONOLOGICAL_EVENT",
             "The supplied instant is inconsistent with the instants already "
             "recorded on this cycle.")


# --------------------------------------------------------------------------
# ordering a car
# --------------------------------------------------------------------------

@bp.post("/placement-cycles")
def create_cycle():
    authenticate(ROLE_RAILROAD)
    data = schema.body()
    with db.lock:
        # Band 7: body references resolve in their declared order.
        customer = tariff = facility = car = None
        raw_customer = schema.opt_ref(data, "customer_id")
        if raw_customer is not None:
            customer = guards.customer(raw_customer)
        raw_car = schema.opt_ref(data, "rail_car_id")
        if raw_car is not None:
            car = guards.rail_car(raw_car)
        raw_facility = schema.opt_ref(data, "facility_id")
        if raw_facility is not None:
            facility = guards.facility(raw_facility)
        raw_tariff = schema.opt_ref(data, "tariff_rule_set_id")
        if raw_tariff is not None:
            tariff = guards.tariff(raw_tariff)

        # Band 8: the schema, including the required-field set.
        customer_id = schema.req_ref(data, "customer_id")
        rail_car_id = schema.req_ref(data, "rail_car_id")
        facility_id = schema.req_ref(data, "facility_id")
        tariff_rule_set_id = schema.req_ref(data, "tariff_rule_set_id")
        waybill = schema.req_str(data, "waybill_number", 1, 24)
        expected = schema.req_int(data, "expected_rail_car_version")

        # Band 11: optimistic concurrency against the car's version.
        if expected != car["version"]:
            fail("ERR_RAIL_CAR_VERSION_STALE",
                 "expected_rail_car_version does not match the rail car.")

        # Band 13: the pinned tariff.
        tariff_referential_guard(tariff, car)

        # Band 15: a car hosts only one live cycle at a time.  The occupation
        # interval is half-open at its upper end.
        now = db.now()
        for other in db.cycles.values():
            if other["rail_car_id"] != rail_car_id:
                continue
            if other["movement_status"] == "VOIDED":
                continue
            released = other.get("released_at")
            if released is None or now < released:
                fail("ERR_CAR_CYCLE_OVERLAP",
                     "The car already hosts a live placement cycle.")

        rec = base_record("cycle")
        rec.update({
            "customer_id": customer_id,
            "rail_car_id": rail_car_id,
            "facility_id": facility_id,
            "tariff_rule_set_id": tariff_rule_set_id,
            "waybill_number": waybill,
            "movement_status": "ORDERED",
            "billing_status": "UNBILLED",
            "constructive_placement_at": None,
            "constructive_reason_code": None,
            "actual_placement_at": None,
            "released_at": None,
            "refusal_count": 0,
            "clock_basis": "NONE",
            "clock_start_at": None,
            "free_days": 0,
            "free_time_expires_at": None,
            "chargeable_days": 0,
            "early_release_days": 0,
        })
        db.cycles[rec["id"]] = rec
        # Creating a cycle is a write against the car.
        touch(car)
        return ok(cycle_json(rec), 201)


@bp.get("/placement-cycles/<cyid>")
def get_cycle(cyid):
    actor = authenticate(ROLE_CUSTOMER, ROLE_RAILROAD, ROLE_ADJUDICATOR,
                         ROLE_BILLING)
    with db.lock:
        rec = guards.cycle(cyid)
        require_owner(actor, rec["customer_id"])
        return ok(cycle_json(rec))


_CYCLE_FILTERS = ("customer_id", "rail_car_id", "facility_id",
                  "tariff_rule_set_id", "movement_status", "billing_status")


@bp.get("/placement-cycles")
def list_cycles():
    actor = authenticate(ROLE_CUSTOMER, ROLE_RAILROAD, ROLE_ADJUDICATOR,
                         ROLE_BILLING)
    with db.lock:
        rows = db.ordered("cycles")
        for name in _CYCLE_FILTERS:
            value = request.args.get(name)
            if value is not None:
                rows = [r for r in rows if r[name] == value]
        if actor.is_customer:
            rows = [r for r in rows if r["customer_id"] == actor.user_id]
        return listing(rows, cycle_json)


# --------------------------------------------------------------------------
# constructive placement - the event that births the charge line
# --------------------------------------------------------------------------

@bp.post("/placement-cycles/<cyid>/constructive-placement")
def constructive_placement(cyid):
    authenticate(ROLE_RAILROAD)
    with db.lock:
        cycle = guards.cycle(cyid)
        data = schema.body()
        moment = schema.req_instant(data, "constructive_placement_at")
        reason = schema.req_enum(data, "reason_code", REASON_CODES)

        if cycle["movement_status"] != "ORDERED":
            fail("ERR_INVALID_MOVEMENT_STATE",
                 "Constructive placement requires an ORDERED cycle.")
        _customer, tariff, facility, car = parents_of(cycle)
        if facility["access_mode"] == "EMBARGOED":
            fail("ERR_FACILITY_EMBARGOED",
                 "An embargoed facility blocks constructive placement.")
        tariff_referential_guard(tariff, car)

        cycle["constructive_placement_at"] = moment
        cycle["constructive_reason_code"] = reason
        cycle["movement_status"] = "CONSTRUCTIVELY_PLACED"

        charge = base_record("charge")
        charge.update({
            "placement_cycle_id": cycle["id"],
            "invoice_id": None,
            "charge_kind": _charge_kind(facility, car),
            "computation_basis": None,
            "chargeable_days": 0,
            "bunching_exempt_days": 0,
            "gross_amount_cents": 0,
            "credit_applied_cents": 0,
            "status": "PROVISIONAL",
        })
        db.charges[charge["id"]] = charge

        # With no arrival notice yet on file the election cannot start a clock.
        run_election(cycle)
        recompute_charge(cycle, charge, final=False)
        touch(cycle)
        return ok(cycle_json(cycle))


# --------------------------------------------------------------------------
# arrival notices
# --------------------------------------------------------------------------

@bp.post("/placement-cycles/<cyid>/notify")
def notify(cyid):
    authenticate(ROLE_RAILROAD)
    with db.lock:
        cycle = guards.cycle(cyid)
        data = schema.body()
        channel = schema.req_enum(data, "channel", CHANNELS)
        sent_at = schema.req_instant(data, "sent_at")

        if cycle["movement_status"] not in ("CONSTRUCTIVELY_PLACED",
                                           "ACTUALLY_PLACED"):
            fail("ERR_INVALID_MOVEMENT_STATE",
                 "A notice can only be sent on a held or spotted car.")
        _chronology(cycle["constructive_placement_at"] is not None
                    and sent_at >= cycle["constructive_placement_at"])

        customer, _tariff, _facility, _car = parents_of(cycle)
        if channel != customer["notification_method"]:
            delivery = "FAILED"
        elif channel == "EDI":
            delivery = "DELIVERED"
        else:
            delivery = "SENT"

        note = base_record("notification", versioned=False)
        note.update({
            "placement_cycle_id": cycle["id"],
            "channel": channel,
            "sent_at": sent_at,
            "delivery_status": delivery,
            "acknowledged_at": None,
        })
        db.notifications[note["id"]] = note

        run_election(cycle)
        charge = charge_of_cycle(cycle["id"])
        if charge is not None and charge["status"] == "PROVISIONAL":
            recompute_charge(cycle, charge, final=False)
        touch(cycle)
        return ok(notification_json(note), 201)


@bp.get("/placement-cycles/<cyid>/notifications")
def list_notifications(cyid):
    actor = authenticate(ROLE_CUSTOMER, ROLE_RAILROAD, ROLE_ADJUDICATOR)
    with db.lock:
        cycle = guards.cycle(cyid)
        require_owner(actor, cycle["customer_id"])
        rows = notifications_of_cycle(cyid)
        status = request.args.get("delivery_status")
        if status is not None:
            rows = [n for n in rows if n["delivery_status"] == status]
        return listing(rows, notification_json)


@bp.post("/placement-cycles/<cyid>/acknowledge-notification")
def acknowledge_notification(cyid):
    actor = authenticate(ROLE_CUSTOMER)
    with db.lock:
        cycle = guards.cycle(cyid)
        require_owner(actor, cycle["customer_id"])
        data = schema.body()
        ack_at = schema.req_instant(data, "ack_at")

        note = pick_acknowledgeable(notifications_of_cycle(cyid))
        if note is None:
            fail("ERR_NO_PENDING_NOTIFICATION",
                 "This cycle has no acknowledgeable arrival notice.")
        _chronology(ack_at >= note["sent_at"])

        note["delivery_status"] = "ACKNOWLEDGED"
        note["acknowledged_at"] = ack_at
        note["_ack_seq"] = db.next_seq()
        # Acknowledgement re-runs the election - which is what finally starts a
        # FAX consignee's clock - but does not itself reprice the line.
        run_election(cycle)
        touch(cycle)
        return ok(notification_json(note))


# --------------------------------------------------------------------------
# spotting, refusal, release and voiding
# --------------------------------------------------------------------------

@bp.post("/placement-cycles/<cyid>/actual-placement")
def actual_placement(cyid):
    authenticate(ROLE_RAILROAD)
    with db.lock:
        cycle = guards.cycle(cyid)
        data = schema.body()
        moment = schema.req_instant(data, "actual_placement_at")

        if cycle["movement_status"] != "CONSTRUCTIVELY_PLACED":
            fail("ERR_INVALID_MOVEMENT_STATE",
                 "Actual placement requires a constructively placed cycle.")
        _customer, _tariff, facility, _car = parents_of(cycle)
        if facility["access_mode"] != "OPEN":
            fail("ERR_FACILITY_NOT_OPEN",
                 "Actual placement requires an OPEN facility.")
        if facility_occupied_spot_count(facility["id"]) >= facility["car_spot_capacity"]:
            fail("ERR_FACILITY_SPOT_UNAVAILABLE", "The track has no spare spot.")
        last_switch = facility_last_switch_at(facility["id"])
        if last_switch is not None and moment < add_minutes(
                last_switch, facility["switch_buffer_minutes"]):
            fail("ERR_FACILITY_SWITCH_BUFFER",
                 "The facility's switch buffer has not elapsed.")
        _chronology(cycle["constructive_placement_at"] is not None
                    and moment >= cycle["constructive_placement_at"])

        cycle["actual_placement_at"] = moment
        cycle["movement_status"] = "ACTUALLY_PLACED"
        run_election(cycle)
        charge = charge_of_cycle(cycle["id"])
        if charge is not None and charge["status"] == "PROVISIONAL":
            recompute_charge(cycle, charge, final=False)
        touch(cycle)
        return ok(cycle_json(cycle))


@bp.post("/placement-cycles/<cyid>/refuse")
def refuse(cyid):
    actor = authenticate(ROLE_CUSTOMER)
    with db.lock:
        cycle = guards.cycle(cyid)
        require_owner(actor, cycle["customer_id"])
        data = schema.body()
        schema.req_str(data, "refusal_reason", 1)

        if cycle["movement_status"] != "ACTUALLY_PLACED":
            fail("ERR_INVALID_MOVEMENT_STATE",
                 "Only a spotted car can be refused.")
        if cycle["refusal_count"] >= 2:
            fail("ERR_REFUSAL_LIMIT", "This cycle has exhausted its refusals.")

        # Setting actual_placement_at back to null flips an ACTUAL basis back to
        # CONSTRUCTIVE and moves free_time_expires_at backwards.
        cycle["actual_placement_at"] = None
        cycle["movement_status"] = "CONSTRUCTIVELY_PLACED"
        cycle["refusal_count"] += 1
        run_election(cycle)
        charge = charge_of_cycle(cycle["id"])
        if charge is not None and charge["status"] == "PROVISIONAL":
            recompute_charge(cycle, charge, final=False)
        touch(cycle)
        return ok(cycle_json(cycle))


@bp.post("/placement-cycles/<cyid>/release")
def release(cyid):
    actor = authenticate(ROLE_CUSTOMER)
    with db.lock:
        cycle = guards.cycle(cyid)
        require_owner(actor, cycle["customer_id"])
        data = schema.body()
        moment = schema.req_instant(data, "released_at")

        customer, _tariff, facility, _car = parents_of(cycle)
        movement = cycle["movement_status"]
        yard = facility["kind"] in YARD_KINDS
        if movement == "ACTUALLY_PLACED":
            industry_path = True
        elif movement == "CONSTRUCTIVELY_PLACED" and yard:
            industry_path = False
        else:
            fail("ERR_INVALID_MOVEMENT_STATE",
                 "This cycle cannot be released from its current state.")

        if facility["access_mode"] == "EMBARGOED":
            fail("ERR_FACILITY_EMBARGOED", "An embargoed facility blocks release.")

        if industry_path:
            _chronology(cycle["actual_placement_at"] is not None
                        and moment >= cycle["actual_placement_at"])
        else:
            _chronology(cycle["constructive_placement_at"] is not None
                        and moment >= cycle["constructive_placement_at"])

        if customer["billing_posture"] != "CURRENT":
            fail("ERR_CUSTOMER_CREDIT_HOLD",
                 "The consignee is on credit hold and cannot release cars.")

        charge = charge_of_cycle(cycle["id"])
        if industry_path and facility["kind"] == "INDUSTRY_TRACK":
            from calc import notification_sent_at as _nsa
            if _nsa(notifications_of_cycle(cycle["id"])) is None:
                fail("ERR_NOTIFICATION_NOT_SENT",
                     "No qualifying arrival notice was ever sent on this cycle.")

        cycle["released_at"] = moment
        cycle["movement_status"] = "RELEASED"
        if charge is not None:
            recompute_charge(cycle, charge, final=True)
            charge["status"] = "FINAL"
            finalize_cycle_days(cycle, charge)
        agreement = open_agreement_for_release(cycle)
        if agreement is not None:
            rebuild_agreement_days(agreement)
            touch(agreement)
        touch(cycle)
        return ok(cycle_json(cycle))


@bp.post("/placement-cycles/<cyid>/void")
def void_cycle(cyid):
    authenticate(ROLE_BILLING)
    with db.lock:
        cycle = guards.cycle(cyid)
        data = schema.body()
        schema.req_str(data, "void_reason", 1)

        if cycle["movement_status"] not in ("ORDERED", "RELEASED"):
            fail("ERR_INVALID_MOVEMENT_STATE",
                 "Only an ORDERED or RELEASED cycle may be voided.")
        charge = charge_of_cycle(cycle["id"])
        invoice = None
        if charge is not None and charge["invoice_id"] is not None:
            invoice = db.invoices.get(charge["invoice_id"])
            if invoice is not None and invoice["status_base"] == "CLOSED":
                fail("ERR_INVOICE_INVALID_STATE",
                     "A cycle on a closed invoice can no longer be voided.")

        cycle["movement_status"] = "VOIDED"
        if charge is not None:
            # The line leaves every aggregate it participated in; both its
            # gross and its credit go together, preserving the money invariant.
            charge["status"] = "VOIDED"
        if invoice is not None:
            touch(invoice)
        agreement = open_agreement_for_release(cycle)
        if agreement is not None:
            rebuild_agreement_days(agreement)
        touch(cycle)
        return ok(cycle_json(cycle))


# --------------------------------------------------------------------------
# charge lines are read-only
# --------------------------------------------------------------------------

@bp.get("/charges/<chid>")
def get_charge(chid):
    actor = authenticate(ROLE_CUSTOMER, ROLE_ADJUDICATOR, ROLE_REGULATOR,
                         ROLE_BILLING)
    with db.lock:
        rec = guards.charge(chid)
        require_owner(actor, guards.owner_of_charge(rec))
        return ok(charge_json(rec))


@bp.get("/charges")
def list_charges():
    actor = authenticate(ROLE_CUSTOMER, ROLE_ADJUDICATOR, ROLE_BILLING)
    with db.lock:
        rows = db.ordered("charges")
        for name in ("placement_cycle_id", "invoice_id", "charge_kind", "status"):
            value = request.args.get(name)
            if value is not None:
                rows = [r for r in rows if r[name] == value]
        if actor.is_customer:
            rows = [r for r in rows
                    if guards.owner_of_charge(r) == actor.user_id]
        return listing(rows, charge_json)
