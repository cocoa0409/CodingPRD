"""Corner cases of the consistency model: every cascade a write triggers is complete before
that write's own response is returned, so the first read after a write is already final and the
version token it carries is already the post-cascade version."""
from test_helpers import (
    CO,
    PO,
    RC,
    api_client,
    assert_one_decimal_score,
    assert_same_instant,
    create_agreement_payload,
    create_diligence_review_payload,
    create_partner,
    get_success_data,
    oversight_summary,
    raise_alert,
    read_custody_account,
    read_partner,
    seed_reserve_balance,
    setup_contracted_partner,
    validate_paginated,
)


class TestTheAlertCascadeIsCompleteWhenTheAlertIsReturned:
    def test_the_first_read_after_the_alert_already_shows_the_frozen_posture_and_frozen_custody(self):
        """A single open sanctions alert satisfies the most severe rung of the posture ladder, so
        the re-derived `oversight_posture` becomes `FROZEN`, which in turn freezes both of that
        partner's custody accounts inside the same request. There is no fixed-point iteration and
        no second pass: the posture value written later in the same pass is not fed back into the
        reserve formula.

        Design: Corner/consistency_model/a_single_alert_completes_the_whole_posture_cascade_before_its_own_response_is_returned
        """
        ctx = setup_contracted_partner(
            partner_overrides={
                "legal_name": "Pellworth Deposits Inc",
                "business_model": "DEPOSIT_WALLET",
                "end_user_account_count": 25_000,
            }
        )
        partner_id = ctx["partner"]["id"]
        seed_reserve_balance(partner_id, ctx["reserve"], 312_500)

        before = read_partner(partner_id)
        assert before["oversight_posture"] == "OPEN"
        assert before["open_sanctions_alert_count"] == 0
        assert before["required_reserve_cents"] == 312_500, (
            "the flat absolute floor is the binding base while the end-user account is empty, and "
            "the top-up's own pass read the HEIGHTENED the execution shortfall had written, so "
            f"250000 is scaled by 1.25, got {before['required_reserve_cents']}"
        )
        assert before["reserve_shortfall_cents"] == 0

        alert = raise_alert(
            partner_id,
            alert_type="SANCTIONS_HIT",
            triggered_at="2026-08-01T00:00:00Z",
            detection_note="an outbound wire beneficiary matched a sanctions list entry",
        )
        assert alert["disposition"] == "OPEN"
        assert alert["sla_breach_count"] == 0
        assert_same_instant(alert["sla_due_at"], "2026-08-02T00:00:00Z", "sla_due_at")

        first = read_partner(partner_id)
        assert first["oversight_posture"] == "FROZEN", (
            "the very first read after the write is final: no polling, no delay and no pending "
            f"marker, got {first['oversight_posture']}"
        )
        assert first["open_sanctions_alert_count"] == 1
        assert first["required_reserve_cents"] == 312_500, (
            "raising an alert is not one of the reserve recomputation triggers and the FROZEN the "
            "alert wrote is never fed back into the reserve formula, so the requirement is not "
            f"rescaled to 625000, got {first['required_reserve_cents']}"
        )
        assert first["reserve_shortfall_cents"] == 0, (
            "312500 is still covered exactly by the 312500 sitting in the reserve"
        )

        second = read_partner(partner_id)
        assert second["oversight_posture"] == first["oversight_posture"]
        assert second["required_reserve_cents"] == first["required_reserve_cents"]
        assert second["reserve_shortfall_cents"] == first["reserve_shortfall_cents"]
        assert second["version"] == first["version"], (
            "a repeated read is identical, so there is no eventual-consistency window to observe"
        )

        accounts, acc_meta = validate_paginated(
            api_client.list_custody_accounts(PO, params={"partner_id": partner_id})
        )
        assert acc_meta["total_count"] == 2
        assert all(account["status"] == "FROZEN" for account in accounts), (
            "the cross-entity leg of the cascade landed in the same request as the alert insert, "
            f"got {[account['status'] for account in accounts]}"
        )
        assert read_custody_account(ctx["reserve"]["id"])["status"] == "FROZEN"

        alerts, alerts_meta = validate_paginated(
            api_client.list_alerts(PO, params={"partner_id": partner_id})
        )
        assert alerts_meta["total_count"] == 1
        assert_same_instant(alerts[0]["sla_due_at"], "2026-08-02T00:00:00Z", "listed sla_due_at")

        summary = oversight_summary(partner_id)
        assert summary["oversight_posture"] == "FROZEN"
        assert summary["required_reserve_cents"] == 312_500, (
            "the computed read endpoint agrees with the stored row, so it is derived from the same "
            "committed state rather than from a stale snapshot"
        )
        assert summary["open_sanctions_alert_count"] == 1


