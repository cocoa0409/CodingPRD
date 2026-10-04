"""Non-linear state machines: negotiation cycle and slot hold/release cycle.

Design: Difficulty/non_linear_state_machine
"""
from test_helpers import (
    TEST_USERS, create_festival_payload, create_offer_payload,
    get_success_data, setup_festival, setup_film, setup_film_with_offer,
    setup_premiere_slot, setup_territory, validate_success,
)

ACQ = TEST_USERS["acq_exec_headers"]
PROG = TEST_USERS["festival_prog_headers"]


class TestOfferNegotiationCycle:
    def test_offer_negotiation_cycle_open_countered_open(self, api):
        """PRD §3.2: "Countering is a cyclic negotiation step. An
        `AcquisitionExec` counters an `OPEN` offer by submitting a new payload
        of the same shape as offer creation. The original offer transitions
        `OPEN → COUNTERED`, and a fresh offer is minted on the same film in
        `OPEN` status with `round_number` equal to the prior round plus one."
        PRD §3.3: "if, after the transition, no `OPEN` offer remains on the
        film and no `EXECUTED` or `IN_RELEASE` deal exists, the film's
        `acquisition_status` collapses `UNDER_NEGOTIATION → SHOPPING`".

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_open_countered_open
        """
        film, offer_1 = setup_film_with_offer()
        film_id = film["id"]

        offer_2 = validate_success(api.counter_offer(
            film_id, offer_1["id"],
            create_offer_payload(upfront_price_cents=6_500_000), ACQ,
        ), expected_status=201)
        offer_3 = validate_success(api.counter_offer(
            film_id, offer_2["id"],
            create_offer_payload(
                upfront_price_cents=7_500_000, backend_participation_pct=0.12,
            ),
            ACQ,
        ), expected_status=201)

        # Withdraw the last OPEN offer
        withdrawn = validate_success(api.withdraw_offer(film_id, offer_3["id"], ACQ))
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["round_number"] == 3

        # Verify prior offers' terminal states and round numbers
        o1_now = get_success_data(api.get_offer(film_id, offer_1["id"], ACQ))
        o2_now = get_success_data(api.get_offer(film_id, offer_2["id"], ACQ))
        assert o1_now["status"] == "COUNTERED"
        assert o1_now["round_number"] == 1
        assert o2_now["status"] == "COUNTERED"
        assert o2_now["round_number"] == 2

        # Film reverts to SHOPPING — the negotiation-collapse loop
        film_now = get_success_data(api.get_film(film_id, ACQ))
        assert film_now["acquisition_status"] == "SHOPPING"

    def test_offer_cycle_film_stays_under_negotiation_across_counters(self, api):
        """PRD §3.2: "If the film was in `SHOPPING` when the first `OPEN`
        offer is created, the film transitions `SHOPPING → UNDER_NEGOTIATION`"
        — and countering keeps the film in UNDER_NEGOTIATION across the
        cyclic loop.
        PRD §3.2: "The `round_number` is set to 1 for the first offer ever
        made on the film, or to one more than the maximum existing
        `round_number` on that film otherwise."

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_open_countered_open
        """
        film, offer_1 = setup_film_with_offer()
        film_id = film["id"]

        # First offer: film moves SHOPPING -> UNDER_NEGOTIATION
        film_after_offer = get_success_data(api.get_film(film_id, ACQ))
        assert film_after_offer["acquisition_status"] == "UNDER_NEGOTIATION"

        offer_2 = validate_success(api.counter_offer(
            film_id, offer_1["id"], create_offer_payload(), ACQ,
        ), expected_status=201)
        film_mid = get_success_data(api.get_film(film_id, ACQ))
        assert film_mid["acquisition_status"] == "UNDER_NEGOTIATION"
        assert offer_2["status"] == "OPEN"
        assert offer_2["round_number"] == 2


class TestPremiereSlotHoldReleaseCycle:
    def test_premiere_slot_hold_release_hold_cycle(self, api):
        """PRD §3.4: "A hold may be released (or may lapse on hold timeout),
        transitioning the slot `HELD → OPEN`, clearing the `film_id`, and
        resetting `cachet_score` to 0."
        PRD §3.4: "A programmer then holds the slot for a specific film by
        supplying the `film_id` in the hold payload. The slot transitions
        `OPEN → HELD`, the `film_id` is set, and a provisional `cachet_score`
        is computed."

        Design: Difficulty/non_linear_state_machine/premiere_slot_hold_release_hold_cycle
        """
        festival = setup_festival()
        f1 = setup_film(title="F1", director_name="D1")
        f2 = setup_film(title="F2", director_name="D2",
                        genre="COMEDY", runtime_minutes=95)
        slot = setup_premiere_slot(festival["id"])

        held = validate_success(api.hold_premiere_slot(
            festival["id"], slot["id"], {"film_id": f1["id"]}, PROG,
        ))
        assert held["status"] == "HELD"
        assert held["film_id"] == f1["id"]
        assert held["cachet_score"] == 175  # (100+40)*1.25

        released = validate_success(api.release_hold_premiere_slot(
            festival["id"], slot["id"], PROG,
        ))
        assert released["status"] == "OPEN"
        assert released["film_id"] is None
        assert released["cachet_score"] == 0

        reheld = validate_success(api.hold_premiere_slot(
            festival["id"], slot["id"], {"film_id": f2["id"]}, PROG,
        ))
        assert reheld["status"] == "HELD"
        assert reheld["film_id"] == f2["id"]
        assert reheld["cachet_score"] == 175

    def test_premiere_slot_release_hold_resets_and_recomputes_cachet(self, api):
        """PRD §3.4: "A hold may be released (or may lapse on hold timeout),
        transitioning the slot `HELD → OPEN`, clearing the `film_id`, and
        resetting `cachet_score` to 0."
        PRD §3.4: "a delay of at most 12 hours multiplies by 1.25"

        Design: Difficulty/non_linear_state_machine/premiere_slot_hold_release_hold_cycle
        """
        festival = setup_festival(prestige_tier="B_LIST")
        f1 = setup_film(title="F1", director_name="D1")
        slot = setup_premiere_slot(festival["id"], section="PREMIERES")

        held = validate_success(api.hold_premiere_slot(
            festival["id"], slot["id"], {"film_id": f1["id"]}, PROG,
        ))
        # (60 + 25) * 1.25 = 106.25 -> 106
        assert held["cachet_score"] == 106

        released = validate_success(api.release_hold_premiere_slot(
            festival["id"], slot["id"], PROG,
        ))
        assert released["cachet_score"] == 0
        assert released["film_id"] is None

        # The slot is OPEN again and can be held by any film (same one here);
        # the provisional cachet recomputes to the same deterministic value.
        reheld = validate_success(api.hold_premiere_slot(
            festival["id"], slot["id"], {"film_id": f1["id"]}, PROG,
        ))
        assert reheld["status"] == "HELD"
        assert reheld["cachet_score"] == 106
