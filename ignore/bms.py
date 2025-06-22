import time
import random
import sys
import paho.mqtt.client as mqtt
from datetime import datetime

BROKER = "localhost"
PORT = 1883
CLIENT_ID = "simulateur-banc"

client = mqtt.Client(
    client_id=CLIENT_ID, protocol=mqtt.MQTTv311, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)  # type: ignore


class BatterieSim:

    def __init__(self):
        self.voltage = random.uniform(48.0, 52.0)
        self.current = 0.0
        self.soc = random.randint(50, 90)
        self.temperature = random.uniform(25.0, 30.0)
        self.dischargedCapacity = random.uniform(0.0, 100.0)
        self.dischargedEnergy = random.uniform(0.0, 500.0)
        self.cellVoltages = [random.randint(3100, 3400) for _ in range(15)]
        self.nourriceSoc = [random.randint(50, 90) for _ in range(6)]
        self.heartbeat = 0
        self.averageNurseSOC = random.randint(50, 90)

    def update(self):
        self.voltage = min(max(self.voltage + random.uniform(-0.05, 0.05), 42.0), 54.5)
        self.current = min(max(self.current + random.uniform(-1.0, 1.0), -100.0), 100.0)
        self.soc = min(max(self.soc + random.randint(-1, 1), 0), 100)
        self.temperature = min(max(self.temperature + random.uniform(-0.2, 0.2), 20.0), 45.0)
        self.dischargedCapacity = min(self.dischargedCapacity + random.uniform(0.0, 0.5), 291.0)
        self.dischargedEnergy = min(self.dischargedEnergy + random.uniform(0.0, 10.0), 13968.0)
        self.heartbeat = (self.heartbeat + 1) % 256
        self.averageNurseSOC = min(max(self.averageNurseSOC + random.randint(-1, 1), 0), 100)

        for i in range(15):
            self.cellVoltages[i] = min(max(self.cellVoltages[i] + random.randint(-5, 5), 2800), 3650)

        for i in range(6):
            variation = random.randint(-4, 4)
            self.nourriceSoc[i] = min(max(self.nourriceSoc[i] + variation, 91), 97)

    def get_csv(self):
        max_cell = max(self.cellVoltages)
        min_cell = min(self.cellVoltages)
        max_cell_index = self.cellVoltages.index(max_cell) + 1
        min_cell_index = self.cellVoltages.index(min_cell) + 1

        data = [
            f"{self.voltage:.2f}",
            f"{self.current:.2f}",
            str(self.soc),
            f"{self.temperature:.1f}",
            str(max_cell_index),
            str(max_cell),
            str(min_cell_index),
            str(min_cell),
            f"{self.dischargedCapacity:.1f}",
            f"{self.dischargedEnergy:.1f}",
        ]
        data += [str(v) for v in self.cellVoltages]
        data.append(str(self.heartbeat))
        data.append(str(self.averageNurseSOC))
        return ",".join(data)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        pass
    else:
        pass


def main():
    if len(sys.argv) != 2:
        print("Erreur: vous devez fournir un argument (ex: banc1)")
        sys.exit(1)

    banc_name = sys.argv[1]  # exemple: "banc1"

    client.on_connect = on_connect
    client.connect(BROKER, PORT, 60)
    client.loop_start()  # MQTT en thread

    banc = BatterieSim()
    tick = 0

    try:
        while True:
            banc.update()
            topic_bms = f"{banc_name}/bms/data"
            client.publish(topic_bms, banc.get_csv(), qos=0)

            # Toutes les 4 secondes, publier les 6 nourrices
            if tick % 4 == 0:
                for n, soc in enumerate(banc.nourriceSoc):
                    topic_soc = f"{banc_name}/n{n+1}"
                    client.publish(topic_soc, str(soc), qos=0)

            tick += 1
            time.sleep(1)

    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
