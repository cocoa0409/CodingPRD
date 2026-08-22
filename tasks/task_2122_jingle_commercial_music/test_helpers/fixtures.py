"""Composite setup helpers - the multi-step preambles the PRD workflows need.

Every helper uses get_success_data() so a broken setup step surfaces as a clear
"Setup step failed" assertion rather than a confusing downstream error. The
harness restarts the server before every test, so each helper builds its whole
world from scratch through PRD-declared endpoints only.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_booking_payload,
    create_brief_payload,
    create_client_payload,
    create_composer_payload,
    create_counter_payload,
    create_cue_entry_payload,
    create_demo_payload,
    create_library_track_payload,
    create_license_deal_payload,
    create_musician_payload,
    create_project_payload,
    create_reuse_extension_payload,
    create_session_call_payload,
    create_stems_payload,
    create_studio_room_payload,
)
from .test_users import (
    RIGHTS_ADMIN_DRAFTER_ID,
    RIGHTS_ADMIN_ISSUER_ID,
    make_afm_steward_headers,
    make_client_rep_headers,
    make_composer_headers,
    make_producer_headers,
    make_rights_admin_headers,
)

DEFAULT_CALL_START = "2026-09-10T09:00:00Z"
DEFAULT_CALL_END = "2026-09-10T13:00:00Z"
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

PLAYER_NAMES = [
    ("Mia Vance", "DRUMS"),
    ("Noel Park", "BASS"),
    ("Ola Reed", "KEYS"),
    ("Rio Sands", "GUITAR"),
    ("Sam Iyer", "STRINGS"),
    ("Tess Lowe", "BRASS"),
]
COMPOSER_NAMES = [
    ("Ada Rivers", "ASCAP"),
    ("Ben Cole", "BMI"),
    ("Cass Iver", "SESAC"),
    ("Dee Marsh", "NONE"),
]


# ---------------------------------------------------------------------------
# Tier 1: single-call creation helpers and reads
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, headers=None):
    """Move the logical clock and run the licence renewal sweep."""
    return get_success_data(api_client.set_clock(
        {"to_iso8601": to_iso8601}, headers or make_producer_headers()))


def create_client(**overrides):
    return get_success_data(api_client.create_client(
        create_client_payload(**overrides), make_producer_headers()))


def create_project(client_id, **overrides):
    return get_success_data(api_client.create_project(
        create_project_payload(client_id, **overrides), make_producer_headers()))


def create_brief(project_id, **overrides):
    return get_success_data(api_client.create_brief(
        project_id, create_brief_payload(**overrides), make_producer_headers()))


def approve_brief(brief_id, client_id):
    return get_success_data(api_client.approve_brief(
        brief_id, make_client_rep_headers(client_id)))


def create_composer(index=0, **overrides):
    name, pro = COMPOSER_NAMES[index % len(COMPOSER_NAMES)]
    payload = create_composer_payload(display_name=name, pro_affiliation=pro)
    payload.update(overrides)
    return get_success_data(api_client.create_composer(payload, make_producer_headers()))


def create_musician(index=0, cleared=True, **overrides):
    name, instrument = PLAYER_NAMES[index % len(PLAYER_NAMES)]
    payload = create_musician_payload(full_name=name, instrument=instrument)
    payload.update(overrides)
    musician = get_success_data(api_client.create_musician(payload, make_producer_headers()))
    if cleared:
        musician = set_afm_clearance(musician["id"], "SIGNATORY_CLEARED")
    return musician


def set_afm_clearance(musician_id, afm_member_status):
    return get_success_data(api_client.set_afm_clearance(
        musician_id, {"afm_member_status": afm_member_status}, make_afm_steward_headers()))


def create_studio_room(**overrides):
    return get_success_data(api_client.create_studio_room(
        create_studio_room_payload(**overrides), make_producer_headers()))


def create_library_track(**overrides):
    return get_success_data(api_client.create_library_track(
        create_library_track_payload(**overrides), make_producer_headers()))


def get_project(project_id, headers=None):
    return get_success_data(api_client.get_project(project_id, headers or make_producer_headers()))


def get_demo(demo_id, headers=None):
    return get_success_data(api_client.get_demo(demo_id, headers or make_producer_headers()))


def get_session_call(session_call_id, headers=None):
    return get_success_data(api_client.get_session_call(
        session_call_id, headers or make_producer_headers()))


def get_booking(booking_id, headers=None):
    return get_success_data(api_client.get_booking(
        booking_id, headers or make_producer_headers()))


def get_license_deal(license_deal_id, headers=None):
    return get_success_data(api_client.get_license_deal(
        license_deal_id, headers or make_producer_headers()))


def get_deliverable(deliverable_id, headers=None):
    return get_success_data(api_client.get_deliverable(
        deliverable_id, headers or make_producer_headers()))


def get_cue_entry(cue_entry_id, headers=None):
    return get_success_data(api_client.get_cue_entry(
        cue_entry_id, headers or make_producer_headers()))


def get_brief(project_id, brief_id, headers=None):
    briefs = get_success_data(api_client.list_project_briefs(
        project_id, headers or make_producer_headers(), params={"limit": 100, "offset": 0}))
    for brief in briefs:
        if brief["id"] == brief_id:
            return brief
    raise AssertionError(f"Setup step failed: brief {brief_id} not listed on project {project_id}")


# ---------------------------------------------------------------------------
# Tier 2: engagement state progression
# ---------------------------------------------------------------------------

def setup_engagement(budget_cents=None, target_markets=("US_NATIONAL",), required_lengths=(30,),
                     tempo_bpm=110, mood_tags=("cosy",), with_brief=True, **project_overrides):
    """Client + Project. With a brief the engagement sits in BRIEFING with a DRAFT brief."""
    client = create_client()
    project = create_project(
        client["id"],
        budget_cents=budget_cents if budget_cents is not None else TEST_DEFAULTS["BUDGET_CENTS"],
        **project_overrides)
    env = {
        "client": client,
        "client_headers": make_client_rep_headers(client["id"]),
        "project": project,
    }
    if with_brief:
        env["brief"] = create_brief(
            project["id"], tempo_bpm=tempo_bpm, mood_tags=list(mood_tags),
            target_markets=list(target_markets), required_lengths=list(required_lengths))
        env["project"] = get_project(project["id"])
    return env


def setup_engagement_in_demo(**kwargs):
    """Engagement whose single brief is APPROVED, so the engagement is IN_DEMO."""
    env = setup_engagement(**kwargs)
    env["brief"] = approve_brief(env["brief"]["id"], env["client"]["id"])
    env["project"] = get_project(env["project"]["id"])
    return env


def pitch_demo(project_id, composer_id, **overrides):
    return get_success_data(api_client.create_demo(
        project_id, create_demo_payload(**overrides), make_composer_headers(composer_id)))


def submit_demo(demo_id, composer_id):
    return get_success_data(api_client.submit_demo(demo_id, make_composer_headers(composer_id)))


def shortlist_demo(demo_id, client_id):
    return get_success_data(api_client.shortlist_demo(demo_id, make_client_rep_headers(client_id)))


def select_demo(demo_id, client_id):
    return get_success_data(api_client.select_demo(demo_id, make_client_rep_headers(client_id)))


def request_demo_revision(demo_id, client_id, revision_note="brighter chorus"):
    return get_success_data(api_client.request_demo_revision(
        demo_id, {"revision_note": revision_note}, make_client_rep_headers(client_id)))


def add_shortlisted_demo(env, composer_index=0, **demo_overrides):
    """Register a writer, pitch, submit and shortlist one demo on an IN_DEMO engagement."""
    composer = create_composer(index=composer_index)
    demo = pitch_demo(env["project"]["id"], composer["id"], **demo_overrides)
    submit_demo(demo["id"], composer["id"])
    demo = shortlist_demo(demo["id"], env["client"]["id"])
    return composer, demo


def setup_engagement_in_production(demo_fee_cents=None, demo_title="Cut One",
                                   submitted_length_seconds=30, composer_index=0,
                                   **engagement_kwargs):
    """Engagement driven all the way to IN_PRODUCTION through a selected demo."""
    env = setup_engagement_in_demo(**engagement_kwargs)
    composer, demo = add_shortlisted_demo(
        env, composer_index=composer_index, title=demo_title,
        demo_fee_cents=(demo_fee_cents if demo_fee_cents is not None
                        else TEST_DEFAULTS["DEMO_FEE_CENTS"]),
        submitted_length_seconds=submitted_length_seconds)
    demo = select_demo(demo["id"], env["client"]["id"])
    env.update({
        "composer": composer,
        "composer_headers": make_composer_headers(composer["id"]),
        "demo": demo,
        "project": get_project(env["project"]["id"]),
    })
    return env


# ---------------------------------------------------------------------------
# Tier 3: licence deal lifecycle
# ---------------------------------------------------------------------------

def draft_license_deal(env, drafter=RIGHTS_ADMIN_DRAFTER_ID, expected_project_version=None,
                       demo_id=None, **overrides):
    """Draft a deal against the engagement's freshly read version."""
    project = get_project(env["project"]["id"])
    version = (expected_project_version if expected_project_version is not None
               else project["version"])
    payload = create_license_deal_payload(
        project["id"], demo_id or env["demo"]["id"], version, **overrides)
    return get_success_data(api_client.create_license_deal(
        payload, make_rights_admin_headers(drafter)))


