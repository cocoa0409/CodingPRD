"""Offer expiry sweep and the waitlist promotion cascade (PRD §2.4, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_offer,
    create_nominee_at_round_1,
    create_offer,
    create_selected_nominee,
    create_waitlisted_nominee,
    decide,
    get_cohort,
    get_nominee,
    get_offer,
    make_nominee_headers,
    scholar_lifecycle,
    setup_cohort_foundation,
    setup_locked_cohort,
    submit_round_evals_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OFFICER = TEST_USERS["selection_officer_headers"]


def _waitlisted_with_triple(program, partner, name, triple):
    """Nominee driven to WAITLISTED with every round scored on `triple`."""
    nominee = create_nominee_at_round_1(program, partner, name)
    for round_number in (1, 2):
        submit_round_evals_pair(nominee["id"], round_number, triple, triple)
        decide(nominee["id"], "ADVANCE")
    submit_round_evals_pair(nominee["id"], 3, triple, triple)
    decide(nominee["id"], "WAITLIST")
    return get_nominee(nominee["id"])


def _offers_for_nominee(nominee_id):
    offers, _ = validate_paginated(
        api_client.list_offers(_ADMIN, params={"nominee_id": nominee_id})
    )
    return offers


class TestOfferExpiryBoundary:
    def test_offer_expiry_boundary_is_strictly_past_deadline(self, api):
        """PRD §2.4: "Every offer lives for fourteen days: at creation, its
        `expires_at` is set to its `created_at` plus 14 days."
        PRD §2.4: "Each offer still in `OFFERED` status whose `expires_at` is
        strictly earlier than the new now transitions to `EXPIRED`; an offer
        whose `expires_at` is exactly equal to the new now does not expire and
        remains acceptable at its deadline."
        PRD §3.5: "Acceptance requires the offer to still be `OFFERED` — an
        `OFFERED` offer whose deadline has passed is already `EXPIRED` via the
        clock sweep of Section 2.4."

        Design: Corner/calculations/offer_expiry_boundary_is_strictly_past_deadline
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        n1 = create_selected_nominee(ctx["program"], ctx["partner"], "Nom One")
        n2 = create_selected_nominee(ctx["program"], ctx["partner"], "Nom Two")
        o1 = create_offer(n1["id"], ctx["cohort"]["id"])
        o2 = create_offer(n2["id"], ctx["cohort"]["id"])
        assert o1["expires_at"].startswith("2026-09-15T00:00:00"), (
            f"created at the 2026-09-01 boot clock, expires 14 days out; got {o1['expires_at']}"
        )

        # Exactly at the deadline: the strict sweep has not fired.
        advance_clock("2026-09-15T00:00:00Z")
        accepted = validate_success(
            api.accept_offer(o1["id"], make_nominee_headers(n1["id"]))
        )
        assert accepted["status"] == "ACCEPTED", "acceptable at exactly its deadline"

        # One second past: o2 is sweep-expired and refuses acceptance.
        advance_clock("2026-09-15T00:00:01Z")
        assert get_offer(o2["id"])["status"] == "EXPIRED"
        late = api.accept_offer(o2["id"], make_nominee_headers(n2["id"]))
        validate_error(late, ApiErrorId.ERR_INVALID_STATE)


