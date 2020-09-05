import paho.mqtt.client as mqtt
import json
import asyncio
import logging
import sys
import subprocess

_LOGGER = logging.getLogger(__name__)

COMMAND_TOPIC = "office/screen/display/set"
STATE_TOPIC = "office/screen/display/state"
DEFAULT_QOS = 0

ON_COMMAND = "xset -display :0.0 dpms force on"
OFF_COMMAND = "xset -display :0.0 dpms force off"
CHECK_COMMAND = "xset -display :0.0 q"

OFF_STATUS = "Monitor is Off"
ON_STATUS = "Monitor is On"


class ScreenManager:
    def __init__(self, loop):
        self.loop = loop
        self.connected = False
        self._paho_lock = asyncio.Lock()
        self.subscriptions: list = []
        self._mqttc: mqtt.Client = None
        self.conf = {}

        with open("config.json") as f:
            self.conf = json.loads(f.read())

        self.init_client()

    def init_client(self):
        self._mqttc = mqtt.Client()

        # Enable logging
        self._mqttc.enable_logger()

        username = self.conf.get("username")
        password = self.conf.get("password")
        if username is not None:
            self._mqttc.username_pw_set(username, password)

        self._mqttc.on_connect = self._mqtt_on_connect
        self._mqttc.on_disconnect = self._mqtt_on_disconnect
        self._mqttc.on_message = self._mqtt_on_message
        self._mqttc.on_publish = self._mqtt_on_callback
        self._mqttc.on_subscribe = self._mqtt_on_callback
        self._mqttc.on_unsubscribe = self._mqtt_on_callback

    async def run(self):
        await self.connect()

        await self.perform_subscription(COMMAND_TOPIC, DEFAULT_QOS)

        while True:
            self.reportStatus()
            await asyncio.sleep(60)

    async def connect(self):
        result = await self.loop.run_in_executor(
            None, self._mqttc.connect, self.conf["host"], self.conf["port"], 60
        )

        self._mqttc.loop_start()
        return result

    def _mqtt_on_connect(self, _mqttc, _userdata, _flags, result_code: int):
        if result_code != mqtt.CONNACK_ACCEPTED:
            _LOGGER.error(
                "Unable to connect to the MQTT broker: %s",
                mqtt.connack_string(result_code),
            )
            return

        self.connected = True
        _LOGGER.info(
            "Connected to MQTT server %s:%s (%s)",
            self.conf["host"],
            self.conf["port"],
            result_code,
        )

    def _mqtt_on_disconnect(self, _mqttc, _userdata, result_code: int):
        self.connected = False
        _LOGGER.warning(
            "Disconnected from MQTT server %s:%s (%s)",
            self.conf["host"],
            self.conf["port"],
            result_code,
        )

    def _mqtt_on_message(self, _mqttc, _userdata, msg):
        _LOGGER.info(
            "Received message on %s%s: %s",
            msg.topic,
            " (retained)" if msg.retain else "",
            msg.payload,
        )
        if msg.topic == COMMAND_TOPIC:
            if msg.payload == "ON":
                self.turnOnScreen()
            elif msg.payload == "OFF":
                self.turnOffScreen()

    def _mqtt_on_callback(self, _mqttc, _userdata, mid, _granted_qos=None):
        pass

    async def perform_subscription(self, topic: str, qos: int):
        async with self._paho_lock:
            result, mid = await self.loop.run_in_executor(
                None, self._mqttc.subscribe, topic, qos
            )
            _LOGGER.info("Subscribing to %s, mid: %s", topic, mid)
        return result

    def turnOnScreen(self):
        subprocess.check_output(ON_COMMAND.split(" "))
        self.reportStatus()

    def turnOffScreen(self):
        subprocess.check_output(OFF_COMMAND.split(" "))
        self.reportStatus()

    def reportStatus(self):
        status = self.getScreenStatus()
        asyncio.run_coroutine_threadsafe(
            self.publish(STATE_TOPIC, status, DEFAULT_QOS, True), self.loop
        )

    async def publish(self, topic: str, payload, qos: int, retain: bool):
        async with self._paho_lock:
            msg_info = await self.loop.run_in_executor(
                None, self._mqttc.publish, topic, payload, qos, retain
            )
            _LOGGER.info(
                "Transmitting message on %s: '%s', mid: %s",
                topic,
                payload,
                msg_info.mid,
            )

    def getScreenStatus(self):
        result = subprocess.check_output(CHECK_COMMAND.split(" "))
        if OFF_STATUS in result.decode():
            return "off"
        elif ON_STATUS in result.decode():
            return "on"
        else:
            return "unknown"


def main():
    loop = asyncio.get_event_loop()

    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    screen_manager = ScreenManager(loop=loop)
    loop.run_until_complete(screen_manager.run())


if __name__ == "__main__":
    main()
