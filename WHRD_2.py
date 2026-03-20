import RPi.GPIO as GPIO
import board
import adafruit_dht
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from RPLCD.i2c import CharLCD
import time
import threading
import csv
import os
from flask import Flask, jsonify, request, render_template
import subprocess
import webbrowser
from datetime import datetime
import json 
import socket
from zeroconf import ServiceInfo, Zeroconf

fan_start_time = 0.0
heater1_start_time = 0.0
heater2_start_time = 0.0
last_fan_on = False
last_heater1_on = False
last_heater2_on = False
baseline_reached_time = 0.0 

# =============================
# Flask & Global Config
# =============================
app = Flask(__name__)
SCRIPT_START_TIME = time.time()
STATE_FILE = 'curing_system_state.json'
SECONDARY_ACTUATOR_DELAY = 600

# =============================
# Dynamic Pin Configuration
# =============================
PIN_FILE = 'hardware_pins.json'

DEFAULT_PINS = {
    "FAN_PIN": 17,
    "DEHUMIDIFIER_PIN": 27,       
    "DEHUMIDIFIER_PIN_2": 23,     
    "O2_HEATER_PIN": 11,
    "SERVO_PIN": 18,
    "BUZZER_PIN": 24,
    "DHT_PIN": 4 
}

def load_pins():
    if os.path.exists(PIN_FILE):
        try:
            with open(PIN_FILE, 'r') as f: return json.load(f)
        except: pass
    with open(PIN_FILE, 'w') as f: json.dump(DEFAULT_PINS, f)
    return DEFAULT_PINS

HARDWARE_PINS = load_pins()

FAN_PIN = HARDWARE_PINS["FAN_PIN"]
DEHUMIDIFIER_PIN = HARDWARE_PINS["DEHUMIDIFIER_PIN"]
DEHUMIDIFIER_PIN_2 = HARDWARE_PINS["DEHUMIDIFIER_PIN_2"]
O2_HEATER_PIN = HARDWARE_PINS["O2_HEATER_PIN"]
SERVO_PIN = HARDWARE_PINS["SERVO_PIN"]
BUZZER_PIN = HARDWARE_PINS["BUZZER_PIN"]

try: DHT_PIN = getattr(board, f"D{HARDWARE_PINS['DHT_PIN']}")
except: DHT_PIN = board.D4 

X9_INC_PIN, X9_UD_PIN, X9_CS_PIN = 26, 8, 7
MODE_BUTTON_PIN, YELLOWING_BUTTON_PIN, LEAF_DRYING_BUTTON_PIN = 5, 6, 10
MIDRIB_DRYING_BUTTON_PIN, FAN_BUTTON_PIN, DEHUMIDIFIER_BUTTON_PIN, SERVO_BUTTON_PIN = 9, 13, 19, 15
YELLOWING_LED_PIN, LEAF_DRYING_LED_PIN, MIDRIB_DRYING_LED_PIN = 16, 20, 21
AUTO_MODE_LED_PIN, MANUAL_MODE_LED_PIN = 12, 25

RELAY_ACTIVE_LOW = True

CURING_STAGES = {
    "YELLOWING": { "min_temp": 28.0, "max_temp": 40.0, "humidity": 85.0, "ramp_fan_on": False, "duration_hours": 48 },
    "LEAF_DRYING": { "min_temp": 45.0, "max_temp": 55.0, "humidity": 70.0, "ramp_fan_on": True, "duration_hours": 48 },
    "MIDRIB_DRYING": { "min_temp": 60.0, "max_temp": 70.0, "humidity": 50.0, "ramp_fan_on": True, "duration_hours": 72 },
}

SERVO_DUTY_CYCLES = { 0: 2.5, 45: 5.0, 90: 7.5, 180: 12.5 }
servo_pwm = None 

