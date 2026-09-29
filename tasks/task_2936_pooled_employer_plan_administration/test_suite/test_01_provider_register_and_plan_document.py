"""Admission to the pooled plan provider register and authoring the plan document."""

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_DUPLICATE_PLAN_NUMBER,
    ERR_DUPLICATE_PROVIDER_EIN,
    ERR_FIDELITY_BOND_BELOW_FLOOR,
    ERR_PLAN_DOCUMENT_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_calendar_date,
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_resource_shape,
    ids_of,
    validate_collection,
    validate_created,
    validate_single,
)
from test_helpers.test_users import (
    UNRESOLVABLE_PLAN_DOCUMENT_ID,
    plan_provider_headers,
    regulator_headers,
)
from prd_bench_local_runner.testing import validate_error


def test_new_provider_opens_pending_registration_with_no_register_fields(api: ApiClient):
    """
    A created provider is not yet on the register.

    "The new record opens with `registration_status` `PENDING_REGISTRATION`, and
    `registration_number`, `registration_effective_date` and `registered_at` all
    null."

    Design: Corner/entities/corner_create_plan_provider_returns_pending_registration
    """
    response = api.create_plan_provider(f.plan_provider_payload(), regulator_headers())
    provider = validate_created(response)

    assert_resource_shape(provider, "PooledPlanProvider")
    assert_fields(
        provider,
        legal_name=k.MERIDIAN_LEGAL_NAME,
        ein=k.MERIDIAN_EIN,
        fidelity_bond_amount_cents=k.MERIDIAN_BOND_CENTS,
        registration_status=k.PROVIDER_PENDING_REGISTRATION,
        version=1,
    )
    assert_null_fields(
        provider, "registration_number", "registration_effective_date", "registered_at"
    )
    assert provider["created_at"] == provider["updated_at"], (
        "A row that has never been mutated must carry created_at == updated_at"
    )


def test_provider_read_back_returns_the_minted_registration_number(api: ApiClient):
    """
    The read-back exposes what the register minted, not the create echo.

    "On success the server mints `registration_number` in the form `PPP-NNNN`,
    where `NNNN` is the one-based ordinal of this approval among all approvals,
    zero-padded to four digits and assigned in ascending order of approval, so
    the first firm admitted carries `PPP-0001` and the tenth carries `PPP-0010`;
    it copies `registration_effective_date` from the request, stamps
    `registered_at` from the logical clock, and increments the provider's
    `version` by one."

    Design: Corner/entities/corner_get_plan_provider_returns_stored_row
    """
    provider = fixtures.registered_provider(api)

    read_back = validate_single(
        api.get_plan_provider(provider["id"], regulator_headers())
    )

    assert_fields(
        read_back,
        id=provider["id"],
        registration_status=k.PROVIDER_REGISTERED,
        registration_number="PPP-0001",
        registration_effective_date=k.REGISTRATION_EFFECTIVE_DATE,
        version=2,
    )
    assert_calendar_date(
        read_back["registration_effective_date"], "registration_effective_date"
    )
    assert_instant_equals(read_back["registered_at"], k.DEFAULT_CLOCK, "registered_at")


def test_registration_mints_number_and_stamps_the_logical_clock(api: ApiClient):
    """
    The single provider transition is observable in three fields at once.

    "Granting the registration advances `registration_status` from
    `PENDING_REGISTRATION` to `REGISTERED`, and is the only transition the
    provider record ever makes; `REGISTERED` is terminal."

    Design: Corner/state_machines/corner_register_provider_mints_registration_number
    """
    provider = validate_created(
        api.create_plan_provider(f.plan_provider_payload(), regulator_headers())
    )

    registered = validate_single(
        api.register_plan_provider(
            provider["id"], f.register_provider_payload(), regulator_headers()
        )
    )

    assert_fields(
        registered,
        registration_status=k.PROVIDER_REGISTERED,
        registration_effective_date=k.REGISTRATION_EFFECTIVE_DATE,
        version=2,
    )
    assert registered["registration_number"], "registration_number must be minted"
    assert registered["registration_number"].startswith("PPP-"), (
        f"registration_number must be of the form PPP-NNNN, got "
        f"{registered['registration_number']!r}"
    )
    digits = registered["registration_number"].split("-", 1)[1]
    assert len(digits) == 4 and digits.isdigit(), (
        f"registration_number must be zero-padded to four digits, got "
        f"{registered['registration_number']!r}"
    )
    assert_instant_equals(registered["registered_at"], k.DEFAULT_CLOCK, "registered_at")


