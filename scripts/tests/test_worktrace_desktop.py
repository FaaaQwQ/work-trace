"""Exercise Qt reply cleanup in a separate process: native crashes cannot be caught."""
import os
import subprocess
import sys


def test_bar_survives_repeated_network_refresh_and_garbage_collection(tmp_path):
    code = r'''
import gc, json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from aw_qt.worktrace import WorkTraceBar

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = [] if self.path.endswith('/projects') else {'paused': False, 'project_id': None}
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
bar = WorkTraceBar('http://127.0.0.1:' + str(server.server_port))
bar.show()
bar.timer.stop()
completed = 0
def step():
    global completed
    if bar.pending_requests or bar.loading:
        return
    if bar.state:
        completed += 1
    gc.collect()
    bar.set_expanded(completed % 2 == 0)
    if completed >= 40:
        assert bar.controls.isEnabled()
        app.exit(0)
    else:
        bar.refresh()
timer = QTimer()
timer.timeout.connect(step)
timer.start(40)
QTimer.singleShot(15000, lambda: app.exit(2))
result = app.exec()
server.shutdown()
raise SystemExit(result)
'''
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "WORKTRACE_HOME": str(tmp_path), "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
