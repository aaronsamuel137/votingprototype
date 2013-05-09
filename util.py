#
# Commonly used utility functions
#
#

import base64
import hmac
import random
import string
import time
import hashlib
import Cookie
import email.utils
import datetime

from google.appengine.api import memcache

FACEBOOK_APP_SECRET = "fe38d6dd8f118e20c99378f5151d28d1"

### Useful functions ###

def escape_html(s):
    s = s.replace("&", "&amp;")
    return cgi.escape(s, quote = True)



def make_cookie(n):
    return''.join(random.choice(string.letters + string.digits) for a in range(n))

# adjust to our time zone
def tz_adjust(entries):
    for e in entries:
        e.created = e.created + datetime.timedelta(hours = -6)


def set_cookie(response, name, value, domain=None, path="/", expires=None):
    """Generates and signs a cookie for the give name/value"""
    timestamp = str(int(time.time()))
    value = base64.b64encode(value)
    signature = cookie_signature(value, timestamp)
    cookie = Cookie.BaseCookie()
    cookie[name] = "|".join([value, timestamp, signature])
    cookie[name]["path"] = path
    if domain:
        cookie[name]["domain"] = domain
    if expires:
        cookie[name]["expires"] = email.utils.formatdate(
            expires, localtime=False, usegmt=True)
    response.headers.add("Set-Cookie", cookie.output()[12:])


def parse_cookie(value):
    """Parses and verifies a cookie value from set_cookie"""
    if not value:
        return None
    parts = value.split("|")
    if len(parts) != 3:
        return None
    if cookie_signature(parts[0], parts[1]) != parts[2]:
        logging.warning("Invalid cookie signature %r", value)
        return None
    timestamp = int(parts[1])
    if timestamp < time.time() - 30 * 86400:
        logging.warning("Expired cookie %r", value)
        return None
    try:
        return base64.b64decode(parts[0]).strip()
    except:
        return None


def cookie_signature(*parts):
    """Generates a cookie signature.

    We use the Facebook app secret since it is different for every app (so
    people using this example don't accidentally all use the same secret).
    """
    hash = hmac.new(FACEBOOK_APP_SECRET, digestmod=hashlib.sha1)
    for part in parts:
        hash.update(part)
    return hash.hexdigest()

def sort_likes():
    likes_by_user = memcache.get('likes')
    group_likes = {}
    if likes_by_user:
        for user in likes_by_user:
            for like in likes_by_user[user]:
                if like in group_likes:
                    group_likes[like] += 1
                else:
                    group_likes[like] = 1
    
        likes_by_number = {}
        max_key = 0
        for key, value in group_likes.iteritems():
            likes_by_number.setdefault(value, []).append(key)
            if value > max_key:
                max_key = value

    memcache.set('likes_by_number', likes_by_number)