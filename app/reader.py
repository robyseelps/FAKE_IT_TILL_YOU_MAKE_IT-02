import os
import ssl
import time
import json
import base64
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.crud import get_email_record_by_email, set_email_status

# ==== Ваш n8n webhook ====
N8N_URL = "https://chadstudio.app.n8n.cloud/webhook/dea43c1c-ddbe-4549-8d41-5854692f8014"


# Gmail Scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# Should be changed to normal database like  REDIS
# Mails we already checked, so we do not process them twice
PROCESSED_FILE = "processed.json"


# ==========================
#   PROCESSED IDS
# ==========================
def load_processed_ids():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_processed_ids(processed_ids):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed_ids), f)


# ==========================
#   GMAIL AUTH
# ==========================
def get_credentials():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds


# ==========================
#   SEND EMAIL REPLY
# ==========================
def send_reply(service, original_msg, reply_text):
    headers = original_msg["payload"]["headers"]
    from_email = next((h["value"] for h in headers if h["name"] == "From"), "")
    thread_id = original_msg["threadId"]

    message_body = (
        f"From: me\n"
        f"To: {from_email}\n"
        f"Subject: Re: reply\n\n"
        f"{reply_text}"
    )

    raw = base64.urlsafe_b64encode(message_body.encode("utf-8")).decode("utf-8")

    service.users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": thread_id}
    ).execute()

    print(f"[✓] Sent reply '{reply_text}' to {from_email}")


# ==========================
#   EXTRACT BASE64 IMAGE
# ==========================
def extract_image_base64(parts):
    for part in parts:
        mime = part.get("mimeType", "")
        body = part.get("body", {})

        if "image" in mime and "attachmentId" in body:
            return body["attachmentId"]

    return None

#Extract text from mail
def extract_text_from_payload(payload):
    """Extract text/plain or text/html from any Gmail nested payload structure."""
    text_plain = None
    text_html = None

    def walk_parts(part):
        nonlocal text_plain, text_html

        mime = part.get("mimeType", "")
        body = part.get("body", {})

        # If message body contains text directly
        if "data" in body:
            decoded = base64.urlsafe_b64decode(body["data"]).decode("utf-8")
            if mime == "text/plain" and not text_plain:
                text_plain = decoded
            elif mime == "text/html" and not text_html:
                text_html = decoded

        # If there are nested parts
        for sub in part.get("parts", []):
            walk_parts(sub)

    walk_parts(payload)

    # Prefer plain text, fallback to HTML
    return text_plain or text_html or ""

def get_base64_attachment(service, msg_id, attachment_id):
    att = service.users().messages().attachments().get(
        userId="me",
        messageId=msg_id,
        id=attachment_id
    ).execute()
    return att["data"]  # already base64


# ==========================
#   PROCESS MESSAGE
# ==========================
def process_message(service, msg_id, processed_ids):
    msg = service.users().messages().get(
        userId="me",
        id=msg_id,
        format="full"
    ).execute()

    payload = msg["payload"]
    headers = payload.get("headers", [])
    parts = payload.get("parts", [])

    from_email = next((h["value"] for h in headers if h["name"] == "From"), "")
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")

    print("\n==========================")
    print(f"📨 NEW EMAIL: {subject}")
    print(f"👤 FROM: {from_email}")
    print("==========================")

    # ===== TEXT =====
    text_content = ""
    html_content = ""

    # for part in parts:
    #     mime = part.get("mimeType", "")
    #     if "data" in part.get("body", {}):
    #         if mime == "text/plain":
    #             text_content = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
    #         elif mime == "text/html":
    #             html_content = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
    #
    # if not text_content:
    #     text_content = html_content

    text_content = extract_text_from_payload(payload)
    print("📜 Extracted text:", text_content)
    # ===== IMAGE BASE64 =====
    image_attachment_id = extract_image_base64(parts)
    image_base64 = None

    if image_attachment_id:
        image_base64 = get_base64_attachment(service, msg_id, image_attachment_id)
        print("📷 Image extracted (base64)")
    else:
        print("📭 No image in email")

    # ===== CHECK DB =====
    record = get_email_record_by_email(from_email)

    if record:
        status = record["status"]
        print(f"📌 DB status: {status}")

        if status == "whitelist":
            print("✔ Whitelisted. Nothing to do.")
            return

        if status == "blacklist":
            print("❌ Blacklisted. Sending SCAM reply.")
            payload_n8n = {
                "textContent": text_content or "",
                "image": image_base64 or ""
            }
            response = requests.post(N8N_URL, json=payload_n8n)
            data = response.json()
            ai_result = data.get("output", {}).get("response")
            send_reply(service, msg, ai_result)
            return

    # ===== NEW EMAIL (not in DB) =====
    print("🆕 New sender. Sending to n8n AI classifier...")

    payload_n8n = {
        "textContent": text_content or "",
        "image": image_base64 or ""
    }

    print(payload_n8n["textContent"])

    response = requests.post(N8N_URL, json=payload_n8n)
    data = response.json()

    ai_result = data.get("output", {}).get("output")
    ai_response = data.get("output", {}).get("response")
    print(f"🤖 n8n classified sender as: {ai_result}")

    # ===== UPDATE DB =====
    if ai_result == "whitelist":
        set_email_status(from_email, "whitelist")
        print("✔ Added to whitelist")

    elif ai_result == "blacklist":
        set_email_status(from_email, "blacklist")
        print("❌ Added to blacklist")
        send_reply(service, msg, ai_response)

    else:
        print("⚠ Unknown classification. Marking as none.")
        set_email_status(from_email, "none")


# ==========================
#   MAIN LOOP
# ==========================
def watch_inbox():
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    processed_ids = load_processed_ids()

    print("📡 Watching inbox...")

    while True:
        try:
            result = service.users().messages().list(
                userId="me",
                labelIds=["INBOX"],
                q="newer_than:5d",
                maxResults=20
            ).execute()

            messages = result.get("messages", [])

            if messages:
                for msg in messages:
                    msg_id = msg["id"]

                    if msg_id in processed_ids:
                        continue

                    process_message(service, msg_id, processed_ids)

                    processed_ids.add(msg_id)
                    save_processed_ids(processed_ids)

            time.sleep(3)

        except HttpError as error:
            print(f"⚠ Gmail error: {error}")
            time.sleep(5)


if __name__ == "__main__":
    while True:
        try:
            watch_inbox()
        except ssl.SSLEOFError:
            print("⚠ SSL EOF Error — reconnecting in 2 seconds...")
            time.sleep(2)
            continue
        except Exception as e:
            print("⚠ Unexpected error:", e)
            print("Reconnecting in 5 seconds...")
            time.sleep(5)
            continue
