"""Bounded revision cycles: the grant send-back loop and the preclearance
information-request loop.

Both loops are traversable exactly twice. A grant may be sent back from
`PENDING_APPROVAL` to `CHANGES_REQUESTED` and resubmitted twice, with the counter
compared against its cap before the increment; a preclearance request may be
bounced to `INFO_REQUESTED` and resubmitted twice, with the cap enforced on the
decision that opens each loop rather than on the resubmission that closes it. In
both cases the refused third attempt leaves the row in the status it already held
and still lets the workflow finish.
"""

from test_helpers import (
    ADMIN,
    BOARD,
    COMPLIANCE,
    ApiErrorId,
    api_client,
    assert_grant,
    assert_instant_equals,
    assert_preclearance_request,
    assert_reserve_conservation,
    assert_trading_window,
    create_draft_grant,
    create_open_window,
    create_participant,
    create_plan,
    create_preclearance,
    create_vesting_tranche_payload,
    decide_payload,
    decide_preclearance,
    make_participant_headers,
    read_grant,
    read_plan,
    read_preclearance,
    read_window,
    request_changes_payload,
    request_grant_changes,
    resubmit_preclearance,
    revise_grant,
    set_clock,
    submit_grant,
    validate_error,
    validate_success,
)

_WINDOW_OPEN_AT = "2026-01-05T00:00:00Z"
_WINDOW_CLOSE_AT = "2026-03-31T00:00:00Z"


def _pending_grant_scenario():
    """An RSU grant of 10000 target shares sitting in PENDING_APPROVAL with one
    TIME tranche of 4000 shares, submitted by admin-1."""
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Plan E Revision",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=0,
    )
    participant = create_participant(
        full_name="Eve Cycle",
        employee_number="E-2882-05",
        home_country_code="US",
        home_state_code="WA",
        hire_date="2022-01-10",
        birth_date="1992-07-19",
    )
    grant, tranches = create_draft_grant(
        plan["id"], participant["id"],
        award_type="RSU", target_shares=10000,
        tranches=[
            {"tranche_index": 1, "vest_type": "TIME",
             "scheduled_vest_date": "2027-01-05", "target_shares": 4000},
        ],
    )
    grant = submit_grant(grant["id"])
    return {"plan": plan, "participant": participant, "grant": grant,
            "tranches": tranches}


def _append_second_tranche(grant_id):
    """Append the 8000-share tranche the send-back asked for. Appending is legal
    while the grant sits in CHANGES_REQUESTED."""
    payload = create_vesting_tranche_payload(
        tranche_index=2, vest_type="TIME",
        scheduled_vest_date="2028-01-05", target_shares=8000,
    )
    return validate_success(
        api_client.create_vesting_tranche(grant_id, payload, ADMIN), 201
    )


def _walk_grant_cycle_twice(grant_id):
    """Traverse PENDING_APPROVAL -> CHANGES_REQUESTED -> PENDING_APPROVAL twice,
    resizing the award to 12000 shares on the way. Leaves the grant pending."""
    request_grant_changes(
        grant_id, change_note="Split the award into two tranches."
    )
    revise_grant(grant_id, 12000)
    _append_second_tranche(grant_id)
    submit_grant(grant_id)
    request_grant_changes(
        grant_id, change_note="Confirm the second tranche date."
    )
    revise_grant(grant_id, 12000)
    return submit_grant(grant_id)


