
#  topho – Upload Google Drive Photos to Google Photos

Welcome to **topho**! This tool helps you transfer media from your **Google Drive** to **Google Photos**.

---

## 🚀 Setup Instructions

### 1. Create a Virtual Environment (Recommended)

Using a virtual environment keeps dependencies isolated:

```bash
python -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

### 2. Install Required Packages

```bash
pip install -r requirements.txt
```

---

## 🔐 Google API Setup

To use this tool, you need to authenticate with your own **Google Cloud credentials**:

### Steps:

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new **project**.
3. Enable the following APIs:

   * **Google Drive API**
   * **Google Photos Library API**
4. Go to **Credentials** and create an **OAuth 2.0 Client ID**:

   * Application type: **Desktop app**
   * Download the `client_secret.json`
5. Rename it to `credentials.json` and place it in the project’s root folder.

---

## 📂 Using the Script

Once everything is set up:

```bash
python main.py
```

You'll be prompted to enter the name of the root folder from your Google Drive that you want to process.

Optional command-line flags:

```bash
python main.py \
  --root-folder "MyDriveFolder" \
  --max-video-seconds 300 \
  --credentials credentials.json \
  --token token.json
```

---

## 🧼 Notes

* Media will be organized into albums in Google Photos by folder name.
* Only media with supported formats (e.g., `.jpg`, `.mp4`) will be uploaded.
* Videos longer than your specified limit will be skipped.


