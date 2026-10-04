"""Notify the owner through a Feishu application bot without logging credentials."""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE_URL = "https://open.feishu.cn/open-apis/"
BEIJING = ZoneInfo("Asia/Shanghai")


def post_api(path: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(BASE_URL + path, json.dumps(payload).encode(), headers, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Feishu HTTP error {exc.code}") from None
    except (URLError, TimeoutError, ValueError):
        raise RuntimeError("Feishu network error or invalid response") from None
    if not isinstance(data, dict) or data.get("code") != 0:
        code = data.get("code", "missing") if isinstance(data, dict) else "invalid"
        raise RuntimeError(f"Feishu API rejected request (code={code})")
    return data


def read_json(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def task_names() -> list[str]:
    raw = os.environ.get("DOUYIN_CONFIG")
    try:
        config = json.loads(raw) if raw else read_json("config.json")
        targets = config.get("targets")
        names = [item["name"] for item in targets] if targets else config.get("friends", [])
        return names if isinstance(names, list) and all(isinstance(name, str) and name.strip() for name in names) else []
    except (ValueError, KeyError, TypeError, AttributeError):
        return []


def beijing_time(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(BEIJING) if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def list_lines(label: str, names: list[str]) -> list[str]:
    if not names:
        return [f"{label}：无"]
    return [f"{label}（{len(names)}人）："] + [" · ".join(names[i:i + 3]) for i in range(0, len(names), 3)]


def next_plan(reference: datetime) -> str:
    if os.environ.get("STREAK_ENABLED") != "true":
        return "下次计划：每日定时还没开启。"
    try:
        workflow = Path(".github/workflows/send.yml").read_text(encoding="utf-8-sig")
    except OSError:
        workflow = ""
    if not re.search(r"^  schedule:\s*$", workflow, re.MULTILINE) or not re.search(r"^    - cron: [\"']0 0 \* \* \*[\"']\s*$", workflow, re.MULTILINE):
        return "下次计划：暂未安排。"
    upcoming = reference.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return f"下次计划：{upcoming.month}月{upcoming.day}日 00:00（北京时间）"


def make_summary() -> str:
    dry_run = os.environ.get("DRY_RUN") == "true"
    ok = os.environ.get("JOB_STATUS") == "success" and os.environ.get("SENDER_OUTCOME") == "success"
    names = task_names()
    report = read_json("artifacts/result.json")
    metrics = read_json("artifacts/metrics.json")
    results = report.get("results", [])
    results = results if isinstance(results, list) else []
    indexed = {item["target"]: item for item in results if isinstance(item, dict) and isinstance(item.get("target"), str)}
    successful, unsuccessful, pending = [], [], []
    for index, name in enumerate(names):
        item = indexed.get(f"好友{index + 1:02d}", indexed.get(name))
        if item is None:
            pending.append(name)
        elif dry_run:
            (successful if item.get("status") == "success" else unsuccessful).append(name)
        elif isinstance(item.get("sent"), int) and item["sent"] > 0:
            successful.append(name)
        elif item.get("status") == "failed":
            unsuccessful.append(name)
        else:
            pending.append(name)
    ok = ok and bool(names) and len(successful) == len(names)
    if dry_run:
        title = "名单检查好了 ✅" if ok else "名单还没检查完 ⚠️"
    elif ok:
        title = "今天的火花消息发好了 🔥"
    elif successful:
        title = "今天的消息还没全部发完 ⚠️" if len(successful) < len(names) else "消息已发出，任务收尾没完成 ⚠️"
    else:
        title = "今天的消息还没完成 ⚠️"
    finished = beijing_time(metrics.get("finished_at")) or beijing_time(report.get("finished_at")) or datetime.now(BEIJING)
    started = beijing_time(metrics.get("started_at")) or beijing_time(os.environ.get("SENDER_STARTED_AT"))
    date = started or finished
    lines = [title, f"日期：{date.year}年{date.month}月{date.day}日", "这次只检查，没有发消息。" if dry_run else "这次是实际发送消息。"]
    if names:
        if dry_run:
            lines.append(f"人数：共{len(names)}人，{len(successful)}人已确认，{len(unsuccessful) + len(pending)}人待确认")
            lines += [""] + list_lines("已确认的好友", successful)
            lines += [""] + list_lines("暂时没确认的好友", unsuccessful + pending)
        else:
            lines.append(f"人数：共{len(names)}人，{len(successful)}人已发，{len(unsuccessful)}人没发成功，{len(pending)}人结果待确认")
            lines += [""] + list_lines("已发成功的好友", successful)
            lines += [""] + list_lines("没发成功的好友", unsuccessful)
            if pending:
                lines += [""] + list_lines("还没确认发送结果的好友", pending)
    else:
        lines.append("好友名单暂时无法读取，人数和名字还不能确认。")
    lines.append("")
    if started:
        start_label = started.strftime("%H:%M") if started.date() == finished.date() else f"{started.month}月{started.day}日 {started:%H:%M}"
        lines.append(f"开始：{start_label} ｜ 结束：{finished:%H:%M}（北京时间）")
    else:
        lines.append(f"开始：尚未取得时间 ｜ 结束：{finished:%H:%M}（北京时间）")
    lines.append(next_plan(finished))
    return "\n".join(lines)


def public_note(delivered: bool) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("通知已发送到飞书，详细名单请在飞书查看。\n" if delivered else "飞书通知未能发送，请检查通知步骤。\n")


def main() -> int:
    summary = make_summary()
    app_id = os.environ.get("FEISHU_APP_ID")
    secret = os.environ.get("FEISHU_APP_SECRET")
    receive_id = os.environ.get("FEISHU_RECEIVE_ID")
    if not all((app_id, secret, receive_id)):
        print("::error::Feishu notification credentials are incomplete.")
        public_note(False)
        return 1
    try:
        auth = post_api("auth/v3/tenant_access_token/internal", {"app_id": app_id, "app_secret": secret})
        token = auth.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Feishu token missing from successful response")
        identity = "/".join(os.environ.get(name, "") for name in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
        post_api("im/v1/messages?receive_id_type=open_id", {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": summary}, ensure_ascii=False),
            "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
        }, token)
    except RuntimeError as exc:
        print(f"::error::{exc}")
        public_note(False)
        return 1
    public_note(True)
    print("Feishu notification delivered successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
