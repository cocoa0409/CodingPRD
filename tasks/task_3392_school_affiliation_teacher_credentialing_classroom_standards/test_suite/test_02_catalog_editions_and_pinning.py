"""Standards catalog lifecycle: activation ordering, the ACTIVE-catalog
requirement, and edition pinning onto self-studies, schools and audits.
"""

from test_helpers import (
    SOCIETY_ADMIN,
    ApiErrorId,
    create_accepted_self_study,
    create_active_catalog,
    create_classroom,
    create_next_catalog_payload,
    create_self_study,
    create_self_study_payload,
    create_school,
    create_standards_catalog_payload,
    file_classroom_audit,
    make_school_admin_headers,
    read_catalog,
    read_school,
    reset_clock,
    review_self_study,
    submit_self_study,
    validate_error,
    validate_success,
)


def test_catalog_activation_order_and_no_active_catalog(api):
    """PRD section 2.6: "Creating a self-study, a practicum placement, or a
    classroom audit requires an `ACTIVE` catalog to exist; when none does, the
    request is rejected with `ERR_NO_ACTIVE_CATALOG` (HTTP 422)." PRD section
    2.6: "if another edition is already `ACTIVE`, the incoming edition's
    `effective_from` must be strictly later than that edition's, otherwise
    activation is rejected with `ERR_CATALOG_EFFECTIVE_ORDER` (HTTP 422)." PRD
    section 2.6: "Activating a newer edition automatically transitions the
    previously `ACTIVE` edition to `RETIRED` — there is at most one `ACTIVE`
    catalog at any moment."

    Design: Corner/errors/catalog_activation_order_and_no_active_catalog
    """
    reset_clock()
    school = create_school(name="Cat School", display_name="Cat Schoolhouse")

    too_early = api.create_self_study(
        create_self_study_payload(school["id"], school["version"], narrative="too early"),
        headers=make_school_admin_headers(school["id"]),
    )
    validate_error(too_early, ApiErrorId.ERR_NO_ACTIVE_CATALOG)

    first = create_active_catalog()

    cold = validate_success(
        api.create_standards_catalog(
            create_standards_catalog_payload(
                version_label="Standards 2025", effective_from="2025-06-01"
            ),
            headers=SOCIETY_ADMIN,
        ),
        201,
    )
    out_of_order = api.activate_standards_catalog(cold["id"], headers=SOCIETY_ADMIN)
    validate_error(out_of_order, ApiErrorId.ERR_CATALOG_EFFECTIVE_ORDER)

    newer = validate_success(
        api.create_standards_catalog(create_next_catalog_payload(), headers=SOCIETY_ADMIN),
        201,
    )
    validate_success(api.activate_standards_catalog(newer["id"], headers=SOCIETY_ADMIN), 200)

    assert read_catalog(first["id"])["status"] == "RETIRED"
    assert read_catalog(newer["id"])["status"] == "ACTIVE"


def test_self_study_review_survives_catalog_retirement(api):
    """PRD section 2.6: "A `SelfStudy` pins the currently `ACTIVE` catalog at
    creation, storing `pinned_catalog_id` plus a denormalized
    `pinned_catalog_label` copied from the edition's `version_label`, and its
    review proceeds against that edition even if the edition is later retired."
    PRD section 2.6: "When a self-study is accepted, the school adopts that
    pinned edition as its own `pinned_catalog_id`, which then drives
    classroom-audit scoring until replaced."

    Design: Corner/cross_cutting_layers/self_study_review_survives_catalog_retirement
    """
    reset_clock()
    first = create_active_catalog()
    school = create_school(name="Pin School", display_name="Pin Schoolhouse 2")
    study = create_self_study(school["id"], narrative="Pinned self-study")
    assert study["pinned_catalog_id"] == first["id"]
    assert study["pinned_catalog_label"] == "Standards 2026"
    submit_self_study(study["id"], school["id"])

    successor = validate_success(
        api.create_standards_catalog(create_next_catalog_payload(), headers=SOCIETY_ADMIN),
        201,
    )
    validate_success(api.activate_standards_catalog(successor["id"], headers=SOCIETY_ADMIN), 200)

    accepted = review_self_study(study["id"], "ACCEPTED")
    assert accepted["status"] == "ACCEPTED"
    pinned = read_school(school["id"])["pinned_catalog_id"]
    assert pinned == first["id"], "school inherits the pinned edition, not the ACTIVE one"
    assert pinned != successor["id"]


def test_audit_uses_pinned_catalog_not_newer_active_edition(api):
    """PRD section 2.6: "Each `ClassroomAudit` records, in its `catalog_id`, the
    edition it was scored against — the school's pinned edition when one is set,
    otherwise the catalog that is `ACTIVE` at audit time." PRD section 3.3: the
    work-period check "sets `work_period_pass` when
    `observed_uninterrupted_minutes` is at least the catalog's
    `min_uninterrupted_work_minutes_by_level` minimum".

    Design: Corner/calculations/audit_input_set_excludes_other_classrooms_and_uses_pinned_catalog
    """
    reset_clock()
    first = create_active_catalog()
    pinned_school = create_school(name="P School", display_name="P Schoolhouse")
    create_accepted_self_study(pinned_school["id"])

    successor = validate_success(
        api.create_standards_catalog(create_next_catalog_payload(), headers=SOCIETY_ADMIN),
        201,
    )
    validate_success(api.activate_standards_catalog(successor["id"], headers=SOCIETY_ADMIN), 200)

    plain_school = create_school(name="Q School", display_name="Q Schoolhouse")
    pinned_room = create_classroom(pinned_school["id"], name="CP")
    plain_room = create_classroom(plain_school["id"], name="CQ")

    # 185 minutes passes the first edition's 180-minute EARLY_CHILDHOOD floor
    # but fails the successor edition's 200-minute floor.
    full_materials = [{"domain": "PRACTICAL_LIFE", "required_count": 10, "present_count": 10}]
    pinned_audit = file_classroom_audit(
        pinned_room["id"],
        students_present=20,
        adults_present=2,
        observed_uninterrupted_minutes=185,
        materials_groups=full_materials,
    )
    plain_audit = file_classroom_audit(
        plain_room["id"],
        students_present=20,
        adults_present=2,
        observed_uninterrupted_minutes=185,
        materials_groups=full_materials,
    )
    assert pinned_audit["catalog_id"] == first["id"]
    assert pinned_audit["verdict"] == "COMPLIANT"
    assert plain_audit["catalog_id"] == successor["id"]
    assert plain_audit["verdict"] == "NONCOMPLIANT"
    assert plain_audit["failed_checks"] == ["WORK_PERIOD"]
