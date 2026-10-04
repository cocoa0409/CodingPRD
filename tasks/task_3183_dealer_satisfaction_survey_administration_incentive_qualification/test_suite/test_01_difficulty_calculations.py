"""Difficulty queue: dual-variant calculations and combinatorial formulas."""
import pytest

from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    TEST_USERS,
    setup_dealer_env, create_tx, open_wave_and_get_invitations,
    send_invitation, respond, create_statement, confirm_flag,
    reset_clock, assert_statement,
)

ADMIN = TEST_USERS["admin_headers"]


class TestDualVariantCalc:
    def test_dealer_score_adjusted_subtracts_25_per_confirmed_flag(self, api):
        """PRD §3.6: "The adjusted composite — the one stored as
        current_score_adjusted and consumed downstream — subtracts twenty-five
        points per CONFIRMED manipulation flag on the dealer, with the
        trailing-two-wave confirmed_flag_count as the multiplier, rounds
        half-up to two decimal places, and floors at zero so the adjusted
        score can never go negative."

        Design: Difficulty/dual_variant_calc/score_computation_raw_vs_adjusted_divergence_on_dealer
        """
        env = setup_dealer_env(dealer_code="D1", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100000)
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 1
        send_invitation(invs[0]["id"])
        resp = respond(invs[0], cust, {"q1": 8})
        assert resp["score"] == 80.0
        confirm_flag(env["dealer"]["id"], kind="COACHING",
                     evidence="coached customer")
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        dealer = validate_success(api.get_dealer(env["dealer"]["id"], ADMIN))
        assert dealer["current_score_adjusted"] == 775.0, (
            "raw 80*10=800; adjusted = 800 - 25*1 = 775"
        )
        assert dealer["confirmed_flag_count"] == 1

    def test_dealer_score_no_flags_adjusted_equals_raw(self, api):
        """PRD §3.6: "The mean of the individual score values is multiplied by
        ten to land on the 0–1000 scale and rounded half-up to two decimal
        places; this is the raw composite, reported on the wave summary but
        never used for tiering. The adjusted composite — the one stored as
        current_score_adjusted and consumed downstream — subtracts twenty-five
        points per CONFIRMED manipulation flag on the dealer, with the
        trailing-two-wave confirmed_flag_count as the multiplier, rounds
        half-up to two decimal places, and floors at zero so the adjusted
        score can never go negative."

        Design: Difficulty/dual_variant_calc/score_computation_raw_vs_adjusted_divergence_on_dealer
        """
        env = setup_dealer_env(dealer_code="D1b", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100000)
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 1
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 8})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        dealer = validate_success(api.get_dealer(env["dealer"]["id"], ADMIN))
        # zero confirmed flags: adjusted == raw == 80 * 10 == 800
        assert dealer["confirmed_flag_count"] == 0
        assert dealer["current_score_adjusted"] == 800.0

    def test_final_statement_locked_after_finalize_and_payable(self, api):
        """PRD §3.10: "At wave finalize, every PROVISIONAL statement for the
        wave promotes to FINAL. A PlatformAdmin may then mark a FINAL
        statement paid, transitioning it to PAID. PAID and SUPERSEDED are the
        terminal states; there is no path back."

        Design: Difficulty/dual_variant_calc/incentive_tiering_provisional_vs_final_statement_payout_divergence
        """
        env = setup_dealer_env(dealer_code="D2", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100000)
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 1
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 10})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st = create_statement(env["dealer"]["id"], env["wave"]["id"])
        assert st["status"] == "PROVISIONAL"
        assert st["tier"] == "GOLD"
        assert st["payout_cents"] == 8000, "100000 * 0.08 = 8000"
        validate_success(api.finalize_wave(env["wave"]["id"], ADMIN), 200)
        st_after = validate_success(api.get_statement(st["id"], ADMIN))
        assert_statement(st_after)
        assert st_after["status"] == "FINAL"
        assert st_after["tier"] == "GOLD"
        assert st_after["payout_cents"] == 8000
        paid = validate_success(api.pay_statement(st["id"], ADMIN), 200)
        assert paid["status"] == "PAID"

    def test_final_statement_not_superseded_by_restatement(self, api):
        """PRD §3.10: "If a prior PROVISIONAL statement already exists for
        the same (dealer_id, wave_id), creating the new one supersedes the
        old: the old statement transitions to SUPERSEDED, and the new
        statement's supersedes_id points back at it." and "At wave finalize,
        every PROVISIONAL statement for the wave promotes to FINAL. A
        PlatformAdmin may then mark a FINAL statement paid, transitioning it
        to PAID. PAID and SUPERSEDED are the terminal states; there is no
        path back."

        Design: Difficulty/dual_variant_calc/incentive_tiering_provisional_vs_final_statement_payout_divergence
        """
        env = setup_dealer_env(dealer_code="D2b", customers=1)
        cust = env["customers"][0]
        create_tx(env, cust, margin_cents=100000)
        invs = open_wave_and_get_invitations(env)
        send_invitation(invs[0]["id"])
        respond(invs[0], cust, {"q1": 10})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st = create_statement(env["dealer"]["id"], env["wave"]["id"])
        validate_success(api.finalize_wave(env["wave"]["id"], ADMIN), 200)
        # After finalize the statement is FINAL (locked); a restatement for
        # the same (dealer, wave) must not flip the FINAL row to SUPERSEDED —
        # supersession targets the prior PROVISIONAL only.
        st2 = create_statement(env["dealer"]["id"], env["wave"]["id"])
        st1_after = validate_success(api.get_statement(st["id"], ADMIN))
        assert st1_after["status"] == "FINAL", (
            "a FINAL statement is locked; restatement must not supersede it"
        )
        assert st2["status"] == "PROVISIONAL"


