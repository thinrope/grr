#!/usr/bin/env python
"""AFF4 RDFValue implementations.

This module contains all RDFValue implementations.

NOTE: This module uses the class registry to contain all implementations of
RDFValue class, regardless of where they are defined. To do this reliably, these
implementations must be imported _before_ the relevant classes are referenced
from this module.
"""


import abc
import calendar
import collections
import datetime
import functools
import posixpath
import re
import time
import zlib

import dateutil
from dateutil import parser

import logging

from grr.lib import registry
from grr.lib import utils
from grr.proto import jobs_pb2


# Factor to convert from seconds to microseconds
MICROSECONDS = 1000000

# Somewhere to keep all the late binding placeholders.
_LATE_BINDING_STORE = {}


def RegisterLateBindingCallback(target_name, callback, **kwargs):
  """Registers a callback to be invoked when the RDFValue named is declared."""
  _LATE_BINDING_STORE.setdefault(target_name, []).append((callback, kwargs))


class Error(Exception):
  """Errors generated by RDFValue parsers."""


class InitializeError(Error):
  """Raised when we can not initialize from this parameter."""


class DecodeError(InitializeError, ValueError):
  """Generated when we can not decode the data."""

  def __init__(self, msg):
    logging.debug(msg)
    super(DecodeError, self).__init__(msg)


class RDFValueMetaclass(registry.MetaclassRegistry):
  """A metaclass for managing semantic values."""

  def __init__(cls, name, bases, env_dict):  # pylint: disable=no-self-argument
    super(RDFValueMetaclass, cls).__init__(name, bases, env_dict)

    # Run and clear any late binding callbacks registered for this class.
    for callback, kwargs in _LATE_BINDING_STORE.pop(name, []):
      callback(target=cls, **kwargs)


class RDFValue(object):
  """Baseclass for values.

  RDFValues are serialized to and from the data store.
  """
  __metaclass__ = RDFValueMetaclass

  # This is how the attribute will be serialized to the data store. It must
  # indicate both the type emitted by SerializeToDataStore() and expected by
  # ParseFromDataStore()
  data_store_type = "bytes"

  # URL pointing to a help page about this value type.
  context_help_url = None

  _age = 0

  # Mark as dirty each time we modify this object.
  dirty = False

  # If this value was created as part of an AFF4 attribute, the attribute is
  # assigned here.
  attribute_instance = None

  def __init__(self, initializer=None, age=None):
    """Constructor must be able to take no args.

    Args:
      initializer: Optional parameter to construct from.
      age: The age of this entry as an RDFDatetime. If not provided, create a
           new instance.

    Raises:
      InitializeError: if we can not be initialized from this parameter.
    """
    # Default timestamp is now.
    if age is None:
      age = RDFDatetime(age=0)

    self._age = age

    # Allow an RDFValue to be initialized from an identical RDFValue.
    if initializer.__class__ == self.__class__:
      self.ParseFromString(initializer.SerializeToString())

    elif initializer is not None:
      self.ParseFromString(initializer)

  def Copy(self):
    """Make a new copy of this RDFValue."""
    return self.__class__(initializer=self.SerializeToString())

  def __copy__(self):
    return self.Copy()

  @property
  def age(self):
    if self._age.__class__ is not RDFDatetime:
      self._age = RDFDatetime(self._age, age=0)

    return self._age

  @age.setter
  def age(self, value):
    """When assigning to this attribute it must be an RDFDatetime."""
    self._age = RDFDatetime(value, age=0)

  def ParseFromDataStore(self, data_store_obj):
    """Serialize from an object read from the datastore."""
    return self.ParseFromString(data_store_obj)

  @abc.abstractmethod
  def ParseFromString(self, string):
    """Given a string, parse ourselves from it."""
    pass

  def SerializeToDataStore(self):
    """Serialize to a datastore compatible form."""
    return self.SerializeToString()

  @abc.abstractmethod
  def SerializeToString(self):
    """Serialize into a string which can be parsed using ParseFromString."""

  def __getstate__(self):
    """Support the pickle protocol."""
    # __pickled_rdfvalue is used to mark RDFValues pickled via the new way.
    return dict(__pickled_rdfvalue=True,
                age=int(self.age),
                data=self.SerializeToString())

  def __setstate__(self, data):
    """Support the pickle protocol."""
    if "__pickled_rdfvalue" in data:
      self.ParseFromString(data["data"])
      self.age = RDFDatetime(data["age"])
    else:
      self.__dict__ = data

  def AsProto(self):
    """Serialize into an RDFValue protobuf."""
    return jobs_pb2.EmbeddedRDFValue(age=int(self.age),
                                     name=self.__class__.__name__,
                                     data=self.SerializeToString())

  def __iter__(self):
    """This allows every RDFValue to be iterated over."""
    yield self

  def __hash__(self):
    return hash(self.SerializeToString())

  def Summary(self):
    """Return a summary representation of the object."""
    return str(self)

  @classmethod
  def Fields(cls):
    """Return a list of fields which can be queried from this value."""
    return []

  @staticmethod
  def ContainsMatch(attribute, filter_implemention, regex):
    return filter_implemention.PredicateContainsFilter(attribute, regex)

  # The operators this type supports in the query language
  operators = dict(contains=(1, "ContainsMatch"))


