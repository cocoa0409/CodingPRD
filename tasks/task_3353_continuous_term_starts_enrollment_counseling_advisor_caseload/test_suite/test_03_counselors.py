"""Staff defaults, counselor assignment selector, and contact cadence."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, create_staff_payload, create_applicant_payload,
    create_counselor, create_applicant, set_clock, make_counselor_headers,
    assert_staff, assert_applicant,
)

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_staff_compensation_plan_defaults_to_non_incentive():
    """PRD §3.3: "An optional `compensation_plan` of `NON_INCENTIVE` or
    `INCENTIVE` defaults to `NON_INCENTIVE` when omitted; the `INCENTIVE`
    value is a regulatory marker that later bars conversion attribution
    (§3.6)."

    Design: Corner/entities/staff_compensation_plan_defaults_to_non_incentive
    """
    payload = create_staff_payload(staff_type="COUNSELOR", caseload_cap=5)
    payload.pop("compensation_plan", None)
    resp = api_client.create_staff(payload, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_staff(data)
    assert data["compensation_plan"] == "NON_INCENTIVE", (
        f"omitted compensation_plan must default to NON_INCENTIVE; "
        f"got {data['compensation_plan']}")


def test_counselor_selector_empty_pool_leaves_unassigned():
    """PRD §3.3: "If the candidate pool is empty, creation still succeeds and
    `assigned_counselor_id` is simply null; an empty pool is not an error."

    Design: Corner/entities/counselor_selector_empty_pool_leaves_unassigned
    """
    resp = api_client.create_applicant(
        create_applicant_payload(full_name="Solo", state_code="CO"), REGISTRAR)
    data = validate_success(resp, expected_status=201)
    assert_applicant(data)
    assert data["assigned_counselor_id"] is None, (
        f"no counselors exist; expected null assignment, got "
        f"{data['assigned_counselor_id']}")
    assert data["status"] == "PROSPECT"


def test_counselor_selector_lowest_count_wins():
    """PRD §3.3: "The selector considers every staff member with `staff_type`
    `COUNSELOR` whose `active_caseload_count` is strictly below their
    `caseload_cap`, ranks the candidates by `active_caseload_count`
    ascending, breaks ties by `caseload_cap` descending, and breaks remaining
    ties by `created_at` ascending — never by `id`. The first candidate in
    that ranking receives the assignment, recorded as the applicant's
    `assigned_counselor_id`."

    Design: Corner/entities/counselor_selector_lowest_count_wins
    """
    c1 = create_counselor(cap=5, full_name="C1")
    first = create_applicant(full_name="First")
    assert first["assigned_counselor_id"] == c1["id"], (
        "with one counselor in the pool the first applicant must go to it")
    c2 = create_counselor(cap=5, full_name="C2")
    second = create_applicant(full_name="Second")
    assert second["assigned_counselor_id"] == c2["id"], (
        f"C1 holds count 1, C2 holds count 0; the new applicant must assign "
        f"to C2 ({c2['id']}), got {second['assigned_counselor_id']}")


class TestContactCadenceWindowEdge:
    def _setup_assigned_applicant(self):
        counselor = create_counselor(cap=5)
        applicant = create_applicant()
        assert applicant["assigned_counselor_id"] == counselor["id"]
        return counselor, applicant

    def _three_attempts(self, applicant_id, counselor_id):
        headers = make_counselor_headers(counselor_id)
        set_clock("2026-09-05T12:00:00Z")
        resp = api_client.create_contact_attempt(
            applicant_id, {"channel": "PHONE", "outcome": "NO_ANSWER"},
            headers)
        validate_success(resp, expected_status=201)
        set_clock("2026-09-06T12:00:00Z")
        resp = api_client.create_contact_attempt(
            applicant_id, {"channel": "EMAIL", "outcome": "SENT"}, headers)
        validate_success(resp, expected_status=201)
        set_clock("2026-09-07T12:00:00Z")
        resp = api_client.create_contact_attempt(
            applicant_id, {"channel": "SMS", "outcome": "SENT"}, headers)
        validate_success(resp, expected_status=201)
        return headers

    def test_third_attempt_allowed_fourth_rejected(self):
        """PRD §3.3: "Before appending, the system counts the entries already
        in the applicant's `contact_log` whose `attempted_at` falls within
        the trailing half-open window from 168 hours before the current
        logical instant up to and including that instant — an attempt exactly
        168 hours old is excluded from the count, and attempts on every
        channel and with every outcome count toward the total. If the window
        already holds three attempts, the new attempt is rejected with
        `ERR_CONTACT_CADENCE_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/contact_cadence_third_allowed_fourth_rejected_window_edge
        """
        counselor, applicant = self._setup_assigned_applicant()
        headers = self._three_attempts(applicant["id"], counselor["id"])
        # Window (2026-08-31T12:00, 2026-09-07T12:00] already holds 3 entries.
        resp = api_client.create_contact_attempt(
            applicant["id"], {"channel": "PHONE", "outcome": "NO_ANSWER"},
            headers)
        validate_error(resp, ApiErrorId.ERR_CONTACT_CADENCE_EXCEEDED)

    def test_attempt_exactly_168h_old_falls_out_of_window(self):
        """PRD §3.3: "Before appending, the system counts the entries already
        in the applicant's `contact_log` whose `attempted_at` falls within
        the trailing half-open window from 168 hours before the current
        logical instant up to and including that instant — an attempt exactly
        168 hours old is excluded from the count, and attempts on every
        channel and with every outcome count toward the total. If the window
        already holds three attempts, the new attempt is rejected with
        `ERR_CONTACT_CADENCE_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/contact_cadence_third_allowed_fourth_rejected_window_edge
        """
        counselor, applicant = self._setup_assigned_applicant()
        headers = self._three_attempts(applicant["id"], counselor["id"])
        # Oldest entry (2026-09-05T12:00:00Z) is exactly 168h old at
        # 2026-09-12T12:00:00Z -> excluded; window holds only 2 entries.
        set_clock("2026-09-12T12:00:00Z")
        resp = api_client.create_contact_attempt(
            applicant["id"], {"channel": "PHONE", "outcome": "REACHED"},
            headers)
        data = validate_success(resp, expected_status=201)
        assert_applicant(data)
        assert len(data["contact_log"]) == 4, (
            f"4 attempts must be logged after the oldest aged out; got "
            f"{len(data['contact_log'])}")