class TestTheVersionReadAfterAWriteIsAlreadyPostCascade:
    def test_the_token_read_immediately_after_the_decision_is_accepted_by_the_next_write(self):
        """A successful pass advances the partner `IN_DILIGENCE → DILIGENCE_PASSED`, copies the
        file's `tier` onto the partner's `capability_tier` and the file's `composite_score` onto the
        partner's `latest_composite_score`, and increments the partner's `version` by 1. Each of the
        four contributions is then formed **and rounded on its own** to two decimal places, half up:
        the business-model score weighted at 0.20, the funding score weighted at 0.25, the
        compliance-capability score weighted at 0.35, and the effective complaint-history score
        weighted at 0.20.

        Design: Corner/consistency_model/the_version_a_client_reads_immediately_after_a_write_is_already_the_post_cascade_version
        """
        partner = create_partner(legal_name="Rookmoor Credit Inc", business_model="LENDING")
        partner_id = partner["id"]
        review = get_success_data(
            api_client.create_diligence_review(
                create_diligence_review_payload(
                    partner_id,
                    partner["version"],
                    review_type="INITIAL",
                    business_model_score=80,
                    funding_score=80,
                    compliance_capability_score=90,
                    complaint_history_score=85,
                ),
                PO,
            )
        )
        submitted = get_success_data(api_client.submit_diligence_review(review["id"], {}, PO))
        assert submitted["status"] == "SUBMITTED"

        pre = read_partner(partner_id)
        assert pre["status"] == "IN_DILIGENCE", (
            "submitting the first file is what opens diligence"
        )
        assert pre["capability_tier"] == "UNRATED", (
            "the mirrored tier is untouched until a decision exists"
        )
        pre_version = pre["version"]

        decided = get_success_data(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, CO)
        )
        assert decided["status"] == "PASSED"
        assert decided["effective_complaint_history_score"] == 85, (
            "an INITIAL review takes the submitted complaint_history_score verbatim"
        )
        assert_one_decimal_score(decided["composite_score"], "composite_score")
        assert decided["composite_score"] == 84.5, (
            "16.00 plus 20.00 plus 31.50 plus 17.00, each contribution rounded on its own, got "
            f"{decided['composite_score']}"
        )
        assert decided["tier"] == "TIER_2", (
            "84.5 sits below the inclusive TIER_1 floor of 85.0"
        )

        post = read_partner(partner_id)
        assert post["status"] == "DILIGENCE_PASSED", (
            "the partner mirror is written inside the decision's own transaction, so the first "
            f"read already shows it, got {post['status']}"
        )
        assert post["latest_composite_score"] == 84.5
        assert post["capability_tier"] == "TIER_2"
        assert post["version"] == pre_version + 1, (
            "exactly one version bump for the whole cascade, not one bump per denormalised field, "
            f"got {post['version']} against {pre_version}"
        )

        agreement = get_success_data(
            api_client.create_agreement(
                create_agreement_payload(partner_id, post["version"]), PO
            )
        )
        assert agreement["status"] == "DRAFT", (
            "no invisible write happened between the decision and the read, so the token the "
            "client just observed is still the partner's current version"
        )
        routed = get_success_data(
            api_client.submit_agreement_for_approval(agreement["id"], {}, PO)
        )
        assert routed["status"] == "PENDING_RISK_APPROVAL", (
            "the mirrored tier is what makes the routing legal, and it was already in place"
        )
        executed = get_success_data(
            api_client.decide_agreement_risk(agreement["id"], {"decision": "EXECUTE"}, RC)
        )
        assert executed["status"] == "EXECUTED"

        reviews, meta = validate_paginated(
            api_client.list_diligence_reviews(PO, params={"partner_id": partner_id})
        )
        assert meta["total_count"] == 1
        assert reviews[0]["composite_score"] == 84.5, (
            "the list projection agrees with both the write response and the partner mirror, so "
            "no reader ever sees an intermediate state"
        )
        assert reviews[0]["tier"] == "TIER_2"
