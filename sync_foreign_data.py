import requests
import mysql.connector
from datetime import datetime
import config

BASE_API_URL = "http://admin.jhc.vms/api/sync-all-controller-attendance"


def get_last_sync(cursor):
    cursor.execute("SELECT last_sync FROM sync_foreign_data ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    return row[0]


def update_last_sync(cursor):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE sync_foreign_data SET last_sync = %s WHERE id = 1", (current_time,))
    print(f"Updated last_sync to: {current_time}")


def insert_attendance(record, cursor):
    emp_id = record["empid"]
    name = record["employee_name"]
    status = record["status"]
    timestamp = record["time"]
    device_id = int(record["device_id"])

    sql = """
        INSERT IGNORE INTO attendance
        (emp_id, name, status, timestamp, device_id)
        VALUES (%s, %s, %s, %s, %s)
    """

    cursor.execute(sql, (emp_id, name, status, timestamp, device_id))
    print(f"Inserted: {emp_id} {status} at {timestamp} (or ignored if duplicate)")


def main():
    try:
        # DB connect
        db = mysql.connector.connect(
            host="localhost",
            user="acs_user",
            password="Secret4acs_user",
            database="face_attendance"
        )
        cursor = db.cursor()

        # 1) Get last sync time
        last_sync = get_last_sync(cursor)
        print("Last sync time:", last_sync)

        # 2) Hit API with last sync
        api_url = f"{BASE_API_URL}/{config.DEVICE_ID}/{last_sync}"
        response = requests.get(api_url, timeout=10)
        data = response.json()

        if not isinstance(data, list):
            print("API did not return a list. Aborting.")
            return

        # 3) Insert each attendance record
        for record in data:
            insert_attendance(record, cursor)

        # 4) Update last sync time
        update_last_sync(cursor)

        db.commit()
        cursor.close()
        db.close()

    except Exception as e:
        print("Error:", e)


if __name__ == "__main__":
    main()
