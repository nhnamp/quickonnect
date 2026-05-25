"""Subtitle broadcaster.

Receives STT transcripts and optionally translates them via
LibreTranslate, then broadcasts SUBTITLE packets to all room
participants.

Translation is enabled when LIBRETRANSLATE_URL is set as an
environment variable (e.g. http://localhost:5000).
"""

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Callable

from shared.constants import PacketType

logger = logging.getLogger(__name__)


class SubtitleBroadcaster:
    """Broadcasts subtitle packets to every client in a room.

    Parameters
    ----------
    room_code:
        The room this broadcaster belongs to.
    get_clients_fn:
        Callable returning ``dict[int, handler]`` — the current room members.
    """

    def __init__(
        self,
        room_code: str,
        get_clients_fn: Callable[[], dict],
    ) -> None:
        self._room_code = room_code
        self._get_clients = get_clients_fn

        self._translate_url: str = os.environ.get("LIBRETRANSLATE_URL", "").rstrip("/")
        self._target_lang: str = os.environ.get("SUBTITLE_TARGET_LANG", "")

        if self._translate_url:
            logger.info(
                "Room %s: translation enabled (%s -> %s)",
                room_code,
                "auto",
                self._target_lang or "auto",
            )
        else:
            logger.debug("Room %s: translation disabled (no LIBRETRANSLATE_URL)", room_code)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def broadcast_transcript(
        self, user_id: int, username: str, text: str,
    ) -> None:
        """Optionally translate *text* and broadcast a SUBTITLE packet.

        The packet is sent to every client currently in the room.
        """
        translated_text = ""
        source_lang = "auto"
        target_lang = self._target_lang

        if self._translate_url and self._target_lang:
            translated_text, source_lang = self._translate(text)

        payload = {
            "room_code": self._room_code,
            "speaker_user_id": user_id,
            "speaker_username": username,
            "text": text,
            "translated_text": translated_text,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }

        clients = self._get_clients()
        for recipient_uid, handler in clients.items():
            try:
                handler.send(PacketType.SUBTITLE, payload)
            except Exception:
                logger.debug(
                    "Room %s: failed to send subtitle to uid=%d",
                    self._room_code, recipient_uid,
                )

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def _translate(self, text: str) -> tuple[str, str]:
        """Translate *text* via LibreTranslate.

        Returns ``(translated_text, detected_source_lang)``.  On any
        failure returns ``("", "auto")`` so the caller can still broadcast
        the original text.
        """
        url = f"{self._translate_url}/translate"
        body = json.dumps({
            "q": text,
            "source": "auto",
            "target": self._target_lang,
            "format": "text",
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated = data.get("translatedText", "")
                src_lang = data.get("detectedLanguage", {}).get("language", "auto")
                return translated, src_lang
        except urllib.error.HTTPError as exc:
            logger.warning(
                "Room %s: LibreTranslate HTTP %d: %s",
                self._room_code, exc.code, exc.reason,
            )
        except urllib.error.URLError as exc:
            logger.warning(
                "Room %s: LibreTranslate unreachable: %s",
                self._room_code, exc.reason,
            )
        except Exception:
            logger.exception("Room %s: translation error", self._room_code)

        return "", "auto"
