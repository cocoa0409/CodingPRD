"""Quality audits, the suspension cascade, and license termination cascades."""
from test_helpers import (
    ADMIN,
    AUDITOR,
    LICENSING,
    PLANNER,
    ApiErrorId,
    assert_quality_audit,
    create_active_agreement,
    create_audit,
    create_brand,
    create_facility_with_line,
    create_variety,
    get_success_data,
    make_brand_manager_headers,
    reserve_run,
    set_clock,
    setup_household_with_brewer,
    transition_run,
    validate_error,
    validate_success,
)


def test_quality_audit_is_immutable_without_version(api):
    """PRD §2.5: "Two resources are immutable record types and carry only `id`
    and `created_at`: the quality audit and the consumption record. Both
    `updated_at` and `version` are **absent** from their representations — an
    audit or a consumption record is never modified after creation."

    Design: Corner/entities/quality_audit_is_immutable_without_version
    """
    brand = create_brand(kind="LICENSED", name="Audit Imm Co")
    agreement = create_active_agreement(brand["id"])

    resp = api.create_quality_audit(
        agreement["id"],
        {"audited_at": "2026-08-01T00:00:00Z", "cup_score": 92,
         "defect_rate_ppm": 40},
        AUDITOR)
    data = validate_success(resp, 201)
    assert_quality_audit(data)
    assert data["result"] == "PASS"
    assert data["agreement_id"] == agreement["id"]
    assert data["cup_score"] == 92
    assert data["defect_rate_ppm"] == 40


