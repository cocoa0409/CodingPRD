"""Change-of-address forwarding and hold-mail windows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_point,
    create_coa,
    create_hold,
    create_point,
    get_coa,
    get_hold,
    get_point,
    get_success_data,
    make_carrier_headers,
    reset_clock,
    set_clock,
    setup_route_with_active_points,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["csr_headers"]
AMS = TEST_USERS["ams_headers"]

FWD = dict(new_address_line1="99 Palm St", new_city="Tucson", new_state_code="AZ",
           new_zip11="85701000100", move_kind="FAMILY", move_type="TEMPORARY",
           begin_date="2026-09-01", end_date="2026-10-01")


class TestCoaParallelDimensions:

    def test_activation_gated_on_validation_then_axes_independent(self, api):
        """PRD §3.9: "activation — automatic when the logical clock reaches the
        `begin_date`, or forced same-day through an explicit activation action —
        requires the order to be `VERIFIED`; activating an unverified order is
        rejected with `ERR_CROSS_ENTITY_STATE`."
        PRD §3.9: "Validation and forwarding are two independent dimensions."

        Design: Difficulty/cross_entity_state_dependency/coa_activation_gated_on_validation_dimension
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        coa = create_coa(unit_id, point_id, move_type="PERMANENT",
                         move_kind="INDIVIDUAL", end_date=None)
        resp = api.activate_coa_now(unit_id, coa["id"], CSR)
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)
        coa_after = get_coa(unit_id, coa["id"])
        assert coa_after["forwarding_status"] == "PENDING"
        get_success_data(api.verify_coa(unit_id, coa["id"], CSR))
        data = get_success_data(api.activate_coa_now(unit_id, coa["id"], CSR))
        assert data["forwarding_status"] == "ACTIVE"
        assert data["validation_status"] == "VERIFIED"

    def test_suspend_resume_leaves_validation_untouched(self, api):
        """PRD §3.9: "Validation and forwarding are two independent dimensions."
        PRD §3.9: "While `ACTIVE`, an order may be suspended and later resumed".

        Design: Difficulty/non_linear_state_machine/coa_parallel_dimensions_evolve_independently
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        coa = create_coa(unit_id, point_id, **FWD)
        # Verify does not activate.
        get_success_data(api.verify_coa(unit_id, coa["id"], CSR))
        mid = get_coa(unit_id, coa["id"])
        assert mid["validation_status"] == "VERIFIED"
        assert mid["forwarding_status"] == "PENDING"
        get_success_data(api.activate_coa_now(unit_id, coa["id"], CSR))
        suspended = get_success_data(api.suspend_coa(unit_id, coa["id"], CSR))
        assert suspended["forwarding_status"] == "SUSPENDED"
        assert suspended["validation_status"] == "VERIFIED"
        resumed = get_success_data(api.resume_coa(unit_id, coa["id"], CSR))
        assert resumed["forwarding_status"] == "ACTIVE"
        assert resumed["validation_status"] == "VERIFIED"


class TestCoaTemporaryWindow:

    def test_temporary_364_day_window_accepted(self, api):
        """PRD §3.9: "For a temporary move an `end_date` is required, must be
        later than `begin_date`, and may not extend more than 364 days past it".

        Design: Corner/validations/coa_temporary_end_date_window_enforced
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        coa = create_coa(ctx["unit"]["id"], ctx["points"][0]["id"],
                         new_zip11="89501000100", move_kind="FAMILY",
                         move_type="TEMPORARY", begin_date="2026-09-01",
                         end_date="2027-08-31", new_address_line1="1 Far Rd",
                         new_city="Reno", new_state_code="NV")
        assert coa["forwarding_status"] == "PENDING"

    def test_temporary_365_day_window_rejected(self, api):
        """PRD §3.9: "may not extend more than 364 days past it" and "Temporal
        violations are rejected with `ERR_TEMPORAL_WINDOW`."

        Design: Corner/validations/coa_temporary_end_date_window_enforced
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        resp = api.create_coa(
            ctx["unit"]["id"],
            {"old_delivery_point_id": ctx["points"][0]["id"],
             "new_address_line1": "2 Far Rd", "new_city": "Reno",
             "new_state_code": "NV", "new_zip11": "89501000100",
             "move_kind": "FAMILY", "move_type": "TEMPORARY",
             "begin_date": "2026-09-01", "end_date": "2027-09-01"}, CSR)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW)


class TestCoaSupersession:

    def _active_coa_ctx(self, api, unit_id, point_id, **overrides):
        payload = dict(new_address_line1="1 First Rd", new_city="Reno",
                       new_state_code="NV", new_zip11="89501000200",
                       move_kind="FAMILY", move_type="TEMPORARY",
                       begin_date="2026-09-01", end_date="2026-12-01")
        payload.update(overrides)
        coa = create_coa(unit_id, point_id, **payload)
        get_success_data(api.verify_coa(unit_id, coa["id"], CSR))
        get_success_data(api.activate_coa_now(unit_id, coa["id"], CSR))
        return coa

    def test_superseded_coa_auto_cancelled_on_activation(self, api):
        """PRD §3.9: "when the other active order is exactly this order's
        supersession target, activation proceeds and the superseded order is
        automatically cancelled."

        Design: Corner/validations/superseded_coa_auto_cancelled_on_activation
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        coa1 = self._active_coa_ctx(api, unit_id, point_id)
        coa2 = create_coa(unit_id, point_id, new_address_line1="2 Second Rd",
                          new_zip11="85701000200", move_kind="FAMILY",
                          move_type="TEMPORARY", begin_date="2026-09-01",
                          end_date="2026-12-01", supersedes_coa_id=coa1["id"])
        get_success_data(api.verify_coa(unit_id, coa2["id"], CSR))
        data = get_success_data(api.activate_coa_now(unit_id, coa2["id"], CSR))
        assert data["forwarding_status"] == "ACTIVE"
        coa1_after = get_coa(unit_id, coa1["id"])
        assert coa1_after["forwarding_status"] == "CANCELLED"

    def test_overlap_with_unrelated_active_forward_rejected(self, api):
        """PRD §3.9: "no other `ACTIVE` order may exist for the same old point,
        with one exception — when the other active order is exactly this order's
        supersession target, activation proceeds and the superseded order is
        automatically cancelled."
        PRD §3.9: "Any other overlapping active order is rejected with
        `ERR_FORWARD_OVERLAP` (HTTP 409)."

        Design: Corner/validations/coa_overlap_with_unrelated_active_forward_rejected
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        coa1 = self._active_coa_ctx(api, unit_id, point_id,
                                    new_address_line1="1 Alpha Rd",
                                    new_zip11="89501000300")
        coa2 = create_coa(unit_id, point_id, new_address_line1="2 Beta Rd",
                          new_zip11="85701000300", move_kind="INDIVIDUAL",
                          move_type="TEMPORARY", begin_date="2026-09-01",
                          end_date="2026-12-01")
        get_success_data(api.verify_coa(unit_id, coa2["id"], CSR))
        resp = api.activate_coa_now(unit_id, coa2["id"], CSR)
        validate_error(resp, ApiErrorId.ERR_FORWARD_OVERLAP)
        assert get_coa(unit_id, coa2["id"])["forwarding_status"] == "PENDING"
        assert get_coa(unit_id, coa1["id"])["forwarding_status"] == "ACTIVE"


class TestCrossEntityGuards:

    def test_mark_vacant_blocked_by_active_pickup_hold(self, api):
        """PRD §3.4: "A `Carrier` who finds an address empty marks it `OCCUPIED →
        VACANT`, but only when no `ACTIVE` hold with disposition `CARRIER_PICKUP`
        exists for the point — such a hold means the customer picks up at the
        office and the address must not be declared vacant; the conflict is
        rejected with `ERR_HOLD_ACTIVE` (HTTP 409)."

        Design: Corner/validations/mark_vacant_blocked_by_active_pickup_hold
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        create_hold(unit_id, point_id, hold_start_date="2026-09-10",
                    hold_end_date="2026-09-12", disposition="CARRIER_PICKUP")
        set_clock("2026-09-10T00:00:00Z")
        resp = api.mark_vacant(unit_id, point_id,
                               make_carrier_headers(ctx["carrier"]["id"]))
        validate_error(resp, ApiErrorId.ERR_HOLD_ACTIVE)
        point = get_point(unit_id, point_id)
        assert point["occupancy_status"] == "OCCUPIED"

    def test_discontinue_blocked_by_active_forward(self, api):
        """PRD §3.4: "it requires that no `ACTIVE` change-of-address forwards mail
        from the point; an active forwarding order blocks discontinuation with
        `ERR_FORWARD_ACTIVE` (HTTP 409)."

        Design: Corner/validations/discontinue_blocked_by_active_forward
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        coa = create_coa(unit_id, point_id, move_kind="INDIVIDUAL",
                         move_type="PERMANENT", begin_date="2026-09-01",
                         end_date=None, new_address_line1="1 Move St",
                         new_city="Fresno", new_state_code="CA",
                         new_zip11="93701000100")
        get_success_data(api.verify_coa(unit_id, coa["id"], CSR))
        get_success_data(api.activate_coa_now(unit_id, coa["id"], CSR))
        get_success_data(api.mark_vacant(unit_id, point_id,
                                         make_carrier_headers(ctx["carrier"]["id"])))
        set_clock("2026-11-30T00:00:00Z")
        resp = api.discontinue_point(unit_id, point_id, AMS)
        validate_error(resp, ApiErrorId.ERR_FORWARD_ACTIVE)
        point = get_point(unit_id, point_id)
        assert point["occupancy_status"] == "VACANT"


class TestHoldWindows:

    def test_hold_starting_on_incumbent_end_date_collides(self, api):
        """PRD §3.10: "windows are compared as half-open intervals from the start
        date up to but not including the day after the end date, and an
        intersection — whether discovered at creation or at the moment a scheduled
        hold would activate — is rejected with `ERR_HOLD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hold_mail_half_open_overlap_on_shared_point
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        create_hold(unit_id, point_id, hold_start_date="2026-09-10",
                    hold_end_date="2026-09-15",
                    disposition="ACCUMULATE_DELIVER_ON_END")
        resp = api.create_hold(
            unit_id,
            {"delivery_point_id": point_id, "hold_start_date": "2026-09-15",
             "hold_end_date": "2026-09-20",
             "disposition": "ACCUMULATE_DELIVER_ON_END"}, CSR)
        validate_error(resp, ApiErrorId.ERR_HOLD_OVERLAP)

    def test_hold_starting_day_after_incumbent_end_accepted(self, api):
        """PRD §3.10: "windows are compared as half-open intervals from the start
        date up to but not including the day after the end date".

        Design: Difficulty/resource_temporal_overlap/hold_mail_half_open_overlap_on_shared_point
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        create_hold(unit_id, point_id, hold_start_date="2026-09-10",
                    hold_end_date="2026-09-15",
                    disposition="ACCUMULATE_DELIVER_ON_END")
        data = get_success_data(api.create_hold(
            unit_id,
            {"delivery_point_id": point_id, "hold_start_date": "2026-09-16",
             "hold_end_date": "2026-09-20", "disposition": "CARRIER_PICKUP"}, CSR))
        assert data["status"] == "SCHEDULED"

    def test_hold_activates_and_expires_on_clock(self, api):
        """PRD §3.10: "Activation is automatic when the logical clock reaches
        `hold_start_date`, moving `SCHEDULED → ACTIVE`. Expiry is likewise
        automatic once the logical date passes `hold_end_date`, moving `ACTIVE →
        EXPIRED`".

        Design: Corner/state_machines/hold_mail_activates_and_expires_on_clock
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        hold = create_hold(unit_id, point_id, hold_start_date="2026-09-10",
                           hold_end_date="2026-09-12",
                           disposition="ACCUMULATE_DELIVER_ON_END")
        set_clock("2026-09-09T00:00:00Z")
        assert get_hold(unit_id, hold["id"])["status"] == "SCHEDULED"
        set_clock("2026-09-10T00:00:00Z")
        assert get_hold(unit_id, hold["id"])["status"] == "ACTIVE"
        set_clock("2026-09-13T00:00:00Z")
        assert get_hold(unit_id, hold["id"])["status"] == "EXPIRED"

    def test_unset_clock_defaults_to_startup_instant(self, api):
        """PRD §2.4: "Before any test-driving call, the logical clock reads exactly
        `2026-09-01T00:00:00Z` (the startup default)."

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_startup_time
        """
        # Deliberately no set_clock call anywhere in this test.
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        hold = create_hold(unit_id, point_id, hold_start_date="2026-09-02",
                           hold_end_date="2026-09-04",
                           disposition="ACCUMULATE_DELIVER_ON_END")
        assert get_hold(unit_id, hold["id"])["status"] == "SCHEDULED"
