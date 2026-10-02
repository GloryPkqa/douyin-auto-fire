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
    mode = "预演检查（未发送抖音消息）" if dry_run else "正式发送"
    status = "完成" if ok else "未完成，请查看运行记录"
    lines = ["抖音续火花", f"模式：{mode}", f"结果：{status}"]
    result_path = Path("artifacts/result.json")
    if result_path.exists():
        try:
            results = json.loads(result_path.read_text(encoding="utf-8"))["results"]
            succeeded = sum(item["status"] == "success" for item in results)
            failed = sum(item["status"] == "failed" for item in results)
            sent = sum(item.get("sent", 0) for item in results)
            lines += [f"检查成功：{succeeded}，失败：{failed}", f"实际发送条数：{sent}"]
        except (ValueError, KeyError, TypeError):
            lines.append("统计结果无法读取，请查看运行记录。")
    else:
        lines.append("任务未产生统计结果，请查看运行记录。")
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    lines.append(f"运行记录：{run_url}")
    return "\n".join(lines)


def main() -> int:
    summary = make_summary()
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
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
