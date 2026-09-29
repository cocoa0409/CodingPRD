"""Derived quantities, serializers, cascades."""

import calc
from core import (CLOCK, S, fail, fmt_date, fmt_instant, force_mark, insert,
                  mark, parse_date, parse_instant, rows)

ALLERGEN_GROUPS = (
    "NONE", "MILK", "EGG", "FISH", "CRUSTACEAN_SHELLFISH", "TREE_NUT",
    "PEANUT", "WHEAT", "SOY", "SESAME",
)
CROSS_CONTACT_RISKS = ("NONE", "SHARED_FRYER", "SHARED_LINE", "SHARED_EQUIPMENT")
ITEM_CLASSES = (
    "STANDARD", "TEMPORARY", "TEST_MARKET", "DAILY_SPECIAL",
    "CUSTOM_ORDER", "SELF_SERVICE",
)
VARIABLE_TYPES = ("NONE", "SIZE_VARIANTS", "FLAVOR_VARIANTS", "COMBINATION_MEAL", "TOPPING_BASED")
UNIT_STATUSES = ("PLANNED", "OPERATING", "TEMPORARILY_CLOSED", "PERMANENTLY_CLOSED")
BOARD_TYPES = ("PRIMARY_MENU_BOARD", "DRIVE_THRU_BOARD", "PRINTED_MENU", "THIRD_PARTY_DELIVERY")
SUCCINCT_VARIANTS = ("FEDERAL_DEFAULT", "STATE_EXTENDED", "OMITTED")
WRITTEN_INFO_CHANNELS = ("IN_STORE_BINDER", "WEBSITE", "QR_HANDOUT", "PHONE_LINE")
REQUIREMENT_CODES = ("SUCCINCT_STATEMENT", "SODIUM_WARNING", "ADDED_SUGAR_ICON", "WRITTEN_INFO_FORMAT")
CITATION_CODES = (
    "CALORIES_NOT_DECLARED", "SUCCINCT_STATEMENT_MISSING", "WRITTEN_INFO_UNAVAILABLE",
    "ALLERGEN_MATRIX_MISSING", "SODIUM_WARNING_MISSING",
)
RESPONSE_TYPES = ("REPRINT_COMPLETED", "VARIANCE_CITED", "DISPUTED")
ACTION_TYPES = (
    "REQUEST_INFO", "ESCALATE", "CLOSE_COMPLIANT", "ASSESS_PENALTY",
    "RESCIND_PENALTY", "CLOSE_PENALTY",
)
PENALTY_BASES = ("PER_BOARD", "PER_ESTABLISHMENT")
COVERAGE_BASES = ("OPERATING_ONLY", "REGISTERED_ALL")
SELECTION_MODES = ("EXACTLY_ONE", "UP_TO_N", "UNLIMITED")
COMPONENT_ROLES = ("BASE", "CHOICE")

CITATION_REQUIREMENT = {
    "SUCCINCT_STATEMENT_MISSING": "SUCCINCT_STATEMENT",
    "SODIUM_WARNING_MISSING": "SODIUM_WARNING",
    "WRITTEN_INFO_UNAVAILABLE": "WRITTEN_INFO_FORMAT",
}

OPEN_REPRINT_STATUSES = ("REPRINT_REQUIRED", "OVERDUE")


# ---------------------------------------------------------------------------
# Lookups (insertion / created_at ascending order everywhere)
# ---------------------------------------------------------------------------

def all_rows(table):
    return rows(table)


def brand_units(brand_id):
    return [r for r in rows(S.establishments) if r["brand_id"] == brand_id]


def brand_items(brand_id):
    return [r for r in rows(S.menu_items) if r["brand_id"] == brand_id]


def brand_packets(brand_id):
    return [r for r in rows(S.packets) if r["brand_id"] == brand_id]


def item_recipes(item_id):
    return [r for r in rows(S.recipes) if r["menu_item_id"] == item_id]


