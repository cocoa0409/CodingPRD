"""Header authentication, entity-backed identity, scoping, pagination bounds and clock timing.

Every test in this module drives the service from an empty database with the logical
clock at its process-start value, and builds each precondition through the public API.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    UNRECOGNIZED_IDENTITY,
    ApiErrorId,
    assert_baseline_period,
    assert_reduction_target,
    assert_waste_entry,
    factories,
    fixtures,
    make_corporate_lead_headers,
    make_headers_without_role,
    make_hauler_operator_headers,
    make_kitchen_staff_headers,
    make_platform_admin_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_FOOD_TYPE_ID = "00000000-0000-0000-0000-0000000000fe"


class TestHeaderAuthenticationAndRoleAdmission:
    """The two header checks that precede every other judgement on a request."""

    def test_capture_without_a_role_header_is_rejected(self, api):
        """A fully valid capture body carrying no role header is refused before the body is read.

        PRD Coverage: "If `X-User-Role` is absent or does not name one of those six roles, the
        request fails with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/capture_without_a_role_header_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        world = fixtures.site_with_open_shift()

        payload = factories.create_waste_entry_payload(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            captured_at="2026-08-01T10:00:00Z",
        )
        response = api.create_waste_entry(payload, make_headers_without_role())
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value)

        listed = api.list_waste_entries(make_platform_admin_headers(), shift_id=world["shift"]["id"])
        _, meta = validate_paginated(listed)
        assert meta["total_count"] == 0, "the rejected capture must not have been written"

    def test_role_check_outranks_body_schema_and_returns_403(self, api):
        """Registering a site as kitchen staff with an incomplete body answers on the role, not the schema.

        PRD Coverage: "When both headers are present and well-formed but the caller's role is not
        among the roles the target endpoint admits, the request fails with `ERR_UNAUTHORIZED`."
        "When a single request violates several rules at once, exactly one error is returned — the
        one belonging to the earliest check in the following fixed evaluation order."

        Design: Corner/validations/role_check_outranks_body_schema_and_returns_403
        """
        response = api.create_site({"name": "Harbor Kitchen", "region_code": "NE"}, make_kitchen_staff_headers())
        validate_error(response, ApiErrorId.UNAUTHORIZED.value)

        listed = api.list_sites(make_platform_admin_headers())
        _, meta = validate_paginated(listed)
        assert meta["total_count"] == 0, "no site may be registered by a caller the endpoint does not admit"

    def test_site_manager_identity_that_is_not_a_site_is_rejected(self, api):
        """A site manager acting as an identifier that resolves to no site row is refused.

        PRD Coverage: "For either of these two roles, an `X-User-ID` that does not resolve to an
        existing row of the backing entity — no such `Site`, no such `Hauler` — is rejected with
        `ERR_IDENTITY_NOT_RECOGNIZED`."

        Design: Corner/validations/site_manager_identity_that_is_not_a_site_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()

        payload = factories.create_baseline_period_payload(site["id"])
        response = api.create_baseline_period(
            payload, make_site_sustainability_manager_headers(UNRECOGNIZED_IDENTITY)
        )
        validate_error(response, ApiErrorId.IDENTITY_NOT_RECOGNIZED.value)

        listed = api.list_baseline_periods(make_platform_admin_headers(), site_id=site["id"])
        _, meta = validate_paginated(listed)
        assert meta["total_count"] == 0, "an unrecognised identity must not open a baseline window"


class TestPaginationBounds:
    """The declared limit ceiling on every list read."""

    def test_pagination_limit_above_one_hundred_is_rejected(self, api):
        """A limit of 101 is a pagination error while a limit of exactly 100 is served.

        PRD Coverage: "`limit` defaults to 10 when omitted, has a minimum accepted value of 1 and a
        maximum accepted value of 100." "A `limit` that is not an integer, is below 1 or is above
        100, or an `offset` that is not an integer or is negative, is rejected with
        `ERR_INVALID_PAGINATION`."

        Design: Corner/validations/pagination_limit_above_one_hundred_is_rejected
        """
        fixtures.create_site()

        rejected = api.list_sites(make_platform_admin_headers(), limit=101)
        validate_error(rejected, ApiErrorId.INVALID_PAGINATION.value)

        accepted = api.list_sites(make_platform_admin_headers(), limit=100)
        rows, meta = validate_paginated(accepted)
        assert accepted.status_code == 200
        assert meta["limit"] == 100
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestSiteAndHaulerScoping:
    """Ownership is enforced on the acting identity rather than on the role alone."""

    def test_site_manager_cannot_open_a_baseline_for_another_site(self, api):
        """The recognised manager of one kitchen may not open a baseline naming a different kitchen.

        PRD Coverage: "A `SiteSustainabilityManager` may only write rows whose `site_id` equals
        their `X-User-ID`; every other write in their reach is refused with
        `ERR_SITE_SCOPE_VIOLATION`."

        Design: Corner/validations/site_manager_cannot_open_a_baseline_for_another_site
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site_a = fixtures.create_site(name="Harbor Kitchen", site_code="HK-01")
        site_b = fixtures.create_site(name="Hillside Kitchen", site_code="HK-02")

        payload = factories.create_baseline_period_payload(site_b["id"])
        response = api.create_baseline_period(payload, make_site_sustainability_manager_headers(site_a["id"]))
        validate_error(response, ApiErrorId.SITE_SCOPE_VIOLATION.value)

        listed = api.list_baseline_periods(make_platform_admin_headers(), site_id=site_b["id"])
        _, meta = validate_paginated(listed)
        assert meta["total_count"] == 0, "a foreign baseline window must not be created"

    def test_hauler_cannot_dispatch_another_haulers_consignment(self, api):
        """A second approved hauler cannot collect a staged load that belongs to the first.

        PRD Coverage: "A `HaulerOperator` may only act on a consignment or weigh ticket whose
        `hauler_id` equals their `X-User-ID`, and violations are refused with
        `ERR_HAULER_SCOPE_VIOLATION`."

        Design: Corner/validations/hauler_cannot_dispatch_another_haulers_consignment
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        world = fixtures.staged_consignment(
            allocated_weight_grams=400,
            entry_overrides={"captured_at": "2026-08-01T10:00:00Z"},
            consignment_overrides={
                "pickup_window_start": "2026-08-02T09:00:00Z",
                "pickup_window_end": "2026-08-02T11:00:00Z",
            },
        )
        collecting_hauler = world["hauler"]
        foreign_hauler = fixtures.create_approved_hauler(
            name="Blue Haul", rate_cents_per_tonne=49000, stop_fee_cents=1500
        )
        consignment_id = world["consignment"]["id"]

        refused = api.dispatch_consignment(consignment_id, make_hauler_operator_headers(foreign_hauler["id"]))
        validate_error(refused, ApiErrorId.HAULER_SCOPE_VIOLATION.value)
        assert fixtures.read_consignment(consignment_id)["logistics_status"] == "STAGED"

        allowed = api.dispatch_consignment(consignment_id, make_hauler_operator_headers(collecting_hauler["id"]))
        dispatched = validate_success(allowed, 200)
        assert dispatched["logistics_status"] == "DISPATCHED"


class TestPathIdentifierResolvedBeforeBody:
    """The single path identifier is settled before any foreign key in the body."""

    def test_unknown_correction_path_id_outranks_the_unknown_body_food_type_not_found(self, api):
        """A correction aimed at no capture reports the missing capture, not the missing food type.

        PRD Coverage: "That single identifier is resolved before any body content is inspected, and
        a path identifier that names no existing row yields that entity's not-found error."

        Design: Corner/validations/unknown_correction_path_id_outranks_the_unknown_body_food_type_not_found
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        world = fixtures.site_with_one_capture(entry_overrides={"captured_at": "2026-08-01T10:00:00Z"})

        payload = factories.correction_payload(
            world["entry"]["version"],
            correction_note="aimed at nothing",
            food_type_id=UNKNOWN_FOOD_TYPE_ID,
        )
        response = api.correct_waste_entry(NON_EXISTENT_UUID, payload, make_shift_lead_headers("sl-2"))
        validate_error(response, ApiErrorId.ENTRY_NOT_FOUND.value)

        listed = api.list_waste_entries(make_platform_admin_headers(), shift_id=world["shift"]["id"])
        _, meta = validate_paginated(listed)
        assert meta["total_count"] == 1, "the real capture must be untouched and no successor written"


