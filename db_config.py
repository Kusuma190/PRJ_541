import os

# This checks if the project is running online (Render) or locally on your PC
if os.environ.get('DB_HOST'):
    DB_CONFIG = {
        "host": str(os.environ.get('DB_HOST')),
        "port": int(os.environ.get('DB_PORT', 28293)),
        "user": str(os.environ.get('DB_USER')),
        "password": str(os.environ.get('DB_PASSWORD')),
        "database": str(os.environ.get('DB_NAME')),
        "ssl_disabled": False  # Enforces a secure cloud connection rules
    }
else:
    # This keeps your exact local host configuration working perfectly on your PC
    DB_CONFIG = {
        "host": "localhost",
        "user": "root",
        "password": "root123", 
        "database": "edumentor"
    }