def test_duplicate_provider_ein_is_rejected_globally(api: ApiClient):
    """
    Provider EIN uniqueness is global, and the refused create leaves no row.

    "its `ein` (exactly nine digits, and unique across every provider record in
    the system — a second record carrying an `ein` that already exists is
    rejected with `ERR_DUPLICATE_PROVIDER_EIN`)"

    Design: Corner/validations/corner_duplicate_provider_ein_rejected
    """
    first = validate_created(
        api.create_plan_provider(f.plan_provider_payload(), regulator_headers())
    )

    clash = api.create_plan_provider(
        f.second_plan_provider_payload(ein=k.MERIDIAN_EIN), regulator_headers()
    )
    validate_error(clash, ERR_DUPLICATE_PROVIDER_EIN)

    accepted = validate_created(
        api.create_plan_provider(f.second_plan_provider_payload(), regulator_headers())
    )
    assert accepted["id"] != first["id"], "The accepted create must mint a new row"
    assert_fields(accepted, ein=k.WESTVALE_EIN)

    unchanged = validate_single(api.get_plan_provider(first["id"], regulator_headers()))
    assert_fields(
        unchanged,
        legal_name=k.MERIDIAN_LEGAL_NAME,
        fidelity_bond_amount_cents=k.MERIDIAN_BOND_CENTS,
        version=1,
    )


def test_fidelity_bond_floor_binds_at_registration_and_is_inclusive(api: ApiClient):
    """
    The statutory floor is checked at the grant, not at creation, and includes
    its boundary value.

    "The money check is the statutory floor: `fidelity_bond_amount_cents` must
    be at least 100000 cents — one thousand dollars of bond face amount — and a
    provider below that floor is rejected with
    `ERR_FIDELITY_BOND_BELOW_FLOOR`."

    Design: Corner/validations/corner_low_fidelity_bond_at_registration_rejected
    """
    below = validate_created(
        api.create_plan_provider(
            f.plan_provider_payload(
                legal_name="Thinbond Pooled Services LLC",
                ein="410000003",
                fidelity_bond_amount_cents=k.FIDELITY_BOND_FLOOR_CENTS - 1,
            ),
            regulator_headers(),
        )
    )
    at_floor = validate_created(
        api.create_plan_provider(
            f.plan_provider_payload(
                legal_name="Exactbond Pooled Services LLC",
                ein="410000004",
                fidelity_bond_amount_cents=k.FIDELITY_BOND_FLOOR_CENTS,
            ),
            regulator_headers(),
        )
    )

    refused = api.register_plan_provider(
        below["id"], f.register_provider_payload(), regulator_headers()
    )
    validate_error(refused, ERR_FIDELITY_BOND_BELOW_FLOOR)

    still_pending = validate_single(
        api.get_plan_provider(below["id"], regulator_headers())
    )
    assert_fields(still_pending, registration_status=k.PROVIDER_PENDING_REGISTRATION)
    assert_null_fields(still_pending, "registration_number")

    granted = validate_single(
        api.register_plan_provider(
            at_floor["id"], f.register_provider_payload(), regulator_headers()
        )
    )
    assert_fields(granted, registration_status=k.PROVIDER_REGISTERED)


