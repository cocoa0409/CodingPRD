"""Role-based access control denials and the CustomerPlanner ownership rule
(PRD §2.1, §4)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_plant, create_customer, create_agreement,
    create_active_agreement, publish_index_payload,
    make_customer_planner_headers, get_agreement, get_run,
    setup_scheduled_run, manager, scheduler, engineer, admin, api_client,
)


class TestRoleDenials:
    def test_customer_planner_cannot_amend_agreement(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint ... is rejected with `ERR_UNAUTHORIZED` (HTTP 403)"; the §4
        table gives `POST /supply-agreements/{id}/amend` to PlantManager only.

        Design: Corner/rbac/customer_planner_cannot_amend_agreement
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = create_active_agreement(plant["id"], customer["id"])
        planner = make_customer_planner_headers(customer["id"])
        reneg = validate_success(
            api.open_renegotiation(agreement["id"], planner))
        # Even the OWNING customer planner may not amend.
        resp = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": reneg["version"],
             "conversion_cost_cents_per_1000": 1600}, planner)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        current = get_agreement(agreement["id"])
        assert current["status"] == "RENEGOTIATING"
        assert current["conversion_cost_cents_per_1000"] == 1500

    def test_line_scheduler_cannot_publish_metal_price_index(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint ... is rejected with `ERR_UNAUTHORIZED` (HTTP 403)"; the §4
        table gives `POST /metal-price-indices` to PlatformAdmin only.

        Design: Corner/rbac/line_scheduler_cannot_publish_metal_price_index
        """
        set_clock()
        resp = api.publish_index(publish_index_payload("2026-08", 128.0),
                                 scheduler())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_customer_cannot_sign_another_customers_agreement(self, api):
        """PRD §2.1: "a `CustomerPlanner` may sign an agreement or reopen its
        renegotiation only when `X-User-ID` equals that agreement's
        `customer_id`".

        Design: Corner/rbac/customer_cannot_sign_another_customers_agreement
        """
        set_clock()
        plant = create_plant()
        cust_a = create_customer(name="A Co", home_region="US-SW")
        cust_b = create_customer(name="B Co", home_region="US-NE")
        agreement = create_agreement(plant["id"], cust_b["id"])
        resp = api.sign_agreement(agreement["id"],
                                  make_customer_planner_headers(cust_a["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        signed = validate_success(api.sign_agreement(
            agreement["id"], make_customer_planner_headers(cust_b["id"])))
        assert signed["status"] == "ACTIVE"

    def test_quality_engineer_cannot_start_production_run(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint ... is rejected with `ERR_UNAUTHORIZED` (HTTP 403)"; the §4
        table gives `POST /production-runs/{id}/start` to LineScheduler only.

        Design: Corner/rbac/quality_engineer_cannot_start_production_run
        """
        env = setup_scheduled_run()
        resp = api.start_run(env["run"]["id"], engineer())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_run(env["run"]["id"])["status"] == "SCHEDULED"
