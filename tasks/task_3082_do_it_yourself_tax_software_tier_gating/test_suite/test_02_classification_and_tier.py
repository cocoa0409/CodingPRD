"""Classification, free-file eligibility, tier selection, and OCC."""
from test_helpers import (
    TEST_USERS,
    add_form,
    create_account,
    create_return,
    get_pending_prompt,
    get_return,
    make_taxpayer_headers,
    seed_catalog,
    setup_return_with_forms,
    setup_submitted_return,
    submit_review,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import FREE_FILE_AGI_LIMIT_CENTS


class TestFreeFileIncomeBoundary:
    def test_agi_exactly_at_limit_stays_free_file_eligible(self, api):
        """PRD §2.5: "The free-file income ceiling is $84,000.00 of adjusted
        gross income — an inclusive upper bound, so an account at exactly
        $84,000.00 remains eligible and one cent over does not."

        Design: Difficulty/combinatorial_formula/free_file_income_boundary_combinatorial
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",),
            agi_cents=FREE_FILE_AGI_LIMIT_CENTS,
            email=unique_email("comb2a"),
        )
        data = submit_review(ret)
        assert data["status"] == "READY_FOR_REVIEW"
        assert data["free_file_eligible"] is True

    def test_agi_one_cent_over_limit_is_ineligible(self, api):
        """PRD §3.6: "Finally, the free-file disclosure gate: a return still
        priced at `FREE` whose `free_file_eligible` is false may not pass
        review, and is rejected with `ERR_FREE_FILE_INELIGIBLE` (HTTP 422)."
        PRD §2.5: "The free-file income ceiling is $84,000.00 of adjusted
        gross income — an inclusive upper bound, so an account at exactly
        $84,000.00 remains eligible and one cent over does not."

        Design: Difficulty/combinatorial_formula/free_file_income_boundary_combinatorial
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",),
            agi_cents=FREE_FILE_AGI_LIMIT_CENTS + 1,
            email=unique_email("comb2b"),
        )
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FREE_FILE_INELIGIBLE)
        after = get_return(ret)
        assert after["status"] == "DRAFT"
        assert after["free_file_eligible"] is False


class TestProvisionalVsSettledClassification:
    def _setup_with_sch_c_prompt(self):
        seed_catalog(
            tiers=("FREE", "DELUXE", "PREMIER", "SELF_EMPLOYED"),
            forms=("F1040", "W2_WH", "SCH_E", "SCH_D", "F8949", "F4562", "SCH_C"),
        )
        account = create_account(email=unique_email("dual1"), agi_cents=5000000)
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        sch_c = add_form(ret, "SCH_C", 2500000)
        prompt = get_pending_prompt(ret)
        assert prompt is not None, "Setup failed: expected a PENDING prompt"
        return account, ret, sch_c, prompt

    def test_decline_downgrade_settles_classification_back_to_free(self, api):
        """PRD §3.2: "Because decline-downgrade can shrink the active form
        set, a return that provisionally required `SELF_EMPLOYED` may settle
        all the way back at `FREE` once the offending forms are gone."
        PRD §3.6: "The submission then runs the **settled classification**:
        the minimum-tier formula of §3.2 recomputed over the form set as it
        now stands, after every prompt has been resolved and every
        decline-downgrade sweep applied."

        Design: Difficulty/dual_variant_calc/provisional_vs_settled_classification_after_decline
        """
        account, ret, sch_c, prompt = self._setup_with_sch_c_prompt()
        resp = api.decline_prompt(
            ret.id, prompt["id"], ret.version, make_taxpayer_headers(account["id"])
        )
        validate_success(resp)
        ret.refresh(get_return(ret))
        data = submit_review(ret)
        assert data["status"] == "READY_FOR_REVIEW"
        assert data["minimum_required_tier"] == "FREE"
        assert data["current_tier"] == "FREE"
        assert data["total_fees_due_cents"] == 0

    def test_declined_prompt_price_delta_frozen_from_provisional_pass(self, api):
        """PRD §3.2: "The prompt opens in `PENDING` status, recording
        `from_tier` (the return's tier at that moment), `to_tier` (the freshly
        computed minimum), and a `price_delta_cents` frozen at creation as the
        destination tier's `price_cents` minus the source tier's `price_cents`
        — this frozen figure is what the taxpayer is asked to acknowledge, so
        a later catalog price change cannot move the number under them."

        Design: Difficulty/dual_variant_calc/provisional_vs_settled_classification_after_decline
        """
        account, ret, sch_c, prompt = self._setup_with_sch_c_prompt()
        assert prompt["price_delta_cents"] == 19999
        resp = api.decline_prompt(
            ret.id, prompt["id"], ret.version, make_taxpayer_headers(account["id"])
        )
        declined = validate_success(resp)
        assert declined["status"] == "DECLINED_DOWNGRADED"
        prompts = api.list_upgrade_prompts(
            ret.id, make_taxpayer_headers(account["id"])
        )
        settled = {
            p["id"]: p for p in validate_success(prompts)
        }
        assert settled[prompt["id"]]["price_delta_cents"] == 19999


