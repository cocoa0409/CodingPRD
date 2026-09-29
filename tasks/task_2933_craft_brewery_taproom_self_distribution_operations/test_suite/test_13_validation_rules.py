"""Aggregate, cascading, temporal, cross-entity and conditional validation."""

from test_helpers import (
    ADMIN,
    APPT_ACTIVE,
    APPT_TERMINATION_REQUESTED,
    CELLAR,
    COMPLIANCE,
    DESTINATION_TAPROOM,
    ERR_EVENT_BARREL_CAP_EXCEEDED,
    ERR_FORBIDDEN_ROLE,
    ERR_GOOD_CAUSE_REQUIRED,
    ERR_GROWLER_LABEL_INCOMPLETE,
    ERR_LICENSE_NOT_YET_EFFECTIVE,
    ERR_TERRITORY_NOT_LICENSED,
    ERR_WHOLESALER_APPOINTMENT_REQUIRED,
    KEG_SIZE_HALF_BBL,
    LICENSE_ACTIVE,
    LICENSE_SELF_DISTRIBUTION,
    LICENSE_WHOLESALER_ONLY,
    ORDER_CHANNEL_WHOLESALER,
    ORDER_SUBMITTED,
    PACKAGE_HALF_BBL_KEG,
    PERMIT_DRAFT,
    PERMIT_FARMERS_MARKET,
    PERMIT_FESTIVAL,
    PERMIT_OFF_SITE_TASTING,
    PERMIT_SUBMITTED,
    SCOPE_ALL_BRANDS,
    TAPROOM,
    TERMINATION_REQUEST,
    assert_cents,
    assert_instant_equals,
    growler_payload,
    order_payload,
    termination_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_active_appointment,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_exempt_beer,
    create_license,
    create_tank,
    create_tapped_keg,
    draft_permit,
    submit_permit,
)
from test_helpers.test_users import USER_TAPROOM_2

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class TestAggregateAnnualEventCeiling:
    def test_three_modest_permits_collectively_break_the_annual_ceiling(self, api):
        """12.00 plus 12.00 plus 2.00 is 26.00 barrels, so the third submission fails.

        PRD §3.9: "Submission also enforces an **aggregate annual ceiling per state**
        that no single permit can breach on its own: the sum of `requested_bbl` over
        every event permit in the same `venue_state_code` whose `state` is `SUBMITTED`
        or `APPROVED`, **plus** this permit's own `requested_bbl`, must be at most
        25.00 barrels."

        Design: Corner/validations/three_small_event_permits_collectively_breach_the_annual_offsite_barrel_cap
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(api, name="Ridgeline IPA")
        create_license(
            api,
            "OR",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        first = draft_permit(
            api,
            beer["id"],
            venue_state_code="OR",
            requested_bbl=12.00,
            event_start_utc="2026-09-10T12:00:00Z",
            event_end_utc="2026-09-10T18:00:00Z",
            permit_type=PERMIT_FESTIVAL,
            event_name="Riverfront Fest",
        )
        submit_permit(api, first["id"])
        second = draft_permit(
            api,
            beer["id"],
            venue_state_code="OR",
            requested_bbl=12.00,
            event_start_utc="2026-10-10T12:00:00Z",
            event_end_utc="2026-10-10T18:00:00Z",
            permit_type=PERMIT_OFF_SITE_TASTING,
            event_name="Harvest Tasting",
        )
        submit_permit(api, second["id"])
        third = draft_permit(
            api,
            beer["id"],
            venue_state_code="OR",
            requested_bbl=2.00,
            event_start_utc="2026-11-10T12:00:00Z",
            event_end_utc="2026-11-10T18:00:00Z",
            permit_type=PERMIT_FARMERS_MARKET,
            event_name="Winter Market",
        )

        validate_error(
            api.submit_event_permit(third["id"], COMPLIANCE),
            ERR_EVENT_BARREL_CAP_EXCEEDED,
            422,
        )

        blocked = validate_success(api.get_event_permit(third["id"], COMPLIANCE))
        assert blocked["state"] == PERMIT_DRAFT
        assert blocked["submission_count"] == 0
        for permit in (first, second):
            assert (
                validate_success(api.get_event_permit(permit["id"], COMPLIANCE))["state"]
                == PERMIT_SUBMITTED
            )


class TestCascadingSealedContainerChecks:
    def test_a_passing_reading_exposes_the_label_gap_underneath_it(self, api):
        """With sanitation in band the request falls through to the label check.

        PRD §3.5: "The label check runs strictly **after** the sanitation check:
        `label_fields` must be present and must carry non-blank values for every one
        of `brand_name`, `abv_statement`, `net_contents`, `health_warning` and
        `fill_date`, and a missing or blank member is refused with
        `ERR_GROWLER_LABEL_INCOMPLETE`."

        Design: Corner/validations/growler_label_gap_is_reported_once_the_sanitation_reading_is_in_band
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8)
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_conditioning_batch(
            api,
            beer["id"],
            tank["id"],
            actual_yield_bbl=16.000,
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code="R-TAP-1",
        )
        keg = create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        payload = growler_payload(
            keg["id"],
            USER_TAPROOM_2,
            sanitizer_ppm=200,
            contact_time_seconds=90,
            price_cents=2000,
        )
        payload["label_fields"] = {
            "brand_name": "Ridgeline IPA",
            "abv_statement": "6.8% ALC/VOL",
            "net_contents": "64 FL OZ",
            "health_warning": "GOVERNMENT WARNING: ACCORDING TO THE SURGEON GENERAL",
        }

        validate_error(
            api.create_taproom_pour(payload, TAPROOM),
            ERR_GROWLER_LABEL_INCOMPLETE,
            422,
        )

        _, meta = validate_paginated(
            api.list_taproom_pours(TAPROOM, {"keg_asset_id": keg["id"]})
        )
        assert meta["total_count"] == 0


