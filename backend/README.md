# Smart Attendance & Environment Monitoring API

A lightweight, robust Flask-based REST API designed for hardware-integrated student attendance tracking and environmental monitoring. It features an automated, background Machine Learning system (Isolation Forest) that actively detects suspicious login behavior based on historical student footprints.

## Features

* **Dual-Entry Attendance**: Supports both hardware RFID scanning and manual form entries.
* **Environmental Logging**: Tracks temperature and humidity data from IoT sensors.
* **AI Anomaly Detection**: Automatically analyzes attendance patterns in the background to flag suspicious activities (e.g., rapid double-logging, unusual shifts to manual entry).
* **Security**: Payload limits and HTTP Header API Key enforcement for device-facing endpoints.

---

# Installation & Setup

## 1. Clone the Repository

Clone the repository and navigate to the project directory.

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

> Ensure `pandas` and `scikit-learn` are included in your requirements for the ML features.

## 3. Configure the Environment

Create a `.env` file in the root directory:

```env
API_KEY=HatdogNiAljur123
DB_FILE=system.db
MAX_PAYLOAD=2048
PORT=5000
ALLOWLIST_FILE=allowlist.csv
```

## 4. Run the Server

```bash
python app.py
```

The database tables will automatically initialize on the first run.

---

# Database Tables

The SQLite database (`system.db`) utilizes WAL mode for concurrent reads and writes.

## users

Registered user profiles mapped to RFID UIDs.

| Column     | Type      | Description                              |
| ---------- | --------- | ---------------------------------------- |
| uid        | TEXT (PK) | Unique Hexadecimal RFID Tag (8–14 chars) |
| name       | TEXT      | Full name of the student/staff           |
| id_number  | TEXT      | Official School ID string                |
| photo_path | TEXT      | Path to user image                       |

---

## attendance

Main log for all entry events.

| Column     | Type | Description                             |
| ---------- | ---- | --------------------------------------- |
| timestamp  | TEXT | UTC ISO-8601 string                     |
| name       | TEXT | Name of the attendee                    |
| id_number  | TEXT | Official School ID string               |
| entry_type | TEXT | `"RFID"` or `"Manual"`                  |
| purpose    | TEXT | Reason for manual entry (NULL for RFID) |

---

## environment

Sensor data logs.

| Column      | Type | Description                                 |
| ----------- | ---- | ------------------------------------------- |
| timestamp   | TEXT | UTC ISO-8601 string                         |
| temperature | REAL | Temperature in Celsius (-50.0 to 100.0)     |
| humidity    | REAL | Relative humidity percentage (0.0 to 100.0) |

---

## anomalies

Logs generated automatically by the background machine learning thread.

| Column      | Type         | Description                            |
| ----------- | ------------ | -------------------------------------- |
| id          | INTEGER (PK) | Auto-incrementing identifier           |
| timestamp   | TEXT         | UTC ISO-8601 when the anomaly occurred |
| id_number   | TEXT         | Student ID associated with the anomaly |
| description | TEXT         | Description of the flagged behavior    |

---

# API Endpoints

> **Global Security Note:** Endpoints interacting with hardware (`/scan`, `/manual`, `/environment`) require the `X-API-Key` header. The dashboard endpoint (`/status`) does not.

---

## POST /scan

Triggered by the hardware RFID scanner.

Logs attendance and triggers a background ML check.

### Headers

```http
X-API-Key: <your_key>
Content-Type: application/json
```

### Payload

```json
{
  "uid": "A1B2C3D4"
}
```

### Success (200 OK)

Returns the user profile data.

### Errors

* 400 Invalid UID
* 404 User Not Found

---

## POST /manual

Triggered by the software UI for users without their RFID cards.

Logs attendance and triggers a background ML check.

### Headers

```http
X-API-Key: <your_key>
Content-Type: application/json
```

### Payload

```json
{
  "name": "Juan dela Cruz",
  "id": "20240072-E",
  "purpose": "Library Visit"
}
```

> `id` must be a non-empty alphanumeric string.

### Success (201 Created)

```json
{
  "status": "Success"
}
```

### Errors

* 400 Invalid Input

---

## POST /environment

Triggered by the hardware IoT sensors.

### Headers

```http
X-API-Key: <your_key>
Content-Type: application/json
```

### Payload

```json
{
  "temperature": 26.5,
  "humidity": 60.2
}
```

### Success (201 Created)

```json
{
  "status": "Success"
}
```

### Errors

* 400 Invalid Sensor Values

---

## GET /status

Public dashboard endpoint used to fetch the current state of the system.

### Headers

None required.

### Success (200 OK)

```json
{
  "environment": {
    "timestamp": "2026-06-16T23:50:22+00:00",
    "temperature": 27.5,
    "humidity": 65.0
  },
  "recent_attendance": [
    {
      "timestamp": "2026-06-16T23:50:18+00:00",
      "name": "Juan dela Cruz",
      "id_number": "20240001",
      "entry_type": "Manual",
      "purpose": "Library Visit"
    }
  ],
  "recent_anomalies": [
    {
      "id_number": "20240072-E",
      "timestamp": "2026-06-16T17:05:19+00:00",
      "description": "Suspicious: Unusual shift to manual entry. Possible lost/broken RFID."
    }
  ]
}
```

---

# Machine Learning Integration (Isolation Forest)

The system features an automated tracking system that cross-references individual student habits against global database patterns.

## How It Works

1. A background thread silently executes after every successful `/scan` or `/manual` entry.
2. The model requires a minimum of **50 attendance records** in the database to establish a baseline. Before this threshold, anomaly checks are bypassed.
3. The model evaluates four core vectors:

   * **Time of day** (`hour`)
   * **Day of the week** (`day_of_week`)
   * **Entry method** (`entry_numeric`)
   * **Frequency** (`time_diff`)

## Flagged Behaviors

### Rapid Dual Logging

A manual entry occurs within 1–2 minutes of an RFID scan under the same ID.

### Sudden Method Shifts

A user with a strict history of RFID usage suddenly shifts to manual entry.

### Time Outliers

Entries recorded significantly outside normal student traffic hours.
