import json
import re
from collections import Counter, defaultdict
from csv import Error
from hashlib import sha256

from app.business import DomainIssue
from app.intake.reader import records
from app.intake.resolve import partition
from app.intake.schema import HEADER, record

IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,35}')


def materials(submitted):
    """按申请登记的材料指纹。

    指纹覆盖该申请提交的全部原始记录（含被隔离的行），因此一份材料即使被更正
    成不可采信，也会被视为新版材料生效。
    """
    return {case: sha256(json.dumps(sorted(set(rows)), ensure_ascii=False).encode()).hexdigest()
            for case, rows in sorted(submitted.items())}


def applications(accepted):
    """已采信申请号。坏行只有指向这些申请时才算有归属。"""
    return {row['case'] for row in accepted}


def attribute(rejects, known):
    """把隔离行归到所属申请。

    不属于任何已采信申请的坏行无法判断学分归属，单列为 global_hold，整批申请暂缓。
    坏行自报的 case 不足以成为归属依据：一份申请若没有采信记录，就不构成申请。
    DUPLICATE_REPLAY 是逐字重复的副本，不改变所属申请，因此不构成暂缓。
    """
    per_case = defaultdict(set)
    unattributed = Counter()
    for item in rejects:
        if item['reason'] == 'DUPLICATE_REPLAY':
            continue
        if item['case'] in known:
            per_case[item['case']].add(item['reason'])
        else:
            unattributed[item['reason']] += 1
    return per_case, dict(sorted(unattributed.items()))


def record_conflicts(seen, known):
    """同一记录号出现在两份申请时，两份申请都暂缓。"""
    conflicts = []
    for key, cases in seen.items():
        involved = sorted(case for case in cases if case in known)
        if len(involved) >= 2:
            conflicts.append({'record': key, 'cases': involved})
    return sorted(conflicts, key=lambda item: item['record'])


def inspect(data):
    counted = repeated = blanks = 0
    candidates, rejected = [], []
    seen = defaultdict(set)
    submitted = defaultdict(list)
    try:
        for line, values in records(data):
            counted += 1
            if not any(v.strip() for v in values):
                blanks += 1
                continue
            if tuple(values) == HEADER:
                repeated += 1
                continue
            key = values[0].strip() if values else ''
            case = values[1].strip() if len(values) > 1 else ''
            if IDENTIFIER.fullmatch(key) and IDENTIFIER.fullmatch(case):
                seen[key].add(case)
                submitted[case].append(tuple(values))
            try:
                candidates.append((line, record(values)))
            except DomainIssue as error:
                rejected.append(dict(line=line, record=key[:36], case=case[:36], reason=error.code))
    except Error as error:
        raise DomainIssue('CSV_MALFORMED') from error
    accepted, conflicts = partition(candidates)
    rejects = sorted(rejected + conflicts, key=lambda row: row['line'])
    known = applications(accepted)
    per_case, unattributed = attribute(rejects, known)
    cross = record_conflicts(seen, known)
    for item in cross:
        for case in item['cases']:
            per_case.setdefault(case, set()).add('RECORD_CASE_CONFLICT')
    holds = {case: sorted(per_case[case]) for case in sorted(per_case)}
    return dict(input=counted, accepted=len(accepted), repeated=repeated, blank=blanks,
                rejected=len(rejects), reasons=dict(Counter(r['reason'] for r in rejects)),
                isolation=rejects, holds=holds, global_hold=unattributed,
                record_conflicts=cross, materials=materials(submitted), rows=accepted)
