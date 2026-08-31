"""Authentication, role authorization and entity-backed ownership."""

from test_helpers import (
    ADMIN,
    COURSE_EXT_101,
    REGISTRAR,
    ApiErrorId,
    add_paid_registration,
    create_course_payload,
    deposit,
    issue_voucher,
    make_instructor_headers,
    make_learner_headers,
    make_sponsor_headers,
    new_account,
    new_learner,
    pay_payload,
    read_contract,
    read_registration,
    read_voucher,
    register_learner,
    reset_clock,
    set_clock,
    setup_open_offering,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_x_user_id_header_returns_unauthenticated(api):
    """PRD 2.1: "`X-User-ID` must also be present on every request except those made as
    `Anonymous`, which is the sole role permitted to omit it. A request whose
    `X-User-Role` is missing, or names a string that is not one of those six, or whose
    `X-User-ID` is missing for a non-`Anonymous` role, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated
    """
    reset_clock()
    headers = {"X-User-Role": "ProgramAdmin", "Content-Type": "application/json"}
    validate_error(
        api.create_course(create_course_payload(**COURSE_EXT_101), headers),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    _, meta = validate_paginated(api.list_courses(ADMIN))
    assert meta["total_count"] == 0


def test_instructor_cannot_take_the_census_decision(api):
    """PRD 2.1: "A well-formed caller whose role does not appear in the authorized-role
    list of the endpoint being addressed is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD 3.6: "The minimum-enrollment cancellation decision is the single most
    consequential act in the extension school's calendar, and it is taken once per
    section by a `ProgramAdmin`."

    Design: Corner/rbac/instructor_cannot_run_offering_census
    """
    reset_clock()
    scene = setup_open_offering()
    add_paid_registration(scene["offering_id"], learner_index=0)
    set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api.census_offering(
            scene["offering_id"], make_instructor_headers(scene["instructor_id"])
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["status"] == "OPEN"
    assert read_contract(scene["contract_id"])["census_headcount"] is None


def test_learner_cannot_pay_another_learners_registration(api):
    """PRD 2.1: "When `X-User-Role` is `Learner`, `X-User-ID` is the `id` of the acting
    `Learner`; ownership checks on any resource that references a `Learner` compare the
    resource's learner foreign-key field to `X-User-ID`."
    PRD 2.1: "A `Learner` acting on another learner's learner record, registration, or
    petition; an `Instructor` acting on a contract that is not theirs or on a
    registration whose section they do not staff; a `CorporateSponsor` acting on another
    sponsor's account or voucher — all are rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/learner_cannot_pay_another_learners_registration
    """
    reset_clock()
    scene = setup_open_offering()
    ada = new_learner(email="ada@x.com", full_name="Ada Ito")
    ben = new_learner(email="ben@x.com", full_name="Ben Osei")
    registration = register_learner(scene["offering_id"], ada["id"], scene["version"])

    validate_error(
        api.pay_registration(
            registration["id"], pay_payload("SELF_PAY"), make_learner_headers(ben["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    after = read_registration(registration["id"])
    assert after["payment_status"] == "UNPAID"
    assert after["enrollment_status"] == "PENDING"
    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["confirmed_enrollment_count"] == 0


def test_sponsor_cannot_assign_another_sponsors_voucher(api):
    """PRD 2.1: "When `X-User-Role` is `CorporateSponsor`, `X-User-ID` is the `id` of
    the acting `CorporateAccount`; ownership checks on any resource that references a
    `CorporateAccount` compare the resource's sponsor foreign-key field to `X-User-ID`."
    PRD 3.4: "A voucher is bound to a person before it can be spent. The owning sponsor
    names a `learner_id`, and the voucher moves `ISSUED → ASSIGNED` with
    `assigned_learner_id` set to that learner and its `version` incremented by 1; the
    assignment also runs the marketing segmentation recompute for the assigned learner,
    since the corporate-sponsorship axis has just changed."

    Design: Corner/rbac/corporate_sponsor_cannot_assign_another_sponsors_voucher
    """
    reset_clock()
    acme = new_account(org_name="ACME Industrial", billing_email="ap@acme.example")
    beta = new_account(org_name="BETA Logistics", billing_email="ap@beta.example")
    funded = deposit(acme["id"], 200000)
    voucher = issue_voucher(acme["id"], 200000, funded["version"])
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")

    validate_error(
        api.assign_voucher(
            voucher["id"], {"learner_id": learner["id"]}, make_sponsor_headers(beta["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    after = read_voucher(voucher["id"], acme["id"])
    assert after["status"] == "ISSUED"
    assert after["assigned_learner_id"] is None
    _, meta = validate_paginated(
        api.list_vouchers(REGISTRAR, params={"assigned_learner_id": learner["id"]})
    )
    assert meta["total_count"] == 0


def test_registrar_may_register_and_pay_on_behalf_of_a_learner(api):
    """PRD 2.1: "When `X-User-Role` is `Registrar`, `X-User-ID` is likewise an opaque
    operator identifier not tied to any persisted entity and is not compared to any
    entity's `id`."
    PRD 3.5: "Either the learner or a `Registrar` opens a registration against a
    section, supplying the `learner_id` and the `expected_offering_version` guard of
    §2.6."
    PRD 3.5: "The learner or a `Registrar` supplies a `method` of either `SELF_PAY` or
    `VOUCHER`, plus a `voucher_id` when the method is `VOUCHER`."

    Design: Corner/rbac/registrar_may_register_and_pay_on_behalf_of_a_learner
    """
    reset_clock()
    scene = setup_open_offering()
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")

    created = validate_success(
        api.create_registration(
            scene["offering_id"],
            {"learner_id": learner["id"], "expected_offering_version": scene["version"]},
            REGISTRAR,
        ),
        201,
    )
    assert created["learner_id"] == learner["id"]

    paid = validate_success(
        api.pay_registration(created["id"], pay_payload("SELF_PAY"), REGISTRAR)
    )
    assert paid["enrollment_status"] == "ENROLLED"
    assert paid["payment_status"] == "PAID"
    assert paid["amount_paid_cents"] == 62400
    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["paid_enrollment_count"] == 1
