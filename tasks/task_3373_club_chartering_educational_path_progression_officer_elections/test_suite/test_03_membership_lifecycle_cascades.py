"""Membership status, the dues dimension and the cascades a lapse triggers."""
from test_helpers import (
    ApiErrorId,
    bulk_enroll_paid,
    bulk_members_payload,
    close_dues_cycle,
    create_club_contest,
    create_entry,
    create_organizing_club,
    create_path,
    enroll_membership,
    get_club,
    get_contest,
    get_entry,
    get_member,
    get_membership,
    get_path,
    list_memberships_for_club,
    list_paths_for_membership,
    make_member_headers,
    membership_version,
    numbered_members,
    refund_dues,
    renew_dues,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    FIRST_CYCLE_CLOSE_AT,
    SECOND_CYCLE_OPENED_AT,
)


def _setup_member_paid_then_lapsed() -> tuple:
    """Organizing club + one member who paid cycle 0 and was lapsed by two closes."""
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Grace Hopper", email="grace@example.org")
    renew_dues(membership["id"], membership["member_id"])
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)
    return club, membership


def test_membership_status_and_dues_walk_through_two_closes(api, whq_headers):
    """PRD §3.2: "Step one sweeps the closing cycle. Every membership whose
    `dues_paid_through_cycle` is below the club's `dues_cycle_index` — evaluated
    before the index moves — is resolved: an invoice still in `ISSUED` becomes
    `OVERDUE`, and a membership still in `ACTIVE` becomes `LAPSED`."
    PRD §3.2: "The next invoice is then issued to every membership still in status
    `PENDING` or `ACTIVE`: a membership whose `dues_status` was `PAID` or `VOID` moves
    to `ISSUED`, and the applicable quote total for the new cycle is stored in its
    `quoted_total_cents`."

    Design: Difficulty/non_linear_state_machine/membership_status_lapse_and_renewal_cycle
    """
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Grace Hopper", email="grace@example.org")

    first = renew_dues(membership["id"], membership["member_id"])
    assert first["status"] == "ACTIVE"
    assert first["dues_status"] == "PAID"
    assert first["dues_paid_through_cycle"] == 0

    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    after_first_close = get_membership(membership["id"])
    assert after_first_close["status"] == "ACTIVE", "a membership paid for the closing cycle is not swept"
    assert after_first_close["dues_status"] == "ISSUED", "the cycle-1 invoice is issued"

    close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)
    after_second_close = get_membership(membership["id"])
    assert after_second_close["status"] == "LAPSED", "the unpaid cycle-1 invoice lapses the membership"
    assert after_second_close["dues_status"] == "OVERDUE"


def test_reinstatement_renewal_returns_lapsed_membership_to_active(api, whq_headers):
    """PRD §3.3: "When a payment lands, the invoice moves from `ISSUED` or `OVERDUE` to `PAID`, `dues_paid_through_cycle` is set to the club's current `dues_cycle_index`, and the consecutive-payment counter is updated: `consecutive_cycles_paid` increments by one when the previous `dues_paid_through_cycle` equalled the club's `dues_cycle_index` minus one, and otherwise resets to 1."
    PRD §3.3: "The membership's `status` moves from `PENDING` or `LAPSED` to `ACTIVE`, and if it became `ACTIVE` in this operation each of its suspended education paths is lifted back to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/membership_status_lapse_and_renewal_cycle
    """
    club, membership = _setup_member_paid_then_lapsed()
    assert get_membership(membership["id"])["status"] == "LAPSED", "setup: the member is lapsed"

    revived = renew_dues(membership["id"], membership["member_id"])
    assert revived["status"] == "ACTIVE"
    assert revived["dues_status"] == "PAID"
    assert revived["dues_paid_through_cycle"] == 2, "the reinstatement pays the club's current cycle"


def test_close_cycle_lapse_marks_invoice_overdue_and_membership_lapsed(api, whq_headers):
    """PRD §3.2: "Step one sweeps the closing cycle. Every membership whose
    `dues_paid_through_cycle` is below the club's `dues_cycle_index` — evaluated
    before the index moves — is resolved: an invoice still in `ISSUED` becomes
    `OVERDUE`, and a membership still in `ACTIVE` becomes `LAPSED`."

    Design: Difficulty/transitive_cascade/close_cycle_lapse_suspends_path_and_disqualifies_entry_depth_five
    """
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org", pay_dues=True)
    create_path(membership["id"], membership["member_id"])
    contest = create_club_contest(club["id"], membership["member_id"])
    create_entry(contest["id"], membership["member_id"], club["id"])
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)

    close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)

    after = get_membership(membership["id"])
    assert after["dues_status"] == "OVERDUE", "hop 1: the unpaid cycle-1 invoice goes overdue"
    assert after["status"] == "LAPSED", "hop 2: the overdue invoice lapses the membership"


