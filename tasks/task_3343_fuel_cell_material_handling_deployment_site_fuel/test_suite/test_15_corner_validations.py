"""Corner coverage — validation rules and their error ids
(PRD §2.1, §2.7, §2.10, §3.2, §3.4, §3.6).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID, ANONYMOUS_HEADERS,
    set_clock, create_site, create_technician, create_approved_assessment,
    create_scheduled_plan, create_event,
    create_active_contract, create_planned_station, file_and_issue_permit,
    create_commissioned_station, create_draft_invoice, create_fueling_event,
    create_invoice_with_lines, create_fueling_event_payload,
    create_supply_contract_payload, create_invoice_payload,
    setup_billing_scenario, tech_headers,
    MANAGER, SAFETY, COMPLIANCE, BILLING,
)


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    name one of these roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    resp = api.list_sites(ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_forbidden_role_rejected(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.10: "Second, authorization: the role must be permitted on the
    endpoint (`ERR_FORBIDDEN`). Third, existence: every path-referenced
    resource must exist, validated left to right (`ERR_NOT_FOUND`)."

    Design: Corner/validations/forbidden_role_rejected
    """
    # SafetyOfficer calling the BillingOperator-only invoice creation; the ids
    # need not exist because authorization runs before existence checks.
    resp = api.create_invoice(create_invoice_payload(
        site_id=NON_EXISTENT_UUID, supply_contract_id=NON_EXISTENT_UUID,
        period_start="2026-10-01", period_end="2026-11-01"), SAFETY)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_occurrence_before_commission_rejected(api):
    """PRD §3.6: "The station must be `COMMISSIONED` and the `occurred_at`
    must not precede the station's `commissioned_at` — violations are
    `ERR_STATION_NOT_COMMISSIONED` (HTTP 422)."

    Design: Corner/validations/occurrence_before_commission_rejected
    """
    site = create_site(code="S-V3")
    contract = create_active_contract(
        site["id"], supply_mode="PIPELINE", base_price_per_kg=2.5,
        reliability_sla_pct=99.0, committed_monthly_kg=10)
    station = create_planned_station(
        site["id"], station_code="ST-V3", capacity_kg_per_day=500,
        storage_capacity_kg=1000, construction_start="2026-10-01",
        construction_end="2026-10-05")
    file_and_issue_permit(station["id"], "CONSTRUCTION")
    file_and_issue_permit(station["id"], "FIRE")
    validate_success(api.start_construction(station["id"], MANAGER))
    set_clock("2026-10-05T00:00:00Z")
    commissioned = validate_success(api.commission_station(station["id"], COMPLIANCE))
    assert commissioned["construction_status"] == "COMMISSIONED"
    # occurred_at 2026-10-03 precedes commissioned_at 2026-10-05.
    resp = api.create_fueling_event(
        station["id"], create_fueling_event_payload(
            forklift_id="FL-V3", occurred_at="2026-10-03T08:00:00Z",
            kg_dispensed=10, supply_contract_id=contract["id"]), MANAGER)
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_COMMISSIONED)


