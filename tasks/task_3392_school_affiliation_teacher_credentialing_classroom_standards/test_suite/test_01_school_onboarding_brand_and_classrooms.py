"""School onboarding defaults, brand rules, classroom creation and listing.

Covers the school-create default surface with its floored dues quote, the
brand differentiation rule (at onboarding and at brand update), case-
insensitive display-name uniqueness, classroom creation against an unknown
school, and classroom list pagination.
"""

from test_helpers import (
    ACCREDITATION_REVIEWER,
    CONSULTANT,
    MIN_DUES_CENTS,
    NON_EXISTENT_UUID_ALT,
    SOCIETY_ADMIN,
    ApiErrorId,
    assert_school,
    create_classroom,
    create_classroom_payload,
    create_school,
    create_school_payload,
    make_school_admin_headers,
    read_classroom,
    read_school,
    reset_clock,
    update_brand_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_school_create_returns_defaults_and_floored_dues(api):
    """PRD section 3.2: "New schools start at membership level `APPLICANT` with
    standing `GOOD_STANDING`." PRD section 3.2: "an `APPLICANT` school quotes
    the `AFFILIATE` schedule" and "an `AFFILIATE` school with zero students and
    one classroom raws to 48000 cents and pays the 60000-cent floor" — with zero
    classrooms the raw 40000 is still lifted by the same 60000-cent floor.

    Design: Corner/entities/school_create_returns_defaults_and_floored_dues_quote
    """
    reset_clock()
    resp = api.create_school(
        create_school_payload(
            name="Naked School",
            display_name="Naked Schoolhouse",
            uses_method_name=False,
            contact_email="n@x.org",
        ),
        headers=SOCIETY_ADMIN,
    )
    data = validate_success(resp, 201)
    assert_school(data)
    assert data["membership_level"] == "APPLICANT"
    assert data["standing"] == "GOOD_STANDING"
    assert data["dues_current"] is False
    assert data["brand_compliant"] is True
    assert data["directory_visible"] is False
    assert data["total_enrollment"] == 0
    assert data["compliant_classroom_count"] == 0
    assert data["annual_dues_cents"] == MIN_DUES_CENTS
    for field in (
        "affiliated_since",
        "member_since",
        "accredited_since",
        "dues_paid_through",
        "pinned_catalog_id",
    ):
        assert data[field] is None, "{0} must be null on a fresh school".format(field)


def test_classroom_create_roundtrip_and_unknown_school_rejected(api):
    """PRD section 2.7: "Tier 3 is existence: path identifiers are validated left
    to right, then body-supplied foreign keys that are present and well-formed"
    — an unknown `school_id` on classroom create fails `ERR_SCHOOL_NOT_FOUND`.
    PRD section 3.3: "the optional `lead_credential_id` is null in that case" and
    the room "carries a system-managed `compliance_override`, normally `NONE`".

    Design: Corner/entities/classroom_create_roundtrip_and_unknown_school_rejected
    """
    reset_clock()
    school = create_school(name="Parent School", display_name="Parent Schoolhouse")

    ghost = api.create_classroom(
        create_classroom_payload(
            NON_EXISTENT_UUID_ALT,
            name="Ghost",
            age_level="EARLY_CHILDHOOD",
            declared_age_span_years=3,
            enrolled_student_count=10,
            assistant_count=1,
        ),
        headers=make_school_admin_headers(NON_EXISTENT_UUID_ALT),
    )
    validate_error(ghost, ApiErrorId.ERR_SCHOOL_NOT_FOUND)

    created = api.create_classroom(
        create_classroom_payload(
            school["id"],
            name="Willow",
            age_level="ELEMENTARY_I",
            declared_age_span_years=3,
            enrolled_student_count=26,
            assistant_count=2,
        ),
        headers=make_school_admin_headers(school["id"]),
    )
    room = validate_success(created, 201)
    fetched = read_classroom(room["id"], headers=make_school_admin_headers(school["id"]))
    assert fetched["age_level"] == "ELEMENTARY_I"
    assert fetched["declared_age_span_years"] == 3
    assert fetched["enrolled_student_count"] == 26
    assert fetched["assistant_count"] == 2
    assert fetched["compliance_override"] == "NONE"
    assert fetched["latest_audit_verdict"] is None


def test_classrooms_list_paginates_with_total_count_and_has_more(api):
    """PRD section 2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at a maximum of 100." PRD section 2.3: "List responses carry four
    pagination fields in the `meta` object of the envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/classrooms_list_paginates_with_total_count_and_has_more
    """
    reset_clock()
    school = create_school(name="Page School", display_name="Page Schoolhouse")
    create_classroom(school["id"], name="P1", enrolled_student_count=10)
    create_classroom(school["id"], name="P2", enrolled_student_count=12)
    create_classroom(
        school["id"], name="P3", age_level="ELEMENTARY_I", enrolled_student_count=14
    )

    page1, meta1 = validate_paginated(
        api.list_classrooms(
            headers=ACCREDITATION_REVIEWER,
            params={"school_id": school["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_classrooms(
            headers=ACCREDITATION_REVIEWER,
            params={"school_id": school["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert page2[0]["name"] == "P3"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    # The age_level filter scopes the listed set, so total_count counts only
    # the matching rows (PRD 2.3: offset skips items of the filtered list).
    filtered, meta_f = validate_paginated(
        api.list_classrooms(
            headers=ACCREDITATION_REVIEWER,
            params={"school_id": school["id"], "age_level": "ELEMENTARY_I"},
        )
    )
    assert len(filtered) == 1
    assert filtered[0]["name"] == "P3"
    assert meta_f["total_count"] == 1
    assert meta_f["has_more"] is False

    all_rows, meta3 = validate_paginated(api.list_classrooms(headers=ACCREDITATION_REVIEWER))
    assert len(all_rows) == 3
    assert meta3["limit"] == 10
    assert meta3["total_count"] == 3


def test_brand_differentiation_required_for_method_name_use(api):
    """PRD section 3.2: "A school's computed `brand_compliant` flag is true when
    the school does not use the method name, or when the school is `ACCREDITED`,
    or when a non-`ACCREDITED` school using the method name carries a
    `descriptor` that actually appears inside its `display_name`." PRD section
    3.2: "a violation is rejected with `ERR_BRAND_DIFFERENTIATION_REQUIRED`
    (HTTP 422)."

    Design: Corner/validations/brand_differentiation_required_for_non_accredited_method_name_use
    """
    reset_clock()
    no_descriptor = api.create_school(
        create_school_payload(
            name="Bare",
            display_name="Springfield Montessori School",
            uses_method_name=True,
            contact_email="b1@x.org",
        ),
        headers=SOCIETY_ADMIN,
    )
    validate_error(no_descriptor, ApiErrorId.ERR_BRAND_DIFFERENTIATION_REQUIRED)

    stray_descriptor = api.create_school(
        create_school_payload(
            name="BadDesc",
            display_name="Springfield Montessori School",
            uses_method_name=True,
            descriptor="Inspired",
            contact_email="b2@x.org",
        ),
        headers=SOCIETY_ADMIN,
    )
    validate_error(stray_descriptor, ApiErrorId.ERR_BRAND_DIFFERENTIATION_REQUIRED)

    good = api.create_school(
        create_school_payload(
            name="Good",
            display_name="Springfield Montessori Inspired School",
            uses_method_name=True,
            descriptor="Inspired",
            contact_email="b3@x.org",
        ),
        headers=SOCIETY_ADMIN,
    )
    good_data = validate_success(good, 201)
    assert good_data["brand_compliant"] is True


def test_display_name_case_insensitive_uniqueness(api):
    """PRD section 3.2: "Independently, `display_name` must be unique
    case-insensitively across all schools at any level; a collision is rejected
    with `ERR_DISPLAY_NAME_TAKEN` (HTTP 409)."

    Design: Corner/validations/display_name_case_insensitive_uniqueness
    """
    reset_clock()
    create_school(name="Cedar", display_name="Cedar Lane School")
    clone = api.create_school(
        create_school_payload(
            name="Cedar Clone",
            display_name="cedar lane school",
            uses_method_name=False,
            contact_email="c2@x.org",
        ),
        headers=SOCIETY_ADMIN,
    )
    validate_error(clone, ApiErrorId.ERR_DISPLAY_NAME_TAKEN)


def test_brand_update_recomputes_compliance_and_bumps_version(api):
    """PRD section 3.2: "The rule bites at three moments — school onboarding,
    any later brand update by the school's own `SchoolAdmin` (payload
    `display_name`, `uses_method_name`, optional `descriptor`), and affiliation
    submission — and a violation is rejected with
    `ERR_BRAND_DIFFERENTIATION_REQUIRED` (HTTP 422)." PRD section 3.2:
    "A successful brand update recomputes `brand_compliant` and
    `directory_visible` and increments the school's `version`."

    Design: Corner/cross_cutting_layers/brand_update_recomputes_compliance_and_bumps_version
    """
    reset_clock()
    school = create_school(name="Brand School", display_name="Brand Schoolhouse")
    version_before = school["version"]

    rejected = api.update_school_brand(
        school["id"],
        update_brand_payload(display_name="Brand Montessori School", uses_method_name=True),
        headers=make_school_admin_headers(school["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_BRAND_DIFFERENTIATION_REQUIRED)

    accepted = api.update_school_brand(
        school["id"],
        update_brand_payload(
            display_name="Brand Montessori Inspired School",
            uses_method_name=True,
            descriptor="Inspired",
        ),
        headers=make_school_admin_headers(school["id"]),
    )
    updated = validate_success(accepted, 200)
    assert updated["brand_compliant"] is True
    assert updated["version"] == version_before + 1, "exactly one version bump"

    rejected_again = api.update_school_brand(
        school["id"],
        update_brand_payload(display_name="Brand Montessori School", uses_method_name=True),
        headers=make_school_admin_headers(school["id"]),
    )
    validate_error(rejected_again, ApiErrorId.ERR_BRAND_DIFFERENTIATION_REQUIRED)

    final = read_school(school["id"])
    assert final["version"] == version_before + 1, "rejected updates never mutate"
    assert final["display_name"] == "Brand Montessori Inspired School"
