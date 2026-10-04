"""Deal-driven layouts and early-access events: window geometry, supersede
semantics, jurisdictional gates, member gates, and the discount cap."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_aisle,
    create_aisle_assignment_payload,
    create_default_jurisdiction,
    create_event,
    create_jurisdiction,
    create_lot,
    create_member,
    create_priced_lot,
    create_store,
    create_vendor,
    get_lot,
    get_store,
    get_success_data,
    make_club_member_headers,
    set_clock,
    setup_sellable_store,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
FLOOR = TEST_USERS["store_manager_headers"]


def test_event_window_half_open_adjacency(api):
    """PRD §3.9: "The event carries `starts_at` and `ends_at` defining a
    half-open window — the start instant is included, the end instant
    excluded" and "must not overlap any `SCHEDULED` or `ACTIVE` event on the
    same lot under half-open semantics, where one event ending exactly when
    another begins is allowed; a true overlap is `ERR_EVENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/event_window_half_open_adjacency
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_priced_lot(vendor["id"], jur["id"])
    ev_a = create_event(lot["id"], starts_at="2026-09-02T10:00:00Z",
                        ends_at="2026-09-02T12:00:00Z", min_tier="SILVER",
                        extra_discount_pct=10)
    assert ev_a["status"] == "SCHEDULED"
    # Touching endpoint: [12:00, 14:00) starts exactly when A ends — allowed.
    ev_b = create_event(lot["id"], starts_at="2026-09-02T12:00:00Z",
                        ends_at="2026-09-02T14:00:00Z", min_tier="GOLD",
                        extra_discount_pct=5)
    assert ev_b["status"] == "SCHEDULED"


def test_event_window_one_minute_overlap_rejected(api, pricing_headers):
    """PRD §3.9: "must not overlap any `SCHEDULED` or `ACTIVE` event on the
    same lot under half-open semantics, where one event ending exactly when
    another begins is allowed; a true overlap is `ERR_EVENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/event_window_half_open_adjacency
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_priced_lot(vendor["id"], jur["id"])
    create_event(lot["id"], starts_at="2026-09-02T10:00:00Z",
                 ends_at="2026-09-02T12:00:00Z", min_tier="SILVER",
                 extra_discount_pct=10)
    # 11:59 start overlaps [10:00, 12:00)
    resp = api.create_early_access_event(
        lot["id"],
        {"starts_at": "2026-09-02T11:59:00Z", "ends_at": "2026-09-02T13:00:00Z",
         "min_tier": "BRONZE", "extra_discount_pct": 5},
        pricing_headers)
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)


