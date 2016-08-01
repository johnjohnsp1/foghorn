import logging
from datetime import datetime,timedelta
from FoghornSettings import FoghornSettings
from twisted.internet import reactor, defer
from twisted.names import client, dns, error, server
from GreylistEntry import GreylistEntry
import dateutil.parser

class Foghorn(object):

  def __init__(self, settings):
    self.settings = settings
    self._peer_address = None
    self.logging = logging.getLogger('foghornd')
    self.whitelist = set(self.loadList(self.settings.WhitelistFile))
    self.blacklist = set(self.loadList(self.settings.BlacklistFile))
    self.greylist = {}
    for item in self.loadList(self.settings.GreylistFile):
      elements = [n.strip() for n in item.split(',')]
      entry = GreylistEntry(
          elements[0],
          dateutil.parser.parse(elements[1]),
          dateutil.parser.parse(elements[2])
          )
      self.greylist[elements[0]] = entry
    print self.greylist

  def saveState(self):
    print self.greylist
    self.writeList(self.settings.GreylistFile, self.greylist)

  @property
  def peer_address(self):
    return self._peer_address

  @peer_address.setter
  def peer_address(self, value):
    self._peer_address = value

  def listCheck(self, query):
    if query.type == dns.A:
      key = query.name.name
      if key in self.whitelist:
        self.logging.debug('Allowed by whitelist %s ref-by %s' % (key, self.peer_address))
        return True
      if key in self.blacklist:
        # Key is in blacklist
        self.logging.debug('Rejected by blacklist %s ref-by %s' % (key, self.peer_address))
        return False
      if self.greylist.has_key(key):
        # Key exists in greylist
        curtime = datetime.now()
        entry = self.greylist[key]
        if ((curtime - self.settings.GreyOut) >= entry.firstSeen):
          # Is the entry in the greyout period?
          if (curtime - self.settings.BlackOut <= entry.lastSeen):
            # Is the entry in the blackout period?
            self.logging.debug('Allowed by greylist %s ref-by %s' % (key, self.peer_address))
            return True
          else:
            self.logging.debug('Rejected/timeout by greylist %s ref-by %s' % (key, self.peer_address))
            entry.firstSeen()
            entry.lastSeen()
            return False
        else:
          self.logging.debug('Rejected/greyout by greylist %s ref-by %s' % (key, self.peer_address))
          return False
      else:
        # Entry not found in any list, so add it
        self.logging.debug('Rejected/notseen by greylist %s ref-by %s' % (key, self.peer_address))
        entry = GreylistEntry(key)
        self.greylist[key] = entry
        return False
    return False

  def buildResponse(self, query):
    name = query.name.name
    answer = dns.RRHeader(
        name=name,
        payload=dns.Record_A(address=b'%s' % (self.settings.Sinkhole)))
    answers = [answer]
    authority = []
    additional = []
    return answers, authority, additional

  def dataReceived(self, data):
    from pprint import pprint
    pprint (vars(data))

  def query(self, query, timeout=None):
    """
    Either return our fake response, or let it on through to the next resolver
    in the chain
    """
    if not self.listCheck(query):
      return defer.succeed(self.buildResponse(query))
    else:
      return defer.fail(error.DomainError())

  def loadList(self, filename):
    lines = []
    try:
      with open(filename, mode='r') as f:
        lines = [x.strip() for x in f.readlines()]
      return lines
    except IOError as e:
      print "%s" % e
    return []

  def writeList(self, filename, items):
    greylistEntries = False
    if len(items.keys()) > 0 and isinstance(items.itervalues().next(), GreylistEntry):
      greylistEntries = True
    else:
      # We're not going to support writing the other lists at the moment
      return False

    try:
      with open(filename, mode='w') as f:
        if greylistEntries:
          for item in items.itervalues():
            f.write("%s\n" % item)
      return True
    except IOError as e:
      print "%s" % e
    return False

