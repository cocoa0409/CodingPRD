"""
Entity surface: creation, retrieval, listing, defaults, computed and stamped fields.

This module pins the observable shape of the records the service writes — that a create
returns every declared field rather than a subset, that a read echoes what was stored
while still recomputing the counters the specification calls derived, that the two
append-only entities expose neither `updated_at` nor `version`, that omitted optional
inputs fall back to their documented defaults rather than to null, and that the
entity-specific 404 and the payload-shape 400 fire before any business rule does.

Every scenario is built from an empty database through the public endpoints, with the
logical clock starting at its documented epoch.
"""

from typing import Any, Dict

from test_helpers import (
    BASE_REFERRAL_THRESHOLD_PCT,
    CLOCK_EPOCH,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    DEFAULT_PROTOCOL_LABEL,
    ApiErrorId,
    ClinicalStatus,
    Discipline,
    HospitalType,
    MonitoringState,
    NON_EXISTENT_UUID,
    Payer,
    PaymentReviewStatus,
    PeriodStatus,
    QualifyingTrack,
    ReferralStatus,
    WeaningPlanStatus,
    assert_cents,
    assert_contains_only,
    assert_created_record,
    assert_exact_keys,
    assert_ids_equal,
    assert_immutable_record,
    assert_instant_equals,
    assert_integer_field,
    assert_pagination_meta,
    assert_pct,
    assert_stay_dimensions,
    assert_unset,
    assert_vent_hours,
    assertions,
    factories,
    fixtures,
    get_success_data,
    ids_of,
    types,
    validate_error,
    validate_paginated,
)

Json = Dict[str, Any]


def _pagination_view(meta: Json) -> Json:
    """The response's pagination block, keyed for the shared four-field assertion.

    The envelope reports the pre-pagination population under the name `total_count`;
    the shared assertion reads that figure under the shorter key, so the two spellings
    are bridged in one place instead of restating four comparisons in every listing test.
    """
    return dict(meta, total=meta.get("total_count"))


class TestReferringHospitalCreation:
    """A single registration call returns the whole record, computed fields included."""

    def test_registering_a_hospital_returns_every_declared_field_it_was_given(
        self, api, officer
    ):
        """A create echoes the three supplied inputs and exposes the full declared key set.

        Only `name`, `npi` and `hospital_type` are supplied. The response must still be a
        complete `ReferringHospital` — the standard object envelope, a bare UUID id, the
        three inputs unchanged, and the optional flag resolved to its documented default
        rather than left absent or null.

        PRD 3.1: "Registering a referring acute-care hospital records its `name` (1 to 120 characters, required), its `npi` (exactly 10 digits, unique across all referring hospitals), and a `hospital_type` that is either `ACUTE_CARE` or `CRITICAL_ACCESS`."
        PRD 3.1: "An optional `is_colocated` flag, defaulting to false, marks hospitals that host the LTCH as a hospital-within-a-hospital."
        PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/entities/create_referring_hospital_returns_every_declared_field
        """
        response = api.create_referring_hospital(
            factories.referring_hospital_payload(
                name="Metro General", npi="1000000001", is_colocated=None
            ),
            headers=officer,
        )
        hospital = get_success_data(response, expected_status=201)

        body = response.json()
        assert body["response_type"] == "object", (
            "a single resource must come back as response_type 'object', got {!r}".format(
                body["response_type"]
            )
        )
        assert_exact_keys(hospital, "ReferringHospital")
        assert hospital["name"] == "Metro General"
        assert hospital["npi"] == "1000000001"
        assert hospital["hospital_type"] == HospitalType.ACUTE_CARE
        assert hospital["is_colocated"] is False, (
            "an omitted is_colocated must default to false, got {!r}".format(
                hospital["is_colocated"]
            )
        )

    def test_a_new_hospital_opens_compliant_at_a_twenty_five_percent_ceiling(
        self, api, officer
    ):
        """The four monitoring fields start at their documented opening values.

        An acute-care source that does not host the LTCH gets the base ceiling of 25.00
        rather than the expanded 50.00, and its live posture opens empty: no admissions
        counted, a zero share, and a state of `COMPLIANT` because nothing has been
        admitted from it yet.

        PRD 3.1: "Two of those inputs determine how much of the LTCH's admission mix this hospital is allowed to supply: a hospital's `threshold_pct` is 50.00 when `is_colocated` is true **or** its `hospital_type` is `CRITICAL_ACCESS`, and 25.00 otherwise."
        PRD 3.1: "A newly registered hospital starts with `admissions_in_period` at 0, `share_pct` at 0.00 and `monitoring_state` at `COMPLIANT`; the live posture is readable at any time and by every role."

        Design: Corner/entities/create_referring_hospital_returns_every_declared_field
        """
        hospital = get_success_data(
            api.create_referring_hospital(
                factories.referring_hospital_payload(
                    npi="1000000001", hospital_type=HospitalType.ACUTE_CARE, is_colocated=None
                ),
                headers=officer,
            ),
            expected_status=201,
        )

        assert_pct(hospital, "threshold_pct", BASE_REFERRAL_THRESHOLD_PCT)
        assert_integer_field(hospital, "admissions_in_period", 0)
        assert_pct(hospital, "share_pct", 0.00)
        assert hospital["monitoring_state"] == MonitoringState.COMPLIANT

    def test_a_new_hospital_opens_at_version_one_stamped_from_the_logical_clock(
        self, api, officer
    ):
        """The four common properties open at their documented initial values.

        Nothing has advanced the clock, so the row is stamped at the epoch the logical
        clock holds before any operator sets it. A record that has never been mutated
        carries `version` 1 and an `updated_at` that still denotes the creation instant.

        PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID with no type prefix; clients never supply an `id`."
        PRD 2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that row."
        PRD 2.4: "Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/entities/create_referring_hospital_returns_every_declared_field
        """
        hospital = get_success_data(
            api.create_referring_hospital(
                factories.referring_hospital_payload(npi="1000000001"), headers=officer
            ),
            expected_status=201,
        )

        assert_created_record(hospital)
        assert_instant_equals(hospital["created_at"], CLOCK_EPOCH, "created_at")


