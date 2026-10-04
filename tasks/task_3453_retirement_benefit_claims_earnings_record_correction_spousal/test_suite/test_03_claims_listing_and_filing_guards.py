"""Claim filing guards, listing pagination defaults, and status filtering."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_claim_payload,
    create_relationship,
    create_worker,
    file_claim,
    make_claimant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestRelationshipIdCondition:
    def test_claim_create_auxiliary_requires_relationship(self, api, claims_specialist_headers):
        """PRD §3.4: "A `relationship_id` is required for the three auxiliary types
        and forbidden for `RETIREMENT`; either violation is rejected with
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/claim_create_auxiliary_requires_relationship
        """
        worker = create_worker(full_name="Conditional Worker")

        resp1 = api.create_claim(
            create_claim_payload(worker["id"], "SPOUSAL", "2026-06"),
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST, 400)

        spouse = create_worker(full_name="Rel Dummy")
        rel = create_relationship(worker["id"], spouse["id"], "CURRENT_SPOUSE", "2000-01-01")
        resp2 = api.create_claim(
            create_claim_payload(
                worker["id"], "RETIREMENT", "2026-06", relationship_id=rel["id"]
            ),
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST, 400)

        claims, meta = validate_paginated(
            api.list_claims(claims_specialist_headers, params={"worker_id": worker["id"]})
        )
        assert claims == [], "both filings were rejected; no claim may be persisted"


class TestClaimsListing:
    def test_claims_list_pagination_defaults(self, api, claims_specialist_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter sets the number of items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/claims_list_pagination_defaults
        """
        w1 = create_worker(full_name="Page One")
        w2 = create_worker(full_name="Page Two")
        c1 = file_claim(w1["id"], "RETIREMENT", "2026-06")
        c2 = file_claim(w2["id"], "RETIREMENT", "2026-06")

        claims, meta = validate_paginated(api.list_claims(claims_specialist_headers))
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 2 and meta["has_more"] is False
        assert {c["id"] for c in claims} == {c1["id"], c2["id"]}

        page, meta2 = validate_paginated(
            api.list_claims(claims_specialist_headers, params={"limit": 1})
        )
        assert len(page) == 1
        assert meta2["total_count"] == 2 and meta2["has_more"] is True

    def test_claims_list_filter_by_status(self, api, claims_specialist_headers):
        """PRD §3.4: "The claims listing supports optional `worker_id`,
        `relationship_id`, and `status` filters alongside the standard pagination
        parameters."

        Design: Corner/entities/claims_list_filter_by_status
        """
        w1 = create_worker(full_name="Filter One")
        c1 = file_claim(w1["id"], "RETIREMENT", "2026-06")
        w2 = create_worker(full_name="Filter Two")
        c2 = file_claim(w2["id"], "RETIREMENT", "2026-06")
        deny_resp = api.deny_claim(c2["id"], "not insured", TEST_USERS["claims_specialist_headers"])
        validate_success(deny_resp)

        denied, meta = validate_paginated(
            api.list_claims(claims_specialist_headers, params={"status": "DENIED"})
        )
        assert [c["id"] for c in denied] == [c2["id"]]

        filed, _ = validate_paginated(
            api.list_claims(claims_specialist_headers, params={"status": "FILED"})
        )
        assert [c["id"] for c in filed] == [c1["id"]]


class TestFilingGuards:
    def test_duplicate_active_claim_rejected(self, api):
        """PRD §3.4: "at most one non-terminal claim may exist per worker and
        claim type — `WITHDRAWN` and `TERMINATED` claims do not block re-filing —
        and a duplicate is rejected with `ERR_DUPLICATE_ACTIVE_CLAIM` (409)".

        Design: Corner/validations/duplicate_active_claim_rejected
        """
        worker = create_worker(full_name="Dup Claim")
        first = file_claim(worker["id"], "RETIREMENT", "2026-06")

        resp = api.create_claim(
            create_claim_payload(worker["id"], "RETIREMENT", "2026-07"),
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CLAIM, 409)

        unchanged = validate_success(api.get_claim(first["id"], CS))
        assert unchanged["status"] == "FILED"

    def test_retirement_claim_for_deceased_worker_rejected(self, api, claims_specialist_headers):
        """PRD §3.4: "no new `RETIREMENT` claim may be filed for a `DECEASED`
        worker, rejected with `ERR_WORKER_DECEASED` (409)".

        Design: Corner/validations/retirement_claim_for_deceased_worker_rejected
        """
        worker = create_worker(full_name="Posthumous")
        validate_success(
            api.report_death(worker["id"], "2026-08-01", claims_specialist_headers)
        )

        resp = api.create_claim(
            create_claim_payload(worker["id"], "RETIREMENT", "2026-06"),
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WORKER_DECEASED, 409)
