"""Leases, disclosure dimensions, and payment-record rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    attach_lease,
    create_lease_payload,
    create_payment_record_payload,
    get_success_data,
    make_buyer_headers,
    make_seller_headers,
    setup_buyer,
    setup_certified_listing,
    setup_draft_listing,
    setup_seller,
    validate_error,
    validate_success,
)


class TestLeasePeriodOverlap:
    def test_overlapping_active_lease_rejected(self, api):
        """PRD §3.3: "Creating a lease is rejected with `ERR_LEASE_PERIOD_OVERLAP`
        if an existing `ACTIVE` lease on the same listing has a half-open
        occupancy interval — from its `lease_start` up to but not including its
        `lease_end` — that intersects the new lease's half-open interval."

        Design: Difficulty/resource_temporal_overlap/lease_period_overlap_half_open
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        resp = api.create_lease(
            listing["id"],
            create_lease_payload(
                tenant_alias="T-O2",
                lease_start="2026-06-01T00:00:00Z",
                lease_end="2027-06-01T00:00:00Z",
            ),
            seller_h,
        )
        validate_error(resp, ApiErrorId.ERR_LEASE_PERIOD_OVERLAP)

    def test_adjacent_lease_at_existing_end_permitted(self, api):
        """PRD §3.3: "Pure adjacency is permitted: a new lease starting exactly
        when the existing one ends, or ending exactly when the existing one
        starts, does not overlap."

        Design: Difficulty/resource_temporal_overlap/lease_period_overlap_half_open
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        attach_lease(seller, listing)  # [2026-01-01, 2027-01-01)
        seller_h = make_seller_headers(seller["id"])
        resp = api.create_lease(
            listing["id"],
            create_lease_payload(
                tenant_alias="T-O3",
                lease_start="2027-01-01T00:00:00Z",
                lease_end="2028-01-01T00:00:00Z",
            ),
            seller_h,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "ACTIVE"


class TestLeaseDisclosureDimensions:
    def test_redact_requires_confidential_flag(self, api):
        """PRD §3.3: "The disclosure dimension moves from `PENDING` to `DISCLOSED`
        when the seller discloses the lease — permitted only while the tenancy
        dimension is `ACTIVE` — and from `PENDING` to `REDACTED` when the seller
        redacts it, permitted only when the listing's `seller_asks_confidential`
        flag is true."

        Design: Corner/validations/redact_requires_confidential_flag
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller, seller_asks_confidential=False)
        lease = attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        resp = api.transition_lease(lease["id"], {"action": "REDACT"}, seller_h)
        validate_error(resp, ApiErrorId.ERR_PRECONDITION)
        current = get_success_data(api.get_lease(lease["id"], seller_h))
        assert current["disclosure_status"] == "PENDING"

    def test_redacted_lease_can_be_disclosed_again(self, api):
        """PRD §3.3: "A redacted lease can later be disclosed (`REDACTED` →
        `DISCLOSED`, again requiring the tenancy dimension to be `ACTIVE`), so
        the disclosure dimension may cycle pending-to-redacted-to-disclosed
        independently of tenancy."

        Design: Corner/validations/redact_requires_confidential_flag
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller, seller_asks_confidential=True)
        lease = attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        redacted = get_success_data(
            api.transition_lease(lease["id"], {"action": "REDACT"}, seller_h)
        )
        assert redacted["disclosure_status"] == "REDACTED"
        disclosed = get_success_data(
            api.transition_lease(lease["id"], {"action": "DISCLOSE"}, seller_h)
        )
        assert disclosed["disclosure_status"] == "DISCLOSED"
        assert disclosed["status"] == "ACTIVE"


class TestPaymentLateGraceBoundary:
    def test_payment_exactly_at_grace_boundary_not_late(self, api):
        """PRD §3.3: "Every payment record computes a `late` flag: the record is
        late when `paid_date` is set and falls strictly more than 5 days after
        `due_date`; a payment landing exactly at the five-day mark is not late."

        Design: Difficulty/boundary_precision_check/payment_late_grace_boundary
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        lease = attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        resp = api.create_payment_record(
            lease["id"],
            create_payment_record_payload(
                due_date="2026-01-01T00:00:00Z",
                paid_date="2026-01-06T00:00:00Z",
                amount_cents=100_000,
            ),
            seller_h,
        )
        record = validate_success(resp, expected_status=201)
        assert record["late"] is False

    def test_payment_one_second_past_grace_is_late(self, api):
        """PRD §3.3: "Every payment record computes a `late` flag: the record is
        late when `paid_date` is set and falls strictly more than 5 days after
        `due_date`; a payment landing exactly at the five-day mark is not late."

        Design: Difficulty/boundary_precision_check/payment_late_grace_boundary
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        lease = attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        resp = api.create_payment_record(
            lease["id"],
            create_payment_record_payload(
                due_date="2026-02-01T00:00:00Z",
                paid_date="2026-02-06T00:00:01Z",
                amount_cents=100_000,
            ),
            seller_h,
        )
        record = validate_success(resp, expected_status=201)
        assert record["late"] is True

    def test_late_computed_and_record_omits_version(self, api):
        """PRD §2.4: "`PaymentRecord` is the sole exception: it carries only `id`
        and `created_at` — both `updated_at` and `version` are absent on payment
        records."

        Design: Corner/entities/payment_record_computed_late_ignores_input
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        lease = attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        resp = api.create_payment_record(
            lease["id"],
            create_payment_record_payload(
                due_date="2026-01-01T00:00:00Z",
                paid_date="2026-01-11T00:00:00Z",
                amount_cents=100_000,
            ),
            seller_h,
        )
        record = validate_success(resp, expected_status=201)
        assert record["late"] is True
        assert "version" not in record
        assert "updated_at" not in record


