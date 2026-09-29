"""The summer reading challenge: ladder, enrolment, ledger and prize awards."""

from flask import Blueprint, request

import calc
import derive
import lookup
import revision
import services
import store
import validate
from core import clock
from errors import ApiError
from web import Arr, Obj, endpoint

bp = Blueprint("challenges", __name__)

MANAGER = ("ProgramManager",)
STAFF = ("ProgramManager", "ProgramCoordinator")
STAFF_AND_READER = ("ProgramManager", "ProgramCoordinator", "Reader")

LOGGING_METHODS = ("MINUTES", "BOOKS", "ACTIVITIES")
CORRECTION_POLICIES = ("HIGH_WATER", "LEDGER_TRUTH")
AGE_BANDS = ("UNDER_5", "AGE_5_11", "AGE_12_17", "ADULT")
LOG_SOURCES = ("SELF_SERVICE", "STAFF_DESK", "OUTREACH_SITE")
ENTRY_TYPES = ("LOG", "CORRECTION")


# ------------------------------------------------------------- challenges

@bp.route("/library/reading-challenges/<challenge_id>", methods=["GET"])
@endpoint(STAFF)
def get_challenge(user_id, role, challenge_id):
    return Obj("challenges", lookup.challenge(challenge_id))


@bp.route("/library/reading-challenges", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def create_challenge(user_id, role):
    payload = validate.body()
    name = validate.string_field(payload, "name")
    logging_method = validate.enum_field(payload, "logging_method", LOGGING_METHODS)
    unit_label = validate.string_field(payload, "unit_label")
    start_on = validate.date_field(payload, "start_on")
    end_on = validate.date_field(payload, "end_on")
    policy = validate.enum_field(payload, "correction_policy", CORRECTION_POLICIES)
    budget = validate.integer_field(payload, "prize_budget_cents", minimum=0)
    if end_on < start_on:
        raise ApiError("ERR_INVALID_REQUEST", "end_on must not precede start_on.")

    challenge = store.new_entity(
        "challenges",
        {
            "name": name,
            "logging_method": logging_method,
            "unit_label": unit_label,
            "start_on": start_on,
            "end_on": end_on,
            "correction_policy": policy,
            "prize_budget_cents": budget,
            "status": "PLANNING",
        },
    )
    return Obj("challenges", challenge, 201)


@bp.route("/library/reading-challenges/<challenge_id>/open", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def open_challenge(user_id, role, challenge_id):
    challenge = lookup.challenge(challenge_id)
    if challenge["status"] != "PLANNING":
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    if not derive.challenge_tiers(challenge["id"]):
        raise ApiError("ERR_CHALLENGE_HAS_NO_TIERS")
    challenge["status"] = "OPEN"
    revision.mark(challenge)
    return Obj("challenges", challenge)


@bp.route("/library/reading-challenges/<challenge_id>/reconcile", methods=["POST"])
@endpoint(MANAGER, mutating=True)
def reconcile_challenge(user_id, role, challenge_id):
    challenge = lookup.challenge(challenge_id)
    if challenge["status"] != "OPEN":
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    if clock.today() <= challenge["end_on"]:
        raise ApiError("ERR_CHALLENGE_WINDOW_STILL_OPEN")

    for award in derive.challenge_awards(challenge["id"]):
        if award["status"] == "RESERVED":
            lot = store.get("lots", award["lot_id"])
            if lot is not None:
                services.issue_reserved_units(lot, award["units"])
            award["status"] = "ISSUED"
            revision.mark(award)
        elif award["status"] == "DEFERRED":
            award["status"] = "FORFEITED"
            revision.mark(award)

    challenge["status"] = "RECONCILED"
    revision.mark(challenge)
    return Obj("challenges", challenge)


# ----------------------------------------------------------- incentive tiers

@bp.route("/library/incentive-tiers/<tier_id>", methods=["GET"])
@endpoint(STAFF)
def get_tier(user_id, role, tier_id):
    return Obj("tiers", lookup.tier(tier_id))


@bp.route("/library/incentive-tiers", methods=["GET"])
@endpoint(STAFF)
def list_tiers(user_id, role):
    tiers = store.all_of("tiers")
    challenge_id = request.args.get("challenge_id")
    if challenge_id is not None:
        tiers = [t for t in tiers if t["challenge_id"] == challenge_id]
    tiers = sorted(tiers, key=lambda t: t["tier_index"])
    return Arr("tiers", tiers)


@bp.route(
    "/library/reading-challenges/<challenge_id>/incentive-tiers", methods=["POST"]
)
@endpoint(MANAGER, mutating=True)
def append_tier(user_id, role, challenge_id):
    payload = validate.body()
    tier_index = validate.integer_field(payload, "tier_index", minimum=1)
    threshold = validate.integer_field(payload, "threshold_units", minimum=1)
    prize_sku = validate.string_field(payload, "prize_sku")
    units = validate.integer_field(
        payload, "prize_units_per_participant", minimum=1
    )
    challenge = lookup.challenge(challenge_id)

    if challenge["status"] != "PLANNING":
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")

    existing = derive.challenge_tiers(challenge["id"])
    highest_index = max([t["tier_index"] for t in existing]) if existing else 0
    if tier_index != highest_index + 1:
        raise ApiError("ERR_TIER_SEQUENCE_INVALID")
    if existing:
        previous = max(existing, key=lambda t: t["tier_index"])
        if threshold <= previous["threshold_units"]:
            raise ApiError("ERR_TIER_SEQUENCE_INVALID")

    tier = store.new_entity(
        "tiers",
        {
            "challenge_id": challenge["id"],
            "tier_index": tier_index,
            "threshold_units": threshold,
            "prize_sku": prize_sku,
            "prize_units_per_participant": units,
        },
    )
    return Obj("tiers", tier, 201)


# ------------------------------------------------------------- participants

@bp.route("/library/participants/<participant_id>", methods=["GET"])
@endpoint(STAFF_AND_READER)
def get_participant(user_id, role, participant_id):
    participant = lookup.participant(participant_id)
    if role == "Reader" and user_id != participant["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return Obj("participants", participant)


@bp.route("/library/participants", methods=["GET"])
@endpoint(STAFF)
def list_participants(user_id, role):
    participants = store.all_of("participants")
    for field in ("challenge_id", "home_branch_id"):
        value = request.args.get(field)
        if value is not None:
            participants = [p for p in participants if p[field] == value]
    return Arr("participants", participants)


@bp.route("/library/participants", methods=["POST"])
@endpoint(STAFF, mutating=True)
def enrol_participant(user_id, role):
    payload = validate.body()
    challenge_id = validate.string_field(payload, "challenge_id")
    home_branch_id = validate.string_field(payload, "home_branch_id")
    display_name = validate.string_field(payload, "display_name")
    age_band = validate.enum_field(payload, "age_band", AGE_BANDS)

    # step 6: body foreign keys, in field-declaration order
    challenge = lookup.challenge(challenge_id)
    branch = lookup.branch(home_branch_id)

    # step 14
    if challenge["status"] not in ("PLANNING", "OPEN"):
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")

    participant = store.new_entity(
        "participants",
        {
            "challenge_id": challenge["id"],
            "home_branch_id": branch["id"],
            "display_name": display_name,
            "age_band": age_band,
        },
    )
    revision.mark(challenge)
    return Obj("participants", participant, 201)


# ------------------------------------------------------------- reading ledger

@bp.route("/library/log-entries/<entry_id>", methods=["GET"])
@endpoint(STAFF)
def get_entry(user_id, role, entry_id):
    return Obj("entries", lookup.entry(entry_id))


@bp.route("/library/log-entries", methods=["GET"])
@endpoint(STAFF)
def list_entries(user_id, role):
    entries = store.all_of("entries")
    for field in ("participant_id", "entry_type", "corrected_entry_id"):
        value = request.args.get(field)
        if value is not None:
            entries = [e for e in entries if e[field] == value]
    return Arr("entries", entries)


@bp.route(
    "/library/participants/<participant_id>/log-entries", methods=["POST"]
)
@endpoint(STAFF_AND_READER, mutating=True)
def post_log_entry(user_id, role, participant_id):
    payload = validate.body()
    units = validate.integer_field(payload, "units", minimum=1)
    logged_on = validate.date_field(payload, "logged_on")
    source = validate.enum_field(payload, "source", LOG_SOURCES)

    participant = lookup.participant(participant_id)
    if role == "Reader" and user_id != participant["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    challenge = store.get("challenges", participant["challenge_id"])
    # step 14
    if challenge is None or challenge["status"] != "OPEN":
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    # step 35
    if role == "Reader" and source != "SELF_SERVICE":
        raise ApiError("ERR_LOG_SOURCE_NOT_PERMITTED")
    # step 36
    if logged_on < challenge["start_on"] or logged_on > challenge["end_on"]:
        raise ApiError("ERR_LOG_DATE_OUTSIDE_WINDOW")
    # step 37
    if logged_on > clock.today():
        raise ApiError("ERR_LOG_DATE_IN_FUTURE")
    # step 38
    cap = calc.DAILY_CAPS[challenge["logging_method"]]
    if derive.net_units_on_date(participant["id"], logged_on) + units > cap:
        raise ApiError("ERR_DAILY_LOG_CAP_EXCEEDED")

    entry = store.new_entity(
        "entries",
        {
            "participant_id": participant["id"],
            "entry_type": "LOG",
            "units": units,
            "units_delta": 0,
            "logged_on": logged_on,
            "source": source,
            "corrected_entry_id": None,
            "note": None,
            "recorded_by_user_id": user_id,
        },
        versioned=False,
    )

    # CASCADE-C: awards for every newly reached tier
    services.grant_awards_for_progress(participant)
    revision.mark(participant)
    return Obj("entries", entry, 201)


@bp.route(
    "/library/participants/<participant_id>/log-corrections", methods=["POST"]
)
@endpoint(STAFF, mutating=True)
def post_log_correction(user_id, role, participant_id):
    payload = validate.body()
    corrected_entry_id = validate.string_field(payload, "corrected_entry_id")
    units_delta = validate.integer_field(payload, "units_delta")
    expected_version = validate.integer_field(
        payload, "expected_participant_version"
    )
    note = validate.string_field(payload, "note", required=False)

    participant = lookup.participant(participant_id)
    # step 6: the only body foreign key on this write
    target = lookup.entry(corrected_entry_id)

    # step 10: the stale echo outranks every payload rule below
    if expected_version != participant["version"]:
        raise ApiError("ERR_STALE_PARTICIPANT_VERSION")

    challenge = store.get("challenges", participant["challenge_id"])
    # step 14
    if challenge is None or challenge["status"] != "OPEN":
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")

    # step 39
    if (
        target["entry_type"] != "LOG"
        or target["participant_id"] != participant["id"]
        or target["id"] in derive.superseded_entry_ids(participant["id"])
    ):
        raise ApiError("ERR_CORRECTION_TARGET_INVALID")

    # step 40
    if units_delta == 0 or int(target["units"]) + units_delta < 0:
        raise ApiError("ERR_CORRECTION_WOULD_GO_NEGATIVE")

    entry = store.new_entity(
        "entries",
        {
            "participant_id": participant["id"],
            "entry_type": "CORRECTION",
            "units": 0,
            "units_delta": units_delta,
            "logged_on": target["logged_on"],
            "source": None,
            "corrected_entry_id": target["id"],
            "note": note,
            "recorded_by_user_id": user_id,
        },
        versioned=False,
    )

    # CASCADE-D: LEDGER_TRUTH retracts awards, HIGH_WATER touches nothing
    if challenge["correction_policy"] == "LEDGER_TRUTH":
        services.revoke_awards_below(
            participant, derive.cumulative_units(participant["id"])
        )
    revision.mark(participant)
    return Obj("entries", entry, 201)


# --------------------------------------------------------------- tier awards

@bp.route("/library/tier-awards/<award_id>", methods=["GET"])
@endpoint(STAFF)
def get_award(user_id, role, award_id):
    return Obj("awards", lookup.award(award_id))


@bp.route("/library/tier-awards", methods=["GET"])
@endpoint(STAFF)
def list_awards(user_id, role):
    awards = store.all_of("awards")
    for field in ("participant_id", "tier_id", "lot_id", "status"):
        value = request.args.get(field)
        if value is not None:
            awards = [a for a in awards if a[field] == value]
    return Arr("awards", awards)
