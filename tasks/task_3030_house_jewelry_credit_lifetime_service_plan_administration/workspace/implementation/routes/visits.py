"""Inspection visit records: logging, claiming and no-shows."""

from datetime import timedelta

from flask import request

from db import DB, iso, parse_dt
from middleware import guard
from response import (ApiError, Err, as_enum, as_int, as_str, body, created_obj,
                      ensure_known, invalid_state, ok_list, ok_obj, pagination,
                      sorted_by_created)
from services import core


def register(app):
    @app.route("/inspection-visits", methods=["POST"])
    def create_visit():
        guard(["StoreManager"])
        data = body()
        ensure_known(data, ["registration_id", "store_id", "visit_at", "result",
                            "scheduled_for_at", "expected_registration_version"],
                     optional=("scheduled_for_at",))
        registration_id = as_str(data, "registration_id")
        store_id = as_str(data, "store_id")
        visit_at = parse_dt(as_str(data, "visit_at"))
        if visit_at is None:
            raise ApiError(Err.INVALID_REQUEST, "visit_at must be an ISO 8601 instant.")
        result = as_enum(data, "result", ("SCHEDULED", "CLAIMED", "NO_SHOW"))
        expected = as_int(data, "expected_registration_version", required=True)

        registration = core.fetch("registrations", registration_id, "service plan registration")
        store = core.fetch("stores", store_id, "store")

        # Priority 5: the registration's version assertion.
        if registration["version"] != expected:
            raise ApiError(Err.STALE_VERSION)
        # Priority 15: a visit may not be logged earlier than the current due instant.
        due = parse_dt(registration.get("inspection_due_at"))
        if due is not None and visit_at < due:
            raise ApiError(Err.EXTENSION_WINDOW_EXPIRED)

        visit = core.new_row(
            "visits",
            registration_id=registration_id,
            store_id=store_id,
            visit_at=iso(visit_at),
            result=result,
            scheduled_for_at=iso(parse_dt(data.get("scheduled_for_at"))) if data.get("scheduled_for_at") else None,
            inspection_status=result,
            # PRD §3.3: the standing visit record becomes CLAIMED with
            # `claimed_at` supplied or stamped.
            claimed_at=iso(DB.now()) if result == "CLAIMED" else None,
        )
        if result == "CLAIMED":
            _advance_registration(registration, store, visit, visit_at)
        core.touch(registration)
        return created_obj(visit)

    @app.route("/inspection-visits", methods=["GET"])
    def list_visits():
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        limit, offset = pagination()
        rows = DB.all("visits")
        for field in ("registration_id", "store_id", "inspection_status", "result"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/inspection-visits/<ident>", methods=["GET"])
    def get_visit(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        return ok_obj(core.fetch("visits", ident, "inspection visit"))

    @app.route("/inspection-visits/<ident>/claim", methods=["POST"])
    def claim_visit(ident):
        guard(["StoreManager"])
        data = body()
        ensure_known(data, ["claimed_at"], optional=("claimed_at",))
        visit = core.fetch("visits", ident, "inspection visit")
        if visit["inspection_status"] != "SCHEDULED":
            raise invalid_state("Only a SCHEDULED visit may be claimed.")
        registration = core.fetch("registrations", visit["registration_id"],
                                  "service plan registration")
        if registration["coverage_status"] not in ("PENDING_INSPECTION", "REMINDER_ISSUED",
                                                   "GRACE_PERIOD"):
            raise invalid_state("The registration is not in a claimable status.")
        instant = parse_dt(data.get("claimed_at")) or DB.now()
        visit["inspection_status"] = "CLAIMED"
        visit["result"] = "CLAIMED"
        visit["claimed_at"] = iso(instant)
        store = core.fetch("stores", registration["store_id"], "store")
        # Coverage forks on the visit instant, not on the claim stamp.
        _advance_registration(registration, store, visit,
                              parse_dt(visit.get("visit_at")) or instant)
        core.touch(registration)
        core.touch(visit)
        return ok_obj(visit)

    @app.route("/inspection-visits/<ident>/no-show", methods=["POST"])
    def no_show_visit(ident):
        guard(["StoreManager"])
        visit = core.fetch("visits", ident, "inspection visit")
        if visit["inspection_status"] != "SCHEDULED":
            raise invalid_state("Only a SCHEDULED visit may be marked as a no-show.")
        scheduled = parse_dt(visit.get("scheduled_for_at"))
        if scheduled is None or DB.now() <= scheduled:
            raise invalid_state("The visit's scheduled instant has not passed.")
        visit["inspection_status"] = "NO_SHOW"
        visit["result"] = "NO_SHOW"
        core.touch(visit)
        return ok_obj(visit)


def _advance_registration(registration, store, visit, visit_at):
    """Both exams branches share this housekeeping; the outcome forks on timing."""
    due = parse_dt(registration.get("inspection_due_at"))
    timely = due is None or visit_at <= due
    interval = core.inspection_interval(registration)
    next_at = visit_at + timedelta(days=interval)
    registration["last_inspection_at"] = iso(visit_at)
    registration["next_inspection_at"] = iso(next_at)
    registration["inspection_due_at"] = iso(next_at)
    registration["cure_expires_at"] = iso(
        next_at + timedelta(days=core.cure_days(registration)))
    if timely:
        registration["coverage_status"] = "ACTIVE"
        registration["is_valid"] = True
        for other in DB.all("visits"):
            if other["id"] != visit["id"] and other["registration_id"] == registration["id"] \
                    and other["inspection_status"] == "SCHEDULED":
                other["inspection_status"] = "NO_SHOW"
                other["result"] = "NO_SHOW"
                core.touch(other)
        customer = DB.get("customers", registration["customer_id"])
        if customer is not None:
            customer["lost_inspection_streak"] = 0
            core.recompute_customer(customer)
    else:
        registration["coverage_status"] = "GRACE_PERIOD"
        registration["is_valid"] = True
    core.recompute_store(store)