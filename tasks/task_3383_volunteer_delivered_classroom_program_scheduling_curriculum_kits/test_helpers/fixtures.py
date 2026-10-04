"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch via PRD-declared endpoints —
each test starts against an empty database with the logical clock at its
documented default of 2026-09-01T00:00:00Z (PRD §2.4). The default is relied
on directly; the clock is only ever moved forward.

Setup calls use the lenient ``get_success_data`` so a broken precondition
fails loudly with a "Setup failed" style error rather than a confusing
assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import funding_floor_cents, required_kits
from .factories import (
    area_office_payload,
    capstone_event_payload,
    corporate_partner_payload,
    delivery_payload,
    district_payload,
    kit_inventory_payload,
    partnership_agreement_payload,
    program_catalog_payload,
    school_payload,
    session_payload,
    students_payload,
    volunteer_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["area_director_headers"]
PARTNER_MGR = TEST_USERS["partnership_manager_headers"]
COORDINATOR = TEST_USERS["program_coordinator_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
FUNDER = TEST_USERS["funder_headers"]


# ---------------------------------------------------------------------------
# clock + single-entity creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock forward (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def make_area_office(**overrides) -> dict:
    return get_success_data(api_client.create_area_office(area_office_payload(**overrides), ADMIN), 201)


def make_district(area_office_id, activate=True, **overrides) -> dict:
    district = get_success_data(
        api_client.create_district(district_payload(area_office_id, **overrides), DIRECTOR), 201
    )
    if activate:
        district = get_success_data(
            api_client.transition_district(district["id"], {"action": "ACTIVATE"}, DIRECTOR)
        )
    return district


def transition_district(district_id, action) -> dict:
    return get_success_data(api_client.transition_district(district_id, {"action": action}, DIRECTOR))


def make_school(district_id, **overrides) -> dict:
    return get_success_data(api_client.create_school(school_payload(district_id, **overrides), DIRECTOR), 201)


def make_partner(activate=True, **overrides) -> dict:
    partner = get_success_data(
        api_client.create_corporate_partner(corporate_partner_payload(**overrides), PARTNER_MGR), 201
    )
    if activate:
        partner = get_success_data(
            api_client.transition_corporate_partner(partner["id"], {"action": "ACTIVATE"}, PARTNER_MGR)
        )
    return partner


def credential_event(volunteer_id, kind, event) -> dict:
    return get_success_data(
        api_client.create_credential_event(volunteer_id, {"kind": kind, "event": event}, PARTNER_MGR)
    )


def make_volunteer(corporate_partner_id, credentialed=True, **overrides) -> dict:
    """Recruit a volunteer; when credentialed, CLEAR screening and COMPLETE training."""
    volunteer = get_success_data(
        api_client.create_volunteer(volunteer_payload(corporate_partner_id, **overrides), PARTNER_MGR), 201
    )
    if credentialed:
        credential_event(volunteer["id"], "SCREENING", "CLEAR")
        credential_event(volunteer["id"], "TRAINING", "BEGIN")
        volunteer = credential_event(volunteer["id"], "TRAINING", "COMPLETE")
    return volunteer


def make_program(**overrides) -> dict:
    return get_success_data(api_client.create_program_catalog(program_catalog_payload(**overrides), ADMIN), 201)


def make_agreement(school_id, program_catalog_id, sponsor_partner_id, activate=False, **overrides) -> dict:
    agreement = get_success_data(
        api_client.create_partnership_agreement(
            partnership_agreement_payload(school_id, program_catalog_id, sponsor_partner_id, **overrides),
            DIRECTOR,
        ),
        201,
    )
    if activate:
        agreement = transition_agreement(agreement["id"], "PROPOSE")
        agreement = transition_agreement(agreement["id"], "ACTIVATE")
    return agreement


def transition_agreement(agreement_id, action, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.transition_partnership_agreement(agreement_id, payload, DIRECTOR))


def record_funding(agreement_id, amount_cents) -> dict:
    return transition_agreement(agreement_id, "RECORD_FUNDING", amount_cents=amount_cents)


def make_inventory(area_office_id, program_catalog_id, assemble=0) -> dict:
    inventory = get_success_data(
        api_client.create_kit_inventory(
            kit_inventory_payload(area_office_id, program_catalog_id), LOGISTICS
        ),
        201,
    )
    if assemble:
        inventory = get_success_data(
            api_client.transition_kit_inventory(
                inventory["id"], {"action": "ASSEMBLE", "quantity": assemble}, LOGISTICS
            )
        )
    return inventory


# ---------------------------------------------------------------------------
# read helpers
# ---------------------------------------------------------------------------

def get_agreement(agreement_id) -> dict:
    return get_success_data(api_client.get_partnership_agreement(agreement_id, DIRECTOR))


def get_delivery(delivery_id) -> dict:
    return get_success_data(api_client.get_delivery(delivery_id, COORDINATOR))


def get_session(session_id) -> dict:
    return get_success_data(api_client.get_session(session_id, COORDINATOR))


def get_volunteer(volunteer_id) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, PARTNER_MGR))


