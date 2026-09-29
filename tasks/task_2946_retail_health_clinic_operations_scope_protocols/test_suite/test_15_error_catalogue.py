"""Every refusal must name its own code, and competing refusals must name the higher rung."""
from test_helpers import (
    ASSESSMENT_COSIGNED,
    ASSESSMENT_REFERRAL_REQUIRED,
    ASSIGNMENT_ACTIVE,
    ASSIGNMENT_CANCELLED,
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_SCHEDULED,
    CLINIC_CLOSED,
    CLINIC_OPEN,
    COMPLAINT_EAR_PAIN,
    COMPLAINT_SORE_THROAT,
    COMPLAINT_UTI,
    CREDENTIAL_PA,
    NON_EXISTENT_UUID,
    OUTCOME_WITHIN_SCOPE,
    PHYSICIAN_INACTIVE,
    PRESCRIPTION_DRAFT,
    QUEUE_CALLED,
    QUEUE_SCHEDULED,
    QUEUE_SERVED,
    QUEUE_WAITING,
    REVIEW_ATTESTED,
    REVIEW_PENDING,
    THERAPY_ANTIBIOTIC_BETA_LACTAM,
    THERAPY_CONTROLLED_OPIOID,
    VALID_PHARMACY_NPI,
    VISIT_REFERRED,
    VISIT_TREATED,
    ApiErrorId,
    add_walk_in,
    appointment_payload,
    call_next,
    clinic_payload,
    closed_insured_visit,
    cosign_assessment,
    create_assignment,
    create_clinic,
    create_clinician,
    create_insured_patient,
    create_patient,
    create_physician,
    create_protocol,
    create_state_rule,
    error_id,
    make_admin_headers,
    prescription_payload,
    protocol_payload,
    read_chart_review,
    read_clinic,
    read_clinician,
    read_patient,
    read_physician,
    read_queue_entry,
    read_visit,
    run_sampling,
    set_clock,
    staffed_clinic,
    staffing_assignment_payload,
    start_visit,
    state_rule_payload,
    treated_visit,
    validate_error,
    validate_paginated,
    validate_success,
    walk_in_payload,
)

# ---------------------------------------------------------------------------
# corner_unknown_identifier_probes_return_the_entity_specific_not_found
# ---------------------------------------------------------------------------


def _reference_data_only(api):
    """A CA rule and one real protocol, so no 404 can be blamed on empty tables."""
    admin = make_admin_headers()
    create_state_rule(api, admin)
    protocol = create_protocol(api, admin)
    return {"admin": admin, "protocol": protocol, "protocol_id": protocol["id"]}


