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
from redisUtils import (
    get_redis_connection,
    is_processed as redis_is_processed,
    mark_processed as redis_mark_processed,
    load_from_file,
    save_to_file
)

# ==== n8n webhook ====
N8N_URL = "https://chadstudio.app.n8n.cloud/webhook/dea43c1c-ddbe-4549-8d41-5854692f8014"

# Gmail scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


# =====================================================
#  STORAGE WRAPPER (Redis or File Fallback)
# =====================================================

class ProcessedStorage:
    def __init__(self):
        self.redis = get_redis_connection()
        if self.redis:
            print("🔌 Redis connected — using Redis for processed IDs")
            self.file_mode = False
        else:
            print("📁 Redis unavailable — using fallback file processed.json")
            self.file_mode = True
            self.processed_ids = load_from_file()

    def is_processed(self, msg_id):
        if self.file_mode:
            return msg_id in self.processed_ids
        return redis_is_processed(self.redis, msg_id)

    def mark_processed(self, msg_id):
        if self.file_mode:
            self.processed_ids.add(msg_id)
            save_to_file(self.processed_ids)
        else:
            redis_mark_processed(self.redis, msg_id)


# =====================================================
#   GMAIL AUTH
# =====================================================

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


# =====================================================
#   SEND EMAIL REPLY
# =====================================================

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

    print(f"[✓] Sent reply to {from_email}")


# =====================================================
#   TEXT EXTRACTION
# =====================================================

def extract_text_from_payload(payload):
    text_plain = None
    text_html = None

    def walk(part):
        nonlocal text_plain, text_html
        mime = part.get("mimeType", "")
        body = part.get("body", {})

        if "data" in body:
            decoded = base64.urlsafe_b64decode(body["data"]).decode("utf-8")
            if mime == "text/plain" and not text_plain:
                text_plain = decoded
            elif mime == "text/html" and not text_html:
                text_html = decoded

        for sub in part.get("parts", []):
            walk(sub)

    walk(payload)

    return text_plain or text_html or ""


def extract_image_base64(parts):
    for part in parts:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        if "image" in mime and "attachmentId" in body:
            return body["attachmentId"]
    return None


def get_base64_attachment(service, msg_id, attachment_id):
    att = service.users().messages().attachments().get(
        userId="me",
        messageId=msg_id,
        id=attachment_id
    ).execute()
    return att["data"]


# =====================================================
#   PROCESS ONE MESSAGE
# =====================================================

def process_message(service, msg_id, store: ProcessedStorage):
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()

    payload = msg["payload"]
    headers = payload.get("headers", [])
    parts = payload.get("parts", [])

    from_email = next((h["value"] for h in headers if h["name"] == "From"), "")
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")

    print(f"\n=== NEW EMAIL FROM {from_email} ===")
    print("Subject:", subject)

    # Extract text
    text_content = extract_text_from_payload(payload)

    # Extract image (if any)
    attachment_id = extract_image_base64(parts)
    image_base64 = get_base64_attachment(service, msg_id, attachment_id) if attachment_id else None

    # Check DB record for sender
    record = get_email_record_by_email(from_email)

    if record:
        status = record["status"]
        print(f"DB status = {status}")

        if status == "whitelist":
            print("✔ Whitelisted → skip")
            return

        if status == "blacklist":
            print("❌ Blacklisted → auto reply via n8n")

            payload_n8n = {
                "textContent": text_content or "",
                "image": image_base64 or ""
            }
            res = requests.post(N8N_URL, json=payload_n8n).json()
            ai_res = res["output"]["response"]
            send_reply(service, msg, ai_res)
            return

    # NEW sender → send to n8n
    print("🆕 New sender → classifying...")

    payload_n8n = {
        "textContent": text_content or "",
        "image": image_base64 or ""
    }

    res = requests.post(N8N_URL, json=payload_n8n).json()
    ai_result = res["output"]["output"]
    ai_response = res["output"]["response"]

    print("🤖 n8n classified:", ai_result)

    if ai_result == "whitelist":
        set_email_status(from_email, "whitelist")
    elif ai_result == "blacklist":
        set_email_status(from_email, "blacklist")
        send_reply(service, msg, ai_response)
    else:
        set_email_status(from_email, "none")

    return


# =====================================================
#   MAIN LOOP
# =====================================================

def watch_inbox():
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    store = ProcessedStorage()

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

            for msg in messages:
                msg_id = msg["id"]

                if store.is_processed(msg_id):
                    continue

                process_message(service, msg_id, store)

                store.mark_processed(msg_id)

            time.sleep(3)

        except HttpError as e:
            print("⚠ Gmail API Error:", e)
            time.sleep(5)

        except Exception as e:
            print("⚠ Unexpected error:", e)
            time.sleep(5)


if __name__ == "__main__":
    while True:
        try:
            watch_inbox()
        except ssl.SSLEOFError:
            print("⚠ SSL EOF Error — reconnecting...")
            time.sleep(2)
