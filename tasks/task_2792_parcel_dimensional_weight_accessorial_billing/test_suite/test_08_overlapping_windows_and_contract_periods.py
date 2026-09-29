"""Two dated resources whose endpoint conventions are deliberately opposite.

A surcharge window abutting an armed one is legal because window ranges are
half-open; a rate contract starting on the incumbent's last effective day is a
collision because contract periods are closed. Both exclusions are also scoped
— windows by kind and service level, contracts by shipper.
"""

import pytest

from test_helpers import (
    CARRIER_ADMIN_HEADERS,
    ERR_CONTRACT_PERIOD_OVERLAP,
    ERR_SURCHARGE_WINDOW_OVERLAP,
    activate_rate_contract,
    activate_surcharge_window,
    assert_date,
    cancel_surcharge_window,
    create_express_service_level,
    create_ground_service_level,
    create_shipper_account,
    create_surcharge_window,
    draft_rate_contract,
    get_success_data,
    ids_of,
    rate_contract_payload,
    surcharge_window_payload,
    validate_error,
    validate_success,
)

# PEAK-A occupies [2026-11-01, 2026-12-01); every probe below is aimed at one
# of its two endpoints or at its interior.
PEAK_A_START = "2026-11-01"
PEAK_A_END = "2026-12-01"
STRADDLE_START = "2026-11-15"
STRADDLE_END = "2026-12-15"

SUCCESSOR_RATE_TABLE = [
    {"zone": 2, "min_lbs": 1, "max_lbs": 20, "cents_per_lb": 400},
    {"zone": 2, "min_lbs": 21, "max_lbs": 9999, "cents_per_lb": 360},
]


# ---------------------------------------------------------------------------
# Half-open surcharge windows, scoped by kind and by service level
# ---------------------------------------------------------------------------
@pytest.fixture
def armed_express_peak_window(api):
    """An ACTIVE EXPRESS-scoped PEAK_SEASON window over [2026-11-01, 2026-12-01)."""
    express = create_express_service_level(api)
    ground = create_ground_service_level(api)
    window = create_surcharge_window(
        api,
        code="PEAK-A",
        kind="PEAK_SEASON",
        service_level_id=express["id"],
        start_date=PEAK_A_START,
        end_date=PEAK_A_END,
        per_package_cents=65,
        oversize_add_cents=4500,
    )
    assert window["status"] == "SCHEDULED"
    armed = activate_surcharge_window(api, window["id"])
    assert armed["status"] == "ACTIVE"
    return {
        "express_id": express["id"],
        "ground_id": ground["id"],
        "peak_a": armed,
    }


def _schedule_window(api, **kwargs):
    """Attempt one surcharge window and return the raw response."""
    return api.create_surcharge_window(
        surcharge_window_payload(**kwargs), CARRIER_ADMIN_HEADERS
    )


def _windows(api, **params):
    """List surcharge windows through the admin's own view."""
    return get_success_data(
        api.list_surcharge_windows(CARRIER_ADMIN_HEADERS, dict(params, limit=100))
    )


def test_a_window_starting_exactly_where_an_armed_one_ends_does_not_collide(
    api, armed_express_peak_window
):
    """PRD §3.2: "The date range is **half-open**: `start_date` is the first calendar date inside the window and `end_date` is the date on which the window stops applying, so `end_date` is excluded."
    PRD §3.2: "An intersection is rejected with `ERR_SURCHARGE_WINDOW_OVERLAP` (HTTP 409), but **abutting windows do not collide**: a window ending exactly where the next begins is legal, because the first window has already stopped applying on that date."
    PRD §3.2: "A window opens at `status` `SCHEDULED`, which means it is on the calendar but invisible to pricing."

    Design: Difficulty/resource_temporal_overlap/surcharge_windows_use_half_open_intervals_scoped_by_kind_and_service_level
    """
    ctx = armed_express_peak_window
    peak_b = validate_success(
        _schedule_window(
            api,
            code="PEAK-B",
            kind="PEAK_SEASON",
            service_level_id=ctx["express_id"],
            start_date=PEAK_A_END,
            end_date="2027-01-01",
            per_package_cents=80,
            oversize_add_cents=4500,
        ),
        201,
    )
    assert peak_b["status"] == "SCHEDULED"
    assert_date(peak_b["start_date"], PEAK_A_END, "start_date")
    assert peak_b["kind"] == "PEAK_SEASON"
    assert peak_b["service_level_id"] == ctx["express_id"]


