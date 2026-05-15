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
        # ntfy supports max 3 action buttons
        base = self.callback_base_url.rstrip("/")
        idx = planned_set.index
        snooze = self.config.snooze_options_minutes[0]
        return "; ".join([
            f"http, Hotovo, {base}/callback/done, method=POST, clear=true",
            f"http, Snooze {snooze} min, {base}/callback/snooze?set={idx}&minutes={snooze}, method=POST, clear=true",
            f"http, Skip dnesek, {base}/callback/skip, method=POST, clear=true",
        ])

    def _post(self, message: str, headers: dict[str, str]) -> None:
        with httpx.Client(timeout=10) as client:
            client.post(
                self._topic_url(),
                content=message.encode("utf-8"),
                headers={k: v.encode("utf-8") for k, v in headers.items()},
            )

    def send_set_notification(self, planned_set: PlannedSet) -> None:
        reps = self._reps_label(planned_set)
        message = f"Čas na GTG set #{planned_set.index} z {planned_set.total}. {reps}."
        self._post(message, {
            "Title": "GTG Reminder",
            "Priority": "default",
            "Tags": "muscle",
            "Actions": self._actions_header(planned_set),
        })

    def send_calibration_reminder(self) -> None:
        self._post(
            "Čas na re-kalibraci! Otestuj svá maxima (OAP / OLS / Shyb) a zadej nové hodnoty.",
            {"Title": "GTG — nová kalibrace", "Priority": "high", "Tags": "muscle,stopwatch"},
        )

    def send_skip_confirmation(self) -> None:
        self._post(
            "Dnešní trénink byl přeskočen. Zítra jedeme dál.",
            {"Title": "GTG — dnešek přeskočen", "Priority": "low", "Tags": "muscle"},
        )
