"""Authentication, authorization, people operations, and the staffing-posture
gate (PRD sections 2.1/2.5/3.7)."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_associate_payload,
    create_menu_item_payload,
    create_open_store_with_manager,
    create_operational_commissary,
    create_production_run_payload,
    create_shift_payload,
    create_site_store,
    get_success_data,
    hr_closer_headers,
    hr_poster_headers,
    make_associate_headers,
    planner_headers,
    promote_to_shift_lead,
    scd_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_unauthenticated_request_missing_role_header(self, api):
        """PRD section 2.1: "A request whose `X-User-Role` header is missing
        or names anything outside this declared set is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_missing_role_header
        """
        # No role header at all.
        headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
        resp = api.get_menu_item(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401
        # A role outside the declared set.
        bad = build_user_headers("someone", "NotARealRole")
        resp2 = api.get_menu_item(NON_EXISTENT_UUID, bad)
        validate_error(resp2, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp2.status_code == 401


class TestAuthorization:
    def test_quality_auditor_cannot_run_production(self, api):
        """PRD section 2.1: "A request whose role is declared but is not
        permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD section 4: the production-run planning endpoint lists only the
        CommissaryPlanner role.

        Design: Corner/validations/quality_auditor_cannot_run_production
        """
        env = create_operational_commissary()
        auditor = build_user_headers("auditor-1", "QualityAuditor")
        resp = api.create_production_run(
            env["commissary"]["id"],
            create_production_run_payload(run_date="2026-09-02T00:00:00Z"),
            auditor)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403


class TestPromotionGate:
    def test_promotion_below_tenure_threshold_rejected(self, api):
        """PRD section 3.7: "Promotion by an `HRDirector` advances exactly
        one rung along this order and is gated by four conditions, all
        enforced with the boundary inclusivity stated: the associate's tenure
        — whole calendar days from `hired_date` to the clock date — must be
        at least 180 days; the associate must hold at least 2 `SCHEDULED`
        shifts whose `shift_start` is at or after the current clock time;
        their `promotion_count` must be below 6; and their `current_level`
        must not already be `MANAGER`. Any failure is rejected with
        `ERR_PROMOTION_INELIGIBLE` (HTTP 422)."

        Design: Corner/validations/promotion_below_tenure_threshold_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        env = create_operational_commissary()
        store = create_site_store(env["commissary"])
        # Hired 2026-03-05: 179 whole days before the clock — under 180.
        assoc_a = get_success_data(api.create_associate(
            create_associate_payload(store["id"], full_name="Assoc A",
                                     hired_date="2026-03-05T00:00:00Z"),
            hr_poster_headers()))
        resp = api.promote_associate(assoc_a["id"], hr_poster_headers())
        validate_error(resp, ApiErrorId.ERR_PROMOTION_INELIGIBLE)
        assert resp.status_code == 422
        # Hired 2026-03-04: exactly 180 whole days before the clock — the
        # boundary is inclusive ("at least 180 days"), so with the shift gate
        # satisfied the promotion succeeds.
        assoc_b = get_success_data(api.create_associate(
            create_associate_payload(store["id"], full_name="Assoc B",
                                     hired_date="2026-03-04T00:00:00Z"),
            hr_poster_headers()))
        # Satisfy the >= 2 future scheduled-shift gate; the clock is parked
        # inside the first window while scheduling so the store's coverage
        # ratio is non-zero (coverage is checked first in the posture rule).
        windows = [("2026-10-01T16:00:00Z", "2026-10-02T00:00:00Z",
                    "2026-10-01T18:00:00Z"),
                   ("2026-10-02T16:00:00Z", "2026-10-03T00:00:00Z",
                    "2026-10-02T18:00:00Z")]
        for start, end, park in windows:
            set_clock(park)
            get_success_data(api.create_shift(
                store["id"], create_shift_payload(assoc_b["id"], start, end),
                hr_poster_headers()))
        set_clock("2026-09-01T00:00:00Z")
        promoted = validate_success(api.promote_associate(
            assoc_b["id"], hr_poster_headers()))
        assert promoted["current_level"] == "LEVEL_2"
        assert promoted["hourly_wage_cents"] == 1850


