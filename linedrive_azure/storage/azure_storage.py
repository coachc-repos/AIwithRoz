#!/usr/bin/env python3
"""
Azure Data Lake Storage Utility for Tournament Data
==================================================

This module provides functionality to upload tournament scraper data
to Azure Data Lake Storage with proper hierarchical organization.

Organization structure:
tournament-data/
├── raw/year=YYYY/month=MM/day=DD/tournaments_YYYYMMDD_HHMMSS.json
└── processed/year=YYYY/month=MM/day=DD/tournaments_YYYYMMDD_HHMMSS.csv
"""

import json
import csv
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

try:
    from azure.storage.blob import BlobServiceClient
    from azure.identity import (
        DefaultAzureCredential,
        AzureCliCredential,
        ChainedTokenCredential,
    )

    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    logging.warning("Azure SDK not available. Storage upload will be disabled.")


class AzureDataLakeUploader:
    """Upload tournament data to Azure Data Lake Storage with hierarchical organization"""

    def __init__(
        self,
        storage_account_name: str = "linedrivestorage",
        container_name: str = "tournament-data",
    ):
        self.storage_account_name = storage_account_name
        self.container_name = container_name
        self.blob_service_client = None

        if AZURE_AVAILABLE:
            try:
                # Use Azure CLI credentials first (for local development), fall back to default
                credential = ChainedTokenCredential(
                    AzureCliCredential(), DefaultAzureCredential()
                )
                self.blob_service_client = BlobServiceClient(
                    account_url=f"https://{storage_account_name}.blob.core.windows.net",
                    credential=credential,
                )
                logging.info(
                    f"✅ Azure Data Lake connection initialized for {storage_account_name}"
                )
            except Exception as e:
                logging.error(
                    f"❌ Failed to initialize Azure Data Lake connection: {e}"
                )
                self.blob_service_client = None
        else:
            logging.warning("⚠️ Azure SDK not available - storage uploads disabled")

    def _get_date_hierarchy(self, timestamp: datetime = None) -> str:
        """Generate hierarchical date path: year=YYYY/month=MM/day=DD"""
        if timestamp is None:
            timestamp = datetime.now()

        return (
            f"year={timestamp.year}/month={timestamp.month:02d}/day={timestamp.day:02d}"
        )

    def _get_timestamp_string(self, timestamp: datetime = None) -> str:
        """Generate timestamp string: YYYYMMDD_HHMMSS"""
        if timestamp is None:
            timestamp = datetime.now()

        return timestamp.strftime("%Y%m%d_%H%M%S")

    def upload_raw_data(
        self,
        tournaments: List[Dict],
        run_type: str = "manual",
        timestamp: datetime = None,
    ) -> Optional[str]:
        """
        Upload raw tournament data as JSON to Azure Data Lake

        Args:
            tournaments: List of tournament dictionaries
            run_type: Type of scraper run ("manual" or "scheduled")
            timestamp: Override timestamp (defaults to now)

        Returns:
            Blob URL if successful, None if failed
        """
        if not self.blob_service_client:
            logging.warning("⚠️ Azure Data Lake not available - skipping upload")
            return None

        if not tournaments:
            logging.warning("⚠️ No tournament data to upload")
            return None

        try:
            if timestamp is None:
                timestamp = datetime.now()

            # Create file paths
            date_path = self._get_date_hierarchy(timestamp)
            timestamp_str = self._get_timestamp_string(timestamp)
            filename = f"tournaments_{timestamp_str}.json"
            blob_path = f"raw/{date_path}/{filename}"

            # Prepare data with metadata
            upload_data = {
                "metadata": {
                    "scrape_timestamp": timestamp.isoformat(),
                    "run_type": run_type,
                    "tournament_count": len(tournaments),
                    "data_format": "raw_json",
                    "scraper_version": "1.0",
                },
                "tournaments": tournaments,
            }

            # Convert to JSON
            json_data = json.dumps(upload_data, indent=2, default=str)

            # Upload to blob storage
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_path
            )

            blob_client.upload_blob(
                json_data.encode("utf-8"),
                overwrite=True,
                content_type="application/json",
            )

            blob_url = blob_client.url
            logging.info(f"✅ Raw data uploaded: {blob_path}")
            logging.info(f"📊 Uploaded {len(tournaments)} tournaments")

            return blob_url

        except Exception as e:
            logging.error(f"❌ Failed to upload raw data: {e}")
            return None

    def upload_processed_data(
        self,
        tournaments: List[Dict],
        run_type: str = "manual",
        timestamp: datetime = None,
    ) -> Optional[str]:
        """
        Upload processed tournament data as CSV to Azure Data Lake

        Args:
            tournaments: List of tournament dictionaries
            run_type: Type of scraper run ("manual" or "scheduled")
            timestamp: Override timestamp (defaults to now)

        Returns:
            Blob URL if successful, None if failed
        """
        if not self.blob_service_client:
            logging.warning("⚠️ Azure Data Lake not available - skipping upload")
            return None

        if not tournaments:
            logging.warning("⚠️ No tournament data to upload")
            return None

        try:
            if timestamp is None:
                timestamp = datetime.now()

            # Create file paths
            date_path = self._get_date_hierarchy(timestamp)
            timestamp_str = self._get_timestamp_string(timestamp)
            filename = f"tournaments_{timestamp_str}.csv"
            blob_path = f"processed/{date_path}/{filename}"

            # Convert tournaments to CSV format
            csv_data = self._tournaments_to_csv(tournaments, run_type, timestamp)

            # Upload to blob storage
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=blob_path
            )

            blob_client.upload_blob(
                csv_data.encode("utf-8"), overwrite=True, content_type="text/csv"
            )

            blob_url = blob_client.url
            logging.info(f"✅ Processed data uploaded: {blob_path}")
            logging.info(f"📊 Uploaded {len(tournaments)} tournaments as CSV")

            return blob_url

        except Exception as e:
            logging.error(f"❌ Failed to upload processed data: {e}")
            return None

    def _tournaments_to_csv(
        self, tournaments: List[Dict], run_type: str, timestamp: datetime
    ) -> str:
        """Convert tournament data to CSV format"""
        if not tournaments:
            return ""

        # Define CSV columns
        columns = [
            "tournament_name",
            "date_start",
            "date_end",
            "location_city",
            "location_state",
            "age_groups",
            "organizer",
            "tournament_type",
            "teams_count",
            "entry_fee",
            "status",
            "contact",
            "source",
            "url",
            "is_texas",
            "has_youth_ages",
            "run_type",
            "scrape_timestamp",
        ]

        # Create CSV content
        output = []

        # Add header
        output.append(",".join(columns))

        # Add data rows
        for tournament in tournaments:
            row = []
            for col in columns:
                if col == "run_type":
                    value = run_type
                elif col == "scrape_timestamp":
                    value = timestamp.isoformat()
                elif col == "tournament_name":
                    value = tournament.get("name", "")
                elif col == "location_city":
                    # Parse location to extract city
                    location = tournament.get("location", "")
                    if location and "," in location:
                        value = location.split(",")[0].strip()
                    else:
                        value = location
                elif col == "location_state":
                    # Parse location to extract state
                    location = tournament.get("location", "")
                    if location and "," in location:
                        parts = location.split(",")
                        value = parts[1].strip() if len(parts) > 1 else ""
                    else:
                        value = ""
                elif col == "teams_count":
                    value = tournament.get("teams", "")
                elif col == "is_texas":
                    location = tournament.get("location", "")
                    value = "True" if "TX" in str(location).upper() else "False"
                elif col == "has_youth_ages":
                    age_group = str(tournament.get("age_groups", ""))
                    value = (
                        "True"
                        if any(x in age_group for x in ["U", "youth", "Youth"])
                        else "False"
                    )
                else:
                    value = tournament.get(col, "")

                # Clean and escape value for CSV
                value = str(value).replace('"', '""') if value else ""
                if "," in value or '"' in value or "\n" in value:
                    value = f'"{value}"'

                row.append(value)

            output.append(",".join(row))

        return "\n".join(output)

    def upload_both_formats(
        self,
        tournaments: List[Dict],
        run_type: str = "manual",
        timestamp: datetime = None,
    ) -> Dict[str, Optional[str]]:
        """
        Upload tournament data in both raw (JSON) and processed (CSV) formats

        Args:
            tournaments: List of tournament dictionaries
            run_type: Type of scraper run ("manual" or "scheduled")
            timestamp: Override timestamp (defaults to now)

        Returns:
            Dictionary with raw_url and processed_url
        """
        if timestamp is None:
            timestamp = datetime.now()

        results = {
            "raw_url": None,
            "processed_url": None,
            "timestamp": timestamp.isoformat(),
            "count": len(tournaments) if tournaments else 0,
        }

        if not tournaments:
            logging.warning("⚠️ No tournament data to upload")
            return results

        logging.info(
            f"🚀 Uploading {len(tournaments)} tournaments to Azure Data Lake..."
        )

        # Upload raw JSON data
        raw_url = self.upload_raw_data(tournaments, run_type, timestamp)
        results["raw_url"] = raw_url

        # Upload processed CSV data
        processed_url = self.upload_processed_data(tournaments, run_type, timestamp)
        results["processed_url"] = processed_url

        if raw_url and processed_url:
            logging.info("🎉 Successfully uploaded data in both formats!")
        elif raw_url or processed_url:
            logging.warning("⚠️ Partial upload success - check logs for details")
        else:
            logging.error("❌ Upload failed for both formats")

        return results

    # ------------------------------------------------------------------
    # De-duplicated "master" upload
    #
    # Instead of writing a full snapshot every run (which piles up duplicate
    # tournaments in the lake), maintain a single canonical, de-duplicated
    # dataset at curated/tournaments_master.{json,csv}. Each run merges in
    # only the tournaments not already present, so the lake holds exactly one
    # copy of each unique tournament.
    # ------------------------------------------------------------------
    MASTER_JSON_BLOB = "curated/tournaments_master.json"
    MASTER_CSV_BLOB = "curated/tournaments_master.csv"

    @staticmethod
    def dedupe_key(t: Dict) -> str:
        """Stable identity for a tournament (records have no id/url field)."""
        for f in ("id", "tournament_id", "event_id", "url", "website_url", "link"):
            v = t.get(f)
            if v:
                return "id:" + str(v).strip().lower()
        name = (t.get("name") or t.get("tournament_name") or "").strip().lower()
        date = (t.get("start_date") or t.get("date") or t.get("dates") or "").strip().lower()
        loc = (t.get("location") or t.get("city") or "").strip().lower()
        return f"{name}|{date}|{loc}"

    def _load_master(self) -> List[Dict]:
        """Return the current de-duplicated tournament list, or [] if none."""
        if not self.blob_service_client:
            return []
        try:
            bc = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=self.MASTER_JSON_BLOB
            )
            raw = bc.download_blob().readall()
            data = json.loads(raw)
            if isinstance(data, dict):
                items = data.get("tournaments", [])
            elif isinstance(data, list):
                items = data
            else:
                items = []
            return [t for t in items if isinstance(t, dict)]
        except Exception:
            # Missing master (first run) or unreadable → treat as empty.
            return []

    @staticmethod
    def _to_csv(tournaments: List[Dict]) -> str:
        """Loss-tolerant CSV over the union of all fields (stable column order)."""
        import csv
        import io

        if not tournaments:
            return ""
        preferred = [
            "name", "date", "location", "organizer", "age_groups",
            "tournament_type", "is_texas", "has_youth_ages",
        ]
        keys = list(preferred)
        for t in tournaments:
            for k in t.keys():
                if k not in keys:
                    keys.append(k)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for t in tournaments:
            row = {}
            for k in keys:
                v = t.get(k, "")
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, default=str)
                row[k] = v
            w.writerow(row)
        return buf.getvalue()

    def upload_unique(
        self, tournaments: List[Dict], run_type: str = "automated"
    ) -> Dict[str, Optional[object]]:
        """Merge only NEW tournaments into the canonical de-duplicated master.

        Returns: {new, total_unique, raw_url, processed_url, skipped}
        """
        result = {
            "new": 0,
            "total_unique": 0,
            "skipped": 0,
            "raw_url": None,
            "processed_url": None,
        }
        if not self.blob_service_client:
            logging.warning("⚠️ Azure Data Lake not available - skipping upload")
            return result

        incoming = [t for t in (tournaments or []) if isinstance(t, dict)]
        existing = self._load_master()
        result["total_unique"] = len(existing)

        seen = {self.dedupe_key(t) for t in existing}
        new_items = []
        for t in incoming:
            k = self.dedupe_key(t)
            if k in seen:
                continue
            seen.add(k)
            new_items.append(t)

        result["skipped"] = len(incoming) - len(new_items)

        if not new_items:
            logging.info(
                f"🟰 No new tournaments (all {len(incoming)} already stored). "
                f"Master unchanged at {len(existing)} unique."
            )
            return result

        merged = existing + new_items
        payload = {
            "metadata": {
                "updated_at": datetime.now().isoformat(),
                "run_type": run_type,
                "unique_count": len(merged),
                "added_this_run": len(new_items),
                "data_format": "deduped_master",
            },
            "tournaments": merged,
        }
        try:
            jbc = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=self.MASTER_JSON_BLOB
            )
            jbc.upload_blob(
                json.dumps(payload, indent=2, default=str).encode("utf-8"),
                overwrite=True, content_type="application/json",
            )
            result["raw_url"] = jbc.url

            cbc = self.blob_service_client.get_blob_client(
                container=self.container_name, blob=self.MASTER_CSV_BLOB
            )
            cbc.upload_blob(
                self._to_csv(merged).encode("utf-8"),
                overwrite=True, content_type="text/csv",
            )
            result["processed_url"] = cbc.url

            result["new"] = len(new_items)
            result["total_unique"] = len(merged)
            logging.info(
                f"✅ Master updated: +{len(new_items)} new, "
                f"{result['skipped']} duplicates skipped, "
                f"{len(merged)} unique total."
            )
        except Exception as e:
            logging.error(f"❌ Failed to update de-duplicated master: {e}")
        return result

    def test_connection(self) -> bool:
        """Test connection to Azure Data Lake"""
        if not self.blob_service_client:
            return False

        try:
            # Try to list containers as a connection test
            containers = list(self.blob_service_client.list_containers())
            logging.info(f"✅ Azure Data Lake connection test successful")
            logging.info(f"📁 Found {len(containers)} containers")
            return True
        except Exception as e:
            logging.error(f"❌ Azure Data Lake connection test failed: {e}")
            return False


def install_azure_dependencies():
    """Install required Azure SDK packages"""
    try:
        import subprocess
        import sys

        packages = ["azure-storage-blob>=12.0.0", "azure-identity>=1.12.0"]

        for package in packages:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

        print("✅ Azure dependencies installed successfully!")
        return True
    except Exception as e:
        print(f"❌ Failed to install Azure dependencies: {e}")
        return False


if __name__ == "__main__":
    # Test the uploader
    print("🧪 Testing Azure Data Lake Storage Uploader...")

    uploader = AzureDataLakeUploader()

    if uploader.test_connection():
        print("✅ Connection test passed!")

        # Test with sample data
        sample_tournaments = [
            {
                "tournament_name": "Test Tournament",
                "location": "Houston, TX",
                "age_group": "10U",
                "organizer": "Test Organizer",
                "source": "test_data",
            }
        ]

        result = uploader.upload_both_formats(sample_tournaments, "test")
        print(f"Upload result: {result}")
    else:
        print("❌ Connection test failed!")
