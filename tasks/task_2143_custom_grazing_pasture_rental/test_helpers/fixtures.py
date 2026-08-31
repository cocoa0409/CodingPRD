"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database. Setup calls use
the lenient validator so a broken precondition reports as a setup failure
rather than as a confusing assertion further down.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    capacity_assessment_payload,
    cattle_owner_payload,
    contract_payload,
    death_loss_payload,
    drought_reading_payload,
    grazier_payload,
    infrastructure_ticket_payload,
    lot_payload,
    out_weight_payload,
    pasture_payload,
    range_consultant_payload,
    receive_payload,
    settlement_payload,
    treatment_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    make_cattle_owner_headers,
    make_grazier_headers,
    make_range_consultant_headers,
)


class World(dict):
    """A setup result addressed either as a dict or by attribute."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer aid only
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ===========================================================================
# Tier 0 — single-call helpers
# ===========================================================================

def set_logical_clock(iso_instant: str) -> dict:
    """Move the server's logical clock to the supplied instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso_instant}, ADMIN_HEADERS))


def create_grazier(**overrides) -> dict:
    return get_success_data(
        api_client.register_grazier(grazier_payload(**overrides), ADMIN_HEADERS)
    )


def create_cattle_owner(**overrides) -> dict:
    return get_success_data(
        api_client.register_cattle_owner(cattle_owner_payload(**overrides), ADMIN_HEADERS)
    )


def create_range_consultant(**overrides) -> dict:
    return get_success_data(
        api_client.register_range_consultant(
            range_consultant_payload(**overrides), ADMIN_HEADERS
        )
    )


def create_pasture(grazier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_pasture(pasture_payload(**overrides), make_grazier_headers(grazier_id))
    )


def read_pasture(pasture_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.get_pasture(pasture_id, make_grazier_headers(grazier_id))
    )


def read_contract(contract_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.get_contract(contract_id, make_grazier_headers(grazier_id))
    )


def read_lot(lot_id: str, grazier_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, make_grazier_headers(grazier_id)))


def read_settlement(settlement_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.get_settlement(settlement_id, make_grazier_headers(grazier_id))
    )


def read_owner(owner_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.get_cattle_owner(owner_id, make_grazier_headers(grazier_id))
    )


def read_ticket(ticket_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.get_infrastructure_ticket(ticket_id, make_grazier_headers(grazier_id))
    )


def file_capacity_assessment(pasture_id: str, consultant_id: str, grazier_id: str,
                             expected_pasture_version=None, **overrides) -> dict:
    """File an assessment, reading the pasture's live version when none is given."""
    if expected_pasture_version is None:
        expected_pasture_version = read_pasture(pasture_id, grazier_id)["version"]
    return get_success_data(
        api_client.create_capacity_assessment(
            pasture_id,
            capacity_assessment_payload(expected_pasture_version, **overrides),
            make_range_consultant_headers(consultant_id),
        )
    )


def set_pasture_status(pasture_id: str, grazier_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.set_pasture_status(
            pasture_id, {"to_status": to_status}, make_grazier_headers(grazier_id)
        )
    )


def file_drought_reading(pasture_id: str, consultant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_drought_reading(
            pasture_id,
            drought_reading_payload(**overrides),
            make_range_consultant_headers(consultant_id),
        )
    )


def create_contract(grazier_id: str, cattle_owner_id: str, pasture_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(
            contract_payload(cattle_owner_id, pasture_id, **overrides),
            make_grazier_headers(grazier_id),
        )
    )


def submit_contract(contract_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.submit_contract(contract_id, make_grazier_headers(grazier_id))
    )


def sign_contract(contract_id: str, owner_id: str, signature_ref: str = "SIG-K1") -> dict:
    return get_success_data(
        api_client.sign_contract(
            contract_id, {"signature_ref": signature_ref}, make_cattle_owner_headers(owner_id)
        )
    )


def create_lot(contract_id: str, grazier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(
            contract_id, lot_payload(**overrides), make_grazier_headers(grazier_id)
        )
    )


def receive_lot(lot_id: str, grazier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.receive_lot(
            lot_id, receive_payload(**overrides), make_grazier_headers(grazier_id)
        )
    )


def weigh_out_lot(lot_id: str, grazier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_weight_event(
            lot_id, out_weight_payload(**overrides), make_grazier_headers(grazier_id)
        )
    )


