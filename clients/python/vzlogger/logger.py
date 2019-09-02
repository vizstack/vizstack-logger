import sys
import json
import time
from typing import Optional, Any, Tuple, Mapping, Sequence
from inspect import currentframe, getframeinfo
from types import FrameType
import socketio

from vizstack import assemble, Flow


# TODO: Locking, exceptions, msgs?
# logger.log(Msg("hello"))  --> string label
# logger.log(Msg("hello", 1))  --> named value
# logger.log(Msg("hello", 1, 2))  --> named tuple
# logger.log(Msg("Hello {} there {}", 1, 2))  --> formatted flow 
# logger.logx("Hello {} there {}", 1, 2)
# logger.infox(), logger.debugx(), logger.warnx(), logger.errorx()
# TODO: Optimize for speed (binary format like Protobuf)
# TODO: How to make logx aligned so printing, e.g. tabular format. Don't want to reimplement,
# so do View assembly on frontend.
# TODO: Want machine parsable format to be extractable.
# TODO: Level-based stdout? Tag-based std out?
# TODO: Key-value tags, not just key.
# TODO: Pass stack trace on exceptions (get from frame?).
# TODO: logger.infoc() closure using lambdas so won't execute expensive if log level too high

# SocketIO Client used to send log records to the server.
_client = None


class Connection:
    """
    Connects a new socket client on creation, and if used as a context disconnects it on exit.
    """
    def __init__(self, url):
        disconnect()
        global _client
        _client = socketio.Client()
        _client.connect(url, namespaces=['/program'])
        # See `disconnect()` for explanation.
        _client.on('ServerApproveDisconnect', _client.disconnect, namespace='/program')

    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        disconnect()


def connect(url: str = 'http://localhost:4000'):
    return Connection(url)


def disconnect():
    global _client
    if _client is not None:
        # Attempting to call `_client.disconnect()` directly here causes issues if the server
        # has not consumed every log message yet. Unconsumed log messages never get consumed,
        # and the disconnect will not be registered by the server, causing the program to hang.
        # Instead, we send a special message to the server; when it receives it, it sends a special
        # message back, at which point a handler on the client allows it to finally and safely 
        # disconnect.
        _client.emit('ProgramRequestDisconnect', namespace='/program')
        _client = None


# Log levels to distinguish messages of different severity.
DEBUG = 1
INFO = 2
WARN = 3
ERROR = 4

_level_to_name = { DEBUG: 'debug', INFO: 'info', WARN: 'warn', ERROR: 'error' }

class Logger:
    def __init__(self, name: str):
        self._name = name
        self._level = INFO
        self._enabled = True
        self._tags = []
        self._stdout = False
        self._stderr = False


    # ==============================================================================================
    # Logger configuration.

    def level(self, level: int = INFO) -> 'Logger':
        """Sets the least severe records to log."""
        self._level = level
        return self

    def enabled(self, enabled: bool = True) -> 'Logger':
        """Sets if logger should log any records."""
        self._enabled = enabled
        return self

    def tags(self, *tags: Sequence[str]) -> 'Logger':
        """Sets default tags to attach to log records."""
        self._tags = tags
        return self

    def stdout(self, enabled: bool = True) -> 'Logger':
        """Sets if log records should be echoed to stdout."""
        self._stdout = enabled
        return self
    
    def stderr(self, enabled: bool = True) -> 'Logger':
        """Sets if log records should be echoed to stderr."""
        self._stderr = enabled
        return self


    # ==============================================================================================
    # Logging functions.

    def debug(self, *objects, msg: str = "", tags: Sequence[str] = []):
        self._log(DEBUG, objects, msg, tags)

    def info(self, *objects, msg: str = "", tags: Sequence[str] = []):
        self._log(INFO, objects, msg, tags)

    def warn(self, *objects, msg: str = "", tags: Sequence[str] = []):
        self._log(WARN, objects, msg, tags)

    def error(self, *objects, msg: str = "", tags: Sequence[str] = []):
        self._log(ERROR, objects, msg, tags)


    # ==============================================================================================
    # Behind-the-scenes.

    def _log(self, level: int, objects: Sequence[Any], msg: str, tags: Sequence[str]):
        # No logging when globally or selectively disabled.
        if not self._enabled: return
        if level < self._level: return

        # Get information about code context.
        frame: Optional[FrameType] = currentframe()
        filepath, lineno, colno, funcname = "", -1, -1, ""
        try:
            if frame is not None:
                frame_info = getframeinfo(frame.f_back.f_back)
                filepath = frame_info.filename
                lineno = frame_info.lineno
                funcname = frame_info.function
                # Retrieving `colno` from bytecode is not currently possible.
        finally:
            del frame
        
        # Echo to standard out/err, if set.
        if self._stdout: print(*objects, file=sys.stdout)
        if self._stderr: print(*objects, file=sys.stderr)
        
        record: str = json.dumps({
            'timestamp': int(time.time() * 1000),  # Convert to milliseconds.
            'filePath': filepath,
            'lineNumber': lineno,
            'columnNumber': colno,
            'functionName': funcname,
            'loggerName': self._name,
            'level': _level_to_name[level],
            'tags': self._tags + tags,
            'view': assemble(objects[0] if len(objects) == 1 else Flow(*objects)),
        })

        # TODO: Deal with msg (format string, etc.)
        # TODO: Add error handling
        # _client is None:
        # socketio.exceptions.ConnectionError: Connection refused by the server
        if _client is not None:
            _client.emit('ProgramToServer', record, namespace='/program')

# Map from names to the Logger objects, so that Loggers can be recycled.
_loggers: Mapping[str, Logger] = dict()

def get_logger(name: str) -> Logger:
    """Returns the Logger associated with the given name, creating it if it does not already exist."""
    name = str(name)
    if name not in _loggers:
        _loggers[name] = Logger(name)
    logger = _loggers[name]
    return logger