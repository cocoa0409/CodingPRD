"""Requests that are refused for the state of an entity they only reference.

In both tests the request itself is well formed and the target entity is in a
perfectly good state; what blocks it is the state of a third record — a campaign
that has not yet dropped, and a contractor the overnight sweep has just put on
probation. Each refusal is followed by the change that clears it, so the gate is
shown to be about state and nothing else.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_client import canonical_instant
from test_helpers.api_errors import ERR_CAMPAIGN_NOT_MAILED, ERR_CONTRACTOR_NOT_ACTIVE
from test_helpers.assertions import assert_list_envelope, assert_refused
from test_helpers.test_users import (
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    OPERATIONS_ADMIN,
)


class TestEnrollmentDependsOnTheCampaignState:
    """The same enrollment body is refused, then accepted, on the drop alone."""

    def test_enrollment_requires_its_sourcing_campaign_to_have_reached_mailed(self, api):
        """An APPROVED but undropped campaign cannot yet source a sale.

        PRD: "a supplied `source_campaign_id` must name a campaign that has actually reached `MAILED`, and a campaign still in review or approved but undropped is refused with `ERR_CAMPAIGN_NOT_MAILED`"

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_sourcing_campaign_in_mailed_state
        """
        world = fixtures.partner_product_premises(api)
        premises_id = world["premises_id"]
        premises_v1 = world["premises_version"]

        campaign = fixtures.create_campaign(api, world["partner_id"], world["product_id"])
        assert campaign["status"] == "DRAFT"

        submitted = fixtures.submit_campaign(api, campaign["id"])
        assert submitted["status"] == "PARTNER_REVIEW"

        approved = fixtures.approve_campaign(
            api, campaign["id"], world["partner_id"], approved_quantity=100
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_quantity"] == 100

        # The clock reaches the drop date, but the drop has not been run.
        fixtures.set_clock(api, "2026-08-05T00:00:00.000Z")

        refused = api.create_enrollment(
            factories.enrollment_payload(
                premises_id,
                world["product_id"],
                premises_v1,
                source_campaign_id=campaign["id"],
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(refused, ERR_CAMPAIGN_NOT_MAILED, 409)

        # Nothing was created and the address was not touched.
        assert_list_envelope(
            api.list_enrollments(CUSTOMER_SERVICE_REP, params={"premises_id": premises_id}),
            expected_total=0,
        )
        assert fixtures.refresh_premises_version(api, premises_id) == premises_v1

        # ── the one change that clears the gate ──
        summary = fixtures.mail_drop(api, campaign["id"])
        assert summary["status"] == "MAILED"
        assert summary["mailed_count"] == 1
        assert summary["suppressed_count"] == 0
        assert summary["mailed_premises_ids"] == [premises_id]

        stamped = validate_success(api.get_premises(premises_id, MARKETING_OPS))
        assert stamped["version"] == premises_v1 + 1
        assert stamped["last_mail_decision"] == "MAILED"
        assert stamped["last_mailed_campaign_id"] == campaign["id"]
        assert stamped["mail_count_current_year"] == 1

        # The identical body, carrying the version the drop left behind.
        enrollment = fixtures.create_enrollment(
            api,
            premises_id,
            world["product_id"],
            stamped["version"],
            source_campaign_id=campaign["id"],
        )
        assert enrollment["coverage_status"] == "PENDING_WAITING_PERIOD"
        assert enrollment["source_campaign_id"] == campaign["id"]
        assert canonical_instant(enrollment["coverage_effective_at"]) == "2026-09-04T00:00:00.000Z"
        assert enrollment["term_end"] == "2027-08-05"

        dropped = validate_success(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert dropped["status"] == "MAILED"
        assert canonical_instant(dropped["mail_dropped_at"]) == "2026-08-05T00:00:00.000Z"
        # The campaign was approved first time, so nothing was ever revised.
        assert dropped["revision_count"] == 0


class TestManualDispatchDependsOnTheContractorState:
    """A contractor earns probation overnight, and the next dispatch is refused."""

    def test_manual_dispatch_requires_the_named_contractor_not_to_be_on_probation(self, api):
        """Two breaches probate the contractor, and only then is the third job refused.

        PRD: "a contractor whose `status` is not `ACTIVE` is refused with `ERR_CONTRACTOR_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/manual_dispatch_requires_contractor_not_on_probation
        """
        world = fixtures.active_coverage(api)
        enrollment_id = world["enrollment_id"]

        alder = fixtures.create_contractor(api)
        assert alder["status"] == "ACTIVE"
        assert alder["sla_breach_count"] == 0
        assert alder["max_open_dispatches"] == 5

        # An untouched control of the same shape, so the refusal below cannot be
        # blamed on the request or on the claim.
        basalt = fixtures.create_contractor(
            api,
            name="Basalt Excavation",
            license_number="OR-EX-2210",
            license_expires_on="2028-06-30",
            line_types_certified=["WATER_SERVICE_LINE", "SEWER_LATERAL"],
            hourly_rate_cents=6000,
            sla_compliance_pct=76,
            max_open_dispatches=4,
        )

        def dispatched_emergency(defect_location, description, window_start):
            """File, approve and manually dispatch one emergency to Alder."""
            claim = fixtures.file_claim(
                api,
                enrollment_id,
                defect_location=defect_location,
                urgency="EMERGENCY",
                incident_description=description,
            )
            approved = fixtures.approve_claim(api, claim["id"], coverage_note="Covered.")
            dispatch = fixtures.dispatch_claim_to(
                api, claim["id"], approved["version"], alder["id"], window_start
            )
            return claim, dispatch

        # Both windows sit on the same day; 14:00 clears the first window's
        # 13:00 end plus the 45-minute travel buffer.
        _, first = dispatched_emergency(
            "CURB_STOP_TO_METER",
            "Claim 1: curb stop blown out, water in the street.",
            "2026-09-10T09:00:00.000Z",
        )
        _, second = dispatched_emergency(
            "METER_TO_HOME",
            "Claim 2: second break, meter-to-home run.",
            "2026-09-10T14:00:00.000Z",
        )

        # Reported at 08:00, so an emergency is due four hours later.
        assert canonical_instant(first["sla_deadline_at"]) == "2026-09-10T12:00:00.000Z"
        assert canonical_instant(second["sla_deadline_at"]) == "2026-09-10T12:00:00.000Z"
        # Neither is accepted, which is what makes them breachable.
        assert first["status"] == "ASSIGNED"
        assert second["status"] == "ASSIGNED"

        # ── the overnight sweep, run at exactly the deadline ──
        fixtures.set_clock(api, "2026-09-10T12:00:00.000Z")
        report = fixtures.run_nightly(api)

        assert first["id"] in report["sla_breached_dispatch_ids"]
        assert second["id"] in report["sla_breached_dispatch_ids"]
        assert fixtures.refresh_dispatch(api, first["id"])["status"] == "SLA_BREACHED"
        assert fixtures.refresh_dispatch(api, second["id"])["status"] == "SLA_BREACHED"

        assert report["probated_contractor_ids"] == [alder["id"]]
        # Breaches are recorded before probation is applied, so probation finds
        # no dispatch of Alder's still sitting in ASSIGNED to cancel.
        assert report["cancelled_dispatch_ids"] == []

        probated = fixtures.refresh_contractor(api, alder["id"])
        assert probated["sla_breach_count"] == 2
        assert probated["status"] == "PROBATION"

        # ── an unrelated third job, refused purely on the earned state ──
        third = fixtures.file_claim(
            api,
            enrollment_id,
            urgency="EMERGENCY",
            incident_description="Claim 3: unrelated third break.",
        )
        approved_third = fixtures.approve_claim(api, third["id"], coverage_note="Covered.")
        assert approved_third["status"] == "APPROVED"
        claim_version = approved_third["version"]

        blocked = api.create_dispatch(
            third["id"],
            factories.manual_dispatch_payload(
                claim_version, "2026-09-11T09:00:00.000Z", alder["id"]
            ),
            OPERATIONS_ADMIN,
        )
        assert_refused(blocked, ERR_CONTRACTOR_NOT_ACTIVE, 409)

        unchanged = fixtures.refresh_claim(api, third["id"])
        assert unchanged["status"] == "APPROVED"
        assert unchanged["version"] == claim_version

        # Control: the identical call, redirected to the untouched contractor.
        accepted = validate_success(
            api.create_dispatch(
                third["id"],
                factories.manual_dispatch_payload(
                    claim_version, "2026-09-11T09:00:00.000Z", basalt["id"]
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert accepted["status"] == "ASSIGNED"
        assert accepted["contractor_id"] == basalt["id"]
        # The third claim was reported at 12:00, so it carries its own deadline.
        assert canonical_instant(accepted["sla_deadline_at"]) == "2026-09-10T16:00:00.000Z"

        control = fixtures.refresh_contractor(api, basalt["id"])
        assert control["status"] == "ACTIVE"
        assert control["sla_breach_count"] == 0