def propose_license_deal(deal_id, drafter=RIGHTS_ADMIN_DRAFTER_ID):
    return get_success_data(api_client.propose_license_deal(
        deal_id, make_rights_admin_headers(drafter)))


def counter_license_deal(deal_id, client_id, **overrides):
    return get_success_data(api_client.counter_license_deal(
        deal_id, create_counter_payload(**overrides), make_client_rep_headers(client_id)))


def accept_license_deal(deal_id, client_id):
    return get_success_data(api_client.accept_license_deal(
        deal_id, make_client_rep_headers(client_id)))


def activate_license_deal(deal_id, issuer=RIGHTS_ADMIN_ISSUER_ID):
    return get_success_data(api_client.activate_license_deal(
        deal_id, make_rights_admin_headers(issuer)))


def renew_license_deal(deal_id, operator=RIGHTS_ADMIN_ISSUER_ID):
    return get_success_data(api_client.renew_license_deal(
        deal_id, make_rights_admin_headers(operator)))


def setup_license_deal(env, stage="ACTIVE", drafter=RIGHTS_ADMIN_DRAFTER_ID,
                       issuer=RIGHTS_ADMIN_ISSUER_ID, **overrides):
    """Drive a licence deal to DRAFT, PROPOSED, ACCEPTED or ACTIVE."""
    deal = draft_license_deal(env, drafter=drafter, **overrides)
    if stage in ("PROPOSED", "ACCEPTED", "ACTIVE"):
        deal = propose_license_deal(deal["id"], drafter=drafter)
    if stage in ("ACCEPTED", "ACTIVE"):
        deal = accept_license_deal(deal["id"], env["client"]["id"])
    if stage == "ACTIVE":
        deal = activate_license_deal(deal["id"], issuer=issuer)
    env["deal"] = deal
    return deal


