"""Quotes, the half-open price hold, revision chains and the quote refusal paths.

Covers quote submission and revision, the derivation of `expires_at`, the half-open
`[received_at, expires_at)` overlap rule scoped to one (material_package_id, supplier_id)
pair, the revision exemption from that rule, the supplier-scope check that outranks it, and
the quote-shaped 404 and 422 refusals.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_quote,
    countersign_commitment,
    issue_commitment,
    make_supplier_rep_headers,
    open_project,
    read_package,
    read_quote,
    register_package,
    register_supplier,
    set_clock,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_escalation_agreement_payload,
    create_quote_payload,
    revise_quote_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]


# ─── setup helpers (not tests) ─────────────────────────────────────────────

def _setup_package_and_supplier(scope_code="STRUCT-STEEL-01", legal_name=None):
    """A project, one steel package at IDENTIFIED, and one US supplier at 0.00 pct."""
    project = open_project()
    package = register_package(
        project["id"],
        scope_code=scope_code,
        description="Structural steel frame package",
        commodity_index_code="PPI_STEEL_MILL",
        estimated_cost=1200000.00,
        required_onsite_date="2027-03-01T00:00:00.000Z",
        fabrication_duration_days=70,
        delivery_transit_days=20,
        submittal_review_days=21,
    )
    supplier = register_supplier(
        legal_name=legal_name or "Ironworks Fabricators LLC",
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )
    return project, package, supplier


def _setup_package_and_two_suppliers():
    """The same package plus a second US supplier, so scope and overlap can be separated."""
    project, package, ironworks = _setup_package_and_supplier()
    northline = register_supplier(
        legal_name="Northline Steel Mills",
        country_of_origin="US",
        declared_tariff_rate_pct=0.00,
    )
    return project, package, ironworks, northline


def _setup_converted_hold_expiring_on_the_eleventh():
    """Buy out and countersign a 10-day hold, then advance the clock to its expiry instant.

    The quote is CONVERTED — still inside the {OPEN, CONVERTED} overlap-eligibility set —
    and its half-open interval is [2026-08-01, 2026-08-11).
    """
    project, package, supplier = _setup_package_and_supplier()
    quote = submit_quote(
        package["id"],
        supplier["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=10,
    )
    commitment = issue_commitment(
        project["id"], quote["id"], po_number="PO-2996-0041", is_early_buyout=False
    )
    countersign_commitment(commitment["id"])
    set_clock("2026-08-11T00:00:00.000Z")
    return project, package, supplier, quote


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap /
#          price_hold_overlap_scoped_to_the_same_package_and_supplier
# ---------------------------------------------------------------------------

def test_price_hold_identical_window_from_a_different_supplier_is_accepted():
    """A second supplier may hold the very same window on the same package.

    The overlap resource is the (material_package_id, supplier_id) pair, so Northline's
    2026-08-01 to 2026-09-15 hold does not collide with Ironworks' identical hold — the
    package simply carries two live prices and `open_quote_count` reads 2.

    PRD §3.3: "The same supplier may not hold two live prices on the same package for
    overlapping periods."
    PRD §3.3: "A new quote's half-open interval, running from `received_at` up to but
    excluding `expires_at`, must not overlap the interval of any existing quote for the same
    package and supplier whose status is `OPEN` or `CONVERTED`; a collision is
    `ERR_PRICE_HOLD_OVERLAP`."
    PRD §3.3: "From those two temporal inputs the server derives `expires_at` as
    `received_at` advanced by `price_hold_days` calendar days, and the price-hold interval
    is **half-open** — the price is holdable while the clock is strictly before `expires_at`,
    and the instant `expires_at` itself is already outside the hold."
    PRD §3.3: "New quotes start `OPEN` with `supersedes_quote_id` null, and their arrival is
    what lifts a package out of `IDENTIFIED` or revives it from `SOURCING_STALLED` into
    `SOURCING`, recomputing that package's `open_quote_count`."

    Design: Difficulty/resource_temporal_overlap/price_hold_overlap_scoped_to_the_same_package_and_supplier
    """
    _project, package, ironworks, northline = _setup_package_and_two_suppliers()
    incumbent = submit_quote(
        package["id"],
        ironworks["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )

    response = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=northline["id"],
            base_price=1190000.00,
            received_at="2026-08-01T00:00:00.000Z",
            price_hold_days=45,
        ),
        make_supplier_rep_headers(northline["id"]),
    )
    rival = validate_success(response, 201)
    assert_quote(rival)
    assert rival["status"] == "OPEN"
    assert rival["supplier_id"] == northline["id"]
    assert rival["supersedes_quote_id"] is None
    assert_instant_equals(rival["expires_at"], "2026-09-15T00:00:00.000Z")

    package_read = read_package(package["id"])
    assert package_read["open_quote_count"] == 2, (
        "both suppliers hold a live price on the same package"
    )
    assert package_read["status"] == "SOURCING"

    incumbent_read = read_quote(incumbent["id"])
    assert incumbent_read["status"] == "OPEN"
    assert incumbent_read["base_price"] == pytest.approx(1150000.00, abs=0.005)


def test_price_hold_shorter_overlapping_window_from_the_same_supplier_is_rejected():
    """The same supplier's shorter hold inside its own live window is refused.

    Ironworks' second quote runs [2026-08-01, 2026-08-31), which sits wholly inside its own
    live [2026-08-01, 2026-09-15) hold, so the interval-conflict rung fires and nothing is
    created: the package still carries only the two pre-existing live prices.

    PRD §3.3: "The same supplier may not hold two live prices on the same package for
    overlapping periods."
    PRD §3.3: "A new quote's half-open interval, running from `received_at` up to but
    excluding `expires_at`, must not overlap the interval of any existing quote for the same
    package and supplier whose status is `OPEN` or `CONVERTED`; a collision is
    `ERR_PRICE_HOLD_OVERLAP`."
    PRD §2.9: "a new quote's price-hold interval may not overlap a live interval for the
    same package and supplier (`ERR_PRICE_HOLD_OVERLAP`, 409)"
    PRD §2.3: "Filters offered on a list endpoint are combined conjunctively: a request that
    supplies both a package identifier and a status returns only the rows matching both."

    Design: Difficulty/resource_temporal_overlap/price_hold_overlap_scoped_to_the_same_package_and_supplier
    """
    _project, package, ironworks, northline = _setup_package_and_two_suppliers()
    incumbent = submit_quote(
        package["id"],
        ironworks["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )
    submit_quote(
        package["id"],
        northline["id"],
        base_price=1190000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )

    response = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=ironworks["id"],
            base_price=1120000.00,
            received_at="2026-08-01T00:00:00.000Z",
            price_hold_days=30,
        ),
        make_supplier_rep_headers(ironworks["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PRICE_HOLD_OVERLAP.value, 409)

    package_read = read_package(package["id"])
    assert package_read["open_quote_count"] == 2, "the refused quote was never created"

    listed, meta = validate_paginated(
        api_client.list_quotes(BUYOUT_MANAGER, params={"material_package_id": package["id"]})
    )
    assert meta["total_count"] == 2
    assert all(row["base_price"] != pytest.approx(1120000.00, abs=0.005) for row in listed), (
        "no quote row exists at the refused price"
    )

    incumbent_read = read_quote(incumbent["id"])
    assert incumbent_read["status"] == "OPEN"
    assert incumbent_read["base_price"] == pytest.approx(1150000.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check /
#          price_hold_adjacent_window_allowed_and_one_day_overlap_rejected
# ---------------------------------------------------------------------------

def test_price_hold_adjacent_window_starting_exactly_at_expiry_is_accepted():
    """A new hold beginning at the previous hold's expires_at merely touches it.

    The bought-out quote holds [2026-08-01, 2026-08-11) and is CONVERTED, which is still
    inside the overlap-eligibility set. A fresh 20-day hold received exactly at
    2026-08-11 runs [2026-08-11, 2026-08-31) and only touches its predecessor, so it is
    accepted. The package remains BOUGHT_OUT, because only IDENTIFIED and SOURCING_STALLED
    are lifted by an arriving quote, and `open_quote_count` reads 1 for the new quote alone.

    PRD §3.3: "Intervals that merely touch — one ending exactly where the next begins — do
    not overlap, precisely because the interval is half-open at its upper end."
    PRD §3.3: "From those two temporal inputs the server derives `expires_at` as
    `received_at` advanced by `price_hold_days` calendar days, and the price-hold interval
    is **half-open** — the price is holdable while the clock is strictly before `expires_at`,
    and the instant `expires_at` itself is already outside the hold."
    PRD §3.3: "A new quote's half-open interval, running from `received_at` up to but
    excluding `expires_at`, must not overlap the interval of any existing quote for the same
    package and supplier whose status is `OPEN` or `CONVERTED`; a collision is
    `ERR_PRICE_HOLD_OVERLAP`."
    PRD §3.3: "becomes `CONVERTED` at the moment a commitment against it is countersigned"
    PRD §3.3: "New quotes start `OPEN` with `supersedes_quote_id` null, and their arrival is
    what lifts a package out of `IDENTIFIED` or revives it from `SOURCING_STALLED` into
    `SOURCING`, recomputing that package's `open_quote_count`."
    PRD §3.5: "The addressed package leaves `SOURCING` — or `SOURCING_STALLED`, since a
    stalled package can still be bought out from a quote created after the stall, provided
    that quote is `OPEN` — and becomes `BOUGHT_OUT`."
    PRD §2.5: "Hop one expires price holds: every quote still `OPEN` whose `expires_at` is
    at or before the supplied instant becomes `EXPIRED`, processed in `created_at` ascending
    order."

    Design: Difficulty/boundary_precision_check/price_hold_adjacent_window_allowed_and_one_day_overlap_rejected
    """
    _project, package, supplier, converted = _setup_converted_hold_expiring_on_the_eleventh()

    response = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=supplier["id"],
            base_price=1160000.00,
            received_at="2026-08-11T00:00:00.000Z",
            price_hold_days=20,
        ),
        make_supplier_rep_headers(supplier["id"]),
    )
    adjacent = validate_success(response, 201)
    assert_quote(adjacent)
    assert adjacent["status"] == "OPEN"
    assert_instant_equals(adjacent["expires_at"], "2026-08-31T00:00:00.000Z")

    converted_read = read_quote(converted["id"])
    assert converted_read["status"] == "CONVERTED", (
        "countersigning converted it, and hop one only expires OPEN quotes"
    )
    assert_instant_equals(converted_read["expires_at"], "2026-08-11T00:00:00.000Z")

    package_read = read_package(package["id"])
    assert package_read["open_quote_count"] == 1, "the adjacent quote only"
    assert package_read["status"] == "BOUGHT_OUT"


def test_price_hold_window_opening_one_day_before_expiry_is_rejected():
    """A hold received one day before the incumbent's expiry overlaps by a day and is refused.

    2026-08-10 with a 5-day hold runs [2026-08-10, 2026-08-15), which shares the single day
    2026-08-10 with the CONVERTED [2026-08-01, 2026-08-11) hold from the same supplier on the
    same package — a genuine overlap rather than a touch — so it is refused. The received_at
    is still at or before the 2026-08-11 clock, so the temporal rung has nothing to say.

    PRD §3.3: "A new quote's half-open interval, running from `received_at` up to but
    excluding `expires_at`, must not overlap the interval of any existing quote for the same
    package and supplier whose status is `OPEN` or `CONVERTED`; a collision is
    `ERR_PRICE_HOLD_OVERLAP`."
    PRD §3.3: "The `received_at` instant may not be later than the current logical clock: a
    quote cannot be received in the future."
    PRD §2.9: "a new quote's price-hold interval may not overlap a live interval for the
    same package and supplier (`ERR_PRICE_HOLD_OVERLAP`, 409)"
    PRD §3.3: "becomes `CONVERTED` at the moment a commitment against it is countersigned"
    PRD §3.5: "The addressed package leaves `SOURCING` — or `SOURCING_STALLED`, since a
    stalled package can still be bought out from a quote created after the stall, provided
    that quote is `OPEN` — and becomes `BOUGHT_OUT`."

    Design: Difficulty/boundary_precision_check/price_hold_adjacent_window_allowed_and_one_day_overlap_rejected
    """
    _project, package, supplier, converted = _setup_converted_hold_expiring_on_the_eleventh()

    response = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=supplier["id"],
            base_price=1170000.00,
            received_at="2026-08-10T00:00:00.000Z",
            price_hold_days=5,
        ),
        make_supplier_rep_headers(supplier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PRICE_HOLD_OVERLAP.value, 409)

    converted_read = read_quote(converted["id"])
    assert converted_read["status"] == "CONVERTED"
    assert_instant_equals(converted_read["expires_at"], "2026-08-11T00:00:00.000Z")

    package_read = read_package(package["id"])
    assert package_read["open_quote_count"] == 0, "the refused quote was never created"
    assert package_read["status"] == "BOUGHT_OUT"


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict /
#          supplier_scope_auth_check_beats_price_hold_overlap_constraint
# ---------------------------------------------------------------------------

def test_quote_supplier_scope_violation_outranks_the_price_hold_overlap():
    """A rep quoting under another supplier's id is a scope violation, never an overlap.

    Northline's rep submits a quote whose body `supplier_id` is Ironworks' — and whose window
    exactly re-covers Ironworks' live [2026-08-01, 2026-08-11) hold, so the request violates
    both the supplier-scope rung and the interval-conflict rung. Supplier scope sits at rung 6
    and the interval conflict at rung 14, so the answer must be the 403 and nothing is created.

    PRD §2.9: "Checks are therefore evaluated in a strict precedence order, and evaluation
    stops at the first failure."
    PRD §2.9: "When the caller is a `SupplierRep`, the supplier it acts for must be its own."
    PRD §2.9: "This rule guards exactly four operations: submitting a quote
    (`POST /procurement/quotes`, where the body's `supplier_id` must equal `X-User-ID`)"
    PRD §2.9: "A violation is `ERR_SUPPLIER_SCOPE_VIOLATION` (403)."
    PRD §2.9: "a new quote's price-hold interval may not overlap a live interval for the
    same package and supplier (`ERR_PRICE_HOLD_OVERLAP`, 409)"
    PRD §3.3: "The submission names the `material_package_id` being quoted and the
    `supplier_id` doing the quoting — which must be the caller's own supplier identity"

    Design: Difficulty/priority_pair_validation_conflict/supplier_scope_auth_check_beats_price_hold_overlap_constraint
    """
    _project, package, ironworks, northline = _setup_package_and_two_suppliers()
    incumbent = submit_quote(
        package["id"],
        ironworks["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=10,
    )

    response = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=ironworks["id"],
            base_price=1100000.00,
            received_at="2026-08-01T00:00:00.000Z",
            price_hold_days=10,
        ),
        make_supplier_rep_headers(northline["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SUPPLIER_SCOPE_VIOLATION.value, 403)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_PRICE_HOLD_OVERLAP.value, (
        "the lower-precedence interval conflict must not be reported"
    )

    package_read = read_package(package["id"])
    assert package_read["open_quote_count"] == 1

    incumbent_read = read_quote(incumbent["id"])
    assert incumbent_read["status"] == "OPEN"
    assert incumbent_read["base_price"] == pytest.approx(1150000.00, abs=0.005)


def test_quote_price_hold_overlap_is_reported_once_the_supplier_scope_check_passes():
    """The very same overlapping window from its own rep reaches the interval-conflict rung.

    This is the compensating arm: nothing changes except the caller's `X-User-ID`, which now
    matches the body's `supplier_id`. Rung 6 is satisfied, evaluation continues down the
    ladder, and the identical window that was masked by the 403 now surfaces as the 409.

    PRD §2.9: "Checks are therefore evaluated in a strict precedence order, and evaluation
    stops at the first failure."
    PRD §2.9: "When the caller is a `SupplierRep`, the supplier it acts for must be its own."
    PRD §2.9: "a new quote's price-hold interval may not overlap a live interval for the
    same package and supplier (`ERR_PRICE_HOLD_OVERLAP`, 409)"
    PRD §3.3: "A new quote's half-open interval, running from `received_at` up to but
    excluding `expires_at`, must not overlap the interval of any existing quote for the same
    package and supplier whose status is `OPEN` or `CONVERTED`; a collision is
    `ERR_PRICE_HOLD_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/supplier_scope_auth_check_beats_price_hold_overlap_constraint
    """
    _project, package, ironworks, _northline = _setup_package_and_two_suppliers()
    incumbent = submit_quote(
        package["id"],
        ironworks["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=10,
    )

    response = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=ironworks["id"],
            base_price=1100000.00,
            received_at="2026-08-01T00:00:00.000Z",
            price_hold_days=10,
        ),
        make_supplier_rep_headers(ironworks["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PRICE_HOLD_OVERLAP.value, 409)

    package_read = read_package(package["id"])
    assert package_read["open_quote_count"] == 1

    incumbent_read = read_quote(incumbent["id"])
    assert incumbent_read["status"] == "OPEN"
    assert incumbent_read["base_price"] == pytest.approx(1150000.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue B: entities /
#          listing_quotes_filtered_by_supersedes_quote_id_returns_only_the_revision
# ---------------------------------------------------------------------------

def test_quote_list_filtered_by_supersedes_quote_id_returns_only_the_revision():
    """Filtering the quote list on supersedes_quote_id walks the revision chain forwards.

    The filter names the original quote, so the only matching row is the revision that points
    back at it — the original itself carries a null `supersedes_quote_id` and is therefore
    never in the result set, even though it is the row the filter names.

    PRD §3.3: "Revision chains are discoverable by filtering the quote list on
    `supersedes_quote_id`, and the list also filters on `material_package_id`, `supplier_id`
    and `status`."
    PRD §3.3: "it moves the addressed quote from `OPEN` to `SUPERSEDED` and creates a
    brand-new quote carrying its own `base_price`, `received_at` and `price_hold_days`, with
    `supersedes_quote_id` set to the superseded quote's identifier"
    PRD §3.3: "New quotes start `OPEN` with `supersedes_quote_id` null"
    PRD §2.3: "where `total_count` counts every row matching the request's filters before
    pagination is applied and `has_more` states whether any matching row remains beyond the
    current page"
    PRD §2.3: "Filters are also the only reverse-navigation channel in this API"

    Design: Corner/entities/listing_quotes_filtered_by_supersedes_quote_id_returns_only_the_revision
    """
    _project, package, supplier = _setup_package_and_supplier()
    original = submit_quote(
        package["id"],
        supplier["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )
    revision = validate_success(
        api_client.revise_quote(
            original["id"],
            revise_quote_payload(
                base_price=1140000.00,
                received_at="2026-08-01T00:00:00.000Z",
                price_hold_days=45,
            ),
            make_supplier_rep_headers(supplier["id"]),
        ),
        201,
    )

    rows, meta = validate_paginated(
        api_client.list_quotes(
            BUYOUT_MANAGER, params={"supersedes_quote_id": original["id"]}
        )
    )
    assert meta["total_count"] == 1, "only the one revision points at the original"
    assert len(rows) == 1
    assert rows[0]["id"] == revision["id"]
    assert rows[0]["base_price"] == pytest.approx(1140000.00, abs=0.005)
    assert rows[0]["status"] == "OPEN"
    assert original["id"] not in [row["id"] for row in rows], (
        "the original carries a null supersedes_quote_id and cannot match the filter"
    )

    original_read = read_quote(original["id"])
    assert original_read["status"] == "SUPERSEDED"
    assert original_read["supersedes_quote_id"] is None
    assert read_package(package["id"])["open_quote_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: entities / type_constraints_unknown_field_in_a_quote_payload_rejected
# ---------------------------------------------------------------------------

def test_quote_payload_carrying_the_derived_expires_at_is_rejected():
    """`expires_at` is derived, so supplying it is an unknown field and a 422.

    The server derives `expires_at` from `received_at` and `price_hold_days`; it is not an
    input to the create, so a client-supplied value is an unknown field rather than a
    silently ignored one. Nothing is created, and the package stays IDENTIFIED with no quotes.

    PRD §2.9: "unknown fields are rejected outright"
    PRD §2.9: "All of these are `ERR_INVALID_REQUEST` (422)."
    PRD §3.3: "From those two temporal inputs the server derives `expires_at` as
    `received_at` advanced by `price_hold_days` calendar days"
    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."
    PRD §2.3: "where `total_count` counts every row matching the request's filters before
    pagination is applied and `has_more` states whether any matching row remains beyond the
    current page"

    Design: Corner/entities/type_constraints_unknown_field_in_a_quote_payload_rejected
    """
    _project, package, supplier = _setup_package_and_supplier()

    response = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=supplier["id"],
            base_price=1150000.00,
            received_at="2026-08-01T00:00:00.000Z",
            price_hold_days=45,
            expires_at="2027-01-01T00:00:00.000Z",
        ),
        make_supplier_rep_headers(supplier["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    _rows, meta = validate_paginated(
        api_client.list_quotes(
            BUYOUT_MANAGER, params={"material_package_id": package["id"]}
        )
    )
    assert meta["total_count"] == 0, "the malformed submission created nothing"

    package_read = read_package(package["id"])
    assert package_read["open_quote_count"] == 0
    assert package_read["status"] == "IDENTIFIED"


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          initial_state_package_moves_identified_to_sourcing_on_its_first_quote
# ---------------------------------------------------------------------------

def test_package_moves_from_identified_to_sourcing_on_its_first_quote():
    """A package is born IDENTIFIED and the first landing quote moves it to SOURCING.

    The transition is a side effect of the quote create, not a package endpoint: before the
    quote the package reads IDENTIFIED with `open_quote_count` 0, and afterwards SOURCING
    with 1. The quote's own `expires_at` is 2026-08-01 advanced by 45 days = 2026-09-15.

    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."
    PRD §3.1: "The first quote landing on it moves it to `SOURCING`, and a quote landing on a
    package already in `SOURCING` leaves the status untouched."
    PRD §3.3: "New quotes start `OPEN` with `supersedes_quote_id` null, and their arrival is
    what lifts a package out of `IDENTIFIED` or revives it from `SOURCING_STALLED` into
    `SOURCING`, recomputing that package's `open_quote_count`."
    PRD §3.3: "From those two temporal inputs the server derives `expires_at` as
    `received_at` advanced by `price_hold_days` calendar days"
    PRD §4: "Operations that mint a new resource — opening a project, registering a package
    or supplier, publishing an index reading, submitting or revising a quote, drafting an
    escalation clause, issuing a purchase commitment, arranging off-site storage, filing a
    storage document, logging a disruption event, raising a substitution request, or
    preparing a change order — return `201 Created` with the new resource in the envelope's
    `data` field."

    Design: Corner/state_machines/initial_state_package_moves_identified_to_sourcing_on_its_first_quote
    """
    _project, package, supplier = _setup_package_and_supplier()
    assert package["status"] == "IDENTIFIED"
    assert package["open_quote_count"] == 0

    response = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=supplier["id"],
            base_price=1150000.00,
            received_at="2026-08-01T00:00:00.000Z",
            price_hold_days=45,
        ),
        make_supplier_rep_headers(supplier["id"]),
    )
    quote = validate_success(response, 201)
    assert_quote(quote)
    assert quote["status"] == "OPEN"
    assert quote["supersedes_quote_id"] is None
    assert_instant_equals(quote["expires_at"], "2026-09-15T00:00:00.000Z")

    package_read = read_package(package["id"])
    assert package_read["status"] == "SOURCING"
    assert package_read["open_quote_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: validations /
#          violation_error_a_quote_received_after_the_clock_or_held_zero_days_is_rejected
# ---------------------------------------------------------------------------

def test_quote_received_after_the_clock_or_held_zero_days_is_rejected():
    """Two quote-shape rules share ERR_INVALID_REQUEST and both fire before any state work.

    A `received_at` of 2026-08-02 is later than the 2026-08-01 startup clock, and a
    `price_hold_days` of 0 is below the declared minimum of 1; each is refused with the same
    422. Because neither quote ever landed, the package is untouched, and the third
    well-formed submission is the one that finally moves it to SOURCING.

    PRD §3.3: "The `received_at` instant may not be later than the current logical clock: a
    quote cannot be received in the future."
    PRD §3.3: "plus a `base_price` greater than zero with at most 2 decimal places, the
    `received_at` instant the quote was received, and a `price_hold_days` firm-price period
    between 1 and 120 calendar days inclusive"
    PRD §2.9: "A quote's `received_at` must be at or before the current logical clock and its
    `price_hold_days` at least 1 (`ERR_INVALID_REQUEST`)."
    PRD §2.5: "Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`;
    this fixed startup default must not be replaced by the host's system time."
    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."
    PRD §3.3: "From those two temporal inputs the server derives `expires_at` as
    `received_at` advanced by `price_hold_days` calendar days"

    Design: Corner/validations/violation_error_a_quote_received_after_the_clock_or_held_zero_days_is_rejected
    """
    _project, package, supplier = _setup_package_and_supplier()
    rep = make_supplier_rep_headers(supplier["id"])

    future = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=supplier["id"],
            base_price=1150000.00,
            received_at="2026-08-02T00:00:00.000Z",
            price_hold_days=45,
        ),
        rep,
    )
    validate_error(future, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    zero_hold = api_client.create_quote(
        create_quote_payload(
            material_package_id=package["id"],
            supplier_id=supplier["id"],
            base_price=1150000.00,
            received_at="2026-08-01T00:00:00.000Z",
            price_hold_days=0,
        ),
        rep,
    )
    validate_error(zero_hold, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    accepted = validate_success(
        api_client.create_quote(
            create_quote_payload(
                material_package_id=package["id"],
                supplier_id=supplier["id"],
                base_price=1150000.00,
                received_at="2026-08-01T00:00:00.000Z",
                price_hold_days=45,
            ),
            rep,
        ),
        201,
    )
    assert_quote(accepted)
    assert_instant_equals(accepted["expires_at"], "2026-09-15T00:00:00.000Z")
    assert_instant_equals(accepted["received_at"], "2026-08-01T00:00:00.000Z")
    assert accepted["price_hold_days"] == 45

    package_read = read_package(package["id"])
    assert package_read["status"] == "SOURCING"
    assert package_read["open_quote_count"] == 1, "only the accepted quote counts"


# ---------------------------------------------------------------------------
# Queue B: endpoints /
#          action_endpoint_revise_supersedes_its_own_quote_and_is_exempt_from_the_overlap_check
# ---------------------------------------------------------------------------

def test_quote_revision_is_exempt_from_the_overlap_check_against_its_own_predecessor():
    """A revision carrying the identical window is let through by the declared exemption.

    The revision repeats `received_at` and `price_hold_days` exactly, so its half-open window
    is a perfect duplicate of the quote it supersedes — a collision under the general overlap
    rule. The exemption for the directly superseded quote is what admits it, and it leaves
    exactly one OPEN quote behind because the predecessor moves to SUPERSEDED in the same act.

    PRD §3.3: "For this create alone, the quote being directly superseded is exempted from the
    price-hold overlap test — otherwise no supplier could ever re-price inside its own live
    hold — but every *other* live quote from the same supplier on that package is still
    tested."
    PRD §3.3: "Revision requires the addressed quote to be `OPEN` and the caller to be that
    quote's supplier; it moves the addressed quote from `OPEN` to `SUPERSEDED` and creates a
    brand-new quote carrying its own `base_price`, `received_at` and `price_hold_days`, with
    `supersedes_quote_id` set to the superseded quote's identifier."
    PRD §3.3: "Both quotes' effect on the package's `open_quote_count` is recomputed."
    PRD §4: "Note that quote revision returns `201 Created`, because it creates a new quote
    rather than editing the one addressed."
    PRD §3.3: "From those two temporal inputs the server derives `expires_at` as
    `received_at` advanced by `price_hold_days` calendar days"

    Design: Corner/endpoints/action_endpoint_revise_supersedes_its_own_quote_and_is_exempt_from_the_overlap_check
    """
    _project, package, supplier = _setup_package_and_supplier()
    original = submit_quote(
        package["id"],
        supplier["id"],
        base_price=1150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )

    response = api_client.revise_quote(
        original["id"],
        revise_quote_payload(
            base_price=1140000.00,
            received_at="2026-08-01T00:00:00.000Z",
            price_hold_days=45,
        ),
        make_supplier_rep_headers(supplier["id"]),
    )
    revision = validate_success(response, 201)
    assert_quote(revision)
    assert revision["status"] == "OPEN"
    assert revision["supersedes_quote_id"] == original["id"]
    assert revision["base_price"] == pytest.approx(1140000.00, abs=0.005)
    assert_instant_equals(revision["expires_at"], "2026-09-15T00:00:00.000Z")

    original_read = validate_success(api_client.get_quote(original["id"], BUYOUT_MANAGER), 200)
    assert original_read["status"] == "SUPERSEDED"

    package_read = validate_success(
        api_client.get_material_package(package["id"], BUYOUT_MANAGER), 200
    )
    assert package_read["open_quote_count"] == 1, "the revision replaces its predecessor"
    assert package_read["status"] == "SOURCING"


# ---------------------------------------------------------------------------
# Queue B: errors /
#          errors_triggerable_an_unknown_quote_id_is_a_404_from_the_path_and_from_the_body
# ---------------------------------------------------------------------------

def test_unknown_quote_id_is_a_404_from_the_path_and_from_the_body():
    """ERR_QUOTE_NOT_FOUND is reachable from a path identifier and from a body foreign key.

    A GET on an unknown quote id fails the path-existence rung. The escalation-agreement
    create carries the same unknown id in its body together with an `index_code` that does not
    match the package's `commodity_index_code` — two violations at once — and because body
    foreign-key existence sits at rung 5 while referential coherence sits at rung 11, the
    answer is still the 404 and never the index mismatch.

    PRD §2.8: "Path identifiers are validated left to right before any request body is
    inspected; only once every path identifier resolves does the server resolve the foreign
    keys carried in the body."
    PRD §2.8: "a missing quote `ERR_QUOTE_NOT_FOUND`"
    PRD §2.8: "a `quote_id` that names no quote is `ERR_QUOTE_NOT_FOUND`"
    PRD §2.9: "Every identifier in the path resolves, left to right, per §2.8 (404)."
    PRD §2.9: "Every foreign key in the body resolves, per §2.8 (404)."
    PRD §2.9: "A clause's `index_code` must equal the `commodity_index_code` of its quote's
    package (`ERR_INDEX_CODE_MISMATCH`, 422)"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."

    Design: Corner/errors/errors_triggerable_an_unknown_quote_id_is_a_404_from_the_path_and_from_the_body
    """
    _project, package, _supplier = _setup_package_and_supplier()

    from_path = api_client.get_quote(NON_EXISTENT_UUID, BUYOUT_MANAGER)
    validate_error(from_path, ApiErrorId.ERR_QUOTE_NOT_FOUND.value, 404)

    from_body = api_client.create_escalation_agreement(
        create_escalation_agreement_payload(
            quote_id=NON_EXISTENT_UUID,
            index_code="PPI_COPPER_WIRE",
            baseline_index_period="2026-07",
            cap_pct=8.0,
            contractor_share_pct=40.0,
            price_hold_through="2026-09-15T00:00:00.000Z",
        ),
        BUYOUT_MANAGER,
    )
    validate_error(from_body, ApiErrorId.ERR_QUOTE_NOT_FOUND.value, 404)
    assert from_body.json()["data"]["error_id"] != ApiErrorId.ERR_INDEX_CODE_MISMATCH.value, (
        "the body existence rung outranks the referential coherence rung"
    )

    for response in (from_path, from_body):
        body = response.json()
        assert body["data"]["message"].strip(), "every error envelope carries a message"
        assert body["meta"]["api_request_id"].startswith("req_")

    package_read = read_package(package["id"])
    assert package_read["status"] == "IDENTIFIED"
    assert package_read["open_quote_count"] == 0