def test_a_window_straddling_the_interior_is_refused_and_frees_its_code_again(
    api, armed_express_peak_window
):
    """PRD §3.2: "The new window's half-open range from `start_date` up to but excluding `end_date` is scanned against the half-open range of every other window sharing the same `kind` and the same `service_level_id` scope whose `status` is `SCHEDULED` or `ACTIVE`."
    PRD §3.2: "The `code` must be unique across all windows (`ERR_DUPLICATE_KEY` otherwise)."

    Design: Difficulty/resource_temporal_overlap/surcharge_windows_use_half_open_intervals_scoped_by_kind_and_service_level
    """
    ctx = armed_express_peak_window
    validate_success(
        _schedule_window(
            api,
            code="PEAK-B",
            kind="PEAK_SEASON",
            service_level_id=ctx["express_id"],
            start_date=PEAK_A_END,
            end_date="2027-01-01",
            per_package_cents=80,
        ),
        201,
    )
    validate_error(
        _schedule_window(
            api,
            code="PEAK-C",
            kind="PEAK_SEASON",
            service_level_id=ctx["express_id"],
            start_date=STRADDLE_START,
            end_date=STRADDLE_END,
            per_package_cents=90,
            oversize_add_cents=0,
        ),
        ERR_SURCHARGE_WINDOW_OVERLAP,
        409,
    )

    peak_rows = _windows(api, kind="PEAK_SEASON")
    assert len(peak_rows) == 2, (
        f"only PEAK-A and PEAK-B may exist, found {len(peak_rows)}"
    )
    assert sorted(row["code"] for row in peak_rows) == ["PEAK-A", "PEAK-B"]

    # No partial row was written, so the refused code is still available.
    revived = validate_success(
        _schedule_window(
            api,
            code="PEAK-C",
            kind="PEAK_SEASON",
            service_level_id=ctx["express_id"],
            start_date="2027-02-01",
            end_date="2027-03-01",
            per_package_cents=90,
        ),
        201,
    )
    assert revived["code"] == "PEAK-C"


def test_the_window_exclusion_is_scoped_by_kind_and_by_service_level(
    api, armed_express_peak_window
):
    """PRD §3.2: "A null `service_level_id` means the window applies to every service level; a non-null one scopes it to that single service, and a `service_level_id` that resolves to nothing is `ERR_SERVICE_LEVEL_NOT_FOUND`."
    PRD §3.2: "The new window's half-open range from `start_date` up to but excluding `end_date` is scanned against the half-open range of every other window sharing the same `kind` and the same `service_level_id` scope whose `status` is `SCHEDULED` or `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/surcharge_windows_use_half_open_intervals_scoped_by_kind_and_service_level
    """
    ctx = armed_express_peak_window
    validate_error(
        _schedule_window(
            api,
            code="PEAK-C",
            kind="PEAK_SEASON",
            service_level_id=ctx["express_id"],
            start_date=STRADDLE_START,
            end_date=STRADDLE_END,
            per_package_cents=90,
        ),
        ERR_SURCHARGE_WINDOW_OVERLAP,
        409,
    )

    demand = validate_success(
        _schedule_window(
            api,
            code="DEM-X",
            kind="DEMAND",
            service_level_id=ctx["express_id"],
            start_date=STRADDLE_START,
            end_date=STRADDLE_END,
            per_package_cents=150,
            oversize_add_cents=0,
        ),
        201,
    )
    assert demand["status"] == "SCHEDULED", (
        "a DEMAND window does not share the PEAK_SEASON partition"
    )

    carrier_wide = validate_success(
        _schedule_window(
            api,
            code="PEAK-G",
            kind="PEAK_SEASON",
            start_date=STRADDLE_START,
            end_date=STRADDLE_END,
            per_package_cents=45,
            oversize_add_cents=0,
        ),
        201,
    )
    assert carrier_wide["service_level_id"] is None, (
        "the carrier-wide window must be left unscoped, got "
        f"{carrier_wide['service_level_id']}"
    )
    assert carrier_wide["status"] == "SCHEDULED"


