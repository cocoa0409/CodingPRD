"""Return-rate snapshots and the inquiry pipeline — PRD §3.7, §3.8.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_return_rate_snapshot,
    assert_snapshot_breach_flags,
    create_active_participant,
    create_approved_originator,
    create_payment_entry,
    create_settlement_window,
    create_snapshot,
    create_transaction_code,
    find_inquiry_cases,
    is_unauth_breach,
    make_participant_officer_headers,
    originate_entries,
    respond_payload,
    return_entry,
    run_settlement,
    set_clock,
    setup_auto_opened_inquiry,
    setup_origination_stack,
    validate_create_success,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_return_rate_settlement_vs_origination_basis_divergence(api, admin_headers):
    """PRD §3.7: "On the **origination basis**, recorded on the same snapshot
    for enforcement severity review, `origination_forward_count` counts entries
    created in the period, and `origination_unauth_count` /
    `origination_admin_count` count only returns created in the period whose
    underlying entry was also created in the period — so a late-arriving return
    of an old entry moves the settlement basis but not the origination basis."
    PRD §3.7: "`unauth_breach` is true when `forward_count` is positive and
    unauthorized returns exceed one-tenth of it (one hundred times
    `unauth_return_count` is strictly greater than ten times `forward_count`)"
    PRD §3.7: "Computing a snapshot is also the trigger for supervisory
    follow-up: for each breached class — `UNAUTHORIZED` when `unauth_breach` is
    set, `ADMINISTRATIVE` when `admin_breach` is set, `OVERALL` when
    `overall_breach` is set — the network opens an **InquiryCase** unless one
    already exists for that participant, period, and class in `OPENED` or
    `RESPONSE_SUBMITTED` status."

    Design: Difficulty/dual_variant_calc/return_rate_settlement_vs_origination_basis_divergence
    """
    stack = setup_origination_stack(clock_iso="2026-09-01T09:00:00Z")
    participant = stack["participant"]
    receiver = stack["receiver"]
    code = stack["transaction_code"]
    window = stack["window"]
    originator = stack["originator"]

    entry_a = create_payment_entry(originator, code, amount_cents=50000)
    run_settlement(window["id"], at_iso="2026-09-01T18:00:00Z")

    originate_entries(originator, code, [10000, 10000, 10000, 10000],
                      at_iso="2026-10-05T09:00:00Z")
    run_settlement(window["id"], at_iso="2026-10-05T18:00:00Z")

    # One late-arriving October return of the September entry.
    entry_a_settled = validate_success(api.get_payment_entry(entry_a["id"], admin_headers))
    return_entry(
        entry_a_settled, receiver, "UNAUTHORIZED_DEBIT", at_iso="2026-10-06T10:00:00Z"
    )

    snap = validate_create_success(
        api.create_return_rate_snapshot(
            {"participant_id": participant["id"], "period": "2026-10"}, admin_headers
        )
    )
    assert_return_rate_snapshot(snap)
    assert snap["forward_count"] == 4
    assert snap["origination_forward_count"] == 4
    assert snap["unauth_return_count"] == 1
    assert snap["origination_unauth_count"] == 0
    assert snap["settlement_unauth_rate"] == pytest.approx(0.25)
    assert snap["origination_unauth_rate"] == pytest.approx(0.0)
    assert snap["unauth_breach"] is True
    # The identical data on the origination basis would not breach.
    assert is_unauth_breach(
        snap["origination_forward_count"], snap["origination_unauth_count"]
    ) is False

    inquiries = find_inquiry_cases(
        participant_id=participant["id"], snapshot_id=snap["id"]
    )
    assert len(inquiries) == 1
    assert inquiries[0]["return_class"] == "UNAUTHORIZED"
    assert inquiries[0]["status"] == "OPENED"


def test_unauthorized_rate_exactly_at_threshold_does_not_breach(api, admin_headers):
    """PRD §3.7: "Three breach flags are computed by exact integer
    cross-multiplication, strictly greater-than, so a rate sitting exactly on
    the threshold does not breach: `unauth_breach` is true when `forward_count`
    is positive and unauthorized returns exceed one-tenth of it (one hundred
    times `unauth_return_count` is strictly greater than ten times
    `forward_count`)"
    PRD §3.7: "Computing a snapshot is also the trigger for supervisory
    follow-up: for each breached class — `UNAUTHORIZED` when `unauth_breach` is
    set, `ADMINISTRATIVE` when `admin_breach` is set, `OVERALL` when
    `overall_breach` is set — the network opens an **InquiryCase** unless one
    already exists for that participant, period, and class in `OPENED` or
    `RESPONSE_SUBMITTED` status."

    Design: Difficulty/boundary_precision_check/unauthorized_rate_exactly_at_threshold_does_not_breach
    """
    set_clock("2026-09-01T09:00:00Z")
    p1 = create_active_participant(participant_type="ODFI")
    p2 = create_active_participant(participant_type="ODFI")
    p3 = create_active_participant(participant_type="RDFI")
    code = create_transaction_code()
    window = create_settlement_window()
    o1 = create_approved_originator(p1)
    o2 = create_approved_originator(p2)

    p1_entries = originate_entries(o1, code, [1000] * 10)
    p2_entries = originate_entries(o2, code, [1000] * 10)
    run_settlement(window["id"], at_iso="2026-09-01T18:00:00Z")

    set_clock("2026-09-02T10:00:00Z")
    return_entry(p1_entries[0], p3, "UNAUTHORIZED_DEBIT")
    return_entry(p2_entries[0], p3, "UNAUTHORIZED_DEBIT")
    return_entry(p2_entries[1], p3, "UNAUTHORIZED_DEBIT")

    snap1 = validate_create_success(
        api.create_return_rate_snapshot(
            {"participant_id": p1["id"], "period": "2026-09"}, admin_headers
        )
    )
    assert_return_rate_snapshot(snap1)
    assert_snapshot_breach_flags(snap1)
    assert snap1["forward_count"] == 10
    assert snap1["unauth_return_count"] == 1
    assert snap1["settlement_unauth_rate"] == pytest.approx(0.1)
    assert snap1["unauth_breach"] is False  # 1*100 == 10*10: exact threshold
    assert is_unauth_breach(10, 1) is False
    assert find_inquiry_cases(participant_id=p1["id"], status="OPENED") == []

    snap2 = validate_create_success(
        api.create_return_rate_snapshot(
            {"participant_id": p2["id"], "period": "2026-09"}, admin_headers
        )
    )
    assert_return_rate_snapshot(snap2)
    assert_snapshot_breach_flags(snap2)
    assert snap2["forward_count"] == 10
    assert snap2["unauth_return_count"] == 2
    assert snap2["settlement_unauth_rate"] == pytest.approx(0.2)
    assert snap2["unauth_breach"] is True  # 2*100 > 10*10

    p2_inquiries = find_inquiry_cases(participant_id=p2["id"], status="OPENED")
    assert len(p2_inquiries) == 1
    assert p2_inquiries[0]["return_class"] == "UNAUTHORIZED"


def test_snapshot_zero_forward_yields_zero_rates_no_breach(api, admin_headers):
    """PRD §3.7: "Five rates are derived, each rounded half-up to four decimal
    places and each reading 0.0 when its denominator is zero"
    PRD §3.7: "`unauth_breach` is true when `forward_count` is positive and
    unauthorized returns exceed one-tenth of it (one hundred times
    `unauth_return_count` is strictly greater than ten times `forward_count`)"

    Design: Corner/calculations/snapshot_zero_forward_yields_zero_rates_no_breach
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="ODFI")

    snap = create_snapshot(participant["id"], "2026-09")
    assert_return_rate_snapshot(snap)
    assert_snapshot_breach_flags(snap)
    assert snap["forward_count"] == 0
    assert snap["unauth_return_count"] == 0
    assert snap["settlement_unauth_rate"] == pytest.approx(0.0)
    assert snap["settlement_admin_rate"] == pytest.approx(0.0)
    assert snap["settlement_overall_rate"] == pytest.approx(0.0)
    assert snap["unauth_breach"] is False
    assert snap["admin_breach"] is False
    assert snap["overall_breach"] is False
    assert snap["status"] == "COMPUTED"

    assert find_inquiry_cases(participant_id=participant["id"]) == []


