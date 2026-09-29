"""The offer negotiation loop: the counter/revise cycle and its round cap, the
order in which an accept reports offer state before agent roster authorization,
and the encumbrance and stage posture a withdrawal restores.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_offer_round
from test_helpers.factories import build_counter_payload, build_revise_payload
from test_helpers.test_users import (
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    TALENT_BUYER_HEADERS,
    make_talent_agent_headers,
)

AGENT_ASK_CENTS = 11_000_000
BUYER_OPENING_CENTS = 8_000_000
BUYER_REVISED_CENTS = 9_500_000
FOURTH_ROUND_ASK_CENTS = 12_000_000


def _sent_offer_at_opening_guarantee():
    """A sent offer whose standing guarantee is the buyer's opening figure."""
    return fixtures.setup_sent_offer(offered_guarantee_cents=BUYER_OPENING_CENTS)


def _agent_counters(scenario, proposed_guarantee_cents, note):
    payload = build_counter_payload(
        proposed_guarantee_cents,
        proposed_backend_split_pct=0.9000,
        proposed_breakeven_cents=6_000_000,
        note=note,
    )
    return api_client.counter_offer(
        scenario["offer"]["id"], payload, scenario["agent_headers"]
    )


def _buyer_revises(offer_id, offered_guarantee_cents, note):
    payload = build_revise_payload(
        fixtures.offer_version(offer_id),
        offered_guarantee_cents,
        backend_breakeven_cents=6_000_000,
        note=note,
    )
    return api_client.revise_offer(offer_id, payload, TALENT_BUYER_HEADERS)


