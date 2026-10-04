"""Restricted-item interception: compliance gates, resolution, closeout expiry."""
from test_helpers import (
    ASSOCIATE,
    MANAGER,
    ApiErrorId,
    create_item,
    create_member,
    create_session,
    get_line,
    get_session,
    member_headers,
    scan_unit_line,
    set_clock,
    setup_club_member,
    setup_session_with_unit_item,
    validate_error,
    validate_paginated,
    validate_success,
)


def _scan_restricted_and_get_intercept(api, session, member, item, quantity=1):
    line = scan_unit_line(session, member, item, quantity=quantity)
    assert line["status"] == "INTERCEPTED", f"Setup failed: line not INTERCEPTED: {line}"
    resp = api.list_session_intercepts(session["id"], ASSOCIATE)
    assert resp.status_code == 200, f"Setup failed: list intercepts -> {resp.text}"
    intercepts = resp.json()["data"]
    pending = [i for i in intercepts if i["status"] == "PENDING"]
    assert pending, "Setup failed: no PENDING intercept created"
    return line, pending[0]


class TestReviewHoldCycle:
    def test_session_review_hold_cycle_repeats_statuses(self, api):
        """PRD §3.4: "scanning a restricted item does not reject the scan;
        instead the line is born `INTERCEPTED`, a `RestrictedIntercept` is
        created `PENDING` for that line (one intercept per line, addressed back
        to it via `scan_line_id`, and denormalized with the session's `club_id`
        so associates can queue by club), and the session itself moves from
        `OPEN` to `REVIEW_HOLD`."; "In both cases, once no `PENDING` intercepts
        remain for the session, the session reopens from `REVIEW_HOLD` to
        `OPEN`."

        Design: Difficulty/non_linear_state_machine/session_review_hold_cycle_repeats
        """
        club, member = setup_club_member(
            member_overrides={"tier": "PLUS", "birth_year": 1990},
        )
        item = create_item(
            club["id"], sku="WINE-750", unit_price_cents=1500,
            restricted_class="ALCOHOL",
        )
        session = create_session(club, member)

        line1, int1 = _scan_restricted_and_get_intercept(api, session, member, item)
        resp = api.resolve_intercept(
            int1["id"], {"decision": "APPROVE", "birth_year_verified": True}, ASSOCIATE,
        )
        validate_success(resp)
        assert get_session(session["id"])["status"] == "OPEN"

        # Second restricted scan re-enters REVIEW_HOLD — a cycle, not a line.
        line2, int2 = _scan_restricted_and_get_intercept(api, session, member, item)
        assert get_session(session["id"])["status"] == "REVIEW_HOLD"

        resp = api.resolve_intercept(
            int2["id"], {"decision": "APPROVE", "birth_year_verified": True}, ASSOCIATE,
        )
        validate_success(resp)
        assert get_session(session["id"])["status"] == "OPEN"

    def test_session_review_hold_cycle_accumulates_provisional_total(self, api):
        """PRD §3.4: "On approval, the intercept becomes `APPROVED`, the line
        moves `INTERCEPTED → CLEARED`, the resolving associate's identity is
        recorded as the intercept's `associate_id`, and the line's savings and
        total are finalized."; PRD §3.2: "The session's
        `provisional_total_cents` is the sum of `line_total_cents` over all
        non-`REMOVED` lines, recomputed on every line addition, removal, or
        intercept resolution".

        Design: Difficulty/non_linear_state_machine/session_review_hold_cycle_repeats
        """
        club, member = setup_club_member(
            member_overrides={"tier": "PLUS", "birth_year": 1990},
        )
        item = create_item(
            club["id"], sku="WINE-750", unit_price_cents=1500,
            restricted_class="ALCOHOL",
        )
        session = create_session(club, member)

        _line1, int1 = _scan_restricted_and_get_intercept(api, session, member, item)
        api.resolve_intercept(
            int1["id"], {"decision": "APPROVE", "birth_year_verified": True}, ASSOCIATE,
        )
        _line2, int2 = _scan_restricted_and_get_intercept(api, session, member, item)
        api.resolve_intercept(
            int2["id"], {"decision": "APPROVE", "birth_year_verified": True}, ASSOCIATE,
        )

        reread = get_session(session["id"])
        assert reread["status"] == "OPEN"
        assert reread["provisional_total_cents"] == 3000


