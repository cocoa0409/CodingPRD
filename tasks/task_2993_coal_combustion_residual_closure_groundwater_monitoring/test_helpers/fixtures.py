"""World builders that assemble state through the public API only.

The harness restarts the server before every individual test, so each test
begins against an empty database and must build whatever it needs by calling
the contract. These helpers are the shared vocabulary for doing that, arranged
from the cheapest tier (the clock and the roster) to the most expensive (a unit
already in post-closure care).

Every helper reads a parent's current ``version`` immediately before the write
that quotes it, so a helper can be called twice in a row without its own second
step quoting a version its own first step has already superseded.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import ApiClient
from .constants import (
    ASD_DECISION_ACCEPT,
    BASE_CLOCK_INSTANT,
    EVENT_TYPE_BACKGROUND,
    EVENT_TYPE_DETECTION,
    MAX_LIMIT,
    PARAM_SULFATE,
    WELL_ROLE_BACKGROUND,
    WELL_ROLE_DOWNGRADIENT,
)
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    REGULATOR_HEADERS,
    UTILITY_ADMIN_HEADERS,
    make_engineer_headers,
    make_hydrogeologist_headers,
    make_statistical_reviewer_headers,
)
from .types import Json, World

# The four background sampling dates used by every helper that builds a
# background data set. Each is at least 90 days after the one before it, and all
# four fall inside the standard 2025 background window.
BACKGROUND_DATES: Tuple[str, str, str, str] = (
    "2025-01-15",
    "2025-04-20",
    "2025-07-25",
    "2025-10-30",
)

# A detection round dated strictly after the standard window's end, so it is
# eligible as a comparison measurement rather than as background.
DETECTION_DATE = "2026-02-10"

# The standard interwell background quartet and the detection value that
# exceeds the limit it produces.
BACKGROUND_SULFATE_VALUES: Tuple[float, float, float, float] = (0.5000, 0.6000, 0.5500, 0.5800)
DETECTION_SULFATE_VALUE = 0.9000


# ── Tier 1: the clock and page reading ────────────────────────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> Json:
    """Move the logical clock, which is a UtilityAdmin capability."""
    return get_success_data(api.set_clock(factories.clock_payload(to_iso8601), UTILITY_ADMIN_HEADERS))


def reset_clock(api: ApiClient) -> Json:
    """Park the clock explicitly on the contract's documented starting instant."""
    return set_clock(api, BASE_CLOCK_INSTANT)


def rows(response) -> List[Json]:
    """The rows of a paginated list response, discarding the meta block."""
    page, _meta = validate_paginated(response)
    return page


def page(response) -> Tuple[List[Json], Json]:
    """Both halves of a paginated list response."""
    return validate_paginated(response)


# ── Tier 2: the professional roster ───────────────────────────────────────


def register_professional(api: ApiClient, payload: Dict[str, Any]) -> Json:
    return get_success_data(api.create_professional(payload, UTILITY_ADMIN_HEADERS))


def seed_roster(api: ApiClient) -> World:
    """Register one licensee per discipline and return their ids and headers.

    Four disciplines and five records: the contract's two-signature control on a
    closure plan needs two distinct CIVIL identities, so a second civil engineer
    is registered alongside the first.

    The roster's ``license_number`` values are fixed literals and the contract
    makes a licence number unique within its licensing state, so a second call
    of this helper against the same server must reuse the records the first call
    minted rather than re-register them. A test that builds two units therefore
    reads the roster first and only registers the licensees that are missing.
    """
    already = {
        row["license_number"]: row
        for row in rows(api.list_professionals(UTILITY_ADMIN_HEADERS, {"limit": MAX_LIMIT}))
    }

    def ensure(payload: Dict[str, Any]) -> Json:
        found = already.get(payload["license_number"])
        if found is not None:
            return found
        record = register_professional(api, payload)
        already[record["license_number"]] = record
        return record

    geotech = ensure(factories.geotechnical_engineer_payload())
    civil = ensure(factories.civil_engineer_payload())
    hydro = ensure(factories.hydrogeologist_payload())
    stats = ensure(factories.statistician_payload())
    second_civil = ensure(factories.second_civil_engineer_payload())
    return {
        "geotech": geotech,
        "civil": civil,
        "hydro": hydro,
        "stats": stats,
        "second_civil": second_civil,
        "geotech_id": geotech["id"],
        "civil_id": civil["id"],
        "hydro_id": hydro["id"],
        "stats_id": stats["id"],
        "second_civil_id": second_civil["id"],
        "geotech_headers": make_engineer_headers(geotech["id"]),
        "civil_headers": make_engineer_headers(civil["id"]),
        "second_civil_headers": make_engineer_headers(second_civil["id"]),
        "hydro_headers": make_hydrogeologist_headers(hydro["id"]),
        "stats_headers": make_statistical_reviewer_headers(stats["id"]),
    }


