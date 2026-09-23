// Firebase configuration
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

// Initialize Firebase
firebase.initializeApp(firebaseConfig);
const database = firebase.database();

// Chart instances
let flowChartMain = null;
let flowChartTrends = null;
let pressureChartTrends = null;
let tempChartTrends = null;
let dpChartTrends = null;

// Data buffers
let flowData = [];
const MAX_CHART_POINTS = 30;

// Offline tracking
let isOffline = false;
let pendingData = [];

// Tab switching
function showTab(tabName) {
    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.style.display = 'none');

    event.currentTarget.classList.add('active');
    const tabElement = document.getElementById(tabName);
    if (tabElement) {
        tabElement.style.display = 'block';
    }

    if (tabName === 'main') initMainDashboard();
    if (tabName === 'trends') initTrendsTab();
    if (tabName === 'data') loadDataLogger();
    if (tabName === 'calibration') loadCalibrationData();
    if (tabName === 'aegis') loadAegisLogs();
    if (tabName === 'flow') loadFlowData();
}

// Update offline badge
function updateOfflineStatus(online) {
    const badge = document.getElementById('offline-badge');
    isOffline = !online;
    badge.style.display = online ? 'none' : 'flex';
}

// Real-time connection status
window.addEventListener('online', () => updateOfflineStatus(true));
window.addEventListener('offline', () => updateOfflineStatus(false));

// Initialize main dashboard charts
function initMainDashboard() {
    const ctx = document.getElementById('flow-chart-main');
    if (!ctx) return;

    flowChartMain = new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Flow Rate (m³/h)',
                data: [],
                borderColor: '#23d18b',
                backgroundColor: 'rgba(35, 209, 139, 0.1)',
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { color: 'rgba(255,255,255,0.1)' } },
                y: { grid: { color: 'rgba(255,255,255,0.1)' }, beginAtZero: true }
            }
        }
    });
}

// Initialize trends tab with multiple charts
function initTrendsTab() {
    // Flow Rate Chart
    const flowCtx = document.getElementById('flow-chart-trends');
    if (flowCtx && !flowChartTrends) {
        flowChartTrends = new Chart(flowCtx.getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Flow Rate (m³/h)', data: [], borderColor: '#23d18b', borderWidth: 2 }] },
            options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { color: 'rgba(255,255,255,0.1)' } }, y: { grid: { color: 'rgba(255,255,255,0.1)' } } } }
        });
    }

    // Pressure Chart
    const pressureCtx = document.getElementById('pressure-chart-trends');
    if (pressureCtx && !pressureChartTrends) {
        pressureChartTrends = new Chart(pressureCtx.getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Pressure (bar)', data: [], borderColor: '#0ea5e9', borderWidth: 2 }] },
            options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { color: 'rgba(255,255,255,0.1)' } }, y: { grid: { color: 'rgba(255,255,255,0.1)' } } } }
        });
    }

    // Temperature Chart
    const tempCtx = document.getElementById('temp-chart-trends');
    if (tempCtx && !tempChartTrends) {
        tempChartTrends = new Chart(tempCtx.getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Temperature (°C)', data: [], borderColor: '#ff7b72', borderWidth: 2 }] },
            options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { color: 'rgba(255,255,255,0.1)' } }, y: { grid: { color: 'rgba(255,255,255,0.1)' } } } }
        });
    }

    // DP Chart
    const dpCtx = document.getElementById('dp-chart-trends');
    if (dpCtx && !dpChartTrends) {
        dpChartTrends = new Chart(dpCtx.getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'DP (mmH2O)', data: [], borderColor: '#8957e5', borderWidth: 2 }] },
            options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { color: 'rgba(255,255,255,0.1)' } }, y: { grid: { color: 'rgba(255,255,255,0.1)' } } } }
        });
    }
}

// Load data logger table
function loadDataLogger() {
    const tbody = document.getElementById('data-table');
    if (!tbody) return;

    database.ref('flow_data').orderByChild('timestamp').limitToLast(100).on('value', (snapshot) => {
        const data = [];
        snapshot.forEach((childSnapshot) => {
            data.push(childSnapshot.val());
        });

        data.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        tbody.innerHTML = data.map(row => `
            <tr>
                <td>${row.timestamp || '--'}</td>
                <td>${row.pressure ? row.pressure.toFixed(2) : '--'}</td>
                <td>${row.flow_rate ? row.flow_rate.toFixed(2) : '--'}</td>
                <td>${row.temperature ? row.temperature.toFixed(1) : '--'}</td>
                <td>${row.dp ? row.dp.toFixed(1) : '--'}</td>
                <td>${row.totalizer ? row.totalizer.toFixed(2) : '--'}</td>
            </tr>
        `).join('');

        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6">No data yet</td></tr>';
        }
    });
}

