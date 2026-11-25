import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.business import DomainIssue
from app.evidence.render import artifact
from app.intake.service import inspect
from app.modules.pipeline import run
from app.review.service import execute, review
from conftest import csv_data


def row(record, case, kind='external', external='1', local='0', credits='3', priority='0', note='校核'):
    return [record, case, kind, external, local, credits, priority, note]


def application(case):
    return [row(f'{case}01', case),
            row(f'{case}02', case, 'required', '0', '1', '3'),
            row(f'{case}03', case, 'equivalence', '1', '1', '3'),
            row(f'{case}04', case, 'authorization', '0', '0', '3')]


def edit(data, record, patch):
    """按记录号改写一组单元格，返回新的 CSV 字节。"""
    rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'), newline='')))
    rows = [rows[0], *[row if row[0] != record else patch(row) for row in rows[1:]]]
    stream = io.StringIO(newline='')
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode()


def corrected(clean):
    return edit(clean, '000206', lambda row: [*row[:7], '更正材料'])


# --- 隔离行归属 -------------------------------------------------------------

def test_record_shared_by_two_applications_holds_both():
    data = csv_data([*application('0001'), *application('0002'), row('000101', '0002')])
    result = inspect(data)
    assert result['record_conflicts'] == [{'record': '000101', 'cases': ['0001', '0002']}]
    assert set(result['holds']) == {'0001', '0002'}
    assert all('RECORD_CASE_CONFLICT' in reasons for reasons in result['holds'].values())
    assert all(not case['releasable'] for case in run(data)['cases'])


def test_unattributed_bad_row_holds_whole_batch():
    data = csv_data([*application('0001'), *application('0002'), row('ERR1', '9999', credits='N/A')])
    report = run(data)
    assert report['intake']['global_hold'] == {'MISSING_NUMBER': 1}
    assert report['balance']['blocked'] and not report['balance']['releasable']
    assert all(not case['releasable'] for case in report['cases'])


def test_bad_row_inside_application_holds_only_that_application():
    data = csv_data([*application('0001'), *application('0002'),
                     row('000203', '0002', 'required', '0', '2', credits='N/A')])
    result = inspect(data)
    assert result['holds'] == {'0002': ['MISSING_NUMBER']} and not result['global_hold']
    report = run(data)
    cases = {case['case']: case for case in report['cases']}
    assert cases['0001']['releasable'] is True
    assert cases['0002']['releasable'] is False and cases['0002']['holds'] == ['MISSING_NUMBER']
    assert report['balance']['partial'] is True


def test_duplicate_conflict_between_versions_holds_its_application():
    data = csv_data([*application('0001'), row('000101', '0001', credits='4')])
    result = inspect(data)
    assert result['holds'] == {'0001': ['DUPLICATE_CONFLICT']}
    assert result['rejected'] == 2


def test_replayed_copy_does_not_hold_application(clean):
    rows = list(csv.reader(io.StringIO(clean.decode('utf-8-sig'), newline='')))
    stream = io.StringIO(newline='')
    csv.writer(stream).writerows([rows[0], *rows[1:], rows[1]])
    report = run(stream.getvalue().encode())
    assert report['intake']['holds'] == {} and report['balance']['releasable'] is True


def test_dirty_sample_blocks_batch_on_unattributed_rows(dirty):
    report = run(dirty)
    assert report['intake']['global_hold'] and report['balance']['blocked']
    assert report['balance']['signable'] == 0


# --- 逐申请签发 -------------------------------------------------------------

def test_partial_application_can_be_signed_first(store, clean):
    run_id = execute(store, clean)['id']
    first = review(store, run_id, dict(revision=0, status='HELD', note='先签一份申请', cases={'0001': 'APPROVED'}))
    assert first['decisions'] == {'0001': 'APPROVED'} and first['status'] == 'HELD'
    second = review(store, run_id, dict(revision=1, status='HELD', note='再签第二份', cases={'0002': 'APPROVED'}))
    assert second['status'] == 'APPROVED'
    assert second['decisions'] == {'0001': 'APPROVED', '0002': 'APPROVED'}


def test_approved_application_cannot_be_resigned(store, clean):
    run_id = execute(store, clean)['id']
    review(store, run_id, dict(revision=0, status='HELD', note='先签一份申请', cases={'0001': 'APPROVED'}))
    with pytest.raises(DomainIssue, match='RUN_FINALIZED'):
        review(store, run_id, dict(revision=1, status='HELD', note='重复签发', cases={'0001': 'APPROVED'}))


def test_held_application_cannot_be_signed(store, dirty):
    run_id = execute(store, dirty)['id']
    with pytest.raises(DomainIssue, match='UNRESOLVED_ISSUES'):
        review(store, run_id, dict(revision=0, status='HELD', note='坏行无归属', cases={'0001': 'APPROVED'}))


def test_batch_hold_keeps_earlier_application_approval(store, clean):
    run_id = execute(store, clean)['id']
    review(store, run_id, dict(revision=0, status='HELD', note='先签一份申请', cases={'0001': 'APPROVED'}))
    out = review(store, run_id, dict(revision=1, status='HELD', note='整批暂缓'))
    assert out['status'] == 'HELD'
    assert out['decisions'] == {'0001': 'APPROVED', '0002': 'HELD'}


