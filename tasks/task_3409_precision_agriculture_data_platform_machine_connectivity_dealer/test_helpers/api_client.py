"""API client: one method per endpoint defined in the PRD (section 4 table).

Every method returns the raw ``requests.Response`` so tests assert on status
codes and the envelope themselves.  The base URL comes from the runner via
the ``API_BASE_URL`` environment variable (see ``GenericApiClient``); it is
never hardcoded here.

``canonical_instant`` / ``same_instant`` exist because the PRD pins ISO 8601
UTC timestamps with three fractional digits while design-time expectations
are written without a fractional part; comparisons go through them so equal
instants spelled differently still compare equal.
"""

import re

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt ]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz") or "Z"
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        flat = tz.replace(":", "")
        suffix = "{0}:{1}".format(flat[:3], flat[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Endpoint-shaped facade over the shared HTTP client."""

    # --- Logical clock -----------------------------------------------------

    def set_clock(self, current_utc, headers=None):
        return self.post(
            API_PREFIX + "/_clock/set_current_utc",
            json={"current_utc": current_utc},
            headers=headers,
        )

    # --- Organizations -----------------------------------------------------

    def create_organization(self, payload, headers=None):
        return self.post(API_PREFIX + "/organizations", json=payload, headers=headers)

    def suspend_organization(self, org_id, headers=None):
        return self.post(
            "{0}/organizations/{1}/suspend".format(API_PREFIX, org_id),
            json={},
            headers=headers,
        )

    def resume_organization(self, org_id, headers=None):
        return self.post(
            "{0}/organizations/{1}/resume".format(API_PREFIX, org_id),
            json={},
            headers=headers,
        )

    # --- Dealers ------------------------------------------------------------

    def create_dealer(self, payload, headers=None):
        return self.post(API_PREFIX + "/dealers", json=payload, headers=headers)

    def get_dealer(self, dealer_id, headers=None):
        return self.get("{0}/dealers/{1}".format(API_PREFIX, dealer_id), headers=headers)

    def suspend_dealer(self, dealer_id, headers=None):
        return self.post(
            "{0}/dealers/{1}/suspend".format(API_PREFIX, dealer_id),
            json={},
            headers=headers,
        )

    # --- Machines -----------------------------------------------------------

    def create_machine(self, payload, headers=None):
        return self.post(API_PREFIX + "/machines", json=payload, headers=headers)

    def get_machine(self, machine_id, headers=None):
        return self.get("{0}/machines/{1}".format(API_PREFIX, machine_id), headers=headers)

    def list_machines(self, headers=None, params=None):
        return self.get(API_PREFIX + "/machines", headers=headers, params=params)

    def activate_machine(self, machine_id, headers=None):
        return self.post(
            "{0}/machines/{1}/activate".format(API_PREFIX, machine_id),
            json={},
            headers=headers,
        )

    def provision_modem(self, machine_id, headers=None):
        return self.post(
            "{0}/machines/{1}/provision-modem".format(API_PREFIX, machine_id),
            json={},
            headers=headers,
        )

    def report_modem_provisioning_event(self, machine_id, outcome, headers=None):
        return self.post(
            "{0}/machines/{1}/modem-provisioning-events".format(API_PREFIX, machine_id),
            json={"outcome": outcome},
            headers=headers,
        )

    def telemetry_ingest(self, machine_id, payload, headers=None):
        return self.post(
            "{0}/machines/{1}/telemetry-ingest".format(API_PREFIX, machine_id),
            json=payload,
            headers=headers,
        )

    def get_uptime_prediction(self, machine_id, headers=None):
        return self.get(
            "{0}/machines/{1}/uptime-prediction".format(API_PREFIX, machine_id),
            headers=headers,
        )

    # --- Data plans ----------------------------------------------------------

    def create_data_plan(self, payload, headers=None):
        return self.post(API_PREFIX + "/data-plans", json=payload, headers=headers)

    def get_data_plan(self, plan_id, headers=None):
        return self.get("{0}/data-plans/{1}".format(API_PREFIX, plan_id), headers=headers)

    def list_data_plans(self, headers=None, params=None):
        return self.get(API_PREFIX + "/data-plans", headers=headers, params=params)

    def activate_data_plan(self, plan_id, headers=None):
        return self.post(
            "{0}/data-plans/{1}/activate".format(API_PREFIX, plan_id),
            json={},
            headers=headers,
        )

    def suspend_data_plan(self, plan_id, headers=None):
        return self.post(
            "{0}/data-plans/{1}/suspend".format(API_PREFIX, plan_id),
            json={},
            headers=headers,
        )

    def resume_data_plan(self, plan_id, headers=None):
        return self.post(
            "{0}/data-plans/{1}/resume".format(API_PREFIX, plan_id),
            json={},
            headers=headers,
        )

    def change_data_plan_tier(self, plan_id, payload, headers=None):
        return self.post(
            "{0}/data-plans/{1}/change-tier".format(API_PREFIX, plan_id),
            json=payload,
            headers=headers,
        )

    # --- Field boundaries ----------------------------------------------------

    def create_field_boundary(self, payload, headers=None):
        return self.post(API_PREFIX + "/field-boundaries", json=payload, headers=headers)

    def get_field_boundary(self, field_id, headers=None):
        return self.get(
            "{0}/field-boundaries/{1}".format(API_PREFIX, field_id), headers=headers
        )

    def list_field_boundaries(self, headers=None, params=None):
        return self.get(API_PREFIX + "/field-boundaries", headers=headers, params=params)

    def activate_field_boundary(self, field_id, headers=None):
        return self.post(
            "{0}/field-boundaries/{1}/activate".format(API_PREFIX, field_id),
            json={},
            headers=headers,
        )

    def archive_field_boundary(self, field_id, headers=None):
        return self.post(
            "{0}/field-boundaries/{1}/archive".format(API_PREFIX, field_id),
            json={},
            headers=headers,
        )

    # --- Prescriptions --------------------------------------------------------

    def create_prescription(self, payload, headers=None):
        return self.post(API_PREFIX + "/prescriptions", json=payload, headers=headers)

    def get_prescription(self, prescription_id, headers=None):
        return self.get(
            "{0}/prescriptions/{1}".format(API_PREFIX, prescription_id), headers=headers
        )

    def list_prescriptions(self, headers=None, params=None):
        return self.get(API_PREFIX + "/prescriptions", headers=headers, params=params)

    def approve_prescription(self, prescription_id, headers=None):
        return self.post(
            "{0}/prescriptions/{1}/approve".format(API_PREFIX, prescription_id),
            json={},
            headers=headers,
        )

    def revise_prescription(self, prescription_id, headers=None):
        return self.post(
            "{0}/prescriptions/{1}/revise".format(API_PREFIX, prescription_id),
            json={},
            headers=headers,
        )

    def send_prescription_to_machine(self, prescription_id, headers=None):
        return self.post(
            "{0}/prescriptions/{1}/send-to-machine".format(API_PREFIX, prescription_id),
            json={},
            headers=headers,
        )

    def report_prescription_as_applied(self, prescription_id, payload, headers=None):
        return self.post(
            "{0}/prescriptions/{1}/report-as-applied".format(API_PREFIX, prescription_id),
            json=payload,
            headers=headers,
        )

    # --- Data share grants -----------------------------------------------------

    def create_data_share_grant(self, payload, headers=None):
        return self.post(API_PREFIX + "/data-share-grants", json=payload, headers=headers)

    def get_data_share_grant(self, grant_id, headers=None):
        return self.get(
            "{0}/data-share-grants/{1}".format(API_PREFIX, grant_id), headers=headers
        )

    def list_data_share_grants(self, headers=None, params=None):
        return self.get(API_PREFIX + "/data-share-grants", headers=headers, params=params)

    def suspend_data_share_grant(self, grant_id, headers=None):
        return self.post(
            "{0}/data-share-grants/{1}/suspend".format(API_PREFIX, grant_id),
            json={},
            headers=headers,
        )

    def resume_data_share_grant(self, grant_id, headers=None):
        return self.post(
            "{0}/data-share-grants/{1}/resume".format(API_PREFIX, grant_id),
            json={},
            headers=headers,
        )

    def revoke_data_share_grant(self, grant_id, headers=None):
        return self.post(
            "{0}/data-share-grants/{1}/revoke".format(API_PREFIX, grant_id),
            json={},
            headers=headers,
        )

    # --- Consent tickets ---------------------------------------------------------

    def create_consent_ticket(self, payload, headers=None):
        return self.post(API_PREFIX + "/consent-tickets", json=payload, headers=headers)

    def get_consent_ticket(self, ticket_id, headers=None):
        return self.get(
            "{0}/consent-tickets/{1}".format(API_PREFIX, ticket_id), headers=headers
        )

    def list_consent_tickets(self, headers=None, params=None):
        return self.get(API_PREFIX + "/consent-tickets", headers=headers, params=params)

    def grant_consent_ticket(self, ticket_id, headers=None):
        return self.post(
            "{0}/consent-tickets/{1}/grant".format(API_PREFIX, ticket_id),
            json={},
            headers=headers,
        )

    def deny_consent_ticket(self, ticket_id, headers=None):
        return self.post(
            "{0}/consent-tickets/{1}/deny".format(API_PREFIX, ticket_id),
            json={},
            headers=headers,
        )

    # --- Diagnostic sessions -------------------------------------------------------

    def create_diagnostic_session(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/diagnostic-sessions", json=payload, headers=headers
        )

    def get_diagnostic_session(self, session_id, headers=None):
        return self.get(
            "{0}/diagnostic-sessions/{1}".format(API_PREFIX, session_id),
            headers=headers,
        )

    def list_diagnostic_sessions(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/diagnostic-sessions", headers=headers, params=params
        )

    def close_diagnostic_session(self, session_id, payload, headers=None):
        return self.post(
            "{0}/diagnostic-sessions/{1}/close".format(API_PREFIX, session_id),
            json=payload,
            headers=headers,
        )

    # --- Software packages ------------------------------------------------------------

    def create_software_package(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/software-packages", json=payload, headers=headers
        )

    def get_software_package(self, package_id, headers=None):
        return self.get(
            "{0}/software-packages/{1}".format(API_PREFIX, package_id), headers=headers
        )

    def publish_software_package(self, package_id, headers=None):
        return self.post(
            "{0}/software-packages/{1}/publish".format(API_PREFIX, package_id),
            json={},
            headers=headers,
        )

    def withdraw_software_package(self, package_id, headers=None):
        return self.post(
            "{0}/software-packages/{1}/withdraw".format(API_PREFIX, package_id),
            json={},
            headers=headers,
        )

    # --- Update deliveries --------------------------------------------------------------

    def create_update_delivery(self, payload, headers=None):
        return self.post(API_PREFIX + "/update-deliveries", json=payload, headers=headers)

    def get_update_delivery(self, delivery_id, headers=None):
        return self.get(
            "{0}/update-deliveries/{1}".format(API_PREFIX, delivery_id), headers=headers
        )

    def list_update_deliveries(self, headers=None, params=None):
        return self.get(API_PREFIX + "/update-deliveries", headers=headers, params=params)

    def start_update_download(self, delivery_id, headers=None):
        return self.post(
            "{0}/update-deliveries/{1}/start-download".format(API_PREFIX, delivery_id),
            json={},
            headers=headers,
        )

    def report_update_installed(self, delivery_id, headers=None):
        return self.post(
            "{0}/update-deliveries/{1}/report-installed".format(API_PREFIX, delivery_id),
            json={},
            headers=headers,
        )

    def report_update_failed(self, delivery_id, failure_reason, headers=None):
        return self.post(
            "{0}/update-deliveries/{1}/report-failed".format(API_PREFIX, delivery_id),
            json={"failure_reason": failure_reason},
            headers=headers,
        )

    # --- Feature licenses ------------------------------------------------------------------

    def create_feature_license(self, payload, headers=None):
        return self.post(API_PREFIX + "/feature-licenses", json=payload, headers=headers)

    def get_feature_license(self, license_id, headers=None):
        return self.get(
            "{0}/feature-licenses/{1}".format(API_PREFIX, license_id), headers=headers
        )

    def list_feature_licenses(self, headers=None, params=None):
        return self.get(API_PREFIX + "/feature-licenses", headers=headers, params=params)

    def activate_feature_license(self, license_id, headers=None):
        return self.post(
            "{0}/feature-licenses/{1}/activate".format(API_PREFIX, license_id),
            json={},
            headers=headers,
        )

    def suspend_feature_license(self, license_id, headers=None):
        return self.post(
            "{0}/feature-licenses/{1}/suspend".format(API_PREFIX, license_id),
            json={},
            headers=headers,
        )

    def revoke_feature_license(self, license_id, headers=None):
        return self.post(
            "{0}/feature-licenses/{1}/revoke".format(API_PREFIX, license_id),
            json={},
            headers=headers,
        )

    # --- Warranty claims -----------------------------------------------------------------------

    def create_warranty_claim(self, payload, headers=None):
        return self.post(API_PREFIX + "/warranty-claims", json=payload, headers=headers)

    def get_warranty_claim(self, claim_id, headers=None):
        return self.get(
            "{0}/warranty-claims/{1}".format(API_PREFIX, claim_id), headers=headers
        )

    def list_warranty_claims(self, headers=None, params=None):
        return self.get(API_PREFIX + "/warranty-claims", headers=headers, params=params)

    def submit_warranty_claim(self, claim_id, headers=None):
        return self.post(
            "{0}/warranty-claims/{1}/submit".format(API_PREFIX, claim_id),
            json={},
            headers=headers,
        )

    def decide_warranty_claim(self, claim_id, decision, headers=None):
        return self.post(
            "{0}/warranty-claims/{1}/decide".format(API_PREFIX, claim_id),
            json={"decision": decision},
            headers=headers,
        )

    def settle_warranty_claim(self, claim_id, headers=None):
        return self.post(
            "{0}/warranty-claims/{1}/settle".format(API_PREFIX, claim_id),
            json={},
            headers=headers,
        )

    # --- Integration partners ---------------------------------------------------------------------

    def create_integration_partner(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/integration-partners", json=payload, headers=headers
        )

    def get_integration_partner(self, partner_id, headers=None):
        return self.get(
            "{0}/integration-partners/{1}".format(API_PREFIX, partner_id),
            headers=headers,
        )

    def submit_partner_for_certification(self, partner_id, headers=None):
        return self.post(
            "{0}/integration-partners/{1}/submit-for-certification".format(
                API_PREFIX, partner_id
            ),
            json={},
            headers=headers,
        )

    def decide_partner_certification(self, partner_id, decision, headers=None):
        return self.post(
            "{0}/integration-partners/{1}/decide".format(API_PREFIX, partner_id),
            json={"decision": decision},
            headers=headers,
        )

    def partner_data_pull(self, partner_id, payload, headers=None):
        return self.post(
            "{0}/integration-partners/{1}/data-pull".format(API_PREFIX, partner_id),
            json=payload,
            headers=headers,
        )


api_client = ApiClient()
