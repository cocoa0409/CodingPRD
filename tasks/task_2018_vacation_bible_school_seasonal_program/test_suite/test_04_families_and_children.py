"""Family intake, soft delete, archive cascade, and child creation gates
(PRD §3.2)."""
import re

from test_helpers import (
    ApiErrorId,
    archive_family,
    assert_instant_equals,
    create_child,
    create_child_payload,
    create_family,
    create_family_payload,
    get_classroom,
    get_registration,
    register_child,
    setup_family_with_children,
    setup_open_program_with_classroom,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_parent_headers

_REGCOORD = TEST_USERS["registration_coordinator_headers"]
_THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class TestFamilyCreation:
    def test_family_creation_applies_defaults(self, api):
        """PRD §3.2: households supply "`household_name`,
        `primary_contact_name`, `email`, `phone`, and optionally
        `preferred_contact` — one of `EMAIL`, `PHONE`, or `TEXT`, defaulting to
        `EMAIL`" and "The family is born `ACTIVE`." PRD §2.5: "`created_at`, an
        ISO 8601 UTC timestamp with three fractional digits assigned at
        creation" and "`version`, an integer that starts at 1 when the resource
        is created".

        Design: Corner/entities/family_creation_applies_defaults
        """
        family = create_family()
        assert family["preferred_contact"] == "EMAIL", "default applied"
        assert family["status"] == "ACTIVE"
        assert family["version"] == 1
        assert _THREE_FRACTIONAL_DIGITS.match(family["created_at"]), (
            f"created_at must carry three fractional digits: {family['created_at']!r}"
        )

    def test_duplicate_family_email_rejected(self, api, anonymous_headers):
        """PRD §3.2: "The `email` must be unique across all families including
        `ARCHIVED` ones, or creation fails with `ERR_DUPLICATE_EMAIL`."

        Design: Corner/validations/duplicate_family_email_rejected
        """
        create_family(email="alvarez@example.com")
        resp = api.create_family(
            create_family_payload(email="alvarez@example.com"), anonymous_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL, 409)


class TestArchivedFamily:
    def test_family_archived_blocks_child_create(self, api):
        """PRD §3.2: "The family must be `ACTIVE`: creating a child, and
        likewise creating a registration, against an archived family fails with
        `ERR_FAMILY_ARCHIVED`."

        Design: Corner/validations/family_archived_blocks_child_create
        """
        family = create_family()
        archive_family(family["id"])
        # A RegistrationCoordinator may act on any family; the referential
        # gate (priority 9) is what must fire here.
        resp = api.create_child(create_child_payload(family["id"]), _REGCOORD)
        validate_error(resp, ApiErrorId.ERR_FAMILY_ARCHIVED, 409)

    def test_soft_delete_family_list_filter(self, api):
        """PRD §3.2: "Family lists exclude archived households unless the
        caller passes `include_archived` true"; archiving is a soft delete —
        "A `RegistrationCoordinator` soft-deletes a family by archiving it" —
        so the row itself remains addressable.

        Design: Corner/cross_cutting_layers/soft_delete_family_list_filter
        """
        family_1 = create_family(household_name="F1")
        family_2 = create_family(household_name="F2")
        archive_family(family_1["id"])

        data_default, meta_default = validate_paginated(api.list_families(_REGCOORD))
        assert meta_default["total_count"] == 1
        assert [f["id"] for f in data_default] == [family_2["id"]]

        data_all, meta_all = validate_paginated(
            api.list_families(_REGCOORD, params={"include_archived": "true"})
        )
        assert meta_all["total_count"] == 2
        assert {f["id"] for f in data_all} == {family_1["id"], family_2["id"]}

        direct = validate_success(api.get_family(family_1["id"], _REGCOORD))
        assert direct["status"] == "ARCHIVED", (
            "direct GET still resolves the soft-deleted row"
        )


class TestArchiveCascade:
    def _setup_two_family_queue(self):
        """capacity 1: family F1's child A ENROLLED; family F2's child B
        WAITLISTED at position 1. Logical clock at its default."""
        program, classroom = setup_open_program_with_classroom(capacity=1)
        family_1, children_1 = setup_family_with_children(count=1)
        family_2, children_2 = setup_family_with_children(count=1)
        reg_a = register_child(children_1[0]["id"], classroom["id"], family_1["id"])
        reg_b = register_child(children_2[0]["id"], classroom["id"], family_2["id"])
        assert reg_a["status"] == "ENROLLED"
        assert reg_b["status"] == "WAITLISTED"
        return classroom, family_1, reg_a, reg_b

    def test_archive_cancels_enrollee_as_admin(self, api):
        """PRD §3.2: "The cascade is immediate: for every child of the family,
        every registration in `ENROLLED`, `WAITLISTED`, or `OFFERED`
        transitions to `CANCELLED` with `cancellation_reason` `ADMIN`".

        Design: Difficulty/transitive_cascade/family_archive_cascades_to_waitlist_promotion
        """
        classroom, family_1, reg_a, _reg_b = self._setup_two_family_queue()
        archived = archive_family(family_1["id"])
        assert archived["status"] == "ARCHIVED"

        reg_a_after = get_registration(reg_a["id"])
        assert reg_a_after["status"] == "CANCELLED"
        assert reg_a_after["cancellation_reason"] == "ADMIN"

    def test_archive_frees_seat_and_promotes_other_family(self, api):
        """PRD §3.2: "each `ENROLLED` cancellation runs its normal cascade —
        the seat flip and promotion waterfall of §3.3." PRD §2.7: the promoted
        registration is "stamped with an `offer_expires_at` of the promotion
        instant plus the program's `waitlist_offer_ttl_hours` (default 48
        hours, at least 1)"; PRD §2.4: "At startup the clock reads exactly
        2026-08-01T00:00:00Z".

        Design: Difficulty/transitive_cascade/family_archive_cascades_to_waitlist_promotion
        """
        classroom, family_1, _reg_a, reg_b = self._setup_two_family_queue()
        archive_family(family_1["id"])

        reg_b_after = get_registration(reg_b["id"])
        assert reg_b_after["status"] == "OFFERED", (
            "the freed seat promoted the other family's waitlisted child"
        )
        assert_instant_equals(reg_b_after["offer_expires_at"], "2026-08-03T00:00:00Z")

        view = get_classroom(classroom["id"])
        assert view["enrolled_count"] == 0
        assert view["offered_count"] == 1
        assert view["status"] == "ACCEPTING"


class TestChildCreation:
    def test_invalid_grade_rejected(self, api):
        """PRD §3.2: children supply "the `grade_completed` (one of `PRE_K`,
        `KINDERGARTEN`, `GRADE_1`, `GRADE_2`, `GRADE_3`, `GRADE_4`, `GRADE_5`,
        `GRADE_6`)"; PRD §2.9 (priority 0): "enums, integers, and dates parse"
        — failures report `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/child_create_with_invalid_grade_rejected
        """
        family = create_family()
        resp = api.create_child(
            create_child_payload(family["id"], grade_completed="GRADE_7"),
            make_parent_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        data, meta = validate_paginated(
            api.list_children(_REGCOORD, params={"family_id": family["id"]})
        )
        assert meta["total_count"] == 0, "the rejected create persisted nothing"


class TestConstraintBeatsReferential:
    def _setup_over_age_child_of_archived_family(self):
        """Child is 10 on the program start_date (outside the 4-6 band) AND
        his family is ARCHIVED: both priority-8 and priority-9 checks fail."""
        program, classroom = setup_open_program_with_classroom(
            capacity=10, age_min=4, age_max=6
        )
        family = create_family()
        child = create_child(
            family["id"], birth_date="2016-01-01", grade_completed="GRADE_4"
        )
        archive_family(family["id"])
        return classroom, child

    def test_age_out_of_range_wins_over_family_archived(self, api):
        """PRD §2.9: "Tiers run in ascending priority number, and when several
        checks fail at once the lowest-numbered failure wins and produces the
        response." — priority 8's "the inclusive age band
        (`ERR_AGE_OUT_OF_RANGE`, HTTP 422)" sits ahead of priority 9's
        "the family must be `ACTIVE` to create children or registrations
        (`ERR_FAMILY_ARCHIVED`)".

        Design: Difficulty/priority_pair_validation_conflict/registration_constraint_beats_referential
        """
        classroom, child = self._setup_over_age_child_of_archived_family()
        resp = api.create_registration(
            {"child_id": child["id"], "classroom_id": classroom["id"]}, _REGCOORD
        )
        validate_error(resp, ApiErrorId.ERR_AGE_OUT_OF_RANGE, 422)

    def test_dual_failure_persists_nothing(self, api):
        """PRD §2.9: "when several checks fail at once the lowest-numbered
        failure wins and produces the response" — the rejected creation is
        atomic, so no registration row exists for the child afterwards.

        Design: Difficulty/priority_pair_validation_conflict/registration_constraint_beats_referential
        """
        classroom, child = self._setup_over_age_child_of_archived_family()
        resp = api.create_registration(
            {"child_id": child["id"], "classroom_id": classroom["id"]}, _REGCOORD
        )
        validate_error(resp, ApiErrorId.ERR_AGE_OUT_OF_RANGE, 422)
        data, meta = validate_paginated(
            api.list_registrations(_REGCOORD, params={"child_id": child["id"]})
        )
        assert meta["total_count"] == 0


class TestFamilyPagination:
    def test_limit_offset_interaction(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        defaulting to 10 with a minimum of 1 and a maximum of 100, and
        `offset`, defaulting to 0. List responses carry the four pagination
        fields `limit`, `offset`, `total_count`, and `has_more` in `meta`.
        Every list sorts by `created_at` ascending, using server-assigned
        monotonic timestamps; an entity's `id` is never used as an ordering key
        or tie-break."

        Design: Corner/endpoints/pagination_limit_offset_interaction
        """
        family_1 = create_family(email="f1@example.com")
        create_family(email="f2@example.com")
        family_3 = create_family(email="f3@example.com")

        page1, meta1 = validate_paginated(
            api.list_families(_REGCOORD, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert page1[0]["email"] == family_1["email"], "creation order"

        page2, meta2 = validate_paginated(
            api.list_families(_REGCOORD, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["email"] == family_3["email"]

        default_page, default_meta = validate_paginated(api.list_families(_REGCOORD))
        assert default_meta["limit"] == 10, "default limit"
        assert len(default_page) == 3
