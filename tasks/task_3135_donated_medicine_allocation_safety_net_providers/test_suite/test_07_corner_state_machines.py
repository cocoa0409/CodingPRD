"""Corner tests: state-machine edges — invalid transitions, terminal lockdown,
initial states, and transition side effects."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    EMERGENCY_MANAGER_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    QA_PHARMACIST_HEADERS,
    ApiErrorId as E,
    assert_lot_quantity_conservation,
)
from test_helpers import fixtures
from test_helpers.test_users import make_site_coordinator_headers


class TestLotReleaseInvalidState:
    def test_release_on_releasable_lot_rejected(self, api):
        """PRD §3.2: "Release requires the lot to currently be `QUARANTINED`
        (otherwise `ERR_INVALID_STATE`), the donor to be `ACTIVE` (otherwise
        `ERR_DONOR_NOT_ACTIVE`), and — for controlled lots — the donor's
        `dea_registration_no` to be non-empty (otherwise
        `ERR_CONTROLLED_DONOR_UNREGISTERED`)."

        Design: Corner/state_machines/lot_release_from_releasable_returns_invalid_state
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_and_release_lot(api, donor["id"], ndc_code="N1")
        resp = api.release_lot(lot["id"], QA_PHARMACIST_HEADERS)
        validate_error(resp, E.ERR_INVALID_STATE, 409)
        lot_after = fixtures.get_lot(api, lot["id"])
        assert lot_after["lot_posture"] == "RELEASABLE"


class TestRevokedSiteTerminal:
    def test_reinstate_revoked_site_rejected(self, api):
        """PRD §3.3: "Either a `QUALIFIED` or a `SUSPENDED` site may be
        permanently moved to the terminal `REVOKED` status; revocation carries
        the same cascade as suspension and additionally cancels every `Shipment`
        to the site that is still in `PACKING`, `AWAITING_CUSTOMS_DOCS`, or
        `READY_TO_DISPATCH`. There is no path out of `REVOKED`."

        Design: Corner/state_machines/site_revoked_is_terminal_no_reinstate
        """
        fixtures.set_clock(api)
        site = fixtures.setup_qualified_site(api)
        get_success_data(api.revoke_site(site["id"], COMPLIANCE_OFFICER_HEADERS))
        resp = api.reinstate_site(site["id"], COMPLIANCE_OFFICER_HEADERS)
        validate_error(resp, E.ERR_INVALID_STATE, 409)
        site_after = fixtures.get_site(api, site["id"])
        assert site_after["qualification_status"] == "REVOKED"


class TestAllocationRequestInitialState:
    def test_new_request_is_submitted_with_zero_approved(self, api):
        """PRD §3.4: "The `requested_by_user_id` is captured from `X-User-ID`. If
        an `emergency_event_id` is supplied, the referenced `EmergencyEvent` must
        exist and must be in `ACTIVE` status for the request to confer emergency
        weighting; otherwise the submission is rejected with
        `ERR_EMERGENCY_NOT_ACTIVE` (HTTP 409). New requests enter in `SUBMITTED`
        status."
        PRD §3.6: "The `need_score` is a weighted sum computed exactly once, at
        the moment a decision is finalized, and persisted on the
        `AllocationRequest`. Later changes to the site or the emergency event do
        not retroactively recompute it."

        Design: Corner/state_machines/allocation_request_initial_state_is_submitted
        """
        fixtures.set_clock(api)
        site = fixtures.setup_qualified_site(api)
        request = fixtures.create_request(api, site["id"], quantity_requested=10, ndc_code="N1")
        assert request["status"] == "SUBMITTED"
        assert request["quantity_approved"] == 0
        assert request.get("need_score") is None, (
            "need_score is computed at finalize time; before that it must be null"
        )
        assert request["requested_by_user_id"] == site["id"]


class TestDeliveryFailureSideEffects:
    def test_mark_failed_moves_lines_to_forfeited_and_units_to_expired(self, api):
        """PRD §3.7: "Alternatively, a `LogisticsCoordinator` may mark a
        `DISPATCHED` shipment as `DELIVERY_FAILED` with an optional `reason`;
        every `SHIPPED` line then transitions to the terminal `FORFEITED` status,
        and each line's quantity is removed from its lot's `quantity_shipped` and
        added to `quantity_expired` — the product is considered spoiled in
        transit."

        Design: Corner/state_machines/shipment_delivery_failure_marks_lines_forfeited_and_moves_quantity_to_expired
        """
        fixtures.set_clock(api)
        world = fixtures.setup_shipped_domestic(api, quantity_requested=10, lot_quantity=100)
        lot = fixtures.get_lot(api, world["lot"]["id"])
        assert lot["quantity_shipped"] == 10
        failed = get_success_data(
            api.mark_delivery_failed(world["shipment"]["id"], LOGISTICS_COORDINATOR_HEADERS)
        )
        assert failed["status"] == "DELIVERY_FAILED"
        lot_after = fixtures.get_lot(api, world["lot"]["id"])
        assert lot_after["quantity_shipped"] == 0
        assert lot_after["quantity_expired"] == 10
        assert lot_after["quantity_available"] == 90
        assert_lot_quantity_conservation(lot_after)
        lines = fixtures.list_lines_for_decision(api, world["decision"]["id"])
        assert all(line["status"] == "FORFEITED" for line in lines)


class TestEmergencyStandDownReleasesModules:
    def test_clock_past_surge_window_stands_down_and_releases_module(self, api):
        """PRD §3.9: "When the logical clock reaches `surge_window_ends_at`, the
        event automatically transitions to `STAND_DOWN`, and every
        `PrepositionedModule` currently `RESERVED` for the event returns to
        `AVAILABLE` with its `reserved_for_event_id` cleared."

        Design: Corner/state_machines/emergency_event_stand_down_releases_reserved_modules
        """
        fixtures.set_clock(api)
        event = fixtures.create_active_event(
            api, event_name="EV", severity=3, affected_country_codes=["HT"],
            surge_window_ends_at="2026-09-10T00:00:00Z",
        )
        module = fixtures.create_module(
            api, module_code="MOD-1", intended_use="PRIMARY_CARE", holding_country_code="HT"
        )
        reserved = get_success_data(
            api.reserve_module(module["id"], {"event_id": event["id"]}, EMERGENCY_MANAGER_HEADERS)
        )
        assert reserved["status"] == "RESERVED"
        fixtures.set_clock(api, "2026-09-11T00:00:00Z")
        event_after = fixtures.get_event(api, event["id"])
        assert event_after["status"] == "STAND_DOWN"
        module_after = fixtures.get_module(api, module["id"])
        assert module_after["status"] == "AVAILABLE"
        assert module_after.get("reserved_for_event_id") is None
