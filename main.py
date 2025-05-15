import os
import io
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Scopes for Drive and Photos
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata'
]

# Authenticate user
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

# Find a folder by name
def get_folder_id(drive_service, parent_id, folder_name):
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and '{parent_id}' in parents"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get('files', [])
    return folders[0]['id'] if folders else None

# List child folders inside a parent
def list_child_folders(drive_service, parent_id):
    query = f"mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

# List image files in a folder
def list_image_files(drive_service, folder_id):
    query = f"'{folder_id}' in parents and mimeType contains 'image/'"
    results = drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute()
    return results.get('files', [])

# Download image in memory
def download_image(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    image_data = io.BytesIO()
    downloader = MediaIoBaseDownload(image_data, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return image_data.getvalue()

# Upload image to Google Photos
def upload_to_photos(access_token, image_bytes, file_name):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": file_name,
        "X-Goog-Upload-Protocol": "raw",
    }
    upload_url = "https://photoslibrary.googleapis.com/v1/uploads"
    response = requests.post(upload_url, headers=headers, data=image_bytes)
    return response.text if response.status_code == 200 else None

# Create album
def create_album(access_token, title):
    url = "https://photoslibrary.googleapis.com/v1/albums"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {"album": {"title": title}}
    response = requests.post(url, headers=headers, json=body)
    return response.json().get("id") if response.status_code == 200 else None

# Batch create media items
def add_to_album(access_token, upload_tokens, album_id):
    url = "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"
    headers = {"Authorization": f"Bearer {access_token}"}
    body = {
        "albumId": album_id,
        "newMediaItems": [{"simpleMediaItem": {"uploadToken": token}} for token in upload_tokens]
    }
    response = requests.post(url, headers=headers, json=body)
    return response.status_code == 200

# Main logic
def main():
    creds = authenticate()
    drive_service = build('drive', 'v3', credentials=creds)

    # Access token for Photos API requests
    access_token = creds.token

    # 1. Locate parent folder
    parent_folder_name = 'testpic'
    parent_id = get_folder_id(drive_service, 'root', parent_folder_name)
    if not parent_id:
        print("Parent folder not found.")
        return

    # 2. Loop through child folders
    child_folders = list_child_folders(drive_service, parent_id)
    for folder in child_folders:
        print(f"Processing folder: {folder['name']}")
        images = list_image_files(drive_service, folder['id'])

        if not images:
            print(" - No images found.")
            continue

        # 3. Create album in Photos
        album_id = create_album(access_token, folder['name'])
        if not album_id:
            print(" - Failed to create album.")
            continue

        upload_tokens = []
        for img in images:
            print(f"  - Uploading {img['name']}...")
            image_data = download_image(drive_service, img['id'])
            token = upload_to_photos(access_token, image_data, img['name'])
            if token:
                upload_tokens.append(token)

        if upload_tokens:
            success = add_to_album(access_token, upload_tokens, album_id)
            print(f"  - Added {len(upload_tokens)} images to album: {folder['name']}")
        else:
            print("  - No valid images uploaded.")

if __name__ == '__main__':
    main()