class TestCombinatorialFormula:
    def test_tiering_combines_score_rate_and_margin(self, api):
        """PRD §3.10: "If either score_used or response_rate_used is null,
        the tier is INELIGIBLE. Otherwise, if response_rate_used is below
        0.30 — the minimum response-rate gate that makes survey
        administration quality a precondition of payment — the tier is
        INELIGIBLE. Otherwise, tier selection by score: at least 900 earns
        GOLD; at least 800 but below 900 earns SILVER; at least 700 but
        below 800 earns BRONZE; below 700 is INELIGIBLE. payout_cents is
        eligible_margin_cents multiplied by the tier rate — eight percent for
        GOLD, five percent for SILVER, two percent for BRONZE, zero for
        INELIGIBLE — rounded half-up to zero decimal places, so payouts land
        on whole cents."

        Design: Difficulty/combinatorial_formula/incentive_tiering_multi_input_threshold_mode_a
        """
        env = setup_dealer_env(dealer_code="D3", customers=3)
        ca, cb, cc = env["customers"]
        create_tx(env, ca, margin_cents=50000, completed_at="2026-09-05T00:00:00Z")
        create_tx(env, cb, margin_cents=50000, completed_at="2026-09-06T00:00:00Z")
        create_tx(env, cc, margin_cents=50000, completed_at="2026-09-07T00:00:00Z")
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 3
        by_cust = {inv["customer_id"]: inv for inv in invs}
        send_invitation(by_cust[ca["id"]]["id"])
        send_invitation(by_cust[cb["id"]]["id"])
        respond(by_cust[ca["id"]], ca, {"q1": 10})
        respond(by_cust[cb["id"]], cb, {"q1": 10})
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st = create_statement(env["dealer"]["id"], env["wave"]["id"])
        assert_statement(st)
        assert st["score_used"] == 1000.0
        assert st["response_rate_used"] == 0.6667
        assert st["tier"] == "GOLD"
        assert st["eligible_margin_cents"] == 150000
        assert st["payout_cents"] == 12000, "150000 * 0.08 = 12000"

    def test_rate_gate_blocks_high_score_dealer_below_threshold(self, api):
        """PRD §3.10: "Otherwise, if response_rate_used is below 0.30 — the
        minimum response-rate gate that makes survey administration quality a
        precondition of payment — the tier is INELIGIBLE."

        Design: Difficulty/combinatorial_formula/incentive_tiering_multi_input_threshold_mode_a
        """
        env = setup_dealer_env(dealer_code="D3b", customers=4)
        custs = env["customers"]
        for i, cust in enumerate(custs):
            create_tx(env, cust, margin_cents=25000,
                      completed_at=f"2026-09-0{5 + i}T00:00:00Z")
        invs = open_wave_and_get_invitations(env)
        assert len(invs) == 4
        by_cust = {inv["customer_id"]: inv for inv in invs}
        send_invitation(by_cust[custs[0]["id"]]["id"])
        respond(by_cust[custs[0]["id"]], custs[0], {"q1": 10})  # score 1000, rate 1/4 = 0.25
        reset_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_wave(env["wave"]["id"], ADMIN), 200)
        st = create_statement(env["dealer"]["id"], env["wave"]["id"])
        assert st["score_used"] == 1000.0
        assert st["response_rate_used"] == 0.25
        assert st["tier"] == "INELIGIBLE", "rate 0.25 < 0.30 gates tier"
        assert st["payout_cents"] == 0
