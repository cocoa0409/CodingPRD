"""
Error resolution and access control across the licensing service.

Two families of rules meet in this file. The first is identifier resolution: a
society code already taken is a conflict rather than a second row, every read
path reports the resource type of the identifier that failed, and an action
endpoint resolves the identifiers in its path before it looks at the addressed
row's state or at the request body. The second is the authorisation ladder: the
society side of the contract is closed to a venue's own operator, the auditing
side and the settlement side are closed to each other, the human who issued a
case's findings may not then negotiate that case, and the licensing
administrator's opaque identity is never narrowed to a particular venue.
"""

from test_helpers import (
    ADMIN_USER_ID_ALT,
    APPLICATION_STATUS_DRAFT,
    AUDITOR_USER_ID,
    AUDIT_TRIGGER_ROUTINE,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_ISSUED,
    CASE_STATUS_DISPUTED,
    CASE_STATUS_FINDINGS_ISSUED,
    CASE_STATUS_OPEN,
    CASE_STATUS_SETTLED,
    CASE_STATUS_SETTLEMENT_PROPOSED,
    CLOCK_START_INSTANT,
    ERR_APPLICATION_NOT_FOUND,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_AUDIT_CASE_NOT_FOUND,
    ERR_COVERAGE_WINDOW_NOT_FOUND,
    ERR_DUPLICATE_SOCIETY_CODE,
    ERR_FORBIDDEN_ROLE,
    ERR_LICENSE_NOT_FOUND,
    ERR_RATE_SCHEDULE_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SETLIST_ENTRY_NOT_FOUND,
    ERR_SOCIETY_NOT_FOUND,
    ERR_VENUE_NOT_FOUND,
    ERR_WORK_NOT_FOUND,
    REPORT_STATUS_DRAFT,
    SETTLEMENT_USER_ID,
    SETTLEMENT_USER_ID_ALT,
    SHARE_BMI_BP,
    SUSPENSION_REASON_OPERATOR_REQUEST,
    UNUSED_UUID,
    WINDOW_KIND_SEASONAL_EVENT_RIDER,
    admin_headers,
    ascap_payload,
    assert_assessment,
    assert_bp,
    assert_count,
    assert_empty_list,
    assert_money,
    assert_version_unchanged,
    assessments_of_venue,
    audit_case_payload,
    auditor_headers,
    bar_grill_venue_payload,
    bmi_payload,
    case_row,
    close_case_payload,
    coverage_window_payload,
    get_success_data,
    given_licensed_venue,
    given_open_case,
    given_society,
    given_venue,
    license_row,
    matching_application_payload,
    payment_payload,
    performance_report_payload,
    rate_schedule_payload,
    read_rows,
    repertoire_work_payload,
    setlist_entry_payload,
    settlement_headers,
    settlement_offer_payload,
    suspend_payload,
    terminate_payload,
    validate_error,
    validate_success,
    venue_operator_headers,
    venue_row,
)

# Enum members of PRD §3.2's venue category list and §3.8's affiliation list
# that have no dedicated constant in the shared helpers.
_CATEGORY_BAR_GRILL = "BAR_GRILL"
_AFFILIATION_BMI = "BMI"

# A disposition value outside PRD §3.4's four-member enum, used only to prove
# that a path identifier is resolved before the body is inspected at all.
_UNKNOWN_DISPOSITION = "NOT_A_DISPOSITION"

# The verified annual fee a 4600 bp society charges the shared bar and grill.
_BAR_GRILL_ANNUAL_FEE_CENTS = 90017


def test_error_duplicate_society_code_is_a_conflict(api):
    """A second registration under a society code already taken is refused and
    writes nothing, while a different code from the enum is accepted.

    PRD §3.1: "`society_code` is unique across all `Society` rows, so a second
    registration attempt using a code already taken is rejected with
    `ERR_DUPLICATE_SOCIETY_CODE`."

    Design: Corner/errors/corner_error_duplicate_society_code_rejected
    """
    first = given_society(api)
    assert_bp(first["repertoire_share_bp"], SHARE_BMI_BP, "repertoire_share_bp")
    assert_count(first["licensed_venue_count"], 0, "licensed_venue_count")

    validate_error(
        api.create_society(
            bmi_payload(
                display_name="Broadcast Music Incorporated",
                repertoire_share_bp=5000,
            ),
            admin_headers(),
        ),
        ERR_DUPLICATE_SOCIETY_CODE,
    )

    # The refused registration neither created a row nor edited the incumbent.
    surviving = read_rows(api.list_societies(admin_headers()), expected_total=1)
    assert surviving[0]["id"] == first["id"]
    assert surviving[0]["display_name"] == first["display_name"]
    assert_bp(
        surviving[0]["repertoire_share_bp"], SHARE_BMI_BP, "incumbent repertoire_share_bp"
    )
    assert_version_unchanged(
        validate_success(api.get_society(first["id"], admin_headers())),
        first,
        "incumbent society",
    )

    # Uniqueness is per code, not per registration attempt.
    second = given_society(api, ascap_payload())
    assert second["id"] != first["id"]
    read_rows(api.list_societies(admin_headers()), expected_total=2)
    narrowed = read_rows(
        api.list_societies(admin_headers(), {"society_code": first["society_code"]}),
        expected_total=1,
    )
    assert narrowed[0]["id"] == first["id"]