def test_each_by_id_read_answers_with_the_not_found_code_of_its_own_entity(api):
    """Nine single-resource reads of an unknown id give nine distinct 404 codes.

    PRD: "The refusal is the 404 that names the missing resource type:
    `ERR_CLINIC_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`,
    `ERR_STAFFING_ASSIGNMENT_NOT_FOUND`, `ERR_QUEUE_ENTRY_NOT_FOUND`,
    `ERR_VISIT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`,
    `ERR_CHART_REVIEW_NOT_FOUND` or `ERR_VISIT_SUMMARY_NOT_FOUND`."

    Design: Corner/errors/corner_unknown_identifier_probes_return_the_entity_specific_not_found
    """
    env = _reference_data_only(api)
    probes = [
        (api.get_protocol, ApiErrorId.ERR_PROTOCOL_NOT_FOUND),
        (api.get_physician, ApiErrorId.ERR_PHYSICIAN_NOT_FOUND),
        (api.get_clinician, ApiErrorId.ERR_CLINICIAN_NOT_FOUND),
        (api.get_staffing_assignment, ApiErrorId.ERR_STAFFING_ASSIGNMENT_NOT_FOUND),
        (api.get_queue_entry, ApiErrorId.ERR_QUEUE_ENTRY_NOT_FOUND),
        (api.get_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        (api.get_prescription, ApiErrorId.ERR_PRESCRIPTION_NOT_FOUND),
        (api.get_chart_review, ApiErrorId.ERR_CHART_REVIEW_NOT_FOUND),
        (api.get_visit_summary, ApiErrorId.ERR_VISIT_SUMMARY_NOT_FOUND),
    ]

    for getter, expected in probes:
        validate_error(getter(NON_EXISTENT_UUID, env["admin"]), expected, 404)


def test_identifiers_are_type_scoped_so_a_real_protocol_id_is_no_physician(api):
    """A live id from another table resolves nowhere here and names this path's type.

    PRD: "Every identifier embedded in the URL must resolve to an existing row, and
    path identifiers are validated left to right so that the outermost container is
    confirmed before anything nested inside it."

    Design: Corner/errors/corner_unknown_identifier_probes_return_the_entity_specific_not_found
    """
    env = _reference_data_only(api)

    response = api.get_physician(env["protocol_id"], env["admin"])

    validate_error(response, ApiErrorId.ERR_PHYSICIAN_NOT_FOUND, 404)
    assert error_id(response) != "ERR_PROTOCOL_NOT_FOUND"


def test_the_real_protocol_identifier_still_reads_back_on_its_own_path(api):
    """The control read proves the nine 404s were about the ids, not the endpoints.

    PRD: "Path identifiers are resolved strictly left to right, so a request naming a
    clinic and then a resource inside it always reports the clinic's absence first."

    Design: Corner/errors/corner_unknown_identifier_probes_return_the_entity_specific_not_found
    """
    env = _reference_data_only(api)

    protocol = validate_success(api.get_protocol(env["protocol_id"], env["admin"]))

    assert protocol["complaint_code"] == COMPLAINT_SORE_THROAT
    assert protocol["id"] == env["protocol_id"]


# ---------------------------------------------------------------------------
# corner_state_with_no_state_rule_blocks_staffing_until_the_rule_is_filed
# ---------------------------------------------------------------------------


def test_opening_a_clinic_in_a_state_with_no_rule_on_file_is_refused(api):
    """A CA rule does nothing for TX: the site cannot be opened before its own rule.

    PRD: "A clinic itself may only be opened in a state that already has a
    `StateRule`; otherwise the creation is refused with `ERR_STATE_RULE_NOT_FOUND`."

    Design: Corner/errors/corner_state_with_no_state_rule_blocks_staffing_until_the_rule_is_filed
    """
    admin = make_admin_headers()
    create_state_rule(api, admin, state_code="CA")

    response = api.create_clinic(
        clinic_payload(name="TX Store 62", state_code="TX"), admin)

    validate_error(response, ApiErrorId.ERR_STATE_RULE_NOT_FOUND, 404)


def test_the_same_site_and_shift_go_through_once_the_state_rule_is_filed(api):
    """Filing the TX rule unblocks the identical clinic and staffing writes.

    PRD: "A `StateRule` row must exist for the relevant clinic's `state_code` before
    any state-dependent rule is evaluated, else `ERR_STATE_RULE_NOT_FOUND` (404)."

    Design: Corner/errors/corner_state_with_no_state_rule_blocks_staffing_until_the_rule_is_filed
    """
    admin = make_admin_headers()
    create_state_rule(api, admin, state_code="TX", chart_review_sample_pct=10,
                      review_deadline_hours=120, controlled_rx_allowed=True,
                      max_supervised_clinicians_per_physician=5)
    clinic = create_clinic(api, admin, name="TX Store 62", state_code="TX")
    physician = create_physician(api, admin, full_name="Dr Dogwood",
                                 licensed_state_codes=("TX",))
    clinician = create_clinician(api, clinic["id"], physician["id"], admin,
                                 full_name="NP Dogwood", license_state_code="TX")

    assignment = create_assignment(
        api, clinic["id"], clinician["id"], admin,
        pinned_supervising_physician_id=physician["id"])

    assert assignment["status"] == ASSIGNMENT_ACTIVE
    assert read_clinic(api, clinic["id"])["on_duty_clinician_count"] == 1
    assert read_clinic(api, clinic["id"])["open_status"] == CLINIC_OPEN


# ---------------------------------------------------------------------------
# corner_state_rule_and_protocol_offering_uniqueness_are_scoped_differently
# ---------------------------------------------------------------------------


def _ca_rule_and_a_sore_throat_offering_in_two_states(api):
    """One CA rule; SORE_THROAT is offered in CA and NV by a single protocol."""
    admin = make_admin_headers()
    rule = create_state_rule(api, admin, state_code="CA")
    protocol = create_protocol(api, admin, complaint_code=COMPLAINT_SORE_THROAT,
                               allowed_state_codes=("CA", "NV"))
    return {"admin": admin, "state_rule": rule, "protocol": protocol}


def test_a_second_rule_for_the_same_state_code_is_refused(api):
    """State-rule uniqueness is on the scalar `state_code`, so CA is taken.

    PRD: "A state may be registered only once: a second registration for the same
    `state_code` is refused with `ERR_DUPLICATE_STATE_RULE`."

    Design: Corner/errors/corner_state_rule_and_protocol_offering_uniqueness_are_scoped_differently
    """
    env = _ca_rule_and_a_sore_throat_offering_in_two_states(api)

    response = api.create_state_rule(
        state_rule_payload(state_code="CA", chart_review_sample_pct=25,
                           review_deadline_hours=48,
                           collaborating_physician_required=False,
                           min_independent_practice_age_months=36,
                           controlled_rx_allowed=True,
                           max_supervised_clinicians_per_physician=9),
        env["admin"])

    validate_error(response, ApiErrorId.ERR_DUPLICATE_STATE_RULE, 409)


def test_the_rejected_duplicate_rule_leaves_the_stored_rule_in_force(api):
    """The rejected body asked for no pinned supervisor; the pin is still mandatory.

    PRD: "When the clinic state's rule sets `collaborating_physician_required`, the
    field must be supplied and must equal the clinician's own
    `supervising_physician_id`, else `ERR_SUPERVISION_REQUIRED`."

    Design: Corner/errors/corner_state_rule_and_protocol_offering_uniqueness_are_scoped_differently
    """
    env = _ca_rule_and_a_sore_throat_offering_in_two_states(api)
    api.create_state_rule(
        state_rule_payload(state_code="CA", chart_review_sample_pct=25,
                           review_deadline_hours=48,
                           collaborating_physician_required=False,
                           min_independent_practice_age_months=36,
                           controlled_rx_allowed=True,
                           max_supervised_clinicians_per_physician=9),
        env["admin"])
    clinic = create_clinic(api, env["admin"], name="CA Store 63")
    physician = create_physician(api, env["admin"], full_name="Dr Cedar")
    clinician = create_clinician(api, clinic["id"], physician["id"], env["admin"],
                                 full_name="NP Cedar")

    response = api.create_staffing_assignment(
        staffing_assignment_payload(clinic["id"], clinician["id"]), env["admin"])

    validate_error(response, ApiErrorId.ERR_SUPERVISION_REQUIRED, 422)


def test_a_protocol_offering_sharing_a_single_state_is_refused(api):
    """`NV` overlaps and `AZ` does not — one shared state is enough to collide.

    PRD: "Protocol offerings must not collide: if an existing protocol already offers
    the same `complaint_code` in any one of the requested `allowed_state_codes`, the
    registration is refused with `ERR_DUPLICATE_PROTOCOL_OFFERING`."

    Design: Corner/errors/corner_state_rule_and_protocol_offering_uniqueness_are_scoped_differently
    """
    env = _ca_rule_and_a_sore_throat_offering_in_two_states(api)

    response = api.create_protocol(
        protocol_payload(complaint_code=COMPLAINT_SORE_THROAT, min_age_months=24,
                         max_age_months=900, base_price_cents=8800, acuity_tier=1,
                         red_flag_codes=(), max_temp_c=39.0,
                         max_heart_rate_bpm=118, min_spo2_pct=93,
                         allowed_state_codes=("NV", "AZ")),
        env["admin"])

    validate_error(response, ApiErrorId.ERR_DUPLICATE_PROTOCOL_OFFERING, 409)


def test_a_disjoint_state_list_and_a_different_complaint_are_both_accepted(api):
    """Uniqueness is per complaint-plus-state pair, not per complaint and not per state.

    PRD: "Protocol offerings must not collide: if an existing protocol already offers
    the same `complaint_code` in any one of the requested `allowed_state_codes`, the
    registration is refused with `ERR_DUPLICATE_PROTOCOL_OFFERING`."

    Design: Corner/errors/corner_state_rule_and_protocol_offering_uniqueness_are_scoped_differently
    """
    env = _ca_rule_and_a_sore_throat_offering_in_two_states(api)

    disjoint = create_protocol(api, env["admin"], complaint_code=COMPLAINT_SORE_THROAT,
                               min_age_months=24, max_age_months=900,
                               base_price_cents=8800, acuity_tier=1,
                               red_flag_codes=(), allowed_state_codes=("AZ",))
    other = create_protocol(api, env["admin"], complaint_code=COMPLAINT_EAR_PAIN,
                            min_age_months=24, base_price_cents=7900, acuity_tier=1,
                            red_flag_codes=("MASTOID_SWELLING",),
                            allowed_state_codes=("CA", "NV"))

    assert disjoint["id"] != env["protocol"]["id"]
    assert other["complaint_code"] == COMPLAINT_EAR_PAIN
    rows, meta = validate_paginated(
        api.list_protocols(env["admin"], params={"complaint_code": COMPLAINT_SORE_THROAT}))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {env["protocol"]["id"], disjoint["id"]}


# ---------------------------------------------------------------------------
# corner_invalid_time_range_is_checked_at_all_three_write_sites
# ---------------------------------------------------------------------------


def _open_clinic_with_an_unstaffed_second_clinician(api):
    """NP Test 1 holds the floor 00:00-23:00; NP Elder holds no shift at all."""
    env = staffed_clinic(api)
    env["spare"] = create_clinician(api, env["clinic_id"], env["physician_id"],
                                    env["admin"], full_name="NP Elder")
    env["patient"] = create_patient(api, env["front_desk"], full_name="Tim Timeless",
                                    date_of_birth="1991-01-01")
    return env


def test_a_shift_whose_start_equals_its_end_is_refused(api):
    """Equality fails "strictly before", so a zero-length shift is not a shift.

    PRD: "The interval is half-open: `starts_at` is inclusive, `ends_at` is exclusive,
    and `starts_at` must fall strictly before `ends_at` or the request is refused with
    `ERR_INVALID_TIME_RANGE`."

    Design: Corner/errors/corner_invalid_time_range_is_checked_at_all_three_write_sites
    """
    env = _open_clinic_with_an_unstaffed_second_clinician(api)

    response = api.create_staffing_assignment(
        staffing_assignment_payload(
            env["clinic_id"], env["spare"]["id"],
            starts_at="2026-08-01T09:00:00Z", ends_at="2026-08-01T09:00:00Z",
            pinned_supervising_physician_id=env["physician_id"]),
        env["admin"])

    validate_error(response, ApiErrorId.ERR_INVALID_TIME_RANGE, 422)
    assert read_clinician(api, env["spare"]["id"])["active_assignment_count"] == 0


def test_nudging_the_end_by_one_minute_makes_the_same_shift_legal(api):
    """Sixty seconds of separation is all the strict inequality asks for.

    PRD: "A shift's start must fall strictly before its end, a sampling window's start
    must fall strictly before its end, and an appointment slot must not be earlier than
    the logical clock, else `ERR_INVALID_TIME_RANGE` (422)."

    Design: Corner/errors/corner_invalid_time_range_is_checked_at_all_three_write_sites
    """
    env = _open_clinic_with_an_unstaffed_second_clinician(api)

    assignment = validate_success(api.create_staffing_assignment(
        staffing_assignment_payload(
            env["clinic_id"], env["spare"]["id"],
            starts_at="2026-08-01T09:00:00Z", ends_at="2026-08-01T09:01:00Z",
            pinned_supervising_physician_id=env["physician_id"]),
        env["admin"]), 201)

    assert assignment["status"] == ASSIGNMENT_SCHEDULED
    assert read_clinician(api, env["spare"]["id"])["active_assignment_count"] == 1


def test_a_slot_behind_the_clock_is_refused_while_the_clock_instant_is_bookable(api):
    """One minute early queues nothing; the boundary instant itself books cleanly.

    PRD: "The requested `scheduled_at` must not be earlier than the logical clock — the
    past cannot be booked — else `ERR_INVALID_TIME_RANGE`."

    Design: Corner/errors/corner_invalid_time_range_is_checked_at_all_three_write_sites
    """
    env = _open_clinic_with_an_unstaffed_second_clinician(api)

    response = api.create_queue_entry(
        appointment_payload(env["clinic_id"], env["patient"]["id"],
                            "2026-07-31T23:59:00Z"),
        env["front_desk"])

    validate_error(response, ApiErrorId.ERR_INVALID_TIME_RANGE, 422)
    rows, meta = validate_paginated(api.list_queue_entries(env["admin"]))
    assert meta["total_count"] == 0
    assert rows == []
    entry = validate_success(api.create_queue_entry(
        appointment_payload(env["clinic_id"], env["patient"]["id"],
                            "2026-08-01T00:00:00Z"),
        env["front_desk"]), 201)
    assert entry["status"] == QUEUE_SCHEDULED
    assert read_queue_entry(api, entry["id"])["status"] == QUEUE_SCHEDULED


def test_a_sampling_window_of_zero_width_is_refused_and_reviews_nothing(api):
    """The third write site guarded by the same rung: window_start == window_end.

    PRD: "A `window_start` that is not strictly before `window_end` is refused with
    `ERR_INVALID_TIME_RANGE`."

    Design: Corner/errors/corner_invalid_time_range_is_checked_at_all_three_write_sites
    """
    env = _open_clinic_with_an_unstaffed_second_clinician(api)

    response = api.run_chart_review_sampling(
        env["clinic_id"], "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z",
        env["admin"])

    validate_error(response, ApiErrorId.ERR_INVALID_TIME_RANGE, 422)
    rows, meta = validate_paginated(api.list_chart_reviews(env["admin"]))
    assert meta["total_count"] == 0
    assert rows == []


# ---------------------------------------------------------------------------
# corner_physician_licensing_outranks_the_supervision_pin_requirement
# ---------------------------------------------------------------------------


def _three_physicians_and_two_clinicians_in_california(api):
    """Dr Fern CA is licensed and active; Dr Fern NV is out of state; Dr Fern Retired
    is CA-licensed but INACTIVE and supervises NP Fern B."""
    admin = make_admin_headers()
    create_state_rule(api, admin, state_code="CA")
    clinic = create_clinic(api, admin, name="CA Store 65")
    ca = create_physician(api, admin, full_name="Dr Fern CA",
                          licensed_state_codes=("CA",))
    nv = create_physician(api, admin, full_name="Dr Fern NV",
                          licensed_state_codes=("NV",))
    retired = create_physician(api, admin, full_name="Dr Fern Retired",
                               licensed_state_codes=("CA",),
                               status=PHYSICIAN_INACTIVE)
    clinician_a = create_clinician(api, clinic["id"], ca["id"], admin,
                                   full_name="NP Fern A")
    clinician_b = create_clinician(api, clinic["id"], retired["id"], admin,
                                   full_name="NP Fern B", credential=CREDENTIAL_PA)
    return {
        "admin": admin,
        "clinic_id": clinic["id"],
        "ca_id": ca["id"],
        "nv_id": nv["id"],
        "retired_id": retired["id"],
        "clinician_a_id": clinician_a["id"],
        "clinician_b_id": clinician_b["id"],
    }


def test_a_shift_filed_with_no_pinned_physician_at_all_is_refused(api):
    """California demands the collaborating physician be named, and none was.

    PRD: "When the state rule requires a collaborating physician,
    `pinned_supervising_physician_id` must be supplied and must equal the clinician's own
    `supervising_physician_id`, else `ERR_SUPERVISION_REQUIRED` (422). This rung guards
    staffing creation."

    Design: Corner/errors/corner_physician_licensing_outranks_the_supervision_pin_requirement
    """
    env = _three_physicians_and_two_clinicians_in_california(api)

    response = api.create_staffing_assignment(
        staffing_assignment_payload(env["clinic_id"], env["clinician_a_id"]),
        env["admin"])

    validate_error(response, ApiErrorId.ERR_SUPERVISION_REQUIRED, 422)
    assert read_clinic(api, env["clinic_id"])["open_status"] == CLINIC_CLOSED


def test_an_unlicensed_or_inactive_pin_is_reported_ahead_of_the_wrong_supervisor(api):
    """Dr Fern NV is out of state and Dr Fern Retired is not ACTIVE; licensure answers both.

    PRD: "A `Physician` holds a list of `licensed_state_codes` and may only be pinned to,
    or review for, a clinic whose `state_code` appears in that list; a physician who is
    `INACTIVE`, or whose list omits the clinic's state, is refused with
    `ERR_PHYSICIAN_NOT_LICENSED_IN_STATE`."

    Design: Corner/errors/corner_physician_licensing_outranks_the_supervision_pin_requirement
    """
    env = _three_physicians_and_two_clinicians_in_california(api)

    response = api.create_staffing_assignment(
        staffing_assignment_payload(env["clinic_id"], env["clinician_a_id"],
                                    pinned_supervising_physician_id=env["nv_id"]),
        env["admin"])

    validate_error(response, ApiErrorId.ERR_PHYSICIAN_NOT_LICENSED_IN_STATE, 422)
    assert error_id(response) != "ERR_SUPERVISION_REQUIRED"
    inactive = api.create_staffing_assignment(
        staffing_assignment_payload(env["clinic_id"], env["clinician_b_id"],
                                    pinned_supervising_physician_id=env["retired_id"]),
        env["admin"])
    validate_error(inactive, ApiErrorId.ERR_PHYSICIAN_NOT_LICENSED_IN_STATE, 422)
    assert error_id(inactive) != "ERR_SUPERVISION_REQUIRED"


def test_a_licensed_stranger_falls_back_to_the_supervision_complaint(api):
    """Dr Fern CA clears licensure and then fails the identity test for NP Fern B.

    PRD: "Supervision is pinned at creation, not looked up later. The new assignment
    records a `pinned_supervising_physician_id`, which the client may supply explicitly
    and which otherwise copies the clinician's own `supervising_physician_id`; once
    written it is never re-read, so changing the clinician's default supervisor
    afterwards does not retroactively move existing shifts."

    Design: Corner/errors/corner_physician_licensing_outranks_the_supervision_pin_requirement
    """
    env = _three_physicians_and_two_clinicians_in_california(api)

    response = api.create_staffing_assignment(
        staffing_assignment_payload(env["clinic_id"], env["clinician_b_id"],
                                    pinned_supervising_physician_id=env["ca_id"]),
        env["admin"])

    validate_error(response, ApiErrorId.ERR_SUPERVISION_REQUIRED, 422)
    assert error_id(response) != "ERR_PHYSICIAN_NOT_LICENSED_IN_STATE"


def test_the_matching_licensed_pin_staffs_the_floor_and_moves_one_counter(api):
    """Only NP Fern A under Dr Fern CA satisfies both rungs, and only that pair counts.

    PRD: "A physician's `current_supervised_count` is the number of **distinct**
    clinicians appearing on assignments that name that physician as pinned supervisor and
    sit in `SCHEDULED` or `ACTIVE` status; two shifts for the same clinician under the
    same physician count once, and `CANCELLED` or `COMPLETED` assignments are excluded
    entirely."

    Design: Corner/errors/corner_physician_licensing_outranks_the_supervision_pin_requirement
    """
    env = _three_physicians_and_two_clinicians_in_california(api)

    assignment = validate_success(api.create_staffing_assignment(
        staffing_assignment_payload(env["clinic_id"], env["clinician_a_id"],
                                    pinned_supervising_physician_id=env["ca_id"]),
        env["admin"]), 201)

    assert assignment["status"] == ASSIGNMENT_ACTIVE
    assert read_physician(api, env["ca_id"])["current_supervised_count"] == 1
    assert read_physician(api, env["retired_id"])["current_supervised_count"] == 0
    assert read_clinic(api, env["clinic_id"])["on_duty_clinician_count"] == 1


# ---------------------------------------------------------------------------
# corner_walk_in_capacity_then_the_uncalled_and_the_served_entry_are_both_unvisitable
# ---------------------------------------------------------------------------


def _walk_in_queue_filled_to_its_capacity_of_two(api):
    """Una and Dee are WAITING at a site whose walk-in room holds exactly two."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         clinic={"walk_in_queue_capacity": 2})
    env["una"] = create_patient(api, env["front_desk"], full_name="Una One",
                                date_of_birth="1985-05-05")
    env["dee"] = create_patient(api, env["front_desk"], full_name="Dee Two",
                                date_of_birth="1986-06-06")
    env["tre"] = create_patient(api, env["front_desk"], full_name="Tre Three",
                                date_of_birth="1987-07-07")
    env["una_entry"] = add_walk_in(api, env, env["una"]["id"])
    env["dee_entry"] = add_walk_in(api, env, env["dee"]["id"])
    return env


def test_a_third_walk_in_is_refused_once_the_waiting_room_is_full(api):
    """Two WAITING walk-ins against a capacity of two leaves no room to be strictly below.

    PRD: "And the site must have room: the number of that clinic's entries whose `kind` is
    `WALK_IN` and whose status is `WAITING` must be strictly below
    `walk_in_queue_capacity`, else the intake is refused with
    `ERR_QUEUE_CAPACITY_REACHED`."

    Design: Corner/errors/corner_walk_in_capacity_then_the_uncalled_and_the_served_entry_are_both_unvisitable
    """
    env = _walk_in_queue_filled_to_its_capacity_of_two(api)

    response = api.create_queue_entry(
        walk_in_payload(env["clinic_id"], env["tre"]["id"]), env["front_desk"])

    validate_error(response, ApiErrorId.ERR_QUEUE_CAPACITY_REACHED, 409)
    assert read_clinic(api, env["clinic_id"])["waiting_count"] == 2


def test_an_entry_that_has_never_been_called_cannot_be_visited(api):
    """Dee is WAITING, and a visit may only consume a CALLED entry.

    PRD: "The named entry must belong to the same clinic as the visit being opened, must
    be in `CALLED` status, and must not already have a visit attached to it — any of those
    three failures is `ERR_QUEUE_ENTRY_NOT_CALLABLE`."

    Design: Corner/errors/corner_walk_in_capacity_then_the_uncalled_and_the_served_entry_are_both_unvisitable
    """
    env = _walk_in_queue_filled_to_its_capacity_of_two(api)

    response = api.create_visit({"queue_entry_id": env["dee_entry"]["id"]},
                                env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_QUEUE_ENTRY_NOT_CALLABLE, 409)
    assert read_queue_entry(api, env["dee_entry"]["id"])["status"] == QUEUE_WAITING


def test_a_served_entry_cannot_be_visited_a_second_time(api):
    """Una's entry is consumed by the first visit, and the replay finds it SERVED.

    PRD: "The visit copies its `clinic_id`, its `patient_id` and its `complaint_code` from
    the entry it consumes, and the consumed entry advances `CALLED → SERVED` in the same
    request."

    Design: Corner/errors/corner_walk_in_capacity_then_the_uncalled_and_the_served_entry_are_both_unvisitable
    """
    env = _walk_in_queue_filled_to_its_capacity_of_two(api)
    called = call_next(api, env)
    assert called["id"] == env["una_entry"]["id"]
    assert called["status"] == QUEUE_CALLED
    start_visit(api, env, env["una_entry"]["id"])

    response = api.create_visit({"queue_entry_id": env["una_entry"]["id"]},
                                env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_QUEUE_ENTRY_NOT_CALLABLE, 409)
    assert read_queue_entry(api, env["una_entry"]["id"])["status"] == QUEUE_SERVED
    rows, meta = validate_paginated(api.list_visits(env["admin"]))
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_the_refused_walk_in_succeeds_once_a_waiting_slot_is_freed(api):
    """Capacity reads the live WAITING count, not the site's lifetime intake.

    PRD: "A walk-in is admitted straight into the waiting room. Inside the same request
    the entry advances `SCHEDULED → WAITING`, its `arrived_at` is stamped with the logical
    clock, its `priority_score` is computed, the clinic's `waiting_count` rises by 1 and
    `posted_wait_minutes` is recomputed from the new depth."

    Design: Corner/errors/corner_walk_in_capacity_then_the_uncalled_and_the_served_entry_are_both_unvisitable
    """
    env = _walk_in_queue_filled_to_its_capacity_of_two(api)
    validate_error(
        api.create_queue_entry(walk_in_payload(env["clinic_id"], env["tre"]["id"]),
                               env["front_desk"]),
        ApiErrorId.ERR_QUEUE_CAPACITY_REACHED, 409)
    call_next(api, env)
    start_visit(api, env, env["una_entry"]["id"])

    entry = validate_success(api.create_queue_entry(
        walk_in_payload(env["clinic_id"], env["tre"]["id"]), env["front_desk"]), 201)

    assert entry["status"] == QUEUE_WAITING
    assert read_clinic(api, env["clinic_id"])["waiting_count"] == 2


# ---------------------------------------------------------------------------
# corner_controlled_opioid_refused_without_burning_the_visit_version
# ---------------------------------------------------------------------------


def _treated_visit_in_a_state_that_forbids_controlled_prescribing(api):
    """CA's rule leaves `controlled_rx_allowed` false; Opie Oakes is TREATED."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    env["patient"] = create_insured_patient(
        api, env["front_desk"], full_name="Opie Oakes", date_of_birth="1975-03-03",
        payer_name="BlueCo", member_id="M-6767")
    env["bundle"] = treated_visit(
        api, env, env["patient"]["id"],
        vitals={"temp_c": 37.2, "heart_rate_bpm": 80, "spo2_pct": 98})
    env["visit"] = read_visit(api, env["bundle"]["visit_id"])
    env["visit_version"] = env["visit"]["version"]
    return env


