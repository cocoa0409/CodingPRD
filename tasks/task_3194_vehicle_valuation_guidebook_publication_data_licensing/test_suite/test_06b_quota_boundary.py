"""Difficulty rule: boundary_precision_check — quota cutoff variant.

Zero-count/cutoff edge on the billing event count: the event that would
exceed monthly_event_quota is rejected and records no row.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_published_edition, setup_active_agreement, make_licensee_headers,
    ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def _setup_agreement_with_quota_one():
    env = setup_published_edition(segment="SEDAN", price_cents=2000000)
    lic = setup_active_agreement(permitted_uses=("DISPLAY",),
                                 monthly_event_quota=1500)
    agreement = lic["agreement"]
    current = validate_success(
        api_client.get_license_agreement(agreement["id"], ADMIN), 200)
    validate_success(api_client.patch_license_agreement(
        agreement["id"],
        {"monthly_event_quota": 1, "expected_version": current["version"]},
        ADMIN), 200)
    return env, agreement


class TestQuotaFirstBillableEventAndQuotaCutoff:
    def test_first_read_within_quota_records_event(self, api):
        """PRD §3.8: "When a Licensee caller reads an edition, the server
        records an EDITION_READ event" and "the monthly event count must be
        below monthly_event_quota — recording the event that would exceed the
        quota is rejected with ERR_QUOTA_EXCEEDED (HTTP 422) and no event row
        is written."

        With quota 1 the first read is within quota and records exactly one
        event row.

        Design: Difficulty/boundary_precision_check/quota_first_billable_event_and_quota_cutoff
        """
        env, agreement = _setup_agreement_with_quota_one()
        licensee = make_licensee_headers(agreement["id"])
        validate_success(api.get_valuation_edition(
            env["edition"]["id"], licensee, params={"purpose": "DISPLAY"}), 200)
        data, meta = validate_paginated(
            api.list_agreement_events(agreement["id"], ADMIN))
        assert meta["total_count"] == 1
        assert data[0]["event_type"] == "EDITION_READ"

    def test_event_beyond_quota_rejected_and_no_row_written(self, api):
        """PRD §3.8: "the monthly event count must be below
        monthly_event_quota — recording the event that would exceed the quota
        is rejected with ERR_QUOTA_EXCEEDED (HTTP 422) and no event row is
        written."

        With quota 1 the second read in the same calendar month is the
        (quota+1)-th event: it is rejected and the count stays at exactly 1.

        Design: Difficulty/boundary_precision_check/quota_first_billable_event_and_quota_cutoff
        """
        env, agreement = _setup_agreement_with_quota_one()
        licensee = make_licensee_headers(agreement["id"])
        validate_success(api.get_valuation_edition(
            env["edition"]["id"], licensee, params={"purpose": "DISPLAY"}), 200)

        res = api.get_valuation_edition(
            env["edition"]["id"], licensee, params={"purpose": "DISPLAY"})
        validate_error(res, ApiErrorId.ERR_QUOTA_EXCEEDED.value)
        data, meta = validate_paginated(
            api.list_agreement_events(agreement["id"], ADMIN))
        assert meta["total_count"] == 1, (
            "rejected event must not be recorded; count stays at the quota")