def recipe_components(recipe_id):
    return [r for r in rows(S.components) if r["recipe_id"] == recipe_id]


def board_listings(board_id):
    return [r for r in rows(S.listings) if r["menu_board_id"] == board_id]


def item_listings(item_id):
    return [r for r in rows(S.listings) if r["menu_item_id"] == item_id]


def est_boards(est_id):
    return [r for r in rows(S.boards) if r["establishment_id"] == est_id]


def brand_boards(brand_id):
    unit_ids = set(u["id"] for u in brand_units(brand_id))
    return [r for r in rows(S.boards) if r["establishment_id"] in unit_ids]


def brand_of_board(board):
    est = S.establishments.get(board["establishment_id"])
    if est is None:
        return None
    return S.brands.get(est["brand_id"])


def approved_recipe(item_id):
    for r in item_recipes(item_id):
        if r["status"] == "APPROVED":
            return r
    return None


def brand_variances(brand_id):
    return [r for r in rows(S.variances) if r["brand_id"] == brand_id]


def est_enforcements(est_id):
    return [r for r in rows(S.enforcements) if r["establishment_id"] == est_id]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def brand_out(row):
    out = _common(row)
    out.update({
        "legal_name": row["legal_name"],
        "doing_business_as": row["doing_business_as"],
        "coverage_status": row["coverage_status"],
        "coverage_reason": row["coverage_reason"],
        "counted_unit_count": row["counted_unit_count"],
        "standard_item_count": row["standard_item_count"],
        "compliance_posture": row["compliance_posture"],
        "open_reprint_obligation_count": row["open_reprint_obligation_count"],
        "overdue_board_count": row["overdue_board_count"],
        "open_enforcement_escalated_count": row["open_enforcement_escalated_count"],
        "has_published_disclosure_packet": row["has_published_disclosure_packet"],
    })
    return out


def jurisdiction_out(row):
    out = _common(row)
    out.update({
        "code": row["code"],
        "name": row["name"],
        "preemption_mode": row["preemption_mode"],
        "extra_requirement": row["extra_requirement"],
        "enforcement_tier": row["enforcement_tier"],
        "sodium_warning_threshold_mg": row["sodium_warning_threshold_mg"],
        "required_succinct_statement_variant": row["required_succinct_statement_variant"],
        "reprint_grace_days": row["reprint_grace_days"],
        "assessed_penalty_cents_total": row["assessed_penalty_cents_total"],
    })
    return out