class RDFBytes(RDFValue):
  """An attribute which holds bytes."""
  data_store_type = "bytes"

  _value = ""

  def ParseFromString(self, string):
    # TODO(user): this needs some more test coverage, particularly around
    # submitting unicode strings and byte literals in the UI forms.
    if isinstance(string, unicode):
      self._value = utils.SmartStr(string)
    else:
      self._value = string

  def SerializeToString(self):
    return self._value

  def __str__(self):
    return utils.SmartStr(self._value)

  def __lt__(self, other):
    if isinstance(other, self.__class__):
      return self._value < other._value  # pylint: disable=protected-access
    else:
      return self._value < other

  def __gt__(self, other):
    if isinstance(other, self.__class__):
      return self._value > other._value  # pylint: disable=protected-access
    else:
      return self._value > other

  def __eq__(self, other):
    if isinstance(other, self.__class__):
      return self._value == other._value  # pylint: disable=protected-access
    else:
      return self._value == other

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(self._value)

  def __bool__(self):
    return bool(self._value)

  def __nonzero__(self):
    return bool(self._value)

  def __len__(self):
    return len(self._value)


class RDFZippedBytes(RDFBytes):
  """Zipped bytes sequence."""

  def Uncompress(self):
    if self:
      return zlib.decompress(self._value)
    else:
      return ""


class RDFString(RDFBytes):
  """Represent a simple string."""

  data_store_type = "string"

  _value = u""

  @staticmethod
  def Startswith(attribute, filter_implemention, string):
    return filter_implemention.PredicateContainsFilter(
        attribute, "^" + utils.EscapeRegex(string))

  operators = RDFValue.operators.copy()
  operators["matches"] = (1, "ContainsMatch")
  operators["="] = (1, "ContainsMatch")
  operators["startswith"] = (1, "Startswith")

  def format(self, *args, **kwargs):  # pylint: disable=invalid-name
    return self._value.format(*args, **kwargs)

  def __unicode__(self):
    return utils.SmartUnicode(self._value)

  def __getitem__(self, value):
    return self._value.__getitem__(value)

  def ParseFromString(self, string):
    # This handles the cases when we're initialized from Unicode strings.
    self._value = utils.SmartStr(string)

  def SerializeToString(self):
    return utils.SmartStr(self._value)

  def SerializeToDataStore(self):
    return utils.SmartUnicode(self._value)


class HashDigest(RDFBytes):
  """Binary hash digest with hex string representation."""

  data_store_type = "bytes"

  def __str__(self):
    return self._value.encode("hex")

  def __eq__(self, other):
    return (self._value == utils.SmartStr(other) or
            self._value.encode("hex") == other)

  def __ne__(self, other):
    return not self.__eq__(other)


