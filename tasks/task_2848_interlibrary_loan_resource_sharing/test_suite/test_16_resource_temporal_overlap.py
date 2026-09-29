"""Two contended resources under opposite interval conventions: a partner's agreement
timeline, whose windows are half-open, and a patron's loan capacity, whose windows are
closed."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.factories import agreement_payload
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_agreement,
    create_bib_item,
    create_partner,
    create_patron,
    create_rota,
    intake_request,
    list_request_loans,
    partner_version,
    read_loan,
    read_request,
    receive_shipment,
    run_rota_round,
    set_clock,
    ship_item,
)
from test_helpers.test_users import make_admin_headers, make_ill_staff_headers
from test_helpers.types import (
    AgreementStatus,
    CustodyStatus,
    FeeWaiverMode,
    ItemType,
    MaterialType,
    RequestStatus,
    SettlementMode,
    ShipmentStatus,
)


def _partner_with_two_adjacent_agreement_windows(client):
    """One partner carrying two agreements that meet end-to-start at the turn of the year."""
    set_clock(client, CLOCK_START_ISO)
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    first = create_agreement(
        client,
        partner["id"],
        expected_partner_version=partner["version"],
        fee_waiver_mode=FeeWaiverMode.NONE,
        settlement_mode=SettlementMode.GROSS,
        turnaround_guarantee_days=5,
        balance_tolerance_items=3,
        effective_from="2026-09-01T00:00:00.000Z",
        effective_to="2027-01-01T00:00:00.000Z",
    )
    second = create_agreement(
        client,
        partner["id"],
        fee_waiver_mode=FeeWaiverMode.FULL,
        settlement_mode=SettlementMode.NET,
        turnaround_guarantee_days=4,
        balance_tolerance_items=5,
        effective_from="2027-01-01T00:00:00.000Z",
        effective_to="2027-07-01T00:00:00.000Z",
    )
    return {"partner": partner, "first": first, "second": second}


def test_an_agreement_beginning_exactly_where_another_ends_is_not_an_intersection(client):
    """The second window starts at the very instant the first one stops covering, and the
    half-open convention lets both live on the same partner, each bumping the parent version.

    PRD: "Adjacency is therefore permitted: an agreement beginning at exactly the instant
    another one ends does not intersect it." And: "Both the create and the supersede flip run
    under the optimistic-concurrency guard of §2.7, and the create increments the parent
    partner's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/agreement_windows_are_half_open_so_adjacency_clears_and_intersection_conflicts
    """
    world = _partner_with_two_adjacent_agreement_windows(client)
    partner = world["partner"]

    assert world["first"]["status"] == AgreementStatus.ACTIVE
    assert world["second"]["status"] == AgreementStatus.ACTIVE
    assert_same_instant(world["first"]["effective_to"], "2027-01-01T00:00:00.000Z")
    assert_same_instant(world["second"]["effective_from"], "2027-01-01T00:00:00.000Z")
    assert partner_version(client, partner["id"]) == partner["version"] + 2

    rows, meta = validate_paginated(
        client.list_agreements(
            headers=make_admin_headers(), params={"partner_id": partner["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in rows) == sorted(
        [world["first"]["id"], world["second"]["id"]]
    )

    active_rows, active_meta = validate_paginated(
        client.list_agreements(
            headers=make_admin_headers(),
            params={"partner_id": partner["id"], "status": AgreementStatus.ACTIVE},
        )
    )
    assert active_meta["total_count"] == 2
    assert len(active_rows) == 2


def test_a_window_straddling_both_neighbours_is_refused_and_writes_nothing(client):
    """A third window that genuinely intersects each of the two established ones is rejected,
    and the rejection is total: the parent version does not move and neither neighbour changes.

    PRD: "A new agreement intersects an existing `ACTIVE` agreement on the same partner when
    the new window's `effective_from` is strictly before the existing window's `effective_to`
    **and** the existing window's `effective_from` is strictly before the new window's
    `effective_to`; any such intersection is refused with `ERR_AGREEMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/agreement_windows_are_half_open_so_adjacency_clears_and_intersection_conflicts
    """
    world = _partner_with_two_adjacent_agreement_windows(client)
    partner_id = world["partner"]["id"]
    before = partner_version(client, partner_id)

    validate_error(
        client.create_agreement(
            agreement_payload(
                partner_id=partner_id,
                expected_partner_version=before,
                fee_waiver_mode=FeeWaiverMode.CAPPED,
                capped_waiver_cents=4000,
                settlement_mode=SettlementMode.GROSS,
                turnaround_guarantee_days=6,
                balance_tolerance_items=3,
                effective_from="2026-12-01T00:00:00.000Z",
                effective_to="2027-02-01T00:00:00.000Z",
            ),
            headers=make_admin_headers(),
        ),
        ApiErrorId.AGREEMENT_WINDOW_OVERLAP,
        expected_status=409,
    )

    assert partner_version(client, partner_id) == before

    rows, meta = validate_paginated(
        client.list_agreements(
            headers=make_admin_headers(),
            params={"partner_id": partner_id, "status": AgreementStatus.ACTIVE},
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in rows) == sorted(
        [world["first"]["id"], world["second"]["id"]]
    )


def _one_week_loan_held_and_a_second_parcel_waiting_in_transit(client):
    """A patron allowed one concurrent loan, holding a week-long loan received on the first of
    the month, with a second parcel still in transit."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8015",
        full_name="Omar Undergrad",
        email="omar@u.edu",
        patron_type="UNDERGRAD",
        department="MATH",
        max_open_requests=5,
        max_concurrent_loans=1,
        unpaid_balance_cap_cents=5000,
    )
    partner = create_partner(
        client,
        code="SHORTL",
        name="Short Loan Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=7,
        max_renewals=1,
    )
    rota = create_rota(
        client,
        name="Short loan rota",
        material_type=MaterialType.LOAN,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )

    def commit(title, isbn, publication_year, needed_by, tracking_code):
        bib_item = create_bib_item(
            client,
            title=title,
            item_type=ItemType.BOOK,
            publication_year=publication_year,
            isbn=isbn,
            list_price_cents=9000,
        )
        request = intake_request(
            client,
            patron["id"],
            bib_item["id"],
            rota["id"],
            needed_by=needed_by,
            max_supply_fee_cents=5000,
        )
        offer = run_rota_round(client, request["id"])
        accept_offer(client, offer["id"], partner["id"])
        shipment = ship_item(
            client,
            offer["id"],
            partner["id"],
            carrier="UPS",
            tracking_code=tracking_code,
            insured_value_cents=9000,
        )
        return request, shipment

    request_a, shipment_a = commit(
        "Elliptic Curves I",
        "978-0-000-00010-3",
        2012,
        "2026-08-09T00:00:00.000Z",
        "1Z-SL-0071",
    )
    loan_a = receive_shipment(client, shipment_a["id"])
    assert_same_instant(loan_a["received_at"], CLOCK_START_ISO)
    assert_same_instant(loan_a["due_at"], "2026-08-08T00:00:00.000Z")

    request_b, shipment_b = commit(
        "Elliptic Curves II",
        "978-0-000-00011-0",
        2013,
        "2026-08-20T00:00:00.000Z",
        "1Z-SL-0072",
    )
    return {
        "patron": patron,
        "loan_a": loan_a,
        "request_b": request_b,
        "shipment_b": shipment_b,
    }


def test_two_loan_windows_that_merely_touch_at_one_instant_breach_the_concurrent_cap(
    client,
):
    """A receipt on the very day the held loan falls due would open a window sharing exactly
    one instant with it, and closed intervals count that single shared instant as an overlap.

    PRD: "Each loan occupies the **closed** interval from its `received_at` to its `due_at`,
    and the counted set is that patron's loans whose `custody_status` is `AWAITING_PICKUP` or
    `WITH_PATRON` — loans at `RETURN_PREPARED`, `UNCLAIMED_RETURN_PREPARED`,
    `RETURNED_TO_LENDER` or `DECLARED_LOST` are excluded, because the item is no longer in the
    patron's hands." And: "Two windows overlap when the first starts at or before the second
    ends and the second starts at or before the first ends; because the intervals are closed,
    two windows that merely touch at a single endpoint **do** overlap."

    Design: Difficulty/resource_temporal_overlap/loan_windows_are_closed_so_touching_endpoints_breach_aggregate_loan_capacity
    """
    world = _one_week_loan_held_and_a_second_parcel_waiting_in_transit(client)
    set_clock(client, "2026-08-08T00:00:00.000Z")

    validate_error(
        client.receive_shipment(
            world["shipment_b"]["id"], headers=make_ill_staff_headers()
        ),
        ApiErrorId.PATRON_LOAN_WINDOW_CAPACITY,
        expected_status=409,
    )

    untouched = validate_success(
        client.get_shipment(world["shipment_b"]["id"], headers=make_ill_staff_headers())
    )
    assert untouched["status"] == ShipmentStatus.IN_TRANSIT

    rows, meta = validate_paginated(
        client.list_request_loans(
            world["request_b"]["id"], headers=make_ill_staff_headers()
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_request(client, world["request_b"]["id"])["status"] == (
        RequestStatus.IN_TRANSIT
    )
    assert (
        read_loan(client, world["loan_a"]["id"])["custody_status"]
        == CustodyStatus.AWAITING_PICKUP
    )


def test_one_more_day_makes_the_windows_disjoint_and_the_identical_receipt_succeeds(client):
    """The refused call is repeated unchanged a day later, when the prospective window no
    longer shares even its first instant with the held loan, and the aggregate limit clears.

    PRD: "Let the overlap count be the number of counted loans whose window overlaps the
    prospective window; receipt is refused with `ERR_PATRON_LOAN_WINDOW_CAPACITY` when that
    count plus one would exceed the patron's `max_concurrent_loans`." And: "The prospective
    window runs from the logical clock to the clock plus the request's
    `committed_loan_period_days` days."

    Design: Difficulty/resource_temporal_overlap/loan_windows_are_closed_so_touching_endpoints_breach_aggregate_loan_capacity
    """
    world = _one_week_loan_held_and_a_second_parcel_waiting_in_transit(client)
    set_clock(client, "2026-08-08T00:00:00.000Z")
    validate_error(
        client.receive_shipment(
            world["shipment_b"]["id"], headers=make_ill_staff_headers()
        ),
        ApiErrorId.PATRON_LOAN_WINDOW_CAPACITY,
    )

    set_clock(client, "2026-08-09T00:00:00.000Z")
    loan_b = receive_shipment(client, world["shipment_b"]["id"])
    assert_same_instant(loan_b["received_at"], "2026-08-09T00:00:00.000Z")
    assert_same_instant(loan_b["due_at"], "2026-08-16T00:00:00.000Z")
    assert loan_b["custody_status"] == CustodyStatus.AWAITING_PICKUP

    landed = list_request_loans(client, world["request_b"]["id"])
    assert [row["id"] for row in landed] == [loan_b["id"]]

    _, meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(),
            params={
                "patron_id": world["patron"]["id"],
                "status": RequestStatus.IN_TRANSIT,
            },
        )
    )
    assert meta["total_count"] == 0
