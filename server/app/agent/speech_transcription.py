from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import (
    SPEECH_TRANSCRIPTION_API_KEY,
    SPEECH_TRANSCRIPTION_BASE_URL,
    SPEECH_TRANSCRIPTION_MODEL,
    SPEECH_TRANSCRIPTION_TIMEOUT_SECONDS,
)


class SpeechTranscriptionError(Exception):
    pass


class SpeechTranscriptionService:
    def __init__(self) -> None:
        self.base_url = SPEECH_TRANSCRIPTION_BASE_URL.rstrip("/")
        self.model = SPEECH_TRANSCRIPTION_MODEL
        self.api_key = SPEECH_TRANSCRIPTION_API_KEY
        self.timeout = SPEECH_TRANSCRIPTION_TIMEOUT_SECONDS

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    async def transcribe(self, audio: bytes, filename: str, content_type: str | None = None) -> str:
        if not self.is_configured:
            raise SpeechTranscriptionError("后端未配置语音转写模型或 API Key。")
        if not audio:
            raise SpeechTranscriptionError("录音为空。")

        try:
            return await self._transcribe_with_responses(audio, filename, content_type)
        except SpeechTranscriptionError:
            raise
        except Exception as exc:
            raise SpeechTranscriptionError(f"语音转写失败：{exc}") from exc

    async def _transcribe_with_responses(self, audio: bytes, filename: str, content_type: str | None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        timeout = httpx.Timeout(self.timeout)
        media_type = content_type or self._content_type(filename)

        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            upload = await client.post(
                f"{self.base_url}/files",
                headers=headers,
                data={"purpose": "user_data"},
                files={"file": (filename or "speech.m4a", audio, media_type)},
            )
            if upload.status_code >= 400:
                raise SpeechTranscriptionError(self._provider_error(upload))
            file_payload = upload.json()
            file_id = str(file_payload.get("id") or "")
            if not file_id:
                raise SpeechTranscriptionError("语音文件上传后未返回 file_id。")

            await self._wait_until_processed(client, headers, file_id)

            response = await client.post(
                f"{self.base_url}/responses",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_audio", "file_id": file_id},
                                {
                                    "type": "input_text",
                                    "text": (
                                        "请逐字识别这段音频里的用户导购需求，只输出实际听到的转写文字，"
                                        "不要解释、总结或补充。若没有可识别的人声，只输出 __NO_SPEECH__。"
                                    ),
                                },
                            ],
                        }
                    ],
                },
            )
            if response.status_code >= 400:
                raise SpeechTranscriptionError(self._provider_error(response))
            text = self._normalize_transcript(self._extract_response_text(response.json()))
            if not text:
                raise SpeechTranscriptionError("语音转写结果为空，请靠近麦克风再试。")
            return text

    async def _wait_until_processed(self, client: httpx.AsyncClient, headers: dict[str, str], file_id: str) -> None:
        for _ in range(20):
            response = await client.get(f"{self.base_url}/files/{file_id}", headers=headers)
            if response.status_code >= 400:
                raise SpeechTranscriptionError(self._provider_error(response))
            status = str(response.json().get("status") or "")
            if status in {"active", "processed", "uploaded", "success", "succeeded"}:
                return
            if status in {"failed", "error"}:
                raise SpeechTranscriptionError("语音文件处理失败。")
            await asyncio.sleep(1)
        raise SpeechTranscriptionError("语音文件处理超时。")

    def _extract_response_text(self, payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        chunks: list[str] = []
        for item in payload.get("output", []) or []:
            for content in item.get("content", []) or []:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks).strip()

    def _normalize_transcript(self, text: str) -> str:
        normalized = text.strip()
        if not normalized:
            return ""
        lower = normalized.lower()
        no_speech_markers = (
            "__no_speech__",
            "未出现可识别",
            "没有可识别",
            "未识别到人声",
            "不存在对应可转写",
        )
        if any(marker in lower for marker in no_speech_markers):
            return ""
        return normalized

    def _provider_error(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:300] or f"HTTP {response.status_code}"
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            return self._sanitize_provider_message(str(error.get("message") or error.get("code") or payload))
        return self._sanitize_provider_message(str(payload))

    def _sanitize_provider_message(self, message: str) -> str:
        normalized = message.lower()
        if "safe experience mode" in normalized or "inference limit" in normalized:
            return (
                "后端语音转写模型已因当前账号的推理限额或 Safe Experience Mode 暂停。"
                "请在火山方舟控制台调整模型启用/限额，或配置可用的 SPEECH_TRANSCRIPTION_MODEL。"
            )
        return message[:300]

    def _content_type(self, filename: str) -> str:
        lower = filename.lower()
        if lower.endswith(".wav"):
            return "audio/wav"
        if lower.endswith(".mp3"):
            return "audio/mpeg"
        if lower.endswith(".pcm"):
            return "audio/L16"
        return "audio/mp4"
