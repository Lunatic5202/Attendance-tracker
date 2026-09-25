
# 👤 Face Attendance Tracker

A smart **employee attendance management system** that uses **facial recognition** to automatically record employee check-ins and check-outs.

Instead of manually entering attendance, employees simply stand in front of a camera. The system identifies them and records their attendance automatically.

---

## ✨ Features

* 📷 **Face-based attendance**

  * Detect and recognize employees using a camera.
* 🟢 **Automatic Check-In**

  * First successful scan of the day records the employee's check-in time.
* 🔴 **Automatic Check-Out**

  * A later scan records the employee's check-out time.
* ⏱️ **Working Hours Calculation**

  * Automatically calculates the employee's total working duration.
* 👥 **Employee Registration**

  * Add new employees and register their facial data.
* 📊 **Attendance Records**

  * View daily attendance and employee history.
* 🖥️ **Admin Dashboard**

  * Manage employees and monitor attendance.
* 🔐 **Face Verification**

  * Matches a detected face against registered employees before creating an attendance record.
* 🚫 **Duplicate Scan Protection**

  * Prevents accidental repeated check-ins/check-outs.
* ⏳ **Check-Out Buffer**

  * A check-out scan is rejected until a minimum work buffer (default 4 hours, `MIN_CHECKOUT_HOURS`) has passed since check-in. Enforced on the server, not just the UI.
* 🔒 **Secure Kiosk + Admin Console**

  * Employees use the public kiosk with their face and **no accounts or passwords**. All employee data, logs, and face enrollment live behind a password-protected administrator console.
* 🗄️ **Encrypted at Rest**

  * Employee details, attendance timestamps, and face templates are encrypted at rest with authenticated encryption using `ATTENDANCE_MASTER_KEY`.

---

## 🧠 How It Works

```text
                    📷 Camera
                       │
                       ▼
                ┌──────────────┐
                │    OpenCV    │
                │ Face Detect  │
                └──────┬───────┘
                       │
                       ▼
              Face Recognition
                       │
                       ▼
                Employee Found?
                 /           \
               No             Yes
               │               │
               ▼               ▼
          Unknown Face     Check Attendance
                               │
                    ┌──────────┴──────────┐
                    │                     │
              No attendance          Checked in
                 today                 already
                    │                     │
                    ▼                     ▼
                CHECK-IN              CHECK-OUT
                    │                     │
                    └──────────┬──────────┘
                               ▼
                          💾 Database
                               │
                               ▼
                         📊 Dashboard
```

### Attendance Logic

The system determines the action automatically:

```text
First scan of the day
        ↓
    CHECK-IN
        ↓
Employee works
        ↓
Second scan
        ↓
Has the check-out
buffer (default 4h)
passed since check-in?
   /                 \
 No                   Yes
  │                    │
  │               CHECK-OUT
  │                    │
Rejected with         Calculate
"unlocks at" time   working hours
```

Employees do not need to manually select **Check In** or **Check Out**.

---

## 🛠️ Tech Stack

### Backend / Recognition

* **Python**
* **FastAPI** backend with signed, HttpOnly admin session cookies
* **OpenCV** Haar cascade (detection) + LBPH (recognition)
* **cryptography** (Fernet) authenticated encryption for data at rest

### Database

* **PostgreSQL** — set `DATABASE_URL`. Required for ephemeral hosts (Render free, Heroku, most PaaS) because the container filesystem is wiped on every deploy, which deletes local data.
* **SQLite** (default) — single-file, zero-config. Fine for a kiosk that runs on a machine you control, where the data directory persists on its own.

### Frontend

* **React**
* HTML / CSS / JavaScript

### Hardware

* Webcam / USB camera
* Computer or attendance kiosk

---

## 📁 Project Structure

```text
face-attendance-tracker/
│
├── backend/
│   ├── main.py
│   ├── camera.py
│   ├── face_recognition.py
│   ├── attendance.py
│   └── database.py
│
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
│
├── data/
│   └── .gitkeep
│
├── requirements.txt
├── .gitignore
└── README.md
```

> The project structure may change as development progresses.

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/face-attendance-tracker.git
cd face-attendance-tracker
```

### 2. Create a Python virtual environment

```bash
python -m venv venv
```

Activate it:

**Linux/macOS**

```bash
source venv/bin/activate
```

**Windows**

```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the application

```bash
python main.py
```

---

## 👤 Employee Registration

Before an employee can use the attendance system, their facial data needs to be registered.

Example flow:

```text
Employee Registration
        │
        ▼
Enter Employee Details
        │
        ▼
Capture Face
        │
        ▼
Generate Face Embedding
        │
        ▼
Store Employee Record
        │
        ▼
Employee Ready ✅
```

Example employee record:

```text
Employee ID : EMP001
Name        : John Doe
Department  : Development
Face Data   : Registered
```

---

## 📅 Attendance Record

Each attendance entry can contain information such as:

| Field        | Description                |
| ------------ | -------------------------- |
| Employee ID  | Unique employee identifier |
| Date         | Attendance date            |
| Check-In     | Time employee arrived      |
| Check-Out    | Time employee left         |
| Hours Worked | Total working duration     |
| Status       | Present / Late / etc.      |