def test_a_controlled_opioid_draft_is_refused_where_the_state_forbids_it(api):
    """The visit is squarely TREATED; the state rule is what stops the drug class.

    PRD: "A prescription in the controlled-opioid therapy class is refused with
    `ERR_CONTROLLED_RX_NOT_PERMITTED` (422) when the clinic state's rule forbids
    controlled prescribing."

    Design: Corner/errors/corner_controlled_opioid_refused_without_burning_the_visit_version
    """
    env = _treated_visit_in_a_state_that_forbids_controlled_prescribing(api)
    assert env["visit"]["clinical_status"] == VISIT_TREATED

    response = api.create_prescription(
        prescription_payload(env["bundle"]["visit_id"], env["visit_version"],
                             drug_name="Oxycodone 5mg",
                             therapy_class=THERAPY_CONTROLLED_OPIOID, days_supply=3,
                             pharmacy_npi=VALID_PHARMACY_NPI),
        env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_CONTROLLED_RX_NOT_PERMITTED, 422)


def test_the_refused_draft_leaves_the_visit_version_available_to_replay(api):
    """The very same `expected_visit_version` still writes a legal draft afterwards.

    PRD: "If that number does not equal the visit's current `version`, the creation is
    refused with `ERR_STALE_VISIT_VERSION` (HTTP 412) and the client must re-read the
    visit before retrying."

    Design: Corner/errors/corner_controlled_opioid_refused_without_burning_the_visit_version
    """
    env = _treated_visit_in_a_state_that_forbids_controlled_prescribing(api)
    api.create_prescription(
        prescription_payload(env["bundle"]["visit_id"], env["visit_version"],
                             drug_name="Oxycodone 5mg",
                             therapy_class=THERAPY_CONTROLLED_OPIOID, days_supply=3,
                             pharmacy_npi=VALID_PHARMACY_NPI),
        env["clinician_headers"])

    prescription = validate_success(api.create_prescription(
        prescription_payload(env["bundle"]["visit_id"], env["visit_version"],
                             therapy_class=THERAPY_ANTIBIOTIC_BETA_LACTAM),
        env["clinician_headers"]), 201)

    assert prescription["status"] == PRESCRIPTION_DRAFT
    assert read_visit(api, env["bundle"]["visit_id"])["version"] == env["visit_version"]


