# Central place for database credentials.
# Every script (app.py, train_models.py, load_data_to_mysql.py,
# regenerate_sgpa_history.py) imports DB_CONFIG from here instead of
# defining its own copy. Change the password in ONE place only.
#
# If you ever push this project to GitHub, add "db_config.py" to a
# .gitignore file so your password doesn't get uploaded.

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root123",   # <-- change this once, here only
    "database": "edumentor",
}
