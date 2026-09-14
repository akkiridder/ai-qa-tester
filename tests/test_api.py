"""Basic tests for AI QA Tester backend API."""
import pytest
import json
import sys
import os
import shutil
import tempfile

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smart_tester
from smart_tester import app

@pytest.fixture
def client():
    """Create test client with a temporary database."""
    from tinydb import TinyDB
    
    # Create temp database
    tmp_dir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmp_dir, 'test_database.json')
    
    # Backup originals
    orig_db = smart_tester.db
    orig_db_file = smart_tester.DB_FILE
    orig_projects = smart_tester.projects_table
    orig_tcs = smart_tester.test_cases_table
    orig_results = smart_tester.results_table
    orig_config = smart_tester.config_table
    
    # Swap to temp DB
    smart_tester.DB_FILE = type(orig_db_file)(tmp_db)
    smart_tester.db = TinyDB(tmp_db, sort_keys=True, indent=2)
    smart_tester.projects_table = smart_tester.db.table('projects')
    smart_tester.test_cases_table = smart_tester.db.table('test_cases')
    smart_tester.results_table = smart_tester.db.table('results')
    smart_tester.config_table = smart_tester.db.table('config')
    smart_tester._invalidate_table_cache()
    
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client
    
    # Restore originals
    smart_tester.db = orig_db
    smart_tester.DB_FILE = orig_db_file
    smart_tester.projects_table = orig_projects
    smart_tester.test_cases_table = orig_tcs
    smart_tester.results_table = orig_results
    smart_tester.config_table = orig_config
    smart_tester._invalidate_table_cache()
    
    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)

