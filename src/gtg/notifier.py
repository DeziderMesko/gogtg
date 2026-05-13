from dataclasses import dataclass

import httpx

from gtg.models import Config, Exercise, PlannedSet


@dataclass
class Notifier:
    config: Config
    callback_base_url: str  # e.g. "https://abc123.trycloudflare.com"

    def _topic_url(self) -> str:
        return f"{self.config.ntfy_base_url}/{self.config.ntfy_topic}"

    def _reps_label(self, planned_set: PlannedSet) -> str:
        parts = []
        for ex in self.config.exercises:
            n = planned_set.reps.get(ex.id, 0)
            unit = "s" if ex.unit == "seconds" else "×"
            parts.append(f"{ex.name}: {n}{unit}")
        return " / ".join(parts)

    def _actions_header(self, planned_set: PlannedSet) -> str:
        base = self.callback_base_url.rstrip("/")
        idx = planned_set.index
        actions: list[str] = [
            f"http, ✅ Hotovo, {base}/callback/done?set={idx}, method=POST, clear=true",
        ]
        for minutes in self.config.snooze_options_minutes:
            actions.append(
                f"http, ⏸ Snooze {minutes} min, {base}/callback/snooze?set={idx}&minutes={minutes}, method=POST, clear=true"
            )
        actions.append(
            f"http, ❌ Skip dnešek, {base}/callback/skip, method=POST, clear=true"
        )
        return "; ".join(actions)

    def send_set_notification(self, planned_set: PlannedSet) -> None:
        reps = self._reps_label(planned_set)
        message = f"Čas na GTG set #{planned_set.index} z {planned_set.total}. {reps}."
        headers = {
            "Title": "GTG Reminder",
            "Priority": "default",
            "Tags": "muscle",
            "Actions": self._actions_header(planned_set),
        }
        with httpx.Client(timeout=10) as client:
            client.post(self._topic_url(), content=message.encode(), headers=headers)

    def send_calibration_reminder(self) -> None:
        message = "Čas na re-kalibraci! Otestuj svá maxima (OAP / OLS / Shyb) a zadej nové hodnoty."
        headers = {
            "Title": "GTG — nová kalibrace",
            "Priority": "high",
            "Tags": "muscle,stopwatch",
        }
        with httpx.Client(timeout=10) as client:
            client.post(self._topic_url(), content=message.encode(), headers=headers)

    def send_skip_confirmation(self) -> None:
        headers = {
            "Title": "GTG — dnešek přeskočen",
            "Priority": "low",
            "Tags": "muscle",
        }
        with httpx.Client(timeout=10) as client:
            client.post(
                self._topic_url(),
                content="Dnešní trénink byl přeskočen. Zítra jedeme dál.".encode(),
                headers=headers,
            )
