"""Optimistic concurrency control on the three version-guarded writes."""
from test_helpers import (
    ApiErrorId,
    create_operation,
    create_pool,
    create_region,
    create_shelter_operation,
    create_shelter_site,
    inspect_site,
    setup_casework_scenario,
    validate_error,
    validate_success,
)


def test_stale_shelter_site_version_blocks_a_second_inspection(api):
    """PRD §2.12: "A `POST /api/v1/shelter-sites/{id}/inspections` request, which records a
    shelter site inspection, requires `expected_shelter_site_version`, carrying the inspector's
    last observed `version` of the target shelter site. A mismatch is rejected with
    `ERR_STALE_VERSION` at HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_shelter_site_version_on_second_inspection
    """
    region = create_region()
    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}
    site = create_shelter_site(region["id"])
    stale_version = site["version"]

    first = validate_success(api.record_inspection(
        site["id"],
        {"expected_shelter_site_version": stale_version,
         "inspected_at": "2026-09-02T12:00:00Z", "inspector_user_id": "rc_gl",
         "capacity_verified_beds": 8, "accessibility_verified": True,
         "functional_needs_verified": True, "deficiency_count": 0, "result": "PASS"},
        coord), 201)
    assert first["version"] != stale_version

    resp = api.record_inspection(
        site["id"],
        {"expected_shelter_site_version": stale_version,
         "inspected_at": "2026-09-03T12:00:00Z", "inspector_user_id": "rc_gl",
         "capacity_verified_beds": 6, "accessibility_verified": True,
         "functional_needs_verified": True, "deficiency_count": 0,
         "result": "CONDITIONAL_PASS"},
        coord)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_refreshed_shelter_site_version_lets_the_reinspection_through(api):
    """PRD §2.12: "Re-inspecting a site is legitimate and supersedes the earlier result, so the
    check exists solely to stop an inspector from acting on a site state they have not seen."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_shelter_site_version_on_second_inspection
    """
    region = create_region()
    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}
    site = create_shelter_site(region["id"])

    first = validate_success(api.record_inspection(
        site["id"],
        {"expected_shelter_site_version": site["version"],
         "inspected_at": "2026-09-02T12:00:00Z", "inspector_user_id": "rc_gl",
         "capacity_verified_beds": 8, "accessibility_verified": True,
         "functional_needs_verified": True, "deficiency_count": 0, "result": "PASS"},
        coord), 201)

    second = validate_success(api.record_inspection(
        site["id"],
        {"expected_shelter_site_version": first["version"],
         "inspected_at": "2026-09-03T12:00:00Z", "inspector_user_id": "rc_gl",
         "capacity_verified_beds": 6, "accessibility_verified": True,
         "functional_needs_verified": True, "deficiency_count": 0,
         "result": "CONDITIONAL_PASS"},
        coord), 201)
    assert second["inspection_result"] == "CONDITIONAL_PASS"
    assert second["capacity_verified_beds"] == 6


def test_stale_client_case_version_blocks_a_recovery_plan_write(api):
    """PRD §2.12: "A `POST /api/v1/client-cases/{id}/recovery-plans` request, which writes a new
    recovery plan revision, requires `expected_client_case_version` ... If the case's version has
    advanced since the client last read it, the write is rejected with `ERR_STALE_VERSION` at
    HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_client_case_version_on_second_recovery_plan
    """
    bundle = setup_casework_scenario()
    caseworker = bundle["caseworker_headers"]

    case = validate_success(api.get_client_case(bundle["case_id"], caseworker))
    stale_version = case["version"]

    first = validate_success(api.write_recovery_plan(
        bundle["case_id"],
        {"expected_client_case_version": stale_version,
         "recovery_plan_summary": "Initial recovery plan"},
        caseworker), 201)
    assert first["version"] != stale_version

    resp = api.write_recovery_plan(
        bundle["case_id"],
        {"expected_client_case_version": stale_version,
         "recovery_plan_summary": "Stale revision"},
        caseworker)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_refreshed_client_case_version_advances_the_revision(api):
    """PRD §2.12: "writing a second, later recovery plan revision is legitimate product behavior
    — a new revision supersedes the prior one — so a strictly later write succeeds provided the
    client observed the version it is superseding."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_client_case_version_on_second_recovery_plan
    """
    bundle = setup_casework_scenario()
    caseworker = bundle["caseworker_headers"]

    case = validate_success(api.get_client_case(bundle["case_id"], caseworker))
    first = validate_success(api.write_recovery_plan(
        bundle["case_id"],
        {"expected_client_case_version": case["version"],
         "recovery_plan_summary": "Initial recovery plan"},
        caseworker), 201)

    second = validate_success(api.write_recovery_plan(
        bundle["case_id"],
        {"expected_client_case_version": first["version"],
         "recovery_plan_summary": "Revised recovery plan"},
        caseworker), 201)
    assert second["recovery_plan_revision"] == 2


def test_stale_operation_version_blocks_a_cost_ledger_entry(api):
    """PRD §2.12: "A `POST /api/v1/disaster-relief-operations/{id}/cost-ledger-entries` request,
    which books a cost ledger entry, requires `expected_disaster_relief_operation_version` ...
    A mismatch is rejected with `ERR_STALE_VERSION` at HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_operation_version_on_cost_entry
    """
    region = create_region()
    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}
    finance = {"X-User-ID": "fo_1", "X-User-Role": "FinanceOfficer"}
    operation = create_operation(region["id"])
    stale_version = operation["version"]

    site = create_shelter_site(region["id"])
    inspect_site(site["id"], site["version"])
    create_shelter_operation(site["id"], operation["id"])
    pool = create_pool(fund_code="DR-9101-GEN", total_received_cents=100000)

    advanced = validate_success(api.advance_operation_phase(operation["id"], coord))
    assert advanced["phase"] == "ACTIVE"

    resp = api.create_cost_ledger_entry(
        operation["id"],
        {"expected_disaster_relief_operation_version": stale_version,
         "fund_pool_id": pool["id"], "cost_category": "LOGISTICS",
         "amount_cents": 5000, "entry_type": "CHARGE",
         "incurred_at": "2026-09-04T10:00:00Z"},
        finance)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_refreshed_operation_version_accepts_the_ledger_entry(api):
    """PRD §2.12: "Appending a further ledger entry is itself legitimate, so only a stale
    observation of the operation makes the write fail."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_operation_version_on_cost_entry
    """
    region = create_region()
    coord = {"X-User-ID": "rc_gl", "X-User-Role": "RegionalCoordinator"}
    finance = {"X-User-ID": "fo_1", "X-User-Role": "FinanceOfficer"}
    operation = create_operation(region["id"])

    site = create_shelter_site(region["id"])
    inspect_site(site["id"], site["version"])
    create_shelter_operation(site["id"], operation["id"])
    pool = create_pool(fund_code="DR-9101-GEN", total_received_cents=100000)

    advanced = validate_success(api.advance_operation_phase(operation["id"], coord))

    entry = validate_success(api.create_cost_ledger_entry(
        operation["id"],
        {"expected_disaster_relief_operation_version": advanced["version"],
         "fund_pool_id": pool["id"], "cost_category": "LOGISTICS",
         "amount_cents": 5000, "entry_type": "CHARGE",
         "incurred_at": "2026-09-04T10:00:00Z"},
        finance), 201)
    assert entry["amount_cents"] == 5000