def test_future_audit_date_rejected(api):
    """PRD §3.2: "it must not be later than the logical clock, and a future
    audit date is a payload-shape failure, `ERR_INVALID_REQUEST`"

    Design: Corner/validations/future_audit_date_rejected
    """
    brand = create_brand(kind="LICENSED", name="Future Audit Co")
    agreement = create_active_agreement(brand["id"])

    resp = api.create_quality_audit(
        agreement["id"],
        {"audited_at": "2026-10-01T00:00:00Z", "cup_score": 90,
         "defect_rate_ppm": 50},
        AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_audit_fail_cascades_to_variety_block_and_run_cancel(api, planner_headers):
    """PRD §3.2: "A `FAIL` recorded against an `ACTIVE` agreement is the
    sharpest edge in the system: the agreement is immediately suspended,
    exactly as if a `LicensingManager` had driven `ACTIVE → SUSPENDED` by hand,
    and the full suspension cascade fires."
    PRD §3.2: "Every pod variety of the agreement's brand that is currently
    `ACTIVE` flips to `SUPPLY_BLOCKED`; every production run of those varieties
    still in `RESERVED` is `CANCELLED` and its window capacity on the filling
    line is released"

    Design: Difficulty/transitive_cascade/audit_fail_depth4_cascade
    """
    brand_l = create_brand(kind="LICENSED", name="Cascade Coffee")
    agreement = create_active_agreement(brand_l["id"], quality_min_cup_score=80)
    variety_l = create_variety(brand_l["id"], name="Cascade Dark",
                               roast_level="DARK")
    brand_p = create_brand(kind="PLATFORM_OWNED", name="Platform Select")
    variety_p = create_variety(brand_p["id"], name="Select Medium")
    _, line = create_facility_with_line(capacity_pods_per_day=100000,
                                        changeover_hours=0)
    run = reserve_run(line["id"], variety_l["id"], planned_units=50000)

    audit = create_audit(agreement["id"], audited_at="2026-09-01T00:00:00Z",
                         cup_score=70, defect_rate_ppm=50)
    assert audit["result"] == "FAIL"

    agreement_after = get_success_data(
        api.get_license_agreement(agreement["id"], LICENSING))
    assert agreement_after["status"] == "SUSPENDED"

    variety_l_after = get_success_data(api.get_pod_variety(
        variety_l["id"], make_brand_manager_headers(brand_l["id"])))
    assert variety_l_after["status"] == "SUPPLY_BLOCKED"
    variety_p_after = get_success_data(api.get_pod_variety(
        variety_p["id"], make_brand_manager_headers(brand_p["id"])))
    assert variety_p_after["status"] == "ACTIVE"

    run_after = get_success_data(api.get_production_run(run["id"], planner_headers))
    assert run_after["status"] == "CANCELLED"

    # Hop 4: the freed window accepts a new run for the unaffected variety.
    rebooked = validate_success(api.create_production_run(
        {"line_id": line["id"], "variety_id": variety_p["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-11T00:00:00Z", "planned_units": 50000},
        PLANNER), 201)
    assert rebooked["status"] == "RESERVED"


def test_audit_fail_spares_in_progress_runs(api, planner_headers):
    """PRD §3.2: "every production run of those varieties still in `RESERVED`
    is `CANCELLED` and its window capacity on the filling line is released;
    runs already `IN_PROGRESS` are deliberately **not** touched."

    Design: Difficulty/transitive_cascade/audit_fail_depth4_cascade
    """
    brand = create_brand(kind="LICENSED", name="Spared Coffee")
    agreement = create_active_agreement(brand["id"], quality_min_cup_score=80)
    variety_a = create_variety(brand["id"], name="Spared Dark", roast_level="DARK")
    variety_b = create_variety(brand["id"], name="Spared Medium")
    _, line = create_facility_with_line(capacity_pods_per_day=100000,
                                        changeover_hours=0)

    run_in_progress = reserve_run(
        line["id"], variety_a["id"], window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-11T00:00:00Z", planned_units=1000)
    run_reserved = reserve_run(
        line["id"], variety_b["id"], window_start="2026-09-12T00:00:00Z",
        window_end="2026-09-13T00:00:00Z", planned_units=1000)

    set_clock("2026-09-10T12:00:00Z")
    get_success_data(transition_run(run_in_progress["id"], "IN_PROGRESS"))

    audit = create_audit(agreement["id"], audited_at="2026-09-10T00:00:00Z",
                         cup_score=70, defect_rate_ppm=50)
    assert audit["result"] == "FAIL"

    ip_after = get_success_data(
        api.get_production_run(run_in_progress["id"], planner_headers))
    assert ip_after["status"] == "IN_PROGRESS"
    res_after = get_success_data(
        api.get_production_run(run_reserved["id"], planner_headers))
    assert res_after["status"] == "CANCELLED"


def test_license_terminate_cascades_to_delist_and_cancel(api, planner_headers,
                                                         licensing_headers):
    """PRD §3.1: "Terminating an `ACTIVE` agreement delists the brand's
    catalog: every variety of that brand in `ACTIVE`, `SUPPLY_BLOCKED`, or
    `PHASE_OUT` becomes `DELISTED`, and every `RESERVED` production run of
    those varieties is `CANCELLED`, releasing its window capacity."

    Design: Difficulty/transitive_cascade/license_terminate_depth3_cascade
    """
    brand = create_brand(kind="LICENSED", name="Termina Tea")
    agreement = create_active_agreement(brand["id"])
    variety = create_variety(brand["id"], name="Termina Black", roast_level="DARK")
    _, line = create_facility_with_line(capacity_pods_per_day=80000,
                                        changeover_hours=0)
    run = reserve_run(line["id"], variety["id"], planned_units=1000)

    terminated = get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "TERMINATED"}, LICENSING))
    assert terminated["status"] == "TERMINATED"

    variety_after = get_success_data(api.get_pod_variety(
        variety["id"], make_brand_manager_headers(brand["id"])))
    assert variety_after["status"] == "DELISTED"

    run_after = get_success_data(api.get_production_run(run["id"], planner_headers))
    assert run_after["status"] == "CANCELLED"


def test_terminated_variety_cannot_be_produced_or_brewed(api):
    """PRD §3.4: "The variety must currently be `ACTIVE`; any other status is
    `ERR_VARIETY_NOT_ACTIVE`."
    PRD §3.5: "The variety must exist and must not be `DELISTED` — a delisted
    pod can no longer be recorded, and the attempt is `ERR_VARIETY_NOT_ACTIVE`."

    Design: Difficulty/transitive_cascade/license_terminate_depth3_cascade
    """
    brand = create_brand(kind="LICENSED", name="Termina Tea 2")
    agreement = create_active_agreement(brand["id"])
    variety = create_variety(brand["id"], name="Termina Black 2", roast_level="DARK")
    _, line = create_facility_with_line()
    _, _, brewer = setup_household_with_brewer(size=2)

    get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "TERMINATED"}, LICENSING))

    run_resp = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-12T00:00:00Z",
         "window_end": "2026-09-13T00:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(run_resp, ApiErrorId.ERR_VARIETY_NOT_ACTIVE)

    brew_resp = api.record_brews(
        brewer["id"], {"brews": 3, "variety_id": variety["id"]}, ADMIN)
    validate_error(brew_resp, ApiErrorId.ERR_VARIETY_NOT_ACTIVE)
