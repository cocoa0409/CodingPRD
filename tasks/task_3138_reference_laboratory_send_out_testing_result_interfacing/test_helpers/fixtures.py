"""Composite setup helpers for the send-out testing workflows.

Every fixture here builds its preconditions from an empty database using only
PRD-declared endpoints, because the harness restarts the API server before every
individual test. Helpers use the framework's lenient ``get_success_data()`` so a
setup failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure deep inside a test.
"""
import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    add_on_payload,
    create_billing_ledger_payload,
    create_catalog_entry_payload,
    create_client_laboratory_payload,
    create_courier_run_payload,
    create_instrument_run_payload,
    create_interface_build_payload,
    create_interface_message_payload,
    create_send_out_order_payload,
    create_specimen_payload,
    create_utilization_advisory_payload,
    enter_results_payload,
    result_line,
    order_line,
)
from .test_users import (
    TEST_USERS,
    make_lab_client_admin_headers,
)

OPS = TEST_USERS["reference_lab_operations_headers"]
CLIENT_ADMIN = TEST_USERS["lab_client_admin_headers"]
COURIER = TEST_USERS["courier_coordinator_headers"]
ACCESSIONING = TEST_USERS["accessioning_technologist_headers"]
MEDTECH = TEST_USERS["medical_technologist_headers"]
IFACE = TEST_USERS["interface_analyst_headers"]
PATHOLOGIST = TEST_USERS["pathologist_headers"]
DIRECTOR = TEST_USERS["medical_director_headers"]
BILLING = TEST_USERS["lab_billing_specialist_headers"]
UTILIZATION = TEST_USERS["utilization_reviewer_headers"]


def _ok(response, label="setup step"):
    if response.status_code >= 400:
        body = response.json() if response.text else {}
        detail = ""
        if body.get("response_type") == "error":
            err = body.get("data", {})
            detail = f": {err.get('error_id')} - {err.get('message')}"
        pytest.fail(f"Setup failed at {label}: HTTP {response.status_code}{detail}")
    return get_success_data(response)


def _created(response, label="setup step"):
    return _ok(response, label)


# =============================================================================
# Tier 1 — primitives
# =============================================================================

def set_clock(current_utc, headers=None):
    """Advance the logical clock (PRD 2.4). Only ReferenceLabOperations may."""
    return _ok(api_client.set_clock(current_utc, headers or OPS), f"set clock to {current_utc}")


def register_client(**overrides):
    """Register a client laboratory; it starts in PENDING_ONBOARDING (PRD 3.1)."""
    payload = create_client_laboratory_payload(**overrides)
    return _created(api_client.create_client_laboratory(payload, OPS), "register client laboratory")


def create_entry(**overrides):
    """Create a catalogue entry in DRAFT (PRD 3.4)."""
    payload = create_catalog_entry_payload(**overrides)
    return _created(api_client.create_catalog_entry(payload, CLIENT_ADMIN), "create catalog entry")


def publish_entry(entry_id, headers=None):
    return _ok(api_client.publish_catalog_entry(entry_id, headers or CLIENT_ADMIN),
               f"publish catalog entry {entry_id}")


def create_and_publish_entry(**overrides):
    entry = create_entry(**overrides)
    publish_entry(entry["id"])
    return entry


def deprecate_entry(entry_id, headers=None):
    return _ok(api_client.deprecate_catalog_entry(entry_id, headers or CLIENT_ADMIN),
               f"deprecate catalog entry {entry_id}")


def open_certified_build(client_id, **overrides):
    """Open an interface build and drive it DRAFT -> IN_BUILD -> CERTIFIED (PRD 3.12)."""
    payload = create_interface_build_payload(client_id, **overrides)
    build = _created(api_client.create_interface_build(payload, IFACE), "open interface build")
    _ok(api_client.start_interface_build(build["id"], IFACE), "start interface build")
    _ok(api_client.certify_interface_build(build["id"], IFACE), "certify interface build")
    return _ok(api_client.get_interface_build(build["id"], IFACE), "read certified interface build")


