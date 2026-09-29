"""Operations that are refused because of the state of a different entity, with
every precondition on the addressed entity itself satisfied.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import ERR_AGREEMENT_NOT_ACTIVE, ERR_FACILITY_FROZEN
from test_helpers.assertions import assert_dry_tons, assert_percent, assert_wet_tons
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    CERTIFYING_OFFICER_ID,
    OFFICER_HEADERS,
    make_officer_headers,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSchedulingDependsOnAgreementActivation:
    @staticmethod
    def _signed_but_not_activated(build):
        facility = build.facility()
        build.limit()
        batch = build.qualified_batch(facility["id"])
        site = build.permitted_site(facility["id"])
        agreement = build.agreement(site["id"], site["version"])
        build.propose(agreement["id"])
        signed = build.sign(agreement["id"])
        build.weather(site["id"])
        return facility, batch, site, signed

    @staticmethod
    def _event_payload(site, batch, agreement):
        return F.event_payload(
            site["id"],
            batch["id"],
            agreement["id"],
            acres_treated=80.0,
            planned_dry_tons=80.000,
        )

    def test_signed_agreement_is_not_enough_to_book_a_window(self, api, build):
        """PRD §2.7: "**Priority 25 — agreement active.** The referenced agreement's `status` is `ACTIVE`, otherwise `ERR_AGREEMENT_NOT_ACTIVE` (409)."

        The site is PERMITTED, the batch is QUALIFIED with tonnage to spare, the
        weather is clear and the requested rate is well under the cap, yet scheduling is
        refused because the agreement has only been countersigned. The refusal reserves
        nothing and creates no event row.

        Design: Difficulty/cross_entity_state_dependency/event_creation_requires_agreement_in_active_state
        """
        _, batch, site, agreement = self._signed_but_not_activated(build)

        response = api.create_event(
            self._event_payload(site, batch, agreement), AGRONOMIST_HEADERS
        )
        validate_error(response, ERR_AGREEMENT_NOT_ACTIVE)

        current = build.read_agreement(agreement["id"])
        assert current["status"] == C.AGREEMENT_SIGNED
        assert current["signed_at"] is not None

        _, meta = validate_paginated(
            api.list_events(OFFICER_HEADERS, {"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 0
        assert_dry_tons(build.read_batch(batch["id"])["unallocated_dry_tons"], 160.000)

    def test_activation_is_the_only_blocker(self, api, build):
        """PRD §3.6: "**Activating** is an `Agronomist` action from `SIGNED` only."

        Activating the very same agreement and replaying the identical create request
        succeeds with the window SCHEDULED, proving the agreement's state was the sole
        cause of the earlier refusal.

        Design: Difficulty/cross_entity_state_dependency/event_creation_requires_agreement_in_active_state
        """
        _, batch, site, agreement = self._signed_but_not_activated(build)
        api.create_event(self._event_payload(site, batch, agreement), AGRONOMIST_HEADERS)

        activated = build.activate(agreement["id"])
        assert activated["status"] == C.AGREEMENT_ACTIVE

        event = validate_success(
            api.create_event(
                self._event_payload(site, batch, agreement), AGRONOMIST_HEADERS
            ),
            201,
        )
        assert event["status"] == C.EVENT_SCHEDULED


class TestCertificationDependsOnFacilityPosture:
    @staticmethod
    def _frozen_by_a_sibling_batch(build):
        facility = build.facility(storage_capacity_wet_tons=1000.00)
        build.limit()
        batch = build.dewatered_batch(facility["id"])
        build.lab_result(batch["id"])
        sibling = build.batch(
            facility["id"], wet_tons=190.00, dry_tons_in=40.000
        )
        return facility, batch, sibling

    def test_certification_is_refused_while_the_plant_is_frozen(self, api, build):
        """PRD §2.7: "**Priority 30 — facility not frozen.** The governing facility's `posture` is not `FROZEN`, otherwise `ERR_FACILITY_FROZEN` (409)."

        The batch's own analyte panel is complete and clean, so it is certifiable on
        its own merits, but a second batch pushed plant storage to 99.00% and froze the
        facility, and the freeze reaches through the plant to block certification. The
        batch keeps its PENDING_RESULTS quality dimension with no certification stamp.

        Design: Difficulty/cross_entity_state_dependency/certification_requires_facility_posture_not_frozen
        """
        _, batch, _ = self._frozen_by_a_sibling_batch(build)

        response = api.certify_batch(
            batch["id"], make_officer_headers(CERTIFYING_OFFICER_ID)
        )
        validate_error(response, ERR_FACILITY_FROZEN)

        current = build.read_batch(batch["id"])
        assert current["quality_status"] == C.QUALITY_PENDING_RESULTS
        assert current["certified_at"] is None
        assert current["certified_by_user_id"] is None

    def test_utilization_alone_froze_the_plant(self, api, build):
        """PRD §2.8: "`posture` is `FROZEN` when `open_ceiling_exceedance_count` is greater than 0, or when `storage_utilization_pct` is at or above 98.00."

        Storage holds 990.00 of 1000.00 wet tons, which is 99.00% and above the
        freeze threshold, while no ceiling exceedance is open - so utilization by itself
        set the posture. The sibling batch's own creation was accepted because the plant
        was still at 80.00% when it arrived.

        Design: Difficulty/cross_entity_state_dependency/certification_requires_facility_posture_not_frozen
        """
        facility, batch, sibling = self._frozen_by_a_sibling_batch(build)
        api.certify_batch(batch["id"], make_officer_headers(CERTIFYING_OFFICER_ID))

        current_facility = build.read_facility(facility["id"])
        assert_wet_tons(current_facility["storage_used_wet_tons"], 990.00)
        assert_percent(current_facility["storage_utilization_pct"], 99.00)
        assert current_facility["posture"] == C.POSTURE_FROZEN
        assert current_facility["open_ceiling_exceedance_count"] == 0

        assert build.read_batch(sibling["id"])["process_status"] == C.PROCESS_THICKENED
