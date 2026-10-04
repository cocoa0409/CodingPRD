"""HTTP client for the Medicare Enrollment API.

One transport method per endpoint declared in PRD section 4.  Every method
returns the raw HTTP response so a test may assert on the status code as well
as the envelope.  The ``/medicare`` prefix and the exact shape of each path
live here and nowhere else.

Two test-driving operations live OUTSIDE the business prefix and are built
bare: ``POST /_clock/set_current_utc`` and ``POST /_ops/run_monthly_cycle``.
"""

import re

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH, MONTHLY_CYCLE_PATH

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits.

    PRD section 2.2 promises three fractional digits on envelope timestamps;
    expected instants a test carries are normalised through this helper so an
    equal instant spelled with a different fractional width compares on value
    rather than on spelling.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        suffix = tz.replace(":", "")
        suffix = "{0}:{1}".format(suffix[:3], suffix[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    # --- Test-driving operations (UNPREFIXED, BenefitAdministrator only) ----

    def set_clock(self, to_iso8601, headers=None):
        """POST /_clock/set_current_utc - set the logical clock."""
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    def run_monthly_cycle(self, headers=None):
        """POST /_ops/run_monthly_cycle - run the monthly batch for the clock month."""
        return self.post(MONTHLY_CYCLE_PATH, json={}, headers=headers)

    # --- Beneficiaries ------------------------------------------------------

    def create_beneficiary(self, payload, headers=None):
        return self.post(API_PREFIX + "/beneficiaries", json=payload, headers=headers)

    def get_beneficiary(self, beneficiary_id, headers=None):
        return self.get(
            "{0}/beneficiaries/{1}".format(API_PREFIX, beneficiary_id),
            headers=headers,
        )

    # --- Rate schedules -----------------------------------------------------

    def create_rate_schedule(self, payload, headers=None):
        return self.post(API_PREFIX + "/rate-schedules", json=payload, headers=headers)

    # --- Enrollment periods -------------------------------------------------

    def list_enrollment_periods(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/enrollment-periods".format(API_PREFIX, beneficiary_id),
            headers=headers,
            params=params,
        )

    # --- Coverage enrollments -----------------------------------------------

    def create_enrollment(self, payload, headers=None):
        return self.post(API_PREFIX + "/enrollments", json=payload, headers=headers)

    def get_enrollment(self, enrollment_id, headers=None):
        return self.get(
            "{0}/enrollments/{1}".format(API_PREFIX, enrollment_id),
            headers=headers,
        )

    def list_enrollments(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/enrollments".format(API_PREFIX, beneficiary_id),
            headers=headers,
            params=params,
        )

    def terminate_enrollment(self, enrollment_id, payload=None, headers=None):
        return self.post(
            "{0}/enrollments/{1}/terminate".format(API_PREFIX, enrollment_id),
            json=payload if payload is not None else {},
            headers=headers,
        )

    def switch_collection_method(self, enrollment_id, payload, headers=None):
        return self.post(
            "{0}/enrollments/{1}/switch-collection-method".format(
                API_PREFIX, enrollment_id
            ),
            json=payload,
            headers=headers,
        )

    # --- Employer coverage records ------------------------------------------

    def create_employer_coverage(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/employer-coverages", json=payload, headers=headers
        )

    def list_employer_coverages(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/employer-coverages".format(
                API_PREFIX, beneficiary_id
            ),
            headers=headers,
            params=params,
        )

    def verify_employer_coverage(self, record_id, payload, headers=None):
        return self.post(
            "{0}/employer-coverages/{1}/verify".format(API_PREFIX, record_id),
            json=payload,
            headers=headers,
        )

    def end_employer_coverage(self, record_id, payload, headers=None):
        return self.post(
            "{0}/employer-coverages/{1}/end".format(API_PREFIX, record_id),
            json=payload,
            headers=headers,
        )

    # --- Tax records ----------------------------------------------------------

    def create_tax_record(self, payload, headers=None):
        return self.post(API_PREFIX + "/tax-records", json=payload, headers=headers)

    def list_tax_records(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/tax-records".format(API_PREFIX, beneficiary_id),
            headers=headers,
            params=params,
        )

    # --- Premium determinations -----------------------------------------------

    def create_premium_determination(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/premium-determinations", json=payload, headers=headers
        )

    def get_premium_determination(self, determination_id, headers=None):
        return self.get(
            "{0}/premium-determinations/{1}".format(API_PREFIX, determination_id),
            headers=headers,
        )

    def list_premium_determinations(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/premium-determinations".format(
                API_PREFIX, beneficiary_id
            ),
            headers=headers,
            params=params,
        )

    def list_determination_appeals(self, determination_id, headers=None, params=None):
        return self.get(
            "{0}/premium-determinations/{1}/appeals".format(
                API_PREFIX, determination_id
            ),
            headers=headers,
            params=params,
        )

    # --- Appeals --------------------------------------------------------------

    def create_appeal(self, payload, headers=None):
        return self.post(API_PREFIX + "/appeals", json=payload, headers=headers)

    def list_appeals(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/appeals".format(API_PREFIX, beneficiary_id),
            headers=headers,
            params=params,
        )

    def adjudicate_appeal(self, appeal_id, payload, headers=None):
        return self.post(
            "{0}/appeals/{1}/adjudicate".format(API_PREFIX, appeal_id),
            json=payload,
            headers=headers,
        )

    def respond_to_appeal(self, appeal_id, payload, headers=None):
        return self.post(
            "{0}/appeals/{1}/respond".format(API_PREFIX, appeal_id),
            json=payload,
            headers=headers,
        )

    # --- Withholding arrangements ---------------------------------------------

    def create_withholding_arrangement(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/withholding-arrangements", json=payload, headers=headers
        )

    def list_withholding_arrangements(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/withholding-arrangements".format(
                API_PREFIX, beneficiary_id
            ),
            headers=headers,
            params=params,
        )

    def adjust_withholding_arrangement(self, arrangement_id, payload, headers=None):
        return self.post(
            "{0}/withholding-arrangements/{1}/adjust".format(
                API_PREFIX, arrangement_id
            ),
            json=payload,
            headers=headers,
        )

    # --- Premium invoices -------------------------------------------------------

    def list_invoices(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/invoices".format(API_PREFIX, beneficiary_id),
            headers=headers,
            params=params,
        )

    def pay_invoice(self, invoice_id, payload, headers=None):
        return self.post(
            "{0}/invoices/{1}/pay".format(API_PREFIX, invoice_id),
            json=payload,
            headers=headers,
        )

    # --- Payer coordination -----------------------------------------------------

    def list_payer_coordination(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/payer-coordination".format(
                API_PREFIX, beneficiary_id
            ),
            headers=headers,
            params=params,
        )

    # --- Plan elections -----------------------------------------------------------

    def create_election(self, payload, headers=None):
        return self.post(API_PREFIX + "/elections", json=payload, headers=headers)

    def list_elections(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/elections".format(API_PREFIX, beneficiary_id),
            headers=headers,
            params=params,
        )

    # --- Equitable relief cases ---------------------------------------------------

    def create_equitable_relief_case(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/equitable-relief-cases", json=payload, headers=headers
        )

    def list_equitable_relief_cases(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/equitable-relief-cases".format(
                API_PREFIX, beneficiary_id
            ),
            headers=headers,
            params=params,
        )

    def adjudicate_equitable_relief_case(self, case_id, payload, headers=None):
        return self.post(
            "{0}/equitable-relief-cases/{1}/adjudicate".format(API_PREFIX, case_id),
            json=payload,
            headers=headers,
        )

    # --- Penalty assessments --------------------------------------------------------

    def list_penalties(self, beneficiary_id, headers=None, params=None):
        return self.get(
            "{0}/beneficiaries/{1}/penalties".format(API_PREFIX, beneficiary_id),
            headers=headers,
            params=params,
        )

    # --- Raw escape hatch -------------------------------------------------------------

    def raw(self, method, path, payload=None, headers=None, params=None):
        """Send an arbitrary request, for probes that need a route by hand."""
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
