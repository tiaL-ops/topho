import os
import io
import json
import requests
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

# Supported extensions & video duration threshold
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.dng'}
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv','wav'}
MAX_VIDEO_SECONDS = 1800

# Tracking files
IMPORTED_FILE = 'imported.json'
SKIPPED_FILE = 'skipped.json'
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


def list_all_items(drive_service, folder_id):
    query = f"'{folder_id}' in parents"
    items, page_token = [], None
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
    data = io.BytesIO()
    downloader = MediaIoBaseDownload(data, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return data.getvalue()


def upload_to_photos(token, file_bytes, file_name):
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
    # extract error message if possible
    try:
        err = resp.json().get('error', {})
        msg = err.get('message', resp.text)
    except ValueError:
        msg = resp.text
    raise RuntimeError(f"Upload failed ({resp.status_code}): {msg}")


def create_album(token, title):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(
        "https://photoslibrary.googleapis.com/v1/albums",
        headers=headers,
        json={"album": {"title": title}}
    )
    return resp.json().get('id') if resp.status_code == 200 else None


def get_album_id(token, title):
    """Return existing app-created album ID by title, or None."""
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


def add_to_album(token, upload_tokens, album_id):
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
    if resp.status_code == 200:
        return True
    # extract error message
    try:
        err = resp.json().get('error', {})
        msg = err.get('message', resp.text)
    except ValueError:
        msg = resp.text
    raise RuntimeError(f"Add to album failed ({resp.status_code}): {msg}")


def process_folder(drive_service, token, folder_id, folder_name, imported, skipped):
    print(f"\n📁 Entering folder: {folder_name}")
    items = list_all_items(drive_service, folder_id)

    # Log contents
    for itm in items:
        name, mime = itm['name'], itm['mimeType']
        ext = os.path.splitext(name)[1].lower()
        if mime == 'application/vnd.google-apps.folder':
            print(f"  [Folder] {name}")
        elif mime.startswith('image/') or ext in IMAGE_EXTS:
            print(f"  [Image]  {name}")
        elif mime.startswith('video/') or ext in VIDEO_EXTS:
            print(f"  [Video]  {name}")
        else:
            print(f"  [Skip]   {name} (unsupported)")
            log_missing(folder_name, name, 'unsupported format')

    upload_tokens = []

    for itm in items:
        if itm['mimeType'] == 'application/vnd.google-apps.folder':
            process_folder(
                drive_service, token,
                itm['id'], f"{folder_name}/{itm['name']}",
                imported, skipped
            )
            continue

        file_id = itm['id']
        name = itm['name']
        mime = itm['mimeType']
        ext = os.path.splitext(name)[1].lower()
        is_image = mime.startswith('image/') or ext in IMAGE_EXTS
        is_video = mime.startswith('video/') or ext in VIDEO_EXTS

        if not (is_image or is_video):
            continue
        if file_id in imported:
            print(f"  ↳ Already imported: {name}")
            continue
        if file_id in skipped:
            print(f"  ↳ Already skipped: {name} ({skipped[file_id]})")
            continue

        # Video-length check by metadata (cast duration to int)
        if is_video:
            dur_raw = itm.get('videoMediaMetadata', {}).get('durationMillis')
            try:
                dur_ms = int(dur_raw) if dur_raw is not None else None
            except (ValueError, TypeError):
                dur_ms = None

            if dur_ms and (dur_ms / 1000) > MAX_VIDEO_SECONDS:
                reason = f"video too long ({dur_ms/1000:.1f}s)"
                print(f"    ⚠️ Skipped {name}: {reason}")
                log_missing(folder_name, name, reason)
                skipped[file_id] = reason
                save_json(SKIPPED_FILE, skipped)
                continue

        try:
            data = download_file(drive_service, file_id)
            token_str = upload_to_photos(token, data, name)
            upload_tokens.append(token_str)
            imported.add(file_id)
            save_json(IMPORTED_FILE, list(imported))
            print(f"  ✅ Uploaded {name}")
        except Exception as e:
            print(f"  ❌ Upload failed for {name}: {e}")
            log_missing(folder_name, name, str(e))
            skipped[file_id] = str(e)
            save_json(SKIPPED_FILE, skipped)

    if upload_tokens:
        album_id = get_album_id(token, folder_name) or create_album(token, folder_name)
        if not album_id:
            print(f"⚠️ Could not create or find album '{folder_name}'")
            log_missing(folder_name, '', 'album creation/fetch failed')
            return
        chunk_size = 50
        for i in range(0, len(upload_tokens), chunk_size):
            batch = upload_tokens[i:i+chunk_size]
            try:
                add_to_album(token, batch, album_id)
                print(f"  🎉 Added {len(upload_tokens)} items to album '{folder_name}'")
            except Exception as e:
                print(f"  ❌ Failed to add items to album '{folder_name}': {e}")
                log_missing(folder_name, '', str(e))
    else:
        # don't create an album if there's nothing to upload
        print(f"  - No valid media uploaded; skipping album creation.")
def get_folder_items_id_json(drive_service, folder_id):
    """
    Returns a JSON string mapping each file’s name to its Drive ID
    for all non‐folder items in the given folder.
    """
    items = list_all_items(drive_service, folder_id)
    mapping = {
        itm['name']: itm['id']
        for itm in items
        if itm['mimeType'] != 'application/vnd.google-apps.folder'
    }
    return json.dumps(mapping, indent=2)
def export_and_clear_imported_for_folder(drive_service, folder_id):
    """
    1) Loads imported.json (either a list of IDs or a dict of {id:info})
    2) Converts it to a dict if necessary, saving it back
    3) Lists that Drive folder
    4) Builds a {fileName: fileId} map for only those IDs in imported.json
    5) Deletes those IDs from imported.json on disk
    6) Returns the mapping as pretty JSON
    """
    # 1) load whatever is in imported.json
    imported_raw = load_json(IMPORTED_FILE, None)
    if imported_raw is None:
        imported = {}
    elif isinstance(imported_raw, list):
        # convert old list-of-IDs into a dict
        imported = {fid: {} for fid in imported_raw}
        save_json(IMPORTED_FILE, imported)
    elif isinstance(imported_raw, dict):
        imported = imported_raw
    else:
        raise RuntimeError(f"{IMPORTED_FILE} has unexpected format")

    # 2) list all items in the folder
    items = list_all_items(drive_service, folder_id)

    # 3) build mapping for those IDs that were imported
    mapping = {}
    to_remove = []
    for itm in items:
        fid = itm['id']
        if itm['mimeType'] != 'application/vnd.google-apps.folder' and fid in imported:
            mapping[itm['name']] = fid
            to_remove.append(fid)

    # 4) remove them from imported and save back
    for fid in to_remove:
        imported.pop(fid, None)
    save_json(IMPORTED_FILE, imported)

    # 5) return the JSON block
    return json.dumps(mapping, indent=2)




def main():
    creds = authenticate()
    drive_service = build('drive', 'v3', credentials=creds)
    token = creds.token
    
   
   
    imported = set(load_json(IMPORTED_FILE, []))
    skipped = load_json(SKIPPED_FILE, {})

    root_name = 'picvid'
    resp = drive_service.files().list(
        q=(f"mimeType='application/vnd.google-apps.folder' and"
           f" name='{root_name}' and 'root' in parents"),
        fields="files(id,name)"
    ).execute()
    folders = resp.get('files', [])
    if not folders:
        print(f"Root folder '{root_name}' not found.")
        return
    root_id = folders[0]['id']

    children = drive_service.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and '{root_id}' in parents",
        fields="files(id,name)"
    ).execute().get('files', [])

    for f in children:
        process_folder(drive_service, token, f['id'], f['name'], imported, skipped)


if __name__ == '__main__':
    main()
