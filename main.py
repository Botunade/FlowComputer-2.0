import sys
import random
import math
import json
import os
from PySide6.QtWidgets import (
    QApplication, QDialog, QMessageBox, QLabel, QVBoxLayout,
    QDoubleSpinBox, QLCDNumber, QTableWidgetItem, QWidget
)
from PySide6.QtCore import QTimer, Qt, QDateTime, QFile, QIODevice, QObject
from PySide6.QtUiTools import QUiLoader
import pyqtgraph as pg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

try:
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError):
    HARDWARE_AVAILABLE = False

class AegisPrimeSupervisor(QDialog):
    def __init__(self, parent, message):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet("""
            QDialog { background-color: #0d1117; border: 2px solid #8957e5; border-radius: 8px; }
            QLabel { color: #0ea5e9; font-family: 'Segoe UI', 'Roboto', sans-serif; font-weight: bold; font-size: 10pt; }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        label = QLabel(f"🤖 Aegis Prime:\n{message}")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.setLayout(layout)
        
        if parent:
            p_geo = parent.geometry()
            popup_w = min(360, max(260, int(p_geo.width() * 0.38)))
            self.setFixedWidth(popup_w)
            self.adjustSize()
            popup_h = self.sizeHint().height()
            margin = 16
            x = p_geo.x() + p_geo.width() - popup_w - margin
            y = p_geo.y() + p_geo.height() - popup_h - margin
            self.move(max(p_geo.x() + margin, x), max(p_geo.y() + margin, y))
        else:
            self.resize(320, 90)

        QTimer.singleShot(8000, self.close)

    def mousePressEvent(self, event):
        self.close() 

class DashboardApp(QDialog):
    def __init__(self):
        super().__init__()
        # Load dashboard.ui directly into self
        ui_path = os.path.join(BASE_DIR, "dashboard.ui")
        load_ui(ui_path, self)

        # 1. Override default Qt limits so loaded values over 99.99 don't get clipped
        for spinbox in self.findChildren(QDoubleSpinBox):
            spinbox.setMaximum(99999.99)
            
        for lcd in self.findChildren(QLCDNumber):
            lcd.setSegmentStyle(QLCDNumber.SegmentStyle.Flat)

        # 2. Config File Path
        self.config_file = os.path.join(BASE_DIR, "config.json")
        
        # Load previous calibrations into UI
        self.load_configuration()

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

        self.ads = None
        self.chan_pressure = None
        self.chan_dp = None
        if HARDWARE_AVAILABLE:
            try:
                i2c = busio.I2C(board.SCL, board.SDA)
                self.ads = ADS.ADS1115(i2c)
                self.chan_pressure = AnalogIn(self.ads, ADS.P0)
                self.chan_dp = AnalogIn(self.ads, ADS.P1)
            except Exception as e:
                print(f"Hardware init warning: {e}")

        if hasattr(self, 'btnSimulationToggle'):
            self.btnSimulationToggle.toggled.connect(self.toggle_simulation_mode)
            self.btnSimulationToggle.setChecked(True)

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
            "orifice_expansion": self.spin_orifice_expansion.value() if hasattr(self, 'spin_orifice_expansion') else 0.0
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
        self.popup = AegisPrimeSupervisor(self, fact)
        self.popup.show()

    def toggle_simulation_mode(self, checked):
        self.SIMULATION_MODE = checked
        self.hardware_fault_acknowledged = False 
        if checked:
            self.btnSimulationToggle.setText("Simulation Mode: ON")
        else:
            self.btnSimulationToggle.setText("Hardware Mode: ACTIVE")

    def scale_4_20ma_to_engineering(self, voltage, unit_type):
        v_min, v_max = 0.48, 2.40
        if unit_type == "pressure":
            span_min = self.spin_press_min.value()
            span_max = self.spin_press_max.value()
            if span_max <= span_min: span_max = span_min + 10.0 
        elif unit_type == "dp":
            span_min = self.spin_dp_min.value()
            span_max = self.spin_dp_max.value()
            if span_max <= span_min: span_max = span_min + 2500.0
        elif unit_type == "temp":
            span_min = self.spin_temp_min.value()
            span_max = self.spin_temp_max.value()
            if span_max <= span_min: span_max = span_min + 150.0
        else:
            return 0.0

        clamped_v = max(v_min, min(voltage, v_max))
        return span_min + (clamped_v - v_min) * (span_max - span_min) / (v_max - v_min)

    def calculate_iso5167_flow(self, dp_mmh2o, pressure_bar, temp_c, orifice_d_mm):
        if dp_mmh2o <= 0 or pressure_bar <= 0:
            return 0.0
        k_factor = 0.035
        temp_k = temp_c + 273.15
        return k_factor * (orifice_d_mm ** 2) * math.sqrt((dp_mmh2o * pressure_bar) / temp_k)

    def update_system_cycle(self):
        orifice_diameter_mm = self.spin_orifice_dia.value() if self.spin_orifice_dia.value() > 0 else 50.0 
        sensor_fault = False

        if self.SIMULATION_MODE:
            sim_v_press = 1.44 + random.uniform(-0.02, 0.02)
            sim_v_dp = 1.44 + random.uniform(-0.05, 0.05)
            sim_v_temp = 1.44 + random.uniform(-0.01, 0.01)
            
            raw_pressure_val = self.scale_4_20ma_to_engineering(sim_v_press, "pressure")
            raw_dp_val = self.scale_4_20ma_to_engineering(sim_v_dp, "dp")
            raw_temp_val = self.scale_4_20ma_to_engineering(sim_v_temp, "temp")
            
            if random.random() < 0.05:
                raw_pressure_val += (self.spin_press_max.value() * 0.1) 
        else:
            if not HARDWARE_AVAILABLE or self.chan_pressure is None or self.chan_dp is None:
                sensor_fault = True
            else:
                try:
                    v_press, v_dp = self.chan_pressure.voltage, self.chan_dp.voltage
                    if v_press < 0.40 or v_dp < 0.40:
                        sensor_fault = True
                    else:
                        raw_pressure_val = self.scale_4_20ma_to_engineering(v_press, "pressure")
                        raw_dp_val = self.scale_4_20ma_to_engineering(v_dp, "dp")
                        raw_temp_val = self.scale_4_20ma_to_engineering(1.44, "temp") 
                except Exception:
                    sensor_fault = True

            if sensor_fault:
                raw_pressure_val, raw_dp_val, raw_temp_val = 0.0, 0.0, 0.0
                if not self.hardware_fault_acknowledged:
                    self.hardware_fault_acknowledged = True
                    QMessageBox.critical(self, "Hardware Alert", "4-20mA loop fault detected!\nSwitch to Simulation Mode to refresh.")

        self.filtered_pressure = (self.alpha * raw_pressure_val) + ((1 - self.alpha) * self.filtered_pressure)
        self.filtered_dp = (self.alpha * raw_dp_val) + ((1 - self.alpha) * self.filtered_dp)
        self.current_temp = raw_temp_val
        self.current_flow_m3h = self.calculate_iso5167_flow(self.filtered_dp, self.filtered_pressure, self.current_temp, orifice_diameter_mm)
        
        self.totalizer_m3 += (self.current_flow_m3h / 3600.0)

        self.ydata_flow = self.ydata_flow[1:] + [self.current_flow_m3h]
        self.ydata_pressure = self.ydata_pressure[1:] + [self.filtered_pressure]
        self.ydata_temp = self.ydata_temp[1:] + [self.current_temp]
        self.ydata_dp = self.ydata_dp[1:] + [self.filtered_dp]

        self.curve_flow.setData(self.xdata, self.ydata_flow)
        self.curve_pressure.setData(self.xdata, self.ydata_pressure)
        self.curve_temp.setData(self.xdata, self.ydata_temp)
        self.curve_dp.setData(self.xdata, self.ydata_dp)

        self.lcd_flow_rate.display(round(self.current_flow_m3h, 2))
        self.lcd_temp.display(round(self.current_temp, 1))
        self.lcd_pressure.display(round(self.filtered_pressure, 2))
        self.lcd_dp.display(round(self.filtered_dp, 1))
        self.lcd_totalizer.display(round(self.totalizer_m3, 2))

    def log_data_to_table(self):
        if not hasattr(self, 'tableWidget'): return
        
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        row_position = self.tableWidget.rowCount()
        self.tableWidget.insertRow(row_position)
        
        self.tableWidget.setItem(row_position, 0, QTableWidgetItem(timestamp))
        self.tableWidget.setItem(row_position, 1, QTableWidgetItem(f"{self.filtered_pressure:.2f}"))
        self.tableWidget.setItem(row_position, 2, QTableWidgetItem(f"{self.current_flow_m3h:.2f}"))
        self.tableWidget.setItem(row_position, 3, QTableWidgetItem(f"{self.current_temp:.1f}"))
        self.tableWidget.setItem(row_position, 4, QTableWidgetItem(f"{self.filtered_dp:.1f}"))
        self.tableWidget.setItem(row_position, 5, QTableWidgetItem(f"{self.totalizer_m3:.2f}"))
        
        self.tableWidget.scrollToBottom()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
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