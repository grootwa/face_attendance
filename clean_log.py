# -*- coding: utf-8 -*-
import os

# List of files to trim
LOG_FILES = [
    "/home/pi/face_attendance/logs/generate_embeddings.log",
    "/home/pi/face_attendance/logs/sync_attendance.log",
    "/home/pi/face_attendance/logs/sync_emp_data.log",
    "/home/pi/face_attendance/logs/sync_foreign_data.log"
]

MAX_SIZE_KB = 100
MAX_SIZE_BYTES = MAX_SIZE_KB * 1024

def trim_file(file_path):
    try:
        file_size = os.path.getsize(file_path)

        if file_size <= MAX_SIZE_BYTES:
            print(f"{file_path}: Already under {MAX_SIZE_KB} KB.")
            return

        with open(file_path, 'rb') as f:
            f.seek(-MAX_SIZE_BYTES, os.SEEK_END)
            data = f.read()

        # Trim to next newline to avoid broken first line
        first_newline = data.find(b'\n')
        if first_newline != -1:
            data = data[first_newline + 1:]

        with open(file_path, 'wb') as f:
            f.write(data)

        print(f"{file_path}: Trimmed to last {MAX_SIZE_KB} KB.")
    except Exception as e:
        print(f"{file_path}: Failed to trim - {e}")


def main():
    for log_file in LOG_FILES:
        if os.path.isfile(log_file):
            trim_file(log_file)
        else:
            print(f"{log_file}: File not found.")

if __name__ == "__main__":
    main()
