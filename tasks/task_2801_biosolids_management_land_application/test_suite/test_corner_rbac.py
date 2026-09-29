"""Role corners: exclusive operations, the identity checks that survive a passing
role check, segregation of duties, and a read shared by peer roles.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_ACTOR_NOT_PARTY,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_dry_tons,
    assert_instant_equals,
    assert_loading_delta,
    assert_wet_tons,
)
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    CERTIFYING_OFFICER_HEADERS,
    CERTIFYING_OFFICER_ID,
    CLOSING_OFFICER_HEADERS,
    CLOSING_OFFICER_ID,
    FARMER_HEADERS,
    LAB_ANALYST_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
    OTHER_FARMER_HEADERS,
    make_operator_headers,
)
from prd_bench_local_runner.testing import validate_error, validate_success


class TestOnlyTheOfficerCertifies:
    def test_the_analyst_who_filed_the_result_cannot_certify_against_it(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §3.4: "**Certification.** Only a `ComplianceOfficer` may certify, and certification moves `quality_status` from `PENDING_RESULTS` to `QUALIFIED`."

        Certification is a ComplianceOfficer exclusive operation. The analyst who filed
        the passing cadmium result is refused with ERR_UNAUTHORIZED on the very batch he
        characterised, and the officer succeeds on that identical state, becoming the
        certifier of record.

        Design: Corner/rbac/rbac_lab_analyst_cannot_certify_a_batch
        """
        batch = build.dewatered_batch(facility["id"])
        build.lab_result(batch["id"])

        validate_error(
            api.certify_batch(batch["id"], LAB_ANALYST_HEADERS), ERR_UNAUTHORIZED, 403
        )

        certified = validate_success(
            api.certify_batch(batch["id"], CERTIFYING_OFFICER_HEADERS)
        )
        assert certified["process_status"] == C.PROCESS_DEWATERED
        assert certified["quality_status"] == C.QUALITY_QUALIFIED
        assert_instant_equals(certified["certified_at"], C.SEED_CLOCK)
        assert certified["certified_by_user_id"] == CERTIFYING_OFFICER_ID


class TestOnlyTheAgronomistSchedules:
    def test_the_signatory_farmer_cannot_create_the_event(self, api, base_world):
        """PRD §3.7: "Only an `Agronomist` may do it, supplying `site_id`, `batch_id`, `agreement_id`, `window_start`, `window_end` (strictly after `window_start`), `application_method` (one of `SURFACE`, `INCORPORATED`, `INJECTED`), `acres_treated` (greater than 0, 2 decimal places) and `planned_dry_tons` (greater than 0, 3 decimal places); `incorporation_within_hours` is optional and defaults to null."

        Being the named party to the ACTIVE agreement grants no scheduling rights:
        farmer-jones is refused with ERR_UNAUTHORIZED, and the Agronomist creates the
        identical window as SCHEDULED.

        Design: Corner/rbac/rbac_farmer_cannot_create_an_application_event
        """
        w = base_world
        payload = F.event_payload(w.site_id, w.batch_id, w.agreement_id)

        validate_error(api.create_event(payload, FARMER_HEADERS), ERR_UNAUTHORIZED, 403)

        event = validate_success(api.create_event(payload, AGRONOMIST_HEADERS), 201)
        assert event["status"] == C.EVENT_SCHEDULED
        assert_dry_tons(event["planned_dry_tons"], 80.000)


class TestOnlyTheOfficerDecidesPermits:
    def test_the_operator_cannot_decide_the_permit(self, api, build, draft_site):
        """PRD §2.1: "They deliberately cannot certify a batch, cannot decide a site permit and cannot close out an application event — the plant does not sign off on its own product."

        The permit decision is a ComplianceOfficer exclusive operation. The operator's
        attempt is refused with ERR_UNAUTHORIZED and leaves the site UNDER_REVIEW at
        version 2; the officer's approval then writes the permit number and PERMITTED at
        version 3.

        Design: Corner/rbac/rbac_facility_operator_cannot_decide_a_site_permit
        """
        under_review = build.submit_permit(draft_site["id"])
        assert under_review["status"] == C.SITE_UNDER_REVIEW

        validate_error(
            api.permit_decision(
                draft_site["id"],
                F.permit_approval_payload(permit_number="LAP-0001"),
                make_operator_headers(),
            ),
            ERR_UNAUTHORIZED,
            403,
        )

        still_under_review = build.read_site(draft_site["id"])
        assert still_under_review["status"] == C.SITE_UNDER_REVIEW
        assert still_under_review["version"] == 2

        approved = validate_success(
            api.permit_decision(
                draft_site["id"],
                F.permit_approval_payload(permit_number="LAP-0001"),
                OFFICER_HEADERS,
            )
        )
        assert approved["status"] == C.SITE_PERMITTED
        assert approved["permit_number"] == "LAP-0001"
        assert approved["version"] == 3


