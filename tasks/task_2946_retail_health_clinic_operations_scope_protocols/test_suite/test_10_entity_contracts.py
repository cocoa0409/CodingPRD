"""Entity contracts: declared inputs echoed back, declared defaults applied,
system housekeeping stamped by the server, and the named refusals a bad
reference or a bad enum member earns.
"""
from test_helpers import (
    CLINIC_CLOSED,
    CLOCK_START,
    COMPLAINT_RASH,
    COMPLAINT_UTI,
    CREDENTIAL_NP,
    CREDENTIAL_PA,
    NON_EXISTENT_UUID,
    PHYSICIAN_ACTIVE,
    QUEUE_WAITING,
    ApiErrorId,
    add_walk_in,
    assert_clinic,
    assert_freshly_created,
    assert_instant_equal,
    assert_page,
    assert_patient,
    assert_queue_entry,
    assert_response_type,
    assert_state_rule,
    clinician_payload,
    create_clinic,
    create_clinician,
    create_patient,
    create_physician,
    create_state_rule,
    error_id,
    make_admin_headers,
    protocol_payload,
    read_clinic,
    read_clinician,
    read_patient,
    read_physician,
    read_queue_entry,
    staffed_clinic,
    state_rule_payload,
    validate_error,
    validate_paginated,
    validate_success,
    walk_in_payload,
)

# A complaint deliberately outside the six-member vocabulary the PRD declares.
UNKNOWN_COMPLAINT_CODE = "TOOTHACHE"

CA_RULE = {
    "state_code": "CA",
    "chart_review_sample_pct": 40,
    "review_deadline_hours": 72,
    "collaborating_physician_required": True,
    "min_independent_practice_age_months": 24,
    "controlled_rx_allowed": False,
    "max_supervised_clinicians_per_physician": 3,
}


def _register_california(api):
    """POST the seven oversight inputs for CA and hand back the raw response."""
    return api.create_state_rule(state_rule_payload(**CA_RULE), make_admin_headers())


def test_registering_a_state_echoes_all_seven_oversight_inputs(api):
    """Every declared input comes back on the created row exactly as supplied.

    PRD: "Registering the oversight rules for a state supplies a `state_code` of exactly
    two uppercase letters, a `chart_review_sample_pct` between 0 and 100 inclusive, a
    `review_deadline_hours` of at least 1, the boolean `collaborating_physician_required`,
    a `min_independent_practice_age_months` of 0 or more, the boolean
    `controlled_rx_allowed`, and a `max_supervised_clinicians_per_physician` of at least
    1."

    Design: Corner/entities/corner_state_rule_creation_echoes_every_declared_field
    """
    response = _register_california(api)

    rule = validate_success(response, 201)
    assert_state_rule(rule)
    assert rule["state_code"] == "CA"
    assert rule["chart_review_sample_pct"] == 40
    assert rule["review_deadline_hours"] == 72
    assert rule["collaborating_physician_required"] is True
    assert rule["min_independent_practice_age_months"] == 24
    assert rule["controlled_rx_allowed"] is False
    assert rule["max_supervised_clinicians_per_physician"] == 3


def test_a_newly_registered_state_rule_starts_at_version_one(api):
    """The four housekeeping fields are the server's, and version begins at 1.

    PRD: "`version` is an integer that begins at 1 when the row is created and increases
    by exactly 1 on every mutation of that row, including mutations the server performs
    on its own initiative as part of a cascade rather than in response to a client
    request naming that row."

    Design: Corner/entities/corner_state_rule_creation_echoes_every_declared_field
    """
    rule = validate_success(_register_california(api), 201)

    assert rule["version"] == 1
    assert_freshly_created(rule)


def test_the_state_rule_creation_answers_in_a_single_object_envelope(api):
    """A create answers 201 with meta identifiers and a single-resource envelope.

    PRD: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/entities/corner_state_rule_creation_echoes_every_declared_field
    """
    response = _register_california(api)

    assert response.status_code == 201
    assert_response_type(response, "object")
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert isinstance(meta["api_request_timestamp"], str) and meta["api_request_timestamp"]


def _clinic_at_rest(api):
    """A CA site with a floor of two, nobody rostered and nobody waiting."""
    create_state_rule(api, **CA_RULE)
    return create_clinic(api, name="CA Store 20", state_code="CA",
                         min_clinicians_required=2, appointment_slots_per_hour=3,
                         walk_in_queue_capacity=4)


