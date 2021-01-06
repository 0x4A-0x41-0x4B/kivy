'''
Logger object
=============

The Kivy `Logger` class provides a singleton logger instance. This instance
exposes a standard Python
`logger <https://docs.python.org/3/library/logging.html>`_ object but adds
some convenient features.

All the standard logging levels are available : `trace`, `debug`, `info`,
`warning`, `error` and `critical`.

Example Usage
-------------

Use the `Logger` as you would a standard Python logger. ::

    from kivy.logger import Logger

    Logger.info('title: This is a info message.')
    Logger.debug('title: This is a debug message.')

    try:
        raise Exception('bleh')
    except Exception:
        Logger.exception('Something happened!')

The message passed to the logger is split into two parts separated by a colon
(:). The first part is used as a title and the second part is used as the
message. This way, you can "categorize" your messages easily. ::

    Logger.info('Application: This is a test')

    # will appear as

    [INFO   ] [Application ] This is a test

You can change the logging level at any time using the `setLevel` method. ::

    from kivy.logger import Logger, LOG_LEVELS

    Logger.setLevel(LOG_LEVELS["debug"])


Features
--------

Although you are free to use standard python loggers, the Kivy `Logger` offers
some solid benefits and useful features. These include:

* simplied usage (single instance, simple configuration, works by default)
* color-coded output
* output to `stdout` by default
* message categorization via colon separation
* access to log history even if logging is disabled
* built-in handling of various cross-platform considerations

Kivys' logger was designed to be used with kivy apps and makes logging from
Kivy apps more convenient.

Logger Configuration
--------------------

The Logger can be controlled via the Kivy configuration file::

    [kivy]
    log_level = info
    log_enable = 1
    log_dir = logs
    log_name = kivy_%y-%m-%d_%_.txt
    log_maxfiles = 100

More information about the allowed values are described in the
:mod:`kivy.config` module.

Logger History
--------------

Even if the logger is not enabled, you still have access to the last 100
messages::

    from kivy.logger import LoggerHistory

    print(LoggerHistory.history)

'''

import logging
import os
import sys
import copy
from random import randint
from functools import partial
import pathlib

import kivy


__all__ = (
    'Logger', 'LOG_LEVELS', 'COLORS', 'LoggerHistory', 'file_log_handler')

try:
    PermissionError
except NameError:  # Python 2
    PermissionError = OSError, IOError

Logger = None

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = list(range(8))

# These are the sequences need to get colored ouput
RESET_SEQ = "\033[0m"
COLOR_SEQ = "\033[1;%dm"
BOLD_SEQ = "\033[1m"

previous_stderr = sys.stderr


def formatter_message(message, use_color=True):
    if use_color:
        message = message.replace("$RESET", RESET_SEQ)
        message = message.replace("$BOLD", BOLD_SEQ)
    else:
        message = message.replace("$RESET", "").replace("$BOLD", "")
    return message


COLORS = {
    'TRACE': MAGENTA,
    'WARNING': YELLOW,
    'INFO': GREEN,
    'DEBUG': CYAN,
    'CRITICAL': RED,
    'ERROR': RED}

logging.TRACE = 9
LOG_LEVELS = {
    'trace': logging.TRACE,
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'warning': logging.WARNING,
    'error': logging.ERROR,
    'critical': logging.CRITICAL}


class FileHandler(logging.Handler):
    history = []
    filename = 'log.txt'
    fd = None
    log_dir = ''
    encoding = 'utf-8'

    def purge_logs(self):
        """Purge logs which exceed the maximum amount of log files,
        starting with the oldest creation timestamp (or edit-timestamp on Linux)
        """

        if not self.log_dir:
            return

        from kivy.config import Config
        maxfiles = Config.getint("kivy", "log_maxfiles")

        # Get path to log directory
        log_dir = pathlib.Path(self.log_dir)

        if maxfiles < 0:  # No log file limit set
            return

        Logger.info("Logger: Purge log fired. Processing...")

        # Get all files from log directory and corresponding creation timestamps
        files = [(item, item.stat().st_ctime)
                 for item in log_dir.iterdir() if item.is_file()]
        # Sort files by ascending timestamp
        files.sort(key=lambda x: x[1])

        for file, _ in files[:(-maxfiles or len(files))]:
            # More log files than allowed maximum,
            # delete files, starting with oldest creation timestamp
            # (or edit-timestamp on Linux)
            try:
                file.unlink()
            except PermissionError as e:
                Logger.info(f"Logger: Skipped file {file}, {repr(e)}")

        Logger.info("Logger: Purge finished!")

    def _configure(self, *largs, **kwargs):
        from time import strftime
        from kivy.config import Config
        log_dir = Config.get('kivy', 'log_dir')
        log_name = Config.get('kivy', 'log_name')

        _dir = kivy.kivy_home_dir
        if log_dir and os.path.isabs(log_dir):
            _dir = log_dir
        else:
            _dir = os.path.join(_dir, log_dir)
        if not os.path.exists(_dir):
            os.makedirs(_dir)
        self.log_dir = _dir

        pattern = log_name.replace('%_', '@@NUMBER@@')
        pattern = os.path.join(_dir, strftime(pattern))
        n = 0
        while True:
            filename = pattern.replace('@@NUMBER@@', str(n))
            if not os.path.exists(filename):
                break
            n += 1
            if n > 10000:  # prevent maybe flooding ?
                raise Exception('Too many logfile, remove them')

        if FileHandler.filename == filename and FileHandler.fd is not None:
            return

        FileHandler.filename = filename
        if FileHandler.fd not in (None, False):
            FileHandler.fd.close()
        FileHandler.fd = open(filename, 'w', encoding=FileHandler.encoding)
        Logger.info('Logger: Record log in %s' % filename)

    def _write_message(self, record):
        if FileHandler.fd in (None, False):
            return

        msg = self.format(record)
        stream = FileHandler.fd
        fs = "%s\n"
        stream.write('[%-7s] ' % record.levelname)
        stream.write(fs % msg)
        stream.flush()

    def emit(self, message):
        # during the startup, store the message in the history
        if Logger.logfile_activated is None:
            FileHandler.history += [message]
            return

        # startup done, if the logfile is not activated, avoid history.
        if Logger.logfile_activated is False:
            FileHandler.history = []
            return

        if FileHandler.fd is None:
            try:
                self._configure()
                from kivy.config import Config
                Config.add_callback(self._configure, 'kivy', 'log_dir')
                Config.add_callback(self._configure, 'kivy', 'log_name')
            except Exception:
                # deactivate filehandler...
                if FileHandler.fd not in (None, False):
                    FileHandler.fd.close()
                FileHandler.fd = False
                Logger.exception('Error while activating FileHandler logger')
                return
            while FileHandler.history:
                _message = FileHandler.history.pop()
                self._write_message(_message)

        self._write_message(message)


