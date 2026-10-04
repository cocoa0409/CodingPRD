"""Optimistic concurrency control and role-based access control
(queue B endpoints OCC + rbac; queue B cross_cutting_layers epoch checkpoint)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    setup_facility, setup_cxl_dough_type, setup_cafe, set_clock,
    create_order, place_and_submit_order,
    create_plan_for_date, lock_plan,
    setup_two_cafe_released_day,
    setup_billing_period,
    get_cafe, get_plan,
    make_cafe_manager_headers, build_user_headers,
    create_facility_payload, create_cafe_order_payload,
)

PLANNER = TEST_USERS["facility_planner_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]
DISPATCHER = TEST_USERS["route_dispatcher_headers"]


class TestOccCafeVersion:
    def test_stale_cafe_version_on_order_create_rejected(self, api):
        """PRD §2.9: "Creating a cafe order requires the `expected_cafe_version`
        field, carrying the `version` of the target `Cafe` as the client last
        observed it. If the cafe's version has since advanced — because a prior order
        was created, submitted, amended, or cancelled against it, a payment was
        posted, a plan close invoiced it, or a donation credit landed — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412), since the client's view of the
        cafe aggregate is stale."

        Design: Corner/endpoints/occ_stale_cafe_version_on_order_create
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        v0 = cafe["version"]
        set_clock("2026-09-09T10:00:00Z")

        mgr = make_cafe_manager_headers(cafe["id"])
        first = validate_success(api.create_cafe_order(
            create_cafe_order_payload(cafe_id=cafe["id"], dough_type_id=cxl["id"],
                                      production_date="2026-09-10", quantity=10,
                                      expected_cafe_version=v0),
            mgr), 201)
        assert get_cafe(cafe["id"])["version"] == v0 + 1

        # Second create carrying the pre-mutation token is stale.
        resp = api.create_cafe_order(
            create_cafe_order_payload(cafe_id=cafe["id"], dough_type_id=cxl["id"],
                                      production_date="2026-09-10", quantity=20,
                                      expected_cafe_version=v0),
            mgr)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_fresh_cafe_version_on_order_create_accepted(self, api):
        """PRD §2.9: "Creating a cafe order requires the `expected_cafe_version`
        field, carrying the `version` of the target `Cafe` as the client last
        observed it."

        Design: Corner/endpoints/occ_stale_cafe_version_on_order_create
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        set_clock("2026-09-09T10:00:00Z")
        mgr = make_cafe_manager_headers(cafe["id"])
        validate_success(api.create_cafe_order(
            create_cafe_order_payload(cafe_id=cafe["id"], dough_type_id=cxl["id"],
                                      production_date="2026-09-10", quantity=10,
                                      expected_cafe_version=cafe["version"]),
            mgr), 201)
        # Re-read and create again with the fresh token.
        cafe_now = get_cafe(cafe["id"])
        validate_success(api.create_cafe_order(
            create_cafe_order_payload(cafe_id=cafe["id"], dough_type_id=cxl["id"],
                                      production_date="2026-09-10", quantity=20,
                                      expected_cafe_version=cafe_now["version"]),
            mgr), 201)


class TestOccFacilityVersion:
    def test_stale_facility_version_on_plan_release_rejected(self, api):
        """PRD §2.9: "Releasing a production plan requires the
        `expected_facility_version` field, carrying the `version` of the owning
        `DoughFacility` as the client last observed it. A mismatch with the
        facility's current version — advanced by an overlapping plan's creation,
        lock, release, or close — is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/endpoints/occ_stale_facility_version_on_plan_release
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        place_and_submit_order(cafe, cxl, "2026-09-10", 10)

        plan = create_plan_for_date(facility, "2026-09-10")
        # The client holds the facility version observed right after plan creation.
        fac_after_create = get_success_data(api.get_facility(facility["id"], PLANNER))
        lock_plan(facility, plan)  # lock bumps DoughFacility.version

        resp = api.release_production_plan(
            facility["id"], plan["id"],
            {"expected_facility_version": fac_after_create["version"]},
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_fresh_facility_version_on_plan_release_accepted(self, api):
        """PRD §2.9: "Releasing a production plan requires the
        `expected_facility_version` field, carrying the `version` of the owning
        `DoughFacility` as the client last observed it."
        PRD §3.4: "Releasing moves the plan from `LOCKED` to `RELEASED` and requires
        the `expected_facility_version` OCC token per §2.9 — a mismatch is rejected
        with `ERR_STALE_VERSION`."

        Design: Corner/endpoints/occ_stale_facility_version_on_plan_release
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        place_and_submit_order(cafe, cxl, "2026-09-10", 10)
        plan = create_plan_for_date(facility, "2026-09-10")
        lock_plan(facility, plan)

        fac_now = get_success_data(api.get_facility(facility["id"], PLANNER))
        released = validate_success(api.release_production_plan(
            facility["id"], plan["id"],
            {"expected_facility_version": fac_now["version"]},
            PLANNER), 200)
        assert released["status"] == "RELEASED"


class TestRbac:
    def test_cafe_manager_cannot_create_facility(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint
        is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /dough-ops/facilities is authorized for FacilityPlanner only.

        Design: Corner/rbac/cafe_manager_cannot_create_facility
        """
        resp = api.create_facility(
            create_facility_payload(name="F1", effective_capacity_units=2000),
            make_cafe_manager_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_donation_coordinator_cannot_close_billing_period(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint
        is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /dough-ops/facilities/{facility_id}/billing-periods/{period_id}/close
        is authorized for FinanceAdmin only.

        Design: Corner/rbac/donation_coordinator_cannot_close_billing_period
        """
        facility = setup_facility()
        period = setup_billing_period(facility)
        resp = api.close_billing_period(
            facility["id"], period["id"],
            TEST_USERS["donation_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_cafe_manager_cannot_touch_other_cafes_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `CafeManager`, `X-User-ID` is the `id` of
        the acting `Cafe`; ownership checks on any resource that references a cafe
        compare the resource's cafe foreign key to `X-User-ID`, so a cafe manager may
        only create, submit, amend, or cancel orders, manage schedules and bake
        entries, for their own cafe."
        PRD §2.1: "A request whose role is not permitted for the target endpoint is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/cafe_manager_cannot_touch_other_cafes_order
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        c1 = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        c2 = setup_cafe(facility["id"], "C2", "COMPANY", 200000)
        order2 = place_and_submit_order(c2, cxl, "2026-09-10", 10)

        c2_now = get_cafe(c2["id"])
        resp = api.amend_cafe_order(
            order2["id"],
            {"quantity": 20, "expected_cafe_version": c2_now["version"]},
            make_cafe_manager_headers(c1["id"]))   # C1's manager touching C2's order
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


class TestEpochCheckpoint:
    def test_finance_admin_cannot_close_production_plan(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint
        is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /dough-ops/facilities/{facility_id}/production-plans/{plan_id}/close
        is authorized for FacilityPlanner only.

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_plan_close_advances_epoch
        """
        day = setup_two_cafe_released_day()
        resp = api.close_production_plan(day["facility"]["id"], day["plan"]["id"],
                                         FINANCE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        assert get_plan(day["plan"]["id"])["status"] == "RELEASED"