def test_aisle_assignment_closed_interval_touch_conflict(api, floor_headers):
    """PRD §3.9: "Aisle windows on the same store and `aisle_code` follow
    closed-interval semantics: touching endpoints conflict. A new assignment
    that overlaps an existing `ACTIVE` assignment on the same aisle is
    rejected with `ERR_AISLE_WINDOW_CONFLICT` unless the caller passes
    `supersede` as true, in which case the prior assignment is superseded —
    its `valid_to` rewritten to one second before the new assignment's
    `valid_from` — and the new deal takes the aisle."

    Design: Difficulty/resource_temporal_overlap/aisle_assignment_closed_interval_touch_conflict
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_priced_lot(vendor["id"], jur["id"])
    version = store["version"]
    first = get_success_data(api.create_aisle_assignment(
        store["id"],
        create_aisle_assignment_payload(
            lot["id"], version, daily_unit_limit=4,
            valid_from="2026-09-01T00:00:00Z", valid_to="2026-09-10T00:00:00Z"),
        floor_headers))
    assert first["status"] == "ACTIVE"
    v2 = get_store(store["id"])["version"]
    # Closed-interval: valid_from == incumbent valid_to conflicts.
    resp = api.create_aisle_assignment(
        store["id"],
        create_aisle_assignment_payload(
            lot["id"], v2, daily_unit_limit=2,
            valid_from="2026-09-10T00:00:00Z", valid_to="2026-09-20T00:00:00Z"),
        floor_headers)
    validate_error(resp, ApiErrorId.ERR_AISLE_WINDOW_CONFLICT)


def test_aisle_assignment_supersede_ends_incumbent_one_second_earlier(
        api, floor_headers):
    """PRD §3.9: "A new assignment that overlaps an existing `ACTIVE`
    assignment on the same aisle is rejected with `ERR_AISLE_WINDOW_CONFLICT`
    unless the caller passes `supersede` as true, in which case the prior
    assignment is superseded — its `valid_to` rewritten to one second before
    the new assignment's `valid_from` — and the new deal takes the aisle."

    Design: Difficulty/resource_temporal_overlap/aisle_assignment_closed_interval_touch_conflict
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_priced_lot(vendor["id"], jur["id"])
    get_success_data(api.create_aisle_assignment(
        store["id"],
        create_aisle_assignment_payload(
            lot["id"], store["version"], daily_unit_limit=4,
            valid_from="2026-09-01T00:00:00Z", valid_to="2026-09-10T00:00:00Z"),
        floor_headers))
    v2 = get_store(store["id"])["version"]
    payload = create_aisle_assignment_payload(
        lot["id"], v2, daily_unit_limit=2,
        valid_from="2026-09-10T00:00:00Z", valid_to="2026-09-20T00:00:00Z")
    payload["supersede"] = True
    second = get_success_data(
        api.create_aisle_assignment(store["id"], payload, floor_headers))
    assert second["status"] == "ACTIVE"
    data, _ = validate_paginated(
        api.list_store_aisle_assignments(store["id"], ADMIN))
    by_id = {row["id"]: row for row in data}
    incumbent = next(r for r in data if r["id"] != second["id"])
    assert incumbent["status"] == "SUPERSEDED"
    # PRD §3.9 pins the instant ("one second before the new assignment's
    # valid_from"); §2.4's three-fractional-digit requirement applies to
    # system-managed created_at/updated_at only, so accept equivalent ISO
    # 8601 spellings of that instant.
    from datetime import datetime
    actual = datetime.fromisoformat(
        incumbent["valid_to"].replace("Z", "+00:00"))
    expected = datetime.fromisoformat("2026-09-09T23:59:59+00:00")
    assert actual == expected


def test_prohibited_jurisdiction_blocks_assignment(api):
    """PRD §3.5: "Under `COMPARISON_PROHIBITED`, `advertises_comparison` must
    be false; pricing a lot to advertise a comparison price in such a
    jurisdiction, or creating an aisle assignment at a store in such a
    jurisdiction for a lot whose `advertises_comparison` is true, is rejected
    with `ERR_COMPARISON_ADVERTISING_PROHIBITED`."

    Design: Corner/errors/error_prohibited_jurisdiction_blocks_assignment
    """
    jur_ca = create_default_jurisdiction()
    jur_nt = create_jurisdiction(jurisdiction_code="NT",
                                 comparison_rule="COMPARISON_PROHIBITED",
                                 max_advertised_discount_pct=0,
                                 member_discount_cap_pct=25)
    vendor = create_vendor()
    store_nt = create_store(jur_nt["id"], store_code="SN", name="Store NT")
    # The lot is priced under CA (comparison advertising allowed there).
    lot = create_priced_lot(vendor["id"], jur_ca["id"],
                            lot_overrides={"quantity_total": 10,
                                           "est_sellable_qty": 10,
                                           "total_cost_cents": 1000})
    resp = api.create_aisle_assignment(
        store_nt["id"],
        create_aisle_assignment_payload(lot["id"], store_nt["version"],
                                        daily_unit_limit=4),
        FLOOR)
    validate_error(resp, ApiErrorId.ERR_COMPARISON_ADVERTISING_PROHIBITED)
    data, _ = validate_paginated(
        api.list_store_aisle_assignments(store_nt["id"], ADMIN))
    assert data == []


