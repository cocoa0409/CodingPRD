"""Two resources with opposite interval semantics.

Bench windows are half-open and guarded by an aggregate slot count plus an
aggregate hour ceiling; display windows are closed, keyed on the
retailer-grant-channel triple, and widened backwards by an inclusive buffer.
"""
from test_helpers import (
    ADMIN,
    PUBLISHER,
    ApiErrorId,
    api_client,
    assert_bench_hour_ledger,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK

ROUTER_CATEGORY = {
    "category_code": "HOME_ROUTER",
    "display_name": "Home Router",
    "min_support_period_days": 1095,
}


def _lab_with_one_assessment_under_review():
    """An ACCREDITED lab of 240 bench hours and capacity 2, ledger at 0/240."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("THIRD_PARTY_TEST", category_overrides=ROUTER_CATEGORY)
    sponsor = fixtures.enrol_manufacturer()
    lab = fixtures.register_lab()
    product = fixtures.register_product(
        program,
        sponsor,
        model_name="Northwind Router R7",
        sku="NW-RTR-R7",
        retail_units_shipped=40000,
    )
    assessment = fixtures.open_assessment(program, sponsor, product)
    fixtures.attach_responses(program, sponsor, assessment)
    assessment = validate_success(
        api_client.submit_assessment(assessment["id"], sponsor.headers), 201
    )
    ledger = lab.refresh()
    assert_bench_hour_ledger(ledger, reserved=0)
    assert ledger["available_bench_hours"] == 240, ledger
    assert ledger["concurrent_bench_capacity"] == 2, ledger
    return {"sponsor": sponsor, "lab": lab, "assessment": assessment}


def _book(ctx, window_start, window_end, bench_hours):
    return api_client.create_test_engagement(
        factories.create_test_engagement_payload(
            ctx["assessment"]["id"],
            ctx["lab"].id,
            window_start=window_start,
            window_end=window_end,
            bench_hours=bench_hours,
        ),
        ctx["sponsor"].headers,
    )


E1 = ("2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z", 48)
E2 = ("2026-09-02T00:00:00Z", "2026-09-04T00:00:00Z", 48)
E3 = ("2026-09-02T12:00:00Z", "2026-09-05T00:00:00Z", 24)
E4 = ("2026-09-04T00:00:00Z", "2026-09-06T00:00:00Z", 24)
E5 = ("2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z", 200)


class TestLabBenchAggregateCapacityHalfOpenOverlap:
    """A half-open overlap count against capacity 2, plus an aggregate hour ceiling."""

    def test_two_overlapping_windows_fit_under_a_capacity_of_two(self):
        """One intersecting neighbour is strictly fewer than two, so E2 is booked.

        PRD: "Booking an engagement therefore raises `reserved_bench_hours` by the requested `bench_hours` and lowers `available_bench_hours` by the same amount."
        Design: Difficulty/resource_temporal_overlap/lab_bench_aggregate_capacity_halfopen_overlap
        """
        ctx = _lab_with_one_assessment_under_review()
        first = validate_success(_book(ctx, *E1), 201)
        assert_status(first, "status", "SCHEDULED")
        after_first = ctx["lab"].refresh()
        assert_bench_hour_ledger(after_first, reserved=48)
        assert after_first["available_bench_hours"] == 192, after_first

        second = validate_success(_book(ctx, *E2), 201)
        assert_status(second, "status", "SCHEDULED")
        after_second = ctx["lab"].refresh()
        assert_bench_hour_ledger(after_second, reserved=96)
        assert after_second["available_bench_hours"] == 144, after_second

    def test_window_intersecting_both_neighbours_exhausts_the_bench(self):
        """Two intersecting neighbours are not strictly fewer than two.

        PRD: "Then the bench must have a free slot: count the laboratory's *other* engagements whose `status` is `SCHEDULED` or `IN_PROGRESS` and whose own half-open window intersects the requested half-open window, and that count must be strictly less than the lab's `concurrent_bench_capacity`, otherwise the booking is rejected with `ERR_LAB_BENCH_CAPACITY_CONFLICT`."
        Design: Difficulty/resource_temporal_overlap/lab_bench_aggregate_capacity_halfopen_overlap
        """
        ctx = _lab_with_one_assessment_under_review()
        validate_success(_book(ctx, *E1), 201)
        validate_success(_book(ctx, *E2), 201)

        response = _book(ctx, *E3)
        validate_error(response, ApiErrorId.ERR_LAB_BENCH_CAPACITY_CONFLICT.value)
        assert response.status_code == 409, response.text

        unchanged = ctx["lab"].refresh()
        assert_bench_hour_ledger(unchanged, reserved=96)
        assert unchanged["available_bench_hours"] == 144, unchanged

    def test_window_starting_exactly_when_another_ends_does_not_intersect(self):
        """Half-open adjacency consumes no slot, so E4 is booked.

        PRD: "Because both windows are half-open, an engagement that begins at exactly the instant another one ends does *not* intersect it and does not consume a slot."
        Design: Difficulty/resource_temporal_overlap/lab_bench_aggregate_capacity_halfopen_overlap
        """
        ctx = _lab_with_one_assessment_under_review()
        validate_success(_book(ctx, *E1), 201)
        validate_success(_book(ctx, *E2), 201)
        validate_error(_book(ctx, *E3), ApiErrorId.ERR_LAB_BENCH_CAPACITY_CONFLICT.value)

        adjacent = validate_success(_book(ctx, *E4), 201)
        assert_status(adjacent, "status", "SCHEDULED")
        after = ctx["lab"].refresh()
        assert_bench_hour_ledger(after, reserved=120)
        assert after["available_bench_hours"] == 120, after

    def test_non_overlapping_window_can_still_break_the_aggregate_ceiling(self):
        """A window nothing intersects is rejected purely on the hour budget.

        PRD: "Finally the aggregate budget must hold: the requested `bench_hours` must be less than or equal to the laboratory's `available_bench_hours` as the ledger stands after the capacity check and before the write, otherwise the booking is rejected with `ERR_LAB_BENCH_HOURS_EXCEEDED`."
        Design: Difficulty/resource_temporal_overlap/lab_bench_aggregate_capacity_halfopen_overlap
        """
        ctx = _lab_with_one_assessment_under_review()
        first = validate_success(_book(ctx, *E1), 201)
        second = validate_success(_book(ctx, *E2), 201)
        validate_error(_book(ctx, *E3), ApiErrorId.ERR_LAB_BENCH_CAPACITY_CONFLICT.value)
        fourth = validate_success(_book(ctx, *E4), 201)

        response = _book(ctx, *E5)
        validate_error(response, ApiErrorId.ERR_LAB_BENCH_HOURS_EXCEEDED.value)
        assert response.status_code == 409, response.text

        final = ctx["lab"].refresh()
        assert_bench_hour_ledger(final, reserved=120)
        assert final["total_bench_hours"] == 240, final

        items, meta = validate_paginated(
            api_client.list_test_engagements(
                ADMIN, params={"test_lab_id": ctx["lab"].id, "status": "SCHEDULED"}
            )
        )
        assert len(items) == 3, items
        assert meta["total_count"] == 3, meta
        assert {item["id"] for item in items} == {first["id"], second["id"], fourth["id"]}, items


A1_FROM = "2026-08-10T00:00:00Z"
A1_UNTIL = "2026-09-10T00:00:00Z"
BUFFER_EDGE_FROM = "2026-09-17T00:00:00Z"
BUFFER_CLEAR_FROM = "2026-09-17T00:00:01Z"
PROBE_UNTIL = "2026-10-10T00:00:00Z"
BEYOND_VALIDITY = ("2027-07-20T00:00:00Z", "2027-08-15T00:00:00Z")


def _published_grant_with_one_online_display():
    """A live label plus one AUTHORIZED ONLINE window running 08-10 to 09-10."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    sponsor = fixtures.enrol_manufacturer()
    claim = fixtures.approved_claim(program=program, sponsor=sponsor)
    grant = fixtures.published_grant(claim, publisher_headers=PUBLISHER)
    store = fixtures.register_retailer(retailer_name="Cedar Home Retail")
    first = validate_success(
        api_client.create_display_authorization(
            factories.create_display_authorization_payload(
                store.id, grant.id, A1_FROM, A1_UNTIL, channel="ONLINE"
            ),
            store.headers,
        ),
        201,
    )
    assert_status(first, "status", "AUTHORIZED")
    return {"grant": grant, "store": store, "first": first}


def _display(ctx, display_from, display_until, channel="ONLINE"):
    return api_client.create_display_authorization(
        factories.create_display_authorization_payload(
            ctx["store"].id, ctx["grant"].id, display_from, display_until, channel=channel
        ),
        ctx["store"].headers,
    )


class TestRetailerDisplayClosedIntervalWithChangeoverBuffer:
    """Closed windows widened backwards by an inclusive seven-day buffer."""

    def test_window_exactly_seven_days_after_the_previous_until_still_conflicts(self):
        """The buffer edge is inclusive, so the seventh day is not yet clear.

        PRD: "Both the buffer and both endpoints are inclusive, so a new window whose `display_from` falls exactly seven days after a previous window's `display_until` still conflicts; eight days clears."
        Design: Difficulty/resource_temporal_overlap/retailer_display_closed_interval_with_changeover_buffer
        """
        ctx = _published_grant_with_one_online_display()
        response = _display(ctx, BUFFER_EDGE_FROM, PROBE_UNTIL)
        validate_error(response, ApiErrorId.ERR_DISPLAY_WINDOW_CONFLICT.value)
        assert response.status_code == 409, response.text

    def test_one_second_past_the_buffer_edge_is_accepted(self):
        """Widening backwards by seven days no longer touches the earlier window.

        PRD: "Finally, the window must clear a changeover buffer against the retailer's own existing displays: take every other authorization of the *same* combination of `retailer_id`, `label_grant_id` and `channel` whose `status` is `AUTHORIZED`, widen the requested closed window backwards in time by seven days, and if the widened window intersects any of those existing closed windows the request is rejected with `ERR_DISPLAY_WINDOW_CONFLICT`."
        Design: Difficulty/resource_temporal_overlap/retailer_display_closed_interval_with_changeover_buffer
        """
        ctx = _published_grant_with_one_online_display()
        validate_error(
            _display(ctx, BUFFER_EDGE_FROM, PROBE_UNTIL),
            ApiErrorId.ERR_DISPLAY_WINDOW_CONFLICT.value,
        )
        accepted = validate_success(_display(ctx, BUFFER_CLEAR_FROM, PROBE_UNTIL), 201)
        assert_status(accepted, "status", "AUTHORIZED")

    def test_the_same_instants_on_another_channel_never_conflict(self):
        """The overlap key includes the channel, so IN_STORE is a separate lane.

        PRD: "Because the check is scoped to the retailer-grant-channel combination, the same retailer may run an `IN_STORE` and an `ONLINE` display of the same label over identical dates without conflict."
        Design: Difficulty/resource_temporal_overlap/retailer_display_closed_interval_with_changeover_buffer
        """
        ctx = _published_grant_with_one_online_display()
        validate_error(
            _display(ctx, BUFFER_EDGE_FROM, PROBE_UNTIL),
            ApiErrorId.ERR_DISPLAY_WINDOW_CONFLICT.value,
        )
        in_store = validate_success(
            _display(ctx, BUFFER_EDGE_FROM, PROBE_UNTIL, channel="IN_STORE"), 201
        )
        assert_status(in_store, "status", "AUTHORIZED")
        assert_status(in_store, "channel", "IN_STORE")

    def test_window_leaving_the_grant_validity_reports_the_containment_error(self):
        """A window running past `valid_until` fails containment, not separation.

        PRD: "The requested closed window must lie entirely inside the grant's own window from `valid_from` to `valid_until`, so that a display cannot still be live after the label expires; a window that pokes outside is rejected at creation time with `ERR_DISPLAY_WINDOW_OUTSIDE_VALIDITY` rather than discovered later."
        Design: Difficulty/resource_temporal_overlap/retailer_display_closed_interval_with_changeover_buffer
        """
        ctx = _published_grant_with_one_online_display()
        response = _display(ctx, *BEYOND_VALIDITY)
        validate_error(response, ApiErrorId.ERR_DISPLAY_WINDOW_OUTSIDE_VALIDITY.value)
        assert response.status_code == 422, response.text

    def test_only_the_three_accepted_windows_are_counted(self):
        """Three AUTHORIZED rows promote the retailer to GOLD; the rejects wrote nothing.

        PRD: "Then `participation_tier` is chosen: a retailer whose `education_materials_ack` is true and whose `active_display_count` is 5 or more is `PLATINUM`; failing that, a retailer whose `education_materials_ack` is true and whose `active_display_count` is 2 or more is `GOLD`; every other retailer is `BASELINE`."
        Design: Difficulty/resource_temporal_overlap/retailer_display_closed_interval_with_changeover_buffer
        """
        ctx = _published_grant_with_one_online_display()
        validate_error(
            _display(ctx, BUFFER_EDGE_FROM, PROBE_UNTIL),
            ApiErrorId.ERR_DISPLAY_WINDOW_CONFLICT.value,
        )
        third = validate_success(_display(ctx, BUFFER_CLEAR_FROM, PROBE_UNTIL), 201)
        fourth = validate_success(
            _display(ctx, BUFFER_EDGE_FROM, PROBE_UNTIL, channel="IN_STORE"), 201
        )
        validate_error(
            _display(ctx, *BEYOND_VALIDITY),
            ApiErrorId.ERR_DISPLAY_WINDOW_OUTSIDE_VALIDITY.value,
        )

        retailer = ctx["store"].refresh()
        assert retailer["active_display_count"] == 3, retailer["active_display_count"]
        assert_status(retailer, "participation_tier", "GOLD")

        items, meta = validate_paginated(
            api_client.list_display_authorizations(
                ADMIN, params={"retailer_id": ctx["store"].id}
            )
        )
        assert len(items) == 3, items
        assert meta["total_count"] == 3, meta
        assert {item["id"] for item in items} == {
            ctx["first"]["id"],
            third["id"],
            fourth["id"],
        }, items
