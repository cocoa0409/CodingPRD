"""Counterfeit enforcement and exposure valuation."""
import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    ENFORCEMENT,
    create_licensor,
    set_clock,
)
from test_helpers.factories import create_counterfeit_report_payload


def _report(api, licensor, **overrides):
    payload = create_counterfeit_report_payload(licensor["id"])
    payload.update(overrides)
    return validate_success(
        api.create_counterfeit_report(payload, ENFORCEMENT),
        expected_status=201,
    )


def test_a_confirmed_finding_computes_leakage_penalty_and_total(api):
    """PRD §3.10: "A confirmation on 200 units against a licensor whose
    `royalty_rate_pct` is 0.08 computes a leaked royalty of 13920 cents, a penalty
    of 34800 cents and a total exposure of 48720 cents."

    Design: Difficulty/priority_pair_validation_conflict/counterfeit_confirmation_prefers_safety_over_referential
    """

    set_clock(api)
    licensor = create_licensor(api, name="NBL Exposure",
                               royalty_rate_pct=0.08, minimum_guarantee_cents=100000)
    report = _report(api, licensor, online_listing_id="UNVERIFIED-LIST-1",
                     unit_count=500, suspect_quantity=0)

    enforced = validate_success(
        api.enforce_counterfeit_report(
            report["id"],
            {"infringement_confirmed": True, "suspect_quantity": 200},
            ENFORCEMENT,
        ),
        expected_status=200,
    )

    assert enforced["report_status"] == "ENFORCED"
    assert enforced["royalty_leakage_cents"] == 13920
    assert enforced["penalty_cents"] == 34800
    assert enforced["total_exposure_cents"] == 48720


def test_an_unconfirmed_finding_writes_zero_and_leaves_the_report_open(api):
    """PRD §3.10: "When `infringement_confirmed` is false the report writes a
    total exposure of 0 and stays in `OPEN`, and it is left open deliberately so
    that it may be enforced again after further evidence arrives."

    Design: Corner/errors/counterfeit_overcount_via_verified_listing
    """

    set_clock(api)
    licensor = create_licensor(api, name="NBL Cleared",
                               royalty_rate_pct=0.08, minimum_guarantee_cents=100000)
    report = _report(api, licensor, unit_count=100, suspect_quantity=0)

    cleared = validate_success(
        api.enforce_counterfeit_report(
            report["id"],
            {"infringement_confirmed": False, "suspect_quantity": 0},
            ENFORCEMENT,
        ),
        expected_status=200,
    )

    assert cleared["report_status"] == "OPEN"
    assert cleared["total_exposure_cents"] == 0


def test_a_confirmed_overcount_is_refused(api):
    """PRD §3.10: "the `suspect_quantity` may not exceed the report's `unit_count`,
    since more units cannot be counterfeit than were observed ... "
    PRD §3.10: "Two integrity checks guard a confirmation, and both are reported
    as `ERR_COUNTERFEIT_OVERCOUNT` (HTTP 422)"

    Design: Corner/errors/counterfeit_overcount_via_verified_listing
    """

    set_clock(api)
    licensor = create_licensor(api, name="Licensor AB",
                               royalty_rate_pct=0.08, minimum_guarantee_cents=100000)
    report = _report(api, licensor, venue_code="BOS_VENUE",
                     online_listing_id="VERIFIED-LIST-31", unit_count=40,
                     suspect_quantity=0)

    resp = api.enforce_counterfeit_report(
        report["id"],
        {"infringement_confirmed": True, "suspect_quantity": 60},
        ENFORCEMENT,
    )
    validate_error(resp, ApiErrorId.ERR_COUNTERFEIT_OVERCOUNT, expected_status=422)

    read = validate_success(
        api.get_counterfeit_report(report["id"], ENFORCEMENT), expected_status=200,
    )
    assert read["report_status"] == "OPEN"
    assert read["total_exposure_cents"] == 0


def test_a_confirmed_zero_suspect_quantity_is_refused(api):
    """PRD §3.10: "a confirmed infringement may not carry a `suspect_quantity` of
    zero, since a confirmation of nothing is not a finding."

    Design: Corner/errors/counterfeit_overcount_via_verified_listing
    """

    set_clock(api)
    licensor = create_licensor(api, name="Licensor AB2",
                               royalty_rate_pct=0.08, minimum_guarantee_cents=100000)
    report = _report(api, licensor, online_listing_id="UNVERIFIED-LIST-9",
                     unit_count=40, suspect_quantity=0)

    resp = api.enforce_counterfeit_report(
        report["id"],
        {"infringement_confirmed": True, "suspect_quantity": 0},
        ENFORCEMENT,
    )
    validate_error(resp, ApiErrorId.ERR_COUNTERFEIT_OVERCOUNT, expected_status=422)


