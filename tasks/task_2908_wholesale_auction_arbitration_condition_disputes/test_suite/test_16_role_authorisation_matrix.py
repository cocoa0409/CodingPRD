"""The role matrix probed on both sides: six write routes refused to the wrong role
before any business check runs, one shared write route, and the uniformly open reads."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import INSPECTOR_USER_ID, MECHANICAL_POLICY
from test_helpers.factories import (
    build_case_world,
    build_sale_world,
    case_payload,
    create_buyer,
    create_inspection,
    create_seller,
    evidence_payload,
    sale_payload,
    seller_payload,
)
from test_helpers.test_users import (
    admin_headers,
    arbitrator_headers,
    buyer_rep_headers,
    clerk_headers,
    inspector_headers,
    seller_rep_headers,
)

YELLOW_SALE = {"light_channel": "YELLOW"}
MECHANICAL_CLAIM = {
    "defect_class": "MECHANICAL",
    "claim_amount_cents": 60000,
    "odometer_at_claim": 84100,
    "complaint_text": "Transmission slips under load",
}


def test_a_bidders_representative_cannot_register_a_consignor(api):
    """Registration belongs to auction-house operations, and the buying dealer's
    representative has no share of it.

    PRD: "Registers sellers and buyers, publishes arbitration policy, releases sale
    proceeds, records transportation legs, reinstates blocked sellers, and drives the
    logical clock and the deadline sweep."

    Design: Corner/rbac/a_buyer_rep_cannot_register_a_seller
    """
    buyer = create_buyer(api)

    response = api.create_seller(
        seller_payload(name="Ridgeline Motors", dealer_license_no="SL-1001"),
        buyer_rep_headers(buyer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403


def test_a_consignors_representative_cannot_record_its_own_sale(api):
    """The block's own staff record units, so naming that very consignor in the body
    buys no authority at all.

    PRD: "Records units as they cross the block and the condition announcements read
    on them."

    Design: Corner/rbac/a_seller_rep_cannot_record_a_sale_at_the_block
    """
    seller = create_seller(api)
    buyer = create_buyer(api)

    response = api.create_sale(
        sale_payload(seller["id"], buyer["id"]), seller_rep_headers(seller["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403

    _, meta = validate_paginated(api.list_sales(admin_headers()))
    assert meta["total_count"] == 0


def test_a_block_clerk_cannot_open_review_even_on_an_unevidenced_claim(api):
    """The role gate fires ahead of the evidence-sufficiency gates, so the answer is
    an authorisation failure rather than a complaint about the empty file.

    PRD: "Once both headers are present, the service checks the supplied role against
    the roles authorised for the requested operation in §4; a role that is not listed
    there is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Both of these checks
    precede request-body parsing, so a malformed payload sent by an unauthenticated or
    unauthorised caller never produces a schema error."

    Design: Corner/rbac/a_block_clerk_cannot_open_a_case_review
    """
    world = build_case_world(
        api,
        [MECHANICAL_POLICY],
        sale_overrides=dict(YELLOW_SALE),
        case_overrides=dict(MECHANICAL_CLAIM),
    )

    response = api.open_review(world["case"]["id"], {}, clerk_headers())

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "SUBMITTED"
    assert case["review_opened_at_utc"] is None
    assert case["intake_arbitrator_user_id"] is None


def test_the_bidder_who_paid_for_an_inspection_cannot_file_its_findings(api):
    """Filing findings is the technician's act, so paying for the programme does not
    let the buyer write the outcome.

    PRD: "Files inspection findings and may attach evidence to a case."

    Design: Corner/rbac/a_buyer_rep_cannot_complete_the_inspection_it_paid_for
    """
    world = build_sale_world(api, [MECHANICAL_POLICY], **YELLOW_SALE)
    inspection = create_inspection(
        api, world["sale"]["id"], world["buyer"]["id"], program_tier="STANDARD"
    )

    response = api.complete_inspection(
        inspection["id"],
        {"findings": ["MECHANICAL"]},
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403

    rows, meta = validate_unpaginated(
        api.list_sale_inspections(world["sale"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rows[0]["status"] == "REQUESTED"
    assert rows[0]["findings"] == []
    assert rows[0]["completed_at_utc"] is None


def test_an_arbitrator_cannot_file_the_claim_it_would_later_hear(api):
    """Intake is the buying dealer's act; the officer is refused on the role gate
    before the sale-ownership comparison can even be reached.

    PRD: "Purchases post-sale inspections, files and evidences claims, counters and
    accepts allowance offers, withdraws claims, and pays down frivolous-claim fees."

    Design: Corner/rbac/an_arbitrator_cannot_file_a_claim
    """
    world = build_sale_world(api, [MECHANICAL_POLICY], **YELLOW_SALE)

    response = api.create_case(
        case_payload(world["sale"]["id"], **MECHANICAL_CLAIM), arbitrator_headers()
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["open_case_count"] == 0
    assert sale["arbitration_status"] == "NONE"


def test_the_claimant_cannot_answer_its_own_claim_as_the_consignor(api):
    """The answer route belongs to the consigning dealer, so the claimant is refused
    on the role gate rather than on the case's status.

    PRD: "Answers a claim with an allowance offer, a dispute, or a conceded unwind."

    Design: Corner/rbac/a_buyer_rep_cannot_file_the_seller_response
    """
    world = build_case_world(
        api,
        [MECHANICAL_POLICY],
        sale_overrides=dict(YELLOW_SALE),
        case_overrides=dict(MECHANICAL_CLAIM),
    )

    response = api.seller_response(
        world["case"]["id"],
        {"response_type": "ACCEPT_UNWIND", "response_note": "Filed by the wrong party"},
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "SUBMITTED"
    assert case["seller_conceded"] is False
    assert case["current_round_index"] == 0


def test_auction_house_operations_cannot_escalate_a_claim(api):
    """The matrix is segregation of duties rather than a hierarchy, so the role that
    settles sales and drives the sweep still cannot move a case to the panel.

    PRD: "Opens intake review, escalates exhausted negotiations, and issues
    decisions."

    Design: Corner/rbac/an_auction_admin_cannot_escalate_a_case
    """
    world = build_case_world(
        api,
        [MECHANICAL_POLICY],
        sale_overrides=dict(YELLOW_SALE),
        case_overrides=dict(MECHANICAL_CLAIM),
    )

    response = api.escalate_case(
        world["case"]["id"],
        {"escalation_note": "Front office wants this in front of a panel"},
        admin_headers(),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "SUBMITTED"
    assert case["version"] == 1


def test_a_technician_may_append_evidence_and_is_recorded_as_the_submitter(api):
    """The evidence route is shared, and the row records which of the two permitted
    roles filed it straight from the headers.

    PRD: "the submitter's identity as `submitted_by_role` — either `BuyerRep` or
    `Inspector` — and `submitted_by_user_id`, both taken from the request headers
    rather than the body."

    Design: Corner/rbac/an_inspector_may_append_evidence_as_a_shared_operation
    """
    world = build_case_world(
        api,
        [MECHANICAL_POLICY],
        sale_overrides=dict(YELLOW_SALE),
        case_overrides=dict(MECHANICAL_CLAIM),
    )

    evidence = validate_success(
        api.create_evidence(
            world["case"]["id"],
            evidence_payload(
                evidence_type="INSPECTION_REPORT",
                provider_name="Statewide Vehicle Inspection",
                document_reference="IR-77120",
                repair_estimate_cents=285000,
            ),
            inspector_headers(),
        ),
        201,
    )

    assert evidence["submitted_by_role"] == "Inspector"
    assert evidence["submitted_by_user_id"] == INSPECTOR_USER_ID
    assert evidence["verified"] is True
    assert evidence["case_version_after"] == 2

    rows, meta = validate_unpaginated(
        api.list_evidence(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["version"] == 2


def test_a_consignors_representative_may_read_across_the_whole_prefix(api):
    """Write access is narrow but read access is not: the consignor's own rep reads
    the case, the counterparty bidder and the sale's books.

    PRD: "Read access is uniformly broad: every retrieval route in the service admits
    all six roles."

    Design: Corner/rbac/a_seller_rep_may_read_every_get_under_the_prefix
    """
    world = build_case_world(
        api,
        [MECHANICAL_POLICY],
        sale_overrides=dict(YELLOW_SALE),
        case_overrides=dict(MECHANICAL_CLAIM),
    )
    headers = seller_rep_headers(world["seller"]["id"])

    case = validate_success(api.get_case(world["case"]["id"], headers), 200)
    assert case["id"] == world["case"]["id"]
    assert case["status"] == "SUBMITTED"

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], headers), 200)
    assert buyer["id"] == world["buyer"]["id"]

    entries, meta = validate_unpaginated(
        api.list_sale_ledger_entries(world["sale"]["id"], headers)
    )
    assert_unpaginated_meta(meta, 0)
    assert entries == []