def setup_engagement_with_deal(stage="ACTIVE", deal_overrides=None, **engagement_kwargs):
    """Engagement in IN_PRODUCTION carrying one licence deal at the requested stage."""
    env = setup_engagement_in_production(**engagement_kwargs)
    setup_license_deal(env, stage=stage, **(deal_overrides or {}))
    return env


def create_deliverable(deal_id):
    return get_success_data(api_client.create_deliverable(deal_id, make_producer_headers()))


def setup_engagement_with_deliverable(stage="ACTIVE", deal_overrides=None, **engagement_kwargs):
    """Engagement + licence deal + its single delivery package."""
    env = setup_engagement_with_deal(
        stage=stage, deal_overrides=deal_overrides, **engagement_kwargs)
    env["deliverable"] = create_deliverable(env["deal"]["id"])
    return env


def add_cue_entry(deliverable_id, composer_id, operator=RIGHTS_ADMIN_ISSUER_ID, **overrides):
    return get_success_data(api_client.create_cue_entry(
        deliverable_id, create_cue_entry_payload(composer_id, **overrides),
        make_rights_admin_headers(operator)))


def void_cue_entry(cue_entry_id, operator=RIGHTS_ADMIN_ISSUER_ID):
    return get_success_data(api_client.void_cue_entry(
        cue_entry_id, make_rights_admin_headers(operator)))


