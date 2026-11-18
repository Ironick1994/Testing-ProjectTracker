"""
Parse the MS Project file and overwrite MSP_Raw in the Quote & Scope Tracker.
Runs in GitHub Actions; authenticates with a Google service account (no expiring OAuth token).

Env:
  MPP_FILE       path to the .mpp inside the checkout
  GOOGLE_SA_KEY  service account JSON key (GitHub secret)

!! UNVERIFIED ASSUMPTIONS — check against the real .mpp before trusting the data !!
  1. Each project is a summary task at PROJECT_OUTLINE_LEVEL.
  2. The quoted duration = that summary task's duration.
  3. TG:B = Finish of the first child task whose name contains DESIGN_KEYWORD.
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import jpype
import mpxj  # noqa: F401  (puts the bundled MPXJ jars on the classpath)
from google.oauth2 import service_account
from googleapiclient.discovery import build

TRACKER_SHEET_ID = "1QB2YPla1oSbY8My-IvszHYh13AdmKn8o2p4z6seUF28"
PROJECT_OUTLINE_LEVEL = 1
DESIGN_KEYWORD = "design"
LOCAL_TZ = ZoneInfo("America/New_York")

jpype.startJVM()
from org.mpxj import TimeUnit  # noqa: E402
from org.mpxj.reader import UniversalProjectReader  # noqa: E402


def days(task, props):
    dur = task.getDuration()
    if dur is None:
        return ""
    return round(float(dur.convertUnits(TimeUnit.DAYS, props).getDuration()), 2)


def as_date(dt):
    return str(dt)[:10] if dt is not None else ""


def build_rows(project):
    props = project.getProjectProperties()
    rows = []
    for task in project.getTasks():
        lvl = task.getOutlineLevel()
        if task.getName() is None or lvl is None or int(lvl) != PROJECT_OUTLINE_LEVEL:
            continue
        tgb = ""
        for child in task.getChildTasks():
            name = child.getName()
            if name is not None and DESIGN_KEYWORD in str(name).lower():
                tgb = as_date(child.getFinish())
                break
        rows.append([str(task.getName()), days(task, props), tgb])
    return rows


def main():
    mpp_file = os.environ.get("MPP_FILE", "")
    if not mpp_file or not os.path.exists(mpp_file):
        sys.exit(f"MPP_FILE not found: {mpp_file!r}")

    project = UniversalProjectReader().read(mpp_file)
    stamp = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    rows = [r + [stamp] for r in build_rows(project)]
    if not rows:
        sys.exit("Parsed 0 projects — outline level / structure assumptions are probably wrong.")

    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    values = build("sheets", "v4", credentials=creds, cache_discovery=False) \
        .spreadsheets().values()
    values.clear(spreadsheetId=TRACKER_SHEET_ID, range="MSP_Raw!A2:D").execute()
    values.update(
        spreadsheetId=TRACKER_SHEET_ID,
        range="MSP_Raw!A2",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()
    print(f"MSP_Raw: wrote {len(rows)} projects at {stamp}")


if __name__ == "__main__":
    main()
