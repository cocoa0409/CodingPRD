"""Brands, jurisdictions, establishments, coverage determination, logical clock."""

import re

import calc
import domain as D
from core import (CLOCK, ROLE_BRAND_OFFICER, ROLE_PLATFORM_ADMIN, S, authenticate,
                  body_or_empty, envelope, fail, fmt_date, get_body, insert, mark,
                  not_found, require_scope)
from validate import (opt_bool, opt_enum, opt_string, peek_id, req_enum, req_id,
                      req_int, req_instant, req_string)

CODE_RE = re.compile(r"^[A-Z0-9-]{2,12}$")


def register(app):

    # ---------------------------------------------------------------- brands
    @app.post("/brands")
    def create_brand():
        authenticate([ROLE_PLATFORM_ADMIN])
        body = get_body()
        legal_name = req_string(body, "legal_name", 1, 120)
        dba = opt_string(body, "doing_business_as", 1, 120)
        brand = insert(S.brands, {
            "legal_name": legal_name,
            "doing_business_as": dba if dba is not None else legal_name,
            "coverage_status": "NOT_COVERED",
            "coverage_reason": "NO_STANDARD_MENU_ITEMS",
            "counted_unit_count": 0,
            "standard_item_count": 0,
            "compliance_posture": "EXEMPT",
            "open_reprint_obligation_count": 0,
            "overdue_board_count": 0,
            "open_enforcement_escalated_count": 0,
            "has_published_disclosure_packet": False,
        })
        return envelope(D.brand_out(brand), 201)

    # --------------------------------------------------------- jurisdictions
    @app.post("/jurisdictions")
    def create_jurisdiction():
        authenticate([ROLE_PLATFORM_ADMIN])
        body = get_body()
        code = req_string(body, "code", 2, 12)
        if not CODE_RE.match(code):
            fail("ERR_VALIDATION", "code must be 2-12 characters of A-Z, 0-9 or hyphen")
        name = req_string(body, "name", 1, 120)
        preemption_mode = req_enum(body, "preemption_mode", ("PREEMPTED", "VARIANCE_ALLOWED"))
        extra_requirement = opt_enum(
            body, "extra_requirement",
            ("NONE", "SODIUM_WARNING", "ADDED_SUGAR_ICON"), "NONE")
        enforcement_tier = opt_enum(
            body, "enforcement_tier", ("FEDERAL_ALIGNED", "ENHANCED"), "FEDERAL_ALIGNED")
        threshold = body.get("sodium_warning_threshold_mg")
        if threshold is None:
            threshold = 2300
        else:
            threshold = req_int(body, "sodium_warning_threshold_mg", 0, 10000)
        variant = opt_enum(
            body, "required_succinct_statement_variant",
            ("FEDERAL_DEFAULT", "STATE_EXTENDED"), "FEDERAL_DEFAULT")
        for existing in S.jurisdictions.values():
            if existing["code"] == code:
                fail("ERR_VALIDATION", "code is already registered")
        jurisdiction = insert(S.jurisdictions, {
            "code": code,
            "name": name,
            "preemption_mode": preemption_mode,
            "extra_requirement": extra_requirement,
            "enforcement_tier": enforcement_tier,
            "sodium_warning_threshold_mg": threshold,
            "required_succinct_statement_variant": variant,
            "reprint_grace_days": calc.grace_days(extra_requirement),
            "assessed_penalty_cents_total": 0,
        })
        return envelope(D.jurisdiction_out(jurisdiction), 201)

    # -------------------------------------------------------- establishments
    @app.post("/establishments")
    def create_establishment():
        authenticate([ROLE_PLATFORM_ADMIN, ROLE_BRAND_OFFICER])
        require_scope(peek_id(body_or_empty(), "brand_id"))
        body = get_body()
        brand_id = req_id(body, "brand_id")
        jurisdiction_id = req_id(body, "jurisdiction_id")
        unit_label = req_string(body, "unit_label", 1, 40)
        unit_status = opt_enum(body, "unit_status", D.UNIT_STATUSES, "PLANNED")
        operates = opt_bool(body, "operates_under_brand_name", True)
        for unit in D.brand_units(brand_id):
            if unit["unit_label"] == unit_label:
                fail("ERR_VALIDATION", "unit_label is already used within this brand")
        brand = S.brands.get(brand_id)
        if brand is None:
            not_found("brand")
        jurisdiction = S.jurisdictions.get(jurisdiction_id)
        if jurisdiction is None:
            not_found("jurisdiction")
        establishment = insert(S.establishments, {
            "brand_id": brand_id,
            "jurisdiction_id": jurisdiction_id,
            "unit_label": unit_label,
            "unit_status": unit_status,
            "operates_under_brand_name": operates,
            "outstanding_penalty_cents": 0,
            "board_count": 0,
        })
        D.run_coverage(brand, "OPERATING_ONLY")
        return envelope(D.establishment_out(establishment), 201)

    @app.post("/brands/<brand_id>/establishment-batches")
    def create_establishment_batch(brand_id):
        authenticate([ROLE_PLATFORM_ADMIN, ROLE_BRAND_OFFICER])
        require_scope(brand_id)
        body = get_body()
        jurisdiction_id = req_id(body, "jurisdiction_id")
        unit_count = req_int(body, "unit_count", 1)
        unit_status = opt_enum(body, "unit_status", D.UNIT_STATUSES, "PLANNED")
        operates = opt_bool(body, "operates_under_brand_name", True)
        prefix = opt_string(body, "unit_label_prefix", 1, 40, default="UNIT")
        brand = S.brands.get(brand_id)
        if brand is None:
            not_found("brand")
        jurisdiction = S.jurisdictions.get(jurisdiction_id)
        if jurisdiction is None:
            not_found("jurisdiction")
        labels = ["%s-%04d" % (prefix, n) for n in range(1, unit_count + 1)]
        taken = set(u["unit_label"] for u in D.brand_units(brand_id))
        for label in labels:
            if label in taken:
                fail("ERR_VALIDATION", "unit_label %s is already used within this brand" % label)
        first_id = None
        for label in labels:
            created = insert(S.establishments, {
                "brand_id": brand_id,
                "jurisdiction_id": jurisdiction_id,
                "unit_label": label,
                "unit_status": unit_status,
                "operates_under_brand_name": operates,
                "outstanding_penalty_cents": 0,
                "board_count": 0,
            })
            if first_id is None:
                first_id = created["id"]
        counted, standard, status, reason = D.run_coverage(brand, "OPERATING_ONLY")
        return envelope({
            "brand_id": brand_id,
            "created_count": len(labels),
            "unit_status": unit_status,
            "first_created_establishment_id": first_id,
            "brand_coverage_status": status,
            "brand_counted_unit_count": counted,
        }, 201)

    @app.post("/establishments/<establishment_id>/status-changes")
    def change_unit_status(establishment_id):
        authenticate([ROLE_PLATFORM_ADMIN, ROLE_BRAND_OFFICER])
        establishment = S.establishments.get(establishment_id)
        if establishment is not None:
            require_scope(establishment["brand_id"])
        body = get_body()
        new_status = req_enum(body, "new_unit_status", D.UNIT_STATUSES)
        opt_string(body, "effective_note", 1, 400)
        if establishment is None:
            not_found("establishment")
        if establishment["unit_status"] == "PERMANENTLY_CLOSED":
            fail("ERR_ALREADY_TERMINAL", "unit is permanently closed")
        brand = S.brands[establishment["brand_id"]]
        if new_status == "PERMANENTLY_CLOSED":
            for action in D.est_enforcements(establishment_id):
                if action["status"] not in ("CLOSED_COMPLIANT", "CLOSED_PENALTY"):
                    fail("ERR_UNIT_HAS_OPEN_ENFORCEMENT",
                         "unit still carries an open enforcement file")
        mark(establishment)
        establishment["unit_status"] = new_status
        if new_status == "PERMANENTLY_CLOSED":
            touched_items = {}
            for board in D.est_boards(establishment_id):
                if board["publication_status"] in ("DRAFT", "PUBLISHED"):
                    touched_items.update(D.withdraw_board(board))
            for item in touched_items.values():
                if item["labeling_status"] == "RELABEL_REQUIRED" and not D.item_has_stale_line(item["id"]):
                    mark(item)
                    item["labeling_status"] = "DECLARED"
            D.recompute_est_board_count(establishment)
            D.recompute_obligation_counters(brand)
        D.run_coverage(brand, "OPERATING_ONLY")
        return envelope(D.establishment_out(establishment), 200)

    @app.post("/brands/<brand_id>/coverage-determinations")
    def determine_coverage(brand_id):
        authenticate([ROLE_PLATFORM_ADMIN, ROLE_BRAND_OFFICER])
        require_scope(brand_id)
        body = get_body()
        basis = req_enum(body, "basis", D.COVERAGE_BASES)
        brand = S.brands.get(brand_id)
        if brand is None:
            not_found("brand")
        counted, standard, status, reason = D.run_coverage(brand, basis)
        return envelope({
            "brand_id": brand_id,
            "basis": basis,
            "counted_unit_count": counted,
            "standard_item_count": standard,
            "coverage_status": status,
            "coverage_reason": reason,
            "persisted": True,
        }, 200)

    # ------------------------------------------------------------ logical clock
    @app.post("/_clock/set_current_utc")
    def set_clock():
        authenticate([ROLE_PLATFORM_ADMIN])
        body = get_body()
        target = req_instant(body, "to_iso8601")
        CLOCK.set(target)
        boards_marked_overdue, variances_expired = D.clock_sweep(CLOCK.now())
        return envelope({
            "current_utc": CLOCK.iso(),
            "boards_marked_overdue": boards_marked_overdue,
            "variances_expired": variances_expired,
        }, 200)
