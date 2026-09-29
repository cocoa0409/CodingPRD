"""Requests that violate two rules at once, where only the higher tier is reported.

Each test first collects the lower-tier refusal on its own, to prove the losing
rule is genuinely live, and only then arranges for both to hold.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ANNUAL_CAP_EXHAUSTED,
    ERR_CONTRACTOR_LICENSE_EXPIRED,
    ERR_CONTRACTOR_NOT_CERTIFIED,
    ERR_ENROLLMENT_NOT_ACTIVE,
)
from test_helpers.assertions import assert_refused
from test_helpers.test_users import CLAIMS_ADJUSTER, OPERATIONS_ADMIN, PLATFORM_ADMIN

TIGHT_CAP_PRODUCT = {
    "name": "Sewer Guard Basic",
    "per_occurrence_cap_cents": 600000,
    "annual_cap_cents": 600000,
    "permit_covered": False,
    "restoration_covered_scope": "NONE",
}


class TestStateGateOutranksFiscalCheck:
    """A triage approval that is both out of coverage and out of cap."""

    def test_enrollment_state_gate_outranks_the_annual_cap_check(self, api):
        """The same call answers 422 while covered and 409 once suspended.

        PRD: "First, on a triage approval the coverage state gate outranks the cap check: an enrollment that is both `SUSPENDED_NONPAY` and cap-exhausted reports `ERR_ENROLLMENT_NOT_ACTIVE` (tier 11), never `ERR_ANNUAL_CAP_EXHAUSTED` (tier 16)."

        Design: Difficulty/priority_pair_validation_conflict/enrollment_state_gate_outranks_annual_cap_fiscal_check
        """
        world = fixtures.partner_product_premises(api, product_overrides=dict(TIGHT_CAP_PRODUCT))
        world = fixtures.active_coverage(api, world)
        enrollment_id = world["enrollment_id"]
        contractor = fixtures.create_contractor(api)

        # Exhaust the whole policy year on one settled job.
        claim_a = fixtures.file_claim(
            api,
            enrollment_id,
            incident_description="Claim A: curb stop shattered by frost heave.",
        )
        approved_a = fixtures.approve_claim(api, claim_a["id"])
        dispatch_a = fixtures.dispatch_claim_to(
            api,
            claim_a["id"],
            approved_a["version"],
            contractor["id"],
            "2026-09-10T09:00:00.000Z",
        )
        fixtures.accept_dispatch(api, dispatch_a["id"], contractor["id"])
        fixtures.complete_dispatch(
            api, dispatch_a["id"], contractor["id"], labor_cents=500000, materials_cents=150000
        )

        after_a = fixtures.refresh_enrollment(api, enrollment_id)
        assert after_a["cap_status"] == "ANNUAL_CAP_EXHAUSTED"
        assert after_a["coverage_status"] == "ACTIVE"

        # Filed after the cap flipped, so the sibling denial cascade cannot reach
        # it and it survives in triage.
        claim_b = fixtures.file_claim(
            api,
            enrollment_id,
            defect_location="METER_TO_HOME",
            incident_description="Claim B: separate pinhole on the meter-to-home run.",
        )
        assert claim_b["status"] == "TRIAGE"
        assert claim_b["eligibility_assessment"] == "CAP_EXHAUSTED"

        # Control: with coverage still live, the lower-tier rule answers alone.
        control = api.triage_claim(
            claim_b["id"], factories.triage_approval_payload(), CLAIMS_ADJUSTER
        )
        assert_refused(control, ERR_ANNUAL_CAP_EXHAUSTED, 422)

        # Now put the policy out of coverage as well.
        fixtures.billing_event(api, enrollment_id, "MISSED_PAYMENT", "2026-09-10")
        fixtures.set_clock(api, "2026-10-10T00:00:00.000Z")
        fixtures.run_nightly(api)

        before_trigger = fixtures.refresh_enrollment(api, enrollment_id)
        assert before_trigger["coverage_status"] == "SUSPENDED_NONPAY"
        assert before_trigger["cap_status"] == "ANNUAL_CAP_EXHAUSTED"

        conflict = api.triage_claim(
            claim_b["id"], factories.triage_approval_payload(), CLAIMS_ADJUSTER
        )
        assert_refused(conflict, ERR_ENROLLMENT_NOT_ACTIVE, 409)
        assert conflict.status_code != 422

        # Both refusals were side-effect free.
        final_b = fixtures.refresh_claim(api, claim_b["id"])
        assert final_b["status"] == "TRIAGE"
        assert final_b["version"] == 1
        assert final_b["triage_decided_by_user_id"] is None
        assert final_b["triage_decided_at"] is None
        # The intake ladder's own first step agrees with the refusal order.
        assert final_b["eligibility_assessment"] == "COVERAGE_INACTIVE"

        # Thirty days of arrears suspend the policy; sixty would lapse it.
        assert before_trigger["coverage_status"] != "LAPSED"


class TestLicenceOutranksCertification:
    """A manual dispatch to a contractor who fails two 422 checks at once."""

    def test_licence_check_outranks_the_certification_check(self, api):
        """Both refusals are 422, so only the declared order can pick the winner.

        PRD: "Second, on a manual dispatch the licence check outranks the certification check: a contractor that is both unlicensed and uncertified for the claim's service line reports `ERR_CONTRACTOR_LICENSE_EXPIRED` (tier 12), never `ERR_CONTRACTOR_NOT_CERTIFIED` (tier 13)."

        Design: Difficulty/priority_pair_validation_conflict/contractor_licence_safety_check_outranks_certification_referential_check
        """
        world = fixtures.active_coverage(api)

        # Basalt is kept ACTIVE, permit-authorised and idle so that no other
        # eligibility condition can pre-empt the pair under test.
        basalt = fixtures.create_contractor(
            api,
            name="Basalt Excavation",
            license_number="OR-EX-3310",
            license_expires_on="2026-09-01",
            line_types_certified=["SEWER_LATERAL"],
        )
        assert basalt["status"] == "ACTIVE"
        assert basalt["open_dispatch_count"] == 0
        assert basalt["permit_pull_authorized"] is True
        # Both violations really hold on the same record.
        assert basalt["license_expires_on"] == "2026-09-01"
        assert "WATER_SERVICE_LINE" not in basalt["line_types_certified"]

        alder = fixtures.create_contractor(api)

        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="Curb stop cracked open under the sidewalk.",
        )
        approved = fixtures.approve_claim(api, claim["id"])
        assert approved["status"] == "APPROVED"
        claim_version = approved["version"]

        refused = api.create_dispatch(
            claim["id"],
            factories.manual_dispatch_payload(
                claim_version, "2026-09-11T09:00:00.000Z", basalt["id"]
            ),
            OPERATIONS_ADMIN,
        )
        body = assert_refused(refused, ERR_CONTRACTOR_LICENSE_EXPIRED, 422)
        assert body["error_id"] != ERR_CONTRACTOR_NOT_CERTIFIED

        # The rejection consumed nothing.
        _, meta = validate_paginated(
            api.list_dispatches(OPERATIONS_ADMIN, params={"claim_id": claim["id"]})
        )
        assert meta["total_count"] == 0

        unchanged = fixtures.refresh_claim(api, claim["id"])
        assert unchanged["status"] == "APPROVED"
        assert unchanged["version"] == claim_version

        idle = fixtures.refresh_contractor(api, basalt["id"])
        assert idle["open_dispatch_count"] == 0
        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"], PLATFORM_ADMIN)
        assert enrollment["annual_benefit_reserved_cents"] == 0

        # Control: only the two contractor attributes differ.
        accepted = validate_success(
            api.create_dispatch(
                claim["id"],
                factories.manual_dispatch_payload(
                    claim_version, "2026-09-11T09:00:00.000Z", alder["id"]
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert accepted["status"] == "ASSIGNED"
        assert accepted["contractor_id"] == alder["id"]
