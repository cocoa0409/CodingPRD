"""Composite state builders.

Every builder here drives the public API only, and every one of them is called
from inside an individual test's own fixture: the harness relaunches the server
before each test, so no state may be shared between tests.

Two rules shape the phasing of these helpers:

* the three stale-read guards of PRD 2.6 (`expected_raw_mix_design_version`,
  `expected_clinker_silo_version`, `expected_mill_certificate_version`) are
  echoed from a *fresh* read taken immediately before the committing write, so a
  builder's own earlier hop can never invalidate its own later hop;
* the three two-person controls of PRD 2.7 are satisfied by handing the upstream
  act and the downstream adjudication to two different ``X-User-ID`` literals.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_START
from .test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    ENV_HEADERS,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)
from .types import Headers, Payload, Row

# Reference instants used by the canonical chain.
RUN_WINDOW_START = "2026-08-01T00:00:00Z"
RUN_WINDOW_END = "2026-08-01T12:00:00Z"
ORDER_WINDOW_START = "2026-08-05T06:00:00Z"
ORDER_WINDOW_END = "2026-08-05T08:00:00Z"

# Additions moisture-compensated so that the pile's dry basis reproduces the
# design's dry mass fractions: 836.73 as-received limestone at 2% moisture gives
# 820.00 dry tonnes and 204.55 as-received clay at 12% gives 180.00, so the bed
# holds 1000.00 dry tonnes in the design's own 82 / 18 proportions and the pile's
# lsf_deviation stays inside the default pile_lsf_tolerance (PRD 3.2).
REFERENCE_ADDITIONS = ((836.73, 2.0), (204.55, 12.0))
REFERENCE_PILE_DRY_TONNES = 1000.00


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------
def data_of(response: Any) -> Any:
    """Unwrap a success envelope leniently, for setup calls."""
    return get_success_data(response)


def set_clock(api: Any, to_iso8601: str, headers: Headers = ADMIN_HEADERS) -> Row:
    """Move the logical clock (PRD 2.4)."""
    return data_of(api.set_clock(to_iso8601, headers))


def reset_clock(api: Any, headers: Headers = ADMIN_HEADERS) -> Row:
    return set_clock(api, CLOCK_START, headers)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def create_plant(api: Any, headers: Headers = ADMIN_HEADERS, **overrides: Any) -> Row:
    return data_of(api.create_plant(f.plant_payload(**overrides), headers))


def create_raw_materials(
    api: Any, headers: Headers = ENGINEER_HEADERS, suffix: str = ""
) -> Dict[str, Row]:
    """Register the limestone / clay / iron ore triple the reference recipe uses."""
    return {
        "limestone": data_of(
            api.create_raw_material(f.limestone_payload(f"LS-1{suffix}"), headers)
        ),
        "clay": data_of(api.create_raw_material(f.clay_payload(f"CL-1{suffix}"), headers)),
        "iron_ore": data_of(
            api.create_raw_material(f.iron_ore_payload(f"IR-1{suffix}"), headers)
        ),
    }


def create_fuels(
    api: Any, headers: Headers = ENV_HEADERS, suffix: str = ""
) -> Dict[str, Row]:
    """Register the four reference fuels: two conventional, two alternative."""
    return {
        "gas": data_of(api.create_fuel(f.natural_gas_payload(f"GAS-1{suffix}"), headers)),
        "coal": data_of(api.create_fuel(f.coal_payload(f"COAL-1{suffix}"), headers)),
        "rdf": data_of(api.create_fuel(f.rdf_payload(f"RDF-1{suffix}"), headers)),
        "tdf": data_of(api.create_fuel(f.tdf_payload(f"TDF-1{suffix}"), headers)),
    }


def create_kiln(
    api: Any, plant_id: str, headers: Headers = ADMIN_HEADERS, **overrides: Any
) -> Row:
    return data_of(api.create_kiln(f.kiln_payload(plant_id, **overrides), headers))


def create_clinker_silo(
    api: Any, plant_id: str, headers: Headers = ADMIN_HEADERS, **overrides: Any
) -> Row:
    return data_of(api.create_silo(f.clinker_silo_payload(plant_id, **overrides), headers))


def create_cement_silo(
    api: Any, plant_id: str, headers: Headers = ADMIN_HEADERS, **overrides: Any
) -> Row:
    return data_of(api.create_silo(f.cement_silo_payload(plant_id, **overrides), headers))


def create_customer(
    api: Any, headers: Headers = LOGISTICS_HEADERS, **overrides: Any
) -> Row:
    return data_of(api.create_customer(f.customer_payload(**overrides), headers))


# ---------------------------------------------------------------------------
# Raw mix designs
# ---------------------------------------------------------------------------
def reference_components(materials: Dict[str, Row]) -> List[Payload]:
    """The 82 / 18 dry-basis recipe whose as-designed LSF is 96.98."""
    return [
        f.component(materials["limestone"]["id"], 82.00),
        f.component(materials["clay"]["id"], 18.00),
    ]


def create_draft_design(
    api: Any,
    plant_id: str,
    materials: Dict[str, Row],
    headers: Headers = ENGINEER_HEADERS,
    components: Optional[List[Payload]] = None,
    **overrides: Any,
) -> Row:
    """Author a DRAFT design. The reference recipe's as-designed LSF of 96.98 sits
    0.02 from the 97.00 target, well inside the default module_tolerance_lsf."""
    payload = f.design_payload(
        plant_id,
        components if components is not None else reference_components(materials),
        **overrides,
    )
    return data_of(api.create_design(payload, headers))


def create_approved_design(
    api: Any,
    plant_id: str,
    materials: Dict[str, Row],
    author_headers: Headers = ENGINEER_HEADERS,
    approver_headers: Headers = QUALITY_HEADERS,
    components: Optional[List[Payload]] = None,
    **overrides: Any,
) -> Row:
    """DRAFT -> SUBMITTED -> APPROVED, with two distinct user ids for PRD 2.7."""
    design = create_draft_design(
        api, plant_id, materials, author_headers, components, **overrides
    )
    data_of(api.submit_design(design["id"], author_headers))
    return data_of(api.approve_design(design["id"], approver_headers))


# ---------------------------------------------------------------------------
# Blended piles
# ---------------------------------------------------------------------------
def create_open_pile(
    api: Any,
    plant_id: str,
    design_id: str,
    headers: Headers = ENGINEER_HEADERS,
    pile_code: str = "PA",
) -> Row:
    """Open a pile, echoing the design version as read immediately beforehand."""
    design = data_of(api.get_design(design_id, headers))
    return data_of(
        api.create_pile(
            f.pile_payload(plant_id, design_id, design["version"], pile_code), headers
        )
    )


def add_reference_additions(
    api: Any,
    pile_id: str,
    materials: Dict[str, Row],
    headers: Headers = ENGINEER_HEADERS,
    additions: Any = REFERENCE_ADDITIONS,
) -> Row:
    """Feed limestone, clay and iron ore onto the bed in that order."""
    order = ("limestone", "clay", "iron_ore")
    row: Row = {}
    for key, (tonnes, moisture) in zip(order, additions):
        row = data_of(
            api.add_pile_addition(
                pile_id,
                f.addition_payload(materials[key]["id"], tonnes, moisture),
                headers,
            )
        )
    return row


def create_sealed_pile(
    api: Any,
    plant_id: str,
    design_id: str,
    materials: Dict[str, Row],
    headers: Headers = ENGINEER_HEADERS,
    pile_code: str = "PA",
    additions: Any = REFERENCE_ADDITIONS,
) -> Row:
    pile = create_open_pile(api, plant_id, design_id, headers, pile_code)
    add_reference_additions(api, pile["id"], materials, headers, additions)
    return data_of(api.seal_pile(pile["id"], headers))


# ---------------------------------------------------------------------------
# Trial burns
# ---------------------------------------------------------------------------
def create_authorized_burn_test(
    api: Any,
    plant_id: str,
    fuel_id: str,
    requested_max_tsr_pct: float = 25.00,
    authorized_max_tsr_pct: float = 25.00,
    valid_days: int = 30,
    recorder_headers: Headers = LAB_HEADERS,
    adjudicator_headers: Headers = ENV_HEADERS,
) -> Row:
    """REQUESTED -> IN_PROGRESS -> RESULT_RECORDED -> AUTHORIZED.

    The recording technician and the adjudicating officer are two different user
    ids, as the trial-burn two-person control of PRD 2.7 requires.
    """
    burn = data_of(
        api.create_burn_test(
            f.burn_test_payload(plant_id, fuel_id, requested_max_tsr_pct, valid_days),
            ENV_HEADERS,
        )
    )
    data_of(api.start_burn_test(burn["id"], recorder_headers))
    data_of(
        api.record_burn_test_result(burn["id"], f.burn_result_payload(), recorder_headers)
    )
    return data_of(
        api.adjudicate_burn_test(
            burn["id"],
            f.adjudication_payload("AUTHORIZED", authorized_max_tsr_pct),
            adjudicator_headers,
        )
    )


# ---------------------------------------------------------------------------
# Kiln runs
# ---------------------------------------------------------------------------
IN_SPEC_FREE_LIME = 1.40
OUT_OF_SPEC_FREE_LIME = 1.62


def create_scheduled_run(
    api: Any,
    kiln_id: str,
    pile_id: str,
    clinker_silo_id: str,
    headers: Headers = OPERATOR_HEADERS,
    window_start: str = RUN_WINDOW_START,
    window_end: str = RUN_WINDOW_END,
) -> Row:
    return data_of(
        api.create_kiln_run(
            f.kiln_run_payload(
                kiln_id, pile_id, clinker_silo_id, window_start, window_end
            ),
            headers,
        )
    )


def create_burning_run(
    api: Any,
    kiln_id: str,
    pile_id: str,
    clinker_silo_id: str,
    headers: Headers = OPERATOR_HEADERS,
    window_start: str = RUN_WINDOW_START,
    window_end: str = RUN_WINDOW_END,
) -> Row:
    """Schedule and light a run; the clock must already sit inside the window."""
    run = create_scheduled_run(
        api, kiln_id, pile_id, clinker_silo_id, headers, window_start, window_end
    )
    return data_of(api.light_kiln_run(run["id"], headers))


def charge(
    api: Any,
    run_id: str,
    fuel_id: str,
    tonnes: float,
    headers: Headers = OPERATOR_HEADERS,
) -> Row:
    return data_of(api.charge_fuel(run_id, f.fuel_charge_payload(fuel_id, tonnes), headers))


def create_completed_run(
    api: Any,
    kiln_id: str,
    pile_id: str,
    clinker_silo_id: str,
    fuel_id: str,
    tonnes: float = 45.00,
    headers: Headers = OPERATOR_HEADERS,
    window_start: str = RUN_WINDOW_START,
    window_end: str = RUN_WINDOW_END,
) -> Row:
    """Light, charge one fuel delivery, advance the clock to ``window_end``, complete."""
    run = create_burning_run(
        api, kiln_id, pile_id, clinker_silo_id, headers, window_start, window_end
    )
    charge(api, run["id"], fuel_id, tonnes, headers)
    set_clock(api, window_end)
    return data_of(api.complete_kiln_run(run["id"], headers))


def record_free_lime(
    api: Any,
    run_id: str,
    value: float = IN_SPEC_FREE_LIME,
    headers: Headers = LAB_HEADERS,
) -> Row:
    return data_of(
        api.create_lab_test(f.lab_test_payload("FREE_LIME", value, kiln_run_id=run_id), headers)
    )


def create_released_run(
    api: Any,
    kiln_id: str,
    pile_id: str,
    clinker_silo_id: str,
    fuel_id: str,
    tonnes: float = 45.00,
    free_lime_value: float = IN_SPEC_FREE_LIME,
    operator_headers: Headers = OPERATOR_HEADERS,
    lab_headers: Headers = LAB_HEADERS,
    quality_headers: Headers = QUALITY_HEADERS,
    window_start: str = RUN_WINDOW_START,
    window_end: str = RUN_WINDOW_END,
) -> Row:
    """Complete a run, record an in-specification free-lime reading, release it."""
    run = create_completed_run(
        api,
        kiln_id,
        pile_id,
        clinker_silo_id,
        fuel_id,
        tonnes,
        operator_headers,
        window_start,
        window_end,
    )
    record_free_lime(api, run["id"], free_lime_value, lab_headers)
    return data_of(api.release_clinker(run["id"], quality_headers))


# ---------------------------------------------------------------------------
# Cement batches
# ---------------------------------------------------------------------------
def create_planned_batch(
    api: Any,
    plant_id: str,
    clinker_silo_id: str,
    cement_silo_id: str,
    headers: Headers = ENGINEER_HEADERS,
    **overrides: Any,
) -> Row:
    """Plan a batch, echoing the clinker silo version as read immediately beforehand."""
    silo = data_of(api.get_silo(clinker_silo_id, headers))
    return data_of(
        api.create_cement_batch(
            f.cement_batch_payload(
                plant_id, clinker_silo_id, cement_silo_id, silo["version"], **overrides
            ),
            headers,
        )
    )


def create_ground_batch(
    api: Any,
    plant_id: str,
    clinker_silo_id: str,
    cement_silo_id: str,
    engineer_headers: Headers = ENGINEER_HEADERS,
    operator_headers: Headers = OPERATOR_HEADERS,
    **overrides: Any,
) -> Row:
    batch = create_planned_batch(
        api, plant_id, clinker_silo_id, cement_silo_id, engineer_headers, **overrides
    )
    data_of(api.start_grinding(batch["id"], operator_headers))
    return data_of(api.finish_grinding(batch["id"], operator_headers))


def record_blaine(
    api: Any, batch_id: str, value: int = 400, headers: Headers = LAB_HEADERS
) -> Row:
    return data_of(
        api.create_lab_test(f.lab_test_payload("BLAINE", value, cement_batch_id=batch_id), headers)
    )


def record_strength(
    api: Any, batch_id: str, value: float = 45.00, headers: Headers = LAB_HEADERS
) -> Row:
    return data_of(
        api.create_lab_test(
            f.lab_test_payload("COMPRESSIVE_STRENGTH_28D", value, cement_batch_id=batch_id),
            headers,
        )
    )


def create_qualified_batch(
    api: Any,
    plant_id: str,
    clinker_silo_id: str,
    cement_silo_id: str,
    engineer_headers: Headers = ENGINEER_HEADERS,
    operator_headers: Headers = OPERATOR_HEADERS,
    lab_headers: Headers = LAB_HEADERS,
    blaine_value: int = 400,
    strength_value: float = 45.00,
    **overrides: Any,
) -> Row:
    """Grind a batch and pass both laboratory branches so the join fires."""
    batch = create_ground_batch(
        api,
        plant_id,
        clinker_silo_id,
        cement_silo_id,
        engineer_headers,
        operator_headers,
        **overrides,
    )
    record_blaine(api, batch["id"], blaine_value, lab_headers)
    record_strength(api, batch["id"], strength_value, lab_headers)
    return data_of(api.get_cement_batch(batch["id"], engineer_headers))


# ---------------------------------------------------------------------------
# Mill certificates and loadout orders
# ---------------------------------------------------------------------------
def create_draft_certificate(
    api: Any,
    batch_id: str,
    customer_id: str,
    certified_tonnes: float,
    headers: Headers = QUALITY_HEADERS,
) -> Row:
    return data_of(
        api.create_mill_certificate(
            f.mill_certificate_payload(batch_id, customer_id, certified_tonnes), headers
        )
    )


def create_issued_certificate(
    api: Any,
    batch_id: str,
    customer_id: str,
    certified_tonnes: float,
    drafter_headers: Headers = QUALITY_HEADERS,
    issuer_headers: Headers = QUALITY_HEADERS,
) -> Row:
    """Draft then issue. The issuing user id differs from the technician who
    recorded the batch's newest 28-day strength test, as PRD 2.7 requires."""
    certificate = create_draft_certificate(
        api, batch_id, customer_id, certified_tonnes, drafter_headers
    )
    return data_of(api.issue_mill_certificate(certificate["id"], issuer_headers))


