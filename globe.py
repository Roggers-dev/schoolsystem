import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import hashlib
import hmac
import secrets
import re
import io
import os
import tempfile
import unicodedata
import math
import zipfile
from fpdf import FPDF

# ---------------------------------------------------------
# 1. SCHOOL CONFIGURATION & BRANDING
# ---------------------------------------------------------
SCHOOL_NAME = "GLOBAL INTERNATIONAL SCHOOL"
SCHOOL_LOCATION = "Breman Esiam, Ajumako-Enyan-Esiam District, Central Region, Ghana"
SCHOOL_MOTTO = "Excellence, Discipline & Innovation"

DB_FILE = "globe_sms_v4.db"

CLASS_LEVELS = [
    "Nursery / KG 1",
    "KG 2",
    "Basic 1",
    "Basic 2",
    "Basic 3",
    "Basic 4",
    "Basic 5",
    "Basic 6",
    "JHS 1",
    "JHS 2",
    "JHS 3",
    "SHS 1",
    "SHS 2",
    "SHS 3",
]

SUBJECTS_LIST = [
    "RME",
    "Social Studies",
    "Mathematics",
    "ICT (Core/Elective)",
    "English Language",
    "Integrated Science",
    "Economics",
    "Accounting",
    "Elective Mathematics",
]

TEACHER_ACADEMIC_PROGRAMMES = [
    "WASSCE",
    "Pupil Teacher",
    "B.Ed / B.Sc (Education)",
    "Diploma in Basic Education (DBE)",
    "PGDE",
    "M.Ed / M.Phil / M.Sc",
]


BEHAVIOUR_OPTIONS = [
    "Exemplary Conduct & Respect",
    "Punctual & Attentive in Class",
    "Helpful & Cooperative with Peers",
    "Neat, Tidy & Well-Groomed",
    "Honest & Trustworthy",
    "Diligent & Self-Disciplined",
    "Needs Reminders on Punctuality",
    "Occasional Class Distraction",
    "Needs Improvement in Neatness",
    "Requires Conduct Guidance",
]


# Role names available for subordinate accounts. Admin is intentionally excluded.
ASSIGNABLE_ROLES = ["Manager", "Bursar", "ICT Teacher", "Teacher"]

MENU_DASHBOARD = "📊 Dashboard, Gender Totals & Filters"
MENU_STAFF_ROLES = "👥 Manage Staff & Roles"
MENU_TEACHER_DIRECTORY = "👨‍🏫 Teacher Registration & Directory"
MENU_STUDENT_RECORDS = "📝 Student Registration & Edit"
MENU_TIMETABLE = "👔 School Manager Profile & Timetable/Register"
MENU_LESSONS = "📖 Daily/Weekly Lessons & Remaining Topics"
MENU_ASSESSMENT = "🧮 Continuous Assessment & Score Entry"
MENU_REPORTS = "📄 Terminal Report Cards (PDF Export)"
MENU_CERTIFICATES = "🎓 Student Certificates & Term Honours"
MENU_FINANCE = "💰 Fees, Teacher Salaries & Occasions/Incidents"
MENU_ISSUE_REPORT = "📩 Report Issues to School Manager"
MENU_ISSUE_MANAGEMENT = "📬 Teacher Issues & Manager Replies"
MENU_EXPORT = "📥 CSV File Generator & Data Export"

ALL_MENU_OPTIONS = [
    MENU_DASHBOARD, MENU_STAFF_ROLES, MENU_TEACHER_DIRECTORY, MENU_STUDENT_RECORDS,
    MENU_TIMETABLE, MENU_LESSONS, MENU_ASSESSMENT, MENU_REPORTS, MENU_CERTIFICATES,
    MENU_FINANCE, MENU_ISSUE_REPORT, MENU_ISSUE_MANAGEMENT, MENU_EXPORT,
]

# Managers receive school-wide operational administration, but cannot manage
# privileged user accounts. Other roles receive only position-related modules.
ROLE_BASE_PERMISSIONS = {
    "Admin": list(ALL_MENU_OPTIONS),
    "Manager": [item for item in ALL_MENU_OPTIONS if item != MENU_STAFF_ROLES],
    "Bursar": [MENU_DASHBOARD, MENU_FINANCE, MENU_EXPORT],
    "ICT Teacher": [MENU_DASHBOARD, MENU_LESSONS, MENU_ASSESSMENT, MENU_REPORTS, MENU_CERTIFICATES, MENU_ISSUE_REPORT],
    "Teacher": [MENU_DASHBOARD, MENU_LESSONS, MENU_ASSESSMENT, MENU_REPORTS, MENU_CERTIFICATES, MENU_ISSUE_REPORT],
}

# Admin-selected extras are deliberately restricted to work-related modules.
# The Admin role and account-management module can never be granted here.
ROLE_EXTRA_PRIVILEGES = {
    "Manager": [],
    "Bursar": [],
    "ICT Teacher": [MENU_TEACHER_DIRECTORY, MENU_TIMETABLE, MENU_EXPORT],
    "Teacher": [MENU_TIMETABLE, MENU_EXPORT],
}


def get_user_extra_permissions(conn, username: str):
    rows = conn.execute(
        "SELECT module_name FROM user_extra_permissions WHERE username = ? ORDER BY module_name",
        (username,),
    ).fetchall()
    return [row["module_name"] for row in rows]


def get_effective_permissions(conn, username: str, role: str):
    base = list(ROLE_BASE_PERMISSIONS.get(role, []))
    if role == "Admin":
        return base
    # Admin may grant any operational module individually, but cannot grant
    # the account/role administration module or the Admin identity itself.
    allowed_extras = set(ALL_MENU_OPTIONS) - {MENU_STAFF_ROLES}
    stored_extras = set(get_user_extra_permissions(conn, username))
    return list(dict.fromkeys(base + [item for item in stored_extras if item in allowed_extras]))


def write_audit_log(conn, username: str, role: str, action: str, details: str = ""):
    conn.execute(
        "INSERT INTO system_audit_log (username, role, action, details, created_at) VALUES (?, ?, ?, ?, ?)",
        (username, role, action, details, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )


def pdf_safe_text(value):
    """Convert arbitrary user text to safe text for built-in FPDF core fonts."""
    text_value = str(value if value is not None else "")
    text_value = text_value.translate(str.maketrans({
        "ɛ": "e", "Ɛ": "E", "ɔ": "o", "Ɔ": "O", "’": "'", "‘": "'",
        "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "•": "-",
    }))
    normalized = unicodedata.normalize("NFKD", text_value)
    return normalized.encode("latin-1", "replace").decode("latin-1")


def pdf_output_bytes(pdf):
    """Finalize an FPDF document and return validated raw PDF bytes.

    PyFPDF 1.x and fpdf2 2.x differ in their output() defaults and return
    types.  The in-memory destination ("S") is the portable contract across
    both families: PyFPDF returns a Latin-1 string and fpdf2 returns bytes.
    """
    try:
        # Explicit in-memory output avoids browser/inline/file destinations.
        output = pdf.output(dest="S")
    except TypeError:
        # Compatibility for wrappers that removed the legacy dest parameter.
        output = pdf.output()

    if output is None:
        raise RuntimeError(
            "The PDF library returned no data. Check the installed fpdf package."
        )

    if isinstance(output, str):
        data = output.encode("latin-1")
    elif isinstance(output, (bytes, bytearray, memoryview)):
        data = bytes(output)
    else:
        try:
            data = bytes(output)
        except Exception as exc:
            raise TypeError(
                f"Unsupported PDF output type: {type(output).__name__}"
            ) from exc

    # Remove only known transport prefixes; do not silently accept arbitrary data.
    data = data.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
    header_at = data.find(b"%PDF-")
    if header_at == -1 or header_at > 32:
        preview = data[:24].hex(" ") if data else "empty"
        raise ValueError(
            "FPDF did not return a PDF document (missing %PDF- header; "
            f"output type={type(output).__name__}, prefix={preview}). "
            "Check for conflicting PyFPDF/fpdf2 installations."
        )
    return data[header_at:]


def validate_pdf_bytes(data):
    """Reject empty, truncated, or non-PDF output before offering a download."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("PDF output must be bytes.")
    payload = bytes(data)
    if not payload.startswith(b"%PDF-"):
        raise ValueError("PDF generation failed: the file header is missing.")
    if b"%%EOF" not in payload[-2048:]:
        raise ValueError("PDF generation failed: the file appears incomplete.")
    return payload


def create_db_backup(reason: str = "auto"):
    """Create a consistent SQLite online-backup snapshot without leaking connections."""
    if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
        return None

    backup_dir = "db_backups"
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "_", reason)[:30]
    backup_path = os.path.join(backup_dir, f"globe_sms_backup_{timestamp}_{safe_reason}.db")
    source_conn = destination_conn = None
    try:
        source_conn = sqlite3.connect(DB_FILE, timeout=30.0)
        destination_conn = sqlite3.connect(backup_path, timeout=30.0)
        source_conn.backup(destination_conn)
        destination_conn.commit()
        backups = sorted(
            [os.path.join(backup_dir, name) for name in os.listdir(backup_dir) if name.endswith(".db")],
            key=os.path.getmtime,
        )
        for old_backup in backups[:-25]:
            try:
                os.remove(old_backup)
            except OSError:
                pass
        return backup_path
    except Exception:
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        except OSError:
            pass
        return None
    finally:
        if destination_conn is not None:
            destination_conn.close()
        if source_conn is not None:
            source_conn.close()


def _ensure_column(cursor, table_name: str, col_name: str, col_def: str):
    """Safely add a missing internal schema column; propagate unexpected DB errors."""
    columns = [row["name"] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()]
    if col_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")


def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
    return conn


def hash_password(password: str) -> str:
    """Hash new passwords with salted PBKDF2-SHA256."""
    iterations = 310000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify modern hashes and transparently accept legacy SHA-256 hashes."""
    if not stored_hash:
        return False
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            algorithm, iteration_text, salt_hex, digest_hex = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            iterations = int(iteration_text)
            if iterations < 100000 or iterations > 2000000:
                return False
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    # Compatibility path for accounts created by earlier GLOBE versions.
    legacy_digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_digest, stored_hash)


def capitalize_initials(name: str) -> str:
    """Capitalizes the initial letter of every word/segment in a name without clearing user input."""
    if not name:
        return ""
    return " ".join(
        "-".join(part[:1].upper() + part[1:] if part else "" for part in word.split("-"))
        for word in name.strip().split()
    )


def format_full_name(surname: str, first_name: str, middle_name: str = "") -> str:
    parts = [capitalize_initials(p) for p in [surname, first_name, middle_name] if p and p.strip()]
    return " ".join(parts)


def capitalize_name_widget(key: str):
    """Title-case a name input when the user leaves the field or presses Enter."""
    value = st.session_state.get(key, "")
    st.session_state[key] = capitalize_initials(str(value))


def save_teacher_class_assignments(conn, staff_id: str, class_levels: list):
    """Replace a teacher's class allocations atomically; an empty list means all classes."""
    valid_levels = list(dict.fromkeys(level for level in (class_levels or []) if level in CLASS_LEVELS))
    if not valid_levels:
        valid_levels = list(CLASS_LEVELS)
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM teacher_class_assignments WHERE staff_id = ?", (staff_id,))
    cursor.executemany(
        "INSERT INTO teacher_class_assignments (staff_id, class_level, assigned_at) VALUES (?, ?, ?)",
        [(staff_id, level, now_text) for level in valid_levels],
    )
    legacy_value = "All / Multiple Classes" if len(valid_levels) == len(CLASS_LEVELS) else ", ".join(valid_levels)
    cursor.execute("UPDATE teachers SET assigned_class_level = ? WHERE staff_id = ?", (legacy_value, staff_id))


def get_teacher_assigned_classes(conn, username: str):
    """Return only explicitly allocated classes, including recognized legacy all-class labels."""
    row = conn.execute("SELECT staff_id FROM teachers WHERE username = ? AND TRIM(COALESCE(username, '')) != ''", (username,)).fetchone()
    if not row:
        return []
    rows = conn.execute(
        "SELECT class_level FROM teacher_class_assignments WHERE staff_id = ? ORDER BY assignment_id",
        (row["staff_id"],),
    ).fetchall()
    if rows:
        return [r["class_level"] for r in rows if r["class_level"] in CLASS_LEVELS]
    # Compatibility fallback for a teacher profile created before the new table.
    legacy = conn.execute("SELECT assigned_class_level FROM teachers WHERE staff_id = ?", (row["staff_id"],)).fetchone()
    legacy_value = (legacy["assigned_class_level"] or "").strip() if legacy else ""
    if legacy_value.lower() in ("all", "all classes", "all / multiple classes"):
        return list(CLASS_LEVELS)
    if not legacy_value:
        return []
    return [part.strip() for part in legacy_value.split(",") if part.strip() in CLASS_LEVELS]


def generate_admission_number(surname: str, first_name: str, middle_name: str = "", seq_num: int = 1) -> str:
    """Attaches letters from the student's name plus year and sequence number."""
    s_letters = re.sub(r"[^A-Za-z]", "", surname or "X")[:2].upper().ljust(2, "X")
    f_letter = re.sub(r"[^A-Za-z]", "", first_name or "X")[:1].upper().ljust(1, "X")
    m_letter = re.sub(r"[^A-Za-z]", "", middle_name or "")[:1].upper()
    code_letters = f"{s_letters}{f_letter}{m_letter}"
    year = datetime.now().strftime("%Y")
    return f"GIS-{code_letters}-{year}-{seq_num:03d}"


def generate_unique_admission_number(conn, surname: str, first_name: str, middle_name: str = "") -> str:
    """Generate the next unused admission number, even if older records were deleted."""
    next_seq = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] + 1
    while True:
        candidate = generate_admission_number(surname, first_name, middle_name, next_seq)
        exists = conn.execute("SELECT 1 FROM students WHERE student_id = ?", (candidate,)).fetchone()
        if not exists:
            return candidate
        next_seq += 1


def init_db():
    if not st.session_state.get("_globe_startup_backup_done", False):
        if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > 0:
            create_db_backup("startup")
        st.session_state["_globe_startup_backup_done"] = True
    conn = get_connection()
    c = conn.cursor()

    # Users Table (Admin, Manager, Teacher, Bursar)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL,
            assigned_subject TEXT,
            passport_photo BLOB,
            passport_mime TEXT
        )
    """)

    # Seed default accounts if empty
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        default_users = [
            ("admin", hash_password("admin123"), "Headmaster Admin", "Admin", "All", None, None),
            ("manager", hash_password("mgr123"), "School Manager", "Manager", "All", None, None),
            ("teacher1", hash_password("teach123"), "ICT Teacher", "Teacher", "ICT (Core/Elective)", None, None),
            ("bursar", hash_password("fees123"), "School Bursar", "Bursar", "None", None, None),
        ]
        c.executemany(
            "INSERT INTO users (username, password_hash, full_name, role, assigned_subject, passport_photo, passport_mime) VALUES (?, ?, ?, ?, ?, ?, ?)",
            default_users,
        )

    # Students Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            surname TEXT NOT NULL,
            first_name TEXT NOT NULL,
            middle_name TEXT,
            full_name TEXT NOT NULL,
            gender TEXT NOT NULL,
            class_level TEXT NOT NULL,
            program TEXT NOT NULL,
            boarding_status TEXT NOT NULL,
            guardian_name TEXT,
            guardian_phone TEXT,
            passport_photo BLOB,
            passport_mime TEXT,
            status TEXT DEFAULT 'Active',
            date_registered TEXT
        )
    """)

    # Teachers Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS teachers (
            staff_id TEXT PRIMARY KEY,
            surname TEXT NOT NULL,
            first_name TEXT NOT NULL,
            middle_name TEXT,
            full_name TEXT NOT NULL,
            gender TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            academic_programme TEXT NOT NULL,
            department TEXT NOT NULL,
            assigned_subject TEXT NOT NULL,
            passport_photo BLOB,
            passport_mime TEXT,
            employment_date TEXT,
            username TEXT,
            status TEXT DEFAULT 'Active'
        )
    """)

    # Assessments Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            subject TEXT NOT NULL,
            class_test_1 REAL DEFAULT 0,
            class_test_2 REAL DEFAULT 0,
            project_work REAL DEFAULT 0,
            exam_raw REAL DEFAULT 0,
            sba_weighted REAL DEFAULT 0,
            exam_weighted REAL DEFAULT 0,
            total_score REAL DEFAULT 0,
            grade TEXT,
            remark TEXT,
            UNIQUE(student_id, term, subject),
            FOREIGN KEY(student_id) REFERENCES students(student_id)
        )
    """)

    # Management Approvals Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS management_approvals (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            manager_role TEXT NOT NULL,
            management_remark TEXT,
            signed_date TEXT NOT NULL,
            UNIQUE(student_id, term)
        )
    """)

    # Fee Payments Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS fee_payments (
            receipt_no TEXT PRIMARY KEY,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            fee_billed REAL NOT NULL,
            amount_paid REAL NOT NULL,
            payment_method TEXT NOT NULL,
            payment_date TEXT NOT NULL,
            recorded_by TEXT,
            FOREIGN KEY(student_id) REFERENCES students(student_id)
        )
    """)

    # Teacher Salary Payment Records Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS salary_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            pay_month TEXT NOT NULL,
            basic_salary REAL NOT NULL,
            allowances REAL DEFAULT 0,
            deductions REAL DEFAULT 0,
            net_pay REAL NOT NULL,
            payment_method TEXT NOT NULL,
            payment_date TEXT NOT NULL,
            paid_by TEXT
        )
    """)

    # Special Activities & Occasions Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS special_occasions (
            occasion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            occasion_type TEXT NOT NULL,
            event_date TEXT NOT NULL,
            venue TEXT,
            coordinator TEXT,
            summary TEXT NOT NULL,
            recorded_by TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # Incidents Report Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS incident_reports (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_date TEXT NOT NULL,
            class_level TEXT NOT NULL,
            involved_person TEXT NOT NULL,
            severity TEXT NOT NULL,
            description TEXT NOT NULL,
            action_taken TEXT,
            reported_by TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # Teacher Daily/Weekly Lesson Coverage & Remaining Topics Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS lesson_coverage_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_username TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            class_level TEXT NOT NULL,
            subject TEXT NOT NULL,
            period_type TEXT NOT NULL,
            log_date TEXT NOT NULL,
            areas_taught TEXT NOT NULL,
            areas_left_to_cover TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Teacher Issues & Manager Replies Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS staff_issues (
            issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_username TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            category TEXT NOT NULL,
            subject_line TEXT NOT NULL,
            issue_details TEXT NOT NULL,
            status TEXT DEFAULT 'Open',
            manager_reply TEXT,
            replied_by TEXT,
            replied_at TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # In-app notifications for issue reports and manager replies.
    c.execute("""
        CREATE TABLE IF NOT EXISTS app_notifications (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_username TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            related_issue_id INTEGER,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_app_notifications_user ON app_notifications(recipient_username, is_read, notification_id)")

    # School Attendance Register Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS school_register (
            reg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            register_date TEXT NOT NULL,
            class_level TEXT NOT NULL,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            attendance_status TEXT NOT NULL,
            timetable_slot TEXT,
            generated_by TEXT,
            UNIQUE(register_date, student_id)
        )
    """)

    # Clash-Free School Timetable Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS school_timetable (
            slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_level TEXT NOT NULL,
            day_of_week TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            subject TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            mode_used TEXT NOT NULL,
            created_by TEXT,
            UNIQUE(class_level, day_of_week, time_slot),
            UNIQUE(day_of_week, time_slot, teacher_name)
        )
    """)

    # Issued Certificates Log Table
    c.execute("""
        CREATE TABLE IF NOT EXISTS issued_certificates (
            cert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            certificate_no TEXT UNIQUE NOT NULL,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            cert_type TEXT NOT NULL,
            term TEXT,
            average_score REAL,
            honour_tier TEXT,
            issued_date TEXT NOT NULL,
            issued_by TEXT
        )
    """)

    # Student History Removal Audit Log Table (Admin only)
    c.execute("""
        CREATE TABLE IF NOT EXISTS student_history_removal_logs (
            removal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            class_level TEXT NOT NULL,
            removed_sections TEXT NOT NULL,
            reason TEXT NOT NULL,
            removed_by TEXT NOT NULL,
            removed_at TEXT NOT NULL
        )
    """)

    # Learner Behaviours Table (selected strictly from BEHAVIOUR_OPTIONS)
    c.execute("""
        CREATE TABLE IF NOT EXISTS student_behaviours (
            behaviour_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            behaviour_label TEXT NOT NULL,
            recorded_by TEXT,
            recorded_at TEXT NOT NULL,
            UNIQUE(student_id, term)
        )
    """)

    # Self-healing schema columns & edit-permission / teacher-assignment support
    _ensure_column(c, "students", "promotion_status", "TEXT DEFAULT 'Promoted'")
    _ensure_column(c, "students", "student_edit_locked", "INTEGER DEFAULT 1")
    _ensure_column(c, "students", "assigned_teacher_staff_id", "TEXT")
    _ensure_column(c, "students", "assigned_teacher_name", "TEXT")
    _ensure_column(c, "teachers", "assigned_class_level", "TEXT")

    # Normalized many-to-many teacher/class assignments. The legacy column is
    # retained for compatibility with existing versions and reports.
    c.execute("""
        CREATE TABLE IF NOT EXISTS teacher_class_assignments (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id TEXT NOT NULL,
            class_level TEXT NOT NULL,
            assigned_at TEXT NOT NULL,
            UNIQUE(staff_id, class_level),
            FOREIGN KEY(staff_id) REFERENCES teachers(staff_id) ON DELETE CASCADE
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_teacher_class_staff ON teacher_class_assignments(staff_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_teacher_class_level ON teacher_class_assignments(class_level)")

    c.execute("UPDATE students SET promotion_status = 'Promoted' WHERE promotion_status IS NULL OR TRIM(promotion_status) = ''")
    c.execute("UPDATE students SET student_edit_locked = 1 WHERE student_edit_locked IS NULL")

    # Normalize legacy role labels so existing accounts retain the correct access.
    c.execute("UPDATE users SET role = 'Bursar' WHERE LOWER(TRIM(role)) = 'bursary'")
    c.execute("UPDATE users SET role = 'ICT Teacher' WHERE LOWER(TRIM(role)) IN ('ict', 'ict teacher')")
    c.execute("UPDATE users SET role = 'Manager' WHERE LOWER(TRIM(role)) IN ('manager', 'school manager')")
    c.execute("UPDATE users SET role = 'Teacher' WHERE LOWER(TRIM(role)) = 'teacher'")
    c.execute("UPDATE users SET role = 'Admin' WHERE LOWER(TRIM(role)) = 'admin'")

    # One-time/idempotent migration: preserve existing teacher class allocations.
    legacy_teachers = c.execute(
        "SELECT staff_id, assigned_class_level FROM teachers WHERE assigned_class_level IS NOT NULL AND TRIM(assigned_class_level) != ''"
    ).fetchall()
    for legacy_teacher in legacy_teachers:
        legacy_class = str(legacy_teacher["assigned_class_level"]).strip()
        if legacy_class == "All / Multiple Classes":
            legacy_classes = CLASS_LEVELS
        else:
            legacy_classes = [part.strip() for part in legacy_class.split(",") if part.strip() in CLASS_LEVELS]
        for legacy_level in legacy_classes:
            c.execute(
                "INSERT OR IGNORE INTO teacher_class_assignments (staff_id, class_level, assigned_at) VALUES (?, ?, ?)",
                (legacy_teacher["staff_id"], legacy_level, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )

    # Idempotent indexes to guard against duplicate records & speed lookups
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_assessment ON assessments(student_id, term, subject)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_approval ON management_approvals(student_id, term)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_register ON school_register(register_date, student_id)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_timetable_cls ON school_timetable(class_level, day_of_week, time_slot)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_timetable_tch ON school_timetable(day_of_week, time_slot, teacher_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_level)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_students_teacher ON students(assigned_teacher_staff_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fees_student ON fee_payments(student_id, term)")

    # Position-based extra privileges and an audit trail for sensitive actions.
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_extra_permissions (
            username TEXT NOT NULL,
            module_name TEXT NOT NULL,
            granted_by TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            PRIMARY KEY(username, module_name),
            FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_extra_permissions_username ON user_extra_permissions(username)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_system_audit_created ON system_audit_log(created_at)")

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# 2. WASSCE GRADING & CLASH-FREE TIMETABLE ENGINE
# ---------------------------------------------------------
def calculate_wassce_grade(total_score: float):
    try:
        score = round(float(total_score))
    except (TypeError, ValueError, OverflowError):
        return "F9", "Fail"
    if not math.isfinite(float(score)) or score < 0 or score > 100:
        return "F9", "Fail"
    if 80 <= score <= 100:
        return "A1", "Excellent"
    elif 70 <= score <= 79:
        return "B2", "Very Good"
    elif 65 <= score <= 69:
        return "B3", "Good"
    elif 60 <= score <= 64:
        return "C4", "Credit"
    elif 55 <= score <= 59:
        return "C5", "Credit"
    elif 50 <= score <= 54:
        return "C6", "Credit"
    elif 45 <= score <= 49:
        return "D7", "Pass"
    elif 40 <= score <= 44:
        return "E8", "Pass"
    else:
        return "F9", "Fail"


def compute_assessment(t1, t2, proj, exam_raw):
    sba_raw_total = t1 + t2 + proj
    sba_weighted = round((sba_raw_total / 60.0) * 30.0, 2)
    exam_weighted = round((exam_raw / 100.0) * 70.0, 2)
    total_score = round(sba_weighted + exam_weighted, 2)
    grade, remark = calculate_wassce_grade(total_score)
    return sba_weighted, exam_weighted, total_score, grade, remark


def determine_term_honour(avg_score: float, min_pass_mark: float = 60.0):
    try:
        avg_score = float(avg_score)
        min_pass_mark = float(min_pass_mark)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(avg_score) or not math.isfinite(min_pass_mark):
        return None
    if avg_score < min_pass_mark:
        return None
    if avg_score >= 85.0:
        return "First Class Distinction / Principal's Honour Roll"
    elif avg_score >= 75.0:
        return "First Class Honour / Merit Scholar"
    elif avg_score >= 65.0:
        return "Second Class Upper Merit"
    else:
        return "Qualified Term Merit Pass"


def generate_clash_free_timetable(conn, target_class: str, days: list, time_slots: list, chosen_subjects: list, mode_used: str, created_by: str):
    """Create a clash-free timetable using only teachers assigned to the class and subject."""
    if target_class not in CLASS_LEVELS:
        raise ValueError("A valid class level must be selected before generating a timetable.")

    cursor = conn.cursor()
    active_teachers = [dict(row) for row in cursor.execute(
        "SELECT staff_id, full_name, assigned_subject, assigned_class_level FROM teachers WHERE status = 'Active'"
    ).fetchall()]
    for teacher in active_teachers:
        assigned_rows = cursor.execute(
            "SELECT class_level FROM teacher_class_assignments WHERE staff_id = ?",
            (teacher["staff_id"],),
        ).fetchall()
        allocated = {row["class_level"] for row in assigned_rows if row["class_level"] in CLASS_LEVELS}
        if not allocated:
            legacy_value = (teacher.get("assigned_class_level") or "").strip()
            if legacy_value.lower() in ("all", "all classes", "all / multiple classes"):
                allocated = set(CLASS_LEVELS)
            else:
                allocated = {part.strip() for part in legacy_value.split(",") if part.strip() in CLASS_LEVELS}
        teacher["allocated_classes"] = allocated

    booked_slots = {
        (row["day_of_week"], row["time_slot"], row["teacher_name"])
        for row in cursor.execute(
            "SELECT day_of_week, time_slot, teacher_name FROM school_timetable WHERE class_level != ?",
            (target_class,),
        ).fetchall()
    }

    subject_pool = list(dict.fromkeys(subject for subject in (chosen_subjects or []) if subject in SUBJECTS_LIST))
    if not subject_pool:
        subject_pool = SUBJECTS_LIST[:5]

    subject_index = 0
    conflicts_skipped = 0
    scheduled_rows = []

    for day in days:
        used_subjects_today = set()
        for slot in time_slots:
            assigned_teacher_name = None
            assigned_subject = None
            eligible_teachers = [
                teacher for teacher in active_teachers
                if target_class in teacher["allocated_classes"]
            ]

            for attempt in range(len(subject_pool)):
                candidate_subject = subject_pool[(subject_index + attempt) % len(subject_pool)]
                if candidate_subject in used_subjects_today:
                    continue

                matching_teachers = [
                    teacher["full_name"] for teacher in eligible_teachers
                    if teacher.get("assigned_subject") == candidate_subject
                ]
                for teacher_name in matching_teachers:
                    if (day, slot, teacher_name) not in booked_slots:
                        assigned_teacher_name = teacher_name
                        assigned_subject = candidate_subject
                        booked_slots.add((day, slot, teacher_name))
                        used_subjects_today.add(candidate_subject)
                        subject_index = (subject_index + attempt + 1) % len(subject_pool)
                        break
                if assigned_teacher_name:
                    break

            if not assigned_teacher_name:
                conflicts_skipped += 1
                continue

            scheduled_rows.append((
                target_class, day, slot, assigned_subject, assigned_teacher_name, mode_used, created_by
            ))

    # Do not erase a previously saved timetable when there is no valid replacement.
    if scheduled_rows:
        cursor.execute("SAVEPOINT timetable_replace")
        try:
            cursor.execute("DELETE FROM school_timetable WHERE class_level = ?", (target_class,))
            cursor.executemany(
                """INSERT INTO school_timetable
                   (class_level, day_of_week, time_slot, subject, teacher_name, mode_used, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                scheduled_rows,
            )
            cursor.execute("RELEASE SAVEPOINT timetable_replace")
            conn.commit()
        except Exception:
            cursor.execute("ROLLBACK TO SAVEPOINT timetable_replace")
            cursor.execute("RELEASE SAVEPOINT timetable_replace")
            conn.rollback()
            raise

    return len(scheduled_rows), conflicts_skipped


# ---------------------------------------------------------
# 3. PDF GENERATORS (TERMINAL REPORT & CERTIFICATES)
# ---------------------------------------------------------
class SchoolPDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 15)
        self.set_text_color(27, 54, 93)
        self.cell(0, 8, pdf_safe_text(SCHOOL_NAME), ln=True, align="C")
        self.set_font("Arial", "B", 9)
        self.set_text_color(80, 80, 80)
        self.cell(0, 5, pdf_safe_text(SCHOOL_LOCATION), ln=True, align="C")
        self.set_font("Arial", "I", 9)
        self.cell(0, 5, pdf_safe_text(f'Motto: "{SCHOOL_MOTTO}"'), ln=True, align="C")
        self.ln(3)
        self.set_draw_color(27, 54, 93)
        self.set_line_width(0.6)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Generated by {SCHOOL_NAME} Management System | Page {self.page_no()}", align="C")


