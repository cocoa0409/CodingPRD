"""Franchise filings: the amendment loop, the finalisation cascade and the
checks that stand between a filing and taking effect.
"""
from prd_bench_local_runner.testing import validate_error
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    BOARD_ADMIN,
    make_dealer_headers,
    make_manufacturer_headers,
)


def _served_additional_point_filing():
    """An ADDITIONAL_POINT notice served 2026-09-10, proposing 2026-11-15.

    The proposed point sits 15.00 km from the incumbent at the origin, inside
    the relevant market, so the incumbent has standing to protest.
    """
    ctx = fx.setup_licensed_dealer()
    filing = fx.open_additional_point_filing(
        ctx["manufacturer"]["id"], proposed_effective_on="2026-11-15",
        site_x_km=9, site_y_km=12)
    fx.set_clock("2026-09-10T00:00:00Z")
    ctx["filing"] = fx.serve_notice(filing["id"], ctx["manufacturer"]["id"])
    return ctx


def _protested_additional_point_filing():
    """The same notice with the incumbent's protest lodged on 2026-09-15."""
    ctx = _served_additional_point_filing()
    fx.set_clock("2026-09-15T00:00:00Z")
    ctx["protest"] = fx.file_protest(
        ctx["filing"]["id"], ctx["dealer"]["id"], ctx["filing"]["version"],
        grounds_code="MARKET_ENCROACHMENT")
    return ctx


