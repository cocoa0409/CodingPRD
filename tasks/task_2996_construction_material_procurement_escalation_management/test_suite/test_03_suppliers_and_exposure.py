"""Suppliers, country-of-origin derivation, disruption events and disruption exposure.

Covers supplier registration defaults, the `is_domestic` derivation, the two readings of
the exposure formula (snapshot versus forward-looking) with their component caps and band
edges, and the two decisions those readings gate: issuing a purchase commitment (snapshot)
and approving a substitution (forward-looking).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_exposure_band,
    assert_supplier,
    log_disruption_event,
    open_project,
    raise_substitution,
    read_package,
    read_project_version,
    read_substitution,
    read_supplier,
    register_package,
    register_supplier,
    submit_quote,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_purchase_commitment_payload,
    disposition_substitution_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]
DESIGN_ENGINEER = TEST_USERS["design_engineer_headers"]


# ─── setup helpers (not tests) ─────────────────────────────────────────────

def _setup_future_disruption_substitution():
    """Supplier with two OPEN events dated after the clock, plus a SUBMITTED substitution.

    The clock is left at its 2026-08-01T00:00:00Z startup default, so both events sit in
    the future and only the forward-looking reading can see them.
    """
    project = open_project()
    package = register_package(project["id"])
    supplier = register_supplier(
        legal_name="Cascade Rebar Supply",
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )
    tariff_event = log_disruption_event(
        supplier["id"],
        event_type="TARIFF_IMPOSED",
        effective_date="2026-12-01T00:00:00.000Z",
        description="Announced Section 232 action effective 2026-12-01",
        tariff_rate_pct=25.00,
    )
    shutdown_event = log_disruption_event(
        supplier["id"],
        event_type="PLANT_SHUTDOWN",
        effective_date="2026-12-01T00:00:00.000Z",
        description="Mill placed the product on allocation from 2026-12-01",
        tariff_rate_pct=0.00,
    )
    request = raise_substitution(
        package["id"],
        supplier["id"],
        driver="VALUE_ENGINEERING",
        proposed_product="Cascade rebar cage assembly",
        cost_delta=0.00,
        schedule_delta_days=0,
    )
    return {
        "project": project,
        "package": package,
        "supplier": supplier,
        "events": [tariff_event, shutdown_event],
        "request": request,
    }


def _setup_exposure_boundary_suppliers():
    """Two CN suppliers straddling the HIGH band edge, each holding one OPEN quote.

    'Pacific Rim Steel' declares 25.00 pct and scores exactly 60.00; 'Han River Metals'
    declares 24.90 pct and scores 59.84. The project's version is read once and no write
    has advanced it since, so the same token serves both buyout attempts.
    """
    project = open_project()
    package_high = register_package(
        project["id"],
        scope_code="STRUCT-STEEL-01",
        description="Package quoted by the HIGH-exposure supplier",
        estimated_cost=1200000.00,
    )
    package_elevated = register_package(
        project["id"],
        scope_code="STRUCT-STEEL-02",
        description="Package quoted by the ELEVATED-exposure supplier",
        estimated_cost=1200000.00,
    )
    supplier_high = register_supplier(
        legal_name="Pacific Rim Steel",
        country_of_origin="CN",
        declared_tariff_rate_pct=25.00,
    )
    supplier_elevated = register_supplier(
        legal_name="Han River Metals",
        country_of_origin="CN",
        declared_tariff_rate_pct=24.90,
    )
    quote_high = submit_quote(
        package_high["id"],
        supplier_high["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )
    quote_elevated = submit_quote(
        package_elevated["id"],
        supplier_elevated["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )
    return {
        "project": project,
        "package_high": package_high,
        "package_elevated": package_elevated,
        "supplier_high": supplier_high,
        "supplier_elevated": supplier_elevated,
        "quote_high": quote_high,
        "quote_elevated": quote_elevated,
        "project_version": read_project_version(project["id"]),
    }


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / supplier_exposure_snapshot_versus_forward_on_one_supplier
# ---------------------------------------------------------------------------

def test_supplier_snapshot_exposure_ignores_events_dated_after_the_clock():
    """The snapshot reading of a supplier carrying only future OPEN events is 0.00 / LOW.

    The supplier is domestic, declares no tariff, and its two OPEN events are both
    effective 2026-12-01 while the clock sits at its startup default.

    PRD §2.5: "Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`"
    PRD §3.2: "The **snapshot** reading, exposed on the supplier row as
    `exposure_score_snapshot` and `exposure_band_snapshot` and counted in
    `open_disruption_count`, admits only events that are `OPEN` *and* whose
    `effective_date` is at or before the current logical clock."
    PRD §3.2: "A disruption dated next month is invisible to it"
    PRD §3.2: "The **geographic component** is zero for a supplier whose
    `country_of_origin` is `US`"
    PRD §3.2: "The band is then `HIGH` when the score is at least 60, `ELEVATED` when it
    is at least 30 but below 60, and `LOW` below 30"

    Design: Difficulty/dual_variant_calc/supplier_exposure_snapshot_versus_forward_on_one_supplier
    """
    scenario = _setup_future_disruption_substitution()

    response = api_client.get_supplier(scenario["supplier"]["id"], BUYOUT_MANAGER)
    supplier = validate_success(response, 200)
    assert_supplier(supplier)

    assert supplier["is_domestic"] is True
    assert supplier["exposure_score_snapshot"] == pytest.approx(0.00, abs=0.005), (
        "a domestic supplier whose only OPEN events are dated after the clock scores 0.00"
    )
    assert supplier["exposure_band_snapshot"] == "LOW"
    assert_exposure_band(
        supplier["exposure_score_snapshot"], supplier["exposure_band_snapshot"]
    )
    # open_disruption_count is the snapshot in-scope count, so the two 2026-12-01 events
    # are invisible to it at a clock of 2026-08-01.
    assert supplier["open_disruption_count"] == 0, (
        "open_disruption_count counts only OPEN events effective at or before the clock"
    )


def test_supplier_forward_exposure_high_band_blocks_substitution_approval():
    """The same row is refused as a substitute because its forward-looking band is HIGH.

    Forward-looking scope admits both 2026-12-01 events: the greatest tariff rate is
    25.00, so the tariff component is min(40, 25.00 * 1.6) = 40; two OPEN events give
    min(40, 2 * 20) = 40; the domestic origin adds nothing. The score is 80.00 — HIGH.

    PRD §3.2: "The **forward-looking** reading admits every `OPEN` event regardless of
    `effective_date`, so known future tariffs and announced shutdowns count now."
    PRD §3.2: "The **tariff component** starts from an effective tariff rate defined as
    the greatest value among the supplier's `declared_tariff_rate_pct` and the
    `tariff_rate_pct` of every in-scope `OPEN` event whose `event_type` is
    `TARIFF_IMPOSED`, with an absent rate treated as zero."
    PRD §3.2: "That effective rate is multiplied by 1.6, and the product is capped at 40
    points."
    PRD §3.2: "The **event component** is the count of in-scope `OPEN` events of any type,
    whatever their kind, multiplied by 20 points, also capped at 40 — so two open events
    already max this component out."
    PRD §3.2: "Approving a substitution — with or without conditions — consults the
    **forward-looking** band of the proposed supplier and is refused with
    `ERR_SUBSTITUTE_SUPPLIER_EXPOSED` when that reads `HIGH`, even if the same supplier's
    snapshot band is `LOW`."
    PRD §3.8: "An **`APPROVED`** disposition requires the scope package not to be `CLOSED`
    and requires the proposed supplier's forward-looking exposure band ... not to be
    `HIGH`"

    Design: Difficulty/dual_variant_calc/supplier_exposure_snapshot_versus_forward_on_one_supplier
    """
    scenario = _setup_future_disruption_substitution()

    response = api_client.disposition_substitution_request(
        scenario["request"]["id"],
        disposition_substitution_payload("APPROVED"),
        DESIGN_ENGINEER,
    )
    validate_error(response, ApiErrorId.ERR_SUBSTITUTE_SUPPLIER_EXPOSED.value, 409)

    request = read_substitution(scenario["request"]["id"])
    assert request["status"] == "SUBMITTED", "a refused disposition leaves the request open"
    assert request["applied_cost_delta"] == pytest.approx(0.00, abs=0.005)
    assert request["applied_schedule_delta_days"] == 0

    package = read_package(scenario["package"]["id"])
    assert package["fabrication_duration_days"] == 70, (
        "no delta is applied when the approval is refused"
    )
    assert package["estimated_cost"] == pytest.approx(1200000.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check /
#          supplier_exposure_high_band_at_exactly_sixty_blocks_commitment
# ---------------------------------------------------------------------------

def test_supplier_exposure_exactly_sixty_is_high_and_blocks_the_buyout():
    """A CN supplier declaring 25.00 pct scores exactly 60.00 and cannot be bought out.

    The tariff component is min(40, 25.00 * 1.6) = 40, there are no disruption events, and
    the non-domestic origin adds 20, so the score is exactly 60.00 — the inclusive lower
    bound of the HIGH band.

    PRD §3.2: "That effective rate is multiplied by 1.6, and the product is capped at 40
    points."
    PRD §3.2: "The **geographic component** is zero for a supplier whose
    `country_of_origin` is `US` and a flat 20-point penalty for every other origin."
    PRD §3.2: "The band is then `HIGH` when the score is at least 60, `ELEVATED` when it
    is at least 30 but below 60, and `LOW` below 30; each threshold is an inclusive lower
    bound."
    PRD §3.2: "Issuing a purchase commitment consults the **snapshot** band and is refused
    with `ERR_SUPPLIER_EXPOSURE_TOO_HIGH` when the quote's supplier reads `HIGH`."
    PRD §3.1: "The first quote landing on it moves it to `SOURCING`"

    Design: Difficulty/boundary_precision_check/supplier_exposure_high_band_at_exactly_sixty_blocks_commitment
    """
    scenario = _setup_exposure_boundary_suppliers()

    supplier = read_supplier(scenario["supplier_high"]["id"])
    assert supplier["is_domestic"] is False
    assert supplier["exposure_score_snapshot"] == pytest.approx(60.00, abs=0.005), (
        "25.00 pct weighted by 1.6 caps at 40 and the 20-point origin penalty makes 60.00"
    )
    assert supplier["exposure_band_snapshot"] == "HIGH"
    assert_exposure_band(
        supplier["exposure_score_snapshot"], supplier["exposure_band_snapshot"]
    )

    response = api_client.create_purchase_commitment(
        create_purchase_commitment_payload(
            quote_id=scenario["quote_high"]["id"],
            expected_project_version=scenario["project_version"],
            po_number="PO-2996-0031",
            is_early_buyout=False,
        ),
        BUYOUT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_SUPPLIER_EXPOSURE_TOO_HIGH.value, 409)

    package = read_package(scenario["package_high"]["id"])
    assert package["status"] == "SOURCING", "a refused buyout never moves the package"
    assert package["open_quote_count"] == 1


def test_supplier_exposure_just_below_sixty_is_elevated_and_permits_the_buyout():
    """A CN supplier declaring 24.90 pct scores 59.84 / ELEVATED and its quote buys out.

    24.90 * 1.6 = 39.84, which is below the 40-point cap, plus the 20-point origin penalty
    gives 59.84 — one hundredth short of the HIGH band, so only the exposure gate differs
    between this arm and its HIGH twin. The refused HIGH request is issued first with the
    same `expected_project_version`, which the accepted request then reuses, so the refusal
    demonstrably left the project's `version` alone.

    PRD §3.2: "The band is then `HIGH` when the score is at least 60, `ELEVATED` when it
    is at least 30 but below 60, and `LOW` below 30; each threshold is an inclusive lower
    bound."
    PRD §2.7: "If that value does not equal the project's current `version`, the request is
    rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) and nothing is created."
    PRD §3.5: "The new row starts with `commitment_status` `PENDING` and
    `delivery_posture` `SCHEDULED`"
    PRD §3.5: "The addressed package leaves `SOURCING` ... and becomes `BOUGHT_OUT`."

    Design: Difficulty/boundary_precision_check/supplier_exposure_high_band_at_exactly_sixty_blocks_commitment
    """
    scenario = _setup_exposure_boundary_suppliers()

    supplier = read_supplier(scenario["supplier_elevated"]["id"])
    assert supplier["exposure_score_snapshot"] == pytest.approx(59.84, abs=0.005), (
        "24.90 pct weighted by 1.6 is 39.84, under the 40 cap, plus the 20-point penalty"
    )
    assert supplier["exposure_band_snapshot"] == "ELEVATED"
    assert_exposure_band(
        supplier["exposure_score_snapshot"], supplier["exposure_band_snapshot"]
    )

    refused = api_client.create_purchase_commitment(
        create_purchase_commitment_payload(
            quote_id=scenario["quote_high"]["id"],
            expected_project_version=scenario["project_version"],
            po_number="PO-2996-0031",
            is_early_buyout=False,
        ),
        BUYOUT_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_SUPPLIER_EXPOSURE_TOO_HIGH.value, 409)

    accepted = api_client.create_purchase_commitment(
        create_purchase_commitment_payload(
            quote_id=scenario["quote_elevated"]["id"],
            expected_project_version=scenario["project_version"],
            po_number="PO-2996-0032",
            is_early_buyout=False,
        ),
        BUYOUT_MANAGER,
    )
    commitment = validate_success(accepted, 201)
    assert commitment["commitment_status"] == "PENDING"
    assert commitment["delivery_posture"] == "SCHEDULED"

    package = read_package(scenario["package_elevated"]["id"])
    assert package["status"] == "BOUGHT_OUT"


# ---------------------------------------------------------------------------
# Queue B: entities / defaults_supplier_declared_tariff_rate_defaults_to_zero
# ---------------------------------------------------------------------------

def test_supplier_declared_tariff_rate_defaults_to_zero():
    """Omitting declared_tariff_rate_pct applies the default 0 and the supplier reads LOW.

    With a US origin, no declared tariff and no disruption events, every one of the three
    exposure components is zero, so the score is 0.00 and the band is LOW.

    PRD §3.2: "A supplier may also declare a `declared_tariff_rate_pct` — the tariff rate
    it says applies to its imported content — as a percentage between 0 and 100 inclusive,
    defaulting to 0 when omitted."
    PRD §3.2: "Suppliers start with `status` `ACTIVE` and a null `suspension_reason`."
    PRD §3.2: "From that code the server derives `is_domestic`, which is true exactly when
    the country is `US`."
    PRD §3.2: "with an absent rate treated as zero"
    PRD §3.2: "The band is then `HIGH` when the score is at least 60, `ELEVATED` when it is
    at least 30 but below 60, and `LOW` below 30"
    PRD §4: "Operations that mint a new resource ... return `201 Created` with the new
    resource in the envelope's `data` field."

    Design: Corner/entities/defaults_supplier_declared_tariff_rate_defaults_to_zero
    """
    response = api_client.create_supplier(
        {"legal_name": "Ironworks Fabricators LLC", "country_of_origin": "US"},
        BUYOUT_MANAGER,
    )
    supplier = validate_success(response, 201)
    assert_supplier(supplier)

    assert supplier["declared_tariff_rate_pct"] == pytest.approx(0, abs=0.005), (
        "declared_tariff_rate_pct defaults to 0 when omitted"
    )
    assert supplier["status"] == "ACTIVE"
    assert supplier["suspension_reason"] is None
    assert supplier["is_domestic"] is True
    assert supplier["open_disruption_count"] == 0
    assert supplier["exposure_score_snapshot"] == pytest.approx(0.00, abs=0.005)
    assert supplier["exposure_band_snapshot"] == "LOW"


# ---------------------------------------------------------------------------
# Queue B: entities / computed_fields_is_domestic_derived_from_country_of_origin
# ---------------------------------------------------------------------------

def test_supplier_is_domestic_derived_from_country_of_origin():
    """A CN supplier reads is_domestic false and carries only the 20-point origin penalty.

    Nothing but `country_of_origin` decides `is_domestic`; with a declared tariff of 0.00
    and no events, the geographic component alone gives a score of exactly 20.00, which is
    still below the ELEVATED cut-point of 30.

    PRD §3.2: "From that code the server derives `is_domestic`, which is true exactly when
    the country is `US`."
    PRD §3.2: "The **geographic component** is zero for a supplier whose
    `country_of_origin` is `US` and a flat 20-point penalty for every other origin."
    PRD §3.2: "The three components are added and the total is rounded half up to 2 decimal
    places to yield the exposure score."
    PRD §3.2: "The band is then `HIGH` when the score is at least 60, `ELEVATED` when it is
    at least 30 but below 60, and `LOW` below 30"

    Design: Corner/entities/computed_fields_is_domestic_derived_from_country_of_origin
    """
    response = api_client.create_supplier(
        {
            "legal_name": "Pacific Rim Steel Works",
            "country_of_origin": "CN",
            "declared_tariff_rate_pct": 0.00,
        },
        BUYOUT_MANAGER,
    )
    supplier = validate_success(response, 201)
    assert_supplier(supplier)

    assert supplier["is_domestic"] is False
    assert supplier["exposure_score_snapshot"] == pytest.approx(20.00, abs=0.005), (
        "the non-domestic penalty is the only non-zero component"
    )
    assert supplier["exposure_band_snapshot"] == "LOW"
    assert supplier["open_disruption_count"] == 0


# ---------------------------------------------------------------------------
# Queue B: calculations /
#          constants_applied_exposure_component_caps_and_the_greatest_tariff_wins
# ---------------------------------------------------------------------------

def test_supplier_exposure_component_caps_bind_and_the_greatest_tariff_wins():
    """Both component caps bind, and the event rate beats a lower declared rate.

    The CN mill declares 10.00 pct but carries an OPEN TARIFF_IMPOSED event at 30.00 pct,
    so the effective rate is 30.00: 30.00 * 1.6 = 48 clamps to 40, one event adds 20, and
    the foreign origin adds 20 — exactly 80.00 / HIGH, with the declared field itself left
    at 10.00. The US mill's three OPEN events give 3 * 20 = 60, which clamps to 40, and
    with no tariff and no origin penalty it reads exactly 40.00 / ELEVATED.

    PRD §3.2: "The **tariff component** starts from an effective tariff rate defined as the
    greatest value among the supplier's `declared_tariff_rate_pct` and the
    `tariff_rate_pct` of every in-scope `OPEN` event whose `event_type` is
    `TARIFF_IMPOSED`, with an absent rate treated as zero."
    PRD §3.2: "That effective rate is multiplied by 1.6, and the product is capped at 40
    points."
    PRD §3.2: "The **event component** is the count of in-scope `OPEN` events of any type,
    whatever their kind, multiplied by 20 points, also capped at 40"
    PRD §3.2: "The **geographic component** is zero for a supplier whose
    `country_of_origin` is `US` and a flat 20-point penalty for every other origin."
    PRD §3.2: "A `tariff_rate_pct` between 0 and 100 may accompany the event, defaulting to
    0, and it is read only when the event type is `TARIFF_IMPOSED`"
    PRD §3.2: "The band is then `HIGH` when the score is at least 60, `ELEVATED` when it is
    at least 30 but below 60, and `LOW` below 30"

    Design: Corner/calculations/constants_applied_exposure_component_caps_and_the_greatest_tariff_wins
    """
    supplier_cn = register_supplier(
        legal_name="Pacific Rim Steel Works",
        country_of_origin="CN",
        declared_tariff_rate_pct=10.00,
    )
    log_disruption_event(
        supplier_cn["id"],
        event_type="TARIFF_IMPOSED",
        effective_date="2026-07-01T00:00:00.000Z",
        description="Section 232 action on imported mill product",
        tariff_rate_pct=30.00,
    )
    supplier_us = register_supplier(
        legal_name="Northline Steel Mills",
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )
    for event_type, description in (
        ("PLANT_SHUTDOWN", "Rolling mill down for unplanned reline"),
        ("PORT_CONGESTION", "Inbound plate stuck at the terminal"),
        ("FORCE_MAJEURE", "Regional flooding at the service center"),
    ):
        log_disruption_event(
            supplier_us["id"],
            event_type=event_type,
            effective_date="2026-07-01T00:00:00.000Z",
            description=description,
            tariff_rate_pct=0.00,
        )

    cn_response = api_client.get_supplier(supplier_cn["id"], BUYOUT_MANAGER)
    cn_read = validate_success(cn_response, 200)
    assert_supplier(cn_read)
    assert cn_read["declared_tariff_rate_pct"] == pytest.approx(10.00, abs=0.005), (
        "the declared field is never overwritten by the greater event rate"
    )
    assert cn_read["exposure_score_snapshot"] == pytest.approx(80.00, abs=0.005), (
        "min(40, 30.00 * 1.6) + min(40, 1 * 20) + 20 = 80.00"
    )
    assert cn_read["exposure_band_snapshot"] == "HIGH"
    assert cn_read["open_disruption_count"] == 1
    assert cn_read["is_domestic"] is False

    us_response = api_client.get_supplier(supplier_us["id"], BUYOUT_MANAGER)
    us_read = validate_success(us_response, 200)
    assert_supplier(us_read)
    assert us_read["declared_tariff_rate_pct"] == pytest.approx(0.00, abs=0.005)
    assert us_read["is_domestic"] is True
    assert us_read["exposure_score_snapshot"] == pytest.approx(40.00, abs=0.005), (
        "min(40, 3 * 20) is the only non-zero component"
    )
    assert us_read["exposure_band_snapshot"] == "ELEVATED"
    assert us_read["open_disruption_count"] == 3
    assert us_read["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Queue B: calculations /
#          weighted_scoring_elevated_band_lands_exactly_on_thirty_from_the_tariff_weight
# ---------------------------------------------------------------------------

def test_supplier_exposure_elevated_band_lands_exactly_on_thirty_from_the_tariff_weight():
    """A declared rate of 18.75 pct alone puts a domestic supplier exactly on the ELEVATED edge.

    18.75 * 1.6 = 30.00, which is under the 40-point cap, and a US supplier with no OPEN
    events contributes nothing from the other two components — so the score is exactly 30.00
    and the band is ELEVATED because the cut-point is inclusive. Shaving the declared rate
    to 18.70 gives 29.92, one hundredth of a point short of two, and the band falls to LOW.

    PRD §3.2: "The **tariff component** starts from an effective tariff rate defined as the
    greatest value among the supplier's `declared_tariff_rate_pct` and the
    `tariff_rate_pct` of every in-scope `OPEN` event whose `event_type` is
    `TARIFF_IMPOSED`, with an absent rate treated as zero."
    PRD §3.2: "That effective rate is multiplied by 1.6, and the product is capped at 40
    points."
    PRD §3.2: "The **event component** is the count of in-scope `OPEN` events of any type,
    whatever their kind, multiplied by 20 points, also capped at 40"
    PRD §3.2: "The **geographic component** is zero for a supplier whose
    `country_of_origin` is `US` and a flat 20-point penalty for every other origin."
    PRD §3.2: "The three components are added and the total is rounded half up to 2 decimal
    places to yield the exposure score."
    PRD §3.2: "The band is then `HIGH` when the score is at least 60, `ELEVATED` when it is
    at least 30 but below 60, and `LOW` below 30"

    Design: Corner/calculations/weighted_scoring_elevated_band_lands_exactly_on_thirty_from_the_tariff_weight
    """
    on_the_edge = register_supplier(
        legal_name="Cutpoint Rebar Supply",
        country_of_origin="US",
        declared_tariff_rate_pct=18.75,
    )
    edge_read = validate_success(api_client.get_supplier(on_the_edge["id"], BUYOUT_MANAGER), 200)
    assert_supplier(edge_read)
    assert edge_read["is_domestic"] is True
    assert edge_read["open_disruption_count"] == 0
    assert edge_read["exposure_score_snapshot"] == pytest.approx(30.00, abs=0.005), (
        "18.75 * 1.6 = 30.00 is the whole score for a domestic supplier with no events"
    )
    assert edge_read["exposure_band_snapshot"] == "ELEVATED", (
        "30 is inclusive at the bottom of the ELEVATED band"
    )
    assert_exposure_band(edge_read["exposure_score_snapshot"], "ELEVATED")

    just_below = register_supplier(
        legal_name="Subcut Rebar Supply",
        country_of_origin="US",
        declared_tariff_rate_pct=18.70,
    )
    below_read = validate_success(api_client.get_supplier(just_below["id"], BUYOUT_MANAGER), 200)
    assert_supplier(below_read)
    assert below_read["exposure_score_snapshot"] == pytest.approx(29.92, abs=0.005), (
        "18.70 * 1.6 = 29.92"
    )
    assert below_read["exposure_band_snapshot"] == "LOW", "below 30 is LOW"
    assert_exposure_band(below_read["exposure_score_snapshot"], "LOW")


# ---------------------------------------------------------------------------
# Queue B: endpoints /
#          computed_read_a_supplier_read_restates_its_own_exposure_snapshot
# ---------------------------------------------------------------------------

def test_supplier_read_restates_its_own_exposure_snapshot_without_mutating_the_row():
    """A supplier read recomputes its exposure from the current event rows and never mutates.

    The freshly registered domestic supplier reads 0.00 / LOW with no open events. Two OPEN
    events already effective at the logical clock's startup value raise the event component
    to its 40-point cap, so the very next read of the same row restates 40.00 / ELEVATED —
    and a further read repeats those derived values while leaving `version` and `updated_at`
    exactly where they were, because a derivation is not a mutation.

    PRD §2.10: "A supplier's `open_disruption_count`, `exposure_score_snapshot` and
    `exposure_band_snapshot` are recomputed on every read of that supplier."
    PRD §2.10: "Nothing about a derivation counts as a mutation: it never refreshes
    `updated_at` and never increments `version`."
    PRD §3.2: "The **event component** is the count of in-scope `OPEN` events of any type,
    whatever their kind, multiplied by 20 points, also capped at 40"
    PRD §3.2: "The **geographic component** is zero for a supplier whose
    `country_of_origin` is `US` and a flat 20-point penalty for every other origin."
    PRD §3.2: "The band is then `HIGH` when the score is at least 60, `ELEVATED` when it is
    at least 30 but below 60, and `LOW` below 30"
    PRD §2.5: "Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`;
    this fixed startup default must not be replaced by the host's system time."

    Design: Corner/endpoints/computed_read_a_supplier_read_restates_its_own_exposure_snapshot
    """
    supplier = register_supplier(
        legal_name="Restated Reads Steel Co",
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )

    quiet = validate_success(api_client.get_supplier(supplier["id"], BUYOUT_MANAGER), 200)
    assert_supplier(quiet)
    assert quiet["open_disruption_count"] == 0
    assert quiet["exposure_score_snapshot"] == pytest.approx(0.00, abs=0.005)
    assert quiet["exposure_band_snapshot"] == "LOW"

    for event_type, description in (
        ("PORT_CONGESTION", "Berth queue at the receiving terminal"),
        ("PLANT_SHUTDOWN", "Galvanizing line offline for repairs"),
    ):
        log_disruption_event(
            supplier["id"],
            event_type=event_type,
            effective_date="2026-07-15T00:00:00.000Z",
            description=description,
            tariff_rate_pct=0.00,
        )

    disrupted = validate_success(api_client.get_supplier(supplier["id"], BUYOUT_MANAGER), 200)
    assert_supplier(disrupted)
    assert disrupted["open_disruption_count"] == 2, (
        "both events are OPEN and already effective at the startup clock"
    )
    assert disrupted["exposure_score_snapshot"] == pytest.approx(40.00, abs=0.005), (
        "min(40, 2 * 20) is the only non-zero component for a domestic supplier"
    )
    assert disrupted["exposure_band_snapshot"] == "ELEVATED"
    assert_exposure_band(disrupted["exposure_score_snapshot"], "ELEVATED")

    again = validate_success(api_client.get_supplier(supplier["id"], BUYOUT_MANAGER), 200)
    assert again["open_disruption_count"] == 2
    assert again["exposure_score_snapshot"] == pytest.approx(40.00, abs=0.005)
    assert again["exposure_band_snapshot"] == "ELEVATED"
    assert again["version"] == disrupted["version"], "re-deriving on read never bumps version"
    assert again["updated_at"] == disrupted["updated_at"], (
        "re-deriving on read never refreshes updated_at"
    )