def test_error_read_path_ids_each_report_their_own_resource_type(api):
    """Every single-resource read reports the not-found error that names the
    resource type of the identifier in its own path.

    PRD §2.8: "The request fails on the *first* identifier in the path that
    matches no row, with the 404 error naming that identifier's resource type:
    `ERR_SOCIETY_NOT_FOUND` for `society_id`, `ERR_RATE_SCHEDULE_NOT_FOUND` for
    `rate_schedule_id`, `ERR_VENUE_NOT_FOUND` for `venue_id`,
    `ERR_APPLICATION_NOT_FOUND` for `application_id`, `ERR_LICENSE_NOT_FOUND`
    for `license_id`, `ERR_COVERAGE_WINDOW_NOT_FOUND` for `coverage_window_id`,
    `ERR_WORK_NOT_FOUND` for `repertoire_work_id`, `ERR_REPORT_NOT_FOUND` for
    `report_id`, `ERR_SETLIST_ENTRY_NOT_FOUND` for `setlist_entry_id`,
    `ERR_AUDIT_CASE_NOT_FOUND` for `audit_case_id`, and
    `ERR_ASSESSMENT_NOT_FOUND` for `assessment_id`."

    Design: Corner/errors/corner_error_read_path_ids_each_return_their_own_not_found
    """
    headers = admin_headers()

    validate_error(api.get_society(UNUSED_UUID, headers), ERR_SOCIETY_NOT_FOUND)
    validate_error(
        api.get_rate_schedule(UNUSED_UUID, headers), ERR_RATE_SCHEDULE_NOT_FOUND
    )
    validate_error(api.get_venue(UNUSED_UUID, headers), ERR_VENUE_NOT_FOUND)
    validate_error(
        api.get_application(UNUSED_UUID, headers), ERR_APPLICATION_NOT_FOUND
    )
    validate_error(api.get_license(UNUSED_UUID, headers), ERR_LICENSE_NOT_FOUND)
    validate_error(
        api.get_coverage_window(UNUSED_UUID, headers), ERR_COVERAGE_WINDOW_NOT_FOUND
    )
    validate_error(
        api.get_repertoire_work(UNUSED_UUID, headers), ERR_WORK_NOT_FOUND
    )
    validate_error(
        api.get_performance_report(UNUSED_UUID, headers), ERR_REPORT_NOT_FOUND
    )
    validate_error(
        api.get_setlist_entry(UNUSED_UUID, headers), ERR_SETLIST_ENTRY_NOT_FOUND
    )
    validate_error(
        api.get_audit_case(UNUSED_UUID, headers), ERR_AUDIT_CASE_NOT_FOUND
    )
    validate_error(
        api.get_fee_assessment(UNUSED_UUID, headers), ERR_ASSESSMENT_NOT_FOUND
    )

    # The nested coverage-window list resolves its licence identifier the same way.
    validate_error(
        api.list_license_coverage_windows(UNUSED_UUID, headers), ERR_LICENSE_NOT_FOUND
    )
    validate_error(
        api.list_report_setlist_entries(UNUSED_UUID, headers), ERR_REPORT_NOT_FOUND
    )

    # An identifier that does resolve reads back normally, so the unknown
    # identifier is the only thing the refusals were about.
    society = given_society(api)
    assert (
        validate_success(api.get_society(society["id"], headers))["id"] == society["id"]
    )