def test_the_refused_draft_persists_no_row_and_locks_no_therapy_class(api):
    """One prescription exists at the end, and a DRAFT never claims the class.

    PRD: "On success the prescription advances `DRAFT → ROUTED`, its `routed_at` is
    stamped with the logical clock, and the patient's `active_therapy_classes` gains this
    `therapy_class` with `active_therapy_class_count` recomputed as the length of that
    set."

    Design: Corner/errors/corner_controlled_opioid_refused_without_burning_the_visit_version
    """
    env = _treated_visit_in_a_state_that_forbids_controlled_prescribing(api)
    api.create_prescription(
        prescription_payload(env["bundle"]["visit_id"], env["visit_version"],
                             drug_name="Oxycodone 5mg",
                             therapy_class=THERAPY_CONTROLLED_OPIOID, days_supply=3,
                             pharmacy_npi=VALID_PHARMACY_NPI),
        env["clinician_headers"])
    validate_success(api.create_prescription(
        prescription_payload(env["bundle"]["visit_id"], env["visit_version"],
                             therapy_class=THERAPY_ANTIBIOTIC_BETA_LACTAM),
        env["clinician_headers"]), 201)

    rows, meta = validate_paginated(api.list_prescriptions(env["clinician_headers"]))

    assert meta["total_count"] == 1
    assert rows[0]["therapy_class"] == THERAPY_ANTIBIOTIC_BETA_LACTAM
    assert read_patient(api, env["patient"]["id"])["active_therapy_class_count"] == 0


