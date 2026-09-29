"""Corrections that compensate rather than rewrite, and counters that net out.

The first test undoes part of a paid benefit by appending a negative row and
checks that every derived figure re-derives from the new sum while the frozen
settlement stays exactly as it was. The second releases and re-acquires the same
contractor slot inside one request and checks the counter never drifts.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_client import canonical_instant
from test_helpers.assertions import (
    assert_ids_in_order,
    assert_list_envelope,
    assert_ledger_amounts,
)
from test_helpers.test_users import MARKETING_OPS, OPERATIONS_ADMIN, PLATFORM_ADMIN


class TestBenefitReversalRestoresHeadroom:
    """A partial reversal walks the cap dimension backwards without editing history."""

    def test_benefit_reversal_restores_annual_cap_headroom(self, api):
        """A third, negative row lowers usage while the settled dispatch is untouched.

        PRD: "`BENEFIT_REVERSAL` appends a negative benefit ledger row for `remedy_amount_cents`, carrying the policy's `cap_year_start`, which lowers `annual_benefit_used_cents` and may return the cap dimension `ANNUAL_CAP_EXHAUSTED → WITHIN_CAP` — a reversal genuinely gives cap room back."

        Design: Difficulty/compensating_invariant/benefit_reversal_restores_annual_cap_headroom
        """
        world = fixtures.active_coverage(api)
        enrollment_id = world["enrollment_id"]
        contractor = fixtures.create_contractor(api)

        def settle(defect_location, description, window_start, **completion):
            claim = fixtures.file_claim(
                api,
                enrollment_id,
                defect_location=defect_location,
                incident_description=description,
            )
            approved = fixtures.approve_claim(api, claim["id"], coverage_note="Covered.")
            dispatch = fixtures.dispatch_claim_to(
                api, claim["id"], approved["version"], contractor["id"], window_start
            )
            fixtures.accept_dispatch(api, dispatch["id"], contractor["id"])
            completed = fixtures.complete_dispatch(
                api, dispatch["id"], contractor["id"], **completion
            )
            return claim["id"], dispatch["id"], completed

        first_claim, first_dispatch, first_settlement = settle(
            "CURB_STOP_TO_METER",
            "Claim 1: curb stop replaced with permit and backfill.",
            "2026-09-10T09:00:00.000Z",
            labor_cents=260000,
            materials_cents=175000,
            permit_number="OR-PERMIT-3391",
            permit_fee_cents=42000,
            restoration_cents=90000,
            restoration_scope="BASIC_BACKFILL",
        )
        assert first_settlement["benefit_paid_cents"] == 527000

        # The first dispatch is COMPLETED, so it no longer blocks the calendar.
        second_claim, _, second_settlement = settle(
            "METER_TO_HOME",
            "Claim 2: meter-to-home run relaid.",
            "2026-09-11T09:00:00.000Z",
            labor_cents=400000,
            materials_cents=73000,
        )
        assert second_settlement["benefit_paid_cents"] == 473000

        before = fixtures.refresh_enrollment(api, enrollment_id)
        assert before["annual_benefit_used_cents"] == 1000000
        assert before["cap_status"] == "ANNUAL_CAP_EXHAUSTED"

        paid = fixtures.refresh_claim(api, first_claim)
        assert paid["status"] == "PAID"
        assert paid["benefit_paid_cents"] == 527000
        assert paid["occurrence_used_cents"] == 527000

        fixtures.set_clock(api, "2026-09-20T00:00:00.000Z")
        complaint = fixtures.create_complaint(
            api,
            world["partner_id"],
            allegation=(
                "Policyholder alleges the permit fee on the curb-stop repair was "
                "billed to the programme twice."
            ),
            claim_id=first_claim,
        )
        # The cited claim is PAID rather than denied, so the full PUC window
        # applies and no appeal is reopened.
        assert canonical_instant(complaint["response_due_at"]) == "2026-09-30T00:00:00.000Z"
        assert fixtures.refresh_claim(api, first_claim)["status"] == "PAID"
        assert fixtures.refresh_claim(api, first_claim)["appeal_count"] == 0

        # ── the compensating response ──
        closed = fixtures.respond_to_complaint(
            api,
            complaint["id"],
            "SUBSTANTIATED",
            "BENEFIT_REVERSAL",
            complaint["version"],
            remedy_amount_cents=100000,
            response_summary="The duplicated permit fee is reversed to the programme.",
        )
        assert closed["status"] == "CLOSED_SUBSTANTIATED"
        assert closed["remedy_type"] == "BENEFIT_REVERSAL"
        assert closed["remedy_amount_cents"] == 100000
        assert canonical_instant(closed["responded_at"]) == "2026-09-20T00:00:00.000Z"

        # Nothing was rewritten: the two original charges stand as booked.
        charges = fixtures.ledger_entries(
            api, PLATFORM_ADMIN, enrollment_id=enrollment_id, entry_type="BENEFIT_CHARGE"
        )
        assert len(charges) == 2
        assert_ledger_amounts(charges, [527000, 473000])

        benefit_rows = fixtures.ledger_entries(
            api, PLATFORM_ADMIN, enrollment_id=enrollment_id, ledger_kind="BENEFIT"
        )
        assert len(benefit_rows) == 3
        assert_ledger_amounts(benefit_rows, [527000, 473000, -100000])
        assert sum(row["amount_cents"] for row in benefit_rows) == 900000

        reversal = benefit_rows[-1]
        assert reversal["entry_type"] == "BENEFIT_REVERSAL"
        assert reversal["amount_cents"] == -100000
        assert reversal["claim_id"] == first_claim
        assert reversal["cap_year_start"] == "2026-08-05"

        # The cap dimension re-derives from the new sum and walks backwards.
        after = fixtures.refresh_enrollment(api, enrollment_id)
        assert after["annual_benefit_used_cents"] == 900000
        assert after["cap_status"] == "WITHIN_CAP"
        assert after["annual_benefit_reserved_cents"] == 0

        # The ledger-derived figure moves; the frozen settlement does not.
        reduced = fixtures.refresh_claim(api, first_claim)
        assert reduced["benefit_paid_cents"] == 427000
        assert reduced["occurrence_used_cents"] == 427000

        frozen = fixtures.refresh_dispatch(api, first_dispatch)
        assert frozen["status"] == "COMPLETED"
        assert frozen["benefit_paid_cents"] == 527000
        assert frozen["invoice_total_cents"] == 567000
        assert frozen["customer_responsibility_cents"] == 40000

        # A reversal aimed at one claim leaves its sibling alone.
        assert fixtures.refresh_claim(api, second_claim)["benefit_paid_cents"] == 473000

        premises = validate_success(api.get_premises(world["premises_id"], MARKETING_OPS))
        # The complaint cited no policy, and the closure re-derives the flag anyway.
        assert premises["regulator_hold"] is False


class TestCapacitySlotConservedAcrossSupersede:
    """One slot released and one taken, on the same contractor, in one request."""

    def test_contractor_capacity_slot_is_conserved_across_supersede_and_completion(self, api):
        """The counter reads 1 after the supersede — never 0 and never 2.

        PRD: "because a supersede moves the open slot from the outgoing contractor to the incoming one in the same request, the sum of every contractor's `open_dispatch_count` always equals the number of dispatches actually in the open set"

        Design: Difficulty/compensating_invariant/contractor_capacity_slot_conserved_across_supersede_and_completion
        """
        world = fixtures.active_coverage(api)
        enrollment_id = world["enrollment_id"]

        contractor = fixtures.create_contractor(api)
        assert contractor["open_dispatch_count"] == 0

        claim = fixtures.file_claim(
            api,
            enrollment_id,
            incident_description="Curb stop weeping under the parking strip.",
        )
        approved = fixtures.approve_claim(api, claim["id"], coverage_note="Covered.")
        approved_version = approved["version"]

        outgoing = fixtures.dispatch_claim_to(
            api, claim["id"], approved_version, contractor["id"], "2026-09-10T09:00:00.000Z"
        )
        assert outgoing["status"] == "ASSIGNED"
        # Six hours at 18000 cents plus 120000 of materials, on the rate card.
        assert outgoing["estimated_benefit_cents"] == 228000
        assert canonical_instant(outgoing["sla_deadline_at"]) == "2026-09-13T08:00:00.000Z"

        assert fixtures.refresh_contractor(api, contractor["id"])["open_dispatch_count"] == 1

        held = fixtures.refresh_enrollment(api, enrollment_id)
        # A reservation is a forward-looking hold, not usage.
        assert held["annual_benefit_reserved_cents"] == 228000
        assert held["annual_benefit_used_cents"] == 0

        dispatched = fixtures.refresh_claim(api, claim["id"])
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["version"] == approved_version + 1
        assert canonical_instant(dispatched["sla_deadline_at"]) == "2026-09-13T08:00:00.000Z"

        # ── the replacement, on a different day so no buffer can fire ──
        incoming = validate_success(
            api.create_dispatch(
                claim["id"],
                factories.manual_dispatch_payload(
                    dispatched["version"],
                    "2026-09-11T09:00:00.000Z",
                    contractor["id"],
                    supersedes_dispatch_id=outgoing["id"],
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert incoming["status"] == "ASSIGNED"
        assert incoming["estimated_benefit_cents"] == 228000
        # Re-dispatching never buys the network more time.
        assert canonical_instant(incoming["sla_deadline_at"]) == "2026-09-13T08:00:00.000Z"

        superseded = fixtures.refresh_dispatch(api, outgoing["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["cancellation_reason"] == "SUPERSEDED_BY_REDISPATCH"
        assert superseded.get("benefit_paid_cents") is None

        # ── the conserved counters ──
        assert fixtures.refresh_contractor(api, contractor["id"])["open_dispatch_count"] == 1
        mid = fixtures.refresh_enrollment(api, enrollment_id)
        assert mid["annual_benefit_reserved_cents"] == 228000

        # The self-loop keeps the claim in place rather than reverting it.
        assert fixtures.refresh_claim(api, claim["id"])["status"] == "DISPATCHED"

        # ── the unwind ──
        fixtures.accept_dispatch(api, incoming["id"], contractor["id"])
        settled = fixtures.complete_dispatch(
            api, incoming["id"], contractor["id"], labor_cents=100000, materials_cents=50000
        )
        assert settled["status"] == "COMPLETED"
        assert settled["benefit_paid_cents"] == 150000
        assert settled["customer_responsibility_cents"] == 0

        assert fixtures.refresh_contractor(api, contractor["id"])["open_dispatch_count"] == 0
        final = fixtures.refresh_enrollment(api, enrollment_id)
        assert final["annual_benefit_reserved_cents"] == 0
        # Neither the reservation nor the superseded dispatch leaked into usage.
        assert final["annual_benefit_used_cents"] == 150000

        charges = fixtures.ledger_entries(
            api, PLATFORM_ADMIN, enrollment_id=enrollment_id, entry_type="BENEFIT_CHARGE"
        )
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == 150000

        rows, _ = assert_list_envelope(
            api.list_dispatches(OPERATIONS_ADMIN, params={"claim_id": claim["id"]}),
            expected_total=2,
        )
        assert_ids_in_order(rows, [outgoing["id"], incoming["id"]])
        assert [row["status"] for row in rows] == ["SUPERSEDED", "COMPLETED"]

        assert fixtures.refresh_claim(api, claim["id"])["status"] == "PAID"
        assert fixtures.refresh_claim(api, claim["id"])["benefit_paid_cents"] == 150000
