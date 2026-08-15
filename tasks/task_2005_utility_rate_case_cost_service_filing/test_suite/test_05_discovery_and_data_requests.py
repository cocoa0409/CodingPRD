"""Discovery window, data-request lifecycle, procedural clock, overdue sweeps,
and cross-case reference guards (PRD §2.6, §3.4, §3.5, §3.9)."""
from test_helpers import (
    ApiErrorId,
    add_adjustment,
    add_class,
    add_data_request,
    add_entry,
    add_intervenor,
    advance_to_hearing,
    assert_instant_equals,
    create_case,
    create_data_request_payload,
    create_rate_case_payload,
    get_case,
    get_intervenor,
    get_data_request,
    setup_discovery_case,
    setup_discovery_case_light,
    validate_error,
    validate_paginated,
    validate_success,
    DEFAULT_CLOCK_ISO,
    DISCOVERY_CLOSE_DEFAULT_ISO,
    TEST_USERS,
    make_intervenor_rep_headers,
)

UF = TEST_USERS["utility_filer_alice"]
STAFF = TEST_USERS["commission_staff"]
ALJ = TEST_USERS["alj"]
IR = TEST_USERS["intervenor_rep"]


def test_staff_issued_data_request_system_fields(api):
    """PRD §3.4: "`issuer_kind` is derived from the caller's role: `INTERVENOR`
    for an `IntervenorRep` caller, `STAFF` for a `CommissionStaff` caller." and
    "The server stamps `issued_at` with the current clock, sets `response_due_at`
    to `issued_at` plus 10 days, and the request enters `ISSUED`." and "if
    `issuer_kind` is `STAFF`, the caller must be `CommissionStaff`."

    Design: Corner/state_machines/staff_issued_data_request_system_fields
    """
    s = setup_discovery_case_light()
    i1 = add_intervenor(s.case["id"])
    dr = validate_success(api.create_data_request(
        create_data_request_payload(s.case["id"], subject="Staff audit schedule",
                                    body="Produce the depreciation study workpapers"),
        STAFF), 201)
    assert dr["issuer_kind"] == "STAFF"
    assert dr.get("issuing_intervenor_id") is None
    assert dr["status"] == "ISSUED"
    assert_instant_equals(dr["issued_at"], DEFAULT_CLOCK_ISO, "issued_at")
    assert_instant_equals(dr["response_due_at"], "2026-08-11T00:00:00Z",
                          "response_due_at = issued_at + 10 days")
    res = api.withdraw_data_request(dr["id"], make_intervenor_rep_headers(i1["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)
    done = validate_success(api.withdraw_data_request(dr["id"], STAFF), 200)
    assert done["status"] == "WITHDRAWN", "staff can withdraw its own issuance"


def test_data_request_invalid_from_cluster(api):
    """PRD §3.4: "As an alternative available only from `ISSUED`, the utility may
    object, supplying an `objection_reason`; the request moves to `OBJECTED`. The
    ALJ then rules on the objection with a `ruling`: `SUSTAINED` moves the request
    to `CLOSED` and records the ruling" and "Any wrong-state invocation is
    `ERR_INVALID_REQUEST_STATE`."

    Design: Corner/state_machines/data_request_invalid_from_cluster
    """
    s = setup_discovery_case_light()
    i1 = add_intervenor(s.case["id"])
    dr1 = add_data_request(s.case["id"], intervenor_id=i1["id"])
    res1 = api.rule_data_request(dr1["id"], {"ruling": "SUSTAINED"}, ALJ)
    validate_error(res1, ApiErrorId.ERR_INVALID_REQUEST_STATE, expected_status=409)
    objected = validate_success(api.object_data_request(
        dr1["id"], {"objection_reason": "Overly broad and unduly burdensome"}, UF), 200)
    assert objected["status"] == "OBJECTED"
    res2 = api.object_data_request(dr1["id"], {"objection_reason": "Second objection"}, UF)
    validate_error(res2, ApiErrorId.ERR_INVALID_REQUEST_STATE, expected_status=409)
    closed = validate_success(api.rule_data_request(dr1["id"], {"ruling": "SUSTAINED"}, ALJ), 200)
    assert closed["status"] == "CLOSED"
    res3 = api.respond_data_request(dr1["id"], {"response_text": "Too late"}, UF)
    validate_error(res3, ApiErrorId.ERR_INVALID_REQUEST_STATE, expected_status=409)
    res4 = api.withdraw_data_request(dr1["id"], make_intervenor_rep_headers(i1["id"]))
    validate_error(res4, ApiErrorId.ERR_INVALID_REQUEST_STATE, expected_status=409)
    assert get_data_request(dr1["id"])["status"] == "CLOSED"


# ─── Difficulty: objection / overrule / overdue / respond cycle ──────────────

def _setup_overruled_request(api):
    """Canonical DISCOVERY case; I1's request objected and OVERRULED at the
    default clock (extended_due_at = 2026-08-06)."""
    s = setup_discovery_case()
    i1 = add_intervenor(s.case["id"])
    dr1 = add_data_request(s.case["id"], intervenor_id=i1["id"])
    validate_success(api.object_data_request(
        dr1["id"], {"objection_reason": "Overly broad and unduly burdensome"}, UF), 200)
    return s, i1, dr1


def test_objection_overrule_sets_extended_due_and_sweeps_overdue(api):
    """PRD §3.4: "`OVERRULED` moves it to `RESPOND_REQUIRED`, records the ruling,
    and sets `extended_due_at` to the ruling clock time plus 5 days." and "every
    DataRequest in `RESPOND_REQUIRED` whose `extended_due_at` is strictly before
    the new clock flips to `OVERDUE`; each flip increments the owning case's
    `overdue_data_request_count` by one."

    Design: Difficulty/non_linear_state_machine/data_request_objection_overrule_overdue_cycle
    """
    s, _i1, dr1 = _setup_overruled_request(api)
    ruled = validate_success(api.rule_data_request(dr1["id"], {"ruling": "OVERRULED"}, ALJ), 200)
    assert ruled["status"] == "RESPOND_REQUIRED"
    assert ruled["ruling"] == "OVERRULED"
    assert_instant_equals(ruled["extended_due_at"], "2026-08-06T00:00:00Z",
                          "ruling at 2026-08-01 + 5 days")
    validate_success(api.set_clock("2026-08-07T00:00:00Z", STAFF), 200)
    assert get_data_request(dr1["id"])["status"] == "OVERDUE", (
        "extended window lapsed by one day"
    )
    assert get_case(s.case["id"])["overdue_data_request_count"] == 1


def test_late_response_from_overdue_clears_counter(api):
    """PRD §3.4: "Responding to a request that is currently `OVERDUE` also
    decrements the case's `overdue_data_request_count`." and "The utility answers
    a request in `ISSUED`, `OVERDUE`, or `RESPOND_REQUIRED` by responding with a
    `response_text`; the request moves to `RESPONDED`."

    Design: Difficulty/non_linear_state_machine/data_request_objection_overrule_overdue_cycle
    """
    s, _i1, dr1 = _setup_overruled_request(api)
    validate_success(api.rule_data_request(dr1["id"], {"ruling": "OVERRULED"}, ALJ), 200)
    validate_success(api.set_clock("2026-08-07T00:00:00Z", STAFF), 200)
    assert get_case(s.case["id"])["overdue_data_request_count"] == 1
    responded = validate_success(api.respond_data_request(
        dr1["id"], {"response_text": "Workpapers attached as Exhibit U-7"}, UF), 200)
    assert responded["status"] == "RESPONDED"
    assert get_case(s.case["id"])["overdue_data_request_count"] == 0


# ─── Difficulty: boundary_precision / hearing_gate_zero_overdue ──────────────

def _setup_issued_request_case():
    """Canonical DISCOVERY case; I1's request issued at the default clock with
    response_due_at 2026-08-11T00:00:00Z."""
    s = setup_discovery_case()
    i1 = add_intervenor(s.case["id"])
    dr1 = add_data_request(s.case["id"], intervenor_id=i1["id"])
    return s, i1, dr1


def test_due_instant_equal_is_not_overdue_then_blocks_gate(api):
    """PRD §3.4: "A request whose due instant is exactly equal to the new clock
    is not overdue — the comparison is strictly-before."
    PRD §3.5: "the case must be in `DISCOVERY` and `overdue_data_request_count`
    must equal zero, otherwise `ERR_OVERDUE_DATA_REQUESTS_EXIST`."

    Design: Difficulty/boundary_precision_check/hearing_gate_zero_overdue_boundary
    """
    s, _i1, dr1 = _setup_issued_request_case()
    assert_instant_equals(dr1["response_due_at"], "2026-08-11T00:00:00Z",
                          "issued 2026-08-01 + 10 days")
    validate_success(api.set_clock("2026-08-11T00:00:00Z", STAFF), 200)
    assert get_data_request(dr1["id"])["status"] == "ISSUED", "equal is NOT overdue"
    validate_success(api.set_clock("2026-08-12T00:00:00Z", STAFF), 200)
    assert get_data_request(dr1["id"])["status"] == "OVERDUE"
    assert get_case(s.case["id"])["overdue_data_request_count"] == 1
    res = api.advance_to_hearing(s.case["id"], ALJ)
    validate_error(res, ApiErrorId.ERR_OVERDUE_DATA_REQUESTS_EXIST, expected_status=409)


def test_respond_reopens_hearing_gate(api):
    """PRD §3.5: "The ALJ advances the case from `DISCOVERY` to `HEARING` once
    discovery is clean: the case must be in `DISCOVERY` and
    `overdue_data_request_count` must equal zero, otherwise
    `ERR_OVERDUE_DATA_REQUESTS_EXIST`."

    Design: Difficulty/boundary_precision_check/hearing_gate_zero_overdue_boundary
    """
    s, _i1, dr1 = _setup_issued_request_case()
    validate_success(api.set_clock("2026-08-12T00:00:00Z", STAFF), 200)
    validate_error(api.advance_to_hearing(s.case["id"], ALJ),
                   ApiErrorId.ERR_OVERDUE_DATA_REQUESTS_EXIST, expected_status=409)
    validate_success(api.respond_data_request(
        dr1["id"], {"response_text": "Workpapers attached as Exhibit U-7"}, UF), 200)
    assert get_case(s.case["id"])["overdue_data_request_count"] == 0
    final = validate_success(api.advance_to_hearing(s.case["id"], ALJ), 200)
    assert final["status"] == "HEARING", "count 0 reopens the gate"


# ─── Difficulty: cross_entity / hearing gate via the extended-due arm ────────

def test_hearing_gate_blocked_by_overruled_then_overdue_request(api):
    """PRD §3.5: "the case must be in `DISCOVERY` and `overdue_data_request_count`
    must equal zero, otherwise `ERR_OVERDUE_DATA_REQUESTS_EXIST`."
    PRD §3.4: "`OVERRULED` moves it to `RESPOND_REQUIRED`, records the ruling, and
    sets `extended_due_at` to the ruling clock time plus 5 days."

    Design: Difficulty/cross_entity_state_dependency/hearing_gate_blocked_by_overruled_then_overdue_request
    """
    s, _i1, dr1 = _setup_overruled_request(api)
    validate_success(api.rule_data_request(dr1["id"], {"ruling": "OVERRULED"}, ALJ), 200)
    validate_success(api.set_clock("2026-08-07T00:00:00Z", STAFF), 200)
    assert get_data_request(dr1["id"])["status"] == "OVERDUE"
    res = api.advance_to_hearing(s.case["id"], ALJ)
    validate_error(res, ApiErrorId.ERR_OVERDUE_DATA_REQUESTS_EXIST, expected_status=409)


def test_hearing_gate_cleared_by_late_response_on_extended_path(api):
    """PRD §3.4: "Responding to a request that is currently `OVERDUE` also
    decrements the case's `overdue_data_request_count`."

    Design: Difficulty/cross_entity_state_dependency/hearing_gate_blocked_by_overruled_then_overdue_request
    """
    s, _i1, dr1 = _setup_overruled_request(api)
    validate_success(api.rule_data_request(dr1["id"], {"ruling": "OVERRULED"}, ALJ), 200)
    validate_success(api.set_clock("2026-08-07T00:00:00Z", STAFF), 200)
    validate_error(api.advance_to_hearing(s.case["id"], ALJ),
                   ApiErrorId.ERR_OVERDUE_DATA_REQUESTS_EXIST, expected_status=409)
    validate_success(api.respond_data_request(
        dr1["id"], {"response_text": "Workpapers attached as Exhibit U-7"}, UF), 200)
    final = validate_success(api.advance_to_hearing(s.case["id"], ALJ), 200)
    assert final["status"] == "HEARING"


def test_discovery_window_exact_close_boundary(api):
    """PRD §3.4: "Data requests may not be issued after `discovery_close_at`: an
    issue request whose clock time is later than `discovery_close_at` is rejected
    with `ERR_DISCOVERY_WINDOW_CLOSED`." and "This stamps `discovery_close_at` to
    the current logical clock plus 120 days and moves the case to `DISCOVERY`."

    Design: Corner/validations/discovery_window_exact_close_boundary
    """
    s = setup_discovery_case_light()
    assert_instant_equals(s.case["discovery_close_at"], DISCOVERY_CLOSE_DEFAULT_ISO,
                          "default clock + 120 days")
    i1 = add_intervenor(s.case["id"])
    validate_success(api.set_clock(DISCOVERY_CLOSE_DEFAULT_ISO, STAFF), 200)
    ok = validate_success(api.create_data_request(
        create_data_request_payload(s.case["id"], subject="At-close request",
                                    body="Issued exactly at discovery_close_at",
                                    issuing_intervenor_id=i1["id"]),
        make_intervenor_rep_headers(i1["id"])), 201)
    assert ok["status"] == "ISSUED", "the window is inclusive at the deadline"
    validate_success(api.set_clock("2026-11-29T00:00:01Z", STAFF), 200)
    res = api.create_data_request(
        create_data_request_payload(s.case["id"], subject="One second late",
                                    body="Issued one second past discovery_close_at",
                                    issuing_intervenor_id=i1["id"]),
        make_intervenor_rep_headers(i1["id"]))
    validate_error(res, ApiErrorId.ERR_DISCOVERY_WINDOW_CLOSED, expected_status=409)


def test_clock_regression_rejected(api):
    """PRD §2.6: "Only forward moves are accepted: an attempt to set the clock to
    an instant before the current logical clock is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 409)."

    Design: Corner/validations/clock_regression_rejected
    """
    moved = validate_success(api.set_clock("2026-08-05T00:00:00Z", STAFF), 200)
    assert_instant_equals(moved["current_utc"], "2026-08-05T00:00:00Z", "forward move")
    res1 = api.set_clock("2026-08-04T00:00:00Z", STAFF)
    validate_error(res1, ApiErrorId.ERR_CLOCK_REGRESSION, expected_status=409)
    res2 = api.set_clock("2026-08-05T00:00:00Z", STAFF)
    validate_error(res2, ApiErrorId.ERR_CLOCK_REGRESSION, expected_status=409)


def test_clock_default_stamp_on_data_request(api):
    """PRD §2.6: "At startup, before any call, the clock reads exactly
    `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."
    PRD §3.4: "The server stamps `issued_at` with the current clock, sets
    `response_due_at` to `issued_at` plus 10 days, and the request enters
    `ISSUED`."

    Design: Corner/complexity_layers/clock_default_stamp_on_data_request
    """
    s = setup_discovery_case_light()
    assert_instant_equals(s.case["created_at"], DEFAULT_CLOCK_ISO, "case created_at")
    assert_instant_equals(s.case["discovery_close_at"], DISCOVERY_CLOSE_DEFAULT_ISO,
                          "default clock + 120 days")
    i1 = add_intervenor(s.case["id"])
    dr = add_data_request(s.case["id"], intervenor_id=i1["id"])
    assert_instant_equals(dr["issued_at"], DEFAULT_CLOCK_ISO, "issued_at")
    assert_instant_equals(dr["response_due_at"], "2026-08-11T00:00:00Z",
                          "issued + 10 days")


# ─── Difficulty: priority_pair / temporal_window_beats_cross_case_reference ──

def _setup_two_cases_with_foreign_adjustment():
    """Case 1 canonical in DISCOVERY; case 2 DRAFT holding entry E2x and its
    own adjustment A_other."""
    s1 = setup_discovery_case()
    case2 = create_case(case_number="UR-2026-999", utility_name="Other State Gas",
                        return_on_rate_base_bp=800,
                        proposed_revenue_requirement_cents=100000000,
                        allocation_method="ENERGY_AVERAGE")
    e_other = add_entry(case2["id"], "900", "O_AND_M", 50000000)
    a_other = add_adjustment(case2["id"], e_other["id"], -5000000,
                             reason="Remove one-time merger cost")
    return s1, case2, a_other


def test_temporal_window_beats_cross_case_reference(api):
    """PRD §2.9: "then temporal-window rules (`ERR_DISCOVERY_WINDOW_CLOSED`,
    `ERR_TARIFF_WINDOW_OVERLAP`, `ERR_DEFERRAL_OVERLAPS_TEST_YEAR`,
    `ERR_CLOCK_REGRESSION`), then cross-case referential rules
    (`ERR_ADJUSTMENT_NOT_IN_CASE`, `ERR_CLASS_NOT_IN_CASE`, `ERR_PARTY_NOT_IN_CASE`,
    `ERR_INCOMPLETE_CLASS_REVENUE`)"

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_beats_cross_case_reference
    """
    s1, _case2, a_other = _setup_two_cases_with_foreign_adjustment()
    validate_success(api.set_clock("2026-11-30T00:00:00Z", STAFF), 200)
    res = api.create_data_request(
        create_data_request_payload(s1.case["id"], subject="Cross-exhibit probe",
                                    body="Explain the other utility's treatment",
                                    referenced_adjustment_id=a_other["id"]),
        STAFF)
    validate_error(res, ApiErrorId.ERR_DISCOVERY_WINDOW_CLOSED, expected_status=409)
    data, meta = validate_paginated(api.list_data_requests(
        UF, params={"rate_case_id": s1.case["id"], "status": "ISSUED"}))
    assert meta["total_count"] == 0, "no DataRequest row may be persisted"


def test_cross_case_reference_fires_when_window_open(api):
    """PRD §3.4: "If `referenced_adjustment_id` is present it must reference an
    adjustment of the same case — otherwise `ERR_ADJUSTMENT_NOT_IN_CASE`"

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_beats_cross_case_reference
    """
    s1, _case2, a_other = _setup_two_cases_with_foreign_adjustment()
    res = api.create_data_request(
        create_data_request_payload(s1.case["id"], subject="Cross-exhibit probe",
                                    body="Explain the other utility's treatment",
                                    referenced_adjustment_id=a_other["id"]),
        STAFF)
    validate_error(res, ApiErrorId.ERR_ADJUSTMENT_NOT_IN_CASE, expected_status=422)


def test_cross_case_references_rejected(api):
    """PRD §3.4: "If `referenced_adjustment_id` is present it must reference an
    adjustment of the same case — otherwise `ERR_ADJUSTMENT_NOT_IN_CASE`; if
    `issuing_intervenor_id` is present it must reference an intervenor of the same
    case — otherwise `ERR_PARTY_NOT_IN_CASE`."
    PRD §3.8: "`customer_class_id` (which must reference a class of the addressed
    case — otherwise `ERR_CLASS_NOT_IN_CASE`)"

    Design: Corner/validations/cross_case_references_rejected
    """
    s1 = setup_discovery_case()
    case2 = create_case(case_number="UR-2026-999", utility_name="Other State Gas",
                        return_on_rate_base_bp=800,
                        proposed_revenue_requirement_cents=58000000,
                        allocation_method="ENERGY_AVERAGE")
    e2x = add_entry(case2["id"], "900", "O_AND_M", 50000000)
    a2x = add_adjustment(case2["id"], e2x["id"], -5000000,
                         reason="Remove one-time merger cost")
    cls2 = add_class(case2["id"], class_code="GENERAL", customer_count=10000,
                     monthly_kwh_per_customer=100, annual_kwh=12000000,
                     coincident_peak_kw=10000, average_demand_kw=5000,
                     present_customer_charge_cents=100,
                     present_tiers=[{"up_to_kwh": None, "rate_mills": 500}])
    i2x = add_intervenor(case2["id"], "ZZZ Rival Party", "Pat Ng", "pat@zzz.example")
    i1 = add_intervenor(s1.case["id"])

    res1 = api.create_data_request(
        create_data_request_payload(s1.case["id"], subject="Foreign adjustment probe",
                                    body="Targeted at another case's adjustment",
                                    issuing_intervenor_id=i1["id"],
                                    referenced_adjustment_id=a2x["id"]),
        make_intervenor_rep_headers(i1["id"]))
    validate_error(res1, ApiErrorId.ERR_ADJUSTMENT_NOT_IN_CASE, expected_status=422)

    res2 = api.create_data_request(
        create_data_request_payload(s1.case["id"], subject="Foreign party probe",
                                    body="Issued by a party of another case",
                                    issuing_intervenor_id=i2x["id"]),
        make_intervenor_rep_headers(i2x["id"]))
    validate_error(res2, ApiErrorId.ERR_PARTY_NOT_IN_CASE, expected_status=422)

    res3 = api.get_bill_impact(s1.case["id"], UF,
                               params={"customer_class_id": cls2["id"], "monthly_kwh": 100})
    validate_error(res3, ApiErrorId.ERR_CLASS_NOT_IN_CASE, expected_status=422)

    data, meta = validate_paginated(api.list_data_requests(
        UF, params={"rate_case_id": s1.case["id"]}))
    assert meta["total_count"] == 0


# ─── Difficulty: transitive_cascade / intervenor_withdraw_overdue ────────────

def _setup_overdue_party_request(api):
    """Canonical DISCOVERY case; I1's request swept to OVERDUE at 2026-08-12."""
    s = setup_discovery_case()
    i1 = add_intervenor(s.case["id"])
    dr1 = add_data_request(s.case["id"], intervenor_id=i1["id"])
    validate_success(api.set_clock("2026-08-12T00:00:00Z", STAFF), 200)
    return s, i1, dr1


def test_intervenor_withdraw_overdue_cascade(api):
    """PRD §3.9: "The cascade runs in hops: first the party moves to `WITHDRAWN`;
    second, every DataRequest whose `issuing_intervenor_id` is this party and
    whose status is `ISSUED`, `OBJECTED`, `RESPOND_REQUIRED`, or `OVERDUE` moves
    to `WITHDRAWN`; third, each hop-2 withdrawal out of `OVERDUE` decrements the
    owning case's `overdue_data_request_count`"

    Design: Difficulty/transitive_cascade/intervenor_withdraw_overdue_cascade
    """
    s, i1, dr1 = _setup_overdue_party_request(api)
    assert get_data_request(dr1["id"])["status"] == "OVERDUE"
    assert get_case(s.case["id"])["overdue_data_request_count"] == 1
    withdrawn = validate_success(api.withdraw_intervenor(
        i1["id"], make_intervenor_rep_headers(i1["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_data_request(dr1["id"])["status"] == "WITHDRAWN", (
        "force-withdrawn by the party cascade, no direct call on the request"
    )
    assert get_case(s.case["id"])["overdue_data_request_count"] == 0


def test_intervenor_withdraw_reopens_hearing_gate(api):
    """PRD §3.5: "the case must be in `DISCOVERY` and `overdue_data_request_count`
    must equal zero, otherwise `ERR_OVERDUE_DATA_REQUESTS_EXIST`."

    Design: Difficulty/transitive_cascade/intervenor_withdraw_overdue_cascade
    """
    s, i1, dr1 = _setup_overdue_party_request(api)
    validate_error(api.advance_to_hearing(s.case["id"], ALJ),
                   ApiErrorId.ERR_OVERDUE_DATA_REQUESTS_EXIST, expected_status=409)
    validate_success(api.withdraw_intervenor(
        i1["id"], make_intervenor_rep_headers(i1["id"])), 200)
    final = validate_success(api.advance_to_hearing(s.case["id"], ALJ), 200)
    assert final["status"] == "HEARING", "guard reopened by the withdrawal cascade"


# ─── Corner: RBAC and party ownership ─────────────────────────────────────

def test_rbac_role_denials_unauthorized(api):
    """PRD §2.1: "Once headers are present, the role named in `X-User-Role` is
    checked against the endpoint's authorized role list; a caller whose role is
    not listed is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/rbac_role_denials_unauthorized
    """
    # Case 1 in DISCOVERY with an intervenor-issued data request.
    s1 = setup_discovery_case_light()
    i1 = add_intervenor(s1.case["id"])
    dr1 = add_data_request(s1.case["id"], intervenor_id=i1["id"])
    # Case 2 DRAFT holding a PROPOSED adjustment.
    case2 = create_case(case_number="UR-2026-999", utility_name="Other State Gas",
                        return_on_rate_base_bp=800,
                        proposed_revenue_requirement_cents=58000000,
                        allocation_method="ENERGY_AVERAGE")
    e2x = add_entry(case2["id"], "900", "O_AND_M", 50000000)
    a2p = add_adjustment(case2["id"], e2x["id"], -5000000,
                         reason="Remove one-time merger cost")

    res_a = api.create_rate_case(
        create_rate_case_payload(case_number="UR-2026-777",
                                 utility_name="Party Crasher Power",
                                 proposed_revenue_requirement_cents=100000000),
        IR)
    validate_error(res_a, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    res_b = api.deficiency_review(s1.case["id"], {"outcome": "ACCEPTED"}, UF)
    validate_error(res_b, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    res_c = api.respond_data_request(
        dr1["id"], {"response_text": "ALJ trying to respond"}, ALJ)
    validate_error(res_c, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    res_d = api.verify_adjustment(a2p["id"], STAFF)
    validate_error(res_d, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


def test_intervenor_ownership_scoping(api):
    """PRD §3.4: "Withdrawal of a data request is available from `ISSUED`,
    `OBJECTED`, `OVERDUE`, or `RESPOND_REQUIRED` to the issuing party: if
    `issuer_kind` is `INTERVENOR`, the caller must be an `IntervenorRep` whose
    `X-User-ID` equals `issuing_intervenor_id` (otherwise
    `ERR_FORBIDDEN_OWNERSHIP`)"
    PRD §3.9: "Withdrawal is available to the party's own representative (whose
    `X-User-ID` must equal the Intervenor `id`, otherwise
    `ERR_FORBIDDEN_OWNERSHIP`) or to `CommissionStaff`"

    Design: Corner/rbac/intervenor_ownership_scoping
    """
    s = setup_discovery_case_light()
    i1 = add_intervenor(s.case["id"])
    i2 = add_intervenor(s.case["id"], "BBB Consumer Advocates", "Sam Cho",
                        "sam@bbb.example")
    dr1 = add_data_request(s.case["id"], intervenor_id=i1["id"],
                           subject="I1 request", body="From AAA")
    dr2 = add_data_request(s.case["id"], intervenor_id=i2["id"],
                           subject="I2 request", body="From BBB")

    res1 = api.withdraw_data_request(dr2["id"], make_intervenor_rep_headers(i1["id"]))
    validate_error(res1, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)
    assert get_data_request(dr2["id"])["status"] == "ISSUED"

    own = validate_success(api.withdraw_data_request(
        dr1["id"], make_intervenor_rep_headers(i1["id"])), 200)
    assert own["status"] == "WITHDRAWN", "I1 withdraws its own request"

    res2 = api.withdraw_intervenor(i2["id"], make_intervenor_rep_headers(i1["id"]))
    validate_error(res2, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)

    by_staff = validate_success(api.withdraw_intervenor(i2["id"], STAFF), 200)
    assert by_staff["status"] == "WITHDRAWN", "CommissionStaff is unscoped"
    assert get_data_request(dr2["id"])["status"] == "WITHDRAWN", (
        "party withdrawal cascades to its open data requests"
    )


def test_intervenor_double_withdraw_rejected(api):
    """PRD §3.9: "Withdrawal is available to the party's own representative
    (whose `X-User-ID` must equal the Intervenor `id`, otherwise
    `ERR_FORBIDDEN_OWNERSHIP`) or to `CommissionStaff`, and requires the party in
    `PARTY` (otherwise `ERR_INVALID_INTERVENOR_STATE`)." and "`WITHDRAWN` is
    terminal for a party."

    Design: Corner/state_machines/intervenor_double_withdraw_rejected
    """
    case = create_case()
    i1 = add_intervenor(case["id"])
    first = validate_success(api.withdraw_intervenor(
        i1["id"], make_intervenor_rep_headers(i1["id"])), 200)
    assert first["status"] == "WITHDRAWN"
    res = api.withdraw_intervenor(i1["id"], make_intervenor_rep_headers(i1["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_INTERVENOR_STATE, expected_status=409)
    assert get_intervenor(i1["id"])["status"] == "WITHDRAWN"
