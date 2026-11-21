import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import hashlib
import re
import io
import os
import tempfile
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


def create_db_backup(reason: str = "auto"):
    """Creates a safe SQLite online backup snapshot so historical data is never lost."""
    try:
        if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
            return None
        backup_dir = "db_backups"
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "_", reason)[:30]
        bak_path = os.path.join(backup_dir, f"globe_sms_backup_{ts}_{safe_reason}.db")
        src_conn = sqlite3.connect(DB_FILE)
        dst_conn = sqlite3.connect(bak_path)
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        # Keep latest 25 backups to manage disk space cleanly
        backups = sorted(
            [os.path.join(backup_dir, fn) for fn in os.listdir(backup_dir) if fn.endswith(".db")],
            key=os.path.getmtime,
        )
        for old_bak in backups[:-25]:
            try:
                os.remove(old_bak)
            except OSError:
                pass
        return bak_path
    except Exception:
        return None


def _ensure_column(cursor, table_name: str, col_name: str, col_def: str):
    """Safely adds a column to an existing table if it does not already exist."""
    try:
        cols = [r["name"] for r in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()]
        if col_name not in cols:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
    except Exception:
        pass


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
    return hashlib.sha256(password.encode()).hexdigest()


def format_full_name(surname: str, first_name: str, middle_name: str = "") -> str:
    parts = [p.strip() for p in [surname, first_name, middle_name] if p and p.strip()]
    return " ".join(parts)


def generate_admission_number(surname: str, first_name: str, middle_name: str = "", seq_num: int = 1) -> str:
    """Attaches letters from the student's name plus year and sequence number."""
    s_letters = re.sub(r"[^A-Za-z]", "", surname or "X")[:2].upper().ljust(2, "X")
    f_letter = re.sub(r"[^A-Za-z]", "", first_name or "X")[:1].upper().ljust(1, "X")
    m_letter = re.sub(r"[^A-Za-z]", "", middle_name or "")[:1].upper()
    code_letters = f"{s_letters}{f_letter}{m_letter}"
    year = datetime.now().strftime("%Y")
    return f"GIS-{code_letters}-{year}-{seq_num:03d}"


