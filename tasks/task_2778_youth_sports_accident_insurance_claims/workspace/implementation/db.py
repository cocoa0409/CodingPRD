"""In-memory data store. Starts empty on every boot; nothing is ever seeded."""

import constants
import util

STORE_NAMES = (
    "leagues",
    "sport_classifications",
    "league_policies",
    "participants",
    "enrollments",
    "family_health_plans",
    "sanctioned_activities",
    "injury_reports",
    "claims",
    "provider_bills",
    "coordination_records",
    "benefit_payments",
)

# id -> row (plain dicts, keyed by id)
stores = {name: {} for name in STORE_NAMES}

_state = {
    "clock": util.parse_datetime(constants.LOGICAL_CLOCK_DEFAULT_UTC),
    "seq": 0,
}


def reset():
    for name in STORE_NAMES:
        stores[name] = {}
    _state["clock"] = util.parse_datetime(constants.LOGICAL_CLOCK_DEFAULT_UTC)
    _state["seq"] = 0


# --------------------------------------------------------------- logical clock

def now():
    return _state["clock"]


def now_iso():
    return util.format_datetime(_state["clock"])


def today():
    return _state["clock"].date()


def set_clock(dt):
    _state["clock"] = dt


# ------------------------------------------------------------------- sequence

def next_seq():
    _state["seq"] += 1
    return _state["seq"]


# ------------------------------------------------------------------- row helpers

def insert(store_name, row):
    row["_store"] = store_name
    row["_seq"] = next_seq()
    stores[store_name][row["id"]] = row
    return row


def get(store_name, row_id):
    if not isinstance(row_id, str):
        return None
    return stores[store_name].get(row_id)


def all_rows(store_name):
    """Every row in insertion order."""
    return sorted(stores[store_name].values(), key=lambda r: (r["created_at"], r["_seq"]))


def new_row(store_name, fields):
    stamp = now_iso()
    row = {"id": util.new_uuid(), "created_at": stamp, "updated_at": stamp, "version": 1}
    row.update(fields)
    return insert(store_name, row)


# ----------------------------------------------------------------- convenience

def policies_of_league(league_id):
    return [p for p in all_rows("league_policies") if p["league_id"] == league_id]


def enrollments_of_policy(policy_id):
    return [e for e in all_rows("enrollments") if e["league_policy_id"] == policy_id]


def claims_of_policy(policy_id):
    return [c for c in all_rows("claims") if c["league_policy_id"] == policy_id]


def claims_of_enrollment(enrollment_id):
    return [c for c in all_rows("claims") if c["enrollment_id"] == enrollment_id]


def bills_of_claim(claim_id):
    return [b for b in all_rows("provider_bills") if b["claim_id"] == claim_id]


def payments_of_claim(claim_id):
    return [p for p in all_rows("benefit_payments") if p["claim_id"] == claim_id]


def coordination_records_of_claim(claim_id):
    return [r for r in all_rows("coordination_records") if r["claim_id"] == claim_id]


def activities_of_policy(policy_id):
    return [a for a in all_rows("sanctioned_activities") if a["league_policy_id"] == policy_id]


def plans_of_participant(participant_id):
    return [p for p in all_rows("family_health_plans") if p["participant_id"] == participant_id]
