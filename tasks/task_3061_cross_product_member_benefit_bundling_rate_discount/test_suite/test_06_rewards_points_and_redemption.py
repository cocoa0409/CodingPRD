"""Rewards points: earning, redemption, reversal and the pinned rounding order."""
from test_helpers import (
    TEST_USERS,
    assert_ledger_entry,
    fetch_loan,
    fetch_member,
    list_ledger_entries,
    make_member_headers,
    register_member,
    rewards_adjust_payload,
    setup_member_with_loan_only,
    setup_rewards_member,
    validate_error,
    validate_success,
)


def test_each_redemption_floors_its_own_points_before_anything_is_summed(api):
    """PRD §3.8: "The rounding order is pinned and is not negotiable: the floor
    is applied per entry, at the moment that entry is created, and the per-entry
    reductions are then summed. The platform never sums all consumed points
    first and floors once. Two redemptions of 1,150 points each therefore yield
    11 cents plus 11 cents — 22 cents in total — and never the 23 cents that a
    single floor over the combined 2,300 points would give."

    Design: Difficulty/combinatorial_formula/principal_redemption_nested_floor_per_entry_then_sum
    """
    setup = setup_rewards_member(3000, principal_cents=500000, base_apr_bps=1100)
    member_id, loan_id = setup["member"]["id"], setup["loan"]["id"]

    first = validate_success(api.redeem_principal(
        member_id,
        {"loan_account_id": loan_id, "points": 1150, "source_event_code": "REDEEM_A"},
        make_member_headers(member_id),
    ), expected_status=201)
    second = validate_success(api.redeem_principal(
        member_id,
        {"loan_account_id": loan_id, "points": 1150, "source_event_code": "REDEEM_B"},
        make_member_headers(member_id),
    ), expected_status=201)

    assert_ledger_entry(first)
    assert first["entry_type"] == "REDEEM_PRINCIPAL"
    assert first["points_delta"] == -1150
    assert first["principal_reduction_cents"] == 11, "1150 floors to 11 at 100 points per cent"
    assert second["principal_reduction_cents"] == 11, "each entry floors independently"

    loan = fetch_loan(loan_id)
    assert loan["principal_cents"] == 499978, (
        "500000 - 11 - 11; the sum-then-floor reading would leave 499977"
    )


def test_the_destroyed_remainder_points_are_not_carried_forward(api):
    """PRD §3.8: "Any remainder points are destroyed by the floor rather than
    carried forward."
    PRD §2.6: "`rewards_points_balance` is the non-negative sum of the point
    deltas of the member's posted rewards ledger entries."

    Design: Difficulty/combinatorial_formula/principal_redemption_nested_floor_per_entry_then_sum
    """
    setup = setup_rewards_member(3000, principal_cents=500000)
    member_id, loan_id = setup["member"]["id"], setup["loan"]["id"]

    for code in ("REDEEM_A", "REDEEM_B"):
        validate_success(api.redeem_principal(
            member_id, {"loan_account_id": loan_id, "points": 1150, "source_event_code": code},
            make_member_headers(member_id),
        ), expected_status=201)

    member = fetch_member(member_id)
    assert member["rewards_points_balance"] == 700, (
        "3000 - 1150 - 1150; the 50 remainder points per entry are destroyed"
    )
    balance = validate_success(api.get_rewards_balance(member_id, TEST_USERS["platform_admin_headers"]))
    assert balance["points_balance"] == 700


def test_a_redemption_with_no_points_at_all_is_refused_with_the_fiscal_error(api):
    """PRD §3.8: "a redemption whose points exceed the member's posted balance
    is refused with `ERR_INSUFFICIENT_POINTS`; a redemption outside the
    permitted per-entry bounds of at least 1,000 points and at most 500,000
    points is refused with `ERR_REDEMPTION_LIMIT_EXCEEDED`".

    Design: Difficulty/boundary_precision_check/redemption_points_floor_boundary_and_the_empty_entry_set
    """
    setup = setup_member_with_loan_only(principal_cents=400000, base_apr_bps=1000)
    member_id, loan_id = setup["member"]["id"], setup["loan"]["id"]
    assert fetch_member(member_id)["rewards_points_balance"] == 0

    resp = api.redeem_principal(
        member_id, {"loan_account_id": loan_id, "points": 1000, "source_event_code": "REDEEM_EMPTY"},
        make_member_headers(member_id),
    )
    validate_error(resp, "ERR_INSUFFICIENT_POINTS", expected_status=422)

    loan = fetch_loan(loan_id)
    assert loan["principal_cents"] == 400000, "a refused redemption must not move the principal"


