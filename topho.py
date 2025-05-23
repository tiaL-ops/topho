import os
import io
import json
import requests
import time
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Scopes for Drive (read-only) and Photos (append-only)
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata',
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata'
]

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.dng'}
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.wav'}

IMPORTED_FILE = 'imported.json'
SKIPPED_FILE = 'skipped.json'
MISSED_FILE = 'missedimages.txt'
ALLMISSED_FILE = 'allmissed.txt'


def authenticate(credentials_path: str, token_path: str) -> Credentials:
    """
    Authenticate with Google, saving token to token_path.
    """
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    return creds


def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def log_missing(folder, name, reason):
    with open(MISSED_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{folder} - {name} : {reason}\n")


def log_allmissed(folder, name, file_id, reason):
    with open(ALLMISSED_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{folder} - {name} - {file_id} : {reason}\n")


def list_all_items(drive_service, folder_id):
    query = f"'{folder_id}' in parents"
    items = []
    page_token = None
    while True:
        resp = drive_service.files().list(
            q=query,
            pageSize=1000,
            fields="nextPageToken, files(id,name,mimeType,videoMediaMetadata(durationMillis))",
            pageToken=page_token
        ).execute()
        items.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return items


def download_file(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def upload_to_photos(token: str, file_bytes: bytes, file_name: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": file_name,
        "X-Goog-Upload-Protocol": "raw",
    }
    resp = requests.post(
        "https://photoslibrary.googleapis.com/v1/uploads",
        headers=headers,
        data=file_bytes
    )
    if resp.status_code == 200:
        return resp.text
    try:
        err = resp.json().get('error', {})
        msg = err.get('message', resp.text)
    except ValueError:
        msg = resp.text
    raise RuntimeError(f"Upload failed ({resp.status_code}): {msg}")


def create_album(token: str, title: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(
        "https://photoslibrary.googleapis.com/v1/albums",
        headers=headers,
        json={"album": {"title": title}}
    )
    return resp.json().get('id') if resp.status_code == 200 else None


def get_album_id(token: str, title: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    next_page = None
    while True:
        params = {"pageSize": 50}
        if next_page:
            params["pageToken"] = next_page
        resp = requests.get(
            "https://photoslibrary.googleapis.com/v1/albums",
            headers=headers,
            params=params
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        for alb in data.get("albums", []):
            if alb.get("title") == title:
                return alb.get("id")
        next_page = data.get("nextPageToken")
        if not next_page:
            break
    return None


def add_to_album(token: str, upload_tokens: list, album_id: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "albumId": album_id,
        "newMediaItems": [{"simpleMediaItem": {"uploadToken": t}} for t in upload_tokens]
    }
    resp = requests.post(
        "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate",
        headers=headers,
        json=body
    )
    if resp.status_code != 200:
        err = resp.json().get('error', {}).get('message', resp.text)
        raise RuntimeError(f"Add to album failed ({resp.status_code}): {err}")


def process_folder(drive_service, token, folder_id, folder_name, imported, skipped, max_video_seconds):
    print(f"\n📁 Processing: {folder_name}")
    items = list_all_items(drive_service, folder_id)
    upload_tokens = []
    for itm in items:
        fid = itm['id']
        name = itm['name']
        mime = itm['mimeType']
        ext = os.path.splitext(name)[1].lower()
        is_image = mime.startswith('image/') or ext in IMAGE_EXTS
        is_video = mime.startswith('video/') or ext in VIDEO_EXTS
        if mime == 'application/vnd.google-apps.folder':
            process_folder(
                drive_service, token, fid,
                f"{folder_name}/{name}", imported, skipped, max_video_seconds
            )
            continue
        if not (is_image or is_video):
            log_missing(folder_name, name, 'unsupported')
            continue
        if fid in imported:
            print(f"  ↳ Already imported {name}")
            continue
        if fid in skipped:
            print(f"  ↳ Skipped {name}: {skipped[fid]}")
            continue
        if is_video:
            dur_ms = itm.get('videoMediaMetadata', {}).get('durationMillis')
            try:
                dur = int(dur_ms)/1000 if dur_ms else 0
            except Exception:
                dur = 0
            if dur > max_video_seconds:
                reason = f"too long ({dur:.1f}s)"
                log_missing(folder_name, name, reason)
                skipped[fid] = reason
                save_json(SKIPPED_FILE, skipped)
                continue
        try:
            data = download_file(drive_service, fid)
            token_str = upload_to_photos(token, data, name)
            upload_tokens.append(token_str)
            imported.add(fid)
            save_json(IMPORTED_FILE, list(imported))
            print(f"  ✅ Uploaded {name}")
        except Exception as e:
            err = str(e)
            log_missing(folder_name, name, err)
            skipped[fid] = err
            save_json(SKIPPED_FILE, skipped)
    if upload_tokens:
        album_id = get_album_id(token, folder_name) or create_album(token, folder_name)
        if album_id:
            for i in range(0, len(upload_tokens), 50):
                add_to_album(token, upload_tokens[i:i+50], album_id)
            print(f"  🎉 Added {len(upload_tokens)} items to '{folder_name}'")
        else:
            print(f"⚠️ Could not create/find album '{folder_name}'")


def run(root_folder_name: str, max_video_seconds: int, credentials_path: str, token_path: str):
    creds = authenticate(credentials_path, token_path)
    drive_service = build('drive', 'v3', credentials=creds)
    token = creds.token

    # locate root folder by name
    resp = drive_service.files().list(
        q=(f"mimeType='application/vnd.google-apps.folder' and "
           f"name='{root_folder_name}' and 'root' in parents"),
        fields="files(id,name)"
    ).execute()
    files = resp.get('files', [])
    if not files:
        print(f"Root folder '{root_folder_name}' not found.")
        return
    root_id = files[0]['id']

    imported = set(load_json(IMPORTED_FILE, []))
    skipped = load_json(SKIPPED_FILE, {})

    children = drive_service.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and '{root_id}' in parents",
        fields="files(id,name)"
    ).execute().get('files', [])

    for child in children:
        process_folder(
            drive_service, token,
            child['id'], child['name'],
            imported, skipped, max_video_seconds
        )