def record_treatment(lot_id: str, grazier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_treatment(
            lot_id, treatment_payload(**overrides), make_grazier_headers(grazier_id)
        )
    )


def review_treatment_as_owner(treatment_id: str, owner_id: str, decision: str, note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.review_treatment(treatment_id, payload, make_cattle_owner_headers(owner_id))
    )


def review_treatment_as_grazier(treatment_id: str, grazier_id: str, decision: str,
                                note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.review_treatment(treatment_id, payload, make_grazier_headers(grazier_id))
    )


def report_death_loss(lot_id: str, grazier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_death_loss(
            lot_id, death_loss_payload(**overrides), make_grazier_headers(grazier_id)
        )
    )


def review_death_loss_as_consultant(report_id: str, consultant_id: str, decision: str,
                                    note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.review_death_loss(
            report_id, payload, make_range_consultant_headers(consultant_id)
        )
    )


def review_death_loss_as_grazier(report_id: str, grazier_id: str, decision: str,
                                 note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.review_death_loss(report_id, payload, make_grazier_headers(grazier_id))
    )


def open_infrastructure_ticket(pasture_id: str, contract_id: str, headers: dict,
                               **overrides) -> dict:
    return get_success_data(
        api_client.create_infrastructure_ticket(
            infrastructure_ticket_payload(pasture_id, contract_id, **overrides), headers
        )
    )


def assign_infrastructure_ticket(ticket_id: str, grazier_id: str, repair_party: str) -> dict:
    return get_success_data(
        api_client.assign_infrastructure_ticket(
            ticket_id, {"repair_party": repair_party}, make_grazier_headers(grazier_id)
        )
    )


def complete_infrastructure_ticket(ticket_id: str, headers: dict, repair_cost_cents: int,
                                   cause: str, completed_at: str) -> dict:
    return get_success_data(
        api_client.complete_infrastructure_ticket(
            ticket_id,
            {
                "repair_cost_cents": repair_cost_cents,
                "cause": cause,
                "completed_at": completed_at,
            },
            headers,
        )
    )


def draft_settlement(contract_id: str, lot_id: str, grazier_id: str,
                     expected_contract_version=None) -> dict:
    """Draft a settlement, reading the contract's live version when none is given."""
    if expected_contract_version is None:
        expected_contract_version = read_contract(contract_id, grazier_id)["version"]
    return get_success_data(
        api_client.create_settlement(
            settlement_payload(contract_id, lot_id, expected_contract_version),
            make_grazier_headers(grazier_id),
        )
    )


def issue_settlement(settlement_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.issue_settlement(settlement_id, make_grazier_headers(grazier_id))
    )


def dispute_settlement(settlement_id: str, owner_id: str,
                       disputed_field: str = "SHRUNK_GAIN_LBS",
                       claimed_shrunk_gain_lbs: float = 14000, note=None) -> dict:
    payload = {
        "disputed_field": disputed_field,
        "claimed_shrunk_gain_lbs": claimed_shrunk_gain_lbs,
    }
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.dispute_settlement(settlement_id, payload, make_cattle_owner_headers(owner_id))
    )


def adjudicate_settlement(settlement_id: str, consultant_id: str, resolution: str,
                          note=None) -> dict:
    payload = {"resolution": resolution}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.adjudicate_settlement(
            settlement_id, payload, make_range_consultant_headers(consultant_id)
        )
    )


def reissue_settlement(settlement_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.reissue_settlement(settlement_id, make_grazier_headers(grazier_id))
    )


def finalize_settlement_as_owner(settlement_id: str, owner_id: str) -> dict:
    return get_success_data(
        api_client.finalize_settlement(settlement_id, make_cattle_owner_headers(owner_id))
    )


def finalize_settlement_as_grazier(settlement_id: str, grazier_id: str) -> dict:
    return get_success_data(
        api_client.finalize_settlement(settlement_id, make_grazier_headers(grazier_id))
    )


def void_settlement(settlement_id: str, grazier_id: str, reason: str) -> dict:
    return get_success_data(
        api_client.void_settlement(
            settlement_id, {"reason": reason}, make_grazier_headers(grazier_id)
        )
    )


# ===========================================================================
# Tier 1 — parties
# ===========================================================================