def create_reserved_order(
    api: Any,
    customer_id: str,
    cement_silo_id: str,
    certificate_id: str,
    headers: Headers = LOGISTICS_HEADERS,
    **overrides: Any,
) -> Row:
    """Reserve an appointment, echoing the certificate version read immediately before."""
    certificate = data_of(api.get_mill_certificate(certificate_id, headers))
    return data_of(
        api.create_loadout_order(
            f.loadout_order_payload(
                customer_id,
                cement_silo_id,
                certificate_id,
                certificate["version"],
                **overrides,
            ),
            headers,
        )
    )


# ---------------------------------------------------------------------------
# Composite environments
# ---------------------------------------------------------------------------
def plant_environment(api: Any, suffix: str = "") -> Dict[str, Any]:
    """Plant, catalogue, kiln and the two silos: the base every chain starts from."""
    plant = create_plant(api)
    materials = create_raw_materials(api, suffix=suffix)
    fuels = create_fuels(api, suffix=suffix)
    return {
        "plant": plant,
        "plant_id": plant["id"],
        "materials": materials,
        "fuels": fuels,
        "kiln": create_kiln(api, plant["id"]),
        "clinker_silo": create_clinker_silo(api, plant["id"]),
        "cement_silo": create_cement_silo(api, plant["id"]),
    }


