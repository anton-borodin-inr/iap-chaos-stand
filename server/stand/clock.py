"""Server time in the wire format: RFC 3339 UTC with milliseconds."""

from datetime import UTC, datetime, timedelta


def now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso(now())


def plus_seconds_iso(moment: datetime, seconds: int) -> str:
    return iso(moment + timedelta(seconds=seconds))