def setup_parties(owner_credit_limit: int = 5_000_000, second_consultant: bool = False,
                  second_grazier: bool = False, second_owner: bool = False) -> World:
    """Register the parties every scenario needs and cache their headers."""
    world = World()
    world.grazier = create_grazier()
    world.grazier_id = world.grazier["id"]
    world.grazier_headers = make_grazier_headers(world.grazier_id)

    world.owner = create_cattle_owner(credit_limit_cents=owner_credit_limit)
    world.owner_id = world.owner["id"]
    world.owner_headers = make_cattle_owner_headers(world.owner_id)

    world.consultant = create_range_consultant()
    world.consultant_id = world.consultant["id"]
    world.consultant_headers = make_range_consultant_headers(world.consultant_id)

    if second_consultant:
        world.consultant2 = create_range_consultant(
            full_name="Kim Alvarez", certification_number="RC-2288"
        )
        world.consultant2_id = world.consultant2["id"]
        world.consultant2_headers = make_range_consultant_headers(world.consultant2_id)

    if second_grazier:
        world.grazier2 = create_grazier(
            business_name="Two Creek Grazing", liability_carrier="Range Mutual"
        )
        world.grazier2_id = world.grazier2["id"]
        world.grazier2_headers = make_grazier_headers(world.grazier2_id)

    if second_owner:
        world.owner2 = create_cattle_owner(
            legal_name="Two Dot Livestock", brand_registration="MT-9000",
            credit_limit_cents=5_000_000,
        )
        world.owner2_id = world.owner2["id"]
        world.owner2_headers = make_cattle_owner_headers(world.owner2_id)

    return world


# ===========================================================================
# Tier 2 — pasture / contract / lot hierarchy
# ===========================================================================

def provision_available_pasture(world: World, pasture=None, assessment=None):
    """Create a pasture, rate it once and move it to AVAILABLE.

    Returns (refreshed_pasture, assessment).
    """
    created = create_pasture(world.grazier_id, **(pasture or {}))
    rating = file_capacity_assessment(
        created["id"], world.consultant_id, world.grazier_id, **(assessment or {})
    )
    set_pasture_status(created["id"], world.grazier_id, "AVAILABLE")
    return read_pasture(created["id"], world.grazier_id), rating


def provision_draft_pasture(world: World, pasture=None):
    """Create a pasture and leave it in DRAFT with no assessment at all."""
    return create_pasture(world.grazier_id, **(pasture or {}))


def provision_active_contract(world: World, pasture_id: str, signature_ref="SIG-K1",
                              **contract_overrides) -> dict:
    """Draft, submit and sign a contract so it lands in ACTIVE."""
    contract = create_contract(
        world.grazier_id, world.owner_id, pasture_id, **contract_overrides
    )
    submit_contract(contract["id"], world.grazier_id)
    sign_contract(contract["id"], world.owner_id, signature_ref)
    return read_contract(contract["id"], world.grazier_id)


def provision_pending_contract(world: World, pasture_id: str, **contract_overrides) -> dict:
    """Draft and submit a contract so it rests in PENDING_SIGNATURE."""
    contract = create_contract(
        world.grazier_id, world.owner_id, pasture_id, **contract_overrides
    )
    submit_contract(contract["id"], world.grazier_id)
    return read_contract(contract["id"], world.grazier_id)


def provision_lot_on_feed(world: World, contract_id: str, lot=None, receive=None) -> dict:
    """Book a delivery against an ACTIVE contract and receive it."""
    booked = create_lot(contract_id, world.grazier_id, **(lot or {}))
    receive_lot(booked["id"], world.grazier_id, **(receive or {}))
    return read_lot(booked["id"], world.grazier_id)


# ===========================================================================
# Tier 3 — the North Bench lifecycle shortcuts
# ===========================================================================

def setup_north_bench_available(owner_credit_limit: int = 5_000_000,
                                second_consultant: bool = False,
                                second_grazier: bool = False,
                                second_owner: bool = False,
                                pasture=None, assessment=None) -> World:
    """Parties plus North Bench AVAILABLE at 20769 rated head-days."""
    world = setup_parties(
        owner_credit_limit=owner_credit_limit,
        second_consultant=second_consultant,
        second_grazier=second_grazier,
        second_owner=second_owner,
    )
    world.pasture, world.assessment = provision_available_pasture(
        world, pasture=pasture, assessment=assessment
    )
    world.pasture_id = world.pasture["id"]
    return world