def test_close_cycle_lapse_suspends_path_and_disqualifies_entry(api, whq_headers):
    """PRD §2.11: "A membership that lapses suspends that member's education paths,
    disqualifies the contest entries those paths were supporting, and vacates the
    member's officer terms."
    PRD §3.8: "A `DISQUALIFIED` entry stops counting toward the contest's `entry_count` and `judged_entry_count`, both of which are recomputed, and the entry's `version` increments."

    Design: Difficulty/transitive_cascade/close_cycle_lapse_suspends_path_and_disqualifies_entry_depth_five
    """
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org", pay_dues=True)
    path = create_path(membership["id"], membership["member_id"])
    contest = create_club_contest(club["id"], membership["member_id"])
    entry = create_entry(contest["id"], membership["member_id"], club["id"])
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)

    close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)

    assert get_path(path["id"])["status"] == "SUSPENDED", "hop 3: the lapsed membership suspends the path"
    assert get_entry(entry["id"])["status"] == "DISQUALIFIED", "hop 4: the entry loses its eligibility"
    assert get_contest(contest["id"])["entry_count"] == 0, "hop 5: the contest recounts its live entries"


def test_reinstatement_reactivates_the_suspended_path(api, whq_headers):
    """PRD §3.3: "The membership's `status` moves from `PENDING` or `LAPSED` to
    `ACTIVE`, and if it became `ACTIVE` in this operation each of its suspended
    education paths is lifted back to `ACTIVE`."

    Design: Difficulty/transitive_cascade/renewal_reactivates_path_and_recounts_roster
    """
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org", pay_dues=True)
    path = create_path(membership["id"], membership["member_id"])
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)
    assert get_path(path["id"])["status"] == "SUSPENDED", "setup: the lapse suspended the path"

    renewed = renew_dues(membership["id"], membership["member_id"])
    assert renewed["dues_status"] == "PAID", "hop 1"
    assert renewed["status"] == "ACTIVE" and renewed["dues_paid_through_cycle"] == 2, "hop 2"
    assert get_path(path["id"])["status"] == "ACTIVE", "hop 3: the reactivated membership unsuspends the path"


def test_reinstatement_recounts_the_club_paid_roster(api, whq_headers):
    """PRD §2.6: "`paid_member_count` (memberships whose `dues_paid_through_cycle` is
    at least the club's `dues_cycle_index`)".

    Design: Difficulty/transitive_cascade/renewal_reactivates_path_and_recounts_roster
    """
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org", pay_dues=True)
    create_path(membership["id"], membership["member_id"])
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)
    assert get_club(club["id"])["paid_member_count"] == 0, "the lapsed member no longer counts"

    renew_dues(membership["id"], membership["member_id"])
    assert get_club(club["id"])["paid_member_count"] == 1, "hop 4: the renewal restores the paid roster"


def test_refund_returns_the_paid_roster_to_its_prior_value(api, whq_headers):
    """PRD §3.3: "Reversing a payment is a `ClubOfficer` act and requires the invoice
    to be `PAID`. The refund moves `dues_status` to `VOID`, restores
    `dues_paid_through_cycle` and `consecutive_cycles_paid` to the values they held
    before the refunded payment, recomputes the club's `paid_member_count` and
    `good_standing_score`, and increments the membership's `version`."

    Design: Difficulty/compensating_invariant/dues_payment_and_refund_conserve_paid_roster
    """
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org")
    assert get_club(club["id"])["paid_member_count"] == 0, "before the pair"

    renew_dues(membership["id"], membership["member_id"])
    assert get_club(club["id"])["paid_member_count"] == 1, "after the renewal"

    refund_dues(membership["id"], membership["id"])
    assert get_club(club["id"])["paid_member_count"] == 0, "the refund restores the pre-pair count"


def test_refund_restores_the_cycle_pointer_and_voids_the_invoice(api, whq_headers):
    """PRD §3.3: "The refund moves `dues_status` to `VOID`, restores `dues_paid_through_cycle` and `consecutive_cycles_paid` to the values they held before the refunded payment, recomputes the club's `paid_member_count` and `good_standing_score`, and increments the membership's `version`."

    Design: Difficulty/compensating_invariant/dues_payment_and_refund_conserve_paid_roster
    """
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org")

    paid = renew_dues(membership["id"], membership["member_id"])
    assert paid["dues_paid_through_cycle"] == 0

    refunded = refund_dues(membership["id"], membership["id"])
    assert refunded["dues_paid_through_cycle"] == -1, "the cycle pointer reverts to its pre-payment value"
    assert refunded["dues_status"] == "VOID"