class TestAmendmentLoop:
    def test_amending_from_protest_pending_returns_to_notice_served(self, api):
        """PRD 3.4: "An amendment is admitted from `NOTICE_SERVED`, where it
        returns the filing to `NOTICE_SERVED`, and from `PROTEST_PENDING`, where
        it also returns the filing to `NOTICE_SERVED`." PRD 3.4: "Each protest
        against that filing standing in `FILED` or `SCHEDULED` moves to
        `WITHDRAWN`." PRD 3.4: "restarts the protest window by setting
        `protest_window_ends_on` to 30 days after the clock date."

        Design: Difficulty/non_linear_state_machine/franchise_filing_amend_cycle_back_to_notice_served
        """
        ctx = _protested_additional_point_filing()
        assert fx.read_filing(ctx["filing"]["id"])["status"] == "PROTEST_PENDING"

        fx.set_clock("2026-09-16T00:00:00Z")
        amended = fx.amend_filing(
            ctx["filing"]["id"], ctx["manufacturer"]["id"], "2026-11-20",
            site_x_km=9, site_y_km=12)

        assert amended["status"] == "NOTICE_SERVED"
        assert amended["amendment_count"] == 1
        assert amended["notice_served_on"] == "2026-09-16"
        assert amended["protest_window_ends_on"] == "2026-10-16"
        assert amended["active_protest_count"] == 0

        protest = fx.read_protest(ctx["protest"]["id"])
        assert protest["status"] == "WITHDRAWN"
        assert protest["hearing_room_id"] is None

    def test_the_third_amendment_is_refused_by_the_loop_cap(self, api):
        """PRD 3.4: "a filing whose `amendment_count` is still below 2 — a third
        amendment is refused with `ERR_AMENDMENT_LIMIT_REACHED`." The second
        amendment re-enters `NOTICE_SERVED` from itself and is admitted, so only
        the cap can stop the third.

        Design: Difficulty/non_linear_state_machine/franchise_filing_amend_cycle_back_to_notice_served
        """
        ctx = _protested_additional_point_filing()
        fx.set_clock("2026-09-16T00:00:00Z")
        fx.amend_filing(ctx["filing"]["id"], ctx["manufacturer"]["id"], "2026-11-20",
                        site_x_km=9, site_y_km=12)

        fx.set_clock("2026-09-17T00:00:00Z")
        second = fx.amend_filing(ctx["filing"]["id"], ctx["manufacturer"]["id"],
                                 "2026-11-21", site_x_km=9, site_y_km=12)
        assert second["status"] == "NOTICE_SERVED"
        assert second["amendment_count"] == 2
        assert second["notice_served_on"] == "2026-09-17"
        assert second["protest_window_ends_on"] == "2026-10-17"
        assert second["proposed_effective_on"] == "2026-11-21"

        fx.set_clock("2026-09-18T00:00:00Z")
        response = api.amend_franchise_filing(
            ctx["filing"]["id"],
            f.amendment_payload("2026-11-22", site_x_km=9, site_y_km=12),
            make_manufacturer_headers(ctx["manufacturer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_AMENDMENT_LIMIT_REACHED.value)

        after = fx.read_filing(ctx["filing"]["id"])
        assert after["amendment_count"] == 2
        assert after["proposed_effective_on"] == "2026-11-21"


def _terminating_dealer_with_live_dispute():
    """A licensed dealership with a salesperson and an unanswered rate dispute,
    under a TERMINATION notice served 2026-09-10 for 2026-11-15."""
    ctx = fx.setup_licensed_dealer()
    dealer, manufacturer = ctx["dealer"], ctx["manufacturer"]

    fx.set_clock("2026-09-02T00:00:00Z")
    ctx["salesperson"] = fx.license_salesperson(dealer["id"], full_name="Dana Reyes")

    fx.set_clock("2026-09-03T00:00:00Z")
    ctx["dispute"] = fx.file_rate_dispute(
        dealer["id"], manufacturer["id"],
        [
            f.repair_order_line(12000, 1.0),
            f.repair_order_line(9000, 1.5),
            f.repair_order_line(10000, 2.0),
            f.repair_order_line(8000, 0.5),
            f.repair_order_line(6000, 2.0),
            f.repair_order_line(5000, 0.4),
            f.repair_order_line(7000, 1.0, "WARRANTY"),
        ],
    )

    filing = fx.open_termination_filing(
        manufacturer["id"], dealer["id"], "2026-11-15")
    fx.set_clock("2026-09-10T00:00:00Z")
    ctx["filing"] = fx.serve_notice(filing["id"], manufacturer["id"])
    return ctx


class TestTerminationFinalisationCascade:
    def test_finalising_a_termination_cancels_the_licence_and_the_sponsorships(self, api):
        """PRD 3.4: "On a `TERMINATION` the affected dealership's franchise
        dimension moves `TERMINATION_PENDING → TERMINATED` and, for a
        `NEW_MOTOR_VEHICLE` dealership, its licence dimension moves `LICENSED →
        CANCELLED` in the same request." PRD 3.4: "In the same request each of
        that dealership's salespersons in `LICENSED` or `RENEWAL_PENDING` moves to
        `SUSPENDED_BY_SPONSOR`, and the dealership's `version` increments by 1."

        Design: Difficulty/transitive_cascade/filing_finalize_termination_to_dispute_moot_to_mfr_count
        """
        ctx = _terminating_dealer_with_live_dispute()
        before = fx.read_dealer(ctx["dealer"]["id"])
        assert before["franchise_status"] == "TERMINATION_PENDING"
        assert before["license_status"] == "LICENSED"

        fx.set_clock("2026-11-15T00:00:00Z")
        finalised = fx.finalize_filing(ctx["filing"]["id"])

        assert finalised["status"] == "EFFECTIVE"
        after = fx.read_dealer(ctx["dealer"]["id"])
        assert after["license_status"] == "CANCELLED"
        assert after["franchise_status"] == "TERMINATED"
        assert after["licensed_salesperson_count"] == 0
        assert after["version"] > before["version"]
        assert (fx.read_salesperson(ctx["salesperson"]["id"])["license_status"]
                == "SUSPENDED_BY_SPONSOR")

    def test_the_cascade_moots_the_live_dispute_and_recomputes_the_counters(self, api):
        """PRD 3.4: "every warranty rate dispute naming that dealership and still
        standing in `FILED` or `UNDER_REVIEW` moves to `DISMISSED_MOOT`, and
        because those disputes are no longer open, `open_dispute_count` is
        recomputed for each franchisor whose dispute was mooted." The mooted row
        keeps its filing-time figures, because PRD 3.8 leaves
        `approved_rate_cents` to the board's approval alone.

        Design: Difficulty/transitive_cascade/filing_finalize_termination_to_dispute_moot_to_mfr_count
        """
        ctx = _terminating_dealer_with_live_dispute()
        assert fx.read_manufacturer(ctx["manufacturer"]["id"])["open_dispute_count"] == 1

        fx.set_clock("2026-11-15T00:00:00Z")
        fx.finalize_filing(ctx["filing"]["id"])

        dispute = fx.read_dispute(ctx["dispute"]["id"])
        assert dispute["status"] == "DISMISSED_MOOT"
        assert dispute["qualifying_line_count"] == 5
        assert dispute["declared_rate_cents"] == 8400
        assert dispute["approved_rate_cents"] is None

        manufacturer = fx.read_manufacturer(ctx["manufacturer"]["id"])
        assert manufacturer["open_dispute_count"] == 0
        assert manufacturer["active_filing_count"] == 0
        assert fx.read_dealer(ctx["dealer"]["id"])["approved_warranty_labor_rate_cents"] is None


class TestProtestStateGateBeatsTheWindow:
    def test_protesting_an_effective_filing_reports_the_state_not_the_window(self, api):
        """PRD 2.10 orders the scan so that "**State gates** — the target record
        is in a state that admits the requested action" is reached before
        "**Temporal checks**, in this order: notice period length
        (`ERR_NOTICE_PERIOD_TOO_SHORT`), protest window still open
        (`ERR_PROTEST_WINDOW_CLOSED`)". PRD 3.5: "a filing still in `DRAFT`, or
        already in `PROTEST_RESOLVED`, `EFFECTIVE` or `BARRED`, is refused with
        `ERR_INVALID_FILING_STATE`." A filing that took effect on 2026-11-15 also
        has a window that closed on 2026-10-10, so both faults are live and only
        the ordering decides.

        Design: Difficulty/priority_pair_validation_conflict/protest_on_effective_filing_state_beats_window_closed_temporal
        """
        ctx = _served_additional_point_filing()
        assert ctx["filing"]["protest_window_ends_on"] == "2026-10-10"

        fx.set_clock("2026-11-15T00:00:00Z")
        effective = fx.finalize_filing(ctx["filing"]["id"])
        assert effective["status"] == "EFFECTIVE"

        fx.set_clock("2026-11-16T00:00:00Z")
        response = api.create_protest(
            f.protest_payload(effective["id"], ctx["dealer"]["id"], effective["version"],
                              grounds_code="MARKET_ENCROACHMENT"),
            make_dealer_headers(ctx["dealer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_FILING_STATE.value,
                       expected_status=409)

        after = fx.read_filing(effective["id"])
        assert after["status"] == "EFFECTIVE"
        assert after["active_protest_count"] == 0
        assert after["protest_window_ends_on"] == "2026-10-10"

    def test_the_window_check_is_reachable_while_the_filing_still_admits_protests(self, api):
        """PRD 3.5: "The 30-day window must still be running: the clock date must
        be on or before the filing's `protest_window_ends_on`, and a later filing
        draws `ERR_PROTEST_WINDOW_CLOSED`." Left in `NOTICE_SERVED` the same
        filing passes the state gate, so the temporal fault is the one reported —
        which is what makes the previous test's outcome an ordering result rather
        than an accident.

        Design: Difficulty/priority_pair_validation_conflict/protest_on_effective_filing_state_beats_window_closed_temporal
        """
        ctx = _served_additional_point_filing()

        fx.set_clock("2026-10-11T00:00:00Z")
        response = api.create_protest(
            f.protest_payload(ctx["filing"]["id"], ctx["dealer"]["id"],
                              ctx["filing"]["version"],
                              grounds_code="MARKET_ENCROACHMENT"),
            make_dealer_headers(ctx["dealer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PROTEST_WINDOW_CLOSED.value,
                       expected_status=422)

        after = fx.read_filing(ctx["filing"]["id"])
        assert after["status"] == "NOTICE_SERVED"
        assert after["active_protest_count"] == 0


class TestFinalisationBlockedByProtest:
    def test_a_live_protest_turns_the_finalisation_away_after_the_state_gate(self, api):
        """PRD 3.4: "The filing's `active_protest_count` must be exactly 0, or the
        request draws `ERR_ACTIVE_PROTEST_BLOCKS_FINALIZE` — which is how a filing
        still sitting in `PROTEST_PENDING` is turned away, since it clears the
        state gate and then fails this one." The window closed on 2026-10-10 and
        the effective date has arrived, so the protest is the only remaining
        obstacle.

        Design: Difficulty/cross_entity_state_dependency/filing_finalize_blocked_by_active_protest
        """
        ctx = _protested_additional_point_filing()
        blocked = fx.read_filing(ctx["filing"]["id"])
        assert blocked["status"] == "PROTEST_PENDING"
        assert blocked["active_protest_count"] == 1

        fx.set_clock("2026-11-15T00:00:00Z")
        response = api_client.finalize_franchise_filing(ctx["filing"]["id"], BOARD_ADMIN)
        validate_error(response, ApiErrorId.ERR_ACTIVE_PROTEST_BLOCKS_FINALIZE.value,
                       expected_status=409)

        after = fx.read_filing(ctx["filing"]["id"])
        assert after["status"] == "PROTEST_PENDING"
        assert after["active_protest_count"] == 1
        assert after["proposed_effective_on"] == "2026-11-15"

    def test_withdrawing_the_protest_by_amendment_clears_the_way_to_effective(self, api):
        """PRD 3.4: "Each protest against that filing standing in `FILED` or
        `SCHEDULED` moves to `WITHDRAWN`." PRD 3.4: "The filing's
        `active_protest_count` is then recomputed to 0." PRD 3.4: "On an
        `ADDITIONAL_POINT`, no
        dealership row is touched at all." The identical finalisation therefore
        succeeds once the amendment has emptied the count and the restarted
        window has run out.

        Design: Difficulty/cross_entity_state_dependency/filing_finalize_blocked_by_active_protest
        """
        ctx = _protested_additional_point_filing()
        fx.set_clock("2026-11-16T00:00:00Z")
        amended = fx.amend_filing(
            ctx["filing"]["id"], ctx["manufacturer"]["id"], "2027-01-20")

        assert amended["status"] == "NOTICE_SERVED"
        assert amended["active_protest_count"] == 0
        assert amended["protest_window_ends_on"] == "2026-12-16"
        assert fx.read_protest(ctx["protest"]["id"])["status"] == "WITHDRAWN"

        fx.set_clock("2027-01-20T00:00:00Z")
        effective = fx.finalize_filing(ctx["filing"]["id"])

        assert effective["status"] == "EFFECTIVE"
        assert effective["amendment_count"] == 1
        assert effective["active_protest_count"] == 0
        assert fx.read_manufacturer(ctx["manufacturer"]["id"])["active_filing_count"] == 0

        dealer = fx.read_dealer(ctx["dealer"]["id"])
        assert dealer["license_status"] == "LICENSED"
        assert dealer["franchise_status"] == "FRANCHISED"
        assert dealer["site_x_km"] == 0
