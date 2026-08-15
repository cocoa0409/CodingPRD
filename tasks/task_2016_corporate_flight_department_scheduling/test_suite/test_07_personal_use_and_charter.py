"""Personal-use governance (approval + segregation of duties) and charter
supplementation state rules."""
from test_helpers import (
    ApiErrorId,
    add_leg,
    approve_trip,
    assign_aircraft,
    assign_crew,
    create_charter_for_trip,
    create_trip,
    get_success_data,
    make_dispatcher_headers,
    make_finance_headers,
    reset_clock,
    setup_approved_trip,
    setup_bu_and_passenger,
    setup_crewed_trip,
    setup_fleet_and_crew,
    setup_submitted_trip,
    submit_trip,
    validate_error,
    validate_success,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestPersonalUseGovernance:
    def test_dispatch_without_personal_use_approval_rejected(self, api):
        """PRD §3.5: "First, a `FinanceAdmin` must already have recorded
        personal-use approval on the trip — the approval action sets
        `personal_use_approved_by` to the acting finance administrator's
        `X-User-ID` — and dispatch without that approval is rejected with
        `ERR_PERSONAL_USE_NOT_APPROVED` (HTTP 422)."

        Design: Corner/validations/dispatch_without_personal_use_approval_rejected
        """
        _bu, _pax, trip, _legs, _ac, _pic, _sic = setup_crewed_trip(
            trip_kind="PERSONAL", personal_use_flag=True)
        # Dispatch under a different dispatcher than the assigner so the
        # segregation-of-duties check is satisfied and only the missing
        # personal-use approval can fail.
        resp = api.dispatch_trip(trip["id"], make_dispatcher_headers("disp-2"))
        validate_error(resp, ApiErrorId.ERR_PERSONAL_USE_NOT_APPROVED)

    def test_dispatch_same_dispatcher_as_assign_rejected(self, api):
        """PRD §3.5: "Second, segregation of duties forbids the same operator
        from both assigning and dispatching a personal-use trip: when
        `personal_use_flag` is true, the acting dispatcher's `X-User-ID` must
        differ from the trip's `assigned_by_user_id`, and a violation is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

        Design: Corner/validations/dispatch_segregation_of_duties_violation
        """
        _bu, _pax, trip, _legs, _ac, _pic, _sic = setup_crewed_trip(
            trip_kind="PERSONAL", personal_use_flag=True, dispatcher_id="disp-1")
        get_success_data(
            api.approve_personal_use(trip["id"], make_finance_headers("fin-1")))
        resp = api.dispatch_trip(trip["id"], make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestCharterState:
    def test_accept_charter_on_submitted_trip_rejected(self, api):
        """PRD §3.6: "Acceptance is valid only while the parent trip is
        `APPROVED` and still `UNASSIGNED`; an accept attempted against any other
        combination is rejected with `ERR_CHARTER_STATE_INVALID` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/charter_accept_depends_on_trip_approval_state
        """
        _bu, _pax, trip, _legs = setup_submitted_trip()
        charter = create_charter_for_trip(trip["id"], quoted_cost_cents=500_000)
        resp = api.accept_charter(charter["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CHARTER_STATE_INVALID)

    def test_accept_charter_on_assigned_trip_rejected(self, api):
        """PRD §3.6: "Acceptance is valid only while the parent trip is
        `APPROVED` and still `UNASSIGNED`; an accept attempted against any other
        combination is rejected with `ERR_CHARTER_STATE_INVALID` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/charter_accept_depends_on_trip_approval_state
        """
        reset_clock()
        _ac, _pic, _sic = setup_fleet_and_crew()
        _bu, _pax, trip, _legs = setup_approved_trip()
        assign_aircraft(trip["id"])  # trip now ASSIGNED
        charter = create_charter_for_trip(trip["id"], quoted_cost_cents=500_000)
        resp = api.accept_charter(charter["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CHARTER_STATE_INVALID)
