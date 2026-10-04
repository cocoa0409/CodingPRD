"""Upgrade prompts: creation, frozen price delta, acknowledgment, decline
downgrade, and the gates they place on submit-review."""
from test_helpers import (
    add_form,
    carryforward_item,
    create_account,
    create_return,
    create_snapshot,
    get_pending_prompt,
    get_return,
    import_snapshot,
    list_prompts,
    make_taxpayer_headers,
    remove_form,
    seed_catalog,
    setup_return_with_forms,
    submit_review,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def _setup_return_with_sch_d_prompt(email):
    """Account + DRAFT return with F1040 + SCH_D and a PENDING FREE->PREMIER
    prompt. Returns (account, ret, prompt)."""
    account, ret = setup_return_with_forms(
        forms=("F1040", "SCH_D"), email=email, resolve_prompt=None
    )
    prompt = get_pending_prompt(ret)
    assert prompt is not None, "Setup failed: expected a PENDING prompt"
    return account, ret, prompt


class TestFrozenPriceDelta:
    def test_price_delta_frozen_when_minimum_later_collapses(self, api):
        """PRD §3.2: "The prompt opens in `PENDING` status, recording
        `from_tier` (the return's tier at that moment), `to_tier` (the freshly
        computed minimum), and a `price_delta_cents` frozen at creation as the
        destination tier's `price_cents` minus the source tier's `price_cents`
        — this frozen figure is what the taxpayer is asked to acknowledge, so
        a later catalog price change cannot move the number under them."

        Design: Corner/entities/prompt_price_delta_frozen_at_creation
        """
        account, ret, prompt = _setup_return_with_sch_d_prompt(
            unique_email("ent4")
        )
        assert prompt["price_delta_cents"] == 12999
        # Removing SCH_D collapses the minimum back to FREE and supersedes the
        # pending prompt.
        sch_d = [f for f in api.list_forms(
            ret.id, make_taxpayer_headers(account["id"])
        ).json()["data"] if f["form_code"] == "SCH_D"][0]
        remove_form(ret, sch_d["id"])
        prompts = {
            p["id"]: p
            for p in list_prompts(ret)
        }
        assert prompts[prompt["id"]]["price_delta_cents"] == 12999
        assert prompts[prompt["id"]]["status"] == "SUPERSEDED"
        assert get_return(ret)["minimum_required_tier"] == "FREE"


class TestAcknowledgeGatesReview:
    def test_pending_prompt_blocks_submit_review_until_acknowledged(self, api):
        """PRD §3.6: "Any outstanding `PENDING` upgrade prompt blocks review
        with `ERR_UPGRADE_ACK_REQUIRED` (HTTP 409) — the price change must be
        acknowledged or decline-downgraded first, and this gate is evaluated
        before the free-file gate."

        Design: Difficulty/cross_entity_state_dependency/prompt_resolution_gates_return_review
        """
        account, ret, prompt = _setup_return_with_sch_d_prompt(
            unique_email("xes2")
        )
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UPGRADE_ACK_REQUIRED)
        assert get_return(ret)["status"] == "DRAFT"
        # Acknowledge and retry.
        resp = api.acknowledge_prompt(
            ret.id, prompt["id"], ret.version, make_taxpayer_headers(account["id"])
        )
        validate_success(resp)
        ret.refresh(get_return(ret))
        data = submit_review(ret)
        assert data["status"] == "READY_FOR_REVIEW"

    def test_acknowledge_ratchets_tier_and_reprices(self, api):
        """PRD §3.2: "**Acknowledging** moves the prompt `PENDING` →
        `ACKNOWLEDGED`, sets its `acknowledged` flag true, ratchets the
        return's `current_tier` up to the prompt's `to_tier`, recomputes
        `upgrade_prompt_pending` (it clears when this was the last pending
        prompt), and reprices the return at the new tier."

        Design: Difficulty/cross_entity_state_dependency/prompt_resolution_gates_return_review
        """
        account, ret, prompt = _setup_return_with_sch_d_prompt(
            unique_email("xes2b")
        )
        resp = api.acknowledge_prompt(
            ret.id, prompt["id"], ret.version, make_taxpayer_headers(account["id"])
        )
        acknowledged = validate_success(resp)
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged"] is True
        after = get_return(ret)
        assert after["current_tier"] == "PREMIER"
        assert after["total_fees_due_cents"] == 12999
        assert after["upgrade_prompt_pending"] is False