class TestManagerPostingSegregation:
    def test_hr_poster_cannot_close_own_posting(self, api):
        """PRD section 3.7: "Closing a posting is where segregation of duties
        bites: the `HRDirector` who closes must not be the one whose
        `X-User-ID` was recorded as `posted_by_id` (`ERR_SOD_VIOLATION`
        otherwise)."

        Design: Corner/validations/hr_poster_cannot_close_own_posting
        """
        env = create_operational_commissary()
        store = create_site_store(env["commissary"])
        cand = get_success_data(api.create_associate(
            create_associate_payload(store["id"], full_name="Cand V3"),
            hr_poster_headers()))
        cand = promote_to_shift_lead(cand["id"], store["id"])
        set_clock()
        posting = get_success_data(api.create_manager_posting(
            {"store_id": store["id"]}, hr_poster_headers()))
        app = get_success_data(api.create_manager_application(
            posting["id"], {"candidate_associate_id": cand["id"]},
            make_associate_headers(cand["id"])))
        # The same HRDirector identity that posted attempts the close.
        resp = api.close_manager_posting(
            posting["id"], {"candidate_application_id": app["id"]},
            hr_poster_headers())
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert resp.status_code == 422
        stored = get_success_data(api.get_manager_posting(
            posting["id"], hr_poster_headers()))
        assert stored["status"] == "OPEN"


class TestPostingCloseSideEffects:
    def test_posting_close_compound_side_effects(self, api):
        """PRD section 3.7: "A successful close writes the application's
        `candidate_associate_id` into `filled_by_associate_id`, moves the
        selected application to `ACCEPTED`, cascades every other `PENDING`
        application on the posting to `REJECTED`, and promotes the candidate:
        `current_level` moves from `SHIFT_LEAD` to `MANAGER`,
        `hourly_wage_cents` is recomputed from the ladder to the manager
        wage, `promotion_count` increments by one as a compounding internal
        promotion, the candidate's `home_store_id` moves to the posting's
        store, and that store's `manager_associate_id` is updated to the
        candidate."

        Design: Corner/state_machines/posting_close_compound_side_effects
        """
        env = create_operational_commissary()
        store = create_site_store(env["commissary"])
        cand_a = get_success_data(api.create_associate(
            create_associate_payload(store["id"], full_name="Cand A"),
            hr_poster_headers()))
        cand_b = get_success_data(api.create_associate(
            create_associate_payload(store["id"], full_name="Cand B"),
            hr_poster_headers()))
        cand_a = promote_to_shift_lead(cand_a["id"], store["id"])
        cand_b = promote_to_shift_lead(cand_b["id"], store["id"])
        set_clock()
        posting = get_success_data(api.create_manager_posting(
            {"store_id": store["id"]}, hr_poster_headers()))
        app_a = get_success_data(api.create_manager_application(
            posting["id"], {"candidate_associate_id": cand_a["id"]},
            make_associate_headers(cand_a["id"])))
        app_b = get_success_data(api.create_manager_application(
            posting["id"], {"candidate_associate_id": cand_b["id"]},
            make_associate_headers(cand_b["id"])))
        closed = validate_success(api.close_manager_posting(
            posting["id"], {"candidate_application_id": app_a["id"]},
            hr_closer_headers()))
        assert closed["status"] == "CLOSED"
        assert closed["filled_by_associate_id"] == cand_a["id"]
        apps = api.list_applications_for_posting(
            posting["id"], hr_poster_headers()).json()["data"]
        by_id = {a["id"]: a for a in apps}
        assert by_id[app_a["id"]]["status"] == "ACCEPTED"
        assert by_id[app_b["id"]]["status"] == "REJECTED"
        winner = get_success_data(api.get_associate(
            cand_a["id"], hr_poster_headers()))
        assert winner["current_level"] == "MANAGER"
        assert winner["hourly_wage_cents"] == 3200
        assert winner["promotion_count"] == 6
        assert winner["home_store_id"] == store["id"]
        stored_store = get_success_data(api.get_store(store["id"], scd_headers()))
        assert stored_store["manager_associate_id"] == cand_a["id"]


