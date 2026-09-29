"""Accepting an offer, opening the ESA account and the seat-pool identity."""

from test_helpers import (
    AWARD_BAND_B_IEP,
    AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC,
    PA,
    PRORATED_932663_THREE_QUARTERS,
    Q1_NET_CENTS,
    ApiErrorId,
    accept_award,
    anonymous_headers,
    assert_account,
    assert_instant_equals,
    create_application,
    create_program_year,
    create_student,
    make_guardian_headers,
    open_window,
    read_account,
    read_application,
    read_program_year,
    record_determination,
    run_awarding,
    run_disbursement,
    set_clock,
    setup_eligible_application,
    setup_funded_account,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_application,
)


def _offered_application(**year_overrides):
    """The canonical single-candidate year carried to an outstanding offer."""
    env = setup_eligible_application(year_overrides=year_overrides or None)
    env["awarding_run"] = run_awarding(env.program_year_id)
    env["application"] = read_application(env.application_id)
    return env


class TestAwardProrationVariants:
    """The claimed provisional figure and the verified prorated figure diverge."""

    def test_award_prorates_over_the_three_quarters_that_remain(self, api):
        """PRD §3.5: "The prorated entitlement is the application's verified
        `annual_award_cents` multiplied by the quarters that remain, divided by four, and
        rounded half up to whole cents; it is written to the application's
        `final_award_cents`. With a verified annual figure of 932663 that yields 932663
        when four quarters remain, 699497 when three remain, and 466332 when two remain"

        PRD §3.3: "On the same application the two variants routinely disagree — a
        claimed set that produces 978382 may verify down to 932663 — which is exactly why
        the provisional figure is never treated as an entitlement."

        Design: Difficulty/dual_variant_calc/award_provisional_claimed_vs_final_verified_diverge
        """
        env = _offered_application()
        application = env.application
        assert application["status"] == "AWARD_OFFERED", (
            f"the single candidate holds the offer, got {application['status']!r}"
        )
        assert application["provisional_award_cents"] == AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC, (
            "the claimed variant scored both claimed flags at 978382, got "
            f"{application['provisional_award_cents']}"
        )
        assert application["annual_award_cents"] == AWARD_BAND_B_IEP, (
            "the verified variant scored only the confirmed flag at 932663, got "
            f"{application['annual_award_cents']}"
        )

        run_disbursement(env.program_year_id, 1)
        assert read_program_year(env.program_year_id)["current_quarter"] == 1, (
            "the quarter-1 run advanced the year's checkpoint before any account existed"
        )

        accept = validate_success(
            api.accept_award(env.application_id, env.guardian)
        )

        assert accept["quarters_remaining_at_award"] == 3, (
            "the number of quarters that remain is four less the year's current_quarter, "
            f"got {accept['quarters_remaining_at_award']}"
        )
        assert accept["annual_award_cents"] == AWARD_BAND_B_IEP, (
            f"the response reports the verified annual figure, got "
            f"{accept['annual_award_cents']}"
        )
        assert accept["final_award_cents"] == PRORATED_932663_THREE_QUARTERS, (
            "932663 over three of four quarters is 699497 after rounding half up, got "
            f"{accept['final_award_cents']}"
        )
        assert accept["application_status"] == "ACCEPTED", (
            f"acceptance moves the application AWARD_OFFERED to ACCEPTED, got "
            f"{accept['application_status']!r}"
        )

        account = read_account(accept["account_id"])
        assert_account(account)
        assert account["final_award_cents"] == PRORATED_932663_THREE_QUARTERS, (
            f"the account copies final_award_cents from the application, got "
            f"{account['final_award_cents']}"
        )
        assert account["quarters_remaining_at_award"] == 3, (
            f"quarters_remaining_at_award is four less the year's current_quarter, got "
            f"{account['quarters_remaining_at_award']}"
        )
        assert account["final_award_cents"] != AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC, (
            "the prorated verified figure of 699497 must not be confused with the "
            f"claimed provisional 978382, got {account['final_award_cents']}"
        )

        after = read_application(env.application_id)
        assert after["final_award_cents"] == PRORATED_932663_THREE_QUARTERS, (
            f"the prorated entitlement is written to the application, got "
            f"{after['final_award_cents']}"
        )
        assert after["provisional_award_cents"] == AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC, (
            "the provisional figure is untouched by the proration, got "
            f"{after['provisional_award_cents']}"
        )

    def test_a_full_four_quarters_leaves_the_verified_figure_untouched(self, api):
        """PRD §3.5: "With a verified annual figure of 932663 that yields 932663 when four
        quarters remain, 699497 when three remain, and 466332 when two remain — the
        identity being that a full four quarters leaves the annual figure untouched."

        PRD §3.2: "The claimed variant stops there and always assumes the whole
        four-quarter year, so `provisional_award_cents` receives the step-four figure with
        no proration whatsoever."

        Design: Difficulty/dual_variant_calc/award_provisional_claimed_vs_final_verified_diverge
        """
        env = _offered_application()
        assert read_program_year(env.program_year_id)["current_quarter"] == 0, (
            "no disbursement run has fired, so the whole year is still ahead"
        )

        accept = accept_award(env.application_id, env.student_id)

        assert accept["quarters_remaining_at_award"] == 4, (
            f"four quarters remain against a current_quarter of 0, got "
            f"{accept['quarters_remaining_at_award']}"
        )
        assert accept["final_award_cents"] == AWARD_BAND_B_IEP, (
            "a full four quarters leaves the annual figure untouched at 932663, got "
            f"{accept['final_award_cents']}"
        )
        assert accept["final_award_cents"] == accept["annual_award_cents"], (
            "the prorated figure and the verified annual figure coincide here, got "
            f"{accept!r}"
        )
        assert accept["final_award_cents"] != AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC, (
            "the claimed variant still disagrees at 978382 because it scored a flag the "
            f"officer did not confirm, got {accept['final_award_cents']}"
        )

        account = read_account(accept["account_id"])
        assert account["balance_cents"] == 0, (
            "the account starts with balance_cents at 0 — acceptance is not a credit, "
            f"got {account['balance_cents']}"
        )
        assert account["lifetime_disbursed_cents"] == 0, (
            f"every lifetime counter starts at 0, got "
            f"{account['lifetime_disbursed_cents']}"
        )


