"""Composite setup helpers.

Most interesting board claims need the system walked several requests deep
before the behaviour under test is even reachable — an estray distribution needs
a district, an inspector, an order, a field visit, a lot, a finding, a clock
move and an auction before a single number can be asserted. These helpers
encapsulate those preambles so tests carry assertions rather than plumbing.

Setup calls use the lenient validator so a broken preamble reports "Setup step
failed" instead of surfacing as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    EXAMINER_ID,
    FEE_ADMIN_ID,
    INVESTIGATOR_ID,
    RECORDER_ID,
    SECOND_RECORDER_ID,
    TEST_DEFAULTS,
)
from .factories import (
    close_investigation_payload,
    create_bill_of_sale_payload,
    create_brand_application_payload,
    create_conflict_claim_payload,
    create_fee_remittance_payload,
    create_inspection_order_payload,
    create_inspector_payload,
    create_lot_payload,
    create_owner_payload,
    create_renewal_application_payload,
    create_territory_payload,
    decide_claim_payload,
    record_finding_payload,
    schedule_auction_payload,
    schedule_order_payload,
    set_clock_payload,
    set_inspector_status_payload,
    unique_suffix,
)
from .test_users import (
    make_board_admin_headers,
    make_brand_recorder_headers,
    make_fee_administrator_headers,
    make_field_inspector_headers,
    make_livestock_owner_headers,
    make_theft_investigator_headers,
    TEST_USERS,
)

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
FEE_ADMIN = TEST_USERS["fee_administrator_headers"]
INVESTIGATOR = TEST_USERS["theft_investigator_headers"]


# ─── Tier 0: single-call primitives ───────────────────────────────────────────

def set_clock(to_iso8601: str) -> str:
    """Move the board's logical clock and return the resulting instant."""
    data = get_success_data(
        api_client.set_current_utc(set_clock_payload(to_iso8601), BOARD_ADMIN)
    )
    return data["current_utc"]


def run_delinquency_sweep(headers=None) -> dict:
    return get_success_data(api_client.delinquency_sweep(headers or FEE_ADMIN))


def enrol_owner(legal_name: str = "Test Livestock Ranch", **overrides) -> dict:
    payload = create_owner_payload(legal_name=legal_name, **overrides)
    return get_success_data(api_client.create_owner(payload, BOARD_ADMIN))


def open_district(territory_code: str = None, **overrides) -> dict:
    payload = create_territory_payload(**overrides)
    if territory_code is not None:
        payload["territory_code"] = territory_code
    return get_success_data(api_client.create_territory(payload, BOARD_ADMIN))


def commission_inspector(territory_id: str, badge_number: str = None, **overrides) -> dict:
    payload = create_inspector_payload(territory_id, **overrides)
    if badge_number is not None:
        payload["badge_number"] = badge_number
    return get_success_data(api_client.create_inspector(payload, BOARD_ADMIN))


def change_inspector_status(inspector_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_inspector_status(
            inspector_id, set_inspector_status_payload(status), BOARD_ADMIN
        )
    )


def read_inspector(inspector_id: str) -> dict:
    return get_success_data(api_client.get_inspector(inspector_id, BOARD_ADMIN))


def inspector_version(inspector_id: str) -> int:
    return read_inspector(inspector_id)["version"]


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_inspection_order(order_id, BOARD_ADMIN))


def read_owner(owner_id: str) -> dict:
    return get_success_data(api_client.get_owner(owner_id, BOARD_ADMIN))


def read_owner_statement(owner_id: str) -> dict:
    return get_success_data(api_client.get_owner_statement(owner_id, FEE_ADMIN))


def read_territory(territory_id: str) -> dict:
    return get_success_data(api_client.get_territory(territory_id, BOARD_ADMIN))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_animal_lot(lot_id, BOARD_ADMIN))


def read_registration(registration_id: str) -> dict:
    return get_success_data(
        api_client.get_brand_registration(registration_id, BOARD_ADMIN)
    )


def read_application(application_id: str) -> dict:
    return get_success_data(
        api_client.get_brand_application(application_id, BOARD_ADMIN)
    )


def read_estray_case(case_id: str) -> dict:
    return get_success_data(api_client.get_estray_case(case_id, BOARD_ADMIN))


def read_investigation(investigation_id: str) -> dict:
    return get_success_data(
        api_client.get_theft_investigation(investigation_id, INVESTIGATOR)
    )


def read_remittance(remittance_id: str) -> dict:
    return get_success_data(api_client.get_fee_remittance(remittance_id, FEE_ADMIN))


# ─── Tier 1: brand filing lifecycle ───────────────────────────────────────────

def file_brand_application(owner_id: str, **overrides) -> dict:
    payload = create_brand_application_payload(owner_id, **overrides)
    return get_success_data(
        api_client.create_brand_application(
            payload, make_livestock_owner_headers(owner_id)
        )
    )


def begin_examination(application_id: str, operator_id: str = EXAMINER_ID) -> dict:
    return get_success_data(
        api_client.begin_examination(
            application_id, make_brand_recorder_headers(operator_id)
        )
    )


def record_application(application_id: str, operator_id: str = RECORDER_ID) -> dict:
    return get_success_data(
        api_client.record_application(
            application_id, make_brand_recorder_headers(operator_id)
        )
    )