def test_reading_a_clinic_returns_its_stored_inputs_unchanged(api):
    """The three capacity settings and the name survive the round trip.

    PRD: "Opening a clinic supplies its `name`, its `state_code`, a
    `min_clinicians_required` that defaults to 1 when omitted and must be at least 1, an
    `appointment_slots_per_hour` of at least 1, and a `walk_in_queue_capacity` of at
    least 1."

    Design: Corner/entities/corner_clinic_retrieval_returns_inputs_and_derived_counters
    """
    created = _clinic_at_rest(api)

    clinic = read_clinic(api, created["id"])

    assert_clinic(clinic)
    assert clinic["name"] == "CA Store 20"
    assert clinic["state_code"] == "CA"
    assert clinic["min_clinicians_required"] == 2
    assert clinic["appointment_slots_per_hour"] == 3
    assert clinic["walk_in_queue_capacity"] == 4


def test_a_fresh_clinic_reports_every_operational_reading_at_rest(api):
    """Five server-derived readings, four at zero and the realized wait still null.

    PRD: "The site's operational readings are all server-derived and start at rest:
    `on_duty_clinician_count` at 0, `open_status` at `CLOSED`, `waiting_count` at 0,
    `posted_wait_minutes` at 0, and `last_realized_wait_minutes` null, since no patient
    has yet been called and there is therefore no realized wait to report."

    Design: Corner/entities/corner_clinic_retrieval_returns_inputs_and_derived_counters
    """
    created = _clinic_at_rest(api)

    clinic = read_clinic(api, created["id"])

    assert clinic["open_status"] == CLINIC_CLOSED
    assert clinic["on_duty_clinician_count"] == 0
    assert clinic["waiting_count"] == 0
    assert clinic["posted_wait_minutes"] == 0
    assert clinic["last_realized_wait_minutes"] is None


def _three_walk_ins_waiting(api):
    """One OPEN CA site with a single clinician on duty and three adults waiting."""
    env = staffed_clinic(api, state=CA_RULE,
                         clinic={"name": "CA Store 21", "min_clinicians_required": 1,
                                 "appointment_slots_per_hour": 2,
                                 "walk_in_queue_capacity": 5})
    for name, dob in (("Page One", "1990-01-01"), ("Page Two", "1990-02-01"),
                      ("Page Three", "1990-03-01")):
        patient = create_patient(api, env["front_desk"], full_name=name,
                                 date_of_birth=dob)
        add_walk_in(api, env, patient["id"])
    return env


def test_the_first_page_of_waiting_entries_reports_the_unpaginated_total(api):
    """Two rows come back, but the total counts all three matches and more remain.

    PRD: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside
    the `meta` object of the envelope. The `total_count` reflects the number of rows
    matching the request's filters before pagination is applied, and `has_more` is true
    exactly when rows remain beyond the current window."

    Design: Corner/entities/corner_queue_entries_listing_paginates_with_total_count_and_has_more
    """
    env = _three_walk_ins_waiting(api)

    response = api.list_queue_entries(
        env["admin"], params={"clinic_id": env["clinic_id"], "status": QUEUE_WAITING,
                              "limit": 2, "offset": 0})

    rows, meta = validate_paginated(response)
    assert_response_type(response, "array")
    assert len(rows) == 2
    assert_page(meta, total_count=3, has_more=True, limit=2, offset=0)


def test_the_second_page_carries_the_remainder_and_reports_no_more(api):
    """Skipping two of three leaves exactly one row and closes the window.

    PRD: "The `total_count` reflects the number of rows matching the request's filters
    before pagination is applied, and `has_more` is true exactly when rows remain beyond
    the current window."

    Design: Corner/entities/corner_queue_entries_listing_paginates_with_total_count_and_has_more
    """
    env = _three_walk_ins_waiting(api)

    response = api.list_queue_entries(
        env["admin"], params={"clinic_id": env["clinic_id"], "status": QUEUE_WAITING,
                              "limit": 2, "offset": 2})

    rows, meta = validate_paginated(response)
    assert len(rows) == 1
    assert_page(meta, total_count=3, has_more=False, limit=2, offset=2)


