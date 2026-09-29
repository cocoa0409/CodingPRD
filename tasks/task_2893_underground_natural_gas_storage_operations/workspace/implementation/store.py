"""In-memory data store (plain dicts keyed by id) and the server's logical clock.

Nothing is seeded here: every record is created by an API caller.
"""
from datetime import timedelta

import config
from utils import UTC, iso, new_uuid, parse_instant

# ---------------------------------------------------------------- collections
storage_fields = {}
wells = {}
mits = {}
remediation_programs = {}
compressor_units = {}
compressor_runs = {}
shippers = {}
contracts = {}
nominations = {}
tickets = {}
ledger_entries = {}
emergency_events = {}
reports = {}

COLLECTIONS = {
    "StorageField": storage_fields,
    "Well": wells,
    "MechanicalIntegrityTest": mits,
    "RemediationProgram": remediation_programs,
    "CompressorUnit": compressor_units,
    "CompressorRun": compressor_runs,
    "Shipper": shippers,
    "StorageContract": contracts,
    "Nomination": nominations,
    "GasMovementTicket": tickets,
    "ImbalanceLedgerEntry": ledger_entries,
    "EmergencyEvent": emergency_events,
    "RegulatoryReport": reports,
}

# ---------------------------------------------------------------- logical clock
_clock = parse_instant(config.CLOCK_EPOCH_ISO)
_seq = 0


def now():
    """The current logical clock instant (never wall-clock time)."""
    return _clock


def set_clock(instant):
    global _clock
    _clock = instant
    return _clock


def today():
    """UTC calendar date of the current logical clock."""
    return _clock.date()


def next_seq():
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------- record helpers
def new_record(with_common=True):
    """Mint a record carrying the common properties of PRD 2.4."""
    record = {"id": new_uuid(), "_seq": next_seq(), "created_at": now()}
    if with_common:
        record["updated_at"] = now()
        record["version"] = 1
    return record


def touch(record):
    """A mutation: refresh updated_at and increment version (PRD 2.4, 2.12)."""
    if record is None:
        return record
    record["updated_at"] = now()
    record["version"] = record.get("version", 1) + 1
    return record


def sorted_rows(rows):
    """created_at ascending; the insertion sequence breaks any identical instant."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def get(collection_name, record_id):
    return COLLECTIONS[collection_name].get(record_id)


def put(collection_name, record):
    COLLECTIONS[collection_name][record["id"]] = record
    return record


def values(collection_name):
    return list(COLLECTIONS[collection_name].values())


# ---------------------------------------------------------------- lookup helpers
def wells_of_field(field_id):
    return [w for w in wells.values() if w["storage_field_id"] == field_id]


def mits_of_well(well_id):
    return [m for m in mits.values() if m["well_id"] == well_id]


def programs_of_well(well_id):
    return [p for p in remediation_programs.values() if p["well_id"] == well_id]


def programs_of_field(field_id):
    out = []
    for program in remediation_programs.values():
        well = wells.get(program["well_id"])
        if well is not None and well["storage_field_id"] == field_id:
            out.append(program)
    return out


def units_of_field(field_id):
    return [u for u in compressor_units.values() if u["storage_field_id"] == field_id]


def runs_of_unit(unit_id):
    return [r for r in compressor_runs.values() if r["compressor_unit_id"] == unit_id]


def runs_of_field(field_id):
    unit_ids = {u["id"] for u in units_of_field(field_id)}
    return [r for r in compressor_runs.values() if r["compressor_unit_id"] in unit_ids]


def events_of_field(field_id):
    return [e for e in emergency_events.values() if e["storage_field_id"] == field_id]


def contracts_of_shipper(shipper_id):
    return [c for c in contracts.values() if c["shipper_id"] == shipper_id]


def contracts_of_field(field_id):
    return [c for c in contracts.values() if c["storage_field_id"] == field_id]


def nominations_of_contract(contract_id):
    return [n for n in nominations.values() if n["contract_id"] == contract_id]


def nominations_of_field(field_id):
    field_contracts = {c["id"] for c in contracts_of_field(field_id)}
    return [n for n in nominations.values() if n["contract_id"] in field_contracts]


def tickets_of_nomination(nomination_id):
    return [t for t in tickets.values() if t["nomination_id"] == nomination_id]


def tickets_of_well(well_id):
    return [t for t in tickets.values() if t["well_id"] == well_id]


def ledger_of_contract(contract_id):
    return [e for e in ledger_entries.values() if e["contract_id"] == contract_id]


def reports_of_field(field_id):
    return [r for r in reports.values() if r["storage_field_id"] == field_id]


def has_confirmed_ticket(nomination_id):
    return any(t["status"] == "CONFIRMED" for t in tickets_of_nomination(nomination_id))


def nomination_cutoff(gas_day):
    """13:00:00Z on the day immediately before the gas day (PRD 2.11 rung 18)."""
    previous = gas_day - timedelta(days=1)
    return parse_instant(
        "%sT%02d:00:00Z" % (previous.isoformat(), config.NOMINATION_CUTOFF_HOUR_UTC)
    )


def reset():
    """Used only by tests of this module; the process starts empty anyway."""
    global _clock, _seq
    for collection in COLLECTIONS.values():
        collection.clear()
    _clock = parse_instant(config.CLOCK_EPOCH_ISO)
    _seq = 0
