"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock -------------------------------------------------------

    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- funding units -------------------------------------------------------

    def create_funding_unit(self, payload, headers):
        return self._request("POST", "/funding-units", payload, headers)

    def list_funding_units(self, headers, params=None):
        return self._request("GET", "/funding-units", headers=headers, params=params)

    def get_funding_unit(self, unit_id, headers):
        return self._request("GET", f"/funding-units/{unit_id}", headers=headers)

    def list_funding_unit_faculty(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/funding-units/{unit_id}/faculty", headers=headers, params=params
        )

    # --- faculty -------------------------------------------------------------

    def create_faculty(self, payload, headers):
        return self._request("POST", "/faculty", payload, headers)

    def list_faculty(self, headers, params=None):
        return self._request("GET", "/faculty", headers=headers, params=params)

    def get_faculty(self, faculty_id, headers):
        return self._request("GET", f"/faculty/{faculty_id}", headers=headers)

    def activate_faculty(self, faculty_id, headers, payload=None):
        return self._request(
            "POST", f"/faculty/{faculty_id}/activate", payload or {}, headers
        )

    def record_departure_notice(self, faculty_id, payload, headers):
        return self._request(
            "POST", f"/faculty/{faculty_id}/departure-notice", payload, headers
        )

    def separate_faculty(self, faculty_id, headers, payload=None):
        return self._request(
            "POST", f"/faculty/{faculty_id}/separate", payload or {}, headers
        )

    # --- startup packages ----------------------------------------------------

    def create_startup_package(self, payload, headers):
        return self._request("POST", "/startup-packages", payload, headers)

    def list_startup_packages(self, headers, params=None):
        return self._request("GET", "/startup-packages", headers=headers, params=params)

    def get_startup_package(self, package_id, headers):
        return self._request("GET", f"/startup-packages/{package_id}", headers=headers)

    def create_commitment_tranche(self, package_id, payload, headers):
        return self._request(
            "POST", f"/startup-packages/{package_id}/tranches", payload, headers
        )

    def delete_commitment_tranche(self, package_id, tranche_id, headers):
        return self._request(
            "DELETE",
            f"/startup-packages/{package_id}/tranches/{tranche_id}",
            headers=headers,
        )

    def list_package_tranches(self, package_id, headers, params=None):
        return self._request(
            "GET",
            f"/startup-packages/{package_id}/tranches",
            headers=headers,
            params=params,
        )

    def list_package_staff_appointments(self, package_id, headers, params=None):
        return self._request(
            "GET",
            f"/startup-packages/{package_id}/staff-appointments",
            headers=headers,
            params=params,
        )

    def list_package_spend_transactions(self, package_id, headers, params=None):
        return self._request(
            "GET",
            f"/startup-packages/{package_id}/spend-transactions",
            headers=headers,
            params=params,
        )

    def get_package_spend_summary(self, package_id, headers):
        return self._request(
            "GET", f"/startup-packages/{package_id}/spend-summary", headers=headers
        )

    def submit_startup_package(self, package_id, headers, payload=None):
        return self._request(
            "POST", f"/startup-packages/{package_id}/submit", payload or {}, headers
        )

    def endorse_startup_package(self, package_id, headers, payload=None):
        return self._request(
            "POST", f"/startup-packages/{package_id}/endorse", payload or {}, headers
        )

    def counter_startup_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/startup-packages/{package_id}/counter", payload, headers
        )

    def revise_startup_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/startup-packages/{package_id}/revise", payload, headers
        )

    def approve_startup_package(self, package_id, headers, payload=None):
        return self._request(
            "POST", f"/startup-packages/{package_id}/approve", payload or {}, headers
        )

    def activate_startup_package(self, package_id, headers, payload=None):
        return self._request(
            "POST", f"/startup-packages/{package_id}/activate", payload or {}, headers
        )

    def year_end_rollover(self, package_id, payload, headers):
        return self._request(
            "POST",
            f"/startup-packages/{package_id}/year-end-rollover",
            payload,
            headers,
        )

    def close_out_startup_package(self, package_id, headers, payload=None):
        return self._request(
            "POST", f"/startup-packages/{package_id}/close-out", payload or {}, headers
        )

    # --- commitment tranches -------------------------------------------------

    def get_commitment_tranche(self, tranche_id, headers):
        return self._request("GET", f"/commitment-tranches/{tranche_id}", headers=headers)

    def list_tranche_spend_transactions(self, tranche_id, headers, params=None):
        return self._request(
            "GET",
            f"/commitment-tranches/{tranche_id}/spend-transactions",
            headers=headers,
            params=params,
        )

    # --- lab spaces ----------------------------------------------------------

    def create_lab_space(self, payload, headers):
        return self._request("POST", "/lab-spaces", payload, headers)

    def list_lab_spaces(self, headers, params=None):
        return self._request("GET", "/lab-spaces", headers=headers, params=params)

    def get_lab_space(self, space_id, headers):
        return self._request("GET", f"/lab-spaces/{space_id}", headers=headers)

    def upgrade_lab_space_utilities(self, space_id, payload, headers):
        return self._request(
            "POST", f"/lab-spaces/{space_id}/utility-upgrade", payload, headers
        )

    # --- space assignments ---------------------------------------------------

    def create_space_assignment(self, payload, headers):
        return self._request("POST", "/space-assignments", payload, headers)

    def list_space_assignments(self, headers, params=None):
        return self._request("GET", "/space-assignments", headers=headers, params=params)

    def get_space_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/space-assignments/{assignment_id}", headers=headers
        )

    def activate_space_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/space-assignments/{assignment_id}/activate", payload or {}, headers
        )

    def release_space_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/space-assignments/{assignment_id}/release", payload, headers
        )

    # --- renovation projects -------------------------------------------------

    def create_renovation_project(self, payload, headers):
        return self._request("POST", "/renovation-projects", payload, headers)

    def list_renovation_projects(self, headers, params=None):
        return self._request(
            "GET", "/renovation-projects", headers=headers, params=params
        )

    def get_renovation_project(self, project_id, headers):
        return self._request("GET", f"/renovation-projects/{project_id}", headers=headers)

    def create_renovation_phase(self, project_id, payload, headers):
        return self._request(
            "POST", f"/renovation-projects/{project_id}/phases", payload, headers
        )

    def list_renovation_phases(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/renovation-projects/{project_id}/phases",
            headers=headers,
            params=params,
        )

    def solicit_renovation_bids(self, project_id, headers, payload=None):
        return self._request(
            "POST",
            f"/renovation-projects/{project_id}/solicit-bids",
            payload or {},
            headers,
        )

    def rescope_renovation_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/renovation-projects/{project_id}/rescope", payload, headers
        )

    def award_renovation_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/renovation-projects/{project_id}/award", payload, headers
        )

    def start_renovation_phase(self, project_id, phase_id, headers, payload=None):
        return self._request(
            "POST",
            f"/renovation-projects/{project_id}/phases/{phase_id}/start",
            payload or {},
            headers,
        )

    def complete_renovation_phase(self, project_id, phase_id, payload, headers):
        return self._request(
            "POST",
            f"/renovation-projects/{project_id}/phases/{phase_id}/complete",
            payload,
            headers,
        )

    def substantial_completion(self, project_id, headers, payload=None):
        return self._request(
            "POST",
            f"/renovation-projects/{project_id}/substantial-completion",
            payload or {},
            headers,
        )

    # --- equipment orders ----------------------------------------------------

    def create_equipment_order(self, payload, headers):
        return self._request("POST", "/equipment-orders", payload, headers)

    def list_equipment_orders(self, headers, params=None):
        return self._request("GET", "/equipment-orders", headers=headers, params=params)

    def get_equipment_order(self, order_id, headers):
        return self._request("GET", f"/equipment-orders/{order_id}", headers=headers)

    def place_equipment_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/equipment-orders/{order_id}/place", payload, headers
        )

    def receive_equipment_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/equipment-orders/{order_id}/receive", payload or {}, headers
        )

    def install_equipment_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/equipment-orders/{order_id}/install", payload or {}, headers
        )

    def cancel_equipment_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/equipment-orders/{order_id}/cancel", payload or {}, headers
        )

    # --- staff appointments --------------------------------------------------

    def create_staff_appointment(self, payload, headers):
        return self._request("POST", "/staff-appointments", payload, headers)

    def get_staff_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/staff-appointments/{appointment_id}", headers=headers
        )

    def activate_staff_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/staff-appointments/{appointment_id}/activate",
            payload or {},
            headers,
        )

    def end_staff_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/staff-appointments/{appointment_id}/end", payload, headers
        )


api_client = ApiClient()