def record_brand(
    owner_id: str,
    brand_symbol: str = "7X",
    position_code: str = "LEFT_RIB",
    species_class: str = "CATTLE",
    state_code: str = None,
    examiner_id: str = EXAMINER_ID,
    recorder_id: str = RECORDER_ID,
    **application_overrides,
):
    """File a NEW application, examine it and record it.

    Returns ``(application, registration)``. Examining and recording use two
    distinct operator identifiers because the board separates the officer who
    examines a filing from the officer who records it.
    """
    application = file_brand_application(
        owner_id,
        brand_symbol=brand_symbol,
        position_code=position_code,
        species_class=species_class,
        state_code=state_code or TEST_DEFAULTS["STATE_CODE"],
        **application_overrides,
    )
    begin_examination(application["id"], examiner_id)
    registration = record_application(application["id"], recorder_id)
    return application, registration


def file_renewal(owner_id: str, registration_id: str, expected_version: int = None, **overrides) -> dict:
    if expected_version is None:
        expected_version = read_registration(registration_id)["version"]
    payload = create_renewal_application_payload(owner_id, expected_version, **overrides)
    return get_success_data(
        api_client.create_renewal_application(
            registration_id, payload, make_livestock_owner_headers(owner_id)
        )
    )


def file_conflict_claim(
    claimant_owner_id: str, respondent_registration_id: str, **overrides
) -> dict:
    payload = create_conflict_claim_payload(
        claimant_owner_id, respondent_registration_id, **overrides
    )
    return get_success_data(
        api_client.create_conflict_claim(
            payload, make_livestock_owner_headers(claimant_owner_id)
        )
    )


def adjudicate_and_decide_claim(
    claim_id: str, decision: str, decision_note: str = "board decision", operator_id: str = SECOND_RECORDER_ID
) -> dict:
    get_success_data(
        api_client.adjudicate_claim(claim_id, make_brand_recorder_headers(operator_id))
    )
    return get_success_data(
        api_client.decide_claim(
            claim_id,
            decide_claim_payload(decision, decision_note=decision_note),
            make_brand_recorder_headers(operator_id),
        )
    )


# ─── Tier 2: inspection order lifecycle ───────────────────────────────────────

def request_inspection(owner_id: str, territory_id: str, **overrides) -> dict:
    payload = create_inspection_order_payload(owner_id, territory_id, **overrides)
    return get_success_data(
        api_client.create_inspection_order(
            payload, make_livestock_owner_headers(owner_id)
        )
    )


