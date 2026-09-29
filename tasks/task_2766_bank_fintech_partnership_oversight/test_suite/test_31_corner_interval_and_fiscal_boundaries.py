"""Interval sanity, the two opposite overlap conventions, ledger sign discipline
and the adjacent fiscal boundaries that guard a custody movement."""
from test_helpers import (
    CO,
    PO,
    ApiErrorId,
    api_client,
    close_cycle,
    create_batch,
    create_ledger_entry_payload,
    create_settlement_batch_payload,
    create_partner,
    custody_accounts,
    decide_marketing_review,
    dispose_alert,
    file_marketing_review,
    get_success_data,
    launch_partner,
    open_cycle,
    open_second_cycle,
    post_ledger_entry,
    raise_sanctions_alert,
    read_batch,
    read_custody_account,
    read_partner,
    reconcile_batch,
    seed_end_user_balance,
    seed_reserve_balance,
    set_clock,
    setup_ballast_partner,
    setup_contracted_partner,
    setup_live_partner,
    validate_error,
    validate_success,
)


class TestIntervalSanityAndOverlapConventions:
    def test_settlement_windows_may_abut_per_partner_while_cycle_periods_never_intersect(self):
        """Settlement windows for one partner are half-open, running from `window_start`
        inclusive up to `window_end` exclusive, and `window_end` must be strictly later than
        `window_start`, else `ERR_INVALID_INTERVAL`. Two windows for the same partner may abut
        but never overlap: a new batch may start at exactly a prior batch's `window_end`, and may
        end at exactly a prior batch's `window_start`. Cycle periods are half-open — inclusive of
        `period_start`, exclusive of `period_end` — and no two cycles may overlap: if the new
        interval intersects the interval of any existing cycle, whatever that cycle's `status`,
        the request is refused with `ERR_CYCLE_PERIOD_OVERLAP`.

        Design: Corner/validations/interval_sanity_precedes_overlap_and_settlement_windows_may_abut_but_never_intersect
        """
        cycle = open_cycle()
        assert cycle["cycle_index"] == 1
        partner_a = create_partner(legal_name="Larkspur Settlements Inc")
        partner_b = create_partner(legal_name="Ridgeway Settlements Inc")

        zero_length = api_client.create_settlement_batch(
            create_settlement_batch_payload(
                partner_a["id"],
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-08-01T00:00:00Z",
            ),
            PO,
        )
        validate_error(zero_length, ApiErrorId.ERR_INVALID_INTERVAL, 422)

        first = create_batch(
            partner_a["id"],
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
        )
        abutting = create_batch(
            partner_a["id"],
            window_start="2026-08-08T00:00:00Z",
            window_end="2026-08-15T00:00:00Z",
        )
        assert abutting["reconciliation_status"] == "UNRECONCILED"
        assert abutting["id"] != first["id"]

        one_second_intrusion = api_client.create_settlement_batch(
            create_settlement_batch_payload(
                partner_a["id"],
                window_start="2026-08-07T23:59:59Z",
                window_end="2026-08-09T00:00:00Z",
            ),
            PO,
        )
        validate_error(
            one_second_intrusion, ApiErrorId.ERR_SETTLEMENT_WINDOW_OVERLAP, 409
        )

        other_partner_same_window = create_batch(
            partner_b["id"],
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
        )
        assert other_partner_same_window["partner_id"] == partner_b["id"], (
            "the overlap scan is scoped to one partner's own book"
        )

        straddling_cycle = api_client.create_cycle(
            {
                "cycle_label": "2026-08b",
                "period_start": "2026-08-15T00:00:00Z",
                "period_end": "2026-09-15T00:00:00Z",
            },
            PO,
        )
        validate_error(straddling_cycle, ApiErrorId.ERR_CYCLE_PERIOD_OVERLAP, 409)

        adjacent_cycle = validate_success(
            api_client.create_cycle(
                {
                    "cycle_label": "2026-09",
                    "period_start": "2026-09-01T00:00:00Z",
                    "period_end": "2026-10-01T00:00:00Z",
                },
                PO,
            ),
            expected_status=201,
        )
        assert adjacent_cycle["cycle_index"] == 2
        assert adjacent_cycle["status"] == "OPEN"


