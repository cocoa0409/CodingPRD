"""Menu items, recipes, components, nutrition analyses."""

from decimal import Decimal

import calc
import domain as D
from core import (ROLE_ANALYST, ROLE_BRAND_OFFICER, S, authenticate, body_or_empty,
                  envelope, fail, fmt_date, get_body, insert, mark, not_found,
                  require_scope)
from validate import (opt_decimal, opt_enum, opt_int, opt_string, peek_id, req_date,
                      req_decimal, req_enum, req_id, req_int, req_string)


def _check_choice_group(role, choice_group, selection_mode, selection_limit, siblings):
    if role == "BASE":
        if choice_group is not None or selection_mode is not None or selection_limit is not None:
            fail("ERR_CHOICE_GROUP_INCONSISTENT",
                 "a BASE component must leave choice_group, selection_mode and selection_limit null")
        return
    if choice_group is None or selection_mode is None:
        fail("ERR_CHOICE_GROUP_INCONSISTENT",
             "a CHOICE component requires choice_group and selection_mode")
    if selection_mode == "UP_TO_N":
        if selection_limit is None or selection_limit < 1:
            fail("ERR_CHOICE_GROUP_INCONSISTENT", "UP_TO_N requires a selection_limit of at least 1")
    else:
        if selection_limit is not None:
            fail("ERR_CHOICE_GROUP_INCONSISTENT",
                 "%s must not carry a selection_limit" % selection_mode)
    for sibling in siblings:
        if sibling["choice_group"] != choice_group:
            continue
        if sibling["selection_mode"] != selection_mode or sibling["selection_limit"] != selection_limit:
            fail("ERR_CHOICE_GROUP_INCONSISTENT",
                 "choice_group %s already declares a different selection rule" % choice_group)


