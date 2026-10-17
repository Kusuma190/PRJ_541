from flask import Flask, render_template, request, Response, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
import os
import math
import mysql.connector
import random
import csv
import io
import joblib
import pandas as pd
from functools import wraps
from db_config import DB_CONFIG
from semester_utils import MAX_SEMESTER, clamp_semester, build_sgpa_points

app = Flask(__name__)

# The secret key signs the login cookie. It is never stored in the code: a public
# default would let anyone forge a login. The app refuses to start without one.
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    raise RuntimeError(
        "SECRET_KEY is not set. Add it to your .env file (local) "
        "or to Render's Environment settings (deployed)."
    )
app.secret_key = _secret

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,    # JavaScript cannot read the login cookie
    SESSION_COOKIE_SAMESITE="Lax",   # basic protection against cross-site requests
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",  # HTTPS-only cookie when deployed
)

PAGE_SIZE = 20

# ---------- Load trained models once at startup ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models")


def _load(name):
    return joblib.load(os.path.join(MODEL_DIR, name))


risk_model = _load("risk_model.pkl")
risk_features = _load("risk_features.pkl")
sgpa_median = _load("sgpa_median.pkl")
engagement_model = _load("engagement_model.pkl")
engagement_scaler = _load("engagement_scaler.pkl")
engagement_features = _load("engagement_features.pkl")


# ---------- Explainable risk: what drives a score, and what would change it ----------
RISK_COEF = dict(zip(risk_features, (float(c) for c in risk_model.coef_[0])))
RISK_INTERCEPT = float(risk_model.intercept_[0])

# (feature, label shown to the student, value format)
EXPLAIN_FACTORS = [
    ("attendance_pct", "Attendance", "{:.0f}%"),
    ("study_hours", "Daily study time", "{:.1f} hrs"),
    ("previous_sgpa_clean", "Previous SGPA", "{:.2f} / 4.0"),
]
# Things a student can actually change: (feature, action, max value, rounding step, format).
# Social-media time is deliberately NOT used for advice: in this survey data its link to risk
# is not in the expected direction, so recommending anything about it would be misleading.
LEVERS = [
    ("attendance_pct", "Raise attendance", 100.0, 1.0, "{:.0f}%"),
    ("study_hours", "Raise daily study time", 12.0, 0.5, "{:.1f} hrs"),
]


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z))


def explain_risk(student, means):
    """Return the model's risk score for one student, the factors driving it, and the
    smallest single changes (attendance or study time) that would bring it below 50%.
    `means` maps each model feature to the class average."""

    def num(value, fallback):
        try:
            return float(value) if value is not None else float(fallback)
        except (TypeError, ValueError):
            return float(fallback)

    prev = student.get("previous_sgpa")
    x = {
        "attendance_pct": num(student.get("attendance_pct"), means["attendance_pct"]),
        "study_hours": num(student.get("study_hours"), means["study_hours"]),
        "social_media_hours": num(student.get("social_media_hours"), means["social_media_hours"]),
        "credits_completed": num(student.get("credits_completed"), means["credits_completed"]),
        "previous_sgpa_clean": num(prev if prev else None, sgpa_median),  # 0 = "no record yet"
    }
    logit = RISK_INTERCEPT + sum(RISK_COEF[f] * x[f] for f in risk_features)
    at_risk = logit >= 0

    factors = []
    for feat, label, fmt in EXPLAIN_FACTORS:
        effect = RISK_COEF[feat] * (x[feat] - float(means[feat]))
        factors.append({
            "label": label,
            "yours": fmt.format(x[feat]),
            "average": fmt.format(float(means[feat])),
            "direction": "raises" if effect > 0 else "lowers",
            "size": abs(effect),
        })
    factors.sort(key=lambda f: f["size"], reverse=True)
    max_size = max((f["size"] for f in factors), default=0.0)

    suggestions, note = [], None
    if at_risk:
        for feat, action, cap, step, fmt in LEVERS:
            coef = RISK_COEF[feat]
            if coef >= 0:
                continue  # unexpected direction: never advise on it
            target = math.ceil((x[feat] + (logit + 0.02) / abs(coef)) / step - 1e-9) * step
            if target <= cap:
                suggestions.append(
                    f"{action} from {fmt.format(x[feat])} to {fmt.format(target)} (changing only this)")
        if not suggestions:
            c_att, c_study = RISK_COEF["attendance_pct"], RISK_COEF["study_hours"]
            if c_att < 0 and c_study < 0:
                logit_full_att = logit + c_att * (100.0 - x["attendance_pct"])
                need = max(x["study_hours"], x["study_hours"] + (logit_full_att + 0.02) / abs(c_study))
                need = math.ceil(need / 0.5 - 1e-9) * 0.5
                if need <= 12.0:
                    suggestions.append(
                        f"Combine both: attendance of 100% and about {need:.1f} hrs of daily study")
            if not suggestions:
                note = ("Even full attendance and 12 hrs of daily study would not bring the score below "
                        "the threshold. Previous SGPA is the largest factor in your score, so strong "
                        "results in the coming semester are what move it most.")

    return {
        "score": round(_sigmoid(logit) * 100, 1),
        "at_risk": at_risk,
        "factors": factors,
        "max_size": max_size,
        "suggestions": suggestions,
        "note": note,
        "whatif": {
            "fixed": RISK_INTERCEPT + sum(RISK_COEF[f] * x[f] for f in risk_features
                                          if f not in ("attendance_pct", "study_hours")),
            "coef_att": RISK_COEF["attendance_pct"],
            "coef_study": RISK_COEF["study_hours"],
            "att": x["attendance_pct"],
            "study": x["study_hours"],
        },
    }


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