def init_db():
    if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > 0:
        create_db_backup("startup")
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

    # Self-healing schema columns & edit-permission / teacher-assignment support
    _ensure_column(c, "students", "promotion_status", "TEXT DEFAULT 'Promoted'")
    _ensure_column(c, "students", "student_edit_locked", "INTEGER DEFAULT 1")
    _ensure_column(c, "students", "assigned_teacher_staff_id", "TEXT")
    _ensure_column(c, "students", "assigned_teacher_name", "TEXT")
    _ensure_column(c, "teachers", "assigned_class_level", "TEXT")

    c.execute("UPDATE students SET promotion_status = 'Promoted' WHERE promotion_status IS NULL OR TRIM(promotion_status) = ''")
    c.execute("UPDATE students SET student_edit_locked = 1 WHERE student_edit_locked IS NULL")

    # Idempotent indexes to guard against duplicate records & speed lookups
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_assessment ON assessments(student_id, term, subject)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_approval ON management_approvals(student_id, term)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_register ON school_register(register_date, student_id)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_timetable_cls ON school_timetable(class_level, day_of_week, time_slot)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_timetable_tch ON school_timetable(day_of_week, time_slot, teacher_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_level)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_students_teacher ON students(assigned_teacher_staff_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fees_student ON fee_payments(student_id, term)")

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# 2. WASSCE GRADING & CLASH-FREE TIMETABLE ENGINE
# ---------------------------------------------------------
def calculate_wassce_grade(total_score: float):
    score = round(total_score)
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
    c = conn.cursor()

    c.execute("SELECT full_name, assigned_subject FROM teachers WHERE status = 'Active'")
    active_teachers = [dict(r) for r in c.fetchall()]

    c.execute("SELECT day_of_week, time_slot, teacher_name FROM school_timetable WHERE class_level != ?", (target_class,))
    booked_slots = {(r["day_of_week"], r["time_slot"], r["teacher_name"]) for r in c.fetchall()}

    c.execute("DELETE FROM school_timetable WHERE class_level = ?", (target_class,))

    subject_pool = chosen_subjects if chosen_subjects else SUBJECTS_LIST[:5]
    sub_idx = 0
    inserted_count = 0
    conflicts_skipped = 0

    for day in days:
        used_subjects_today = set()
        for slot in time_slots:
            assigned_teacher_name = None
            assigned_sub = None

            for attempt in range(len(subject_pool)):
                candidate_sub = subject_pool[(sub_idx + attempt) % len(subject_pool)]
                if candidate_sub in used_subjects_today and len(subject_pool) > len(time_slots):
                    continue

                matching_teachers = [t["full_name"] for t in active_teachers if t["assigned_subject"] == candidate_sub]
                other_teachers = [t["full_name"] for t in active_teachers if t["full_name"] not in matching_teachers]
                ordered_candidates = matching_teachers + other_teachers

                for t_name in ordered_candidates:
                    if (day, slot, t_name) not in booked_slots:
                        assigned_teacher_name = t_name
                        assigned_sub = candidate_sub
                        booked_slots.add((day, slot, t_name))
                        used_subjects_today.add(candidate_sub)
                        sub_idx = (sub_idx + attempt + 1) % len(subject_pool)
                        break

                if assigned_teacher_name:
                    break

            if not assigned_teacher_name:
                assigned_sub = subject_pool[sub_idx % len(subject_pool)]
                sub_idx += 1
                fallback_teacher = f"{assigned_sub} Master"
                if (day, slot, fallback_teacher) not in booked_slots:
                    assigned_teacher_name = fallback_teacher
                    booked_slots.add((day, slot, fallback_teacher))
                else:
                    conflicts_skipped += 1
                    continue

            c.execute(
                """
                INSERT INTO school_timetable (class_level, day_of_week, time_slot, subject, teacher_name, mode_used, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (target_class, day, slot, assigned_sub, assigned_teacher_name, mode_used, created_by),
            )
            inserted_count += 1

    conn.commit()
    return inserted_count, conflicts_skipped


# ---------------------------------------------------------
# 3. PDF GENERATORS (TERMINAL REPORT & CERTIFICATES)
# ---------------------------------------------------------
class SchoolPDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 15)
        self.set_text_color(27, 54, 93)
        self.cell(0, 8, SCHOOL_NAME, ln=True, align="C")
        self.set_font("Arial", "B", 9)
        self.set_text_color(80, 80, 80)
        self.cell(0, 5, SCHOOL_LOCATION, ln=True, align="C")
        self.set_font("Arial", "I", 9)
        self.cell(0, 5, f'Motto: "{SCHOOL_MOTTO}"', ln=True, align="C")
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


def _render_single_report_page(pdf, student_info, term, report_df, overall_total, overall_avg, master_comment, approval_info=None):
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
                tmp_f.write(photo_bytes)
            pdf.set_draw_color(27, 54, 93)
            pdf.set_line_width(0.6)
            pdf.rect(168, 36, 26, 29)
            pdf.image(temp_img_path, x=169, y=37, w=24, h=27)
        except Exception:
            temp_img_path = None

    pdf.set_font("Arial", "B", 12)
    pdf.set_fill_color(230, 238, 248)
    pdf.cell(152, 8, f"STUDENT TERMINAL REPORT CARD - {term.upper()}", ln=True, align="C", fill=True)
    pdf.ln(3)

    promo_val = ""
    try:
        promo_val = student_info["promotion_status"] or "Promoted"
    except Exception:
        promo_val = "Promoted"

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(34, 6.5, "Student Name:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(58, 6.5, str(student_info["full_name"]), border=0)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(30, 6.5, "Admission No.:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(35, 6.5, str(student_info["student_id"]), ln=True)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(34, 6.5, "Class / Grade:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(58, 6.5, str(student_info["class_level"]), border=0)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(30, 6.5, "Status:", border=0)
    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(35, 6.5, str(promo_val), ln=True)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(34, 6.5, "Program:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(58, 6.5, str(student_info["program"]), border=0)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(30, 6.5, "Overall Average:", border=0)
    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(35, 6.5, f"{overall_avg}%", ln=True)

    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(34, 6.5, "Residential:", border=0)
    pdf.set_font("Arial", "", 9.5)
    pdf.cell(58, 6.5, str(student_info["boarding_status"]), ln=True)
    pdf.ln(5)


def generate_terminal_report_pdf(student_info, term, report_df, overall_total, overall_avg, master_comment, approval_info=None):
    pdf = SchoolPDF()
    _render_single_report_page(pdf, student_info, term, report_df, overall_total, overall_avg, master_comment, approval_info)



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
        pdf.cell(col_widths[0], 7, str(row["Subject"]), border=1)
        pdf.cell(col_widths[1], 7, f"{row['SBA (30%)']}", border=1, align="C")
        pdf.cell(col_widths[2], 7, f"{row['Exam (70%)']}", border=1, align="C")
        pdf.cell(col_widths[3], 7, f"{row['Total (100%)']}", border=1, align="C")
        pdf.cell(col_widths[4], 7, str(row["Grade"]), border=1, align="C")
        pdf.cell(col_widths[5], 7, str(row["Remark"]), border=1, align="C")
        pdf.ln()

    pdf.ln(5)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 7, f"Grand Total Score: {overall_total}   |   Subjects Taken: {len(report_df)}   |   Overall Average: {overall_avg}%", ln=True)
    pdf.ln(3)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 6, "Form Master's Remark:", ln=True)
    pdf.set_font("Arial", "I", 10)
    pdf.multi_cell(0, 6, master_comment)
    pdf.ln(3)

    if approval_info is not None:
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, f"School Manager Sign-Off ({approval_info['manager_role']} - {approval_info['approved_by']}):", ln=True)
        pdf.set_font("Arial", "I", 10)
        pdf.multi_cell(0, 6, f"{approval_info['management_remark']} (Signed on {approval_info['signed_date']})")
        pdf.ln(4)

    pdf.ln(6)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(95, 7, "__________________________", align="C")
    pdf.cell(95, 7, "__________________________", align="C", ln=True)
    pdf.cell(95, 5, "Class Teacher's Signature", align="C")
    pdf.cell(95, 5, "School Manager Signature", align="C", ln=True)

    return bytes(pdf.output())


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
            pdf.cell(col_widths[0], 7, str(row["Subject"]), border=1)
            pdf.cell(col_widths[1], 7, f"{row['SBA (30%)']}", border=1, align="C")
            pdf.cell(col_widths[2], 7, f"{row['Exam (70%)']}", border=1, align="C")
            pdf.cell(col_widths[3], 7, f"{row['Total (100%)']}", border=1, align="C")
            pdf.cell(col_widths[4], 7, str(row["Grade"]), border=1, align="C")
            pdf.cell(col_widths[5], 7, str(row["Remark"]), border=1, align="C")
            pdf.ln()

        pdf.ln(5)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 7, f"Grand Total Score: {item['overall_total']}   |   Subjects Taken: {len(item['report_df'])}   |   Overall Average: {item['overall_avg']}%", ln=True)
        pdf.ln(3)

        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, "Form Master's Remark:", ln=True)
        pdf.set_font("Arial", "I", 10)
        pdf.multi_cell(0, 6, item["master_comment"])
        pdf.ln(3)

        if item.get("approval_info") is not None:
            pdf.set_font("Arial", "B", 10)
            pdf.cell(0, 6, f"School Manager Sign-Off ({item['approval_info']['manager_role']} - {item['approval_info']['approved_by']}):", ln=True)
            pdf.set_font("Arial", "I", 10)
            pdf.multi_cell(0, 6, f"{item['approval_info']['management_remark']} (Signed on {item['approval_info']['signed_date']})")
            pdf.ln(4)

        pdf.ln(6)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(95, 7, "__________________________", align="C")
        pdf.cell(95, 7, "__________________________", align="C", ln=True)
        pdf.cell(95, 5, "Class Teacher's Signature", align="C")
        pdf.cell(95, 5, "School Manager Signature", align="C", ln=True)

    return bytes(pdf.output())


def generate_student_certificate_pdf(
    student_info: dict,
    cert_no: str,
    cert_title: str,
    subtitle: str,
    citation_text: str,
    issued_date: str,
    manager_name: str,
):
    """Generates a landscape A4 certificate with decorative gold/navy borders and student passport photo."""
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    # Outer Navy Frame & Inner Gold Double Border
    pdf.set_draw_color(27, 54, 93)
    pdf.set_line_width(2.2)
    pdf.rect(8, 8, 281, 194)

    pdf.set_draw_color(212, 160, 23)
    pdf.set_line_width(0.9)
    pdf.rect(12, 12, 273, 186)

    # Subtle header ribbon
    pdf.set_fill_color(244, 247, 251)
    pdf.rect(14, 14, 269, 34, style="F")

    # School Name & Motto
    pdf.set_xy(15, 17)
    pdf.set_font("Arial", "B", 20)
    pdf.set_text_color(27, 54, 93)
    pdf.cell(0, 9, SCHOOL_NAME, ln=True, align="C")

    pdf.set_font("Arial", "B", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, SCHOOL_LOCATION, ln=True, align="C")

    pdf.set_font("Arial", "I", 10)
    pdf.set_text_color(160, 118, 10)
    pdf.cell(0, 6, f'"{SCHOOL_MOTTO}"', ln=True, align="C")

    # Student Passport Picture on Top-Right if available
    temp_img_path = None
    photo_bytes = student_info.get("passport_photo")
    if photo_bytes:
        mime = (student_info.get("passport_mime") or "").lower()
        ext = ".png" if "png" in mime else ".jpg"
        try:
            fd, temp_img_path = tempfile.mkstemp(suffix=ext)
            with os.fdopen(fd, "wb") as tmp_f:
                tmp_f.write(photo_bytes)
            pdf.set_draw_color(212, 160, 23)
            pdf.set_line_width(0.8)
            pdf.rect(244, 52, 34, 38)
            pdf.image(temp_img_path, x=245, y=53, w=32, h=36)
        except Exception:
            temp_img_path = None
    else:
        pdf.set_draw_color(180, 190, 205)
        pdf.set_line_width(0.5)
        pdf.rect(244, 52, 34, 38)
        pdf.set_xy(244, 68)
        pdf.set_font("Arial", "I", 8)
        pdf.set_text_color(130, 130, 130)
        pdf.cell(34, 5, "Passport Photo", align="C")

    # Certificate Title
    pdf.set_xy(15, 54)
    pdf.set_font("Arial", "B", 22)
    pdf.set_text_color(27, 54, 93)
    pdf.cell(0, 11, cert_title.upper(), ln=True, align="C")

    pdf.set_font("Arial", "B", 11)
    pdf.set_text_color(180, 130, 15)
    pdf.cell(0, 6, subtitle, ln=True, align="C")

    pdf.ln(5)
    pdf.set_font("Arial", "", 12)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 7, "This is to proudly certify that", ln=True, align="C")

    # Student Full Name
    pdf.ln(2)
    pdf.set_font("Arial", "B", 21)
    pdf.set_text_color(15, 35, 66)
    pdf.cell(0, 11, str(student_info["full_name"]).upper(), ln=True, align="C")

    # Gold underline under student name
    pdf.set_draw_color(212, 160, 23)
    pdf.set_line_width(0.7)
    pdf.line(78, pdf.get_y() + 1, 219, pdf.get_y() + 1)
    pdf.ln(4)

    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(70, 85, 105)
    pdf.cell(
        0,
        6,
        f"Admission No.: {student_info['student_id']}   |   Class / Grade: {student_info['class_level']}   |   Programme: {student_info['program']}",
        ln=True,
        align="C",
    )

    pdf.ln(4)
    pdf.set_xy(32, pdf.get_y())
    pdf.set_font("Arial", "", 11.5)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(233, 6.5, citation_text, align="C")

    # Footer Signatures & Certificate ID
    pdf.set_xy(22, 165)
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(27, 54, 93)
    pdf.cell(80, 6, "____________________________", align="C")
    pdf.cell(93, 6, f"Certificate No: {cert_no}", align="C")
    pdf.cell(80, 6, "____________________________", align="C", ln=True)

    pdf.set_x(22)
    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(80, 5, "Class Teacher / Academic Head", align="C")
    pdf.set_font("Arial", "I", 9.5)
    pdf.cell(93, 5, f"Issued on: {issued_date}", align="C")
    pdf.set_font("Arial", "B", 9.5)
    pdf.cell(80, 5, f"{manager_name} (School Manager)", align="C", ln=True)

    pdf_out = bytes(pdf.output())
    if temp_img_path and os.path.exists(temp_img_path):
        try:
            os.remove(temp_img_path)
        except OSError:
            pass
    return pdf_out


# ---------------------------------------------------------
# 4. STREAMLIT UI, EDUCATIONAL THEME & AUTHENTICATION
# ---------------------------------------------------------
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
                    "SELECT username, full_name, role, assigned_subject, passport_photo FROM users WHERE username = ? AND password_hash = ?",
                    (username.strip(), hash_password(password)),
                )
                user_row = c.fetchone()
                conn.close()
                if user_row:
                    st.session_state.user = {
                        "username": user_row["username"],
                        "full_name": user_row["full_name"],
                        "role": user_row["role"],
                        "assigned_subject": user_row["assigned_subject"],
                        "passport_photo": user_row["passport_photo"],
                    }
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

        with st.expander("ℹ️ Default Demo Credentials"):
            st.markdown(
                "- **Admin:** `admin` / `admin123`\n"
                "- **School Manager:** `manager` / `mgr123`\n"
                "- **Teacher:** `teacher1` / `teach123`\n"
                "- **Bursar:** `bursar` / `fees123`"
            )
    st.stop()

# Logged-in User Sidebar
user = st.session_state.user
if user.get("passport_photo"):
    st.sidebar.image(user["passport_photo"], caption=f"{user['full_name']} ({user['role']})", width=120)
st.sidebar.success(f"👤 **{user['full_name']}**\n\nRole: `{user['role']}`")
if st.sidebar.button("Logout"):
    st.session_state.user = None
    st.rerun()

# Role-based Navigation
if user["role"] in ["Admin", "Manager"]:
    nav_options = [
        "📊 Dashboard, Gender Totals & Filters",
        "📝 Student Registration & Edit",
        "👨‍🏫 Teacher Registration & Directory",
        "👔 School Manager Profile & Timetable/Register",
        "🧮 Continuous Assessment & Score Entry",
        "🎓 Student Certificates & Term Honours",
        "📥 CSV File Generator & Data Export",
        "💰 Fees, Teacher Salaries & Occasions/Incidents",
        "📬 Teacher Issues & Manager Replies",
        "📄 Terminal Report Cards (PDF Export)",
        "👥 Manage Staff & Roles",
    ]
elif user["role"] == "Teacher":
    nav_options = [
        "📊 Dashboard, Gender Totals & Filters",
        "📖 Daily/Weekly Lessons & Remaining Topics",
        "🧮 Continuous Assessment & Score Entry",
        "🎓 Student Certificates & Term Honours",
        "📥 CSV File Generator & Data Export",
        "📩 Report Issues to School Manager",
        "📄 Terminal Report Cards (PDF Export)",
    ]
else:  # Bursar
    nav_options = [
        "📊 Dashboard, Gender Totals & Filters",
        "📥 CSV File Generator & Data Export",
        "💰 Fees, Teacher Salaries & Occasions/Incidents",
    ]

menu = st.sidebar.radio("System Modules", nav_options)


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
    c.execute("SELECT COUNT(*) AS cnt FROM students")
    current_count = c.fetchone()["cnt"]
    suggested_adm_no = generate_admission_number("Mensah", "Kwame", "Boateng", current_count + 1)

    tab_reg, tab_edit = st.tabs(["➕ Register New Learner", "✏️ Edit Existing Learner Entry"])

    with tab_reg:
        with st.form("student_registration_form", clear_on_submit=True):
            st.markdown("#### Learner Name & Auto Admission Number")
            n1, n2, n3 = st.columns(3)
            with n1:
                surname = st.text_input("Surname *", placeholder="e.g., Mensah")
            with n2:
                first_name = st.text_input("First Name *", placeholder="e.g., Kwame")
            with n3:
                middle_name = st.text_input("Middle Name (Optional)", placeholder="e.g., Boateng")

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
                if not confirm_reg:
                    st.error("Please tick the confirmation box before submitting.")
                elif not surname.strip() or not first_name.strip():
                    st.error("Surname and First Name are required.")
                else:
                    c.execute("SELECT COUNT(*) AS cnt FROM students")
                    seq = c.fetchone()["cnt"] + 1
                    adm_no = (
                        generate_admission_number(surname.strip(), first_name.strip(), middle_name.strip(), seq)
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
                                    surname.strip(),
                                    first_name.strip(),
                                    middle_name.strip(),
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
                            st.success(f"Learner **{full_nm}** registered with Admission No. **`{adm_no}`**!")
                        except sqlite3.IntegrityError:
                            st.error(f"Admission Number `{adm_no}` already exists. Please submit again.")

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

                # Match students explicitly assigned to this teacher OR in the teacher's assigned class/subject timetable
                t_stu_df = pd.read_sql_query(
                    """
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
                         OR (? IS NOT NULL AND ? != 'All / Multiple Classes' AND s.class_level = ?)
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
                        t_info_obj["assigned_class_level"],
                        t_info_obj["assigned_class_level"],
                        t_info_obj["assigned_class_level"],
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

    conn.close()


# ---------------------------------------------------------
# MODULE 3: TEACHER REGISTRATION & DIRECTORY
# ---------------------------------------------------------
elif menu == "👨‍🏫 Teacher Registration & Directory":
    st.header("Teacher Registration & Directory")
    st.caption("Includes WASSCE and Pupil Teacher academic programmes, passport photo, and confirmation before submit.")

    conn = get_connection()
    c = conn.cursor()

    with st.form("teacher_registration_form", clear_on_submit=True):
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

        assigned_cls_lvl = st.selectbox("Primary Class / Grade Level Assigned (Optional)", ["All / Multiple Classes"] + CLASS_LEVELS)
        confirm_t = st.checkbox("I confirm all teacher registration entries are accurate.")
        if st.form_submit_button("Register Teacher"):
            if not confirm_t:
                st.error("Please tick the confirmation box before submitting.")
            elif not staff_id.strip() or not t_surname.strip() or not t_first.strip():
                st.error("Staff ID, Surname, and First Name are required.")
            elif create_login and (not t_user.strip() or not t_pass.strip()):
                st.error("Please provide Username and Password for the teacher portal login.")
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
                            t_surname.strip(),
                            t_first.strip(),
                            t_middle.strip(),
                            full_t_name,
                            t_gender,
                            t_phone.strip(),
                            t_email.strip(),
                            acad_prog,
                            department,
                            assigned_sub,
                            assigned_cls_lvl,
                            t_photo_bytes,
                            t_photo_mime,
                            datetime.now().strftime("%Y-%m-%d"),
                            t_user.strip() if create_login else None,
                        ),
                    )
                    if create_login:
                        c.execute(
                            "INSERT INTO users (username, password_hash, full_name, role, assigned_subject, passport_photo, passport_mime) VALUES (?, ?, ?, 'Teacher', ?, ?, ?)",
                            (t_user.strip(), hash_password(t_pass), full_t_name, assigned_sub, t_photo_bytes, t_photo_mime),
                        )
                    conn.commit()
                    st.success(f"Teacher **{full_t_name}** (`{staff_id.upper()}`) registered under **{acad_prog}**!")
                except sqlite3.IntegrityError:
                    st.error("Staff ID or Username already exists.")

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
                st.markdown(f"**{tr['full_name']}** (`{tr['staff_id']}`) — **{tr['gender']}** | **{tr['academic_programme']}** | Subject: **{tr['assigned_subject']}** | Dept: {tr['department']} | Tel: {tr['phone']}")
    conn.close()


