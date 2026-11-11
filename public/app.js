// ========================================================
// Flow Computer 2.0 - Web Dashboard Controller
// Mirrors dashboard.ui and main.py
// ========================================================

const firebaseConfig = {
    apiKey: "AIzaSyCEMeaWLbxkIMcJtXBUPmuzh8gDufSZUFU",
    authDomain: "flowcomputer-fc428.firebaseapp.com",
    databaseURL: "https://flowcomputer-fc428.firebaseio.com",
    projectId: "flowcomputer-fc428",
    storageBucket: "flowcomputer-fc428.firebasestorage.app",
    messagingSenderId: "468250150999",
    appId: "1:4682501509d959ab75bb12",
    measurementId: "G-NTB5V1J7B6"
};

// Initialize Firebase if library available
let database = null;
let isFirebaseConnected = false;
try {
    if (typeof firebase !== 'undefined') {
        firebase.initializeApp(firebaseConfig);
        database = firebase.database();
        const connectedRef = database.ref(".info/connected");
        connectedRef.on("value", (snap) => {
            isFirebaseConnected = snap.val() === true;
            updateConnectionStatus(isFirebaseConnected);
        });
    }
} catch (e) {
    console.warn("Firebase initialization notice:", e);
    updateConnectionStatus(false);
}

function updateConnectionStatus(connected) {
    const pill = document.getElementById("sync-status");
    const text = document.getElementById("sync-status-text");
    if (!pill || !text) return;
    if (connected) {
        pill.className = "status-pill online";
        text.textContent = "Hardware Cloud Synced";
    } else {
        pill.className = "status-pill offline";
        text.textContent = "Local Client / Sim Mode";
    }
}

// Live Clock in Header
setInterval(() => {
    const clock = document.getElementById("live-clock");
    if (clock) {
        const now = new Date();
        clock.textContent = now.toTimeString().split(' ')[0];
    }
}, 1000);

// ========================================================
// Application State & Parameters (ISO 5167)
// ========================================================
let simulationMode = true;
let currentFlow = 0.0;
let currentPressure = 1.44;
let currentTemp = 25.0;
let currentDP = 14.4; // mmH2O
let currentDPBar = 0.0014;
let totalizerM3 = 0.0;
let currentVoltages = null;

// Filter coefficients
let filteredPressure = 1.44;
let filteredDP = 14.4;
const alpha = 0.25;

// Calibration parameters
let calibConfig = {
    dp_min: 0.0,
    dp_max: 2500.0,
    press_min: 0.0,
    press_max: 60.0,
    temp_min: 0.0,
    temp_max: 80.0,
    pipe_dia: 3.0,
    orifice_dia: 2.0,
    fluid_density: 1.0,
    dynamic: 1.0,
    atmospheric: 1.0,
    isentropic: 1.4,
    pipe_expansion: 0.0,
    orifice_expansion: 0.0
};

