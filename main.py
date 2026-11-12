import sys
import signal
import random
import math
import json
import os
import time
from PySide6.QtWidgets import (
    QApplication, QDialog, QMessageBox, QLabel, QVBoxLayout,
    QDoubleSpinBox, QLCDNumber, QTableWidgetItem, QWidget
)
from PySide6.QtCore import QTimer, Qt, QDateTime, QFile, QIODevice, QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtUiTools import QUiLoader
import pyqtgraph as pg
import sqlite3

# Optional Firebase synchronization for web dashboard
try:
    from firebase_sync import get_sync_instance
    FIREBASE_SYNC_AVAILABLE = True
except ImportError:
    FIREBASE_SYNC_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Hardware imports for ADS1115 ADC on Raspberry Pi
try:
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError):
    HARDWARE_AVAILABLE = False

class UiLoader(QUiLoader):
    def __init__(self, base_instance):
        super().__init__()
        self.base_instance = base_instance

    def createWidget(self, class_name, parent=None, name=""):
        if parent is None and self.base_instance:
            return self.base_instance
        else:
            widget = super().createWidget(class_name, parent, name)
            if self.base_instance and name:
                setattr(self.base_instance, name, widget)
            return widget

def load_ui(ui_file_path, base_instance):
    loader = UiLoader(base_instance)
    ui_file = QFile(ui_file_path)
    if not ui_file.open(QIODevice.ReadOnly):
        raise RuntimeError(f"Cannot open {ui_file_path}: {ui_file.errorString()}")
    widget = loader.load(ui_file)
    ui_file.close()

    if base_instance:
        for obj in base_instance.findChildren(QObject):
            name = obj.objectName()
            if name and not hasattr(base_instance, name):
                setattr(base_instance, name, obj)
    return widget

def init_aegis_logs_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS aegis_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            message TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

