"""Role authority: what each role may do, what it may not, and the duty separation."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant, kinds_of
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    create_lending_charge,
    draft_invoice,
    escalate_request,
    list_notifications,
    read_request,
    run_rota_round,
    set_clock,
)
from test_helpers.test_users import (
    ACQ_ALT_USER_ID,
    ACQ_USER_ID,
    make_accountant_headers,
    make_acquisitions_headers,
    make_admin_headers,
    make_ill_staff_headers,
    make_partner_agent_headers,
    make_patron_headers,
)
from test_helpers.types import (
    ItemType,
    LocalHoldingStatus,
    MaterialType,
    NotificationKind,
    OfferStatus,
    PodDecision,
    PodOrderStatus,
    RequestStatus,
)

# Syntactically valid identifiers that no row ever carries, so a role refusal
# cannot be confused with a missing row.
NO_SUCH_PATRON = "00000000-0000-4000-8000-000000000c01"
NO_SUCH_REQUEST = "00000000-0000-4000-8000-000000000c02"
NO_SUCH_POD_ORDER = "00000000-0000-4000-8000-000000000c03"
NO_SUCH_PARTNER = "00000000-0000-4000-8000-000000000c04"
NO_SUCH_PATRON_CALLER = "00000000-0000-4000-8000-000000000c05"
NO_SUCH_PARTNER_CALLER = "00000000-0000-4000-8000-000000000c06"
NO_SUCH_INVOICE = "00000000-0000-4000-8000-000000000c07"


def test_each_of_the_six_roles_performs_its_own_permitted_operation(client):
    """One borrowing lifecycle is driven end to end by six different identities, each
    touching only the operations its own role is granted.

    PRD: "`IllBorrowingStaff` runs the borrowing desk: intake, royalty clearances, rota
    rounds, escalation, parcel receipt, hold-shelf pickup, return and loss declaration,
    plus the copyright-usage read." And: "`LibraryAdmin` owns partner master data,
    reciprocity terms, patron standing and migrated infraction history, and may waive a
    patron's charges."

    Design: Corner/rbac/each_of_the_six_roles_performs_its_own_permitted_operation
    """
    set_clock(client, CLOCK_START_ISO)

    rota = validate_success(
        client.create_rota(
            F.rota_payload(
                name="Monograph rota",
                material_type=MaterialType.LOAN,
                max_attempts=3,
                auto_escalate_pod=False,
                offer_response_hours=48,
            ),
            headers=make_ill_staff_headers(),
        ),
        expected_status=201,
    )
    bib_item = validate_success(
        client.create_bib_item(
            F.bib_item_payload(
                title="Roman Roads of Gaul",
                item_type=ItemType.BOOK,
                publication_year=2008,
                isbn="978-0-000-00070-7",
                list_price_cents=9000,
            ),
            headers=make_acquisitions_headers(),
        ),
        expected_status=201,
    )
    partner = validate_success(
        client.create_partner(
            F.partner_payload(
                code="NORTHU",
                name="North University Library",
                consortium_code="MIDWEST",
                base_lending_fee_cents=2000,
                avg_turnaround_days=4,
                loan_period_days=28,
                max_renewals=2,
            ),
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )
    patron = validate_success(
        client.create_patron(
            F.patron_payload(
                external_id="P-9060",
                full_name="Kim Reader",
                email="kim@u.edu",
                patron_type="FACULTY",
                department="CLAS",
                max_open_requests=5,
            ),
            headers=make_ill_staff_headers(),
        ),
        expected_status=201,
    )
    entry = validate_success(
        client.create_rota_entry(
            F.rota_entry_payload(
                rota_id=rota["id"],
                partner_id=partner["id"],
                expected_rota_version=rota["version"],
                manual_rank=1,
                quoted_fee_cents=2000,
                quoted_turnaround_days=4,
            ),
            headers=make_ill_staff_headers(),
        ),
        expected_status=201,
    )

    request = validate_success(
        client.create_request(
            F.request_payload(
                patron["id"],
                bib_item["id"],
                rota["id"],
                needed_by="2026-08-09T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_patron_headers(patron["id"]),
        ),
        expected_status=201,
    )
    assert request["status"] == RequestStatus.SOURCING
    assert request["intake_user_id"] == patron["id"]

    offer = run_rota_round(client, request["id"])
    assert offer["status"] == OfferStatus.OFFERED
    accepted = accept_offer(client, offer["id"], partner["id"])
    assert accepted["status"] == OfferStatus.ACCEPTED

    repriced = validate_success(
        client.update_bib_item(
            bib_item["id"],
            F.bib_item_update_payload(list_price_cents=11000),
            headers=make_acquisitions_headers(),
        )
    )
    assert repriced["list_price_cents"] == 11000

    own_read = validate_success(
        client.get_request(request["id"], headers=make_patron_headers(patron["id"]))
    )
    assert own_read["status"] == RequestStatus.SUPPLY_COMMITTED

    charge = create_lending_charge(
        client,
        partner["id"],
        item_title="Outbound lend, volume 4",
        charge_cents=2000,
        incurred_at="2026-08-05T00:00:00.000Z",
    )

    set_clock(client, "2026-09-01T00:00:00.000Z")
    invoice = draft_invoice(client, partner["id"], "2026-08")
    assert invoice["receivable_total_cents"] == 2150

    entry_read = validate_success(
        client.get_rota_entry(entry["id"], headers=make_ill_staff_headers())
    )
    assert entry_read["partner_id"] == partner["id"]
    charge_read = validate_success(
        client.get_lending_charge(charge["id"], headers=make_accountant_headers())
    )
    assert charge_read["charge_cents"] == 2000


def test_no_role_can_reach_another_roles_exclusive_operation(client):
    """Seven exclusive operations are each attempted by the wrong role on an identifier
    that does not exist, and every one answers on authority rather than on existence.

    PRD: "**20 —** acting role authorized for the endpoint: `ERR_UNAUTHORIZED` (403), on
    every endpoint." And: "`ConsortiumAccountant` generates, issues and settles partner
    invoices and applies patron charge settlements."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    set_clock(client, CLOCK_START_ISO)

    refusals = (
        client.create_partner(
            F.partner_payload(
                code="SNEAK",
                name="Sneak Library",
                consortium_code="MIDWEST",
                supplies_electronic=False,
                allows_renewals=False,
                loan_period_days=21,
                max_renewals=1,
            ),
            headers=make_ill_staff_headers(),
        ),
        client.update_patron(
            NO_SUCH_PATRON,
            F.patron_update_payload(status="BLOCKED"),
            headers=make_ill_staff_headers(),
        ),
        client.source_request(NO_SUCH_REQUEST, headers=make_acquisitions_headers()),
        client.decide_pod_order(
            NO_SUCH_POD_ORDER,
            F.pod_decision_payload(decision=PodDecision.APPROVE),
            headers=make_accountant_headers(),
        ),
        client.create_lending_charge(
            F.lending_charge_payload(
                NO_SUCH_PARTNER,
                item_title="Not mine to bill",
                charge_cents=2000,
                incurred_at=CLOCK_START_ISO,
            ),
            headers=make_patron_headers(NO_SUCH_PATRON_CALLER),
        ),
        client.get_copyright_usage(
            headers=make_partner_agent_headers(NO_SUCH_PARTNER_CALLER),
            params={"issn": "1111-0001", "calendar_year": 2026},
        ),
        client.issue_invoice(NO_SUCH_INVOICE, headers=make_admin_headers()),
    )
    assert len(refusals) == 7
    for response in refusals:
        validate_error(response, ApiErrorId.UNAUTHORIZED, expected_status=403)
        assert response.status_code != 404

    _rows, meta = validate_paginated(client.list_partners(headers=make_admin_headers()))
    assert meta["total_count"] == 0
    validate_error(
        client.get_lending_charge(NO_SUCH_PARTNER, headers=make_accountant_headers()),
        ApiErrorId.LENDING_CHARGE_NOT_FOUND,
        expected_status=404,
    )


