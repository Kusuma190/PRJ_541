import os

# This checks if the project is running online (Render) or locally on your PC
if os.environ.get('DB_HOST'):
    DB_CONFIG = {
        "host": os.environ.get('DB_HOST'),
        "port": int(os.environ.get('DB_PORT', 28293)),
        "user": os.environ.get('DB_USER'),
        "password": os.environ.get('DB_PASSWORD'),
        "database": os.environ.get('DB_NAME'),
        "ssl_mode": "REQUIRED"
    }
else:
    # This falls back to your local PC parameters if you run it at home
    DB_CONFIG = {
        "host": "localhost",
        "user": "root",
        "password": "root123", 
        "database": "edumentor"
    }
