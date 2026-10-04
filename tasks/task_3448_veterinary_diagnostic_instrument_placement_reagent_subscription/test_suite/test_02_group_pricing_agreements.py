"""Group pricing agreement windows, sweeps, and pricing fall-through (PRD §2.4, §2.7, §3.2, §3.4)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_2026_10_01,
    CLOCK_2026_10_02,
    CLOCK_START_ISO,
    TEST_USERS,
    advance_clock,
    api_client,
    create_group_pricing_agreement,
    create_group_pricing_agreement_payload,
    extract_pricing_lines,
    list_group_pricing_agreements,
    place_reagent_order,
    reagent_line,
    setup_clinic_with_active_reagent_commitment,
    sku_override,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


def test_gpa_invalid_window_rejected(api):
    """PRD §3.2: "The window must be sane at birth: `effective_to` strictly
    after `effective_from`, and strictly after the logical clock at creation,
    or the request is rejected with `ERR_WINDOW_INVALID`."

    Design: Corner/validations/gpa_invalid_window_rejected
    """
    zero_length = api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(
            group_code="CORP-W",
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
        ),
        _ADMIN,
    )
    validate_error(zero_length, ApiErrorId.ERR_WINDOW_INVALID)

    already_past = api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(
            group_code="CORP-W",
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        ),
        _ADMIN,
    )
    validate_error(already_past, ApiErrorId.ERR_WINDOW_INVALID)

    data, _meta = validate_paginated(
        api_client.list_group_pricing_agreements(_ADMIN, params={"group_code": "CORP-W"})
    )
    assert data == []


def test_gpa_window_one_second_intrusion_rejected(api):
    """PRD §2.7: "A new agreement for the same `group_type` and `group_code`
    conflicts with an existing one whose `status` is not `EXPIRED` when the
    new window begins strictly before the existing window ends and the
    existing window begins strictly before the new window ends".

    Design: Difficulty/boundary_precision_check/gpa_window_adjacency_half_open
    """
    create_group_pricing_agreement(
        group_code="CORP-B", effective_to="2027-03-01T00:00:00Z",
    )
    intrusion = api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(
            group_code="CORP-B",
            effective_from="2027-02-28T23:59:59Z",
            effective_to="2027-06-01T00:00:00Z",
            discount_pct=0.15,
        ),
        _ADMIN,
    )
    validate_error(intrusion, ApiErrorId.ERR_PRICING_AGREEMENT_WINDOW_OVERLAP)
    rows = list_group_pricing_agreements(group_code="CORP-B")
    assert len(rows) == 1


def test_gpa_window_exact_adjacency_accepted(api):
    """PRD §2.7: "back-to-back adjacency, where the new `effective_from`
    equals the existing `effective_to`, is allowed." PRD §3.2: "otherwise it
    starts `DRAFT` and waits for the clock sweep to promote it once the clock
    reaches `effective_from`."

    Design: Difficulty/boundary_precision_check/gpa_window_adjacency_half_open
    """
    create_group_pricing_agreement(
        group_code="CORP-B", effective_to="2027-03-01T00:00:00Z",
    )
    resp = api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(
            group_code="CORP-B",
            effective_from="2027-03-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z",
            discount_pct=0.15,
        ),
        _ADMIN,
    )
    adjacent = validate_success(resp, 201)
    assert adjacent["status"] == "DRAFT"  # effective_from is after the logical clock
    rows = list_group_pricing_agreements(group_code="CORP-B")
    assert len(rows) == 2


def test_gpa_window_overlap_same_group_key_rejected(api):
    """PRD §2.7: "A new agreement for the same `group_type` and `group_code`
    conflicts with an existing one whose `status` is not `EXPIRED` when the
    new window begins strictly before the existing window ends and the
    existing window begins strictly before the new window ends". PRD §3.2:
    "a new agreement whose half-open window intersects a non-`EXPIRED`
    agreement of the same `group_type` and `group_code` is rejected with
    `ERR_PRICING_AGREEMENT_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/gpa_window_overlap_keyed_on_group_type
    """
    create_group_pricing_agreement(group_type="BUYING", group_code="BUY-Z", discount_pct=0.20)
    overlap = api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(
            group_type="BUYING",
            group_code="BUY-Z",
            effective_from="2027-06-01T00:00:00Z",
            effective_to="2028-01-01T00:00:00Z",
            discount_pct=0.25,
        ),
        _ADMIN,
    )
    validate_error(overlap, ApiErrorId.ERR_PRICING_AGREEMENT_WINDOW_OVERLAP)


def test_gpa_window_overlap_other_group_type_accepted(api):
    """PRD §2.7: the occupation is keyed on the pair — "A new agreement for
    the same `group_type` and `group_code`" — so the identical window under
    the other `group_type` does not intersect the incumbent's resource.

    Design: Difficulty/resource_temporal_overlap/gpa_window_overlap_keyed_on_group_type
    """
    create_group_pricing_agreement(group_type="BUYING", group_code="BUY-Z", discount_pct=0.20)
    resp = api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(
            group_type="CORPORATE",
            group_code="BUY-Z",
            effective_from="2027-06-01T00:00:00Z",
            effective_to="2028-01-01T00:00:00Z",
            discount_pct=0.25,
        ),
        _ADMIN,
    )
    validate_success(resp, 201)
    rows = list_group_pricing_agreements(group_code="BUY-Z")
    assert len(rows) == 2


def test_referential_error_beats_window_overlap_on_create(api):
    """PRD §2.9: "Checks run in a fixed sequence of tiers, and a request that
    fails several checks reports the failure from the earliest tier". PRD
    §2.9 tier 5: "every `sku` in the price table ... reported as
    `ERR_INVALID_REQUEST`, `ERR_INVALID_PROGRAM_TERMS`, or `ERR_UNKNOWN_SKU`"
    precedes tier 8: "group-pricing window overlap
    (`ERR_PRICING_AGREEMENT_WINDOW_OVERLAP`)".

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_gpa_create
    """
    create_group_pricing_agreement(group_code="CORP-X", effective_to="2027-03-01T00:00:00Z")
    resp = api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(
            group_code="CORP-X",
            effective_from="2027-02-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z",
            sku_overrides=[sku_override("NOPE_SKU", 1)],
        ),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_SKU)
    rows = list_group_pricing_agreements(group_code="CORP-X")
    assert len(rows) == 1


def test_window_overlap_fires_when_referential_check_passes(api):
    """PRD §3.2: "Overlap is policed per §2.7 — a new agreement whose
    half-open window intersects a non-`EXPIRED` agreement of the same
    `group_type` and `group_code` is rejected with
    `ERR_PRICING_AGREEMENT_WINDOW_OVERLAP`, while mere adjacency is
    permitted." Control: with a valid override sku the same overlapping
    window fails on the temporal tier.

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_gpa_create
    """
    create_group_pricing_agreement(group_code="CORP-X", effective_to="2027-03-01T00:00:00Z")
    resp = api_client.create_group_pricing_agreement(
        create_group_pricing_agreement_payload(
            group_code="CORP-X",
            effective_from="2027-02-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z",
            sku_overrides=[sku_override("VC300_CHEM_SLIDE", 400)],
        ),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PRICING_AGREEMENT_WINDOW_OVERLAP)
    rows = list_group_pricing_agreements(group_code="CORP-X")
    assert len(rows) == 1


def test_clock_default_fixed_at_startup(api):
    """PRD §2.4: "At server startup the logical clock reads exactly
    2026-09-01T00:00:00Z." PRD §3.2: "An agreement born with `effective_from`
    at or before the logical clock starts `ACTIVE`; otherwise it starts
    `DRAFT`".

    Design: Corner/cross_cutting_layers/clock_default_fixed_at_startup
    """
    born_active = create_group_pricing_agreement(
        group_code="CORP-D",
        effective_from=CLOCK_START_ISO,
        effective_to="2027-01-01T00:00:00Z",
    )
    born_draft = create_group_pricing_agreement(
        group_code="CORP-E",
        effective_from="2026-09-01T00:00:01Z",
        effective_to="2027-01-01T00:00:00Z",
    )
    assert born_active["status"] == "ACTIVE"
    assert born_draft["status"] == "DRAFT"


def test_gpa_deferred_activation_and_expiry_sweep(api):
    """PRD §2.4: "First, group pricing agreements whose window start has been
    reached move `DRAFT` → `ACTIVE`, and those whose window end has been
    reached move `ACTIVE` → `EXPIRED`." PRD §3.2: "When the clock reaches
    `effective_to`, an `ACTIVE` agreement becomes `EXPIRED`, which is
    terminal".

    Design: Corner/cross_cutting_layers/gpa_deferred_activation_and_expiry_sweep
    """
    gpa = create_group_pricing_agreement(
        group_type="BUYING",
        group_code="BUY-Q",
        effective_from="2026-10-01T00:00:00Z",
        effective_to="2026-11-01T00:00:00Z",
        discount_pct=0.15,
    )
    assert gpa["status"] == "DRAFT"  # window opens after the startup clock

    advance_clock(CLOCK_2026_10_01)
    rows = list_group_pricing_agreements(group_code="BUY-Q")
    assert rows[0]["status"] == "ACTIVE"

    advance_clock("2026-11-01T00:00:00Z")
    rows = list_group_pricing_agreements(group_code="BUY-Q")
    assert rows[0]["status"] == "EXPIRED"


def test_gpa_expiry_sweep_terminal_and_repricing(api):
    """PRD §3.2: "When the clock reaches `effective_to`, an `ACTIVE`
    agreement becomes `EXPIRED`, which is terminal — an expired agreement
    never prices another order." PRD §3.4: "when the membership's agreement
    does not cover that timestamp, resolution falls through to list pricing
    and never to the other group type."

    Design: Corner/state_machines/gpa_expiry_sweep_terminal_and_repricing
    """
    create_group_pricing_agreement(
        group_type="BUYING",
        group_code="BUY-9",
        effective_from=CLOCK_START_ISO,
        effective_to="2026-10-01T00:00:00Z",
        discount_pct=0.20,
    )
    scenario = setup_clinic_with_active_reagent_commitment(
        clinic_kwargs={"buying_group_code": "BUY-9"}
    )
    clinic = scenario["clinic"]
    agreement = scenario["agreement"]

    september = place_reagent_order(
        clinic["id"], agreement["id"],
        order_month="2026-09", lines=[reagent_line("VC300_CHEM_SLIDE", 10)],
    )
    # 10 x round_half_up(420 * (1 - 0.20)) = 10 x 336
    assert september["final_total_cents"] == 3360
    assert extract_pricing_lines(september["pricing_detail"])[0]["price_source"] == "BUYING_DISCOUNT"

    advance_clock(CLOCK_2026_10_01)
    rows = list_group_pricing_agreements(group_code="BUY-9")
    assert rows[0]["status"] == "EXPIRED"

    advance_clock(CLOCK_2026_10_02)
    rows = list_group_pricing_agreements(group_code="BUY-9")
    assert rows[0]["status"] == "EXPIRED"  # terminal: no resurrection

    october = place_reagent_order(
        clinic["id"], agreement["id"],
        order_month="2026-10", lines=[reagent_line("VC300_CHEM_SLIDE", 10)],
    )
    assert october["final_total_cents"] == 4200  # 10 x 420 LIST
    assert extract_pricing_lines(october["pricing_detail"])[0]["price_source"] == "LIST"
