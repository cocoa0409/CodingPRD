"""Corner-design translations: authentication, role authorization, and the
segregation-of-duties rule (PRD §2.1, §2.10 gates 1-2, §3.7, §4).
"""
from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    NON_EXISTENT_UUID,
    create_barrel_payload,
    create_bonded_report_payload,
    create_filed_report,
    create_label_payload,
    create_program_payload,
    make_compliance_officer_headers,
    set_clock,
    validate_error,
    validate_success,
)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, declaring the capacity
    in which they act."
    PRD §2.1: "A request missing either header, or presenting a role outside
    this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    set_clock(DEFAULT_CLOCK_ISO)

    # No X-User-ID and no X-User-Role at all.
    resp = api.list_barrels({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_warehouse_manager_cannot_create_label(api, warehouse_manager_headers):
    """PRD §2.1: "A request whose authenticated role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/barrel-aging/labels` | Register a label with its
    immutable age statement | MasterBlender |"

    Design: Corner/rbac/warehouse_manager_cannot_create_label
    """
    set_clock(DEFAULT_CLOCK_ISO)

    resp = api.create_label(
        create_label_payload(name="Forbidden Label", age_statement_years=4, spirit_type="BOURBON"),
        warehouse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_cross_role_exclusive_ops_forbidden(
    api, program_director_headers, bonded_preparer_headers, master_blender_headers,
):
    """PRD §2.1: "A request whose authenticated role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/barrel-aging/bonded-reports` | Open a bonded-period
    report; periods are half-open and non-overlapping | BondedPreparer |"
    PRD §4: "| POST | `/barrel-aging/private-selection-programs` | Open a
    single-barrel / private selection program | ProgramDirector |"
    PRD §4: "| POST | `/barrel-aging/barrels` | Fill a new barrel and place it
    into a slot (initial occupancy) | WarehouseManager |"

    Design: Corner/rbac/cross_role_exclusive_ops_forbidden
    """
    set_clock(DEFAULT_CLOCK_ISO)

    resp_reports = api.create_bonded_report(
        create_bonded_report_payload("2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        program_director_headers,
    )
    validate_error(resp_reports, ApiErrorId.ERR_FORBIDDEN_ROLE)

    resp_programs = api.create_private_selection_program(
        create_program_payload(name="Wrong Role"),
        bonded_preparer_headers,
    )
    validate_error(resp_programs, ApiErrorId.ERR_FORBIDDEN_ROLE)

    # The role gate (§2.10 gate 2) fires before payload shape and existence,
    # so the otherwise-valid body naming a non-existent slot still draws 403.
    resp_barrels = api.create_barrel(
        create_barrel_payload(NON_EXISTENT_UUID),
        master_blender_headers,
    )
    validate_error(resp_barrels, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_filer_cannot_accept_own_report(api):
    """PRD §3.7: "Judgment belongs to a different desk: a `ComplianceOfficer`
    accepts a `FILED` report, moving it to the terminal `ACCEPTED`, or rejects
    it, moving it to `REJECTED` — and in either case the officer's `X-User-ID`
    must differ from the report's `filed_by_user_id`."
    PRD §3.7: "An accept or reject attempted by the filer themselves is refused
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); a clean decision records the
    officer as `decided_by_user_id` and increments the `version`."

    Design: Corner/rbac/filer_cannot_accept_own_report
    """
    set_clock(DEFAULT_CLOCK_ISO)
    # The period closed before the startup clock, so reconcile is legal now.
    report = create_filed_report(
        "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z",
        at_clock=DEFAULT_CLOCK_ISO, preparer_user_id="prep-1",
    )
    assert report["state"] == "FILED"
    assert report["filed_by_user_id"] == "prep-1"

    # Same operator id as the filer, acting in the ComplianceOfficer role.
    resp = api.accept_bonded_report(report["id"], make_compliance_officer_headers("prep-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    accepted = validate_success(
        api.accept_bonded_report(report["id"], make_compliance_officer_headers("officer-9"))
    )
    assert accepted["state"] == "ACCEPTED"
    assert accepted["decided_by_user_id"] == "officer-9"