class LoggerHistory(logging.Handler):

    history = []

    def emit(self, message):
        LoggerHistory.history = [message] + LoggerHistory.history[:100]

    @classmethod
    def clear_history(cls):
        del cls.history[:]

    def flush(self):
        super(LoggerHistory, self).flush()
        self.clear_history()


class ColoredFormatter(logging.Formatter):

    def __init__(self, msg, use_color=True):
        logging.Formatter.__init__(self, msg)
        self.use_color = use_color

    def format(self, record):
        """Apply terminal color code to the record"""
        # deepcopy so we do not mess up the record for other formatters
        record = copy.deepcopy(record)
        try:
            msg = record.msg.split(':', 1)
            if len(msg) == 2:
                record.msg = '[%-12s]%s' % (msg[0], msg[1])
        except:
            pass
        levelname = record.levelname
        if record.levelno == logging.TRACE:
            levelname = 'TRACE'
            record.levelname = levelname
        if self.use_color and levelname in COLORS:
            levelname_color = (
                COLOR_SEQ % (30 + COLORS[levelname]) + levelname + RESET_SEQ)
            record.levelname = levelname_color
        return logging.Formatter.format(self, record)


class ConsoleHandler(logging.StreamHandler):

    def filter(self, record):
        try:
            msg = record.msg
            k = msg.split(':', 1)
            if k[0] == 'stderr' and len(k) == 2:
                previous_stderr.write(k[1] + '\n')
                return False
        except:
            pass
        return True


class LogFile(object):

    def __init__(self, channel, func):
        self.buffer = ''
        self.func = func
        self.channel = channel
        self.errors = ''

    def write(self, s):
        s = self.buffer + s
        self.flush()
        f = self.func
        channel = self.channel
        lines = s.split('\n')
        for l in lines[:-1]:
            f('%s: %s' % (channel, l))
        self.buffer = lines[-1]

    def flush(self):
        return

    def isatty(self):
        return False


def logger_config_update(section, key, value):
    if LOG_LEVELS.get(value) is None:
        raise AttributeError('Loglevel {0!r} doesn\'t exists'.format(value))
    Logger.setLevel(level=LOG_LEVELS.get(value))


#: Kivy default logger instance
Logger = logging.getLogger('kivy')
Logger.logfile_activated = None
Logger.trace = partial(Logger.log, logging.TRACE)

# set the Kivy logger as the default
logging.root = Logger

# add default kivy logger
Logger.addHandler(LoggerHistory())
file_log_handler = None
if 'KIVY_NO_FILELOG' not in os.environ:
    file_log_handler = FileHandler()
    Logger.addHandler(file_log_handler)

# Use the custom handler instead of streaming one.
if 'KIVY_NO_CONSOLELOG' not in os.environ:
    if hasattr(sys, '_kivy_logging_handler'):
        Logger.addHandler(getattr(sys, '_kivy_logging_handler'))
    else:
        use_color = (
            (
                os.environ.get("WT_SESSION") or
                os.environ.get("COLORTERM") == 'truecolor' or
                os.environ.get('PYCHARM_HOSTED') == '1' or
                os.environ.get('TERM') in (
                    'rxvt',
                    'rxvt-256color',
                    'rxvt-unicode',
                    'rxvt-unicode-256color',
                    'xterm',
                    'xterm-256color',
                )
            ) and os.environ.get('KIVY_BUILD') not in ('android', 'ios')
        )
        if not use_color:
            # No additional control characters will be inserted inside the
            # levelname field, 7 chars will fit "WARNING"
            color_fmt = formatter_message(
                '[%(levelname)-7s] %(message)s', use_color)
        else:
            # levelname field width need to take into account the length of the
            # color control codes (7+4 chars for bold+color, and reset)
            color_fmt = formatter_message(
                '[%(levelname)-18s] %(message)s', use_color)
        formatter = ColoredFormatter(color_fmt, use_color=use_color)
        console = ConsoleHandler()
        console.setFormatter(formatter)
        Logger.addHandler(console)

# install stderr handlers
sys.stderr = LogFile('stderr', Logger.warning)