# ---------------------------------------------------------------------------
# corner_complaint_offered_only_in_another_state_is_queueable_but_not_visitable
# ---------------------------------------------------------------------------


def _ca_clinic_whose_uti_protocol_is_offered_only_in_nevada(api):
    """UTI is an NV-only offering; SORE_THROAT is the site's one CA-legal complaint."""
    env = staffed_clinic(api, protocol={
        "complaint_code": COMPLAINT_UTI, "min_age_months": 216,
        "max_age_months": 1200, "base_price_cents": 12900, "acuity_tier": 3,
        "red_flag_codes": ("THUNDERCLAP",), "max_temp_c": 39.0,
        "max_heart_rate_bpm": 118, "min_spo2_pct": 93, "requires_cosign": True,
        "allowed_state_codes": ("NV",)})
    env["throat_protocol"] = create_protocol(api, env["admin"])
    env["mira"] = create_insured_patient(
        api, env["front_desk"], full_name="Mira Urgent", date_of_birth="1980-04-04",
        payer_name="BlueCo", member_id="M-6868")
    env["theo"] = create_insured_patient(
        api, env["front_desk"], full_name="Theo Throat", date_of_birth="1981-05-05",
        payer_name="BlueCo", member_id="M-6869")
    return env


def test_a_complaint_offered_only_in_another_state_still_joins_the_queue(api):
    """Intake has no state filter, so the UTI walk-in is admitted at the CA site.

    PRD: "A `Protocol` must exist for the presenting complaint whose
    `allowed_state_codes` contains the clinic's `state_code`, else
    `ERR_PROTOCOL_NOT_OFFERED_IN_STATE` (422). This rung guards visit creation."

    Design: Corner/errors/corner_complaint_offered_only_in_another_state_is_queueable_but_not_visitable
    """
    env = _ca_clinic_whose_uti_protocol_is_offered_only_in_nevada(api)

    entry = validate_success(api.create_queue_entry(
        walk_in_payload(env["clinic_id"], env["mira"]["id"],
                        complaint_code=COMPLAINT_UTI), env["front_desk"]), 201)

    assert entry["status"] == QUEUE_WAITING
    assert entry["complaint_code"] == COMPLAINT_UTI
    assert read_clinic(api, env["clinic_id"])["waiting_count"] == 1


