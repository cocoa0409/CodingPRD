"""Cross-entity state dependencies: manifest shipping gated on a confirmed
site agreement, and encounter completion gated on the treating volunteer
remaining AUTHORIZED."""

from test_helpers import (
    TEST_USERS,
    create_event,
    create_manifest_payload,
    get_success_data,
    setup_event_with_open_encounter,
    suspend_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
SL = TEST_USERS["station_lead_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


class TestManifestShipRequiresConfirmedAgreement:
    def test_ship_in_planning_rejected_by_posture_gate(self, api):
        """PRD §3.5: "Shipping moves `PACKED → IN_TRANSIT` and is gated on the
        event having a confirmed site agreement — posture at least
        `SITE_LOCKED`, otherwise `ERR_EVENT_POSTURE_FORBIDS`."

        Design: Difficulty/cross_entity_state_dependency/manifest_ship_requires_confirmed_agreement
        """
        event = create_event(
            service_date="2027-01-09",
            doors_open_utc="2027-01-09T10:00:00Z",
            total_patient_capacity=150,
        )
        manifest = validate_success(
            api.create_manifest(
                event["id"],
                create_manifest_payload(
                    manifest_label="T-1", item_count=20, weight_kg=900.0
                ),
                LC,
            ),
            201,
        )
        assert manifest["status"] == "PACKED"

        response = api.ship_manifest(event["id"], manifest["id"], LC)
        validate_error(response, "ERR_EVENT_POSTURE_FORBIDS")

    def test_rejected_ship_leaves_manifest_packed(self, api):
        """PRD §3.5: "Manifests start as `PACKED`. Shipping moves
        `PACKED → IN_TRANSIT` and is gated on the event having a confirmed
        site agreement" — a rejected ship leaves the manifest in PACKED.

        Design: Difficulty/cross_entity_state_dependency/manifest_ship_requires_confirmed_agreement
        """
        event = create_event(
            service_date="2027-01-09",
            doors_open_utc="2027-01-09T10:00:00Z",
            total_patient_capacity=150,
        )
        manifest = validate_success(
            api.create_manifest(event["id"], create_manifest_payload(), LC), 201
        )
        response = api.ship_manifest(event["id"], manifest["id"], LC)
        validate_error(response, "ERR_EVENT_POSTURE_FORBIDS")

        manifests, _ = validate_paginated(
            api.list_event_manifests(event["id"], LC)
        )
        assert manifests[0]["status"] == "PACKED"


class TestEncounterCompleteRequiresAuthorizedVolunteer:
    def test_completion_rejected_after_treating_volunteer_suspended(self, api):
        """PRD §3.6: "The treating volunteer must still be `AUTHORIZED` at
        completion time, otherwise `ERR_VOLUNTEER_NOT_AUTHORIZED`."

        Design: Difficulty/cross_entity_state_dependency/encounter_complete_requires_authorized_volunteer
        """
        ctx = setup_event_with_open_encounter()
        get_success_data(
            api.suspend_volunteer(
                ctx["volunteer_id"], suspend_payload(ctx["id"], "audit"), VC
            )
        )
        response = api.complete_encounter(ctx["id"], ctx["encounter_id"], {}, SL)
        validate_error(response, "ERR_VOLUNTEER_NOT_AUTHORIZED")

    def test_rejected_completion_leaves_encounter_open(self, api):
        """PRD §3.6: "The treating volunteer must still be `AUTHORIZED` at
        completion time, otherwise `ERR_VOLUNTEER_NOT_AUTHORIZED`; the station
        must be `OPERATIONAL` or `DEGRADED`, otherwise
        `ERR_STATION_NOT_SERVING`." A rejected completion leaves the encounter
        in its OPEN from-state.

        Design: Difficulty/cross_entity_state_dependency/encounter_complete_requires_authorized_volunteer
        """
        ctx = setup_event_with_open_encounter()
        get_success_data(
            api.suspend_volunteer(
                ctx["volunteer_id"], suspend_payload(ctx["id"], "audit"), VC
            )
        )
        response = api.complete_encounter(ctx["id"], ctx["encounter_id"], {}, SL)
        validate_error(response, "ERR_VOLUNTEER_NOT_AUTHORIZED")

        encounters, _ = validate_paginated(
            api.list_event_encounters(ctx["id"], SL)
        )
        assert encounters[0]["status"] == "OPEN"
