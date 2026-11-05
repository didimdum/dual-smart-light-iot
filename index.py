from flask import Flask, render_template, jsonify, request, redirect, url_for, session
import paho.mqtt.client as mqtt
import time
import threading
from datetime import datetime, timedelta
import ssl
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file  

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per day"]
) # Tambahkan kurung tutup ini

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=15)

# Kunci rahasia untuk enkripsi session Flask
app.secret_key = os.getenv('SECRET_KEY')  # Gunakan kunci rahasia dari .env atau default jika tidak ada

# --- KREDENSIAL TUNGGAL (LOGIN) ---
ADMIN_USER = os.getenv('ADMIN_USER')
ADMIN_PASS = os.getenv('ADMIN_PASS')

MQTT_BROKER = os.getenv('MQTT_BROKER')
MQTT_PORT = int(os.getenv('MQTT_PORT'))
MQTT_USER = os.getenv('MQTT_USER')
MQTT_PASS = os.getenv('MQTT_PASS')

# --- TOPIK MQTT UNTUK BOX 1 & BOX 2 ---
MQTT_TOPIC_BOX1_CTRL = "smk/box1/relay/control"
MQTT_TOPIC_BOX1_STATUS = "smk/box1/relay/status"
MQTT_TOPIC_BOX1_MODE = "smk/box1/mode/control"

MQTT_TOPIC_BOX2_CTRL = "smk/box2/relay/control"
MQTT_TOPIC_BOX2_STATUS = "smk/box2/relay/status"
MQTT_TOPIC_BOX2_MODE = "smk/box2/mode/control"

# Status Variabel Global
box1_status = "OFF"
box2_status = "OFF"
box1_mode = "MANUAL"
box2_mode = "MANUAL"
schedule_on_1 = "18:00"
schedule_off_1 = "06:00"
schedule_on_2 = "18:00"
schedule_off_2 = "06:00"
last_update = "Belum ada update"
history_data = []
mqtt_connected = False

def add_history(device, action):
    global history_data
    waktu = datetime.now().strftime("%H:%M:%S")
    history_data.insert(0, {"time": waktu, "device": device, "action": action})
    if len(history_data) > 50:
        history_data = history_data[:50]

# --- CALLBACKS MQTT ---
def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print("[MQTT] Server Connected Successfully!")
    else:
        mqtt_connected = False
        print(f"[MQTT] Connection Error Code: {rc}")

def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print("[MQTT] Disconnected from Server!")

def on_message(client, userdata, msg):
    global box1_status, box2_status, last_update
    payload = msg.payload.decode()
    topic = msg.topic
    waktu = datetime.now().strftime("%H:%M:%S")

    if topic == MQTT_TOPIC_BOX1_STATUS:
        box1_status = payload
        last_update = waktu
        add_history("Box 1 (Dimas)", f"Relay {payload}")
    elif topic == MQTT_TOPIC_BOX2_STATUS:
        box2_status = payload
        last_update = waktu
        add_history("Box 2 (Yubi)", f"Relay {payload}")

# Setup MQTT Client
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
# Keamanan TLS untuk port 8883
client.tls_set(cert_reqs=ssl.CERT_NONE)
client.tls_insecure_set(True)
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

try:
    print(f"[MQTT] Mencoba menghubungkan ke broker {MQTT_BROKER}:{MQTT_PORT}...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe([
        (MQTT_TOPIC_BOX1_STATUS, 0),
        (MQTT_TOPIC_BOX2_STATUS, 0)
    ])
    client.loop_start()
except Exception as e:
    print(f"[MQTT] Connection Error Detail: {e}")

