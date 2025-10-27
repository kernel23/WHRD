#include <Wire.h>
#include <SPI.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>

#define SEALEVELPRESSURE_HPA (1013.25)

Adafruit_BME280 bme; // I2C

// Set your desired temperature and humidity setpoints
float temperatureSetpoint = 25.0; // Celsius
float humiditySetpoint = 60.0; // %

// Define pins for your control devices (e.g., relays for a heater and a humidifier)
#define HEATER_PIN 16
#define HUMIDIFIER_PIN 17


void setup() {
  Serial.begin(9600);

  bool status;

  // default settings
  status = bme.begin();
  if (!status) {
    Serial.println("Could not find a valid BME280 sensor, check wiring!");
    while (1);
  }

  pinMode(HEATER_PIN, OUTPUT);
  pinMode(HUMIDIFIER_PIN, OUTPUT);

  digitalWrite(HEATER_PIN, LOW);
  digitalWrite(HUMIDIFIER_PIN, LOW);
}

void loop() {
  float temperature = bme.readTemperature();
  float humidity = bme.readHumidity();

  if (isnan(temperature) || isnan(humidity)) {
    Serial.println(F("Failed to read from BME280 sensor!"));
    return;
  }

  Serial.print(F("Temperature: "));
  Serial.print(temperature);
  Serial.println(F("°C"));

  // Temperature control logic
  if (temperature < temperatureSetpoint) {
    digitalWrite(HEATER_PIN, HIGH); // Turn on heater
    Serial.println("Heater ON");
  } else {
    digitalWrite(HEATER_PIN, LOW); // Turn off heater
    Serial.println("Heater OFF");
  }

  Serial.print(F("Humidity: "));
  Serial.print(humidity);
  Serial.println(F("%"));

  // Humidity control logic
  if (humidity < humiditySetpoint) {
    digitalWrite(HUMIDIFIER_PIN, HIGH); // Turn on humidifier
    Serial.println("Humidifier ON");
  } else {
    digitalWrite(HUMIDIFIER_PIN, LOW); // Turn off humidifier
    Serial.println("Humidifier OFF");
  }

  delay(2000);
}