class TestLogicalClockTiming:
    """Capture timing and clock monotonicity are both judged against the logical clock."""

    def test_capture_timestamped_after_the_clock_is_rejected(self, api):
        """One second past the pinned clock is already the future; the clock instant itself is accepted.

        PRD Coverage: "The `captured_at` instant must not be later than the current logical clock —
        a strictly future instant is refused with `ERR_CAPTURE_IN_FUTURE` — and the calendar date of
        `captured_at` must equal the period's `shift_date`, with any other date refused as
        `ERR_CAPTURE_OUTSIDE_SHIFT_DATE`."

        Design: Corner/validations/capture_timestamped_after_the_clock_is_rejected
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        world = fixtures.site_with_open_shift()

        future = factories.create_waste_entry_payload(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            captured_at="2026-08-01T12:00:01Z",
        )
        validate_error(
            api.create_waste_entry(future, make_kitchen_staff_headers()),
            ApiErrorId.CAPTURE_IN_FUTURE.value,
        )

        on_the_clock = factories.create_waste_entry_payload(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            captured_at="2026-08-01T12:00:00Z",
        )
        entry = validate_success(api.create_waste_entry(on_the_clock, make_kitchen_staff_headers()), 201)
        assert_waste_entry(entry)
        assert entry["status"] == "RECORDED"

    def test_setting_the_clock_backwards_is_rejected(self, api):
        """An earlier instant is refused and the stored clock value survives untouched.

        PRD Coverage: "The clock may only move forward: a `current_utc` that is not strictly greater
        than the currently stored value is rejected with `ERR_CLOCK_NOT_MONOTONIC`."
        "Three optional inputs follow: a `recipe_id` attributing the loss to a published recipe, a
        `captured_at` instant which defaults to the current logical clock when omitted, and a
        free-text operator `note`."

        Design: Corner/validations/setting_the_clock_backwards_is_rejected
        """
        fixtures.set_clock("2026-08-02T00:00:00Z")

        validate_error(api.set_clock("2026-08-01T23:59:59Z"), ApiErrorId.CLOCK_NOT_MONOTONIC.value)

        world = fixtures.site_with_open_shift(shift_overrides={"shift_date": "2026-08-02"})
        entry = fixtures.capture_entry(world["station"]["id"], world["shift"]["id"], world["food_type"]["id"])
        assert entry["captured_at"].startswith("2026-08-02T00:00:00"), (
            "a defaulted captured_at proves the logical clock never moved backwards"
        )


class TestInclusiveWindowBoundaries:
    """Baseline windows and performance windows are both judged on inclusive endpoints."""

    def test_overlapping_baseline_windows_are_rejected_on_the_shared_end_date(self, api):
        """A second window opening on the first window's last day collides; the next day does not.

        PRD Coverage: "The window is inclusive on both ends. A new period whose inclusive date
        interval intersects an existing period of the same site is refused with
        `ERR_BASELINE_WINDOW_OVERLAP`."

        Design: Corner/validations/overlapping_baseline_windows_are_rejected_on_the_shared_end_date
        """
        fixtures.set_clock("2026-08-06T12:00:00Z")
        site = fixtures.create_site()
        fixtures.open_baseline(site["id"], start_date="2026-08-01", end_date="2026-08-05")
        headers = make_site_sustainability_manager_headers(site["id"])

        colliding = factories.create_baseline_period_payload(
            site["id"], start_date="2026-08-05", end_date="2026-08-09"
        )
        validate_error(
            api.create_baseline_period(colliding, headers),
            ApiErrorId.BASELINE_WINDOW_OVERLAP.value,
        )

        listed = api.list_baseline_periods(make_platform_admin_headers(), site_id=site["id"])
        _, meta = validate_paginated(listed)
        assert meta["total_count"] == 1, "the colliding window must not have been opened"

        adjoining = factories.create_baseline_period_payload(
            site["id"], start_date="2026-08-06", end_date="2026-08-09"
        )
        opened = validate_success(api.create_baseline_period(adjoining, headers), 201)
        assert_baseline_period(opened)
        assert opened["status"] == "OPEN"

    def test_target_window_starting_on_the_baseline_end_date_is_rejected(self, api):
        """Reusing the baseline's own last day as the first performance day is refused.

        PRD Coverage: "The performance window must begin strictly after the baseline it is measured
        against ends: a `window_start` that is not strictly later than the bound period's `end_date`
        is refused with `ERR_TARGET_WINDOW_BEFORE_BASELINE`, which is what keeps a target from
        grading itself against overlapping data."

        Design: Corner/validations/target_window_starting_on_the_baseline_end_date_is_rejected
        """
        fixtures.set_clock("2026-08-01T20:00:00Z")
        world = fixtures.certified_baseline(entry_overrides={"captured_at": "2026-08-01T10:00:00Z"})
        site = fixtures.read_site(world["site"]["id"])
        headers = make_corporate_lead_headers()

        overlapping = factories.create_reduction_target_payload(
            site["id"],
            world["baseline"]["id"],
            site["version"],
            window_start="2026-08-01",
            window_end="2026-08-31",
        )
        validate_error(
            api.create_reduction_target(overlapping, headers),
            ApiErrorId.TARGET_WINDOW_BEFORE_BASELINE.value,
        )

        listed = api.list_reduction_targets(make_platform_admin_headers(), site_id=site["id"])
        _, meta = validate_paginated(listed)
        assert meta["total_count"] == 0, "no target may be written against an overlapping window"

        following_day = factories.create_reduction_target_payload(
            site["id"],
            world["baseline"]["id"],
            site["version"],
            window_start="2026-08-02",
            window_end="2026-08-31",
        )
        target = validate_success(api.create_reduction_target(following_day, headers), 201)
        assert_reduction_target(target)
        assert target["status"] == "PROPOSED"
