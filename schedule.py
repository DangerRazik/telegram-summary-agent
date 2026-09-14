"""Local schedule; no network requests or GUI dependencies."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from summary_modes import SUMMARY_MODES


@dataclass
class Schedule:
    enabled: bool = False
    mode: str = 'interval'
    minutes: int = 30
    daily_time: str = '09:00'
    send_saved: bool = False
    first_run_limit: int = 10
    next_run: float | None = None
    summary_detail: str = 'brief'
    delivery_target: str = 'saved'

    def validate(self):
        if self.delivery_target not in ('saved', 'bot'):
            raise ValueError('Выберите получателя сводок')
        if self.summary_detail not in SUMMARY_MODES:
            raise ValueError('Выберите подробность сводки')
        if type(self.enabled) is not bool or type(self.send_saved) is not bool or self.mode not in ('interval', 'daily'):
            raise ValueError('Неверный режим расписания')
        if type(self.minutes) is not int or not 1 <= self.minutes <= 10080:
            raise ValueError('Интервал должен быть от 1 до 10080 минут')
        if type(self.first_run_limit) is not int or not 1 <= self.first_run_limit <= 10000:
            raise ValueError('Количество постов должно быть от 1 до 10000')
        try:
            parsed = datetime.strptime(self.daily_time, '%H:%M')
        except (ValueError, TypeError) as error:
            raise ValueError('Укажите время в формате ЧЧ:ММ, например 09:00') from error
        self.daily_time = parsed.strftime('%H:%M')
        if self.next_run is not None:
            import math
            if not isinstance(self.next_run, (int, float)) or not math.isfinite(self.next_run):
                raise ValueError('Неверное время следующего запуска')

    def plan(self, now: float):
        self.validate()
        if not self.enabled:
            self.next_run = None
        elif self.mode == 'interval':
            self.next_run = now + self.minutes * 60
        else:
            hour, minute = map(int, self.daily_time.split(':'))
            local = datetime.fromtimestamp(now)
            target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= local:
                target += timedelta(days=1)
            self.next_run = target.timestamp()

    def due(self, now: float) -> bool:
        return self.enabled and self.next_run is not None and now >= self.next_run

    def save(self, path):
        self.validate()
        path = Path(path)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            value = cls(**json.loads(path.read_text(encoding='utf-8')))
            value.validate()
            if value.enabled and value.next_run is None:
                raise ValueError('Отсутствует время следующего запуска')
            return value
        except (ValueError, TypeError) as error:
            raise ValueError('Не удалось прочитать расписание. Автосбор выключен; сохраните настройки заново.') from error
