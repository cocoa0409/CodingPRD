"""Error-catalog tests: budget guard, flight-window gate, withdrawn updates,
and recovery-policy mismatch."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_published_channel,
    create_campaign,
    create_active_campaign,
    create_viewer,
    create_manufacturer,
    create_certified_model,
    create_activated_unit,
    create_os_update,
    set_clock,
    schedule_campaign,
    make_publisher_headers,
    make_viewer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_budget_exhausted_rejects_overspending_impression_batch():
    """PRD §3.5: "Before anything is applied, the guard checks that the
    current `spent_cents` plus this batch cost does not exceed `budget_cents`
    — spending to exactly the budget is allowed and completes the campaign;
    one cent over is rejected with `ERR_BUDGET_EXHAUSTED`."

    Design: Corner/errors/budget_exhausted_rejects_overspending_impression_batch
    """
    publisher = create_publisher(legal_name="Bud Pub")
    channel = create_published_channel(publisher)
    campaign = create_active_campaign(publisher, channel["id"],
                                      budget_cents=10000)
    validate_success(api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 8000, "cpm_cents": 1000},
        ADOPS,
    ))

    resp = api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 3000, "cpm_cents": 1000},
        ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXHAUSTED, 422)
    assert get_success_data(api_client.get_campaign(campaign["id"], ADMIN))[
        "spent_cents"] == 8000, "the failed batch must apply nothing"

    completed = validate_success(api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 2000, "cpm_cents": 1000},
        ADOPS,
    ))
    assert completed["spent_cents"] == 10000
    assert completed["status"] == "COMPLETED"


def test_campaign_start_outside_flight_rejected():
    """PRD §3.5: "`AdOps` starts a `SCHEDULED` campaign, moving it to
    `ACTIVE`, but only while the logical clock reads within the flight window
    — at or after `flight_start` and strictly before `flight_end` — and only
    while the channel remains `PUBLISHED`; starting outside the flight is
    rejected with `ERR_CAMPAIGN_OUTSIDE_FLIGHT`."

    Design: Corner/errors/campaign_start_outside_flight_rejected
    """
    publisher = create_publisher(legal_name="Fly Pub")
    channel = create_published_channel(publisher)
    campaign = create_campaign(
        publisher, channel["id"],
        flight_start="2026-09-10T00:00:00Z",
        flight_end="2026-09-20T00:00:00Z",
        budget_cents=5000,
    )
    schedule_campaign(campaign["id"], publisher["id"])

    # Default clock is 2026-09-01T00:00:00Z, before the flight.
    resp = api_client.start_campaign(campaign["id"], ADOPS)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_OUTSIDE_FLIGHT, 409)

    # At flight_start exactly, start succeeds (window is start-inclusive).
    set_clock("2026-09-10T00:00:00Z")
    started = validate_success(api_client.start_campaign(campaign["id"], ADOPS))
    assert started["status"] == "ACTIVE"


def test_withdrawn_update_cannot_be_applied():
    """PRD §3.10: "Applying an update that is not `ROLLING`, or one the unit
    already runs, is rejected with `ERR_UPDATE_NOT_APPLICABLE`."

    Design: Corner/errors/withdrawn_update_cannot_be_applied
    """
    manufacturer = create_manufacturer(legal_name="WD TV")
    model = create_certified_model(
        manufacturer, recovery_policy="MONETIZATION", model_code="WD-1",
        bench_code="B1",
    )
    viewer = create_viewer(email="wd@x.com")
    unit = create_activated_unit(
        manufacturer, model["id"], viewer["id"], serial_number="WD-1-001",
        hardware_cost_cents=9000, sale_price_cents=9000,
    )
    update = create_os_update(
        version_tag="16.0.0", mandatory=True,
        rollout_start="2026-09-02T00:00:00Z",
        compliance_deadline="2026-09-20T00:00:00Z",
    )
    get_success_data(api_client.withdraw_os_update(update["id"], ADMIN))

    resp = api_client.apply_os_update(
        unit["id"], {"os_update_id": update["id"]},
        make_viewer_headers(viewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UPDATE_NOT_APPLICABLE, 409)
    assert get_success_data(api_client.get_device_unit(unit["id"], ADMIN))[
        "os_version_tag"] == "BASE"


def test_recovery_policy_mismatch_rejected_both_directions():
    """PRD §3.10: "Recovery proceeds per the model's `recovery_policy`, and
    the two variants are mutually exclusive — recording ad revenue against a
    `STRAIGHT_LINE` model's unit, or accruing straight-line recovery against
    a `MONETIZATION` model's unit, is rejected with
    `ERR_RECOVERY_POLICY_MISMATCH`."

    Design: Corner/errors/recovery_policy_mismatch_rejected_both_directions
    """
    manufacturer = create_manufacturer(legal_name="Mix TV")
    msl = create_certified_model(
        manufacturer, recovery_policy="STRAIGHT_LINE", model_code="MX-SL",
        bench_code="B1",
    )
    mmn = create_certified_model(
        manufacturer, recovery_policy="MONETIZATION", model_code="MX-MN",
        bench_code="B2",
    )
    viewer = create_viewer(email="mx@x.com")
    usl = create_activated_unit(
        manufacturer, msl["id"], viewer["id"], serial_number="MX-SL-1",
        hardware_cost_cents=12000, sale_price_cents=10000,
    )
    umn = create_activated_unit(
        manufacturer, mmn["id"], viewer["id"], serial_number="MX-MN-1",
        hardware_cost_cents=12000, sale_price_cents=10000,
    )

    resp = api_client.accrue_straight_line(umn["id"], ADOPS)
    validate_error(resp, ApiErrorId.ERR_RECOVERY_POLICY_MISMATCH, 409)

    resp = api_client.record_device_ad_revenue(
        usl["id"], {"revenue_cents": 5000}, ADOPS,
    )
    validate_error(resp, ApiErrorId.ERR_RECOVERY_POLICY_MISMATCH, 409)

    assert get_success_data(api_client.get_device_unit(umn["id"], ADMIN))[
        "subsidy_recovered_cents"] == 0
    assert get_success_data(api_client.get_device_unit(usl["id"], ADMIN))[
        "subsidy_recovered_cents"] == 0
