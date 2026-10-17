"""One place for the semester rules, so every page and script agrees.

An engineering programme has 8 semesters. The survey data contains impossible
values (up to 24), which are data-entry errors, so any value outside 1-8 is
clamped into that range.
"""
import random

MAX_SEMESTER = 8


def clamp_semester(value, default=1):
    """Return an int between 1 and 8, whatever the stored value is."""
    try:
        sem = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(sem, MAX_SEMESTER))


def build_sgpa_points(semester, previous_sgpa, seed_text):
    """Return [(label, sgpa_out_of_10), ...] for Sem 1 .. Sem <semester>.

    The last point is the student's real previous SGPA (converted from a 4.0 scale
    to /10). The earlier points are simulated, because the dataset holds only one
    SGPA value per student. The seed makes the same student always get the same
    chart.
    """
    semester = clamp_semester(semester)
    rng = random.Random(str(seed_text))
    end = round(min(10.0, max(0.0, float(previous_sgpa or 2.5) * 2.5)), 2)
    values = [round(min(10.0, max(0.0, end + rng.uniform(-1.0, 1.0))), 2) for _ in range(semester - 1)]
    values.append(end)
    return [(f"Sem {i}", v) for i, v in enumerate(values, start=1)]
