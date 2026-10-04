"""Medical record capture, verification tickets, the reject/resubmit cycle,
supersession, and dispute review loops."""
from test_helpers import (
    ApiErrorId,
    add_record_item,
    add_verified_item,
    approve_item,
    create_record_item_payload,
    enroll_member,
    get_member,
    list_item_tickets,
    make_member_headers,
    open_dispute,
    open_ticket_for_item,
    reject_item,
    set_clock,
    setup_member_with_verified_cognitive_condition,
    validate_error,
    validate_paginated,
    validate_success,
)


def _verify_item(api, member_id, item_id, verifier_headers):
    ticket = open_ticket_for_item(member_id, item_id, api=api)
    return validate_success(
        api.resolve_verification_ticket(
            ticket["id"], {"decision": "APPROVE", "decision_note": "ok"}, verifier_headers
        ),
        expected_status=200,
    )


class TestRejectResubmitCycle:
    def test_resubmit_returns_item_to_pending_with_incremented_round(self, api, verifier_headers):
        """PRD §3.3: "Resubmission returns the item to `PENDING_VERIFICATION` and
        opens a new ticket whose `submission_round` is the previous maximum round
        for that item plus one; an `AuditEvent` with action `RECORD_RESUBMIT` is
        appended."

        Design: Difficulty/non_linear_state_machine/record_item_reject_resubmit_cycle_increments_submission_round
        """
        set_clock(api=api)
        member = enroll_member(full_name="Rita Round", email="rita@x.com", dob="1992-02-02", api=api)
        item = add_record_item(
            member["id"], api=api, item_kind="ALLERGY", label="Peanuts",
            detail="anaphylaxis", severity="CRITICAL", provider_document_ref="doc-r1",
        )
        t1 = open_ticket_for_item(member["id"], item["id"], api=api)
        validate_success(
            api.resolve_verification_ticket(
                t1["id"], {"decision": "REJECT", "decision_note": "illegible scan"}, verifier_headers
            )
        )
        item_after_reject = validate_success(
            api.get_record_item(member["id"], item["id"], make_member_headers(member["id"]))
        )
        assert item_after_reject["status"] == "REJECTED"

        validate_success(
            api.submit_record_item_for_verification(
                member["id"], item["id"],
                {"provider_document_ref": "doc-r2-better-scan"},
                make_member_headers(member["id"]),
            )
        )
        item_after_resubmit = validate_success(
            api.get_record_item(member["id"], item["id"], make_member_headers(member["id"]))
        )
        assert item_after_resubmit["status"] == "PENDING_VERIFICATION", (
            "the cycle returned to the initial state"
        )
        tickets = list_item_tickets(member["id"], item["id"], api=api)
        assert len(tickets) == 2, f"expected 2 tickets after resubmission, got {len(tickets)}"
        t1_after = next(t for t in tickets if t["id"] == t1["id"])
        assert t1_after["status"] == "REJECTED", "old ticket terminal, unchanged"
        t2 = next(t for t in tickets if t["id"] != t1["id"])
        assert t2["submission_round"] == 2
        assert t2["status"] == "OPEN"

    def test_second_round_approve_completes_the_cycle(self, api, verifier_headers):
        """PRD §3.3: "The loop is bounded only by verifier decisions."
        PRD §3.3: "Approval — decision `APPROVE` — requires the ticket to be `OPEN`
        and moves the underlying item from `PENDING_VERIFICATION` to `VERIFIED`
        while the ticket becomes `APPROVED`; the member's `has_cognitive_condition`
        is recomputed (and can flip true when the approved item is a `COGNITIVE`
        condition), `record_revision` increments, the member's `version` increments
        by 1, and an `AuditEvent` with action `RECORD_VERIFY` is appended."

        Design: Difficulty/non_linear_state_machine/record_item_reject_resubmit_cycle_increments_submission_round
        """
        set_clock(api=api)
        member = enroll_member(full_name="Rita Second", email="rita2@x.com", dob="1992-02-02", api=api)
        item = add_record_item(member["id"], api=api, item_kind="ALLERGY", label="Peanuts")
        reject_item(member["id"], item["id"], api=api)
        validate_success(
            api.submit_record_item_for_verification(
                member["id"], item["id"], {"provider_document_ref": "doc-better"},
                make_member_headers(member["id"]),
            )
        )
        t2 = open_ticket_for_item(member["id"], item["id"], api=api)
        assert t2["submission_round"] == 2
        validate_success(
            api.resolve_verification_ticket(
                t2["id"], {"decision": "APPROVE", "decision_note": "ok"}, verifier_headers
            )
        )
        item = validate_success(api.get_record_item(member["id"], item["id"], make_member_headers(member["id"])))
        assert item["status"] == "VERIFIED"
        ticket = validate_success(api.get_verification_ticket(t2["id"], verifier_headers))
        assert ticket["status"] == "APPROVED"


