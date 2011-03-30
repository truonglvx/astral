from elixir import ManyToOne, Entity
from elixir.events import after_insert
import json

from astral.models.base import BaseEntityMixin
from astral.models.event import Event
from astral.models.node import Node


class Ticket(BaseEntityMixin, Entity):
    source = ManyToOne('Node')
    destination = ManyToOne('Node')
    stream = ManyToOne('Stream')

    API_FIELDS = ['id', 'source_id', 'destination_id', 'stream_id']

    def __init__(self, source=None, destination=None, *args, **kwargs):
        source = source or Node.me()
        destination = destination or Node.me()
        super(Ticket, self).__init__(source=source,
                destination=destination, *args, **kwargs)

    def absolute_url(self):
        return '/stream/%s/ticket/%s' % (self.stream.id,
                self.destination.uuid)

    def to_dict(self):
        return {'source_uuid': self.source.uuid,
                'destination_uuid': self.destination.uuid,
                'stream': self.stream_id}

    @after_insert
    def emit_new_node_event(self):
        Event(message=json.dumps({'type': "ticket", 'data': self.to_dict()}))

    def __repr__(self):
        return u'<Ticket %s: %s from %s to %s>' % (
                self.id, self.stream, self.source, self.destination)
