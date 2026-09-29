"""
Endpoint breadth: the three contracts one list endpoint carries at once, the
three-way reverse lookup around a video feed, the clock endpoint's inline sweep
counters and its refusal to rewind, and the cost close as the only lift out of
RESTRICTED.
"""

from test_helpers import (
    HTTP_BAD_REQUEST,
    ObservationApiClient,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_envelope_meta,
    assert_fields,
    assert_row_count,
    exactly_one,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    COST_POSTED,
    ENTRY_KIND_PROVISIONAL,
    ERR_INVALID_REQUEST,
    FEED_ACTIVE,
    MODALITY_VIDEO_MONITORING,
    ORDER_LAPSED,
    ORDER_REASSESSMENT_DUE,
    PATIENT_ADMITTED,
    PATIENT_DISCHARGED,
    POOL_INTERNAL_FLOAT,
    RESTRICTION_BUDGET_THRESHOLD_REACHED,
    RESTRICTION_OBSERVATION_ORDER_LAPSED,
    RISK_FALL,
    STAFF_ON_ASSIGNMENT,
    STATION_ACTIVE_MONITORING,
    STATION_IDLE,
    UNIT_OPEN,
    UNIT_RESTRICTED,
)
from test_helpers.factories import clock_payload, cost_close_payload
from test_helpers.fixtures import (
    advance_clock,
    make_assignment,
    make_feed,
    make_order,
    make_patient,
    make_staff,
    make_station,
    make_unit,
    order_feeds,
    read_feed,
    read_order,
    read_staff,
    read_unit,
    station_feeds,
    unit_cost_entries,
)
from test_helpers.test_users import ADMIN, COORDINATOR, MANAGER

CERT_VALID = "2027-01-01T00:00:00Z"


