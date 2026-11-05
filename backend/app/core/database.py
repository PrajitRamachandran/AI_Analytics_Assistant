
import os

import psycopg
from dotenv import load_dotenv

# Load environment variables from the project root
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../")
)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def get_db_connection():
    """Create and return a PostgreSQL database connection."""

    connection = psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        connect_timeout=5,
    )

    return connection