def file_cue_sheet(deliverable_id, operator=RIGHTS_ADMIN_ISSUER_ID):
    return get_success_data(api_client.file_cue_sheet(
        deliverable_id, make_rights_admin_headers(operator)))


def register_cue_sheet(deliverable_id, operator=RIGHTS_ADMIN_ISSUER_ID):
    return get_success_data(api_client.register_cue_sheet(
        deliverable_id, make_rights_admin_headers(operator)))


def deliver_stems(deliverable_id, lengths_seconds=None, stem_names=None):
    payload = create_stems_payload()
    if lengths_seconds is not None:
        payload["lengths_seconds"] = list(lengths_seconds)
    if stem_names is not None:
        payload["stem_names"] = list(stem_names)
    return get_success_data(api_client.deliver_stems(
        deliverable_id, payload, make_producer_headers()))


def create_reuse_extension(deal_id, market_code, expected_license_deal_version=None,
                           operator=RIGHTS_ADMIN_ISSUER_ID):
    version = expected_license_deal_version
    if version is None:
        version = get_license_deal(deal_id)["version"]
    return get_success_data(api_client.create_reuse_extension(
        deal_id, create_reuse_extension_payload(market_code, version),
        make_rights_admin_headers(operator)))


# ---------------------------------------------------------------------------
# Tier 4: session calls, bookings and settlement
# ---------------------------------------------------------------------------

def schedule_session_call(project_id, studio_room_id, start=DEFAULT_CALL_START,
                          end=DEFAULT_CALL_END):
    return get_success_data(api_client.create_session_call(
        create_session_call_payload(
            project_id, studio_room_id, scheduled_start_utc=start, scheduled_end_utc=end),
        make_producer_headers()))


def book_musician(session_call_id, musician_id, is_leader=False, doubles_count=0):
    return get_success_data(api_client.create_booking(
        session_call_id,
        create_booking_payload(musician_id, is_leader=is_leader, doubles_count=doubles_count),
        make_producer_headers()))


def confirm_session_call(session_call_id):
    return get_success_data(api_client.confirm_session_call(
        session_call_id, make_producer_headers()))


def complete_session_call(session_call_id, actual_end_utc):
    return get_success_data(api_client.complete_session_call(
        session_call_id, {"actual_end_utc": actual_end_utc}, make_producer_headers()))


def cancel_session_call(session_call_id, reason="client postponed the shoot"):
    return get_success_data(api_client.cancel_session_call(
        session_call_id, {"reason": reason}, make_producer_headers()))


def setup_players(count=3, scale_hourly_cents=None, cleared=True):
    """Register `count` session players, cleared for signatory work by default."""
    rate = (scale_hourly_cents if scale_hourly_cents is not None
            else TEST_DEFAULTS["SCALE_HOURLY_CENTS"])
    return [create_musician(index=i, cleared=cleared, scale_hourly_cents=rate)
            for i in range(count)]


