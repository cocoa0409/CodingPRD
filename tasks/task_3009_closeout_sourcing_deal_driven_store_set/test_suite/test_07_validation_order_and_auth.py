"""Validation ordering, safety gating, authentication and authorization."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_default_jurisdiction,
    create_lot,
    create_lot_payload,
    create_member,
    create_store,
    create_vendor,
    get_lot,
    make_club_member_headers,
    open_screening,
    pass_screening,
    setup_sellable_store,
    setup_on_sale_lot,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    complete_screening,
)

ADMIN = TEST_USERS["admin_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]


def test_purchase_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing `X-User-Role`, carrying a role value
    outside this set, or missing `X-User-ID` for any role other than
    `Anonymous` is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/purchase_missing_role_header_unauthenticated
    """
    resp = api.create_purchase(
        NON_EXISTENT_UUID,
        {"lot_id": NON_EXISTENT_UUID, "qty": 1},
        {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_existence_beats_state_on_purchase(api):
    """PRD §2.6: "Every request passes through a fixed, ordered validation
    cascade, and the order is observable: when several checks would fail, the
    earliest one wins." and "Existence checks come next ... with any failure
    reported as `ERR_NOT_FOUND`. Lifecycle-state checks
    (`ERR_INVALID_STATE`) follow".

    Design: Corner/validations/existence_beats_state_on_purchase
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_lot(vendor["id"], jur["id"], quantity_total=10,
                     total_cost_cents=1000, est_sellable_qty=10)
    # lot is SOURCED (not sellable); the member id does not exist at all
    resp = api.create_purchase(
        store["id"],
        {"lot_id": lot["id"], "qty": 1, "member_id": NON_EXISTENT_UUID},
        make_club_member_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_member_suspended_beats_signage_limit(api, admin_headers):
    """PRD §3.6: "Fifth, a supplied `member_id` must reference an `ACTIVE`
    member, else `ERR_MEMBER_SUSPENDED`." comes before "Ninth, the
    quantity-limited signage rule: the units already purchased for this store
    and lot on the current UTC day by this member — or by the shared guest
    bucket when no member is involved — plus the requested `qty` must not
    exceed the covering assignment's `daily_unit_limit`, else
    `ERR_SIGNAGE_LIMIT_EXCEEDED`."
    PRD §3.1: "A purchase that names a `SUSPENDED` member is rejected with
    `ERR_MEMBER_SUSPENDED`."

    Design: Corner/validations/member_suspended_beats_signage_limit
    """
    ctx = setup_sellable_store(daily_unit_limit=4,
                               lot_overrides={"pace_target_units_per_week": 1000})
    member = create_member(ctx["store"]["id"], member_code="M-GOLD",
                           tier="GOLD")
    get_success_data(api.update_member(member["id"], {"status": "SUSPENDED"},
                                       admin_headers))
    # qty 9 over the limit of 4 AND member suspended: member check wins
    resp = api.create_purchase(
        ctx["store"]["id"],
        {"lot_id": ctx["lot"]["id"], "qty": 9, "member_id": member["id"]},
        make_club_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)


def test_segregation_of_duties_enforced(api, officer_headers):
    """PRD §3.3: "Segregation of duties is enforced at the moment of opening:
    the screening officer's identity must differ from the lot's
    `created_by_user_id`, and a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_enforced
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    # The lot is created by operator "buyer-1"; the same operator id under the
    # SafetyOfficer role may not open the screening.
    lot = create_lot(vendor["id"], jur["id"], quantity_total=10,
                     total_cost_cents=1000, est_sellable_qty=10)
    resp = api.create_screening(lot["id"],
                                build_user_headers("buyer-1", "SafetyOfficer"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    data, _ = validate_paginated(api.list_screenings(lot["id"], ADMIN))
    assert data == []


def test_screening_grade_sum_mismatch_rejected(api, officer_headers):
    """PRD §3.3: "the three grade counts must reconcile exactly to the lot's
    `quantity_total`, or the completion is rejected with
    `ERR_GRADE_SUM_MISMATCH`."

    Design: Corner/validations/screening_grade_sum_mismatch_rejected
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_lot(vendor["id"], jur["id"])
    scr = open_screening(lot["id"], officer_headers)
    # 40 + 30 + 29 == 99 != quantity_total 100
    resp = api.complete_screening(
        lot["id"], scr["id"],
        {"recall_check": "PASS", "expiration_check": "PASS",
         "condition_verified": True,
         "qty_grade_a": 40, "qty_grade_b": 30, "qty_grade_c": 29},
        officer_headers)
    validate_error(resp, ApiErrorId.ERR_GRADE_SUM_MISMATCH)
    data, _ = validate_paginated(api.list_screenings(lot["id"], ADMIN))
    assert data[0]["status"] == "PENDING"
    assert get_lot(lot["id"])["commercial_status"] == "SCREENING"


def test_event_inverted_window_rejected(api, pricing_headers):
    """PRD §3.9: "The window must be strictly positive — an end at or before
    the start is `ERR_INVALID_EVENT_WINDOW`".

    Design: Corner/validations/event_inverted_window_rejected
    """
    from test_helpers import create_priced_lot

    jur = create_default_jurisdiction()
    vendor = create_vendor()
    lot = create_priced_lot(vendor["id"], jur["id"],
                            lot_overrides={"quantity_total": 10,
                                           "est_sellable_qty": 10})
    resp = api.create_early_access_event(
        lot["id"],
        {"starts_at": "2026-09-02T12:00:00Z", "ends_at": "2026-09-02T10:00:00Z",
         "min_tier": "BRONZE", "extra_discount_pct": 10},
        pricing_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_WINDOW)


def test_purchase_safety_beats_signage_constraint(api, guest_headers):
    """PRD §2.10: "This gate sits ahead of layout, membership, pricing, and
    fiscal checks in the validation order."
    PRD §3.6: "Second, the lot's `safety_status` must be `CLEARED`, else
    `ERR_LOT_SAFETY_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/purchase_safety_beats_signage_constraint
    """
    ctx = setup_sellable_store(daily_unit_limit=4)
    lot = ctx["lot"]
    # Post-market recall re-screen blocks the lot (and the cascade supersedes
    # the aisle assignment, so the layout gate would also fail).
    scr = open_screening(lot["id"], TEST_USERS["safety_officer_alt_headers"])
    complete_screening(lot["id"], scr["id"],
                       TEST_USERS["safety_officer_alt_headers"],
                       recall_check="FAIL", expiration_check="PASS",
                       condition_verified=True,
                       qty_grade_a=100, qty_grade_b=0, qty_grade_c=0)
    assert get_lot(lot["id"])["commercial_status"] == "BLOCKED"
    # qty 5 exceeds the signage limit of 4; safety must still win.
    resp = api.create_purchase(ctx["store"]["id"],
                               {"lot_id": lot["id"], "qty": 5}, guest_headers)
    validate_error(resp, ApiErrorId.ERR_LOT_SAFETY_BLOCKED)


def test_purchase_on_unscreened_lot_safety_blocked(api, guest_headers):
    """PRD §2.10: "A lot that is `BLOCKED`, or one that has never passed a
    screening, is rejected from all three with `ERR_LOT_SAFETY_BLOCKED`."
    PRD §3.6: "First, the lot must be in a sellable lifecycle state:
    `ON_SALE`, `DISPOSITION_REVIEW`, or `BLOCKED` all pass the state check
    ... and any other commercial status yields `ERR_INVALID_STATE`. Second,
    the lot's `safety_status` must be `CLEARED`, else
    `ERR_LOT_SAFETY_BLOCKED`."

    A never-screened SOURCED lot violates both gates; PRD §3.6's pinned
    cascade only guarantees that one of the two fires (state precedes safety
    there), so accept either error identifier.

    Design: Difficulty/priority_pair_validation_conflict/purchase_safety_beats_signage_constraint
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_lot(vendor["id"], jur["id"])  # never screened
    resp = api.create_purchase(store["id"], {"lot_id": lot["id"], "qty": 5},
                               guest_headers)
    validate_error_is_one_of(resp, [ApiErrorId.ERR_LOT_SAFETY_BLOCKED,
                                    ApiErrorId.ERR_INVALID_STATE])


def test_allocation_referential_beats_fiscal(api, admin_headers):
    """PRD §3.1: "A `SUSPENDED` store refuses new business: allocation
    proposals naming it, aisle assignments created on it, and purchases
    attempted at it are all rejected with `ERR_STORE_SUSPENDED`."
    PRD §3.8: "the requested quantity must not exceed the lot's unallocated
    `qty_pool` at proposal time, else `ERR_INSUFFICIENT_LOT_QUANTITY`".

    Design: Difficulty/priority_pair_validation_conflict/allocation_referential_beats_fiscal
    """
    from test_helpers import create_priced_lot

    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"], performance_tier="TIER_2", store_code="S2",
                         name="Store Two")
    lot = create_priced_lot(vendor["id"], jur["id"])
    get_success_data(api.update_store(store["id"], {"status": "SUSPENDED"},
                                      admin_headers))
    # qty 999 also exceeds the pool of 100; the store check wins.
    resp = api.create_allocation(lot["id"], {"store_id": store["id"],
                                             "qty_requested": 999}, ALLOCATOR)
    validate_error(resp, ApiErrorId.ERR_STORE_SUSPENDED)


def test_allocation_to_suspended_store_rejected_within_pool(api,
                                                            admin_headers):
    """PRD §3.1: "A `SUSPENDED` store refuses new business: allocation
    proposals naming it, aisle assignments created on it, and purchases
    attempted at it are all rejected with `ERR_STORE_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/allocation_referential_beats_fiscal
    """
    from test_helpers import create_priced_lot

    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_priced_lot(vendor["id"], jur["id"])
    get_success_data(api.update_store(store["id"], {"status": "SUSPENDED"},
                                      admin_headers))
    resp = api.create_allocation(lot["id"], {"store_id": store["id"],
                                             "qty_requested": 5}, ALLOCATOR)
    validate_error(resp, ApiErrorId.ERR_STORE_SUSPENDED)
