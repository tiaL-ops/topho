import os
import io
import json
import tempfile
import requests
import ffmpeg
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Scopes for Drive (read-only) and Photos (append-only)
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata'
]

# Supported extensions
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.dng'}
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv'}

# Files for tracking
IMPORTED_FILE = 'imported.json'
MISSED_FILE = 'missedimages.txt'


def authenticate():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds


def load_imported():
    if os.path.exists(IMPORTED_FILE):
        with open(IMPORTED_FILE, 'r') as f:
            return set(json.load(f))
    return set()


def save_imported(imported_set):
    with open(IMPORTED_FILE, 'w') as f:
        json.dump(list(imported_set), f, indent=2)


def log_missing(folder, name, reason):
    with open(MISSED_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{folder} - {name} : {reason}\n")


def list_all_items(drive_service, folder_id):
    query = f"'{folder_id}' in parents"
    results = drive_service.files().list(q=query, fields="files(id,name,mimeType)").execute()
    return results.get('files', [])


def download_file(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    data = io.BytesIO()
    downloader = MediaIoBaseDownload(data, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return data.getvalue()


def upload_to_photos(token, file_bytes, file_name):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": file_name,
        "X-Goog-Upload-Protocol": "raw",
    }
    upload_url = "https://photoslibrary.googleapis.com/v1/uploads"
    resp = requests.post(upload_url, headers=headers, data=file_bytes)
    if resp.status_code == 200:
        return resp.text
    return None


def create_album(token, title):
    url = "https://photoslibrary.googleapis.com/v1/albums"
    headers = {"Authorization": f"Bearer {token}"}
    body = {"album": {"title": title}}
    resp = requests.post(url, headers=headers, json=body)
    if resp.status_code == 200:
        return resp.json().get('id')
    return None


def add_to_album(token, upload_tokens, album_id):
    url = "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "albumId": album_id,
        "newMediaItems": [{"simpleMediaItem": {"uploadToken": t}} for t in upload_tokens]
    }
    resp = requests.post(url, headers=headers, json=body)
    return resp.status_code == 200


def get_video_duration(video_bytes):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        info = ffmpeg.probe(tmp_path)
        os.remove(tmp_path)
        return float(info['format']['duration'])
    except Exception as e:
        return None


def process_folder(drive_service, token, folder_id, folder_name, imported):
    print(f"\n📁 Entering folder: {folder_name}")
    items = list_all_items(drive_service, folder_id)
    # Log items
    for itm in items:
        ext = os.path.splitext(itm['name'])[1].lower()
        if itm['mimeType'] == 'application/vnd.google-apps.folder':
            print(f"  [Folder] {itm['name']}")
        elif ext in IMAGE_EXTS:
            print(f"  [Image]  {itm['name']}")
        elif ext in VIDEO_EXTS:
            print(f"  [Video]  {itm['name']}")
        else:
            print(f"  [Skip]   {itm['name']} (unsupported)")
            log_missing(folder_name, itm['name'], 'unsupported format')
    
    # Create album for this folder
    album_id = create_album(token, folder_name)
    if not album_id:
        print(f"⚠️ Could not create album for '{folder_name}'")
        log_missing(folder_name, '', 'album creation failed')
        return

    upload_tokens = []
    # Process media
    for itm in items:
        if itm['mimeType'] == 'application/vnd.google-apps.folder':
            process_folder(drive_service, token, itm['id'], f"{folder_name}/{itm['name']}", imported)
            continue
        file_id = itm['id']
        name = itm['name']
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue
        if file_id in imported:
            print(f"  ↳ Already imported: {name}")
            continue
        try:
            data = download_file(drive_service, file_id)
            if ext in VIDEO_EXTS:
                dur = get_video_duration(data)
                if dur and dur > 300:
                    print(f"    ⚠️ Skipped {name}: video too long ({dur:.1f}s)")
                    log_missing(folder_name, name, f"video too long ({dur:.1f}s)")
                    continue
            token_str = upload_to_photos(token, data, name)
            if not token_str:
                raise RuntimeError('upload failed')
            upload_tokens.append(token_str)
            imported.add(file_id)
            save_imported(imported)
            print(f"  ✅ Uploaded {name}")
        except Exception as e:
            print(f"  ❌ Error {name}: {e}")
            log_missing(folder_name, name, str(e))

    # Add to album
    if upload_tokens:
        ok = add_to_album(token, upload_tokens, album_id)
        if ok:
            print(f"  🎉 Added {len(upload_tokens)} items to album")
        else:
            print(f"  ❌ Failed to add items to album")
            log_missing(folder_name, '', 'batchCreate failed')


def main():
    creds = authenticate()
    drive_service = build('drive', 'v3', credentials=creds)
    token = creds.token
    imported = load_imported()
    
    # Start from a root folder name
    root_name = '_Pictures and Video'
    resp = drive_service.files().list(q=f"mimeType='application/vnd.google-apps.folder' and name='{root_name}' and 'root' in parents", fields="files(id,name)").execute()
    folders = resp.get('files', [])
    if not folders:
        print(f"Root folder '{root_name}' not found.")
        return
    root_id = folders[0]['id']
    # Process each child folder
    children = drive_service.files().list(q=f"mimeType='application/vnd.google-apps.folder' and '{root_id}' in parents", fields="files(id,name)").execute().get('files', [])
    for f in children:
        process_folder(drive_service, token, f['id'], f['name'], imported)

if __name__ == '__main__':
    main()
