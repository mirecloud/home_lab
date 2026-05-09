import os
import psycopg2
from flask import Flask

app = Flask(__name__)

def get_db_credentials():
    """Reads secrets on the fly from the tmpfs mounted by the CSI Driver."""
    try:
        with open("/mnt/secrets/db-username", "r") as f:
            user = f.read().strip()
        with open("/mnt/secrets/db-password", "r") as f:
            password = f.read().strip()
        return user, password
    except Exception as e:
        return None, str(e)

@app.route("/")
def index():
    user, password_or_error = get_db_credentials()
    
    if not user:
        return f"<h1>CSI Error</h1><p>Failed to read /mnt/secrets: {password_or_error}</p>", 500

    try:
        # Connect to the actual MireCloud Postgres instance
        conn = psycopg2.connect(
            host="postgres.postgres.svc",
            database="postgres",
            user=user,
            password=password_or_error
        )
        cur = conn.cursor()
        
        # Ask Postgres to confirm our identity and connection details
        cur.execute("SELECT current_user, inet_server_addr(), current_timestamp;")
        db_user, db_ip, db_time = cur.fetchone()
        cur.close()
        conn.close()

        return f"""
        <body style='font-family: sans-serif; background: #121212; color: white; padding: 50px;'>
            <h1> MireCloud Secure App (Part 8)</h1>
            <p style='color: #4CAF50;'> Successfully connected to PostgreSQL!</p>
            <div style='background: #1e1e1e; padding: 20px; border-radius: 10px; border: 1px solid #333;'>
                <p><b>Dynamic Identity (Vault):</b> <code style='color: #ff9800;'>{db_user}</code></p>
                <p><b>DB Server IP:</b> {db_ip}</p>
                <p><b>DB Timestamp:</b> {db_time}</p>
            </div>
            <p style='color: gray; font-size: 0.8em; margin-top: 20px;'>
               (The password used for this request starts with: {password_or_error[:4]}***)
            </p>
        </body>
        """
    except Exception as e:
        return f"""
        <body style='font-family: sans-serif; background: #121212; color: white; padding: 50px;'>
            <h1 style='color: #f44336;'> Connection Failed</h1>
            <p>The application could not connect to PostgreSQL.</p>
            <div style='background: #2a0000; padding: 20px; border-radius: 10px; border: 1px solid #ff0000;'>
                <code>{e}</code>
            </div>
            <p style='color: gray; font-size: 0.8em; margin-top: 20px;'>
               If the Vault TTL just expired, the CSI driver might be in the middle of a rotation. Try refreshing.
            </p>
        </body>
        """, 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)