def test_reading_a_visit_that_never_existed_names_the_missing_visit(api):
    """A well-formed but unknown path id is a 404 that says which type is absent.

    PRD: "Every identifier embedded in the URL must resolve to an existing row, and path
    identifiers are validated left to right so that the outermost container is confirmed
    before anything nested inside it."

    Design: Corner/entities/corner_visit_retrieval_with_unknown_id_returns_visit_not_found
    """
    response = api.get_visit(NON_EXISTENT_UUID, make_admin_headers())

    validate_error(response, ApiErrorId.ERR_VISIT_NOT_FOUND, 404)
    assert error_id(response) == "ERR_VISIT_NOT_FOUND"
    assert_response_type(response, "error")


def _clinician_registration_without_a_supervisor(api):
    """A CA site exists and resolves; the supervising physician is simply absent."""
    create_state_rule(api, **CA_RULE)
    clinic = create_clinic(api, name="CA Store 22", state_code="CA",
                           min_clinicians_required=1, appointment_slots_per_hour=2,
                           walk_in_queue_capacity=5)
    payload = {
        "full_name": "NP Nameless",
        "credential": CREDENTIAL_NP,
        "license_state_code": "CA",
        "home_clinic_id": clinic["id"],
    }
    return clinic, api.create_clinician(payload, make_admin_headers())


def test_registering_a_clinician_with_no_supervising_physician_is_a_shape_failure(api):
    """The reference that is present resolves; the one that is missing is required.

    PRD: "Unknown body fields are rejected, required fields must be present, types and
    enum members must be valid, integers declared non-negative must be non-negative,
    `limit` must lie between 1 and 100 inclusive and `offset` must be 0 or greater."

    Design: Corner/entities/corner_clinician_creation_missing_supervising_physician_returns_validation
    """
    _clinic, response = _clinician_registration_without_a_supervisor(api)

    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)
    assert error_id(response) == "ERR_VALIDATION"


def test_the_refused_clinician_registration_persists_no_row_at_that_clinic(api):
    """A request-shape refusal writes nothing, so the site's roster stays empty.

    PRD: "Clinicians — the nurse practitioners and physician assistants who actually see
    patients — are registered with a `full_name`, a `credential` of either `NP` or `PA`,
    a single `license_state_code`, a `home_clinic_id` naming the site they normally work,
    and a `supervising_physician_id` naming the collaborating physician who will be
    pinned onto their shifts by default."

    Design: Corner/entities/corner_clinician_creation_missing_supervising_physician_returns_validation
    """
    clinic, _response = _clinician_registration_without_a_supervisor(api)

    rows, meta = validate_paginated(
        api.list_clinicians(make_admin_headers(),
                            params={"home_clinic_id": clinic["id"]}))

    assert meta["total_count"] == 0
    assert rows == []


def _clinician_registered_with_only_the_required_inputs(api):
    """A PA registered with no float flag, under a physician with no status supplied."""
    create_state_rule(api, **CA_RULE)
    clinic = create_clinic(api, name="CA Store 23", state_code="CA",
                           min_clinicians_required=1, appointment_slots_per_hour=2,
                           walk_in_queue_capacity=5)
    physician = create_physician(api, full_name="Dr Ruth", licensed_state_codes=["CA"],
                                max_supervised_clinicians=3)
    clinician = create_clinician(api, clinic["id"], physician["id"],
                                 full_name="NP Default", credential=CREDENTIAL_PA,
                                 license_state_code="CA")
    return {"clinic": clinic, "physician": physician, "clinician": clinician}


def test_a_clinician_registered_without_the_float_flag_is_not_float_eligible(api):
    """The omitted optional flag reads back as false, never as null.

    PRD: "The optional `float_eligible` flag defaults to false; when true, the clinician
    becomes a candidate for covering shifts at other sites in the same state."

    Design: Corner/entities/corner_clinician_creation_omitting_float_eligible_applies_false_default
    """
    env = _clinician_registered_with_only_the_required_inputs(api)

    clinician = read_clinician(api, env["clinician"]["id"])

    assert clinician["float_eligible"] is False
    assert clinician["credential"] == CREDENTIAL_PA


def test_a_new_clinician_carries_no_scope_hold_and_no_active_shifts(api):
    """Both server-maintained readings start at their declared rest values.

    PRD: "A new clinician's `scope_hold` is false and their `active_assignment_count` is
    0."

    Design: Corner/entities/corner_clinician_creation_omitting_float_eligible_applies_false_default
    """
    env = _clinician_registered_with_only_the_required_inputs(api)

    clinician = read_clinician(api, env["clinician"]["id"])

    assert clinician["scope_hold"] is False
    assert clinician["active_assignment_count"] == 0