def test_snapshot_counts_only_own_participant_entries(api, admin_headers):
    """PRD §3.7: "On the **settlement basis** — the official threshold basis —
    the denominator `forward_count` counts the participant's entries whose
    `settled_date` falls in the period, and the numerators
    `unauth_return_count`, `admin_return_count`, and `other_return_count` count
    the `ReturnRecord`s created in the period of each class whose underlying
    entry belongs to the participant, regardless of when that entry was
    originated."
    PRD §3.6: "The run settles every entry assigned to that window that is
    still in `ORIGINATED` status, and the response reports how many settled as
    `settled_count` together with their identifiers as `settled_entry_ids`."

    Design: Corner/calculations/snapshot_counts_only_own_participant_entries
    """
    set_clock("2026-09-01T09:00:00Z")
    p1 = create_active_participant(participant_type="ODFI")
    p2 = create_active_participant(participant_type="ODFI")
    code = create_transaction_code()
    window = create_settlement_window()
    o1 = create_approved_originator(p1)
    o2 = create_approved_originator(p2)

    originate_entries(o1, code, [1000, 1000])
    originate_entries(o2, code, [1000, 1000, 1000])
    run = run_settlement(window["id"], at_iso="2026-09-01T18:00:00Z")
    assert run["settled_count"] == 5

    snap = create_snapshot(p1["id"], "2026-09")
    assert snap["forward_count"] == 2