class TestPatientRetrieval:
    """A read gives back the stored inputs plus the counter the specification derives."""

    def test_reading_a_patient_echoes_the_registered_inputs_unchanged(self, api, intake):
        """The four registration inputs come back exactly as they were supplied.

        A patient is registered and then read. `mrn`, `full_name`, `birth_date` and
        `primary_payer` are stored inputs, not derived values, so the read must return
        them byte-for-byte, and the response must expose the entity's whole declared key
        set rather than a projection of it.

        PRD 3.1: "Patients are registered by either a `ComplianceOfficer` or an `IntakeCoordinator` with an `mrn` (1 to 24 characters, unique across patients), a `full_name` (1 to 120 characters), a `birth_date` in `YYYY-MM-DD` form, and a `primary_payer` drawn from `MEDICARE_FFS`, `MEDICARE_ADVANTAGE` or `COMMERCIAL`."

        Design: Corner/entities/get_patient_returns_the_stored_row_unchanged
        """
        world = fixtures.build_world(
            api,
            patient={
                "mrn": "MRN-200",
                "full_name": "Ada Read",
                "birth_date": "1944-02-02",
                "primary_payer": Payer.MEDICARE_FFS,
            },
        )
        fixtures.create_referral(api, world)

        patient = get_success_data(api.get_patient(world.patient_id, headers=intake))

        assert_exact_keys(patient, "Patient")
        assert patient["id"] == world.patient_id
        assert patient["mrn"] == "MRN-200"
        assert patient["full_name"] == "Ada Read"
        assert patient["birth_date"] == "1944-02-02"
        assert patient["primary_payer"] == Payer.MEDICARE_FFS

    def test_reading_a_patient_reports_one_open_referral_and_version_two(self, api, intake):
        """The read reports the live referral counter and the version the create advanced.

        The patient was registered with no referrals, so `open_referral_count` began at 0.
        Creating one referral that is still `RECEIVED` settles the counter at 1 and
        advances the patient row exactly once — the write the optimistic-concurrency check
        exists to serialize — so the version read back is 2, not the 1 the create returned.

        PRD 3.1: "A new patient's `open_referral_count` begins at 0."
        PRD 3.2: "Creation also does something destructive, which is what §2.6's version check protects: any other referral of the same patient whose `status` is `RECEIVED`, `INFO_REQUESTED` or `CRITERIA_MET` is flipped to `SUPERSEDED` (a terminal status), the patient's `version` advances by 1, and the patient's `open_referral_count` settles at 1 — one decrement for the superseded referral, one increment for the new one, so the net stays at 1."
        PRD 2.6: "On success the patient's `version` advances by 1, which invalidates every other in-flight referral create for that patient."

        Design: Corner/entities/get_patient_returns_the_stored_row_unchanged
        """
        world = fixtures.build_world(api, patient={"mrn": "MRN-200"})
        assert world.patient_version == 1, "a freshly registered patient opens at version 1"
        assert world.patient["open_referral_count"] == 0

        referral = fixtures.create_referral(api, world)
        assert referral["status"] == ReferralStatus.RECEIVED

        patient = get_success_data(api.get_patient(world.patient_id, headers=intake))

        assert_integer_field(patient, "open_referral_count", 1)
        assert_integer_field(patient, "version", 2)


def _three_referrals_one_withdrawn(api, intake):
    """Three referrals for three different patients, the third of them withdrawn.

    Each referral belongs to its own patient, so none of them supersedes another and the
    population stays at three rows: two still `RECEIVED` and one `WITHDRAWN`.
    """
    world = fixtures.build_world(api, patient={"mrn": "MRN-201", "full_name": "Bea One"})
    second = fixtures.add_patient(api, mrn="MRN-202", full_name="Cal Two")
    third = fixtures.add_patient(api, mrn="MRN-203", full_name="Dot Three")

    first_referral = fixtures.create_referral(api, world)
    second_referral = fixtures.create_referral(
        api, world, patient_id=second["id"], patient_version=second["version"]
    )
    third_referral = fixtures.create_referral(
        api, world, patient_id=third["id"], patient_version=third["version"]
    )
    get_success_data(
        api.withdraw_referral(third_referral["id"], headers=intake), expected_status=200
    )
    return first_referral["id"], second_referral["id"], third_referral["id"]


class TestReferralListing:
    """The referral list paginates over the whole population and filters on status."""

    def test_the_first_window_of_two_reports_the_population_not_the_page_size(
        self, api, intake
    ):
        """A two-record window over three referrals reports a total of three and more to come.

        `total_count` is the number of records matching the filter before pagination, so
        with no filter supplied it must read 3 even though the page carries 2. `limit` and
        `offset` echo the values actually used, and `has_more` is true because a third
        record remains beyond this window.

        PRD 2.3: "Every list response populates all four pagination fields in `meta`: `limit` and `offset` echo the effective values used for the query, `total_count` reports the number of records matching the filter before pagination, and `has_more` is true when records remain beyond the current page."

        Design: Corner/entities/list_referrals_paginates_and_filters_on_status
        """
        _three_referrals_one_withdrawn(api, intake)

        page, meta = validate_paginated(
            api.list_referrals(params={"limit": 2, "offset": 0}, headers=intake)
        )

        assert len(page) == 2, "a limit of 2 must return 2 records, got {}".format(len(page))
        assert_pagination_meta(
            _pagination_view(meta), total=3, limit=2, offset=0, has_more=True
        )

    def test_the_second_window_closes_the_population_without_repeating_a_record(
        self, api, intake
    ):
        """The two windows together cover the three referrals exactly once each.

        An offset of 2 over a population of 3 leaves a single record, so `has_more` turns
        false while `total_count` still reports 3. Taken together the two windows must
        enumerate all three referrals with no duplicate and nothing dropped — including
        the withdrawn one, which no filter has excluded.

        PRD 2.3: "`offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0."
        PRD 2.3: "Every list response populates all four pagination fields in `meta`: `limit` and `offset` echo the effective values used for the query, `total_count` reports the number of records matching the filter before pagination, and `has_more` is true when records remain beyond the current page."

        Design: Corner/entities/list_referrals_paginates_and_filters_on_status
        """
        first_id, second_id, third_id = _three_referrals_one_withdrawn(api, intake)

        page_one, _meta_one = validate_paginated(
            api.list_referrals(params={"limit": 2, "offset": 0}, headers=intake)
        )
        page_two, meta_two = validate_paginated(
            api.list_referrals(params={"limit": 2, "offset": 2}, headers=intake)
        )

        assert len(page_two) == 1, "the last window holds the single remaining record"
        assert_pagination_meta(
            _pagination_view(meta_two), total=3, limit=2, offset=2, has_more=False
        )
        seen = ids_of(page_one) + ids_of(page_two)
        assert len(seen) == len(set(seen)), "the two windows repeated a record: {}".format(seen)
        assert set(seen) == {first_id, second_id, third_id}

    def test_filtering_on_status_narrows_both_the_page_and_the_total(self, api, intake):
        """A status filter shrinks `total_count` to the matching population, not just the page.

        Two referrals are still `RECEIVED` and one has been withdrawn. Filtering on
        `RECEIVED` must return exactly the two, report a total of 2 rather than the
        unfiltered 3, and set `has_more` false because the filtered population fits in
        one page.

        PRD 3.2: "Referrals are readable individually with their full screening outcome, and listable with optional filters on `patient_id`, `referring_hospital_id`, `drg_rate_id`, `pinned_criteria_set_id` and `status`, alongside `limit` and `offset`."
        PRD 2.3: "Every list response populates all four pagination fields in `meta`: `limit` and `offset` echo the effective values used for the query, `total_count` reports the number of records matching the filter before pagination, and `has_more` is true when records remain beyond the current page."

        Design: Corner/entities/list_referrals_paginates_and_filters_on_status
        """
        first_id, second_id, third_id = _three_referrals_one_withdrawn(api, intake)

        page, meta = validate_paginated(
            api.list_referrals(
                params={"status": ReferralStatus.RECEIVED, "limit": 10, "offset": 0},
                headers=intake,
            )
        )

        assert_pagination_meta(
            _pagination_view(meta), total=2, limit=10, offset=0, has_more=False
        )
        assert_contains_only(page, [first_id, second_id])
        assert third_id not in ids_of(page), "the withdrawn referral must not match RECEIVED"
        for record in page:
            assert record["status"] == ReferralStatus.RECEIVED

    def test_omitting_both_pagination_parameters_uses_the_declared_defaults(
        self, api, intake
    ):
        """With no query parameters the list returns the whole population on one page.

        The documented defaults are a `limit` of 10 and an `offset` of 0, which is wide
        enough for all three referrals, so the effective values echoed back in `meta` must
        be those defaults rather than anything the client supplied.

        PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100."
        PRD 2.3: "`offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0."

        Design: Corner/entities/list_referrals_paginates_and_filters_on_status
        """
        first_id, second_id, third_id = _three_referrals_one_withdrawn(api, intake)

        page, meta = validate_paginated(api.list_referrals(headers=intake))

        assert len(page) == 3, "all three referrals fit inside the default page"
        assert_pagination_meta(
            _pagination_view(meta),
            total=3,
            limit=DEFAULT_LIMIT,
            offset=DEFAULT_OFFSET,
            has_more=False,
        )
        assert_contains_only(page, [first_id, second_id, third_id])