def test_a_confirmation_on_a_verified_listing_is_refused(api):
    """PRD §3.10: "the report's `online_listing_id` must not begin with the
    `VERIFIED-` prefix, because enforcement may not confirm a violation against a
    listing that has already been verified — the attempt is rejected with
    `ERR_LISTING_UNVERIFIED` (HTTP 422)."
    PRD §3.10: "Two integrity checks guard a confirmation, and both are reported
    as `ERR_COUNTERFEIT_OVERCOUNT` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/counterfeit_confirmation_prefers_safety_over_referential
    """

    set_clock(api)
    licensor = create_licensor(api, name="NBL Enforcement",
                               royalty_rate_pct=0.08, minimum_guarantee_cents=100000)
    _report(api, licensor, venue_code="ATL_POPUP",
            online_listing_id="UNVERIFIED-LISTING-42", unit_count=100,
            suspect_quantity=0)

    # A second report on a verified listing, confirmed within the observed count
    # so the listing ground is the only one that fails.
    verified = _report(api, licensor, venue_code="ATL_POPUP",
                       online_listing_id="VERIFIED-LISTING-42", unit_count=100,
                       suspect_quantity=0)
    resp = api.enforce_counterfeit_report(
        verified["id"],
        {"infringement_confirmed": True, "suspect_quantity": 40},
        ENFORCEMENT,
    )
    validate_error(resp, ApiErrorId.ERR_LISTING_UNVERIFIED, expected_status=422)

    read = validate_success(
        api.get_counterfeit_report(verified["id"], ENFORCEMENT),
        expected_status=200,
    )
    assert read["report_status"] == "OPEN"
    assert read["total_exposure_cents"] == 0


def test_an_enforced_report_takes_a_larger_confirmed_quantity(api):
    """PRD §3.10: "A report already in `ENFORCED` may be re-enforced with a larger
    confirmed quantity: the leaked royalty, the penalty and the total exposure are
    all recomputed on the newly confirmed quantity, and the report stays
    `ENFORCED`"

    Design: Corner/errors/counterfeit_overcount_via_verified_listing
    """

    set_clock(api)
    licensor = create_licensor(api, name="NBL Reenforce",
                               royalty_rate_pct=0.08, minimum_guarantee_cents=100000)
    report = _report(api, licensor, unit_count=500, suspect_quantity=0)

    first = validate_success(
        api.enforce_counterfeit_report(
            report["id"],
            {"infringement_confirmed": True, "suspect_quantity": 100},
            ENFORCEMENT,
        ),
        expected_status=200,
    )
    second = validate_success(
        api.enforce_counterfeit_report(
            report["id"],
            {"infringement_confirmed": True, "suspect_quantity": 200},
            ENFORCEMENT,
        ),
        expected_status=200,
    )

    assert second["report_status"] == "ENFORCED"
    assert second["total_exposure_cents"] > first["total_exposure_cents"]
    assert second["royalty_leakage_cents"] == 13920


def test_a_new_report_starts_open_with_no_exposure(api):
    """PRD §3.10: "A new report is written with its `report_status` in `OPEN` and
    `infringement_confirmed` null, `suspect_quantity` at 0 unless supplied,
    `royalty_leakage_cents`, `penalty_cents` and `total_exposure_cents` all at 0."

    Design: Corner/endpoints/counterfeit_list_scoped_by_licensor
    """

    set_clock(api)
    licensor = create_licensor(api, name="Licensor Y",
                               royalty_rate_pct=0.08, minimum_guarantee_cents=100000)
    report = _report(api, licensor, online_listing_id="VERIFIED-LIST-77",
                     unit_count=100, suspect_quantity=0)

    assert report["report_status"] == "OPEN"
    assert report["suspect_quantity"] == 0
    assert report["infringement_confirmed"] is None
    assert report["total_exposure_cents"] == 0