# =============================
# Classes & States
# =============================
class AC_Spoofer:
    def __init__(self, inc, ud, cs):
        self.inc, self.ud, self.cs = inc, ud, cs
        GPIO.setup([self.inc, self.ud, self.cs], GPIO.OUT, initial=GPIO.HIGH)
        self.current_mode = "UNKNOWN"
        self.reset_to_zero()
        
    def reset_to_zero(self):
        GPIO.output(self.cs, GPIO.LOW); GPIO.output(self.ud, GPIO.LOW) 
        for _ in range(100):
            GPIO.output(self.inc, GPIO.LOW); time.sleep(0.01); GPIO.output(self.inc, GPIO.HIGH); time.sleep(0.01)
        GPIO.output(self.cs, GPIO.HIGH)
        
    def set_mode(self, mode):
        if mode == self.current_mode: return 
        self.reset_to_zero() 
        target = 30 if mode == "COMPRESSOR_ON" else 75 if mode == "FAN_ONLY" else 75
        if target > 0:
            GPIO.output(self.cs, GPIO.LOW); GPIO.output(self.ud, GPIO.HIGH) 
            for _ in range(target):
                GPIO.output(self.inc, GPIO.LOW); time.sleep(0.01); GPIO.output(self.inc, GPIO.HIGH); time.sleep(0.01)
            GPIO.output(self.cs, GPIO.HIGH)
        self.current_mode = mode

ac_controller = None

current_mode, current_stage_index = "AUTO", 0
stage_start_time, stage_start_temp, auto_target_temp = 0.0, 24.0, 24.0
fan_on, dehumidifier_on, dehumidifier_on_2, o2_heater_on = False, False, False, False
dehum_1_on_time, buzzer_on = 0.0, False
temperature, humidity, o2_voltage, servo_angle = 0.0, 0.0, 0.0, 0 
dht_error, o2_error = True, True
last_dht_read_time = time.time()
lock = threading.Lock()
ads, o2_channel = None, None

# =============================
# Hardware Functions
# =============================
def initialize_lcd():
    for address in [0x27, 0x3F]:
        try:
            lcd = CharLCD(i2c_expander='PCF8574', address=address, port=1, cols=20, rows=4, dotsize=8)
            lcd.clear(); return lcd
        except: pass
    return None

lcd = initialize_lcd()

def initialize_i2c_sensors():
    global ads, o2_channel, o2_error
    try:
        i2c = board.I2C()
        ads = ADS.ADS1115(i2c)
        o2_channel = AnalogIn(ads, ADS.P0)
        o2_error = False
        print("ADS1115 (O2) Initialized")
    except Exception as e:
        o2_error = True
        print(f"ADS1115 Error: {e}")

def relay_on(pin): GPIO.output(pin, GPIO.LOW if RELAY_ACTIVE_LOW else GPIO.HIGH)
def relay_off(pin): GPIO.output(pin, GPIO.HIGH if RELAY_ACTIVE_LOW else GPIO.LOW)
def control_buzzer(state): GPIO.output(BUZZER_PIN, GPIO.HIGH if state else GPIO.LOW)

def set_servo_angle(angle):
    global servo_pwm
    if angle in SERVO_DUTY_CYCLES and servo_pwm:
        servo_pwm.ChangeDutyCycle(SERVO_DUTY_CYCLES[angle])
        time.sleep(0.5) 
        servo_pwm.ChangeDutyCycle(0) 

def update_hardware():
    if dehumidifier_on: relay_on(DEHUMIDIFIER_PIN)
    else: relay_off(DEHUMIDIFIER_PIN)

    if dehumidifier_on_2: relay_on(DEHUMIDIFIER_PIN_2)
    else: relay_off(DEHUMIDIFIER_PIN_2)

    if fan_on: GPIO.output(FAN_PIN, GPIO.HIGH)
    else: GPIO.output(FAN_PIN, GPIO.LOW)

    if o2_heater_on and not o2_error: relay_on(O2_HEATER_PIN)
    else: relay_off(O2_HEATER_PIN)

    if ac_controller:
        if dehumidifier_on: ac_controller.set_mode("COMPRESSOR_ON")
        else: ac_controller.set_mode("FAN_ONLY")