# ---------- Auth helpers ----------

def login_required(roles=None):
    """roles: None = any logged-in user, or a list like ['faculty','admin']"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if roles and session.get("role") not in roles:
                return "Access denied for your role.", 403
            return f(*args, **kwargs)
        return wrapped
    return decorator


@app.route("/")
def home():
    if "user_id" in session:
        if session["role"] == "student":
            return redirect(url_for("student_dashboard", student_id=session["student_id"]))
        elif session["role"] == "faculty":
            return redirect(url_for("faculty_dashboard"))
        elif session["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["student_id"] = user["student_id"]
            return redirect(url_for("home"))
        else:
            error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        roll_no = request.form.get("roll_no", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not roll_no or not password:
            return render_template("register.html", error="Roll number and password are required.")
        if password != confirm:
            return render_template("register.html", error="Passwords do not match.")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE username = %s", (roll_no,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return render_template("register.html", error="This roll number is already registered. Please log in instead.")

        cursor.execute("SELECT * FROM students WHERE student_id = %s", (roll_no,))
        existing_student = cursor.fetchone()

        if existing_student:
            # Claiming one of the pre-loaded demo students - no new data needed
            password_hash = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO users (username, password_hash, role, student_id) VALUES (%s, %s, 'student', %s)",
                (roll_no, password_hash, roll_no)
            )
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for("login"))

        # ---- New student: create a live profile from the submitted form ----
        try:
            student_name = request.form.get("student_name", "").strip() or "New Student"
            gender = request.form.get("gender", "Male")
            age = int(request.form.get("age", 20))
            current_semester = clamp_semester(request.form.get("current_semester", 1))
            attendance_pct = float(request.form.get("attendance_pct", 75))
            study_hours = float(request.form.get("study_hours", 2))
            social_media_hours = float(request.form.get("social_media_hours", 2))
            credits_completed = float(request.form.get("credits_completed", 20))
            previous_sgpa = float(request.form.get("previous_sgpa", 2.5))
        except ValueError:
            cursor.close()
            conn.close()
            return render_template("register.html", error="Please enter valid numbers for all academic fields.")

        # Assign a random synthetic department (source data has no real department field)
        cursor.execute("SELECT department_id, department_name FROM departments ORDER BY RAND() LIMIT 1")
        dept = cursor.fetchone()
        department_id = dept["department_id"]

        # ---- Live prediction using the saved models ----
        sgpa_for_model = previous_sgpa if previous_sgpa > 0 else sgpa_median
        risk_input = pd.DataFrame([{
            "attendance_pct": attendance_pct,
            "study_hours": study_hours,
            "social_media_hours": social_media_hours,
            "credits_completed": credits_completed,
            "previous_sgpa_clean": sgpa_for_model,
        }])[risk_features]
        risk_prediction = int(risk_model.predict(risk_input)[0])

        eng_input = pd.DataFrame([{
            "study_hours": study_hours,
            "social_media_hours": social_media_hours,
            "attendance_pct": attendance_pct,
        }])[engagement_features]
        eng_scaled = engagement_scaler.transform(eng_input)
        engagement_level = engagement_model.predict(eng_scaled)[0]

        current_cgpa = previous_sgpa  # best available estimate for a brand-new record

        cursor.execute("""
            INSERT INTO students (
                student_id, student_name, department_id, admission_year, gender, age,
                current_semester, previous_sgpa, current_cgpa, attendance_pct,
                study_hours, social_media_hours, credits_completed,
                probation, suspension, at_risk, risk_prediction, engagement_level
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            roll_no, student_name, department_id, None, gender, age,
            current_semester, previous_sgpa, current_cgpa, attendance_pct,
            study_hours, social_media_hours, credits_completed,
            "No", "No", risk_prediction, risk_prediction, engagement_level,
        ))

        # Lightweight synthetic course attendance (4 courses in their department)
        cursor.execute("SELECT course_id FROM courses WHERE department_id = %s", (department_id,))
        course_ids = [r["course_id"] for r in cursor.fetchall()]
        for cid in course_ids:
            val = max(40, min(100, attendance_pct + random.uniform(-8, 8)))
            cursor.execute(
                "INSERT INTO course_attendance (student_id, course_id, attendance_pct) VALUES (%s, %s, %s)",
                (roll_no, cid, round(val, 1))
            )

        # SGPA trend for Sem 1..N (last point is real, earlier points are simulated)
        for label, value in build_sgpa_points(current_semester, previous_sgpa, roll_no):
            cursor.execute(
                "INSERT INTO sgpa_history (student_id, semester_label, sgpa) VALUES (%s, %s, %s)",
                (roll_no, label, value)
            )

        password_hash = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, student_id) VALUES (%s, %s, 'student', %s)",
            (roll_no, password_hash, roll_no)
        )

        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for("login"))

    return render_template("register.html", error=error)