def open_draft_build(client_id, **overrides):
    payload = create_interface_build_payload(client_id, **overrides)
    return _created(api_client.create_interface_build(payload, IFACE), "open draft interface build")


def book_leg(client_id, **overrides):
    """Book a courier leg; the booking carries the coordinator's observed client version."""
    client = _ok(api_client.get_client_laboratory(client_id, OPS), "read client for courier booking")
    payload = create_courier_run_payload(client_id, client["version"], **overrides)
    return _created(api_client.create_courier_run(payload, COURIER), "book courier leg")


def publish_requirements(client_id, headers=None):
    return _ok(api_client.publish_requirements(client_id, headers or OPS),
               f"publish requirements for {client_id}")


def activate_client(client_id, headers=None):
    """Activate a client laboratory (PRD 3.1).

    Activation is a `LabClientAdmin` or `ReferenceLabOperations` act, and for the
    entity-backed `LabClientAdmin` role the `X-User-ID` is the acting
    `ClientLaboratory` id (PRD 2.1), so the default headers carry that id.
    """
    default = make_lab_client_admin_headers(client_id)
    return _ok(api_client.activate_client(client_id, headers or default),
               f"activate client {client_id}")


def create_specimen_for(client_id, courier_run_id, **overrides):
    payload = create_specimen_payload(client_id, courier_run_id, **overrides)
    return _created(api_client.create_specimen(payload, ACCESSIONING), "record specimen")


def create_order(client_id, specimen_id, lines, **overrides):
    payload = create_send_out_order_payload(client_id, specimen_id, lines, **overrides)
    return _created(api_client.create_send_out_order(payload, ACCESSIONING), "submit send-out order")


def book_run(entry_id, **overrides):
    payload = create_instrument_run_payload(entry_id, **overrides)
    return _created(api_client.create_instrument_run(payload, MEDTECH), "book analyzer window")


def refresh_order(order_id):
    return _ok(api_client.get_send_out_order(order_id, OPS), f"refresh order {order_id}")


def enter_results_for(order_id, lines):
    """Enter result values under the order's current version guard (PRD 3.7)."""
    order = refresh_order(order_id)
    payload = enter_results_payload(order["version"], lines)
    return _ok(api_client.enter_results(order_id, payload, MEDTECH), "enter results")


def release_order(order_id, comment="Ferritin within reference interval."):
    return _ok(api_client.release_results(order_id, comment, PATHOLOGIST), "release results")


# =============================================================================
# Tier 2 — the shared onboarding + intake chain
#
# The single most reused preamble: clock -> client -> published catalogue entry
# -> certified interface build -> courier leg -> published requirements ->
# activated client. Almost every workflow claim starts here.
# =============================================================================

def setup_active_client(client_overrides=None, entry_overrides=None, build_overrides=None,
                        leg_overrides=None, clock="2026-09-01T07:00:00Z"):
    """Return an ACTIVE client with one published entry, a certified build and a leg.

    Keys: client, entry, build, courier_run, admin_headers.
    """
    set_clock(clock)
    client = register_client(**(client_overrides or {}))
    admin_headers = make_lab_client_admin_headers(client["id"])
    entry = create_and_publish_entry(**(entry_overrides or {}))
    build = open_certified_build(client["id"], **(build_overrides or {}))
    courier_run = book_leg(client["id"], **(leg_overrides or {}))
    publish_requirements(client["id"])
    activate_client(client["id"])
    client = _ok(api_client.get_client_laboratory(client["id"], OPS), "re-read activated client")
    return {
        "client": client,
        "entry": entry,
        "build": build,
        "courier_run": courier_run,
        "admin_headers": admin_headers,
    }


def setup_second_published_entry(test_code, **overrides):
    """Publish a second catalogue entry on an already-prepared database."""
    entry = create_and_publish_entry(test_code=test_code, **overrides)
    return entry


