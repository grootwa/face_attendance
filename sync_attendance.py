#!/home/pi/acs/acsenv/bin/python
import mysql.connector
from mysql.connector import Error
import json
import requests
from datetime import datetime, timedelta
import config

api_url = "http://admin.jhc.vms/api/sync-attendance-log"


def get_conn():
    return mysql.connector.connect(**config.DB_CONFIG)


current_time = datetime.now()
cutoff_timestamp = (current_time - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
current_formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")


def ensure_sync_table(cursor, conn):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_controller_db (
            device_id INT PRIMARY KEY,
            up_date_time DATETIME
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM sync_controller_db WHERE device_id = 1")
    count = cursor.fetchone()[0]

    if count == 0:
        cursor.execute("""
            INSERT INTO sync_controller_db (device_id, up_date_time)
            VALUES (1, %s)
        """, ("1970-01-01 00:00:00",))
        conn.commit()


def main():
    try:
        conn = get_conn()
        cursor = conn.cursor()

        ensure_sync_table(cursor, conn)

        cursor.execute("SELECT up_date_time FROM sync_controller_db WHERE device_id = 1")
        row = cursor.fetchone()
        last_synced = row[0] if row and row[0] else "1970-01-01 00:00:00"

        print(f"Last synced at: {last_synced}")

        cursor.execute("""
            SELECT emp_id, name, status, timestamp
            FROM attendance
            WHERE timestamp > %s and device_id = %s
            ORDER BY timestamp ASC
        """, (last_synced,config.DEVICE_ID))

        records = cursor.fetchall()

        if not records:
            print("No new attendance records to sync.")
            conn.close()
            return

        data_list = []
        for row in records:
            emp_id, name, status, timestamp = row
            data_list.append({
                "emp_id": emp_id,
                "name": name,
                "status": status,
                "time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "device_id": config.DEVICE_ID
            })

        try:
            response = requests.post(api_url, verify=False, json=data_list)

            if response.status_code == 200:
                last_record_time = records[-1][3].strftime("%Y-%m-%d %H:%M:%S")

                cursor.execute("""
                    UPDATE sync_controller_db
                    SET up_date_time = %s
                    WHERE device_id = 1
                """, (last_record_time,))

                cursor.execute("""
                    DELETE FROM attendance
                    WHERE timestamp < %s
                """, (cutoff_timestamp,))

                conn.commit()

                print(f"{len(records)} record(s) synced successfully.")
                print(f"Last sync time updated to: {last_record_time}")

            else:
                print(f"Server returned {response.status_code}: {response.text}")

        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")

    except Error as db_err:
        print(f"MySQL error: {db_err}")

    finally:
        if 'conn' in locals():
            conn.close()
            print("Database connection closed.")


if __name__ == "__main__":
    main()
