"""Corner coverage: error catalog behavior — OCC stale versions, temporal
window boundaries, message/session shape limits, lifecycle gates, activation
and uniqueness constraints, missing pricing source, and the two escheat
exits (PRD §2.7, §3.1, §3.2, §3.3, §3.5, §3.6, §3.7, §3.9).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_closure_balance_partition,
    book_inmate,
    close_account,
    connect_call,
    create_cap_amendment_payload,
    create_contract,
    create_facility_raw,
    create_inmate_payload,
    create_message_payload,
    create_rate_schedule,
    create_regulatory_cap,
    create_regulatory_cap_payload,
    create_video_session_payload,
    create_verified_recipient,
    deposit,
    get_account,
    get_regulatory_summary,
    get_success_data,
    iso_days_after,
    make_account_holder_headers,
    make_compliance_officer_headers,
    open_account,
    setup_account_with_confirmed_session,
    setup_active_facility,
    setup_call_ready_account,
    setup_complaint_under_review,
    setup_funded_account,
    setup_notice_sent_account,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_stale_contract_version_on_schedule_activate_returns_412(
    api, platform_admin_headers
):
    """PRD §2.7: "Activating a rate schedule requires the request to carry `expected_contract_version`, holding the parent contract's `version` as the client last observed it. Activation supersedes whichever schedule is currently active on that contract and advances the contract's `version` by one; if the contract's current `version` no longer matches the value the client last read — because another schedule was activated in between, which legitimately superseded the prior one — the client's view of which schedule is active is stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_contract_version_on_schedule_activate_returns_412
    """
    create_regulatory_cap()
    facility = create_facility_raw(name="OCC Facility")
    contract = create_contract(facility["id"])
    validate_success(api.activate_contract(contract["id"], platform_admin_headers))
    contract = get_success_data(api.get_contract(contract["id"], platform_admin_headers))
    observed_version = contract["version"]

    s1 = create_rate_schedule(contract["id"], local_per_minute_cents=19)
    s2 = create_rate_schedule(contract["id"])

    first = validate_success(
        api.activate_rate_schedule(s1["id"], observed_version, platform_admin_headers)
    )
    assert first["status"] == "ACTIVE"

    stale = api.activate_rate_schedule(s2["id"], observed_version, platform_admin_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    refreshed = get_success_data(api.get_contract(contract["id"], platform_admin_headers))
    assert refreshed["version"] == observed_version + 1

    retry = validate_success(
        api.activate_rate_schedule(s2["id"], refreshed["version"], platform_admin_headers)
    )
    assert retry["status"] == "ACTIVE"
    s1_after = get_success_data(api.get_rate_schedule(s1["id"], platform_admin_headers))
    assert s1_after["status"] == "SUPERSEDED"
    final = get_success_data(api.get_contract(contract["id"], platform_admin_headers))
    assert final["version"] == observed_version + 2, (
        "each schedule activation advances the contract version by exactly one"
    )


def test_stale_cap_version_on_amend_returns_412(api, state_regulator_headers):
    """PRD §2.7: "Amending a regulatory cap row requires the request to carry `expected_regulatory_cap_version`, holding the cap row's `version` as the client last observed it. Amendment replaces the jurisdiction's cap values in place and advances the row's `version` by one; if the row's current `version` has advanced since the client last read it, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently overwriting newer values."

    Design: Corner/errors/stale_cap_version_on_amend_returns_412
    """
    cap = create_regulatory_cap()
    observed_version = cap["version"]

    amended = validate_success(
        api.amend_regulatory_cap(
            cap["id"],
            create_cap_amendment_payload(observed_version, max_per_minute_cents=21),
            state_regulator_headers,
        )
    )
    assert amended["max_per_minute_cents"] == 21

    stale = api.amend_regulatory_cap(
        cap["id"],
        create_cap_amendment_payload(observed_version, max_connection_fee_cents=250),
        state_regulator_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    reread = validate_success(api.get_regulatory_cap(cap["id"], state_regulator_headers))
    assert reread["max_connection_fee_cents"] == 300, "first amendment stays intact"
    assert reread["max_per_minute_cents"] == 21
    assert reread["version"] == observed_version + 1


def test_complaint_escalation_before_min_age_fails_at_boundary(
    api, compliance_officer_headers
):
    """PRD §3.9: "Alternatively, the officer may escalate the complaint to the state regulator, but only once it has reached the platform's minimum escalation age of seven days: a complaint exactly seven days old may be escalated, a younger one fails with `ERR_ESCALATION_TOO_EARLY`, and escalation stamps `escalated_at` on the way to `ESCALATED_TO_REGULATOR`."

    Design: Corner/errors/complaint_escalation_before_min_age_fails_at_boundary
    """
    env = setup_complaint_under_review()
    complaint = env["complaint"]
    filed_at = complaint["created_at"]

    advance_clock_to(iso_days_after(filed_at, 6))
    early = api.escalate_complaint(complaint["id"], compliance_officer_headers)
    validate_error(early, ApiErrorId.ERR_ESCALATION_TOO_EARLY)
    mid = get_success_data(api.get_complaint(complaint["id"], compliance_officer_headers))
    assert mid["status"] == "UNDER_REVIEW"

    seventh_day = iso_days_after(filed_at, 7)
    advance_clock_to(seventh_day)
    escalated = validate_success(
        api.escalate_complaint(complaint["id"], compliance_officer_headers)
    )
    assert escalated["status"] == "ESCALATED_TO_REGULATOR"
    assert escalated["escalated_at"].startswith(seventh_day[:16])


def test_escheat_remit_before_claim_window_fails_then_remitted_at_boundary(
    api, compliance_officer_headers
):
    """PRD §3.9: "Remittance to the state is allowed only from `NOTICE_SENT` (again, `ERR_INVALID_STATE` otherwise) and only once the logical clock has reached the notice instant plus the jurisdiction's `claim_window_days`: a clock exactly at that boundary allows remittance, while anything earlier fails with `ERR_CLAIM_WINDOW_OPEN`."
    PRD §3.9: "Remittance moves the account to `REMITTED`, the terminal escheat state; it appends an `ESCHEAT_REMITTANCE` debit of the full `unclaimed_balance_cents` together with a settling `CLOSURE_FEE` debit of the closure snapshot minus all prior payouts and remittances minus the unclaimed balance just remitted; and it drives the ledger balance to zero."

    Design: Corner/errors/escheat_remit_before_claim_window_fails_then_remitted_at_boundary
    """
    env = setup_notice_sent_account()
    account = env["account"]
    assert account["escheat_status"] == "NOTICE_SENT"
    assert account["unclaimed_balance_cents"] == 900
    notice_at = account["escheat_notice_sent_at"]

    advance_clock_to(iso_days_after(notice_at, 44))
    early = api.remit_escheat(account["id"], compliance_officer_headers)
    validate_error(early, ApiErrorId.ERR_CLAIM_WINDOW_OPEN)
    mid = get_account(account["id"])
    assert mid["escheat_status"] == "NOTICE_SENT"

    advance_clock_to(iso_days_after(notice_at, 45))
    remitted = validate_success(api.remit_escheat(account["id"], compliance_officer_headers))
    assert remitted["escheat_status"] == "REMITTED"

    final = get_account(account["id"])
    assert final["balance_cents"] == 0
    assert final["escheated_total_cents"] == 900
    assert final["retained_fees_cents"] == 100
    assert final["unclaimed_balance_cents"] == 0
    assert_closure_balance_partition(final, remaining_frozen_cents=0)


def test_message_over_1000_chars_rejected_exactly_at_limit_ok(
    api, compliance_officer_headers
):
    """PRD §3.6: "Tablet messaging lets an `AccountHolder` write to the inmate their account serves, one message at a time, with `account_id`, `inmate_id`, and the `body_text` — which may not exceed 1000 characters, on pain of `ERR_MESSAGE_TOO_LONG`."

    Design: Corner/errors/message_over_1000_chars_rejected_exactly_at_limit_ok
    """
    env = setup_funded_account()
    account, inmate = env["account"], env["inmate"]
    holder = make_account_holder_headers(account["id"])

    at_limit = validate_success(
        api.create_message(
            create_message_payload(account["id"], inmate["id"], "x" * 1000),
            holder,
        ),
        201,
    )
    assert at_limit["status"] == "PENDING_REVIEW"
    assert at_limit["price_cents"] == 15
    assert get_account(account["id"])["balance_cents"] == 985

    over_limit = api.create_message(
        create_message_payload(account["id"], inmate["id"], "x" * 1001),
        holder,
    )
    validate_error(over_limit, ApiErrorId.ERR_MESSAGE_TOO_LONG)
    assert over_limit.status_code == 422

    _rows, meta = validate_paginated(
        api.list_messages(
            compliance_officer_headers, params={"account_id": account["id"]}
        )
    )
    assert meta["total_count"] == 1, "the rejected message persists no row"


def test_session_duration_bounds_and_visiting_window(api):
    """PRD §3.7: "Creation validates the shape of the request: the end must be strictly after the start, the session must run at least fifteen minutes and no longer than the facility's `max_session_minutes`, start and end must fall on the same UTC date, and the whole session must sit inside the visiting window bounded by `visiting_open_minutes` and `visiting_close_minutes` — any breach fails with `ERR_SESSION_DURATION_INVALID`."

    Design: Corner/errors/session_duration_bounds_and_visiting_window
    """
    env = setup_funded_account()
    facility, inmate, account = env["facility"], env["inmate"], env["account"]
    holder = make_account_holder_headers(account["id"])

    cases = [
        ("2026-09-24T10:00:00Z", "2026-09-24T10:31:00Z"),  # 31 > max 30
        ("2026-09-24T11:00:00Z", "2026-09-24T11:14:00Z"),  # 14 < min 15
        ("2026-09-24T19:45:00Z", "2026-09-24T20:15:00Z"),  # ends past window close
    ]
    for start, end in cases:
        resp = api.create_video_session(
            create_video_session_payload(
                facility["id"], inmate["id"], account["id"], start, end
            ),
            holder,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_DURATION_INVALID)
        assert resp.status_code == 422

    ok = validate_success(
        api.create_video_session(
            create_video_session_payload(
                facility["id"],
                inmate["id"],
                account["id"],
                "2026-09-24T12:00:00Z",
                "2026-09-24T12:30:00Z",
            ),
            holder,
        ),
        201,
    )
    assert ok["duration_minutes"] == 30
    assert ok["status"] == "REQUESTED"


def test_close_out_before_session_end_and_cancel_after_start_rejected(
    api, facility_staff_headers
):
    """PRD §3.7: "Once the logical clock reaches `scheduled_end`, `FacilityStaff` close the session out; earlier attempts fail with `ERR_SESSION_NOT_ENDED`."
    PRD §3.7: "Cancelling a `CONFIRMED` session is possible only while the logical clock is still before `scheduled_start`; at or after the start, the attempt fails with `ERR_SESSION_NOT_CANCELLABLE`."

    Design: Corner/errors/close_out_before_session_end_and_cancel_after_start_rejected
    """
    env = setup_account_with_confirmed_session(
        session_kwargs={
            "scheduled_start": "2026-09-05T10:00:00Z",
            "scheduled_end": "2026-09-05T10:30:00Z",
        }
    )
    session, account = env["session"], env["account"]
    assert account["balance_cents"] == 500

    early_close = api.close_out_video_session(
        session["id"], "COMPLETED", facility_staff_headers
    )
    validate_error(early_close, ApiErrorId.ERR_SESSION_NOT_ENDED)

    advance_clock_to("2026-09-05T10:15:00Z")
    late_cancel = api.cancel_video_session(
        session["id"], make_account_holder_headers(account["id"])
    )
    validate_error(late_cancel, ApiErrorId.ERR_SESSION_NOT_CANCELLABLE)

    advance_clock_to("2026-09-05T10:30:00Z")
    closed_out = validate_success(
        api.close_out_video_session(session["id"], "COMPLETED", facility_staff_headers)
    )
    assert closed_out["status"] == "COMPLETED"

    assert get_account(account["id"])["balance_cents"] == 500, (
        "the charge stands throughout: no refund fires on either rejection "
        "or on a completed close-out"
    )


def test_contract_activation_rejects_over_cap_commission_and_second_active(
    api, platform_admin_headers
):
    """PRD §3.2: "the `commission_pct` must not exceed the jurisdiction's `max_commission_pct` — a commission exactly equal to the cap is acceptable — or the request fails with `ERR_COMMISSION_EXCEEDS_CAP`; and no other contract for the same facility may already be `ACTIVE` (otherwise `ERR_ACTIVE_CONTRACT_EXISTS`)."

    Design: Corner/errors/contract_activation_rejects_over_cap_commission_and_second_active
    """
    create_regulatory_cap()
    facility = create_facility_raw(name="Commission Facility")
    c1 = create_contract(facility["id"], commission_pct=0.7)
    c2 = create_contract(facility["id"], commission_pct=0.5)
    c3 = create_contract(facility["id"], commission_pct=0.4, commission_basis="NET")

    over_cap = api.activate_contract(c1["id"], platform_admin_headers)
    validate_error(over_cap, ApiErrorId.ERR_COMMISSION_EXCEEDS_CAP)
    assert get_success_data(api.get_contract(c1["id"], platform_admin_headers))[
        "status"
    ] == "DRAFT"

    activated = validate_success(api.activate_contract(c2["id"], platform_admin_headers))
    assert activated["status"] == "ACTIVE"

    second_active = api.activate_contract(c3["id"], platform_admin_headers)
    validate_error(second_active, ApiErrorId.ERR_ACTIVE_CONTRACT_EXISTS)
    assert get_success_data(api.get_contract(c3["id"], platform_admin_headers))[
        "status"
    ] == "DRAFT"


def test_duplicate_cap_for_state_and_duplicate_booking_number_rejected(
    api, state_regulator_headers, facility_staff_headers
):
    """PRD §3.1: "Only one cap row may exist per jurisdiction; a second row for the same `state_code` is rejected with `ERR_DUPLICATE_CAP_FOR_STATE`."
    PRD §3.3: "The booking number must be unique among the facility's inmates who are currently `IN_CUSTODY`; reusing one fails with `ERR_DUPLICATE_BOOKING_NUMBER`."

    Design: Corner/errors/duplicate_cap_for_state_and_duplicate_booking_number_rejected
    """
    create_regulatory_cap()
    duplicate_cap = api.create_regulatory_cap(
        create_regulatory_cap_payload(
            max_per_minute_cents=20,
            max_connection_fee_cents=250,
            max_ancillary_fee_cents=400,
            max_deposit_fee_cents=400,
            max_commission_pct=0.5,
            refund_method="LIFO_NET",
            dormancy_days=60,
            claim_window_days=30,
        ),
        state_regulator_headers,
    )
    validate_error(duplicate_cap, ApiErrorId.ERR_DUPLICATE_CAP_FOR_STATE)
    caps, caps_meta = validate_paginated(
        api.list_regulatory_caps(state_regulator_headers, params={"state_code": "ST"})
    )
    assert caps_meta["total_count"] == 1 and len(caps) == 1
    assert caps[0]["max_per_minute_cents"] == 25, "the original row is untouched"

    facility = create_facility_raw(name="Uniq Facility")
    book_inmate(facility["id"], booking_number="B-1000", full_name="Inmate First")
    duplicate_booking = api.create_inmate(
        create_inmate_payload(
            facility["id"], booking_number="B-1000", full_name="Inmate Second"
        ),
        facility_staff_headers,
    )
    validate_error(duplicate_booking, ApiErrorId.ERR_DUPLICATE_BOOKING_NUMBER)
    inmates, inmates_meta = validate_paginated(
        api.list_inmates(facility_staff_headers, params={"facility_id": facility["id"]})
    )
    assert inmates_meta["total_count"] == 1 and len(inmates) == 1


def test_call_without_active_schedule_returns_no_active_rate_schedule(
    api, platform_admin_headers, facility_staff_headers
):
    """PRD §3.5: "The recipient must be `VERIFIED` (`ERR_NUMBER_NOT_VERIFIED`) and must not be `BLOCKED` (`ERR_NUMBER_BLOCKED`), and the contract's active rate schedule must exist (`ERR_NO_ACTIVE_RATE_SCHEDULE`)."

    Design: Corner/errors/call_without_active_schedule_returns_no_active_rate_schedule
    """
    create_regulatory_cap()
    facility = create_facility_raw(name="NoSched Facility")
    contract = create_contract(facility["id"])
    validate_success(api.activate_contract(contract["id"], platform_admin_headers))
    schedule = create_rate_schedule(contract["id"])  # left DRAFT on purpose
    validate_success(api.activate_facility(facility["id"], platform_admin_headers))
    inmate = book_inmate(facility["id"])
    account = open_account(facility["id"], inmate["id"])
    recipient = create_verified_recipient(account["id"])
    deposit(account, 1025)

    resp = api.create_call(
        {
            "account_id": account["id"],
            "inmate_id": inmate["id"],
            "recipient_number_id": recipient["id"],
            "call_type": "LOCAL",
        },
        facility_staff_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE_SCHEDULE)

    assert get_success_data(api.get_rate_schedule(schedule["id"], platform_admin_headers))[
        "status"
    ] == "DRAFT"
    assert get_account(account["id"])["balance_cents"] == 1000
    _rows, meta = validate_paginated(
        api.list_calls(facility_staff_headers, params={"account_id": account["id"]})
    )
    assert meta["total_count"] == 0


def test_escheat_claim_reopens_payout_then_remitted_account_rejects_claim(
    api, platform_admin_headers
):
    """PRD §3.9: "Claiming the unclaimed balance — by the `AccountHolder` themself, from either `DORMANT` or `NOTICE_SENT`, otherwise `ERR_ESCHEAT_NOT_CLAIMABLE` — moves `escheat_status` to `CLAIMED` and creates a **RefundRequest** with `source` `ESCHEAT_CLAIM` that is already `APPROVED`: its `requested_amount_cents` and `computed_payout_cents` both equal the unclaimed balance at claim time, its `decided_by_user_id` is 'system', and the account's `latest_refund_request_id` is updated."
    PRD §3.8: "Disbursement is a separate act by a `ComplianceOfficer`, and it carries its own segregation check: the payer's identity must differ from `decided_by_user_id` — a 'system' decider never conflicts — otherwise `ERR_SOD_VIOLATION`, and only an `APPROVED` request can be paid, anything else failing with `ERR_REFUND_NOT_PAYABLE`."

    Design: Corner/errors/escheat_claim_reopens_payout_then_remitted_account_rejects_claim
    """
    env = setup_active_facility()
    facility = env["facility"]
    officer1 = make_compliance_officer_headers("co-1")
    officer2 = make_compliance_officer_headers("co-2")

    accounts = []
    for name in ("Claim One", "Claim Two"):
        inmate = book_inmate(facility["id"], full_name=f"Inmate {name}")
        account = open_account(facility["id"], inmate["id"], owner_name=f"Fam {name}")
        deposit(account, 1025)
        accounts.append(account)
    a1, a2 = accounts

    for account in (a1, a2):
        closed = close_account(account)
        validate_success(
            api.decide_refund_request(
                closed["latest_refund_request_id"],
                "DENY",
                officer1,
                denial_reason="owner not located",
            )
        )

    advance_clock_to("2026-10-01T00:00:00Z")
    scan = validate_success(api.run_dormancy_scan(facility["id"], platform_admin_headers))
    assert scan["accounts_flagged"] == 2
    for account in (a1, a2):
        validate_success(api.send_escheat_notice(account["id"], officer1))

    # A1: the holder claims before remittance.
    advance_clock_to("2026-10-20T00:00:00Z")
    claimed = validate_success(
        api.claim_unclaimed(a1["id"], make_account_holder_headers(a1["id"]))
    )
    assert claimed["escheat_status"] == "CLAIMED"
    claim_rr_id = claimed["latest_refund_request_id"]
    claim_rr = validate_success(api.get_refund_request(claim_rr_id, officer1))
    assert claim_rr["source"] == "ESCHEAT_CLAIM"
    assert claim_rr["status"] == "APPROVED"
    assert claim_rr["requested_amount_cents"] == 900
    assert claim_rr["computed_payout_cents"] == 900
    assert claim_rr["decided_by_user_id"] == "system"

    paid = validate_success(api.mark_refund_paid(claim_rr_id, officer1))
    assert paid["status"] == "PAID", "a 'system' decider never conflicts on SoD"
    a1_final = get_account(a1["id"])
    assert a1_final["balance_cents"] == 0
    assert a1_final["refunded_total_cents"] == 900
    assert a1_final["retained_fees_cents"] == 100
    assert a1_final["unclaimed_balance_cents"] == 0

    # A2: remitted first; the late claim is rejected.
    advance_clock_to("2026-11-16T00:00:00Z")
    remitted = validate_success(api.remit_escheat(a2["id"], officer2))
    assert remitted["escheat_status"] == "REMITTED"

    late_claim = api.claim_unclaimed(a2["id"], make_account_holder_headers(a2["id"]))
    validate_error(late_claim, ApiErrorId.ERR_ESCHEAT_NOT_CLAIMABLE)
    a2_final = get_account(a2["id"])
    assert a2_final["escheat_status"] == "REMITTED"
    assert a2_final["escheated_total_cents"] == 900