def test_a_physician_registered_without_a_status_is_active(api):
    """The other omitted optional on this setup path also takes its declared default.

    PRD: "Collaborating physicians are registered with a `full_name`, a non-empty
    `licensed_state_codes` array, a `max_supervised_clinicians` of at least 1, and an
    optional `status` that is `ACTIVE` when omitted and may otherwise be `INACTIVE`."

    Design: Corner/entities/corner_clinician_creation_omitting_float_eligible_applies_false_default
    """
    env = _clinician_registered_with_only_the_required_inputs(api)

    physician = read_physician(api, env["physician"]["id"])

    assert physician["status"] == PHYSICIAN_ACTIVE


def _minimally_registered_patient(api):
    """Only the two required inputs: a name and a date of birth."""
    return create_patient(api, full_name="Minimal Mary", date_of_birth="1994-04-04")


def test_a_patient_registered_with_no_insurance_details_has_them_all_null(api):
    """Both payer columns stay null, which is what puts her on the self-pay path.

    PRD: "A patient with no `payer_name` on file has no coverage and will be priced on
    the self-pay path."

    Design: Corner/entities/corner_patient_creation_omitting_pcp_fields_applies_declared_defaults
    """
    patient = read_patient(api, _minimally_registered_patient(api)["id"])

    assert_patient(patient)
    assert patient["payer_name"] is None
    assert patient["member_id"] is None


def test_a_patient_registered_with_no_pcp_details_has_nulls_and_false_consents(api):
    """The two PCP strings default to null and the two PCP booleans to false.

    PRD: "Insurance and primary-care details are all optional and default to null or
    false: `payer_name` names the insurer and `member_id` the identifier under it, where a
    `member_id` is required whenever a `payer_name` is supplied and its absence in that
    case is a request-shape failure answered with `ERR_VALIDATION`; `pcp_name` records the
    primary care provider; `pcp_direct_address` records the direct-messaging address or
    fax number for that provider; `pcp_accepts_electronic_summary` records whether the
    provider takes electronic delivery; and `pcp_consent_on_file` records the patient's
    consent to disclose visit information to their provider, without which no summary is
    ever produced."

    Design: Corner/entities/corner_patient_creation_omitting_pcp_fields_applies_declared_defaults
    """
    patient = read_patient(api, _minimally_registered_patient(api)["id"])

    assert patient["pcp_name"] is None
    assert patient["pcp_direct_address"] is None
    assert patient["pcp_accepts_electronic_summary"] is False
    assert patient["pcp_consent_on_file"] is False


def test_a_new_patient_holds_no_therapy_locks_and_owes_nothing(api):
    """The three system-maintained readings start empty, not null.

    PRD: "Three readings are maintained by the system and start empty:
    `active_therapy_classes`, the array of therapy classes the patient currently holds
    locked; `active_therapy_class_count`, its length; and `outstanding_balance_cents` at
    0."

    Design: Corner/entities/corner_patient_creation_omitting_pcp_fields_applies_declared_defaults
    """
    patient = read_patient(api, _minimally_registered_patient(api)["id"])

    assert patient["active_therapy_classes"] == []
    assert patient["active_therapy_class_count"] == 0
    assert patient["outstanding_balance_cents"] == 0


def test_a_created_patient_carries_a_server_minted_identity_at_version_one(api):
    """The client supplied no id, so the row's identity is entirely the server's.

    PRD: "`id` is a server-minted UUID with no type prefix — clients never supply it."

    Design: Corner/entities/corner_patient_creation_stamps_system_identity_and_version
    """
    patient = create_patient(api, full_name="Stamp Sam", date_of_birth="1970-10-10")

    assert_freshly_created(patient)
    assert patient["version"] == 1
    assert "_" not in patient["id"]


def test_a_created_patient_is_stamped_with_the_logical_clock(api):
    """Nothing has moved the clock, so both housekeeping stamps read its start value.

    PRD: "Before any client moves it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/entities/corner_patient_creation_stamps_system_identity_and_version
    """
    patient = create_patient(api, full_name="Stamp Sam", date_of_birth="1970-10-10")

    assert_instant_equal(patient["created_at"], CLOCK_START)
    assert_instant_equal(patient["updated_at"], CLOCK_START)