def _render_single_report_page(pdf, student_info, term, report_df, overall_total, overall_avg, master_comment, approval_info=None, behaviour_label=None):
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)

    # Student Passport Picture on top-right of report card if available
    temp_img_path = None
    photo_bytes = None
    photo_mime = ""
    try:
        photo_bytes = student_info["passport_photo"]
    except Exception:
        photo_bytes = None
    try:
        photo_mime = (student_info["passport_mime"] or "").lower()
    except Exception:
        photo_mime = ""

    if photo_bytes:
        ext = ".png" if "png" in photo_mime else ".jpg"
        try:
            fd, temp_img_path = tempfile.mkstemp(suffix=ext)
            with os.fdopen(fd, "wb") as tmp_f:
                tmp_f.write(bytes(photo_bytes))
            pdf.set_draw_color(27, 54, 93)
            pdf.set_line_width(0.6)
            pdf.rect(168, 36, 26, 29)
            pdf.image(temp_img_path, x=169, y=37, w=24, h=27)
        except Exception:
            pdf.set_draw_color(180, 190, 205)
            pdf.rect(168, 36, 26, 29)
        finally:
            if temp_img_path and os.path.exists(temp_img_path):
                try:
                    os.remove(temp_img_path)
                except OSError:
                    pass
            temp_img_path = None

    pdf.set_font("Arial", "B", 12)
    pdf.set_fill_color(230, 238, 248)
    pdf.cell(152, 8, pdf_safe_text(f"STUDENT TERMINAL REPORT CARD - {term.upper()}"), ln=True, align="C", fill=True)
    pdf.ln(3)

    promo_val = ""
    try:
        promo_val = student_info["promotion_status"] or "Promoted"
    except Exception:
        promo_val = "Promoted"

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(34, 6.5, "Student Name:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(58, 6.5, pdf_safe_text(student_info["full_name"]), border=0)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(30, 6.5, "Admission No.:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(35, 6.5, pdf_safe_text(student_info["student_id"]), ln=True)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(34, 6.5, "Class / Grade:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(58, 6.5, pdf_safe_text(student_info["class_level"]), border=0)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(30, 6.5, "Status:", border=0)
    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(35, 6.5, pdf_safe_text(promo_val), ln=True)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(34, 6.5, "Program:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(58, 6.5, pdf_safe_text(student_info["program"]), border=0)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(30, 6.5, "Overall Average:", border=0)
    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(35, 6.5, f"{overall_avg}%", ln=True)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(34, 6.5, "Residential:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(58, 6.5, pdf_safe_text(student_info["boarding_status"]), border=0)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(30, 6.5, "Behaviour:", border=0)
    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(35, 6.5, pdf_safe_text(behaviour_label or "Exemplary Conduct & Respect"), ln=True)
    pdf.ln(5)


def generate_terminal_report_pdf(student_info, term, report_df, overall_total, overall_avg, master_comment, approval_info=None, behaviour_label=None):
    pdf = SchoolPDF()
    _render_single_report_page(pdf, student_info, term, report_df, overall_total, overall_avg, master_comment, approval_info, behaviour_label)



    pdf.set_font("Arial", "B", 9)
    pdf.set_fill_color(27, 54, 93)
    pdf.set_text_color(255, 255, 255)
    col_widths = [55, 25, 25, 25, 20, 40]
    headers = ["Subject", "SBA (30%)", "Exam (70%)", "Total (100%)", "Grade", "Remark"]
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 8, h, border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_font("Arial", "", 9)
    pdf.set_text_color(0, 0, 0)
    for _, row in report_df.iterrows():
        pdf.cell(col_widths[0], 7, pdf_safe_text(row["Subject"]), border=1)
        pdf.cell(col_widths[1], 7, f"{row['SBA (30%)']}", border=1, align="C")
        pdf.cell(col_widths[2], 7, f"{row['Exam (70%)']}", border=1, align="C")
        pdf.cell(col_widths[3], 7, f"{row['Total (100%)']}", border=1, align="C")
        pdf.cell(col_widths[4], 7, pdf_safe_text(row["Grade"]), border=1, align="C")
        pdf.cell(col_widths[5], 7, pdf_safe_text(row["Remark"]), border=1, align="C")
        pdf.ln()

    pdf.ln(5)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 7, f"Grand Total Score: {overall_total}   |   Subjects Taken: {len(report_df)}   |   Overall Average: {overall_avg}%", ln=True)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 6, "Form Master's Remark:", ln=True)
    pdf.set_font("Arial", "I", 10)
    pdf.multi_cell(0, 6, pdf_safe_text(master_comment))
    pdf.ln(3)

    if approval_info is not None:
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, pdf_safe_text(f"School Manager Sign-Off ({approval_info['manager_role']} - {approval_info['approved_by']}):"), ln=True)
        pdf.set_font("Arial", "I", 10)
        pdf.multi_cell(0, 6, pdf_safe_text(f"{approval_info['management_remark']} (Signed on {approval_info['signed_date']})"))
        pdf.ln(4)

    pdf.ln(6)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(95, 7, "__________________________", align="C")
    pdf.cell(95, 7, "__________________________", align="C", ln=True)
    pdf.cell(95, 5, "Class Teacher's Signature", align="C")
    pdf.cell(95, 5, "School Manager Signature", align="C", ln=True)

    return validate_pdf_bytes(pdf_output_bytes(pdf))


def generate_class_report_cards_pdf(class_records):
    """Generates a multi-page PDF with one student's report card per page."""
    pdf = SchoolPDF()
    for item in class_records:
        _render_single_report_page(
            pdf,
            item["student_info"],
            item["term"],
            item["report_df"],
            item["overall_total"],
            item["overall_avg"],
            item["master_comment"],
            item.get("approval_info"),
            item.get("behaviour_label"),
        )
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(27, 54, 93)
        pdf.set_text_color(255, 255, 255)
        col_widths = [55, 25, 25, 25, 20, 40]
        headers = ["Subject", "SBA (30%)", "Exam (70%)", "Total (100%)", "Grade", "Remark"]
        for w, h in zip(col_widths, headers):
            pdf.cell(w, 8, h, border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(0, 0, 0)
        for _, row in item["report_df"].iterrows():
            pdf.cell(col_widths[0], 7, pdf_safe_text(row["Subject"]), border=1)
            pdf.cell(col_widths[1], 7, f"{row['SBA (30%)']}", border=1, align="C")
            pdf.cell(col_widths[2], 7, f"{row['Exam (70%)']}", border=1, align="C")
            pdf.cell(col_widths[3], 7, f"{row['Total (100%)']}", border=1, align="C")
            pdf.cell(col_widths[4], 7, pdf_safe_text(row["Grade"]), border=1, align="C")
            pdf.cell(col_widths[5], 7, pdf_safe_text(row["Remark"]), border=1, align="C")
            pdf.ln()

        pdf.ln(5)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 7, f"Grand Total Score: {item['overall_total']}   |   Subjects Taken: {len(item['report_df'])}   |   Overall Average: {item['overall_avg']}%", ln=True)
        pdf.ln(3)

        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, "Form Master's Remark:", ln=True)
        pdf.set_font("Arial", "I", 10)
        pdf.multi_cell(0, 6, pdf_safe_text(item["master_comment"]))
        pdf.ln(3)

        if item.get("approval_info") is not None:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 6, pdf_safe_text(f"School Manager Sign-Off ({item['approval_info']['manager_role']} - {item['approval_info']['approved_by']}):"), ln=True)
            pdf.set_font("Arial", "I", 10)
            pdf.multi_cell(0, 6, pdf_safe_text(f"{item['approval_info']['management_remark']} (Signed on {item['approval_info']['signed_date']})"))
            pdf.ln(4)

        pdf.ln(6)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(95, 7, "__________________________", align="C")
        pdf.cell(95, 7, "__________________________", align="C", ln=True)
        pdf.cell(95, 5, "Class Teacher's Signature", align="C")
        pdf.cell(95, 5, "School Manager Signature", align="C", ln=True)

    return validate_pdf_bytes(pdf_output_bytes(pdf))


