"""Cross-cutting corners: the three optimistic-concurrency tokens in one chain, the
five-link funding cascade whose link order decides admissibility, the reserve-basis
variant worth exactly five thousand cents, and the checkpoint that alone thaws custody."""
from test_helpers import (
    CO,
    PO,
    RC,
    ApiErrorId,
    account_census_payload,
    api_client,
    assert_same_instant,
    assert_two_decimal_percentage,
    clawback_batch,
    clear_variance,
    close_cycle,
    create_agreement_payload,
    create_batch,
    create_diligence_review_payload,
    create_ledger_entry_payload,
    create_partner,
    custody_accounts,
    file_complaint,
    fund_batch,
    get_success_data,
    open_cycle,
    open_second_cycle,
    raise_alert,
    dispose_alert,
    read_batch,
    read_custody_account,
    read_partner,
    reconcile_batch,
    seed_end_user_balance,
    seed_reserve_balance,
    setup_live_partner,
    set_clock,
    validate_error,
    validate_paginated,
)


def _ledger_rows(params):
    data, meta = validate_paginated(api_client.list_ledger_entries(PO, params=params))
    return data, meta


class TestAllThreeOptimisticConcurrencyTokens:
    def test_a_stale_token_is_refused_and_the_refreshed_one_is_accepted_at_every_gate(self):
        """Creating a diligence review — `POST /oversight/diligence-reviews` — must carry
        `expected_partner_version` matching the target `Partner`'s current `version`. Booking a
        ledger entry — `POST /oversight/ledger-entries` — must carry
        `expected_custody_account_version` matching the current `version` of the `CustodyAccount`
        named in the body. A census overwrites `end_user_account_count` outright rather than
        accumulating, then recomputes the partner's `complaint_rate_bps` and re-evaluates the
        posture ladder, and increments the partner's `version` by 1.

        Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
        """
        open_cycle()
        partner = create_partner(legal_name="Larkspur Rails Inc", end_user_account_count=1_000)
        partner_id = partner["id"]
        version_1 = partner["version"]

        censused = get_success_data(
            api_client.report_account_census(
                partner_id, account_census_payload(end_user_account_count=120_000), PO
            )
        )
        assert censused["end_user_account_count"] == 120_000, (
            "the census overwrites the count outright rather than accumulating"
        )
        version_2 = censused["version"]
        assert version_2 == version_1 + 1, (
            f"a census is a write and bumps the partner version, got {version_2}"
        )

        validate_error(
            api_client.create_diligence_review(
                create_diligence_review_payload(partner_id, version_1), PO
            ),
            ApiErrorId.ERR_STALE_PARTNER_VERSION,
            412,
        )
        _rows, meta = validate_paginated(
            api_client.list_diligence_reviews(PO, params={"partner_id": partner_id})
        )
        assert meta["total_count"] == 0, (
            "the refused create is returned before any state change, so the collection is empty"
        )

        review = get_success_data(
            api_client.create_diligence_review(
                create_diligence_review_payload(partner_id, version_2), PO
            )
        )
        assert review["status"] == "DRAFT", (
            "the byte-identical retry carrying the refreshed version is accepted, so the 412 "
            "can only be attributed to the version token"
        )
        get_success_data(api_client.submit_diligence_review(review["id"], {}, PO))
        decided = get_success_data(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, CO)
        )
        assert decided["status"] == "PASSED"

        validate_error(
            api_client.create_agreement(create_agreement_payload(partner_id, version_2), PO),
            ApiErrorId.ERR_STALE_PARTNER_VERSION,
            412,
        )
        passed = read_partner(partner_id)
        assert passed["status"] == "DILIGENCE_PASSED"
        agreement = get_success_data(
            api_client.create_agreement(
                create_agreement_payload(partner_id, passed["version"]), PO
            )
        )
        assert agreement["status"] == "DRAFT", (
            "the decision rewrote capability_tier and latest_composite_score behind the client's "
            "back, so only the version read after it is usable"
        )
        get_success_data(api_client.submit_agreement_for_approval(agreement["id"], {}, PO))
        get_success_data(
            api_client.decide_agreement_risk(agreement["id"], {"decision": "EXECUTE"}, RC)
        )

        _fbo, reserve = custody_accounts(partner_id)
        assert reserve["version"] == 1
        assert reserve["balance_cents"] == 0
        seeded = seed_reserve_balance(partner_id, reserve, 312_500)
        assert seeded["sequence_no"] == 1
        reserve_v2 = read_custody_account(reserve["id"])["version"]
        assert reserve_v2 == reserve["version"] + 1, (
            f"the client's own reserve funding bumps the account version, got {reserve_v2}"
        )

        validate_error(
            api_client.create_ledger_entry(
                create_ledger_entry_payload(
                    partner_id,
                    reserve["id"],
                    reserve["version"],
                    entry_type="RESERVE_FUND",
                    amount_cents=100_000,
                ),
                PO,
            ),
            ApiErrorId.ERR_STALE_CUSTODY_ACCOUNT_VERSION,
            412,
        )
        still = read_custody_account(reserve["id"])
        assert still["balance_cents"] == 312_500, "no second entry was booked"
        assert still["version"] == reserve_v2, "the refused booking left the version alone"

        accepted = get_success_data(
            api_client.create_ledger_entry(
                create_ledger_entry_payload(
                    partner_id,
                    reserve["id"],
                    reserve_v2,
                    entry_type="RESERVE_FUND",
                    amount_cents=100_000,
                ),
                PO,
            )
        )
        assert accepted["amount_cents"] == 100_000
        assert accepted["sequence_no"] == 2
        final = read_custody_account(reserve["id"])
        assert final["balance_cents"] == 412_500
        assert final["version"] == reserve_v2 + 1


