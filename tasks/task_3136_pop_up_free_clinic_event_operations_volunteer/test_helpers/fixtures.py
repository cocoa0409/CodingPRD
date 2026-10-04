"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch via the public API (the
server is restarted before each test, so each test starts against an empty
store). Setup calls use get_success_data() so failures surface as clear
"setup failed" errors rather than confusing assertion failures.

Entity facts are returned as plain dicts of the form
    {"id": ..., "event_id": ..., "version": ...}
which fixtures pass to each other; tests use the same dicts to build follow-up
calls and to re-fetch current state.
"""

import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    authorize_payload,
    begin_service_payload,
    create_assignment_payload,
    create_cycle_payload,
    create_event_payload,
    create_handoff_payload,
    create_manifest_payload,
    create_referral_payload,
    create_site_agreement_payload,
    create_site_payload,
    create_station_payload,
    create_ticket_payload,
    create_verification_request_payload,
    create_volunteer_payload,
    suspend_payload,
)
from .test_users import TEST_USERS

_counter = itertools.count(1)


def _n():
    return next(_counter)


# ---------------------------------------------------------------------------
# Tier 1 — base entities
# ---------------------------------------------------------------------------


def create_site(**overrides) -> dict:
    """Create a PROSPECT site. Returns the full site dict."""
    return get_success_data(
        api_client.create_site(
            create_site_payload(**overrides), TEST_USERS["logistics_coordinator_headers"]
        )
    )


def create_vetted_site(**overrides) -> dict:
    """Create a site and move it to VETTED."""
    site = create_site(**overrides)
    return get_success_data(
        api_client.vet_site(site["id"], TEST_USERS["logistics_coordinator_headers"])
    )


def create_event(**overrides) -> dict:
    """Create a PLANNING clinic event. Returns the full event dict."""
    return get_success_data(
        api_client.create_event(
            create_event_payload(**overrides), TEST_USERS["event_director_headers"]
        )
    )


def _event_fact(event_id: str) -> dict:
    event = get_success_data(
        api_client.get_event(event_id, TEST_USERS["event_director_headers"])
    )
    return {"id": event["id"], "version": event["version"], "posture": event["posture"]}


def create_agreement(event, site_id: str, **overrides) -> dict:
    """Create a DRAFT site agreement against the event (OCC-guarded).

    `event` is an event fact dict carrying the current version.
    """
    return get_success_data(
        api_client.create_site_agreement(
            event["id"],
            create_site_agreement_payload(site_id, event["version"], **overrides),
            TEST_USERS["logistics_coordinator_headers"],
        )
    )


def submit_agreement(event_id: str, agreement_id: str) -> dict:
    return get_success_data(
        api_client.submit_agreement(
            event_id, agreement_id, TEST_USERS["logistics_coordinator_headers"]
        )
    )


def confirm_agreement(event_id: str, agreement_id: str) -> dict:
    return get_success_data(
        api_client.confirm_agreement(
            event_id, agreement_id, TEST_USERS["event_director_headers"]
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — posture progression
# ---------------------------------------------------------------------------


def create_event_site_locked(
    event_overrides=None, site_overrides=None, agreement_overrides=None
) -> dict:
    """Event with a CONFIRMED site agreement (posture SITE_LOCKED).

    Returns the event fact dict {"id", "version", "posture"}.
    """
    overrides = dict(site_overrides or {})
    event_defaults = dict(event_overrides or {})
    if "host_state_code" in event_defaults and "state_code" not in overrides:
        overrides["state_code"] = event_defaults["host_state_code"]
    site = create_vetted_site(**overrides)
    event = create_event(**event_defaults)
    fact = {"id": event["id"], "version": event["version"], "posture": event["posture"]}
    agreement = create_agreement(fact, site["id"], **(agreement_overrides or {}))
    submit_agreement(fact["id"], agreement["id"])
    confirm_agreement(fact["id"], agreement["id"])
    return _event_fact(fact["id"])


def create_station(event_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_station(
            event_id,
            create_station_payload(**overrides),
            TEST_USERS["logistics_coordinator_headers"],
        )
    )


def setup_station(event_id: str, **overrides) -> dict:
    """Create a station and move it PLANNED -> SET_UP."""
    station = create_station(event_id, **overrides)
    return get_success_data(
        api_client.mark_station_set_up(
            event_id, station["id"], TEST_USERS["logistics_coordinator_headers"]
        )
    )


def create_volunteer(**overrides) -> dict:
    """Register a volunteer (REGISTERED). Returns the full volunteer dict."""
    return get_success_data(
        api_client.create_volunteer(
            create_volunteer_payload(**overrides),
            TEST_USERS["volunteer_coordinator_headers"],
        )
    )


def verify_volunteer(volunteer_id: str, event_id: str) -> dict:
    """Request verification and approve it; volunteer becomes VERIFIED.

    Returns the approved LicenseVerification dict.
    """
    verification = get_success_data(
        api_client.request_verification(
            volunteer_id,
            create_verification_request_payload(event_id),
            TEST_USERS["volunteer_coordinator_headers"],
        )
    )
    return get_success_data(
        api_client.approve_verification(
            volunteer_id,
            verification["id"],
            TEST_USERS["credentialing_officer_headers"],
        )
    )


def authorize_volunteer(volunteer_id: str, event_id: str) -> dict:
    """Authorize a VERIFIED volunteer against the event's current version."""
    event = get_success_data(
        api_client.get_event(event_id, TEST_USERS["event_director_headers"])
    )
    return get_success_data(
        api_client.authorize_volunteer(
            volunteer_id,
            authorize_payload(event_id, event["version"]),
            TEST_USERS["volunteer_coordinator_headers"],
        )
    )