class TestGrantSendBackCycle:
    """The grant revision loop, its cap, and the approval that exits it."""

    def test_send_back_then_revise_returns_the_grant_to_pending_approval(self):
        """PRD §3.4: "An approver — either a `BoardMember` or a `DelegatedOfficer` — may send a pending grant back with a mandatory `change_note`, moving it from `PENDING_APPROVAL` to `CHANGES_REQUESTED` and incrementing `changes_requested_count` by 1."

        PRD §3.4: "A revision does not touch `changes_requested_count`, which the send-back already advanced, and it leaves the grant in `CHANGES_REQUESTED` until it is submitted again. That closes the cycle `PENDING_APPROVAL → CHANGES_REQUESTED → PENDING_APPROVAL`."

        Design: Difficulty/non_linear_state_machine/grant_changes_requested_revision_cycle
        """
        scenario = _pending_grant_scenario()
        grant_id = scenario["grant"]["id"]
        assert scenario["grant"]["status"] == "PENDING_APPROVAL"
        assert scenario["grant"]["changes_requested_count"] == 0

        sent_back = validate_success(
            api_client.request_grant_changes(
                grant_id,
                request_changes_payload("Split the award into two tranches."),
                BOARD,
            ),
            200,
        )
        assert sent_back["status"] == "CHANGES_REQUESTED"
        assert sent_back["changes_requested_count"] == 1, (
            "the send-back increments the counter by 1"
        )

        revised = revise_grant(grant_id, 12000)
        assert revised["status"] == "CHANGES_REQUESTED", (
            "a revision leaves the grant in CHANGES_REQUESTED until it is "
            "submitted again"
        )
        assert revised["changes_requested_count"] == 1, (
            "a revision does not touch changes_requested_count"
        )
        assert revised["target_shares"] == 12000
        _append_second_tranche(grant_id)

        resubmitted = submit_grant(grant_id)
        assert resubmitted["status"] == "PENDING_APPROVAL", (
            "submitting closes the cycle back to PENDING_APPROVAL"
        )
        assert resubmitted["changes_requested_count"] == 1
        assert resubmitted["submitted_by_user_id"] == "admin-1"
        assert_grant(resubmitted)

        plan = read_plan(scenario["plan"]["id"])
        assert plan["shares_committed_cumulative"] == 0, (
            "sending a grant back touches no reserve figure"
        )
        assert plan["fiscal_year_gross_granted_shares"] == 0
        assert plan["available_reserve_shares"] == 1_000_000

    def test_third_send_back_is_refused_and_leaves_the_grant_pending(self):
        """PRD §3.4: "The counter is compared against a cap of 2 **before** the increment, so the first and second send-backs are allowed and the third is refused with `ERR_MAX_GRANT_REVISIONS_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/grant_changes_requested_revision_cycle
        """
        scenario = _pending_grant_scenario()
        grant_id = scenario["grant"]["id"]
        pending = _walk_grant_cycle_twice(grant_id)
        assert pending["status"] == "PENDING_APPROVAL"
        assert pending["changes_requested_count"] == 2, (
            "the first and second send-backs are allowed"
        )

        validate_error(
            api_client.request_grant_changes(
                grant_id,
                request_changes_payload("Third pass - must be refused."),
                BOARD,
            ),
            ApiErrorId.ERR_MAX_GRANT_REVISIONS_EXCEEDED,
        )

        stored = read_grant(grant_id)
        assert stored["status"] == "PENDING_APPROVAL", (
            "the refused third send-back leaves the grant where it was"
        )
        assert stored["changes_requested_count"] == 2, (
            "the counter is compared before the increment, so a refusal does "
            "not advance it"
        )
        assert stored["target_shares"] == 12000

    def test_grant_still_approves_after_the_refused_third_send_back(self):
        """PRD §3.4: "Both paths move the grant from `PENDING_APPROVAL` to `APPROVED`, record `approved_by_user_id` from the acting `X-User-ID`, stamp `approved_at` from the logical clock, store the chosen `approval_path`, write `weighted_reserve_shares` from the calculation above, add that figure to the plan's `shares_committed_cumulative` and to its `fiscal_year_gross_granted_shares`, and then rerun the reserve ledger and both burn-rate variants."

        Design: Difficulty/non_linear_state_machine/grant_changes_requested_revision_cycle
        """
        scenario = _pending_grant_scenario()
        grant_id = scenario["grant"]["id"]
        _walk_grant_cycle_twice(grant_id)
        validate_error(
            api_client.request_grant_changes(
                grant_id,
                request_changes_payload("Third pass - must be refused."),
                BOARD,
            ),
            ApiErrorId.ERR_MAX_GRANT_REVISIONS_EXCEEDED,
        )

        approved = validate_success(
            api_client.approve_grant(
                grant_id, {"approval_path": "BOARD"}, BOARD
            ),
            200,
        )
        assert approved["status"] == "APPROVED", (
            "a capped-out grant remains approvable"
        )
        assert approved["approval_path"] == "BOARD"
        assert approved["approved_by_user_id"] == "board-1"
        assert approved["submitted_by_user_id"] == "admin-1"
        assert approved["changes_requested_count"] == 2
        assert approved["target_shares"] == 12000
        assert approved["weighted_reserve_shares"] == 18000, (
            "12000 full-value shares weighted at 15000 bps"
        )
        assert_grant(approved)

        plan = read_plan(scenario["plan"]["id"])
        assert plan["shares_committed_cumulative"] == 18000
        assert plan["fiscal_year_gross_granted_shares"] == 18000
        assert plan["available_reserve_shares"] == 982000
        assert_reserve_conservation(plan)


