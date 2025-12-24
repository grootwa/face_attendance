# -*- coding: utf-8 -*-
#!/home/pi/acs/acsenv/bin/python

import cv2
import face_recognition
import base64
import numpy as np
import mysql.connector
from mysql.connector import Error
import config


def get_connection():
    return mysql.connector.connect(**config.DB_CONFIG)

def main():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Fetch employees who have image but missing encodings
        cursor.execute("""
            SELECT emp_id, image 
            FROM info 
            WHERE image IS NOT NULL 
              AND (encodings IS NULL OR encodings = '')
        """)

        rows = cursor.fetchall()
        print(f"Total rows fetched: {len(rows)}")

        for emp_id, image_data_url in rows:
            try:
                # Extract base64 from data:image URL
                if image_data_url.startswith("data:image"):
                    image_b64 = image_data_url.split(",")[1]
                else:
                    image_b64 = image_data_url

                # Decode base64 ? numpy array
                image_data = base64.b64decode(image_b64)
                image_array = np.frombuffer(image_data, dtype=np.uint8)
                img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

                if img is None:
                    print(f"Could not decode image for emp_id={emp_id}")
                    continue

                # Convert BGR ? RGB for face_recognition
                rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

                # Extract encodings
                enc = face_recognition.face_encodings(rgb_img)

                if enc:
                    encoding = enc[0]
                    encoding_str = base64.b64encode(encoding.tobytes()).decode("utf-8")

                    # Update MySQL record
                    cursor.execute("""
                        UPDATE info 
                        SET encodings = %s 
                        WHERE emp_id = %s
                    """, (encoding_str, emp_id))

                    print(f"Encoding saved for emp_id={emp_id}")

                else:
                    print(f"No face detected in image emp_id={emp_id}")

            except Exception as e:
                print(f"Error processing emp_id={emp_id}: {e}")

        # Commit updates
        conn.commit()
        print("All encodings updated successfully.")

    except Error as err:
        print(f"MySQL Error: {err}")

    finally:
        if 'conn' in locals():
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    main()
