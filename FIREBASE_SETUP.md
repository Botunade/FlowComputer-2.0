# Firebase Integration Setup Guide

## Overview
This guide explains how to connect FlowComputer2.0 to Firebase for remote monitoring and data logging.

## Prerequisites

1. **Firebase Project Created**
   - Go to https://console.firebase.google.com/
   - Create or select your project
   - Enable Realtime Database

2. **Database Security Rules**
   In Firebase Console > Realtime Database > Rules, set:
   ```json
   {
     "rules": {
       ".read": true,
       ".write": "auth != null"
     }
   }
   ```

## Setup Steps

### 1. Get Firebase Credentials

**Option A: Using Database Secret (simpler)**
- Go to Project Settings > Service Accounts
- Click "Generate new private key" and download the JSON file
- Extract `databaseURL` and use the private key in your config

**Option B: Using Firebase CLI**
```bash
firebase login
firebase init database
```

### 2. Configure Local Settings

Copy the example config file:
```bash
copy firebase_config.json.example firebase_config.json
```

Edit `firebase_config.json` with your values:
```json
{
  "firebase_url": "https://your-project-id.firebaseio.com",
  "firebase_token": "your_database_secret_or_token"
}
```

### 3. Install Dependencies
```bash
pip install python-firebase requests
```

### 4. Start the Application

The application will automatically:
- Sync Aegis AI observations to Firebase
- Upload flow data in real-time
- Provide offline buffering when internet is unavailable

## Database Structure

Firebase Realtime Database will have these paths:

```
/
├── aegis_logs/
│   ├── -Nk123abc...
│   │   ├── timestamp: "2026-09-21 10:30:00"
│   │   └── message: "Orifice plates experience..."
│   └── ...
├── flow_data/
│   ├── -Nk123def...
│   │   ├── timestamp: "2026-09-21 10:30:00"
│   │   ├── flow_rate: 123.45
│   │   ├── pressure: 2.45
│   │   ├── temperature: 25.3
│   │   ├── dp: 50.2
│   │   └── totalizer: 1234.56
│   └── ...
└── current_readings/
    ├── flow_rate: 123.45
    ├── pressure: 2.45
    ├── temperature: 25.3
    ├── dp: 50.2
    └── totalizer: 1234.56
```

## Deployment to Raspberry Pi

1. Copy the configuration files to your Raspberry Pi:
```bash
scp -r ./* pi@raspberrypi:/path/to/FlowComputer2.0/
```

2. On the Raspberry Pi, install dependencies:
```bash
pip install -r requirements.txt
```

3. Ensure internet connectivity for Firebase sync

## Web Dashboard Configuration

Edit `web/app.js` and replace placeholder values:

```javascript
const firebaseConfig = {
    apiKey: "YOUR_API_KEY",        // From Firebase Console > Project Settings
    authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
    databaseURL: "https://YOUR_PROJECT_ID.firebaseio.com",
    projectId: "YOUR_PROJECT_ID",
    storageBucket: "YOUR_PROJECT_ID.appspot.com",
    messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
    appId: "YOUR_APP_ID"
};
```

## Firebase Hosting Setup (Optional)

To deploy the web dashboard:

1. In Firebase Console, go to Hosting
2. In your local project:
```bash
firebase init hosting
```

3. Set public directory to `public`
4. Deploy:
```bash
firebase deploy
```

## Troubleshooting

**Connection Issues:**
- Verify database URL is correct
- Check firewall/Network settings on Raspberry Pi
- Verify Firebase token is valid

**Data Not Syncing:**
- Check `datalog.db` exists and has data
- Run `python firebase_sync.py` to test connection
- Check Firebase database rules

**Offline Mode:**
- Data is buffered locally and will sync when internet returns
- Check status in application logs

## Web Dashboard Features

- **Real-time flow monitoring** - Live updates every few seconds
- **Aegis Logs** - Historical AI observations
- **Flow Data History** - Trend charts and historical data
- **Dashboard Stats** - Current readings at a glance