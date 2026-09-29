"""Composite setup helpers.

The harness restarts the service before every individual test, so each test
starts against an empty database and has to build every row it needs through
documented endpoints. These helpers are those build sequences.

Three tiers:

* thin wrappers (`enroll_donor`, `log_container`, ...) that post one payload and
  return the unwrapped resource;
* read helpers (`get_pool`, `pool_version`, ...) that fetch current state, which
  matters because the three optimistic-concurrency tokens must be read fresh
  immediately before the write that carries them;
* composites (`qualified_donor`, `build_chain`, `released_lot`) that assemble the
  donor-to-inventory chain with keyword knobs.

Nothing here asserts business outcomes; setup failures surface through
`get_success_data`, which insists only on a 2xx.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as f
from .api_client import api_client
from .test_users import (
    ADMIN_HEADERS,
    INTAKE_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    PHARMACIST_HEADERS,
    PRESCRIBER_HEADERS,
    QA_OFFICER_HEADERS,
    QA_RELEASER_HEADERS,
    TECHNICIAN_HEADERS,
)
from .types import MilkClass, TargetMilkClass

JsonDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Tier 1: one call, one resource
# ---------------------------------------------------------------------------
def set_clock(instant: str, headers: Dict[str, str] = ADMIN_HEADERS) -> JsonDict:
    """Advance the logical clock and sweep every expirable row."""
    return get_success_data(api_client.set_clock(instant, headers), 200)


def enroll_donor(headers: Dict[str, str] = INTAKE_HEADERS, **overrides: Any) -> JsonDict:
    return get_success_data(api_client.create_donor(f.donor(**overrides), headers), 201)


def submit_questionnaire(
    donor_id: str, headers: Dict[str, str] = INTAKE_HEADERS, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.submit_health_history(donor_id, f.health_history(**overrides), headers), 201
    )


def record_serology(
    donor_id: str, headers: Dict[str, str] = MEDICAL_DIRECTOR_HEADERS, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.record_serology_panel(donor_id, f.serology_panel(**overrides), headers), 201
    )


def record_approval(
    donor_id: str, headers: Dict[str, str] = MEDICAL_DIRECTOR_HEADERS, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.record_physician_approval(donor_id, f.physician_approval(**overrides), headers),
        201,
    )


def qualify(donor_id: str, headers: Dict[str, str] = MEDICAL_DIRECTOR_HEADERS) -> JsonDict:
    return get_success_data(api_client.qualify_donor(donor_id, headers), 200)


def requalify(donor_id: str, headers: Dict[str, str] = MEDICAL_DIRECTOR_HEADERS) -> JsonDict:
    return get_success_data(api_client.requalify_donor(donor_id, headers), 200)


def record_deferral(
    donor_id: str, headers: Dict[str, str] = MEDICAL_DIRECTOR_HEADERS, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.record_deferral(donor_id, f.deferral(**overrides), headers), 201
    )


def register_shipment(
    donor_id: str, headers: Dict[str, str] = INTAKE_HEADERS, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.create_shipment(f.shipment(donor_id, **overrides), headers), 201
    )


def receive_shipment(
    shipment_id: str, headers: Dict[str, str] = INTAKE_HEADERS, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.receive_shipment(shipment_id, f.receipt(**overrides), headers), 200
    )


def disposition_shipment(
    shipment_id: str, value: str, headers: Dict[str, str] = MEDICAL_DIRECTOR_HEADERS
) -> JsonDict:
    return get_success_data(
        api_client.disposition_shipment(shipment_id, f.disposition(value), headers), 200
    )


def log_container(
    shipment_id: str,
    headers: Dict[str, str] = INTAKE_HEADERS,
    expected_shipment_version: Optional[int] = None,
    **overrides: Any,
) -> JsonDict:
    """Log one container, reading the cooler's live version unless one is given."""
    version = (
        expected_shipment_version
        if expected_shipment_version is not None
        else shipment_version(shipment_id)
    )
    return get_success_data(
        api_client.log_donation(shipment_id, f.donation(version, **overrides), headers), 201
    )


def open_pool(headers: Dict[str, str] = TECHNICIAN_HEADERS, **overrides: Any) -> JsonDict:
    return get_success_data(api_client.create_pool(f.pool(**overrides), headers), 201)