class AegisPrimeSupervisor(QDialog):
    def __init__(self, parent, message, db_path=None):
        super().__init__(parent)
        self.message = message
        self.db_path = db_path
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet("""
            QDialog { background-color: #0d1117; border: 2px solid #8957e5; border-radius: 6px; }
            QLabel { color: #0ea5e9; font-family: 'Segoe UI', 'Roboto', sans-serif; font-weight: bold; font-size: 9pt; }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        label = QLabel(f"🤖 Aegis Prime:\n{message}")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.setLayout(layout)

        # Always anchor to the bottom-right corner of the active screen
        popup_w = 260
        self.setFixedWidth(popup_w)
        self.adjustSize()
        popup_h = max(60, self.sizeHint().height())
        margin = 16

        primary_screen = QGuiApplication.primaryScreen()
        if primary_screen:
            s_geo = primary_screen.availableGeometry()
            x = s_geo.x() + s_geo.width() - popup_w - margin
            y = s_geo.y() + s_geo.height() - popup_h - margin
            self.move(x, y)
        elif parent:
            p_geo = parent.geometry()
            x = p_geo.x() + p_geo.width() - popup_w - margin
            y = p_geo.y() + p_geo.height() - popup_h - margin
            self.move(x, y)
        else:
            self.resize(260, 75)

        if db_path:
            self._save_to_database()

        QTimer.singleShot(8000, self.close)

    def mousePressEvent(self, event):
        self.close()

    def _save_to_database(self):
        from datetime import datetime
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO aegis_logs (timestamp, message) VALUES (?, ?)",
                          (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), self.message))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error saving Aegis log: {e}")

        # Also push to Firebase for real-time web mirroring
        if FIREBASE_SYNC_AVAILABLE:
            try:
                sync = get_sync_instance(self.db_path)
                if sync:
                    sync.log_aegis_message(self.message)
            except Exception:
                pass 

class DashboardApp(QDialog):
    def __init__(self):
        global HARDWARE_AVAILABLE
        super().__init__()
        # Load dashboard.ui directly into self
        ui_path = os.path.join(BASE_DIR, "dashboard.ui")
        load_ui(ui_path, self)

        # 1. Override default Qt limits so loaded values over 99.99 don't get clipped
        for spinbox in self.findChildren(QDoubleSpinBox):
            spinbox.setMaximum(99999.99)
            
        for lcd in self.findChildren(QLCDNumber):
            lcd.setSegmentStyle(QLCDNumber.SegmentStyle.Flat)
            lcd.setDigitCount(8)

        # 2. Config File Path
        self.config_file = os.path.join(BASE_DIR, "config.json")
        self.db_path = os.path.join(BASE_DIR, "datalog.db")
        init_aegis_logs_db(self.db_path)

        # Load previous calibrations into UI
        self.load_configuration()

        # Load past Aegis logs
        self.load_aegis_logs()

        # Timer interval for loading fresh logs (every 5 seconds)
        self.aegis_logs_timer = QTimer(self)
        self.aegis_logs_timer.timeout.connect(self.load_aegis_logs)
        self.aegis_logs_timer.start(5000)

        # Connect Save Buttons to the save function
        if hasattr(self, 'btn_save_calibration'):
            self.btn_save_calibration.clicked.connect(self.save_configuration)
        if hasattr(self, 'btn_save_calibration_2'):
            self.btn_save_calibration_2.clicked.connect(self.save_configuration)

        self.SIMULATION_MODE = True
        self.hardware_fault_acknowledged = False
        self.totalizer_m3 = 0.0
        self.current_flow_m3h = 0.0
        self.current_temp = 0.0

        # Cached live voltages and I2C error recovery tracking
        self.current_v_dp = 1.44
        self.current_v_press = 1.44
        self.current_v_temp = 1.44
        self.last_valid_dp = 1.44
        self.last_valid_press = 1.44
        self.last_valid_temp = 1.44
        self.i2c_error_count = 0
        self.cal_v_min = 0.48
        self.cal_v_max = 2.40
        self.cal_offset_dp = 0.0
        self.cal_offset_sp = 0.0
        self.cal_offset_temp = 0.0

        # Initialize Firebase background synchronization if configured
        self.firebase_sync = None
        if FIREBASE_SYNC_AVAILABLE:
            try:
                self.firebase_sync = get_sync_instance(self.db_path)
                if self.firebase_sync and self.firebase_sync.is_connected:
                    print("Firebase Sync: Connected and ready for web mirroring")
            except Exception as e:
                print(f"Firebase Sync note: {e}")
        
        self.max_points = 60
        self.xdata = list(range(-self.max_points, 0))
        self.ydata_flow = [0.0] * self.max_points
        self.ydata_pressure = [0.0] * self.max_points
        self.ydata_temp = [0.0] * self.max_points
        self.ydata_dp = [0.0] * self.max_points
        
        self.filtered_pressure = 0.0
        self.filtered_dp = 0.0
        self.alpha = 0.25  

        self.setup_charts_dynamically()

        # ============================================
        # Hardware sensor initialization for Raspberry Pi
        # ============================================
        # Initialize I2C bus and ADS1115 ADC
        self.dp_sensor = None      # A0 - Differential Pressure (mmH2O)
        self.sp_sensor = None      # A1 - Static Pressure (bar)
        self.temp_sensor = None    # A2 - Temperature transmitter
        self.ads = None
        self.hardware_connected = False  # Flag to indicate successful hardware init

        if HARDWARE_AVAILABLE:
            try:
                import time
                self.i2c = busio.I2C(board.SCL, board.SDA)

                # Scan for I2C devices to detect ADS1115
                print("Scanning I2C bus for ADS1115...")
                devices = []
                for _ in range(3):
                    devices = [hex(x) for x in self.i2c.scan()]
                    time.sleep(0.1)

                if devices:
                    print(f"Found I2C devices: {devices}")
                    if "0x48" in devices or "0x49" in devices or "0x4a" in devices or "0x4b" in devices:
                        # Try default address 0x48 first
                        for addr in [0x48, 0x49, 0x4a, 0x4b]:
                            try:
                                self.ads = ADS.ADS1115(self.i2c, address=addr, gain=1)
                                print(f"Connected to ADS1115 at address 0x{addr:02x}")
                                break
                            except Exception:
                                continue

                if self.ads is None:
                    print("Could not find ADS1115, falling back to simulated hardware")
                    HARDWARE_AVAILABLE = False
                else:
                    # Initialize channels: A0=DP, A1=Static Pressure, A2=Temperature
                    self.dp_sensor = AnalogIn(self.ads, 0)      # A0 - Differential Pressure
                    self.sp_sensor = AnalogIn(self.ads, 1)        # A1 - Static Pressure
                    self.temp_sensor = AnalogIn(self.ads, 2)      # A2 - Temperature
                    self.hardware_connected = True
                    print("ADS1115 channels configured: A0(DP), A1(Pressure), A2(Temp)")
            except Exception as e:
                print(f"Hardware init warning: {e}")
                HARDWARE_AVAILABLE = False
                self.hardware_connected = False

        if hasattr(self, 'btnSimulationToggle'):
            self.btnSimulationToggle.toggled.connect(self.toggle_simulation_mode)
            # The ADS1115 confirmation is the permissive that hardware is connected
            if self.hardware_connected:
                print("[PERMISSIVE] ADS1115 detected and confirmed -> Hardware Mode automatically ENGAGED")
                self.SIMULATION_MODE = False
                self.btnSimulationToggle.setChecked(False)
                self.btnSimulationToggle.setText("⚡ Hardware Mode : ACTIVE (ADS1115 OK)")
            else:
                print("[INFO] ADS1115 not detected on I2C -> Defaulting to Simulation Mode")
                self.SIMULATION_MODE = True
                self.btnSimulationToggle.setChecked(True)
                self.btnSimulationToggle.setText("Simulation Mode : ON (No Hardware)")

        self.ai_facts = [
            "Orifice plates experience permanent pressure loss. Ensure your beta ratio is optimized.",
            "Did you know? The ADS1115 provides 16-bit precision, making it highly sensitive to loop noise.",
            "Anomaly Check: Flow rate stable. No cavitation signatures detected in the DP readings.",
            "ISO 5167 Reminder: Ensure a straight pipe run of at least 10D upstream for measurement accuracy.",
            "Maintaining 4-20mA loop voltage above 0.4V ensures reliable transmitter health."
        ]
        self.aegis_timer = QTimer(self)
        self.aegis_timer.timeout.connect(self.trigger_aegis_popup)
        self.aegis_timer.start(15000)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_system_cycle)
        self.timer.start(1000)

        self.logger_timer = QTimer(self)
        self.logger_timer.timeout.connect(self.log_data_to_table)
        self.logger_timer.start(10000)

        # Timer for live voltage display updates (non-blocking, 1 second interval)
        self.sensor_timer = QTimer(self)
        self.sensor_timer.timeout.connect(self.update_live_values)
        self.sensor_timer.start(1000)

        # Hardware health check timer (checks every 30 seconds for auto-reconnect)
        self.hardware_health_timer = QTimer(self)
        self.hardware_health_timer.timeout.connect(self.check_hardware_connection)
        self.hardware_health_timer.start(30000)  # Check every 30 seconds

    def load_configuration(self):
        """Loads JSON data and populates the UI spin boxes on startup"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    
                # Apply saved values back to the UI widgets
                if hasattr(self, 'spin_dp_min'): self.spin_dp_min.setValue(config.get("dp_min", 0.0))
                if hasattr(self, 'spin_dp_max'): self.spin_dp_max.setValue(config.get("dp_max", 2500.0))
                
                if hasattr(self, 'spin_press_min'): self.spin_press_min.setValue(config.get("press_min", 0.0))
                if hasattr(self, 'spin_press_max'): self.spin_press_max.setValue(config.get("press_max", 10.0))
                
                if hasattr(self, 'spin_temp_min'): self.spin_temp_min.setValue(config.get("temp_min", 0.0))
                if hasattr(self, 'spin_temp_max'): self.spin_temp_max.setValue(config.get("temp_max", 150.0))
                
                if hasattr(self, 'spin_pipe_dia'): self.spin_pipe_dia.setValue(config.get("pipe_dia", 50.0))
                if hasattr(self, 'spin_orifice_dia'): self.spin_orifice_dia.setValue(config.get("orifice_dia", 25.0))
                if hasattr(self, 'spin_fluid_density'): self.spin_fluid_density.setValue(config.get("fluid_density", 1000.0))
                if hasattr(self, 'spin_dynamic'): self.spin_dynamic.setValue(config.get("dynamic", 1.0))
                if hasattr(self, 'spin_atmospheric'): self.spin_atmospheric.setValue(config.get("atmospheric", 1.01325))
                if hasattr(self, 'spin_isentropic'): self.spin_isentropic.setValue(config.get("isentropic", 1.4))
                if hasattr(self, 'spin_pipe_expansion'): self.spin_pipe_expansion.setValue(config.get("pipe_expansion", 0.0))
                if hasattr(self, 'spin_orifice_expansion'): self.spin_orifice_expansion.setValue(config.get("orifice_expansion", 0.0))

                self.cal_v_min = config.get("v_min", 0.468)
                self.cal_v_max = config.get("v_max", 2.34)
                self.cal_offset_dp = config.get("v_offset_dp", 0.0)
                self.cal_offset_sp = config.get("v_offset_sp", 0.0)
                self.cal_offset_temp = config.get("v_offset_temp", 0.0)
                self.press_offset_bar = config.get("press_offset_bar", 0.002)
                
            except Exception as e:
                print(f"Error loading configuration: {e}")

    def save_configuration(self):
        """Extracts values from UI, writes to JSON, and shows a success prompt"""
        config = {
            "dp_min": self.spin_dp_min.value() if hasattr(self, 'spin_dp_min') else 0.0,
            "dp_max": self.spin_dp_max.value() if hasattr(self, 'spin_dp_max') else 2500.0,
            "press_min": self.spin_press_min.value() if hasattr(self, 'spin_press_min') else 0.0,
            "press_max": self.spin_press_max.value() if hasattr(self, 'spin_press_max') else 10.0,
            "temp_min": self.spin_temp_min.value() if hasattr(self, 'spin_temp_min') else 0.0,
            "temp_max": self.spin_temp_max.value() if hasattr(self, 'spin_temp_max') else 150.0,
            "pipe_dia": self.spin_pipe_dia.value() if hasattr(self, 'spin_pipe_dia') else 50.0,
            "orifice_dia": self.spin_orifice_dia.value() if hasattr(self, 'spin_orifice_dia') else 25.0,
            "fluid_density": self.spin_fluid_density.value() if hasattr(self, 'spin_fluid_density') else 1000.0,
            "dynamic": self.spin_dynamic.value() if hasattr(self, 'spin_dynamic') else 1.0,
            "atmospheric": self.spin_atmospheric.value() if hasattr(self, 'spin_atmospheric') else 1.01325,
            "isentropic": self.spin_isentropic.value() if hasattr(self, 'spin_isentropic') else 1.4,
            "pipe_expansion": self.spin_pipe_expansion.value() if hasattr(self, 'spin_pipe_expansion') else 0.0,
            "orifice_expansion": self.spin_orifice_expansion.value() if hasattr(self, 'spin_orifice_expansion') else 0.0,
            "press_offset_bar": getattr(self, 'press_offset_bar', 0.002),
            "v_min": getattr(self, 'cal_v_min', 0.468),
            "v_max": getattr(self, 'cal_v_max', 2.34),
            "v_offset_dp": getattr(self, 'cal_offset_dp', 0.0),
            "v_offset_sp": getattr(self, 'cal_offset_sp', 0.0),
            "v_offset_temp": getattr(self, 'cal_offset_temp', 0.0)
        }
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
            QMessageBox.information(self, "Aegis Prime", "Calibration settings saved successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")

    def setup_charts_dynamically(self):
        def replace_graph(layout, old_widget, title, color):
            plot = pg.PlotWidget(background='#0d1117')
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setLabel('bottom', 'Time', units='s', color='#c9d1d9')
            plot.setLabel('left', title, color='#c9d1d9')
            layout.replaceWidget(old_widget, plot)
            old_widget.deleteLater()
            return plot, plot.plot(pen=pg.mkPen(color=color, width=3))

        self.plot_flow, self.curve_flow = replace_graph(self.gridLayout_3, self.graph_flow, 'Flow Rate (m3/h)', '#23d18b')
        self.plot_pressure, self.curve_pressure = replace_graph(self.gridLayout_4, self.graph_pressure, 'Pressure (bar)', '#0ea5e9')
        self.plot_temp, self.curve_temp = replace_graph(self.gridLayout_5, self.graph_temp, 'Temperature (C)', '#ff7b72')
        self.plot_dp, self.curve_dp = replace_graph(self.gridLayout_6, self.graph_dp, 'Diff Pressure (mmH2O)', '#8957e5')

    def trigger_aegis_popup(self):
        fact = random.choice(self.ai_facts)
        self.popup = AegisPrimeSupervisor(self, fact, self.db_path)
        self.popup.show()

    def load_aegis_logs(self):
        """Load past Aegis observations from database and display in table"""
        if not hasattr(self, 'table_aegis_logs'):
            return

        try:
            # Set horizontal header labels
            self.table_aegis_logs.setHorizontalHeaderLabels(["Timestamp", "Aegis Message"])

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp, message FROM aegis_logs ORDER BY id DESC LIMIT 100")
            rows = cursor.fetchall()
            conn.close()

            self.table_aegis_logs.setRowCount(0)
            for row_data in rows:
                row_position = self.table_aegis_logs.rowCount()
                self.table_aegis_logs.insertRow(row_position)
                self.table_aegis_logs.setItem(row_position, 0, QTableWidgetItem(row_data[0]))
                self.table_aegis_logs.setItem(row_position, 1, QTableWidgetItem(row_data[1]))

            # Set reasonable column widths
            self.table_aegis_logs.setColumnWidth(0, 150)  # Timestamp column
            self.table_aegis_logs.setColumnWidth(1, 800)  # Message column

            self.table_aegis_logs.scrollToBottom()
        except Exception as e:
            print(f"Error loading Aegis logs: {e}")

    def toggle_simulation_mode(self, checked):
        self.SIMULATION_MODE = checked
        self.hardware_fault_acknowledged = False
        if checked:
            self.btnSimulationToggle.setText("Simulation Mode: ON")
            if hasattr(self, 'label'): self.label.setText("Flow Rate")
            if hasattr(self, 'label_2'): self.label_2.setText("Temp (°C / °F)")
            if hasattr(self, 'label_3'): self.label_3.setText("Pressure (bar / psi)")
            if hasattr(self, 'label_4'): self.label_4.setText("DP (bars / mmH2O)")
            self.setWindowTitle("Flow Computer 2.0 - Simulation Mode")
        else:
            if self.hardware_connected:
                self.btnSimulationToggle.setText("⚡ Hardware Mode : ACTIVE (ADS1115 OK)")
            else:
                self.btnSimulationToggle.setText("Hardware Mode : ACTIVE (Waiting for ADS1115...)")

    def read_hardware_sensors(self):
        """
        Safely reads the 3 analog channels from ADS1115 with retry, settling time,
        and transient fault tolerance. Prevents OSError: [Errno 5] Input/output error
        from crashing the application.
        Returns: (dp_v, sp_v, temp_v, is_valid)
        """
        global HARDWARE_AVAILABLE
        if not HARDWARE_AVAILABLE or not getattr(self, 'hardware_connected', False) or \
           self.dp_sensor is None or self.sp_sensor is None or self.temp_sensor is None:
            return 0.0, 0.0, 0.0, False

        for attempt in range(3):
            try:
                # Multi-sample averaging: average 3 successive reads to smooth out loop noise
                def get_channel_avg(sensor, samples=3):
                    total = 0.0
                    for _ in range(samples):
                        total += float(sensor.voltage)
                        time.sleep(0.003)
                    return total / samples

                dp_v = get_channel_avg(self.dp_sensor, 3)
                time.sleep(0.004)
                sp_v = get_channel_avg(self.sp_sensor, 3)
                time.sleep(0.004)
                temp_v = get_channel_avg(self.temp_sensor, 3)

                # Reset error counter on successful read
                self.i2c_error_count = 0
                self.last_valid_dp = dp_v
                self.last_valid_press = sp_v
                self.last_valid_temp = temp_v
                return dp_v, sp_v, temp_v, True

            except (OSError, RuntimeError) as e:
                # Common transient I2C I/O error on Raspberry Pi (Errno 5 / 121)
                time.sleep(0.02 * (attempt + 1))
                if attempt == 2:
                    self.i2c_error_count += 1
                    print(f"I2C Read Warning on ADS1115: {e} (consecutive failures: {self.i2c_error_count})")
            except Exception as e:
                print(f"Unexpected ADC read error: {e}")
                self.i2c_error_count += 1
                return 0.0, 0.0, 0.0, False

        # If a transient glitch occurs (<= 3 consecutive cycles), hold last known good values
        if self.i2c_error_count <= 3 and hasattr(self, 'last_valid_dp'):
            return self.last_valid_dp, self.last_valid_press, self.last_valid_temp, True

        return 0.0, 0.0, 0.0, False

    def update_live_values(self):
        """Update live voltage display labels safely without colliding on the I2C bus"""
        try:
            # Ensure labels always show clean engineering units without raw voltages
            if hasattr(self, 'label'): self.label.setText("Flow Rate")
            if hasattr(self, 'label_2'): self.label_2.setText("Temp (°C / °F)")
            if hasattr(self, 'label_3'): self.label_3.setText("Pressure (bar / psi)")
            if hasattr(self, 'label_4'): self.label_4.setText("DP (bars / mmH2O)")

            if self.SIMULATION_MODE or not getattr(self, 'hardware_connected', False):
                dp_v = getattr(self, 'current_v_dp', 1.44)
                sp_v = getattr(self, 'current_v_press', 1.44)
                temp_v = getattr(self, 'current_v_temp', 1.44)
                mode_prefix = "[SIM]"

                if hasattr(self, 'btnSimulationToggle'):
                    self.btnSimulationToggle.setText("Simulation Mode : ON")
                self.setWindowTitle("Flow Computer 2.0 - Aegis Prime Industrial Dashboard [Simulation Mode]")
            else:
                # In hardware mode, use voltages already sampled by update_system_cycle
                dp_v = getattr(self, 'current_v_dp', None)
                sp_v = getattr(self, 'current_v_press', None)
                temp_v = getattr(self, 'current_v_temp', None)

                # Fallback read only if not yet sampled
                if dp_v is None or sp_v is None or temp_v is None:
                    dp_v, sp_v, temp_v, ok = self.read_hardware_sensors()
                    if not ok:
                        if hasattr(self, 'voltage_status'):
                            self.voltage_status.setText("Hardware Alert: I2C I/O failure")
                        return

                mode_prefix = "[HW]"

                if hasattr(self, 'btnSimulationToggle'):
                    self.btnSimulationToggle.setText("⚡ Hardware Mode : ACTIVE")

                self.setWindowTitle("Flow Computer 2.0 - Aegis Prime Industrial Dashboard [Hardware Connected]")

            # Update dedicated voltage labels (if present in custom views)
            if hasattr(self, 'voltage_dp'):
                self.voltage_dp.setText(f"DP: {dp_v:.3f} V")
            if hasattr(self, 'voltage_sp'):
                self.voltage_sp.setText(f"SP: {sp_v:.3f} V")
            if hasattr(self, 'voltage_temp'):
                self.voltage_temp.setText(f"Temp: {temp_v:.3f} V")

            # Also update single status label if present
            if hasattr(self, 'voltage_status'):
                self.voltage_status.setText(f"{mode_prefix} A0(DP): {dp_v:.3f}V | A1(SP): {sp_v:.3f}V | A2(T): {temp_v:.3f}V")

            # Console log with permissive status
            if mode_prefix == "[HW]":
                print(f"[ADS1115 PERMISSIVE: HW CONNECTED] Sensing Voltages -> A0(DP): {dp_v:.3f}V | A1(SP): {sp_v:.3f}V | A2(Temp): {temp_v:.3f}V")
            else:
                print(f"[SIMULATION MODE] Generated Voltages -> DP: {dp_v:.3f}V | SP: {sp_v:.3f}V | Temp: {temp_v:.3f}V")

        except Exception as e:
            print(f"Error in update_live_values: {e}")

    def check_hardware_connection(self):
        """Periodic health check - attempts to re-establish ADS1115 connection"""
        global HARDWARE_AVAILABLE

        if self.hardware_connected:
            return  # Already connected, no need to check

        print("Health check: Attempting to reconnect to ADS1115...")
        try:
            # Try to scan I2C bus
            devices = [hex(x) for x in self.i2c.scan()]
            if "0x48" in devices or "0x49" in devices or "0x4a" in devices or "0x4b" in devices:
                for addr in [0x48, 0x49, 0x4a, 0x4b]:
                    try:
                        self.ads = ADS.ADS1115(self.i2c, address=addr, gain=1)
                        print(f"Reconnected to ADS1115 at address 0x{addr:02x}")
                        break
                    except Exception:
                        continue

                if self.ads is not None:
                    # Re-initialize channels
                    self.dp_sensor = AnalogIn(self.ads, 0)
                    self.sp_sensor = AnalogIn(self.ads, 1)
                    self.temp_sensor = AnalogIn(self.ads, 2)
                    self.hardware_connected = True
                    HARDWARE_AVAILABLE = True
                    self.SIMULATION_MODE = False
                    if hasattr(self, 'btnSimulationToggle'):
                        self.btnSimulationToggle.setChecked(False)
                        self.btnSimulationToggle.setText("⚡ Hardware Mode : ACTIVE (ADS1115 OK)")
                    print("[PERMISSIVE] ADS1115 confirmed reconnected -> Hardware Mode automatically ENGAGED")
                    if hasattr(self, 'voltage_status'):
                        self.voltage_status.setText("Hardware Permissive: Reconnected!")
                    return

        except Exception as e:
            pass  # Still not available, will retry on next health check

        # Still not connected
        if hasattr(self, 'voltage_status'):
            self.voltage_status.setText("Waiting for hardware...")


    def scale_4_20ma_to_engineering(self, voltage, unit_type):
        v_min = getattr(self, 'cal_v_min', 0.48)
        v_max = getattr(self, 'cal_v_max', 2.40)

        # Apply fine-tuning offsets if specified in configuration
        if unit_type == "pressure":
            voltage += getattr(self, 'cal_offset_sp', 0.0)
            span_min = self.spin_press_min.value()
            span_max = self.spin_press_max.value()
            if span_max <= span_min: span_max = span_min + 10.0 
        elif unit_type == "dp":
            voltage += getattr(self, 'cal_offset_dp', 0.0)
            span_min = self.spin_dp_min.value()
            span_max = self.spin_dp_max.value()
            if span_max <= span_min: span_max = span_min + 2500.0
        elif unit_type == "temp":
            voltage += getattr(self, 'cal_offset_temp', 0.0)
            span_min = self.spin_temp_min.value()
            span_max = self.spin_temp_max.value()
            if span_max <= span_min: span_max = span_min + 150.0
        else:
            return 0.0

        # Disconnected channel or true zero DP transmitter sitting near 0V
        if voltage < 0.20:
            return span_min

        # Scale 4-20mA (e.g. ~0.468V - 2.34V on 117-ohm shunt)
        clamped_v = max(v_min, min(voltage, v_max))
        scaled_val = span_min + (clamped_v - v_min) * (span_max - span_min) / (v_max - v_min)
        if unit_type == "pressure":
            scaled_val += getattr(self, 'press_offset_bar', 0.002)
        return scaled_val

    def calculate_iso5167_flow(self, dp_mmh2o, pressure_bar, temp_c, orifice_d_mm):
        if dp_mmh2o <= 0 or pressure_bar <= 0:
            return 0.0
        k_factor = 0.035
        temp_k = temp_c + 273.15
        return k_factor * (orifice_d_mm ** 2) * math.sqrt((dp_mmh2o * pressure_bar) / temp_k)

    def update_system_cycle(self):
        global HARDWARE_AVAILABLE
        # Orifice diameter in inches (as per UI labels and calibration section)
        orifice_diameter_mm = self.spin_orifice_dia.value() if self.spin_orifice_dia.value() > 0 else 1.0

        if self.SIMULATION_MODE:
            sim_v_press = 1.44 + random.uniform(-0.02, 0.02)
            sim_v_dp = 1.44 + random.uniform(-0.05, 0.05)
            sim_v_temp = 1.44 + random.uniform(-0.01, 0.01)

            self.current_v_dp = sim_v_dp
            self.current_v_press = sim_v_press
            self.current_v_temp = sim_v_temp

            raw_pressure_val = self.scale_4_20ma_to_engineering(sim_v_press, "pressure")
            raw_dp_val = self.scale_4_20ma_to_engineering(sim_v_dp, "dp")
            raw_temp_val = self.scale_4_20ma_to_engineering(sim_v_temp, "temp")

            if random.random() < 0.05:
                raw_pressure_val += (self.spin_press_max.value() * 0.1)
        else:
            dp_v, sp_v, temp_v, ok = self.read_hardware_sensors()
            if ok:
                # Update live voltages directly from hardware read
                self.current_v_dp = dp_v
                self.current_v_press = sp_v
                self.current_v_temp = temp_v

                raw_pressure_val = self.scale_4_20ma_to_engineering(sp_v, "pressure")
                raw_dp_val = self.scale_4_20ma_to_engineering(dp_v, "dp")
                raw_temp_val = self.scale_4_20ma_to_engineering(temp_v, "temp")
            else:
                # Retain last valid readings without freezing the UI or halting execution
                raw_pressure_val = getattr(self, 'filtered_pressure', 0.0)
                raw_dp_val = getattr(self, 'filtered_dp', 0.0)
                raw_temp_val = getattr(self, 'current_temp', 0.0)

        # Sync live voltage display labels with the latest voltages
        self.update_live_values()

        # Push to Firebase for web dashboard synchronization if connected
        if getattr(self, 'firebase_sync', None) and getattr(self.firebase_sync, 'is_connected', False):
            try:
                self.firebase_sync.push_current_readings(
                    self.current_flow_m3h,
                    self.filtered_pressure,
                    self.current_temp,
                    self.filtered_dp,
                    self.totalizer_m3,
                    voltages={
                        'dp': getattr(self, 'current_v_dp', 0.0),
                        'sp': getattr(self, 'current_v_press', 0.0),
                        'temp': getattr(self, 'current_v_temp', 0.0)
                    },
                    hw_connected=self.hardware_connected and not self.SIMULATION_MODE
                )
            except Exception:
                pass

        self.filtered_pressure = max(0.0, (self.alpha * raw_pressure_val) + ((1 - self.alpha) * self.filtered_pressure))
        self.filtered_dp = max(0.0, (self.alpha * raw_dp_val) + ((1 - self.alpha) * self.filtered_dp))

        # DP transmitter is configured in bar (0.0 to 1.0 bar nameplate)
        self.filtered_dp_bar = self.filtered_dp
        self.dp_val_mmh2o = self.filtered_dp * 10000.0

        self.current_temp = raw_temp_val
        self.current_flow_m3h = self.calculate_iso5167_flow(self.dp_val_mmh2o, self.filtered_pressure, self.current_temp, orifice_diameter_mm)
        
        self.totalizer_m3 += (self.current_flow_m3h / 3600.0)

        self.ydata_flow = self.ydata_flow[1:] + [self.current_flow_m3h]
        self.ydata_pressure = self.ydata_pressure[1:] + [self.filtered_pressure]
        self.ydata_temp = self.ydata_temp[1:] + [self.current_temp]
        self.ydata_dp = self.ydata_dp[1:] + [self.filtered_dp]

        self.curve_flow.setData(self.xdata, self.ydata_flow)
        self.curve_pressure.setData(self.xdata, self.ydata_pressure)
        self.curve_temp.setData(self.xdata, self.ydata_temp)
        self.curve_dp.setData(self.xdata, self.ydata_dp)

        self.lcd_flow_rate.display(round(self.current_flow_m3h, 3))
        # Temperature: display in Celsius (label shows °C / °F)
        # °F = (°C × 9/5) + 32
        self.lcd_temp.display(round(self.current_temp, 1))
        # Pressure: display in bar (label shows bar / psi)
        # psi = bar × 14.5038
        self.lcd_pressure.display(round(self.filtered_pressure, 3))
        # DP: display in bars (label shows bars / mmH2O)
        self.lcd_dp.display(round(self.filtered_dp_bar, 4))
        # Totalizer: display in m³ (label shows m³ / L)
        # liters = m³ × 1000
        self.lcd_totalizer.display(round(self.totalizer_m3, 3))

    def log_data_to_table(self):
        if not hasattr(self, 'tableWidget'): return

        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        row_position = self.tableWidget.rowCount()
        self.tableWidget.insertRow(row_position)

        # Calculate secondary units
        pressure_psi = self.filtered_pressure * 14.5038
        temp_f = (self.current_temp * 9/5) + 32
        totalizer_l = self.totalizer_m3 * 1000

        self.tableWidget.setItem(row_position, 0, QTableWidgetItem(timestamp))
        self.tableWidget.setItem(row_position, 1, QTableWidgetItem(f"{self.filtered_pressure:.3f} / {pressure_psi:.3f}"))
        self.tableWidget.setItem(row_position, 2, QTableWidgetItem(f"{self.current_flow_m3h:.3f}"))
        self.tableWidget.setItem(row_position, 3, QTableWidgetItem(f"{self.current_temp:.1f} / {temp_f:.1f}"))
        self.tableWidget.setItem(row_position, 4, QTableWidgetItem(f"{self.filtered_dp:.1f} / {self.filtered_dp_bar:.4f}"))
        self.tableWidget.setItem(row_position, 5, QTableWidgetItem(f"{self.totalizer_m3:.3f} / {totalizer_l:.1f}"))

        # Sync logged row to Firebase so website Data Logger mirrors dashboard
        if getattr(self, 'firebase_sync', None) and getattr(self.firebase_sync, 'is_connected', False):
            try:
                self.firebase_sync.log_flow_data({
                    'timestamp': timestamp,
                    'pressure': round(self.filtered_pressure, 3),
                    'flow_rate': round(self.current_flow_m3h, 3),
                    'temperature': round(self.current_temp, 1),
                    'dp': round(self.filtered_dp, 1),
                    'totalizer': round(self.totalizer_m3, 2)
                })
            except Exception:
                pass

        self.tableWidget.scrollToBottom()

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Clean immediate terminal exit on Ctrl+C (SIGINT) and SIGTERM
    def handle_terminal_exit(signum=None, frame=None):
        print("\n[FlowComputer] Interrupt signal received (Ctrl+C). Terminating...")
        try:
            app.quit()
        finally:
            sys.exit(0)

    signal.signal(signal.SIGINT, handle_terminal_exit)
    signal.signal(signal.SIGTERM, handle_terminal_exit)

    # Periodic timer to allow Python signal handler to wake up from Qt event loop
    sig_timer = QTimer()
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(150)
    
    app.setStyleSheet("""
        QDialog { background-color: #0d1117; }
        QWidget { color: #c9d1d9; font-family: 'Segoe UI', 'Roboto', sans-serif; font-size: 14pt; }
        QLCDNumber { background-color: #010409; color: #23d18b; border: 2px solid #30363d; border-radius: 8px; min-height: 80px; }
        QTableWidget, QTableView { background-color: #010409; color: #0ea5e9; gridline-color: #30363d; border: 1px solid #30363d; selection-background-color: #21262d; }
        QHeaderView::section { background-color: #161b22; color: #c9d1d9; padding: 8px; border: 1px solid #30363d; font-weight: bold; font-size: 12pt; }
        QTabWidget::pane { border: 1px solid #30363d; background-color: #161b22; border-radius: 6px; }
        QTabBar::tab { background: #0d1117; color: #8b949e; padding: 14px 28px; min-width: 180px; font-size: 15pt; font-weight: bold; border: 1px solid transparent; }
        QTabBar::tab:selected { color: #0ea5e9; border-bottom: 2px solid #0ea5e9; }
        QTabBar::tab:hover { color: #ffffff; background: #161b22; }
        QDoubleSpinBox, QSpinBox, QLineEdit { background-color: #010409; color: #0ea5e9; border: 1px solid #30363d; padding: 10px; border-radius: 4px; font-weight: bold; font-size: 15pt; }
        QDoubleSpinBox:focus { border: 1px solid #8957e5; }
        QPushButton { background-color: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 12px 20px; color: #c9d1d9; font-weight: bold; font-size: 14pt; }
        QPushButton:hover { background-color: #30363d; }
        QPushButton:checked { background-color: #8957e5; border-color: #a371f7; color: #ffffff; }
    """)

    window = DashboardApp()
    window.showMaximized()
    sys.exit(app.exec())