"""Account suspension/appeal branching and appeal temporal windows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_verified_account,
    create_and_activate_campaign,
    create_campaign,
    suspend_account,
    file_appeal,
    decide_appeal,
    refresh_account,
    refresh_campaign,
    submit_identity_verification,
    approve_verification,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
)


class TestSuspendAppealOverturnResuspendBranch:
    def test_overturn_resumes_suspension_paused_campaigns(self, api):
        """PRD §3.2: "An `OVERTURNED` decision moves the appeal to `OVERTURNED`
        and the account back to `ACTIVE`, clearing `suspension_reason_code` to
        null while retaining `suspended_at` for audit, and firing the resume
        cascade: every campaign paused with `pause_origin` `SUSPENSION` returns to
        `ACTIVE` with `pause_origin` reset to `NONE`, and each resumed campaign
        recomputes its `eligible_ad_count`."
        PRD §3.2: "A successful filing moves the account from `SUSPENDED` to
        `APPEAL_PENDING`, increments the account's `version`, creates the appeal
        in `SUBMITTED`, and immediately — as an automatic intake step — advances
        the appeal to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/account_suspend_appeal_overturn_resuspend_upheld_final_branch
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Branch Corp", payment_method_type="INVOICING")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CB", daily_budget_cents=1000)
        suspend_account(account)
        ap1 = file_appeal(account, "false positive")
        assert ap1["status"] == "UNDER_REVIEW"  # automatic intake at creation
        decide_appeal(ap1["id"], "OVERTURNED")
        got_camp = refresh_campaign(campaign, account)
        assert got_camp["status"] == "ACTIVE"
        assert got_camp["pause_origin"] == "NONE"
        got_acct = refresh_account(account)
        assert got_acct["status"] == "ACTIVE"

    def test_second_upheld_reaches_suspended_final(self, api):
        """PRD §3.2: "An `UPHELD` decision moves the appeal to `UPHELD` and the
        account back from `APPEAL_PENDING` to `SUSPENDED`, incrementing
        `upheld_appeal_count` by 1 — and when that count reaches 2, the account
        lands in `SUSPENDED_FINAL` instead of `SUSPENDED`, closing the episode
        permanently (`SUSPENDED_FINAL` is terminal)."

        Design: Difficulty/non_linear_state_machine/account_suspend_appeal_overturn_resuspend_upheld_final_branch
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Branch Corp", payment_method_type="INVOICING")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CB", daily_budget_cents=1000)
        # Episode 1: suspend -> appeal -> OVERTURNED (count stays 0).
        suspend_account(account)
        ap1 = file_appeal(account, "false positive")
        decide_appeal(ap1["id"], "OVERTURNED")
        # Episode 2: suspend (new suspension resets the window) -> appeal -> UPHELD.
        set_clock("2026-09-02T00:00:00Z")
        suspend_account(account, reason_code="CIRCUMVENTION")
        ap2 = file_appeal(account, "still wrong")
        decide_appeal(ap2["id"], "UPHELD")
        got = refresh_account(account)
        assert got["status"] == "SUSPENDED"
        assert got["upheld_appeal_count"] == 1
        # Episode 2 continues: cooldown 14 days after 2026-09-06 decision; the
        # decision here happened at 2026-09-02, so +14d = 2026-09-16; window is
        # 2026-09-02 + 30d = 2026-10-02. File again on 2026-09-20.
        set_clock("2026-09-20T00:00:00Z")
        ap3 = file_appeal(account, "second try after cooldown")
        decide_appeal(ap3["id"], "UPHELD")
        final = refresh_account(account)
        assert final["status"] == "SUSPENDED_FINAL"
        assert final["upheld_appeal_count"] == 2


class TestAppealOverturnCascade:
    def test_overturn_resumes_only_suspension_paused_campaigns(self, api):
        """PRD §3.2: "An `OVERTURNED` decision moves the appeal to `OVERTURNED`
        and the account back to `ACTIVE`, clearing `suspension_reason_code` to
        null while retaining `suspended_at` for audit, and firing the resume
        cascade: every campaign paused with `pause_origin` `SUSPENSION` returns to
        `ACTIVE` with `pause_origin` reset to `NONE`, and each resumed campaign
        recomputes its `eligible_ad_count`."
        PRD §2.12: "Overturning the suspension through an appeal walks the cascade
        in reverse, resuming exactly the campaigns the suspension paused and no
        others."

        Design: Difficulty/transitive_cascade/appeal_overturned_cascade_appeal_to_account_to_campaigns
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Resume Corp")
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        k1 = create_and_activate_campaign(account, name="K1", daily_budget_cents=1000)
        k2 = create_and_activate_campaign(account, name="K2", daily_budget_cents=1000)
        # K2 manually paused by the advertiser before the suspension.
        api.pause_campaign(k2["id"], headers)
        suspend_account(account)
        ap = file_appeal(account, "we fixed the landing page")
        decide_appeal(ap["id"], "OVERTURNED", reviewer_note="verified fix")
        got_acct = refresh_account(account)
        assert got_acct["status"] == "ACTIVE"
        got_k1 = refresh_campaign(k1, account)
        assert got_k1["status"] == "ACTIVE" and got_k1["pause_origin"] == "NONE"
        got_k2 = refresh_campaign(k2, account)
        assert got_k2["status"] == "PAUSED" and got_k2["pause_origin"] == "ADVERTISER"

    def test_overturn_clears_suspension_reason_code(self, api):
        """PRD §3.2: "An `OVERTURNED` decision moves the appeal to `OVERTURNED`
        and the account back to `ACTIVE`, clearing `suspension_reason_code` to
        null while retaining `suspended_at` for audit, and firing the resume
        cascade: every campaign paused with `pause_origin` `SUSPENSION` returns to
        `ACTIVE` with `pause_origin` reset to `NONE`, and each resumed campaign
        recomputes its `eligible_ad_count`."

        Design: Difficulty/transitive_cascade/appeal_overturned_cascade_appeal_to_account_to_campaigns
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Resume Corp")
        account = ctx["account"]
        create_and_activate_campaign(account, name="K1", daily_budget_cents=1000)
        suspend_account(account)
        suspended = refresh_account(account)
        assert suspended["suspension_reason_code"] == "POLICY_VIOLATION"
        ap = file_appeal(account, "we fixed the landing page")
        decide_appeal(ap["id"], "OVERTURNED")
        got = refresh_account(account)
        assert got["status"] == "ACTIVE"
        assert got["suspension_reason_code"] is None


class TestCampaignActivationBlockedByAccountPosture:
    def test_activate_on_pending_verification_account_rejected(self, api):
        """PRD §3.3: "and the owning account must be `ACTIVE` — activation against
        a `PENDING_VERIFICATION` account is rejected with
        `ERR_VERIFICATION_REQUIRED` (422), while a `SUSPENDED`, `APPEAL_PENDING`,
        or `SUSPENDED_FINAL` account yields `ERR_ACCOUNT_SUSPENDED` (422)."

        Design: Difficulty/cross_entity_state_dependency/campaign_activation_blocked_by_account_posture
        """
        set_clock("2026-09-01T00:00:00Z")
        account_u = create_account("Unver")  # never verified
        headers_u = make_advertiser_headers(account_u["id"])
        cu = get_success_data(api_client.create_campaign(
            {
                "account_id": account_u["id"], "name": "CU", "daily_budget_cents": 1000,
                "start_date": "2026-09-01", "end_date": "2026-12-31",
            },
            headers_u,
        ))
        resp = api_client.activate_campaign(cu["id"], headers_u)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_REQUIRED)

    def test_activate_on_suspended_account_rejected(self, api):
        """PRD §3.3: "and the owning account must be `ACTIVE` — activation against
        a `PENDING_VERIFICATION` account is rejected with
        `ERR_VERIFICATION_REQUIRED` (422), while a `SUSPENDED`, `APPEAL_PENDING`,
        or `SUSPENDED_FINAL` account yields `ERR_ACCOUNT_SUSPENDED` (422)."

        Design: Difficulty/cross_entity_state_dependency/campaign_activation_blocked_by_account_posture
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Susp", with_billing_profile=False)
        account_v = ctx["account"]
        headers_v = make_advertiser_headers(account_v["id"])
        cv = get_success_data(api_client.create_campaign(
            {
                "account_id": account_v["id"], "name": "CV", "daily_budget_cents": 1000,
                "start_date": "2026-09-01", "end_date": "2026-12-31",
            },
            headers_v,
        ))
        suspend_account(account_v, reason_code="CIRCUMVENTION")
        resp = api_client.activate_campaign(cv["id"], headers_v)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)