class TestAcceptanceVisibility:
    """The account is visible in the very response that creates it."""

    def test_account_and_seat_counters_are_current_in_the_same_request(self, api):
        """PRD §3.5: "The response reports `application_id`, the resulting
        `application_status`, the `account_id` just created, the verified
        `annual_award_cents`, the prorated `final_award_cents`, and
        `quarters_remaining_at_award`."

        PRD §3.5: "Because both `AWARD_OFFERED` and `ACCEPTED` count as committed,
        acceptance leaves `seats_committed` and `seats_available` unchanged."

        Design: Corner/consistency_model/accept_award_response_carries_the_new_account_immediately
        """
        env = _offered_application()

        accept = validate_success(api.accept_award(env.application_id, env.guardian))

        assert accept["application_id"] == env.application_id, (
            f"the response names the application it acted on, got {accept!r}"
        )
        assert accept["application_status"] == "ACCEPTED", (
            f"the resulting application_status is reported, got "
            f"{accept['application_status']!r}"
        )
        assert accept["account_id"], (
            f"the account_id just created is reported, got {accept['account_id']!r}"
        )
        assert accept["final_award_cents"] == AWARD_BAND_B_IEP, (
            f"the prorated figure is reported, got {accept['final_award_cents']}"
        )
        assert accept["quarters_remaining_at_award"] == 4, (
            f"quarters_remaining_at_award is reported, got "
            f"{accept['quarters_remaining_at_award']}"
        )

        reread = validate_success(api.get_account(accept["account_id"], env.guardian))
        assert reread["status"] == "ACTIVE", (
            f"the new account starts in ACTIVE on an immediate re-read, got "
            f"{reread['status']!r}"
        )
        assert reread["balance_cents"] == 0, (
            f"the re-read agrees that no money has moved yet, got "
            f"{reread['balance_cents']}"
        )
        assert reread["final_award_cents"] == accept["final_award_cents"], (
            "the re-read carries the same prorated entitlement the response reported, "
            f"got {reread['final_award_cents']} against {accept['final_award_cents']}"
        )
        assert reread["application_id"] == env.application_id, (
            "the account records the application_id of the accepted award, got "
            f"{reread['application_id']!r}"
        )
        assert reread["program_year_id"] == env.program_year_id, (
            "and, denormalised from it, the program_year_id, got "
            f"{reread['program_year_id']!r}"
        )

        rows, meta = validate_paginated(
            api.list_accounts(PA, params={"student_id": env.student_id})
        )
        assert meta["total_count"] == 1, (
            f"the account is immediately discoverable, got {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [accept["account_id"]], (
            f"and it is the account the acceptance minted, got {rows!r}"
        )

        year = read_program_year(env.program_year_id)
        assert year["seats_committed"] == 1 and year["seats_available"] == 1, (
            "the offer already counted as committed, so the counters do not move on "
            f"acceptance, got committed {year['seats_committed']} / available "
            f"{year['seats_available']}"
        )


