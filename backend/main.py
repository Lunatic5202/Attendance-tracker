"""FastAPI application for the Face Attendance Tracker.

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv  # noqa: E402  (must run before backend imports)

load_dotenv(BASE_DIR / ".env")

import base64
import io

import numpy as np
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import attendance, backup_sync, database as db, excel_sync, onedrive, scheduler, security
from backend import seed_data
from backend.attendance import AttendanceError
from backend.face_recognition import engine
from backend.limits import scan_limiter
from backend.store import store
from backend.security import (
    SESSION_COOKIE,
    admin_password_matches,
    create_session,
    public_attendance,
    public_employee,
    security_status,
    verify_session,
)

FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
DATA_DIR = BASE_DIR / "data"

_MAX_IMAGE_BYTES = 8_000_000

app = FastAPI(title="Face Attendance Tracker", version="0.1.0")

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _cache_headers(request: Request, call_next):
    """Never cache the SPA index.html (its hashed asset names change on every
    build, so a cached copy points at deleted bundles -> blank white page).
    Assets under /assets are content-hashed, so cache them forever."""
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif response.status_code == 200 and "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.on_event("startup")
def _startup() -> None:
    store.init()
    seed_data.seed_employees(engine)
    scheduler.spawn()


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    department: str = "General"
    role: str = ""
    email: str = ""
    phone: str = ""
    face_image: str | None = Field(None, max_length=4_000_000)  # base64 (data URL or raw)


class EmployeeUpdate(BaseModel):
    name: str | None = None
    department: str | None = None
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool | None = None


class ScanRequest(BaseModel):
    image: str | None = Field(None, max_length=4_000_000)  # base64 frame from the browser camera
    employee_id: str | None = None  # explicit id, only honoured by demo engine


class ManualRequest(BaseModel):
    employee_id: str
    action: str = Field(pattern="^(in|out)$")


class AdminLogin(BaseModel):
    password: str = Field(min_length=1, max_length=256)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _decode_image(payload: str | None, upload: UploadFile | None = None):
    """Decode a base64 payload or an uploaded file into a numpy BGR frame."""
    raw = None
    if upload is not None:
        raw = upload.file.read(_MAX_IMAGE_BYTES + 1)
        if len(raw) > _MAX_IMAGE_BYTES:
            raise HTTPException(413, "Image file too large (max 8 MB).")
    elif payload:
        if len(payload) > 4_000_000:
            raise HTTPException(413, "Image payload too large.")
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
    return [public_employee(r) for r in store.employees()]


def require_admin(admin_cookie: str | None = Cookie(None, alias=SESSION_COOKIE)):
    if not verify_session(admin_cookie):
        raise HTTPException(401, "Administrator access required.")
    return True


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "face_engine": engine.name,
        "database": "postgres" if db.using_postgres() else "sqlite",
        **security_status(),
    }


@app.post("/api/admin/login")
def admin_login(body: AdminLogin, response: Response):
    if not os.getenv("ADMIN_PASSWORD"):
        raise HTTPException(
            503,
            "The administrator password is not configured. "
            "Set ADMIN_PASSWORD in the server environment and restart.",
        )
    if not admin_password_matches(body.password):
        raise HTTPException(401, "Invalid administrator password.")
    response.set_cookie(
        SESSION_COOKIE,
        create_session(),
        httponly=True,
        secure=os.getenv("ENVIRONMENT", "development").lower() == "production",
        samesite="strict",
        max_age=int(os.getenv("ADMIN_SESSION_TTL", "28800")),
    )
    return {"authenticated": True}


@app.post("/api/admin/logout")
def admin_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"authenticated": False}


@app.get("/api/admin/session")
def admin_session(_: bool = Depends(require_admin)):
    return {"authenticated": True}


# --------------------------------------------------------------------------
# Employees
# --------------------------------------------------------------------------
@app.get("/api/employees")
def list_employees(q: str | None = None, _: bool = Depends(require_admin)):
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
def create_employee(body: EmployeeCreate, _: bool = Depends(require_admin)):
    emp_id = store.next_employee_id()
    store.insert_employee(
        {
            "id": emp_id,
            **{
                key: security.encrypt_text(value)
                for key, value in {
                    "name": body.name,
                    "department": body.department,
                    "role": body.role,
                    "email": body.email,
                    "phone": body.phone,
                }.items()
            },
            "created_at": security.encrypt_text(db.now_str()),
        }
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
def get_employee(employee_id: str, _: bool = Depends(require_admin)):
    row = store.get_employee(employee_id)
    if row is None:
        raise HTTPException(404, "Employee not found.")
    return public_employee(row)


@app.patch("/api/employees/{employee_id}")
def update_employee(employee_id: str, body: EmployeeUpdate, _: bool = Depends(require_admin)):
    row = store.get_employee(employee_id)
    if row is None:
        raise HTTPException(404, "Employee not found.")
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return public_employee(row)
    sets = {}
    for key, value in fields.items():
        if key in {"name", "department", "role", "email", "phone"}:
            value = security.encrypt_text(value)
        sets[key] = value
    return public_employee(store.update_employee(employee_id, sets))


def _remove_face(label: int | None) -> None:
    if label is None:
        return
    faces_dir = DATA_DIR / "faces"
    if not faces_dir.exists():
        return
    for p in faces_dir.iterdir():
        if p.is_file() and p.stem in {str(label), f"{label}.0"}:
            p.unlink(missing_ok=True)
        elif p.is_file() and p.stem.startswith(f"{label}."):
            p.unlink(missing_ok=True)
        elif p.is_file() and p.stem.startswith(f"{label}-"):
            p.unlink(missing_ok=True)


@app.delete("/api/employees/{employee_id}")
def delete_employee(employee_id: str, _: bool = Depends(require_admin)):
    row = store.delete_employee(employee_id)
    _remove_face(row["face_label"] if row else None)
    return {"deleted": employee_id}


def _allocate_face_label(employee_id: str) -> int:
    row = store.get_employee(employee_id)
    if row is None:
        raise HTTPException(404, "Employee not found.")
    label = row["face_label"]
    if label is None:
        label = (store.max_face_label() or 0) + 1
        store.set_face_label(employee_id, label)
    return label


def _enroll_face(employee_id: str, frame):
    label = _allocate_face_label(employee_id)
    ok = engine.enroll(label, frame)
    if not ok:
        raise HTTPException(400, "No face detected in the provided image.")
    store.set_face_available(employee_id, 1)


@app.post("/api/employees/{employee_id}/face")
async def enroll_face(employee_id: str, file: UploadFile | None = File(None), _: bool = Depends(require_admin)):
    frame = _decode_image(None, file) if file else None
    if frame is None:
        raise HTTPException(400, "Provide an image file to enroll the face.")
    _enroll_face(employee_id, frame)
    return {"detail": "Face enrolled."}


@app.post("/api/employees/{employee_id}/face/upload")
async def upload_enrollment_face(
    employee_id: str,
    files: list[UploadFile] = File(...),
    _: bool = Depends(require_admin),
):
    """First-enrollment only: enroll a new face from uploaded picture(s).

    Upload is deliberately refused once a face exists, so the trusted live
    camera path is used for re-enrolments instead.
    """
    row = store.get_employee(employee_id)
    if row is None:
        raise HTTPException(404, "Employee not found.")
    if row["face_available"]:
        raise HTTPException(
            409,
            "Face already enrolled — pictures can only be used for the first enrollment.",
        )
    if not files:
        raise HTTPException(400, "Provide at least one picture.")
    frames = []
    for upload in files:
        frame = _decode_image(None, upload)
        if frame is not None:
            frames.append(frame)
    if not frames:
        raise HTTPException(400, "None of the provided pictures could be read.")
    label = _allocate_face_label(employee_id)
    if not engine.enroll_many(label, frames):
        raise HTTPException(400, "No face detected in the provided pictures.")
    store.set_face_available(employee_id, 1)
    return {"detail": f"Enrolled {len(frames)} picture(s) for {employee_id}.", "face_enrolled": True}


@app.get("/api/employees/{employee_id}/face")
def face_status(employee_id: str, _: bool = Depends(require_admin)):
    row = store.get_employee(employee_id)
    if row is None:
        raise HTTPException(404, "Employee not found.")
    return {"employee_id": employee_id, "face_enrolled": bool(row["face_available"])}


@app.get("/api/departments")
def departments(_: bool = Depends(require_admin)):
    counts = {}
    for department in store.departments():
        name = security.decrypt_text(department) or "General"
        counts[name] = counts.get(name, 0) + 1
    return [{"department": department, "count": count} for department, count in counts.items()]


# --------------------------------------------------------------------------
# Attendance
# --------------------------------------------------------------------------
@app.post("/api/attendance/scan")
def scan_attendance(body: ScanRequest, request: Request):
    """Auto check-in / check-out driven by a recognised face."""
    client = _client_identity(request)
    allowed, retry_after = scan_limiter.check(client)
    if not allowed:
        return JSONResponse(
            {"action": "RATE_LIMITED", "message": "Too many scans. Please wait a moment."},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    if engine.name == "opencv":
        frame = _decode_image(body.image)
        if frame is None:
            raise HTTPException(400, "No image frame provided.")
        result = engine.recognize(frame, candidates=store.active_face_labels())
        if result is None:
            return JSONResponse({"action": "UNKNOWN", "message": "Face not recognised."})
        emp = store.get_employee_by_face_label(result[0])
        if emp is None:
            return JSONResponse({"action": "UNKNOWN", "message": "Face not recognised."})
        employee_id = emp["id"]
    else:
        raise HTTPException(503, "Face recognition is unavailable; public scanning is disabled.")

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
def manual_attendance(body: ManualRequest, _: bool = Depends(require_admin)):
    try:
        return attendance.record_scan(body.employee_id, source=body.action)
    except AttendanceError as exc:
        return JSONResponse({"action": exc.code.upper(), "message": exc.message, **exc.info}, status_code=409)


@app.get("/api/attendance")
def get_attendance(date: str | None = Query(None), employee_id: str | None = None, _: bool = Depends(require_admin)):
    if employee_id:
        return attendance.get_by_employee(employee_id)
    return attendance.get_by_date(date or db.today_str())


@app.get("/api/stats")
def stats(date: str | None = None, _: bool = Depends(require_admin)):
    return attendance.summary(date)


# --------------------------------------------------------------------------
# Microsoft 365 sync (Excel export + encrypted data backups)
# --------------------------------------------------------------------------
@app.get("/api/excel/status")
def excel_status(_: bool = Depends(require_admin)):
    return {
        "configured": onedrive.configured(),
        "sync_time": scheduler.ms_sync_time(),
        "folder": os.getenv("MS_FOLDER", "Attendance Tracker"),
        "filename": os.getenv("MS_EXCEL_FILENAME", "Attendance.xlsx"),
        "excel_enabled": scheduler.excel_enabled(),
        "backup_enabled": scheduler.backup_enabled(),
    }


@app.post("/api/excel/sync")
def excel_sync_now(_: bool = Depends(require_admin)):
    try:
        result = excel_sync.sync_to_excel()
    except onedrive.OneDriveError as exc:
        raise HTTPException(502, str(exc))
    if result.get("disabled"):
        raise HTTPException(503, result.get("reason", "Microsoft sync is not configured."))
    return result


@app.post("/api/backup/now")
def backup_now(_: bool = Depends(require_admin)):
    try:
        result = backup_sync.run_backup()
    except onedrive.OneDriveError as exc:
        raise HTTPException(502, str(exc))
    if result.get("disabled"):
        raise HTTPException(503, result.get("reason", "Backup is not configured."))
    return result


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
        root = FRONTEND_DIST.resolve()
        if full_path:
            try:
                candidate = (root / full_path).resolve()
            except Exception:
                candidate = root
            if (candidate == root or root in candidate.parents) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(root / "index.html")


def run() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)


if __name__ == "__main__":
    run()