class TestInterceptResolutionGates:
    def test_age_verification_failed_for_underage_alcohol_approval(self, api):
        """PRD §3.4: "For `ALCOHOL` and `TOBACCO`, the associate must attest
        `birth_year_verified` as true, and the member's age — the current clock
        year minus the member's `birth_year` — must be at least 21; failing
        either condition rejects the approval with
        `ERR_AGE_VERIFICATION_FAILED`."

        Design: Corner/validations/age_verification_failed_for_underage_alcohol_approval
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1500, quantity=1,
            member_overrides={"tier": "PLUS", "birth_year": 2010},
            restricted_class="ALCOHOL",
        )
        resp = api.list_session_intercepts(session["id"], ASSOCIATE)
        intercept = resp.json()["data"][0]

        resp = api.resolve_intercept(
            intercept["id"], {"decision": "APPROVE", "birth_year_verified": True},
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_AGE_VERIFICATION_FAILED)
        resp = api.get_intercept(intercept["id"], ASSOCIATE)
        assert resp.json()["data"]["status"] == "PENDING"

    def test_pharmacy_approval_requires_pharmacist_note(self, api):
        """PRD §3.4: "For `PHARMACY`, the associate must supply a non-empty
        `pharmacist_note`, or the resolution is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/pharmacy_approval_requires_pharmacist_note
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1200, quantity=1, restricted_class="PHARMACY",
        )
        resp = api.list_session_intercepts(session["id"], ASSOCIATE)
        intercept = resp.json()["data"][0]

        resp = api.resolve_intercept(
            intercept["id"], {"decision": "APPROVE"}, ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        resp = api.get_intercept(intercept["id"], ASSOCIATE)
        assert resp.json()["data"]["status"] == "PENDING"

    def test_resolve_intercept_twice_rejected(self, api):
        """PRD §3.4: "Resolving an intercept that is no longer `PENDING` is
        rejected with `ERR_INTERCEPT_NOT_PENDING`."

        Design: Corner/state_machines/resolve_intercept_twice_rejected
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1500, quantity=1,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
            restricted_class="ALCOHOL",
        )
        resp = api.list_session_intercepts(session["id"], ASSOCIATE)
        intercept = resp.json()["data"][0]

        resp = api.resolve_intercept(
            intercept["id"], {"decision": "APPROVE", "birth_year_verified": True},
            ASSOCIATE,
        )
        validate_success(resp)

        resp = api.resolve_intercept(
            intercept["id"], {"decision": "DENY"}, ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_INTERCEPT_NOT_PENDING)
        # The approved line stays in the cart.
        assert get_session(session["id"])["provisional_total_cents"] == 1500

    def test_intercept_deny_removes_line_and_recomputes_totals(self, api):
        """PRD §3.4: "On denial, the intercept becomes `DENIED`, the line moves
        `INTERCEPTED → REMOVED`, and the session's provisional totals are
        recomputed with the line excluded. In both cases, once no `PENDING`
        intercepts remain for the session, the session reopens from
        `REVIEW_HOLD` to `OPEN`."

        Design: Corner/state_machines/intercept_deny_removes_line_and_recomputes_totals
        """
        club, member = setup_club_member(
            member_overrides={"tier": "PLUS", "birth_year": 1990},
        )
        milk = create_item(club["id"], sku="MILK", unit_price_cents=400)
        wine = create_item(
            club["id"], sku="WINE", unit_price_cents=1500,
            restricted_class="ALCOHOL",
        )
        session = create_session(club, member)
        scan_unit_line(session, member, milk, quantity=1)
        alc_line, intercept = _scan_restricted_and_get_intercept(
            api, session, member, wine,
        )

        resp = api.resolve_intercept(
            intercept["id"], {"decision": "DENY"}, ASSOCIATE,
        )
        validate_success(resp)

        assert get_line(alc_line["id"])["status"] == "REMOVED"
        reread = get_session(session["id"])
        assert reread["status"] == "OPEN"
        assert reread["provisional_total_cents"] == 400

    def test_restricted_scan_blocked_during_offline_fallback(self, api):
        """PRD §3.4: "While the club is `OFFLINE_FALLBACK` there is no
        associate channel at all, so scanning a restricted item is rejected
        with `ERR_RESTRICTED_BLOCKED_OFFLINE`".

        Design: Corner/state_machines/restricted_scan_blocked_during_offline_fallback
        """
        club, member = setup_club_member(
            member_overrides={"tier": "PLUS", "birth_year": 1990},
        )
        item = create_item(
            club["id"], sku="WINE", unit_price_cents=1500,
            restricted_class="ALCOHOL",
        )
        session = create_session(club, member)
        resp = api.set_connectivity(club["id"], "OFFLINE_FALLBACK", MANAGER)
        assert resp.status_code == 200, f"Setup failed: {resp.text}"

        resp = api.scan_line(
            session["id"], {"catalog_item_id": item["id"], "quantity": 1},
            member_headers(member),
        )
        validate_error(resp, ApiErrorId.ERR_RESTRICTED_BLOCKED_OFFLINE)
        assert get_session(session["id"])["provisional_total_cents"] == 0

    def test_early_hours_restricted_scan_blocked(self, api):
        """PRD §3.3: "Restricted merchandise is never sold during the early
        window: scanning an item whose `restricted_class` is `ALCOHOL`,
        `TOBACCO`, or `PHARMACY` while the clock sits in the early window is
        rejected outright with `ERR_RESTRICTED_BLOCKED_EARLY_HOURS`."

        Design: Corner/calculations/early_hours_restricted_scan_blocked
        """
        set_clock("2026-09-01T09:00:00Z")  # 540 in [480, 600): early window
        from test_helpers import create_club

        club = create_club(name="Club ER")
        item = create_item(
            club["id"], sku="WINE", unit_price_cents=1500,
            restricted_class="ALCOHOL",
        )
        member = create_member(club["id"], tier="PLUS", birth_year=1990)
        session = create_session(club, member)

        resp = api.scan_line(
            session["id"], {"catalog_item_id": item["id"], "quantity": 1},
            member_headers(member),
        )
        validate_error(resp, ApiErrorId.ERR_RESTRICTED_BLOCKED_EARLY_HOURS)
        assert get_session(session["id"])["scanned_item_count"] == 0


class TestCloseoutCascade:
    def test_closeout_expires_intercept_removes_line_reopens_session(self, api):
        """PRD §3.10: "First, every `PENDING` restricted intercept at the club
        older than the club's `intercept_ttl_minutes` expires, cascading as a
        denial: line removed, provisional totals recomputed, and the session
        reopened to `OPEN` if no pending intercepts remain (§3.4)."

        Design: Difficulty/transitive_cascade/closeout_expires_intercept_removes_line_reopens_session
        """
        club, item, member, session, line = setup_session_with_unit_item(
            price_cents=900, quantity=1,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
            restricted_class="TOBACCO",
        )
        assert get_session(session["id"])["status"] == "REVIEW_HOLD"
        set_clock("2026-09-01T12:11:00Z")  # past the default 10-minute TTL

        resp = api.run_closeout(club["id"], MANAGER)
        validate_success(resp)

        reread = get_session(session["id"])
        assert reread["status"] == "OPEN"
        assert reread["provisional_total_cents"] == 0
        assert get_line(line["id"])["status"] == "REMOVED"

    def test_closeout_marks_intercept_expired(self, api):
        """PRD §3.4: "A pending intercept can also die without an associate:
        the closeout sweep expires any intercept that has sat `PENDING` longer
        than the club's `intercept_ttl_minutes` (measured from its creation),
        and expiry cascades exactly like a denial — intercept `EXPIRED`, line
        `REMOVED`, totals recomputed, session reopened if clear."

        Design: Difficulty/transitive_cascade/closeout_expires_intercept_removes_line_reopens_session
        """
        club, item, member, session, line = setup_session_with_unit_item(
            price_cents=900, quantity=1,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
            restricted_class="TOBACCO",
        )
        set_clock("2026-09-01T12:11:00Z")
        resp = api.run_closeout(club["id"], MANAGER)
        validate_success(resp)

        resp = api.list_session_intercepts(session["id"], MANAGER)
        intercepts = resp.json()["data"]
        assert len(intercepts) == 1
        assert intercepts[0]["status"] == "EXPIRED"


class TestInterceptListing:
    def test_filtered_intercepts_list_by_session(self, api):
        """PRD §4: "GET | `/intercepts` | List intercepts with optional filters
        | Any" (the routing summary lists `session_id` among the optional
        filters; §2.3 governs the paginated envelope).

        Design: Corner/endpoints/filtered_intercepts_list_by_session
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1500, quantity=1,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
            restricted_class="ALCOHOL",
        )
        resp = api.list_intercepts(ASSOCIATE, params={"session_id": session["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["session_id"] == session["id"]
        assert data[0]["status"] == "PENDING"
