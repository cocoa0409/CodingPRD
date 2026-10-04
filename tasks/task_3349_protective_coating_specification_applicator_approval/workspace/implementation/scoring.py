"""quality_history_score events, suspension cascades, probation tracking, decay sweep."""
from helpers import touch
from storage import store

PREP_FAILURE_PENALTY = 25
INSPECTION_PASS_BONUS = 10
INSPECTION_FAILURE_PENALTY = 75
VOC_VIOLATION_PENALTY = 100
PROBATION_PENALTY = 150
MONTHLY_DECAY = 5
SCORE_FLOOR = 0
SCORE_CEILING = 1000


def clamp(score):
    return max(SCORE_FLOOR, min(SCORE_CEILING, score))


def hold_work_orders(applicator_id):
    """Suspension cascade: SCHEDULED/PREP_INSPECTION/PREP_APPROVED -> ON_HOLD."""
    for wo in store.work_orders.values():
        if (wo['applicator_id'] == applicator_id
                and wo['status'] in ('SCHEDULED', 'PREP_INSPECTION', 'PREP_APPROVED')):
            wo['status'] = 'ON_HOLD'
            touch(wo)


def unhold_work_orders(applicator_id):
    """Reinstatement cascade: ON_HOLD -> SCHEDULED or PREP_APPROVED by hold point."""
    for wo in store.work_orders.values():
        if wo['applicator_id'] == applicator_id and wo['status'] == 'ON_HOLD':
            wo['status'] = 'PREP_APPROVED' if wo['hold_point_prep_released'] else 'SCHEDULED'
            touch(wo)


def cancel_held_work_orders(applicator_id):
    """Revocation cascade: ON_HOLD -> CANCELLED."""
    for wo in store.work_orders.values():
        if wo['applicator_id'] == applicator_id and wo['status'] == 'ON_HOLD':
            wo['status'] = 'CANCELLED'
            touch(wo)


def suspend_qualification(qual):
    qual['status'] = 'SUSPENDED'
    qual['suspension_count'] += 1
    touch(qual)
    hold_work_orders(qual['applicator_id'])


def apply_score_delta(applicator, delta):
    """Apply one score event: clamp, touch, then the CERTIFIED-below-floor cascade."""
    applicator['quality_history_score'] = clamp(
        applicator['quality_history_score'] + delta)
    touch(applicator)
    for qual in store.qualifications.values():
        if qual['applicator_id'] != applicator['id'] or qual['status'] != 'CERTIFIED':
            continue
        program = store.qualification_programs.get(qual['program_id'])
        if (program is not None
                and applicator['quality_history_score'] < program['min_quality_history_score']):
            suspend_qualification(qual)


def on_prep_failed(applicator):
    apply_score_delta(applicator, -PREP_FAILURE_PENALTY)


def on_voc_violation(applicator):
    apply_score_delta(applicator, -VOC_VIOLATION_PENALTY)


def on_report_filed(applicator, accepted):
    """Inspection report verdict: streak + score event, then probation tracking."""
    if accepted:
        applicator['consecutive_passed_inspections'] += 1
        apply_score_delta(applicator, INSPECTION_PASS_BONUS)
    else:
        applicator['consecutive_passed_inspections'] = 0
        apply_score_delta(applicator, -INSPECTION_FAILURE_PENALTY)
    probated = [q for q in store.qualifications.values()
                if q['applicator_id'] == applicator['id'] and q['status'] == 'PROBATION']
    for qual in probated:
        if accepted:
            progress = store.probation_progress.get(qual['id'], 0) + 1
            if progress >= 2:
                qual['status'] = 'CERTIFIED'
                touch(qual)
                store.probation_progress[qual['id']] = 0
            else:
                store.probation_progress[qual['id']] = progress
        else:
            store.probation_progress[qual['id']] = 0
            suspend_qualification(qual)


def on_application_error(applicator, qual):
    """ADJUDICATED_APPLICATION_ERROR: CERTIFIED -> PROBATION, then the 150pt penalty."""
    if qual is not None and qual['status'] == 'CERTIFIED':
        qual['status'] = 'PROBATION'
        touch(qual)
        store.probation_progress[qual['id']] = 0
    apply_score_delta(applicator, -PROBATION_PENALTY)


def monthly_decay(month_start, month_end):
    """-5 for each applicator with no ACCEPTED InspectionReport in [month_start, month_end)."""
    for applicator in list(store.applicators.values()):
        has_accept = False
        for rep in store.inspection_reports.values():
            if rep['overall_verdict'] != 'ACCEPTED':
                continue
            if not (month_start <= rep['_created_dt'] < month_end):
                continue
            app = store.applications.get(rep['coating_application_id'])
            if app is None:
                continue
            wo = store.work_orders.get(app['work_order_id'])
            if wo is not None and wo['applicator_id'] == applicator['id']:
                has_accept = True
                break
        if not has_accept:
            apply_score_delta(applicator, -MONTHLY_DECAY)