class TestUnknownPatientId:
    """A path id that resolves to no row produces that entity's own 404."""

    def test_reading_an_unknown_patient_id_returns_the_patient_specific_not_found(
        self, api, intake
    ):
        """A well-formed id matching no patient is refused as `ERR_PATIENT_NOT_FOUND`.

        The database is empty, so the id in the path resolves to nothing. Path existence
        is checked against the entity the path names, which means the refusal must be the
        patient-specific 404 carrying a machine-readable error id and a message — not a
        generic failure and not an empty success body.

        PRD 2.8: "Every entity `id` appearing in the request path resolves to an existing row, returning the type-specific 404: `ERR_REFERRAL_NOT_FOUND`, `ERR_STAY_NOT_FOUND`, `ERR_WEANING_PLAN_NOT_FOUND`, `ERR_INTERRUPTION_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_QUERY_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_HOSPITAL_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_CRITERIA_SET_NOT_FOUND` or `ERR_PHYSICIAN_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/entities/get_patient_with_unknown_id_returns_patient_not_found
        """
        response = api.get_patient(NON_EXISTENT_UUID, headers=intake)

        error = validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND)
        assert error["message"].strip(), "the refusal must carry a human-readable message"


class TestPatientPayloadShape:
    """Payload shape is checked before uniqueness or any other business rule."""

    def test_registering_a_patient_without_an_mrn_is_a_payload_shape_violation(
        self, api, intake
    ):
        """An absent `mrn` is refused as `ERR_VALIDATION` rather than stored as null.

        The `mrn` is a required registration input with no documented default, so a body
        that omits it fails the first check in the precedence order. Nothing later — not
        uniqueness, not authorization — gets a chance to run.

        PRD 3.1: "Patients are registered by either a `ComplianceOfficer` or an `IntakeCoordinator` with an `mrn` (1 to 24 characters, unique across patients), a `full_name` (1 to 120 characters), a `birth_date` in `YYYY-MM-DD` form, and a `primary_payer` drawn from `MEDICARE_FFS`, `MEDICARE_ADVANTAGE` or `COMMERCIAL`."
        PRD 2.8: "The request body carries every non-optional field named in the endpoint's input contract, each field parses to its declared type, numeric fields fall inside their declared range, and every enum-typed field holds one of that field's declared literals — this covers `hospital_type`, `primary_payer`, `specialty`, `discipline`, `destination`, `discharge_disposition`, `query_type`, `credential_status` and the `outcome` values of the weaning and review operations."

        Design: Corner/entities/create_patient_missing_required_mrn_returns_validation
        """
        response = api.create_patient(
            factories.patient_payload(mrn=None, full_name="No Mrn", birth_date="1955-05-05"),
            headers=intake,
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION)

    def test_registering_a_patient_with_a_payer_outside_the_catalogue_is_rejected(
        self, api, intake
    ):
        """A `primary_payer` outside the three declared literals is refused as `ERR_VALIDATION`.

        `primary_payer` is one of the enum-typed fields the payload-shape check names
        explicitly, so a value that is not one of the three documented payers is a format
        violation and not, for instance, silently coerced or stored verbatim.

        PRD 3.1: "Patients are registered by either a `ComplianceOfficer` or an `IntakeCoordinator` with an `mrn` (1 to 24 characters, unique across patients), a `full_name` (1 to 120 characters), a `birth_date` in `YYYY-MM-DD` form, and a `primary_payer` drawn from `MEDICARE_FFS`, `MEDICARE_ADVANTAGE` or `COMMERCIAL`."
        PRD 2.8: "The request body carries every non-optional field named in the endpoint's input contract, each field parses to its declared type, numeric fields fall inside their declared range, and every enum-typed field holds one of that field's declared literals — this covers `hospital_type`, `primary_payer`, `specialty`, `discipline`, `destination`, `discharge_disposition`, `query_type`, `credential_status` and the `outcome` values of the weaning and review operations."

        Design: Corner/entities/create_patient_missing_required_mrn_returns_validation
        """
        response = api.create_patient(
            factories.patient_payload(
                mrn="MRN-210", full_name="Bad Payer", primary_payer="CRYPTO"
            ),
            headers=intake,
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION)

    def test_a_rejected_registration_leaves_the_mrn_free_for_a_later_one(self, api, intake):
        """Neither rejection persists a partial row, so `MRN-210` is still available.

        Both refusals happen at the payload-shape check, ahead of the uniqueness rule, so
        no `Patient` row can have been written. A subsequent well-formed registration
        reusing the same `mrn` must therefore be created — at version 1, as a brand new
        row — instead of colliding with a ghost.

        PRD 2.8: "The server evaluates its checks in a fixed order and the **first** violated rule determines the response; no later check is evaluated once one has fired."
        PRD 2.8: "`DrgRateEntry.drg_code`, `ReferringHospital.npi`, `Physician.npi`, `Patient.mrn`, `AdmissionCriteriaSet.label` and `CostReportingPeriod.period_label` are each unique; a new criteria set's `effective_from` must be strictly after the `effective_from` of every `ACTIVE` set; a new period's `start_date` through `end_date` range must not overlap an existing period and only one period may be `OPEN` at a time."

        Design: Corner/entities/create_patient_missing_required_mrn_returns_validation
        """
        validate_error(
            api.create_patient(factories.patient_payload(mrn=None), headers=intake),
            ApiErrorId.ERR_VALIDATION,
        )
        validate_error(
            api.create_patient(
                factories.patient_payload(mrn="MRN-210", primary_payer="CRYPTO"),
                headers=intake,
            ),
            ApiErrorId.ERR_VALIDATION,
        )

        patient = get_success_data(
            api.create_patient(
                factories.patient_payload(mrn="MRN-210", primary_payer=Payer.MEDICARE_FFS),
                headers=intake,
            ),
            expected_status=201,
        )

        assert patient["mrn"] == "MRN-210"
        assert_created_record(patient)
        assert_integer_field(patient, "open_referral_count", 0)