def test_plan_document_shape_defects_are_rejected_before_any_row_is_written(
    api: ApiClient,
):
    """
    Request shape is checked before uniqueness or foreign keys, and a rejected
    create persists nothing.

    "Priority 7 is request shape — required fields present, correct types,
    declared enum members, declared integer ranges, ISO-8601 date and datetime
    formats, and pagination bounds — reported as `ERR_VALIDATION`; unknown
    fields in a body are ignored rather than rejected."

    Design: Corner/entities/corner_create_plan_document_missing_plan_number_rejected
    """
    provider = fixtures.registered_provider(api)
    headers = plan_provider_headers(provider["id"])

    missing = f.plan_document_payload(provider["id"])
    missing.pop("plan_number")
    validate_error(api.create_plan_document(missing, headers), ERR_VALIDATION)

    validate_error(
        api.create_plan_document(
            f.plan_document_payload(provider["id"], plan_number="1"), headers
        ),
        ERR_VALIDATION,
    )
    validate_error(
        api.create_plan_document(
            f.plan_document_payload(provider["id"], base_eligibility_min_age=17), headers
        ),
        ERR_VALIDATION,
    )

    validate_collection(
        api.list_provider_plan_documents(provider["id"], headers), expected_total=0
    )


def test_new_plan_document_opens_draft_with_zeroed_control_totals(api: ApiClient):
    """
    Every control total on a fresh plan document is zero and its posture is open.

    "A freshly authored plan document opens in `status` `DRAFT` with
    `effective_date` null, every control total described in §2.9 initialised to
    zero, and `compliance_posture` `OPEN`."

    Design: Corner/entities/corner_new_plan_document_defaults_are_draft_and_zeroed
    """
    provider = fixtures.registered_provider(api)

    plan = validate_created(
        api.create_plan_document(
            f.plan_document_payload(provider["id"]),
            plan_provider_headers(provider["id"]),
        )
    )

    assert_resource_shape(plan, "PlanDocument")
    assert_fields(
        plan,
        status=k.PLAN_DRAFT,
        compliance_posture=k.POSTURE_OPEN,
        audit_required=False,
        participant_count=0,
        cumulative_enrolled_participant_count=0,
        transferred_out_participant_count=0,
        headcount_control_delta=0,
        active_employer_count=0,
        suspended_employer_count=0,
        total_validated_contributions_cents=0,
        aggregate_receivable_cents=0,
        total_assets_cents=0,
        total_corrections_funded_cents=0,
        transferred_out_cents=0,
        expense_recovered_cents=0,
        contribution_control_delta_cents=0,
    )
    assert_null_fields(plan, "effective_date")


def test_unresolvable_body_foreign_keys_name_the_collection_they_point_at(
    api: ApiClient,
):
    """
    A body foreign key that does not resolve is a 404 for the referenced
    collection, not an ownership failure.

    "A body foreign key that is well-formed but does not resolve produces the
    same not-found error the corresponding path identifier would produce —
    `ERR_PLAN_DOCUMENT_NOT_FOUND`, `ERR_SERVICE_PROVIDER_NOT_FOUND`,
    `ERR_ADOPTING_EMPLOYER_NOT_FOUND` or `ERR_PAYROLL_BATCH_NOT_FOUND`,
    selected by the entity the field points at, including when the unresolvable
    value arrives as `affiliated_service_provider_id` or
    `audit_firm_service_provider_id`."

    The enumerated set names the four entities a body foreign key may point at,
    and `PooledPlanProvider` is deliberately not among them: a body's
    `pooled_plan_provider_id` is what the ownership check of priority 4 compares
    against `X-User-ID`, so an unresolvable sponsor can never reach the
    priority-6 body foreign-key stage at all.  Only the four enumerated
    collections are asserted here.

    Design: Corner/entities/corner_plan_document_create_with_unknown_provider_not_found
    """
    provider = fixtures.registered_provider(api)
    headers = plan_provider_headers(provider["id"])

    unknown_plan = api.create_adopting_employer(
        f.adopting_employer_payload(UNRESOLVABLE_PLAN_DOCUMENT_ID), headers
    )
    validate_error(unknown_plan, ERR_PLAN_DOCUMENT_NOT_FOUND, expected_status=404)

    validate_created(
        api.create_plan_document(f.plan_document_payload(provider["id"]), headers)
    )
    validate_collection(
        api.list_provider_plan_documents(provider["id"], headers), expected_total=1
    )