class TestSeatIdentityAcrossWithdrawal:
    """A released seat is re-consumed by the waitlist promotion in one request."""

    def _single_seat_year_with_a_waitlist(self):
        year = create_program_year(total_seats=1)
        open_window(year["id"])
        top = create_student(income_band="BAND_A", category_flags=["DISABILITY_IEP"])
        second = create_student(
            household_id="HH-2",
            first_name="Beto",
            last_name="Salas",
            date_of_birth="2012-07-19",
            prior_enrollment="PRIVATE_SCHOOL",
            category_flags=[],
        )
        set_clock("2026-09-01T00:00:00Z")

        a1 = create_application(
            year["id"],
            top["id"],
            claimed_income_band="BAND_A",
            claimed_category_flags=["DISABILITY_IEP"],
        )
        submit_application(a1["id"], top["id"])
        a2 = create_application(
            year["id"], second["id"], claimed_category_flags=[]
        )
        submit_application(a2["id"], second["id"])

        d1 = record_determination(
            a1["id"],
            verified_income_band="BAND_A",
            verified_prior_enrollment="PUBLIC_SCHOOL_FULL_YEAR",
            verified_category_flags=["DISABILITY_IEP"],
        )
        d2 = record_determination(
            a2["id"],
            verified_income_band="BAND_B",
            verified_prior_enrollment="PRIVATE_SCHOOL",
            verified_category_flags=[],
        )
        run = run_awarding(year["id"])
        accept = accept_award(a1["id"], top["id"])
        return {
            "year": year,
            "top": top,
            "second": second,
            "a1": a1,
            "a2": a2,
            "d1": d1,
            "d2": d2,
            "run": run,
            "accept": accept,
        }

    def test_withdrawal_releases_the_seat_and_the_promotion_takes_it_back(self, api):
        """PRD §3.5: "The seat is then released: `seats_committed` falls by 1 and
        `seats_available` rises by 1, and that release itself promotes the waitlisted
        application with the lowest `waitlist_position` when one exists, which
        re-consumes the seat and so lowers `seats_available` again."

        PRD §2.10: "A seat released while any application is still waitlisted is not
        left idle — it is immediately handed to the waitlisted application holding the
        lowest `waitlist_position`, which itself consumes the seat again."

        Design: Difficulty/compensating_invariant/seat_identity_holds_across_withdrawal_and_waitlist_promotion
        """
        world = self._single_seat_year_with_a_waitlist()
        year_id = world["year"]["id"]

        assert (world["d1"]["priority_tier"], world["d1"]["priority_score"]) == (3, 140), (
            "the seat holder is tier 3 scoring 140, got "
            f"{(world['d1']['priority_tier'], world['d1']['priority_score'])!r}"
        )
        assert (world["d2"]["priority_tier"], world["d2"]["priority_score"]) == (5, 60), (
            "the waitlisted candidate is tier 5 scoring 60, got "
            f"{(world['d2']['priority_tier'], world['d2']['priority_score'])!r}"
        )
        assert world["run"]["awarded_count"] == 1, (
            f"the single seat is offered once, got {world['run']['awarded_count']}"
        )
        assert world["run"]["waitlisted_count"] == 1, (
            f"the loser is waitlisted, got {world['run']['waitlisted_count']}"
        )
        assert read_application(world["a2"]["id"])["waitlist_position"] == 1, (
            "the waitlisted application holds position 1"
        )

        before = read_program_year(year_id)
        assert before["seats_committed"] == 1 and before["seats_available"] == 0, (
            f"the only seat is committed before the withdrawal, got {before!r}"
        )
        assert before["seats_committed"] + before["seats_available"] == 1, (
            "the identity holds before the withdrawal, got "
            f"{before['seats_committed']} plus {before['seats_available']}"
        )

        result = withdraw_application(world["a1"]["id"], world["top"]["id"])

        assert result["application_status"] == "WITHDRAWN", (
            f"the application moves ACCEPTED to WITHDRAWN, got "
            f"{result['application_status']!r}"
        )
        assert result["account_status"] == "CLOSED", (
            f"the account funded by that application moves to CLOSED, got "
            f"{result['account_status']!r}"
        )
        assert result["promoted_application_id"] == world["a2"]["id"], (
            "the waitlisted application with the lowest waitlist_position takes the "
            f"freed seat, got {result['promoted_application_id']!r}"
        )
        assert result["seats_committed"] == 1 and result["seats_available"] == 0, (
            "the promotion re-consumes the seat inside the same request, got committed "
            f"{result['seats_committed']} / available {result['seats_available']}"
        )

        promoted = read_application(world["a2"]["id"])
        assert promoted["status"] == "AWARD_OFFERED", (
            f"the promoted application moves WAITLISTED to AWARD_OFFERED, got "
            f"{promoted['status']!r}"
        )
        assert promoted["waitlist_position"] is None, (
            f"its waitlist_position is set to null, got {promoted['waitlist_position']!r}"
        )
        assert_instant_equals(
            promoted["acceptance_deadline_at"],
            "2026-09-15T00:00:00Z",
            "a fresh acceptance_deadline_at is stamped 14 days out",
        )
        assert read_account(world["accept"]["account_id"])["status"] == "CLOSED", (
            "the withdrawn family's account is closed"
        )

        after = read_program_year(year_id)
        assert after["seats_committed"] + after["seats_available"] == after["total_seats"], (
            "the identity still holds after the withdrawal, got committed "
            f"{after['seats_committed']} plus available {after['seats_available']} "
            f"against {after['total_seats']} seats"
        )
        assert after["seats_committed"] == 1 and after["seats_available"] == 0, (
            f"and both counters read exactly as the response reported, got {after!r}"
        )
        _, meta = validate_paginated(
            api.list_accounts(PA, params={"program_year_id": year_id})
        )
        assert meta["total_count"] == 1, (
            "the promotion mints no second account, because only an acceptance ever "
            f"opens one, got {meta['total_count']}"
        )

    def test_withdrawal_with_no_waitlist_leaves_the_seat_free(self, api):
        """PRD §3.5: "The application moves `ACCEPTED → WITHDRAWN`, and the cascade runs
        to completion in one request. The account funded by that application moves to
        `CLOSED`, and — unlike suspension — closure deliberately leaves `balance_cents`
        and `encumbered_cents` exactly as they stood, so the ledger remains readable as
        an audit trail."

        PRD §3.4: "Promotion off the waitlist is never an explicit request; it is a
        cascade that fires whenever a seat is released, whether by a withdrawal, by an
        offer expiring, or by any other seat return."

        Design: Difficulty/compensating_invariant/seat_identity_holds_across_withdrawal_and_waitlist_promotion
        """
        env = _offered_application(total_seats=1)
        accept = accept_award(env.application_id, env.student_id)
        run_disbursement(env.program_year_id, 1)
        funded = read_account(accept["account_id"])
        assert funded["balance_cents"] > 0, (
            f"the account carries credited money before the withdrawal, got "
            f"{funded['balance_cents']}"
        )

        before = read_program_year(env.program_year_id)
        assert before["seats_committed"] + before["seats_available"] == 1, (
            f"the identity holds before the withdrawal, got {before!r}"
        )

        result = withdraw_application(env.application_id, env.student_id)

        assert result["promoted_application_id"] is None, (
            "there is no waitlisted application to promote, got "
            f"{result['promoted_application_id']!r}"
        )
        assert result["seats_committed"] == 0 and result["seats_available"] == 1, (
            "seats_committed falls by 1 and seats_available rises by 1 with nothing to "
            f"re-consume the seat, got committed {result['seats_committed']} / available "
            f"{result['seats_available']}"
        )

        closed = read_account(accept["account_id"])
        assert closed["status"] == "CLOSED", (
            f"the funded account moves to CLOSED, got {closed['status']!r}"
        )
        assert closed["balance_cents"] == funded["balance_cents"], (
            "closure deliberately leaves balance_cents exactly as it stood, got "
            f"{closed['balance_cents']} against {funded['balance_cents']}"
        )
        assert closed["encumbered_cents"] == funded["encumbered_cents"], (
            "and leaves encumbered_cents exactly as it stood, got "
            f"{closed['encumbered_cents']} against {funded['encumbered_cents']}"
        )

        after = read_program_year(env.program_year_id)
        assert after["seats_committed"] + after["seats_available"] == after["total_seats"], (
            "the identity still holds with the seat now free, got committed "
            f"{after['seats_committed']} plus available {after['seats_available']} "
            f"against {after['total_seats']} seats"
        )
        assert after["seats_committed"] >= 0 and after["seats_available"] >= 0, (
            f"neither counter is ever negative, got {after!r}"
        )


