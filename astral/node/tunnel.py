import threading
import asyncore
import time

from astral.net.tunnel import Tunnel
from astral.models import Ticket, Node, session
from astral.models.ticket import TUNNEL_QUEUE

import logging
log = logging.getLogger(__name__)


class TunnelControlThread(threading.Thread):
    def __init__(self):
        super(TunnelControlThread, self).__init__()
        self.daemon = True
        self.tunnels = dict()

    def run(self):
        while True:
            ticket_id = TUNNEL_QUEUE.get()
            ticket = Ticket.get_by(id=ticket_id)
            log.debug("Found %s in tunnel queue", ticket)
            if ticket.source == Node.me():
                source_ip = "127.0.0.1"
            else:
                source_ip = ticket.source.ip_address
            port = self.create_tunnel(ticket.id, source_ip, ticket.source_port)
            TUNNEL_QUEUE.task_done()
            if not ticket.destination_port:
                ticket.destination_port = port
                session.commit()
            self.close_expired_tunnels()

    def create_tunnel(self, ticket_id, source_ip, source_port):
        tunnel = self.tunnels.get(ticket_id)
        if not tunnel:
            tunnel = Tunnel(source_ip, source_port)
            log.info("Starting %s", tunnel)
            self.tunnels[ticket_id] = tunnel
        return tunnel.bind_port

    def destroy_tunnel(self, ticket_id):
        tunnel = self.tunnels.pop(ticket_id)
        log.info("Stopping %s", tunnel)
        tunnel.handle_close()

    def close_expired_tunnels(self):
        for ticket_id, tunnel in self.tunnels.items():
            if not Ticket.get_by(id=ticket_id):
                self.destroy_tunnel(ticket_id)


class TunnelLoopThread(threading.Thread):
    def __init__(self):
        super(TunnelLoopThread, self).__init__()
        self.daemon = True

    def run(self):
        # TODO this is going to just spin when we first start up and have no
        # existing tunnels. we talked about having everyone with the rtmp server
        # access that not directly, but through a tunnel, so we could use that
        # to control the on/off. still need that?
        while True:
            asyncore.loop()
            # TODO this is a little workaround to make sure we don't eat up 100%
            # CPU at the moment
            time.sleep(1)
