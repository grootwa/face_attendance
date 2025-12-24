# -*- coding: utf-8 -*-
#!/home/pi/acs/acsenv/bin/python

import requests
import json
import mysql.connector
import traceback
from datetime import datetime
import config

def get_connection():
    return mysql.connector.connect(**config.DB_CONFIG)

def get_last_synced(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_meta (
            id INT PRIMARY KEY,
            last_synced VARCHAR(255)
        )
    """)
    cursor.execute("SELECT last_synced FROM sync_meta WHERE id = 1")
    row = cursor.fetchone()
    if row and row[0]:
        return row[0]
    else:
        return "1970-01-01 00:00:00"

def update_last_synced(cursor, timestamp):
    cursor.execute("""
        INSERT INTO sync_meta (id, last_synced)
        VALUES (1, %s)
        ON DUPLICATE KEY UPDATE last_synced = VALUES(last_synced)
    """, (timestamp,))

def main():
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # 1. Get last synced time
        last_synced = get_last_synced(cursor)
        print(f"Last synced: {last_synced}")

        # 2. Current API hit time
        hit_time = datetime.now().replace(second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        print(f"API hit time: {hit_time}")

        # 3. Build API URL
        api_url = f"http://admin.jhc.vms/api/sync-employees-for-attendance/75/{last_synced}"
        print(f"Hitting API: {api_url}")

        response = requests.get(api_url, verify=False, timeout=15)
        if response.status_code != 200:
            print(f"API failed with status {response.status_code}")
            return

        data = response.json()
        print("Sync started...")

        # ======================================================
        # INSERT / UPDATE LOGIC (Variable Images 1-10)
        # ======================================================
        users_processed = 0
        total_photos_inserted = 0

        # Define all possible keys the API might send
        # It checks 'image', then 'img1' through 'img9'
        possible_keys = ['image'] + [f'img{i}' for i in range(1, 10)]

        for item in data.get("to_add", []):
            try:
                emp_id = item.get("empid")
                empno = item.get("empno")
                name = item.get("employee_name")
                designation = item.get("designation")

                # Step A: Collect all valid images for this specific user
                valid_images = []
                for key in possible_keys:
                    img_data = item.get(key)
                    # Check if image data exists and is not just an empty string
                    if img_data and len(str(img_data)) > 50:
                        valid_images.append(img_data)

                # If no images found at all, skip this user
                if not valid_images:
                    continue

                # Step B: DELETE existing rows for this user
                # We wipe the slate clean for this ID so we don't have duplicates
                cursor.execute("DELETE FROM info WHERE emp_id = %s", (emp_id,))

                # Step C: INSERT a new row for EACH image found
                for img_blob in valid_images:
                    cursor.execute("""
                        INSERT INTO info (emp_id, empno, name, designation, image, created_on, encodings)
                        VALUES (%s, %s, %s, %s, %s, NOW(), NULL)
                    """, (emp_id, empno, name, designation, img_blob))
                    total_photos_inserted += 1
                
                users_processed += 1

            except Exception as e:
                print(f"Skipping user {item.get('employee_name', 'Unknown')}: {e}")

        if users_processed > 0:
            print(f"Processed {users_processed} users. Total {total_photos_inserted} photos inserted.")
        else:
            print("No new/updated records found.")

        # ======================================================
        # DELETE LOGIC
        # ======================================================
        deleted_count = 0
        for item in data.get("to_delete", []):
            emp_id = item.get("emp_id")
            if emp_id:
                cursor.execute("DELETE FROM info WHERE emp_id = %s", (emp_id,))
                deleted_count += cursor.rowcount

        print(f"{deleted_count} record(s) deleted.")

        # Save last sync time
        update_last_synced(cursor, hit_time)

        conn.commit()
        print(f"Sync completed successfully at {hit_time}")

    except Exception as e:
        print("Fatal Error:", e)
        traceback.print_exc()

    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()
            print("DB connection closed.")

if __name__ == "__main__":
    main()