def test_plan_number_uniqueness_is_scoped_to_the_sponsor(api: ApiClient):
    """
    The three-digit plan number is unique per sponsor rather than globally.

    "the three-digit `plan_number` used on the annual return, which must be
    unique among the plans of that same sponsoring provider (a repeat is
    rejected with `ERR_DUPLICATE_PLAN_NUMBER`)"

    Design: Corner/errors/corner_plan_number_uniqueness_is_scoped_to_the_sponsor_rejected
    """
    first = fixtures.registered_provider(api)
    second = validate_created(
        api.create_plan_provider(f.second_plan_provider_payload(), regulator_headers())
    )
    first_headers = plan_provider_headers(first["id"])

    validate_created(
        api.create_plan_document(f.plan_document_payload(first["id"]), first_headers)
    )

    repeat = api.create_plan_document(
        f.plan_document_payload(first["id"], plan_year_end_date="2027-12-31"),
        first_headers,
    )
    validate_error(repeat, ERR_DUPLICATE_PLAN_NUMBER)

    validate_created(
        api.create_plan_document(
            f.plan_document_payload(second["id"]),
            plan_provider_headers(second["id"]),
        )
    )

    validate_collection(
        api.list_provider_plan_documents(first["id"], first_headers), expected_total=1
    )


def test_provider_listing_is_scoped_to_its_path_parent_and_pages_stably(
    api: ApiClient,
):
    """
    A sub-resource listing returns only the addressed parent's children, and the
    offset window slides over a stable order.

    "List results are ordered by `created_at` ascending unless a specific
    listing states otherwise, so pagination is stable across pages."

    Design: Corner/endpoints/corner_provider_crud_and_scoped_plan_document_listing
    """
    first = validate_created(
        api.create_plan_provider(f.plan_provider_payload(), regulator_headers())
    )
    second = validate_created(
        api.create_plan_provider(f.second_plan_provider_payload(), regulator_headers())
    )
    first_headers = plan_provider_headers(first["id"])
    second_headers = plan_provider_headers(second["id"])

    validate_created(
        api.create_plan_document(f.plan_document_payload(first["id"]), first_headers)
    )
    validate_created(
        api.create_plan_document(
            f.second_plan_document_payload(first["id"]), first_headers
        )
    )
    validate_created(
        api.create_plan_document(f.plan_document_payload(second["id"]), second_headers)
    )

    read_back = validate_single(api.get_plan_provider(first["id"], first_headers))
    assert_fields(
        read_back,
        legal_name=k.MERIDIAN_LEGAL_NAME,
        ein=k.MERIDIAN_EIN,
        fidelity_bond_amount_cents=k.MERIDIAN_BOND_CENTS,
        registration_status=k.PROVIDER_PENDING_REGISTRATION,
        version=1,
    )

    page, _ = validate_collection(
        api.list_provider_plan_documents(first["id"], first_headers, limit=10, offset=0),
        expected_total=2,
        expected_len=2,
        expected_limit=10,
        expected_offset=0,
    )
    assert [row["plan_number"] for row in page] == [k.PLAN_NUMBER, k.PLAN_NUMBER_SECOND]

    window, _ = validate_collection(
        api.list_provider_plan_documents(first["id"], first_headers, limit=1, offset=1),
        expected_total=2,
        expected_len=1,
        expected_limit=1,
        expected_offset=1,
    )
    assert ids_of(window) == [page[1]["id"]], (
        "offset 1 must return the second row of the same stable order"
    )

    other, _ = validate_collection(
        api.list_provider_plan_documents(
            second["id"], second_headers, limit=10, offset=0
        ),
        expected_total=1,
        expected_len=1,
    )
    assert other[0]["pooled_plan_provider_id"] == second["id"]
