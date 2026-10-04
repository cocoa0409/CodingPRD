"""SubTicket queue group (PRD 3.4)."""
from decimal import Decimal

from errors import fail, invalid
from http_support import (
    Endpoint, as_int, as_list, as_number, as_string, body, envelope_array,
    opt, query, req,
)
from response import ok_object
from util import parse_dt, to_dec
import calc
import services as svc
import views

READ_ROLES = ["PlatformAdmin", "DeliManager", "DeliClerk", "BakeryCoordinator",
              "ScaleOperator"]
CLERK_ROLES = ["DeliClerk", "DeliManager"]

CHANNELS = ("IN_STORE", "DIGITAL", "PHONE")
QUEUE_DEPTH_GATE = 8


def register(app):
    Endpoint(app, "POST", "/deli/sub-tickets", CLERK_ROLES, create_ticket)
    Endpoint(app, "GET", "/deli/sub-tickets/<id>", READ_ROLES, get_ticket)
    Endpoint(app, "GET", "/deli/sub-tickets", READ_ROLES, list_tickets)
    Endpoint(app, "POST", "/deli/sub-tickets/<id>/ticket", CLERK_ROLES, ticket)
    Endpoint(app, "POST", "/deli/sub-tickets/<id>/complete", CLERK_ROLES, complete)
    Endpoint(app, "POST", "/deli/sub-tickets/<id>/pickup", CLERK_ROLES, pickup)
    Endpoint(app, "POST", "/deli/sub-tickets/<id>/abandon", CLERK_ROLES, abandon)
    Endpoint(app, "POST", "/deli/sub-tickets/<id>/requeue", CLERK_ROLES, requeue)
    Endpoint(app, "GET", "/deli/sub-queue", READ_ROLES, queue)


def create_ticket(store, actor, view_args):
    payload = body()
    store_id = as_string(req(payload, "store_id"), "store_id")
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    item = svc.get_item(store, as_string(req(payload, "deli_item_id"), "deli_item_id"))
    bread_item = svc.get_item(
        store, as_string(req(payload, "bread_deli_item_id"), "bread_deli_item_id"))
    channel = req(payload, "order_channel")
    if channel not in CHANNELS:
        invalid("order_channel must be one of %s." % ", ".join(CHANNELS))

    raw_lines = as_list(req(payload, "lines"), "lines")
    if not raw_lines:
        fail("ERR_EMPTY_CART", )
    lines = []
    for index, entry in enumerate(raw_lines):
        if not isinstance(entry, dict):
            invalid("each line must be an object.")
        line_item_id = as_string(req(entry, "deli_item_id"), "lines[].deli_item_id")
        svc.get_item(store, line_item_id)
        units = as_int(req(entry, "half_lb_units"), "lines[].half_lb_units")
        if units < 1:
            fail("ERR_EMPTY_CART", )
        lines.append({
            "deli_item_id": line_item_id,
            "half_lb_units": units,
            "line_sequence_number": index,
        })

    weight = sum((to_dec(line["half_lb_units"]) * calc.HALF_LB_UNIT for line in lines),
                 Decimal(0))

    # Priority 6: pickup-window lockout.
    if svc.pickup_window_lockout(store, store_id):
        fail("ERR_HACCP_WINDOW_FREEZE")
    if store.stores[store_id]["haccp_safety_flag"]:
        fail("ERR_HACCP_HOLD")
    # Priority 8: HALT blocks fresh work; RESTRICTED deliberately does not.
    if store.stores[store_id]["posture"] == "HALT":
        fail("ERR_POSTURE_HALT")

    store.seq["ticket_sequence:%s" % store_id] = \
        store.seq.get("ticket_sequence:%s" % store_id, 0) + 1
    sequence = store.seq["ticket_sequence:%s" % store_id]

    row = svc.create(store, "sub_tickets", {
        "store_id": store_id,
        "deli_item_id": item["id"],
        "bread_deli_item_id": bread_item["id"],
        "order_channel": channel,
        "placed_by_customer_ref": opt(payload, "placed_by_customer_ref"),
        "lines": lines,
        "creation_sequence": sequence,
        "ticket_number": sequence,
        "queue_position": 0,
        "weight_lbs": weight,
        "status": "QUEUED",
        "promised_at": None,
        "completed_at": None,
        "line_total_cents": 0,
        "lateness_minutes": 0,
        "remake_count": 0,
        "label_id": None,
        "bread_status": "QUEUED",
    })
    svc.recompute_ticket_price(store, row)
    svc.touch(store, row)
    svc.recompute_queue(store, store_id)
    svc.recompute_bread(store, store_id)
    return ok_object(store, views.ticket(row), 201)


