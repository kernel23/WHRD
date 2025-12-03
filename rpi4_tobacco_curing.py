# A Python script for controlling the tobacco curing process using a DHT22 sensor
# on a Raspberry Pi 4. The script includes both manual and automatic modes, with
# buttons for control, and follows the four stages of flue-curing for tobacco.
#
# Before running, make sure you have installed the required libraries inside your virtual environment:
# pip3 install RPi.GPIO
# pip3 install adafruit-circuitpython-dht
# pip3 install RPLCD

try:
    import RPi.GPIO as GPIO
    import board
    import adafruit_dht
    from RPLCD.i2c import CharLCD
except (RuntimeError, ImportError):
    import mock_gpio as GPIO
    import mock_board as board
    import mock_adafruit_dht as adafruit_dht
    from mock_rplcd import CharLCD
import time
import threading
import csv
import os
import json
from flask import Flask, jsonify, render_template
from datetime import datetime

# =============================
# LCD Configuration
# =============================
app = Flask(__name__)
SCRIPT_START_TIME = time.time()

# =============================
# Web Server Routes
# =============================
@app.route('/api/status', methods=['GET'])
def get_status():
    """Returns the current status of the curing process."""
    stage_name = list(CURING_STAGES.keys())[current_stage_index]
    setpoints = CURING_STAGES[stage_name]
    target_temp = auto_target_temp if current_mode == "AUTO" else 0.0

    remaining_seconds = 0
    if current_mode == "AUTO":
        elapsed_since_start = time.time() - stage_start_time
        remaining_seconds = 3600 - (elapsed_since_start % 3600)

    uptime = time.time() - SCRIPT_START_TIME
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    status = {
        "mode": current_mode,
        "stage": stage_name,
        "temperature": temperature,
        "humidity": humidity,
        "target_temp": target_temp,
        "max_temp": setpoints["max_temp"],
        "fan_on": fan_on,
        "dehumidifier_on": dehumidifier_on,
        "fan_on_2": fan_on,
        "dehumidifier_on_2": dehumidifier_on,
        "buzzer_on": buzzer_on,
        "remaining_seconds": remaining_seconds,
        "uptime": uptime,
        "current_time": current_time
    }
    return jsonify(status)


@app.route('/api/mode', methods=['POST'])
def set_mode():
    """Sets the curing mode."""
    global current_mode
    current_mode = "MANUAL" if current_mode == "AUTO" else "AUTO"
    return jsonify({"mode": current_mode})

@app.route('/api/stage', methods=['POST'])
def set_stage():
    """Sets the curing stage."""
    global current_stage_index
    current_stage_index = (current_stage_index + 1) % len(list(CURING_STAGES.keys()))
    return jsonify({"stage": list(CURING_STAGES.keys())[current_stage_index]})

@app.route('/api/fan', methods=['POST'])
def toggle_fan():
    """Toggles the fan."""
    global fan_on
    fan_on = not fan_on
    return jsonify({"fan_on": fan_on})

@app.route('/api/dehumidifier', methods=['POST'])
def toggle_dehumidifier():
    """Toggles the dehumidifier."""
    global dehumidifier_on
    dehumidifier_on = not dehumidifier_on
    return jsonify({"dehumidifier_on": dehumidifier_on})

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')

lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1,
cols=20, rows=4, dotsize=8)

# =============================
# Pin definitions (BCM numbering)
# =============================
DHT_PIN = board.D4 # DHT sensor data pin connected to GPIO 4
FAN_PIN = 17
DEHUMIDIFIER_PIN = 27
FAN_PIN_2 = 22
DEHUMIDIFIER_PIN_2 = 23
BUZZER_PIN = 24

# Button definitions
MODE_BUTTON_PIN = 5
STAGE_BUTTON_PIN = 6
FAN_BUTTON_PIN = 13
DEHUMIDIFIER_BUTTON_PIN = 19

# LED Indicator definitions
YELLOWING_LED_PIN = 16
LEAF_DRYING_LED_PIN = 20
MIDRIB_DRYING_LED_PIN = 21
ORDERING_LED_PIN = 26

AUTO_MODE_LED_PIN = 12
MANUAL_MODE_LED_PIN = 25

# =============================
# Relay configuration
# =============================
# Set this to True if your relays are active LOW (most common)
# Set to False if active HIGH
RELAY_ACTIVE_LOW = False

# =============================
# Curing stages configuration
# =============================
CURING_STAGES = {
    "YELLOWING": {"min_temp": 27.0, "max_temp": 40.0, "humidity": 85.0, "ramp_fan_on": False},
    "LEAF_DRYING": {"min_temp": 45.0, "max_temp": 55.0, "humidity": 70.0, "ramp_fan_on": True},
    "MIDRIB_DRYING": {"min_temp": 60.0, "max_temp": 70.0, "humidity": 50.0, "ramp_fan_on": True},
    "ORDERING": {"min_temp": 23.0, "max_temp": 27.0, "humidity": 80.0, "ramp_fan_on": False},
}