def create_authorized_volunteer(event_id: str, assign: bool = True, **overrides) -> dict:
    """Register -> verify -> (optionally roster) -> authorize a volunteer.

    Returns the authorized volunteer dict.
    """
    volunteer = create_volunteer(**overrides)
    verify_volunteer(volunteer["id"], event_id)
    if assign:
        get_success_data(
            api_client.create_assignment(
                event_id,
                create_assignment_payload(volunteer["id"]),
                TEST_USERS["volunteer_coordinator_headers"],
            )
        )
    return authorize_volunteer(volunteer["id"], event_id)


def create_event_in_service(
    event_overrides=None, site_overrides=None, station_overrides=None
) -> dict:
    """Event in IN_SERVICE posture with an OPERATIONAL station and AUTHORIZED
    volunteers rostered on the event.

    The READY posture gate requires a discipline coverage score of at least
    60, so the setup staffs two disciplines: one DENTAL station (SET_UP) with
    one authorized DENTAL volunteer (coverage 50) and one MEDICAL station
    (OPERATIONAL, non-sterilization) with one authorized MEDICAL volunteer
    (coverage 20) for a total score of 70. The MEDICAL station is the one
    that serves tickets. Returns a dict:
      {"id", "version", "posture", "station_id", "volunteer_id",
       "dental_station_id", "dental_volunteer_id"}
    """
    st_overrides = {
        "station_type": "MEDICAL",
        "requires_sterilization": False,
        "chair_count": 1,
        "minutes_per_patient": 15,
    }
    st_overrides.update(station_overrides or {})
    event = create_event_site_locked(event_overrides, site_overrides)
    # DENTAL leg: lifts coverage to 70 so the STAFFING -> READY gate passes.
    dental_station = setup_station(event["id"], station_type="DENTAL")
    dental_volunteer = create_authorized_volunteer(event["id"], discipline="DENTAL")
    station = setup_station(event["id"], **st_overrides)
    volunteer = create_authorized_volunteer(event["id"], discipline="MEDICAL")
    if not st_overrides.get("requires_sterilization", False):
        station = get_success_data(
            api_client.mark_station_operational(
                event["id"], station["id"], TEST_USERS["station_lead_headers"]
            )
        )
    event_now = get_success_data(
        api_client.open_doors(event["id"], TEST_USERS["event_director_headers"])
    )
    return {
        "id": event["id"],
        "version": event_now["version"],
        "posture": event_now["posture"],
        "station_id": station["id"],
        "volunteer_id": volunteer["id"],
        "dental_station_id": dental_station["id"],
        "dental_volunteer_id": dental_volunteer["id"],
    }