# ======================== STUDENT ========================

@app.route("/student/<student_id>")
@login_required()
def student_dashboard(student_id):
    # A student may only view their own dashboard; faculty/admin may view any
    if session["role"] == "student" and session["student_id"] != student_id:
        return "You do not have permission to view this student's dashboard.", 403

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT s.*, d.department_name
        FROM students s
        JOIN departments d ON s.department_id = d.department_id
        WHERE s.student_id = %s
    """, (student_id,))
    student = cursor.fetchone()

    if not student:
        cursor.close()
        conn.close()
        return f"No student found with ID {student_id}", 404

    cursor.execute("""
        SELECT c.course_name, ca.attendance_pct
        FROM course_attendance ca
        JOIN courses c ON ca.course_id = c.course_id
        WHERE ca.student_id = %s
    """, (student_id,))
    course_attendance = cursor.fetchall()

    cursor.execute("""
        SELECT semester_label, sgpa
        FROM sgpa_history
        WHERE student_id = %s
        ORDER BY id
    """, (student_id,))
    sgpa_history = cursor.fetchall()

    # An engineering programme has 8 semesters. Whatever is stored, never show more.
    student["current_semester"] = clamp_semester(student.get("current_semester"))
    sem = student["current_semester"]
    expected_labels = [f"Sem {i}" for i in range(1, sem + 1)]
    stored = {r["semester_label"]: r["sgpa"] for r in sgpa_history}
    if len(sgpa_history) == sem and all(label in stored for label in expected_labels):
        sgpa_history = [{"semester_label": label, "sgpa": stored[label]} for label in expected_labels]
    else:
        # Stored history is missing, out of range or from an older format: rebuild Sem 1..N.
        sgpa_history = [{"semester_label": label, "sgpa": value}
                        for label, value in build_sgpa_points(sem, student.get("previous_sgpa"), student_id)]

    cursor.execute("""
        SELECT AVG(attendance_pct) AS avg_att, AVG(study_hours) AS avg_study,
               AVG(social_media_hours) AS avg_social, AVG(credits_completed) AS avg_credits,
               AVG(CASE WHEN previous_sgpa > 0 THEN previous_sgpa END) AS avg_sgpa
        FROM students
    """)
    class_avgs = cursor.fetchone()

    cursor.close()
    conn.close()

    improvements = []
    if student["attendance_pct"] < class_avgs["avg_att"]:
        improvements.append(
            f"Attendance ({student['attendance_pct']:.0f}%) is below the class average "
            f"({class_avgs['avg_att']:.0f}%). Improving attendance is the single strongest "
            f"driver of risk reduction in this model."
        )
    if student["study_hours"] is not None and student["study_hours"] < class_avgs["avg_study"]:
        improvements.append(
            f"Daily study time ({student['study_hours']:.1f} hrs) is below the class average "
            f"({class_avgs['avg_study']:.1f} hrs)."
        )
    if student["social_media_hours"] is not None and student["social_media_hours"] > class_avgs["avg_social"]:
        improvements.append(
            f"Daily social media time ({student['social_media_hours']:.1f} hrs) is above the "
            f"class average ({class_avgs['avg_social']:.1f} hrs). Consider redirecting some of "
            f"this time toward study."
        )
    if not improvements:
        improvements.append(
            "This student is performing at or above class average on all tracked habits. "
            "Consider stretch goals like deeper subject mastery or peer mentoring."
        )

    cgpa10 = round((student["current_cgpa"] or 0) * 2.5, 2)
    if cgpa10 >= 8:
        cgpa_label = "Excellent"
    elif cgpa10 >= 6.5:
        cgpa_label = "Good"
    elif cgpa10 >= 5:
        cgpa_label = "Average"
    else:
        cgpa_label = "Needs Improvement"

    rng = random.Random(student_id)  # stable: the same student always sees the same marks
    base_marks = min(95, max(35, cgpa10 * 10 + rng.uniform(-8, 8)))
    course_marks = []
    for c in course_attendance:
        val = min(100, max(30, base_marks + rng.uniform(-10, 10)))
        course_marks.append({"course_name": c["course_name"], "marks": round(val, 1)})
    avg_marks = round(sum(c["marks"] for c in course_marks) / len(course_marks), 1) if course_marks else 0

    timetable = [
        ("Monday", "9:00 AM", "Data Structures", "Room 204"),
        ("Monday", "11:00 AM", "Database Systems", "Room 108"),
        ("Tuesday", "10:00 AM", "Operating Systems", "Room 301"),
        ("Wednesday", "9:00 AM", "Machine Learning", "Lab 2"),
        ("Thursday", "1:00 PM", "Software Engineering", "Room 204"),
        ("Friday", "11:00 AM", "Computer Networks", "Room 108"),
    ]
    notifications = [
        ("Mid-term exam scheduled for 15th May", "2 days ago"),
        ("Assignment 2 submitted successfully", "5 days ago"),
        ("Practical record updated", "1 week ago"),
        ("Fee payment reminder: due in 10 days", "1 week ago"),
    ]

    risk_info = explain_risk(student, {
        "attendance_pct": class_avgs["avg_att"],
        "study_hours": class_avgs["avg_study"],
        "social_media_hours": class_avgs["avg_social"],
        "credits_completed": class_avgs["avg_credits"],
        "previous_sgpa_clean": class_avgs["avg_sgpa"],
    })
    # Show the same live model result everywhere on this page (stored flags can be slightly
    # older than the model currently deployed).
    student["risk_prediction"] = 1 if risk_info["at_risk"] else 0

    return render_template(
        "student_dashboard.html",
        risk=risk_info,
        student=student, cgpa10=cgpa10, cgpa_label=cgpa_label,
        course_attendance=course_attendance, sgpa_history=sgpa_history,
        improvements=improvements, course_marks=course_marks, avg_marks=avg_marks,
        timetable=timetable, notifications=notifications,
    )


# ======================== FACULTY ========================

@app.route("/faculty")
@login_required(roles=["faculty", "admin"])
def faculty_dashboard():
    dept_name = request.args.get("dept", "CSE")
    page = max(1, request.args.get("page", 1, type=int))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT department_id FROM departments WHERE department_name = %s", (dept_name,))
    dept_row = cursor.fetchone()
    dept_id = dept_row["department_id"] if dept_row else None

    cursor.execute("SELECT department_name FROM departments ORDER BY department_name")
    all_departments = [r["department_name"] for r in cursor.fetchall()]

    cursor.execute("""
        SELECT COUNT(*) AS total, AVG(attendance_pct) AS avg_att, SUM(risk_prediction) AS at_risk
        FROM students WHERE department_id = %s
    """, (dept_id,))
    stats = cursor.fetchone()

    cursor.execute("""
        SELECT c.course_name, AVG(ca.attendance_pct) AS avg_att
        FROM course_attendance ca
        JOIN courses c ON ca.course_id = c.course_id
        WHERE c.department_id = %s
        GROUP BY c.course_name
    """, (dept_id,))
    course_perf = cursor.fetchall()

    cursor.execute("""
        SELECT student_id, student_name, attendance_pct, current_cgpa
        FROM students
        WHERE department_id = %s AND risk_prediction = 1
        ORDER BY attendance_pct ASC
        LIMIT 5
    """, (dept_id,))
    at_risk_students = cursor.fetchall()
    for s in at_risk_students:
        s["marks_equiv"] = round((s["current_cgpa"] or 0) * 10, 1)

    cursor.execute("""
        SELECT c.course_name, f.faculty_name
        FROM courses c
        JOIN faculty f ON c.faculty_id = f.faculty_id
        WHERE c.department_id = %s
    """, (dept_id,))
    my_classes = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS total FROM students WHERE department_id = %s", (dept_id,))
    dept_student_total = cursor.fetchone()["total"]
    total_pages = max(1, (dept_student_total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    offset = (page - 1) * PAGE_SIZE

    cursor.execute("""
        SELECT student_id, student_name, attendance_pct, current_cgpa, engagement_level
        FROM students
        WHERE department_id = %s
        ORDER BY student_name
        LIMIT %s OFFSET %s
    """, (dept_id, PAGE_SIZE, offset))
    dept_students = cursor.fetchall()

    cursor.close()
    conn.close()

    avg_att = round(stats["avg_att"] or 0, 1)
    course_labels = [c["course_name"].split(" (")[0] for c in course_perf]

    return render_template(
        "faculty_dashboard.html",
        dept_name=dept_name, all_departments=all_departments, stats=stats, avg_att=avg_att,
        course_perf=course_perf, course_labels=course_labels, at_risk_students=at_risk_students,
        my_classes=my_classes, dept_students=dept_students, page=page, total_pages=total_pages,
    )


@app.route("/faculty/export/attendance")
@login_required(roles=["faculty", "admin"])
def export_faculty_attendance():
    dept_name = request.args.get("dept", "CSE")
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT department_id FROM departments WHERE department_name = %s", (dept_name,))
    dept_row = cursor.fetchone()
    dept_id = dept_row["department_id"] if dept_row else None
    cursor.execute("""
        SELECT student_id, student_name, attendance_pct, current_cgpa, risk_prediction
        FROM students WHERE department_id = %s ORDER BY student_name
    """, (dept_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Name", "Attendance %", "CGPA (/10)", "At Risk"])
    for r in rows:
        writer.writerow([r["student_id"], r["student_name"], r["attendance_pct"],
                          round((r["current_cgpa"] or 0) * 2.5, 2), "Yes" if r["risk_prediction"] else "No"])
    return Response(output.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment;filename={dept_name}_attendance_summary.csv"})


@app.route("/faculty/export/at_risk")
@login_required(roles=["faculty", "admin"])
def export_faculty_at_risk():
    dept_name = request.args.get("dept", "CSE")
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT department_id FROM departments WHERE department_name = %s", (dept_name,))
    dept_row = cursor.fetchone()
    dept_id = dept_row["department_id"] if dept_row else None
    cursor.execute("""
        SELECT student_id, student_name, attendance_pct, current_cgpa
        FROM students WHERE department_id = %s AND risk_prediction = 1 ORDER BY attendance_pct ASC
    """, (dept_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Name", "Attendance %", "CGPA (/10)"])
    for r in rows:
        writer.writerow([r["student_id"], r["student_name"], r["attendance_pct"], round((r["current_cgpa"] or 0) * 2.5, 2)])
    return Response(output.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment;filename={dept_name}_at_risk_report.csv"})


# ======================== ADMIN ========================

@app.route("/admin")
@login_required(roles=["admin"])
def admin_dashboard():
    page = max(1, request.args.get("page", 1, type=int))

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS total FROM students")
    total_students = cursor.fetchone()["total"]

    cursor.execute("SELECT AVG(current_cgpa) AS avg_cgpa, AVG(attendance_pct) AS avg_att FROM students")
    overall = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) AS total FROM departments")
    dept_count = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT d.department_name, AVG(s.current_cgpa) AS avg_cgpa,
               AVG(s.attendance_pct) AS avg_att, COUNT(*) AS total
        FROM students s
        JOIN departments d ON s.department_id = d.department_id
        GROUP BY d.department_name
        ORDER BY d.department_name
    """)
    dept_perf = cursor.fetchall()

    total_pages = max(1, (total_students + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    offset = (page - 1) * PAGE_SIZE

    cursor.execute("""
        SELECT s.student_id, s.student_name, d.department_name,
               s.attendance_pct, s.current_cgpa
        FROM students s
        JOIN departments d ON s.department_id = d.department_id
        ORDER BY s.student_name
        LIMIT %s OFFSET %s
    """, (PAGE_SIZE, offset))
    all_students = cursor.fetchall()

    cursor.execute("""
        SELECT f.faculty_name, d.department_name
        FROM faculty f
        JOIN departments d ON f.department_id = d.department_id
        ORDER BY d.department_name
    """)
    all_faculty = cursor.fetchall()

    cursor.execute("""
        SELECT engagement_level, COUNT(*) AS total
        FROM students
        WHERE engagement_level IS NOT NULL
        GROUP BY engagement_level
    """)
    engagement_counts = cursor.fetchall()

    cursor.close()
    conn.close()

    dept_cgpa10_list = [round((d["avg_cgpa"] or 0) * 2.5, 2) for d in dept_perf]
    for d in dept_perf:
        d["avg_att_rounded"] = round(d["avg_att"] or 0, 1)
        d["avg_cgpa10"] = round((d["avg_cgpa"] or 0) * 2.5, 2)
    for s in all_students:
        s["cgpa10"] = round((s["current_cgpa"] or 0) * 2.5, 2)

    reports = [
        ("All Students Report (CSV)", "/admin/export/students"),
        ("Department Summary (CSV)", "/admin/export/departments"),
    ]

    return render_template(
        "admin_dashboard.html",
        total_students=total_students, avg_cgpa10=round((overall["avg_cgpa"] or 0) * 2.5, 1),
        avg_attendance=round(overall["avg_att"] or 0, 1), dept_count=dept_count, dept_perf=dept_perf,
        dept_cgpa10_list=dept_cgpa10_list, all_students=all_students, all_faculty=all_faculty,
        engagement_counts=engagement_counts, reports=reports, page=page, total_pages=total_pages,
    )


@app.route("/admin/export/students")
@login_required(roles=["admin"])
def export_admin_students():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT s.student_id, s.student_name, d.department_name, s.attendance_pct,
               s.current_cgpa, s.risk_prediction, s.engagement_level
        FROM students s
        JOIN departments d ON s.department_id = d.department_id
        ORDER BY d.department_name, s.student_name
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student ID", "Name", "Department", "Attendance %", "CGPA (/10)", "At Risk", "Engagement"])
    for r in rows:
        writer.writerow([r["student_id"], r["student_name"], r["department_name"], r["attendance_pct"],
                          round((r["current_cgpa"] or 0) * 2.5, 2),
                          "Yes" if r["risk_prediction"] else "No", r["engagement_level"]])
    return Response(output.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": "attachment;filename=all_students_report.csv"})


@app.route("/admin/export/departments")
@login_required(roles=["admin"])
def export_admin_departments():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT d.department_name, COUNT(*) AS total, AVG(s.attendance_pct) AS avg_att, AVG(s.current_cgpa) AS avg_cgpa
        FROM students s
        JOIN departments d ON s.department_id = d.department_id
        GROUP BY d.department_name
        ORDER BY d.department_name
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Department", "Total Students", "Avg Attendance %", "Avg CGPA (/10)"])
    for r in rows:
        writer.writerow([r["department_name"], r["total"], round(r["avg_att"] or 0, 1), round((r["avg_cgpa"] or 0) * 2.5, 2)])
    return Response(output.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": "attachment;filename=department_summary.csv"})


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
