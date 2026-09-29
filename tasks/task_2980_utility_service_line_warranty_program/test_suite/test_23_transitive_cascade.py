"""Chains where one write propagates across three or four entity types.

A single contractor event settles a dispatch and ends by denying a claim nobody
touched; a single compliance intake reopens a claim and ends on the marketing
file.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.api_client import canonical_instant
from test_helpers.test_users import MARKETING_OPS, OPERATIONS_ADMIN, PLATFORM_ADMIN

# A product whose per-occurrence allowance is the whole annual cap, so one
# settled job can exhaust the policy year.
TIGHT_CAP_PRODUCT = {
    "name": "Sewer Guard Basic",
    "per_occurrence_cap_cents": 600000,
    "annual_cap_cents": 600000,
    "permit_covered": False,
    "restoration_covered_scope": "NONE",
}


class TestCompletionCascadesToASiblingClaim:
    """One COMPLETE event, four hops, ending on an untouched claim."""

    def test_dispatch_completion_cascades_to_sibling_claim_denial(self, api):
        """Settling one dispatch exhausts the cap and auto-denies the other claim.

        PRD: "If the newly posted charge brings `annual_benefit_used_cents` to or past `annual_cap_cents`, the cap dimension moves `WITHIN_CAP → ANNUAL_CAP_EXHAUSTED`, and that in turn denies **every remaining claim of that policy still sitting in `TRIAGE`**, each recording `CAP_EXHAUSTED` as its `denial_reason` and the logical clock as its `denied_at`."

        Design: Difficulty/transitive_cascade/dispatch_completion_cascades_to_sibling_claim_denial
        """
        world = fixtures.partner_product_premises(api, product_overrides=dict(TIGHT_CAP_PRODUCT))
        world = fixtures.active_coverage(api, world)
        enrollment_id = world["enrollment_id"]
        contractor = fixtures.create_contractor(api)

        claim_a = fixtures.file_claim(
            api,
            enrollment_id,
            incident_description="Claim A: curb stop shattered by frost heave.",
        )
        approved_a = fixtures.approve_claim(
            api, claim_a["id"], coverage_note="Covered curb-stop segment."
        )
        dispatch_a = fixtures.dispatch_claim_to(
            api,
            claim_a["id"],
            approved_a["version"],
            contractor["id"],
            "2026-09-10T09:00:00.000Z",
        )
        fixtures.accept_dispatch(api, dispatch_a["id"], contractor["id"])

        # A separate defect on the same policy, left sitting in triage.
        claim_b = fixtures.file_claim(
            api,
            enrollment_id,
            defect_location="METER_TO_HOME",
            incident_description="Claim B: separate pinhole on the meter-to-home run.",
        )
        assert claim_b["eligibility_assessment"] == "ELIGIBLE"
        assert claim_b["status"] == "TRIAGE"

        # ── the single triggering event ──
        completed = fixtures.complete_dispatch(
            api,
            dispatch_a["id"],
            contractor["id"],
            labor_cents=500000,
            materials_cents=150000,
        )

        # hop 1: the dispatch itself. The 600000 pool covers all the labour and
        # only 100000 of the materials.
        assert completed["status"] == "COMPLETED"
        assert completed["benefit_paid_cents"] == 600000
        assert completed["invoice_total_cents"] == 650000
        assert completed["customer_responsibility_cents"] == 50000

        # hop 2: the worked claim and the ledger row.
        worked = fixtures.refresh_claim(api, claim_a["id"])
        assert worked["status"] == "PAID"
        assert worked["benefit_paid_cents"] == 600000

        charges = fixtures.ledger_entries(
            api, PLATFORM_ADMIN, enrollment_id=enrollment_id, entry_type="BENEFIT_CHARGE"
        )
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == 600000
        assert charges[0]["claim_id"] == claim_a["id"]

        # hop 3: the policy's cap dimension, on an inclusive comparison.
        enrollment = fixtures.refresh_enrollment(api, enrollment_id)
        assert enrollment["annual_benefit_used_cents"] == 600000
        assert enrollment["cap_status"] == "ANNUAL_CAP_EXHAUSTED"
        assert enrollment["annual_benefit_reserved_cents"] == 0

        # hop 4: the sibling claim nobody touched.
        sibling = fixtures.refresh_claim(api, claim_b["id"])
        assert sibling["status"] == "DENIED"
        assert sibling["denial_reason"] == "CAP_EXHAUSTED"
        assert sibling["eligibility_assessment"] == "CAP_EXHAUSTED"
        # A null decider is the durable signal that no adjuster acted.
        assert sibling["triage_decided_by_user_id"] is None
        assert canonical_instant(sibling["denied_at"]) == "2026-09-10T08:00:00.000Z"

        released = fixtures.refresh_contractor(api, contractor["id"], OPERATIONS_ADMIN)
        assert released["open_dispatch_count"] == 0


class TestComplaintIntakeCascadesToMarketing:
    """One compliance intake, three hops, ending on the mailing file."""

    def test_regulator_complaint_intake_cascades_to_premises_suppression(self, api):
        """Citing a denied claim reopens it as a regulator appeal and suppresses the address.

        PRD: "When the cited `claim_id` names a claim in `DENIED` **or in the otherwise terminal `APPEAL_UPHELD_DENIAL`**, that claim is driven to `APPEAL_OPEN` with `appeal_source` `REGULATOR`, `appeal_opened_at` stamped and `appeal_count` incremented, and the `retention_hold` and suppression cascade follows exactly as for a policyholder appeal."

        Design: Difficulty/transitive_cascade/regulator_complaint_intake_cascades_to_premises_suppression
        """
        world = fixtures.active_coverage(api)
        assert world["enrollment"]["retention_hold"] is False

        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="Curb stop weeping into the parking strip.",
        )
        denied = fixtures.deny_claim(
            api,
            claim["id"],
            "NOT_COVERED_SEGMENT",
            coverage_note="Adjuster judges the break outside the insured segment.",
        )
        assert denied["status"] == "DENIED"
        # No policyholder appeal has been filed.
        assert denied["appeal_count"] == 0

        # The address is mailable, and its standing reason skips the two
        # campaign-scoped reasons, so a live policy alone does not suppress it.
        premises_before = validate_success(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert premises_before["suppression_reason"] == "NONE"
        assert premises_before["regulator_hold"] is False

        fixtures.set_clock(api, "2026-09-20T00:00:00.000Z")

        # ── the single triggering intake ──
        complaint = fixtures.create_complaint(
            api,
            world["partner_id"],
            regulator="PUC",
            allegation=(
                "Policyholder alleges the curb-stop denial contradicts the marketed "
                "coverage boundary."
            ),
            claim_id=claim["id"],
        )

        # hop 0: the complaint itself, on the expedited five-day floor.
        assert complaint["status"] == "OPEN"
        assert canonical_instant(complaint["received_at"]) == "2026-09-20T00:00:00.000Z"
        assert canonical_instant(complaint["response_due_at"]) == "2026-09-25T00:00:00.000Z"
        assert complaint["escalation_count"] == 0
        assert complaint["days_overdue"] == 0

        # hop 1: the cited claim, reopened by the regulator rather than the household.
        reopened = fixtures.refresh_claim(api, claim["id"])
        assert reopened["status"] == "APPEAL_OPEN"
        assert reopened["appeal_source"] == "REGULATOR"
        assert reopened["appeal_count"] == 1

        # hop 2: the policy's retention hold.
        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["retention_hold"] is True

        # hop 3: the marketing file.
        premises_after = validate_success(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert premises_after["suppression_reason"] == "OPEN_APPEAL"
        assert premises_after["suppressed"] is True
        # The complaint cited a claim only, never a policy.
        assert premises_after["regulator_hold"] is False
