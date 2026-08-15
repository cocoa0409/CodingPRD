"""The decision endpoint: track authority, segregation of duties, documentary
requirements, terminal lockdown, guideline supersession, and precedent lookup
(PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    begin_review,
    create_adopted_guideline_set,
    create_district,
    create_guideline_set,
    create_owner,
    create_property,
    decide_by_staff,
    get_application,
    get_success_data,
    make_staff_headers,
    setup_commission_track_accepted,
    setup_hearing_open,
    setup_hearing_scheduled,
    setup_staff_approved,
    setup_staff_track_accepted,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    verified_item,
    work_item,
)

STAFF = TEST_USERS["staff_headers"]
COMMISSIONER = TEST_USERS["commissioner_headers"]
COUNCIL = TEST_USERS["council_headers"]


def test_staff_decide_on_commission_track_accepted_rejected(api):
    """PRD §3.4: "The cross cases are hard errors: a staff decision on a
    `COMMISSION`-track application still sitting in `ACCEPTED` is rejected with
    `ERR_COMMISSION_HEARING_REQUIRED` — it must be heard first — and a
    `PreservationStaff` attempt to decide a `COMMISSION`-track application in
    `HEARING_OPEN` is rejected with `ERR_STAFF_DECISION_NOT_PERMITTED`, because
    only a commissioner may decide there."

    Design: Corner/endpoints/staff_decide_on_commission_track_rejected
    """
    ctx = setup_commission_track_accepted(verified_cost_cents=1100000)
    response = api.decide_application(
        ctx["application"]["id"], {"outcome": "APPROVE"}, make_staff_headers("staff-2")
    )
    validate_error(response, ApiErrorId.ERR_COMMISSION_HEARING_REQUIRED)
    assert get_application(ctx["application"]["id"])["status"] == "ACCEPTED"


def test_staff_decide_on_open_commission_hearing_forbidden(api):
    """PRD §3.4: "The cross cases are hard errors: a staff decision on a
    `COMMISSION`-track application still sitting in `ACCEPTED` is rejected with
    `ERR_COMMISSION_HEARING_REQUIRED` — it must be heard first — and a
    `PreservationStaff` attempt to decide a `COMMISSION`-track application in
    `HEARING_OPEN` is rejected with `ERR_STAFF_DECISION_NOT_PERMITTED`, because
    only a commissioner may decide there."

    Design: Corner/rbac/staff_decide_on_open_commission_hearing_forbidden
    """
    ctx = setup_hearing_open(verified_cost_cents=1100000)
    response = api.decide_application(
        ctx["application"]["id"], {"outcome": "APPROVE"}, make_staff_headers("staff-2")
    )
    validate_error(response, ApiErrorId.ERR_STAFF_DECISION_NOT_PERMITTED)
    assert get_application(ctx["application"]["id"])["status"] == "HEARING_OPEN"


def test_segregation_of_duties_blocks_accepting_staff_user(api):
    """PRD §3.4: "Segregation of duties adds one more guard on the staff track:
    the staff user whose identifier sits in `completeness_accepted_by` may not
    decide that same application, and their attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_same_staff_cannot_decide
    """
    ctx = setup_staff_track_accepted(staff_id="staff-1")
    app_id = ctx["application"]["id"]

    blocked = api.decide_application(
        app_id, {"outcome": "APPROVE"}, make_staff_headers("staff-1")
    )
    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    decided = validate_success(
        api.decide_application(app_id, {"outcome": "APPROVE"}, make_staff_headers("staff-2"))
    )
    assert decided["status"] == "APPROVED"


def test_council_member_cannot_open_hearing(api):
    """PRD §2.1: "Access to specific operations is further restricted by role,
    per the endpoint authorization lists in §4; an attempt to perform an action
    outside the caller's designated role, or an `Applicant` attempt to act on
    another owner's application or appeal, is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/council_member_cannot_open_hearing
    """
    ctx = setup_hearing_scheduled(verified_cost_cents=1100000)
    response = api.open_hearing(ctx["hearing"]["id"], COUNCIL)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)

    hearing = validate_success(api.get_hearing(ctx["hearing"]["id"], STAFF))
    assert hearing["status"] == "SCHEDULED"


def test_deny_requires_rationale(api):
    """PRD §3.4: "An `outcome` of `DENY` requires a non-empty
    `denial_rationale_sections` array citing the `section_code`s of the pinned
    guideline set that the proposal violates — missing or empty is rejected
    with `ERR_DENIAL_RATIONALE_REQUIRED`."

    Design: Corner/endpoints/deny_requires_rationale
    """
    ctx = setup_staff_track_accepted()
    response = api.decide_application(
        ctx["application"]["id"], {"outcome": "DENY"}, make_staff_headers("staff-2")
    )
    validate_error(response, ApiErrorId.ERR_DENIAL_RATIONALE_REQUIRED)
    assert get_application(ctx["application"]["id"])["status"] == "ACCEPTED"


def test_approve_with_conditions_requires_conditions(api):
    """PRD §3.4: "An `outcome` of `APPROVE_WITH_CONDITIONS` requires a
    non-empty `conditions` array — missing or empty is rejected with
    `ERR_CONDITIONS_REQUIRED` — and records it onto `decision_conditions`."

    Design: Corner/endpoints/approve_with_conditions_requires_conditions
    """
    ctx = setup_staff_track_accepted()
    response = api.decide_application(
        ctx["application"]["id"],
        {"outcome": "APPROVE_WITH_CONDITIONS", "conditions": []},
        make_staff_headers("staff-2"),
    )
    validate_error(response, ApiErrorId.ERR_CONDITIONS_REQUIRED)
    assert get_application(ctx["application"]["id"])["status"] == "ACCEPTED"


def test_decide_on_terminal_application_rejected(api):
    """PRD §2.8: "The target resource must be in a state from which the
    requested transition is declared in §3; otherwise the request is rejected
    with `ERR_INVALID_STATE`."
    PRD §3.4: "For a `STAFF`-track application in `ACCEPTED`, a
    `PreservationStaff` user records the decision by naming an `outcome`."

    Design: Corner/state_machines/decide_on_terminal_application_rejected
    """
    ctx = setup_staff_approved()
    response = api.decide_application(
        ctx["application"]["id"],
        {"outcome": "DENY", "denial_rationale_sections": ["S1"]},
        make_staff_headers("staff-2"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_application(ctx["application"]["id"])["status"] == "APPROVED"


def test_guideline_superseded_blocks_decide_then_ack_repins(api):
    """PRD §3.4: "If, at decision time, the pinned guideline set is no longer
    the district's `ADOPTED` set — a newer set was adopted after acceptance —
    the decision is rejected with `ERR_GUIDELINE_SET_SUPERSEDED` unless the
    payload carries `guideline_override_ack` set to true, an explicit
    acknowledgement that the commission proceeds under superseded guidance."
    PRD §3.4: "When the acknowledgement is present, the application's
    `guideline_set_id` is re-pinned to the district's currently `ADOPTED` set
    as part of the decision."
    PRD §3.3: "The acceptance also pins `guideline_set_id` to the district's
    currently `ADOPTED` guideline set, or to null when the district has no
    adopted set or the property sits outside any district, and records the
    caller in `completeness_accepted_by` — a field that exists solely to
    enforce segregation of duties at decision time in §3.4."

    Design: Corner/cross_cutting_layers/guideline_superseded_blocks_decide_then_ack_repins
    """
    district = create_district(name="Old Town")
    gs1 = create_adopted_guideline_set(district["id"], title="DG-1")
    owner = create_owner()
    prop = create_property(owner["id"], district_id=district["id"])
    submitted = submit_application(
        prop["id"], owner["id"], work_items=[work_item("SITE_WORK", "wall", 200000)]
    )
    begin_review(submitted["id"])
    accepted = accept_application(
        submitted["id"], [verified_item("SITE_WORK", 200000)], "staff-1"
    )
    assert accepted["guideline_set_id"] == gs1["id"], "acceptance pins the ADOPTED set"

    gs2 = create_guideline_set(district["id"], title="DG-2")
    get_success_data(api.adopt_guideline_set(gs2["id"], STAFF))

    blocked = api.decide_application(
        submitted["id"], {"outcome": "APPROVE"}, make_staff_headers("staff-2")
    )
    validate_error(blocked, ApiErrorId.ERR_GUIDELINE_SET_SUPERSEDED)

    decided = validate_success(
        api.decide_application(
            submitted["id"],
            {"outcome": "APPROVE", "guideline_override_ack": True},
            make_staff_headers("staff-2"),
        )
    )
    assert decided["status"] == "APPROVED"
    assert decided["guideline_set_id"] == gs2["id"], (
        "the acknowledgement re-pins to the currently ADOPTED set"
    )


def test_precedent_lookup_filtered_list(api):
    """PRD §3.4: "For precedent research, the application listing supports
    filtering by `property_id`, `owner_id`, `district_id`, `violation_id`,
    `guideline_set_id`, `status`, and `work_category`, so staff and
    commissioners can survey how prior applications in a category or under a
    guideline set were treated."

    Design: Corner/endpoints/precedent_lookup_filtered_list
    """
    district = create_district(name="Old Town")
    owner = create_owner()
    prop = create_property(owner["id"], district_id=district["id"])

    decided_app = submit_application(
        prop["id"], owner["id"], work_items=[work_item("SITE_WORK", "wall A", 200000)]
    )
    begin_review(decided_app["id"])
    accept_application(decided_app["id"], [verified_item("SITE_WORK", 200000)], "staff-1")
    decide_by_staff(decided_app["id"], {"outcome": "APPROVE"}, "staff-2")

    pending_app = submit_application(
        prop["id"], owner["id"], work_items=[work_item("SITE_WORK", "wall B", 210000)]
    )

    data, meta = validate_paginated(
        api.list_applications(
            STAFF,
            params={
                "district_id": district["id"],
                "status": "APPROVED",
                "work_category": "SITE_WORK",
            },
        )
    )
    assert meta["total_count"] == 1
    assert [a["id"] for a in data] == [decided_app["id"]]
    assert pending_app["id"] not in [a["id"] for a in data]