def test_opening_the_visit_is_where_the_out_of_state_protocol_is_caught(api):
    """The entry was callable, but the encounter cannot be opened in California.

    PRD: "A `Protocol` must exist for the presenting complaint whose
    `allowed_state_codes` contains the clinic's `state_code`, else
    `ERR_PROTOCOL_NOT_OFFERED_IN_STATE` (422). This rung guards visit creation."

    Design: Corner/errors/corner_complaint_offered_only_in_another_state_is_queueable_but_not_visitable
    """
    env = _ca_clinic_whose_uti_protocol_is_offered_only_in_nevada(api)
    entry = add_walk_in(api, env, env["mira"]["id"], complaint_code=COMPLAINT_UTI)
    called = call_next(api, env)
    assert called["id"] == entry["id"]

    response = api.create_visit({"queue_entry_id": entry["id"]},
                                env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_PROTOCOL_NOT_OFFERED_IN_STATE, 422)
    assert error_id(response) != "ERR_QUEUE_ENTRY_NOT_CALLABLE"


def test_the_refused_visit_leaves_the_entry_called_and_out_of_the_running(api):
    """The stuck entry is neither served nor returned to the queue, so the next call
    reaches the CA-legal patient instead.

    PRD: "Selection considers only that clinic's entries in `WAITING` status —
    `SCHEDULED`, `CALLED`, `SERVED`, `ABANDONED` and `DEFERRED_CLOSURE` entries are all
    excluded — and each candidate's `priority_score` is recomputed at evaluation time so
    that accrued waiting is honoured."

    Design: Corner/errors/corner_complaint_offered_only_in_another_state_is_queueable_but_not_visitable
    """
    env = _ca_clinic_whose_uti_protocol_is_offered_only_in_nevada(api)
    stuck = add_walk_in(api, env, env["mira"]["id"], complaint_code=COMPLAINT_UTI)
    call_next(api, env)
    api.create_visit({"queue_entry_id": stuck["id"]}, env["clinician_headers"])
    assert read_queue_entry(api, stuck["id"])["status"] == QUEUE_CALLED
    theo_entry = add_walk_in(api, env, env["theo"]["id"])

    second = call_next(api, env)

    assert second["id"] == theo_entry["id"]
    visit = start_visit(api, env, theo_entry["id"])
    assert visit["protocol_id"] == env["throat_protocol"]["id"]
    assert read_queue_entry(api, stuck["id"])["status"] == QUEUE_CALLED


# ---------------------------------------------------------------------------
# corner_referral_required_blocks_any_prescription_for_that_visit
# ---------------------------------------------------------------------------


def _referred_visit_after_a_red_flag_submission(api):
    """STRIDOR is on the protocol's red-flag list, so Ravi's submit refers him out."""
    env = staffed_clinic(api, protocol={"requires_cosign": True,
                                        "red_flag_codes": ("STRIDOR",)})
    env["patient"] = create_insured_patient(
        api, env["front_desk"], full_name="Ravi Redflag", date_of_birth="1979-09-09",
        payer_name="BlueCo", member_id="M-6969")
    env["bundle"] = treated_visit(
        api, env, env["patient"]["id"],
        vitals={"temp_c": 37.4, "heart_rate_bpm": 88, "spo2_pct": 97,
                "red_flag_codes": ("STRIDOR",)})
    env["visit"] = read_visit(api, env["bundle"]["visit_id"])
    env["visit_version"] = env["visit"]["version"]
    return env


