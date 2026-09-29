"""In-memory data store. Every byte of state lives in these dicts and vanishes
when the process exits. No seeding, no preloading, no persistence."""
from common import ApiError, new_id, now, iso3, num

# collection name -> {id: row}
country_profiles = {}
providers = {}
engagements = {}
cycles = {}
input_files = {}
gtn_runs = {}
bank_accounts = {}
funding_instructions = {}
filings = {}
incidents = {}
evidence_items = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_row(extra=None, common=True):
    row = {"id": new_id()}
    if extra:
        row.update(extra)
    stamp = now()
    row["created_at"] = stamp
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Record a mutation: refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = now()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def ordered(rows):
    """Default ordering: created_at ascending, stable by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def _fetch(collection, ident, error_id):
    if not isinstance(ident, str) or ident not in collection:
        raise ApiError(error_id, "Referenced resource does not exist.")
    return collection[ident]


def get_country(ident):
    return _fetch(country_profiles, ident, "ERR_COUNTRY_PROFILE_NOT_FOUND")


def get_provider(ident):
    return _fetch(providers, ident, "ERR_PROVIDER_NOT_FOUND")


def get_engagement(ident):
    return _fetch(engagements, ident, "ERR_ENGAGEMENT_NOT_FOUND")


def get_cycle(ident):
    return _fetch(cycles, ident, "ERR_CYCLE_NOT_FOUND")


def get_input_file(ident):
    return _fetch(input_files, ident, "ERR_INPUT_FILE_NOT_FOUND")


def get_run(ident):
    return _fetch(gtn_runs, ident, "ERR_GTN_RUN_NOT_FOUND")


def get_bank_account(ident):
    return _fetch(bank_accounts, ident, "ERR_BANK_ACCOUNT_NOT_FOUND")


def get_funding(ident):
    return _fetch(funding_instructions, ident, "ERR_FUNDING_INSTRUCTION_NOT_FOUND")


def get_filing(ident):
    return _fetch(filings, ident, "ERR_FILING_NOT_FOUND")


def get_incident(ident):
    return _fetch(incidents, ident, "ERR_SLA_INCIDENT_NOT_FOUND")


# ---------------------------------------------------------------------------
# Relationship helpers
# ---------------------------------------------------------------------------
def engagement_of_cycle(cycle):
    return engagements[cycle["engagement_id"]]


def country_of_engagement(engagement):
    return country_profiles[engagement["country_profile_id"]]


def provider_of_engagement(engagement):
    return providers[engagement["provider_id"]]


def cycles_of_engagement(engagement_id):
    return ordered([c for c in cycles.values() if c["engagement_id"] == engagement_id])


def engagements_of_provider(provider_id):
    return ordered([e for e in engagements.values() if e["provider_id"] == provider_id])


def input_files_of_cycle(cycle_id):
    return ordered([f for f in input_files.values() if f["cycle_id"] == cycle_id])


def runs_of_cycle(cycle_id):
    return ordered([r for r in gtn_runs.values() if r["cycle_id"] == cycle_id])


def filings_of_cycle(cycle_id):
    return ordered([f for f in filings.values() if f["cycle_id"] == cycle_id])


def funding_of_cycle(cycle_id):
    return ordered(
        [f for f in funding_instructions.values() if f["cycle_id"] == cycle_id]
    )


def evidence_of_cycle(cycle_id):
    return sorted(
        [e for e in evidence_items.values() if e["cycle_id"] == cycle_id],
        key=lambda r: r["sequence_no"],
    )


def incidents_of_engagement(engagement_id):
    return ordered([i for i in incidents.values() if i["engagement_id"] == engagement_id])


def approved_run_of_cycle(cycle_id):
    for run in ordered(runs_of_cycle(cycle_id)):
        if run["status"] == "APPROVED":
            return run
    return None