def test_a_cancelled_window_stops_excluding_the_dates_it_used_to_hold(
    api, armed_express_peak_window
):
    """PRD §3.2: "Cancellation reaches the window from either of two states: `SCHEDULED` → `CANCELLED` simply retires an unarmed window and bumps its `version`; `ACTIVE` → `CANCELLED` removes it from the candidate set for every *future* pricing evaluation and likewise bumps its `version`."
    PRD §3.2: "The new window's half-open range from `start_date` up to but excluding `end_date` is scanned against the half-open range of every other window sharing the same `kind` and the same `service_level_id` scope whose `status` is `SCHEDULED` or `ACTIVE`."
    PRD §3.2: "Windows can be listed with optional filters on `kind`, on `service_level_id`, and on `status`."

    Design: Difficulty/resource_temporal_overlap/surcharge_windows_use_half_open_intervals_scoped_by_kind_and_service_level
    """
    ctx = armed_express_peak_window
    peak_b = validate_success(
        _schedule_window(
            api,
            code="PEAK-B",
            kind="PEAK_SEASON",
            service_level_id=ctx["express_id"],
            start_date=PEAK_A_END,
            end_date="2027-01-01",
            per_package_cents=80,
        ),
        201,
    )
    peak_g = validate_success(
        _schedule_window(
            api,
            code="PEAK-G",
            kind="PEAK_SEASON",
            start_date=STRADDLE_START,
            end_date=STRADDLE_END,
            per_package_cents=45,
        ),
        201,
    )

    cancelled = cancel_surcharge_window(api, ctx["peak_a"]["id"])
    assert cancelled["status"] == "CANCELLED"

    # PEAK-D sits inside PEAK-A's now-cancelled range and abuts SCHEDULED
    # PEAK-B at 2026-12-01, so the only window it could have collided with is
    # the cancelled one.
    peak_d = validate_success(
        _schedule_window(
            api,
            code="PEAK-D",
            kind="PEAK_SEASON",
            service_level_id=ctx["express_id"],
            start_date=STRADDLE_START,
            end_date=PEAK_A_END,
            per_package_cents=90,
        ),
        201,
    )
    assert peak_d["status"] == "SCHEDULED", (
        "a CANCELLED window no longer excludes its own dates"
    )

    scheduled = _windows(api, kind="PEAK_SEASON", status="SCHEDULED")
    assert len(scheduled) == 3, (
        f"exactly PEAK-B, PEAK-G and PEAK-D remain SCHEDULED, found {len(scheduled)}"
    )
    assert sorted(ids_of(scheduled)) == sorted(
        [peak_b["id"], peak_g["id"], peak_d["id"]]
    )


# ---------------------------------------------------------------------------
# Closed rate-contract periods, partitioned per shipper
# ---------------------------------------------------------------------------
@pytest.fixture
def two_shippers_and_one_active_contract(api):
    """Two ACTIVE accounts where only the first holds a contract, 2026-01-01..2026-12-31."""
    first = create_shipper_account(
        api, account_number="SH-1001", name="Northwind Freight"
    )
    second = create_shipper_account(
        api, account_number="SH-2002", name="Southbound Retail"
    )
    contract = draft_rate_contract(api, first["id"])
    activated = activate_rate_contract(api, contract["id"], first["version"])
    assert activated["status"] == "ACTIVE"
    return {"first": first, "second": second, "contract": contract}


def _draft_contract(api, shipper_id, **kwargs):
    """Attempt one rate contract and return the raw response."""
    return api.create_rate_contract(
        rate_contract_payload(shipper_id, **kwargs), CARRIER_ADMIN_HEADERS
    )


def _contracts(api, **params):
    """List rate contracts through the admin's own view."""
    return get_success_data(
        api.list_rate_contracts(CARRIER_ADMIN_HEADERS, dict(params, limit=100))
    )


def _read_contract(api, contract_id):
    """Re-read one rate contract."""
    return get_success_data(api.get_rate_contract(contract_id, CARRIER_ADMIN_HEADERS))


def test_a_contract_starting_on_the_incumbents_last_effective_day_collides(
    api, two_shippers_and_one_active_contract
):
    """PRD §3.1: "Then the new contract's closed interval from `effective_from` through `effective_to` is scanned against the closed interval of every *other* contract of the same shipper whose `status` is `DRAFT` or `ACTIVE`; any intersection, **including the case where one contract's `effective_to` falls on exactly the same date as another's `effective_from`**, is rejected with `ERR_CONTRACT_PERIOD_OVERLAP` (HTTP 409)."
    PRD §3.1: "A `CarrierAdmin` drafts one against a `shipper_id` with an inclusive effectivity window running from `effective_from` through `effective_to`, a cubic-inch `dim_divisor`, a per-package `min_charge_cents` floor, a `rate_table`, and a `tier_discount_table`."

    Design: Difficulty/resource_temporal_overlap/rate_contract_periods_are_closed_intervals_so_touching_endpoints_collide
    """
    ctx = two_shippers_and_one_active_contract
    validate_error(
        _draft_contract(
            api,
            ctx["first"]["id"],
            effective_from="2026-12-31",
            effective_to="2027-06-30",
            dim_divisor=150,
            min_charge_cents=1250,
            rate_table=SUCCESSOR_RATE_TABLE,
            tier_discount_table=[],
        ),
        ERR_CONTRACT_PERIOD_OVERLAP,
        409,
    )

    rows = _contracts(api, shipper_id=ctx["first"]["id"])
    assert len(rows) == 1, (
        f"the refused draft must not be persisted, found {len(rows)} contracts"
    )
    assert rows[0]["id"] == ctx["contract"]["id"]


