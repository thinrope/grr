#!/usr/bin/env python
"""Tests for grr.lib.console_utils."""


from grr.lib import aff4
from grr.lib import console_utils
from grr.lib import flags
from grr.lib import test_lib


class ConsoleUtilsTest(test_lib.FlowTestsBaseclass):
  """Test the console utils library."""

  def testClientIdToHostname(self):
    client_ids = self.SetupClients(1)
    client1 = aff4.FACTORY.Open(client_ids[0], token=self.token, mode="rw")
    client1.Set(client1.Schema.HOSTNAME("test1"))
    client1.Flush()
    self.assertEqual(
        console_utils.ClientIdToHostname(client1.urn, token=self.token),
        "test1")

  def testFindClonedClients(self):
    client_ids = self.SetupClients(2)
    client = aff4.FACTORY.Open(client_ids[0], token=self.token, mode="rw")

    # A changing serial number is not enough indication for a cloned client.
    client.Set(client.Schema.HARDWARE_INFO(serial_number="aaa"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="aaa"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="aaa"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="bbb"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="bbb"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="bbb"))
    client.Close()

    res = console_utils.FindClonedClients(token=self.token)
    self.assertFalse(res)

    client = aff4.FACTORY.Open(client_ids[1], token=self.token, mode="rw")

    # Here, the serial number alternates back and forth between two values. This
    # is definitely two machines using the same client_id.
    client.Set(client.Schema.HARDWARE_INFO(serial_number="aaa"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="aaa"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="aaa"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="bbb"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="bbb"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="bbb"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="aaa"))
    client.Set(client.Schema.HARDWARE_INFO(serial_number="bbb"))
    client.Close()

    res = console_utils.FindClonedClients(token=self.token)
    self.assertEqual(len(res), 1)
    self.assertEqual(res[0].urn, client.urn)


class ConsoleUtilsTestLoader(test_lib.GRRTestLoader):
  base_class = ConsoleUtilsTest


def main(argv):
  # Run the full test suite
  test_lib.GrrTestProgram(argv=argv, testLoader=ConsoleUtilsTestLoader())

if __name__ == "__main__":
  flags.StartMain(main)
