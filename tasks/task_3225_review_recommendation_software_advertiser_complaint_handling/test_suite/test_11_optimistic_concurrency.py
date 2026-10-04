"""Optimistic concurrency: stale-version rejection on the three OCC endpoints."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    claim_page,
    create_page,
    create_page_claim_payload,
    create_user,
    get_page,
    make_business_owner_headers,
    setup_claimed_page,
    set_clock,
    validate_error,
    validate_success,
)


def _verified_claim(api, page_id, owner_id):
    claim = validate_success(
        api.create_page_claim(page_id, create_page_claim_payload(kind="CLAIM"),
                              make_business_owner_headers(owner_id)),
        expected_status=201,
    )
    return validate_success(
        api.verify_page_claim(claim["id"], {"verification_code": claim["verification_code"]},
                              make_business_owner_headers(owner_id))
    )


class TestStaleVersionOnClaimApprove:
    def test_approve_with_stale_page_version_rejected(self, api):
        """PRD §2.9: "Approving a verified page claim requires
        `expected_page_version` matching the `BusinessPage`'s current
        `version`. A mismatch — for example because another admin has just
        approved a different claim, or a merge re-pointed the page — is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/err_stale_version_on_claim_approve
        """
        set_clock("2026-09-01T00:00:00Z")
        owner = create_user()
        page = create_page(name="OCC Outfit")
        claim = _verified_claim(api, page["id"], owner["id"])
        stale_version = page["version"] - 1
        r = api.approve_page_claim(
            claim["id"], {"expected_page_version": stale_version}, ADMIN
        )
        validate_error(r, ApiErrorId.ERR_STALE_VERSION.value)

    def test_stale_approve_leaves_claim_verified(self, api):
        """PRD §2.9: "Approving a verified page claim requires
        `expected_page_version` matching the `BusinessPage`'s current
        `version`. A mismatch — for example because another admin has just
        approved a different claim, or a merge re-pointed the page — is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "A `SupportAdmin` decides a `VERIFIED` claim."

        Design: Corner/errors/err_stale_version_on_claim_approve
        """
        set_clock("2026-09-01T00:00:00Z")
        owner = create_user()
        page = create_page(name="OCC Outfit Two")
        claim = _verified_claim(api, page["id"], owner["id"])
        api.approve_page_claim(
            claim["id"], {"expected_page_version": page["version"] - 1}, ADMIN
        )
        claim_after = validate_success(api.get_page_claim(claim["id"], ADMIN))
        assert claim_after["status"] == "VERIFIED"


class TestStaleVersionOnPageInfoUpdate:
    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.9: "An owner submitting a page info update must include
        `expected_page_version` matching the page's current `version`; a stale
        value is rejected with `ERR_STALE_VERSION` (HTTP 412), and the owner
        must re-read the page and retry."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_page_info_update
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        # page["version"] reflects the post-approval read; the pre-approval
        # version is one behind and therefore stale.
        r = api.update_business_page(
            page["id"],
            {"expected_page_version": page["version"] - 1,
             "website": "https://stale.example"},
            make_business_owner_headers(owner["id"]),
        )
        validate_error(r, ApiErrorId.ERR_STALE_VERSION.value)

    def test_patch_with_current_version_succeeds_and_bumps_version(self, api):
        """PRD §3.2: "otherwise the update is applied and the page's `version`
        is incremented by 1."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_page_info_update
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        updated = validate_success(
            api.update_business_page(
                page["id"],
                {"expected_page_version": page["version"],
                 "website": "https://fresh.example"},
                make_business_owner_headers(owner["id"]),
            )
        )
        assert updated["website"] == "https://fresh.example"
        assert updated["version"] == page["version"] + 1


class TestStaleVersionOnMergeExecute:
    def test_execute_with_stale_duplicate_version_rejected(self, api):
        """PRD §2.9: "Executing a merge request requires
        `expected_duplicate_page_version` matching the duplicate
        `BusinessPage`'s current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_merge_execute
        """
        set_clock("2026-09-01T00:00:00Z")
        pd = create_page(name="MG Dup")
        ps = create_page(name="MG Surv")
        mr = validate_success(
            api.create_merge_request(
                {
                    "duplicate_page_id": pd["id"],
                    "survivor_page_id": ps["id"],
                    "reason": "Same business listed twice on MG street.",
                },
                ADMIN,
            ),
            expected_status=201,
        )
        # Advance the duplicate's version after the merge request was filed.
        claim_page(pd["id"], create_user()["id"])
        r = api.execute_merge_request(
            mr["id"], {"expected_duplicate_page_version": pd["version"]}, ADMIN
        )
        validate_error(r, ApiErrorId.ERR_STALE_VERSION.value)

    def test_stale_execute_leaves_pages_and_request_untouched(self, api):
        """PRD §2.9: "Executing a merge request requires
        `expected_duplicate_page_version` matching the duplicate
        `BusinessPage`'s current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.11: "On acceptance the merge request starts in `PENDING`".

        Design: Corner/cross_cutting_layers/occ_stale_version_on_merge_execute
        """
        set_clock("2026-09-01T00:00:00Z")
        pd = create_page(name="MG Dup Two")
        ps = create_page(name="MG Surv Two")
        mr = validate_success(
            api.create_merge_request(
                {
                    "duplicate_page_id": pd["id"],
                    "survivor_page_id": ps["id"],
                    "reason": "Same business listed twice on MG street.",
                },
                ADMIN,
            ),
            expected_status=201,
        )
        claim_page(pd["id"], create_user()["id"])
        api.execute_merge_request(
            mr["id"], {"expected_duplicate_page_version": pd["version"]}, ADMIN
        )
        assert get_page(pd["id"])["status"] == "ACTIVE"
        mr_after = validate_success(api.get_merge_request(mr["id"], ADMIN))
        assert mr_after["status"] == "PENDING"