class TestAppealWindowHalfOpen:
    def test_appeal_at_window_minus_one_second_succeeds(self, api):
        """PRD §3.2: "Filing is permitted only within a half-open window: the
        logical clock must be strictly before thirty days after `suspended_at`; an
        appeal filed at or after that boundary is rejected with
        `ERR_APPEAL_WINDOW_CLOSED` (422), and the lazy evaluation of §2.6 — which
        runs on the filing attempt itself — may already have moved the account to
        `SUSPENDED_FINAL`."

        Design: Difficulty/boundary_precision_check/appeal_window_half_open_day30_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Alpha", with_billing_profile=False)
        account = ctx["account"]
        suspend_account(account)
        # suspended_at = 2026-09-01T00:00:00Z; +30d = 2026-10-01T00:00:00Z.
        set_clock("2026-09-30T23:59:59Z")
        resp = api_client.create_appeal(
            account["id"], {"argument_text": "just inside the window"},
            make_advertiser_headers(account["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_appeal_at_exactly_day30_rejected(self, api):
        """PRD §3.2: "Filing is permitted only within a half-open window: the
        logical clock must be strictly before thirty days after `suspended_at`; an
        appeal filed at or after that boundary is rejected with
        `ERR_APPEAL_WINDOW_CLOSED` (422), and the lazy evaluation of §2.6 — which
        runs on the filing attempt itself — may already have moved the account to
        `SUSPENDED_FINAL`."

        Design: Difficulty/boundary_precision_check/appeal_window_half_open_day30_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Beta", with_billing_profile=False)
        account = ctx["account"]
        suspend_account(account)
        set_clock("2026-10-01T00:00:00Z")  # exactly suspended_at + 30 days
        resp = api_client.create_appeal(
            account["id"], {"argument_text": "exactly at day 30"},
            make_advertiser_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)


