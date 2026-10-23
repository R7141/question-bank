"""MinerU 4.x V1 API 客户端:PDF → Markdown。

只负责"提交异步任务 → 轮询 → 取回结果 zip/Markdown";图片落地与路径重写由
`PdfIngestor` 复用现有 markdown 归档逻辑完成。MinerU 版本差异被限制在本模块。

接口契约以 MinerU 4.0 运行实例的 OpenAPI 为准:
- POST /v1/tasks?tier=...&output_formats=markdown&output_formats=zip
- GET  /v1/tasks/{task_id}
- GET  /v1/tasks/{task_id}/result?response_format=zip
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TERMINAL_FAILED = {"failed", "canceled", "cancelled", "partial"}
_TERMINAL_OK = {"completed", "success", "succeeded"}


class MinerUError(RuntimeError):
    """MinerU 调用失败;文案直接面向用户。"""


class MinerUConfigurationError(MinerUError):
    """未配置 MinerU 服务地址。"""


@dataclass
class MinerUParseResult:
    """转换产物:正常路径返回 zip 路径,兼容分支返回内联 Markdown。"""

    zip_path: Optional[Path] = None
    markdown: Optional[str] = None
    remote_task_id: Optional[str] = None


def _snippet(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


class MinerUClient:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        tier: Optional[str] = None,
        poll_interval: Optional[float] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        configured = (base_url if base_url is not None else settings.MINERU_API_URL).strip()
        # 允许用户误填 .../v1 或末尾斜杠,统一归一,避免拼成 /v1/v1/tasks。
        configured = configured.rstrip("/")
        if configured.endswith("/v1"):
            configured = configured[:-3].rstrip("/")
        self.base_url = configured
        self.api_key = (api_key if api_key is not None else settings.MINERU_API_KEY).strip()
        self.tier = (tier if tier is not None else settings.MINERU_TIER).strip() or "standard"
        self.poll_interval = max(
            0.2,
            poll_interval
            if poll_interval is not None
            else settings.MINERU_POLL_INTERVAL_SECONDS,
        )
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @asynccontextmanager
    async def _client(self, *, timeout: float) -> AsyncIterator[httpx.AsyncClient]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        client_timeout = httpx.Timeout(
            connect=10.0,
            read=max(float(timeout), 30.0),
            write=300.0,
            pool=10.0,
        )
        async with httpx.AsyncClient(
            base_url=f"{self.base_url}/",
            headers=headers,
            timeout=client_timeout,
            transport=self._transport,
        ) as client:
            yield client

    async def parse_pdf(
        self,
        file_path: Path,
        *,
        task_id: str,
        timeout: Optional[int] = None,
        on_submitted: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> MinerUParseResult:
        """把 PDF 转成 Markdown 或结果 zip。调用方负责后续图片路径重写。"""
        if not self.configured:
            raise MinerUConfigurationError(
                "未配置 MinerU，无法导入 PDF。请设置 MINERU_API_URL 后重试。"
            )

        timeout_seconds = int(timeout or settings.MINERU_TIMEOUT_SECONDS)
        deadline = time.monotonic() + max(timeout_seconds, 1)

        data = await asyncio.to_thread(file_path.read_bytes)
        if not data:
            raise MinerUError("PDF 文件为空，无法转换。")

        async with self._client(timeout=timeout_seconds) as client:
            remote_task_id = await self._submit(client, filename=file_path.name, data=data)
            logger.info("MinerU task %s submitted for %s", remote_task_id, file_path.name)
            if on_submitted is not None:
                await on_submitted(remote_task_id)
            await self._wait(client, remote_task_id, deadline)
            result = await self._download(
                client, remote_task_id, task_id=task_id, deadline=deadline
            )
            result.remote_task_id = remote_task_id
            return result

    async def cancel_task(self, remote_task_id: str) -> None:
        """Best-effort cancel of a queued/running MinerU task (DELETE /v1/tasks/{id})."""
        if not self.configured or not remote_task_id:
            return
        try:
            async with self._client(timeout=30) as client:
                response = await client.delete(f"v1/tasks/{remote_task_id}")
                if response.status_code >= 400 and response.status_code != 404:
                    logger.warning(
                        "MinerU cancel %s failed: HTTP %s %s",
                        remote_task_id,
                        response.status_code,
                        _snippet(response.text),
                    )
        except httpx.HTTPError as exc:
            logger.warning("MinerU cancel %s failed: %s", remote_task_id, exc)

    async def _submit(self, client: httpx.AsyncClient, *, filename: str, data: bytes) -> str:
        try:
            response = await client.post(
                "v1/tasks",
                params=[
                    ("tier", self.tier),
                    ("output_formats", "markdown"),
                    ("output_formats", "zip"),
                ],
                files=[("files", (filename, data, "application/pdf"))],
            )
        except httpx.HTTPError as exc:
            raise MinerUError(f"连接 MinerU 失败: {exc}") from exc

        payload = self._checked_json(response, action="提交 MinerU 任务")
        task_id = (
            payload.get("task_id")
            or payload.get("id")
            or (payload.get("data") or {}).get("task_id")
            or (payload.get("data") or {}).get("id")
        )
        if not task_id:
            raise MinerUError(f"MinerU 未返回 task_id: {_snippet(payload)}")
        return str(task_id)

    async def _wait(
        self, client: httpx.AsyncClient, remote_task_id: str, deadline: float
    ) -> None:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MinerUError("MinerU 转换超时，请稍后重试或改用批量导入。")

            try:
                response = await client.get(f"v1/tasks/{remote_task_id}", timeout=30.0)
            except httpx.HTTPError as exc:
                raise MinerUError(f"查询 MinerU 任务失败: {exc}") from exc

            payload = self._checked_json(response, action="查询 MinerU 任务")
            status = str(
                payload.get("status")
                or payload.get("state")
                or (payload.get("data") or {}).get("status")
                or ""
            ).lower()

            if status in _TERMINAL_OK:
                return
            if status in _TERMINAL_FAILED:
                raise MinerUError(self._task_error(payload, status))

            await asyncio.sleep(min(self.poll_interval, max(remaining, 0.2)))

    async def _download(
        self,
        client: httpx.AsyncClient,
        remote_task_id: str,
        *,
        task_id: str,
        deadline: float,
    ) -> MinerUParseResult:
        remaining = max(deadline - time.monotonic(), 30.0)
        try:
            response = await client.get(
                f"v1/tasks/{remote_task_id}/result",
                params={"response_format": "zip"},
                timeout=remaining,
            )
        except httpx.HTTPError as exc:
            raise MinerUError(f"下载 MinerU 转换结果失败: {exc}") from exc

        if response.status_code >= 400:
            self._raise_response(response, action="下载 MinerU 转换结果")

        content_type = response.headers.get("content-type", "").lower()
        body = response.content
        if body.startswith(b"PK") or "zip" in content_type:
            zip_path = settings.UPLOAD_DIR / task_id / "mineru_result.zip"
            await asyncio.to_thread(zip_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(zip_path.write_bytes, body)
            return MinerUParseResult(
                zip_path=zip_path, remote_task_id=remote_task_id
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MinerUError(
                f"MinerU 返回了无法识别的结果（{content_type or 'unknown'}）。"
            ) from exc

        markdown = self._markdown_from_payload(payload)
        if not markdown:
            raise MinerUError(f"MinerU 结果中没有 Markdown: {_snippet(payload)}")
        return MinerUParseResult(markdown=markdown, remote_task_id=remote_task_id)

    def _checked_json(self, response: httpx.Response, *, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            self._raise_response(response, action=action)
        try:
            payload = response.json()
        except ValueError as exc:
            raise MinerUError(f"{action}失败: MinerU 未返回 JSON。") from exc
        if not isinstance(payload, dict):
            raise MinerUError(f"{action}失败: {_snippet(payload)}")
        return payload

    def _raise_response(self, response: httpx.Response, *, action: str) -> None:
        detail = ""
        try:
            payload = response.json()
            detail = (
                payload.get("detail")
                or payload.get("error")
                or payload.get("message")
                or payload
            )
        except ValueError:
            detail = response.text
        raise MinerUError(
            f"{action}失败（HTTP {response.status_code}）: {_snippet(detail)}"
        )

    @staticmethod
    def _task_error(payload: dict[str, Any], status: str) -> str:
        detail = (
            payload.get("error")
            or payload.get("error_msg")
            or payload.get("message")
            or payload.get("detail")
            or (payload.get("data") or {}).get("error")
            or (payload.get("data") or {}).get("message")
        )
        if detail:
            return f"MinerU 转换失败（{status}）: {_snippet(detail)}"
        return f"MinerU 转换失败（{status}）。"

    @staticmethod
    def _markdown_from_payload(payload: dict[str, Any]) -> str:
        content = payload.get("content")
        if isinstance(content, dict) and content.get("markdown"):
            return str(content["markdown"])

        files = payload.get("files")
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                item_content = item.get("content")
                if isinstance(item_content, dict) and item_content.get("markdown"):
                    return str(item_content["markdown"])

        results = payload.get("results")
        if isinstance(results, dict):
            for item in results.values():
                if isinstance(item, dict) and item.get("md_content"):
                    return str(item["md_content"])
        return ""
