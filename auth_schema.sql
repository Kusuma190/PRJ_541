USE edumentor;

CREATE TABLE IF NOT EXISTS users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('student', 'faculty', 'admin') NOT NULL,
    student_id VARCHAR(10) NULL,
    FOREIGN KEY (student_id) REFERENCES students(student_id)
);

-- Demo accounts for Faculty and Admin roles (change these passwords after testing!)
-- We insert placeholder hashes here and set real ones via create_demo_accounts.py