def setup_specimen_and_order(scenario, lines=None, specimen_overrides=None,
                             order_overrides=None, run_overrides=None,
                             accession=True, probe=True):
    """Add a specimen and a SUBMITTED order against an ACTIVE-client scenario.

    ``accession`` drives the order to ACCESSIONED through the specimen-level act
    alone. PRD section 3.3 states that this act bubbles upward — "the owning
    send-out order, if still in SUBMITTED status, moves to ACCESSIONED in the
    same transaction" — so a second, explicit call to the order-accession
    endpoint would act on an order that has already left SUBMITTED and is refused
    with ERR_INVALID_STATE. The dedicated order endpoint is exercised only where
    a specimen is already ACCESSIONED when the order is submitted (e.g. a
    re-accessioned specimen), which is the one case where the bubble has nothing
    to move.

    Returns the scenario dict extended with specimen, order and run.
    """
    client = scenario["client"]
    entry = scenario["entry"]
    lines = lines if lines is not None else [order_line(entry["id"], 1)]
    specimen = create_specimen_for(client["id"], scenario["courier_run"]["id"],
                                   **(specimen_overrides or {}))
    if accession:
        # PRD 3.3: the accession action bubbles upward, moving the owning order
        # from SUBMITTED to ACCESSIONED in the same transaction — so the specimen
        # is accessioned while the order is still SUBMITTED.
        _ok(api_client.accession_specimen(specimen["id"], ACCESSIONING), "accession specimen")
    order = create_order(client["id"], specimen["id"], lines, **(order_overrides or {}))
    if accession and order.get("order_status") == "SUBMITTED":
        # A requisition submitted against an already-accessioned specimen has no
        # SUBMITTED predecessor for the bubble to move, so PRD 4's dedicated
        # order-accession endpoint is the act that carries it into ACCESSIONED.
        order = _ok(api_client.accession_order(order["id"], ACCESSIONING), "accession order")
    run = None
    if probe:
        run = book_run(entry["id"], **(run_overrides or {}))
    order = refresh_order(order["id"])
    scenario = dict(scenario)
    scenario.update({"specimen": specimen, "order": order, "run": run})
    return scenario


def start_testing(scenario):
    """Drive specimen -> IN_TESTING and order -> IN_TESTING (PRD 3.6)."""
    specimen = _ok(api_client.begin_testing(scenario["specimen"]["id"], MEDTECH),
                   "begin testing")
    scenario = dict(scenario)
    scenario["specimen"] = specimen
    scenario["order"] = refresh_order(scenario["order"]["id"])
    return scenario


def setup_order_in_testing(client_overrides=None, entry_overrides=None,
                           specimen_overrides=None, order_overrides=None,
                           run_overrides=None, clock=CLOCK_START):
    """Full chain through IN_TESTING with a result entered on the single line."""
    scenario = setup_active_client(client_overrides=client_overrides,
                                   entry_overrides=entry_overrides, clock=clock)
    scenario = setup_specimen_and_order(scenario, specimen_overrides=specimen_overrides,
                                        order_overrides=order_overrides,
                                        run_overrides=run_overrides)
    scenario = start_testing(scenario)
    line = scenario["order"]["test_lines"][0]
    enter_results_for(scenario["order"]["id"], [result_line(line["id"], 250.0)])
    scenario["order"] = refresh_order(scenario["order"]["id"])
    scenario["line"] = line
    return scenario


def setup_released_order(client_overrides=None, entry_overrides=None,
                         specimen_overrides=None, order_overrides=None,
                         run_overrides=None, result_value=250.0,
                         comment="Ferritin within reference interval.",
                         release_clock="2026-09-01T10:00:00Z"):
    """Full chain through RESULT_RELEASED, with billing_status BILLED."""
    scenario = setup_active_client(client_overrides=client_overrides,
                                   entry_overrides=entry_overrides)
    # PRD 3.10: release posts the order's charge to the client's ledger, so the
    # ledger is opened before the release runs. (There is no "open a ledger on
    # release" prose anywhere, so the fixture supplies it explicitly.)
    scenario["ledger"] = open_ledger(scenario["client"]["id"])
    scenario = setup_specimen_and_order(scenario, specimen_overrides=specimen_overrides,
                                        order_overrides=order_overrides,
                                        run_overrides=run_overrides)
    scenario = start_testing(scenario)
    line = scenario["order"]["test_lines"][0]
    enter_results_for(scenario["order"]["id"], [result_line(line["id"], result_value)])
    set_clock(release_clock)
    scenario["order"] = release_order(scenario["order"]["id"], comment)
    scenario["line"] = line
    return scenario


