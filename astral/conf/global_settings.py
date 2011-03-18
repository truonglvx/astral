import logging
import logging.handlers

DEBUG = True

LOG_FORMAT = '[%(asctime)s: %(levelname)s] %(message)s'
if DEBUG:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.WARN
LOG_COLOR = True

TORNADO_SETTINGS = {}
TORNADO_SETTINGS['debug'] = DEBUG
TORNADO_SETTINGS['xsrf_cookies'] = False
TORNADO_SETTINGS['port'] = 8000

if DEBUG:
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO
USE_SYSLOG = False

LOGGING_CONFIG = 'astral.conf.logconfig.initialize_logging'
LOGGING = {
   'loggers': {
        'astral': {},
    },
    'syslog_facility': logging.handlers.SysLogHandler.LOG_LOCAL0,
    'syslog_tag': "astral",
    'log_level': LOG_LEVEL,
    'use_syslog': USE_SYSLOG,
}

ASTRAL_WEBSERVER = "http://localhost:4567"
BOOTSTRAP_NODES = [{'ip_address': "127.0.0.1", 'port': 8001},]