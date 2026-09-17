"""FastAPI application for the Face Attendance Tracker.

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

import base64
import io
import os
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import attendance, database as db
from backend.attendance import AttendanceError
from backend.face_recognition import engine

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
DATA_DIR = BASE_DIR / "data"

app = FastAPI(title="Face Attendance Tracker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    department: str = "General"
    role: str = ""
    email: str = ""
    phone: str = ""
    face_image: str | None = None  # base64 (data URL or raw)


class EmployeeUpdate(BaseModel):
    name: str | None = None
    department: str | None = None
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool | None = None


class ScanRequest(BaseModel):
    image: str | None = None  # base64 frame from the browser camera
    employee_id: str | None = None  # explicit id, only honoured by demo engine


class ManualRequest(BaseModel):
    employee_id: str
    action: str = Field(pattern="^(in|out)$")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _decode_image(payload: str | None, upload: UploadFile | None = None):
    """Decode a base64 payload or an uploaded file into a numpy BGR frame."""
    raw = None
    if upload is not None:
        raw = upload.file.read()
    elif payload:
        if payload.startswith("data:"):
            payload = payload.split(",", 1)[1]
        try:
            raw = base64.b64decode(payload)
        except Exception:
            raise HTTPException(400, "Invalid base64 image payload.")
    if raw is None:
        return None
    if not raw:
        raise HTTPException(400, "Empty image payload.")
    import cv2

    arr = np.frombuffer(raw, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(400, "Image could not be decoded.")
    return frame


def _employee_list():
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM employees ORDER BY created_at DESC").fetchall()
    return [{**dict(r), "face_enrolled": bool(r["face_available"])} for r in rows]


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "face_engine": engine.name}


# --------------------------------------------------------------------------
# Employees
# --------------------------------------------------------------------------
@app.get("/api/employees")
def list_employees(q: str | None = None):
    employees = _employee_list()
    if q:
        employees = [
            e for e in employees
            if q.lower() in e["name"].lower()
            or q.lower() in e["department"].lower()
            or q.lower() in e["id"].lower()
        ]
    return employees


@app.post("/api/employees")
def create_employee(body: EmployeeCreate):
    with db.get_conn() as conn:
        emp_id = db.next_employee_id(conn)
        conn.execute(
            """
            INSERT INTO employees (id, name, department, role, email, phone, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (emp_id, body.name, body.department, body.role, body.email, body.phone, db.now_str()),
        )
    new = {"id": emp_id, "name": body.name, "department": body.department,
           "role": body.role, "email": body.email, "phone": body.phone,
           "face_enrolled": False, "is_active": 1}
    if body.face_image:
        try:
            frame = _decode_image(body.face_image)
            _enroll_face(emp_id, frame)
            new["face_enrolled"] = True
        except HTTPException:
            pass
    return new


@app.get("/api/employees/{employee_id}")
def get_employee(employee_id: str):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Employee not found.")
    return {**dict(row), "face_enrolled": bool(row["face_available"])}


@app.patch("/api/employees/{employee_id}")
def update_employee(employee_id: str, body: EmployeeUpdate):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Employee not found.")
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return dict(row)
        sets, vals = [], []
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            vals.append(value)
        vals.append(employee_id)
        conn.execute(f"UPDATE employees SET {', '.join(sets)} WHERE id = ?", vals)
    return get_employee(employee_id)


def _remove_face(label: int | None) -> None:
    if label is None:
        return
    faces_dir = DATA_DIR / "faces"
    if not faces_dir.exists():
        return
    for p in faces_dir.iterdir():
        if p.is_file() and (p.stem == str(label) or p.stem.startswith(f"{label}.")):
            p.unlink(missing_ok=True)


@app.delete("/api/employees/{employee_id}")
def delete_employee(employee_id: str):
    with db.get_conn() as conn:
        row = conn.execute("SELECT face_label FROM employees WHERE id = ?", (employee_id,)).fetchone()
        label = row["face_label"] if row else None
        conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
    _remove_face(label)
    return {"deleted": employee_id}


def _enroll_face(employee_id: str, frame):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Employee not found.")
        label = row["face_label"]
        if label is None:
            max_label = conn.execute(
                "SELECT MAX(face_label) AS m FROM employees"
            ).fetchone()["m"]
            label = (max_label or 0) + 1
            conn.execute(
                "UPDATE employees SET face_label = ? WHERE id = ?", (label, employee_id)
            )
        conn.commit()
    ok = engine.enroll(label, frame)
    if not ok:
        raise HTTPException(400, "No face detected in the provided image.")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE employees SET face_available = 1 WHERE id = ?", (employee_id,)
        )


@app.post("/api/employees/{employee_id}/face")
async def enroll_face(employee_id: str, file: UploadFile | None = File(None)):
    frame = _decode_image(None, file) if file else None
    if frame is None:
        raise HTTPException(400, "Provide an image file to enroll the face.")
    _enroll_face(employee_id, frame)
    return {"detail": "Face enrolled."}


@app.get("/api/employees/{employee_id}/face")
def face_status(employee_id: str):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT face_available, face_label FROM employees WHERE id = ?",
            (employee_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Employee not found.")
    return {"employee_id": employee_id, "face_enrolled": bool(row["face_available"])}


@app.get("/api/departments")
def departments():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT department, COUNT(*) AS count FROM employees GROUP BY department"
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Attendance
# --------------------------------------------------------------------------
@app.post("/api/attendance/scan")
def scan_attendance(body: ScanRequest):
    """Auto check-in / check-out driven by a recognised face."""
    if engine.name == "opencv":
        frame = _decode_image(body.image)
        if frame is None:
            raise HTTPException(400, "No image frame provided.")
        with db.get_conn() as conn:
            candidates = [
                r["face_label"]
                for r in conn.execute(
                    "SELECT face_label FROM employees WHERE is_active = 1 AND face_label IS NOT NULL"
                ).fetchall()
            ]
        result = engine.recognize(frame, candidates=candidates)
        if result is None:
            return JSONResponse({"action": "UNKNOWN", "message": "Face not recognised."})
        label = result[0]
        with db.get_conn() as conn:
            emp = conn.execute(
                "SELECT * FROM employees WHERE face_label = ?", (label,)
            ).fetchone()
        employee_id = emp["id"]
    else:
        employee_id = body.employee_id
        if not employee_id:
            # Demo mode without a camera: allow a simulated scan.
            return JSONResponse(
                {
                    "action": "DEMO_NEEDS_EMPLOYEE",
                    "message": "An employee_id is required in demo mode.",
                }
            )

    try:
        result = attendance.record_scan(employee_id, source="face")
        return result
    except AttendanceError as exc:
        status_code = 409 if exc.code == "duplicate_scan" else 422
        return JSONResponse(
            {"action": exc.code.upper(), "message": exc.message, **exc.info},
            status_code=status_code,
        )


@app.post("/api/attendance/manual")
def manual_attendance(body: ManualRequest):
    try:
        return attendance.record_scan(body.employee_id, source=body.action)
    except AttendanceError as exc:
        return JSONResponse({"action": exc.code.upper(), "message": exc.message}, status_code=409)


@app.get("/api/attendance")
def get_attendance(date: str | None = Query(None), employee_id: str | None = None):
    if employee_id:
        return attendance.get_by_employee(employee_id)
    return attendance.get_by_date(date or db.today_str())


@app.get("/api/stats")
def stats(date: str | None = None):
    return attendance.summary(date)


# --------------------------------------------------------------------------
# Static frontend (production)
# --------------------------------------------------------------------------
if FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


def run() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)


if __name__ == "__main__":
    run()