def test_a_red_flag_on_submission_refers_the_visit_and_flags_it(api):
    """The overlap with the protocol's red-flag list decides the fork before anything else.

    PRD: "On the referral branch, the linked visit advances `IN_ASSESSMENT → REFERRED` and
    its `referral_required` flag is set true; then every prescription on that visit whose
    status is `DRAFT` or `ROUTED` is cancelled; then, for each prescription that was
    cancelled, the patient's `active_therapy_classes` and `active_therapy_class_count` are
    recomputed."

    Design: Corner/errors/corner_referral_required_blocks_any_prescription_for_that_visit
    """
    env = _referred_visit_after_a_red_flag_submission(api)

    assert env["bundle"]["assessment"]["status"] == ASSESSMENT_REFERRAL_REQUIRED
    assert env["visit"]["clinical_status"] == VISIT_REFERRED
    assert env["visit"]["referral_required"] is True


def test_prescribing_on_a_referred_visit_names_the_referral_not_treatability(api):
    """Two refusals compete for a REFERRED visit and the referral rung answers first.

    PRD: "A visit whose assessment produced a mandatory referral may not be prescribed
    for, and its prescriptions may not be routed to a pharmacy, else
    `ERR_REFERRAL_REQUIRED` (422). Cosigning such an assessment remains permitted — the
    referral record itself needs the collaborating physician's signature. This rung guards
    prescription creation and prescription routing."

    Design: Corner/errors/corner_referral_required_blocks_any_prescription_for_that_visit
    """
    env = _referred_visit_after_a_red_flag_submission(api)

    response = api.create_prescription(
        prescription_payload(env["bundle"]["visit_id"], env["visit_version"]),
        env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_REFERRAL_REQUIRED, 422)
    assert error_id(response) != "ERR_VISIT_NOT_TREATABLE"


def test_the_cosignature_is_allowed_and_still_does_not_unlock_prescribing(api):
    """The physician may sign the referral, and signing it changes nothing for drugs.

    PRD: "A `CollaboratingPhysician` may cosign an assessment that sits in
    `TREATMENT_AUTHORIZED` or in `REFERRAL_REQUIRED` — both branches are cosignable, and
    cosigning a referral is expected practice, since the referral record itself is what
    the physician is signing."

    Design: Corner/errors/corner_referral_required_blocks_any_prescription_for_that_visit
    """
    env = _referred_visit_after_a_red_flag_submission(api)
    api.create_prescription(
        prescription_payload(env["bundle"]["visit_id"], env["visit_version"]),
        env["clinician_headers"])

    cosigned = cosign_assessment(api, env, env["bundle"]["assessment_id"])

    assert cosigned["status"] == ASSESSMENT_COSIGNED
    response = api.create_prescription(
        prescription_payload(env["bundle"]["visit_id"], env["visit_version"]),
        env["clinician_headers"])
    validate_error(response, ApiErrorId.ERR_REFERRAL_REQUIRED, 422)
    rows, meta = validate_paginated(api.list_prescriptions(env["clinician_headers"]))
    assert meta["total_count"] == 0
    assert rows == []


# ---------------------------------------------------------------------------
# corner_lone_physician_cannot_be_reassigned_away_and_state_beats_the_empty_pool
# ---------------------------------------------------------------------------


def _lone_physician_holding_the_only_pending_review(api):
    """Dr Kelp is California's only physician and reviews Lila Lone's closed chart."""
    env = staffed_clinic(api, protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Kelp"})
    env["patient"] = create_insured_patient(
        api, env["front_desk"], full_name="Lila Lone", date_of_birth="1983-03-13",
        payer_name="BlueCo", member_id="M-7070", pcp_consent_on_file=False)
    env["bundle"] = closed_insured_visit(
        api, env, env["patient"]["id"], services_rendered=[], copay_cents=2000,
        coinsurance_pct=10.0,
        vitals={"temp_c": 37.0, "heart_rate_bpm": 74, "spo2_pct": 99})
    env["run"] = run_sampling(api, env["clinic_id"], "2026-08-01T00:00:00Z",
                              "2026-08-02T00:00:00Z", env["admin"])
    env["review_id"] = env["run"]["chart_review_ids"][0]
    return env


def test_the_run_names_the_treating_clinicians_supervisor_as_reviewer(api):
    """One eligible chart at a 40 percent rate rounds up to one review, owned by Dr Kelp.

    PRD: "Every chart the run selects becomes a review in `PENDING` status recording the
    `visit_id` sampled, the `assessment_id` under review, a `reviewer_physician_id` taken
    from the treating clinician's `supervising_physician_id`, the `sampled_reason`
    established above, and a `due_at` computed as the logical clock at the moment of
    sampling plus the state rule's `review_deadline_hours`."

    Design: Corner/errors/corner_lone_physician_cannot_be_reassigned_away_and_state_beats_the_empty_pool
    """
    env = _lone_physician_holding_the_only_pending_review(api)

    review = read_chart_review(api, env["review_id"])

    assert env["run"]["sampled_count"] == 1
    assert review["reviewer_physician_id"] == env["physician_id"]
    assert review["status"] == REVIEW_PENDING


def test_a_state_with_one_physician_has_nobody_to_reassign_the_review_to(api):
    """The incumbent is struck from their own candidate pool, so the pool is empty.

    PRD: "Candidates are physicians whose `status` is `ACTIVE`, whose
    `licensed_state_codes` contains the clinic's `state_code`, who are neither the
    incumbent `reviewer_physician_id` nor the assessment's `cosigned_by_physician_id`, and
    whose `current_supervised_count` is strictly below their effective cap — the smaller of
    their own `max_supervised_clinicians` and the state rule's
    `max_supervised_clinicians_per_physician`."

    Design: Corner/errors/corner_lone_physician_cannot_be_reassigned_away_and_state_beats_the_empty_pool
    """
    env = _lone_physician_holding_the_only_pending_review(api)

    response = api.reassign_chart_review(env["review_id"], env["admin"])

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_REVIEWER, 409)
    review = read_chart_review(api, env["review_id"])
    assert review["status"] == REVIEW_PENDING
    assert review["reviewer_physician_id"] == env["physician_id"]


def test_attesting_within_scope_ends_the_review_and_holds_nobody(api):
    """The clean outcome is terminal and leaves the clinician free to keep working.

    PRD: "`WITHIN_SCOPE` moves the review `PENDING → ATTESTED` and records that outcome,
    and nothing further happens."

    Design: Corner/errors/corner_lone_physician_cannot_be_reassigned_away_and_state_beats_the_empty_pool
    """
    env = _lone_physician_holding_the_only_pending_review(api)

    attested = validate_success(api.attest_chart_review(
        env["review_id"], OUTCOME_WITHIN_SCOPE, env["physician_headers"],
        attestation_note="Chart complete"))

    assert attested["status"] == REVIEW_ATTESTED
    assert attested["outcome"] == OUTCOME_WITHIN_SCOPE
    assert read_clinician(api, env["clinician_id"])["scope_hold"] is False


