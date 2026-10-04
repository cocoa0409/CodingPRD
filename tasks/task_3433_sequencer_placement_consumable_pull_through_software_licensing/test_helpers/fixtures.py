"""Composite setup helpers (PRD section 3 workflows).

Every fixture builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and returns the parsed `data` payload(s) of
the final call(s). Setup calls use the lenient get_success_data() validator so
failures surface as clear "Setup step failed" errors.

Identity threading: LabOperator calls always go through
make_lab_operator_headers(account_id) because the LabOperator X-User-ID IS the
account id. Segregation-of-duties flows take explicit am_user_id / fa_user_id
arguments that MUST differ.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_payload,
    create_account_payload,
    create_credit_grant_payload,
    create_instrument_model_payload,
    create_instrument_payload,
    create_placement_program_payload,
    create_reagent_kit_payload,
    create_reagent_lot_payload,
    create_reagent_order_payload,
    create_run_record_payload,
    create_service_contract_payload,
    create_software_license_payload,
    create_software_update_payload,
    create_supply_forecast_payload,
    create_transition_program_payload,
    forecast_advance_payload,
    forecast_line,
    instrument_event_payload,
    license_status_payload,
    lot_qc_payload,
    order_advance_payload,
    order_line,
    program_review_payload,
    transition_advance_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_manager_headers,
    make_finance_admin_headers,
    make_lab_operator_headers,
)

__all__ = [
    "advance_clock",
    "create_account",
    "create_model",
    "create_kit",
    "create_software_update",
    "create_instrument",
    "drive_instrument_to",
    "commission_instrument",
    "create_operational_instrument",
    "create_decommissioned_instrument",
    "create_lot",
    "create_lots",
    "pass_lot_qc",
    "create_passed_lot",
    "create_program",
    "submit_program",
    "approve_program",
    "create_submitted_program",
    "create_active_program",
    "close_program_periods",
    "create_contract",
    "activate_contract",
    "create_active_contract",
    "record_service_window",
    "create_license",
    "activate_license",
    "create_active_license",
    "grant_credits",
    "create_forecast",
    "submit_forecast",
    "create_submitted_forecast",
    "freeze_forecast",
    "create_frozen_forecast",
    "create_order",
    "submit_order",
    "ship_order",
    "deliver_order",
    "create_allocated_order",
    "create_shipped_order",
    "create_delivered_order",
    "record_run",
    "create_enrolled_transition",
    "appraise_transition",
    "setup_run_ready",
    "setup_active_contract_scenario",
    "setup_update_gate_scenario",
    "setup_breached_account",
    "setup_program_order_pipeline",
    "setup_backordered_order",
]


# ---------------------------------------------------------------------------
# Test-driving logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------
def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; returns {current_utc, lots_expired,
    contracts_expired, transitions_expired}."""
    return get_success_data(
        api_client.set_clock(clock_payload(to_iso8601), TEST_USERS["platform_admin_headers"])
    )


# ---------------------------------------------------------------------------
# Accounts and vendor catalog
# ---------------------------------------------------------------------------
def create_account(name=None, regulatory_class="RUO", region="NA") -> dict:
    payload = create_account_payload()
    if name is not None:
        payload["name"] = name
    payload["regulatory_class"] = regulatory_class
    payload["region"] = region
    return get_success_data(
        api_client.create_account(payload, TEST_USERS["account_manager_headers"])
    )


