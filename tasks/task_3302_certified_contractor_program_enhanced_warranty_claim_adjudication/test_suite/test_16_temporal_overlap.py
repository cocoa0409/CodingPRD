"""Difficulty queue A: resource/temporal overlap — territory windows and inspector capacity."""
from test_helpers import (
    ApiErrorId,
    assign_lead,
    create_distributor_payload,
    create_lead_assignment_payload,
    file_claim_with_photos,
    get_success_data,
    make_certified_contractor,
    make_distributor_headers,
    set_clock,
    setup_active_registration,
    validate_error,
    validate_success,
)


def test_lead_territory_touching_windows_allowed(api, program_admin_headers):
    """PRD §3.8: "The window must not overlap any existing `ASSIGNED` assignment of
    the same distributor and `territory_code`; overlap is judged on the half-open
    interval, so two windows that merely touch — one's `end_date` equal to the
    other's `start_date` — do not conflict, while any positive overlap is refused
    with `ERR_TERRITORY_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lead_territory_half_open_windows_touching_allowed_overlap_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist T", territory_codes=["T1"], lead_pool_total=3),
        program_admin_headers))
    assign_lead(dist["id"], contractor["id"], start_date="2026-10-01", end_date="2026-11-01")
    resp = api.create_lead_assignment(
        create_lead_assignment_payload(
            distributor_id=dist["id"], contractor_id=contractor["id"],
            start_date="2026-11-01", end_date="2026-12-01"),
        make_distributor_headers(dist["id"]))
    validate_success(resp, expected_status=201)


def test_lead_territory_interior_overlap_rejected(api, program_admin_headers):
    """PRD §3.8: "...overlap is judged on the half-open interval, so two windows that
    merely touch — one's `end_date` equal to the other's `start_date` — do not
    conflict, while any positive overlap is refused with `ERR_TERRITORY_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lead_territory_half_open_windows_touching_allowed_overlap_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist T", territory_codes=["T1"], lead_pool_total=3),
        program_admin_headers))
    assign_lead(dist["id"], contractor["id"], start_date="2026-10-01", end_date="2026-11-01")
    resp = api.create_lead_assignment(
        create_lead_assignment_payload(
            distributor_id=dist["id"], contractor_id=contractor["id"],
            start_date="2026-10-15", end_date="2026-10-20"),
        make_distributor_headers(dist["id"]))
    validate_error(resp, ApiErrorId.ERR_TERRITORY_OVERLAP)


def test_inspector_daily_capacity_third_ok(api, program_admin_headers, claimant_headers):
    """PRD §3.5: "An inspector may carry at most three `SCHEDULED` orders on a single
    `service_date`; scheduling a fourth order for the same `inspector_id` and
    `service_date` pair is refused with `ERR_INSPECTOR_CAPACITY_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/inspector_daily_capacity_third_ok_fourth_rejected
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=10000,
                                  file_at="2026-09-20", description="multi-inspection claim")
    claim = info["claim"]
    orders = []
    for _ in range(4):
        orders.append(get_success_data(api.request_inspection(claim["id"], program_admin_headers)))
    for order in orders[:3]:
        data = validate_success(api.schedule_inspection_order(
            order["id"], {"inspector_id": "INSP-9", "service_date": "2026-10-05"}, program_admin_headers))
        assert data["status"] == "SCHEDULED"


def test_inspector_daily_capacity_fourth_rejected(api, program_admin_headers, claimant_headers):
    """PRD §3.5: "An inspector may carry at most three `SCHEDULED` orders on a single
    `service_date`; scheduling a fourth order for the same `inspector_id` and
    `service_date` pair is refused with `ERR_INSPECTOR_CAPACITY_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/inspector_daily_capacity_third_ok_fourth_rejected
    """
    ctx = setup_active_registration(tier="BRONZE")
    reg = ctx["registration"]
    info = file_claim_with_photos(reg["id"], claim_labor_cost_cents=10000,
                                  file_at="2026-09-20", description="multi-inspection claim")
    claim = info["claim"]
    orders = []
    for _ in range(4):
        orders.append(get_success_data(api.request_inspection(claim["id"], program_admin_headers)))
    for order in orders[:3]:
        get_success_data(api.schedule_inspection_order(
            order["id"], {"inspector_id": "INSP-9", "service_date": "2026-10-05"}, program_admin_headers))
    resp = api.schedule_inspection_order(
        orders[3]["id"], {"inspector_id": "INSP-9", "service_date": "2026-10-05"}, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_CAPACITY_EXCEEDED)
