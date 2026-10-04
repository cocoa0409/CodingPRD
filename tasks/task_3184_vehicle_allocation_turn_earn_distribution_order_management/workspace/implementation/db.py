"""In-memory data store. The store starts empty on every boot — no seeding."""

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

STORES = {
    "regions": {},
    "dealers": {},
    "model_lines": {},
    "commodities": {},
    "commodity_restrictions": {},
    "allocation_runs": {},
    "dealer_allocations": {},
    "dealer_model_lines": {},
    "vehicle_orders": {},
    "dealer_trades": {},
    "appeals": {},
    "incentive_programs": {},
    "carriers": {},
    "shipments": {},
}

# Logical clock, separate from wall-clock time (PRD §2.9). Never falls back
# to wall-clock: default is exactly CLOCK_DEFAULT until set.
_clock = {"current_utc": CLOCK_DEFAULT}


def now_iso() -> str:
    return _clock["current_utc"]


def set_clock(to_iso8601: str) -> None:
    _clock["current_utc"] = to_iso8601


def get_store(name: str) -> dict:
    return STORES[name]
