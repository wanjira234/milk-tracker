"""Send ONE test SMS through Africa's Talking and show exactly what came back.

    python -m src.sms_check +254712345678

Use it to check your keys before the daily job runs. With AT_USERNAME=sandbox nothing
reaches a real phone: the message appears in the simulator on the Africa's Talking
website (Sandbox > SMS > Launch Simulator), and the number you type must be the one
you entered in that simulator.
"""
import os
import sys

from dotenv import load_dotenv

from src.sms import SmsError, make_client, send_sms

load_dotenv()


def main(argv):
    if len(argv) != 2:
        return "usage: python -m src.sms_check +2547XXXXXXXX"
    username = os.environ.get("AT_USERNAME", "")
    print(f"AT_USERNAME = {username or '(not set)'}   AT_API_KEY set: {bool(os.environ.get('AT_API_KEY'))}   AT_SENDER_ID = {os.environ.get('AT_SENDER_ID') or '(empty)'}")
    try:
        result = send_sms(argv[1], "Milk Tracker: test message. If you can read this, SMS works.", client=make_client())
    except SmsError as e:
        return f"Not sent: {e}"
    print(result)
    if result["ok"]:
        return "Accepted by Africa's Talking." + (" Check the simulator." if username == "sandbox" else "")
    return "Africa's Talking did not accept it. Read 'status' and 'detail' above."


if __name__ == "__main__":
    sys.exit(main(sys.argv))
