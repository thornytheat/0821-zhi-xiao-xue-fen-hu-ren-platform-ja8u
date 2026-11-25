from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.config import RULE_VERSION
from app.modules.pipeline import run

STATES = ('APPROVED', 'HELD')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def execute(store, data):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    run_id = sha256(f'{RULE_VERSION}:{fingerprint}'.encode()).hexdigest()
    try:
        return store.load(run_id)
    except DomainIssue as error:
        if error.code != 'RUN_NOT_FOUND':
            raise
    report = run(data)
    report['manifest'] = dict(sha256=fingerprint, version=RULE_VERSION, created=now(),
                              duration_ms=round((monotonic()-start)*1000,3), bytes=len(data), run_id=run_id)
    return store.register(run_id,report)


def requested(values, cases):
    """复核意见可以整批复用，也可以逐个申请提交。

    提交 `cases` 时只按逐份结论判定，`status` 视为整批期望状态而忽略：
    只要还有申请未签发，批次状态就是 `HELD`。
    """
    per_case = values.get('cases')
    if per_case is None:
        return {case['case']: values.get('status') for case in cases}, False
    if not isinstance(per_case, dict) or not per_case:
        raise DomainIssue('REVIEW_FIELDS')
    known = {case['case'] for case in cases}
    for name, state in per_case.items():
        if name not in known or state not in STATES:
            raise DomainIssue('REVIEW_FIELDS')
    return per_case, True


def settle(db, store, run_id, current, decisions, explicit, batch_approved, note):
    """在写锁内逐个申请判定；旧材料已被更正时拒绝签发。"""
    cases = {case['case']: case for case in current['report']['cases']}
    merged = dict(current['decisions'])
    if batch_approved and not current['report']['balance']['releasable']:
        raise DomainIssue('UNRESOLVED_ISSUES')
    for name, state in decisions.items():
        if merged.get(name) == 'APPROVED':
            if explicit:
                raise DomainIssue('RUN_FINALIZED')
            continue
        if state == 'APPROVED':
            if not current['report']['balance']['balanced'] or not cases[name].get('releasable'):
                raise DomainIssue('UNRESOLVED_ISSUES')
            if store.superseded(db, run_id, [name]):
                raise DomainIssue('STALE_MATERIAL')
        merged[name] = state
    status = 'APPROVED' if cases and all(merged.get(name) == 'APPROVED' for name in cases) else 'HELD'
    return status, dict(sorted(merged.items())), note


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue('REVIEW_FIELDS')
    revision, status, note = (values.get(key) for key in ('revision','status','note'))
    if type(revision) is not int or revision < 0 or not isinstance(note,str) or not (3<=len(note.strip())<=200):
        raise DomainIssue('REVIEW_FIELDS')
    if 'cases' not in values and status not in STATES:
        raise DomainIssue('REVIEW_FIELDS')
    current = store.load(run_id)
    decisions, explicit = requested(values, current['report']['cases'])
    batch_approved = not explicit and status == 'APPROVED'
    return store.decide(run_id, revision,
                        lambda db, fresh: settle(db, store, run_id, fresh, decisions, explicit,
                                                 batch_approved, note.strip()),
                        now())