class TestFundingDrivesTheFullCascade:
    def test_the_same_funding_is_refused_then_allowed_with_only_the_reserve_balance_changed(self):
        """Each ledger insert recomputes its account's `balance_cents`; the changed balances
        recompute the partner's `required_reserve_cents`, `reserve_shortfall_cents` and
        `concentration_ratio_pct`; the recomputed shortfall re-derives `oversight_posture`; and a
        posture of `FROZEN` moves both custody accounts `ACTIVE → FROZEN`. The base is then
        multiplied by a posture multiplier and the product floored to whole cents: 1.00 at `OPEN`,
        1.25 at `HEIGHTENED`, 1.50 at `RESTRICTED` and 2.00 at `FROZEN`.

        Design: Corner/cross_cutting_complexity_layers/funding_drives_the_full_five_link_cascade_and_the_link_order_decides_whether_it_is_allowed
        """
        ctx = setup_live_partner(
            partner_overrides={
                "legal_name": "Marlowe Transit Inc",
                "business_model": "CARD_ISSUING",
                "end_user_account_count": 40_000,
            },
            fbo_balance_cents=0,
            reserve_balance_cents=312_500,
        )
        partner_id = ctx["partner"]["id"]
        seed_end_user_balance(partner_id, ctx["fbo"], 8_100_000)

        before = read_partner(partner_id)
        assert before["required_reserve_cents"] == 405_000, (
            "the 500 bps end-user term beats both the trailing-gross floor of 0 and the 250000 "
            f"absolute floor at the OPEN multiplier, got {before['required_reserve_cents']}"
        )
        assert before["reserve_shortfall_cents"] == 92_500
        assert before["oversight_posture"] == "HEIGHTENED"

        batch = create_batch(
            partner_id,
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-15T00:00:00Z",
            gross_settlement_cents=8_000_000,
            interchange_cents=200_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_100_000,
        )
        reconciled = reconcile_batch(batch["id"], 8_100_000)
        assert reconciled["reconciliation_status"] == "MATCHED"
        assert reconciled["variance_cents"] == 0
        after_recon = read_partner(partner_id)
        assert after_recon["required_reserve_cents"] == 405_000, (
            "reconciliation is not one of the reserve recomputation triggers, so it leaves the "
            "reserve fields untouched"
        )
        assert after_recon["reserve_shortfall_cents"] == 92_500

        validate_error(
            api_client.fund_settlement_batch(batch["id"], {"funding_reference": "WIRE-X-1"}, PO),
            ApiErrorId.ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING,
            402,
        )
        assert read_batch(batch["id"])["funding_status"] == "UNFUNDED"
        _rows, meta = _ledger_rows({"partner_id": partner_id})
        assert meta["total_count"] == 2, (
            "the shortfall gate precedes the first link of the cascade, so no leg was written, "
            f"got {meta['total_count']} entries"
        )

        seed_reserve_balance(partner_id, ctx["reserve"], 193_750)
        mid = read_partner(partner_id)
        assert mid["required_reserve_cents"] == 506_250, (
            "the top-up's own pass reads the heightened multiplier the previous pass wrote, so "
            f"405000 is scaled by 1.25, got {mid['required_reserve_cents']}"
        )
        assert mid["reserve_shortfall_cents"] == 0, (
            "paying only the 92500 the client could see beforehand would have left a shortfall"
        )
        assert mid["oversight_posture"] == "OPEN"

        funded = fund_batch(batch["id"], funding_reference="WIRE-X-2")
        assert funded["funding_status"] == "FUNDED"
        assert funded["bank_fee_bps_applied"] == 45
        assert funded["bank_fee_cents"] == 61_000
        assert funded["settlement_base_cents"] == 8_100_000
        assert funded["reserve_funding_cents"] == 400_000
        assert funded["net_to_partner_cents"] == 7_639_000
        assert funded["shortfall_carry_cents"] == 0
        assert_same_instant(funded["funded_at"], "2026-08-01T00:00:00Z", "funded_at")

        legs, legs_meta = _ledger_rows({"settlement_batch_id": batch["id"]})
        assert legs_meta["total_count"] == 3, f"three synthesised legs, got {legs_meta}"
        by_type = {leg["entry_type"]: leg for leg in legs}
        assert by_type["END_USER_DEBIT"]["amount_cents"] == -8_100_000
        assert by_type["RESERVE_FUND"]["amount_cents"] == 400_000
        assert by_type["FEE"]["amount_cents"] == -61_000
        assert all(leg["settlement_batch_id"] == batch["id"] for leg in legs)

        accounts, acc_meta = validate_paginated(
            api_client.list_custody_accounts(PO, params={"partner_id": partner_id})
        )
        assert acc_meta["total_count"] == 2
        assert all(account["status"] == "ACTIVE" for account in accounts), (
            "the posture never reached FROZEN, so the last link of the cascade does not fire"
        )
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 0
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 845_250, (
            "506250 plus the 400000 reserve leg less the 61000 fee leg"
        )

        after = read_partner(partner_id)
        assert after["cumulative_paid_out_cents"] == 7_639_000
        assert after["cumulative_bank_fee_cents"] == 61_000, (
            "the counters take the net and the fee, never the settlement base"
        )
        assert after["required_reserve_cents"] == 250_000, (
            "with the end-user account drained the 500 bps term is 0 and the trailing-gross term "
            "is 0 because the batch window ends after the logical clock, so the absolute floor wins"
        )
        assert after["reserve_shortfall_cents"] == 0
        assert after["oversight_posture"] == "OPEN"
        assert_two_decimal_percentage(after["concentration_ratio_pct"], "concentration_ratio_pct")
        assert after["concentration_ratio_pct"] == 0.00, (
            "the bank-wide end-user denominator is now zero, which is defined to be 0.00 rather "
            f"than an error, got {after['concentration_ratio_pct']}"
        )


