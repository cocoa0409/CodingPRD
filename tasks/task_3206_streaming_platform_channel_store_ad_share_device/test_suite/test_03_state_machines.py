"""State-machine lifecycle tests: channel certification revision loop and
device-model parallel cert/compliance dimensions."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_channel,
    get_channel,
    submit_channel_version,
    create_manufacturer,
    create_device_model,
    create_certified_model,
    create_device_unit,
    create_activated_unit,
    create_viewer,
    create_os_update,
    set_clock,
    make_manufacturer_headers,
    make_viewer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_channel_certification_revision_loop():
    """PRD §3.2: "A failing decision (an `outcome` of `FAIL`) requires a
    non-empty `failure_codes` list, which is recorded on the version as its
    `review_status` becomes `FAILED`; the channel drops back to
    `CHANGES_REQUESTED`, opening the revision loop."

    Design: Difficulty/non_linear_state_machine/channel_certification_revision_cycle
    """
    publisher = create_publisher(legal_name="Loop Pub")
    channel = create_channel(publisher, name="Loop Channel", category="GAME",
                             content_rating="PG")

    v1 = submit_channel_version(channel["id"], publisher["id"],
                                version_label="1.0.0")
    get_success_data(api_client.review_channel_version(v1["id"], ADMIN))
    resp = api_client.decide_channel_version(
        v1["id"], {"outcome": "FAIL", "failure_codes": ["DEEP_LINK_MISSING"]},
        ADMIN,
    )
    failed_version = validate_success(resp)
    assert failed_version["review_status"] == "FAILED"
    assert failed_version["failure_codes"] == ["DEEP_LINK_MISSING"]

    after_fail = get_channel(channel["id"])
    assert after_fail["status"] == "CHANGES_REQUESTED", (
        f"channel must drop back to CHANGES_REQUESTED, got "
        f"{after_fail['status']}"
    )


def test_channel_certification_revision_loop_reaches_published():
    """PRD §3.2: "After a failed review the channel sits in
    `CHANGES_REQUESTED`, and resubmission from there likewise supersedes any
    lingering `SUBMITTED` version, creates a new one, and returns the channel
    to `SUBMITTED`."
    PRD §3.3: "A `CERTIFIED` channel is made commercially live when a
    `PlatformAdmin` publishes it, moving it to `PUBLISHED`."

    Design: Difficulty/non_linear_state_machine/channel_certification_revision_cycle
    """
    publisher = create_publisher(legal_name="Loop Pub 2")
    channel = create_channel(publisher, name="Loop Channel 2",
                             category="GAME", content_rating="PG")

    v1 = submit_channel_version(channel["id"], publisher["id"],
                                version_label="1.0.0")
    get_success_data(api_client.review_channel_version(v1["id"], ADMIN))
    get_success_data(api_client.decide_channel_version(
        v1["id"], {"outcome": "FAIL", "failure_codes": ["DEEP_LINK_MISSING"]},
        ADMIN,
    ))

    # Revision resubmission from CHANGES_REQUESTED.
    v2 = submit_channel_version(channel["id"], publisher["id"],
                                version_label="1.0.1")
    assert v2["review_status"] == "SUBMITTED"
    get_success_data(api_client.review_channel_version(v2["id"], ADMIN))
    passed = get_success_data(api_client.decide_channel_version(
        v2["id"], {"outcome": "PASS"}, ADMIN,
    ))
    assert passed["review_status"] == "PASSED"

    published = get_success_data(api_client.publish_channel(channel["id"], ADMIN))
    assert published["status"] == "PUBLISHED"
    assert published["active_version_id"] == v2["id"]


def test_device_model_compliance_overdue_cascades_license():
    """PRD §3.8: "A model in `COMPLIANT` or `GRACE` moves to `OVERDUE` when a
    mandatory `ROLLING` update's deadline has strictly passed — applying the
    update at exactly the deadline is compliant, the boundary is inclusive —
    and at least one `ACTIVATED` unit still lacks it. Entering `OVERDUE`
    cascades: the manufacturer's `license_status` becomes `SUSPENDED`,
    blocking new device-unit creation and lab bookings until cured."

    Design: Difficulty/non_linear_state_machine/device_model_parallel_cert_and_compliance_dimensions
    """
    manufacturer = create_manufacturer(legal_name="Par TV")
    model = create_certified_model(
        manufacturer, recovery_policy="MONETIZATION", model_code="P-1",
        bench_code="LAB_BENCH_1",
    )
    viewer = create_viewer(email="pv@x.com")
    unit = create_activated_unit(
        manufacturer, model["id"], viewer["id"], serial_number="PAR-1",
        hardware_cost_cents=15000, sale_price_cents=14999,
    )

    create_os_update(
        version_tag="14.1.0", mandatory=True,
        rollout_start="2026-09-02T00:00:00Z",
        compliance_deadline="2026-09-10T00:00:00Z",
    )
    set_clock("2026-09-11T00:00:00Z")

    updated_model = get_success_data(
        api_client.refresh_device_model_compliance(model["id"], ADMIN)
    )
    assert updated_model["cert_status"] == "CERTIFIED"
    assert updated_model["update_compliance"] == "OVERDUE"

    refreshed_mfr = get_success_data(
        api_client.get_manufacturer(manufacturer["id"], ADMIN)
    )
    assert refreshed_mfr["license_status"] == "SUSPENDED"


def test_device_model_overdue_blocks_new_unit_creation():
    """PRD §3.8: "Entering `OVERDUE` cascades: the manufacturer's
    `license_status` becomes `SUSPENDED`, blocking new device-unit creation
    and lab bookings until cured."
    PRD §2.8: "(3) the manufacturer's `license_status` is `LICENSED` — else
    `ERR_MANUFACTURER_NOT_LICENSED`"

    Design: Difficulty/non_linear_state_machine/device_model_parallel_cert_and_compliance_dimensions
    """
    manufacturer = create_manufacturer(legal_name="Par TV 2")
    model = create_certified_model(
        manufacturer, recovery_policy="MONETIZATION", model_code="P-2",
        bench_code="LAB_BENCH_1",
    )
    viewer = create_viewer(email="pv2@x.com")
    create_activated_unit(
        manufacturer, model["id"], viewer["id"], serial_number="PAR2-1",
        hardware_cost_cents=15000, sale_price_cents=14999,
    )
    create_os_update(
        version_tag="14.2.0", mandatory=True,
        rollout_start="2026-09-02T00:00:00Z",
        compliance_deadline="2026-09-10T00:00:00Z",
    )
    set_clock("2026-09-11T00:00:00Z")
    get_success_data(
        api_client.refresh_device_model_compliance(model["id"], ADMIN)
    )

    # The OVERDUE cascade suspends the manufacturer, and the model itself is
    # still OVERDUE. PRD §2.8 pins the referential-state sub-order
    # (ERR_UPDATE_OVERDUE before ERR_MANUFACTURER_NOT_LICENSED) for the
    # activation posture gate; for unit creation §3.8 names the block without
    # pinning which of the two errors surfaces, so either is faithful.
    resp = api_client.create_device_unit(
        {
            "device_model_id": model["id"],
            "serial_number": "PAR2-2",
            "hardware_cost_cents": 15000,
            "sale_price_cents": 14999,
        },
        make_manufacturer_headers(manufacturer["id"]),
    )
    assert resp.status_code == 409
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_MANUFACTURER_NOT_LICENSED,
        ApiErrorId.ERR_UPDATE_OVERDUE,
    ])