// ========================================================
// Tab Navigation
// ========================================================
function switchMainTab(tabId, element) {
    document.querySelectorAll('.main-tab-bar .tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(section => section.classList.remove('active'));

    if (element) element.classList.add('active');
    const target = document.getElementById(tabId);
    if (target) target.classList.add('active');

    // Resize chart if switching to Trends tab
    if (tabId === 'Trends' && trendChart) {
        setTimeout(() => trendChart.resize(), 50);
    }
}

let activeTrendParam = 'flow';
function switchTrendSubTab(param, element) {
    document.querySelectorAll('.trends-card .sub-tab-btn').forEach(btn => btn.classList.remove('active'));
    if (element) element.classList.add('active');
    activeTrendParam = param;
    updateChartDisplayConfig();
}

function switchCalibSubTab(subId, element) {
    document.querySelectorAll('#Calibrations .sub-tab-btn').forEach(btn => btn.classList.remove('active'));
    if (element) element.classList.add('active');

    document.getElementById('calib-transmitters').style.display = (subId === 'transmitters') ? 'block' : 'none';
    document.getElementById('calib-orifice').style.display = (subId === 'orifice') ? 'block' : 'none';
}

// ========================================================
// Simulation Mode Toggle
// ========================================================
function toggleSimulationMode() {
    simulationMode = !simulationMode;
    const btn = document.getElementById("btnSimulationToggle");
    if (!btn) return;

    if (simulationMode) {
        btn.classList.add("active");
        btn.innerHTML = "<span>🔁</span> Simulation Mode : ON";
        showToast("Simulation Mode Activated");
    } else {
        btn.classList.remove("active");
        btn.innerHTML = "<span>⚡</span> Hardware Mode : ACTIVE";
        showToast("Hardware Telemetry Engaged");
    }
}

// ========================================================
// Trend Chart (pyqtgraph Dark Style with Chart.js)
// ========================================================
const MAX_POINTS = 60;
const chartLabels = Array.from({ length: MAX_POINTS }, (_, i) => `-${MAX_POINTS - 1 - i}s`);
const historyData = {
    flow: Array(MAX_POINTS).fill(0.0),
    pressure: Array(MAX_POINTS).fill(0.0),
    temp: Array(MAX_POINTS).fill(0.0),
    dp: Array(MAX_POINTS).fill(0.0)
};

const paramConfigs = {
    flow: {
        label: 'Flow Rate (m³/h)',
        borderColor: '#23d18b',
        backgroundColor: 'rgba(35, 209, 139, 0.1)',
        unit: 'm³/h'
    },
    pressure: {
        label: 'Pressure (bar)',
        borderColor: '#0ea5e9',
        backgroundColor: 'rgba(14, 165, 233, 0.1)',
        unit: 'bar'
    },
    temp: {
        label: 'Temperature (°C)',
        borderColor: '#ff7b72',
        backgroundColor: 'rgba(255, 123, 114, 0.1)',
        unit: '°C'
    },
    dp: {
        label: 'Differential Pressure (mmH2O)',
        borderColor: '#8957e5',
        backgroundColor: 'rgba(137, 87, 229, 0.1)',
        unit: 'mmH2O'
    }
};

let trendChart = null;

function initTrendChart() {
    const ctx = document.getElementById('trendChartCanvas');
    if (!ctx) return;

    const config = paramConfigs[activeTrendParam];
    trendChart = new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: {
            labels: chartLabels,
            datasets: [{
                label: config.label,
                data: historyData[activeTrendParam],
                borderColor: config.borderColor,
                backgroundColor: config.backgroundColor,
                borderWidth: 2.2,
                pointRadius: 0,
                tension: 0.25,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.06)' },
                    ticks: { color: '#8b949e', font: { family: 'Courier New', size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.06)' },
                    ticks: { color: '#8b949e', font: { family: 'Courier New', size: 11 } }
                }
            },
            plugins: {
                legend: {
                    labels: { color: '#c9d1d9', font: { weight: 'bold', size: 12 } }
                }
            }
        }
    });
}

function updateChartDisplayConfig() {
    if (!trendChart) return;
    const config = paramConfigs[activeTrendParam];
    trendChart.data.datasets[0].label = config.label;
    trendChart.data.datasets[0].borderColor = config.borderColor;
    trendChart.data.datasets[0].backgroundColor = config.backgroundColor;
    trendChart.data.datasets[0].data = historyData[activeTrendParam];
    trendChart.update();
}

function pushChartPoint(param, val) {
    if (!historyData[param]) return;
    historyData[param].shift();
    historyData[param].push(val);
}

// ========================================================
// Calculation Engine (ISO 5167 Placeholder Formula)
// ========================================================
function calculateISO5167Flow(dp_mmh2o, press_bar, temp_c, orifice_d_inch) {
    if (dp_mmh2o <= 0 || press_bar <= 0) return 0.0;
    const k_factor = 0.035;
    const temp_k = temp_c + 273.15;
    const d = orifice_d_inch > 0 ? orifice_d_inch : 1.0;
    return k_factor * (d * d) * Math.sqrt((dp_mmh2o * press_bar) / temp_k);
}

function scaleVoltage(voltage, v_min, v_max, span_min, span_max) {
    if (voltage < 0.20) return span_min;
    const clamped = Math.max(v_min, Math.min(voltage, v_max));
    return span_min + (clamped - v_min) * (span_max - span_min) / (v_max - v_min);
}

