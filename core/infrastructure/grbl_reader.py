from typing import Dict
from typing import Optional
import serial
import re
import time


class GrblReader:
    """
    GRBL konfigurációs értékek olvasása (csak read-only).

    Lekért értékek:
        $100 - X steps/mm
        $101 - Y steps/mm
        $110 - X max rate
        $111 - Y max rate
        $120 - X acceleration
        $121 - Y acceleration
    """

    BAUDRATE = 115200

    @staticmethod
    def read_settings(port: str, timeout: float = 1.0) -> Optional[dict]:
        wanted = {3, 30, 31, 100, 101, 110, 111, 120, 121}
        required = {100, 101, 110, 111, 120, 121}
        result: dict[int, float] = {}

        with serial.Serial(port, GrblReader.BAUDRATE, timeout=timeout) as ser:

            ser.write(b"$$\n")
            ser.flush()

            deadline = time.time() + timeout
            while time.time() < deadline:
                raw = ser.readline()
                if not raw:
                    continue

                line = raw.decode(errors="ignore").strip()
                if not line:
                    continue

                print("RX:", line)

                if line.lower() == "ok":
                    break

                m = re.match(r"^\$(\d+)=([0-9.]+)", line)
                if not m:
                    continue

                key = int(m.group(1))
                if key in wanted:
                    result[key] = float(m.group(2))

        if not required.issubset(result.keys()):
            return None

        invert_mask = int(result.get(3, 0.0))
        laser: dict[str, float] = {
            "pwm_max": float(result.get(30, 1000.0)),
        }
        if 31 in result:
            laser["pwm_min"] = float(result[31])

        return {
            "x": {
                "steps_per_mm": result[100],
                "max_rate": result[110],
                "acceleration": result[120],
            },
            "y": {
                "steps_per_mm": result[101],
                "max_rate": result[111],
                "acceleration": result[121],
            },
            "laser": laser,
            "motion": {
                "invert_mask": invert_mask,
                "invert_x": bool(invert_mask & 1),
                "invert_y": bool(invert_mask & 2),
            },
        }
