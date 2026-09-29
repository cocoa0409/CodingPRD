"""Who may act, who must be a second pair of hands, and when a cascade becomes visible."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories
from test_helpers import fixtures as F
from test_helpers.test_users import (
    AUDITOR_USER_ID,
    CLERK_USER_ID,
    admin_headers,
    auditor_headers,
    clerk_headers,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_partner_headers,
    manager_2_headers,
    manager_headers,
)

RECORDER_USER_ID = "u-clerk-1"
MANAGER_ONE_USER_ID = "u-mgr-1"
MANAGER_TWO_USER_ID = "u-mgr-2"


def test_callers_are_refused_without_a_valid_role_header_and_outside_their_role(api):
    """A blank header is 401, an unknown role is 403, and each endpoint's own table is 403.

    PRD 1.1: "Every request to this API, without exception, must carry two headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that
    user is acting in. If either header is absent, or is present but an empty string,
    the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401 before any other
    consideration -- including before the request body is parsed and before any path
    identifier is looked up."

    PRD 1.1: "If `X-User-Role` holds any string other than those five, or holds one of
    the five but that role is not listed as authorised for the endpoint being called,
    the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403."

    PRD 1.1: "This role cannot price, sell or donate product: every markdown, sale,
    label, manifest and order-recommendation write returns `ERR_UNAUTHORIZED` for a
    `ComplianceAuditor`."

    PRD 2.11 places "Header presence -- `ERR_UNAUTHENTICATED` (401)" first and "Role
    recognition and endpoint authorisation -- `ERR_UNAUTHORIZED` (403)" second, above
    request shape and above every existence check, so none of these refusals depends on
    the body being well formed.

    The endpoint table in PRD 5 supplies the per-endpoint role lists this exercises:
    `POST /fresh/stores` is `StoreOperationsAdmin` alone; `POST
    /fresh/shrink-events/{shrinkEventId}/verify` is `DepartmentManager` alone; `POST
    /fresh/compliance-audits` is `ComplianceAuditor` alone; `POST
    /fresh/lots/{lotId}/markdowns` is `FreshClerk`, `DepartmentManager`; `POST
    /fresh/donation-pickups/{pickupId}/confirm` is `DonationPartner` alone; and `POST
    /fresh/lots` is `FreshClerk`, `DepartmentManager`, `StoreOperationsAdmin`.

    Design: Corner/rbac/callers_cannot_act_without_a_valid_role_header_or_outside_their_role
    """
    chain = F.build_meat_chain(
        api, store_overrides={"store_number": "0412", "dock_door_codes": ["D1"]}
    )
    partner = F.build_partner(
        api,
        service_region_code="MID-ATL",
        accepted_department_codes=["MEAT"],
        cold_chain_certified=True,
    )
    event = F.record_shrink(api, chain.lot["id"], 2, "DAMAGE", headers=clerk_headers())
    assert event["recorded_by_user_id"] == RECORDER_USER_ID
    pickup = F.book_pickup(
        api,
        chain.store["id"],
        partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
    )

    # 1 -- header presence, checked before the path identifier is even resolved.
    blank_user = api.get_lot(chain.lot["id"], headers_without_user_id("FreshClerk"))
    validate_error(blank_user, "ERR_UNAUTHENTICATED", expected_status=401)
    blank_role = api.get_lot(chain.lot["id"], headers_without_role(CLERK_USER_ID))
    validate_error(blank_role, "ERR_UNAUTHENTICATED", expected_status=401)

    # 2a -- a string outside the five declared roles is not recognised at all.
    unknown_role = api.get_lot(chain.lot["id"], make_headers("u-stocker-1", "ShelfStocker"))
    validate_error(unknown_role, "ERR_UNAUTHORIZED", expected_status=403)

    # 2b -- a recognised role acting off its own endpoint list, one refusal per role.
    clerk_store = api.create_store(
        factories.create_store_payload(store_number="0499", name="Fresh Market 0499"),
        clerk_headers(),
    )
    validate_error(clerk_store, "ERR_UNAUTHORIZED", expected_status=403)

    clerk_verify = api.verify_shrink_event(event["id"], clerk_headers())
    validate_error(clerk_verify, "ERR_UNAUTHORIZED", expected_status=403)
    A.assert_fields(F.reload_shrink(api, event["id"]), status="RECORDED")

    manager_audit = api.create_compliance_audit(
        factories.create_compliance_audit_payload(
            chain.department["id"],
            "2026-08-01T00:00:00.000Z",
            "2026-08-10T08:00:00.000Z",
        ),
        manager_headers(),
    )
    validate_error(manager_audit, "ERR_UNAUTHORIZED", expected_status=403)

    auditor_markdown = api.create_markdown(
        chain.lot["id"],
        {"expected_lot_version": chain.lot["version"], "pricing_variant": "LADDER_DAYS"},
        auditor_headers(),
    )
    validate_error(auditor_markdown, "ERR_UNAUTHORIZED", expected_status=403)
    lot_after = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot_after, version=1)
    A.assert_fresh_unpriced_lot(lot_after, 599)

    admin_confirm = api.confirm_donation_pickup(pickup["id"], admin_headers())
    validate_error(admin_confirm, "ERR_UNAUTHORIZED", expected_status=403)
    A.assert_fields(F.reload_pickup(api, pickup["id"]), logistics_status="SCHEDULED")

    partner_lot = api.create_lot(
        factories.create_lot_payload(chain.item["id"]),
        make_partner_headers(partner["id"]),
    )
    validate_error(partner_lot, "ERR_UNAUTHORIZED", expected_status=403)

    # Every refusal above wrote nothing at all.
    _stores, store_meta = validate_paginated(
        api.list_stores(admin_headers(), params={"limit": 10, "offset": 0})
    )
    assert store_meta["total_count"] == 1, (
        "the clerk's POST /fresh/stores was refused on the role check, so only the "
        f"seeded store 0412 exists, got total_count {store_meta['total_count']}"
    )
    _audits, audit_meta = validate_paginated(
        api.list_compliance_audits(
            auditor_headers(),
            params={"department_id": chain.department["id"], "limit": 10, "offset": 0},
        )
    )
    assert audit_meta["total_count"] == 0, (
        "the manager's audit request was refused before any row was written, got "
        f"total_count {audit_meta['total_count']}"
    )
    lot_rows, lot_meta = validate_paginated(
        api.list_lots(
            clerk_headers(),
            params={"item_id": chain.item["id"], "limit": 10, "offset": 0},
        )
    )
    assert lot_meta["total_count"] == 1, (
        "the DonationPartner's POST /fresh/lots was refused, so the item still owns "
        f"exactly one lot, got total_count {lot_meta['total_count']}"
    )
    assert lot_rows[0]["quantity_on_hand"] == 24, (
        "recording a shrink event moves no units and the refused verify moved none "
        f"either, got quantity_on_hand {lot_rows[0]['quantity_on_hand']}"
    )


def test_operations_shared_between_two_roles_accept_either_of_them(api):
    """Recording takes a clerk or a manager; disputing and withdrawing take a manager or an auditor.

    PRD 3.6: "A `FreshClerk` or a `DepartmentManager` records a shrink event against a
    lot by supplying the `lot_id`, a `cause_code`, the `quantity_units` written off, and
    optionally a `note` [...] A newly recorded event lands in `RECORDED` with `origin`
    `MANUAL` and `recorded_by_user_id` set to the acting `X-User-ID`."

    PRD 3.6: "**Verification is the call that actually moves units**, and it belongs
    exclusively to a `DepartmentManager`."

    PRD 3.6: "**Disputing** an event is available to a `DepartmentManager` or a
    `ComplianceAuditor`, with an optional `dispute_note` [...] Disputing a `VERIFIED`
    event whose `origin` is `MANUAL` is the compensating case: the event's
    `quantity_units` are subtracted from the lot's `units_shrunk` and added back to its
    `quantity_on_hand`, restoring the unit-conservation invariant exactly; if the lot had
    been `DEPLETED` it reopens, returning to `MARKED_DOWN` when its `current_rung_index`
    is 0 or greater and to `FRESH` when that index is -1 [...] `verified_by_user_id` and
    `verified_at` are cleared to null".

    PRD 3.5 step 1: "A shrink event is synthesised for the lot's entire remaining
    balance, with `cause_code` `SPOILAGE`, `origin` `WITHDRAWAL_AUTO`, `quantity_units`
    equal to the lot's `quantity_on_hand`, and `status` already `VERIFIED`. Its
    `recorded_by_user_id` is the acting `X-User-ID`, and its `verified_by_user_id` is the
    literal string `system`".

    PRD 5 lists `POST /fresh/lots` for `FreshClerk`, `DepartmentManager`,
    `StoreOperationsAdmin` and `POST /fresh/lots/{lotId}/withdraw` for
    `DepartmentManager`, `ComplianceAuditor`, so the manager may receive a lot the clerk
    normally receives and the auditor may pull it.

    Design: Corner/rbac/shared_operations_accept_either_declared_role
    """
    chain = F.build_meat_chain(api)
    lot_one = chain.lot
    # POST /fresh/lots is shared three ways; the manager exercises it here.
    lot_two = F.build_lot(
        api,
        chain.item["id"],
        headers=manager_headers(),
        production_date="2026-08-06",
        quantity_original=6,
    )
    A.assert_fields(lot_two, quantity_original=6, quantity_on_hand=6, status="FRESH")

    # Recording: the clerk arm and the manager arm both land in RECORDED / MANUAL.
    clerk_event = F.record_shrink(
        api, lot_one["id"], 2, "DAMAGE", headers=clerk_headers()
    )
    A.assert_fields(
        clerk_event,
        status="RECORDED",
        origin="MANUAL",
        recorded_by_user_id=RECORDER_USER_ID,
        cause_code="DAMAGE",
        quantity_units=2,
    )
    manager_event = F.record_shrink(
        api, lot_one["id"], 1, "SPOILAGE", headers=manager_headers()
    )
    A.assert_fields(
        manager_event,
        status="RECORDED",
        origin="MANUAL",
        recorded_by_user_id=MANAGER_ONE_USER_ID,
    )

    # Verification is the manager's alone, and it moves the clerk's two units.
    verified = F.verify_shrink(api, clerk_event["id"], headers=manager_headers())
    A.assert_fields(
        verified, status="VERIFIED", verified_by_user_id=MANAGER_ONE_USER_ID
    )
    after_verify = F.reload_lot(api, lot_one["id"])
    A.assert_fields(after_verify, quantity_on_hand=22, units_shrunk=2)
    A.assert_lot_units_conservation(after_verify)

    # Disputing is shared with the auditor, and it compensates exactly.
    disputed = F.dispute_shrink(
        api, clerk_event["id"], dispute_note="recount", headers=auditor_headers()
    )
    A.assert_fields(disputed, status="DISPUTED")
    A.assert_absent_or_none(disputed, "verified_by_user_id", "verified_at")
    restored = F.reload_lot(api, lot_one["id"])
    A.assert_fields(
        restored, quantity_on_hand=24, units_shrunk=0, status="FRESH"
    )
    A.assert_lot_units_conservation(restored)

    # Withdrawal is shared with the auditor too, and it verifies itself as `system`.
    withdrawn = F.withdraw_lot(
        api, lot_two["id"], reason_note="food safety pull", headers=auditor_headers()
    )
    A.assert_fields(withdrawn, status="WITHDRAWN", quantity_on_hand=0, units_shrunk=6)
    A.assert_lot_units_conservation(withdrawn)

    auto_rows, auto_meta = validate_paginated(
        api.list_shrink_events(
            auditor_headers(),
            params={
                "lot_id": lot_two["id"],
                "origin": "WITHDRAWAL_AUTO",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert auto_meta["total_count"] == 1, (
        "the withdrawal synthesises exactly one WITHDRAWAL_AUTO event, got "
        f"total_count {auto_meta['total_count']}"
    )
    A.assert_fields(
        auto_rows[0],
        quantity_units=6,
        status="VERIFIED",
        cause_code="SPOILAGE",
        origin="WITHDRAWAL_AUTO",
        verified_by_user_id="system",
        recorded_by_user_id=AUDITOR_USER_ID,
    )

    # Nothing here was ever priced, so the department carries no open giveback.  The
    # posture is deliberately left unasserted: the withdrawal moved real shrink cost
    # against a department with no cost of goods yet, so PRD 2.8 clause 3 legitimately
    # drops it out of COMPLIANT, and the design recipe asserts only the liability.
    department = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        department["markdown_liability_cents"], 0, "markdown_liability_cents"
    )


def test_a_recorder_may_neither_verify_his_own_shrink_nor_approve_his_own_markdown(api):
    """Both duties split on X-User-ID, not on role: the same manager is refused twice.

    PRD 1.1: "Segregation of duties is enforced in two places and is described in full
    where those workflows are specified: the user verifying a shrink event must differ
    from the user who recorded it (`ERR_SHRINK_SELF_VERIFICATION`, HTTP 403), and the
    manager nominated to approve an approval-gated or override markdown must differ from
    the requesting user (`ERR_MARKDOWN_SELF_APPROVAL`, HTTP 403)."

    PRD 3.6: "It requires the verifying `X-User-ID` to differ from the event's
    `recorded_by_user_id`, and a manager who recorded the shrink personally cannot verify
    it -- a second manager must, and self-verification is refused with
    `ERR_SHRINK_SELF_VERIFICATION` and HTTP 403."

    PRD 3.3: "Two situations demand a named approver: the effective rung's
    `requires_manager_approval` flag is true, or the caller supplied
    `override_price_cents`. In either case the request must come from a
    `DepartmentManager` **and** carry a non-null `approval_manager_user_id` [...] And
    because a manager must not sign off on their own deep discount,
    `approval_manager_user_id` must differ from the requesting `X-User-ID`; naming
    yourself is refused with `ERR_MARKDOWN_SELF_APPROVAL` and HTTP 403."

    PRD 3.2: "Days remaining [...] is the number of whole days between the logical clock
    and the lot's `sell_by_at`" -- at 2026-08-14T00:00:00.000Z against a sell-by of
    2026-08-15T00:00:00.000Z that is 1, and PRD 3.3's rung selection takes "the
    **deepest** such candidate", which is the approval-gated rung 1.

    PRD 3.3: "The cost floor [...] is 40 percent of `unit_cost_cents`, rounded half up to
    whole cents" -- 168 cents here, so the 50 percent rung price of 299.5 rounds half up
    to 300 without the floor biting, and `total_discount_pct` is 299/599 -> 49.92.

    PRD 2.7: `markdown_liability_cents` "is the sum, over every lot belonging to the
    department's items whose `status` is `FRESH`, `MARKED_DOWN` or `DONATION_PENDING`, of
    that lot's `quantity_on_hand` multiplied by the difference between its item's
    `base_retail_cents` and the lot's `current_price_cents`" -- 22 * 299 = 6578.

    Design: Corner/rbac/recorder_cannot_verify_his_own_shrink_nor_approve_his_own_markdown
    """
    chain = F.build_meat_chain(api)
    event = F.record_shrink(
        api, chain.lot["id"], 2, "DAMAGE", headers=manager_headers()
    )
    A.assert_fields(
        event, status="RECORDED", recorded_by_user_id=MANAGER_ONE_USER_ID
    )
    F.set_clock(api, "2026-08-14T00:00:00.000Z")

    self_verify = api.verify_shrink_event(event["id"], manager_headers())
    validate_error(self_verify, "ERR_SHRINK_SELF_VERIFICATION", expected_status=403)
    A.assert_fields(F.reload_shrink(api, event["id"]), status="RECORDED")
    A.assert_fields(F.reload_lot(api, chain.lot["id"]), quantity_on_hand=24, units_shrunk=0)

    # The same role in a different pair of hands is accepted.
    verified = F.verify_shrink(api, event["id"], headers=manager_2_headers())
    A.assert_fields(
        verified, status="VERIFIED", verified_by_user_id=MANAGER_TWO_USER_ID
    )
    A.assert_money_cents(verified["cost_value_cents"], 869, "cost_value_cents")
    after_verify = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(after_verify, quantity_on_hand=22, units_shrunk=2, status="FRESH")
    A.assert_lot_units_conservation(after_verify)

    lot_version = after_verify["version"]
    self_approval = api.create_markdown(
        chain.lot["id"],
        {
            "expected_lot_version": lot_version,
            "pricing_variant": "LADDER_DAYS",
            "approval_manager_user_id": MANAGER_ONE_USER_ID,
        },
        manager_headers(),
    )
    validate_error(self_approval, "ERR_MARKDOWN_SELF_APPROVAL", expected_status=403)
    unpriced = F.reload_lot(api, chain.lot["id"])
    A.assert_fresh_unpriced_lot(unpriced, 599)
    A.assert_fields(unpriced, version=lot_version)

    label = F.cut_markdown(
        api,
        chain.lot,
        pricing_variant="LADDER_DAYS",
        approval_manager_user_id=MANAGER_TWO_USER_ID,
        headers=manager_headers(),
        expected_lot_version=lot_version,
    )
    A.assert_label(
        label,
        "QUEUED",
        from_price_cents=599,
        to_price_cents=300,
        discount_pct=49.92,
        reason="LADDER_AUTO",
        barcode=A.expected_barcode("000111222333", 300),
    )
    A.assert_fields(
        label, rung_index=1, approved_by_user_id=MANAGER_TWO_USER_ID
    )
    A.assert_absent_or_none(label, "supersedes_label_id")

    priced = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(priced, 300, 1, 49.92, status="MARKED_DOWN")
    A.assert_fields(priced, version=lot_version + 1)

    department = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        department["markdown_liability_cents"], 6578, "markdown_liability_cents"
    )


def test_each_concurrency_rule_rejects_its_own_stale_parent_version(api):
    """A stale lot version is 412 ERR_STALE_LOT_VERSION; a stale item version is 412 ERR_STALE_ITEM_VERSION.

    PRD 2.3: "**Markdown creation on a lot** requires `expected_lot_version`, carrying
    the client's last observed `version` of the target `DateCodeLot`. If that value does
    not equal the lot's current `version`, the markdown is rejected with
    `ERR_STALE_LOT_VERSION` and HTTP 412."

    PRD 2.3: "**Order-recommendation creation** requires `expected_item_version`,
    carrying the client's last observed `version` of the target `Item`. If that value does
    not equal the item's current `version`, the create is rejected with
    `ERR_STALE_ITEM_VERSION` and HTTP 412."

    PRD 3.4: "The lot's `expected_sell_through_pct` and the department's
    `markdown_liability_cents` are recomputed, and the lot's `version` is incremented by
    one" -- so the pre-sale version 1 is stale by the time the markdown arrives.

    PRD 3.1: an item revision to `daily_forecast_units` is one that "bumps the item's
    `version` by one -- which, as 2.7 explains, invalidates any order-recommendation
    request still holding the item's previous version."

    PRD 3.7: "Creating it **increments the item's `version` by one**".

    PRD 3.7: "`recommended_order_units` is the item's `daily_forecast_units` multiplied by
    a three-day order horizon, dampened by the shrink rate -- that is, multiplied by one
    minus the shrink rate expressed as a fraction -- with `open_units` subtracted, the
    result rounded half up to a whole number, and then floored at 0" -- the PATCHed
    forecast of 9.00 gives 9.00 * 3 * (1 - 0) - 20 = 7, where the creation-time 4.00
    would have floored at 0.

    PRD 3.7: "`open_units` is the sum of `quantity_on_hand` across the item's lots whose
    `status` is `FRESH` or `MARKED_DOWN`, regardless of when those lots were created."

    The design recipe names the accepted label's price field `price_cents`; PRD 3.3 calls
    it `to_price_cents` ("the new `to_price_cents`"), so that is what is asserted here.

    Design: Corner/complexity_layers/each_concurrency_rule_rejects_its_own_stale_parent_version
    """
    chain = F.build_meat_chain(api, clock="2026-08-12T08:00:00.000Z")
    lot_v1 = chain.lot["version"]
    item_v1 = chain.item["version"]
    assert lot_v1 == 1 and item_v1 == 1

    F.post_sale(api, chain.lot["id"], 4, register_lane_code="L07")
    patched = validate_success(
        api.update_item(
            chain.item["id"],
            factories.update_item_payload(daily_forecast_units=9.00),
            manager_headers(),
        )
    )
    A.assert_fields(patched, version=2)
    A.assert_percent(patched["daily_forecast_units"], 9.00, "daily_forecast_units")

    stale_markdown = api.create_markdown(
        chain.lot["id"],
        {"expected_lot_version": lot_v1, "pricing_variant": "LADDER_DAYS"},
        clerk_headers(),
    )
    validate_error(stale_markdown, "ERR_STALE_LOT_VERSION", expected_status=412)
    lot_now = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot_now, version=2)
    A.assert_fresh_unpriced_lot(lot_now, 599)

    label = F.cut_markdown(
        api, lot_now, pricing_variant="LADDER_DAYS", expected_lot_version=lot_now["version"]
    )
    A.assert_label(
        label,
        "QUEUED",
        from_price_cents=599,
        to_price_cents=509,
        discount_pct=15.03,
        reason="LADDER_AUTO",
    )
    A.assert_fields(label, rung_index=0)
    priced = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(priced, 509, 0, 15.03, status="MARKED_DOWN")
    A.assert_fields(priced, version=3, quantity_on_hand=20)
    A.assert_money_cents(
        F.reload_department(api, chain.department["id"])["markdown_liability_cents"],
        1800,
        "markdown_liability_cents",
    )

    stale_recommendation = api.create_order_recommendation(
        factories.create_order_recommendation_payload(
            chain.item["id"], "2026-08-12", "2026-08-12", item_v1
        ),
        manager_headers(),
    )
    validate_error(stale_recommendation, "ERR_STALE_ITEM_VERSION", expected_status=412)
    item_now = F.reload_item(api, chain.item["id"])
    A.assert_fields(item_now, version=2)
    _rows, rec_meta = validate_paginated(
        api.list_order_recommendations(
            manager_headers(),
            params={"item_id": chain.item["id"], "limit": 10, "offset": 0},
        )
    )
    assert rec_meta["total_count"] == 0, (
        "the stale recommendation was refused on the version check, so no row was "
        f"written, got total_count {rec_meta['total_count']}"
    )

    recommendation = validate_success(
        api.create_order_recommendation(
            factories.create_order_recommendation_payload(
                chain.item["id"], "2026-08-12", "2026-08-12", item_now["version"]
            ),
            manager_headers(),
        ),
        expected_status=201,
    )
    A.assert_fields(
        recommendation, received_units=24, shrink_units=0, open_units=20,
        recommended_order_units=7,
    )
    A.assert_percent(recommendation["shrink_rate_pct"], 0.0, "shrink_rate_pct")

    final_item = F.reload_item(api, chain.item["id"])
    A.assert_fields(final_item, version=3)
    A.assert_percent(final_item["daily_forecast_units"], 9.00, "daily_forecast_units")


def test_the_shrink_budget_trigger_is_strict_and_its_lookback_window_is_closed(api):
    """The same 19.99 ratio sits COMPLIANT at 19.99, WATCH at 19.98, COMPLIANT at 20.00.

    PRD 2.8 clause 3: "Otherwise, if the department's `shrink_cost_ratio_pct` is strictly
    greater than its `shrink_budget_pct`, the posture is `WATCH`." Strictly greater is the
    whole point: equality is not a breach.

    PRD 2.7: "`shrink_cost_ratio_pct` is a rolling ratio over a trailing window described
    in the reporting narrative below, recomputed on every shrink verification, shrink
    dispute, withdrawal, donation completion and nightly operations run."

    PRD 3.8: "The department's own stored `shrink_cost_ratio_pct` uses the same per-line
    rounding as the report but a different window: a **trailing seven days**, running from
    seven days before the current logical clock through the logical clock itself, closed at
    both ends, over the department's lots whose `created_at` falls inside that window. It
    is the shrink-cost total divided by the sum of cost of goods, shrink cost and donation
    cost, multiplied by 100, rounded half up to two decimal places".

    PRD 3.8: "Its cost-of-goods line is `units_sold` multiplied by its item's
    `unit_cost_cents`, increased by the 3.5 percent waste-handling surcharge, rounded half
    up to whole cents. Its shrink-cost line is the same arithmetic applied to
    `units_shrunk` [...] **Every line is rounded before anything is added.**"

    So with lot ONE alone: cogs = round_half_up(8 * 420 * 1.035) = 3478 and shrink =
    round_half_up(2 * 420 * 1.035) = 869, giving 869 / 4347 = 19.99. With lot TWO added at
    the exact lower bound: (869 + 435) / (3478 + 3912 + 869 + 435) = 1304 / 8694 = 15.00.
    One millisecond later lot ONE has aged out and only lot TWO remains: 435 / 4347 =
    10.01.

    Two departures from the design recipe, both forced by the PRD. Its ladder carries a
    single rung, but PRD 3.1 requires `rungs` to be "an ordered array of between 2 and 6
    objects", so the standard two-rung MEAT ladder is used; nothing here prices a lot, so
    no assertion moves. And the recipe describes a `shrink_budget_pct` PATCH as
    deliberately not a recompute trigger while PRD 5 says "a `shrink_budget_pct` change
    recomputes the compliance posture" -- the recipe asserts nothing between a PATCH and
    the next declared trigger, and neither does this test.

    Design: Corner/complexity_layers/shrink_budget_trigger_is_strict_and_its_lookback_window_is_closed
    """
    chain = F.build_meat_chain(
        api,
        clock="2026-08-12T08:00:00.000Z",
        department_overrides={"shelf_life_days_default": 10, "shrink_budget_pct": 19.99},
    )
    lot_one = chain.lot
    A.assert_percent(chain.department["shrink_budget_pct"], 19.99, "shrink_budget_pct")
    F.post_sale(api, lot_one["id"], 8, register_lane_code="L07")

    def _ratio_after_verified_shrink(quantity_units, cause_code, lot_id):
        event = F.record_shrink(
            api, lot_id, quantity_units, cause_code, headers=clerk_headers()
        )
        F.verify_shrink(api, event["id"], headers=manager_headers())
        return event, F.reload_department(api, chain.department["id"])

    def _patch_budget(value):
        validate_success(
            api.update_department(
                chain.department["id"],
                factories.update_department_payload(shrink_budget_pct=value),
                admin_headers(),
            )
        )

    # Arm 1 -- ratio exactly equal to the budget: not strictly greater, so COMPLIANT.
    event_a, dept_equal = _ratio_after_verified_shrink(2, "SPOILAGE", lot_one["id"])
    A.assert_department_posture(dept_equal, "COMPLIANT", shrink_cost_ratio_pct=19.99)

    F.dispute_shrink(api, event_a["id"], dispute_note="recount", headers=manager_headers())
    A.assert_department_posture(
        F.reload_department(api, chain.department["id"]),
        "COMPLIANT",
        shrink_cost_ratio_pct=0.0,
    )

    # Arm 2 -- one hundredth of a point below the same ratio: WATCH.
    _patch_budget(19.98)
    event_b, dept_over = _ratio_after_verified_shrink(2, "SPOILAGE", lot_one["id"])
    A.assert_department_posture(dept_over, "WATCH", shrink_cost_ratio_pct=19.99)

    F.dispute_shrink(api, event_b["id"], dispute_note="recount", headers=manager_headers())
    A.assert_department_posture(
        F.reload_department(api, chain.department["id"]),
        "COMPLIANT",
        shrink_cost_ratio_pct=0.0,
    )

    # Arm 3 -- one hundredth of a point above the same ratio: COMPLIANT again.
    _patch_budget(20.00)
    _event_c, dept_under = _ratio_after_verified_shrink(2, "SPOILAGE", lot_one["id"])
    A.assert_department_posture(dept_under, "COMPLIANT", shrink_cost_ratio_pct=19.99)

    # Arm 4 -- the lookback window is closed on its lower bound.
    _patch_budget(12.00)
    F.set_clock(api, "2026-08-19T08:00:00.000Z")
    lot_two = F.build_lot(
        api, chain.item["id"], production_date="2026-08-19", quantity_original=12
    )
    F.post_sale(api, lot_two["id"], 9, register_lane_code="L07")
    event_d, dept_in_window = _ratio_after_verified_shrink(1, "DAMAGE", lot_two["id"])
    A.assert_department_posture(dept_in_window, "WATCH", shrink_cost_ratio_pct=15.0)

    # Arm 5 -- one millisecond later lot ONE has aged out of the window entirely.
    F.set_clock(api, "2026-08-19T08:00:00.001Z")
    F.dispute_shrink(api, event_d["id"], dispute_note="recount", headers=manager_headers())
    _event_e, dept_aged_out = _ratio_after_verified_shrink(1, "DAMAGE", lot_two["id"])
    A.assert_department_posture(dept_aged_out, "COMPLIANT", shrink_cost_ratio_pct=10.01)

    final_one = F.reload_lot(api, lot_one["id"])
    final_two = F.reload_lot(api, lot_two["id"])
    A.assert_fields(final_one, units_shrunk=2, units_sold=8)
    A.assert_fields(final_two, units_shrunk=1, units_sold=9)
    A.assert_lot_units_conservation(final_one)
    A.assert_lot_units_conservation(final_two)

    _rows, disputed_meta = validate_paginated(
        api.list_shrink_events(
            manager_headers(),
            params={
                "lot_id": lot_one["id"],
                "status": "DISPUTED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert disputed_meta["total_count"] == 2, (
        "two of lot ONE's three events were disputed back out, got total_count "
        f"{disputed_meta['total_count']}"
    )


def test_every_cascade_is_already_visible_in_the_response_that_caused_it(api):
    """One verify call drains the lot, and the next reads need no settling time.

    PRD 1: "Two properties of the design deserve emphasis before the detail begins" -- the
    second is that "money and units are conserved, not estimated".

    PRD 3.6: "From there the effects cascade four levels deep, and each level is caused by
    the one above it rather than by the verify call itself. First, the lot's `units_shrunk`
    grows by the event's `quantity_units` and its `quantity_on_hand` shrinks by the same
    amount. Second, **because** `quantity_on_hand` reached zero, the lot's status becomes
    `DEPLETED` [...] Third, **because** the lot is no longer sellable, every label on it in
    `QUEUED`, `PRINTED` or `APPLIED` transitions to `VOIDED` and the department's
    `markdown_liability_cents` is recomputed. Fourth, **because** the department's shrink
    cost has moved, its `shrink_cost_ratio_pct` is recomputed and its `compliance_status`
    becomes `WATCH` when that ratio ends up strictly above the department's
    `shrink_budget_pct`."

    PRD 3.6: "Verification sets `verified_by_user_id` and stamps `verified_at` with the
    current logical clock, recomputes `cost_value_cents`".

    PRD 3.4: "`revenue_cents` grows by the units sold multiplied by the lot's
    `current_price_cents` at call time. `markdown_giveback_cents` grows by the units sold
    multiplied by the difference between the item's `base_retail_cents` and the lot's
    `current_price_cents` at call time" -- 22 * 509 = 11198 and 22 * 90 = 1980.

    PRD 2.7: `markdown_liability_cents` is "the sum, over every lot belonging to the
    department's items whose `status` is `FRESH`, `MARKED_DOWN` or `DONATION_PENDING`, of
    that lot's `quantity_on_hand` multiplied by the difference between its item's
    `base_retail_cents` and the lot's `current_price_cents`. Lots that are `DONATED`,
    `WITHDRAWN` or `DEPLETED` are excluded entirely." So the depleted lot takes the
    exposure to 0.

    PRD 3.8: "`gross_margin_cents` is revenue less cost of goods less shrink cost less
    donation cost. `gross_margin_pct` is `gross_margin_cents` divided by `revenue_cents`,
    multiplied by 100, rounded half up to two decimal places [...]
    `shrink_cost_ratio_pct` is `shrink_cost_cents` divided by the sum of `cogs_cents`,
    `shrink_cost_cents` and `donation_cost_cents`, multiplied by 100, rounded half up to
    two decimal places" -- cogs = round_half_up(22 * 420 * 1.035) = 9563, shrink =
    round_half_up(2 * 420 * 1.035) = 869, so the margin is 11198 - 9563 - 869 = 766,
    6.84 percent of revenue, and the ratio is 869 / 10432 = 8.33.

    PRD 3.8: the margin report "is a pure read: it writes nothing, and in particular it
    does **not** rewrite the department's stored `shrink_cost_ratio_pct`" -- which is why
    the report's 8.33 must already match the department field read one call earlier.

    The design recipe's single-rung ladder is replaced by the standard two-rung MEAT
    ladder, because PRD 3.1 requires `rungs` to be "an ordered array of between 2 and 6
    objects"; with 2 days remaining the deepest candidate rung is still rung 0, so the
    509-cent price and every figure derived from it are unchanged.

    Design: Corner/consistency_model/every_cascade_is_already_visible_in_the_response_that_caused_it
    """
    chain = F.build_meat_chain(api, clock="2026-08-12T08:00:00.000Z")
    A.assert_percent(chain.department["shrink_budget_pct"], 2.50, "shrink_budget_pct")

    label = F.cut_markdown(api, chain.lot, pricing_variant="LADDER_DAYS")
    A.assert_label(
        label, "QUEUED", from_price_cents=599, to_price_cents=509, discount_pct=15.03
    )
    F.post_sale(api, chain.lot["id"], 22, register_lane_code="L07")
    event = F.record_shrink(api, chain.lot["id"], 2, "SPOILAGE", headers=clerk_headers())

    verified = F.verify_shrink(api, event["id"], headers=manager_headers())
    A.assert_fields(
        verified, status="VERIFIED", verified_by_user_id=MANAGER_ONE_USER_ID
    )
    A.assert_instant_equals(
        verified["verified_at"], "2026-08-12T08:00:00.000Z", "verified_at"
    )
    A.assert_money_cents(verified["cost_value_cents"], 869, "cost_value_cents")

    # No intervening write from here on: every read below sees the settled cascade.
    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(
        lot,
        status="DEPLETED",
        quantity_on_hand=0,
        units_sold=22,
        units_shrunk=2,
        revenue_cents=11198,
        markdown_giveback_cents=1980,
    )
    A.assert_lot_units_conservation(lot)

    A.assert_fields(F.reload_label(api, label["id"]), status="VOIDED")

    department = F.reload_department(api, chain.department["id"])
    A.assert_department_posture(
        department, "WATCH", shrink_cost_ratio_pct=8.33, markdown_liability_cents=0
    )

    report = validate_success(
        api.get_department_margin_report(
            chain.department["id"],
            manager_headers(),
            params=factories.window_params("2026-08-12", "2026-08-12"),
        )
    )
    A.assert_money_cents(report["revenue_cents"], 11198, "revenue_cents")
    A.assert_money_cents(report["markdown_giveback_cents"], 1980, "markdown_giveback_cents")
    A.assert_money_cents(report["cogs_cents"], 9563, "cogs_cents")
    A.assert_money_cents(report["shrink_cost_cents"], 869, "shrink_cost_cents")
    A.assert_money_cents(report["donation_cost_cents"], 0, "donation_cost_cents")
    A.assert_money_cents(report["gross_margin_cents"], 766, "gross_margin_cents")
    A.assert_percent(report["gross_margin_pct"], 6.84, "gross_margin_pct")
    A.assert_percent(report["shrink_cost_ratio_pct"], 8.33, "shrink_cost_ratio_pct")
    assert report["shrink_cost_ratio_pct"] == department["shrink_cost_ratio_pct"], (
        "the report and the department field are two reads of one settled value, so they "
        f"must agree exactly: report {report['shrink_cost_ratio_pct']} against department "
        f"{department['shrink_cost_ratio_pct']}"
    )

    _rows, verified_meta = validate_paginated(
        api.list_shrink_events(
            manager_headers(),
            params={
                "lot_id": chain.lot["id"],
                "status": "VERIFIED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert verified_meta["total_count"] == 1, (
        "the lot carries exactly one verified shrink event, got total_count "
        f"{verified_meta['total_count']}"
    )
