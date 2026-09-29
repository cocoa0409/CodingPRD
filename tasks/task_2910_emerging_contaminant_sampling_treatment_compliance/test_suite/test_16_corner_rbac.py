"""Who may act, who may only read, and who may not attest to their own work.

Authorisation here has three distinct layers: the endpoint's role list, the
universal read grant that cuts across every role, and one duty segregated by
operator identity rather than by role at all. Each test drives one of the three
without leaning on the others.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DETERMINATION_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_LABORATORY_NOT_OWNED,
    ERR_PROJECT_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_equals,
    assert_instant_equals,
    assert_is_null,
    assert_status,
    assert_total_count,
    first_row,
)
from test_helpers.fixtures import (
    build_registry,
    collect_sample,
    issued_violation,
    read_notification,
    read_sample,
    register_entry_point,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    OFFICER_2_USER_ID,
    OFFICER_USER_ID,
    SAMPLING_TECHNICIAN_HEADERS,
    STATE_REGULATOR_HEADERS,
    TREATMENT_ENGINEER_HEADERS,
    UTILITY_ADMIN_HEADERS,
    make_laboratory_manager_headers,
)


def test_no_role_can_perform_another_roles_exclusive_operation(api):
    """Seven crossed attempts, one code, and two of them never touch the database.

    An officer cannot extend the registry, an administrator cannot collect a
    sample, an officer cannot report an analytical result, a technician cannot
    invalidate one, a finance officer cannot open a treatment study, an engineer
    cannot adjust project costs and an officer cannot rescind a determination. Two
    of the seven address identifiers that resolve to nothing at all, and because the
    role gate sits above the path-existence family they must still be refused as
    forbidden rather than reported as missing — an implementation that loads the row
    before checking the role leaks which identifiers exist. The lab-result attempt
    is the sharpest of the seven: the officer's identifier is no laboratory either,
    yet the role gate outranks the ownership gate. Nothing is created by any of
    them.

    PRD: "Each endpoint declares the roles permitted to invoke it; a recognised role
    calling an endpoint outside its permission set is refused with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/no_role_can_perform_another_roles_exclusive_operation
    """
    registry = build_registry(api)
    sample = collect_sample(
        api, registry["entry_point_id"], [registry["contaminant_id"]], preservative_lot="LOT-A1"
    )

    validate_error(
        api.create_contaminant(
            f.contaminant_payload(code="PFOS"), COMPLIANCE_OFFICER_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_sample(
            f.sample_payload(
                registry["entry_point_id"],
                [registry["contaminant_id"]],
                collected_at="2026-05-16T08:00:00.000Z",
                protocol="COMPOSITE",
                preservative_lot="LOT-A2",
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    lab_attempt = api.create_lab_result(
        f.lab_result_payload(sample["id"], registry["contaminant_id"]),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(lab_attempt, ERR_FORBIDDEN_ROLE, 403)
    assert lab_attempt.json()["data"]["error_id"] != ERR_LABORATORY_NOT_OWNED, (
        "the role gate outranks the laboratory-ownership gate"
    )

    validate_error(
        api.invalidate_sample(
            sample["id"], f.invalidate_sample_payload(), SAMPLING_TECHNICIAN_HEADERS
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.create_treatment_evaluation(
            f.treatment_evaluation_payload(
                registry["entry_point_id"], residuals_budget_cents=500000
            ),
            FINANCE_OFFICER_HEADERS,
        ),
        ERR_FORBIDDEN_ROLE,
        403,
    )

    patch_attempt = api.patch_capital_project(
        NON_EXISTENT_UUID,
        f.project_patch_payload(capital_cost_cents=1000),
        TREATMENT_ENGINEER_HEADERS,
    )
    validate_error(patch_attempt, ERR_FORBIDDEN_ROLE, 403)
    assert patch_attempt.json()["data"]["error_id"] != ERR_PROJECT_NOT_FOUND, (
        "the role gate must not disclose whether the project exists"
    )

    rescind_attempt = api.rescind_determination(
        NON_EXISTENT_UUID,
        f.rescind_payload(rescind_reason="Attempted by the wrong role"),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(rescind_attempt, ERR_FORBIDDEN_ROLE, 403)
    assert rescind_attempt.json()["data"]["error_id"] != ERR_DETERMINATION_NOT_FOUND, (
        "the role gate must not disclose whether the determination exists"
    )

    assert_total_count(api.list_samples(COMPLIANCE_OFFICER_HEADERS), 1)
    assert_status(read_sample(api, sample["id"]), "COLLECTED")
    assert_total_count(api.list_treatment_evaluations(COMPLIANCE_OFFICER_HEADERS), 0)


def test_all_seven_roles_share_the_read_surface_and_the_clock(api):
    """The registry is readable from every seat, and anyone may move the clock.

    The same entry-point list is requested once per role, including the laboratory
    manager whose identifier scoping governs samples and results but never the
    registry, and all seven see the one row. The logical clock is likewise open to
    every role, so a sampling technician may move it to the second of August and
    receives the instant it stored back; the move is a harness affordance and
    disturbs no business row, which the eighth read confirms.

    PRD: "Read access is deliberately universal — all seven roles may retrieve any
    resource and run any list query — while every write is restricted to the role
    that owns the act."

    Design: Corner/rbac/all_seven_roles_share_the_read_surface_and_the_clock
    """
    entry_point = register_entry_point(api)
    readers = [
        UTILITY_ADMIN_HEADERS,
        SAMPLING_TECHNICIAN_HEADERS,
        make_laboratory_manager_headers("some-laboratory-user"),
        COMPLIANCE_OFFICER_HEADERS,
        TREATMENT_ENGINEER_HEADERS,
        FINANCE_OFFICER_HEADERS,
        STATE_REGULATOR_HEADERS,
    ]

    for headers in readers:
        listed = api.list_entry_points(headers)
        assert listed.status_code == 200, (
            f"{headers} was refused the shared read surface with {listed.status_code}"
        )
        assert_total_count(listed, 1)
        assert_equals(first_row(listed), "id", entry_point["id"])

    moved = validate_success(
        api.set_clock(
            f.clock_payload("2026-08-02T00:00:00.000Z"), SAMPLING_TECHNICIAN_HEADERS
        )
    )
    assert_instant_equals(
        moved["current_utc"], "2026-08-02T00:00:00.000Z", label="current_utc"
    )

    after = api.list_entry_points(UTILITY_ADMIN_HEADERS)
    assert_total_count(after, 1)
    assert_equals(first_row(after), "id", entry_point["id"])


def test_the_officer_who_drafted_a_notification_cannot_certify_its_distribution(api):
    """Same role, different identifier: the guard is the operator, not the seat.

    Officer one drafts and submits the tier-two notice and the regulator approves
    it, so the only thing standing between officer one and a certified distribution
    is the identifier stored at submit time. The self-certification is refused, and
    the refusal stores nothing — the notice is still approved, with no certifying
    officer, no distribution instant and no evidence reference. Officer two, holding
    the very same role, sends the identical request through, and the evidence
    reference that lands on the row is the second one, never the first.

    PRD: "A `ComplianceOfficer` certifies with a mandatory `delivery_evidence_ref`,
    and the certifying officer's `X-User-ID` must differ from the notification's
    `drafted_by_user_id`; the person who wrote the notice may not attest that it was
    delivered, and a self-certification is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_officer_who_drafted_a_notification_cannot_certify_its_distribution
    """
    registry = build_registry(api)
    violation = issued_violation(api, registry, reported_ng_per_l=4.50)
    notification_id = violation["notification"]["id"]

    submitted = validate_success(
        api.submit_notification(
            notification_id, f.notification_submit_payload(), COMPLIANCE_OFFICER_HEADERS
        )
    )
    assert_equals(submitted, "drafted_by_user_id", OFFICER_USER_ID)
    approved = validate_success(
        api.review_notification(
            notification_id,
            f.notification_review_payload(approve=True, review_note="Approved for distribution"),
            STATE_REGULATOR_HEADERS,
        )
    )
    assert_status(approved, "APPROVED")

    validate_error(
        api.certify_notification_distribution(
            notification_id,
            f.certify_distribution_payload(delivery_evidence_ref="MAILING-SELF-CERTIFIED"),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    refused = read_notification(api, notification_id)
    assert_status(refused, "APPROVED")
    assert_is_null(
        refused, "certified_by_user_id", "distributed_at", "delivery_evidence_ref"
    )

    distributed = validate_success(
        api.certify_notification_distribution(
            notification_id,
            f.certify_distribution_payload(delivery_evidence_ref="MAILING-2026-0801"),
            COMPLIANCE_OFFICER_2_HEADERS,
        )
    )
    assert_status(distributed, "DISTRIBUTED")
    assert_equals(distributed, "certified_by_user_id", OFFICER_2_USER_ID)
    assert_equals(distributed, "late_by_hours", 0)
    assert_equals(distributed, "delivery_evidence_ref", "MAILING-2026-0801")
