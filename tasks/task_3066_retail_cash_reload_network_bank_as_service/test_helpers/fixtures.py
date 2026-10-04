"""Composite setup helpers — multi-step preconditions built from PRD endpoints only.

Every helper builds its preconditions from scratch (the harness restarts the
server before each test, so each test starts against an empty database).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CLOCK_NOON
from .factories import (
    create_bank_sponsor_payload,
    create_program_payload,
    create_brand_partner_payload,
    create_retailer_agreement_payload,
    create_reload_location_payload,
    create_card_account_payload,
    create_load_payload,
    create_aml_alert_payload,
    create_dispute_payload,
    create_loss_allocation_payload,
    create_settlement_batch_payload,
    create_float_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_bank_sponsor_headers,
    make_program_manager_headers,
    make_retailer_clerk_headers,
    make_analyst_headers,
    make_officer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["compliance_analyst_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SETTLEMENT = TEST_USERS["settlement_operator_headers"]


# ---------------------------------------------------------------------------
# Primitive create helpers
# ---------------------------------------------------------------------------

def set_clock(current_utc):
    return get_success_data(api.set_clock(current_utc, ADMIN))


def create_sponsor(**overrides):
    return get_success_data(
        api.create_bank_sponsor(create_bank_sponsor_payload(**overrides), ADMIN))


def create_program(sponsor_bank_id, **overrides):
    return get_success_data(
        api.create_program(create_program_payload(sponsor_bank_id, **overrides), ADMIN))


def create_brand(program, **overrides):
    payload = create_brand_partner_payload(program["id"], program["version"], **overrides)
    return get_success_data(api.create_brand_partner(payload, OFFICER))


def set_brand_state(brand_id, to_status):
    return api.set_brand_partner_state(brand_id, {"to_status": to_status}, OFFICER)


def activate_brand(brand):
    return get_success_data(set_brand_state(brand["id"], "ACTIVE"))


def create_agreement(program, **overrides):
    payload = create_retailer_agreement_payload(program["id"], **overrides)
    return get_success_data(
        api.create_retailer_agreement(payload, make_program_manager_headers(program["id"])))


def set_agreement_state(program_id, agreement_id, to_status):
    return api.set_retailer_agreement_state(
        agreement_id, {"to_status": to_status}, make_program_manager_headers(program_id))


def activate_agreement(program, agreement):
    return get_success_data(set_agreement_state(program["id"], agreement["id"], "ACTIVE"))


def create_location(program, agreement, **overrides):
    payload = create_reload_location_payload(agreement["id"], **overrides)
    return get_success_data(
        api.create_reload_location(payload, make_program_manager_headers(program["id"])))


def set_location_state(program_id, location_id, to_status):
    return api.set_reload_location_state(
        location_id, {"to_status": to_status}, make_program_manager_headers(program_id))


def create_account(program, brand, **overrides):
    payload = create_card_account_payload(program["id"], brand["id"], **overrides)
    return get_success_data(
        api.create_card_account(payload, make_program_manager_headers(program["id"])))


def get_account(account_id):
    return get_success_data(api.get_card_account(account_id, ADMIN))


def get_program(program_id):
    return get_success_data(api.get_program(program_id, ADMIN))


def get_load(load_id):
    return get_success_data(api.get_load(load_id, ADMIN))


def get_agreement(agreement_id):
    return get_success_data(api.get_retailer_agreement(agreement_id, ADMIN))


def get_location(location_id):
    return get_success_data(api.get_reload_location(location_id, ADMIN))


def get_brand_partner(brand_id):
    return get_success_data(api.get_brand_partner(brand_id, ADMIN))


def get_alert(alert_id):
    return get_success_data(api.get_aml_alert(alert_id, ADMIN))


def get_dispute(dispute_id):
    return get_success_data(api.get_dispute(dispute_id, ADMIN))


def get_allocation(allocation_id):
    return get_success_data(api.get_loss_allocation(allocation_id, ADMIN))


def get_batch(batch_id):
    return get_success_data(api.get_settlement_batch(batch_id, ADMIN))


def get_float_window(window_id):
    return get_success_data(api.get_float_window(window_id, ADMIN))


def get_sponsor(bank_id):
    return get_success_data(api.get_bank_sponsor(bank_id, ADMIN))


def move_program_posture(program_id, to_posture, bank_id):
    """Returns the raw response so callers can assert on success or on the error."""
    program = get_program(program_id)
    return api.set_program_state(
        program_id,
        {"to_posture": to_posture, "expected_program_version": program["version"]},
        make_bank_sponsor_headers(bank_id),
    )


def oversight_review(program_id, bank_id, review_note="quarterly review"):
    return api.oversight_review(program_id, {"review_note": review_note},
                                make_bank_sponsor_headers(bank_id))


# ---------------------------------------------------------------------------
# Load lifecycle
# ---------------------------------------------------------------------------

def create_load(location, account, agreement, principal_cents=3000, **overrides):
    account_version = get_account(account["id"])["version"]
    payload = create_load_payload(location["id"], account["id"], account_version,
                                  principal_cents=principal_cents, **overrides)
    return get_success_data(
        api.create_load(payload, make_retailer_clerk_headers(agreement["id"])))


def create_load_raw(location, account, agreement, principal_cents=3000, **overrides):
    """Raw response (for tests asserting a rejection on the create path)."""
    account_version = get_account(account["id"])["version"]
    payload = create_load_payload(location["id"], account["id"], account_version,
                                  principal_cents=principal_cents, **overrides)
    return api.create_load(payload, make_retailer_clerk_headers(agreement["id"]))


def fund_load(load_id, agreement_id):
    return get_success_data(
        api.fund_load(load_id, make_retailer_clerk_headers(agreement_id)))


def fund_load_raw(load_id, agreement_id):
    return api.fund_load(load_id, make_retailer_clerk_headers(agreement_id))


def create_and_fund_load(location, account, agreement, principal_cents=3000):
    load = create_load(location, account, agreement, principal_cents=principal_cents)
    return fund_load(load["id"], agreement["id"])


def fund_n_loads(location, account, agreement, principal_cents, n):
    """Fund `n` loads of the same principal. Returns the list of funded load dicts."""
    loads = []
    for _ in range(n):
        loads.append(create_and_fund_load(location, account, agreement, principal_cents))
    return loads


def decline_load(load_id, agreement_id, reason="customer left the register"):
    return get_success_data(
        api.decline_load(load_id, {"decline_reason": reason},
                         make_retailer_clerk_headers(agreement_id)))


def reverse_load(load_id, reason, headers=None):
    load = get_load(load_id)
    return api.reverse_load(
        load_id,
        {"reversal_reason": reason, "expected_load_transaction_version": load["version"]},
        headers or ANALYST,
    )


def reverse_load_ok(load_id, reason, headers=None):
    return get_success_data(reverse_load(load_id, reason, headers))


def reinstate_load(load_id, account_id):
    load = get_load(load_id)
    account = get_account(account_id)
    return api.reinstate_load(
        load_id,
        {"expected_card_account_version": account["version"],
         "expected_load_transaction_version": load["version"]},
        OFFICER,
    )


def reinstate_load_ok(load_id, account_id):
    return get_success_data(reinstate_load(load_id, account_id))


def setup_settled_load(network, principal_cents=12000, reason="DISPUTE_FAVOR_CARDHOLDER"):
    """A load funded -> reversed -> re-instated, so it is SETTLED and eligible
    for a loss allocation (PRD §3.4)."""
    load = create_and_fund_load(network["location"], network["account"],
                                network["agreement"], principal_cents=principal_cents)
    reverse_load_ok(load["id"], reason)
    reinstate_load_ok(load["id"], network["account"]["id"])
    return load


# ---------------------------------------------------------------------------
# AML alerts
# ---------------------------------------------------------------------------

def raise_alert(program, account, alert_type="VELOCITY"):
    payload = create_aml_alert_payload(program["id"], account["id"], alert_type=alert_type)
    return get_success_data(api.create_aml_alert(payload, ANALYST))


def raise_alert_raw(program, account, alert_type="VELOCITY"):
    payload = create_aml_alert_payload(program["id"], account["id"], alert_type=alert_type)
    return api.create_aml_alert(payload, ANALYST)


def review_alert(alert_id, note="reviewing the trip", headers=None):
    return get_success_data(
        api.review_aml_alert(alert_id, {"resolution_note": note}, headers or ANALYST))


def confirm_alert(alert_id, headers=None):
    return get_success_data(api.confirm_aml_alert(alert_id, headers or OFFICER))


def setup_alert_under_review(program, account, alert_type="VELOCITY"):
    alert = raise_alert(program, account, alert_type=alert_type)
    return review_alert(alert["id"])


def setup_confirmed_alert(program, account, alert_type="VELOCITY"):
    """Raises, reviews and confirms an alert (freezes the account as a cascade)."""
    alert = setup_alert_under_review(program, account, alert_type=alert_type)
    return confirm_alert(alert["id"])


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

def create_dispute(program, load, account, **overrides):
    load_version = get_load(load["id"])["version"]
    payload = create_dispute_payload(program["id"], load["id"], account["id"],
                                     load_version, **overrides)
    return get_success_data(api.create_dispute(payload, ANALYST))


def dispute_retailer_response(dispute_id, agreement_id, position="register receipt attached"):
    return api.dispute_retailer_response(
        dispute_id, {"retailer_position": position},
        make_retailer_clerk_headers(agreement_id))


def dispute_program_review(dispute_id, headers=None):
    return api.dispute_program_review(dispute_id, {}, headers or ANALYST)


def dispute_return_to_retailer(dispute_id):
    return api.dispute_return_to_retailer(dispute_id, ANALYST)


def dispute_resolve(dispute_id, resolution):
    return api.dispute_resolve(dispute_id, {"resolution": resolution}, OFFICER)


# ---------------------------------------------------------------------------
# Loss allocations
# ---------------------------------------------------------------------------

def create_loss_allocation(program, load, agreement, **overrides):
    payload = create_loss_allocation_payload(program["id"], load["id"], agreement["id"],
                                             **overrides)
    return get_success_data(api.create_loss_allocation(payload, OFFICER))


def post_loss_allocation(allocation_id):
    return get_success_data(api.post_loss_allocation(allocation_id, OFFICER))


def recover_loss_allocation(allocation_id):
    return get_success_data(api.recover_loss_allocation(allocation_id, SETTLEMENT))


# ---------------------------------------------------------------------------
# Settlement batches
# ---------------------------------------------------------------------------

def create_settlement_batch(agreement, **overrides):
    payload = create_settlement_batch_payload(agreement["id"], **overrides)
    return get_success_data(api.create_settlement_batch(payload, SETTLEMENT))


def open_settlement_batch(batch_id):
    return get_success_data(api.open_settlement_batch(batch_id, SETTLEMENT))


def settle_settlement_batch(batch_id):
    return api.settle_settlement_batch(batch_id, SETTLEMENT)


def settle_settlement_batch_ok(batch_id):
    return get_success_data(settle_settlement_batch(batch_id))


def clawback_settlement_batch(batch_id, reason="retailer reported the cash was never tendered"):
    return get_success_data(
        api.clawback_settlement_batch(batch_id, {"reason": reason}, SETTLEMENT))


def setup_settled_batch(agreement, period_start="2026-09-01T00:00:00Z",
                        period_end="2026-09-02T00:00:00Z"):
    batch = create_settlement_batch(agreement,
                                    period_start_at=period_start,
                                    period_end_at=period_end)
    open_settlement_batch(batch["id"])
    return settle_settlement_batch_ok(batch["id"])


# ---------------------------------------------------------------------------
# Float windows
# ---------------------------------------------------------------------------

def create_float_window(location, **overrides):
    payload = create_float_window_payload(location["id"], **overrides)
    return get_success_data(api.create_float_window(payload, SETTLEMENT))


def setup_requested_float_window(location, **overrides):
    return create_float_window(location, **overrides)


# ---------------------------------------------------------------------------
# Tier 2/3: composite networks
# ---------------------------------------------------------------------------

def setup_program_pair(clock=CLOCK_NOON, bank_overrides=None, program_overrides=None):
    """Logical clock + one sponsor + one OPEN program. Returns (bank, program)."""
    set_clock(clock)
    bank = create_sponsor(**(bank_overrides or {}))
    program = create_program(bank["id"], **(program_overrides or {}))
    return bank, program


def setup_brand_program(clock=CLOCK_NOON, brand_overrides=None, activate=False, **kwargs):
    """Sponsor + program + brand. Returns (bank, program, brand)."""
    bank, program = setup_program_pair(clock=clock, **kwargs)
    brand = create_brand(program, **(brand_overrides or {}))
    if activate:
        brand = activate_brand(brand)
    return bank, program, brand


def setup_network(clock=CLOCK_NOON, bank_overrides=None, program_overrides=None,
                  brand_overrides=None, agreement_overrides=None,
                  location_overrides=None, account_overrides=None,
                  activate_brand_flag=False, activate_agreement_flag=True):
    """The canonical composite: clock -> sponsor -> program -> brand ->
    agreement (optionally ACTIVE) -> location (OPEN) -> account.

    Returns a dict carrying every entity plus pre-built role headers.
    """
    set_clock(clock)
    bank = create_sponsor(**(bank_overrides or {}))
    program = create_program(bank["id"], **(program_overrides or {}))
    brand = create_brand(program, **(brand_overrides or {}))
    if activate_brand_flag:
        brand = activate_brand(brand)
    agreement = create_agreement(program, **(agreement_overrides or {}))
    if activate_agreement_flag:
        agreement = activate_agreement(program, agreement)
    location = create_location(program, agreement, **(location_overrides or {}))
    account = create_account(program, brand, **(account_overrides or {}))
    return {
        "bank": bank,
        "program": program,
        "brand": brand,
        "agreement": agreement,
        "location": location,
        "account": account,
        "bank_headers": make_bank_sponsor_headers(bank["id"]),
        "pm_headers": make_program_manager_headers(program["id"]),
        "clerk_headers": make_retailer_clerk_headers(agreement["id"]),
    }


def setup_network_with_funded_load(clock=CLOCK_NOON, principal_cents=3000, **kwargs):
    """setup_network plus one funded load. Adds 'load' to the returned dict."""
    network = setup_network(clock=clock, **kwargs)
    network["load"] = create_and_fund_load(
        network["location"], network["account"], network["agreement"],
        principal_cents=principal_cents)
    return network


def setup_network_with_settled_load(clock=CLOCK_NOON, principal_cents=12000, **kwargs):
    """setup_network plus a SETTLED load (funded -> reversed -> re-instated)."""
    network = setup_network(clock=clock, **kwargs)
    network["load"] = setup_settled_load(network, principal_cents=principal_cents)
    return network


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_velocity_boundary(funded_count=5, principal_cents=1000, **kwargs):
    """Create funded_count + 1 INITIATED loads up front (so no load creation is
    blocked by a live alert raised during funding), then fund the first
    `funded_count` of them.

    Returns (network, funded_loads, next_load).
    """
    network = setup_network(**kwargs)
    pending = [create_load(network["location"], network["account"],
                           network["agreement"], principal_cents=principal_cents)
               for _ in range(funded_count + 1)]
    funded = [fund_load(load["id"], network["agreement"]["id"])
              for load in pending[:funded_count]]
    next_load = pending[funded_count]
    network["loads"] = funded
    network["load"] = next_load
    return network, funded, next_load


def suspend_brands(network, count):
    """Create and activate `count` brands under the network's program, then
    suspend each by COMPLIANCE so posture_breach_count rises by `count`."""
    brands = []
    for i in range(count):
        program = get_program(network["program"]["id"])
        brand = create_brand(program, brand_name=f"Suspended Brand {i}",
                             services_scope=["LEDGERING"], ledgering_enabled=True,
                             compliance_oversight_enabled=False)
        activate_brand(brand)
        get_success_data(set_brand_state(brand["id"], "SUSPENDED"))
        brands.append(brand)
    return brands


def setup_program_frozen(network, brand_count=5):
    """Drive the program to FROZEN by accumulating breach count.

    Uses an overdue oversight review (which raises the decay factor to 0.20)
    plus `brand_count` COMPLIANCE-suspended brands; five breaches then yield a
    posture score above the 60.00 freeze floor.
    """
    suspend_brands(network, brand_count)
    return setup_frozen_program(network, target="FROZEN")


def setup_structuring_account(principals=(9000, 9500, 9999), **kwargs):
    """Fund one load per principal in the sub-threshold band. Returns (network, loads)."""
    network = setup_network(**kwargs)
    loads = []
    for p in principals:
        loads.append(create_and_fund_load(network["location"], network["account"],
                                          network["agreement"], principal_cents=p))
    network["loads"] = loads
    return network, loads


# ---------------------------------------------------------------------------
# Tier 5: finalization / terminal states
# ---------------------------------------------------------------------------

def setup_posted_loss_allocation(network, total_loss_cents=18000, principal_cents=12000,
                                 load=None):
    """A FUNDED load with a POSTED loss allocation raised on it. Returns
    (allocation, load).

    A fresh funded load is created unless the caller supplies one — callers that
    need the allocation to cover a specific load (e.g. a load they reversed
    themselves) pass `load=`.  PRD §3.8 places no load-status precondition on
    raising or posting an allocation, so a plain FUNDED load is the right
    precondition: a SETTLED load is excluded from the fund/confirm reversal hops
    the cascades walk.
    """
    if load is None:
        load = create_and_fund_load(network["location"], network["account"],
                                    network["agreement"], principal_cents=principal_cents)
    allocation = create_loss_allocation(network["program"], load, network["agreement"],
                                        total_loss_cents=total_loss_cents)
    allocation = post_loss_allocation(allocation["id"])
    return allocation, load


def setup_frozen_program(network, target="FROZEN"):
    """Drive the program to FROZEN through the posture transition."""
    program = get_program(network["program"]["id"])
    return api.set_program_state(
        program["id"],
        {"to_posture": target, "expected_program_version": program["version"]},
        make_bank_sponsor_headers(network["bank"]["id"]),
    )