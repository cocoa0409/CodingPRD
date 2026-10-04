"""Policy changes: activation gate, grandfather/trust cascade, standing cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_org_owner_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_org,
    create_editor_version,
    create_project,
    ship_project,
    setup_shipped_project,
    setup_personal_and_pro_tiers,
    create_policy_change_payload,
    create_asset_listing_payload,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Queue B — validations / retroactive_policy_requires_minimum_grandfather_window
# ---------------------------------------------------------------------------

class TestGrandfatherWindowMinimum:
    def test_retroactive_activation_with_short_window_rejected(self, api):
        """PRD §3.5: "A PlatformAdmin activates a DRAFT change provided both dates are
        set and — if retroactive_flag is true — the grandfather_window_days is at least
        30; activating a retroactive change with a shorter window is rejected with
        ERR_POLICY_WINDOW_TOO_SHORT."

        Design: Corner/validations/retroactive_policy_requires_minimum_grandfather_window
        """
        policy = get_success_data(
            api.create_policy_change(
                create_policy_change_payload(
                    change_code="SHORT-WIN",
                    announcement_date="2026-02-01",
                    effective_date="2026-01-01",
                    retroactive_flag=True,
                    adverse_flag=True,
                    grandfather_window_days=10,
                    new_per_install_cents=30,
                ),
                ADMIN,
            ),
            201,
        )
        resp = api.activate_policy_change(policy["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_TOO_SHORT.value)

        still_draft = get_success_data(api.get_policy_change(policy["id"], ADMIN), 200)
        assert still_draft["change_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / policy_activation_depth3_grandfather_trust_listing
# ---------------------------------------------------------------------------

class TestPolicyActivationCascade:
    def test_activation_creates_commitment_pins_project_dents_trust(self, api):
        """PRD §3.5: "Hop one: every GameProject whose project_status is SHIPPED and
        whose shipped_on is on or before the announcement_date receives a
        GrandfatherCommitment with locked_schedule_label BASE — the schedule frozen at
        pre-change rates — and an attestation_deadline set to the announcement date plus
        the grandfather window in days. Hop two: each such project's
        pinned_policy_change_id is set to the change, and any PROVISIONAL invoices on
        those projects keep the BASE schedule label. Hop three, only when the change is
        both retroactive and adverse: every affected org's trust_score drops by 10, and
        any org whose score falls below 50 flips org_standing to REVIEW".

        Design: Difficulty/transitive_cascade/policy_activation_depth3_grandfather_trust_listing
        """
        set_clock("2026-01-05T00:00:00Z")
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Policy Co", contact_email="po@x.com")
        ev = create_editor_version("2022.3.12f1", "2022.3", "2025-09-01")
        project = create_project(org, ev["id"], title="Game Old")
        set_clock("2026-01-10T00:00:00Z")
        ship_project(org, project)

        policy = get_success_data(
            api.create_policy_change(
                create_policy_change_payload(
                    change_code="RUNTIME-FEE-2026",
                    announcement_date="2026-02-01",
                    effective_date="2026-01-01",
                    retroactive_flag=True,
                    adverse_flag=True,
                    grandfather_window_days=45,
                    new_per_install_cents=30,
                ),
                ADMIN,
            ),
            201,
        )
        get_success_data(api.activate_policy_change(policy["id"], ADMIN), 200)

        commitments, _ = validate_paginated(
            api.list_grandfather_commitments(ADMIN, params={"org_id": org["id"]})
        )
        assert len(commitments) == 1
        commitment = commitments[0]
        assert commitment["project_id"] == project["id"]
        assert commitment["locked_schedule_label"] == "BASE"
        assert commitment["commitment_status"] == "ACTIVE"

        project_now = get_success_data(api.get_project(project["id"], ADMIN), 200)
        assert project_now["pinned_policy_change_id"] == policy["id"]

        org_now = get_success_data(api.get_org(org["id"], ADMIN), 200)
        assert org_now["trust_score"] == 70
        assert org_now["org_standing"] == "GOOD"

    def test_non_adverse_activation_leaves_trust_unchanged(self, api):
        """PRD §3.5: "Hop three, only when the change is both retroactive and adverse:
        every affected org's trust_score drops by 10".

        Design: Difficulty/transitive_cascade/policy_activation_depth3_grandfather_trust_listing
        """
        set_clock("2026-01-05T00:00:00Z")
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Policy Co", contact_email="po@x.com")
        ev = create_editor_version("2022.3.12f1", "2022.3", "2025-09-01")
        project = create_project(org, ev["id"], title="Game Old")
        set_clock("2026-01-10T00:00:00Z")
        ship_project(org, project)

        policy = get_success_data(
            api.create_policy_change(
                create_policy_change_payload(
                    change_code="BENIGN-2026",
                    announcement_date="2026-02-01",
                    effective_date="2026-01-01",
                    retroactive_flag=True,
                    adverse_flag=False,
                    grandfather_window_days=45,
                    new_per_install_cents=15,
                ),
                ADMIN,
            ),
            201,
        )
        get_success_data(api.activate_policy_change(policy["id"], ADMIN), 200)

        org_now = get_success_data(api.get_org(org["id"], ADMIN), 200)
        assert org_now["trust_score"] == 80
        assert org_now["org_standing"] == "GOOD"


# ---------------------------------------------------------------------------
# Queue B — rbac / org_owner_cannot_activate_policy_change
# ---------------------------------------------------------------------------

class TestPolicyActivationRBAC:
    def test_org_owner_cannot_activate_policy_change(self, api):
        """PRD §3.5: "A PlatformAdmin activates a DRAFT change provided both dates are
        set".
        PRD §2.1: "Even with well-formed headers, a caller whose role is not listed as
        authorized for the target endpoint is rejected with ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/org_owner_cannot_activate_policy_change
        """
        get_success_data(
            api.create_tier(
                {
                    "tier_code": "PERSONAL",
                    "revenue_ceiling_cents": 20_000_000,
                    "funding_ceiling_cents": 20_000_000,
                    "seat_minimum": 0,
                    "seat_overage_cents": 0,
                    "runtime_fee_exempt": True,
                    "export_module_allowed": False,
                    "marketplace_sell_allowed": False,
                },
                ADMIN,
            ),
            201,
        )
        org = create_org("PERSONAL", legal_name="Rbac Co", contact_email="rb@x.com")
        policy = get_success_data(
            api.create_policy_change(
                create_policy_change_payload(
                    change_code="RBAC-1",
                    announcement_date="2026-02-01",
                    effective_date="2026-03-01",
                    retroactive_flag=False,
                    adverse_flag=False,
                    grandfather_window_days=30,
                    new_per_install_cents=25,
                ),
                ADMIN,
            ),
            201,
        )
        resp = api.activate_policy_change(policy["id"], make_org_owner_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_layers / standing_drop_forces_approved_listing_back_to_review
# ---------------------------------------------------------------------------

class TestStandingCascade:
    def test_trust_below_50_flips_standing_and_forces_re_review(self, api):
        """PRD §3.5: "any org whose score falls below 50 flips org_standing to REVIEW —
        which cascades further, returning that org's APPROVED asset listings to
        PENDING_REVIEW."
        PRD §3.6: "when a creator org's standing drops to REVIEW or SUSPENDED — for
        instance through an adverse retroactive policy activation — its APPROVED
        listings cascade back to PENDING_REVIEW with review_rounds incremented, and
        must be re-approved before new purchases."

        Design: Corner/cross_cutting_layers/standing_drop_forces_approved_listing_back_to_review
        """
        setup_personal_and_pro_tiers()
        set_clock("2026-01-05T00:00:00Z")
        org = create_org("PRO", legal_name="Trust Co", contact_email="t@x.com")
        ev = create_editor_version("2022.3.71f1", "2022.3", "2025-09-01")
        project = create_project(org, ev["id"], title="Game T2")
        ship_project(org, project)

        owner = make_org_owner_headers(org["id"])
        listing = get_success_data(
            api.create_asset_listing(
                org["id"], create_asset_listing_payload(title="Trust Asset", price_cents=10_000), owner
            ),
            201,
        )
        get_success_data(api.submit_listing_review(listing["id"], owner), 200)
        get_success_data(
            api.review_asset_listing(listing["id"], {"action": "APPROVE"}, REVIEWER), 200
        )

        codes = ("ADV-1", "ADV-2", "ADV-3", "ADV-4")
        announcements = ("2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01")
        effectives = ("2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01")
        rates = (30, 35, 40, 45)
        policy_ids = []
        for code, ann, eff, rate in zip(codes, announcements, effectives, rates):
            policy = get_success_data(
                api.create_policy_change(
                    create_policy_change_payload(
                        change_code=code,
                        announcement_date=ann,
                        effective_date=eff,
                        retroactive_flag=True,
                        adverse_flag=True,
                        grandfather_window_days=45,
                        new_per_install_cents=rate,
                    ),
                    ADMIN,
                ),
                201,
            )
            policy_ids.append(policy["id"])
        for policy_id in policy_ids:
            get_success_data(api.activate_policy_change(policy_id, ADMIN), 200)

        org_now = get_success_data(api.get_org(org["id"], ADMIN), 200)
        assert org_now["trust_score"] == 40
        assert org_now["org_standing"] == "REVIEW"

        listing_now = get_success_data(api.get_asset_listing(listing["id"], ADMIN), 200)
        assert listing_now["listing_status"] == "PENDING_REVIEW"
