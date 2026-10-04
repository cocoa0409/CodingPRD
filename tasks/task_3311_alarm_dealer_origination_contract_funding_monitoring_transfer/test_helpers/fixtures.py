"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup failures
produce clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CAPEX_CENTS_BY_CONFIG, LOGICAL_CLOCK_START
from .factories import (
    create_alarm_event_payload,
    create_assumption_request_payload,
    create_contract_payload,
    create_customer_payload,
    create_dealer_payload,
    create_dispatch_payload,
    create_installation_payload,
    create_package_payload,
    create_reduction_action_payload,
    create_rescission_request_payload,
    create_service_visit_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_dealer_headers,
    make_operator_headers,
)

_PLATFORM = TEST_USERS["platform_admin_headers"]
_CHANNEL = TEST_USERS["channel_manager_headers"]
_ANALYST = TEST_USERS["funding_analyst_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]
_MONITORING = TEST_USERS["monitoring_operator_headers"]
_SERVICE = TEST_USERS["service_coordinator_headers"]


# ─── Small utilities ──────────────────────────────────

def _rows(response):
    """Lenient extractor for a list response body."""
    data = get_success_data(response)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _first(response):
    rows = _rows(response)
    assert rows, "Setup failed: expected at least one row in list response"
    return rows[0]


def set_logical_clock(to_iso8601=LOGICAL_CLOCK_START, headers=None):
    """Move the logical clock. Returns the reported current_utc."""
    res = api_client.set_clock(
        {"to_iso8601": to_iso8601}, headers or _PLATFORM
    )
    return get_success_data(res)


# ─── Tier 1: Single-entity creation ───────────────────

def register_dealer(dealer_code="D1", legal_name="Northstar Security LLC",
                    holdback_rate=0.10, quality_tier="TIER_1"):
    """Register a dealer. Returns the created Dealer row."""
    res = api_client.create_dealer(
        create_dealer_payload(
            dealer_code=dealer_code, legal_name=legal_name,
            holdback_rate=holdback_rate, quality_tier=quality_tier,
        ),
        _CHANNEL,
    )
    return get_success_data(res, 201)


def register_customer(full_name="Test Subscriber", email=None, phone="+15550001000"):
    """Register a subscriber. Returns the created Customer row."""
    if email is None:
        email = f"{full_name.lower().replace(' ', '.')}@example.com"
    res = api_client.create_customer(
        create_customer_payload(full_name=full_name, email=email, phone=phone),
        _CHANNEL,
    )
    return get_success_data(res, 201)


def open_package(dealer_id, package_reference="PKG-TEST", as_analyst=True,
                 headers=None):
    """Open a funding package owned by dealer_id. Returns the DealerPackage row."""
    payload = create_package_payload(dealer_id=dealer_id,
                                     package_reference=package_reference)
    res = api_client.create_package(payload, headers or _ANALYST)
    return get_success_data(res, 201)


# ─── Tier 2: Entity hierarchy ─────────────────────────

def originate_direct_contract(customer_id, equipment_config_code="PREMIUM",
                              credit_score=700, contract_term_months=60,
                              monthly_monitoring_cents=4999,
                              financed_charge_at_apr_cents=0,
                              installation_scheduled_at=None,
                              installation_duration_minutes=None,
                              installation_engineer_id=None,
                              **extra):
    """Originate a DIRECT-channel contract. Returns the Contract row."""
    overrides = dict(
        equipment_config_code=equipment_config_code,
        credit_score=credit_score,
        contract_term_months=contract_term_months,
        monthly_monitoring_cents=monthly_monitoring_cents,
        financed_charge_at_apr_cents=financed_charge_at_apr_cents,
    )
    if installation_scheduled_at is not None:
        overrides["installation_scheduled_at"] = installation_scheduled_at
    if installation_duration_minutes is not None:
        overrides["installation_duration_minutes"] = installation_duration_minutes
    if installation_engineer_id is not None:
        overrides["installation_engineer_id"] = installation_engineer_id
    overrides.update(extra)
    res = api_client.create_contract(
        create_contract_payload(customer_id, **overrides), _CHANNEL
    )
    return get_success_data(res, 201)


def declare_package_contract(package_id, customer_id, equipment_config_code="PREMIUM",
                             credit_score=700, contract_term_months=60,
                             monthly_monitoring_cents=4999,
                             financed_charge_at_apr_cents=0,
                             installation_scheduled_at=None,
                             installation_duration_minutes=None,
                             installation_engineer_id=None,
                             headers=None, **extra):
    """Declare a contract on a package. Returns the Contract row."""
    overrides = dict(
        equipment_config_code=equipment_config_code,
        credit_score=credit_score,
        contract_term_months=contract_term_months,
        monthly_monitoring_cents=monthly_monitoring_cents,
        financed_charge_at_apr_cents=financed_charge_at_apr_cents,
    )
    if installation_scheduled_at is not None:
        overrides["installation_scheduled_at"] = installation_scheduled_at
    if installation_duration_minutes is not None:
        overrides["installation_duration_minutes"] = installation_duration_minutes
    if installation_engineer_id is not None:
        overrides["installation_engineer_id"] = installation_engineer_id
    overrides.update(extra)
    res = api_client.declare_contract(
        package_id, create_contract_payload(customer_id, **overrides),
        headers or _ANALYST,
    )
    return get_success_data(res, 201)


# ─── Tier 3: Lifecycle shortcuts ──────────────────────

def find_monitoring_account(contract_id):
    """Return the monitoring account owned by contract_id."""
    return _first(api_client.list_monitoring_accounts(
        _MONITORING, params={"contract_id": contract_id}))


def find_installation(contract_id):
    """Return the first installation owned by contract_id."""
    return _first(api_client.list_installations(
        _SERVICE, params={"contract_id": contract_id}))


def provision_monitoring_account(contract_id):
    """Trigger the central-station transfer for the contract's account."""
    account = find_monitoring_account(contract_id)
    res = api_client.trigger_monitoring_transfer(account["id"], _MONITORING)
    return get_success_data(res)


def complete_contract_installation(contract_id):
    """Complete the contract's installation (requires a committed transfer)."""
    installation = find_installation(contract_id)
    res = api_client.complete_installation(installation["id"], _SERVICE)
    return get_success_data(res)


def project_version(contract_id):
    """Read the contract's current version (for OCC-guarded writes)."""
    return get_success_data(api_client.get_contract(contract_id, _ANALYST))["version"]


def package_version(package_id):
    """Read the package's current version (for OCC-guarded writes)."""
    return get_success_data(api_client.get_package(package_id, _ANALYST))["version"]


def fund_direct_contract(contract_id):
    """Fund a DIRECT contract whose monitoring account is already provisioned."""
    res = api_client.fund_contract(
        contract_id, {"expected_contract_version": project_version(contract_id)}, _ANALYST
    )
    return get_success_data(res)


def _create_provisioned_and_completed_direct(customer_id=None, **contract_kwargs):
    """Customer (optional) + DIRECT contract + provisioned account + completed install."""
    if customer_id is None:
        customer_id = register_customer(full_name="Direct Subscriber",
                                        email="direct.subscriber@example.com")["id"]
    contract = originate_direct_contract(customer_id, **contract_kwargs)
    provision_monitoring_account(contract["id"])
    complete_contract_installation(contract["id"])
    return customer_id, contract


def setup_funded_direct_contract(equipment_config_code="PREMIUM",
                                 credit_score=700, contract_term_months=60,
                                 monthly_monitoring_cents=4999,
                                 financed_charge_at_apr_cents=0,
                                 customer_id=None, customer_email=None,
                                 fund=True):
    """Create + provision + install + fund a DIRECT contract.

    Returns (customer, contract). When fund=False the contract is returned still in
    PENDING_VALIDATION with its account provisioned and its installation completed.
    """
    if customer_id is None:
        customer_id = register_customer(
            full_name="Funded Direct",
            email=customer_email or "funded.direct@example.com",
        )["id"]
    customer = get_success_data(api_client.get_customer(customer_id, _ANALYST))
    contract = originate_direct_contract(
        customer_id,
        equipment_config_code=equipment_config_code,
        credit_score=credit_score,
        contract_term_months=contract_term_months,
        monthly_monitoring_cents=monthly_monitoring_cents,
        financed_charge_at_apr_cents=financed_charge_at_apr_cents,
        installation_scheduled_at="2026-09-02T00:00:00Z",
        installation_engineer_id="ENG-1",
    )
    provision_monitoring_account(contract["id"])
    complete_contract_installation(contract["id"])
    if fund:
        contract = fund_direct_contract(contract["id"])
    else:
        contract = get_success_data(api_client.get_contract(contract["id"], _ANALYST))
    return customer, contract


def setup_package_with_contract(dealer_code="D1", legal_name="Northstar Security LLC",
                                holdback_rate=0.10,
                                quality_tier="TIER_1", package_reference="PKG-P1",
                                credit_score=700, equipment_config_code="PREMIUM",
                                contract_term_months=60, monthly_monitoring_cents=4999,
                                financed_charge_at_apr_cents=0,
                                install_scheduled_at="2026-09-02T00:00:00Z",
                                engineer_id="ENG-1", customer_email=None,
                                provision=True):
    """Dealer + package + one declared child contract (account optionally provisioned).

    Returns (dealer, package, contract).
    """
    dealer = register_dealer(dealer_code=dealer_code, legal_name=legal_name,
                             holdback_rate=holdback_rate,
                             quality_tier=quality_tier)
    package = open_package(dealer["id"], package_reference=package_reference)
    customer = register_customer(
        full_name="Package Subscriber",
        email=customer_email or f"{dealer_code.lower()}.pkgsub@example.com",
    )
    contract = declare_package_contract(
        package["id"], customer["id"],
        equipment_config_code=equipment_config_code,
        credit_score=credit_score,
        contract_term_months=contract_term_months,
        monthly_monitoring_cents=monthly_monitoring_cents,
        financed_charge_at_apr_cents=financed_charge_at_apr_cents,
        installation_scheduled_at=install_scheduled_at,
        installation_engineer_id=engineer_id,
    )
    if provision:
        provision_monitoring_account(contract["id"])
    package = get_success_data(api_client.get_package(package["id"], _ANALYST))
    return dealer, package, contract


def submit_and_approve_package(dealer, package_id):
    """Submit (as the owning Dealer) then approve (as the analyst). Returns the package."""
    get_success_data(api_client.submit_package(
        package_id, make_dealer_headers(dealer["id"])))
    res = api_client.approve_package(
        package_id, {"expected_dealer_package_version": package_version(package_id)},
        _ANALYST,
    )
    return get_success_data(res)


def fund_package(package_id):
    """Fund an APPROVED package with a fresh version."""
    res = api_client.fund_package(
        package_id, {"expected_dealer_package_version": package_version(package_id)},
        _ANALYST,
    )
    return get_success_data(res)


def setup_funded_package_contract(dealer_code="D1", holdback_rate=0.10,
                                  quality_tier="TIER_1", package_reference="PKG-P1",
                                  credit_score=700, equipment_config_code="PREMIUM",
                                  contract_term_months=60, monthly_monitoring_cents=4999,
                                  financed_charge_at_apr_cents=0,
                                  customer_email=None, provision=True, fund=True):
    """Full dealer channel lifecycle: dealer + package + child + provision + approve + fund.

    Returns (dealer, package, contract).
    """
    dealer, package, contract = setup_package_with_contract(
        dealer_code=dealer_code, holdback_rate=holdback_rate, quality_tier=quality_tier,
        package_reference=package_reference, credit_score=credit_score,
        equipment_config_code=equipment_config_code,
        contract_term_months=contract_term_months,
        monthly_monitoring_cents=monthly_monitoring_cents,
        financed_charge_at_apr_cents=financed_charge_at_apr_cents,
        customer_email=customer_email, provision=provision,
    )
    package = submit_and_approve_package(dealer, package["id"])
    if fund:
        package = fund_package(package["id"])
    contract = get_success_data(api_client.get_contract(contract["id"], _ANALYST))
    return dealer, package, contract


def cancel_contract(contract_id, customer_id=None):
    """Cancel a monitored contract. Uses the owning subscriber when given."""
    headers = make_customer_headers(customer_id) if customer_id else _ANALYST
    res = api_client.cancel_contract(contract_id, headers)
    return get_success_data(res)


# ─── Tier 4: Accumulation / threshold targeting ───────

def setup_alarm_account(alarm_count, provision=True, contract_id=None,
                        occurred_at="2026-08-15T00:00:00Z",
                        entered_offset_seconds=30):
    """Provision an account and record `alarm_count` alarms in the ratio window.

    Returns (account, [alarm rows]). Each alarm's entered_at_utc sits inside the
    inclusive verified window so it may later be verified.
    """
    if contract_id is None:
        _, contract = setup_funded_direct_contract(
            customer_email="alarm.account@example.com")
        contract_id = contract["id"]
    account = find_monitoring_account(contract_id)
    if provision and account["provision_state"] != "PROVISIONED":
        account = provision_monitoring_account(contract_id)

    alarms = []
    for i in range(alarm_count):
        res = api_client.create_alarm_event(
            create_alarm_event_payload(
                account["id"],
                signal_source=f"ZONE-{i + 1}",
                occurred_at=occurred_at,
                entered_at_utc=_shift_iso(occurred_at, entered_offset_seconds),
            ),
            _MONITORING,
        )
        alarms.append(get_success_data(res, 201))
    return account, alarms


def _shift_iso(iso, seconds):
    """Offset an ISO-8601 Z instant by a whole number of seconds."""
    from datetime import datetime, timedelta, timezone
    base = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    shifted = base + timedelta(seconds=seconds)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def verify_alarm(alarm_id, outcome="VERIFIED"):
    """Record a verification outcome on a PENDING alarm. Returns the alarm row."""
    res = api_client.verify_alarm_event(alarm_id, {"outcome": outcome}, _MONITORING)
    return get_success_data(res)


def setup_verified_alarm_account(alarm_count, outcome="VERIFIED", provision=True,
                                 occurred_at="2026-08-15T00:00:00Z"):
    """Account with `alarm_count` alarms, all verified with the given outcome."""
    account, alarms = setup_alarm_account(
        alarm_count, provision=provision, occurred_at=occurred_at)
    for alarm in alarms:
        verify_alarm(alarm["id"], outcome=outcome)
    return account, alarms


def setup_dispatch_scenario(alarm_count=1, provision=True):
    """Provisioned account plus `alarm_count` PENDING alarms ready for dispatch."""
    return setup_alarm_account(alarm_count, provision=provision)


def setup_cancelled_contract(dealer_code="D1", holdback_rate=0.10,
                             quality_tier="TIER_1", package_reference="PKG-C1",
                             equipment_config_code="PREMIUM", customer_id=None,
                             contract_term_months=60, credit_score=700):
    """Funded contract on the dealer channel, then cancelled.

    Returns (dealer, package, contract, customer_id).
    """
    if customer_id is None:
        register_customer(
            full_name="Cancelled Subscriber",
            email=f"{package_reference.lower()}.cancel@example.com",
        )
    dealer, package, contract = setup_package_with_contract(
        dealer_code=dealer_code, holdback_rate=holdback_rate, quality_tier=quality_tier,
        package_reference=package_reference, credit_score=credit_score,
        equipment_config_code=equipment_config_code,
        contract_term_months=contract_term_months,
    )
    package = submit_and_approve_package(dealer, package["id"])
    package = fund_package(package["id"])
    contract = get_success_data(api_client.get_contract(contract["id"], _ANALYST))
    contract = cancel_contract(contract["id"], customer_id=contract["customer_id"])
    return dealer, package, contract


def setup_delinquent_contract(sweep_month="2026-09", activate_at="2026-06-15T00:00:00Z",
                              equipment_config_code="PREMIUM"):
    """DIRECT contract funded ACTIVE in an earlier cohort month, then swept delinquent.

    Returns (customer, contract, sweep).
    """
    set_logical_clock(activate_at)
    customer = register_customer(full_name="Attrited Subscriber",
                                 email="attrited.subscriber@example.com")
    contract = originate_direct_contract(
        customer["id"], equipment_config_code=equipment_config_code,
        installation_scheduled_at=_shift_iso(activate_at, 12 * 3600),
        installation_engineer_id="ENG-3",
    )
    provision_monitoring_account(contract["id"])
    complete_contract_installation(contract["id"])
    contract = fund_direct_contract(contract["id"])
    set_logical_clock(LOGICAL_CLOCK_START)
    sweep_res = api_client.run_attrition_sweep(
        {"sweep_month": sweep_month}, _ANALYST)
    sweep = get_success_data(sweep_res, 201)
    contract = get_success_data(api_client.get_contract(contract["id"], _ANALYST))
    return customer, contract, sweep


# ─── Tier 5: Finalization / terminal-state helpers ────

def raise_service_required_action(account_id):
    """Open a SERVICE_REQUIRED reduction action on an account."""
    res = api_client.create_reduction_action(
        create_reduction_action_payload(account_id, action_type="SERVICE_REQUIRED"),
        _SERVICE,
    )
    return get_success_data(res, 201)


def setup_scheduled_visit(contract_id, scheduled_at="2026-09-10T00:00:00Z",
                          work_type="REPAIR", technician_id="TECH-1",
                          duration_minutes=None, allowed_duration_minutes=None,
                          schedule=True, schedule_at=None):
    """Request (and optionally schedule) a service visit. Returns the visit row."""
    kwargs = dict(scheduled_at=scheduled_at, work_type=work_type,
                  technician_id=technician_id)
    if duration_minutes is not None:
        kwargs["duration_minutes"] = duration_minutes
    if allowed_duration_minutes is not None:
        kwargs["allowed_duration_minutes"] = allowed_duration_minutes
    visit = get_success_data(api_client.create_service_visit(
        create_service_visit_payload(contract_id, **kwargs), _SERVICE), 201)
    if schedule:
        res = api_client.schedule_service_visit(
            visit["id"], {"scheduled_at": schedule_at or scheduled_at}, _SERVICE)
        visit = get_success_data(res)
    return visit


def setup_assumption_ready(customer_id=None, residence_state_code="TX",
                           incoming_credit_score=700, equipment_config_code="PREMIUM"):
    """Funded ACTIVE contract with a second subscriber and an open assumption request.

    Returns (outgoing_customer, incoming_customer, contract, assumption_request).
    """
    customer, contract = setup_funded_direct_contract(
        equipment_config_code=equipment_config_code,
        customer_email="assumption.outgoing@example.com",
    )
    incoming = register_customer(full_name="Incoming Subscriber",
                                 email="assumption.incoming@example.com")
    request = get_success_data(api_client.create_assumption_request(
        create_assumption_request_payload(
            contract["id"], incoming["id"],
            incoming_credit_score=incoming_credit_score,
            residence_state_code=residence_state_code,
        ),
        make_customer_headers(customer["id"]),
    ), 201)
    return customer, incoming, contract, request


def setup_rescission_ready(equipment_config_code="PREMIUM", contract_term_months=60,
                           financed_charge_at_apr_cents=0, operator_id="ops-requestor-1",
                           customer_email="rescission.subscriber@example.com"):
    """Funded DIRECT contract with an open rescission request.

    Returns (customer, contract, rescission_request).
    """
    customer, contract = setup_funded_direct_contract(
        equipment_config_code=equipment_config_code,
        contract_term_months=contract_term_months,
        financed_charge_at_apr_cents=financed_charge_at_apr_cents,
        customer_email=customer_email,
    )
    request = get_success_data(api_client.create_rescission_request(
        create_rescission_request_payload(contract["id"], operator_id=operator_id),
        make_customer_headers(customer["id"]),
    ), 201)
    return customer, contract, request


def approve_rescission(request_id, approver_id="ops-approver-1"):
    """Decide a rescission request as APPROVED under a given approver identity."""
    res = api_client.decide_rescission_request(
        request_id, {"outcome": "APPROVED"},
        make_operator_headers(approver_id, "ComplianceOfficer"),
    )
    return get_success_data(res)


def expected_capex_cents(equipment_config_code):
    """Capitalised equipment amount for a configuration."""
    return CAPEX_CENTS_BY_CONFIG[equipment_config_code]