def released_clinker_environment(
    api: Any, fuel_key: str = "gas", tonnes: float = 45.00, suffix: str = ""
) -> Dict[str, Any]:
    """A plant environment carrying one released run, so its clinker is available."""
    env = plant_environment(api, suffix)
    env["design"] = create_approved_design(api, env["plant_id"], env["materials"])
    env["pile"] = create_sealed_pile(
        api, env["plant_id"], env["design"]["id"], env["materials"]
    )
    env["run"] = create_released_run(
        api,
        env["kiln"]["id"],
        env["pile"]["id"],
        env["clinker_silo"]["id"],
        env["fuels"][fuel_key]["id"],
        tonnes,
    )
    return env


def qualified_cement_environment(api: Any, suffix: str = "", **batch_overrides: Any) -> Dict[str, Any]:
    """A released run plus a TYPE_IL batch ground and passed through both branches."""
    env = released_clinker_environment(api, suffix=suffix)
    env["batch"] = create_qualified_batch(
        api,
        env["plant_id"],
        env["clinker_silo"]["id"],
        env["cement_silo"]["id"],
        **batch_overrides,
    )
    return env


def certificate_chain(api: Any, suffix: str = "", order_tonnes: float = 120.00) -> Dict[str, Any]:
    """The canonical chain: released clinker, a qualified TYPE_IL batch, a customer,
    an issued certificate for the whole batch and one reserved loadout order."""
    env = qualified_cement_environment(api, suffix=suffix)
    env["customer"] = create_customer(api)
    env["certificate"] = create_issued_certificate(
        api,
        env["batch"]["id"],
        env["customer"]["id"],
        env["batch"]["cement_tonnes"],
    )
    env["order"] = create_reserved_order(
        api,
        env["customer"]["id"],
        env["cement_silo"]["id"],
        env["certificate"]["id"],
        tonnes=order_tonnes,
    )
    return env