@functools.total_ordering
class RDFInteger(RDFString):
  """Represent an integer."""

  data_store_type = "integer"

  @staticmethod
  def IsNumeric(value):
    return isinstance(value, (int, long, float, RDFInteger))

  def __init__(self, initializer=None, age=None):
    super(RDFInteger, self).__init__(initializer=initializer, age=age)
    if initializer is None:
      self._value = 0
    else:
      self.ParseFromString(initializer)

  def ParseFromString(self, string):
    self._value = 0
    if string:
      try:
        self._value = int(string)
      except TypeError as e:
        raise DecodeError(e)

  def SerializeToDataStore(self):
    """Use varint to store the integer."""
    return int(self._value)

  def Set(self, value):
    if isinstance(value, (long, int)):
      self._value = value
    else:
      self.ParseFromString(value)

  def __long__(self):
    return long(self._value)

  def __int__(self):
    return int(self._value)

  def __float__(self):
    return float(self._value)

  def __index__(self):
    return self._value

  def __eq__(self, other):
    return self._value == other

  def __lt__(self, other):
    return self._value < other

  def __and__(self, other):
    return self._value & other

  def __rand__(self, other):
    return self._value & other

  def __iand__(self, other):
    self._value &= other
    return self

  def __or__(self, other):
    return self._value | other

  def __ror__(self, other):
    return self._value | other

  def __ior__(self, other):
    self._value |= other
    return self

  def __add__(self, other):
    return self._value + other

  def __radd__(self, other):
    return self._value + other

  def __iadd__(self, other):
    self._value += other
    return self

  def __sub__(self, other):
    return self._value - other

  def __rsub__(self, other):
    return other - self._value

  def __isub__(self, other):
    self._value -= other
    return self

  def __mul__(self, other):
    return self._value * other

  def __rmul__(self, other):
    return self._value * other

  def __div__(self, other):
    return self._value / other

  def __rdiv__(self, other):
    return other / self._value

  @staticmethod
  def LessThan(attribute, filter_implemention, value):
    return filter_implemention.PredicateLessThanFilter(attribute, long(value))

  @staticmethod
  def GreaterThan(attribute, filter_implemention, value):
    return filter_implemention.PredicateGreaterThanFilter(
        attribute, long(value))

  @staticmethod
  def Equal(attribute, filter_implemention, value):
    return filter_implemention.PredicateNumericEqualFilter(
        attribute, long(value))

  operators = {"<": (1, "LessThan"),
               ">": (1, "GreaterThan"),
               "=": (1, "Equal")}


class RDFBool(RDFInteger):
  """Boolean value."""
  data_store_type = "unsigned_integer"