class TestNegotiationCycle:
    """The two-actor loop between SENT and COUNTERED and the cap that ends it."""

    def test_buyer_revision_returns_offer_to_sent_with_revised_terms(self):
        """The agent's counter moves a sent offer to COUNTERED and the buyer's
        revision carries it back to SENT with the revised guarantee standing and
        the agent's ask cleared away.

        "the buyer can answer that counter with revised terms, taking it back from `COUNTERED` to `SENT`"

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_exhausts_round_cap
        """
        scenario = _sent_offer_at_opening_guarantee()
        countered = validate_success(
            _agent_counters(scenario, AGENT_ASK_CENTS, "Agent ask, round 2")
        )
        assert countered["status"] == "COUNTERED"
        assert countered["countered_guarantee_cents"] == AGENT_ASK_CENTS

        revised = validate_success(
            _buyer_revises(
                scenario["offer"]["id"], BUYER_REVISED_CENTS, "Buyer revise, round 3"
            )
        )
        assert revised["status"] == "SENT"
        assert revised["offered_guarantee_cents"] == BUYER_REVISED_CENTS
        assert revised["countered_guarantee_cents"] is None
        assert revised["round_count"] == 3

    def test_round_log_records_three_alternating_proposals_in_order(self):
        """Each send, counter and revision appends one immutable negotiation
        round, so the offer's round tally is exactly the number of logged rounds
        and each round carries the figure its own side proposed.

        "Every round ever proposed is appended to an immutable log, and the offer's `round_count` is simply the number of rows in that log"

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_exhausts_round_cap
        """
        scenario = _sent_offer_at_opening_guarantee()
        validate_success(
            _agent_counters(scenario, AGENT_ASK_CENTS, "Agent ask, round 2")
        )
        validate_success(
            _buyer_revises(
                scenario["offer"]["id"], BUYER_REVISED_CENTS, "Buyer revise, round 3"
            )
        )

        rounds, meta = validate_paginated(
            api_client.list_offer_rounds(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )
        assert meta["total_count"] == 3
        for record in rounds:
            assert_offer_round(record)
        assert [record["round_number"] for record in rounds] == [1, 2, 3]
        assert [record["proposed_by"] for record in rounds] == ["BUYER", "AGENT", "BUYER"]
        assert [record["proposed_guarantee_cents"] for record in rounds] == [
            BUYER_OPENING_CENTS,
            AGENT_ASK_CENTS,
            BUYER_REVISED_CENTS,
        ]

    def test_fourth_counter_is_refused_and_leaves_the_offer_in_sent(self):
        """Three rounds exhaust the negotiation whichever side proposed them, so
        the counter that would open a fourth round is refused and the offer is
        left standing exactly where the third round left it.

        "both further counters and further revisions are then refused with `ERR_NEGOTIATION_ROUND_LIMIT`"

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_exhausts_round_cap
        """
        scenario = _sent_offer_at_opening_guarantee()
        validate_success(
            _agent_counters(scenario, AGENT_ASK_CENTS, "Agent ask, round 2")
        )
        validate_success(
            _buyer_revises(
                scenario["offer"]["id"], BUYER_REVISED_CENTS, "Buyer revise, round 3"
            )
        )

        refused = _agent_counters(
            scenario, FOURTH_ROUND_ASK_CENTS, "Fourth round attempt - must be refused"
        )
        validate_error(refused, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT.value)

        offer = fixtures.get_offer(scenario["offer"]["id"])
        assert offer["status"] == "SENT"
        assert offer["round_count"] == 3


class TestAcceptRejectionOrdering:
    """A rival agent accepting a draft breaches two rules; only one is reported."""

    @staticmethod
    def _world_with_rival_agent():
        world = fixtures.setup_base_world()
        rival = fixtures.create_agent(
            user_id="agent-bexley",
            agency_name="Bexley Artists",
            contact_email="desk@bexley.example",
        )
        scenario = fixtures.setup_draft_offer(world)
        scenario["rival_agent"] = rival
        scenario["rival_headers"] = make_talent_agent_headers(rival["user_id"])
        return scenario

    def test_accept_on_a_draft_offer_by_a_rival_agent_reports_offer_state(self):
        """An accept is only declared from SENT, and the acting agent must be the
        artist's own. Both rules are broken at once here, and the service reports
        the offer-state failure because it is evaluated first.

        "The service evaluates candidate rejections in the following strict order, reporting the first that fires and evaluating no further"

        Design: Difficulty/priority_pair_validation_conflict/offer_state_outranks_agent_roster_authorization
        """
        scenario = self._world_with_rival_agent()
        assert scenario["offer"]["status"] == "DRAFT"

        refused = api_client.accept_offer(
            scenario["offer"]["id"], scenario["rival_headers"]
        )
        error = validate_error(refused, ApiErrorId.ERR_INVALID_OFFER_STATE.value)
        assert error["error_id"] != ApiErrorId.ERR_AGENT_NOT_AUTHORIZED_FOR_ARTIST.value

    def test_accept_on_a_sent_offer_by_a_rival_agent_reports_roster_authorization(self):
        """Once the offer reads SENT the state check passes and the roster breach
        that was already present is the failure that surfaces; nothing about the
        offer moves and no show booking is created for it.

        "a mismatch is refused with `ERR_AGENT_NOT_AUTHORIZED_FOR_ARTIST` (HTTP 403), because an agent may only counter, accept or decline for acts on its own roster"

        Design: Difficulty/priority_pair_validation_conflict/offer_state_outranks_agent_roster_authorization
        """
        scenario = self._world_with_rival_agent()
        sent = validate_success(
            api_client.send_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )
        assert sent["status"] == "SENT"

        refused = api_client.accept_offer(
            scenario["offer"]["id"], scenario["rival_headers"]
        )
        validate_error(refused, ApiErrorId.ERR_AGENT_NOT_AUTHORIZED_FOR_ARTIST.value)

        offer = fixtures.get_offer(scenario["offer"]["id"])
        assert offer["status"] == "SENT"
        assert offer["agreed_guarantee_cents"] is None

        bookings, meta = validate_paginated(
            api_client.list_show_bookings(
                FAIR_OPERATIONS_DIRECTOR_HEADERS, {"offer_id": scenario["offer"]["id"]}
            )
        )
        assert bookings == []
        assert meta["total_count"] == 0
        assert scenario["rival_agent"]["user_id"] == "agent-bexley"
        assert scenario["artist"]["agent_id"] == scenario["agent"]["id"]


class TestWithdrawalRestoresTheLedgers:
    """A send followed by a withdrawal is a round trip on money and on slots."""

    SENT_GUARANTEE_CENTS = 12_500_000

    @staticmethod
    def _world_with_single_slot_stage():
        """One stage whose soft cap is a single slot, so one hold saturates it."""
        return fixtures.setup_draft_offer(
            fixtures.setup_base_world(stage_overrides={"slot_soft_cap": 1})
        )

    def test_send_encumbers_the_guarantee_and_saturates_the_single_slot_stage(self):
        """Sending the offer takes the stage hold and the budget encumbrance, and
        because the stage's soft cap is a single slot the hold saturates it and
        removes it from the edition's tally of open stages.

        "The stage's `booking_posture` is then `SATURATED` whenever `held_show_count` is greater than or equal to `slot_soft_cap`, and `OPEN` otherwise."

        Design: Difficulty/compensating_invariant/withdraw_restores_committed_guarantee_and_stage_posture
        """
        scenario = self._world_with_single_slot_stage()
        edition_before = fixtures.get_edition(scenario["edition"]["id"])
        assert edition_before["committed_guarantee_total_cents"] == 0
        assert edition_before["open_stage_count"] == 1
        stage_before = fixtures.get_stage(scenario["stage"]["id"])
        assert stage_before["held_show_count"] == 0
        assert stage_before["booking_posture"] == "OPEN"

        sent = validate_success(
            api_client.send_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )
        assert sent["status"] == "SENT"
        assert sent["offered_guarantee_cents"] == self.SENT_GUARANTEE_CENTS

        stage = fixtures.get_stage(scenario["stage"]["id"])
        assert stage["held_show_count"] == 1
        assert stage["booking_posture"] == "SATURATED"
        edition = fixtures.get_edition(scenario["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 12_500_000
        assert edition["open_stage_count"] == 0

    def test_withdraw_restores_the_encumbrance_posture_and_open_stage_count(self):
        """Withdrawing the sent offer releases the hold and recomputes the
        encumbrance from the surviving rows, so both the money figure and the slot
        figures return to precisely the values they carried before the send.

        "because the encumbrance is a full recompute rather than a delta, `committed_guarantee_total_cents` returns to precisely the value it held before the offer was ever sent"

        Design: Difficulty/compensating_invariant/withdraw_restores_committed_guarantee_and_stage_posture
        """
        scenario = self._world_with_single_slot_stage()
        validate_success(
            api_client.send_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )

        withdrawn = validate_success(
            api_client.withdraw_offer(scenario["offer"]["id"], TALENT_BUYER_HEADERS)
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["offered_guarantee_cents"] == 12_500_000

        edition = fixtures.get_edition(scenario["edition"]["id"])
        assert edition["committed_guarantee_total_cents"] == 0
        assert edition["open_stage_count"] == 1
        stage = fixtures.get_stage(scenario["stage"]["id"])
        assert stage["held_show_count"] == 0
        assert stage["booking_posture"] == "OPEN"

        bookings, meta = validate_paginated(
            api_client.list_show_bookings(
                FAIR_OPERATIONS_DIRECTOR_HEADERS, {"offer_id": scenario["offer"]["id"]}
            )
        )
        assert bookings == []
        assert meta["total_count"] == 0