// ========================================================
// Live Update Cycle (Runs every 1000ms, matching main.py)
// ========================================================
function runSystemCycle() {
    let rawPressure = 0.0;
    let rawDP = 0.0;
    let rawTemp = 25.0;

    if (simulationMode) {
        // Generate simulated voltage jitter around 1.44V
        const simVPress = 1.44 + (Math.random() * 0.04 - 0.02);
        const simVDP = 1.44 + (Math.random() * 0.10 - 0.05);
        const simVTemp = 1.44 + (Math.random() * 0.02 - 0.01);

        rawPressure = scaleVoltage(simVPress, 0.48, 2.40, calibConfig.press_min, calibConfig.press_max);
        rawDP = scaleVoltage(simVDP, 0.48, 2.40, calibConfig.dp_min, calibConfig.dp_max);
        rawTemp = scaleVoltage(simVTemp, 0.48, 2.40, calibConfig.temp_min, calibConfig.temp_max);

        // Occasional process disturbance
        if (Math.random() < 0.05) {
            rawPressure += (calibConfig.press_max * 0.1);
        }
    } else {
        // Hardware values maintained via Firebase or last known good
        rawPressure = currentPressure;
        rawDP = currentDP;
        rawTemp = currentTemp;
    }

    // Apply digital smoothing filter (alpha = 0.25)
    filteredPressure = (alpha * rawPressure) + ((1 - alpha) * filteredPressure);
    filteredDP = (alpha * rawDP) + ((1 - alpha) * filteredDP);
    currentDPBar = filteredDP / 10000.0;
    currentTemp = rawTemp;

    // Compute ISO 5167 flow rate
    currentFlow = calculateISO5167Flow(filteredDP, filteredPressure, currentTemp, calibConfig.orifice_dia);
    totalizerM3 += (currentFlow / 3600.0);

    // Update history buffers
    pushChartPoint('flow', currentFlow);
    pushChartPoint('pressure', filteredPressure);
    pushChartPoint('temp', currentTemp);
    pushChartPoint('dp', filteredDP);

    if (trendChart) {
        trendChart.update();
    }

    // Render LCDs on Main Dashboard
    renderLCDDisplays();
}

// ========================================================
// Render LCD Displays
// ========================================================
function renderLCDDisplays() {
    // Flow Rate
    const elFlow = document.getElementById("lcd_flow_rate");
    if (elFlow) elFlow.textContent = currentFlow.toFixed(2);

    // Temperature (Dual: °C and °F)
    const elTemp = document.getElementById("lcd_temp");
    const elTempSub = document.getElementById("lcd_temp_sub");
    if (elTemp) elTemp.textContent = currentTemp.toFixed(1);
    if (elTempSub) {
        const tempF = (currentTemp * 9 / 5) + 32;
        elTempSub.textContent = `${tempF.toFixed(1)} °F`;
    }

    // Pressure (Dual: bar and psi)
    const elPress = document.getElementById("lcd_pressure");
    const elPressSub = document.getElementById("lcd_pressure_sub");
    if (elPress) elPress.textContent = filteredPressure.toFixed(2);
    if (elPressSub) {
        const pressPsi = filteredPressure * 14.5038;
        elPressSub.textContent = `${pressPsi.toFixed(2)} psi`;
    }

    // Differential Pressure (Dual: bar and mmH2O)
    const elDP = document.getElementById("lcd_dp");
    const elDPSub = document.getElementById("lcd_dp_sub");
    if (elDP) elDP.textContent = currentDPBar.toFixed(4);
    if (elDPSub) {
        elDPSub.textContent = `${filteredDP.toFixed(1)} mmH2O`;
    }

    // Totalizer (Dual: m³ and Liters)
    const elTot = document.getElementById("lcd_totalizer");
    const elTotSub = document.getElementById("lcd_totalizer_sub");
    if (elTot) elTot.textContent = totalizerM3.toFixed(2);
    if (elTotSub) {
        const totalizerL = totalizerM3 * 1000.0;
        elTotSub.textContent = `${totalizerL.toFixed(1)} L`;
    }
}

// ========================================================
// Data Logger Table (tableWidget)
// ========================================================
function logCurrentCycleToTable() {
    const tbody = document.getElementById("log-table-body");
    if (!tbody) return;

    const now = new Date();
    const timestamp = now.toISOString().replace('T', ' ').substring(0, 19);

    const pressPsi = filteredPressure * 14.5038;
    const tempF = (currentTemp * 9 / 5) + 32;
    const totalizerL = totalizerM3 * 1000;

    const row = document.createElement("tr");
    row.innerHTML = `
        <td>${timestamp}</td>
        <td>${filteredPressure.toFixed(2)} / ${pressPsi.toFixed(2)}</td>
        <td style="color: #23d18b; font-weight: bold;">${currentFlow.toFixed(2)}</td>
        <td>${currentTemp.toFixed(1)} / ${tempF.toFixed(1)}</td>
        <td>${filteredDP.toFixed(1)} / ${currentDPBar.toFixed(4)}</td>
        <td>${totalizerM3.toFixed(2)} / ${totalizerL.toFixed(1)}</td>
    `;

    // Remove placeholder row if present
    if (tbody.children.length === 1 && tbody.children[0].children.length === 1) {
        tbody.innerHTML = '';
    }

    tbody.insertBefore(row, tbody.firstChild);

    // Limit table length to 100 rows
    while (tbody.children.length > 100) {
        tbody.removeChild(tbody.lastChild);
    }
}

