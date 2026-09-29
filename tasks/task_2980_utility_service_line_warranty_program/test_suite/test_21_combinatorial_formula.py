"""Single formulas that fuse several independent inputs.

The contractor selection score fuses three entity inputs into one ranking, and
the cancellation proration fuses four separately rounded monthly shares into one
earned premium.
"""

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.test_users import (
    CUSTOMER_SERVICE_REP,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
)


class TestSelectionScoreCombinesThreeInputs:
    """No single component decides the winner."""

    def test_score_combines_sla_capacity_and_rate(self, api):
        """The candidate leading on the heaviest input still loses 60.25 to 82.5.

        PRD: "For an `URGENT` or `ROUTINE` claim, the weights are 0.45 on `sla_compliance_pct`, 0.35 on capacity headroom and 0.20 on the rate component: cost and availability dominate, so a cheap, idle contractor with a mediocre record wins."

        Design: Difficulty/combinatorial_formula/contractor_selection_score_combines_sla_capacity_and_rate
        """
        world = fixtures.active_coverage(api)

        # Sitka leads on sla_compliance_pct but its rate floors the rate score to
        # zero and one open job halves its capacity headroom.
        sitka = fixtures.create_contractor(
            api,
            name="Sitka Utility Works",
            license_number="OR-PL-1201",
            hourly_rate_cents=25000,
            sla_compliance_pct=95,
            max_open_dispatches=2,
        )
        quarry = fixtures.create_contractor(
            api,
            name="Quarry Trenching",
            license_number="OR-EX-1202",
            hourly_rate_cents=4000,
            sla_compliance_pct=70,
            max_open_dispatches=4,
        )

        # One manual dispatch loads Sitka's book so its headroom is 50, not 100.
        loader = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="First leak, curb stop weeping steadily.",
        )
        loader_approved = fixtures.approve_claim(api, loader["id"])
        validate_success(
            api.create_dispatch(
                loader["id"],
                factories.manual_dispatch_payload(
                    loader_approved["version"], "2026-09-10T09:00:00.000Z", sitka["id"]
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )

        contested = fixtures.file_claim(
            api,
            world["enrollment_id"],
            defect_location="METER_TO_HOME",
            incident_description="Separate seep on the meter-to-home run.",
        )
        contested_approved = fixtures.approve_claim(api, contested["id"])

        loaded_sitka = validate_success(api.get_contractor(sitka["id"], OPERATIONS_ADMIN))
        assert loaded_sitka["sla_compliance_pct"] == 95
        assert loaded_sitka["open_dispatch_count"] == 1
        assert loaded_sitka["max_open_dispatches"] == 2
        assert loaded_sitka["hourly_rate_cents"] == 25000

        dispatch = validate_success(
            api.create_dispatch(
                contested["id"],
                factories.dispatch_payload(
                    contested_approved["version"], "2026-09-11T09:00:00.000Z"
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )

        assert dispatch["selection_mode"] == "AUTOMATIC"
        assert dispatch["contractor_id"] == quarry["id"]
        assert dispatch["contractor_id"] != sitka["id"]
        assert dispatch["selection_score"] == pytest.approx(82.5, abs=0.01)

        # Both candidates cleared the eligibility filter, so the loss is the score.
        _, meta = validate_paginated(
            api.list_contractors(
                OPERATIONS_ADMIN, params={"state_code": "OR", "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 2

        # The reservation uses the winner's own rate card.
        assert dispatch["estimated_benefit_cents"] == 144000


class TestProrationRoundingOrder:
    """Each overlapped month is rounded before the shares are summed."""

    def test_direct_bill_refund_rounds_each_month_before_summing(self, api):
        """A 2499-cent policy cancelled on 2026-11-18 refunds 18897, not 18861.

        PRD: "The monthly shares are 27 of August's 31 days giving 2177 cents, all 30 of September giving 2499, all 31 of October giving 2499, and 17 of November's 30 days giving 1416 — summing to 8591 cents earned."

        Design: Difficulty/combinatorial_formula/direct_bill_refund_rounds_each_month_before_summing
        """
        world = fixtures.active_coverage(api, clock="2026-09-10T00:00:00.000Z")
        enrollment = world["enrollment"]
        assert enrollment["term_start"] == "2026-08-05"
        assert enrollment["prepaid_amount_cents"] == 29988

        fixtures.set_clock(api, "2026-11-18T00:00:00.000Z", PLATFORM_ADMIN)

        cancelled = validate_success(
            api.cancel_enrollment(
                world["enrollment_id"],
                factories.cancellation_payload("2026-11-18"),
                CUSTOMER_SERVICE_REP,
            )
        )

        assert cancelled["cancellation_fee_cents"] == 2500
        assert cancelled["refund_cents"] == 18897
        assert cancelled["credit_cents"] == 0
        assert cancelled["premium_refunded_cents"] == 18897
        assert cancelled["coverage_status"] == "CANCELLED"
        assert cancelled["billing_status"] == "REFUND_ISSUED"
        assert cancelled["cancellation_effective_date"] == "2026-11-18"

        refund_rows, refund_meta = validate_paginated(
            api.list_ledger_entries(
                PLATFORM_ADMIN,
                params={
                    "enrollment_id": world["enrollment_id"],
                    "entry_type": "PRORATION_REFUND",
                },
            )
        )
        assert refund_meta["total_count"] == 1
        assert refund_rows[0]["amount_cents"] == -18897
        assert refund_rows[0]["ledger_kind"] == "CASH"

        fee_rows, fee_meta = validate_paginated(
            api.list_ledger_entries(
                PLATFORM_ADMIN,
                params={
                    "enrollment_id": world["enrollment_id"],
                    "entry_type": "CANCELLATION_FEE",
                },
            )
        )
        assert fee_meta["total_count"] == 1
        assert fee_rows[0]["amount_cents"] == 2500
