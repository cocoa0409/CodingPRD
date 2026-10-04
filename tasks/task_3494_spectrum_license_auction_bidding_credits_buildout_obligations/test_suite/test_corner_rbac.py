"""Breadth tests over the RBAC surface: per-endpoint role authorization,
action-value restriction on multiplexed drivers, and the outermost
authentication gate."""
from test_helpers import (
    GRANT_DAY_ISO,
    NON_EXISTENT_UUID,
    UPFRONT_10M_UNITS,
    ApiErrorId,
    add_area,
    add_block,
    begin_quiet_period,
    close_round,
    complete_assignment,
    create_band_plan_payload,
    create_bid_payload,
    create_draft_plan,
    create_open_auction,
    create_qualified_applicant,
    current_round,
    file_assignment_bid,
    file_transfer,
    get_round,
    get_transfer,
    list_licenses,
    make_bidder_headers,
    make_incumbent_operator_headers,
    place_bid,
    register_applicant,
    register_incumbent,
    set_clock,
    settle_license_in_full,
    setup_clock_active_auction,
    start_clock,
    transfer_begin_review,
    transfer_provide_info,
    transfer_request_info,
    validate_error,
    validate_paginated,
    validate_success,
)


def _transfer_in_info_requested() -> tuple:
    """Full chain to a transfer application in INFO_REQUESTED: rural R wins
    CATEGORY_A @ PEA002, settles at the 2026-10-01 grant day (license
    ACTIVE), files a FULL_ASSIGNMENT to transferee T; the TransferReviewer
    drives BEGIN_REVIEW then REQUEST_INFO. Returns (transferor_id, ta_id)."""
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction_id = ctx["auction"]["id"]
    r = create_qualified_applicant(
        auction_id,
        UPFRONT_10M_UNITS,
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    t = register_applicant(auction_id, legal_name="T Co")
    begin_quiet_period(auction_id, ctx["auction"]["application_deadline"])
    start_clock(auction_id)
    round_ = current_round(auction_id)
    place_bid(round_["id"], r["id"], "PEA002", "CATEGORY_A", 1)
    close_round(round_["id"])
    file_assignment_bid(auction_id, r["id"], "PEA002", "CATEGORY_A", 0)
    complete_assignment(auction_id)
    lic = list_licenses(auction_id=auction_id, holder_applicant_id=r["id"])[0]
    set_clock(GRANT_DAY_ISO)
    lic = settle_license_in_full(lic)
    ta = file_transfer(lic, t["id"])
    transfer_begin_review(ta["id"])
    transfer_request_info(ta["id"])
    return r["id"], ta["id"]


def test_bidder_cannot_publish_band_plan(api, auction_admin_headers):
    """PRD §2.1: "A request whose role is not on the endpoint's authorization
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
    PRD §2.1: "The `AuctionAdmin` runs band planning, the auction lifecycle,
    clock rounds, qualification review, milestone review, and incumbent
    registration and relocation scheduling; the `TransferReviewer` alone
    adjudicates secondary-market transfer applications and renewal
    applications."

    Design: Corner/rbac/bidder_cannot_publish_band_plan
    """
    plan = create_draft_plan()
    add_area(plan["id"], area_code="PEA002", name="Rural Y", population=500_000)
    add_block(plan["id"], category="CATEGORY_A")

    # A well-formed Bidder identity on an existing DRAFT plan is still
    # refused: publish is an AuctionAdmin operation.
    resp = api.publish_band_plan(plan["id"], make_bidder_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403

    plan_after = validate_success(api.get_band_plan(plan["id"], auction_admin_headers), 200)
    assert plan_after["status"] == "DRAFT"


def test_transfer_reviewer_cannot_publish_either(
    api, auction_admin_headers, transfer_reviewer_headers
):
    """PRD §2.1: "A request whose role is not on the endpoint's authorization
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
    PRD §2.1: "The two administrative roles are deliberately disjoint. The
    `AuctionAdmin` runs band planning, the auction lifecycle, clock rounds,
    qualification review, milestone review, and incumbent registration and
    relocation scheduling; the `TransferReviewer` alone adjudicates
    secondary-market transfer applications and renewal applications."

    Design: Corner/rbac/transfer_reviewer_cannot_publish_either
    """
    plan = create_draft_plan()
    add_area(plan["id"], area_code="PEA002", name="Rural Y", population=500_000)
    add_block(plan["id"], category="CATEGORY_A")

    resp = api.publish_band_plan(plan["id"], transfer_reviewer_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403

    # The role gate precedes even the existence check on the review driver.
    resp2 = api.review_applicant(NON_EXISTENT_UUID, "QUALIFY", transfer_reviewer_headers)
    validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp2.status_code == 403

    plan_after = validate_success(api.get_band_plan(plan["id"], auction_admin_headers), 200)
    assert plan_after["status"] == "DRAFT"


def test_incumbent_operator_cannot_close_round(api, auction_admin_headers):
    """PRD §2.1: "A request whose role is not on the endpoint's authorization
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
    PRD §2.1: "The `AuctionAdmin` runs band planning, the auction lifecycle,
    clock rounds, qualification review, milestone review, and incumbent
    registration and relocation scheduling; the `TransferReviewer` alone
    adjudicates secondary-market transfer applications and renewal
    applications."

    Design: Corner/rbac/incumbent_operator_cannot_close_round
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {
                "legal_name": "Rural Wireless Co",
                "claims_rural_credit": True,
                "service_population": 200_000,
            }
        ],
    )
    inc = register_incumbent(
        ctx["plan"]["id"],
        ctx["areas"]["PEA002"]["id"],
        callsign="KZ1",
        relocation_cost_cents=1000,
    )
    round_id = ctx["round"]["id"]

    resp = api.close_round(round_id, make_incumbent_operator_headers(inc["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403

    assert get_round(round_id)["status"] == "OPEN"


def test_auction_admin_cannot_place_bid(api, auction_admin_headers):
    """PRD §3.5: "A `Bidder` places a clock bid against an open round by
    supplying `area_code`, `category`, and a whole-number `quantity` between
    1 and the block's `supply_per_area`"
    PRD §2.1: "A request whose role is not on the endpoint's authorization
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."

    Design: Corner/rbac/auction_admin_cannot_place_bid
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {
                "legal_name": "Rural Wireless Co",
                "claims_rural_credit": True,
                "service_population": 200_000,
            }
        ],
    )
    round_id = ctx["round"]["id"]

    resp = api.place_bid(
        round_id,
        create_bid_payload("PEA002", "CATEGORY_A", 1),
        auction_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403

    rows, meta = validate_paginated(api.list_round_bids(round_id, auction_admin_headers))
    assert rows == []
    assert meta["total_count"] == 0


def test_bidder_provide_info_allowed_but_approve_denied(api, auction_admin_headers):
    """PRD §3.9: "requesting information (`REQUEST_INFO`) moves it
    `UNDER_REVIEW → INFO_REQUESTED`; and the transferor — and only the
    transferor, as a `Bidder` — supplies the information (`PROVIDE_INFO`),
    moving it `INFO_REQUESTED → UNDER_REVIEW`."
    PRD §2.1: "Endpoints that multiplex several operations behind a single
    `action` field additionally restrict which role may supply which action
    value: on the transfer adjudication driver, a `Bidder` may perform only
    `PROVIDE_INFO`; on the incumbent transition driver, an
    `IncumbentOperator` may not perform `BEGIN_RELOCATION`, and an
    `AuctionAdmin` may not perform `SUBMIT_PLAN`, `DISPUTE`,
    `RESUBMIT_PLAN`, or `CONFIRM_CLEARED`. A caller whose role is permitted
    on the endpoint but not on the requested action value is rejected with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/bidder_provide_info_allowed_but_approve_denied
    """
    r_id, ta_id = _transfer_in_info_requested()

    # The transferor Bidder may PROVIDE_INFO: INFO_REQUESTED -> UNDER_REVIEW.
    provided = transfer_provide_info(ta_id, r_id)
    assert provided["status"] == "UNDER_REVIEW"

    # ...but adjudication belongs to the TransferReviewer alone.
    resp = api.review_transfer_application(
        ta_id, {"action": "APPROVE"}, make_bidder_headers(r_id)
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403

    assert get_transfer(ta_id)["status"] == "UNDER_REVIEW"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
    identifying the acting party, and `X-User-Role`, naming one of four
    roles — `AuctionAdmin`, `Bidder`, `IncumbentOperator`, and
    `TransferReviewer`. A request missing either header, or carrying a role
    value outside this set, is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_band_plan(
        create_band_plan_payload(
            band_name="Anon Band", frequency_start_mhz=900, frequency_end_mhz=960
        ),
        {},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401