# =============================================================================
# Tier 3 — lifecycle shortcuts and ledger helpers
# =============================================================================

def open_ledger(client_id):
    return _created(api_client.create_billing_ledger(
        create_billing_ledger_payload(client_id), BILLING), "open billing ledger")


def read_ledger(ledger_id):
    return _ok(api_client.get_billing_ledger(ledger_id, BILLING), "read billing ledger")


def read_client(client_id):
    return _ok(api_client.get_client_laboratory(client_id, OPS), "read client laboratory")


def setup_released_order_with_ledger(**overrides):
    """A released, billed order plus the client's ledger, for charge/void pairs."""
    return setup_released_order(**overrides)


def setup_charged_order(**overrides):
    """A released order whose final charge is posted directly to the ledger."""
    scenario = setup_released_order(**overrides)
    scenario["order"] = _ok(api_client.charge_order(scenario["order"]["id"], BILLING),
                            "post order charge")
    return scenario


def void_and_recharge(ledger_id, order_id, amount_cents):
    """The compensating pair: void the charge, then post it again (PRD 3.10)."""
    _ok(api_client.void_charges(ledger_id, order_id, amount_cents, BILLING), "void charges")
    return _ok(api_client.charge_order(order_id, BILLING), "re-charge order")


def setup_order_on_hold(scenario):
    """Hold an order and pull its in-progress lines back to PENDING (PRD 3.11)."""
    order = _ok(api_client.hold_order(scenario["order"]["id"], OPS), "hold order")
    scenario = dict(scenario)
    scenario["order"] = order
    return scenario


def setup_order_with_reflex_chain(critical_result=12.5):
    """A thyrotropin entry whose RESULT_ABOVE_HIGH reflex spawns free-T4.

    Returns a scenario with client, tsh entry, ft4 entry, a thyrotropin order in
    IN_TESTING carrying a critical-high result, and a certified build.
    """
    scenario = setup_active_client(
        entry_overrides={
            "test_code": "TSH_REFLEX",
            "test_name": "Thyrotropin with Reflex to Free T4",
            "base_tat_hours": 8,
            "list_price_cents": 2400,
            "client_price_cents": 2000,
            "floor_price_cents": 900,
            "critical_value_low": 0.01,
            "critical_value_high": 10.0,
            "reflex_test_code": "FT4_FREE",
            "reflex_condition": "RESULT_ABOVE_HIGH",
            "reflex_within_hours": 24,
            "reflex_min_remaining_hours": 6,
            "is_utilization_managed": False,
        })
    ft4 = create_and_publish_entry(
        test_code="FT4_FREE", test_name="Free T4, Serum", base_tat_hours=6,
        list_price_cents=1800, client_price_cents=1500, floor_price_cents=700,
        critical_value_low=None, critical_value_high=None,
        reflex_test_code=None, reflex_condition="NONE",
        min_volume_ml=0.5, is_utilization_managed=False, reflex_min_remaining_hours=6)
    scenario["ft4_entry"] = ft4
    scenario = setup_specimen_and_order(scenario, run_overrides={"instrument_code": "IMM-06"})
    scenario = start_testing(scenario)
    line = scenario["order"]["test_lines"][0]
    enter_results_for(scenario["order"]["id"], [result_line(
        line["id"], critical_result, result_units="mIU/L",
        critical_value_notified_to="Dr. A. Reyes",
        critical_value_notified_at="2026-09-01T09:45:00Z")])
    scenario["order"] = refresh_order(scenario["order"]["id"])
    scenario["line"] = line
    return scenario