def test_lapsed_membership_cannot_enroll_in_a_path(api, whq_headers):
    """PRD §3.3: "A membership whose dues are not paid through the club's current
    cycle is barred from the progression and participation surfaces — creating an
    education path, logging a project completion, taking a meeting role and entering a
    contest all require an `ACTIVE` membership paid through the current cycle, and are
    refused with `ERR_MEMBERSHIP_NOT_ACTIVE` when that does not hold."

    Design: Corner/errors/membership_not_active_blocks_path_enrollment
    """
    club, membership = _setup_member_paid_then_lapsed()
    assert get_membership(membership["id"])["status"] == "LAPSED"

    response = api.create_education_path(
        {
            "membership_id": membership["id"],
            "path_code": "DYNAMIC_LEADERSHIP",
            "expected_membership_version": membership_version(membership["id"]),
        },
        make_member_headers(membership["member_id"]),
    )
    validate_error(response, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)
    assert list_paths_for_membership(membership["id"]) == [], "no path may be created"


def test_bulk_enrollment_recomputes_club_counters(api, whq_headers):
    """PRD §3.3: "Afterwards the club's `total_member_count`, `paid_member_count`,
    `new_member_count_this_cycle` and `good_standing_score` are recomputed."
    PRD §2.6: "Posture is never supplied by a caller and is never flipped by an
    ordinary in-cycle mutation."

    Design: Corner/entities/club_derived_counters_after_bulk_enrollment
    """
    club = create_organizing_club()
    response = api.bulk_create_memberships(
        bulk_members_payload(club["id"], numbered_members(20), pay_dues_immediately=True),
        whq_headers,
    )
    result = validate_success(response, 201)
    assert result["created_count"] == 20
    assert result["failed_count"] == 0

    updated = get_club(club["id"])
    assert updated["paid_member_count"] == 20
    assert updated["total_member_count"] == 20
    assert updated["new_member_count_this_cycle"] == 20, "every first paid cycle equals cycle index 0"
    assert updated["good_standing_score"] == 36, "30 dues points + 6 points from 3 recognition points"
    assert updated["good_standing"] == "GOOD", "posture only moves at close-cycle"


def test_membership_list_pages_and_filters_by_club(api, whq_headers):
    """PRD §2.3: "`total_count` is the number of items matching the filter before
    paging, and `has_more` reports whether further items remain beyond the returned
    window."

    Design: Corner/entities/membership_list_reports_pagination_metadata
    """
    club = create_organizing_club()
    bulk_enroll_paid(club["id"], 3, prefix="p")

    response = api.list_memberships(whq_headers, {"club_id": club["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(response)

    assert len(data) == 2, "the page honours limit=2"
    assert meta["total_count"] == 3, "total_count counts matches before paging"
    assert meta["has_more"] is True
    assert all(item["club_id"] == club["id"] for item in data), "the club filter must hold"


def test_membership_create_without_join_date_is_invalid(api, whq_headers):
    """PRD §2.10: "A request whose payload is structurally invalid — a required field
    missing, a field of the wrong type, an enum value outside its declared set, or a
    judge score outside the range 0 through 100 inclusive — is rejected with
    `ERR_INVALID_REQUEST` before any business rule is consulted."

    Design: Corner/entities/membership_create_missing_required_field_rejected
    """
    club = create_organizing_club()

    response = api.create_membership({"club_id": club["id"], "first_time_member": True}, whq_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert list_memberships_for_club(club["id"]) == [], "no membership row may exist afterwards"


def test_bulk_enrollment_skips_malformed_rows_and_commits_the_rest(api, whq_headers):
    """PRD §3.3: "It is best-effort rather than all-or-nothing: one membership is
    created per entry of `members` in array order, reusing a member row when the
    entry's email already exists, and a row whose email is malformed is skipped and
    counted in `failed_count` while the remaining rows are still committed."

    Design: Corner/endpoints/bulk_enrollment_partial_failure
    """
    club = create_organizing_club()
    response = api.bulk_create_memberships(
        {
            "club_id": club["id"],
            "pay_dues_immediately": True,
            "members": [
                {"full_name": "M1", "email": "m1@example.org"},
                {"full_name": "Broken Row", "email": "not-an-email"},
                {"full_name": "M3", "email": "m3@example.org"},
            ],
        },
        whq_headers,
    )
    result = validate_success(response, 201)
    assert result["created_count"] == 2
    assert result["failed_count"] == 1

    listed = list_memberships_for_club(club["id"])
    assert len(listed) == 2, "the two valid rows are committed"
    emails = {get_member(item["member_id"])["email"] for item in listed}
    assert emails == {"m1@example.org", "m3@example.org"}, "the malformed row must not be stored"