def update_stage_leds(stage_name, mode):
    stage_to_pin = {"YELLOWING": YELLOWING_LED_PIN, "LEAF_DRYING": LEAF_DRYING_LED_PIN, "MIDRIB_DRYING": MIDRIB_DRYING_LED_PIN}
    for stage, pin in stage_to_pin.items(): GPIO.output(pin, GPIO.HIGH if stage == stage_name else GPIO.LOW)
    GPIO.output(AUTO_MODE_LED_PIN, GPIO.HIGH if mode == "AUTO" else GPIO.LOW)
    GPIO.output(MANUAL_MODE_LED_PIN, GPIO.HIGH if mode == "MANUAL" else GPIO.LOW)

def update_lcd_display(stage, mode):
    if lcd:
        lcd.home()
        lcd.write_string(f"T:{f'{temperature:.1f}C' if not dht_error else 'ERR '} H:{f'{humidity:.0f}%' if not dht_error else 'ERR '}")
        lcd.write_string(f" O2:{f'{o2_voltage:.2f}V' if not o2_error else 'ERR '}")
        lcd.crlf()
        lcd.write_string(f"Stg:{stage[:3]} Md:{mode[:4]}")

def register_mdns_service():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)) 
        local_ip = s.getsockname()[0]; s.close()
        info = ServiceInfo("_tobacco._tcp.local.", "Tobacco Curing System._tobacco._tcp.local.",
                           addresses=[socket.inet_aton(local_ip)], port=5050,
                           properties={'version': '1.0'}, server="tobacco-pi.local.")
        zeroconf = Zeroconf(); zeroconf.register_service(info)
        return zeroconf
    except: return None

# =============================
# Persistence & Logging
# =============================
def save_state():
    state = {
        'current_mode': current_mode, 'current_stage': current_stage_index,
        'stage_start_timestamp': stage_start_time, 'target_temp': auto_target_temp, 
        'stage_start_temp': stage_start_temp, 'fan_on': fan_on, 'dehumidifier_on': dehumidifier_on,
        'dehumidifier_on_2': dehumidifier_on_2, 'dehum_1_on_time': dehum_1_on_time,
        'buzzer_on': buzzer_on, 'servo_angle': servo_angle,
        'baseline_reached_time': baseline_reached_time
    }
    try:
        with open(STATE_FILE, 'w') as f: json.dump(state, f)
    except: pass

def load_state():
    global current_mode, current_stage_index, stage_start_time, auto_target_temp, stage_start_temp
    global fan_on, dehumidifier_on, dehumidifier_on_2, buzzer_on, servo_angle, dehum_1_on_time
    global baseline_reached_time
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f: state = json.load(f)
            current_mode, current_stage_index = state.get('current_mode', 'MANUAL'), state.get('current_stage', 0)
            stage_start_time, auto_target_temp = state.get('stage_start_timestamp', time.time()), state.get('target_temp', 24.0)
            stage_start_temp, fan_on = state.get('stage_start_temp', 24.0), state.get('fan_on', False)
            dehumidifier_on, dehumidifier_on_2 = state.get('dehumidifier_on', False), state.get('dehumidifier_on_2', False)
            dehum_1_on_time, buzzer_on = state.get('dehum_1_on_time', time.time()), state.get('buzzer_on', False)
            servo_angle = state.get('servo_angle', 0)
            baseline_reached_time = state.get('baseline_reached_time', 0.0)
            
            # --- HOTFIX MIGRATION FOR ACTIVE CURING ---
            if baseline_reached_time == 0.0 and (time.time() - stage_start_time > 3600):
                baseline_reached_time = stage_start_time
            # ------------------------------------------
                
            return True
        except: return False
    return False

