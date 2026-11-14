"""Read-only capture of laboratory 1 evidence through the public Gateway."""
import json
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OUT = Path(__file__).resolve().parents[2] / 'docs/lab1'
OUT.mkdir(parents=True, exist_ok=True)
BASE = 'http://localhost:8000'
trace = []
token = ''


def get(path, params=(), auth=True):
    url = BASE + path + ('?' + urlencode(params, doseq=True) if params else '')
    request = Request(url, headers={'Authorization': 'Bearer ' + token} if auth else {})
    try:
        with urlopen(request, timeout=60) as response:
            status, body = response.status, json.load(response)
    except HTTPError as error:
        status, body = error.code, json.load(error)
    trace.append({'method': 'GET', 'url': url, 'authenticated': auth, 'status': status, 'response': body})
    return status, body


def pages(path, params):
    result = []
    while True:
        status, body = get(path, [*params, ('limit', 100), ('offset', len(result))])
        assert status == 200, body
        result.extend(body['items'])
        if len(result) == body['total']:
            return result
        assert body['items']


request = Request(BASE + '/api/v1/auth/token', data=json.dumps({'username': 'api-user', 'password': 'api-password'}).encode(), headers={'Content-Type': 'application/json'})
with urlopen(request) as response:
    credentials = json.load(response)
    token = credentials['access_token']
    trace.append({'method': 'POST', 'url': BASE + '/api/v1/auth/token', 'status': response.status, 'response': {**credentials, 'access_token': '<скрыт>'}})
query = [('term', 'нормализация'), ('search_mode', 'words'), ('date_from', '2026-09-01'), ('date_to', '2026-10-31')]
assert get('/api/v1/reports/lowest-attendance', query, False)[0] == 401
ids = set()
cursor = None
while True:
    params = [('q', 'нормализация'), ('search_mode', 'words'), ('limit', 100)]
    if cursor:
        params.append(('cursor', cursor))
    status, body = get('/api/v1/academic/search/lectures', params)
    assert status == 200
    ids.update(body['items'])
    cursor = body['next_cursor']
    if cursor is None:
        break
lectures = pages('/api/v1/academic/lectures', [('ids', x) for x in sorted(ids)] + [('lecture_type', 'lecture')])
schedules = pages('/api/v1/schedule', [('lecture_ids', x['id']) for x in lectures] + [('status', 'completed'), ('date_from', '2026-09-01'), ('date_to', '2026-10-31')])
assert schedules, 'No suitable lessons'
groups = pages('/api/v1/students/groups', [('group_ids', x) for x in sorted({s['group_id'] for s in schedules})])
students = pages('/api/v1/students/students', [('group_ids', g['id']) for g in groups])
attendance = []
for start in range(0, len(schedules), 100):
    attendance.extend(pages('/api/v1/attendance', [('schedule_ids', s['id']) for s in schedules[start:start+100]] + [('week_from', '2026-08-31'), ('week_to', '2026-10-26')]))
present = {(a['student_id'], a['schedule_id']) for a in attendance if a['is_present']}
ranked = []
for student in students:
    lessons = [s for s in schedules if s['group_id'] == student['group_id'] and s['scheduled_date'] >= student['enrollment_date']]
    if lessons:
        count = sum((student['id'], s['id']) in present for s in lessons)
        ranked.append((Fraction(count, len(lessons)), student['id'], count, len(lessons), student))
ranked.sort(key=lambda r: (r[0], r[1]))
status, report = get('/api/v1/reports/lowest-attendance', query)
assert status == 200
expected = [(r[1], r[2], r[3], round(float(100*r[0]), 2)) for r in ranked[:10]]
actual = [(r['student']['id'], r['attended_count'], r['lecture_count'], r['attendance_percent']) for r in report['items']]
assert actual == expected, (actual, expected)
assert get('/api/v1/reports/lowest-attendance', [(k, 'несуществующийтерминлабораторная' if k == 'term' else v) for k, v in query])[1]['items'] == []
assert get('/api/v1/reports/lowest-attendance', [('term', 'нормализация'), ('date_from', '2026-11-01'), ('date_to', '2026-09-01')])[0] == 422
get('/api/v1/reports/lowest-attendance', [(k, 'phrase' if k == 'search_mode' else v) for k, v in query])
evidence = {'captured_at': datetime.now(UTC).isoformat(), 'counts': {'search_lecture_ids': len(ids), 'lectures': len(lectures), 'schedules': len(schedules), 'groups': len(groups), 'students': len(students), 'attendance': len(attendance), 'ranked': len(ranked)}, 'expected_top10': expected, 'report': report, 'requests': trace}
(OUT / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(evidence['counts'], ensure_ascii=False))
print('Independent calculation matches report; evidence saved.')
