"""Volunteer registration defaults, readiness ladder, certification lifecycle,
readiness scoring variants, and immediate-consistency reads."""
from test_helpers import (
    AVAILABILITY_END,
    AVAILABILITY_START,
    AVAILABILITY_WINDOW,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_certification,
    assert_certification,
    assert_volunteer,
    build_user_headers,
    get_certification,
    get_volunteer,
    make_volunteer_headers,
    parse_iso,
    register_volunteer,
    run_ops_epoch,
    set_clock,
    setup_fatigued_volunteer,
    transition_volunteer,
    validate_error,
    validate_success,
    verify_certification,
)


def test_volunteer_registration_applies_defaults(api, system_admin_headers):
    """PRD §3.1: "A freshly registered volunteer has `readiness_status` `REGISTERED`, both readiness scores at 0, and `fatigue_hours` at 0."
    PRD §3.1: "Registration may also carry `availability_windows`, a list of deployment availability intervals each described by a `start_iso8601` and an `end_iso8601` treated as a closed interval, and `instructor_certified`, a flag defaulting to false that marks whether the volunteer may lead training courses; an empty availability list is the default when none is supplied."

    Design: Corner/entities/volunteer_creation_defaults_applied
    """
    set_clock()
    resp = api.create_volunteer(
        {
            "full_name": "Default Dan",
            "email": "dan@x.org",
            "home_region": "TX-GULF",
            "skills": ["DEBRIS"],
        },
        system_admin_headers,
    )
    data = validate_success(resp, 201)
    assert_volunteer(data)
    assert data["readiness_status"] == "REGISTERED"
    assert data["availability_windows"] == []
    assert data["instructor_certified"] is False
    assert data["operational_readiness_score"] == 0
    assert data["readiness_score"] == 0
    assert data["fatigue_hours"] == 0
    assert data["version"] == 1