class TestPaymentDueMonthBucket:
    def test_second_record_in_same_month_rejected(self, api):
        """PRD §3.3: "Each lease accepts at most one payment record per due
        month: creating a record is rejected with `ERR_DUPLICATE_DUE_MONTH` if
        another record on the same lease already has a `due_date` falling in
        the same UTC calendar month, regardless of the day or time component."

        Design: Difficulty/resource_temporal_overlap/payment_record_due_month_bucket
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        lease = attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        api.create_payment_record(
            lease["id"],
            create_payment_record_payload(
                due_date="2026-03-05T00:00:00Z",
                paid_date="2026-03-05T00:00:00Z",
                amount_cents=100_000,
            ),
            seller_h,
        )
        resp = api.create_payment_record(
            lease["id"],
            create_payment_record_payload(due_date="2026-03-25T00:00:00Z", amount_cents=100_000),
            seller_h,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DUE_MONTH)

    def test_record_in_next_month_accepted(self, api):
        """PRD §3.3: "Each lease accepts at most one payment record per due
        month: creating a record is rejected with `ERR_DUPLICATE_DUE_MONTH` if
        another record on the same lease already has a `due_date` falling in
        the same UTC calendar month, regardless of the day or time component."

        Design: Difficulty/resource_temporal_overlap/payment_record_due_month_bucket
        """
        seller = setup_seller()
        listing = setup_draft_listing(seller)
        lease = attach_lease(seller, listing)
        seller_h = make_seller_headers(seller["id"])
        api.create_payment_record(
            lease["id"],
            create_payment_record_payload(
                due_date="2026-03-05T00:00:00Z",
                paid_date="2026-03-05T00:00:00Z",
                amount_cents=100_000,
            ),
            seller_h,
        )
        resp = api.create_payment_record(
            lease["id"],
            create_payment_record_payload(due_date="2026-04-01T00:00:00Z", amount_cents=100_000),
            seller_h,
        )
        record = validate_success(resp, expected_status=201)
        assert record["due_date"].startswith("2026-04-01")
