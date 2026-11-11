"""
Robust, zero-dependency Firebase Realtime Database synchronization module
Uses Python standard library (urllib.request, json, threading, queue)
"""

import os
import json
import time
import threading
import queue
import urllib.request
from datetime import datetime

DATABASE_URL = "https://flowcomputer-fc428-default-rtdb.firebaseio.com"

class FirebaseSync:
    def __init__(self, db_path=None):
        self.db_path = db_path
        self.database_url = DATABASE_URL
        self.is_connected = True
        self.work_queue = queue.Queue(maxsize=200)
        self.running = True

        # Load databaseURL from config if present
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'firebase_config.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    if cfg.get('databaseURL'):
                        self.database_url = cfg['databaseURL'].rstrip('/')
            except Exception:
                pass

        # Start non-blocking daemon thread for HTTP sync requests
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        print(f"[FirebaseSync] Live cloud sync active: {self.database_url}")

    def _http_put(self, path, data):
        url = f"{self.database_url}/{path}.json"
        payload = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method='PUT')
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            return False

    def _http_post(self, path, data):
        url = f"{self.database_url}/{path}.json"
        payload = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            return False

    def _worker_loop(self):
        while self.running:
            try:
                task = self.work_queue.get(timeout=1.0)
                if task is None:
                    break
                action, path, data = task
                if action == 'put':
                    self._http_put(path, data)
                elif action == 'post':
                    self._http_post(path, data)
                self.work_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass

    def push_current_readings(self, flow_m3h, pressure, temp, dp, totalizer, is_simulation=False, hw_connected=False):
        """Enqueue live telemetry update for Firebase 'current_readings'"""
        data = {
            'flow_rate': round(float(flow_m3h), 2),
            'pressure': round(float(pressure), 2),
            'temperature': round(float(temp), 1),
            'dp': round(float(dp), 1),
            'totalizer': round(float(totalizer), 2),
            'is_simulation': bool(is_simulation),
            'hardware_connected': bool(hw_connected),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        try:
            self.work_queue.put_nowait(('put', 'current_readings', data))
        except queue.Full:
            pass

    def log_flow_data(self, row_data):
        """Enqueue historic log row for Firebase 'flow_data'"""
        try:
            self.work_queue.put_nowait(('post', 'flow_data', row_data))
        except queue.Full:
            pass

    def log_aegis_message(self, message):
        """Enqueue Aegis message for Firebase 'aegis_logs'"""
        data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'message': str(message)
        }
        try:
            self.work_queue.put_nowait(('post', 'aegis_logs', data))
        except queue.Full:
            pass


_sync_instance = None

def get_sync_instance(db_path=None):
    global _sync_instance
    if _sync_instance is None:
        _sync_instance = FirebaseSync(db_path)
    return _sync_instance
