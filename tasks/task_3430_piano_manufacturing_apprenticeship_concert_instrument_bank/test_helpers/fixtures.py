"""Composite setup helpers.

Every fixture builds preconditions from scratch through PRD-declared endpoints
(the harness restarts the server before every test, so each test starts on an
empty database with the logical clock at its startup value). Setup calls use
the lenient get_success_data validator so a failed precondition surfaces as a
clear setup error, not a confusing assertion failure.

Clock discipline: all clock moves are derived from freshly created entities'
own timestamps (drying_started_at, seasoning_started_at, next_review_date),
so every move is forward-only regardless of what earlier fixtures did.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_START_ISO,
    HOURS_REQUIRED,
    MIN_DRYING_DAYS,
    MOISTURE_READY_PCT,
    SEASONING_MIN_DAYS,
)
from .factories import (
    advance_build_payload,
    advance_restoration_payload,
    assess_payload,
    complete_restoration_payload,
    confirm_loan_payload,
    create_apprentice_payload,
    create_artist_payload,
    create_build_order_payload,
    create_craftsman_payload,
    create_endorsement_payload,
    create_loan_payload,
    create_restoration_payload,
    create_wood_batch_payload,
    log_hours_payload,
    moisture_reading_payload,
    performance_payload,
    resolve_authenticity_payload,
    return_loan_payload,
    review_endorsement_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_apprentice_headers,
    make_artist_headers,
    make_master_craftsman_headers,
)

WM = TEST_USERS["workshop_manager_headers"]
LIAISON = TEST_USERS["artist_liaison_headers"]


# --- Logical clock helpers (PRD section 2.4) ---

def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_days_after(base_iso: str, days: int) -> str:
    """Whole-day arithmetic on an ISO 8601 UTC timestamp."""
    return _format_iso(_parse_iso(base_iso) + timedelta(days=days))


def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock forward (strict: regression is a setup bug)."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), WM)
    return get_success_data(resp)


def ensure_clock_at_least(to_iso8601: str) -> None:
    """Move the clock to to_iso8601 unless it is already at or past it.

    The clock has no read endpoint, so a regression error here means the clock
    is already ahead of the target, which satisfies the caller's need.
    """
    resp = api_client.set_clock(set_clock_payload(to_iso8601), WM)
    if resp.status_code == 422:
        return
    get_success_data(resp)


def set_clock_days_after(base_iso: str, days: int) -> str:
    """Set the clock to base_iso + days (forward only); returns the new instant."""
    target = iso_days_after(base_iso, days)
    set_clock(target)
    return target


# --- Wood batches (PRD section 3.1) ---

def create_wood_batch(species="MAPLE", moisture_content_pct=12.0) -> dict:
    resp = api_client.create_wood_batch(
        create_wood_batch_payload(species, moisture_content_pct), WM
    )
    return get_success_data(resp)


def record_moisture(batch_id: str, moisture_content_pct=MOISTURE_READY_PCT) -> dict:
    resp = api_client.record_moisture_reading(
        batch_id, moisture_reading_payload(moisture_content_pct), WM
    )
    return get_success_data(resp)


def get_wood_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_wood_batch(batch_id, WM))


def condition_wood_batch(batch=None, *, species="MAPLE", initial_moisture=12.0,
                         ready_moisture=MOISTURE_READY_PCT,
                         drying_days=MIN_DRYING_DAYS) -> dict:
    """Create (or take) a DRYING batch and drive it to the drying gate:
    clock -> drying_started_at + drying_days, then one reading of
    ready_moisture. With defaults this lands the batch in CONDITIONED."""
    if batch is None:
        batch = create_wood_batch(species, initial_moisture)
    ensure_clock_at_least(iso_days_after(batch["drying_started_at"], drying_days))
    return record_moisture(batch["id"], ready_moisture)


# --- People (PRD section 3.3) ---

def create_craftsman(specialty: str, name=None) -> dict:
    resp = api_client.create_craftsman(
        create_craftsman_payload(name or f"Master {specialty}", specialty), WM
    )
    return get_success_data(resp)


def create_craftsman_set() -> dict:
    """One master craftsman per specialty, keyed by specialty name."""
    return {
        specialty: create_craftsman(specialty)
        for specialty in ("RIM_BENDING", "SEASONING_CHECK", "ACTION_REGULATION", "VOICING")
    }


def create_apprentice(name="Test Apprentice") -> dict:
    return get_success_data(api_client.create_apprentice(create_apprentice_payload(name), WM))


# --- Skill endorsements (PRD section 3.3) ---

def create_endorsement(apprentice_id: str, operation_type="RIM_BENDING") -> dict:
    resp = api_client.create_skill_endorsement(
        create_endorsement_payload(apprentice_id, operation_type), WM
    )
    return get_success_data(resp)


def get_endorsement(endorsement_id: str) -> dict:
    return get_success_data(api_client.get_skill_endorsement(endorsement_id, WM))


def log_supervised_hours(endorsement_id: str, apprentice_id: str, hours,
                         supervising_craftsman_id) -> dict:
    """Apprentice logs hours against their own track (ownership rule)."""
    resp = api_client.log_endorsement_hours(
        endorsement_id,
        log_hours_payload(hours, supervising_craftsman_id),
        make_apprentice_headers(apprentice_id),
    )
    return get_success_data(resp)


def assess_endorsement(endorsement_id: str, assessor: dict, outcome="ENDORSE") -> dict:
    resp = api_client.assess_endorsement(
        endorsement_id, assess_payload(outcome), make_master_craftsman_headers(assessor["id"])
    )
    return get_success_data(resp)


def review_endorsement(endorsement_id: str, action="REVOKE") -> dict:
    resp = api_client.review_endorsement(endorsement_id, review_endorsement_payload(action), WM)
    return get_success_data(resp)


def setup_endorsement(operation_type="RIM_BENDING", apprentice_name="Test Apprentice") -> dict:
    """Fresh apprentice + fresh IN_TRAINING track. Returns both."""
    apprentice = create_apprentice(apprentice_name)
    endorsement = create_endorsement(apprentice["id"], operation_type)
    return {"apprentice": apprentice, "endorsement": endorsement}


def setup_endorsement_with_entries(operation_type="RIM_BENDING",
                                   entries=((10, "RIM_BENDING"),)) -> dict:
    """Apprentice + track + one supervision entry per (hours, supervisor_specialty).

    entries: iterable of (hours, specialty) pairs; specialty None logs an
    explicit-null supervisor entry. One craftsman is created per distinct
    specialty used. Returns {"apprentice", "endorsement", "supervisors"} with
    supervisors keyed by specialty."""
    ctx = setup_endorsement(operation_type)
    supervisors = {}
    endorsement = ctx["endorsement"]
    for hours, specialty in entries:
        if specialty is not None and specialty not in supervisors:
            supervisors[specialty] = create_craftsman(specialty)
        supervisor_id = supervisors[specialty]["id"] if specialty is not None else None
        endorsement = log_supervised_hours(
            endorsement["id"], ctx["apprentice"]["id"], hours, supervisor_id
        )
    return {
        "apprentice": ctx["apprentice"],
        "endorsement": endorsement,
        "supervisors": supervisors,
    }


def setup_pending_endorsement(operation_type="RIM_BENDING", hours=None) -> dict:
    """Track auto-advanced to PENDING_ASSESSMENT via a single matched entry of
    exactly HOURS_REQUIRED[operation_type] hours (equality passes the bar)."""
    required = HOURS_REQUIRED[operation_type] if hours is None else hours
    ctx = setup_endorsement_with_entries(operation_type, ((required, operation_type),))
    return {
        "apprentice": ctx["apprentice"],
        "endorsement": ctx["endorsement"],
        "supervisor": ctx["supervisors"][operation_type],
    }


def setup_endorsed_track(operation_type="RIM_BENDING", hours=None) -> dict:
    """PENDING_ASSESSMENT track endorsed by a craftsman who is NOT the top
    supervisor (segregation of duties). Returns apprentice, endorsement,
    supervisor, assessor."""
    ctx = setup_pending_endorsement(operation_type, hours)
    assessor = create_craftsman("ACTION_REGULATION", name="Assessor")
    endorsement = assess_endorsement(ctx["endorsement"]["id"], assessor, "ENDORSE")
    return {
        "apprentice": ctx["apprentice"],
        "endorsement": endorsement,
        "supervisor": ctx["supervisor"],
        "assessor": assessor,
    }


# --- Build orders (PRD section 3.2) ---

STAGE_CHAIN = ["RIM_BENT", "SEASONING", "ACTION_REGULATION", "VOICING", "COMPLETED"]

# The operation each stage entry credits, which selects the actor gate.
STAGE_TO_OPERATION = {
    "RIM_BENT": "RIM_BENDING",
    "SEASONING": "SEASONING_CHECK",
    "ACTION_REGULATION": "SEASONING_CHECK",
    "VOICING": "ACTION_REGULATION",
    "COMPLETED": "VOICING",
}

DEFAULT_STAGE_HOURS = {
    "RIM_BENT": 120,
    "SEASONING": 40,
    "ACTION_REGULATION": 40,
    "VOICING": 200,
    "COMPLETED": 160,
}


def get_build_order(build_id: str) -> dict:
    return get_success_data(api_client.get_build_order(build_id, WM))


def create_build_order(model="MODEL_B", batch_id=None, commissioned_note=None) -> dict:
    resp = api_client.create_build_order(
        create_build_order_payload(model, batch_id, commissioned_note), WM
    )
    return get_success_data(resp)


def advance_build(build, to_stage, hours, headers, *, supervising_craftsman_id=None,
                  wood_batch_id=None) -> dict:
    """OCC-guarded advance; the expected version is read off the given build."""
    payload = advance_build_payload(
        to_stage,
        hours,
        build["version"],
        supervising_craftsman_id=supervising_craftsman_id,
        wood_batch_id=wood_batch_id,
    )
    resp = api_client.advance_build_order(build["id"], payload, headers)
    return get_success_data(resp)


def advance_build_by_master(build, to_stage, hours, craftsman: dict, **kwargs) -> dict:
    return advance_build(
        build, to_stage, hours, make_master_craftsman_headers(craftsman["id"]), **kwargs
    )


def advance_build_by_apprentice(build, to_stage, hours, apprentice: dict, **kwargs) -> dict:
    return advance_build(
        build, to_stage, hours, make_apprentice_headers(apprentice["id"]), **kwargs
    )


def setup_commissioned_build(model="MODEL_B", batch=None, commissioned_note=None,
                             craftsmen=None) -> dict:
    """CONDITIONED batch (created and conditioned unless supplied) plus a fresh
    COMMISSIONED build holding it. Returns {"build", "batch", "craftsmen"}."""
    if batch is None or batch.get("status") == "DRYING":
        batch = condition_wood_batch(batch)
    build = create_build_order(model, batch["id"], commissioned_note)
    return {"build": build, "batch": get_wood_batch(batch["id"]), "craftsmen": craftsmen}


def setup_build_in_stage(model="MODEL_B", target_stage="COMMISSIONED",
                         hours_per_stage=None, craftsmen=None, batch=None) -> dict:
    """Walk a build along the fixed chain to target_stage.

    Masters advance every stage (matching specialty per the actor gate); the
    seasoning gate is satisfied by moving the clock to seasoning_started_at +
    365 days before the ACTION_REGULATION advance. Returns
    {"build", "batch", "craftsmen"} with all entities freshly re-read."""
    hours_per_stage = {**DEFAULT_STAGE_HOURS, **(hours_per_stage or {})}
    if craftsmen is None:
        craftsmen = create_craftsman_set()
    ctx = setup_commissioned_build(model, batch, craftsmen=craftsmen)
    build, batch = ctx["build"], ctx["batch"]
    if target_stage != "COMMISSIONED":
        for stage in STAGE_CHAIN:
            if stage == "ACTION_REGULATION":
                ensure_clock_at_least(
                    iso_days_after(build["seasoning_started_at"], SEASONING_MIN_DAYS)
                )
            operation = STAGE_TO_OPERATION[stage]
            build = advance_build_by_master(
                build, stage, hours_per_stage[stage], craftsmen[operation]
            )
            if stage == target_stage:
                break
    return {"build": build, "batch": get_wood_batch(batch["id"]), "craftsmen": craftsmen}


# --- Instruments and the concert bank (PRD section 3.4) ---

def get_instrument(instrument_id: str) -> dict:
    return get_success_data(api_client.get_instrument(instrument_id, WM))


def list_instruments(params=None, headers=None) -> list:
    data, _meta = validate_paginated(api_client.list_instruments(headers or WM, params=params))
    return data


def find_instrument_for_build(build_id: str) -> dict:
    """The single instrument minted by a completed build."""
    rows = list_instruments({"build_order_id": build_id})
    assert len(rows) == 1, f"expected exactly one instrument for build {build_id}"
    return rows[0]


def bank_intake(instrument_id: str) -> dict:
    return get_success_data(api_client.bank_intake_instrument(instrument_id, {}, LIAISON))


def setup_completed_instrument(model="MODEL_B", hours_per_stage=None, craftsmen=None,
                               batch=None) -> dict:
    """Full build pipeline to COMPLETED. Returns {"instrument", "build",
    "batch", "craftsmen"} — the instrument starts SHOWROOM, grade A,
    certified_authentic true."""
    ctx = setup_build_in_stage(model, "COMPLETED", hours_per_stage, craftsmen, batch)
    instrument = find_instrument_for_build(ctx["build"]["id"])
    return {**ctx, "instrument": instrument}


def setup_bank_instrument(model="MODEL_B", hours_per_stage=None, craftsmen=None,
                          batch=None) -> dict:
    """Completed instrument admitted to the concert bank (status BANK)."""
    ctx = setup_completed_instrument(model, hours_per_stage, craftsmen, batch)
    instrument = bank_intake(ctx["instrument"]["id"])
    return {**ctx, "instrument": instrument}


# --- Artists (PRD section 3.5) ---

def create_artist(name="Test Artist", tier="STANDARD", performance_quota=2) -> dict:
    resp = api_client.create_artist(
        create_artist_payload(name, tier, performance_quota), LIAISON
    )
    return get_success_data(resp)


def get_artist(artist_id: str) -> dict:
    return get_success_data(api_client.get_artist(artist_id, LIAISON))


def log_performance(artist_id: str, venue="Test Hall", performed_at=CLOCK_START_ISO) -> dict:
    resp = api_client.log_artist_performance(
        artist_id, performance_payload(venue, performed_at), LIAISON
    )
    return get_success_data(resp)


def setup_artist_with_performances(count, name="Test Artist", tier="STANDARD",
                                   performance_quota=2, performed_at=CLOCK_START_ISO) -> dict:
    artist = create_artist(name, tier, performance_quota)
    for index in range(count):
        artist = log_performance(artist["id"], f"Venue {index + 1}", performed_at)
    return artist


def review_artist(artist_id: str) -> dict:
    return get_success_data(api_client.review_artist(artist_id, {}, LIAISON))


def setup_suspended_artist(performance_quota=3, name="Test Artist") -> dict:
    """Artist reviewed at their due date with zero logged performances, which
    suspends them (0 < quota). Returns the SUSPENDED artist."""
    artist = create_artist(name, "STANDARD", performance_quota)
    ensure_clock_at_least(artist["next_review_date"])
    return review_artist(artist["id"])


# --- Concert loans (PRD section 3.6) ---

def get_concert_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_concert_loan(loan_id, LIAISON))


def list_concert_loans(params=None, headers=None) -> list:
    data, _meta = validate_paginated(api_client.list_concert_loans(headers or LIAISON, params=params))
    return data


def create_loan(artist: dict, desired_model="MODEL_B", tour_start="2027-01-10T00:00:00Z",
                tour_end="2027-01-24T00:00:00Z") -> dict:
    """Artist requests a tour loan; artist_id binds to the caller's X-User-ID."""
    resp = api_client.create_concert_loan(
        create_loan_payload(desired_model, tour_start, tour_end),
        make_artist_headers(artist["id"]),
    )
    return get_success_data(resp)


