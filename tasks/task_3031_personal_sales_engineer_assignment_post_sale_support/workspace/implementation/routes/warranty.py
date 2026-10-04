"""Free extended warranty: plans, repair rounds, service-center routing.

PRD §3.6.
"""

from db import DB, add_months, iso, parse_dt
from errors import ApiError, Err, invalid_value
from middleware import guard
from response import (as_enum, as_int, as_str, body, created_obj, ensure_known,
                      has, ok_obj, page)
from services import calc, core

TERM_MONTHS = (12, 24, 36)
PLAN_STATUSES = ("PENDING", "ACTIVE", "CLAIM_OPEN", "REPAIR_IN_PROGRESS",
                 "EXPIRED", "VOIDED")
PLAN_ROLES = ["PlatformAdmin", "SalesEngineerOps", "SupportAgent"]
CLAIM_ROLES = ["PlatformAdmin", "SupportAgent", "ServiceDepartment"]


def register(app):
    # ---- plans -----------------------------------------------------------
    @app.route("/warranty-plans", methods=["POST"])
    def create_plan():
        guard(["SalesEngineerOps", "SupportAgent"])
        data = body()
        ensure_known(data, ["customer_id", "instrument_unit_id", "term_months"],
                     optional=("term_months",))
        customer = core.fetch("customers", as_str(data, "customer_id", required=True),
                              Err.CUSTOMER_NOT_FOUND)
        unit = core.fetch("instrument_units",
                          as_str(data, "instrument_unit_id", required=True),
                          Err.INSTRUMENT_UNIT_NOT_FOUND)
        term = as_int(data, "term_months", default=24)
        if term not in TERM_MONTHS:
            raise invalid_value("term_months must be one of 12, 24 or 36.")
        row = core.new_row(
            "warranty_plans",
            customer_id=customer["id"],
            instrument_unit_id=unit["id"],
            term_months=term,
            starts_on=None,
            expires_on=None,
            status="PENDING",
            repair_rounds_used=0,
            remaining_repair_rounds=calc.MAX_REPAIR_ROUNDS,
            _service_fee_cents=0,
            _service_fee_variant=None,
        )
        return created_obj(core.public(row))

    @app.route("/warranty-plans", methods=["GET"])
    def list_plans():
        guard(PLAN_ROLES)
        return page(core.all_rows("warranty_plans"), filters=(
            ("customer_id", "customer_id", None),
            ("instrument_unit_id", "instrument_unit_id", None),
            ("status", "status", None),
        ))

    @app.route("/warranty-plans/<ident>", methods=["GET"])
    def get_plan(ident):
        guard(PLAN_ROLES)
        return ok_obj(core.public(core.fetch("warranty_plans", ident,
                                             Err.WARRANTY_PLAN_NOT_FOUND)))

    @app.route("/warranty-plans/<ident>/activate", methods=["POST"])
    def activate_plan(ident):
        guard(["SalesEngineerOps"])
        data = body()
        ensure_known(data, ["starts_on"])
        plan = core.fetch("warranty_plans", ident, Err.WARRANTY_PLAN_NOT_FOUND)
        core.require_state(plan, ("PENDING",))
        unit = core.fetch("instrument_units", plan["instrument_unit_id"],
                          Err.INSTRUMENT_UNIT_NOT_FOUND)
        if unit.get("setup_status") != "SHIPPED":
            raise ApiError(Err.INVALID_STATE,
                           "The covered instrument has not reached SHIPPED.")
        starts_on = parse_dt(as_str(data, "starts_on", required=True))
        if starts_on is None:
            raise invalid_value("starts_on must be an ISO 8601 instant.")
        # A plan may not be anchored in the future.
        if starts_on > DB.now():
            raise ApiError(Err.INVALID_STATE,
                           "starts_on is later than the logical clock.")
        plan["starts_on"] = iso(starts_on)
        plan["expires_on"] = iso(add_months(starts_on, int(plan["term_months"])))
        plan["status"] = "ACTIVE"
        core.recompute_repair_rounds(plan)
        # A warranty now in force is one of the three facts the customer's
        # entitlement reads, and derived state propagates in the same mutation
        # (PRD §2.8 / §3.7).
        core.recompute_entitlement(plan["customer_id"])
        return ok_obj(core.public(plan))

    @app.route("/warranty-plans/<ident>/void", methods=["POST"])
    def void_plan(ident):
        guard(["PlatformAdmin"])
        plan = core.fetch("warranty_plans", ident, Err.WARRANTY_PLAN_NOT_FOUND)
        core.require_state(plan, ("PENDING", "ACTIVE", "EXPIRED"))
        plan["status"] = "VOIDED"
        core.touch(plan)
        for claim in core.claims_for_plan(plan["id"]):
            if claim["status"] in ("PENDING_ROUTING", "ROUTED"):
                claim["status"] = "CLOSED"
                claim["closed_at"] = iso(DB.now())
                core.touch(claim)
        # Voiding removes coverage, which can drop the customer's entitlement.
        core.recompute_entitlement(plan["customer_id"])
        return ok_obj(core.public(plan))

    # ---- claims ----------------------------------------------------------
    @app.route("/warranty-claims", methods=["POST"])
    def create_claim():
        guard(["SupportAgent"])
        data = body()
        ensure_known(data, ["warranty_plan_id", "reported_fault",
                            "service_center_id"])
        plan = core.fetch("warranty_plans",
                          as_str(data, "warranty_plan_id", required=True),
                          Err.WARRANTY_PLAN_NOT_FOUND)
        center = core.fetch("service_centers",
                            as_str(data, "service_center_id", required=True),
                            Err.REFERENCED_RESOURCE_NOT_FOUND)
        reported_fault = as_str(data, "reported_fault", required=True)

        # Priority 5 (409) before the business checks: the plan must be in a
        # state from which a claim is declared to open.
        if plan["status"] not in ("ACTIVE", "EXPIRED"):
            raise ApiError(Err.INVALID_STATE,
                           "A claim opens only against an ACTIVE or EXPIRED plan.")
        # Priority 15: the allowance is checked before the claim row exists.
        if int(plan.get("remaining_repair_rounds") or 0) <= 0:
            raise ApiError(Err.REPAIR_ROUNDS_EXHAUSTED)
        if plan["status"] == "ACTIVE":
            expires_on = parse_dt(plan.get("expires_on"))
            if expires_on is not None and DB.now() > expires_on:
                raise ApiError(Err.INVALID_STATE,
                               "The logical clock is past the plan's expiry.")
        elif int(plan.get("repair_rounds_used") or 0) >= calc.MAX_REPAIR_ROUNDS:
            # The narrow reopening an EXPIRED plan permits.
            raise ApiError(Err.REPAIR_ROUNDS_EXHAUSTED)

        row = core.new_row(
            "warranty_claims",
            warranty_plan_id=plan["id"],
            reported_fault=reported_fault,
            service_center_id=center["id"],
            status="PENDING_ROUTING",
            routed_at=None,
            closed_at=None,
            _service_fee_cents=0,
            _service_fee_variant=None,
        )
        plan["status"] = "CLAIM_OPEN"
        core.touch(plan)
        return created_obj(core.public(row))

    @app.route("/warranty-claims", methods=["GET"])
    def list_claims():
        guard(CLAIM_ROLES)
        return page(core.all_rows("warranty_claims"), filters=(
            ("warranty_plan_id", "warranty_plan_id", None),
            ("service_center_id", "service_center_id", None),
            ("status", "status", None),
        ))

    @app.route("/warranty-claims/<ident>", methods=["GET"])
    def get_claim(ident):
        guard(CLAIM_ROLES)
        return ok_obj(core.public(core.fetch("warranty_claims", ident,
                                             Err.REFERENCED_RESOURCE_NOT_FOUND)))

    @app.route("/warranty-claims/<ident>/route", methods=["POST"])
    def route_claim(ident):
        guard(["SupportAgent"])
        claim = core.fetch("warranty_claims", ident,
                           Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(claim, ("PENDING_ROUTING",))
        center = core.fetch("service_centers", claim["service_center_id"],
                            Err.REFERENCED_RESOURCE_NOT_FOUND)
        plan = core.fetch("warranty_plans", claim["warranty_plan_id"],
                          Err.WARRANTY_PLAN_NOT_FOUND)
        # priority 37 (suspension) before priority 36 (capacity).
        if center.get("status") != "OPEN":
            raise ApiError(Err.SERVICE_CENTER_SUSPENDED)
        if not core.has_free_slot(center):
            raise ApiError(Err.SERVICE_CENTER_CAPACITY_FULL)
        family = core.plan_product_family(plan)
        if family is not None and family not in (center.get("accepted_families") or []):
            raise ApiError(Err.SERVICE_CENTER_FAMILY_NOT_ACCEPTED)

        claim["status"] = "ROUTED"
        claim["routed_at"] = iso(DB.now())
        core.touch(claim)
        core.adjust_open_tickets(center["id"], 1)
        plan["status"] = "REPAIR_IN_PROGRESS"
        plan["_service_fee_cents"] = calc.warranty_service_fee_cents(
            plan, "provisional")
        plan["_service_fee_variant"] = "provisional"
        core.touch(plan)
        return ok_obj(core.public(claim))

    @app.route("/warranty-claims/<ident>/reopen", methods=["POST"])
    def reopen_claim(ident):
        guard(["SupportAgent"])
        claim = core.fetch("warranty_claims", ident,
                           Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(claim, ("ROUTED",))
        plan = core.fetch("warranty_plans", claim["warranty_plan_id"],
                          Err.WARRANTY_PLAN_NOT_FOUND)
        expires_on = parse_dt(plan.get("expires_on"))
        if expires_on is not None and DB.now() > expires_on:
            raise ApiError(Err.INVALID_STATE,
                           "The logical clock is past the plan's expiry.")
        claim["status"] = "PENDING_ROUTING"
        claim["routed_at"] = None
        core.touch(claim)
        core.adjust_open_tickets(claim["service_center_id"], -1)
        plan["status"] = "CLAIM_OPEN"
        core.touch(plan)
        return ok_obj(core.public(claim))

    @app.route("/warranty-claims/<ident>/close", methods=["POST"])
    def close_claim(ident):
        guard(["SupportAgent"])
        claim = core.fetch("warranty_claims", ident,
                           Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(claim, ("ROUTED",))
        plan = core.fetch("warranty_plans", claim["warranty_plan_id"],
                          Err.WARRANTY_PLAN_NOT_FOUND)
        # The final variant reads repair_rounds_used before it is incremented.
        rounds_used = int(plan.get("repair_rounds_used") or 0)
        plan["_service_fee_cents"] = calc.warranty_service_fee_cents(
            plan, "final")
        plan["_service_fee_variant"] = "final"

        claim["status"] = "CLOSED"
        claim["closed_at"] = iso(DB.now())
        core.touch(claim)
        plan["repair_rounds_used"] = rounds_used + 1
        core.recompute_repair_rounds(plan)
        plan["status"] = "ACTIVE" if int(plan["remaining_repair_rounds"]) > 0 \
            else "EXPIRED"
        core.touch(plan)
        core.adjust_open_tickets(claim["service_center_id"], -1)
        core.recompute_entitlement(plan["customer_id"])
        return ok_obj(core.public(claim))