Example:

```text
Employee: EMP001
Date:     2026-09-17
Check-In: 09:31 AM
Check-Out: 06:12 PM
Worked:   8h 41m
Status:   Present
```

---

## 🔒 Privacy & Security

Facial recognition involves **biometric information**, so the system should be designed with privacy and security in mind.

Recommended practices:

* Do not publicly expose employee facial data.
* Store facial embeddings securely.
* Restrict access to attendance records.
* Use encryption where appropriate.
* Obtain required employee consent/notice.
* Provide a fallback attendance method when facial recognition fails.
* Follow applicable privacy and employment laws for the deployment location.
* Avoid storing raw face images unless they are genuinely required.

---

## 🔐 Access Model & Deployment

The tracker has exactly two experiences, so nothing depends on employees remembering passwords or keys.

| Who                | How they sign in               | What they can do                                   |
| ------------------ | ------------------------------ | -------------------------------------------------- |
| **Employees**      | Face scan at the public kiosk  | Check in / check out only — no data is exposed     |
| **Administrators** | Password on the admin console  | Enroll faces, manage employees, view all logs      |

* The kiosk scan route is the only public API. It only creates attendance for an **enrolled, active, recognized** face.
* **Enrollment is never public** — only an administrator can register an employee and capture their face, so strangers can't add themselves to the system.
* Employee logs, statistics, departments, employee records, and manual overrides all return `401` without a valid administrator session.
* An admin session lasts `ADMIN_SESSION_TTL` (default 8h) and is tracked with a signed, HttpOnly cookie. Use the **Admin · Logout** button when done.

### First-time deployment

1. Install dependencies and copy the example config:

   ```bash
   pip install -r requirements.txt
   cp .env.example .env
   ```

2. Edit `.env`:

   * `ADMIN_PASSWORD` — choose a strong random value. This is the **only** password in the system; keep it with the company owner(s), not printed in the office.
   * `ATTENDANCE_MASTER_KEY` — generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. It encrypts all employee data and face templates at rest. Back it up; losing it makes encrypted data unrecoverable.
   * `MIN_CHECKOUT_HOURS` — the minimum time between check-in and check-out (the work buffer). Default `4`.
   * `ALLOWED_ORIGINS` — the exact browser origin (your kiosk/server hostname). Never `*`.
   * `ENVIRONMENT=production` to enable secure cookies.

3. Build the frontend once, then start:

   ```bash
   cd frontend && npm install && npm run build && cd ..
   python main.py
   ```

4. Open the app, go to **Employees → Register Employee**, add each person, and **Enroll** their face from the admin console. Verify one real check-in followed by an early rejected check-out before opening the kiosk to staff.

> The app reads `.env` automatically at startup. After changing `.env`, restart the service.

### Using PostgreSQL

Hosting providers with an ephemeral filesystem (Render's free tier, Heroku, and
most other PaaS) delete the container on every deploy, so the default SQLite file
is lost each time. Point `DATABASE_URL` at a managed PostgreSQL database and the
attendance history survives redeploys.

1. Create a free database (for example Neon or Supabase) and copy its
   **pooled** connection string — the one ending in `-pooler`. The app holds a
   small connection pool open, so the pooled endpoint avoids exhausting the
   provider's connection limit.
2. Set it in the host's environment as `DATABASE_URL`, and set `PG_POOL_MAX` to a
   small number such as `5` on free tiers.
3. Restart. `GET /api/health` reports `"database": "postgres"` once it is
   connected. Tables are created automatically on first start.

Leave `DATABASE_URL` unset to keep using SQLite. If `DATABASE_URL` is set but
unreachable, the app fails to start rather than silently falling back to an empty
local database. Keep `ATTENDANCE_MASTER_KEY` unchanged for the life of the
database: every stored field is encrypted with it, and changing it makes existing
rows unreadable.

---

## 📊 Microsoft 365 / Excel Sync + Encrypted Backup *(optional)*

Push attendance records to a real **Excel** workbook in **OneDrive for Business** every day, and take **encrypted backups** of the whole database (including face templates) so data survives cloud restarts.

* Requires a **Microsoft 365 work/school account** (e.g. Business Basic) — the consumer `@outlook.com` plan does **not** expose the Excel/OneDrive APIs.
* Uses **app-only (client credentials)** auth via an Entra ID app, so no refresh token is stored on the server (important on ephemeral cloud disk).
* **Face templates never leave the server unencrypted** — they stay Fernet-encrypted under `ATTENDANCE_MASTER_KEY`. Excel only ever receives the *attendance records* and an *employee roster* (with a "Face Enrolled" yes/no column). The daily backup archive is the only place full face data goes, and it is encrypted a second time before upload.

### Where to get the API keys (one-time, ~10 min)

