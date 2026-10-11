CREATE DATABASE IF NOT EXISTS edumentor;
USE edumentor;

CREATE TABLE departments (
    department_id INT AUTO_INCREMENT PRIMARY KEY,
    department_name VARCHAR(50) NOT NULL
);

CREATE TABLE faculty (
    faculty_id INT AUTO_INCREMENT PRIMARY KEY,
    faculty_name VARCHAR(100) NOT NULL,
    department_id INT,
    FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE courses (
    course_id INT AUTO_INCREMENT PRIMARY KEY,
    course_name VARCHAR(100) NOT NULL,
    department_id INT,
    faculty_id INT,
    FOREIGN KEY (department_id) REFERENCES departments(department_id),
    FOREIGN KEY (faculty_id) REFERENCES faculty(faculty_id)
);

CREATE TABLE students (
    student_id VARCHAR(10) PRIMARY KEY,
    student_name VARCHAR(100),
    department_id INT,
    admission_year INT,
    gender VARCHAR(10),
    age INT,
    current_semester INT,
    previous_sgpa FLOAT,
    current_cgpa FLOAT,
    attendance_pct FLOAT,
    study_hours FLOAT,
    social_media_hours FLOAT,
    credits_completed FLOAT,
    probation VARCHAR(5),
    suspension VARCHAR(5),
    at_risk INT,
    risk_prediction INT,
    FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE course_attendance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(10),
    course_id INT,
    attendance_pct FLOAT,
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    FOREIGN KEY (course_id) REFERENCES courses(course_id)
);

CREATE TABLE sgpa_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(10),
    semester_label VARCHAR(20),
    sgpa FLOAT,
    FOREIGN KEY (student_id) REFERENCES students(student_id)
);
