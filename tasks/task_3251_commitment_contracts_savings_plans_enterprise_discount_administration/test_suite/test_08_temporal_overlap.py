"""Tests for resource temporal overlap: amendment windows and capacity quota."""
from test_helpers import (
    validate_error,
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    create_org,
    create_active_agreement,
    create_amendment,
    create_plan,
    get_agreement,
    ApiErrorId,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()


class TestAmendmentHalfOpenWindows:
    """Adjacency is not overlap; intersection is."""

    def _setup(self):
        org = create_org(name="Am Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10},
                   {"service_family": "STORAGE", "threshold_cents": 0, "rate": 0.05}],
            committed_spend_cents=1000000,
        )
        v = get_agreement(agr["id"])["version"]
        create_amendment(
            agr["id"], v,
            service_family="COMPUTE", discount_rate=0.15,
            effective_from="2026-10-01T00:00:00Z",
            effective_to="2026-11-01T00:00:00Z",
        )
        return org, agr

    def test_adjacent_window_accepted(self, api):
        """PRD section 3.3: "Two amendments on the same agreement and the same
        service family may not overlap under half-open semantics; adjacency, where
        one amendment's `effective_to` equals the other's `effective_from`, is
        explicitly not an overlap."

        Design: Difficulty/resource_temporal_overlap/amendment_half_open_adjacency_is_not_overlap_but_intersection_is
        """
        _, agr = self._setup()
        v = get_agreement(agr["id"])["version"]
        resp = api.create_pricing_amendment(
            {
                "agreement_id": agr["id"], "service_family": "COMPUTE",
                "discount_rate": 0.20,
                "effective_from": "2026-11-01T00:00:00Z",
                "effective_to": "2026-12-01T00:00:00Z",
                "expected_agreement_version": v,
            },
            FINANCE,
        )
        data = validate_success(resp, expected_status=201)
        # PRD section 5: timestamps are rendered with three fractional digits,
        # so the stored value is the canonical form of the submitted instant.
        assert data["effective_from"] == "2026-11-01T00:00:00.000Z"

    def test_intersecting_window_rejected(self, api):
        """PRD section 3.3: "Two amendments on the same agreement and the same
        service family may not overlap under half-open semantics; adjacency, where
        one amendment's `effective_to` equals the other's `effective_from`, is
        explicitly not an overlap. A violating create is rejected with
        `ERR_AMENDMENT_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/amendment_half_open_adjacency_is_not_overlap_but_intersection_is
        """
        _, agr = self._setup()
        v = get_agreement(agr["id"])["version"]
        resp = api.create_pricing_amendment(
            {
                "agreement_id": agr["id"], "service_family": "COMPUTE",
                "discount_rate": 0.25,
                "effective_from": "2026-10-31T00:00:00Z",
                "effective_to": "2026-11-15T00:00:00Z",
                "expected_agreement_version": v,
            },
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_WINDOW_OVERLAP)
        assert resp.status_code == 422


class TestReservedCapacityAggregateQuota:
    """Quota is an aggregate over overlapping windows, not pairwise."""

    def _setup(self):
        org = create_org(name="Rc Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=10)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        return org, agr

    def test_overlapping_aggregate_sum_exceeding_quota_rejected(self, api):
        """PRD section 3.4: "For reserved capacity plans, the structural quota
        applies: the sum of `units` over the org's `ACTIVE` reserved-capacity
        plans of the same `instance_family` whose term windows intersect the new
        plan's window, plus the new plan's `units`, must not exceed the org's
        `capacity_quota_units`, else `ERR_CAPACITY_QUOTA_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/reserved_capacity_aggregate_quota_counts_overlapping_units_not_pairwise
        """
        org, agr = self._setup()
        create_plan(
            org["id"], agr["id"], type="RESERVED_CAPACITY", instance_family="GPU",
            units=6, hourly_commitment_cents=50, plan_discount_rate=0.40,
            term_start="2026-09-01T00:00:00Z", term_end="2026-11-01T00:00:00Z",
        )
        resp = api.create_commitment_plan(
            {
                "org_id": org["id"], "agreement_id": agr["id"],
                "type": "RESERVED_CAPACITY", "instance_family": "GPU", "units": 6,
                "hourly_commitment_cents": 50, "plan_discount_rate": 0.40,
                "term_start": "2026-10-01T00:00:00Z",
                "term_end": "2026-12-01T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_QUOTA_EXCEEDED)
        assert resp.status_code == 422, (
            "aggregate over the October intersection is 6 + 6 = 12 > quota 10"
        )

    def test_adjacent_window_after_rejection_succeeds(self, api):
        """PRD section 3.4: "For reserved capacity plans, the structural quota
        applies: the sum of `units` over the org's `ACTIVE` reserved-capacity
        plans of the same `instance_family` whose term windows intersect the new
        plan's window, plus the new plan's `units`, must not exceed the org's
        `capacity_quota_units`, else `ERR_CAPACITY_QUOTA_EXCEEDED` (HTTP 422)."
        PRD section 3.3: "Two amendments on the same agreement and the same
        service family may not overlap under half-open semantics; adjacency, where
        one amendment's `effective_to` equals the other's `effective_from`, is
        explicitly not an overlap."

        Design: Difficulty/resource_temporal_overlap/reserved_capacity_aggregate_quota_counts_overlapping_units_not_pairwise
        """
        org, agr = self._setup()
        create_plan(
            org["id"], agr["id"], type="RESERVED_CAPACITY", instance_family="GPU",
            units=6, hourly_commitment_cents=50, plan_discount_rate=0.40,
            term_start="2026-09-01T00:00:00Z", term_end="2026-11-01T00:00:00Z",
        )
        validate_error(
            api.create_commitment_plan(
                {
                    "org_id": org["id"], "agreement_id": agr["id"],
                    "type": "RESERVED_CAPACITY", "instance_family": "GPU",
                    "units": 6, "hourly_commitment_cents": 50,
                    "plan_discount_rate": 0.40,
                    "term_start": "2026-10-01T00:00:00Z",
                    "term_end": "2026-12-01T00:00:00Z",
                },
                ADMIN,
            ),
            ApiErrorId.ERR_CAPACITY_QUOTA_EXCEEDED,
        )
        # r3 starts exactly at r1's term_end (adjacent, no overlap) and r2 was
        # rejected so it never contributes.
        data = validate_success(
            api.create_commitment_plan(
                {
                    "org_id": org["id"], "agreement_id": agr["id"],
                    "type": "RESERVED_CAPACITY", "instance_family": "GPU",
                    "units": 4, "hourly_commitment_cents": 50,
                    "plan_discount_rate": 0.40,
                    "term_start": "2026-11-01T00:00:00Z",
                    "term_end": "2026-12-01T00:00:00Z",
                },
                ADMIN,
            ),
            expected_status=201,
        )
        assert data["status"] == "ACTIVE"
