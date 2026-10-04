"""Campaign lifecycle corners and chick-order state corners."""

from test_helpers import (
    activate_campaign,
    ApiErrorId,
    create_account,
    create_campaign_ready,
    create_open_store,
    create_season_campaign_payload,
    create_store,
    get_success_data,
    place_chick_order,
    set_clock,
    setup_fulfilled_order,
    setup_spring_store,
    TEST_USERS,
    ts_iso,
    validate_error,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FLOOR_NOW = "2026-09-10T09:00:00Z"


def test_campaign_full_happy_path_walks_draft_to_active(api):
    """PRD §3.1: "A `StoreManager` begins teardown, moving the campaign `DRAFT → TEARDOWN`"
    PRD §3.1: "A successful completion moves the campaign `TEARDOWN → VERIFY_PENDING` and stores the reported count."
    PRD §3.1: "A passed audit moves the campaign `VERIFY_PENDING → READY`."
    PRD §3.1: "A successful activation sets `activated_at` to the logical now and fires a five-hop cascade"
    PRD §2.6: "Every recomputation of posture increments the store's `version` and refreshes its `updated_at`."

    Design: Corner/state_machines/campaign_full_happy_path_draft_to_active
    """
    set_clock(FLOOR_NOW)
    store = create_store()
    camp = get_success_data(
        api.create_season_campaign(
            create_season_campaign_payload(
                store["id"], season="WINTER_HEATING", aisle_count=4,
                planogram_map="winter-v1",
            ),
            RA,
        )
    )
    assert camp["status"] == "DRAFT"

    s1 = validate_success(api.begin_teardown(camp["id"], MGR))
    assert s1["status"] == "TEARDOWN"

    s2 = validate_success(
        api.complete_reset(camp["id"], {"aisles_reset_count": 4}, MGR)
    )
    assert s2["status"] == "VERIFY_PENDING"
    assert s2["aisles_reset_count"] == 4

    s3 = validate_success(api.verify_campaign(camp["id"], {"audit_passed": True}, RA))
    assert s3["status"] == "READY"

    s4 = validate_success(
        api.activate_campaign(camp["id"], {"expected_store_version": 1}, RA)
    )
    assert s4["status"] == "ACTIVE"
    assert s4["activated_at"] == ts_iso(FLOOR_NOW)

    store_after = validate_success(api.get_store(store["id"], RA))
    assert store_after["posture"] == "WINTER_HEATING"
    assert store_after["active_campaign_id"] == camp["id"]
    assert store_after["version"] == 2


def test_campaign_verify_failure_cycles_back_to_teardown(api):
    """PRD §3.1: "A failed audit sends the campaign back `VERIFY_PENDING → TEARDOWN` and resets `aisles_reset_count` to 0, so the rework loop from teardown to verification may repeat as many times as needed."

    Design: Corner/state_machines/campaign_verify_failure_cycles_back_to_teardown
    """
    set_clock(FLOOR_NOW)
    store = create_store()
    camp = get_success_data(
        api.create_season_campaign(
            create_season_campaign_payload(
                store["id"], season="FALL_FEED", aisle_count=2,
                planogram_map="fall-v1",
            ),
            RA,
        )
    )
    get_success_data(api.begin_teardown(camp["id"], MGR))
    get_success_data(api.complete_reset(camp["id"], {"aisles_reset_count": 2}, MGR))

    failed = validate_success(
        api.verify_campaign(camp["id"], {"audit_passed": False}, RA)
    )
    assert failed["status"] == "TEARDOWN"
    assert failed["aisles_reset_count"] == 0

    # The loop repeats and terminates on a passing audit.
    second = validate_success(
        api.complete_reset(camp["id"], {"aisles_reset_count": 2}, MGR)
    )
    assert second["status"] == "VERIFY_PENDING"
    passed = validate_success(
        api.verify_campaign(camp["id"], {"audit_passed": True}, RA)
    )
    assert passed["status"] == "READY"


def test_verify_brooder_on_fulfilled_order_rejected(api):
    """PRD §3.4: "A `StoreAssociate` runs brooder verification on a `RESERVED` order (any other state fails with `ERR_ORDER_NOT_RESERVED`)"
    PRD §3.4: "`FULFILLED`, `CANCELLED`, and `EXPIRED` are terminal."

    Design: Corner/state_machines/chick_order_verify_brooder_on_fulfilled_order_rejected
    """
    ctx = setup_fulfilled_order()
    resp = api.verify_brooder(
        ctx["order"]["id"],
        {"heat_lamp_ok": True, "thermometer_ok": True, "bedding_ok": True},
        ASSOC,
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_RESERVED)

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "FULFILLED"


def test_chick_order_initial_state_and_system_fields(api):
    """PRD §3.4: "A successful reservation lands in `RESERVED`."
    PRD §3.5: "An opened claim moves `claim_status` from `NONE` to `CLAIMED`"
    PRD §2.4: "an integer `version` that starts at 1 and increments by exactly one on every mutation of that resource."

    Design: Corner/state_machines/chick_order_initial_state_and_system_fields
    """
    ctx = setup_spring_store()
    account = create_account()
    order = place_chick_order(
        ctx["store"], ctx["lot"], account, quantity=6,
        lot_version=ctx["lot_version"],
    )
    assert order["status"] == "RESERVED"
    assert order["version"] == 1
    assert order["claim_status"] == "NONE"
    assert order["claimed_mortality_count"] == 0
    assert order["approved_claim_count"] == 0
    assert order["refund_cents"] == 0