def test_the_same_user_may_not_escalate_and_then_decide_the_purchase_on_demand_order(
    client,
):
    """The duty check compares the acting identity, not the acting role, so the escalating
    user is refused on the decision while a second librarian with the same role is not.

    PRD: "The order must be at `PROPOSED`, otherwise `ERR_POD_ORDER_INVALID_STATE`, and
    the deciding `X-User-ID` must differ from `escalated_by_user_id`, otherwise
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_same_user_may_not_escalate_and_then_decide_the_purchase_on_demand_order
    """
    set_clock(client, CLOCK_START_ISO)
    patron = validate_success(
        client.create_patron(
            F.patron_payload(
                external_id="P-9061",
                full_name="Lou Reader",
                email="lou@u.edu",
                patron_type="FACULTY",
                department="ARTH",
                max_open_requests=5,
            ),
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )
    partner = validate_success(
        client.create_partner(
            F.partner_payload(
                code="NORTHU",
                name="North University Library",
                consortium_code="MIDWEST",
                base_lending_fee_cents=2000,
                avg_turnaround_days=4,
                loan_period_days=28,
                max_renewals=2,
            ),
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )
    rota = validate_success(
        client.create_rota(
            F.rota_payload(
                name="Monograph rota",
                material_type=MaterialType.LOAN,
                max_attempts=3,
                auto_escalate_pod=False,
                offer_response_hours=48,
            ),
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        client.create_rota_entry(
            F.rota_entry_payload(
                rota_id=rota["id"],
                partner_id=partner["id"],
                expected_rota_version=rota["version"],
                manual_rank=1,
                quoted_fee_cents=2000,
                quoted_turnaround_days=4,
            ),
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )
    bib_item = validate_success(
        client.create_bib_item(
            F.bib_item_payload(
                title="Baroque Altarpieces",
                item_type=ItemType.BOOK,
                publication_year=2006,
                isbn="978-0-000-00071-4",
                list_price_cents=9000,
            ),
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )
    request = validate_success(
        client.create_request(
            F.request_payload(
                patron["id"],
                bib_item["id"],
                rota["id"],
                needed_by="2026-08-20T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        expected_status=201,
    )

    order = escalate_request(
        client,
        request["id"],
        headers=make_ill_staff_headers(ACQ_USER_ID),
        vendor="GOBI",
    )
    assert order["status"] == PodOrderStatus.PROPOSED
    assert order["escalated_by_user_id"] == ACQ_USER_ID
    assert order["list_price_cents"] == 9000
    assert read_request(client, request["id"])["status"] == RequestStatus.ESCALATED_POD

    validate_error(
        client.decide_pod_order(
            order["id"],
            F.pod_decision_payload(
                decision=PodDecision.APPROVE, decision_note="Cheaper to buy"
            ),
            headers=make_acquisitions_headers(ACQ_USER_ID),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    undecided = validate_success(
        client.get_pod_order(order["id"], headers=make_acquisitions_headers())
    )
    assert undecided["status"] == PodOrderStatus.PROPOSED
    assert undecided["decided_by_user_id"] is None
    assert undecided["decided_at"] is None
    untouched_bib = validate_success(
        client.get_bib_item(bib_item["id"], headers=make_acquisitions_headers())
    )
    assert untouched_bib["local_holding_status"] == LocalHoldingStatus.NONE

    approved = validate_success(
        client.decide_pod_order(
            order["id"],
            F.pod_decision_payload(
                decision=PodDecision.APPROVE, decision_note="Cheaper to buy"
            ),
            headers=make_acquisitions_headers(ACQ_ALT_USER_ID),
        )
    )
    assert approved["status"] == PodOrderStatus.APPROVED
    assert approved["decided_by_user_id"] == ACQ_ALT_USER_ID
    assert_same_instant(approved["decided_at"], CLOCK_START_ISO)

    received = validate_success(
        client.receive_pod_order(
            order["id"], headers=make_acquisitions_headers(ACQ_ALT_USER_ID)
        )
    )
    assert received["status"] == PodOrderStatus.RECEIVED
    assert_same_instant(received["received_at"], CLOCK_START_ISO)
    filled_bib = validate_success(
        client.get_bib_item(bib_item["id"], headers=make_acquisitions_headers())
    )
    assert filled_bib["local_holding_status"] == LocalHoldingStatus.HELD_AVAILABLE

    closed = read_request(client, request["id"])
    assert closed["status"] == RequestStatus.FILLED_BY_PURCHASE
    notices = kinds_of(list_notifications(client, request["id"]))
    assert NotificationKind.POD_APPROVED in notices
    assert NotificationKind.PURCHASE_RECEIVED in notices