def test_the_day_after_the_incumbent_is_admitted_as_a_draft_successor(
    api, two_shippers_and_one_active_contract
):
    """PRD §3.1: "A contract may also name `supersedes_contract_id`, a pointer to another contract of the same shipper that this one is intended to replace on activation; it defaults to null for a shipper's first contract."
    PRD §3.1: "Every new contract is created with `status` `DRAFT` and `activated_at` null."
    PRD §3.1: "One contract is exempt from that scan: the single contract named by this request's `supersedes_contract_id`, because activating the successor is precisely the act that truncates the predecessor's window."

    Design: Difficulty/resource_temporal_overlap/rate_contract_periods_are_closed_intervals_so_touching_endpoints_collide
    """
    ctx = two_shippers_and_one_active_contract
    successor = validate_success(
        _draft_contract(
            api,
            ctx["first"]["id"],
            effective_from="2027-01-01",
            effective_to="2027-06-30",
            dim_divisor=150,
            min_charge_cents=1250,
            rate_table=SUCCESSOR_RATE_TABLE,
            tier_discount_table=[],
            supersedes_contract_id=ctx["contract"]["id"],
        ),
        201,
    )
    assert successor["status"] == "DRAFT"
    assert_date(successor["effective_from"], "2027-01-01", "effective_from")
    assert successor["supersedes_contract_id"] == ctx["contract"]["id"]
    assert successor["activated_at"] is None

    incumbent = _read_contract(api, ctx["contract"]["id"])
    assert incumbent["status"] == "ACTIVE", (
        "drafting a successor never supersedes anything on its own, got "
        f"{incumbent['status']}"
    )
    assert_date(incumbent["effective_to"], "2026-12-31", "effective_to")


def test_a_draft_contract_excludes_too_and_the_exclusion_is_partitioned_per_shipper(
    api, two_shippers_and_one_active_contract
):
    """PRD §3.1: "Then the new contract's closed interval from `effective_from` through `effective_to` is scanned against the closed interval of every *other* contract of the same shipper whose `status` is `DRAFT` or `ACTIVE`; any intersection, **including the case where one contract's `effective_to` falls on exactly the same date as another's `effective_from`**, is rejected with `ERR_CONTRACT_PERIOD_OVERLAP` (HTTP 409)."
    PRD §3.1: "Contracts may be listed with optional filters on `shipper_id`, on `supersedes_contract_id` (to find the successor of a given contract), and on `status`, and an individual contract read returns its full `rate_table` and `tier_discount_table`."

    Design: Difficulty/resource_temporal_overlap/rate_contract_periods_are_closed_intervals_so_touching_endpoints_collide
    """
    ctx = two_shippers_and_one_active_contract
    successor = validate_success(
        _draft_contract(
            api,
            ctx["first"]["id"],
            effective_from="2027-01-01",
            effective_to="2027-06-30",
            dim_divisor=150,
            min_charge_cents=1250,
            rate_table=SUCCESSOR_RATE_TABLE,
            tier_discount_table=[],
            supersedes_contract_id=ctx["contract"]["id"],
        ),
        201,
    )

    validate_error(
        _draft_contract(
            api,
            ctx["first"]["id"],
            effective_from="2027-01-01",
            effective_to="2027-03-31",
            dim_divisor=160,
            min_charge_cents=1300,
            rate_table=[{"zone": 2, "min_lbs": 1, "max_lbs": 9999, "cents_per_lb": 420}],
            tier_discount_table=[],
        ),
        ERR_CONTRACT_PERIOD_OVERLAP,
        409,
    )

    other = validate_success(
        _draft_contract(
            api,
            ctx["second"]["id"],
            effective_from="2026-06-01",
            effective_to="2027-06-30",
            dim_divisor=166,
            min_charge_cents=1000,
            rate_table=[{"zone": 2, "min_lbs": 1, "max_lbs": 9999, "cents_per_lb": 350}],
            tier_discount_table=[],
        ),
        201,
    )
    assert other["status"] == "DRAFT", (
        "a period overlapping both of the first shipper's contracts is fine for a "
        "different shipper"
    )

    assert len(_contracts(api, shipper_id=ctx["first"]["id"])) == 2
    assert ids_of(_contracts(api, shipper_id=ctx["second"]["id"])) == [other["id"]]

    by_predecessor = _contracts(api, supersedes_contract_id=ctx["contract"]["id"])
    assert ids_of(by_predecessor) == [successor["id"]], (
        "exactly the successor must be findable by the contract it supersedes"
    )