class TestWeaningPlanAndNoteDefaults:
    """Omitted optional inputs fall back to their documented defaults, never to null."""

    def test_a_weaning_plan_opened_with_an_empty_body_takes_the_standard_protocol(
        self, api, nurse
    ):
        """Both optional plan inputs default, and every progression counter opens at zero.

        The nurse opens the plan without naming a protocol or seeding an hour total, so the
        label must read `STANDARD_SBT` rather than null and the cumulative ventilator-hour
        counter must read 0 — the hours from the preceding acute stay are deliberately not
        carried across. The plan itself opens in its initial trial state with nothing yet
        attempted, tolerated or closed.

        PRD 3.4: "Two optional inputs are accepted: `protocol_label`, a 1-to-40-character protocol identifier that defaults to `STANDARD_SBT`, and `vent_hours_total`, which seeds the plan's cumulative ventilator-hour counter and defaults to 0."
        PRD 3.4: "A new plan carries `stay_id`, enters `status` `SBT_TRIAL` with `current_step` 0, `sbt_attempt_count` 0, `consecutive_failed_sbt` 0, `max_tolerated_sbt_hours` 0, `liberation_eligible` false, and `last_progression_at`, `closed_at` and `closed_by_physician_id` all null."

        Design: Corner/entities/weaning_plan_and_idt_note_apply_their_declared_defaults
        """
        admission = fixtures.admitted_stay(api)

        plan = get_success_data(
            api.create_weaning_plan(admission.stay_id, headers=nurse), expected_status=201
        )

        assert_exact_keys(plan, "WeaningPlan")
        assert_created_record(plan)
        assert plan["stay_id"] == admission.stay_id
        assert plan["protocol_label"] == DEFAULT_PROTOCOL_LABEL
        assert plan["status"] == WeaningPlanStatus.SBT_TRIAL
        assert_vent_hours(plan, "vent_hours_total", 0)
        assert_vent_hours(plan, "max_tolerated_sbt_hours", 0)
        assert_integer_field(plan, "current_step", 0)
        assert_integer_field(plan, "sbt_attempt_count", 0)
        assert_integer_field(plan, "consecutive_failed_sbt", 0)
        assert plan["liberation_eligible"] is False
        assert_unset(plan, "last_progression_at", "closed_at", "closed_by_physician_id")

    def test_a_note_filed_without_the_goals_flag_records_it_as_false(self, api, nurse):
        """An omitted `goals_documented` reads false, and the admission note lands in week 0.

        The flag is optional with a documented default, so leaving it out must produce the
        boolean false and not null. The note is filed on the same calendar date as the
        admission, and the week index is the whole-day offset divided by seven and rounded
        down, so a zero-day offset puts this note in week 0.

        PRD 3.4: "A note names its `discipline` — one of `PHYSICIAN`, `NURSING`, `RESPIRATORY_THERAPY`, `CASE_MANAGEMENT`, `NUTRITION` or `PT_OT` — carries `note_text` of 1 to 2000 characters, and may set the optional `goals_documented` flag, which defaults to false and records whether measurable weekly goals appear in the note."
        PRD 3.4: "The system stamps `documented_at` from the logical clock and computes `week_index` as the whole-day count from the stay's `admitted_at` to `documented_at`, divided by 7 and rounded down, so the admission week is week 0."

        Design: Corner/entities/weaning_plan_and_idt_note_apply_their_declared_defaults
        """
        admission = fixtures.admitted_stay(api)

        note = get_success_data(
            api.create_idt_note(
                admission.stay_id,
                factories.idt_note_payload(
                    discipline=Discipline.NURSING, note_text="Admission assessment complete."
                ),
                headers=nurse,
            ),
            expected_status=201,
        )

        assert_exact_keys(note, "IdtNote")
        assert note["goals_documented"] is False, (
            "an omitted goals_documented must default to false, got {!r}".format(
                note["goals_documented"]
            )
        )
        assert_integer_field(note, "week_index", 0)

    def test_an_admission_that_needed_no_override_carries_the_admission_defaults(
        self, api
    ):
        """A stay created without an override counts toward the mix and records no override.

        Nothing about this admission needed justifying: the referral source is compliant,
        so the request supplied no `override_reason`. The new stay must therefore count
        toward the admission threshold, carry the override flag as false rather than null,
        and hold no justification text.

        PRD 3.3: "The new stay's `patient_id` and `referral_id` are copied from the admitting referral, its `cost_reporting_period_id` is the selected open period, its `clinical_status` is `ADMITTED`, its `payment_review_status` is `PENDING`, its `admitted_at` is the supplied value or the current logical instant, and its `counts_toward_admission_threshold` is true."
        PRD 3.3: "Supplying one lets the admission proceed, records `admitted_with_override` as true on the resulting stay and stores the justification in `override_reason`; admissions that did not need an override carry `admitted_with_override` false and `override_reason` null."

        Design: Corner/entities/weaning_plan_and_idt_note_apply_their_declared_defaults
        """
        admission = fixtures.admitted_stay(api)

        stay = fixtures.read_stay(api, admission.stay_id)

        assert_exact_keys(stay, "Stay")
        assert_stay_dimensions(stay, ClinicalStatus.ADMITTED, PaymentReviewStatus.PENDING)
        assert stay["counts_toward_admission_threshold"] is True
        assert stay["admitted_with_override"] is False
        assert_unset(stay, "override_reason")


