"""Consultative quoting: quotes, dependency closure, reservation, amendment.

PRD §2.9, §3.2, §3.3.
"""

from db import DB, iso, parse_dt
from errors import ApiError, Err, invalid_value
from middleware import guard, require_engineer_owner
from response import (as_bool, as_enum, as_int, as_str, body, created_obj,
                      ensure_known, has, ok_list, ok_obj, page, pagination)
from services import calc, core

PACKAGE_TYPES = ("SYSTEM_PACKAGE", "INSTRUMENT_ONLY", "ACCESSORY_ONLY")
QUOTE_ROLES = ["PlatformAdmin", "SalesEngineerOps", "Engineer"]
BACKORDER_BLOCKING = ("BOARD_FILLED", "SHIPPED", "RECEIVING")


def _engineer_certified(engineer_id, product_family):
    now = iso(DB.now())
    for attempt in DB.all("certification_attempts"):
        if attempt["engineer_id"] != engineer_id:
            continue
        if attempt["product_family"] != product_family:
            continue
        if not attempt.get("certified"):
            continue
        expires_at = attempt.get("expires_at")
        if expires_at and expires_at <= now:
            continue
        return True
    return False


def _quote_lines(quote_id):
    return core.quote_lines(quote_id)


def register(app):
    # ---- quote lifecycle -------------------------------------------------
    @app.route("/quotes", methods=["POST"])
    def create_quote():
        guard(["Engineer", "SalesEngineerOps"])
        data = body()
        ensure_known(data, ["customer_id", "engineer_id", "package_type"])
        customer = core.fetch("customers", as_str(data, "customer_id", required=True),
                              Err.CUSTOMER_NOT_FOUND)
        engineer = core.fetch("engineers", as_str(data, "engineer_id", required=True),
                              Err.ENGINEER_NOT_FOUND)
        row = core.new_row(
            "quotes",
            customer_id=customer["id"],
            engineer_id=engineer["id"],
            package_type=as_enum(data, "package_type", PACKAGE_TYPES),
            status="DRAFT",
            bundle_ready=False,
            dependency_closure_size=0,
            gross_subtotal_cents=0,
            reserved_at=None,
            _commission_cents=0,
            _commission_variant=None,
        )
        core.recompute_quote_derived(row)
        return created_obj(core.public(row))

    @app.route("/quotes", methods=["GET"])
    def list_quotes():
        guard(QUOTE_ROLES)
        return page(core.all_rows("quotes"), filters=(
            ("customer_id", "customer_id", None),
            ("engineer_id", "engineer_id", None),
            ("status", "status", None),
        ))

    @app.route("/quotes/<ident>", methods=["GET"])
    def get_quote(ident):
        guard(QUOTE_ROLES)
        return ok_obj(core.public(core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)))

    @app.route("/quotes/<ident>/lines", methods=["GET"])
    def list_quote_lines(ident):
        guard(QUOTE_ROLES)
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        rows = _quote_lines(quote["id"])
        # A list endpoint: every one honours the pagination contract of §2.3.
        limit, offset = pagination()
        return ok_list(core.public_list(rows), limit, offset, len(rows))

    @app.route("/quotes/<ident>/summary", methods=["GET"])
    def quote_summary(ident):
        guard(QUOTE_ROLES)
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        lines = _quote_lines(quote["id"])
        commission, variant = core.quote_commission_state(quote)
        return ok_obj({
            "gross_subtotal_cents": int(quote.get("gross_subtotal_cents") or 0),
            "package_bundle_price_cents": calc.package_bundle_price_cents(
                lines, quote["package_type"]),
            "dependency_closure_size": int(quote.get("dependency_closure_size") or 0),
            "bundle_ready": bool(quote.get("bundle_ready")),
            "engineer_commission_cents": commission,
            "commission_variant": variant,
        })

    @app.route("/quote-lines", methods=["GET"])
    def list_lines():
        guard(QUOTE_ROLES)
        return page(core.all_rows("quote_lines"), filters=(
            ("quote_id", "quote_id", None),
            ("requires_line_id", "requires_line_id", None),
        ))

    @app.route("/quote-lines/<ident>", methods=["GET"])
    def get_line(ident):
        guard(QUOTE_ROLES)
        return ok_obj(core.public(core.fetch("quote_lines", ident,
                                             Err.REFERENCED_RESOURCE_NOT_FOUND)))

    # ---- lines -----------------------------------------------------------
    @app.route("/quotes/<ident>/lines", methods=["POST"])
    def add_line(ident):
        guard(["Engineer", "SalesEngineerOps"])
        data = body()
        ensure_known(data, ["product_code", "quantity", "is_anchor",
                            "requires_line_id"],
                     optional=("quantity", "is_anchor", "requires_line_id"))
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        core.require_state(quote, ("DRAFT",))

        code = as_str(data, "product_code", required=True)
        product = core.lookup("products", product_code=code)
        if product is None:
            raise ApiError(Err.REFERENCED_RESOURCE_NOT_FOUND,
                           "product_code resolves to no Product.")
        if not product.get("in_catalog"):
            raise invalid_value("The product is discontinued and cannot be newly quoted.")

        quantity = as_int(data, "quantity", default=1)
        if quantity < 1:
            raise invalid_value("quantity must be >= 1.")

        requires_line_id = None
        if has(data, "requires_line_id"):
            requires_line_id = as_str(data, "requires_line_id", required=True)
            prerequisite = DB.get("quote_lines", requires_line_id)
            if prerequisite is None or prerequisite["quote_id"] != quote["id"]:
                raise ApiError(Err.REFERENCED_RESOURCE_NOT_FOUND,
                               "requires_line_id names no line of this quote.")

        if product.get("requires_certification") \
                and not _engineer_certified(quote["engineer_id"], product["product_family"]):
            raise ApiError(Err.INVALID_STATE,
                           "The engineer holds no current certification in this family.")

        discount_bps = calc.SYSTEM_LINE_DISCOUNT_BPS \
            if quote["package_type"] == "SYSTEM_PACKAGE" else 0
        unit_price = int(product["unit_price_cents"])
        unit_after = calc.apply_bps(unit_price, 10000 - discount_bps) \
            if discount_bps else unit_price
        line_total = unit_after * quantity

        candidate = {"id": DB.new_id(), "quote_id": quote["id"],
                     "product_family": product["product_family"],
                     "requires_line_id": requires_line_id}
        existing = _quote_lines(quote["id"])
        if calc.has_cycle(existing + [candidate]):
            raise ApiError(Err.DEPENDENCY_CYCLE)

        row = core.new_row(
            "quote_lines",
            quote_id=quote["id"],
            product_id=product["id"],
            product_code=code,
            product_family=product["product_family"],
            is_anchor=as_bool(data, "is_anchor", default=False),
            unit_price_cents=unit_price,
            quantity=quantity,
            requires_line_id=requires_line_id,
            required_family=product.get("required_family"),
            bundle_discount_bps=discount_bps,
            line_total_cents=line_total,
        )
        # The candidate id only existed for the cycle probe; the stored row gets
        # its own freshly minted id.
        core.recompute_quote_derived(quote)
        # A line added to a quote that is already in the counted set changes the
        # owning customer's purchase history (§1.1 purchased_instrument_count).
        core.refresh_purchased_count(quote["customer_id"])
        return created_obj(core.public(row))

    # ---- transitions -----------------------------------------------------
    @app.route("/quotes/<ident>/submit", methods=["POST"])
    def submit_quote(ident):
        guard(["Engineer", "SalesEngineerOps"])
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        core.require_state(quote, ("DRAFT",))
        lines = _quote_lines(quote["id"])
        # priority 7 (cycle) -> priority 8 (assignment) -> priority 39 (missing)
        if calc.has_cycle(lines):
            raise ApiError(Err.DEPENDENCY_CYCLE)
        holder = core.active_assignment(quote["customer_id"])
        if holder is None or holder["engineer_id"] != quote["engineer_id"]:
            raise ApiError(Err.CUSTOMER_ASSIGNMENT_REQUIRED)
        core.recompute_quote_derived(quote)
        if not quote["bundle_ready"]:
            raise ApiError(Err.DEPENDENCY_MISSING)

        quote["status"] = "SUBMITTED"
        quote["_commission_cents"] = core.quote_provisional_commission(quote)
        quote["_commission_variant"] = "provisional"
        core.recompute_quote_derived(quote)
        core.bump(quote)
        return ok_obj(core.public(quote))

    @app.route("/quotes/<ident>/reserve", methods=["POST"])
    def reserve_quote(ident):
        guard(["Engineer", "SalesEngineerOps"])
        data = body()
        if not has(data, "expected_quote_version"):
            raise ApiError(Err.MISSING_REQUIRED_FIELD,
                           "Field expected_quote_version is required.")
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        core.require_state(quote, ("SUBMITTED",))
        holder = core.active_assignment(quote["customer_id"])
        if holder is None or holder["engineer_id"] != quote["engineer_id"]:
            raise ApiError(Err.CUSTOMER_ASSIGNMENT_REQUIRED)
        if int(quote.get("version") or 1) != as_int(data, "expected_quote_version"):
            raise ApiError(Err.STALE_VERSION)
        lines = _quote_lines(quote["id"])
        for line in lines:
            if any(bo["quote_line_id"] == line["id"]
                   and bo["status"] in ("BOARD_FILLED", "SHIPPED")
                   for bo in DB.all("backorders")):
                raise ApiError(Err.INVALID_STATE,
                               "A backorder on this quote is already filled or shipped.")
        if not quote.get("bundle_ready"):
            raise ApiError(Err.DEPENDENCY_MISSING)

        now = DB.now()
        quote["status"] = "RESERVED"
        quote["reserved_at"] = iso(now)
        core.bump(quote)
        for line in lines:
            _create_backorder(line, quote)
        core.recompute_quote_derived(quote)
        # Admitting the quote into the RESERVED set changes which lines count
        # toward the customer's purchase history (PRD §2.8).
        core.refresh_purchased_count(quote["customer_id"])
        return ok_obj(core.public(quote))

    @app.route("/quotes/<ident>/reject", methods=["POST"])
    def reject_quote(ident):
        guard(["SalesEngineerOps"])
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        core.require_state(quote, ("SUBMITTED",))
        quote["status"] = "REJECTED"
        quote["bundle_ready"] = False
        core.touch(quote)
        return ok_obj(core.public(quote))

    @app.route("/quotes/<ident>/amend", methods=["POST"])
    def amend_quote(ident):
        user_id, role = guard(["Engineer"])
        data = body()
        ensure_known(data, ["expected_quote_version"],
                     optional=("expected_quote_version",))
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        core.require_state(quote, ("RESERVED",))
        require_engineer_owner(user_id, role, quote)
        if has(data, "expected_quote_version") \
                and int(quote.get("version") or 1) != as_int(data, "expected_quote_version"):
            raise ApiError(Err.STALE_VERSION)
        lines = _quote_lines(quote["id"])
        for line in lines:
            if any(bo["quote_line_id"] == line["id"]
                   and bo["status"] in BACKORDER_BLOCKING
                   for bo in DB.all("backorders")):
                raise ApiError(Err.INVALID_STATE,
                               "A backorder on this quote is already on its way.")
        quote["status"] = "SUBMITTED"
        quote["reserved_at"] = None
        core.bump(quote)
        for line in lines:
            for bo in DB.all("backorders"):
                if bo["quote_line_id"] == line["id"] and bo["status"] == "ALLOCATION_SWEEP":
                    bo["status"] = "CANCELLED"
                    core.touch(bo)
        core.recompute_quote_derived(quote)
        return ok_obj(core.public(quote))

    @app.route("/quotes/<ident>/cancel", methods=["POST"])
    def cancel_quote(ident):
        guard(["Engineer", "SalesEngineerOps"])
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        core.require_state(quote, ("DRAFT", "REJECTED"))
        quote["status"] = "CANCELLED"
        core.bump(quote)
        return ok_obj(core.public(quote))

    @app.route("/quotes/<ident>/reopen", methods=["POST"])
    def reopen_quote(ident):
        user_id, role = guard(["Engineer"])
        quote = core.fetch("quotes", ident, Err.QUOTE_NOT_FOUND)
        core.require_state(quote, ("REJECTED",))
        require_engineer_owner(user_id, role, quote)
        quote["status"] = "DRAFT"
        core.recompute_quote_derived(quote)
        return ok_obj(core.public(quote))


def _create_backorder(line, quote):
    """One Backorder per QuoteLine, created by the reservation (PRD §3.3)."""
    highest = 0
    for bo in DB.all("backorders"):
        highest = max(highest, int(bo.get("alloc_sequence") or 0))
    opened = DB.now()
    row = core.new_row(
        "backorders",
        quote_line_id=line["id"],
        engineer_id=quote["engineer_id"],
        variant_bps=6000,
        preorder_open_at=iso(opened),
        units_requested=int(line.get("quantity") or 1),
        units_filled=0,
        overcommit_estimate_units=0,
        alloc_sequence=highest + 1,
        eta_deadline=None,
        status="PREORDER_PENDING",
    )
    core.recompute_backorder_deadline(row)
    return row