def setup_north_bench_active_contract(contract=None, **kwargs) -> World:
    """North Bench AVAILABLE plus contract K1 in ACTIVE."""
    world = setup_north_bench_available(**kwargs)
    world.contract = provision_active_contract(
        world, world.pasture_id, **(contract or {})
    )
    world.contract_id = world.contract["id"]
    return world


def setup_north_bench_lot_on_feed(lot=None, receive=None, **kwargs) -> World:
    """Contract K1 ACTIVE with lot L1 ON_FEED (150 head at 63745 lb gross)."""
    world = setup_north_bench_active_contract(**kwargs)
    world.lot = provision_lot_on_feed(world, world.contract_id, lot=lot, receive=receive)
    world.lot_id = world.lot["id"]
    return world


def setup_north_bench_weighed_out(out=None, **kwargs) -> World:
    """Lot L1 driven all the way to WEIGHED_OUT."""
    world = setup_north_bench_lot_on_feed(**kwargs)
    world.out_event = weigh_out_lot(world.lot_id, world.grazier_id, **(out or {}))
    world.lot = read_lot(world.lot_id, world.grazier_id)
    return world


def setup_north_bench_settlement_draft(clock: str = "2026-11-12T00:00:00Z", **kwargs) -> World:
    """A DRAFT settlement over the weighed-out North Bench lot."""
    world = setup_north_bench_weighed_out(**kwargs)
    if clock is not None:
        set_logical_clock(clock)
    world.settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)
    world.settlement_id = world.settlement["id"]
    return world


def setup_north_bench_settlement_issued(**kwargs) -> World:
    """The same settlement, issued and therefore inside its dispute window."""
    world = setup_north_bench_settlement_draft(**kwargs)
    world.settlement = issue_settlement(world.settlement_id, world.grazier_id)
    return world


def setup_north_bench_settlement_disputed(claimed_shrunk_gain_lbs: float = 14000,
                                          note: str = "Gain is short", **kwargs) -> World:
    """The settlement after the owner has opened a dispute round."""
    world = setup_north_bench_settlement_issued(**kwargs)
    world.settlement = dispute_settlement(
        world.settlement_id, world.owner_id,
        claimed_shrunk_gain_lbs=claimed_shrunk_gain_lbs, note=note,
    )
    return world


# ===========================================================================
# Named units and contract term sets used by the multi-pasture scenarios
# ===========================================================================

HOME_FIELD = {
    "name": "Home Field", "acres": 200, "forage_type": "IMPROVED_PASTURE",
    "water_source_type": "WELL", "fence_class": "CLASS_A", "prior_season_head_days": 0,
}
CREEK_FIELD = {
    "name": "Creek Field", "acres": 200, "forage_type": "IMPROVED_PASTURE",
    "water_source_type": "CREEK", "fence_class": "CLASS_A", "prior_season_head_days": 0,
}
SCHOOL_SECTION = {
    "name": "School Section", "acres": 300, "forage_type": "COOL_SEASON_MIX",
    "water_source_type": "WELL", "fence_class": "CLASS_B", "prior_season_head_days": 0,
}
RIMROCK = {
    "name": "Rimrock", "acres": 100, "forage_type": "NATIVE_RANGE",
    "water_source_type": "POND", "fence_class": "CLASS_C", "prior_season_head_days": 0,
}
SAGE_FLAT = {
    "name": "Sage Flat", "acres": 700, "forage_type": "IMPROVED_PASTURE",
    "water_source_type": "PIPELINE", "fence_class": "CLASS_A", "prior_season_head_days": 0,
}
BIG_COULEE = {
    "name": "Big Coulee", "acres": 1500, "forage_type": "WARM_SEASON_MIX",
    "water_source_type": "CREEK", "fence_class": "CLASS_A", "prior_season_head_days": 0,
}
COULEE_A = {
    "name": "Coulee A", "acres": 600, "forage_type": "NATIVE_RANGE",
    "water_source_type": "WELL", "fence_class": "CLASS_B", "prior_season_head_days": 0,
}
COULEE_B = dict(COULEE_A, name="Coulee B")

# Assessment inputs, all walked on 2026-07-15.
DM_1600_AT_25 = {"forage_dry_matter_lbs_per_acre": 1600, "utilization_pct": 25}
DM_1700_AT_25 = {"forage_dry_matter_lbs_per_acre": 1700, "utilization_pct": 25}
DM_2000_AT_30 = {"forage_dry_matter_lbs_per_acre": 2000, "utilization_pct": 30}
DM_1300_AT_20 = {"forage_dry_matter_lbs_per_acre": 1300, "utilization_pct": 20}

