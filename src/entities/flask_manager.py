"""
FLASK manager
Marcelo Vogel
"""

# Flask
from flask import Flask, url_for, redirect, request, jsonify, session, Response

# from .rest_api import setup_rest_api

from flask_cors import CORS

import os, sys, tempfile, getopt, time, calendar

# from subprocess import getstatusoutput
# Date and time manipulation
# from datetime import datetime

from svom.auth import AuthManager
from svom.auth import requires_auth

# Logs
import logging

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
            self.app.run(host, port=port_num, debug=debug_flag, use_reloader=False)
        except Exception as exc:
            log.warning(f"Stopping because of an exception {exc}")
            raise RuntimeError(str(exc))
        finally:
            log.info(f"Stopping....")

    def get_app(self):
        """get the manager app"""
        return self.app