def release_and_reflex(scenario, comment="Thyrotropin elevated; reflex free T4 ordered.",
                       release_clock="2026-09-01T10:00:00Z"):
    set_clock(release_clock)
    order = release_order(scenario["order"]["id"], comment)
    scenario = dict(scenario)
    scenario["order"] = order
    child = _ok(api_client.list_send_out_orders(
        OPS, {"reflex_source_order_id": scenario["order"]["id"]}), "list reflex children")
    scenario["reflex_orders"] = child
    return scenario


def queue_result_message(scenario, control_id, message_type="RESULT"):
    """Queue an outbound message against the scenario's certified build (PRD 3.12)."""
    order = refresh_order(scenario["order"]["id"])
    payload = create_interface_message_payload(
        order["id"], scenario["build"]["id"], control_id, order["version"],
        message_type=message_type)
    return _created(api_client.create_interface_message(payload, IFACE), "queue interface message")


def setup_message_validated(scenario, control_id="CTL-9001"):
    scenario["message"] = queue_result_message(scenario, control_id)
    scenario["message"] = _ok(api_client.validate_interface_message(
        scenario["message"]["id"], IFACE), "validate interface message")
    return scenario


# =============================================================================
# Tier 4 — multi-line and threshold-targeting scenarios
# =============================================================================

def setup_multi_line_order(lines_per_entry, entry_specs, release_clock="2026-09-01T20:00:00Z",
                           result_value=200.0, instrument_code="IMM-21"):
    """Build one order carrying ``lines_per_entry[i]`` lines of ``entry_specs[i]``.

    ``entry_specs`` is a list of one dict per distinct test, each with a
    ``test_code`` key plus overrides. Returns the scenario with ``orders``,
    ``entries`` and the line ids keyed by test_code.
    """
    primary = entry_specs[0]
    scenario = setup_active_client(entry_overrides=primary)
    entries = {primary["test_code"]: scenario["entry"]}
    for spec in entry_specs[1:]:
        spec = dict(spec)
        code = spec.pop("test_code")
        entries[code] = create_and_publish_entry(test_code=code, **spec)
    scenario["entries"] = entries

    specimen_overrides = primary.get("_specimen_overrides", {})
    lines = []
    sequence = 1
    for spec, count in zip(entry_specs, lines_per_entry):
        for _ in range(count):
            lines.append(order_line(entries[spec["test_code"]]["id"], sequence))
            sequence += 1
    scenario = setup_specimen_and_order(
        scenario, lines=lines, specimen_overrides=specimen_overrides,
        run_overrides={"instrument_code": instrument_code})
    scenario = start_testing(scenario)
    order = refresh_order(scenario["order"]["id"])
    scenario["order"] = order
    scenario["lines"] = order["test_lines"]
    return scenario