def get_inventory(inventory_id) -> dict:
    return get_success_data(api_client.get_kit_inventory(inventory_id, LOGISTICS))


def get_capstone(capstone_id) -> dict:
    return get_success_data(api_client.get_capstone_event(capstone_id, COORDINATOR))


def get_student(student_id) -> dict:
    return get_success_data(api_client.get_student(student_id, COORDINATOR))


def get_evaluation(agreement_id, variant="PROVISIONAL") -> dict:
    return get_success_data(
        api_client.get_evaluation(agreement_id, FUNDER, params={"variant": variant})
    )


# ---------------------------------------------------------------------------
# deliveries, sessions, kits
# ---------------------------------------------------------------------------

def make_delivery(agreement_id, lead_volunteer_id, expected_agreement_version=None, **overrides) -> dict:
    """Create a delivery, reading the agreement's current version when the OCC
    field is not supplied (PRD §2.6: creating a delivery bumps that version)."""
    if expected_agreement_version is None:
        expected_agreement_version = get_agreement(agreement_id)["version"]
    return get_success_data(
        api_client.create_delivery(
            delivery_payload(agreement_id, lead_volunteer_id, expected_agreement_version, **overrides),
            COORDINATOR,
        ),
        201,
    )


def transition_delivery(delivery_id, action, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.transition_delivery(delivery_id, payload, COORDINATOR))


def plan_delivery(delivery_id) -> dict:
    return transition_delivery(delivery_id, "PLAN")


def add_roster(delivery_id, count, prefix="Stu") -> list:
    names = tuple(f"{prefix} {i + 1}" for i in range(count))
    return get_success_data(api_client.create_students(students_payload(delivery_id, names), COORDINATOR), 201)


def add_session(delivery_id, volunteer_id, scheduled_date, start_minutes=540, end_minutes=600, confirm=False) -> dict:
    session = get_success_data(
        api_client.create_session(
            session_payload(
                delivery_id,
                volunteer_id,
                scheduled_date,
                start_minutes=start_minutes,
                end_minutes=end_minutes,
            ),
            COORDINATOR,
        ),
        201,
    )
    if confirm:
        session = get_success_data(
            api_client.transition_session(session["id"], {"action": "CONFIRM"}, COORDINATOR)
        )
    return session


def confirm_session(session_id) -> dict:
    return get_success_data(api_client.transition_session(session_id, {"action": "CONFIRM"}, COORDINATOR))


def schedule_delivery(delivery_id) -> dict:
    """CONFIRM_TEACHER -> RESERVE_KITS -> SCHEDULE (PRD §3.4 gates)."""
    transition_delivery(delivery_id, "CONFIRM_TEACHER")
    transition_delivery(delivery_id, "RESERVE_KITS")
    return transition_delivery(delivery_id, "SCHEDULE")


def record_session_delivery(session_id, ymd: str) -> dict:
    """Move the clock onto the session date, then RECORD_DELIVERY (PRD §3.5)."""
    set_clock(f"{ymd}T09:00:00Z")
    return get_success_data(api_client.transition_session(session_id, {"action": "RECORD_DELIVERY"}, COORDINATOR))


