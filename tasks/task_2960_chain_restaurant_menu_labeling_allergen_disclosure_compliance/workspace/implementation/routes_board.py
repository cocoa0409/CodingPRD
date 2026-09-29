"""Disclosure packets, menu boards, board listings, publication, reprints."""

import calc
import domain as D
from core import (CLOCK, ROLE_BRAND_OFFICER, ROLE_PUBLISHER, S, authenticate,
                  body_or_empty, envelope, fail, fmt_instant, get_body, insert, mark,
                  not_found, parse_instant, require_scope)
from validate import (opt_bool, opt_instant, opt_string, peek_id, req_enum,
                      req_enum_list, req_id, req_instant, req_int, req_string)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; a null end means open-ended."""
    if a_end is not None and b_start is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start is not None and a_start >= b_end:
        return False
    return True


def register(app):

    # ------------------------------------------------------ disclosure packets
    @app.post("/brands/<brand_id>/disclosure-packets")
    def draft_packet(brand_id):
        authenticate([ROLE_BRAND_OFFICER])
        require_scope(brand_id)
        body = get_body()
        expected_version = req_int(body, "expected_brand_version")
        statement = req_string(body, "cross_contact_statement", 0, 400, non_blank=False)
        channels = req_enum_list(body, "written_info_channels", D.WRITTEN_INFO_CHANNELS, 1, 4)
        brand = S.brands.get(brand_id)
        if brand is None:
            not_found("brand")
        if expected_version != brand["version"]:
            fail("ERR_STALE_BRAND_VERSION", "expected_brand_version is stale")
        if brand["coverage_status"] != "COVERED":
            fail("ERR_BRAND_NOT_COVERED", "brand is not COVERED")
        covered, allergen_rows, complete, cross_required = D.synthesize_packet(brand)
        existing = D.brand_packets(brand_id)
        packet_version = max([p["packet_version"] for p in existing]) + 1 if existing else 1
        packet = insert(S.packets, {
            "brand_id": brand_id,
            "packet_version": packet_version,
            "cross_contact_statement": statement,
            "written_info_channels": channels,
            "status": "DRAFT",
            "covered_item_count": covered,
            "allergen_matrix_complete": complete,
            "cross_contact_statement_required": cross_required,
            "allergen_rows": allergen_rows,
            "published_at": None,
        })
        return envelope(D.packet_out(packet), 201)

    @app.post("/disclosure-packets/<packet_id>/publish")
    def publish_packet(packet_id):
        authenticate([ROLE_BRAND_OFFICER])
        packet = S.packets.get(packet_id)
        if packet is not None:
            require_scope(packet["brand_id"])
        get_body()
        if packet is None:
            not_found("packet")
        if packet["status"] == "SUPERSEDED":
            fail("ERR_ALREADY_TERMINAL", "packet is superseded")
        if packet["status"] != "DRAFT":
            fail("ERR_PACKET_NOT_DRAFT", "packet is not DRAFT")
        brand = S.brands[packet["brand_id"]]
        mark(packet)
        covered, allergen_rows, complete, cross_required = D.synthesize_packet(brand)
        packet["covered_item_count"] = covered
        packet["allergen_rows"] = allergen_rows
        packet["allergen_matrix_complete"] = complete
        packet["cross_contact_statement_required"] = cross_required
        if not packet["allergen_matrix_complete"]:
            fail("ERR_ALLERGEN_MATRIX_INCOMPLETE", "the allergen matrix is incomplete")
        if cross_required and packet["cross_contact_statement"].strip() == "":
            fail("ERR_CROSS_CONTACT_STATEMENT_REQUIRED",
                 "a cross-contact statement is required")
        if len(packet["written_info_channels"]) < 1:
            fail("ERR_VALIDATION", "written_info_channels must hold at least one entry")
        packet["status"] = "PUBLISHED"
        packet["published_at"] = CLOCK.iso()
        for other in D.brand_packets(brand["id"]):
            if other["id"] == packet["id"]:
                continue
            if other["status"] in ("PUBLISHED", "STALE"):
                mark(other)
                other["status"] = "SUPERSEDED"
        D.recompute_obligation_counters(brand)
        return envelope(D.packet_out(packet), 200)

    # ------------------------------------------------------------- menu boards
    @app.post("/menu-boards")
    def create_board():
        authenticate([ROLE_PUBLISHER])
        require_scope(peek_id(body_or_empty(), "establishment_id"))
        body = get_body()
        establishment_id = req_id(body, "establishment_id")
        board_type = req_enum(body, "board_type", D.BOARD_TYPES)
        variant = req_enum(body, "succinct_statement_variant", D.SUCCINCT_VARIANTS)
        establishment = S.establishments.get(establishment_id)
        if establishment is None:
            not_found("establishment")
        brand = S.brands[establishment["brand_id"]]
        if brand["compliance_posture"] == "FROZEN":
            fail("ERR_BRAND_POSTURE_FROZEN", "brand posture is FROZEN")
        board = insert(S.boards, {
            "establishment_id": establishment_id,
            "board_type": board_type,
            "succinct_statement_variant": variant,
            "publication_status": "DRAFT",
            "calorie_compliance_status": "CURRENT",
            "effective_from": None,
            "effective_to": None,
            "reprint_deadline": None,
            "reprint_count": 0,
            "listing_count": 0,
            "stale_listing_count": 0,
        })
        D.recompute_est_board_count(establishment)
        return envelope(D.board_out(board), 201)

    @app.post("/menu-boards/<board_id>/listings")
    def create_listing(board_id):
        authenticate([ROLE_PUBLISHER])
        board = S.boards.get(board_id)
        if board is not None:
            require_scope(board["establishment_id"])
        body = get_body()
        menu_item_id = req_id(body, "menu_item_id")
        icon = opt_bool(body, "sodium_warning_icon", False)
        if board is None:
            not_found("board")
        item = S.menu_items.get(menu_item_id)
        if item is None:
            not_found("menu_item")
        if board["publication_status"] == "WITHDRAWN":
            fail("ERR_ALREADY_TERMINAL", "board is withdrawn")
        if board["publication_status"] != "DRAFT":
            fail("ERR_BOARD_NOT_DRAFT", "board is not DRAFT")
        establishment = S.establishments[board["establishment_id"]]
        brand = S.brands[establishment["brand_id"]]
        if brand["compliance_posture"] == "FROZEN":
            fail("ERR_BRAND_POSTURE_FROZEN", "brand posture is FROZEN")
        if item["brand_id"] != brand["id"]:
            fail("ERR_ITEM_BRAND_MISMATCH", "menu item belongs to a different brand")
        for line in D.board_listings(board_id):
            if line["menu_item_id"] == menu_item_id and line["listing_status"] != "REMOVED":
                fail("ERR_DUPLICATE_LISTING", "menu item is already listed on this board")
        listing = insert(S.listings, {
            "menu_board_id": board_id,
            "menu_item_id": menu_item_id,
            "listing_status": "LISTED",
            "display_calorie_text": calc.display_calorie_text(
                item["declared_calorie_min"], item["declared_calorie_max"]),
            "declared_min_snapshot": item["declared_calorie_min"],
            "declared_max_snapshot": item["declared_calorie_max"],
            "sodium_warning_icon": icon,
        })
        D.recompute_board_counts(board)
        return envelope(D.listing_out(listing), 201)

    @app.post("/menu-boards/<board_id>/publish")
    def publish_board(board_id):
        authenticate([ROLE_PUBLISHER])
        board = S.boards.get(board_id)
        if board is not None:
            require_scope(board["establishment_id"])
        body = get_body()
        effective_from = req_instant(body, "effective_from")
        effective_to = opt_instant(body, "effective_to")
        if board is None:
            not_found("board")
        if board["publication_status"] == "WITHDRAWN":
            fail("ERR_ALREADY_TERMINAL", "board is withdrawn")
        if board["publication_status"] != "DRAFT":
            fail("ERR_BOARD_NOT_DRAFT", "board is not DRAFT")
        establishment = S.establishments[board["establishment_id"]]
        jurisdiction = S.jurisdictions[establishment["jurisdiction_id"]]
        brand = S.brands[establishment["brand_id"]]
        if brand["compliance_posture"] == "FROZEN":
            fail("ERR_BRAND_POSTURE_FROZEN", "brand posture is FROZEN")
        if brand["coverage_status"] != "COVERED":
            fail("ERR_BRAND_NOT_COVERED", "brand is not COVERED")
        published_packet = None
        for packet in D.brand_packets(brand["id"]):
            if packet["status"] == "PUBLISHED":
                published_packet = packet
                break
        if published_packet is None:
            fail("ERR_NO_PUBLISHED_PACKET", "brand has no PUBLISHED disclosure packet")
        if not published_packet["allergen_matrix_complete"]:
            fail("ERR_ALLERGEN_MATRIX_INCOMPLETE", "the published packet's matrix is incomplete")
        if board["succinct_statement_variant"] != jurisdiction["required_succinct_statement_variant"]:
            if not D.granted_variance_covers(
                    brand["id"], jurisdiction["id"], "SUCCINCT_STATEMENT",
                    effective_from.date()):
                fail("ERR_SUCCINCT_STATEMENT_MISMATCH",
                     "succinct statement variant does not match the authority's requirement")
        lines = [l for l in D.board_listings(board_id) if l["listing_status"] != "REMOVED"]
        if jurisdiction["extra_requirement"] == "SODIUM_WARNING":
            for line in lines:
                item = S.menu_items[line["menu_item_id"]]
                sodium = item["declared_sodium_mg"]
                if sodium is None:
                    continue
                if sodium >= jurisdiction["sodium_warning_threshold_mg"] and not line["sodium_warning_icon"]:
                    fail("ERR_SODIUM_WARNING_ICON_REQUIRED",
                         "a sodium warning icon is required on this line")
        if board["listing_count"] < 1:
            fail("ERR_ITEM_CALORIES_UNDECLARED", "the board carries no lines")
        for line in lines:
            item = S.menu_items[line["menu_item_id"]]
            if item["labeling_exempt"]:
                continue
            if (item["labeling_status"] in ("DECLARED", "RELABEL_REQUIRED")
                    and item["declared_calorie_max"] is not None):
                continue
            fail("ERR_ITEM_CALORIES_UNDECLARED", "a listed item has no calorie declaration")
        if effective_to is not None and effective_from > effective_to:
            fail("ERR_INVALID_DATE_RANGE", "effective_from must not fall after effective_to")
        for other in D.est_boards(establishment["id"]):
            if other["id"] == board_id:
                continue
            if other["publication_status"] != "PUBLISHED":
                continue
            if other["board_type"] != board["board_type"]:
                continue
            if _overlaps(effective_from, effective_to,
                         parse_instant(other["effective_from"]),
                         parse_instant(other["effective_to"])):
                fail("ERR_BOARD_WINDOW_CONFLICT",
                     "the display window conflicts with an already published board")
        mark(board)
        board["publication_status"] = "PUBLISHED"
        board["effective_from"] = fmt_instant(effective_from)
        board["effective_to"] = fmt_instant(effective_to)
        for line in lines:
            D.refresh_listing_snapshot(line, S.menu_items[line["menu_item_id"]])
        D.recompute_est_board_count(establishment)
        return envelope(D.board_out(board), 200)

    @app.post("/menu-boards/<board_id>/reprint")
    def reprint_board(board_id):
        authenticate([ROLE_PUBLISHER])
        board = S.boards.get(board_id)
        if board is not None:
            require_scope(board["establishment_id"])
        body = get_body()
        opt_string(body, "reprint_note", 0, 400, non_blank=False)
        if board is None:
            not_found("board")
        if board["publication_status"] == "WITHDRAWN":
            fail("ERR_ALREADY_TERMINAL", "board is withdrawn")
        if board["publication_status"] != "PUBLISHED" or board["stale_listing_count"] < 1:
            fail("ERR_NO_STALE_LISTINGS", "the board carries no stale lines")
        D.reprint_board(board)
        return envelope(D.board_out(board), 200)
