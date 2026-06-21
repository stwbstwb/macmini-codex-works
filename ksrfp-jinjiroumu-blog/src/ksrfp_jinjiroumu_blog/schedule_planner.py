from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .io_utils import read_json, write_json, write_markdown
from .paths import CONFIG_DIR, STATE_DIR, GENERATED_DIR


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def build_schedule_plan(now: datetime | None = None) -> dict[str, Any]:
    settings = read_json(CONFIG_DIR / "project_settings.json", {}) or {}
    schedule = settings.get("schedule", {})
    post_status = str(settings.get("default_post_status") or "draft")
    tz_name = schedule.get("timezone") or settings.get("timezone") or "Asia/Tokyo"
    tz = ZoneInfo(tz_name)
    current = now.astimezone(tz) if now else datetime.now(tz)
    target_weekday = WEEKDAYS.get(str(schedule.get("weekday", "monday")).lower(), 0)
    target_hour = int(schedule.get("hour") or 9)
    target_minute = int(schedule.get("minute") or 0)
    ignore_conflicts = bool(schedule.get("ignore_conflicts_for_draft")) and post_status == "draft"
    reserved_slots = set() if ignore_conflicts else load_reserved_slots()
    wordpress_check = (
        {"slots": set(), "checked": False, "source": "conflict_check_skipped_for_draft", "error": None}
        if ignore_conflicts
        else load_wordpress_future_slots(settings, tz)
    )
    reserved_slots.update(wordpress_check["slots"])

    candidate = nearest_future_weekday_at(current, target_weekday, target_hour, target_minute)
    if schedule.get("same_day_policy") == "next_week" and candidate.date() == current.date():
        candidate += timedelta(days=7)
    skipped: list[str] = []
    while local_slot_key(candidate) in reserved_slots:
        skipped.append(candidate.isoformat(timespec="seconds"))
        candidate += timedelta(days=7)

    plan = {
        "status": "ok",
        "generated_at": datetime.now(tz).isoformat(timespec="seconds"),
        "timezone": tz_name,
        "target_weekday": schedule.get("weekday", "monday"),
        "target_time": f"{target_hour:02d}:{target_minute:02d}",
        "scheduled_local": candidate.isoformat(timespec="seconds"),
        "scheduled_gmt": candidate.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scheduled_date_for_wordpress": candidate.isoformat(timespec="seconds"),
        "scheduled_date_gmt_for_wordpress": candidate.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", ""),
        "skipped_conflicting_slots": skipped,
        "conflict_check_source": wordpress_check["source"],
        "wordpress_future_posts_checked": wordpress_check["checked"],
        "wordpress_future_posts_error": wordpress_check.get("error"),
        "post_status": post_status,
        "ignore_conflicts_for_draft": ignore_conflicts,
        "note": "下書き保存では3件すべて同じ翌週月曜9:00の日付を設定する。future投稿として公開予約する場合のみ衝突回避を行う。",
    }
    write_json(GENERATED_DIR / "wordpress-payloads" / "schedule_plan_latest.json", plan)
    write_markdown(GENERATED_DIR / "wordpress-payloads" / "schedule_plan_latest.md", render_schedule_plan(plan))
    return plan


def nearest_future_weekday_at(current: datetime, weekday: int, hour: int, minute: int) -> datetime:
    days_ahead = (weekday - current.weekday()) % 7
    candidate = (current + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=7)
    return candidate


def load_reserved_slots() -> set[str]:
    payload = read_json(STATE_DIR / "scheduled_posts.json", {"items": []}) or {"items": []}
    slots = set()
    for item in payload.get("items", []):
        if item.get("status") in {"scheduled", "posted", "published", "future"} and item.get("scheduled_local"):
            slots.add(local_slot_key_from_text(str(item["scheduled_local"])))
    return slots


def load_wordpress_future_slots(settings: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    if not settings.get("enable_external_api_calls"):
        return {"slots": set(), "checked": False, "source": "local_state_only"}
    try:
        from .wordpress_client import read_wordpress_credentials

        credentials = read_wordpress_credentials()
        if not credentials.get("ready"):
            return {
                "slots": set(),
                "checked": False,
                "source": "local_state_only",
                "error": "WordPress credentials are not ready.",
            }
        posts = fetch_wordpress_future_posts(
            str(settings.get("wordpress_api_base", "")).rstrip("/"),
            credentials["username"],
            credentials["application_password"],
        )
        slots = set()
        for post in posts:
            post_date = post.get("date")
            if not post_date:
                continue
            slots.add(local_slot_key(parse_wordpress_local_datetime(post_date, tz)))
        return {"slots": slots, "checked": True, "source": "wordpress_api_and_local_state"}
    except Exception as exc:
        return {
            "slots": set(),
            "checked": False,
            "source": "local_state_only",
            "error": str(exc),
        }


def fetch_wordpress_future_posts(api_base: str, username: str, application_password: str) -> list[dict[str, Any]]:
    token = base64.b64encode(f"{username}:{application_password}".encode("utf-8")).decode("ascii")
    params = urlencode(
        {
            "status": "future",
            "per_page": "100",
            "orderby": "date",
            "order": "asc",
            "_fields": "id,date,date_gmt,status,link,title",
        }
    )
    request = Request(f"{api_base}/posts?{params}", headers={"Authorization": f"Basic {token}"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_wordpress_local_datetime(value: str, tz: ZoneInfo) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def local_slot_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


def local_slot_key_from_text(value: str) -> str:
    return value[:16]


def render_schedule_plan(plan: dict[str, Any]) -> str:
    lines = [
        "# 予約投稿スケジュール計画",
        "",
        f"- 生成日時: {plan['generated_at']}",
        f"- 投稿曜日: {plan['target_weekday']}",
        f"- 投稿時刻: {plan['target_time']}",
        f"- タイムゾーン: {plan['timezone']}",
        f"- 予約日時: {plan['scheduled_local']}",
        f"- WordPress date: {plan['scheduled_date_for_wordpress']}",
        f"- WordPress date_gmt: {plan['scheduled_date_gmt_for_wordpress']}",
        f"- 投稿ステータス: {plan.get('post_status', '未設定')}",
        f"- 下書き同日付許可: {plan.get('ignore_conflicts_for_draft', False)}",
        f"- 衝突確認: {plan['conflict_check_source']}",
        f"- WordPress予約投稿確認済み: {plan['wordpress_future_posts_checked']}",
        f"- WordPress予約投稿確認エラー: {plan.get('wordpress_future_posts_error') or 'なし'}",
        "",
        "## スキップした予約枠",
        "",
    ]
    if plan["skipped_conflicting_slots"]:
        lines.extend(f"- {slot}" for slot in plan["skipped_conflicting_slots"])
    else:
        lines.append("- なし")
    lines.extend(["", "## 注意", "", plan["note"]])
    return "\n".join(lines)