def setup_booked_call(env, players=3, room=None, start=DEFAULT_CALL_START, end=DEFAULT_CALL_END,
                      scale_hourly_cents=None, hourly_rate_cents=None, capacity_players=None,
                      is_leader=False, doubles_count=0, musicians=None, room_name="Room A"):
    """A SCHEDULED SessionCall in a fresh room with `players` booked lines on it."""
    if room is None:
        room = create_studio_room(
            name=room_name,
            hourly_rate_cents=(hourly_rate_cents if hourly_rate_cents is not None
                               else TEST_DEFAULTS["ROOM_HOURLY_RATE_CENTS"]),
            capacity_players=(capacity_players if capacity_players is not None
                              else TEST_DEFAULTS["ROOM_CAPACITY_PLAYERS"]))
    if musicians is None:
        musicians = setup_players(count=players, scale_hourly_cents=scale_hourly_cents)
    call = schedule_session_call(env["project"]["id"], room["id"], start=start, end=end)
    bookings = [book_musician(call["id"], m["id"], is_leader=is_leader,
                              doubles_count=doubles_count) for m in musicians]
    return {"room": room, "musicians": musicians, "call": call, "bookings": bookings}


def setup_confirmed_call(env, **kwargs):
    """A CONFIRMED SessionCall whose commitment is frozen on the engagement ledger."""
    booked = setup_booked_call(env, **kwargs)
    booked["call"] = confirm_session_call(booked["call"]["id"])
    return booked


def setup_engagement_with_confirmed_call(budget_cents=None, demo_fee_cents=150_000, players=3,
                                         clock=DEFAULT_CLOCK, start=DEFAULT_CALL_START,
                                         end=DEFAULT_CALL_END, scale_hourly_cents=None,
                                         hourly_rate_cents=None, is_leader=False,
                                         doubles_count=0, **engagement_kwargs):
    """Clock + IN_PRODUCTION engagement + one CONFIRMED call with `players` booked lines."""
    set_clock(clock)
    env = setup_engagement_in_production(
        budget_cents=budget_cents, demo_fee_cents=demo_fee_cents, **engagement_kwargs)
    env.update(setup_confirmed_call(
        env, players=players, start=start, end=end, scale_hourly_cents=scale_hourly_cents,
        hourly_rate_cents=hourly_rate_cents, is_leader=is_leader, doubles_count=doubles_count))
    env["project"] = get_project(env["project"]["id"])
    return env


def setup_two_same_day_completed_calls(clock=DEFAULT_CLOCK, budget_cents=None,
                                       demo_fee_cents=150_000, players=3,
                                       scale_hourly_cents=None, hourly_rate_cents=None,
                                       first=("2026-09-10T09:00:00Z", "2026-09-10T13:00:00Z"),
                                       second=("2026-09-10T14:00:00Z", "2026-09-10T19:00:00Z")):
    """Two COMPLETED calls on the same UTC date sharing one room and one player roster."""
    set_clock(clock)
    env = setup_engagement_in_production(
        budget_cents=budget_cents, demo_fee_cents=demo_fee_cents)
    room = create_studio_room(
        hourly_rate_cents=(hourly_rate_cents if hourly_rate_cents is not None
                           else TEST_DEFAULTS["ROOM_HOURLY_RATE_CENTS"]))
    musicians = setup_players(count=players, scale_hourly_cents=scale_hourly_cents)
    first_call = setup_booked_call(
        env, room=room, musicians=musicians, start=first[0], end=first[1])
    second_call = setup_booked_call(
        env, room=room, musicians=musicians, start=second[0], end=second[1])
    confirm_session_call(first_call["call"]["id"])
    confirm_session_call(second_call["call"]["id"])
    env["first"] = complete_session_call(first_call["call"]["id"], first[1])
    env["second"] = complete_session_call(second_call["call"]["id"], second[1])
    env["room"] = room
    env["musicians"] = musicians
    env["first_bookings"] = first_call["bookings"]
    env["second_bookings"] = second_call["bookings"]
    env["project"] = get_project(env["project"]["id"])
    return env
