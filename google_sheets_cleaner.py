# google_sheets_cleaner.py

import os
import json
import re
import gspread
import pandas as pd
from datetime import datetime
from google.oauth2 import service_account
from typing import List, Optional

RAW_SHEET_NAME = "trends-history"
PROCESS_SHEET_NAME = "trends-history-process"
CLEANED_SHEET_NAME = "trends-history-cleaned"
LOG_SHEET_NAME = "automation-log"


# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
def log(message: str, client):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        log_sheet = client.open(LOG_SHEET_NAME).sheet1
    except gspread.SpreadsheetNotFound:
        new_sheet = client.create(LOG_SHEET_NAME)
        log_sheet = new_sheet.sheet1
        log_sheet.append_row(["Timestamp", "Message"])

    log_sheet.append_row([timestamp, message])


# ---------------------------------------------------------
# DATE PARSER
# ---------------------------------------------------------
def parse_date_try_formats(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None

    s = str(date_str).strip()
    if s == "":
        return None

    formats = [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%d %b %Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass

    try:
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()
    except Exception:
        return None


# ---------------------------------------------------------
# NETWORK NAME EXTRACTION
# ---------------------------------------------------------
def find_network_name_in_header(cells: List[str]) -> str:
    if len(cells) > 1 and cells[1]:
        text = str(cells[1])
        m = re.search(r"([A-Za-z0-9 &\-\_\.]+)\s*:", text)
        if m:
            return m.group(1).strip()

        if ":" in text:
            return text.split(":")[0].strip()

    joined = " ".join([str(c) for c in cells if c])
    m = re.search(r"([A-Za-z0-9 &\-\_\.]+)\s*:", joined)
    if m:
        return m.group(1).strip()

    return "UNKNOWN"


# ---------------------------------------------------------
# MAIN CLEANING FUNCTION
# ---------------------------------------------------------
def run_cleaning_process():
    client = None

    try:
        # AUTH
        json_content = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not json_content:
            return "Error: GOOGLE_SERVICE_ACCOUNT_JSON not set"

        creds_dict = json.loads(json_content)
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=scope
        )
        client = gspread.authorize(creds)

        raw_sheet = client.open(RAW_SHEET_NAME).sheet1
        process_sheet = client.open(PROCESS_SHEET_NAME).sheet1
        cleaned_sheet = client.open(CLEANED_SHEET_NAME).sheet1

        log("----- Script Started -----", client)

        # LOAD RAW
        raw_rows = raw_sheet.get_all_values()
        max_cols = max((len(r) for r in raw_rows), default=0)
        rows = [r + [""] * (max_cols - len(r)) for r in raw_rows]

        # DETECT BLOCKS
        blocks = []
        i = 0
        n = len(rows)

        while i < n:
            row = rows[i]
            first = str(row[0]).strip().lower()

            header_found = False
            if first in ("day", "week"):
                header_found = True
            else:
                for c in row[:3]:
                    if ":" in str(c):
                        header_found = True
                        break

            if header_found:
                block = [row]
                j = i + 1
                while j < n:
                    rj = rows[j]
                    if all(str(c).strip() == "" for c in rj):
                        break
                    if str(rj[0]).strip().lower() in ("day", "week"):
                        break
                    if any(":" in str(c) for c in rj[:3]):
                        break

                    block.append(rj)
                    j += 1

                blocks.append(block)
                i = j + 1
            else:
                i += 1

        log(f"Detected {len(blocks)} blocks.", client)

        # PARSE BLOCKS
        cleaned_blocks = []

        for block in blocks:
            header = block[0]
            network = find_network_name_in_header(header)

            parsed = []
            for r in block[1:]:
                tokens = [t.strip() for t in r if t.strip()]
                if len(tokens) < 2:
                    continue

                date_raw = tokens[0]
                interest_raw = tokens[1]

                dt = parse_date_try_formats(date_raw)
                if not dt:
                    continue

                try:
                    interest = float(interest_raw)
                except:
                    continue

                parsed.append({
                    "Date": dt.strftime("%Y-%m-%d"),
                    "Interest": interest,
                    "Network": network
                })

            if parsed:
                df = pd.DataFrame(parsed)
                df = df.drop_duplicates(subset=["Date", "Network"])
                cleaned_blocks.append(df)

        if not cleaned_blocks:
            log("No valid blocks.", client)
            return "No valid data."

        # CONCAT AND REMOVE DUPLICATES ACROSS BLOCKS (NEW FIX)
        df_process = pd.concat(cleaned_blocks, ignore_index=True)

        df_process = df_process.drop_duplicates(subset=["Date", "Network"])

        df_process = df_process.sort_values(["Network", "Date"]).reset_index(drop=True)

        # WRITE PROCESS SHEET
        process_sheet.clear()
        process_sheet.update(
            [df_process.columns.tolist()] + df_process.astype(str).values.tolist()
        )

        log(f"Updated process sheet ({len(df_process)} rows).", client)

        # LOAD CLEANED SHEET
        cleaned_vals = cleaned_sheet.get_all_values()

        if len(cleaned_vals) <= 1:
            cleaned_sheet.clear()
            cleaned_sheet.update(
                [df_process.columns.tolist()] +
                df_process.astype(str).values.tolist()
            )
            log("Cleaned sheet empty → inserted all data.", client)
            return f"Inserted all {len(df_process)} rows."

        df_cleaned = pd.DataFrame(cleaned_vals[1:], columns=cleaned_vals[0])
        df_cleaned["Date"] = pd.to_datetime(df_cleaned["Date"], errors="coerce")

        df_process["Date_dt"] = pd.to_datetime(df_process["Date"], errors="coerce")
        df_process["Date_only"] = df_process["Date_dt"].dt.date

        existing_pairs = set(
            (str(d.date()), net)
            for d, net in zip(df_cleaned["Date"], df_cleaned["Network"])
        )

        def is_new(row):
            key = (str(row["Date_only"]), row["Network"])
            return key not in existing_pairs

        df_new = df_process[df_process.apply(is_new, axis=1)].copy()
        df_new = df_new.drop(columns=["Date_dt", "Date_only"], errors="ignore")

        if df_new.empty:
            log("No new rows to append.", client)
            return "No new rows."

        cleaned_sheet.append_rows(df_new.astype(str).values.tolist())
        log(f"Appended {len(df_new)} new rows.", client)
        return f"Appended {len(df_new)} new rows."

    except Exception as e:
        if client:
            try:
                log(f"Error: {repr(e)}", client)
            except:
                pass
        return f"Error: {repr(e)}"