def test_an_empty_posted_entry_set_reports_a_zero_balance_and_no_synthesized_row(api):
    """PRD §2.6: "`rewards_points_balance` is the non-negative sum of the point
    deltas of the member's posted rewards ledger entries."

    Design: Difficulty/boundary_precision_check/redemption_points_floor_boundary_and_the_empty_entry_set
    """
    setup = setup_member_with_loan_only(principal_cents=400000)
    member_id = setup["member"]["id"]

    member = fetch_member(member_id)
    assert member["rewards_points_balance"] == 0, "the sum over an empty set is zero"

    entries = list_ledger_entries(member_id=member_id)
    assert entries == [], "no zero-amount entry is synthesized for a member who never earned a point"
    balance = validate_success(api.get_rewards_balance(member_id, TEST_USERS["platform_admin_headers"]))
    assert balance["points_balance"] == 0
    assert balance["posted_entry_count"] == 0


def test_a_redemption_paired_with_its_reversal_restores_the_principal_exactly(api):
    """PRD §3.8: "When the reversed entry was a principal redemption, the linked
    loan's principal is increased by the original's `principal_reduction_cents`,
    and the loan is repriced with its stack and effective rate recomputed and
    its timestamp refreshed."

    Design: Difficulty/compensating_invariant/redemptions_plus_reversals_restore_principal_exactly
    """
    setup = setup_rewards_member(5000, principal_cents=600000, base_apr_bps=1050)
    member_id, loan_id = setup["member"]["id"], setup["loan"]["id"]
    before = fetch_loan(loan_id)["principal_cents"]

    entry = validate_success(api.redeem_principal(
        member_id, {"loan_account_id": loan_id, "points": 2500, "source_event_code": "REDEEM_X"},
        make_member_headers(member_id),
    ), expected_status=201)
    assert entry["principal_reduction_cents"] == 25
    assert fetch_loan(loan_id)["principal_cents"] == before - 25

    validate_success(api.reverse_ledger_entry(entry["id"], TEST_USERS["benefits_admin_headers"]))

    reversed_entry = validate_success(api.get_ledger_entry(entry["id"],
                                                           TEST_USERS["benefits_admin_headers"]))
    assert reversed_entry["entry_status"] == "REVERSED"
    assert reversed_entry["reversed_by_entry_id"] is not None, (
        "the compensating entry is linked back to the original"
    )
    assert fetch_loan(loan_id)["principal_cents"] == before, (
        "a redemption paired with its compensating reversal leaves the principal byte-identical"
    )


def test_reversing_the_same_redemption_twice_cannot_drive_the_invariant_negative(api):
    """PRD §2.9: "6. The target resource is in a state that permits the
    requested transition, else `ERR_INVALID_STATE`; this applies to every
    state-transition operation."

    Design: Difficulty/compensating_invariant/redemptions_plus_reversals_restore_principal_exactly
    """
    setup = setup_rewards_member(5000, principal_cents=600000)
    member_id, loan_id = setup["member"]["id"], setup["loan"]["id"]
    before = fetch_loan(loan_id)["principal_cents"]

    entry = validate_success(api.redeem_principal(
        member_id, {"loan_account_id": loan_id, "points": 2500, "source_event_code": "REDEEM_X2"},
        make_member_headers(member_id),
    ), expected_status=201)
    validate_success(api.reverse_ledger_entry(entry["id"], TEST_USERS["benefits_admin_headers"]))
    assert fetch_loan(loan_id)["principal_cents"] == before

    resp = api.reverse_ledger_entry(entry["id"], TEST_USERS["benefits_admin_headers"])
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
    assert fetch_loan(loan_id)["principal_cents"] == before, (
        "repeating the compensation must not move the conserved quantity"
    )


