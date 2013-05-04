import json
from google.appengine.ext import db

class VoteRecord(db.Model):
    votes = db.TextProperty(required = True)
    event = db.StringProperty()
    created = db.DateTimeProperty(auto_now_add = True)

    def store(self):
        self.votes = json.dumps(self.votes)
        self.put()

    def unpack(self):
        return {'votes': json.loads(self.votes),
                'time': self.created.strftime('%c'),
                'event': self.event}