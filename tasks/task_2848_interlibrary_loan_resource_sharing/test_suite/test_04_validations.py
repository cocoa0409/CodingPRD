"""Field, business-rule and priority-ordering validations on the write paths."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    build_loan_with_patron,
    build_loan_world,
    create_bib_item,
    create_partner,
    create_patron,
    create_rota,
    decline_offer,
    intake_request,
    list_request_shipments,
    lender_confirm,
    pickup_loan,
    read_loan,
    read_patron,
    read_request,
    receive_shipment,
    return_loan,
    run_rota_round,
    set_clock,
    ship_item,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_ill_staff_headers,
    make_partner_agent_headers,
)
from test_helpers.types import (
    BillingStatus,
    CustodyStatus,
    ItemType,
    LicensedAccessStatus,
    LocalHoldingStatus,
    MaterialType,
    OfferStatus,
    PatronStatus,
    RequestStatus,
    ShipmentStatus,
)


def test_intake_is_refused_when_the_item_is_already_on_the_local_shelf(client):
    """Only the `HELD_AVAILABLE` value blocks intake: an otherwise identical work that
    is held but checked out is admitted.

    PRD: "First, the work must not already be sitting on our own shelf: a
    `local_holding_status` of `HELD_AVAILABLE` is refused with `ERR_HELD_LOCALLY`,
    because the patron should borrow it locally instead."

    Design: Corner/validations/intake_is_refused_when_the_item_is_already_on_the_local_shelf
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9030",
        full_name="Yuki Reader",
        email="yuki@u.edu",
        patron_type="GRAD",
        department="MATH",
        max_open_requests=5,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    shelved = create_bib_item(
        client,
        title="Measure Theory Notes",
        item_type=ItemType.BOOK,
        publication_year=2015,
        isbn="978-0-000-00050-9",
        local_holding_status=LocalHoldingStatus.HELD_AVAILABLE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )
    checked_out = create_bib_item(
        client,
        title="Measure Theory Problems",
        item_type=ItemType.BOOK,
        publication_year=2015,
        isbn="978-0-000-00051-6",
        local_holding_status=LocalHoldingStatus.HELD_CHECKED_OUT,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )

    validate_error(
        client.create_request(
            F.request_payload(
                patron["id"],
                shelved["id"],
                rota["id"],
                needed_by="2026-08-09T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.HELD_LOCALLY,
        expected_status=422,
    )

    admitted = intake_request(
        client,
        patron["id"],
        checked_out["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    assert admitted["status"] == RequestStatus.SOURCING

    assert read_patron(client, patron["id"])["open_request_count"] == 1
    rows, meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(), params={"patron_id": patron["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [admitted["id"]]


def test_lender_damage_fee_above_the_replacement_cost_is_refused(client):
    """The ceiling is the snapshotted replacement cost, not the insured value, and the
    comparison is inclusive: 9001 is refused with nothing written while 9000 is taken.

    PRD: "On the `DAMAGED` branch the declared `damage_fee_cents` must be at or below
    the loan's `replacement_cost_cents` snapshot, otherwise the confirmation is refused
    with `ERR_DAMAGE_FEE_EXCEEDS_REPLACEMENT` — a library may not bill more for a
    scratch than the book is worth."

    Design: Corner/validations/lender_damage_fee_above_the_replacement_cost_is_refused
    """
    set_clock(client, CLOCK_START_ISO)
    world = build_loan_world(
        client,
        patron_kwargs={
            "external_id": "P-9031",
            "full_name": "Zoe Reader",
            "email": "zoe@u.edu",
            "patron_type": "FACULTY",
            "department": "GEOL",
            "unpaid_balance_cap_cents": 40000,
        },
        partner_kwargs={
            "code": "NORTHU",
            "name": "North University Library",
            "base_lending_fee_cents": 2000,
            "avg_turnaround_days": 4,
            "loan_period_days": 28,
            "max_renewals": 2,
        },
        entry_kwargs={
            "manual_rank": 1,
            "quoted_fee_cents": 2000,
            "quoted_turnaround_days": 4,
        },
        bib_kwargs={
            "title": "Sedimentary Basins",
            "item_type": ItemType.BOOK,
            "publication_year": 2010,
            "isbn": "978-0-000-00052-3",
            "list_price_cents": 9000,
        },
    )
    built = build_loan_with_patron(
        client,
        world,
        request_kwargs={
            "needed_by": "2026-08-09T00:00:00.000Z",
            "max_supply_fee_cents": 5000,
        },
        shipment_kwargs={
            "carrier": "FEDEX",
            "tracking_code": "FX-DM-0052",
            "insured_value_cents": 20000,
        },
    )
    loan = built["loan"]
    assert loan["replacement_cost_cents"] == 9000

    set_clock(client, "2026-08-05T00:00:00Z")
    returned = return_loan(client, loan["id"])
    assert returned["overdue_fine_cents"] == 0

    parcels = list_request_shipments(
        client, built["request"]["id"], params={"direction": "RETURN"}
    )
    return_parcel = parcels[0]

    validate_error(
        client.lender_confirm_shipment(
            return_parcel["id"],
            F.lender_confirm_payload(condition="DAMAGED", damage_fee_cents=9001),
            headers=make_partner_agent_headers(world["partner"]["id"]),
        ),
        ApiErrorId.DAMAGE_FEE_EXCEEDS_REPLACEMENT,
        expected_status=422,
    )

    untouched = read_loan(client, loan["id"])
    assert untouched["custody_status"] == CustodyStatus.RETURN_PREPARED
    assert untouched["billing_status"] == BillingStatus.NO_CHARGE
    assert untouched["damage_fee_cents"] == 0
    assert untouched["lender_processing_fee_cents"] == 0
    assert (
        validate_success(
            client.get_shipment(return_parcel["id"], headers=make_ill_staff_headers())
        )["status"]
        == ShipmentStatus.IN_TRANSIT
    )

    confirmed = lender_confirm(
        client,
        return_parcel["id"],
        world["partner"]["id"],
        condition="DAMAGED",
        damage_fee_cents=9000,
    )
    assert confirmed["status"] == ShipmentStatus.CONFIRMED_DAMAGED

    billed = read_loan(client, loan["id"])
    assert billed["billing_status"] == BillingStatus.DAMAGE_BILLED
    assert billed["damage_fee_cents"] == 9000
    assert billed["lender_processing_fee_cents"] == 2500
    assert billed["total_charge_cents"] == 11500
    assert billed["outstanding_cents"] == 11500

    assert (
        read_request(client, built["request"]["id"])["status"]
        == RequestStatus.CLOSED_WITH_DAMAGE
    )
    patron = read_patron(client, world["patron"]["id"])
    assert patron["damaged_count"] == 1
    assert patron["unpaid_balance_cents"] == 11500
    assert patron["final_risk_score"] == 19
    assert patron["status"] == PatronStatus.ACTIVE


def test_needed_by_one_second_after_the_clock_is_accepted(client):
    """The deadline test is exclusive at the clock instant, so a `needed_by` equal to
    the clock is refused while one second later is admitted with zero days of runway.

    PRD: "It declares `needed_by`, the instant after which the item is useless to the
    patron, which must be strictly later than the logical clock — an instant at or
    before the clock is `ERR_NEEDED_BY_IN_PAST`."

    Design: Corner/validations/needed_by_one_second_after_the_clock_is_accepted
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9032",
        full_name="Abe Reader",
        email="abe@u.edu",
        patron_type="STAFF",
        department="ENGR",
        max_open_requests=5,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Fluid Mechanics Casebook",
        item_type=ItemType.BOOK,
        publication_year=2016,
        isbn="978-0-000-00053-0",
        list_price_cents=9000,
    )

    validate_error(
        client.create_request(
            F.request_payload(
                patron["id"],
                bib_item["id"],
                rota["id"],
                needed_by="2026-08-01T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.NEEDED_BY_IN_PAST,
        expected_status=422,
    )

    admitted = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-01T00:00:01.000Z",
        max_supply_fee_cents=5000,
    )
    assert admitted["status"] == RequestStatus.SOURCING
    assert_same_instant(admitted["needed_by"], "2026-08-01T00:00:01.000Z")

    offer = run_rota_round(client, admitted["id"])
    assert read_request(client, admitted["id"])["days_available_at_source"] == 0
    assert offer["landed_cost_cents"] == 3000
    assert offer["effective_fee_cents"] == 2000
    assert read_patron(client, patron["id"])["open_request_count"] == 1


def test_role_check_outranks_path_existence_on_a_missing_patron(client):
    """The wrong role on a non-existent identifier reports the authorization failure,
    never the 404, so no resource existence leaks to an unauthorised caller.

    PRD: "When more than one rule could reject the same request, the outcome is not a
    matter of implementation taste: the checks are evaluated in one fixed order and the
    **first** failure decides the response."

    Design: Corner/validations/role_check_outranks_path_existence_so_a_bad_role_on_a_bad_id_returns_forbidden
    """
    set_clock(client, CLOCK_START_ISO)

    forbidden = client.create_infraction_record(
        NON_EXISTENT_UUID,
        F.infraction_payload(kind="LOST", count=1),
        headers=make_ill_staff_headers(),
    )
    forbidden_data = validate_error(
        forbidden, ApiErrorId.UNAUTHORIZED, expected_status=403
    )
    assert "external_id" not in forbidden_data
    assert "provisional_risk_score" not in forbidden_data
    assert isinstance(forbidden.json()["meta"]["api_request_id"], str)

    missing = client.create_infraction_record(
        NON_EXISTENT_UUID,
        F.infraction_payload(kind="LOST", count=1),
        headers=make_admin_headers(),
    )
    missing_data = validate_error(
        missing, ApiErrorId.PATRON_NOT_FOUND, expected_status=404
    )
    assert "external_id" not in missing_data
    assert isinstance(missing.json()["meta"]["api_request_id"], str)


def test_three_individually_valid_intakes_breach_the_open_request_cap(client):
    """Each intake is legal on its own; only the running open-request counter makes the
    third illegal, and cancelling one frees the slot at once.

    PRD: "an account whose `open_request_count` has already reached
    `max_open_requests` is refused with `ERR_PATRON_REQUEST_CAP_REACHED`"

    Design: Corner/validations/three_individually_valid_intakes_breach_the_open_request_cap
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9033",
        full_name="Bea Reader",
        email="bea@u.edu",
        patron_type="UNDERGRAD",
        department="ECON",
        max_open_requests=2,
    )
    assert patron["max_open_requests"] == 2

    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    works = [
        create_bib_item(
            client,
            title=f"Macro Policy {ordinal}",
            item_type=ItemType.BOOK,
            publication_year=2018,
            isbn=isbn,
            list_price_cents=9000,
        )
        for ordinal, isbn in (
            ("One", "978-0-000-00054-7"),
            ("Two", "978-0-000-00055-4"),
            ("Three", "978-0-000-00056-1"),
        )
    ]

    first = intake_request(
        client,
        patron["id"],
        works[0]["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    intake_request(
        client,
        patron["id"],
        works[1]["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    assert read_patron(client, patron["id"])["open_request_count"] == 2

    validate_error(
        client.create_request(
            F.request_payload(
                patron["id"],
                works[2]["id"],
                rota["id"],
                needed_by="2026-08-09T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.PATRON_REQUEST_CAP_REACHED,
        expected_status=409,
    )

    cancelled = validate_success(
        client.cancel_request(first["id"], headers=make_ill_staff_headers())
    )
    assert cancelled["status"] == RequestStatus.CANCELLED
    assert read_patron(client, patron["id"])["open_request_count"] == 1

    third = intake_request(
        client,
        patron["id"],
        works[2]["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    assert third["status"] == RequestStatus.SOURCING

    _rows, meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(), params={"patron_id": patron["id"]}
        )
    )
    assert meta["total_count"] == 3


def test_renewal_hinges_purely_on_the_lender_renewal_flag(client):
    """Two loans in identical custody state diverge only on the snapshotted lender
    permission, and the refusal names the policy rung rather than the cap rung.

    PRD: "the loan's `renewals_allowed` snapshot must be true, otherwise
    `ERR_RENEWALS_NOT_ALLOWED_BY_LENDER`; and `renewal_count` must be strictly below
    `max_renewals`, otherwise `ERR_RENEWAL_CAP_REACHED`."

    Design: Corner/validations/renewal_is_allowed_or_refused_purely_on_the_lender_renewal_flag
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9034",
        full_name="Cy Reader",
        email="cy@u.edu",
        patron_type="FACULTY",
        department="PHIL",
        max_open_requests=5,
        max_concurrent_loans=3,
    )
    permissive = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        allows_renewals=True,
        loan_period_days=28,
        max_renewals=2,
    )
    restrictive = create_partner(
        client,
        code="SHORTL",
        name="Short Loan Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=28,
        max_renewals=1,
    )

    loans = {}
    for label, partner, title, isbn, tracking in (
        ("yes", permissive, "Ethics Readings A", "978-0-000-00057-8", "1Z-YES-0057"),
        ("no", restrictive, "Ethics Readings B", "978-0-000-00058-5", "1Z-NO-0058"),
    ):
        rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
        add_rota_entry(
            client,
            rota["id"],
            partner["id"],
            manual_rank=1,
            quoted_fee_cents=2000,
            quoted_turnaround_days=4,
        )
        bib_item = create_bib_item(
            client,
            title=title,
            item_type=ItemType.BOOK,
            publication_year=2013,
            isbn=isbn,
            list_price_cents=9000,
        )
        request = intake_request(
            client,
            patron["id"],
            bib_item["id"],
            rota["id"],
            needed_by="2026-08-09T00:00:00.000Z",
            max_supply_fee_cents=5000,
        )
        offer = run_rota_round(client, request["id"])
        accept_offer(client, offer["id"], partner["id"])
        parcel = ship_item(
            client,
            offer["id"],
            partner["id"],
            carrier="UPS",
            tracking_code=tracking,
            insured_value_cents=9000,
        )
        loan = receive_shipment(client, parcel["id"])
        pickup_loan(client, loan["id"])
        loans[label] = loan

    assert loans["yes"]["renewals_allowed"] is True
    assert loans["yes"]["max_renewals"] == 2
    assert loans["no"]["renewals_allowed"] is False
    assert loans["no"]["max_renewals"] == 1
    assert_same_instant(loans["yes"]["due_at"], "2026-08-29T00:00:00.000Z")
    assert_same_instant(loans["no"]["due_at"], "2026-08-29T00:00:00.000Z")

    renewed = validate_success(
        client.renew_loan(loans["yes"]["id"], headers=make_ill_staff_headers())
    )
    assert_same_instant(renewed["due_at"], "2026-09-12T00:00:00.000Z")
    assert_same_instant(renewed["original_due_at"], "2026-08-29T00:00:00.000Z")
    assert renewed["renewal_count"] == 1

    validate_error(
        client.renew_loan(loans["no"]["id"], headers=make_ill_staff_headers()),
        ApiErrorId.RENEWALS_NOT_ALLOWED_BY_LENDER,
        expected_status=422,
    )

    refused = read_loan(client, loans["no"]["id"])
    assert_same_instant(refused["due_at"], "2026-08-29T00:00:00.000Z")
    assert refused["renewal_count"] == 0


def test_attempt_budget_is_checked_before_the_candidate_pool_is_scored(client):
    """An exhausted rota whose only entry is also disabled reports the budget failure,
    so the empty-pool answer is unreachable while the cheaper check still fails.

    PRD: "its `attempt_count`, the number of rota rounds already spent, must be strictly
    below the rota's `max_attempts`, or the round is refused with
    `ERR_ROTA_ATTEMPTS_EXHAUSTED`"

    Design: Corner/validations/attempt_budget_is_checked_before_the_candidate_pool_is_scored
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9035",
        full_name="Dee Reader",
        email="dee@u.edu",
        patron_type="GRAD",
        department="ANTH",
        max_open_requests=5,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=1)
    entry = add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Kinship Structures",
        item_type=ItemType.BOOK,
        publication_year=2011,
        isbn="978-0-000-00059-2",
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-20T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    declined = decline_offer(client, offer["id"], partner["id"], decline_reason="NOT_HELD")
    assert declined["status"] == OfferStatus.DECLINED

    disabled = validate_success(
        client.update_rota_entry(
            entry["id"],
            F.rota_entry_update_payload(is_enabled=False),
            headers=make_admin_headers(),
        )
    )
    assert disabled["is_enabled"] is False

    returned_to_sourcing = read_request(client, request["id"])
    assert returned_to_sourcing["status"] == RequestStatus.SOURCING
    assert returned_to_sourcing["attempt_count"] == 1

    validate_error(
        client.source_request(request["id"], headers=make_ill_staff_headers()),
        ApiErrorId.ROTA_ATTEMPTS_EXHAUSTED,
        expected_status=409,
    )
    validate_error(
        client.source_request(request["id"], headers=make_ill_staff_headers()),
        ApiErrorId.ROTA_ATTEMPTS_EXHAUSTED,
        expected_status=409,
    )

    unchanged = read_request(client, request["id"])
    assert unchanged["status"] == RequestStatus.SOURCING
    assert unchanged["attempt_count"] == 1

    _rows, meta = validate_paginated(
        client.list_supply_offers(
            headers=make_ill_staff_headers(), params={"request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 1