class TestScreeningRecomputation:
    """`data_complete`, `missing_fields` and `qualifying_track` are recomputed, never supplied."""

    def test_a_freshly_created_referral_holds_the_unscreened_verdict(self, api, intake):
        """Creation leaves every screening output at its unevaluated value.

        The referral is filed with none of the five clinical inputs, and no screening has
        run yet, so the track must read `NONE` rather than a guess, the completeness flag
        must read false rather than null, the screen counter must be 0 and no criteria set
        may be pinned — pinning is the first act of screening, not of creation.

        PRD 3.2: "A newly created referral enters `RECEIVED` with `qualifying_track` `NONE`, `screened_count` 0, `data_complete` false and `pinned_criteria_set_id` null."

        Design: Corner/entities/screening_recomputes_data_complete_and_qualifying_track
        """
        world = fixtures.build_world(api)

        referral = fixtures.create_referral(api, world, clinicals={})

        assert_exact_keys(referral, "Referral")
        assert referral["status"] == ReferralStatus.RECEIVED
        assert referral["qualifying_track"] == QualifyingTrack.NONE
        assert referral["data_complete"] is False
        assert_integer_field(referral, "screened_count", 0)
        assert_unset(referral, "pinned_criteria_set_id")

    def test_screening_an_empty_referral_names_all_five_missing_inputs(self, api, intake):
        """An incomplete screen stops at completeness and lists every null input by name.

        None of the five required inputs was supplied, so completeness fails and the
        evaluation must stop before any track arithmetic: the referral bounces to
        `INFO_REQUESTED`, the track stays `NONE`, and `missing_fields` names all five.
        The screen still happened, so the counter advances to 1.

        PRD 3.2: "The names of whichever of those five are null are written into `missing_fields` as an array of strings, and `data_complete` is set to true only when `missing_fields` is empty."
        PRD 3.2: "If the data is incomplete, the referral moves `RECEIVED → INFO_REQUESTED`, `qualifying_track` is left at `NONE`, and evaluation stops there."
        PRD 3.2: "Every screening evaluation, whatever its verdict, increases `screened_count` by 1."

        Design: Corner/entities/screening_recomputes_data_complete_and_qualifying_track
        """
        world = fixtures.build_world(api)
        referral = fixtures.create_referral(api, world, clinicals={})

        screened = fixtures.screen_referral(api, referral["id"])

        assert screened["status"] == ReferralStatus.INFO_REQUESTED
        assert screened["qualifying_track"] == QualifyingTrack.NONE
        assert screened["data_complete"] is False
        assert_integer_field(screened, "screened_count", 1)
        assert set(screened["missing_fields"]) == set(types.SCREENING_INPUT_FIELDS), (
            "missing_fields must name exactly the five required inputs, got {!r}".format(
                screened["missing_fields"]
            )
        )
        assert len(screened["missing_fields"]) == len(types.SCREENING_INPUT_FIELDS), (
            "missing_fields must not repeat a name, got {!r}".format(
                screened["missing_fields"]
            )
        )

    def test_submitting_the_late_data_completes_the_referral_on_the_ventilation_track(
        self, api, intake
    ):
        """The late submission clears `missing_fields`, flips completeness and resolves `PMV`.

        The five inputs arrive together, so the re-run finds nothing null: the list empties,
        completeness becomes true and the track resolves. The supplied 240 ventilator hours
        and 5 ICU days both clear the pinned set's ventilation minimums of 96 and 3, and the
        ventilation criterion is evaluated first, so the verdict is `PMV` and the referral
        reaches `CRITERIA_MET`. This is a second evaluation, so the counter reads 2, and the
        set selected for it is the only active one on the current logical date.

        PRD 3.2: "The evaluation then re-runs in full, and here is the subtlety: **the criteria set is re-selected against the current logical date, not against the date of the original screen.**"
        PRD 3.2: "The prolonged-mechanical-ventilation criterion is met when `vent_hours_at_referral` is at least the pinned set's `pmv_min_vent_hours` **and** `icu_days_at_referral` is at least its `pmv_min_icu_days`."
        PRD 3.2: "If the data is now complete and a track matches, the referral moves `INFO_REQUESTED → CRITERIA_MET`."

        Design: Corner/entities/screening_recomputes_data_complete_and_qualifying_track
        """
        world = fixtures.build_world(api)
        referral = fixtures.create_referral(api, world, clinicals={})
        fixtures.screen_referral(api, referral["id"])

        completed = fixtures.submit_info(
            api, referral["id"], **dict(factories.PMV_CLINICALS)
        )

        assert completed["status"] == ReferralStatus.CRITERIA_MET
        assert completed["qualifying_track"] == QualifyingTrack.PMV
        assert completed["data_complete"] is True
        assert completed["missing_fields"] == [], (
            "a complete referral must carry an empty missing_fields, got {!r}".format(
                completed["missing_fields"]
            )
        )
        assert_integer_field(completed, "screened_count", 2)
        assert completed["pinned_criteria_set_id"] == world.criteria_set_id


class TestNoteStamping:
    """`documented_at` comes from the logical clock and `week_index` from the admission date."""

    def test_a_note_filed_on_the_admission_date_is_stamped_at_the_clock_epoch(
        self, api, nurse
    ):
        """The filing instant is read from the logical clock, not from the wall clock.

        Nothing has moved the clock, so it still reads its documented starting instant, and
        that is the instant the note must carry. The note is filed on the admission date
        itself, a whole-day offset of zero, which floors to week 0. Being append-only, the
        record exposes `id` and `created_at` and neither `updated_at` nor `version`.

        PRD 2.4: "Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."
        PRD 3.4: "The system stamps `documented_at` from the logical clock and computes `week_index` as the whole-day count from the stay's `admitted_at` to `documented_at`, divided by 7 and rounded down, so the admission week is week 0."

        Design: Corner/entities/idt_note_documented_at_and_week_index_are_server_stamped
        """
        admission = fixtures.admitted_stay(api)

        note = fixtures.file_note(api, admission.stay_id, Discipline.NURSING)

        assert_exact_keys(note, "IdtNote")
        assert_immutable_record(note)
        assert_instant_equals(note["documented_at"], CLOCK_EPOCH)
        assert_instant_equals(note["created_at"], CLOCK_EPOCH)
        assert_integer_field(note, "week_index", 0)
        assert note["stay_id"] == admission.stay_id

    def test_advancing_the_clock_reports_the_instant_it_replaced(self, api):
        """The clock advance echoes both the new instant and the one it superseded.

        The admission happened at the starting instant, and the operator now moves the clock
        eight days forward. The response must name the new instant and the previous one, so
        the caller can see exactly which instant later stamps will read from.

        PRD 2.4: "An operator in any of the five roles may advance the clock by supplying a `current_utc` instant; the response reports the new `current_utc` alongside the `previous_utc` it replaced."

        Design: Corner/entities/idt_note_documented_at_and_week_index_are_server_stamped
        """
        fixtures.admitted_stay(api)

        moved = fixtures.advance_clock(api, "2026-08-09T00:00:00Z")

        assert_instant_equals(moved["current_utc"], "2026-08-09T00:00:00Z")
        assert_instant_equals(moved["previous_utc"], CLOCK_EPOCH)

    def test_a_note_filed_eight_days_after_admission_lands_in_week_one(self, api, nurse):
        """Eight whole days after admission floors to the second week of the stay.

        The stay was admitted at the starting instant and the clock is moved to the ninth of
        August, a whole-day count of 8. Dividing by seven and rounding down puts the note in
        week 1 — the admission week itself being week 0 — and the note must be stamped with
        the moved clock rather than the admission instant.

        PRD 2.5: "The day count between two instants is the difference between their UTC *calendar dates*, expressed in whole days; the later day is not itself counted."
        PRD 3.4: "The system stamps `documented_at` from the logical clock and computes `week_index` as the whole-day count from the stay's `admitted_at` to `documented_at`, divided by 7 and rounded down, so the admission week is week 0."

        Design: Corner/entities/idt_note_documented_at_and_week_index_are_server_stamped
        """
        admission = fixtures.admitted_stay(api)
        fixtures.advance_clock(api, "2026-08-09T00:00:00Z")

        note = fixtures.file_note(api, admission.stay_id, Discipline.PT_OT)

        assert_instant_equals(note["documented_at"], "2026-08-09T00:00:00Z")
        assert_integer_field(note, "week_index", 1)

    def test_both_filed_notes_remain_listed_and_unchanged(self, api, nurse):
        """Filing never rewrites an earlier note: the stay lists both, oldest first.

        One note is filed on the admission date and a second eight days later, so the two
        carry distinct instants and their creation order is unambiguous. Notes are
        append-only, so the listing must return both records, each still exposing only the
        two common properties an append-only entity carries.

        PRD 3.4: "Notes are strictly append-only: there is no update and no delete, and a filed note never changes."
        PRD 2.3: "Unless a specific endpoint's description states otherwise, list results are ordered by `created_at` ascending."

        Design: Corner/entities/idt_note_documented_at_and_week_index_are_server_stamped
        """
        admission = fixtures.admitted_stay(api)
        first = fixtures.file_note(api, admission.stay_id, Discipline.NURSING)
        fixtures.advance_clock(api, "2026-08-09T00:00:00Z")
        second = fixtures.file_note(api, admission.stay_id, Discipline.PT_OT)

        notes = fixtures.notes_of(api, admission.stay_id)

        assert_ids_equal(notes, [first["id"], second["id"]])
        for note in notes:
            assert_exact_keys(note, "IdtNote")
            assert_immutable_record(note)
        assert_integer_field(notes[0], "week_index", 0)
        assert_integer_field(notes[1], "week_index", 1)