def setup_event_ready_at_coverage_boundary(event_overrides=None, site_overrides=None) -> dict:
    """Event driven to exactly the READY coverage boundary (score 60.0).

    Layout: two DENTAL stations (SET_UP) with two AUTHORIZED DENTAL volunteers
    rostered (coverage 1.0 -> 50 points), two VISION stations (SET_UP) with one
    AUTHORIZED VISION volunteer (coverage 0.5 -> 15 points), and one MEDICAL
    station (SET_UP) with one AUTHORIZED MEDICAL volunteer (coverage 1.0 ->
    20 points). Total score 85.0. Suspending one DENTAL volunteer drops DENTAL
    coverage to 0.5 and the total to 60.0 — exactly at the floor.

    Returns a dict: {"id", "version", "posture", "dental_volunteer_ids",
    "vision_volunteer_id", "medical_volunteer_id", "dental_assignment_ids"}.
    """
    event = create_event_site_locked(event_overrides, site_overrides)
    for _ in range(2):
        setup_station(event["id"], station_type="DENTAL")
    for _ in range(2):
        setup_station(event["id"], station_type="VISION")
    setup_station(event["id"], station_type="MEDICAL")

    dental_ids = []
    dental_assignment_ids = []
    for _ in range(2):
        v = create_volunteer(discipline="DENTAL")
        verify_volunteer(v["id"], event["id"])
        assignment = get_success_data(
            api_client.create_assignment(
                event["id"],
                create_assignment_payload(v["id"]),
                TEST_USERS["volunteer_coordinator_headers"],
            )
        )
        dental_assignment_ids.append(assignment["id"])
        dental_ids.append(v["id"])
    vision = create_volunteer(discipline="VISION")
    verify_volunteer(vision["id"], event["id"])
    get_success_data(
        api_client.create_assignment(
            event["id"],
            create_assignment_payload(vision["id"]),
            TEST_USERS["volunteer_coordinator_headers"],
        )
    )
    medical = create_volunteer(discipline="MEDICAL")
    verify_volunteer(medical["id"], event["id"])
    get_success_data(
        api_client.create_assignment(
            event["id"],
            create_assignment_payload(medical["id"]),
            TEST_USERS["volunteer_coordinator_headers"],
        )
    )
    for v in [*dental_ids, vision["id"], medical["id"]]:
        authorize_volunteer(v, event["id"])

    fact = _event_fact(event["id"])
    return {
        **fact,
        "dental_volunteer_ids": dental_ids,
        "vision_volunteer_id": vision["id"],
        "medical_volunteer_id": medical["id"],
        "dental_assignment_ids": dental_assignment_ids,
    }


# ---------------------------------------------------------------------------
# Tier 3 — manifests, cycles, sterilization-cleared stations
# ---------------------------------------------------------------------------
def create_unpacked_sterilizer_manifest(event_id: str, **overrides) -> dict:
    """Manifest with contains_sterilizer=true moved PACKED -> UNPACKED."""
    defaults = {"contains_sterilizer": True, "requires_loading_dock": False}
    defaults.update(overrides)
    manifest = get_success_data(
        api_client.create_manifest(
            event_id,
            create_manifest_payload(**defaults),
            TEST_USERS["logistics_coordinator_headers"],
        )
    )
    get_success_data(
        api_client.ship_manifest(
            event_id, manifest["id"], TEST_USERS["logistics_coordinator_headers"]
        )
    )
    get_success_data(
        api_client.deliver_manifest(
            event_id, manifest["id"], TEST_USERS["logistics_coordinator_headers"]
        )
    )
    return get_success_data(
        api_client.unpack_manifest(
            event_id, manifest["id"], TEST_USERS["logistics_coordinator_headers"]
        )
    )