class TestDisclosureCoolingBuffer:
    def test_a_gap_of_exactly_three_days_conflicts_and_only_a_longer_gap_clears(self):
        """For a given combination of `partner_id`, `material_type` and `placement_channel`, the
        closed interval running from the new filing's `effective_from` through its
        `effective_until` must be separated from the closed interval of every already-`APPROVED`
        filing on that same combination by **more than three days on both sides**. Unlike the
        settlement windows of §3.5, touching endpoints conflict here, and so does a gap of exactly
        three days — only a gap strictly greater than three days clears.

        Design: Corner/validations/the_disclosure_cooling_buffer_conflicts_at_exactly_three_days_and_clears_only_beyond_it
        """
        ctx = setup_contracted_partner(
            partner_overrides={"legal_name": "Cooling Buffer Wallet Inc"},
        )
        partner_id = ctx["partner"]["id"]
        agreement_id = ctx["agreement"]["id"]
        seed_reserve_balance(partner_id, ctx["reserve"], 312_500)
        assert read_partner(partner_id)["oversight_posture"] == "OPEN"

        reference = file_marketing_review(
            partner_id,
            agreement_id,
            material_type="AD",
            placement_channel="SEARCH",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-09-10T00:00:00Z",
        )
        approved = decide_marketing_review(reference["id"], "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["risk_flags"] == []

        exactly_three_days = file_marketing_review(
            partner_id,
            agreement_id,
            material_type="AD",
            placement_channel="SEARCH",
            effective_from="2026-09-13T00:00:00Z",
            effective_until="2026-09-20T00:00:00Z",
        )
        refused = api_client.decide_marketing_review(
            exactly_three_days["id"], {"decision": "APPROVE"}, CO
        )
        validate_error(refused, ApiErrorId.ERR_DISCLOSURE_WINDOW_CONFLICT, 409)

        one_day_further = file_marketing_review(
            partner_id,
            agreement_id,
            material_type="AD",
            placement_channel="SEARCH",
            effective_from="2026-09-14T00:00:00Z",
            effective_until="2026-09-20T00:00:00Z",
        )
        cleared = decide_marketing_review(one_day_further["id"], "APPROVE")
        assert cleared["status"] == "APPROVED", (
            "2026-09-14 is the first start strictly more than three days past 2026-09-10"
        )

        other_channel = file_marketing_review(
            partner_id,
            agreement_id,
            material_type="AD",
            placement_channel="IN_APP",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-09-10T00:00:00Z",
        )
        assert decide_marketing_review(other_channel["id"], "APPROVE")["status"] == "APPROVED", (
            "the conflict is keyed on the placement channel as well as the material type"
        )

        still_open = get_success_data(
            api_client.get_marketing_review(exactly_three_days["id"], PO)
        )
        assert still_open["status"] == "SUBMITTED", (
            "the refusal leaves the filing available for a resubmit"
        )


class TestLedgerSignAndAccountDiscipline:
    def test_sign_account_and_zero_rules_share_one_error_id_below_the_partner_mismatch_check(self):
        """The account named must belong to the partner named, else
        `ERR_CUSTODY_PARTNER_MISMATCH`. An `END_USER_CREDIT`, a `RESERVE_FUND` or a `CLAWBACK`
        must carry a positive `amount_cents`. In no case may `amount_cents` be zero. The
        classification must also match the account it moves: `END_USER_CREDIT` and
        `END_USER_DEBIT` are only legal on an `FBO_END_USER` account, and `RESERVE_FUND` and
        `RESERVE_RELEASE` are only legal on a `RESERVE` account. The `effective_at` of an entry
        must fall inside the period of an oversight cycle that is currently `OPEN` — at or after
        that cycle's `period_start` and strictly before its `period_end`.

        Design: Corner/validations/ledger_sign_and_account_type_discipline_is_enforced_per_entry_type_and_after_the_partner_mismatch_check
        """
        ctx = setup_live_partner(
            partner_overrides={"legal_name": "Sign Discipline Payments Inc"},
            agreement_overrides={"reserve_requirement_bps": 500},
            fbo_balance_cents=0,
            reserve_balance_cents=312_500,
        )
        partner_id = ctx["partner"]["id"]
        other = setup_contracted_partner(
            partner_overrides={"legal_name": "Second Book Payments Inc"},
            open_the_cycle=False,
        )
        other_fbo = read_custody_account(other["fbo"]["id"])

        cross_partner = api_client.create_ledger_entry(
            create_ledger_entry_payload(
                partner_id,
                other_fbo["id"],
                other_fbo["version"],
                entry_type="END_USER_CREDIT",
                amount_cents=-250_000,
                effective_at="2026-08-01T00:00:00Z",
            ),
            PO,
        )
        validate_error(cross_partner, ApiErrorId.ERR_CUSTODY_PARTNER_MISMATCH, 409)

        wrong_sign = post_ledger_entry(
            partner_id, ctx["fbo"], "END_USER_CREDIT", -250_000
        )
        validate_error(wrong_sign, ApiErrorId.ERR_LEDGER_SIGN_MISMATCH, 422)

        wrong_account = post_ledger_entry(
            partner_id, ctx["fbo"], "RESERVE_FUND", 250_000
        )
        validate_error(wrong_account, ApiErrorId.ERR_LEDGER_SIGN_MISMATCH, 422)

        zero_amount = post_ledger_entry(
            partner_id, ctx["reserve"], "VARIANCE_ADJUSTMENT", 0
        )
        validate_error(zero_amount, ApiErrorId.ERR_LEDGER_SIGN_MISMATCH, 422)

        accepted = validate_success(
            post_ledger_entry(partner_id, ctx["reserve"], "VARIANCE_ADJUSTMENT", 100_000),
            expected_status=201,
        )
        assert accepted["sequence_no"] == 2, (
            "the reserve seed took sequence_no 1 and per-account numbering starts at 1, got "
            f"{accepted['sequence_no']}"
        )
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 412_500

        outside_period = post_ledger_entry(
            partner_id,
            ctx["reserve"],
            "VARIANCE_ADJUSTMENT",
            100_000,
            effective_at="2026-09-05T00:00:00Z",
        )
        validate_error(outside_period, ApiErrorId.ERR_NO_OPEN_CYCLE, 409)

        on_the_exclusive_bound = post_ledger_entry(
            partner_id,
            ctx["reserve"],
            "VARIANCE_ADJUSTMENT",
            100_000,
            effective_at="2026-09-01T00:00:00Z",
        )
        validate_error(on_the_exclusive_bound, ApiErrorId.ERR_NO_OPEN_CYCLE, 409)
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 412_500


class TestBalanceCapAndNegativeFloor:
    def test_the_cap_tolerates_equality_while_the_floor_refuses_a_single_cent_overdraw(self):
        """No custody account may go negative: after applying `amount_cents`, the account's
        `balance_cents` must be at least 0, else `ERR_CUSTODY_INSUFFICIENT_FUNDS`. After an
        `END_USER_CREDIT`, the `FBO_END_USER` account's resulting `balance_cents` must not exceed
        the partner's agreement `max_end_user_balance_cents`; a post-credit balance exactly equal
        to the cap is accepted, and only a balance above it is refused with
        `ERR_END_USER_BALANCE_CAP_EXCEEDED`.

        Design: Corner/validations/the_end_user_balance_cap_accepts_an_exactly_equal_balance_while_the_negative_balance_floor_refuses
        """
        ctx = setup_live_partner(
            partner_overrides={"legal_name": "Fiscal Boundary Wallet Inc"},
            agreement_overrides={
                "max_end_user_balance_cents": 500_000_000,
                "concentration_cap_pct": 100.00,
                "reserve_requirement_bps": 500,
            },
            fbo_balance_cents=0,
            reserve_balance_cents=312_500,
        )
        partner_id = ctx["partner"]["id"]
        setup_ballast_partner(
            60_000_000, cycle_open=False, legal_name="Harbinger Ballast Partner Inc"
        )

        validate_success(
            post_ledger_entry(partner_id, ctx["fbo"], "END_USER_CREDIT", 199_999_999),
            expected_status=201,
        )
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 199_999_999

        one_cent_over = post_ledger_entry(
            partner_id, ctx["fbo"], "END_USER_CREDIT", 300_000_002
        )
        validate_error(one_cent_over, ApiErrorId.ERR_END_USER_BALANCE_CAP_EXCEEDED, 409)

        exactly_at_cap = validate_success(
            post_ledger_entry(partner_id, ctx["fbo"], "END_USER_CREDIT", 300_000_001),
            expected_status=201,
        )
        assert exactly_at_cap["amount_cents"] == 300_000_001
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 500_000_000
        at_cap_partner = read_partner(partner_id)
        assert at_cap_partner["concentration_ratio_pct"] == 89.29, (
            "500000000 of 560000000 is 89.2857 percent, strictly below the 100.00 cap, so the "
            f"concentration rule must not mask the balance cap, got "
            f"{at_cap_partner['concentration_ratio_pct']}"
        )

        one_cent_short = post_ledger_entry(
            partner_id, ctx["fbo"], "END_USER_DEBIT", -500_000_001
        )
        validate_error(one_cent_short, ApiErrorId.ERR_CUSTODY_INSUFFICIENT_FUNDS, 409)

        validate_success(
            post_ledger_entry(partner_id, ctx["fbo"], "END_USER_DEBIT", -500_000_000),
            expected_status=201,
        )
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 0, (
            "the floor is balance >= 0, so a debit landing exactly on zero is legal"
        )


class TestFundingGateLadder:
    def test_one_fund_call_walks_reconciliation_then_live_then_custody_then_reserve(self):
        """The reconciliation dimension must be `MATCHED` or `VARIANCE_CLEARED`, else
        `ERR_BATCH_NOT_RECONCILED`. The partner must be `LIVE`, else `ERR_PARTNER_NOT_LIVE`. The
        partner's `RESERVE` custody account must be `ACTIVE`, else
        `ERR_CUSTODY_ACCOUNT_NOT_ACTIVE`. And the partner's `reserve_shortfall_cents` must be
        exactly 0 — a partner short of reserve does not get paid, and the refusal is
        `ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING`, which is the one condition in this system reported
        as HTTP 402.

        Design: Corner/validations/funding_walks_four_gates_in_priority_order_reconciliation_then_live_then_custody_then_reserve
        """
        ctx = setup_contracted_partner(
            partner_overrides={"legal_name": "Gatewalk Settlements Inc"},
            agreement_overrides={
                "reserve_requirement_bps": 500,
                "max_end_user_balance_cents": 500_000_000,
            },
        )
        partner_id = ctx["partner"]["id"]
        seed_reserve_balance(partner_id, ctx["reserve"], 312_500)

        batch = create_batch(
            partner_id,
            gross_settlement_cents=8_100_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=8_100_000,
        )
        batch_id = batch["id"]
        payload = {"funding_reference": "WIRE-GATEWALK-1"}

        not_reconciled = api_client.fund_settlement_batch(batch_id, payload, PO)
        validate_error(not_reconciled, ApiErrorId.ERR_BATCH_NOT_RECONCILED, 409)

        reconciled = reconcile_batch(batch_id, 8_100_000)
        assert reconciled["reconciliation_status"] == "MATCHED", (
            "a zero variance selects the matched edge, not VARIANCE_OPEN"
        )

        not_live = api_client.fund_settlement_batch(batch_id, payload, PO)
        validate_error(not_live, ApiErrorId.ERR_PARTNER_NOT_LIVE, 409)

        launched = launch_partner(partner_id)
        assert launched["status"] == "LIVE"
        assert launched["reserve_shortfall_cents"] == 0

        seed_end_user_balance(partner_id, ctx["fbo"], 8_100_000)
        seed_end_user_balance(partner_id, ctx["fbo"], 1)
        short = read_partner(partner_id)
        assert short["required_reserve_cents"] == 506_250, short["required_reserve_cents"]
        assert short["reserve_shortfall_cents"] == 193_750, short["reserve_shortfall_cents"]
        assert short["oversight_posture"] == "HEIGHTENED"

        reserve_short = api_client.fund_settlement_batch(batch_id, payload, PO)
        validate_error(reserve_short, ApiErrorId.ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING, 402)

        alert = raise_sanctions_alert(
            partner_id,
            triggered_at="2026-07-31T10:00:00Z",
            detection_note="OFAC name match on an inbound originator pending secondary review",
        )
        assert read_custody_account(ctx["reserve"]["id"])["status"] == "FROZEN"

        frozen_custody = api_client.fund_settlement_batch(batch_id, payload, PO)
        validate_error(frozen_custody, ApiErrorId.ERR_CUSTODY_ACCOUNT_NOT_ACTIVE, 409)
        assert read_partner(partner_id)["reserve_shortfall_cents"] == 193_750, (
            "the reserve gate is still unsatisfied, and the custody gate outranks it"
        )

        assert read_batch(batch_id)["funding_status"] == "UNFUNDED"
        entries = get_success_data(
            api_client.list_ledger_entries(PO, {"partner_id": partner_id, "limit": 100})
        )
        assert len(entries) == 3, (
            "only the three seeding movements exist; no refusal wrote a ledger row, got "
            f"{len(entries)}"
        )
        assert all(entry["settlement_batch_id"] is None for entry in entries)

        # Clearing every gate in turn lets the identical call through.
        dispose_alert(alert["id"], "CLEARED", disposition_note="secondary review cleared the name")
        set_clock("2026-09-01T00:00:00Z")
        close_cycle(ctx["cycle"]["id"])
        assert read_custody_account(ctx["reserve"]["id"])["status"] == "ACTIVE"
        open_second_cycle()
        seed_reserve_balance(
            partner_id, ctx["reserve"], 700_000, effective_at="2026-09-01T00:00:00Z"
        )
        ready = read_partner(partner_id)
        assert ready["reserve_shortfall_cents"] == 0
        assert ready["oversight_posture"] == "OPEN"

        funded = get_success_data(api_client.fund_settlement_batch(batch_id, payload, PO))
        assert funded["funding_status"] == "FUNDED"
        assert funded["bank_fee_bps_applied"] == 45
        assert funded["bank_fee_cents"] == 61_450, funded["bank_fee_cents"]
        assert funded["reserve_funding_cents"] == 405_000
        assert funded["net_to_partner_cents"] == 7_633_550, funded["net_to_partner_cents"]
        assert funded["shortfall_carry_cents"] == 0