def establishment_out(row):
    out = _common(row)
    out.update({
        "brand_id": row["brand_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "unit_label": row["unit_label"],
        "unit_status": row["unit_status"],
        "operates_under_brand_name": row["operates_under_brand_name"],
        "outstanding_penalty_cents": row["outstanding_penalty_cents"],
        "board_count": row["board_count"],
    })
    return out


def menu_item_out(row):
    out = _common(row)
    out.update({
        "brand_id": row["brand_id"],
        "name": row["name"],
        "item_class": row["item_class"],
        "variable_type": row["variable_type"],
        "first_offered_on": row["first_offered_on"],
        "offer_windows": [dict(w) for w in row["offer_windows"]],
        "cumulative_offered_days": row["cumulative_offered_days"],
        "labeling_exempt": row["labeling_exempt"],
        "labeling_status": row["labeling_status"],
        "declared_calorie_min": row["declared_calorie_min"],
        "declared_calorie_max": row["declared_calorie_max"],
        "declared_sodium_mg": row["declared_sodium_mg"],
        "approved_recipe_version_no": row["approved_recipe_version_no"],
        "allergen_groups": list(row["allergen_groups"]),
        "cross_contact_groups": list(row["cross_contact_groups"]),
    })
    return out


def recipe_out(row):
    out = _common(row)
    out.update({
        "menu_item_id": row["menu_item_id"],
        "version_no": row["version_no"],
        "supersedes_recipe_id": row["supersedes_recipe_id"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "change_note": row["change_note"],
        "component_count": row["component_count"],
        "computed_base_calories": calc.num(row["computed_base_calories"]),
        "computed_declared_min": row["computed_declared_min"],
        "computed_declared_max": row["computed_declared_max"],
        "computed_sodium_mg": row["computed_sodium_mg"],
        "approved_at": row["approved_at"],
    })
    return out


def component_out(row):
    # RecipeComponent carries only id and created_at -- no updated_at, no version.
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "recipe_id": row["recipe_id"],
        "component_name": row["component_name"],
        "role": row["role"],
        "choice_group": row["choice_group"],
        "selection_mode": row["selection_mode"],
        "selection_limit": row["selection_limit"],
        "grams": calc.num(row["grams"]),
        "calories_per_100g": calc.num(row["calories_per_100g"]),
        "sodium_mg_per_100g": calc.num(row["sodium_mg_per_100g"]),
        "added_sugar_g_per_100g": calc.num(row["added_sugar_g_per_100g"]),
        "allergen_group": row["allergen_group"],
        "cross_contact_risk": row["cross_contact_risk"],
        "component_calories": calc.num(row["component_calories"]),
        "component_sodium_mg": calc.num(row["component_sodium_mg"]),
    }


def analysis_out(row):
    out = _common(row)
    out.update({
        "recipe_id": row["recipe_id"],
        "method": row["method"],
        "status": row["status"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decision_note": row["decision_note"],
        "certified_at": row["certified_at"],
        "declared_calorie_min": row["declared_calorie_min"],
        "declared_calorie_max": row["declared_calorie_max"],
        "declared_sodium_mg": row["declared_sodium_mg"],
    })
    return out


def packet_out(row):
    out = _common(row)
    out.update({
        "brand_id": row["brand_id"],
        "packet_version": row["packet_version"],
        "cross_contact_statement": row["cross_contact_statement"],
        "written_info_channels": list(row["written_info_channels"]),
        "status": row["status"],
        "covered_item_count": row["covered_item_count"],
        "allergen_matrix_complete": row["allergen_matrix_complete"],
        "cross_contact_statement_required": row["cross_contact_statement_required"],
        "allergen_rows": [dict(r) for r in row["allergen_rows"]],
        "published_at": row["published_at"],
    })
    return out


def board_out(row):
    out = _common(row)
    out.update({
        "establishment_id": row["establishment_id"],
        "board_type": row["board_type"],
        "succinct_statement_variant": row["succinct_statement_variant"],
        "publication_status": row["publication_status"],
        "calorie_compliance_status": row["calorie_compliance_status"],
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "reprint_deadline": row["reprint_deadline"],
        "reprint_count": row["reprint_count"],
        "listing_count": row["listing_count"],
        "stale_listing_count": row["stale_listing_count"],
    })
    return out


def listing_out(row):
    out = _common(row)
    out.update({
        "menu_board_id": row["menu_board_id"],
        "menu_item_id": row["menu_item_id"],
        "listing_status": row["listing_status"],
        "display_calorie_text": row["display_calorie_text"],
        "declared_min_snapshot": row["declared_min_snapshot"],
        "declared_max_snapshot": row["declared_max_snapshot"],
        "sodium_warning_icon": row["sodium_warning_icon"],
    })
    return out


def variance_out(row):
    out = _common(row)
    out.update({
        "brand_id": row["brand_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "requirement_code": row["requirement_code"],
        "justification": row["justification"],
        "requested_start_date": row["requested_start_date"],
        "requested_end_date": row["requested_end_date"],
        "status": row["status"],
        "effective_start_date": row["effective_start_date"],
        "effective_end_date": row["effective_end_date"],
        "decision_note": row["decision_note"],
        "decided_by_user_id": row["decided_by_user_id"],
    })
    return out


def enforcement_out(row):
    out = _common(row)
    out.update({
        "establishment_id": row["establishment_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "citation_code": row["citation_code"],
        "inspection_note": row["inspection_note"],
        "status": row["status"],
        "info_round_count": row["info_round_count"],
        "response_count": row["response_count"],
        "last_response_type": row["last_response_type"],
        "penalty_basis": row["penalty_basis"],
        "violation_unit_count": row["violation_unit_count"],
        "base_penalty_cents": row["base_penalty_cents"],
        "admin_fee_cents": row["admin_fee_cents"],
        "penalty_total_cents": row["penalty_total_cents"],
        "opened_at": row["opened_at"],
        "closed_at": row["closed_at"],
    })
    return out


# ---------------------------------------------------------------------------
# Coverage, posture, conserved counters (PRD sections 2.9, 2.10, 3.1)
# ---------------------------------------------------------------------------

def count_units(brand_id, basis):
    counted = 0
    for unit in brand_units(brand_id):
        if not unit["operates_under_brand_name"]:
            continue
        if basis == "REGISTERED_ALL":
            if unit["unit_status"] in ("OPERATING", "TEMPORARILY_CLOSED"):
                counted += 1
        else:
            if unit["unit_status"] == "OPERATING":
                counted += 1
    return counted


def count_standard_items(brand_id):
    return len([i for i in brand_items(brand_id) if not i["labeling_exempt"]])


def coverage_decision(counted_unit_count, standard_item_count):
    if standard_item_count == 0:
        return "NOT_COVERED", "NO_STANDARD_MENU_ITEMS"
    if counted_unit_count >= calc.COVERED_UNIT_THRESHOLD:
        return "COVERED", "COVERED_BY_UNIT_COUNT"
    return "NOT_COVERED", "BELOW_UNIT_THRESHOLD"


def compute_coverage(brand, basis):
    counted = count_units(brand["id"], basis)
    standard = count_standard_items(brand["id"])
    status, reason = coverage_decision(counted, standard)
    return counted, standard, status, reason


def run_coverage(brand, basis="OPERATING_ONLY"):
    """Overwrite the four stored coverage fields and bump the brand's version."""
    counted, standard, status, reason = compute_coverage(brand, basis)
    force_mark(brand)
    brand["counted_unit_count"] = counted
    brand["standard_item_count"] = standard
    brand["coverage_status"] = status
    brand["coverage_reason"] = reason
    recompute_posture(brand)
    return counted, standard, status, reason


def recompute_obligation_counters(brand):
    mark(brand)
    boards = brand_boards(brand["id"])
    brand["open_reprint_obligation_count"] = len([
        b for b in boards
        if b["publication_status"] == "PUBLISHED"
        and b["calorie_compliance_status"] in OPEN_REPRINT_STATUSES
    ])
    brand["overdue_board_count"] = len([
        b for b in boards
        if b["publication_status"] == "PUBLISHED"
        and b["calorie_compliance_status"] == "OVERDUE"
    ])
    unit_ids = set(u["id"] for u in brand_units(brand["id"]))
    brand["open_enforcement_escalated_count"] = len([
        e for e in rows(S.enforcements)
        if e["establishment_id"] in unit_ids and e["status"] == "ESCALATED"
    ])
    brand["has_published_disclosure_packet"] = any(
        p["status"] == "PUBLISHED" for p in brand_packets(brand["id"])
    )
    recompute_posture(brand)


def posture_for(coverage_status, overdue_board_count, escalated_count, reprint_count):
    if coverage_status == "COVERED" and (overdue_board_count >= 1 or escalated_count >= 1):
        return "FROZEN"
    if coverage_status == "COVERED" and reprint_count >= 1:
        return "RESTRICTED"
    if coverage_status == "COVERED":
        return "COMPLIANT"
    return "EXEMPT"


def recompute_posture(brand):
    mark(brand)
    brand["compliance_posture"] = posture_for(
        brand["coverage_status"],
        brand["overdue_board_count"],
        brand["open_enforcement_escalated_count"],
        brand["open_reprint_obligation_count"],
    )
    return brand["compliance_posture"]


def recompute_est_board_count(est):
    mark(est)
    est["board_count"] = len([
        b for b in est_boards(est["id"]) if b["publication_status"] != "WITHDRAWN"
    ])


def recompute_est_penalty(est):
    mark(est)
    est["outstanding_penalty_cents"] = sum(
        e["penalty_total_cents"] for e in est_enforcements(est["id"])
        if e["status"] in ("PENALTY_ASSESSED", "CLOSED_PENALTY")
    )


def recompute_jurisdiction_penalty(jur):
    mark(jur)
    jur["assessed_penalty_cents_total"] = sum(
        e["penalty_total_cents"] for e in rows(S.enforcements)
        if e["jurisdiction_id"] == jur["id"]
        and e["status"] in ("PENALTY_ASSESSED", "CLOSED_PENALTY")
    )


def recompute_board_counts(board):
    mark(board)
    lines = board_listings(board["id"])
    board["listing_count"] = len([l for l in lines if l["listing_status"] != "REMOVED"])
    board["stale_listing_count"] = len([l for l in lines if l["listing_status"] == "STALE"])


# ---------------------------------------------------------------------------
# Recipe derivations (PRD section 3.3)
# ---------------------------------------------------------------------------

def recipe_allergen_sets(recipe):
    comps = recipe_components(recipe["id"])
    allergens = sorted(set(
        c["allergen_group"] for c in comps if c["allergen_group"] != "NONE"
    ))
    cross = sorted(set(
        c["allergen_group"] for c in comps
        if c["cross_contact_risk"] != "NONE" and c["allergen_group"] != "NONE"
    ))
    return allergens, cross


def recompute_recipe_figures(recipe):
    item = S.menu_items.get(recipe["menu_item_id"])
    comps = recipe_components(recipe["id"])
    mark(recipe)
    recipe["component_count"] = len(comps)
    base = calc.q2(sum(
        (c["component_calories"] for c in comps if c["role"] == "BASE"),
        calc.dec(0),
    ))
    recipe["computed_base_calories"] = base
    raw_sodium = calc.q2(sum(
        (c["component_sodium_mg"] for c in comps if c["role"] == "BASE"),
        calc.dec(0),
    ))
    recipe["computed_sodium_mg"] = calc.declare_sodium(raw_sodium)
    variable_type = item["variable_type"] if item else "NONE"
    if variable_type == "NONE":
        declared = calc.declare_calories(base)
        recipe["computed_declared_min"] = declared
        recipe["computed_declared_max"] = declared
        return
    groups = {}
    for comp in comps:
        if comp["role"] == "BASE":
            continue
        groups.setdefault(comp["choice_group"], []).append(comp)
    raw_min = base
    raw_max = base
    for members in groups.values():
        members.sort(key=lambda c: (-c["component_calories"], c["created_at"], c["_seq"]))
        cals = [c["component_calories"] for c in members]
        gmin, gmax = calc.group_endpoints(
            cals, members[0]["selection_mode"], members[0]["selection_limit"]
        )
        raw_min += gmin
        raw_max += gmax
    recipe["computed_declared_min"] = calc.declare_calories(calc.q2(raw_min))
    recipe["computed_declared_max"] = calc.declare_calories(calc.q2(raw_max))


def refresh_listing_snapshot(listing, item):
    mark(listing)
    listing["declared_min_snapshot"] = item["declared_calorie_min"]
    listing["declared_max_snapshot"] = item["declared_calorie_max"]
    listing["display_calorie_text"] = calc.display_calorie_text(
        item["declared_calorie_min"], item["declared_calorie_max"]
    )


# ---------------------------------------------------------------------------
# Disclosure packet synthesis (PRD section 3.5)
# ---------------------------------------------------------------------------

def matrix_items(brand_id):
    items = [i for i in brand_items(brand_id) if not i["labeling_exempt"]]
    return sorted(items, key=lambda i: i["name"])


def synthesize_packet(brand):
    covered = 0
    allergen_rows = []
    cross_required = False
    for item in matrix_items(brand["id"]):
        recipe = approved_recipe(item["id"])
        if recipe is not None:
            covered += 1
            allergens, cross = recipe_allergen_sets(recipe)
            for comp in recipe_components(recipe["id"]):
                if comp["cross_contact_risk"] != "NONE":
                    cross_required = True
        else:
            allergens, cross = [], []
        allergen_rows.append({
            "menu_item_id": item["id"],
            "item_name": item["name"],
            "allergen_groups": allergens,
            "cross_contact_groups": cross,
        })
    complete = (
        covered >= calc.MIN_COVERED_ITEMS_FOR_PACKET
        and covered == brand["standard_item_count"]
    )
    return covered, allergen_rows, complete, cross_required


def stale_published_packets(brand):
    for packet in brand_packets(brand["id"]):
        if packet["status"] == "PUBLISHED":
            mark(packet)
            packet["status"] = "STALE"


# ---------------------------------------------------------------------------
# Certification / withdrawal cascades (PRD section 3.4)
# ---------------------------------------------------------------------------

def published_listed_lines(item_id):
    out = []
    for line in item_listings(item_id):
        if line["listing_status"] != "LISTED":
            continue
        board = S.boards.get(line["menu_board_id"])
        if board is not None and board["publication_status"] == "PUBLISHED":
            out.append(line)
    return out


def item_has_stale_line(item_id):
    return any(l["listing_status"] == "STALE" for l in item_listings(item_id))


def certify_analysis(analysis, recipe, user_id, note):
    item = S.menu_items[recipe["menu_item_id"]]
    brand = S.brands[item["brand_id"]]
    prior_max = item["declared_calorie_max"]
    prior_allergens = list(item["allergen_groups"])
    prior_cross = list(item["cross_contact_groups"])

    recompute_recipe_figures(recipe)
    mark(analysis)
    mark(recipe)
    mark(item)

    analysis["status"] = "CERTIFIED"
    analysis["decided_by_user_id"] = user_id
    analysis["decision_note"] = note
    analysis["certified_at"] = CLOCK.iso()
    analysis["declared_calorie_min"] = recipe["computed_declared_min"]
    analysis["declared_calorie_max"] = recipe["computed_declared_max"]
    analysis["declared_sodium_mg"] = recipe["computed_sodium_mg"]

    recipe["status"] = "APPROVED"
    recipe["approved_at"] = CLOCK.iso()

    # Hop 1 -- supersede the prior approved version.
    prior = None
    for other in item_recipes(item["id"]):
        if other["id"] != recipe["id"] and other["status"] == "APPROVED":
            prior = other
            break
    if prior is not None:
        mark(prior)
        prior["status"] = "SUPERSEDED"
        recipe["supersedes_recipe_id"] = prior["id"]
    else:
        recipe["supersedes_recipe_id"] = None

    # Hop 2 -- rewrite the item's declaration.
    allergens, cross = recipe_allergen_sets(recipe)
    item["declared_calorie_min"] = recipe["computed_declared_min"]
    item["declared_calorie_max"] = recipe["computed_declared_max"]
    item["declared_sodium_mg"] = recipe["computed_sodium_mg"]
    item["allergen_groups"] = allergens
    item["cross_contact_groups"] = cross
    item["approved_recipe_version_no"] = recipe["version_no"]

    needs_reprint = calc.reprint_required(prior_max, item["declared_calorie_max"])
    lines = published_listed_lines(item["id"])
    relabel = False
    if not item["labeling_exempt"]:
        if item["labeling_status"] == "DECLARATION_PENDING" and recipe["component_count"] >= 1:
            item["labeling_status"] = "DECLARED"
        if needs_reprint and lines:
            item["labeling_status"] = "RELABEL_REQUIRED"
            relabel = True

    # Hop 3 -- stale the printed lines and open the reprint obligation.
    if relabel:
        touched_boards = {}
        for line in lines:
            mark(line)
            line["listing_status"] = "STALE"
            touched_boards[line["menu_board_id"]] = S.boards[line["menu_board_id"]]
        for board in touched_boards.values():
            recompute_board_counts(board)
            if board["calorie_compliance_status"] == "CURRENT":
                mark(board)
                board["calorie_compliance_status"] = "REPRINT_REQUIRED"
                est = S.establishments[board["establishment_id"]]
                jur = S.jurisdictions[est["jurisdiction_id"]]
                board["reprint_deadline"] = fmt_instant(
                    calc.add_days(CLOCK.now(), jur["reprint_grace_days"])
                )

    # Independent trigger -- a covered item's allergen sets changed.
    if not item["labeling_exempt"] and (allergens != prior_allergens or cross != prior_cross):
        stale_published_packets(brand)

    # Hop 4 -- brand counters and posture.
    recompute_obligation_counters(brand)


def reject_analysis(analysis, recipe, user_id, note):
    mark(analysis)
    mark(recipe)
    analysis["status"] = "REJECTED"
    analysis["decided_by_user_id"] = user_id
    analysis["decision_note"] = note
    if recipe["revision_round"] >= 3:
        recipe["status"] = "REJECTED"
    else:
        recipe["status"] = "DRAFT"
        recipe["revision_round"] = recipe["revision_round"] + 1


def withdraw_certification(recipe):
    item = S.menu_items[recipe["menu_item_id"]]
    brand = S.brands[item["brand_id"]]
    prior = S.recipes.get(recipe["supersedes_recipe_id"])

    mark(recipe)
    recipe["status"] = "WITHDRAWN"

    # Hop 1 -- restore the superseded version.
    mark(prior)
    prior["status"] = "APPROVED"
    prior["approved_at"] = CLOCK.iso()

    # Hop 2 -- rewrite the item's declaration from the restored recipe.
    mark(item)
    allergens, cross = recipe_allergen_sets(prior)
    item["declared_calorie_min"] = prior["computed_declared_min"]
    item["declared_calorie_max"] = prior["computed_declared_max"]
    item["declared_sodium_mg"] = prior["computed_sodium_mg"]
    item["allergen_groups"] = allergens
    item["cross_contact_groups"] = cross
    item["approved_recipe_version_no"] = prior["version_no"]

    # Hop 3 -- stale lines return to LISTED; boards return to CURRENT.
    touched_boards = {}
    for line in item_listings(item["id"]):
        if line["listing_status"] == "STALE":
            mark(line)
            line["listing_status"] = "LISTED"
            refresh_listing_snapshot(line, item)
            touched_boards[line["menu_board_id"]] = S.boards[line["menu_board_id"]]
    for board in touched_boards.values():
        recompute_board_counts(board)
        if board["stale_listing_count"] == 0 and board["calorie_compliance_status"] in OPEN_REPRINT_STATUSES:
            mark(board)
            board["calorie_compliance_status"] = "CURRENT"
            board["reprint_deadline"] = None

    # Hop 4 -- counters restored, labeling status restored, posture recomputed.
    if item["labeling_status"] == "RELABEL_REQUIRED":
        item["labeling_status"] = "DECLARED"
    recompute_obligation_counters(brand)


def reprint_board(board):
    brand = brand_of_board(board)
    touched_items = {}
    for line in board_listings(board["id"]):
        if line["listing_status"] == "STALE":
            mark(line)
            line["listing_status"] = "LISTED"
            item = S.menu_items[line["menu_item_id"]]
            refresh_listing_snapshot(line, item)
            touched_items[item["id"]] = item
    mark(board)
    board["reprint_count"] = board["reprint_count"] + 1
    board["reprint_deadline"] = None
    board["calorie_compliance_status"] = "CURRENT"
    recompute_board_counts(board)

    for item in touched_items.values():
        if item["labeling_status"] == "RELABEL_REQUIRED" and not item_has_stale_line(item["id"]):
            mark(item)
            item["labeling_status"] = "DECLARED"

    if brand is not None:
        recompute_obligation_counters(brand)


def withdraw_board(board):
    """Board withdrawal used by the permanent-closure cascade."""
    mark(board)
    board["publication_status"] = "WITHDRAWN"
    touched_items = {}
    for line in board_listings(board["id"]):
        if line["listing_status"] in ("LISTED", "STALE"):
            mark(line)
            line["listing_status"] = "REMOVED"
            item = S.menu_items.get(line["menu_item_id"])
            if item is not None:
                touched_items[item["id"]] = item
    recompute_board_counts(board)
    return touched_items


# ---------------------------------------------------------------------------
# Exemption arithmetic (PRD section 3.2)
# ---------------------------------------------------------------------------

TEMPORARY_CLASSES = ("TEMPORARY", "TEST_MARKET")
ALWAYS_EXEMPT_CLASSES = ("DAILY_SPECIAL", "CUSTOM_ORDER", "SELF_SERVICE")


def windows_in_year(item, year):
    out = []
    for window in item["offer_windows"]:
        start = parse_date(window["start_date"])
        end = parse_date(window["end_date"])
        if start is None or end is None:
            continue
        if start.year == year:
            out.append((start, end))
    return out


def offered_days_for_year(item, year):
    return calc.merged_day_count(windows_in_year(item, year))


def exemption_flag(item_class, cumulative_offered_days):
    if item_class == "STANDARD":
        return False
    if item_class in ALWAYS_EXEMPT_CLASSES:
        return True
    return cumulative_offered_days < calc.EXEMPTION_DAY_LIMIT


def labeling_status_for(item, exempt):
    if exempt:
        return "NOT_REQUIRED"
    recipe = approved_recipe(item["id"])
    if recipe is None:
        return "DECLARATION_PENDING"
    return "DECLARED"


# ---------------------------------------------------------------------------
# Variance coverage (PRD sections 3.6, 3.9)
# ---------------------------------------------------------------------------

def granted_variance_covers(brand_id, jurisdiction_id, requirement_code, day):
    if requirement_code is None or day is None:
        return False
    for variance in rows(S.variances):
        if variance["status"] != "GRANTED":
            continue
        if variance["brand_id"] != brand_id:
            continue
        if variance["jurisdiction_id"] != jurisdiction_id:
            continue
        if variance["requirement_code"] != requirement_code:
            continue
        start = parse_date(variance["effective_start_date"])
        end = parse_date(variance["effective_end_date"])
        if start is None or end is None:
            continue
        if start <= day <= end:
            return True
    return False


# ---------------------------------------------------------------------------
# Logical clock sweep (PRD section 3.7)
# ---------------------------------------------------------------------------

def clock_sweep(new_instant):
    new_day = new_instant.astimezone(CLOCK.now().tzinfo).date()
    boards_marked_overdue = 0
    touched_brands = {}
    for board in rows(S.boards):
        if board["publication_status"] != "PUBLISHED":
            continue
        if board["calorie_compliance_status"] != "REPRINT_REQUIRED":
            continue
        deadline = parse_instant(board["reprint_deadline"])
        if deadline is None or not deadline < new_instant:
            continue
        mark(board)
        board["calorie_compliance_status"] = "OVERDUE"
        boards_marked_overdue += 1
        brand = brand_of_board(board)
        if brand is not None:
            touched_brands[brand["id"]] = brand

    variances_expired = 0
    for variance in rows(S.variances):
        if variance["status"] != "GRANTED":
            continue
        end = parse_date(variance["effective_end_date"])
        if end is None or not end < new_day:
            continue
        mark(variance)
        variance["status"] = "EXPIRED"
        variances_expired += 1

    for brand in touched_brands.values():
        recompute_obligation_counters(brand)

    return boards_marked_overdue, variances_expired
