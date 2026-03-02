import os
import requests
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
URL = "https://openapi.koreainvestment.com:9443" # real account server

def get_token():
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": SECRET_KEY
    }
    path = "oauth2/tokenP"
    res = requests.post(f"{URL}/{path}", headers=headers, json=body)

    if res.status_code == 200:
        print("Access Success. You Get Token")
        print(f"Token: {res.json()['access_token'][:20]}...")
    else:
        print(f"Access Failed : {res.text}")

if __name__ == "__main__":
    get_token()