class TestLicenceWindowLowerBound:
    def test_an_order_a_month_ahead_of_the_licence_is_not_yet_effective(self, api):
        """The unopened window has its own error, distinct from the lapsed one.

        PRD §3.6: "A licence whose window has not opened — the logical clock is
        earlier than `effective_from_utc` — refuses order submission, allocation,
        shipment and appointment proposal with `ERR_LICENSE_NOT_YET_EFFECTIVE`."

        Design: Corner/validations/order_created_before_the_license_effective_instant_is_not_yet_effective
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-09-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )

        validate_error(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=2.00,
                    ship_to_state_code="ID",
                    distance_miles=100,
                    requested_ship_utc="2026-09-15T15:00:00Z",
                    order_code="SO-6500",
                ),
                ADMIN,
            ),
            ERR_LICENSE_NOT_YET_EFFECTIVE,
            409,
        )

        _, meta = validate_paginated(
            api.list_distribution_orders(ADMIN, {"state_license_id": license_row["id"]})
        )
        assert meta["total_count"] == 0
        assert (
            validate_success(api.get_state_license(license_row["id"], COMPLIANCE))["status"]
            == LICENSE_ACTIVE
        )


class TestWholesalerOnlyNeedsItsAppointment:
    def test_the_same_order_is_refused_then_accepted_once_a_wholesaler_exists(self, api):
        """Order validity turns on a different entity, and the retry is rerouted.

        PRD §3.7: "The mirror-image case is the one that fails: a licence whose
        `license_type` is `WHOLESALER_ONLY` with **no** live appointment covering the
        beer cannot be shipped into at all, because the brewery holds no
        self-distribution privilege there and has no wholesaler to hand the beer to."

        Design: Corner/validations/wholesaler_only_license_needs_an_appointment_before_it_can_take_an_order
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )

        validate_error(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=5.00,
                    ship_to_state_code="WA",
                    distance_miles=100,
                    requested_ship_utc="2026-08-20T15:00:00Z",
                    order_code="SO-6601",
                ),
                ADMIN,
            ),
            ERR_WHOLESALER_APPOINTMENT_REQUIRED,
            422,
        )
        appointment = create_active_appointment(
            api, license_row["id"], brand_scope=SCOPE_ALL_BRANDS
        )
        accepted = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=5.00,
                    ship_to_state_code="WA",
                    distance_miles=100,
                    requested_ship_utc="2026-08-20T15:00:00Z",
                    order_code="SO-6602",
                ),
                ADMIN,
            ),
            201,
        )

        assert accepted["channel"] == ORDER_CHANNEL_WHOLESALER
        assert accepted["appointment_id"] == appointment["id"]
        assert_cents(accepted["product_cents"], 210000, "product_cents")
        assert_cents(accepted["freight_cents"], 7200, "freight_cents")
        assert_cents(accepted["franchise_fee_cents"], 6516, "franchise_fee_cents")
        assert_cents(accepted["landed_cost_cents"], 223716, "landed_cost_cents")
        _, meta = validate_paginated(
            api.list_distribution_orders(ADMIN, {"state_license_id": license_row["id"]})
        )
        assert meta["total_count"] == 1
        assert validate_success(api.get_brewery(ADMIN))["franchise_locked_state_codes"] == [
            "WA"
        ]


