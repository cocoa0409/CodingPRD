"""Envelope, RBAC denials, pagination, and OCC guards (PRD §2.1-§2.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    authorization_payload,
    build_user_headers,
    clearance_payload,
    create_agreement,
    create_authorized_converter,
    create_distributor,
    create_formulation,
    create_jurisdiction,
    decision_payload,
    formulation_payload,
    get_clearance,
    get_converter,
    grant_authorization,
    make_distributor_headers,
    order_payload,
    set_clock,
    setup_active_formulation,
    submit_clearance,
    successor_payload,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]


def test_response_envelope_shape_on_success_and_error(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body" with
    `response_type` "either "object" for a single resource or "array" for a list
    of resources"; and "All error API responses (4xx status codes) follow this
    standard envelope format" where "The `error_id` is a unique,
    machine-readable string that identifies the specific error."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    set_clock()
    resp = api.create_formulation(
        formulation_payload(product_code="F-ENV", name="Envelope probe"), PM
    )
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]
    assert body["response_type"] == "object"
    assert body["data"]["id"] == data["id"]

    err = api.get_formulation(NON_EXISTENT_UUID, PM)
    validate_error(err, ApiErrorId.ERR_NOT_FOUND)
    ebody = err.json()
    assert ebody["response_type"] == "error"
    assert ebody["data"]["error_id"] == "ERR_NOT_FOUND"
    assert ebody["data"]["message"]


def test_request_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
    capacity in which that user acts. A request in which either header is
    missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
    """
    set_clock()
    resp = api.create_formulation(
        formulation_payload(product_code="F-NOAUTH", name="No auth probe"), headers={}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_converter_cannot_create_formulation(api):
    """PRD §2.1: "Each endpoint admits a defined subset of these roles — all
    read (GET) endpoints are open to every one of the nine roles, while each
    write endpoint names its authorized role(s) in Section 4 — and a request
    whose `X-User-Role` is not admitted by the endpoint is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4: formulation creation is a
    ProductManager operation.

    Design: Corner/rbac/converter_cannot_create_formulation
    """
    set_clock()
    resp = api.create_formulation(
        formulation_payload(product_code="F-CONV", name="Converter probe"),
        build_user_headers("00000000-0000-4000-8000-0000000000aa", "Converter"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_productmanager_cannot_decide_clearance(api):
    """PRD §2.1: "a request whose `X-User-Role` is not admitted by the endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §3.2: "Decisions belong
    to the `RegulatoryManager`, acting only while the clearance is `SUBMITTED`".

    Design: Corner/rbac/productmanager_cannot_decide_clearance
    """
    set_clock()
    jur = create_jurisdiction()
    form = create_formulation()
    cl = submit_clearance(form["id"], jur["id"], "EXEMPT")
    resp = api.decide_clearance(cl["id"], decision_payload("CLEARED"), PM)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_clearance(cl["id"])["status"] == "SUBMITTED"


def test_orders_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` object of a list response carries exactly the
    pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a
    client can always tell how many records exist in total and whether further
    pages follow." and "The `limit` parameter sets the maximum number of items
    returned in one page; it defaults to 10 when omitted".

    Design: Corner/cross_cutting_layers/orders_list_paginates_with_total_count_and_has_more
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD", base_price_cents=10000)
    headers = make_distributor_headers(dist["id"])
    version = ag["version"]
    for qty, day in ((1, "2026-11-01T00:00:00Z"), (2, "2026-11-02T00:00:00Z"),
                     (3, "2026-11-03T00:00:00Z")):
        resp = api.create_order(
            order_payload(ag["id"], quantity=qty, requested_ship_date=day,
                          expected_price_agreement_version=version,
                          distributor_id=dist["id"]),
            headers,
        )
        validate_success(resp, 201)
        version = validate_success(api.get_price_agreement(ag["id"], CM), 200)["version"]

    page1, meta1 = validate_paginated(
        api.list_orders(CM, params={"distributor_id": dist["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_orders(CM, params={"distributor_id": dist["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta_all = validate_paginated(api.list_orders(CM, params={}))
    assert len(all_rows) == 3, "default limit 10 / offset 0 returns all three"
    assert {r["id"] for r in page1} | {r["id"] for r in page2} == {r["id"] for r in all_rows}


def test_occ_successor_create_with_stale_formulation_version_rejected(api):
    """PRD §2.6: "`POST /stewardship/formulations/{id}/successors` requires the
    request body to carry `expected_formulation_version`, holding the
    predecessor formulation's `version` as the client last observed it. If the
    predecessor's current `version` has advanced — for example because another
    writer discontinued the predecessor or created a successor from it, each of
    which bumps its version — the stale expectation no longer matches and the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_successor_create_with_stale_formulation_version_rejected
    """
    set_clock()
    form = create_formulation()
    first = api.create_successor(
        form["id"],
        successor_payload(product_code="F-100R",
                          expected_formulation_version=form["version"]),
        PM,
    )
    validate_success(first, 201)
    stale = api.create_successor(
        form["id"],
        successor_payload(product_code="F-100R2", name="Second reformulation",
                          expected_formulation_version=form["version"]),
        PM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


def test_occ_authorization_create_with_stale_converter_version_rejected(api):
    """PRD §2.6: "`POST /stewardship/converter-authorizations` requires
    `expected_converter_version`, matching the target converter's current
    `version`. Because authorization creation itself bumps the converter's
    `version`, a second authorization create carrying the pre-first version
    deterministically fails with `ERR_STALE_VERSION` (HTTP 412), even though the
    converter remains `AUTHORIZED` and otherwise eligible."

    Design: Corner/cross_cutting_layers/occ_authorization_create_with_stale_converter_version_rejected
    """
    set_clock()
    conv = create_authorized_converter()
    pre_first_version = conv["version"]
    grant_authorization(conv["id"], capability="SLITTING", territory_code="DE")
    stale = api.create_converter_authorization(
        authorization_payload(conv["id"], capability="LAMINATION", territory_code="DE",
                              valid_from="2026-10-01T00:00:00Z",
                              valid_to="2027-04-01T00:00:00Z",
                              expected_converter_version=pre_first_version),
        CM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert get_converter(conv["id"])["status"] == "AUTHORIZED"


def test_occ_order_create_with_stale_agreement_version_rejected(api):
    """PRD §2.6: "`POST /stewardship/orders` requires
    `expected_price_agreement_version`, matching the agreement's current
    `version`. Order creation itself bumps the agreement's `version`, so a
    second order carrying the pre-first version deterministically fails with
    `ERR_STALE_VERSION` (HTTP 412), even though every business field of the
    agreement is unchanged and the order would otherwise succeed."

    Design: Corner/cross_cutting_layers/occ_order_create_with_stale_agreement_version_rejected
    """
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD", base_price_cents=10000)
    headers = make_distributor_headers(dist["id"])
    first = api.create_order(
        order_payload(ag["id"], quantity=1, requested_ship_date="2026-11-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"]),
        headers,
    )
    validate_success(first, 201)
    stale = api.create_order(
        order_payload(ag["id"], quantity=1, requested_ship_date="2026-11-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"]),
        headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
