import os

# Checks if running on Render online
if os.environ.get('DB_HOST'):
    raw_host = os.environ.get('DB_HOST', '')
    # Safely splits the string and takes just the text before the colon
    clean_host = raw_host.split(':')[0]
    
    DB_CONFIG = {
        "host": clean_host,
        "port": int(os.environ.get('DB_PORT', 28293)),
        "user": os.environ.get('DB_USER'),
        "password": os.environ.get('DB_PASSWORD'),
        "database": os.environ.get('DB_NAME'),
        "ssl_disabled": False
    }
else:
    # This RESTORES your exact local setup for your PC completely
    DB_CONFIG = {
        "host": "localhost",
        "user": "root",
        "password": "root123",
        "database": "edumentor"
    }
