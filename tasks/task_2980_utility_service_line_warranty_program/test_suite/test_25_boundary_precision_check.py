"""Thresholds walked at their smallest representable step.

The waiting period is probed one millisecond either side of the coverage instant,
and the annual cap is probed one cent either side of its ceiling.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories, fixtures
from test_helpers.api_client import canonical_instant
from test_helpers.api_errors import ERR_WAITING_PERIOD_NOT_ELAPSED
from test_helpers.assertions import assert_refused
from test_helpers.test_users import CLAIMS_ADJUSTER, CUSTOMER_SERVICE_REP, PLATFORM_ADMIN


class TestWaitingPeriodInstantBoundary:
    """One millisecond decides whether a claim is covered at all."""

    def test_waiting_period_boundary_at_the_exact_coverage_effective_instant(self, api):
        """23:59:59.999Z is inside the waiting period and 00:00:00.000Z is outside it.

        PRD: "Fourth, `WAITING_PERIOD` when the claim's `reported_at` is strictly earlier than the policy's `coverage_effective_at`."

        Design: Difficulty/boundary_precision_check/waiting_period_boundary_at_exact_coverage_effective_instant
        """
        world = fixtures.enrolled_premises(api)
        enrollment_id = world["enrollment_id"]
        enrollment = world["enrollment"]

        # 2026-08-05 plus a 30-day waiting period, at midnight UTC.
        assert canonical_instant(enrollment["coverage_effective_at"]) == "2026-09-04T00:00:00.000Z"
        assert enrollment["term_end"] == "2027-08-05"
        # PENDING_WAITING_PERIOD is not one of the inactive statuses, so the
        # ladder's first step cannot pre-empt its fourth.
        assert enrollment["coverage_status"] == "PENDING_WAITING_PERIOD"

        # ── one millisecond below the boundary ──
        fixtures.set_clock(api, "2026-09-03T23:59:59.999Z")
        early = fixtures.file_claim(
            api,
            enrollment_id,
            incident_description="Boundary probe: filed one millisecond before coverage attaches.",
        )
        assert canonical_instant(early["reported_at"]) == "2026-09-03T23:59:59.999Z"
        assert early["eligibility_assessment"] == "WAITING_PERIOD"

        refused = api.triage_claim(
            early["id"],
            factories.triage_approval_payload(
                coverage_note="Attempting to approve the one-millisecond-early claim."
            ),
            CLAIMS_ADJUSTER,
        )
        assert_refused(refused, ERR_WAITING_PERIOD_NOT_ELAPSED, 422)

        untouched = fixtures.refresh_claim(api, early["id"])
        assert untouched["status"] == "TRIAGE"
        assert untouched["version"] == 1

        # ── exactly on the boundary ──
        fixtures.set_clock(api, "2026-09-04T00:00:00.000Z")
        report = fixtures.run_nightly(api)
        # The activation sweep reaches the same instant with an inclusive test.
        assert enrollment_id in report["activated_enrollment_ids"]

        on_boundary = fixtures.file_claim(
            api,
            enrollment_id,
            incident_description="Boundary probe: filed at the exact coverage_effective_at instant.",
        )
        assert canonical_instant(on_boundary["reported_at"]) == "2026-09-04T00:00:00.000Z"
        # Equality is not "strictly earlier", so the claim is covered.
        assert on_boundary["eligibility_assessment"] == "ELIGIBLE"

        approved = fixtures.approve_claim(
            api, on_boundary["id"], coverage_note="Exact-instant claim is inside coverage."
        )
        assert approved["status"] == "APPROVED"
        assert canonical_instant(approved["triage_decided_at"]) == "2026-09-04T00:00:00.000Z"

        activated = fixtures.refresh_enrollment(api, enrollment_id)
        assert activated["coverage_status"] == "ACTIVE"

        rows, meta = validate_paginated(
            api.list_claims(CUSTOMER_SERVICE_REP, params={"enrollment_id": enrollment_id})
        )
        assert meta["total_count"] == 2
        assert rows[0]["id"] == early["id"]


class TestAnnualCapCentBoundary:
    """One cent decides whether the policy year is exhausted."""

    def test_annual_cap_exhausts_when_usage_equals_the_cap_exactly(self, api):
        """527000 stays within cap, 999999 still does, and 1000000 exhausts it.

        PRD: "The comparison is inclusive: usage landing exactly on `annual_cap_cents` exhausts the cap, and one cent less leaves the dimension at `WITHIN_CAP`."

        Design: Difficulty/boundary_precision_check/annual_cap_exhausts_when_usage_equals_cap_exactly
        """
        world = fixtures.active_coverage(api)
        enrollment_id = world["enrollment_id"]
        assert world["enrollment"]["cap_status"] == "WITHIN_CAP"
        assert world["enrollment"]["annual_benefit_used_cents"] == 0

        contractor = fixtures.create_contractor(api)

        def settle(defect_location, description, **complete_overrides):
            """File, approve, dispatch, accept and complete one occurrence.

            Each occurrence is filed without a recurrence link, so it is the root
            of its own group and the per-occurrence pool never binds.
            """
            claim = fixtures.file_claim(
                api,
                enrollment_id,
                defect_location=defect_location,
                incident_description=description,
            )
            approved = fixtures.approve_claim(api, claim["id"], coverage_note="Covered.")
            dispatch = fixtures.dispatch_claim_to(
                api,
                claim["id"],
                approved["version"],
                contractor["id"],
                "2026-09-10T09:00:00.000Z",
            )
            fixtures.accept_dispatch(api, dispatch["id"], contractor["id"])
            completed = fixtures.complete_dispatch(
                api, dispatch["id"], contractor["id"], **complete_overrides
            )
            return claim, completed

        # ── point 1: far below the ceiling ──
        _, first = settle(
            "CURB_STOP_TO_METER",
            "Occurrence 1: curb-stop failure with permit and restoration.",
            labor_cents=260000,
            materials_cents=175000,
            permit_number="OR-PERMIT-3391",
            permit_fee_cents=42000,
            restoration_cents=90000,
            restoration_scope="BASIC_BACKFILL",
        )
        assert first["benefit_paid_cents"] == 527000

        after_first = fixtures.refresh_enrollment(api, enrollment_id)
        assert after_first["annual_benefit_used_cents"] == 527000
        assert after_first["cap_status"] == "WITHIN_CAP"

        # ── point 2: exactly one cent below the ceiling ──
        _, second = settle(
            "METER_TO_HOME",
            "Occurrence 2: sized to land one cent under the annual cap.",
            labor_cents=400000,
            materials_cents=72999,
        )
        assert second["benefit_paid_cents"] == 472999
        assert second["customer_responsibility_cents"] == 0

        after_second = fixtures.refresh_enrollment(api, enrollment_id)
        assert after_second["annual_benefit_used_cents"] == 999999
        assert after_second["cap_status"] == "WITHIN_CAP"

        # ── point 3: exactly on the ceiling ──
        third_claim = fixtures.file_claim(
            api,
            enrollment_id,
            incident_description="Occurrence 3: one-cent callout that lands exactly on the cap.",
        )
        # Still within cap at the moment the claim is filed.
        assert third_claim["eligibility_assessment"] == "ELIGIBLE"

        approved_third = fixtures.approve_claim(
            api, third_claim["id"], coverage_note="Covered."
        )
        dispatch_third = fixtures.dispatch_claim_to(
            api,
            third_claim["id"],
            approved_third["version"],
            contractor["id"],
            "2026-09-10T09:00:00.000Z",
        )
        fixtures.accept_dispatch(api, dispatch_third["id"], contractor["id"])
        third = fixtures.complete_dispatch(
            api, dispatch_third["id"], contractor["id"], labor_cents=1, materials_cents=0
        )
        assert third["benefit_paid_cents"] == 1

        after_third = fixtures.refresh_enrollment(api, enrollment_id)
        # Exactly the cap, never one cent past it: the pool does not over-pay.
        assert after_third["annual_benefit_used_cents"] == 1000000
        assert after_third["cap_status"] == "ANNUAL_CAP_EXHAUSTED"
        assert after_third["annual_benefit_reserved_cents"] == 0

        charges = fixtures.ledger_entries(
            api, PLATFORM_ADMIN, enrollment_id=enrollment_id, entry_type="BENEFIT_CHARGE"
        )
        assert [row["amount_cents"] for row in charges] == [527000, 472999, 1]
        assert sum(row["amount_cents"] for row in charges) == 1000000

        # The claim that reached the cap is itself paid; only later ones are refused.
        assert fixtures.refresh_claim(api, third_claim["id"])["status"] == "PAID"