def test_counterfeit_reports_are_reachable_through_the_scoped_list(api):
    """PRD §4: "GET | `/counterfeit-reports` | List counterfeit reports filtered by
    licensor or report status | EnforcementAgent, AuditOnly"

    Design: Corner/endpoints/counterfeit_list_scoped_by_licensor
    """

    set_clock(api)
    licensor = create_licensor(api, name="Licensor Y2",
                               royalty_rate_pct=0.08, minimum_guarantee_cents=100000)
    report = _report(api, licensor, online_listing_id="VERIFIED-LIST-78",
                     unit_count=100, suspect_quantity=0)

    resp = api.list_counterfeit_reports(
        ENFORCEMENT, params={"licensor_id": licensor["id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = body["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == report["id"]
    assert rows[0]["report_status"] == "OPEN"
    assert rows[0]["total_exposure_cents"] == 0


def test_the_read_only_role_cannot_register_a_capacity_window(api):
    """PRD §2.1: "`AuditOnly` holds no exclusive operation whatsoever and can
    serve no request that mutates state."
    PRD §2.10: "the role must be permitted for the operation, otherwise
    `ERR_FORBIDDEN_ROLE` (HTTP 403)"

    Design: Corner/rbac/audit_role_cannot_register_capacity
    """
    from test_helpers import TEST_USERS

    set_clock(api)

    resp = api.create_print_capacity(
        {
            "city_code": "ATL",
            "print_type": "BASE",
            "window_start": "2026-09-01T01:00:00Z",
            "window_end": "2026-09-02T01:00:00Z",
            "capacity_qty": 20,
            "rush_sla_hours": 24,
        },
        TEST_USERS["audit_only_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_the_rights_holder_role_cannot_operate_the_press(api):
    """PRD §2.1: "`PrintOperator` exclusively prints units and records lost units."
    PRD §2.10: "the role must be permitted for the operation, otherwise
    `ERR_FORBIDDEN_ROLE` (HTTP 403)"

    Design: Corner/rbac/licensing_role_cannot_operate_the_press
    """
    from test_helpers.fixtures import (
        PLANNER,
        committed_run,
        make_licensing_ops_headers,
    )

    set_clock(api)
    setup = committed_run(api, base_qty=20)

    resp = api.print_layer(
        setup["base_layer_id"], {"printed_qty": 20},
        make_licensing_ops_headers(setup["licensor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

    layer = validate_success(
        api.get_print_layer(setup["base_layer_id"], PLANNER), expected_status=200,
    )
    assert layer["printed_qty"] == 0
    assert layer["layer_state"] == "PENDING_PRINT"


def test_a_design_cannot_be_authored_by_the_enforcement_role(api):
    """PRD §2.1: "`DesignOps` exclusively creates designs and resubmits rejected
    ones."
    PRD §2.10: "the role must be permitted for the operation, otherwise
    `ERR_FORBIDDEN_ROLE` (HTTP 403)"

    Design: Corner/validations/enforcement_role_cannot_create_a_design
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor R")

    resp = api.create_design(
        {
            "licensor_id": licensor["id"],
            "team_code": "ATL",
            "garment_sku": "CAP",
            "design_name": "R Cap",
        },
        ENFORCEMENT,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_a_request_with_no_role_header_is_unauthenticated(api):
    """PRD §2.10: "Authentication is checked second: absent or malformed
    `X-User-Role` or `X-User-ID` headers yield `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_user_role_header_returns_unauthenticated
    """
    from test_helpers import make_headers_without_role

    set_clock(api)

    resp = api.create_design(
        {
            "licensor_id": "00000000-0000-0000-0000-000000000001",
            "team_code": "ATL",
            "garment_sku": "CAP",
            "design_name": "Unreadable",
        },
        make_headers_without_role(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_reading_an_unknown_accrual_returns_not_found(api):
    """PRD §2.10: "Existence is checked fourth: a path identifier that resolves to
    nothing yields `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/validations/unknown_endpoint_returns_not_found
    """
    from test_helpers import NON_EXISTENT_UUID, TEST_USERS

    set_clock(api)

    resp = api.get_royalty_accrual(
        NON_EXISTENT_UUID, TEST_USERS["audit_only_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


@pytest.mark.parametrize("unit_count", [0, -5])
def test_a_non_positive_unit_count_is_a_shape_failure(api, unit_count):
    """PRD §3.10: "the total units observed through `unit_count`, which must be
    strictly positive"

    Design: Corner/entities/counterfeit_report_requires_positive_unit_count
    """

    set_clock(api)
    licensor = create_licensor(api, name="Licensor H")

    resp = api.create_counterfeit_report(
        {
            "licensor_id": licensor["id"],
            "venue_code": "ATL_POPUP",
            "online_listing_id": "VERIFIED-LIST-11",
            "unit_count": unit_count,
            "suspect_quantity": 0,
            "detected_at": "2026-09-01T00:00:00Z",
        },
        ENFORCEMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_a_confirmed_finding_below_the_floor_is_raised_to_it(api):
    """PRD §3.10: "a confirmed finding whose total falls below 500 cents is raised
    to 500 cents, so trivial confirmations still carry a deterrent floor."

    Design: Corner/errors/counterfeit_overcount_via_verified_listing
    """

    set_clock(api)
    licensor = create_licensor(api, name="NBL Floor",
                               royalty_rate_pct=0.01, minimum_guarantee_cents=100000)
    report = _report(api, licensor, unit_count=100, suspect_quantity=0)

    enforced = validate_success(
        api.enforce_counterfeit_report(
            report["id"],
            {"infringement_confirmed": True, "suspect_quantity": 1},
            ENFORCEMENT,
        ),
        expected_status=200,
    )
    assert enforced["total_exposure_cents"] == 500