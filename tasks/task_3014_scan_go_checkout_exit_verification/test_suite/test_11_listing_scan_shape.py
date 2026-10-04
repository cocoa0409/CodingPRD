"""Session-concurrency constraint, scan shape checks, and listing reachability."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    create_item,
    create_member,
    create_session,
    member_headers,
    scan_unit_line,
    setup_club_member,
    validate_error,
    validate_paginated,
)


class TestScanShape:
    def test_scan_unit_item_with_zero_quantity_rejected(self, api):
        """PRD §3.2: "either a `quantity` (required for a `UNIT` item, and it
        must be at least 1, else `ERR_INVALID_QUANTITY`)".

        Design: Corner/validations/scan_unit_item_with_zero_quantity_rejected
        """
        club, item, member, session, _line = _setup_open_session(api)
        resp = api.scan_line(
            session["id"], {"catalog_item_id": item["id"], "quantity": 0},
            member_headers(member),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)

    def test_scan_weighted_item_with_zero_weight_rejected(self, api):
        """PRD §3.2: "or a `weight_grams` scale reading (required for a
        `WEIGHTED` item, and it must be strictly greater than 0, else
        `ERR_INVALID_WEIGHT`)".

        Design: Corner/validations/scan_weighted_item_with_zero_weight_rejected
        """
        club, member = setup_club_member()
        item = create_item(
            club["id"], sku="BAN", pricing_mode="WEIGHTED",
            price_per_pound_cents=250, unit_price_cents=None,
        )
        session = create_session(club, member)
        resp = api.scan_line(
            session["id"], {"catalog_item_id": item["id"], "weight_grams": 0},
            member_headers(member),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WEIGHT)


class TestOneActiveSession:
    def test_second_active_session_same_member_club_rejected(self, api):
        """PRD §3.2: "Session creation is refused with ... and with
        `ERR_SESSION_ALREADY_ACTIVE` when the member already has a non-terminal
        session at that same club — only one active session per member per
        club is permitted."

        Design: Corner/validations/second_active_session_same_member_club_rejected
        """
        club, member = setup_club_member()
        first = create_session(club, member)
        assert first["status"] == "OPEN"

        resp = api.create_scan_session(club["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_SESSION_ALREADY_ACTIVE)


class TestListingReachability:
    def test_catalog_item_scan_lines_reverse_reachability(self, api):
        """PRD §3.1: "For recall audits, the platform can list every scan line
        that references a given catalog item."

        Design: Corner/endpoints/catalog_item_scan_lines_reverse_reachability
        """
        club, item, member, session, line = _setup_open_session(api, quantity=2)
        resp = api.list_catalog_item_scan_lines(item["id"], ADMIN)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["catalog_item_id"] == item["id"]
        assert data[0]["id"] == line["id"]

    def test_member_scan_sessions_subresource_lists_only_own_sessions(self, api):
        """PRD §3.2: "A member begins shopping by creating a scan session
        against a `club_id`; the creating member's identity is taken from
        `X-User-ID` and recorded as the session's `member_id`."; PRD §4: "GET
        | `/members/{id}/scan-sessions` | List a member's scan sessions | Any".

        Design: Corner/endpoints/member_scan_sessions_subresource_lists_only_own_sessions
        """
        club, _m = setup_club_member()
        member_a = create_member(club["id"], tier="CLUB", birth_year=1990)
        member_b = create_member(club["id"], tier="CLUB", birth_year=1991)
        create_session(club, member_a)

        resp = api.list_member_scan_sessions(member_a["id"], ADMIN)
        _data_a, meta_a = validate_paginated(resp)
        assert meta_a["total_count"] == 1

        resp = api.list_member_scan_sessions(member_b["id"], ADMIN)
        _data_b, meta_b = validate_paginated(resp)
        assert meta_b["total_count"] == 0


def _setup_open_session(api, quantity=1):
    club, member = setup_club_member()
    item = create_item(club["id"], sku="MILK", unit_price_cents=500)
    session = create_session(club, member)
    line = None
    if quantity:
        line = scan_unit_line(session, member, item, quantity=quantity)
    return club, item, member, session, line