def generate_student_certificate_pdf(
    student_info: dict,
    cert_no: str,
    cert_title: str,
    subtitle: str,
    citation_text: str,
    issued_date: str,
    manager_name: str,
):
    """Generate a polished, standards-compliant A4 landscape certificate PDF."""
    required = ("student_id", "full_name", "class_level", "program")
    missing = [key for key in required if not student_info.get(key)]
    if missing:
        raise ValueError("Missing student certificate details: " + ", ".join(missing))

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=False)
    # Metadata and conservative built-in fonts maximise compatibility with common PDF readers.
    pdf.set_title(pdf_safe_text(f"{cert_title} - {student_info['full_name']}"))
    pdf.set_author(pdf_safe_text(SCHOOL_NAME))
    pdf.set_subject("Official student academic certificate")
    pdf.set_creator(pdf_safe_text(f"{SCHOOL_NAME} Management System"))
    pdf.add_page()
    temp_img_path = None
    try:
        navy = (25, 48, 82)
        gold = (184, 142, 40)
        pale = (246, 248, 251)
        muted = (83, 96, 113)

        # Double-line frame and restrained corner accents.
        pdf.set_draw_color(*navy)
        pdf.set_line_width(1.7)
        pdf.rect(7, 7, 283, 196)
        pdf.set_draw_color(*gold)
        pdf.set_line_width(0.65)
        pdf.rect(11, 11, 275, 188)
        pdf.set_fill_color(*pale)
        pdf.rect(14, 14, 269, 35, style="F")

        # Institutional heading.
        pdf.set_xy(20, 18)
        pdf.set_font("Arial", "B", 20)
        pdf.set_text_color(*navy)
        school = pdf_safe_text(SCHOOL_NAME).upper()
        while pdf.get_string_width(school) > 235 and pdf.font_size_pt > 13:
            pdf.set_font_size(pdf.font_size_pt - 1)
        pdf.cell(257, 9, school, align="C")
        pdf.set_xy(20, 29)
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(*muted)
        pdf.cell(257, 5, pdf_safe_text(SCHOOL_LOCATION), align="C")
        pdf.set_xy(20, 36)
        pdf.set_font("Arial", "I", 9)
        pdf.set_text_color(*gold)
        pdf.cell(257, 5, pdf_safe_text(f'"{SCHOOL_MOTTO}"'), align="C")

        # Official school certification heading and subtitle.
        pdf.set_xy(22, 55)
        pdf.set_font("Arial", "B", 19)
        pdf.set_text_color(*navy)
        title_text = pdf_safe_text(cert_title).upper()
        while pdf.get_string_width(title_text) > 235 and pdf.font_size_pt > 12:
            pdf.set_font_size(pdf.font_size_pt - 1)
        pdf.cell(253, 10, title_text, align="C")
        pdf.set_draw_color(*gold)
        pdf.set_line_width(0.9)
        pdf.line(88, 68, 209, 68)

        pdf.set_xy(22, 72)
        pdf.set_font("Arial", "B", 10)
        pdf.set_text_color(*muted)
        subtitle_text = pdf_safe_text(subtitle)
        while pdf.get_string_width(subtitle_text) > 230 and pdf.font_size_pt > 8:
            pdf.set_font_size(pdf.font_size_pt - 0.5)
        pdf.cell(253, 6, subtitle_text, align="C")

        # Student photograph is optional; an unsupported image never blocks PDF creation.
        photo_bytes = student_info.get("passport_photo")
        if photo_bytes:
            mime = (student_info.get("passport_mime") or "").lower()
            ext = ".png" if "png" in mime else ".jpg"
            try:
                fd, temp_img_path = tempfile.mkstemp(suffix=ext)
                with os.fdopen(fd, "wb") as tmp_f:
                    tmp_f.write(bytes(photo_bytes))
                pdf.set_draw_color(*gold)
                pdf.set_line_width(0.7)
                pdf.rect(246, 82, 31, 37)
                pdf.image(temp_img_path, x=247, y=83, w=29, h=35)
            except Exception:
                if temp_img_path and os.path.exists(temp_img_path):
                    os.remove(temp_img_path)
                temp_img_path = None

        pdf.set_xy(25, 88)
        pdf.set_font("Arial", "", 11)
        pdf.set_text_color(55, 55, 55)
        pdf.cell(247, 7, "This is to certify that", align="C")

        student_name = pdf_safe_text(student_info["full_name"]).upper()
        pdf.set_xy(22, 99)
        pdf.set_font("Arial", "B", 24)
        pdf.set_text_color(*navy)
        while pdf.get_string_width(student_name) > 235 and pdf.font_size_pt > 14:
            pdf.set_font_size(pdf.font_size_pt - 1)
        pdf.cell(253, 12, student_name, align="C")
        pdf.set_draw_color(*gold)
        pdf.set_line_width(0.6)
        pdf.line(70, 113, 227, 113)

        # Admission details in a quiet, readable information band.
        pdf.set_fill_color(*pale)
        pdf.set_draw_color(220, 226, 234)
        pdf.rect(31, 119, 235, 12, style="DF")
        pdf.set_xy(34, 122)
        pdf.set_font("Arial", "B", 8.5)
        pdf.set_text_color(*muted)
        details = (
            f"ADMISSION NO.: {student_info['student_id']}     |     "
            f"CLASS / GRADE: {student_info['class_level']}     |     "
            f"PROGRAMME: {student_info['program']}"
        )
        while pdf.get_string_width(pdf_safe_text(details)) > 226 and pdf.font_size_pt > 7:
            pdf.set_font_size(pdf.font_size_pt - 0.5)
        pdf.cell(229, 6, pdf_safe_text(details), align="C")

        # Citation is wrapped and constrained to its own reserved area.
        citation = pdf_safe_text(citation_text).replace("\r", " ").replace("\n", " ")
        pdf.set_font("Arial", "", 10)
        words, lines, current = citation.split(), [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and pdf.get_string_width(candidate) > 220:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        lines = lines[:4]
        if len(words) and not lines:
            lines = [citation[:120]]
        pdf.set_xy(37, 137)
        pdf.set_font("Arial", "", 10)
        pdf.set_text_color(55, 55, 55)
        pdf.multi_cell(223, 5.5, "\n".join(lines), align="C")

        # Signature blocks and issue information.
        pdf.set_draw_color(120, 130, 145)
        pdf.set_line_width(0.35)
        pdf.line(35, 177, 105, 177)
        pdf.line(114, 177, 184, 177)
        pdf.line(193, 177, 263, 177)
        pdf.set_xy(30, 179)
        pdf.set_font("Arial", "B", 8)
        pdf.set_text_color(*navy)
        pdf.cell(80, 5, "CLASS TEACHER", align="C")
        pdf.cell(80, 5, "OFFICIAL SCHOOL STAMP", align="C")
        pdf.cell(80, 5, "HEADTEACHER / AUTHORIZED OFFICIAL", align="C")
        pdf.set_xy(193, 184)
        pdf.set_font("Arial", "", 7.5)
        pdf.set_text_color(*muted)
        pdf.cell(70, 4, pdf_safe_text(manager_name), align="C")
        pdf.set_xy(30, 184)
        pdf.set_font("Arial", "", 7.5)
        pdf.set_text_color(*muted)
        pdf.cell(80, 4, "Name and signature", align="C")
        pdf.set_xy(114, 184)
        pdf.cell(80, 4, pdf_safe_text(f"DATE OF ISSUE: {issued_date}"), align="C")
        pdf.set_xy(18, 190)
        pdf.set_font("Arial", "", 7)
        pdf.set_text_color(105, 105, 105)
        pdf.cell(261, 4, pdf_safe_text(f"Certificate No.: {cert_no}"), align="C")

        result = validate_pdf_bytes(pdf_output_bytes(pdf))
        return result
    finally:
        if temp_img_path and os.path.exists(temp_img_path):
            try:
                os.remove(temp_img_path)
            except OSError:
                pass


# ---------------------------------------------------------
# 4. STREAMLIT UI, EDUCATIONAL THEME & AUTHENTICATION
# ---------------------------------------------------------
def _focus_next_field_js():
    st.components.v1.html(
        """
        <script>
        (function() {
            const doc = window.parent.document;
            if (doc.__enterNavBound) return;
            doc.__enterNavBound = true;
            function advanceFrom(el) {
                const inputs = Array.from(doc.querySelectorAll('input[type="text"], input[type="number"], textarea'))
                    .filter(item => !item.disabled && item.offsetParent !== null);
                const idx = inputs.indexOf(el);
                if (idx >= 0 && idx < inputs.length - 1) {
                    const nextEl = inputs[idx + 1];
                    nextEl.scrollIntoView({ behavior: "smooth", block: "center" });
                    setTimeout(() => {
                        nextEl.focus();
                        if (typeof nextEl.select === "function" && nextEl.tagName === "INPUT") {
                            nextEl.select();
                        }
                    }, 30);
                }
            }
            doc.addEventListener("keydown", function(e) {
                if (e.key !== "Enter" && e.keyCode !== 13) return;
                const active = doc.activeElement;
                if (!active) return;
                if (active.tagName === "INPUT" && (active.type === "text" || active.type === "number")) {
                    e.preventDefault();
                    advanceFrom(active);
                }
            }, true);
        })();
        </script>
        """,
        height=0,
    )


def focus_required_input(label_text: str):
    """Moves focus/cursor back to the missing required input field without clearing cached/entered values."""
    import json
    safe_label = json.dumps(label_text)
    st.components.v1.html(
        f"""
        <script>
        (function() {{
            const doc = window.parent.document;
            const targetText = ({safe_label}).toLowerCase().trim();
            const containers = Array.from(doc.querySelectorAll('[data-testid="stTextInput"], [data-testid="stTextArea"], [data-testid="stNumberInput"]'));
            for (const box of containers) {{
                const lbl = box.querySelector('label');
                const txt = (lbl ? lbl.innerText : box.innerText || '').toLowerCase().trim();
                if (txt.includes(targetText)) {{
                    const field = box.querySelector('input, textarea');
                    if (field && !field.disabled) {{
                        box.scrollIntoView({{ behavior: "smooth", block: "center" }});
                        setTimeout(() => {{
                            field.focus();
                            if (typeof field.select === "function") {{
                                field.select();
                            }}
                        }}, 60);
                        break;
                    }}
                }}
            }}
        }})();
        </script>
        """,
        height=0,
    )


st.set_page_config(page_title=f"{SCHOOL_NAME} - SMS", page_icon="🏫", layout="wide")
init_db()

st.markdown(
    """
    <style>
    .stApp {
        background-color: #F4F7FB;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='260' height='260' viewBox='0 0 260 260'%3E%3Cg fill='none' stroke='%231B365D' stroke-width='1.5' stroke-opacity='0.09'%3E%3Cpath d='M30 45 Q50 35 70 45 L70 80 Q50 70 30 80 Z'/%3E%3Cpath d='M70 45 Q90 35 110 45 L110 80 Q90 70 70 80 Z'/%3E%3Cpolygon points='185,35 220,50 185,65 150,50'/%3E%3Cpath d='M165,57 L165,72 Q185,82 205,72 L205,57'/%3E%3Cline x1='220' y1='50' x2='220' y2='72'/%3E%3Cpolygon points='45,155 55,145 95,185 85,195'/%3E%3Cpolygon points='95,185 102,202 85,195'/%3E%3Ccircle cx='185' cy='175' r='24'/%3E%3Cellipse cx='185' cy='175' rx='10' ry='24'/%3E%3Cline x1='161' y1='175' x2='209' y2='175'/%3E%3Cpath d='M165,205 L205,205 M185,199 L185,205'/%3E%3Ctext x='115' y='125' font-family='Georgia, serif' font-size='16' fill='%231B365D' fill-opacity='0.10' stroke='none'%3EE = mc%C2%B2%3C/text%3E%3Ctext x='25' y='235' font-family='Georgia, serif' font-size='15' fill='%231B365D' fill-opacity='0.10' stroke='none'%3EA%2BB=C%3C/text%3E%3Ctext x='145' y='240' font-family='Georgia, serif' font-size='16' fill='%231B365D' fill-opacity='0.10' stroke='none'%3E%CF%80 %E2%88%91 %E2%88%9A%3C/text%3E%3C/g%3E%3C/svg%3E");
        background-repeat: repeat;
    }

    .block-container {
        background-color: rgba(255, 255, 255, 0.96);
        border-radius: 12px;
        padding: 2rem 2.2rem !important;
        margin-top: 1rem;
        box-shadow: 0 4px 18px rgba(27, 54, 93, 0.08);
        border: 1px solid #D6E0EC;
    }

    section[data-testid="stSidebar"] {
        background-color: #EDF2F8;
        border-right: 2px solid #CBD7E6;
    }

    label, .stTextInput label, .stSelectbox label, .stNumberInput label,
    .stTextArea label, .stRadio label, .stCheckbox label, .stFileUploader label,
    div[data-testid="stWidgetLabel"] p {
        color: #0F2342 !important;
        font-weight: 700 !important;
        font-size: 0.96rem !important;
        background-color: rgba(255, 255, 255, 0.88);
        padding: 2px 6px;
        border-radius: 4px;
    }

    h1, h2, h3, h4 {
        color: #1B365D !important;
    }

    div[data-testid="stMetric"] {
        background-color: #F8FAFD;
        border: 1px solid #D0DCEA;
        padding: 12px 14px;
        border-radius: 8px;
    }
    div[data-testid="stMetricLabel"] p {
        color: #1B365D !important;
        font-weight: 700 !important;
    }
    div[data-testid="stMetricValue"] {
        color: #0D1F3C !important;
    }

    div[data-testid="stForm"] {
        background-color: #FAFCFF;
        border: 1.5px solid #C8D6E5;
        border-radius: 10px;
        padding: 18px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "user" not in st.session_state:
    st.session_state.user = None

# Top Header Banner
st.markdown(
    f"""
    <div style="background: linear-gradient(135deg, #1B365D 0%, #274C77 100%);padding:20px;border-radius:10px;color:white;margin-bottom:18px;border-bottom:4px solid #D4A017;">
        <h2 style="margin:0;color:white !important;">🏫 {SCHOOL_NAME}</h2>
        <p style="margin:5px 0 0 0;font-size:14px;color:#E8F0FA;">📍 {SCHOOL_LOCATION} &nbsp;|&nbsp; 📚 <em>"{SCHOOL_MOTTO}"</em></p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Automatic integrity check & safety banner for Admins
if os.path.exists(DB_FILE):
    try:
        _chk = sqlite3.connect(DB_FILE, timeout=15.0)
        _chk_res = _chk.execute("PRAGMA integrity_check").fetchone()[0]
        _chk.close()
        if str(_chk_res).lower() != "ok":
            st.error(f"Database integrity notice: {_chk_res}. A backup snapshot can be restored from db_backups/.")
    except Exception as _e:
        st.warning(f"Database check warning: {_e}")

# Login Screen
if st.session_state.user is None:
    col_l, col_c, col_r = st.columns([1, 1.4, 1])
    with col_c:
        st.subheader("🔐 Staff, Teacher & School Manager Login")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login_btn = st.form_submit_button("Sign In", use_container_width=True)
            if login_btn:
                conn = get_connection()
                c = conn.cursor()
                c.execute(
                    "SELECT username, password_hash, full_name, role, assigned_subject, passport_photo FROM users WHERE username = ?",
                    (username.strip(),),
                )
                user_row = c.fetchone()
                if user_row and verify_password(password, user_row["password_hash"]):
                    # Upgrade older unsalted hashes only after a successful login.
                    if not user_row["password_hash"].startswith("pbkdf2_sha256$"):
                        c.execute(
                            "UPDATE users SET password_hash = ? WHERE username = ?",
                            (hash_password(password), user_row["username"]),
                        )
                        conn.commit()
                    conn.close()
                    st.session_state.user = {
                        "username": user_row["username"],
                        "full_name": user_row["full_name"],
                        "role": user_row["role"],
                        "assigned_subject": user_row["assigned_subject"],
                        "passport_photo": user_row["passport_photo"],
                    }
                    st.rerun()
                else:
                    conn.close()
                    st.error("Invalid username or password.")

        with st.expander("ℹ️ Sign-In Guidance"):
            st.markdown(
                "Sign in with your assigned staff, teacher, school manager, or bursar credentials."
            )
    st.stop()

# Logged-in account is refreshed on every rerun so role changes take effect immediately.
user = st.session_state.user
_auth_conn = get_connection()
_auth_row = _auth_conn.execute(
    "SELECT username, full_name, role, assigned_subject, passport_photo FROM users WHERE username = ?",
    (user.get("username"),),
).fetchone()
if not _auth_row:
    _auth_conn.close()
    st.session_state.user = None
    st.error("This account is no longer available. Please sign in again.")
    st.stop()
user = dict(_auth_row)
st.session_state.user = user
nav_options = get_effective_permissions(_auth_conn, user["username"], user["role"])
_auth_conn.close()
if user.get("passport_photo"):
    st.sidebar.image(user["passport_photo"], caption=f"{user['full_name']} ({user['role']})", width=120)
st.sidebar.success(f"👤 **{user['full_name']}**\n\nRole: `{user['role']}`")
try:
    _notice_conn = get_connection()
    _notices = _notice_conn.execute(
        "SELECT notification_id, title, message, created_at FROM app_notifications WHERE recipient_username=? AND is_read=0 ORDER BY notification_id DESC LIMIT 20",
        (user["username"],),
    ).fetchall()
    if _notices:
        with st.sidebar.expander(f"🔔 Notifications ({len(_notices)})", expanded=True):
            for _notice in _notices:
                st.warning(f"**{_notice['title']}**\n\n{_notice['message']}\n\n{_notice['created_at']}")
                if st.button("Mark as read", key=f"read_notice_{_notice['notification_id']}"):
                    _notice_conn.execute("UPDATE app_notifications SET is_read=1 WHERE notification_id=? AND recipient_username=?", (_notice["notification_id"], user["username"]))
                    _notice_conn.commit()
                    st.rerun()
    _notice_conn.close()
except Exception:
    try: _notice_conn.close()
    except Exception: pass
if st.sidebar.button("Logout"):
    st.session_state.user = None
    st.rerun()

with st.sidebar.expander("🔐 Change My Password"):
    # Widgets inside a form must use the active container (st.*), not
    # st.sidebar.* again. Re-entering the sidebar context while a form is
    # active triggers StreamlitInvalidLayoutContextError.
    with st.form(f"change_password_form_{user['username']}"):
        current_password = st.text_input(
            "Current Password", type="password",
            key=f"current_password_{user['username']}"
        )
        new_password = st.text_input(
            "New Password (10+ characters)", type="password",
            key=f"new_password_{user['username']}"
        )
        confirm_new_password = st.text_input(
            "Confirm New Password", type="password",
            key=f"confirm_password_{user['username']}"
        )
        change_password_clicked = st.form_submit_button("Update My Password")

    if change_password_clicked:
        password_conn = get_connection()
        try:
            stored_row = password_conn.execute(
                "SELECT password_hash FROM users WHERE username = ?",
                (user["username"],)
            ).fetchone()
            if not stored_row or not verify_password(current_password, stored_row["password_hash"]):
                st.sidebar.error("The current password is incorrect.")
            elif len(new_password) < 10:
                st.sidebar.error("New password must contain at least 10 characters.")
            elif new_password != confirm_new_password:
                st.sidebar.error("The new password and confirmation do not match.")
            elif new_password == current_password:
                st.sidebar.error("Choose a new password different from your current password.")
            else:
                password_conn.execute(
                    "UPDATE users SET password_hash = ? WHERE username = ?",
                    (hash_password(new_password), user["username"]),
                )
                write_audit_log(
                    password_conn, user["username"], user["role"],
                    "Password changed", "Account owner changed their password"
                )
                password_conn.commit()
                st.sidebar.success("Your password has been updated securely.")
        except Exception:
            password_conn.rollback()
            st.sidebar.error("Your password could not be updated. Please try again.")
            raise
        finally:
            password_conn.close()

if not nav_options:
    st.error("No modules are assigned to this account. Please contact the system administrator.")
    st.stop()
menu = st.sidebar.radio("System Modules", nav_options)
if menu not in nav_options:
    st.error("You do not have permission to open this module.")
    st.stop()
_focus_next_field_js()


# ---------------------------------------------------------
# MODULE 1: DASHBOARD, GENDER TOTALS & INTERACTIVE FILTERS
# ---------------------------------------------------------
if menu == "📊 Dashboard, Gender Totals & Filters":
    st.header("School Population, Gender Breakdown & Filtered Directory")
    conn = get_connection()
    df_students = pd.read_sql_query(
        "SELECT student_id, full_name, gender, class_level, program, boarding_status, guardian_name, guardian_phone, status, date_registered FROM students",
        conn,
    )
    df_teachers = pd.read_sql_query(
        "SELECT staff_id, full_name, gender, phone, email, academic_programme, department, assigned_subject, status, employment_date FROM teachers",
        conn,
    )
    df_fees = pd.read_sql_query("SELECT * FROM fee_payments", conn)
    df_occasions = pd.read_sql_query("SELECT * FROM special_occasions ORDER BY created_at DESC LIMIT 5", conn)
    df_incidents = pd.read_sql_query("SELECT * FROM incident_reports ORDER BY created_at DESC LIMIT 5", conn)
    if user["role"] in ("Teacher", "ICT Teacher"):
        _allowed_classes = set(get_teacher_assigned_classes(conn, user["username"]))
        df_students = df_students[df_students["class_level"].isin(_allowed_classes)].drop(
            columns=["guardian_name", "guardian_phone"], errors="ignore"
        )
        df_teachers = df_teachers.iloc[0:0]
        df_fees = df_fees.iloc[0:0]
        df_occasions = df_occasions.iloc[0:0]
        df_incidents = df_incidents.iloc[0:0]
    elif user["role"] == "Bursar":
        df_teachers = df_teachers.iloc[0:0]
        df_occasions = df_occasions.iloc[0:0]
        df_incidents = df_incidents.iloc[0:0]
        df_students = df_students[["student_id", "full_name", "gender", "class_level", "program", "status"]]
    conn.close()

    # Exact Gender Totals across Learners, Teachers, and Combined School Population
    active_stu = df_students[df_students["status"] == "Active"] if not df_students.empty else df_students
    active_tch = df_teachers[df_teachers["status"] == "Active"] if not df_teachers.empty else df_teachers

    male_students = len(active_stu[active_stu["gender"] == "Male"]) if not active_stu.empty else 0
    female_students = len(active_stu[active_stu["gender"] == "Female"]) if not active_stu.empty else 0

    male_teachers = len(active_tch[active_tch["gender"] == "Male"]) if not active_tch.empty else 0
    female_teachers = len(active_tch[active_tch["gender"] == "Female"]) if not active_tch.empty else 0

    all_male = male_students + male_teachers
    all_female = female_students + female_teachers
    total_collected = df_fees["amount_paid"].sum() if not df_fees.empty else 0.0

    st.subheader("📌 School-Wide Gender & Population Summary")
    r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
    r1_c1.metric("Total Male Teachers", male_teachers)
    r1_c2.metric("Total Female Teachers", female_teachers)
    r1_c3.metric("All Male (Learners + Teachers)", all_male)
    r1_c4.metric("All Female (Learners + Teachers)", all_female)

    r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)
    r2_c1.metric("Male Learners", male_students)
    r2_c2.metric("Female Learners", female_students)
    r2_c3.metric("Total Active Learners", len(active_stu))
    r2_c4.metric("Total Fees Collected", f"GHS {total_collected:,.2f}")

    st.divider()

    # Interactive Filters Section (including Gender Filters)
    st.subheader("🔍 Filter Directory (By Role, Gender, Class / Grade Level & Programme)")
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        record_scope = st.selectbox("Directory Group", ["Learners", "Teachers", "Combined Population"])
    with f_col2:
        gender_filter = st.selectbox("Filter by Gender", ["All Genders", "Male", "Female"])
    with f_col3:
        class_filter = st.selectbox("Filter by Class / Grade", ["All Classes"] + CLASS_LEVELS)
    with f_col4:
        search_text = st.text_input("Search by Name or ID", placeholder="Type name or ID...")

    if record_scope == "Learners":
        filtered_df = df_students.copy()
        if not filtered_df.empty:
            if gender_filter != "All Genders":
                filtered_df = filtered_df[filtered_df["gender"] == gender_filter]
            if class_filter != "All Classes":
                filtered_df = filtered_df[filtered_df["class_level"] == class_filter]
            if search_text.strip():
                q = search_text.strip().lower()
                filtered_df = filtered_df[
                    filtered_df["full_name"].str.lower().str.contains(q, na=False)
                    | filtered_df["student_id"].str.lower().str.contains(q, na=False)
                ]
        st.caption(f"Showing **{len(filtered_df)}** matching learner record(s).")
        st.dataframe(filtered_df, use_container_width=True)

    elif record_scope == "Teachers":
        filtered_df = df_teachers.copy()
        if not filtered_df.empty:
            if gender_filter != "All Genders":
                filtered_df = filtered_df[filtered_df["gender"] == gender_filter]
            if search_text.strip():
                q = search_text.strip().lower()
                filtered_df = filtered_df[
                    filtered_df["full_name"].str.lower().str.contains(q, na=False)
                    | filtered_df["staff_id"].str.lower().str.contains(q, na=False)
                    | filtered_df["assigned_subject"].str.lower().str.contains(q, na=False)
                ]
        st.caption(f"Showing **{len(filtered_df)}** matching teacher record(s).")
        st.dataframe(filtered_df, use_container_width=True)

    else:
        stu_part = pd.DataFrame()
        if not df_students.empty:
            stu_part = df_students[["student_id", "full_name", "gender", "class_level", "program", "status"]].copy()
            stu_part.columns = ["ID", "Full Name", "Gender", "Class / Dept", "Programme / Subject", "Status"]
            stu_part["Category"] = "Learner"

        tch_part = pd.DataFrame()
        if not df_teachers.empty:
            tch_part = df_teachers[["staff_id", "full_name", "gender", "department", "assigned_subject", "status"]].copy()
            tch_part.columns = ["ID", "Full Name", "Gender", "Class / Dept", "Programme / Subject", "Status"]
            tch_part["Category"] = "Teacher"

        combined_df = pd.concat([stu_part, tch_part], ignore_index=True)
        if not combined_df.empty:
            if gender_filter != "All Genders":
                combined_df = combined_df[combined_df["Gender"] == gender_filter]
            if class_filter != "All Classes":
                combined_df = combined_df[combined_df["Class / Dept"] == class_filter]
            if search_text.strip():
                q = search_text.strip().lower()
                combined_df = combined_df[
                    combined_df["Full Name"].str.lower().str.contains(q, na=False)
                    | combined_df["ID"].str.lower().str.contains(q, na=False)
                ]
        st.caption(f"Showing **{len(combined_df)}** combined record(s).")
        st.dataframe(combined_df, use_container_width=True)

    st.divider()
    if not active_stu.empty:
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Learners by Class / Grade Level")
            st.bar_chart(active_stu["class_level"].value_counts())
        with col_b:
            st.subheader("School Gender Distribution (All Male vs All Female)")
            gender_chart_df = pd.DataFrame(
                {"Count": [male_students, female_students, male_teachers, female_teachers]},
                index=["Male Learners", "Female Learners", "Male Teachers", "Female Teachers"],
            )
            st.bar_chart(gender_chart_df)

    st.divider()
    h1, h2 = st.columns(2)
    with h1:
        st.subheader("🎉 Recent Special Activities & Occasions")
        if df_occasions.empty:
            st.caption("No special occasions recorded yet.")
        else:
            for _, occ in df_occasions.iterrows():
                st.info(f"**{occ['title']}** ({occ['occasion_type']} • {occ['event_date']})\n\n{occ['summary']}")
    with h2:
        st.subheader("⚠️ Recent Incident Reports")
        if df_incidents.empty:
            st.caption("No incidents reported.")
        else:
            for _, inc in df_incidents.iterrows():
                st.warning(f"**{inc['class_level']} — {inc['involved_person']}** [{inc['severity']}] ({inc['incident_date']})\n\n{inc['description']}")


# ---------------------------------------------------------
# MODULE 2: STUDENT REGISTRATION & EDITING
# ---------------------------------------------------------
elif menu == "📝 Student Registration & Edit":
    st.header("Learner Registration & Record Editing")
    st.caption("Form inputs stay intact until you click **Register Learner** or **Save Learner Changes**.")

    conn = get_connection()
    c = conn.cursor()
    suggested_adm_no = generate_unique_admission_number(conn, "Mensah", "Kwame", "Boateng")

    tab_reg, tab_edit = st.tabs(["➕ Register New Learner", "✏️ Edit Existing Learner Entry"])

    with tab_reg:
        st.markdown("#### Learner Name & Auto Admission Number")
        n1, n2, n3 = st.columns(3)
        with n1:
            st.text_input("Surname *", placeholder="e.g., Mensah", key="reg_student_surname", on_change=capitalize_name_widget, args=("reg_student_surname",))
        with n2:
            st.text_input("First Name *", placeholder="e.g., Kwame", key="reg_student_first_name", on_change=capitalize_name_widget, args=("reg_student_first_name",))
        with n3:
            st.text_input("Middle Name (Optional)", placeholder="e.g., Boateng", key="reg_student_middle_name", on_change=capitalize_name_widget, args=("reg_student_middle_name",))
        surname = st.session_state.get("reg_student_surname", "")
        first_name = st.session_state.get("reg_student_first_name", "")
        middle_name = st.session_state.get("reg_student_middle_name", "")

        with st.form("student_registration_form", clear_on_submit=False):
            a1, a2 = st.columns(2)
            with a1:
                auto_gen = st.checkbox("Auto-generate Admission Number from Name + Number", value=True)
                st.caption(f"Sample auto format: `{suggested_adm_no}` (generated dynamically on submit)")
            with a2:
                custom_adm_no = st.text_input("Manual Admission Number (if unchecked)", placeholder="e.g., GIS-MK-2026-010")

            st.markdown("#### Class / Grade Level, Programme & Passport Photo")
            c1, c2 = st.columns(2)
            with c1:
                gender = st.selectbox("Gender *", ["Male", "Female"])
                class_level = st.selectbox("Class / Grade Level *", CLASS_LEVELS)
                program = st.selectbox(
                    "Academic / Class Programme *",
                    ["General Basic / Primary", "General Science", "General Arts", "Business", "Visual Arts", "Home Economics", "Agricultural Science"],
                )
            with c2:
                boarding_status = st.selectbox("Residential Status *", ["Day", "Boarding"])
                guardian_name = st.text_input("Parent / Guardian Name", placeholder="e.g., Mr. Kofi Mensah")
                guardian_phone = st.text_input("Parent / Guardian Phone", placeholder="e.g., 024XXXXXXX")
                passport_file = st.file_uploader("Upload Passport-Sized Picture (Student)", type=["png", "jpg", "jpeg"])

            confirm_reg = st.checkbox("I confirm all learner details above are accurate before submitting.")
            submitted = st.form_submit_button("Register Learner")

            if submitted:
                if not surname.strip():
                    st.error("Surname is required. Cursor moved back to Surname.")
                    focus_required_input("Surname")
                elif not first_name.strip():
                    st.error("First Name is required. Cursor moved back to First Name.")
                    focus_required_input("First Name")
                elif not confirm_reg:
                    st.error("Please tick the confirmation box before submitting.")
                else:
                    adm_no = (
                        generate_unique_admission_number(conn, surname.strip(), first_name.strip(), middle_name.strip())
                        if auto_gen
                        else custom_adm_no.strip().upper()
                    )
                    if not adm_no:
                        st.error("Please provide an Admission Number or enable Auto-generate.")
                    else:
                        full_nm = format_full_name(surname, first_name, middle_name)
                        photo_bytes = passport_file.getvalue() if passport_file is not None else None
                        photo_mime = passport_file.type if passport_file is not None else None
                        try:
                            c.execute(
                                """
                                INSERT INTO students (
                                    student_id, surname, first_name, middle_name, full_name,
                                    gender, class_level, program, boarding_status,
                                    guardian_name, guardian_phone, passport_photo, passport_mime, date_registered
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    adm_no,
                                    capitalize_initials(surname),
                                    capitalize_initials(first_name),
                                    capitalize_initials(middle_name),
                                    full_nm,
                                    gender,
                                    class_level,
                                    program,
                                    boarding_status,
                                    guardian_name.strip(),
                                    guardian_phone.strip(),
                                    photo_bytes,
                                    photo_mime,
                                    datetime.now().strftime("%Y-%m-%d"),
                                ),
                            )
                            conn.commit()
                            write_audit_log(conn, user["username"], user["role"], "Learner registered", f"{adm_no} | {full_nm} | {class_level}")
                            conn.commit()
                            st.success(f"Learner **{full_nm}** registered with Admission No. **`{adm_no}`**!")
                        except sqlite3.IntegrityError:
                            conn.rollback()
                            st.error(f"Admission Number `{adm_no}` already exists. Please review the details and submit again.")

    with tab_edit:
        students_rows = c.execute("SELECT * FROM students ORDER BY full_name ASC").fetchall()
        teachers_all = c.execute("SELECT staff_id, full_name, assigned_subject, assigned_class_level FROM teachers WHERE status='Active' ORDER BY full_name ASC").fetchall()
        tch_lookup = {f"{t['full_name']} ({t['staff_id']} • {t['assigned_subject']})": (t["staff_id"], t["full_name"]) for t in teachers_all}

        if not students_rows:
            st.info("No learners in the database to edit yet.")
        else:
            student_map = {f"{r['student_id']} — {r['full_name']} ({r['class_level']})": r["student_id"] for r in students_rows}
            selected_key = st.selectbox("Select Learner to Inspect / Edit", list(student_map.keys()))
            rec = dict(c.execute("SELECT * FROM students WHERE student_id = ?", (student_map[selected_key],)).fetchone())

            is_admin = user["role"] == "Admin"
            is_edit_permitted = is_admin or (int(rec.get("student_edit_locked", 1)) == 0)

            st.info(
                f"🔒 **Protected Student Data Status:** {'Unlocked for Editing' if is_edit_permitted else 'Protected (Admin permission required to edit learner entries)'} "
                f"| **Assigned Teacher:** {rec.get('assigned_teacher_name') or 'Unassigned'}"
            )

            if is_admin:
                with st.expander("🛡️ Admin Edit Permission & Teacher Assignment for This Learner", expanded=True):
                    ap1, ap2 = st.columns(2)
                    with ap1:
                        allow_non_admin_edit = st.checkbox(
                            "Permit non-Admin users (e.g., School Manager) to edit this learner's entry",
                            value=(int(rec.get("student_edit_locked", 1)) == 0),
                            key=f"perm_edit_{rec['student_id']}",
                        )
                    with ap2:
                        tch_keys = ["Unassigned"] + list(tch_lookup.keys())
                        cur_tch_idx = 0
                        for idx_k, k_str in enumerate(tch_keys):
                            if rec.get("assigned_teacher_staff_id") and f"({rec['assigned_teacher_staff_id']} " in k_str:
                                cur_tch_idx = idx_k
                                break
                        chosen_tch_key = st.selectbox("Assign Teacher to Learner", tch_keys, index=cur_tch_idx, key=f"assign_tch_{rec['student_id']}")

                    if st.button("Save Admin Edit Permission & Teacher Assignment"):
                        try:
                            new_lock_val = 0 if allow_non_admin_edit else 1
                            if chosen_tch_key == "Unassigned":
                                t_sid_val, t_nm_val = None, None
                            else:
                                t_sid_val, t_nm_val = tch_lookup[chosen_tch_key]
                            create_db_backup("admin_perm_assign")
                            c.execute(
                                "UPDATE students SET student_edit_locked=?, assigned_teacher_staff_id=?, assigned_teacher_name=? WHERE student_id=?",
                                (new_lock_val, t_sid_val, t_nm_val, rec["student_id"]),
                            )
                            conn.commit()
                            st.success(f"Updated edit permission and teacher assignment for **{rec['full_name']}**.")
                            st.rerun()
                        except Exception as db_err:
                            conn.rollback()
                            st.error(f"Could not update permission/assignment: {db_err}")

            if rec.get("passport_photo"):
                st.image(rec["passport_photo"], caption=f"Current Passport Photo: {rec['full_name']}", width=120)

            with st.form("edit_student_form"):
                e1, e2, e3 = st.columns(3)
                with e1:
                    ed_surname = st.text_input("Surname", value=rec["surname"] or "", disabled=not is_edit_permitted)
                with e2:
                    ed_first = st.text_input("First Name", value=rec["first_name"] or "", disabled=not is_edit_permitted)
                with e3:
                    ed_middle = st.text_input("Middle Name", value=rec["middle_name"] or "", disabled=not is_edit_permitted)

                f1, f2, f3 = st.columns(3)
                with f1:
                    ed_gender = st.selectbox("Gender", ["Male", "Female"], index=0 if rec["gender"] == "Male" else 1, disabled=not is_edit_permitted)
                with f2:
                    cls_idx = CLASS_LEVELS.index(rec["class_level"]) if rec["class_level"] in CLASS_LEVELS else 0
                    ed_class = st.selectbox("Class / Grade Level", CLASS_LEVELS, index=cls_idx, disabled=not is_edit_permitted)
                with f3:
                    ed_boarding = st.selectbox("Residential Status", ["Day", "Boarding"], index=0 if rec["boarding_status"] == "Day" else 1, disabled=not is_edit_permitted)

                g1, g2, g3 = st.columns(3)
                with g1:
                    ed_gname = st.text_input("Guardian Name", value=rec["guardian_name"] or "", disabled=not is_edit_permitted)
                with g2:
                    ed_gphone = st.text_input("Guardian Phone", value=rec["guardian_phone"] or "", disabled=not is_edit_permitted)
                with g3:
                    ed_status = st.selectbox("Status", ["Active", "Transferred", "Graduated"], index=["Active", "Transferred", "Graduated"].index(rec["status"]) if rec["status"] in ["Active", "Transferred", "Graduated"] else 0, disabled=not is_edit_permitted)

                ed_photo = st.file_uploader("Replace Passport Picture (Optional)", type=["png", "jpg", "jpeg"], key="edit_stu_photo", disabled=not is_edit_permitted)
                confirm_edit = st.checkbox("Confirm spelling / record corrections before saving.", disabled=not is_edit_permitted)

                if st.form_submit_button("Save Learner Changes", disabled=not is_edit_permitted):
                    if not is_edit_permitted:
                        st.error("Student data is protected. Ask an Admin to permit editing of this learner entry.")
                    elif not confirm_edit:
                        st.error("Please tick the confirmation box to save edits.")
                    elif not ed_surname.strip() or not ed_first.strip():
                        st.error("Surname and First Name cannot be empty.")
                    else:
                        try:
                            create_db_backup("student_edit")
                            new_full = format_full_name(ed_surname, ed_first, ed_middle)
                            new_photo = ed_photo.getvalue() if ed_photo is not None else rec["passport_photo"]
                            new_mime = ed_photo.type if ed_photo is not None else rec["passport_mime"]
                            c.execute(
                                """
                                UPDATE students
                                SET surname=?, first_name=?, middle_name=?, full_name=?,
                                    gender=?, class_level=?, boarding_status=?,
                                    guardian_name=?, guardian_phone=?, status=?,
                                    passport_photo=?, passport_mime=?
                                WHERE student_id=?
                                """,
                                (
                                    ed_surname.strip(),
                                    ed_first.strip(),
                                    ed_middle.strip(),
                                    new_full,
                                    ed_gender,
                                    ed_class,
                                    ed_boarding,
                                    ed_gname.strip(),
                                    ed_gphone.strip(),
                                    ed_status,
                                    new_photo,
                                    new_mime,
                                    rec["student_id"],
                                ),
                            )
                            conn.commit()
                            st.success(f"Updated learner entry for **{new_full}** (`{rec['student_id']}`)!")
                        except Exception as db_err:
                            conn.rollback()
                            st.error(f"Database error while saving learner changes: {db_err}")

        if user["role"] == "Admin":
            st.divider()
            st.subheader("👨‍🏫 Admin Privilege: Students Registered Under a Particular Teacher & Counts")
            if not teachers_all:
                st.info("No active teachers registered yet.")
            else:
                t_sel_map = {f"{t['full_name']} ({t['staff_id']} • Subject: {t['assigned_subject']})": t for t in teachers_all}
                chosen_t_label = st.selectbox("Select Teacher to View Registered Students & Counts", list(t_sel_map.keys()), key="admin_view_tch_students")
                t_info_obj = t_sel_map[chosen_t_label]

                # Match direct learner assignments, timetable assignments, or any allocated class.
                t_class_rows = c.execute(
                    "SELECT class_level FROM teacher_class_assignments WHERE staff_id = ?",
                    (t_info_obj["staff_id"],),
                ).fetchall()
                t_assigned_classes = [row["class_level"] for row in t_class_rows]
                if not t_assigned_classes:
                    legacy_class = (t_info_obj["assigned_class_level"] or "").strip()
                    t_assigned_classes = CLASS_LEVELS if legacy_class in ("", "All / Multiple Classes") else [
                        part.strip() for part in legacy_class.split(",") if part.strip() in CLASS_LEVELS
                    ]
                if not t_assigned_classes:
                    t_assigned_classes = CLASS_LEVELS
                placeholders = ",".join("?" for _ in t_assigned_classes)
                t_stu_df = pd.read_sql_query(
                    f"""
                    SELECT DISTINCT s.student_id AS 'Adm. No.', s.full_name AS 'Learner Name',
                           s.gender AS 'Gender', s.class_level AS 'Class',
                           s.program AS 'Programme', s.promotion_status AS 'Status',
                           CASE WHEN s.assigned_teacher_staff_id = ? THEN 'Directly Assigned' ELSE 'Class / Subject Roster' END AS 'Assignment Basis'
                    FROM students s
                    LEFT JOIN school_timetable tt
                           ON tt.class_level = s.class_level
                          AND tt.teacher_name = ?
                    WHERE s.status = 'Active'
                      AND (
                            s.assigned_teacher_staff_id = ?
                         OR s.assigned_teacher_name = ?
                         OR tt.teacher_name = ?
                         OR s.class_level IN ({placeholders})
                      )
                    ORDER BY s.class_level, s.full_name
                    """,
                    conn,
                    params=(
                        t_info_obj["staff_id"],
                        t_info_obj["full_name"],
                        t_info_obj["staff_id"],
                        t_info_obj["full_name"],
                        t_info_obj["full_name"],
                        *t_assigned_classes,
                    ),
                )

                tc1, tc2, tc3 = st.columns(3)
                tc1.metric("Total Students Under Teacher", len(t_stu_df))
                tc2.metric("Male Students", int((t_stu_df["Gender"] == "Male").sum()) if not t_stu_df.empty else 0)
                tc3.metric("Female Students", int((t_stu_df["Gender"] == "Female").sum()) if not t_stu_df.empty else 0)

                if t_stu_df.empty:
                    st.info(f"No active students are currently linked to **{t_info_obj['full_name']}**. You can assign learners to this teacher above or generate their class timetable.")
                else:
                    st.dataframe(t_stu_df, use_container_width=True)
                    by_cls_cnt = t_stu_df.groupby("Class").size().reset_index(name="Student Count")
                    st.caption("Count by Class / Grade Level")
                    st.dataframe(by_cls_cnt, use_container_width=True)

    st.divider()
    st.subheader("🎓 Student Promotion, Repeated, On Try & Probation")
    promo_choices = ["Promoted", "Repeated", "On Try", "Probation"]
    if not students_rows:
        st.info("No learners available for promotion management.")
    else:
        p_map = {f"{r['student_id']} — {r['full_name']} ({r['class_level']} | Status: {r['promotion_status'] or 'Promoted'})": r["student_id"] for r in students_rows}
        sel_p_label = st.selectbox("Select Learner for Progression / Status Update", list(p_map.keys()), key="promo_stu_select")
        p_rec = dict(c.execute("SELECT * FROM students WHERE student_id = ?", (p_map[sel_p_label],)).fetchone())

        with st.form("promotion_status_form"):
            pr1, pr2, pr3 = st.columns(3)
            with pr1:
                cur_p_idx = promo_choices.index(p_rec["promotion_status"]) if p_rec.get("promotion_status") in promo_choices else 0
                new_promo_status = st.selectbox("Progression Status", promo_choices, index=cur_p_idx)
            with pr2:
                cur_c_idx = CLASS_LEVELS.index(p_rec["class_level"]) if p_rec["class_level"] in CLASS_LEVELS else 0
                next_class_idx = min(cur_c_idx + 1, len(CLASS_LEVELS) - 1) if new_promo_status == "Promoted" else cur_c_idx
                target_promo_class = st.selectbox("Target Class / Grade Level", CLASS_LEVELS, index=next_class_idx)
            with pr3:
                promo_note = st.text_input("Promotion / Placement Note (Optional)", placeholder="e.g., End of term progression")

            conf_pr = st.checkbox("Confirm student progression status and class assignment.")
            if st.form_submit_button("Apply Progression Status"):
                if not conf_pr:
                    st.error("Please confirm before updating progression status.")
                else:
                    c.execute(
                        "UPDATE students SET class_level=?, promotion_status=? WHERE student_id=?",
                        (target_promo_class, new_promo_status, p_rec["student_id"]),
                    )
                    conn.commit()
                    st.success(f"**{p_rec['full_name']}** (`{p_rec['student_id']}`) set to **{new_promo_status}** in **{target_promo_class}**.")
                    st.rerun()

    st.divider()
    st.subheader("👥 Bulk Student Promotion / Placement")
    if students_rows:
        bulk_classes = sorted({r["class_level"] for r in students_rows if r["class_level"]})
        bulk_source = st.selectbox("Select current class", bulk_classes, key="bulk_promo_source")
        bulk_candidates = [dict(r) for r in students_rows if r["class_level"] == bulk_source]
        bulk_map = {f"{r['student_id']} — {r['full_name']}": r["student_id"] for r in bulk_candidates}
        bulk_selected_labels = st.multiselect("Select any number of learners to promote together", list(bulk_map.keys()), key="bulk_promo_students")
        with st.form("bulk_promotion_form"):
            bp1, bp2 = st.columns(2)
            with bp1:
                bulk_target_class = st.selectbox("New class / grade", CLASS_LEVELS, index=min(CLASS_LEVELS.index(bulk_source)+1, len(CLASS_LEVELS)-1) if bulk_source in CLASS_LEVELS else 0)
            with bp2:
                bulk_status = st.selectbox("New progression status", promo_choices, index=0)
            bulk_reason = st.text_input("Promotion note (optional)")
            bulk_confirm = st.checkbox("Confirm updating all selected learners")
            if st.form_submit_button("Promote Selected Learners"):
                if not bulk_selected_labels:
                    st.error("Select at least one learner.")
                elif not bulk_confirm:
                    st.error("Confirm the bulk promotion before saving.")
                else:
                    ids = [bulk_map[x] for x in bulk_selected_labels]
                    create_db_backup("bulk_student_promotion")
                    c.executemany("UPDATE students SET class_level=?, promotion_status=? WHERE student_id=?", [(bulk_target_class, bulk_status, sid) for sid in ids])
                    write_audit_log(conn, user["username"], user["role"], "Bulk student progression", f"{len(ids)} learners: {bulk_source} -> {bulk_target_class}; {bulk_status}; {bulk_reason}")
                    conn.commit()
                    st.success(f"Updated {len(ids)} learner(s) to {bulk_target_class}.")
                    st.rerun()

    if user["role"] == "Admin":
        st.divider()
        st.subheader("🛡️ Admin Privilege: Remove Student History (With Reason)")
        st.warning("Admin-only action: Permanently clears selected historical records for a learner and logs the mandatory reason.")
        if students_rows:
            h_map = {f"{r['student_id']} — {r['full_name']} ({r['class_level']})": r["student_id"] for r in students_rows}
            sel_h_label = st.selectbox("Select Learner Whose History Will Be Removed", list(h_map.keys()), key="hist_rem_stu")
            h_rec = dict(c.execute("SELECT * FROM students WHERE student_id = ?", (h_map[sel_h_label],)).fetchone())

            with st.form("admin_remove_history_form"):
                hist_sections = st.multiselect(
                    "Select Historical Records to Remove",
                    ["Assessments & Grades", "Fee Payment Ledger", "Attendance Register", "Issued Certificates"],
                    default=["Assessments & Grades"],
                )
                removal_reason = st.text_area("Mandatory Reason for Removing History *", placeholder="State why this student's historical records are being removed...")
                conf_rem = st.checkbox("I am the Administrator and confirm permanent removal of the selected history with the stated reason.")
                if st.form_submit_button("Remove Selected Student History"):
                    if not conf_rem:
                        st.error("Please tick the Admin confirmation box.")
                    elif not hist_sections:
                        st.error("Select at least one history category to remove.")
                    elif not removal_reason.strip():
                        st.error("A clear reason is required before removing student history.")
                    else:
                        sid_h = h_rec["student_id"]
                        if "Assessments & Grades" in hist_sections:
                            c.execute("DELETE FROM assessments WHERE student_id = ?", (sid_h,))
                        if "Fee Payment Ledger" in hist_sections:
                            c.execute("DELETE FROM fee_payments WHERE student_id = ?", (sid_h,))
                        if "Attendance Register" in hist_sections:
                            c.execute("DELETE FROM school_register WHERE student_id = ?", (sid_h,))
                        if "Issued Certificates" in hist_sections:
                            c.execute("DELETE FROM issued_certificates WHERE student_id = ?", (sid_h,))

                        c.execute(
                            """
                            INSERT INTO student_history_removal_logs (
                                student_id, student_name, class_level, removed_sections, reason, removed_by, removed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sid_h,
                                h_rec["full_name"],
                                h_rec["class_level"],
                                ", ".join(hist_sections),
                                removal_reason.strip(),
                                user["full_name"],
                                datetime.now().strftime("%Y-%m-%d %H:%M"),
                            ),
                        )
                        conn.commit()
                        st.success(f"Removed **{', '.join(hist_sections)}** for **{h_rec['full_name']}** (`{sid_h}`) and logged the reason.")
                        st.rerun()

        rem_logs_df = pd.read_sql_query(
            "SELECT removed_at AS 'Date/Time', student_id AS 'Adm. No.', student_name AS 'Learner', class_level AS 'Class', removed_sections AS 'Removed History', reason AS 'Reason', removed_by AS 'Admin' FROM student_history_removal_logs ORDER BY removal_id DESC",
            conn,
        )
        if not rem_logs_df.empty:
            st.caption("Audit Log of Removed Student History")
            st.dataframe(rem_logs_df, use_container_width=True)

        st.divider()
        st.subheader("🚨 Admin: Remove a Student or Teacher Record")
        st.warning("Permanent deletion. A database backup and mandatory reason are required. This removes the selected person's profile and associated records.")
        delete_kind = st.radio("Record type", ["Student", "Teacher"], horizontal=True, key="admin_delete_kind")
        delete_reason = st.text_area("Reason for permanent deletion *", key="admin_delete_reason")
        if delete_kind == "Student":
            delete_rows = c.execute("SELECT student_id, full_name, class_level FROM students ORDER BY full_name").fetchall()
            delete_options = {f"{r['student_id']} — {r['full_name']} ({r['class_level']})": dict(r) for r in delete_rows}
        else:
            delete_rows = c.execute("SELECT staff_id, full_name, username FROM teachers ORDER BY full_name").fetchall()
            delete_options = {f"{r['staff_id']} — {r['full_name']}": dict(r) for r in delete_rows}
        if delete_options:
            delete_label = st.selectbox("Select record to remove", list(delete_options.keys()), key="admin_delete_target")
            delete_confirm = st.checkbox("I understand this is permanent and have verified the selected record.", key="admin_delete_confirm")
            if st.button("Permanently Remove Selected Record", type="primary", key="admin_delete_submit"):
                if not delete_reason.strip() or not delete_confirm:
                    st.error("A reason and confirmation are both required.")
                else:
                    try:
                        create_db_backup("admin_person_record_deletion")
                        conn.execute("BEGIN IMMEDIATE")
                        target = delete_options[delete_label]
                        if delete_kind == "Student":
                            target_id = target["student_id"]
                            # Delete every related table that explicitly stores this student_id.
                            for table_row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                                table_name = table_row[0]
                                if table_name == "students":
                                    continue
                                columns = [x[1] for x in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
                                if "student_id" in columns:
                                    conn.execute(f'DELETE FROM "{table_name}" WHERE student_id=?', (target_id,))
                            conn.execute("DELETE FROM students WHERE student_id=?", (target_id,))
                            details = f"Student {target_id} / {target['full_name']}; reason: {delete_reason.strip()}"
                        else:
                            target_id = target["staff_id"]
                            linked_username = target.get("username")
                            conn.execute("DELETE FROM teacher_class_assignments WHERE staff_id=?", (target_id,))
                            conn.execute("DELETE FROM lesson_coverage_logs WHERE teacher_username=?", (linked_username or "",))
                            conn.execute("DELETE FROM school_timetable WHERE teacher_name=?", (target["full_name"],))
                            conn.execute("DELETE FROM teachers WHERE staff_id=?", (target_id,))
                            if linked_username:
                                conn.execute("DELETE FROM app_notifications WHERE recipient_username=?", (linked_username,))
                                conn.execute("DELETE FROM user_extra_permissions WHERE username=?", (linked_username,))
                                conn.execute("DELETE FROM users WHERE username=? AND role!='Admin'", (linked_username,))
                            details = f"Teacher {target_id} / {target['full_name']}; linked account={linked_username or 'none'}; reason: {delete_reason.strip()}"
                        write_audit_log(conn, user["username"], user["role"], f"Admin deleted {delete_kind.lower()} record", details)
                        conn.commit()
                        st.success(f"The selected {delete_kind.lower()} record and associated data were removed. The action was recorded in the audit log.")
                        st.rerun()
                    except Exception as delete_error:
                        conn.rollback()
                        st.error(f"Deletion failed and was rolled back: {delete_error}")
        else:
            st.info(f"No {delete_kind.lower()} records are available to remove.")

    conn.close()


# ---------------------------------------------------------
# MODULE 3: TEACHER REGISTRATION & DIRECTORY
# ---------------------------------------------------------
elif menu == "👨‍🏫 Teacher Registration & Directory":
    st.header("Teacher Registration & Directory")
    st.caption("Includes WASSCE and Pupil Teacher academic programmes, passport photo, and confirmation before submit.")

    conn = get_connection()
    c = conn.cursor()

    with st.form("teacher_registration_form", clear_on_submit=False):
        n1, n2, n3 = st.columns(3)
        with n1:
            t_surname = st.text_input("Teacher Surname *", placeholder="e.g., Osei")
        with n2:
            t_first = st.text_input("Teacher First Name *", placeholder="e.g., Emmanuel")
        with n3:
            t_middle = st.text_input("Teacher Middle Name (Optional)", placeholder="e.g., Kwaku")

        c1, c2 = st.columns(2)
        with c1:
            staff_id = st.text_input("Teacher Staff ID *", placeholder="e.g., GIS-TCH-001")
            t_gender = st.selectbox("Gender *", ["Male", "Female"])
            t_phone = st.text_input("Phone Number *", placeholder="e.g., 024XXXXXXX")
            t_email = st.text_input("Email Address", placeholder="e.g., teacher@globalintl.edu.gh")
            t_photo = st.file_uploader("Upload Passport-Sized Picture (Teacher)", type=["png", "jpg", "jpeg"])
        with c2:
            acad_prog = st.selectbox("Academic Programme *", TEACHER_ACADEMIC_PROGRAMMES)
            department = st.selectbox(
                "Department *",
                ["Basic & Primary", "Religious & Moral / Social", "Mathematics & ICT", "Sciences", "Languages", "Business & Arts"],
            )
            assigned_sub = st.selectbox("Primary Subject Taught *", SUBJECTS_LIST)
            create_login = st.checkbox("Create Teacher Portal Login Account", value=True)
            t_user = st.text_input("Portal Username", placeholder="e.g., eosei")
            t_pass = st.text_input("Portal Password", type="password", placeholder="Set password")

        st.markdown("**Class Allocation**")
        assign_all_classes = st.checkbox("Teacher handles ALL classes", value=False, key="teacher_register_all_classes")
        assigned_cls_levels = st.multiselect(
            "Select every class this teacher handles",
            CLASS_LEVELS,
            default=[],
            help="Select one class, several classes, or tick the option above for all classes.",
            disabled=assign_all_classes,
            key="teacher_register_class_levels",
        )
        if assign_all_classes:
            st.caption(f"All {len(CLASS_LEVELS)} class levels will be assigned.")
        else:
            st.caption(f"{len(assigned_cls_levels)} class level(s) selected.")
        confirm_t = st.checkbox("I confirm all teacher registration entries are accurate.")
        if st.form_submit_button("Register Teacher"):
            if not t_surname.strip():
                st.error("Teacher Surname is required. Cursor moved back to Teacher Surname.")
                focus_required_input("Teacher Surname")
            elif not t_first.strip():
                st.error("Teacher First Name is required. Cursor moved back to Teacher First Name.")
                focus_required_input("Teacher First Name")
            elif not staff_id.strip():
                st.error("Teacher Staff ID is required. Cursor moved back to Teacher Staff ID.")
                focus_required_input("Teacher Staff ID")
            elif not confirm_t:
                st.error("Please tick the confirmation box before submitting.")
            elif create_login and (not t_user.strip() or not t_pass.strip()):
                st.error("Please provide Username and Password for the teacher portal login.")
            elif create_login and len(t_user.strip()) < 3:
                st.error("Portal username must contain at least 3 characters.")
            elif create_login and len(t_pass) < 10:
                st.error("For account security, use a portal password with at least 10 characters.")
            elif not assign_all_classes and not assigned_cls_levels:
                st.error("Select at least one class, or tick 'Teacher handles ALL classes'.")
            else:
                full_t_name = format_full_name(t_surname, t_first, t_middle)
                t_photo_bytes = t_photo.getvalue() if t_photo is not None else None
                t_photo_mime = t_photo.type if t_photo is not None else None
                try:
                    c.execute(
                        """
                        INSERT INTO teachers (
                            staff_id, surname, first_name, middle_name, full_name,
                            gender, phone, email, academic_programme, department,
                            assigned_subject, assigned_class_level, passport_photo, passport_mime,
                            employment_date, username, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active')
                        """,
                        (
                            staff_id.strip().upper(),
                            capitalize_initials(t_surname),
                            capitalize_initials(t_first),
                            capitalize_initials(t_middle),
                            full_t_name,
                            t_gender,
                            t_phone.strip(),
                            t_email.strip(),
                            acad_prog,
                            department,
                            assigned_sub,
                            "All / Multiple Classes" if assign_all_classes else ", ".join(assigned_cls_levels),
                            t_photo_bytes,
                            t_photo_mime,
                            datetime.now().strftime("%Y-%m-%d"),
                            t_user.strip() if create_login else None,
                        ),
                    )
                    save_teacher_class_assignments(
                        conn,
                        staff_id.strip().upper(),
                        CLASS_LEVELS if assign_all_classes else assigned_cls_levels,
                    )
                    if create_login:
                        c.execute(
                            "INSERT INTO users (username, password_hash, full_name, role, assigned_subject, passport_photo, passport_mime) VALUES (?, ?, ?, 'Teacher', ?, ?, ?)",
                            (t_user.strip(), hash_password(t_pass), full_t_name, assigned_sub, t_photo_bytes, t_photo_mime),
                        )
                    conn.commit()
                    st.success(f"Teacher **{full_t_name}** (`{staff_id.upper()}`) registered under **{acad_prog}**!")
                except sqlite3.IntegrityError:
                    conn.rollback()
                    st.error("Staff ID or Username already exists. No partial teacher record was saved.")
                except Exception as registration_error:
                    conn.rollback()
                    st.error(f"Teacher registration failed; no partial record was saved: {registration_error}")

    st.divider()
    st.subheader("Manage Existing Teacher Class Allocations")
    allocation_rows = c.execute(
        "SELECT staff_id, full_name, assigned_class_level FROM teachers WHERE status = 'Active' ORDER BY full_name"
    ).fetchall()
    if allocation_rows:
        allocation_map = {
            f"{row['full_name']} ({row['staff_id']})": row["staff_id"] for row in allocation_rows
        }
        chosen_allocation_label = st.selectbox(
            "Select teacher to update class allocation", list(allocation_map.keys()), key="teacher_allocation_staff"
        )
        chosen_staff_id = allocation_map[chosen_allocation_label]
        current_allocations = [
            row["class_level"]
            for row in c.execute(
                "SELECT class_level FROM teacher_class_assignments WHERE staff_id = ? ORDER BY assignment_id",
                (chosen_staff_id,),
            ).fetchall()
        ]
        if not current_allocations:
            legacy_row = c.execute(
                "SELECT assigned_class_level FROM teachers WHERE staff_id = ?", (chosen_staff_id,)
            ).fetchone()
            legacy_value = (legacy_row["assigned_class_level"] or "").strip() if legacy_row else ""
            if legacy_value.lower() in ("all", "all classes", "all / multiple classes"):
                current_allocations = list(CLASS_LEVELS)
            else:
                current_allocations = [part.strip() for part in legacy_value.split(",") if part.strip() in CLASS_LEVELS]
        allocation_all = st.checkbox(
            "This teacher handles ALL classes", value=(len(current_allocations) == len(CLASS_LEVELS)),
            key=f"allocation_all_{chosen_staff_id}"
        )
        revised_allocations = st.multiselect(
            "Assigned class levels", CLASS_LEVELS,
            default=current_allocations,
            disabled=allocation_all,
            key=f"allocation_levels_{chosen_staff_id}"
        )
        if st.button("Save Teacher Class Allocation", key="save_teacher_allocation"):
            if not allocation_all and not revised_allocations:
                st.error("Select at least one class or choose all classes.")
            else:
                try:
                    create_db_backup("teacher_class_allocation")
                    save_teacher_class_assignments(
                        conn, chosen_staff_id, CLASS_LEVELS if allocation_all else revised_allocations
                    )
                    conn.commit()
                    st.success("Teacher class allocation updated successfully.")
                    st.rerun()
                except Exception as allocation_error:
                    conn.rollback()
                    st.error(f"Could not update teacher class allocation: {allocation_error}")

    st.divider()
    st.subheader("Registered Teachers")
    t_rows = c.execute("SELECT staff_id, full_name, gender, phone, academic_programme, department, assigned_subject, passport_photo FROM teachers").fetchall()
    if not t_rows:
        st.caption("No teachers registered yet.")
    else:
        for tr in t_rows:
            cols = st.columns([1, 4])
            with cols[0]:
                if tr["passport_photo"]:
                    st.image(tr["passport_photo"], width=85)
                else:
                    st.caption("No Photo")
            with cols[1]:
                class_rows = c.execute(
                    "SELECT class_level FROM teacher_class_assignments WHERE staff_id = ? ORDER BY assignment_id",
                    (tr["staff_id"],),
                ).fetchall()
                class_names = [row["class_level"] for row in class_rows]
                class_text = "All Classes" if len(class_names) == len(CLASS_LEVELS) else (", ".join(class_names) if class_names else "Not assigned")
                st.markdown(f"**{tr['full_name']}** (`{tr['staff_id']}`) — **{tr['gender']}** | **{tr['academic_programme']}** | Subject: **{tr['assigned_subject']}** | Classes: **{class_text}** | Dept: {tr['department']} | Tel: {tr['phone']}")
    conn.close()


# ---------------------------------------------------------
# MODULE 4: SCHOOL MANAGER PROFILE, REGISTER & CLASH-FREE TIMETABLE
# ---------------------------------------------------------
elif menu == "👔 School Manager Profile & Timetable/Register":
    _profile_heading = "My Staff Profile, Timetable & Register" if user["role"] in ("Teacher", "ICT Teacher") else "School Manager Profile, Timetable & Register"
    st.header(_profile_heading)
    conn = get_connection()
    c = conn.cursor()

    tab_mgr, tab_tt, tab_workload, tab_reg = st.tabs([
        "🪪 My Profile & Passport",
        "🗓️ Clash-Free Timetable Generator",
        "📊 Teacher Workload & Timetable",
        "📋 School Register Generator",
    ])

    with tab_mgr:
        with st.form("manager_profile_form"):
            m1, m2, m3 = st.columns(3)
            with m1:
                m_surname = st.text_input("Manager Surname", placeholder="e.g., Mensah")
            with m2:
                m_first = st.text_input("Manager First Name", placeholder="e.g., Yaw")
            with m3:
                m_middle = st.text_input("Manager Middle Name", placeholder="e.g., Kofi")
            m_photo = st.file_uploader("Upload Passport-Sized Picture (School Manager)", type=["png", "jpg", "jpeg"])
            confirm_m = st.checkbox("Confirm your profile details before saving.")
            if st.form_submit_button("Save My Profile"):
                if not confirm_m:
                    st.error("Please confirm before saving.")
                elif not m_surname.strip() or not m_first.strip():
                    st.error("Surname and First Name are required.")
                else:
                    m_full = format_full_name(m_surname, m_first, m_middle)
                    p_bytes = m_photo.getvalue() if m_photo is not None else user.get("passport_photo")
                    p_mime = m_photo.type if m_photo is not None else None
                    c.execute(
                        "UPDATE users SET full_name=?, passport_photo=?, passport_mime=? WHERE username=?",
                        (m_full, p_bytes, p_mime, user["username"]),
                    )
                    conn.commit()
                    st.session_state.user["full_name"] = m_full
                    st.session_state.user["passport_photo"] = p_bytes
                    st.success(f"Profile updated: **{m_full}**!")

    with tab_tt:
        st.subheader("Automatic Clash-Free School Timetable")
        st.write("Choose a class, select subjects, and pick your timetable generation option without teacher or slot clashes.")

        with st.form("timetable_gen_form"):
            t1, t2 = st.columns(2)
            with t1:
                _timetable_classes = get_teacher_assigned_classes(conn, user["username"]) if user["role"] in ("Teacher", "ICT Teacher") else CLASS_LEVELS
                target_cls = st.selectbox("Select Class / Grade Level", _timetable_classes or ["No class assigned"], disabled=not bool(_timetable_classes))
                gen_choice = st.radio(
                    "Choose Timetable Generation Option",
                    [
                        "Option A: Full Week Clash-Free Auto-Schedule (Mon–Fri, 6 Periods)",
                        "Option B: Core & Primary Subjects Auto-Schedule (Mon–Fri, 4 Periods)",
                    ],
                    disabled=user["role"] in ("Teacher", "ICT Teacher"),
                )
            with t2:
                selected_subs = st.multiselect(
                    "Subjects to Include",
                    SUBJECTS_LIST,
                    default=["RME", "Social Studies", "Mathematics", "English Language", "Integrated Science", "ICT (Core/Elective)"],
                    disabled=user["role"] in ("Teacher", "ICT Teacher"),
                )
            confirm_tt = st.checkbox("Confirm timetable generation for selected class.", disabled=user["role"] in ("Teacher", "ICT Teacher"))
            if st.form_submit_button("Generate Clash-Free Timetable", disabled=user["role"] in ("Teacher", "ICT Teacher") or not bool(_timetable_classes)):
                if user["role"] in ("Teacher", "ICT Teacher"):
                    st.error("Timetable generation is reserved for the School Manager or Admin. You can view your assigned class timetable below.")
                elif not confirm_tt:
                    st.error("Please confirm before generating the timetable.")
                else:
                    days_list = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
                    if "Option A" in gen_choice:
                        slots_list = ["08:00-09:00", "09:00-10:00", "10:30-11:30", "11:30-12:30", "13:00-14:00", "14:00-15:00"]
                        mode_label = "Option A (6-Period Clash-Free)"
                    else:
                        slots_list = ["08:00-09:30", "09:30-11:00", "11:30-13:00", "13:00-14:30"]
                        mode_label = "Option B (4-Period Clash-Free)"

                    try:
                        ins_cnt, skip_cnt = generate_clash_free_timetable(
                            conn, target_cls, days_list, slots_list, selected_subs, mode_label, user["full_name"]
                        )
                        if ins_cnt:
                            write_audit_log(conn, user["username"], user["role"], "Timetable generated", f"{target_cls}: {ins_cnt} slots; {skip_cnt} skipped")
                            conn.commit()
                            st.success(f"Timetable updated for **{target_cls}** ({ins_cnt} slots scheduled, {skip_cnt} unavailable / conflicting slots skipped).")
                        else:
                            st.warning("No valid teacher/subject assignments were available. The previously saved timetable was preserved.")
                    except Exception as timetable_error:
                        conn.rollback()
                        st.error(f"Timetable could not be updated. The previous timetable was preserved: {timetable_error}")

        tt_df = pd.read_sql_query(
            "SELECT class_level AS 'Class', day_of_week AS 'Day', time_slot AS 'Time', subject AS 'Subject', teacher_name AS 'Teacher', mode_used AS 'Mode' FROM school_timetable ORDER BY slot_id ASC",
            conn,
        )
        if user["role"] in ("Teacher", "ICT Teacher"):
            _view_classes = set(get_teacher_assigned_classes(conn, user["username"]))
            tt_df = tt_df[tt_df["Class"].isin(_view_classes)]
        if not tt_df.empty:
            st.dataframe(tt_df, use_container_width=True)

    with tab_workload:
        st.subheader("Teacher Workload Overview")
        st.caption("Review each teacher's weekly teaching periods and inspect their assigned timetable. Counts are based on the timetable currently saved in the system.")
        if user["role"] in ("Teacher", "ICT Teacher"):
            _linked_teacher = conn.execute("SELECT full_name FROM teachers WHERE username = ?", (user["username"],)).fetchone()
            _workload_name = _linked_teacher["full_name"] if _linked_teacher else user["full_name"]
            workload_df = pd.read_sql_query(
                """SELECT teacher_name AS 'Teacher', COUNT(*) AS 'Weekly Periods',
                          COUNT(DISTINCT class_level) AS 'Classes', COUNT(DISTINCT subject) AS 'Subjects'
                   FROM school_timetable WHERE teacher_name = ? GROUP BY teacher_name""",
                conn, params=(_workload_name,),
            )
        else:
            workload_df = pd.read_sql_query(
                """SELECT teacher_name AS 'Teacher', COUNT(*) AS 'Weekly Periods',
                          COUNT(DISTINCT class_level) AS 'Classes', COUNT(DISTINCT subject) AS 'Subjects'
                   FROM school_timetable GROUP BY teacher_name
                   ORDER BY COUNT(*) DESC, teacher_name ASC""",
                conn,
            )
        if workload_df.empty:
            st.info("No timetable entries are available yet. Generate a class timetable to see teacher workloads here.")
        else:
            st.dataframe(workload_df, use_container_width=True, hide_index=True)
            teacher_options = sorted(workload_df["Teacher"].dropna().astype(str).unique().tolist())
            chosen_teacher = st.selectbox("View individual teacher timetable", teacher_options, key="workload_teacher_view", disabled=user["role"] in ("Teacher", "ICT Teacher"))
            teacher_tt_df = pd.read_sql_query(
                """
                SELECT class_level AS 'Class', day_of_week AS 'Day', time_slot AS 'Time',
                       subject AS 'Subject', mode_used AS 'Generation Mode'
                FROM school_timetable
                WHERE teacher_name = ?
                ORDER BY CASE day_of_week
                    WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
                    WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 ELSE 6 END, time_slot
                """,
                conn,
                params=(chosen_teacher,),
            )
            st.dataframe(teacher_tt_df, use_container_width=True, hide_index=True)
            weekly_periods = len(teacher_tt_df)
            st.metric("Scheduled periods this week", weekly_periods)

    with tab_reg:
        st.subheader("Automatic School Register Generator")
        st.write("Choose a class and date to automatically generate/update the daily school register for active learners.")
        with st.form("school_register_form"):
            r1, r2, r3 = st.columns(3)
            with r1:
                reg_date = st.date_input("Register Date", value=datetime.now().date())
            with r2:
                _register_classes = get_teacher_assigned_classes(conn, user["username"]) if user["role"] in ("Teacher", "ICT Teacher") else CLASS_LEVELS
                reg_class = st.selectbox("Class / Grade Level", _register_classes or ["No class assigned"], key="reg_cls_sel", disabled=not bool(_register_classes))
            with r3:
                default_att = st.selectbox("Default Attendance Mark", ["Present", "Absent", "Late"])
            confirm_r = st.checkbox("Confirm school register generation.")
            if st.form_submit_button("Generate / Sync School Register", disabled=not bool(_register_classes)):
                if not confirm_r:
                    st.error("Please confirm before generating the school register.")
                else:
                    learners = c.execute(
                        "SELECT student_id, full_name FROM students WHERE status='Active' AND class_level=?",
                        (reg_class,),
                    ).fetchall()
                    if not learners:
                        st.warning(f"No active learners found in **{reg_class}**.")
                    else:
                        d_str = reg_date.strftime("%Y-%m-%d")
                        for lr in learners:
                            c.execute(
                                """
                                INSERT INTO school_register (register_date, class_level, student_id, student_name, attendance_status, timetable_slot, generated_by)
                                VALUES (?, ?, ?, ?, ?, 'Morning Assembly & Session 1', ?)
                                ON CONFLICT(register_date, student_id) DO UPDATE SET
                                    attendance_status=excluded.attendance_status,
                                    generated_by=excluded.generated_by
                                """,
                                (d_str, reg_class, lr["student_id"], lr["full_name"], default_att, user["full_name"]),
                            )
                        conn.commit()
                        st.success(f"School register generated for **{len(learners)}** learners in **{reg_class}** on `{d_str}`!")

        reg_df = pd.read_sql_query(
            "SELECT register_date AS 'Date', class_level AS 'Class', student_id AS 'Adm. No.', student_name AS 'Learner Name', attendance_status AS 'Status', generated_by AS 'By' FROM school_register ORDER BY reg_id DESC",
            conn,
        )
        if user["role"] in ("Teacher", "ICT Teacher") and not reg_df.empty:
            reg_df = reg_df[reg_df["Class"].isin(set(get_teacher_assigned_classes(conn, user["username"]))) ]
        if not reg_df.empty:
            st.dataframe(reg_df, use_container_width=True)

    conn.close()


# ---------------------------------------------------------
# MODULE 5: TEACHER DAILY/WEEKLY LESSONS & REMAINING TOPICS
# ---------------------------------------------------------
elif menu == "📖 Daily/Weekly Lessons & Remaining Topics":
    st.header("Daily & Weekly Areas Taught + Lessons Left to Cover")
    conn = get_connection()
    c = conn.cursor()
    lesson_class_options = (
        get_teacher_assigned_classes(conn, user["username"])
        if user["role"] in ("Teacher", "ICT Teacher") else list(CLASS_LEVELS)
    )
    if not lesson_class_options:
        conn.close()
        st.error("This teacher account has no class allocation linked to a teacher profile. Ask the Admin to link the account and assign classes.")
        st.stop()

    with st.form("lesson_log_form", clear_on_submit=False):
        l1, l2, l3 = st.columns(3)
        with l1:
            l_class = st.selectbox("Class / Grade Level", lesson_class_options)
        with l2:
            _teacher_subject = user.get("assigned_subject")
            _lesson_subjects = [_teacher_subject] if user["role"] in ("Teacher", "ICT Teacher") and _teacher_subject in SUBJECTS_LIST else SUBJECTS_LIST
            l_subject = st.selectbox("Subject", _lesson_subjects)
        with l3:
            period_type = st.selectbox("Log Frequency", ["Daily", "Weekly"])
        log_date = st.date_input("Date", value=datetime.now().date())
        areas_taught = st.text_area("Areas / Topics Taught (Daily or Weekly) *", placeholder="List sub-topics, exercises, and practicals completed...")
        areas_left = st.text_area("Areas Left to Cover in Lessons *", placeholder="List remaining syllabus topics yet to be taught...")
        confirm_l = st.checkbox("Confirm lesson coverage details before submitting.")

        if st.form_submit_button("Submit Lesson Log"):
            if not areas_taught.strip():
                st.error("Areas / Topics Taught is required. Cursor moved back to Areas / Topics Taught.")
                focus_required_input("Areas / Topics Taught")
            elif not areas_left.strip():
                st.error("Areas Left to Cover is required. Cursor moved back to Areas Left to Cover.")
                focus_required_input("Areas Left to Cover")
            elif not confirm_l:
                st.error("Please tick confirmation before submitting.")
            else:
                c.execute(
                    """
                    INSERT INTO lesson_coverage_logs (
                        teacher_username, teacher_name, class_level, subject,
                        period_type, log_date, areas_taught, areas_left_to_cover, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user["username"],
                        user["full_name"],
                        l_class,
                        l_subject,
                        period_type,
                        log_date.strftime("%Y-%m-%d"),
                        areas_taught.strip(),
                        areas_left.strip(),
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                    ),
                )
                conn.commit()
                st.success("Lesson coverage log saved!")

    st.divider()
    st.subheader("Submitted Lesson Logs")
    logs_df = pd.read_sql_query(
        "SELECT log_date AS 'Date', period_type AS 'Type', class_level AS 'Class', subject AS 'Subject', areas_taught AS 'Areas Taught', areas_left_to_cover AS 'Areas Left to Cover' FROM lesson_coverage_logs WHERE teacher_username = ? ORDER BY log_id DESC",
        conn,
        params=(user["username"],),
    )
    if not logs_df.empty:
        st.dataframe(logs_df, use_container_width=True)
    conn.close()


# ---------------------------------------------------------
# MODULE 6: CONTINUOUS ASSESSMENT & SCORE ENTRY
# ---------------------------------------------------------
elif menu == "🧮 Continuous Assessment & Score Entry":
    st.header("Continuous Assessment (30% SBA) & Exam (70%) Entry")
    st.caption("Select a class to load every active learner and every subject scheduled for that class. Enter scores directly or download, complete and upload the class CSV template.")

    conn = get_connection()
    students = pd.read_sql_query(
        "SELECT student_id, full_name, class_level, program FROM students WHERE status = 'Active' ORDER BY class_level, full_name",
        conn,
    )
    if students.empty:
        st.warning("Please register learners first.")
    else:
        term = st.selectbox("Academic Term", ["2026/2027 - Term 1", "2026/2027 - Term 2", "2026/2027 - Term 3"], key="ass_term_sel")
        class_choices = sorted(students["class_level"].dropna().unique().tolist())
        if user["role"] in ("Teacher", "ICT Teacher"):
            permitted_classes = set(get_teacher_assigned_classes(conn, user["username"]))
            class_choices = [level for level in class_choices if level in permitted_classes]
        if not class_choices:
            st.warning("No active learners are registered in the class levels assigned to this account.")
            conn.close()
            st.stop()
        selected_cls = st.selectbox("Select Class / Grade Level", class_choices, key="ass_cls_sel")
        cls_students = students[students["class_level"] == selected_cls].copy().reset_index(drop=True)

        # Use the subjects actually scheduled for this class. If no timetable exists yet,
        # fall back to the school's configured subject list so score entry remains available.
        timetable_subjects = pd.read_sql_query(
            "SELECT DISTINCT subject FROM school_timetable WHERE class_level = ? ORDER BY subject",
            conn, params=(selected_cls,)
        )["subject"].dropna().astype(str).tolist()
        class_subjects = timetable_subjects or list(SUBJECTS_LIST)
        if user["role"] in ("Teacher", "ICT Teacher"):
            assigned_subject = (user.get("assigned_subject") or "").strip()
            class_subjects = [x for x in class_subjects if x == assigned_subject]
        if not class_subjects:
            st.warning("No subjects are available for this class and staff account. Check the class timetable and teacher subject assignment.")
            conn.close()
            st.stop()

        st.info(f"Loaded **{len(cls_students)} learner(s)** and **{len(class_subjects)} subject(s)** for **{selected_cls}**.")
        st.caption("The class timetable determines the class subject list. This version does not yet store separate elective-subject combinations for individual learners.")

        existing_df = pd.read_sql_query(
            "SELECT student_id, term, subject, class_test_1, class_test_2, project_work, exam_raw FROM assessments WHERE term = ?",
            conn, params=(term,)
        )
        existing_map = {(r["student_id"], r["subject"]): dict(r) for _, r in existing_df.iterrows()}

        def _score_row(sid, student_name, subj):
            ex = existing_map.get((sid, subj), {})
            return {
                "Admission_No": sid, "Learner_Name": student_name, "Class_Level": selected_cls,
                "Subject": subj, "Term": term,
                "Class_Test_1_Max20": float(ex.get("class_test_1", 0) or 0),
                "Class_Test_2_Max20": float(ex.get("class_test_2", 0) or 0),
                "Project_Work_Max20": float(ex.get("project_work", 0) or 0),
                "Exam_Raw_Max100": float(ex.get("exam_raw", 0) or 0),
                "Overall_Max100": 100.0,
            }

        template_rows = [_score_row(r["student_id"], r["full_name"], subj)
                         for _, r in cls_students.iterrows() for subj in class_subjects]
        template_df = pd.DataFrame(template_rows)
        csv_buffer = io.StringIO()
        template_df.to_csv(csv_buffer, index=False)
        safe_cls = re.sub(r"[^A-Za-z0-9_]+", "_", selected_cls)
        csv_filename = f"{safe_cls}_ALL_SUBJECTS_{term.replace('/', '-')}_Assessment.csv"
        st.download_button(
            "📥 Download Complete Class Assessment CSV",
            data=csv_buffer.getvalue().encode("utf-8-sig"), file_name=csv_filename, mime="text/csv",
            help="This editable CSV contains every active learner and every subject scheduled for the selected class."
        )
        st.caption("CSV files cannot be encrypted and remain directly editable in Excel at the same time. The uploaded file is therefore validated strictly by the app; invalid or over-limit scores are rejected, never silently reduced.")

        uploaded_sheet = st.file_uploader(
            "📤 Upload completed class assessment CSV / Excel file",
            type=["csv", "xlsx", "xls"], key="ass_all_subjects_upload"
        )
        if uploaded_sheet is not None:
            upload_sig = hashlib.sha256(uploaded_sheet.getvalue()).hexdigest() + f":{term}:{selected_cls}"
            if st.session_state.get("last_all_subjects_upload") != upload_sig:
                try:
                    up_df = pd.read_csv(uploaded_sheet) if uploaded_sheet.name.lower().endswith(".csv") else pd.read_excel(uploaded_sheet)
                    required = {"Admission_No", "Subject", "Class_Test_1_Max20", "Class_Test_2_Max20", "Project_Work_Max20", "Exam_Raw_Max100", "Overall_Max100"}
                    missing = sorted(required - set(up_df.columns))
                    errors, parsed_rows = [], []
                    if missing:
                        errors.append("Missing required column(s): " + ", ".join(missing))
                    else:
                        valid_ids = set(cls_students["student_id"].astype(str))
                        valid_subjects = set(class_subjects)
                        seen = set()
                        limits = {"Class_Test_1_Max20": 20.0, "Class_Test_2_Max20": 20.0, "Project_Work_Max20": 20.0, "Exam_Raw_Max100": 100.0, "Overall_Max100": 100.0}
                        for ridx, row in up_df.iterrows():
                            sid = str(row.get("Admission_No", "")).strip()
                            subj = str(row.get("Subject", "")).strip()
                            if sid not in valid_ids or subj not in valid_subjects:
                                errors.append(f"Row {ridx + 2}: learner or subject does not belong to the selected class.")
                                continue
                            pair = (sid, subj)
                            if pair in seen:
                                errors.append(f"Row {ridx + 2}: duplicate learner/subject entry ({sid}, {subj}).")
                                continue
                            seen.add(pair)
                            values = {}
                            for col, maximum in limits.items():
                                try:
                                    raw = row.get(col, 0)
                                    value = 0.0 if pd.isna(raw) or str(raw).strip() == "" else float(raw)
                                    if not math.isfinite(value) or value < 0 or value > maximum:
                                        errors.append(f"Row {ridx + 2}: {col} must be between 0 and {maximum:g}. Values cannot be greater than the overall/maximum score.")
                                    values[col] = value
                                except (TypeError, ValueError):
                                    errors.append(f"Row {ridx + 2}: {col} must contain a valid number.")
                            if len(values) == len(limits):
                                parsed_rows.append((sid, subj, values))
                        expected_pairs = {(str(r["student_id"]), subj) for _, r in cls_students.iterrows() for subj in class_subjects}
                        missing_pairs = expected_pairs - seen
                        if missing_pairs:
                            errors.append(f"The file is missing {len(missing_pairs)} learner/subject row(s). Please use the complete downloaded template.")
                    if errors:
                        st.error("The assessment file was rejected. Correct the following before uploading again:")
                        for msg in errors[:30]:
                            st.write(f"- {msg}")
                        if len(errors) > 30:
                            st.write(f"...and {len(errors) - 30} more error(s).")
                    else:
                        for sid, subj, vals in parsed_rows:
                            prefix = f"ass_{sid}_{re.sub(r'[^A-Za-z0-9]+', '_', subj)}"
                            st.session_state[f"{prefix}_t1"] = f"{vals['Class_Test_1_Max20']:g}"
                            st.session_state[f"{prefix}_t2"] = f"{vals['Class_Test_2_Max20']:g}"
                            st.session_state[f"{prefix}_pj"] = f"{vals['Project_Work_Max20']:g}"
                            st.session_state[f"{prefix}_ex"] = f"{vals['Exam_Raw_Max100']:g}"
                            st.session_state[f"{prefix}_ovr"] = f"{vals['Overall_Max100']:g}"
                        st.session_state["last_all_subjects_upload"] = upload_sig
                        st.success(f"Validated and loaded {len(parsed_rows)} learner/subject score row(s). Review the grid and save.")
                except Exception as upload_error:
                    st.error(f"Could not read the uploaded assessment file: {upload_error}")

        st.divider()
        st.subheader(f"📋 Full Class Assessment Grid — {selected_cls} ({term})")
        st.caption("Enter all subjects for each learner. Test and project maximums are 20 each; the examination maximum is 100; overall maximum is 100.")
        rows_to_save = []
        with st.form("class_all_subjects_assessment_form"):
            for subj in class_subjects:
                st.markdown(f"#### {subj}")
                h = st.columns([2.2, 0.8, 0.8, 0.8, 0.85, 0.9, 1.0])
                for col, label in zip(h, ["Learner", "Test 1 /20", "Test 2 /20", "Project /20", "Exam /100", "Overall /100", "Computed total"]):
                    col.markdown(f"**{label}**")
                for _, sr in cls_students.iterrows():
                    sid, nm = str(sr["student_id"]), str(sr["full_name"])
                    ex = existing_map.get((sid, subj), {})
                    prefix = f"ass_{sid}_{re.sub(r'[^A-Za-z0-9]+', '_', subj)}"
                    defaults = {"t1": ex.get("class_test_1", 0), "t2": ex.get("class_test_2", 0), "pj": ex.get("project_work", 0), "ex": ex.get("exam_raw", 0), "ovr": 100}
                    for suffix, default in defaults.items():
                        key = f"{prefix}_{suffix}"
                        if key not in st.session_state:
                            st.session_state[key] = f"{float(default or 0):g}"
                    cols = st.columns([2.2, 0.8, 0.8, 0.8, 0.85, 0.9, 1.0])
                    cols[0].markdown(f"{nm} (`{sid}`)")
                    raw = {}
                    for col, suffix, label in zip(cols[1:6], ["t1", "t2", "pj", "ex", "ovr"], ["T1", "T2", "Project", "Exam", "Overall"]):
                        raw[suffix] = col.text_input(label, key=f"{prefix}_{suffix}", label_visibility="collapsed")
                    try:
                        nums = {k: float(v or 0) for k, v in raw.items()}
                        total = compute_assessment(nums["t1"], nums["t2"], nums["pj"], nums["ex"])[2]
                        grade, _ = calculate_wassce_grade(total)
                        cols[6].markdown(f"**{total:.2f}%** ({grade})")
                    except (TypeError, ValueError):
                        total, grade = None, "ERR"
                        cols[6].error("Invalid")
                    rows_to_save.append((sid, nm, subj, prefix))
            confirm_sc = st.checkbox("I have checked the scores for all learners and subjects.", key="conf_all_subjects_save")
            save_all = st.form_submit_button("Save All Class Assessment Scores")

        if save_all:
            if not confirm_sc:
                st.error("Please confirm the scores before saving.")
            else:
                validation_errors = []
                validated = []
                for sid, nm, subj, prefix in rows_to_save:
                    try:
                        values = {suffix: float(st.session_state.get(f"{prefix}_{suffix}", "0") or 0) for suffix in ("t1", "t2", "pj", "ex", "ovr")}
                        caps = {"t1": 20, "t2": 20, "pj": 20, "ex": 100, "ovr": 100}
                        for suffix, cap in caps.items():
                            val = values[suffix]
                            if not math.isfinite(val) or val < 0 or val > cap:
                                validation_errors.append(f"{nm} — {subj}: {suffix.upper()} must be between 0 and {cap}. Values cannot be greater than the overall/maximum score.")
                        weighted = compute_assessment(values["t1"], values["t2"], values["pj"], values["ex"] )
                        if weighted[2] > values["ovr"]:
                            validation_errors.append(f"{nm} — {subj}: computed total {weighted[2]:.2f} is greater than Overall ({values['ovr']:g}).")
                        validated.append((sid, subj, values, weighted))
                    except (TypeError, ValueError, OverflowError):
                        validation_errors.append(f"{nm} — {subj}: enter valid numeric scores in every field.")
                if validation_errors:
                    st.error("Scores were not saved. Correct these errors first:")
                    for msg in validation_errors[:30]:
                        st.write(f"- {msg}")
                    if len(validation_errors) > 30:
                        st.write(f"...and {len(validation_errors) - 30} more error(s).")
                else:
                    try:
                        create_db_backup("class_all_subjects_scores_save")
                        cur = conn.cursor()
                        for sid, subj, values, weighted in validated:
                            sba_w, exam_w, total, grade, remark = weighted
                            cur.execute("""
                                INSERT INTO assessments (student_id, term, subject, class_test_1, class_test_2, project_work, exam_raw, sba_weighted, exam_weighted, total_score, grade, remark)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(student_id, term, subject) DO UPDATE SET
                                  class_test_1=excluded.class_test_1, class_test_2=excluded.class_test_2, project_work=excluded.project_work,
                                  exam_raw=excluded.exam_raw, sba_weighted=excluded.sba_weighted, exam_weighted=excluded.exam_weighted,
                                  total_score=excluded.total_score, grade=excluded.grade, remark=excluded.remark
                            """, (sid, term, subj, values["t1"], values["t2"], values["pj"], values["ex"], sba_w, exam_w, total, grade, remark))
                        conn.commit()
                        write_audit_log(conn, user["username"], user["role"], "Class assessments saved", f"{selected_cls} | {term} | {len(validated)} learner-subject records")
                        conn.commit()
                        st.success(f"Saved {len(validated)} assessment record(s) for {selected_cls}.")
                    except Exception as save_error:
                        conn.rollback()
                        st.error(f"Could not save the class assessments: {save_error}")

        recorded_df = pd.read_sql_query(
            "SELECT a.student_id AS 'Admission No.', s.full_name AS 'Learner Name', a.subject AS 'Subject', a.sba_weighted AS 'SBA (30%)', a.exam_weighted AS 'Exam (70%)', a.total_score AS 'Total (100%)', a.grade AS 'Grade', a.remark AS 'Remark' FROM assessments a JOIN students s ON a.student_id=s.student_id WHERE a.term=? AND s.class_level=? ORDER BY s.full_name, a.subject",
            conn, params=(term, selected_cls)
        )
        if not recorded_df.empty:
            st.subheader("Recorded Class Assessments")
            st.dataframe(recorded_df, use_container_width=True)
    conn.close()


# MODULE 7: STUDENT CERTIFICATES OF COMPLETION & TERM HONOURS
# ---------------------------------------------------------
elif menu == "🎓 Student Certificates & Term Honours":
    st.header("Professional Student Certificates & End-of-Term Honours")
    st.caption("Issue formal school certification documents confirming academic completion or qualification. These are official school records, not appreciation certificates.")

    conn = get_connection()
    c = conn.cursor()
    students_rows = c.execute("SELECT * FROM students ORDER BY full_name ASC").fetchall()
    if user["role"] in ("Teacher", "ICT Teacher"):
        permitted_classes = set(get_teacher_assigned_classes(conn, user["username"]))
        students_rows = [row for row in students_rows if row["class_level"] in permitted_classes]

    tab_comp, tab_term, tab_bulk = st.tabs([
        "🏅 Certificate of Completion (Individual Learner)",
        "🌟 End-of-Term Overall Qualification Certificates",
        "📦 Bulk Certificate Downloads",
    ])

    with tab_comp:
        st.subheader("Generate Certificate of Completion / Graduation")
        if not students_rows:
            st.warning("No learners registered yet. Please register learners first.")
        else:
            s_map = {f"{r['student_id']} — {r['full_name']} ({r['class_level']})": dict(r) for r in students_rows}
            selected_label = st.selectbox("Select Learner for Certificate of Completion", list(s_map.keys()))
            stu_obj = s_map[selected_label]

            prev1, prev2 = st.columns([1, 3])
            with prev1:
                if stu_obj.get("passport_photo"):
                    st.image(stu_obj["passport_photo"], caption=stu_obj["full_name"], width=120)
                else:
                    st.info("No passport photo uploaded for this learner yet (you can add one in **Student Registration & Edit**).")
            with prev2:
                cert_title = st.text_input("Certificate Heading", value="CERTIFICATE OF COMPLETION")
                cert_sub = st.text_input("Certificate Subtitle", value=f"OFFICIAL ACADEMIC CERTIFICATION — {stu_obj['class_level']}")
                default_citation = (
                    f"This is to officially certify that the above-named learner was duly enrolled at {SCHOOL_NAME}, "
                    f"and has satisfactorily completed the prescribed course of study for {stu_obj['class_level']} "
                    f"({stu_obj['program']}) in accordance with the academic requirements and regulations of the school. "
                    f"This certificate is hereby issued as an official record of the learner's academic completion."
                )
                citation_txt = st.text_area("Certificate Citation", value=default_citation, height=95)
                mgr_signatory = st.text_input("Headteacher / Authorized School Official", value=user["full_name"])

            cert_no = f"GIS-CERT-{re.sub(r'[^A-Za-z0-9_-]+', '-', str(stu_obj['student_id']))}-{datetime.now().strftime('%Y%m%d')}"
            issue_dt = datetime.now().strftime("%d %B %Y")
            pdf_cert = generate_student_certificate_pdf(
                stu_obj, cert_no, cert_title, cert_sub, citation_txt, issue_dt, mgr_signatory
            )

            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                if st.button("Record Certificate in Issued Certificates Log"):
                    c.execute(
                        """
                        INSERT OR IGNORE INTO issued_certificates (
                            certificate_no, student_id, student_name, cert_type, term, average_score, honour_tier, issued_date, issued_by
                        ) VALUES (?, ?, ?, 'Completion', 'Full Programme', NULL, ?, ?, ?)
                        """,
                        (cert_no, stu_obj["student_id"], stu_obj["full_name"], cert_title, issue_dt, user["full_name"]),
                    )
                    conn.commit()
                    if c.rowcount:
                        write_audit_log(conn, user["username"], user["role"], "Certificate issued", f"{cert_no} | {stu_obj['student_id']}")
                        conn.commit()
                        st.success(f"Certificate `{cert_no}` recorded in the issued-certificate log.")
                    else:
                        st.info("This certificate number is already recorded. You can still download the PDF.")
            with col_dl2:
                st.download_button(
                    label="📥 Download PDF Certificate of Completion",
                    data=pdf_cert,
                    file_name=f"{re.sub(r'[^A-Za-z0-9_-]+', '_', str(stu_obj['student_id']))}_Completion_Certificate.pdf",
                    mime="application/pdf",
                )

    with tab_term:
        st.subheader("End-of-Term Overall Qualification & Merit Certification")
        st.write("Automatically evaluates learners at the end of the selected term and issues Overall Term Certificates to all qualified pupils.")

        t_col1, t_col2, t_col3 = st.columns(3)
        with t_col1:
            eval_term = st.selectbox("Select Academic Term", ["2026/2027 - Term 1", "2026/2027 - Term 2", "2026/2027 - Term 3"])
        with t_col2:
            _cert_classes = get_teacher_assigned_classes(conn, user["username"]) if user["role"] in ("Teacher", "ICT Teacher") else CLASS_LEVELS
            eval_class_options = ["All Classes"] + _cert_classes
            eval_class = st.selectbox("Filter Class / Grade Level", eval_class_options, key="cert_term_cls")
        with t_col3:
            qual_threshold = st.number_input("Minimum Qualifying Average (%)", min_value=40.0, max_value=95.0, value=60.0, step=2.5)

        query = """
            SELECT
                s.student_id,
                s.full_name,
                s.gender,
                s.class_level,
                s.program,
                s.passport_photo,
                s.passport_mime,
                COUNT(a.subject) AS subjects_taken,
                ROUND(AVG(a.total_score), 2) AS overall_avg
            FROM students s
            JOIN assessments a ON s.student_id = a.student_id
            WHERE a.term = ? AND s.status = 'Active'
        """
        params = [eval_term]
        if user["role"] in ("Teacher", "ICT Teacher"):
            if _cert_classes:
                class_placeholders = ",".join("?" for _ in _cert_classes)
                query += f" AND s.class_level IN ({class_placeholders})"
                params.extend(_cert_classes)
            else:
                query += " AND 1 = 0"
        if eval_class != "All Classes":
            query += " AND s.class_level = ?"
            params.append(eval_class)
        query += " GROUP BY s.student_id HAVING AVG(a.total_score) IS NOT NULL ORDER BY overall_avg DESC"

        term_eval_rows = [dict(r) for r in c.execute(query, params).fetchall()]

        if not term_eval_rows:
            st.info(f"No assessment records found for **{eval_term}** yet.")
        else:
            qualified_list = []
            for row in term_eval_rows:
                tier = determine_term_honour(row["overall_avg"], qual_threshold)
                if tier:
                    row["honour_tier"] = tier
                    qualified_list.append(row)

            st.metric("Qualified Pupils for End-of-Term Certification", f"{len(qualified_list)} / {len(term_eval_rows)}")

            summary_table = pd.DataFrame(
                [
                    {
                        "Adm. No.": r["student_id"],
                        "Learner Name": r["full_name"],
                        "Gender": r["gender"],
                        "Class": r["class_level"],
                        "Subjects": r["subjects_taken"],
                        "Term Average (%)": r["overall_avg"],
                        "Qualification Status": r["honour_tier"],
                    }
                    for r in qualified_list
                ]
            )

            if qualified_list:
                st.dataframe(summary_table, use_container_width=True)

                q_map = {f"{r['student_id']} — {r['full_name']} ({r['overall_avg']}% | {r['honour_tier']})": r for r in qualified_list}
                chosen_q = st.selectbox("Select Qualified Pupil to Generate Overall Term Certificate", list(q_map.keys()))
                q_stu = q_map[chosen_q]

                term_code = re.sub(r"[^A-Za-z0-9]+", "", eval_term)
                term_cert_no = f"GIS-TERM-{re.sub(r'[^A-Za-z0-9_-]+', '-', str(q_stu['student_id']))}-{term_code}-{datetime.now().strftime('%Y%m%d')}"
                term_issue_dt = datetime.now().strftime("%d %B %Y")
                term_citation = (
                    f"having demonstrated commendable academic excellence and discipline during {eval_term} in "
                    f"{q_stu['class_level']}, achieving an overall average of {q_stu['overall_avg']}% across "
                    f"{q_stu['subjects_taken']} subject(s), has duly qualified for the Overall Term Award of "
                    f"{q_stu['honour_tier']}."
                )
                term_pdf = generate_student_certificate_pdf(
                    q_stu,
                    term_cert_no,
                    f"OVERALL TERM CERTIFICATE OF EXCELLENCE ({eval_term})",
                    q_stu["honour_tier"],
                    term_citation,
                    term_issue_dt,
                    user["full_name"],
                )

                c_t1, c_t2 = st.columns(2)
                with c_t1:
                    if st.button("Record All Qualified Pupils in Certificate Log"):
                        newly_logged = 0
                        for item in qualified_list:
                            c_no = f"GIS-TERM-{re.sub(r'[^A-Za-z0-9_-]+', '-', str(item['student_id']))}-{term_code}-{datetime.now().strftime('%Y%m%d')}"
                            c.execute(
                                """
                                INSERT OR IGNORE INTO issued_certificates (
                                    certificate_no, student_id, student_name, cert_type, term, average_score, honour_tier, issued_date, issued_by
                                ) VALUES (?, ?, ?, 'End-of-Term Overall', ?, ?, ?, ?, ?)
                                """,
                                (c_no, item["student_id"], item["full_name"], eval_term, item["overall_avg"], item["honour_tier"], term_issue_dt, user["full_name"]),
                            )
                            newly_logged += max(c.rowcount, 0)
                        conn.commit()
                        write_audit_log(conn, user["username"], user["role"], "Bulk term certificates recorded", f"{eval_term} | {newly_logged} new of {len(qualified_list)} qualified learners")
                        conn.commit()
                        st.success(f"Added **{newly_logged}** new certificate record(s). {len(qualified_list) - newly_logged} were already in the log.")
                with c_t2:
                    st.download_button(
                        label="📥 Download Selected Pupil's End-of-Term Certificate (PDF)",
                        data=term_pdf,
                        file_name=f"{re.sub(r'[^A-Za-z0-9_-]+', '_', str(q_stu['student_id']))}_{re.sub(r'[^A-Za-z0-9_-]+', '_', eval_term)}_Term_Certificate.pdf",
                        mime="application/pdf",
                    )
                if st.button("Prepare Certificates for ALL Qualified Learners", key="prepare_all_term_certificates"):
                    term_zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(term_zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for qualified in qualified_list:
                            safe_qid = re.sub(r"[^A-Za-z0-9_-]+", "_", str(qualified["student_id"]))
                            q_cert_no = f"GIS-TERM-{safe_qid}-{term_code}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                            q_citation = (f"having demonstrated commendable academic excellence and discipline during {eval_term} in "
                                          f"{qualified['class_level']}, achieving an overall average of {qualified['overall_avg']}% across "
                                          f"{qualified['subjects_taken']} subject(s), has duly qualified for the Overall Term Award of {qualified['honour_tier']}.")
                            q_pdf = generate_student_certificate_pdf(qualified, q_cert_no, f"OVERALL TERM CERTIFICATE OF EXCELLENCE ({eval_term})", qualified["honour_tier"], q_citation, term_issue_dt, user["full_name"])
                            zf.writestr(f"{safe_qid}_{term_code}_Term_Certificate.pdf", q_pdf)
                    st.session_state["all_term_certificates_zip"] = term_zip_buffer.getvalue()
                    st.session_state["all_term_certificates_zip_name"] = f"{term_code}_All_Qualified_Certificates.zip"
                    write_audit_log(conn, user["username"], user["role"], "Bulk end-of-term certificates generated", f"{eval_term}: {len(qualified_list)} learners")
                    conn.commit()
                    st.success(f"Prepared {len(qualified_list)} end-of-term certificate(s). Download the ZIP below.")
                if st.session_state.get("all_term_certificates_zip"):
                    st.download_button("📥 Download All Qualified Term Certificates (ZIP)", data=st.session_state["all_term_certificates_zip"], file_name=st.session_state.get("all_term_certificates_zip_name", "Term_Certificates.zip"), mime="application/zip")
            else:
                st.warning(f"No pupils met the qualifying average of {qual_threshold}% for {eval_term}.")

    with tab_bulk:
        st.subheader("Download Multiple Completion Certificates")
        st.caption("Select a class and any number of learners. Each certificate is generated as a separate PDF inside one ZIP download.")
        bulk_cert_class = st.selectbox("Certificate class", sorted({r["class_level"] for r in students_rows}), key="bulk_cert_class") if students_rows else None
        if bulk_cert_class:
            bulk_cert_students = [dict(r) for r in students_rows if r["class_level"] == bulk_cert_class]
            cert_student_map = {f"{r['student_id']} — {r['full_name']}": r for r in bulk_cert_students}
            cert_selected = st.multiselect("Select learners for certificates", list(cert_student_map.keys()), key="bulk_cert_students")
            bulk_cert_heading = st.text_input("Certificate heading", value="CERTIFICATE OF COMPLETION", key="bulk_cert_heading")
            bulk_cert_subtitle = st.text_input("Certificate subtitle", value=f"Awarded upon successful completion of {bulk_cert_class}", key="bulk_cert_subtitle")
            bulk_cert_signatory = st.text_input("Signatory", value=user["full_name"], key="bulk_cert_signatory")
            bulk_cert_confirm = st.checkbox("I confirm these certificates are for the selected learners", key="bulk_cert_confirm")
            if st.button("Prepare Bulk Certificate ZIP", type="primary", key="prepare_bulk_cert_zip"):
                if not cert_selected:
                    st.error("Select at least one learner.")
                elif not bulk_cert_confirm:
                    st.error("Confirm the certificate selection first.")
                else:
                    zip_buffer = io.BytesIO()
                    issued = datetime.now().strftime("%d %B %Y")
                    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                        for label in cert_selected:
                            student_obj = cert_student_map[label]
                            safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(student_obj["student_id"]))
                            cert_no = f"GIS-CERT-{safe_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                            citation = f"having fulfilled the academic, moral, and practical requirements prescribed by {SCHOOL_NAME} in {student_obj['class_level']} ({student_obj['program']}), is hereby awarded this Certificate of Completion."
                            cert_bytes = generate_student_certificate_pdf(student_obj, cert_no, bulk_cert_heading, bulk_cert_subtitle, citation, issued, bulk_cert_signatory)
                            zf.writestr(f"{safe_id}_Completion_Certificate.pdf", cert_bytes)
                    st.session_state["bulk_certificate_zip"] = zip_buffer.getvalue()
                    st.session_state["bulk_certificate_zip_name"] = f"{re.sub(r'[^A-Za-z0-9_]+', '_', bulk_cert_class)}_Certificates_{datetime.now().strftime('%Y%m%d')}.zip"
                    write_audit_log(conn, user["username"], user["role"], "Bulk certificates generated", f"{bulk_cert_class}: {len(cert_selected)} learners")
                    conn.commit()
                    st.success(f"Prepared {len(cert_selected)} certificate PDF(s). Download the ZIP below.")
            if st.session_state.get("bulk_certificate_zip"):
                st.download_button("📥 Download All Selected Certificates (ZIP)", data=st.session_state["bulk_certificate_zip"], file_name=st.session_state.get("bulk_certificate_zip_name", "Certificates.zip"), mime="application/zip")

    conn.close()


# ---------------------------------------------------------
# MODULE 8: CSV FILE GENERATOR & FILTERED DATA EXPORT
# ---------------------------------------------------------
elif menu == "📥 CSV File Generator & Data Export":
    st.header("CSV File Generator & Filtered Data Export")
    st.caption("Filter school records by dataset, gender, class / grade level, or term and download ready-to-use CSV files.")

    conn = get_connection()
    if user["role"] == "Bursar":
        _export_datasets = ["Fee Payments Ledger", "Teacher Salary Payments"]
    elif user["role"] in ("Teacher", "ICT Teacher"):
        _export_datasets = ["Student Assessments & Grades", "School Attendance Register", "School Timetable"]
    else:
        _export_datasets = [
            "Students Register", "Teachers Directory",
            "Combined Population (Students + Teachers with Gender Summary)",
            "Student Assessments & Grades", "Qualified End-of-Term Pupils",
            "Fee Payments Ledger", "Teacher Salary Payments",
            "School Attendance Register", "School Timetable",
            "Incident Reports & Special Occasions",
        ]
    dataset_choice = st.selectbox("Select Dataset to Export as CSV", _export_datasets)

    f1, f2, f3 = st.columns(3)
    with f1:
        csv_gender = st.selectbox("Gender Filter", ["All Genders", "Male", "Female"], key="csv_gender_filter")
    with f2:
        csv_class = st.selectbox("Class / Grade Level Filter", ["All Classes"] + CLASS_LEVELS, key="csv_class_filter")
    with f3:
        csv_term = st.selectbox("Term Filter (for Assessments / Fees)", ["All Terms", "2026/2027 - Term 1", "2026/2027 - Term 2", "2026/2027 - Term 3"])

    export_df = pd.DataFrame()

    if dataset_choice == "Students Register":
        export_df = pd.read_sql_query(
            "SELECT student_id AS 'Admission_No', surname AS 'Surname', first_name AS 'First_Name', middle_name AS 'Middle_Name', full_name AS 'Full_Name', gender AS 'Gender', class_level AS 'Class_Level', program AS 'Programme', boarding_status AS 'Boarding_Status', guardian_name AS 'Guardian_Name', guardian_phone AS 'Guardian_Phone', status AS 'Status', date_registered AS 'Date_Registered' FROM students",
            conn,
        )
        if not export_df.empty:
            if csv_gender != "All Genders":
                export_df = export_df[export_df["Gender"] == csv_gender]
            if csv_class != "All Classes":
                export_df = export_df[export_df["Class_Level"] == csv_class]

    elif dataset_choice == "Teachers Directory":
        export_df = pd.read_sql_query(
            "SELECT staff_id AS 'Staff_ID', surname AS 'Surname', first_name AS 'First_Name', middle_name AS 'Middle_Name', full_name AS 'Full_Name', gender AS 'Gender', phone AS 'Phone', email AS 'Email', academic_programme AS 'Academic_Programme', department AS 'Department', assigned_subject AS 'Primary_Subject', employment_date AS 'Employment_Date', status AS 'Status' FROM teachers",
            conn,
        )
        if not export_df.empty and csv_gender != "All Genders":
            export_df = export_df[export_df["Gender"] == csv_gender]

    elif dataset_choice == "Combined Population (Students + Teachers with Gender Summary)":
        s_df = pd.read_sql_query("SELECT student_id AS 'ID', full_name AS 'Full_Name', gender AS 'Gender', class_level AS 'Class_Or_Dept', program AS 'Programme_Or_Subject', status AS 'Status' FROM students", conn)
        if not s_df.empty:
            s_df["Role"] = "Learner"
        t_df = pd.read_sql_query("SELECT staff_id AS 'ID', full_name AS 'Full_Name', gender AS 'Gender', department AS 'Class_Or_Dept', assigned_subject AS 'Programme_Or_Subject', status AS 'Status' FROM teachers", conn)
        if not t_df.empty:
            t_df["Role"] = "Teacher"
        export_df = pd.concat([s_df, t_df], ignore_index=True)
        if not export_df.empty:
            if csv_gender != "All Genders":
                export_df = export_df[export_df["Gender"] == csv_gender]
            if csv_class != "All Classes":
                export_df = export_df[export_df["Class_Or_Dept"] == csv_class]

    elif dataset_choice == "Student Assessments & Grades":
        export_df = pd.read_sql_query(
            """
            SELECT a.student_id AS 'Admission_No', s.full_name AS 'Full_Name', s.gender AS 'Gender',
                   s.class_level AS 'Class_Level', a.term AS 'Term', a.subject AS 'Subject',
                   a.class_test_1 AS 'Test_1', a.class_test_2 AS 'Test_2', a.project_work AS 'Project',
                   a.sba_weighted AS 'SBA_30', a.exam_weighted AS 'Exam_70', a.total_score AS 'Total_100',
                   a.grade AS 'Grade', a.remark AS 'Remark'
            FROM assessments a JOIN students s ON a.student_id = s.student_id
            """,
            conn,
        )
        if not export_df.empty:
            if csv_gender != "All Genders":
                export_df = export_df[export_df["Gender"] == csv_gender]
            if csv_class != "All Classes":
                export_df = export_df[export_df["Class_Level"] == csv_class]
            if csv_term != "All Terms":
                export_df = export_df[export_df["Term"] == csv_term]

    elif dataset_choice == "Qualified End-of-Term Pupils":
        export_df = pd.read_sql_query(
            """
            SELECT s.student_id AS 'Admission_No', s.full_name AS 'Full_Name', s.gender AS 'Gender',
                   s.class_level AS 'Class_Level', a.term AS 'Term',
                   COUNT(a.subject) AS 'Subjects_Taken', ROUND(AVG(a.total_score), 2) AS 'Overall_Average'
            FROM students s JOIN assessments a ON s.student_id = a.student_id
            WHERE s.status = 'Active'
            GROUP BY s.student_id, a.term
            HAVING AVG(a.total_score) >= 60.0
            ORDER BY Overall_Average DESC
            """,
            conn,
        )
        if not export_df.empty:
            if csv_gender != "All Genders":
                export_df = export_df[export_df["Gender"] == csv_gender]
            if csv_class != "All Classes":
                export_df = export_df[export_df["Class_Level"] == csv_class]
            if csv_term != "All Terms":
                export_df = export_df[export_df["Term"] == csv_term]

    elif dataset_choice == "Fee Payments Ledger":
        export_df = pd.read_sql_query(
            """
            SELECT f.receipt_no AS 'Receipt_No', f.student_id AS 'Admission_No', s.full_name AS 'Full_Name',
                   s.gender AS 'Gender', s.class_level AS 'Class_Level', f.term AS 'Term',
                   f.fee_billed AS 'Fee_Billed_GHS', f.amount_paid AS 'Amount_Paid_GHS',
                   f.payment_method AS 'Payment_Method', f.payment_date AS 'Payment_Date'
            FROM fee_payments f JOIN students s ON f.student_id = s.student_id
            """,
            conn,
        )
        if not export_df.empty:
            if csv_gender != "All Genders":
                export_df = export_df[export_df["Gender"] == csv_gender]
            if csv_class != "All Classes":
                export_df = export_df[export_df["Class_Level"] == csv_class]
            if csv_term != "All Terms":
                export_df = export_df[export_df["Term"] == csv_term]

    elif dataset_choice == "Teacher Salary Payments":
        export_df = pd.read_sql_query("SELECT * FROM salary_payments ORDER BY payment_id DESC", conn)

    elif dataset_choice == "School Attendance Register":
        export_df = pd.read_sql_query("SELECT * FROM school_register ORDER BY reg_id DESC", conn)
        if not export_df.empty and csv_class != "All Classes":
            export_df = export_df[export_df["class_level"] == csv_class]

    elif dataset_choice == "School Timetable":
        export_df = pd.read_sql_query("SELECT * FROM school_timetable ORDER BY slot_id ASC", conn)
        if not export_df.empty and csv_class != "All Classes":
            export_df = export_df[export_df["class_level"] == csv_class]

    else:
        export_df = pd.read_sql_query("SELECT * FROM incident_reports ORDER BY incident_id DESC", conn)

    if user["role"] in ("Teacher", "ICT Teacher") and not export_df.empty:
        _assigned = set(get_teacher_assigned_classes(conn, user["username"]))
        for _class_col in ("Class_Level", "class_level", "Class"):
            if _class_col in export_df.columns:
                export_df = export_df[export_df[_class_col].isin(_assigned)]
                break
        _assigned_subject = user.get("assigned_subject")
        if _assigned_subject and "Subject" in export_df.columns:
            export_df = export_df[export_df["Subject"] == _assigned_subject]

    conn.close()

    st.subheader(f"Preview: {dataset_choice} ({len(export_df)} row(s))")
    st.dataframe(export_df, use_container_width=True)

    csv_buffer = io.StringIO()
    export_df.to_csv(csv_buffer, index=False)
    safe_filename = re.sub(r"[^A-Za-z0-9_]+", "_", dataset_choice.lower()).strip("_") + f"_{datetime.now().strftime('%Y%m%d')}.csv"

    st.download_button(
        label=f"📥 Generate & Download CSV File ({safe_filename})",
        data=csv_buffer.getvalue().encode("utf-8"),
        file_name=safe_filename,
        mime="text/csv",
    )


# ---------------------------------------------------------
# MODULE 9: FEES, TEACHER SALARIES, OCCASIONS & INCIDENTS
# ---------------------------------------------------------
elif menu == "💰 Fees, Teacher Salaries & Occasions/Incidents":
    st.header("Fees, Teacher Salaries, Special Occasions & Incidents")
    conn = get_connection()
    c = conn.cursor()

    if user["role"] == "Bursar":
        t_fees, t_sal = st.tabs(["💳 School Fees & Receipts", "💵 Teacher Salary Payments"])
        t_occ = t_inc = None
    else:
        t_fees, t_sal, t_occ, t_inc = st.tabs([
            "💳 School Fees & Receipts", "💵 Teacher Salary Payments",
            "🎉 Special Activities / Occasions", "⚠️ Incident Reports",
        ])

    with t_fees:
        students = pd.read_sql_query("SELECT * FROM students WHERE status='Active' ORDER BY full_name ASC", conn)
        if students.empty:
            st.info("No active learners registered yet.")
        else:
            st.subheader("💳 School Fees Ledger, Full Pay & Arrears Deduction")
            s_map = {
                f"{r['student_id']} - {r['full_name']} ({r['class_level']}) | Guardian: {r['guardian_name'] or 'N/A'}": r["student_id"]
                for _, r in students.iterrows()
            }
            top_f1, top_f2 = st.columns(2)
            with top_f1:
                sel_stu = st.selectbox("Select Ward / Learner (or Parent/Guardian)", list(s_map.keys()), key="fee_ward_selector")
            with top_f2:
                f_term = st.selectbox("Academic Term", ["2026/2027 - Term 1", "2026/2027 - Term 2", "2026/2027 - Term 3"], key="fee_term_selector")

            sid_selected = s_map[sel_stu]
            ward_row = students[students["student_id"] == sid_selected].iloc[0]

            prev_term_payments = pd.read_sql_query(
                "SELECT * FROM fee_payments WHERE student_id = ? AND term = ? ORDER BY payment_date ASC",
                conn,
                params=(sid_selected, f_term),
            )
            default_billed = float(prev_term_payments["fee_billed"].iloc[-1]) if not prev_term_payments.empty else 1200.0
            already_paid_term = float(prev_term_payments["amount_paid"].sum()) if not prev_term_payments.empty else 0.0
            current_arrears = max(0.0, round(default_billed - already_paid_term, 2))

            # Display Debtor & Ward Information immediately upon selection
            st.markdown("#### 👤 Debtor & Ward Information")
            info_c1, info_c2, info_c3, info_c4 = st.columns(4)
            info_c1.metric("Ward / Learner", f"{ward_row['full_name']} ({ward_row['student_id']})")
            info_c2.metric("Class & Boarding", f"{ward_row['class_level']} • {ward_row['boarding_status']}")
            info_c3.metric("Debtor / Guardian", ward_row["guardian_name"] or "Not Specified")
            info_c4.metric("Guardian Contact", ward_row["guardian_phone"] or "Not Specified")

            bal_c1, bal_c2, bal_c3 = st.columns(3)
            bal_c1.metric("Total Term Fee Billed", f"GHS {default_billed:,.2f}")
            bal_c2.metric("Total Paid So Far", f"GHS {already_paid_term:,.2f}")
            bal_c3.metric("Current Arrears / Balance Due", f"GHS {current_arrears:,.2f}")

            pay_mode = st.radio(
                "Payment Option",
                ["Full Pay (Settle Remaining Arrears)", "Partial / Custom Amount Payment"],
                horizontal=True,
                key="fee_pay_mode_radio",
            )

            with st.form("fee_payment_form", clear_on_submit=True):
                f1, f2 = st.columns(2)
                with f1:
                    f_billed = st.number_input("Total Term Fee Billed (GHS)", min_value=0.0, value=default_billed, step=50.0)
                    f_method = st.selectbox("Payment Method", ["Mobile Money", "Bank Deposit", "Cash"])
                with f2:
                    suggested_pay = max(0.0, round(f_billed - already_paid_term, 2)) if "Full Pay" in pay_mode else 0.0
                    f_paid = st.number_input(
                        "Amount Paid Now (GHS)",
                        min_value=0.0,
                        value=suggested_pay,
                        step=50.0,
                        help="Automatically set to remaining arrears in Full Pay mode; enter any amount for partial payment.",
                    )
                    projected_arrears = max(0.0, round(f_billed - (already_paid_term + f_paid), 2))
                    st.caption(f"Projected Arrears After This Payment: **GHS {projected_arrears:,.2f}**")

                conf_f = st.checkbox("Confirm debtor, ward, and fee payment details.")
                if st.form_submit_button("Record Fee Payment & Deduct Arrears"):
                    if not conf_f:
                        st.error("Please confirm fee payment.")
                    elif f_paid <= 0:
                        st.error("Amount paid must be above zero.")
                    else:
                        rct_no = f"GIS-RCT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        c.execute(
                            "INSERT INTO fee_payments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (rct_no, sid_selected, f_term, f_billed, f_paid, f_method, datetime.now().strftime("%Y-%m-%d %H:%M"), user["full_name"]),
                        )
                        conn.commit()
                        new_rem = max(0.0, round(f_billed - (already_paid_term + f_paid), 2))
                        st.success(
                            f"Payment of **GHS {f_paid:,.2f}** recorded for **{ward_row['full_name']}** (Debtor: **{ward_row['guardian_name'] or 'Guardian'}**) | "
                            f"Receipt: **`{rct_no}`** | Remaining Arrears: **GHS {new_rem:,.2f}**"
                        )
                        st.rerun()

        st.divider()
        st.subheader("📊 Ward & Debtor Fee Balances Summary")
        all_fees_df = pd.read_sql_query("SELECT * FROM fee_payments ORDER BY payment_date DESC", conn)
        ledger_rows = []
        for _, sr in students.iterrows():
            s_pays = all_fees_df[all_fees_df["student_id"] == sr["student_id"]] if not all_fees_df.empty else pd.DataFrame()
            if s_pays.empty:
                ledger_rows.append(
                    {
                        "Adm. No.": sr["student_id"],
                        "Ward / Learner": sr["full_name"],
                        "Class": sr["class_level"],
                        "Debtor / Guardian": sr["guardian_name"] or "N/A",
                        "Phone": sr["guardian_phone"] or "N/A",
                        "Term": f_term,
                        "Total Fees (GHS)": 1200.0,
                        "Amount Paid (GHS)": 0.0,
                        "Arrears / Balance (GHS)": 1200.0,
                        "Fee Status": "Unpaid / Arrears",
                    }
                )
            else:
                for term_name, t_grp in s_pays.groupby("term"):
                    billed_val = float(t_grp["fee_billed"].iloc[-1])
                    paid_val = float(t_grp["amount_paid"].sum())
                    arrears_val = max(0.0, round(billed_val - paid_val, 2))
                    ledger_rows.append(
                        {
                            "Adm. No.": sr["student_id"],
                            "Ward / Learner": sr["full_name"],
                            "Class": sr["class_level"],
                            "Debtor / Guardian": sr["guardian_name"] or "N/A",
                            "Phone": sr["guardian_phone"] or "N/A",
                            "Term": term_name,
                            "Total Fees (GHS)": billed_val,
                            "Amount Paid (GHS)": paid_val,
                            "Arrears / Balance (GHS)": arrears_val,
                            "Fee Status": "Cleared (Full Pay)" if arrears_val == 0 else "Arrears Due",
                        }
                    )
        if ledger_rows:
            st.dataframe(pd.DataFrame(ledger_rows), use_container_width=True)

        if not all_fees_df.empty:
            st.subheader("🧾 Recorded Fee Payment Receipts")
            st.dataframe(all_fees_df, use_container_width=True)

    with t_sal:
        st.subheader("Teacher Salary Payment Records Entry")
        teachers_list = c.execute("SELECT staff_id, full_name FROM teachers WHERE status='Active'").fetchall()
        with st.form("salary_entry_form", clear_on_submit=True):
            if teachers_list:
                t_map = {f"{r['staff_id']} — {r['full_name']}": (r["staff_id"], r["full_name"]) for r in teachers_list}
                chosen_t = st.selectbox("Select Teacher", list(t_map.keys()))
                st_id, st_name = t_map[chosen_t]
            else:
                st_id = st.text_input("Teacher Staff ID", value="GIS-TCH-001")
                st_name = st.text_input("Teacher Full Name", placeholder="Enter teacher name")

            s1, s2, s3 = st.columns(3)
            with s1:
                pay_month = st.text_input("Salary Month *", value=datetime.now().strftime("%B %Y"))
                basic_sal = st.number_input("Basic Salary (GHS) *", min_value=0.0, value=1800.0, step=50.0)
            with s2:
                allowances = st.number_input("Allowances (GHS)", min_value=0.0, value=200.0, step=25.0)
                deductions = st.number_input("Deductions (GHS)", min_value=0.0, value=0.0, step=25.0)
            with s3:
                sal_method = st.selectbox("Payment Mode", ["Bank Transfer", "Mobile Money", "Cash"])
                sal_date = st.date_input("Payment Date", value=datetime.now().date())

            conf_sal = st.checkbox("Confirm salary payment figures before submitting.")
            if st.form_submit_button("Record Salary Payment"):
                if not conf_sal:
                    st.error("Please confirm salary details.")
                elif not st_name.strip():
                    st.error("Teacher name is required.")
                else:
                    net_pay = max(0.0, basic_sal + allowances - deductions)
                    c.execute(
                        """
                        INSERT INTO salary_payments (
                            staff_id, teacher_name, pay_month, basic_salary,
                            allowances, deductions, net_pay, payment_method, payment_date, paid_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (st_id.strip(), st_name.strip(), pay_month.strip(), basic_sal, allowances, deductions, net_pay, sal_method, sal_date.strftime("%Y-%m-%d"), user["full_name"]),
                    )
                    conn.commit()
                    st.success(f"Salary recorded for **{st_name}** ({pay_month}) — Net Pay: **GHS {net_pay:,.2f}**")

        sal_df = pd.read_sql_query("SELECT pay_month AS 'Month', staff_id AS 'Staff ID', teacher_name AS 'Teacher', basic_salary AS 'Basic', allowances AS 'Allowances', deductions AS 'Deductions', net_pay AS 'Net Pay (GHS)', payment_method AS 'Mode', payment_date AS 'Date' FROM salary_payments ORDER BY payment_id DESC", conn)
        if not sal_df.empty:
            st.dataframe(sal_df, use_container_width=True)

    if t_occ is not None:
        with t_occ:
            st.subheader("Special Activities & Occasions Report Entry")
            with st.form("occasion_form", clear_on_submit=True):
                o1, o2, o3 = st.columns(3)
                with o1:
                    occ_title = st.text_input("Activity / Occasion Title *", placeholder="e.g., Inter-House Sports / Speech Day")
                with o2:
                    occ_type = st.selectbox("Occasion Category", ["Cultural / Speech Day", "Sports Festival", "PTA / Open Day", "Excursion / Field Trip", "Special Assembly"])
                with o3:
                    occ_date = st.date_input("Event Date", value=datetime.now().date())
                occ_venue = st.text_input("Venue", value="School Campus, Breman Esiam")
                occ_coord = st.text_input("Coordinator / Lead", placeholder="e.g., Academic & Events Team")
                occ_summary = st.text_area("Occasion Report / Summary *", placeholder="Describe what happened, attendance, key highlights...")
                conf_occ = st.checkbox("Confirm occasion report before submitting.")
                if st.form_submit_button("Save Occasion Report"):
                    if not conf_occ:
                        st.error("Please confirm before submitting.")
                    elif not occ_title.strip() or not occ_summary.strip():
                        st.error("Title and Summary are required.")
                    else:
                        c.execute(
                            """
                            INSERT INTO special_occasions (title, occasion_type, event_date, venue, coordinator, summary, recorded_by, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (occ_title.strip(), occ_type, occ_date.strftime("%Y-%m-%d"), occ_venue.strip(), occ_coord.strip(), occ_summary.strip(), user["full_name"], datetime.now().strftime("%Y-%m-%d %H:%M")),
                        )
                        conn.commit()
                        st.success(f"Occasion report **'{occ_title}'** saved!")

            occ_df = pd.read_sql_query("SELECT event_date AS 'Date', occasion_type AS 'Type', title AS 'Title', venue AS 'Venue', summary AS 'Report Summary' FROM special_occasions ORDER BY occasion_id DESC", conn)
            if not occ_df.empty:
                st.dataframe(occ_df, use_container_width=True)

    if t_inc is not None:
        with t_inc:
            st.subheader("Incident Reports Section (Any Learner / School Case)")
            with st.form("incident_form", clear_on_submit=True):
                i1, i2, i3 = st.columns(3)
                with i1:
                    inc_date = st.date_input("Incident Date", value=datetime.now().date())
                with i2:
                    inc_class = st.selectbox("Class / Grade Level Involved", CLASS_LEVELS + ["Whole School / Compound"])
                with i3:
                    inc_sev = st.selectbox("Severity", ["Minor", "Moderate", "Urgent / Serious"])
                inc_person = st.text_input("Learner / Person(s) Involved *", placeholder="e.g., Name and Admission No. or group")
                inc_desc = st.text_area("Incident Description *", placeholder="State clearly what happened, time, and witnesses...")
                inc_action = st.text_area("Immediate Action Taken / Recommendation", placeholder="e.g., First aid given, parent called, referred to management...")
                conf_inc = st.checkbox("Confirm incident details before submitting.")
                if st.form_submit_button("Submit Incident Report"):
                    if not conf_inc:
                        st.error("Please confirm before submitting.")
                    elif not inc_person.strip() or not inc_desc.strip():
                        st.error("Person(s) Involved and Incident Description are required.")
                    else:
                        c.execute(
                            """
                            INSERT INTO incident_reports (incident_date, class_level, involved_person, severity, description, action_taken, reported_by, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (inc_date.strftime("%Y-%m-%d"), inc_class, inc_person.strip(), inc_sev, inc_desc.strip(), inc_action.strip(), user["full_name"], datetime.now().strftime("%Y-%m-%d %H:%M")),
                        )
                        conn.commit()
                        st.success("Incident report logged securely!")

            inc_df = pd.read_sql_query("SELECT incident_date AS 'Date', class_level AS 'Class', involved_person AS 'Involved', severity AS 'Severity', description AS 'Description', action_taken AS 'Action Taken' FROM incident_reports ORDER BY incident_id DESC", conn)
            if not inc_df.empty:
                st.dataframe(inc_df, use_container_width=True)

    conn.close()


# ---------------------------------------------------------
# MODULE 10A: TEACHER ISSUE REPORTING PORTAL
# ---------------------------------------------------------
elif menu == "📩 Report Issues to School Manager":
    st.header("Teacher Issues Portal (Send to School Manager)")
    conn = get_connection()
    c = conn.cursor()

    with st.form("teacher_issue_form", clear_on_submit=True):
        is_cat = st.selectbox("Issue Category", ["Classroom / Teaching Materials", "Timetable / Class Allocation", "Salary / Welfare", "Learner Discipline / Safety", "Facility / ICT / Lab"])
        is_subj = st.text_input("Issue Subject *", placeholder="e.g., Need extra markers and syllabus guides for Basic 4")
        is_body = st.text_area("Detailed Issue Description *", placeholder="Explain the challenge clearly for the School Manager...")
        conf_is = st.checkbox("Confirm issue report before sending to School Manager.")
        if st.form_submit_button("Send Issue to School Manager"):
            if not conf_is:
                st.error("Please confirm before sending.")
            elif not is_subj.strip() or not is_body.strip():
                st.error("Subject and Issue Description are required.")
            else:
                c.execute(
                    """
                    INSERT INTO staff_issues (teacher_username, teacher_name, category, subject_line, issue_details, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'Open', ?)
                    """,
                    (user["username"], user["full_name"], is_cat, is_subj.strip(), is_body.strip(), datetime.now().strftime("%Y-%m-%d %H:%M")),
                )
                issue_id = c.lastrowid
                recipients = c.execute("SELECT username FROM users WHERE role IN ('Admin','Manager')").fetchall()
                notice_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for recipient in recipients:
                    c.execute(
                        "INSERT INTO app_notifications (recipient_username, title, message, related_issue_id, created_at) VALUES (?, ?, ?, ?, ?)",
                        (recipient["username"], "New staff issue reported", f"{user['full_name']} reported: {is_subj.strip()}", issue_id, notice_time),
                    )
                conn.commit()
                st.success("Your issue has been sent. The Admin and School Manager will receive an in-app notification.")

    st.divider()
    st.subheader("My Reported Issues & School Manager Replies")
    my_issues = c.execute(
        "SELECT * FROM staff_issues WHERE teacher_username = ? ORDER BY issue_id DESC",
        (user["username"],),
    ).fetchall()
    if not my_issues:
        st.caption("You have not reported any issues yet.")
    else:
        for item in my_issues:
            st.markdown(f"**#{item['issue_id']} — {item['subject_line']}** (`{item['category']}`) • Status: **`{item['status']}`**")
            st.write(item["issue_details"])
            if item["manager_reply"]:
                st.success(f"**School Manager Reply ({item['replied_by']} • {item['replied_at']}):** {item['manager_reply']}")
            else:
                st.caption("Awaiting reply from School Manager...")
            st.divider()
    conn.close()


# ---------------------------------------------------------
# MODULE 10B: SCHOOL MANAGER REPLIES TO TEACHER ISSUES
# ---------------------------------------------------------
elif menu == "📬 Teacher Issues & Manager Replies":
    st.header("Teacher Issues Inbox & School Manager Replies")
    conn = get_connection()
    c = conn.cursor()

    all_issues = c.execute("SELECT * FROM staff_issues ORDER BY issue_id DESC").fetchall()
    if not all_issues:
        st.info("No issues reported by teachers yet.")
    else:
        issue_opts = {f"#{r['issue_id']} — {r['subject_line']} (From: {r['teacher_name']} | {r['status']})": r["issue_id"] for r in all_issues}
        sel_issue_label = st.selectbox("Select Teacher Issue to View & Reply", list(issue_opts.keys()))
        target_issue = dict(c.execute("SELECT * FROM staff_issues WHERE issue_id = ?", (issue_opts[sel_issue_label],)).fetchone())

        st.info(f"**From:** {target_issue['teacher_name']} | **Category:** {target_issue['category']} | **Sent:** {target_issue['created_at']}\n\n**Details:** {target_issue['issue_details']}")

        with st.form("manager_reply_form"):
            reply_text = st.text_area("School Manager Reply *", value=target_issue["manager_reply"] or "")
            new_status = st.selectbox("Update Issue Status", ["Replied", "Resolved", "Open"], index=["Replied", "Resolved", "Open"].index(target_issue["status"]) if target_issue["status"] in ["Replied", "Resolved", "Open"] else 0)
            conf_rep = st.checkbox("Confirm reply before sending.")
            if st.form_submit_button("Send Reply to Teacher"):
                if not conf_rep:
                    st.error("Please confirm before sending reply.")
                elif not reply_text.strip():
                    st.error("Please write a reply message.")
                else:
                    c.execute(
                        """
                        UPDATE staff_issues
                        SET manager_reply=?, status=?, replied_by=?, replied_at=?
                        WHERE issue_id=?
                        """,
                        (reply_text.strip(), new_status, user["full_name"], datetime.now().strftime("%Y-%m-%d %H:%M"), target_issue["issue_id"]),
                    )
                    conn.execute(
                        "INSERT INTO app_notifications (recipient_username, title, message, related_issue_id, created_at) VALUES (?, ?, ?, ?, ?)",
                        (target_issue["teacher_username"], "School response to your issue", f"Your issue '{target_issue['subject_line']}' has been updated: {new_status}.", target_issue["issue_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    conn.commit()
                    st.success(f"Reply sent to **{target_issue['teacher_name']}** and an in-app notification was delivered.")

    conn.close()


# ---------------------------------------------------------
# MODULE 11: TERMINAL REPORT CARDS (PDF EXPORT)
# ---------------------------------------------------------
elif menu == "📄 Terminal Report Cards (PDF Export)":
    st.header("Automated Terminal Report Card & PDF Generator")
    conn = get_connection()
    students = pd.read_sql_query("SELECT * FROM students WHERE status='Active' ORDER BY full_name ASC", conn)
    if user["role"] in ("Teacher", "ICT Teacher"):
        permitted_classes = set(get_teacher_assigned_classes(conn, user["username"]))
        students = students[students["class_level"].isin(permitted_classes)].copy()
    if students.empty:
        st.warning("No active learners found.")
    else:
        tab_ind_rep, tab_cls_rep = st.tabs([
            "👤 Individual Learner Report Card",
            "📚 All Learners in a Class (One Learner Per Page)",
        ])

        with tab_ind_rep:
            col1, col2 = st.columns(2)
            with col1:
                s_map = {f"{r['student_id']} - {r['full_name']} ({r['class_level']})": r["student_id"] for _, r in students.iterrows()}
                chosen_s = st.selectbox("Select Learner", list(s_map.keys()))
                sid = s_map[chosen_s]
            with col2:
                chosen_term = st.selectbox("Select Term", ["2026/2027 - Term 1", "2026/2027 - Term 2", "2026/2027 - Term 3"])

            s_info = students[students["student_id"] == sid].iloc[0]
            beh_row = conn.execute(
                "SELECT behaviour_label FROM student_behaviours WHERE student_id=? AND term=?",
                (sid, chosen_term),
            ).fetchone()
            cur_beh = beh_row["behaviour_label"] if beh_row and beh_row["behaviour_label"] in BEHAVIOUR_OPTIONS else BEHAVIOUR_OPTIONS[0]

            sel_beh = st.selectbox(
                "Learner Behaviour (Pick from List)",
                BEHAVIOUR_OPTIONS,
                index=BEHAVIOUR_OPTIONS.index(cur_beh),
                key=f"beh_ind_{sid}_{chosen_term}",
            )
            if st.button("Save Learner Behaviour", key=f"save_beh_ind_{sid}_{chosen_term}"):
                c_beh = conn.cursor()
                c_beh.execute(
                    """
                    INSERT INTO student_behaviours (student_id, term, behaviour_label, recorded_by, recorded_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(student_id, term) DO UPDATE SET
                        behaviour_label=excluded.behaviour_label,
                        recorded_by=excluded.recorded_by,
                        recorded_at=excluded.recorded_at
                    """,
                    (sid, chosen_term, sel_beh, user["full_name"], datetime.now().strftime("%Y-%m-%d %H:%M")),
                )
                conn.commit()
                st.success(f"Saved behaviour **`{sel_beh}`** for **{s_info['full_name']}** ({chosen_term}).")

            rep_df = pd.read_sql_query(
                """
                SELECT subject AS 'Subject', class_test_1 AS 'Test 1 (20)', class_test_2 AS 'Test 2 (20)',
                       project_work AS 'Project (20)', sba_weighted AS 'SBA (30%)',
                       exam_weighted AS 'Exam (70%)', total_score AS 'Total (100%)',
                       grade AS 'Grade', remark AS 'Remark'
                FROM assessments WHERE student_id = ? AND term = ?
                """,
                conn,
                params=(sid, chosen_term),
            )
            app_row = conn.execute("SELECT * FROM management_approvals WHERE student_id=? AND term=?", (sid, chosen_term)).fetchone()
            app_info = dict(app_row) if app_row else None

            info_p1, info_p2 = st.columns([1, 4])
            with info_p1:
                if s_info["passport_photo"]:
                    st.image(s_info["passport_photo"], caption=s_info["full_name"], width=115)
                else:
                    st.caption("No passport photo uploaded.")
            with info_p2:
                st.markdown(f"**Learner:** {s_info['full_name']} (`{s_info['student_id']}`)")
                st.markdown(f"**Class:** {s_info['class_level']} | **Status:** `{s_info['promotion_status'] or 'Promoted'}`")
                st.markdown(f"**Learner Behaviour:** `{sel_beh}`")

            if rep_df.empty:
                st.info("No assessment scores recorded for this learner in the selected term.")
            else:
                st.table(rep_df)
                overall_avg = round(rep_df["Total (100%)"].mean(), 2)
                overall_total = round(rep_df["Total (100%)"].sum(), 2)
                comment = "Commendable academic progress. Keep working diligently." if overall_avg >= 60 else "Needs extra academic support and consistent practice."
                pdf_bytes = generate_terminal_report_pdf(s_info, chosen_term, rep_df, overall_total, overall_avg, comment, app_info, sel_beh)
                st.download_button(
                    label="📥 Download Official PDF Report Card",
                    data=pdf_bytes,
                    file_name=f"{s_info['student_id']}_{chosen_term.replace('/', '_')}_Report.pdf",
                    mime="application/pdf",
                )

        with tab_cls_rep:
            st.subheader("Batch Download All Report Cards for a Particular Class")
            st.caption("Each student's report card (including their passport photo) is placed on its own separate page.")
            bc1, bc2 = st.columns(2)
            with bc1:
                batch_class = st.selectbox("Select Class / Grade Level", CLASS_LEVELS, key="batch_rep_class")
            with bc2:
                batch_term = st.selectbox("Select Term", ["2026/2027 - Term 1", "2026/2027 - Term 2", "2026/2027 - Term 3"], key="batch_rep_term")

            class_students = students[students["class_level"] == batch_class]
            if not class_students.empty:
                batch_student_map = {f"{r['student_id']} — {r['full_name']}": r["student_id"] for _, r in class_students.iterrows()}
                selected_batch_labels = st.multiselect("Choose learners for batch report cards (leave blank to include the whole class)", list(batch_student_map.keys()), key="batch_report_students")
                if selected_batch_labels:
                    selected_batch_ids = {batch_student_map[x] for x in selected_batch_labels}
                    class_students = class_students[class_students["student_id"].isin(selected_batch_ids)].copy()
                st.subheader("Bulk Behaviour Recording")
                bulk_behaviour = st.selectbox("Behaviour to apply to selected learners", BEHAVIOUR_OPTIONS, key="batch_behaviour_value")
                behaviour_target_labels = st.multiselect("Select learners to receive this behaviour (leave blank to apply to the report-card selection)", list(batch_student_map.keys()), key="batch_behaviour_students")
                if st.button("Save Behaviour for Selected Learners", key="save_batch_behaviour"):
                    behaviour_ids = [batch_student_map[x] for x in behaviour_target_labels] if behaviour_target_labels else class_students["student_id"].astype(str).tolist()
                    if not behaviour_ids:
                        st.error("Select at least one learner.")
                    else:
                        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                        for behaviour_sid in behaviour_ids:
                            conn.execute("INSERT INTO student_behaviours (student_id, term, behaviour_label, recorded_by, recorded_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(student_id, term) DO UPDATE SET behaviour_label=excluded.behaviour_label, recorded_by=excluded.recorded_by, recorded_at=excluded.recorded_at", (behaviour_sid, batch_term, bulk_behaviour, user["full_name"], stamp))
                        conn.commit()
                        st.success(f"Saved '{bulk_behaviour}' for {len(behaviour_ids)} learner(s).")
                        st.rerun()
            if class_students.empty:
                st.info(f"No active learners registered in **{batch_class}**.")
            else:
                batch_items = []
                for _, st_row in class_students.iterrows():
                    st_rep_df = pd.read_sql_query(
                        """
                        SELECT subject AS 'Subject', class_test_1 AS 'Test 1 (20)', class_test_2 AS 'Test 2 (20)',
                               project_work AS 'Project (20)', sba_weighted AS 'SBA (30%)',
                               exam_weighted AS 'Exam (70%)', total_score AS 'Total (100%)',
                               grade AS 'Grade', remark AS 'Remark'
                        FROM assessments WHERE student_id = ? AND term = ?
                        """,
                        conn,
                        params=(st_row["student_id"], batch_term),
                    )
                    if st_rep_df.empty:
                        st_rep_df = pd.DataFrame(
                            [{"Subject": "No Scores Recorded Yet", "SBA (30%)": 0.0, "Exam (70%)": 0.0, "Total (100%)": 0.0, "Grade": "-", "Remark": "Pending"}]
                        )
                        st_avg = 0.0
                        st_tot = 0.0
                    else:
                        st_avg = round(st_rep_df["Total (100%)"].mean(), 2)
                        st_tot = round(st_rep_df["Total (100%)"].sum(), 2)

                    st_beh_row = conn.execute(
                        "SELECT behaviour_label FROM student_behaviours WHERE student_id=? AND term=?",
                        (st_row["student_id"], batch_term),
                    ).fetchone()
                    st_beh_val = (
                        st_beh_row["behaviour_label"]
                        if st_beh_row and st_beh_row["behaviour_label"] in BEHAVIOUR_OPTIONS
                        else BEHAVIOUR_OPTIONS[0]
                    )
                    st_app_row = conn.execute(
                        "SELECT * FROM management_approvals WHERE student_id=? AND term=?",
                        (st_row["student_id"], batch_term),
                    ).fetchone()
                    st_comment = "Commendable academic progress. Keep working diligently." if st_avg >= 60 else "Needs extra academic support and consistent practice."
                    batch_items.append(
                        {
                            "student_info": st_row,
                            "term": batch_term,
                            "report_df": st_rep_df,
                            "overall_total": st_tot,
                            "overall_avg": st_avg,
                            "master_comment": st_comment,
                            "approval_info": dict(st_app_row) if st_app_row else None,
                            "behaviour_label": st_beh_val,
                        }
                    )

                batch_pdf_bytes = generate_class_report_cards_pdf(batch_items)
                st.success(f"Prepared **{len(batch_items)}** report card page(s) for **{batch_class}** ({batch_term}).")
                st.download_button(
                    label=f"📥 Download All {batch_class} Report Cards (1 Student Per Page PDF)",
                    data=batch_pdf_bytes,
                    file_name=f"{re.sub(r'[^A-Za-z0-9_]+', '_', batch_class)}_{batch_term.replace('/', '_')}_All_Reports.pdf",
                    mime="application/pdf",
                )
    conn.close()


# ---------------------------------------------------------
# MODULE 12: MANAGE STAFF & ROLES
# ---------------------------------------------------------
elif menu == "👥 Manage Staff & Roles":
    if user["role"] != "Admin":
        st.error("Only the system Admin can assign staff roles and extra privileges.")
        st.stop()

    st.header("Staff Accounts, Position Roles & Extra Privileges")
    st.caption("Admin accounts are protected. Assign each subordinate a position, then grant only the additional modules required for that position.")
    conn = get_connection()
    c = conn.cursor()
    u_rows = c.execute("SELECT username, full_name, role FROM users WHERE role != 'Admin' ORDER BY full_name").fetchall()
    if not u_rows:
        st.info("No subordinate accounts are available for role assignment yet.")
    else:
        u_map = {f"{r['username']} — {r['full_name']} ({r['role']})": dict(r) for r in u_rows}
        sel_u = st.selectbox("Select Staff Account", list(u_map.keys()), key="role_target_user")
        selected_account = u_map[sel_u]
        current_role = selected_account["role"] if selected_account["role"] in ASSIGNABLE_ROLES else "Teacher"
        new_r = st.selectbox("Assign Position / Role", ASSIGNABLE_ROLES, index=ASSIGNABLE_ROLES.index(current_role), key=f"role_choice_{selected_account['username']}")
        current_extras = get_user_extra_permissions(conn, selected_account["username"])
        extra_choices = [item for item in ALL_MENU_OPTIONS if item != MENU_STAFF_ROLES and item not in ROLE_BASE_PERMISSIONS.get(new_r, [])]
        default_extras = current_extras if new_r == current_role else []
        selected_extras = st.multiselect(
            "Extra Privileges (optional)",
            options=extra_choices,
            default=[x for x in default_extras if x in extra_choices],
            key=f"extra_privileges_{selected_account['username']}_{new_r}",
            help="Admin can grant any additional operational module. Admin identity and role/account administration cannot be delegated.",
        )
        st.info("Base permissions are automatically included. You may grant any additional operational module to this staff account. Admin identity and role administration remain protected.")
        with st.expander(f"View base modules included with the {new_r} role"):
            for base_module in ROLE_BASE_PERMISSIONS.get(new_r, []):
                st.write(f"• {base_module}")
        if not extra_choices:
            st.caption("There are no additional module privileges available for this position; its standard role permissions remain active.")
        confirm_role = st.checkbox("I confirm this role and its extra privileges are appropriate.", key=f"confirm_role_{selected_account['username']}")
        if st.button("Save Role & Extra Privileges", type="primary"):
            if not confirm_role:
                st.error("Please confirm the role assignment before saving.")
            elif new_r not in ASSIGNABLE_ROLES:
                st.error("Invalid role. Admin cannot be assigned to subordinate accounts.")
            elif new_r in ("Teacher", "ICT Teacher") and not conn.execute(
                "SELECT 1 FROM teachers WHERE username = ?", (selected_account["username"],)
            ).fetchone():
                st.error("This account has no linked teacher profile. Link it to a registered teacher profile below before assigning a teaching role.")
            elif new_r == "ICT Teacher" and conn.execute(
                "SELECT assigned_subject FROM teachers WHERE username = ?", (selected_account["username"],)
            ).fetchone()["assigned_subject"] != "ICT (Core/Elective)":
                st.error("To assign the ICT Teacher role, first set this teacher's primary subject to ICT (Core/Elective) in the Teacher Directory.")
            else:
                try:
                    create_db_backup("staff_role_permissions")
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("UPDATE users SET role = ? WHERE username = ? AND role != 'Admin'", (new_r, selected_account["username"]))
                    conn.execute("DELETE FROM user_extra_permissions WHERE username = ?", (selected_account["username"],))
                    now_value = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    valid_extras = [x for x in selected_extras if x in ALL_MENU_OPTIONS and x != MENU_STAFF_ROLES and x not in ROLE_BASE_PERMISSIONS.get(new_r, [])]
                    conn.executemany(
                        "INSERT INTO user_extra_permissions (username, module_name, granted_by, granted_at) VALUES (?, ?, ?, ?)",
                        [(selected_account["username"], item, user["username"], now_value) for item in valid_extras],
                    )
                    write_audit_log(conn, user["username"], user["role"], "Staff role/privileges updated", f"{selected_account['username']}: {new_r}; extras={', '.join(valid_extras)}")
                    conn.commit()
                    st.success(f"Updated `{selected_account['username']}` to **{new_r}** with {len(valid_extras)} extra privilege(s).")
                    st.rerun()
                except Exception as role_error:
                    conn.rollback()
                    st.error(f"Role update failed safely: {role_error}")

    st.divider()
    st.subheader("Link an Existing Portal Account to a Teacher Profile")
    unlinked_profiles = c.execute(
        "SELECT staff_id, full_name, assigned_subject FROM teachers WHERE username IS NULL OR TRIM(username) = '' ORDER BY full_name"
    ).fetchall()
    available_accounts = c.execute(
        """SELECT username, full_name, role FROM users
           WHERE role != 'Admin'
             AND username NOT IN (SELECT username FROM teachers WHERE username IS NOT NULL AND TRIM(username) != '')
           ORDER BY full_name"""
    ).fetchall()
    if unlinked_profiles and available_accounts:
        profile_map = {f"{r['full_name']} ({r['staff_id']}) — {r['assigned_subject']}": dict(r) for r in unlinked_profiles}
        account_map = {f"{r['username']} — {r['full_name']} ({r['role']})": dict(r) for r in available_accounts}
        with st.form("link_teacher_account_form"):
            selected_profile_label = st.selectbox("Registered Teacher Profile", list(profile_map.keys()))
            selected_account_label = st.selectbox("Teaching Portal Account", list(account_map.keys()))
            confirm_link = st.checkbox("Confirm that this portal account belongs to the selected teacher.")
            if st.form_submit_button("Link Teacher Profile to Portal Account"):
                if not confirm_link:
                    st.error("Please confirm the identity match before linking.")
                else:
                    profile = profile_map[selected_profile_label]
                    account = account_map[selected_account_label]
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute("UPDATE teachers SET username = ? WHERE staff_id = ? AND (username IS NULL OR TRIM(username) = '')", (account["username"], profile["staff_id"]))
                        conn.execute("UPDATE users SET role = 'Teacher', assigned_subject = ?, full_name = ? WHERE username = ? AND role != 'Admin'", (profile["assigned_subject"], profile["full_name"], account["username"]))
                        conn.execute("DELETE FROM user_extra_permissions WHERE username = ?", (account["username"],))
                        write_audit_log(conn, user["username"], user["role"], "Teacher portal account linked", f"{account['username']} -> {profile['staff_id']}")
                        conn.commit()
                        st.success(f"Linked `{account['username']}` to teacher profile `{profile['staff_id']}`.")
                        st.rerun()
                    except Exception as link_error:
                        conn.rollback()
                        st.error(f"Could not link teacher account: {link_error}")
    elif not unlinked_profiles:
        st.caption("All registered teacher profiles are already linked to portal accounts.")
    else:
        st.caption("No unlinked subordinate portal accounts are available. Register a teacher profile or create a subordinate account first.")

    st.divider()
    st.subheader("Recent System Audit Trail")
    audit_df = pd.read_sql_query(
        "SELECT created_at AS 'Date / Time', username AS 'Account', role AS 'Role', action AS 'Action', details AS 'Details' FROM system_audit_log ORDER BY audit_id DESC LIMIT 100",
        conn,
    )
    if audit_df.empty:
        st.caption("No audit events have been recorded yet.")
    else:
        st.dataframe(audit_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Staff Role & Privilege Directory")
    df_u = pd.read_sql_query("SELECT username, full_name, role, assigned_subject FROM users ORDER BY role, full_name", conn)
    extra_rows = c.execute("SELECT username, module_name FROM user_extra_permissions ORDER BY username, module_name").fetchall()
    extra_map = {}
    for extra_row in extra_rows:
        extra_map.setdefault(extra_row["username"], []).append(extra_row["module_name"])
    if not df_u.empty:
        df_u["Extra Privileges"] = df_u["username"].map(lambda name: ", ".join(extra_map.get(name, [])) or "None")
        st.dataframe(df_u, use_container_width=True)
    st.caption("The Admin account is not selectable for role changes and no subordinate role can be changed to Admin.")
    conn.close()
