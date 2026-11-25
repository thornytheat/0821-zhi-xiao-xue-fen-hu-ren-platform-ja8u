from collections import Counter


def balance(intake, cases):
    accounted = intake['accepted'] + intake['rejected'] + intake['blank'] + intake['repeated']
    status = Counter(case['status'] for case in cases)
    ready = status.pop('READY', 0)
    observed = sum(len(case['records']) for case in cases)
    signable = sum(1 for case in cases if case.get('releasable', case['status'] == 'READY'))
    held = sum(1 for case in cases if case.get('holds'))
    blocked = bool(intake.get('global_hold'))
    balanced = accounted == intake['input'] and observed == intake['accepted']
    return dict(input=intake['input'], accepted=intake['accepted'], isolated=intake['rejected'],
                ignored=intake['blank'] + intake['repeated'], accounted=accounted,
                balanced=balanced,
                ready=ready, pending=len(cases) - ready, issues=dict(sorted(status.items())),
                signable=signable, held=held, blocked=blocked,
                partial=bool(cases) and balanced and 0 < signable < len(cases),
                releasable=bool(cases) and signable == len(cases) and balanced)
