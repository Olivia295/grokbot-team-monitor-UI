"""The client's name before 0.6. Import ``bot_monitor`` in new code; this keeps old imports working."""

try:  # installed package
    from .bot_monitor import BotMonitor
except ImportError:  # copied next to your code
    from bot_monitor import BotMonitor

BotOffice = BotMonitor

__all__ = ["BotMonitor", "BotOffice"]
