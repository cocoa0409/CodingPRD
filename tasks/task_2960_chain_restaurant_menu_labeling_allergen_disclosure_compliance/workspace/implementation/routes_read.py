"""The 24 read endpoints.  Open to all five roles, never ownership-scoped."""

import domain as D
from core import (S, any_role, envelope, not_found, page, parse_pagination, rows)
from flask import request


def _filtered(items, filters):
    out = items
    for field, value in filters.items():
        if value is None:
            continue
        out = [r for r in out if r.get(field) == value]
    return out


def _args(*names):
    return dict((n, request.args.get(n)) for n in names)


def register(app):

    # --------------------------------------------------------------- brands
    @app.get("/brands/<brand_id>")
    def get_brand(brand_id):
        any_role()
        brand = S.brands.get(brand_id)
        if brand is None:
            not_found("brand")
        return envelope(D.brand_out(brand), 200)

    @app.get("/brands/<brand_id>/compliance-summary")
    def get_compliance_summary(brand_id):
        any_role()
        brand = S.brands.get(brand_id)
        if brand is None:
            not_found("brand")
        counted, standard, status, reason = D.compute_coverage(brand, "OPERATING_ONLY")
        boards = D.brand_boards(brand_id)
        reprint = len([
            b for b in boards
            if b["publication_status"] == "PUBLISHED"
            and b["calorie_compliance_status"] in D.OPEN_REPRINT_STATUSES
        ])
        overdue = len([
            b for b in boards
            if b["publication_status"] == "PUBLISHED"
            and b["calorie_compliance_status"] == "OVERDUE"
        ])
        units = D.brand_units(brand_id)
        unit_ids = set(u["id"] for u in units)
        escalated = len([
            e for e in rows(S.enforcements)
            if e["establishment_id"] in unit_ids and e["status"] == "ESCALATED"
        ])
        has_published = any(p["status"] == "PUBLISHED" for p in D.brand_packets(brand_id))
        outstanding = sum(u["outstanding_penalty_cents"] for u in units)
        return envelope({
            "brand_id": brand_id,
            "coverage_status": status,
            "coverage_reason": reason,
            "counted_unit_count": counted,
            "standard_item_count": standard,
            "compliance_posture": D.posture_for(status, overdue, escalated, reprint),
            "open_reprint_obligation_count": reprint,
            "overdue_board_count": overdue,
            "open_enforcement_escalated_count": escalated,
            "has_published_disclosure_packet": has_published,
            "outstanding_penalty_cents_total": outstanding,
        }, 200)

    @app.get("/brands/<brand_id>/disclosure-packets")
    def list_brand_packets(brand_id):
        any_role()
        limit, offset = parse_pagination()
        if brand_id not in S.brands:
            not_found("brand")
        items = _filtered(D.brand_packets(brand_id), _args("status"))
        items = sorted(items, key=lambda p: -p["packet_version"])
        return page(items, limit, offset, D.packet_out)

    @app.get("/brands/<brand_id>/variance-requests")
    def list_brand_variances(brand_id):
        any_role()
        limit, offset = parse_pagination()
        if brand_id not in S.brands:
            not_found("brand")
        items = _filtered(D.brand_variances(brand_id), _args("status", "requirement_code"))
        return page(items, limit, offset, D.variance_out)

    # -------------------------------------------------------- jurisdictions
    @app.get("/jurisdictions/<jurisdiction_id>")
    def get_jurisdiction(jurisdiction_id):
        any_role()
        jurisdiction = S.jurisdictions.get(jurisdiction_id)
        if jurisdiction is None:
            not_found("jurisdiction")
        return envelope(D.jurisdiction_out(jurisdiction), 200)

    @app.get("/jurisdictions/<jurisdiction_id>/variance-requests")
    def list_jurisdiction_variances(jurisdiction_id):
        any_role()
        limit, offset = parse_pagination()
        if jurisdiction_id not in S.jurisdictions:
            not_found("jurisdiction")
        items = [v for v in rows(S.variances) if v["jurisdiction_id"] == jurisdiction_id]
        items = _filtered(items, _args("status", "brand_id"))
        return page(items, limit, offset, D.variance_out)

    @app.get("/jurisdictions/<jurisdiction_id>/enforcement-actions")
    def list_jurisdiction_enforcements(jurisdiction_id):
        any_role()
        limit, offset = parse_pagination()
        if jurisdiction_id not in S.jurisdictions:
            not_found("jurisdiction")
        items = [e for e in rows(S.enforcements) if e["jurisdiction_id"] == jurisdiction_id]
        items = _filtered(items, _args("status"))
        return page(items, limit, offset, D.enforcement_out)

    # ------------------------------------------------------- establishments
    @app.get("/establishments")
    def list_establishments():
        any_role()
        limit, offset = parse_pagination()
        items = _filtered(rows(S.establishments),
                          _args("brand_id", "jurisdiction_id", "unit_status"))
        return page(items, limit, offset, D.establishment_out)

    @app.get("/establishments/<establishment_id>")
    def get_establishment(establishment_id):
        any_role()
        establishment = S.establishments.get(establishment_id)
        if establishment is None:
            not_found("establishment")
        return envelope(D.establishment_out(establishment), 200)

    @app.get("/establishments/<establishment_id>/enforcement-actions")
    def list_establishment_enforcements(establishment_id):
        any_role()
        limit, offset = parse_pagination()
        if establishment_id not in S.establishments:
            not_found("establishment")
        items = _filtered(D.est_enforcements(establishment_id), _args("status"))
        return page(items, limit, offset, D.enforcement_out)

    # ----------------------------------------------------------- menu items
    @app.get("/menu-items")
    def list_menu_items():
        any_role()
        limit, offset = parse_pagination()
        items = _filtered(rows(S.menu_items),
                          _args("brand_id", "item_class", "labeling_status"))
        return page(items, limit, offset, D.menu_item_out)

    @app.get("/menu-items/<menu_item_id>")
    def get_menu_item(menu_item_id):
        any_role()
        item = S.menu_items.get(menu_item_id)
        if item is None:
            not_found("menu_item")
        return envelope(D.menu_item_out(item), 200)

    @app.get("/menu-items/<menu_item_id>/listings")
    def list_item_listings(menu_item_id):
        any_role()
        limit, offset = parse_pagination()
        if menu_item_id not in S.menu_items:
            not_found("menu_item")
        items = _filtered(D.item_listings(menu_item_id), _args("listing_status"))
        return page(items, limit, offset, D.listing_out)

    # -------------------------------------------------------------- recipes
    @app.get("/recipes")
    def list_recipes():
        any_role()
        limit, offset = parse_pagination()
        items = _filtered(rows(S.recipes),
                          _args("menu_item_id", "supersedes_recipe_id", "status"))
        return page(items, limit, offset, D.recipe_out)

    @app.get("/recipes/<recipe_id>")
    def get_recipe(recipe_id):
        any_role()
        recipe = S.recipes.get(recipe_id)
        if recipe is None:
            not_found("recipe")
        return envelope(D.recipe_out(recipe), 200)

    @app.get("/recipes/<recipe_id>/components")
    def list_components(recipe_id):
        any_role()
        limit, offset = parse_pagination()
        if recipe_id not in S.recipes:
            not_found("recipe")
        items = _filtered(D.recipe_components(recipe_id), _args("role", "choice_group"))
        return page(items, limit, offset, D.component_out)

    @app.get("/recipes/<recipe_id>/nutrition-analyses")
    def list_recipe_analyses(recipe_id):
        any_role()
        limit, offset = parse_pagination()
        if recipe_id not in S.recipes:
            not_found("recipe")
        items = [a for a in rows(S.analyses) if a["recipe_id"] == recipe_id]
        items = _filtered(items, _args("status"))
        return page(items, limit, offset, D.analysis_out)

    @app.get("/nutrition-analyses/<analysis_id>")
    def get_analysis(analysis_id):
        any_role()
        analysis = S.analyses.get(analysis_id)
        if analysis is None:
            not_found("analysis")
        return envelope(D.analysis_out(analysis), 200)

    # ---------------------------------------------------------- menu boards
    @app.get("/menu-boards")
    def list_boards():
        any_role()
        limit, offset = parse_pagination()
        items = _filtered(rows(S.boards), _args(
            "establishment_id", "board_type", "publication_status",
            "calorie_compliance_status"))
        return page(items, limit, offset, D.board_out)

    @app.get("/menu-boards/<board_id>")
    def get_board(board_id):
        any_role()
        board = S.boards.get(board_id)
        if board is None:
            not_found("board")
        return envelope(D.board_out(board), 200)

    @app.get("/menu-boards/<board_id>/listings")
    def list_board_listings(board_id):
        any_role()
        limit, offset = parse_pagination()
        if board_id not in S.boards:
            not_found("board")
        items = _filtered(D.board_listings(board_id), _args("listing_status"))
        return page(items, limit, offset, D.listing_out)

    # ---------------------------------------------- packets, variances, files
    @app.get("/disclosure-packets/<packet_id>")
    def get_packet(packet_id):
        any_role()
        packet = S.packets.get(packet_id)
        if packet is None:
            not_found("packet")
        return envelope(D.packet_out(packet), 200)

    @app.get("/variance-requests/<variance_id>")
    def get_variance(variance_id):
        any_role()
        variance = S.variances.get(variance_id)
        if variance is None:
            not_found("variance")
        return envelope(D.variance_out(variance), 200)

    @app.get("/enforcement-actions/<action_id>")
    def get_enforcement(action_id):
        any_role()
        action = S.enforcements.get(action_id)
        if action is None:
            not_found("enforcement")
        return envelope(D.enforcement_out(action), 200)