def register(app):

    # ------------------------------------------------------------- menu items
    @app.post("/menu-items")
    def create_menu_item():
        authenticate([ROLE_BRAND_OFFICER])
        require_scope(peek_id(body_or_empty(), "brand_id"))
        body = get_body()
        brand_id = req_id(body, "brand_id")
        name = req_string(body, "name", 1, 120)
        item_class = req_enum(body, "item_class", D.ITEM_CLASSES)
        variable_type = opt_enum(body, "variable_type", D.VARIABLE_TYPES, "NONE")
        first_offered_on = req_date(body, "first_offered_on")
        for existing in D.brand_items(brand_id):
            if existing["name"] == name:
                fail("ERR_VALIDATION", "name is already used within this brand")
        brand = S.brands.get(brand_id)
        if brand is None:
            not_found("brand")
        if brand["compliance_posture"] == "FROZEN":
            fail("ERR_BRAND_POSTURE_FROZEN", "brand posture is FROZEN")
        exempt = item_class != "STANDARD"
        item = insert(S.menu_items, {
            "brand_id": brand_id,
            "name": name,
            "item_class": item_class,
            "variable_type": variable_type,
            "first_offered_on": fmt_date(first_offered_on),
            "offer_windows": [],
            "cumulative_offered_days": 0,
            "labeling_exempt": exempt,
            "labeling_status": "NOT_REQUIRED" if exempt else "DECLARATION_PENDING",
            "declared_calorie_min": None,
            "declared_calorie_max": None,
            "declared_sodium_mg": None,
            "approved_recipe_version_no": None,
            "allergen_groups": [],
            "cross_contact_groups": [],
        })
        D.run_coverage(brand, "OPERATING_ONLY")
        return envelope(D.menu_item_out(item), 201)

    @app.post("/menu-items/<menu_item_id>/offer-windows")
    def append_offer_window(menu_item_id):
        authenticate([ROLE_BRAND_OFFICER])
        item = S.menu_items.get(menu_item_id)
        if item is not None:
            require_scope(item["brand_id"])
        body = get_body()
        start = req_date(body, "start_date")
        end = req_date(body, "end_date")
        if item is None:
            not_found("menu_item")
        if start > end:
            fail("ERR_INVALID_DATE_RANGE", "start_date must not fall after end_date")
        if item["item_class"] not in D.TEMPORARY_CLASSES:
            fail("ERR_ITEM_NOT_TEMPORARY", "only TEMPORARY and TEST_MARKET items carry offer windows")
        mark(item)
        item["offer_windows"] = list(item["offer_windows"]) + [{
            "start_date": fmt_date(start),
            "end_date": fmt_date(end),
        }]
        item["cumulative_offered_days"] = D.offered_days_for_year(item, start.year)
        return envelope(D.menu_item_out(item), 200)

    @app.post("/menu-items/<menu_item_id>/exemption-reviews")
    def review_exemption(menu_item_id):
        authenticate([ROLE_BRAND_OFFICER])
        item = S.menu_items.get(menu_item_id)
        if item is not None:
            require_scope(item["brand_id"])
        body = get_body()
        review_year = req_int(body, "review_year", 1, 9999)
        if item is None:
            not_found("menu_item")
        if item["item_class"] not in D.TEMPORARY_CLASSES:
            fail("ERR_ITEM_NOT_TEMPORARY", "only TEMPORARY and TEST_MARKET items are reviewed")
        mark(item)
        days = D.offered_days_for_year(item, review_year)
        item["cumulative_offered_days"] = days
        new_exempt = D.exemption_flag(item["item_class"], days)
        if new_exempt != item["labeling_exempt"]:
            item["labeling_exempt"] = new_exempt
            item["labeling_status"] = D.labeling_status_for(item, new_exempt)
            brand = S.brands[item["brand_id"]]
            D.run_coverage(brand, "OPERATING_ONLY")
            D.stale_published_packets(brand)
            D.recompute_obligation_counters(brand)
        return envelope(D.menu_item_out(item), 200)

    # ---------------------------------------------------------------- recipes
    @app.post("/menu-items/<menu_item_id>/recipes")
    def create_recipe(menu_item_id):
        authenticate([ROLE_ANALYST])
        body = get_body()
        expected_version = req_int(body, "expected_menu_item_version")
        change_note = req_string(body, "change_note", 1, 240)
        item = S.menu_items.get(menu_item_id)
        if item is None:
            not_found("menu_item")
        if expected_version != item["version"]:
            fail("ERR_STALE_MENU_ITEM_VERSION", "expected_menu_item_version is stale")
        brand = S.brands[item["brand_id"]]
        if brand["compliance_posture"] == "FROZEN":
            fail("ERR_BRAND_POSTURE_FROZEN", "brand posture is FROZEN")
        existing = D.item_recipes(menu_item_id)
        version_no = max([r["version_no"] for r in existing]) + 1 if existing else 1
        recipe = insert(S.recipes, {
            "menu_item_id": menu_item_id,
            "version_no": version_no,
            "supersedes_recipe_id": None,
            "status": "DRAFT",
            "revision_round": 0,
            "change_note": change_note,
            "component_count": 0,
            "computed_base_calories": Decimal("0"),
            "computed_declared_min": None,
            "computed_declared_max": None,
            "computed_sodium_mg": None,
            "approved_at": None,
        })
        return envelope(D.recipe_out(recipe), 201)

    @app.post("/recipes/<recipe_id>/components")
    def add_component(recipe_id):
        authenticate([ROLE_ANALYST])
        body = get_body()
        component_name = req_string(body, "component_name", 1, 80)
        role = req_enum(body, "role", D.COMPONENT_ROLES)
        grams = req_decimal(body, "grams", exclusive_min=0, places=2)
        calories_per_100g = req_decimal(body, "calories_per_100g", minimum=0, places=2)
        sodium_mg_per_100g = req_decimal(body, "sodium_mg_per_100g", minimum=0, places=2)
        added_sugar = opt_decimal(body, "added_sugar_g_per_100g", minimum=0, places=2,
                                  default=Decimal("0"))
        allergen_group = opt_enum(body, "allergen_group", D.ALLERGEN_GROUPS, "NONE")
        cross_contact_risk = opt_enum(body, "cross_contact_risk", D.CROSS_CONTACT_RISKS, "NONE")
        choice_group = opt_string(body, "choice_group", 1, 40)
        selection_mode = opt_enum(body, "selection_mode", D.SELECTION_MODES)
        selection_limit = opt_int(body, "selection_limit", 1, 10)
        siblings = D.recipe_components(recipe_id)
        for sibling in siblings:
            if sibling["component_name"] == component_name:
                fail("ERR_VALIDATION", "component_name is already used within this recipe")
        recipe = S.recipes.get(recipe_id)
        if recipe is None:
            not_found("recipe")
        if recipe["status"] != "DRAFT":
            fail("ERR_RECIPE_NOT_DRAFT", "recipe is not DRAFT")
        _check_choice_group(role, choice_group, selection_mode, selection_limit, siblings)
        component = insert(S.components, {
            "recipe_id": recipe_id,
            "component_name": component_name,
            "role": role,
            "choice_group": choice_group,
            "selection_mode": selection_mode,
            "selection_limit": selection_limit,
            "grams": grams,
            "calories_per_100g": calories_per_100g,
            "sodium_mg_per_100g": sodium_mg_per_100g,
            "added_sugar_g_per_100g": added_sugar,
            "allergen_group": allergen_group,
            "cross_contact_risk": cross_contact_risk,
            "component_calories": calc.component_calories(calories_per_100g, grams),
            "component_sodium_mg": calc.component_sodium(sodium_mg_per_100g, grams),
        }, versioned=False)
        D.recompute_recipe_figures(recipe)
        return envelope(D.component_out(component), 201)

    @app.post("/recipes/<recipe_id>/submit-for-analysis")
    def submit_for_analysis(recipe_id):
        user_id, _role = authenticate([ROLE_ANALYST])
        body = get_body()
        method = req_enum(body, "method", ("DATABASE", "LAB_ANALYSIS"))
        recipe = S.recipes.get(recipe_id)
        if recipe is None:
            not_found("recipe")
        if recipe["status"] in ("SUPERSEDED", "REJECTED", "WITHDRAWN"):
            fail("ERR_ALREADY_TERMINAL", "recipe is in a terminal state")
        if recipe["status"] != "DRAFT":
            fail("ERR_RECIPE_NOT_DRAFT", "recipe is not DRAFT")
        components = D.recipe_components(recipe_id)
        if not any(c["role"] == "BASE" for c in components):
            fail("ERR_RECIPE_HAS_NO_BASE_COMPONENT", "recipe carries no BASE component")
        for other in D.item_recipes(recipe["menu_item_id"]):
            if other["id"] != recipe_id and other["status"] == "ANALYSIS_PENDING":
                fail("ERR_VALIDATION",
                     "another recipe of this menu item is already in ANALYSIS_PENDING")
        mark(recipe)
        recipe["status"] = "ANALYSIS_PENDING"
        D.recompute_recipe_figures(recipe)
        analysis = insert(S.analyses, {
            "recipe_id": recipe_id,
            "method": method,
            "status": "SUBMITTED",
            "submitted_by_user_id": user_id,
            "decided_by_user_id": None,
            "decision_note": None,
            "certified_at": None,
            "declared_calorie_min": None,
            "declared_calorie_max": None,
            "declared_sodium_mg": None,
        })
        return envelope(D.analysis_out(analysis), 201)

    @app.post("/nutrition-analyses/<analysis_id>/decision")
    def decide_analysis(analysis_id):
        user_id, _role = authenticate([ROLE_ANALYST])
        body = get_body()
        decision = req_enum(body, "decision", ("CERTIFY", "REJECT"))
        note = opt_string(body, "decision_note", 0, 400, non_blank=False)
        analysis = S.analyses.get(analysis_id)
        if analysis is None:
            not_found("analysis")
        if analysis["status"] != "SUBMITTED":
            fail("ERR_ANALYSIS_ALREADY_DECIDED", "analysis has already been decided")
        if decision == "CERTIFY" and analysis["submitted_by_user_id"] == user_id:
            fail("ERR_SAME_USER_CERTIFICATION",
                 "the submitting analyst may not certify their own analysis")
        recipe = S.recipes[analysis["recipe_id"]]
        if decision == "CERTIFY":
            D.certify_analysis(analysis, recipe, user_id, note)
        else:
            D.reject_analysis(analysis, recipe, user_id, note)
        return envelope(D.analysis_out(analysis), 200)

    @app.post("/recipes/<recipe_id>/withdraw-certification")
    def withdraw_certification(recipe_id):
        authenticate([ROLE_ANALYST])
        body = get_body()
        req_string(body, "reason", 1, 400)
        recipe = S.recipes.get(recipe_id)
        if recipe is None:
            not_found("recipe")
        if recipe["status"] == "SUPERSEDED":
            fail("ERR_ALREADY_TERMINAL", "recipe is superseded")
        if recipe["status"] != "APPROVED":
            fail("ERR_RECIPE_NOT_APPROVED", "recipe is not APPROVED")
        prior_id = recipe["supersedes_recipe_id"]
        if not prior_id or prior_id not in S.recipes:
            fail("ERR_RECIPE_NOT_APPROVED", "recipe has no prior version to restore")
        D.withdraw_certification(recipe)
        return envelope(D.recipe_out(recipe), 200)