def test_reversing_repeatedly_cannot_double_compensate_the_points_balance(api):
    """PRD §3.8: "A benefits operator reverses a posted earning or principal
    redemption, which is admitted only when the entry is posted and its type is
    an earning or a principal redemption."

    Design: Corner/state_machines/reversing_a_rewards_entry_twice_returns_invalid_state_on_the_second
    """
    member = register_member(member_number="M-S-011", email="noor.c@x.com")
    entry = validate_success(api.adjust_rewards(
        member["id"], rewards_adjust_payload(400, source_event_code="MANUAL"),
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)

    validate_success(api.reverse_ledger_entry(entry["id"], TEST_USERS["benefits_admin_headers"]))
    assert fetch_member(member["id"])["rewards_points_balance"] == 0

    resp = api.reverse_ledger_entry(entry["id"], TEST_USERS["benefits_admin_headers"])
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    assert fetch_member(member["id"])["rewards_points_balance"] == 0, (
        "the balance is compensated exactly once and never driven negative"
    )
    rows = list_ledger_entries(member_id=member["id"])
    assert len(rows) == 2, "the original entry plus its single REVERSE companion"
    assert {row["entry_type"] for row in rows} == {"ADJUST", "REVERSE"}


def test_reversing_the_career_session_earning_restores_the_points_balance(api):
    """PRD §3.9: "completing a career-coaching session appends a rewards entry
    earning 250 points with a career-session-completed provenance tag and
    recomputes the member's posted balance."
    PRD §3.8: "The reversal moves the original entry to `REVERSED` and appends a
    compensating reversal entry whose point delta is the negation of the
    original's, linked back to the original; the member's posted balance is
    recomputed."

    Design: Difficulty/compensating_invariant/rewards_point_balance_is_exactly_restored_by_a_reversal
    """
    set_clock_result = validate_success(api.set_current_utc(
        {"current_utc": "2026-09-01T00:00:00Z"}, TEST_USERS["platform_admin_headers"]))
    assert set_clock_result["current_utc"] == "2026-09-01T00:00:00Z"

    member = register_member(member_number="M-3061-018", email="rex.c@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "CAREER", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    validate_success(api.create_entitlement(
        member["id"],
        {"source_holding_id": holding["id"], "benefit_code": "CAREER_COACHING_CREDIT",
         "value_bps": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    session = validate_success(api.book_coaching_session(
        {"member_id": member["id"], "coach_ref": "COACH-DELTA", "session_kind": "CAREER_COACHING",
         "starts_at": "2026-09-14T14:00:00Z", "ends_at": "2026-09-14T15:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    validate_success(api.confirm_coaching_session(session["id"], make_member_headers(member["id"])))

    assert fetch_member(member["id"])["rewards_points_balance"] == 0, "before completion"

    api.set_current_utc({"current_utc": "2026-09-14T15:01:00Z"}, TEST_USERS["platform_admin_headers"])
    validate_success(api.complete_coaching_session(session["id"], TEST_USERS["platform_admin_headers"]))

    earned = fetch_member(member["id"])["rewards_points_balance"]
    assert earned == 250, "completing a career-coaching session earns 250 points"

    entries = list_ledger_entries(member_id=member["id"], entry_type="EARN")
    assert len(entries) == 1
    assert_ledger_entry(entries[0])
    assert entries[0]["points_delta"] == 250
    assert entries[0]["source_event_code"] == "CAREER_SESSION_COMPLETED"

    validate_success(api.reverse_ledger_entry(entries[0]["id"], TEST_USERS["benefits_admin_headers"]))
    assert fetch_member(member["id"])["rewards_points_balance"] == 0, (
        "the compensating reversal restores the balance exactly"
    )


def test_the_point_balance_equals_the_sum_of_posted_entry_deltas_after_compensation(api):
    """PRD §2.6: "`rewards_points_balance` is the non-negative sum of the point
    deltas of the member's posted rewards ledger entries."

    Design: Difficulty/compensating_invariant/rewards_point_balance_is_exactly_restored_by_a_reversal
    """
    set_clock_result = validate_success(api.set_current_utc(
        {"current_utc": "2026-09-01T00:00:00Z"}, TEST_USERS["platform_admin_headers"]))
    assert set_clock_result["previous_utc"] is not None

    member = register_member(member_number="M-3061-018B", email="rex.c.b@x.com")
    holding = api.create_holding(
        {"member_id": member["id"], "product_line": "CAREER", "balance_cents": 0},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    validate_success(api.create_entitlement(
        member["id"],
        {"source_holding_id": holding["id"], "benefit_code": "CAREER_COACHING_CREDIT",
         "value_bps": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    session = validate_success(api.book_coaching_session(
        {"member_id": member["id"], "coach_ref": "COACH-DELTA-B", "session_kind": "CAREER_COACHING",
         "starts_at": "2026-09-14T14:00:00Z", "ends_at": "2026-09-14T15:00:00Z",
         "capacity_total": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    validate_success(api.confirm_coaching_session(session["id"], make_member_headers(member["id"])))
    api.set_current_utc({"current_utc": "2026-09-14T15:01:00Z"}, TEST_USERS["platform_admin_headers"])
    validate_success(api.complete_coaching_session(session["id"], TEST_USERS["platform_admin_headers"]))
    entry = list_ledger_entries(member_id=member["id"], entry_type="EARN")[0]

    validate_success(api.reverse_ledger_entry(entry["id"], TEST_USERS["benefits_admin_headers"]))

    rows = list_ledger_entries(member_id=member["id"])
    posted = [
        row
        for row in rows
        if row["entry_status"] == "POSTED" and row["entry_type"] != "REVERSE"
    ]
    assert sum(row["points_delta"] for row in posted) == fetch_member(member["id"])["rewards_points_balance"], (
        "the stored balance equals the sum over the member's posted point movements "
        "exactly; the compensating REVERSE row is an audit companion, not a movement"
    )
    assert fetch_member(member["id"])["rewards_points_balance"] >= 0, "the invariant cannot go negative"