def _preclearance_scenario():
    """One DESIGNATED_INSIDER holding a SUBMITTED request for 500 shares inside an
    OPEN window, filed by the participant so a compliance decider satisfies the
    four-eyes control."""
    set_clock("2026-01-06T10:00:00Z")
    plan = create_plan(
        name="Plan F Preclear",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=0,
    )
    participant = create_participant(
        full_name="Finn Insider",
        employee_number="E-2882-06",
        home_country_code="US",
        home_state_code="MA",
        hire_date="2017-05-22",
        birth_date="1979-12-04",
        insider_status="DESIGNATED_INSIDER",
    )
    window = create_open_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at=_WINDOW_OPEN_AT, close_at=_WINDOW_CLOSE_AT,
    )
    request = create_preclearance(
        participant["id"], window["id"],
        transaction_type="SELL", requested_shares=500,
        intended_trade_date="2026-01-15",
    )
    return {"plan": plan, "participant": participant, "window": window,
            "request": request}


def _walk_preclearance_cycle_twice(scenario):
    """Traverse SUBMITTED -> INFO_REQUESTED -> SUBMITTED twice, raising the share
    count to 600 and then 700. Leaves the request SUBMITTED."""
    participant_headers = make_participant_headers(scenario["participant"]["id"])
    request_id = scenario["request"]["id"]
    decide_preclearance(
        request_id, "REQUEST_INFO",
        decision_note="Attach the broker confirmation.",
    )
    resubmit_preclearance(request_id, 600, "2026-01-15",
                          headers=participant_headers)
    decide_preclearance(
        request_id, "REQUEST_INFO", decision_note="Confirm the share count."
    )
    return resubmit_preclearance(request_id, 700, "2026-01-15",
                                 headers=participant_headers)


