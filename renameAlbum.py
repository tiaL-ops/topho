#!/usr/bin/env python3
import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Full access to your Photos library (required for delete & rename)
SCOPES = ['https://www.googleapis.com/auth/photoslibrary']


TOKEN_PATH = 'token.json'
CREDS_PATH = 'credentials.json'


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

def list_all_albums(service):
    albums = []
    next_token = None
    while True:
        resp = service.albums().list(
            pageSize=50,
            pageToken=next_token,
            fields='nextPageToken,albums(id,title,mediaItemsCount)'
        ).execute()
        albums.extend(resp.get('albums', []))
        next_token = resp.get('nextPageToken')
        if not next_token:
            break
    return albums


def delete_album(service, album_id, title):
    try:
        service.albums().delete(albumId=album_id).execute()
        print(f"🗑  Deleted empty album: '{title}'")
    except Exception as e:
        print(f"❌ Failed to delete '{title}': {e}")


def rename_album(service, album_id, old_title, new_title):
    try:
        body = {
            'album': {'title': new_title},
            'updateMask': 'title'
        }
        service.albums().patch(albumId=album_id, body=body).execute()
        print(f"✏️  Renamed album: '{old_title}' → '{new_title}'")
    except Exception as e:
        print(f"❌ Failed to rename '{old_title}': {e}")


def main():
    
    creds = authenticate()
    print("🔐 Granted scopes:")
    print(creds.scopes)   

    # ← here’s the only change:
    service = build(
        'photoslibrary', 'v1', credentials=creds,
        discoveryServiceUrl='https://photoslibrary.googleapis.com/$discovery/rest?version=v1'
    )

    print("🔍 Fetching all albums...")
    albums = list_all_albums(service)
    print(f"Found {len(albums)} albums.\n")

    for album in albums:
        album_id = album['id']
        title = album.get('title', '')
        # mediaItemsCount comes back as a string, default to zero if missing
        count = int(album.get('mediaItemsCount', '0'))

        # 1) Delete empty albums
        if count == 0:
            delete_album(service, album_id, title)
            continue

        # 2) Rename if title contains "/"
        if '/' in title:
            new_title = title.split('/')[-1].strip()
            if new_title and new_title != title:
                rename_album(service, album_id, title, new_title)

    print("\n✅ Done.")


if __name__ == '__main__':
    main()
