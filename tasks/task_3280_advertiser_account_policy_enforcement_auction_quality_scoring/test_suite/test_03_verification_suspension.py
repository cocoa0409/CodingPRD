"""Verification, suspension, and appeal lifecycle tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    submit_identity_verification,
    approve_verification,
    create_verified_account,
    create_campaign,
    create_and_activate_campaign,
    suspend_account,
    file_appeal,
    decide_appeal,
    refresh_account,
    refresh_campaign,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
)


class TestVerificationLifecycle:
    def test_disclosure_text_set_on_verification_approval(self, api):
        """PRD §3.1: "Approval moves the verification from `SUBMITTED` to
        `APPROVED` and the account from `PENDING_VERIFICATION` to `ACTIVE` in the
        same act, stamping `verified_business_name` with the approved legal name
        and composing `disclosure_text` as the string "Ads by " followed by the
        verified business name — the public identity disclosure shown alongside
        the advertiser's ads."

        Design: Corner/state_machines/disclosure_text_set_on_verification_approval
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Cap")
        ver = submit_identity_verification(account, legal_business_name="Cap Corp LLC")
        approve_verification(ver["id"])
        data = get_success_data(
            api.get_advertiser_account(account["id"], TEST_USERS["platform_admin_headers"])
        )
        assert data["status"] == "ACTIVE"
        assert data["verified_business_name"] == "Cap Corp LLC"
        assert data["disclosure_text"] == "Ads by Cap Corp LLC"

    def test_verification_decide_on_terminal_record_returns_invalid_state(self, api):
        """PRD §3.1: "Both `APPROVED` and `REJECTED` are terminal for a
        verification; deciding an already-decided record is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/verification_decide_on_terminal_record_returns_invalid_state
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Dec Corp")
        ver = submit_identity_verification(
            account, legal_business_name="Dec Corp LLC", document_type="GOVERNMENT_ID"
        )
        approve_verification(ver["id"])
        resp = api.decide_identity_verification(
            ver["id"],
            {"outcome": "REJECTED", "rejection_reason": "late doubt"},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSuspensionCascade:
    def test_suspend_cascades_pause_to_active_campaigns_only(self, api):
        """PRD §3.2: "The cascade of §2.12 then fires: every `ACTIVE` campaign of
        the account moves to `PAUSED` with `pause_origin` set to `SUSPENSION`, and
        each paused campaign recomputes its `eligible_ad_count` — the count itself
        is unchanged, because the ads keep their `ELIGIBLE` status, but they are
        auction-ineligible for as long as the campaign is paused."

        Design: Corner/state_machines/suspend_cascades_pause_to_active_campaigns_only
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Casc Corp", with_billing_profile=False)
        account = ctx["account"]
        c1 = create_and_activate_campaign(account, name="A1", daily_budget_cents=1000)
        c2 = create_campaign(account, name="A2", daily_budget_cents=1000)  # stays DRAFT
        suspend_account(account, reason_code="BILLING_DELINQUENCY")
        got1 = refresh_campaign(c1, account)
        got2 = refresh_campaign(c2, account)
        assert got1["status"] == "PAUSED" and got1["pause_origin"] == "SUSPENSION"
        assert got2["status"] == "DRAFT" and got2["pause_origin"] == "NONE"


class TestCampaignPauseActivateRoundtrip:
    def test_campaign_pause_activate_roundtrip_valid(self, api):
        """PRD §3.3: "Pausing moves an `ACTIVE` campaign to `PAUSED` with
        `pause_origin` set to `ADVERTISER`."
        PRD §3.3: "Activation moves a campaign from `DRAFT` — or resumes it from
        `PAUSED` — to `ACTIVE` and resets `pause_origin` to `NONE`."

        Design: Corner/state_machines/campaign_pause_activate_roundtrip_valid
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("RT Corp", with_billing_profile=False)
        account = ctx["account"]
        camp = create_and_activate_campaign(account, name="RT", daily_budget_cents=1000)
        headers = make_advertiser_headers(account["id"])
        paused = validate_success(api.pause_campaign(camp["id"], headers))
        assert paused["status"] == "PAUSED" and paused["pause_origin"] == "ADVERTISER"
        resumed = validate_success(api.activate_campaign(camp["id"], headers))
        assert resumed["status"] == "ACTIVE" and resumed["pause_origin"] == "NONE"

    def test_campaign_pause_from_draft_returns_invalid_state(self, api):
        """PRD §3.3: "Attempting to pause a campaign that is not `ACTIVE` — a
        `DRAFT` campaign, for instance — is `ERR_INVALID_STATE` (409), as is
        activating or pausing an `ENDED` one."

        Design: Corner/state_machines/campaign_pause_from_draft_returns_invalid_state
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("SM Corp", with_billing_profile=False)
        account = ctx["account"]
        camp = create_campaign(account, name="DR", daily_budget_cents=1000,
                               start_date="2026-09-01", end_date="2026-09-30")
        resp = api.pause_campaign(camp["id"], make_advertiser_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        got = refresh_campaign(camp, account)
        assert got["status"] == "DRAFT"


class TestAppealLifecycle:
    def test_appeal_while_one_open_returns_already_open(self, api):
        """PRD §3.2: "Filing while another appeal is still open trips
        `ERR_APPEAL_ALREADY_OPEN` (409)."
        PRD §2.11: "A new appeal while an appeal of the same account sits in
        `SUBMITTED` or `UNDER_REVIEW` is rejected with `ERR_APPEAL_ALREADY_OPEN`
        (409)."

        Design: Corner/validations/appeal_while_one_open_returns_already_open
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Open Corp", with_billing_profile=False)
        account = ctx["account"]
        suspend_account(account)
        file_appeal(account, "first")
        resp = api.create_appeal(
            account["id"], {"argument_text": "second while open"},
            make_advertiser_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_OPEN)
