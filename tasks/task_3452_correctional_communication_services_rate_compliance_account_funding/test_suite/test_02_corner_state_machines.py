"""Corner coverage: state-machine guards, terminal-state lockdown, and
pinned side effects across contract termination, privilege revocation, and
call completion (PRD §3.2, §3.4, §3.5, §3.8, §3.9).
"""
from test_helpers import (
    ApiErrorId,
    activate_contract,
    book_inmate,
    connect_call,
    create_contract,
    create_facility_raw,
    create_rate_schedule,
    create_recipient,
    create_regulatory_cap,
    create_video_session_payload,
    decide_privilege,
    file_complaint,
    get_account,
    get_ledger,
    get_success_data,
    make_account_holder_headers,
    open_account,
    release_inmate,
    setup_active_facility,
    setup_call_ready_account,
    setup_funded_account,
    validate_error,
    validate_success,
    verify_recipient,
)


def test_contract_double_activate_returns_invalid_state(
    api, platform_admin_headers
):
    """PRD §3.2: "Activation, by a `PlatformAdmin`, moves the contract from `DRAFT` to `ACTIVE`, and it is where commercial terms meet regulation."
    PRD §2.8: "The target resource and its directly gating parents must be in a valid state for the operation — a facility active for calls, video, or messaging; an account active for deposits, calls, messages, or video; an inmate in custody; a contract active for schedule activation; a state machine's required source state matching the resource's current state. Failures surface as `ERR_INVALID_STATE`, `ERR_FACILITY_NOT_ACTIVE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_INMATE_NOT_IN_CUSTODY`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_NO_ACTIVE_CONTRACT`, or `ERR_NO_ACTIVE_RATE_SCHEDULE`."

    Design: Corner/state_machines/contract_double_activate_returns_invalid_state
    """
    create_regulatory_cap()
    facility = create_facility_raw(name="Idem Facility")
    contract = create_contract(facility["id"])
    activated = activate_contract(contract["id"])
    assert activated["status"] == "ACTIVE"
    version_after = activated["version"]

    second = api.activate_contract(contract["id"], platform_admin_headers)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    reread = validate_success(api.get_contract(contract["id"], platform_admin_headers))
    assert reread["status"] == "ACTIVE"
    assert reread["version"] == version_after, (
        "a rejected re-activation must not mutate the contract "
        f"(version {reread['version']} != {version_after})"
    )


def test_released_inmate_is_terminal_and_blocks_new_activity(
    api, facility_staff_headers
):
    """PRD §3.8: "When `FacilityStaff` release an inmate, `status` moves from `IN_CUSTODY` to `RELEASED`, `released_at` is stamped from the logical clock — and then three things happen in a pinned order."
    PRD §3.7: "The start must also lie strictly in the future (`ERR_SESSION_IN_PAST`), the inmate must be `IN_CUSTODY` (`ERR_INMATE_NOT_IN_CUSTODY`), and the facility and account state gates apply as usual."

    Design: Corner/state_machines/released_inmate_is_terminal_and_blocks_new_activity
    """
    env = setup_funded_account()
    inmate = env["inmate"]
    account = env["account"]

    released = release_inmate(inmate["id"])
    assert released["status"] == "RELEASED"

    second = api.release_inmate(inmate["id"], facility_staff_headers)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    session_attempt = api.create_video_session(
        create_video_session_payload(
            env["facility"]["id"],
            inmate["id"],
            account["id"],
            "2026-09-20T10:00:00Z",
            "2026-09-20T10:30:00Z",
        ),
        facility_staff_headers,
    )
    validate_error(session_attempt, ApiErrorId.ERR_INMATE_NOT_IN_CUSTODY)

    reread = validate_success(api.get_inmate(inmate["id"], facility_staff_headers))
    assert reread["status"] == "RELEASED"


def test_contract_terminate_supersedes_active_schedule_but_calls_keep_pins(
    api, platform_admin_headers, facility_staff_headers
):
    """PRD §3.2: "Termination moves an `ACTIVE` contract to `TERMINATED`, its terminal state; the contract's active rate schedule, if any, is superseded in the same motion, while call records that pinned that schedule keep their `rate_schedule_id` and their applied rates untouched."
    PRD §3.5: "The recipient must be `VERIFIED` (`ERR_NUMBER_NOT_VERIFIED`) and must not be `BLOCKED` (`ERR_NUMBER_BLOCKED`), and the contract's active rate schedule must exist (`ERR_NO_ACTIVE_RATE_SCHEDULE`)."

    Design: Corner/state_machines/contract_terminate_supersedes_active_schedule_but_calls_keep_pins
    """
    env = setup_call_ready_account()
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]
    schedule_id = env["schedule"]["id"]

    call = connect_call(account, inmate, recipient, call_type="LOCAL")
    assert call["rate_schedule_id"] == schedule_id
    assert call["applied_per_minute_cents"] == 18

    validate_success(api.terminate_contract(env["contract"]["id"], platform_admin_headers))

    schedule = validate_success(api.get_rate_schedule(schedule_id, platform_admin_headers))
    assert schedule["status"] == "SUPERSEDED"

    pinned = validate_success(api.get_call(call["id"], facility_staff_headers))
    assert pinned["rate_schedule_id"] == schedule_id
    assert pinned["applied_per_minute_cents"] == 18

    ended = validate_success(api.end_call(call["id"], 60, facility_staff_headers))
    assert ended["total_charge_cents"] == 218, (
        "ending the call bills at the pinned rate: 200 connection + 1 x 18"
    )

    new_call = api.create_call(
        {
            "account_id": account["id"],
            "inmate_id": inmate["id"],
            "recipient_number_id": recipient["id"],
            "call_type": "LOCAL",
        },
        facility_staff_headers,
    )
    validate_error(new_call, ApiErrorId.ERR_NO_ACTIVE_RATE_SCHEDULE)