def run_completed_cycle(event_id: str, batch_size: int = 2) -> dict:
    """Start a cycle and complete it. Returns the COMPLETED cycle dict."""
    cycle = get_success_data(
        api_client.start_sterilization_cycle(
            event_id,
            create_cycle_payload(batch_size),
            TEST_USERS["sterilization_tech_headers"],
        )
    )
    return get_success_data(
        api_client.complete_cycle(
            event_id, cycle["id"], TEST_USERS["sterilization_tech_headers"]
        )
    )


def setup_event_with_operational_sterile_station(
    station_overrides=None, event_overrides=None, site_overrides=None
) -> dict:
    """Event with one requires_sterilization station moved to OPERATIONAL via
    a completed sterilization cycle (no doors opened).

    Returns {"id", "version", "posture", "station_id"}.
    """
    st = {
        "station_type": "DENTAL",
        "chair_count": 2,
        "minutes_per_patient": 30,
        "requires_sterilization": True,
    }
    st.update(station_overrides or {})
    site = {"site_type": "ARENA", "square_footage": 30000, "sterilization_capable": True}
    site.update(site_overrides or {})
    event = create_event_site_locked(event_overrides, site)
    create_unpacked_sterilizer_manifest(event["id"])
    station = setup_station(event["id"], **st)
    run_completed_cycle(event["id"], batch_size=2)
    get_success_data(
        api_client.mark_station_operational(
            event["id"], station["id"], TEST_USERS["station_lead_headers"]
        )
    )
    return {**_event_fact(event["id"]), "station_id": station["id"]}


# ---------------------------------------------------------------------------
# Tier 4 — tickets, queue and encounters
# ---------------------------------------------------------------------------


def issue_ticket(event_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.issue_ticket(
            event_id,
            create_ticket_payload(**overrides),
            TEST_USERS["queue_marshal_headers"],
        )
    )


def setup_event_with_queued_ticket(
    service: str = "MEDICAL", event_overrides=None
) -> dict:
    """IN_SERVICE event plus one QUEUED ticket. Returns a dict with the event
    fact plus "station_id", "volunteer_id", "ticket_id"."""
    event = create_event_in_service(event_overrides)
    ticket = issue_ticket(event["id"], requested_service=service)
    return {**event, "ticket_id": ticket["id"]}


def setup_event_with_open_encounter(
    requires_followup: bool = False, event_overrides=None
) -> dict:
    """IN_SERVICE event; one ticket moved CALLED -> IN_SERVICE with an OPEN
    encounter. Returns dict with "id", "station_id", "volunteer_id",
    "ticket_id", "encounter_id"."""
    ctx = setup_event_with_queued_ticket(event_overrides=event_overrides)
    get_success_data(
        api_client.call_ticket(
            ctx["id"], ctx["ticket_id"], TEST_USERS["queue_marshal_headers"]
        )
    )
    # Beginning service requires the station's service window to be open at
    # the server's logical clock; advance the clock into the default window
    # (2026-10-03T11:00-19:00Z).
    get_success_data(
        api_client.set_clock(
            "2026-10-03T12:00:00Z", TEST_USERS["platform_admin_headers"]
        )
    )
    encounter = get_success_data(
        api_client.begin_service(
            ctx["id"],
            ctx["ticket_id"],
            begin_service_payload(
                ctx["station_id"],
                ctx["volunteer_id"],
                requires_followup=requires_followup,
            ),
            TEST_USERS["station_lead_headers"],
        )
    )
    return {**ctx, "encounter_id": encounter["id"]}


def complete_encounter_with_referral(event_id: str, encounter_id: str) -> dict:
    """Complete an OPEN encounter, bundling one referral."""
    return get_success_data(
        api_client.complete_encounter(
            event_id,
            encounter_id,
            {"referrals": [create_referral_payload()]},
            TEST_USERS["station_lead_headers"],
        )
    )


def setup_event_in_teardown(event_overrides=None) -> dict:
    """Event driven IN_SERVICE -> TEARDOWN with no active tickets."""
    event = create_event_in_service(event_overrides)
    ended = get_success_data(
        api_client.end_service(event["id"], TEST_USERS["event_director_headers"])
    )
    return {**event, "version": ended["version"], "posture": ended["posture"]}