class TestReferenceDataPayloadShape:
    """An undeclared enum literal and an inverted date range are both shape violations."""

    def test_registering_a_hospital_of_an_undeclared_type_is_rejected(self, api, officer):
        """`hospital_type` accepts two literals, and a third is not one of them.

        The registration names a facility type that does not appear among the declared
        literals. Enum membership is part of the payload-shape check, the very first rule
        evaluated, so the request is refused on shape rather than being stored with an
        unrecognised type or coerced to the default.

        PRD 3.1: "Registering a referring acute-care hospital records its `name` (1 to 120 characters, required), its `npi` (exactly 10 digits, unique across all referring hospitals), and a `hospital_type` that is either `ACUTE_CARE` or `CRITICAL_ACCESS`."
        PRD 2.8: "The request body carries every non-optional field named in the endpoint's input contract, each field parses to its declared type, numeric fields fall inside their declared range, and every enum-typed field holds one of that field's declared literals — this covers `hospital_type`, `primary_payer`, `specialty`, `discipline`, `destination`, `discharge_disposition`, `query_type`, `credential_status` and the `outcome` values of the weaning and review operations."

        Design: Corner/entities/create_referring_hospital_with_an_invalid_enum_is_rejected
        """
        response = api.create_referring_hospital(
            factories.referring_hospital_payload(
                name="Undeclared Type General", hospital_type="URGENT_CARE"
            ),
            headers=officer,
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION)

    def test_opening_a_period_that_ends_before_it_starts_is_rejected(self, api, officer):
        """A period's end must be strictly later than its start, so an inverted range fails.

        The request asks for a fiscal envelope whose end date precedes its start date by
        almost a year. The declared range constraint is part of the endpoint's input
        contract, so the period is refused outright rather than opened with a negative span
        that no admission date could ever fall inside.

        PRD 3.1: "Cost reporting periods are opened with a `period_label` (1 to 40 characters, unique), a `start_date` and an `end_date`, where the `end_date` must be strictly later than the `start_date`."

        Design: Corner/entities/create_referring_hospital_with_an_invalid_enum_is_rejected
        """
        response = api.create_period(
            factories.period_payload(
                period_label="BACKWARDS", start_date="2027-06-30", end_date="2026-07-01"
            ),
            headers=officer,
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION)

    def test_a_rejected_period_leaves_the_calendar_free_for_a_valid_one(
        self, api, officer
    ):
        """Neither rejection wrote a row, so the same span opens cleanly afterwards.

        Both refused requests were rejected on shape, before any row was written, so the
        fiscal calendar is untouched: the well-formed period covering the same span opens
        normally, in `OPEN` with an empty ledger and no close instant.

        PRD 2.7: "A period's `status` is `OPEN` while it accrues admissions and payments and `CLOSED` once an operator closes it; `closed_at` records the logical instant of the close and is null while the period is `OPEN`."
        PRD 2.7: "A newly opened period begins with `total_admissions` 0, `total_payment_cents` 0 and `final_determination_count` 0."

        Design: Corner/entities/create_referring_hospital_with_an_invalid_enum_is_rejected
        """
        validate_error(
            api.create_referring_hospital(
                factories.referring_hospital_payload(hospital_type="URGENT_CARE"),
                headers=officer,
            ),
            ApiErrorId.ERR_VALIDATION,
        )
        validate_error(
            api.create_period(
                factories.period_payload(
                    period_label="FY2027", start_date="2027-06-30", end_date="2026-07-01"
                ),
                headers=officer,
            ),
            ApiErrorId.ERR_VALIDATION,
        )

        period = get_success_data(
            api.create_period(factories.period_payload(), headers=officer),
            expected_status=201,
        )

        assert_exact_keys(period, "CostReportingPeriod")
        assert_created_record(period)
        assert period["period_label"] == "FY2027"
        assert period["status"] == PeriodStatus.OPEN
        assert_unset(period, "closed_at")
        assert_integer_field(period, "total_admissions", 0)
        assert_cents(period, "total_payment_cents", 0)
        assert_integer_field(period, "final_determination_count", 0)


