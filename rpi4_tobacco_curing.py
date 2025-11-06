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
from flask import Flask, jsonify, render_template_string

# =============================
# LCD Configuration
# =============================
app = Flask(__name__)

# =============================
# Web Server Routes
# =============================
@app.route('/api/status', methods=['GET'])
def get_status():
    """Returns the current status of the curing process."""
    stage_name = list(CURING_STAGES.keys())[current_stage_index]
    setpoints = CURING_STAGES[stage_name]
    status = {
        "mode": current_mode,
        "stage": stage_name,
        "temperature": temperature,
        "humidity": humidity,
        "target_temp": setpoints["temp"],
        "min_temp": setpoints["min_temp"],
        "max_temp": setpoints["max_temp"],
        "fan_on": fan_on,
        "dehumidifier_on": dehumidifier_on,
        "buzzer_on": buzzer_on
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
    return render_template_string(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Tobacco Curing Control</title>
            <style>
                body { font-family: sans-serif; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .status { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
                .status-item { padding: 10px; border: 1px solid #ccc; border-radius: 5px; }
                .controls { margin-top: 20px; }
                .controls button { padding: 10px 20px; font-size: 16px; cursor: pointer; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Tobacco Curing Control</h1>
                <div class="status">
                    <div class="status-item"><strong>Mode:</strong> <span id="mode"></span></div>
                    <div class="status-item"><strong>Stage:</strong> <span id="stage"></span></div>
                    <div class="status-item"><strong>Temperature:</strong> <span id="temperature"></span> &deg;C</div>
                    <div class="status-item"><strong>Target Temp:</strong> <span id="target_temp"></span> &deg;C</div>
                    <div class="status-item"><strong>Min Temp:</strong> <span id="min_temp"></span> &deg;C</div>
                    <div class="status-item"><strong>Max Temp:</strong> <span id="max_temp"></span> &deg;C</div>
                    <div class="status-item"><strong>Humidity:</strong> <span id="humidity"></span> %</div>
                    <div class="status-item"><strong>Fan:</strong> <span id="fan_on"></span></div>
                    <div class="status-item"><strong>Dehumidifier:</strong> <span id="dehumidifier_on"></span></div>
                    <div class="status-item"><strong>Buzzer:</strong> <span id="buzzer_on"></span></div>
                </div>
                <div class="controls">
                    <button id="toggle-mode">Toggle Mode</button>
                    <button id="next-stage" disabled>Next Stage</button>
                    <button id="toggle-fan" disabled>Toggle Fan</button>
                    <button id="toggle-dehumidifier" disabled>Toggle Dehumidifier</button>
                </div>
            </div>
            <script>
                function updateStatus() {
                    fetch('/api/status')
                        .then(response => response.json())
                        .then(data => {
                            document.getElementById('mode').textContent = data.mode;
                            document.getElementById('stage').textContent = data.stage;
                            document.getElementById('temperature').textContent = data.temperature.toFixed(1);
                            document.getElementById('target_temp').textContent = data.target_temp.toFixed(1);
                            document.getElementById('min_temp').textContent = data.min_temp.toFixed(1);
                            document.getElementById('max_temp').textContent = data.max_temp.toFixed(1);
                            document.getElementById('humidity').textContent = data.humidity.toFixed(1);
                            document.getElementById('fan_on').textContent = data.fan_on ? 'ON' : 'OFF';
                            document.getElementById('dehumidifier_on').textContent = data.dehumidifier_on ? 'ON' : 'OFF';
                            document.getElementById('buzzer_on').textContent = data.buzzer_on ? 'ON' : 'OFF';

                            // Disable manual controls in AUTO mode
                            const isAutoMode = data.mode === 'AUTO';
                            document.getElementById('next-stage').disabled = isAutoMode;
                            document.getElementById('toggle-fan').disabled = isAutoMode;
                            document.getElementById('toggle-dehumidifier').disabled = isAutoMode;
                        });
                }

                document.getElementById('toggle-mode').addEventListener('click', () => {
                    fetch('/api/mode', { method: 'POST' })
                        .then(() => updateStatus());
                });

                document.getElementById('next-stage').addEventListener('click', () => {
                    fetch('/api/stage', { method: 'POST' })
                        .then(() => updateStatus());
                });

                document.getElementById('toggle-fan').addEventListener('click', () => {
                    fetch('/api/fan', { method: 'POST' })
                        .then(() => updateStatus());
                });

                document.getElementById('toggle-dehumidifier').addEventListener('click', () => {
                    fetch('/api/dehumidifier', { method: 'POST' })
                        .then(() => updateStatus());
                });

                setInterval(updateStatus, 2000);
                updateStatus();
            </script>
        </body>
        </html>
        """
    )

lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1,
cols=20, rows=4, dotsize=8)

# =============================
# Pin definitions (BCM numbering)
# =============================
DHT_PIN = board.D4 # DHT sensor data pin connected to GPIO 4
FAN_PIN = 17
DEHUMIDIFIER_PIN = 27
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
    "YELLOWING": {"temp": 35.0, "min_temp": 33.0, "max_temp": 37.0, "humidity": 85.0, "duration_hours": 48},
    "LEAF_DRYING": {"temp": 46.0, "min_temp": 44.0, "max_temp": 48.0, "humidity": 70.0, "duration_hours": 24},
    "MIDRIB_DRYING": {"temp": 65.0, "min_temp": 63.0, "max_temp": 67.0, "humidity": 50.0, "duration_hours": 24},
    "ORDERING": {"temp": 25.0, "min_temp": 23.0, "max_temp": 27.0, "humidity": 80.0, "duration_hours": 12},
}

# =============================
# State variables
# =============================
current_mode = "AUTO" # "AUTO" or "MANUAL"
current_stage_index = 0
stage_start_time = 0
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
    else:
        relay_off(DEHUMIDIFIER_PIN)

    if fan_on:
        relay_on(FAN_PIN)
    else:
        relay_off(FAN_PIN)

# =============================
# LCD Update Function
# =============================
def log_data(timestamp, temp, hum, stage, mode, fan_on, dehum_on, alarm_on):
    """Logs the current state to a CSV file."""
    log_file = 'curing_log.csv'
    file_exists = os.path.isfile(log_file)
    with open(log_file, 'a', newline='') as csvfile:
        fieldnames = ['timestamp', 'temperature', 'humidity', 'stage', 'mode', 'fan_on', 'dehumidifier_on', 'alarm_on']
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
    lcd.clear()

    # Line 1: Temperature and Mode
    lcd.write_string(f"Temp: {temp:.1f} C")
    lcd.cursor_pos = (0, 14)
    lcd.write_string(f"M:{mode[:3]}")

    # Line 2: Humidity
    lcd.crlf()
    lcd.write_string(f"Humidity: {hum:.1f} %")

    # Line 3: Stage
    lcd.crlf()
    lcd.write_string(f"Stage: {stage}")

    # Line 4: Actuator Status
    lcd.crlf()
    fan_str = "F" if fan_on else "-"
    dehum_str = "D" if dehum_on else "-"
    lcd.write_string(f"Status: {fan_str}{dehum_str}")

# =============================
# Main Control Loop
# =============================
def main():
    """Main loop for the tobacco curing controller."""
    global current_mode, current_stage_index, stage_start_time, fan_on, dehumidifier_on, buzzer_on, temperature, humidity

    setup_gpio()
    dht_device = adafruit_dht.DHT22(DHT_PIN)
    stage_keys = list(CURING_STAGES.keys())
    stage_start_time = time.time()
    last_mode_press = 0
    last_stage_press = 0
    last_fan_press = 0
    last_dehumidifier_press = 0

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

            # Sensor reading
            try:
                temperature = dht_device.temperature
                humidity = dht_device.humidity
                if temperature is not None and humidity is not None:
                    stage_name = stage_keys[current_stage_index]
                    setpoints = CURING_STAGES[stage_name]

                    # Stage transition and control logic
                    if current_mode == "AUTO":
                        stage_duration_seconds = setpoints["duration_hours"] * 3600
                        if time.time() - stage_start_time > stage_duration_seconds:
                            current_stage_index = (current_stage_index + 1) % len(stage_keys)
                            stage_start_time = time.time()
                            print(f"Auto-advancing to stage: {stage_keys[current_stage_index]}")

                        dehumidifier_on = humidity > setpoints["humidity"]
                        fan_on = dehumidifier_on or (stage_name == "LEAF_DRYING")
                    else: # MANUAL mode
                        if stage_button_pressed and (time.time() - last_stage_press > 0.2):
                            last_stage_press = time.time()
                            current_stage_index = (current_stage_index + 1) % len(stage_keys)
                            stage_start_time = time.time()
                            print(f"Manually advanced to stage: {stage_keys[current_stage_index]}")

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
                    log_data(time.time(), temperature, humidity, stage_name, current_mode, fan_on, dehumidifier_on, buzzer_on)

            except RuntimeError as error:
                print(error.args[0])

            time.sleep(0.5)
    finally:
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