def test_volunteer_create_missing_email_rejected(api, system_admin_headers):
    """PRD §2.6: "The request body must be well-formed: required fields present, types correct, enum members valid, `planned_end` strictly after `planned_start`, `ends_at` strictly after `starts_at`, and no unknown fields. Violations are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/volunteer_create_missing_required_email
    """
    resp = api.create_volunteer(
        {"full_name": "No Email", "home_region": "TX-GULF", "skills": ["DEBRIS"]},
        system_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_volunteer_create_unknown_computed_field_rejected(api, system_admin_headers):
    """PRD §2.6: "The request body must be well-formed: required fields present, types correct, enum members valid, `planned_end` strictly after `planned_start`, `ends_at` strictly after `starts_at`, and no unknown fields. Violations are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/volunteer_unknown_field_rejected
    """
    resp = api.create_volunteer(
        {
            "full_name": "Score Hacker",
            "email": "hack@x.org",
            "home_region": "TX-GULF",
            "skills": ["DEBRIS"],
            "readiness_score": 99,
        },
        system_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_volunteer_jump_registered_to_deployable_rejected(api, safety_officer_headers):
    """PRD §2.6: "6. **State legality.** The target entity must be in a from-state for the requested transition; repeated transitions and transitions out of terminal states are rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.1: "The decisive step is `VETTED` to `DEPLOYABLE`, which the same officer may take only once the volunteer holds at least one certification in `VERIFIED` status (`MIN_VERIFIED_CERTS_FOR_DEPLOYABLE` is 1); crossing into `DEPLOYABLE` recomputes both readiness scores."

    Design: Corner/state_machines/volunteer_jump_registered_to_deployable_rejected
    """
    set_clock()
    volunteer = register_volunteer(
        full_name="Skip Sam", email="sam@x.org", skills=["DEBRIS"], availability_windows=[],
    )
    resp = api.patch_volunteer(
        volunteer["id"], {"readiness_status": "DEPLOYABLE"}, safety_officer_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_volunteer(volunteer["id"])
    assert after["readiness_status"] == "REGISTERED"


def test_certification_verify_stamps_acting_officer(api):
    """PRD §3.1: "Verification moves `PENDING_VERIFICATION` to `VERIFIED` and is refused when the credential is already past its `expires_at` at the acting moment; a successful verification stamps `verified_by_user_id` with the acting officer's `X-User-ID` and recomputes the owner's readiness scores."
    PRD §2.5: "Counters and accumulators — `renewal_count`, `rostered_count`, `seats_taken`, `bunks_occupied`, `lodging_cost_cents`, and the two readiness scores together with `fatigue_hours` — all start at 0 on a newly created resource."

    Design: Corner/state_machines/cert_verify_stamps_verified_by
    """
    set_clock()
    volunteer = register_volunteer(
        full_name="Cert Cary", email="cary@x.org", skills=["MEDICAL"], availability_windows=[],
    )
    cert = add_certification(volunteer["id"], kind="MEDICAL")
    officer_headers = build_user_headers("safety-officer-7", "SafetyOfficer")
    resp = api.patch_certification(cert["id"], {"status": "VERIFIED"}, officer_headers)
    data = validate_success(resp, 200)
    assert_certification(data)
    assert data["status"] == "VERIFIED"
    assert data["verified_by_user_id"] == "safety-officer-7"
    assert data["renewal_count"] == 0


def test_certification_get_unknown_id_returns_404(api, safety_officer_headers):
    """PRD §2.6: "The request is rejected immediately with a `404 Not Found` carrying the per-entity error of the *first* path segment that does not resolve: `ERR_VOLUNTEER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_OPERATION_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_FOB_SITE_NOT_FOUND`, `ERR_DUTY_SHIFT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_TRAINING_COURSE_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, or `ERR_WELLNESS_CHECK_NOT_FOUND`."

    Design: Corner/entities/certification_get_not_found_returns_404
    """
    resp = api.get_certification(NON_EXISTENT_UUID, safety_officer_headers)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_FOUND)


def test_volunteer_writes_visible_immediately_and_scores_recompute(api):
    """PRD §2.9: "The **operational readiness** score, `operational_readiness_score`, is a pure credentialing view: a volunteer holding no `VERIFIED` certification scores 0; otherwise the score is a base of 10 points plus a per-kind weight for each distinct certification kind the volunteer currently holds in `VERIFIED` status — 30 for `CHAINSAW`, 25 for `HEAVY_EQUIPMENT`, 25 for `STRUCTURAL`, and 20 for `MEDICAL`."
    PRD §2.9: "Both are recomputed whenever a certification of the volunteer is verified, expires, is revoked, or is renewed; whenever the volunteer's readiness transitions into `DEPLOYABLE`; and whenever `fatigue_hours` changes."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    set_clock()
    volunteer = register_volunteer(
        full_name="Read Reba", email="reba@x.org", skills=["MEDICAL"], availability_windows=[],
    )
    cert = add_certification(volunteer["id"], kind="MEDICAL")
    own_headers = make_volunteer_headers(volunteer["id"])
    resp = api.patch_volunteer(
        volunteer["id"],
        {"availability_windows": [dict(AVAILABILITY_WINDOW)]},
        own_headers,
    )
    validate_success(resp, 200)
    data = validate_success(api.get_volunteer(volunteer["id"], own_headers), 200)
    assert len(data["availability_windows"]) == 1
    window = data["availability_windows"][0]
    assert parse_iso(window["start_iso8601"]) == parse_iso(AVAILABILITY_START)
    assert parse_iso(window["end_iso8601"]) == parse_iso(AVAILABILITY_END)
    verify_certification(cert["id"])
    data = validate_success(api.get_volunteer(volunteer["id"], own_headers), 200)
    assert data["operational_readiness_score"] == 30
    assert data["readiness_score"] == 30


def _setup_deployable_with_expiring_cert(expires_at="2026-09-05T00:00:00Z"):
    """Volunteer Cy Daly DEPLOYABLE with a single VERIFIED CHAINSAW cert."""
    set_clock()
    volunteer = register_volunteer(
        full_name="Cy Daly", email="cy@x.org", skills=["CHAINSAW"], availability_windows=[],
    )
    cert = add_certification(volunteer["id"], kind="CHAINSAW", expires_at=expires_at)
    verify_certification(cert["id"])
    transition_volunteer(volunteer["id"], "VETTED")
    transition_volunteer(volunteer["id"], "DEPLOYABLE")
    return volunteer, cert


def test_readiness_operational_ignores_fatigue(api):
    """PRD §2.9: "The **operational readiness** score, `operational_readiness_score`, is a pure credentialing view: a volunteer holding no `VERIFIED` certification scores 0; otherwise the score is a base of 10 points plus a per-kind weight for each distinct certification kind the volunteer currently holds in `VERIFIED` status — 30 for `CHAINSAW`, 25 for `HEAVY_EQUIPMENT`, 25 for `STRUCTURAL`, and 20 for `MEDICAL`."
    PRD §3.5: "Every completed duty shift adds its duration in hours to the volunteer's `fatigue_hours`"

    Design: Difficulty/dual_variant_calc/readiness_operational_vs_wellness_adjusted
    """
    bundle = setup_fatigued_volunteer(
        cert_kinds=("CHAINSAW", "STRUCTURAL"),
        volunteer_overrides={
            "full_name": "Bo Karr", "email": "bo@x.org", "skills": ["CHAINSAW", "STRUCTURAL"],
        },
    )
    volunteer = get_volunteer(bundle["volunteer"]["id"])
    assert_volunteer(volunteer)
    assert volunteer["fatigue_hours"] == 10
    assert volunteer["operational_readiness_score"] == 65


def test_readiness_wellness_adjusted_subtracts_fatigue_penalty(api):
    """PRD §2.9: "The **wellness-adjusted** score, `readiness_score`, starts from the same operational figure and subtracts a fatigue penalty of 2 points per accumulated `fatigue_hours`, floored at 0 so the score can never go negative."
    PRD §2.9: "The two scores therefore agree exactly when a volunteer carries no fatigue, and diverge whenever they do."

    Design: Difficulty/dual_variant_calc/readiness_operational_vs_wellness_adjusted
    """
    bundle = setup_fatigued_volunteer(
        cert_kinds=("CHAINSAW", "STRUCTURAL"),
        volunteer_overrides={
            "full_name": "Bo Karr", "email": "bo@x.org", "skills": ["CHAINSAW", "STRUCTURAL"],
        },
    )
    volunteer = get_volunteer(bundle["volunteer"]["id"])
    assert_volunteer(volunteer)
    assert volunteer["fatigue_hours"] == 10
    assert volunteer["readiness_score"] == 45
    assert volunteer["readiness_score"] != volunteer["operational_readiness_score"]


def test_certification_expiry_auto_downgrades_deployable_volunteer(api):
    """PRD §2.4: "First, every `Certification` in `VERIFIED` status whose `expires_at` is strictly earlier than `current_utc` flips to `EXPIRED` — a certification remains `VERIFIED` while `current_utc` is less than or equal to `expires_at` and expires only once `current_utc` is strictly greater. Second, any volunteer left holding zero `VERIFIED` certifications by that sweep, and whose `readiness_status` is `DEPLOYABLE`, is automatically downgraded to `VETTED`."

    Design: Difficulty/non_linear_state_machine/certification_expiry_renewal_cycle
    """
    volunteer, cert = _setup_deployable_with_expiring_cert()
    set_clock("2026-09-06T00:00:00Z")
    run_ops_epoch()
    expired = get_certification(cert["id"])
    assert expired["status"] == "EXPIRED"
    downgraded = get_volunteer(volunteer["id"])
    assert downgraded["readiness_status"] == "VETTED"


def test_certification_renewal_restores_verified_and_counts(api, safety_officer_headers):
    """PRD §3.1: "An `EXPIRED` credential is not dead: the officer may renew it back to `VERIFIED` by supplying a new `expires_at` strictly later than `current_utc`, which increments `renewal_count` by 1, replaces `expires_at`, restamps `verified_by_user_id`, and recomputes the owner's scores."

    Design: Difficulty/non_linear_state_machine/certification_expiry_renewal_cycle
    """
    _volunteer, cert = _setup_deployable_with_expiring_cert()
    set_clock("2026-09-06T00:00:00Z")
    run_ops_epoch()
    assert get_certification(cert["id"])["status"] == "EXPIRED"
    resp = api.patch_certification(
        cert["id"],
        {"status": "VERIFIED", "expires_at": "2027-01-01T00:00:00Z"},
        safety_officer_headers,
    )
    data = validate_success(resp, 200)
    assert_certification(data)
    assert data["status"] == "VERIFIED"
    assert data["renewal_count"] == 1
    assert parse_iso(data["expires_at"]) == parse_iso("2027-01-01T00:00:00Z")


def test_certification_survives_ops_run_at_exact_expiry(api):
    """PRD §2.4: "a certification remains `VERIFIED` while `current_utc` is less than or equal to `expires_at` and expires only once `current_utc` is strictly greater."

    Design: Difficulty/boundary_precision_check/cert_expiry_strictly_greater_boundary
    """
    _volunteer, cert = _setup_deployable_with_expiring_cert()
    set_clock("2026-09-05T00:00:00Z")
    run_ops_epoch()
    surviving = get_certification(cert["id"])
    assert surviving["status"] == "VERIFIED"


def test_certification_expires_one_second_after_expiry(api):
    """PRD §2.4: "a certification remains `VERIFIED` while `current_utc` is less than or equal to `expires_at` and expires only once `current_utc` is strictly greater."

    Design: Difficulty/boundary_precision_check/cert_expiry_strictly_greater_boundary
    """
    _volunteer, cert = _setup_deployable_with_expiring_cert()
    set_clock("2026-09-05T00:00:01Z")
    run_ops_epoch()
    expired = get_certification(cert["id"])
    assert expired["status"] == "EXPIRED"
