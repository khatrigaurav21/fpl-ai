import os

import requests


def send_ntfy(message: str, title: str = "FPL Captain Pick") -> bool:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC not set; skipping notification.")
        return False
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": "default", "Tags": "soccer"},
        timeout=10,
    )
    resp.raise_for_status()
    return True
