#
# This is the db class for beta signups
#
#
import datetime
from google.appengine.ext import db

class BetaSignups(db.Model):
    email = db.StringProperty(required = True)
    name = db.StringProperty()
    created = db.DateTimeProperty(auto_now_add = True)