def draw_component(
    pool_id: str,
    donation_id: str,
    allocated_volume_ml: int,
    headers: Dict[str, str] = TECHNICIAN_HEADERS,
    expected_pool_version: Optional[int] = None,
) -> JsonDict:
    """Draw volume into the pool, reading the pool's live version unless given."""
    version = (
        expected_pool_version if expected_pool_version is not None else pool_version(pool_id)
    )
    payload = f.pool_component(donation_id, allocated_volume_ml, version)
    return get_success_data(api_client.add_pool_component(pool_id, payload, headers), 201)


def commit_pool(pool_id: str, headers: Dict[str, str] = TECHNICIAN_HEADERS) -> JsonDict:
    return get_success_data(api_client.commit_pool(pool_id, headers), 200)


def scrap_pool(pool_id: str, headers: Dict[str, str] = TECHNICIAN_HEADERS) -> JsonDict:
    return get_success_data(api_client.scrap_pool(pool_id, headers), 200)


def schedule_run(
    pool_id: str, headers: Dict[str, str] = TECHNICIAN_HEADERS, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api_client.create_run(f.pasteurization_run(pool_id, **overrides), headers), 201
    )


def add_reading(
    run_id: str,
    offset_seconds: int,
    celsius: float,
    headers: Dict[str, str] = TECHNICIAN_HEADERS,
) -> JsonDict:
    return get_success_data(
        api_client.append_reading(
            run_id, f.temperature_reading(offset_seconds, celsius), headers
        ),
        201,
    )


def add_readings(
    run_id: str,
    samples: Sequence[Tuple[int, float]],
    headers: Dict[str, str] = TECHNICIAN_HEADERS,
) -> List[JsonDict]:
    return [add_reading(run_id, offset, celsius, headers) for offset, celsius in samples]


def complete_run(run_id: str, headers: Dict[str, str] = TECHNICIAN_HEADERS) -> JsonDict:
    return get_success_data(api_client.complete_run(run_id, headers), 200)


def record_culture(
    run_id: str,
    culture_cfu_per_ml: int = 0,
    culture_organism: str = C.NO_GROWTH_ORGANISM,
    headers: Dict[str, str] = QA_OFFICER_HEADERS,
) -> JsonDict:
    return get_success_data(
        api_client.record_culture(
            run_id, f.culture(culture_cfu_per_ml, culture_organism), headers
        ),
        200,
    )


def bottle_lot(
    run_id: str,
    bottle_count: int,
    bottle_volume_ml: int,
    headers: Dict[str, str] = TECHNICIAN_HEADERS,
) -> JsonDict:
    return get_success_data(
        api_client.bottle_lot(run_id, f.milk_lot(bottle_count, bottle_volume_ml), headers), 201
    )


def release_lot(lot_id: str, headers: Dict[str, str] = QA_RELEASER_HEADERS) -> JsonDict:
    return get_success_data(api_client.release_milk_lot(lot_id, headers), 200)


def open_program(headers: Dict[str, str] = ADMIN_HEADERS, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_subsidy_program(f.subsidy_program(**overrides), headers), 201
    )


def submit_prescription(headers: Dict[str, str] = PRESCRIBER_HEADERS, **overrides: Any) -> JsonDict:
    return get_success_data(
        api_client.create_prescription(f.prescription(**overrides), headers), 201
    )


def fill_prescription(
    prescription_id: str,
    lot_id: str,
    volume_ml: int,
    headers: Dict[str, str] = PHARMACIST_HEADERS,
    expected_lot_version: Optional[int] = None,
) -> JsonDict:
    """Fill an order, reading the parent lot's live version unless one is given."""
    version = expected_lot_version if expected_lot_version is not None else lot_version(lot_id)
    payload = f.dispense(lot_id, volume_ml, version)
    return get_success_data(api_client.create_dispense(prescription_id, payload, headers), 201)


def void_dispense(dispense_id: str, headers: Dict[str, str] = PHARMACIST_HEADERS) -> JsonDict:
    return get_success_data(api_client.void_dispense(dispense_id, headers), 200)


def cancel_prescription(
    prescription_id: str, headers: Dict[str, str] = PRESCRIBER_HEADERS
) -> JsonDict:
    return get_success_data(api_client.cancel_prescription(prescription_id, headers), 200)


