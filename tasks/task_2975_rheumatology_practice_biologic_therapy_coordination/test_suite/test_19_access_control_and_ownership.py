"""Authentication, role authorization, the credential gate and ownership.

Every test in this module translates exactly one instance of the `rbac`
section of the breadth-test design index:

  * a blank (or absent) identity header is `ERR_UNAUTHENTICATED`, never
    `ERR_FORBIDDEN_ROLE` (PRD §2.1, §2.10 rule 1),
  * each exclusive operation refuses every role outside its authorized list,
    and does so before any existence check (PRD §2.1, §2.10 rule 2),
  * formulary-exception signing is role-plus-credential (PRD §2.1, §3.5),
  * only a visit's own clinician may score it (PRD §2.1, §3.2),
  * a `Patient` caller may read only their own chart (PRD §2.1),
  * one counselor may not both submit and attest an enrollment (PRD §3.8).
"""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import instant
from test_helpers.fixtures import ADMIN, COUNSELOR, COUNSELOR_TWO
from test_helpers.test_users import (
    COUNSELOR_ALPHA_USER_ID,
    COUNSELOR_BETA_USER_ID,
    make_headers,
    make_infusion_nurse_headers,
    make_patient_headers,
    make_rheumatologist_headers,
)


# ---------------------------------------------------------------------------
# rbac / a_blank_identity_header_is_unauthenticated_not_forbidden
# ---------------------------------------------------------------------------
def test_a_blank_identity_header_is_unauthenticated_not_forbidden(api):
    """A header transmitted as the empty string is refused with
    `ERR_UNAUTHENTICATED` 401, never with `ERR_FORBIDDEN_ROLE` 403.

    PRD §2.1: "Both must be present and non-empty; a header that is absent, and
    a header that is transmitted as an empty string, are treated identically and
    the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.10: "`ERR_UNAUTHENTICATED` — either authentication header missing or
    empty. Applies to every endpoint."

    Design: Corner/rbac/a_blank_identity_header_is_unauthenticated_not_forbidden
    """
    fixtures.set_clock(instant(2026, 8, 1))
    patient = get_success_data(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Pat One"), ADMIN
        ),
        201,
    )

    blank_role = {
        "X-User-ID": "registry-alpha",
        "X-User-Role": "",
        "Content-Type": "application/json",
    }
    blank_user = {
        "X-User-ID": "",
        "X-User-Role": "RegistryAdmin",
        "Content-Type": "application/json",
    }
    blank_both = {
        "X-User-ID": "",
        "X-User-Role": "",
        "Content-Type": "application/json",
    }

    validate_error(
        api.get_patient(patient["id"], blank_role),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.get_patient(patient["id"], blank_user),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    second_patient = factories.create_patient_payload(
        mrn="RH0002", full_name="Pat Two", date_of_birth="1980-09-30", diagnosis_code="PSA"
    )
    validate_error(
        api.create_patient(second_patient, blank_both),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    # Nothing persisted: mrn RH0002 is still free, so the admin's own create of
    # the very same natural key succeeds instead of colliding.
    created = get_success_data(api.create_patient(second_patient, ADMIN), 201)
    assert created["mrn"] == "RH0002"


ABSENT_HEADER_CASES = [
    pytest.param({"X-User-ID": "registry-alpha"}, id="role-header-absent"),
    pytest.param({"X-User-Role": "RegistryAdmin"}, id="user-header-absent"),
    pytest.param({}, id="both-headers-absent"),
]


@pytest.mark.parametrize("headers", ABSENT_HEADER_CASES)
def test_an_absent_identity_header_is_unauthenticated_too(api, headers):
    """An absent header is treated identically to a blank one: 401, not 403.

    PRD §2.1: "Both must be present and non-empty; a header that is absent, and
    a header that is transmitted as an empty string, are treated identically and
    the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/a_blank_identity_header_is_unauthenticated_not_forbidden
    """
    fixtures.set_clock(instant(2026, 8, 1))
    patient = get_success_data(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Pat One"), ADMIN
        ),
        201,
    )

    validate_error(
        api.get_patient(patient["id"], headers),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )


# ---------------------------------------------------------------------------
# rbac / each_exclusive_operation_rejects_every_role_that_does_not_own_it
# ---------------------------------------------------------------------------
FORBIDDEN_ROLE_CASES = [
    pytest.param(
        "POST",
        "/patients",
        {
            "mrn": "RH0009",
            "full_name": "Nine",
            "date_of_birth": "1970-01-01",
            "diagnosis_code": "PSA",
            "registry_consent": True,
        },
        "Rheumatologist",
        "rheum-alpha",
        id="rheumatologist-cannot-register-a-patient",
    ),
    pytest.param(
        "POST",
        f"/authorizations/{NON_EXISTENT_UUID}/submit",
        {},
        "PayerReviewer",
        "payer-alpha",
        id="payer-cannot-submit",
    ),
    pytest.param(
        "POST",
        f"/authorizations/{NON_EXISTENT_UUID}/determination",
        {"decision": "APPROVED"},
        "PriorAuthCoordinator",
        "pac-alpha",
        id="coordinator-cannot-decide",
    ),
    pytest.param(
        "POST",
        f"/visits/{NON_EXISTENT_UUID}/check-in",
        {},
        "Rheumatologist",
        "rheum-alpha",
        id="rheumatologist-cannot-check-in",
    ),
    pytest.param(
        "POST",
        "/assistance-enrollments",
        {
            "episode_id": NON_EXISTENT_UUID,
            "program_type": "FOUNDATION_GRANT",
            "annual_benefit_cents": 50_000,
            "coverage_start": instant(2026, 8, 1),
        },
        "PriorAuthCoordinator",
        "pac-alpha",
        id="coordinator-cannot-enroll",
    ),
    pytest.param(
        "POST",
        "/_ops/run-reauthorization-calendar",
        {},
        "BenefitsCounselor",
        "counselor-alpha",
        id="counselor-cannot-sweep",
    ),
    pytest.param(
        "GET",
        "/patients/{patient_id}",
        None,
        "ChiefOfStaff",
        "chief-alpha",
        id="unknown-role-string",
    ),
]


@pytest.mark.parametrize("method,path,payload,role,user_id", FORBIDDEN_ROLE_CASES)
def test_each_exclusive_operation_rejects_every_role_that_does_not_own_it(
    api, method, path, payload, role, user_id
):
    """The role check answers before any existence check, so an all-zero path id
    still yields `ERR_FORBIDDEN_ROLE` 403 rather than a 404; an unrecognised role
    string lands here too, not on the 401.

    PRD §2.1: "A value of `X-User-Role` that is not one of those seven strings is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403), and so is a value that is one
    of the seven but does not appear in the authorized-role list of the endpoint
    being addressed."
    PRD §2.10: "`ERR_FORBIDDEN_ROLE` — the role is unrecognised, or is not
    authorized for this endpoint. Applies to every endpoint."

    Design: Corner/rbac/each_exclusive_operation_rejects_every_role_that_does_not_own_it
    """
    fixtures.set_clock(instant(2026, 8, 1))
    patient = get_success_data(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Pat One"), ADMIN
        ),
        201,
    )

    response = api.raw(
        method,
        path.format(patient_id=patient["id"]),
        payload,
        make_headers(user_id, role),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_a_role_rejected_create_writes_no_row(api):
    """A create refused on the role alone persists nothing, so its natural key is
    still free for the authorized role afterwards.

    PRD §2.1: "A value of `X-User-Role` that is not one of those seven strings is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403), and so is a value that is one
    of the seven but does not appear in the authorized-role list of the endpoint
    being addressed."

    Design: Corner/rbac/each_exclusive_operation_rejects_every_role_that_does_not_own_it
    """
    fixtures.set_clock(instant(2026, 8, 1))
    payload = factories.create_patient_payload(
        mrn="RH0009",
        full_name="Nine",
        date_of_birth="1970-01-01",
        diagnosis_code="PSA",
    )

    validate_error(
        api.create_patient(payload, make_headers("rheum-alpha", "Rheumatologist")),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    # mrn RH0009 was never taken, so the admin's create succeeds rather than
    # colliding with a row the forbidden call might have written.
    created = get_success_data(api.create_patient(payload, ADMIN), 201)
    assert created["mrn"] == "RH0009"


# ---------------------------------------------------------------------------
# rbac / formulary_exception_attestation_needs_a_rheumatologist_holding_the_privilege
# ---------------------------------------------------------------------------
def test_formulary_exception_attestation_needs_a_rheumatologist_holding_the_privilege(api):
    """Holding the `Rheumatologist` role is not enough: the clinician row behind
    `X-User-ID` must exist, be a `RHEUMATOLOGIST` and carry the privilege.

    PRD §2.1: "A caller whose clinician row is missing, whose `role_type` is
    `NURSE`, or whose `can_attest_formulary_exception` is false is refused with
    `ERR_CLINICIAN_NOT_AUTHORIZED_TO_ATTEST` (HTTP 403)."
    PRD §3.5: "A credentialed `Rheumatologist` — one whose clinician row is a
    `RHEUMATOLOGIST` carrying `can_attest_formulary_exception` — signs the
    exception on an authorization that is in `DRAFT` or `DENIED`, and the server
    writes that clinician's `X-User-ID` into `exception_attested_by_clinician_id`
    and increments the authorization's `version` by one."

    Design: Corner/rbac/formulary_exception_attestation_needs_a_rheumatologist_holding_the_privilege
    """
    fixtures.set_clock(instant(2026, 8, 1))
    rheum_one = fixtures.create_clinician(
        None, npi="1234567893", full_name="Ada Rheum", can_attest_formulary_exception=True
    )
    rheum_two = fixtures.create_clinician(
        None, npi="1234567894", full_name="Bo Rheum", can_attest_formulary_exception=False
    )
    nurse_one = get_success_data(
        api.create_clinician(
            factories.create_nurse_payload(npi="1234567895", full_name="Nia Nurse"), ADMIN
        ),
        201,
    )
    tocilizumab = fixtures.create_drug(
        None,
        factories.create_drug_payload(
            name="Tocilizumab",
            molecule_class="IL6",
            route="IV",
            formulary_tier=4,
            acquisition_cost_cents=500_000,
            admin_time_minutes=150,
            monitoring_panel_type="CMP",
            monitoring_panel_interval_days=90,
        ),
    )
    plan = fixtures.create_plan(None, factories.meridian_plan_payload())
    patient = get_success_data(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Pat One"), ADMIN
        ),
        201,
    )

    episode = get_success_data(
        api.create_therapy_episode(
            factories.create_therapy_episode_payload(
                patient["id"],
                tocilizumab["id"],
                plan["id"],
                patient["version"],
                therapy_start_at=instant(2026, 8, 1),
            ),
            make_rheumatologist_headers(rheum_one["id"]),
        ),
        201,
    )
    authorization = get_success_data(
        api.create_authorization(
            factories.create_authorization_payload(
                episode["id"], episode["version"], 6, formulary_exception_requested=True
            ),
            fixtures.COORDINATOR,
        ),
        201,
    )
    assert authorization["exception_attested_by_clinician_id"] is None
    created_version = authorization["version"]

    # Role passes, credential does not: the privilege flag is false.
    validate_error(
        api.attest_exception(
            authorization["id"], make_rheumatologist_headers(rheum_two["id"])
        ),
        ApiErrorId.ERR_CLINICIAN_NOT_AUTHORIZED_TO_ATTEST.value,
        403,
    )
    # The resolved row is a NURSE, whatever the header claims.
    validate_error(
        api.attest_exception(
            authorization["id"], make_rheumatologist_headers(nurse_one["id"])
        ),
        ApiErrorId.ERR_CLINICIAN_NOT_AUTHORIZED_TO_ATTEST.value,
        403,
    )
    # No clinician row resolves at all.
    validate_error(
        api.attest_exception(
            authorization["id"], make_rheumatologist_headers(NON_EXISTENT_UUID)
        ),
        ApiErrorId.ERR_CLINICIAN_NOT_AUTHORIZED_TO_ATTEST.value,
        403,
    )

    signed = get_success_data(
        api.attest_exception(
            authorization["id"], make_rheumatologist_headers(rheum_one["id"])
        )
    )
    assert signed["exception_attested_by_clinician_id"] == rheum_one["id"]
    assert signed["status"] == "DRAFT"
    assert signed["version"] == created_version + 1, (
        "only the credentialed signature bumped the revision counter"
    )


# ---------------------------------------------------------------------------
# rbac / only_the_visits_own_clinician_may_score_it
# ---------------------------------------------------------------------------
def test_only_the_visits_own_clinician_may_score_it(api):
    """Two callers both hold `Rheumatologist`, so the role gate passes for each;
    the ownership comparison against `clinician_id` separates them.

    PRD §2.1: "Ownership is enforced in exactly four places, and the rejection in
    all four is `ERR_NOT_RESOURCE_OWNER` (HTTP 403): scoring a visit, where the
    caller's `X-User-ID` must equal the visit's `clinician_id`; reading a single
    patient; listing a patient's screening records; and listing visits, where a
    caller acting as `Patient` must address their own patient `id` in the path or
    supply their own `id` as the `patient_id` filter."
    PRD §3.2: "Scoring advances the visit `CHECKED_IN → SCORED`, which is
    terminal, and only the treating rheumatologist may do it — the caller's
    `X-User-ID` must equal the visit's `clinician_id`, or the request is refused
    with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/only_the_visits_own_clinician_may_score_it
    """
    fixtures.set_clock(instant(2026, 8, 1))
    rheum_one = fixtures.create_clinician(
        None, npi="1234567893", full_name="Ada Rheum", can_attest_formulary_exception=True
    )
    rheum_two = fixtures.create_clinician(
        None, npi="1234567894", full_name="Bo Rheum", can_attest_formulary_exception=False
    )
    nurse_one = get_success_data(
        api.create_clinician(
            factories.create_nurse_payload(npi="1234567895", full_name="Nia Nurse"), ADMIN
        ),
        201,
    )
    patient = get_success_data(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Pat One"), ADMIN
        ),
        201,
    )

    visit = get_success_data(
        api.create_visit(
            factories.create_visit_payload(
                patient["id"],
                rheum_one["id"],
                visit_datetime=instant(2026, 8, 1, 9, 0, 0),
                visit_type="NEW",
            ),
            ADMIN,
        ),
        201,
    )
    checked_in = get_success_data(
        api.check_in_visit(visit["id"], make_infusion_nurse_headers(nurse_one["id"]))
    )
    assert checked_in["status"] == "CHECKED_IN"
    checked_in_version = checked_in["version"]

    score_payload = factories.score_visit_cdai_payload(
        tender_joint_count=1,
        swollen_joint_count=1,
        patient_global_assessment=2.0,
        physician_global_assessment=2.0,
    )

    validate_error(
        api.score_visit(
            visit["id"], score_payload, make_rheumatologist_headers(rheum_two["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )

    untouched = get_success_data(api.get_visit(visit["id"], ADMIN))
    assert untouched["status"] == "CHECKED_IN"
    assert untouched["activity_score"] is None
    assert untouched["version"] == checked_in_version

    scored = get_success_data(
        api.score_visit(
            visit["id"], score_payload, make_rheumatologist_headers(rheum_one["id"])
        )
    )
    assert scored["status"] == "SCORED"
    assert scored["activity_score"] == 6.00
    assert scored["activity_category"] == "LOW"
    assert scored["escalation_recommendation"] == "CONTINUE"

    projected = get_success_data(api.get_patient(patient["id"], ADMIN))
    assert projected["latest_activity_score"] == 6.00
    assert projected["target_status"] == "AT_TARGET"


# ---------------------------------------------------------------------------
# rbac / a_patient_role_can_read_only_its_own_chart
# ---------------------------------------------------------------------------
def test_a_patient_role_can_read_only_its_own_chart(api):
    """For the `Patient` role the ownership comparison covers all three reads;
    only the caller's own chart answers 200.

    PRD §2.1: "Ownership is enforced in exactly four places, and the rejection in
    all four is `ERR_NOT_RESOURCE_OWNER` (HTTP 403): scoring a visit, where the
    caller's `X-User-ID` must equal the visit's `clinician_id`; reading a single
    patient; listing a patient's screening records; and listing visits, where a
    caller acting as `Patient` must address their own patient `id` in the path or
    supply their own `id` as the `patient_id` filter."
    PRD §2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the
    acting `Patient`; ownership checks compare the patient identified in the
    request to `X-User-ID`."

    Design: Corner/rbac/a_patient_role_can_read_only_its_own_chart
    """
    fixtures.set_clock(instant(2026, 8, 1))
    patient_one = get_success_data(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Pat One"), ADMIN
        ),
        201,
    )
    patient_two = get_success_data(
        api.create_patient(
            factories.create_patient_payload(
                mrn="RH0002",
                full_name="Pat Two",
                date_of_birth="1980-09-30",
                diagnosis_code="PSA",
            ),
            ADMIN,
        ),
        201,
    )
    caller = make_patient_headers(patient_one["id"])

    validate_error(
        api.get_patient(patient_two["id"], caller),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )
    validate_error(
        api.list_patient_screening_records(patient_two["id"], caller),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )
    validate_error(
        api.list_visits(caller, params={"patient_id": patient_two["id"]}),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )

    own_chart = validate_success(api.get_patient(patient_one["id"], caller), 200)
    assert own_chart["id"] == patient_one["id"]
    assert own_chart["mrn"] == "RH0001"


# ---------------------------------------------------------------------------
# rbac / the_same_counselor_cannot_submit_and_attest_one_enrollment
# ---------------------------------------------------------------------------
def test_the_same_counselor_cannot_submit_and_attest_one_enrollment(api):
    """Both callers hold `BenefitsCounselor`; only the second `X-User-ID` may
    attest, and the refusal leaves the enrollment exactly as it was.

    PRD §3.8: "It must be attested by a **second** counselor before it becomes
    visible to the assistance selector, and that separation is enforced rather
    than encouraged: the attesting caller's `X-User-ID` must differ from the
    enrollment's `submitted_by_user_id`, and a counselor attesting their own
    submission is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD §3.8: "A successful attestation advances `SUBMITTED → ACTIVE`, writes
    `attested_by_user_id` from the attesting caller's `X-User-ID` and
    `attested_at` from the logical clock, and increments the enrollment's
    `version` by one."
    PRD §3.8: "The server writes `coverage_end` as `coverage_start` advanced by
    that many whole days. It then writes `reauth_due_at` as `coverage_end` pulled
    back by 30 days, giving the counselor a month of lead time before coverage
    runs out."

    Design: Corner/rbac/the_same_counselor_cannot_submit_and_attest_one_enrollment
    """
    fixtures.set_clock(instant(2026, 8, 1))
    rheumatologist = fixtures.create_clinician(
        None, npi="1234567893", full_name="Ada Rheum", can_attest_formulary_exception=True
    )
    drug = fixtures.create_drug(None, factories.infliximab_payload())
    plan = fixtures.create_plan(
        None, factories.meridian_plan_payload(step_therapy_classes_required=[])
    )
    patient = get_success_data(
        api.create_patient(
            factories.create_patient_payload(mrn="RH0001", full_name="Pat One"), ADMIN
        ),
        201,
    )
    episode = get_success_data(
        api.create_therapy_episode(
            factories.create_therapy_episode_payload(
                patient["id"],
                drug["id"],
                plan["id"],
                patient["version"],
                therapy_start_at=instant(2026, 8, 1),
            ),
            make_rheumatologist_headers(rheumatologist["id"]),
        ),
        201,
    )

    enrollment = get_success_data(
        api.create_assistance_enrollment(
            factories.create_assistance_enrollment_payload(
                episode["id"],
                program_type="MANUFACTURER_COPAY_CARD",
                annual_benefit_cents=1_000_000,
                coverage_start=instant(2026, 8, 1),
            ),
            COUNSELOR,
        ),
        201,
    )
    assert enrollment["status"] == "SUBMITTED"
    assert enrollment["submitted_by_user_id"] == COUNSELOR_ALPHA_USER_ID
    submitted_version = enrollment["version"]

    # The submitter attesting their own paperwork.
    validate_error(
        api.attest_enrollment(enrollment["id"], COUNSELOR),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )

    unchanged = get_success_data(api.get_assistance_enrollment(enrollment["id"], ADMIN))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["attested_by_user_id"] is None
    assert unchanged["attested_at"] is None
    assert unchanged["version"] == submitted_version

    attested = get_success_data(api.attest_enrollment(enrollment["id"], COUNSELOR_TWO))
    assert attested["status"] == "ACTIVE"
    assert attested["attested_by_user_id"] == COUNSELOR_BETA_USER_ID
    assertions.assert_instant_equals(
        attested["attested_at"], instant(2026, 8, 1), "attested_at"
    )
    assert attested["version"] == submitted_version + 1

    assertions.assert_instant_equals(
        attested["coverage_end"], instant(2027, 8, 1), "coverage_end"
    )
    assertions.assert_instant_equals(
        attested["reauth_due_at"], instant(2027, 7, 2), "reauth_due_at"
    )
    assertions.assert_money_ledger(attested, used=0, reserved=0, remaining=1_000_000)