def confirm_loan(loan_id: str, technician_id: str, instrument_id=None) -> dict:
    resp = api_client.confirm_concert_loan(
        loan_id, confirm_loan_payload(technician_id, instrument_id), LIAISON
    )
    return get_success_data(resp)


def return_loan(loan_id: str, condition_grade_observed="A") -> dict:
    resp = api_client.return_concert_loan(
        loan_id, return_loan_payload(condition_grade_observed), LIAISON
    )
    return get_success_data(resp)


def setup_on_tour_loan(model="MODEL_B", tour_start="2027-01-10T00:00:00Z",
                       tour_end="2027-01-24T00:00:00Z", artist=None, instrument_ctx=None,
                       technician=None) -> dict:
    """BANK instrument + ACTIVE artist + REQUESTED loan, confirmed ON_TOUR with
    an explicit instrument and a VOICING technician. Returns {"loan",
    "instrument", "artist", "technician"} plus the build context keys."""
    if instrument_ctx is None:
        instrument_ctx = setup_bank_instrument(model)
    if technician is None:
        technician = instrument_ctx["craftsmen"]["VOICING"]
    if artist is None:
        artist = create_artist()
    loan = create_loan(artist, model, tour_start, tour_end)
    loan = confirm_loan(loan["id"], technician["id"], instrument_ctx["instrument"]["id"])
    return {
        **instrument_ctx,
        "instrument": get_instrument(instrument_ctx["instrument"]["id"]),
        "artist": artist,
        "technician": technician,
        "loan": loan,
    }


