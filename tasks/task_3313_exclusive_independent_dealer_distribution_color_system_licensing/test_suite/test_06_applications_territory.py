"""Applications: territory screening, approval gates, attestation, and OCC."""
from test_helpers import (
    CD,
    RM,
    ApiErrorId,
    api_client,
    get_success_data,
    set_clock,
    setup_application,
    setup_onboarding_dealer,
    setup_region,
    validate_error,
    validate_success,
)


class TestStateBeatsStaleAttestation:
    def test_approve_draft_application_yields_invalid_state(self, api):
        """PRD section 2.5: "(5) transition validity — the target resource is
        in a state from which the requested transition exists, else
        `ERR_INVALID_STATE`".
        PRD section 3.2: "Approval by either a `RegionManager` (when there is
        no conflict) or a `ChannelDirector` moves the application from
        `SUBMITTED` to `APPROVED`".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_priority_on_approve
        """
        set_clock()
        region = setup_region()
        app = setup_application(
            region["id"], legal_name="Stale Paint LLC",
            latitude=40.0, longitude=-74.0,
            exclusivity_attested_on="2025-08-01T00:00:00Z",
        )
        assert app["status"] == "DRAFT"
        resp = api.approve_application(
            app["id"], {"expected_application_version": app["version"]}, RM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_submitted_application_with_fresh_attestation_succeeds(self, api):
        """PRD section 3.2: "First, the applicant dealer's
        `exclusivity_attested_on` must be within 366 days of the current
        logical time — an attestation older than that is rejected with
        `ERR_ATTESTATION_STALE` (HTTP 422)".
        PRD section 3.2: "Approval by either a `RegionManager` (when there is
        no conflict) or a `ChannelDirector` moves the application from
        `SUBMITTED` to `APPROVED`".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_priority_on_approve
        """
        set_clock()
        region = setup_region()
        app = setup_application(region["id"], legal_name="Fresh Paint LLC")
        submitted = validate_success(api.submit_application(app["id"], RM))
        approved = validate_success(
            api.approve_application(
                app["id"], {"expected_application_version": submitted["version"]}, RM,
            )
        )
        assert approved["status"] == "APPROVED"


class TestAttestationFreshnessBoundary:
    def test_attestation_exactly_366_days_old_is_fresh(self, api):
        """PRD section 3.2: "First, the applicant dealer's
        `exclusivity_attested_on` must be within 366 days of the current
        logical time — an attestation older than that is rejected with
        `ERR_ATTESTATION_STALE` (HTTP 422)".

        Design: Corner/validations/attestation_exactly_366_days_is_fresh_367_is_stale
        """
        set_clock()
        region = setup_region()
        app = setup_application(
            region["id"], legal_name="Fresh Attest Co",
            exclusivity_attested_on="2025-09-01T00:00:00Z",
        )
        submitted = validate_success(api.submit_application(app["id"], RM))
        approved = validate_success(
            api.approve_application(
                app["id"], {"expected_application_version": submitted["version"]}, RM,
            )
        )
        assert approved["status"] == "APPROVED"

    def test_attestation_367_days_old_is_stale(self, api):
        """PRD section 3.2: "First, the applicant dealer's
        `exclusivity_attested_on` must be within 366 days of the current
        logical time — an attestation older than that is rejected with
        `ERR_ATTESTATION_STALE` (HTTP 422)".

        Design: Corner/validations/attestation_exactly_366_days_is_fresh_367_is_stale
        """
        set_clock()
        region = setup_region()
        app = setup_application(
            region["id"], legal_name="Stale Attest Co",
            latitude=44.0, longitude=-73.0,
            # 367 days before the 2026-09-01 logical clock start: older than
            # the 366-day freshness limit, hence stale.
            exclusivity_attested_on="2025-08-30T00:00:00Z",
        )
        submitted = validate_success(api.submit_application(app["id"], RM))
        resp = api.approve_application(
            app["id"], {"expected_application_version": submitted["version"]}, RM,
        )
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_STALE)


