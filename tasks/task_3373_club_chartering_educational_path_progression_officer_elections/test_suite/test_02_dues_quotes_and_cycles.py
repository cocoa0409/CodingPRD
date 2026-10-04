"""Dues quotes: the two variants, the pinned rounding order and the proration cutoff."""
from test_helpers import (
    ApiErrorId,
    close_dues_cycle,
    create_organizing_club,
    enroll_membership,
    get_membership,
    make_member_headers,
    renew_dues,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    FIRST_CYCLE_CLOSE_AT,
    JOIN_DATE,
    SECOND_CYCLE_OPENED_AT,
)


def test_renewal_quote_for_first_time_member_of_2999_cent_club(api, whq_headers):
    """PRD §3.2: "The renewal quote applies while the membership's status is
    `PENDING` or `ACTIVE`, and its reinstatement line is 0."

    Design: Difficulty/dual_variant_calc/dues_quote_renewal_vs_reinstatement_divergence
    """
    club = create_organizing_club(club_dues_cents=2999)
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org")

    assert membership["quoted_total_cents"] == 10062, (
        "renewal quote: round(4837.5) + round(3223.925) + 2000 new-member + 0 + 0"
    )
    renewed = renew_dues(membership["id"], membership["member_id"])
    assert renewed["quoted_total_cents"] == 10062, "the paid renewal charges the renewal variant"
    assert renewed["dues_status"] == "PAID"
    assert renewed["status"] == "ACTIVE"
    assert renewed["dues_paid_through_cycle"] == 0


def test_reinstatement_quote_for_lapsed_member_of_2999_cent_club(api, whq_headers):
    """PRD §3.2: "The reinstatement quote applies while the membership's status is
    `LAPSED`; its reinstatement line is 1000 cents, and its new-member line is forced
    to 0 even when `first_time_member` is true and `dues_paid_through_cycle` is minus
    one."

    Design: Difficulty/dual_variant_calc/dues_quote_renewal_vs_reinstatement_divergence
    """
    club = create_organizing_club(club_dues_cents=2999)
    membership = enroll_membership(
        club["id"], full_name="Grace Hopper", email="grace@example.org", pay_dues=True
    )
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)

    lapsed = get_membership(membership["id"])
    assert lapsed["status"] == "LAPSED" and lapsed["dues_status"] == "OVERDUE", (
        "setup: two closes must leave the unpaid membership lapsed"
    )

    renewed = renew_dues(membership["id"], membership["member_id"])
    assert renewed["quoted_total_cents"] == 9515, (
        "reinstatement quote: 4838 + 3224 + 0 + 1000 reinstatement + 453 late"
    )
    assert renewed["status"] == "ACTIVE"
    assert renewed["dues_paid_through_cycle"] == 2


def test_quote_rounds_each_line_before_summing(api, whq_headers):
    """PRD §3.2: "Each of the five lines — international, club, new-member,
    reinstatement and late — is individually rounded to two decimal places, that is
    to the nearest cent, using round half up, and only then are the five rounded
    values summed."
    PRD §3.2: "for a club whose `club_dues_cents` is 2999 and a first-time member who
    has never paid, the pinned per-line order yields 10062 cents, while summing the
    unrounded lines and rounding once yields 10061."

    Design: Difficulty/combinatorial_formula/dues_quote_round_per_line_beats_sum_then_round
    """
    club = create_organizing_club(club_dues_cents=2999)
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org")

    assert membership["quoted_total_cents"] == 10062, (
        "round(4837.5) + round(3223.925) + 2000 + 0 + 0 = 4838 + 3224 + 2000"
    )


def test_quote_is_not_the_sum_then_round_result(api, whq_headers):
    """PRD §2.9: "Rounding once at the end, after summing unrounded lines, produces a
    different and incorrect total; the difference is small but real, and it is
    observable."
    PRD §3.2: "for a club whose `club_dues_cents` is 2999 and a first-time member who
    has never paid, the pinned per-line order yields 10062 cents, while summing the
    unrounded lines and rounding once yields 10061."

    Design: Difficulty/combinatorial_formula/dues_quote_round_per_line_beats_sum_then_round
    """
    club = create_organizing_club(club_dues_cents=2999)
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org")
    renewed = renew_dues(membership["id"], membership["member_id"])

    assert renewed["quoted_total_cents"] != 10061, (
        "10061 is the sum-then-round result and must not be charged"
    )
    assert renewed["dues_status"] == "PAID"
    assert renewed["dues_paid_through_cycle"] == 0


