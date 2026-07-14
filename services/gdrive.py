"""
Google Drive integration — downloads and monitors files from a shared folder.
Uses a Service Account for authentication (no user login required).
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger(__name__)

# Supported MIME types and their export formats
SUPPORTED_TYPES = {
    # Native Google Sheets → export as xlsx
    "application/vnd.google-apps.spreadsheet": {
        "export_mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "extension": ".xlsx",
    },
    # Native Google Docs → export as docx
    "application/vnd.google-apps.document": {
        "export_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "extension": ".docx",
    },
    # Uploaded Excel files
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
        "extension": ".xlsx",
    },
    "application/vnd.ms-excel": {
        "extension": ".xls",
    },
    # Uploaded Word files
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        "extension": ".docx",
    },
}


class GoogleDriveService:
    """Handles all Google Drive API operations."""

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    def __init__(self, service_account_file: str, folder_id: str):
        self.folder_id = folder_id
        self._service = None
        self._credentials = None
        self._service_account_file = service_account_file

    def _get_service(self):
        """Lazy-initialize the Drive API service."""
        if self._service is None:
            self._credentials = service_account.Credentials.from_service_account_file(
                self._service_account_file,
                scopes=self.SCOPES,
            )
            self._service = build("drive", "v3", credentials=self._credentials)
            logger.info("Google Drive service initialized")
        return self._service

    def list_files(self) -> list[dict]:
        """
        List all supported files in the monitored folder.

        Returns a list of dicts with keys: id, name, mimeType, modifiedTime
        """
        service = self._get_service()

        # Build query for supported file types
        mime_queries = " or ".join(
            f"mimeType='{mime}'" for mime in SUPPORTED_TYPES.keys()
        )
        query = f"'{self.folder_id}' in parents and ({mime_queries}) and trashed=false"

        try:
            results = (
                service.files()
                .list(
                    q=query,
                    fields="files(id, name, mimeType, modifiedTime)",
                    orderBy="modifiedTime desc",
                    pageSize=50,
                )
                .execute()
            )
            files = results.get("files", [])
            logger.info(f"Found {len(files)} files in Drive folder")
            return files

        except Exception as e:
            logger.error(f"Error listing Drive files: {e}")
            raise

    def download_file(
        self,
        file_id: str,
        file_name: str,
        mime_type: str,
        download_dir: str | Path,
    ) -> Optional[Path]:
        """
        Download a file from Google Drive.

        For Google Docs/Sheets, exports to Office format.
        For uploaded files, downloads directly.
        """
        service = self._get_service()
        download_dir = Path(download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)

        type_info = SUPPORTED_TYPES.get(mime_type)
        if not type_info:
            logger.warning(f"Unsupported MIME type: {mime_type}")
            return None

        # Determine output filename
        extension = type_info["extension"]
        clean_name = Path(file_name).stem + extension
        output_path = download_dir / clean_name

        try:
            if "export_mime" in type_info:
                # Google native format → export
                request = service.files().export_media(
                    fileId=file_id,
                    mimeType=type_info["export_mime"],
                )
            else:
                # Regular file → download
                request = service.files().get_media(fileId=file_id)

            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug(
                        f"Download {file_name}: {int(status.progress() * 100)}%"
                    )

            # Write to file
            with open(output_path, "wb") as f:
                f.write(buffer.getvalue())

            logger.info(f"Downloaded: {file_name} → {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error downloading {file_name}: {e}")
            raise

    def get_file_modified_time(self, file_id: str) -> Optional[str]:
        """Get the last modified time of a file."""
        service = self._get_service()
        try:
            file_meta = (
                service.files()
                .get(fileId=file_id, fields="modifiedTime")
                .execute()
            )
            return file_meta.get("modifiedTime")
        except Exception as e:
            logger.error(f"Error getting modified time for {file_id}: {e}")
            return None

    def sync_files(self, download_dir: str | Path) -> list[dict]:
        """
        Sync all supported files from the monitored folder.

        Returns list of dicts: {file_id, file_name, local_path, modified_time}
        """
        files = self.list_files()
        synced = []

        for file_info in files:
            try:
                local_path = self.download_file(
                    file_id=file_info["id"],
                    file_name=file_info["name"],
                    mime_type=file_info["mimeType"],
                    download_dir=download_dir,
                )
                if local_path:
                    synced.append(
                        {
                            "file_id": file_info["id"],
                            "file_name": file_info["name"],
                            "local_path": str(local_path),
                            "modified_time": file_info.get("modifiedTime"),
                        }
                    )
            except Exception as e:
                logger.error(f"Failed to sync {file_info['name']}: {e}")
                continue

        logger.info(f"Synced {len(synced)}/{len(files)} files")
        return synced
