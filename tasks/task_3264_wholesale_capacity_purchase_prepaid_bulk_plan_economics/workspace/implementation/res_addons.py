"""AddOn resource: request, read, list, activate, cancel (M11)."""

import auth
import calcs
import respond
import store
from errors import ApiError
from store import add_days, iso, now, parse_ts, touch

READ_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
              "Subscriber"]
LIST_ROLES = READ_ROLES
CREATE_ROLES = ["Subscriber"]
CANCEL_ROLES = ["Subscriber"]
PLANNER = ["CapacityPlanner"]

TYPES = ("ROAMING", "INTERNATIONAL_LD")
WINDOWS = (1, 7, 30)


def _get(ident):
    return auth.get_or_404("addons", ident, "ERR_ADDON_NOT_FOUND")


def _subscriber_of(addon):
    subscriber = store.SUBSCRIBERS.get(addon["subscriber_id"])
    if subscriber is None:
        raise ApiError("ERR_SUBSCRIBER_NOT_FOUND")
    return subscriber


def register(app):
    @app.route("/carriers/add-ons", methods=["POST"])
    def create_addon():
        uid, role = auth.actor()
        auth.require_role(uid, role, CREATE_ROLES)
        data = auth.body()
        auth.check_fields(data, ["subscriber_id", "addon_type", "addon_days",
                                 "per_day_allotment_mb"])
        subscriber = auth.get_or_404("subscribers", auth.string(data, "subscriber_id"),
                                     "ERR_SUBSCRIBER_NOT_FOUND")
        auth.require_owner(uid, role, subscriber["id"], "subscriber")
        # The activity gate (validation priority 15) governs consuming data and
        # *activating* an add-on, not requesting one: SCAFFOLD priority 15 applies to
        # "POST /add-ons ... /activate, POST /subscribers/{id}/consume_data", PRD 3.4
        # words the gate for "a consume_data call or a new add-on" while PRD 3.8 scopes
        # "admitted only when the parent subscriber is ACTIVE" to the activation, and
        # PRD 3.3 gates suspension on *activating* add-ons. A request therefore opens
        # in REQUESTED regardless, and the gates are applied on activation.
        addon_type = auth.string(data, "addon_type")
        if addon_type not in TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "addon_type must be ROAMING or INTERNATIONAL_LD")
        addon_days = auth.integer(data, "addon_days")
        allotment = auth.integer(data, "per_day_allotment_mb")
        # Priority 20: window and allotment validity. PRD 3.8: "The window must be one
        # of 1, 7, or 30 days, and the daily allotment must be 0 for an international
        # long-distance add-on and at least 1 megabyte for a roaming add-on; a request
        # that violates either is rejected with ERR_INVALID_ADDON_WINDOW (HTTP 422)."
        if addon_days not in WINDOWS:
            raise ApiError("ERR_INVALID_ADDON_WINDOW")
        if addon_type == "INTERNATIONAL_LD" and allotment != 0:
            raise ApiError("ERR_INVALID_ADDON_WINDOW",
                           "per_day_allotment_mb must be 0 for INTERNATIONAL_LD")
        if addon_type == "ROAMING" and allotment < 1:
            raise ApiError("ERR_INVALID_ADDON_WINDOW",
                           "per_day_allotment_mb must be at least 1 for ROAMING")
        record = store.stamp({
            "subscriber_id": subscriber["id"],
            "addon_type": addon_type,
            "addon_status": "REQUESTED",
            "addon_price_cents": 0,
            "per_day_allotment_mb": allotment,
            "addon_days": addon_days,
            "start_at": None,
            "end_at": None,
            "deprovisioned_msisdn": None,
        })
        store.ADDONS[record["id"]] = record
        return respond.created(store.serialize("AddOn", record))

    @app.route("/carriers/add-ons/<ident>", methods=["GET"])
    def read_addon(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, READ_ROLES)
        return respond.ok(store.serialize("AddOn", _get(ident)))

    @app.route("/carriers/add-ons", methods=["GET"])
    def list_addons():
        uid, role = auth.actor()
        auth.require_role(uid, role, LIST_ROLES)
        from flask import request
        args = request.args
        records = list(store.ADDONS.values())
        if args.get("subscriber_id"):
            records = [a for a in records if a["subscriber_id"] == args["subscriber_id"]]
        if args.get("addon_status"):
            records = [a for a in records if a["addon_status"] == args["addon_status"]]
        if args.get("addon_type"):
            records = [a for a in records if a["addon_type"] == args["addon_type"]]
        return respond.listing("AddOn", store.by_created(records),
                               args.get("limit"), args.get("offset"))

    @app.route("/carriers/add-ons/<ident>/activate", methods=["POST"])
    def activate_addon(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        addon = _get(ident)
        data = auth.body()
        auth.check_fields(data, [])
        if addon["addon_status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "add-on is %s" % addon["addon_status"])
        subscriber = _subscriber_of(addon)
        # Priority 15: subscriber and term activity. PRD 3.3: "While suspended, the
        # subscriber cannot take new add-ons — the attempt is rejected with
        # ERR_SUBSCRIBER_NOT_ACTIVE (HTTP 409)", so suspension is its own gate ahead of
        # the term. Any other non-live subscriber falls to the term gate, because PRD
        # 3.8 gates activation on the subscriber being ACTIVE and the term being
        # ACTIVE or ACTIVE_RENEWAL.
        if subscriber["subscriber_status"] == "SUSPENDED":
            raise ApiError("ERR_SUBSCRIBER_NOT_ACTIVE")
        term = calcs.current_term(subscriber["id"])
        if term is None or term["term_status"] not in calcs.LIVE_TERM:
            raise ApiError("ERR_TERM_NOT_ACTIVE")
        # Priority 20: window validity still applies on activation.
        terminal = now()
        start_at = iso(terminal)
        end_at = iso(add_days(terminal, addon["addon_days"]))
        # Priority 27: half-open window overlap, checked last.
        overlap = False
        for other in store.ADDONS.values():
            if other["id"] == addon["id"] or other["subscriber_id"] != addon["subscriber_id"]:
                continue
            if other["addon_status"] != "ACTIVE":
                continue
            other_start = parse_ts(other.get("start_at"))
            other_end = parse_ts(other.get("end_at"))
            if other_start is None or other_end is None:
                continue
            if terminal < other_end and other_start < add_days(terminal, addon["addon_days"]):
                overlap = True
                break
        # PRD 2.10 orders the cascade state -> ... -> constraint -> duplicate ->
        # ... -> add-on window (20) -> ... -> add-on window overlap (27). The window
        # and allotment constraint must therefore be evaluated *before* the overlap
        # check, so an illegal 14-day window for a suspended subscriber reports the
        # subscriber and term state and then, once both are live, still reports the
        # window rather than the overlap.
        if addon["addon_days"] not in WINDOWS:
            raise ApiError("ERR_INVALID_ADDON_WINDOW")
        if addon["addon_type"] == "INTERNATIONAL_LD" and addon["per_day_allotment_mb"] != 0:
            raise ApiError("ERR_INVALID_ADDON_WINDOW",
                           "per_day_allotment_mb must be 0 for INTERNATIONAL_LD")
        if addon["addon_type"] == "ROAMING" and addon["per_day_allotment_mb"] < 1:
            raise ApiError("ERR_INVALID_ADDON_WINDOW",
                           "per_day_allotment_mb must be at least 1 for ROAMING")
        if overlap:
            raise ApiError("ERR_ADDON_WINDOW_OVERLAP")
        addon["addon_status"] = "ACTIVE"
        addon["start_at"] = start_at
        addon["end_at"] = end_at
        addon["addon_price_cents"] = calcs.roaming_rate_card(addon)
        touch(addon)
        return respond.ok(store.serialize("AddOn", addon))

    @app.route("/carriers/add-ons/<ident>/cancel", methods=["POST"])
    def cancel_addon(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, CANCEL_ROLES)
        addon = _get(ident)
        auth.require_owner(uid, role, addon["subscriber_id"], "add-on")
        if addon["addon_status"] not in ("REQUESTED", "ACTIVE"):
            raise ApiError("ERR_INVALID_STATE", "add-on is %s" % addon["addon_status"])
        addon["addon_status"] = "CANCELLED"
        addon["addon_price_cents"] = 0
        addon["end_at"] = addon.get("start_at")
        touch(addon)
        return respond.ok(store.serialize("AddOn", addon))