def assign_inspector(
    order_id: str,
    inspector_id: str,
    scheduled_start_at: str = "2026-08-10T09:00:00Z",
    scheduled_end_at: str = "2026-08-10T11:00:00Z",
    expected_inspector_version: int = None,
) -> dict:
    if expected_inspector_version is None:
        expected_inspector_version = inspector_version(inspector_id)
    payload = schedule_order_payload(
        inspector_id,
        expected_inspector_version,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    return get_success_data(api_client.schedule_order(order_id, payload, BOARD_ADMIN))


def open_in_field(order_id: str, inspector_id: str) -> dict:
    return get_success_data(
        api_client.begin_order(order_id, make_field_inspector_headers(inspector_id))
    )


def present_lot(order_id: str, inspector_id: str, head_count: int, **overrides) -> dict:
    payload = create_lot_payload(head_count, **overrides)
    return get_success_data(
        api_client.create_lot(
            order_id, payload, make_field_inspector_headers(inspector_id)
        )
    )


def enter_finding(lot_id: str, inspector_id: str, finding: str, **overrides) -> dict:
    payload = record_finding_payload(finding, **overrides)
    return get_success_data(
        api_client.record_finding(
            lot_id, payload, make_field_inspector_headers(inspector_id)
        )
    )


def close_field_work(order_id: str, inspector_id: str) -> dict:
    return get_success_data(
        api_client.complete_order(order_id, make_field_inspector_headers(inspector_id))
    )


def setup_order_in_field(
    territory_code: str = None,
    travel_surcharge_cents: int = TEST_DEFAULTS["TRAVEL_SURCHARGE_CENTS"],
    impound_capacity_head: int = TEST_DEFAULTS["IMPOUND_CAPACITY_HEAD"],
    state_code: str = TEST_DEFAULTS["STATE_CODE"],
    inspection_purpose: str = "SALE",
    requested_window_start_at: str = "2026-08-10T08:00:00Z",
    requested_window_end_at: str = "2026-08-10T17:00:00Z",
    scheduled_start_at: str = "2026-08-10T09:00:00Z",
    scheduled_end_at: str = "2026-08-10T11:00:00Z",
    owner_name: str = "In Field Ranch",
    max_daily_assignments: int = None,
) -> dict:
    """District + inspector + owner + an order walked to `IN_FIELD`.

    Returns a dict with keys ``owner``, ``territory``, ``inspector``, ``order``.
    """
    owner = enrol_owner(owner_name, contact_email=f"infield{unique_suffix()}@example.test")
    territory = open_district(
        territory_code,
        state_code=state_code,
        travel_surcharge_cents=travel_surcharge_cents,
        impound_capacity_head=impound_capacity_head,
    )
    inspector_kwargs = {}
    if max_daily_assignments is not None:
        inspector_kwargs["max_daily_assignments"] = max_daily_assignments
    inspector = commission_inspector(territory["id"], **inspector_kwargs)
    order = request_inspection(
        owner["id"],
        territory["id"],
        inspection_purpose=inspection_purpose,
        requested_window_start_at=requested_window_start_at,
        requested_window_end_at=requested_window_end_at,
    )
    assign_inspector(
        order["id"],
        inspector["id"],
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    order = open_in_field(order["id"], inspector["id"])
    return {
        "owner": owner,
        "territory": territory,
        "inspector": inspector,
        "order": order,
    }


def add_order_in_field(
    scenario: dict,
    inspection_purpose: str = "MOVEMENT",
    requested_window_start_at: str = "2026-08-12T08:00:00Z",
    requested_window_end_at: str = "2026-08-12T17:00:00Z",
    scheduled_start_at: str = "2026-08-12T09:00:00Z",
    scheduled_end_at: str = "2026-08-12T11:00:00Z",
) -> dict:
    """Add a second order for the same owner and district, on a fresh inspector,
    and walk it to `IN_FIELD`. Returns ``(inspector, order)``."""
    inspector = commission_inspector(scenario["territory"]["id"])
    order = request_inspection(
        scenario["owner"]["id"],
        scenario["territory"]["id"],
        inspection_purpose=inspection_purpose,
        requested_window_start_at=requested_window_start_at,
        requested_window_end_at=requested_window_end_at,
    )
    assign_inspector(
        order["id"],
        inspector["id"],
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    order = open_in_field(order["id"], inspector["id"])
    return inspector, order


# ─── Tier 3: completed orders and the fee dimension ───────────────────────────

def setup_completed_order(
    lot_head_counts=(),
    travel_surcharge_cents: int = TEST_DEFAULTS["TRAVEL_SURCHARGE_CENTS"],
    territory_code: str = None,
    brand_symbol: str = "CO",
    position_code: str = "LEFT_RIB",
    species_class: str = "CATTLE",
    requested_window_start_at: str = "2026-08-10T08:00:00Z",
    requested_window_end_at: str = "2026-08-10T17:00:00Z",
    scheduled_start_at: str = "2026-08-10T09:00:00Z",
    scheduled_end_at: str = "2026-08-10T13:00:00Z",
    owner_name: str = "Completed Order Ranch",
) -> dict:
    """An order walked all the way to `COMPLETED`, with the given lots recorded
    in order and each given a `MATCH_CONFIRMED` finding.

    Returns a dict with ``owner``, ``territory``, ``inspector``, ``order``,
    ``registration`` and ``lots``.
    """
    scenario = setup_order_in_field(
        territory_code=territory_code,
        travel_surcharge_cents=travel_surcharge_cents,
        requested_window_start_at=requested_window_start_at,
        requested_window_end_at=requested_window_end_at,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        owner_name=owner_name,
    )
    registration = None
    lots = []
    if lot_head_counts:
        _, registration = record_brand(
            scenario["owner"]["id"],
            brand_symbol=brand_symbol,
            position_code=position_code,
            species_class=species_class,
        )
        for head_count in lot_head_counts:
            lot = present_lot(
                scenario["order"]["id"],
                scenario["inspector"]["id"],
                head_count,
                species_class=species_class,
                brand_registration_id=registration["id"],
            )
            enter_finding(lot["id"], scenario["inspector"]["id"], "MATCH_CONFIRMED")
            lots.append(lot)
    order = close_field_work(scenario["order"]["id"], scenario["inspector"]["id"])
    scenario["order"] = order
    scenario["registration"] = registration
    scenario["lots"] = lots
    return scenario


def setup_owner_with_assessed_fee(
    travel_surcharge_cents: int = TEST_DEFAULTS["TRAVEL_SURCHARGE_CENTS"],
    owner_name: str = "Assessed Fee Ranch",
    territory_code: str = None,
) -> dict:
    """One lot-free completed order, so the assessment is exactly the district's
    travel surcharge. Returns the same shape as ``setup_completed_order``."""
    return setup_completed_order(
        lot_head_counts=(),
        travel_surcharge_cents=travel_surcharge_cents,
        territory_code=territory_code,
        owner_name=owner_name,
    )


def tender_remittance(owner_id: str, amount_cents: int, covered_order_ids: list) -> dict:
    payload = create_fee_remittance_payload(owner_id, amount_cents, covered_order_ids)
    return get_success_data(
        api_client.create_fee_remittance(payload, make_livestock_owner_headers(owner_id))
    )


# ─── Tier 4: estray impound, hold and auction ─────────────────────────────────

def estray_case_for_lot(lot_id: str) -> dict:
    """The estray case the board opened for a given impounded lot."""
    data = get_success_data(
        api_client.list_estray_cases(BOARD_ADMIN, params={"animal_lot_id": lot_id})
    )
    assert data, f"Setup step failed: no estray case exists for lot {lot_id}"
    return data[0]


def investigation_for_lot(lot_id: str) -> dict:
    """The theft investigation the board opened for a given mismatched lot."""
    data = get_success_data(
        api_client.list_theft_investigations(INVESTIGATOR, params={"animal_lot_id": lot_id})
    )
    assert data, f"Setup step failed: no theft investigation exists for lot {lot_id}"
    return data[0]


def setup_impounded_estray(
    head_count: int = 12,
    impounded_at: str = "2026-08-05T00:00:00Z",
    impound_capacity_head: int = TEST_DEFAULTS["IMPOUND_CAPACITY_HEAD"],
    territory_code: str = None,
    owner_name: str = "Estray Ranch",
) -> dict:
    """Clock parked at `impounded_at`, one order in the field, one lot with no
    legible mark of record given a `NO_LEGIBLE_BRAND` finding.

    Returns ``owner``, ``territory``, ``inspector``, ``order``, ``lot``, ``case``.
    """
    set_clock(impounded_at)
    date = impounded_at[:10]
    scenario = setup_order_in_field(
        territory_code=territory_code,
        impound_capacity_head=impound_capacity_head,
        inspection_purpose="MOVEMENT",
        requested_window_start_at=f"{date}T08:00:00Z",
        requested_window_end_at=f"{date}T17:00:00Z",
        scheduled_start_at=f"{date}T09:00:00Z",
        scheduled_end_at=f"{date}T15:00:00Z",
        owner_name=owner_name,
    )
    lot = present_lot(
        scenario["order"]["id"], scenario["inspector"]["id"], head_count
    )
    lot = enter_finding(lot["id"], scenario["inspector"]["id"], "NO_LEGIBLE_BRAND")
    scenario["lot"] = lot
    scenario["case"] = estray_case_for_lot(lot["id"])
    return scenario


def impound_additional_lot(scenario: dict, head_count: int) -> tuple:
    """Record and impound one more lot under the same in-field order.
    Returns ``(lot, case)``."""
    lot = present_lot(
        scenario["order"]["id"], scenario["inspector"]["id"], head_count
    )
    lot = enter_finding(lot["id"], scenario["inspector"]["id"], "NO_LEGIBLE_BRAND")
    return lot, estray_case_for_lot(lot["id"])


def setup_estray_at_auction(
    head_count: int = 12,
    impounded_at: str = "2026-08-05T00:00:00Z",
    auction_at: str = "2026-08-25T00:00:00Z",
    estimated_gross_cents: int = 180000,
    territory_code: str = None,
) -> dict:
    """An impounded case carried through to `AUCTION_SCHEDULED`, so the
    provisional distribution has already been written."""
    scenario = setup_impounded_estray(
        head_count=head_count,
        impounded_at=impounded_at,
        territory_code=territory_code,
        owner_name="Auction Ranch",
    )
    set_clock(auction_at)
    scenario["case"] = get_success_data(
        api_client.schedule_auction(
            scenario["case"]["id"],
            schedule_auction_payload(estimated_gross_cents),
            BOARD_ADMIN,
        )
    )
    return scenario


# ─── Tier 5: the theft cascade ────────────────────────────────────────────────

def setup_theft_cascade(
    head_count: int = 25,
    brand_symbol: str = "K-BAR",
    position_code: str = "RIGHT_RIB",
    with_pending_renewal: bool = False,
    territory_code: str = None,
    owner_name: str = "Theft Cascade Ranch",
) -> dict:
    """A recorded brand read on a lot, given a `BRAND_MISMATCH` finding.

    The finding raises the order's hold flag, opens a theft investigation and
    encumbers the mark; with ``with_pending_renewal`` a renewal filing lodged
    beforehand is frozen by that encumbrance.

    Returns ``owner``, ``territory``, ``inspector``, ``order``, ``registration``,
    ``lot``, ``investigation`` and (optionally) ``renewal``.
    """
    scenario = setup_order_in_field(
        territory_code=territory_code, owner_name=owner_name
    )
    _, registration = record_brand(
        scenario["owner"]["id"],
        brand_symbol=brand_symbol,
        position_code=position_code,
    )
    renewal = None
    if with_pending_renewal:
        renewal = file_renewal(
            scenario["owner"]["id"], registration["id"], registration["version"]
        )
    lot = present_lot(
        scenario["order"]["id"],
        scenario["inspector"]["id"],
        head_count,
        brand_registration_id=registration["id"],
    )
    lot = enter_finding(lot["id"], scenario["inspector"]["id"], "BRAND_MISMATCH")
    scenario["registration"] = registration
    scenario["renewal"] = renewal
    scenario["lot"] = lot
    scenario["investigation"] = investigation_for_lot(lot["id"])
    return scenario


def close_investigation(
    investigation_id: str, outcome: str, operator_id: str = INVESTIGATOR_ID
) -> dict:
    return get_success_data(
        api_client.close_investigation(
            investigation_id,
            close_investigation_payload(outcome),
            make_theft_investigator_headers(operator_id),
        )
    )


def reopen_investigation(investigation_id: str, operator_id: str = INVESTIGATOR_ID) -> dict:
    return get_success_data(
        api_client.reopen_investigation(
            investigation_id, make_theft_investigator_headers(operator_id)
        )
    )


# ─── Tier 6: arrears, delinquency and suspension ──────────────────────────────

def setup_delinquent_owner(
    travel_surcharge_cents: int = 25000,
    due_date_clock: str = "2026-09-01T00:00:00Z",
    owner_name: str = "Delinquent Ranch",
    territory_code: str = None,
) -> dict:
    """One lot-free order completed on the default clock instant, the clock then
    moved past its due date and a sweep run, so the fee stands at `DELINQUENT`
    and the owner's posted arrears equal ``travel_surcharge_cents``.

    Returns the completed-order scenario plus ``sweep``.
    """
    scenario = setup_completed_order(
        lot_head_counts=(),
        travel_surcharge_cents=travel_surcharge_cents,
        territory_code=territory_code,
        owner_name=owner_name,
    )
    set_clock(due_date_clock)
    scenario["sweep"] = run_delinquency_sweep()
    return scenario


def create_bill_of_sale(seller_owner_id: str, buyer_owner_id: str, **overrides) -> dict:
    payload = create_bill_of_sale_payload(seller_owner_id, buyer_owner_id, **overrides)
    return get_success_data(
        api_client.create_bill_of_sale(
            payload, make_livestock_owner_headers(seller_owner_id)
        )
    )


# ─── Tier 7: scenario builders shared by several depth tests ──────────────────

def setup_two_order_arrears_scenario(sweep_clock: str = "2026-08-31T00:00:00Z") -> dict:
    """One owner, two completed orders on different clock instants.

    Order 1 completes on the default clock instant with a single 40-head lot, so
    its fee falls due 30 days later; order 2 completes a fortnight later with no
    lots at all. The clock is left parked at ``sweep_clock``, where only order 1
    has reached its due date. Returns ``owner``, ``territory``, ``registration``,
    ``order_1`` and ``order_2``.
    """
    owner = enrol_owner("Aspen Draw Ranch", contact_email="aspen@example.test")
    territory = open_district(travel_surcharge_cents=2500)
    first_inspector = commission_inspector(territory["id"])
    second_inspector = commission_inspector(territory["id"])
    _, registration = record_brand(owner["id"], brand_symbol="7X", position_code="LEFT_RIB")

    order_1 = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    assign_inspector(order_1["id"], first_inspector["id"],
                     "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
    open_in_field(order_1["id"], first_inspector["id"])
    lot = present_lot(order_1["id"], first_inspector["id"], 40,
                      brand_registration_id=registration["id"])
    enter_finding(lot["id"], first_inspector["id"], "MATCH_CONFIRMED")
    order_1 = close_field_work(order_1["id"], first_inspector["id"])

    set_clock("2026-08-15T00:00:00Z")
    order_2 = request_inspection(
        owner["id"], territory["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-16T08:00:00Z",
        requested_window_end_at="2026-08-16T17:00:00Z",
    )
    assign_inspector(order_2["id"], second_inspector["id"],
                     "2026-08-16T09:00:00Z", "2026-08-16T11:00:00Z")
    open_in_field(order_2["id"], second_inspector["id"])
    order_2 = close_field_work(order_2["id"], second_inspector["id"])

    set_clock(sweep_clock)
    return {
        "owner": owner,
        "territory": territory,
        "registration": registration,
        "order_1": order_1,
        "order_2": order_2,
    }


def setup_void_assessment_scenario() -> dict:
    """A baseline lot-free assessment of 2500 already on the books, plus a second
    order completed with a single 40-head lot so its assessment is 7450.

    Returns ``owner``, ``territory``, ``baseline_order``, ``order``,
    ``registration`` and ``baseline_projected``.
    """
    owner = enrol_owner("Ledger Bar Ranch", contact_email="ledger@example.test")
    territory = open_district(travel_surcharge_cents=2500)
    first_inspector = commission_inspector(territory["id"])
    second_inspector = commission_inspector(territory["id"])
    _, registration = record_brand(owner["id"], brand_symbol="LB", position_code="LEFT_RIB")

    baseline = request_inspection(
        owner["id"], territory["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-12T08:00:00Z",
        requested_window_end_at="2026-08-12T17:00:00Z",
    )
    assign_inspector(baseline["id"], second_inspector["id"],
                     "2026-08-12T09:00:00Z", "2026-08-12T11:00:00Z")
    open_in_field(baseline["id"], second_inspector["id"])
    baseline = close_field_work(baseline["id"], second_inspector["id"])
    baseline_projected = read_owner_statement(owner["id"])["projected_arrears_cents"]

    order = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    assign_inspector(order["id"], first_inspector["id"],
                     "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
    open_in_field(order["id"], first_inspector["id"])
    lot = present_lot(order["id"], first_inspector["id"], 40,
                      brand_registration_id=registration["id"])
    enter_finding(lot["id"], first_inspector["id"], "MATCH_CONFIRMED")
    order = close_field_work(order["id"], first_inspector["id"])

    return {
        "owner": owner,
        "territory": territory,
        "registration": registration,
        "baseline_order": baseline,
        "baseline_projected": baseline_projected,
        "order": order,
    }


def setup_two_dimension_scenario(clock_after: str = "2026-09-01T00:00:00Z") -> dict:
    """Order 1 completed and assessed on the default clock instant; order 2 walked
    only as far as `IN_FIELD` so its fee dimension has never left `UNASSESSED`.
    The clock is left past order 1's due date. Returns ``owner``, ``territory``,
    ``order_1`` and ``order_2``.
    """
    owner = enrol_owner("Judith Gap Ranch", contact_email="judith@example.test")
    territory = open_district(travel_surcharge_cents=2500)
    first_inspector = commission_inspector(territory["id"])
    second_inspector = commission_inspector(territory["id"])

    order_1 = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    assign_inspector(order_1["id"], first_inspector["id"],
                     "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
    open_in_field(order_1["id"], first_inspector["id"])
    order_1 = close_field_work(order_1["id"], first_inspector["id"])

    order_2 = request_inspection(
        owner["id"], territory["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-12T08:00:00Z",
        requested_window_end_at="2026-08-12T17:00:00Z",
    )
    assign_inspector(order_2["id"], second_inspector["id"],
                     "2026-08-12T09:00:00Z", "2026-08-12T11:00:00Z")
    order_2 = open_in_field(order_2["id"], second_inspector["id"])

    set_clock(clock_after)
    return {
        "owner": owner,
        "territory": territory,
        "order_1": order_1,
        "order_2": order_2,
    }


def setup_arrears_boundary_pair(
    threshold_surcharge_cents: int = 25000,
    under_surcharge_cents: int = 24999,
    sweep_clock: str = "2026-08-31T00:00:00Z",
) -> dict:
    """Two owners in two districts whose travel surcharges straddle the board's
    suspension threshold, each with one lot-free order completed on the default
    clock instant, then swept once the clock reaches their common due date.

    Returns ``owner_at_threshold``, ``owner_under_threshold``, their districts,
    a spare inspector in each district, a fresh `REQUESTED` order for each, and
    the ``sweep`` report.
    """
    owner_at = enrol_owner("Exact Line Ranch", contact_email="exact@example.test")
    owner_under = enrol_owner("Under Line Ranch", contact_email="under@example.test")
    district_at = open_district(travel_surcharge_cents=threshold_surcharge_cents)
    district_under = open_district(travel_surcharge_cents=under_surcharge_cents)

    worker_at = commission_inspector(district_at["id"])
    spare_at = commission_inspector(district_at["id"])
    worker_under = commission_inspector(district_under["id"])
    spare_under = commission_inspector(district_under["id"])

    for owner, district, inspector in (
        (owner_at, district_at, worker_at),
        (owner_under, district_under, worker_under),
    ):
        order = request_inspection(
            owner["id"], district["id"], inspection_purpose="SALE",
            requested_window_start_at="2026-08-10T08:00:00Z",
            requested_window_end_at="2026-08-10T17:00:00Z",
        )
        assign_inspector(order["id"], inspector["id"],
                         "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
        open_in_field(order["id"], inspector["id"])
        close_field_work(order["id"], inspector["id"])

    set_clock(sweep_clock)
    sweep = run_delinquency_sweep()

    next_at = request_inspection(
        owner_at["id"], district_at["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-09-05T08:00:00Z",
        requested_window_end_at="2026-09-05T17:00:00Z",
    )
    next_under = request_inspection(
        owner_under["id"], district_under["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-09-05T08:00:00Z",
        requested_window_end_at="2026-09-05T17:00:00Z",
    )
    return {
        "owner_at_threshold": owner_at,
        "owner_under_threshold": owner_under,
        "district_at_threshold": district_at,
        "district_under_threshold": district_under,
        "spare_inspector_at_threshold": spare_at,
        "spare_inspector_under_threshold": spare_under,
        "next_order_at_threshold": next_at,
        "next_order_under_threshold": next_under,
        "sweep": sweep,
    }


def setup_cancelled_order_for_suspended_owner() -> dict:
    """An owner suspended by a 25000-cent delinquent fee who also holds a
    `CANCELLED` order and a free inspector. Returns ``owner``, ``territory``,
    ``delinquent_order``, ``cancelled_order``, ``spare_inspector`` and ``sweep``.
    """
    scenario = setup_delinquent_owner(
        travel_surcharge_cents=25000,
        owner_name="Powder River Cattle",
    )
    spare = commission_inspector(scenario["territory"]["id"])
    cancelled = request_inspection(
        scenario["owner"]["id"], scenario["territory"]["id"],
        inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-09-05T08:00:00Z",
        requested_window_end_at="2026-09-05T17:00:00Z",
    )
    cancelled = get_success_data(
        api_client.cancel_order(
            cancelled["id"], make_livestock_owner_headers(scenario["owner"]["id"])
        )
    )
    return {
        "owner": scenario["owner"],
        "territory": scenario["territory"],
        "delinquent_order": scenario["order"],
        "cancelled_order": cancelled,
        "spare_inspector": spare,
        "sweep": scenario["sweep"],
    }


def setup_busy_inspector_day(max_daily_assignments: int = 1) -> dict:
    """One inspector holding a `SCHEDULED` 09:00-11:00 window on 2026-08-10 and a
    second order requested for the same day in the same district."""
    owner = enrol_owner("Gallatin Feeders", contact_email="gallatin@example.test")
    territory = open_district()
    inspector = commission_inspector(
        territory["id"], max_daily_assignments=max_daily_assignments
    )
    held = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    assign_inspector(held["id"], inspector["id"],
                     "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
    pending = request_inspection(
        owner["id"], territory["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    return {
        "owner": owner,
        "territory": territory,
        "inspector": inspector,
        "held_order": held,
        "pending_order": pending,
        "inspector_version": inspector_version(inspector["id"]),
    }


def setup_cross_district_inspector() -> dict:
    """Two districts in one state, one inspector homed in the northern district
    already holding a 09:00-11:00 window there, plus a southern order and a
    northern order both still `REQUESTED` for the same day."""
    owner = enrol_owner("Divide Creek Cattle", contact_email="divide@example.test")
    north = open_district()
    south = open_district()
    inspector = commission_inspector(north["id"])
    held = request_inspection(
        owner["id"], north["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    assign_inspector(held["id"], inspector["id"],
                     "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
    southern = request_inspection(
        owner["id"], south["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    northern = request_inspection(
        owner["id"], north["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    return {
        "owner": owner,
        "north": north,
        "south": south,
        "inspector": inspector,
        "held_order": held,
        "southern_order": southern,
        "northern_order": northern,
        "inspector_version": inspector_version(inspector["id"]),
    }


def setup_suspended_commission() -> dict:
    """A commissioned inspector moved to `SUSPENDED`, with one `REQUESTED` order
    in the same district and an owner in good standing."""
    owner = enrol_owner("Big Hole Cattle", contact_email="bighole@example.test")
    territory = open_district()
    inspector = commission_inspector(territory["id"])
    inspector = change_inspector_status(inspector["id"], "SUSPENDED")
    order = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    return {
        "owner": owner,
        "territory": territory,
        "inspector": inspector,
        "order": order,
    }


def setup_two_lot_rounding_order() -> dict:
    """An in-field order carrying a 30-head lot and then a 40-head lot, both on
    the same recorded mark and both already given a `MATCH_CONFIRMED` finding.
    Ready for the completion call that stamps the fee."""
    scenario = setup_order_in_field(
        travel_surcharge_cents=2500,
        scheduled_end_at="2026-08-10T13:00:00Z",
        owner_name="Two Dot Livestock",
    )
    _, registration = record_brand(
        scenario["owner"]["id"], brand_symbol="TD", position_code="LEFT_HIP"
    )
    lots = []
    for head_count in (30, 40):
        lot = present_lot(
            scenario["order"]["id"], scenario["inspector"]["id"], head_count,
            brand_registration_id=registration["id"],
        )
        enter_finding(lot["id"], scenario["inspector"]["id"], "MATCH_CONFIRMED")
        lots.append(lot)
    scenario["registration"] = registration
    scenario["lots"] = lots
    return scenario


def setup_zero_and_single_lot_orders() -> dict:
    """Two in-field orders for one owner in one district: the first carries no
    lots at all, the second exactly one 1-head lot with a `MATCH_CONFIRMED`
    finding. Both windows start at 09:00Z."""
    scenario = setup_order_in_field(
        travel_surcharge_cents=2500,
        inspection_purpose="SLAUGHTER",
        owner_name="Empty Pen Livestock",
    )
    _, registration = record_brand(
        scenario["owner"]["id"], brand_symbol="EP",
        position_code="RIGHT_SHOULDER", species_class="SHEEP",
    )
    second_inspector, second_order = add_order_in_field(
        scenario,
        inspection_purpose="SLAUGHTER",
        requested_window_start_at="2026-08-11T08:00:00Z",
        requested_window_end_at="2026-08-11T17:00:00Z",
        scheduled_start_at="2026-08-11T09:00:00Z",
        scheduled_end_at="2026-08-11T11:00:00Z",
    )
    single_lot = present_lot(
        second_order["id"], second_inspector["id"], 1,
        species_class="SHEEP", brand_registration_id=registration["id"],
    )
    enter_finding(single_lot["id"], second_inspector["id"], "MATCH_CONFIRMED")
    return {
        "owner": scenario["owner"],
        "territory": scenario["territory"],
        "registration": registration,
        "empty_order": scenario["order"],
        "empty_inspector": scenario["inspector"],
        "single_lot_order": second_order,
        "single_lot_inspector": second_inspector,
        "single_lot": single_lot,
    }


def setup_prior_use_priority_contest(
    documented_prior_use_years: int = 12,
    prior_use_affidavit_on_file: bool = True,
    contest_clock: str = "2026-08-02T00:00:00Z",
) -> dict:
    """An incumbent mark recorded on the default clock instant, then a rival
    filing lodged a day later in the same conflict group and taken up for
    examination. Returns ``incumbent_owner``, ``rival_owner``,
    ``incumbent_registration``, ``incumbent_application`` and
    ``rival_application``."""
    incumbent_owner = enrol_owner(
        "Bitterroot Land & Cattle", contact_email="bitterroot@example.test"
    )
    rival_owner = enrol_owner("Absaroka Angus", contact_email="absaroka@example.test")
    incumbent_application, incumbent_registration = record_brand(
        incumbent_owner["id"],
        brand_symbol="W-BAR",
        position_code="RIGHT_HIP",
        documented_prior_use_years=0,
        prior_use_affidavit_on_file=False,
    )
    set_clock(contest_clock)
    rival_application = file_brand_application(
        rival_owner["id"],
        brand_symbol="W-BAR",
        position_code="RIGHT_HIP",
        species_class="CATTLE",
        documented_prior_use_years=documented_prior_use_years,
        prior_use_affidavit_on_file=prior_use_affidavit_on_file,
    )
    begin_examination(rival_application["id"])
    return {
        "incumbent_owner": incumbent_owner,
        "rival_owner": rival_owner,
        "incumbent_application": incumbent_application,
        "incumbent_registration": incumbent_registration,
        "rival_application": rival_application,
    }


def setup_correction_cycle_at_ceiling() -> dict:
    """A filing walked twice around the correction cycle, so `correction_rounds`
    stands at the board's ceiling of two and the filing is `UNDER_EXAMINATION`
    once more. Returns ``owner`` and ``application``."""
    owner = enrol_owner("Sweet Grass Partners", contact_email="sweetgrass@example.test")
    application = file_brand_application(
        owner["id"], brand_symbol="SG",
        position_code="LEFT_SHOULDER", species_class="HORSE",
    )
    owner_headers = make_livestock_owner_headers(owner["id"])
    for _ in range(2):
        begin_examination(application["id"])
        get_success_data(
            api_client.return_application(
                application["id"], make_brand_recorder_headers(EXAMINER_ID)
            )
        )
        get_success_data(
            api_client.resubmit_application(
                application["id"], {"brand_symbol": "SG"}, owner_headers
            )
        )
    application = begin_examination(application["id"])
    return {"owner": owner, "application": application}


def setup_revoked_prior_registration_renewal() -> dict:
    """A renewal filing sitting `UNDER_EXAMINATION` whose prior mark of record
    has been revoked by a sustained contest. Returns ``owner``, ``contestant``,
    ``registration``, ``renewal`` and ``claim``."""
    owner = enrol_owner("Rocker A Cattle", contact_email="rockera@example.test")
    contestant = enrol_owner("Yellowstone Stock", contact_email="yellow@example.test")
    _, registration = record_brand(
        owner["id"], brand_symbol="ROCK-A", position_code="RIGHT_RIB"
    )
    renewal = file_renewal(owner["id"], registration["id"], registration["version"])
    renewal = begin_examination(renewal["id"])
    claim = file_conflict_claim(
        contestant["id"], registration["id"], grounds="RECORDING_ERROR"
    )
    claim = adjudicate_and_decide_claim(
        claim["id"], "SUSTAIN", "recorded in error against the 2019 index"
    )
    return {
        "owner": owner,
        "contestant": contestant,
        "registration": registration,
        "renewal": renewal,
        "claim": claim,
    }


def setup_estray_capacity_scenario(
    capacity_head: int = 30,
    first_head_count: int = 20,
    pending_head_counts=(15, 10),
    impounded_at: str = "2026-08-05T00:00:00Z",
    later_clock: str = "2026-08-06T00:00:00Z",
) -> dict:
    """A district whose facility already holds one live occupancy, plus further
    lots recorded a day later and still `UNCHECKED`, ready for the intake that
    tests the aggregate capacity projection."""
    scenario = setup_impounded_estray(
        head_count=first_head_count,
        impounded_at=impounded_at,
        impound_capacity_head=capacity_head,
        owner_name="Stillwater Feeders",
    )
    scenario["territory_after_first_intake"] = read_territory(scenario["territory"]["id"])
    set_clock(later_clock)
    scenario["pending_lots"] = [
        present_lot(scenario["order"]["id"], scenario["inspector"]["id"], head_count)
        for head_count in pending_head_counts
    ]
    return scenario


def setup_estray_sold_unclaimed(
    first_head_count: int = 12,
    second_head_count: int = 8,
    impounded_at: str = "2026-08-05T00:00:00Z",
    auction_at: str = "2026-08-25T00:00:00Z",
    sale_at: str = "2026-09-04T00:00:00Z",
    estimated_gross_cents: int = 180000,
    gross_proceeds_cents: int = 160000,
) -> dict:
    """Two impounded cases at one district; the first is auctioned and sold with
    nobody ever having claimed it, so it is ready to be closed out."""
    scenario = setup_impounded_estray(
        head_count=first_head_count,
        impounded_at=impounded_at,
        owner_name="Yard Gate Livestock",
    )
    second_lot, second_case = impound_additional_lot(scenario, second_head_count)
    scenario["second_lot"] = second_lot
    scenario["second_case"] = second_case
    scenario["head_after_intake"] = read_territory(
        scenario["territory"]["id"]
    )["impound_current_head"]

    set_clock(auction_at)
    get_success_data(
        api_client.schedule_auction(
            scenario["case"]["id"],
            schedule_auction_payload(estimated_gross_cents),
            BOARD_ADMIN,
        )
    )
    set_clock(sale_at)
    scenario["case"] = get_success_data(
        api_client.record_sale(
            scenario["case"]["id"],
            {"gross_proceeds_cents": gross_proceeds_cents},
            BOARD_ADMIN,
        )
    )
    return scenario


def setup_three_open_fees_for_waterfall() -> dict:
    """One owner with three completed orders in one district, all completed on
    the default clock instant so all share a due date, assessed 7450, 10601 and
    2500 in `created_at` order. Returns the orders and the district."""
    owner = enrol_owner("Waterfall Ranch", contact_email="wf@example.test")
    territory = open_district(travel_surcharge_cents=2500, impound_capacity_head=200)
    _, registration = record_brand(owner["id"], brand_symbol="WF", position_code="LEFT_RIB")

    orders = []
    plans = [
        ("SALE", "2026-08-10", "11:00:00Z", (40,)),
        ("MOVEMENT", "2026-08-11", "13:00:00Z", (30, 40)),
        ("SLAUGHTER", "2026-08-12", "11:00:00Z", ()),
    ]
    for purpose, date, end_hour, head_counts in plans:
        inspector = commission_inspector(territory["id"])
        order = request_inspection(
            owner["id"], territory["id"], inspection_purpose=purpose,
            requested_window_start_at=f"{date}T08:00:00Z",
            requested_window_end_at=f"{date}T17:00:00Z",
        )
        assign_inspector(order["id"], inspector["id"],
                         f"{date}T09:00:00Z", f"{date}T{end_hour}")
        open_in_field(order["id"], inspector["id"])
        for head_count in head_counts:
            lot = present_lot(order["id"], inspector["id"], head_count,
                              brand_registration_id=registration["id"])
            enter_finding(lot["id"], inspector["id"], "MATCH_CONFIRMED")
        orders.append(close_field_work(order["id"], inspector["id"]))

    return {
        "owner": owner,
        "territory": territory,
        "registration": registration,
        "orders": orders,
    }


def setup_contest_under_adjudication(
    grounds: str = "PRIOR_USE",
    head_count: int = 18,
    brand_symbol: str = "BAR-L",
    position_code: str = "LEFT_HIP",
) -> dict:
    """A recorded mark read on a lot of an in-field order, contested by a second
    owner whose claim a recorder has already taken up.

    Returns ``owner``, ``contestant``, ``territory``, ``inspector``, ``order``,
    ``registration``, ``lot`` and ``claim``.
    """
    scenario = setup_order_in_field(owner_name="Beaverhead Livestock")
    contestant = enrol_owner("Ruby Valley Stock", contact_email="ruby@example.test")
    _, registration = record_brand(
        scenario["owner"]["id"], brand_symbol=brand_symbol, position_code=position_code
    )
    lot = present_lot(
        scenario["order"]["id"], scenario["inspector"]["id"], head_count,
        brand_registration_id=registration["id"],
    )
    claim = file_conflict_claim(
        contestant["id"], registration["id"], grounds=grounds
    )
    claim = get_success_data(
        api_client.adjudicate_claim(
            claim["id"], make_brand_recorder_headers(SECOND_RECORDER_ID)
        )
    )
    scenario["contestant"] = contestant
    scenario["registration"] = registration
    scenario["lot"] = lot
    scenario["claim"] = claim
    return scenario