# ── Tier 3: units and their cascade-created monitoring programs ───────────


def create_unit(api: ApiClient, unit_code: str = "IMP-0101", **overrides: Any) -> Json:
    payload = factories.unit_payload(unit_code, **overrides)
    return get_success_data(api.create_unit(payload, UTILITY_ADMIN_HEADERS))


def read_unit(api: ApiClient, unit_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_unit(unit_id, headers or UTILITY_ADMIN_HEADERS))


def unit_version(api: ApiClient, unit_id: str) -> int:
    """The unit's current version, read fresh for an OCC-guarded write."""
    return read_unit(api, unit_id)["version"]


def read_program(api: ApiClient, program_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_program(program_id, headers or UTILITY_ADMIN_HEADERS))


def seed_unit(api: ApiClient, unit_code: str = "IMP-0101", **overrides: Any) -> World:
    """A roster plus one registered unit and the program registration minted."""
    world = seed_roster(api)
    unit = create_unit(api, unit_code, **overrides)
    world["unit"] = unit
    world["unit_id"] = unit["id"]
    world["program_id"] = unit["monitoring_program_id"]
    return world


# ── Tier 4: the monitoring network ────────────────────────────────────────


def install_well(
    api: ApiClient,
    unit_id: str,
    hydro_headers: Dict[str, str],
    well_code: str,
    well_role: str = WELL_ROLE_DOWNGRADIENT,
    **overrides: Any,
) -> Json:
    payload = factories.well_payload(unit_id, well_code, well_role, **overrides)
    return get_success_data(api.create_well(payload, hydro_headers))


def install_standard_network(
    api: ApiClient,
    unit_id: str,
    hydro_headers: Dict[str, str],
    background_codes: Sequence[str] = ("BG-01",),
    downgradient_codes: Sequence[str] = ("DG-01", "DG-02", "DG-03"),
) -> Dict[str, Json]:
    """Install the minimum certifiable network: one background, three downgradient.

    Screen intervals are staggered per well so that a retrieval test can tell
    the wells apart by their stored interval alone.
    """
    wells: Dict[str, Json] = {}
    for index, code in enumerate(background_codes):
        wells[code] = install_well(
            api,
            unit_id,
            hydro_headers,
            code,
            WELL_ROLE_BACKGROUND,
            screen_top_ft=22.00 + index,
            screen_bottom_ft=42.00 + index,
        )
    for index, code in enumerate(downgradient_codes):
        wells[code] = install_well(
            api,
            unit_id,
            hydro_headers,
            code,
            WELL_ROLE_DOWNGRADIENT,
            screen_top_ft=20.00 + index,
            screen_bottom_ft=40.00 + index,
        )
    return wells


def configure_program(
    api: ApiClient, program_id: str, hydro_headers: Dict[str, str], **overrides: Any
) -> Json:
    payload = factories.program_config_payload(**overrides)
    return get_success_data(api.patch_program(program_id, payload, hydro_headers))


def certify_network(
    api: ApiClient, program_id: str, hydro_headers: Dict[str, str], certified_on: str = "2026-01-05"
) -> Json:
    payload = factories.certify_network_payload(certified_on)
    return get_success_data(api.certify_network(program_id, payload, hydro_headers))


def seed_certified_network(
    api: ApiClient,
    unit_code: str = "IMP-0101",
    background_codes: Sequence[str] = ("BG-01",),
    downgradient_codes: Sequence[str] = ("DG-01", "DG-02", "DG-03"),
    **unit_overrides: Any,
) -> World:
    """A unit whose network is installed, configured and certified.

    This is the gate every sampling round and every evaluation sits behind, so
    most monitoring tests start here.
    """
    world = seed_unit(api, unit_code, **unit_overrides)
    world["wells"] = install_standard_network(
        api, world["unit_id"], world["hydro_headers"], background_codes, downgradient_codes
    )
    configure_program(api, world["program_id"], world["hydro_headers"])
    world["program"] = certify_network(api, world["program_id"], world["hydro_headers"])
    return world


