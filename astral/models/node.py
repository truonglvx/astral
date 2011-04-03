from elixir import (Field, Unicode, Integer, Entity, Boolean,
        using_table_options, ManyToOne)
from elixir.events import after_insert
from sqlalchemy import UniqueConstraint
import uuid
import socket
import json

from astral.exceptions import NetworkError
from astral.models.base import BaseEntityMixin
from astral.models.event import Event
from astral.api.client import NodeAPI
from astral.conf import settings

import logging
log = logging.getLogger(__name__)


class Node(BaseEntityMixin, Entity):
    ip_address = Field(Unicode(15))
    uuid = Field(Integer, nullable=False, unique=True, primary_key=True)
    port = Field(Integer)
    supernode = Field(Boolean, default=False)
    primary_supernode = ManyToOne('Node')
    rtt = Field(Integer)
    upstream = Field(Integer)
    downstream = Field(Integer)

    using_table_options(UniqueConstraint('ip_address', 'port'))

    API_FIELDS = ['ip_address', 'uuid', 'port', 'supernode',]
    RTT_STEP = 0.2
    BANDWIDTH_STEP = 0.2

    @classmethod
    def from_dict(cls, data):
        node = Node.get_by(uuid=data['uuid'])
        if not node:
            node = cls(ip_address=data['ip_address'], uuid=data['uuid'],
                    port=data['port'])
        if 'supernode' in data:
            node.supernode = data['supernode']
        if 'primary_supernode_uuid' in data:
            node.primary_supernode = Node.get_by(
                    uuid=data['primary_supernode_uuid'])
        return node

    def update_rtt(self):
        sampled_rtt = NodeAPI(self.uri()).ping()
        self.rtt = self._weighted_average(self.rtt, self.RTT_STEP, sampled_rtt)
        return self.rtt

    def update_downstream(self):
        byte_count, transfer_time = NodeAPI(self.uri()).downstream_check()
        self.downstream = self._weighted_average(self.downstream,
                self.BANDWIDTH_STEP, byte_count / transfer_time)
        return self.downstream

    def update_upstream(self):
        byte_count, transfer_time = NodeAPI(self.uri()).upstream_check()
        self.upstream = self._weighted_average(self.upstream,
                self.BANDWIDTH_STEP, byte_count / transfer_time)
        return self.upstream

    def _weighted_average(self, estimated, step, sample):
        if not estimated:
            return sample
        return (1 - step) * estimated + step * sample

    @classmethod
    def update_supernode_rtt(cls):
        for supernode in cls.query.filter_by(supernode=True):
            try:
                supernode.update_rtt()
            except NetworkError:
                supernode.delete()

    @classmethod
    def supernodes(cls):
        return cls.query.filter_by(supernode=True)

    @classmethod
    def closest_supernode(cls):
        closest = cls.supernodes().order_by('rtt').first()
        if not closest:
            log.warn("No supernodes in the database")
        return closest

    @classmethod
    def me(cls, uuid_override=None):
        node = Node.get_by(uuid=uuid_override or uuid.getnode())
        if not node:
            node = Node()
            node.uuid = uuid_override or uuid.getnode()
            log.info("Using %s for this node's unique ID", node.uuid)

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect((settings.ASTRAL_WEBSERVER, 80))
            except socket.gaierror, e:
                log.debug("Couldn't connect to the Astral webserver: %s", e)
                node.ip_address = '127.0.0.1'
            else:
                node.ip_address = s.getsockname()
            log.info("Using %s for this node's IP address",
                    node.ip_address)

            node.port = settings.PORT
            log.info("Using %s for this node's API port", node.port)
        return node

    def uri(self):
        return "http://%s:%s" % (self.ip_address, self.port)

    def absolute_url(self):
        return '/node/%s' % self.uuid

    def to_dict(self):
        data = super(Node, self).to_dict()
        if self.primary_supernode:
            data['primary_supernode_uuid'] = self.primary_supernode.uuid
        return data

    @after_insert
    def emit_new_node_event(self):
        Event(message=json.dumps({'type': "node", 'data': self.to_dict()}))

    def __repr__(self):
        return u'<Node %s:%s>' % (self.ip_address, self.port)
