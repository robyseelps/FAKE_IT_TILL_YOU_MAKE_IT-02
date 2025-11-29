import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

# Fetch variables
USER = os.getenv("user")
PASSWORD = os.getenv("password")
HOST = os.getenv("host")
PORT = os.getenv("port")
DBNAME = os.getenv("dbname")


def get_connection():
    """Return a new psycopg2 connection using env settings."""
    return psycopg2.connect(
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT,
        dbname=DBNAME,
        cursor_factory=RealDictCursor,
    )

# Optional quick-connect demo
if __name__ == "__main__":
    try:
        with get_connection() as connection:
            print("Connection successful!")
            with connection.cursor() as cursor:
                cursor.execute("SELECT NOW() AS now;")
                result = cursor.fetchone()
                print("Current Time:", result["now"])
        print("Connection closed.")
    except Exception as e:
        print(f"Failed to connect: {e}")
