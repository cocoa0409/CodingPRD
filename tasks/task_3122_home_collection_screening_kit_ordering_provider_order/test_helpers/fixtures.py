"""Composite setup helpers.

The harness restarts the API server before every test, so each fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() so a failure surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_adequacy_payload,
    create_cohort_payload,
    create_kit_payload,
    create_order_payload,
    create_outreach_payload,
    create_patient_payload,
    create_program_payload,
    create_provider_payload,
    create_result_payload,
)
from .test_users import TEST_USERS, make_provider_headers

PA = TEST_USERS["program_admin_headers"]
FA = TEST_USERS["fulfillment_agent_headers"]
LT = TEST_USERS["lab_technician_headers"]
NAV = TEST_USERS["navigator_headers"]

CLOCK_DEFAULT = TEST_DEFAULTS["CLOCK_DEFAULT"]


def _ok(resp, label):
    data = get_success_data(resp)
    assert isinstance(data, dict) or isinstance(data, list), (
        f"Setup failed ({label}): {resp.status_code} {resp.text}"
    )
    return data


def set_clock(iso=CLOCK_DEFAULT):
    resp = api_client.set_clock({"to_iso8601": iso}, PA)
    assert resp.status_code == 200, f"Setup failed (set_clock): {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# Tier 1: base entity creation
# ---------------------------------------------------------------------------

def create_patient(**overrides):
    return _ok(api_client.create_patient(create_patient_payload(**overrides), PA), "create patient")


def create_provider(**overrides):
    return _ok(api_client.create_provider(create_provider_payload(**overrides), PA), "create provider")


def create_program(**overrides):
    return _ok(api_client.create_program(create_program_payload(**overrides), PA), "create program")


def create_order(patient, provider, **overrides):
    """Create an order as the ordering provider (entity_backed identity)."""
    return _ok(
        api_client.create_order(
            create_order_payload(patient["id"], provider["id"], **overrides),
            make_provider_headers(provider["id"]),
        ),
        "create order",
    )


def enroll_cohort(program, patient):
    return _ok(
        api_client.enroll_cohort(program["id"], create_cohort_payload(patient["id"]), PA),
        "enroll cohort",
    )


def get_order(order_id):
    return _ok(api_client.get_order(order_id, PA), "get order")


def get_kit(kit_id):
    return _ok(api_client.get_kit(kit_id, PA), "get kit")


def get_cohort(cohort_id):
    return _ok(api_client.get_cohort(cohort_id, PA), "get cohort")


def get_program(program_id):
    return _ok(api_client.get_program(program_id, PA), "get program")


def get_specimen(specimen_id):
    return _ok(api_client.get_specimen(specimen_id, PA), "get specimen")


def get_result(result_id):
    return _ok(api_client.get_result(result_id, PA), "get result")


# ---------------------------------------------------------------------------
# Tier 2: order progression helpers
# ---------------------------------------------------------------------------

def setup_patient_provider(**kwargs):
    """Patient + provider pair. Returns {"patient": ..., "provider": ...}."""
    return {"patient": create_patient(**kwargs.pop("patient_overrides", {})),
            "provider": create_provider(**kwargs.pop("provider_overrides", {}))}


def setup_pending_order(**kwargs):
    """Patient + provider + order in PENDING_ELIGIBILITY."""
    ctx = setup_patient_provider(**kwargs)
    ctx["order"] = create_order(ctx["patient"], ctx["provider"], **kwargs.get("order_overrides", {}))
    return ctx


def setup_eligible_order(**kwargs):
    """Order confirmed ELIGIBLE."""
    ctx = setup_pending_order(**kwargs)
    ctx["order"] = _ok(api_client.confirm_eligibility(ctx["order"]["id"], PA), "confirm eligibility")
    return ctx


def create_kit_for(order):
    """Create the kit against an ELIGIBLE (or RECOLLECTION_REQUESTED) order,
    reading the current version first. Returns the created kit."""
    current = get_order(order["id"])
    kit = _ok(
        api_client.create_kit(
            order["id"], create_kit_payload(current["version"]), FA
        ),
        "create kit",
    )
    return kit


def setup_kit_ordered(**kwargs):
    """Order in KIT_ORDERED with a kit. Adds ctx["kit"]."""
    ctx = setup_eligible_order(**kwargs)
    ctx["kit"] = create_kit_for(ctx["order"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_kit_shipped(**kwargs):
    """Order in KIT_SHIPPED with a shipped kit and 3 SCHEDULED reminders."""
    ctx = setup_kit_ordered(**kwargs)
    ctx["kit"] = _ok(api_client.ship_kit(ctx["kit"]["id"], FA), "ship kit")
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_kit_returned(**kwargs):
    """Order in KIT_RETURNED; kit RETURNED with stabilization window open."""
    ctx = setup_kit_shipped(**kwargs)
    ctx["kit"] = _ok(api_client.return_kit(ctx["kit"]["id"], FA), "return kit")
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_in_lab(**kwargs):
    """Order in IN_LAB with an ACCESSIONED specimen. Adds ctx["specimen"]."""
    ctx = setup_kit_returned(**kwargs)
    ctx["specimen"] = _ok(api_client.accession_specimen(ctx["order"]["id"], LT), "accession specimen")
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_processing(**kwargs):
    """Specimen in PROCESSING (still PENDING adequacy)."""
    ctx = setup_in_lab(**kwargs)
    ctx["specimen"] = _ok(api_client.process_specimen(ctx["specimen"]["id"], LT), "process specimen")
    return ctx


def setup_adequate(**kwargs):
    """Specimen PROCESSING with adequacy ADEQUATE; ready for resulting."""
    ctx = setup_processing(**kwargs)
    ctx["specimen"] = _ok(
        api_client.record_adequacy(ctx["specimen"]["id"], create_adequacy_payload("ADEQUATE"), LT),
        "record adequacy",
    )
    return ctx


def setup_resulted(outcome="NEGATIVE", **kwargs):
    """Fully resulted order. Adds ctx["result"]."""
    ctx = setup_adequate(**kwargs)
    ctx["result"] = _ok(
        api_client.result_specimen(ctx["specimen"]["id"], create_result_payload(outcome), LT),
        "result specimen",
    )
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_inadequate_round(**kwargs):
    """One inadequate cycle completed: order in RECOLLECTION_REQUESTED with
    recollection_round == 1 and the first kit CONSUMED."""
    ctx = setup_in_lab(**kwargs)
    ctx["specimen"] = _ok(
        api_client.record_adequacy(ctx["specimen"]["id"], create_adequacy_payload("INADEQUATE"), LT),
        "record inadequate",
    )
    ctx["first_kit"] = ctx["kit"]
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_replacement_kit(**kwargs):
    """After one inadequate round: replacement kit created; order KIT_ORDERED
    with recollection_round == 1. ctx["kit"] is the replacement kit."""
    ctx = setup_inadequate_round(**kwargs)
    ctx["kit"] = create_kit_for(ctx["order"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_second_in_lab(**kwargs):
    """Replacement kit shipped + returned + accessioned: order IN_LAB with
    recollection_round == 1 and a second ACCESSIONED specimen."""
    ctx = setup_replacement_kit(**kwargs)
    ctx["kit"] = _ok(api_client.ship_kit(ctx["kit"]["id"], FA), "ship replacement kit")
    ctx["kit"] = _ok(api_client.return_kit(ctx["kit"]["id"], FA), "return replacement kit")
    ctx["specimen"] = _ok(api_client.accession_specimen(ctx["order"]["id"], LT), "accession specimen 2")
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_round_exhausted_in_lab(**kwargs):
    """Two inadequate cycles completed (recollection_round == 2), then a third
    kit created via the recollection path, shipped, returned, accessioned.
    Order IN_LAB with recollection_round == 2."""
    ctx = setup_second_in_lab(**kwargs)
    # second INADEQUATE -> round becomes 2
    ctx["specimen"] = _ok(
        api_client.record_adequacy(ctx["specimen"]["id"], create_adequacy_payload("INADEQUATE"), LT),
        "record inadequate 2",
    )
    ctx["order"] = get_order(ctx["order"]["id"])
    # third kit via recollection path
    ctx["kit"] = create_kit_for(ctx["order"])
    ctx["kit"] = _ok(api_client.ship_kit(ctx["kit"]["id"], FA), "ship kit 3")
    ctx["kit"] = _ok(api_client.return_kit(ctx["kit"]["id"], FA), "return kit 3")
    ctx["specimen"] = _ok(api_client.accession_specimen(ctx["order"]["id"], LT), "accession specimen 3")
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: program / cohort composites
# ---------------------------------------------------------------------------

def setup_program_with_cohort(program_overrides=None, patient_overrides=None):
    """Program + patient + enrolled cohort."""
    program = create_program(**(program_overrides or {}))
    patient = create_patient(**(patient_overrides or {}))
    cohort = enroll_cohort(program, patient)
    return {"program": program, "patient": patient, "cohort": cohort}


def setup_program_order_in_lab(program_overrides=None):
    """PUSH program with one cohort member whose order is IN_LAB with an
    ACCESSIONED specimen (kit shipped + returned)."""
    base = setup_program_with_cohort(program_overrides=program_overrides)
    provider = create_provider()
    order = _ok(
        api_client.create_order(
            create_order_payload(
                base["patient"]["id"], provider["id"],
                program_id=base["program"]["id"], cohort_id=base["cohort"]["id"],
            ),
            make_provider_headers(provider["id"]),
        ),
        "create order",
    )
    order = _ok(api_client.confirm_eligibility(order["id"], PA), "confirm eligibility")
    kit = create_kit_for(order)
    kit = _ok(api_client.ship_kit(kit["id"], FA), "ship kit")
    kit = _ok(api_client.return_kit(kit["id"], FA), "return kit")
    specimen = _ok(api_client.accession_specimen(order["id"], LT), "accession specimen")
    base.update({
        "provider": provider,
        "order": get_order(order["id"]),
        "kit": kit,
        "specimen": specimen,
    })
    return base


def result_cohort_order(ctx, outcome="NEGATIVE"):
    """Drive a ctx built by setup_program_order_in_lab to RESULTED."""
    _ok(api_client.process_specimen(ctx["specimen"]["id"], LT), "process specimen")
    _ok(
        api_client.record_adequacy(ctx["specimen"]["id"], create_adequacy_payload("ADEQUATE"), LT),
        "record adequacy",
    )
    result = _ok(
        api_client.result_specimen(ctx["specimen"]["id"], create_result_payload(outcome), LT),
        "result specimen",
    )
    return result