// Load calibration settings
function loadCalibrationData() {
    database.ref('calibration').on('value', (snapshot) => {
        const cal = snapshot.val() || {};

        const setVal = (id, val) => { if (document.getElementById(id)) document.getElementById(id).textContent = val || '--'; };

        setVal('dp-min', cal.dp_min);
        setVal('dp-max', cal.dp_max);
        setVal('press-min', cal.press_min);
        setVal('press-max', cal.press_max);
        setVal('temp-min', cal.temp_min);
        setVal('temp-max', cal.temp_max);
        setVal('pipe-dia', cal.pipe_dia);
        setVal('orifice-dia', cal.orifice_dia);
        setVal('fluid-density', cal.fluid_density);
    });
}

// Load Aegis logs from Firebase
function loadAegisLogs() {
    const logsRef = database.ref('aegis_logs');
    const tbody = document.getElementById('aegis-logs');

    logsRef.orderByChild('timestamp').limitToLast(50).on('value', (snapshot) => {
        const logs = [];
        snapshot.forEach((childSnapshot) => {
            logs.push({
                timestamp: childSnapshot.val().timestamp,
                message: childSnapshot.val().message,
                key: childSnapshot.key
            });
        });

        logs.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        tbody.innerHTML = logs.map(log => `
            <tr>
                <td>${log.timestamp}</td>
                <td>${escapeHtml(log.message)}</td>
            </tr>
        `).join('');

        if (logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="2">No logs yet</td></tr>';
        }
    });
}

// Load flow data from Firebase
function loadFlowData() {
    const flowRef = database.ref('flow_data');
    const tbody = document.getElementById('flow-data');

    flowRef.orderByChild('timestamp').limitToLast(100).on('value', (snapshot) => {
        const data = [];
        snapshot.forEach((childSnapshot) => {
            data.push(childSnapshot.val());
        });

        data.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        tbody.innerHTML = data.map(row => `
            <tr>
                <td>${row.timestamp}</td>
                <td>${row.pressure ? row.pressure.toFixed(2) : '--'}</td>
                <td>${row.flow_rate ? row.flow_rate.toFixed(2) : '--'}</td>
                <td>${row.temperature ? row.temperature.toFixed(1) : '--'}</td>
                <td>${row.dp ? row.dp.toFixed(1) : '--'}</td>
                <td>${row.totalizer ? row.totalizer.toFixed(2) : '--'}</td>
            </tr>
        `).join('');

        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6">No data yet</td></tr>';
        }

        updateFlowChart(data.reverse());
    });
}

// Update all charts with flow data
function updateFlowChart(data) {
    const labels = data.map(d => formatTime(d.timestamp));
    const flowRates = data.map(d => d.flow_rate || 0);
    const pressures = data.map(d => d.pressure || 0);
    const temps = data.map(d => d.temperature || 0);
    const dps = data.map(d => d.dp || 0);

    // Update main dashboard chart
    if (flowChartMain) {
        flowChartMain.data.labels = labels;
        flowChartMain.data.datasets[0].data = flowRates;
        flowChartMain.update();
    }

    // Update trends charts
    if (flowChartTrends) {
        flowChartTrends.data.labels = labels;
        flowChartTrends.data.datasets[0].data = flowRates;
        flowChartTrends.update();
    }

    if (pressureChartTrends) {
        pressureChartTrends.data.labels = labels;
        pressureChartTrends.data.datasets[0].data = pressures;
        pressureChartTrends.update();
    }

    if (tempChartTrends) {
        tempChartTrends.data.labels = labels;
        tempChartTrends.data.datasets[0].data = temps;
        tempChartTrends.update();
    }

    if (dpChartTrends) {
        dpChartTrends.data.labels = labels;
        dpChartTrends.data.datasets[0].data = dps;
        dpChartTrends.update();
    }
}

// Update dashboard stats in real-time
function updateDashboard() {
    const flowRef = database.ref('current_readings');

    flowRef.on('value', (snapshot) => {
        const data = snapshot.val();
        if (!data) return;

        document.getElementById('flow-rate').textContent = (data.flow_rate || 0).toFixed(2);
        document.getElementById('totalizer').textContent = (data.totalizer || 0).toFixed(2);
        document.getElementById('temperature').textContent = (data.temperature || 0).toFixed(1);
        document.getElementById('pressure').textContent = (data.pressure || 0).toFixed(2);
        document.getElementById('dp').textContent = (data.dp || 0).toFixed(1);
    });
}

// Utility functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', () => {
    updateOfflineStatus(navigator.onLine);
    updateDashboard();
    initMainDashboard();

    // Listen for new aegis logs and update immediately
    database.ref('aegis_logs').limitToLast(1).on('child_added', (snapshot) => {
        if (document.getElementById('aegis').style.display !== 'none') {
            loadAegisLogs();
        }
    });

    // Listen for new flow data
    database.ref('flow_data').limitToLast(1).on('child_added', (snapshot) => {
        if (document.getElementById('flow').style.display !== 'none') {
            loadFlowData();
        }
        updateDashboard();
        initTrendsTab();
    });
});