# ---------------------------------------------------------
# MODULE 4: SCHOOL MANAGER PROFILE, REGISTER & CLASH-FREE TIMETABLE
# ---------------------------------------------------------
elif menu == "👔 School Manager Profile & Timetable/Register":
    st.header("School Manager Privileges: Passport Profile, Register & Timetable")
    conn = get_connection()
    c = conn.cursor()

    tab_mgr, tab_tt, tab_reg = st.tabs([
        "🪪 School Manager Profile & Passport",
        "🗓️ Clash-Free Timetable Generator",
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
            confirm_m = st.checkbox("Confirm School Manager details before saving.")
            if st.form_submit_button("Save School Manager Profile"):
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
                    st.success(f"School Manager profile updated: **{m_full}**!")

    with tab_tt:
        st.subheader("Automatic Clash-Free School Timetable")
        st.write("Choose a class, select subjects, and pick your timetable generation option without teacher or slot clashes.")

        with st.form("timetable_gen_form"):
            t1, t2 = st.columns(2)
            with t1:
                target_cls = st.selectbox("Select Class / Grade Level", CLASS_LEVELS)
                gen_choice = st.radio(
                    "Choose Timetable Generation Option",
                    [
                        "Option A: Full Week Clash-Free Auto-Schedule (Mon–Fri, 6 Periods)",
                        "Option B: Core & Primary Subjects Auto-Schedule (Mon–Fri, 4 Periods)",
                    ],
                )
            with t2:
                selected_subs = st.multiselect(
                    "Subjects to Include",
                    SUBJECTS_LIST,
                    default=["RME", "Social Studies", "Mathematics", "English Language", "Integrated Science", "ICT (Core/Elective)"],
                )
            confirm_tt = st.checkbox("Confirm timetable generation for selected class.")
            if st.form_submit_button("Generate Clash-Free Timetable"):
                if not confirm_tt:
                    st.error("Please confirm before generating the timetable.")
                else:
                    days_list = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
                    if "Option A" in gen_choice:
                        slots_list = ["08:00-09:00", "09:00-10:00", "10:30-11:30", "11:30-12:30", "13:00-14:00", "14:00-15:00"]
                        mode_label = "Option A (6-Period Clash-Free)"
                    else:
                        slots_list = ["08:00-09:30", "09:30-11:00", "11:30-13:00", "13:00-14:30"]
                        mode_label = "Option B (4-Period Clash-Free)"

                    ins_cnt, skip_cnt = generate_clash_free_timetable(
                        conn, target_cls, days_list, slots_list, selected_subs, mode_label, user["full_name"]
                    )
                    st.success(f"Timetable generated for **{target_cls}** ({ins_cnt} slots scheduled, {skip_cnt} teacher conflicts avoided).")

        tt_df = pd.read_sql_query(
            "SELECT class_level AS 'Class', day_of_week AS 'Day', time_slot AS 'Time', subject AS 'Subject', teacher_name AS 'Teacher', mode_used AS 'Mode' FROM school_timetable ORDER BY slot_id ASC",
            conn,
        )
        if not tt_df.empty:
            st.dataframe(tt_df, use_container_width=True)

    with tab_reg:
        st.subheader("Automatic School Register Generator")
        st.write("Choose a class and date to automatically generate/update the daily school register for active learners.")
        with st.form("school_register_form"):
            r1, r2, r3 = st.columns(3)
            with r1:
                reg_date = st.date_input("Register Date", value=datetime.now().date())
            with r2:
                reg_class = st.selectbox("Class / Grade Level", CLASS_LEVELS, key="reg_cls_sel")
            with r3:
                default_att = st.selectbox("Default Attendance Mark", ["Present", "Absent", "Late"])
            confirm_r = st.checkbox("Confirm school register generation.")
            if st.form_submit_button("Generate / Sync School Register"):
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

    with st.form("lesson_log_form", clear_on_submit=True):
        l1, l2, l3 = st.columns(3)
        with l1:
            l_class = st.selectbox("Class / Grade Level", CLASS_LEVELS)
        with l2:
            l_subject = st.selectbox("Subject", SUBJECTS_LIST)
        with l3:
            period_type = st.selectbox("Log Frequency", ["Daily", "Weekly"])
        log_date = st.date_input("Date", value=datetime.now().date())
        areas_taught = st.text_area("Areas / Topics Taught (Daily or Weekly) *", placeholder="List sub-topics, exercises, and practicals completed...")
        areas_left = st.text_area("Areas Left to Cover in Lessons *", placeholder="List remaining syllabus topics yet to be taught...")
        confirm_l = st.checkbox("Confirm lesson coverage details before submitting.")

        if st.form_submit_button("Submit Lesson Log"):
            if not confirm_l:
                st.error("Please tick confirmation before submitting.")
            elif not areas_taught.strip() or not areas_left.strip():
                st.error("Both Areas Taught and Areas Left to Cover are required.")
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
    st.caption("Arrange class lists into rows and columns for direct entry, download/upload CSV or Excel (.xlsx/.xls) score sheets, and press Enter in score boxes to move to the next input field.")

    # Keyboard Enter-to-next-input helper across score inputs
    st.components.v1.html(
        """
        <script>
        (function() {
            const doc = window.parent.document;
            if (doc.__enterNavBound) return;
            doc.__enterNavBound = true;
            doc.addEventListener("keydown", function(e) {
                if (e.key !== "Enter") return;
                const active = doc.activeElement;
                if (!active) return;
                const isInput = active.tagName === "INPUT" && (active.type === "text" || active.type === "number");
                if (!isInput) return;
                e.preventDefault();
                const inputs = Array.from(doc.querySelectorAll('input[type="text"], input[type="number"]'))
                    .filter(el => !el.disabled && el.offsetParent !== null);
                const idx = inputs.indexOf(active);
                if (idx >= 0 && idx < inputs.length - 1) {
                    const nextEl = inputs[idx + 1];
                    nextEl.focus();
                    if (typeof nextEl.select === "function") {
                        nextEl.select();
                    }
                }
            }, true);
        })();
        </script>
        """,
        height=0,
    )

    conn = get_connection()
    students = pd.read_sql_query(
        "SELECT student_id, full_name, class_level, program FROM students WHERE status = 'Active' ORDER BY class_level, full_name",
        conn,
    )

    if students.empty:
        st.warning("Please register learners first.")
    else:
        top1, top2, top3 = st.columns(3)
        with top1:
            term = st.selectbox("Academic Term", ["2026/2027 - Term 1", "2026/2027 - Term 2", "2026/2027 - Term 3"], key="ass_term_sel")
        with top2:
            subject = st.selectbox("Subject", SUBJECTS_LIST, key="ass_sub_sel")
        with top3:
            class_choices = sorted(students["class_level"].dropna().unique().tolist())
            selected_cls = st.selectbox("Select Class / Grade Level", class_choices, key="ass_cls_sel")

        cls_students = students[students["class_level"] == selected_cls].reset_index(drop=True)
        existing_scores_df = pd.read_sql_query(
            "SELECT student_id, class_test_1, class_test_2, project_work, exam_raw FROM assessments WHERE term = ? AND subject = ?",
            conn,
            params=(term, subject),
        )
        existing_map = {r["student_id"]: dict(r) for _, r in existing_scores_df.iterrows()}

        roster_rows = []
        for _, sr in cls_students.iterrows():
            ex = existing_map.get(sr["student_id"], {})
            roster_rows.append(
                {
                    "Admission_No": sr["student_id"],
                    "Learner_Name": sr["full_name"],
                    "Class_Level": sr["class_level"],
                    "Term": term,
                    "Subject": subject,
                    "Class_Test_1_Max20": float(ex.get("class_test_1", 0.0) or 0.0),
                    "Class_Test_2_Max20": float(ex.get("class_test_2", 0.0) or 0.0),
                    "Project_Work_Max20": float(ex.get("project_work", 0.0) or 0.0),
                    "Exam_Raw_Max100": float(ex.get("exam_raw", 0.0) or 0.0),
                }
            )
        roster_df = pd.DataFrame(roster_rows)

        csv_buf = io.StringIO()
        roster_df.to_csv(csv_buf, index=False)
        csv_filename = f"{re.sub(r'[^A-Za-z0-9_]+', '_', selected_cls)}_{re.sub(r'[^A-Za-z0-9_]+', '_', subject)}_Scores.csv"
        st.download_button(
            label=f"📥 Download Class Score CSV for Excel ({csv_filename})",
            data=csv_buf.getvalue().encode("utf-8"),
            file_name=csv_filename,
            mime="text/csv",
        )

        uploaded_sheet = st.file_uploader(
            "📤 Upload Recorded Excel (.xlsx / .xls) or CSV Score Sheet (Auto-Fills Scores Below)",
            type=["xlsx", "xls", "csv"],
            key="ass_excel_csv_upload",
        )

        if uploaded_sheet is not None:
            upload_key_sig = f"{uploaded_sheet.name}_{uploaded_sheet.size}_{term}_{subject}_{selected_cls}"
            if st.session_state.get("last_loaded_score_sheet") != upload_key_sig:
                try:
                    if uploaded_sheet.name.lower().endswith(".csv"):
                        up_df = pd.read_csv(uploaded_sheet)
                    else:
                        up_df = pd.read_excel(uploaded_sheet)

                    col_lookup = {str(col).strip().lower(): col for col in up_df.columns}

                    def _pick_col(candidates):
                        for cand in candidates:
                            if cand in col_lookup:
                                return col_lookup[cand]
                        for k, orig in col_lookup.items():
                            for cand in candidates:
                                if cand in k:
                                    return orig
                        return None

                    id_col = _pick_col(["admission_no", "adm. no.", "adm_no", "student_id", "id"])
                    name_col = _pick_col(["learner_name", "learner name", "full_name", "student_name", "name"])
                    t1_col = _pick_col(["class_test_1_max20", "class_test_1", "test 1", "test1", "t1"])
                    t2_col = _pick_col(["class_test_2_max20", "class_test_2", "test 2", "test2", "t2"])
                    pj_col = _pick_col(["project_work_max20", "project_work", "project", "proj"])
                    ex_col = _pick_col(["exam_raw_max100", "exam_raw", "exam", "exam_score"])

                    applied_count = 0
                    for _, urow in up_df.iterrows():
                        matched_sid = None
                        if id_col and pd.notna(urow[id_col]):
                            cand_id = str(urow[id_col]).strip()
                            if cand_id in cls_students["student_id"].values:
                                matched_sid = cand_id
                        if not matched_sid and name_col and pd.notna(urow[name_col]):
                            cand_nm = str(urow[name_col]).strip().lower()
                            hit = cls_students[cls_students["full_name"].str.lower() == cand_nm]
                            if not hit.empty:
                                matched_sid = hit.iloc[0]["student_id"]

                        if matched_sid:
                            v_t1 = float(pd.to_numeric(urow[t1_col], errors="coerce")) if (t1_col and pd.notna(urow[t1_col])) else 0.0
                            v_t2 = float(pd.to_numeric(urow[t2_col], errors="coerce")) if (t2_col and pd.notna(urow[t2_col])) else 0.0
                            v_pj = float(pd.to_numeric(urow[pj_col], errors="coerce")) if (pj_col and pd.notna(urow[pj_col])) else 0.0
                            v_ex = float(pd.to_numeric(urow[ex_col], errors="coerce")) if (ex_col and pd.notna(urow[ex_col])) else 0.0

                            v_t1 = max(0.0, min(20.0, 0.0 if pd.isna(v_t1) else v_t1))
                            v_t2 = max(0.0, min(20.0, 0.0 if pd.isna(v_t2) else v_t2))
                            v_pj = max(0.0, min(20.0, 0.0 if pd.isna(v_pj) else v_pj))
                            v_ex = max(0.0, min(100.0, 0.0 if pd.isna(v_ex) else v_ex))

                            st.session_state[f"sc_t1_{matched_sid}"] = f"{v_t1:g}"
                            st.session_state[f"sc_t2_{matched_sid}"] = f"{v_t2:g}"
                            st.session_state[f"sc_pj_{matched_sid}"] = f"{v_pj:g}"
                            st.session_state[f"sc_ex_{matched_sid}"] = f"{v_ex:g}"
                            applied_count += 1

                    st.session_state["last_loaded_score_sheet"] = upload_key_sig
                    st.success(f"Auto-filled scores for **{applied_count}** student(s) from `{uploaded_sheet.name}`! Review below and click **Save All Class Scores**.")
                except Exception as up_err:
                    st.error(f"Could not read uploaded sheet: {up_err}")

        st.divider()
        st.subheader(f"📋 Class Score Grid — {selected_cls} ({subject} • {term})")
        st.caption("Type scores in each row; pressing **Enter** moves directly to the next score input box.")

        with st.form("class_grid_assessment_form"):
            hdr1, hdr2, hdr3, hdr4, hdr5, hdr6 = st.columns([2.6, 1.1, 1.1, 1.1, 1.2, 1.3])
            hdr1.markdown("**Learner (Adm. No. — Name)**")
            hdr2.markdown("**Test 1 (/20)**")
            hdr3.markdown("**Test 2 (/20)**")
            hdr4.markdown("**Project (/20)**")
            hdr5.markdown("**Exam (/100)**")
            hdr6.markdown("**Total & Grade**")

            row_widgets = []
            for _, sr in cls_students.iterrows():
                sid = sr["student_id"]
                ex = existing_map.get(sid, {})
                def_t1 = f"{float(ex.get('class_test_1', 0.0) or 0.0):g}"
                def_t2 = f"{float(ex.get('class_test_2', 0.0) or 0.0):g}"
                def_pj = f"{float(ex.get('project_work', 0.0) or 0.0):g}"
                def_ex = f"{float(ex.get('exam_raw', 0.0) or 0.0):g}"

                if f"sc_t1_{sid}" not in st.session_state:
                    st.session_state[f"sc_t1_{sid}"] = def_t1
                if f"sc_t2_{sid}" not in st.session_state:
                    st.session_state[f"sc_t2_{sid}"] = def_t2
                if f"sc_pj_{sid}" not in st.session_state:
                    st.session_state[f"sc_pj_{sid}"] = def_pj
                if f"sc_ex_{sid}" not in st.session_state:
                    st.session_state[f"sc_ex_{sid}"] = def_ex

                c_nm, c_t1, c_t2, c_pj, c_ex, c_tot = st.columns([2.6, 1.1, 1.1, 1.1, 1.2, 1.3])
                with c_nm:
                    st.markdown(f"**{sr['full_name']}** (`{sid}`)")
                with c_t1:
                    w_t1 = st.text_input("T1", key=f"sc_t1_{sid}", label_visibility="collapsed")
                with c_t2:
                    w_t2 = st.text_input("T2", key=f"sc_t2_{sid}", label_visibility="collapsed")
                with c_pj:
                    w_pj = st.text_input("Proj", key=f"sc_pj_{sid}", label_visibility="collapsed")
                with c_ex:
                    w_ex = st.text_input("Exam", key=f"sc_ex_{sid}", label_visibility="collapsed")

                try:
                    pv_t1 = max(0.0, min(20.0, float(w_t1 or 0)))
                    pv_t2 = max(0.0, min(20.0, float(w_t2 or 0)))
                    pv_pj = max(0.0, min(20.0, float(w_pj or 0)))
                    pv_ex = max(0.0, min(100.0, float(w_ex or 0)))
                    _, _, pv_tot, pv_grd, _ = compute_assessment(pv_t1, pv_t2, pv_pj, pv_ex)
                except ValueError:
                    pv_tot, pv_grd = 0.0, "ERR"

                with c_tot:
                    st.markdown(f"**{pv_tot}%** (`{pv_grd}`)")

                row_widgets.append((sid, sr["full_name"], w_t1, w_t2, w_pj, w_ex))

            confirm_sc = st.checkbox("Confirm all class scores before saving to database.", key="conf_class_grid_save")
            if st.form_submit_button("Save All Class Scores"):
                if not confirm_sc:
                    st.error("Please tick confirmation before saving scores.")
                else:
                    try:
                        create_db_backup("class_scores_save")
                        c = conn.cursor()
                        saved_cnt = 0
                        for sid, _, raw_t1, raw_t2, raw_pj, raw_ex in row_widgets:
                            t1 = max(0.0, min(20.0, float(raw_t1 or 0)))
                            t2 = max(0.0, min(20.0, float(raw_t2 or 0)))
                            proj = max(0.0, min(20.0, float(raw_pj or 0)))
                            exam_raw = max(0.0, min(100.0, float(raw_ex or 0)))
                            sba_w, exam_w, total, grade, remark = compute_assessment(t1, t2, proj, exam_raw)
                            c.execute(
                                """
                                INSERT INTO assessments (
                                    student_id, term, subject, class_test_1, class_test_2, project_work,
                                    exam_raw, sba_weighted, exam_weighted, total_score, grade, remark
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(student_id, term, subject) DO UPDATE SET
                                    class_test_1=excluded.class_test_1,
                                    class_test_2=excluded.class_test_2,
                                    project_work=excluded.project_work,
                                    exam_raw=excluded.exam_raw,
                                    sba_weighted=excluded.sba_weighted,
                                    exam_weighted=excluded.exam_weighted,
                                    total_score=excluded.total_score,
                                    grade=excluded.grade,
                                    remark=excluded.remark
                                """,
                                (sid, term, subject, t1, t2, proj, exam_raw, sba_w, exam_w, total, grade, remark),
                            )
                            saved_cnt += 1
                        conn.commit()
                        st.success(f"Saved scores for **{saved_cnt}** learner(s) in **{selected_cls}** ({subject} • {term})!")
                    except Exception as save_err:
                        conn.rollback()
                        st.error(f"Error saving scores: {save_err}")

        broad_df = pd.read_sql_query(
            """
            SELECT a.student_id AS 'Adm. No.', s.full_name AS 'Learner Name', s.class_level AS 'Class',
                   a.term AS 'Term', a.subject AS 'Subject', a.sba_weighted AS 'SBA (30%)',
                   a.exam_weighted AS 'Exam (70%)', a.total_score AS 'Total (100%)',
                   a.grade AS 'Grade', a.remark AS 'Remark'
            FROM assessments a JOIN students s ON a.student_id = s.student_id
            WHERE a.term = ? AND a.subject = ? AND s.class_level = ?
            ORDER BY a.total_score DESC
            """,
            conn,
            params=(term, subject, selected_cls),
        )
        if not broad_df.empty:
            st.subheader("Recorded Assessments for Selected Class & Subject")
            st.dataframe(broad_df, use_container_width=True)

    conn.close()


# ---------------------------------------------------------
# MODULE 7: STUDENT CERTIFICATES OF COMPLETION & TERM HONOURS
# ---------------------------------------------------------
elif menu == "🎓 Student Certificates & Term Honours":
    st.header("Professional Student Certificates & End-of-Term Honours")
    st.caption("Generate official PDF certificates featuring the learner's name, passport photo, and academic citation.")

    conn = get_connection()
    c = conn.cursor()
    students_rows = c.execute("SELECT * FROM students ORDER BY full_name ASC").fetchall()

    tab_comp, tab_term = st.tabs([
        "🏅 Certificate of Completion (Individual Learner)",
        "🌟 End-of-Term Overall Qualification Certificates",
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
                cert_sub = st.text_input("Certificate Subtitle", value=f"Awarded upon Successful Completion of {stu_obj['class_level']}")
                default_citation = (
                    f"having diligently fulfilled all academic, moral, and practical requirements prescribed by "
                    f"{SCHOOL_NAME} in {stu_obj['class_level']} ({stu_obj['program']}), is hereby awarded this Certificate of Completion "
                    f"with all rights, honours, and privileges appertaining thereto."
                )
                citation_txt = st.text_area("Certificate Citation", value=default_citation, height=95)
                mgr_signatory = st.text_input("School Manager Signatory Name", value=user["full_name"])

            cert_no = f"GIS-CERT-{stu_obj['student_id']}-{datetime.now().strftime('%Y%m%d')}"
            issue_dt = datetime.now().strftime("%d %B %Y")
            pdf_cert = generate_student_certificate_pdf(
                stu_obj, cert_no, cert_title, cert_sub, citation_txt, issue_dt, mgr_signatory
            )

            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                if st.button("Log & Download Certificate of Completion"):
                    c.execute(
                        """
                        INSERT OR IGNORE INTO issued_certificates (
                            certificate_no, student_id, student_name, cert_type, term, average_score, honour_tier, issued_date, issued_by
                        ) VALUES (?, ?, ?, 'Completion', 'Full Programme', NULL, ?, ?, ?)
                        """,
                        (cert_no, stu_obj["student_id"], stu_obj["full_name"], cert_title, issue_dt, user["full_name"]),
                    )
                    conn.commit()
                    st.success(f"Certificate `{cert_no}` logged!")
            with col_dl2:
                st.download_button(
                    label="📥 Download PDF Certificate of Completion",
                    data=pdf_cert,
                    file_name=f"{stu_obj['student_id']}_Completion_Certificate.pdf",
                    mime="application/pdf",
                )

    with tab_term:
        st.subheader("End-of-Term Overall Qualification & Merit Certification")
        st.write("Automatically evaluates learners at the end of the selected term and issues Overall Term Certificates to all qualified pupils.")

        t_col1, t_col2, t_col3 = st.columns(3)
        with t_col1:
            eval_term = st.selectbox("Select Academic Term", ["2026/2027 - Term 1", "2026/2027 - Term 2", "2026/2027 - Term 3"])
        with t_col2:
            eval_class = st.selectbox("Filter Class / Grade Level", ["All Classes"] + CLASS_LEVELS, key="cert_term_cls")
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
        if eval_class != "All Classes":
            query += " AND s.class_level = ?"
            params.append(eval_class)
        query += " GROUP BY s.student_id ORDER BY overall_avg DESC"

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

                term_cert_no = f"GIS-TERM-{q_stu['student_id']}-{datetime.now().strftime('%Y%m%d')}"
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
                        for item in qualified_list:
                            c_no = f"GIS-TERM-{item['student_id']}-{eval_term.replace(' ', '').replace('/', '')}"
                            c.execute(
                                """
                                INSERT OR IGNORE INTO issued_certificates (
                                    certificate_no, student_id, student_name, cert_type, term, average_score, honour_tier, issued_date, issued_by
                                ) VALUES (?, ?, ?, 'End-of-Term Overall', ?, ?, ?, ?, ?)
                                """,
                                (c_no, item["student_id"], item["full_name"], eval_term, item["overall_avg"], item["honour_tier"], term_issue_dt, user["full_name"]),
                            )
                        conn.commit()
                        st.success(f"Logged certificates for all **{len(qualified_list)}** qualified pupils!")
                with c_t2:
                    st.download_button(
                        label="📥 Download Selected Pupil's End-of-Term Certificate (PDF)",
                        data=term_pdf,
                        file_name=f"{q_stu['student_id']}_{eval_term.replace('/', '_')}_Term_Certificate.pdf",
                        mime="application/pdf",
                    )
            else:
                st.warning(f"No pupils met the qualifying average of {qual_threshold}% for {eval_term}.")

    conn.close()


# ---------------------------------------------------------
# MODULE 8: CSV FILE GENERATOR & FILTERED DATA EXPORT
# ---------------------------------------------------------
elif menu == "📥 CSV File Generator & Data Export":
    st.header("CSV File Generator & Filtered Data Export")
    st.caption("Filter school records by dataset, gender, class / grade level, or term and download ready-to-use CSV files.")

    conn = get_connection()
    dataset_choice = st.selectbox(
        "Select Dataset to Export as CSV",
        [
            "Students Register",
            "Teachers Directory",
            "Combined Population (Students + Teachers with Gender Summary)",
            "Student Assessments & Grades",
            "Qualified End-of-Term Pupils",
            "Fee Payments Ledger",
            "Teacher Salary Payments",
            "School Attendance Register",
            "School Timetable",
            "Incident Reports & Special Occasions",
        ],
    )

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

    t_fees, t_sal, t_occ, t_inc = st.tabs([
        "💳 School Fees & Receipts",
        "💵 Teacher Salary Payments",
        "🎉 Special Activities / Occasions",
        "⚠️ Incident Reports",
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
                conn.commit()
                st.success("Your issue has been sent to the School Manager!")

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
                    conn.commit()
                    st.success(f"Reply sent to **{target_issue['teacher_name']}**!")

    conn.close()


# ---------------------------------------------------------
# MODULE 11: TERMINAL REPORT CARDS (PDF EXPORT)
# ---------------------------------------------------------
elif menu == "📄 Terminal Report Cards (PDF Export)":
    st.header("Automated Terminal Report Card & PDF Generator")
    conn = get_connection()
    students = pd.read_sql_query("SELECT * FROM students WHERE status='Active' ORDER BY full_name ASC", conn)
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

            if rep_df.empty:
                st.info("No assessment scores recorded for this learner in the selected term.")
            else:
                st.table(rep_df)
                overall_avg = round(rep_df["Total (100%)"].mean(), 2)
                overall_total = round(rep_df["Total (100%)"].sum(), 2)
                comment = "Commendable academic progress. Keep working diligently." if overall_avg >= 60 else "Needs extra academic support and consistent practice."
                pdf_bytes = generate_terminal_report_pdf(s_info, chosen_term, rep_df, overall_total, overall_avg, comment, app_info)
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
    st.header("Staff Accounts & Role Assignment")
    conn = get_connection()
    c = conn.cursor()
    with st.form("manage_roles_form"):
        u_rows = c.execute("SELECT username, full_name, role FROM users").fetchall()
        u_map = {f"{r['username']} — {r['full_name']} ({r['role']})": r["username"] for r in u_rows}
        sel_u = st.selectbox("Select Account", list(u_map.keys()))
        new_r = st.selectbox("Assign Role", ["Manager", "Admin", "Teacher", "Bursar"])
        conf_u = st.checkbox("Confirm role update.")
        if st.form_submit_button("Update Role"):
            if not conf_u:
                st.error("Please confirm before updating.")
            else:
                c.execute("UPDATE users SET role=? WHERE username=?", (new_r, u_map[sel_u]))
                conn.commit()
                st.success(f"Updated role for `{u_map[sel_u]}` to **{new_r}**!")
    df_u = pd.read_sql_query("SELECT username, full_name, role, assigned_subject FROM users", conn)
    st.dataframe(df_u, use_container_width=True)
    conn.close()
