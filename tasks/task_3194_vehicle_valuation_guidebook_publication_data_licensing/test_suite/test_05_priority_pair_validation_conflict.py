"""Difficulty rule: priority_pair_validation_conflict.

When two checks could reject the same request, the fixed validation order of
PRD §2.10 decides which error surfaces.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_published_edition, setup_redeemed_offer_with_dispute,
    setup_active_agreement, make_licensee_headers, make_dealer_headers,
    make_consumer_headers, create_dispute_payload, ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


class TestStateBeforeFiscalOnLicenseeEditionRead:
    def test_suspended_agreement_reports_license_inactive_not_quota(self, api):
        """PRD §2.10: "When several checks could reject the same request, they
        are evaluated in a fixed priority order so that the surfaced error is
        deterministic. Authentication (missing or unknown role header) comes
        first, then authorization (role not permitted), then existence (path
        or body references failing to resolve), then idempotency-key
        conflicts, then state-precondition failures (ERR_INVALID_STATE), then
        license gates (ERR_LICENSE_INACTIVE), then business rules in their
        documented order (funding source eligibility, confidence gate,
        cadence, offer expiry, quota, permitted use, archived region), then
        input shape (ERR_INVALID_INPUT), then OCC staleness
        (ERR_STALE_VERSION), then duplicate-dispute uniqueness, then
        shift-in-past, then the edition-withdrawal open-offer guard."
        License-inactive therefore precedes quota.

        Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_licensee_edition_read
        """
        env = setup_published_edition(segment="SEDAN", price_cents=2000000)
        edition = env["edition"]
        lic = setup_active_agreement(permitted_uses=("DISPLAY",),
                                     monthly_event_quota=1500)
        agreement = lic["agreement"]
        # Amend quota down to 1 under OCC, then consume the single event.
        current = validate_success(
            api.get_license_agreement(agreement["id"], ADMIN), 200)
        validate_success(api.patch_license_agreement(
            agreement["id"],
            {"monthly_event_quota": 1,
             "expected_version": current["version"]},
            ADMIN), 200)
        licensee = make_licensee_headers(agreement["id"])
        validate_success(api.get_valuation_edition(
            edition["id"], licensee, params={"purpose": "DISPLAY"}), 200)
        # Suspend: now both license-inactive AND quota-exceeded would apply.
        validate_success(api.suspend_license_agreement(agreement["id"], ADMIN), 200)

        res = api.get_valuation_edition(
            edition["id"], licensee, params={"purpose": "DISPLAY"})
        validate_error(res, ApiErrorId.ERR_LICENSE_INACTIVE.value)

    def test_rejected_licensee_read_records_no_event(self, api):
        """PRD §3.8: "the monthly event count must be below
        monthly_event_quota — recording the event that would exceed the quota
        is rejected with ERR_QUOTA_EXCEEDED (HTTP 422) and no event row is
        written." A read rejected by the earlier license-inactive gate
        likewise records no event.

        Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_licensee_edition_read
        """
        env = setup_published_edition(segment="SEDAN", price_cents=2000000)
        edition = env["edition"]
        lic = setup_active_agreement(permitted_uses=("DISPLAY",),
                                     monthly_event_quota=1500)
        agreement = lic["agreement"]
        current = validate_success(
            api.get_license_agreement(agreement["id"], ADMIN), 200)
        validate_success(api.patch_license_agreement(
            agreement["id"],
            {"monthly_event_quota": 1,
             "expected_version": current["version"]},
            ADMIN), 200)
        licensee = make_licensee_headers(agreement["id"])
        validate_success(api.get_valuation_edition(
            edition["id"], licensee, params={"purpose": "DISPLAY"}), 200)
        validate_success(api.suspend_license_agreement(agreement["id"], ADMIN), 200)
        validate_error(
            api.get_valuation_edition(
                edition["id"], licensee, params={"purpose": "DISPLAY"}),
            ApiErrorId.ERR_LICENSE_INACTIVE.value)

        data, meta = validate_paginated(
            api.list_agreement_events(agreement["id"], ADMIN))
        assert meta["total_count"] == 1, (
            "no event may be recorded for the rejected read")


class TestTemporalBeforeReferentialOnExpiredRedeemedOffer:
    def test_second_dispute_on_same_offer_rejected_duplicate(self, api):
        """PRD §3.7: "at most one dispute per offer may be OPEN at any time —
        a second open attempt against the same offer is rejected with
        ERR_DUPLICATE_DISPUTE (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_before_referential_on_expired_redeemed_offer
        """
        env = setup_redeemed_offer_with_dispute(segment="SEDAN",
                                                price_cents=2000000)
        offer = env["offer"]
        consumer = env["consumer"]
        # Advance the clock past the offer's expiry — the duplicate-dispute
        # rule still owns the second open attempt.
        validate_success(
            api.set_clock("2026-09-20T00:00:00Z", ADMIN), 200)

        res = api.create_dispute(
            {"offer_id": offer["id"], "reason_code": "WRONG_CONDITION"},
            make_consumer_headers(consumer["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_DISPUTE.value)

    def test_expired_offer_rejections_use_temporal_or_state_error(self, api):
        """PRD §3.6: "Inspection requires the server clock to be at or before
        expires_at; an expired offer rejects inspection with ERR_OFFER_EXPIRED
        (HTTP 422)." and PRD §3.7: "at most one dispute per offer may be OPEN
        at any time — a second open attempt against the same offer is
        rejected with ERR_DUPLICATE_DISPUTE (HTTP 409)."

        On an offer already REDEEMED and past expiry with an OPEN dispute:
        redeem again fails the state precondition (ERR_INVALID_STATE, it is
        already REDEEMED) and the second dispute fails with
        ERR_DUPLICATE_DISPUTE — each rule owns its own endpoint.

        Design: Difficulty/priority_pair_validation_conflict/temporal_before_referential_on_expired_redeemed_offer
        """
        env = setup_redeemed_offer_with_dispute(segment="SEDAN",
                                                price_cents=2000000)
        offer = env["offer"]
        source = env["source"]
        consumer = env["consumer"]
        validate_success(
            api.set_clock("2026-09-20T00:00:00Z", ADMIN), 200)

        redeem_res = api.redeem_cash_offer(
            offer["id"], make_dealer_headers(source["id"]))
        validate_error(redeem_res, ApiErrorId.ERR_INVALID_STATE.value)

        dup_res = api.create_dispute(
            create_dispute_payload(offer["id"], reason_code="WRONG_CONDITION"),
            make_consumer_headers(consumer["id"]))
        validate_error(dup_res, ApiErrorId.ERR_DUPLICATE_DISPUTE.value)
