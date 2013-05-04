import hashlib
import hmac

def make_secure_val(s):
    hsh = hmac.new(CHANNEL_KEY, s).hexdigest()
    return "%s|%s" % (s, hsh)

def hash_str(s):
    return hmac.new(CHANNEL_KEY, s).hexdigest()

def check_secure_val(h):
    if h:
        val = h.split('|')[0]
        if h == make_secure_val(val):
            return val