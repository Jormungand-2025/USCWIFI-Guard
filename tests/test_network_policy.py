"""Network selection must not confuse VPN/VM interfaces with physical Ethernet."""
import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import campus_guard as guard


class NetworkPolicyTests(unittest.TestCase):
    def row(self, flags=5, oper=1, media=1, medium=14):
        row = guard.IfRow2()
        row.type = 6
        row.flags, row.oper_status, row.media_state = flags, oper, media
        row.physical_medium = medium
        return row

    def action(self, row, ips=None, gateway='192.0.2.1'):
        with patch.object(guard, 'adapters', return_value=[(7, 6, ips if ips is not None else ['192.0.2.2'], gateway)]), \
             patch.object(guard, 'interface_info', return_value=row):
            return guard.action_for([(1, 'USCWIFI')], guard.wired_active())

    def test_virtual_adapter_with_ip_and_gateway_does_not_block_campus(self):
        self.assertEqual(self.action(self.row(flags=0)), 'wireless')

    def test_disconnected_ethernet_with_retained_address_does_not_block(self):
        self.assertEqual(self.action(self.row(oper=2, media=2)), 'wireless')
        self.assertEqual(self.action(self.row(flags=21)), 'wireless')

    def test_wireless_driver_reporting_ethernet_type_does_not_block(self):
        for medium in (1, 9):
            self.assertEqual(self.action(self.row(medium=medium)), 'wireless')

    def test_actual_connected_ethernet_is_preserved(self):
        self.assertEqual(self.action(self.row()), 'other')

    def test_physical_interface_without_address_or_gateway_does_not_block(self):
        self.assertEqual(self.action(self.row(), ips=[]), 'wireless')
        self.assertEqual(self.action(self.row(), gateway='0.0.0.0'), 'wireless')

    def test_no_stale_interface_classification_after_index_reuse(self):
        with patch.object(guard, 'adapters', return_value=[(7, 6, ['192.0.2.2'], '192.0.2.1')]), \
             patch.object(guard, 'interface_info', side_effect=[self.row(), self.row(flags=0)]):
            self.assertTrue(guard.wired_active())
            self.assertFalse(guard.wired_active())

    def test_interface_query_failure_is_not_reported_as_other_network(self):
        with patch.object(guard, 'adapters', return_value=[(7, 6, ['192.0.2.2'], '192.0.2.1')]), \
             patch.object(guard, 'interface_info', side_effect=OSError(1168, 'missing')):
            with self.assertRaises(OSError):
                guard.wired_active()

    def test_connected_wifi_uses_api_regardless_of_ssid(self):
        self.assertEqual(guard.action_for([(1, 'hotspot')], False), 'wireless')
        self.assertEqual(guard.action_for([(1, 'USCWIFI'), (1, 'hotspot')], False), 'wireless')
        self.assertEqual(guard.action_for([(1, None)], False), 'wireless')

    def test_virtual_wireless_adapter_does_not_block_real_wifi(self):
        rows = [(7, 71, ['192.0.2.2'], '192.0.2.1'),
                (8, 71, ['192.0.2.3'], '192.0.2.1')]
        with patch.object(guard, 'adapters', return_value=rows), \
             patch.object(guard, 'interface_info', side_effect=[self.row(medium=9), self.row(flags=0, medium=9)]):
            self.assertEqual(guard.wireless_connections(), ((7, '192.0.2.2', '192.0.2.1'),))

    def test_windows_abi_complete_output_buffer(self):
        self.assertEqual(ctypes.sizeof(guard.IfRow2), 1352)
        self.assertEqual(guard.IfRow2.flags.offset, 1152)
        self.assertEqual(guard.IfRow2.oper_status.offset, 1156)
        self.assertEqual(guard.IfRow2.counters.offset, 1192)


if __name__ == '__main__':
    unittest.main()