class TestClockSweepPromotion:
    def test_clock_sweep_expires_offers_and_promotes_waitlist(self, api):
        """PRD §2.4: "Every time the clock moves, an offer-expiry sweep runs
        against the new now. ... Per expired offer, the cohort's outstanding
        count drops by one and the waitlist promotion sweep runs for that
        cohort."
        PRD §3.5: "it picks the nominee ranked by `round_3_score` descending
        with ties broken by earlier nominee `created_at` — the `id` is never
        used in ranking or tie-breaking — moves that nominee from `WAITLISTED`
        to `SELECTED`, creates a fresh offer for the nominee and the triggering
        cohort in `OFFERED` status with `expires_at` set to now plus 14 days".

        Design: Corner/cross_cutting_layers/clock_sweep_expires_offers_and_promotes_waitlist
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        nominees = [
            create_selected_nominee(ctx["program"], ctx["partner"], f"Nom {i}")
            for i in (1, 2, 3)
        ]
        offers = [create_offer(n["id"], ctx["cohort"]["id"]) for n in nominees]
        w = create_waitlisted_nominee(ctx["program"], ctx["partner"], "Nom W")

        advance_clock("2026-09-20T00:00:00Z")

        for offer in offers:
            assert get_offer(offer["id"])["status"] == "EXPIRED", (
                "all three offers shared the 2026-09-15 deadline and expired"
            )
        assert get_nominee(w["id"])["status"] == "SELECTED", (
            "the promotion sweep seated the lone waitlisted nominee"
        )
        w_offers = _offers_for_nominee(w["id"])
        assert len(w_offers) == 1
        assert w_offers[0]["status"] == "OFFERED"
        assert w_offers[0]["expires_at"].startswith("2026-10-04T00:00:00"), (
            f"new now 2026-09-20 + 14 days; got {w_offers[0]['expires_at']}"
        )
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["offers_outstanding"] == 1, "only W's promoted offer remains"
        assert cohort["seats_committed"] == 0


class TestWaitlistPromotionOrder:
    def test_waitlist_promotion_rank_and_created_at_tiebreak(self, api):
        """PRD §3.5: "Otherwise the sweep repeats while `seats_remaining` is
        above zero and the pool is non-empty: it picks the nominee ranked by
        `round_3_score` descending with ties broken by earlier nominee
        `created_at` — the `id` is never used in ranking or tie-breaking".
        PRD §3.5: "The eligible pool is the set of nominees in `WAITLISTED`
        status whose `city_program_id` equals the cohort's and who hold no
        offer in `OFFERED` or `ACCEPTED` status in any cohort."

        Design: Corner/calculations/waitlist_promotion_rank_and_created_at_tiebreak
        """
        ctx = setup_locked_cohort()
        program, partner = ctx["program"], ctx["partner"]
        # W1 scores 820 (100,100,40 -> 4*100+3*100+3*40); W2 and W3 score 800.
        w1 = _waitlisted_with_triple(program, partner, "Nom W1", (100, 100, 40))
        w2 = _waitlisted_with_triple(program, partner, "Nom W2", (80, 80, 80))
        w3 = _waitlisted_with_triple(program, partner, "Nom W3", (80, 80, 80))
        assert get_nominee(w1["id"])["round_3_score"] == 820
        assert get_nominee(w2["id"])["round_3_score"] == 800
        assert get_nominee(w3["id"])["round_3_score"] == 800

        s1, s2 = ctx["scholars"][0], ctx["scholars"][1]

        # First opened seat: the highest round_3_score wins.
        scholar_lifecycle(s1["id"], to_enrollment_status="WITHDRAWN")
        assert get_nominee(w1["id"])["status"] == "SELECTED"
        assert get_nominee(w2["id"])["status"] == "WAITLISTED"
        assert get_nominee(w3["id"])["status"] == "WAITLISTED"

        # Second opened seat: the 800-tie breaks by nominee.created_at ASC.
        scholar_lifecycle(s2["id"], to_enrollment_status="WITHDRAWN")
        assert get_nominee(w2["id"])["status"] == "SELECTED", (
            "W2 was created before W3 and wins the tie"
        )
        assert get_nominee(w3["id"])["status"] == "WAITLISTED"

        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["seats_committed"] == 1
        assert cohort["offers_outstanding"] == 2, (
            "two revocations, two promotions, one seat each"
        )


class TestScholarWithdrawalCascade:
    def _setup_locked_with_waitlisted(self):
        ctx = setup_locked_cohort()
        w = create_waitlisted_nominee(ctx["program"], ctx["partner"], "Nom W")
        return ctx, w

    def test_withdrawal_revokes_offer_and_reverts_cohort(self, api):
        """PRD §3.7: "`PRE_COLLEGIATE` → `WITHDRAWN`, by the scholar themself
        or a `ProgramAdmin`, or by the system at the matriculation training
        gate: the scholar's accepted offer becomes `REVOKED`, the cohort's
        `seats_committed` falls by one, and the lock-revert-plus-promotion
        cascade of Section 3.5 runs when the cohort is still `LOCKED`".

        Design: Difficulty/transitive_cascade/scholar_withdrawal_cascade_to_waitlist_promotion
        """
        ctx, w = self._setup_locked_with_waitlisted()
        offer, scholar = ctx["offers"][0], ctx["scholars"][0]
        scholar_lifecycle(scholar["id"], to_enrollment_status="WITHDRAWN")

        assert get_offer(offer["id"])["status"] == "REVOKED", (
            "link 1: the accepted offer revoked — caused by the withdrawal"
        )
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "FORMING", "link 3: the ledger drop reverted LOCKED"
        assert cohort["seats_committed"] == 2, "link 2: committed seats fell by one"

    def test_revert_fires_promotion_of_waitlisted_nominee(self, api):
        """PRD §3.5: "It triggers on any event that raises `seats_remaining`
        while the cohort is `FORMING`: an offer decline, an offer expiry, an
        offer revocation, or a lock revert."
        PRD §3.5: "moves that nominee from `WAITLISTED` to `SELECTED`, creates
        a fresh offer for the nominee and the triggering cohort in `OFFERED`
        status with `expires_at` set to now plus 14 days, and raises the
        cohort's `offers_outstanding` by one."

        Design: Difficulty/transitive_cascade/scholar_withdrawal_cascade_to_waitlist_promotion
        """
        ctx, w = self._setup_locked_with_waitlisted()
        scholar_lifecycle(ctx["scholars"][0]["id"], to_enrollment_status="WITHDRAWN")

        assert get_nominee(w["id"])["status"] == "SELECTED", (
            "link 4: the promotion sweep flipped WAITLISTED -> SELECTED"
        )
        w_offers = _offers_for_nominee(w["id"])
        assert len(w_offers) == 1
        promoted = w_offers[0]
        assert promoted["status"] == "OFFERED"
        assert promoted["cohort_id"] == ctx["cohort"]["id"], (
            "the fresh offer belongs to the triggering cohort"
        )
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["offers_outstanding"] == 1, (
            "exactly one promotion because only one seat reopened"
        )
