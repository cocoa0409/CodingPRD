"""Nested sub-resource reads.

Every path here resolves its identifiers in strict left-to-right order and
rejects at the first one that does not resolve.  The doubler GETs (the ones
that name a UUID) return the full curated list; the single-resource GETs return
the standard paginated envelope, as §2.3 requires of every list endpoint.
"""

from db import DB
from middleware import guard
from response import ok_obj, sorted_by_created
from services import core

ALL_ROLES = ["ChainAdmin", "StoreManager", "CreditAnalyst", "SalesAssociate", "CustomerService"]


def register(app):
    # --- stores ----------------------------------------------------------
    @app.route("/stores/<ident>/repairs", methods=["GET"])
    def store_repairs(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        core.fetch("stores", ident, "store")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("repairs") if r["store_id"] == ident]))

    @app.route("/stores/<ident>/credit-applications", methods=["GET"])
    def store_applications(ident):
        guard(ALL_ROLES)
        core.fetch("stores", ident, "store")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("credit_applications") if r["store_id"] == ident]))

    @app.route("/stores/<ident>/service-plan-registrations", methods=["GET"])
    def store_registrations(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        core.fetch("stores", ident, "store")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("registrations") if r["store_id"] == ident]))

    @app.route("/stores/<ident>/inspection-visits", methods=["GET"])
    def store_visits(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        core.fetch("stores", ident, "store")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("visits") if r["store_id"] == ident]))

    @app.route("/stores/<ident>/purchases", methods=["GET"])
    def store_purchases(ident):
        guard(ALL_ROLES)
        core.fetch("stores", ident, "store")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("purchases") if r["store_id"] == ident]))

    # --- vendor shops ----------------------------------------------------
    @app.route("/vendor-shops/<ident>/repairs", methods=["GET"])
    def vendor_repairs(ident):
        guard(["ChainAdmin", "StoreManager", "CustomerService"])
        shop = core.fetch("vendor_shops", ident, "vendor shop")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("repairs") if r.get("vendor_shop_code") == shop["shop_code"]]))

    # --- customers -------------------------------------------------------
    @app.route("/customers/<ident>/credit-applications", methods=["GET"])
    def customer_applications(ident):
        guard(ALL_ROLES)
        core.fetch("customers", ident, "customer")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("credit_applications") if r["customer_id"] == ident]))

    @app.route("/customers/<ident>/promotional-plans", methods=["GET"])
    def customer_plans(ident):
        guard(ALL_ROLES)
        core.fetch("customers", ident, "customer")
        rows = sorted_by_created(
            [r for r in DB.all("promotional_plans") if r["customer_id"] == ident])
        for plan in rows:
            core.recompute_plan_derived(plan)
        return ok_obj(rows)

    @app.route("/customers/<ident>/service-plan-registrations", methods=["GET"])
    def customer_registrations(ident):
        guard(ALL_ROLES)
        core.fetch("customers", ident, "customer")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("registrations") if r["customer_id"] == ident]))

    @app.route("/customers/<ident>/diamonds", methods=["GET"])
    def customer_diamonds(ident):
        guard(["ChainAdmin", "StoreManager", "SalesAssociate", "CustomerService"])
        core.fetch("customers", ident, "customer")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("diamonds") if r["owner_customer_id"] == ident]))

    @app.route("/customers/<ident>/purchases", methods=["GET"])
    def customer_purchases(ident):
        guard(ALL_ROLES)
        core.fetch("customers", ident, "customer")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("purchases") if r["customer_id"] == ident]))

    @app.route("/customers/<ident>/custom-design-orders", methods=["GET"])
    def customer_designs(ident):
        guard(["ChainAdmin", "StoreManager", "SalesAssociate", "CustomerService"])
        core.fetch("customers", ident, "customer")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("designs") if r["customer_id"] == ident]))

    @app.route("/customers/<ident>/billing-statements", methods=["GET"])
    def customer_statements(ident):
        guard(["ChainAdmin", "CreditAnalyst", "CustomerService", "Customer"])
        core.fetch("customers", ident, "customer")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("statements") if r["customer_id"] == ident]))

    # --- diamonds --------------------------------------------------------
    @app.route("/diamonds/<ident>/service-plan-registrations", methods=["GET"])
    def diamond_registrations(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        core.fetch("diamonds", ident, "diamond")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("registrations") if r["diamond_id"] == ident]))

    # --- purchases -------------------------------------------------------
    @app.route("/purchases/<ident>/promotional-plans", methods=["GET"])
    def purchase_plans(ident):
        guard(ALL_ROLES)
        core.fetch("purchases", ident, "purchase")
        rows = sorted_by_created(
            [r for r in DB.all("promotional_plans") if r["purchase_id"] == ident])
        for plan in rows:
            core.recompute_plan_derived(plan)
        return ok_obj(rows)

    @app.route("/purchases/<ident>/service-plan-registrations", methods=["GET"])
    def purchase_registrations(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        core.fetch("purchases", ident, "purchase")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("registrations") if r["purchase_id"] == ident]))

    @app.route("/purchases/<ident>/purchases", methods=["GET"])
    def purchase_derivatives(ident):
        guard(["ChainAdmin", "StoreManager", "SalesAssociate", "CustomerService"])
        core.fetch("purchases", ident, "purchase")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("purchases") if r.get("origin_purchase_id") == ident]))

    # --- protection bundles ----------------------------------------------
    @app.route("/protection-bundles/<ident>/service-plan-registrations", methods=["GET"])
    def bundle_registrations(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        core.fetch("bundles", ident, "protection bundle")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("registrations") if r["bundle_id"] == ident]))

    # --- promotional plans -----------------------------------------------
    @app.route("/promotional-plans/<ident>/payoff-ledger-entries", methods=["GET"])
    def plan_ledger(ident):
        guard(["ChainAdmin", "CreditAnalyst", "StoreManager", "CustomerService"])
        core.fetch("promotional_plans", ident, "promotional plan")
        return ok_obj(core.ledger_entries_of(ident))

    # --- service plan registrations --------------------------------------
    @app.route("/service-plan-registrations/<ident>/inspection-visits", methods=["GET"])
    def registration_visits(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        core.fetch("registrations", ident, "service plan registration")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("visits") if r["registration_id"] == ident]))

    @app.route("/service-plan-registrations/<ident>/repairs", methods=["GET"])
    def registration_repairs(ident):
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        core.fetch("registrations", ident, "service plan registration")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("repairs") if r["registration_id"] == ident]))

    # --- repairs ---------------------------------------------------------
    @app.route("/repairs/<ident>/appraisals", methods=["GET"])
    def repair_appraisals(ident):
        guard(["ChainAdmin", "StoreManager", "CustomerService"])
        core.fetch("repairs", ident, "repair")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("appraisals") if r["repair_id"] == ident]))

    @app.route("/repairs/<ident>/holds", methods=["GET"])
    def repair_holds(ident):
        guard(["ChainAdmin", "StoreManager", "CustomerService"])
        core.fetch("repairs", ident, "repair")
        return ok_obj(sorted_by_created(
            [r for r in DB.all("holds") if r["repair_id"] == ident]))

    @app.route("/repairs/<ident>/payoff-ledger-entries", methods=["GET"])
    def repair_ledger(ident):
        guard(["ChainAdmin", "CreditAnalyst", "StoreManager", "CustomerService"])
        core.fetch("repairs", ident, "repair")
        return ok_obj([])