import os
import io
import tempfile
import requests
import ffmpeg
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata'
]


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

def get_folder_id(drive_service, parent_id, folder_name):
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and '{parent_id}' in parents"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get('files', [])
    return folders[0]['id'] if folders else None

def list_child_folders(drive_service, parent_id):
    query = f"mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def list_media_files(drive_service, folder_id):
    query = f"'{folder_id}' in parents and (mimeType contains 'image/' or mimeType contains 'video/')"
    results = drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute()
    return results.get('files', [])

def download_file(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    data = io.BytesIO()
    downloader = MediaIoBaseDownload(data, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return data.getvalue()

def upload_to_photos(access_token, file_bytes, file_name):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": file_name,
        "X-Goog-Upload-Protocol": "raw",
    }
    upload_url = "https://photoslibrary.googleapis.com/v1/uploads"
    response = requests.post(upload_url, headers=headers, data=file_bytes)
    return response.text if response.status_code == 200 else None

def create_album(access_token, title):
    url = "https://photoslibrary.googleapis.com/v1/albums"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {"album": {"title": title}}
    response = requests.post(url, headers=headers, json=body)
    
    if response.status_code != 200:
        print(f"  ❌ Album creation error ({title}): {response.status_code} - {response.text}")
        return None

    return response.json().get("id")


def add_to_album(access_token, upload_tokens, album_id):
    url = "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {
        "albumId": album_id,
        "newMediaItems": [{"simpleMediaItem": {"uploadToken": token}} for token in upload_tokens]
    }
    response = requests.post(url, headers=headers, json=body)
    return response.status_code == 200

def get_video_duration_from_bytes(video_bytes):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
            temp_file.write(video_bytes)
            temp_file_path = temp_file.name
        probe = ffmpeg.probe(temp_file_path)
        duration = float(probe['format']['duration'])
        os.unlink(temp_file_path)
        return duration
    except Exception as e:
        print("Error getting video duration:", e)
        return None

def write_to_file(file_name, data):
    with open(file_name, 'wb') as file:
        file.write(data)
    print(f"File written: {file_name}")

def main():
    creds = authenticate()
    drive_service = build('drive', 'v3', credentials=creds)
    access_token = creds.token
    skipped_videos = []

    parent_folder_name = 'testpic'
    parent_id = get_folder_id(drive_service, 'root', parent_folder_name)
    if not parent_id:
        print("Parent folder not found.")
        return

    child_folders = list_child_folders(drive_service, parent_id)
    for folder in child_folders:
        print(f"Processing folder: {folder['name']}")
        media_files = list_media_files(drive_service, folder['id'])

        if not media_files:
            print(" - No media files found.")
            continue

        album_id = create_album(access_token, folder['name'])
        if not album_id:
            print(" - Failed to create album.")
            continue

        upload_tokens = []

        for media in media_files:
            print(f"  - Processing {media['name']}...")
            file_bytes = download_file(drive_service, media['id'])
            mime_type = media['mimeType']

            if mime_type.startswith('video/'):
                duration = get_video_duration_from_bytes(file_bytes)
                if duration and duration > 300:  # 5 minutes
                    print(f"    ⚠️ Skipped {media['name']}: video too long ({duration:.1f} sec)")
                    skipped_videos.append((folder['name'], media['name'], duration))
                    continue

            token = upload_to_photos(access_token, file_bytes, media['name'])
            if token:
                upload_tokens.append(token)

        if upload_tokens:
            success = add_to_album(access_token, upload_tokens, album_id)
            print(f"  - Added {len(upload_tokens)} media items to album: {folder['name']}")
        else:
            print("  - No valid media uploaded.")

    if skipped_videos:
        with open("missed_videos.txt", "w", encoding="utf-8") as f:
            for folder_name, video_name, duration in skipped_videos:
                f.write(f"{folder_name} - {video_name} (Duration: {duration:.1f} sec)\n")
        print("⚠️ Skipped video log saved to missed_videos.txt")

if __name__ == '__main__':
    main()
