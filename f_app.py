# -*- coding: utf-8 -*-
import logging
import cv2
import time
import threading
import numpy as np
import base64
import face_recognition
import dlib
import mysql.connector
from scipy.spatial import distance as dist
from datetime import datetime
from flask import Flask, render_template, Response, jsonify, request
import mediapipe as mp
import config 

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.WARNING)
logging.getLogger("picamera2").setLevel(logging.ERROR)
logging.getLogger("libcamera").setLevel(logging.ERROR)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__)

# ==========================================
# 1. DATABASE MANAGER
# ==========================================
class DatabaseManager:
    @staticmethod
    def get_connection():
        return mysql.connector.connect(**config.DB_CONFIG)

    @staticmethod
    def setup_tables():
        try:
            conn = DatabaseManager.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    emp_id INT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    timestamp DATETIME NOT NULL,
                    device_id VARCHAR(50)
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[DB ERROR] Setup failed: {e}")

    @staticmethod
    def fetch_users():
        emp_ids, names, designations, encodings = [], [], [], []
        try:
            conn = DatabaseManager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT emp_id, name, designation, encodings FROM info")
            rows = cursor.fetchall()
            conn.close()

            for emp_id, name, desig, enc_b64 in rows:
                if enc_b64:
                    try:
                        arr_bytes = base64.b64decode(enc_b64)
                        face_encoding = np.frombuffer(arr_bytes, dtype=np.float64)
                        if face_encoding.size != 128:
                            face_encoding = np.frombuffer(arr_bytes, dtype=np.float32)
                        
                        if face_encoding.size == 128:
                            emp_ids.append(emp_id)
                            names.append(name)
                            designations.append(desig)
                            encodings.append(face_encoding)
                    except:
                        pass
            print(f"[DB INFO] Loaded {len(emp_ids)} users.")
        except Exception as e:
            print(f"[DB ERROR] Fetch users failed: {e}")
        return emp_ids, names, designations, encodings

    @staticmethod
    def get_last_status(emp_id):
        try:
            conn = DatabaseManager.get_connection()
            cursor = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
                SELECT status FROM attendance 
                WHERE emp_id = %s AND DATE(timestamp) = %s 
                ORDER BY id DESC LIMIT 1
            """, (emp_id, today))
            record = cursor.fetchone()
            conn.close()
            return record[0] if record else "out"
        except:
            return "out"

    @staticmethod
    def mark_attendance(emp_id, name):
        last_status = DatabaseManager.get_last_status(emp_id)
        new_status = "out" if last_status == "in" else "in"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            conn = DatabaseManager.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO attendance (emp_id, name, status, timestamp, device_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (emp_id, name, new_status, timestamp, config.DEVICE_ID))
            conn.commit()
            conn.close()
            
            color = "#cc0000" if new_status == "out" else "#00cc00"
            msg = f"MARKED {new_status.upper()}"
            return msg, color, new_status
        except Exception as e:
            return f"Error: {e}", "#ff0000", "error"

# ==========================================
# 2. FACE SYSTEM (Matching Logic)
# ==========================================
class FaceSystem:
    def __init__(self):
        self.predictor = dlib.shape_predictor(config.DLIB_PREDICTOR_PATH)
        self.emp_ids, self.names, self.designations, self.encodings = [], [], [], []
        self.reload_data()

    def reload_data(self):
        self.emp_ids, self.names, self.designations, self.encodings = DatabaseManager.fetch_users()

    def get_head_pose_ratio(self, shape):
        nose = shape.part(30)
        jaw_left = shape.part(0)
        jaw_right = shape.part(16)
        
        dist_left = dist.euclidean((nose.x, nose.y), (jaw_left.x, jaw_left.y))
        dist_right = dist.euclidean((nose.x, nose.y), (jaw_right.x, jaw_right.y))
        
        if dist_right == 0: return 1.0
        return dist_left / dist_right

    def recognize_from_box(self, rgb_frame, box):
        if not self.encodings:
            return {'name': 'Unknown', 'id': None, 'desig': ''}

        encodings = face_recognition.face_encodings(rgb_frame, known_face_locations=[box])
        if not encodings:
            return {'name': 'Unknown', 'id': None, 'desig': ''}

        current_encoding = encodings[0]
        face_distances = face_recognition.face_distance(self.encodings, current_encoding)
        
        # Sort best to worst
        sorted_indices = np.argsort(face_distances)
        best_match_index = sorted_indices[0]
        best_match_score = face_distances[best_match_index]
        
        # Identify the potential candidate
        candidate_emp_id = self.emp_ids[best_match_index]
        
        # --- [NEW] DETERMINE THRESHOLD ---
        # Check if this specific user has a custom threshold in config
        if candidate_emp_id in config.CUSTOM_THRESHOLDS:
            current_threshold = config.CUSTOM_THRESHOLDS[candidate_emp_id]
        else:
            current_threshold = config.FACE_MATCH_THRESHOLD

        # --- RULE 1: THRESHOLD CHECK ---
        # Compare score against the SPECIFIC threshold for this user
        if best_match_score > current_threshold:
            return {'name': 'Unknown', 'id': None, 'desig': ''}

        # --- RULE 2: CONFIDENCE GAP ---
        if len(self.encodings) > 1:
            second_best_index = sorted_indices[1]
            second_best_score = face_distances[second_best_index]
            
            gap = second_best_score - best_match_score
            if gap < config.CONFIDENCE_GAP:
                print(f"[REJECTED] Confusion detected. Gap: {gap:.3f}")
                return {'name': 'Unknown', 'id': None, 'desig': ''}

        return {
            'id': candidate_emp_id,
            'name': self.names[best_match_index],
            'desig': self.designations[best_match_index],
            'encoding': current_encoding,
            'score': best_match_score
        }

# ==========================================
# 3. CAMERA MANAGER
# ==========================================
class CameraManager:
    def __init__(self):
        self.cap = None
        self.using_picam = False
        try:
            from picamera2 import Picamera2
            self.picam2 = Picamera2()
            config_cam = self.picam2.create_preview_configuration(main={"size": config.CAM_RES, "format": "BGR888"})
            self.picam2.configure(config_cam)
            self.picam2.start()
            self.using_picam = True
            print("[CAM] Picamera2 initialized (BGR).")
        except Exception:
            print("[CAM] Fallback to OpenCV.")
            self.cap = cv2.VideoCapture(0)
            self.cap.set(3, config.CAM_RES[0])
            self.cap.set(4, config.CAM_RES[1])

    def get_frame(self):
        if self.using_picam:
            return self.picam2.capture_array()
        else:
            ret, frame = self.cap.read()
            return frame if ret else None

    def release(self):
        if self.using_picam:
            self.picam2.stop()
        elif self.cap:
            self.cap.release()

# ==========================================
# 4. ATTENDANCE SYSTEM (Main Logic)
# ==========================================
class AttendanceSystem:
    STATE_SCANNING = 0
    STATE_VERIFYING = 1
    STATE_READY = 2
    STATE_MARKED = 3

    def __init__(self):
        DatabaseManager.setup_tables()
        self.face_system = FaceSystem()
        self.camera = CameraManager()
        
        self.mp_face = mp.solutions.face_detection.FaceDetection(
            model_selection=0, 
            min_detection_confidence=config.MIN_DETECTION_CONF
        )

        self.state = self.STATE_SCANNING
        self.current_user_data = None
        
        # Counters
        self.scan_counter = 0
        self.missed_frame_count = 0
        self.match_streak = 0
        self.streak_id = None
        self.stabilization_counter = 0
        
        # [NEW] Counter for re-scan timeout
        self.rescan_counter = 0
        
        self.last_box_coords = None
        self.last_landmarks = None
        
        self.button_timeout_timer = None
        self.reset_timer = None
        
        self.ui_status = {
            "name": "", "subtext": "", "name_color": "#333333",
            "show_button": False, "button_text": "", "button_color": "#888888"
        }

    def reset_to_scanning(self):
        if self.button_timeout_timer: self.button_timeout_timer.cancel()
        if self.reset_timer: self.reset_timer.cancel()

        self.state = self.STATE_SCANNING
        self.current_user_data = None
        
        # Reset Logic Counters
        self.missed_frame_count = 0
        self.match_streak = 0
        self.streak_id = None
        self.stabilization_counter = 0
        self.rescan_counter = 0 # Reset timeout
        
        self.last_box_coords = None
        
        self.ui_status.update({
            "name": "", "subtext": "", "name_color": "#333333",
            "show_button": False
        })

    def process_frame(self):
        frame = self.camera.get_frame()
        if frame is None: return None

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        
        small_frame = cv2.resize(frame, (0, 0), fx=config.PROCESS_SCALE, fy=config.PROCESS_SCALE)
        scale = 1.0 / config.PROCESS_SCALE
        box_color = (0, 165, 255) # Orange (Default)
        self.scan_counter += 1

        # 1. DETECTION
        should_detect = (self.state == self.STATE_SCANNING and self.scan_counter % 2 == 0) or \
                        (self.state in [self.STATE_VERIFYING, self.STATE_READY] and self.scan_counter % 3 == 0)

        found_box_scaled = None 

        if should_detect:
            small_rgb = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            results = self.mp_face.process(small_rgb)
            
            if results.detections:
                max_area = 0
                for detection in results.detections:
                    bboxC = detection.location_data.relative_bounding_box
                    if (bboxC.width * bboxC.height) < config.MIN_FACE_AREA: continue 
                    ratio = bboxC.width / bboxC.height
                    if ratio < 0.5 or ratio > 1.5: continue

                    ih, iw, _ = small_frame.shape
                    x = int(bboxC.xmin * iw)
                    y = int(bboxC.ymin * ih)
                    bw = int(bboxC.width * iw)
                    bh = int(bboxC.height * ih)
                    x, y = max(0, x), max(0, y)
                    
                    area = bw * bh
                    if area > max_area:
                        max_area = area
                        found_box_scaled = (int(y*scale), int((x+bw)*scale), int((y+bh)*scale), int(x*scale))

        # 2. PERSISTENCE
        if should_detect:
            if found_box_scaled:
                self.last_box_coords = found_box_scaled
                self.missed_frame_count = 0
            else:
                self.missed_frame_count += 1
                if self.missed_frame_count >= 2:
                    self.match_streak = 0
                    self.streak_id = None
                    self.stabilization_counter = 0 
                
                if self.missed_frame_count >= config.MAX_MISSED_FRAMES:
                    self.reset_to_scanning()
                    return frame

        # 3. STATE MACHINE
        
        # --- PHASE A: SCANNING ---
        if self.state == self.STATE_SCANNING:
            if self.last_box_coords:
                if self.stabilization_counter < config.STABILIZATION_FRAMES:
                    self.stabilization_counter += 1
                    box_color = (0, 255, 255) # Yellow
                else:
                    t, r, b, l = self.last_box_coords
                    small_box = (
                        int(t * config.PROCESS_SCALE), int(r * config.PROCESS_SCALE),
                        int(b * config.PROCESS_SCALE), int(l * config.PROCESS_SCALE)
                    )
                    
                    small_rgb = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
                    result = self.face_system.recognize_from_box(small_rgb, small_box)

                    detected_id = result.get('id')

                    if detected_id is not None:
                        if detected_id == self.streak_id:
                            self.match_streak += 1
                        else:
                            self.match_streak = 1
                            self.streak_id = detected_id
                        
                        if self.match_streak >= config.REQUIRED_STREAK:
                            self.current_user_data = result
                            self.state = self.STATE_VERIFYING
                            self.missed_frame_count = 0
                            self.match_streak = 0 
                            self.rescan_counter = 0 # Start Rescan Timer
                            
                            self.ui_status.update({
                                "name": f"{result['name']} - {result['desig']}",
                                "name_color": "#0000AA", "subtext": "", "show_button": False
                            })
                    else:
                        self.match_streak = 0
                        self.streak_id = None
                        box_color = (0, 0, 255) # Red

        # --- PHASE B: VERIFYING / READY ---
        elif self.state in [self.STATE_VERIFYING, self.STATE_READY]:
            if self.last_box_coords:
                
                # [NEW] CHECK RE-SCAN TIMER
                # If user stands there too long without punching, reset.
                self.rescan_counter += 1
                if self.rescan_counter >= config.RESCAN_FRAMES:
                    self.reset_to_scanning()
                    return frame

                # Proceed with Liveness Logic
                if self.state == self.STATE_VERIFYING:
                    user_id = self.current_user_data.get('id')
                    user_is_exempt = user_id in config.EXEMPT_LIVENESS_IDS
                    
                    if (not config.ENABLE_LIVENESS) or user_is_exempt:
                        self.state = self.STATE_READY
                        self.update_button_status()
                    else:
                        self.ui_status.update({"subtext": "Please Turn Head Left/Right"})
                        try:
                            t, r, b, l = self.last_box_coords
                            pad_h, pad_w = int((b-t)*0.15), int((r-l)*0.15)
                            small_t, small_b = max(0, int(t*config.PROCESS_SCALE)-pad_h), min(h, int(b*config.PROCESS_SCALE)+pad_h)
                            small_l, small_r = max(0, int(l*config.PROCESS_SCALE)-pad_w), min(w, int(r*config.PROCESS_SCALE)+pad_w)

                            dlib_rect = dlib.rectangle(small_l, small_t, small_r, small_b)
                            gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
                            shape = self.face_system.predictor(gray, dlib_rect)
                            
                            ratio = self.face_system.get_head_pose_ratio(shape)
                            
                            if ratio < config.YAW_THRESH_LEFT or ratio > config.YAW_THRESH_RIGHT:
                                self.state = self.STATE_READY
                                self.update_button_status()
                        except: pass

            if self.state == self.STATE_READY:
                box_color = (0, 255, 0) # Green

        # 4. DRAWING
        if self.last_box_coords:
            t, r, b, l = self.last_box_coords
            cv2.rectangle(frame, (l, t), (r, b), box_color, 2)
            
            if self.current_user_data and 'score' in self.current_user_data:
                score = self.current_user_data['score']
                text = f"{1-score:.3f}"
                cv2.putText(frame, text, (l, t - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (8, 145, 252), 2)

        return frame
    
    def update_button_status(self):
        emp_id = self.current_user_data['id']
        status = DatabaseManager.get_last_status(emp_id)
        btn_text = "PUNCH OUT" if status == 'in' else "PUNCH IN"
        btn_color = "#D32F2F" if status == 'in' else "#388E3C"
        
        self.ui_status.update({ "subtext": "", "show_button": True, "button_text": btn_text, "button_color": btn_color })
        
        if self.button_timeout_timer: self.button_timeout_timer.cancel()
        self.button_timeout_timer = threading.Timer(config.BUTTON_TIMEOUT, self.reset_to_scanning)
        self.button_timeout_timer.start()

    def handle_punch(self):
        if self.button_timeout_timer: self.button_timeout_timer.cancel()
        if not self.current_user_data: return
        
        e_id, name = self.current_user_data['id'], self.current_user_data['name']
        msg, color, _ = DatabaseManager.mark_attendance(e_id, name)
        
        self.state = self.STATE_MARKED
        self.ui_status.update({ "name": msg, "name_color": color, "subtext": f"Time: {datetime.now().strftime('%H:%M:%S')}", "show_button": False })
        
        self.last_box_coords = None
        self.reset_timer = threading.Timer(config.RESET_TIME_AFTER_PUNCH, self.reset_to_scanning)
        self.reset_timer.start()

# Initialize System
system = AttendanceSystem()

# ==========================================
# 5. FLASK ROUTES
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

def gen_frames():
    while True:
        frame = system.process_frame()
        if frame is not None:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ret, buffer = cv2.imencode('.jpg', rgb_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(1.0 / config.FPS)

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/status')
def status():
    return jsonify(system.ui_status)

@app.route('/punch_action', methods=['POST'])
def punch_action():
    system.handle_punch()
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)