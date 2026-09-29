"""Who may act, and on whose rows.

The first test walks the exclusive operations of all four roles and the three ways a request
can fail to authenticate at all; the second and third hold two peers of the same role apart,
once for growers and once for verification bodies.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_RESOURCE_NOT_OWNED,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import assert_pct, assert_tonnes, assert_visit_day
from test_helpers.constants import (
    CROP_YEAR_2026,
    ENROLLMENT_DRAFT,
    ENROLLMENT_SCREENING,
    METHOD_MODEL,
    OPINION_ADVERSE,
    OPINION_PENDING,
    OPINION_POSITIVE,
    RUN_VERIFIED,
    UNKNOWN_UUIDS,
)
from test_helpers.factories import (
    field_payload,
    enrollment_payload,
    grower_payload,
    issue_payload,
    opinion_payload,
    qc_payload,
    quantification_run_payload,
    registry_listing_payload,
    retirement_payload,
    screen_payload,
    verification_body_payload,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ADMIN_SCREENER_ID,
    NO_HEADERS,
    REGISTRY_HEADERS,
    grower_headers,
    headers_blank_role,
    headers_unknown_role,
    verifier_headers,
)


def test_no_role_holds_another_roles_operations_and_bad_headers_answer_first(scenario):
    """Each role is refused the operations reserved to the others, the refusal arrives even
    when the addressed row does not exist, and a missing, blank or unrecognised role header is
    answered one rung earlier still.

    PRD §2.10: "The acting role appears in the called endpoint's authorized-role list →
    otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    PRD §2.10: "`X-User-Role` and `X-User-ID` are both present and non-empty, and
    `X-User-Role` is one of the four declared roles → otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/role_gates_refuse_other_roles_exclusive_operations_and_missing_headers
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field()
    scenario.file_reference_history()
    scenario.create_enrollment()
    scenario.accredit_body()
    enrollment_id = scenario.enrollment_id
    observed = scenario.enrollment_version
    grower_auth = scenario.grower_auth
    verifier_auth = scenario.verifier_auth

    # A grower holds none of the three administrative operations, nor the reconciliation read.
    validate_error(
        scenario.api.screen_enrollment(enrollment_id, screen_payload("ACCEPT"), grower_auth),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        scenario.api.qc_data_packet(
            UNKNOWN_UUIDS["data_packet"], qc_payload("PASS"), grower_auth
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        scenario.api.issue_credits(
            UNKNOWN_UUIDS["quantification_run"], issue_payload(CROP_YEAR_2026), grower_auth
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        scenario.api.get_grower_ledger_summary(scenario.grower_id, grower_auth),
        ERR_UNAUTHORIZED,
        403,
    )

    # A verifier neither quantifies nor keeps the registry.
    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                enrollment_id, UNKNOWN_UUIDS["baseline"], observed, CROP_YEAR_2026,
                METHOD_MODEL,
            ),
            verifier_auth,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        scenario.api.list_batch_on_registry(
            UNKNOWN_UUIDS["credit_batch"],
            registry_listing_payload(registry_account_ref="REG-ACCT-X"),
            verifier_auth,
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    # A registry officer neither opines nor onboards growers.
    validate_error(
        scenario.api.opine_verification(
            UNKNOWN_UUIDS["verification"], opinion_payload(OPINION_POSITIVE), REGISTRY_HEADERS
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        scenario.api.create_grower(grower_payload(), REGISTRY_HEADERS),
        ERR_UNAUTHORIZED,
        403,
    )

    # And the programme administrator holds neither the opinion nor registry custody.
    validate_error(
        scenario.api.opine_verification(
            UNKNOWN_UUIDS["verification"], opinion_payload(OPINION_POSITIVE), ADMIN_HEADERS
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        scenario.api.retire_batch(
            UNKNOWN_UUIDS["credit_batch"],
            retirement_payload(retirement_beneficiary="Northwind Airlines"),
            ADMIN_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    # The authentication rung answers before the authorization rung on the same path.
    validate_error(
        scenario.api.screen_enrollment(enrollment_id, screen_payload("ACCEPT"), NO_HEADERS),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        scenario.api.screen_enrollment(
            enrollment_id, screen_payload("ACCEPT"), headers_blank_role(ADMIN_SCREENER_ID)
        ),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        scenario.api.screen_enrollment(
            enrollment_id, screen_payload("ACCEPT"),
            headers_unknown_role(ADMIN_SCREENER_ID, "Auditor"),
        ),
        ERR_UNAUTHENTICATED,
        401,
    )

    untouched = scenario.reload_enrollment(enrollment_id)
    assert untouched["status"] == ENROLLMENT_DRAFT
    assert untouched["version"] == observed


def test_one_grower_cannot_read_write_or_extend_another_growers_rows(scenario):
    """A peer grower is refused a write, a read and a field registration on the first grower's
    rows, while the very same submit succeeds for the owner and for the administrator, and the
    peer's own filtered list never shows the neighbour.

    PRD §2.10: "A `Grower` caller owns the addressed resource; a `Verifier` caller is the body
    assigned to the addressed verification → otherwise `ERR_RESOURCE_NOT_OWNED` (403). Applies
    to every endpoint reachable by `Grower` or `Verifier`."

    Design: Corner/rbac/growers_are_isolated_from_each_others_resources_while_shared_operations_work_for_both
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field()
    scenario.file_reference_history()
    scenario.create_enrollment()
    grower_one = scenario.grower_id
    enrollment_one = scenario.enrollment_id
    owner_auth = scenario.grower_auth

    peer = get_success_data(scenario.api.create_grower(grower_payload(), ADMIN_HEADERS))
    peer_auth = grower_headers(peer["id"])
    peer_field = get_success_data(
        scenario.api.create_field(
            peer["id"],
            field_payload(
                field_name="Peer Home Section", boundary_min_x=8000, boundary_min_y=0,
                boundary_max_x=10000, boundary_max_y=2000,
            ),
            ADMIN_HEADERS,
        )
    )
    scenario.map_confirm(peer_field["id"])
    scenario.file_reference_history(peer_field["id"])
    enrollment_two = get_success_data(
        scenario.api.create_enrollment(
            enrollment_payload(peer_field["id"], scenario.standard_id), ADMIN_HEADERS
        )
    )["id"]

    validate_error(
        scenario.api.submit_enrollment(enrollment_one, None, peer_auth),
        ERR_RESOURCE_NOT_OWNED,
        403,
    )
    assert scenario.reload_enrollment(enrollment_one)["status"] == ENROLLMENT_DRAFT

    # Ownership gates reads exactly as it gates writes.
    validate_error(
        scenario.api.get_enrollment(enrollment_one, peer_auth),
        ERR_RESOURCE_NOT_OWNED,
        403,
    )

    validate_error(
        scenario.api.create_field(
            grower_one,
            field_payload(
                field_name="Peer 1 Extra", boundary_min_x=6000, boundary_min_y=0,
                boundary_max_x=7000, boundary_max_y=1000,
            ),
            peer_auth,
        ),
        ERR_RESOURCE_NOT_OWNED,
        403,
    )
    owner_fields, owner_meta = validate_paginated(
        scenario.api.list_fields({"grower_id": grower_one}, ADMIN_HEADERS)
    )
    assert owner_meta["total_count"] == 1
    assert owner_fields[0]["id"] == scenario.field_id

    # The shared operation works for both principal classes.
    submitted_by_owner = validate_success(
        scenario.api.submit_enrollment(enrollment_one, None, owner_auth), 200
    )
    assert submitted_by_owner["status"] == ENROLLMENT_SCREENING
    submitted_by_admin = validate_success(
        scenario.api.submit_enrollment(enrollment_two, None, ADMIN_HEADERS), 200
    )
    assert submitted_by_admin["status"] == ENROLLMENT_SCREENING

    assert get_success_data(
        scenario.api.get_enrollment(enrollment_one, ADMIN_HEADERS)
    )["id"] == enrollment_one

    peer_rows, peer_meta = validate_paginated(
        scenario.api.list_enrollments({"grower_id": peer["id"]}, peer_auth)
    )
    assert peer_meta["total_count"] == 1
    assert peer_rows[0]["id"] == enrollment_two


def test_an_accredited_peer_body_cannot_touch_another_bodys_assignment(scenario):
    """A second body accredited for the very same practice is refused both the opinion and the
    arrival record on an assignment it does not hold, and the assigned body's identical call
    carries the run through to verified.

    PRD §3.6: "Acting as a `Verifier` requires that `X-User-ID` equal the
    `verification_body_id` recorded on the addressed verification."

    Design: Corner/rbac/a_verification_body_cannot_opine_on_another_bodys_assignment
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    scenario.create_run(METHOD_MODEL)
    scenario.submit_run()
    scenario.accredit_body()
    assigned = scenario.commission_verification(
        site_visit_start="2026-07-01", site_visit_end="2026-07-03"
    )
    peer_body = get_success_data(
        scenario.api.create_verification_body(verification_body_payload(), ADMIN_HEADERS)
    )
    peer_auth = verifier_headers(peer_body["id"])

    validate_error(
        scenario.api.opine_verification(
            assigned["id"],
            opinion_payload(OPINION_ADVERSE, findings_note="hostile takeover attempt"),
            peer_auth,
        ),
        ERR_RESOURCE_NOT_OWNED,
        403,
    )
    assert get_success_data(
        scenario.api.get_verification(assigned["id"], ADMIN_HEADERS)
    )["opinion"] == OPINION_PENDING

    validate_error(
        scenario.api.start_visit(assigned["id"], None, peer_auth),
        ERR_RESOURCE_NOT_OWNED,
        403,
    )
    unmoved = get_success_data(
        scenario.api.get_verification(assigned["id"], ADMIN_HEADERS)
    )
    assert_visit_day(unmoved["site_visit_start"], "2026-07-01")

    opined = validate_success(
        scenario.api.opine_verification(
            assigned["id"], opinion_payload(OPINION_POSITIVE), scenario.verifier_auth
        ),
        200,
    )
    assert opined["opinion"] == OPINION_POSITIVE
    assert_pct(opined["material_discrepancy_pct"], 0.00)

    run = scenario.reload_run()
    assert run["status"] == RUN_VERIFIED
    assert_tonnes(run["net_removals_t"], 283.360)