class TestPreclearanceInformationRequestCycle:
    """The preclearance information loop, its cap, and the clearance that exits it."""

    def test_information_request_then_resubmit_advances_only_the_revision_count(self):
        """PRD §3.9: "`REQUEST_INFO` moves the request from `SUBMITTED` to `INFO_REQUESTED`, stores the `decision_note`, stamps `decided_by_user_id` and `decided_at`, leaves `valid_until` null, and takes no share reservation."

        PRD §3.9: "Resubmission moves the request back to `SUBMITTED`, overwrites both fields, clears `decision_note` to null, and increments `revision_count` by 1; the cap itself is enforced on the decision that opens each loop, not here."

        Design: Difficulty/non_linear_state_machine/preclearance_info_requested_resubmit_cycle
        """
        scenario = _preclearance_scenario()
        request_id = scenario["request"]["id"]
        assert scenario["request"]["status"] == "SUBMITTED"
        assert scenario["request"]["revision_count"] == 0

        bounced = validate_success(
            api_client.decide_preclearance_request(
                request_id,
                decide_payload(
                    "REQUEST_INFO",
                    decision_note="Attach the broker confirmation.",
                ),
                COMPLIANCE,
            ),
            200,
        )
        assert bounced["status"] == "INFO_REQUESTED"
        assert bounced["decision_note"] == "Attach the broker confirmation."
        assert bounced["decided_by_user_id"] == "compliance-1"
        assert bounced["valid_until"] is None, (
            "REQUEST_INFO leaves valid_until null"
        )
        assert bounced["revision_count"] == 0, (
            "the information request itself does not bump revision_count"
        )
        window = read_window(scenario["window"]["id"])
        assert window["approved_shares_cumulative"] == 0, (
            "REQUEST_INFO takes no share reservation"
        )

        resubmitted = resubmit_preclearance(
            request_id, 600, "2026-01-15",
            headers=make_participant_headers(scenario["participant"]["id"]),
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["requested_shares"] == 600
        assert resubmitted["intended_trade_date"] == "2026-01-15"
        assert resubmitted["decision_note"] is None, (
            "resubmission clears decision_note to null"
        )
        assert resubmitted["revision_count"] == 1, (
            "resubmission increments revision_count by 1"
        )
        assert_preclearance_request(resubmitted)

    def test_third_information_request_is_refused_and_leaves_the_request_submitted(self):
        """PRD §3.9: "Its own guard is the revision cap: `revision_count` is compared against 2 before the loop is opened, so the first and second information requests are allowed and the third is refused with `ERR_MAX_PRECLEARANCE_REVISIONS_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/preclearance_info_requested_resubmit_cycle
        """
        scenario = _preclearance_scenario()
        request_id = scenario["request"]["id"]
        submitted = _walk_preclearance_cycle_twice(scenario)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["revision_count"] == 2, (
            "the first and second information requests are allowed"
        )
        assert submitted["requested_shares"] == 700

        validate_error(
            api_client.decide_preclearance_request(
                request_id,
                decide_payload(
                    "REQUEST_INFO",
                    decision_note="Third pass - must be refused.",
                ),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_MAX_PRECLEARANCE_REVISIONS_EXCEEDED,
        )

        stored = read_preclearance(request_id)
        assert stored["status"] == "SUBMITTED", (
            "the refused third information request leaves the row SUBMITTED"
        )
        assert stored["revision_count"] == 2, (
            "the cap is compared before the loop is opened, so a refusal does "
            "not advance the counter"
        )
        assert stored["requested_shares"] == 700

    def test_approval_exits_the_loop_and_stamps_a_five_day_validity(self):
        """PRD §3.9: "On success the request becomes `APPROVED`, `decided_by_user_id`, `decided_at`, and `decision_note` are stored, `valid_until` is computed as described below, the window's `approved_shares_cumulative` is increased by `requested_shares`, and both the request's `version` and the window's `version` advance by 1."

        PRD §3.9: "On approval, `valid_until` is the earlier of the `decided_at` instant advanced by 5 days and the window's own `close_at` — a clearance is good for five days or until the window closes, whichever comes first. The arithmetic is exact instant arithmetic."

        Design: Difficulty/non_linear_state_machine/preclearance_info_requested_resubmit_cycle
        """
        scenario = _preclearance_scenario()
        request_id = scenario["request"]["id"]
        _walk_preclearance_cycle_twice(scenario)
        validate_error(
            api_client.decide_preclearance_request(
                request_id,
                decide_payload(
                    "REQUEST_INFO",
                    decision_note="Third pass - must be refused.",
                ),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_MAX_PRECLEARANCE_REVISIONS_EXCEEDED,
        )

        approved = validate_success(
            api_client.decide_preclearance_request(
                request_id,
                decide_payload("APPROVE", decision_note="Cleared."),
                COMPLIANCE,
            ),
            200,
        )
        assert approved["status"] == "APPROVED", (
            "a capped-out request is still decidable"
        )
        assert approved["revision_count"] == 2
        assert approved["requested_shares"] == 700
        assert approved["decided_by_user_id"] == "compliance-1"
        assert approved["decision_note"] == "Cleared."
        assert_instant_equals(
            approved["decided_at"], "2026-01-06T10:00:00.000Z",
            "decided_at is stamped from the logical clock",
        )
        assert_instant_equals(
            approved["valid_until"], "2026-01-11T10:00:00.000Z",
            "valid_until is decided_at advanced by 5 days, which precedes the "
            "window close",
        )
        assert_preclearance_request(approved)

        window = read_window(scenario["window"]["id"])
        assert window["approved_shares_cumulative"] == 700, (
            "the window reserves the shares of the surviving revision"
        )
        assert window["status"] == "OPEN"
        assert_trading_window(window)
