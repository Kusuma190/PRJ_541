-- Engineering has 8 semesters. Fix the stored data so the database itself is correct.
-- Run this once against the database your website uses (Aiven).

-- 1) Cap impossible semester values (the survey data has values up to 24)
UPDATE students SET current_semester = 8 WHERE current_semester > 8;
UPDATE students SET current_semester = 1 WHERE current_semester < 1 OR current_semester IS NULL;

-- 2) Remove trend rows for semesters that do not exist (Sem 9, Sem 10 ... or the old "Sem -3" style)
DELETE FROM sgpa_history
 WHERE semester_label REGEXP '^Sem -?[0-9]+$'
   AND (CAST(SUBSTRING(semester_label, 5) AS SIGNED) < 1
        OR CAST(SUBSTRING(semester_label, 5) AS SIGNED) > 8);

-- 3) Check: both numbers below must be 0
SELECT COUNT(*) AS students_outside_1_to_8
  FROM students WHERE current_semester < 1 OR current_semester > 8;
SELECT COUNT(*) AS history_rows_outside_1_to_8
  FROM sgpa_history
 WHERE semester_label REGEXP '^Sem -?[0-9]+$'
   AND (CAST(SUBSTRING(semester_label, 5) AS SIGNED) < 1
        OR CAST(SUBSTRING(semester_label, 5) AS SIGNED) > 8);
