# traffic-light

An MQTT-controlled traffic light relay driver for Home Assistant, running on a Raspberry Pi. Replaces the `remote_rpi_gpio` integration with MQTT switches for better reliability and no dependency on the `pigpiod` daemon.

## Hardware

| Light | GPIO | Relay |
|---|---|---|
| GREEN | GPIO 17 | Active-low |
| YELLOW | GPIO 27 | Active-low |
| RED | GPIO 22 | Active-low |

The relay board is assumed to be active-low (pin LOW = relay ON). This matches the `invert_logic: true` setting from the previous `remote_rpi_gpio` config.

---

## Requirements

- Raspberry Pi (any model with GPIO)
- Raspberry Pi OS
- Home Assistant with Mosquitto MQTT broker add-on
- 3-channel relay module (active-low, optoisolated preferred)

---

## 1. Flash & Configure Pi OS

Flash Raspberry Pi OS Lite using Raspberry Pi Imager. In the imager settings:
- Set hostname (e.g. `traffic-light`)
- Enable SSH
- Configure WiFi (if not using ethernet)

---

## 2. Install Dependencies

```bash
sudo apt update
sudo apt install python3-full python3-rpi.gpio git -y

python3 -m venv /home/pi/venv --system-site-packages
/home/pi/venv/bin/pip install paho-mqtt gpiozero python-dotenv
```

---

## 3. Install the Script

```bash
git clone https://github.com/142West/Traffic-Light.git
cd Traffic-Light

cp .env.example .env
nano .env        # set MQTT_USER and MQTT_PASS
chmod 600 .env
```

---

## 4. Configure Home Assistant

Remove the old `remote_rpi_gpio` switch config from `configuration.yaml`:

```yaml
# DELETE this block
switch:
  - platform: remote_rpi_gpio
    host: 10.1.13.57
    invert_logic: true
    ports:
      17: GREEN
      27: YELLOW
      22: RED
    scan_interval: 1
```

No replacement YAML is needed. The Pi publishes MQTT Discovery messages on connect, and HA automatically creates a **Traffic Light** device with three switch entities (Green, Yellow, Red). They appear under **Settings > Devices & Services > MQTT**.

---

## 5. Install as a System Service

```bash
sudo cp traffic-light.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable traffic-light
sudo systemctl start traffic-light
```

Check it's running:

```bash
sudo systemctl status traffic-light
```

View live logs:

```bash
journalctl -u traffic-light -f
```

---

## Configuration Reference

All config lives in `/home/pi/Traffic-Light/.env`. Only `MQTT_USER` and `MQTT_PASS` are required.

| Variable | Default | Description |
|---|---|---|
| `MQTT_USER` | -- | MQTT username (required) |
| `MQTT_PASS` | -- | MQTT password (required) |
| `MQTT_BROKER` | `homeassistant.local` | HA IP or hostname |
| `MQTT_PORT` | `1883` | MQTT port |
| `DEVICE_NAME` | `traffic-light` | Used in MQTT topics and logs |
| `RECONNECT_S` | `5` | Seconds between reconnect attempts |
| `HEARTBEAT_S` | `30` | Seconds between state re-publishes |

## MQTT Topics

| Topic | Direction | Payload | Description |
|---|---|---|---|
| `home/traffic-light/green/set` | HA -> Pi | `ON` / `OFF` | Command to switch relay |
| `home/traffic-light/green/state` | Pi -> HA | `ON` / `OFF` | Confirmed relay state |
| `home/traffic-light/yellow/set` | HA -> Pi | `ON` / `OFF` | Command to switch relay |
| `home/traffic-light/yellow/state` | Pi -> HA | `ON` / `OFF` | Confirmed relay state |
| `home/traffic-light/red/set` | HA -> Pi | `ON` / `OFF` | Command to switch relay |
| `home/traffic-light/red/state` | Pi -> HA | `ON` / `OFF` | Confirmed relay state |
| `home/traffic-light/status` | Pi -> HA | `online` / `offline` | Availability (LWT) |