class TestAppendOnlyEntities:
    """The two exempt entities expose two common properties, and neither is updatable."""

    def test_a_new_rate_entry_carries_no_version_and_no_updated_at(self, api, officer):
        """A rate entry is written once, so the two mutation-tracking keys are absent.

        The exemption is not a null value but an absence: an append-only row publishes `id`
        and `created_at` and nothing else from the common set, because there is no mutation
        for `updated_at` to record and no revision for `version` to count.

        PRD 2.4: "Two entities are deliberately exempt because they are append-only and never change once written: a `DrgRateEntry` and an `IdtNote` carry only `id` and `created_at` — for those two, `updated_at` and `version` are absent from the response entirely."

        Design: Corner/entities/drg_rate_and_idt_note_expose_no_version_and_no_mutation_endpoint
        """
        entry = get_success_data(
            api.create_drg_rate(factories.drg_rate_payload(), headers=officer),
            expected_status=201,
        )

        assert_exact_keys(entry, "DrgRateEntry")
        assert_immutable_record(entry)
        assert "version" not in entry, (
            "an append-only DrgRateEntry must omit version entirely, got {!r}".format(
                entry.get("version")
            )
        )
        assert "updated_at" not in entry, (
            "an append-only DrgRateEntry must omit updated_at entirely, got {!r}".format(
                entry.get("updated_at")
            )
        )

    def test_a_filed_note_carries_no_version_and_no_updated_at(self, api, nurse):
        """The other exempt entity behaves identically: two common properties, no more.

        A note is the second append-only record, and the same exemption applies to it — the
        two mutation-tracking keys must be missing from the response rather than present and
        null.

        PRD 2.4: "Two entities are deliberately exempt because they are append-only and never change once written: a `DrgRateEntry` and an `IdtNote` carry only `id` and `created_at` — for those two, `updated_at` and `version` are absent from the response entirely."

        Design: Corner/entities/drg_rate_and_idt_note_expose_no_version_and_no_mutation_endpoint
        """
        admission = fixtures.admitted_stay(api)

        note = fixtures.file_note(api, admission.stay_id, Discipline.RESPIRATORY_THERAPY)

        assert_exact_keys(note, "IdtNote")
        assert_immutable_record(note)
        assert "version" not in note, (
            "an append-only IdtNote must omit version entirely, got {!r}".format(
                note.get("version")
            )
        )
        assert "updated_at" not in note, (
            "an append-only IdtNote must omit updated_at entirely, got {!r}".format(
                note.get("updated_at")
            )
        )

    def test_reposting_the_same_drg_code_collides_instead_of_updating_the_row(
        self, api, officer
    ):
        """A second post of code 207 is a uniqueness collision, not an upsert.

        The code is declared unique, and there is no update path for a rate entry, so the
        second registration of `207` — carrying a different weight and a different average
        length of stay — must be refused rather than silently replacing the first. The
        rejection is a duplicate key, which is the specification's answer for a repeated
        unique value.

        PRD 2.8: "`DrgRateEntry.drg_code`, `ReferringHospital.npi`, `Physician.npi`, `Patient.mrn`, `AdmissionCriteriaSet.label` and `CostReportingPeriod.period_label` are each unique; a new criteria set's `effective_from` must be strictly after the `effective_from` of every `ACTIVE` set; a new period's `start_date` through `end_date` range must not overlap an existing period and only one period may be `OPEN` at a time."

        Design: Corner/entities/drg_rate_and_idt_note_expose_no_version_and_no_mutation_endpoint
        """
        get_success_data(
            api.create_drg_rate(factories.drg_rate_payload(), headers=officer),
            expected_status=201,
        )

        response = api.create_drg_rate(
            factories.drg_rate_payload(
                drg_code="207",
                relative_weight=9.99,
                alos_days=99,
                standard_federal_rate_cents=1,
                ipps_comparable_per_diem_cents=1,
                ipps_comparable_full_cents=1,
            ),
            headers=officer,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY)

    def test_the_rejected_repost_leaves_the_priced_snapshot_on_the_original_rate(
        self, api, officer, nurse
    ):
        """Pricing after the collision still reads the first entry's weight and average stay.

        The refused second post carried a weight of 9.99 and an average stay of 99 days. If
        it had overwritten the row, the determination raised at discharge would freeze those
        figures. It must instead freeze the originally registered `207` at weight 1.25 and 30
        average days, which is the only visible proof the stored row was untouched.

        PRD 3.7: "The snapshot fields are `drg_code_used`, `relative_weight_used`, `alos_days_used`, `ipps_per_diem_used_cents`, `ipps_full_used_cents` — copied from the DRG in force — and `covered_los_days_used`, copied from the stay's `covered_los_days` at pricing time."

        Design: Corner/entities/drg_rate_and_idt_note_expose_no_version_and_no_mutation_endpoint
        """
        world = fixtures.build_world(api)
        validate_error(
            api.create_drg_rate(
                factories.drg_rate_payload(
                    drg_code="207", relative_weight=9.99, alos_days=99
                ),
                headers=officer,
            ),
            ApiErrorId.ERR_DUPLICATE_KEY,
        )

        admission = fixtures.discharged_stay(api, world=world)
        determination = fixtures.sole_determination(api, admission.stay_id)

        assert determination["drg_code_used"] == "207"
        assert assertions.round_half_up(
            determination["relative_weight_used"], 2
        ) == assertions.round_half_up(1.25, 2), (
            "relative_weight_used = {!r}, expected the originally registered 1.25".format(
                determination["relative_weight_used"]
            )
        )
        assert_integer_field(determination, "alos_days_used", 30)
        assert_cents(determination, "ipps_per_diem_used_cents", 90000)
        assert_cents(determination, "ipps_full_used_cents", 2400000)


class TestUnknownDrgRateOnReferralCreation:
    """A body foreign key that resolves to nothing names the entity it could not find."""

    def test_a_referral_naming_a_phantom_rate_entry_returns_the_rate_specific_not_found(
        self, api, intake
    ):
        """The patient and the source exist, so the only unresolvable reference is the rate.

        No rate entry has ever been registered, so the `drg_rate_id` in the body resolves to
        no row. Body foreign keys are checked by lookup, and each one has its own 404, so the
        caller must be told the DRG rate is what is missing rather than being handed a generic
        not-found or a validation error.

        PRD 2.8: "Every foreign key supplied in the body resolves to an existing row — `patient_id`, `referring_hospital_id`, `drg_rate_id`, `physician_id`, `cost_reporting_period_id`, `interrupted_parent_stay_id`, `referral_id`, `stay_id` and `review_id` — returning `ERR_PATIENT_NOT_FOUND`, `ERR_HOSPITAL_NOT_FOUND`, `ERR_DRG_RATE_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_STAY_NOT_FOUND` or `ERR_REFERRAL_NOT_FOUND` as appropriate."

        Design: Corner/entities/create_referral_with_an_unknown_drg_rate_returns_drg_rate_not_found
        """
        hospital = fixtures.add_hospital(api)
        patient = fixtures.add_patient(api, mrn="MRN-250", full_name="Hal Orphan")

        response = api.create_referral(
            factories.referral_payload(
                patient["id"], hospital["id"], NON_EXISTENT_UUID, patient["version"]
            ),
            headers=intake,
        )

        validate_error(response, ApiErrorId.ERR_DRG_RATE_NOT_FOUND)

    def test_the_rejected_referral_performs_no_write_on_the_patient(self, api, intake):
        """A refused create leaves the patient at version 1 with no open referral.

        Creating a referral is the one operation that mutates the patient — it advances the
        version and settles the open-referral counter. A create that never got past the
        foreign-key check must perform neither half of that, so the patient must still read
        exactly as it did at registration.

        PRD 2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that row."
        PRD 3.1: "A new patient's `open_referral_count` begins at 0."

        Design: Corner/entities/create_referral_with_an_unknown_drg_rate_returns_drg_rate_not_found
        """
        hospital = fixtures.add_hospital(api)
        patient = fixtures.add_patient(api, mrn="MRN-250", full_name="Hal Orphan")
        validate_error(
            api.create_referral(
                factories.referral_payload(
                    patient["id"], hospital["id"], NON_EXISTENT_UUID, patient["version"]
                ),
                headers=intake,
            ),
            ApiErrorId.ERR_DRG_RATE_NOT_FOUND,
        )

        reread = fixtures.read_patient(api, patient["id"], headers=intake)

        assert reread["version"] == patient["version"] == 1
        assert_integer_field(reread, "open_referral_count", 0)

    def test_the_rejected_referral_leaves_the_referral_collection_empty(self, api, intake):
        """Nothing was stored, so the listing reports an empty population.

        A rejected create must not leave a partial row behind. The list endpoint reports the
        pre-pagination population, so a `total_count` of 0 alongside an empty page is the
        direct evidence that no referral was written.

        PRD 2.3: "Every list response populates all four pagination fields in `meta`: `limit` and `offset` echo the effective values used for the query, `total_count` reports the number of records matching the filter before pagination, and `has_more` is true when records remain beyond the current page."

        Design: Corner/entities/create_referral_with_an_unknown_drg_rate_returns_drg_rate_not_found
        """
        hospital = fixtures.add_hospital(api)
        patient = fixtures.add_patient(api, mrn="MRN-250", full_name="Hal Orphan")
        validate_error(
            api.create_referral(
                factories.referral_payload(
                    patient["id"], hospital["id"], NON_EXISTENT_UUID, patient["version"]
                ),
                headers=intake,
            ),
            ApiErrorId.ERR_DRG_RATE_NOT_FOUND,
        )

        page, meta = validate_paginated(api.list_referrals(headers=intake))

        assert page == [], "expected no stored referrals, got {!r}".format(ids_of(page))
        assert_pagination_meta(
            _pagination_view(meta),
            total=0,
            limit=DEFAULT_LIMIT,
            offset=DEFAULT_OFFSET,
            has_more=False,
        )