# ── Tier 5: sampling rounds and laboratory data ───────────────────────────


def open_round(
    api: ApiClient,
    program_id: str,
    hydro_headers: Dict[str, str],
    event_code: str,
    sampled_on: str,
    event_type: str = EVENT_TYPE_BACKGROUND,
) -> Json:
    payload = factories.sampling_event_payload(program_id, event_code, sampled_on, event_type)
    return get_success_data(api.create_sampling_event(payload, hydro_headers))


def read_round(api: ApiClient, event_id: str, headers: Dict[str, str]) -> Json:
    return get_success_data(api.get_sampling_event(event_id, headers))


def append_result(
    api: ApiClient,
    event_id: str,
    well_id: str,
    concentration: float,
    hydro_headers: Dict[str, str],
    parameter_code: str = PARAM_SULFATE,
    **overrides: Any,
) -> Json:
    """Append one laboratory result, quoting the round's version read just now.

    The version is fetched immediately before the append rather than being
    carried in from an earlier step, so repeated calls never quote a version
    that a previous call of this same helper has already bumped.
    """
    version = read_round(api, event_id, hydro_headers)["version"]
    payload = factories.result_payload(
        event_id, well_id, concentration, version, parameter_code, **overrides
    )
    return get_success_data(api.create_analytical_result(payload, hydro_headers))


def close_round(
    api: ApiClient, event_id: str, hydro_headers: Dict[str, str], validated_on: str
) -> Json:
    payload = factories.validate_event_payload(validated_on)
    return get_success_data(api.validate_sampling_event(event_id, payload, hydro_headers))


def validated_round(
    api: ApiClient,
    program_id: str,
    hydro_headers: Dict[str, str],
    event_code: str,
    sampled_on: str,
    results: Sequence[Tuple[str, float]],
    event_type: str = EVENT_TYPE_BACKGROUND,
    parameter_code: str = PARAM_SULFATE,
    validated_on: Optional[str] = None,
) -> Json:
    """Open a round, append every (well_id, value) pair, then validate it."""
    event = open_round(api, program_id, hydro_headers, event_code, sampled_on, event_type)
    for well_id, value in results:
        append_result(api, event["id"], well_id, value, hydro_headers, parameter_code)
    return close_round(api, event["id"], hydro_headers, validated_on or sampled_on)


def seed_background_quartet(
    api: ApiClient,
    world: World,
    well_id: str,
    values: Sequence[float] = BACKGROUND_SULFATE_VALUES,
    parameter_code: str = PARAM_SULFATE,
    codes: Sequence[str] = ("BG-R1", "BG-R2", "BG-R3", "BG-R4"),
    dates: Sequence[str] = BACKGROUND_DATES,
) -> List[Json]:
    """Four validated rounds inside the background window, one value each.

    Four is exactly the contract's minimum background count, which is also what
    puts the coverage multiplier in its 4-to-5 band.
    """
    events: List[Json] = []
    for code, date, value in zip(codes, dates, values):
        events.append(
            validated_round(
                api,
                world["program_id"],
                world["hydro_headers"],
                code,
                date,
                [(well_id, value)],
                EVENT_TYPE_BACKGROUND,
                parameter_code,
            )
        )
    return events


def seed_detection_measurement(
    api: ApiClient,
    world: World,
    well_id: str,
    value: float = DETECTION_SULFATE_VALUE,
    parameter_code: str = PARAM_SULFATE,
    event_code: str = "DET-R1",
    sampled_on: str = DETECTION_DATE,
) -> Json:
    """One validated detection round dated after the background window's end."""
    return validated_round(
        api,
        world["program_id"],
        world["hydro_headers"],
        event_code,
        sampled_on,
        [(well_id, value)],
        EVENT_TYPE_DETECTION,
        parameter_code,
    )


