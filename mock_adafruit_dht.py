import time

class DHT22:
    def __init__(self, pin):
        time.sleep(2) # Simulate sensor initialization
        self.temperature = 25.0
        self.humidity = 60.0
