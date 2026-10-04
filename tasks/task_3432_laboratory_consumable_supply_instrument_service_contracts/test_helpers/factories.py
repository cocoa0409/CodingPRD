"""Request-payload builders - one per creatable resource, input fields only.

Each builder returns a dict satisfying every declared constraint of the
operation it names, and accepts ``**overrides`` so a test can perturb one
field without restating the rest; overrides are applied by ``update`` after
the defaults are assembled, so no field is ever passed twice.

Conventions applied everywhere:

* money travels as JSON integer cents, never fractional and never strings;
* every instant field carries a full ISO 8601 UTC timestamp, never a bare
  date;
* sku and serial values are counter-stamped so two payloads built inside
  one test never collide on a uniqueness constraint.
"""

import itertools

from .constants import (
    CLOCK_START_UTC,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)

_SKU_COUNTER = itertools.count(1)
_SERIAL_COUNTER = itertools.count(1)
_NAME_COUNTER = itertools.count(1)


def _next(counter, prefix):
    return "{0}-{1}".format(prefix, next(counter))


# --- Account (PRD section 3.1) ---------------------------------------------------
def account_payload(**overrides):
    """Required: name, segment, territory_code.  Optional flags default per PRD."""
    defaults = {
        "name": _next(_NAME_COUNTER, "Lab"),
        "segment": "PHARMA",
        "priority_class": "STANDARD",
        "territory_code": "CA-NORTH",
        "controlled_substance_license": False,
    }
    defaults.update(overrides)
    return defaults


# --- EnterpriseAgreement (PRD section 3.2) -----------------------------------------
def enterprise_agreement_payload(account_id, **overrides):
    """Default window is the standard fixture window: clock start + 12 months."""
    defaults = {
        "account_id": account_id,
        "start_date": DEFAULT_WINDOW_START,
        "end_date": DEFAULT_WINDOW_END,
        "committed_annual_spend_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


# --- Instrument (PRD section 3.3) -----------------------------------------------------
def instrument_payload(account_id, **overrides):
    """Defaults to a CAPITAL placement with commitment 0 (the only legal CAPITAL
    commitment); pass placement_type REAGENT_RENTAL/LEASE together with a
    positive monthly_consumable_commitment_cents."""
    defaults = {
        "account_id": account_id,
        "model": "SEQ-5000",
        "serial_number": _next(_SERIAL_COUNTER, "SN"),
        "placement_type": "CAPITAL",
        "monthly_consumable_commitment_cents": 0,
        "monthly_baseline_consumable_cents": 0,
    }
    defaults.update(overrides)
    return defaults


# --- ServiceContract (PRD section 3.4) --------------------------------------------------
def service_contract_payload(instrument_id, **overrides):
    defaults = {
        "instrument_id": instrument_id,
        "tier": "GOLD",
        "start_date": DEFAULT_WINDOW_START,
        "end_date": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def contract_renew_payload(expected_contract_version):
    return {"expected_contract_version": expected_contract_version}


def agreement_renew_payload(expected_agreement_version):
    return {"expected_agreement_version": expected_agreement_version}


# --- Engineer / LoanerUnit (PRD section 3.5) ----------------------------------------------
def engineer_payload(**overrides):
    """Defaults to an ACTIVE installer in CA-NORTH; pass skills to retarget."""
    defaults = {
        "name": _next(_NAME_COUNTER, "Engineer"),
        "territory_code": "CA-NORTH",
        "skills": ["INSTALL"],
        "status": "ACTIVE",
    }
    defaults.update(overrides)
    return defaults


def loaner_unit_payload(**overrides):
    defaults = {
        "model": "SEQ-5000",
        "serial_number": _next(_SERIAL_COUNTER, "LN"),
    }
    defaults.update(overrides)
    return defaults


# --- ServiceRequest (PRD section 3.5) ---------------------------------------------------
def service_request_payload(instrument_id, **overrides):
    """Defaults to a LOW BREAK_FIX.  For PREVENTIVE_MAINTENANCE pass
    scheduled_for - the PRD requires it for that type only."""
    defaults = {
        "instrument_id": instrument_id,
        "request_type": "BREAK_FIX",
        "severity": "LOW",
    }
    defaults.update(overrides)
    return defaults


def resolve_payload(hours_on_site, **overrides):
    """parts_cost_cents defaults to 0 per PRD section 3.5."""
    defaults = {
        "hours_on_site": hours_on_site,
        "parts_cost_cents": 0,
    }
    defaults.update(overrides)
    return defaults


# --- CatalogItem (PRD section 3.6) ---------------------------------------------------------
def catalog_item_payload(**overrides):
    defaults = {
        "sku": _next(_SKU_COUNTER, "SKU"),
        "name": _next(_NAME_COUNTER, "Item"),
        "item_class": "STANDARD",
        "allocation_group": "GROUP_B",
        "base_price_cents": 1000,
        "stock_on_hand": 100,
    }
    defaults.update(overrides)
    return defaults


# --- Order (PRD section 3.6) ------------------------------------------------------------------
def order_line(sku, quantity):
    return {"sku": sku, "quantity": quantity}


def order_payload(account_id, lines=None, **overrides):
    """lines is a non-empty array of {"sku", "quantity"}; pass explicit lines or
    let the caller compose them with order_line()."""
    defaults = {"account_id": account_id}
    if lines is not None:
        defaults["lines"] = lines
    defaults.update(overrides)
    return defaults


# --- SurgeEvent (PRD section 3.7) ----------------------------------------------------------------
def surge_event_payload(**overrides):
    defaults = {
        "allocation_group": "GROUP_A",
        "reason": _next(_NAME_COUNTER, "surge"),
    }
    defaults.update(overrides)
    return defaults


# --- Logical clock (PRD section 2.4) ------------------------------------------------------------------
def clock_payload(to_iso8601=CLOCK_START_UTC):
    return {"to_iso8601": to_iso8601}
