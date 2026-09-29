"""Validation corners: site capability, attempt caps, campaign gates and priority order."""
from test_helpers import (
    NON_EXISTENT_UUID,
    PROGRAM_ADMIN,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    campaign_evaluation_payload,
    campaign_payload,
    campaign_status_payload,
    create_and_open_station,
    create_station,
    create_water_body,
    enroll_inspector,
    fetch_campaign,
    fetch_decon_order,
    fetch_record,
    fetch_station,
    inspection_record_payload,
    make_decon_technician_headers,
    make_inspector_headers,
    move_campaign,
    move_station,
    plan_campaign,
    register_watercraft,
    set_clock,
    setup_decon_order,
    treat_order,
    treatment_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_dry,
)

ARRIVAL = "2026-08-05T09:00:00Z"
WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-31T00:00:00Z"


class TestTreatmentRequiresAHotWaterStation:
    """The site capability gate follows the technician's certification gate."""

    def test_a_certified_technician_is_still_refused_at_a_cold_station(self):
        """hot_water_capable false is a 409 and the order never leaves ORDERED.

        PRD: "The station must be equipped — `hot_water_capable` true and
        `decon_bay_count` of at least 1 — or the call fails with
        `ERR_STATION_NOT_HOT_WATER_CAPABLE`."

        Design: Corner/validations/violation_to_error_treatment_at_a_station_without_hot_water_rejected
        """
        ctx = setup_decon_order(
            hot_water_capable=False, decon_bay_count=1, arrived_at=ARRIVAL,
            screen_at=ARRIVAL,
        )
        assert ctx["station"]["hot_water_capable"] is False
        assert ctx["inspector_b"]["certification_level"] == "DECON_CERTIFIED"
        assert ctx["inspector_b"]["decon_endorsement"] is True
        order = ctx["decon_order"]
        set_clock(ARRIVAL)

        response = api_client.treat_decon_order(
            order["id"], treatment_payload(140, 3000, 120),
            make_decon_technician_headers(ctx["inspector_b"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_STATION_NOT_HOT_WATER_CAPABLE, 409)
        after = fetch_decon_order(order["id"])
        assert after["status"] == "ORDERED"
        assert after["attempt_count"] == 0
        assert after["treated_by_inspector_id"] is None
        assert after["dry_until"] is None
        assert after["version"] == order["version"]

    def test_the_cold_station_books_no_treatment_charge(self):
        """The record keeps its inspection fee alone and the ledger matches.

        PRD: "Four site and parameter gates apply before anything is written."

        Design: Corner/validations/violation_to_error_treatment_at_a_station_without_hot_water_rejected
        """
        ctx = setup_decon_order(
            hot_water_capable=False, decon_bay_count=1, arrived_at=ARRIVAL,
            screen_at=ARRIVAL,
        )
        set_clock(ARRIVAL)

        api_client.treat_decon_order(
            ctx["decon_order"]["id"], treatment_payload(140, 3000, 120),
            make_decon_technician_headers(ctx["inspector_b"]["id"]),
        )

        record = fetch_record(ctx["record"]["id"])
        assert record["decon_fee_cents"] == 0
        assert record["total_fee_cents"] == 2500
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 2500


def _order_after_three_retreats():
    """Treat and retreat the same order three times, leaving attempt_count at 3."""
    ctx = setup_decon_order(
        decon_bay_count=2, arrived_at=ARRIVAL, screen_at=ARRIVAL
    )
    order_id = ctx["decon_order"]["id"]
    schedule = [
        (ARRIVAL, "2026-08-06T03:02:00Z", "2026-08-06T04:00:00Z"),
        ("2026-08-06T04:00:00Z", "2026-08-06T22:02:00Z", "2026-08-06T23:00:00Z"),
        ("2026-08-06T23:00:00Z", "2026-08-07T17:02:00Z", "2026-08-07T18:00:00Z"),
    ]
    for treat_at, dry_until, retreat_at in schedule:
        set_clock(treat_at)
        treated = treat_order(order_id, ctx["inspector_b"]["id"], 140, 3000, 120)
        assert treated["status"] == "TREATED"
        assert treated["required_dry_hours"] == 18
        assert_instant_equals(treated["dry_until"], dry_until, "dry_until")
        set_clock(retreat_at)
        ctx["decon_order"] = verify_dry(order_id, ctx["inspector_c"]["id"], "RETREAT")
    return ctx


class TestFourthTreatmentOnTheSameOrderIsRefused:
    """attempt_count is monotonic across the retreat loop and the cap ends it."""

    def test_the_fourth_treatment_is_refused_once_three_attempts_are_spent(self):
        """attempt_count 3 makes the next treatment a 409 and freezes the order.

        PRD: "`attempt_count` is monotonic across the whole cycle, and the cap is
        what terminates it: an order may be treated at most 3 times, so a fourth
        treatment on the same order is rejected with `ERR_DECON_ATTEMPTS_EXHAUSTED`
        while the order remains in `RETREAT_REQUIRED`."

        Design: Corner/validations/violation_to_error_fourth_treatment_on_the_same_order_rejected
        """
        ctx = _order_after_three_retreats()
        exhausted = ctx["decon_order"]
        assert exhausted["status"] == "RETREAT_REQUIRED"
        assert exhausted["attempt_count"] == 3

        response = api_client.treat_decon_order(
            exhausted["id"], treatment_payload(140, 3000, 120),
            make_decon_technician_headers(ctx["inspector_b"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DECON_ATTEMPTS_EXHAUSTED, 409)
        after = fetch_decon_order(exhausted["id"])
        assert after["status"] == "RETREAT_REQUIRED"
        assert after["attempt_count"] == 3
        assert after["version"] == exhausted["version"]

    def test_three_treatments_billed_one_decontamination_component(self):
        """Each treatment overwrote the same 900-cent component instead of accumulating.

        PRD: "The fee calculation of §3.5 is re-run on the parent record with the
        `dwell_seconds` just recorded, overwriting `decon_fee_cents`,
        `surcharge_cents` and `total_fee_cents`, and the station's
        `collected_fees_cents` is adjusted by the resulting delta."

        Design: Corner/validations/violation_to_error_fourth_treatment_on_the_same_order_rejected
        """
        ctx = _order_after_three_retreats()

        record = fetch_record(ctx["record"]["id"])

        assert record["inspection_status"] == "DECON_REQUIRED"
        assert record["decon_fee_cents"] == 900
        assert record["total_fee_cents"] == 3400
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 3400


class TestCampaignLaunchNeedsACandidateStation:
    """Closed stations never qualify, and a station elsewhere does not rescue a launch."""

    def test_a_target_guarded_only_by_a_closed_station_cannot_launch(self):
        """The empty candidate set is a 422 and no money is committed anywhere.

        PRD: "The candidate stations are exactly those whose `water_body_id`
        equals the campaign's `target_water_body_id` and whose `status` is
        `PLANNED`, `OPEN` or `SUSPENDED`; closed stations never qualify. If no
        station qualifies, the launch is rejected with
        `ERR_NO_STATIONS_FOR_CAMPAIGN`, and if the budget is too small to give
        every qualifying station at least one cent, it is rejected with
        `ERR_CAMPAIGN_BUDGET_EXCEEDED`."

        Design: Corner/validations/violation_to_error_campaign_launch_without_candidate_stations_rejected
        """
        set_clock(WINDOW_START)
        target = create_water_body(name="Flathead Lake", risk_tier="HIGH")
        elsewhere = create_water_body(name="Nilan Reservoir", risk_tier="LOW")
        closed = create_and_open_station(
            water_body_id=target["id"], name="Polson Access"
        )
        closed = move_station(closed["id"], "CLOSED")
        unrelated = create_and_open_station(
            water_body_id=elsewhere["id"], name="Nilan Access"
        )
        campaign = plan_campaign(target["id"], WINDOW_START, WINDOW_END, 100000)

        response = api_client.set_campaign_status(
            campaign["id"], campaign_status_payload("RUNNING"), PROGRAM_ADMIN
        )

        validate_error(response, ApiErrorId.ERR_NO_STATIONS_FOR_CAMPAIGN, 422)
        after = fetch_campaign(campaign["id"])
        assert after["status"] == "PLANNED"
        assert after["station_allocations"] == []
        assert after["version"] == campaign["version"]
        assert fetch_station(closed["id"])["campaign_allocated_cents"] == 0
        assert fetch_station(unrelated["id"])["campaign_allocated_cents"] == 0

    def test_a_merely_planned_station_does_qualify(self):
        """A never-opened station absorbs the whole budget, so only CLOSED is excluded.

        PRD: "The candidate stations are exactly those whose `water_body_id`
        equals the campaign's `target_water_body_id` and whose `status` is
        `PLANNED`, `OPEN` or `SUSPENDED`; closed stations never qualify."

        Design: Corner/validations/violation_to_error_campaign_launch_without_candidate_stations_rejected
        """
        set_clock(WINDOW_START)
        target = create_water_body(name="Nilan Reservoir", risk_tier="LOW")
        planned = create_station(name="Nilan Access", water_body_id=target["id"])
        assert planned["status"] == "PLANNED"
        campaign = plan_campaign(target["id"], WINDOW_START, WINDOW_END, 100000)

        data = validate_success(
            api_client.set_campaign_status(
                campaign["id"], campaign_status_payload("RUNNING"), PROGRAM_ADMIN
            ),
            200,
        )

        assert data["status"] == "RUNNING"
        assert len(data["station_allocations"]) == 1
        assert data["station_allocations"][0]["station_id"] == planned["id"]
        assert data["station_allocations"][0]["allocated_cents"] == 100000
        assert fetch_station(planned["id"])["campaign_allocated_cents"] == 100000


def _two_open_stations_on_one_water_body():
    """Two OPEN candidates guarding the same target, both weighing 1."""
    set_clock(WINDOW_START)
    target = create_water_body(name="Nilan Reservoir", risk_tier="LOW")
    first = create_and_open_station(water_body_id=target["id"], name="Alpha Access")
    second = create_and_open_station(water_body_id=target["id"], name="Bravo Access")
    return target, first, second


class TestCampaignBudgetTooSmallForEveryStation:
    """The budget rule is guarded at both ends by the same error."""

    def test_one_cent_across_two_candidates_cannot_launch(self):
        """A budget that cannot give every candidate a cent is a 422.

        PRD: "if the budget is too small to give every qualifying station at least
        one cent, it is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED`."

        Design: Corner/validations/violation_to_error_campaign_budget_too_small_for_every_station_rejected
        """
        target, first, second = _two_open_stations_on_one_water_body()
        campaign = plan_campaign(target["id"], WINDOW_START, WINDOW_END, 1)
        assert campaign["budget_cents"] == 1
        assert campaign["status"] == "PLANNED"

        response = api_client.set_campaign_status(
            campaign["id"], campaign_status_payload("RUNNING"), PROGRAM_ADMIN
        )

        validate_error(response, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED, 422)
        after = fetch_campaign(campaign["id"])
        assert after["status"] == "PLANNED"
        assert after["station_allocations"] == []
        assert after["version"] == campaign["version"]
        assert fetch_station(first["id"])["campaign_allocated_cents"] == 0
        assert fetch_station(second["id"])["campaign_allocated_cents"] == 0

    def test_two_cents_across_two_candidates_launch_one_cent_each(self):
        """The smallest launchable budget splits exactly and sums to the budget.

        PRD: "Because the remainder is always at least zero and always smaller
        than the number of candidates, the resulting allocations sum to exactly
        `budget_cents`."

        Design: Corner/validations/violation_to_error_campaign_budget_too_small_for_every_station_rejected
        """
        target, first, second = _two_open_stations_on_one_water_body()
        campaign = plan_campaign(target["id"], WINDOW_START, WINDOW_END, 2)

        data = validate_success(
            api_client.set_campaign_status(
                campaign["id"], campaign_status_payload("RUNNING"), PROGRAM_ADMIN
            ),
            200,
        )

        assert data["status"] == "RUNNING"
        allocations = {row["station_id"]: row["allocated_cents"]
                       for row in data["station_allocations"]}
        assert allocations == {first["id"]: 1, second["id"]: 1}
        assert sum(allocations.values()) == 2
        assert fetch_station(first["id"])["campaign_allocated_cents"] == 1
        assert fetch_station(second["id"])["campaign_allocated_cents"] == 1

    def test_a_budget_above_the_program_cap_is_refused_at_creation(self):
        """5,000,001 cents is refused before a campaign row ever exists.

        PRD: "The budget must be greater than zero and must not exceed the program
        cap of 5,000,000 cents — fifty thousand dollars per campaign — and a budget
        over the cap is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED`."

        Design: Corner/validations/violation_to_error_campaign_budget_too_small_for_every_station_rejected
        """
        target, _first, _second = _two_open_stations_on_one_water_body()

        response = api_client.create_campaign(
            campaign_payload(target["id"], WINDOW_START, WINDOW_END, 5000001),
            PROGRAM_ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED, 422)
        _rows, meta = validate_paginated(api_client.list_campaigns(PROGRAM_ADMIN))
        assert meta["total_count"] == 0


def _running_campaign_with_no_inspections():
    """A launched campaign whose target saw no boats at all."""
    set_clock(WINDOW_START)
    target = create_water_body(name="Nilan Reservoir", risk_tier="LOW")
    station = create_and_open_station(water_body_id=target["id"], name="Nilan Access")
    campaign = plan_campaign(target["id"], WINDOW_START, WINDOW_END, 100000)
    running = move_campaign(campaign["id"], "RUNNING")
    return {"water_body": target, "station": station, "campaign": running}


class TestEvaluationWithAnEmptyDenominator:
    """An empty target denominator is a hard rejection, never a score of zero."""

    def test_a_closed_window_with_no_dispositioned_record_is_refused(self):
        """The evaluation is a 422 and the campaign keeps both scores null.

        PRD: "An empty denominator here is a hard rejection rather than a score of
        zero: `ERR_NO_INSPECTIONS_IN_WINDOW`."

        Design: Corner/validations/violation_to_error_evaluation_with_an_empty_denominator_rejected
        """
        ctx = _running_campaign_with_no_inspections()
        campaign = ctx["campaign"]
        assert len(campaign["station_allocations"]) == 1
        assert campaign["station_allocations"][0]["allocated_cents"] == 100000
        set_clock("2026-09-01T00:00:00Z")

        response = api_client.evaluate_campaign(
            campaign["id"], campaign_evaluation_payload(impressions=5000), PROGRAM_ADMIN
        )

        validate_error(response, ApiErrorId.ERR_NO_INSPECTIONS_IN_WINDOW, 422)
        after = fetch_campaign(campaign["id"])
        assert after["status"] == "RUNNING"
        assert after["effectiveness_score"] is None
        assert after["alternate_effectiveness_score"] is None
        assert after["window_compliance_rate"] is None
        assert after["version"] == campaign["version"]

    def test_the_failed_evaluation_leaves_the_allocations_alone(self):
        """The station keeps its committed cents after the rejection.

        PRD: "`RUNNING → CANCELLED` is the compensating action for the launch: it
        subtracts from each station's `campaign_allocated_cents` exactly the
        `allocated_cents` recorded for that station in `station_allocations`, sets
        `station_allocations` back to the empty array, advances the `version` of
        every de-allocated station by 1, and advances the campaign's `version` by
        1."

        Design: Corner/validations/violation_to_error_evaluation_with_an_empty_denominator_rejected
        """
        ctx = _running_campaign_with_no_inspections()
        set_clock("2026-09-01T00:00:00Z")

        api_client.evaluate_campaign(
            ctx["campaign"]["id"], campaign_evaluation_payload(), PROGRAM_ADMIN
        )

        assert fetch_station(ctx["station"]["id"])["campaign_allocated_cents"] == 100000


class TestEvaluationWindowIsCheckedBeforeTheDenominator:
    """Two rules are violated at once and the temporal one is announced."""

    def test_a_mid_window_evaluation_names_the_window_not_the_denominator(self):
        """Inside the window the answer is the 409, never the 422.

        PRD: "**Evaluation** closes the loop, and it is available only once the
        window has closed: the current logical time must have reached or passed
        `end_at`, or the call is rejected with `ERR_EVALUATION_WINDOW_NOT_ENDED`."

        Design: Corner/validations/priority_ordering_evaluation_window_checked_before_the_denominator
        """
        ctx = _running_campaign_with_no_inspections()
        set_clock("2026-08-15T00:00:00Z")

        response = api_client.evaluate_campaign(
            ctx["campaign"]["id"], campaign_evaluation_payload(), PROGRAM_ADMIN
        )

        validate_error(response, ApiErrorId.ERR_EVALUATION_WINDOW_NOT_ENDED, 409)
        after = fetch_campaign(ctx["campaign"]["id"])
        assert after["status"] == "RUNNING"
        assert after["version"] == ctx["campaign"]["version"]

    def test_at_exactly_end_at_the_denominator_rule_takes_over(self):
        """The identical call at end_at reveals the lower-priority 422.

        PRD: "33. The campaign's evaluation window has ended — otherwise
        `ERR_EVALUATION_WINDOW_NOT_ENDED` (409). Applies to campaign evaluation."

        Design: Corner/validations/priority_ordering_evaluation_window_checked_before_the_denominator
        """
        ctx = _running_campaign_with_no_inspections()
        set_clock(WINDOW_END)

        response = api_client.evaluate_campaign(
            ctx["campaign"]["id"], campaign_evaluation_payload(), PROGRAM_ADMIN
        )

        validate_error(response, ApiErrorId.ERR_NO_INSPECTIONS_IN_WINDOW, 422)
        assert fetch_campaign(ctx["campaign"]["id"])["status"] == "RUNNING"


def _inspector_and_vessel_without_a_station():
    """An ACTIVE inspector and a registered vessel, plus one unrelated station."""
    set_clock(WINDOW_START)
    water_body = create_water_body(name="Flathead Lake", risk_tier="HIGH")
    station = create_and_open_station(
        water_body_id=water_body["id"], name="Polson Access"
    )
    inspector = enroll_inspector(
        station["id"], credited_hours=8, completed_at=WINDOW_START
    )
    assert inspector["status"] == "ACTIVE"
    vessel = register_watercraft(last_water_body_id=water_body["id"])
    set_clock(ARRIVAL)
    return inspector, vessel


class TestStructuralSoundnessPrecedesForeignKeyLookup:
    """A body that is both malformed and points nowhere is answered as malformed."""

    def test_a_missing_arrived_at_wins_over_an_unknown_station_id(self):
        """The 400 is announced and no record row is written.

        PRD: "6. On every creating or modifying operation, the body is
        structurally sound — otherwise `ERR_INVALID_REQUEST` (400). Every required
        field is present; every supplied value matches its declared type and, for
        enumerated fields, is one of the declared members; and every numeric and
        ordering constraint holds."

        Design: Corner/validations/priority_ordering_type_check_precedes_foreign_key_existence
        """
        inspector, vessel = _inspector_and_vessel_without_a_station()

        response = api_client.create_inspection_record(
            {"station_id": NON_EXISTENT_UUID, "watercraft_id": vessel["id"]},
            make_inspector_headers(inspector["id"]),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        _rows, meta = validate_paginated(
            api_client.list_inspection_records(make_inspector_headers(inspector["id"]))
        )
        assert meta["total_count"] == 0

    def test_a_well_formed_body_then_reveals_the_foreign_key_miss(self):
        """Supplying arrived_at lets priority 8 fire with a 404.

        PRD: "8. Every foreign key supplied in the body exists — otherwise the
        matching 404 from the same family."

        Design: Corner/validations/priority_ordering_type_check_precedes_foreign_key_existence
        """
        inspector, vessel = _inspector_and_vessel_without_a_station()

        response = api_client.create_inspection_record(
            inspection_record_payload(NON_EXISTENT_UUID, vessel["id"], ARRIVAL),
            make_inspector_headers(inspector["id"]),
        )

        validate_error(response, ApiErrorId.ERR_STATION_NOT_FOUND, 404)
        _rows, meta = validate_paginated(
            api_client.list_inspection_records(make_inspector_headers(inspector["id"]))
        )
        assert meta["total_count"] == 0


def _two_water_bodies_to_list():
    """Two rows so a successful listing has something to page over."""
    set_clock(WINDOW_START)
    create_water_body(name="Flathead Lake", risk_tier="HIGH")
    create_water_body(name="Nilan Reservoir", risk_tier="LOW",
                      water_body_class="RESERVOIR")


class TestPaginationWindowIsClosedAtOneHundred:
    """The accepted window is limit 1 through 100 with a non-negative offset."""

    def test_a_limit_of_one_hundred_and_one_is_refused(self):
        """101 falls outside the inclusive range and is a 400.

        PRD: "A `limit` that is not an integer or falls outside the range 1
        through 100 inclusive, or an `offset` that is not an integer or is
        negative, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/violation_to_error_limit_above_one_hundred_rejected
        """
        _two_water_bodies_to_list()

        response = api_client.list_water_bodies(
            PROGRAM_ADMIN, params={"limit": 101, "offset": 0}
        )

        validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION, 400)

    def test_a_limit_of_exactly_one_hundred_is_accepted(self):
        """100 is the top of the window, so the page comes back whole.

        PRD: "`limit` controls page size: it defaults to 10 when omitted, its
        minimum accepted value is 1, and its maximum accepted value is 100."

        Design: Corner/validations/violation_to_error_limit_above_one_hundred_rejected
        """
        _two_water_bodies_to_list()

        rows, meta = validate_paginated(
            api_client.list_water_bodies(PROGRAM_ADMIN,
                                         params={"limit": 100, "offset": 0})
        )

        assert len(rows) == 2
        assert meta["total_count"] == 2
        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["has_more"] is False

    def test_a_limit_of_zero_and_a_negative_offset_are_both_refused(self):
        """Both ends of the window are guarded by the same error.

        PRD: "`offset` controls the starting position: it defaults to 0 and its
        minimum accepted value is 0."

        Design: Corner/validations/violation_to_error_limit_above_one_hundred_rejected
        """
        _two_water_bodies_to_list()

        validate_error(
            api_client.list_water_bodies(PROGRAM_ADMIN, params={"limit": 0}),
            ApiErrorId.ERR_INVALID_PAGINATION, 400,
        )
        validate_error(
            api_client.list_water_bodies(PROGRAM_ADMIN,
                                         params={"limit": 10, "offset": -1}),
            ApiErrorId.ERR_INVALID_PAGINATION, 400,
        )

    def test_the_rule_is_not_specific_to_water_bodies(self):
        """The station listing rejects the same over-wide page.

        PRD: "5. On every collection listing, `limit` is an integer from 1 through
        100 and `offset` is an integer of at least 0 — otherwise
        `ERR_INVALID_PAGINATION` (400)."

        Design: Corner/validations/violation_to_error_limit_above_one_hundred_rejected
        """
        _two_water_bodies_to_list()

        response = api_client.list_stations(PROGRAM_ADMIN, params={"limit": 101})

        validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION, 400)


def _station_open_for_one_day():
    """A station whose only window is [2026-08-05T08:00:00Z, 2026-08-05T17:00:00Z)."""
    set_clock(WINDOW_START)
    water_body = create_water_body(name="Flathead Lake", risk_tier="HIGH")
    station = create_and_open_station(
        water_body_id=water_body["id"], name="Polson Access",
        mandatory_inspection=True,
        opens_at="2026-08-05T08:00:00Z", closes_at="2026-08-05T17:00:00Z",
        staffing_level="SINGLE",
    )
    inspector = enroll_inspector(
        station["id"], credited_hours=8, completed_at=WINDOW_START
    )
    first = register_watercraft(last_water_body_id=water_body["id"])
    second = register_watercraft(last_water_body_id=water_body["id"])
    return station, inspector, first, second


class TestArrivalExactlyAtOpensAtIsInsideTheWindow:
    """The operating window is half-open, so only the closing instant is outside."""

    def test_an_arrival_stamped_exactly_at_opens_at_opens_a_record(self):
        """08:00:00Z is inside, so the record is created INITIATED.

        PRD: "And `arrived_at` must fall inside at least one of the station's
        declared operating windows, evaluated as the half-open interval from
        `opens_at` up to but not including `closes_at`: an arrival at exactly
        `opens_at` is inside the window, an arrival at exactly `closes_at` is not,
        and a station that has declared no windows at all rejects every arrival."

        Design: Corner/validations/satisfaction_to_pass_arrival_exactly_at_opens_at_is_inside_the_window
        """
        station, inspector, vessel, _spare = _station_open_for_one_day()
        set_clock("2026-08-05T08:00:00Z")

        record = validate_success(
            api_client.create_inspection_record(
                inspection_record_payload(
                    station["id"], vessel["id"], "2026-08-05T08:00:00Z"
                ),
                make_inspector_headers(inspector["id"]),
            ),
            201,
        )

        assert record["inspection_status"] == "INITIATED"
        assert record["enforcement_status"] == "NONE"
        assert_instant_equals(
            record["arrived_at"], "2026-08-05T08:00:00Z", "arrived_at"
        )

    def test_an_arrival_stamped_exactly_at_closes_at_is_refused(self):
        """17:00:00Z is the excluded end of the half-open interval.

        PRD: "30. The arrival instant falls within one of the station's operating
        windows — otherwise `ERR_STATION_OUTSIDE_OPERATING_HOURS` (409). Applies
        to record creation."

        Design: Corner/validations/satisfaction_to_pass_arrival_exactly_at_opens_at_is_inside_the_window
        """
        station, inspector, _first, vessel = _station_open_for_one_day()
        set_clock("2026-08-05T17:00:00Z")

        response = api_client.create_inspection_record(
            inspection_record_payload(
                station["id"], vessel["id"], "2026-08-05T17:00:00Z"
            ),
            make_inspector_headers(inspector["id"]),
        )

        validate_error(response, ApiErrorId.ERR_STATION_OUTSIDE_OPERATING_HOURS, 409)
        _rows, meta = validate_paginated(
            api_client.list_inspection_records(make_inspector_headers(inspector["id"]))
        )
        assert meta["total_count"] == 0

    def test_one_second_before_closing_is_still_inside_the_window(self):
        """16:59:59Z is accepted, so only the closing instant itself is outside.

        PRD: "an arrival at exactly `opens_at` is inside the window, an arrival at
        exactly `closes_at` is not"

        Design: Corner/validations/satisfaction_to_pass_arrival_exactly_at_opens_at_is_inside_the_window
        """
        station, inspector, first, second = _station_open_for_one_day()
        set_clock("2026-08-05T08:00:00Z")
        validate_success(
            api_client.create_inspection_record(
                inspection_record_payload(
                    station["id"], first["id"], "2026-08-05T08:00:00Z"
                ),
                make_inspector_headers(inspector["id"]),
            ),
            201,
        )
        set_clock("2026-08-05T16:59:59Z")

        record = validate_success(
            api_client.create_inspection_record(
                inspection_record_payload(
                    station["id"], second["id"], "2026-08-05T16:59:59Z"
                ),
                make_inspector_headers(inspector["id"]),
            ),
            201,
        )

        assert record["inspection_status"] == "INITIATED"
        _rows, meta = validate_paginated(
            api_client.list_inspection_records(make_inspector_headers(inspector["id"]))
        )
        assert meta["total_count"] == 2
