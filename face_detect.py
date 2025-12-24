import logging
logging.getLogger("picamera2").setLevel(logging.WARNING)
logging.getLogger("libcamera").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.ERROR)
logging.getLogger().setLevel(logging.WARNING)

import subprocess
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.core.window import Window

import numpy as np
import cv2
import base64
import face_recognition
import dlib
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from scipy.spatial import distance as dist
import config

# ---------------- Config ----------------
b_dir = "/home/pi/face_attendance/"



def get_conn():
    return mysql.connector.connect(**config.DB_CONFIG)

subprocess.run(["wlr-randr", "--output", "DSI-1", "--on"])

Window.fullscreen = True
Window.show_cursor = False
Window.size = (460, 720)
Window.clearcolor = (0.93, 0.95, 1, 1)


# ---------------- Database Utilities ----------------
def create_attendance_table():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INT PRIMARY KEY AUTO_INCREMENT,
            emp_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL,
            timestamp DATETIME NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_face_data_from_db():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT emp_id, name, designation, encodings FROM info")
    rows = cursor.fetchall()
    conn.close()

    emp_ids, names, designations, encodings = [], [], [], []

    for emp_id, name, desig, enc_b64 in rows:
        try:
            if not enc_b64:
                continue

            arr_bytes = base64.b64decode(enc_b64)
            face_encoding = np.frombuffer(arr_bytes, dtype=np.float64)

            if face_encoding.size != 128:
                face_encoding = np.frombuffer(arr_bytes, dtype=np.float32)

            if face_encoding.size == 128:
                emp_ids.append(emp_id)
                names.append(name)
                designations.append(desig)
                encodings.append(face_encoding)

        except Exception as e:
            print(f"[ERROR] Could not process {name}: {e}")

    return emp_ids, names, designations, encodings


def get_latest_record(emp_id):
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, emp_id, name, status, timestamp
        FROM attendance
        WHERE emp_id = %s
          AND DATE(timestamp) = %s
        ORDER BY id DESC
        LIMIT 1
    """, (emp_id, today))

    record = cursor.fetchone()
    conn.close()
    return record


def record_attendance(emp_id, name):
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    record = get_latest_record(emp_id)
    last_status = record[3] if record else None

    new_status = "out" if last_status == "in" else "in"

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO attendance (emp_id, name, status, timestamp, device_id)
        VALUES (%s, %s, %s, %s, %s)
    """, (emp_id, name, new_status, timestamp, config.DEVICE_ID))

    conn.commit()
    conn.close()

    msg = f"Attendance Marked Successfully \n{timestamp}"
    color = (0, 0.6, 1, 1) if new_status == "out" else (0, 0.8, 0, 1)
    return msg, color, new_status


# ---------------- Blink Logic ----------------
def eye_aspect_ratio(eye):
    A = dist.euclidean(eye[1], eye[5])
    B = dist.euclidean(eye[2], eye[4])
    C = dist.euclidean(eye[0], eye[3])
    return (A + B) / (2.0 * C)


# ---------------- Camera Manager ----------------
class CameraManager:
    def __init__(self):
        self.using_picam2 = False
        try:
            from picamera2 import Picamera2
            self.picam2 = Picamera2()
            self.picam2.preview_configuration.main.size = (400, 400)
            self.picam2.preview_configuration.main.format = "RGB888"
            self.picam2.configure("preview")
            self.picam2.start()
            self.using_picam2 = True
            print("[INFO] Using Picamera2")
        except Exception as e:
            print(f"[WARN] Picamera2 not available, using default camera. ({e})")
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    def get_frame(self):
        if self.using_picam2:
            return self.picam2.capture_array()
        else:
            ret, frame = self.cap.read()
            return frame if ret else np.zeros((240, 320, 3), dtype=np.uint8)

    def release(self):
        if self.using_picam2:
            self.picam2.stop()
        else:
            self.cap.release()


