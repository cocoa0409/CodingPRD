"""Dispute adjudication: the information-request cycle and the grant guard."""

from test_helpers import (
    ANALYST_HEADERS,
    ApiErrorId,
    assert_dispute,
    assert_instant_equals,
    bank_deposit,
    factories,
    file_trading_power_dispute,
    list_ledger_entries,
    list_page,
    make_member_headers,
    open_dispute_review,
    read_deposit,
    read_dispute,
    read_member,
    request_dispute_info,
    respond_to_dispute,
    run_matching,
    set_clock,
    setup_banked_week,
    setup_market,
    validate_error,
    validate_success,
)


def _dispute_at_the_round_cap():
    """A TRADING_POWER dispute driven around the info cycle twice."""
    market = setup_banked_week(check_in_date="2027-06-15")
    assert market["deposit"]["awarded_power"] == 82
    dispute = file_trading_power_dispute(
        market["member"]["id"], market["deposit"]["id"]
    )
    assert_dispute(dispute)
    assert dispute["status"] == "OPEN"
    assert dispute["round_count"] == 0

    reviewing = open_dispute_review(dispute["id"])
    assert reviewing["status"] == "UNDER_REVIEW"
    assert reviewing["round_count"] == 0

    first = request_dispute_info(dispute["id"])
    assert first["status"] == "INFO_REQUESTED"
    assert first["round_count"] == 1
    back = respond_to_dispute(dispute["id"], market["member"]["id"])
    assert back["status"] == "UNDER_REVIEW"
    assert back["round_count"] == 1, "the member's answer does not raise the counter"

    second = request_dispute_info(dispute["id"], "One more photograph, please.")
    assert second["status"] == "INFO_REQUESTED"
    assert second["round_count"] == 2
    settled = respond_to_dispute(dispute["id"], market["member"]["id"], "Attached.")
    assert settled["status"] == "UNDER_REVIEW"
    assert settled["round_count"] == 2

    market["dispute"] = dispute
    return market


def _dispute_over_an_expired_week():
    """A dispute UNDER_REVIEW whose cited week is expired by a later run."""
    market = setup_market(
        member_count=1,
        resort_overrides=dict(factories.RESORT_C),
        band_code="SILVER",
        band_start_month_day="01-01",
        band_end_month_day="12-31",
    )
    member = market["members"][0]
    deposit = bank_deposit(
        member["id"], market["resort"]["id"], unit_size="STUDIO",
        check_in_date="2026-11-01",
    )
    assert deposit["awarded_power"] == 27
    assert_instant_equals(deposit["expires_at"], "2028-10-31T00:00:00Z", "expires_at")

    dispute = file_trading_power_dispute(member["id"], deposit["id"])
    open_dispute_review(dispute["id"])

    set_clock("2028-11-01T00:00:00Z")
    run = run_matching("expire the ageing studio")
    assert run["expired_deposit_count"] == 1

    market.update({"member": member, "deposit": deposit, "dispute": dispute})
    return market