def set_curing_stage(target_stage_name):
    global current_stage_index, stage_start_time, stage_start_temp, auto_target_temp
    global fan_on, dehumidifier_on, dehumidifier_on_2, dehum_1_on_time
    global baseline_reached_time
    
    try: new_index = list(CURING_STAGES.keys()).index(target_stage_name)
    except ValueError: return False
        
    current_stage_index, stage_start_time = new_index, time.time()
    setpoints = CURING_STAGES[target_stage_name]
    
    if current_mode == "AUTO":
        stage_start_temp = max(temperature, setpoints["min_temp"]) if not dht_error else setpoints["min_temp"] 
        auto_target_temp = stage_start_temp 
        baseline_reached_time = 0.0 
        fan_on, dehumidifier_on, dehumidifier_on_2 = False, False, False
        dehum_1_on_time = time.time()
    else:
        stage_start_temp, auto_target_temp = setpoints["min_temp"], setpoints["min_temp"]
        
    update_stage_leds(target_stage_name, current_mode)
    update_hardware(); save_state()
    return True

def log_data(timestamp, temp, hum, stage, mode, fan1, dehum1, dehum2, alarm, servo, o2_v, o2_heat):
    log_file = 'curing_log.csv'
    file_exists = os.path.isfile(log_file)
    try:
        with open(log_file, 'a', newline='') as csvfile:
            fieldnames = [
                'timestamp', 'datetime', 'temperature', 'humidity', 'stage', 'mode', 
                'fan_on', 'dehumidifier_on', 'dehumidifier_on_2', 
                'alarm_on', 'servo_angle', 'o2_voltage', 'o2_heater_on'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists: writer.writeheader()
            writer.writerow({
                'timestamp': timestamp,
                'datetime': datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                'temperature': round(temp, 2) if temp is not None else 0, 
                'humidity': round(hum, 2) if hum is not None else 0,
                'stage': stage, 'mode': mode, 'fan_on': fan1, 
                'dehumidifier_on': dehum1, 'dehumidifier_on_2': dehum2,
                'alarm_on': alarm, 'servo_angle': servo,
                'o2_voltage': round(o2_v, 2) if o2_v is not None else 0, 
                'o2_heater_on': o2_heat
            })
    except Exception as e: print(f"Logging error: {e}")

# =============================
# API Routes
# =============================
@app.route('/api/config/stages', methods=['POST'])
def update_stage_config():
    global current_stage_index 
    
    data = request.get_json()
    if not data or "stage" not in data:
        return jsonify({"error": "Missing stage data"}), 400
        
    stage_name = data["stage"]
    if stage_name in CURING_STAGES:
        if "min_temp" in data: CURING_STAGES[stage_name]["min_temp"] = float(data["min_temp"])
        if "max_temp" in data: CURING_STAGES[stage_name]["max_temp"] = float(data["max_temp"])
        if "duration_minutes" in data: 
            CURING_STAGES[stage_name]["duration_hours"] = float(data["duration_minutes"]) / 60.0
        
        current_active_stage_name = list(CURING_STAGES.keys())[current_stage_index]
        if stage_name == current_active_stage_name:
            set_curing_stage(stage_name)
        
        return jsonify({"success": True})
        
    return jsonify({"error": "Invalid stage name"}), 400

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    global baseline_reached_time
    stage_name = list(CURING_STAGES.keys())[current_stage_index]
    setpoints = CURING_STAGES[stage_name]
    elapsed = time.time() - stage_start_time
    
    if baseline_reached_time == 0.0:
        next_inc = 0 
    else:
        elapsed_ramp = time.time() - baseline_reached_time
        next_inc = int(3600 - (elapsed_ramp % 3600))
        
    return jsonify({
        "mode": current_mode, "stage": stage_name,
        "temperature": round(float(temperature), 1) if not dht_error else 0.0,
        "humidity": round(float(humidity), 1) if not dht_error else 0.0,
        "o2_voltage": round(float(o2_voltage), 2) if not o2_error else 0.0,
        "o2_heater_on": o2_heater_on,
        "target_temp": round(float(auto_target_temp), 1) if current_mode == "AUTO" else 0.0,
        "max_temp": float(setpoints["max_temp"]),
        "fan_on": fan_on, "dehumidifier_on": dehumidifier_on, "dehumidifier_on_2": dehumidifier_on_2,
        "buzzer_on": buzzer_on, "servo_angle": int(servo_angle),
        "uptime": int(time.time() - SCRIPT_START_TIME),               
        "next_temp_increase": next_inc,           
        "stage_remaining": int(max(0, (setpoints.get("duration_hours", 48) * 3600) - elapsed)),
        "stage_start_temp": round(float(stage_start_temp), 1),
        "next_target_temp": round(float(min(setpoints["max_temp"], auto_target_temp + 1.0)), 1) if current_mode == "AUTO" else 0.0,
        "fan_run_time": int(time.time() - fan_start_time) if (fan_on and fan_start_time > 0) else 0,
        "heater1_run_time": int(time.time() - heater1_start_time) if (dehumidifier_on and heater1_start_time > 0) else 0,
        "heater2_run_time": int(time.time() - heater2_start_time) if (dehumidifier_on_2 and heater2_start_time > 0) else 0,
        "dht_error": dht_error, "o2_error": o2_error 
    })

@app.route('/api/logs', methods=['GET'])
def get_logs():
    log_file = 'curing_log.csv'
    if not os.path.exists(log_file): return jsonify([])
    data = []
    try:
        with open(log_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)[-1440:]
            for row in rows:
                try:
                    data.append({
                        "timestamp": float(row["timestamp"]),
                        "datetime": row["datetime"],
                        "temperature": float(row["temperature"]),
                        "humidity": float(row["humidity"])
                    })
                except (ValueError, KeyError, TypeError):
                    continue 
                    
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/mode', methods=['POST'])
def set_mode():
    global current_mode, fan_on, dehumidifier_on, dehumidifier_on_2
    current_mode = "MANUAL" if current_mode == "AUTO" else "AUTO"
    if current_mode == "MANUAL": fan_on, dehumidifier_on, dehumidifier_on_2 = False, False, False; update_hardware()
    update_stage_leds(list(CURING_STAGES.keys())[current_stage_index], current_mode); save_state()
    return jsonify({"mode": current_mode})

@app.route('/api/stage', methods=['POST'])
def set_stage_api():
    if set_curing_stage(request.get_json().get('stage')): return jsonify({"stage": request.get_json().get('stage')})
    return jsonify({"error": "Invalid stage"}), 400

@app.route('/api/fan', methods=['POST'])
def toggle_fan():
    global fan_on; fan_on = not fan_on; update_hardware(); save_state(); return jsonify({"fan_on": fan_on})

@app.route('/api/dehumidifier', methods=['POST'])
def toggle_dehumidifier():
    global dehumidifier_on, dehumidifier_on_2
    dehumidifier_on = not dehumidifier_on; dehumidifier_on_2 = dehumidifier_on 
    update_hardware(); save_state(); return jsonify({"dehumidifier_on": dehumidifier_on})

@app.route('/api/servo', methods=['POST'])
def set_servo_api():
    global servo_angle
    new_angle = request.get_json().get('angle')
    if new_angle in SERVO_DUTY_CYCLES:
        set_servo_angle(new_angle); servo_angle = new_angle; save_state(); return jsonify({"servo_angle": servo_angle})
    return jsonify({"error": "Invalid Angle"}), 400

@app.route('/api/config/pins', methods=['GET', 'POST'])
def manage_pins():
    if request.method == 'GET': return jsonify(load_pins())
    if request.method == 'POST':
        new_pins = request.get_json()
        with open(PIN_FILE, 'w') as f: json.dump(new_pins, f)
        return jsonify({"status": "Pins saved. Please reboot the Pi hardware."})

# =============================
# Main Loop
# =============================
def setup_gpio():
    global servo_pwm, ac_controller
    GPIO.setmode(GPIO.BCM)
    GPIO.setup([FAN_PIN, DEHUMIDIFIER_PIN, DEHUMIDIFIER_PIN_2, BUZZER_PIN, SERVO_PIN, O2_HEATER_PIN], GPIO.OUT)
    ac_controller = AC_Spoofer(X9_INC_PIN, X9_UD_PIN, X9_CS_PIN)
    GPIO.setup([MODE_BUTTON_PIN, YELLOWING_BUTTON_PIN, LEAF_DRYING_BUTTON_PIN, MIDRIB_DRYING_BUTTON_PIN, FAN_BUTTON_PIN, DEHUMIDIFIER_BUTTON_PIN, SERVO_BUTTON_PIN], GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    GPIO.setup([YELLOWING_LED_PIN, LEAF_DRYING_LED_PIN, MIDRIB_DRYING_LED_PIN, AUTO_MODE_LED_PIN, MANUAL_MODE_LED_PIN], GPIO.OUT)
    
    for p in [DEHUMIDIFIER_PIN, DEHUMIDIFIER_PIN_2, O2_HEATER_PIN]: relay_off(p)
    
    GPIO.output(FAN_PIN, GPIO.LOW)
    
    servo_pwm = GPIO.PWM(SERVO_PIN, 50); servo_pwm.start(0) 

def main():
    global current_mode, current_stage_index, stage_start_time, fan_on, dehumidifier_on, dehumidifier_on_2, buzzer_on, temperature, humidity, auto_target_temp, servo_angle
    global dehum_1_on_time, o2_heater_on, o2_voltage, dht_error, o2_error, last_dht_read_time
    global baseline_reached_time

    setup_gpio(); initialize_i2c_sensors(); load_state() 
    if stage_start_time == 0.0: stage_start_time = time.time()
    
    zeroconf_service = register_mdns_service()
    dht_device = adafruit_dht.DHT22(DHT_PIN)
    stage_keys, servo_angles = list(CURING_STAGES.keys()), list(SERVO_DUTY_CYCLES.keys())
    update_stage_leds(stage_keys[current_stage_index], current_mode)
    last_press = {k:0 for k in ['m','y','l','mi','f','d','s']}

    try:
        while True:
            t = time.time()
            btns = {
                'm': not GPIO.input(MODE_BUTTON_PIN), 'y': not GPIO.input(YELLOWING_BUTTON_PIN),
                'l': not GPIO.input(LEAF_DRYING_BUTTON_PIN), 'mi': not GPIO.input(MIDRIB_DRYING_BUTTON_PIN),
                'f': not GPIO.input(FAN_BUTTON_PIN), 'd': not GPIO.input(DEHUMIDIFIER_BUTTON_PIN), 's': not GPIO.input(SERVO_BUTTON_PIN)
            }

            if btns['m'] and (t - last_press['m'] > 0.5):
                current_mode = "MANUAL" if current_mode == "AUTO" else "AUTO"
                if current_mode == "MANUAL": fan_on, dehumidifier_on, dehumidifier_on_2 = False, False, False; update_hardware()
                update_stage_leds(stage_keys[current_stage_index], current_mode); save_state(); last_press['m'] = t
            if btns['y'] and (t - last_press['y'] > 0.5): set_curing_stage("YELLOWING"); last_press['y'] = t
            if btns['l'] and (t - last_press['l'] > 0.5): set_curing_stage("LEAF_DRYING"); last_press['l'] = t
            if btns['mi'] and (t - last_press['mi'] > 0.5): set_curing_stage("MIDRIB_DRYING"); last_press['mi'] = t

            try:
                with lock:
                    temp_val, hum_val = dht_device.temperature, dht_device.humidity
                    if temp_val is not None and hum_val is not None: temperature, humidity, dht_error, last_dht_read_time = temp_val, hum_val, False, t
            except RuntimeError: pass 
            if t - last_dht_read_time > 10.0: dht_error = True

            try:
                if o2_channel: o2_voltage, o2_error = o2_channel.voltage, False
                else: o2_error = True
            except: o2_error = True

            stage_name = stage_keys[current_stage_index]
            setpoints = CURING_STAGES[stage_name]

            if current_mode == "AUTO":
                if not dht_error:
                    if baseline_reached_time == 0.0:
                        auto_target_temp = stage_start_temp
                        if temperature >= stage_start_temp:
                            baseline_reached_time = t
                            save_state() 
                    else:
                        hours_passed = int((t - baseline_reached_time) / 3600)
                        auto_target_temp = min(setpoints["max_temp"], stage_start_temp + hours_passed)
                    
                    if temperature < auto_target_temp - 0.5:
                        if not dehumidifier_on: dehum_1_on_time = t 
                        dehumidifier_on, fan_on = True, False
                        if t - dehum_1_on_time > SECONDARY_ACTUATOR_DELAY: dehumidifier_on_2 = True
                    elif temperature < auto_target_temp + 0.5: 
                        dehumidifier_on, dehumidifier_on_2, fan_on = False, False, setpoints.get("ramp_fan_on", False)
                    else: 
                        dehumidifier_on, dehumidifier_on_2, fan_on = False, False, True
                        
                    # --- THE NEW HUMIDITY FIX ---
                    # If humidity is high, vent with the fan, but DO NOT turn off the heaters if they need to be on!
                    if humidity > setpoints["humidity"] + 5.0: 
                        fan_on = True 
                    # ----------------------------

                    buzzer_on = (temperature > setpoints["max_temp"])
                else: 
                    dehumidifier_on, dehumidifier_on_2, fan_on, buzzer_on = False, False, True, True 
            else: 
                if btns['s'] and (t - last_press['s'] > 0.5): set_servo_angle(servo_angles[(servo_angles.index(servo_angle) + 1) % len(servo_angles)]); save_state(); last_press['s'] = t
                if btns['f'] and (t - last_press['f'] > 0.5): fan_on = not fan_on; save_state(); last_press['f'] = t
                if btns['d'] and (t - last_press['d'] > 0.5): dehumidifier_on = not dehumidifier_on; dehumidifier_on_2 = dehumidifier_on; save_state(); last_press['d'] = t
                buzzer_on = False if dht_error else (temperature > setpoints["max_temp"])

            global fan_start_time, heater1_start_time, heater2_start_time
            global last_fan_on, last_heater1_on, last_heater2_on
            
            if fan_on and not last_fan_on: fan_start_time = t
            if not fan_on: fan_start_time = 0.0
            last_fan_on = fan_on
            
            if dehumidifier_on and not last_heater1_on: heater1_start_time = t
            if not dehumidifier_on: heater1_start_time = 0.0
            last_heater1_on = dehumidifier_on

            if dehumidifier_on_2 and not last_heater2_on: heater2_start_time = t
            if not dehumidifier_on_2: heater2_start_time = 0.0
            last_heater2_on = dehumidifier_on_2

            o2_heater_on = True if fan_on else False
            update_hardware(); control_buzzer(buzzer_on); update_lcd_display(stage_name, current_mode)
            
            if t % 30 < 0.5: save_state()
            if t % 60 < 0.5: log_data(t, temperature, humidity, stage_name, current_mode, fan_on, dehumidifier_on, dehumidifier_on_2, buzzer_on, servo_angle, o2_voltage, o2_heater_on)
            time.sleep(0.5)
    finally:
        if zeroconf_service: zeroconf_service.close()
        if lcd: lcd.clear()
        if servo_pwm: servo_pwm.stop()
        GPIO.cleanup()

def launch_kiosk():
    time.sleep(3) 
    try:
        subprocess.Popen(['chromium-browser', '--kiosk', '--noerrdialogs', '--disable-infobars', 'http://localhost:5050/'])
    except Exception:
        webbrowser.open_new('http://localhost:5050/')

if __name__ == "__main__":
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5050, debug=False, use_reloader=False))
    flask_thread.daemon = True; flask_thread.start()
    
    threading.Thread(target=launch_kiosk, daemon=True).start()
    
    main()