def setup_two_and_three_line_orders(entry_overrides=None, release_clock="2026-09-01T10:00:00Z",
                                    instrument_code="IMM-21"):
    """Two orders on one specimen: one with two ferritin lines, one with three."""
    scenario = setup_active_client(entry_overrides=entry_overrides,
                                   client_overrides={"credit_limit_cents": 5_000_000})
    entry = scenario["entry"]
    client = scenario["client"]
    # PRD 3.6: expected_result_at is the receipt instant plus the effective
    # turnaround, so a 06:00 receipt on a six-hour ROUTINE assay (escalated to
    # RUSH for a 3.0-hour turnaround) pins it at 09:00 and leaves the fixture's
    # 10:00 release with exactly one hour of overrun.
    specimen = create_specimen_for(client["id"], scenario["courier_run"]["id"],
                                   accession_number="ACC-4301", patient_mrn="MRN-4301",
                                   volume_ml=3.0, collection_at="2026-08-31T22:30:00Z",
                                   received_at="2026-09-01T06:00:00Z")
    order_two = create_order(client["id"], specimen["id"],
                             [order_line(entry["id"], 1), order_line(entry["id"], 2)],
                             order_number="REQ-4301", patient_mrn="MRN-4301",
                             client_requested_at="2026-08-31T22:35:00Z",
                             override_utilization_guard=True)
    order_three = create_order(client["id"], specimen["id"],
                               [order_line(entry["id"], 1), order_line(entry["id"], 2),
                                order_line(entry["id"], 3)],
                               order_number="REQ-4302", patient_mrn="MRN-4302",
                               client_requested_at="2026-08-31T22:36:00Z",
                               override_utilization_guard=True)
    # PRD 3.6: the run advances to RUNNING when the clock reaches its start, so
    # the window brackets the fixture clock.
    book_run(entry["id"], instrument_code=instrument_code,
             reserved_start_at="2026-09-01T06:00:00Z", reserved_end_at="2026-09-01T10:00:00Z")
    # PRD section 3.3: the specimen-level act bubbles each SUBMITTED order to
    # ACCESSIONED in the same transaction, so no separate order accession runs.
    _ok(api_client.accession_specimen(specimen["id"], ACCESSIONING), "accession specimen")
    _ok(api_client.begin_testing(specimen["id"], MEDTECH), "begin testing")
    order_two = refresh_order(order_two["id"])
    order_three = refresh_order(order_three["id"])
    enter_results_for(order_two["id"], [
        result_line(order_two["test_lines"][0]["id"], 200.0),
        result_line(order_two["test_lines"][1]["id"], 210.0)])
    enter_results_for(order_three["id"], [
        result_line(order_three["test_lines"][0]["id"], 220.0),
        result_line(order_three["test_lines"][1]["id"], 230.0),
        result_line(order_three["test_lines"][2]["id"], 240.0)])
    set_clock(release_clock)
    scenario = dict(scenario)
    scenario.update({
        "specimen": specimen,
        "order_two": release_order(order_two["id"], "Ferritin pair within reference interval."),
        "order_three": release_order(order_three["id"], "Ferritin panel within reference interval."),
    })
    return scenario


def setup_two_orders_for_utilization(entry_overrides=None,
                                     second_entry_overrides=None,
                                     release_clock="2026-09-01T10:00:00Z",
                                     read_clock="2026-09-01T11:00:00Z"):
    """Three unreleased ferritin lines plus one released thyroglobulin line.

    Returns a scenario whose client exposes a forward count of 4 and a settled
    count of 1, which is the divergence the two utilisation variants produce.
    """
    scenario = setup_active_client(entry_overrides=entry_overrides)
    client = scenario["client"]
    entry = scenario["entry"]
    thyro = create_and_publish_entry(
        test_code="THYROGLOBULIN", test_name="Thyroglobulin, Serum",
        list_price_cents=2600, client_price_cents=2200, floor_price_cents=0,
        critical_value_low=None, critical_value_high=None,
        reflex_test_code=None, reflex_condition="NONE",
        min_volume_ml=1.0, reflex_min_remaining_hours=6,
        is_utilization_managed=False)

    specimen1 = create_specimen_for(client["id"], scenario["courier_run"]["id"],
                                    accession_number="ACC-1001", patient_mrn="MRN-5001")
    order1 = create_order(client["id"], specimen1["id"], [order_line(entry["id"], 1)],
                          order_number="REQ-1001", patient_mrn="MRN-5001")
    book_run(entry["id"])
    _ok(api_client.accession_specimen(specimen1["id"], ACCESSIONING), "accession specimen 1")
    _ok(api_client.accession_order(order1["id"], ACCESSIONING), "accession order 1")
    _ok(api_client.begin_testing(specimen1["id"], MEDTECH), "begin testing specimen 1")
    _ok(api_client.order_add_on_test(order1["id"],
        add_on_payload(entry["id"], 2, "2026-09-01T07:30:00Z"), ACCESSIONING),
        "add-on line 2")
    _ok(api_client.order_add_on_test(order1["id"],
        add_on_payload(entry["id"], 3, "2026-09-01T07:31:00Z"), ACCESSIONING),
        "add-on line 3")

    specimen2 = create_specimen_for(client["id"], scenario["courier_run"]["id"],
                                    accession_number="ACC-1002", patient_mrn="MRN-5002")
    order2 = create_order(client["id"], specimen2["id"], [order_line(thyro["id"], 1)],
                          order_number="REQ-1002", patient_mrn="MRN-5002",
                          client_requested_at="2026-09-01T06:36:00Z")
    book_run(thyro["id"], instrument_code="IMM-02")
    _ok(api_client.accession_specimen(specimen2["id"], ACCESSIONING), "accession specimen 2")
    _ok(api_client.accession_order(order2["id"], ACCESSIONING), "accession order 2")
    _ok(api_client.begin_testing(specimen2["id"], MEDTECH), "begin testing specimen 2")
    enter_results_for(order2["id"], [result_line(order2["test_lines"][0]["id"], 12.0)])
    set_clock(release_clock)
    order2 = release_order(order2["id"], "Thyroglobulin below the assay ceiling.")
    set_clock(read_clock)

    scenario = dict(scenario)
    scenario.update({
        "specimen": specimen1,
        "order": refresh_order(order1["id"]),
        "second_specimen": specimen2,
        "second_order": order2,
        "thyroglobulin_entry": thyro,
    })
    return scenario


