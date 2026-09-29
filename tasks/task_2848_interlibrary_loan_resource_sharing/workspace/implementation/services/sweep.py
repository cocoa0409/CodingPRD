"""The nightly operational sweep (PRD 3.9).

Eight steps in a pinned order, each observing the effects of the ones before
it.  Within a step rows are processed in ascending created_at order, tie-broken
by the ascending created_at of the parent request, and a second run at the same
logical clock performs no writes and returns all-zero counters.
"""
from db import add_days, db, iso_ms, now, touch
from services import calc, derive


def _parent_created(request_id):
    req = db.requests.get(request_id)
    return req["created_at"] if req is not None else now()


def _ordered(rows, request_key="request_id"):
    return sorted(rows, key=lambda r: (r["created_at"],
                                       _parent_created(r.get(request_key)),
                                       r["_seq"]))


def _self_ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def run_sweep():
    from routes.fulfilment import create_return_parcel
    from routes.pod import open_order

    clock = now()
    counters = {
        "agreements_expired": 0,
        "offers_expired": 0,
        "recalls_breached": 0,
        "pickups_abandoned": 0,
        "deliveries_expired": 0,
        "shipments_lost": 0,
        "requests_escalated": 0,
        "requests_unfilled": 0,
        "patrons_blocked": 0,
    }

    # --- step 1: expire reciprocity agreements ----------------------------
    for agreement in _self_ordered([a for a in db.agreements.values()
                                    if a["status"] == "ACTIVE"
                                    and clock >= a["effective_to"]]):
        agreement["status"] = "EXPIRED"
        touch(agreement)
        counters["agreements_expired"] += 1

    # --- step 2: expire supply offers -------------------------------------
    for offer in _ordered([o for o in db.offers.values()
                           if o["status"] == "OFFERED"
                           and clock >= o["respond_by"]]):
        offer["status"] = "EXPIRED"
        touch(offer)
        counters["offers_expired"] += 1
        req = db.requests.get(offer["request_id"])
        if req is not None and req["status"] == "OFFER_PENDING":
            # no refund of the rota budget: attempt_count is left alone
            req["status"] = "SOURCING"
            touch(req)

    # --- step 3: breach recalls -------------------------------------------
    for loan in _ordered([l for l in db.loans.values()
                          if l["recall_status"] == "RECALL_ISSUED"
                          and l["recall_due_at"] is not None
                          and clock > l["recall_due_at"]]):
        loan["recall_status"] = "RECALL_BREACHED"
        touch(loan)
        counters["recalls_breached"] += 1

    # --- step 4: abandon hold-shelf items ---------------------------------
    for loan in _ordered([l for l in db.loans.values()
                          if l["custody_status"] == "AWAITING_PICKUP"
                          and clock >= l["pickup_expires_at"]]):
        loan["custody_status"] = "UNCLAIMED_RETURN_PREPARED"
        loan["return_prepared_at"] = clock
        touch(loan)
        counters["pickups_abandoned"] += 1
        req = db.requests.get(loan["request_id"])
        if req is None:
            continue
        create_return_parcel(req)
        req["status"] = "UNCLAIMED"
        req["closed_at"] = clock
        touch(req)
        bib = db.bib_items.get(req["bib_item_id"]) or {}
        derive.notify(req, "UNCLAIMED",
                      "Hold shelf item not collected: %s" % bib.get("title", ""))
        derive.recompute_patron_for_request(
            req, ("unclaimed_count", "open_request_count", "final_risk_score"))

    # --- step 5: expire electronic access ---------------------------------
    for delivery in _ordered([d for d in db.deliveries.values()
                              if d["status"] == "AVAILABLE"
                              and clock >= d["expires_at"]]):
        delivery["status"] = "EXPIRED"
        touch(delivery)
        counters["deliveries_expired"] += 1
        req = db.requests.get(delivery["request_id"])
        if req is None:
            continue
        req["status"] = "CLOSED"
        req["closed_at"] = clock
        touch(req)
        bib = db.bib_items.get(req["bib_item_id"]) or {}
        derive.notify(req, "DELIVERY_EXPIRED",
                      "Electronic access closed: %s" % bib.get("title", ""))
        derive.recompute_patron_for_request(req, ("open_request_count",))

    # --- step 6: write off transit failures -------------------------------
    deadline = add_days(clock, -calc.TRANSIT_SLA_DAYS)
    for shipment in _ordered([s for s in db.shipments.values()
                              if s["direction"] == "INBOUND"
                              and s["status"] == "IN_TRANSIT"
                              and s["shipped_at"] is not None
                              and s["shipped_at"] <= deadline]):
        shipment["status"] = "LOST_IN_TRANSIT"
        touch(shipment)
        counters["shipments_lost"] += 1
        req = db.requests.get(shipment["request_id"])
        if req is None:
            continue
        req["status"] = "UNFILLED"
        req["unfilled_reason"] = "TRANSIT_LOST"
        req["closed_at"] = clock
        touch(req)
        bib = db.bib_items.get(req["bib_item_id"]) or {}
        derive.notify(req, "REQUEST_UNFILLED",
                      "Parcel lost in transit: %s" % bib.get("title", ""))

    # --- step 7: dispose of exhausted rotas -------------------------------
    exhausted = []
    for req in db.requests.values():
        if req["status"] != "SOURCING":
            continue
        rota = db.rotas.get(req["rota_id"])
        if rota is None:
            continue
        if req["attempt_count"] >= rota["max_attempts"]:
            exhausted.append(req)
    for req in _self_ordered(exhausted):
        rota = db.rotas[req["rota_id"]]
        bib = db.bib_items.get(req["bib_item_id"]) or {}
        if rota["auto_escalate_pod"]:
            open_order(req, None, "system")
            counters["requests_escalated"] += 1
        else:
            req["status"] = "UNFILLED"
            req["unfilled_reason"] = "ATTEMPTS_EXHAUSTED"
            req["closed_at"] = clock
            touch(req)
            derive.notify(req, "REQUEST_UNFILLED",
                          "No lender could supply: %s" % bib.get("title", ""))
            derive.recompute_patron_for_request(req, ("open_request_count",))
            counters["requests_unfilled"] += 1

    # --- step 8: re-derive standing ---------------------------------------
    for patron in _self_ordered(list(db.patrons.values())):
        was_blocked = patron["status"] == "BLOCKED"
        derive.recompute_patron(patron, ("final_risk_score",), block=True)
        if not was_blocked and patron["status"] == "BLOCKED":
            counters["patrons_blocked"] += 1

    summary = {"ran_at": iso_ms(clock)}
    summary.update(counters)
    return summary