# Checker Jadwal Timer
def schedule_checker():
    while True:
        now_sec = datetime.now().strftime("%H:%M:%S")
        
        if box1_mode == "SCHEDULE":
            if now_sec == f"{schedule_on_1}:00":
                client.publish(MQTT_TOPIC_BOX1_CTRL, "ON")
            elif now_sec == f"{schedule_off_1}:00":
                client.publish(MQTT_TOPIC_BOX1_CTRL, "OFF")
                
        # PERBAIKAN: Posisi 'if box2_mode' sekarang sejajar dengan 'if box1_mode'
        if box2_mode == "SCHEDULE":
            if now_sec == f"{schedule_on_2}:00":
                client.publish(MQTT_TOPIC_BOX2_CTRL, "ON")
            elif now_sec == f"{schedule_off_2}:00":
                client.publish(MQTT_TOPIC_BOX2_CTRL, "OFF")
                
        time.sleep(1)

threading.Thread(target=schedule_checker, daemon=True).start()

# --- DEKORATOR LOGIN CHECK ---
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES AUTH (LOGIN / LOGOUT) ---
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", error_message="Terlalu banyak percobaan login. Silakan tunggu 1 menit.")
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USER and password == ADMIN_PASS:
            session['logged_in'] = True
            session.permanent = True
            return redirect(url_for('index'))
        else:
            error = 'Username atau Password salah!'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# --- ROUTES FLASK (DILINDUNGI LOGIN) ---
@app.route('/')
@login_required
def index():
    return render_template(
        'control.html',
        box1_status=box1_status,
        box2_status=box2_status,
        box1_mode=box1_mode,
        box2_mode=box2_mode,
        schedule_on_1=schedule_on_1,
        schedule_off_1=schedule_off_1,
        schedule_on_2=schedule_on_2,
        schedule_off_2=schedule_off_2,
        last_update=last_update,
        mqtt_connected=mqtt_connected
    )

@app.route('/monitoring')
@login_required
def monitoring():
    return render_template(
        'monitoring.html',
        history=history_data,
        last_update=last_update,
        mqtt_connected=mqtt_connected
    )

@app.route('/relay/<int:box_id>/<action>')
@login_required
def control_relay(box_id, action):
    global box1_mode, box2_mode
    try:
        if box_id == 1:
            if box1_mode != "MANUAL":
                box1_mode = "MANUAL"
                client.publish(MQTT_TOPIC_BOX1_MODE, "MANUAL")
            client.publish(MQTT_TOPIC_BOX1_CTRL, action)
            
        elif box_id == 2:
            if box2_mode != "MANUAL":
                box2_mode = "MANUAL"
                client.publish(MQTT_TOPIC_BOX2_MODE, "MANUAL")
            client.publish(MQTT_TOPIC_BOX2_CTRL, action)
            
        return jsonify({"status": "success", "message": f"Box {box_id} diarahkan {action}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/set_mode/<int:box_id>', methods=['POST'])
@login_required
def set_mode(box_id):
    global box1_mode, box2_mode, schedule_on_1, schedule_off_1, schedule_on_2, schedule_off_2
    mode = request.form.get('mode')
    
    if box_id == 1:
        box1_mode = mode
        schedule_on_1 = request.form.get('time_on')
        schedule_off_1 = request.form.get('time_off')
        client.publish(MQTT_TOPIC_BOX1_MODE, "LDR" if box1_mode == "LDR" else "MANUAL")
        add_history("Box 1 (Dimas)", f"Mode -> {mode}")
    elif box_id == 2:
        box2_mode = mode
        schedule_on_2 = request.form.get('time_on')
        schedule_off_2 = request.form.get('time_off')
        client.publish(MQTT_TOPIC_BOX2_MODE, "LDR" if box2_mode == "LDR" else "MANUAL")
        add_history("Box 2 (Yubi)", f"Mode -> {mode}")
        
    return jsonify({"status": "success", "message": f"Mode Box {box_id} diperbarui"})

@app.route('/api/status')
@login_required
def api_status():
    return jsonify({
        'mqtt_connected': mqtt_connected,
        'box1_status': box1_status,
        'box2_status': box2_status,
        'box1_mode': box1_mode,
        'box2_mode': box2_mode,
        'last_update': last_update,
        'history': history_data[:10]
    })

if __name__ == '__main__':
    print("=" * 50)
    print("  Dual Smart Light Control System (Box 1 & Box 2)")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)