def setup_specimen_pair_for_volume_boundary(entry_overrides=None):
    """Two specimens identical but for 0.01 mL of volume, each with one order."""
    scenario = setup_active_client(
        entry_overrides=entry_overrides or {
            "min_volume_ml": 1.0, "stability_hours_ambient": 12,
            "stability_hours_refrigerated": 24, "reflex_condition": "NONE",
            "reflex_min_remaining_hours": 12,
        })
    client = scenario["client"]
    entry = scenario["entry"]
    at_volume = create_specimen_for(client["id"], scenario["courier_run"]["id"],
                                    accession_number="ACC-8301", patient_mrn="MRN-8401",
                                    volume_ml=1.00, collection_at="2026-09-01T05:00:00Z",
                                    received_at="2026-09-01T05:30:00Z")
    order_at = create_order(client["id"], at_volume["id"], [order_line(entry["id"], 1)],
                            order_number="REQ-8301", patient_mrn="MRN-8401",
                            client_requested_at="2026-09-01T05:05:00Z")
    below_volume = create_specimen_for(client["id"], scenario["courier_run"]["id"],
                                       accession_number="ACC-8302", patient_mrn="MRN-8402",
                                       volume_ml=0.99, collection_at="2026-09-01T05:00:00Z",
                                       received_at="2026-09-01T05:30:00Z")
    order_below = create_order(client["id"], below_volume["id"], [order_line(entry["id"], 1)],
                               order_number="REQ-8302", patient_mrn="MRN-8402",
                               client_requested_at="2026-09-01T05:06:00Z")
    scenario = dict(scenario)
    scenario.update({
        "at_volume_specimen": at_volume, "at_volume_order": order_at,
        "below_volume_specimen": below_volume, "below_volume_order": order_below,
    })
    return scenario


def setup_short_window_pair(entry_overrides=None):
    """A specimen carrying a long-window and a short-window line on one order."""
    scenario = setup_active_client(
        entry_overrides=entry_overrides or {
            "stability_hours_ambient": 72, "stability_hours_refrigerated": 168,
        })
    short = create_and_publish_entry(
        test_code="LACTATE_SERUM", test_name="Lactate, Serum",
        stability_hours_ambient=2, stability_hours_refrigerated=24,
        min_volume_ml=1.0, list_price_cents=1400, client_price_cents=1200,
        floor_price_cents=0, critical_value_low=None, critical_value_high=None,
        reflex_test_code=None, reflex_condition="NONE", reflex_min_remaining_hours=0.0,
        is_utilization_managed=False)
    client = scenario["client"]
    entry = scenario["entry"]
    specimen = create_specimen_for(client["id"], scenario["courier_run"]["id"],
                                   accession_number="ACC-3601", patient_mrn="MRN-3601",
                                   volume_ml=2.5, collection_at="2026-08-31T22:30:00Z",
                                   received_at="2026-09-01T00:00:00Z")
    order = create_order(client["id"], specimen["id"],
                         [order_line(entry["id"], 1), order_line(short["id"], 2)],
                         order_number="REQ-3601", patient_mrn="MRN-3601",
                         client_requested_at="2026-08-31T22:35:00Z")
    scenario = dict(scenario)
    scenario.update({
        "short_entry": short, "specimen": specimen, "order": order,
        "short_line": order["test_lines"][1],
    })
    return scenario


