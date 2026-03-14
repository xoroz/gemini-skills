import boto3
from pathlib import Path
from dotenv import load_dotenv
import os
import sys
import logging
from datetime import datetime

# Load environment variables
load_dotenv()

# Configuration from .env
BUCKET_NAME = os.getenv("AWS_S3") or os.getenv("AWS_s3")
AWS_ACCESS_KEY = os.getenv("AWS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET")
REGION = os.getenv("AWS_REGION", "eu-south-1")

if not all([BUCKET_NAME, AWS_ACCESS_KEY, AWS_SECRET_KEY]):
    print("❌ Missing credentials in .env file!")
    print("Please check AWS_S3, AWS_KEY, and AWS_SECRET.")
    sys.exit(1)

# ========================
# Setup Logging
# ========================
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler("logs/s3.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class S3WebsiteUploader:
    def __init__(self):
        self.s3 = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY,
            region_name=REGION
        )
        self.bucket_name = BUCKET_NAME

    def sync_site(self, site_name: str):
        site_name = site_name.strip().lower().replace(" ", "-").replace("_", "-")
        local_path = Path("sites") / site_name

        if not local_path.exists():
            logger.error(f"Local folder not found: {local_path}")
            return False, f"Error: Folder 'sites/{site_name}' does not exist!"

        s3_prefix = f"sites/{site_name}/"
        s3_url = f"https://{self.bucket_name}.s3.{REGION}.amazonaws.com/{s3_prefix}index.html"
        
        # If the bucket is configured as a website, this is the URL
        website_url = f"https://{self.bucket_name}.s3-website.{REGION}.amazonaws.com/{s3_prefix}index.html"

        logger.info(f"Starting sync for site: {site_name}")
        uploaded = 0

        for file_path in local_path.rglob("*"):
            if file_path.is_file():
                relative_path = file_path.relative_to(local_path)
                s3_key = f"{s3_prefix}{relative_path}"

                try:
                    content_type = self._get_content_type(file_path)
                    
                    self.s3.upload_file(
                        Filename=str(file_path),
                        Bucket=self.bucket_name,
                        Key=s3_key,
                        ExtraArgs={
                            'ContentType': content_type,
                            'CacheControl': 'max-age=86400'
                        }
                    )
                    logger.info(f"Uploaded: {s3_key}")
                    uploaded += 1
                except Exception as e:
                    logger.error(f"Failed to upload {s3_key}: {e}")

        logger.info(f"Sync completed for {site_name}. Uploaded {uploaded} files.")
        
        # Verify reachability
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                resp = client.head(s3_url)
                if resp.status_code == 200:
                    logger.info(f"✅ Verified reachability for: {s3_url}")
                else:
                    logger.warning(f"⚠️ Reachability check returned status {resp.status_code} for: {s3_url}")
        except Exception as e:
            logger.warning(f"⚠️ Could not verify reachability: {e}")

        return True, s3_url

    def _get_content_type(self, file_path: Path) -> str:
        ext = file_path.suffix.lower()
        content_types = {
            '.html': 'text/html',
            '.css':  'text/css',
            '.js':   'application/javascript',
            '.png':  'image/png',
            '.jpg':  'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif':  'image/gif',
            '.svg':  'image/svg+xml',
            '.ico':  'image/x-icon',
            '.webp': 'image/webp',
        }
        return content_types.get(ext, 'application/octet-stream')

    def delete_site(self, site_name: str):
        site_name = site_name.strip().lower().replace(" ", "-").replace("_", "-")
        s3_prefix = f"sites/{site_name}/"

        logger.info(f"Starting deletion for site: {site_name}")
        try:
            # List all objects with the prefix
            paginator = self.s3.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=s3_prefix)

            delete_keys = []
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        delete_keys.append({'Key': obj['Key']})

            if not delete_keys:
                logger.info(f"No files found for site: {site_name}")
                return True, f"No files found for site '{site_name}' on S3."

            # Batch delete
            # S3 delete_objects can take up to 1000 keys at a time
            for i in range(0, len(delete_keys), 1000):
                batch = delete_keys[i:i + 1000]
                self.s3.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={'Objects': batch}
                )

            logger.info(f"Successfully deleted {len(delete_keys)} files for site: {site_name}")
            return True, f"Successfully deleted {len(delete_keys)} files for site '{site_name}' from S3."
        except Exception as e:
            logger.error(f"Failed to delete site {site_name}: {e}")
            return False, str(e)


# ========================
# Main
# ========================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python s3_upload.py [upload|delete] <site-name>")
        print("Example: python s3_upload.py upload acme-corp")
        sys.exit(1)

    cmd = "upload"
    site_name = ""

    if len(sys.argv) == 2:
        site_name = sys.argv[1]
    else:
        cmd = sys.argv[1].lower()
        site_name = sys.argv[2]

    uploader = S3WebsiteUploader()
    if cmd == "delete":
        success, msg = uploader.delete_site(site_name)
        if success:
            print(f"✅ {msg}")
        else:
            print(f"❌ Failed: {msg}")
            sys.exit(1)
    else:
        success, url = uploader.sync_site(site_name)
        if success:
            print(f"🎉 Sync completed! 🌐 Website URL: {url}")
        else:
            print(f"❌ Sync failed: {url}")
            sys.exit(1)