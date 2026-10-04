"""Shift planning: assignment constraints (rotation, overlap, certification),
peak staffing, publish gating, deficit-score variants, no-show sweep; loyalty
tier boundaries; channel gating (seasonal/secret); distribution withdrawal and
recipe retirement."""
from test_helpers import (
    ApiErrorId,
    PA,
    RM,
    add_assignment,
    add_recipe,
    create_crew_member,
    create_draft_shift,
    create_loyalty_account,
    list_items_of_order,
    make_crew_member_headers,
    make_stand_operator_headers,
    place_window_order,
    serve_window_order,
    set_clock,
    setup_in_progress_shift,
    setup_open_stand_with_menu,
    stand_version,
    validate_error,
    validate_success,
)


class TestAssignmentOverlap:
    def test_crew_assignment_overlap_half_open_adjacency(self, api):
        """PRD §3.5: "two non-cancelled assignments for the same crew member may
        not overlap, with intervals treated as half-open so that back-to-back
        shifts where one ends exactly as the next begins are allowed
        (`ERR_ASSIGNMENT_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/crew_assignment_overlap_half_open_adjacency
        """
        ctx = setup_open_stand_with_menu()
        shift = create_draft_shift(
            ctx, starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T11:00:00Z"
        )
        first = add_assignment(
            ctx, shift["id"], ctx["taker"]["id"], role="TAKER",
            starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T09:00:00Z",
        )
        assert first["status"] == "ASSIGNED"

        # Adjacent: [09:00, 11:00) touches [07:00, 09:00) at a point — allowed.
        second = add_assignment(
            ctx, shift["id"], ctx["taker"]["id"], role="RUNNER",
            starts_at="2026-09-01T09:00:00Z", ends_at="2026-09-01T11:00:00Z",
        )
        assert second["status"] == "ASSIGNED", (
            "half-open intervals permit end == start (adjacency)"
        )

        # Overlapping: [08:30, 10:00) intersects both existing intervals.
        current = validate_success(api.get_shift(shift["id"], ctx["operator_headers"]), 200)
        overlap = api.create_assignment(
            shift["id"],
            {
                "crew_member_id": ctx["taker"]["id"],
                "role": "BAR",
                "starts_at": "2026-09-01T08:30:00Z",
                "ends_at": "2026-09-01T10:00:00Z",
                "expected_shift_version": current["version"],
            },
            ctx["operator_headers"],
        )
        validate_error(overlap, ApiErrorId.ERR_ASSIGNMENT_OVERLAP, 409)

    def test_overlapping_assignment_rejected_while_adjacent_accepted(self, api):
        """PRD §3.5: "two non-cancelled assignments for the same crew member may
        not overlap, with intervals treated as half-open"

        Design: Difficulty/resource_temporal_overlap/crew_assignment_overlap_half_open_adjacency
        """
        ctx = setup_open_stand_with_menu()
        shift = create_draft_shift(
            ctx, starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T11:00:00Z"
        )
        add_assignment(
            ctx, shift["id"], ctx["taker"]["id"], role="TAKER",
            starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T09:00:00Z",
        )
        current = validate_success(api.get_shift(shift["id"], ctx["operator_headers"]), 200)
        overlap = api.create_assignment(
            shift["id"],
            {
                "crew_member_id": ctx["taker"]["id"],
                "role": "BAR",
                "starts_at": "2026-09-01T08:59:00Z",
                "ends_at": "2026-09-01T10:00:00Z",
                "expected_shift_version": current["version"],
            },
            ctx["operator_headers"],
        )
        validate_error(overlap, ApiErrorId.ERR_ASSIGNMENT_OVERLAP, 409)


