
from app.core.database import get_db_connection


def test_database_connection():
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), CURRENT_USER;")
            result = cursor.fetchone()

        print("PostgreSQL connection successful!")
        print(f"Database: {result[0]}")
        print(f"User: {result[1]}")

    except Exception as error:
        print("Database connection failed!")
        print(f"Error: {error}")

    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    test_database_connection()