class TestTheReserveBasisVariant:
    def test_two_batches_with_an_identical_base_differ_by_exactly_the_adjustment_at_five_hundred_bps(self):
        """For a batch that is `MATCHED`, the basis is `gross_settlement_cents` alone, ignoring
        interchange, returns and adjustments: the reserve funding is that gross multiplied by
        `reserve_requirement_bps`, divided by 10000 and floored to whole cents. For a batch that is
        `VARIANCE_CLEARED`, the basis is `settlement_base_cents` instead, multiplied by the same
        `reserve_requirement_bps`, divided by 10000 and floored to whole cents.

        Design: Corner/cross_cutting_complexity_layers/the_reserve_basis_variant_moves_exactly_5000_cents_on_an_identical_settlement_base
        """
        ctx = setup_live_partner(
            partner_overrides={
                "legal_name": "Netherby Payments Inc",
                "business_model": "PAYMENT_FACILITATION",
                "end_user_account_count": 30_000,
            },
            agreement_overrides={"reserve_requirement_bps": 500},
            fbo_balance_cents=8_100_000,
            reserve_balance_cents=506_250,
        )
        partner_id = ctx["partner"]["id"]

        matched = create_batch(
            partner_id,
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-15T00:00:00Z",
            gross_settlement_cents=8_000_000,
            interchange_cents=200_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_100_000,
        )
        matched = reconcile_batch(matched["id"], 8_100_000)
        assert matched["reconciliation_status"] == "MATCHED"
        assert matched["variance_cents"] == 0

        variant = create_batch(
            partner_id,
            window_start="2026-07-15T00:00:00Z",
            window_end="2026-07-29T00:00:00Z",
            gross_settlement_cents=8_000_000,
            interchange_cents=100_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_000_000,
        )
        variant = reconcile_batch(variant["id"], 8_100_000)
        assert variant["reconciliation_status"] == "VARIANCE_OPEN"
        assert variant["variance_cents"] == 100_000
        variant = clear_variance(
            variant["id"], 100_000, root_cause_note="an interchange file arrived a day late"
        )
        assert variant["reconciliation_status"] == "VARIANCE_CLEARED"
        assert variant["variance_adjustment_cents"] == 100_000
        assert variant["settlement_base_cents"] == 8_100_000, (
            "the cleared adjustment is the fourth term of the base, so the two batches reach the "
            f"very same base by different routes, got {variant['settlement_base_cents']}"
        )

        gross_basis = fund_batch(matched["id"], funding_reference="WIRE-G-1")
        assert gross_basis["settlement_base_cents"] == 8_100_000
        assert gross_basis["bank_fee_cents"] == 61_000
        assert gross_basis["reserve_funding_cents"] == 400_000, (
            "the gross basis ignores interchange, returns and the adjustment, got "
            f"{gross_basis['reserve_funding_cents']}"
        )
        assert gross_basis["net_to_partner_cents"] == 7_639_000

        clawed = clawback_batch(matched["id"], clawback_reason="RECONCILIATION_ERROR")
        assert clawed["funding_status"] == "CLAWED_BACK"
        assert clawed["net_to_partner_cents"] == 7_639_000, (
            "the historical figures survive the reversal, so the two variants stay comparable"
        )
        assert clawed["funded_at"] is not None
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 506_250
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 8_100_000
        restored = read_partner(partner_id)
        assert restored["cumulative_paid_out_cents"] == 0
        assert restored["cumulative_bank_fee_cents"] == 0
        assert restored["reserve_shortfall_cents"] == 0, (
            "the second funding therefore starts from the same custody state as the first"
        )

        net_basis = fund_batch(variant["id"], funding_reference="WIRE-N-1")
        assert net_basis["settlement_base_cents"] == 8_100_000
        assert net_basis["bank_fee_cents"] == 61_000
        assert net_basis["reserve_funding_cents"] == 405_000, (
            "the net basis takes the whole settlement base, got "
            f"{net_basis['reserve_funding_cents']}"
        )
        assert net_basis["net_to_partner_cents"] == 7_634_000

        assert net_basis["reserve_funding_cents"] - gross_basis["reserve_funding_cents"] == 5_000, (
            "the only possible source of a difference is the variant selector, and it must be "
            "exactly the adjustment scaled by 500 basis points"
        )
        assert gross_basis["net_to_partner_cents"] - net_basis["net_to_partner_cents"] == 5_000, (
            "the extra reserve routing comes straight out of the payout"
        )


