#
# This is the db class for user suggestion
#
#
import datetime
from google.appengine.ext import db

class Input(db.Model):
    suggestion = db.StringProperty(required = True)
    user = db.StringProperty()
    event = db.StringProperty()
    created = db.DateTimeProperty(auto_now_add = True)