# =============================
# State persistence
# =============================
STATE_FILE = "curing_state.json"

def save_state():
    """Saves the current state to a file."""
    state = {
        "current_mode": current_mode,
        "current_stage_index": current_stage_index,
        "auto_target_temp": auto_target_temp,
        "stage_start_time": stage_start_time,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def load_state():
    """Loads the state from a file."""
    global current_mode, current_stage_index, auto_target_temp, stage_start_time
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            current_mode = state.get("current_mode", "AUTO")
            current_stage_index = state.get("current_stage_index", 0)
            auto_target_temp = state.get("auto_target_temp", 0.0)
            stage_start_time = state.get("stage_start_time", time.time())
    except FileNotFoundError:
        pass # No state file yet, start with defaults

# =============================
# State variables
# =============================
current_mode = "AUTO" # "AUTO" or "MANUAL"
current_stage_index = 0
stage_start_time = 0
stage_start_temp = 0.0
auto_target_temp = 0.0
fan_on = False
dehumidifier_on = False
buzzer_on = False
temperature = 0.0
humidity = 0.0

# =============================
# GPIO Setup
# =============================
def setup_gpio():
    """Sets up the GPIO pins."""
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(FAN_PIN, GPIO.OUT)
    GPIO.setup(DEHUMIDIFIER_PIN, GPIO.OUT)
    GPIO.setup(FAN_PIN_2, GPIO.OUT)
    GPIO.setup(DEHUMIDIFIER_PIN_2, GPIO.OUT)
    GPIO.setup(BUZZER_PIN, GPIO.OUT)
    GPIO.setup(MODE_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(STAGE_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(FAN_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(DEHUMIDIFIER_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Output pins for LEDs
    GPIO.setup(YELLOWING_LED_PIN, GPIO.OUT)
    GPIO.setup(LEAF_DRYING_LED_PIN, GPIO.OUT)
    GPIO.setup(MIDRIB_DRYING_LED_PIN, GPIO.OUT)
    GPIO.setup(ORDERING_LED_PIN, GPIO.OUT)
    GPIO.setup(AUTO_MODE_LED_PIN, GPIO.OUT)
    GPIO.setup(MANUAL_MODE_LED_PIN, GPIO.OUT)

    # Initialize all relays OFF
    relay_off(FAN_PIN)
    relay_off(DEHUMIDIFIER_PIN)
    relay_off(FAN_PIN_2)
    relay_off(DEHUMIDIFIER_PIN_2)
    GPIO.output(BUZZER_PIN, GPIO.LOW)

    # Initialize all LEDs OFF
    GPIO.output(YELLOWING_LED_PIN, GPIO.LOW)
    GPIO.output(LEAF_DRYING_LED_PIN, GPIO.LOW)
    GPIO.output(MIDRIB_DRYING_LED_PIN, GPIO.LOW)
    GPIO.output(ORDERING_LED_PIN, GPIO.LOW)
    GPIO.output(AUTO_MODE_LED_PIN, GPIO.LOW)
    GPIO.output(MANUAL_MODE_LED_PIN, GPIO.LOW)

# =============================
# Relay Control Functions
# =============================
def relay_on(pin):
    """Turns ON the relay depending on the relay logic type."""
    if RELAY_ACTIVE_LOW:
        GPIO.output(pin, GPIO.LOW)
    else:
        GPIO.output(pin, GPIO.HIGH)

def relay_off(pin):
    """Turns OFF the relay depending on the relay logic type."""
    if RELAY_ACTIVE_LOW:
        GPIO.output(pin, GPIO.HIGH)
    else:
        GPIO.output(pin, GPIO.LOW)

def control_buzzer(buzzer_on):
    """Controls the buzzer."""
    if buzzer_on:
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
    else:
        GPIO.output(BUZZER_PIN, GPIO.LOW)

def update_relays(dehumidifier_on, fan_on):
    """Updates all relay states."""
    if dehumidifier_on:
        relay_on(DEHUMIDIFIER_PIN)
        relay_on(DEHUMIDIFIER_PIN_2)
    else:
        relay_off(DEHUMIDIFIER_PIN)
        relay_off(DEHUMIDIFIER_PIN_2)

    if fan_on:
        relay_on(FAN_PIN)
        relay_on(FAN_PIN_2)
    else:
        relay_off(FAN_PIN)
        relay_off(FAN_PIN_2)

# =============================
# LCD Update Function
# =============================
def log_data(timestamp, temp, hum, stage, mode, fan_on, dehum_on, fan_on_2, dehum_on_2, alarm_on):
    """Logs the current state to a CSV file."""
    log_file = 'curing_log.csv'
    file_exists = os.path.isfile(log_file)
    with open(log_file, 'a', newline='') as csvfile:
        fieldnames = ['timestamp', 'temperature', 'humidity', 'stage', 'mode', 'fan_on', 'dehumidifier_on', 'fan_on_2', 'dehumidifier_on_2', 'alarm_on']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow({
            'timestamp': timestamp,
            'temperature': temp,
            'humidity': hum,
            'stage': stage,
            'mode': mode,
            'fan_on': fan_on,
            'dehumidifier_on': dehum_on,
            'fan_on_2': fan_on_2,
            'dehumidifier_on_2': dehum_on_2,
            'alarm_on': alarm_on
        })

def update_leds(stage_name, mode):
    """Updates the LED indicators for stage and mode."""
    # Turn off all stage LEDs first
    GPIO.output(YELLOWING_LED_PIN, GPIO.LOW)
    GPIO.output(LEAF_DRYING_LED_PIN, GPIO.LOW)
    GPIO.output(MIDRIB_DRYING_LED_PIN, GPIO.LOW)
    GPIO.output(ORDERING_LED_PIN, GPIO.LOW)

    # Turn on the current stage LED
    if stage_name == "YELLOWING":
        GPIO.output(YELLOWING_LED_PIN, GPIO.HIGH)
    elif stage_name == "LEAF_DRYING":
        GPIO.output(LEAF_DRYING_LED_PIN, GPIO.HIGH)
    elif stage_name == "MIDRIB_DRYING":
        GPIO.output(MIDRIB_DRYING_LED_PIN, GPIO.HIGH)
    elif stage_name == "ORDERING":
        GPIO.output(ORDERING_LED_PIN, GPIO.HIGH)

    # Update mode LEDs
    if mode == "AUTO":
        GPIO.output(AUTO_MODE_LED_PIN, GPIO.HIGH)
        GPIO.output(MANUAL_MODE_LED_PIN, GPIO.LOW)
    else: # MANUAL
        GPIO.output(AUTO_MODE_LED_PIN, GPIO.LOW)
        GPIO.output(MANUAL_MODE_LED_PIN, GPIO.HIGH)

def update_lcd(temp, hum, stage, mode, fan_on, dehum_on):
    """Formats and writes the current status to the LCD screen."""
    lcd.home()

    # Line 1: Temperature and Mode
    lcd.write_string(f"Temp: {temp:.1f}C")
    lcd.write_string(f" Mode:{mode[:3]}")

    # Line 2: Humidity
    lcd.crlf()
    lcd.write_string(f"Humidity: {hum:.1f} %")

    # Line 3: Stage
    lcd.crlf()
    lcd.write_string(f"Stage: {stage}")

    # Line 4: Actuator Status
    lcd.crlf()
    fan_str = "F1" if fan_on else "- "
    dehum_str = "D1" if dehum_on else "- "
    fan_str_2 = "F2" if fan_on else "- "
    dehum_str_2 = "D2" if dehum_on else "- "
    lcd.write_string(f"Status: {fan_str}{dehum_str}{fan_str_2}{dehum_str_2}")

# =============================
# Main Control Loop
# =============================
def main():
    """Main loop for the tobacco curing controller."""
    global current_mode, current_stage_index, stage_start_time, fan_on, dehumidifier_on, buzzer_on, temperature, humidity, stage_start_temp, auto_target_temp

    setup_gpio()

    # Splash screen
    lcd.clear()
    lcd.write_string("Tobacco Curing Sys")
    lcd.crlf()
    lcd.write_string("Initializing...")
    time.sleep(3)
    lcd.clear()

    dht_device = adafruit_dht.DHT22(DHT_PIN)

    # Perform an initial sensor reading to ensure we start with valid data
    print("Getting initial sensor reading...")
    lcd.write_string("Reading sensor...")
    temperature = None
    while temperature is None:
        try:
            temperature = dht_device.temperature
            humidity = dht_device.humidity
            if temperature is None:
                print("Failed to get initial DHT22 reading, retrying...")
                lcd.clear()
                lcd.write_string("Sensor fail!")
                lcd.crlf()
                lcd.write_string("Retrying...")
                time.sleep(2)
        except RuntimeError as error:
            print(f"Initial sensor read error: {error.args[0]}. Retrying...")
            lcd.clear()
            lcd.write_string("Sensor error!")
            lcd.crlf()
            lcd.write_string("Retrying...")
            time.sleep(2)
    print(f"Initial reading: Temp={temperature:.1f}C, Hum={humidity:.1f}%")
    lcd.clear()
    lcd.write_string("Sensor OK!")
    time.sleep(2)
    lcd.clear()

    stage_keys = list(CURING_STAGES.keys())
    last_mode_press = 0
    last_stage_press = 0
    last_fan_press = 0
    last_dehumidifier_press = 0

    load_state() # Load the last saved state

    # Initialize temperature state variables
    stage_start_temp = temperature
    if stage_start_time == 0:
        stage_start_time = time.time()
    auto_target_temp = stage_start_temp + 1.0 if auto_target_temp == 0.0 else auto_target_temp

    try:
        lcd.clear()
        while True:
            # Button reading
            mode_button_pressed = not GPIO.input(MODE_BUTTON_PIN)
            stage_button_pressed = not GPIO.input(STAGE_BUTTON_PIN)
            fan_button_pressed = not GPIO.input(FAN_BUTTON_PIN)
            dehumidifier_button_pressed = not GPIO.input(DEHUMIDIFIER_BUTTON_PIN)

            # Mode switching
            if mode_button_pressed and (time.time() - last_mode_press > 0.2):
                last_mode_press = time.time()
                current_mode = "MANUAL" if current_mode == "AUTO" else "AUTO"
                print(f"Switched to {current_mode} mode")

            # Stage advancement
            if stage_button_pressed and (time.time() - last_stage_press > 0.2):
                last_stage_press = time.time()
                current_stage_index = (current_stage_index + 1) % len(stage_keys)
                stage_start_time = time.time()
                stage_name = stage_keys[current_stage_index]
                setpoints = CURING_STAGES[stage_name]
                if current_mode == "AUTO":
                    stage_start_temp = temperature if temperature is not None else setpoints["min_temp"]
                print(f"Manually advanced to stage: {stage_keys[current_stage_index]}")

            # Sensor reading
            try:
                temperature = dht_device.temperature
                humidity = dht_device.humidity
                if temperature is not None and humidity is not None:
                    stage_name = stage_keys[current_stage_index]
                    setpoints = CURING_STAGES[stage_name]

                    # Stage transition and control logic
                    if current_mode == "AUTO":
                        # Calculate the elapsed time in hours, rounded down to the nearest hour
                        elapsed_hours = int((time.time() - stage_start_time) / 3600)

                        # The target temperature starts at initial_temp + 1 and increases by 1°C each hour thereafter
                        auto_target_temp = stage_start_temp + 1 + elapsed_hours

                        # Determine if we are in the ramp-up phase or maintenance phase
                        if auto_target_temp < setpoints["max_temp"]:
                            # Ramp-up phase
                            fan_on = setpoints.get("ramp_fan_on", False)

                            # Dehumidifier controls temperature based on ramping target
                            if temperature < auto_target_temp - 2:
                                dehumidifier_on = True
                            elif temperature > auto_target_temp + 2:
                                dehumidifier_on = False
                        else:
                            # Maintenance phase (target temperature is max_temp)
                            auto_target_temp = setpoints["max_temp"]

                            # Hysteresis control for both fan and dehumidifier
                            if temperature < auto_target_temp - 2:
                                dehumidifier_on = True
                                fan_on = True
                            elif temperature > auto_target_temp + 2:
                                dehumidifier_on = False
                                fan_on = False
                    else: # MANUAL mode
                        if fan_button_pressed and (time.time() - last_fan_press > 0.2):
                            last_fan_press = time.time()
                            fan_on = not fan_on

                        if dehumidifier_button_pressed and (time.time() - last_dehumidifier_press > 0.2):
                            last_dehumidifier_press = time.time()
                            dehumidifier_on = not dehumidifier_on

                    # Update relays (fan, dehumidifier)
                    update_relays(dehumidifier_on, fan_on)

                    # Update LED indicators
                    update_leds(stage_name, current_mode)

                    # Temperature alarm
                    buzzer_on = not (setpoints["min_temp"] <= temperature <= setpoints["max_temp"])
                    control_buzzer(buzzer_on)

                    # Update LCD display
                    update_lcd(temperature, humidity, stage_name, current_mode, fan_on, dehumidifier_on)

                    # Console feedback
                    print(f"Stage: {stage_name}, Mode: {current_mode}, Temp: {temperature:.1f}°C, Hum: {humidity:.1f}%")
                    print(f"Dehumidifier: {'ON' if dehumidifier_on else 'OFF'}, Fan: {'ON' if fan_on else 'OFF'}")

                    # Log data
                    log_data(time.time(), temperature, humidity, stage_name, current_mode, fan_on, dehumidifier_on, fan_on, dehumidifier_on, buzzer_on)

            except RuntimeError as error:
                print(error.args[0])

            save_state() # Periodically save the state
            time.sleep(0.5)
    finally:
        save_state() # Save state on exit
        lcd.clear()
        GPIO.cleanup()

# =============================
# Entry point
# =============================
if __name__ == "__main__":
    # Start the Flask app in a separate thread
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000))
    flask_thread.daemon = True
    flask_thread.start()

    main()