class TestAppealCooldownBuffer:
    def test_appeal_inside_cooldown_rejected(self, api):
        """PRD §3.2: "If a previous appeal on the current suspension episode was
        decided `UPHELD`, the logical clock must also be at or after fourteen days
        past that decision's `decided_at`; filing earlier is rejected with
        `ERR_APPEAL_COOLDOWN` (422)."

        Design: Difficulty/resource_temporal_overlap/appeal_cooldown_buffer_after_upheld_decision
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Cool Corp", with_billing_profile=False)
        account = ctx["account"]
        suspend_account(account)
        ap1 = file_appeal(account, "first appeal")
        set_clock("2026-09-06T00:00:00Z")
        decide_appeal(ap1["id"], "UPHELD", reviewer_note="violation confirmed")
        # decided_at 2026-09-06; cooldown ends 2026-09-20. File at 2026-09-15.
        set_clock("2026-09-15T00:00:00Z")
        resp = api_client.create_appeal(
            account["id"], {"argument_text": "inside cooldown"},
            make_advertiser_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_COOLDOWN)

    def test_appeal_at_cooldown_end_inside_window_succeeds(self, api):
        """PRD §3.2: "If a previous appeal on the current suspension episode was
        decided `UPHELD`, the logical clock must also be at or after fourteen days
        past that decision's `decided_at`; filing earlier is rejected with
        `ERR_APPEAL_COOLDOWN` (422)."
        PRD §3.2: "Filing is permitted only within a half-open window: the logical
        clock must be strictly before thirty days after `suspended_at`; an appeal
        filed at or after that boundary is rejected with `ERR_APPEAL_WINDOW_CLOSED`
        (422), and the lazy evaluation of §2.6 — which runs on the filing attempt
        itself — may already have moved the account to `SUSPENDED_FINAL`."

        Design: Difficulty/resource_temporal_overlap/appeal_cooldown_buffer_after_upheld_decision
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Cool Corp", with_billing_profile=False)
        account = ctx["account"]
        suspend_account(account)
        ap1 = file_appeal(account, "first appeal")
        set_clock("2026-09-06T00:00:00Z")
        decide_appeal(ap1["id"], "UPHELD", reviewer_note="violation confirmed")
        # Buffer ended exactly at 2026-09-20 (decided_at + 14d); window closes
        # 2026-10-01. Filing at exactly the buffer end succeeds.
        set_clock("2026-09-20T00:00:00Z")
        resp = api_client.create_appeal(
            account["id"], {"argument_text": "after cooldown, inside window"},
            make_advertiser_headers(account["id"]),
        )
        validate_success(resp, expected_status=201)