def get_ticket(store, actor, view_args):
    row = svc.get_plain(store, "sub_tickets", view_args["id"])
    svc.sync_ticket_progress(store, [row])
    return ok_object(store, views.ticket(row))


def list_tickets(store, actor, view_args):
    rows = svc.all_rows(store, "sub_tickets")
    svc.sync_ticket_progress(store, rows)
    for name, key in (("store_id", "store_id"), ("status", "status"),
                      ("order_channel", "order_channel"),
                      ("deli_item_id", "deli_item_id"),
                      ("bread_deli_item_id", "bread_deli_item_id")):
        value = query(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    # The sub-ticket list is explicitly ordered by its per-store sequence.
    return envelope_array(store, rows, views.ticket,
                          sort_key=lambda r: (r["store_id"], r["creation_sequence"]))


def ticket(store, actor, view_args):
    row = svc.get_plain(store, "sub_tickets", view_args["id"])
    store_id = row["store_id"]
    store_row = svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    svc.recompute_queue(store, store_id)

    # Priority 5: required state.
    if row["status"] != "QUEUED":
        fail("ERR_INVALID_STATE")
    # Priority 6: pickup-window lockout.
    if svc.pickup_window_lockout(store, store_id):
        fail("ERR_HACCP_WINDOW_FREEZE")
    if store_row["haccp_safety_flag"]:
        fail("ERR_HACCP_HOLD")
    # Priority 8: only HALT blocks ticketing.
    if store_row["posture"] == "HALT":
        fail("ERR_POSTURE_RESTRICTED")
    # Priority 16: certified staff.
    if store_row["certified_slicer_operator_count"] < 1:
        fail("ERR_NO_CERTIFIED_STAFF")
    # Priority 17: a CLEAN slicer for every slicer-required line.
    for line in row["lines"]:
        line_item = store.items.get(line["deli_item_id"])
        if line_item is None or not line_item["slicer_required"]:
            continue
        if not any(s["store_id"] == store_id and s["sanitation_status"] == "CLEAN"
                   for s in svc.all_rows(store, "slicers")):
            fail("ERR_NO_CLEAN_SLICER")
    # Priority 22: bread availability.
    if row["bread_status"] != "QUEUED":
        fail("ERR_BREAD_UNAVAILABLE")
    # Priority 41: queue-depth gate counts the eligible set only.
    eligible = calc.sub_queue_order(svc.all_rows(store, "sub_tickets"), store_id)
    if len(eligible) >= QUEUE_DEPTH_GATE:
        fail("ERR_QUEUE_DEPTH_BREACH")

    row["status"] = "TICKETED"
    row["ticket_number"] = row["creation_sequence"]
    promised, _ = calc.promised_time_sla(row, svc.batch_code_index(store), store.now())
    row["promised_at"] = promised
    svc.touch(store, row)
    svc.recompute_queue(store, store_id)
    svc.recompute_bread(store, store_id)
    return ok_object(store, views.ticket(row))


def complete(store, actor, view_args):
    payload = body()
    row = svc.get_plain(store, "sub_tickets", view_args["id"])
    store_id = row["store_id"]
    store_row = svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)

    # A station begins the build automatically once its prerequisites hold, so
    # the completion path advances an eligible TICKETED ticket the same way a
    # read would; anything else is a genuine state violation.
    svc.sync_ticket_progress(store, [row])
    if row["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE")

    net_weight = as_number(req(payload, "net_weight_lbs"), "net_weight_lbs")
    if net_weight <= 0 or net_weight > 10:
        fail("ERR_LABEL_WEIGHT_EXCEEDED", )

    # Priority 18: allergen coverage against the completing associate.
    if actor.entity_backed:
        associate = svc.get_associate(store, actor.id)
        covered = set(associate["allergy_set"])
        for line in row["lines"]:
            need = set(svc.item_allergens(store, line["deli_item_id"]))
            if not need.issubset(covered):
                fail("ERR_ALLERGY_HOLD_ACTIVE")
    # Priority 19: case weight sufficiency, per line at half the line poundage.
    for line in row["lines"]:
        required = to_dec(line["half_lb_units"]) * calc.HALF_LB_UNIT * to_dec("0.5")
        if to_dec(store_row["case_on_hand_lbs"]) < required:
            fail("ERR_SHELF_OUT")
    # Priority 20: price-file currency.
    if store_row["active_price_file_id"] is None:
        fail("ERR_PRICE_FILE_STALE")
    # Priority 22: bread availability.
    if row["bread_status"] != "QUEUED":
        fail("ERR_BREAD_UNAVAILABLE")

    row["completed_at"] = store.now()
    row["lateness_minutes"] = calc.lateness_minutes(row["completed_at"],
                                                    row["promised_at"])
    # Priorities 39 and 40: the store's completed-ticket slip basis.
    #
    # PRD §3.4 states the governing rule as a summary sentence -- "a store is
    # allowed exactly one late completion, and the grace it grants is the grace it
    # must then keep" -- so the first late completion passes vacuously (an empty
    # prior set, whose newest lateness reads as zero) and establishes the basis T,
    # and every later completion must land within T minutes of its own
    # `promised_at`. A later completion beyond T is the slip-lock violation.
    basis = 0
    for other in svc.all_rows(store, "sub_tickets"):
        if other["id"] == row["id"] or other["store_id"] != store_id:
            continue
        if other["status"] in ("COMPLETED", "PICKED_UP"):
            basis = max(basis, other["lateness_minutes"])
    if basis > 0 and row["lateness_minutes"] > basis:
        fail("ERR_SLIP_LOCK_VIOLATED")

    svc.recompute_ticket_price(store, row)
    row["status"] = "COMPLETED"
    svc.touch(store, row)

    # PRD §3.6: the label's `unit_price_cents` is "resolved from the ACTIVE
    # scale price file". The labelled subject is the sub being built, so the
    # price comes from the ticket's own line items rather than from the ticket's
    # top-level catalog row (which for a SUB item is the sub shell, not its
    # sliced contents).
    label_item = svc.get_item(store, row["lines"][0]["deli_item_id"]) \
        if row["lines"] else svc.get_item(store, row["deli_item_id"])
    label = svc.synthesize_label(
        store, store_id, "SUB_TICKET", row["id"], net_weight,
        svc.unit_price_for(store, label_item), sub_ticket_id=row["id"])
    row["label_id"] = label["id"]
    svc.touch(store, row)
    svc.recompute_queue(store, store_id)
    svc.recompute_bread(store, store_id)
    return ok_object(store, views.ticket(row))


