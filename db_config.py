import os

# This checks if the project is running online (Render) or locally on your PC
if os.environ.get('DB_HOST'):
    # Clean the host string in case Render passes the port inside it
    raw_host = os.environ.get('DB_HOST', '')
    clean_host = raw_host.split(':')[0] # This chops off any trailing port numbers
    
    DB_CONFIG = {
        "host": clean_host,
        "port": int(os.environ.get('DB_PORT', 28293)),
        "user": os.environ.get('DB_USER'),
        "password": os.environ.get('DB_PASSWORD'),
        "database": os.environ.get('DB_NAME'),
        "ssl_disabled": False  # Enforces a secure SSL connection on Aiven
    }
else:
    # This falls back to your local PC parameters if you run it at home
    DB_CONFIG = {
        "host": "localhost",
        "user": "root",
        "password": "root123", 
        "database": "edumentor"
    }