class TestUnitPatientListing:
    """One list endpoint carrying a page window, a status filter and declared bounds."""

    def test_the_unit_patient_list_pages_filters_and_refuses_out_of_range_windows(
        self, api: ObservationApiClient
    ) -> None:
        """
        Two pages cover three admitted-or-discharged patients exactly once each, the
        status filter narrows `total_count` and not merely the page, the defaults are
        echoed when nothing is asked for, and each of the three declared bounds is a
        shape rejection rather than a silently clamped success.

        PRD 2.3: "The `limit` parameter caps how many items come back: it defaults to 10
        when omitted, its minimum accepted value is 1 and its maximum accepted value is
        100."
        PRD 2.3: "The `offset` parameter says how many items to skip and defaults to 0."
        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope, alongside `api_request_id` and
        `api_request_timestamp`."
        PRD 2.3: "Beyond paging, list endpoints accept optional filters drawn from the
        fields of the resource being listed, and a filter is applied before paging."
        PRD 2.3: "Units, patients, orders, cost entries, feeds, stations, safety events and
        staff can all be narrowed by `status`."
        PRD 2.6: "Request-body shape: every required input field present, every enumerated
        value a declared member, every integer inside its declared range, every array
        non-empty and duplicate-free where declared so, every ISO 8601 instant parseable —
        `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/unit_patient_list_pages_filters_and_rejects_bad_windows
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C34",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirtyfour",
        )
        admitted = [
            make_patient(
                api, unit["id"], mrn=mrn, full_name=full_name, age_years=60
            )["id"]
            for mrn, full_name in (
                ("MRN-C3401", "Page Patient One"),
                ("MRN-C3402", "Page Patient Two"),
            )
        ]
        discharged = make_patient(
            api,
            unit["id"],
            mrn="MRN-C3403",
            full_name="Page Patient Three",
            age_years=60,
        )
        validate_success(api.discharge_patient(discharged["id"], MANAGER))
        everyone = set(admitted) | {discharged["id"]}

        first_response = api.list_unit_patients(unit["id"], COORDINATOR, {"limit": 2, "offset": 0})
        assert first_response.json()["response_type"] == "array"
        first_rows, first_meta = validate_paginated(first_response)
        assert_row_count(first_rows, 2, "rows on the first page")
        assert_fields(
            first_meta,
            label="first page meta",
            limit=2,
            offset=0,
            total_count=3,
            has_more=True,
        )

        second_rows, second_meta = validate_paginated(
            api.list_unit_patients(unit["id"], COORDINATOR, {"limit": 2, "offset": 2})
        )
        assert_row_count(second_rows, 1, "rows on the second page")
        assert_fields(
            second_meta,
            label="second page meta",
            limit=2,
            offset=2,
            total_count=3,
            has_more=False,
        )
        served = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
        assert len(served) == len(set(served)), f"a patient was served twice: {served}"
        assert set(served) == everyone, "the two pages must cover the whole unit"

        filtered_rows, filtered_meta = validate_paginated(
            api.list_unit_patients(unit["id"], COORDINATOR, {"status": PATIENT_DISCHARGED})
        )
        assert_row_count(filtered_rows, 1, "discharged patients")
        assert_fields(
            filtered_rows[0],
            label="the only discharged patient",
            id=discharged["id"],
            status=PATIENT_DISCHARGED,
        )
        assert_fields(
            filtered_meta,
            label="filtered meta",
            total_count=1,
            has_more=False,
        )

        default_response = api.list_unit_patients(unit["id"], COORDINATOR)
        default_rows, default_meta = validate_paginated(default_response)
        assert_row_count(default_rows, 3, "rows under the default page window")
        assert_fields(default_meta, label="default meta", limit=10, offset=0, total_count=3)
        assert_envelope_meta(default_response.json())
        admitted_rows = [row for row in default_rows if row["status"] == PATIENT_ADMITTED]
        assert_row_count(admitted_rows, 2, "still-admitted patients")

        for params, label in (
            ({"limit": 0}, "limit below the declared minimum"),
            ({"limit": 101}, "limit above the declared maximum"),
            ({"offset": -1}, "negative offset"),
        ):
            rejection = api.list_unit_patients(unit["id"], COORDINATOR, params)
            validate_error(rejection, ERR_INVALID_REQUEST, HTTP_BAD_REQUEST)
            assert_envelope_meta(rejection.json())
            assert rejection.json()["response_type"] == "error", label


class TestFeedReverseLookups:
    """One feed reachable from the observer, the console and the order alike."""

    def test_a_single_feed_is_reachable_from_the_console_and_the_order_side(
        self, api: ObservationApiClient
    ) -> None:
        """
        One observer staffs two consoles and admits exactly one feed onto the first, so
        the observer's console list carries both consoles in different postures, the feed
        appears on the first console's list and on its order's list, and the second
        console shares nothing with the first.

        PRD 3.7: "A new console opens in `status` `IDLE` with `active_feed_count` at 0,
        `active_acuity_weight` at 0.0, `effective_span_limit` equal to `declared_max_span`,
        and `offlined_at` null."
        PRD 3.7: "Each feed freezes an `acuity_weight` at the moment it is admitted, computed
        from the risk categories of the order it serves: a `FALL` criterion contributes 1.0,
        an `ELOPEMENT` criterion contributes 2.0, and a `SELF_HARM` criterion contributes
        3.0, with the sum rounded half up to one decimal place."
        PRD 3.7: "A console's `active_acuity_weight` is the sum of `acuity_weight` across the
        feeds on it whose `status` is `ACTIVE`, again to one decimal place; released feeds are
        excluded, which is precisely what lets the console's capacity recover after a
        release."
        PRD 3.7: "From that weight a penalty is derived over inclusive thresholds: a weight of
        6.0 or higher costs 2 slots, a weight below 6.0 but 4.0 or higher costs 1 slot, and
        anything below 4.0 costs nothing."
        PRD 3.7: "An admitted feed opens in `status` `ACTIVE` with `release_reason` and
        `released_at` null."
        PRD 3.7: "On the first admitted feed the console transitions `IDLE →
        ACTIVE_MONITORING` and its observer moves `AVAILABLE → ON_ASSIGNMENT`; an observer who
        is already `ON_ASSIGNMENT` simply stays there."
        PRD 2.3: "Units, patients, orders, cost entries, feeds, stations, safety events and
        staff can all be narrowed by `status`."

        Design: Corner/endpoints/observer_station_and_feed_reverse_lookups_resolve_from_both_ends
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C35",
            budget_cents=250000,
            video_monitoring_enabled=True,
            name="Corner Unit Thirtyfive",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C3501", full_name="Feed Link Patient", age_years=60
        )
        observer = make_staff(
            api,
            unit["id"],
            full_name="Link Observer",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2200,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_VIDEO_MONITORING,
            clinical_rationale="Fall risk suitable for continuous video observation",
        )
        console_a = make_station(
            api, observer["id"], station_label="CONSOLE-A", declared_max_span=3
        )
        console_b = make_station(
            api, observer["id"], station_label="CONSOLE-B", declared_max_span=2
        )
        feed = make_feed(
            api,
            console_a["id"],
            order["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
            observer["id"],
        )

        console_rows, console_meta = validate_paginated(
            api.list_staff_stations(observer["id"], MANAGER)
        )
        assert_row_count(console_rows, 2, "consoles staffed by the observer")
        assert_fields(console_meta, label="console list meta", total_count=2)
        assert_fields(
            exactly_one(console_rows, id=console_a["id"]),
            label="loaded console",
            observer_staff_id=observer["id"],
            status=STATION_ACTIVE_MONITORING,
            active_feed_count=1,
            active_acuity_weight=1.0,
            effective_span_limit=3,
        )
        assert_fields(
            exactly_one(console_rows, id=console_b["id"]),
            label="idle console",
            observer_staff_id=observer["id"],
            status=STATION_IDLE,
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=2,
        )

        active_rows, active_meta = validate_paginated(
            api.list_station_feeds(console_a["id"], MANAGER, {"status": FEED_ACTIVE})
        )
        assert_row_count(active_rows, 1, "active feeds on the loaded console")
        assert active_rows[0]["id"] == feed["id"]
        assert_fields(active_meta, label="loaded console feed meta", total_count=1)

        empty_rows, empty_meta = validate_paginated(
            api.list_station_feeds(console_b["id"], MANAGER)
        )
        assert_row_count(empty_rows, 0, "feeds on the observer's second console")
        assert_fields(empty_meta, label="idle console feed meta", total_count=0)

        from_order = order_feeds(api, order["id"])
        assert_row_count(from_order, 1, "feeds reachable from the order")
        assert from_order[0]["id"] == feed["id"]

        assert_fields(
            read_feed(api, feed["id"]),
            label="the feed read directly",
            station_id=console_a["id"],
            order_id=order["id"],
            status=FEED_ACTIVE,
            acuity_weight=1.0,
            release_reason=None,
            released_at=None,
        )
        assert_fields(
            read_staff(api, observer["id"]),
            label="observer taken on duty by the first feed",
            status=STAFF_ON_ASSIGNMENT,
        )
        assert_row_count(
            station_feeds(api, console_a["id"]), 1, "all feeds ever on the loaded console"
        )


class TestClockEndpointCounters:
    """The clock response is itself the derived read of what its sweep just did."""

    def test_the_clock_reports_only_this_calls_transitions_and_refuses_a_rewind(
        self, api: ObservationApiClient
    ) -> None:
        """
        Two orders share one due instant, so the due sweep reports two and the lapse
        sweep on the following call reports two, never both in one call; an advance to
        the same instant is a no-op that reports zeros, one second earlier is refused
        outright, and a later advance over two LAPSED orders sweeps nothing.

        PRD 2.4: "A `SystemAdmin` moves the clock by supplying a `current_utc` instant; the
        new value must be greater than or equal to the current logical clock, and an attempt
        to rewind the clock is rejected with `ERR_INVALID_REQUEST`."
        PRD 3.3: "Only orders in `ACTIVE` or `REASSESSMENT_DUE` are candidates — an order
        sitting in `ESCALATED` or `DISCONTINUATION_REVIEW` is immune to the sweep entirely,
        which is what makes an open discontinuation review safe from lapsing while it is
        being decided."
        PRD 3.3: "An order in `ACTIVE` transitions `ACTIVE → REASSESSMENT_DUE` when the new
        clock value is greater than or equal to its `next_reassessment_due_at`, equality being
        sufficient to fire it."
        PRD 3.3: "An order in `REASSESSMENT_DUE` transitions `REASSESSMENT_DUE → LAPSED` when
        the new clock value is greater than or equal to its `next_reassessment_due_at`
        advanced by the 6-hour reassessment grace period — inclusive, so the instant exactly
        6 hours past due already lapses."
        PRD 3.3: "Because at most one transition applies per order per call, an `ACTIVE` order
        that is already many days overdue still needs two separate clock advances to reach
        `LAPSED`: one to become `REASSESSMENT_DUE` and a second to lapse."
        PRD 3.3: "The clock response reports the instant now in force as `current_utc`,
        together with `orders_marked_reassessment_due` and `orders_lapsed` as counts of what
        the sweep did."
        PRD 3.3: "In particular `next_reassessment_due_at` is left exactly where it was, which
        is what allows the grace period to be measured from the original due instant."
        PRD 3.3: "Alongside those hops, the unit occupied by the lapsed order's patient is
        driven to `RESTRICTED` with `restriction_reason` set to `OBSERVATION_ORDER_LAPSED`; a
        unit already `RESTRICTED` is left as it is, and this step is then a no-op."

        Design: Corner/endpoints/clock_advance_reports_its_sweep_counters_inline_and_refuses_a_rewind
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C36",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirtysix",
        )
        orders = []
        for mrn, full_name, rationale in (
            ("MRN-C3601", "Sweep Patient One", "Sweep order one"),
            ("MRN-C3602", "Sweep Patient Two", "Sweep order two"),
        ):
            patient = make_patient(
                api, unit["id"], mrn=mrn, full_name=full_name, age_years=60
            )
            orders.append(
                make_order(
                    api,
                    patient["id"],
                    risk_categories=[RISK_FALL],
                    clinical_rationale=rationale,
                )
            )

        assert_fields(
            advance_clock(api, "2026-08-01T12:00:00Z"),
            label="advance to midday",
            current_utc="2026-08-01T12:00:00.000Z",
            orders_marked_reassessment_due=0,
            orders_lapsed=0,
        )
        assert_fields(
            advance_clock(api, "2026-08-01T12:00:00Z"),
            label="advance to the very same instant",
            current_utc="2026-08-01T12:00:00.000Z",
            orders_marked_reassessment_due=0,
            orders_lapsed=0,
        )

        validate_error(
            api.set_clock(clock_payload("2026-08-01T11:59:59Z"), ADMIN),
            ERR_INVALID_REQUEST,
            HTTP_BAD_REQUEST,
        )
        assert_fields(
            advance_clock(api, "2026-08-01T12:00:00Z"),
            label="clock re-read after the refused rewind",
            current_utc="2026-08-01T12:00:00.000Z",
            orders_marked_reassessment_due=0,
            orders_lapsed=0,
        )

        assert_fields(
            advance_clock(api, "2026-08-02T00:00:00Z"),
            label="advance onto the shared due instant",
            current_utc="2026-08-02T00:00:00.000Z",
            orders_marked_reassessment_due=2,
            orders_lapsed=0,
        )
        for order in orders:
            assert_fields(
                read_order(api, order["id"]),
                label="order swept as due",
                status=ORDER_REASSESSMENT_DUE,
                next_reassessment_due_at="2026-08-02T00:00:00.000Z",
                lapsed_at=None,
            )

        assert_fields(
            advance_clock(api, "2026-08-02T06:00:01Z"),
            label="advance past the grace period",
            current_utc="2026-08-02T06:00:01.000Z",
            orders_marked_reassessment_due=0,
            orders_lapsed=2,
        )
        for order in orders:
            assert_fields(
                read_order(api, order["id"]),
                label="lapsed order",
                status=ORDER_LAPSED,
                lapsed_at="2026-08-02T06:00:01.000Z",
            )
        assert_fields(
            read_unit(api, unit["id"]),
            label="unit restricted by the lapses",
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_OBSERVATION_ORDER_LAPSED,
        )

        assert_fields(
            advance_clock(api, "2026-08-02T23:00:00Z"),
            label="advance over two terminal orders",
            current_utc="2026-08-02T23:00:00.000Z",
            orders_marked_reassessment_due=0,
            orders_lapsed=0,
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="unit after the empty sweep",
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_OBSERVATION_ORDER_LAPSED,
        )


class TestCostCloseRestrictionLift:
    """A single cent of headroom decides whether the identical close reopens the unit."""

    def test_the_same_close_is_a_no_op_and_then_the_lift_once_the_budget_rises(
        self, api: ObservationApiClient
    ) -> None:
        """
        Two provisional rows take the head to exactly the budget, which restricts the
        unit; the first close prices the period and leaves the unit RESTRICTED because
        equality is not strictly less, and the identical close carrying a one-cent budget
        increase returns the same four figures but reopens the unit, all without touching
        a single ledger row.

        PRD 3.9: "Step one computes `subtotal_cents` as the exact integer sum of
        `amount_cents` over the unit's ledger rows whose `status` is `POSTED` and whose
        `posted_at` falls strictly before `close_through_utc`; the bound is strict, so a row
        posted at exactly `close_through_utc` is excluded, and rows in `status` `REVERSED` are
        excluded entirely — which is why a voided watch leaves no trace whatsoever in the
        charge."
        PRD 3.9: "Step two selects `coverage_surcharge_pct` from a tier keyed on
        `subtotal_cents` **alone**, over inclusive thresholds: a subtotal of 150000 cents or
        more takes 0.12, a subtotal below that but 60000 cents or more takes 0.08, a subtotal
        below that but 20000 cents or more takes 0.04, and anything below 20000 cents takes
        0.00."
        PRD 3.9: "Step three computes `coverage_surcharge_cents` as the subtotal multiplied by
        that percentage, rounded half up to whole cents — this is the only rounding in the
        entire calculation."
        PRD 3.9: "Step four computes `charge_total_cents` as `subtotal_cents` plus
        `coverage_surcharge_cents`."
        PRD 3.9: "The response returns `subtotal_cents`, `coverage_surcharge_pct`,
        `coverage_surcharge_cents` and `charge_total_cents`, together with the unit's resulting
        posture as `unit_status` and its resulting `version` as `unit_version`."
        PRD 3.9: "When `budget_increase_cents` is supplied it is added to the unit's
        `observation_cost_budget_cents` **before** the lift condition is evaluated, which is
        what allows a single cost-close call both to raise the ceiling and to reopen the unit
        in one step."
        PRD 3.9: "A unit in `RESTRICTED` then transitions `RESTRICTED → OPEN` with
        `restriction_reason` cleared to null when two conditions hold together: the unit's
        `observed_cost_to_date_cents` is strictly less than the (possibly just-increased)
        `observation_cost_budget_cents`, and no observation order on this unit sits in
        `LAPSED`."
        PRD 3.9: "No ledger row is created, mutated or reversed by a cost close under any
        circumstances, and the unit's `version` advances by 1."

        Design: Corner/endpoints/cost_close_with_a_budget_increase_is_the_only_lift_out_of_restricted
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C37",
            budget_cents=30000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirtyseven",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C3701", full_name="Close Patient", age_years=60
        )
        sitters = [
            make_staff(
                api,
                unit["id"],
                full_name=name,
                source_pool=POOL_INTERNAL_FLOAT,
                hourly_rate_cents=2000,
                competency_level=COMPETENCY_ADVANCED,
                deescalation_cert_expires_on=CERT_VALID,
            )
            for name in ("Close Sitter One", "Close Sitter Two")
        ]
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Fall watch on a tight budget",
        )
        eight_hours = make_assignment(
            api,
            order["id"],
            sitters[0]["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
        )
        seven_hours = make_assignment(
            api,
            order["id"],
            sitters[1]["id"],
            "2026-08-01T16:00:00Z",
            "2026-08-01T23:00:00Z",
        )
        assert eight_hours["provisional_cost_cents"] == 16000
        assert seven_hours["provisional_cost_cents"] == 14000
        advance_clock(api, "2026-08-01T06:00:00Z")

        assert_fields(
            read_unit(api, unit["id"]),
            label="unit with its head exactly on the budget",
            observed_cost_to_date_cents=30000,
            observation_cost_budget_cents=30000,
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_BUDGET_THRESHOLD_REACHED,
        )

        first_close = validate_success(
            api.cost_close(
                unit["id"], cost_close_payload("2026-08-01T06:00:00Z"), COORDINATOR
            )
        )
        assert_fields(
            first_close,
            label="close without a budget increase",
            subtotal_cents=30000,
            coverage_surcharge_cents=1200,
            charge_total_cents=31200,
            unit_status=UNIT_RESTRICTED,
        )
        assert abs(float(first_close["coverage_surcharge_pct"]) - 0.04) < 1e-9

        second_close = validate_success(
            api.cost_close(
                unit["id"],
                cost_close_payload("2026-08-01T06:00:00Z", budget_increase_cents=1),
                COORDINATOR,
            )
        )
        assert_fields(
            second_close,
            label="close carrying one cent of headroom",
            subtotal_cents=30000,
            coverage_surcharge_cents=1200,
            charge_total_cents=31200,
            unit_status=UNIT_OPEN,
            unit_version=first_close["unit_version"] + 1,
        )
        assert abs(float(second_close["coverage_surcharge_pct"]) - 0.04) < 1e-9

        assert_fields(
            read_unit(api, unit["id"]),
            label="reopened unit",
            observation_cost_budget_cents=30001,
            observed_cost_to_date_cents=30000,
            status=UNIT_OPEN,
            restriction_reason=None,
            version=second_close["unit_version"],
        )

        rows = unit_cost_entries(api, unit["id"])
        assert_row_count(rows, 2, "ledger rows after two closes")
        for row, amount in ((exactly_one(rows, assignment_id=eight_hours["id"]), 16000),
                            (exactly_one(rows, assignment_id=seven_hours["id"]), 14000)):
            assert_fields(
                row,
                label=f"untouched provisional row of {amount}",
                entry_kind=ENTRY_KIND_PROVISIONAL,
                status=COST_POSTED,
                amount_cents=amount,
                posted_at=CLOCK_START,
                reversed_at=None,
            )