def test_after_attestation_the_state_error_masks_the_empty_reviewer_pool(api):
    """All three follow-up actions report the terminal state, not the missing candidate.

    PRD: "A review that is not `PENDING` cannot be reassigned, earning
    `ERR_CHART_REVIEW_INVALID_STATE`."

    Design: Corner/errors/corner_lone_physician_cannot_be_reassigned_away_and_state_beats_the_empty_pool
    """
    env = _lone_physician_holding_the_only_pending_review(api)
    validate_success(api.attest_chart_review(
        env["review_id"], OUTCOME_WITHIN_SCOPE, env["physician_headers"],
        attestation_note="Chart complete"))

    validate_error(
        api.attest_chart_review(env["review_id"], OUTCOME_WITHIN_SCOPE,
                                env["physician_headers"]),
        ApiErrorId.ERR_CHART_REVIEW_INVALID_STATE, 409)
    validate_error(
        api.request_chart_review_changes(env["review_id"], "Too late",
                                         env["physician_headers"]),
        ApiErrorId.ERR_CHART_REVIEW_INVALID_STATE, 409)
    response = api.reassign_chart_review(env["review_id"], env["admin"])
    validate_error(response, ApiErrorId.ERR_CHART_REVIEW_INVALID_STATE, 409)
    assert error_id(response) != "ERR_NO_ELIGIBLE_REVIEWER"


# ---------------------------------------------------------------------------
# corner_cancel_is_refused_on_a_cancelled_and_on_a_clock_completed_assignment
# ---------------------------------------------------------------------------


def _two_clinicians_on_a_single_hour_shift(api):
    """NP Test 1 and NP Test 2 both work [00:00, 01:00) under Dr Larch."""
    env = staffed_clinic(
        api, with_protocol=False, clinician_count=2,
        physician={"full_name": "Dr Larch"},
        assignment={"starts_at": "2026-08-01T00:00:00Z",
                    "ends_at": "2026-08-01T01:00:00Z"})
    env["shift_a"] = env["assignments"][0]
    env["shift_b"] = env["assignments"][1]
    return env


def test_cancelling_one_of_two_active_shifts_keeps_the_site_open(api):
    """The floor is one, so losing the second clinician does not change the posture.

    PRD: "Hop two re-derives `open_status` from the new count, moving `OPEN → LIMITED`
    when the count is above 0 but below `min_clinicians_required`, and `OPEN → CLOSED` or
    `LIMITED → CLOSED` when it reaches 0."

    Design: Corner/errors/corner_cancel_is_refused_on_a_cancelled_and_on_a_clock_completed_assignment
    """
    env = _two_clinicians_on_a_single_hour_shift(api)

    cancelled = validate_success(api.cancel_staffing_assignment(
        env["shift_a"]["id"], env["admin"], cancel_reason="Called away"))

    assert cancelled["status"] == ASSIGNMENT_CANCELLED
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["on_duty_clinician_count"] == 1
    assert clinic["open_status"] == CLINIC_OPEN


def test_a_cancelled_shift_cannot_be_cancelled_again(api):
    """CANCELLED is terminal, and the refused repeat decrements nothing.

    PRD: "A `ClinicAdmin` may cancel an assignment from `SCHEDULED` or from `ACTIVE`,
    optionally recording a `cancel_reason`; an assignment already `COMPLETED` or
    `CANCELLED` cannot be cancelled again and the attempt earns
    `ERR_STAFFING_ASSIGNMENT_INVALID_STATE`."

    Design: Corner/errors/corner_cancel_is_refused_on_a_cancelled_and_on_a_clock_completed_assignment
    """
    env = _two_clinicians_on_a_single_hour_shift(api)
    validate_success(api.cancel_staffing_assignment(
        env["shift_a"]["id"], env["admin"], cancel_reason="Called away"))

    response = api.cancel_staffing_assignment(
        env["shift_a"]["id"], env["admin"], cancel_reason="Called away again")

    validate_error(response, ApiErrorId.ERR_STAFFING_ASSIGNMENT_INVALID_STATE, 409)
    assert read_clinic(api, env["clinic_id"])["on_duty_clinician_count"] == 1


def test_a_shift_the_clock_completed_cannot_be_cancelled_either(api):
    """Passing `ends_at` retires the shift, and the retired shift refuses the cancel.

    PRD: "When the clock later passes `ends_at`, the assignment advances
    `ACTIVE → COMPLETED`, lowering `on_duty_clinician_count` by 1 and re-deriving posture
    in the other direction — `OPEN → LIMITED`, `OPEN → CLOSED` or `LIMITED → CLOSED`, with
    the queue and visit cascades of §2.8 — and both counters are recomputed again."

    Design: Corner/errors/corner_cancel_is_refused_on_a_cancelled_and_on_a_clock_completed_assignment
    """
    env = _two_clinicians_on_a_single_hour_shift(api)
    validate_success(api.cancel_staffing_assignment(
        env["shift_a"]["id"], env["admin"], cancel_reason="Called away"))
    set_clock(api, "2026-08-01T02:00:00Z", env["admin"])

    response = api.cancel_staffing_assignment(
        env["shift_b"]["id"], env["admin"], cancel_reason="Too late")

    validate_error(response, ApiErrorId.ERR_STAFFING_ASSIGNMENT_INVALID_STATE, 409)
    assert validate_success(api.get_staffing_assignment(
        env["shift_b"]["id"], env["admin"]))["status"] == ASSIGNMENT_COMPLETED


def test_the_two_refused_cancels_leave_the_counters_at_a_single_decrement(api):
    """One cancel and one clock completion empty the floor exactly once each.

    PRD: "A physician's `current_supervised_count` is the number of **distinct**
    clinicians appearing on assignments that name that physician as pinned supervisor and
    sit in `SCHEDULED` or `ACTIVE` status; two shifts for the same clinician under the
    same physician count once, and `CANCELLED` or `COMPLETED` assignments are excluded
    entirely."

    Design: Corner/errors/corner_cancel_is_refused_on_a_cancelled_and_on_a_clock_completed_assignment
    """
    env = _two_clinicians_on_a_single_hour_shift(api)
    validate_success(api.cancel_staffing_assignment(
        env["shift_a"]["id"], env["admin"], cancel_reason="Called away"))
    api.cancel_staffing_assignment(env["shift_a"]["id"], env["admin"],
                                   cancel_reason="Called away again")
    set_clock(api, "2026-08-01T02:00:00Z", env["admin"])

    api.cancel_staffing_assignment(env["shift_b"]["id"], env["admin"],
                                   cancel_reason="Too late")

    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["on_duty_clinician_count"] == 0
    assert clinic["open_status"] == CLINIC_CLOSED
    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 0
