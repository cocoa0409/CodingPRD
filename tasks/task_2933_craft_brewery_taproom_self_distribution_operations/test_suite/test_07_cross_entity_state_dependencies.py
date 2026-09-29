"""Gates that live on a neighbouring row: a dirty vessel and a revoked label."""

from test_helpers import (
    ADMIN,
    BATCH_BREWING,
    BATCH_DUMPED,
    BATCH_SCHEDULED,
    CELLAR,
    COMPLIANCE,
    DECISION_APPROVED,
    DECISION_REVOKED,
    ERR_LABEL_NOT_APPROVED,
    ERR_TANK_NOT_IDLE,
    FILING_LABEL,
    LABEL_COLA_REVOKED,
    LICENSE_ACTIVE,
    LICENSE_SELF_DISTRIBUTION,
    REG_FORMULA_EXEMPT,
    REGULATOR,
    TANK_ACTION_CIP,
    TANK_DIRTY,
    TANK_OCCUPIED,
    dump_payload,
    filing_decision_payload,
    label_filing_payload,
    order_payload,
    tank_service_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_exempt_beer,
    create_license,
    create_scheduled_batch,
    create_tank,
)


class TestBatchStartBlockedByADirtyTank:
    def _dumped_predecessor_then_a_fresh_batch(self, api):
        bootstrap_brewery(api)
        beer = create_exempt_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        first = create_scheduled_batch(
            api,
            beer["id"],
            tank["id"],
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        assert validate_success(api.start_batch(first["id"], CELLAR))["state"] == BATCH_BREWING
        validate_success(
            api.dump_batch(
                first["id"],
                dump_payload(reason="lactobacillus infection detected at day 3"),
                CELLAR,
            )
        )
        second = create_scheduled_batch(
            api,
            beer["id"],
            tank["id"],
            batch_code="B-1002",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-20T06:00:00Z",
            brew_end_utc="2026-08-27T06:00:00Z",
        )
        return tank, first, second

    def test_a_valid_batch_cannot_start_in_a_vessel_a_dumped_batch_left_dirty(self, api):
        """The gate is the tank's status, and the refusal names the tank.

        PRD §3.2: "The transition demands three things: the batch is in
        `SCHEDULED`, the brewery's `notice_status` is `ACTIVE` (otherwise
        `ERR_NOTICE_NOT_ACTIVE`), and the referenced vessel's `status` is exactly
        `IDLE` (otherwise `ERR_TANK_NOT_IDLE` — a `DIRTY` vessel must pass a
        clean-in-place cycle first, and an `OUT_OF_SERVICE` one must be returned
        to service)."

        Design: Difficulty/cross_entity_state_dependency/batch_start_blocked_by_dirty_tank_left_by_a_dumped_predecessor
        """
        tank, first, second = self._dumped_predecessor_then_a_fresh_batch(api)

        validate_error(api.start_batch(second["id"], CELLAR), ERR_TANK_NOT_IDLE, 409)

        assert validate_success(api.get_batch(second["id"], CELLAR))["state"] == BATCH_SCHEDULED
        assert validate_success(api.get_batch(first["id"], CELLAR))["state"] == BATCH_DUMPED
        stored_tank = validate_success(api.get_tank(tank["id"], CELLAR))
        assert stored_tank["status"] == TANK_DIRTY
        assert stored_tank["occupying_batch_id"] is None
        assert stored_tank["cip_cycle_count"] == 0

    def test_washing_the_vessel_lets_the_same_start_call_through(self, api):
        """A clean-in-place returns FV-01 to IDLE and the blocked start succeeds.

        PRD §3.2: "`CIP` — clean-in-place — is legal only from `DIRTY` and returns
        the vessel to `IDLE`, stamping `last_cip_utc` with the current logical
        clock and incrementing `cip_cycle_count` by 1."

        Design: Difficulty/cross_entity_state_dependency/batch_start_blocked_by_dirty_tank_left_by_a_dumped_predecessor
        """
        tank, _, second = self._dumped_predecessor_then_a_fresh_batch(api)
        validate_error(api.start_batch(second["id"], CELLAR), ERR_TANK_NOT_IDLE)

        validate_success(
            api.service_tank(
                tank["id"],
                tank_service_payload(TANK_ACTION_CIP, 150, 60),
                CELLAR,
            )
        )
        started = validate_success(api.start_batch(second["id"], CELLAR))

        assert started["state"] == BATCH_BREWING
        stored_tank = validate_success(api.get_tank(tank["id"], CELLAR))
        assert stored_tank["status"] == TANK_OCCUPIED
        assert stored_tank["occupying_batch_id"] == second["id"]
        assert stored_tank["cip_cycle_count"] == 1


class TestOrderBlockedByARevokedLabel:
    def _revoked_label_beer_and_active_licence(self, api):
        bootstrap_brewery(api)
        beer = create_exempt_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        validate_success(api.create_beer_filing(beer["id"], label_filing_payload(), COMPLIANCE))
        validate_success(
            api.decide_beer_filing(
                beer["id"],
                FILING_LABEL,
                filing_decision_payload(DECISION_APPROVED, cola_id="COLA-24-0917"),
                REGULATOR,
            )
        )
        validate_success(
            api.decide_beer_filing(
                beer["id"],
                FILING_LABEL,
                filing_decision_payload(
                    DECISION_REVOKED,
                    note="net contents statement does not match the fill",
                ),
                REGULATOR,
            )
        )
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )
        return beer, license_row

    def test_order_submission_is_refused_for_a_beer_whose_cola_was_revoked(self, api):
        """Everything else is in order; only the beer's label dimension fails.

        PRD §2.8: "`ERR_LABEL_NOT_APPROVED` (422) when `label_state` is anything
        other than `COLA_APPROVED` on a **distribution** path, meaning order
        submission or a distribution deployment of a keg — a certificate of label
        approval is never required for a taproom draft pour and this code is never
        raised for one."

        Design: Difficulty/cross_entity_state_dependency/distribution_order_blocked_by_revoked_cola_on_the_beer
        """
        beer, license_row = self._revoked_label_beer_and_active_licence(api)

        validate_error(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=2.00,
                    ship_to_state_code="ID",
                    distance_miles=120,
                    requested_ship_utc="2026-08-15T15:00:00Z",
                    order_code="SO-4004",
                ),
                ADMIN,
            ),
            ERR_LABEL_NOT_APPROVED,
            422,
        )

        orders, meta = validate_paginated(api.list_distribution_orders(ADMIN))
        assert orders == []
        assert meta["total_count"] == 0
        assert (
            validate_success(api.get_state_license(license_row["id"], ADMIN))["status"]
            == LICENSE_ACTIVE
        )

    def test_the_revoked_label_leaves_the_beer_pourable_across_the_bar(self, api):
        """Revocation drops distribution_sellable alone; taproom_sellable stands.

        PRD §3.1: "`COLA_APPROVED → COLA_REVOKED` drops `distribution_sellable`
        to false while leaving `taproom_sellable` exactly as it was, then reaches
        out two hops: first every distribution order for that beer whose `state`
        is `SUBMITTED` or `ALLOCATED` moves to `REJECTED` with `rejection_reason`
        of `LABEL_REVOKED`, and then — caused by those rejections — every
        allocation entry of each just-rejected order is released, decrementing the
        cited run's `allocated_bbl` and incrementing its `available_bbl` by that
        entry's barrel figure."

        Design: Difficulty/cross_entity_state_dependency/distribution_order_blocked_by_revoked_cola_on_the_beer
        """
        beer, _ = self._revoked_label_beer_and_active_licence(api)

        stored = validate_success(api.get_beer(beer["id"], ADMIN))

        assert stored["label_state"] == LABEL_COLA_REVOKED
        assert stored["registration_state"] == REG_FORMULA_EXEMPT
        assert stored["distribution_sellable"] is False
        assert stored["taproom_sellable"] is True
