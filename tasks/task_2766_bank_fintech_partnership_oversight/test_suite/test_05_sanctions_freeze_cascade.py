"""One open sanctions hit freezes custody and blocks marketing approval; the
freeze outlives its cause until the next cycle close thaws it."""
from test_helpers import (
    COMPLIANCE_OFFICER_2,
    ApiErrorId,
    api_client,
    assert_same_instant,
    close_cycle,
    dispose_alert,
    file_marketing_review,
    get_success_data,
    make_compliance_officer_headers,
    raise_sanctions_alert,
    read_custody_account,
    read_partner,
    set_clock,
    setup_live_partner,
    validate_error,
)

CO_DECIDER = make_compliance_officer_headers(COMPLIANCE_OFFICER_2)


def _northwake_live():
    return setup_live_partner(
        partner_overrides={
            "legal_name": "Northwake Ledger Inc",
            "business_model": "PAYMENT_FACILITATION",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 30,
            "disclosed_complaints_per_10k": 2.00,
            "end_user_account_count": 4000,
        },
        agreement_overrides={"reserve_requirement_bps": 500},
        fbo_balance_cents=5_000_000,
        reserve_balance_cents=312_500,
    )


def _pending_material(ctx):
    """Filed before the alert, so its approval is pending when the posture flips."""
    return file_marketing_review(
        ctx["partner"]["id"],
        ctx["agreement"]["id"],
        material_type="AD",
        placement_channel="IN_APP",
        effective_from="2026-09-01T00:00:00Z",
        effective_until="2026-09-10T00:00:00Z",
    )


class TestSanctionsFreezeCascade:
    def test_a_single_sanctions_hit_freezes_custody_and_refuses_the_pending_approval(self):
        """A filing lands directly in `SUBMITTED` — there is no draft stage — with `review_round`
        at 1, an empty `change_requests` array, `decided_by_user_id` null. `APPROVE` moves the
        filing `SUBMITTED → APPROVED` and is the only branch that carries substantive gates: the partner's
        `oversight_posture` must be `OPEN` or `HEIGHTENED` (a `RESTRICTED` or `FROZEN` partner
        cannot get material approved, refused with `ERR_POSTURE_BLOCKS_MARKETING`).

        Design: Difficulty/transitive_cascade/sanctions_alert_cascade_freezes_custody_and_blocks_marketing_until_cycle_close
        """
        ctx = _northwake_live()
        partner_id = ctx["partner"]["id"]
        assert read_partner(partner_id)["oversight_posture"] == "OPEN"

        review = _pending_material(ctx)
        assert review["status"] == "SUBMITTED", "filing is the submission; there is no draft stage"
        assert review["risk_flags"] == []
        assert review["review_round"] == 1

        alert = raise_sanctions_alert(
            partner_id,
            triggered_at="2026-07-31T10:00:00Z",
            transaction_volume_cents=450_000,
            detection_note="OFAC screening hit on an inbound ACH originator name",
        )
        assert_same_instant(alert["sla_due_at"], "2026-08-01T10:00:00Z", "sla_due_at")

        partner = read_partner(partner_id)
        assert partner["open_sanctions_alert_count"] == 1
        assert partner["oversight_posture"] == "FROZEN"
        assert read_custody_account(ctx["fbo"]["id"])["status"] == "FROZEN"
        assert read_custody_account(ctx["reserve"]["id"])["status"] == "FROZEN"

        refused = api_client.decide_marketing_review(
            review["id"], {"decision": "APPROVE"}, CO_DECIDER
        )
        validate_error(refused, ApiErrorId.ERR_POSTURE_BLOCKS_MARKETING, 403)
        untouched = get_success_data(api_client.get_marketing_review(review["id"], CO_DECIDER))
        assert untouched["status"] == "SUBMITTED"
        assert untouched["review_round"] == 1

    def test_clearing_the_alert_recovers_the_posture_but_only_the_cycle_close_thaws_custody(self):
        """Note carefully that the posture may drop off `FROZEN` at that moment but the custody
        accounts do **not** thaw inside this request: unfreezing is deferred to the next oversight
        cycle close. Symmetrically, a partner whose recomputed posture is no longer `FROZEN` has
        each of its `FROZEN` custody accounts returned to `ACTIVE`, setting `frozen_at` back to null
        and incrementing that account's `version` by 1.

        Design: Difficulty/transitive_cascade/sanctions_alert_cascade_freezes_custody_and_blocks_marketing_until_cycle_close
        """
        ctx = _northwake_live()
        partner_id = ctx["partner"]["id"]
        review = _pending_material(ctx)
        alert = raise_sanctions_alert(
            partner_id,
            triggered_at="2026-07-31T10:00:00Z",
            transaction_volume_cents=450_000,
            detection_note="OFAC screening hit on an inbound ACH originator name",
        )
        validate_error(
            api_client.decide_marketing_review(review["id"], {"decision": "APPROVE"}, CO_DECIDER),
            ApiErrorId.ERR_POSTURE_BLOCKS_MARKETING,
            403,
        )

        disposed = dispose_alert(
            alert["id"],
            "CLEARED",
            disposition_note="false positive confirmed: originator name mismatch on secondary review",
        )
        assert disposed["disposition"] == "CLEARED"
        assert disposed["sla_breach_count"] == 0

        recovered = read_partner(partner_id)
        assert recovered["open_sanctions_alert_count"] == 0
        assert recovered["oversight_posture"] == "OPEN", "the cause has been removed"
        assert read_custody_account(ctx["fbo"]["id"])["status"] == "FROZEN", (
            "the freeze is not auto-reverted when the posture recovers"
        )
        assert read_custody_account(ctx["reserve"]["id"])["status"] == "FROZEN"

        set_clock("2026-09-01T00:00:00Z")
        closed = close_cycle(ctx["cycle"]["id"])
        assert closed["status"] == "CLOSED"
        assert closed["partners_frozen_count"] == 0
        assert closed["marketing_approvals_expired_count"] == 0
        assert closed["growth_breach_partner_count"] == 0

        assert read_custody_account(ctx["fbo"]["id"])["status"] == "ACTIVE"
        assert read_custody_account(ctx["reserve"]["id"])["status"] == "ACTIVE"
        final = read_partner(partner_id)
        assert final["required_reserve_cents"] == 250_000, final["required_reserve_cents"]
        assert final["reserve_shortfall_cents"] == 0
        assert final["oversight_posture"] == "OPEN"