def test_the_minted_patient_id_addresses_the_row_on_a_later_read(api):
    """The id the create answered with is the one the single-resource read honours.

    PRD: "Requests that create a new resource answer with HTTP 201 and the created row in
    the envelope's `data` field; requests that modify or transition an existing resource
    answer with HTTP 200 and the updated row; reads answer with HTTP 200."

    Design: Corner/entities/corner_patient_creation_stamps_system_identity_and_version
    """
    created = create_patient(api, full_name="Stamp Sam", date_of_birth="1970-10-10")

    fetched = read_patient(api, created["id"])

    assert fetched["id"] == created["id"]
    assert fetched["full_name"] == "Stamp Sam"
    assert fetched["date_of_birth"] == "1970-10-10"


def _walk_in_on_a_tier_three_protocol(api):
    """A RASH protocol declared tier 3 in CA, and one adult admitted against it."""
    env = staffed_clinic(
        api, state=CA_RULE,
        protocol={"complaint_code": COMPLAINT_RASH, "min_age_months": 12,
                  "max_age_months": 1200, "base_price_cents": 7500,
                  "acuity_tier": 3, "red_flag_codes": ["PETECHIAE"],
                  "max_heart_rate_bpm": 130},
        clinic={"name": "CA Store 24", "min_clinicians_required": 1,
                "appointment_slots_per_hour": 2, "walk_in_queue_capacity": 5})
    patient = create_patient(api, env["front_desk"], full_name="Rita Rash",
                             date_of_birth="1989-09-09")
    env["patient"] = patient
    env["entry"] = add_walk_in(api, env, patient["id"],
                               complaint_code=COMPLAINT_RASH)
    return env


def test_a_walk_in_copies_its_acuity_tier_from_the_governing_protocol(api):
    """The client never sends acuity; the tier-3 protocol for RASH supplies it.

    PRD: "The entry's `acuity_tier` is not supplied by the client: it is copied from the
    protocol whose `complaint_code` equals the entry's complaint and whose
    `allowed_state_codes` contains the clinic's `state_code`."

    Design: Corner/entities/corner_queue_entry_acuity_tier_is_taken_from_the_protocol
    """
    env = _walk_in_on_a_tier_three_protocol(api)

    entry = read_queue_entry(api, env["entry"]["id"])

    assert_queue_entry(entry)
    assert entry["complaint_code"] == COMPLAINT_RASH
    assert entry["acuity_tier"] == 3
    assert entry["status"] == QUEUE_WAITING


def test_a_freshly_admitted_walk_in_scores_only_its_acuity_points(api):
    """No punctuality bonus, no accrued waiting and no age bump leaves 300.

    PRD: "**Acuity** contributes 100 points per tier, so a routine tier-1 complaint earns
    100, a symptomatic tier-2 earns 200 and a high-acuity tier-3 earns 300.
    **Punctuality** contributes a flat 250 points when the entry's `kind` is
    `APPOINTMENT`, its `arrived_at` is set, and that arrival instant is no later than its
    `scheduled_at` plus 10 minutes of grace; a walk-in, an un-arrived appointment, or an
    appointment that arrived more than 10 minutes late contributes 0 from this component."

    Design: Corner/entities/corner_queue_entry_acuity_tier_is_taken_from_the_protocol
    """
    env = _walk_in_on_a_tier_three_protocol(api)

    entry = read_queue_entry(api, env["entry"]["id"])

    assert entry["priority_score"] == 300


def test_a_freshly_admitted_walk_in_carries_an_arrival_but_no_call_or_slot(api):
    """Arrival is stamped at intake while the call-side readings stay null.

    PRD: "Inside the same request the entry advances `SCHEDULED → WAITING`, its
    `arrived_at` is stamped with the logical clock, its `priority_score` is computed, the
    clinic's `waiting_count` rises by 1 and `posted_wait_minutes` is recomputed from the
    new depth."

    Design: Corner/entities/corner_queue_entry_acuity_tier_is_taken_from_the_protocol
    """
    env = _walk_in_on_a_tier_three_protocol(api)

    entry = read_queue_entry(api, env["entry"]["id"])

    assert_instant_equal(entry["arrived_at"], CLOCK_START)
    assert entry["called_at"] is None
    assert entry["realized_wait_minutes"] is None
    assert entry["scheduled_at"] is None


def _protocol_attempt(api, **overrides):
    """POST /protocols with one field deliberately outside its declared domain."""
    payload = protocol_payload(red_flag_codes=[], **overrides)
    return api.create_protocol(payload, make_admin_headers())


