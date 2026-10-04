"""Role-based access, ownership isolation and the two optimistic-concurrency guards."""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import create_listing_payload, next_imei
from test_helpers.test_users import make_seller_headers


class TestAccessControl:
    def test_missing_credentials_are_refused_before_existence(self, api):
        """PRD §2.1: "A request that omits either header on an endpoint that requires credentials is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.11: "Priority 1 is the credential check described in §2.1 (`ERR_UNAUTHENTICATED`, 401)."

        Design: Corner/validations/unauthenticated_request_without_role_header
        """
        response = api.get(
            "/v1/sellers/00000000-0000-4000-8000-000000000000", headers={}
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_role_without_the_grant_is_refused(self, api):
        """PRD §2.1: "A request whose role is not listed against the target endpoint is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)"
        PRD §4: "| GET | `/v1/sellers/{id}` | Read one seller with its tier and exposure floor | PlatformAdmin, ComplianceReviewer, ClaimAdjudicator, Seller |"

        Design: Corner/validations/seller_read_by_unauthorized_role
        """
        seller = fx.create_approved_seller()
        response = fx.api_client.get_seller(seller["id"], fx.INSPECTOR)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        allowed = validate_success(fx.api_client.get_seller(seller["id"], fx.ADMIN))
        assert allowed["onboarding_state"] == "APPROVED"


class TestReferentialIntegrity:
    def test_body_foreign_keys_are_resolved_after_the_path_guard(self, api):
        """PRD §2.11: "Priority 5 is foreign-key resolution for body-supplied references — `seller_id`, `listing_id`, `originated_claim_id`, and `replacement_listing_id` must each resolve to an existing row (`ERR_REFERENCED_ENTITY_NOT_FOUND`, 404)."

        Design: Corner/validations/listing_create_referential_seller_missing
        """
        fx.set_clock("2026-09-02T00:00:00Z")
        fx.create_active_definition()
        response = fx.api_client.create_verification(
            {
                "seller_id": "00000000-0000-4000-8000-000000000000",
                "listing_id": "00000000-0000-4000-8000-000000000000",
                "rationale_code": "GRADE_GHOST",
                "ordered_cosmetic_grade": "GOOD",
            },
            fx.REVIEWER,
        )
        validate_error(response, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND, 404)

        _, meta = validate_paginated(fx.api_client.list_verifications(fx.ADMIN))
        assert meta["total_count"] == 0


class TestOwnershipIsolation:
    def test_a_seller_may_not_list_on_another_sellers_behalf(self, api):
        """PRD §2.1: "When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a `Seller` compare the resource's foreign-key field — `seller_id` on a listing — to `X-User-ID`."

        Design: Corner/cross_cutting_complexity_layers/multi_tenancy_seller_cannot_list_for_another_seller
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        fx.create_active_definition()
        seller_a = fx.create_approved_seller(clock="2026-12-01T00:00:00Z", legal_name="Refurb Isolation A")
        seller_c = fx.create_approved_seller(clock="2026-12-01T00:00:00Z", legal_name="Refurb Isolation C")
        existing = fx.create_listing(seller_c["id"])

        response = fx.api_client.create_listing(
            seller_c["id"],
            create_listing_payload(imei=next_imei(), part_provenance="OEM_ONLY",
                                   provenance_doc_digest=None),
            make_seller_headers(seller_a["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        rows, meta = fx.list_seller_listings(seller_c["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == existing["id"]


class TestOptimisticConcurrency:
    def test_resubmission_with_a_stale_seller_version_is_refused(self, api):
        """PRD §2.10: "Re-submitting a listing for review, and closing a service-score section, each carry a non-optional `expected_seller_version` input field in the request body. When the supplied value does not equal the referenced seller's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "a client that holds a pre-recompute view of the seller is refused with `ERR_STALE_VERSION` (HTTP 412) rather than allowed to re-submit against stale assumptions"

        Design: Corner/cross_cutting_complexity_layers/occ_submit_with_stale_seller_version
        """
        scenario = fx.setup_listed_device(clock="2026-12-01T00:00:00Z")
        listing_id = scenario["listing"]["id"]
        seller_id = scenario["seller"]["id"]

        validate_success(fx.delist_listing(listing_id))
        live_version = fx.current_seller_version(seller_id)

        stale = fx.resubmit_listing(listing_id, seller_id, live_version - 1)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        after = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert after["listing_state"] == "DELISTED"

        fresh = fx.resubmit_listing(listing_id, seller_id, live_version)
        validate_success(fresh)

    def test_section_close_with_a_stale_seller_version_is_refused(self, api):
        """PRD §3.7: "Because a seller closing a section carries the same freshness risk described in §2.10, the close request must carry `expected_seller_version`; a mismatch is refused with `ERR_STALE_VERSION` (412), since the section's aggregates and the seller's exposure floor are read from one instant and a stale seller view would pin the floor to a superseded value."

        Design: Corner/cross_cutting_complexity_layers/occ_close_section_with_stale_seller_version
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        section = fx.open_section(seller["id"], "2026-01-05T00:00:00Z")

        before = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        response = fx.close_section(section["id"], before["version"] - 1)
        validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

        unchanged = fx.read_section(section["id"])
        assert unchanged["section_state"] == "OPEN"

        after = validate_success(api.get(f"/v1/sellers/{seller['id']}", headers=fx.ADMIN))
        assert after["performance_tier"] == before["performance_tier"]

    def test_section_younger_than_ninety_days_cannot_close(self, api):
        """PRD §3.7: "A section may close only once it is at least 90 calendar days old, measured from `section_opened_on`, and only when no claim routed to that seller is `APPROVED` and unresolved"
        PRD §3.7: "A section closed sooner than 90 days after it opened reports the too-young code."

        Design: Corner/state_machines/service_score_close_without_section_age
        """
        fx.set_clock("2026-12-01T00:00:00Z")
        seller = fx.create_approved_seller(clock="2026-12-01T00:00:00Z")
        listing = fx.create_listing(seller["id"])
        fx.approve_listing(listing["id"])
        section = fx.open_section(seller["id"], "2026-11-15T00:00:00Z")

        version = fx.current_seller_version(seller["id"])
        response = fx.close_section(section["id"], version)
        validate_error(response, ApiErrorId.ERR_SECTION_TOO_YOUNG, 409)

        unchanged = fx.read_section(section["id"])
        assert unchanged["section_state"] == "OPEN"


class TestPartialFailure:
    def test_a_refused_submission_does_not_roll_back_an_earlier_success(self, api):
        """PRD §2.11: "The business-safety band follows: blocklist screening of the device IMEI (`ERR_DEVICE_BLOCKLISTED`, 422) at priority 6"
        PRD §3.2: "The `imei` must appear on neither the stolen-device blocklist nor the counterfeit blocklist, or the submission fails with `ERR_DEVICE_BLOCKLISTED`."

        Design: Corner/cross_cutting_complexity_layers/bulk_family_partial_failure_is_per_call
        """
        scenario = fx.setup_listed_device(clock="2026-12-01T00:00:00Z")
        seller_id = scenario["seller"]["id"]

        admitted = validate_success(
            fx.api_client.create_listing(
                seller_id,
                create_listing_payload(imei=next_imei(), part_provenance="OEM_ONLY",
                                       provenance_doc_digest=None),
                make_seller_headers(seller_id),
            ),
            201,
        )
        assert admitted["listing_state"] == "UNDER_REVIEW"

        # The IMEI must sit on a blocklist for the screening rule to fire; the
        # blocklists are operator-owned policy filed through the catalogue
        # endpoints, so the test files the entry rather than assuming a seed.
        blocked_imei = next_imei()
        validate_success(
            fx.api_client.add_blocklist_entry("stolen", blocked_imei, fx.ADMIN), 201
        )

        refused = fx.api_client.create_listing(
            seller_id,
            create_listing_payload(imei=blocked_imei, part_provenance="OEM_ONLY",
                                   provenance_doc_digest=None),
            make_seller_headers(seller_id),
        )
        validate_error(refused, ApiErrorId.ERR_DEVICE_BLOCKLISTED, 422)

        rows, meta = fx.list_seller_listings(seller_id)
        non_withdrawn = [row for row in rows if row["listing_state"] != "WITHDRAWN"]
        assert len(non_withdrawn) == 2, (
            "the refusal is per-call and does not roll back the earlier success"
        )


class TestCascadeVisibility:
    def test_cascade_effects_are_readable_immediately(self, api):
        """PRD §2.4: "`version` is a system-managed integer that increments by exactly one on every mutation of the row, including mutations performed by cascades rather than by direct client request"
        PRD §3.9: "The seller's `blocklisted` flag is set true, `onboarding_state` and `performance_tier` both become `SUSPENDED`, and the cascade runs: every listing of that seller that is `LISTED` becomes `SUSPENDED`"

        Design: Corner/consistency_model/cascade_visibility_is_immediate_within_same_request
        """
        scenario = fx.setup_listed_device(clock="2026-12-01T00:00:00Z")
        seller_id, listing_id = scenario["seller"]["id"], scenario["listing"]["id"]
        listing_before = scenario["listing"]["version"]

        validate_success(
            fx.api_client.blocklist_seller(
                seller_id, fx.blocklist_payload(finding="CONFIRMED_STOLEN"), fx.REVIEWER
            )
        )

        listing = validate_success(api.get(f"/v1/listings/{listing_id}", headers=fx.ADMIN))
        assert listing["listing_state"] == "SUSPENDED"
        assert listing["version"] > listing_before, "the cascade mutation advances the listing version"

        seller = validate_success(api.get(f"/v1/sellers/{seller_id}", headers=fx.ADMIN))
        assert seller["performance_tier"] == "SUSPENDED"


from prd_bench_local_runner.testing import validate_paginated  # noqa: E402