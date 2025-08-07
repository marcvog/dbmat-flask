"""
FLASK manager
Marcelo Vogel
"""

# Logs
import logging

# Flask
from flask import Flask
from flask_cors import CORS
from svom.auth import AuthManager

log = logging.getLogger(__name__)


class FlaskManager:
    """
    Flask manager class
    """

    def __init__(self, properties=None):
        self.app = Flask(__name__)
        CORS(self.app)
        AuthManager(self.app)

    def config(self, properties):
        self.app.config["MAX_CONTENT_LENGTH"] = 1000 * 1024 * 1024
        if properties is None:
            log.info("Use default properties")
            return
        if "MAX_CONTENT_LENGTH" in properties:
            self.app.config["MAX_CONTENT_LENGTH"] = properties["MAX_CONTENT_LENGTH"]

    def run(self, host, port_num, debug_flag):
        """runs the manager app"""
        try:
            self.app.run(
                host,
                port=port_num,
                debug=debug_flag,
                use_reloader=False,
            )
        except Exception as exc:
            log.warning(f"Stopping because of an exception {exc}")
            raise RuntimeError(str(exc))
        finally:
            log.info("Stopping....")

    def get_app(self):
        """get the manager app"""
        return self.app