class TestGoodCauseIsConditional:
    def test_only_the_franchise_state_demands_a_good_cause_code(self, api):
        """One flag on the parent licence switches the requirement on and off.

        PRD §3.6: "In a franchise state — the licence's `franchise_state` is true —
        the request must carry a `good_cause_code`, one of `NONPAYMENT`,
        `BREACH_OF_CONTRACT`, `LOSS_OF_LICENSE` or `VOLUNTARY_MUTUAL`; omitting it is
        refused with `ERR_GOOD_CAUSE_REQUIRED`."

        Design: Corner/validations/good_cause_is_demanded_only_when_the_license_is_a_franchise_state
        """
        bootstrap_brewery(api, home_state_code="OR")
        franchise_license = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            termination_notice_days=90,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        open_license = create_license(
            api,
            "ID",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=False,
            termination_notice_days=30,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        franchise_appointment = create_active_appointment(
            api, franchise_license["id"], brand_scope=SCOPE_ALL_BRANDS
        )
        open_appointment = create_active_appointment(
            api, open_license["id"], brand_scope=SCOPE_ALL_BRANDS
        )

        validate_error(
            api.terminate_appointment(
                franchise_appointment["id"],
                termination_payload(TERMINATION_REQUEST),
                COMPLIANCE,
            ),
            ERR_GOOD_CAUSE_REQUIRED,
            422,
        )
        accepted = validate_success(
            api.terminate_appointment(
                open_appointment["id"], termination_payload(TERMINATION_REQUEST), COMPLIANCE
            )
        )

        blocked = validate_success(
            api.get_distributor_appointment(franchise_appointment["id"], COMPLIANCE)
        )
        assert blocked["state"] == APPT_ACTIVE
        assert blocked["termination_requested_at_utc"] is None
        assert accepted["state"] == APPT_TERMINATION_REQUESTED
        assert accepted["good_cause_code"] is None
        assert_instant_equals(
            accepted["termination_requested_at_utc"],
            DEFAULT_CLOCK,
            "termination_requested_at_utc",
        )
        assert_instant_equals(
            accepted["termination_effective_utc"],
            DEFAULT_CLOCK,
            "termination_effective_utc",
        )


class TestTerritoryEquality:
    def test_an_idaho_licence_cannot_carry_a_washington_shipment(self, api):
        """The rule is equality with the licence's own state, not mere existence.

        PRD §3.7: "The territory rule applies without exception:
        `ship_to_state_code` must equal the referenced licence's `state_code`, and any
        mismatch is refused with `ERR_TERRITORY_NOT_LICENSED` — the brewery may not
        ship into Ohio on a Michigan licence, however convenient the truck route."

        Design: Corner/validations/order_shipping_to_a_state_the_license_does_not_cover_is_refused
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", price_per_bbl_cents=42000
        )
        idaho = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        washington = create_license(
            api,
            "WA",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )

        validate_error(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    idaho["id"],
                    bbl_requested=2.00,
                    ship_to_state_code="WA",
                    distance_miles=100,
                    requested_ship_utc="2026-08-20T15:00:00Z",
                    order_code="SO-6701",
                ),
                ADMIN,
            ),
            ERR_TERRITORY_NOT_LICENSED,
            422,
        )
        accepted = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    idaho["id"],
                    bbl_requested=2.00,
                    ship_to_state_code="ID",
                    distance_miles=100,
                    requested_ship_utc="2026-08-20T15:00:00Z",
                    order_code="SO-6702",
                ),
                ADMIN,
            ),
            201,
        )

        assert accepted["state"] == ORDER_SUBMITTED
        assert accepted["ship_to_state_code"] == "ID"
        _, idaho_meta = validate_paginated(
            api.list_distribution_orders(ADMIN, {"state_license_id": idaho["id"]})
        )
        assert idaho_meta["total_count"] == 1
        _, washington_meta = validate_paginated(
            api.list_distribution_orders(ADMIN, {"state_license_id": washington["id"]})
        )
        assert washington_meta["total_count"] == 0


class TestRolePrecedesTheBody:
    def test_a_forbidden_role_is_reported_before_the_body_is_examined(self, api):
        """A body missing every required field still earns 403, never 400.

        PRD §2.8: "**Role authorisation** — the acting role appears in the
        endpoint's authorised list. Otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to
        every endpoint, and is evaluated before the body is inspected."

        Design: Corner/validations/forbidden_role_is_reported_before_the_body_is_even_parsed
        """
        bootstrap_brewery(api)

        body = validate_error(
            api.create_batch({"batch_code": "B-9001"}, TAPROOM), ERR_FORBIDDEN_ROLE, 403
        )

        serialised = str(body)
        for field in ("beer_id", "tank_id", "planned_volume_bbl", "brew_start_utc"):
            assert field not in serialised
        _, meta = validate_paginated(api.list_batches(CELLAR))
        assert meta["total_count"] == 0
