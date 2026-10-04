"""Validation claims: priority pairs, overlap semantics, field constraints."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_company_rep_headers,
    create_booking_payload,
    create_company, create_theatre, create_production, create_booking,
    approve_booking, reset_clock, setup_approved_booking, setup_active_booking,
    TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


def test_state_vs_business_temporal_on_approve(api):
    """PRD §2.5: "Third, state-machine legality of the requested transition
    (`ERR_INVALID_STATE`, HTTP 409). Fourth, union-minimum crew checks where
    they apply (`ERR_UNION_MIN_CREW_VIOLATION`, HTTP 422). Fifth,
    booking-window overlap checks (`ERR_BOOKING_WINDOW_CONFLICT`, HTTP 409)."
    PRD §2.5: "An earlier check always masks a later one — a request that
    fails authorization is never reported as a window conflict, and a window
    conflict is never reported as a fiscal violation."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_approve
    """
    reset_clock()
    comp1 = create_company("P1Co", "p1@x.com")
    comp2 = create_company("P2Co", "p2@x.com")
    house = create_theatre("OverlapHouse")
    prod_a = create_production(comp1["id"], title="Show A")
    prod_b = create_production(comp2["id"], title="Show B")
    bk_a = create_booking(prod_a["id"], house["id"], comp1["id"])
    bk_b = create_booking(prod_b["id"], house["id"], comp2["id"],
                          loadin_start="2026-09-10T00:00:00Z",
                          run_end="2026-11-10T00:00:00Z")
    approve_booking(bk_a["id"])  # cascades bk_b (overlapping REQUESTED) to DECLINED
    assert get_success_data(api_client.get_booking(bk_b["id"], HM))["status"] == "DECLINED"
    resp = api_client.approve_booking(bk_b["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_approve_declined_booking_leaves_state_unchanged(api):
    """PRD §3.2: "`DECLINED`, `WITHDRAWN`, and `DONE` are terminal booking
    states. Attempting a transition from a state that does not allow it —
    approving a `WITHDRAWN` booking, say — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_approve
    """
    reset_clock()
    comp1 = create_company("P1bCo", "p1b@x.com")
    comp2 = create_company("P2bCo", "p2b@x.com")
    house = create_theatre("OverlapHouseB")
    prod_a = create_production(comp1["id"], title="Show AB")
    prod_b = create_production(comp2["id"], title="Show BB")
    bk_a = create_booking(prod_a["id"], house["id"], comp1["id"])
    bk_b = create_booking(prod_b["id"], house["id"], comp2["id"],
                          loadin_start="2026-09-10T00:00:00Z",
                          run_end="2026-11-10T00:00:00Z")
    approve_booking(bk_a["id"])
    resp = api_client.approve_booking(bk_b["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_success_data(api_client.get_booking(bk_b["id"], HM))["status"] == "DECLINED", (
        "a rejected transition must not change the booking's state")


class TestSizeClassVsUnionCrew:
    def test_undersized_house_rejected_with_size_class_mismatch(self, api):
        """PRD §3.2: "The theatre's `size_class` must be at least the
        production's `required_size_class`; otherwise the request is rejected
        with `ERR_SIZE_CLASS_MISMATCH` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_crew
        """
        reset_clock()
        comp = create_company("P3Co", "p3@x.com")
        house = create_theatre("TinyHouse", size_class="SMALL", capacity=300,
                               base_weekly_rent_cents=300000)
        prod = create_production(comp["id"], title="Big Show",
                                 required_size_class="LARGE")
        resp = api_client.create_booking(
            {"production_id": prod["id"], "theatre_id": house["id"],
             "loadin_start": "2026-09-06T00:00:00Z",
             "run_end": "2026-11-01T00:00:00Z"},
            make_company_rep_headers(comp["id"]))
        validate_error(resp, ApiErrorId.ERR_SIZE_CLASS_MISMATCH)

    def test_crew_below_union_minimum_rejected(self, api):
        """PRD §3.4: "The `crew_size` must meet the union minimum for the
        theatre's size class — 4 for `SMALL`, 8 for `MEDIUM`, 14 for `LARGE` —
        or creation is rejected with `ERR_UNION_MIN_CREW_VIOLATION`."

        Design: Corner/validations/crew_below_union_minimum_rejected
        """
        ctx = setup_approved_booking(size_class="MEDIUM", company_name="UnCo",
                                     company_email="un@x.com",
                                     house_name="MidU",
                                     production_title="Show U2")
        resp = api_client.create_crew_assignment(
            ctx["booking"]["id"], {"crew_size": 7}, HM)
        validate_error(resp, ApiErrorId.ERR_UNION_MIN_CREW_VIOLATION)

    def test_crew_at_union_minimum_accepted(self, api):
        """PRD §2.6: "The size class drives the union minimum crew size that
        must be engaged for any production playing the house: 4 crew for a
        `SMALL` house, 8 for a `MEDIUM` house, and 14 for a `LARGE` house.
        Engaging a crew whose `crew_size` is below the union minimum for the
        theatre's size class is rejected with `ERR_UNION_MIN_CREW_VIOLATION`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_crew
        """
        ctx = setup_approved_booking(size_class="MEDIUM", company_name="Un2Co",
                                     company_email="un2@x.com",
                                     house_name="MidU2",
                                     production_title="Show U3")
        data = validate_success(api_client.create_crew_assignment(
            ctx["booking"]["id"], {"crew_size": 8}, HM), expected_status=201)
        assert data["crew_size"] == 8, (
            "crew at exactly the MEDIUM minimum must be accepted — the union "
            "error and the size-class error never swap categories")


class TestBookingWindowOverlap:
    def _setup_incumbent(self, api):
        reset_clock()
        comp1 = create_company("O1Co", "o1@x.com")
        comp2 = create_company("O2Co", "o2@x.com")
        house = create_theatre("OverlapT")
        prod1 = create_production(comp1["id"], title="Incumbent",
                                  required_loadout_hours=48)
        prod2 = create_production(comp2["id"], title="Challenger",
                                  required_loadin_hours=1,
                                  required_loadout_hours=1)
        bk1 = create_booking(prod1["id"], house["id"], comp1["id"],
                             loadin_start="2026-09-06T00:00:00Z",
                             run_end="2026-09-27T00:00:00Z")
        approve_booking(bk1["id"])
        return comp2, house, prod2

    def test_challenger_inside_incumbent_buffer_rejected(self, api):
        """PRD §3.2: "the requested occupancy window — `loadin_start` through
        `run_end` plus the production's load-out buffer — must not overlap any
        `APPROVED` or `ACTIVE` booking on the same theatre, nor any
        `SCHEDULED` capital-project window touching the performance run; an
        overlap is rejected with `ERR_BOOKING_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/theatre_booking_overlap_with_buffers_half_open
        """
        comp2, house, prod2 = self._setup_incumbent(api)
        # incumbent buffer: [09-06, 09-27 + 48h) = [09-06, 09-29); 09-28 inside.
        # PRD §2.4 applies the overlap check at creation ("Two business checks
        # guard creation"), so the conflict surfaces on the create call itself.
        resp = api_client.create_booking(
            create_booking_payload(prod2["id"], house["id"],
                                   loadin_start="2026-09-28T00:00:00Z",
                                   run_end="2026-10-26T00:00:00Z"),
            make_company_rep_headers(comp2["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_CONFLICT)

    def test_challenger_touching_buffer_boundary_approved(self, api):
        """PRD §2.10: "Booking occupancy on a house is modeled as a half-open
        interval that includes both buffers: it begins at `loadin_start` and
        ends at `run_end` plus the production's required load-out hours. Two
        such intervals conflict if they overlap; touching boundaries do not
        constitute an overlap."

        Design: Difficulty/resource_temporal_overlap/theatre_booking_overlap_with_buffers_half_open
        """
        comp2, house, prod2 = self._setup_incumbent(api)
        bk2 = create_booking(prod2["id"], house["id"], comp2["id"],
                             loadin_start="2026-09-29T00:00:00Z",
                             run_end="2026-10-27T00:00:00Z")
        data = validate_success(api_client.approve_booking(bk2["id"], HM))
        assert data["status"] == "APPROVED"


def test_report_week_duplicate_rejected(api):
    """PRD §3.6: "There is exactly one report per booking per `week_start`: a
    duplicate is rejected with `ERR_REPORT_WEEK_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/report_week_duplicate_rejected
    """
    ctx = setup_active_booking()
    from test_helpers import open_report
    open_report(ctx["booking"]["id"], ctx["company"]["id"])
    resp = api_client.create_weekly_gross_report(
        ctx["booking"]["id"], {"week_start": TEST_DEFAULTS["WEEK1_START"]},
        ctx["rep"])
    validate_error(resp, ApiErrorId.ERR_REPORT_WEEK_DUPLICATE)


def test_dynamic_factor_out_of_range_rejected(api):
    """PRD §3.5: "The dynamic-pricing factor defaults to 1.0 and must lie
    within the inclusive range from 0.5 to 2.0; anything outside is rejected
    with `ERR_DYNAMIC_FACTOR_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/validations/dynamic_factor_out_of_range_rejected
    """
    ctx = setup_active_booking()
    resp = api_client.create_ticket_order(
        ctx["booking"]["id"],
        {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 2,
         "is_group_sale": False, "face_value_cents": 5000,
         "dynamic_pricing_factor": 2.01},
        BO)
    validate_error(resp, ApiErrorId.ERR_DYNAMIC_FACTOR_OUT_OF_RANGE)