class RDFDatetime(RDFInteger):
  """A date and time internally stored in MICROSECONDS."""
  converter = MICROSECONDS
  data_store_type = "unsigned_integer"

  # A value of 0 means this object is not initialized.
  _value = 0

  def __init__(self, initializer=None, age=None):
    super(RDFDatetime, self).__init__(None, age)

    if isinstance(initializer, RDFInteger):
      self._value = initializer._value  # pylint: disable=protected-access

    elif isinstance(initializer, (int, long, float)):
      self._value = int(initializer)

    elif isinstance(initializer, datetime.datetime):
      seconds = calendar.timegm(initializer.utctimetuple())
      self._value = (seconds * self.converter) + initializer.microsecond

    elif isinstance(initializer, basestring):
      try:
        # Can be just a serialized integer.
        self._value = int(initializer)
      except ValueError:
        if initializer:
          # Try to parse from human readable string.
          self.ParseFromHumanReadable(initializer)

    elif initializer is not None:
      raise InitializeError("Unknown initializer for RDFDateTime: %s." %
                            type(initializer))

  def Now(self):
    self._value = int(time.time() * self.converter)
    return self

  def Format(self, fmt):
    """Return the value as a string formatted as per strftime semantics."""
    return time.strftime(fmt, time.gmtime(self._value / self.converter))

  def __str__(self):
    """Return the date in human readable (UTC)."""
    return self.Format("%Y-%m-%d %H:%M:%S")

  def __unicode__(self):
    return utils.SmartUnicode(str(self))

  def AsDatetime(self):
    """Return the time as a python datetime object."""
    return datetime.datetime.utcfromtimestamp(self._value / self.converter)

  def AsSecondsFromEpoch(self):
    return self._value / self.converter

  def AsMicroSecondsFromEpoch(self):
    return self._value

  def FromSecondsFromEpoch(self, value):
    self._value = value * self.converter

    return self

  def ParseFromHumanReadable(self, string, eoy=False):
    self._value = self._ParseFromHumanReadable(string, eoy=eoy)
    return self

  def __add__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      # Assume other is in seconds
      return self.__class__(self._value + other * self.converter)

    return NotImplemented

  def __iadd__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      # Assume other is in seconds
      self._value += other * self.converter
      return self

    return NotImplemented

  def __mul__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      return self.__class__(self._value * other)

    return NotImplemented

  def __rmul__(self, other):
    return self.__mul__(other)

  def __sub__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      # Assume other is in seconds
      return self.__class__(self._value - other * self.converter)

    if isinstance(other, RDFDatetime):
      return Duration(self.AsSecondsFromEpoch() - other.AsSecondsFromEpoch())

    return NotImplemented

  def __isub__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      # Assume other is in seconds
      self._value -= other * self.converter
      return self

    return NotImplemented

  @classmethod
  def _ParseFromHumanReadable(cls, string, eoy=False):
    """Parse a human readable string of a timestamp (in local time).

    Args:
      string: The string to parse.
      eoy: If True, sets the default value to the end of the year.
           Usually this method returns a timestamp where each field that is
           not present in the given string is filled with values from the date
           January 1st of the current year, midnight. Sometimes it makes more
           sense to compare against the end of a period so if eoy is set, the
           default values are copied from the 31st of December of the current
           year, 23:59h.

    Returns:
      The parsed timestamp.
    """
    # By default assume the time is given in UTC.
    if eoy:
      default = datetime.datetime(time.gmtime().tm_year, 12, 31, 23, 59,
                                  tzinfo=dateutil.tz.tzutc())
    else:
      default = datetime.datetime(time.gmtime().tm_year, 1, 1, 0, 0,
                                  tzinfo=dateutil.tz.tzutc())

    timestamp = parser.parse(string, default=default)

    return calendar.timegm(timestamp.utctimetuple()) * cls.converter

  @classmethod
  def LessThanEq(cls, attribute, filter_implemention, value):
    return filter_implemention.PredicateLesserEqualFilter(
        attribute, cls._ParseFromHumanReadable(value, eoy=True))

  @classmethod
  def LessThan(cls, attribute, filter_implemention, value):
    """For dates we want to recognize a variety of values."""
    return filter_implemention.PredicateLesserEqualFilter(
        attribute, cls._ParseFromHumanReadable(value))

  @classmethod
  def GreaterThanEq(cls, attribute, filter_implemention, value):
    return filter_implemention.PredicateGreaterEqualFilter(
        attribute, cls._ParseFromHumanReadable(value))

  @classmethod
  def GreaterThan(cls, attribute, filter_implemention, value):
    return filter_implemention.PredicateGreaterEqualFilter(
        attribute, cls._ParseFromHumanReadable(value, eoy=True))

  operators = {"<": (1, "LessThan"),
               ">": (1, "GreaterThan"),
               "<=": (1, "LessThanEq"),
               ">=": (1, "GreaterThanEq")}


class RDFDatetimeSeconds(RDFDatetime):
  """A DateTime class which is stored in whole seconds."""
  converter = 1


