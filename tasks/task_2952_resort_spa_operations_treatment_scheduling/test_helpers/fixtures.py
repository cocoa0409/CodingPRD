"""Composite setup builders.

The harness restarts the server before every test, so each test begins against
an empty database and every precondition here is built from scratch through the
public API only.

Actor discipline (PRD §2.1 segregation of duties): a licence's submitting
ComplianceOfficer and its reviewing ComplianceOfficer must be DISTINCT user ids,
and an intake form's screening ComplianceOfficer must differ from the
SpaDirector who overrides it. The default ids below keep those pairs distinct.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import (
    CANON_BOOKING_CLOCK,
    CANON_CONSENT_VERSION,
    CANON_START_AT,
)
from . import factories as f
from .test_users import (
    make_compliance_headers,
    make_coordinator_headers,
    make_director_headers,
    make_guest_headers,
    make_therapist_headers,
)

# Distinct ComplianceOfficer identities, mirroring the design-index chains.
CO_SUBMIT = "co-1"
CO_REVIEW = "co-2"
CO_SCREEN = "co-3"
CO_REVOKE = "co-4"
CO_SPARE = "co-5"

DIRECTOR = make_director_headers()
COORDINATOR = make_coordinator_headers()
COMPLIANCE = make_compliance_headers(CO_SUBMIT)


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(current_utc: str, headers=None) -> dict:
    """PRD §2.4: only a SpaDirector may move the logical clock."""
    response = api_client.set_clock(
        f.clock_payload(current_utc), headers or DIRECTOR)
    return get_success_data(response)


def create_treatment_type(code="HYDRO90", headers=None, **overrides) -> dict:
    response = api_client.create_treatment_type(
        f.treatment_type_payload(code=code, **overrides), headers or DIRECTOR)
    return get_success_data(response, 201)


def create_room(code="HYDRO-1", headers=None, **overrides) -> dict:
    response = api_client.create_treatment_room(
        f.treatment_room_payload(code=code, **overrides), headers or DIRECTOR)
    return get_success_data(response, 201)


def set_room_status(room_id: str, status: str, headers=None) -> dict:
    response = api_client.patch_treatment_room(
        room_id, f.room_status_payload(status), headers or DIRECTOR)
    return get_success_data(response)


def create_therapist(full_name="Leilani Akana", headers=None, **overrides) -> dict:
    response = api_client.create_therapist(
        f.therapist_payload(full_name=full_name, **overrides), headers or DIRECTOR)
    return get_success_data(response, 201)


def submit_license(therapist_id: str, submit_user=CO_SUBMIT, **overrides) -> dict:
    response = api_client.create_license(
        therapist_id, f.license_payload(**overrides),
        make_compliance_headers(submit_user))
    return get_success_data(response, 201)


def review_license(license_id: str, decision="VERIFIED", review_user=CO_REVIEW,
                   review_note=None) -> dict:
    response = api_client.review_license(
        license_id, f.review_payload(decision, review_note),
        make_compliance_headers(review_user))
    return get_success_data(response)


def verified_license(therapist_id: str, submit_user=CO_SUBMIT,
                     review_user=CO_REVIEW, **overrides) -> dict:
    """Submit then VERIFY a licence using two DISTINCT ComplianceOfficer ids."""
    license_row = submit_license(therapist_id, submit_user=submit_user, **overrides)
    return review_license(license_row["id"], "VERIFIED", review_user=review_user)


def grant_certification(therapist_id: str, user=CO_REVIEW, **overrides) -> dict:
    response = api_client.create_certification(
        therapist_id, f.certification_payload(**overrides),
        make_compliance_headers(user))
    return get_success_data(response, 201)


def revoke_certification(certification_id: str, user=CO_REVOKE,
                         reason_note=None) -> dict:
    response = api_client.revoke_certification(
        certification_id, f.revoke_payload(reason_note),
        make_compliance_headers(user))
    return get_success_data(response)


def add_ce_record(license_id: str, headers=None, **overrides) -> dict:
    response = api_client.create_ce_record(
        license_id, f.ce_record_payload(**overrides),
        headers or make_compliance_headers(CO_SUBMIT))
    return get_success_data(response, 201)


def add_shift_block(therapist_id: str, headers=None, **overrides) -> dict:
    response = api_client.create_shift_block(
        therapist_id, f.shift_block_payload(**overrides), headers or COORDINATOR)
    return get_success_data(response, 201)


def create_guest(full_name="Nia Kalani", headers=None, **overrides) -> dict:
    response = api_client.create_guest(
        f.guest_payload(full_name=full_name, **overrides), headers or COORDINATOR)
    return get_success_data(response, 201)


def screened_intake(guest_id: str, guest_version: int, condition_codes=None,
                    medications=None, consent_version=CANON_CONSENT_VERSION,
                    screen_user=CO_SCREEN, sign_consent=True, screen=True) -> dict:
    """Drive an intake form from DRAFT through consent and submission to a
    screened state. With no condition codes the screen lands SCREENED_CLEAR."""
    guest_headers = make_guest_headers(guest_id)
    intake = get_success_data(api_client.create_intake_form(
        guest_id,
        f.intake_form_payload(
            guest_version,
            condition_codes=[] if condition_codes is None else condition_codes,
            medications=[] if medications is None else medications),
        guest_headers), 201)
    if sign_consent:
        get_success_data(api_client.sign_consent(
            intake["id"], f.consent_payload(consent_version), guest_headers))
    get_success_data(api_client.submit_intake_form(intake["id"], {}, guest_headers))
    if screen:
        return get_success_data(api_client.screen_intake_form(
            intake["id"], {}, make_compliance_headers(screen_user)))
    return get_success_data(api_client.get_intake_form(intake["id"], guest_headers))


def book_appointment(guest_id, treatment_type_id, room_id, start_at=CANON_START_AT,
                     therapist_id=None, headers=None) -> dict:
    response = api_client.create_appointment(
        f.appointment_payload(guest_id, treatment_type_id, room_id, start_at,
                              therapist_id),
        headers or COORDINATOR)
    return validate_success(response, 201)


def confirm(appointment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.confirm_appointment(appointment_id, {}, headers or COORDINATOR))


def check_in(appointment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.check_in_appointment(appointment_id, {}, headers or COORDINATOR))


def start_service(appointment_id: str, therapist_id: str) -> dict:
    return get_success_data(api_client.start_appointment(
        appointment_id, {}, make_therapist_headers(therapist_id)))


def complete_service(appointment_id: str, therapist_id: str,
                     actual_duration_minutes: int, gratuity_cents=None) -> dict:
    return get_success_data(api_client.complete_appointment(
        appointment_id, f.complete_payload(actual_duration_minutes, gratuity_cents),
        make_therapist_headers(therapist_id)))


# ---------------------------------------------------------------------------
# Composite world
# ---------------------------------------------------------------------------

class SpaWorld:
    """The canonical fixture: one HYDRO90 treatment type, one or more HYDRO
    rooms, one credentialled SENIOR therapist on an all-day AVAILABLE block, and
    one PLATINUM guest with a SCREENED_CLEAR intake."""

    def __init__(self):
        self.treatment_type = None
        self.rooms = {}
        self.therapists = {}
        self.licenses = {}
        self.certifications = {}
        self.guest = None
        self.intake = None
        self.appointments = {}

    # -- convenience accessors ------------------------------------------
    @property
    def treatment_type_id(self):
        return self.treatment_type["id"]

    @property
    def room(self):
        return next(iter(self.rooms.values()))

    @property
    def room_id(self):
        return self.room["id"]

    def room_of(self, code):
        return self.rooms[code]["id"]

    @property
    def therapist(self):
        return next(iter(self.therapists.values()))

    @property
    def therapist_id(self):
        return self.therapist["id"]

    def therapist_of(self, name):
        return self.therapists[name]["id"]

    @property
    def license_id(self):
        return next(iter(self.licenses.values()))["id"]

    @property
    def certification_id(self):
        return next(iter(self.certifications.values()))["id"]

    @property
    def guest_id(self):
        return self.guest["id"]

    @property
    def guest_headers(self):
        return make_guest_headers(self.guest["id"])

    @property
    def therapist_headers(self):
        return make_therapist_headers(self.therapist_id)

    # -- live reads ------------------------------------------------------
    def fetch_room(self, code=None):
        room_id = self.room_id if code is None else self.room_of(code)
        return validate_success(api_client.get_treatment_room(room_id, DIRECTOR))

    def fetch_therapist(self, name=None):
        therapist_id = self.therapist_id if name is None else self.therapist_of(name)
        return validate_success(api_client.get_therapist(therapist_id, DIRECTOR))

    def fetch_guest(self):
        return validate_success(api_client.get_guest(self.guest_id, COORDINATOR))

    def fetch_appointment(self, appointment_id):
        return validate_success(
            api_client.get_appointment(appointment_id, COORDINATOR))


def build_world(room_codes=("HYDRO-1",), therapist_names=("Leilani Akana",),
                clock=CANON_BOOKING_CLOCK, treatment_type_overrides=None,
                room_overrides=None, therapist_overrides=None,
                guest_overrides=None, shift_block_overrides=None,
                condition_codes=None, medications=None,
                consent_version=CANON_CONSENT_VERSION,
                screen_intake=True, sign_consent=True,
                license_overrides=None, certification_overrides=None,
                with_guest=True) -> SpaWorld:
    """Build the canonical world.

    The clock is parked at `clock` (default 2026-08-03T09:00:00.000Z) so that a
    2026-08-10 start satisfies the 120-minute booking lead time of PRD §3.5.
    """
    world = SpaWorld()
    if clock is not None:
        set_clock(clock)

    world.treatment_type = create_treatment_type(**(treatment_type_overrides or {}))

    for code in room_codes:
        world.rooms[code] = create_room(code=code, **(room_overrides or {}))

    for index, name in enumerate(therapist_names):
        therapist = create_therapist(full_name=name, **(therapist_overrides or {}))
        world.therapists[name] = therapist
        lic_overrides = dict(license_overrides or {})
        lic_overrides.setdefault("license_number", f"HI-LMT-441{index}")
        world.licenses[name] = verified_license(
            therapist["id"],
            submit_user=f"co-1{index}", review_user=f"co-2{index}",
            **lic_overrides)
        world.certifications[name] = grant_certification(
            therapist["id"], user=f"co-2{index}",
            **(certification_overrides or {}))
        add_shift_block(therapist["id"], **(shift_block_overrides or {}))

    if with_guest:
        world.guest = create_guest(**(guest_overrides or {}))
        world.intake = screened_intake(
            world.guest["id"], world.guest["version"],
            condition_codes=condition_codes, medications=medications,
            consent_version=consent_version, sign_consent=sign_consent,
            screen=screen_intake)
    return world


def world_with_confirmed_appointment(start_at=CANON_START_AT, **kwargs) -> SpaWorld:
    """The canonical world plus one CONFIRMED appointment at `start_at`."""
    world = build_world(**kwargs)
    appointment = book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, start_at,
        world.therapist_id)
    world.appointments["a"] = confirm(appointment["id"])
    return world


def world_with_checked_in_appointment(start_at=CANON_START_AT,
                                     arrival_clock="2026-08-10T16:45:00.000Z",
                                     **kwargs) -> SpaWorld:
    """CONFIRMED then CHECKED_IN — check-in posts the TREATMENT folio charge."""
    world = world_with_confirmed_appointment(start_at=start_at, **kwargs)
    set_clock(arrival_clock)
    world.appointments["a"] = check_in(world.appointments["a"]["id"])
    return world


def world_with_completed_appointment(start_at=CANON_START_AT,
                                     arrival_clock="2026-08-10T16:45:00.000Z",
                                     start_clock="2026-08-10T17:00:00.000Z",
                                     actual_duration_minutes=105,
                                     gratuity_cents=None, **kwargs) -> SpaWorld:
    """Drive the canonical appointment all the way to COMPLETED."""
    world = world_with_checked_in_appointment(
        start_at=start_at, arrival_clock=arrival_clock, **kwargs)
    appointment_id = world.appointments["a"]["id"]
    set_clock(start_clock)
    start_service(appointment_id, world.therapist_id)
    world.appointments["a"] = complete_service(
        appointment_id, world.therapist_id, actual_duration_minutes, gratuity_cents)
    return world


def appointment_id_of(world: SpaWorld, key="a") -> str:
    return world.appointments[key]["id"]
