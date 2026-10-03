"""Notify the owner through a Feishu application bot without logging credentials."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://open.feishu.cn/open-apis/"


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


def make_summary() -> str:
    dry_run = os.environ.get("DRY_RUN") == "true"
    ok = os.environ.get("JOB_STATUS") == "success" and os.environ.get("SENDER_OUTCOME") == "success"
    succeeded = 0
    sent_people = 0
    result_path = Path("artifacts/result.json")
    if result_path.exists():
        try:
            results = json.loads(result_path.read_text(encoding="utf-8"))["results"]
            succeeded = sum(item["status"] == "success" for item in results)
            sent_people = sum(item.get("sent", 0) > 0 for item in results)
        except (OSError, ValueError, KeyError, TypeError):
            ok = False
    else:
        ok = False
    if dry_run:
        if ok:
            return f"名单检查好了 ✅\n{succeeded} 个聊天都能找到。\n这次没有发消息。"
        return "这次检查没完成 ⚠️\n没有发送抖音消息。\n告诉我一声，我来检查。"
    if ok and sent_people:
        return f"今天的火花消息发好了 🔥\n已发给 {sent_people} 位好友。"
    if ok:
        return "今天没有发送新消息。\n如果你原本希望发送，告诉我一声。"
    if sent_people:
        return f"今天的消息没发完 ⚠️\n已经发给 {sent_people} 位好友。\n先别重复发送，告诉我一声，我来检查。"
    return "今天的火花消息没发出去 ⚠️\n告诉我一声，我来检查。"


def main() -> int:
    summary = make_summary()
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary.replace("\n", "\n\n") + "\n")
    app_id = os.environ.get("FEISHU_APP_ID")
    secret = os.environ.get("FEISHU_APP_SECRET")
    receive_id = os.environ.get("FEISHU_RECEIVE_ID")
    if not all((app_id, secret, receive_id)):
        print("::error::Feishu notification credentials are incomplete.")
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
        return 1
    print("Feishu notification delivered successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