class TestSelectTier:
    def test_overincome_filer_escapes_free_via_select_tier(self, api):
        """PRD §3.2: "A filer may also climb the ladder voluntarily through
        tier selection, the required path for an over-income filer stuck at
        `FREE` (whose return can never pass review while free-file
        ineligible)." PRD §3.2: "A successful selection sets `current_tier`
        to the target and reprices the return."

        Design: Corner/endpoints/select_tier_allows_overincome_filer_to_leave_free
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), agi_cents=9000000, email=unique_email("ep3")
        )
        resp = api.select_tier(
            ret.id, "DELUXE", ret.version, make_taxpayer_headers(account["id"])
        )
        data = validate_success(resp)
        ret.refresh(data)
        assert data["current_tier"] == "DELUXE"
        assert data["total_fees_due_cents"] == 6999
        reviewed = submit_review(ret)
        assert reviewed["status"] == "READY_FOR_REVIEW"

    def test_select_tier_rejects_downgrade(self, api):
        """PRD §3.2: "Tier selection names a `target_tier` whose rank must be
        strictly greater than the current tier's rank — a sideways or downward
        request is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and whose
        rank must also be at least the `minimum_required_tier` rank, otherwise
        `ERR_TIER_BELOW_REQUIRED` (HTTP 422)."

        Design: Corner/endpoints/select_tier_allows_overincome_filer_to_leave_free
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), agi_cents=9000000, email=unique_email("ep3b")
        )
        resp = api.select_tier(
            ret.id, "DELUXE", ret.version, make_taxpayer_headers(account["id"])
        )
        data = validate_success(resp)
        ret.refresh(data)
        resp = api.select_tier(
            ret.id, "FREE", ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestOcc:
    def test_stale_version_on_form_add_rejected(self, api):
        """PRD §2.7: "If the return's current `version` has advanced since
        the client last read it — because a prior form add or remove, or a
        prior-year import, already recomputed the minimum tier and possibly
        created or superseded an upgrade prompt — the add is rejected with
        `ERR_STALE_VERSION` (HTTP 412), since the stale writer's view of the
        return's tier state is outdated."

        Design: Corner/errors/occ_stale_version_on_form_add
        """
        seed_catalog(tiers=("FREE",), forms=("F1040", "W2_WH"))
        account = create_account(email=unique_email("err3"))
        ret = create_return(account)
        stale_version = ret.version
        add_form(ret, "F1040", 0)
        resp = api.add_form(
            ret.id, "W2_WH", 1000, stale_version,
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        resp = api.add_form(
            ret.id, "W2_WH", 1000, ret.version,
            make_taxpayer_headers(account["id"]),
        )
        form = validate_success(resp, expected_status=201)
        assert form["status"] == "ACTIVE"

    def test_stale_version_on_submit_review_rejected(self, api):
        """PRD §2.7: "A mismatch with the return's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412), because an intervening
        upgrade acknowledgment, form removal, or state-return change may have
        altered the fee and tier state after the client last read the
        return."

        Design: Corner/errors/occ_stale_version_on_submit_review
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(email=unique_email("err4"))
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        stale_version = ret.version
        from test_helpers import add_state_return

        add_state_return(ret, "CA")
        resp = api.submit_review(
            ret.id, stale_version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        data = submit_review(ret)
        assert data["status"] == "READY_FOR_REVIEW"
