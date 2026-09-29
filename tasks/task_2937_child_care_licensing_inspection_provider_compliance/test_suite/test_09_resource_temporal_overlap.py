"""The three occupancy tests and the clearance validity window (PRD §3.4, §3.3).

Each contended resource carries a different edge rule: the inspector's window is
half-open, the provider's buffered window is closed, the inspector's daily quota
is a UTC-date bucket with no interval arithmetic at all, and a clearance is a
validity interval whose upper edge is exclusive.
"""

from test_helpers import (
    DEFAULT_LOGICAL_CLOCK,
    assert_capacity_slots,
    assert_instant,
    assert_score,
    bgu_headers,
    factories as f,
    fixtures as fx,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PRESCHOOL = ["PRESCHOOL"]


def _schedule(api, provider_id, inspector_id, scheduled_for, duration_minutes=120):
    return api.create_inspection(
        f.inspection_payload(
            provider_id,
            inspector_id,
            inspection_type="ANNUAL",
            scheduled_for=scheduled_for,
            target_age_groups=PRESCHOOL,
            duration_minutes=duration_minutes,
        ),
        headers=supervisor_headers(),
    )


def _inspector(api, name):
    return fx.register_inspector(
        api, full_name=name, certified_age_groups=PRESCHOOL, max_daily_visits=3
    )


def _provider(api, name, address):
    return fx.create_provider(
        api,
        legal_name=name,
        site_address=address,
        program_type="CENTER",
        requested_capacity=20,
    )


def _count(api, inspector_id):
    return validate_success(
        api.get_inspector(inspector_id, headers=supervisor_headers())
    )["scheduled_visit_count"]


def _one_inspector_two_providers(api):
    """Ada holds a single ANNUAL visit at Alder from 09:00 to 11:00 on 2026-08-05.

    The second provider exists so that a refusal can never be explained by the
    provider-side buffer rule.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = _inspector(api, "Ada Inspector")
    alder = _provider(api, "Alder Center", "1 Alder St")
    birchwood = _provider(api, "Birchwood Center", "2 Birchwood St")
    first = validate_success(
        _schedule(api, alder["id"], ada["id"], "2026-08-05T09:00:00Z"), 201
    )
    return {
        "ada": ada,
        "alder_id": alder["id"],
        "birchwood_id": birchwood["id"],
        "first": first,
    }


class TestInspectorHalfOpenWindowAllowsBackToBack:
    """§3.4: "The **inspector's** window is half-open — it includes its start
    instant and excludes its end instant"."""

    def test_a_one_second_overlap_is_still_a_double_booking(self, api):
        """A visit starting at 10:59:59Z intersects the anchor by exactly one second
        and is refused without creating a row.

        PRD §3.4: "two visits for the same inspector conflict only when their
        half-open windows genuinely overlap ... An overlap is
        `ERR_INSPECTOR_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_inspector_half_open_window_allows_back_to_back
        """
        ctx = _one_inspector_two_providers(api)
        assert_instant(
            ctx["first"]["visit_window_end"],
            "2026-08-05T11:00:00Z",
            "visit_window_end",
        )
        assert _count(api, ctx["ada"]["id"]) == 1

        validate_error(
            _schedule(
                api, ctx["birchwood_id"], ctx["ada"]["id"], "2026-08-05T10:59:59Z"
            ),
            "ERR_INSPECTOR_DOUBLE_BOOKED",
            409,
        )

        assert _count(api, ctx["ada"]["id"]) == 1
        rows, _meta = validate_paginated(
            api.list_inspections(
                provider_id=ctx["birchwood_id"], headers=supervisor_headers()
            )
        )
        assert rows == [], (
            f"the refused request must create no inspection row; got {rows!r}"
        )

    def test_touching_windows_do_not_conflict(self, api):
        """The identical request one second later starts exactly when the anchor
        ends and is accepted, leaving Ada two visits on the same day.

        PRD §3.4: "Back-to-back visits, where one ends at the exact instant the next
        begins, do **not** conflict."

        Design: Difficulty/resource_temporal_overlap/overlap_inspector_half_open_window_allows_back_to_back
        """
        ctx = _one_inspector_two_providers(api)
        validate_error(
            _schedule(
                api, ctx["birchwood_id"], ctx["ada"]["id"], "2026-08-05T10:59:59Z"
            ),
            "ERR_INSPECTOR_DOUBLE_BOOKED",
            409,
        )

        second = validate_success(
            _schedule(
                api, ctx["birchwood_id"], ctx["ada"]["id"], "2026-08-05T11:00:00Z"
            ),
            201,
        )

        assert second["status"] == "SCHEDULED"
        assert_instant(
            second["visit_window_end"], "2026-08-05T13:00:00Z", "visit_window_end"
        )
        assert _count(api, ctx["ada"]["id"]) == 2, (
            "two active visits on 2026-08-05 stay strictly below max_daily_visits 3, "
            "so the daily limit never enters this instance"
        )

    def test_voiding_releases_the_window_for_an_identical_request(self, api):
        """The 09:00Z slot is refused while the anchor is SCHEDULED and accepted once
        the anchor is VOIDED, which is only possible if the occupied set holds live
        rows alone.

        PRD §3.4: "The **active set** for all three is every inspection whose status
        is `SCHEDULED` or `IN_PROGRESS`: a visit that has moved on to
        `PENDING_REVIEW`, `FINALIZED` or `VOIDED` releases its windows and never
        conflicts again."

        Design: Difficulty/resource_temporal_overlap/overlap_inspector_half_open_window_allows_back_to_back
        """
        ctx = _one_inspector_two_providers(api)
        validate_error(
            _schedule(api, ctx["birchwood_id"], ctx["ada"]["id"], "2026-08-05T09:00:00Z"),
            "ERR_INSPECTOR_DOUBLE_BOOKED",
            409,
        )

        voided = validate_success(
            api.void_inspection(ctx["first"]["id"], headers=supervisor_headers())
        )
        assert voided["status"] == "VOIDED"
        assert _count(api, ctx["ada"]["id"]) == 0

        third = validate_success(
            _schedule(api, ctx["birchwood_id"], ctx["ada"]["id"], "2026-08-05T09:00:00Z"),
            201,
        )
        assert third["status"] == "SCHEDULED"
        assert third["id"] != ctx["first"]["id"]
        assert_instant(
            third["visit_window_end"], "2026-08-05T11:00:00Z", "visit_window_end"
        )
        assert _count(api, ctx["ada"]["id"]) == 1


def _one_site_two_inspectors(api):
    """Cedarcroft's only visit is Ada's 09:00-11:00 anchor, whose buffered window
    is the closed interval [08:00:00Z, 12:00:00Z].

    Ben is a second certified inspector, so every refusal below is about the site
    and never about an inspector's own calendar.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = _inspector(api, "Ada Inspector")
    ben = _inspector(api, "Ben Inspector")
    cedarcroft = _provider(api, "Cedarcroft Center", "3 Cedarcroft St")
    anchor = validate_success(
        _schedule(api, cedarcroft["id"], ada["id"], "2026-08-05T09:00:00Z"), 201
    )
    return {"ada": ada, "ben": ben, "provider_id": cedarcroft["id"], "anchor": anchor}


class TestProviderBufferedWindowTouchConflicts:
    """§3.4: "Two visits at the same site therefore conflict when their padded
    closed windows touch at even a single instant"."""

    def test_buffered_windows_that_merely_touch_conflict_on_both_edges(self, api):
        """A visit two hours after the anchor ends and a visit whose buffer reaches
        exactly the anchor's lower buffer edge are both refused, and the refusals
        name an inspector who is entirely free.

        PRD §3.4: "a visit ending at ten o'clock and another beginning at noon are
        120 minutes apart, their padded windows meet exactly at eleven o'clock, and
        the second is refused with `ERR_PROVIDER_VISIT_BUFFER_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_provider_site_closed_buffered_window_touch_conflicts
        """
        ctx = _one_site_two_inspectors(api)
        assert_instant(
            ctx["anchor"]["visit_window_end"],
            "2026-08-05T11:00:00Z",
            "visit_window_end",
        )

        validate_error(
            _schedule(
                api, ctx["provider_id"], ctx["ben"]["id"], "2026-08-05T13:00:00Z"
            ),
            "ERR_PROVIDER_VISIT_BUFFER_CONFLICT",
            409,
        )
        validate_error(
            _schedule(
                api, ctx["provider_id"], ctx["ben"]["id"], "2026-08-05T05:00:00Z"
            ),
            "ERR_PROVIDER_VISIT_BUFFER_CONFLICT",
            409,
        )

        assert _count(api, ctx["ben"]["id"]) == 0, (
            "Ben holds no visit at all, so neither refusal can be a double booking"
        )
        assert _count(api, ctx["ada"]["id"]) == 1

    def test_one_second_of_clearance_on_either_side_is_enough(self, api):
        """One second outside the anchor's padded window at each end is accepted, so
        the buffer is 60 minutes per side applied to both rows.

        PRD §3.4: "The **provider's** window is closed — it includes both endpoints —
        and is additionally padded by 60 minutes on each side before comparison."

        Design: Difficulty/resource_temporal_overlap/overlap_provider_site_closed_buffered_window_touch_conflicts
        """
        ctx = _one_site_two_inspectors(api)
        early = validate_success(
            _schedule(
                api, ctx["provider_id"], ctx["ben"]["id"], "2026-08-05T04:59:59Z"
            ),
            201,
        )
        late = validate_success(
            _schedule(
                api, ctx["provider_id"], ctx["ben"]["id"], "2026-08-05T13:00:01Z"
            ),
            201,
        )

        assert_instant(
            early["visit_window_end"], "2026-08-05T06:59:59Z", "visit_window_end"
        )
        assert_instant(
            late["visit_window_end"], "2026-08-05T15:00:01Z", "visit_window_end"
        )
        assert _count(api, ctx["ben"]["id"]) == 2
        assert _count(api, ctx["ada"]["id"]) == 1

    def test_the_site_holds_exactly_the_three_accepted_visits(self, api):
        """The two refusals leave no rows behind, so Cedarcroft ends the day with the
        anchor and the two visits that cleared the buffer.

        PRD §3.4: "Widening the gap to 121 minutes clears it."

        Design: Difficulty/resource_temporal_overlap/overlap_provider_site_closed_buffered_window_touch_conflicts
        """
        ctx = _one_site_two_inspectors(api)
        validate_error(
            _schedule(
                api, ctx["provider_id"], ctx["ben"]["id"], "2026-08-05T13:00:00Z"
            ),
            "ERR_PROVIDER_VISIT_BUFFER_CONFLICT",
            409,
        )
        early = validate_success(
            _schedule(
                api, ctx["provider_id"], ctx["ben"]["id"], "2026-08-05T04:59:59Z"
            ),
            201,
        )
        late = validate_success(
            _schedule(
                api, ctx["provider_id"], ctx["ben"]["id"], "2026-08-05T13:00:01Z"
            ),
            201,
        )

        rows, meta = validate_paginated(
            api.list_inspections(
                provider_id=ctx["provider_id"], headers=supervisor_headers()
            )
        )
        assert meta["total_count"] == 3
        assert sorted(row["id"] for row in rows) == sorted(
            [ctx["anchor"]["id"], early["id"], late["id"]]
        )


def _cara_with_three_visits_on_one_date(api):
    """Cara holds back-to-back ANNUAL visits at 09:00, 11:00 and 13:00 on
    2026-08-05, each at a different provider so the site buffer can never fire."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    cara = _inspector(api, "Cara Inspector")
    providers = [
        _provider(api, f"P{n} Center", f"1{n} Street")["id"] for n in range(1, 6)
    ]
    visits = [
        validate_success(
            _schedule(api, providers[i], cara["id"], start), 201
        )
        for i, start in enumerate(
            ["2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z"]
        )
    ]
    return {"cara": cara, "providers": providers, "visits": visits}


class TestInspectorDailyBucketCountsByUtcDate:
    """§3.4: "The date is taken from the UTC calendar day of `scheduled_for`"."""

    def test_the_fourth_visit_of_the_date_is_refused_without_any_overlap(self, api):
        """The refused request only touches the third visit's window and its provider
        is free, so the quota is the sole cause.

        PRD §3.4: "The inspector's **daily load** is the count of their active-set
        inspections falling on the same UTC calendar date as the requested start, and
        that count must be strictly below the inspector's `max_daily_visits`. At the
        limit the request is `ERR_INSPECTOR_DAILY_LIMIT_REACHED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_inspector_daily_bucket_counts_by_utc_date
        """
        ctx = _cara_with_three_visits_on_one_date(api)
        assert _count(api, ctx["cara"]["id"]) == 3

        validate_error(
            _schedule(
                api, ctx["providers"][3], ctx["cara"]["id"], "2026-08-05T15:00:00Z"
            ),
            "ERR_INSPECTOR_DAILY_LIMIT_REACHED",
            409,
        )

        assert _count(api, ctx["cara"]["id"]) == 3
        rows, _meta = validate_paginated(
            api.list_inspections(
                provider_id=ctx["providers"][3], headers=supervisor_headers()
            )
        )
        assert rows == [], "the refused request must create no inspection row"

    def test_the_next_utc_date_starts_a_fresh_bucket(self, api):
        """A new calendar date starts the count at zero, and the identical shape that
        was refused on 2026-08-05 is accepted on 2026-08-06.

        PRD §3.4: "so a visit at 23:30 UTC and one at 00:30 UTC the next morning fall
        on different days however close they are in time."

        Design: Difficulty/resource_temporal_overlap/overlap_inspector_daily_bucket_counts_by_utc_date
        """
        ctx = _cara_with_three_visits_on_one_date(api)
        validate_error(
            _schedule(
                api, ctx["providers"][3], ctx["cara"]["id"], "2026-08-05T15:00:00Z"
            ),
            "ERR_INSPECTOR_DAILY_LIMIT_REACHED",
            409,
        )

        next_day = validate_success(
            _schedule(
                api, ctx["providers"][3], ctx["cara"]["id"], "2026-08-06T09:00:00Z"
            ),
            201,
        )
        assert next_day["status"] == "SCHEDULED"
        assert_instant(
            next_day["visit_window_end"], "2026-08-06T11:00:00Z", "visit_window_end"
        )
        assert _count(api, ctx["cara"]["id"]) == 4

    def test_a_visit_crossing_midnight_is_charged_to_its_start_date(self, api):
        """The 23:00Z visit runs into 2026-08-07 yet fills the third slot of
        2026-08-06, which the refusal of a fourth 2026-08-06 visit proves.

        PRD §3.4: "The inspector's **daily load** is the count of their active-set
        inspections falling on the same UTC calendar date as the requested start"

        Design: Difficulty/resource_temporal_overlap/overlap_inspector_daily_bucket_counts_by_utc_date
        """
        ctx = _cara_with_three_visits_on_one_date(api)
        validate_success(
            _schedule(
                api, ctx["providers"][3], ctx["cara"]["id"], "2026-08-06T09:00:00Z"
            ),
            201,
        )
        midnight = validate_success(
            _schedule(
                api, ctx["providers"][4], ctx["cara"]["id"], "2026-08-06T23:00:00Z"
            ),
            201,
        )
        assert_instant(
            midnight["visit_window_end"], "2026-08-07T01:00:00Z", "visit_window_end"
        )

        third_of_the_date = validate_success(
            _schedule(
                api, ctx["providers"][0], ctx["cara"]["id"], "2026-08-06T13:00:00Z"
            ),
            201,
        )
        assert third_of_the_date["status"] == "SCHEDULED"

        validate_error(
            _schedule(
                api, ctx["providers"][1], ctx["cara"]["id"], "2026-08-06T15:00:00Z"
            ),
            "ERR_INSPECTOR_DAILY_LIMIT_REACHED",
            409,
        )

    def test_voiding_frees_a_slot_in_the_bucket(self, api):
        """The quota is recomputed from live rows, so voiding the 09:00 visit lets the
        request that hit the limit through unchanged.

        PRD §3.4: "a visit that has moved on to `PENDING_REVIEW`, `FINALIZED` or
        `VOIDED` releases its windows and never conflicts again."

        Design: Difficulty/resource_temporal_overlap/overlap_inspector_daily_bucket_counts_by_utc_date
        """
        ctx = _cara_with_three_visits_on_one_date(api)
        validate_error(
            _schedule(
                api, ctx["providers"][3], ctx["cara"]["id"], "2026-08-05T15:00:00Z"
            ),
            "ERR_INSPECTOR_DAILY_LIMIT_REACHED",
            409,
        )

        voided = validate_success(
            api.void_inspection(ctx["visits"][0]["id"], headers=supervisor_headers())
        )
        assert voided["status"] == "VOIDED"
        assert _count(api, ctx["cara"]["id"]) == 2

        fourth = validate_success(
            _schedule(
                api, ctx["providers"][3], ctx["cara"]["id"], "2026-08-05T15:00:00Z"
            ),
            201,
        )
        assert fourth["status"] == "SCHEDULED"
        assert _count(api, ctx["cara"]["id"]) == 3, (
            "scheduled_visit_count is always the number of the inspector's "
            "SCHEDULED, IN_PROGRESS or PENDING_REVIEW inspections, so the voided "
            "row leaves it"
        )


def _dunmore_with_fresh_clearances(api):
    """Dunmore Center, cleared at 2026-08-01 so both required checks expire at
    2031-08-01T00:00:00Z, with a single PRESCHOOL room of 20 that exactly matches
    the requested capacity."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = _inspector(api, "Ada Inspector")
    ctx = fx.setup_provider_dossier(
        api,
        legal_name="Dunmore Center",
        site_address="21 Dunmore Rd",
        program_type="CENTER",
        requested_capacity=20,
        rooms=[{"age_group": "PRESCHOOL", "requested_group_size": 20}],
        director_name="Dana Director",
        director_qualified_age_groups=PRESCHOOL,
        seed_checklist=False,
    )
    fx.advance_to_checks_cleared(ctx)
    return {"ctx": ctx, "ada": ada}


def _initial_visit_finalized_one_second_before_expiry(api, bundle):
    """Schedule, work and finalize an INITIAL visit that ends one second inside the
    clearance validity interval."""
    fx.set_clock(api, "2031-07-31T22:00:00Z")
    inspection = fx.schedule_visit(
        api,
        bundle["ctx"].id,
        bundle["ada"]["id"],
        "2031-07-31T23:00:00Z",
        inspection_type="INITIAL",
        target_age_groups=PRESCHOOL,
        duration_minutes=30,
    )
    fx.set_clock(api, "2031-07-31T23:59:59Z")
    fx.start_visit(api, inspection["id"], bundle["ada"]["id"])
    fx.submit_findings(api, inspection["id"], bundle["ada"]["id"], "PASS", PRESCHOOL)
    return fx.finalize_visit(api, inspection["id"])


class TestClearanceValidityWindowUpperEdgeExclusive:
    """§3.3: "The expiry comparison is strict: a check whose `expires_at` equals
    the current instant has already stopped counting"."""

    def test_a_cleared_check_is_valid_for_sixty_months(self, api):
        """Both required checks expire exactly sixty months after their decision, and
        while they are fresh the provider clears.

        PRD §3.3: "it sets `status` to `CLEARED`, stamps `decided_at` with the clock
        and sets `expires_at` to sixty months after that instant."

        Design: Difficulty/resource_temporal_overlap/overlap_clearance_validity_window_upper_edge_exclusive
        """
        bundle = _dunmore_with_fresh_clearances(api)
        checks = bundle["ctx"].director_checks

        for check_type in ("FBI_FINGERPRINT", "CHILD_ABUSE_REGISTRY"):
            check = checks[check_type]
            assert check["status"] == "CLEARED"
            assert_instant(check["decided_at"], DEFAULT_LOGICAL_CLOCK, "decided_at")
            assert_instant(check["expires_at"], "2031-08-01T00:00:00Z", "expires_at")

        provider = bundle["ctx"].reload()
        assert provider["clearance_complete"] is True
        assert provider["application_status"] == "CHECKS_CLEARED"
        assert_capacity_slots(provider, 0, 0)

    def test_one_second_inside_the_interval_the_clearance_still_counts(self, api):
        """A finalize at 2031-07-31T23:59:59Z passes the clearance gate, so the
        interval is still open one second before its upper edge.

        PRD §3.3: "The flag is read as a precondition in three places: the
        supervisor's clearance advance ...; the finalization of an `INITIAL`
        inspection ...; and the issuing licence decision. In all three, a false flag
        is `ERR_CLEARANCE_INCOMPLETE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_clearance_validity_window_upper_edge_exclusive
        """
        bundle = _dunmore_with_fresh_clearances(api)
        finalized = _initial_visit_finalized_one_second_before_expiry(api, bundle)

        assert finalized["status"] == "FINALIZED"
        assert_score(
            finalized["preliminary_compliance_score"],
            100.00,
            "preliminary_compliance_score",
        )
        provider = bundle["ctx"].reload()
        assert provider["clearance_complete"] is True
        assert provider["application_status"] == "INITIAL_INSPECTION_PASSED"

    def test_the_clock_alone_closes_the_window_and_refuses_the_licence(self, api):
        """One second later, with no request made in between, the person is no longer
        cleared and the issuing decision is refused although both checks still read
        CLEARED.

        PRD §3.3: "A consequence worth stating plainly is that a provider can lose
        `clearance_complete` purely by the clock advancing, with no request made at
        all"

        Design: Difficulty/resource_temporal_overlap/overlap_clearance_validity_window_upper_edge_exclusive
        """
        bundle = _dunmore_with_fresh_clearances(api)
        ctx = bundle["ctx"]
        _initial_visit_finalized_one_second_before_expiry(api, bundle)

        fx.set_clock(api, "2031-08-01T00:00:00Z")

        person = validate_success(
            api.get_staff_member(ctx.director["id"], headers=supervisor_headers())
        )
        assert person["clearance_status"] == "PENDING"
        lapsed = ctx.reload()
        assert lapsed["clearance_complete"] is False

        validate_error(
            api.license_decision(ctx.id, "ISSUE", headers=supervisor_headers()),
            "ERR_CLEARANCE_INCOMPLETE",
            409,
        )

        after = ctx.reload()
        assert after["license_status"] == "NONE"
        assert after["application_status"] == "INITIAL_INSPECTION_PASSED"
        assert_capacity_slots(after, 0, 0)
        room = ctx.reload_roster("PRESCHOOL")
        assert room["approved_group_size"] == 0, (
            "the refused decision must not approve any group size"
        )

        for check_type in ("FBI_FINGERPRINT", "CHILD_ABUSE_REGISTRY"):
            check = validate_success(
                api.get_background_check(
                    ctx.director_checks[check_type]["id"], headers=bgu_headers()
                )
            )
            assert check["status"] == "CLEARED", (
                "the clearance lapsed by the clock crossing the exclusive upper edge, "
                "not by any state transition"
            )