def test_quote_at_ninety_days_is_not_prorated(api, whq_headers):
    """PRD §2.5: "a membership whose `join_date` falls at or after `cycle_opened_at`
    plus 91 days has joined in the second half of the cycle and is prorated
    accordingly."

    Design: Difficulty/boundary_precision_check/dues_proration_cutoff_exactly_ninety_one_days
    """
    club = create_organizing_club(club_dues_cents=3000)
    early = enroll_membership(
        club["id"],
        full_name="Early Bird",
        email="early@example.org",
        join_date="2026-11-30T00:00:00Z",
    )

    assert early["quoted_total_cents"] == 10063, (
        "90 days after the cycle opened is before the midpoint: 4838 + 3225 + 2000"
    )
    renewed = renew_dues(early["id"], early["member_id"])
    assert renewed["quoted_total_cents"] == 10063


def test_quote_at_ninety_one_days_is_prorated(api, whq_headers):
    """PRD §3.2: "When the membership's `join_date` falls on or after the moment the
    cycle opened plus 91 days, both of those lines are halved, because the member is
    joining for the second half of the cycle only."

    Design: Difficulty/boundary_precision_check/dues_proration_cutoff_exactly_ninety_one_days
    """
    club = create_organizing_club(club_dues_cents=3000)
    early = enroll_membership(
        club["id"],
        full_name="Early Bird",
        email="early@example.org",
        join_date="2026-11-30T00:00:00Z",
    )
    late = enroll_membership(
        club["id"],
        full_name="Late Bird",
        email="late@example.org",
        join_date="2026-12-01T00:00:00Z",
    )

    assert late["quoted_total_cents"] == 6032, (
        "exactly 91 days after the cycle opened: round(2418.75) + round(1612.5) + 2000"
    )
    renewed_late = renew_dues(late["id"], late["member_id"])
    assert renewed_late["quoted_total_cents"] == 6032
    assert early["quoted_total_cents"] - renewed_late["quoted_total_cents"] == 4031, (
        "the two quotes must differ by exactly 4031 cents"
    )


def test_second_renewal_of_a_paid_membership_is_refused(api, whq_headers):
    """PRD §3.3: "An invoice that is already `PAID` or has been `VOID`ed is refused with `ERR_DUES_ALREADY_PAID`; a club whose `charter_status` is `SUSPENDED` refuses the renewal with `ERR_CLUB_NOT_CHARTERED`; and a club whose `charter_status` is `REVOKED` refuses it with `ERR_CLUB_REVOKED`."

    Design: Corner/errors/dues_already_paid_on_second_renewal
    """
    club = create_organizing_club()
    membership = enroll_membership(club["id"], pay_dues=True)
    assert membership["dues_status"] == "PAID" and membership["dues_paid_through_cycle"] == 0

    response = api.renew_dues(membership["id"], make_member_headers(membership["member_id"]))
    validate_error(response, ApiErrorId.ERR_DUES_ALREADY_PAID)

    after = get_membership(membership["id"])
    assert after["dues_paid_through_cycle"] == 0, "the refused renewal must not move the cycle pointer"
    assert after["dues_status"] == "PAID"


def test_membership_create_response_carries_derived_dues_fields(api, whq_headers):
    """PRD §3.3: "Its `status` is `PENDING`, its `dues_status` is `ISSUED`, its
    `dues_paid_through_cycle` is minus one, its `consecutive_cycles_paid` is 0, its
    `officer_role` is `NONE`, and its `quoted_total_cents` holds the renewal quote
    computed for the cycle it is joining."

    Design: Corner/consistency_model/immediate_consistency_create_response_carries_derived_fields
    """
    club = create_organizing_club(club_dues_cents=3000)
    response = api.create_membership(
        {
            "club_id": club["id"],
            "full_name": "Ada Lovelace",
            "email": "ada@example.org",
            "join_date": JOIN_DATE,
            "first_time_member": True,
        },
        whq_headers,
    )
    membership = validate_success(response, 201)

    assert membership["status"] == "PENDING"
    assert membership["dues_status"] == "ISSUED"
    assert membership["dues_paid_through_cycle"] == -1
    assert membership["consecutive_cycles_paid"] == 0
    assert membership["officer_role"] == "NONE"
    assert membership["quoted_total_cents"] == 10063, (
        "the create response already carries the renewal quote for club dues 3000"
    )
