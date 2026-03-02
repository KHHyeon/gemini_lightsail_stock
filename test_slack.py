# File: ~/my_bot/test_slack.py
import os
from slack_sdk import WebClient
from dotenv import load_dotenv

load_dotenv()

def send_test_message():
    client = WebClient(token=os.getenv("SLACK_TOKEN"))
    channel_id = os.getenv("SLACK_CHANNEL")
    
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            text="[System Check] Slack Integration Successful! Standing by for Trading Logic."
        )
        print("Log: Message sent successfully.")
    except Exception as e:
        print(f"Log: Error sending message - {e}")

if __name__ == "__main__":
    send_test_message()
