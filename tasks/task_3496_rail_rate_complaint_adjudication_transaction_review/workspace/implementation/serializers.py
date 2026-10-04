"""Entity serializers. Internal keys (leading underscore) never serialize.

Identity timestamps render with exactly three fractional digits; domain
timestamps (issued_at, expires_at, comment_close_at, nitu_expires_at) were
stored as their rendered strings at computation time and pass through verbatim.
Ratios and scores are JSON numbers (SCAFFOLD entity table: type number).
"""
from timeutil import render_identity


def _identity(e):
    return {
        'created_at': render_identity(e['created_at']),
        'updated_at': render_identity(e['updated_at']),
        'version': e['version'],
    }


def carrier_view(c):
    d = {
        'id': c['id'],
        'carrier_code': c['carrier_code'],
        'legal_name': c['legal_name'],
        'carrier_class': c['carrier_class'],
        'base_route_miles': c['base_route_miles'],
        'active_route_miles': c['active_route_miles'],
        'abandoned_route_miles': c['abandoned_route_miles'],
        'trail_use_route_miles': c['trail_use_route_miles'],
        'revenue_adequacy_status': c['revenue_adequacy_status'],
        'compliance_standing': c['compliance_standing'],
        'reparation_exposure_cents': c['reparation_exposure_cents'],
    }
    d.update(_identity(c))
    return d


def finding_view(f):
    d = {
        'id': f['id'],
        'carrier_id': f['carrier_id'],
        'fiscal_year': f['fiscal_year'],
        'operating_revenue_cents': f['operating_revenue_cents'],
        'operating_expense_cents': f['operating_expense_cents'],
        'net_investment_cents': f['net_investment_cents'],
        'current_year_roi_bps': f['current_year_roi_bps'],
        'five_year_avg_roi_bps': f['five_year_avg_roi_bps'],
        'finding': f['finding'],
    }
    d.update(_identity(f))
    return d


def complaint_view(c):
    d = {
        'id': c['id'],
        'shipper_id': c['shipper_id'],
        'carrier_id': c['carrier_id'],
        'commodity': c['commodity'],
        'challenged_rate_cents_per_ton': c['challenged_rate_cents_per_ton'],
        'alleged_variable_cost_cents_per_ton': c['alleged_variable_cost_cents_per_ton'],
        'annual_tons': c['annual_tons'],
        'relief_sought_cents': c['relief_sought_cents'],
        'contested_fiscal_year': c['contested_fiscal_year'],
        'track': c['track'],
        'alleged_rvc_ratio': float(c['alleged_rvc_ratio']),
        'adjudicated_rvc_ratio': (None if c['adjudicated_rvc_ratio'] is None
                                  else float(c['adjudicated_rvc_ratio'])),
        'market_dominance': c['market_dominance'],
        'status': c['status'],
        'decision_outcome': c['decision_outcome'],
        'prescribed_rate_cents_per_ton': c['prescribed_rate_cents_per_ton'],
        'relief_granted_cents': c['relief_granted_cents'],
        'award_granted_cents': c['award_granted_cents'],
        'award_paid_cents': c['award_paid_cents'],
        'award_outstanding_cents': c['award_outstanding_cents'],
        'award_status': c['award_status'],
    }
    d.update(_identity(c))
    return d


def evidence_view(e):
    d = {
        'id': e['id'],
        'rate_complaint_id': e['rate_complaint_id'],
        'submission_type': e['submission_type'],
        'submitted_by_party': e['submitted_by_party'],
        'reference_rate_cents_per_ton': e['reference_rate_cents_per_ton'],
        'verified_variable_cost_cents_per_ton': e['verified_variable_cost_cents_per_ton'],
        'review_status': e['review_status'],
    }
    d.update(_identity(e))
    return d


def service_complaint_view(s):
    d = {
        'id': s['id'],
        'shipper_id': s['shipper_id'],
        'carrier_id': s['carrier_id'],
        'issue_type': s['issue_type'],
        'territory_code': s['territory_code'],
        'status': s['status'],
    }
    d.update(_identity(s))
    return d


def eso_view(e):
    d = {
        'id': e['id'],
        'carrier_id': e['carrier_id'],
        'service_complaint_id': e['service_complaint_id'],
        'directive': e['directive'],
        'issued_at': e['issued_at'],
        'expires_at': e['expires_at'],
        'status': e['status'],
    }
    d.update(_identity(e))
    return d


def merger_view(m):
    d = {
        'id': m['id'],
        'acquiring_carrier_id': m['acquiring_carrier_id'],
        'target_carrier_id': m['target_carrier_id'],
        'transaction_value_cents': m['transaction_value_cents'],
        'competition_preservation_score': m['competition_preservation_score'],
        'service_reliability_score': m['service_reliability_score'],
        'shipper_impact_score': m['shipper_impact_score'],
        'public_interest_score': float(m['public_interest_score']),
        'comment_close_at': m['comment_close_at'],
        'service_review_hold': m['service_review_hold'],
        'status': m['status'],
        'conditions_imposed': list(m['conditions_imposed']),
    }
    d.update(_identity(m))
    return d


def plan_view(p):
    d = {
        'id': p['id'],
        'merger_application_id': p['merger_application_id'],
        'plan_name': p['plan_name'],
        'commitments': list(p['commitments']),
        'conditions': list(p.get('conditions', [])),
        'status': p['status'],
    }
    d.update(_identity(p))
    return d


def abandonment_view(a):
    d = {
        'id': a['id'],
        'carrier_id': a['carrier_id'],
        'line_segment_ref': a['line_segment_ref'],
        'segment_miles': a['segment_miles'],
        'public_convenience_finding': a['public_convenience_finding'],
        'status': a['status'],
        'nitu_expires_at': a['nitu_expires_at'],
    }
    d.update(_identity(a))
    return d


def petition_view(p):
    d = {
        'id': p['id'],
        'shipper_id': p['shipper_id'],
        'incumbent_carrier_id': p['incumbent_carrier_id'],
        'interchange_code': p['interchange_code'],
        'facility_distance_miles': p['facility_distance_miles'],
        'evidence_service_complaint_id': p['evidence_service_complaint_id'],
        'service_start_date': p['service_start_date'],
        'service_end_date': p['service_end_date'],
        'status': p['status'],
    }
    d.update(_identity(p))
    return d