class TestInfoRequestRoundCap:
    def test_the_third_information_request_is_refused_at_the_cap(self, api):
        """Two traversals of the cycle are legal and the third request is not.

        PRD §3.9: "From there the analyst may ask the member for more, submitting
        a `question`; that moves the dispute `UNDER_REVIEW` → `INFO_REQUESTED`
        and raises `round_count` by 1, but only while `round_count` is strictly
        below 2 — the third attempt is refused with `ERR_DISPUTE_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/dispute_info_request_review_cycle_round_cap
        """
        market = _dispute_at_the_round_cap()

        response = api.request_dispute_info(
            market["dispute"]["id"],
            factories.dispute_info_request_payload("A third question."),
            ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DISPUTE_ROUND_LIMIT.value, 409)

        after = read_dispute(market["dispute"]["id"])
        assert after["status"] == "UNDER_REVIEW", (
            "the rejected request leaves the cycle where the second response left it"
        )
        assert after["round_count"] == 2

    def test_the_refused_round_changes_nothing_about_the_grievance(self, api):
        """No grant, no note and no movement on the cited week.

        PRD §3.9: "The cycle `UNDER_REVIEW` → `INFO_REQUESTED` → `UNDER_REVIEW`
        may therefore run at most twice, and re-entry into `UNDER_REVIEW` is not
        equivalent to the first entry because `round_count` has advanced and the
        analyst's remaining questions have been consumed."

        Design: Difficulty/non_linear_state_machine/dispute_info_request_review_cycle_round_cap
        """
        market = _dispute_at_the_round_cap()
        validate_error(
            api.request_dispute_info(
                market["dispute"]["id"],
                factories.dispute_info_request_payload("A third question."),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_DISPUTE_ROUND_LIMIT.value,
            409,
        )

        after = read_dispute(market["dispute"]["id"])
        assert after["granted_power_adjustment"] == 0
        assert after["resolution_note"] is None

        assert read_deposit(market["deposit"]["id"])["awarded_power"] == 82, (
            "the dispute lifecycle never touches the valuation on its own"
        )
        assert read_member(market["member"]["id"])["trading_power_balance"] == 82


class TestGrantBlockedByExpiredDeposit:
    def test_upholding_a_grant_against_an_expired_week_is_refused(self, api):
        """The resolution is judged on the state of an entity two hops away.

        PRD §3.9: "Upholding a `TRADING_POWER` dispute requires that the cited
        week is still economically live: its `deposit_status` must be `BANKED`,
        `RESERVED` or `USED`, and it must not have passed its `expires_at`; a week
        that is `EXPIRED` or `WITHDRAWN`, or one whose expiry instant has passed,
        is refused with `ERR_DEPOSIT_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/dispute_power_grant_blocked_by_expired_deposit
        """
        market = _dispute_over_an_expired_week()
        assert read_deposit(market["deposit"]["id"])["deposit_status"] == "EXPIRED"

        response = api.resolve_dispute(
            market["dispute"]["id"],
            factories.dispute_resolution_payload(
                "UPHELD", "The studio was undervalued.", granted_power_adjustment=5
            ),
            ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DEPOSIT_EXPIRED.value, 409)

        after = read_dispute(market["dispute"]["id"])
        assert after["status"] == "UNDER_REVIEW", "not half-resolved and not a dead end"
        assert after["resolution_note"] is None
        assert after["granted_power_adjustment"] == 0
        assert after["round_count"] == 0

        assert read_member(market["member"]["id"])["trading_power_balance"] == 0, (
            "no partial grant was posted"
        )
        _, grants = list_ledger_entries(
            member_id=market["member"]["id"], entry_type="DISPUTE_POWER_GRANT"
        )
        assert grants["total_count"] == 0

    def test_the_analyst_can_immediately_deny_the_same_dispute_instead(self, api):
        """Because the refusal left UNDER_REVIEW intact, the DENIED edge is still open.

        PRD §3.9: "A `DENIED` outcome moves the dispute `UNDER_REVIEW` →
        `RESOLVED_DENIED`, a terminal state, and changes nothing else in the
        system beyond recording the note."

        Design: Difficulty/cross_entity_state_dependency/dispute_power_grant_blocked_by_expired_deposit
        """
        market = _dispute_over_an_expired_week()
        validate_error(
            api.resolve_dispute(
                market["dispute"]["id"],
                factories.dispute_resolution_payload(
                    "UPHELD", "The studio was undervalued.",
                    granted_power_adjustment=5,
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_DEPOSIT_EXPIRED.value,
            409,
        )

        denied = validate_success(
            api.resolve_dispute(
                market["dispute"]["id"],
                factories.dispute_resolution_payload(
                    "DENIED", "The week had already expired unsold."
                ),
                ANALYST_HEADERS,
            )
        )
        assert denied["status"] == "RESOLVED_DENIED"
        assert denied["resolution_note"] == "The week had already expired unsold."
        assert denied["granted_power_adjustment"] == 0
        assert denied["version"] > market["dispute"]["version"], (
            "the resolution is a mutation of the dispute row"
        )
        assert read_member(market["member"]["id"])["trading_power_balance"] == 0, (
            "unchanged by a DENIED resolution"
        )


class TestWithdrawalStraightFromOpen:
    def test_a_member_withdraws_an_open_dispute_without_any_analyst_action(self, api):
        """OPEN reaches the WITHDRAWN terminal directly, moving no power.

        PRD §3.9: "A member may abandon its own dispute at any point before
        resolution: a dispute that is `OPEN`, `UNDER_REVIEW` or `INFO_REQUESTED`
        may be withdrawn by its filer, moving it to `WITHDRAWN`, which is
        terminal."

        Design: Corner/state_machines/dispute_withdrawn_from_open_without_review
        """
        market = setup_banked_week(check_in_date="2027-06-15")
        dispute = file_trading_power_dispute(
            market["member"]["id"], market["deposit"]["id"]
        )
        assert dispute["status"] == "OPEN", "no analyst has called review"

        withdrawn = validate_success(
            api.withdraw_dispute(
                dispute["id"], make_member_headers(market["member"]["id"])
            )
        )
        assert withdrawn["status"] == "WITHDRAWN", "reached directly from OPEN"
        assert withdrawn["round_count"] == 0
        assert withdrawn["granted_power_adjustment"] == 0
        assert withdrawn["resolution_note"] is None

        week = read_deposit(market["deposit"]["id"])
        assert week["awarded_power"] == 82
        assert week["remaining_power"] == 82
        assert read_member(market["member"]["id"])["trading_power_balance"] == 82
        _, grants = list_ledger_entries(
            member_id=market["member"]["id"], entry_type="DISPUTE_POWER_GRANT"
        )
        assert grants["total_count"] == 0, (
            "withdrawal is not the RESOLVED_UPHELD path and grants nothing"
        )


class TestSubjectReferenceExclusivity:
    def test_a_trading_power_dispute_naming_a_resort_is_rejected(self, api):
        """The surplus resort reference is rejected rather than ignored.

        PRD §2.10: "A dispute's subject references match its `subject_type` —
        otherwise `ERR_DISPUTE_SUBJECT_MISMATCH` (422), on dispute filing.
        `TRADING_POWER` requires `deposit_id` present with `resort_id` and
        `confirmation_id` both null"

        Design: Corner/validations/trading_power_dispute_naming_a_resort_is_rejected
        """
        market = setup_banked_week(check_in_date="2027-06-15")
        member_headers = make_member_headers(market["member"]["id"])

        response = api.create_dispute(
            factories.trading_power_dispute_payload(
                market["member"]["id"],
                market["deposit"]["id"],
                resort_id=market["resort"]["id"],
            ),
            member_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_DISPUTE_SUBJECT_MISMATCH.value, 422
        )

        _, meta = list_page(api.list_disputes(ANALYST_HEADERS))
        assert meta["total_count"] == 0, "the rejected filing was not persisted"

    def test_a_trading_power_dispute_with_no_deposit_is_the_same_mismatch(self, api):
        """An absent deposit reference is a subject mismatch, not a malformed body.

        PRD §3.9: "A `TRADING_POWER` dispute names the `deposit_id` of the week
        whose valuation is challenged and must leave `resort_id` and
        `confirmation_id` both null ... Any other combination of subject
        references is refused with `ERR_DISPUTE_SUBJECT_MISMATCH`."

        Design: Corner/validations/trading_power_dispute_naming_a_resort_is_rejected
        """
        market = setup_banked_week(check_in_date="2027-06-15")
        member_headers = make_member_headers(market["member"]["id"])

        payload = factories.trading_power_dispute_payload(
            market["member"]["id"], market["deposit"]["id"]
        )
        payload.pop("deposit_id")
        validate_error(
            api.create_dispute(payload, member_headers),
            ApiErrorId.ERR_DISPUTE_SUBJECT_MISMATCH.value,
            422,
        )

        accepted = validate_success(
            api.create_dispute(
                factories.trading_power_dispute_payload(
                    market["member"]["id"], market["deposit"]["id"]
                ),
                member_headers,
            ),
            201,
        )
        assert accepted["status"] == "OPEN"
        assert accepted["subject_type"] == "TRADING_POWER"
        assert accepted["deposit_id"] == market["deposit"]["id"]
        assert accepted["resort_id"] is None
        assert accepted["confirmation_id"] is None