class TestTicketFilteredList:
    def test_tickets_filtered_list_reverse_reachable_from_item(self, api, verifier_headers):
        """PRD §3.3: "Tickets expose the verifier's round history for an item —
        each resubmission adds another round."
        PRD §4 lists `GET /medical-id/verification-tickets` as "List verification
        tickets (verifier queue)".

        Design: Corner/endpoints/tickets_filtered_list_reverse_reachable_from_item
        """
        set_clock(api=api)
        member = enroll_member(full_name="Tina Ticket", email="tina@x.com", dob="1990-10-10", api=api)
        item = add_record_item(
            member["id"], api=api, item_kind="CONDITION", label="HTN",
            detail="bp", severity="MEDIUM", provider_document_ref="doc-h1",
        )
        t1 = open_ticket_for_item(member["id"], item["id"], api=api)
        validate_success(
            api.resolve_verification_ticket(
                t1["id"], {"decision": "REJECT", "decision_note": "blurry"}, verifier_headers
            )
        )
        validate_success(
            api.submit_record_item_for_verification(
                member["id"], item["id"], {"provider_document_ref": "doc-h2"},
                make_member_headers(member["id"]),
            )
        )
        resp = api.list_verification_tickets(verifier_headers, params={"record_item_id": item["id"]})
        data, _meta = validate_paginated(resp)
        assert len(data) == 2, f"expected exactly 2 tickets, got {len(data)}"
        rounds = sorted(t["submission_round"] for t in data)
        assert rounds == [1, 2]
        by_round = {t["submission_round"]: t for t in data}
        assert by_round[1]["status"] == "REJECTED"
        assert by_round[2]["status"] == "OPEN"