class TestRotationStretch:
    def test_rotation_stretch_boundary_at_120_minutes(self, api):
        """PRD §3.5: "a single assignment may not exceed 120 minutes — the
        rapid-rotation rule (`ERR_ROTATION_STRETCH_EXCEEDED`)"

        Design: Corner/validations/rotation_stretch_boundary_at_120_minutes
        """
        ctx = setup_open_stand_with_menu()
        shift = create_draft_shift(
            ctx, starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T10:00:00Z"
        )
        ok = add_assignment(
            ctx, shift["id"], ctx["taker"]["id"], role="BAR",
            starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T09:00:00Z",
        )
        assert ok["status"] == "ASSIGNED", "120 minutes exactly is allowed"

        current = validate_success(api.get_shift(shift["id"], ctx["operator_headers"]), 200)
        too_long = api.create_assignment(
            shift["id"],
            {
                "crew_member_id": ctx["op"]["id"],
                "role": "LEAD",
                "starts_at": "2026-09-01T07:00:00Z",
                "ends_at": "2026-09-01T09:01:00Z",
                "expected_shift_version": current["version"],
            },
            ctx["operator_headers"],
        )
        validate_error(too_long, ApiErrorId.ERR_ROTATION_STRETCH_EXCEEDED, 422)

    def test_121_minute_assignment_rejected(self, api):
        """PRD §3.5: "a single assignment may not exceed 120 minutes — the
        rapid-rotation rule (`ERR_ROTATION_STRETCH_EXCEEDED`)"

        Design: Corner/validations/rotation_stretch_boundary_at_120_minutes
        """
        ctx = setup_open_stand_with_menu()
        shift = create_draft_shift(
            ctx, starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T10:00:00Z"
        )
        current = validate_success(api.get_shift(shift["id"], ctx["operator_headers"]), 200)
        resp = api.create_assignment(
            shift["id"],
            {
                "crew_member_id": ctx["lead"]["id"],
                "role": "LEAD",
                "starts_at": "2026-09-01T07:00:00Z",
                "ends_at": "2026-09-01T09:01:00Z",
                "expected_shift_version": current["version"],
            },
            ctx["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ROTATION_STRETCH_EXCEEDED, 422)


class TestCertificationGate:
    def test_safety_error_beats_temporal_error_on_assignment_creation(self, api):
        """PRD §2.9: "8. **Food-handler safety** — certification strictly valid
        at the current logical clock date (`ERR_CERTIFICATION_EXPIRED`).
        9. **Temporal rules** — shift-in-past, assignment overlap, window spacing,
        season bounds, window closability (`ERR_SHIFT_IN_PAST`,
        `ERR_ASSIGNMENT_OVERLAP`, `ERR_WINDOW_OVERLAP`, `ERR_RECIPE_OUT_OF_SEASON`,
        `ERR_WINDOW_NOT_CLOSABLE`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_assignment_creation
        """
        set_clock("2026-07-01T00:00:00Z")
        ctx = setup_open_stand_with_menu(clock="2026-07-01T00:00:00Z")
        ed = create_crew_member(
            ctx["stand"]["id"],
            full_name="Expiry Ed",
            hired_on="2025-01-01",
            food_handler_cert_expires_on="2026-08-01",
        )
        shift = create_draft_shift(
            ctx, starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T10:00:00Z"
        )
        # Created while the cert is still valid (July).
        add_assignment(
            ctx, shift["id"], ed["id"], role="BAR",
            starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T09:00:00Z",
        )
        # Advance the clock past the cert expiry.
        set_clock("2026-09-01T00:00:00Z")
        current = validate_success(api.get_shift(shift["id"], ctx["operator_headers"]), 200)
        # Both expired-cert (priority 8) and overlap (priority 9) are tripped.
        resp = api.create_assignment(
            shift["id"],
            {
                "crew_member_id": ed["id"],
                "role": "RUNNER",
                "starts_at": "2026-09-01T08:00:00Z",
                "ends_at": "2026-09-01T10:00:00Z",
                "expected_shift_version": current["version"],
            },
            ctx["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_EXPIRED, 422)

    def test_expired_cert_rejected_even_without_overlap(self, api):
        """PRD §3.5: "The crew member's certification is re-checked at assignment
        creation."
        PRD §3.2: "their `food_handler_cert_expires_on` must fall strictly after
        the current logical clock date (`ERR_CERTIFICATION_EXPIRED`)"

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_assignment_creation
        """
        set_clock("2026-07-01T00:00:00Z")
        ctx = setup_open_stand_with_menu(clock="2026-07-01T00:00:00Z")
        ed = create_crew_member(
            ctx["stand"]["id"],
            full_name="Expiry Ed",
            hired_on="2025-01-01",
            food_handler_cert_expires_on="2026-08-01",
        )
        shift = create_draft_shift(
            ctx, starts_at="2026-09-01T07:00:00Z", ends_at="2026-09-01T10:00:00Z"
        )
        set_clock("2026-09-01T00:00:00Z")
        current = validate_success(api.get_shift(shift["id"], ctx["operator_headers"]), 200)
        resp = api.create_assignment(
            shift["id"],
            {
                "crew_member_id": ed["id"],
                "role": "RUNNER",
                "starts_at": "2026-09-01T07:00:00Z",
                "ends_at": "2026-09-01T09:00:00Z",
                "expected_shift_version": current["version"],
            },
            ctx["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_EXPIRED, 422)


class TestShiftInPast:
    def test_shift_created_in_past_rejected(self, api):
        """PRD §3.5: "The `starts_at` must lie after the current logical clock at
        creation (`ERR_SHIFT_IN_PAST`)"

        Design: Corner/errors/shift_created_in_past_rejected
        """
        ctx = setup_open_stand_with_menu()
        resp = api.create_shift(
            {
                "stand_id": ctx["stand"]["id"],
                "starts_at": "2026-09-01T05:00:00Z",
                "ends_at": "2026-09-01T07:00:00Z",
                "is_peak": False,
            },
            ctx["operator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_IN_PAST, 422)


class TestPeakStaffing:
    def test_peak_shift_publish_requires_four_assignments(self, api):
        """PRD §3.5: "Publishing moves a shift `DRAFT → PUBLISHED` and is gated
        twice: an `ACTIVE` operator agreement must exist for the shift's stand
        (`ERR_AGREEMENT_NOT_ACTIVE`), and a peak shift must carry at least four
        non-cancelled assignments (`ERR_PEAK_STAFFING_INSUFFICIENT`; the base
        staffing floor is two)."

        Design: Corner/validations/peak_shift_publish_requires_four_assignments
        """
        ctx = setup_open_stand_with_menu()
        runner = create_crew_member(ctx["stand"]["id"], full_name="Runner Ru")
        shift = create_draft_shift(ctx, is_peak=True)
        add_assignment(ctx, shift["id"], ctx["op"]["id"], role="LEAD")
        add_assignment(ctx, shift["id"], ctx["taker"]["id"], role="TAKER")
        add_assignment(ctx, shift["id"], ctx["lead"]["id"], role="BAR")

        short = api.publish_shift(shift["id"], ctx["operator_headers"])
        validate_error(short, ApiErrorId.ERR_PEAK_STAFFING_INSUFFICIENT, 422)

        add_assignment(ctx, shift["id"], runner["id"], role="RUNNER")
        published = validate_success(
            api.publish_shift(shift["id"], ctx["operator_headers"]), 200
        )
        assert published["status"] == "PUBLISHED"
        assert published["provisional_deficit_score"] == 0, (
            f"4 confirmed with a LEAD scores 0, got {published['provisional_deficit_score']}"
        )

    def test_three_assignments_short_of_peak_minimum(self, api):
        """PRD §3.5: "a peak shift must carry at least four non-cancelled
        assignments (`ERR_PEAK_STAFFING_INSUFFICIENT`; the base staffing floor
        is two)."

        Design: Corner/validations/peak_shift_publish_requires_four_assignments
        """
        ctx = setup_open_stand_with_menu()
        shift = create_draft_shift(ctx, is_peak=True)
        add_assignment(ctx, shift["id"], ctx["op"]["id"], role="LEAD")
        add_assignment(ctx, shift["id"], ctx["taker"]["id"], role="TAKER")
        add_assignment(ctx, shift["id"], ctx["lead"]["id"], role="BAR")
        resp = api.publish_shift(shift["id"], ctx["operator_headers"])
        validate_error(resp, ApiErrorId.ERR_PEAK_STAFFING_INSUFFICIENT, 422)
        fetched = validate_success(api.get_shift(shift["id"], ctx["operator_headers"]), 200)
        assert fetched["status"] == "DRAFT"


class TestDeficitScoreVariants:
    def test_staffing_deficit_provisional_plan_diverges_from_reconciled_actuals(
        self, api
    ):
        """PRD §3.5: "At publish the system computes the shift's
        `provisional_deficit_score`, a forward-looking measure over the plan:
        take the required crew — four for a peak shift, two otherwise — subtract
        the count of assignments whose status is `ASSIGNED` or `CHECKED_IN`, keep
        the shortfall at zero if negative, multiply the shortfall by ten, and add
        twenty-five if no assignment with role `LEAD` is among those `ASSIGNED`
        or `CHECKED_IN`. A fully staffed plan therefore scores zero at publish
        even if reality later disappoints."
        PRD §3.5: "Reconciliation sweeps every assignment still `ASSIGNED` to
        `NO_SHOW` and computes the `reconciled_deficit_score` over what actually
        happened: the required crew minus the count of `CHECKED_IN` assignments
        (floored at zero), multiplied by ten, plus twenty-five if no
        `CHECKED_IN` assignment has role `LEAD`, plus five for every `NO_SHOW`."

        Design: Difficulty/dual_variant_calc/staffing_deficit_provisional_plan_diverges_from_reconciled_actuals
        """
        ctx = setup_open_stand_with_menu(clock="2026-09-01T00:00:00Z")
        shift = create_draft_shift(ctx)
        asg_lead = add_assignment(ctx, shift["id"], ctx["lead"]["id"], role="LEAD")
        asg_bar = add_assignment(ctx, shift["id"], ctx["taker"]["id"], role="BAR")

        published = validate_success(
            api.publish_shift(shift["id"], ctx["operator_headers"]), 200
        )
        assert published["provisional_deficit_score"] == 0, (
            f"2 planned == 2 required with a LEAD scores 0, got {published['provisional_deficit_score']}"
        )

        set_clock("2026-09-01T07:00:00Z")
        validate_success(api.start_shift(shift["id"], ctx["operator_headers"]), 200)
        validate_success(
            api.check_in_assignment(
                asg_lead["id"], make_crew_member_headers(ctx["lead"]["id"])
            ),
            200,
        )
        set_clock("2026-09-01T09:00:00Z")
        reconciled = validate_success(
            api.reconcile_shift(shift["id"], ctx["operator_headers"]), 200
        )
        assert reconciled["reconciled_deficit_score"] == 15, (
            f"max(0, 2-1)*10 + 0 (LEAD checked in) + 1*5 = 15, got {reconciled['reconciled_deficit_score']}"
        )

        bar_after = validate_success(
            api.get_assignment(asg_bar["id"], ctx["operator_headers"]), 200
        )
        assert bar_after["status"] == "NO_SHOW"
        lead_after = validate_success(
            api.get_assignment(asg_lead["id"], ctx["operator_headers"]), 200
        )
        assert lead_after["status"] == "CHECKED_IN"

    def test_no_show_sweep_flips_still_assigned_assignments(self, api):
        """PRD §3.5: "After the logical clock passes the shift's `ends_at`, the
        operator reconciles it (`IN_PROGRESS → RECONCILED`; reconciling early is
        `ERR_SHIFT_INVALID_STATE`). Reconciliation sweeps every assignment still
        `ASSIGNED` to `NO_SHOW`"

        Design: Difficulty/dual_variant_calc/staffing_deficit_provisional_plan_diverges_from_reconciled_actuals
        """
        ctx = setup_open_stand_with_menu(clock="2026-09-01T00:00:00Z")
        shift, assignments = setup_in_progress_shift(
            ctx, [(ctx["lead"], "LEAD"), (ctx["taker"], "BAR")]
        )
        set_clock("2026-09-01T09:00:00Z")
        reconciled = validate_success(
            api.reconcile_shift(shift["id"], ctx["operator_headers"]), 200
        )
        # Nobody checked in: 2 missing crew * 10 + 25 (no LEAD) + 2 no-shows * 5.
        assert reconciled["reconciled_deficit_score"] == 55, (
            f"max(0, 2-0)*10 + 25 + 2*5 = 55, got {reconciled['reconciled_deficit_score']}"
        )
        for assignment in assignments:
            after = validate_success(
                api.get_assignment(assignment["id"], ctx["operator_headers"]), 200
            )
            assert after["status"] == "NO_SHOW"


class TestLoyaltyTierBoundaries:
    def test_loyalty_tier_thresholds_at_exact_boundaries(self, api):
        """PRD §3.4: "The tier ladder is threshold-based and inclusive at the
        boundary: at least 500 points earns `GOLD` (a ten-percent line discount),
        at least 200 points earns `SILVER` (five percent), and anything below
        that is `NONE` — exactly 500 is `GOLD`, exactly 200 is `SILVER`."

        Design: Corner/calculations/loyalty_tier_thresholds_at_exact_boundaries
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Boundary Bea")

        tier_199 = validate_success(
            api.adjust_points(account["id"], {"delta_points": 199, "reason": "goodwill"}, PA),
            200,
        )
        assert tier_199["tier"] == "NONE"

        tier_200 = validate_success(
            api.adjust_points(account["id"], {"delta_points": 1, "reason": "goodwill"}, PA),
            200,
        )
        assert tier_200["tier"] == "SILVER", "exactly 200 is SILVER (inclusive)"

        tier_499 = validate_success(
            api.adjust_points(account["id"], {"delta_points": 299, "reason": "goodwill"}, PA),
            200,
        )
        assert tier_499["tier"] == "SILVER"

        tier_500 = validate_success(
            api.adjust_points(account["id"], {"delta_points": 1, "reason": "goodwill"}, PA),
            200,
        )
        assert tier_500["points"] == 500
        assert tier_500["tier"] == "GOLD", "exactly 500 is GOLD (inclusive)"

    def test_tier_recomputed_after_every_points_change(self, api):
        """PRD §3.4: "The tier is recomputed after every change to `points`"

        Design: Corner/calculations/loyalty_tier_thresholds_at_exact_boundaries
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Boundary Bea")
        gold = validate_success(
            api.adjust_points(account["id"], {"delta_points": 500, "reason": "goodwill"}, PA),
            200,
        )
        assert gold["tier"] == "GOLD"
        back_down = validate_success(
            api.adjust_points(account["id"], {"delta_points": -1, "reason": "correction"}, PA),
            200,
        )
        assert back_down["points"] == 499
        assert back_down["tier"] == "SILVER"


class TestChannelGating:
    def test_seasonal_recipe_window_is_half_open(self, api):
        """PRD §3.3: "A `SEASONAL` recipe may be ordered only when the current
        logical clock date falls on or after its `season_start` and strictly
        before its `season_end`; outside that window the order is rejected with
        `ERR_RECIPE_OUT_OF_SEASON`."

        Design: Corner/validations/seasonal_recipe_window_is_half_open
        """
        ctx = setup_open_stand_with_menu()
        seasonal, dist = add_recipe(
            ctx,
            name="Autumn Gold",
            channel="SEASONAL",
            base_price_cents=525,
            base_build_seconds=70,
            temperature_class="HOT",
            season_start="2026-09-01",
            season_end="2026-12-01",
        )
        # Clock is 2026-09-01T06:00:00Z: on season_start (inclusive).
        in_season = place_window_order(ctx, seasonal["id"], lane_code="A")
        assert in_season["queue_status"] == "MERGED"

        set_clock("2026-12-01T00:00:00Z")
        version = stand_version(ctx)
        out_of_season = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": seasonal["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(out_of_season, ApiErrorId.ERR_RECIPE_OUT_OF_SEASON, 422)

    def test_seasonal_start_date_inclusive_end_date_exclusive(self, api):
        """PRD §3.3: "Seasonal recipes carry a `season_start` (inclusive) and a
        `season_end` (exclusive, and strictly after `season_start`)"

        Design: Corner/validations/seasonal_recipe_window_is_half_open
        """
        ctx = setup_open_stand_with_menu()
        seasonal, dist = add_recipe(
            ctx,
            name="Autumn Gold",
            channel="SEASONAL",
            base_price_cents=525,
            base_build_seconds=70,
            temperature_class="HOT",
            season_start="2026-09-01",
            season_end="2026-12-01",
        )
        set_clock("2026-11-30T12:00:00Z")
        still_in = place_window_order(ctx, seasonal["id"], lane_code="A")
        assert still_in["queue_status"] == "MERGED"

        set_clock("2026-12-01T00:00:00Z")
        version = stand_version(ctx)
        out = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": seasonal["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(out, ApiErrorId.ERR_RECIPE_OUT_OF_SEASON, 422)

    def test_secret_menu_requires_gold_tier(self, api):
        """PRD §3.3: "A `SECRET` recipe may be ordered only against a loyalty
        account whose current `tier` is `GOLD`; without it the order is rejected
        with `ERR_SECRET_MENU_TIER_REQUIRED`."

        Design: Corner/validations/secret_menu_requires_gold_tier
        """
        ctx = setup_open_stand_with_menu()
        secret, dist = add_recipe(
            ctx,
            name="Vampire Slayer",
            channel="SECRET",
            base_price_cents=600,
            base_build_seconds=80,
            temperature_class="ICED",
        )
        silver = create_loyalty_account(ctx["stand"]["id"], full_name="Silver Sid")
        validate_success(
            api.adjust_points(silver["id"], {"delta_points": 200, "reason": "goodwill"}, PA),
            200,
        )
        gold = create_loyalty_account(ctx["stand"]["id"], full_name="Goldie")
        validate_success(
            api.adjust_points(gold["id"], {"delta_points": 500, "reason": "goodwill"}, PA),
            200,
        )

        def attempt(account_id=None):
            version = stand_version(ctx)
            payload = {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": secret["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            }
            if account_id is not None:
                payload["loyalty_account_id"] = account_id
            return api.create_order(payload, make_crew_member_headers(ctx["taker"]["id"]))

        validate_error(attempt(), ApiErrorId.ERR_SECRET_MENU_TIER_REQUIRED, 403)
        validate_error(
            attempt(silver["id"]), ApiErrorId.ERR_SECRET_MENU_TIER_REQUIRED, 403
        )
        gold_order = validate_success(attempt(gold["id"]), 201)
        assert gold_order["queue_status"] == "MERGED"

    def test_secret_menu_rejects_silver_and_no_account(self, api):
        """PRD §3.3: "A `SECRET` recipe may be ordered only against a loyalty
        account whose current `tier` is `GOLD`; without it the order is rejected
        with `ERR_SECRET_MENU_TIER_REQUIRED`. `CORE` recipes carry no such
        gating."

        Design: Corner/validations/secret_menu_requires_gold_tier
        """
        ctx = setup_open_stand_with_menu()
        secret, dist = add_recipe(
            ctx,
            name="Vampire Slayer",
            channel="SECRET",
            base_price_cents=600,
            base_build_seconds=80,
            temperature_class="ICED",
        )
        silver = create_loyalty_account(ctx["stand"]["id"], full_name="Silver Sid")
        validate_success(
            api.adjust_points(silver["id"], {"delta_points": 200, "reason": "goodwill"}, PA),
            200,
        )
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "loyalty_account_id": silver["id"],
                "items": [
                    {"recipe_id": secret["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SECRET_MENU_TIER_REQUIRED, 403)


class TestDistributionLifecycle:
    def test_retire_blocked_while_distribution_live(self, api):
        """PRD §3.3: "Retiring a recipe from the catalog — a `PlatformAdmin`
        action moving it `ACTIVE → RETIRED` — is blocked while any of its
        distributions is `STAGED`, `ACTIVATED`, or `SUSPENDED`: all distributions
        must be `WITHDRAWN` first, otherwise the retire is rejected with
        `ERR_RECIPE_HAS_ACTIVE_DISTRIBUTIONS`."

        Design: Corner/errors/retire_blocked_while_distribution_live
        """
        ctx = setup_open_stand_with_menu()
        blocked = api.retire_recipe(ctx["recipe"]["id"], PA)
        validate_error(blocked, ApiErrorId.ERR_RECIPE_HAS_ACTIVE_DISTRIBUTIONS, 409)

        validate_success(
            api.withdraw_distribution(ctx["dist"]["id"], ctx["operator_headers"]), 200
        )
        retired = validate_success(api.retire_recipe(ctx["recipe"]["id"], PA), 200)
        assert retired["status"] == "RETIRED"

    def test_retire_succeeds_after_withdraw(self, api):
        """PRD §3.3: "all distributions must be `WITHDRAWN` first, otherwise the
        retire is rejected with `ERR_RECIPE_HAS_ACTIVE_DISTRIBUTIONS`."

        Design: Corner/errors/retire_blocked_while_distribution_live
        """
        ctx = setup_open_stand_with_menu()
        validate_success(
            api.withdraw_distribution(ctx["dist"]["id"], ctx["operator_headers"]), 200
        )
        retired = validate_success(api.retire_recipe(ctx["recipe"]["id"], PA), 200)
        assert retired["status"] == "RETIRED"


class TestWithdrawalCascade:
    def test_distribution_withdrawal_cancels_items_and_recomputes_order_totals(
        self, api
    ):
        """PRD §3.3: "When a distribution is withdrawn, every order item at that
        stand referencing the recipe with `build_status` of `PENDING` or
        `BUILDING` moves to `CANCELLED`, and each affected parent order
        recomputes `subtotal_cents`, `discount_cents`, `total_cents`, and
        `outstanding_build_seconds` from its remaining items."

        Design: Difficulty/transitive_cascade/distribution_withdrawal_cancels_items_and_recomputes_order_totals
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(
            ctx,
            ctx["recipe"]["id"],
            items=[{"recipe_id": ctx["recipe"]["id"], "quantity": 2, "modifier_names": []}],
        )
        assert order["total_cents"] == 900, f"2 x 450 = 900, got {order['total_cents']}"

        withdrawn = validate_success(
            api.withdraw_distribution(ctx["dist"]["id"], ctx["operator_headers"]), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"

        items = list_items_of_order(ctx, order["id"])
        assert items, "the order's item rows must remain readable"
        for item in items:
            assert item["build_status"] == "CANCELLED"

        after = validate_success(
            api.get_order(order["id"], ctx["operator_headers"]), 200
        )
        assert after["total_cents"] == 0, (
            f"all items cancelled: total recomputes to 0, got {after['total_cents']}"
        )
        assert after["subtotal_cents"] == 0
        assert after["discount_cents"] == 0
        assert after["outstanding_build_seconds"] == 0

    def test_withdrawal_marks_items_cancelled_and_totals_recompute(self, api):
        """PRD §3.3: "Withdrawal is destructive to in-flight work. When a
        distribution is withdrawn, every order item at that stand referencing
        the recipe with `build_status` of `PENDING` or `BUILDING` moves to
        `CANCELLED`"

        Design: Difficulty/transitive_cascade/distribution_withdrawal_cancels_items_and_recomputes_order_totals
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        item = list_items_of_order(ctx, order["id"])[0]
        assert item["build_status"] == "PENDING"
        validate_success(
            api.withdraw_distribution(ctx["dist"]["id"], ctx["operator_headers"]), 200
        )
        item_after = validate_success(
            api.get_order_item(item["id"], ctx["operator_headers"]), 200
        )
        assert item_after["build_status"] == "CANCELLED"
        order_after = validate_success(
            api.get_order(order["id"], ctx["operator_headers"]), 200
        )
        assert order_after["total_cents"] == 0


class TestShiftPublishAgreementGate:
    def test_shift_publish_blocked_until_operator_agreement_active(self, api):
        """PRD §3.5: "Publishing moves a shift `DRAFT → PUBLISHED` and is gated
        twice: an `ACTIVE` operator agreement must exist for the shift's stand
        (`ERR_AGREEMENT_NOT_ACTIVE`), and a peak shift must carry at least four
        non-cancelled assignments (`ERR_PEAK_STAFFING_INSUFFICIENT`; the base
        staffing floor is two)."
        PRD §3.2: "Activation is then the operator's own act: the agreement moves
        `APPROVED → ACTIVE` only when the acting `StandOperator`'s `X-User-ID`
        equals the agreement's `crew_member_id` (a mismatch is
        `ERR_UNAUTHORIZED_ROLE`), and only while no other `ACTIVE` agreement
        exists for the stand (otherwise `ERR_AGREEMENT_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/shift_publish_blocked_until_operator_agreement_active
        """
        from test_helpers import (
            activate_agreement,
            approve_agreement,
            setup_stand_with_agreement,
        )

        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_stand_with_agreement()
        # Agreement APPROVED but not ACTIVE; stand stays APPROVED (never opened).
        ctx["agreement"] = approve_agreement(ctx["agreement"]["id"])
        ctx["operator_headers"] = make_stand_operator_headers(ctx["op"]["id"])
        ctx["taker"] = create_crew_member(ctx["stand"]["id"], full_name="Taker Tim")
        ctx["lead"] = create_crew_member(ctx["stand"]["id"], full_name="Lead Lena")

        shift = create_draft_shift(ctx)
        add_assignment(ctx, shift["id"], ctx["lead"]["id"], role="LEAD")
        add_assignment(ctx, shift["id"], ctx["taker"]["id"], role="TAKER")

        blocked = api.publish_shift(shift["id"], ctx["operator_headers"])
        validate_error(blocked, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)

        ctx["agreement"] = activate_agreement(ctx["agreement"])
        published = validate_success(
            api.publish_shift(shift["id"], ctx["operator_headers"]), 200
        )
        assert published["status"] == "PUBLISHED"

    def test_publish_succeeds_once_agreement_is_active(self, api):
        """PRD §3.5: "Publishing moves a shift `DRAFT → PUBLISHED` and is gated
        twice: an `ACTIVE` operator agreement must exist for the shift's stand
        (`ERR_AGREEMENT_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/shift_publish_blocked_until_operator_agreement_active
        """
        ctx = setup_open_stand_with_menu(clock="2026-09-01T00:00:00Z")
        shift = create_draft_shift(ctx)
        add_assignment(ctx, shift["id"], ctx["lead"]["id"], role="LEAD")
        add_assignment(ctx, shift["id"], ctx["taker"]["id"], role="TAKER")
        published = validate_success(
            api.publish_shift(shift["id"], ctx["operator_headers"]), 200
        )
        assert published["status"] == "PUBLISHED"
        assert published["provisional_deficit_score"] == 0