class TestShiftOverlap:
    def test_associate_shift_half_open_overlap(self, api):
        """PRD section 3.7: "the same associate may not hold two `SCHEDULED`
        shifts whose half-open intervals — start inclusive, end exclusive —
        overlap, a violation rejected with `ERR_SHIFT_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/associate_shift_half_open_overlap
        """
        set_clock("2026-09-01T00:00:00Z")
        env = create_operational_commissary()
        store = create_site_store(env["commissary"])
        assoc = get_success_data(api.create_associate(
            create_associate_payload(store["id"], full_name="Crew RT1"),
            hr_poster_headers()))
        # Existing shift 16:00-22:00 on 2026-09-02.  Schedule it with the
        # clock parked inside the window so the coverage ratio is non-zero.
        set_clock("2026-09-02T18:00:00Z")
        first = get_success_data(api.create_shift(
            store["id"],
            create_shift_payload(assoc["id"], "2026-09-02T16:00:00Z",
                                 "2026-09-02T22:00:00Z"),
            hr_poster_headers()))
        assert first["status"] == "SCHEDULED"
        # Adjacent half-open intervals do not overlap: a shift starting
        # exactly at the other's end is allowed.
        adjacent = validate_success(api.create_shift(
            store["id"],
            create_shift_payload(assoc["id"], "2026-09-02T22:00:00Z",
                                 "2026-09-03T02:00:00Z"),
            hr_poster_headers()), expected_status=201)
        assert adjacent["status"] == "SCHEDULED"
        # One minute earlier overlaps the 16:00-22:00 window.
        resp = api.create_shift(
            store["id"],
            create_shift_payload(assoc["id"], "2026-09-02T21:59:00Z",
                                 "2026-09-03T01:00:00Z"),
            hr_poster_headers())
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        assert resp.status_code == 422

    def test_shift_touching_at_start_boundary_also_overlaps(self, api):
        """PRD section 3.7: "the same associate may not hold two `SCHEDULED`
        shifts whose half-open intervals — start inclusive, end exclusive —
        overlap, a violation rejected with `ERR_SHIFT_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/associate_shift_half_open_overlap
        """
        set_clock("2026-09-01T00:00:00Z")
        env = create_operational_commissary()
        store = create_site_store(env["commissary"])
        assoc = get_success_data(api.create_associate(
            create_associate_payload(store["id"], full_name="Crew RT1b"),
            hr_poster_headers()))
        set_clock("2026-09-02T18:00:00Z")
        get_success_data(api.create_shift(
            store["id"],
            create_shift_payload(assoc["id"], "2026-09-02T16:00:00Z",
                                 "2026-09-02T22:00:00Z"),
            hr_poster_headers()))
        # A shift fully inside the existing window overlaps.
        resp = api.create_shift(
            store["id"],
            create_shift_payload(assoc["id"], "2026-09-02T17:00:00Z",
                                 "2026-09-02T18:00:00Z"),
            hr_poster_headers())
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestStaffingPosture:
    def test_staffing_posture_derived_field_reconciliation(self, api):
        """PRD section 3.7: "Otherwise, if the active crew contains no
        associate at `MANAGER` level, the posture is `CRITICAL`."
        PRD section 3.7: "Posture gates scheduling: creating a shift is
        blocked with `ERR_POSTURE_BLOCKS` (HTTP 422) whenever the posture is
        `CRITICAL`, and during `OPENING_SURGE` a `STRAINED` posture is
        treated as `CRITICAL` for this gate."

        Design: Corner/cross_cutting_layers/staffing_posture_derived_field_reconciliation
        """
        env = create_open_store_with_manager()
        store = env["store"]
        mgr = env["manager"]
        # Deactivating the store's only MANAGER recomputes the posture; the
        # manager check makes it CRITICAL.
        get_success_data(api.patch_associate(
            mgr["id"], {"active": False}, hr_poster_headers()))
        stored = get_success_data(api.get_store(store["id"], hr_poster_headers()))
        assert stored["staffing_posture"] == "CRITICAL"
        resp = api.create_shift(
            store["id"],
            create_shift_payload(mgr["id"], "2026-09-04T16:00:00Z",
                                 "2026-09-05T00:00:00Z"),
            hr_poster_headers())
        validate_error(resp, ApiErrorId.ERR_POSTURE_BLOCKS)
        assert resp.status_code == 422


class TestMenuItemRetrieval:
    def test_menu_item_get_round_trips_all_fields(self, api):
        """PRD section 3.6: "A `SupplyChainDirector` creates menu items with
        a unique `sku`, a `name`, a listed `base_price_cents`, the base
        `patty_count` and base `produce_units` per unit before modifiers, and
        an `active` flag that defaults to true."

        Design: Corner/entities/menu_item_get_round_trips_all_fields
        """
        set_clock()
        created = get_success_data(api.create_menu_item(
            create_menu_item_payload(sku="GR-CHZ", name="Grilled Cheese",
                                     base_price_cents=295, patty_count=0,
                                     produce_units=1),
            scd_headers()))
        fetched = validate_success(api.get_menu_item(
            created["id"], planner_headers()))
        assert fetched["sku"] == "GR-CHZ"
        assert fetched["base_price_cents"] == 295
        assert fetched["patty_count"] == 0
        assert fetched["produce_units"] == 1
        assert fetched["active"] is True
