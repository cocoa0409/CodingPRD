"""Composite setup helpers.

Every test starts against an empty database, so every precondition here is built
from scratch through the endpoints the PRD declares.  Setup calls use the
lenient ``get_success_data`` validator so a broken precondition reads as a setup
failure rather than as a confusing assertion failure.

Identity threading: `DesignEngineer`, `SealingEngineer` and `DealerPrincipal`
are entity-backed, so every ownership-gated call below passes the acting
Engineer's or Dealer's own `id` through ``make_*_headers``.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    assign_crew_payload,
    assign_order_to_load_payload,
    complete_run_payload,
    create_bin_design_payload,
    create_coating_spec_payload,
    create_coil_lot_payload,
    create_dealer_order_payload,
    create_dealer_payload,
    create_design_analysis_payload,
    create_engineer_payload,
    create_field_failure_payload,
    create_freight_load_payload,
    create_grain_profile_payload,
    create_installation_crew_payload,
    create_jurisdiction_payload,
    create_roll_forming_line_payload,
    create_roll_forming_run_payload,
    credit_limit_payload,
    order_payment_payload,
    request_revision_payload,
    revise_bin_design_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_dealer_principal_headers,
    make_design_engineer_headers,
    make_sealing_engineer_headers,
)

ADMIN = TEST_USERS["plant_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
QUALITY = TEST_USERS["quality_inspector_headers"]

DEFAULT_JURISDICTIONS = ("NE-WEST", "IA-CENTRAL", "CA-VALLEY")
DEFAULT_GRAIN_PROFILES = ("CORN", "LOWK", "DENSE", "RICE")
DEFAULT_COATINGS = ("G90", "G115", "G165", "G210")
DEFAULT_LINES = ("LINE_A", "LINE_LOW")
DEFAULT_ENGINEERS = ("PE-1001", "PE-1002", "PE-1003", "PE-9001")


# ---------------------------------------------------------------------------
# Tier 0 — single-call primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601):
    """Move the logical plant clock and return the reported new value."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    )


def register_jurisdiction(preset="NE-WEST", **overrides):
    return get_success_data(
        api_client.create_jurisdiction(
            create_jurisdiction_payload(preset, **overrides), ADMIN
        )
    )


def register_grain_profile(preset="CORN", **overrides):
    return get_success_data(
        api_client.create_grain_profile(
            create_grain_profile_payload(preset, **overrides), ADMIN
        )
    )


def register_coating_spec(preset="G115", **overrides):
    return get_success_data(
        api_client.create_coating_spec(
            create_coating_spec_payload(preset, **overrides), ADMIN
        )
    )


def register_roll_forming_line(preset="LINE_A", **overrides):
    return get_success_data(
        api_client.create_roll_forming_line(
            create_roll_forming_line_payload(preset, **overrides), ADMIN
        )
    )


def register_engineer(preset="PE-1001", **overrides):
    return get_success_data(
        api_client.create_engineer(create_engineer_payload(preset, **overrides), ADMIN)
    )


def register_dealer(jurisdiction_id, **overrides):
    return get_success_data(
        api_client.create_dealer(
            create_dealer_payload(jurisdiction_id, **overrides), ADMIN
        )
    )


def lapse_engineer(engineer):
    return get_success_data(api_client.lapse_engineer(engineer["id"], ADMIN))


def read_dealer(dealer_id):
    return get_success_data(api_client.get_dealer(dealer_id, ADMIN))


def read_design(design_id):
    return get_success_data(api_client.get_bin_design(design_id, ADMIN))


def read_order(order_id):
    return get_success_data(api_client.get_dealer_order(order_id, ADMIN))


def read_load(load_id):
    return get_success_data(api_client.get_freight_load(load_id, ADMIN))


def read_coil_lot(lot_id):
    return get_success_data(api_client.get_coil_lot(lot_id, ADMIN))


def read_run(run_id):
    return get_success_data(api_client.get_roll_forming_run(run_id, ADMIN))


