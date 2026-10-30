# "Vučko" — Autonomous ESP32 Mars Rover

An autonomous microcontroller-based vehicle powered by an ESP32 microcontroller and MicroPython. The system utilizes the MQTT protocol for control and telemetry, an MPU6050 gyroscope for heading stabilization, and an MCP architecture running Hermes Agent on a Raspberry Pi 5 for natural language AI control.

---

## Demo Video & Documentation

- **YouTube Video:** [Watch the rover demonstration](https://youtu.be/92EGSl7-Scg)
- **Documentation:** Detailed architecture and functionality description can be found in [`docs/dokumentacija projekta.pdf`](./docs/dokumentacija%20projekta.pdf)

---

## Technologies & Components

- **Microcontroller:** ESP32 (MicroPython)
- **AI Control Layer:** Raspberry Pi 5, MCP Server, Hermes Agent, Telegram Bot
- **Communication:** Wi-Fi, MQTT Broker
- **Drive System:** 4WD DC motors, L298N H-bridge driver, SG90 servo motor
- **Sensors:** MPU6050 (gyroscope for stabilization), HC-SR04 (ultrasonic obstacle sensor), DHT11 (temperature and humidity)

---

## Key Features

- **Heading Stabilization:** Automatic PWM motor speed correction using gyroscope data.
- **Obstacle Avoidance:** Terrain scanning via an ultrasonic sensor.
- **Terrain Mapping:** Generation of a 2D temperature and humidity matrix.
- **Natural Language Control:** Execution of commands from a Telegram chat via an AI agent.
