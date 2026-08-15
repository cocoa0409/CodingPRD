"""Spare parts packages and maintenance plans: quoted-vs-delivered forecast
variants, site shift-change cascade, package lifecycle, and maintenance
window rolling (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_spare_parts_package,
    create_maintenance_plan_payload,
    create_spare_parts_package_payload,
    make_project_engineer_headers,
    make_service_manager_headers,
    setup_full_project,
    setup_project_in_sat,
    validate_error,
    validate_success,
)


def test_spare_parts_forecast_quoted_vs_delivered_diverge(api):
    """PRD §3.7: "The quoted variant, computed while the package stands
    `QUOTED`, uses the site's then-current `shift_windows_per_day` snapshot.
    The delivered variant, computed when the `ServiceManager` marks the
    package `DELIVERED`, re-derives the forecast using the shift count in
    force at delivery time — so identical package inputs can yield different
    forecasts if the site's shift pattern changed in between."

    Design: Difficulty/dual_variant_calc/spare_parts_forecast_quoted_vs_delivered_diverge
    """
    ctx = setup_full_project(
        org_overrides={"brand_specialization": "ABB"},
        site_overrides={"site_name": "Plant B", "shift_windows_per_day": 2},
        project_overrides={"project_code": "P-200"},
    )
    eng = ctx["users"]["PROJECT_ENGINEER"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    svc_hdrs = make_service_manager_headers(svc["id"])

    # 12 months at 2-shift baseline (shift_factor = 2/2 = 1) -> 12.0.
    pkg = validate_success(
        api.create_spare_parts_package(
            ctx["project"]["id"],
            create_spare_parts_package_payload(
                package_code="SPP-ABB-STD",
                list_price_cents=250000,
                recommended_coverage_months=12,
            ),
            svc_hdrs,
        ),
        201,
    )
    assert_spare_parts_package(pkg)
    quoted_forecast = pkg["forecast_consumption_months"]
    assert quoted_forecast == 12.0

    # Site moves to 3 shifts before delivery.
    validate_success(
        api.update_customer_site(
            ctx["site"]["id"],
            {"shift_windows_per_day": 3},
            make_project_engineer_headers(eng["id"]),
        )
    )
    validate_success(api.order_spare_parts_package(pkg["id"], svc_hdrs))
    delivered = validate_success(api.deliver_spare_parts_package(pkg["id"], svc_hdrs))
    # shift_factor = 3/2 = 1.5 -> 12 / 1.5 = 8.0.
    assert delivered["forecast_consumption_months"] == 8.0
    assert delivered["forecast_consumption_months"] != quoted_forecast


def test_site_shift_change_refreshes_package_forecast(api):
    """PRD §3.7: "Separately, whenever a `ProjectEngineer` updates a site's
    `shift_windows_per_day` (§3.1), the forecast is recomputed on every
    spare-parts package of every project under that site."

    Design: Difficulty/transitive_cascade/site_shift_change_refreshes_package_forecast
    """
    ctx = setup_full_project(
        org_overrides={"brand_specialization": "ABB"},
        site_overrides={"site_name": "Plant H", "shift_windows_per_day": 2},
        project_overrides={"project_code": "P-CAS2"},
    )
    eng = ctx["users"]["PROJECT_ENGINEER"]
    svc = ctx["users"]["SERVICE_MANAGER"]
    svc_hdrs = make_service_manager_headers(svc["id"])

    pkg = validate_success(
        api.create_spare_parts_package(
            ctx["project"]["id"],
            create_spare_parts_package_payload(
                package_code="SPP-2",
                list_price_cents=100000,
                recommended_coverage_months=12,
            ),
            svc_hdrs,
        ),
        201,
    )
    assert pkg["forecast_consumption_months"] == 12.0

    validate_success(
        api.update_customer_site(
            ctx["site"]["id"],
            {"shift_windows_per_day": 3},
            make_project_engineer_headers(eng["id"]),
        )
    )

    after = validate_success(api.get_spare_parts_package(pkg["id"], svc_hdrs))
    assert after["forecast_consumption_months"] == 8.0


def test_service_manager_exclusive_package_lifecycle(api):
    """PRD §3.7: "Marking a package `ORDERED` does not recompute anything."
    The package opens as `QUOTED`, then transitions `QUOTED` -> `ORDERED` ->
    `DELIVERED` under ServiceManager authority (PRD §4 endpoint table).

    Design: Corner/rbac/service_manager_exclusive_package_lifecycle
    """
    ctx = setup_full_project(
        org_overrides={"brand_specialization": "ABB"},
        site_overrides={"site_name": "S23"},
        project_overrides={"project_code": "P-SVC"},
    )
    svc = ctx["users"]["SERVICE_MANAGER"]
    svc_hdrs = make_service_manager_headers(svc["id"])

    pkg = validate_success(
        api.create_spare_parts_package(
            ctx["project"]["id"],
            create_spare_parts_package_payload(
                package_code="SPP-11",
                list_price_cents=75000,
                recommended_coverage_months=24,
            ),
            svc_hdrs,
        ),
        201,
    )
    assert pkg["package_status"] == "QUOTED"

    ordered = validate_success(api.order_spare_parts_package(pkg["id"], svc_hdrs))
    assert ordered["package_status"] == "ORDERED"

    delivered = validate_success(api.deliver_spare_parts_package(pkg["id"], svc_hdrs))
    assert delivered["package_status"] == "DELIVERED"


def test_maintenance_window_meter_vs_interval_aggregate_capacity(api):
    """PRD §3.7: "Activation — legal while the project stands in `SAT`,
    `TRAINING`, or `GUARANTEE` — requires the first-due reading to be at or
    beyond the current meter reading". PRD §3.7: "Activation moves the plan
    to `ACTIVE` and computes `hours_until_due`: the hours remaining until the
    next due service, obtained by adding whole maintenance intervals to the
    first-due reading — zero intervals if the first-due reading alone already
    reaches or passes the current meter, otherwise however many it takes —
    and subtracting the current meter reading, so the result is the smallest
    non-negative remainder of that form."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_meter_vs_interval_aggregate_capacity
    """
    ctx = setup_project_in_sat(
        site_overrides={"site_name": "Plant P"},
        project_overrides={"project_code": "P-TO2"},
    )
    svc = ctx["users"]["SERVICE_MANAGER"]
    svc_hdrs = make_service_manager_headers(svc["id"])

    # Edge: first_due_at_hours == current meter (0 >= 0) is accepted.
    edge = validate_success(
        api.create_maintenance_plan(
            ctx["project"]["id"],
            create_maintenance_plan_payload(
                interval_operating_hours=2000, first_due_at_hours=0
            ),
            svc_hdrs,
        ),
        201,
    )
    edge_activated = validate_success(
        api.activate_maintenance_plan(edge["id"], svc_hdrs)
    )
    assert edge_activated["plan_status"] == "ACTIVE"

    # Main plan: interval 2000, first_due 2000.
    mp = validate_success(
        api.create_maintenance_plan(
            ctx["project"]["id"],
            create_maintenance_plan_payload(
                interval_operating_hours=2000, first_due_at_hours=2000
            ),
            svc_hdrs,
        ),
        201,
    )
    validate_success(api.activate_maintenance_plan(mp["id"], svc_hdrs))

    # Meter reads 2100 -> next due at 4000 (2000 + 1*2000); hours_until_due
    # = 4000 - 2100 = 1900.
    after_2100 = validate_success(
        api.report_meter_reading(mp["id"], {"current_operating_hours": 2100}, svc_hdrs)
    )
    assert after_2100["hours_until_due"] == 1900

    # Meter reads 3999 -> hours_until_due = 4000 - 3999 = 1.
    after_3999 = validate_success(
        api.report_meter_reading(mp["id"], {"current_operating_hours": 3999}, svc_hdrs)
    )
    assert after_3999["hours_until_due"] == 1


def test_maintenance_window_invalid_first_due_before_meter(api):
    """PRD §3.7: "Activation — legal while the project stands in `SAT`,
    `TRAINING`, or `GUARANTEE` — requires the first-due reading to be at or
    beyond the current meter reading, and the interval to lie inside its
    permitted range; a violation is rejected with
    `ERR_MAINTENANCE_WINDOW_INVALID`."

    Note: This negative case is the complement boundary check of the same
    rule asserted by the difficulty instance (meter > first_due rejects).

    Design: Difficulty/resource_temporal_overlap/maintenance_window_meter_vs_interval_aggregate_capacity
    """
    ctx = setup_project_in_sat(
        site_overrides={"site_name": "Plant P2"},
        project_overrides={"project_code": "P-TO2B"},
    )
    svc = ctx["users"]["SERVICE_MANAGER"]
    svc_hdrs = make_service_manager_headers(svc["id"])

    # Create a plan and report a meter reading that exceeds first_due.
    mp = validate_success(
        api.create_maintenance_plan(
            ctx["project"]["id"],
            create_maintenance_plan_payload(
                interval_operating_hours=2000, first_due_at_hours=2000
            ),
            svc_hdrs,
        ),
        201,
    )
    # Plan is DRAFT; meter-reading recomputes hours_until_due but does not
    # activate. We need a separate plan whose first_due falls below the
    # current meter at activation time. Create a plan at first_due=0, then
    # report meter 500, then attempt to activate a fresh plan at first_due=0
    # against a project whose current meter is already advanced via the
    # first plan's meter reading... but plans carry independent meters per
    # row. Simpler: create a plan with first_due < 0 is not possible
    # (>= 0), so activate a plan with first_due=0 after its meter advanced.
    mp2 = validate_success(
        api.create_maintenance_plan(
            ctx["project"]["id"],
            create_maintenance_plan_payload(
                interval_operating_hours=2000, first_due_at_hours=0
            ),
            svc_hdrs,
        ),
        201,
    )
    # Report a meter reading on mp2 (still DRAFT) so its current > first_due.
    validate_success(
        api.report_meter_reading(mp2["id"], {"current_operating_hours": 500}, svc_hdrs)
    )
    # Now activation must fail because first_due (0) < current (500).
    resp = api.activate_maintenance_plan(mp2["id"], svc_hdrs)
    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_WINDOW_INVALID)