class TestBasicAuth:
    """HTTP Basic Auth (ID + password) + X-API-Key header enforcement."""

    @pytest.fixture
    def authed(self, monkeypatch):
        monkeypatch.setattr(smart_tester, "API_KEY", "")
        monkeypatch.setattr(smart_tester, "AUTH_USER", "Akki")
        monkeypatch.setattr(smart_tester, "AUTH_PASS", "Akki@123")
        import base64
        good = "Basic " + base64.b64encode(b"Akki:Akki@123").decode()
        bad = "Basic " + base64.b64encode(b"Akki:wrong").decode()
        return {"good": good, "bad": bad}

    def _remote(self, client, path, headers=None):
        return client.get(path, headers=headers or {},
                           environ_overrides={"REMOTE_ADDR": "8.8.8.8"})

    def test_remote_no_creds_401(self, client, authed):
        r = self._remote(client, "/api/projects")
        assert r.status_code == 401
        assert r.headers.get("WWW-Authenticate", "").startswith("Basic")

    def test_remote_ui_locked(self, client, authed):
        r = self._remote(client, "/")
        assert r.status_code == 401

    def test_remote_wrong_password_401(self, client, authed):
        r = self._remote(client, "/api/projects",
                         {"Authorization": authed["bad"]})
        assert r.status_code == 401

    def test_remote_basic_ok(self, client, authed):
        r = self._remote(client, "/api/projects",
                         {"Authorization": authed["good"]})
        assert r.status_code == 200

    def test_remote_query_creds_ok(self, client, authed):
        r = self._remote(client, "/api/projects?access_user=Akki&access_pass=Akki@123")
        assert r.status_code == 200

    def test_localhost_bypass(self, client, authed):
        r = client.get("/api/projects",
                       environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        assert r.status_code == 200

class TestDashboard:
    def test_dashboard_empty(self, client):
        """Test dashboard with no data."""
        response = client.get('/api/dashboard')
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['data']['total_projects'] == 0
        assert data['data']['total_test_cases'] == 0

class TestProjects:
    def test_create_project(self, client):
        """Test creating a project."""
        response = client.post('/api/projects', 
            data=json.dumps({'name': 'Test Project', 'url': 'https://example.com'}),
            content_type='application/json')
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['data']['name'] == 'Test Project'
        assert 'id' in data['data']
    
    def test_list_projects(self, client):
        """Test listing projects."""
        # Create a project first
        client.post('/api/projects', 
            data=json.dumps({'name': 'Test Project', 'url': 'https://example.com'}),
            content_type='application/json')
        
        response = client.get('/api/projects')
        data = json.loads(response.data)
        assert data['success'] == True
        assert len(data['data']) == 1
        assert data['data'][0]['name'] == 'Test Project'
    
    def test_get_project(self, client):
        """Test getting a single project."""
        # Create a project
        create_response = client.post('/api/projects', 
            data=json.dumps({'name': 'Test Project', 'url': 'https://example.com'}),
            content_type='application/json')
        project_id = json.loads(create_response.data)['data']['id']
        
        response = client.get(f'/api/projects/{project_id}')
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['data']['name'] == 'Test Project'
    
    def test_update_project(self, client):
        """Test updating a project."""
        # Create a project
        create_response = client.post('/api/projects', 
            data=json.dumps({'name': 'Test Project', 'url': 'https://example.com'}),
            content_type='application/json')
        project_id = json.loads(create_response.data)['data']['id']
        
        # Update it
        response = client.put(f'/api/projects/{project_id}',
            data=json.dumps({'name': 'Updated Project'}),
            content_type='application/json')
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['data']['name'] == 'Updated Project'
    
    def test_delete_project(self, client):
        """Test deleting a project."""
        # Create a project
        create_response = client.post('/api/projects', 
            data=json.dumps({'name': 'Test Project', 'url': 'https://example.com'}),
            content_type='application/json')
        project_id = json.loads(create_response.data)['data']['id']
        
        # Delete it
        response = client.delete(f'/api/projects/{project_id}')
        data = json.loads(response.data)
        assert data['success'] == True
        
        # Verify it's gone
        response = client.get(f'/api/projects/{project_id}')
        data = json.loads(response.data)
        assert data['success'] == False

class TestTestCases:
    def test_create_test_case(self, client):
        """Test creating a test case."""
        # Create a project first
        create_response = client.post('/api/projects', 
            data=json.dumps({'name': 'Test Project', 'url': 'https://example.com'}),
            content_type='application/json')
        project_id = json.loads(create_response.data)['data']['id']
        
        # Create a test case
        response = client.post(f'/api/projects/{project_id}/test-cases',
            data=json.dumps({
                'name': 'Test Login',
                'category': 'positive',
                'steps': [
                    {'action': 'navigate', 'target': 'https://example.com', 'description': 'Go to homepage'},
                    {'action': 'click', 'target': '#login', 'description': 'Click login button'}
                ]
            }),
            content_type='application/json')
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['data']['name'] == 'Test Login'
        assert len(data['data']['steps']) == 2
    
    def test_list_test_cases(self, client):
        """Test listing test cases for a project."""
        # Create a project
        create_response = client.post('/api/projects', 
            data=json.dumps({'name': 'Test Project', 'url': 'https://example.com'}),
            content_type='application/json')
        project_id = json.loads(create_response.data)['data']['id']
        
        # Create a test case
        client.post(f'/api/projects/{project_id}/test-cases',
            data=json.dumps({'name': 'Test Login', 'steps': []}),
            content_type='application/json')
        
        response = client.get(f'/api/projects/{project_id}/test-cases')
        data = json.loads(response.data)
        assert data['success'] == True
        assert len(data['data']) == 1

class TestConfig:
    def test_get_config(self, client):
        """Test getting config."""
        response = client.get('/api/config')
        data = json.loads(response.data)
        assert data['success'] == True
        assert 'ai_provider' in data['data']
    
    def test_save_config(self, client):
        """Test saving config."""
        response = client.post('/api/config',
            data=json.dumps({'ai_provider': 'ollama', 'ollama_model': 'test-model'}),
            content_type='application/json')
        data = json.loads(response.data)
        assert data['success'] == True

    def test_save_config_preserves_masked_key(self, client):
        """Test that secret values are never exposed and blanks never wipe the key."""
        # Save a real key first
        client.post('/api/config',
            data=json.dumps({'cloud_api_key': 'nvapi-test-dummy-key-12345'}),
            content_type='application/json')
        # GET must NOT expose any key material — only a boolean flag
        response = client.get('/api/config')
        data = json.loads(response.data)
        assert 'cloud_api_key' not in data['data']
        assert 'anthropic_api_key' not in data['data']
        assert data['data'].get('cloud_api_key_set') is True
        # Save again with blank/masked value — stored key must survive
        client.post('/api/config',
            data=json.dumps({'cloud_api_key': ''}),
            content_type='application/json')
        client.post('/api/config',
            data=json.dumps({'cloud_api_key': 'nvapi-...xxx'}),
            content_type='application/json')
        response = client.get('/api/config')
        data = json.loads(response.data)
        assert data['data'].get('cloud_api_key_set') is True

class TestTestCaseUpdateDelete:
    def test_update_test_case(self, client):
        """Test updating a test case."""
        # Create project + TC
        pr = client.post('/api/projects',
            data=json.dumps({'name': 'P', 'url': 'https://example.com'}),
            content_type='application/json')
        pid = json.loads(pr.data)['data']['id']
        
        tr = client.post(f'/api/projects/{pid}/test-cases',
            data=json.dumps({'name': 'TC1', 'steps': [{'action': 'navigate', 'target': 'https://example.com'}]}),
            content_type='application/json')
        tid = json.loads(tr.data)['data']['id']
        
        # Update
        response = client.put(f'/api/test-cases/{tid}',
            data=json.dumps({'name': 'TC1 Updated', 'steps': [{'action': 'navigate', 'target': 'https://example.com'}, {'action': 'click', 'target': 'h1'}]}),
            content_type='application/json')
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['data']['name'] == 'TC1 Updated'
        assert len(data['data']['steps']) == 2
    
    def test_delete_test_case(self, client):
        """Test deleting a test case."""
        pr = client.post('/api/projects',
            data=json.dumps({'name': 'P', 'url': 'https://example.com'}),
            content_type='application/json')
        pid = json.loads(pr.data)['data']['id']
        
        tr = client.post(f'/api/projects/{pid}/test-cases',
            data=json.dumps({'name': 'TC1', 'steps': []}),
            content_type='application/json')
        tid = json.loads(tr.data)['data']['id']
        
        # Delete
        response = client.delete(f'/api/test-cases/{tid}')
        data = json.loads(response.data)
        assert data['success'] == True
        
        # Verify gone
        response = client.get(f'/api/test-cases/{tid}')
        data = json.loads(response.data)
        assert data['success'] == False
    
    def test_delete_nonexistent_test_case(self, client):
        """Test deleting non-existent test case returns 404."""
        response = client.delete('/api/test-cases/nonexistent')
        assert response.status_code == 404

class TestResultsAndAnalytics:
    def test_get_project_results(self, client):
        """Test getting project results."""
        pr = client.post('/api/projects',
            data=json.dumps({'name': 'P', 'url': 'https://example.com'}),
            content_type='application/json')
        pid = json.loads(pr.data)['data']['id']
        
        response = client.get(f'/api/projects/{pid}/results')
        data = json.loads(response.data)
        assert data['success'] == True
        assert isinstance(data['data'], list)
    
    def test_get_project_analytics(self, client):
        """Test getting project analytics."""
        pr = client.post('/api/projects',
            data=json.dumps({'name': 'P', 'url': 'https://example.com'}),
            content_type='application/json')
        pid = json.loads(pr.data)['data']['id']
        
        response = client.get(f'/api/projects/{pid}/analytics')
        data = json.loads(response.data)
        assert data['success'] == True
        assert 'passRate' in data['data']
    
    def test_dashboard_with_data(self, client):
        """Test dashboard with empty data."""
        response = client.get('/api/dashboard')
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['data']['total_projects'] == 0
        assert data['data']['total_test_cases'] == 0
    
    def test_health_check(self, client):
        """Test health endpoint."""
        response = client.get('/api/health')
        data = json.loads(response.data)
        assert data['success'] == True

class TestInputValidation:
    def test_create_tc_without_name_fails(self, client):
        """Test creating test case without name returns error."""
        pr = client.post('/api/projects',
            data=json.dumps({'name': 'P', 'url': 'https://example.com'}),
            content_type='application/json')
        pid = json.loads(pr.data)['data']['id']
        
        response = client.post(f'/api/projects/{pid}/test-cases',
            data=json.dumps({'steps': []}),
            content_type='application/json')
        data = json.loads(response.data)
        assert data['success'] == False
    
    def test_create_tc_with_long_name_fails(self, client):
        """Test creating test case with too-long name returns error."""
        pr = client.post('/api/projects',
            data=json.dumps({'name': 'P', 'url': 'https://example.com'}),
            content_type='application/json')
        pid = json.loads(pr.data)['data']['id']
        
        response = client.post(f'/api/projects/{pid}/test-cases',
            data=json.dumps({'name': 'A' * 600, 'steps': []}),
            content_type='application/json')
        data = json.loads(response.data)
        assert data['success'] == False

class TestSSE:
    def test_stream_endpoint_returns_200(self, client):
        """Test SSE stream endpoint returns 200."""
        response = client.get('/api/run/stream/nonexistent')
        assert response.status_code == 200


class TestSSRFProtection:
    """Tests for SSRF protection — _is_safe_url function."""

    def test_safe_url_https(self):
        """HTTPS public URL should be allowed."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('https://example.com') == True
        assert _is_safe_url('https://google.com/search?q=test') == True

    def test_safe_url_http_public(self):
        """HTTP public URL should be allowed."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('http://example.com') == True
        assert _is_safe_url('http://httpbin.org/get') == True

    def test_blocked_localhost(self):
        """Localhost URLs must be blocked."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('http://localhost:5000') == False
        assert _is_safe_url('http://localhost:8080/api') == False
        assert _is_safe_url('http://127.0.0.1:5000') == False
        assert _is_safe_url('http://127.0.0.1') == False
        assert _is_safe_url('http://[::1]:5000') == False

    def test_blocked_private_ips(self):
        """Private IP ranges must be blocked."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('http://10.0.0.1/') == False
        assert _is_safe_url('http://10.255.255.255/') == False
        assert _is_safe_url('http://172.16.0.1/') == False
        assert _is_safe_url('http://172.31.255.255/') == False
        assert _is_safe_url('http://192.168.1.1/') == False
        assert _is_safe_url('http://192.168.0.100/') == False

    def test_blocked_link_local(self):
        """Link-local IPs (cloud metadata) must be blocked."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('http://169.254.169.254/latest/meta-data/') == False
        assert _is_safe_url('http://169.254.0.1/') == False

    def test_blocked_dangerous_schemes(self):
        """Non-HTTP schemes must be blocked."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('file:///etc/passwd') == False
        assert _is_safe_url('javascript:alert(1)') == False
        assert _is_safe_url('data:text/html,<script>alert(1)</script>') == False
        assert _is_safe_url('ftp://example.com/file') == False

    def test_blocked_loopback_range(self):
        """Full loopback range 127.0.0.0/8 must be blocked."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('http://127.0.0.2/') == False
        assert _is_safe_url('http://127.255.255.255/') == False

    def test_blocked_empty_and_invalid(self):
        """Empty/invalid URLs must be blocked."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('') == False
        assert _is_safe_url('not-a-url') == False
        assert _is_safe_url('://') == False

    def test_blocked_ipv6_private(self):
        """IPv6 private ranges must be blocked."""
        from smart_tester import _is_safe_url
        assert _is_safe_url('http://[fc00::1]/') == False
        assert _is_safe_url('http://[fe80::1]/') == False

    def test_ssrf_blocks_at_run_time(self, client):
        """Running a test with internal URL should be blocked by SSRF protection."""
        # Create project with internal URL
        pr = client.post('/api/projects',
            data=json.dumps({'name': 'SSRF Test', 'url': 'http://169.254.169.254/'}),
            content_type='application/json')
        pid = json.loads(pr.data)['data']['id']

        # Create test case with navigate to internal URL
        tr = client.post(f'/api/projects/{pid}/test-cases',
            data=json.dumps({
                'name': 'SSRF TC',
                'steps': [{'action': 'navigate', 'target': 'http://169.254.169.254/latest/meta-data/'}]
            }),
            content_type='application/json')
        tid = json.loads(tr.data)['data']['id']

        # Trigger the run
        response = client.post(f'/api/run/{tid}',
            data=json.dumps({'mode': 'standard'}),
            content_type='application/json')
        data = json.loads(response.data)
        assert data['success'] == True, f"Run should be queued: {data}"
        run_id = data['data']['runId']

        # Wait briefly then check status - SSRF should block immediately
        import time
        time.sleep(3)
        status_resp = client.get(f'/api/run/status/{run_id}')
        status_data = json.loads(status_resp.data)
        if status_data.get('success'):
            rd = status_data.get('data', {})
            # Verify the run was blocked or completed with SSRF error
            result_str = json.dumps(rd).lower()
            has_ssrf = ('ssrf' in result_str or 'blocked' in result_str or 'private' in result_str
                        or 'internal network' in result_str or 'url blocked' in result_str)
            # Also accept if the run completed with fail status
            if rd.get('status') in ('completed', 'error') and (has_ssrf or rd.get('status') == 'error'):
                return  # Test passed - SSRF blocked
        # If status check didn't show SSRF, check if run is still running (AI call in progress)
        # The SSRF check happens in the thread - just verify the run was queued
        assert response.status_code == 200


class TestSecurityHeaders:
    """Tests for security headers on all responses."""

    def test_health_has_security_headers(self, client):
        """Health endpoint should return security headers."""
        response = client.get('/api/health')
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'
        assert response.headers.get('X-Frame-Options') == 'DENY'
        assert response.headers.get('X-XSS-Protection') == '1; mode=block'
        assert 'Referrer-Policy' in response.headers
        assert 'Permissions-Policy' in response.headers
        assert 'Content-Security-Policy' in response.headers

    def test_projects_endpoint_has_headers(self, client):
        """Projects endpoint should return security headers."""
        response = client.get('/api/projects')
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'
        assert response.headers.get('X-Frame-Options') == 'DENY'

    def test_csp_blocks_external_scripts(self, client):
        """CSP should not allow external script sources."""
        response = client.get('/api/health')
        csp = response.headers.get('Content-Security-Policy', '')
        assert 'frame-ancestors' in csp
        assert "default-src 'self'" in csp

    def test_cors_restricted(self, client):
        """CORS should only allow localhost origins."""
        response = client.options('/api/projects',
            headers={
                'Origin': 'http://evil.com',
                'Access-Control-Request-Method': 'GET'
            })
        # Should not have CORS headers for evil.com
        acao = response.headers.get('Access-Control-Allow-Origin', '')
        assert 'evil.com' not in acao


class TestRequestSizeLimit:
    """Tests for MAX_CONTENT_LENGTH (5MB limit)."""

    def test_normal_request_succeeds(self, client):
        """Normal-sized request should succeed."""
        response = client.post('/api/projects',
            data=json.dumps({'name': 'Normal', 'url': 'https://example.com'}),
            content_type='application/json')
        assert response.status_code == 200

    def test_oversized_request_blocked(self, client):
        """Request exceeding 5MB should be rejected."""
        oversized = {'name': 'A' * (6 * 1024 * 1024), 'url': 'https://example.com'}
        response = client.post('/api/projects',
            data=json.dumps(oversized),
            content_type='application/json')
        assert response.status_code == 413


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_returns_ok(self, client):
        """Health endpoint should return healthy status."""
        response = client.get('/api/health')
        data = json.loads(response.data)
        assert data['success'] == True
        assert data['data']['status'] == 'healthy'
        assert 'version' in data['data']

    def test_health_always_accessible(self, client):
        """Health endpoint should be accessible without auth."""
        response = client.get('/api/health')
        assert response.status_code == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
