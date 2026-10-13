import os

# This checks if the project is running online (Render) or locally on your PC
if os.environ.get('DB_HOST'):
    raw_host = os.environ.get('DB_HOST', '')
    # Safely extract the string text before the colon symbol
    clean_host = raw_host.split(':')[0]
    
    DB_CONFIG = {
        "host": clean_host,
        "port": int(os.environ.get('DB_PORT', 28293)),
        "user": os.environ.get('DB_USER'),
        "password": os.environ.get('DB_PASSWORD'),
        "database": os.environ.get('DB_NAME'),
        "ssl_disabled": False  # Enforces a secure SSL connection on Aiven
    }
else:
    # This keeps your exact local host configuration working perfectly on your PC
    DB_CONFIG = {
        "host": "localhost",
        "user": "root",
        "password": "root123", 
        "database": "edumentor"
    }
