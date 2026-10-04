"""RBAC and authentication enforcement."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_inspector,
    create_laboratory,
    make_director_headers,
    make_inspector_headers,
    respond_and_accept,
    setup_findings_issued,
    validate_error,
)

OFFICER = TEST_USERS["officer_headers"]


def test_auth_missing_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a role not in
    this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/auth_missing_headers_returns_401
    """
    resp = api.create_laboratory({"name": "Anon Lab", "clia_number": "45D1099001"},
                                 headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_laboratory_director_cannot_decide_cycle(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/inspection-cycles/{cycleId}/decide` | Move a cycle from
    FINDINGS_ISSUED to DECIDED; cascades laboratory status |
    AccreditationOfficer"

    Design: Corner/roles/laboratory_director_cannot_decide_cycle
    """
    ctx = setup_findings_issued(level="LEVEL_1")
    respond_and_accept(ctx["finding"]["id"], ctx["lab"]["id"],
                       ctx["inspectors"][1]["id"])
    resp = api.decide_cycle(ctx["cycle"]["id"], "ACCREDITED",
                            make_director_headers(ctx["lab"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    from test_helpers import get_success_data
    cycle_after = get_success_data(
        api.get_inspection_cycle(ctx["cycle"]["id"], OFFICER))
    assert cycle_after["status"] == "FINDINGS_ISSUED"


def test_inspector_cannot_create_laboratory_or_shipment(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/laboratories` | Create a laboratory |
    AccreditationOfficer"
    PRD §4: "POST | `/pt-shipments` | Record a challenge shipment for a
    subscription | PTCoordinator"

    Design: Corner/roles/inspector_cannot_create_laboratory_or_shipment
    """
    lab = create_laboratory(name="Role Lab", clia_number="45D1000047")
    insp = create_inspector(lab["id"], specialties=["CHEMISTRY"],
                            full_name="Role Inspector")
    headers = make_inspector_headers(insp["id"])

    resp_lab = api.create_laboratory(
        {"name": "Nope Lab", "clia_number": "45D1000048"}, headers)
    validate_error(resp_lab, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    resp_ship = api.create_pt_shipment(
        {"subscription_id": NON_EXISTENT_UUID, "event_code": "X"}, headers)
    validate_error(resp_ship, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
