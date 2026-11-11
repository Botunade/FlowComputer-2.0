"""
Firebase synchronization module for Flow Computer 2.0
Connects local SQLite database to Firebase Realtime Database
"""

import os
import json
import time
import threading
import sqlite3
from datetime import datetime

try:
    import pyrebase
    PYFIREBASE_AVAILABLE = True
except ImportError:
    PYFIREBASE_AVAILABLE = False

class FirebaseSync:
    def __init__(self, db_path):
        """
        Initialize Firebase sync

        Args:
            db_path: Path to local SQLite database
        """
        self.db_path = db_path
        self.last_sync_timestamps = {
            'aegis_logs': '1970-01-01 00:00:00',
            'flow_data': '1970-01-01 00:00:00'
        }
        self.is_connected = False
        self.sync_thread = None
        self.running = False
        self.db = None

        firebase_config = self._load_firebase_config()
        if firebase_config and PYFIREBASE_AVAILABLE:
            self._init_firebase(firebase_config)

    def _load_firebase_config(self):
        """Load Firebase configuration from file"""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'firebase_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                # Convert to pyrebase4 format
                return {
                    'apiKey': config.get('apiKey'),
                    'authDomain': config.get('authDomain'),
                    'databaseURL': config.get('databaseURL'),
                    'projectId': config.get('projectId'),
                    'storageBucket': config.get('storageBucket'),
                    'messagingSenderId': config.get('messagingSenderId'),
                    'appId': config.get('appId')
                }
        return None

    def _init_firebase(self, config):
        """Initialize Firebase connection"""
        try:
            self.firebase = pyrebase.initialize_app(config)
            self.db = self.firebase.database()
            self.is_connected = True
            print(f"[FirebaseSync] Connected to Firebase project: {config.get('projectId')}")
        except Exception as e:
            print(f"[FirebaseSync] Connection failed: {e}")
            self.is_connected = False

    def sync_aegis_logs(self):
        """Sync new Aegis logs to Firebase"""
        if not self.is_connected or not self.db:
            return False

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            last_sync = self.last_sync_timestamps['aegis_logs']
            cursor.execute("""
                SELECT timestamp, message FROM aegis_logs
                WHERE timestamp > ? ORDER BY timestamp
            """, (last_sync,))

            new_logs = cursor.fetchall()
            conn.close()

            if not new_logs:
                return True

            for timestamp, message in new_logs:
                log_data = {
                    'timestamp': timestamp,
                    'message': message
                }

                self.db.child('aegis_logs').push(log_data)

                if timestamp > last_sync:
                    self.last_sync_timestamps['aegis_logs'] = timestamp

            if new_logs:
                self.last_sync_timestamps['aegis_logs'] = max(
                    self.last_sync_timestamps['aegis_logs'],
                    new_logs[-1][0]
                )

            print(f"[FirebaseSync] Synced {len(new_logs)} Aegis logs")
            return True

        except Exception as e:
            print(f"[FirebaseSync] Error syncing aegis_logs: {e}")
            return False

    def sync_flow_data(self, flow_data):
        """
        Sync flow data to Firebase

        Args:
            flow_data: Dict with current readings
        """
        if not self.is_connected:
            return False

        try:
            flow_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Push to history
            self.db.child('flow_data').push(flow_data)

            # Update current readings
            self.db.child('current_readings').set(flow_data)

            return True

        except Exception as e:
            print(f"[FirebaseSync] Error syncing flow_data: {e}")
            return False

    def sync_all_pending(self):
        """Sync all pending data to Firebase"""
        self.sync_aegis_logs()
        return self.is_connected

    def start_background_sync(self, interval_seconds=30):
        """Start background sync thread"""
        self.running = True

        def sync_loop():
            while self.running:
                self.sync_all_pending()
                time.sleep(interval_seconds)

        self.sync_thread = threading.Thread(target=sync_loop, daemon=True)
        self.sync_thread.start()
        return self.sync_thread

    def stop_background_sync(self):
        """Stop background sync thread"""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)

    def push_current_readings(self, flow_m3h, pressure, temp, dp, totalizer, voltages=None, hw_connected=False):
        """Push current readings to Firebase"""
        flow_data = {
            'flow_rate': round(flow_m3h, 2),
            'pressure': round(pressure, 2),
            'temperature': round(temp, 1),
            'dp': round(dp, 1),
            'totalizer': round(totalizer, 2),
            'hardware_connected': bool(hw_connected)
        }
        if voltages:
            flow_data['voltages'] = {
                'dp': round(float(voltages.get('dp', 0.0)), 3),
                'sp': round(float(voltages.get('sp', 0.0)), 3),
                'temp': round(float(voltages.get('temp', 0.0)), 3)
            }
        return self.sync_flow_data(flow_data)


# Global sync instance
_sync_instance = None

def get_sync_instance(db_path=None):
    """Get or create the global sync instance"""
    global _sync_instance

    if _sync_instance is None:
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'datalog.db')

        _sync_instance = FirebaseSync(db_path)

    return _sync_instance


if __name__ == '__main__':
    sync = get_sync_instance()
    if sync.is_connected:
        print("Firebase connection successful!")
    else:
        print("Firebase connection not configured or failed")