class TestSupersede:
    def test_supersede_from_pending_returns_invalid_state(self, api):
        """PRD §3.3: "Supersession is how a member corrects an already-`VERIFIED`
        item: the request supplies `replacement_label`, `replacement_detail`, fresh
        `provider_document_ref`, and — because supersession mutates derived fields
        on the member — the OCC token `expected_member_version` per §2.8."
        PRD §2.5: "State-machine from-state checks — `ERR_INVALID_STATE` when the
        target entity is not in the state the transition requires (for example,
        confirming an order that is not `PENDING`, engraving one that is not
        `CONFIRMED`, resolving a ticket that is not `OPEN`, or resolving a dispute
        that is not `UNDER_REVIEW`)."

        Design: Corner/state_machines/supersede_from_pending_returns_invalid_state
        """
        set_clock(api=api)
        member = enroll_member(full_name="Pend Pete", email="pete@x.com", dob="1983-03-03", api=api)
        item = add_record_item(
            member["id"], api=api, item_kind="ALLERGY", label="Latex",
            detail="gloves", severity="MEDIUM", provider_document_ref="doc-lx",
        )
        fresh = get_member(member["id"], api=api)
        resp = api.supersede_record_item(
            member["id"], item["id"],
            {
                "replacement_label": "Latex2",
                "replacement_detail": "x",
                "provider_document_ref": "doc-lx2",
                "expected_member_version": fresh["version"],
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        item_after = validate_success(
            api.get_record_item(member["id"], item["id"], make_member_headers(member["id"]))
        )
        assert item_after["status"] == "PENDING_VERIFICATION"

    def test_derived_has_cognitive_condition_reconciles_on_supersede(self, api):
        """PRD §3.3: "On the member, `record_revision` increments, `version`
        increments by 1, and `has_cognitive_condition` is recomputed — it can flip
        false if the superseded item was the member's last verified `COGNITIVE`
        condition."
        PRD §3.3: "The old item moves `VERIFIED` → `SUPERSEDED`; a brand-new
        item is created in `PENDING_VERIFICATION` carrying the replacement label
        and detail, with `item_kind` and `severity` copied from the superseded
        item and `condition_kind` reset to the `GENERAL` default — supersede
        payloads never carry a `condition_kind`; a fresh ticket opens for the
        replacement."

        Design: Corner/cross_cutting_layers/derived_has_cognitive_condition_reconciles_on_supersede
        """
        member, item = setup_member_with_verified_cognitive_condition(api=api)
        assert member["has_cognitive_condition"] is True

        fresh = get_member(member["id"], api=api)
        replacement = validate_success(
            api.supersede_record_item(
                member["id"], item["id"],
                {
                    "replacement_label": "TBI resolved",
                    "replacement_detail": "updated",
                    "provider_document_ref": "doc-tbi2",
                    "expected_member_version": fresh["version"],
                },
                make_member_headers(member["id"]),
            )
        )
        assert replacement["status"] == "PENDING_VERIFICATION"
        assert replacement["condition_kind"] == "GENERAL", (
            "supersede payloads never carry a condition_kind; the replacement resets to GENERAL"
        )
        after = get_member(member["id"], api=api)
        assert after["has_cognitive_condition"] is False, (
            "the only cognitive item left VERIFIED; the recomputation counts only VERIFIED COGNITIVE items"
        )
        old = validate_success(
            api.get_record_item(member["id"], item["id"], make_member_headers(member["id"]))
        )
        assert old["status"] == "SUPERSEDED"

    def test_supersede_with_correct_replacement_fields_opens_new_ticket(self, api, verifier_headers):
        """PRD §3.3: "The old item moves `VERIFIED` → `SUPERSEDED`; a brand-new
        item is created in `PENDING_VERIFICATION` carrying the replacement label
        and detail, with `item_kind` and `severity` copied from the superseded
        item and `condition_kind` reset to the `GENERAL` default — supersede
        payloads never carry a `condition_kind`; a fresh ticket opens for the
        replacement."

        Design: Corner/cross_cutting_layers/derived_has_cognitive_condition_reconciles_on_supersede
        """
        member, item = setup_member_with_verified_cognitive_condition(api=api)
        fresh = get_member(member["id"], api=api)
        replacement = validate_success(
            api.supersede_record_item(
                member["id"], item["id"],
                {
                    "replacement_label": "TBI resolved",
                    "replacement_detail": "updated",
                    "provider_document_ref": "doc-tbi2",
                    "expected_member_version": fresh["version"],
                },
                make_member_headers(member["id"]),
            )
        )
        assert replacement["item_kind"] == item["item_kind"], "item_kind copied from superseded item"
        assert replacement["severity"] == item["severity"], "severity copied from superseded item"
        assert replacement["label"] == "TBI resolved"
        assert replacement["detail"] == "updated"
        tickets = list_item_tickets(member["id"], replacement["id"], api=api)
        assert len(tickets) == 1 and tickets[0]["status"] == "OPEN"
        assert tickets[0]["submission_round"] == 1


class TestDisputeReviewLoop:
    def _dispute_setup(self, api):
        set_clock(api=api)
        member = enroll_member(full_name="Drew Dispute", email="drew@x.com", dob="1985-07-07", api=api)
        item = add_verified_item(
            member["id"], api=api, item_kind="MEDICATION", label="Warfarin 5mg",
            detail="daily", severity="HIGH", provider_document_ref="doc-w1",
        )
        dispute = open_dispute(member["id"], item["id"], api=api, claim_text="dose is 2mg not 5mg")
        return member, item, dispute

    def test_review_loop_return_to_queue_before_corrected_resolution(self, api, verifier_headers):
        """PRD §3.9: "A claim can be handed back — `UNDER_REVIEW` → `OPEN` with
        action `DISPUTE_RETURN` — for another round."
        PRD §3.9: "resolution `CORRECTED` moves it to `RESOLVED_CORRECTED` and, in
        the same operation, supersedes the disputed item through the full supersede
        side-effect set of §3.3 — the old item becomes `SUPERSEDED`, a replacement
        item is created in `PENDING_VERIFICATION` with a fresh ticket, the member's
        `record_revision` increments, `has_cognitive_condition` is recomputed, and
        the member's `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/dispute_review_loop_return_to_queue_before_corrected_resolution
        """
        member, item, dispute = self._dispute_setup(api)
        revision_at_open = get_member(member["id"], api=api)["record_revision"]

        validate_success(api.claim_dispute_for_review(dispute["id"], verifier_headers))
        returned = validate_success(api.return_dispute_to_queue(dispute["id"], verifier_headers))
        assert returned["status"] == "OPEN"
        reclaimed = validate_success(api.claim_dispute_for_review(dispute["id"], verifier_headers))
        assert reclaimed["status"] == "UNDER_REVIEW"
        resolved = validate_success(
            api.resolve_dispute(
                dispute["id"],
                {"resolution": "CORRECTED", "resolution_note": "provider confirms 2mg"},
                verifier_headers,
            )
        )
        assert resolved["status"] == "RESOLVED_CORRECTED"

        old_item = validate_success(
            api.get_record_item(member["id"], item["id"], make_member_headers(member["id"]))
        )
        assert old_item["status"] == "SUPERSEDED"
        resp = api.list_record_items(member["id"], make_member_headers(member["id"]))
        items, _ = validate_paginated(resp)
        replacements = [
            i for i in items
            if i["id"] != item["id"] and i["status"] == "PENDING_VERIFICATION"
        ]
        assert len(replacements) == 1, "a replacement item is created in PENDING_VERIFICATION"
        tickets = list_item_tickets(member["id"], replacements[0]["id"], api=api)
        assert len(tickets) == 1 and tickets[0]["status"] == "OPEN"
        assert tickets[0]["submission_round"] == 1
        after = get_member(member["id"], api=api)
        assert after["record_revision"] > revision_at_open, (
            "record_revision advanced beyond its value at dispute open"
        )

    def test_returned_dispute_can_be_dismissed_from_open(self, api, verifier_headers):
        """PRD §3.9: "An `OPEN` dispute may instead be dismissed outright, moving
        `OPEN` → `DISMISSED` with action `DISPUTE_DISMISS`. The three terminal
        states are `RESOLVED_UPHELD`, `RESOLVED_CORRECTED`, and `DISMISSED`."

        Design: Difficulty/non_linear_state_machine/dispute_review_loop_return_to_queue_before_corrected_resolution
        """
        member, item, dispute = self._dispute_setup(api)
        validate_success(api.claim_dispute_for_review(dispute["id"], verifier_headers))
        returned = validate_success(api.return_dispute_to_queue(dispute["id"], verifier_headers))
        assert returned["status"] == "OPEN"
        dismissed = validate_success(api.dismiss_dispute(dispute["id"], verifier_headers))
        assert dismissed["status"] == "DISMISSED"
        # The disputed item is untouched by a dismissal.
        item_after = validate_success(
            api.get_record_item(member["id"], item["id"], make_member_headers(member["id"]))
        )
        assert item_after["status"] == "VERIFIED"


class TestVerifyCascade:
    def test_verify_cognitive_item_cascades_to_flag_eligibility_and_escalated_access(
        self, api, admin_headers, verifier_headers, hotline_headers
    ):
        """PRD §3.3: "the member's `has_cognitive_condition` is recomputed (and can
        flip true when the approved item is a `COGNITIVE` condition)".
        PRD §3.6: "The wandering/cognitive override then widens the scope: when the
        member's `has_cognitive_condition` is true, directives with `release_scope`
        `EMERGENCY_ONLY` are also disclosed regardless of tier, and contacts are
        disclosed even to a `BASIC` credential."
        PRD §3.6: "A granted access also flips every in-scope `STORED` directive to
        `RELEASED` (a one-way disclosure marker; the directive remains readable) and
        appends an `AuditEvent` with action `DIRECTIVE_RELEASE` for each."
        PRD §3.8: "Two eligibility constraints are enforced together, with
        violations rejected as `ERR_WANDERING_NOT_ELIGIBLE` (HTTP 409): the
        member's `has_cognitive_condition` must be true, and the member must not
        already have an `OPEN` case — at most one open case per member."

        Design: Difficulty/transitive_cascade/verify_cognitive_item_cascades_to_flag_eligibility_and_escalated_access
        """
        set_clock(api=api)
        member = enroll_member(full_name="Cara Cascade", email="cara@x.com", dob="1960-01-30", api=api)
        item = add_record_item(
            member["id"], api=api, item_kind="CONDITION", condition_kind="COGNITIVE",
            label="Dementia", detail="wanders", severity="HIGH", provider_document_ref="doc-c1",
        )
        from test_helpers import add_contact, add_directive, add_responder
        add_contact(member["id"], api=api, contact_name="Cara Daughter",
                    phone="+15550003333", priority_rank=1)
        directive = add_directive(member["id"], api=api, directive_type="HEALTHCARE_PROXY",
                                  document_ref="proxy-c", release_scope="EMERGENCY_ONLY")
        responder = add_responder(api=api, agency_name="County EMS",
                                  credential_code="EMS-B-777", access_tier="BASIC",
                                  expires_on="2027-01-01")

        # Pre-verification: wandering case is denied (flag still false).
        denied = api.create_wandering_case(
            member["id"], {"opened_via": "SELF_REPORT"}, hotline_headers
        )
        validate_error(denied, ApiErrorId.ERR_WANDERING_NOT_ELIGIBLE.value)

        # Hop 1 -> hop 2: verify flips has_cognitive_condition.
        _verify_item(api, member["id"], item["id"], verifier_headers)
        after = get_member(member["id"], api=api)
        assert after["has_cognitive_condition"] is True

        # Hop 2 -> hop 3 -> hop 4: escalated access releases the EMERGENCY_ONLY directive.
        from test_helpers import grant_access
        event = grant_access(responder, get_member(member["id"], api=api), api=api)
        assert event["is_escalated"] is True
        assert "CONTACTS" in event["disclosed_scope"]
        assert "DIRECTIVES" in event["disclosed_scope"]
        dir_after = validate_success(api.get_directive(directive["id"], admin_headers))
        assert dir_after["status"] == "RELEASED"

        # Eligibility now satisfied.
        case = validate_success(
            api.create_wandering_case(
                member["id"], {"opened_via": "HOTLINE_ESCALATION"}, hotline_headers
            ),
            expected_status=201,
        )
        assert case["status"] == "OPEN"

    def test_verify_cognitive_item_flips_flag_and_enables_case_open(
        self, api, verifier_headers, hotline_headers
    ):
        """PRD §3.3: "The flag `has_cognitive_condition` is true exactly when the
        member has at least one item with `status` `VERIFIED` whose
        `condition_kind` is `COGNITIVE`; a newly captured item is not yet verified,
        so capture alone never flips the flag true, though a capture that leaves
        the verified set unchanged may recompute it to the same value."

        Design: Difficulty/transitive_cascade/verify_cognitive_item_cascades_to_flag_eligibility_and_escalated_access
        """
        set_clock(api=api)
        member = enroll_member(full_name="Cara Flag", email="caraf@x.com", dob="1960-01-30", api=api)
        assert member["has_cognitive_condition"] is False
        item = add_record_item(
            member["id"], api=api, item_kind="CONDITION", condition_kind="COGNITIVE",
            label="Dementia", detail="wanders", severity="HIGH", provider_document_ref="doc-c1",
        )
        mid = get_member(member["id"], api=api)
        assert mid["has_cognitive_condition"] is False, "capture alone never flips the flag"
        _verify_item(api, member["id"], item["id"], verifier_headers)
        after = get_member(member["id"], api=api)
        assert after["has_cognitive_condition"] is True
        case = validate_success(
            api.create_wandering_case(
                member["id"], {"opened_via": "HOTLINE_ESCALATION"}, hotline_headers
            ),
            expected_status=201,
        )
        assert case["status"] == "OPEN"


class TestCancelCascade:
    def test_member_cancel_cascades_to_orders_disputes_links(self, api, admin_headers, verifier_headers):
        """PRD §3.2: "The cascade is comprehensive and identical from either source
        state: every `PENDING` `ProductOrder` is cancelled with a refund of its
        `price_cents` into the member's `wallet_credit_cents`; every `OPEN` or
        `UNDER_REVIEW` `Dispute` is dismissed; every `OPEN` `WanderingCase` is
        resolved with outcome `OTHER`; every `PENDING` reminder is cancelled; and
        every `ACTIVE` `GuardianLink` in which the member appears as either the
        dependent or the guardian is revoked."

        Design: Difficulty/transitive_cascade/member_cancel_cascades_to_orders_disputes_links
        """
        from test_helpers import (
            add_product,
            attach_guardian,
            confirm_order,
            list_member_reminders,
            make_guardian_headers,
            place_order,
        )

        set_clock(api=api)
        product = add_product(api=api, product_sku="BR-K", product_name="Kids Band",
                              base_price_cents=3000, max_engrave_chars=30)
        guardian = enroll_member(full_name="Gus Guard", email="gus@x.com", dob="1970-05-05", api=api)
        dependent = enroll_member(full_name="Dee Minor", email="dee@x.com", dob="2016-01-15", api=api)
        link = attach_guardian(dependent["id"], guardian["id"], relation_label="father", api=api)
        gh = make_guardian_headers(guardian["id"])
        item = add_record_item(
            dependent["id"], actor_headers=gh, api=api, item_kind="ALLERGY",
            label="Bee stings", detail="epi-pen", severity="CRITICAL", provider_document_ref="doc-bee",
        )
        dispute = open_dispute(dependent["id"], item["id"], actor_headers=gh, api=api,
                               claim_text="severity overstated")
        pending_order = place_order(
            dependent["id"], product["id"], actor_headers=gh, api=api,
            engraving_text="Dee - bee allergy", engrave_mode="MANUAL",
        )
        confirmed_order = place_order(
            dependent["id"], product["id"], actor_headers=gh, api=api,
            engraving_text="Dee backup band", engrave_mode="MANUAL",
        )
        confirm_order(dependent["id"], confirmed_order["id"], actor_headers=gh, api=api)

        cancelled = validate_success(api.cancel_member(dependent["id"], gh))
        assert cancelled["status"] == "CANCELLED"

        pending_after = validate_success(api.get_order(pending_order["id"], admin_headers))
        assert pending_after["status"] == "CANCELLED"
        confirmed_after = validate_success(api.get_order(confirmed_order["id"], admin_headers))
        assert confirmed_after["status"] == "CONFIRMED", (
            "the cascade is comprehensive over PENDING orders only; a CONFIRMED "
            "order is not in the cancel cascade's enumerated effects"
        )

        member_after = validate_success(api.get_member(dependent["id"], admin_headers))
        assert member_after["wallet_credit_cents"] == 3000, (
            "confirmed order refunded to wallet; got "
            f"{member_after['wallet_credit_cents']}"
        )

        dispute_after = validate_success(api.get_dispute(dispute["id"], verifier_headers))
        assert dispute_after["status"] == "DISMISSED"
        # Terminal lockdown: no further review transitions on a dismissed dispute.
        resp = api.claim_dispute_for_review(dispute["id"], verifier_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        link_after = validate_success(api.get_guardian_link(link["id"], admin_headers))
        assert link_after["status"] == "REVOKED"

        reminders = list_member_reminders(dependent["id"], api=api)
        pending_reminders = [r for r in reminders if r["status"] == "PENDING"]
        assert pending_reminders == [], (
            f"every PENDING reminder is cancelled; still pending: {pending_reminders}"
        )

    def test_cancel_also_cancels_pending_order_without_refund(self, api, admin_headers):
        """PRD §3.2: "every `PENDING` `ProductOrder` is cancelled with a refund of
        its `price_cents` into the member's `wallet_credit_cents`".
        PRD §3.4: "Cancelling a `PENDING` order moves it to `CANCELLED` with no
        financial side effects beyond an `AuditEvent` of action `ORDER_CANCEL`."

        Design: Difficulty/transitive_cascade/member_cancel_cascades_to_orders_disputes_links
        """
        from test_helpers import add_product, place_order

        set_clock(api=api)
        product = add_product(api=api, base_price_cents=3000)
        member = enroll_member(full_name="Cal Cancel", email="cal@x.com", dob="1980-01-01", api=api)
        order = place_order(member["id"], product["id"], api=api, engraving_text="Cal band")
        validate_success(api.cancel_member(member["id"], make_member_headers(member["id"])))
        order_after = validate_success(api.get_order(order["id"], admin_headers))
        assert order_after["status"] == "CANCELLED"
        member_after = validate_success(api.get_member(member["id"], admin_headers))
        assert member_after["wallet_credit_cents"] == 3000, (
            "the member-cancel cascade refunds the pending order's price to the wallet"
        )