# --- Restoration cases (PRD section 3.7) ---

def get_restoration(case_id: str) -> dict:
    return get_success_data(api_client.get_restoration(case_id, WM))


def list_restorations_for_instrument(instrument_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_restorations(WM, params={"instrument_id": instrument_id})
    )
    return data


def create_restoration_case(instrument_id: str, lead_craftsman_id: str,
                            diagnosis="Restoration work", authentic_parts_value_cents=0,
                            total_parts_value_cents=0, waiver_accepted=None) -> dict:
    resp = api_client.create_restoration(
        create_restoration_payload(
            instrument_id, lead_craftsman_id, diagnosis,
            authentic_parts_value_cents, total_parts_value_cents, waiver_accepted,
        ),
        WM,
    )
    return get_success_data(resp)


def advance_restoration_case(case: dict, to_stage: str, craftsman: dict,
                             authenticity_concern=None) -> dict:
    resp = api_client.advance_restoration(
        case["id"],
        advance_restoration_payload(to_stage, authenticity_concern),
        make_master_craftsman_headers(craftsman["id"]),
    )
    return get_success_data(resp)


def resolve_authenticity(case: dict, craftsman: dict, authentic_parts_value_cents,
                         total_parts_value_cents, waiver_accepted=None) -> dict:
    resp = api_client.resolve_restoration_authenticity(
        case["id"],
        resolve_authenticity_payload(
            authentic_parts_value_cents, total_parts_value_cents, waiver_accepted
        ),
        make_master_craftsman_headers(craftsman["id"]),
    )
    return get_success_data(resp)


