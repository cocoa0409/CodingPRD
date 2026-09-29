"""Requests that arm two rules from different priority bands at once; the lower
priority number must be the one that answers.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_AGRONOMIC_RATE_EXCEEDED,
    ERR_EVENT_NOT_IN_PROGRESS,
    ERR_ODOR_RISK_BLOCK,
    ERR_SITE_RESTRICTED,
)
from test_helpers.assertions import assert_dry_tons, assert_loading_delta, assert_percent
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
    make_officer_headers,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEventStateOutranksSiteRestriction:
    def test_deferred_event_on_a_restricted_site_answers_the_state_rule(
        self, api, tight_cplr_world
    ):
        """PRD §2.7: "**Priority 32 — site not restricted.** The referenced site's `status` is not `RESTRICTED`, otherwise `ERR_SITE_RESTRICTED` (409)."

        Closing out event A restricts the site and defers event B, so a close-out
        aimed at event B breaks the event-state rule and the site-restriction rule at
        the same time. The state rule carries the lower priority number, so the answer
        is ERR_EVENT_NOT_IN_PROGRESS and not ERR_SITE_RESTRICTED.

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_site_restriction_on_complete
        """
        build = tight_cplr_world["build"]
        build.complete(tight_cplr_world["event_a"]["id"], applied_dry_tons=80.000)

        site = build.read_site(tight_cplr_world["site"]["id"])
        assert site["status"] == C.SITE_RESTRICTED

        response = api.complete_event(
            tight_cplr_world["event_b"]["id"],
            make_officer_headers("officer-close-2"),
            {"applied_dry_tons": 80.000},
        )
        error = validate_error(response, ERR_EVENT_NOT_IN_PROGRESS)
        assert error["error_id"] != ERR_SITE_RESTRICTED

    def test_refused_close_out_writes_nothing(self, api, tight_cplr_world):
        """PRD §2.7: "**Priority 21 — other entity states.** The target site, agreement, application event, diversion order, odor complaint or annual report is in the from-state its transition declares, otherwise `ERR_SITE_INVALID_STATE`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_EVENT_NOT_SCHEDULED`, `ERR_EVENT_NOT_IN_PROGRESS`, `ERR_EVENT_NOT_COMPLETED`, `ERR_ORDER_INVALID_STATE`, `ERR_COMPLAINT_INVALID_STATE` or `ERR_REPORT_INVALID_STATE`, all 409."

        The refused close-out leaves event B DEFERRED with its deferral reason and
        no applied tonnage, and the site keeps exactly the one ledger row written by
        event A's close-out.

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_site_restriction_on_complete
        """
        build = tight_cplr_world["build"]
        site_id = tight_cplr_world["site"]["id"]
        build.complete(tight_cplr_world["event_a"]["id"], applied_dry_tons=80.000)

        api.complete_event(
            tight_cplr_world["event_b"]["id"],
            make_officer_headers("officer-close-2"),
            {"applied_dry_tons": 80.000},
        )

        event_b = build.read_event(tight_cplr_world["event_b"]["id"])
        assert event_b["status"] == C.EVENT_DEFERRED
        assert event_b["defer_reason"] == "SITE_RESTRICTED"
        assert_dry_tons(event_b["applied_dry_tons"], 0.000)

        _, meta = validate_paginated(
            api.list_ledger_entries(OFFICER_HEADERS, {"site_id": site_id})
        )
        assert meta["total_count"] == 1

        current_site = build.read_site(site_id)
        assert_loading_delta(
            current_site["cumulative_loading_kg_per_hectare"]["CADMIUM"], 0.1793
        )


class TestOdorSafetyOutranksRateOverage:
    @staticmethod
    def _world_with_three_open_severe_complaints(build):
        facility = build.facility()
        build.limit()
        batch = build.qualified_batch(facility["id"])
        site = build.permitted_site(facility["id"], nearest_residence_ft=1200)
        agreement = build.active_agreement(site["id"], site["version"])
        build.weather(site["id"])
        for received_at in (
            "2026-07-20T13:00:00Z",
            "2026-07-25T13:00:00Z",
            "2026-07-30T13:00:00Z",
        ):
            validate_success(
                build.api.create_complaint(
                    F.complaint_payload(
                        facility["id"],
                        site_id=site["id"],
                        received_at=received_at,
                        severity="SEVERE",
                        description="Persistent odor at the fence line",
                    ),
                    LIAISON_HEADERS,
                ),
                201,
            )
        return facility, batch, site, agreement

    def test_odor_block_answers_before_the_rate_overage(self, api, build):
        """PRD §2.7: "**Priority 37 — odor gate.** The site's `gating_risk_score` is strictly below 60.00, otherwise `ERR_ODOR_RISK_BLOCK` (422)."

        Three open SEVERE complaints give a precautionary score of 84.00 on a site
        1200 ft from the nearest residence, which is the gating score, while the
        requested 160.000 dry tons on 15.0 acres is 10.67 per acre against a 9.88 cap.
        The safety rule carries the lower priority number, so the answer is
        ERR_ODOR_RISK_BLOCK and not ERR_AGRONOMIC_RATE_EXCEEDED.

        Design: Difficulty/priority_pair_validation_conflict/odor_safety_block_outranks_agronomic_rate_overage
        """
        _, batch, site, agreement = self._world_with_three_open_severe_complaints(build)

        response = api.create_event(
            F.event_payload(
                site["id"],
                batch["id"],
                agreement["id"],
                acres_treated=15.0,
                planned_dry_tons=160.000,
            ),
            AGRONOMIST_HEADERS,
        )
        error = validate_error(response, ERR_ODOR_RISK_BLOCK)
        assert error["error_id"] != ERR_AGRONOMIC_RATE_EXCEEDED

        current_site = build.read_site(site["id"])
        assert_percent(current_site["odor_risk_score_precautionary"], 84.00)
        assert_percent(current_site["odor_risk_score_historical"], 0.00)
        assert_percent(current_site["gating_risk_score"], 84.00)

    def test_blocked_schedule_reserves_nothing(self, api, build):
        """PRD §2.7: "When a single request violates several rules at once, the server must return the violation with the **lowest priority number** in the ladder below."

        The blocked request creates no event, leaves the batch's full 160.000 dry
        tons unallocated, and leaves the facility OPEN because no complaint has been
        substantiated.

        Design: Difficulty/priority_pair_validation_conflict/odor_safety_block_outranks_agronomic_rate_overage
        """
        facility, batch, site, agreement = (
            self._world_with_three_open_severe_complaints(build)
        )

        api.create_event(
            F.event_payload(
                site["id"],
                batch["id"],
                agreement["id"],
                acres_treated=15.0,
                planned_dry_tons=160.000,
            ),
            AGRONOMIST_HEADERS,
        )

        _, meta = validate_paginated(
            api.list_events(OFFICER_HEADERS, {"site_id": site["id"]})
        )
        assert meta["total_count"] == 0

        current_batch = build.read_batch(batch["id"])
        assert_dry_tons(current_batch["unallocated_dry_tons"], 160.000)

        current_facility = build.read_facility(facility["id"])
        assert current_facility["substantiated_complaint_count_30d"] == 0
        assert current_facility["posture"] == C.POSTURE_OPEN
