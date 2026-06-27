#!/usr/bin/env python3
"""
Traffic Light Controller - MQTT Relay Driver - Pi
==================================================
Replaces remote_rpi_gpio with MQTT switches.
Uses MQTT Discovery so HA auto-creates a single
"Traffic Light" device with three switch entities.

GPIO 17 - GREEN  relay (active-low)
GPIO 27 - YELLOW relay (active-low)
GPIO 22 - RED    relay (active-low)

HA sends ON/OFF to command topics; Pi drives relays
and publishes state back.
"""

import paho.mqtt.client as mqtt
from gpiozero import OutputDevice
from dotenv import load_dotenv
import threading
import logging
import signal
import json
import sys
import time
import os

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ---------------------------------------------
#  CONFIG
# ---------------------------------------------
MQTT_BROKER  = os.getenv("MQTT_BROKER",  "homeassistant.local")
MQTT_PORT    = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER    = os.getenv("MQTT_USER")
MQTT_PASS    = os.getenv("MQTT_PASS")

DEVICE_NAME  = os.getenv("DEVICE_NAME",  "traffic-light")
RECONNECT_S  = int(os.getenv("RECONNECT_S", "5"))
HEARTBEAT_S  = int(os.getenv("HEARTBEAT_S", "30"))

STATUS_TOPIC = f"home/{DEVICE_NAME}/status"

DISCOVERY_PREFIX = "homeassistant"

if not MQTT_USER or not MQTT_PASS:
    sys.exit("ERROR: MQTT_USER and MQTT_PASS must be set in .env")

# ---------------------------------------------
#  LOGGING
# ---------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/home/pi/traffic-light.log"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------
#  GPIO SETUP — active_high=False for active-low
#  relay board (matches invert_logic: true)
# ---------------------------------------------
LIGHTS = {
    "green":  OutputDevice(17, active_high=False, initial_value=False),
    "yellow": OutputDevice(27, active_high=False, initial_value=False),
    "red":    OutputDevice(22, active_high=False, initial_value=False),
}

# ---------------------------------------------
#  STATE
# ---------------------------------------------
_connected    = False
_shutdown_evt = threading.Event()

# ---------------------------------------------
#  HELPERS
# ---------------------------------------------
def light_state_str(name):
    return "ON" if LIGHTS[name].value else "OFF"

def publish_state(name):
    topic = f"home/{DEVICE_NAME}/{name}/state"
    state = light_state_str(name)
    client.publish(topic, state, qos=1, retain=True)
    log.info(f"Published '{state}' -> {topic}")

def publish_all_states():
    for name in LIGHTS:
        publish_state(name)

# ---------------------------------------------
#  MQTT DISCOVERY
# ---------------------------------------------
DEVICE_INFO = {
    "identifiers": [DEVICE_NAME],
    "name": "Traffic Light",
    "manufacturer": "142 West",
    "model": "MQTT Relay Controller",
}

def publish_discovery():
    for name in LIGHTS:
        config = {
            "name": name.capitalize(),
            "unique_id": f"{DEVICE_NAME}_{name}",
            "command_topic": f"home/{DEVICE_NAME}/{name}/set",
            "state_topic": f"home/{DEVICE_NAME}/{name}/state",
            "availability_topic": STATUS_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": DEVICE_INFO,
        }
        topic = f"{DISCOVERY_PREFIX}/switch/{DEVICE_NAME}/{name}/config"
        client.publish(topic, json.dumps(config), qos=1, retain=True)
        log.info(f"Published discovery -> {topic}")

# ---------------------------------------------
#  MQTT CALLBACKS
# ---------------------------------------------
def on_connect(client, userdata, flags, rc):
    global _connected
    if rc == 0:
        log.info(f"MQTT connected to {MQTT_BROKER}")
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        publish_discovery()
        client.subscribe(f"home/{DEVICE_NAME}/+/set", qos=1)
        log.info(f"Subscribed to home/{DEVICE_NAME}/+/set")
        publish_all_states()
        _connected = True
    else:
        log.warning(f"MQTT connect failed, rc={rc}")
        _connected = False

def on_disconnect(client, userdata, rc):
    global _connected
    log.warning(f"MQTT disconnected (rc={rc}), will retry in {RECONNECT_S}s")
    _connected = False

def on_message(client, userdata, msg):
    parts = msg.topic.split("/")
    if len(parts) != 4 or parts[3] != "set":
        return

    name = parts[2]
    if name not in LIGHTS:
        log.warning(f"Unknown light '{name}' in topic {msg.topic}")
        return

    payload = msg.payload.decode().strip().upper()
    if payload == "ON":
        LIGHTS[name].on()
        log.info(f"{name.upper()} -> ON")
    elif payload == "OFF":
        LIGHTS[name].off()
        log.info(f"{name.upper()} -> OFF")
    else:
        log.warning(f"Unknown payload '{payload}' on {msg.topic}")
        return

    publish_state(name)

# ---------------------------------------------
#  MQTT CLIENT
# ---------------------------------------------
client = mqtt.Client(client_id=DEVICE_NAME)
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect    = on_connect
client.on_disconnect = on_disconnect
client.on_message    = on_message

client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)

client.reconnect_delay_set(min_delay=RECONNECT_S, max_delay=60)

def mqtt_connect():
    while not _shutdown_evt.is_set():
        try:
            log.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}...")
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_start()
            return
        except Exception as e:
            log.error(f"Connection error: {e}. Retrying in {RECONNECT_S}s...")
            time.sleep(RECONNECT_S)

# ---------------------------------------------
#  HEARTBEAT — re-publish all states so HA
#  recovers after a restart
# ---------------------------------------------
def _heartbeat_loop():
    while not _shutdown_evt.is_set():
        _shutdown_evt.wait(HEARTBEAT_S)
        if _shutdown_evt.is_set():
            break
        if _connected:
            publish_all_states()
            log.debug("Heartbeat published")

# ---------------------------------------------
#  SIGNAL HANDLING (systemd stop / Ctrl-C)
# ---------------------------------------------
def handle_signal(sig, frame):
    log.info(f"Caught signal {sig}, shutting down cleanly...")
    _shutdown_evt.set()
    try:
        for name, dev in LIGHTS.items():
            dev.off()
        log.info("All relays OFF")
        client.publish(STATUS_TOPIC, "offline", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()
    except Exception:
        pass
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT,  handle_signal)

# ---------------------------------------------
#  MAIN
# ---------------------------------------------
if __name__ == "__main__":
    log.info(f"Starting {DEVICE_NAME}...")
    mqtt_connect()

    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    log.info("Running. Listening for HA commands.")
    _shutdown_evt.wait()