def test_privilege_revoke_keeps_existing_call_exempt_new_calls_recorded(
    api, facility_staff_headers
):
    """PRD §3.4: "While a number is `PRIVILEGED`, calls to it are exempt from recording — their `recording_status` is pinned to `EXEMPT_PRIVILEGED` at connect — and revocation affects only future calls: existing call records keep the recording status they pinned, by the same version-pinning discipline that protects pinned rates."
    PRD §3.4: "a decision of `REVOKE` moves it to `REVOKED` from either `PRIVILEGE_REQUESTED` or `PRIVILEGED`, and any other starting point fails with `ERR_INVALID_STATE`. The officer's optional `note` is recorded as `privilege_decision_note`."

    Design: Corner/state_machines/privilege_revoke_keeps_existing_call_exempt_new_calls_recorded
    """
    env = setup_funded_account(deposit_amount=2025)
    account, inmate = env["account"], env["inmate"]

    atty = create_recipient(
        account["id"], label="Atty Rivera", relationship_type="ATTORNEY"
    )
    assert atty["privilege_status"] == "PRIVILEGE_REQUESTED"
    verify_recipient(atty)
    decide_privilege(
        atty["id"], "VERIFY", note="bar verified with state bar association"
    )

    privileged_call = connect_call(account, inmate, atty, call_type="LOCAL")
    assert privileged_call["recording_status"] == "EXEMPT_PRIVILEGED"

    revoked = decide_privilege(
        atty["id"],
        "REVOKE",
        note="bar number mismatch discovered",
        officer_id="co-2",
    )
    assert revoked["privilege_status"] == "REVOKED"
    assert revoked["privilege_decision_note"] == "bar number mismatch discovered"

    pinned = validate_success(
        api.get_call(privileged_call["id"], facility_staff_headers)
    )
    assert pinned["recording_status"] == "EXEMPT_PRIVILEGED", (
        "revocation must not rewrite the recording status pinned at connect"
    )

    after_call = connect_call(account, inmate, atty, call_type="LOCAL")
    assert after_call["recording_status"] == "RECORDED"


def test_call_end_with_zero_duration_is_not_connected_and_charges_nothing(
    api, facility_staff_headers
):
    """PRD §3.5: "A duration of exactly zero means the call was never answered — the record moves to `NOT_CONNECTED`, `ended_at` is stamped, `total_charge_cents` is zero, and, importantly, no ledger entry is appended at all."

    Design: Corner/state_machines/call_end_with_zero_duration_is_not_connected_and_charges_nothing
    """
    env = setup_call_ready_account()
    account, inmate, recipient = env["account"], env["inmate"], env["recipient"]

    call = connect_call(account, inmate, recipient, call_type="LOCAL")
    ended = validate_success(api.end_call(call["id"], 0, facility_staff_headers))
    assert ended["status"] == "NOT_CONNECTED"
    assert ended["total_charge_cents"] == 0

    account_after = get_account(account["id"])
    assert account_after["balance_cents"] == 1000

    rows = get_ledger(account["id"])
    assert [(r["type"], r["amount_cents"]) for r in rows] == [
        ("DEPOSIT", 1025),
        ("DEPOSIT_FEE", -25),
    ], "no CALL_CHARGE entry may exist for a zero-duration call"


def test_complaint_resolve_from_filed_returns_invalid_state(
    api, compliance_officer_headers
):
    """PRD §3.9: "A `ComplianceOfficer` opens review, moving the complaint to `UNDER_REVIEW` and recording `reviewed_by_user_id`. Resolution requires a `resolution_note` — omitting it fails with `ERR_INVALID_REQUEST` — and stamps `resolved_at` as the complaint reaches `RESOLVED`."
    PRD §3.9: "A new complaint is `FILED`, with `filed_by_user_id` and `filed_by_role` captured from the request headers."

    Design: Corner/state_machines/complaint_resolve_from_filed_returns_invalid_state
    """
    env = setup_funded_account(deposit_amount=0)
    complaint = file_complaint(
        env["facility"],
        account=env["account"],
        category="FEE_DISCLOSURE",
        description="deposit fee was not disclosed",
    )
    assert complaint["status"] == "FILED"

    resp = api.resolve_complaint(
        complaint["id"], "too early", compliance_officer_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = validate_success(
        api.get_complaint(complaint["id"], compliance_officer_headers)
    )
    assert reread["status"] == "FILED"
    assert reread["resolved_at"] is None
    assert reread["filed_by_user_id"] == env["account"]["id"]
    assert reread["filed_by_role"] == "AccountHolder"
