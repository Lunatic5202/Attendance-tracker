
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
   CHECK-OUT
        ↓
Calculate working hours
```

Employees do not need to manually select **Check In** or **Check Out**.

---

## 🛠️ Tech Stack

### Backend / Recognition

* **Python**
* **OpenCV**
* Face recognition / face embedding model
* **FastAPI** *(planned/optional)*

### Database

* **SQLite** for development
* **PostgreSQL** for production

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

* [ ] Liveness detection
* [ ] Secure biometric storage
* [ ] Admin authentication
* [ ] Role-based access

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