def _protocol_catalogue(api):
    """The whole protocol collection, as the discovery list reports it."""
    return validate_paginated(api.list_protocols(make_admin_headers()))


def test_registering_a_protocol_for_an_undeclared_complaint_is_rejected(api):
    """`complaint_code` is a closed six-member enum and TOOTHACHE is not in it.

    PRD: "A protocol declares its `complaint_code`, which is one of `SORE_THROAT`,
    `EAR_PAIN`, `UTI`, `RASH`, `FLU_LIKE` or `SPORTS_PHYSICAL`; an age band given as
    `min_age_months` (0 or more) and `max_age_months` (which must be strictly greater than
    `min_age_months`); a `base_price_cents` greater than 0, which serves both as the
    payer-allowed amount and as the self-pay list price for the base visit; an
    `acuity_tier` of 1 for routine, 2 for symptomatic or 3 for high-acuity care;
    `red_flag_codes`, a possibly-empty array of finding codes that force an
    emergency-department referral; three vital-sign boundaries in the form of `max_temp_c`
    (a Celsius temperature carried to one decimal place), `max_heart_rate_bpm` and
    `min_spo2_pct`; the boolean `requires_cosign`; and a non-empty `allowed_state_codes`
    array of two-letter codes naming the states where the protocol may be delivered."

    Design: Corner/entities/corner_protocol_creation_with_unknown_complaint_code_returns_validation
    """
    response = _protocol_attempt(api, complaint_code=UNKNOWN_COMPLAINT_CODE)

    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)
    assert error_id(response) == "ERR_VALIDATION"


def test_the_rejected_protocol_leaves_the_catalogue_empty(api):
    """A request-shape refusal is decided before anything is written.

    PRD: "Unknown body fields are rejected, required fields must be present, types and
    enum members must be valid, integers declared non-negative must be non-negative,
    `limit` must lie between 1 and 100 inclusive and `offset` must be 0 or greater."

    Design: Corner/entities/corner_protocol_creation_with_unknown_complaint_code_returns_validation
    """
    _protocol_attempt(api, complaint_code=UNKNOWN_COMPLAINT_CODE)

    rows, meta = _protocol_catalogue(api)

    assert meta["total_count"] == 0
    assert rows == []


def test_a_protocol_whose_max_age_only_equals_its_min_age_is_rejected(api):
    """The age band must be strictly widening, so 240 against 240 is not a band.

    PRD: "A protocol declares its `complaint_code`, which is one of `SORE_THROAT`,
    `EAR_PAIN`, `UTI`, `RASH`, `FLU_LIKE` or `SPORTS_PHYSICAL`; an age band given as
    `min_age_months` (0 or more) and `max_age_months` (which must be strictly greater than
    `min_age_months`); a `base_price_cents` greater than 0, which serves both as the
    payer-allowed amount and as the self-pay list price for the base visit; an
    `acuity_tier` of 1 for routine, 2 for symptomatic or 3 for high-acuity care;
    `red_flag_codes`, a possibly-empty array of finding codes that force an
    emergency-department referral; three vital-sign boundaries in the form of `max_temp_c`
    (a Celsius temperature carried to one decimal place), `max_heart_rate_bpm` and
    `min_spo2_pct`; the boolean `requires_cosign`; and a non-empty `allowed_state_codes`
    array of two-letter codes naming the states where the protocol may be delivered."

    Design: Corner/entities/corner_protocol_creation_with_max_age_not_above_min_age_returns_validation
    """
    response = _protocol_attempt(api, complaint_code=COMPLAINT_UTI, min_age_months=240,
                                 max_age_months=240, base_price_cents=12000)

    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)
    assert _protocol_catalogue(api)[1]["total_count"] == 0


