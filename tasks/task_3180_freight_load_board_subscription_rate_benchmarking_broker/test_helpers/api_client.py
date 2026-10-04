"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # Clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # Broker orgs
    def create_broker_org(self, payload, headers):
        return self._request("POST", "/broker-orgs", payload, headers)

    def list_broker_orgs(self, headers, params=None):
        return self._request("GET", "/broker-orgs", headers=headers, params=params)

    def get_broker_org(self, broker_id, headers):
        return self._request("GET", f"/broker-orgs/{broker_id}", headers=headers)

    def suspend_broker_org(self, broker_id, headers):
        return self._request("POST", f"/broker-orgs/{broker_id}/suspend", headers=headers)

    def reinstate_broker_org(self, broker_id, headers):
        return self._request("POST", f"/broker-orgs/{broker_id}/reinstate", headers=headers)

    def deactivate_broker_org(self, broker_id, headers):
        return self._request("POST", f"/broker-orgs/{broker_id}/deactivate", headers=headers)

    # Carrier orgs
    def create_carrier_org(self, payload, headers):
        return self._request("POST", "/carrier-orgs", payload, headers)

    def list_carrier_orgs(self, headers, params=None):
        return self._request("GET", "/carrier-orgs", headers=headers, params=params)

    def get_carrier_org(self, carrier_id, headers):
        return self._request("GET", f"/carrier-orgs/{carrier_id}", headers=headers)

    def suspend_carrier_org(self, carrier_id, headers):
        return self._request("POST", f"/carrier-orgs/{carrier_id}/suspend", headers=headers)

    def reinstate_carrier_org(self, carrier_id, headers):
        return self._request("POST", f"/carrier-orgs/{carrier_id}/reinstate", headers=headers)

    # Subscription plans
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    def list_subscription_plans(self, headers, params=None):
        return self._request("GET", "/subscription-plans", headers=headers, params=params)

    # Subscriptions
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def change_plan(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/change-plan", payload, headers)

    def mark_past_due(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/mark-past-due", headers=headers)

    def record_payment(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/record-payment", headers=headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/cancel", headers=headers)

    # Load posts
    def create_load_post(self, payload, headers):
        return self._request("POST", "/load-posts", payload, headers)

    def list_load_posts(self, headers, params=None):
        return self._request("GET", "/load-posts", headers=headers, params=params)

    def get_load_post(self, load_id, headers):
        return self._request("GET", f"/load-posts/{load_id}", headers=headers)

    def withdraw_load_post(self, load_id, headers):
        return self._request("POST", f"/load-posts/{load_id}/withdraw", headers=headers)

    # Truck posts
    def create_truck_post(self, payload, headers):
        return self._request("POST", "/truck-posts", payload, headers)

    def list_truck_posts(self, headers, params=None):
        return self._request("GET", "/truck-posts", headers=headers, params=params)

    def get_truck_post(self, truck_id, headers):
        return self._request("GET", f"/truck-posts/{truck_id}", headers=headers)

    def withdraw_truck_post(self, truck_id, headers):
        return self._request("POST", f"/truck-posts/{truck_id}/withdraw", headers=headers)

    # Bookings
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    # Rate transactions
    def create_rate_transaction(self, payload, headers):
        return self._request("POST", "/rate-transactions", payload, headers)

    def list_rate_transactions(self, headers, params=None):
        return self._request("GET", "/rate-transactions", headers=headers, params=params)

    def get_rate_transaction(self, rt_id, headers):
        return self._request("GET", f"/rate-transactions/{rt_id}", headers=headers)

    def exclude_rate_transaction(self, rt_id, headers):
        return self._request("POST", f"/rate-transactions/{rt_id}/exclude", headers=headers)

    # Lane benchmarks
    def get_lane_rate_benchmark(self, headers, params):
        return self._request("GET", "/lane-rate-benchmarks", headers=headers, params=params)

    # Credit report events
    def create_credit_report_event(self, payload, headers):
        return self._request("POST", "/credit-report-events", payload, headers)

    def list_credit_report_events(self, headers, params=None):
        return self._request("GET", "/credit-report-events", headers=headers, params=params)

    def get_credit_report_event(self, event_id, headers):
        return self._request("GET", f"/credit-report-events/{event_id}", headers=headers)

    # Credit disputes
    def file_dispute(self, event_id, payload, headers):
        return self._request("POST", f"/credit-report-events/{event_id}/disputes", payload, headers)

    def list_credit_disputes(self, headers, params=None):
        return self._request("GET", "/credit-disputes", headers=headers, params=params)

    def get_credit_dispute(self, dispute_id, headers):
        return self._request("GET", f"/credit-disputes/{dispute_id}", headers=headers)

    def start_dispute_review(self, dispute_id, headers):
        return self._request("POST", f"/credit-disputes/{dispute_id}/start-review", headers=headers)

    def rebut_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/credit-disputes/{dispute_id}/rebut", payload, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/credit-disputes/{dispute_id}/resolve", payload, headers)

    # Authority verifications
    def create_authority_verification(self, payload, headers):
        return self._request("POST", "/authority-verifications", payload, headers)

    def get_authority_verification(self, av_id, headers):
        return self._request("GET", f"/authority-verifications/{av_id}", headers=headers)

    def list_broker_authority_verifications(self, broker_id, headers, params=None):
        return self._request("GET", f"/broker-orgs/{broker_id}/authority-verifications",
                             headers=headers, params=params)

    def list_carrier_authority_verifications(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carrier-orgs/{carrier_id}/authority-verifications",
                             headers=headers, params=params)

    def verify_authority(self, av_id, headers):
        return self._request("POST", f"/authority-verifications/{av_id}/verify", headers=headers)

    def revoke_authority(self, av_id, headers):
        return self._request("POST", f"/authority-verifications/{av_id}/revoke", headers=headers)

    # Fraud alerts
    def create_fraud_alert(self, payload, headers):
        return self._request("POST", "/fraud-alerts", payload, headers)

    def list_fraud_alerts(self, headers, params=None):
        return self._request("GET", "/fraud-alerts", headers=headers, params=params)

    def get_fraud_alert(self, alert_id, headers):
        return self._request("GET", f"/fraud-alerts/{alert_id}", headers=headers)

    def confirm_fraud_alert(self, alert_id, headers):
        return self._request("POST", f"/fraud-alerts/{alert_id}/confirm", headers=headers)

    def dismiss_fraud_alert(self, alert_id, headers):
        return self._request("POST", f"/fraud-alerts/{alert_id}/dismiss", headers=headers)


api_client = ApiClient()