class TestFarmerPartyCheckSurvivesTheRoleCheck:
    def test_a_farmer_who_is_not_the_named_party_cannot_sign(
        self, api, build, permitted_site
    ):
        """PRD §3.6: "**Signing** is a `Farmer` action from `PROPOSED` only, restricted to the named party, and it additionally requires `last_proposed_by_role` to be `Agronomist` — a farmer cannot accept their own standing counter-offer."

        The Farmer role passes the role check and still fails the identity check.
        farmer-smith signing an agreement whose farmer_user_id is farmer-jones is
        ERR_ACTOR_NOT_PARTY, the agreement stays PROPOSED, and the named party then signs
        it into SIGNED at the logical clock.

        Design: Corner/rbac/rbac_farmer_cannot_sign_an_agreement_naming_another_farmer
        """
        agreement = build.agreement(permitted_site["id"], permitted_site["version"])
        proposed = build.propose(agreement["id"])
        assert proposed["status"] == C.AGREEMENT_PROPOSED

        validate_error(
            api.sign_agreement(agreement["id"], OTHER_FARMER_HEADERS),
            ERR_ACTOR_NOT_PARTY,
            403,
        )
        assert build.read_agreement(agreement["id"])["status"] == C.AGREEMENT_PROPOSED

        signed = validate_success(api.sign_agreement(agreement["id"], FARMER_HEADERS))
        assert signed["status"] == C.AGREEMENT_SIGNED
        assert_instant_equals(signed["signed_at"], C.SEED_CLOCK)


class TestSegregationOfDutiesAtCloseOut:
    def test_the_certifying_officer_cannot_close_out_the_event(self, api, base_world):
        """PRD §3.8: "The closing officer's `X-User-ID` must differ from the batch's `certified_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

        The officer who certified the batch is barred from closing out the event that
        applies it: officer-cert-1 gets ERR_SEGREGATION_OF_DUTIES and the event stays
        IN_PROGRESS, while officer-close-2 closes the identical event to COMPLETED with
        the hauled 400.00 wet tons recorded.

        Design: Corner/rbac/rbac_certifying_officer_cannot_close_out_the_same_batch_event
        """
        w = base_world
        build = w.build
        event = build.event(w.site_id, w.batch_id, w.agreement_id)
        build.set_clock("2026-08-20T06:00:00Z")
        build.weather(w.site_id)
        build.start(event["id"])
        build.haul_ticket(event["id"], wet_tons=400.00)

        validate_error(
            api.complete_event(
                event["id"],
                CERTIFYING_OFFICER_HEADERS,
                F.complete_payload(applied_dry_tons=80.000),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert build.read_event(event["id"])["status"] == C.EVENT_IN_PROGRESS

        completed = validate_success(
            api.complete_event(
                event["id"],
                CLOSING_OFFICER_HEADERS,
                F.complete_payload(applied_dry_tons=80.000),
            )
        )
        assert completed["status"] == C.EVENT_COMPLETED
        assert_dry_tons(completed["applied_dry_tons"], 80.000)
        assert_wet_tons(completed["applied_wet_tons"], 400.00)
        assert completed["completed_by_user_id"] == CLOSING_OFFICER_ID


class TestPeerRolesShareTheLoadingSummary:
    def test_the_liaison_and_the_operator_read_the_same_summary_and_the_analyst_cannot(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §2.7: "**Priority 2 — authorization, every endpoint.** `X-User-Role` is one of the six declared roles and that role appears in the called operation's authorized-role list, otherwise `ERR_UNAUTHORIZED` (403)."

        The loading summary is a shared read: the PublicLiaison and the FacilityOperator
        both see the same full 39.0000 kg/ha of cumulative cadmium headroom on an unused
        site, while the LabAnalyst - whose only write in the whole service is filing a
        result - is refused with ERR_UNAUTHORIZED.

        Design: Corner/rbac/rbac_peer_roles_share_read_access_to_the_loading_summary
        """
        site = build.permitted_site(facility["id"])

        liaison_view = validate_success(
            api.get_loading_summary(site["id"], LIAISON_HEADERS)
        )
        operator_view = validate_success(
            api.get_loading_summary(site["id"], make_operator_headers(facility["id"]))
        )

        for view in (liaison_view, operator_view):
            assert_loading_delta(view["cplr_headroom_kg_per_hectare"]["CADMIUM"], 39.0000)
            assert view["binding_analyte"] is None
        assert liaison_view == operator_view

        validate_error(
            api.get_loading_summary(site["id"], LAB_ANALYST_HEADERS),
            ERR_UNAUTHORIZED,
            403,
        )