def test_a_protocol_with_an_acuity_tier_above_three_is_rejected(api):
    """Acuity is a three-member domain, so a fourth tier is a shape failure too.

    PRD: "A protocol declares its `complaint_code`, which is one of `SORE_THROAT`,
    `EAR_PAIN`, `UTI`, `RASH`, `FLU_LIKE` or `SPORTS_PHYSICAL`; an age band given as
    `min_age_months` (0 or more) and `max_age_months` (which must be strictly greater than
    `min_age_months`); a `base_price_cents` greater than 0, which serves both as the
    payer-allowed amount and as the self-pay list price for the base visit; an
    `acuity_tier` of 1 for routine, 2 for symptomatic or 3 for high-acuity care;
    `red_flag_codes`, a possibly-empty array of finding codes that force an
    emergency-department referral; three vital-sign boundaries in the form of `max_temp_c`
    (a Celsius temperature carried to one decimal place), `max_heart_rate_bpm` and
    `min_spo2_pct`; the boolean `requires_cosign`; and a non-empty `allowed_state_codes`
    array of two-letter codes naming the states where the protocol may be delivered."

    Design: Corner/entities/corner_protocol_creation_with_max_age_not_above_min_age_returns_validation
    """
    response = _protocol_attempt(api, complaint_code=COMPLAINT_UTI, min_age_months=24,
                                 max_age_months=1200, base_price_cents=12000,
                                 acuity_tier=4)

    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)
    assert _protocol_catalogue(api)[1]["total_count"] == 0


def _clinician_registration_naming_a_missing_clinic(api):
    """The supervising physician resolves; the home clinic id points at nothing."""
    physician = create_physician(api, full_name="Dr Tull", licensed_state_codes=["CA"],
                                max_supervised_clinicians=3)
    payload = clinician_payload(NON_EXISTENT_UUID, physician["id"],
                               full_name="NP Orphan", credential=CREDENTIAL_NP,
                               license_state_code="CA")
    return physician, api.create_clinician(payload, make_admin_headers())


def test_a_clinician_naming_an_unresolvable_home_clinic_is_a_missing_clinic(api):
    """The body reference that fails is the clinic, so the clinic is what the 404 names.

    PRD: "Every foreign reference carried in a request body must resolve to an existing
    row, checked in the order the fields are declared for that endpoint, and the refusal
    is the matching 404 from the same list."

    Design: Corner/entities/corner_clinician_creation_with_unknown_home_clinic_returns_clinic_not_found
    """
    _physician, response = _clinician_registration_naming_a_missing_clinic(api)

    validate_error(response, ApiErrorId.ERR_CLINIC_NOT_FOUND, 404)
    assert error_id(response) == "ERR_CLINIC_NOT_FOUND"


def test_the_physician_named_beside_the_missing_clinic_gains_no_supervision_load(api):
    """The valid half of the request is not half-applied: the load stays at zero.

    PRD: "A physician's `current_supervised_count` starts at 0 and is thereafter
    maintained by the system."

    Design: Corner/entities/corner_clinician_creation_with_unknown_home_clinic_returns_clinic_not_found
    """
    physician, _response = _clinician_registration_naming_a_missing_clinic(api)

    assert read_physician(api, physician["id"])["current_supervised_count"] == 0


def _walk_in_naming_a_missing_patient(api):
    """An OPEN CA clinic with room to spare, and a patient id that resolves to nothing."""
    env = staffed_clinic(api, state=CA_RULE,
                         clinic={"name": "CA Store 26", "min_clinicians_required": 1,
                                 "appointment_slots_per_hour": 2,
                                 "walk_in_queue_capacity": 5})
    payload = walk_in_payload(env["clinic_id"], NON_EXISTENT_UUID)
    env["response"] = api.create_queue_entry(payload, env["front_desk"])
    return env


def test_a_walk_in_naming_an_unresolvable_patient_is_a_missing_patient(api):
    """The clinic resolves and the complaint is offered; only the patient is absent.

    PRD: "This rung governs clinician registration, staffing creation, float coverage,
    queue intake, visit creation, assessment creation and prescription creation."

    Design: Corner/entities/corner_queue_entry_creation_with_unknown_patient_returns_patient_not_found
    """
    env = _walk_in_naming_a_missing_patient(api)

    validate_error(env["response"], ApiErrorId.ERR_PATIENT_NOT_FOUND, 404)
    assert error_id(env["response"]) == "ERR_PATIENT_NOT_FOUND"


def test_the_refused_intake_leaves_the_clinic_queue_readings_at_zero(api):
    """No admission happened, so neither the depth nor the projection moved.

    PRD: "Inside the same request the entry advances `SCHEDULED → WAITING`, its
    `arrived_at` is stamped with the logical clock, its `priority_score` is computed, the
    clinic's `waiting_count` rises by 1 and `posted_wait_minutes` is recomputed from the
    new depth."

    Design: Corner/entities/corner_queue_entry_creation_with_unknown_patient_returns_patient_not_found
    """
    env = _walk_in_naming_a_missing_patient(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["waiting_count"] == 0
    assert clinic["posted_wait_minutes"] == 0
