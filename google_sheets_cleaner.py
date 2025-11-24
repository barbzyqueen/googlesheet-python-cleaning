# google_sheets_cleaner.py

import os
import json
import re
import gspread
import pandas as pd
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from typing import List, Optional

# -----------------------------
# CONFIG
# -----------------------------
RAW_SHEET_NAME = "trends-history"
PROCESS_SHEET_NAME = "trends-history-process"
CLEANED_SHEET_NAME = "trends-history-cleaned"
LOG_SHEET_NAME = "automation-log"

# ---------------------------------------------------------
# LOGGING (writes into automation-log sheet)
# ---------------------------------------------------------
def log(message: str, client):
    """
    Write timestamped log message to automation-log sheet.
    Creates the sheet if missing.
    """
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
    if date_str is None:
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
            continue

    # Last fallback using pandas
    try:
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()
    except Exception:
        return None

# ---------------------------------------------------------
# FIND NETWORK NAME
# ---------------------------------------------------------
def find_network_name_in_header(cells: List[str]) -> str:
    if len(cells) > 1 and cells[1]:
        m = re.search(r"([A-Za-z0-9 &\-\_\.]+)\s*:", cells[1])
        if m:
            return m.group(1).strip()

        simple = re.sub(r"[\"']", "", cells[1]).strip()
        if ":" in simple:
            return simple.split(":")[0].strip()

    joined = " ".join([str(c) for c in cells if c])
    m = re.search(r"([A-Za-z0-9 &\-\_\.]+)\s*:", joined)
    if m:
        return m.group(1).strip()

    if len(cells) > 0 and ":" in str(cells[0]):
        return str(cells[0]).split(":")[0].replace("'", "").strip()

    return "UNKNOWN"