class Duration(RDFInteger):
  """Duration value stored in seconds internally."""
  data_store_type = "unsigned_integer"

  DIVIDERS = collections.OrderedDict((
      ("w", 60 * 60 * 24 * 7),
      ("d", 60 * 60 * 24),
      ("h", 60 * 60),
      ("m", 60),
      ("s", 1)))

  def __init__(self, initializer=None, age=None):
    super(Duration, self).__init__(None, age)
    if isinstance(initializer, Duration):
      self._value = initializer._value  # pylint: disable=protected-access
    elif isinstance(initializer, basestring):
      self.ParseFromHumanReadable(initializer)
    elif isinstance(initializer, (int, long, float)):
      self._value = initializer
    elif isinstance(initializer, RDFInteger):
      self._value = int(initializer)
    elif initializer is None:
      self._value = 0
    else:
      raise InitializeError("Unknown initializer for Duration: %s." %
                            type(initializer))

  def Validate(self, value, **_):
    self.ParseFromString(value)

  def ParseFromString(self, string):
    self.ParseFromHumanReadable(string)

  def SerializeToString(self):
    return str(self)

  @property
  def seconds(self):
    return self._value

  @property
  def microseconds(self):
    return self._value * 1000000

  def __str__(self):
    time_secs = self._value
    for label, divider in self.DIVIDERS.items():
      if time_secs % divider == 0:
        return "%d%s" % (time_secs / divider, label)

  def __unicode__(self):
    return utils.SmartUnicode(str(self))

  def __add__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      # Assume other is in seconds
      return self.__class__(self._value + other)

    return NotImplemented

  def __iadd__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      # Assume other is in seconds
      self._value += other
      return self

    return NotImplemented

  def __mul__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      return self.__class__(self._value * other)

    return NotImplemented

  def __rmul__(self, other):
    return self.__mul__(other)

  def __sub__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      # Assume other is in seconds
      return self.__class__(self._value - other)

    return NotImplemented

  def __isub__(self, other):
    if isinstance(other, (int, long, float, Duration)):
      # Assume other is in seconds
      self._value -= other
      return self

    return NotImplemented

  def __abs__(self):
    return Duration(abs(self._value))

  def Expiry(self, base_time=None):
    if base_time is None:
      base_time = RDFDatetime().Now()
    else:
      base_time = base_time.Copy()

    base_time_sec = base_time.AsSecondsFromEpoch()

    return base_time.FromSecondsFromEpoch(base_time_sec + self._value)

  def ParseFromHumanReadable(self, timestring):
    """Parse a human readable string of a duration.

    Args:
      timestring: The string to parse.
    """
    if not timestring:
      return

    orig_string = timestring

    multiplicator = 1

    if timestring[-1].isdigit():
      pass
    else:
      try:
        multiplicator = self.DIVIDERS[timestring[-1]]
      except KeyError:
        raise RuntimeError("Invalid duration multiplicator: '%s' ('%s')." %
                           (timestring[-1], orig_string))

      timestring = timestring[:-1]

    try:
      self._value = int(timestring) * multiplicator
    except ValueError:
      raise InitializeError("Could not parse expiration time '%s'." %
                            orig_string)


class ByteSize(RDFInteger):
  """A size for bytes allowing standard unit prefixes.

  We use the standard IEC 60027-2 A.2 and ISO/IEC 80000:
  Binary units (powers of 2): Ki, Mi, Gi
  SI units (powers of 10): k, m, g
  """
  data_store_type = "unsigned_integer"

  DIVIDERS = dict((
      ("", 1),
      ("k", 1000),
      ("m", 1000 ** 2),
      ("g", 1000 ** 3),
      ("ki", 1024),
      ("mi", 1024 ** 2),
      ("gi", 1024 ** 3),
  ))

  REGEX = re.compile("^([0-9.]+)([kmgi]*)b?$")

  def __init__(self, initializer=None, age=None):
    super(ByteSize, self).__init__(None, age)
    if isinstance(initializer, ByteSize):
      self._value = initializer._value  # pylint: disable=protected-access
    elif isinstance(initializer, basestring):
      self.ParseFromHumanReadable(initializer)
    elif isinstance(initializer, (int, long, float)):
      self._value = initializer
    elif isinstance(initializer, RDFInteger):
      self._value = int(initializer)
    elif initializer is None:
      self._value = 0
    else:
      raise InitializeError("Unknown initializer for ByteSize: %s." %
                            type(initializer))

  def __str__(self):
    size_token = ""
    if self._value > 1024 ** 3:
      size_token = "Gb"
      value = float(self._value) / 1024 ** 3
    elif self._value > 1024 ** 2:
      size_token = "Mb"
      value = float(self._value) / 1024 ** 2
    elif self._value > 1024:
      size_token = "Kb"
      value = float(self._value) / 1024
    else:
      return utils.SmartStr(self._value) + "b"

    return "%.1f%s" % (value, size_token)

  def ParseFromHumanReadable(self, string):
    """Parse a human readable string of a byte string.

    Args:
      string: The string to parse.

    Raises:
      DecodeError: If the string can not be parsed.
    """
    if not string:
      return None

    match = self.REGEX.match(string.strip().lower())
    if not match:
      raise DecodeError("Unknown specification for ByteSize %s" % string)

    multiplier = self.DIVIDERS.get(match.group(2))
    if not multiplier:
      raise DecodeError("Invalid multiplier %s" % match.group(2))

    # The value may be represented as a float, but if not dont lose accuracy.
    value = match.group(1)
    if "." in value:
      value = float(value)
    else:
      value = long(value)

    self._value = int(value * multiplier)


