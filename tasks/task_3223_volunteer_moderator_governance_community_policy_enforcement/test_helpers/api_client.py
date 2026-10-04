"""API client: one method per endpoint declared by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- platform core -------------------------------------------------------
    def create_community(self, payload, headers):
        return self._request("POST", "/api/communities", payload, headers)

    def list_communities(self, headers, params=None):
        return self._request("GET", "/api/communities", headers=headers, params=params)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/api/communities/{community_id}", headers=headers)

    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    # --- community rules -----------------------------------------------------
    def create_rule(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/rules", payload, headers)

    def update_rule(self, community_id, rule_id, payload, headers):
        return self._request("PUT", f"/api/communities/{community_id}/rules/{rule_id}", payload, headers)

    def list_rules(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/rules", headers=headers, params=params)

    def get_rule(self, community_id, rule_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/rules/{rule_id}", headers=headers)

    def escalate_rule(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/escalations", payload, headers)

    def list_escalations(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/escalations", headers=headers, params=params)

    # --- moderator team ------------------------------------------------------
    def create_moderator(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/moderators", payload, headers)

    def list_moderators(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/moderators", headers=headers, params=params)

    def get_moderator(self, community_id, moderator_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/moderators/{moderator_id}", headers=headers)

    def get_moderator_by_id(self, moderator_id, headers):
        return self._request("GET", f"/api/moderators/{moderator_id}", headers=headers)

    def list_moderator_approvals(self, moderator_id, headers, params=None):
        return self._request("GET", f"/api/moderators/{moderator_id}/approvals", headers=headers, params=params)

    def list_moderator_actions(self, moderator_id, headers, params=None):
        return self._request("GET", f"/api/moderators/{moderator_id}/actions", headers=headers, params=params)

    def remove_moderator(self, community_id, moderator_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/moderators/{moderator_id}/remove", payload, headers)

    def resign_moderator(self, community_id, moderator_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/moderators/{moderator_id}/resign", payload, headers)

    def demote_moderator(self, community_id, moderator_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/moderators/{moderator_id}/demote", payload, headers)

    def reinstate_moderator(self, community_id, moderator_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/moderators/{moderator_id}/reinstate", payload, headers)

    # --- succession ----------------------------------------------------------
    def create_succession(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/successions", payload, headers)

    def list_successions(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/successions", headers=headers, params=params)

    def get_succession(self, community_id, succession_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/successions/{succession_id}", headers=headers)

    def record_succession_discussion(self, community_id, succession_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/successions/{succession_id}/discussions", payload, headers)

    def dispute_succession(self, community_id, succession_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/successions/{succession_id}/disputes", payload, headers)

    def prevent_succession(self, community_id, succession_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/successions/{succession_id}/prevent", payload, headers)

    # --- posts and reports ---------------------------------------------------
    def create_post(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/posts", payload, headers)

    def list_posts(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/posts", headers=headers, params=params)

    def get_post(self, community_id, post_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/posts/{post_id}", headers=headers)

    def list_account_posts(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/posts", headers=headers, params=params)

    def create_content_report(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/content-reports", payload, headers)

    def list_content_reports(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/content-reports", headers=headers, params=params)

    def get_content_report(self, community_id, report_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/content-reports/{report_id}", headers=headers)

    # --- automated detection -------------------------------------------------
    def create_detection_item(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/automated-detection-backlog-items", payload, headers)

    def list_detection_items(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/automated-detection-backlog-items", headers=headers, params=params)

    def get_detection_item(self, community_id, item_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/automated-detection-backlog-items/{item_id}", headers=headers)

    def list_account_detection_backlog(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/detection-backlog", headers=headers, params=params)

    # --- content decisions ---------------------------------------------------
    def create_content_decision(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/content-decisions", payload, headers)

    def list_content_decisions(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/content-decisions", headers=headers, params=params)

    def get_content_decision(self, community_id, decision_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/content-decisions/{decision_id}", headers=headers)

    # --- account-wide enforcement -------------------------------------------
    def apply_account_wide_sanction(self, payload, headers):
        return self._request("POST", "/api/community-administration/account-sanctions", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def list_account_sanctions(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/sanctions", headers=headers, params=params)

    def list_community_sanctions(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/account-sanctions", headers=headers, params=params)

    def reinstate_sanction(self, payload, headers):
        return self._request("POST", "/api/community-administration/sanction-reinstatements", payload, headers)

    # --- appeals -------------------------------------------------------------
    def file_appeal(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/appeals", payload, headers)

    def list_account_appeals(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/appeals", headers=headers, params=params)

    def list_community_appeals(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/appeals", headers=headers, params=params)

    def get_appeal(self, account_id, appeal_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}/appeals/{appeal_id}", headers=headers)

    def submit_appeal(self, account_id, appeal_id, headers):
        return self._request("POST", f"/api/accounts/{account_id}/appeals/{appeal_id}/submit", {}, headers)

    def refer_appeal(self, appeal_id, headers, note=None):
        payload = {"appeal_id": appeal_id}
        if note is not None:
            payload["note"] = note
        return self._request("POST", "/api/community-administration/appeal-referrals", payload, headers)

    def decide_appeal(self, account_id, appeal_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/appeals/{appeal_id}/decide", payload, headers)

    # --- brigading -----------------------------------------------------------
    def create_brigade_cluster(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/brigade-clusters", payload, headers)

    def list_brigade_clusters(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/brigade-clusters", headers=headers, params=params)

    def get_brigade_cluster(self, community_id, cluster_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/brigade-clusters/{cluster_id}", headers=headers)

    def dismiss_brigade_cluster(self, community_id, cluster_id, headers):
        return self._request("POST", f"/api/communities/{community_id}/brigade-clusters/{cluster_id}/dismiss", {}, headers)

    def escalate_brigade_cluster(self, payload, headers):
        return self._request("POST", "/api/community-administration/brigade-escalations", payload, headers)

    def revive_brigade_cluster(self, payload, headers):
        return self._request("POST", "/api/community-administration/brigade-revivals", payload, headers)

    # --- community posture and platform response -----------------------------
    def request_reinstatement(self, community_id, headers):
        return self._request("POST", f"/api/communities/{community_id}/reinstatement-requests", {}, headers)

    def create_protest(self, community_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/protests", payload, headers)

    def list_protests(self, community_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/protests", headers=headers, params=params)

    def get_protest(self, community_id, protest_id, headers):
        return self._request("GET", f"/api/communities/{community_id}/protests/{protest_id}", headers=headers)

    def get_protest_by_id(self, protest_id, headers):
        return self._request("GET", f"/api/protests/{protest_id}", headers=headers)

    def list_protest_approvals(self, protest_id, headers, params=None):
        return self._request("GET", f"/api/protests/{protest_id}/approvals", headers=headers, params=params)

    def approve_protest(self, community_id, protest_id, payload, headers):
        return self._request("POST", f"/api/communities/{community_id}/protests/{protest_id}/approvals", payload, headers)

    def list_community_protest_approvals(self, community_id, protest_id, headers, params=None):
        return self._request("GET", f"/api/communities/{community_id}/protests/{protest_id}/approvals", headers=headers, params=params)

    def coordinate_protest(self, community_id, protest_id, headers):
        return self._request("POST", f"/api/communities/{community_id}/protests/{protest_id}/coordinate", {}, headers)

    def end_protest(self, community_id, protest_id, headers):
        return self._request("POST", f"/api/communities/{community_id}/protests/{protest_id}/end", {}, headers)

    def issue_policy_advisory(self, payload, headers):
        return self._request("POST", "/api/community-administration/policy-advisories", payload, headers)

    def record_regulation_cadence(self, payload, headers):
        return self._request("POST", "/api/community-administration/regulation-cadences", payload, headers)

    def start_institution_negotiation(self, payload, headers):
        return self._request("POST", "/api/community-administration/institution-negotiations", payload, headers)

    def audit_decision(self, payload, headers):
        return self._request("POST", "/api/community-administration/decision-audits", payload, headers)

    def revise_decision(self, payload, headers):
        return self._request("POST", "/api/community-administration/decision-revisions", payload, headers)

    def reaudit_decision(self, payload, headers):
        return self._request("POST", "/api/community-administration/decision-reaudits", payload, headers)

    def archive_community(self, payload, headers):
        return self._request("POST", "/api/community-administration/archivals", payload, headers)


api_client = ApiClient()