# ---------------------------------------------------------
# MAIN CLEANING FUNCTION (FastAPI calls this)
# ---------------------------------------------------------
def run_cleaning_process():
    """
    Runs the full workflow:
    - reads raw sheet
    - detects blocks
    - parses blocks
    - writes to process sheet
    - appends new rows to cleaned sheet
    Returns a status message.
    """

    client = None

    try:
        # -----------------------------
        # AUTHENTICATE
        # -----------------------------
        service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not service_account_json:
            return "Error: GOOGLE_SERVICE_ACCOUNT_JSON not set"

        credentials_dict = json.loads(service_account_json)
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive",
        ]

        creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
        client = gspread.authorize(creds)

        # Open sheets
        raw_sheet = client.open(RAW_SHEET_NAME).sheet1
        process_sheet = client.open(PROCESS_SHEET_NAME).sheet1
        cleaned_sheet = client.open(CLEANED_SHEET_NAME).sheet1

        log("----- Script Started -----", client)

        # -----------------------------
        # READ RAW SHEET
        # -----------------------------
        raw_values = raw_sheet.get_all_values()
        max_cols = max((len(r) for r in raw_values), default=0)
        normalized_rows = [r + [""] * (max_cols - len(r)) for r in raw_values]

        # -----------------------------
        # IDENTIFY BLOCKS
        # -----------------------------
        blocks = []
        i = 0
        n = len(normalized_rows)

        while i < n:
            row = normalized_rows[i]
            first = str(row[0]).strip().lower() if len(row) > 0 else ""
            header_detected = False

            if first in ("day", "week"):
                header_detected = True
            elif any(":" in str(c) for c in row[:3]):
                for c in row[:3]:
                    cs = str(c).strip()
                    if ":" in cs:
                        left = cs.split(":")[0].strip().lower()
                        if left != "category":
                            header_detected = True
                            break

            if header_detected:
                header_row = row
                block_rows = [header_row]
                j = i + 1

                while j < n:
                    rj = normalized_rows[j]
                    if all(str(c).strip() == "" for c in rj):
                        break

                    first_j = str(rj[0]).strip().lower()
                    if first_j in ("day", "week"):
                        break

                    if any(":" in str(c) for c in rj[:3]):
                        cs = str(rj[1]).strip()
                        if ":" in cs:
                            break

                    block_rows.append(rj)
                    j += 1

                blocks.append(block_rows)
                i = j + 1
            else:
                i += 1

        log(f"Detected {len(blocks)} blocks in raw sheet.", client)

        # -----------------------------
        # PARSE BLOCKS
        # -----------------------------
        cleaned_blocks = []

        for b_idx, block in enumerate(blocks, start=1):
            header = block[0]
            network = find_network_name_in_header(header)

            parsed_rows = []

            for r in block[1:]:
                date_candidate = None
                value_candidate = None

                if len(r) >= 2 and r[0].strip() and r[1].strip():
                    date_candidate = r[0].strip()
                    value_candidate = r[1].strip()
                else:
                    tokens = [x.strip() for x in r if x.strip()]
                    if len(tokens) >= 2:
                        date_candidate = tokens[0]
                        value_candidate = tokens[1]

                if not date_candidate:
                    continue

                parsed_date = parse_date_try_formats(date_candidate)
                if parsed_date is None:
                    continue

                try:
                    interest = float(value_candidate)
                except:
                    continue

                parsed_rows.append({
                    "Date": parsed_date.strftime("%Y-%m-%d"),
                    "Interest": interest,
                    "Network": network
                })

            if parsed_rows:
                df_block = pd.DataFrame(parsed_rows).drop_duplicates(
                    subset=["Date", "Network"]
                )
                cleaned_blocks.append(df_block)
            else:
                log(f"Block {b_idx} ({network}) had no valid rows; skipped.", client)

        if not cleaned_blocks:
            log("No valid rows found in any block.", client)
            return "No valid data found."

        df_process = pd.concat(cleaned_blocks, ignore_index=True)
        df_process = df_process.sort_values(["Network", "Date"]).reset_index(drop=True)

        # -----------------------------
        # WRITE PROCESS SHEET
        # -----------------------------
        process_sheet.clear()
        process_sheet.update(
            [df_process.columns.tolist()] +
            df_process.astype(str).values.tolist()
        )
        log(f"Updated process sheet with {len(df_process)} rows.", client)

        # -----------------------------
        # APPEND NEW DATA TO CLEANED SHEET
        # -----------------------------
        cleaned_vals = cleaned_sheet.get_all_values()

        if len(cleaned_vals) <= 1:
            cleaned_sheet.clear()
            cleaned_sheet.update(
                [df_process.columns.tolist()] +
                df_process.astype(str).values.tolist()
            )
            log(
                f"Cleaned sheet was empty. Wrote all {len(df_process)} rows.",
                client
            )
            log("----- Script Finished -----", client)
            return f"Inserted all {len(df_process)} rows (first run)."

        df_cleaned = pd.DataFrame(cleaned_vals[1:], columns=cleaned_vals[0])
        df_cleaned["Date"] = pd.to_datetime(df_cleaned["Date"], errors="coerce")

        df_process["Date_dt"] = pd.to_datetime(df_process["Date"], errors="coerce")
        max_existing_date = df_cleaned["Date"].max()

        existing_pairs = set(
            (str(d.date()), n)
            for d, n in zip(df_cleaned["Date"], df_cleaned["Network"])
        )

        df_process["Date_only"] = df_process["Date_dt"].dt.date

        mask_new_date = df_process["Date_dt"] > max_existing_date
        mask_new_pair = df_process.apply(
            lambda r: (str(r["Date_only"]), r["Network"]) not in existing_pairs,
            axis=1
        )
        mask_final = mask_new_date & mask_new_pair

        df_to_append = df_process[mask_final].copy()
        df_to_append = df_to_append.drop(columns=["Date_dt", "Date_only"], errors="ignore")

        if df_to_append.empty:
            log("No new rows to append.", client)
            log("----- Script Finished -----", client)
            return "No new rows."

        cleaned_sheet.append_rows(df_to_append.astype(str).values.tolist())
        log(f"Appended {len(df_to_append)} new rows to cleaned sheet.", client)

        log("----- Script Finished -----", client)
        return f"Appended {len(df_to_append)} new rows."

    except Exception as e:
        # SAFELY LOG ERRORS
        if client:
            try:
                log(f"Error: {repr(e)}", client)
            except:
                pass
        return f"Error: {repr(e)}"