@functools.total_ordering
class RDFURN(RDFValue):
  """An object to abstract URL manipulation."""

  data_store_type = "string"

  # Careful when changing this value, this is hardcoded a few times in this
  # class for performance reasons.
  scheme = "aff4"

  def __init__(self, initializer=None, age=None):
    """Constructor.

    Args:
      initializer: A string or another RDFURN.
      age: The age of this entry.
    Raises:
      ValueError: if no urn passed
    """
    if isinstance(initializer, RDFURN):
      # Make a direct copy of the other object
      self._string_urn = initializer.Path()
      super(RDFURN, self).__init__(None, age)
      return

    if initializer is None:
      raise ValueError("URN cannot be None")

    super(RDFURN, self).__init__(initializer=initializer, age=age)

  def ParseFromString(self, initializer=None):
    """Create RDFRUN from string.

    Args:
      initializer: url string
    """
    # Strip off the aff4: prefix if necessary.
    if initializer.startswith("aff4:/"):
      initializer = initializer[5:]

    self._string_urn = utils.NormalizePath(initializer)

  def SerializeToString(self):
    return str(self)

  def SerializeToDataStore(self):
    return unicode(self)

  def __setstate__(self, data):
    """Support the pickle protocol."""
    RDFValue.__setstate__(self, data)
    # NOTE: This is done for backwards compatibility with
    # old pickled RDFURNs that got pickled via default pickling mechanism and
    # have 'aff4:/' pickled as part of _string_urn as a result.
    if self._string_urn.startswith("aff4:/"):
      self._string_urn = self._string_urn[5:]

  def Dirname(self):
    return posixpath.dirname(self._string_urn)

  def Basename(self):
    return posixpath.basename(self.Path())

  def Add(self, path, age=None):
    """Add a relative stem to the current value and return a new RDFURN.

    If urn is a fully qualified URN, replace the current value with it.

    Args:
      path: A string containing a relative path.
      age: The age of the object. If None set to current time.

    Returns:
       A new RDFURN that can be chained.

    Raises:
       ValueError: if the path component is not a string.
    """
    if not isinstance(path, basestring):
      raise ValueError("Only strings should be added to a URN.")

    result = self.Copy(age)
    result.Update(path=utils.JoinPath(self._string_urn, path))

    return result

  def Update(self, url=None, path=None):
    """Update one of the fields.

    Args:
       url: An optional string containing a URL.
       path: If the path for this URN should be updated.
    """
    if url:
      self.ParseFromString(url)
    if path:
      self._string_urn = path
    self.dirty = True

  def Copy(self, age=None):
    """Make a copy of ourselves."""
    if age is None:
      age = int(time.time() * MICROSECONDS)
    return self.__class__(self, age=age)

  def __str__(self):
    return utils.SmartStr("aff4:%s" % self._string_urn)

  def __unicode__(self):
    return utils.SmartUnicode(u"aff4:%s" % self._string_urn)

  def __eq__(self, other):
    if isinstance(other, basestring):
      other = self.__class__(other)

    elif other is None:
      return False

    elif not isinstance(other, RDFURN):
      return NotImplemented

    return self._string_urn == other.Path()

  def __ne__(self, other):
    return not self.__eq__(other)

  def __lt__(self, other):
    return self._string_urn < other

  def Path(self):
    """Return the path of the urn."""
    return self._string_urn

  def Split(self, count=None):
    """Returns all the path components.

    Args:
      count: If count is specified, the output will be exactly this many path
        components, possibly extended with the empty string. This is useful for
        tuple assignments without worrying about ValueErrors:

           namespace, path = urn.Split(2)

    Returns:
      A list of path components of this URN.
    """
    if count:
      result = filter(None, self._string_urn.split("/", count))
      while len(result) < count:
        result.append("")

      return result

    else:
      return filter(None, self._string_urn.split("/"))

  def RelativeName(self, volume):
    """Given a volume URN return the relative URN as a unicode string.

    We remove the volume prefix from our own.
    Args:
      volume: An RDFURN or fully qualified url string.

    Returns:
      A string of the url relative from the volume or None if our URN does not
      start with the volume prefix.
    """
    string_url = utils.SmartUnicode(self)
    volume_url = utils.SmartUnicode(volume)
    if string_url.startswith(volume_url):
      result = string_url[len(volume_url):]
      # This must always return a relative path so we strip leading "/"s. The
      # result is always a unicode string.
      return result.lstrip("/")

    return None

  def __repr__(self):
    return "<%s age=%s>" % (str(self), self.age)


