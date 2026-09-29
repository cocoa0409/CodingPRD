"""Existence and header errors: the three sources of an identifier on this API.

An identifier arrives in a path, in a request body, or in the `X-User-Id`
header, and all three have to resolve to the entity-specific error the contract
names. The header family sits above every one of those checks, so it answers
first even for a request that is also wrong in a more obvious way.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ApiErrors,
    CLINICAL_DOCUMENTED,
    assert_encounter_states,
    assert_error,
    assert_error_envelope,
    assert_identity_fields,
    assert_list_meta,
    build_practice,
    compliance_officer_headers,
    create_clinic,
    error_id_of,
    headers_with_empty_user_id,
    insurance_coordinator_headers,
    inventory_manager_headers,
    make_dme_fitter_headers,
    make_headers,
    make_ortho_physician_headers,
    practice_admin_headers,
    read_encounter,
)
from test_helpers import factories as f

# Well-formed identifiers that were never issued by this API.
NO_SUCH_CLINIC = "11111111-1111-4111-8111-111111111111"
NO_SUCH_SUPPLIER = "22222222-2222-4222-8222-222222222222"
NO_SUCH_PRODUCT = "33333333-3333-4333-8333-333333333333"
NO_SUCH_PAR_LEVEL = "44444444-4444-4444-8444-444444444444"
NO_SUCH_ENCOUNTER = "55555555-5555-4555-8555-555555555555"
NO_SUCH_FITTER = "66666666-6666-4666-8666-666666666666"
NO_SUCH_FITTING_RECORD = "77777777-7777-4777-8777-777777777777"
NO_SUCH_FAB_ORDER = "88888888-8888-4888-8888-888888888888"
NO_SUCH_PATIENT = "99999999-9999-4999-8999-999999999999"
NO_SUCH_PHYSICIAN = "99999999-9999-4999-8999-999999999998"
NO_SUCH_PRIOR_AUTH = "99999999-9999-4999-8999-999999999995"
NO_SUCH_ABN_NOTICE = "99999999-9999-4999-8999-999999999994"
NO_SUCH_RETURN = "99999999-9999-4999-8999-999999999993"
NO_SUCH_ACTOR = "99999999-9999-4999-8999-999999999991"
NO_SUCH_PHYSICIAN_ACTOR = "99999999-9999-4999-8999-999999999990"


def test_every_read_that_takes_a_path_id_names_the_entity_it_could_not_find(api):
    """Against a database with nothing in it, each keyed read answers with its own
    entity's identifier rather than a generic 404, and the two reads nested under a
    clinic resolve that parent before they list or compute anything.

    PRD: "The third band is existence, and within it the order is
    `ERR_CLINIC_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_FITTER_NOT_FOUND`,
    `ERR_PAR_LEVEL_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`,
    `ERR_PRIOR_AUTH_NOT_FOUND`, `ERR_ABN_NOTICE_NOT_FOUND`,
    `ERR_FAB_ORDER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`,
    `ERR_FITTING_RECORD_NOT_FOUND`, and then the cross-entity scoping check
    `ERR_CLINIC_SCOPE_MISMATCH`."

    PRD: "A request that targets a physician roster under a clinic id that does not
    exist is answered with `ERR_CLINIC_NOT_FOUND` and never reaches the roster
    lookup"

    Design: Corner/errors/corner_unknown_path_ids_on_read_endpoints_not_found
    """
    assert_error(api.get_clinic(NO_SUCH_CLINIC, practice_admin_headers()),
                 ApiErrors.CLINIC_NOT_FOUND, 404)
    assert_error(api.get_supplier(NO_SUCH_SUPPLIER, inventory_manager_headers()),
                 ApiErrors.SUPPLIER_NOT_FOUND, 404)
    assert_error(api.get_product(NO_SUCH_PRODUCT, inventory_manager_headers()),
                 ApiErrors.PRODUCT_NOT_FOUND, 404)
    assert_error(api.get_par_level(NO_SUCH_PAR_LEVEL, inventory_manager_headers()),
                 ApiErrors.PAR_LEVEL_NOT_FOUND, 404)
    assert_error(api.get_encounter(NO_SUCH_ENCOUNTER, practice_admin_headers()),
                 ApiErrors.ENCOUNTER_NOT_FOUND, 404)

    # The only path-shaped use of the fitter error: elsewhere it reports an
    # unknown acting fitter, and both readings have to stay reachable.
    assert_error(api.get_fitter(NO_SUCH_FITTER, compliance_officer_headers()),
                 ApiErrors.FITTER_NOT_FOUND, 404)
    assert_error(api.get_fitting_record(NO_SUCH_FITTING_RECORD, compliance_officer_headers()),
                 ApiErrors.FITTING_RECORD_NOT_FOUND, 404)
    assert_error(api.get_custom_fab_order(NO_SUCH_FAB_ORDER, inventory_manager_headers()),
                 ApiErrors.FAB_ORDER_NOT_FOUND, 404)

    # A nested list under a missing parent is a 404, not an empty page, and the
    # computed read resolves its clinic before computing a single field.
    roster = api.list_physicians(NO_SUCH_CLINIC, practice_admin_headers())
    assert_error(roster, ApiErrors.CLINIC_NOT_FOUND, 404)
    assert_error_envelope(roster)
    summary = api.get_dispensing_summary(NO_SUCH_CLINIC, practice_admin_headers())
    assert_error(summary, ApiErrors.CLINIC_NOT_FOUND, 404)
    assert_error_envelope(summary)


def test_unresolvable_body_references_and_acting_ids_each_get_their_own_error(api):
    """A create is refused on the first foreign key that does not resolve instead of
    writing a dangling row, and the two acting-identity cases split: an unknown
    fitter on a fitting session is reported as a missing fitter, while an unknown
    physician attesting supervision is reported as a missing actor.

    PRD: "A request naming a `patient_id` that does not resolve is answered with
    `ERR_PATIENT_NOT_FOUND`, and one naming an `ordering_physician_id` that does not
    resolve with `ERR_PHYSICIAN_NOT_FOUND`."

    PRD: "Any request naming a clinic that does not exist — whether by path or by a
    `clinic_id` in the body — is answered with `ERR_CLINIC_NOT_FOUND`."

    PRD: "One carve-out applies: on the two operations that attribute a record to a
    fitter — recording a fitting session and issuing a refit — an unknown fitter
    actor is reported instead as `ERR_FITTER_NOT_FOUND` with HTTP 404, so that the
    more specific diagnosis stays reachable"

    PRD: "If the acting user for either of these two entity-backed roles is not the
    `id` of an existing `Physician` or `Fitter` respectively, the request is
    rejected with `ERR_ACTOR_NOT_FOUND` and HTTP 403."

    Design: Corner/errors/corner_unknown_body_references_and_action_ids_not_found
    """
    practice = build_practice(api, with_shelf=False)
    encounter_id = practice.documented_encounter()

    # Body references on a create.
    assert_error(
        api.create_encounter(
            f.encounter_payload(
                practice.clinic_id, NO_SUCH_PATIENT, practice.product_id,
                practice.ordering_physician_id, 1
            ),
            practice_admin_headers(),
        ),
        ApiErrors.PATIENT_NOT_FOUND,
        404,
    )
    assert_error(
        api.create_encounter(
            f.encounter_payload(
                practice.clinic_id, practice.patient_id, practice.product_id,
                NO_SUCH_PHYSICIAN, 1
            ),
            practice_admin_headers(),
        ),
        ApiErrors.PHYSICIAN_NOT_FOUND,
        404,
    )
    assert_error(
        api.create_par_level(
            f.par_level_payload(NO_SUCH_CLINIC, practice.product_id),
            inventory_manager_headers(),
        ),
        ApiErrors.CLINIC_NOT_FOUND,
        404,
    )
    assert_error(
        api.create_product(f.product_payload(NO_SUCH_SUPPLIER), inventory_manager_headers()),
        ApiErrors.SUPPLIER_NOT_FOUND,
        404,
    )

    # Action ids in a path.
    assert_error(
        api.decide_prior_auth(
            NO_SUCH_PRIOR_AUTH, f.prior_auth_decision_payload(), insurance_coordinator_headers()
        ),
        ApiErrors.PRIOR_AUTH_NOT_FOUND,
        404,
    )
    assert_error(
        api.sign_abn_notice(
            NO_SUCH_ABN_NOTICE, f.abn_signature_payload(), insurance_coordinator_headers()
        ),
        ApiErrors.ABN_NOTICE_NOT_FOUND,
        404,
    )
    assert_error(
        api.inspect_return(NO_SUCH_RETURN, f.inspection_payload(), inventory_manager_headers()),
        ApiErrors.RETURN_NOT_FOUND,
        404,
    )
    assert_error(
        api.create_fabrication_event(
            NO_SUCH_FAB_ORDER, f.fabrication_event_payload("ACCEPT_ORDER"), inventory_manager_headers()
        ),
        ApiErrors.FAB_ORDER_NOT_FOUND,
        404,
    )

    # The acting identity, with the carve-out on one side and not on the other.
    unknown_fitter = api.create_fitting_record(
        encounter_id, f.fitting_record_payload(), make_dme_fitter_headers(NO_SUCH_ACTOR)
    )
    assert_error(unknown_fitter, ApiErrors.FITTER_NOT_FOUND, 404)
    assert error_id_of(unknown_fitter) != ApiErrors.ACTOR_NOT_FOUND

    unknown_physician = api.attest_ioas(
        encounter_id,
        f.ioas_attestation_payload(),
        make_ortho_physician_headers(NO_SUCH_PHYSICIAN_ACTOR),
    )
    assert_error(unknown_physician, ApiErrors.ACTOR_NOT_FOUND, 403)

    # Nothing above was written.
    assert_encounter_states(
        read_encounter(api, encounter_id), clinical_status=CLINICAL_DOCUMENTED
    )
    assert read_encounter(api, encounter_id)["version"] == 2
    assert_list_meta(
        api.list_par_levels(inventory_manager_headers(), {"clinic_id": practice.clinic_id}),
        expected_total=0,
    )
    assert_list_meta(
        api.list_fitting_records(compliance_officer_headers(), {"encounter_id": encounter_id}),
        expected_total=0,
    )


def test_the_two_header_errors_answer_before_existence_and_before_each_other(api):
    """A headerless read of an id that does not exist reports the missing headers and
    not the missing clinic, an invented role is refused whatever the request would
    otherwise have done, an empty header value counts as absent, and a request that
    is missing an id while also carrying a bogus role reports the absence.

    PRD: "If either header is absent or present but empty, the request is rejected
    with `ERR_MISSING_AUTH_HEADERS` and HTTP 401. If `X-User-Role` carries a value
    that is not one of the six declared roles, the request is rejected with
    `ERR_UNKNOWN_ROLE`, also HTTP 401."

    PRD: "The first band is authentication and authorization:
    `ERR_MISSING_AUTH_HEADERS`, then `ERR_UNKNOWN_ROLE`, then `ERR_UNAUTHORIZED`,
    then `ERR_ACTOR_NOT_FOUND`."

    Design: Corner/errors/corner_auth_header_family_rejected_before_everything_else
    """
    clinic = create_clinic(api)
    no_headers = {"Content-Type": "application/json"}

    assert_error(
        api.raw("GET", "/dme/clinics/{}".format(clinic["id"]), None, no_headers),
        ApiErrors.MISSING_AUTH_HEADERS,
        401,
    )

    # An empty value is treated as absence, not as an unknown acting user.
    assert_error(
        api.raw("GET", "/dme/clinics/{}".format(clinic["id"]), None, headers_with_empty_user_id()),
        ApiErrors.MISSING_AUTH_HEADERS,
        401,
    )

    # Priority 1 precedes every existence check.
    beats_404 = api.raw("GET", "/dme/clinics/{}".format(NO_SUCH_CLINIC), None, no_headers)
    assert_error(beats_404, ApiErrors.MISSING_AUTH_HEADERS, 401)
    assert error_id_of(beats_404) != ApiErrors.CLINIC_NOT_FOUND

    # A role outside the six declared ones is refused, and the six are matched
    # exactly, so a lower-cased spelling is not one of them.
    assert_error(
        api.get_clinic(clinic["id"], make_headers("SupplyChainIntern", NO_SUCH_ACTOR)),
        ApiErrors.UNKNOWN_ROLE,
        401,
    )
    lower_cased = api.create_clinic(
        f.clinic_payload(name="Ghost Ortho"), make_headers("practiceadmin", NO_SUCH_ACTOR)
    )
    assert_error(lower_cased, ApiErrors.UNKNOWN_ROLE, 401)

    # Presence is decided before membership.
    missing_and_bogus = api.raw(
        "GET",
        "/dme/clinics/{}".format(clinic["id"]),
        None,
        {"X-User-Role": "SupplyChainIntern", "Content-Type": "application/json"},
    )
    assert_error(missing_and_bogus, ApiErrors.MISSING_AUTH_HEADERS, 401)
    assert error_id_of(missing_and_bogus) != ApiErrors.UNKNOWN_ROLE

    # None of the rejected requests left a trace: the one real clinic still reads.
    survivor = validate_success(api.get_clinic(clinic["id"], practice_admin_headers()), 200)
    assert survivor["id"] == clinic["id"]
    assert survivor["name"] == clinic["name"]
    assert_identity_fields(survivor, expected_version=1)