1. Sign in to [portal.azure.com](https://portal.azure.com) with your **Microsoft 365 admin/owner** account.
2. **Microsoft Entra ID → App registrations → New registration**:
   * Name: `Attendance Tracker`
   * *Supported account types*: **Accounts in this organizational directory only**
   * Register.
3. On the app's **Overview** page copy:
   * **Application (client) ID** → `MS_CLIENT_ID`
   * **Directory (tenant) ID** → `MS_TENANT_ID`
4. **Certificates & secrets → Client secrets → New client secret** → copy the **Value** immediately → `MS_CLIENT_SECRET`.
5. **API permissions → Add a permission → Microsoft Graph → Application permissions** → add **`Files.ReadWrite.All`** → **Grant admin consent** (you are the admin, so it applies instantly).
6. `MS_DRIVE_UPN` = the **email/UPN** of the OneDrive for Business account that should receive the exports (e.g. `you@yourcompany.com`). That user just needs a normal Business Basic license.

### Environment variables

| Variable             | Purpose                                             | Example |
| -------------------- | --------------------------------------------------- | ------- |
| `MS_CLIENT_ID`       | Entra app (client) ID (step 3)                      | `62cd…` |
| `MS_CLIENT_SECRET`   | Entra app client secret (step 4)                    | `abc…`  |
| `MS_TENANT_ID`       | Entra directory (tenant) ID (step 3)                | `e1d…`  |
| `MS_DRIVE_UPN`       | OneDrive owner's email (step 6)                     | `owner@company.com` |
| `MS_FOLDER`          | OneDrive folder for workbook + backups              | `Attendance Tracker` |
| `MS_EXCEL_FILENAME`  | Excel workbook name                                 | `Attendance.xlsx` |
| `MS_SYNC_TIME`       | Daily sync time in **UTC** (`HH:MM`)                | `23:30` |
| `MS_BACKUP_KEEP`     | Encrypted backups to keep (older ones pruned)       | `14` |
| `MS_EXCEL_ENABLED`   | Set `0` to disable the Excel push only              | `1` |
| `MS_BACKUP_ENABLED`  | Set `0` to disable the encrypted backup only        | `1` |

### How it works

* A background task runs once per day at `MS_SYNC_TIME` (UTC) and once shortly after every boot.
* **Excel sync** regenerates a full `.xlsx` (sheets: `Summary`, `Attendance`, `Employees`) and overwrites `MS_FOLDER/MS_EXCEL_FILENAME` in the owner's OneDrive. It is one-way — edits you make in Excel are overwritten on the next push.
* **Encrypted backup** snapshots the SQLite DB (consistently, via the sqlite backup API), bundles it with the face-template files, encrypts the whole archive with `ATTENDANCE_MASTER_KEY` via Fernet, and uploads to `MS_FOLDER/backups/`. Old backups are pruned to `MS_BACKUP_KEEP`.
* The admin dashboard shows connection status and **Sync to Excel** / **Encrypted Backup** buttons (`POST /api/excel/sync`, `POST /api/backup/now`).

---

## 🛡️ Anti-Spoofing

A future version will include **liveness detection** to reduce attempts to authenticate using:

* 📱 Photos
* 🖼️ Printed images
* 📺 Screens displaying an employee's face
* 🎭 Other simple presentation attacks

Planned flow:

```text
Face Detected
     ↓
Liveness Check
     ↓
Real Person?
   /       \
 No         Yes
 │           │
Reject    Recognize
             │
             ▼
        Record Attendance
```

---

## 🗺️ Roadmap

### Phase 1 — Core System

* [x] Project setup
* [x] Webcam integration
* [x] Face detection
* [x] Employee registration
* [x] Face recognition
* [x] Automatic check-in
* [x] Automatic check-out

### Phase 2 — Attendance Management

* [x] SQLite database
* [x] Attendance history
* [x] Working-hours calculation
* [x] Duplicate scan prevention
* [x] Employee management

### Phase 3 — Dashboard

* [x] React dashboard
* [x] Daily attendance view
* [x] Employee search
* [x] Attendance filters
* [x] Reports/export

### Phase 4 — Security

* [x] Secure biometric storage
* [x] Admin authentication
* [x] Role-based access (kiosk vs admin console)
* [ ] Liveness detection

### Phase 5 — Deployment

* [ ] Kiosk mode
* [ ] PostgreSQL support
* [ ] Multi-device support
* [ ] Cloud deployment
* [ ] Backup and recovery

---

## ⚠️ Current Status

🚧 **Under Development**

This project is currently being developed and features may change as the system evolves.

---

## 🤝 Contributing

Contributions, ideas, and improvements are welcome.

1. Fork the repository
2. Create a feature branch

```bash
git checkout -b feature/your-feature
```

3. Commit your changes

```bash
git commit -m "Add your feature"
```

4. Push the branch

```bash
git push origin feature/your-feature
```

5. Open a Pull Request

---

## 📜 License

This project is licensed under the **MIT License**.

See [`LICENSE`](LICENSE) for more information.

---

## 👨‍💻 Author

**Lunatic Layman**

Built with ❤️ using Python, OpenCV, and modern web technologies.

---

⭐ If you find this project useful, consider giving the repository a star!
