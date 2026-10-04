"""Cross-entity gate tests: subscription creation gated by channel publish
state; device activation gated by model certification and compliance."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_channel,
    certify_channel,
    publish_channel,
    create_viewer,
    create_manufacturer,
    create_certified_model,
    create_device_unit,
    create_activated_unit,
    create_os_update,
    set_clock,
    make_viewer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_subscription_rejected_before_channel_published():
    """PRD §3.6: "A `Viewer` subscribes to a channel through platform billing
    by supplying the `channel_id` and a positive `price_cents` period price;
    the channel must be `PUBLISHED` at that moment."
    PRD §2.8: "Cross-entity state gates: the channel is `PUBLISHED` for
    subscriptions and campaign schedule/start/resume, the campaign is
    `ACTIVE` for impression recording and placement booking, and
    version/channel review pairing holds — else `ERR_CHANNEL_NOT_PUBLISHED`
    or `ERR_CAMPAIGN_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/subscription_creation_gated_by_channel_publish_state
    """
    publisher = create_publisher(legal_name="Gate Pub")
    channel = create_channel(publisher, name="Gate Channel")
    certify_channel(channel["id"], publisher["id"])
    assert get_success_data(api_client.get_channel(channel["id"], ADMIN))[
        "status"] == "CERTIFIED"
    viewer = create_viewer(email="gv@x.com")

    resp = api_client.create_subscription(
        {"channel_id": channel["id"], "price_cents": 1000},
        make_viewer_headers(viewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHANNEL_NOT_PUBLISHED, 409)


def test_subscription_allowed_once_published_blocked_when_suspended():
    """PRD §3.6: "A `Viewer` subscribes to a channel through platform billing
    by supplying the `channel_id` and a positive `price_cents` period price;
    the channel must be `PUBLISHED` at that moment."

    Design: Difficulty/cross_entity_state_dependency/subscription_creation_gated_by_channel_publish_state
    """
    publisher = create_publisher(legal_name="Gate Pub 2")
    channel = create_channel(publisher, name="Gate Channel 2")
    certify_channel(channel["id"], publisher["id"])
    publish_channel(channel["id"])
    viewer = create_viewer(email="gv2@x.com")

    resp = api_client.create_subscription(
        {"channel_id": channel["id"], "price_cents": 1000},
        make_viewer_headers(viewer["id"]),
    )
    subscription = validate_success(resp, expected_status=201)
    assert subscription["billing_status"] == "ACTIVE"

    get_success_data(
        api_client.suspend_channel(channel["id"], {"reason": "OPS"}, ADMIN)
    )
    resp = api_client.create_subscription(
        {"channel_id": channel["id"], "price_cents": 1000},
        make_viewer_headers(viewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHANNEL_NOT_PUBLISHED, 409)
    # The existing subscription is untouched by the suspension.
    existing = get_success_data(
        api_client.get_subscription(subscription["id"], ADMIN)
    )
    assert existing["billing_status"] == "ACTIVE"


def test_device_activation_blocked_when_model_not_certified():
    """PRD §3.10: "Activation is a posture gate across three cross-entity
    dimensions, evaluated in the pinned order of §2.8: the model must be
    `CERTIFIED` (`ERR_MODEL_NOT_CERTIFIED`), the model's `update_compliance`
    must not be `OVERDUE` (`ERR_UPDATE_OVERDUE`), and the manufacturer's
    license must be `LICENSED` (`ERR_MANUFACTURER_NOT_LICENSED`)."

    Design: Difficulty/cross_entity_state_dependency/device_activation_gated_by_model_certification_and_compliance
    """
    manufacturer = create_manufacturer(legal_name="Gate TV NC")
    viewer = create_viewer(email="dvn@x.com")

    # Manufacture and sell a unit while the model is CERTIFIED, then
    # decertify the model: activation of the SOLD unit must fail the
    # ERR_MODEL_NOT_CERTIFIED gate.
    model = create_certified_model(
        manufacturer, recovery_policy="MONETIZATION", model_code="G-NC2",
        bench_code="LAB_BENCH_2",
    )
    unit = create_device_unit(
        manufacturer, model["id"], serial_number="G-NC2-1",
        hardware_cost_cents=9000, sale_price_cents=9000,
    )
    get_success_data(api_client.sell_device_unit(unit["id"], ADMIN))
    get_success_data(api_client.decertify_device_model(
        model["id"], {"reason": "post-sale recall"}, ADMIN,
    ))

    resp = api_client.activate_device_unit(
        unit["id"], make_viewer_headers(viewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MODEL_NOT_CERTIFIED, 409)


def test_device_activation_blocked_when_model_overdue():
    """PRD §3.10: "Activation is a posture gate across three cross-entity
    dimensions, evaluated in the pinned order of §2.8: the model must be
    `CERTIFIED` (`ERR_MODEL_NOT_CERTIFIED`), the model's `update_compliance`
    must not be `OVERDUE` (`ERR_UPDATE_OVERDUE`), and the manufacturer's
    license must be `LICENSED` (`ERR_MANUFACTURER_NOT_LICENSED`)."

    Design: Difficulty/cross_entity_state_dependency/device_activation_gated_by_model_certification_and_compliance
    """
    manufacturer = create_manufacturer(legal_name="Gate TV")
    model = create_certified_model(
        manufacturer, recovery_policy="MONETIZATION", model_code="G-OK",
        bench_code="LAB_BENCH_1",
    )
    viewer = create_viewer(email="dv@x.com")
    u1 = create_activated_unit(
        manufacturer, model["id"], viewer["id"], serial_number="G-1",
        hardware_cost_cents=9000, sale_price_cents=9000,
    )
    assert u1["status"] == "ACTIVATED"

    u2 = create_device_unit(
        manufacturer, model["id"], serial_number="G-2",
        hardware_cost_cents=9000, sale_price_cents=9000,
    )
    get_success_data(api_client.sell_device_unit(u2["id"], ADMIN))

    create_os_update(
        version_tag="15.0.0", mandatory=True,
        rollout_start="2026-09-02T00:00:00Z",
        compliance_deadline="2026-09-05T00:00:00Z",
    )
    set_clock("2026-09-06T00:00:00Z")
    updated_model = get_success_data(
        api_client.refresh_device_model_compliance(model["id"], ADMIN)
    )
    assert updated_model["update_compliance"] == "OVERDUE"

    resp = api_client.activate_device_unit(
        u2["id"], make_viewer_headers(viewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UPDATE_OVERDUE, 409)
    assert get_success_data(api_client.get_device_unit(u2["id"], ADMIN))[
        "status"] == "SOLD"