# A plain per-head-per-day term set with no shrink and no cost sharing.
SIMPLE_HEAD_DAY_TERMS = {
    "billing_mode": "PER_HEAD_PER_DAY",
    "rate_cents": 100,
    "shrink_pct": 0,
    "out_shrink_pct": 0,
    "head_count_committed": 20,
    "head_value_cents": 100000,
    "start_date": "2026-08-10",
    "end_date": "2026-11-10",
    "min_days": 60,
    "treatment_cost_split_pct": 0,
    "water_responsibility": "GRAZIER",
    "fence_responsibility": "GRAZIER",
    "infrastructure_owner_cap_cents": 100000,
    "death_loss_terms": "OWNER_BEARS_ALL",
    "death_loss_threshold_pct": 2.0,
}

SCHOOL_SECTION_TERMS = {
    "billing_mode": "PER_HEAD_PER_DAY",
    "rate_cents": 95,
    "shrink_pct": 3.0,
    "out_shrink_pct": 0,
    "head_count_committed": 40,
    "head_value_cents": 130000,
    "start_date": "2026-08-10",
    "end_date": "2026-11-10",
    "min_days": 60,
    "treatment_cost_split_pct": 50,
    "water_responsibility": "GRAZIER",
    "fence_responsibility": "GRAZIER",
    "infrastructure_owner_cap_cents": 100000,
    "death_loss_terms": "OWNER_BEARS_ALL",
    "death_loss_threshold_pct": 2.0,
}


# ===========================================================================
# Tier 4 — threshold and ledger targeting
# ===========================================================================

def setup_delinquency_world(clock: str = "2026-11-12T00:00:00Z", issue: bool = True,
                            overlapping_contract: bool = False,
                            clean_second_contract: bool = False) -> World:
    """Owner with a 150000-cent limit whose 184000-cent settlement tips them over.

    Home Field carries ACTIVE contract K6 with lot L6 weighed out; Creek Field
    carries K7 sitting in PENDING_SIGNATURE. When ``issue`` is true the
    settlement is issued, so the owner is DELINQUENT and K7 has been suspended.

    ``overlapping_contract`` adds K8 on Home Field for 2026-10-01 to 2026-12-01
    AFTER the delinquency, so it is PENDING_SIGNATURE and its window overlaps K6.
    ``clean_second_contract`` adds K9 on Creek Field for a 2027 window that
    conflicts with nothing, also drafted after the delinquency.
    """
    world = setup_parties(owner_credit_limit=150000)

    world.home_field, _ = provision_available_pasture(
        world, pasture=HOME_FIELD, assessment=DM_1600_AT_25
    )
    world.contract_k6 = provision_active_contract(
        world, world.home_field["id"], signature_ref="SIG-K6", **SIMPLE_HEAD_DAY_TERMS
    )
    world.lot_l6 = provision_lot_on_feed(
        world, world.contract_k6["id"],
        lot={"scheduled_head_count": 20, "scheduled_delivery_date": "2026-08-10"},
        receive={
            "head_count_received": 20, "gross_weight_lbs": 10000,
            "scale_ticket_ref": "T6-IN", "received_at": "2026-08-10T09:00:00Z",
        },
    )
    weigh_out_lot(
        world.lot_l6["id"], world.grazier_id,
        gross_weight_lbs=13000, head_count=20,
        scale_ticket_ref="T6-OUT", weighed_at="2026-11-10T09:00:00Z",
    )

    world.creek_field, _ = provision_available_pasture(
        world, pasture=CREEK_FIELD, assessment=DM_1600_AT_25
    )
    world.contract_k7 = provision_pending_contract(
        world, world.creek_field["id"], **dict(SIMPLE_HEAD_DAY_TERMS, head_count_committed=15)
    )

    set_logical_clock(clock)
    world.settlement = draft_settlement(
        world.contract_k6["id"], world.lot_l6["id"], world.grazier_id
    )
    world.settlement_id = world.settlement["id"]

    if issue:
        world.settlement = issue_settlement(world.settlement_id, world.grazier_id)

    if overlapping_contract:
        world.contract_k8 = provision_pending_contract(
            world, world.home_field["id"],
            **dict(SIMPLE_HEAD_DAY_TERMS, head_count_committed=15,
                   start_date="2026-10-01", end_date="2026-12-01", min_days=30)
        )

    if clean_second_contract:
        world.contract_k9 = provision_pending_contract(
            world, world.creek_field["id"],
            **dict(SIMPLE_HEAD_DAY_TERMS, head_count_committed=15,
                   start_date="2027-04-01", end_date="2027-07-01")
        )

    return world