# ---------------- Main App ----------------
class DetectApp(App):
    VERIFIED_DISPLAY_TIME = 5

    def build(self):
        create_attendance_table()
        self.emp_ids, self.names, self.designations, self.encodings = get_face_data_from_db()
        print(f"[INFO] Loaded {len(self.emp_ids)} employees from database.")

        self.camera = CameraManager()
        self.predictor = dlib.shape_predictor(b_dir+"shape_predictor_68_face_landmarks.dat")
        self.detector = dlib.get_frontal_face_detector()

        self.EYE_AR_THRESH = 0.22
        self.blinked = False
        self.current_emp = None
        self.last_detect_time = None

        layout = BoxLayout(orientation='vertical', padding=0, spacing=1)

        header = Label(
            text="[b]Attendance Management System[/b]",
            markup=True,
            size_hint=(1, 0.08),
            font_size=28,
            bold=True,
            color=(0.1, 0.1, 0.1, 1)
        )
        layout.add_widget(header)

        self.img_widget = Image(size_hint=(1, 0.55))
        layout.add_widget(self.img_widget)
        layout.add_widget(Widget(size_hint_y=None, height=10))

        # Info grid
        self.info_grid = GridLayout(cols=2, spacing=[5,0], size_hint=(1, 1))
        self.info_labels = {
            "ID": Label(text="", color=(0.1,0.1,0.1,1), font_size=24, halign='left', valign='middle'),
            "Name": Label(text="", color=(0.1,0.1,0.1,1), font_size=24, halign='left', valign='middle'),
            "Designation": Label(text="", color=(0.1,0.1,0.1,1), font_size=24, halign='left', valign='middle')
        }
        for label in self.info_labels.values():
            label.bind(size=label.setter('text_size'))

        for key, label in self.info_labels.items():
            key_label = Label(
                text=f"[b]{key}:[/b]",
                markup=True,
                color=(0,0,0,1),
                font_size=24,
                halign='left',
                valign='middle'
            )
            key_label.bind(size=key_label.setter('text_size'))
            self.info_grid.add_widget(key_label)
            self.info_grid.add_widget(label)

        self.info_card = BoxLayout(
            orientation='vertical',
            padding=[10,10,10,10],
            spacing=.5,
            size_hint=(None, 0.8),
            width=420
        )
        with self.info_card.canvas.before:
            Color(1,1,1,1)
            self.card_bg = RoundedRectangle(radius=[15], pos=self.info_card.pos, size=self.info_card.size)
        with self.info_card.canvas.after:
            Color(0.3,0.3,0.3,1)
            self.card_border = Line(
                rounded_rectangle=[self.info_card.x, self.info_card.y, self.info_card.width, self.info_card.height, 15],
                width=1.2
            )
        self.info_card.bind(pos=self.update_card, size=self.update_card)
        self.info_card.add_widget(self.info_grid)

        info_wrapper = BoxLayout(orientation='horizontal', size_hint=(1, 0.3))
        info_wrapper.add_widget(Widget())
        info_wrapper.add_widget(self.info_card)
        info_wrapper.add_widget(Widget())
        layout.add_widget(info_wrapper)

        self.action_button = Button(
            text="", size_hint=(1,0.1), opacity=0,
            background_color=(0,0.8,0,1), font_size=22, bold=True
        )
        self.action_button.bind(on_press=self.handle_punch)
        layout.add_widget(self.action_button)

        # schedule frame updates and periodic face-data refresh
        Clock.schedule_interval(self.update_frame, 1/15)
        Clock.schedule_interval(self.refresh_face_data, 300)  # every 5 minutes

        return layout

    def refresh_face_data(self, dt):
        try:
            new_emp_ids, new_names, new_designations, new_encodings = get_face_data_from_db()
            self.emp_ids = new_emp_ids
            self.names = new_names
            self.designations = new_designations
            self.encodings = new_encodings
            print(f"[INFO] Refreshed face data: {len(self.emp_ids)} employees loaded.")
        except Exception as e:
            print(f"[ERROR] Failed to refresh face data: {e}")

    def update_card(self, *args):
        self.card_bg.pos = self.info_card.pos
        self.card_bg.size = self.info_card.size
        self.card_border.rounded_rectangle = [
            self.info_card.x, self.info_card.y, self.info_card.width, self.info_card.height, 15
        ]

    def update_frame(self, dt):
        frame = self.camera.get_frame()
        if frame is None or frame.size == 0:
            return

        frame_small = cv2.resize(frame, (200, 200))
        frame_display = cv2.resize(frame_small, (400, 400))

        gray = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)
        rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
        
        # ---------- Display frame ----------
        #frame_display = cv2.resize(frame, (400, 400))

        # ---------- Use full frame for recognition ----------
        #gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        #rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


        rects = self.detector(gray, 0)
        recognized_name, emp_id = None, None
        DETECTION_TIMEOUT = 3

        for rect in rects:
            x, y, w, h = rect.left(), rect.top(), rect.width(), rect.height()
            shape = self.predictor(rgb, rect)
            shape_np = np.array([[shape.part(i).x, shape.part(i).y] for i in range(68)])
            leftEye, rightEye = shape_np[42:48], shape_np[36:42]

            ear = (eye_aspect_ratio(leftEye) + eye_aspect_ratio(rightEye)) / 2.0

            if ear < self.EYE_AR_THRESH and not self.blinked:
                self.blinked = True
            elif ear >= self.EYE_AR_THRESH:
                self.blinked = False

            if not self.blinked:
                continue

            face_locations = [(y, x + w, y + h, x)]
            encodings = face_recognition.face_encodings(rgb, face_locations)

            if encodings:
                face_encoding = encodings[0]
                if self.encodings:
                    distances = np.linalg.norm(np.array(self.encodings) - face_encoding, axis=1)
                    idx = np.argmin(distances)
                    if distances[idx] < 0.38:
                        recognized_name = self.names[idx]
                        emp_id = self.emp_ids[idx]
                    else:
                        recognized_name = "Unknown"
                self.blinked = False

        now = datetime.now()

        if recognized_name is not None:
            self.last_detect_time = now
            if recognized_name != "Unknown":
                if self.current_emp is None or self.current_emp[0] != emp_id:
                    self.show_person_info(emp_id, recognized_name)
            else:
                self.current_emp = None
                for k in self.info_labels:
                    self.info_labels[k].text = "Unknown"
                    self.info_labels[k].color = (1, 0, 0, 1)
                self.action_button.opacity = 0
        else:
            if self.last_detect_time and (now - self.last_detect_time).total_seconds() > DETECTION_TIMEOUT:
                self.reset_view()

        frame_display = cv2.cvtColor(frame_display, cv2.COLOR_BGR2RGB)
        buf = cv2.flip(frame_display, -1).tobytes()
        texture = Texture.create(size=(frame_display.shape[1], frame_display.shape[0]), colorfmt='rgb')
        texture.blit_buffer(buf, colorfmt='rgb', bufferfmt='ubyte')
        self.img_widget.texture = texture

    def show_person_info(self, emp_id, name):
        record = get_latest_record(emp_id)
        self.current_emp = (emp_id, name)
        idx = self.emp_ids.index(emp_id)
        self.info_labels["ID"].text = str(emp_id)
        self.info_labels["ID"].color = ((0.0, 0.2, 0.6, 1))
        self.info_labels["Name"].text = name
        self.info_labels["Name"].color = ((0.0, 0.2, 0.6, 1))
        self.info_labels["Designation"].text = self.designations[idx]
        self.info_labels["Designation"].color = ((0.0, 0.2, 0.6, 1))

        if record and record[3] == "in":
            self.action_button.text = "Punch Out"
            self.action_button.background_color = (0.8, 0, 0, 1)
            self.action_button.punch_type = "out"
        else:
            self.action_button.text = "Punch In"
            self.action_button.background_color = (0, 0.8, 0, 1)
            self.action_button.punch_type = "in"

        self.action_button.opacity = 1

    def handle_punch(self, instance):
        if not self.current_emp:
            return
        emp_id, name = self.current_emp
        msg, color, new_status = record_attendance(emp_id, name)
        self.show_verified_screen(msg, color)

    def show_verified_screen(self, msg, color):
        self.info_card.clear_widgets()
        self.action_button.opacity = 0

        verified_layout = BoxLayout(orientation='vertical', spacing=5, padding=10)
        face_img = Image(source=b_dir+"verified.png", size_hint=(1,1))
        verified_layout.add_widget(face_img)

        label = Label(
            text=f"[b]{msg}[/b]",
            markup=True,
            color=color,
            font_size=20,
            halign="center",
            valign="middle"
        )
        label.bind(size=label.setter('text_size'))
        verified_layout.add_widget(label)

        self.info_card.add_widget(verified_layout)
        Clock.schedule_once(lambda dt: self.reset_view(), self.VERIFIED_DISPLAY_TIME)

    def reset_view(self):
        for key in self.info_labels:
            self.info_labels[key].text = ""
        self.current_emp = None
        self.action_button.opacity = 0
        self.info_card.clear_widgets()
        self.info_card.add_widget(self.info_grid)

    def on_stop(self):
        self.camera.release()


if __name__ == "__main__":
    DetectApp().run()
