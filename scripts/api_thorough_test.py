import time, json, requests
from urllib.parse import quote

BASE = 'http://localhost:5000'
TIMEOUT = 30

results = []

def check(name, func):
    try:
        start = time.time()
        out = func()
        dur = int((time.time()-start)*1000)
        results.append({'name': name, 'ok': True, 'ms': dur, 'detail': out})
    except Exception as e:
        results.append({'name': name, 'ok': False, 'ms': None, 'detail': str(e)})


def jget(path, params=None):
    r = requests.get(BASE+path, params=params, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f'HTTP {r.status_code}: {r.text[:200]}')
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f'Non-JSON response: {r.text[:200]}')


def jpost(path, payload=None, params=None):
    r = requests.post(BASE+path, json=payload, params=params, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f'HTTP {r.status_code}: {r.text[:200]}')
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f'Non-JSON response: {r.text[:200]}')


def jput(path, payload=None):
    r = requests.put(BASE+path, json=payload, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f'HTTP {r.status_code}: {r.text[:200]}')
    return r.json()


def jdelete(path):
    r = requests.delete(BASE+path, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f'HTTP {r.status_code}: {r.text[:200]}')
    return r.json()


def main():
    # Dashboard
    check('GET /api/dashboard', lambda: jget('/api/dashboard').get('data', {}).keys())

    # Config + Ollama
    check('GET /api/config', lambda: list(jget('/api/config').get('data', {}).keys())[:5])
    check('GET /api/ollama-status', lambda: jget('/api/ollama-status').get('data', {}))
    check('GET /api/ollama-models', lambda: jget('/api/ollama-models').get('data', {}).get('models', [])[:2])

    # Projects CRUD + analytics + results
    def project_flow():
        created = jpost('/api/projects', {'name':'API Test Project', 'url':'https://example.com', 'platform':'web'}).get('data', {})
        pid = created.get('id') or created.get('_id')
        if not pid:
            raise RuntimeError('Project id missing')

        # get
        p = jget('/api/projects/'+quote(pid)).get('data', {})
        # update
        up = jput('/api/projects/'+quote(pid), {'name':'API Test Project v2', 'url':'https://example.com'}).get('data', {})
        # analytics
        dash = jget('/api/projects/'+quote(pid)+'/dashboard').get('data', {})
        ana = jget('/api/projects/'+quote(pid)+'/analytics').get('data', {})
        # results list
        ress = jget('/api/projects/'+quote(pid)+'/results', params=None).get('data', [])
        # cleanup
        jdelete('/api/projects/'+quote(pid))
        return {'pid': pid, 'dashboardKeys': list(dash.keys()), 'analyticsKeys': list(ana.keys()), 'resultsCount': len(ress)}

    check('Projects CRUD + dashboard/analytics/results', project_flow)

    # Test cases CRUD
    def test_case_flow():
        # create project
        created = jpost('/api/projects', {'name':'Test Case Project', 'url':'https://example.com', 'platform':'web'}).get('data', {})
        pid = created.get('id') or created.get('_id')

        # create a new test case via API
        tc = jpost('/api/projects/'+quote(pid)+'/test-cases', {
            'name': 'API Seeded Test',
            'category': 'regression',
            'steps': [
                {'action': 'navigate', 'description': 'Home', 'target': 'https://example.com', 'seq': 1, 'timestamp': 1, 'value': None, 'verify': 'Homepage loads'}
            ]
        }).get('data', {})
        tcid = tc.get('id') or tc.get('_id')

        tcs = jget('/api/projects/'+quote(pid)+'/test-cases').get('data', [])
        if not tcs:
            raise RuntimeError('No test cases after creation')

        # get tc
        jget('/api/test-cases/'+quote(tcid))

        # update tc steps
        steps = tc.get('steps', [])
        if not isinstance(steps, list):
            steps = []
        steps2 = steps[:1] if steps else [{'action': 'navigate', 'target': 'https://example.com', 'description': 'x', 'seq': 1, 'timestamp': 1, 'value': None, 'verify': ''}]
        jput('/api/test-cases/'+quote(tcid), {'steps': steps2, 'name': 'API Updated TC'})

        # delete tc
        jdelete('/api/test-cases/'+quote(tcid))

        # delete project
        jdelete('/api/projects/'+quote(pid))
        return {'tcCount': len(tcs)}

    check('Test cases CRUD', test_case_flow)

    # Test plans CRUD
    def plan_flow():
        payload = {'filename':'api_test_plan.md','content':'### TC-01: Open Example\n1. navigate | Open | https://example.com |  | HTTP 200'}
        saved = jpost('/api/test-plans', payload).get('data', {})
        fn = saved.get('filename')
        listing = jget('/api/test-plans').get('data', [])
        _ = jget('/api/test-plans/'+quote(fn)).get('data', {}).get('content', '')
        jdelete('/api/test-plans/'+quote(fn))
        return {'saved': fn, 'plansCount': len(listing)}

    check('Test plans CRUD', plan_flow)

    # Runs + streaming (smoke)
    def run_flow():
        # create project + a minimal test case
        created = jpost('/api/projects', {'name':'Run Test Project', 'url':'https://example.com', 'platform':'web'}).get('data', {})
        pid = created.get('id') or created.get('_id')
        tc = jpost('/api/projects/'+quote(pid)+'/test-cases', {
            'name':'Run Flow TC',
            'category':'positive',
            'steps': [
                {'action':'navigate','description':'Home','target':'https://example.com','seq':1,'timestamp':1,'value':None,'verify':'Page loads'}
            ],
        }).get('data', {})
        tcid = tc.get('id') or tc.get('_id')

        # run test case
        run = jpost('/api/run/'+quote(tcid), {'mode':'standard'}).get('data', {})
        rid = run.get('runId')
        if not rid:
            raise RuntimeError('runId missing')

        # SSE stream smoke: read first few events
        # Note: Playwright may take time; we read stream but stop once 'complete' observed.
        url = BASE+'/api/run/stream/'+quote(rid)
        events = []
        with requests.get(url, stream=True, timeout=TIMEOUT, headers={'Accept':'text/event-stream'}) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f'SSE HTTP {resp.status_code}: {resp.text[:200]}')
            start = time.time()
            buf = ''
            event = None
            for line in resp.iter_lines(decode_unicode=False):
                if time.time()-start > 300:
                    break
                if not line:
                    if event and buf:
                        events.append((event, buf))
                    event = None
                    buf = ''
                    continue
                if line.startswith('event:'):
                    event = line.split(':',1)[1].strip()
                elif line.startswith('data:'):
                    buf += line.split(':',1)[1].strip()
                if event == 'complete':
                    break

        st = jget('/api/run/status/'+quote(rid)).get('data', {})

        # cancel should be safe after completion; test anyway
        jpost('/api/run/cancel/'+quote(rid), None)

        # cleanup
        jdelete('/api/projects/'+quote(pid))

        return {'runId': rid, 'sseEvents': [e[0] for e in events][:5], 'finalStatus': st.get('status')}

    check('Runs + SSE stream smoke + status/cancel', run_flow)

    # Print report
    ok_count = sum(1 for r in results if r['ok'])
    fail_count = len(results)-ok_count
    print('\n===== THOROUGH API TEST REPORT =====')
    for r in results:
        status_icon = "[PASS]" if r['ok'] else "[FAIL]"
        print(f"{status_icon} {r['name']} ({r.get('ms', 0)} ms) -> {r['detail']}")
    print(f"\nTOTAL: {len(results)} | PASSED: {ok_count} | FAILED: {fail_count}")


if __name__ == '__main__':
    main()