class TestAccountReadAccess:
    """The account read is shared, and the ownership rule narrows the guardian only."""

    def test_administrator_and_owning_guardian_read_the_same_balance(self, api):
        """PRD §2.1: "When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the
        acting `Student`; every guardian write is checked by comparing the `student_id` of
        the application under operation — or the `student_id` of the application that
        funds the account under operation — against `X-User-ID`, and a mismatch is
        rejected with `ERR_NOT_ACCOUNT_HOLDER`."

        Design: Corner/rbac/account_read_is_shared_by_program_admin_and_the_owning_guardian
        """
        env = setup_funded_account(quarters=1)

        as_admin = validate_success(api.get_account(env.account_id, PA))
        as_guardian = validate_success(api.get_account(env.account_id, env.guardian))

        assert as_admin["balance_cents"] == Q1_NET_CENTS, (
            f"the administrator reads the credited balance of 229088, got "
            f"{as_admin['balance_cents']}"
        )
        assert as_guardian["balance_cents"] == as_admin["balance_cents"], (
            "the owning guardian reads the identical balance, got "
            f"{as_guardian['balance_cents']} against {as_admin['balance_cents']}"
        )
        assert as_guardian["id"] == as_admin["id"] == env.account_id, (
            f"both responses carry the same account, got {as_guardian!r}"
        )
        assert as_guardian["status"] == "ACTIVE" and as_admin["status"] == "ACTIVE", (
            f"and the same status, got {as_guardian['status']!r}"
        )