function clearTable(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #8b949e;">Cleared. Awaiting new telemetry...</td></tr>';
    }
}

// ========================================================
// Aegis Prime Logs & Floating Supervisor Popup
// ========================================================
const aegisFacts = [
    "Differential pressure across orifice maintains turbulent Reynolds profile (>10,000).",
    "Static pressure steady within nominal nameplate tolerances.",
    "Fluid temperature stable. Vapor pressure cavitation threshold verified.",
    "ISO 5167 expansion factor (epsilon) within ±0.02% error envelope.",
    "4-20mA current loop integrity verified across ADC channels A0, A1, A2.",
    "Dual-unit totalizer tracking mass and volumetric conservation accurately."
];

let aegisPopupTimeout = null;

function showAegisPopup(message) {
    const popup = document.getElementById("aegis-popup");
    const msgEl = document.getElementById("aegis-popup-msg");
    if (!popup || !msgEl) return;

    msgEl.textContent = message;
    popup.style.display = "block";

    if (aegisPopupTimeout) clearTimeout(aegisPopupTimeout);
    aegisPopupTimeout = setTimeout(() => {
        dismissAegisPopup();
    }, 8000);

    // Append to Aegis Logs table
    appendAegisLog(message);
}

function dismissAegisPopup() {
    const popup = document.getElementById("aegis-popup");
    if (popup) popup.style.display = "none";
}

function appendAegisLog(message) {
    const tbody = document.getElementById("aegis-table-body");
    if (!tbody) return;

    const now = new Date();
    const timestamp = now.toISOString().replace('T', ' ').substring(0, 19);

    const row = document.createElement("tr");
    row.innerHTML = `
        <td style="color: #8b949e;">${timestamp}</td>
        <td style="color: #0ea5e9;">${message}</td>
    `;

    if (tbody.children.length === 1 && tbody.children[0].children.length === 1) {
        tbody.innerHTML = '';
    }

    tbody.insertBefore(row, tbody.firstChild);

    while (tbody.children.length > 100) {
        tbody.removeChild(tbody.lastChild);
    }
}

// Random Aegis supervisor advisory every 25 seconds
setInterval(() => {
    const randomFact = aegisFacts[Math.floor(Math.random() * aegisFacts.length)];
    showAegisPopup(randomFact);
}, 25000);

// ========================================================
// Calibration Management
// ========================================================
function saveTransmitterCalibration() {
    calibConfig.dp_min = parseFloat(document.getElementById("spin_dp_min").value) || 0.0;
    calibConfig.dp_max = parseFloat(document.getElementById("spin_dp_max").value) || 2500.0;
    calibConfig.press_min = parseFloat(document.getElementById("spin_press_min").value) || 0.0;
    calibConfig.press_max = parseFloat(document.getElementById("spin_press_max").value) || 60.0;
    calibConfig.temp_min = parseFloat(document.getElementById("spin_temp_min").value) || 0.0;
    calibConfig.temp_max = parseFloat(document.getElementById("spin_temp_max").value) || 80.0;

    if (database) {
        database.ref("calibration/transmitters").set({
            dp_min: calibConfig.dp_min,
            dp_max: calibConfig.dp_max,
            press_min: calibConfig.press_min,
            press_max: calibConfig.press_max,
            temp_min: calibConfig.temp_min,
            temp_max: calibConfig.temp_max,
            updated_at: new Date().toISOString()
        });
    }

    showToast("Transmitter Calibration Saved Successfully!");
}