def create_model(**overrides) -> dict:
    return get_success_data(
        api_client.create_instrument_model(
            create_instrument_model_payload(**overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


def create_kit(**overrides) -> dict:
    return get_success_data(
        api_client.create_reagent_kit(
            create_reagent_kit_payload(**overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


def create_software_update(**overrides) -> dict:
    return get_success_data(
        api_client.create_software_update(
            create_software_update_payload(**overrides),
            TEST_USERS["platform_admin_headers"],
        )
    )


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------
def create_instrument(account_id=None, model_id=None, regulatory_class="RUO",
                      model_overrides=None, **overrides) -> dict:
    """Register an instrument (initial state ORDERED). Creates the owning
    account and/or catalog model when their ids are not supplied. The
    regulatory_mode defaults to the account's regulatory_class so CLINICAL
    accounts get CLINICAL instruments (PRD section 2.6)."""
    if account_id is None:
        account_id = create_account(regulatory_class=regulatory_class)["id"]
    if model_id is None:
        model_id = create_model(**(model_overrides or {}))["id"]
    overrides.setdefault("regulatory_mode", regulatory_class)
    return get_success_data(
        api_client.create_instrument(
            create_instrument_payload(account_id, model_id, **overrides),
            TEST_USERS["account_manager_headers"],
        )
    )


_FORWARD_EVENTS = {"ORDERED": "SHIP", "SHIPPED": "INSTALL", "INSTALLED": "COMMISSION"}


def drive_instrument_to(instrument_id: str, target_state: str) -> dict:
    """Walk an instrument forward along ORDERED -> SHIPPED -> INSTALLED ->
    OPERATIONAL until it reaches target_state. Returns the instrument."""
    data = get_success_data(
        api_client.get_instrument(instrument_id, TEST_USERS["account_manager_headers"])
    )
    while data["install_state"] != target_state:
        action = _FORWARD_EVENTS[data["install_state"]]
        data = get_success_data(
            api_client.post_instrument_event(
                instrument_id,
                instrument_event_payload(action),
                TEST_USERS["field_service_engineer_headers"],
            )
        )
    return data


def commission_instrument(instrument_id: str) -> dict:
    """Walk an instrument ORDERED -> SHIPPED -> INSTALLED -> OPERATIONAL."""
    return drive_instrument_to(instrument_id, "OPERATIONAL")


def create_operational_instrument(account_id=None, model_id=None, regulatory_class="RUO",
                                  model_overrides=None, **instrument_overrides) -> dict:
    """Register an instrument and commission it to OPERATIONAL."""
    instrument = create_instrument(
        account_id=account_id, model_id=model_id, regulatory_class=regulatory_class,
        model_overrides=model_overrides, **instrument_overrides,
    )
    return drive_instrument_to(instrument["id"], "OPERATIONAL")


def create_decommissioned_instrument(account_id=None, model_id=None,
                                     regulatory_class="RUO",
                                     model_overrides=None, **instrument_overrides) -> dict:
    """OPERATIONAL instrument decommissioned by an AccountManager (no contracts
    attached, so the cascade has nothing to terminate)."""
    instrument = create_operational_instrument(
        account_id=account_id, model_id=model_id, regulatory_class=regulatory_class,
        model_overrides=model_overrides, **instrument_overrides,
    )
    return get_success_data(
        api_client.post_instrument_event(
            instrument["id"],
            instrument_event_payload("DECOMMISSION"),
            TEST_USERS["account_manager_headers"],
        )
    )


# ---------------------------------------------------------------------------
# Reagent lots
# ---------------------------------------------------------------------------
def create_lot(kit_id=None, kit_overrides=None, **overrides) -> dict:
    """Register a lot (initial qc_status PENDING_QC). Creates its kit when no
    kit_id is supplied."""
    if kit_id is None:
        kit_id = create_kit(**(kit_overrides or {}))["id"]
    return get_success_data(
        api_client.create_reagent_lot(
            create_reagent_lot_payload(kit_id, **overrides),
            TEST_USERS["supply_planner_headers"],
        )
    )


def create_lots(kit_id: str, count: int, **overrides) -> list:
    """Register `count` lots under one kit (pagination fixtures)."""
    return [create_lot(kit_id=kit_id, **overrides) for _ in range(count)]


def pass_lot_qc(lot_id: str) -> dict:
    return get_success_data(
        api_client.post_lot_qc(
            lot_id, lot_qc_payload("PASSED"), TEST_USERS["supply_planner_headers"]
        )
    )


def create_passed_lot(kit_id=None, kit_overrides=None, **overrides) -> dict:
    """Register a lot and pass its QC (usable for allocation and runs)."""
    lot = create_lot(kit_id=kit_id, kit_overrides=kit_overrides, **overrides)
    return pass_lot_qc(lot["id"])


# ---------------------------------------------------------------------------
# Placement programs
# ---------------------------------------------------------------------------
def create_program(account_id=None, am_user_id="am-creator", **overrides) -> dict:
    """Create a DRAFT placement program; records am_user_id as creator."""
    if account_id is None:
        account_id = create_account()["id"]
    return get_success_data(
        api_client.create_placement_program(
            create_placement_program_payload(account_id, **overrides),
            make_account_manager_headers(am_user_id),
        )
    )


def submit_program(program_id: str, am_user_id="am-creator") -> dict:
    """Review SUBMIT: DRAFT -> PENDING_APPROVAL (recomputes subsidy pool)."""
    return get_success_data(
        api_client.review_placement_program(
            program_id,
            program_review_payload("SUBMIT"),
            make_account_manager_headers(am_user_id),
        )
    )


def approve_program(program_id: str, fa_user_id="fa-approver") -> dict:
    """Review APPROVE: PENDING_APPROVAL -> ACTIVE (pins the kit price book).
    fa_user_id MUST differ from the program's creator (segregation of duties)."""
    return get_success_data(
        api_client.review_placement_program(
            program_id,
            program_review_payload("APPROVE"),
            make_finance_admin_headers(fa_user_id),
        )
    )


def create_submitted_program(account_id=None, am_user_id="am-creator", **overrides) -> dict:
    """Program in PENDING_APPROVAL."""
    program = create_program(account_id=account_id, am_user_id=am_user_id, **overrides)
    return submit_program(program["id"], am_user_id)


def create_active_program(account_id=None, am_user_id="am-creator",
                          fa_user_id="fa-approver", **overrides) -> dict:
    """Program driven DRAFT -> PENDING_APPROVAL -> ACTIVE."""
    program = create_program(account_id=account_id, am_user_id=am_user_id, **overrides)
    submit_program(program["id"], am_user_id)
    return approve_program(program["id"], fa_user_id)


def close_program_periods(program_id: str, count: int) -> dict:
    """Close `count` commitment periods (FinanceAdmin ritual, PRD 3.3).
    Returns the final close's program payload."""
    data = None
    for _ in range(count):
        data = get_success_data(
            api_client.close_placement_period(
                program_id, TEST_USERS["finance_admin_headers"]
            )
        )
    return data


# ---------------------------------------------------------------------------
# Service contracts and uptime
# ---------------------------------------------------------------------------
def create_contract(account_id=None, instrument_id=None, **overrides) -> dict:
    """Create a DRAFT service contract. Creates account/instrument as needed."""
    if account_id is None:
        account_id = create_account()["id"]
    if instrument_id is None:
        instrument_id = create_instrument(account_id=account_id)["id"]
    return get_success_data(
        api_client.create_service_contract(
            create_service_contract_payload(account_id, instrument_id, **overrides),
            TEST_USERS["finance_admin_headers"],
        )
    )


def activate_contract(contract_id: str) -> dict:
    return get_success_data(
        api_client.activate_service_contract(
            contract_id, TEST_USERS["finance_admin_headers"]
        )
    )


def create_active_contract(account_id=None, instrument_id=None, **overrides) -> dict:
    """Contract driven DRAFT -> ACTIVE."""
    contract = create_contract(
        account_id=account_id, instrument_id=instrument_id, **overrides
    )
    return activate_contract(contract["id"])


def record_service_window(instrument_id: str, open_at: str, close_at: str) -> dict:
    """Open a service window at open_at and close it at close_at (logical
    clock advances in between). Instrument must be OPERATIONAL; returns it
    OPERATIONAL again with one more closed window (PRD section 3.2)."""
    advance_clock(open_at)
    get_success_data(
        api_client.post_instrument_event(
            instrument_id,
            instrument_event_payload("SERVICE_OPEN"),
            TEST_USERS["field_service_engineer_headers"],
        )
    )
    advance_clock(close_at)
    return get_success_data(
        api_client.post_instrument_event(
            instrument_id,
            instrument_event_payload("SERVICE_CLOSE"),
            TEST_USERS["field_service_engineer_headers"],
        )
    )


# ---------------------------------------------------------------------------
# Software licenses and cloud credits
# ---------------------------------------------------------------------------
def create_license(account_id=None) -> dict:
    """Create a DRAFT software license."""
    if account_id is None:
        account_id = create_account()["id"]
    return get_success_data(
        api_client.create_software_license(
            create_software_license_payload(account_id),
            TEST_USERS["finance_admin_headers"],
        )
    )


def activate_license(license_id: str) -> dict:
    """ACTIVATE: pins sample rates and anchors billing periods (PRD 3.7)."""
    return get_success_data(
        api_client.set_license_status(
            license_id,
            license_status_payload("ACTIVATE"),
            TEST_USERS["finance_admin_headers"],
        )
    )


def grant_credits(license_id: str, credits: int, grant_type="PURCHASE",
                  granted_on=None) -> dict:
    """Append a GRANT/PURCHASE ledger entry; returns the updated license."""
    payload = create_credit_grant_payload(credits, grant_type=grant_type)
    if granted_on is not None:
        payload["granted_on"] = granted_on
    return get_success_data(
        api_client.post_credit_grant(
            license_id, payload, TEST_USERS["finance_admin_headers"]
        )
    )


def create_active_license(account_id=None, grant_credits_amount=None,
                          granted_on=None, grant_type="PURCHASE") -> dict:
    """License driven DRAFT -> ACTIVE, optionally with one credit grant."""
    license_data = create_license(account_id=account_id)
    license_data = activate_license(license_data["id"])
    if grant_credits_amount is not None:
        license_data = grant_credits(
            license_data["id"], grant_credits_amount,
            grant_type=grant_type, granted_on=granted_on,
        )
    return license_data


# ---------------------------------------------------------------------------
# Supply forecasts
# ---------------------------------------------------------------------------
def create_forecast(account_id=None, lines=None, kit_code=None) -> dict:
    """Create a DRAFT supply forecast. With no lines supplied, creates a kit
    and one default 10-unit line for the default Monday week start."""
    if account_id is None:
        account_id = create_account()["id"]
    if lines is None:
        if kit_code is None:
            kit_code = create_kit()["kit_code"]
        lines = [forecast_line(kit_code)]
    return get_success_data(
        api_client.create_supply_forecast(
            create_supply_forecast_payload(account_id, lines),
            TEST_USERS["supply_planner_headers"],
        )
    )


def submit_forecast(forecast_id: str) -> dict:
    """Forecast SUBMIT: DRAFT -> SUBMITTED (capacity check, PRD 3.9)."""
    return get_success_data(
        api_client.advance_supply_forecast(
            forecast_id,
            forecast_advance_payload("SUBMIT"),
            TEST_USERS["supply_planner_headers"],
        )
    )


def create_submitted_forecast(account_id=None, lines=None, kit_code=None) -> dict:
    forecast = create_forecast(account_id=account_id, lines=lines, kit_code=kit_code)
    return submit_forecast(forecast["id"])


def freeze_forecast(forecast_id: str, expected_forecast_version: int) -> dict:
    """Forecast FREEZE (OCC-guarded): SUBMITTED -> FROZEN; supersedes the
    account's prior FROZEN forecasts."""
    return get_success_data(
        api_client.advance_supply_forecast(
            forecast_id,
            forecast_advance_payload(
                "FREEZE", expected_forecast_version=expected_forecast_version
            ),
            TEST_USERS["supply_planner_headers"],
        )
    )


def create_frozen_forecast(account_id=None, lines=None, kit_code=None) -> dict:
    forecast = create_submitted_forecast(
        account_id=account_id, lines=lines, kit_code=kit_code
    )
    return freeze_forecast(forecast["id"], forecast["version"])


# ---------------------------------------------------------------------------
# Reagent orders
# ---------------------------------------------------------------------------
def create_order(account_id: str, lines: list, program_id=None) -> dict:
    """Create a DRAFT order as the account's own LabOperator."""
    payload = create_reagent_order_payload(account_id, lines)
    if program_id is not None:
        payload["program_id"] = program_id
    return get_success_data(
        api_client.create_reagent_order(payload, make_lab_operator_headers(account_id))
    )


def submit_order(order_id: str, account_id: str) -> dict:
    """Order SUBMIT: DRAFT -> ALLOCATED (pricing + FEFO allocation)."""
    return get_success_data(
        api_client.advance_reagent_order(
            order_id,
            order_advance_payload("SUBMIT"),
            make_lab_operator_headers(account_id),
        )
    )


def ship_order(order_id: str) -> dict:
    """Order SHIP: ALLOCATED -> SHIPPED (SupplyPlanner)."""
    return get_success_data(
        api_client.advance_reagent_order(
            order_id,
            order_advance_payload("SHIP"),
            TEST_USERS["supply_planner_headers"],
        )
    )


def deliver_order(order_id: str) -> dict:
    """Order DELIVER: SHIPPED -> DELIVERED (SupplyPlanner); settles lots and
    program attribution, and may auto-complete the program."""
    return get_success_data(
        api_client.advance_reagent_order(
            order_id,
            order_advance_payload("DELIVER"),
            TEST_USERS["supply_planner_headers"],
        )
    )


def create_allocated_order(account_id: str, lines: list, program_id=None) -> dict:
    order = create_order(account_id, lines, program_id)
    return submit_order(order["id"], account_id)


def create_shipped_order(account_id: str, lines: list, program_id=None) -> dict:
    order = create_allocated_order(account_id, lines, program_id)
    return ship_order(order["id"])


def create_delivered_order(account_id: str, lines: list, program_id=None) -> dict:
    order = create_shipped_order(account_id, lines, program_id)
    return deliver_order(order["id"])


# ---------------------------------------------------------------------------
# Run records
# ---------------------------------------------------------------------------
def record_run(instrument_id: str, lot_id: str, license_id: str, account_id: str,
               **overrides) -> dict:
    """Record a sequencing run as the account's own LabOperator."""
    payload = create_run_record_payload(instrument_id, lot_id, license_id, **overrides)
    return get_success_data(
        api_client.create_run_record(payload, make_lab_operator_headers(account_id))
    )


# ---------------------------------------------------------------------------
# Transition programs
# ---------------------------------------------------------------------------
def create_enrolled_transition(account_id=None, old_instrument_id=None,
                               new_model_id=None, commission=False,
                               am_user_id="am-creator", old_installed_at=None,
                               old_model_overrides=None, new_model_overrides=None,
                               regulatory_class="RUO", **overrides) -> dict:
    """Enroll an old instrument into a transition program (ENROLLED).

    Returns {"account", "old_model", "new_model", "old_instrument",
    "transition"}. When the old instrument is built here, its model defaults
    to generation 2 / 4,000,000c and the new model to generation 3 /
    5,000,000c (a gap-1 enrollment); override via old_model_overrides /
    new_model_overrides. commission=True drives the old instrument to
    OPERATIONAL so a later COMPLETE can decommission it.
    """
    if account_id is None:
        account = create_account(regulatory_class=regulatory_class)
    else:
        account = get_success_data(
            api_client.get_account(account_id, TEST_USERS["account_manager_headers"])
        )
    old_model = None
    if old_instrument_id is None:
        old_cfg = {
            "generation": 2,
            "base_price_cents": 4_000_000,
            "supported_chemistry_versions": ["V1"],
        }
        old_cfg.update(old_model_overrides or {})
        old_model = create_model(**old_cfg)
        instrument_kwargs = {}
        if old_installed_at is not None:
            instrument_kwargs["installed_at"] = old_installed_at
        instrument = create_instrument(
            account_id=account["id"], model_id=old_model["id"],
            regulatory_class=regulatory_class, **instrument_kwargs,
        )
        if commission:
            instrument = drive_instrument_to(instrument["id"], "OPERATIONAL")
    else:
        instrument = get_success_data(
            api_client.get_instrument(
                old_instrument_id, TEST_USERS["account_manager_headers"]
            )
        )
    new_model = None
    if new_model_id is None:
        new_cfg = {
            "generation": 3,
            "base_price_cents": 5_000_000,
            "supported_chemistry_versions": ["V1", "V2"],
        }
        new_cfg.update(new_model_overrides or {})
        new_model = create_model(**new_cfg)
        new_model_id = new_model["id"]
    payload = create_transition_program_payload(
        account["id"], instrument["id"], new_model_id, **overrides
    )
    transition = get_success_data(
        api_client.create_transition_program(
            payload, make_account_manager_headers(am_user_id)
        )
    )
    return {
        "account": account,
        "old_model": old_model,
        "new_model": new_model,
        "old_instrument": instrument,
        "transition": transition,
    }


def appraise_transition(program_id: str, condition_flags=None,
                        fa_user_id="fa-appraiser") -> dict:
    """APPRAISE: ENROLLED -> APPRAISED (final credit computed). fa_user_id
    MUST differ from the transition's creator (segregation of duties)."""
    return get_success_data(
        api_client.advance_transition_program(
            program_id,
            transition_advance_payload("APPRAISE", condition_flags=condition_flags),
            make_finance_admin_headers(fa_user_id),
        )
    )


# ---------------------------------------------------------------------------
# Composite scenario fixtures
# ---------------------------------------------------------------------------
def setup_run_ready(regulatory_class="RUO", model_overrides=None, kit_overrides=None,
                    instrument_overrides=None, lot_overrides=None, pass_qc=True,
                    grant_credits_amount=None, granted_on=None, grant_type="PURCHASE",
                    activate=True) -> dict:
    """Everything a sequencing run needs: account, catalog model, catalog kit,
    OPERATIONAL instrument, a lot (QC_PASSED unless pass_qc=False), and an
    ACTIVE license (optionally pre-loaded with cloud credits).

    Returns {"account", "model", "kit", "instrument", "lot", "license"}.
    CLINICAL accounts automatically get a CLINICAL instrument; pair with
    kit_overrides/model_overrides to exercise the regulatory gates.
    """
    account = create_account(regulatory_class=regulatory_class)
    model = create_model(**(model_overrides or {}))
    kit = create_kit(**(kit_overrides or {}))
    instrument = create_operational_instrument(
        account_id=account["id"], model_id=model["id"],
        regulatory_class=regulatory_class, **(instrument_overrides or {}),
    )
    if pass_qc:
        lot = create_passed_lot(kit_id=kit["id"], **(lot_overrides or {}))
    else:
        lot = create_lot(kit_id=kit["id"], **(lot_overrides or {}))
    license_data = create_license(account_id=account["id"])
    if activate:
        license_data = activate_license(license_data["id"])
    if grant_credits_amount is not None:
        license_data = grant_credits(
            license_data["id"], grant_credits_amount,
            grant_type=grant_type, granted_on=granted_on,
        )
    return {
        "account": account,
        "model": model,
        "kit": kit,
        "instrument": instrument,
        "lot": lot,
        "license": license_data,
    }


def setup_active_contract_scenario(regulatory_class="RUO", model_overrides=None,
                                   instrument_overrides=None,
                                   contract_overrides=None) -> dict:
    """Account + catalog model + OPERATIONAL instrument + ACTIVE service
    contract covering it. Returns {"account", "model", "instrument",
    "contract"}. Base state for uptime reconciliations and software-update
    application (both require OPERATIONAL and/or ACTIVE coverage)."""
    account = create_account(regulatory_class=regulatory_class)
    model = create_model(**(model_overrides or {}))
    instrument = create_operational_instrument(
        account_id=account["id"], model_id=model["id"],
        regulatory_class=regulatory_class, **(instrument_overrides or {}),
    )
    contract = create_active_contract(
        account_id=account["id"], instrument_id=instrument["id"],
        **(contract_overrides or {}),
    )
    return {
        "account": account,
        "model": model,
        "instrument": instrument,
        "contract": contract,
    }


def setup_update_gate_scenario(regulatory_class="RUO", model_overrides=None,
                               instrument_overrides=None, contract_overrides=None,
                               update_overrides=None) -> dict:
    """Active-contract scenario plus one published (RELEASED) software update.
    Returns {"account", "model", "instrument", "contract", "update"}."""
    bag = setup_active_contract_scenario(
        regulatory_class=regulatory_class,
        model_overrides=model_overrides,
        instrument_overrides=instrument_overrides,
        contract_overrides=contract_overrides,
    )
    bag["update"] = create_software_update(**(update_overrides or {}))
    return bag


def setup_breached_account(account_name=None, **program_overrides) -> dict:
    """Account whose placement program runs to term with zero delivered spend:
    the final period close posts the shortfall penalty, moves the program
    ACTIVE -> BREACHED, and flips the account's credit_hold to true
    (PRD section 3.3). Returns {"account", "program"} post-breach."""
    account = create_account(name=account_name) if account_name else create_account()
    program = create_active_program(account_id=account["id"], **program_overrides)
    program = close_program_periods(program["id"], program["term_months"])
    assert program["program_state"] == "BREACHED", (
        f"setup_breached_account expected BREACHED, got {program['program_state']}"
    )
    account = get_success_data(
        api_client.get_account(account["id"], TEST_USERS["account_manager_headers"])
    )
    assert account["credit_hold"] is True, "breached program must set credit_hold"
    return {"account": account, "program": program}


def setup_program_order_pipeline(kit_price_cents=5000, lot_quantity=10,
                                 order_quantity=2, program_overrides=None,
                                 kit_overrides=None, advance_to="ALLOCATED",
                                 am_user_id="am-creator",
                                 fa_user_id="fa-approver") -> dict:
    """ACTIVE placement program with one attributed order advanced to the
    requested state (ALLOCATED | SHIPPED | DELIVERED). The program pins the
    kit at kit_price_cents at approval. Returns {"account", "kit", "lot",
    "program", "order"}."""
    account = create_account()
    kit_cfg = {"price_cents": kit_price_cents}
    kit_cfg.update(kit_overrides or {})
    kit = create_kit(**kit_cfg)
    lot = create_passed_lot(kit_id=kit["id"], quantity_units=lot_quantity)
    program = create_active_program(
        account_id=account["id"], am_user_id=am_user_id, fa_user_id=fa_user_id,
        **(program_overrides or {}),
    )
    lines = [order_line(kit["kit_code"], order_quantity)]
    if advance_to == "ALLOCATED":
        order = create_allocated_order(account["id"], lines, program_id=program["id"])
    elif advance_to == "SHIPPED":
        order = create_shipped_order(account["id"], lines, program_id=program["id"])
    elif advance_to == "DELIVERED":
        order = create_delivered_order(account["id"], lines, program_id=program["id"])
    else:
        raise ValueError(f"advance_to must be ALLOCATED|SHIPPED|DELIVERED, got {advance_to}")
    return {
        "account": account,
        "kit": kit,
        "lot": lot,
        "program": program,
        "order": order,
    }


def setup_backordered_order(order_quantity=1, lot_quantity=1) -> dict:
    """ALLOCATED order pushed to BACKORDERED by a field corrective action: its
    only reserving lot fails QC from QC_PASSED and full re-allocation is
    impossible (PRD section 3.4). Returns {"account", "kit", "lot", "order"}
    with the lot QC_FAILED and the order BACKORDERED."""
    account = create_account()
    kit = create_kit()
    lot = create_passed_lot(kit_id=kit["id"], quantity_units=lot_quantity)
    order = create_allocated_order(
        account["id"], [order_line(kit["kit_code"], order_quantity)]
    )
    lot = get_success_data(
        api_client.post_lot_qc(
            lot["id"], lot_qc_payload("FAILED"), TEST_USERS["supply_planner_headers"]
        )
    )
    order = get_success_data(
        api_client.get_reagent_order(order["id"], TEST_USERS["supply_planner_headers"])
    )
    assert order["order_state"] == "BACKORDERED", (
        f"setup_backordered_order expected BACKORDERED, got {order['order_state']}"
    )
    return {"account": account, "kit": kit, "lot": lot, "order": order}
