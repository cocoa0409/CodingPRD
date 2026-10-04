"""Optimistic concurrency: the two guarded writes and the version counter.

Five instances, one test each.  Both guarded writes — contract amendment
drafting via ``expected_lease_version`` and substitution-endorsement creation
via ``expected_production_order_version`` — are exercised in their stale case
(412, nothing applied) and in their correct-version case (accepted, and the
parent's ``version`` advances by exactly one per write).
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_component_payload,
    create_endorsement,
    create_lessee_and_contract,
    create_order,
    complete_order,
    release_order,
    reserve_order,
    set_clock,
    setup_catalogue,
    start_production,
    validate_error,
    validate_success,
)

SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]

CONTRACT_BODY = {
    "lease_type": "FULL_SERVICE",
    "per_diem_rate_cents": 10000,
    "liability_bearer": "LESSOR",
    "term_start_date": "2026-01-01",
    "term_end_date": "2027-12-31",
    "fleet_car_cap": 10,
}


def _active_contract(legal_name: str) -> dict:
    """A lessee account plus an ACTIVE contract written for it."""
    commercial = create_lessee_and_contract(
        legal_name=legal_name,
        credit_tier="A",
        utilization_threshold_pct=50,
        credit_ceiling_cents=5000000,
        **CONTRACT_BODY,
    )
    return commercial


def test_stale_amendment_redraft_is_rejected_and_writes_nothing(api):
    """PRD §2.7: "Both guards use the same rejection: when the supplied expected
    version does not equal the parent's current `version`, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412), and no part of the request is
    applied."
    PRD §2.7: "This matters because a contract that is already in
    `AMENDMENT_DRAFTED` may legitimately be redrafted before ratification — a
    second draft supersedes the first under the product semantics of §3.5 — so
    the two writes are distinguished only by the version the writer observed."
    PRD §3.5: "The expected version must equal the contract's current `version`;
    if the contract has advanced since the client read it, the draft is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
    PRD §2.11: "Seventh, version currency: a supplied expected version must
    equal the parent's current `version`, and a mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412); this check guards amendment drafting and
    substitution-endorsement creation."

    Design: Corner/cross_cutting_complexity_layers/occ_lease_amendment_redraft_stale_version_returns_412
    """
    set_clock("2026-09-01T00:00:00Z")
    contract = _active_contract("LESS-OCC-1")["contract"]
    assert contract["status"] == "ACTIVE"
    observed = contract["version"]

    drafted = validate_success(
        api.draft_lease_amendment(
            contract["id"],
            {
                "per_diem_rate_cents": 12000,
                "liability_bearer": "LESSEE",
                "expected_lease_version": observed,
            },
            LEASE,
        )
    )
    assert drafted["status"] == "AMENDMENT_DRAFTED"
    assert drafted["version"] == observed + 1, "the draft is one contract mutation"
    assert drafted["per_diem_rate_cents"] == 12000

    # The redraft reuses the version observed before the first draft, so it is
    # the write the contract has already moved past.
    stale = api.draft_lease_amendment(
        contract["id"],
        {
            "per_diem_rate_cents": 13000,
            "liability_bearer": "LESSOR",
            "expected_lease_version": observed,
        },
        LEASE,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    final = validate_success(api.get_lease_contract(contract["id"], LEASE))
    assert final["status"] == "AMENDMENT_DRAFTED", "no part of the redraft applied"
    assert final["version"] == drafted["version"], "the stale write did not bump"
    assert final["per_diem_rate_cents"] == 12000, (
        "the first draft's terms survive the refused supersede"
    )


def test_correct_version_redraft_supersedes_and_ratification_counts_once(api):
    """PRD §2.7: "This matters because a contract that is already in
    `AMENDMENT_DRAFTED` may legitimately be redrafted before ratification — a
    second draft supersedes the first under the product semantics of §3.5 — so
    the two writes are distinguished only by the version the writer observed."
    PRD §2.7: "`expected_lease_version` is a required field of that request, and
    the same field is required again when the drafted amendment is ratified, so
    ratification also fails with `ERR_STALE_VERSION` (HTTP 412) if the contract
    moved between drafting and ratification."
    PRD §3.5: "On success the contract returns to `ACTIVE`, its `amendment_seq`
    is incremented by one, and two cascades run."
    PRD §2.4: "`version` starts at 1 for a newly created resource and is
    incremented by exactly 1 on every mutation that the state machines in §3
    prescribe, with `updated_at` refreshed in the same write."

    Design: Corner/cross_cutting_complexity_layers/occ_lease_amendment_correct_version_redraft_and_ratify_succeed
    """
    set_clock("2026-09-01T00:00:00Z")
    contract = _active_contract("LESS-OCC-2")["contract"]
    v1 = contract["version"]
    assert contract["amendment_seq"] == 0

    first = validate_success(
        api.draft_lease_amendment(
            contract["id"],
            {
                "per_diem_rate_cents": 12000,
                "liability_bearer": "LESSEE",
                "expected_lease_version": v1,
            },
            LEASE,
        )
    )
    v2 = first["version"]
    assert v2 == v1 + 1
    assert first["per_diem_rate_cents"] == 12000

    redraft = validate_success(
        api.draft_lease_amendment(
            contract["id"],
            {
                "per_diem_rate_cents": 13000,
                "liability_bearer": "LESSOR",
                "expected_lease_version": v2,
            },
            LEASE,
        )
    )
    v3 = redraft["version"]
    assert redraft["status"] == "AMENDMENT_DRAFTED"
    assert redraft["per_diem_rate_cents"] == 13000, (
        "the second draft supersedes the first draft's terms"
    )
    assert v3 == v2 + 1

    ratified = validate_success(
        api.ratify_lease_amendment(
            contract["id"], {"expected_lease_version": v3}, LEASE
        )
    )
    assert ratified["status"] == "ACTIVE"
    assert ratified["amendment_seq"] == 1, (
        "the superseded draft and its replacement count as one amendment"
    )
    assert ratified["per_diem_rate_cents"] == 13000, (
        "the ratified terms are the redraft's, not the superseded draft's"
    )
    assert ratified["version"] == v3 + 1, (
        f"every amendment write advances the counter by one: "
        f"{v1} -> {v2} -> {v3} -> {ratified['version']}"
    )


def test_stale_endorsement_create_is_rejected_and_leaves_no_row(api):
    """PRD §2.7: "The second guard protects substitution-endorsement creation.
    A `POST /substitution-endorsements` request must carry
    `expected_production_order_version`, holding the client's last observed
    `version` of that order.  If the order's version has advanced since the
    client read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "This is the serialization point for endorsement creation: a newly
    created endorsement for the same original component legitimately supersedes
    the previously `PENDING` endorsement on that order, so the two writes are
    distinguished only by the version the writer observed, and the stale writer
    is prevented from superseding an endorsement it never saw."
    PRD §3.3: "A successful create starts the endorsement in `PENDING`,
    supersedes any earlier `PENDING` endorsement for the same original component
    on that order, and increments the production order's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_endorsement_create_stale_production_order_version_returns_412
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-OCC-3",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-OCC3",
        wheelset_part_number="WS-OCC-3A",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        include_bom=False,
        on_hand_qty=1000,
    )
    substitute = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="WS-OCC-3B",
                component_class="WHEELSET",
                unit_cost_cents=1100,
                lead_time_days=4,
                on_hand_qty=1000,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    observed = order["version"]

    first = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=1,
        decides_material=False,
        expected_production_order_version=observed,
    )
    assert first["status"] == "PENDING"

    after_first = validate_success(api.get_production_order(order["id"], PLANNER))
    assert after_first["version"] == observed + 1, (
        "creating an endorsement is a mutation of its parent order"
    )

    stale = api.create_substitution_endorsement(
        {
            "production_order_id": order["id"],
            "original_component_id": catalogue["wheelset"]["id"],
            "substitute_component_id": substitute["id"],
            "substitute_qty_per_car": 1,
            "decides_material": False,
            "expected_production_order_version": observed,
        },
        PLANNER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    live = validate_success(api.list_substitution_endorsements(PLANNER))
    assert len(live) == 1, "the stale write left no endorsement behind"
    assert live[0]["id"] == first["id"]
    assert live[0]["status"] == "PENDING"


def test_correct_version_endorsement_supersedes_and_advances_the_order(api):
    """PRD §2.7: "This is the serialization point for endorsement creation: a
    newly created endorsement for the same original component legitimately
    supersedes the previously `PENDING` endorsement on that order, so the two
    writes are distinguished only by the version the writer observed, and the
    stale writer is prevented from superseding an endorsement it never saw."
    PRD §3.3: "A successful create starts the endorsement in `PENDING`,
    supersedes any earlier `PENDING` endorsement for the same original component
    on that order, and increments the production order's `version`."
    PRD §2.4: "`version` starts at 1 for a newly created resource and is
    incremented by exactly 1 on every mutation that the state machines in §3
    prescribe, with `updated_at` refreshed in the same write."

    Design: Corner/cross_cutting_complexity_layers/occ_endorsement_create_correct_version_supersedes_and_increments_order_version
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-OCC-4",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-OCC4",
        wheelset_part_number="WS-OCC-4A",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        include_bom=False,
        on_hand_qty=1000,
    )
    substitute = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="WS-OCC-4B",
                component_class="WHEELSET",
                unit_cost_cents=1100,
                lead_time_days=4,
                on_hand_qty=1000,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    v0 = order["version"]

    first = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=1,
        decides_material=False,
        expected_production_order_version=v0,
    )
    assert first["status"] == "PENDING"

    after_first = validate_success(api.get_production_order(order["id"], PLANNER))
    assert after_first["version"] == v0 + 1

    second = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=2,
        decides_material=False,
        expected_production_order_version=after_first["version"],
    )
    assert second["status"] == "PENDING"
    assert second["id"] != first["id"]

    superseded = validate_success(
        api.get_substitution_endorsement(first["id"], PLANNER)
    )
    assert superseded["status"] == "SUPERSEDED", (
        "the earlier pending row is restated rather than deleted"
    )

    final = validate_success(api.get_production_order(order["id"], PLANNER))
    assert final["version"] == v0 + 2, (
        "the order advanced once for each endorsement write, so a writer "
        "holding the create-time version is stale after the first"
    )


def test_order_version_advances_once_per_state_machine_write(api):
    """PRD §3.2: "The order is then re-quoted on the committed basis, its status
    becomes `COMPONENT_RESERVED`, and its `version` and `updated_at` move."
    PRD §3.4: "A successful release moves the order to `RELEASED`, applies every
    `APPROVED` substitution endorsement on it, and re-quotes the order on the
    committed basis."
    PRD §3.4: "On success the order moves to `IN_PRODUCTION`, its
    `planned_shop_days` is set to the width of the changeover window — which
    must still equal the car type's `build_hours` multiplied by the order's
    `quantity` — and its `version` and `updated_at` move."
    PRD §3.4: "The order itself ends as `COMPLETED` with `completed_qty` equal to
    `quantity`, and its `version` and `updated_at` move."
    PRD §2.4: "`version` starts at 1 for a newly created resource and is
    incremented by exactly 1 on every mutation that the state machines in §3
    prescribe, with `updated_at` refreshed in the same write."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_write_across_production_order_lifecycle
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-OCC-5",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-OCC5",
        wheelset_part_number="WS-OCC-5",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-OCC-5",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=10,
    )
    order = create_order(
        catalogue,
        quantity=2,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    v_create = order["version"]
    assert order["status"] == "DRAFT"

    reserved = reserve_order(order["id"])
    assert reserved["status"] == "COMPONENT_RESERVED"
    assert reserved["version"] == v_create + 1

    released = release_order(order["id"])
    assert released["status"] == "RELEASED"
    assert released["version"] == reserved["version"] + 1

    started = start_production(order["id"], "LINE-OCC5", window_start="2026-09-02")
    assert started["status"] == "IN_PRODUCTION"
    assert started["version"] == released["version"] + 1

    completed = complete_order(order["id"], completion_date="2026-09-04")
    assert completed["status"] == "COMPLETED"
    assert completed["version"] == started["version"] + 1

    assert completed["version"] == v_create + 4, (
        "four transitions produced exactly four version increments, so a writer "
        f"holding the create-time version {v_create} is stale after the first"
    )