def test_batch_approval_does_not_reopen_signed_application(store, clean):
    run_id = execute(store, clean)['id']
    review(store, run_id, dict(revision=0, status='HELD', note='先签一份申请', cases={'0001': 'APPROVED'}))
    out = review(store, run_id, dict(revision=1, status='APPROVED', note='整批签发'))
    assert out['status'] == 'APPROVED' and out['revision'] == 2


# --- 材料更正与签发 ---------------------------------------------------------

def test_corrected_material_refuses_stale_checkout(store, clean):
    older = execute(store, clean)
    newer = execute(store, corrected(clean))
    assert older['report']['materials']['0002'] != newer['report']['materials']['0002']
    assert older['report']['materials']['0001'] == newer['report']['materials']['0001']
    with pytest.raises(DomainIssue, match='STALE_MATERIAL'):
        review(store, older['id'], dict(revision=0, status='HELD', note='按旧材料签发', cases={'0002': 'APPROVED'}))
    signed = review(store, older['id'], dict(revision=0, status='HELD', note='0001 材料未变', cases={'0001': 'APPROVED'}))
    assert signed['decisions'] == {'0001': 'APPROVED'}
    assert review(store, newer['id'], dict(revision=0, status='HELD', note='按新版材料', cases={'0002': 'APPROVED'}))['decisions'] == {'0002': 'APPROVED'}


def test_corrected_material_to_unusable_still_supersedes(store, clean):
    older = execute(store, clean)
    newer = execute(store, edit(clean, '000206', lambda row: [*row[:5], 'N/A', *row[6:]]))
    assert '0002' in newer['report']['materials']
    with pytest.raises(DomainIssue, match='STALE_MATERIAL'):
        review(store, older['id'], dict(revision=0, status='HELD', note='按旧材料签发', cases={'0002': 'APPROVED'}))


def test_simultaneous_correction_and_signing_never_cross(store, clean):
    older = execute(store, clean)
    start = Barrier(2)

    def sign():
        start.wait(3)
        try:
            review(store, older['id'], dict(revision=0, status='HELD', note='并发签发', cases={'0002': 'APPROVED'}))
        except DomainIssue as error:
            return error.code
        return 'APPROVED'

    def correct():
        start.wait(3)
        return execute(store, corrected(clean))['id']

    with ThreadPoolExecutor(max_workers=2) as threads:
        signing = threads.submit(sign)
        threads.submit(correct)
        outcome = signing.result()
    current = store.load(older['id'])['decisions'].get('0002')
    if outcome == 'APPROVED':
        # 签发先拿到写锁时，更正材料尚未生效，签发只发生一次。
        assert current == 'APPROVED'
    else:
        assert outcome == 'STALE_MATERIAL' and current is None


# --- 证据与接口 -------------------------------------------------------------

def test_evidence_records_application_decisions(store, clean):
    run_id = execute(store, clean)['id']
    revised = review(store, run_id, dict(revision=0, status='HELD', note='逐份复核', cases={'0001': 'APPROVED'}))
    assert json.loads(artifact(revised))['review']['decisions'] == {'0001': 'APPROVED'}


def test_http_partial_application_signing(client):
    run = client.post('/api/runs', data={'sample': 'clean'}).json
    first = client.patch(f"/api/runs/{run['id']}", json=dict(
        revision=0, status='HELD', note='先签一份申请', cases={'0001': 'APPROVED'}))
    assert first.status_code == 200
    assert first.json['status'] == 'HELD' and first.json['decisions'] == {'0001': 'APPROVED'}
    second = client.patch(f"/api/runs/{run['id']}", json=dict(
        revision=1, status='HELD', note='再签第二份', cases={'0002': 'APPROVED'}))
    assert second.status_code == 200 and second.json['status'] == 'APPROVED'


def test_http_stale_material_conflict(client, clean):
    run = client.post('/api/runs', data={'sample': 'clean'}).json
    client.post('/api/runs', data={'file': (io.BytesIO(corrected(clean)), 'fixed.csv')})
    result = client.patch(f"/api/runs/{run['id']}", json=dict(
        revision=0, status='HELD', note='按旧材料签发', cases={'0002': 'APPROVED'}))
    assert result.status_code == 409 and result.json['code'] == 'STALE_MATERIAL'


def test_http_rejects_unknown_application(client):
    run = client.post('/api/runs', data={'sample': 'clean'}).json
    result = client.patch(f"/api/runs/{run['id']}", json=dict(
        revision=0, status='HELD', note='未知申请', cases={'9999': 'APPROVED'}))
    assert result.status_code == 422 and result.json['code'] == 'REVIEW_FIELDS'


def test_batch_approval_requires_every_application(client):
    data = csv_data([*application('0001'), *application('0002'),
                     row('000205', '0002', 'equivalence', '2', '1', credits='N/A')])
    run = client.post('/api/runs', data={'file': (io.BytesIO(data), 'partial.csv')}).json
    assert run['report']['balance']['partial'] is True
    refused = client.patch(f"/api/runs/{run['id']}", json=dict(
        revision=0, status='APPROVED', note='整批签发尝试'))
    assert refused.status_code == 409 and refused.json['code'] == 'UNRESOLVED_ISSUES'
    signed = client.patch(f"/api/runs/{run['id']}", json=dict(
        revision=0, status='HELD', note='先签第一份申请', cases={'0001': 'APPROVED'}))
    assert signed.status_code == 200 and signed.json['status'] == 'HELD'
