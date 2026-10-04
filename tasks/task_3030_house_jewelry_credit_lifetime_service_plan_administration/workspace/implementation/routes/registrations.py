"""Lifetime service-plan registrations: origination, inspections, lapse, renewal."""

from datetime import timedelta

from flask import request

from constants import NATURAL_ORIGIN_CARAT_THRESHOLD
from db import DB, iso, parse_dt
from middleware import guard
from response import (ApiError, Err, as_enum, as_int, as_str, body, created_obj,
                      ensure_known, invalid_state, ok_list, ok_obj, pagination,
                      sorted_by_created)
from services import core

READ_ROLES = ["ChainAdmin", "StoreManager", "CreditAnalyst", "SalesAssociate", "CustomerService"]


def register(app):
    @app.route("/service-plan-registrations", methods=["POST"])
    def create_registration():
        guard(["SalesAssociate", "StoreManager"])
        data = body()
        ensure_known(data, ["customer_id", "purchase_id", "diamond_id", "store_id",
                            "bundle_id", "plan_term_months"])
        customer_id = as_str(data, "customer_id")
        purchase_id = as_str(data, "purchase_id")
        diamond_id = as_str(data, "diamond_id")
        store_id = as_str(data, "store_id")
        bundle_id = as_str(data, "bundle_id")
        term = as_int(data, "plan_term_months", required=True)

        customer = core.fetch("customers", customer_id, "customer")
        core.fetch("purchases", purchase_id, "purchase")
        diamond = core.fetch("diamonds", diamond_id, "diamond")
        store = core.fetch("stores", store_id, "store")
        core.fetch("bundles", bundle_id, "protection bundle")

        # Priority 6: the governing regulation must exist before any state or
        # business rule runs.
        regulation = core.regulation_for_state(store["state_code"])
        if regulation is None:
            raise ApiError(Err.REGULATION_TERMS_VIOLATION,
                           "No lifetime-plan regulation row exists for this store's state.")
        # Priority 7: the term must fit the state maximum and the inspection
        # mandate must be satisfiable.
        if term > regulation["max_plan_term_months"]:
            raise ApiError(Err.PLAN_TERM_EXCEEDS_REGULATION)
        # Priority 9: the account carrying the obligation must be OPEN.
        if customer["account_status"] != "OPEN":
            raise ApiError(Err.ACCOUNT_NOT_OPEN)
        # Priority 11: a natural centre stone over 1.00 carat needs its
        # origin_registry document on file.
        if diamond["stone_kind"] == "NATURAL" and \
                diamond["carat"] > NATURAL_ORIGIN_CARAT_THRESHOLD and \
                not diamond.get("origin_registry"):
            raise ApiError(Err.ORIGIN_DOCUMENT_MISSING)

        registration = core.new_row(
            "registrations",
            customer_id=customer_id,
            purchase_id=purchase_id,
            diamond_id=diamond_id,
            store_id=store_id,
            bundle_id=bundle_id,
            registered_at=None,
            coverage_status="PENDING_INSPECTION",
            inspection_due_at=None,
            cure_expires_at=None,
            last_inspection_at=None,
            next_inspection_at=None,
            missed_inspection_count=0,
            plan_term_months=term,
            renewal_count=0,
            replacement_claims_used=0,
            is_valid=False,
        )
        core.schedule_registration(registration, DB.now())
        core.recompute_store(store)
        return created_obj(registration)

    @app.route("/service-plan-registrations", methods=["GET"])
    def list_registrations():
        guard(READ_ROLES)
        limit, offset = pagination()
        rows = DB.all("registrations")
        for field in ("customer_id", "purchase_id", "diamond_id", "store_id",
                      "bundle_id", "coverage_status"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/service-plan-registrations/<ident>", methods=["GET"])
    def get_registration(ident):
        guard(READ_ROLES)
        return ok_obj(core.fetch("registrations", ident, "service plan registration"))

    @app.route("/service-plan-registrations/<ident>/exams", methods=["POST"])
    def log_exam(ident):
        guard(["StoreManager"])
        data = body()
        ensure_known(data, ["visit_at", "result"])
        visit_at = parse_dt(as_str(data, "visit_at"))
        if visit_at is None:
            raise ApiError(Err.INVALID_REQUEST, "visit_at must be an ISO 8601 instant.")
        result = as_enum(data, "result", ("SCHEDULED", "CLAIMED", "NO_SHOW"))

        registration = core.fetch("registrations", ident, "service plan registration")
        store = core.fetch("stores", registration["store_id"], "store")
        _guard_not_terminal(registration)
        due = parse_dt(registration.get("inspection_due_at"))
        cure = parse_dt(registration.get("cure_expires_at"))
        # Priority 15: retroactive back-dating beyond one full cycle.
        if _too_early(registration, visit_at, due):
            raise ApiError(Err.EXTENSION_WINDOW_EXPIRED)
        # Priority 13: a visit after the due instant must land inside the cure window.
        if due is not None and visit_at > due:
            if cure is None or visit_at > cure:
                raise ApiError(Err.WINDOW_EXPIRED)

        claimed = _claim_visit(registration, store, visit_at, result)
        return ok_obj(registration if result == "CLAIMED" else claimed)

    @app.route("/service-plan-registrations/<ident>/renew", methods=["POST"])
    def renew_registration(ident):
        guard(["StoreManager"])
        registration = core.fetch("registrations", ident, "service plan registration")
        _guard_not_terminal(registration)
        if registration["coverage_status"] != "LAPSED":
            raise invalid_state("Only a LAPSED registration may be renewed.")
        customer = core.fetch("customers", registration["customer_id"], "customer")
        # Priority 9: the account carrying the obligation must be OPEN.
        if customer["account_status"] not in ("OPEN", "NO_FILE"):
            raise ApiError(Err.ACCOUNT_NOT_OPEN)
        if customer["credit_tier"] == "TIER_1" and registration["renewal_count"] >= 2:
            raise invalid_state("A TIER_1 cardholder may renew at most twice.")

        registration["renewal_count"] += 1
        registration["coverage_status"] = "RENEWED"
        registration["is_valid"] = False
        core.schedule_registration(registration, DB.now())
        customer["lost_inspection_streak"] = 0
        core.recompute_customer(customer)
        core.touch(registration)
        return ok_obj(registration)

    @app.route("/service-plan-registrations/<ident>/terminate", methods=["POST"])
    def terminate_registration(ident):
        guard(["StoreManager", "CustomerService"])
        registration = core.fetch("registrations", ident, "service plan registration")
        _guard_not_terminal(registration)
        if registration["coverage_status"] not in ("PENDING_INSPECTION", "REMINDER_ISSUED",
                                                   "ACTIVE", "GRACE_PERIOD"):
            raise invalid_state("This registration cannot be terminated from its status.")
        for repair in DB.all("repairs"):
            if repair["registration_id"] == registration["id"] and \
                    repair["repair_status"] in ("INTAKE", "ROUTED", "IN_REPAIR", "QC_REVIEW"):
                raise invalid_state("An open repair is pinned to this registration.")

        registration["coverage_status"] = "TERMINATED"
        registration["is_valid"] = False
        _no_show_scheduled(registration)
        store = DB.get("stores", registration["store_id"])
        if store is not None:
            core.recompute_store(store)
        core.touch(registration)
        return ok_obj(registration)

    @app.route("/service-plan-registrations/<ident>/void", methods=["POST"])
    def void_registration(ident):
        guard(["ChainAdmin"])
        registration = core.fetch("registrations", ident, "service plan registration")
        _guard_not_terminal(registration)
        if registration["coverage_status"] != "PENDING_INSPECTION":
            raise invalid_state("Only a PENDING_INSPECTION registration may be voided.")
        store = core.fetch("stores", registration["store_id"], "store")
        if core.regulation_for_state(store["state_code"]) is not None:
            raise invalid_state("A regulation row is registered for this store's state.")
        registration["coverage_status"] = "VOID"
        registration["is_valid"] = False
        core.recompute_store(store)
        core.touch(registration)
        return ok_obj(registration)

    @app.route("/inspection-reminders/run", methods=["POST"])
    def run_reminders():
        guard(["StoreManager", "ChainAdmin"])
        reminded = []
        for registration in sorted_by_created(DB.all("registrations")):
            status = registration["coverage_status"]
            if status == "RENEWED":
                registration["coverage_status"] = "PENDING_INSPECTION"
                registration["is_valid"] = False
                _spawn_visit(registration,
                             parse_dt(registration.get("inspection_due_at")) or DB.now())
                core.touch(registration)
                reminded.append(registration["id"])
                continue
            if status == "PENDING_INSPECTION":
                bundle = core.bundle_of(registration)
                if bundle is not None and bundle["bundle_status"] != "CURRENT":
                    continue
                due = parse_dt(registration.get("inspection_due_at"))
                if due is None or DB.now() < due - timedelta(days=14):
                    continue
                registration["coverage_status"] = "REMINDER_ISSUED"
                _spawn_visit(registration, due)
                core.touch(registration)
                store = DB.get("stores", registration["store_id"])
                if store is not None:
                    core.recompute_store(store)
                reminded.append(registration["id"])
                continue
            if status in ("ACTIVE", "GRACE_PERIOD"):
                next_at = parse_dt(registration.get("next_inspection_at"))
                if next_at is None or DB.now() < next_at - timedelta(days=14):
                    continue
                registration["coverage_status"] = "REMINDER_ISSUED"
                _spawn_visit(registration, next_at)
                core.touch(registration)
                store = DB.get("stores", registration["store_id"])
                if store is not None:
                    core.recompute_store(store)
                reminded.append(registration["id"])
        return ok_obj({"reminded_count": len(reminded),
                       "reminded_registration_ids": reminded})

    @app.route("/service-plan-registrations/lapse-due", methods=["POST"])
    def lapse_due():
        guard(["CreditAnalyst"])
        lapsed = []
        touched_customers = set()
        for registration in sorted_by_created(DB.all("registrations")):
            if registration["coverage_status"] not in ("PENDING_INSPECTION", "REMINDER_ISSUED"):
                continue
            cure = parse_dt(registration.get("cure_expires_at"))
            if cure is None or DB.now() <= cure:
                continue
            registration["coverage_status"] = "LAPSED"
            registration["is_valid"] = False
            registration["missed_inspection_count"] += 1
            _no_show_scheduled(registration)
            store = DB.get("stores", registration["store_id"])
            if store is not None:
                core.recompute_store(store)
            core.touch(registration)
            customer = DB.get("customers", registration["customer_id"])
            if customer is not None:
                customer["lost_inspection_streak"] = (customer.get("lost_inspection_streak") or 0) + 1
                touched_customers.add(customer["id"])
            lapsed.append(registration["id"])
        for customer_id in touched_customers:
            customer = DB.get("customers", customer_id)
            if customer is not None:
                core.recompute_customer(customer)
        return ok_obj({"lapsed_count": len(lapsed), "lapsed_registration_ids": lapsed})


# ---------------------------------------------------------------------------
# shared transitions
# ---------------------------------------------------------------------------

def _too_early(registration, visit_at, due):
    """A visit may not be back-dated more than one cycle before the due instant."""
    if due is None:
        return False
    earliest = due - timedelta(days=core.inspection_interval(registration))
    start = parse_dt(registration.get("registered_at"))
    if start is not None and start > earliest:
        earliest = start
    return visit_at < earliest


def _guard_not_terminal(registration):
    """Priority 28: a terminal coverage status refuses every action."""
    if registration["coverage_status"] in ("TERMINATED", "VOID"):
        raise ApiError(Err.REGISTRATION_TERMINATED)


def _no_show_scheduled(registration):
    for visit in DB.all("visits"):
        if visit["registration_id"] == registration["id"] and \
                visit["inspection_status"] == "SCHEDULED":
            visit["inspection_status"] = "NO_SHOW"
            visit["result"] = "NO_SHOW"
            core.touch(visit)


def _spawn_visit(registration, scheduled_for_at):
    return core.new_row(
        "visits",
        registration_id=registration["id"],
        store_id=registration["store_id"],
        visit_at=iso(DB.now()),
        result="SCHEDULED",
        scheduled_for_at=iso(scheduled_for_at),
        inspection_status="SCHEDULED",
        claimed_at=None,
    )


def _claim_visit(registration, store, visit_at, result):
    """Write the claimed visit and advance coverage per the two exams branches."""
    due = parse_dt(registration.get("inspection_due_at"))
    timely = due is None or visit_at <= due

    visit = core.new_row(
        "visits",
        registration_id=registration["id"],
        store_id=registration["store_id"],
        visit_at=iso(visit_at),
        result=result,
        scheduled_for_at=None,
        inspection_status=result if result in ("SCHEDULED", "NO_SHOW") else "CLAIMED",
        claimed_at=iso(DB.now()) if result == "CLAIMED" else None,
    )
    if result != "CLAIMED":
        return visit

    interval = core.inspection_interval(registration)
    registration["last_inspection_at"] = iso(visit_at)
    next_at = visit_at + timedelta(days=interval)
    registration["next_inspection_at"] = iso(next_at)
    registration["inspection_due_at"] = iso(next_at)
    registration["cure_expires_at"] = iso(
        next_at + timedelta(days=core.cure_days(registration)))
    if timely:
        registration["coverage_status"] = "ACTIVE"
        registration["is_valid"] = True
        _no_show_scheduled(registration)
        store["open_inspection_count"] = max(0, store["open_inspection_count"] - 1)
        customer = DB.get("customers", registration["customer_id"])
        if customer is not None:
            customer["lost_inspection_streak"] = 0
            core.recompute_customer(customer)
    else:
        registration["coverage_status"] = "GRACE_PERIOD"
        registration["is_valid"] = True
    core.touch(registration)
    return visit