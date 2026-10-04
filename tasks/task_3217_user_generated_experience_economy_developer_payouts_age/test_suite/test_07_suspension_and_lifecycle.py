"""User suspension cascades, the parallel eligibility dimension, and experience
terminal-state lockdown (PRD §3.1, §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_experience,
    create_identity_verification_payload,
    create_on_sale_limited_item,
    create_published_experience,
    create_tax_document_payload,
    create_user,
    get_user,
    list_for_resale,
    make_creator_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSuspensionCascade:
    def test_creator_suspension_cascades_to_experience_and_resale_depth2(self, api, platform_admin_headers):
        """PRD §3.1: "Suspension is deliberately loud: every `ACTIVE` resale listing
        owned by the user transitions to `CANCELLED`, every `PUBLISHED` experience
        owned by the user cascades to `SUSPENDED`, and every `SUBMITTED` DevEx request
        for the user transitions to `CANCELLED` with its `locked_robux` released."

        Design: Difficulty/transitive_cascade/creator_suspension_cascades_to_experience_and_resale_depth2
        """
        set_clock("2026-08-20T00:00:00Z")
        creator = create_user(username="cr_d", email="cr_d@x.com", date_of_birth="1990-01-01")
        exp, _sub = create_published_experience(creator["id"], title="World D")
        item, _isub = create_on_sale_limited_item(
            creator["id"], title="Rare Hat", price_robux=1000, total_supply=10, royalty_pct=10
        )
        set_clock("2026-09-01T00:00:00Z")
        listing = list_for_resale(creator["id"], item["id"], 600)
        assert listing["status"] == "ACTIVE"

        suspended = validate_success(
            api.suspend_user(creator["id"], {"reason": "safety escalation"}, platform_admin_headers),
            200,
        )
        assert suspended["status"] == "SUSPENDED"

        exp_now = validate_success(api.get_experience(exp["id"], platform_admin_headers), 200)
        assert exp_now["status"] == "SUSPENDED", (
            f"published experience must cascade to SUSPENDED, got {exp_now['status']}"
        )
        listing_now = validate_success(
            api.get_resale_listing(listing["id"], platform_admin_headers), 200
        )
        assert listing_now["status"] == "CANCELLED", (
            f"active resale listing must cascade to CANCELLED, got {listing_now['status']}"
        )

    def test_reinstate_does_not_undo_experience_or_listing_cascade(self, api, platform_admin_headers):
        """PRD §3.1: "Reinstatement, performed by a `PlatformAdmin`, returns the account
        from `SUSPENDED` to `ACTIVE` and clears `suspension_reason` — but it does not
        undo the cascade: experiences suspended by it stay `SUSPENDED`, and the creator
        must re-publish each one individually."

        Design: Difficulty/transitive_cascade/creator_suspension_cascades_to_experience_and_resale_depth2
        """
        set_clock("2026-08-20T00:00:00Z")
        creator = create_user(username="cr_d2", email="cr_d2@x.com", date_of_birth="1990-01-01")
        exp, _sub = create_published_experience(creator["id"], title="World D2")
        item, _isub = create_on_sale_limited_item(
            creator["id"], title="Rare Hat 2", price_robux=1000, total_supply=10, royalty_pct=10
        )
        set_clock("2026-09-01T00:00:00Z")
        listing = list_for_resale(creator["id"], item["id"], 600)

        validate_success(
            api.suspend_user(creator["id"], {"reason": "test"}, platform_admin_headers), 200
        )
        reinstated = validate_success(
            api.reinstate_user(creator["id"], platform_admin_headers), 200
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated.get("suspension_reason") in (None, ""), (
            "reinstatement must clear suspension_reason"
        )

        exp_now = validate_success(api.get_experience(exp["id"], platform_admin_headers), 200)
        assert exp_now["status"] == "SUSPENDED", (
            f"cascade-suspended experience must stay SUSPENDED after reinstate, got {exp_now['status']}"
        )
        listing_now = validate_success(
            api.get_resale_listing(listing["id"], platform_admin_headers), 200
        )
        assert listing_now["status"] == "CANCELLED", (
            f"cancelled listing must stay CANCELLED after reinstate, got {listing_now['status']}"
        )


class TestParallelEligibilityDimension:
    def test_user_status_and_devex_eligibility_parallel_dimensions(self, api, platform_admin_headers):
        """PRD §3.2: "Independently of review, a verification transitions to `EXPIRED`
        the moment the platform clock passes `expiry_date`; `reviewed_at` is stamped
        whenever the status leaves `PENDING`, by whichever path."
        PRD §3.2: "Six clauses must all hold: the user's `status` is `ACTIVE`; the
        `age_band` is `ADULT`; the identity verification's `status` is `VERIFIED`; the
        tax document's `status` is `ACCEPTED`; `account_age_days` is at least thirty;
        and `earned_robux_lifetime` is at least 30,000 Robux."

        Design: Difficulty/non_linear_state_machine/user_status_and_devex_eligibility_parallel_dimensions
        """
        set_clock("2026-08-01T00:00:00Z")
        creator = create_user(username="cr_c", email="cr_c@x.com", date_of_birth="1990-01-01")
        headers = make_creator_headers(creator["id"])
        iv = validate_success(
            api.create_identity_verification(
                creator["id"],
                create_identity_verification_payload(expiry_date="2026-10-01T00:00:00Z"),
                headers,
            ),
            201,
        )
        validate_success(api.verify_identity(iv["id"], platform_admin_headers), 200)
        tax = validate_success(
            api.create_tax_document(creator["id"], create_tax_document_payload(), headers), 201
        )
        validate_success(api.accept_tax_document(tax["id"], platform_admin_headers), 200)

        # Crossing the document expiry moves the eligibility axis without any
        # lifecycle transition.
        set_clock("2026-10-02T00:00:00Z")
        user = get_user(creator["id"])
        assert user["status"] == "ACTIVE", (
            f"clock advance must not transition the lifecycle, got {user['status']}"
        )
        assert user["is_devex_eligible"] is False, (
            "an EXPIRED identity verification must force is_devex_eligible to false"
        )
        ivs, _meta = validate_paginated(
            api.list_identity_verifications(creator["id"], platform_admin_headers)
        )
        iv_now = [row for row in ivs if row["id"] == iv["id"]]
        assert iv_now, "identity verification row missing"
        assert iv_now[0]["status"] == "EXPIRED", (
            f"verification past expiry_date must be EXPIRED, got {iv_now[0]['status']}"
        )

    def test_suspend_reinstate_does_not_restore_devex_eligibility(self, api, platform_admin_headers):
        """PRD §3.1: "Reinstatement, performed by a `PlatformAdmin`, returns the account
        from `SUSPENDED` to `ACTIVE` and clears `suspension_reason`"
        PRD §3.2: "Six clauses must all hold: the user's `status` is `ACTIVE`; the
        `age_band` is `ADULT`; the identity verification's `status` is `VERIFIED`; the
        tax document's `status` is `ACCEPTED`; `account_age_days` is at least thirty;
        and `earned_robux_lifetime` is at least 30,000 Robux."

        Design: Difficulty/non_linear_state_machine/user_status_and_devex_eligibility_parallel_dimensions
        """
        set_clock()
        user = create_user(username="cr_pd", email="cr_pd@x.com", date_of_birth="1990-01-01")
        # Suspend then reinstate: the lifecycle axis moves out and back...
        validate_success(
            api.suspend_user(user["id"], {"reason": "test"}, platform_admin_headers), 200
        )
        assert get_user(user["id"])["status"] == "SUSPENDED"
        validate_success(api.reinstate_user(user["id"], platform_admin_headers), 200)
        fresh = get_user(user["id"])
        assert fresh["status"] == "ACTIVE"
        # ...but with no identity verification, tax document, age, or earnings, the
        # eligibility axis never moved.
        assert fresh["is_devex_eligible"] is False


class TestExperienceTerminalLockdown:
    def test_experience_archive_from_published_is_terminal(self, api):
        """PRD §3.4: "Finally, a creator may archive an experience they own from
        `DRAFT`, `PUBLISHED`, or `SUSPENDED`; archiving moves it to `ARCHIVED`, stamps
        `archived_at`, is terminal, stops snapshot accumulation, and runs a final
        engagement sweep that settles `engagement_payout_pending_robux` to zero by
        crediting the creator immediately — the pending payout is never lost to
        archival."
        PRD §2.5: "Fourth, the target entity's current state is checked against the
        requested transition, yielding `ERR_INVALID_STATE`."

        Design: Corner/state_machines/experience_archive_from_published_is_terminal
        """
        set_clock()
        creator = create_user(username="cr_ar", email="cr_ar@x.com", date_of_birth="1990-01-01")
        exp = create_experience(creator["id"], title="Archivable")
        headers = make_creator_headers(creator["id"])
        archived = validate_success(api.archive_experience(exp["id"], headers), 200)
        assert archived["status"] == "ARCHIVED"

        resp = api.submit_experience_for_review(exp["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        after = validate_success(
            api.get_experience(exp["id"], TEST_USERS["platform_admin_headers"]), 200
        )
        assert after["status"] == "ARCHIVED", (
            f"terminal ARCHIVED state must be absorbing, got {after['status']}"
        )
