"""RBAC corners: exclusive operations, hierarchical override, anonymous
surface, and customer ownership identity."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accrue_points,
    activate_campaign,
    brooder_verify,
    create_account,
    create_campaign_ready,
    create_loyalty_account_payload,
    create_open_store,
    create_provisional_sale,
    create_store,
    create_weighted_sale_payload,
    make_customer_headers,
    place_chick_order,
    post_care_log,
    set_clock,
    setup_fulfilled_order,
    setup_reserved_order,
    setup_spring_store,
    validate_error,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]
ANON = TEST_USERS["anonymous_headers"]

FALL_NOW = "2026-09-20T10:00:00Z"
FLOOR_NOW = "2026-09-10T09:00:00Z"


def test_customer_cannot_post_care_logs_or_finalize_sales(api):
    """PRD §2.1: "When the role is syntactically valid but not permitted for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`StoreAssociate` covers the front-line writes (care logs, weighted sale creation and finalization, brooder verification, fulfillment, ledger posting, receipt-free lookup, staging and load-out, event check-in)"

    Design: Corner/rbac/customer_cannot_post_care_logs_or_finalize_sales
    """
    ctx = setup_reserved_order()
    cust = make_customer_headers(ctx["account"]["id"])

    care_log = api.create_care_log(ctx["lot"]["id"], {"entry_type": "FEEDING"}, cust)
    validate_error(care_log, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    sale = api.create_weighted_sale(
        create_weighted_sale_payload(
            ctx["store"]["id"], container_class="BAG_50", gross_weight_lbs=52,
        ),
        cust,
    )
    validate_error(sale, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_associate_cannot_activate_campaign_or_review_claims(api):
    """PRD §2.1: "`RegionalAdmin` can perform every `StoreManager` operation plus its own exclusive operations (driving the logical clock, creating stores, creating campaigns, verifying, activating, and cancelling campaigns); `StoreManager` can perform every `StoreAssociate` operation plus its own (staging bays, hatchery schedules, livestock lots, mortality-claim review, weighted-sale voids, account status changes, service events, and the teardown/complete-reset campaign steps)"
    PRD §2.1: "When the role is syntactically valid but not permitted for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/associate_cannot_activate_campaign_or_review_claims
    """
    ctx = setup_fulfilled_order()
    cust = make_customer_headers(ctx["account"]["id"])
    validate_success(
        api.create_mortality_claim(ctx["order"]["id"], {"mortality_count": 1}, cust),
        expected_status=201,
    )

    camp2 = create_campaign_ready(ctx["store"], "FALL_FEED")
    store_now = validate_success(api.get_store(ctx["store"]["id"], RA))

    activate_resp = api.activate_campaign(
        camp2["id"], {"expected_store_version": store_now["version"]}, ASSOC
    )
    validate_error(activate_resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    review_resp = api.review_mortality_claim(
        ctx["order"]["id"], {"decision": "APPROVE"}, ASSOC
    )
    validate_error(review_resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    camp2_after = validate_success(api.get_season_campaign(camp2["id"], RA))
    assert camp2_after["status"] == "READY"


def test_manager_inherits_associate_operations(api):
    """PRD §2.1: "`StoreManager` can perform every `StoreAssociate` operation plus its own (staging bays, hatchery schedules, livestock lots, mortality-claim review, weighted-sale voids, account status changes, service events, and the teardown/complete-reset campaign steps)"

    Design: Corner/rbac/manager_inherits_associate_operations
    """
    ctx = setup_reserved_order()

    log = validate_success(
        api.create_care_log(ctx["lot"]["id"], {"entry_type": "FEEDING"}, MGR),
        expected_status=201,
    )
    assert log["entry_type"] == "FEEDING"

    verified = validate_success(
        api.verify_brooder(
            ctx["order"]["id"],
            {"heat_lamp_ok": True, "thermometer_ok": True, "bedding_ok": True},
            MGR,
        )
    )
    assert verified["status"] == "BROODER_VERIFIED"

    fulfilled = validate_success(api.fulfill_chick_order(ctx["order"]["id"], MGR))
    assert fulfilled["status"] == "FULFILLED"


def test_anonymous_cannot_read_or_write_anything_but_register(api):
    """PRD §2.1: "`Anonymous` exists solely for public loyalty registration."
    PRD §2.1: "When the role is syntactically valid but not permitted for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/anonymous_cannot_read_or_write_anything_but_register
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")

    read_resp = api.get_store(store["id"], ANON)
    validate_error(read_resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    write_resp = api.create_weighted_sale(
        create_weighted_sale_payload(
            store["id"], container_class="BAG_50", gross_weight_lbs=52,
        ),
        ANON,
    )
    validate_error(write_resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_customer_cannot_act_on_another_members_order(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `LoyaltyAccount`; ownership checks on any resource that references a `LoyaltyAccount` compare the resource's `loyalty_account_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_IDENTITY` (HTTP 403)."

    Design: Corner/validations/customer_cannot_act_on_another_members_order
    """
    ctx = setup_reserved_order()
    other = create_account(full_name="Sid Vandal")

    resp = api.cancel_chick_order(
        ctx["order"]["id"], {"reason": "not mine but trying"},
        make_customer_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_IDENTITY, expected_status=403)

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "RESERVED"


def test_receipt_free_lookup_hit_and_miss(api):
    """PRD §3.7: "At the register, an associate finds the member by phone through the receipt-free lookup, which returns the account or fails with `ERR_PHONE_NOT_FOUND`."

    Design: Corner/endpoints/receipt_free_lookup_hit_and_miss
    """
    account = create_account(full_name="Rue Carter", phone="555-0200")

    hit = validate_success(
        api.lookup_loyalty_account({"phone": "555-0200"}, ASSOC)
    )
    assert hit["id"] == account["id"]

    miss = api.lookup_loyalty_account({"phone": "555-9999"}, ASSOC)
    validate_error(miss, ApiErrorId.ERR_PHONE_NOT_FOUND, expected_status=404)


def test_suspended_account_blocks_writes_but_not_lookup(api):
    """PRD §3.6: "any positive redemption requires a `loyalty_account_id` on the sale and that account in `ACTIVE` status — otherwise `ERR_ACCOUNT_SUSPENDED`"
    PRD §3.7: "A `StoreManager` manages account standing through a status-setting operation taking a `status` value: `ACTIVE` suspends to `SUSPENDED`, `SUSPENDED` reactivates to `ACTIVE`, and `ACTIVE` closes to `CLOSED`, which is terminal"
    PRD §3.7: "At the register, an associate finds the member by phone through the receipt-free lookup, which returns the account or fails with `ERR_PHONE_NOT_FOUND`."

    Design: Corner/errors/suspended_account_blocks_redemption_and_accrual_but_not_lookup
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account(full_name="Rue Carter", phone="555-0200")
    accrue_points(account, store, 500000, earn_context="OTHER")

    validate_success(
        api.set_loyalty_account_status(account["id"], {"status": "SUSPENDED"}, MGR)
    )

    ledger_resp = api.create_ledger_entry(
        account["id"], {"entry_type": "ADJUSTMENT", "points_delta": 100}, ASSOC
    )
    validate_error(ledger_resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

    sale = create_provisional_sale(
        store, gross_weight_lbs=100, loyalty_account_id=account["id"]
    )
    finalize_resp = api.finalize_weighted_sale(
        sale["id"], {"measured_tare_lbs": 20, "redeem_points": 100}, ASSOC
    )
    validate_error(finalize_resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

    lookup = validate_success(
        api.lookup_loyalty_account({"phone": "555-0200"}, ASSOC)
    )
    assert lookup["id"] == account["id"]
    assert lookup["status"] == "SUSPENDED"


def test_finalize_posts_redemption_and_accrual_atomically(api):
    """PRD §3.6: "Two ledger writes follow atomically when an account is attached: a `REDEMPTION` entry debiting the redeemed points (recorded on the sale as `points_redeemed`), and an `ACCRUAL` entry on the net-of-redemption amount — the `final_total_cents` minus the `points_redeemed` — with `earn_context` `FEED` for a feed sale or `FUEL` for a propane exchange, posted against the sale's store."

    Design: Corner/consistency_model/finalize_posts_redemption_and_accrual_atomically
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING", name="Winter Store")
    account = create_account()
    accrue_points(account, store, 100000, earn_context="OTHER")  # 1000 points

    sale = create_provisional_sale(
        store, gross_weight_lbs=100, loyalty_account_id=account["id"]
    )
    finalized = validate_success(
        api.finalize_weighted_sale(
            sale["id"], {"measured_tare_lbs": 20, "redeem_points": 700}, ASSOC
        )
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_total_cents"] == 2350  # 3050 - 700
    assert finalized["points_redeemed"] == 700

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    # PRD §3.6 pins the accrual base to the net-of-redemption amount, which the
    # same sentence defines as `final_total_cents` minus `points_redeemed` —
    # i.e. the redemption is already inside `final_total_cents` (price minus
    # redeemed points). The PRD-faithful accrual base is therefore
    # `final_total_cents` = 2350 -> floor(2350/100) = 23 points, and the
    # balance reflects all three writes: 1000 - 700 + 23 = 323.
    assert acct["points_balance"] == 323


def test_brooder_check_failure_blocks_verification(api):
    """PRD §3.4: "All three must be true; any false flag rejects the verification with `ERR_BROODER_CHECK_FAILED`."

    Design: Corner/errors/brooder_check_failure_blocks_verification
    """
    ctx = setup_reserved_order()

    resp = api.verify_brooder(
        ctx["order"]["id"],
        {"heat_lamp_ok": True, "thermometer_ok": False, "bedding_ok": True},
        ASSOC,
    )
    validate_error(resp, ApiErrorId.ERR_BROODER_CHECK_FAILED)

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "RESERVED"
    assert order["brooder_verified_at"] is None


def test_care_log_stale_blocks_fulfillment(api):
    """PRD §3.4: "the lot must show a fresh care log — at least one `CareLogEntry` created within the last 12 hours — failing which the call is rejected with `ERR_CARE_LOG_STALE`."

    Design: Corner/errors/care_log_stale_blocks_fulfillment
    """
    ctx = setup_reserved_order()
    brooder_verify(ctx["order"]["id"])
    post_care_log(ctx["lot"]["id"], "FEEDING")

    # 13 hours later: verification still fresh (< 72h), care log stale.
    set_clock("2026-03-10T23:00:00Z")
    resp = api.fulfill_chick_order(ctx["order"]["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_CARE_LOG_STALE)

    # A fresh care log (same clock) immediately unblocks the identical fulfill.
    post_care_log(ctx["lot"]["id"], "WATER")
    fulfilled = validate_success(api.fulfill_chick_order(ctx["order"]["id"], ASSOC))
    assert fulfilled["status"] == "FULFILLED"
