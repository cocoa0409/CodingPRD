"""Servicer notification lifecycle: dispatch, acknowledgement, scoping."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    advance_clock, create_institution_with_registrars,
    setup_certified_file, list_entry_notifications, enrollment_row,
    make_servicer_headers,
)

OPS = TEST_USERS["ops_headers"]


def _servicer_scene(api):
    """Certified file with one servicer-tracked entry (SVC-100)."""
    ctx = setup_certified_file(rows=[enrollment_row(servicer_ref="SVC-100")])
    ctx["entry_id"] = ctx["entries"][0]["id"]
    ctx["student_id"] = ctx["entries"][0]["student_id"]
    ctx["n1"] = list_entry_notifications(ctx["entry_id"])[0]
    return ctx


def test_notification_dispatched_on_clock_advance(api):
    """PRD section 3.4: "For every `ACCEPTED` entry carrying a
    `servicer_ref`, the system generates a ServicerNotification in `QUEUED`
    status".
    PRD section 3.4: "Notifications travel on the clock: any clock advance
    dispatches every `QUEUED` notification to `SENT` in `created_at`
    ascending order."

    Design: Corner/state_machines/notification_dispatched_on_clock_advance
    """
    ctx = _servicer_scene(api)
    assert ctx["n1"]["status"] == "QUEUED", "generation does not dispatch"
    assert ctx["n1"]["notification_type"] == "DEFERMENT_ELIGIBLE"
    assert ctx["n1"]["grace_end_date"] is None, (
        "a grace date exists only for WITHDRAWN_GRACE"
    )
    advance_clock("2026-11-16T00:00:00Z")
    n1 = validate_success(
        api_client.get_servicer_notification(ctx["n1"]["id"], OPS), 200,
    )
    assert n1["status"] == "SENT"


def test_notification_ack_idempotent_replay_rejected(api):
    """PRD section 3.4: "A `Servicer` acknowledges a `SENT` notification —
    the caller's `X-User-ID` must equal the notification's `servicer_ref`,
    otherwise `ERR_UNAUTHORIZED` — moving it `SENT` → `ACKNOWLEDGED` and
    writing the notification's `notification_type` onto the student's
    `deferment_standing`."
    PRD section 2.9: "an action fired against a resource in the wrong state
    — including re-firing an action whose effect has already been applied,
    or acting on a resource in a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/notification_ack_idempotent_replay_rejected
    """
    ctx = _servicer_scene(api)
    advance_clock("2026-11-16T00:00:00Z")
    acked = validate_success(
        api_client.acknowledge_servicer_notification(
            ctx["n1"]["id"], make_servicer_headers("SVC-100"),
        ),
        200,
    )
    assert acked["status"] == "ACKNOWLEDGED"
    replay = api_client.acknowledge_servicer_notification(
        ctx["n1"]["id"], make_servicer_headers("SVC-100"),
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE)
    student = validate_success(api_client.get_student(ctx["student_id"], OPS), 200)
    assert student["deferment_standing"] == "DEFERMENT_ELIGIBLE", (
        "the first ack's write stands; the replay changes nothing"
    )


def test_rbac_servicer_wrong_ref_cannot_ack(api):
    """PRD section 3.4: "the caller's `X-User-ID` must equal the
    notification's `servicer_ref`, otherwise `ERR_UNAUTHORIZED`".

    Design: Corner/rbac/rbac_servicer_wrong_ref_cannot_ack
    """
    ctx = _servicer_scene(api)
    advance_clock("2026-11-16T00:00:00Z")
    resp = api_client.acknowledge_servicer_notification(
        ctx["n1"]["id"], make_servicer_headers("SVC-999"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    n1 = validate_success(
        api_client.get_servicer_notification(ctx["n1"]["id"], OPS), 200,
    )
    assert n1["status"] == "SENT"


def test_rbac_servicer_list_scoped_to_own_ref(api):
    """PRD section 2.1: "a servicer sees and acknowledges exactly the
    notifications addressed to its code, and no others."
    PRD section 3.4: "a Servicer caller sees only its own `servicer_ref`."

    Design: Corner/rbac/rbac_servicer_list_scoped_to_own_ref
    """
    ctx = setup_certified_file(rows=[
        enrollment_row(student_ref="S1", full_name="Ada Lovelace",
                       servicer_ref="SVC-100"),
        enrollment_row(student_ref="S2", full_name="Bob Student",
                       date_of_birth="2004-07-01", servicer_ref="SVC-200"),
    ])
    own, meta_own = validate_paginated(
        api_client.list_servicer_notifications(make_servicer_headers("SVC-100")),
    )
    assert meta_own["total_count"] == 1
    assert own[0]["servicer_ref"] == "SVC-100"
    _all, meta_all = validate_paginated(
        api_client.list_servicer_notifications(OPS),
    )
    assert meta_all["total_count"] == 2


def test_err_notification_not_found(api):
    """PRD section 2.8: "Each kind of unresolved reference reports its own
    error — `ERR_INSTITUTION_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_DEGREE_NOT_FOUND`, `ERR_REQUESTER_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, or
    `ERR_DATASET_NOT_FOUND`, each HTTP 404".

    Design: Corner/errors/err_notification_not_found
    """
    create_institution_with_registrars()
    resp = api_client.acknowledge_servicer_notification(
        NON_EXISTENT_UUID, make_servicer_headers("SVC-100"),
    )
    validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_FOUND)
