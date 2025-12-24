# config.py

# ==========================================
# 1. DATABASE SETTINGS
# ==========================================
DB_CONFIG = {
    "host": "localhost",
    "user": "acs_user",
    "password": "Secret4acs_user",
    "database": "face_attendance"
}

# ==========================================
# 2. SYSTEM PATHS & DEVICE
# ==========================================
# Directory where the script and .dat file are located
BASE_DIR = '/home/pi/face_attendance/' 
DLIB_PREDICTOR_PATH = BASE_DIR + 'shape_predictor_68_face_landmarks.dat'

# Unique ID for this specific Attendance Machine
DEVICE_ID = 71

# ==========================================
# 3. CAMERA & PERFORMANCE
# ==========================================
# Camera Resolution (Width, Height)
CAM_RES = (640, 480)
# WEB_FRAME_SIZE = (640, 480)

# Target Framerate
FPS = 30

# Image scaling for processing (Lower = Faster, Higher = More Accurate)
# 1.0 = Full resolution. 0.5 = Half size (4x faster).
PROCESS_SCALE = 1.0

# ==========================================
# 4. FACE RECOGNITION TUNING (Crucial)
# ==========================================
# STRICTNESS: Maximum distance to accept a match (Lower is stricter).
# Standard is 0.6. Secure is 0.45.
FACE_MATCH_THRESHOLD = 0.45

CUSTOM_THRESHOLDS = {
    101: 0.55,  # Loose threshold for Emp ID 101
    102: 0.60,  # Very loose for Emp ID 102
    788: 0.39,   # Very strict for Emp ID 999
    335: 0.50
}

# CONFIDENCE GAP: The difference required between the Best Match and 2nd Best.
# Prevents confusion between similar looking people.
CONFIDENCE_GAP = 0.04

# ==========================================
# 5. DETECTION & STABILITY
# ==========================================
# Minimum face size (% of screen). Filters out people standing far away.
MIN_FACE_AREA = 0.03

# Minimum confidence for MediaPipe to accept a face is present.
MIN_DETECTION_CONF = 0.95

# STABILIZATION: How many frames to wait after detecting a face 
# before running recognition. Allows auto-focus/exposure to settle.
STABILIZATION_FRAMES = 5

# STREAK: How many consecutive frames the SAME person must be recognized
# before the system accepts them. Eliminates random flickering.
REQUIRED_STREAK = 3

# PERSISTENCE: How many frames to keep the box if face is momentarily lost.
MAX_MISSED_FRAMES = 2

# ==========================================
# 6. LIVENESS (HEAD TURN)
# ==========================================
# Enable or Disable the Head Turn requirement
ENABLE_LIVENESS = True

# Employee IDs who can skip the head turn (e.g., VIPs or elderly)
EXEMPT_LIVENESS_IDS = [1, 2]

# Head Turn Ratios (1.0 is Center)
# < 0.60 usually means looking LEFT
# > 1.60 usually means looking RIGHT
YAW_THRESH_LEFT = 0.50
YAW_THRESH_RIGHT = 1.50

#rescan
RESCAN_TIMEOUT_SECONDS = 10

# Calculate frames automatically based on FPS
RESCAN_FRAMES = int(FPS * RESCAN_TIMEOUT_SECONDS)

# ==========================================
# 7. UI & TIMING
# ==========================================
# How long (seconds) to show the "MARKED IN/OUT" success screen
RESET_TIME_AFTER_PUNCH = 2.0

# How long (seconds) the Punch Button stays visible if user does nothing
BUTTON_TIMEOUT = 5.0
