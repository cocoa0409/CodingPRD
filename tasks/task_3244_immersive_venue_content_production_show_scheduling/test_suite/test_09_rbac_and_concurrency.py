"""RBAC denials and optimistic-concurrency version progression."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_maintenance_window_payload,
    create_production,
    create_venue_system,
    validate_error,
    validate_success,
)

PD = TEST_USERS["production_director_headers"]
CP = TEST_USERS["content_producer_headers"]
GU = TEST_USERS["guest_headers"]


class TestRoleDenials:

    def test_content_producer_cannot_activate_production(self, api):
        """PRD: "A request whose role is well-formed but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/venue/productions/{production_id}/activate` | Activate production (DRAFT or DARK → ACTIVE) | ProductionDirector |"

        Design: Corner/rbac/content_producer_cannot_activate_production
        """
        prod = create_production(title="RB", production_type="ORIGINAL", base_price_cents=5000)
        resp = api.activate_production(prod["id"], CP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        data = validate_success(api.activate_production(prod["id"], PD))
        assert data["status"] == "ACTIVE"

    def test_venue_scheduler_cannot_activate_production(self, api):
        """PRD: "A request whose role is well-formed but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/venue/productions/{production_id}/activate` | Activate production (DRAFT or DARK → ACTIVE) | ProductionDirector |"

        Design: Corner/rbac/content_producer_cannot_activate_production
        """
        prod = create_production(title="RB2", production_type="ORIGINAL", base_price_cents=5000)
        resp = api.activate_production(prod["id"], TEST_USERS["venue_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        data = validate_success(api.activate_production(prod["id"], PD))
        assert data["status"] == "ACTIVE"

    def test_guest_cannot_schedule_maintenance(self, api):
        """PRD: "A request whose role is well-formed but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/venue/maintenance-windows` | Schedule a maintenance window | VenueOpsEngineer |"

        Design: Corner/rbac/guest_cannot_schedule_maintenance
        """
        system = create_venue_system(name="HAP-1", kind="HAPTIC")
        resp = api.create_maintenance_window(
            create_maintenance_window_payload(
                system["id"],
                start_time="2026-09-05T01:00:00Z",
                end_time="2026-09-05T02:00:00Z",
                buffer_minutes=15,
            ),
            GU,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_content_producer_cannot_schedule_maintenance(self, api):
        """PRD: "A request whose role is well-formed but not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/venue/maintenance-windows` | Schedule a maintenance window | VenueOpsEngineer |"

        Design: Corner/rbac/guest_cannot_schedule_maintenance
        """
        system = create_venue_system(name="HAP-2", kind="HAPTIC")
        resp = api.create_maintenance_window(
            create_maintenance_window_payload(
                system["id"],
                start_time="2026-09-05T01:00:00Z",
                end_time="2026-09-05T02:00:00Z",
                buffer_minutes=15,
            ),
            CP,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestVersionProgression:

    def test_version_increments_by_one_on_each_mutation(self, api):
        """PRD: "`version` (integer): a system-managed integer that increments
        by exactly 1 on every mutation to the resource, including mutations
        triggered by cascading side effects from a parent or sibling resource."

        Design: Corner/cross_cutting_layers/version_increments_on_mutation
        """
        prod = create_production(title="VV", production_type="ORIGINAL", base_price_cents=5000)
        assert prod["version"] == 1
        activated = validate_success(api.activate_production(prod["id"], PD))
        assert activated["version"] == 2
        deactivated = validate_success(api.deactivate_production(prod["id"], PD))
        assert deactivated["version"] == 3

    def test_version_increments_on_retire(self, api):
        """PRD: "`version` (integer): a system-managed integer that increments
        by exactly 1 on every mutation to the resource, including mutations
        triggered by cascading side effects from a parent or sibling resource."

        Design: Corner/cross_cutting_layers/version_increments_on_mutation
        """
        prod = create_production(title="VV2", production_type="ORIGINAL", base_price_cents=5000)
        assert prod["version"] == 1
        retired = validate_success(api.retire_production(prod["id"], PD))
        assert retired["version"] == 2
        assert retired["status"] == "RETIRED"