class TestDeclineDowngrade:
    def test_decline_refused_while_imported_form_requires_higher_tier(self, api):
        """PRD §3.2: "If any `ACTIVE` form with `source` `IMPORTED` still
        requires a tier above the prompt's `from_tier`, the decline is refused
        with `ERR_DOWNGRADE_WOULD_LEAVE_GAP` (HTTP 409); the filer must remove
        those imported forms explicitly first."

        Design: Corner/state_machines/decline_blocked_by_imported_carryforward_gap
        """
        seed_catalog(
            tiers=("FREE", "PREMIER"), forms=("F1040", "F4562")
        )
        account = create_account(email=unique_email("sm4"))
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        snapshot = create_snapshot(
            account,
            2024,
            [carryforward_item("DEPRECIATION", "truck", 50000)],
        )
        import_snapshot(account, snapshot["id"], ret)
        prompt = get_pending_prompt(ret)
        assert prompt is not None, "Setup failed: expected a PENDING prompt"
        assert prompt["to_tier"] == "PREMIER"
        resp = api.decline_prompt(
            ret.id, prompt["id"], ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DOWNGRADE_WOULD_LEAVE_GAP)
        prompts = {p["id"]: p for p in list_prompts(ret)}
        assert prompts[prompt["id"]]["status"] == "PENDING"
        assert get_return(ret)["minimum_required_tier"] == "PREMIER"

    def test_double_acknowledge_rejected(self, api):
        """PRD §2.8: "a target resource in an illegal from-state for the
        requested transition is rejected with `ERR_INVALID_STATE` (HTTP 409) —
        this covers terminal-state lockdowns, a direct file attempt on an
        `AMENDED` return, and double-resolution of an already-settled prompt,
        among others."

        Design: Corner/state_machines/prompt_double_acknowledge_rejected
        """
        account, ret, prompt = _setup_return_with_sch_d_prompt(
            unique_email("sm3")
        )
        resp = api.acknowledge_prompt(
            ret.id, prompt["id"], ret.version, make_taxpayer_headers(account["id"])
        )
        validate_success(resp)
        ret.refresh(get_return(ret))
        resp = api.acknowledge_prompt(
            ret.id, prompt["id"], ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_return(ret)
        assert after["total_fees_due_cents"] == 12999
        assert after["current_tier"] == "PREMIER"


class TestMinimumTierConservation:
    def test_add_remove_cycle_restores_minimum_and_clears_prompts(self, api):
        """PRD §3.2: "An empty form set classifies as `FREE`." PRD §3.2: "At
        most one prompt per return is ever `PENDING`; creating a newer one
        automatically moves the previous `PENDING` prompt to `SUPERSEDED`."

        Design: Difficulty/compensating_invariant/minimum_tier_conservation_across_add_remove_cycle
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("inv2")
        )
        sch_c = add_form(ret, "SCH_C", 500000)
        after_add = get_return(ret)
        assert after_add["minimum_required_tier"] == "SELF_EMPLOYED"
        assert after_add["upgrade_prompt_pending"] is True
        remove_form(ret, sch_c["id"])
        after_remove = get_return(ret)
        assert after_remove["minimum_required_tier"] == "FREE"
        assert after_remove["free_file_eligible"] is True
        assert after_remove["upgrade_prompt_pending"] is False
        assert after_remove["current_tier"] == "FREE"

    def test_removed_form_row_retained_with_removed_status(self, api):
        """PRD §3.2: "The system considers only `ACTIVE` forms (removed rows
        are excluded from classification and refund math but retained for
        audit) and takes the highest `tier_rank` among the `minimum_tier`
        values of their form specs; the tier at that rank becomes the return's
        `minimum_required_tier`."

        Design: Difficulty/compensating_invariant/minimum_tier_conservation_across_add_remove_cycle
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("inv2b")
        )
        sch_c = add_form(ret, "SCH_C", 500000)
        remove_form(ret, sch_c["id"])
        forms = api.list_forms(ret.id, make_taxpayer_headers(account["id"]))
        rows = validate_success(forms)
        removed = [f for f in rows if f["id"] == sch_c["id"]]
        assert len(removed) == 1
        assert removed[0]["status"] == "REMOVED"
