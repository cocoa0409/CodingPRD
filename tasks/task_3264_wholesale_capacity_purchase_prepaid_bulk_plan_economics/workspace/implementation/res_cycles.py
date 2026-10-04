"""CycleRecord resource: read one, list by term (immutable rows, PRD 2.5)."""

import auth
import respond
import store

ALL_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
             "Subscriber", "RetailPartner"]


def register(app):
    @app.route("/carriers/cycles/<ident>", methods=["GET"])
    def read_cycle(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        record = auth.get_or_404("cycles", ident, "ERR_CYCLE_NOT_FOUND")
        return respond.ok(store.serialize("CycleRecord", record))

    @app.route("/carriers/cycles", methods=["GET"])
    def list_cycles():
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        from flask import request
        args = request.args
        records = list(store.CYCLES.values())
        if args.get("prepaid_term_id"):
            records = [c for c in records if c["prepaid_term_id"] == args["prepaid_term_id"]]
        if args.get("cycle_status"):
            records = [c for c in records if c["cycle_status"] == args["cycle_status"]]
        # Ordering inside a term is by cycle_index; created_at carries no meaning
        # for these rows, so fall back to it only across different terms.
        records.sort(key=lambda c: (c["prepaid_term_id"], c["cycle_index"]))
        return respond.listing("CycleRecord", records, args.get("limit"), args.get("offset"))