def setup_school_section_lot_on_feed(death_loss: bool = True) -> World:
    """School Section rated at 4615 head-days with contract K4 ACTIVE on 40 head.

    Lot L4 received 40 head at 22000 lb gross (3 percent shrink -> 21340 lb).
    When ``death_loss`` is true a 2-head DISEASE loss dated 2026-09-09 is
    already CONFIRMED.
    """
    world = setup_parties()
    world.pasture, world.assessment = provision_available_pasture(
        world, pasture=SCHOOL_SECTION, assessment=DM_1600_AT_25
    )
    world.pasture_id = world.pasture["id"]
    world.contract = provision_active_contract(
        world, world.pasture_id, signature_ref="SIG-K4", **SCHOOL_SECTION_TERMS
    )
    world.contract_id = world.contract["id"]
    world.lot = provision_lot_on_feed(
        world, world.contract_id,
        lot={"scheduled_head_count": 40, "scheduled_delivery_date": "2026-08-10"},
        receive={
            "head_count_received": 40, "gross_weight_lbs": 22000,
            "scale_ticket_ref": "T4-IN", "received_at": "2026-08-10T09:00:00Z",
        },
    )
    world.lot_id = world.lot["id"]

    if death_loss:
        world.death_report = report_death_loss(
            world.lot_id, world.grazier_id,
            death_date="2026-09-09", head_lost=2, cause="DISEASE", necropsy_performed=True,
        )
        world.death_report = review_death_loss_as_consultant(
            world.death_report["id"], world.consultant_id, "CONFIRM"
        )
    return world


def setup_rated_pasture_world(pasture: dict, assessment: dict, **party_kw) -> World:
    """Any named unit rated once and moved to AVAILABLE."""
    world = setup_parties(**party_kw)
    world.pasture, world.assessment = provision_available_pasture(
        world, pasture=pasture, assessment=assessment
    )
    world.pasture_id = world.pasture["id"]
    return world


def setup_gain_billed_lot(pasture: dict, assessment: dict, contract_terms: dict,
                          lot_head: int, gross_in_lbs: float, gross_out_lbs: float,
                          out_weighed_at: str, clock: str) -> World:
    """A weighed-out, gain-billed lot on a purpose-rated unit, clock advanced."""
    world = setup_rated_pasture_world(pasture, assessment)
    world.contract = provision_active_contract(
        world, world.pasture_id, signature_ref="SIG-GAIN", **contract_terms
    )
    world.contract_id = world.contract["id"]
    world.lot = provision_lot_on_feed(
        world, world.contract_id,
        lot={"scheduled_head_count": lot_head, "scheduled_delivery_date": "2026-08-10"},
        receive={
            "head_count_received": lot_head, "gross_weight_lbs": gross_in_lbs,
            "scale_ticket_ref": "TG-IN", "received_at": "2026-08-10T09:00:00Z",
        },
    )
    world.lot_id = world.lot["id"]
    weigh_out_lot(
        world.lot_id, world.grazier_id,
        gross_weight_lbs=gross_out_lbs, head_count=lot_head,
        scale_ticket_ref="TG-OUT", weighed_at=out_weighed_at,
    )
    world.lot = read_lot(world.lot_id, world.grazier_id)
    set_logical_clock(clock)
    return world


