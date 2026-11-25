from app.business import DomainIssue
from app.intake.service import inspect
from app.modules.calculate import compute
from app.modules.grouping import case_groups
from app.modules.policy import policy
from app.modules.prepare import prepare
from app.modules.reconcile import balance


def evaluate(rows, stage, holds=(), blocked=False):
    case = {'case': rows[0]['case'], 'records': [r['record'] for r in rows], 'status': 'READY'}
    try:
        case['prep'], payload = prepare(rows)
        if stage >= 3:
            case['measure'] = compute(payload)
        if stage >= 4:
            case.update(policy(case['measure']))
    except DomainIssue as error:
        case['status'] = error.code
    case['holds'] = sorted(holds)
    case['releasable'] = case['status'] == 'READY' and not case['holds'] and not blocked
    return case


def run(data, stage=5):
    intake = inspect(data)
    materials = intake['materials']
    output = {'intake': {k: v for k, v in intake.items() if k not in {'rows', 'materials'}}}
    if stage == 1:
        return output
    groups = list(case_groups(intake['rows']))
    blocked = bool(intake['global_hold'])
    cases = [evaluate(rows, stage, intake['holds'].get(case, ()), blocked) for case, rows in groups]
    output['cases'] = cases
    output['materials'] = materials
    if stage >= 5:
        output['balance'] = balance(intake, cases)
    return output
