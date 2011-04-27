from tornado.web import HTTPError

from astral.conf import settings
from astral.api.handlers.base import BaseHandler
from astral.api.client import TicketsAPI, NodesAPI, StreamsAPI
from astral.models import Ticket, Node, Stream, session
from astral.exceptions import NetworkError, NotFound

import logging
log = logging.getLogger(__name__)


class TicketsHandler(BaseHandler):
    @classmethod
    def _already_streaming(cls, stream, destination):
        return Ticket.get_by(stream=stream, destination=destination)

    @classmethod
    def _already_seeding(cls, ticket):
        return Node.me() in [ticket.destination, ticket.stream.source]

    @classmethod
    def _offer_ourselves(cls, stream, destination):
        # TODO base this on actual outgoing bandwidth
        if (Ticket.query.filter_by(source=Node.me()).count() >
                settings.OUTGOING_STREAM_LIMIT):
            log.info("Can't stream %s to %s, already at limit", stream,
                    destination)
            return HTTPError(412)

        ticket = Ticket.get_by(stream=stream, destination=Node.me())
        if ticket:
            new_ticket = Ticket(stream=stream, destination=destination,
                    source_port=ticket.source_port, hops=ticket.hops + 1)
            log.info("We are receiving %s and have room to forward -- "
                "created %s to potentially forward to %s", stream, new_ticket,
                destination)
            return new_ticket

    @classmethod
    def _already_ticketed(cls, unconfirmed_tickets, node):
        """Check if we already have an unconfirmed ticket for the node we're
        looking for.
        """
        for unconfirmed_ticket in unconfirmed_tickets:
            if unconfirmed_ticket.source == node:
                return True
        return False

    @classmethod
    def _request_stream_from_node(cls, stream, node, destination):
        try:
            ticket_data = TicketsAPI(node.uri()).create(stream.tickets_url(),
                    destination_uuid=destination.uuid)
        except NetworkError, e:
            log.info("Couldn't connect to %s to ask for %s -- deleting "
                    "the node from the database", node, stream)
            log.debug("Node returned: %s", e)
            node.delete()
        else:
            if ticket_data:
                source = Node.get_by(uuid=ticket_data['source'])
                if not source:
                    source_node_data = NodesAPI(node.uri()).get(
                            Node.absolute_url(source))
                    source = Node.from_dict(source_node_data)
                return Ticket(stream=stream, source=source,
                        source_port=ticket_data['source_port'],
                        destination=destination,
                        hops=ticket_data['hops'] + 1)

    @classmethod
    def _request_stream_from_watchers(cls, stream, destination,
            unconfirmed_tickets=None):
        tickets = []
        for ticket in Ticket.query.filter_by(stream=stream):
            if cls._already_seeding(ticket):
                return [ticket]
            else:
                if not cls._already_ticketed(unconfirmed_tickets,
                        ticket.destination):
                    tickets.append(cls._request_stream_from_node(stream,
                            ticket.destination, destination=destination))
        return filter(None, tickets)

    @classmethod
    def _request_stream_from_supernodes(cls, stream, destination,
            unconfirmed_tickets=None):
        tickets = []
        for supernode in Node.supernodes():
            if not cls._already_ticketed(unconfirmed_tickets, destination):
                tickets.append(cls._request_stream_from_node(stream,
                    supernode, destination))
        return filter(None, tickets)

    @classmethod
    def _request_stream_from_source(cls, stream, destination,
            unconfirmed_tickets=None):
        return [cls._request_stream_from_node(stream, stream.source,
            destination)]

    @classmethod
    def _request_stream(cls, stream, destination):
        unconfirmed_tickets = []
        for possible_source_method in [cls._request_stream_from_source,
                cls._request_stream_from_supernodes,
                cls._request_stream_from_watchers]:
            unconfirmed_tickets.extend(possible_source_method(stream,
                destination, unconfirmed_tickets=unconfirmed_tickets))
        return filter(None, unconfirmed_tickets)

    @classmethod
    def _request_stream_from_others(cls, stream, destination):
            unconfirmed_tickets = cls._request_stream(stream, destination)
            if not unconfirmed_tickets:
                raise HTTPError(412)
            unconfirmed_tickets = set(unconfirmed_tickets)
            for ticket in unconfirmed_tickets:
                ticket.source.update_rtt()
            log.debug("Received %d unconfirmed tickets: %s",
                    len(unconfirmed_tickets), unconfirmed_tickets)

            closest = min(unconfirmed_tickets, key=lambda t: t.source.rtt)
            log.debug("Closest ticket of the unconfirmed ones is %s", closest)
            TicketsAPI(closest.source.uri()).confirm(closest.absolute_url())
            closest.confirmed = True
            session.commit()
            for ticket in set(unconfirmed_tickets) - set([closest]):
                TicketsAPI(ticket.source.uri()).cancel(ticket.absolute_url())
                ticket.delete()
            session.commit()
            return closest

    @classmethod
    def handle_ticket_request(cls, stream, destination):
        log.debug("Trying to create a ticket to serve %s to %s",
                stream, destination)
        new_ticket = cls._already_streaming(stream, destination)
        if new_ticket:
            log.info("%s already has a ticket for %s: %s", destination,
                    stream, new_ticket)
            # In case we lost the tunnel, just make sure it exists
            new_ticket.queue_tunnel_creation()
            return new_ticket

        if stream.source != Node.me():
            new_ticket = cls._offer_ourselves(stream, destination)
            if new_ticket:
                log.info("We can stream %s to %s, created %s",
                    stream, destination, new_ticket)
                # In case we lost the tunnel, just make sure it exists
                new_ticket.queue_tunnel_creation()
            elif Node.me().supernode:
                log.info("Propagating the request for streaming %s to %s to "
                        "our other known nodes", stream, destination)
                new_ticket = cls._request_stream_from_others(stream,
                        destination)
        else:
            new_ticket = Ticket(stream=stream, destination=destination,
                confirmed=True)
            log.info("%s is the source of %s, created %s", destination,
                    stream, new_ticket)
        session.commit()
        return new_ticket

    def post(self, stream_slug):
        """Return whether or not this node can forward the stream requested to
        the requesting node, and start doing so if it can."""
        # TODO break this method up, it's gotten quite big and complicated
        stream = Stream.get_by(slug=stream_slug)
        if not stream:
            try:
                stream_data = StreamsAPI(settings.ASTRAL_WEBSERVER).find(
                        stream_slug)
            except NetworkError, e:
                log.warning("Can't connect to server: %s", e)
            except NotFound:
                raise HTTPError(404)
            else:
                stream = Stream.from_dict(stream_data)
        destination_uuid = self.get_json_argument('destination_uuid', '')
        if destination_uuid:
            destination = Node.get_by(uuid=destination_uuid)
            if not destination:
                raise HTTPError(404)
        else:
            destination = Node.me()

        new_ticket = self.handle_ticket_request(stream, destination)
        if isinstance(new_ticket, HTTPError):
            # TODO kind of weird....
            raise new_ticket
        self.redirect(new_ticket.absolute_url())

    def get(self):
        """Return a JSON list of all known tickets."""
        self.write({'tickets': [ticket.to_dict()
                for ticket in Ticket.query.all()]})