def test_error_action_path_ids_resolve_before_state_and_shape_checks(api):
    """An action endpoint resolves the identifiers in its path first: an unknown
    identifier produces that resource type's not-found error even when the
    addressed row's state or the request body would also have been refused.

    PRD §2.12: "Rules are evaluated **strictly in ascending priority order** and
    the **first** failing rule produces the error; later rules are never
    evaluated and their errors never surface."

    Design: Corner/errors/corner_error_action_path_ids_resolve_before_state_checks
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    licence = setup["license"]
    venue = setup["venue"]

    # Activation's departure-state rule would reject an already active licence,
    # but the unknown identifier is resolved long before that rule is reached.
    validate_error(
        api.activate_license(UNUSED_UUID, admin_headers()), ERR_LICENSE_NOT_FOUND
    )

    # A disposition outside the enum is a body-shape defect, which sits below
    # path existence in the ladder.
    validate_error(
        api.review_application(
            UNUSED_UUID, {"disposition": _UNKNOWN_DISPOSITION}, admin_headers()
        ),
        ERR_APPLICATION_NOT_FOUND,
    )

    # An inverted half-open interval is likewise below path existence.
    validate_error(
        api.create_coverage_window(
            UNUSED_UUID,
            coverage_window_payload(
                "2027-01-04T00:00:00Z",
                "2026-12-20T00:00:00Z",
                WINDOW_KIND_SEASONAL_EVENT_RIDER,
            ),
            admin_headers(),
        ),
        ERR_LICENSE_NOT_FOUND,
    )

    validate_error(
        api.pay_assessment(UNUSED_UUID, payment_payload(1), admin_headers()),
        ERR_ASSESSMENT_NOT_FOUND,
    )

    # A performance datetime outside every conceivable period cannot be judged
    # until the report the period belongs to has been found.
    validate_error(
        api.create_setlist_entry(
            UNUSED_UUID,
            setlist_entry_payload(
                "Ghost Song", "N. Obody", _AFFILIATION_BMI, "2030-01-01T00:00:00Z", 120
            ),
            admin_headers(),
        ),
        ERR_REPORT_NOT_FOUND,
    )

    validate_error(
        api.settle_audit_case(UNUSED_UUID, settlement_headers()),
        ERR_AUDIT_CASE_NOT_FOUND,
    )
    validate_error(
        api.terminate_license(UNUSED_UUID, terminate_payload(), admin_headers()),
        ERR_LICENSE_NOT_FOUND,
    )

    # None of those refusals touched the rows that do exist.
    assert_version_unchanged(license_row(api, licence["id"]), licence, "licence")
    assert_version_unchanged(venue_row(api, venue["id"]), venue, "venue")
    assessments = assessments_of_venue(api, venue["id"])
    assert len(assessments) == 1, "no refused call may raise a fee assessment"
    assert_assessment(
        assessments[0],
        ASSESSMENT_KIND_INITIAL,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )


def test_access_venue_operator_denied_society_side_writes(api):
    """A venue's own operator is closed out of every society-side write — the
    registries, the survey it is measured by and the licence lifecycle — and its
    identity does not reach another venue's rows either.

    PRD §2.1: "Each endpoint declares the set of roles permitted to invoke it (§4
    lists the authorised roles per endpoint), and a caller whose role is outside
    that set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_venue_operator_cannot_touch_society_side_writes
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    venue = setup["venue"]
    licence = setup["license"]
    society = setup["society"]
    operator = venue_operator_headers(venue["id"])

    validate_error(api.create_society(ascap_payload(), operator), ERR_FORBIDDEN_ROLE)
    validate_error(
        api.create_rate_schedule(
            rate_schedule_payload(
                society["id"], _CATEGORY_BAR_GRILL, "2026-06-01T00:00:00Z"
            ),
            operator,
        ),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.create_venue(bar_grill_venue_payload("Operator Annex"), operator),
        ERR_FORBIDDEN_ROLE,
    )
    # Even its own survey row is the society's to maintain, not the operator's.
    validate_error(
        api.update_venue(venue["id"], {"speaker_count": 3}, operator),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.run_exemption_analysis(venue["id"], operator), ERR_FORBIDDEN_ROLE
    )
    validate_error(
        api.create_repertoire_work(
            repertoire_work_payload(society["id"], "Operator Song", "O. Perator"),
            operator,
        ),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.suspend_license(
            licence["id"], suspend_payload(SUSPENSION_REASON_OPERATOR_REQUEST), operator
        ),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.terminate_license(licence["id"], terminate_payload(), operator),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.create_coverage_window(
            licence["id"],
            coverage_window_payload(
                "2026-12-20T00:00:00Z",
                "2027-01-04T00:00:00Z",
                WINDOW_KIND_SEASONAL_EVENT_RIDER,
            ),
            operator,
        ),
        ERR_FORBIDDEN_ROLE,
    )

    # Not one of those refusals wrote anything.
    read_rows(api.list_societies(admin_headers()), expected_total=1)
    read_rows(api.list_venues(admin_headers()), expected_total=1)
    assert_empty_list(api.list_repertoire_works(admin_headers()))
    assert_version_unchanged(venue_row(api, venue["id"]), venue, "venue")
    assert_version_unchanged(license_row(api, licence["id"]), licence, "licence")

    # A venue operator's identity is its own venue's id, so a neighbouring
    # venue's operator reaches neither this venue's licence nor its money.
    neighbour = given_venue(api, bar_grill_venue_payload("Neighbouring Tap"))
    neighbour_operator = venue_operator_headers(neighbour["id"])
    assessment = assessments_of_venue(api, venue["id"])[0]
    validate_error(
        api.pay_assessment(assessment["id"], payment_payload(1000), neighbour_operator),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        api.get_license(licence["id"], neighbour_operator), ERR_FORBIDDEN_ROLE
    )
    assert_assessment(
        assessment,
        ASSESSMENT_KIND_INITIAL,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )


def test_access_auditor_and_officer_cannot_cross_the_settlement_line(api):
    """The auditing role opens cases and issues findings but never negotiates
    money, and the settlement role negotiates money but never opens a case or
    issues findings; each refusal leaves the case exactly where it was.

    PRD §3.9: "**Negotiation** is a `SettlementOfficer`'s job, and never the
    auditor's — §2.1 gives the segregation rule and §2.12 its position in the
    ladder."

    Design: Corner/rbac/corner_rbac_auditor_and_officer_cannot_cross_the_settlement_line
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    venue = setup["created_venue"]
    society = setup["society"]

    case = given_open_case(api, venue["id"], [society["id"]])
    assert case["status"] == CASE_STATUS_OPEN

    officer = settlement_headers()
    validate_error(
        api.create_audit_case(
            audit_case_payload(
                venue["id"],
                AUDIT_TRIGGER_ROUTINE,
                "2025-01-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                [society["id"]],
            ),
            officer,
        ),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(api.issue_findings(case["id"], officer), ERR_FORBIDDEN_ROLE)
    validate_error(
        api.close_audit_case(
            case["id"], close_case_payload("No exposure identified"), officer
        ),
        ERR_FORBIDDEN_ROLE,
    )
    assert_version_unchanged(case_row(api, case["id"]), case, "audit case")
    read_rows(
        api.list_audit_cases(admin_headers(), {"venue_id": venue["id"]}),
        expected_total=1,
    )

    findings = get_success_data(api.issue_findings(case["id"], auditor_headers()))
    assert findings["status"] == CASE_STATUS_FINDINGS_ISSUED
    floor = findings["settlement_floor_cents"]

    auditor = auditor_headers()
    validate_error(
        api.propose_settlement(case["id"], settlement_offer_payload(floor), auditor),
        ERR_FORBIDDEN_ROLE,
    )
    validate_error(api.settle_audit_case(case["id"], auditor), ERR_FORBIDDEN_ROLE)
    validate_error(api.dispute_settlement(case["id"], auditor), ERR_FORBIDDEN_ROLE)
    # The auditor is equally shut out of the payment path.
    assessment = assessments_of_venue(api, venue["id"])[0]
    validate_error(
        api.pay_assessment(assessment["id"], payment_payload(1000), auditor),
        ERR_FORBIDDEN_ROLE,
    )
    reread = case_row(api, case["id"])
    assert reread["status"] == CASE_STATUS_FINDINGS_ISSUED
    assert_version_unchanged(reread, findings, "audit case")

    # The officer's own operation, on the same case, is accepted.
    proposed = get_success_data(
        api.propose_settlement(case["id"], settlement_offer_payload(floor), officer)
    )
    assert proposed["status"] == CASE_STATUS_SETTLEMENT_PROPOSED
    assert_money(proposed["offered_amount_cents"], floor, "offered_amount_cents")


def test_access_segregation_of_duties_blocks_the_findings_author(api):
    """The human who issued a case's findings may not negotiate that same case,
    even wearing the settlement role; another officer may, on both the offer and
    the acceptance.

    PRD §2.1: "Concretely, when the acting `X-User-ID` on a settlement offer or a
    settlement acceptance equals the `findings_issued_by_user_id` already
    recorded on that `AuditCase`, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), even though the caller's role is
    otherwise correct."

    Design: Corner/rbac/corner_rbac_segregation_of_duties_blocks_the_findings_author
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    venue = setup["created_venue"]
    society = setup["society"]

    case = given_open_case(
        api, venue["id"], [society["id"]], user_id=AUDITOR_USER_ID
    )
    findings = get_success_data(
        api.issue_findings(case["id"], auditor_headers(AUDITOR_USER_ID))
    )
    assert findings["status"] == CASE_STATUS_FINDINGS_ISSUED
    assert findings["findings_issued_by_user_id"] == AUDITOR_USER_ID
    floor = findings["settlement_floor_cents"]

    # The same human, now presenting the settlement role, is still refused.
    validate_error(
        api.propose_settlement(
            case["id"],
            settlement_offer_payload(floor),
            settlement_headers(AUDITOR_USER_ID),
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert_version_unchanged(case_row(api, case["id"]), findings, "audit case")

    # A different officer may make exactly the same offer.
    proposed = get_success_data(
        api.propose_settlement(
            case["id"],
            settlement_offer_payload(floor),
            settlement_headers(SETTLEMENT_USER_ID),
        )
    )
    assert proposed["status"] == CASE_STATUS_SETTLEMENT_PROPOSED
    assert proposed["settlement_proposed_by_user_id"] == SETTLEMENT_USER_ID
    assert_money(proposed["offered_amount_cents"], floor, "offered_amount_cents")

    # Acceptance is guarded by the same comparison as the offer.
    validate_error(
        api.settle_audit_case(case["id"], settlement_headers(AUDITOR_USER_ID)),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert_version_unchanged(case_row(api, case["id"]), proposed, "audit case")

    settled = get_success_data(
        api.settle_audit_case(case["id"], settlement_headers(SETTLEMENT_USER_ID_ALT))
    )
    assert settled["status"] == CASE_STATUS_SETTLED
    assert settled["settled_by_user_id"] == SETTLEMENT_USER_ID_ALT


def test_access_licensing_admin_covers_every_shared_operation(api):
    """The licensing administrator's identity is opaque: it is never compared to
    a venue id, so the same administrator may file, report, pay and dispute
    alongside any operator as well as run the society side.

    PRD §2.1: "When `X-User-Role` is `LicensingAdmin`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity; the server never
    compares it to any row's `id`."

    Design: Corner/rbac/corner_rbac_licensing_admin_covers_every_shared_operation
    """
    setup = given_licensed_venue(api, requested_term_start=CLOCK_START_INSTANT)
    venue = setup["venue"]
    licence = setup["license"]
    society = setup["society"]
    # An identifier that names no venue at all, and is not the identifier the
    # rest of the setup was built with.
    admin_alt = admin_headers(ADMIN_USER_ID_ALT)

    application = get_success_data(
        api.create_application(
            matching_application_payload(
                venue, society["id"], "2027-09-01T00:00:00Z"
            ),
            admin_alt,
        )
    )
    assert application["venue_id"] == venue["id"]
    assert application["status"] == APPLICATION_STATUS_DRAFT

    report = get_success_data(
        api.create_performance_report(
            performance_report_payload(
                licence["id"], CLOCK_START_INSTANT, "2026-09-01T00:00:00Z"
            ),
            admin_alt,
        )
    )
    assert report["status"] == REPORT_STATUS_DRAFT
    assert report["license_id"] == licence["id"]

    entry = get_success_data(
        api.create_setlist_entry(
            report["id"],
            setlist_entry_payload(
                "Admin Anthem", "A. Author", _AFFILIATION_BMI, "2026-08-15T21:00:00Z", 300
            ),
            admin_alt,
        )
    )
    assert entry["performance_report_id"] == report["id"]

    assessment = assessments_of_venue(api, venue["id"])[0]
    paid = get_success_data(
        api.pay_assessment(assessment["id"], payment_payload(1000), admin_alt)
    )
    assert_assessment(
        paid,
        ASSESSMENT_KIND_INITIAL,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=1000,
    )

    case = given_open_case(api, venue["id"], [society["id"]])
    findings = get_success_data(api.issue_findings(case["id"], auditor_headers()))
    get_success_data(
        api.propose_settlement(
            case["id"],
            settlement_offer_payload(findings["settlement_floor_cents"]),
            settlement_headers(),
        )
    )
    disputed = get_success_data(api.dispute_settlement(case["id"], admin_alt))
    assert disputed["status"] == CASE_STATUS_DISPUTED

    # And the society side of the contract remains the administrator's own.
    window = get_success_data(
        api.create_coverage_window(
            licence["id"],
            coverage_window_payload(
                "2026-12-20T00:00:00Z",
                "2027-01-04T00:00:00Z",
                WINDOW_KIND_SEASONAL_EVENT_RIDER,
            ),
            admin_alt,
        )
    )
    assert window["license_id"] == licence["id"]
    assert_count(window["covered_day_count"], 15, "covered_day_count")
