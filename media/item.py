import logging
import threading
import os
import re
from io import BytesIO
import base64
import hashlib
import mutagen
from PIL import Image

import util
import variables as var

item_builders = {}
item_loaders = {}
item_id_generators = {}

def example_builder(bot, **kwargs):
    return BaseItem(bot)

def example_loader(bot, _dict):
    return BaseItem(bot, from_dict=_dict)

def example_id_generator(**kwargs):
    return ""

item_builders['base'] = example_builder
item_loaders['base'] = example_loader
item_id_generators['base'] = example_id_generator

class BaseItem:
    def __init__(self, bot, from_dict=None):
        self.bot = bot
        self.log = logging.getLogger("bot")
        self.type = "base"
        self.title = ""
        self.path = ""
        self.tags = []
        self.version = 0 # if version increase, wrapper will re-save this item

        if from_dict is None:
            self.id = ""
            self.ready = "pending" # pending - is_valid() -> validated - prepare() -> yes, failed
        else:
            self.id = from_dict['id']
            self.ready = from_dict['ready']

    def is_ready(self):
        return True if self.ready == "yes" else False

    def is_failed(self):
        return True if self.ready == "failed" else False

    def validate(self):
        return False

    def uri(self):
        raise

    def prepare(self):
        return True

    def add_tag(self, tag):
        if tag not in self.tags:
            self.tags.append(tag)
            self.version += 1

    def remove_tag(self, tag):
        if tag not in self.tags:
            self.tags.remove(tag)
            self.version += 1

    def format_song_string(self, user):
        return self.id

    def format_current_playing(self, user):
        return self.id

    def format_short_string(self):
        return self.title

    def format_debug_string(self):
        return self.id

    def display_type(self):
        return ""

    def send_client_message(self, msg):
        self.bot.send_msg(msg)

    def to_dict(self):
        return {"type" : "base", "id": self.id, "ready": self.ready, "path": self.path, "tags": self.tags}