def setup_two_contracts_two_liability_regimes() -> World:
    """Two 600-acre units, each with one 100-head lot and one REPORTED 3-head loss.

    Contract KA is OWNER_BEARS_ALL; contract KB is GRAZIER_SHARE_ABOVE_THRESHOLD
    at 2.0 percent. Both declare head_value_cents 130000.
    """
    world = setup_parties()
    terms = dict(
        SIMPLE_HEAD_DAY_TERMS, head_count_committed=100, head_value_cents=130000
    )

    world.pasture_a, _ = provision_available_pasture(
        world, pasture=COULEE_A, assessment=DM_1700_AT_25
    )
    world.contract_a = provision_active_contract(
        world, world.pasture_a["id"], signature_ref="SIG-KA",
        **dict(terms, death_loss_terms="OWNER_BEARS_ALL"),
    )
    world.lot_a = provision_lot_on_feed(
        world, world.contract_a["id"],
        lot={"scheduled_head_count": 100, "scheduled_delivery_date": "2026-08-10"},
        receive={
            "head_count_received": 100, "gross_weight_lbs": 50000,
            "scale_ticket_ref": "TA-1", "received_at": "2026-08-10T09:00:00Z",
        },
    )
    world.report_a = report_death_loss(
        world.lot_a["id"], world.grazier_id,
        death_date="2026-08-25", head_lost=3, cause="DISEASE", necropsy_performed=True,
    )

    world.pasture_b, _ = provision_available_pasture(
        world, pasture=COULEE_B, assessment=DM_1700_AT_25
    )
    world.contract_b = provision_active_contract(
        world, world.pasture_b["id"], signature_ref="SIG-KB",
        **dict(terms, death_loss_terms="GRAZIER_SHARE_ABOVE_THRESHOLD"),
    )
    world.lot_b = provision_lot_on_feed(
        world, world.contract_b["id"],
        lot={"scheduled_head_count": 100, "scheduled_delivery_date": "2026-08-10"},
        receive={
            "head_count_received": 100, "gross_weight_lbs": 50000,
            "scale_ticket_ref": "TB-1", "received_at": "2026-08-10T09:00:00Z",
        },
    )
    world.report_b = report_death_loss(
        world.lot_b["id"], world.grazier_id,
        death_date="2026-08-25", head_lost=3, cause="DISEASE", necropsy_performed=True,
    )
    return world


def setup_rest_buffer_world() -> World:
    """North Bench with KA ACTIVE and two candidate follow-on windows submitted.

    KB starts 13 clear days after KA ends; KC starts 14 clear days after it.
    """
    world = setup_north_bench_available()
    terms = dict(SIMPLE_HEAD_DAY_TERMS, head_value_cents=120000)
    world.contract_a = provision_active_contract(
        world, world.pasture_id, signature_ref="SIG-KA", **terms
    )
    world.contract_b = provision_pending_contract(
        world, world.pasture_id,
        **dict(terms, start_date="2026-11-23", end_date="2027-01-23", min_days=30),
    )
    world.contract_c = provision_pending_contract(
        world, world.pasture_id,
        **dict(terms, start_date="2026-11-24", end_date="2027-01-24", min_days=30),
    )
    return world


def setup_capacity_boundary_world() -> World:
    """Rimrock rated at exactly 1000 head-days with two DRAFT contracts.

    K3a books 10 head for 100 days (exactly 1000 head-days); K3b books a single
    extra head-day in a non-conflicting December window.
    """
    world = setup_rated_pasture_world(RIMROCK, DM_1300_AT_20)
    terms = dict(SIMPLE_HEAD_DAY_TERMS, rate_cents=120, head_value_cents=110000)
    world.contract_exact = create_contract(
        world.grazier_id, world.owner_id, world.pasture_id,
        **dict(terms, head_count_committed=10, start_date="2026-08-10",
               end_date="2026-11-18", min_days=60),
    )
    world.contract_over = create_contract(
        world.grazier_id, world.owner_id, world.pasture_id,
        **dict(terms, head_count_committed=1, start_date="2026-12-05",
               end_date="2026-12-06", min_days=1),
    )
    return world


# ===========================================================================
# Tier 5 — the full North Bench settlement, and the negotiation cycle
# ===========================================================================

FULL_TREATMENTS = (
    {"protocol_code": "BRD-A", "classification": "ROUTINE_PROTOCOL",
     "treatment_date": "2026-08-20", "withdrawal_days": 21, "head_treated": 12,
     "drug_cost_cents": 1250, "labor_cost_cents": 375},
    {"protocol_code": "BRD-A", "classification": "ROUTINE_PROTOCOL",
     "treatment_date": "2026-09-02", "withdrawal_days": 21, "head_treated": 9,
     "drug_cost_cents": 900, "labor_cost_cents": 350},
    {"protocol_code": "PINK-EYE", "classification": "THERAPEUTIC",
     "treatment_date": "2026-09-20", "withdrawal_days": 14, "head_treated": 4,
     "drug_cost_cents": 4500, "labor_cost_cents": 1200},
)