class Subject(RDFURN):
  """A psuedo attribute representing the subject of an AFF4 object."""

  @staticmethod
  def ContainsMatch(unused_attribute, filter_implemention, regex):
    return filter_implemention.SubjectContainsFilter(regex)

  @staticmethod
  def Startswith(unused_attribute, filter_implemention, string):
    return filter_implemention.SubjectContainsFilter(
        "^" + utils.EscapeRegex(string))

  @staticmethod
  def HasAttribute(unused_attribute, filter_implemention, string):
    return filter_implemention.HasPredicateFilter(string)

  operators = dict(matches=(1, "ContainsMatch"),
                   contains=(1, "ContainsMatch"),
                   startswith=(1, "Startswith"),
                   has=(1, "HasAttribute"))

DEFAULT_FLOW_QUEUE = RDFURN("F")


class SessionID(RDFURN):
  """An rdfvalue object that represents a session_id."""

  def __init__(
      self, initializer=None, age=None, base="aff4:/flows",
      queue=DEFAULT_FLOW_QUEUE, flow_name=None):
    """Constructor.

    Args:
      initializer: A string or another RDFURN.
      age: The age of this entry.
      base: The base namespace this session id lives in.
      queue: The queue to use.
      flow_name: The name of this flow or its random id.
    Raises:
      InitializeError: The given URN cannot be converted to a SessionID.
    """
    if initializer is None:
      # This SessionID is being constructed from scratch.
      if flow_name is None:
        flow_name = utils.PRNG.GetULong()

      if isinstance(flow_name, int):
        initializer = RDFURN(base).Add("%s:%X" % (queue.Basename(), flow_name))
      else:
        initializer = RDFURN(base).Add("%s:%s" % (queue.Basename(), flow_name))
    elif isinstance(initializer, RDFURN):
      try:
        self.ValidateID(initializer.Basename())
      except ValueError as e:
        raise InitializeError("Invalid URN for SessionID: %s, %s" %
                              (initializer, e.message))
    super(SessionID, self).__init__(initializer=initializer, age=age)

  def Queue(self):
    return RDFURN(self.Basename().split(":")[0])

  def FlowName(self):
    return self.Basename().split(":")[1]

  def Add(self, path, age=None):
    # Adding to a SessionID results in a normal RDFURN.
    return RDFURN(self).Add(path, age=age)

  @classmethod
  def ValidateID(cls, id_str):
    # This check is weaker than it could be because we allow queues called
    # "DEBUG-user1" and IDs like "TransferStore"
    allowed_re = re.compile(r"^[-0-9a-zA-Z]+:[0-9a-zA-Z]+$")
    if not allowed_re.match(id_str):
      raise ValueError("Invalid SessionID")


class FlowSessionID(SessionID):

  # TODO(user): This is code to fix some legacy issues. Remove this when all
  # clients are built after Dec 2014.

  def ParseFromString(self, initializer=None):
    # Old clients sometimes send bare well known flow ids.
    if not utils.SmartStr(initializer).startswith("aff4"):
      initializer = "aff4:/flows/" + initializer
    super(FlowSessionID, self).ParseFromString(initializer)