def run_allocation_cycle(headers: Dict[str, str] = PHARMACIST_HEADERS) -> JsonDict:
    return get_success_data(api_client.run_allocation_cycle(headers), 200)


# ---------------------------------------------------------------------------
# Tier 2: read helpers
# ---------------------------------------------------------------------------
def get_donor(donor_id: str, headers: Dict[str, str] = INTAKE_HEADERS) -> JsonDict:
    return get_success_data(api_client.get_donor(donor_id, headers), 200)


def get_shipment(shipment_id: str, headers: Dict[str, str] = INTAKE_HEADERS) -> JsonDict:
    return get_success_data(api_client.get_shipment(shipment_id, headers), 200)


def get_donation(donation_id: str, headers: Dict[str, str] = TECHNICIAN_HEADERS) -> JsonDict:
    return get_success_data(api_client.get_donation(donation_id, headers), 200)


def get_pool(pool_id: str, headers: Dict[str, str] = TECHNICIAN_HEADERS) -> JsonDict:
    return get_success_data(api_client.get_pool(pool_id, headers), 200)


def get_run(run_id: str, headers: Dict[str, str] = TECHNICIAN_HEADERS) -> JsonDict:
    return get_success_data(api_client.get_run(run_id, headers), 200)


def get_lot(lot_id: str, headers: Dict[str, str] = QA_RELEASER_HEADERS) -> JsonDict:
    return get_success_data(api_client.get_milk_lot(lot_id, headers), 200)


def get_program(program_id: str, headers: Dict[str, str] = ADMIN_HEADERS) -> JsonDict:
    return get_success_data(api_client.get_subsidy_program(program_id, headers), 200)


def get_prescription(
    prescription_id: str, headers: Dict[str, str] = PHARMACIST_HEADERS
) -> JsonDict:
    return get_success_data(api_client.get_prescription(prescription_id, headers), 200)


def shipment_version(shipment_id: str) -> int:
    """The cooler's live version, for the `expected_shipment_version` token."""
    return get_shipment(shipment_id)["version"]


def pool_version(pool_id: str) -> int:
    """The pool's live version, for the `expected_pool_version` token."""
    return get_pool(pool_id)["version"]


def lot_version(lot_id: str) -> int:
    """The lot's live version, for the `expected_lot_version` token — the fill's
    concurrency parent is the lot, not the prescription."""
    return get_lot(lot_id)["version"]


def donor_balance(donor_id: str) -> int:
    return get_donor(donor_id)["reimbursement_balance_cents"]


def list_pool_components(pool_id: str, **params: Any) -> List[JsonDict]:
    response = api_client.list_pool_components(pool_id, TECHNICIAN_HEADERS, params or None)
    return get_success_data(response, 200)


def list_readings(run_id: str, **params: Any) -> List[JsonDict]:
    response = api_client.list_readings(run_id, TECHNICIAN_HEADERS, params or None)
    return get_success_data(response, 200)


def list_lot_dispenses(lot_id: str, **params: Any) -> List[JsonDict]:
    response = api_client.list_lot_dispenses(lot_id, PHARMACIST_HEADERS, params or None)
    return get_success_data(response, 200)


def list_prescription_dispenses(prescription_id: str, **params: Any) -> List[JsonDict]:
    response = api_client.list_prescription_dispenses(
        prescription_id, PHARMACIST_HEADERS, params or None
    )
    return get_success_data(response, 200)


def list_deferrals(donor_id: str, **params: Any) -> List[JsonDict]:
    response = api_client.list_deferrals(donor_id, MEDICAL_DIRECTOR_HEADERS, params or None)
    return get_success_data(response, 200)


def list_milk_lots(**params: Any) -> List[JsonDict]:
    response = api_client.list_milk_lots(QA_RELEASER_HEADERS, params or None)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Tier 3: shared parameter sets
# ---------------------------------------------------------------------------

# A questionnaire worth exactly 30 base risk points: two flagged medications
# (16), three alcohol units (5) and fifteen months postpartum (9). With no
# serology on file it triages at 50 and lands ACCEPTED.
CLEAN_QUESTIONNAIRE: Dict[str, Any] = {
    "medication_flag_count": 2,
    "travel_risk_flag": False,
    "tobacco_use": False,
    "alcohol_units_per_week": 3,
    "months_postpartum": 15,
}

