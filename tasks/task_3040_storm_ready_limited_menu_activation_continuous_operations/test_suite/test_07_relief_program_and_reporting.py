"""Community meal service: pledge gating, confirmation settlement, the
conservative-vs-actual reimbursement variants, and the reporting cadence."""
from test_helpers import (
    activate_storm,
    ADMIN,
    ApiErrorId,
    assert_relief_pledge,
    confirm_pledge,
    create_relief_org,
    create_storm,
    create_unit_for,
    deescalate_storm,
    file_condition_report,
    get_unit,
    RC,
    set_clock,
    setup_relief_scenario,
    setup_storm_with_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPledgeCreationGates:
    def test_pledge_creation_requires_active_relief_org(self, api, relief_coordinator_headers):
        """PRD §3.8: "Pledging requires the unit to be storm-affected — a
        `FULL`-menu unit is rejected with `ERR_UNIT_NOT_STORM_AFFECTED` — and
        requires the referenced organization to be `ACTIVE`, a `SUSPENDED` one
        yielding `ERR_RELIEF_ORG_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/pledge_creation_requires_active_relief_org
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="UP", water="DOWN", gas="UP", payment_network="UP"
        )
        org = create_relief_org()
        org = validate_success(
            api.patch_relief_org(org["id"], {"status": "SUSPENDED"}, relief_coordinator_headers)
        )
        assert org["status"] == "SUSPENDED"
        resp = api.create_relief_pledge(
            uid,
            {"relief_org_id": org["id"], "meal_count": 10, "service_date": "2026-09-10"},
            relief_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RELIEF_ORG_INACTIVE)
        _, meta = validate_paginated(
            api.list_relief_pledges(uid, relief_coordinator_headers)
        )
        assert meta["total_count"] == 0

    def test_suspended_org_rejection_is_distinct_from_unit_posture(self, api, relief_coordinator_headers):
        """PRD §3.8: "Pledging requires the unit to be storm-affected — a
        `FULL`-menu unit is rejected with `ERR_UNIT_NOT_STORM_AFFECTED` — and
        requires the referenced organization to be `ACTIVE`, a `SUSPENDED` one
        yielding `ERR_RELIEF_ORG_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/pledge_creation_requires_active_relief_org
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        uid = ctx["unit"]["id"]
        file_condition_report(
            uid, power="UP", water="UP", gas="DOWN", payment_network="UP"
        )
        org = create_relief_org()
        api.patch_relief_org(org["id"], {"status": "SUSPENDED"}, relief_coordinator_headers)
        resp = api.create_relief_pledge(
            uid,
            {"relief_org_id": org["id"], "meal_count": 5, "service_date": "2026-09-10"},
            relief_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RELIEF_ORG_INACTIVE)

    def test_pledge_on_unaffected_unit_rejected(self, api, relief_coordinator_headers):
        """PRD §3.8: "Pledging requires the unit to be storm-affected — a
        `FULL`-menu unit is rejected with `ERR_UNIT_NOT_STORM_AFFECTED` — and
        requires the referenced organization to be `ACTIVE`, a `SUSPENDED` one
        yielding `ERR_RELIEF_ORG_INACTIVE`."

        Design: Corner/validations/pledge_on_unaffected_unit_rejected
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        org = create_relief_org()
        resp = api.create_relief_pledge(
            ctx["unit"]["id"],
            {"relief_org_id": org["id"], "meal_count": 5, "service_date": "2026-09-10"},
            relief_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_STORM_AFFECTED)


class TestConfirmationSettlement:
    def test_relief_pledge_get_returns_computed_fields_after_confirm(self, api, relief_coordinator_headers):
        """PRD §3.8: "`shortfall_meals` is the pledged count minus the served
        count, floored at zero; `overage_meals` is the served count minus the
        pledged count, floored at zero; `shortfall_penalty_cents` is the
        shortfall multiplied by one hundred cents per missing meal. The
        conservative reimbursement posted to `reimbursement_cents` at
        confirmation pays only for pledged meals: eligible meals equal the
        served count minus the overage — that is, capped at the pledged count.
        The gross is eligible meals multiplied by two hundred fifty cents each.
        The tier boundary sits on the gross: tier one below three thousand
        cents earns no bonus, tier two from three thousand up to but not
        including eight thousand cents earns a one-thousand-cent bonus, and
        tier three at eight thousand cents or more earns a
        two-thousand-five-hundred-cent bonus. Liability is the gross plus the
        tier bonus minus the shortfall penalty. Tax is then extracted from that
        tax-inclusive liability: the liability multiplied by eight hundred
        basis points and divided by ten thousand plus eight hundred basis
        points, floored to whole cents. The reimbursement paid to the unit is
        the liability minus that extracted tax."

        Design: Corner/entities/relief_pledge_get_returns_computed_fields_after_confirm
        """
        ctx = setup_relief_scenario(meal_count=10, service_date="2026-09-10")
        pledge = confirm_pledge(ctx["unit"]["id"], ctx["pledge"]["id"], served_count=8)
        assert_relief_pledge(pledge)
        assert pledge["shortfall_meals"] == 2
        assert pledge["overage_meals"] == 0
        assert pledge["shortfall_penalty_cents"] == 200
        # eligible = served - overage = 8; gross 8*250 = 2000 (tier 1, bonus 0);
        # liability 2000 - 200 = 1800; tax floor(1800*800/10800) = 133; net 1667.
        assert pledge["reimbursement_cents"] == 1667
        assert pledge["final_reimbursement_cents"] is None, (
            "final_reimbursement_cents stays null until the reporting cadence posts it"
        )

    def test_relief_tiered_bonus_with_tax_extraction(self, api, relief_coordinator_headers):
        """PRD §3.8: "The gross is eligible meals multiplied by two hundred
        fifty cents each. The tier boundary sits on the gross: tier one below
        three thousand cents earns no bonus, tier two from three thousand up to
        but not including eight thousand cents earns a one-thousand-cent bonus,
        and tier three at eight thousand cents or more earns a
        two-thousand-five-hundred-cent bonus. Liability is the gross plus the
        tier bonus minus the shortfall penalty. Tax is then extracted from that
        tax-inclusive liability: the liability multiplied by eight hundred
        basis points and divided by ten thousand plus eight hundred basis
        points, floored to whole cents. The reimbursement paid to the unit is
        the liability minus that extracted tax."

        Design: Difficulty/combinatorial_formula/relief_tiered_bonus_with_tax_extraction
        """
        # 12 pledged, 12 served: gross 3000 lands exactly on the tier-2 boundary.
        ctx = setup_relief_scenario(meal_count=12, service_date="2026-09-10")
        pledge = confirm_pledge(ctx["unit"]["id"], ctx["pledge"]["id"], served_count=12)
        assert pledge["shortfall_meals"] == 0
        assert pledge["overage_meals"] == 0
        assert pledge["shortfall_penalty_cents"] == 0
        # liability 3000+1000 = 4000; tax floor(4000*800/10800) = 296; net 3704
        assert pledge["reimbursement_cents"] == 3704

    def test_gross_just_below_tier2_boundary_earns_no_bonus(self, api, relief_coordinator_headers):
        """PRD §3.8: "The gross is eligible meals multiplied by two hundred
        fifty cents each. The tier boundary sits on the gross: tier one below
        three thousand cents earns no bonus, tier two from three thousand up to
        but not including eight thousand cents earns a one-thousand-cent bonus,
        and tier three at eight thousand cents or more earns a
        two-thousand-five-hundred-cent bonus. Liability is the gross plus the
        tier bonus minus the shortfall penalty. Tax is then extracted from that
        tax-inclusive liability: the liability multiplied by eight hundred
        basis points and divided by ten thousand plus eight hundred basis
        points, floored to whole cents. The reimbursement paid to the unit is
        the liability minus that extracted tax."

        Design: Difficulty/combinatorial_formula/relief_tiered_bonus_with_tax_extraction
        """
        # 11 pledged, 11 served: gross 2750 stays in tier 1 (no bonus).
        ctx = setup_relief_scenario(meal_count=11, service_date="2026-09-10")
        pledge = confirm_pledge(ctx["unit"]["id"], ctx["pledge"]["id"], served_count=11)
        # liability 2750; tax floor(2750*800/10800) = 203; net 2547
        assert pledge["reimbursement_cents"] == 2547

    def test_relief_reimbursement_tier3_bonus_applies(self, api, relief_coordinator_headers):
        """PRD §3.8: "The tier boundary sits on the gross: tier one below three
        thousand cents earns no bonus, tier two from three thousand up to but
        not including eight thousand cents earns a one-thousand-cent bonus, and
        tier three at eight thousand cents or more earns a
        two-thousand-five-hundred-cent bonus. Liability is the gross plus the
        tier bonus minus the shortfall penalty. Tax is then extracted from that
        tax-inclusive liability: the liability multiplied by eight hundred
        basis points and divided by ten thousand plus eight hundred basis
        points, floored to whole cents. The reimbursement paid to the unit is
        the liability minus that extracted tax."

        Design: Corner/calculations/relief_reimbursement_tier3_bonus_applies
        """
        # 40 pledged, 40 served: gross 10000 (tier 3); liability 12500;
        # tax floor(12500*800/10800) = 925; net 11575.
        ctx = setup_relief_scenario(meal_count=40, service_date="2026-09-10")
        pledge = confirm_pledge(ctx["unit"]["id"], ctx["pledge"]["id"], served_count=40)
        assert pledge["reimbursement_cents"] == 11575


class TestServiceDateGate:
    def test_confirm_before_service_date_rejected(self, api, relief_coordinator_headers):
        """PRD §3.8: "Confirmation happens after the meal day has begun: the
        logical clock must have reached midnight UTC of the `service_date`,
        otherwise `ERR_SERVICE_NOT_PAST`."

        Design: Corner/validations/confirm_before_service_date_rejected
        """
        ctx = setup_relief_scenario(meal_count=5, service_date="2026-09-11")
        uid = ctx["unit"]["id"]
        pledge_id = ctx["pledge"]["id"]
        set_clock("2026-09-10T23:59:59Z")
        resp = api.confirm_relief_pledge(
            uid, pledge_id, {"served_count": 5}, relief_coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_NOT_PAST)
        set_clock("2026-09-11T00:00:00Z")
        pledge = validate_success(
            api.confirm_relief_pledge(
                uid, pledge_id, {"served_count": 5}, relief_coordinator_headers
            )
        )
        assert pledge["status"] == "CONFIRMED"


class TestDualVariantReimbursement:
    def test_relief_reimbursement_conservative_vs_actual(self, api, relief_coordinator_headers, admin_headers):
        """PRD §3.8: "The conservative reimbursement posted to
        `reimbursement_cents` at confirmation pays only for pledged meals:
        eligible meals equal the served count minus the overage — that is,
        capped at the pledged count."
        PRD §3.8: "The actual variant pays for everything served: eligible
        meals equal the full `served_count` uncapped, so the gross is
        recomputed on the larger figure and the tier and bonus recomputed with
        it; the shortfall penalty is zero whenever the served count has reached
        the pledged count; and the same tax-inclusive extraction applies."

        Design: Difficulty/dual_variant_calc/relief_reimbursement_conservative_vs_actual
        """
        ctx = setup_relief_scenario(meal_count=16, service_date="2026-09-10")
        uid = ctx["unit"]["id"]
        pledge = confirm_pledge(uid, ctx["pledge"]["id"], served_count=20)
        assert pledge["overage_meals"] == 4
        assert pledge["shortfall_meals"] == 0
        # conservative: eligible 16, gross 4000 (tier 2), liability 5000,
        # tax floor(5000*800/10800) = 370 -> 4630
        assert pledge["reimbursement_cents"] == 4630
        report = validate_success(api.run_report(None, admin_headers))
        assert report["pledges_finalized"] == 1
        pledges, _ = validate_paginated(api.list_relief_pledges(uid, relief_coordinator_headers))
        assert len(pledges) == 1
        # actual: eligible 20, gross 5000 (tier 2), liability 6000,
        # tax floor(6000*800/10800) = 444 -> 5556
        assert pledges[0]["final_reimbursement_cents"] == 5556
        assert pledges[0]["final_reimbursement_cents"] != pledges[0]["reimbursement_cents"]

    def test_actual_variant_pays_served_overage_after_run_report(self, api, relief_coordinator_headers, admin_headers):
        """PRD §3.8: "The actual variant pays for everything served: eligible
        meals equal the full `served_count` uncapped, so the gross is
        recomputed on the larger figure and the tier and bonus recomputed with
        it; the shortfall penalty is zero whenever the served count has reached
        the pledged count; and the same tax-inclusive extraction applies."
        PRD §3.8: "Second, for every pledge in `CONFIRMED` status whose
        `final_reimbursement_cents` is still null — processed in `service_date`
        ascending order with `created_at` ascending as the tie-breaker, never
        by `id` — it posts the actual-variant reimbursement."

        Design: Difficulty/dual_variant_calc/relief_reimbursement_conservative_vs_actual
        """
        # 30 pledged, 36 served: conservative caps at 30 (gross 7500, tier 2,
        # liability 8500, tax floor(8500*800/10800)=629 -> 7871); actual pays
        # 36 (gross 9000, tier 3, liability 11500, tax floor(11500*800/10800)=851
        # -> 10649). The tier crossing between the two variants is the point.
        ctx = setup_relief_scenario(meal_count=30, service_date="2026-09-10")
        uid = ctx["unit"]["id"]
        pledge = confirm_pledge(uid, ctx["pledge"]["id"], served_count=36)
        assert pledge["reimbursement_cents"] == 7871
        validate_success(api.run_report(None, admin_headers))
        pledges, _ = validate_paginated(api.list_relief_pledges(uid, relief_coordinator_headers))
        assert pledges[0]["final_reimbursement_cents"] == 10649


class TestReportingCadence:
    def test_run_report_sweep_skips_terminal_storms_and_null_shift_units(self, api, admin_headers):
        """PRD §3.8: "First, for every unit of every non-terminal storm
        (`WATCH`, `WARNING`, `ACTIVE`, or `RECOVERY`), it recomputes
        `hours_since_shift_change` as the whole-hour floor between the unit's
        `last_shift_change_at` and the logical clock — a null stamp leaves the
        count unchanged — and collects per-unit status lines; each unit whose
        count changed has its `version` incremented by one."
        PRD §3.8: "Second, for every pledge in `CONFIRMED` status whose
        `final_reimbursement_cents` is still null — processed in `service_date`
        ascending order with `created_at` ascending as the tie-breaker, never
        by `id` — it posts the actual-variant reimbursement."

        Design: Corner/calculations/run_report_sweep_skips_terminal_storms_and_null_shift_units
        """
        set_clock("2026-09-10T08:00:00Z")
        storm1 = create_storm(clock=None, name="Hurricane Delta")
        u1 = create_unit_for(storm1, unit_code="U-1", address="1 Storm Way")
        activate_storm(storm1)
        storm2 = create_storm(clock=None, name="Tropical Storm Eve")
        u2 = create_unit_for(storm2, unit_code="U-2", address="2 Storm Way")
        storm2 = activate_storm(storm2)
        storm2 = deescalate_storm(storm2)
        resp = api.close_storm_event(
            storm2["id"], {"expected_storm_event_version": storm2["version"]}, admin_headers
        )
        storm2 = validate_success(resp)
        assert storm2["status"] == "CLOSED"
        report = validate_success(api.run_report(None, admin_headers))
        assert report["units_reported"] == 1, (
            "the CLOSED storm's unit must be excluded from the sweep"
        )
        assert report["pledges_finalized"] == 0
        report2 = validate_success(api.run_report(None, admin_headers))
        assert report2["pledges_finalized"] == 0, (
            "the sweep is idempotent — nothing is re-posted"
        )
