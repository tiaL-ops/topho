import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Scopes needed to read Google Photos albums
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']

# Token & credentials files
TOKEN_FILE = 'photos_token.json'
CLIENT_SECRETS = 'credentials.json'


def authenticate():
    """
    Authenticate to Google Photos API, storing/reading token from TOKEN_FILE.
    Uses console flow as fallback if run_local_server hangs.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
        try:
            creds = flow.run_local_server(port=0)
        except Exception:
            print("Local server auth failed, falling back to console mode...")
            creds = flow.run_console()
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return creds


def clean_album_name(raw_name: str) -> str:
    """
    Given an album title possibly containing '/', return the text after the last slash.
    """
    return raw_name.rsplit('/', 1)[-1].strip()


def list_clean_albums(service):
    """
    List all albums in the user's Google Photos library,
    printing original and cleaned names.
    """
    albums = []
    next_page_token = None
    while True:
        response = service.albums().list(
            pageSize=50,
            pageToken=next_page_token
        ).execute()
        for a in response.get('albums', []):
            raw = a.get('title', '')
            clean = clean_album_name(raw)
            albums.append({'id': a['id'], 'original': raw, 'cleaned': clean})
            print(f"Album ID: {a['id']}")
            print(f"  Original: {raw}")
            print(f"  Cleaned:  {clean}\n")
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break
    return albums


def main():
    creds = authenticate()
    # Use explicit discovery URL to avoid UnknownApiNameOrVersion
    photos_service = build(
        'photoslibrary', 'v1',
        credentials=creds,
        discoveryServiceUrl='https://photoslibrary.googleapis.com/$discovery/rest?version=v1'
    )
    list_clean_albums(photos_service)


if __name__ == '__main__':
    main()