def make_capstone(delivery_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_capstone_event(capstone_event_payload(delivery_id, **overrides), COORDINATOR),
        201,
    )


def transition_capstone(capstone_id, action, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.transition_capstone_event(capstone_id, payload, COORDINATOR))


# ---------------------------------------------------------------------------
# composite worlds
# ---------------------------------------------------------------------------

def base_world(
    session_count=4,
    minutes_per_session=60,
    capstone_required=False,
    capstone_facility="NONE",
    min_students=4,
    max_students=30,
    program_code="JA-BIZ",
    program_grade_band=(3, 5),
    pledge_cents=None,
    assemble=None,
    school_grade_band=(1, 5),
):
    """Territory (office -> PARTNER district -> school) + ACTIVE sponsor partner
    with one fully credentialed volunteer + program + ACTIVE agreement.

    Returns a dict of the created entities. When ``assemble`` is not None, a
    kit inventory row for the (office, program) pair is also created and
    assembled to that quantity.
    """
    office = make_area_office()
    district = make_district(office["id"], activate=True)
    school = make_school(
        district["id"], grade_band_low=school_grade_band[0], grade_band_high=school_grade_band[1]
    )
    partner = make_partner(activate=True)
    volunteer = make_volunteer(partner["id"], credentialed=True)
    program = make_program(
        code=program_code,
        session_count=session_count,
        minutes_per_session=minutes_per_session,
        capstone_required=capstone_required,
        capstone_facility=capstone_facility,
        min_students=min_students,
        max_students=max_students,
        grade_band_low=program_grade_band[0],
        grade_band_high=program_grade_band[1],
    )
    if pledge_cents is None:
        pledge_cents = funding_floor_cents(session_count)
    agreement = make_agreement(
        school["id"], program["id"], partner["id"], activate=True, funding_pledged_cents=pledge_cents
    )
    world = {
        "office": office,
        "district": district,
        "school": school,
        "partner": partner,
        "volunteer": volunteer,
        "program": program,
        "agreement": agreement,
    }
    if assemble is not None:
        world["inventory"] = make_inventory(office["id"], program["id"], assemble=assemble)
    return world


def add_partner_with_volunteer(name="Beta Corp", industry="Finance", email="vol2@beta.example", credentialed=True) -> dict:
    """Second ACTIVE partner plus a credentialed volunteer."""
    partner = make_partner(activate=True, name=name, industry=industry)
    volunteer = make_volunteer(partner["id"], credentialed=credentialed, full_name="Vol Two", email=email)
    return {"partner": partner, "volunteer": volunteer}


def planned_delivery(world, enrolled_count=10, lead=None, **overrides) -> dict:
    """Delivery taken to PLANNED (PRD §3.4 four gates satisfied)."""
    lead = lead or world["volunteer"]["id"]
    delivery = make_delivery(
        world["agreement"]["id"], lead, enrolled_count=enrolled_count, **overrides
    )
    return plan_delivery(delivery["id"])


def scheduled_delivery(world, session_dates, enrolled_count=10, start_minutes=540, end_minutes=600, lead=None, **overrides) -> dict:
    """Delivery with every date in ``session_dates`` CONFIRMED, then taken to
    SCHEDULED (teacher confirmed, kits reserved, cadence satisfied)."""
    lead = lead or world["volunteer"]["id"]
    delivery = make_delivery(
        world["agreement"]["id"], lead, enrolled_count=enrolled_count, **overrides
    )
    plan_delivery(delivery["id"])
    sessions = [
        add_session(
            delivery["id"],
            lead,
            d,
            start_minutes=start_minutes,
            end_minutes=end_minutes,
            confirm=True,
        )
        for d in session_dates
    ]
    delivery = schedule_delivery(delivery["id"])
    return {"delivery": delivery, "sessions": sessions}


# four consecutive Tuesdays from 2026-09-08 — the canonical cadence-legal set
TUESDAYS_4 = ["2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29"]
TUESDAYS_5 = TUESDAYS_4 + ["2026-10-06"]
WEDNESDAYS_4 = ["2026-09-09", "2026-09-16", "2026-09-23", "2026-09-30"]
