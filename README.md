# "Vučko" — Autonomni ESP32 Mars Rover

Autonomno mikrokontrolersko vozilo bazirano na ESP32 mikrokontroleru i MicroPythonu. Sistem koristi MQTT protokol za upravljanje i telemetriju, MPU6050 žiroskop za održavanje pravca, te MCP arhitekturu i Hermes Agenta na Raspberry Pi 5 za AI upravljanje putem prirodnog jezika.

---

## Demo Video i Dokumentacija

* **YouTube Video:** [Pogledajte demonstraciju rada rovera](https://youtu.be/92EGSl7-Scg)
* **Dokumentacija:** Detaljan opis arhitekture i funkcionalnosti nalazi se u [`docs/dokumentacija projekta.pdf`](./docs/dokumentacija%20projekta.pdf)

---

## Tehnologije i Komponente

* **Mikrokontroler:** ESP32 (MicroPython)
* **Upravljanje (AI):** Raspberry Pi 5, MCP Server, Hermes Agent, Telegram Bot
* **Komunikacija:** Wi-Fi, MQTT broker
* **Pogon:** 4WD DC motori, L298N H-most drajver, SG90 servo motor
* **Senzori:** MPU6050 (žiroskop za stabilizaciju), HC-SR04 (ultrasonični senzor za prepreke), DHT11 (temperatura i vlaga)

---

## Glavne Funkcionalnosti

* **Stabilizacija pravca:** Automatska PWM korekcija brzine motora pomoću žiroskopa.
* **Izbjegavanje prepreka:** Skeniranje terena ultrazvučnim senzorom.
* **Mapiranje terena:** Generisanje 2D matrice temperature i vlage.
* **Upravljanje prirodnim jezikom:** Izvršavanje komandi iz Telegram chata putem AI agenta.
