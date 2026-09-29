"""Two calculations that each have two genuinely different variants.

The benefit settlement is selected by lifecycle position on one dispatch, and the
contractor selection score is selected by the claim's urgency over one pool.
"""

import pytest

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_client import canonical_instant
from test_helpers.test_users import (
    CUSTOMER_SERVICE_REP,
    OPERATIONS_ADMIN,
    make_network_contractor_headers,
)


class TestBenefitSettlementVariants:
    """The provisional reservation and the final settlement of one dispatch."""

    def test_provisional_estimate_and_final_settlement_diverge(self, api):
        """A dispatch reserves 228000 at assignment and settles 527000 at completion.

        PRD: "The two variants routinely disagree, and they are supposed to: the same water-service job estimated at 6 hours times 18000 cents plus 120000, or 228000, settles finally at 527000, and under a cheaper contractor at 6000 cents an hour the estimate would have been 156000 against the identical final figure."

        Design: Difficulty/dual_variant_calc/benefit_provisional_estimate_vs_final_settlement_diverge
        """
        world = fixtures.active_coverage(api)
        contractor = fixtures.create_contractor(api)
        world = fixtures.filed_claim(api, world)
        approved = fixtures.approve_claim(api, world["claim_id"])

        response = api.create_dispatch(
            world["claim_id"],
            factories.manual_dispatch_payload(
                approved["version"], "2026-09-10T09:00:00.000Z", contractor["id"]
            ),
            OPERATIONS_ADMIN,
        )
        dispatch = validate_success(response, 201)

        # The provisional variant: the contractor's rate card, with no permit and
        # no restoration component at all.
        assert dispatch["estimated_benefit_cents"] == 228000
        assert dispatch["selection_mode"] == "MANUAL"
        assert dispatch["selection_score"] == pytest.approx(78.4, abs=0.01)
        assert dispatch["status"] == "ASSIGNED"

        enrollment = validate_success(api.get_enrollment(world["enrollment_id"], OPERATIONS_ADMIN))
        assert enrollment["annual_benefit_reserved_cents"] == 228000
        assert enrollment["annual_benefit_used_cents"] == 0

        crew = make_network_contractor_headers(contractor["id"])
        validate_success(
            api.create_dispatch_event(dispatch["id"], factories.accept_event_payload(), crew)
        )
        completed = validate_success(
            api.create_dispatch_event(
                dispatch["id"], factories.full_complete_event_payload(), crew
            )
        )

        # The final variant: the four-bucket waterfall over the same pool.
        assert completed["benefit_paid_cents"] == 527000
        assert completed["invoice_total_cents"] == 567000
        assert completed["customer_responsibility_cents"] == 40000
        assert completed["status"] == "COMPLETED"
        assert completed["benefit_paid_cents"] - dispatch["estimated_benefit_cents"] == 299000

        claim = validate_success(api.get_claim(world["claim_id"], OPERATIONS_ADMIN))
        assert claim["status"] == "PAID"
        assert claim["benefit_paid_cents"] == 527000

        settled = validate_success(api.get_enrollment(world["enrollment_id"], OPERATIONS_ADMIN))
        assert settled["annual_benefit_reserved_cents"] == 0
        assert settled["annual_benefit_used_cents"] == 527000
        assert settled["cap_status"] == "WITHIN_CAP"

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                OPERATIONS_ADMIN,
                params={
                    "enrollment_id": world["enrollment_id"],
                    "entry_type": "BENEFIT_CHARGE",
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 527000
        assert rows[0]["ledger_kind"] == "BENEFIT"


class TestSelectionScoreWeightVariants:
    """One eligible pool, two urgency weightings, two different winners."""

    def test_emergency_and_standard_weights_pick_different_winners(self, api):
        """Over one pool an EMERGENCY claim takes contractor A and a ROUTINE claim takes B.

        PRD: "A `ROUTINE` claim therefore selects B, while an `EMERGENCY` claim over the identical pool selects A."

        Design: Difficulty/dual_variant_calc/contractor_score_emergency_and_standard_weights_pick_different_winners
        """
        world = fixtures.active_coverage(api)
        contractor_a = fixtures.create_contractor(api)
        contractor_b = fixtures.create_contractor(
            api,
            name="Bridgetown Excavation",
            license_number="OR-EX-8802",
            license_expires_on="2027-12-31",
            hourly_rate_cents=6000,
            sla_compliance_pct=76,
            max_open_dispatches=4,
        )

        emergency = validate_success(
            api.create_claim(
                factories.claim_payload(
                    world["enrollment_id"],
                    urgency="EMERGENCY",
                    incident_description="Curb stop blown out, water flooding the basement now.",
                ),
                CUSTOMER_SERVICE_REP,
            ),
            201,
        )
        emergency_approved = fixtures.approve_claim(api, emergency["id"])

        routine = validate_success(
            api.create_claim(
                factories.claim_payload(
                    world["enrollment_id"],
                    defect_location="METER_TO_HOME",
                    urgency="ROUTINE",
                    incident_description="Slow seep on the meter-to-home run, scheduled repair.",
                ),
                CUSTOMER_SERVICE_REP,
            ),
            201,
        )
        routine_approved = fixtures.approve_claim(api, routine["id"])

        emergency_dispatch = validate_success(
            api.create_dispatch(
                emergency["id"],
                factories.dispatch_payload(
                    emergency_approved["version"], "2026-09-10T09:00:00.000Z"
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        routine_dispatch = validate_success(
            api.create_dispatch(
                routine["id"],
                factories.dispatch_payload(
                    routine_approved["version"], "2026-09-11T09:00:00.000Z"
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )

        assert emergency_dispatch["selection_mode"] == "AUTOMATIC"
        assert emergency_dispatch["contractor_id"] == contractor_a["id"]
        assert emergency_dispatch["selection_score"] == pytest.approx(89.9, abs=0.01)

        assert routine_dispatch["selection_mode"] == "AUTOMATIC"
        assert routine_dispatch["contractor_id"] == contractor_b["id"]
        assert routine_dispatch["selection_score"] == pytest.approx(83.2, abs=0.01)

        assert emergency_dispatch["contractor_id"] != routine_dispatch["contractor_id"]

        # The response deadline follows the urgency, off the shared reported_at.
        assert canonical_instant(emergency_dispatch["sla_deadline_at"]) == "2026-09-10T12:00:00.000Z"
        assert canonical_instant(routine_dispatch["sla_deadline_at"]) == "2026-09-13T08:00:00.000Z"

        # Each reservation uses its own assignee's rate card.
        assert emergency_dispatch["estimated_benefit_cents"] == 228000
        assert routine_dispatch["estimated_benefit_cents"] == 156000

        enrollment = validate_success(api.get_enrollment(world["enrollment_id"], OPERATIONS_ADMIN))
        assert enrollment["annual_benefit_reserved_cents"] == 384000
