"""Deployment orders: interval semantics, uniqueness, OCC, and the
clock-driven scheduled activation."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import factories, fixtures
from test_helpers.fixtures import (
    ADMIN,
    OFFICER_A,
    build_offering,
    member_version,
    register_order,
)


class TestDuplicateOrdersNumber:
    def test_second_order_with_same_orders_number_rejected(self, api):
        """PRD §3.5: "Deployment orders are registered against a member by a
        `VerificationOfficer` carrying `orders_number` (unique across all
        orders — a collision is rejected with `ERR_DUPLICATE_ORDER`)..."

        Design: Corner/validations/duplicate_orders_number_conflict
        """
        member_id, _ = fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date="2026-10-01",
            scra_eligible=False, name="Dup Dan",
        )
        order_number = None
        orders = validate_success(
            api.list_member_deployment_orders(member_id, OFFICER_A)
        )
        order_number = orders[0]["orders_number"]
        payload = factories.deployment_order_payload(
            member_version(api, member_id),
            orders_number=order_number, theater="EUCOM",
            start_date="2027-01-01", end_date="2027-02-01",
            scra_eligible=False,
        )
        resp = api.create_deployment_order(member_id, payload, OFFICER_A)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ORDER, 409)


class TestInclusiveIntervalOverlap:
    def _member_with_first_order(self, api):
        member_id, order = fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date="2026-12-01",
            scra_eligible=False, name="Sal Shore",
        )
        return member_id, order

    def test_adjacent_start_day_conflicts(self, api):
        """PRD §3.5: "Deployment intervals are treated as inclusive at both
        ends, so two orders where one ends on the very day another begins are
        in conflict, failing with `ERR_DEPLOYMENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/deployment_overlap_inclusive_adjacent_days_conflict
        """
        member_id, _ = self._member_with_first_order(api)
        payload = factories.deployment_order_payload(
            member_version(api, member_id),
            theater="EUCOM", start_date="2026-12-01", end_date="2027-03-01",
            scra_eligible=False,
        )
        resp = api.create_deployment_order(member_id, payload, OFFICER_A)
        validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_OVERLAP, 409)

    def test_next_day_start_accepted(self, api):
        """PRD §3.5: "Per member, the date intervals of non-cancelled orders
        must not overlap. Deployment intervals are treated as inclusive at
        both ends, so two orders where one ends on the very day another
        begins are in conflict..." — a start one day later shares no date.

        Design: Difficulty/resource_temporal_overlap/deployment_overlap_inclusive_adjacent_days_conflict
        """
        member_id, _ = self._member_with_first_order(api)
        payload = factories.deployment_order_payload(
            member_version(api, member_id),
            theater="EUCOM", start_date="2026-12-02", end_date="2027-03-01",
            scra_eligible=False,
        )
        created = validate_success(
            api.create_deployment_order(member_id, payload, OFFICER_A), 201
        )
        assert created["start_date"].startswith("2026-12-02")


class TestOccOnOrderCreate:
    def test_stale_member_version_rejected(self, api):
        """PRD §2.8: "Registering a deployment order against a member
        likewise requires `expected_member_version`. In both cases, if the
        supplied value does not equal the member's current `version` on the
        server, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_deployment_order_create
        """
        fixtures.ensure_clock(api)
        _, member_id = fixtures.approve_direct_member(
            api, name="Occ Otto", still_serving=True,
        )
        stale_version = member_version(api, member_id)
        # First registration succeeds and bumps the member version by 1.
        register_order(
            api, member_id, expected_member_version=stale_version,
            start_date="2026-09-01", end_date="2026-10-01",
            scra_eligible=False,
        )
        payload = factories.deployment_order_payload(
            stale_version, theater="EUCOM",
            start_date="2026-11-01", end_date="2026-12-01",
            scra_eligible=False,
        )
        resp = api.create_deployment_order(member_id, payload, OFFICER_A)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_order_create_retry_with_fresh_version_bumps_once(self, api):
        """PRD §2.8: "Both guarded writes themselves increment the member's
        `version` by 1 on success." and "...if the supplied value does not
        equal the member's current `version` on the server, the write is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_deployment_order_create
        """
        fixtures.ensure_clock(api)
        _, member_id = fixtures.approve_direct_member(
            api, name="Occ Otto Two", still_serving=True,
        )
        v1 = member_version(api, member_id)
        register_order(
            api, member_id, expected_member_version=v1,
            start_date="2026-09-01", end_date="2026-10-01",
            scra_eligible=False,
        )
        v2 = member_version(api, member_id)
        payload = factories.deployment_order_payload(
            v2, theater="EUCOM",
            start_date="2026-11-01", end_date="2026-12-01",
            scra_eligible=False,
        )
        created = validate_success(
            api.create_deployment_order(member_id, payload, OFFICER_A), 201
        )
        assert created["orders_number"]
        member = validate_success(api.get_member(member_id, OFFICER_A))
        assert member["version"] == v2 + 1


class TestScheduledActivation:
    def test_order_registered_until_clock_reaches_start(self, api):
        """PRD §2.5: "Before any call is made, the logical clock reads
        exactly `2026-09-01T00:00:00Z`, and the server must not fall back to
        wall-clock time under any circumstance." PRD §3.5: "When the
        `start_date` is on or before the current logical-clock date, the
        order auto-activates to `ACTIVE` at creation..."

        Design: Corner/cross_cutting_layers/scheduled_clock_default_and_activation_on_set
        """
        _, member_id = fixtures.approve_direct_member(
            api, name="Sch Scott", still_serving=True,
        )
        order = register_order(
            api, member_id, start_date="2026-09-10", end_date="2026-12-10",
            scra_eligible=True,
        )
        assert order["status"] == "REGISTERED"
        member = validate_success(api.get_member(member_id, OFFICER_A))
        assert member["deployment_posture"] == "NONE"

    def test_clock_advance_auto_activates_and_deploys_member(self, api):
        """PRD §2.5: "Advancing the clock has exactly one retroactive
        consequence: every `REGISTERED` deployment order whose `start_date`
        is on or before the new clock reading auto-activates to `ACTIVE`,
        carrying the posture cascade described in §3.5 when the owning member
        is `ACTIVE`."

        Design: Corner/cross_cutting_layers/scheduled_clock_default_and_activation_on_set
        """
        _, member_id = fixtures.approve_direct_member(
            api, name="Sch Scott Two", still_serving=True,
        )
        order = register_order(
            api, member_id, start_date="2026-09-10", end_date="2026-12-10",
            scra_eligible=True,
        )
        assert order["status"] == "REGISTERED"
        fixtures.set_clock(api, "2026-09-10T00:00:00Z")
        fetched = validate_success(
            api.get_deployment_order(order["id"], OFFICER_A)
        )
        assert fetched["status"] == "ACTIVE"
        member = validate_success(api.get_member(member_id, OFFICER_A))
        assert member["deployment_posture"] == "DEPLOYED"
