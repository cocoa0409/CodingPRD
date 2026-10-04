"""Decline/expiry release cascades, waitlist promotion, and conserved pool
invariants — PRD §3.6, §3.7, §3.8.
"""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    assert_pool_ledger_consistent,
    decline_award,
    find_award,
    get_agreement,
    get_award,
    list_cycle_awards,
    list_notifications,
    setup_matching_run,
)

PA = TEST_USERS["program_admin_headers"]

_CASC_SPECS = [
    {"full_name": "F One", "parent_sponsor": True, "scores": (37, 37, 38),
     "confirming_selection_index": 212},  # SI 224
    {"full_name": "F Two", "parent_sponsor": True, "scores": (37, 37, 37),
     "confirming_selection_index": 208},  # SI 222
]
_INV_SPECS = _CASC_SPECS + [
    {"full_name": "F Three", "parent_sponsor": True, "scores": (37, 37, 36),
     "confirming_selection_index": 208},  # SI 220
]
_LIVE = {"OFFERED", "ACCEPTED", "ENROLLED", "RENEWED"}


def _casc_ctx():
    return setup_matching_run(
        student_specs=_CASC_SPECS,
        agreement_overrides={
            "award_amount_cents": 250000,
            "max_awards": 2,
            "pool_total_cents": 250000,  # capacity exactly 1
        },
    )


def test_corporate_decline_promotes_next_ranked_finalist(api):
    """PRD §3.8: "decline moves the recipient `OFFERED` → `DECLINED`, expiry
    moves the recipient `OFFERED` → `EXPIRED`, and in both cases the award's
    `funding_status` goes to `RELEASED_BACK`"; "Link two re-evaluates the
    freed pool's capacity, flipping an `EXHAUSTED` agreement or institution
    back to `ACTIVE` when capacity returns"; "Link three runs waitlist
    promotion for that pool (§3.7), creating the next eligible finalist's
    `OFFERED` award when one exists."
    
    Design: Difficulty/transitive_cascade/corporate_decline_cascade_reoffers_waitlist
    """
    ctx = _casc_ctx()
    f1, f2 = ctx["students"]
    aw1 = find_award(f1["id"], ctx["cycle"]["id"])
    assert aw1["recipient_status"] == "OFFERED"  # SI 224 beat 222 for the seat
    assert find_award(f2["id"], ctx["cycle"]["id"]) is None  # waitlisted

    declined = decline_award(aw1["id"], f1["id"])
    assert declined["recipient_status"] == "DECLINED"
    assert declined["funding_status"] == "RELEASED_BACK"

    promoted = find_award(f2["id"], ctx["cycle"]["id"])
    assert promoted["recipient_status"] == "OFFERED"
    assert promoted["category"] == "CORPORATE_SPONSORED"
    assert promoted["amount_cents"] == 250000
    assert promoted["selection_index_snapshot"] == 222
    agreement = get_agreement(ctx["agreement"]["id"])
    # F1's release then F2's re-commit: committed returns to 250000.
    assert agreement["pool_committed_cents"] == 250000
    assert agreement["status"] == "EXHAUSTED"


def test_corporate_decline_supersedes_old_and_queues_new_notifications(api):
    """PRD §3.8: "Link four queues the promoted award's own `AWARD_OFFER` and
    `PUBLIC_ANNOUNCEMENT` notifications, `EMBARGOED`. Meanwhile the
    declined-or-expired award's own unreleased `AWARD_OFFER` and
    `PUBLIC_ANNOUNCEMENT` notifications flip `EMBARGOED` → `SUPERSEDED`." PRD
    §3.7: a promotion "queues its own `AWARD_OFFER` and `PUBLIC_ANNOUNCEMENT`
    notifications under the cycle's embargo values."
    
    Design: Difficulty/transitive_cascade/corporate_decline_cascade_reoffers_waitlist
    """
    ctx = _casc_ctx()
    f1, f2 = ctx["students"]
    aw1 = find_award(f1["id"], ctx["cycle"]["id"])
    decline_award(aw1["id"], f1["id"])

    f1_notes = list_notifications(f1["id"])
    assert [n["sequence_number"] for n in f1_notes] == [1, 2, 3, 4]
    assert [n["status"] for n in f1_notes] == [
        "EMBARGOED", "EMBARGOED", "SUPERSEDED", "SUPERSEDED",
    ]
    f2_notes = list_notifications(f2["id"])
    assert [n["sequence_number"] for n in f2_notes] == [1, 2, 3, 4]
    assert [n["notice_type"] for n in f2_notes] == [
        "SEMIFINALIST_NOTICE", "FINALIST_NOTICE", "AWARD_OFFER", "PUBLIC_ANNOUNCEMENT",
    ]
    assert all(n["status"] == "EMBARGOED" for n in f2_notes)
    by_type = {n["notice_type"]: n for n in f2_notes}
    assert by_type["AWARD_OFFER"]["embargo_until"] == TEST_DEFAULTS["AWARD_EMBARGO_UNTIL"]
    assert by_type["PUBLIC_ANNOUNCEMENT"]["embargo_until"] == (
        TEST_DEFAULTS["PUBLIC_EMBARGO_UNTIL"]
    )