# =============================================================================
# Tier 5 — terminal / compensating states
# =============================================================================

def deactivate_client_cleared(client_id, order_ids):
    """Suspend, cancel every live order, then deactivate into terminal INACTIVE."""
    _ok(api_client.suspend_client(client_id, OPS), "suspend client")
    for order_id in order_ids:
        _ok(api_client.cancel_order(order_id, OPS), "cancel order")
    return _ok(api_client.deactivate_client(client_id, OPS), "deactivate client")


def raise_advisory(client_id, entry_id, source_order_id=None,
                   advisory_type="DUPLICATE_ORDER",
                   message="Ferritin repeated within 24 hours for the same patient."):
    payload = create_utilization_advisory_payload(
        client_id, entry_id, message=message, source_order_id=source_order_id,
        advisory_type=advisory_type)
    return _created(api_client.create_utilization_advisory(payload, UTILIZATION),
                    "raise utilization advisory")


def acknowledge_advisory(advisory_id, client_id):
    return _ok(api_client.acknowledge_utilization_advisory(
        advisory_id, make_lab_client_admin_headers(client_id)), "acknowledge advisory")


def resend_advisory_via_repeat_order(scenario, entry_id=None, patient_mrn="MRN-9101",
                                     accession_number="ACC-9101", order_prefix="REQ-9101"):
    """Drive the acknowledged advisory's send-back cycle (PRD 3.9).

    "If the same client subsequently orders the same utilisation-managed test
    again, the acknowledged advisory is re-sent rather than duplicated - it
    returns to SENT and its send_count increments a second time." Two
    requisitions are needed because the repeat guard identifies a prior
    occurrence by the existing lines for the same patient and test.
    """
    client = scenario["client"]
    entry_id = entry_id or scenario["entry"]["id"]
    specimen = _created(api_client.create_specimen(
        create_specimen_payload(client["id"], scenario["courier_run"]["id"],
                                accession_number=accession_number,
                                patient_mrn=patient_mrn), ACCESSIONING),
        "record specimen for the send-back cycle")
    for suffix in ("A", "B"):
        create_order(client["id"], specimen["id"], [order_line(entry_id, 1)],
                     order_number=f"{order_prefix}-{suffix}", patient_mrn=patient_mrn,
                     client_requested_at=CLOCK_START)
    return specimen


def setup_escalated_advisory(scenario, source_order_id=None, patient_mrn=None):
    """Raise, deliver, re-send and escalate an advisory so the guard can fire.

    PRD 3.9 requires the send count to have reached two before escalation, and
    the only PRD path to a second delivery is the acknowledged send-back cycle.
    When the caller wants the escalated advisory to guard a *specific*
    patient_mrn, that patient's own requisitions supply the send-back.
    """
    advisory = raise_advisory(scenario["client"]["id"], scenario["entry"]["id"],
                              source_order_id=source_order_id)
    acknowledge_advisory(advisory["id"], scenario["client"]["id"])
    if patient_mrn is not None:
        resend_advisory_via_repeat_order(scenario, patient_mrn=patient_mrn,
                                         accession_number="ACC-4102",
                                         order_prefix="REQ-4105")
    return _ok(api_client.escalate_utilization_advisory(advisory["id"], OPS),
               "escalate advisory")


def setup_accessioned_specimen_order(scenario, **specimen_overrides):
    """A specimen in ACCESSIONED with one PENDING ferritin line on an ACCESSIONED order."""
    scenario = setup_specimen_and_order(scenario, specimen_overrides=specimen_overrides)
    return scenario