class TestOnlyTheCheckpointThawsCustody:
    def test_clearing_the_sanctions_alert_does_not_reopen_custody_but_the_close_does(self):
        """Note carefully that the posture may drop off `FROZEN` at that moment but the custody
        accounts do **not** thaw inside this request: unfreezing is deferred to the next oversight
        cycle close. Symmetrically, a partner whose recomputed posture is no longer `FROZEN` has
        each of its `FROZEN` custody accounts returned to `ACTIVE`, setting `frozen_at` back to null
        and incrementing that account's `version` by 1 — this is the deferred thaw promised in
        §3.8, and it is the only place a frozen account ever reopens.

        Design: Corner/cross_cutting_complexity_layers/the_cycle_close_checkpoint_is_the_only_writer_that_can_unfreeze_custody
        """
        ctx = setup_live_partner(
            partner_overrides={
                "legal_name": "Orrindale Wallet Inc",
                "business_model": "DEPOSIT_WALLET",
                "end_user_account_count": 100_000,
            },
            fbo_balance_cents=8_100_000,
            reserve_balance_cents=506_250,
        )
        partner_id = ctx["partner"]["id"]
        complaint = file_complaint(
            partner_id,
            channel="EMAIL",
            received_at="2026-07-25T08:00:00Z",
            narrative="a duplicated monthly maintenance fee",
        )
        assert_same_instant(
            complaint["response_due_at"], "2026-08-24T08:00:00Z", "response_due_at"
        )

        alert = raise_alert(
            partner_id,
            alert_type="SANCTIONS_HIT",
            triggered_at="2026-08-01T00:00:00Z",
            detection_note="an inbound transfer matched a sanctions list entry by name",
        )
        frozen_partner = read_partner(partner_id)
        assert frozen_partner["oversight_posture"] == "FROZEN"
        assert frozen_partner["open_sanctions_alert_count"] == 1
        frozen_accounts, frozen_meta = validate_paginated(
            api_client.list_custody_accounts(PO, params={"partner_id": partner_id})
        )
        assert frozen_meta["total_count"] == 2
        assert all(account["status"] == "FROZEN" for account in frozen_accounts), (
            "the freeze landed inside an ordinary business write, got "
            f"{[account['status'] for account in frozen_accounts]}"
        )
        assert all(account["frozen_at"] is not None for account in frozen_accounts)

        cleared = dispose_alert(
            alert["id"], "CLEARED", disposition_note="the name match was a false positive"
        )
        assert cleared["disposition"] == "CLEARED"
        thawing_attempt = read_partner(partner_id)
        assert thawing_attempt["open_sanctions_alert_count"] == 0
        assert thawing_attempt["oversight_posture"] == "OPEN", (
            "the ladder finds no open sanctions alert and no shortfall, got "
            f"{thawing_attempt['oversight_posture']}"
        )
        assert thawing_attempt["required_reserve_cents"] == 506_250, (
            "an alert disposition is not one of the reserve recomputation triggers"
        )
        still_frozen = read_custody_account(ctx["reserve"]["id"])
        assert still_frozen["status"] == "FROZEN", (
            "no business write unfreezes custody, whatever the posture now says"
        )

        refused = api_client.create_ledger_entry(
            create_ledger_entry_payload(
                partner_id,
                still_frozen["id"],
                still_frozen["version"],
                entry_type="RESERVE_FUND",
                amount_cents=50_000,
                effective_at="2026-09-01T00:00:00Z",
            ),
            PO,
        )
        validate_error(refused, ApiErrorId.ERR_CUSTODY_ACCOUNT_NOT_ACTIVE, 409)

        set_clock("2026-09-01T00:00:00Z")
        closed = close_cycle(ctx["cycle"]["id"], closing_note="August checkpoint")
        assert closed["status"] == "CLOSED"
        assert_same_instant(closed["closed_at"], "2026-09-01T00:00:00Z", "closed_at")
        assert closed["complaints_escalated_count"] == 1, (
            "the EMAIL complaint's response_due_at has fallen behind the logical clock"
        )
        assert closed["alerts_reopened_count"] == 0, (
            "step 2 only touches alerts sitting in PARTNER_RESPONSE_PENDING"
        )
        assert closed["partners_frozen_count"] == 0, (
            "step 6 counts the partners this close froze, not the partners it thawed"
        )
        assert closed["marketing_approvals_expired_count"] == 0
        assert closed["growth_breach_partner_count"] == 0
        assert closed["plans_completed_count"] == 0

        escalated = get_success_data(api_client.get_complaint(complaint["id"], PO))
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_count"] == 1

        reunderwritten = read_partner(partner_id)
        assert reunderwritten["complaint_rate_bps"] == 0, (
            "one complaint across a hundred thousand accounts rounds to zero basis points, got "
            f"{reunderwritten['complaint_rate_bps']}"
        )
        assert reunderwritten["required_reserve_cents"] == 405_000, (
            "the close reads the persisted OPEN posture, so the 500 bps term is unscaled, got "
            f"{reunderwritten['required_reserve_cents']}"
        )
        assert reunderwritten["reserve_shortfall_cents"] == 0
        assert reunderwritten["consecutive_shortfall_cycles"] == 0
        assert reunderwritten["oversight_posture"] == "OPEN"
        assert reunderwritten["concentration_ratio_pct"] == 100.00, (
            "this partner holds the bank's entire end-user float"
        )
        assert reunderwritten["open_complaint_count"] == 0
        assert reunderwritten["escalated_complaint_count"] == 1

        thawed, _meta = validate_paginated(
            api_client.list_custody_accounts(PO, params={"partner_id": partner_id})
        )
        assert all(account["status"] == "ACTIVE" for account in thawed), (
            "step 4 reopened both rows because the recomputed posture is no longer FROZEN, got "
            f"{[account['status'] for account in thawed]}"
        )
        assert all(account["frozen_at"] is None for account in thawed)

        september = open_second_cycle()
        assert september["cycle_index"] == closed["cycle_index"] + 1

        replay = read_custody_account(ctx["reserve"]["id"])
        accepted = get_success_data(
            api_client.create_ledger_entry(
                create_ledger_entry_payload(
                    partner_id,
                    replay["id"],
                    replay["version"],
                    entry_type="RESERVE_FUND",
                    amount_cents=50_000,
                    effective_at="2026-09-01T00:00:00Z",
                ),
                PO,
            )
        )
        assert accepted["amount_cents"] == 50_000, (
            "the same amount, on the same account, at the same instant: refused before the "
            "checkpoint and accepted after it"
        )
        final = read_custody_account(ctx["reserve"]["id"])
        assert final["balance_cents"] == 556_250
        assert final["status"] == "ACTIVE"
