#!/usr/bin/env python3
"""
Jenkins Dashboard Server
Run this to start a local web dashboard for Jenkins operations.

Usage:
    python3 dashboard.py
    
Then open http://localhost:5555 in your browser.
"""

import http.server
import json
import subprocess
import urllib.parse
import os
import re
from pathlib import Path

PORT = 5555
SCRIPT_DIR = Path(__file__).parent
JENKINS_SCRIPT = SCRIPT_DIR / "jenkins.sh"

# Load Jenkins config
JENKINS_CONFIG = {}
config_file = Path.home() / ".jenkins-config"
if config_file.exists():
    with open(config_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                JENKINS_CONFIG[key.strip()] = value.strip().strip('"\'')


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Quieter logging
        pass
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def send_html(self, html):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())
    
    def run_jenkins_cmd(self, *args):
        """Run jenkins.sh command and return output"""
        try:
            result = subprocess.run(
                [str(JENKINS_SCRIPT)] + list(args),
                capture_output=True,
                text=True,
                timeout=120
            )
            # Strip ANSI color codes for clean output
            output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout + result.stderr)
            return {"success": True, "output": output, "exit_code": result.returncode}
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "Command timed out", "exit_code": -1}
        except Exception as e:
            return {"success": False, "output": str(e), "exit_code": -1}
    
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        
        if path == '/' or path == '/index.html':
            self.send_html(DASHBOARD_HTML)
        
        elif path == '/api/config':
            self.send_json({
                "jenkins_url": JENKINS_CONFIG.get('JENKINS_URL', ''),
                "user": JENKINS_CONFIG.get('JENKINS_USER', '')
            })
        
        elif path == '/api/jobs':
            result = self.run_jenkins_cmd('jobs')
            self.send_json(result)
        
        elif path == '/api/search':
            pattern = query.get('pattern', [''])[0]
            if pattern:
                result = self.run_jenkins_cmd('search', pattern)
                self.send_json(result)
            else:
                self.send_json({"success": False, "output": "Missing pattern"}, 400)
        
        elif path == '/api/status':
            job = query.get('job', [''])[0]
            if job:
                result = self.run_jenkins_cmd('status', job)
                self.send_json(result)
            else:
                self.send_json({"success": False, "output": "Missing job name"}, 400)
        
        elif path == '/api/info':
            job = query.get('job', [''])[0]
            if job:
                result = self.run_jenkins_cmd('info', job)
                self.send_json(result)
            else:
                self.send_json({"success": False, "output": "Missing job name"}, 400)
        
        elif path == '/api/running':
            result = self.run_jenkins_cmd('running')
            self.send_json(result)
        
        elif path == '/api/queue':
            result = self.run_jenkins_cmd('queue')
            self.send_json(result)
        
        elif path == '/api/mybuilds':
            pattern = query.get('pattern', [''])[0]
            limit = query.get('limit', ['15'])[0]
            if pattern:
                result = self.run_jenkins_cmd('mybuilds', pattern, limit)
                self.send_json(result)
            else:
                self.send_json({"success": False, "output": "Missing pattern"}, 400)
        
        elif path == '/api/log':
            job = query.get('job', [''])[0]
            build = query.get('build', ['lastBuild'])[0]
            if job:
                result = self.run_jenkins_cmd('log', job, build)
                self.send_json(result)
            else:
                self.send_json({"success": False, "output": "Missing job name"}, 400)
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else '{}'
        
        try:
            data = json.loads(body) if body else {}
        except:
            data = {}
        
        if path == '/api/build':
            job = data.get('job', '')
            params = data.get('params', '')
            if job:
                args = ['build', job]
                if params:
                    args.extend(params.split())
                result = self.run_jenkins_cmd(*args)
                self.send_json(result)
            else:
                self.send_json({"success": False, "output": "Missing job name"}, 400)
        
        else:
            self.send_response(404)
            self.end_headers()


DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jenkins Dashboard</title>
    <style>
        :root {
            --bg-primary: #1a1a2e;
            --bg-secondary: #16213e;
            --bg-card: #0f3460;
            --accent: #e94560;
            --accent-hover: #ff6b6b;
            --text-primary: #eee;
            --text-secondary: #aaa;
            --success: #4ade80;
            --error: #f87171;
            --warning: #fbbf24;
            --building: #60a5fa;
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--bg-card);
        }
        
        h1 {
            font-size: 1.8rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .jenkins-link {
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 0.9rem;
        }
        
        .jenkins-link:hover {
            color: var(--accent);
        }
        
        .grid {
            display: grid;
            grid-template-columns: 350px 1fr;
            gap: 20px;
        }
        
        .sidebar {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        
        .card {
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 20px;
        }
        
        .card h2 {
            font-size: 1rem;
            color: var(--text-secondary);
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .search-box {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
        }
        
        input[type="text"] {
            flex: 1;
            padding: 10px 15px;
            border: none;
            border-radius: 8px;
            background: var(--bg-card);
            color: var(--text-primary);
            font-size: 0.95rem;
        }
        
        input[type="text"]::placeholder {
            color: var(--text-secondary);
        }
        
        input[type="text"]:focus {
            outline: 2px solid var(--accent);
        }
        
        button {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            background: var(--accent);
            color: white;
            font-size: 0.95rem;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        button:hover {
            background: var(--accent-hover);
        }
        
        button:disabled {
            background: var(--bg-card);
            cursor: not-allowed;
        }
        
        .btn-secondary {
            background: var(--bg-card);
        }
        
        .btn-secondary:hover {
            background: #1a4a7a;
        }
        
        .btn-small {
            padding: 6px 12px;
            font-size: 0.85rem;
        }
        
        .quick-actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        
        .quick-actions button {
            padding: 15px;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 5px;
        }
        
        .quick-actions .icon {
            font-size: 1.5rem;
        }
        
        .favorites {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .favorite-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 15px;
            background: var(--bg-card);
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.1s;
        }
        
        .favorite-item:hover {
            transform: translateX(5px);
        }
        
        .favorite-name {
            font-weight: 500;
        }
        
        .favorite-status {
            font-size: 0.85rem;
        }
        
        .status-success { color: var(--success); }
        .status-failure { color: var(--error); }
        .status-building { color: var(--building); }
        .status-unknown { color: var(--text-secondary); }
        
        .main-content {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        
        .output-card {
            flex: 1;
            min-height: 400px;
        }
        
        .output-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .output-header h2 {
            margin-bottom: 0;
        }
        
        .output {
            background: var(--bg-primary);
            border-radius: 8px;
            padding: 15px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.85rem;
            line-height: 1.6;
            white-space: pre-wrap;
            overflow-x: auto;
            max-height: 500px;
            overflow-y: auto;
        }
        
        .output:empty::before {
            content: 'Output will appear here...';
            color: var(--text-secondary);
        }
        
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid var(--text-secondary);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .build-dialog {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.7);
            justify-content: center;
            align-items: center;
            z-index: 100;
        }
        
        .build-dialog.active {
            display: flex;
        }
        
        .dialog-content {
            background: var(--bg-secondary);
            padding: 30px;
            border-radius: 12px;
            width: 90%;
            max-width: 500px;
        }
        
        .dialog-content h3 {
            margin-bottom: 20px;
        }
        
        .dialog-content .form-group {
            margin-bottom: 15px;
        }
        
        .dialog-content label {
            display: block;
            margin-bottom: 5px;
            color: var(--text-secondary);
        }
        
        .dialog-content input {
            width: 100%;
        }
        
        .dialog-actions {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
            margin-top: 20px;
        }
        
        .user-info {
            font-size: 0.9rem;
            color: var(--text-secondary);
        }
        
        @media (max-width: 900px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>
                <span>🚀</span>
                Jenkins Dashboard
            </h1>
            <div class="user-info">
                Connected as: <strong id="username">Loading...</strong>
                <a href="#" id="jenkins-link" class="jenkins-link" target="_blank">Open Jenkins →</a>
            </div>
        </header>
        
        <div class="grid">
            <div class="sidebar">
                <div class="card">
                    <h2>Quick Actions</h2>
                    <div class="quick-actions">
                        <button onclick="showRunning()">
                            <span class="icon">⟳</span>
                            <span>Running</span>
                        </button>
                        <button onclick="showQueue()">
                            <span class="icon">📋</span>
                            <span>Queue</span>
                        </button>
                        <button onclick="showAllJobs()">
                            <span class="icon">📁</span>
                            <span>All Jobs</span>
                        </button>
                        <button onclick="openBuildDialog()">
                            <span class="icon">▶️</span>
                            <span>Build</span>
                        </button>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Search Jobs</h2>
                    <div class="search-box">
                        <input type="text" id="search-input" placeholder="e.g. portal, deploy..." 
                               onkeypress="if(event.key==='Enter')searchJobs()">
                        <button onclick="searchJobs()">Search</button>
                    </div>
                </div>
                
                <div class="card">
                    <h2>My Builds</h2>
                    <div class="search-box">
                        <input type="text" id="mybuilds-input" placeholder="Job pattern..." 
                               onkeypress="if(event.key==='Enter')searchMyBuilds()">
                        <button onclick="searchMyBuilds()">Find</button>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Favorites</h2>
                    <div class="favorites" id="favorites">
                        <div class="favorite-item" onclick="getJobStatus('build_and_deploy_private_portal')">
                            <span class="favorite-name">build_and_deploy_private_portal</span>
                            <span class="favorite-status status-unknown">—</span>
                        </div>
                        <div class="favorite-item" onclick="getJobStatus('Portal-Pack-7.1')">
                            <span class="favorite-name">Portal-Pack-7.1</span>
                            <span class="favorite-status status-unknown">—</span>
                        </div>
                        <div class="favorite-item" onclick="getJobStatus('Centos9_RPMS_Portal_Image_CI')">
                            <span class="favorite-name">Centos9_RPMS_Portal_Image_CI</span>
                            <span class="favorite-status status-unknown">—</span>
                        </div>
                    </div>
                    <button class="btn-secondary btn-small" style="margin-top: 15px; width: 100%;" onclick="refreshFavorites()">
                        Refresh Status
                    </button>
                </div>
            </div>
            
            <div class="main-content">
                <div class="card output-card">
                    <div class="output-header">
                        <h2 id="output-title">Output</h2>
                        <span id="loading" style="display: none;"><span class="loading"></span></span>
                    </div>
                    <div class="output" id="output"></div>
                </div>
                
                <div class="card">
                    <h2>Job Details</h2>
                    <div class="search-box">
                        <input type="text" id="job-input" placeholder="Job name..." 
                               onkeypress="if(event.key==='Enter')getJobInfo()">
                        <button onclick="getJobStatus(document.getElementById('job-input').value)">Status</button>
                        <button class="btn-secondary" onclick="getJobInfo()">Info</button>
                        <button class="btn-secondary" onclick="getJobLog()">Log</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Build Dialog -->
    <div class="build-dialog" id="build-dialog">
        <div class="dialog-content">
            <h3>Trigger Build</h3>
            <div class="form-group">
                <label>Job Name</label>
                <input type="text" id="build-job" placeholder="Enter job name...">
            </div>
            <div class="form-group">
                <label>Parameters (optional)</label>
                <input type="text" id="build-params" placeholder="BRANCH=main ENV=staging">
            </div>
            <div class="dialog-actions">
                <button class="btn-secondary" onclick="closeBuildDialog()">Cancel</button>
                <button onclick="triggerBuild()">Build Now</button>
            </div>
        </div>
    </div>
    
    <script>
        const API_BASE = '';
        let jenkinsUrl = '';
        
        // Load config on page load
        async function loadConfig() {
            try {
                const res = await fetch(`${API_BASE}/api/config`);
                const config = await res.json();
                document.getElementById('username').textContent = config.user || 'Unknown';
                jenkinsUrl = config.jenkins_url;
                document.getElementById('jenkins-link').href = jenkinsUrl;
            } catch (e) {
                console.error('Failed to load config:', e);
            }
        }
        
        function setLoading(loading) {
            document.getElementById('loading').style.display = loading ? 'inline' : 'none';
        }
        
        function setOutput(title, content) {
            document.getElementById('output-title').textContent = title;
            document.getElementById('output').textContent = content;
        }
        
        async function apiGet(endpoint) {
            setLoading(true);
            try {
                const res = await fetch(`${API_BASE}${endpoint}`);
                const data = await res.json();
                return data;
            } catch (e) {
                return { success: false, output: 'Request failed: ' + e.message };
            } finally {
                setLoading(false);
            }
        }
        
        async function apiPost(endpoint, body) {
            setLoading(true);
            try {
                const res = await fetch(`${API_BASE}${endpoint}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await res.json();
                return data;
            } catch (e) {
                return { success: false, output: 'Request failed: ' + e.message };
            } finally {
                setLoading(false);
            }
        }
        
        async function showRunning() {
            const data = await apiGet('/api/running');
            setOutput('Running Builds & Queue', data.output);
        }
        
        async function showQueue() {
            const data = await apiGet('/api/queue');
            setOutput('Build Queue', data.output);
        }
        
        async function showAllJobs() {
            const data = await apiGet('/api/jobs');
            setOutput('All Jobs (768)', data.output);
        }
        
        async function searchJobs() {
            const pattern = document.getElementById('search-input').value;
            if (!pattern) return;
            const data = await apiGet(`/api/search?pattern=${encodeURIComponent(pattern)}`);
            setOutput(`Search: "${pattern}"`, data.output);
        }
        
        async function searchMyBuilds() {
            const pattern = document.getElementById('mybuilds-input').value;
            if (!pattern) return;
            const data = await apiGet(`/api/mybuilds?pattern=${encodeURIComponent(pattern)}`);
            setOutput(`My Builds: "${pattern}"`, data.output);
        }
        
        async function getJobStatus(job) {
            if (!job) job = document.getElementById('job-input').value;
            if (!job) return;
            document.getElementById('job-input').value = job;
            const data = await apiGet(`/api/status?job=${encodeURIComponent(job)}`);
            setOutput(`Status: ${job}`, data.output);
        }
        
        async function getJobInfo() {
            const job = document.getElementById('job-input').value;
            if (!job) return;
            const data = await apiGet(`/api/info?job=${encodeURIComponent(job)}`);
            setOutput(`Info: ${job}`, data.output);
        }
        
        async function getJobLog() {
            const job = document.getElementById('job-input').value;
            if (!job) return;
            const data = await apiGet(`/api/log?job=${encodeURIComponent(job)}`);
            setOutput(`Log: ${job}`, data.output);
        }
        
        function openBuildDialog() {
            document.getElementById('build-dialog').classList.add('active');
            document.getElementById('build-job').focus();
        }
        
        function closeBuildDialog() {
            document.getElementById('build-dialog').classList.remove('active');
        }
        
        async function triggerBuild() {
            const job = document.getElementById('build-job').value;
            const params = document.getElementById('build-params').value;
            if (!job) return;
            
            closeBuildDialog();
            const data = await apiPost('/api/build', { job, params });
            setOutput(`Build: ${job}`, data.output);
        }
        
        async function refreshFavorites() {
            const items = document.querySelectorAll('.favorite-item');
            for (const item of items) {
                const name = item.querySelector('.favorite-name').textContent;
                const statusEl = item.querySelector('.favorite-status');
                
                try {
                    const data = await apiGet(`/api/status?job=${encodeURIComponent(name)}`);
                    if (data.output.includes('SUCCESS')) {
                        statusEl.textContent = '✓';
                        statusEl.className = 'favorite-status status-success';
                    } else if (data.output.includes('FAILURE')) {
                        statusEl.textContent = '✗';
                        statusEl.className = 'favorite-status status-failure';
                    } else if (data.output.includes('BUILDING')) {
                        statusEl.textContent = '⟳';
                        statusEl.className = 'favorite-status status-building';
                    } else {
                        statusEl.textContent = '?';
                        statusEl.className = 'favorite-status status-unknown';
                    }
                } catch (e) {
                    statusEl.textContent = '?';
                    statusEl.className = 'favorite-status status-unknown';
                }
            }
        }
        
        // Close dialog on escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeBuildDialog();
        });
        
        // Close dialog on backdrop click
        document.getElementById('build-dialog').addEventListener('click', (e) => {
            if (e.target.id === 'build-dialog') closeBuildDialog();
        });
        
        // Initialize
        loadConfig();
        showRunning();
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                   Jenkins Dashboard                          ║
╠══════════════════════════════════════════════════════════════╣
║  Server running at: http://localhost:{PORT}                    ║
║  Press Ctrl+C to stop                                        ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    server = http.server.HTTPServer(('localhost', PORT), DashboardHandler)
    
    # Try to open browser automatically
    try:
        import webbrowser
        webbrowser.open(f'http://localhost:{PORT}')
    except:
        pass
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