def read_crew(crew_id):
    return get_success_data(api_client.get_installation_crew(crew_id, ADMIN))


def read_failure(failure_id):
    return get_success_data(api_client.get_field_failure(failure_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 — the shared reference register
# ---------------------------------------------------------------------------


def setup_reference_data(
    jurisdictions=DEFAULT_JURISDICTIONS,
    grain_profiles=DEFAULT_GRAIN_PROFILES,
    coatings=DEFAULT_COATINGS,
    lines=DEFAULT_LINES,
    engineers=DEFAULT_ENGINEERS,
    dealer_jurisdiction="NE-WEST",
    alpha_credit_limit_cents=TEST_DEFAULTS["DEALER_CREDIT_LIMIT_CENTS"],
    alpha_staging_slots=2,
    alpha_high_cube_access=True,
    alpha_program_tier="BASE",
    pinnacle_credit_limit_cents=TEST_DEFAULTS["DEALER_CREDIT_LIMIT_CENTS"],
    pinnacle_staging_slots=1,
    pinnacle_high_cube_access=False,
    pinnacle_program_tier="PREFERRED",
    with_pinnacle=True,
):
    """Register the plant's reference data and two dealerships.

    Returns a dict of lookup tables plus convenience shortcuts:
    ``ref["jurisdictions"]["NE-WEST"]``, ``ref["alpha"]``, ``ref["author"]``,
    ``ref["author_headers"]`` and so on.
    """
    ref = {
        "jurisdictions": {},
        "grain_profiles": {},
        "coating_specs": {},
        "lines": {},
        "engineers": {},
        "dealers": {},
    }
    for code in jurisdictions:
        ref["jurisdictions"][code] = register_jurisdiction(code)
    for code in grain_profiles:
        ref["grain_profiles"][code] = register_grain_profile(code)
    for code in coatings:
        ref["coating_specs"][code] = register_coating_spec(code)
    for code in lines:
        ref["lines"][code] = register_roll_forming_line(code)
    for license_number in engineers:
        ref["engineers"][license_number] = register_engineer(license_number)

    dealer_jurisdiction_id = ref["jurisdictions"][dealer_jurisdiction]["id"]
    ref["dealers"]["alpha"] = register_dealer(
        dealer_jurisdiction_id,
        name="Alpha Grain Systems",
        region_code="NE-01",
        credit_limit_cents=alpha_credit_limit_cents,
        program_tier=alpha_program_tier,
        staging_slots=alpha_staging_slots,
        high_cube_access=alpha_high_cube_access,
    )
    if with_pinnacle:
        ref["dealers"]["pinnacle"] = register_dealer(
            dealer_jurisdiction_id,
            name="Pinnacle Bin Supply",
            region_code="NE-02",
            credit_limit_cents=pinnacle_credit_limit_cents,
            program_tier=pinnacle_program_tier,
            staging_slots=pinnacle_staging_slots,
            high_cube_access=pinnacle_high_cube_access,
        )

    ref["alpha"] = ref["dealers"]["alpha"]
    ref["alpha_headers"] = make_dealer_principal_headers(ref["alpha"]["id"])
    if with_pinnacle:
        ref["pinnacle"] = ref["dealers"]["pinnacle"]
        ref["pinnacle_headers"] = make_dealer_principal_headers(ref["pinnacle"]["id"])

    if "PE-1001" in ref["engineers"]:
        ref["author"] = ref["engineers"]["PE-1001"]
        ref["author_headers"] = make_design_engineer_headers(ref["author"]["id"])
    if "PE-1002" in ref["engineers"]:
        ref["sealer"] = ref["engineers"]["PE-1002"]
        ref["sealer_headers"] = make_sealing_engineer_headers(ref["sealer"]["id"])
    if "PE-1003" in ref["engineers"]:
        ref["second"] = ref["engineers"]["PE-1003"]
        ref["second_headers"] = make_design_engineer_headers(ref["second"]["id"])
    if "PE-9001" in ref["engineers"]:
        ref["outstate"] = ref["engineers"]["PE-9001"]
        ref["outstate_headers"] = make_design_engineer_headers(ref["outstate"]["id"])
    return ref


def dealer_headers(ref, dealer="alpha"):
    return make_dealer_principal_headers(ref["dealers"][dealer]["id"])


def engineer_headers(ref, license_number="PE-1001"):
    return make_design_engineer_headers(ref["engineers"][license_number]["id"])


def sealer_headers(ref, license_number="PE-1002"):
    return make_sealing_engineer_headers(ref["engineers"][license_number]["id"])


# ---------------------------------------------------------------------------
# Tier 2 — bin designs and the review / seal lifecycle
# ---------------------------------------------------------------------------


def build_design_payload(
    ref,
    dealer="alpha",
    jurisdiction="NE-WEST",
    grain_profile="CORN",
    coating="G115",
    **geometry,
):
    return create_bin_design_payload(
        ref["dealers"][dealer]["id"],
        ref["jurisdictions"][jurisdiction]["id"],
        ref["grain_profiles"][grain_profile]["id"],
        ref["coating_specs"][coating]["id"],
        **geometry,
    )


def create_design(
    ref,
    dealer="alpha",
    jurisdiction="NE-WEST",
    grain_profile="CORN",
    coating="G115",
    engineer="PE-1001",
    **geometry,
):
    """Author a DRAFT bin design as the named engineer."""
    payload = build_design_payload(
        ref,
        dealer=dealer,
        jurisdiction=jurisdiction,
        grain_profile=grain_profile,
        coating=coating,
        **geometry,
    )
    return get_success_data(
        api_client.create_bin_design(payload, engineer_headers(ref, engineer)),
        expected_status=201,
    )


def add_analysis(ref, design, design_method=None, engineer="PE-1001", expected_version=None):
    """Run one analysis against a design, refreshing the OCC version first."""
    if expected_version is None:
        expected_version = read_design(design["id"])["version"]
    method = design_method or design["design_method"]
    return get_success_data(
        api_client.create_design_analysis(
            design["id"],
            create_design_analysis_payload(method, expected_version),
            engineer_headers(ref, engineer),
        ),
        expected_status=201,
    )


def submit_for_review(ref, design, engineer="PE-1001"):
    return get_success_data(
        api_client.submit_design_for_review(
            design["id"], engineer_headers(ref, engineer)
        )
    )


def request_revision(ref, design, sealer="PE-1002", revision_note="Please revise."):
    return get_success_data(
        api_client.request_design_revision(
            design["id"],
            request_revision_payload(revision_note),
            sealer_headers(ref, sealer),
        )
    )


def revise_design(ref, design, engineer="PE-1001", **fields):
    return get_success_data(
        api_client.revise_bin_design(
            design["id"],
            revise_bin_design_payload(**fields),
            engineer_headers(ref, engineer),
        )
    )


def seal_design(ref, design, sealer="PE-1002"):
    return get_success_data(
        api_client.seal_bin_design(design["id"], sealer_headers(ref, sealer))
    )


def create_design_under_review(ref, analysis_method=None, engineer="PE-1001", **kwargs):
    """Author a design, analyse it under its own method, and submit it.

    Returns the design row as it reads in UNDER_REVIEW.
    """
    design = create_design(ref, engineer=engineer, **kwargs)
    add_analysis(ref, design, design_method=analysis_method, engineer=engineer)
    return submit_for_review(ref, design, engineer=engineer)


def create_sealed_design(ref, engineer="PE-1001", sealer="PE-1002", **kwargs):
    """Author, analyse, submit and seal a design.  Returns the SEALED row."""
    design = create_design_under_review(ref, engineer=engineer, **kwargs)
    return seal_design(ref, design, sealer=sealer)


def create_design_awaiting_revision(ref, engineer="PE-1001", sealer="PE-1002", **kwargs):
    """Drive a design to REVISION_REQUIRED."""
    design = create_design_under_review(ref, engineer=engineer, **kwargs)
    return request_revision(ref, design, sealer=sealer)


# ---------------------------------------------------------------------------
# Tier 3 — dealer orders, deposits, confirmation and cancellation
# ---------------------------------------------------------------------------


def place_order(
    ref,
    design,
    dealer="alpha",
    order_season="OFFSEASON",
    aeration_package="NONE",
    unload_system="GRAVITY",
    **overrides,
):
    payload = create_dealer_order_payload(
        ref["dealers"][dealer]["id"],
        design["id"],
        order_season=order_season,
        aeration_package=aeration_package,
        unload_system=unload_system,
        **overrides,
    )
    return get_success_data(
        api_client.create_dealer_order(payload, dealer_headers(ref, dealer)),
        expected_status=201,
    )


def pay_deposit(ref, order, dealer="alpha", amount_cents=None):
    amount = order["required_deposit_cents"] if amount_cents is None else amount_cents
    return get_success_data(
        api_client.post_order_payment(
            order["id"], order_payment_payload(amount), dealer_headers(ref, dealer)
        )
    )


def confirm_order(ref, order, dealer="alpha"):
    return get_success_data(
        api_client.confirm_dealer_order(order["id"], dealer_headers(ref, dealer))
    )


def cancel_order(ref, order, dealer="alpha"):
    return get_success_data(
        api_client.cancel_dealer_order(order["id"], dealer_headers(ref, dealer))
    )


def reset_credit_limit(dealer, credit_limit_cents):
    return get_success_data(
        api_client.set_credit_limit(
            dealer["id"], credit_limit_payload(credit_limit_cents), ADMIN
        )
    )


def place_confirmed_order(ref, design, dealer="alpha", **order_kwargs):
    """Place an order and confirm it, leaving it QUEUED."""
    order = place_order(ref, design, dealer=dealer, **order_kwargs)
    return confirm_order(ref, order, dealer=dealer)


def place_paid_confirmed_order(ref, design, dealer="alpha", **order_kwargs):
    """Place an order, post its exact deposit and confirm it."""
    order = place_order(ref, design, dealer=dealer, **order_kwargs)
    pay_deposit(ref, order, dealer=dealer)
    return confirm_order(ref, order, dealer=dealer)


# ---------------------------------------------------------------------------
# Tier 3 — coil receipt, run scheduling and the mass ledger
# ---------------------------------------------------------------------------


def receive_coil_lot(
    ref,
    coating="G115",
    heat_number="H-70001",
    gauge_mm=TEST_DEFAULTS["COIL_GAUGE_MM"],
    received_kg=TEST_DEFAULTS["COIL_RECEIVED_KG"],
    **overrides,
):
    payload = create_coil_lot_payload(
        ref["coating_specs"][coating]["id"],
        heat_number=heat_number,
        gauge_mm=gauge_mm,
        received_kg=received_kg,
        **overrides,
    )
    return get_success_data(
        api_client.create_coil_lot(payload, PLANNER), expected_status=201
    )


def schedule_run(
    ref,
    lot,
    order,
    window_start,
    window_end,
    planned_kg,
    line="LINE_A",
    **overrides,
):
    payload = create_roll_forming_run_payload(
        ref["lines"][line]["id"],
        lot["id"],
        order["id"],
        window_start,
        window_end,
        planned_kg,
        **overrides,
    )
    return get_success_data(
        api_client.create_roll_forming_run(payload, PLANNER), expected_status=201
    )


def complete_run(run, consumed_kg, scrap_kg):
    return get_success_data(
        api_client.complete_roll_forming_run(
            run["id"], complete_run_payload(consumed_kg, scrap_kg), PLANNER
        )
    )


def void_run(run):
    return get_success_data(api_client.void_roll_forming_run(run["id"], PLANNER))


# ---------------------------------------------------------------------------
# Tier 3 — freight loads, yard staging and dispatch
# ---------------------------------------------------------------------------


def plan_freight_load(
    ref,
    dealer="alpha",
    trailer_type="FLATBED",
    allocation_basis="WEIGHT",
    yard_window_start="2026-08-10T08:00:00Z",
    yard_window_end="2026-08-12T17:00:00Z",
    expected_dealer_version=None,
    **overrides,
):
    """Plan a load, refreshing `expected_dealer_version` from the live row."""
    dealer_id = ref["dealers"][dealer]["id"]
    if expected_dealer_version is None:
        expected_dealer_version = read_dealer(dealer_id)["version"]
    payload = create_freight_load_payload(
        dealer_id,
        expected_dealer_version,
        trailer_type=trailer_type,
        allocation_basis=allocation_basis,
        yard_window_start=yard_window_start,
        yard_window_end=yard_window_end,
        **overrides,
    )
    return get_success_data(
        api_client.create_freight_load(payload, LOGISTICS), expected_status=201
    )


def attach_order(load, order):
    return get_success_data(
        api_client.assign_order_to_load(
            load["id"], assign_order_to_load_payload(order["id"]), LOGISTICS
        )
    )


def dispatch_load(load):
    return get_success_data(api_client.dispatch_freight_load(load["id"], LOGISTICS))


def deliver_load(load):
    return get_success_data(api_client.deliver_freight_load(load["id"], LOGISTICS))


def cancel_load(load):
    return get_success_data(api_client.cancel_freight_load(load["id"], LOGISTICS))


# ---------------------------------------------------------------------------
# Tier 3 — erection crews and field failure investigations
# ---------------------------------------------------------------------------


def register_crew(
    ref,
    dealer="alpha",
    crew_name="Alpha Erectors T3",
    certification_tier="T3",
    certified_until=TEST_DEFAULTS["CREW_CERTIFIED_UNTIL"],
    **overrides,
):
    payload = create_installation_crew_payload(
        ref["dealers"][dealer]["id"],
        crew_name=crew_name,
        certification_tier=certification_tier,
        certified_until=certified_until,
        **overrides,
    )
    return get_success_data(
        api_client.create_installation_crew(payload, ADMIN), expected_status=201
    )


def assign_crew(order, crew):
    return get_success_data(
        api_client.assign_crew_to_order(
            order["id"], assign_crew_payload(crew["id"]), ADMIN
        )
    )


def open_field_failure(order, **overrides):
    payload = create_field_failure_payload(order["id"], **overrides)
    return get_success_data(
        api_client.create_field_failure(payload, QUALITY), expected_status=201
    )


def start_failure_analysis(failure):
    return get_success_data(
        api_client.start_field_failure_analysis(failure["id"], QUALITY)
    )


def determine_failure(failure):
    return get_success_data(api_client.determine_field_failure(failure["id"], QUALITY))


def drive_failure_to_determination(order, **overrides):
    """Intake -> start-analysis -> determine.  Returns the DETERMINED row."""
    failure = open_field_failure(order, **overrides)
    start_failure_analysis(failure)
    return determine_failure(failure)


# ---------------------------------------------------------------------------
# Geometry variants used by more than one scenario
# ---------------------------------------------------------------------------

# The canonical 12.0 m x 9.6 m ASD bin lives in factories.D1_GEOMETRY.
GEOMETRY_DEEP = {"eave_height_m": 12.8, "moisture_pct": 17.5}
GEOMETRY_WIDE = {"diameter_m": 15.5, "eave_height_m": 12.0}
GEOMETRY_MID = {"diameter_m": 13.5, "eave_height_m": 11.2}


def add_dealer(ref, key, jurisdiction="NE-WEST", **overrides):
    """Register one extra dealership and file it in ``ref["dealers"][key]``."""
    dealer = register_dealer(ref["jurisdictions"][jurisdiction]["id"], **overrides)
    ref["dealers"][key] = dealer
    return dealer


def place_queued_paid_order(ref, design, dealer="alpha", **order_kwargs):
    """Place an order, confirm it to QUEUED, then post its exact deposit."""
    order = place_order(ref, design, dealer=dealer, **order_kwargs)
    confirm_order(ref, order, dealer=dealer)
    pay_deposit(ref, order, dealer=dealer)
    return read_order(order["id"])


# ---------------------------------------------------------------------------
# Tier 4 — composite scenarios
# ---------------------------------------------------------------------------


def setup_dense_and_bulky_orders():
    """Two DRAFT orders whose kits differ sharply in density.

    The bare sheet-and-stiffener kit is dense; the drying-and-power-sweep kit
    on the deeper bin is bulky.  Both belong to dealer Alpha and neither is
    attached to a load yet.
    """
    ref = setup_reference_data()
    dense_design = create_design(ref)
    bulky_design = create_design(ref, **GEOMETRY_DEEP)
    dense_order = place_order(ref, dense_design)
    bulky_order = place_order(
        ref,
        bulky_design,
        aeration_package="DRYING_FULL",
        unload_system="POWER_SWEEP",
    )
    return {
        "ref": ref,
        "dense_design": dense_design,
        "bulky_design": bulky_design,
        "dense_order": dense_order,
        "bulky_order": bulky_order,
    }


def setup_order_with_crew():
    """A DRAFT order on an UNDER_REVIEW design plus a T3 crew for the dealer."""
    ref = setup_reference_data()
    design = create_design_under_review(ref)
    order = place_order(ref, design)
    crew = register_crew(ref)
    return {"ref": ref, "design": design, "order": order, "crew": crew}


def setup_recall_cascade_chain():
    """A QUEUED order on a loaded trailer with a structural failure mid-analysis.

    Determining the failure recalls the design, holds the order, detaches it
    from the load and empties the trailer.
    """
    ref = setup_reference_data()
    design = create_design_under_review(ref)
    order = place_confirmed_order(ref, design)
    load = plan_freight_load(
        ref,
        trailer_type="FLATBED",
        allocation_basis="WEIGHT",
        yard_window_start="2026-09-10T00:00:00Z",
        yard_window_end="2026-09-12T00:00:00Z",
    )
    load = attach_order(load, order)
    failure = open_field_failure(
        order,
        failure_mode="SIDEWALL_BUCKLE",
        observed_load_kpa=20.0,
        measured_coating_loss_pct=10.0,
        service_years=3.0,
    )
    failure = start_failure_analysis(failure)
    return {
        "ref": ref,
        "design": design,
        "order": order,
        "load": load,
        "failure": failure,
    }


def setup_credit_hold_pair():
    """Two QUEUED orders driven into HOLD_CREDIT by a lowered credit limit.

    The limit ends one cent short of the committed total, so the dealer sits in
    CREDIT_HOLD with ``credit_available_cents`` at -1.
    """
    ref = setup_reference_data()
    design = create_design_under_review(ref)
    first = place_confirmed_order(ref, design)
    second = place_confirmed_order(ref, design)
    committed = read_dealer(ref["alpha"]["id"])["credit_committed_cents"]
    reset_credit_limit(ref["alpha"], committed - 1)
    return {
        "ref": ref,
        "design": design,
        "first": read_order(first["id"]),
        "second": read_order(second["id"]),
        "committed": committed,
    }


def setup_unsealed_confirm_conflict():
    """A seal-required jurisdiction, a broke dealer and an unsealed design.

    Confirming the order violates both the seal requirement and the credit
    limit at once.
    """
    ref = setup_reference_data()
    add_dealer(
        ref,
        "gamma",
        jurisdiction="IA-CENTRAL",
        name="Gamma Grain Co",
        region_code="IA-01",
        credit_limit_cents=0,
        program_tier="BASE",
        staging_slots=2,
        high_cube_access=False,
    )
    design = create_design_under_review(
        ref, dealer="gamma", jurisdiction="IA-CENTRAL"
    )
    order = place_order(ref, design, dealer="gamma")
    return {"ref": ref, "design": design, "order": order}


def setup_crew_conflict_pair():
    """A wide bin owned by Alpha and two crews belonging to Pinnacle.

    The T1 crew is too small for the bin and also on the wrong dealership; the
    T3 crew repairs only the size defect.
    """
    ref = setup_reference_data()
    design = create_design(ref, **GEOMETRY_WIDE)
    order = place_order(ref, design)
    small_crew = register_crew(
        ref, dealer="pinnacle", crew_name="Pinnacle Erectors T1", certification_tier="T1"
    )
    large_crew = register_crew(
        ref, dealer="pinnacle", crew_name="Pinnacle Erectors T3", certification_tier="T3"
    )
    return {
        "ref": ref,
        "design": design,
        "order": order,
        "small_crew": small_crew,
        "large_crew": large_crew,
    }


def setup_high_cube_utilization_pair():
    """Two HIGH_CUBE_VAN loads of three kits each on disjoint yard windows.

    One trailer lands a hair under the cube-utilization floor and the other
    lands exactly on it.  Every order is QUEUED with its deposit paid, so the
    floor is the only gate left.
    """
    ref = setup_reference_data()
    under_design = create_design_under_review(ref, **GEOMETRY_MID)
    exact_design = create_design_under_review(ref)
    under_orders = [
        place_queued_paid_order(ref, under_design) for _ in range(3)
    ]
    exact_orders = [
        place_queued_paid_order(
            ref, exact_design, aeration_package="AERATION", unload_system="SWEEP_AUGER"
        )
        for _ in range(3)
    ]
    under_load = plan_freight_load(
        ref,
        trailer_type="HIGH_CUBE_VAN",
        allocation_basis="CUBE",
        yard_window_start="2026-09-10T00:00:00Z",
        yard_window_end="2026-09-12T00:00:00Z",
    )
    for order in under_orders:
        under_load = attach_order(under_load, order)
    exact_load = plan_freight_load(
        ref,
        trailer_type="HIGH_CUBE_VAN",
        allocation_basis="CUBE",
        yard_window_start="2026-09-20T00:00:00Z",
        yard_window_end="2026-09-22T00:00:00Z",
    )
    for order in exact_orders:
        exact_load = attach_order(exact_load, order)
    return {
        "ref": ref,
        "under_design": under_design,
        "exact_design": exact_design,
        "under_orders": under_orders,
        "exact_orders": exact_orders,
        "under_load": under_load,
        "exact_load": exact_load,
    }


def setup_partially_paid_load():
    """A FLATBED carrying two QUEUED orders, only the first of which has paid."""
    ref = setup_reference_data()
    design = create_design_under_review(ref)
    paid = place_queued_paid_order(ref, design)
    unpaid = place_confirmed_order(ref, design)
    load = plan_freight_load(
        ref,
        trailer_type="FLATBED",
        allocation_basis="WEIGHT",
        yard_window_start="2026-09-10T00:00:00Z",
        yard_window_end="2026-09-12T00:00:00Z",
    )
    load = attach_order(load, paid)
    load = attach_order(load, unpaid)
    return {
        "ref": ref,
        "design": design,
        "paid": read_order(paid["id"]),
        "unpaid": read_order(unpaid["id"]),
        "load": load,
    }


def setup_coating_quarantine_chain():
    """A scheduled run on a matched lot, plus a corrosion failure mid-analysis.

    Determining the failure quarantines every lot sharing the design's coating
    and voids the run standing on it; the differently coated lot is untouched.
    """
    ref = setup_reference_data()
    design = create_design_under_review(ref)
    order = place_confirmed_order(ref, design)
    matched_lot = receive_coil_lot(ref, coating="G115", heat_number="H-77")
    other_lot = receive_coil_lot(ref, coating="G90", heat_number="H-88")
    run = schedule_run(
        ref,
        matched_lot,
        order,
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
        6600,
    )
    failure = open_field_failure(
        order,
        failure_mode="CORROSION_PERFORATION",
        observed_load_kpa=5.0,
        measured_coating_loss_pct=55.0,
        service_years=12.0,
    )
    failure = start_failure_analysis(failure)
    return {
        "ref": ref,
        "design": design,
        "order": order,
        "matched_lot": matched_lot,
        "other_lot": other_lot,
        "run": run,
        "failure": failure,
    }


def setup_line_window_anchor():
    """One anchor run 08:00-12:00 on LINE_A, plus a same- and cross-coating lot."""
    ref = setup_reference_data()
    design = create_design_under_review(ref)
    order = place_confirmed_order(ref, design)
    same_lot = receive_coil_lot(ref, coating="G115", heat_number="H-77")
    other_lot = receive_coil_lot(ref, coating="G90", heat_number="H-88")
    anchor = schedule_run(
        ref,
        same_lot,
        order,
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
        6600,
    )
    return {
        "ref": ref,
        "design": design,
        "order": order,
        "same_lot": same_lot,
        "other_lot": other_lot,
        "anchor": anchor,
    }


def setup_yard_window_anchor():
    """A dealer with two staging slots holding one PLANNED load over 09-10..09-12."""
    ref = setup_reference_data()
    load = plan_freight_load(
        ref,
        trailer_type="FLATBED",
        allocation_basis="WEIGHT",
        yard_window_start="2026-09-10T00:00:00Z",
        yard_window_end="2026-09-12T00:00:00Z",
    )
    return {"ref": ref, "load": load}


def setup_depleted_coil_lot():
    """One lot reserved to exhaustion by two adjacent runs on the same line."""
    ref = setup_reference_data()
    design = create_design_under_review(ref)
    order = place_confirmed_order(ref, design)
    lot = receive_coil_lot(ref, coating="G115", heat_number="H-77")
    first_run = schedule_run(
        ref, lot, order, "2026-08-03T08:00:00Z", "2026-08-03T12:00:00Z", 6600
    )
    second_run = schedule_run(
        ref, lot, order, "2026-08-03T12:00:00Z", "2026-08-03T16:00:00Z", 13400
    )
    return {
        "ref": ref,
        "design": design,
        "order": order,
        "lot": lot,
        "first_run": first_run,
        "second_run": second_run,
    }


def setup_credit_ledger_orders():
    """Four identical orders on one design: three confirmed, one left in DRAFT."""
    ref = setup_reference_data()
    design = create_design_under_review(ref)
    confirmed = [place_confirmed_order(ref, design) for _ in range(3)]
    draft = place_order(ref, design)
    return {
        "ref": ref,
        "design": design,
        "confirmed": [read_order(o["id"]) for o in confirmed],
        "draft": draft,
    }


def setup_design_listing_set():
    """Five bin designs across two dealerships and two authors, in create order.

    Alpha holds three (two by PE-1001, one by PE-1003) and Pinnacle holds two
    (one by PE-1001, one by PE-1003), so a dealer filter and an author filter
    intersect on exactly one row.
    """
    ref = setup_reference_data()
    alpha_one = create_design(ref, dealer="alpha", engineer="PE-1001")
    alpha_two = create_design(ref, dealer="alpha", engineer="PE-1001")
    alpha_three = create_design(ref, dealer="alpha", engineer="PE-1003")
    pinnacle_one = create_design(ref, dealer="pinnacle", engineer="PE-1001")
    pinnacle_two = create_design(ref, dealer="pinnacle", engineer="PE-1003")
    return {
        "ref": ref,
        "alpha_designs": [alpha_one, alpha_two, alpha_three],
        "pinnacle_designs": [pinnacle_one, pinnacle_two],
        "all_designs": [
            alpha_one,
            alpha_two,
            alpha_three,
            pinnacle_one,
            pinnacle_two,
        ],
    }