# A curve whose longest certified hold is exactly 1800 seconds.
PASSING_READINGS: List[Tuple[int, float]] = [
    (0, 63.0),
    (600, 63.5),
    (1200, 64.0),
    (1800, 63.2),
]

DEFAULT_RUN: Dict[str, Any] = {
    "pasteurizer_id": "PAST-01",
    "scheduled_start_at": "2026-08-10T09:00:00Z",
    "cycle_minutes": 60,
}

CANONICAL_DONORS: List[Dict[str, Any]] = [
    {
        "donor_code": "DNR-1001",
        "full_name": "Ana Ruiz",
        "email": "ana.ruiz@example.org",
        "zone_code": "Z2",
        "collected_on": "2026-07-20",
        "physician_npi": "1234567893",
        "approved_on": "2026-07-15",
    },
    {
        "donor_code": "DNR-1002",
        "full_name": "Bea Ortiz",
        "email": "bea.ortiz@example.org",
        "zone_code": "Z1",
        "collected_on": "2026-07-22",
        "physician_npi": "1234567802",
        "approved_on": "2026-07-16",
    },
    {
        "donor_code": "DNR-1003",
        "full_name": "Cyd Park",
        "email": "cyd.park@example.org",
        "zone_code": "Z3",
        "collected_on": "2026-07-23",
        "physician_npi": "1234567811",
        "approved_on": "2026-07-17",
    },
]

CANONICAL_CONTAINERS: List[Dict[str, Any]] = [
    {
        "donor_index": 0,
        "tracking_code": "TRK-1001",
        "declared_volume_ml": 800,
        "container_label": "A1",
        "expressed_on": "2026-07-05",
        "volume_ml": 800,
        "kcal_per_oz": 18.5,
    },
    {
        "donor_index": 1,
        "tracking_code": "TRK-1002",
        "declared_volume_ml": 700,
        "container_label": "A2",
        "expressed_on": "2026-07-10",
        "volume_ml": 700,
        "kcal_per_oz": 20.0,
    },
    {
        "donor_index": 2,
        "tracking_code": "TRK-1003",
        "declared_volume_ml": 600,
        "container_label": "A3",
        "expressed_on": "2026-07-12",
        "volume_ml": 600,
        "kcal_per_oz": 22.5,
    },
]


def donor_spec(index: int, **overrides: Any) -> Dict[str, Any]:
    """A donor enrolment spec with a distinct code, name and valid NPI."""
    code = overrides.pop("donor_code", f"DNR-{index:04d}")
    spec: Dict[str, Any] = {
        "donor_code": code,
        "full_name": f"Donor {index:04d}",
        "email": f"donor{index:04d}@example.org",
        "zone_code": "Z2",
        "collected_on": "2026-07-20",
        "physician_npi": "1234567893",
        "approved_on": "2026-07-15",
    }
    spec.update(overrides)
    return spec


def container_spec(index: int, donor_index: int, volume_ml: int, **overrides: Any) -> Dict[str, Any]:
    """A one-container cooler spec carrying `volume_ml` of milk."""
    spec: Dict[str, Any] = {
        "donor_index": donor_index,
        "tracking_code": f"TRK-{index:04d}",
        "container_count": 1,
        "uses_dry_ice": False,
        "declared_volume_ml": volume_ml,
        "shipped_on": "2026-08-02",
        "container_label": f"C{index}",
        "expressed_on": "2026-07-05",
        "volume_ml": volume_ml,
        "kcal_per_oz": 20.0,
        "milk_class": MilkClass.TERM,
        "excursion_minutes": 0,
        "arrival_max_temp_celsius": -18.0,
    }
    spec.update(overrides)
    return spec