def seed_interwell_data(
    api: ApiClient,
    world: World,
    background_values: Sequence[float] = BACKGROUND_SULFATE_VALUES,
    detection_value: float = DETECTION_SULFATE_VALUE,
    parameter_code: str = PARAM_SULFATE,
) -> World:
    """Background from the BG-01 well plus a detection value at DG-01.

    Under the program's INTERWELL basis the background set is the background
    well's history and the compliance well's own history is excluded, so the two
    halves of this data set are read by two different rules.
    """
    background_well = world["wells"]["BG-01"]["id"]
    compliance_well = world["wells"]["DG-01"]["id"]
    world["background_events"] = seed_background_quartet(
        api, world, background_well, background_values, parameter_code
    )
    world["detection_event"] = seed_detection_measurement(
        api, world, compliance_well, detection_value, parameter_code
    )
    world["compliance_well_id"] = compliance_well
    world["background_well_id"] = background_well
    return world


def issue_evaluation(
    api: ApiClient,
    world: World,
    evaluation_code: str = "EVAL-01",
    parameter_code: str = PARAM_SULFATE,
    **overrides: Any,
) -> Json:
    payload = factories.evaluation_payload(
        world["program_id"], world["compliance_well_id"], evaluation_code, parameter_code, **overrides
    )
    return get_success_data(api.create_statistical_evaluation(payload, world["stats_headers"]))


# ── Tier 6: stability, closure plans and the closure lifecycle ────────────