def test_pool_offer_fully_reserves_pool(api):
    """PRD §3.7: "Every grant debits its pool at offer time:
    `pool_committed_cents` grows by the award's `amount_cents` — a
    reservation, not yet a payment."
    
    Design: Difficulty/compensating_invariant/sponsor_pool_offer_decline_reoffer_conserves_committed
    """
    ctx = setup_matching_run(
        student_specs=_INV_SPECS,
        agreement_overrides={
            "award_amount_cents": 250000,
            "max_awards": 2,
            "pool_total_cents": 500000,  # capacity 2: F1 + F2 offered, F3 waits
        },
    )
    assert ctx["matching_result"]["corporate_granted"] == 2
    assert find_award(ctx["students"][2]["id"], ctx["cycle"]["id"]) is None
    pre = get_agreement(ctx["agreement"]["id"])
    assert pre["pool_committed_cents"] == 500000
    assert pre["pool_paid_cents"] == 0
    assert pre["pool_available_reserved_cents"] == 0
    assert pre["status"] == "EXHAUSTED"
    assert_pool_ledger_consistent(pre)


def test_pool_decline_reoffer_conserves_committed(api):
    """PRD §3.6: "Both kinds of funding pool keep the same double ledger,
    recomputed on every mutation of the pool's awards or disbursements" with
    "pool_available_reserved_cents` is `pool_total_cents` minus
    `pool_committed_cents` minus `pool_paid_cents`"; PRD §3.8: the decline
    cascade releases the reservation and "Link three runs waitlist promotion
    for that pool (§3.7), creating the next eligible finalist's `OFFERED`
    award when one exists."
    
    Design: Difficulty/compensating_invariant/sponsor_pool_offer_decline_reoffer_conserves_committed
    """
    ctx = setup_matching_run(
        student_specs=_INV_SPECS,
        agreement_overrides={
            "award_amount_cents": 250000,
            "max_awards": 2,
            "pool_total_cents": 500000,
        },
    )
    f1, _f2, f3 = ctx["students"]
    aw1 = find_award(f1["id"], ctx["cycle"]["id"])
    decline_award(aw1["id"], f1["id"])

    post = get_agreement(ctx["agreement"]["id"])
    # The -250000 release and the +250000 re-commit cancel exactly.
    assert post["pool_committed_cents"] == 500000
    assert post["pool_paid_cents"] == 0
    assert post["pool_available_reserved_cents"] == 0
    assert post["pool_total_cents"] == 500000
    assert_pool_ledger_consistent(post)

    assert get_award(aw1["id"])["recipient_status"] == "DECLINED"
    promoted = find_award(f3["id"], ctx["cycle"]["id"])
    assert promoted["recipient_status"] == "OFFERED"
    assert promoted["amount_cents"] == 250000


def test_national_slots_filled_at_matching(api):
    """PRD §3.7: "The national bucket grants to the top candidates, at most the
    cycle's `national_award_slots` of them".
    
    Design: Difficulty/compensating_invariant/national_slot_recycle_conserves_active_count
    """
    ctx = setup_matching_run(
        student_specs=[
            {"scores": (37, 37, 38), "confirming_selection_index": 212},
            {"scores": (37, 37, 37), "confirming_selection_index": 210},
            {"scores": (37, 37, 36), "confirming_selection_index": 208},
        ],
        cycle_overrides={"national_award_slots": 2},
    )
    assert ctx["matching_result"]["national_granted"] == 2
    nationals = list_cycle_awards(ctx["cycle"]["id"], category="NATIONAL_SINGLE")
    live = [a for a in nationals if a["recipient_status"] in _LIVE]
    assert len(live) == 2 == ctx["cycle"]["national_award_slots"]
    assert find_award(ctx["students"][2]["id"], ctx["cycle"]["id"]) is None