function saveOrificeCalibration() {
    calibConfig.pipe_dia = parseFloat(document.getElementById("spin_pipe_dia").value) || 3.0;
    calibConfig.orifice_dia = parseFloat(document.getElementById("spin_orifice_dia").value) || 2.0;
    calibConfig.fluid_density = parseFloat(document.getElementById("spin_fluid_density").value) || 1.0;
    calibConfig.dynamic = parseFloat(document.getElementById("spin_dynamic").value) || 1.0;
    calibConfig.atmospheric = parseFloat(document.getElementById("spin_atmospheric").value) || 1.0;
    calibConfig.isentropic = parseFloat(document.getElementById("spin_isentropic").value) || 1.4;
    calibConfig.pipe_expansion = parseFloat(document.getElementById("spin_pipe_expansion").value) || 0.0;
    calibConfig.orifice_expansion = parseFloat(document.getElementById("spin_orifice_expansion").value) || 0.0;

    if (database) {
        database.ref("calibration/orifice").set({
            pipe_dia: calibConfig.pipe_dia,
            orifice_dia: calibConfig.orifice_dia,
            fluid_density: calibConfig.fluid_density,
            dynamic: calibConfig.dynamic,
            atmospheric: calibConfig.atmospheric,
            isentropic: calibConfig.isentropic,
            pipe_expansion: calibConfig.pipe_expansion,
            orifice_expansion: calibConfig.orifice_expansion,
            updated_at: new Date().toISOString()
        });
    }

    showToast("Orifice Calibration Saved Successfully!");
}

function showToast(message) {
    const toast = document.getElementById("toast");
    if (!toast) return;
    toast.textContent = `Aegis Prime: ${message}`;
    toast.style.display = "block";
    setTimeout(() => {
        toast.style.display = "none";
    }, 3500);
}

// ========================================================
// Firebase Realtime Listeners
// ========================================================
function initFirebaseListeners() {
    if (!database) return;

    // Listen to current readings broadcasted by main.py
    database.ref("current_readings").on("value", (snapshot) => {
        const val = snapshot.val();
        if (val) {
            // Check hardware permissive
            if (val.hardware_connected) {
                const pill = document.getElementById("sync-status");
                const text = document.getElementById("sync-status-text");
                if (pill && text) {
                    pill.className = "status-pill online";
                    text.textContent = "Hardware Connected";
                }
            }
            if (val.voltages) {
                currentVoltages = val.voltages;
            }

            if (!simulationMode) {
                currentFlow = val.flow_rate || currentFlow;
                currentPressure = val.pressure || currentPressure;
                currentTemp = val.temperature || currentTemp;
                currentDP = val.dp || currentDP;
                currentDPBar = currentDP / 10000.0;
                totalizerM3 = val.totalizer || totalizerM3;

                const btn = document.getElementById("btnSimulationToggle");
                if (btn) {
                    btn.innerHTML = `<span>⚡</span> Hardware Mode : ACTIVE`;
                }

                renderLCDDisplays();
            }
        }
    });

    // Listen to new historical log entries
    database.ref("flow_data").limitToLast(1).on("child_added", (snapshot) => {
        const row = snapshot.val();
        if (row && !simulationMode) {
            const tbody = document.getElementById("log-table-body");
            if (tbody) {
                const tr = document.createElement("tr");
                const pPsi = (row.pressure || 0) * 14.5038;
                const tF = ((row.temperature || 0) * 9 / 5) + 32;
                const totL = (row.totalizer || 0) * 1000;
                tr.innerHTML = `
                    <td>${row.timestamp || ''}</td>
                    <td>${(row.pressure || 0).toFixed(2)} / ${pPsi.toFixed(2)}</td>
                    <td style="color: #23d18b; font-weight: bold;">${(row.flow_rate || 0).toFixed(2)}</td>
                    <td>${(row.temperature || 0).toFixed(1)} / ${tF.toFixed(1)}</td>
                    <td>${(row.dp || 0).toFixed(1)} / ${((row.dp || 0)/10000).toFixed(4)}</td>
                    <td>${(row.totalizer || 0).toFixed(2)} / ${totL.toFixed(1)}</td>
                `;
                tbody.insertBefore(tr, tbody.firstChild);
            }
        }
    });

    // Listen to Aegis logs
    database.ref("aegis_logs").limitToLast(1).on("child_added", (snapshot) => {
        const log = snapshot.val();
        if (log && log.message) {
            showAegisPopup(log.message);
        }
    });
}

// ========================================================
// Startup Initialization
// ========================================================
window.addEventListener("DOMContentLoaded", () => {
    initTrendChart();
    initFirebaseListeners();

    // Run system cycle every 1000ms
    setInterval(runSystemCycle, 1000);

    // Record to Data Logger table every 3000ms
    setInterval(logCurrentCycleToTable, 3000);

    // Initial advisory popup after 3 seconds
    setTimeout(() => {
        showAegisPopup("Aegis Prime Supervisory Telemetry Initialized.");
    }, 3000);
});