def test_snapshot_duplicate_period_rejected(api, admin_headers):
    """PRD §3.7: "one snapshot exists per participant per period, and a
    duplicate request is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/snapshot_duplicate_period_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="ODFI")
    create_snapshot(participant["id"], "2026-09")

    duplicate = api.create_return_rate_snapshot(
        {"participant_id": participant["id"], "period": "2026-09"}, admin_headers
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    snapshots, meta = validate_paginated(
        api.list_return_rate_snapshots(
            admin_headers, params={"participant_id": participant["id"]}
        )
    )
    assert len(snapshots) == 1 and meta["total_count"] == 1


def test_inquiry_resolve_before_response_rejected(api, admin_headers):
    """PRD §3.8: "A `PlatformAdmin` then closes the matter without sanction by
    moving it from `RESPONSE_SUBMITTED` to `RESOLVED` — a terminal state — or
    escalates it into national enforcement."
    PRD §2.8: "State-machine legality of the requested transition — the target
    entity must be in a state that permits it (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/inquiry_resolve_before_response_rejected
    """
    built = setup_auto_opened_inquiry()
    inquiry = built["inquiry"]
    assert inquiry["status"] == "OPENED"
    assert inquiry["return_class"] == "UNAUTHORIZED"

    resp = api.resolve_inquiry(inquiry["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_inquiry_case(inquiry["id"], admin_headers))
    assert after["status"] == "OPENED"


def test_inquiry_escalate_before_deadline_rejected(api, admin_headers):
    """PRD §3.8: "Escalation out of `OPENED` is allowed only once the response
    deadline has actually passed — the logical time must be strictly later than
    `response_deadline`, otherwise `ERR_RESPONSE_DEADLINE_NOT_PASSED`;
    escalation out of `RESPONSE_SUBMITTED` carries no such wait."

    Design: Corner/state_machines/inquiry_escalate_before_deadline_rejected
    """
    built = setup_auto_opened_inquiry()
    inquiry = built["inquiry"]
    participant = built["stack"]["participant"]

    resp = api.escalate_inquiry(inquiry["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_RESPONSE_DEADLINE_NOT_PASSED)

    after = validate_success(api.get_inquiry_case(inquiry["id"], admin_headers))
    assert after["status"] == "OPENED"

    actions, meta = validate_paginated(
        api.list_enforcement_actions(
            admin_headers, params={"participant_id": participant["id"]}
        )
    )
    assert actions == [] and meta["total_count"] == 0


def test_inquiry_respond_by_foreign_participant_forbidden(api, admin_headers):
    """PRD §3.8: "The institution answers through its `ParticipantOfficer`,
    whose `X-User-ID` must equal the inquiry's `participant_id` (otherwise
    `ERR_FORBIDDEN`), submitting `response_text` that moves the inquiry from
    `OPENED` to `RESPONSE_SUBMITTED`."

    Design: Corner/rbac/inquiry_respond_by_foreign_participant_forbidden
    """
    built = setup_auto_opened_inquiry()
    inquiry = built["inquiry"]
    foreign = built["stack"]["receiver"]

    resp = api.respond_inquiry(
        inquiry["id"],
        respond_payload("A foreign participant trying to answer"),
        make_participant_officer_headers(foreign["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = validate_success(api.get_inquiry_case(inquiry["id"], admin_headers))
    assert after["status"] == "OPENED"
    assert after["response_text"] is None
