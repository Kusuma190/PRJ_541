import random
import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root123",   # <-- change this
    "database": "edumentor",
}

random.seed(42)

conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor(dictionary=True)

# Clear out the old relative-labeled history
cursor.execute("DELETE FROM sgpa_history")
conn.commit()
print("Cleared old SGPA history.")

cursor.execute("SELECT student_id, current_semester, previous_sgpa FROM students")
students = cursor.fetchall()

rows_to_insert = []
for s in students:
    current_sem = s["current_semester"] or 1
    # Engineering programs run 8 semesters - clamp anything beyond that
    # (a few rows report 22-24, clearly data entry errors in the survey)
    current_sem = max(1, min(current_sem, 8))

    end_value = round((s["previous_sgpa"] or 2.5) * 2.5, 2)  # real value, converted to /10
    end_value = max(0, min(10, end_value))

    # Always start from Semester 1 through the student's current semester
    trend = [round(max(0, min(10, end_value + random.uniform(-1.0, 1.0))), 2) for _ in range(current_sem - 1)]
    trend.append(end_value)

    for sem_num, sgpa_val in zip(range(1, current_sem + 1), trend):
        label = f"Sem {sem_num}"
        rows_to_insert.append((s["student_id"], label, sgpa_val))

cursor.executemany(
    "INSERT INTO sgpa_history (student_id, semester_label, sgpa) VALUES (%s, %s, %s)",
    rows_to_insert
)
conn.commit()
print(f"Inserted {len(rows_to_insert)} new SGPA history rows with real semester numbers.")

cursor.close()
conn.close()
