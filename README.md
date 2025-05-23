
# 📸 topho – Upload Google Drive Photos to Google Photos

Welcome to **topho**! This tool helps you transfer media from **Google Drive** to **Google Photos**, organizing everything into albums by folder.

---

## 📥 1. Clone This Repo

First, clone the repository:

```bash
git clone https://github.com/tiaL-ops/topho.git

```

---

## 🚀 2. Set Up Your Environment

### Create a Virtual Environment (Recommended)

```bash
python -m venv .venv
source .venv/bin/activate
```

### Install Required Packages

```bash
pip install -r requirements.txt
```

---

## 🔐 3. Google API Credentials Setup

To authenticate with Google:

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new **project**.
3. Enable the following APIs:

   * **Google Drive API**
   * **Google Photos Library API**
4. Under **Credentials**, create an **OAuth 2.0 Client ID**:

   * Application type: **Desktop App**
   * Download the file and rename it to `credentials.json`
5. Place `credentials.json` in the root of the project.

---

## ▶️ 4. Run the Tool

```bash
python main.py
```

You'll be prompted to enter the name of your Google Drive folder.

### Optional Flags

```bash
python main.py \
  --root-folder "MyDriveFolder" \
  --max-video-seconds 300 \
  --credentials credentials.json \
  --token token.json
```

---

## 📄 Notes

* Only supported media files (e.g. `.jpg`, `.png`, `.mp4`) will be uploaded.
* Videos over the specified duration will be skipped.
* Media is uploaded to albums matching your Drive folder names.