def _one_admitted_and_one_discharged_patient(api):
    """Two patients in the same period: one still admitted, the other already discharged.

    Jon is admitted at the starting instant, the clock moves to the fifth of August, and Jon
    is discharged there. Ivy is then admitted on that same date, so the discharge she might
    be folded into is only three or fewer whole days old — the calendar window is wide open,
    which leaves the parentage requirement as the only thing under test.
    """
    world = fixtures.build_world(api, patient={"mrn": "MRN-261", "full_name": "Ivy Child"})
    jon = fixtures.add_patient(api, mrn="MRN-262", full_name="Jon Other")

    jon_admission = fixtures.admitted_stay(
        api, world=world, patient_id=jon["id"], patient_version=jon["version"]
    )
    fixtures.advance_clock(api, "2026-08-05T00:00:00Z")
    fixtures.discharge(api, jon_admission.stay_id)

    ivy_admission = fixtures.admitted_stay(api, world=world)
    return world, ivy_admission.stay_id, jon_admission.stay_id


class TestRecombinationParentage:
    """The hand-supplied parent link is checked for existence, ownership and identity."""

    def test_a_parent_id_matching_no_stay_returns_the_stay_specific_not_found(
        self, api, officer
    ):
        """An unresolvable parent id is a missing stay, not a window violation.

        The parent is supplied in the body, so it is a body foreign key: before the
        specification can judge ownership, dates or state, the id has to resolve to a row at
        all. A phantom id therefore produces the stay-specific not-found rather than the
        parentage refusal.

        PRD 3.5: "A parent id that resolves to no stay at all yields `ERR_STAY_NOT_FOUND`."

        Design: Corner/entities/recombine_against_a_parent_stay_of_another_patient_is_rejected
        """
        _, ivy_stay_id, _ = _one_admitted_and_one_discharged_patient(api)

        response = api.recombine_stay(
            ivy_stay_id, factories.recombine_payload(NON_EXISTENT_UUID), headers=officer
        )

        validate_error(response, ApiErrorId.ERR_STAY_NOT_FOUND)

    def test_a_parent_stay_belonging_to_another_patient_is_refused(self, api, officer):
        """Same-patient identity is part of the parentage rule, so a stranger's stay is refused.

        Jon's stay exists, sits in `DISCHARGED`, belongs to the same period and was discharged
        on the very date Ivy was admitted, so nothing about the calendar window is at fault.
        The single defect is that the stay belongs to a different patient, and the
        specification folds that requirement into the same rule as the window rather than
        reporting it as a separate not-found.

        PRD 2.8: "`interrupted_parent_stay_id` must reference a *different* stay of the *same* patient whose `clinical_status` is `DISCHARGED` and whose `discharged_at` is no more than 3 whole days before the child stay's `admitted_at`; otherwise `ERR_RECOMBINATION_WINDOW_EXCEEDED` (422)."

        Design: Corner/entities/recombine_against_a_parent_stay_of_another_patient_is_rejected
        """
        _, ivy_stay_id, jon_stay_id = _one_admitted_and_one_discharged_patient(api)

        response = api.recombine_stay(
            ivy_stay_id, factories.recombine_payload(jon_stay_id), headers=officer
        )

        validate_error(response, ApiErrorId.ERR_RECOMBINATION_WINDOW_EXCEEDED)

    def test_naming_the_child_stay_as_its_own_parent_is_refused(self, api, officer):
        """A stay cannot be folded into itself: the parent must be a different stay.

        Here the patient matches trivially, but the named parent is the child itself, which
        fails both halves of the rule — it is not a different stay, and it is not
        `DISCHARGED`. The parentage refusal is the declared answer.

        PRD 3.5: "The named parent must be a different stay, belong to the same patient, sit in `clinical_status` `DISCHARGED`, belong to the same cost reporting period, and have a `discharged_at` no more than 3 whole days before the child's `admitted_at`; at exactly 3 days the fold is accepted, at 4 days it is refused with `ERR_RECOMBINATION_WINDOW_EXCEEDED`."

        Design: Corner/entities/recombine_against_a_parent_stay_of_another_patient_is_rejected
        """
        _, ivy_stay_id, _ = _one_admitted_and_one_discharged_patient(api)

        response = api.recombine_stay(
            ivy_stay_id, factories.recombine_payload(ivy_stay_id), headers=officer
        )

        validate_error(response, ApiErrorId.ERR_RECOMBINATION_WINDOW_EXCEEDED)

    def test_none_of_the_three_refusals_partially_reopens_a_stay(self, api, officer):
        """After all three rejections both stays hold their original clinical status.

        A successful fold would move the child to `RECOMBINED` and reopen the parent to
        `ADMITTED`. None of these three requests got past its integrity check, so Ivy's stay
        must still be `ADMITTED` and Jon's still `DISCHARGED` — no half-applied fold.

        PRD 3.5: "The **child** moves `ADMITTED → RECOMBINED`, which is terminal — no further clinical transition is possible on it — records the parent's id in `interrupted_parent_stay_id`, and sets `counts_toward_admission_threshold` to false."
        PRD 3.5: "The **parent** is reopened, moving `DISCHARGED → ADMITTED`."

        Design: Corner/entities/recombine_against_a_parent_stay_of_another_patient_is_rejected
        """
        _, ivy_stay_id, jon_stay_id = _one_admitted_and_one_discharged_patient(api)
        for parent_id in (NON_EXISTENT_UUID, jon_stay_id, ivy_stay_id):
            api.recombine_stay(
                ivy_stay_id, factories.recombine_payload(parent_id), headers=officer
            )

        ivy_stay = fixtures.read_stay(api, ivy_stay_id)
        jon_stay = fixtures.read_stay(api, jon_stay_id)

        assert ivy_stay["clinical_status"] == ClinicalStatus.ADMITTED
        assert jon_stay["clinical_status"] == ClinicalStatus.DISCHARGED
        assert_unset(ivy_stay, "interrupted_parent_stay_id")
        assert ivy_stay["counts_toward_admission_threshold"] is True

    def test_none_of_the_three_refusals_moves_the_admission_counters(self, api, officer):
        """The period and the referral source still count both admissions.

        A completed fold decrements both the period's admission total and the child's
        referring hospital's count, because the child stops counting toward the mix. Three
        refusals must leave both counters where the two admissions put them, at 2.

        PRD 3.5: "Because the child stopped counting as an admission, the child's referring hospital has its `admissions_in_period` decreased by 1 and the period's `total_admissions` is decreased by 1; and because the denominator moved, `share_pct`, `threshold_pct` and `monitoring_state` are recomputed for every referring hospital exactly as at admission."

        Design: Corner/entities/recombine_against_a_parent_stay_of_another_patient_is_rejected
        """
        world, ivy_stay_id, jon_stay_id = _one_admitted_and_one_discharged_patient(api)
        for parent_id in (NON_EXISTENT_UUID, jon_stay_id, ivy_stay_id):
            api.recombine_stay(
                ivy_stay_id, factories.recombine_payload(parent_id), headers=officer
            )

        period = fixtures.read_period(api, world.period_id)
        hospital = fixtures.read_hospital(api, world.hospital_id)

        assert_integer_field(period, "total_admissions", 2)
        assert_integer_field(hospital, "admissions_in_period", 2)