class TestTerritoryDistance:
    def test_empty_region_yields_null_distance_and_no_conflict(self, api):
        """PRD section 3.2: "The smallest such distance is recorded as
        `distance_to_nearest_miles`, rounded half-up to two decimal places;
        when no candidate dealer exists the field is null. The nearest
        protected dealer is recorded as `nearest_dealer_id` ... it is null
        when no candidates exist. The `territory_conflict` flag is set true
        exactly when `distance_to_nearest_miles` is strictly less than the
        region's `territory_radius_miles`".

        Design: Corner/calculations/territory_distance_empty_candidate_set
        """
        set_clock()
        region = setup_region()
        app = setup_application(region["id"], legal_name="First Paint")
        submitted = validate_success(api.submit_application(app["id"], RM))
        assert submitted["distance_to_nearest_miles"] is None
        assert submitted["territory_conflict"] is False

    def test_nearby_dealer_produces_conflict(self, api):
        """PRD section 3.2: "The `territory_conflict` flag is set true
        exactly when `distance_to_nearest_miles` is strictly less than the
        region's `territory_radius_miles` — a distance exactly equal to the
        radius is not a conflict."

        Design: Corner/validations/territory_override_requires_director_and_notification
        """
        set_clock()
        region = setup_region()
        dealer = setup_onboarding_dealer(region["id"])
        assert dealer["status"] == "ONBOARDING"
        # ~24.94 miles east of (42.0, -71.0); radius is 25.
        app = setup_application(
            region["id"], legal_name="Near Paint Co",
            latitude=42.0, longitude=-70.64,
        )
        submitted = validate_success(api.submit_application(app["id"], RM))
        assert submitted["territory_conflict"] is True
        assert submitted["nearest_dealer_id"] == dealer["id"]


class TestTerritoryOverride:
    def _setup_conflict_application(self):
        set_clock()
        region = setup_region()
        setup_onboarding_dealer(region["id"])
        app = setup_application(
            region["id"], legal_name="Near Paint Co",
            latitude=42.0, longitude=-70.64,
        )
        submitted = validate_success(api_client.submit_application(app["id"], RM))
        assert submitted["territory_conflict"] is True
        return app, submitted

    def test_region_manager_cannot_approve_conflicting_application(self, api):
        """PRD section 3.2: "Second, if `territory_conflict` is true, only a
        `ChannelDirector` may approve, and only after the nearest protected
        dealer has been notified ... An approval attempted on a conflicting
        application by a `RegionManager`, or by anyone before notification,
        is rejected with `ERR_TERRITORY_CONFLICT` (HTTP 422)."

        Design: Corner/validations/territory_override_requires_director_and_notification
        """
        app, submitted = self._setup_conflict_application()
        resp = api.approve_application(
            app["id"], {"expected_application_version": submitted["version"]}, RM,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_CONFLICT)

    def test_director_approval_requires_neighbor_notification(self, api):
        """PRD section 3.2: "Second, if `territory_conflict` is true, only a
        `ChannelDirector` may approve, and only after the nearest protected
        dealer has been notified: a `RegionManager` records that notification
        through the notify-neighbor action, which sets
        `nearest_dealer_notified` to true and increments the application's
        `version` by 1. An approval attempted on a conflicting application by
        a `RegionManager`, or by anyone before notification, is rejected with
        `ERR_TERRITORY_CONFLICT` (HTTP 422)."

        Design: Corner/validations/territory_override_requires_director_and_notification
        """
        app, submitted = self._setup_conflict_application()
        resp = api.approve_application(
            app["id"], {"expected_application_version": submitted["version"]}, CD,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_CONFLICT)
        notified = validate_success(api.notify_neighbor(app["id"], RM))
        assert notified["nearest_dealer_notified"] is True
        assert notified["version"] == submitted["version"] + 1
        approved = validate_success(
            api.approve_application(
                app["id"], {"expected_application_version": notified["version"]}, CD,
            )
        )
        assert approved["status"] == "APPROVED"


class TestApplicationOcc:
    def test_approve_with_stale_version_rejected(self, api):
        """PRD section 2.5: "Approving a dealer application requires the
        request body to carry `expected_application_version` holding the
        application's `version` as the client last observed it; if another
        writer has advanced the application's version since — for example by
        withdrawing it or recording a neighbor notification, both of which
        increment `version` — the approve is rejected with
        `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross-cutting complexity layers/occ_stale_version_on_application_approve
        """
        set_clock()
        region = setup_region()
        app = setup_application(region["id"], legal_name="OCC Paint Co")
        assert app["version"] == 1
        submitted = validate_success(api.submit_application(app["id"], RM))
        assert submitted["version"] == 2
        resp = api.approve_application(
            app["id"], {"expected_application_version": app["version"]}, RM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_approve_with_current_version_succeeds(self, api):
        """PRD section 2.5: "Approving a dealer application requires the
        request body to carry `expected_application_version` holding the
        application's `version` as the client last observed it".
        PRD section 3.2: "Approval by either a `RegionManager` (when there is
        no conflict) or a `ChannelDirector` moves the application from
        `SUBMITTED` to `APPROVED`".

        Design: Corner/cross-cutting complexity layers/occ_stale_version_on_application_approve
        """
        set_clock()
        region = setup_region()
        app = setup_application(region["id"], legal_name="OCC Paint Co")
        submitted = validate_success(api.submit_application(app["id"], RM))
        approved = validate_success(
            api.approve_application(
                app["id"], {"expected_application_version": submitted["version"]}, RM,
            )
        )
        assert approved["status"] == "APPROVED"
