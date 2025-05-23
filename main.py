import argparse
from topho import run


def main():
    parser = argparse.ArgumentParser(
        description="Upload Google Drive media to Google Photos"
    )
    parser.add_argument(
        "--root-folder", "-r",
        help="Name of the root Drive folder to process"
    )
    parser.add_argument(
        "--max-video-seconds", "-m",
        type=int,
        default=10000,
        help="Maximum allowed video duration in seconds (default: 10000)"
    )
    parser.add_argument(
        "--credentials", "-c",
        default="credentials.json",
        help="Path to Google OAuth client secrets file (default: credentials.json)"
    )
    parser.add_argument(
        "--token", "-t",
        default="token.json",
        help="Path to store/retrieve OAuth token (default: token.json)"
    )

    args = parser.parse_args()

    # Prompt interactively if no root folder provided
    if not args.root_folder:
        args.root_folder = input("Enter the name of the root Drive folder to process: ").strip()

    run(
        root_folder_name=args.root_folder,
        max_video_seconds=args.max_video_seconds,
        credentials_path=args.credentials,
        token_path=args.token
    )


if __name__ == '__main__':
    main()