class TestUnauthenticatedRequest:
    """Authentication is checked before existence and before role."""

    def test_read_without_identity_headers_is_unauthenticated(self, api):
        """PRD §2.1: "Every request, without exception, carries two mandatory headers:
        `X-User-ID` identifies the acting principal and `X-User-Role` declares the
        capacity in which it is acting. If either header is absent, or if `X-User-Role` is
        not one of the eight role names below, the request is rejected with
        `ERR_UNAUTHENTICATED`."

        PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
        and `api_request_timestamp`."

        Design: Corner/errors/request_missing_auth_header_returns_unauthenticated
        """
        year = create_program_year()
        open_window(year["id"])

        response = api.get_program_year(year["id"], anonymous_headers())
        body = validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)

        assert isinstance(body["message"], str) and body["message"].strip(), (
            f"the message provides a human-readable explanation, got {body['message']!r}"
        )
        envelope = response.json()
        assert envelope["response_type"] == "error", (
            f"the error envelope declares response_type error, got "
            f"{envelope['response_type']!r}"
        )
        assert set(envelope["meta"]) == {"api_request_id", "api_request_timestamp"}, (
            "the meta object for error responses contains only api_request_id and "
            f"api_request_timestamp, got {sorted(envelope['meta'])!r}"
        )

        assert read_program_year(year["id"])["status"] == "WINDOW_OPEN", (
            "the refused read changed nothing about the year that exists"
        )