def test_indoor_commission_without_dispensing_permit_rejected(api):
    """PRD §2.7: "Separately, commissioning an `INDOOR` station requires a
    dispensing-specific approval: a permit of `permit_type` `DISPENSING_INDOOR`
    in `ISSUED` status must exist for that station, or commissioning is refused
    with `ERR_INDOOR_DISPENSING_NOT_APPROVED` (HTTP 422)."

    Design: Corner/validations/indoor_commission_without_dispensing_permit_rejected
    """
    site = create_site(code="S-V4")
    indoor = create_planned_station(
        site["id"], station_code="ST-IN", location_type="INDOOR",
        capacity_kg_per_day=100, storage_capacity_kg=150,
        construction_start="2026-10-01", construction_end="2026-11-01")
    outdoor = create_planned_station(
        site["id"], station_code="ST-OUT", location_type="OUTDOOR",
        capacity_kg_per_day=100, storage_capacity_kg=500,
        construction_start="2026-10-01", construction_end="2026-11-01")
    for st in (indoor, outdoor):
        file_and_issue_permit(st["id"], "CONSTRUCTION")
        file_and_issue_permit(st["id"], "FIRE")
        validate_success(api.start_construction(st["id"], MANAGER))
    resp = api.commission_station(indoor["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INDOOR_DISPENSING_NOT_APPROVED)
    commissioned = validate_success(api.commission_station(outdoor["id"], COMPLIANCE))
    assert commissioned["construction_status"] == "COMMISSIONED", (
        "OUTDOOR stations need no dispensing approval")


def test_terminate_contract_with_open_invoice_rejected(api):
    """PRD §3.2: "termination is blocked while any invoice billed under that
    contract sits in `DRAFT`, `ISSUED`, or `DISPUTED` status, rejected with
    `ERR_OPEN_INVOICES_EXIST` (HTTP 422); invoices that are `PAID` or `VOID` do
    not block."

    Design: Corner/validations/terminate_contract_with_open_invoice_rejected
    """
    site = create_site(code="S-V5")
    contract = create_active_contract(
        site["id"], supply_mode="PIPELINE", base_price_per_kg=2.5,
        reliability_sla_pct=99.0, committed_monthly_kg=10)
    invoice = create_draft_invoice(site["id"], contract["id"])
    resp = api.terminate_supply_contract(site["id"], contract["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_OPEN_INVOICES_EXIST)
    validate_success(api.void_invoice(invoice["id"], BILLING))
    terminated = validate_success(
        api.terminate_supply_contract(site["id"], contract["id"], MANAGER))
    assert terminated["status"] == "TERMINATED", "VOID invoices do not block"


def test_uncertified_technician_cannot_start(api):
    """PRD §3.4: "Starting an event moves it `SCHEDULED` to `IN_PROGRESS`; it
    requires the technician to be `active` and their `certified_until` to be
    after the current date, failing with `ERR_TECHNICIAN_NOT_CERTIFIED`
    (HTTP 422) when either lapses, and the parent plan must be `SCHEDULED` or
    `IN_PROGRESS`."

    Design: Corner/validations/uncertified_technician_cannot_start
    """
    # Certification must be in the future at registration: register at
    # 2026-09-01 with certified_until 2026-10-01, then advance past it.
    site = create_site(clock="2026-09-01T00:00:00Z", code="S-V6")
    tech = create_technician(name="Tech Expired", certification_level="BASIC",
                             certified_until="2026-10-01")
    create_approved_assessment(
        site["id"], forklift_count=2, duty_cycle_hours_per_day=4.0,
        peak_shift_hours=6)
    plan = create_scheduled_plan(
        site["id"], name="Wave V6", target_forklift_count=1,
        start_date="2026-09-01", end_date="2026-12-01",
        baseline_productivity_units_per_hour=40.0,
        expected_productivity_gain_pct=5)
    ev = create_event(plan["id"], tech["id"], forklift_id="FL-V6",
                      scheduled_start="2026-10-05T08:00:00Z",
                      scheduled_end="2026-10-05T10:00:00Z")
    set_clock("2026-10-05T00:00:00Z")
    resp = api.start_event(plan["id"], ev["id"], tech_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_CERTIFIED)


def test_event_double_billing_rejected(api):
    """PRD §3.6: "the event must fall within the invoice's `[period_start,
    period_end)` window, be billed under the same `supply_contract_id` as the
    invoice, and not already appear on another line item of any non-`VOID`
    invoice — otherwise `ERR_EVENT_NOT_BILLABLE` (HTTP 422)."

    Design: Corner/validations/event_double_billing_rejected
    """
    site, contract, station = setup_billing_scenario(
        site_code="S-V7", supply_mode="PIPELINE",
        base_price_per_kg=2.5, committed_monthly_kg=10)
    fe = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-V7",
        occurred_at="2026-10-10T08:00:00Z", kg_dispensed=5)
    inv1, _lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe["id"]])
    inv2 = create_draft_invoice(site["id"], contract["id"])
    resp = api.add_line_item(
        inv2["id"], {"fueling_event_id": fe["id"],
                     "expected_invoice_version": inv2["version"]}, BILLING)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_BILLABLE)


def test_fueling_event_without_active_contract_rejected(api):
    """PRD §3.6: "The referenced contract must be `ACTIVE`, belong to the same
    site as the station, and cover the dispense: the date of `occurred_at`
    must fall on or after the contract's `start_date` and on or before its
    `end_date`. A contract failing any of these yields `ERR_NO_ACTIVE_CONTRACT`
    (HTTP 422)."

    Design: Corner/validations/fueling_event_without_active_contract_rejected
    """
    site = create_site(code="S-V8")
    contract = get_success_data(api.create_supply_contract(
        site["id"], create_supply_contract_payload(
            supply_mode="PIPELINE", base_price_per_kg=2.5,
            reliability_sla_pct=99.0, committed_monthly_kg=10), MANAGER))
    assert contract["status"] == "DRAFT", "never activated"
    station = create_commissioned_station(site["id"], station_code="ST-V8")
    resp = api.create_fueling_event(
        station["id"], create_fueling_event_payload(
            forklift_id="FL-V8", occurred_at="2026-10-10T08:00:00Z",
            kg_dispensed=5, supply_contract_id=contract["id"]), MANAGER)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CONTRACT)
