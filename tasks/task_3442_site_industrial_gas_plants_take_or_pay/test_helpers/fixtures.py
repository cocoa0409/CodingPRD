"""Composite setup helpers — canonical import surface.

The implementation is split into focused private submodules; this module
re-exports every public helper so tests import from one place:

- fixtures_contracts:   clock, customers, evaluations, contracts, networks,
                        connections, plants, the standard onsite scenario.
- fixtures_logistics:   tanks, telemetry, deliveries, quality certificates.
- fixtures_turnarounds: turnaround negotiation ladder, settlement runs.

Fixture tiers (per the test-generator spec):
- Tier 1 state progression: advance_plant_to_operating, activate_contract,
  create_agreed_turnaround / create_scheduled_turnaround /
  create_in_progress_turnaround.
- Tier 2 entity hierarchy: create_customer_with_evaluation,
  create_accepted_evaluation, create_draft_contract.
- Tier 3 lifecycle shortcuts: create_active_contract, create_operating_plant,
  create_delivered_delivery, create_certified_delivery.
- Tier 4 threshold targeting: create_tank_with_readings /
  create_tank_with_telemetry_delivery (exact reorder/safety boundaries),
  run_final_settlement (bank balance accumulation), setup_standard_onsite_scenario
  with contract_overrides (min volume, fee, escalation, cap targeting).
- Tier 5 terminal states: create_certified_delivery (COMPLETED/CERTIFIED),
  terminate via api.terminate_contract after setup_standard_onsite_scenario,
  clock-driven EXPIRED / COMPLETED via set_logical_clock.
"""
from .fixtures_contracts import *
from .fixtures_contracts import __all__ as _contracts_all
from .fixtures_logistics import *
from .fixtures_logistics import __all__ as _logistics_all
from .fixtures_turnarounds import *
from .fixtures_turnarounds import __all__ as _turnarounds_all

__all__ = list(_contracts_all) + list(_logistics_all) + list(_turnarounds_all)