def complete_restoration_case(case: dict, craftsman: dict, final_authentic_value_cents,
                              final_total_parts_value_cents) -> dict:
    resp = api_client.complete_restoration(
        case["id"],
        complete_restoration_payload(final_authentic_value_cents, final_total_parts_value_cents),
        make_master_craftsman_headers(craftsman["id"]),
    )
    return get_success_data(resp)


def setup_rebuilt_case(authentic_parts_value_cents=45000, total_parts_value_cents=50000,
                       waiver_accepted=None, instrument_ctx=None, lead=None) -> dict:
    """Restoration case walked QUOTED -> DISASSEMBLED -> REBUILT.

    The quote must keep the case out of AUTHENTICITY_HOLD at create (at/above
    the 70.0 threshold, zero total, or an accepted waiver). Returns
    {"case", "instrument", "lead"} plus the build context keys."""
    if instrument_ctx is None:
        instrument_ctx = setup_completed_instrument("MODEL_O")
    if lead is None:
        lead = instrument_ctx["craftsmen"]["ACTION_REGULATION"]
    case = create_restoration_case(
        instrument_ctx["instrument"]["id"], lead["id"], "Restoration work",
        authentic_parts_value_cents, total_parts_value_cents, waiver_accepted,
    )
    case = advance_restoration_case(case, "DISASSEMBLED", lead)
    case = advance_restoration_case(case, "REBUILT", lead)
    return {
        **instrument_ctx,
        "instrument": get_instrument(instrument_ctx["instrument"]["id"]),
        "lead": lead,
        "case": case,
    }