def setup_full_north_bench_settlement(head_count_out: int = 146,
                                      gross_weight_out_lbs: float = 74970,
                                      clock: str = "2026-11-12T00:00:00Z",
                                      issue: bool = False,
                                      dispute: bool = False,
                                      claimed_shrunk_gain_lbs: float = 15400) -> World:
    """The complete North Bench season: three approved treatments, two confirmed
    death losses, one repaired water ticket and a weigh-out short of the head
    received. Optionally issued and then disputed by the owner.
    """
    world = setup_north_bench_lot_on_feed(second_consultant=True)

    world.treatments = []
    for terms in FULL_TREATMENTS:
        row = record_treatment(world.lot_id, world.grazier_id, **terms)
        world.treatments.append(review_treatment_as_owner(row["id"], world.owner_id, "APPROVE"))

    world.death_reports = []
    for death_date in ("2026-08-20", "2026-09-05"):
        report = report_death_loss(
            world.lot_id, world.grazier_id,
            death_date=death_date, head_lost=2, cause="DISEASE",
        )
        world.death_reports.append(
            review_death_loss_as_consultant(report["id"], world.consultant_id, "CONFIRM")
        )

    world.ticket = open_infrastructure_ticket(
        world.pasture_id, world.contract_id, make_grazier_headers(world.grazier_id),
        asset_type="WATER", severity="MAJOR",
        description="Well pump seal leaking at the stock tank",
        reported_at="2026-09-10T08:00:00Z",
    )
    assign_infrastructure_ticket(world.ticket["id"], world.grazier_id, "GRAZIER")
    world.ticket = complete_infrastructure_ticket(
        world.ticket["id"], make_grazier_headers(world.grazier_id),
        180000, "WEAR", "2026-09-14T17:00:00Z",
    )

    weigh_out_lot(
        world.lot_id, world.grazier_id,
        gross_weight_lbs=gross_weight_out_lbs, head_count=head_count_out,
        scale_ticket_ref="T-2001", weighed_at="2026-11-10T09:00:00Z",
    )
    world.lot = read_lot(world.lot_id, world.grazier_id)

    set_logical_clock(clock)
    world.settlement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)
    world.settlement_id = world.settlement["id"]

    if issue or dispute:
        world.settlement = issue_settlement(world.settlement_id, world.grazier_id)
    if dispute:
        world.settlement = dispute_settlement(
            world.settlement_id, world.owner_id,
            claimed_shrunk_gain_lbs=claimed_shrunk_gain_lbs,
            note="Dead head were deducted at the in-weight average",
        )
    return world


SAGE_FLAT_GAIN_TERMS = {
    "billing_mode": "PER_POUND_OF_GAIN", "rate_cents": 90, "shrink_pct": 0,
    "out_shrink_pct": 0, "head_count_committed": 100, "head_value_cents": 120000,
    "start_date": "2026-08-10", "end_date": "2026-11-18", "min_days": 60,
    "treatment_cost_split_pct": 0, "water_responsibility": "GRAZIER",
    "fence_responsibility": "GRAZIER", "infrastructure_owner_cap_cents": 100000,
    "death_loss_terms": "OWNER_BEARS_ALL", "death_loss_threshold_pct": 2.0,
}

BIG_COULEE_HEAD_DAY_TERMS = {
    "billing_mode": "PER_HEAD_PER_DAY", "rate_cents": 82, "shrink_pct": 4.0,
    "out_shrink_pct": 0, "head_count_committed": 200, "head_value_cents": 150000,
    "start_date": "2026-08-10", "end_date": "2026-11-10", "min_days": 60,
    "treatment_cost_split_pct": 0, "water_responsibility": "OWNER",
    "fence_responsibility": "OWNER", "infrastructure_owner_cap_cents": 100000,
    "death_loss_terms": "OWNER_BEARS_ALL", "death_loss_threshold_pct": 2.0,
}

RIMROCK_GAIN_TERMS = {
    "billing_mode": "PER_POUND_OF_GAIN", "rate_cents": 90, "shrink_pct": 0,
    "out_shrink_pct": 0, "head_count_committed": 10, "head_value_cents": 110000,
    "start_date": "2026-08-10", "end_date": "2026-11-10", "min_days": 60,
    "treatment_cost_split_pct": 0, "water_responsibility": "GRAZIER",
    "fence_responsibility": "GRAZIER", "infrastructure_owner_cap_cents": 100000,
    "death_loss_terms": "OWNER_BEARS_ALL", "death_loss_threshold_pct": 2.0,
}