def test_error_early_access_guest_rejected(api, guest_headers):
    """PRD §3.6: "Sixth, while any early-access event of the lot is `ACTIVE`
    at the current instant, a `member_id` is mandatory — member-only early
    access — and a guest attempt is rejected with
    `ERR_EARLY_ACCESS_MEMBER_ONLY`."

    Design: Corner/errors/error_early_access_guest_rejected
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    create_event(ctx["lot"]["id"], starts_at="2026-09-02T10:00:00Z",
                 ends_at="2026-09-02T12:00:00Z", min_tier="BRONZE",
                 extra_discount_pct=10)
    set_clock("2026-09-02T11:00:00Z")
    resp = api.create_purchase(ctx["store"]["id"],
                               {"lot_id": ctx["lot"]["id"], "qty": 1},
                               guest_headers)
    validate_error(resp, ApiErrorId.ERR_EARLY_ACCESS_MEMBER_ONLY, 403)


def test_error_member_tier_too_low_rejected(api):
    """PRD §3.6: "Seventh, during such an event the member's `tier` must rank
    at or above the event's `min_tier` (bronze below silver below gold), else
    `ERR_MEMBER_TIER_TOO_LOW`."

    Design: Corner/errors/error_member_tier_too_low_rejected
    """
    ctx = setup_sellable_store(
        lot_overrides={"pace_target_units_per_week": 1000})
    member = create_member(ctx["store"]["id"], member_code="M-BRONZE",
                           tier="BRONZE")
    create_event(ctx["lot"]["id"], starts_at="2026-09-02T10:00:00Z",
                 ends_at="2026-09-02T12:00:00Z", min_tier="GOLD",
                 extra_discount_pct=10)
    set_clock("2026-09-02T11:00:00Z")
    resp = api.create_purchase(
        ctx["store"]["id"],
        {"lot_id": ctx["lot"]["id"], "qty": 1, "member_id": member["id"]},
        make_club_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_TIER_TOO_LOW, 403)


def test_error_member_discount_cap_exceeded(api):
    """PRD §3.6: "Eighth, the combined member discount must respect the
    jurisdictional cap described below, else
    `ERR_MEMBER_DISCOUNT_CAP_EXCEEDED`."
    PRD §3.6: "The cap gate is applied before charging: if the combined
    percent exceeds the selling store's jurisdiction `member_discount_cap_pct`
    the sale is rejected — a combined percent exactly equal to the cap is
    allowed."

    Design: Corner/errors/error_member_discount_cap_exceeded
    """
    jur = create_jurisdiction(jurisdiction_code="CB",
                              comparison_rule="WAS_NOW_WINDOW", window_days=90,
                              required_offer_days=30,
                              max_advertised_discount_pct=70,
                              member_discount_cap_pct=25)
    ctx = setup_sellable_store(jurisdiction_id=jur["id"],
                               lot_overrides={"pace_target_units_per_week": 1000})
    member = create_member(ctx["store"]["id"], member_code="M-GOLD4",
                           tier="GOLD")
    create_event(ctx["lot"]["id"], starts_at="2026-09-02T10:00:00Z",
                 ends_at="2026-09-02T12:00:00Z", min_tier="BRONZE",
                 extra_discount_pct=15)
    create_event(ctx["lot"]["id"], starts_at="2026-09-02T13:00:00Z",
                 ends_at="2026-09-02T15:00:00Z", min_tier="BRONZE",
                 extra_discount_pct=10)
    # GOLD 15 + event extra 15 == 30 > cap 25: rejected.
    set_clock("2026-09-02T11:00:00Z")
    resp = api.create_purchase(
        ctx["store"]["id"],
        {"lot_id": ctx["lot"]["id"], "qty": 1, "member_id": member["id"]},
        make_club_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_DISCOUNT_CAP_EXCEEDED)
    # GOLD 15 + event extra 10 == 25 == cap: allowed (inclusive boundary).
    set_clock("2026-09-02T14:00:00Z")
    purchase = get_success_data(api.create_purchase(
        ctx["store"]["id"],
        {"lot_id": ctx["lot"]["id"], "qty": 1, "member_id": member["id"]},
        make_club_member_headers(member["id"])))
    assert purchase["discount_pct_applied"] == 25
    assert purchase["unit_price_cents"] == 3000