def test_national_slot_recycle_conserves_active_count(api):
    """PRD §3.7: promotion runs for "the cycle's national slot count, for which
    capacity returns when the live national count (awards in `OFFERED`,
    `ACCEPTED`, `ENROLLED`, or `RENEWED`) drops below `national_award_slots`",
    and grants "exactly one award per iteration to the top-ranked candidate
    when capacity allows".
    
    Design: Difficulty/compensating_invariant/national_slot_recycle_conserves_active_count
    """
    ctx = setup_matching_run(
        student_specs=[
            {"scores": (37, 37, 38), "confirming_selection_index": 212},
            {"scores": (37, 37, 37), "confirming_selection_index": 210},
            {"scores": (37, 37, 36), "confirming_selection_index": 208},
        ],
        cycle_overrides={"national_award_slots": 2},
    )
    f1, _f2, f3 = ctx["students"]
    aw1 = find_award(f1["id"], ctx["cycle"]["id"])
    decline_award(aw1["id"], f1["id"])

    promoted = find_award(f3["id"], ctx["cycle"]["id"])
    assert promoted["category"] == "NATIONAL_SINGLE"
    assert promoted["amount_cents"] == 250000  # cycle national_award_amount_cents
    assert promoted["recipient_status"] == "OFFERED"

    nationals = list_cycle_awards(ctx["cycle"]["id"], category="NATIONAL_SINGLE")
    assert len(nationals) == 3  # the DECLINED row persists as history
    live = [a for a in nationals if a["recipient_status"] in _LIVE]
    assert len(live) == 2 == ctx["cycle"]["national_award_slots"]


def test_waitlist_empty_pool_stays_active_noop(api):
    """PRD §3.7: "an empty candidate set is a no-op and the pool simply stays
    `ACTIVE`". PRD §3.6: "it flips back `EXHAUSTED` → `ACTIVE` when a decline,
    expiry, or lapse release raises `pool_available_reserved_cents` to at
    least `award_amount_cents` while the granted count is below `max_awards`".
    The second student holds a live NATIONAL award so the §3.8 completion
    bubble-up (which fires only when "no award of the cycle remains live" and
    flips agreements to `CLOSED`) cannot mask the §3.7 no-op; the corporate
    waitlist itself is empty because the only corporate-eligible student was
    the decliner.

    Design: Corner/cross_cutting_layers/waitlist_empty_pool_stays_active_noop
    """
    ctx = setup_matching_run(
        student_specs=[
            {"full_name": "Corp Kid", "parent_sponsor": True,
             "scores": (37, 37, 36), "confirming_selection_index": 208},  # SI 220
            {"full_name": "Nat Star", "parent_sponsor": False,
             "scores": (37, 37, 38), "confirming_selection_index": 212},  # SI 224
        ],
        cycle_overrides={"national_award_slots": 1},
        agreement_overrides={
            "award_amount_cents": 250000,
            "max_awards": 2,
            "pool_total_cents": 250000,  # capacity 1 -> EXHAUSTED after the grant
        },
    )
    s1, s2 = ctx["students"]
    award = find_award(s1["id"], ctx["cycle"]["id"])
    assert award["category"] == "CORPORATE_SPONSORED"
    national = find_award(s2["id"], ctx["cycle"]["id"])
    assert national["category"] == "NATIONAL_SINGLE"
    assert national["recipient_status"] == "OFFERED"
    assert get_agreement(ctx["agreement"]["id"])["status"] == "EXHAUSTED"

    before_ids = {a["id"] for a in list_cycle_awards(ctx["cycle"]["id"])}
    decline_award(award["id"], s1["id"])
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["status"] == "ACTIVE"
    assert agreement["pool_committed_cents"] == 0
    assert agreement["pool_available_reserved_cents"] == 250000
    # No corporate-eligible candidate remained: nothing was promoted, no error
    # surfaced, and the live national award is untouched by the cascade.
    awards = list_cycle_awards(ctx["cycle"]["id"])
    assert {a["id"] for a in awards} == before_ids
    assert get_award(award["id"])["recipient_status"] == "DECLINED"
    assert get_award(national["id"])["recipient_status"] == "OFFERED"