def split_pool_volume(total_ml: int, parts: int = 3) -> List[int]:
    """Split a pool volume into equal per-container draws inside the 50-1200
    millilitre range, using at least three containers so the donor-spread rule
    can be satisfied."""
    while total_ml % parts != 0 or total_ml // parts > C.ALLOCATED_VOLUME_MAX:
        parts += 1
        if parts > 12:
            raise ValueError(f"cannot split {total_ml} ml into legal draws")
    return [total_ml // parts] * parts


# ---------------------------------------------------------------------------
# Tier 4: per-stage composites
# ---------------------------------------------------------------------------
def screened_donor(
    donor_code: str = "DNR-0001",
    full_name: str = "Ana Ruiz",
    email: Optional[str] = None,
    zone_code: str = "Z2",
    questionnaire: Optional[Dict[str, Any]] = None,
) -> JsonDict:
    """A donor carrying one questionnaire. Returns the donor as it stands after
    the submission, so its status reflects the triage band."""
    donor = enroll_donor(
        donor_code=donor_code,
        full_name=full_name,
        email=email or f"{donor_code.lower()}@example.org",
        zone_code=zone_code,
    )
    submit_questionnaire(donor["id"], **(CLEAN_QUESTIONNAIRE if questionnaire is None else questionnaire))
    return get_donor(donor["id"])


def cleared_donor(
    donor_code: str = "DNR-0001",
    full_name: str = "Ana Ruiz",
    email: Optional[str] = None,
    zone_code: str = "Z2",
    questionnaire: Optional[Dict[str, Any]] = None,
    collected_on: str = "2026-07-20",
    physician_npi: str = "1234567893",
    approved_on: str = "2026-07-15",
) -> JsonDict:
    """A screened donor who also has an unexpired non-reactive panel and an
    active physician approval on file, but who has not been qualified yet."""
    donor = screened_donor(donor_code, full_name, email, zone_code, questionnaire)
    record_serology(donor["id"], collected_on=collected_on)
    record_approval(donor["id"], physician_npi=physician_npi, approved_on=approved_on)
    return get_donor(donor["id"])


def qualified_donor(
    donor_code: str = "DNR-0001",
    full_name: str = "Ana Ruiz",
    email: Optional[str] = None,
    zone_code: str = "Z2",
    questionnaire: Optional[Dict[str, Any]] = None,
    collected_on: str = "2026-07-20",
    physician_npi: str = "1234567893",
    approved_on: str = "2026-07-15",
) -> JsonDict:
    """A donor admitted to the processing stream."""
    donor = cleared_donor(
        donor_code, full_name, email, zone_code, questionnaire, collected_on, physician_npi, approved_on
    )
    return qualify(donor["id"])


def accepted_cooler(
    donor_id: str,
    tracking_code: str = "TRK-0001",
    container_count: int = 1,
    uses_dry_ice: bool = False,
    declared_volume_ml: int = 800,
    shipped_on: str = "2026-08-02",
    excursion_minutes: int = 0,
    arrival_max_temp_celsius: float = -18.0,
    verified_volume_ml: Optional[int] = None,
) -> JsonDict:
    """A cooler registered and then received inside both cold-chain thresholds."""
    shipment = register_shipment(
        donor_id,
        tracking_code=tracking_code,
        container_count=container_count,
        uses_dry_ice=uses_dry_ice,
        declared_volume_ml=declared_volume_ml,
        shipped_on=shipped_on,
    )
    return receive_shipment(
        shipment["id"],
        excursion_minutes=excursion_minutes,
        arrival_max_temp_celsius=arrival_max_temp_celsius,
        verified_volume_ml=declared_volume_ml if verified_volume_ml is None else verified_volume_ml,
    )


def eligible_donation(
    donor_id: str,
    tracking_code: str = "TRK-0001",
    container_label: str = "A1",
    expressed_on: str = "2026-07-05",
    volume_ml: int = 800,
    kcal_per_oz: float = 20.0,
    milk_class: str = MilkClass.TERM,
) -> Tuple[JsonDict, JsonDict]:
    """One accepted cooler holding one logged container. Returns (cooler, donation)."""
    shipment = accepted_cooler(
        donor_id, tracking_code=tracking_code, declared_volume_ml=volume_ml
    )
    donation = log_container(
        shipment["id"],
        container_label=container_label,
        expressed_on=expressed_on,
        volume_ml=volume_ml,
        kcal_per_oz=kcal_per_oz,
        milk_class=milk_class,
    )
    return shipment, donation


def donor_with_donation(
    index: int = 1,
    volume_ml: int = 700,
    kcal_per_oz: float = 20.0,
    milk_class: str = MilkClass.TERM,
    expressed_on: str = "2026-07-05",
    **donor_overrides: Any,
) -> SimpleNamespace:
    """A qualified donor plus one accepted cooler plus one eligible container."""
    spec = donor_spec(index, **donor_overrides)
    donor = qualified_donor(
        donor_code=spec["donor_code"],
        full_name=spec["full_name"],
        email=spec["email"],
        zone_code=spec["zone_code"],
        collected_on=spec["collected_on"],
        physician_npi=spec["physician_npi"],
        approved_on=spec["approved_on"],
    )
    shipment, donation = eligible_donation(
        donor["id"],
        tracking_code=f"TRK-{index:04d}",
        container_label=f"C{index}",
        expressed_on=expressed_on,
        volume_ml=volume_ml,
        kcal_per_oz=kcal_per_oz,
        milk_class=milk_class,
    )
    return SimpleNamespace(donor=donor, shipment=shipment, donation=donation)


# ---------------------------------------------------------------------------
# Tier 5: the whole donor-to-inventory chain
# ---------------------------------------------------------------------------
def build_chain(
    donors: Optional[List[Dict[str, Any]]] = None,
    containers: Optional[List[Dict[str, Any]]] = None,
    pool_code: str = "POOL-0001",
    target_milk_class: str = TargetMilkClass.TERM,
    draws: Optional[List[Tuple[int, int]]] = None,
    commit: bool = True,
    run: Optional[Dict[str, Any]] = None,
    readings: Optional[Sequence[Tuple[int, float]]] = None,
    complete: bool = True,
    culture: Optional[Tuple[int, str]] = (0, C.NO_GROWTH_ORGANISM),
    lots: Optional[List[Tuple[int, int]]] = None,
    release: bool = True,
    intake_clock: Optional[str] = C.CLOCK_INTAKE,
    run_clock: Optional[str] = C.CLOCK_RUN,
) -> SimpleNamespace:
    """Assemble the processing chain as far as the caller asks for.

    Each entry of `containers` is one cooler holding one container, which is the
    shape the bank's intake actually takes: a donor ships a cooler, the
    coordinator receives it and logs what is inside.

    `draws` names `(container_index, allocated_volume_ml)` pairs and defaults to
    drawing each container's whole volume. Setting `commit` false stops before
    the commit; leaving `run` None stops before scheduling; leaving `lots` None
    stops before bottling.
    """
    donor_specs = CANONICAL_DONORS if donors is None else donors
    container_specs = CANONICAL_CONTAINERS if containers is None else containers

    if intake_clock:
        set_clock(intake_clock)

    donor_rows: List[JsonDict] = []
    for spec in donor_specs:
        donor_rows.append(
            qualified_donor(
                donor_code=spec["donor_code"],
                full_name=spec.get("full_name", spec["donor_code"]),
                email=spec.get("email"),
                zone_code=spec.get("zone_code", "Z2"),
                questionnaire=spec.get("questionnaire"),
                collected_on=spec.get("collected_on", "2026-07-20"),
                physician_npi=spec.get("physician_npi", "1234567893"),
                approved_on=spec.get("approved_on", "2026-07-15"),
            )
        )

    shipments: List[JsonDict] = []
    donations: List[JsonDict] = []
    for spec in container_specs:
        donor = donor_rows[spec.get("donor_index", 0)]
        shipment = accepted_cooler(
            donor["id"],
            tracking_code=spec["tracking_code"],
            container_count=spec.get("container_count", 1),
            uses_dry_ice=spec.get("uses_dry_ice", False),
            declared_volume_ml=spec.get("declared_volume_ml", spec["volume_ml"]),
            shipped_on=spec.get("shipped_on", "2026-08-02"),
            excursion_minutes=spec.get("excursion_minutes", 0),
            arrival_max_temp_celsius=spec.get("arrival_max_temp_celsius", -18.0),
        )
        shipments.append(shipment)
        donations.append(
            log_container(
                shipment["id"],
                container_label=spec.get("container_label", "A1"),
                expressed_on=spec.get("expressed_on", "2026-07-05"),
                volume_ml=spec["volume_ml"],
                kcal_per_oz=spec.get("kcal_per_oz", 20.0),
                milk_class=spec.get("milk_class", MilkClass.TERM),
            )
        )

    pool = open_pool(pool_code=pool_code, target_milk_class=target_milk_class)
    draw_list = (
        [(index, spec["volume_ml"]) for index, spec in enumerate(container_specs)]
        if draws is None
        else draws
    )
    components: List[JsonDict] = []
    for container_index, volume in draw_list:
        components.append(
            draw_component(pool["id"], donations[container_index]["id"], volume)
        )

    if commit:
        pool = commit_pool(pool["id"])
    else:
        pool = get_pool(pool["id"])

    chain = SimpleNamespace(
        donors=donor_rows,
        shipments=shipments,
        donations=donations,
        pool=pool,
        components=components,
        run=None,
        lots=[],
    )
    if run is None or not commit:
        return chain

    if run_clock:
        set_clock(run_clock)

    run_spec = dict(DEFAULT_RUN)
    run_spec.update(run)
    chain.run = schedule_run(pool["id"], **run_spec)

    sample_curve = PASSING_READINGS if readings is None else readings
    add_readings(chain.run["id"], sample_curve)

    if complete:
        chain.run = complete_run(chain.run["id"])
    else:
        chain.run = get_run(chain.run["id"])
        return chain

    if lots:
        for bottle_count, bottle_volume_ml in lots:
            chain.lots.append(bottle_lot(chain.run["id"], bottle_count, bottle_volume_ml))

    if culture is not None:
        chain.run = record_culture(chain.run["id"], culture[0], culture[1])

    if release and lots:
        chain.lots = [release_lot(lot["id"]) for lot in chain.lots]

    chain.pool = get_pool(pool["id"])
    chain.run = get_run(chain.run["id"])
    return chain


def released_lot(
    lot_volume_ml: int = 1200,
    pool_volume_ml: Optional[int] = None,
    bottle_volume_ml: int = 100,
    kcal_per_oz: float = 20.0,
    milk_class: str = MilkClass.TERM,
    target_milk_class: Optional[str] = None,
    expressed_on: str = "2026-07-05",
    donor_count: Optional[int] = None,
) -> SimpleNamespace:
    """One RELEASED lot of `lot_volume_ml`, drawn from a balanced pool.

    Every container carries the same assay so the pool's projection is exactly
    `kcal_per_oz`, which keeps the lot's frozen nutrition figure predictable.
    """
    pool_total = pool_volume_ml or max(lot_volume_ml, C.POOL_VOLUME_MIN)
    volumes = split_pool_volume(pool_total, donor_count or 3)
    donors = [donor_spec(index + 1) for index in range(len(volumes))]
    containers = [
        container_spec(
            index + 1,
            index,
            volume,
            kcal_per_oz=kcal_per_oz,
            milk_class=milk_class,
            expressed_on=expressed_on,
        )
        for index, volume in enumerate(volumes)
    ]
    assert lot_volume_ml % bottle_volume_ml == 0, "choose a bottle volume that divides the lot"
    return build_chain(
        donors=donors,
        containers=containers,
        target_milk_class=target_milk_class or milk_class,
        lots=[(lot_volume_ml // bottle_volume_ml, bottle_volume_ml)],
        release=True,
    )


def held_lot(
    lot_volume_ml: int = 1200,
    pool_volume_ml: Optional[int] = None,
    bottle_volume_ml: int = 100,
    kcal_per_oz: float = 20.0,
    milk_class: str = MilkClass.TERM,
    culture: Optional[Tuple[int, str]] = None,
) -> SimpleNamespace:
    """One lot still in HOLD: bottled, but with no culture recorded, so its run
    is not release-eligible."""
    pool_total = pool_volume_ml or max(lot_volume_ml, C.POOL_VOLUME_MIN)
    volumes = split_pool_volume(pool_total, 3)
    donors = [donor_spec(index + 1) for index in range(len(volumes))]
    containers = [
        container_spec(index + 1, index, volume, kcal_per_oz=kcal_per_oz, milk_class=milk_class)
        for index, volume in enumerate(volumes)
    ]
    return build_chain(
        donors=donors,
        containers=containers,
        target_milk_class=milk_class,
        lots=[(lot_volume_ml // bottle_volume_ml, bottle_volume_ml)],
        culture=culture,
        release=False,
    )
