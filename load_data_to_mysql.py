import pandas as pd
import random
import mysql.connector

# ---------- CONFIG: change these to match your MySQL setup ----------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root123",   # <-- change this
    "database": "edumentor",
}
EXCEL_PATH = r"Students_Performance_data_set.xlsx"  # adjust path if needed
# ----------------------------------------------------------------------

random.seed(42)

# ============ 1. LOAD AND CLEAN THE REAL DATASET ============

df = pd.read_excel(EXCEL_PATH)

df["What is your current CGPA?"] = pd.to_numeric(
    df["What is your current CGPA?"], errors="coerce"
)

def clean_attendance(val):
    if isinstance(val, str) and "-" in val:
        low, high = val.split("-")
        return (float(low) + float(high)) / 2
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

df["Average attendance on class"] = df["Average attendance on class"].apply(clean_attendance)
df["What was your previous SGPA?"] = pd.to_numeric(
    df["What was your previous SGPA?"], errors="coerce"
)

df = df.dropna(subset=[
    "What is your current CGPA?",
    "Average attendance on class",
    "What was your previous SGPA?",
])

df["at_risk"] = (
    (df["Did you ever fall in probation?"] == "Yes") |
    (df["What is your current CGPA?"] < 2.5) |
    (df["Average attendance on class"] < 75)
).astype(int)

df = df.reset_index(drop=True)
df["student_id"] = ["S" + str(1000 + i) for i in range(len(df))]

first_names = ["Aarav", "Vivaan", "Aditya", "Ananya", "Diya", "Ishaan", "Kavya", "Rohan", "Sara", "Meera"]
last_names = ["Sharma", "Verma", "Iyer", "Reddy", "Nair", "Gupta", "Rao", "Menon", "Das", "Khan"]
df["student_name"] = [random.choice(first_names) + " " + random.choice(last_names) for _ in range(len(df))]

print(f"Loaded and cleaned {len(df)} student records.")

# ============ 2. CONNECT TO MYSQL ============

conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

# ============ 3. SYNTHETIC DEPARTMENTS, FACULTY, COURSES ============

department_names = ["CSE", "ECE", "ME", "EEE", "IT", "CIVIL"]
department_ids = {}
for name in department_names:
    cursor.execute("INSERT INTO departments (department_name) VALUES (%s)", (name,))
    department_ids[name] = cursor.lastrowid

faculty_ids = {}  # department_name -> list of faculty_ids
for name in department_names:
    faculty_ids[name] = []
    for fname in random.sample(first_names, 3):
        full_name = "Dr. " + fname + " " + random.choice(last_names)
        cursor.execute(
            "INSERT INTO faculty (faculty_name, department_id) VALUES (%s, %s)",
            (full_name, department_ids[name])
        )
        faculty_ids[name].append(cursor.lastrowid)

course_ids = {}  # department_name -> list of course_ids
course_templates = ["Data Structures", "Database Systems", "Operating Systems", "Machine Learning"]
for name in department_names:
    course_ids[name] = []
    for course_name in course_templates:
        full_course_name = f"{course_name} ({name})"
        assigned_faculty = random.choice(faculty_ids[name])
        cursor.execute(
            "INSERT INTO courses (course_name, department_id, faculty_id) VALUES (%s, %s, %s)",
            (full_course_name, department_ids[name], assigned_faculty)
        )
        course_ids[name].append(cursor.lastrowid)

conn.commit()
print("Departments, faculty, and courses created.")

# ============ 4. INSERT STUDENTS (real data + synthetic department) ============

student_rows = []
for _, row in df.iterrows():
    dept_name = random.choice(department_names)
    student_rows.append((
        row["student_id"],
        row["student_name"],
        department_ids[dept_name],
        int(row["Admission Year"]) if "Admission Year" in df.columns and pd.notna(row.get("Admission Year")) else None,
        str(row.get("Gender", "")),
        int(row["Age"]) if "Age" in df.columns and pd.notna(row.get("Age")) else None,
        int(row["Current Semester"]) if pd.notna(row["Current Semester"]) else None,
        float(row["What was your previous SGPA?"]),
        float(row["What is your current CGPA?"]),
        float(row["Average attendance on class"]),
        float(row["How many hour do you study daily?"]) if pd.notna(row.get("How many hour do you study daily?")) else None,
        float(row["How many hour do you spent daily in social media?"]) if pd.notna(row.get("How many hour do you spent daily in social media?")) else None,
        float(row["How many Credit did you have completed?"]) if pd.notna(row.get("How many Credit did you have completed?")) else None,
        str(row["Did you ever fall in probation?"]),
        str(row["Did you ever got suspension?"]),
        int(row["at_risk"]),
        None,  # risk_prediction filled in later by the ML script
    ))
    # remember department assigned, needed for course_attendance step below
    df.loc[df["student_id"] == row["student_id"], "assigned_dept"] = dept_name

insert_student_sql = """
INSERT INTO students (
    student_id, student_name, department_id, admission_year, gender, age,
    current_semester, previous_sgpa, current_cgpa, attendance_pct,
    study_hours, social_media_hours, credits_completed,
    probation, suspension, at_risk, risk_prediction
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""
cursor.executemany(insert_student_sql, student_rows)
conn.commit()
print(f"Inserted {len(student_rows)} students.")

# ============ 5. SYNTHETIC PER-COURSE ATTENDANCE ============

course_attendance_rows = []
for _, row in df.iterrows():
    dept_name = row["assigned_dept"]
    base_attendance = row["Average attendance on class"]
    dept_courses = course_ids[dept_name]
    remaining = base_attendance * len(dept_courses)
    for i, cid in enumerate(dept_courses):
        if i == len(dept_courses) - 1:
            val = remaining
        else:
            val = base_attendance + random.uniform(-8, 8)
            val = max(40, min(100, val))
            remaining -= val
        course_attendance_rows.append((row["student_id"], cid, round(val, 1)))

cursor.executemany(
    "INSERT INTO course_attendance (student_id, course_id, attendance_pct) VALUES (%s, %s, %s)",
    course_attendance_rows
)
conn.commit()
print(f"Inserted {len(course_attendance_rows)} course attendance records.")

# ============ 6. SYNTHETIC SGPA HISTORY ============

sgpa_rows = []
semester_labels = ["Sem -3", "Sem -2", "Sem -1", "Current"]
for _, row in df.iterrows():
    current_sgpa_10 = round(row["What was your previous SGPA?"] * 2.5, 2)
    trend = [round(max(0, min(10, current_sgpa_10 + random.uniform(-1.2, 1.2))), 2) for _ in range(3)]
    trend.append(current_sgpa_10)
    for label, val in zip(semester_labels, trend):
        sgpa_rows.append((row["student_id"], label, val))

cursor.executemany(
    "INSERT INTO sgpa_history (student_id, semester_label, sgpa) VALUES (%s, %s, %s)",
    sgpa_rows
)
conn.commit()
print(f"Inserted {len(sgpa_rows)} SGPA history records.")

cursor.close()
conn.close()
print("Done. All data loaded into MySQL database 'edumentor'.")