def file_stability(
    api: ApiClient,
    world: World,
    assessed_on: str = "2026-07-15",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Json:
    """File an ADEQUATE assessment unless the caller overrides the factors."""
    payload = factories.stability_payload(world["unit_id"], assessed_on, **overrides)
    return get_success_data(
        api.create_stability_assessment(payload, headers or world["geotech_headers"])
    )


def draft_plan(
    api: ApiClient, world: World, plan_code: str = "PLAN-01", **overrides: Any
) -> Json:
    payload = factories.closure_plan_payload(world["unit_id"], plan_code, **overrides)
    return get_success_data(api.create_closure_plan(payload, UTILITY_ADMIN_HEADERS))


def certify_plan_both_halves(
    api: ApiClient,
    world: World,
    plan_id: str,
    certified_on: str = "2026-08-01",
) -> Json:
    """Sign the engineering half then the cost half with two distinct identities.

    The engineering signature is the geotechnical licensee and the cost
    signature the civil one, so the contract's two-different-identities rule on
    the certification diamond is satisfied by construction.
    """
    get_success_data(
        api.certify_plan_engineering(
            plan_id,
            factories.engineering_certification_payload(certified_on),
            world["geotech_headers"],
        )
    )
    return get_success_data(
        api.certify_plan_cost(
            plan_id, factories.cost_certification_payload(certified_on), world["civil_headers"]
        )
    )


def approve_plan(
    api: ApiClient,
    plan_id: str,
    approved_on: str = "2026-08-01",
    permit_reference: str = "PERMIT-2026-A",
) -> Json:
    payload = factories.approve_plan_payload(approved_on, permit_reference)
    return get_success_data(api.approve_closure_plan(plan_id, payload, REGULATOR_HEADERS))


def seed_approved_plan(
    api: ApiClient,
    world: World,
    plan_code: str = "PLAN-01",
    assessed_on: str = "2026-07-15",
    signed_on: str = "2026-08-01",
    approved_on: str = "2026-08-01",
    **plan_overrides: Any,
) -> Json:
    """Take a unit all the way to an APPROVED closure plan.

    Engineering certification is admitted only once the unit's governing
    stability verdict is ADEQUATE, so the assessment is filed first.
    """
    file_stability(api, world, assessed_on)
    plan = draft_plan(api, world, plan_code, **plan_overrides)
    certify_plan_both_halves(api, world, plan["id"], signed_on)
    approved = approve_plan(api, plan["id"], approved_on)
    world["plan"] = approved
    world["plan_id"] = approved["id"]
    return approved


def begin_closure(api: ApiClient, unit_id: str, initiated_on: str = "2026-08-01") -> Json:
    payload = factories.begin_closure_payload(initiated_on)
    return get_success_data(api.begin_closure(unit_id, payload, UTILITY_ADMIN_HEADERS))


def complete_closure(
    api: ApiClient, world: World, completed_on: str = "2026-08-01", headers: Optional[Dict] = None
) -> Json:
    payload = factories.complete_closure_payload(completed_on)
    return get_success_data(
        api.complete_closure(world["unit_id"], payload, headers or world["civil_headers"])
    )


def seed_post_closure_care(
    api: ApiClient,
    world: World,
    on_date: str = "2026-08-01",
    **plan_overrides: Any,
) -> Json:
    """Drive a unit through approval, commencement and completion of closure.

    The unit lands in POST_CLOSURE_CARE with its cap dimension ADEQUATE and its
    care period running from ``on_date``.
    """
    seed_approved_plan(api, world, approved_on=on_date, signed_on=on_date, **plan_overrides)
    begin_closure(api, world["unit_id"], on_date)
    return complete_closure(api, world, on_date)


def file_cap_inspection(
    api: ApiClient,
    world: World,
    inspected_on: str,
    headers: Optional[Dict[str, str]] = None,
    deficient: bool = False,
    **overrides: Any,
) -> Json:
    builder = (
        factories.deficient_cap_inspection_payload if deficient else factories.cap_inspection_payload
    )
    payload = builder(world["unit_id"], inspected_on, **overrides)
    return get_success_data(
        api.create_cap_inspection(payload, headers or world["civil_headers"])
    )


# ── Tier 6: beneficial reuse ──────────────────────────────────────────────


def draft_agreement(
    api: ApiClient, world: World, agreement_code: str = "AGR-01", **overrides: Any
) -> Json:
    payload = factories.reuse_agreement_payload(world["unit_id"], agreement_code, **overrides)
    return get_success_data(api.create_reuse_agreement(payload, UTILITY_ADMIN_HEADERS))


def seed_active_agreement(
    api: ApiClient,
    world: World,
    agreement_code: str = "AGR-01",
    on_date: str = "2026-08-01",
    **overrides: Any,
) -> Json:
    """Draft, qualify and activate an agreement so shipments may move."""
    agreement = draft_agreement(api, world, agreement_code, **overrides)
    get_success_data(
        api.qualify_reuse_agreement(
            agreement["id"], factories.qualify_agreement_payload(on_date), world["civil_headers"]
        )
    )
    activated = get_success_data(
        api.activate_reuse_agreement(
            agreement["id"], factories.activate_agreement_payload(on_date), UTILITY_ADMIN_HEADERS
        )
    )
    world["agreement"] = activated
    world["agreement_id"] = activated["id"]
    return activated


def ship_load(
    api: ApiClient,
    world: World,
    shipment_code: str,
    tons: int,
    shipped_on: str = "2026-08-01",
    agreement_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """Move a load out, quoting the owning unit's version read a moment ago."""
    version = unit_version(api, world["unit_id"])
    payload = factories.shipment_payload(
        agreement_id or world["agreement_id"], shipment_code, tons, version, shipped_on, **overrides
    )
    return get_success_data(api.create_reuse_shipment(payload, UTILITY_ADMIN_HEADERS))


def return_load(
    api: ApiClient, world: World, shipment_id: str, returned_on: str = "2026-08-01", **overrides: Any
) -> Json:
    version = unit_version(api, world["unit_id"])
    payload = factories.return_shipment_payload(version, returned_on, **overrides)
    return get_success_data(api.return_reuse_shipment(shipment_id, payload, UTILITY_ADMIN_HEADERS))


# ── Tier 6: the public operating record ───────────────────────────────────


def post_document(
    api: ApiClient,
    world: World,
    posting_type: str,
    posted_on: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Json:
    payload = factories.posting_payload(world["unit_id"], posted_on, posting_type, **overrides)
    return get_success_data(
        api.create_public_posting(payload, headers or COMPLIANCE_OFFICER_HEADERS)
    )


def withdraw_document(
    api: ApiClient, posting_id: str, withdrawn_on: str, headers: Optional[Dict] = None
) -> Json:
    payload = factories.withdraw_posting_payload(withdrawn_on)
    return get_success_data(
        api.withdraw_public_posting(posting_id, payload, headers or COMPLIANCE_OFFICER_HEADERS)
    )


# ── Tier 6: extensions and alternate source demonstrations ────────────────


def request_extension(
    api: ApiClient, world: World, requested_months: int = 12, **overrides: Any
) -> Json:
    payload = factories.extension_request_payload(world["unit_id"], requested_months, **overrides)
    return get_success_data(api.create_extension_request(payload, UTILITY_ADMIN_HEADERS))


def decide_extension(
    api: ApiClient,
    request_id: str,
    decision: str,
    decided_on: str = "2026-08-01",
    granted_months: Optional[int] = None,
    **overrides: Any,
) -> Json:
    payload = factories.extension_decision_payload(decision, decided_on, granted_months, **overrides)
    return get_success_data(api.decide_extension_request(request_id, payload, REGULATOR_HEADERS))


def accept_asd(
    api: ApiClient,
    world: World,
    evaluation_id: str,
    certifying_professional_id: str,
    submitted_on: str = "2026-08-01",
    decided_on: str = "2026-08-05",
) -> Json:
    """Submit a demonstration and have the regulator accept it.

    The certifier must be a different identity from the evaluation's reviewer,
    which is why callers pass an identifier other than the statistician's.
    """
    get_success_data(
        api.submit_asd(
            evaluation_id,
            factories.asd_submission_payload(certifying_professional_id, submitted_on),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    return get_success_data(
        api.decide_asd(
            evaluation_id,
            factories.asd_decision_payload(ASD_DECISION_ACCEPT, decided_on),
            REGULATOR_HEADERS,
        )
    )


# ── The shared default world ───────────────────────────────────────────────


def seed_reference_data(api: ApiClient) -> World:
    """The cheapest world worth sharing: a roster and one clean unit.

    Tests that need more build on top of it with the tier helpers above; tests
    that need less simply ignore the parts they do not touch.
    """
    return seed_unit(api)


# ── A whole SSI escalation in one call ─────────────────────────────────────

FOUR_BACKGROUND_WELLS: Tuple[str, str, str, str] = ("BG-01", "BG-02", "BG-03", "BG-04")


def seed_ssi_ready(
    api: ApiClient,
    unit_code: str = "IMP-0101",
    background_values: Sequence[float] = BACKGROUND_SULFATE_VALUES,
    detection_value: float = DETECTION_SULFATE_VALUE,
    background_round_on: str = "2025-06-01",
    detection_round_on: str = "2026-06-15",
    parameter_code: str = PARAM_SULFATE,
    **unit_overrides: Any,
) -> World:
    """Everything an SSI needs except the evaluation that declares it.

    The program is still in DETECTION and the unit is still COMPLIANT, so a
    single later evaluation is the only cause of whatever changes next.

    The background set is four separate upgradient wells sampled in one
    validated round, which reaches the contract's minimum background count of
    four in one round rather than in four, and so needs no 90-day spacing.
    """
    world = seed_unit(api, unit_code, **unit_overrides)
    world["wells"] = install_standard_network(
        api, world["unit_id"], world["hydro_headers"], FOUR_BACKGROUND_WELLS
    )
    configure_program(api, world["program_id"], world["hydro_headers"])
    certify_network(api, world["program_id"], world["hydro_headers"], "2025-01-05")

    world["background_event"] = validated_round(
        api,
        world["program_id"],
        world["hydro_headers"],
        "BG-R1",
        background_round_on,
        [(world["wells"][code]["id"], value) for code, value in zip(FOUR_BACKGROUND_WELLS, background_values)],
        EVENT_TYPE_BACKGROUND,
        parameter_code,
        validated_on="2025-06-02",
    )
    world["compliance_well_id"] = world["wells"]["DG-01"]["id"]
    world["detection_event"] = validated_round(
        api,
        world["program_id"],
        world["hydro_headers"],
        "DET-R1",
        detection_round_on,
        [(world["compliance_well_id"], detection_value)],
        EVENT_TYPE_DETECTION,
        parameter_code,
        validated_on="2026-06-16",
    )
    world["parameter_code"] = parameter_code
    return world


def seed_ssi_escalation(
    api: ApiClient,
    unit_code: str = "IMP-0101",
    evaluation_code: str = "EV-1",
    **overrides: Any,
) -> World:
    """Drive a program from DETECTION into ASSESSMENT with a single evaluation."""
    world = seed_ssi_ready(api, unit_code, **overrides)
    world["evaluation"] = issue_evaluation(api, world, evaluation_code, world["parameter_code"])
    world["evaluation_id"] = world["evaluation"]["id"]
    return world
