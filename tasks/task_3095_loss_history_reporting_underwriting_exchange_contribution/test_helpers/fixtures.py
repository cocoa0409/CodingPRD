"""Composite setup helpers: build PRD-declared state via API calls.

Every fixture creates its own entities from an empty database (the harness
restarts the server before every test). Setup calls use get_success_data so
failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO
from .factories import (
    create_batch_payload,
    create_carrier_payload,
    create_claim_row_payload,
    create_consumer_payload,
    create_dispute_payload,
    create_inquiry_payload,
    create_notice_payload,
)
from .test_users import (
    make_admin_headers,
    make_compliance_headers,
    make_consumer_headers,
    make_data_steward_headers,
    make_underwriter_headers,
)

_counter = {"n": 0}


def _next_naic() -> str:
    _counter["n"] += 1
    return f"9{_counter['n']:04d}"


def admin() -> dict:
    return make_admin_headers()


def compliance() -> dict:
    return make_compliance_headers()


def set_clock(to_iso8601: str = CLOCK_DEFAULT_ISO) -> dict:
    """Advance the logical clock. Returns the sweep payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, admin())
    )


def init_exchange_rules(**overrides) -> dict:
    """Initialize the singleton rulebook, optionally patching tunables."""
    rules = get_success_data(api_client.create_exchange_rules({}, admin()))
    if overrides:
        rules = get_success_data(api_client.patch_exchange_rules(overrides, admin()))
    return rules


def create_carrier(legal_name="Test Carrier Mutual", naic_code=None, **overrides) -> dict:
    payload = create_carrier_payload(
        legal_name=legal_name,
        naic_code=naic_code or _next_naic(),
        **overrides,
    )
    return get_success_data(api_client.create_carrier(payload, admin()))


def create_consumer(
    full_name="Test Person",
    date_of_birth="1985-01-01",
    address_line="1 Test St, Austin TX",
    driver_license_number=None,
    **overrides,
) -> dict:
    _counter["n"] += 1
    payload = create_consumer_payload(
        full_name=full_name,
        date_of_birth=date_of_birth,
        address_line=address_line,
        driver_license_number=driver_license_number or f"DL-{_counter['n']}",
        **overrides,
    )
    return get_success_data(api_client.create_consumer(payload, admin()))


def submit_batch(carrier: dict, claim_rows: list) -> dict:
    """Submit a batch as the carrier's data steward. Returns the batch."""
    return get_success_data(
        api_client.create_batch(
            carrier["id"],
            create_batch_payload(claims=claim_rows),
            make_data_steward_headers(carrier["id"]),
        )
    )


def make_claim_row(consumer_id: str, claim_number: str, **overrides) -> dict:
    return create_claim_row_payload(
        consumer_id=consumer_id, claim_number=claim_number, **overrides
    )


def activate_carrier(carrier: dict, consumer: dict, **claim_overrides) -> tuple:
    """Contribute one valid claim so the carrier transitions to ACTIVE.
    Returns (batch, carrier_refreshed)."""
    batch = submit_batch(
        carrier, [make_claim_row(consumer["id"], f"{carrier['naic_code']}-A1", **claim_overrides)]
    )
    refreshed = get_success_data(api_client.get_carrier(carrier["id"], admin()))
    return batch, refreshed


def submit_inquiry(carrier: dict, consumer: dict, **overrides) -> dict:
    """File an inquiry as the carrier's underwriter matching the consumer's
    exact identifiers. Returns the inquiry data."""
    payload = create_inquiry_payload(
        subject_name=consumer["full_name"],
        subject_dob=consumer["date_of_birth"],
        subject_address=consumer["address_line"],
        subject_driver_license=consumer["driver_license_number"],
        **overrides,
    )
    return get_success_data(
        api_client.create_inquiry(
            carrier["id"], payload, make_underwriter_headers(carrier["id"])
        )
    )


def setup_active_carrier_with_report(
    consumer_overrides=None, claim_overrides=None, inquiry_overrides=None
) -> dict:
    """Clock + rules + carrier (ACTIVE) + consumer with one claim + one inquiry
    issuing a report. Returns a dict of all created resources."""
    set_clock()
    init_exchange_rules()
    carrier = create_carrier()
    consumer = create_consumer(**(consumer_overrides or {}))
    batch = submit_batch(
        carrier,
        [
            make_claim_row(
                consumer["id"],
                f"{carrier['naic_code']}-1",
                **(claim_overrides or {}),
            )
        ],
    )
    carrier = get_success_data(api_client.get_carrier(carrier["id"], admin()))
    inquiry = submit_inquiry(carrier, consumer, **(inquiry_overrides or {}))
    report = None
    if inquiry.get("report_id"):
        report = get_success_data(
            api_client.get_report(inquiry["report_id"], make_underwriter_headers(carrier["id"]))
        )
    return {
        "carrier": carrier,
        "consumer": consumer,
        "batch": batch,
        "inquiry": inquiry,
        "report": report,
    }


def list_consumer_active_claims(consumer: dict) -> list:
    data, _meta = validate_paginated(
        api_client.list_consumer_claims(
            consumer["id"], compliance(), params={"status": "ACTIVE"}
        )
    )
    return data


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, compliance()))


def file_dispute(consumer: dict, claim_id: str, **overrides) -> dict:
    """File a dispute as the consumer at the consumer's current version.
    Returns (dispute_data, consumer_after)."""
    fresh = get_success_data(api_client.get_consumer(consumer["id"], compliance()))
    payload = create_dispute_payload(
        loss_claim_id=claim_id,
        expected_consumer_version=fresh["version"],
        **overrides,
    )
    dispute = get_success_data(
        api_client.create_dispute(consumer["id"], payload, make_consumer_headers(consumer["id"]))
    )
    after = get_success_data(api_client.get_consumer(consumer["id"], compliance()))
    return dispute, after


def create_notice_for_report(carrier: dict, report_id: str, **overrides) -> dict:
    payload = create_notice_payload(report_id=report_id, **overrides)
    return get_success_data(
        api_client.create_notice(carrier["id"], payload, make_underwriter_headers(carrier["id"]))
    )


def audit_event_types_for_carrier(carrier_id: str, event_type: str = None) -> list:
    params = {}
    if event_type:
        params["event_type"] = event_type
    data, _meta = validate_paginated(
        api_client.list_carrier_audit_events(carrier_id, compliance(), params=params)
    )
    return [e["event_type"] for e in data]


def audit_event_types_for_consumer(consumer_id: str, event_type: str = None) -> list:
    params = {}
    if event_type:
        params["event_type"] = event_type
    data, _meta = validate_paginated(
        api_client.list_consumer_audit_events(consumer_id, compliance(), params=params)
    )
    return [e["event_type"] for e in data]
