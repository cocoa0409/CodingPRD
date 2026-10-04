"""Class listings: content review, publishing, and the section lifecycle gates."""
from test_helpers import (
    ApiErrorId,
    create_listing,
    create_section,
    get_listing,
    get_section,
    get_success_data,
    make_platform_admin_headers,
    make_teacher_headers,
    onboard_active_teacher,
    policy_approve_listing,
    publish_listing,
    setup_listing,
    validate_error,
    validate_paginated,
)


def test_section_open_blocked_until_listing_is_published(api):
    """PRD §3.4: "Opening a section for business requires three conditions to hold
    together: the section is `SCHEDULED`, its owning teacher is `ACTIVE` (otherwise
    `ERR_TEACHER_NOT_ACTIVE`, 409), and its listing is both `PUBLISHED` (otherwise
    `ERR_LISTING_NOT_PUBLISHED`, 409) and `POLICY_APPROVED`."
    PRD §3.3: "A listing that has not been published cannot have its sections opened."

    Design: Difficulty/cross_entity_state_dependency/section_open_depends_on_listing_lifecycle_state
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, approve=True, publish=False)
    assert listing["content_review_state"] == "POLICY_APPROVED"
    assert listing["lifecycle_state"] == "DRAFT"

    section = create_section(listing, teacher, open_for_enrollment=False)
    assert section["status"] == "SCHEDULED"

    blocked = api.open_section(listing["id"], section["id"], make_teacher_headers(teacher["id"]))
    validate_error(blocked, ApiErrorId.ERR_LISTING_NOT_PUBLISHED)

    published = publish_listing(listing["id"], teacher["id"])
    assert published["lifecycle_state"] == "PUBLISHED"

    opened = get_success_data(
        api.open_section(listing["id"], section["id"], make_teacher_headers(teacher["id"]))
    )
    assert opened["status"] == "OPEN_FOR_ENROLLMENT", (
        "the identical open request succeeded only after the parent listing moved to PUBLISHED"
    )


def test_failed_section_open_leaves_the_section_untouched(api):
    """PRD §3.4: "Opening a section for business requires three conditions to hold
    together: the section is `SCHEDULED`, its owning teacher is `ACTIVE` (otherwise
    `ERR_TEACHER_NOT_ACTIVE`, 409), and its listing is both `PUBLISHED` (otherwise
    `ERR_LISTING_NOT_PUBLISHED`, 409) and `POLICY_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/section_open_depends_on_listing_lifecycle_state
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, approve=True, publish=False)
    section = create_section(listing, teacher, open_for_enrollment=False)

    blocked = api.open_section(listing["id"], section["id"], make_teacher_headers(teacher["id"]))
    validate_error(blocked, ApiErrorId.ERR_LISTING_NOT_PUBLISHED)

    still_scheduled = get_section(listing["id"], section["id"])
    assert still_scheduled["status"] == "SCHEDULED", "a rejected open must not move the section"

    publish_listing(listing["id"], teacher["id"])
    opened = get_success_data(
        api.open_section(listing["id"], section["id"], make_teacher_headers(teacher["id"]))
    )
    assert opened["status"] == "OPEN_FOR_ENROLLMENT"
    assert get_listing(listing["id"])["lifecycle_state"] == "PUBLISHED"


def test_new_section_starts_in_scheduled_state(api):
    """PRD §3.4: "A new section is born `SCHEDULED` with a null `outcome`, and its
    `cancellation_cutoff_utc` is fixed at `start_utc` minus 24 hours, the instant at
    which the automatic-cancellation sweep will judge it."

    Design: Corner/state_machines/new_section_starts_in_scheduled_state
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)

    section = create_section(
        listing, teacher, open_for_enrollment=False,
        start_utc="2026-11-05T14:00:00Z", end_utc="2026-11-05T16:00:00Z",
        min_learners=2, capacity=5,
    )
    assert section["status"] == "SCHEDULED"
    assert section["outcome"] is None
    assert section["enrolled_count"] == 0
    assert section["reserved_count"] == 0
    assert section["seats_remaining"] == 5
    assert section["enrollment_min_met"] is False
    assert section["cancellation_cutoff_utc"] == "2026-11-04T14:00:00.000Z", (
        "the cutoff is the start instant minus 24 hours"
    )


def test_cancel_already_cancelled_section_returns_invalid_state(api):
    """PRD §3.4: "Cancellation by the teacher is available from `SCHEDULED`,
    `OPEN_FOR_ENROLLMENT` or `MIN_ENROLLMENT_MET`, and only while the current instant
    is strictly before `start_utc`; the owning teacher must be `ACTIVE` unless a
    `PlatformAdmin` is acting."
    PRD §3.4: "An `outcome`, once non-null, is sealed: no later behaviour rewrites it."

    Design: Corner/state_machines/cancel_already_cancelled_section_returns_invalid_state
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher)
    section = create_section(listing, teacher)

    cancelled = get_success_data(
        api.cancel_section(listing["id"], section["id"], make_teacher_headers(teacher["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["outcome"] == "CANCELLED_BY_TEACHER"

    second = api.cancel_section(listing["id"], section["id"], make_teacher_headers(teacher["id"]))
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    fresh = get_section(listing["id"], section["id"])
    assert fresh["status"] == "CANCELLED"
    assert fresh["outcome"] == "CANCELLED_BY_TEACHER", "the sealed outcome was not rewritten"


def test_publish_before_policy_approval_returns_invalid_state(api):
    """PRD §3.3: "Publishing is the teacher's act. It moves a listing from `DRAFT` to
    `PUBLISHED`, and it requires three things at once: the listing must already be
    `POLICY_APPROVED`, the owning teacher must be `ACTIVE` (otherwise
    `ERR_TEACHER_NOT_ACTIVE`, 409), and the acting principal must either be the owning
    teacher or a `PlatformAdmin`."
    PRD §2.6: "The target resource is in a state from which the requested transition is
    declared. Any failure here is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/endpoints/publish_before_policy_approval_returns_invalid_state
    """
    teacher = onboard_active_teacher()
    listing = create_listing(teacher)
    assert listing["content_review_state"] == "PENDING_REVIEW"
    assert listing["lifecycle_state"] == "DRAFT"

    response = api.publish_listing(listing["id"], make_teacher_headers(teacher["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    fresh = get_listing(listing["id"])
    assert fresh["content_review_state"] == "PENDING_REVIEW"
    assert fresh["lifecycle_state"] == "DRAFT", "the rejected publish left the listing in DRAFT"


def test_section_creation_on_unapproved_listing_rejected(api):
    """PRD §3.3: "`content_review_state` is the sole gate on scheduling: a section
    cannot be created under a listing that is not `POLICY_APPROVED`, and the attempt is
    refused with `ERR_LISTING_NOT_APPROVED` (409)."

    Design: Corner/endpoints/section_creation_on_unapproved_listing_rejected
    """
    teacher = onboard_active_teacher()
    listing = create_listing(teacher)
    assert listing["content_review_state"] == "PENDING_REVIEW"

    blocked = api.create_section(
        listing["id"],
        {
            "timezone": "America/New_York",
            "start_utc": "2026-11-05T14:00:00Z",
            "end_utc": "2026-11-05T16:00:00Z",
            "min_learners": 1,
            "capacity": 6,
        },
        make_teacher_headers(teacher["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_LISTING_NOT_APPROVED)

    approved = policy_approve_listing(listing["id"])
    assert approved["content_review_state"] == "POLICY_APPROVED"

    section = get_success_data(
        api.create_section(
            listing["id"],
            {
                "timezone": "America/New_York",
                "start_utc": "2026-11-05T14:00:00Z",
                "end_utc": "2026-11-05T16:00:00Z",
                "min_learners": 1,
                "capacity": 6,
            },
            make_teacher_headers(teacher["id"]),
        )
    )
    assert section["status"] == "SCHEDULED", (
        "the identical request succeeded only after the listing was approved"
    )


def test_listing_list_pagination_reports_total_and_has_more(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the standard envelope. `total_count` is the
    number of resources matching the request's filters before paging is applied, and
    `has_more` is true when further items remain beyond the returned page."

    Design: Corner/endpoints/listing_list_pagination_reports_total_and_has_more
    """
    teacher = onboard_active_teacher()
    first = create_listing(teacher, title="Algebra Club")
    second = create_listing(teacher, title="Geometry Club", format="MULTI_DAY", min_age=9, max_age=13, list_price_cents=3000)

    first_page = api.list_class_listings(make_platform_admin_headers(), params={"limit": 1})
    data, meta = validate_paginated(first_page)
    assert len(data) == 1, "limit 1 returns exactly one element"
    assert meta["total_count"] == 2, "total_count counts matches before paging"
    assert meta["has_more"] is True, "a second page remains"
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    second_page = api.list_class_listings(make_platform_admin_headers(), params={"limit": 1, "offset": 1})
    data2, meta2 = validate_paginated(second_page)
    assert len(data2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False, "the second page exhausts the collection"

    titles = {data[0]["title"], data2[0]["title"]}
    assert titles == {"Algebra Club", "Geometry Club"}, "paging walks the whole collection"
    assert {first["id"], second["id"]} == {data[0]["id"], data2[0]["id"]}


def test_teacher_cannot_publish_another_teachers_listing(api):
    """PRD §2.1: "Ownership is enforced separately from role membership. A request that
    names a resource belonging to somebody else is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403): an acting `Teacher` must own the listing, section or payout being
    mutated, and an acting `Parent` must own the learner whose enrollment is being
    mutated."

    Design: Corner/rbac/teacher_cannot_publish_another_teachers_listing
    """
    ada = onboard_active_teacher()
    listing = setup_listing(ada, approve=True, publish=False)

    grace = onboard_active_teacher(
        applicant_user_id="u_grace",
        email="grace@example.com",
        display_name="Grace Hopper",
        reviewer_user_id="rev_2",
    )
    assert grace["status"] == "ACTIVE"

    response = api.publish_listing(listing["id"], make_teacher_headers(grace["id"]))
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    fresh = get_listing(listing["id"])
    assert fresh["teacher_id"] == ada["id"]
    assert fresh["lifecycle_state"] == "DRAFT", "the foreign publish changed nothing"