def pickup(store, actor, view_args):
    row = svc.get_plain(store, "sub_tickets", view_args["id"])
    store_id = row["store_id"]
    svc.get_store(store, store_id)
    svc.recompute_store(store, store_id)
    if row["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE")
    # Priority 21: the label must still be ISSUED.
    label = store.labels.get(row["label_id"]) if row["label_id"] else None
    if label is None or label["status"] != "ISSUED":
        fail("ERR_LABEL_STALE")
    row["status"] = "PICKED_UP"
    svc.touch(store, row)
    svc.recompute_queue(store, store_id)
    svc.recompute_bread(store, store_id)
    return ok_object(store, views.ticket(row))


def abandon(store, actor, view_args):
    row = svc.get_plain(store, "sub_tickets", view_args["id"])
    svc.get_store(store, row["store_id"])
    svc.recompute_store(store, row["store_id"])
    if row["status"] != "QUEUED":
        fail("ERR_INVALID_STATE")
    svc.abandon_ticket(store, row)
    svc.recompute_queue(store, row["store_id"])
    return ok_object(store, views.ticket(row))


def requeue(store, actor, view_args):
    row = svc.get_plain(store, "sub_tickets", view_args["id"])
    svc.get_store(store, row["store_id"])
    svc.recompute_store(store, row["store_id"])
    if row["status"] != "REMADE":
        fail("ERR_INVALID_STATE")
    row["status"] = "QUEUED"
    svc.touch(store, row)
    svc.recompute_queue(store, row["store_id"])
    return ok_object(store, views.ticket(row))


def queue(store, actor, view_args):
    from http_support import pagination
    limit, offset = pagination()
    store_id = query("store_id")
    if store_id is not None:
        svc.get_store(store, store_id)
        eligible = calc.sub_queue_order(svc.all_rows(store, "sub_tickets"), store_id)
    else:
        eligible = []
        for store_row in svc.all_rows(store, "stores"):
            eligible.extend(calc.sub_queue_order(
                svc.all_rows(store, "sub_tickets"), store_row["id"]))
        eligible.sort(key=lambda t: (parse_dt(t["promised_at"]), t["creation_sequence"]))
    window = eligible[offset:offset + limit]
    return ok_object(store, {
        "store_id": store_id,
        "queue_depth": len(eligible),
        "ordered_total_count": len(eligible),
        "ordered": [views.ticket(ticket) for ticket in window],
    })