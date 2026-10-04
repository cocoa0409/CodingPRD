"""Resource temporal overlap tests (PRD §3.3 half-open lab windows scoped by
lab_code, §3.8 aggregate day-bucket bay capacity).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    assert_certification_test_run,
    assert_engine_unit,
    create_campaign_work_order_payload,
    create_test_run_payload,
    get_unit,
    make_service_advisor_headers,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_testing,
    setup_full_environment,
    stamp_family_non_conforming,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# lab scheduling windows: strict pairwise half-open overlap per lab_code
# ---------------------------------------------------------------------------
def _create_run(api, engineer_headers, family_id, test_type, lab, start, end):
    return api.create_test_run(
        family_id,
        create_test_run_payload(
            test_type=test_type, lab_code=lab,
            scheduled_start=start, scheduled_end=end,
        ),
        engineer_headers,
    )


def test_adjacent_lab_windows_allowed_under_half_open_semantics(api, engineer_headers):
    """PRD §3.3: "Two runs in the same `lab_code` conflict when both occupy overlapping half-open windows: a new run conflicts with an existing run in `SCHEDULED` or `COMPLETED` status exactly when the new window starts before the existing window ends and the existing window starts before the new window ends."
    PRD §3.3: "Mere adjacency — the new run starting at the instant an existing run's window ends — does not conflict, and runs in `REJECTED` or `INVALIDATED` status never block anything."

    Run A occupies [10-05, 10-07) in LAB-9; run B starting at exactly 10-07 —
    the instant A's window ends — is legal.

    Design: Difficulty/resource_temporal_overlap/lab_window_half_open_adjacency
    """
    env = setup_family_testing()
    family_id = env["family"]["id"]

    run_a = validate_success(
        _create_run(api, engineer_headers, family_id, "FTP", "LAB-9",
                    "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z"),
        201,
    )
    run_b = validate_success(
        _create_run(api, engineer_headers, family_id, "RMC", "LAB-9",
                    "2026-10-07T00:00:00Z", "2026-10-09T00:00:00Z"),
        201,
    )
    assert_certification_test_run(run_a)
    assert_certification_test_run(run_b)
    assert run_a["status"] == "SCHEDULED" and run_b["status"] == "SCHEDULED"
    assert run_a["id"] != run_b["id"]


def test_interior_lab_overlap_rejected_and_other_lab_unaffected(api, engineer_headers):
    """PRD §3.3: "A genuine overlap is rejected with `ERR_LAB_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.3: "Two runs in the same `lab_code` conflict when both occupy overlapping half-open windows: a new run conflicts with an existing run in `SCHEDULED` or `COMPLETED` status exactly when the new window starts before the existing window ends and the existing window starts before the new window ends."

    Run C [10-06, 10-08) slices through both existing LAB-9 windows and is
    rejected; the identical window in LAB-8 is accepted because the conflict
    rule is scoped per lab_code.

    Design: Difficulty/resource_temporal_overlap/lab_window_half_open_adjacency
    """
    env = setup_family_testing()
    family_id = env["family"]["id"]
    _create_run(api, engineer_headers, family_id, "FTP", "LAB-9",
                "2026-10-05T00:00:00Z", "2026-10-07T00:00:00Z")
    _create_run(api, engineer_headers, family_id, "RMC", "LAB-9",
                "2026-10-07T00:00:00Z", "2026-10-09T00:00:00Z")

    overlap = _create_run(api, engineer_headers, family_id, "SET", "LAB-9",
                          "2026-10-06T00:00:00Z", "2026-10-08T00:00:00Z")
    validate_error(overlap, ApiErrorId.ERR_LAB_WINDOW_OVERLAP)

    run_d = validate_success(
        _create_run(api, engineer_headers, family_id, "SET", "LAB-8",
                    "2026-10-06T00:00:00Z", "2026-10-08T00:00:00Z"),
        201,
    )
    assert_certification_test_run(run_d)
    assert run_d["lab_code"] == "LAB-8"
    assert run_d["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# shop bay capacity: aggregate per-calendar-day bucket
# ---------------------------------------------------------------------------
def _campaign_with_three_units():
    """RECALL campaign CMP-5 IN_PROGRESS over units UN-911/UN-912/UN-913 at the
    canonical center (bay_capacity_per_day 2, LEVEL_2 endorsed technician)."""
    env = setup_full_environment()
    family, fleet, center, tech = (
        env["family"], env["fleet"], env["center"], env["technician"],
    )
    units = [
        setup_engine_unit(family["id"], fleet["id"], serial_number=serial)
        for serial in ("UN-911", "UN-912", "UN-913")
    ]
    stamp_family_non_conforming(
        family["id"], test_period_label="2027-MY-Q1", sample_size=10, passing_units=8,
    )
    set_logical_clock("2026-12-15T00:00:00Z")
    campaign = setup_campaign_in_progress(
        family["id"], campaign_code="CMP-5", campaign_type="RECALL",
        defect_summary="EGR valve sticking",
        remedy_description="Replace EGR valve", remedy_bay_days=2,
    )
    return env, units, campaign, center, tech


def test_work_orders_sharing_day_at_exact_capacity_allowed(api, admin_headers):
    """PRD §3.8: "A new work order occupies one bay on every calendar day from its `scheduled_start_day` up to but not including the day `bay_days` later. For each day in that span, the system counts the center's other work orders in `SCHEDULED` or `IN_BAY` status whose own spans cover that day; the create is valid exactly when, for every day of the new span, that occupied count plus one is no greater than the center's `bay_capacity_per_day`."

    WO-1 covers 01-04 and 01-05; WO-2 covers 01-05 and 01-06. Their spans share
    only 01-05, which reaches exactly the center's capacity of 2 — at the cap
    is legal, so both orders are created.

    Design: Difficulty/resource_temporal_overlap/bay_capacity_day_bucket_aggregate
    """
    env, units, campaign, center, tech = _campaign_with_three_units()

    wo_a = schedule_work_order(
        campaign["id"], units[0]["id"], center["id"], tech["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=2,
    )
    wo_b = schedule_work_order(
        campaign["id"], units[1]["id"], center["id"], tech["id"],
        scheduled_start_day="2027-01-05T00:00:00Z", bay_days=2,
    )
    assert wo_a["status"] == "SCHEDULED"
    assert wo_b["status"] == "SCHEDULED", (
        "the shared day 2027-01-05 reaches exactly capacity 2, which is allowed"
    )


def test_order_exceeding_day_bucket_capacity_rejected(api, admin_headers):
    """PRD §3.8: "Days on which the span would exceed capacity reject the create with `ERR_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD §3.8: "the create is valid exactly when, for every day of the new span, that occupied count plus one is no greater than the center's `bay_capacity_per_day`."

    A third order on 2027-01-05 — where WO-1 and WO-2 already fill both bays —
    would push the day bucket to 3 > 2 and is rejected, consuming nothing.

    Design: Difficulty/resource_temporal_overlap/bay_capacity_day_bucket_aggregate
    """
    env, units, campaign, center, tech = _campaign_with_three_units()
    wo_a = schedule_work_order(
        campaign["id"], units[0]["id"], center["id"], tech["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=2,
    )
    wo_b = schedule_work_order(
        campaign["id"], units[1]["id"], center["id"], tech["id"],
        scheduled_start_day="2027-01-05T00:00:00Z", bay_days=2,
    )

    payload = create_campaign_work_order_payload(
        engine_unit_id=units[2]["id"], service_center_id=center["id"],
        assigned_technician_id=tech["id"],
        scheduled_start_day="2027-01-05T00:00:00Z", bay_days=1,
    )
    resp = api.create_campaign_work_order(
        campaign["id"], payload, make_service_advisor_headers(center["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    unit_c_now = get_unit(units[2]["id"])
    assert_engine_unit(unit_c_now)
    assert unit_c_now["campaign_compliance"] == "CAMPAIGN_OPEN", (
        "the rejected order consumed nothing on the unit"
    )
    for wo in (wo_a, wo_b):
        wo_now = validate_success(api.get_campaign_work_order(wo["id"], admin_headers))
        assert wo_now["status"] == "SCHEDULED"
